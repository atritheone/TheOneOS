#!/the one/software/python/bin/python -B


"""
creep.py

creep is a cli isr software for target enumeration, secret scanning, and credential checking.
"""



# imports
import os
import sys
import json

DEPENDENCY_ERRORS = {}
requests = None
import re
import ftplib
paramiko = None
import io
import logging
import signal
import math
import atexit
import readline
import threading
from ftplib import FTP
from html import unescape
from urllib.parse import urljoin, urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed


BASE = os.path.dirname(os.path.abspath(__file__))
T1OS_DATA_DIRECTORY = os.environ.get(
    'T1OS_CREEP_DATA', '/software/creep data')
CREEP_INTERACTIVE_STATUS_PATH = os.path.join(
    os.path.expanduser('~'), '.creep-interactive-test.json')
DEFAULT_USERNAMES = frozenset(('admin', 'administrator', 'development', 'root'))
DEFAULT_PASSWORDS = frozenset(('admin', 'password'))
DEFAULT_DIRECTORIES = ('admin', 'api', 'assets', 'login', 'robots.txt')



# globals
COMMANDS = [
    "set target", "clear target", "add endpoints", "clear endpoints",
    "set wordlist", "set passlist", "set directory", "set debug",
    "scan", "scan ftp", "scan ssh", "enumerate", "results",
    "show results", "show options", "show hashes", "check", "reset",
    "session", "help", "clear", "exit"
]

# colours
GREEN = "\033[92m"
GOLD = "\033[1;33m"
RED = "\033[91m"
MAGENTA = "\033[95m"
GREY = "\033[90m"
CYAN = "\033[96m"
BROWN = "\033[38;5;130m"
ORANGE = "\033[38;5;208m"
RESET = "\033[0m"


# misc functions
def loadrequests():

    global requests
    if requests is not None:
        return requests
    try:
        import requests as loaded_requests
    except Exception as error:
        DEPENDENCY_ERRORS['requests'] = f'{type(error).__name__}: {error}'
        return None
    requests = loaded_requests
    DEPENDENCY_ERRORS.pop('requests', None)
    return requests


def requestsession(state):

    loaded = loadrequests()
    if loaded is None:
        raise RuntimeError(
            'requests is unavailable: ' +
            DEPENDENCY_ERRORS.get('requests', 'import failed'))
    session = state.get('session')
    if session is None:
        session = loaded.Session()
        state['session'] = session
    return session


def loadparamiko():

    global paramiko
    if paramiko is not None:
        return paramiko
    try:
        import paramiko as loaded_paramiko
    except Exception as error:
        DEPENDENCY_ERRORS['paramiko'] = f'{type(error).__name__}: {error}'
        return None
    paramiko = loaded_paramiko
    DEPENDENCY_ERRORS.pop('paramiko', None)
    return paramiko


def startup():

    # history
    state = {}
    history_path = os.path.join(os.path.expanduser("~"), ".creep_history")
    try:
        readline.read_history_file(history_path)
    except FileNotFoundError:
        pass
    atexit.register(readline.write_history_file, history_path)
    readline.set_history_length(1000)

    # supress logs
    logging.getLogger("paramiko").setLevel(logging.ERROR)

    # core state
    state['session_states'] = {}
    state['target'] = None
    state['endpoints'] = set()
    state['endpoints_scanned'] = set()
    state['discovered_links'] = set()
    state['scanned_files'] = set()
    state['discovered_users'] = set()
    state['discovered_passwords'] = set()
    state['discovered_wordlist_users'] = set()
    state['discovered_credentials'] = set()
    state['test_credentials'] = set()
    state['valid_ftp_credentials'] = set()
    state['valid_ssh_credentials'] = set()
    state['ftp_tested'] = False
    state['ssh_tested'] = False
    state['debug'] = "--debug" in sys.argv

    # wordlist and directory paths
    share_path = T1OS_DATA_DIRECTORY
    state['wordlist_path'] = os.path.join(share_path, 'usernames.txt')
    state['password_wordlist_path'] = os.path.join(share_path, 'passwords.txt')
    state['directory_path'] = os.path.join(share_path, 'directory.txt')

    # load lists
    state['wordlist'] = loadwordlist(state['wordlist_path'])
    state['password_wordlist'] = loadpasswordwordlist(state['password_wordlist_path'])
    state['directory_list'] = loaddirectorylist(state['directory_path'])
    state['discovered_password_wordlist_matches'] = set()

    # hash patterns and storage
    state['hash_patterns'] = {
        'md5': r"\b[a-fA-F0-9]{32}\b",
        'sha1': r"\b[a-fA-F0-9]{40}\b",
        'sha256': r"\b[a-fA-F0-9]{64}\b",
        'sha512': r"\b[a-fA-F0-9]{128}\b",
        'bcrypt': r"\$2[aby]\$\d{2}\$[./A-Za-z0-9]{53}",
        'scrypt': r"^\$s0\$[0-9a-f]+\$[A-Za-z0-9+/]+={0,2}\$[A-Za-z0-9+/]+={0,2}$"
    }
    state['found_hashes'] = {k: set() for k in state['hash_patterns']}

    # misc secrets categories
    state['misc_secrets'] = {
        'environment': set(),
        'google_api_keys': set(),
        'api_tokens': set(),
        'session_tokens': set(),
        'certificate': set(),
        'private_key': set(),
        'aws_access_keys': set(),
        'aws_secret_keys': set(),
        'jwt_tokens': set(),
        'slack_tokens': set(),
        'discord_tokens': set(),
        'stripe_api_keys': set(),
        'db_connection_strings': set(),
        'oauth_tokens': set(),
        'pgp_keys': set(),
        'high_entropy': set()
    }

    # http session
    state['session'] = None

    # banner
    banner = []
    banner.append(r"""

 ▄████████    ▄████████    ▄████████    ▄████████    ▄███████▄ 
███    ███   ███    ███   ███    ███   ███    ███   ███    ███ 
███    █▀    ███    ███   ███    ███   ███    ███   ███    ███ 
███         ▄███▄▄▄▄██▀  ▄███▄▄▄      ▄███▄▄▄       ███    ███ 
███        ▀▀███▀▀▀▀▀   ▀▀███▀▀▀     ▀▀███▀▀▀     ▀█████████▀  
███    █▄  ▀███████████   ███    █▄    ███    █▄    ███        
███    ███   ███    ███   ███    ███   ███    ███   ███     
████████▀    ███    ███   ██████████   ██████████  ▄████▀      
             ███    ███   


""")
    banner.append("creep 0.28".ljust(62 - len("slayer")) + "slayer")
    banner.append("")
    banner.append("")
    banner.append(f"[+] loaded {len(state['wordlist'])} usernames from {state['wordlist_path']}")
    banner.append(f"[+] loaded {len(state['password_wordlist'])} passwords from {state['password_wordlist_path']}")
    banner.append(f"[+] loaded {len(state['directory_list'])} directories from {state['directory_path']}")
    banner.append("")
    state['banner'] = "\n".join(banner)
    print(state['banner'])
    print()

    # key bindings
    readline.set_completer(completer)
    readline.parse_and_bind("tab: complete")

    # cancel event
    state['cancelevent'] = threading.Event()

    # signal handler
    signal.signal(signal.SIGTSTP, handlesigtstp)
    signal.siginterrupt(signal.SIGTSTP, False)

    return state


def executecommand(state, cmd):

    parts = [c.strip() for c in cmd.split('&') if c.strip()]
    for part in parts:
        redirect = None
        main_part = part
        if '>' in part:
            main_part, redirect = [s.strip() for s in part.split('>', 1)]
        lp = main_part.lower()
        if lp.startswith('set target'):
            settarget(state, main_part)
        elif lp.startswith("add endpoints"):
            addendpoints(state, main_part)
        elif lp.startswith('set wordlist'):
            setwordlist(state, main_part)
        elif lp.startswith('set passlist'):
            setpasslist(state, main_part)
        elif lp.startswith('set directory'):
            setdirectory(state, main_part)
        elif lp.startswith('set debug'):
            setdebug(state, main_part)
        elif lp == 'clear target':
            cleartarget(state)
        elif lp == 'clear endpoints':
            clearendpoints(state)
        elif lp in ('clear', 'cls'):
            clearterminal(state)
        elif lp in ('scan', 'run'):
            scan(state)
        elif lp == 'scan ftp':
            scanftp(state)
        elif lp == 'scan ssh':
            scanssh(state)
        elif lp == 'enumerate':
            enumeratedirectories(state)
        elif lp in ('results', 'show results'):
            showresults(state)
        elif lp == 'results >':
            showresults(state)
        elif lp == 'show options':
            showoptions(state)
        elif lp == 'show hashes':
            showhashes(state)
        elif lp == 'check':
            check(state)
        elif lp == "reset":
            reset(state)
        elif lp.startswith('session'):
            parts = main_part.split()
            if len(parts) == 2 and parts[1].isdigit():
                loadsession(state, parts[1])
            else:
                print('> usage: session <number>')
        elif lp == 'help':
            showhelp()
        elif lp == 'exit':
            sys.exit(0)
        else:
            print('> unknown command')
        if redirect:
            buf = io.StringIO()
            if lp == 'enumerate':
                for ep in sorted(state['endpoints']): buf.write(ep + '\n')
            else:
                old = sys.stdout
                sys.stdout = buf
                showresults(state)
                sys.stdout = old
            try:
                with open(redirect, 'w', encoding='utf-8') as f:
                    f.write(buf.getvalue())
                print(f"[+] output written to {redirect}")
            except Exception as e:
                print(f"{RED}> error writing to {redirect}: {e}{RESET}")


def reset(state):

    debugprint(state, "resetting all options to defaults")

    # preserve sessions
    sessions = state['session_states']

    # clear and reset only the specific runtime options (not full state)
    state['target'] = None
    state['endpoints'] = set()
    state['endpoints_scanned'] = set()
    state['discovered_links'] = set()
    state['scanned_files'] = set()
    state['discovered_users'] = set()
    state['discovered_passwords'] = set()
    state['discovered_wordlist_users'] = set()
    state['discovered_password_wordlist_matches'] = set()
    state['discovered_credentials'] = set()
    state['valid_ftp_credentials'] = set()
    state['valid_ssh_credentials'] = set()
    state['ftp_tested'] = False
    state['ssh_tested'] = False

    # reset debug flag to default (off)
    state['debug'] = False

    # reset wordlist/directory paths to defaults
    share = T1OS_DATA_DIRECTORY
    state['wordlist_path'] = os.path.join(share, 'usernames.txt')
    state['password_wordlist_path'] = os.path.join(share, 'passwords.txt')
    state['directory_path'] = os.path.join(share, 'directory.txt')

    # reload lists
    state['wordlist'] = loadwordlist(state['wordlist_path'])
    state['password_wordlist'] = loadpasswordwordlist(state['password_wordlist_path'])
    state['directory_list'] = loaddirectorylist(state['directory_path'])

    # clear any discovered hashes
    state['found_hashes'] = {k: set() for k in state['hash_patterns']}

    # clear misc secrets categories
    for cat in state['misc_secrets']:
        state['misc_secrets'][cat].clear()

    # fresh HTTP session
    state['session'] = None

    # restore sessions dict (unchanged)
    state['session_states'] = sessions

    print("> all options have been reset")


def completer(text, state_index):

    buffer = readline.get_line_buffer()
    beg = readline.get_begidx()
    if beg == 0:
        options = [cmd for cmd in COMMANDS if cmd.startswith(text)]
        return options[state_index] + " " if state_index < len(options) else None
    else:
        tokens = buffer.split()
        curr = text
        if tokens[0] == "set":
            sub = ["target", "wordlist", "passlist", "directory", "debug"]
            opts = [s for s in sub if s.startswith(curr)]
            return opts[state_index] + " " if state_index < len(opts) else None
        elif tokens[0] == "clear":
            sub = ["target", "endpoints"]
            opts = [s for s in sub if s.startswith(curr)]
            return opts[state_index] + " " if state_index < len(opts) else None
        elif tokens[0] == "add":
            sub = ["endpoints"]
            opts = [s for s in sub if s.startswith(curr)]
            return opts[state_index] + " " if state_index < len(opts) else None
        elif tokens[0] == "show":
            sub = ["results", "options", "hashes"]
            opts = [s for s in sub if s.startswith(curr)]
            return opts[state_index] + " " if state_index < len(opts) else None
        else:
            opts = [cmd for cmd in COMMANDS if cmd.startswith(curr)]
            return opts[state_index] + " " if state_index < len(opts) else None


def debugprint(state, message):

    if state.get('debug'):
        print(f"[debug] {message}")


def safeinput(prompt):

    try:
        return input(prompt)
    except KeyboardInterrupt:
        print("\n> cancelling")
        return ""
    except EOFError:
        print("\n")
        return None
    except OSError:
        return None


# session functions
def loadsession(state, session_id):

    try:
        sid = int(session_id)
    except ValueError:
        print(f"{RED}> session number must be an integer{RESET}")
        return
    sessions = state.get('session_states', {})
    if sid not in sessions:
        print(f"{RED}> session {sid} not found{RESET}")
        return
    saved = sessions[sid]
    for k, v in saved.items():
        state[k] = v
    print(f"[*] session {sid} recalled")


def handlesigtstp(signum, frame):

    # background current state
    global state
    session_id = len(state['session_states']) + 1

    # deep copy state
    saved = {k: v for k, v in state.items() if k != 'session_states'}
    state['session_states'][session_id] = saved
    print(f"\n[*] session {session_id} backgrounded")
    sys.stdout.write("> ")
    sys.stdout.flush()


# load functions
def loadwordlist(filename="usernames.txt"):

    try:
        with open(filename, "r", encoding="utf-8") as f:
            return {line.strip() for line in f if line.strip()}
    except FileNotFoundError:
        return set(DEFAULT_USERNAMES)
    except Exception as e:
        print(f"{RED}[-] error loading wordlist {filename}: {e}{RESET}")
        return set()


def loadpasswordwordlist(filename="passwords.txt"):

    try:
        with open(filename, "r", encoding="utf-8") as f:
            return {line.strip() for line in f if line.strip()}
    except FileNotFoundError:
        return set(DEFAULT_PASSWORDS)
    except Exception as e:
        print(f"{RED}[-] error loading password wordlist {filename}: {e}{RESET}")
        return set()


def loaddirectorylist(filename="directory.txt"):

    try:
        with open(filename, "r", encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        return list(DEFAULT_DIRECTORIES)
    except Exception as e:
        print(f"{RED}[-] error loading directory list {filename}: {e}{RESET}")
        return []


# set functions
def settarget(state, cmd):

    parts = cmd.split()
    if len(parts) < 3:
        print("> usage: set target <ip or url>")
        return
    state['target'] = parts[2]
    debugprint(state, f"target set to {state['target']}")
    print(f"> target set to {state['target']}")


def setwordlist(state, cmd):

    parts = cmd.split(" ", 2)
    if len(parts) < 3:
        print("> usage: set wordlist <path>")
        return
    path = parts[2].strip()
    state['wordlist_path'] = path
    state['wordlist'] = loadwordlist(path)
    debugprint(state, f"wordlist path set to {path}")
    print(f"> wordlist set to {path}")


def setpasslist(state, cmd):

    parts = cmd.split(" ", 2)
    if len(parts) < 3:
        print("> usage: set passlist <path>")
        return
    path = parts[2].strip()
    state['password_wordlist_path'] = path
    state['password_wordlist'] = loadpasswordwordlist(path)
    debugprint(state, f"password wordlist path set to {path}")
    print(f"> passlist set to {path}")


def setdirectory(state, cmd):

    parts = cmd.split(" ", 2)
    if len(parts) < 3:
        print("> usage: set directory <path>")
        return
    path = parts[2].strip()
    state['directory_path'] = path
    state['directory_list'] = loaddirectorylist(path)
    debugprint(state, f"directory list path set to {path}")
    print(f"> directory list set to {path}")


def setdebug(state, cmd):

    parts = cmd.split(" ", 2)
    if len(parts) < 3:
        print("> usage: set debug <true|false>")
        return
    value = parts[2].strip().lower()
    if value == "true":
        state['debug'] = True
    elif value == "false":
        state['debug'] = False
    else:
        print("> debug value must be true or false")
        return
    debugprint(state, f"debug set to {state['debug']}")
    print(f"> debug set to {state['debug']}")


def addendpoints(state, cmd):

    debugprint(state, f"adding endpoints with command: {cmd}")
    parts = cmd.split(" ", 2)
    if len(parts) < 3:
        print("> skipping endpoint addition. running with only the target")
        return

    arg = parts[2].strip()
    raw_eps = []
    if arg.endswith(".txt") and os.path.isfile(arg):
        debugprint(state, f"loading endpoints from file: {arg}")
        with open(arg, "r", encoding="utf-8") as f:
            raw_eps = [line.strip() for line in f if line.strip()]
    else:
        raw_eps = [e.strip() for e in arg.split(",") if e.strip()]

    count = 0
    for ep in raw_eps:
        if not ep.startswith("/"):
            ep = "/" + ep
        parts = ep.strip("/").split("/")
        expanded_list = []
        current = ""
        for part in parts:
            current += "/" + part
            expanded_list.append(current)
        debugprint(state, f"expanded endpoint '{ep}' to {expanded_list}")

        for expanded in expanded_list:
            if expanded not in state['endpoints']:
                state['endpoints'].add(expanded)
                state['endpoints_scanned'].add(expanded)
                count += 1

    debugprint(state, f"added {count} endpoints: {state['endpoints']}")
    print(f"> added {count} endpoints")


# clear functions
def cleartarget(state):

    state['target'] = None
    debugprint(state, "target cleared")
    print("> target cleared")


def clearendpoints(state):

    state['endpoints'].clear()
    state['endpoints_scanned'].clear()
    state['discovered_links'].clear()
    state['scanned_files'].clear()
    debugprint(state, "endpoints cleared")
    print("> endpoints cleared")


def clearterminal(state=None):

    # T1OS intentionally has no general-purpose host shell in PATH.  ANSI
    # clear-and-home works in Brick's PTY and ordinary compatible terminals.
    print("\033[2J\033[H", end="")
    print(state['banner'])
    debugprint(state, "terminal cleared, banner reprinted")


# print functions
def showhelp():

    print()
    print("" + "-" * 60)

    help_text = (
            "set target\t\tset the target ip or url (usage: set target <ip or url>)\n" +
            "clear target\t\tclear the current target\n" +
            "add endpoints\t\tlist address endpoints in format /page separated by commas or use a .txt file\n" +
            "clear endpoints\t\tclear the current endpoints\n" +
            "set wordlist\t\tset the path to the wordlist file (usage: set wordlist <path>)\n" +
            "set passlist\t\tset the path to the password wordlist file (usage: set passlist <path>)\n" +
            "set directory\t\tset the path to the directory wordlist file (usage: set directory <path>)\n" +
            "set debug\t\tenable or disable debug output (usage: set debug <true|false>)\n" +
            "scan (run)\t\tscan the target and endpoints, and check if ftp/ssh ports are open\n" +
            "scan ftp\t\tcheck if ftp port is open\n" +
            "scan ssh\t\tcheck if ssh port is open\n" +
            "enumerate\t\tperform recursive subdirectory enumeration using the loaded directory list\n" +
            "enumerate >\t\toutput discovered endpoints to txt file\n" +
            "check\t\t\tcheck discovered credentials\n" +
            "show results\t\toutput discovered results\n" +
            "results >\t\toutput discovered results to txt file\n" +
            "show options\t\tdisplay the current configuration options\n" +
            "show hashes\t\tdisplay discovered hashes\n" +
            "reset\t\t\treset all options to their initial state\n" +
            "session <num>\t\trecall a backgrounded session by its number\n" +
            "help\t\t\tshow the help message\n" +
            "clear (cls)\t\tclear the terminal\n" +
            "exit\t\t\texit the software"
    )

    print(help_text)
    print("-" * 60 + "")
    print()


def showoptions(state):

    rows = []
    rows.append(("target", state.get('target') or "none", "yes", "the target host to scan"))
    for ep in sorted(state.get('endpoints', [])):
        rows.append(("endpoints", ep, "no", "optional endpoints"))
    rows.append(("wordlist", state['wordlist_path'], "yes", "file to load usernames from"))
    rows.append(("passlist", state['password_wordlist_path'], "yes", "file to load passwords from"))
    rows.append(("directory", state['directory_path'], "yes", "file to load directories from"))
    rows.append(("debug", "true" if state.get('debug') else "false", "no", "enable debug output"))

    headers = ("name", "current setting", "required", "description")
    cols = list(zip(*([headers] + rows)))
    widths = [max(len(str(cell)) for cell in col) for col in cols]

    fmt = f"{{:<{widths[0]}}}  {{:<{widths[1]}}}  {{:<{widths[2]}}}  {{:<{widths[3]}}}"

    print()
    print("=== options ===")
    print(fmt.format(*headers))
    print(fmt.format(*["-" * w for w in widths]))

    for row in rows:
        print(fmt.format(*row))

    print("=" * (sum(widths) + 6))
    print()


def showresults(state):

    # endpoints
    print()
    print("=== creep results ===")
    print(f"target: {state.get('target')}")
    eps = state.get('endpoints_scanned') or set()
    if eps:
        print("endpoints scanned: " + (', '.join(sorted(eps)) if eps else 'none'))
    links = state.get('discovered_links') or set()
    if links:
        print("discovered links: " + (', '.join(sorted(links)) if links else 'none'))

    # files
    files = state.get('scanned_files') or set()
    if files:
        print("scanned files: " + (', '.join(sorted(files)) if files else 'none'))
    # secrets
    wu = state.get('discovered_wordlist_users') or set()
    if wu:
        print(f"possible usernames found: {', '.join(sorted(wu)) if wu else 'none'}")
    pwm = state.get('discovered_password_wordlist_matches') or set()
    if pwm:
        print(f"possible passwords found: {', '.join(sorted(pwm)) if pwm else 'none'}")
    # credentials
    creds = state.get('discovered_credentials') or set()
    if creds:
        print(f"credentials found: {', '.join(sorted(creds)) if creds else 'none'}")
    vftp = state.get('valid_ftp_credentials') or set()
    if vftp:
        print(f"valid ftp credentials: {', '.join(sorted(vftp)) if vftp else 'none'}")
    vssh = state.get('valid_ssh_credentials') or set()
    if vssh:
        print(f"valid ssh credentials: {', '.join(sorted(vssh)) if vssh else 'none'}")

    # hashes

    for htype, hset in state.get('found_hashes', {}).items():
        if hset:
            print("hashes found:")
            print(f"{htype}: {', '.join(sorted(hset)) if hset else 'none'}")

    # misc secrets
    for key, items in state.get('misc_secrets', {}).items():
        if items:
            label = key.replace('_', ' ')
            print(f"{label}: " + ', '.join(sorted(items)))
    print("====================")
    print()


def showhashes(state):

    print()
    print("=== hashes found ===")
    for ht, hs in state['found_hashes'].items():
        print(f"{ht}: {', '.join(hs) if hs else 'none'}")
    print("=" * 20 + "")
    print()


# scanning functions
def checktargetavailability(state):

    if not state['target']:
        debugprint(state, "target is not set; availability check failed")
        return False
    url = f"http://{state['target']}"
    try:
        resp = requestsession(state).get(url, timeout=5)
        debugprint(state, f"target {url} returned status {resp.status_code}")
        return resp.status_code < 400
    except Exception:
        debugprint(state, f"target {url} not reachable")
        return False


def isvalidendpoint(state, full_url, cancelevent):

    if cancelevent.is_set():
        return False
    try:
        r = requestsession(state).head(full_url, allow_redirects=True, timeout=5)
        code = r.status_code
        return code if code < 400 or code == 403 else False
    except Exception:
        return False


def expandendpoint(endpoint):

    endpoint = endpoint.strip()
    if not endpoint.startswith("/"):
        endpoint = "/" + endpoint
    parts = endpoint.strip("/").split("/")
    expanded = []
    current = ""
    for part in parts:
        current += "/" + part
        expanded.append(current)
    return expanded


def scansingletarget(state):

    url = f"http://{state['target']}"
    debugprint(state, f"scanning single target url: {url}")
    try:
        resp = requestsession(state).get(url, timeout=5)
        if resp.status_code == 200:
            print(f"[+] scanned: {url}".lower())
            checkforsshkeys(url)
            extractcredentials(state, resp.text)
            extractwordlistmatches(state, resp.text)
            extractpasswordmatches(state, resp.text)
            extracthashes(state, resp.text)
            extractmiscsecrets(state, resp.text)
            extractlinks(state, resp.text, url)
        else:
            print(f"[-] failed: {url} (status: {resp.status_code})".lower())
    except Exception:
        print(f"{RED}[-] error accessing {url}{RESET}".lower())
    except KeyboardInterrupt:
        print("> cancelling")
        return


def scan(state):

    if not state['target']:
        print("> set a target before scanning")
        return
    if not checktargetavailability(state):
        print(f"{RED}[-] target {state['target']} is down or unreachable.{RESET}")
        return
    debugprint(state, "initiating scan")
    print(f"[+] scanning target: {state['target']}".lower())
    scansingletarget(state)
    scanned = set()
    while True:
        new_eps = state['endpoints'] - scanned
        if not new_eps:
            break
        for ep in sorted(new_eps):
            url = f"http://{state['target']}{ep}"
            debugprint(state, f"scanning url: {url}")
            try:
                resp = requestsession(state).get(url, timeout=5)
                if resp.status_code == 200:
                    print(f"[+] scanned: {url}".lower())
                    checkforsshkeys(url)
                    extractcredentials(state, resp.text)
                    extractwordlistmatches(state, resp.text)
                    extractpasswordmatches(state, resp.text)
                    extracthashes(state, resp.text)
                    extractmiscsecrets(state, resp.text)
                    extractlinks(state, resp.text, url)
                else:
                    print(f"{RED}[-] failed: {url} (status: {resp.status_code}){RESET}".lower())
            except Exception:
                print(f"{RED}[-] error accessing {url}{RESET}".lower())
            except KeyboardInterrupt:
                print("> cancelling")
                return
            scanned.add(ep)
    scanftp(state)
    scanssh(state)


def scanftp(state):

    debugprint(state, "initiating ftp scan")
    if not state['target']:
        print("> set a target before scanning ftp")
        return
    if not checktargetavailability(state):
        print(f"{RED}[-] target {state['target']} is down or unreachable.{RESET}")
        return
    print(f"[+] scanning ftp on {state['target']}...".lower())
    try:
        sock = __import__('socket').socket()
        sock.settimeout(5)
        result = sock.connect_ex((state['target'], 21))
        debugprint(state, f"ftp connect_ex returned {result}")
        if result == 0:
            print(f"{CYAN}[+] ftp port 21 is open{RESET}".lower())
            try:
                ftp = FTP(state['target'])
                ftp.login("anonymous", "")
                print(f"{GOLD}[+] anonymous ftp login successful{RESET}".lower())
                ftp.quit()
            except Exception:
                print("[-] anonymous ftp login failed".lower())
            state['ftp_tested'] = True
        else:
            print(f"{GREY}[-] ftp port 21 is closed{RESET}".lower())
            state['ftp_tested'] = False
        sock.close()
    except Exception as e:
        debugprint(state, f"ftp scan error: {e}")
        print(f"{RED}[-] ftp scan failed{RESET}".lower())


def scanssh(state):

    debugprint(state, "initiating ssh scan")
    if not state['target']:
        print("> set a target before scanning ssh")
        return
    if not checktargetavailability(state):
        print(f"{RED}[-] target {state['target']} is down or unreachable.{RESET}")
        return
    print(f"[+] scanning ssh on {state['target']}...".lower())
    try:
        sock = __import__('socket').socket()
        sock.settimeout(5)
        result = sock.connect_ex((state['target'], 22))
        debugprint(state, f"ssh connect_ex returned {result}")
        if result == 0:
            print(f"{CYAN}[+] ssh port 22 is open{RESET}".lower())
            state['ssh_tested'] = True
        else:
            print(f"{GREY}[-] ssh port 22 is closed{RESET}".lower())
            state['ssh_tested'] = False
        sock.close()
    except Exception as e:
        debugprint(state, f"ssh scan error: {e}")
        print(f"{RED}[-] ssh scan failed{RESET}".lower())


def enumeratedirectories(state):

    old_handler = signal.getsignal(signal.SIGTSTP)
    signal.signal(signal.SIGTSTP, signal.SIG_IGN)

    cancelevent = state['cancelevent']
    cancelevent.clear()

    debugprint(state, "starting subdirectory enumeration")
    if not state['target']:
        print("> set a target before enumeration")
        return
    if not checktargetavailability(state):
        print(f"{RED}[-] target {state['target']} is down or unreachable. aborting enumeration.{RESET}")
        return
    if not state['directory_list']:
        print("[-] no directories loaded".lower())
        return

    parsed = urlparse(f"http://{state['target']}")
    host = parsed.hostname
    port = parsed.port or 80

    to_process = ["/"]
    processed = set()
    print("[+] starting subdirectory enumeration...".lower())

    while to_process and not cancelevent.is_set():
        current = to_process.pop(0)
        debugprint(state, f"enumerating subdirectories for: {current}")
        base = f"{host}:{port}" if current == "/" else f"{host}:{port}{current}"
        print(f"[+] enumerating: {base}")

        future_to_endpoint = {}
        executor = ThreadPoolExecutor(max_workers=20)
        try:
            for candidate in state['directory_list']:
                if cancelevent.is_set():
                    break
                new_ep = f"/{candidate}" if current == "/" else f"{current}/{candidate}"
                new_ep = new_ep.rstrip("/")
                if new_ep in processed or new_ep in state['endpoints']:
                    continue
                full_url = f"http://{host}:{port}{new_ep}"
                fut = executor.submit(isvalidendpoint, state, full_url, cancelevent)
                future_to_endpoint[fut] = new_ep

            total = len(future_to_endpoint)
            completed_count = 0

            for fut in as_completed(future_to_endpoint):
                if cancelevent.is_set():
                    break
                completed_count += 1
                sys.stdout.write("\r\x1b[2K")
                sys.stdout.flush()

                try:
                    valid = fut.result()
                except Exception:
                    valid = False

                ep = future_to_endpoint[fut]
                if valid is not False:
                    if valid == 403:
                        print(f"{BROWN}[+] found endpoint: {ep}{RESET}".lower())
                    else:
                        print(f"{GREEN}[+] found endpoint: {ep}{RESET}".lower())
                        state['endpoints'].add(ep)
                        state['endpoints_scanned'].add(ep)
                        to_process.append(ep)

                pct = int((completed_count / total) * 100)
                sys.stdout.write(f"\r[+] progress: {completed_count}/{total} ({pct}%)")
                sys.stdout.flush()

            sys.stdout.write("\n")
            sys.stdout.flush()
        except KeyboardInterrupt:
            cancelevent.set()
            executor.shutdown(wait=False)
            print("\n> cancelling")
            return
        finally:
            executor.shutdown(wait=True)
            signal.signal(signal.SIGTSTP, old_handler)

        processed.add(current)

    print("[+] subdirectory enumeration complete".lower())
    print(f"[+] total endpoints found: {len(state['endpoints'])}".lower())
    debugprint(state, f"subdirectory enumeration complete, total endpoints: {len(state['endpoints'])}")


def checkforsshkeys(url):

    filename = os.path.basename(urlparse(url).path)
    if filename == "id_rsa":
        print(f"{GOLD}[+] ssh private key found{RESET}")
    elif filename == "id_rsa.pub":
        print(f"{GOLD}[+] ssh public key found{RESET}")


# extract functions
def extractcredentials(state, html):

    text = unescape(html)
    text_clean = re.sub(r"<.*?>", "", text)
    for user in set(re.findall(r'(?i)username["\']?[:=]\s?["\']?([\w\.-]+)', text_clean)):
        if user not in state['discovered_users']:
            state['discovered_users'].add(user)
            print(f"[+] found username: {user}")
    for pwd in set(re.findall(r'(?i)password["\']?[:=]\s?["\']?([\w@#$%^&*]+)', text_clean)):
        if pwd not in state['discovered_passwords']:
            state['discovered_passwords'].add(pwd)
            print(f"{GOLD}[+] found password: {pwd}{RESET}")
    for user, pwd in set(re.findall(r"\b([\w\.-]+):([\w@#$%^&*]+)", text_clean)):
        if user in state['wordlist'] or user in state['discovered_users']:
            cred = f"{user}:{pwd}"
            if cred not in state['discovered_credentials']:
                state['discovered_credentials'].add(cred)
                print(f"{GREEN}[+] found credential: {GOLD}{cred}{GREEN}{RESET}")


def extractwordlistmatches(state, html):

    words = re.findall(r"\b[\w-]+\b", html)
    lower_set = {u.lower() for u in state['wordlist']}
    for w in words:
        if w.lower() in lower_set and w not in state['discovered_wordlist_users']:
            state['discovered_wordlist_users'].add(w)
            print(f"{GREEN}[+] possible username found in source: {w}{RESET}")


def extractpasswordmatches(state, html):

    words = re.findall(r"\b[\w@#$%^&*_-]+\b", html)
    lower_pw = {p.lower() for p in state['password_wordlist']}
    for w in words:
        if w.lower() in lower_pw and w not in state['discovered_password_wordlist_matches']:
            state['discovered_password_wordlist_matches'].add(w)
            print(f"{GREEN}[+] possible password found in source: {w}{RESET}")


def extracthashes(state, html):

    txt = re.sub(r"<.*?>", "", unescape(html))
    for htype, pattern in state['hash_patterns'].items():
        for match in re.findall(pattern, txt):
            if match not in state['found_hashes'][htype]:
                state['found_hashes'][htype].add(match)
                print(f"{GREEN}[+] found {htype} hash: {GOLD}{match}{GREEN}{RESET}")


def shannonentropy(data):

    if not data:
        return 0
    entropy = 0
    length = len(data)
    for c in set(data):
        p = data.count(c) / length
        entropy -= p * math.log(p, 2)
    return entropy


def extractmiscsecrets(state, text):

    # environment variables
    env_matches = re.findall(r'^([A-Z0-9_]+)=(.+)$', text, re.MULTILINE)
    for key, val in env_matches:
        sec = f"{key}={val}"
        if sec not in state['misc_secrets']['environment']:
            state['misc_secrets']['environment'].add(sec)
            print(f"{GOLD}[+] found environment variable: {sec}{RESET}")

    # google api keys
    api_keys = re.findall(r'AIza[0-9A-Za-z_-]+', text)
    for key in api_keys:
        if key not in state['misc_secrets']['google_api_keys']:
            state['misc_secrets']['google_api_keys'].add(key)
            print(f"{GOLD}[+] found api key: {key}{RESET}")

    # aws access keys
    aws_access = re.findall(r'(AKIA[0-9A-Z]{16})', text)
    for key in aws_access:
        if key not in state['misc_secrets']['aws_access_keys']:
            state['misc_secrets']['aws_access_keys'].add(key)
            print(f"{GOLD}[+] found aws access key: {key}{RESET}")

    # aws secret keys
    aws_secret = re.findall(r'aws_secret_access_key["\']?\s*[:=]\s*["\']?([A-Za-z0-9/+=]{40})', text, re.IGNORECASE)
    for key in aws_secret:
        if key not in state['misc_secrets']['aws_secret_keys']:
            state['misc_secrets']['aws_secret_keys'].add(key)
            print(f"{GOLD}[+] found aws secret key: {key}{RESET}")

    # jwt tokens
    jwt_matches = re.findall(r'([A-Za-z0-9-_]+\.[A-Za-z0-9-_]+\.[A-Za-z0-9-_]+)', text)
    for token in jwt_matches:
        if token not in state['misc_secrets']['jwt_tokens']:
            state['misc_secrets']['jwt_tokens'].add(token)
            print(f"{GOLD}[+] found jwt token: {token}{RESET}")

    # high entropy strings
    candidates = re.findall(r"\b[A-Za-z0-9+/=]{20,}\b", text)
    for cand in candidates:
        if cand not in state['misc_secrets']['high_entropy'] and shannonentropy(cand) > 4.0:
            state['misc_secrets']['high_entropy'].add(cand)
            print(f"{GOLD}[+] found high entropy string: {cand}{RESET}")


def extractlinks(state, html, full_url):

    ignored_exts = {'.css', '.js', '.png', '.jpg', '.jpeg', '.svg', '.gif', '.pdf', '.zip', '.tar.gz', '.ttf', '.xls', '.ico', '.xsl', '.php'}
    base_url = full_url if full_url.endswith('/') else full_url + '/'
    for link in re.findall(r'<a\s+[^>]*href=["\'](.*?)["\']', html):
        full = urljoin(base_url, link)
        p = urlparse(full)
        if p.netloc and p.netloc != state['target']:
            continue
        path = p.path.rstrip('/')
        if not path or any(path.endswith(ext) for ext in ignored_exts):
            continue
        if not isvalidendpoint(state, full, state['cancelevent']):
            continue
        if path not in state['endpoints'] and path not in state['discovered_links']:
            state['endpoints'].add(path)
            state['discovered_links'].add(path)
            print(f"[+] discovered new link: {path}")



def checkftpcredentials(state):

    if not state['discovered_credentials']:
        print("[-] no discovered credentials to check via ftp")
        return
    for cred in state['discovered_credentials']:
        user, pwd = cred.split(':', 1)
        try:
            ftp_conn = ftplib.FTP(state['target'], timeout=5)
            ftp_conn.login(user, pwd)
            print(f"{GREEN}[+] valid ftp credentials: {GOLD}{user}:{pwd}{GREEN}{RESET}")
            state['valid_ftp_credentials'].add(cred)
            ftp_conn.quit()
        except ftplib.error_perm:
            print(f"[-] ftp credential failed: {cred}")
        except Exception:
            pass


def checksshcredentials(state):

    if loadparamiko() is None:
        print(
            f"{RED}[-] paramiko is unavailable: "
            f"{DEPENDENCY_ERRORS.get('paramiko', 'import failed')}{RESET}".lower())
        return

    if not state['discovered_credentials'] and not state['test_credentials']:
        print("[-] no discovered credentials to check via ssh")
        return
    for cred in state['discovered_credentials'] | state['test_credentials']:
        user, pwd = cred.split(':', 1)
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            ssh.connect(state['target'], username=user, password=pwd, timeout=5)
            print(f"{GREEN}[+] valid ssh credentials: {GOLD}{user}:{pwd}{GREEN}{RESET}")
            state['valid_ssh_credentials'].add(cred)
        except Exception:
            pass
        finally:
            ssh.close()


def scantxtfile(state, url):

    try:
        r = requestsession(state).get(url, timeout=5)
        if r.status_code == 200:
            extractpasswordmatches(state, r.text)
            print(f"[+] scanned txt file: {os.path.basename(url)}")
            checkforsshkeys(url)
            extractwordlistmatches(state, r.text)
            extractcredentials(state, r.text)
            extracthashes(state, r.text)
            extractmiscsecrets(state, r.text)
        else:
            print(f"{RED}[-] failed to scan txt file: {url}{RESET}")
    except Exception:
        print(f"{RED}[-] error accessing txt file: {url}{RESET}")


def scansqlfile(state, url):

    scantxtfile(state, url)


def scandbfile(state, url):

    scantxtfile(state, url)


# check function
def check(state):
    # ftp
    print("[+] checking ftp credentials...")
    if state.get('ftp_tested'):
        checkftpcredentials(state)
    else:
        print(f"{GREY}[-] ftp port 21 is closed, skipping ftp credential checking{RESET}".lower())

    # ssh
    print("[+] checking ssh credentials...")
    if state.get('ssh_tested'):
        checksshcredentials(state)
    else:
        print(f"{GREY}[-] ssh port 22 is closed, skipping ssh credential checking{RESET}".lower())


def t1osselftest():

    loadrequests()
    loadparamiko()
    if DEPENDENCY_ERRORS:
        checks = {
            't1os_data_path': T1OS_DATA_DIRECTORY == '/software/creep data',
            'requests': requests is not None,
            'paramiko': paramiko is not None,
        }
        result = {
            'format': 1,
            'passed': False,
            'checks': checks,
            'dependency_errors': dict(DEPENDENCY_ERRORS),
            'script': os.path.abspath(__file__),
        }
        writet1osselftest(result)
        return 1

    state = startup()
    executecommand(state, 'set target 127.0.0.1:65535')
    executecommand(state, 'add endpoints api/v1,login')
    executecommand(state, 'set debug true')
    executecommand(state, 'show options')
    executecommand(state, 'help')

    sample = (
        'username=development\npassword=password\n'
        'development:password\n'
        'API_TOKEN=abcdefghijklmnopqrstuvwxyz012345\n'
        '0123456789abcdef0123456789abcdef'
    )
    extractcredentials(state, sample)
    extractwordlistmatches(state, sample)
    extractpasswordmatches(state, sample)
    extracthashes(state, sample)
    extractmiscsecrets(state, sample)

    checks = {
        't1os_data_path': T1OS_DATA_DIRECTORY == '/software/creep data',
        'requests': bool(getattr(requests, '__version__', '')),
        'paramiko': bool(getattr(paramiko, '__version__', '')),
        'target': state['target'] == '127.0.0.1:65535',
        'endpoint_expansion': expandendpoint('/api/v1') == ['/api', '/api/v1'],
        'credentials': 'development:password' in state['discovered_credentials'],
        'hashes': bool(state['found_hashes']['md5']),
        'built_in_usernames': 'development' in state['wordlist'],
        'built_in_passwords': 'password' in state['password_wordlist'],
        'built_in_directories': 'api' in state['directory_list'],
    }
    result = {
        'format': 1,
        'passed': all(checks.values()),
        'checks': checks,
        'requests_version': str(getattr(requests, '__version__', '')),
        'paramiko_version': str(getattr(paramiko, '__version__', '')),
        'script': os.path.abspath(__file__),
    }
    writet1osselftest(result)
    return 0 if result['passed'] else 1


def writet1osselftest(result):

    result_path = os.path.join(
        os.path.expanduser('~'), '.creep-self-test.json')
    temporary_path = result_path + f'.{os.getpid()}.tmp'
    with open(temporary_path, 'w', encoding='utf-8') as stream:
        json.dump(result, stream, sort_keys=True, separators=(',', ':'))
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary_path, result_path)
    print('T1OS_CREEP_SELF_TEST=' + json.dumps(result, sort_keys=True))


def writecreepinteractivestatus(state, stage, sequence, command='', error=''):

    if os.environ.get('T1OS_VM_TEST') != '1':
        return
    payload = {
        'format': 1,
        'pid': os.getpid(),
        'stage': str(stage),
        'sequence': int(sequence),
        'command': str(command),
        'target': str(state.get('target') or ''),
        'endpoints': sorted(str(value) for value in state.get('endpoints', set())),
        'debug': bool(state.get('debug')),
        'error': str(error),
    }
    temporary_path = CREEP_INTERACTIVE_STATUS_PATH + f'.{os.getpid()}.tmp'
    with open(temporary_path, 'w', encoding='utf-8') as stream:
        json.dump(payload, stream, sort_keys=True, separators=(',', ':'))
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary_path, CREEP_INTERACTIVE_STATUS_PATH)


def main(state):

    sequence = 0
    command = ''
    writecreepinteractivestatus(state, 'ready', sequence)
    try:
        while True:
            cmd = safeinput('> ')
            if cmd is None:
                break
            if not cmd.strip():
                continue
            command = cmd.strip()
            try:
                executecommand(state, cmd)
                sequence += 1
                writecreepinteractivestatus(
                    state, 'running', sequence, command)
            except KeyboardInterrupt:
                print('\n> cancelling')
                continue
    finally:
        writecreepinteractivestatus(state, 'exited', sequence, command)


# execute main
if __name__ == "__main__":
    if '--self-test' in sys.argv:
        raise SystemExit(t1osselftest())
    try:
        state = startup()
        main(state)
    except Exception as error:
        writecreepinteractivestatus(
            {}, 'failed', 0,
            error=f'{type(error).__name__}: {error}')
        raise
