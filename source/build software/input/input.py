

"""
input.py

input captures input events for The One OS.
"""




# imports
import os
import sys

sys.path.insert(0, '/the one/build')

import time
import fcntl
import errno
import struct
import select
from reign.reign import timestamp




# globals
LOGFILE = '/the one/logs/input.py.log'
NODEDIR = '/the one/drivers/nodes/input'
_DEBUG_INPUT = False
EVENT_CANDIDATES = [f'event{i}' for i in range(10)]
EV_SIZE = 24
EV_FORMAT = 'qqHHi'
EV_SYN = 0x00
EV_KEY = 0x01
EV_MSC = 0x04
EV_REL = 0x02
EV_ABS = 0x03
REL_X = 0x00
REL_Y = 0x01
REL_HWHEEL = 0x06
REL_WHEEL = 0x08
BTN_LEFT = 0x110
BTN_RIGHT = 0x111
BTN_MIDDLE = 0x112
SYN_REPORT = 0

_fd = None
_MFD = None
_KBDPATH = None

_no_device_logged = False
_mouse_open_logged = False

_mods = {
    'lshift': False,
    'rshift': False,
    'lctrl': False,
    'rctrl': False,
    'lalt': False,
    'ralt': False,
    'lwin': False,
    'rwin': False,
    'caps': False,
    'num': False,
    'scroll': False,
}

_repeatfilter = {}

# key globals (evdev key codes)
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
    KEY_ESC: 'ESC',
    KEY_TAB: 'TAB',
    KEY_CAPSLOCK: 'CAPSLOCK',
    KEY_LEFTSHIFT: 'LSHIFT',
    KEY_RIGHTSHIFT: 'RSHIFT',
    KEY_LEFTCTRL: 'LCTRL',
    KEY_RIGHTCTRL: 'RCTRL',
    KEY_LEFTALT: 'LALT',
    KEY_RIGHTALT: 'RALT',
    KEY_LEFTMETA: 'LWIN',
    KEY_RIGHTMETA: 'RWIN',
    KEY_MENU: 'APPS',
    KEY_ENTER: 'ENTER',
    KEY_BACKSPACE: 'BACKSPACE',
    KEY_SPACE: 'SPACE',

    KEY_HOME: 'HOME',
    KEY_END: 'END',
    KEY_PAGEUP: 'PGUP',
    KEY_PAGEDOWN: 'PGDN',
    KEY_INSERT: 'INS',
    KEY_DELETE: 'DELETE',
    KEY_UP: 'UP',
    KEY_DOWN: 'DOWN',
    KEY_LEFT: 'LEFT',
    KEY_RIGHT: 'RIGHT',

    KEY_SYSRQ: 'PRTSCR',
    KEY_PAUSE: 'PAUSE',
    KEY_SCROLLLOCK: 'SCROLLLOCK',
    KEY_NUMLOCK: 'NUMLOCK',

    KEY_F1: 'F1',
    KEY_F2: 'F2',
    KEY_F3: 'F3',
    KEY_F4: 'F4',
    KEY_F5: 'F5',
    KEY_F6: 'F6',
    KEY_F7: 'F7',
    KEY_F8: 'F8',
    KEY_F9: 'F9',
    KEY_F10: 'F10',
    KEY_F11: 'F11',
    KEY_F12: 'F12',
    KEY_F13: 'F13',
    KEY_F14: 'F14',
    KEY_F15: 'F15',
    KEY_F16: 'F16',
    KEY_F17: 'F17',
    KEY_F18: 'F18',
    KEY_F19: 'F19',
    KEY_F20: 'F20',
    KEY_F21: 'F21',
    KEY_F22: 'F22',
    KEY_F23: 'F23',
    KEY_F24: 'F24',

    KEY_KP0: 'NUMPAD0',
    KEY_KP1: 'NUMPAD1',
    KEY_KP2: 'NUMPAD2',
    KEY_KP3: 'NUMPAD3',
    KEY_KP4: 'NUMPAD4',
    KEY_KP5: 'NUMPAD5',
    KEY_KP6: 'NUMPAD6',
    KEY_KP7: 'NUMPAD7',
    KEY_KP8: 'NUMPAD8',
    KEY_KP9: 'NUMPAD9',
    KEY_KPDOT: 'NUMPADDOT',
    KEY_KPPLUS: 'NUMPADPLUS',
    KEY_KPMINUS: 'NUMPADMINUS',
    KEY_KPASTERISK: 'NUMPADMUL',
    KEY_KPSLASH: 'NUMPADDIV',
    KEY_KPENTER: 'NUMPADENTER',
    KEY_KPEQUAL: 'NUMPADEQUAL',
    KEY_KPPLUSMINUS: 'NUMPADPLUSMINUS',
    KEY_KPCOMMA: 'NUMPADCOMMA',
    KEY_KPJPCOMMA: 'NUMPADJPCOMMA',
    KEY_KPLEFTPAREN: 'NUMPADLPAREN',
    KEY_KPRIGHTPAREN: 'NUMPADRPAREN',

    KEY_MUTE: 'MUTE',
    KEY_VOLUMEDOWN: 'VOLDOWN',
    KEY_VOLUMEUP: 'VOLUP',
    KEY_PLAYPAUSE: 'PLAYPAUSE',
    KEY_PLAYCD: 'PLAYPAUSE',
    KEY_PAUSECD: 'PLAYPAUSE',
    KEY_PLAY: 'PLAYPAUSE',
    KEY_STOPCD: 'STOP',
    KEY_NEXTSONG: 'NEXT',
    KEY_PREVIOUSSONG: 'PREV',
    KEY_RECORD: 'RECORD',
    KEY_REWIND: 'REWIND',
    KEY_FASTFORWARD: 'FASTFORWARD',

    KEY_WWW: 'BROWSER',
    KEY_HOMEPAGE: 'HOMEPAGE',
    KEY_REFRESH: 'REFRESH',
    KEY_BACK: 'BROWSERBACK',
    KEY_FORWARD: 'BROWSERFORWARD',
    KEY_SEARCH: 'SEARCH',
    KEY_MAIL: 'MAIL',
    KEY_COMPUTER: 'MYCOMPUTER',
    KEY_CALC: 'CALC',

    KEY_SLEEP: 'SLEEP',
    KEY_WAKEUP: 'WAKE',
    KEY_POWER: 'POWER',

    KEY_PRINT: 'PRINT',
    KEY_SAVE: 'SAVE',
    KEY_OPEN: 'OPEN',
    KEY_COPY: 'COPY',
    KEY_PASTE: 'PASTE',
    KEY_CUT: 'CUT',
    KEY_UNDO: 'UNDO',
    KEY_REDO: 'REDO',
    KEY_FIND: 'FIND',
    KEY_HELP: 'HELP',

    KEY_BRIGHTNESSDOWN: 'BRIGHTDOWN',
    KEY_BRIGHTNESSUP: 'BRIGHTUP',
    KEY_KBDILLUMTOGGLE: 'KBDLITTOGGLE',
    KEY_KBDILLUMDOWN: 'KBDLITDOWN',
    KEY_KBDILLUMUP: 'KBDLITUP',

    KEY_UNKNOWN: 'UNKNOWN',
}

KEYLETTERS = {
    KEY_A: 'A', KEY_B: 'B', KEY_C: 'C', KEY_D: 'D', KEY_E: 'E',
    KEY_F: 'F', KEY_G: 'G', KEY_H: 'H', KEY_I: 'I', KEY_J: 'J',
    KEY_K: 'K', KEY_L: 'L', KEY_M: 'M', KEY_N: 'N', KEY_O: 'O',
    KEY_P: 'P', KEY_Q: 'Q', KEY_R: 'R', KEY_S: 'S', KEY_T: 'T',
    KEY_U: 'U', KEY_V: 'V', KEY_W: 'W', KEY_X: 'X', KEY_Y: 'Y',
    KEY_Z: 'Z',
}

KEYPRINTABLE = {
    KEY_1: '1',
    KEY_2: '2',
    KEY_3: '3',
    KEY_4: '4',
    KEY_5: '5',
    KEY_6: '6',
    KEY_7: '7',
    KEY_8: '8',
    KEY_9: '9',
    KEY_0: '0',
    KEY_MINUS: '-',
    KEY_EQUAL: '=',
    KEY_LEFTBRACE: '[',
    KEY_RIGHTBRACE: ']',
    KEY_BACKSLASH: '\\',
    KEY_SEMICOLON: ';',
    KEY_APOSTROPHE: "'",
    KEY_GRAVE: '`',
    KEY_COMMA: ',',
    KEY_DOT: '.',
    KEY_SLASH: '/',
}

SHIFTED = {
    '1': '!',
    '2': '@',
    '3': '#',
    '4': '$',
    '5': '%',
    '6': '^',
    '7': '&',
    '8': '*',
    '9': '(',
    '0': ')',
    '-': '_',
    '=': '+',
    '[': '{',
    ']': '}',
    '\\': '|',
    ';': ':',
    "'": '"',
    ',': '<',
    '.': '>',
    '/': '?',
    '`': '~',
}

# alias tables
ALIASES = {}

GENERICMODS = {
    'SHIFT': ('LSHIFT', 'RSHIFT'),
    'CTRL': ('LCTRL', 'RCTRL'),
    'ALT': ('LALT', 'RALT'),
    'WIN': ('LWIN', 'RWIN'),
    'META': ('LWIN', 'RWIN'),
    'SUPER': ('LWIN', 'RWIN'),
}

ALIASGROUPS = {
    'ESC': ['ESC', 'ESCAPE', 'VK_ESCAPE', '<ESC>', '<ESCAPE>'],
    'ENTER': ['ENTER', 'RETURN', 'VK_RETURN', '<ENTER>', '<RETURN>'],
    'TAB': ['TAB', 'VK_TAB', '<TAB>'],
    'BACKSPACE': ['BACKSPACE', 'BKSP', 'VK_BACK', '<BACKSPACE>'],
    'SPACE': ['SPACE', 'SPACEBAR', 'VK_SPACE', '<SPACE>'],
    'DELETE': ['DELETE', 'DEL', 'VK_DELETE', '<DEL>', '<DELETE>'],
    'INS': ['INS', 'INSERT', 'VK_INSERT', '<INS>', '<INSERT>'],
    'HOME': ['HOME', 'VK_HOME', '<HOME>'],
    'END': ['END', 'VK_END', '<END>'],
    'PGUP': ['PGUP', 'PAGEUP', 'PRIOR', 'VK_PRIOR', '<PGUP>'],
    'PGDN': ['PGDN', 'PAGEDOWN', 'NEXT', 'VK_NEXT', '<PGDN>'],
    'UP': ['UP', 'ARROWUP', 'VK_UP', '<UP>'],
    'DOWN': ['DOWN', 'ARROWDOWN', 'VK_DOWN', '<DOWN>'],
    'LEFT': ['LEFT', 'ARROWLEFT', 'VK_LEFT', '<LEFT>'],
    'RIGHT': ['RIGHT', 'ARROWRIGHT', 'VK_RIGHT', '<RIGHT>'],

    'LSHIFT': ['LSHIFT', 'LEFTSHIFT'],
    'RSHIFT': ['RSHIFT', 'RIGHTSHIFT'],
    'LCTRL': ['LCTRL', 'LEFTCTRL', 'LCONTROL', 'LEFTCONTROL'],
    'RCTRL': ['RCTRL', 'RIGHTCTRL', 'RCONTROL', 'RIGHTCONTROL'],
    'LALT': ['LALT', 'LEFTALT'],
    'RALT': ['RALT', 'RIGHTALT', 'ALTGR', 'RIGHTALTGR'],
    'LWIN': ['LWIN', 'LEFTWIN', 'LGUI', 'LEFTMETA', 'LEFTSUPER'],
    'RWIN': ['RWIN', 'RIGHTWIN', 'RGUI', 'RIGHTMETA', 'RIGHTSUPER'],
    'APPS': ['APPS', 'MENU', 'CONTEXT', 'CONTEXTMENU', 'VK_APPS'],

    'CAPSLOCK': ['CAPSLOCK', 'CAPS', 'VK_CAPITAL'],
    'NUMLOCK': ['NUMLOCK', 'VK_NUMLOCK'],
    'SCROLLLOCK': ['SCROLLLOCK', 'SCROLL', 'VK_SCROLL'],
    'PRTSCR': ['PRTSCR', 'PRTSC', 'PRINTSCREEN', 'VK_SNAPSHOT'],
    'PAUSE': ['PAUSE', 'BREAK', 'VK_PAUSE'],
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

    ALIASES[f'F{i}'] = f'F{i}'
    ALIASES[f'VK_F{i}'] = f'F{i}'

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



# file functions
def openlog():


    # open log file
    _log = open(LOGFILE, 'a', buffering=1)
    sys.stdout = _log
    sys.stderr = _log

def openkeyboard():

    global _fd, _KBDPATH


    # close existing
    if _fd is not None:
        os.close(_fd)

    for name in EVENT_CANDIDATES:

        path = os.path.join(NODEDIR, name)

        try:

            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)


            flags = fcntl.fcntl(fd, fcntl.F_GETFD)
            fcntl.fcntl(fd, fcntl.F_SETFD, flags | fcntl.FD_CLOEXEC)

            if not iskeyboard(fd):

                os.close(fd)
                continue

            _fd = fd
            _KBDPATH = path

            print(f"{timestamp()} [input] using keyboard {path}", flush=True)
            return True

        except FileNotFoundError:

            continue

        except PermissionError:

            print(f"{timestamp()} [input] permission denied to open {path}", flush=True)
            continue

        except Exception as e:

            print(f"{timestamp()} [input] error opening {path} {e}", flush=True)
            continue

    global _no_device_logged
    if not _no_device_logged:

        print(f"{timestamp()} [input] no keyboards found", flush=True)
        _no_device_logged = True

    _fd = None
    return False


def openmouse():

    global _MFD, _mouse_open_logged


    # close existing
    if _MFD is not None:
        os.close(_MFD)

    preferred = os.path.join(NODEDIR, 'event2')

    if preferred != _KBDPATH:

        try:

            fd = os.open(preferred, os.O_RDONLY | os.O_NONBLOCK)


            flags = fcntl.fcntl(fd, fcntl.F_GETFD)
            fcntl.fcntl(fd, fcntl.F_SETFD, flags | fcntl.FD_CLOEXEC)

            _MFD = fd
            print(f"{timestamp()} [input] using mouse {preferred}", flush=True)
            _mouse_open_logged = True
            return True

        except FileNotFoundError:
            pass

        except PermissionError:

            print(f"{timestamp()} [input] permission denied to open {preferred}", flush=True)

        except Exception as e:

            print(f"{timestamp()} [input] error opening {preferred} {e}", flush=True)

    for name in EVENT_CANDIDATES:

        path = os.path.join(NODEDIR, name)

        if path == _KBDPATH or path == preferred:
            continue

        try:

            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)


            flags = fcntl.fcntl(fd, fcntl.F_GETFD)
            fcntl.fcntl(fd, fcntl.F_SETFD, flags | fcntl.FD_CLOEXEC)

            _MFD = fd
            print(f"{timestamp()} [input] using mouse {path}", flush=True)
            _mouse_open_logged = True
            return True

        except FileNotFoundError:

            continue

        except PermissionError:

            print(f"{timestamp()} [input] permission denied to open {path}", flush=True)
            continue

        except Exception as e:

            print(f"{timestamp()} [input] error opening {path} {e}", flush=True)
            continue

    if not _mouse_open_logged:
        print(f"{timestamp()} [input] no mouse device found", flush=True)
        _mouse_open_logged = True

    _MFD = None
    return False


def ioc(dir, type, nr, size):

    try:

        # build ioctl number
        num = (dir << IOCDIRSHIFT) | (ord(type) << IOCTYPESHIFT) | (nr << IOCNRSHIFT) | (size << IOCSIZESHIFT)

        return num

    except Exception:

        # ioctl build error
        return 0


def ior(type, nr, size):

    try:

        # read ioctl
        return ioc(IOCREAD, type, nr, size)

    except Exception:

        # ioctl build error
        return 0


def eviocgbit(ev, size):

    try:

        # EVIOCGBIT(ev, len) = _IOR('E', 0x20 + ev, len)
        return ior('E', 0x20 + ev, size)

    except Exception:

        # ioctl build error
        return 0


def hasbit(buf, bit):

    try:

        # compute index
        b = int(bit)
        i = b // 8
        m = 1 << (b % 8)

        if i < 0:
            return False

        if i >= len(buf):
            return False

        # test bit
        return (buf[i] & m) != 0

    except Exception:

        # bit test error
        return False


def getbits(fd, ev, size):

    try:

        # allocate buffer
        buf = bytearray(size)

        # run ioctl
        req = eviocgbit(ev, size)
        if req == 0:
            return None

        fcntl.ioctl(fd, req, buf, True)

        return buf

    except OSError:

        # ioctl unsupported or device error
        return None

    except Exception:

        # other error
        return None


def iskeyboard(fd):

    try:

        # read event types
        types = getbits(fd, 0, 32)

        if types is None:

            # cannot probe, allow fallback
            return True

        if not hasbit(types, EV_KEY):

            # device has no key events
            return False

        # read key capabilities
        keys = getbits(fd, EV_KEY, 128)

        if keys is None:

            # cannot probe, allow fallback
            return True

        # require common keyboard keys
        if hasbit(keys, KEY_A) and hasbit(keys, KEY_ENTER):
            return True

        return False

    except Exception:

        # probe error, allow fallback
        return True


# normalize functions
def normkey(ref):

    if ref is None:
        return None

    if isinstance(ref, int):

        try:

            if ref in KEYCODES:
                return KEYCODES[ref]

            if ref in KEYLETTERS:
                return KEYLETTERS[ref]

            if ref in KEYPRINTABLE:
                return KEYPRINTABLE[ref]

        except Exception:
            return None

        return None

    try:

        s = str(ref).strip()

    except Exception:
        return None

    if not s:
        return None

    if s.startswith('<') and s.endswith('>') and len(s) > 2:
        s = s[1:-1]

    up = s.upper()

    if up in ALIASES:
        return ALIASES[up]

    if up in GENERICMODS:
        return up

    return up


def modstate():

    try:

        return {
            'shift': (_mods['lshift'] or _mods['rshift']),
            'ctrl': (_mods['lctrl'] or _mods['rctrl']),
            'alt': (_mods['lalt'] or _mods['ralt']),
            'win': (_mods['lwin'] or _mods['rwin']),
            'caps': _mods['caps'],
            'num': _mods['num'],
            'scroll': _mods['scroll'],
        }

    except Exception:

        return {
            'shift': False,
            'ctrl': False,
            'alt': False,
            'win': False,
            'caps': False,
            'num': False,
            'scroll': False,
        }


def updatemods(code, value):

    pressed = (value != 0)

    if code == KEY_LEFTSHIFT:
        _mods['lshift'] = pressed
        return True

    if code == KEY_RIGHTSHIFT:
        _mods['rshift'] = pressed
        return True

    if code == KEY_LEFTCTRL:
        _mods['lctrl'] = pressed
        return True

    if code == KEY_RIGHTCTRL:
        _mods['rctrl'] = pressed
        return True

    if code == KEY_LEFTALT:
        _mods['lalt'] = pressed
        return True

    if code == KEY_RIGHTALT:
        _mods['ralt'] = pressed
        return True

    if code == KEY_LEFTMETA:
        _mods['lwin'] = pressed
        return True

    if code == KEY_RIGHTMETA:
        _mods['rwin'] = pressed
        return True

    if code == KEY_CAPSLOCK and value == 1:
        _mods['caps'] = (not _mods['caps'])
        return True

    if code == KEY_NUMLOCK and value == 1:
        _mods['num'] = (not _mods['num'])
        return True

    if code == KEY_SCROLLLOCK and value == 1:
        _mods['scroll'] = (not _mods['scroll'])
        return True

    return False



# decode functions
def keyname(code):

    if code in KEYCODES:
        return KEYCODES[code]

    if code in KEYLETTERS:
        return KEYLETTERS[code]

    if code in KEYPRINTABLE:
        return KEYPRINTABLE[code]

    return None


def keychar(name, mods):

    if name is None:
        return None

    if mods.get('ctrl', False) or mods.get('alt', False) or mods.get('win', False):
        return None

    if len(name) == 1 and name.isalpha():

        upper = (mods.get('caps', False) ^ mods.get('shift', False))

        if upper:
            ch = name.upper()
        else:
            ch = name.lower()

        return ch

    if len(name) == 1 and name in KEYPRINTABLE.values():

        if mods.get('shift', False) and name in SHIFTED:
            return SHIFTED[name]

        return name

    if name == 'SPACE':
        return ' '

    if name == 'TAB':
        return '\t'

    if name == 'ENTER':
        return '\n'

    if name == 'ESC':
        return '\x1b'

    if name == 'BACKSPACE':
        return '\b'

    return None


def keyevent(code, value):

    try:

        ismod = updatemods(code, value)

    except Exception:
        ismod = False

    name = keyname(code)

    mods = modstate()

    if value == 0:
        state = 'up'
    elif value == 1:
        state = 'down'
    else:
        state = 'repeat'

    ch = None

    if not ismod and state in ('down', 'repeat'):

        try:
            ch = keychar(name, mods)
        except Exception:
            ch = None

    return {
        'code': code,
        'name': name,
        'state': state,
        'mods': mods,
        'char': ch,
    }



# shortcut functions
def parsecombo(text):

    if text is None:
        return None

    try:

        raw = str(text).strip()

    except Exception:
        return None

    if not raw:
        return None

    parts = [p.strip() for p in raw.replace('-', '+').split('+') if p.strip()]

    mods = {
        'SHIFT': False,
        'CTRL': False,
        'ALT': False,
        'WIN': False,
    }

    key = None

    for p in parts:

        k = normkey(p)

        if k in ('SHIFT', 'CTRL', 'ALT', 'WIN', 'META', 'SUPER'):

            if k == 'META' or k == 'SUPER':
                k = 'WIN'

            mods[k] = True
            continue

        if k in ('LSHIFT', 'RSHIFT'):
            mods['SHIFT'] = True
            continue

        if k in ('LCTRL', 'RCTRL'):
            mods['CTRL'] = True
            continue

        if k in ('LALT', 'RALT'):
            mods['ALT'] = True
            continue

        if k in ('LWIN', 'RWIN'):
            mods['WIN'] = True
            continue

        key = k

    if key is None:
        return None

    return {
        'mods': mods,
        'key': key,
    }


def matchcombo(ev, combo):

    if ev is None or combo is None:
        return False

    try:

        if ev.get('state') != 'down':
            return False

        key = ev.get('name')

        if key != combo.get('key'):
            return False

        m = ev.get('mods', {})
        want = combo.get('mods', {})

        if bool(want.get('SHIFT')) != bool(m.get('shift')):
            return False

        if bool(want.get('CTRL')) != bool(m.get('ctrl')):
            return False

        if bool(want.get('ALT')) != bool(m.get('alt')):
            return False

        if bool(want.get('WIN')) != bool(m.get('win')):
            return False

        return True

    except Exception:
        return False



# read functions
def readraw(timeout_ms=0):

    if _fd is None:
        return []

    try:

        r, _, _ = select.select([_fd], [], [], timeout_ms / 1000.0)
        if not r:
            return []

    except Exception as e:

        print(f"{timestamp()} [input] select error {e}", flush=True)
        return []

    events = []
    while True:

        try:

            data = os.read(_fd, EV_SIZE)

            if not data or len(data) < EV_SIZE:
                break

            tv_sec, tv_usec, ev_type, ev_code, ev_value = struct.unpack(EV_FORMAT, data)

            events.append((ev_type, ev_code, ev_value))

        except BlockingIOError as e:

            if e.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                break

            print(f"{timestamp()} [input] read would block {e}", flush=True)
            break

        except Exception as e:

            print(f"{timestamp()} [input] read error {e}", flush=True)
            break

    return events


def readmouse(timeout_ms=0):

    if _MFD is None:
        return []

    try:

        r, _, _ = select.select([_MFD], [], [], timeout_ms / 1000.0)
        if not r:
            return []

    except Exception as e:

        print(f"{timestamp()} [input] mouse select error {e}", flush=True)
        return []

    events = []
    dx = 0
    dy = 0
    dz = 0
    dh = 0
    buttons = []

    while True:

        try:

            data = os.read(_MFD, EV_SIZE)
            if not data or len(data) < EV_SIZE:
                break

            tv_sec, tv_usec, ev_type, ev_code, ev_value = struct.unpack(EV_FORMAT, data)

            if ev_type == EV_REL:

                if ev_code == REL_X:
                    dx += ev_value

                elif ev_code == REL_Y:
                    dy += ev_value

                elif ev_code == REL_WHEEL:
                    dz += ev_value

                elif ev_code == REL_HWHEEL:
                    dh += ev_value

            elif ev_type == EV_ABS:
                pass

            elif ev_type == EV_KEY:

                if ev_code == BTN_LEFT:
                    buttons.append(('left', ev_value != 0))

                elif ev_code == BTN_RIGHT:
                    buttons.append(('right', ev_value != 0))

                elif ev_code == BTN_MIDDLE:
                    buttons.append(('middle', ev_value != 0))

            elif ev_type == EV_SYN and ev_code == SYN_REPORT:

                if dx or dy:
                    events.append(('move', dx, dy))
                    dx = 0
                    dy = 0

                if dz:
                    events.append(('scroll', dz))
                    dz = 0

                if dh:
                    events.append(('hscroll', dh))
                    dh = 0

                for bname, state in buttons:
                    events.append(('button', bname, state))
                buttons = []

        except BlockingIOError as e:

            if e.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                break

            print(f"{timestamp()} [input] mouse read would block {e}", flush=True)
            break

        except Exception as e:

            print(f"{timestamp()} [input] mouse read error {e}", flush=True)
            break

    if dx or dy:
        events.append(('move', dx, dy))

    if dz:
        events.append(('scroll', dz))

    if dh:
        events.append(('hscroll', dh))

    for bname, state in buttons:
        events.append(('button', bname, state))

    return events



# decode functions
def readkeys(timeout_ms=0):

    out = []

    events = readraw(timeout_ms=timeout_ms)

    for ev_type, ev_code, ev_value in events:

        if ev_type != EV_KEY:
            continue

        try:

            out.append(keyevent(ev_code, ev_value))

        except Exception as e:

            print(f"{timestamp()} [input] keyevent error code={ev_code} value={ev_value} {e}", flush=True)
            continue

    return out


def readchars(timeout_ms=0):

    chars = []

    keys = readkeys(timeout_ms=timeout_ms)

    for ev in keys:


        ch = ev.get('char')

        if ch is not None:
            chars.append(ch)

    return chars



# convenience functions
def getchar(block=True, timeout_ms=0):

    if block:

        while True:

            chars = readchars(timeout_ms=timeout_ms)

            if chars:
                return chars[0]

            time.sleep(0.001)

    chars = readchars(timeout_ms=timeout_ms)
    return chars[0] if chars else None


def getline(echo=False, maxlen=4096):

    buf = []

    while True:

        ch = getchar(block=True, timeout_ms=0)

        if ch == '\n':

            if echo:
                sys.__stdout__.write('\n')
                sys.__stdout__.flush()
            return ''.join(buf)

        if ch == '\b':

            if buf:
                buf.pop()

                if echo:
                    sys.__stdout__.write('\b \b')
                    sys.__stdout__.flush()
            continue

        if isinstance(ch, str) and len(ch) == 1 and 32 <= ord(ch) <= 126:

            if len(buf) < maxlen:
                buf.append(ch)

                if echo:
                    sys.__stdout__.write(ch)
                    sys.__stdout__.flush()
            continue


def pollmouse(timeout_ms=0):

    try:
        return readmouse(timeout_ms=timeout_ms)
    except Exception as e:
        print(f"{timestamp()} [input] pollmouse error {e}", flush=True)
        return []
