#!/usr/bin/python3

try:
    from irc.bot import SingleServerIRCBot
except ImportError:
    SingleServerIRCBot = object
from bs4 import BeautifulSoup
import forum_archive
import urllib.request, urllib.parse, http.cookiejar
import re, hashlib, sys, argparse

try:
    import willie
except ImportError:
    willie = None

plink_re = re.compile(r"(https?://)?forum.questionablequesting.com/threads/(.*\.)?(?P<tid>\d+)/(page-(?P<pnum>\d+))?(#post-(?P<pid>\d+))?")
pagelink = "http://forum.questionablequesting.com/threads/{tid}/page-{pnum}"

login_creds = None
pastebin_api_key = None
pastebin_user_key = None

def get_posts(url, surl=None):
    o = plink_re.match(url)
    page_start = int(o.group('pnum') or '1')
    id_start = o.group('pid') or ''
    if surl:
        o = plink_re.match(surl)
        page_end = int(o.group('pnum') or '1')
        id_end = o.group('pid') or ''
    else:
        page_end = id_end = None
    a = forum_archive.make_getter(url, cred=login_creds)
    result = a.get_thread((page_start, page_end))
    fi = [id_start in i['post_url'] for i in result].index(True)
    try:
        li = [id_end in i['post_url'] for i in result].index(True)
    except (ValueError, TypeError):
        li = None
    result = result[fi:li]
    return result

# Regular expressions for votes and tally indicators
vote_re = re.compile(r"^(?P<indent>[\s-]*)\[[Xx]\]\s*(?P<vote>\S.*)")
tally_re = re.compile(r"^#####")
 
def get_votes(post):
    soup = BeautifulSoup(post['text'])
    pl = post_lines(soup)
    
    # If we encounter a tally post, skip processing the post entirely
    tally_check = [m for l in pl for m in [tally_re.match(l)] if m ]
    if len(tally_check) > 0:
        return
    
    # Return each valid vote line
    for i in pl:
        if vote_re.match(i):
            yield i

def count_votes(vclist):
    voters = {}
    for i in vclist[1:]: # skip the first post, assumed to be the poll
        vl = list(get_votes(i))
        if len(vl) == 1:
            broke = False
            for v in voters.keys():
                if re.search(v, vl[0], re.I):
                    #print(v, i)
                    voters[i['poster_name']] = list(voters[v])
                    broke = True
                    break
            if broke:
                continue
        elif len(vl) == 0:
            continue
        voters[i['poster_name']] = []
        for v in vl:
            o = vote_re.match(v)
            voters[i['poster_name']].append((o.group('vote').strip(), len(o.group('indent'))))
    votes = {}
    for i in voters.keys():
        for v in voters[i]:
            if not v in votes:
                votes[v] = []
            votes[v].append(i)
    return voters, votes

def format_count(votes):
    out = "[color=transparent]##### QQBot[/color]\n"
    for i in sorted(votes.keys()):
        out += "{}[X] {} {}: ({})\n".format('-' * i[1], len(votes[i]), i[0], ', '.join(votes[i]))
    return out

def post_lines(post):
    """ Takes a post of tag soup, removes any unwanted tags, then gets all the text
    of the post and breaks it into a list of individual lines.

    """
    post = clean_post(post)
    one_long_line = get_lines_rec(post)
    all_post_lines = [s.strip() for s in one_long_line.splitlines() if s.strip() != ""]
    return all_post_lines

def get_lines_rec(tag, accum=''):
    """ Takes a post of tag soup, and recursively extracts the text from
    all the tags (skipping blockquotes).
    Line endings are added where appropriate, but not duplicated.
    The result should be a string containing all the text of the post in lines matching
    what was displayed in the forum.
    """
    for i in tag.children:
        if i.name == 'blockquote':
            continue
        elif i.name == 'ul':
            accum += "\n"
            for n in i.children:
                accum = get_lines_rec(n, accum)
                accum += "\n"
        elif i.name == 'br':
            if not accum.endswith("\n"):
                accum += "\n"
        elif hasattr(i, "contents"):
            accum = get_lines_rec(i, accum)
        else:
            accum += str(i)
    return accum

# Clean the post of any unwanted tags
def clean_post(post):
    # Remove any strike-through spans
    strikes = post.find_all(is_strike_span)
    for s in strikes:
        s.clear()
    return post

def is_strike_span(tag):
    return tag.name == "span" and tag.has_attr('style') and re.match(r'text-decoration:\s*line-through', tag["style"])
    

def pastebin_paste(text):
    r = urllib.request.urlopen('http://pastebin.com/api/api_post.php', 
                               data=urllib.parse.urlencode({'api_dev_key': pastebin_api_key,
                                                            'api_user_key': pastebin_user_key,
                                                            'api_option': 'paste',
                                                            'api_paste_code': text}).encode())
    d = r.read()
    return d.decode()

class Countbot(SingleServerIRCBot):
    def __init__(self, channel, nick, server, nspw=None, port=6667):
        SingleServerIRCBot.__init__(self, [(server, port)], nick, nick)
        self.channel = channel
        self.nspw = nspw

    def on_nicknameinuse(self, c, e):
        c.nick(c.get_nickname() + "_")
        
    def on_welcome(self, c, e):
        if self.channel:
            c.join(self.channel)
        if self.nspw:
            c.privmsg("NickServ", "identify {}".format(self.nspw))

    def do_count(self, event):
        nick = event.source.split('!')[0]
        if event.type == 'pubmsg':
            sendto = event.target
        elif event.type == 'privmsg':
            sendto = nick
        msg = event.arguments[0]
        args = msg.split()
        if len(args) == 0:
            return
        if args[0] == 'votes':
            if len(args) < 2 or len(args) > 3:
                return
            if not plink_re.match(args[1]):
                return
            if len(args) == 3 and not plink_re.match(args[2]):
                return
            print("Doing {} for {}".format(args[1:], nick))
            try:
                posts = get_posts(*args[1:])
                voters, votes = count_votes(posts)
                string = format_count(votes)
                url = pastebin_paste(string)
                self.connection.privmsg(sendto, url)
            except:
                self.connection.privmsg(sendto, "Couldn't access QQ")
        try:
            if event.type == 'privmsg':
                print("Got from {}".format(nick))
                print(msg)
                if args[0] == 'join':
                    self.connection.join(args[1])
                elif args[0] == 'leave':
                    self.connection.part(args[1])
                elif args[0] == 'version':
                    self.connection.privmsg(sendto, 'Countbot version 0.1')
        except IndexError:
            pass

    def on_privmsg(self, c, e):
        #print('priv', e)
        self.do_count(e)

    def on_pubmsg(self, c, e):
        #print('pub', e)
        self.do_count(e)

def main():
    parser = argparse.ArgumentParser(description='IRC bot to count QQ votes')
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
    if args.channel == 'None':
        args.channel = None
    bot = Countbot(args.channel, args.nick, server, args.password, port)
    bot.start()

# Stuff for Willie (try-catch is necessary to be able to load in standard interpreter context)
def setup(bot):
    global login_creds, pastebin_api_key, pastebin_user_key
    c1 = {'username': bot.config.qqbot.username,
          'password': bot.config.qqbot.password }
    a = forum_archive.make_getter('https://forum.questionablequesting.com/threads/rules.1/', cred=c1)
    login_creds = a.cred
    pastebin_api_key = bot.config.qqbot.pastebin_api_key
    pastebin_user_key = bot.config.qqbot.pastebin_user_key

try:
    @willie.module.commands("votes")
    def williecount(bot, trigger):
        try:
            args = trigger.group(2).split()
        except AttributeError:
            return
        if len(args) < 1 or len(args) > 2:
            return
        if not plink_re.match(args[0]):
            return
        if len(args) == 2 and not plink_re.match(args[1]):
            return
        print("Doing {} for {}".format(args, trigger.nick))
        try:
            posts = get_posts(*args)
            voters, votes = count_votes(posts)
            string = format_count(votes)
            url = pastebin_paste(string)
            bot.say(url)
        except:
            bot.say("Couldn't access QQ")
            raise

    @willie.module.commands("man")
    def willieman(bot, trigger):
        try:
            args = trigger.group(2).split()
        except AttributeError:
            return
        if args[0] == 'qqbot':
            bot.say("No manual entry for qqbot")

except AttributeError:
    pass

if __name__=="__main__":
    main()
