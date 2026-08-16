#!"/the one/software/python/bin/python" -B

"""
inputserver.py

input server is the input daemon of The One OS.
"""



## imports
import os
import sys
import time
import json
import errno
import fcntl
import socket
import stat
import struct
import select
import signal
import random
import selectors

sys.path.insert(0, '/the one/build')

from GODDESS.GODDESS import formatlog



## globals

# paths
EPHBASE = "/.ephemeral/inputserver"
SOCKPATH = "/.ephemeral/inputserver/accept.sock"
LOGFILE = "/the one/logs/inputserver.py.log"
NODEDIR = "/the one/drivers/nodes/input"
PROCESSROOT = "/the one/drivers/processes"
MOUSESETTINGS = os.environ.get(
    "T1OS_MOUSE_SETTINGS", "/the one/settings/mouse/settings.json")
SESSIONGID = int(os.environ.get("T1OS_SESSION_GID", "1000"))

# state
SERVERRUN = True
sel = selectors.DefaultSelector()
clients = {}
# Per-event input logging can expose passwords and other private text.  Keep it
# disabled in disposable VM tests as well as in the ordinary appliance.
DEBUGINPUTSERVER = False
EV_SIZE = 24
EV_FORMAT = "qqHHi"
EV_READ_EVENTS = 256
EV_READ_BYTES = EV_SIZE * EV_READ_EVENTS
_DEVICE_SELECTOR_FDS = set()
CLIENTINBUFLIMIT = 64 * 1024
CLIENTOUTBUFLIMIT = 1024 * 1024
CLIENTFLUSHBYTES = 64 * 1024
# Coalesce pointer events only behind real socket backpressure.  An additional
# time gate here stacked with WindowServer and application gates.
CLIENTPOINTERINTERVAL = 0.0
CLIENTPOINTERCOALESCED = 0
CLIENTOUTBUFPEAK = 0
TRUSTEDPARENTPID = os.getppid()
TRUSTEDPARENTSTART = None
RAWINPUTSUBSCRIPTIONS = frozenset((
    "pointer", "button", "scroll", "key", "text",
))

# inputs
EV_SYN = 0x00
EV_KEY = 0x01
EV_MSC = 0x04
EV_REL = 0x02
EV_ABS = 0x03
REL_X = 0x00
REL_Y = 0x01
REL_HWHEEL = 0x06
REL_WHEEL = 0x08
REL_WHEELHI = 0x0b
REL_HWHEELHI = 0x0c
ABS_X = 0x00
ABS_Y = 0x01
ABS_MT_POSITION_X = 0x35
ABS_MT_POSITION_Y = 0x36
BTN_LEFT = 0x110
BTN_RIGHT = 0x111
BTN_MIDDLE = 0x112
BTN_SIDE = 0x113
BTN_EXTRA = 0x114
BTN_FORWARD = 0x115
BTN_BACK = 0x116
BTN_TOUCH = 0x14a
BTN_STYLUS = 0x14b
BTN_STYLUS2 = 0x14c
SYN_REPORT = 0
_KBD_FD = None
_MEDIA_FDS = {}
_MEDIA_REJECTED = {}
_MEDIA_LASTSCAN = 0.0
MEDIA_SCAN_INTERVAL = 3.0
_MOUSE_FD = None
_MOUSEBTN_FD = None
_MOUSEWHEEL_FD = None
_MOUSEABS = None
_MOUSEHASLEFT = False
_KBDPATH = None
_MOUSEPATH = None
_MOUSEBTNPATH = None
_MOUSEWHEELPATH = None
_MOUSEBTN_OPENAT = 0.0
_MOUSEBTN_SEEN = False
_MOUSEBTN_LASTPROBE = 0.0
_no_device_logged = False
_mouse_open_logged = False
_KBD_OPENAT = 0.0
_KBD_SEEN = False
_KBD_LASTPROBE = 0.0
KBD_SILENCE_SECONDS = 2.0
KBD_PROBE_COOLDOWN = 3.0
_kbdreject = {}
_MOUSE_OPENAT = 0.0
_MOUSE_SEEN = False
_MOUSE_LASTPROBE = 0.0
MOUSE_SILENCE_SECONDS = 2.0
MOUSE_PROBE_COOLDOWN = 3.0
_mods = {
    "lshift": False,
    "rshift": False,
    "lctrl": False,
    "rctrl": False,
    "lalt": False,
    "ralt": False,
    "lwin": False,
    "rwin": False,
    "caps": False,
    "num": False,
    "scroll": False,
}
_repeatfilter = {}
SCREENW = 1920
SCREENH = 1080
POINTERX = SCREENW // 2
POINTERY = SCREENH // 2
SCROLLX = 0
SCROLLY = 0
SCROLLHIX = 0
SCROLLHIY = 0
LASTABSX = None
LASTABSY = None
POINTERSPEED = 1.0
POINTERREMAINDERX = 0.0
POINTERREMAINDERY = 0.0
POINTERSAVEINTERVAL = 0.25
POINTERSAVELAST = 0.0
POINTERSAVEDIRTY = False

# evdev key codes
KEY_ESC = 1
KEY_1 = 2
KEY_2 = 3
KEY_3 = 4
KEY_4 = 5
KEY_5 = 6
KEY_6 = 7
KEY_7 = 8
KEY_8 = 9
KEY_9 = 10
KEY_0 = 11
KEY_MINUS = 12
KEY_EQUAL = 13
KEY_BACKSPACE = 14
KEY_TAB = 15
KEY_Q = 16
KEY_W = 17
KEY_E = 18
KEY_R = 19
KEY_T = 20
KEY_Y = 21
KEY_U = 22
KEY_I = 23
KEY_O = 24
KEY_P = 25
KEY_LEFTBRACE = 26
KEY_RIGHTBRACE = 27
KEY_ENTER = 28
KEY_LEFTCTRL = 29
KEY_A = 30
KEY_S = 31
KEY_D = 32
KEY_F = 33
KEY_G = 34
KEY_H = 35
KEY_J = 36
KEY_K = 37
KEY_L = 38
KEY_SEMICOLON = 39
KEY_APOSTROPHE = 40
KEY_GRAVE = 41
KEY_LEFTSHIFT = 42
KEY_BACKSLASH = 43
KEY_Z = 44
KEY_X = 45
KEY_C = 46
KEY_V = 47
KEY_B = 48
KEY_N = 49
KEY_M = 50
KEY_COMMA = 51
KEY_DOT = 52
KEY_SLASH = 53
KEY_RIGHTSHIFT = 54
KEY_KPASTERISK = 55
KEY_LEFTALT = 56
KEY_SPACE = 57
KEY_CAPSLOCK = 58
KEY_F1 = 59
KEY_F2 = 60
KEY_F3 = 61
KEY_F4 = 62
KEY_F5 = 63
KEY_F6 = 64
KEY_F7 = 65
KEY_F8 = 66
KEY_F9 = 67
KEY_F10 = 68
KEY_NUMLOCK = 69
KEY_SCROLLLOCK = 70
KEY_KP7 = 71
KEY_KP8 = 72
KEY_KP9 = 73
KEY_KPMINUS = 74
KEY_KP4 = 75
KEY_KP5 = 76
KEY_KP6 = 77
KEY_KPPLUS = 78
KEY_KP1 = 79
KEY_KP2 = 80
KEY_KP3 = 81
KEY_KP0 = 82
KEY_KPDOT = 83
KEY_ZENKAKUHANKAKU = 85
KEY_102ND = 86
KEY_F11 = 87
KEY_F12 = 88
KEY_RO = 89
KEY_KATAKANA = 90
KEY_HIRAGANA = 91
KEY_HENKAN = 92
KEY_KATAKANAHIRAGANA = 93
KEY_MUHENKAN = 94
KEY_KPJPCOMMA = 95
KEY_KPENTER = 96
KEY_RIGHTCTRL = 97
KEY_KPSLASH = 98
KEY_SYSRQ = 99
KEY_RIGHTALT = 100
KEY_LINEFEED = 101
KEY_HOME = 102
KEY_UP = 103
KEY_PAGEUP = 104
KEY_LEFT = 105
KEY_RIGHT = 106
KEY_END = 107
KEY_DOWN = 108
KEY_PAGEDOWN = 109
KEY_INSERT = 110
KEY_DELETE = 111
KEY_MACRO = 112
KEY_MUTE = 113
KEY_VOLUMEDOWN = 114
KEY_VOLUMEUP = 115
KEY_POWER = 116
KEY_KPEQUAL = 117
KEY_KPPLUSMINUS = 118
KEY_PAUSE = 119
KEY_KPCOMMA = 121
KEY_HANGEUL = 122
KEY_HANJA = 123
KEY_YEN = 124
KEY_LEFTMETA = 125
KEY_RIGHTMETA = 126
KEY_COMPOSE = 127
KEY_STOP = 128
KEY_AGAIN = 129
KEY_PROPS = 130
KEY_UNDO = 131
KEY_FRONT = 132
KEY_COPY = 133
KEY_OPEN = 134
KEY_PASTE = 135
KEY_FIND = 136
KEY_CUT = 137
KEY_HELP = 138
KEY_MENU = 139
KEY_CALC = 140
KEY_SETUP = 141
KEY_SLEEP = 142
KEY_WAKEUP = 143
KEY_FILE = 144
KEY_SENDFILE = 145
KEY_DELETEFILE = 146
KEY_XFER = 147
KEY_PROG1 = 148
KEY_PROG2 = 149
KEY_WWW = 150
KEY_MSDOS = 151
KEY_COFFEE = 152
KEY_ROTATE_DISPLAY = 153
KEY_CYCLEWINDOWS = 154
KEY_MAIL = 155
KEY_BOOKMARKS = 156
KEY_COMPUTER = 157
KEY_BACK = 158
KEY_FORWARD = 159
KEY_CLOSECD = 160
KEY_EJECTCD = 161
KEY_EJECTCLOSECD = 162
KEY_NEXTSONG = 163
KEY_PLAYPAUSE = 164
KEY_PREVIOUSSONG = 165
KEY_STOPCD = 166
KEY_RECORD = 167
KEY_REWIND = 168
KEY_PHONE = 169
KEY_ISO = 170
KEY_CONFIG = 171
KEY_HOMEPAGE = 172
KEY_REFRESH = 173
KEY_EXIT = 174
KEY_MOVE = 175
KEY_EDIT = 176
KEY_SCROLLUP = 177
KEY_SCROLLDOWN = 178
KEY_KPLEFTPAREN = 179
KEY_KPRIGHTPAREN = 180
KEY_NEW = 181
KEY_REDO = 182
KEY_F13 = 183
KEY_F14 = 184
KEY_F15 = 185
KEY_F16 = 186
KEY_F17 = 187
KEY_F18 = 188
KEY_F19 = 189
KEY_F20 = 190
KEY_F21 = 191
KEY_F22 = 192
KEY_F23 = 193
KEY_F24 = 194
KEY_PLAYCD = 200
KEY_PAUSECD = 201
KEY_PROG3 = 202
KEY_PROG4 = 203
KEY_DASHBOARD = 204
KEY_SUSPEND = 205
KEY_CLOSE = 206
KEY_PLAY = 207
KEY_FASTFORWARD = 208
KEY_BASSBOOST = 209
KEY_PRINT = 210
KEY_HP = 211
KEY_CAMERA = 212
KEY_SOUND = 213
KEY_QUESTION = 214
KEY_EMAIL = 215
KEY_CHAT = 216
KEY_SEARCH = 217
KEY_CONNECT = 218
KEY_FINANCE = 219
KEY_SPORT = 220
KEY_SHOP = 221
KEY_ALTERASE = 222
KEY_CANCEL = 223
KEY_BRIGHTNESSDOWN = 224
KEY_BRIGHTNESSUP = 225
KEY_MEDIA = 226
KEY_SWITCHVIDEOMODE = 227
KEY_KBDILLUMTOGGLE = 228
KEY_KBDILLUMDOWN = 229
KEY_KBDILLUMUP = 230
KEY_SEND = 231
KEY_REPLY = 232
KEY_FORWARDMAIL = 233
KEY_SAVE = 234
KEY_DOCUMENTS = 235
KEY_BATTERY = 236
KEY_BLUETOOTH = 237
KEY_WLAN = 238
KEY_UWB = 239
KEY_UNKNOWN = 240

# canonical key tables
KEYCODES = {
    KEY_ESC: "ESC",
    KEY_TAB: "TAB",
    KEY_CAPSLOCK: "CAPSLOCK",
    KEY_LEFTSHIFT: "LSHIFT",
    KEY_RIGHTSHIFT: "RSHIFT",
    KEY_LEFTCTRL: "LCTRL",
    KEY_RIGHTCTRL: "RCTRL",
    KEY_LEFTALT: "LALT",
    KEY_RIGHTALT: "RALT",
    KEY_LEFTMETA: "LWIN",
    KEY_RIGHTMETA: "RWIN",
    KEY_MENU: "APPS",
    KEY_ENTER: "ENTER",
    KEY_BACKSPACE: "BACKSPACE",
    KEY_SPACE: "SPACE",
    KEY_HOME: "HOME",
    KEY_END: "END",
    KEY_PAGEUP: "PGUP",
    KEY_PAGEDOWN: "PGDN",
    KEY_INSERT: "INS",
    KEY_DELETE: "DELETE",
    KEY_UP: "UP",
    KEY_DOWN: "DOWN",
    KEY_LEFT: "LEFT",
    KEY_RIGHT: "RIGHT",
    KEY_SYSRQ: "PRTSCR",
    KEY_PAUSE: "PAUSE",
    KEY_SCROLLLOCK: "SCROLLLOCK",
    KEY_NUMLOCK: "NUMLOCK",
    KEY_F1: "F1",
    KEY_F2: "F2",
    KEY_F3: "F3",
    KEY_F4: "F4",
    KEY_F5: "F5",
    KEY_F6: "F6",
    KEY_F7: "F7",
    KEY_F8: "F8",
    KEY_F9: "F9",
    KEY_F10: "F10",
    KEY_F11: "F11",
    KEY_F12: "F12",
    KEY_F13: "F13",
    KEY_F14: "F14",
    KEY_F15: "F15",
    KEY_F16: "F16",
    KEY_F17: "F17",
    KEY_F18: "F18",
    KEY_F19: "F19",
    KEY_F20: "F20",
    KEY_F21: "F21",
    KEY_F22: "F22",
    KEY_F23: "F23",
    KEY_F24: "F24",
    KEY_KP0: "NUMPAD0",
    KEY_KP1: "NUMPAD1",
    KEY_KP2: "NUMPAD2",
    KEY_KP3: "NUMPAD3",
    KEY_KP4: "NUMPAD4",
    KEY_KP5: "NUMPAD5",
    KEY_KP6: "NUMPAD6",
    KEY_KP7: "NUMPAD7",
    KEY_KP8: "NUMPAD8",
    KEY_KP9: "NUMPAD9",
    KEY_KPDOT: "NUMPADDOT",
    KEY_KPPLUS: "NUMPADPLUS",
    KEY_KPMINUS: "NUMPADMINUS",
    KEY_KPASTERISK: "NUMPADMUL",
    KEY_KPSLASH: "NUMPADDIV",
    KEY_KPENTER: "NUMPADENTER",
    KEY_KPEQUAL: "NUMPADEQUAL",
    KEY_KPPLUSMINUS: "NUMPADPLUSMINUS",
    KEY_KPCOMMA: "NUMPADCOMMA",
    KEY_KPJPCOMMA: "NUMPADJPCOMMA",
    KEY_KPLEFTPAREN: "NUMPADLPAREN",
    KEY_KPRIGHTPAREN: "NUMPADRPAREN",
    KEY_MUTE: "MUTE",
    KEY_VOLUMEDOWN: "VOLDOWN",
    KEY_VOLUMEUP: "VOLUP",
    KEY_PLAYPAUSE: "PLAYPAUSE",
    KEY_PLAYCD: "PLAYPAUSE",
    KEY_PAUSECD: "PLAYPAUSE",
    KEY_PLAY: "PLAYPAUSE",
    KEY_STOPCD: "STOP",
    KEY_NEXTSONG: "NEXT",
    KEY_PREVIOUSSONG: "PREV",
    KEY_RECORD: "RECORD",
    KEY_REWIND: "REWIND",
    KEY_FASTFORWARD: "FASTFORWARD",
    KEY_WWW: "BROWSER",
    KEY_HOMEPAGE: "HOMEPAGE",
    KEY_REFRESH: "REFRESH",
    KEY_BACK: "BROWSERBACK",
    KEY_FORWARD: "BROWSERFORWARD",
    KEY_SEARCH: "SEARCH",
    KEY_MAIL: "MAIL",
    KEY_COMPUTER: "MYCOMPUTER",
    KEY_CALC: "CALC",
    KEY_SLEEP: "SLEEP",
    KEY_WAKEUP: "WAKE",
    KEY_POWER: "POWER",
    KEY_PRINT: "PRINT",
    KEY_SAVE: "SAVE",
    KEY_OPEN: "OPEN",
    KEY_COPY: "COPY",
    KEY_PASTE: "PASTE",
    KEY_CUT: "CUT",
    KEY_UNDO: "UNDO",
    KEY_REDO: "REDO",
    KEY_FIND: "FIND",
    KEY_HELP: "HELP",
    KEY_BRIGHTNESSDOWN: "BRIGHTDOWN",
    KEY_BRIGHTNESSUP: "BRIGHTUP",
    KEY_KBDILLUMTOGGLE: "KBDLITTOGGLE",
    KEY_KBDILLUMDOWN: "KBDLITDOWN",
    KEY_KBDILLUMUP: "KBDLITUP",
    KEY_UNKNOWN: "UNKNOWN",
}

KEYLETTERS = {
    KEY_A: "A", KEY_B: "B", KEY_C: "C", KEY_D: "D", KEY_E: "E",
    KEY_F: "F", KEY_G: "G", KEY_H: "H", KEY_I: "I", KEY_J: "J",
    KEY_K: "K", KEY_L: "L", KEY_M: "M", KEY_N: "N", KEY_O: "O",
    KEY_P: "P", KEY_Q: "Q", KEY_R: "R", KEY_S: "S", KEY_T: "T",
    KEY_U: "U", KEY_V: "V", KEY_W: "W", KEY_X: "X", KEY_Y: "Y",
    KEY_Z: "Z",
}

KEYPRINTABLE = {
    KEY_1: "1",
    KEY_2: "2",
    KEY_3: "3",
    KEY_4: "4",
    KEY_5: "5",
    KEY_6: "6",
    KEY_7: "7",
    KEY_8: "8",
    KEY_9: "9",
    KEY_0: "0",
    KEY_MINUS: "-",
    KEY_EQUAL: "=",
    KEY_LEFTBRACE: "[",
    KEY_RIGHTBRACE: "]",
    KEY_BACKSLASH: "\\",
    KEY_SEMICOLON: ";",
    KEY_APOSTROPHE: "'",
    KEY_GRAVE: "`",
    KEY_COMMA: ",",
    KEY_DOT: ".",
    KEY_SLASH: "/",
}

SHIFTED = {
    "1": "!",
    "2": "@",
    "3": "#",
    "4": "$",
    "5": "%",
    "6": "^",
    "7": "&",
    "8": "*",
    "9": "(",
    "0": ")",
    "-": "_",
    "=": "+",
    "[": "{",
    "]": "}",
    "\\": "|",
    ";": ":",
    "'": '"',
    ",": "<",
    ".": ">",
    "/": "?",
    "`": "~",
}

# alias tables
ALIASES = {}

GENERICMODS = {
    "SHIFT": ("LSHIFT", "RSHIFT"),
    "CTRL": ("LCTRL", "RCTRL"),
    "ALT": ("LALT", "RALT"),
    "WIN": ("LWIN", "RWIN"),
    "META": ("LWIN", "RWIN"),
    "SUPER": ("LWIN", "RWIN"),
}

ALIASGROUPS = {
    "ESC": ["ESC", "ESCAPE", "VK_ESCAPE", "<ESC>", "<ESCAPE>"],
    "ENTER": ["ENTER", "RETURN", "VK_RETURN", "<ENTER>", "<RETURN>"],
    "TAB": ["TAB", "VK_TAB", "<TAB>"],
    "BACKSPACE": ["BACKSPACE", "BKSP", "VK_BACK", "<BACKSPACE>"],
    "SPACE": ["SPACE", "SPACEBAR", "VK_SPACE", "<SPACE>"],
    "DELETE": ["DELETE", "DEL", "VK_DELETE", "<DEL>", "<DELETE>"],
    "INS": ["INS", "INSERT", "VK_INSERT", "<INS>", "<INSERT>"],
    "HOME": ["HOME", "VK_HOME", "<HOME>"],
    "END": ["END", "VK_END", "<END>"],
    "PGUP": ["PGUP", "PAGEUP", "PRIOR", "VK_PRIOR", "<PGUP>"],
    "PGDN": ["PGDN", "PAGEDOWN", "NEXT", "VK_NEXT", "<PGDN>"],
    "UP": ["UP", "ARROWUP", "VK_UP", "<UP>"],
    "DOWN": ["DOWN", "ARROWDOWN", "VK_DOWN", "<DOWN>"],
    "LEFT": ["LEFT", "ARROWLEFT", "VK_LEFT", "<LEFT>"],
    "RIGHT": ["RIGHT", "ARROWRIGHT", "VK_RIGHT", "<RIGHT>"],
    "LSHIFT": ["LSHIFT", "LEFTSHIFT"],
    "RSHIFT": ["RSHIFT", "RIGHTSHIFT"],
    "LCTRL": ["LCTRL", "LEFTCTRL", "LCONTROL", "LEFTCONTROL"],
    "RCTRL": ["RCTRL", "RIGHTCTRL", "RCONTROL", "RIGHTCONTROL"],
    "LALT": ["LALT", "LEFTALT"],
    "RALT": ["RALT", "RIGHTALT", "ALTGR", "RIGHTALTGR"],
    "LWIN": ["LWIN", "LEFTWIN", "LGUI", "LEFTMETA", "LEFTSUPER"],
    "RWIN": ["RWIN", "RIGHTWIN", "RGUI", "RIGHTMETA", "RIGHTSUPER"],
    "APPS": ["APPS", "MENU", "CONTEXT", "CONTEXTMENU", "VK_APPS"],
    "CAPSLOCK": ["CAPSLOCK", "CAPS", "VK_CAPITAL"],
    "NUMLOCK": ["NUMLOCK", "VK_NUMLOCK"],
    "SCROLLLOCK": ["SCROLLLOCK", "SCROLL", "VK_SCROLL"],
    "PRTSCR": ["PRTSCR", "PRTSC", "PRINTSCREEN", "VK_SNAPSHOT"],
    "PAUSE": ["PAUSE", "BREAK", "VK_PAUSE"],
}

for canon, names in ALIASGROUPS.items():

    for n in names:

        ALIASES[n.upper()] = canon

for code, k in KEYLETTERS.items():

    ALIASES[k.upper()] = k

for code, ch in KEYPRINTABLE.items():

    ALIASES[ch] = ch
    ALIASES[ch.upper()] = ch

for k in list(SHIFTED.values()):

    ALIASES[k] = k

for i in range(1, 25):

    ALIASES[f"F{i}"] = f"F{i}"
    ALIASES[f"VK_F{i}"] = f"F{i}"

IOCNRBITS = 8
IOCTYPEBITS = 8
IOCSIZEBITS = 14
IOCDIRBITS = 2
IOCNRMASK = (1 << IOCNRBITS) - 1
IOCTYPEMASK = (1 << IOCTYPEBITS) - 1
IOCSIZEMASK = (1 << IOCSIZEBITS) - 1
IOCDIRMASK = (1 << IOCDIRBITS) - 1
IOCNRSHIFT = 0
IOCTYPESHIFT = IOCNRSHIFT + IOCNRBITS
IOCSIZESHIFT = IOCTYPESHIFT + IOCTYPEBITS
IOCDIRSHIFT = IOCSIZESHIFT + IOCSIZEBITS
IOCNONE = 0
IOCWRITE = 1
IOCREAD = 2



# misc functions
def normalizedpointerspeed(value):

    try:

        speed = float(value)

    except (TypeError, ValueError):

        speed = 1.0

    if speed != speed:

        speed = 1.0

    return max(0.25, min(2.0, speed))


def loadpointerspeed():

    global POINTERSPEED, POINTERREMAINDERX, POINTERREMAINDERY

    speed = 1.0

    try:

        with open(MOUSESETTINGS, "r", encoding="utf-8") as stream:

            settings = json.load(stream)

        if isinstance(settings, dict):

            speed = settings.get("cursor_speed", 1.0)

    except Exception:

        pass

    POINTERSPEED = normalizedpointerspeed(speed)

    POINTERREMAINDERX = 0.0

    POINTERREMAINDERY = 0.0

    return POINTERSPEED


def scalepointerdelta(delta, speed, remainder):

    scaled = float(delta) * normalizedpointerspeed(speed) + float(remainder)

    movement = int(scaled)

    return movement, scaled - movement


def readprocessstat(pid):

    """Return immutable Linux process identity fields from /proc."""

    try:
        with open(os.path.join(PROCESSROOT, str(int(pid)), "stat"), "r", encoding="utf-8") as stream:
            value = stream.read(8192)

        end = value.rfind(")")
        if end < 0:
            return None

        fields = value[end + 2:].split()
        if len(fields) <= 19:
            return None

        return {
            "ppid": int(fields[1]),
            "starttime": int(fields[19]),
        }
    except (OSError, TypeError, ValueError):
        return None


def processsecuritydomain(pid):

    root = os.path.join(PROCESSROOT, str(int(pid)), "attr")
    for relative in (os.path.join("t1os", "current"), "current"):
        try:
            with open(
                os.path.join(root, relative),
                "r",
                encoding="utf-8",
                errors="strict",
            ) as stream:
                label = stream.read(256).strip().split("\0", 1)[0]
        except (OSError, TypeError, ValueError, UnicodeError):
            continue

        prefix = "t1os:"
        if label.startswith(prefix):
            return label[len(prefix):]
    return None


def processdomainidentity(pid, capturepidfd=False):

    """Capture the kernel domain and immutable generation of a service peer.

    Input's LSM domain intentionally cannot read another service's executable
    or command line.  A kernel-assigned domain is already bound to the
    measured executable at exec, so raw-input sibling authentication needs no
    access to that confidential process metadata.
    """

    first = readprocessstat(pid)
    if not first:
        return None

    domain = processsecuritydomain(pid)
    second = readprocessstat(pid)
    if (
        not domain
        or not second
        or int(second["starttime"]) != int(first["starttime"])
    ):
        return None

    identity = {
        "pid": int(pid),
        "ppid": int(first["ppid"]),
        "starttime": int(first["starttime"]),
        "executable": "",
        "script": "",
        "domain": domain,
        "pidfd": None,
    }
    if capturepidfd and hasattr(os, "pidfd_open"):
        try:
            identity["pidfd"] = os.pidfd_open(int(pid), 0)
        except OSError:
            pass

    final = readprocessstat(pid)
    if not final or int(final["starttime"]) != int(first["starttime"]):
        closeprocessidentity(identity)
        return None
    return identity


def processscriptpath(pid, executable, arguments):

    """Resolve the program Python actually executed; reject -c/-m identities."""

    def resolved(value):
        value = os.fsdecode(value)
        if not os.path.isabs(value):
            try:
                value = os.path.join(os.readlink(
                    os.path.join(PROCESSROOT, str(int(pid)), "cwd")), value)
            except OSError:
                return None
        return os.path.realpath(value)

    if not arguments:
        return None

    first = os.fsdecode(arguments[0])
    if first.lower().endswith(".py"):
        return resolved(first)

    executable_name = os.path.basename(str(executable or first)).lower()
    if not executable_name.startswith("python"):
        return None

    index = 1
    while index < len(arguments):
        argument = os.fsdecode(arguments[index])

        if argument in ("-c", "-m"):
            return None

        if argument in ("-W", "-X", "--check-hash-based-pycs"):
            index += 2
            continue

        if argument.startswith("-"):
            index += 1
            continue

        return resolved(argument)

    return None


def processidentity(pid, capturepidfd=False):

    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return None

    if pid <= 1:
        return None

    first = readprocessstat(pid)
    if not first:
        return None

    try:
        executable = os.path.realpath(os.readlink(
            os.path.join(PROCESSROOT, str(pid), "exe")))
        with open(os.path.join(PROCESSROOT, str(pid), "cmdline"), "rb") as stream:
            raw = stream.read(64 * 1024)
        arguments = [part for part in raw.split(b"\0") if part]
    except OSError:
        return None

    second = readprocessstat(pid)
    if not second or second["starttime"] != first["starttime"]:
        return None

    identity = {
        "pid": pid,
        "ppid": int(first["ppid"]),
        "starttime": int(first["starttime"]),
        "executable": executable,
        "script": processscriptpath(pid, executable, arguments),
        "domain": processsecuritydomain(pid),
        "pidfd": None,
    }

    if not identity["domain"]:
        return None

    if capturepidfd and hasattr(os, "pidfd_open"):
        try:
            identity["pidfd"] = os.pidfd_open(pid, 0)
        except OSError:
            pass

    # Close the remaining PID-reuse race between the second stat sample,
    # security-label read, and pidfd capture.
    final = readprocessstat(pid)
    if not final or int(final["starttime"]) != int(first["starttime"]):
        closeprocessidentity(identity)
        return None

    return identity


def closeprocessidentity(identity):

    descriptor = identity.get("pidfd") if isinstance(identity, dict) else None
    if descriptor is not None:
        try:
            os.close(descriptor)
        except OSError:
            pass
        identity["pidfd"] = None


def processidentityalive(identity):

    if not isinstance(identity, dict):
        return False

    descriptor = identity.get("pidfd")
    if descriptor is not None:
        try:
            ready, _, _ = select.select([descriptor], [], [], 0)
            if ready:
                return False
        except (OSError, ValueError):
            return False

    current = readprocessstat(identity.get("pid"))
    return bool(
        current
        and int(current["starttime"]) == int(identity.get("starttime", -1))
    )


def processidentitycurrent(identity):

    return bool(
        processidentityalive(identity)
        and processsecuritydomain(identity.get("pid")) == identity.get("domain")
    )


def rawinputclientalive(client, now=None):

    if not isinstance(client, dict):
        return False

    if now is None:
        now = time.monotonic()

    if now < float(client.get("identity_check_at", 0.0)):
        return True

    alive = processidentitycurrent(client.get("identity"))
    client["identity_check_at"] = now + 0.5
    return alive


def initializeipcidentity():

    global TRUSTEDPARENTPID, TRUSTEDPARENTSTART

    TRUSTEDPARENTPID = os.getppid()
    parent = readprocessstat(TRUSTEDPARENTPID)
    TRUSTEDPARENTSTART = parent.get("starttime") if parent else None
    return TRUSTEDPARENTSTART is not None


def authenticatewindowserverpeer(conn):

    """Bind the raw-input channel to our exact WindowServer sibling."""

    if not hasattr(socket, "SO_PEERCRED"):
        return None

    try:
        raw = conn.getsockopt(
            socket.SOL_SOCKET,
            socket.SO_PEERCRED,
            struct.calcsize("3i"),
        )
        pid, uid, gid = struct.unpack("3i", raw)
    except (OSError, struct.error):
        return None

    if uid != os.geteuid():
        return None

    if TRUSTEDPARENTSTART is None and not initializeipcidentity():
        return None

    # WindowServer can connect immediately after exec, before the kernel's
    # measured process-domain leaf is readable to this sibling.  Retry only
    # while the exact PID generation remains unchanged and continue to require
    # the measured window domain plus our captured GODDESS parent generation.
    generation = readprocessstat(pid)
    deadline = time.monotonic() + 0.5
    identity = None
    authorized = False
    while generation and time.monotonic() < deadline:
        candidate = processdomainidentity(pid, capturepidfd=True)
        if candidate:
            parent = readprocessstat(candidate["ppid"])
            authorized = bool(
                candidate["ppid"] == TRUSTEDPARENTPID
                and parent
                and int(parent["starttime"]) == int(TRUSTEDPARENTSTART)
                and candidate.get("domain") == "window"
            )
            if authorized:
                identity = candidate
                break
            closeprocessidentity(candidate)

        current = readprocessstat(pid)
        if (
            not current
            or int(current.get("starttime", -1))
            != int(generation.get("starttime", -2))
        ):
            break
        time.sleep(0.005)

    if not authorized or identity is None:
        return None

    identity["uid"] = int(uid)
    identity["gid"] = int(gid)
    return identity


def stalecustomsocket(path):

    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return False

    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.geteuid():
        raise RuntimeError(f"unsafe stale socket {path}")

    return True


def makepaths():

    try:

        # Raw input is compositor-private. The exact root-owned sticky tmpfs
        # root is its trust anchor; refuse any substituted parent and validate
        # the private child separately before publishing the socket.
        parent = os.path.dirname(os.path.abspath(EPHBASE))
        parentinfo = os.lstat(parent)
        parentmode = stat.S_IMODE(parentinfo.st_mode)
        trustedephemeral = (
            parent == "/.ephemeral"
            and parentinfo.st_uid == 0
            and parentmode == 0o1777
        )
        if (
            not stat.S_ISDIR(parentinfo.st_mode)
            or stat.S_ISLNK(parentinfo.st_mode)
            or (
                not trustedephemeral
                and (
                    parentinfo.st_uid != os.geteuid()
                    or parentmode & 0o022
                )
            )
        ):
            raise PermissionError(f"unsafe input server parent directory {parent}")
        os.makedirs(EPHBASE, mode=0o710, exist_ok=True)
        info = os.lstat(EPHBASE)
        if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise RuntimeError(f"unsafe input server directory {EPHBASE}")
        if info.st_uid != os.geteuid():
            raise PermissionError(
                f"input server directory is not owned by uid {os.geteuid()}")
        os.chown(EPHBASE, -1, SESSIONGID)
        os.chmod(EPHBASE, 0o710)

    except PermissionError:

        # permission denied creating ephemeral base
        print(formatlog('input server', f'permission denied creating {EPHBASE}'))
        return False

    except Exception as e:

        # error creating ephemeral base
        print(formatlog('input server', f'error creating {EPHBASE} {e}'))
        return False

    try:

        # remove stale socket if present
        if stalecustomsocket(SOCKPATH):

            os.unlink(SOCKPATH)

    except PermissionError:

        # permission denied removing stale socket
        print(formatlog('input server', 'permission denied removing stale socket'))
        return False

    except Exception as e:

        # error removing stale socket
        print(formatlog('input server', f'error removing stale socket {e}'))
        return False

    return True


# logging functions
def openlog():

    if not DEBUGINPUTSERVER:
        return

    try:

        # ensure log directory exists
        logdir = os.path.dirname(LOGFILE)
        os.makedirs(logdir, exist_ok=True)

    except PermissionError:

        # permission denied creating log directory
        print(formatlog('input server', 'permission denied creating log directory'))
        return

    except Exception as e:

        # error creating log directory
        print(formatlog('input server', f'error creating log directory {e}'))
        return

    try:

        # open log file for append
        f = open(LOGFILE, "a")

    except PermissionError:

        # permission denied opening log file
        print(formatlog('input server', 'permission denied opening log file'))
        return

    except Exception as e:

        # error opening log file
        print(formatlog('input server', f'error opening log file {e}'))
        return

    try:

        # redirect stdout and stderr to log only if debugging
        if DEBUGINPUTSERVER:

            sys.stdout = f
            sys.stderr = f

            print(formatlog('input server', 'starting'))

    except Exception as e:

        # error redirecting output
        print(formatlog('input server', f'error redirecting output {e}'))
        return


def log(msg):


    if not DEBUGINPUTSERVER:
        return

    # write timestamped log line
    line = formatlog('input server', msg) + '\n'

    with open(LOGFILE, "a") as f:

        f.write(line)

        f.flush()

        os.fsync(f.fileno())

def formatev(ev):

    try:

        if not isinstance(ev, dict):
            return str(ev)

        kind = ev.get("kind")

        if kind == "key":

            return f'kind=key key={ev.get("key")} code={ev.get("code")} state={ev.get("state")} mods={ev.get("mods")}'

        if kind == "text":

            t = ev.get("text", "")
            if t == " ":
                t = "<SPACE>"
            return f'kind=text text={t} mods={ev.get("mods")}'

        if kind == "pointer":

            return f'kind=pointer x={ev.get("x")} y={ev.get("y")} dx={ev.get("dx")} dy={ev.get("dy")} abs={ev.get("abs")}'

        if kind == "button":

            return f'kind=button button={ev.get("button")} state={ev.get("state")} x={ev.get("x")} y={ev.get("y")}'

        if kind == "scroll":

            return f'kind=scroll dx={ev.get("dx")} dy={ev.get("dy")} x={ev.get("x")} y={ev.get("y")}'

        return f'kind={kind} {ev}'

    except Exception as e:

        log(f'error formatting event {e}')
        return "unformattable"


def logrx(devtype, devpath, ev):


    if not DEBUGINPUTSERVER:
        return

    p = devpath if devpath else "<unknown>"

    log(f'rx <- {devtype} {p} {formatev(ev)}')

def logtx(cid, ev, kind=None):


    if not DEBUGINPUTSERVER:
        return

    k = kind if kind else ev.get("kind")

    log(f'tx -> client {cid} sub={k} {formatev(ev)}')

def startserver():

    try:

        # create unix domain socket
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

        # Bind without ever exposing a permissive creation window.
        previousumask = os.umask(0o077)
        try:
            srv.bind(SOCKPATH)
        finally:
            os.umask(previousumask)

        # set permissions
        os.chmod(SOCKPATH, 0o600)

        # listen for clients
        srv.listen(1)

        # set non-blocking
        srv.setblocking(False)

        # register server socket
        sel.register(srv, selectors.EVENT_READ, ("accept", None))

    except PermissionError:

        # permission denied creating server socket
        log(f'permission denied creating input server socket')
        return None

    except Exception as e:

        # error creating server socket
        log(f'error creating input server socket {e}')
        return None


    # log server start
    log(f'inputserver listening on {SOCKPATH}')

    return srv


def acceptclient(srv):

    try:

        # accept incoming client
        conn, _ = srv.accept()

        # set non-blocking
        conn.setblocking(False)

    except BlockingIOError:

        return

    except Exception as e:

        # error accepting client
        log(f'error accepting client {e}')
        return

    try:

        # There is exactly one consumer of raw input: WindowServer. Authenticate
        # before registering or writing protocol bytes so rejected peers cannot
        # race the compositor for ownership.
        if clients:
            raise PermissionError("raw input consumer already connected")

        identity = authenticatewindowserverpeer(conn)
        if not identity:
            raise PermissionError("raw input peer authentication failed")

        # assign client id
        cid = random.randint(100000, 999999)

        # initialize client state
        clients[cid] = {
            "sock": conn,
            "rx": bytearray(),
            "outbuf": bytearray(),
            "outoffset": 0,
            "pending_pointer": None,
            "pointer_next_at": 0.0,
            "subs": set(),
            "events": selectors.EVENT_READ,
            "identity": identity,
            "identity_check_at": 0.0,
        }

        # register client socket
        sel.register(conn, selectors.EVENT_READ, ("client", cid))

        # send welcome
        sendjson(cid, {"op": "WELCOME", "id": cid})

        log(f'client {cid} connected')

    except Exception as e:

        # error initializing client
        log(f'error initializing client {e}')
        removed = clients.pop(locals().get("cid"), None)
        closeprocessidentity(
            (removed or {}).get("identity", locals().get("identity")))

        try:
            sel.unregister(conn)
        except Exception:
            pass

        conn.close()


def dropclient(cid, reason):

    # Remove ownership first so a selector or close failure cannot leave an
    # over-limit client reachable from the event loop.
    c = clients.pop(cid, None)

    if not c:
        return

    try:
        sel.unregister(c["sock"])
    except Exception:
        pass

    try:
        c["sock"].close()
    except Exception:
        pass

    closeprocessidentity(c.get("identity"))

    log(f'client {cid} dropped ({reason})')


def appendclientoutput(cid, data):

    global CLIENTOUTBUFPEAK

    c = clients.get(cid)

    if not c:
        return False

    try:

        payload = bytes(data)

        if not payload:
            return True

        outbuf = c["outbuf"]
        outoffset = int(c.get("outoffset", 0))

        # Retain a send offset across partial writes.  Compact only
        # amortized-large consumed prefixes, rather than shifting the entire
        # queue after every short nonblocking send.
        if outoffset and (
            outoffset >= int(CLIENTFLUSHBYTES)
            or outoffset * 2 >= len(outbuf)
        ):
            del outbuf[:outoffset]
            c["outoffset"] = 0
            outoffset = 0

        queued = len(outbuf) - outoffset

        if queued + len(payload) > int(CLIENTOUTBUFLIMIT):
            dropclient(
                cid,
                (
                    "output queue exceeded "
                    f"{int(CLIENTOUTBUFLIMIT)} bytes"
                ),
            )
            return False

        outbuf.extend(payload)
        CLIENTOUTBUFPEAK = max(
            CLIENTOUTBUFPEAK,
            len(outbuf) - int(c.get("outoffset", 0)),
        )
        return True

    except Exception as e:

        log(f'error appending output for client {cid} {e}')
        dropclient(cid, f"output queue error {e}")
        return False


def materializeclientpointer(cid, force=False, now=None):

    c = clients.get(cid)

    if not c:
        return False

    pending = c.get("pending_pointer")

    if pending is None:
        return False

    if now is None:
        now = time.monotonic()

    # Keep one replaceable pointer state behind any blocked output.  A
    # loss-sensitive transition calls this with force=True so the newest
    # pointer is committed immediately before that transition.
    if not force:

        if c["outbuf"]:
            return False

        if float(now) < float(c.get("pointer_next_at", 0.0)):
            return False

    c["pending_pointer"] = None

    if not appendclientoutput(cid, pending):
        return False

    c = clients.get(cid)

    if not c:
        return False

    c["pointer_next_at"] = float(now) + float(CLIENTPOINTERINTERVAL)
    return True


def flushclientpointers(now=None):

    if now is None:
        now = time.monotonic()

    for cid in list(clients):

        if materializeclientpointer(cid, now=now):
            updateclientevents(cid)


def nextclientpointertimeout(maximum=0.01, now=None):

    try:
        timeout = max(0.0, float(maximum))
    except Exception:
        timeout = 0.01

    if now is None:
        now = time.monotonic()

    for c in list(clients.values()):

        if c.get("pending_pointer") is None:
            continue

        # A queued byte buffer already has write readiness registered.  Once
        # it drains, flushclient() materializes a due pending pointer.
        if c.get("outbuf"):
            continue

        remaining = float(c.get("pointer_next_at", 0.0)) - float(now)
        timeout = min(timeout, max(0.0, remaining))

    return timeout


def sendjson(cid, obj):

    global CLIENTPOINTERCOALESCED

    try:

        # fetch client
        c = clients.get(cid)

        if not c:
            return False

        # Encode once.  Compact wire records keep the local IPC queue shallow.
        line = (
            json.dumps(obj, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        pointer = (
            isinstance(obj, dict)
            and str(obj.get("op", "")) == "EVENT"
            and str(obj.get("kind", "")) == "pointer"
        )

        if pointer:

            if c.get("pending_pointer") is not None:
                CLIENTPOINTERCOALESCED += 1

            c["pending_pointer"] = line
            materializeclientpointer(cid)

        else:

            # Never allow a key, button, scroll, text, or protocol transition
            # to pass a pointer state that occurred before it.
            materializeclientpointer(cid, force=True)

            if cid not in clients:
                return False

            if not appendclientoutput(cid, line):
                return False

        if cid not in clients:
            return False

        updateclientevents(cid)
        return True

    except Exception as e:

        log(f'error queueing json for client {cid} {e}')
        dropclient(cid, f"output queue error {e}")
        return False


def recvlines(cid):

    try:

        # fetch client
        c = clients.get(cid)

        if not c:
            return []

        # receive data
        data = c["sock"].recv(4096)

        if not data:

            # client closed
            dropclient(cid, "eof")
            return []

        # Append bytes so fragmented UTF-8 and newlines stay intact.
        c["rx"].extend(data)

        if len(c["rx"]) > int(CLIENTINBUFLIMIT):
            dropclient(
                cid,
                (
                    "input queue exceeded "
                    f"{int(CLIENTINBUFLIMIT)} bytes"
                ),
            )
            return []

    except BlockingIOError:

        return []

    except Exception as e:

        # recv error
        dropclient(cid, f"recv error {e}")
        return []

    lines = []

    try:

        # split complete lines
        while True:

            idx = c["rx"].find(b"\n")

            if idx < 0:
                break

            raw = bytes(c["rx"][:idx])
            del c["rx"][:idx + 1]
            lines.append(raw.decode("utf-8", errors="replace").strip())

    except Exception as e:

        # error parsing lines
        log(f'error parsing lines for client {cid} {e}')

    return lines


def flushclient(cid):

    try:

        # fetch client
        c = clients.get(cid)

        if not c:
            return

        budget = int(CLIENTFLUSHBYTES)

        # Send at most one fair budget per client pass.  Bytearray prefix
        # deletion is linear in the bytes retained, never quadratic in the
        # number of queued JSON records.
        while budget > 0:

            c = clients.get(cid)

            if not c:
                return

            if not c["outbuf"]:

                materializeclientpointer(cid)

                c = clients.get(cid)

                if not c or not c["outbuf"]:
                    break

            outoffset = int(c.get("outoffset", 0))
            chunk = bytes(c["outbuf"][outoffset:outoffset + budget])

            try:

                sent = c["sock"].send(chunk)

            except BlockingIOError:

                return

            except Exception as e:

                dropclient(cid, f"send error {e}")
                return

            if sent <= 0:

                dropclient(cid, "send returned no progress")
                return

            c["outoffset"] = outoffset + sent

            if int(c["outoffset"]) >= len(c["outbuf"]):
                c["outbuf"].clear()
                c["outoffset"] = 0

            budget -= sent

    except Exception as e:

        # error flushing client
        log(f'error flushing client {cid} {e}')


def updateclientevents(cid):

    try:

        # fetch client
        c = clients.get(cid)

        if not c:
            return

        # A due pointer becomes ordinary output before selector interest is
        # calculated.  Pending-only state must not subscribe to EVENT_WRITE,
        # because local sockets are usually writable and would busy-loop.
        materializeclientpointer(cid)

        c = clients.get(cid)

        if not c:
            return

        events = selectors.EVENT_READ

        if c["outbuf"]:
            events |= selectors.EVENT_WRITE

        if int(c.get("events", 0)) == int(events):
            return

        sel.modify(c["sock"], events, ("client", cid))
        c["events"] = events

    except Exception as e:

        # error updating selector
        log(f'error updating selector for client {cid} {e}')


def handleline(cid, line):

    global SCREENW, SCREENH, POINTERX, POINTERY, LASTABSX, LASTABSY
    global POINTERSPEED, POINTERREMAINDERX, POINTERREMAINDERY

    client = clients.get(cid)
    if not rawinputclientalive(client):
        dropclient(cid, "authenticated WindowServer identity ended")
        return

    try:

        # parse json
        msg = json.loads(line)

    except Exception:

        # invalid json
        sendjson(cid, {"op": "ERROR", "reason": "invalid json"})

        return

    op = msg.get("op")

    # try:
    #
    #     # log ipc rx
    #     log(f'ipc rx <- client {cid} op={op} msg={msg}')
    #
    # except Exception:
    #
    #     pass

    if op == "HELLO":

        # respond to hello
        sendjson(cid, {"op": "WELCOME", "id": cid})

    elif op == "SUBSCRIBE":

        try:

            subs = msg.get("types", [])
            if not isinstance(subs, list):
                raise ValueError("types must be list")

            requested = {str(value) for value in subs}
            if not requested.issubset(RAWINPUTSUBSCRIPTIONS):
                raise ValueError("unsupported raw input subscription")

            clients[cid]["subs"] = requested

            # Pointer position is persistent service state, not merely the
            # last movement event.  A newly connected compositor must receive
            # the current coordinates immediately; otherwise it displays its
            # own stale/default position until the mouse moves and then jumps
            # to Input Server's position.
            if "pointer" in clients[cid]["subs"]:

                sendjson(cid, {
                    "op": "EVENT",
                    "kind": "pointer",
                    "x": int(POINTERX),
                    "y": int(POINTERY),
                    "dx": 0,
                    "dy": 0,
                    "abs": bool(_MOUSEABS),
                    "sync": True,
                    "source_monotonic_ns": time.monotonic_ns(),
                })

            sendjson(cid, {"op": "OK", "subs": list(clients[cid]["subs"])})

        except Exception as e:

            sendjson(cid, {"op": "ERROR", "reason": str(e)})

    elif op == "FB_SIZE":

        try:

            w = int(msg.get("w", SCREENW))

            h = int(msg.get("h", SCREENH))

        except Exception:

            sendjson(cid, {"op": "ERROR", "reason": "bad fbsize"})
            return

        if w < 1:
            w = 1

        if h < 1:
            h = 1

        SCREENW = w

        SCREENH = h

        if POINTERX < 0:
            POINTERX = 0

        if POINTERY < 0:
            POINTERY = 0

        if POINTERX >= SCREENW:
            POINTERX = SCREENW - 1

        if POINTERY >= SCREENH:
            POINTERY = SCREENH - 1

        LASTABSX = None

        LASTABSY = None

        schedulepointerpossave()

        sendjson(cid, {"op": "OK", "fbsize": [int(SCREENW), int(SCREENH)]})

    elif op == "POINTER_SPEED_SET":

        try:

            POINTERSPEED = normalizedpointerspeed(msg.get("speed", 1.0))

            POINTERREMAINDERX = 0.0

            POINTERREMAINDERY = 0.0

            sendjson(cid, {"op": "OK", "pointer_speed": POINTERSPEED})

        except Exception as e:

            sendjson(cid, {"op": "ERROR", "reason": str(e)})

    else:

        # unknown operation
        sendjson(cid, {"op": "ERROR", "reason": "unknown op"})


def broadcastevent(ev, kind=None):

    try:

        if "source_monotonic_ns" not in ev:
            ev["source_monotonic_ns"] = time.monotonic_ns()

        # iterate clients
        for cid, c in list(clients.items()):

            if not rawinputclientalive(c):
                dropclient(cid, "authenticated WindowServer identity ended")
                continue

            # filter by subscription
            if kind and kind not in c["subs"]:
                continue

            # queue event
            sendjson(cid, ev)


            # log tx per recipient
            logtx(cid, ev, kind)

    except Exception as e:

        # error broadcasting
        log(f'error broadcasting event {e}')


# device probe functions
def mapbutton(code):

    if code == BTN_TOUCH:

        if _MOUSEHASLEFT:
            return None

        return BTN_LEFT

    if code in (BTN_STYLUS, BTN_STYLUS2):
        return BTN_LEFT

    if code in (BTN_LEFT, BTN_RIGHT, BTN_MIDDLE, BTN_SIDE, BTN_EXTRA, BTN_FORWARD, BTN_BACK):
        return code

    return None


def ioc(dir, type, nr, size):

    try:

        # build ioctl command number
        return (
            (dir  << IOCDIRSHIFT)  |
            (ord(type) << IOCTYPESHIFT) |
            (nr   << IOCNRSHIFT)   |
            (size << IOCSIZESHIFT)
        )

    except Exception as e:

        # ioctl build error
        log(f'error building ioctl {e}')
        return 0


def ior(type, nr, size):

    try:

        # build read ioctl
        return ioc(IOCREAD, type, nr, size)

    except Exception as e:

        # ior error
        log(f'error building ior ioctl {e}')
        return 0


def eviocgbit(ev, size):

    try:

        # evdev get bitmask ioctl
        return ior('E', 0x20 + ev, size)

    except Exception as e:

        # eviocgbit error
        log(f'error building eviocgbit ioctl {e}')
        return 0


def eviocgabs(code):

    try:

        # EVIOCGABS(code) = _IOR('E', 0x40 + code, struct input_absinfo)
        return ior('E', 0x40 + code, 24)

    except Exception as e:

        log(f'error building eviocgabs ioctl {e}')
        return 0


def getabsinfo(fd, code):

    try:

        buf = bytearray(24)

    except Exception as e:

        log(f'error allocating absinfo buffer {e}')
        return None

    try:

        fcntl.ioctl(fd, eviocgabs(code), buf, True)

    except Exception:

        return None

    try:

        value, minv, maxv, fuzz, flat, res = struct.unpack("iiiiii", buf)

    except Exception:

        return None

    return {"value": value, "min": minv, "max": maxv}


def hasbit(buf, bit):

    try:

        # calculate byte and bit offset
        byte = bit // 8
        off = bit % 8

        if byte >= len(buf):
            return False

        return (buf[byte] & (1 << off)) != 0

    except Exception as e:

        # bit test error
        log(f'error testing bit {e}')
        return False


def getbits(fd, ev, size):

    try:

        # allocate buffer
        buf = bytearray(size)

    except Exception as e:

        # allocation error
        log(f'error allocating bit buffer {e}')
        return None

    try:

        # perform ioctl
        fcntl.ioctl(fd, eviocgbit(ev, size), buf, True)

    except PermissionError:

        # permission denied ioctl
        log(f'permission denied reading evdev bits')
        return None

    except Exception as e:

        # ioctl error
        log(f'error reading evdev bits {e}')
        return None

    return buf


def iskeyboard(fd):

    try:

        # get key capability bits
        bits = getbits(fd, EV_KEY, 96)

        if bits is None:
            return False

    except Exception as e:

        # capability read error
        log(f'error reading keyboard bits {e}')
        return False

    try:

        # check for common keyboard keys
        if not hasbit(bits, KEY_A):
            return False

        if not hasbit(bits, KEY_Z):
            return False

        if not hasbit(bits, KEY_ENTER):
            return False

        if not hasbit(bits, KEY_SPACE):
            return False

    except Exception as e:

        # bit test error
        log(f'error testing keyboard bits {e}')
        return False

    return True


MEDIAKEYCODES = {
    KEY_MUTE,
    KEY_VOLUMEDOWN,
    KEY_VOLUMEUP,
    KEY_PLAYPAUSE,
    KEY_PLAYCD,
    KEY_PAUSECD,
    KEY_PLAY,
}


def ismediadevice(fd):

    try:

        bits = getbits(fd, EV_KEY, 96)

        if bits is None:
            return False

        return any(hasbit(bits, code) for code in MEDIAKEYCODES)

    except Exception as e:

        log(f'error reading media-key capabilities {e}')
        return False


# device open functions
def eventnumber(name):

    try:

        if not isinstance(name, str) or not name.startswith("event"):
            return None

        suffix = name[5:]

        # Accept only the kernel eventN namespace.  isascii prevents Unicode
        # decimal lookalikes from being treated as driver node names.
        if not suffix or not suffix.isascii() or not suffix.isdigit():
            return None

        return int(suffix)

    except Exception:

        return None


def listeventnodes():

    nodes = os.listdir(NODEDIR)
    events = []

    for name in nodes:

        number = eventnumber(name)

        if number is None:
            continue

        events.append((number, name))

    events.sort(key=lambda item: item[0])
    return [name for _, name in events]


def openeventdevice(path):

    flags = os.O_RDONLY | os.O_NONBLOCK
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)

    try:

        if not stat.S_ISCHR(os.fstat(fd).st_mode):
            raise OSError(errno.ENODEV, "input event path is not a character device", path)

    except Exception:

        os.close(fd)
        raise

    return fd


def registerdevicefd(fd):

    if fd is None:
        return False

    fd = int(fd)

    if fd in _DEVICE_SELECTOR_FDS:
        return True

    try:

        sel.register(fd, selectors.EVENT_READ, ("device", fd))
        _DEVICE_SELECTOR_FDS.add(fd)
        return True

    except KeyError:

        # A descriptor number can be reused after a hotplug close.  Remove a
        # stale selector entry before registering the replacement device.
        try:
            sel.unregister(fd)
        except Exception:
            pass

        try:
            sel.register(fd, selectors.EVENT_READ, ("device", fd))
            _DEVICE_SELECTOR_FDS.add(fd)
            return True
        except Exception as e:
            log(f'error registering input device {fd} with selector {e}')
            return False

    except Exception as e:

        log(f'error registering input device {fd} with selector {e}')
        return False


def unregisterdevicefd(fd):

    if fd is None:
        return

    fd = int(fd)

    try:
        sel.unregister(fd)
    except Exception:
        pass

    _DEVICE_SELECTOR_FDS.discard(fd)


def closeeventdevice(fd):

    if fd is None:
        return

    unregisterdevicefd(fd)

    try:
        os.close(int(fd))
    except Exception:
        pass


def openkeyboard():

    global _KBD_FD
    global _KBDPATH
    global _no_device_logged
    global _KBD_OPENAT
    global _KBD_SEEN
    global _kbdreject

    if _KBD_FD is not None:
        return True

    try:

        # Enumerate every kernel eventN node.  Event numbers are assigned at
        # runtime and regularly exceed event9 on hardware with composite HID
        # devices, so a fixed candidate range is not valid.
        nodes = listeventnodes()

    except FileNotFoundError:

        # input node directory missing
        if not _no_device_logged:
            log(f'input node directory not found')
            _no_device_logged = True
        return False

    except PermissionError:

        # permission denied listing input nodes
        if not _no_device_logged:
            log(f'permission denied accessing input nodes')
            _no_device_logged = True
        return False

    except Exception as e:

        # other node directory error
        if not _no_device_logged:
            log(f'error listing input nodes {e}')
            _no_device_logged = True
        return False

    for name in nodes:

        path = f"{NODEDIR}/{name}"

        try:

            # open candidate device
            fd = openeventdevice(path)

        except PermissionError:

            # permission denied opening device
            if _kbdreject.get(path) != "open:permission":
                log(f'keyboard reject {path} open permission denied')
                _kbdreject[path] = "open:permission"
            continue

        except FileNotFoundError:

            # node vanished between list and open
            if _kbdreject.get(path) != "open:notfound":
                log(f'keyboard reject {path} open not found')
                _kbdreject[path] = "open:notfound"
            continue

        except Exception as e:

            # other open error
            if _kbdreject.get(path) != "open:error":
                log(f'keyboard reject {path} open error {e}')
                _kbdreject[path] = "open:error"
            continue

        try:

            # test if keyboard
            if not iskeyboard(fd):

                os.close(fd)
                if _kbdreject.get(path) != "capabilities":
                    log(f'keyboard reject {path} capability test failed')
                    _kbdreject[path] = "capabilities"
                continue

        except Exception as e:

            os.close(fd)
            if _kbdreject.get(path) != "cap:error":
                log(f'keyboard reject {path} capability test error {e}')
                _kbdreject[path] = "cap:error"
            continue

        _KBD_FD = fd
        _KBDPATH = path
        _no_device_logged = False

        _KBD_OPENAT = time.time()
        _KBD_SEEN = False

        registerdevicefd(_KBD_FD)
        log(f'keyboard opened at {_KBDPATH}')
        return True

    if not _no_device_logged:
        log(f'no keyboard device found')
        _no_device_logged = True

    return False


def openmediakeys(force=False):

    global _MEDIA_LASTSCAN

    now = time.monotonic()

    if not force and (now - float(_MEDIA_LASTSCAN)) < float(MEDIA_SCAN_INTERVAL):
        return bool(_MEDIA_FDS)

    _MEDIA_LASTSCAN = now

    try:

        paths = {f"{NODEDIR}/{name}" for name in listeventnodes()}

    except Exception as e:

        log(f'error listing media-key nodes {e}')
        return bool(_MEDIA_FDS)

    for fd, path in list(_MEDIA_FDS.items()):

        if path not in paths:
            closeeventdevice(fd)
            _MEDIA_FDS.pop(fd, None)

    for path in list(_MEDIA_REJECTED):

        if path not in paths:
            _MEDIA_REJECTED.pop(path, None)

    openedpaths = set(_MEDIA_FDS.values())

    for path in sorted(paths):

        if path in openedpaths or path == _KBDPATH:
            continue

        try:
            status = os.stat(path, follow_symlinks=False)
            signature = (
                int(status.st_dev),
                int(status.st_ino),
                int(status.st_rdev),
                int(getattr(status, "st_ctime_ns", int(status.st_ctime * 1e9))),
            )
        except OSError:
            signature = None

        # Most event nodes are audio jacks, LEDs, or full keyboards. Their
        # capability bitmaps do not change while the node identity is stable;
        # repeating several ioctls for every rejected node every three seconds
        # stalls real mouse/key reads on machines with many HID interfaces.
        if signature is not None and _MEDIA_REJECTED.get(path) == signature:
            continue

        fd = None

        try:

            fd = openeventdevice(path)

            # The primary keyboard is opened separately. Consumer-control
            # interfaces commonly expose only media keys and otherwise fail
            # the full-keyboard capability test.
            if iskeyboard(fd) or not ismediadevice(fd):
                os.close(fd)
                if signature is not None:
                    _MEDIA_REJECTED[path] = signature
                continue

            if not registerdevicefd(fd):
                os.close(fd)
                continue

            _MEDIA_FDS[fd] = path
            _MEDIA_REJECTED.pop(path, None)
            openedpaths.add(path)
            log(f'media keys opened at {path}')

        except Exception:

            try:
                os.close(fd)
            except Exception:
                pass

    return bool(_MEDIA_FDS)


def openmouse():

    global _MOUSE_FD, _MOUSEPATH, _mouse_open_logged, _MOUSEABS, _MOUSE_OPENAT, _MOUSE_SEEN, _MOUSEHASLEFT
    global _MOUSEBTN_FD, _MOUSEBTNPATH, _MOUSEBTN_OPENAT, _MOUSEBTN_SEEN, _MOUSEWHEEL_FD, _MOUSEWHEELPATH

    if _MOUSE_FD is not None and _MOUSEBTN_FD is not None:
        return True

    try:

        # Use the same strict dynamic event-node discovery as keyboards.
        nodes = listeventnodes()

    except FileNotFoundError:

        # input node directory missing
        if not _mouse_open_logged:

            log(f'input node directory not found')

            _mouse_open_logged = True

        return False

    except PermissionError:

        # permission denied listing input nodes
        if not _mouse_open_logged:

            log(f'permission denied accessing input nodes')

            _mouse_open_logged = True

        return False

    except Exception as e:

        # other directory error
        if not _mouse_open_logged:

            log(f'error listing input nodes {e}')

            _mouse_open_logged = True

        return False

    candidates = []

    for name in nodes:

        path = f"{NODEDIR}/{name}"

        try:

            # open candidate device
            fd = openeventdevice(path)

        except PermissionError:

            continue

        except FileNotFoundError:

            continue

        except Exception:

            continue

        try:

            # read capability bitsets
            rel = getbits(fd, EV_REL, 2)

            absb = getbits(fd, EV_ABS, 8)

            keyb = getbits(fd, EV_KEY, 64)

        except Exception:

            try:

                os.close(fd)

            except Exception:

                pass

            continue

        try:

            os.close(fd)

        except Exception:

            pass

        isrel = False

        isabs = False

        hasbtn = False

        btncount = 0

        if rel is not None:

            if hasbit(rel, REL_X) or hasbit(rel, REL_Y):
                isrel = True

            elif hasbit(rel, REL_WHEEL) or hasbit(rel, REL_HWHEEL):
                isrel = True

            elif hasbit(rel, REL_WHEELHI) or hasbit(rel, REL_HWHEELHI):
                isrel = True

        if absb is not None:

            if hasbit(absb, ABS_X) and hasbit(absb, ABS_Y):
                isabs = True

            elif hasbit(absb, ABS_MT_POSITION_X) and hasbit(absb, ABS_MT_POSITION_Y):
                isabs = True

        hasleft = False

        if keyb is not None:

            if hasbit(keyb, BTN_LEFT) or hasbit(keyb, BTN_TOUCH):
                hasbtn = True

            if hasbit(keyb, BTN_LEFT):
                hasleft = True

            for b in (BTN_LEFT, BTN_RIGHT, BTN_MIDDLE, BTN_SIDE, BTN_EXTRA, BTN_FORWARD, BTN_BACK, BTN_TOUCH):

                if hasbit(keyb, b):
                    btncount += 1

        haswheel = False

        if rel is not None:

            if hasbit(rel, REL_WHEEL) or hasbit(rel, REL_HWHEEL):
                haswheel = True

            if hasbit(rel, REL_WHEELHI) or hasbit(rel, REL_HWHEELHI):
                haswheel = True

        candidates.append({
            "path": path,
            "isrel": isrel,
            "isabs": isabs,
            "absb": absb,
            "hasbtn": hasbtn,
            "hasleft": hasleft,
            "btncount": btncount,
            "haswheel": haswheel,
        })

    bestmovepath = None

    bestmovescore = -1

    bestmovehasleft = False

    bestisabs = False

    bestabsb = None

    bestbtnpath = None

    bestbtnscore = -1

    bestbtnhasleft = False

    bestwheelpath = None

    bestwheelscore = -1

    for c in candidates:

        isrel = bool(c.get("isrel"))

        isabs = bool(c.get("isabs"))

        hasbtn = bool(c.get("hasbtn"))

        btncount = int(c.get("btncount", 0))

        haswheel = bool(c.get("haswheel"))

        movescore = -1

        if isabs:
            movescore = 4

        elif isrel:
            movescore = 2

        if movescore >= 0:

            if hasbtn:
                movescore += 1

            if bestmovepath is None or movescore > bestmovescore:

                bestmovepath = c["path"]

                bestmovescore = movescore

                bestmovehasleft = bool(c.get("hasleft"))

                bestisabs = isabs

                bestabsb = c.get("absb")

        btnscore = -1

        if hasbtn:

            btnscore = btncount

            if isabs or isrel:
                btnscore += 1

            if bestbtnpath is None or btnscore > bestbtnscore:

                bestbtnpath = c["path"]

                bestbtnscore = btnscore

                bestbtnhasleft = bool(c.get("hasleft"))

        wheelscore = -1

        if haswheel:

            wheelscore = 1

            if isrel:
                wheelscore += 1

            if hasbtn:
                wheelscore += 1

            if bestwheelpath is None or wheelscore > bestwheelscore:

                bestwheelpath = c["path"]

                bestwheelscore = wheelscore

    if bestmovepath is None and bestbtnpath is None:

        if not _mouse_open_logged:

            log(f'no mouse device found')

            _mouse_open_logged = True

        return False

    if _MOUSE_FD is None and bestmovepath is not None:

        try:

            # open selected movement device
            bestfd = openeventdevice(bestmovepath)

        except Exception as e:

            log(f'error opening mouse movement device {e}')
            bestfd = None

        if bestfd is not None:

            _MOUSE_FD = bestfd

            _MOUSEPATH = bestmovepath

            _MOUSE_OPENAT = time.time()

            _MOUSE_SEEN = False

            _MOUSEABS = None

            if bestisabs:

                absb = bestabsb

                if absb is not None:

                    if hasbit(absb, ABS_X) and hasbit(absb, ABS_Y):

                        xi = getabsinfo(bestfd, ABS_X)

                        yi = getabsinfo(bestfd, ABS_Y)

                    else:

                        xi = getabsinfo(bestfd, ABS_MT_POSITION_X)

                        yi = getabsinfo(bestfd, ABS_MT_POSITION_Y)

                    if xi and yi:

                        _MOUSEABS = {
                            "xmin": xi["min"],
                            "xmax": xi["max"],
                            "ymin": yi["min"],
                            "ymax": yi["max"],
                        }
                    else:
                        _MOUSEABS = {
                            "xmin": 0,
                            "xmax": 65535,
                            "ymin": 0,
                            "ymax": 65535,
                        }

    if _MOUSEWHEEL_FD is None and bestwheelpath is not None:

        if bestwheelpath == _MOUSEPATH and _MOUSE_FD is not None:

            _MOUSEWHEEL_FD = _MOUSE_FD

            _MOUSEWHEELPATH = _MOUSEPATH

        elif bestwheelpath == _MOUSEBTNPATH and _MOUSEBTN_FD is not None:

            _MOUSEWHEEL_FD = _MOUSEBTN_FD

            _MOUSEWHEELPATH = _MOUSEBTNPATH

        else:

            try:

                wfd = openeventdevice(bestwheelpath)

            except Exception as e:

                log(f'error opening mouse wheel device {e}')
                wfd = None

            if wfd is not None:

                _MOUSEWHEEL_FD = wfd

                _MOUSEWHEELPATH = bestwheelpath

    if _MOUSEBTN_FD is None and bestbtnpath is not None:

        if bestbtnpath == _MOUSEPATH and _MOUSE_FD is not None:

            _MOUSEBTN_FD = _MOUSE_FD

            _MOUSEBTNPATH = _MOUSEPATH

            _MOUSEBTN_OPENAT = _MOUSE_OPENAT

            _MOUSEBTN_SEEN = False

        else:

            try:

                # open selected button device
                bfd = openeventdevice(bestbtnpath)

            except Exception as e:

                log(f'error opening mouse button device {e}')
                bfd = None

            if bfd is not None:
                _MOUSEBTN_FD = bfd

                _MOUSEBTNPATH = bestbtnpath

                _MOUSEBTN_OPENAT = time.time()

                _MOUSEBTN_SEEN = False

    _MOUSEHASLEFT = bestmovehasleft or bestbtnhasleft

    for fd in {_MOUSE_FD, _MOUSEBTN_FD, _MOUSEWHEEL_FD}:

        if fd is not None:
            registerdevicefd(fd)


# read functions
def readraw(timeout_ms=0):

    if _KBD_FD is None:
        return []

    try:

        # poll keyboard fd
        r, _, _ = select.select([_KBD_FD], [], [], timeout_ms / 1000.0)

        if not r:
            return []

    except Exception:

        return []

    events = []

    # Drain every event that was ready when the device woke the selector.
    # Reading only one fixed batch allows a high-report-rate HID device to
    # build a persistent queue and turns that queue into visible input lag.
    while True:

        try:
            data = os.read(_KBD_FD, EV_READ_BYTES)
        except BlockingIOError:
            break
        except Exception as e:
            log(f'error reading keyboard {e}')
            break

        if not data:
            break

        try:

            for i in range(0, len(data), EV_SIZE):

                chunk = data[i:i + EV_SIZE]

                if len(chunk) < EV_SIZE:
                    break

                sec, usec, etype, code, value = struct.unpack(EV_FORMAT, chunk)
                events.append((etype, code, value))

        except Exception as e:

            log(f'error unpacking keyboard events {e}')
            break

        if len(data) < EV_READ_BYTES:
            break

    return events


def readmediakeys():

    batches = []

    for fd, path in list(_MEDIA_FDS.items()):

        events = []
        failed = False

        while True:

            try:
                data = os.read(fd, EV_READ_BYTES)
            except BlockingIOError:
                break
            except Exception as e:
                log(f'error reading media keys {path} {e}')
                failed = True
                break

            if not data:
                failed = True
                break

            try:

                for i in range(0, len(data), EV_SIZE):

                    chunk = data[i:i + EV_SIZE]

                    if len(chunk) < EV_SIZE:
                        break

                    sec, usec, etype, code, value = struct.unpack(EV_FORMAT, chunk)

                    if etype == EV_KEY and code in MEDIAKEYCODES:
                        events.append((etype, code, value))

            except Exception as e:

                log(f'error unpacking media-key events {path} {e}')
                failed = True
                break

            if len(data) < EV_READ_BYTES:
                break

        if events:
            batches.append((path, events))

        if failed:
            closeeventdevice(fd)
            _MEDIA_FDS.pop(fd, None)

    return batches


# NEW
def readmouse(timeout_ms=0):

    global _MOUSE_FD, _MOUSEBTN_FD, _MOUSEWHEEL_FD

    fds = []

    if _MOUSE_FD is not None:
        fds.append(_MOUSE_FD)

    if _MOUSEBTN_FD is not None and _MOUSEBTN_FD != _MOUSE_FD:
        fds.append(_MOUSEBTN_FD)

    if _MOUSEWHEEL_FD is not None and _MOUSEWHEEL_FD not in fds:
        fds.append(_MOUSEWHEEL_FD)

    if not fds:
        return []

    try:

        # poll mouse fds
        r, _, _ = select.select(fds, [], [], timeout_ms / 1000.0 if timeout_ms else 0)

        if not r:
            return []

    except Exception:

        return []

    events = []

    for fd in r:

        try:

            # Drain all pending events and join once.  Repeated bytes
            # concatenation copied the entire accumulated HID burst for every
            # read and amplified lag after a scheduling stall.
            chunks = []

            while True:

                chunk = os.read(fd, EV_READ_BYTES)

                if not chunk:
                    break

                chunks.append(chunk)

                if len(chunk) < EV_READ_BYTES:
                    break

        except BlockingIOError:

            pass

        data = b"".join(chunks)

        try:

            # unpack
            for i in range(0, len(data), EV_SIZE):

                chunk = data[i:i + EV_SIZE]

                if len(chunk) < EV_SIZE:
                    break

                sec, usec, etype, code, value = struct.unpack(EV_FORMAT, chunk)

                events.append((fd, etype, code, value))

        except Exception as e:

            log(f'error unpacking mouse events {e}')
            continue

    return events


def pumpdevices():

    global _KBD_FD, _KBDPATH, _KBD_LASTPROBE
    global _MOUSE_FD, _MOUSEPATH, _MOUSE_LASTPROBE
    global _MOUSEBTN_LASTPROBE, _MOUSEBTN_FD, _MOUSEBTNPATH, _MOUSEBTN_OPENAT, _MOUSEBTN_SEEN
    global _MOUSEWHEEL_FD, _MOUSEWHEELPATH

    # ensure devices are open
    if _KBD_FD is None:
        openkeyboard()

    openmediakeys()

    if _MOUSE_FD is None:
        openmouse()

    # keyboard silent reprobe (only if we have never seen EV_KEY from the chosen node)
    if _KBD_FD is not None and not _KBD_SEEN:

        now = time.time()

        if _KBD_OPENAT and (now - _KBD_OPENAT) >= KBD_SILENCE_SECONDS:

            if (now - _KBD_LASTPROBE) >= KBD_PROBE_COOLDOWN:

                _KBD_LASTPROBE = now

                closeeventdevice(_KBD_FD)

                _KBD_FD = None
                _KBDPATH = None

                log(f'keyboard probe: no EV_KEY seen, rescan')

                try:

                    openkeyboard()

                except Exception:

                    pass

    # mouse silent reprobe (only if we have never seen any meaningful mouse event from the chosen node)
    if _MOUSE_FD is not None and not _MOUSE_SEEN:

        now = time.time()

        if _MOUSE_OPENAT and (now - _MOUSE_OPENAT) >= MOUSE_SILENCE_SECONDS:

            if (now - _MOUSE_LASTPROBE) >= MOUSE_PROBE_COOLDOWN:

                _MOUSE_LASTPROBE = now

                oldfd = _MOUSE_FD
                closeeventdevice(oldfd)


                if _MOUSEBTN_FD == oldfd:

                    _MOUSEBTN_FD = None

                    _MOUSEBTNPATH = None

                    _MOUSEBTN_OPENAT = 0.0

                    _MOUSEBTN_SEEN = False

                if _MOUSEWHEEL_FD == oldfd:

                    _MOUSEWHEEL_FD = None

                    _MOUSEWHEELPATH = None

                _MOUSE_FD = None

                _MOUSEPATH = None

                log(f'mouse probe: no events seen, rescan')

                try:

                    openmouse()

                except Exception:

                    pass

    # mouse buttons silent reprobe (movement may be fine but buttons can live on a different node on some hypervisors)
    if _MOUSEBTN_FD is not None and _MOUSEBTN_FD != _MOUSE_FD and not _MOUSEBTN_SEEN:

        now = time.time()

        if _MOUSEBTN_OPENAT and (now - _MOUSEBTN_OPENAT) >= MOUSE_SILENCE_SECONDS:

            if (now - _MOUSEBTN_LASTPROBE) >= MOUSE_PROBE_COOLDOWN:

                _MOUSEBTN_LASTPROBE = now

                oldfd = _MOUSEBTN_FD
                closeeventdevice(oldfd)

                _MOUSEBTN_FD = None

                _MOUSEBTNPATH = None

                if _MOUSEWHEEL_FD == oldfd:

                    _MOUSEWHEEL_FD = None

                    _MOUSEWHEELPATH = None

                log(f'mouse buttons probe: no button events seen, rescan')

                try:

                    openmouse()

                except Exception:

                    pass

    try:

        # read keyboard events
        kevs = readraw(0)

    except Exception:
        kevs = []

    try:

        mediabatches = readmediakeys()

    except Exception:
        mediabatches = []

    try:

        # read mouse events
        mevs = readmouse(0)

    except Exception:
        mevs = []

    try:

        # emit keyboard events
        if kevs:
            emitkeys(kevs)

    except Exception as e:

        log(f'error emitting keyboard events {e}')

    try:

        for mediapath, mediaevents in mediabatches:
            emitkeys(mediaevents, devpath=mediapath)

    except Exception as e:

        log(f'error emitting media-key events {e}')

    try:

        # emit mouse events
        if mevs:
            emitmouse(mevs)

    except Exception as e:

        log(f'error emitting mouse events {e}')


# keyboard normalise functions
def normkey(ref):

    try:

        if not ref:
            return None

        r = ref.upper().strip()

        return ALIASES.get(r)

    except Exception as e:

        # normalize key error
        log(f'error normalizing key {e}')
        return None


def modstate():

    try:

        return {
            "shift": _mods["lshift"] or _mods["rshift"],
            "ctrl": _mods["lctrl"] or _mods["rctrl"],
            "alt": _mods["lalt"] or _mods["ralt"],
            "win": _mods["lwin"] or _mods["rwin"],
            "caps": _mods["caps"],
            "num": _mods["num"],
            "scroll": _mods["scroll"],
        }

    except Exception as e:

        # modstate error
        log(f'error computing modstate {e}')
        return {}


def updatemods(code, value):

    try:

        pressed = value != 0

        if code == KEY_LEFTSHIFT:
            _mods["lshift"] = pressed

        elif code == KEY_RIGHTSHIFT:
            _mods["rshift"] = pressed

        elif code == KEY_LEFTCTRL:
            _mods["lctrl"] = pressed

        elif code == KEY_RIGHTCTRL:
            _mods["rctrl"] = pressed

        elif code == KEY_LEFTALT:
            _mods["lalt"] = pressed

        elif code == KEY_RIGHTALT:
            _mods["ralt"] = pressed

        elif code == KEY_LEFTMETA:
            _mods["lwin"] = pressed

        elif code == KEY_RIGHTMETA:
            _mods["rwin"] = pressed

        elif code == KEY_CAPSLOCK and value == 1:
            _mods["caps"] = not _mods["caps"]

        elif code == KEY_NUMLOCK and value == 1:
            _mods["num"] = not _mods["num"]

        elif code == KEY_SCROLLLOCK and value == 1:
            _mods["scroll"] = not _mods["scroll"]

    except Exception as e:

        # update mods error
        log(f'error updating modifiers {e}')


def keyname(code):

    try:

        if code in KEYCODES:
            return KEYCODES[code]

        if code in KEYLETTERS:
            return KEYLETTERS[code]

        if code in KEYPRINTABLE:
            return KEYPRINTABLE[code]

        return f"KEY_{code}"

    except Exception as e:

        # keyname error
        log(f'error resolving key name {e}')
        return "UNKNOWN"


def keychar(name, mods):

    try:

        if not name:
            return None

        # letters
        if len(name) == 1 and name.isalpha():

            ch = name.lower()

            if mods.get("caps"):
                ch = ch.upper()

            if mods.get("shift"):
                ch = ch.upper()

            return ch

        # printable symbols
        if name in KEYPRINTABLE.values():

            ch = name

            if mods.get("shift"):
                ch = SHIFTED.get(ch, ch)

            return ch

        # space
        if name == "SPACE":
            return " "

    except Exception as e:

        # keychar error
        log(f'error computing keychar {e}')

    return None


def keyevent(code, value):

    try:

        # update modifier state
        updatemods(code, value)

        # resolve key name
        name = keyname(code)

        # determine state
        if value == 0:
            state = "up"
        elif value == 1:
            state = "down"
        else:
            state = "repeat"

        return {
            "op": "EVENT",
            "kind": "key",
            "code": code,
            "key": name,
            "state": state,
            "mods": modstate(),
        }

    except Exception as e:

        # keyevent error
        log(f'error creating key event {e}')
        return None


def emitkeys(events, devpath=None):

    global _KBD_SEEN

    try:

        for etype, code, value in events:

            if etype != EV_KEY:
                continue

            if devpath is None or devpath == _KBDPATH:
                _KBD_SEEN = True

            ev = keyevent(code, value)

            if not ev:
                continue


            # log device rx
            logrx("keyboard", devpath or _KBDPATH, ev)

            broadcastevent(ev, "key")

            # emit text on key down only
            if ev["state"] != "down":
                continue


            # do not generate TEXT while ctrl/alt is held
            # (shortcuts are handled via the KEY event in brick)
            if ev.get("mods", {}).get("ctrl") or ev.get("mods", {}).get("alt"):
                continue

            ch = keychar(ev["key"], ev["mods"])

            if ch:

                tev = {
                    "op": "EVENT",
                    "kind": "text",
                    "text": ch,
                    "mods": ev["mods"],
                }

                # log device rx (derived)
                logrx("keyboard", devpath or _KBDPATH, tev)

                broadcastevent(tev, "text")

    except Exception as e:

        # emitkeys error
        log(f'error emitting keys {e}')


# mouse normalize functions
def clamppointer():

    try:

        global POINTERX, POINTERY, SCREENW, SCREENH

        if POINTERX < 0:
            POINTERX = 0

        if POINTERY < 0:
            POINTERY = 0

        if SCREENW and POINTERX > (SCREENW - 1):
            POINTERX = SCREENW - 1

        if SCREENH and POINTERY > (SCREENH - 1):
            POINTERY = SCREENH - 1

    except Exception as e:

        log(f'error clamping pointer {e}')


# NEW
def emitmouse(events):

    global POINTERX, POINTERY, SCROLLX, SCROLLY, _MOUSE_SEEN, _MOUSEBTN_SEEN, _MOUSEABS
    global POINTERREMAINDERX, POINTERREMAINDERY

    try:

        dx = 0

        dy = 0

        absx = None

        absy = None

        buttons = []

        scrollx = 0

        scrolly = 0

        movefd = _MOUSE_FD

        btnfd = _MOUSEBTN_FD if _MOUSEBTN_FD is not None else _MOUSE_FD

        wheelfd = _MOUSEWHEEL_FD if _MOUSEWHEEL_FD is not None else _MOUSE_FD

        # aggregate events until SYN_REPORT
        for fd, etype, code, value in events:

            if etype == EV_REL:

                if code in (REL_X, REL_Y):

                    if fd != movefd:
                        continue

                elif code in (REL_WHEEL, REL_HWHEEL, REL_WHEELHI, REL_HWHEELHI):

                    if fd != wheelfd:
                        continue

                if code == REL_X:
                    dx += value

                elif code == REL_Y:
                    dy += value

                elif code == REL_HWHEEL:
                    scrollx += value

                elif code == REL_WHEEL:
                    scrolly += value

                elif code == REL_HWHEELHI:

                    global SCROLLHIX

                    SCROLLHIX += value

                    if SCROLLHIX >= 120:

                        step = int(SCROLLHIX / 120)

                        scrollx += step

                        SCROLLHIX -= step * 120

                    elif SCROLLHIX <= -120:

                        step = int(SCROLLHIX / 120)

                        scrollx += step

                        SCROLLHIX -= step * 120

                elif code == REL_WHEELHI:

                    global SCROLLHIY

                    SCROLLHIY += value

                    if SCROLLHIY >= 120:

                        step = int(SCROLLHIY / 120)

                        scrolly += step

                        SCROLLHIY -= step * 120

                    elif SCROLLHIY <= -120:

                        step = int(SCROLLHIY / 120)

                        scrolly += step

                        SCROLLHIY -= step * 120

            elif etype == EV_ABS:


                if fd != movefd:
                    continue

                if code == ABS_X:
                    absx = value

                elif code == ABS_Y:
                    absy = value

                elif code == ABS_MT_POSITION_X:
                    absx = value

                elif code == ABS_MT_POSITION_Y:
                    absy = value

            elif etype == EV_KEY:


                if fd != btnfd:
                    continue

                bcode = mapbutton(code)

                if bcode is not None:

                    if value == 1:

                        buttons.append((bcode, "down"))

                    elif value == 0:

                        buttons.append((bcode, "up"))

        moved = False

        absflag = False

        if absx is not None or absy is not None:

            absflag = True

            global LASTABSX, LASTABSY

            if absx is not None:

                LASTABSX = absx

            if absy is not None:

                LASTABSY = absy

            absx = LASTABSX

            absy = LASTABSY

            # map absolute range to screen space using probed device min/max
            xmin = 0

            xmax = 65535

            ymin = 0

            ymax = 65535

            if isinstance(_MOUSEABS, dict):

                if "xmin" in _MOUSEABS:
                    xmin = int(_MOUSEABS["xmin"])

                if "xmax" in _MOUSEABS:
                    xmax = int(_MOUSEABS["xmax"])

                if "ymin" in _MOUSEABS:
                    ymin = int(_MOUSEABS["ymin"])

                if "ymax" in _MOUSEABS:
                    ymax = int(_MOUSEABS["ymax"])

            xden = (xmax - xmin)

            yden = (ymax - ymin)

            if xden <= 0:
                xden = 1

            if yden <= 0:
                yden = 1

            xr = (absx - xmin) / float(xden)

            yr = (absy - ymin) / float(yden)

            if xr < 0.0:
                xr = 0.0

            if xr > 1.0:
                xr = 1.0

            if yr < 0.0:
                yr = 0.0

            if yr > 1.0:
                yr = 1.0

            POINTERX = int(xr * (SCREENW - 1))

            POINTERY = int(yr * (SCREENH - 1))

            dx = 0

            dy = 0

            moved = True

        else:

            if dx != 0 or dy != 0:

                dx, POINTERREMAINDERX = scalepointerdelta(
                    dx, POINTERSPEED, POINTERREMAINDERX)

                dy, POINTERREMAINDERY = scalepointerdelta(
                    dy, POINTERSPEED, POINTERREMAINDERY)

            if dx != 0 or dy != 0:

                POINTERX += dx

                POINTERY += dy

                moved = True

        if moved:

            _MOUSE_SEEN = True

            clamppointer()

            pev = {
                "op": "EVENT",
                "kind": "pointer",
                "x": POINTERX,
                "y": POINTERY,
                "dx": dx,
                "dy": dy,
                "abs": absflag,
                "mods": modstate(),
                "source_monotonic_ns": time.monotonic_ns(),
            }

            logrx("mouse", _MOUSEPATH, pev)

            broadcastevent(pev, "pointer")
            schedulepointerpossave()

        # emit button events (even if pointer did not move in this batch)
        for bcode, state in buttons:

            _MOUSE_SEEN = True

            _MOUSEBTN_SEEN = True

            bev = {
                "op": "EVENT",
                "kind": "button",
                "button": bcode,
                "state": state,
                "x": POINTERX,
                "y": POINTERY,
                "mods": modstate(),
            }

            logrx("mouse", _MOUSEBTNPATH, bev)

            broadcastevent(bev, "button")

        if scrollx or scrolly:

            SCROLLX += scrollx

            SCROLLY += scrolly

            sev = {
                "op": "EVENT",
                "kind": "scroll",
                "x": POINTERX,
                "y": POINTERY,
                "dx": scrollx,
                "dy": scrolly,
                "mods": modstate(),
            }

            logrx("mouse", _MOUSEWHEELPATH, sev)

            broadcastevent(sev, "scroll")

        if absflag:

            _MOUSEABS = True

        else:

            _MOUSEABS = False

            dx = 0

            dy = 0

            buttons.clear()

            scrollx = 0

            scrolly = 0

    except Exception as e:

        # emitmouse error
        log(f'error emitting mouse events {e}')


def loadpointerpos():

    global POINTERX
    global POINTERY

    try:

        p = os.path.join(EPHBASE, "pointer.pos")

        if not os.path.exists(p):
            return

        txt = open(p, "r").read().strip()

        parts = txt.split(",")

        if len(parts) != 2:
            return

        POINTERX = int(parts[0])
        POINTERY = int(parts[1])

        clamppointer()

    except FileNotFoundError:

        return

    except PermissionError:

        return

    except Exception:

        return


def savepointerpos(force=False):

    global POINTERSAVELAST, POINTERSAVEDIRTY

    if not POINTERSAVEDIRTY and not force:
        return False

    now = time.monotonic()

    if (
        not force
        and now - float(POINTERSAVELAST) < float(POINTERSAVEINTERVAL)
    ):
        return False

    try:

        p = os.path.join(EPHBASE, "pointer.pos")

        with open(p, "w") as f:

            f.write(f"{POINTERX},{POINTERY}")

        POINTERSAVELAST = now
        POINTERSAVEDIRTY = False
        return True

    except PermissionError:

        return False

    except Exception:

        return False


def schedulepointerpossave():

    global POINTERSAVEDIRTY

    POINTERSAVEDIRTY = True


# policy functions
def applysubscriptions(cid, msg):

    try:

        # fetch client
        c = clients.get(cid)

        if not c:
            return

        # extract subscription list
        types = msg.get("types", [])

        if not isinstance(types, list):
            raise ValueError("types must be list")

        requested = {str(value) for value in types}

        if not requested.issubset(RAWINPUTSUBSCRIPTIONS):
            raise ValueError("unsupported raw input subscription")

        # apply subscriptions
        c["subs"] = requested

        # acknowledge
        sendjson(cid, {
            "op": "OK",
            "subs": list(c["subs"]),
        })

    except Exception as e:

        # subscription error
        sendjson(cid, {
            "op": "ERROR",
            "reason": str(e),
        })


def handlereconnects():

    try:

        # keyboard reconnect
        if _KBD_FD is None:

            openkeyboard()
        if _MOUSE_FD is None:

            openmouse()
    except Exception as e:

        # reconnect handler error
        log(f'error handling device reconnects {e}')


# signal functions
def handlesignal(signum, frame):

    global SERVERRUN

    try:

        # log signal
        log(f'signal received {signum}')

        # request shutdown
        SERVERRUN = False

    except Exception as e:

        # signal handling error
        log(f'error handling signal {e}')


# main
def main():


    # install signal handlers
    signal.signal(signal.SIGINT, handlesignal)
    signal.signal(signal.SIGTERM, handlesignal)


    # Capture the launcher's immutable process generation before accepting the
    # only permitted sibling peer. A missing process identity is fail-closed.
    if not initializeipcidentity():
        print(formatlog('input server', 'could not establish launcher identity'))
        return

    # create required paths
    if not makepaths():
        return

    # open logging
    openlog()


    # load last pointer position
    loadpointerpos()

    # Keep 1.0 as the historical unmodified movement and restore any user
    # selection made in Settings before input devices begin producing events.
    loadpointerspeed()

    try:

        # start input server socket
        srv = startserver()

        if srv is None:
            log(f'failed to start input server')
            return

    except Exception as e:

        log(f'fatal error starting server {e}')
        return


    # initial device open attempts
    openkeyboard()
    openmouse()

    while SERVERRUN:

        # Publish pointer state whose 240 Hz deadline elapsed without
        # registering pending-only sockets as permanently writable.
        flushclientpointers()

        try:

            # Physical input descriptors participate in the same selector as
            # IPC.  Hardware input therefore wakes Input Server immediately
            # instead of waiting behind the old 10 ms polling interval.
            events = sel.select(timeout=nextclientpointertimeout(0.01))

        except Exception:

            events = []

        # handle ipc events
        for key, mask in events:

            kind, ident = key.data

            if kind == "accept":

                acceptclient(key.fileobj)
            elif kind == "client":

                cid = ident

                try:

                    if mask & selectors.EVENT_READ:

                        lines = recvlines(cid)

                        for line in lines:
                            handleline(cid, line)

                    if mask & selectors.EVENT_WRITE:

                        flushclient(cid)

                    updateclientevents(cid)

                except Exception as e:

                    dropclient(cid, f"client error {e}")

            elif kind == "device":

                # The shared device pump below drains every ready input fd.
                pass


        # pump input devices and emit events
        pumpdevices()

        # Physical events are queued after the selector result that woke this
        # iteration. Flush them immediately rather than waiting for a second
        # selector pass to report that the local socket is writable.
        flushclientpointers()

        for cid in list(clients):

            if clients.get(cid, {}).get("outbuf"):
                flushclient(cid)
                updateclientevents(cid)

        savepointerpos()

        # attempt device reconnects if needed
        handlereconnects()


    # shutdown sequence
    log(f'input server shutting down')
    savepointerpos(force=True)


    # close all client sockets
    for cid in list(clients.keys()):
        dropclient(cid, "shutdown")

    # close physical input descriptors once, including shared mouse nodes
    for fd in set(_DEVICE_SELECTOR_FDS):
        closeeventdevice(fd)


    # close server socket
    sel.close()
    try:
        srv.close()
    except Exception:
        pass

    try:
        if stalecustomsocket(SOCKPATH):
            os.unlink(SOCKPATH)
    except OSError as error:
        log(f'input server socket cleanup error {error}')

if __name__ == "__main__":

    main()
