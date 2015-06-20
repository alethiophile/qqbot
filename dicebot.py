#!/usr/bin/python3
"""A bot that does die-rolling. If loaded as a script to irssi, it acts as
appropriate; in that context, it doesn't do any joining or connecting, but
leaves that to the irssi user to do manually. If run, it should do the right
thing using Python's irclib. It can also be loaded as a module to the willie bot
framework. This is the current recommended usage, due to persistent bugs in
irclib.

"""

# Includes for use as irssi script
try:
    import irssi
except ImportError:
    irssi = None

# Includes for use as a standalone bot
try:
    from irc.bot import SingleServerIRCBot
    import irc.client
except ImportError:
    pass
import re, random, sys, time
import argparse, signal, itertools

# Includes for use as willie module

import willie

random = random.SystemRandom()

# Regex for non-repeating, non-exploding dice
dice_re = re.compile(r"\[(?P<ndice>\d+)?d(?P<sides>\d+)((\+(?P<plus>\d+))|(\-(?P<minus>\d+)))?\]")
# Regex for dice which can explode or repeat rolls
exdice_re = re.compile(r"(?P<ndice>(\d+|\[.+?\]))?d(?P<sides>(\d+|\[.+?\]|\w+?))((\+(?P<plus>(\d+|\[.+?\])))|(\-(?P<minus>(\d+|\[.+?\]))))?(ex(?P<expl>\d+))?(x(?P<nrolls>(\d+|\[.+?\])))?$")

#nick = "qqdice"

def do_nxroll(instr):
    o = dice_re.match(instr)
    if o == None:
        #print("No match for nxr {}".format(instr))
        return None
    nd = int(o.group('ndice') or '1')
    si = int(o.group('sides'))
    pl = int(o.group('plus') or o.group('minus') or '0')
    if o.group('minus'):
        pl = -pl
    rolls = [random.randrange(0,si)+1 for i in range(0,nd)]
    t = sum(rolls) + pl
    return t

def get_nvalue(ins):
    if re.match(r"^\d+$", ins):
        rv = int(ins)
    else:
        rv = do_nxroll(ins)
    return rv

class YouIdiotException(Exception):
    pass

def do_roll(instr):
    rvs = []
    o = exdice_re.match(instr)
    if o == None:
        #print("No match for {}".format(instr))
        return
    nd = get_nvalue(o.group('ndice') or '1')
    dl = False
    ds = o.group('sides')
    if not re.match(r"^(\d+|\[.+\])$", ds):
        si = len(ds)
        dl = True
    else:
        si = get_nvalue(ds)
    pl = get_nvalue(o.group('plus') or o.group('minus') or '0')
    if o.group('minus'):
        pl = -pl
    ex = get_nvalue(o.group('expl') or '0')
    if si == 1:
        ex = 0
    nr = get_nvalue(o.group('nrolls') or '1')
    if nr > 1000 or nd > 1000:
        raise YouIdiotException()
    for i in range(0, nr):
        rolls = [random.randrange(0,si)+1 for i in range(0,nd)]
        # this does exploding dice properly, since it checks the dice added on at the end of the loop
        for i in rolls:
            if i == ex:
                rolls += [random.randrange(0,si)+1]
        t = sum(rolls) + pl
        rolls.sort(reverse=True)
        rstr = [str(i) for i in rolls]
        if pl > 0:
            ps = " + {}".format(pl)
        elif pl < 0:
            ps = " - {}".format(-pl)
        else:
            ps = ""
        if ex != 0:
            es = " ({} exploded)".format(len(rolls) - nd)
        else:
            es = ""
        if dl:
            t = ds[(t-nd)%si]
            rstr = [ds[i-1] for i in rolls]
        rvs.append("{} = [{}]{}{}".format(t, ','.join(rstr), ps, es))
    if dl:
        si = ds
    return nd, si, rvs

helpstr = """Dicebot roll syntax:
> roll d<sides>
Rolls one die with <sides> sides
> roll <n>d<sides>
Rolls <n> dice with <sides> sides, gives individual rolls and the total
> roll <n>d<sides>+<mod>
Adds <mod> to the total (for a negative, do e.g. roll 2d10+-2)
> roll <n>d<sides>ex<trigger>
For any die which comes up as <trigger>, roll one more die and add it to the total (exploding dice)
> roll <n>d<sides>x<num>
For any roll above, repeats the whole thing <num> times and yields all results
All the modifiers can be used with each other. In addition, any numeric value can be replaced with another die specification in square brackets, e.g. [2d6]d6 to roll a number of d6 determined by the roll of 2 d6s."""

suits = ['♦', '♣', '♥', '♠']

ranks = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']

cards = [j + i for i, j in itertools.product(suits, ranks)]

def draw_cards(n):
    return random.sample(cards, n)

# Stuff for standalone bot

class AlarmException(Exception):
    pass

def alarm_handler(sig, thing):
    raise AlarmException()

class Dicebot(SingleServerIRCBot):
    def __init__(self, channel, nick, server, nspw=None, port=6667):
        SingleServerIRCBot.__init__(self, [(server, port)], nick, nick)
        self.channel = channel
        self.nspw = nspw
        signal.signal(signal.SIGALRM, alarm_handler)

    def on_nicknameinuse(self, c, e):
        c.nick(c.get_nickname() + "_")
        
    def on_welcome(self, c, e):
        c.join(self.channel)
        if self.nspw:
            c.privmsg("NickServ", "identify {}".format(self.nspw))
        time.sleep(2)
        c.mode(c.get_nickname(), "-o")

    def roll_to(self, event):
        nick = event.source.split('!')[0]
        if event.type == 'pubmsg':
            sendto = event.target
        elif event.type == 'privmsg':
            sendto = nick
        if nick == "Babelbot":
            nick = "Babebot"
        msg = event.arguments[0]
        o = re.match("[Rr]oll (\S+)", msg)
        if o:
            roll = o.group(1)
            if roll == "help":
                for i in helpstr.splitlines():
                    self.connection.privmsg(nick, i)
            else:
                try:
                    signal.alarm(10)
                    nd, si, rs = do_roll(roll)
                    self.connection.privmsg(sendto, "{} rolled {}d{}: {}".format(nick, nd, si, ", ".join(rs)))
                    signal.alarm(0)
                except (MemoryError, irc.client.MessageTooLong, AlarmException):
                    self.connection.privmsg(sendto, "Stop being an asshole.")
                    signal.alarm(0)
                    return
                except: # if roll failed
                    signal.alarm(0)
                    return
        elif msg[:6].lower() == 'choose':
            choices = [i.strip() for i in msg[7:].split(',')]
            if len(choices) == 0:
                return
            choice = random.choice(choices)
            choice = re.sub("(babe)l(bot)", lambda x: x.group(1) + x.group(2), choice, flags=re.I)
            self.connection.privmsg(sendto, "{} selects: {}".format(nick, choice))
            

    def on_privmsg(self, c, e):
        self.roll_to(e)

    def on_pubmsg(self, c, e):
        self.roll_to(e)

def main():
    parser = argparse.ArgumentParser(description='IRC bot to roll dice')
    parser.add_argument("server", help="IRC server to connect to")
    parser.add_argument("channel", help="Channel to join")
    parser.add_argument("nick", help="Nickname to use")
    parser.add_argument("-p", "--password", help="NickServ registration password", default=None)
    args = parser.parse_args()

    s = args.server.split(':', 1)
    server = s[0]
    try:
        port = int(s[1])
    except IndexError:
        port = 6667
    bot = Dicebot(args.channel, args.nick, server, args.password, port)
    while True:
        try:
            bot.start()
        except UnicodeDecodeError:
            pass

# Stuff for IRSSI scripting (now obsolete)

def sendhelp(server, to):
    for i in helpstr.splitlines():
        server.command("msg {} {}".format(to, i))

def rdto(server, to, msg, rn):
    o = re.match("[Rr]oll (\S+)", msg)
    if o:
        roll = o.group(1)
        if roll == "help":
            sendhelp(server, rn)
        else:
            nd, si, rs = do_roll(roll)
            server.command("msg {} {}".format(to, "{} rolled {}d{}: {}".format(rn, nd, si, ", ".join(rs))))

def query(server, message, rnick, address):
    rdto(server, rnick, message, rnick)

def message(server, message, rnick, address, target):
    rdto(server, target, message, rnick)

def action(server, message, rnick, address, target):
    pass

# Stuff for Willie module

def setup(bot):
    signal.signal(signal.SIGALRM, alarm_handler)

@willie.module.commands("roll")
def willieroll(bot, trigger):
    try:
        dicestr = trigger.group(2).split()[0]
    except:
        return
    try:
        signal.alarm(10)
        nd, si, rs = do_roll(dicestr)
        bot.say("{} rolled {}d{}: {}".format(trigger.nick, nd, si, ", ".join(rs)))
        signal.alarm(0)
    except (MemoryError, irc.client.MessageTooLong, AlarmException):
        bot.say("Stop being an asshole.")
        signal.alarm(0)
        return
    except: # if roll failed
        signal.alarm(0)
        return

@willie.module.commands("choose")
def williechoose(bot, trigger):
    chstr = trigger.group(2)
    choices = [i.strip() for i in chstr.split(',')]
    if len(choices) == 0:
        return
    choice = random.choice(choices)
    choice = re.sub("(babe)l(bot)", lambda x: x.group(1) + x.group(2), choice, flags=re.I)
    bot.say("{} selects: {}".format(trigger.nick, choice))

@willie.module.commands("draw")
def williedraw(bot, trigger):
    try:
        args = trigger.group(2).split()
    except:
        return
    n = None
    try:
        if args[0] == 'card':
            n = 1
        elif args[0].isnumeric() and args[1] in ['card', 'cards']:
            n = int(args[0])
    except:
        return
    if n:
        try:
            bot.say("{} drew: {}".format(trigger.nick, ', '.join(draw_cards(n))))
        except ValueError:
            bot.say("Yes, you're very clever.")

if irssi:
    irssi.signal_add("message public", message)
    irssi.signal_add("message private", query)
    irssi.signal_add("ctcp action", action)
else:
    if __name__=="__main__":
        main()
