#!"/the one/software/python/bin/python" -B
"""
brick.py

brick is the shell of The One OS.
"""



## imports
import os
import io
import sys
import ast
import importlib.util
import importlib.machinery
import time
import math
import json
import glob
import re
import stat
import shlex
import shutil
import hashlib
import base64
import difflib
import ctypes
import socket
import ipaddress
import signal
import atexit
import selectors
import contextlib
import subprocess
import codecs
import struct
import unicodedata
import datetime
import zoneinfo
from pyroute2 import IPRoute
from collections import deque
try:
    import fcntl
    import termios
except ImportError:
    fcntl = None
    termios = None

SOURCEBUILD = os.path.abspath(
    os.environ.get('T1OS_SOURCE_BUILD', '/the one/build')
)

if not os.path.isfile(os.path.join(SOURCEBUILD, 'brick', 'brick.py')):
    SOURCEBUILD = '/the one/build'

def _prefer_source_build():
    while SOURCEBUILD in sys.path:
        sys.path.remove(SOURCEBUILD)
    sys.path.insert(0, SOURCEBUILD)


_prefer_source_build()

from graphics.graphics import *
import graphics.graphics as gfx
_prefer_source_build()
from reign.reign import timestamp
from GODDESS.GODDESS import formatlog, popenisolated
_prefer_source_build()
import architect.architect as arch
_prefer_source_build()
from exchange.exchange import exset, exget
_prefer_source_build()
from input.input import openkeyboard, getchar, readchars
_prefer_source_build()
from rubbish.rubbish import emptyrubbish, restorefromrubbish, storepaths
import rubbish.rubbish as rubbishapi
_prefer_source_build()
from operations.operations import (
    PowerRequestError,
    addstartupoperation,
    changestartupoperation,
    listcatalogueapplications,
    removestartupoperation,
    requestpower,
    requestsessionlogout,
    runoperation,
    settings_account_get,
    settings_hostname_set,
    settings_master_update,
    settings_time_set,
    startupoperations,
)
_prefer_source_build()
from python.python import PythonManagerError, request as pythonrequest

BRICKVMTESTSTATUSPATH = '/.ephemeral/brick-vm-test.json'
BRICKNETWORKDIR = os.environ.get(
    'T1OS_NETWORK_SETTINGS', '/the one/settings/network')
BRICKNETWORKFILE = os.path.join(BRICKNETWORKDIR, 'network.txt')
BRICKDNSFILE = os.path.join(BRICKNETWORKDIR, 'dns.txt')
BRICKNETWORKSTATE = os.environ.get(
    'T1OS_NETWORK_STATE', '/.ephemeral/network/connection.json')
BRICKFIREWALLSTATE = os.environ.get(
    'T1OS_FIREWALL_STATE', '/.ephemeral/network/firewall.json')
BRICKWIRELESSSTATE = os.environ.get(
    'T1OS_WIRELESS_SCAN_STATE', '/.ephemeral/network/wireless.json')
BRICKWIRELESSREQUEST = os.environ.get(
    'T1OS_WIRELESS_SCAN_REQUEST', '/.ephemeral/network/scan.request')
BRICKNETWORKREQUEST = os.environ.get(
    'T1OS_NETWORK_RECONFIGURE', '/.ephemeral/network/reconfigure.request')
BRICKNETSTATE = os.environ.get('T1OS_NET_STATE', '/sys/class/net')
BRICKDRIVERSTATE = os.environ.get(
    'T1OS_DRIVER_STATUS', '/.ephemeral/drivers/status.json')
BRICKDRIVEMODULESTATE = os.environ.get(
    'T1OS_DRIVER_MODULE_STATE', '/the one/drivers/state/module')
BRICKTIMEZONEDIR = os.environ.get(
    'T1OS_TIMEZONE_DIRECTORY', '/the one/software/chromium/resources/zoneinfo')
BRICKTIMEZONEFILE = os.environ.get(
    'T1OS_TIMEZONE_FILE', '/the one/settings/time/timezone.txt')
BRICKINTERNETTIMEFILE = os.environ.get(
    'T1OS_INTERNET_TIME_FILE', '/the one/settings/time/internet.txt')
BRICKVIRTUALBOXTIMEFILE = os.environ.get(
    'T1OS_VIRTUALBOX_TIME_FILE', '/the one/settings/time/virtualbox.txt')
BRICKTERMINALNAMEFILE = os.environ.get(
    'T1OS_TERMINAL_NAME_FILE', '/the one/settings/terminal/name.txt')
BRICKMASTERSETTINGSFILE = os.environ.get(
    'T1OS_MASTER_SETTINGS_FILE', '/the one/settings/master/settings.json')
BRICKRUBBISHINDEX = os.environ.get(
    'T1OS_RUBBISH_INDEX', '/.rubbish/index.txt')
ATREYANSTARTYEAR = 2021


def writebrickvmteststatus(stage, **detail):
    if os.environ.get('T1OS_VM_TEST') != '1':
        return
    temporary = '{}.{}.tmp'.format(BRICKVMTESTSTATUSPATH, os.getpid())
    try:
        payload = {
            'format': 1,
            'pid': os.getpid(),
            'stage': str(stage),
        }
        payload.update(detail)
        with open(temporary, 'w', encoding='utf-8') as stream:
            json.dump(payload, stream, sort_keys=True, separators=(',', ':'))
            stream.write('\n')
        os.chmod(temporary, 0o604)
        os.replace(temporary, BRICKVMTESTSTATUSPATH)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass

try:
    _prefer_source_build()
    from viewer.viewer import request as viewerrequest

except Exception:
    viewerrequest = None
_prefer_source_build()
from audio.audio import sendcontrol as audiocontrol

try:
    _prefer_source_build()
    import media.media as mediaapi

except Exception:
    mediaapi = None

_prefer_source_build()


class GenerationDeque(deque):
    """A deque whose generation changes after every possible mutation."""

    def __init__(self, iterable=(), maxlen=None):
        super().__init__(iterable, maxlen=maxlen)
        self.generation = 0

    def _changed(self):
        self.generation += 1

    def append(self, value):
        super().append(value)
        self._changed()

    def appendleft(self, value):
        super().appendleft(value)
        self._changed()

    def clear(self):
        super().clear()
        self._changed()

    def extend(self, values):
        super().extend(values)
        self._changed()

    def extendleft(self, values):
        super().extendleft(values)
        self._changed()

    def insert(self, index, value):
        super().insert(index, value)
        self._changed()

    def pop(self):
        value = super().pop()
        self._changed()
        return value

    def popleft(self):
        value = super().popleft()
        self._changed()
        return value

    def remove(self, value):
        super().remove(value)
        self._changed()

    def reverse(self):
        super().reverse()
        self._changed()

    def rotate(self, amount=1):
        super().rotate(amount)
        self._changed()

    def __setitem__(self, index, value):
        super().__setitem__(index, value)
        self._changed()

    def __delitem__(self, index):
        super().__delitem__(index)
        self._changed()



## globals

# misc

RUNNING = True
SHOWHIDDEN = False
HEADLESS = False
DRIVENUMBER = 1
BRICKPATH = os.path.join(SOURCEBUILD, 'brick', 'brick.py')
SETTINGSAPPPATH = os.path.join(SOURCEBUILD, 'settings', 'settings.py')
RUNAPPLICATIONALIASES = {
    'settings': SETTINGSAPPPATH,
}
RUNAPPLICATIONPATHS = frozenset(RUNAPPLICATIONALIASES.values())
AUDIOAPIPATH = '/the one/build/audio/audio.py'
PLAYBACKSTATUSPREFIX = 'T1OS_AUDIO_STATUS '
MEDIAAPIPATH = '/the one/build/media/media.py'
MEDIASTATUSPREFIX = 'T1OS_MEDIA_STATUS '
MEDIAFRAMEPREFIX = 'T1OS_MEDIA_FRAME '
VIEWERPATH = '/the one/build/viewer/viewer.py'
STOPKEY = '\x13'
INVALIDPATH = '\0'

# T1OS version
with open('/the one/settings/t1osversion.txt') as f:
    OSVERSION = f.read().strip()

# sockets
WINDOWSOCKPATH = "/.ephemeral/windowserver/accept.sock"
OPERATIONSSOCKET='/.ephemeral/operations/control.sock'

# colours
TEXTCOLOUR = 0xEFEFEF
CURSORCOLOUR = 0xEFEFEF
ERRORCOLOUR = 0xFF0000
BACKGROUNDCOLOUR = 0x000000
SUGGESTCOLOUR = 0x6A6A6A

# screen
BASESCREENW = 1920
BASESCREENH = 1080
SCREENW = 0
SCREENH = 0
UISCALE = 1.0
WORKX = 0
WORKY = 0
WORKW = 0
WORKH = 0

# font
BASEFONTSIZE = 14
BASELINEHEIGHT = 14
BASETEXTSCALE = 2
FONTSIZE = 14
LINEHEIGHT = 14
TEXTSCALE = 2
FONTOVERRIDE = None
LINEHEIGHTOVERRIDE = None
FONTSTEP = 2
MINFONTSIZE = 8
MAXFONTSIZE = 96
USE_TTF = False
FONTREG = '/the one/resources/fonts/firacode.ttf'
FONTBOLD = "/the one/resources/fonts/firacodebold.ttf"
FONTSEMIBOLD = '/the one/resources/fonts/firacodesemibold.ttf'
CURRENTTTFFONT = None
BRICKSETTINGSFILE = '/the one/settings/brick/settings.json'

# content
TOPBLANKLINES = 2
SPACEW = 0
PROMPTW = 0
PROMPT = '>'
SPACERLINES = 1
BLINKINTERVAL = 0.5
PREV_CWD = ''
PREV_SCROLL_LEN = 0
PREV_SCROLLOFF = 0
PREV_INPUTBUF = ''
PREV_CURSORPOS = 0
PREV_ROWS = 0
PREV_CURSOR_ON = False
CONTENT_TOP_Y = 0
DIRTY_SCROLL = True
DIRTY_PROMPT = True
MAXINPUT = 4096
SCROLL_MAX = 5000
SCROLL = GenerationDeque(maxlen=SCROLL_MAX)
STYLES = GenerationDeque(maxlen=SCROLL_MAX)
LASTSCROLLFRAME = 0.0
SCROLLMANAGEDINTERVAL = 1.0 / 60.0
SCROLLCPUINTERVAL = 1.0 / 12.0
SCROLLSTEP = 3
PENDINGSCROLL = 0
LASTSMOOTHSCROLL = 0.0
SMOOTHSCROLLEASING = 0.25
SMOOTHSCROLLMAXSTEP = 6
INPUTBUF = ''
MULTILINES = []
LASTCWD = ''
PREVTIER = None
MODAL=0
CURSORPOS = 0
LASTTABBUF = ''
LASTTABCANDS = []
SCROLLOFF = 0

# image viewer
VIEWNEXT = 0
VIEWROOT = f'/.ephemeral/brick/{os.getpid()}'

# history
HIST = []
HISTPOS = None
HISTMAX = 2000
SUGGEST = ""
HISTFILE = '/the one/settings/brick/.brick_history'

# Numeric drive locations are public (for example, 2/); their Linux mount
# targets remain private beneath the ephemeral runtime.
DRIVES = {1: {'number': 1, 'root': '/', 'label': 't1os', 'removable': False}}
DRIVELASTSCAN = 0.0
DRIVESCANINTERVAL = 2.0
DRIVEBACKINGROOT = '/.ephemeral/volumes'
DRIVEMETADATAFILE = '/.ephemeral/drivers/volumes.json'
DRIVESETTINGSFILE = '/the one/settings/array/settings.json'
BRICKLSMFORBIDDENROOTS = tuple(
    f'/{name}'
    for name in (
        'bin', 'sbin', 'lib', 'lib64', 'usr', 'etc',
        'dev', 'proc', 'sys', 'run', 'var', 'tmp',
        'home', 'root', 'media', 'mnt', 'opt', 'srv',
    )
)
BRICKLSMMASTERDENIED = (
    '/the one/settings/operations',
    '/the one/settings/windowserver',
    '/the one/drivers',
)
LINKFILEHEADER = b'T1OS link\n'
LINKFILEVERSION = 1
LINKFILEMAXBYTES = 16384
LINKFILEMAXHOPS = 16

# window
SEL = selectors.DefaultSelector()
WINID = None
BUF = None
SOCK = None
INBUF = b""
OUTBUF = bytearray()
OUTBUFLIMIT = 4 * 1024 * 1024
HASFOCUS = True
CTRLHELD = False
KEYQUEUE = deque()
RESIZEPENDINGW = 0
RESIZEPENDINGH = 0
RESIZEPENDINGAT = 0.0
RESIZEAPPLIEDW = 0
RESIZEAPPLIEDH = 0
# Windowserver already coalesces resize requests and only emits RESIZED after
# the geometry has been stable for 80 ms.  Applying another client-side delay
# leaves Brick rendering commands for the old surface against the new window
# bounds, which can invalidate an otherwise healthy retained GPU scene.
RESIZEDELAY = 0.0
BASEWINDOWW = 900
BASEWINDOWH = 600
BASEWINDOWX = 100
BASEWINDOWY = 100
WINDOWMINW = 520
WINDOWMINH = 360
WINDOWMARGIN = 40

# managed graphics
GRAPHICSCAPS = {}
GRAPHICSAVAILABLE = False
GRAPHICSACTIVE = False
GRAPHICSPENDING = False
GRAPHICSPENDINGAT = 0.0
GRAPHICSNEEDSUBMIT = False
GRAPHICSLIMIT = 0
GRAPHICSTEXTLIMIT = 1024
GRAPHICSCURSORON = True
GRAPHICSSCENE = []
GRAPHICSFAILURE = ""
GRAPHICSERRORS = 0
GRAPHICSFRAMES = 0
GRAPHICSMAXCOMMANDS = 0
GRAPHICSLASTCOMMANDS = 0
GRAPHICSCPUOVERRIDE = str(os.environ.get("T1OS_BRICK_GRAPHICS", "")).strip().lower() in ("cpu", "off", "0", "false")
GRAPHICSSTATE = managedstate(cpu=GRAPHICSCPUOVERRIDE)

# scrollbars
BASESCROLLBAR_WIDTH = 12
BASESCROLLBAR_MARGIN = 2
BASESCROLLBAR_MIN_THUMB = 20
SCROLLBAR_WIDTH = 12
SCROLLBAR_MARGIN = 2
SCROLLBAR_MIN_THUMB = 20
SCROLLBAR_BG = 0x111111
SCROLLBAR_THUMB = 0x666666
SCROLLBAR_DRAGGING = False
SCROLLBAR_DRAG_OFFSET = 0
HSCROLLBAR_HEIGHT = SCROLLBAR_WIDTH
HSCROLLBAR_VISIBLE = False
HSCROLLBAR_DRAGGING = False
HSCROLLBAR_DRAG_OFFSET = 0
HSCROLL = 0
HSCROLL_MAX = 0
HSCROLL_VIEWCOLS = 0
WRAPCACHEKEY = None
WRAPCACHEROWS = []
CONTENTLAYOUTKEY = None
CONTENTLAYOUTCACHE = None

# session operations
JOBS = {}
JOBNEXT = 1
JOBFORE = None
JOBLAST = None
JOBKEEP = 50

# directive state
DIRECTIVESPECS = []
LASTDIRECTIVERESULT = {'ok': True, 'code': 'ready', 'message': '', 'items': [], 'data': {}}
DIRECTIVEACTIVE = False
DIRECTIVEFAILED = False

# bounded recursive output
RECURSIVERESULTLIMIT = 2000
TRANSACTIONCOPYORIGINAL = None
TRANSACTIONCOPYCOUNT = 0
TRANSACTIONCOPYFAILAT = 0
TRANSACTIONMOVEORIGINAL = None
TRANSACTIONMOVECOUNT = 0
TRANSACTIONMOVEFAILAT = 0

# foreground media playback
PLAYBACK = {}
PLAYBACK_DRAGGING = False
PLAYBACK_PREVIEW = None
PLAYBACK_TRACK_COLOUR = 0x555555
PLAYBACK_CONTROL_COLOUR = TEXTCOLOUR

# selection
SELREGION = None
SELACTIVE = False
SELANCHOR = None
SELEND = None
SELNORMAL = None
PROMPTSELANCHOR = None
PROMPTSELEND = None
PROMPTSELNORMAL = None
MOUSEDOWN = False
MOUSEDOWNBTN = 0
MOUSEX = 0
MOUSEY = 0
SELCHANGED = False
SELDRAGTHROTTLE = 0.0
DBLCLICKWINDOW = 0.35
DBLCLICKDIST = 6
BASEDBLCLICKDIST = 6
LASTCLICKTIME = 0.0
LASTCLICKX = 0
LASTCLICKY = 0
CLICKCOUNT = 0
DOWNX = 0
DOWNY = 0
DOWNINPROMPT = False
DOWNDRAGGED = False

# interactive console
ACTIVE_CONSOLE = None
CONSOLE_HISTORY_MAX = 5000
CONSOLE_READ_LIMIT = 1024 * 1024
CONSOLE_SEQUENCE_LIMIT = 4096
CONSOLE_LAST_MODS = {'shift': False, 'ctrl': False, 'alt': False}
CONSOLE_BUTTONS = set()
CONSOLE_SELECTING = False
CONSOLE_BLINK_ON = True
CONSOLE_SHIFTED = {
    '1': '!', '2': '@', '3': '#', '4': '$', '5': '%',
    '6': '^', '7': '&', '8': '*', '9': '(', '0': ')',
    '-': '_', '=': '+', '[': '{', ']': '}', '\\': '|',
    ';': ':', "'": '"', ',': '<', '.': '>', '/': '?', '`': '~',
}
CONSOLE_PALETTE = (
    0x000000, 0xCD0000, 0x00CD00, 0xCDCD00,
    0x0000EE, 0xCD00CD, 0x00CDCD, 0xE5E5E5,
    0x7F7F7F, 0xFF0000, 0x00FF00, 0xFFFF00,
    0x5C5CFF, 0xFF00FF, 0x00FFFF, 0xFFFFFF,
)



## functions

class ConsoleCell:

    __slots__ = ('text', 'width', 'style')

    def __init__(self, text=' ', width=1, style=None):
        self.text = str(text)
        self.width = int(width)
        self.style = style if style is not None else consolestyledefault()

    def copy(self):
        return ConsoleCell(self.text, self.width, self.style)


class ConsoleLine:

    __slots__ = ('cells', 'wrapped')

    def __init__(self, cols, style=None):
        self.cells = [ConsoleCell(style=style) for _ in range(max(1, int(cols)))]
        self.wrapped = False

    def copy(self):
        line = ConsoleLine(1)
        line.cells = [cell.copy() for cell in self.cells]
        line.wrapped = bool(self.wrapped)
        return line

    def text(self, trim=True):
        value = ''.join(cell.text if cell.width != 0 else '' for cell in self.cells)
        return value.rstrip(' ') if trim else value


def consolestyledefault():
    return (None, None, False, False, False, 0, False, False, False, None, False)


def consolestylewith(style, **changes):
    values = list(style)
    indexes = {
        'fg': 0, 'bg': 1, 'bold': 2, 'faint': 3, 'italic': 4,
        'underline': 5, 'strike': 6, 'inverse': 7, 'conceal': 8,
        'link': 9,
        'blink': 10,
    }
    for name, value in changes.items():
        if name in indexes:
            values[indexes[name]] = value
    return tuple(values)


def consolecharwidth(ch):
    if not ch or unicodedata.combining(ch) or unicodedata.category(ch).startswith('M'):
        return 0
    if unicodedata.category(ch) in ('Cc', 'Cf'):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ('W', 'F') else 1


class ConsoleBuffer:

    def __init__(self, rows, cols, history=True):
        self.rows = max(1, int(rows))
        self.cols = max(2, int(cols))
        self.lines = [ConsoleLine(self.cols) for _ in range(self.rows)]
        self.history = deque(maxlen=CONSOLE_HISTORY_MAX) if history else None
        self.row = 0
        self.col = 0
        self.saved = None
        self.scroll_top = 0
        self.scroll_bottom = self.rows - 1
        self.wrap_pending = False
        self.style = consolestyledefault()
        self.autowrap = True
        self.origin = False
        self.insert = False
        self.newline = False
        self.tabs = {column for column in range(8, self.cols, 8)}
        self.g0 = 'B'
        self.g1 = 'B'
        self.charset = 0

    def blankline(self, style=None):
        return ConsoleLine(self.cols, style if style is not None else self.style)

    def reset(self):
        self.lines = [ConsoleLine(self.cols) for _ in range(self.rows)]
        if self.history is not None:
            self.history.clear()
        self.row = 0
        self.col = 0
        self.saved = None
        self.scroll_top = 0
        self.scroll_bottom = self.rows - 1
        self.wrap_pending = False
        self.style = consolestyledefault()
        self.autowrap = True
        self.origin = False
        self.insert = False
        self.newline = False
        self.tabs = {column for column in range(8, self.cols, 8)}
        self.g0 = 'B'
        self.g1 = 'B'
        self.charset = 0

    def save(self):
        self.saved = (
            self.row, self.col, self.style, self.origin, self.autowrap,
            self.g0, self.g1, self.charset,
        )

    def restore(self):
        if self.saved is None:
            return
        (self.row, self.col, self.style, self.origin, self.autowrap,
         self.g0, self.g1, self.charset) = self.saved
        self.row = max(0, min(self.rows - 1, self.row))
        self.col = max(0, min(self.cols - 1, self.col))
        self.wrap_pending = False

    def setpos(self, row=None, col=None):
        top = self.scroll_top if self.origin else 0
        bottom = self.scroll_bottom if self.origin else self.rows - 1
        if row is not None:
            value = int(row) + (self.scroll_top if self.origin else 0)
            self.row = max(top, min(bottom, value))
        if col is not None:
            self.col = max(0, min(self.cols - 1, int(col)))
        self.wrap_pending = False

    def _clearwide(self, row, col):
        if not (0 <= row < self.rows and 0 <= col < self.cols):
            return
        line = self.lines[row].cells
        if line[col].width == 0 and col > 0:
            line[col - 1] = ConsoleCell(style=self.style)
        elif line[col].width == 2 and col + 1 < self.cols:
            line[col + 1] = ConsoleCell(style=self.style)

    def erasecells(self, row, start, end):
        if not (0 <= row < self.rows):
            return
        start = max(0, min(self.cols, int(start)))
        end = max(start, min(self.cols, int(end)))
        if start < end:
            self._clearwide(row, start)
            self._clearwide(row, end - 1)
        for column in range(start, end):
            self.lines[row].cells[column] = ConsoleCell(style=self.style)

    def scrollup(self, amount=1, top=None, bottom=None):
        top = self.scroll_top if top is None else max(0, int(top))
        bottom = self.scroll_bottom if bottom is None else min(self.rows - 1, int(bottom))
        if bottom < top:
            return
        for _ in range(max(1, min(int(amount), bottom - top + 1))):
            removed = self.lines.pop(top)
            if self.history is not None and top == 0 and bottom == self.rows - 1:
                self.history.append(removed.copy())
            self.lines.insert(bottom, self.blankline())

    def scrolldown(self, amount=1, top=None, bottom=None):
        top = self.scroll_top if top is None else max(0, int(top))
        bottom = self.scroll_bottom if bottom is None else min(self.rows - 1, int(bottom))
        if bottom < top:
            return
        for _ in range(max(1, min(int(amount), bottom - top + 1))):
            self.lines.pop(bottom)
            self.lines.insert(top, self.blankline())

    def index(self):
        if self.row == self.scroll_bottom:
            self.scrollup()
        else:
            self.row = min(self.rows - 1, self.row + 1)
        self.wrap_pending = False

    def reverseindex(self):
        if self.row == self.scroll_top:
            self.scrolldown()
        else:
            self.row = max(0, self.row - 1)
        self.wrap_pending = False

    def carriage(self):
        self.col = 0
        self.wrap_pending = False

    def linefeed(self):
        self.index()
        if self.newline:
            self.carriage()

    def backspace(self):
        self.col = max(0, self.col - 1)
        if self.lines[self.row].cells[self.col].width == 0 and self.col > 0:
            self.col -= 1
        self.wrap_pending = False

    def tab(self, backwards=False):
        if backwards:
            choices = [value for value in self.tabs if value < self.col]
            self.col = max(choices) if choices else 0
        else:
            choices = [value for value in self.tabs if value > self.col]
            self.col = min(choices) if choices else self.cols - 1
        self.wrap_pending = False

    def put(self, ch):
        width = consolecharwidth(ch)
        if width == 0:
            column = self.col - 1
            if self.wrap_pending:
                column = self.col
            while column >= 0 and self.lines[self.row].cells[column].width == 0:
                column -= 1
            if column >= 0:
                self.lines[self.row].cells[column].text += ch
            return

        if self.wrap_pending:
            if self.autowrap:
                self.lines[self.row].wrapped = True
                self.carriage()
                self.index()
            else:
                self.col = self.cols - 1
            self.wrap_pending = False

        if width == 2 and self.col == self.cols - 1:
            if self.autowrap:
                self.lines[self.row].wrapped = True
                self.carriage()
                self.index()
            else:
                width = 1

        if self.insert:
            cells = self.lines[self.row].cells
            for _ in range(width):
                cells.insert(self.col, ConsoleCell(style=self.style))
                cells.pop()

        self._clearwide(self.row, self.col)
        self.lines[self.row].cells[self.col] = ConsoleCell(ch, width, self.style)
        if width == 2 and self.col + 1 < self.cols:
            self.lines[self.row].cells[self.col + 1] = ConsoleCell('', 0, self.style)

        if self.col + width >= self.cols:
            self.col = self.cols - 1
            self.wrap_pending = True
        else:
            self.col += width

    def erase_display(self, mode):
        if mode == 0:
            self.erasecells(self.row, self.col, self.cols)
            for row in range(self.row + 1, self.rows):
                self.erasecells(row, 0, self.cols)
        elif mode == 1:
            for row in range(0, self.row):
                self.erasecells(row, 0, self.cols)
            self.erasecells(self.row, 0, self.col + 1)
        elif mode in (2, 3):
            for row in range(self.rows):
                self.erasecells(row, 0, self.cols)
            if mode == 3 and self.history is not None:
                self.history.clear()

    def erase_line(self, mode):
        if mode == 0:
            self.erasecells(self.row, self.col, self.cols)
        elif mode == 1:
            self.erasecells(self.row, 0, self.col + 1)
        elif mode == 2:
            self.erasecells(self.row, 0, self.cols)

    def resize(self, rows, cols):
        rows = max(1, int(rows))
        cols = max(2, int(cols))
        if cols != self.cols and self.history is not None:
            source = list(self.history) + self.lines
            cursor_source = len(self.history) + self.row
            logical = []
            group = []
            group_width = 0
            cursor_group = None
            cursor_offset = 0

            for lineindex, line in enumerate(source):
                cells = [cell.copy() for cell in line.cells if cell.width != 0]
                if not line.wrapped:
                    while cells and cells[-1].text == ' ' and cells[-1].style == consolestyledefault():
                        cells.pop()
                if lineindex == cursor_source:
                    cursor_group = len(logical)
                    cursor_offset = group_width + min(self.col, self.cols - 1)
                group.extend(cells)
                group_width += sum(max(1, cell.width) for cell in cells)
                if not line.wrapped:
                    logical.append(group)
                    group = []
                    group_width = 0
            if group or not logical:
                logical.append(group)

            rebuilt = []
            cursor_absolute = None
            for groupindex, cells in enumerate(logical):
                line = ConsoleLine(cols)
                column = 0
                group_column = 0
                first_rebuilt = len(rebuilt)
                rebuilt.append(line)
                for cell in cells:
                    width = max(1, min(2, int(cell.width)))
                    if column + width > cols:
                        rebuilt[-1].wrapped = True
                        line = ConsoleLine(cols)
                        rebuilt.append(line)
                        column = 0
                    if groupindex == cursor_group and cursor_absolute is None and cursor_offset <= group_column:
                        cursor_absolute = len(rebuilt) - 1
                        cursor_column = column
                    line.cells[column] = ConsoleCell(cell.text, width, cell.style)
                    if width == 2 and column + 1 < cols:
                        line.cells[column + 1] = ConsoleCell('', 0, cell.style)
                    column += width
                    group_column += width
                if groupindex == cursor_group and cursor_absolute is None:
                    relative = max(0, cursor_offset - group_column)
                    while relative > 0:
                        available = cols - column
                        if available <= 0:
                            rebuilt[-1].wrapped = True
                            rebuilt.append(ConsoleLine(cols))
                            column = 0
                            available = cols
                        step = min(relative, available)
                        column += step
                        relative -= step
                    cursor_absolute = len(rebuilt) - 1
                    cursor_column = min(cols - 1, column)
                if len(rebuilt) == first_rebuilt:
                    rebuilt.append(ConsoleLine(cols))

            while len(rebuilt) < rows:
                rebuilt.append(ConsoleLine(cols))
            split = max(0, len(rebuilt) - rows)
            self.history = deque((line.copy() for line in rebuilt[:split]), maxlen=CONSOLE_HISTORY_MAX)
            self.lines = rebuilt[split:]
            if cursor_absolute is not None:
                self.row = max(0, min(rows - 1, cursor_absolute - split))
                self.col = max(0, min(cols - 1, cursor_column))
            self.cols = cols

        elif cols != self.cols:
            for line in self.lines:
                if cols > self.cols:
                    line.cells.extend(ConsoleCell() for _ in range(cols - self.cols))
                else:
                    line.cells = line.cells[:cols]
                    if line.cells and line.cells[-1].width == 2:
                        line.cells[-1] = ConsoleCell()
            self.cols = cols
        if rows < len(self.lines):
            remove = len(self.lines) - rows
            for _ in range(remove):
                line = self.lines.pop(0)
                if self.history is not None:
                    self.history.append(line.copy())
            self.row = max(0, self.row - remove)
        elif rows > len(self.lines):
            self.lines.extend(self.blankline() for _ in range(rows - len(self.lines)))
        self.rows = rows
        self.scroll_top = 0
        self.scroll_bottom = rows - 1
        self.row = max(0, min(rows - 1, self.row))
        self.col = max(0, min(cols - 1, self.col))
        self.tabs.update(range(8, cols, 8))
        self.tabs = {value for value in self.tabs if value < cols}
        self.wrap_pending = False


class ConsoleDisplay:

    def __init__(self, rows, cols, writer=None):
        self.primary = ConsoleBuffer(rows, cols, history=True)
        self.alternate = ConsoleBuffer(rows, cols, history=False)
        self.use_alternate = False
        self.writer = writer
        self.decoder = codecs.getincrementaldecoder('utf-8')('replace')
        self.state = 'ground'
        self.sequence = bytearray()
        self.designate = None
        self.osc = bytearray()
        self.dirty = True
        self.generation = 0
        self.title = ''
        self.cursor_visible = True
        self.cursor_blink = True
        self.cursor_style = 1
        self.app_cursor = False
        self.app_keypad = False
        self.bracketed_paste = False
        self.focus_events = False
        self.mouse_mode = 0
        self.mouse_sgr = False
        self.view_offset = 0
        self.last_printed = ' '
        self.text_blink = False

    @property
    def buffer(self):
        return self.alternate if self.use_alternate else self.primary

    @property
    def rows(self):
        return self.buffer.rows

    @property
    def cols(self):
        return self.buffer.cols

    def changed(self):
        self.dirty = True
        self.generation += 1

    def writeback(self, data):
        if self.writer and data:
            try:
                self.writer(data)
            except Exception:
                pass

    def flushdecoder(self):
        try:
            text = self.decoder.decode(b'', final=True)
        except Exception:
            text = ''
        self.decoder = codecs.getincrementaldecoder('utf-8')('replace')
        for ch in text:
            self.printchar(ch)

    def printchar(self, ch):
        mapping = self.buffer.g1 if self.buffer.charset else self.buffer.g0
        if mapping == '0':
            ch = {
                '`': '◆', 'a': '▒', 'f': '°', 'g': '±', 'j': '┘',
                'k': '┐', 'l': '┌', 'm': '└', 'n': '┼', 'o': '⎺',
                'p': '⎻', 'q': '─', 'r': '⎼', 's': '⎽', 't': '├',
                'u': '┤', 'v': '┴', 'w': '┬', 'x': '│', 'y': '≤',
                'z': '≥', '{': 'π', '|': '≠', '}': '£', '~': '·',
            }.get(ch, ch)
        self.buffer.put(ch)
        self.last_printed = ch
        self.changed()

    def feed(self, data):
        history_before = len(self.primary.history)
        for byte in bytes(data):
            self.feedbyte(byte)
        if self.view_offset > 0 and not self.use_alternate:
            added = max(0, len(self.primary.history) - history_before)
            self.view_offset = min(len(self.primary.history), self.view_offset + added)

    def feedbyte(self, byte):
        if self.state == 'ground':
            if byte == 0x1b:
                self.flushdecoder()
                self.state = 'escape'
                return
            if byte < 0x20 or byte == 0x7f:
                self.flushdecoder()
                self.control(byte)
                return
            try:
                text = self.decoder.decode(bytes((byte,)), final=False)
            except Exception:
                text = '�'
                self.decoder = codecs.getincrementaldecoder('utf-8')('replace')
            for ch in text:
                self.printchar(ch)
            return

        if self.state == 'escape':
            self.escape(byte)
            return

        if self.state == 'csi':
            if 0x40 <= byte <= 0x7e:
                sequence = bytes(self.sequence)
                self.sequence.clear()
                self.state = 'ground'
                self.csi(sequence, chr(byte))
            elif len(self.sequence) < CONSOLE_SEQUENCE_LIMIT:
                self.sequence.append(byte)
            else:
                self.sequence.clear()
                self.state = 'ground'
            return

        if self.state == 'osc':
            if byte == 0x07:
                self.finishosc()
            elif byte == 0x1b:
                self.state = 'osc_escape'
            elif len(self.osc) < CONSOLE_SEQUENCE_LIMIT:
                self.osc.append(byte)
            return

        if self.state == 'osc_escape':
            if byte == ord('\\'):
                self.finishosc()
            else:
                if len(self.osc) + 2 < CONSOLE_SEQUENCE_LIMIT:
                    self.osc.extend((0x1b, byte))
                self.state = 'osc'
            return

        if self.state == 'string':
            if byte == 0x1b:
                self.state = 'string_escape'
            return

        if self.state == 'string_escape':
            self.state = 'ground' if byte == ord('\\') else 'string'
            return

        if self.state == 'designate':
            value = chr(byte)
            if self.designate in ('(', '*'):
                self.buffer.g0 = value
            else:
                self.buffer.g1 = value
            self.designate = None
            self.state = 'ground'

    def control(self, byte):
        if byte == 0x07:
            return
        if byte == 0x08:
            self.buffer.backspace()
        elif byte == 0x09:
            self.buffer.tab()
        elif byte in (0x0a, 0x0b, 0x0c):
            self.buffer.linefeed()
        elif byte == 0x0d:
            self.buffer.carriage()
        elif byte == 0x0e:
            self.buffer.charset = 1
        elif byte == 0x0f:
            self.buffer.charset = 0
        else:
            return
        self.changed()

    def escape(self, byte):
        char = chr(byte)
        self.state = 'ground'
        if char == '[':
            self.sequence.clear()
            self.state = 'csi'
        elif char == ']':
            self.osc.clear()
            self.state = 'osc'
        elif char in ('P', '^', '_'):
            self.state = 'string'
        elif char in ('(', ')', '*', '+'):
            self.designate = char
            self.state = 'designate'
        elif char == '7':
            self.buffer.save()
        elif char == '8':
            self.buffer.restore()
            self.changed()
        elif char == 'D':
            self.buffer.index()
            self.changed()
        elif char == 'M':
            self.buffer.reverseindex()
            self.changed()
        elif char == 'E':
            self.buffer.carriage()
            self.buffer.index()
            self.changed()
        elif char == 'H':
            self.buffer.tabs.add(self.buffer.col)
        elif char == 'c':
            self.reset()
        elif char == '=':
            self.app_keypad = True
        elif char == '>':
            self.app_keypad = False

    def reset(self):
        self.primary.reset()
        self.alternate.reset()
        self.use_alternate = False
        self.cursor_visible = True
        self.cursor_blink = True
        self.cursor_style = 1
        self.app_cursor = False
        self.app_keypad = False
        self.bracketed_paste = False
        self.focus_events = False
        self.mouse_mode = 0
        self.mouse_sgr = False
        self.view_offset = 0
        self.text_blink = False
        self.changed()

    def finishosc(self):
        try:
            text = self.osc.decode('utf-8', 'replace')
            command, value = text.split(';', 1)
            if command in ('0', '1', '2'):
                self.title = value[:256]
            elif command == '8':
                parts = value.split(';', 1)
                link = parts[1] if len(parts) > 1 else ''
                self.buffer.style = consolestylewith(self.buffer.style, link=(link or None))
        except Exception:
            pass
        self.osc.clear()
        self.state = 'ground'

    def params(self, raw):
        text = raw.decode('ascii', 'ignore')
        private = ''
        while text and text[0] in '?><!':
            private += text[0]
            text = text[1:]
        intermediate = ''.join(ch for ch in text if ' ' <= ch <= '/')
        if intermediate:
            for ch in intermediate:
                text = text.replace(ch, '')
        values = []
        for item in text.replace(':', ';').split(';'):
            if item == '':
                values.append(None)
            else:
                try:
                    values.append(int(item))
                except Exception:
                    values.append(None)
        return private, intermediate, values or [None]

    @staticmethod
    def param(values, index, default=1, zero_default=True):
        if index >= len(values) or values[index] is None:
            return default
        value = int(values[index])
        return default if zero_default and value == 0 else value

    def csi(self, raw, final):
        private, intermediate, values = self.params(raw)
        buf = self.buffer
        count = self.param(values, 0)
        if final == 'A':
            buf.setpos(row=buf.row - count - (buf.scroll_top if buf.origin else 0))
        elif final in ('B', 'e'):
            buf.setpos(row=buf.row + count - (buf.scroll_top if buf.origin else 0))
        elif final in ('C', 'a'):
            buf.setpos(col=buf.col + count)
        elif final == 'D':
            buf.setpos(col=buf.col - count)
        elif final == 'E':
            buf.setpos(row=buf.row + count - (buf.scroll_top if buf.origin else 0), col=0)
        elif final == 'F':
            buf.setpos(row=buf.row - count - (buf.scroll_top if buf.origin else 0), col=0)
        elif final in ('G', '`'):
            buf.setpos(col=self.param(values, 0) - 1)
        elif final in ('H', 'f'):
            buf.setpos(row=self.param(values, 0) - 1, col=self.param(values, 1) - 1)
        elif final == 'd':
            buf.setpos(row=self.param(values, 0) - 1)
        elif final == 'J':
            buf.erase_display(self.param(values, 0, 0, False))
        elif final == 'K':
            buf.erase_line(self.param(values, 0, 0, False))
        elif final == 'X':
            buf.erasecells(buf.row, buf.col, buf.col + count)
        elif final == '@':
            cells = buf.lines[buf.row].cells
            for _ in range(min(count, buf.cols - buf.col)):
                cells.insert(buf.col, ConsoleCell(style=buf.style))
                cells.pop()
        elif final == 'P':
            cells = buf.lines[buf.row].cells
            for _ in range(min(count, buf.cols - buf.col)):
                cells.pop(buf.col)
                cells.append(ConsoleCell(style=buf.style))
        elif final == 'L' and buf.scroll_top <= buf.row <= buf.scroll_bottom:
            buf.scrolldown(count, buf.row, buf.scroll_bottom)
        elif final == 'M' and buf.scroll_top <= buf.row <= buf.scroll_bottom:
            buf.scrollup(count, buf.row, buf.scroll_bottom)
        elif final == 'S':
            buf.scrollup(count)
        elif final == 'T':
            buf.scrolldown(count)
        elif final == 'I':
            for _ in range(count):
                buf.tab()
        elif final == 'Z':
            for _ in range(count):
                buf.tab(backwards=True)
        elif final == 'b':
            for _ in range(min(count, 4096)):
                buf.put(self.last_printed)
        elif final == 'r':
            top = self.param(values, 0) - 1
            bottom = self.param(values, 1, buf.rows) - 1
            if 0 <= top < bottom < buf.rows:
                buf.scroll_top = top
                buf.scroll_bottom = bottom
                buf.setpos(row=0, col=0)
        elif final == 's':
            buf.save()
        elif final == 'u':
            buf.restore()
        elif final == 'g':
            mode = self.param(values, 0, 0, False)
            if mode == 0:
                buf.tabs.discard(buf.col)
            elif mode == 3:
                buf.tabs.clear()
        elif final == 'm':
            self.sgr(values)
        elif final in ('h', 'l'):
            self.setmodes(private, values, final == 'h')
        elif final == 'n':
            mode = self.param(values, 0, 0, False)
            if mode == 5:
                self.writeback(b'\x1b[0n')
            elif mode == 6:
                self.writeback(f'\x1b[{buf.row + 1};{buf.col + 1}R'.encode())
        elif final == 'c':
            self.writeback(b'\x1b[?1;2c')
        elif final == 'q' and intermediate == ' ':
            self.cursor_style = max(0, min(6, self.param(values, 0, 0, False)))
            self.cursor_blink = self.cursor_style in (0, 1, 3, 5)
        else:
            return
        self.changed()

    def setmodes(self, private, values, enabled):
        buf = self.buffer
        for value in values:
            value = 0 if value is None else int(value)
            if private == '?':
                if value == 1:
                    self.app_cursor = enabled
                elif value == 6:
                    buf.origin = enabled
                    buf.setpos(row=0, col=0)
                elif value == 7:
                    buf.autowrap = enabled
                elif value == 12:
                    self.cursor_blink = enabled
                elif value == 25:
                    self.cursor_visible = enabled
                elif value in (47, 1047, 1049):
                    if enabled and value == 1049:
                        self.primary.save()
                    self.use_alternate = enabled
                    if enabled:
                        self.alternate.reset()
                    elif value == 1049:
                        self.primary.restore()
                    self.view_offset = 0
                    buf = self.buffer
                elif value == 1048:
                    buf.save() if enabled else buf.restore()
                elif value in (1000, 1002, 1003):
                    self.mouse_mode = value if enabled else 0
                elif value == 1004:
                    self.focus_events = enabled
                elif value == 1006:
                    self.mouse_sgr = enabled
                elif value == 2004:
                    self.bracketed_paste = enabled
            else:
                if value == 4:
                    buf.insert = enabled
                elif value == 20:
                    buf.newline = enabled

    def sgr(self, values):
        buf = self.buffer
        if not values:
            values = [0]
        index = 0
        while index < len(values):
            code = 0 if values[index] is None else int(values[index])
            if code == 0:
                buf.style = consolestyledefault()
            elif code == 1:
                buf.style = consolestylewith(buf.style, bold=True)
            elif code == 2:
                buf.style = consolestylewith(buf.style, faint=True)
            elif code == 3:
                buf.style = consolestylewith(buf.style, italic=True)
            elif code in (4, 21):
                buf.style = consolestylewith(buf.style, underline=(2 if code == 21 else 1))
            elif code in (5, 6):
                buf.style = consolestylewith(buf.style, blink=True)
                self.text_blink = True
            elif code == 7:
                buf.style = consolestylewith(buf.style, inverse=True)
            elif code == 8:
                buf.style = consolestylewith(buf.style, conceal=True)
            elif code == 9:
                buf.style = consolestylewith(buf.style, strike=True)
            elif code == 22:
                buf.style = consolestylewith(buf.style, bold=False, faint=False)
            elif code == 23:
                buf.style = consolestylewith(buf.style, italic=False)
            elif code == 24:
                buf.style = consolestylewith(buf.style, underline=0)
            elif code == 25:
                buf.style = consolestylewith(buf.style, blink=False)
            elif code == 27:
                buf.style = consolestylewith(buf.style, inverse=False)
            elif code == 28:
                buf.style = consolestylewith(buf.style, conceal=False)
            elif code == 29:
                buf.style = consolestylewith(buf.style, strike=False)
            elif 30 <= code <= 37:
                buf.style = consolestylewith(buf.style, fg=CONSOLE_PALETTE[code - 30])
            elif code == 39:
                buf.style = consolestylewith(buf.style, fg=None)
            elif 40 <= code <= 47:
                buf.style = consolestylewith(buf.style, bg=CONSOLE_PALETTE[code - 40])
            elif code == 49:
                buf.style = consolestylewith(buf.style, bg=None)
            elif 90 <= code <= 97:
                buf.style = consolestylewith(buf.style, fg=CONSOLE_PALETTE[8 + code - 90])
            elif 100 <= code <= 107:
                buf.style = consolestylewith(buf.style, bg=CONSOLE_PALETTE[8 + code - 100])
            elif code in (38, 48):
                colour = None
                if index + 2 < len(values) and values[index + 1] == 5:
                    colour = consoleindexedcolour(0 if values[index + 2] is None else values[index + 2])
                    index += 2
                elif index + 4 < len(values) and values[index + 1] == 2:
                    rgb = [max(0, min(255, int(values[index + offset] or 0))) for offset in (2, 3, 4)]
                    colour = (rgb[0] << 16) | (rgb[1] << 8) | rgb[2]
                    index += 4
                if colour is not None:
                    buf.style = consolestylewith(buf.style, **({'fg': colour} if code == 38 else {'bg': colour}))
            index += 1

    def resize(self, rows, cols):
        self.primary.resize(rows, cols)
        self.alternate.resize(rows, cols)
        self.view_offset = min(self.view_offset, max(0, len(self.primary.history)))
        self.changed()

    def all_lines(self):
        if self.use_alternate:
            return list(self.alternate.lines)
        return list(self.primary.history) + list(self.primary.lines)

    def visible(self):
        lines = self.all_lines()
        rows = self.rows
        maximum = max(0, len(lines) - rows)
        self.view_offset = max(0, min(maximum, self.view_offset))
        start = max(0, len(lines) - rows - self.view_offset)
        result = lines[start:start + rows]
        while len(result) < rows:
            result.insert(0, ConsoleLine(self.cols))
            start -= 1
        return start, result

    def selection_text(self, normal):
        if normal is None:
            return ''
        lines = self.all_lines()
        (sl, sc), (el, ec) = normal
        sl = max(0, min(len(lines) - 1, int(sl))) if lines else 0
        el = max(0, min(len(lines) - 1, int(el))) if lines else 0
        if not lines or el < sl:
            return ''
        parts = []
        for index in range(sl, el + 1):
            start = sc if index == sl else 0
            end = ec if index == el else len(lines[index].cells)
            start = max(0, min(len(lines[index].cells), int(start)))
            end = max(start, min(len(lines[index].cells), int(end)))
            part = ''.join(
                cell.text for cell in lines[index].cells[start:end]
                if cell.width != 0
            ).rstrip(' ')
            parts.append(part)
        output = ''
        for offset, part in enumerate(parts):
            output += part
            lineindex = sl + offset
            if offset < len(parts) - 1 and not lines[lineindex].wrapped:
                output += '\n'
        return output

    def transcript(self):
        if self.use_alternate:
            lines = list(self.alternate.lines)
        else:
            lines = list(self.primary.history) + list(self.primary.lines)
        result = [line.text() for line in lines]
        while result and not result[0]:
            result.pop(0)
        while result and not result[-1]:
            result.pop()
        return result


def consoleindexedcolour(index):
    index = max(0, min(255, int(index)))
    if index < 16:
        return CONSOLE_PALETTE[index]
    if index < 232:
        value = index - 16
        red = value // 36
        green = (value % 36) // 6
        blue = value % 6
        levels = (0, 95, 135, 175, 215, 255)
        return (levels[red] << 16) | (levels[green] << 8) | levels[blue]
    grey = 8 + ((index - 232) * 10)
    return (grey << 16) | (grey << 8) | grey


def consoleactive():
    return isinstance(ACTIVE_CONSOLE, dict)


def consolegeometry():
    width = max(1, int(getattr(gfx, '_xres', BASEWINDOWW)))
    height = max(1, int(getattr(gfx, '_yres', BASEWINDOWH)))
    top = int(TOPBLANKLINES * LINEHEIGHT + ((1 + SPACERLINES) * LINEHEIGHT))
    usable_width = max(1, width - (LEFTPAD * 2))
    usable_height = max(1, height - top)
    cols = max(2, usable_width // max(1, SPACEW))
    rows = max(1, usable_height // max(1, LINEHEIGHT))
    return {
        'x': LEFTPAD, 'y': top, 'width': cols * max(1, SPACEW),
        'height': rows * max(1, LINEHEIGHT), 'rows': rows, 'cols': cols,
        'screen_width': width, 'screen_height': height,
    }


def consolecapabilityname():
    candidates = []
    configured = str(os.environ.get('T1OS_CONSOLE_CAPABILITY', '')).strip()
    if configured:
        candidates.append(configured)
    candidates.extend(('xterm-256color', 'linux'))
    try:
        import curses
        for candidate in candidates:
            try:
                curses.setupterm(term=candidate)
                return candidate
            except Exception:
                continue
    except Exception:
        pass
    return 'linux'


def consoleopenpair():
    if fcntl is None or termios is None or not hasattr(os, 'fork'):
        raise OSError('interactive console support is unavailable on this platform')
    choices = (
        ('/the one/drivers/nodes/pts/ptmx', '/the one/drivers/nodes/pts'),
    )
    last_error = None
    access_error = None
    for masterpath, slaveroot in choices:
        try:
            flags = os.O_RDWR | os.O_NOCTTY
            if hasattr(os, 'O_CLOEXEC'):
                flags |= os.O_CLOEXEC
            master = os.open(masterpath, flags)
            try:
                unlock = struct.pack('i', 0)
                fcntl.ioctl(master, 0x40045431, unlock)
                number = struct.unpack('I', fcntl.ioctl(master, 0x80045430, struct.pack('I', 0)))[0]
                return master, f'{slaveroot}/{number}'
            except Exception:
                os.close(master)
                raise
        except OSError as error:
            last_error = error
            if getattr(error, 'errno', None) not in (None, 2):
                access_error = error
    if access_error is not None:
        raise access_error
    if last_error is not None:
        raise last_error
    raise FileNotFoundError('console device multiplexer not found')


def consolesetsize(fd, rows, cols):
    if fcntl is None or termios is None:
        return False
    try:
        fcntl.ioctl(
            int(fd), termios.TIOCSWINSZ,
            struct.pack('HHHH', max(1, int(rows)), max(2, int(cols)), 0, 0),
        )
        return True
    except Exception:
        return False


def consolechild(prog, args, slavepath, rows, cols, environment):
    try:
        os.setsid()
        flags = os.O_RDWR
        if hasattr(os, 'O_CLOEXEC'):
            flags |= os.O_CLOEXEC
        slave = os.open(slavepath, flags)
        try:
            fcntl.ioctl(slave, getattr(termios, 'TIOCSCTTY', 0x540E), 0)
        except Exception:
            pass
        consolesetsize(slave, rows, cols)
        for target in (0, 1, 2):
            os.dup2(slave, target)
        if slave > 2:
            os.close(slave)
        try:
            limit = int(os.sysconf('SC_OPEN_MAX'))
        except Exception:
            limit = 1024
        os.closerange(3, max(4, limit))
        if str(prog).endswith('.py'):
            # Resolve the running executable before a confined child exec so
            # arbitrary Python programs use the immutable canonical system
            # interpreter accepted by the kernel policy.
            command = [os.path.realpath(sys.executable), '-u', str(prog)] + [str(value) for value in (args or [])]
        else:
            command = [str(prog)] + [str(value) for value in (args or [])]
        os.execvpe(command[0], command, environment)
    except BaseException as error:
        try:
            os.write(2, f'could not start software: {error}\r\n'.encode('utf-8', 'replace'))
        except Exception:
            pass
    os._exit(126)


def startconsole(prog, args, name, logpath, user, cmdline):
    global ACTIVE_CONSOLE, DIRTY_SCROLL, DIRTY_PROMPT
    if consoleactive():
        raise RuntimeError('interactive software is already running')
    geometry = consolegeometry()
    master, slavepath = consoleopenpair()
    consolesetsize(master, geometry['rows'], geometry['cols'])
    environment = os.environ.copy()
    environment.update({
        'TERM': consolecapabilityname(),
        'COLORTERM': 'truecolor',
        'COLUMNS': str(geometry['cols']),
        'LINES': str(geometry['rows']),
        'T1OS_CONSOLE': '1',
    })
    try:
        pid = os.fork()
    except Exception:
        os.close(master)
        raise
    if pid == 0:
        try:
            os.close(master)
        except Exception:
            pass
        consolechild(prog, args, slavepath, geometry['rows'], geometry['cols'], environment)

    os.set_blocking(master, False)
    display = ConsoleDisplay(geometry['rows'], geometry['cols'])
    session = {
        'pid': int(pid), 'fd': int(master), 'display': display,
        'prog': str(prog), 'args': [str(value) for value in (args or [])],
        'name': str(name), 'log': str(logpath), 'user': str(user),
        'cmdline': str(cmdline), 'job': None, 'status': None,
        'eof': False, 'stopped': False, 'started': time.time(),
        'outbuf': bytearray(),
    }
    display.writer = consolewrite
    ACTIVE_CONSOLE = session
    try:
        SEL.register(master, selectors.EVENT_READ, data={'kind': 'console'})
    except Exception:
        pass
    opsregisterpid(pid, name, prog, logpath, user, 'front')
    session['job'] = jobadd(cmdline, [pid], 'running', 'front', logpath)
    clearselection(None)
    DIRTY_SCROLL = True
    DIRTY_PROMPT = True
    return pid


def consolewrite(data):
    session = ACTIVE_CONSOLE
    if not isinstance(session, dict):
        return False
    if isinstance(data, str):
        data = data.encode('utf-8')
    payload = bytes(data)
    outbuf = session.setdefault('outbuf', bytearray())
    if len(outbuf) + len(payload) > OUTBUFLIMIT:
        return False
    outbuf.extend(payload)
    consoleflushwrite()
    return True


def consoleflushwrite():
    session = ACTIVE_CONSOLE
    if not isinstance(session, dict):
        return False
    outbuf = session.setdefault('outbuf', bytearray())
    while outbuf:
        try:
            written = os.write(session['fd'], outbuf)
            if written <= 0:
                break
            del outbuf[:written]
        except BlockingIOError:
            break
        except OSError:
            return False
    try:
        events = selectors.EVENT_READ | (selectors.EVENT_WRITE if outbuf else 0)
        SEL.modify(session['fd'], events, data={'kind': 'console'})
    except Exception:
        pass
    return not outbuf


def consoleconsume(fd=None):
    global DIRTY_SCROLL, DIRTY_PROMPT
    session = ACTIVE_CONSOLE
    if not isinstance(session, dict):
        return
    if fd is not None and int(fd) != int(session['fd']):
        return
    total = 0
    while total < CONSOLE_READ_LIMIT:
        try:
            data = os.read(session['fd'], min(65536, CONSOLE_READ_LIMIT - total))
            if not data:
                session['eof'] = True
                break
            total += len(data)
            session['display'].feed(data)
        except BlockingIOError:
            break
        except OSError as error:
            if getattr(error, 'errno', None) in (5, 9):
                session['eof'] = True
            break
    if total:
        DIRTY_SCROLL = True
        DIRTY_PROMPT = True
    consoleflushwrite()


def consolepollstate():
    session = ACTIVE_CONSOLE
    if not isinstance(session, dict):
        return
    consoleconsume()
    if session.get('status') is None:
        options = os.WNOHANG
        options |= getattr(os, 'WUNTRACED', 0)
        options |= getattr(os, 'WCONTINUED', 0)
        try:
            pid, status = os.waitpid(session['pid'], options)
        except ChildProcessError:
            pid, status = session['pid'], 0
        except Exception:
            pid, status = 0, 0
        if pid:
            if os.WIFSTOPPED(status):
                session['stopped'] = True
                job = session.get('job')
                if job and job in JOBS:
                    JOBS[job]['state'] = 'stopped'
            elif hasattr(os, 'WIFCONTINUED') and os.WIFCONTINUED(status):
                session['stopped'] = False
                job = session.get('job')
                if job and job in JOBS:
                    JOBS[job]['state'] = 'running'
            else:
                session['status'] = status
    if session.get('status') is not None:
        consoleconsume()
        finishconsole()


def consoleexitcode(status):
    if status is None:
        return None
    if os.WIFEXITED(status):
        return int(os.WEXITSTATUS(status))
    if os.WIFSIGNALED(status):
        return 128 + int(os.WTERMSIG(status))
    return 1


def consoleappendlog(session, lines, exitcode):
    path = str(session.get('log', '') or '')
    if not path:
        return
    try:
        with open(path, 'a', encoding='utf-8', errors='replace') as stream:
            if lines:
                stream.write('\n'.join(lines))
                stream.write('\n')
            stream.write(f'[console exit {exitcode}]\n')
    except Exception:
        pass


def finishconsole():
    global ACTIVE_CONSOLE, DIRTY_SCROLL, DIRTY_PROMPT, CONSOLE_SELECTING, JOBFORE
    session = ACTIVE_CONSOLE
    if not isinstance(session, dict):
        return
    display = session['display']
    try:
        display.flushdecoder()
    except Exception:
        pass
    lines = display.transcript()
    exitcode = consoleexitcode(session.get('status'))
    try:
        SEL.unregister(session['fd'])
    except Exception:
        pass
    try:
        os.close(session['fd'])
    except Exception:
        pass
    job = session.get('job')
    opscompletepid(session['pid'], int(exitcode or 0))
    if job and job in JOBS:
        JOBS[job]['state'] = 'done' if exitcode == 0 else 'failed'
        JOBS[job]['ended'] = float(time.time())
        JOBS[job]['exitcode'] = int(exitcode or 0)
        if JOBFORE == str(job):
            JOBFORE = None
    consoleappendlog(session, lines, exitcode)
    ACTIVE_CONSOLE = None
    CONSOLE_SELECTING = False
    clearselection(None)
    for line in lines:
        guiprint(line)
    if exitcode not in (None, 0):
        guiprint(f'> software exited with code {exitcode}', colour=ERRORCOLOUR)
    guiprint()
    DIRTY_SCROLL = True
    DIRTY_PROMPT = True


def consoleclose():
    session = ACTIVE_CONSOLE
    if not isinstance(session, dict):
        return
    try:
        os.killpg(session['pid'], signal.SIGHUP)
    except Exception:
        pass
    deadline = time.monotonic() + 0.35
    while time.monotonic() < deadline:
        consolepollstate()
        if not consoleactive():
            return
        time.sleep(0.01)
    session = ACTIVE_CONSOLE
    if isinstance(session, dict):
        try:
            os.killpg(session['pid'], signal.SIGKILL)
        except Exception:
            pass
        try:
            _, session['status'] = os.waitpid(session['pid'], 0)
        except Exception:
            session['status'] = 1 << 8
        finishconsole()


def consolefit():
    global DIRTY_SCROLL, DIRTY_PROMPT
    session = ACTIVE_CONSOLE
    if not isinstance(session, dict):
        return False
    geometry = consolegeometry()
    display = session['display']
    if geometry['rows'] == display.rows and geometry['cols'] == display.cols:
        return False
    display.resize(geometry['rows'], geometry['cols'])
    consolesetsize(session['fd'], geometry['rows'], geometry['cols'])
    try:
        os.killpg(session['pid'], signal.SIGWINCH)
    except Exception:
        pass
    DIRTY_SCROLL = True
    DIRTY_PROMPT = True
    return True


def consolecopysel():
    text = selectiontext()
    if not text:
        return False
    try:
        exset(text, source='brick')
        return True
    except Exception:
        return False


def consolepaste():
    session = ACTIVE_CONSOLE
    if not isinstance(session, dict):
        return False
    try:
        ok, state = exget()
    except Exception:
        ok, state = False, {}
    if not ok:
        return False
    value = state.get('data', '')
    if not isinstance(value, str):
        value = str(value)
    value = value.replace('\x00', '').replace('\r\n', '\n').replace('\r', '\n')
    data = value.encode('utf-8')
    if session['display'].bracketed_paste:
        data = b'\x1b[200~' + data + b'\x1b[201~'
    return consolewrite(data)


def consolekeyevent(key, state, mods):
    global CONSOLE_LAST_MODS
    if not consoleactive():
        return False
    key = str(key or '').upper()
    state = str(state or 'down')
    mods = mods if isinstance(mods, dict) else {}
    shift = bool(mods.get('shift', False))
    ctrl = bool(mods.get('ctrl', mods.get('control', False)))
    alt = bool(mods.get('alt', False))
    CONSOLE_LAST_MODS = {'shift': shift, 'ctrl': ctrl, 'alt': alt}
    if state not in ('down', 'repeat'):
        return True
    if state == 'repeat' and key not in {
        'LEFT', 'RIGHT', 'UP', 'DOWN', 'HOME', 'END', 'PGUP', 'PAGEUP',
        'PGDN', 'PAGEDOWN', 'BACKSPACE', 'BKSP', 'DELETE', 'DEL', 'SPACE',
    } and len(key) != 1 and not key.startswith('NUMPAD'):
        return True
    session = ACTIVE_CONSOLE
    display = session['display']

    keypad = {
        'NUMPAD0': ('0', 'p'), 'NUMPAD1': ('1', 'q'), 'NUMPAD2': ('2', 'r'),
        'NUMPAD3': ('3', 's'), 'NUMPAD4': ('4', 't'), 'NUMPAD5': ('5', 'u'),
        'NUMPAD6': ('6', 'v'), 'NUMPAD7': ('7', 'w'), 'NUMPAD8': ('8', 'x'),
        'NUMPAD9': ('9', 'y'), 'NUMPADDOT': ('.', 'n'),
        'NUMPADPLUS': ('+', 'k'), 'NUMPADMINUS': ('-', 'm'),
        'NUMPADMUL': ('*', 'j'), 'NUMPADDIV': ('/', 'o'),
        'NUMPADENTER': ('\r', 'M'), 'NUMPADEQUAL': ('=', 'X'),
        'NUMPADCOMMA': (',', 'l'), 'NUMPADJPCOMMA': (',', 'l'),
        'NUMPADLPAREN': ('(', '('), 'NUMPADRPAREN': (')', ')'),
        'NUMPADPLUSMINUS': ('-', 'm'),
    }
    if ctrl and shift and key == 'C':
        consolecopysel()
        return True
    if ctrl and shift and key == 'V':
        consolepaste()
        return True
    if session.get('stopped') and ctrl and key == 'Q':
        try:
            os.killpg(session['pid'], signal.SIGCONT)
            session['stopped'] = False
        except Exception:
            pass
        return True

    if shift and not ctrl and not alt and key in ('PGUP', 'PAGEUP', 'PGDN', 'PAGEDOWN'):
        amount = max(1, display.rows - 1)
        display.view_offset += amount if key in ('PGUP', 'PAGEUP') else -amount
        display.view_offset = max(0, min(len(display.primary.history), display.view_offset))
        display.changed()
        return True

    if display.view_offset:
        display.view_offset = 0
        display.changed()

    if key in keypad:
        plain, application = keypad[key]
        data = f'\x1bO{application}'.encode() if display.app_keypad else plain.encode()
        if alt and not data.startswith(b'\x1b'):
            data = b'\x1b' + data
        return consolewrite(data)

    if state == 'repeat' and not ctrl and not alt:
        caps = bool(mods.get('caps', False))
        if len(key) == 1 and key.isalpha():
            value = key.upper() if shift != caps else key.lower()
            return consolewrite(value.encode('utf-8'))
        if len(key) == 1:
            value = CONSOLE_SHIFTED.get(key, key) if shift else key
            return consolewrite(value.encode('utf-8'))
        if key == 'SPACE':
            return consolewrite(b' ')

    modifier = 1 + (1 if shift else 0) + (2 if alt else 0) + (4 if ctrl else 0)
    arrows = {'UP': 'A', 'DOWN': 'B', 'RIGHT': 'C', 'LEFT': 'D'}
    if key in arrows:
        if modifier != 1:
            data = f'\x1b[1;{modifier}{arrows[key]}'.encode()
        elif display.app_cursor:
            data = f'\x1bO{arrows[key]}'.encode()
        else:
            data = f'\x1b[{arrows[key]}'.encode()
        return consolewrite(data)

    finalkeys = {
        'HOME': ('H', b'\x1b[H'), 'END': ('F', b'\x1b[F'),
    }
    if key in finalkeys:
        final, plain = finalkeys[key]
        return consolewrite(f'\x1b[1;{modifier}{final}'.encode() if modifier != 1 else plain)

    tildekeys = {
        'INSERT': 2, 'INS': 2, 'DELETE': 3, 'DEL': 3,
        'PGUP': 5, 'PAGEUP': 5, 'PGDN': 6, 'PAGEDOWN': 6,
        'F5': 15, 'F6': 17, 'F7': 18, 'F8': 19, 'F9': 20,
        'F10': 21, 'F11': 23, 'F12': 24, 'F13': 25, 'F14': 26,
        'F15': 28, 'F16': 29, 'F17': 31, 'F18': 32, 'F19': 33,
        'F20': 34, 'F21': 42, 'F22': 43, 'F23': 44, 'F24': 45,
    }
    if key in tildekeys:
        number = tildekeys[key]
        return consolewrite(f'\x1b[{number}{";" + str(modifier) if modifier != 1 else ""}~'.encode())

    ss3keys = {'F1': 'P', 'F2': 'Q', 'F3': 'R', 'F4': 'S'}
    if key in ss3keys:
        final = ss3keys[key]
        return consolewrite(f'\x1b[1;{modifier}{final}'.encode() if modifier != 1 else f'\x1bO{final}'.encode())

    if key in ('ENTER', 'RETURN'):
        data = b'\r'
    elif key in ('BACKSPACE', 'BKSP'):
        data = b'\x7f'
    elif key == 'TAB':
        data = b'\x1b[Z' if shift else b'\t'
    elif key in ('ESC', 'ESCAPE'):
        data = b'\x1b'
    elif ctrl:
        if key in ('SPACE', '2', '@'):
            data = b'\x00'
        elif len(key) == 1 and 'A' <= key <= 'Z':
            data = bytes((ord(key) - 64,))
        elif key in ('[', '3'):
            data = b'\x1b'
        elif key in ('\\', '4'):
            data = b'\x1c'
        elif key in (']', '5'):
            data = b'\x1d'
        elif key in ('^', '6'):
            data = b'\x1e'
        elif key in ('_', '-', '7'):
            data = b'\x1f'
        elif key in ('8', '?'):
            data = b'\x7f'
        else:
            return True
    elif alt and len(key) == 1:
        caps = bool(mods.get('caps', False))
        if key.isalpha():
            value = key.upper() if shift != caps else key.lower()
        else:
            value = CONSOLE_SHIFTED.get(key, key) if shift else key
        data = b'\x1b' + value.encode('utf-8')
    else:
        return True
    if alt and data != b'\x1b' and not data.startswith(b'\x1b'):
        data = b'\x1b' + data
    return consolewrite(data)


def consoletext(text):
    if not consoleactive():
        return False
    if text is None:
        return True
    value = str(text)
    if not value:
        return True
    if ACTIVE_CONSOLE['display'].view_offset:
        ACTIVE_CONSOLE['display'].view_offset = 0
        ACTIVE_CONSOLE['display'].changed()
    return consolewrite(value.encode('utf-8'))


def consolemouseenabled(display, motion=False, drag=False):
    if display.mouse_mode == 1003:
        return True
    if motion and display.mouse_mode == 1002:
        return bool(CONSOLE_BUTTONS)
    if motion:
        return False
    return display.mouse_mode in (1000, 1002, 1003)


def consolecellfromxy(x, y):
    session = ACTIVE_CONSOLE
    if not isinstance(session, dict):
        return None
    geometry = consolegeometry()
    if not (geometry['x'] <= x < geometry['x'] + geometry['width'] and
            geometry['y'] <= y < geometry['y'] + geometry['height']):
        return None
    column = max(0, min(geometry['cols'] - 1, (int(x) - geometry['x']) // max(1, SPACEW)))
    row = max(0, min(geometry['rows'] - 1, (int(y) - geometry['y']) // max(1, LINEHEIGHT)))
    start, _ = session['display'].visible()
    return start + row, column


def consolesendmouse(button, state, x, y, mods=None, motion=False, wheel=False):
    session = ACTIVE_CONSOLE
    if not isinstance(session, dict):
        return False
    display = session['display']
    position = consolecellfromxy(x, y)
    if position is None:
        return False
    _, column = position
    geometry = consolegeometry()
    row = max(0, min(geometry['rows'] - 1, (int(y) - geometry['y']) // max(1, LINEHEIGHT)))
    mods = mods if isinstance(mods, dict) else CONSOLE_LAST_MODS
    code = int(button)
    if bool(mods.get('shift')):
        code |= 4
    if bool(mods.get('alt')):
        code |= 8
    if bool(mods.get('ctrl', mods.get('control', False))):
        code |= 16
    if motion:
        code |= 32
    suffix = 'm' if state == 'up' and not wheel else 'M'
    if display.mouse_sgr:
        return consolewrite(f'\x1b[<{code};{column + 1};{row + 1}{suffix}'.encode())
    legacy = bytes((min(255, 32 + code), min(255, 33 + column), min(255, 33 + row)))
    return consolewrite(b'\x1b[M' + legacy)


def consolepointerbutton(msg):
    global CONSOLE_SELECTING, SELREGION, SELACTIVE, SELANCHOR, SELEND
    global DIRTY_SCROLL, DIRTY_PROMPT
    global LASTCLICKTIME, LASTCLICKX, LASTCLICKY, CLICKCOUNT
    if not consoleactive():
        return False
    button = int(msg.get('button', 0))
    state = str(msg.get('state', ''))
    x = int(msg.get('x', 0))
    y = int(msg.get('y', 0))
    mods = msg.get('mods', {})
    shift = bool(mods.get('shift', CONSOLE_LAST_MODS.get('shift', False)))
    display = ACTIVE_CONSOLE['display']
    if state == 'down':
        CONSOLE_BUTTONS.add(button)
    elif state == 'up':
        CONSOLE_BUTTONS.discard(button)
    if display.mouse_mode and not shift:
        codes = {1: 0, 2: 1, 3: 2}
        code = codes.get(button, 3)
        if state == 'up':
            code = 3
        consolesendmouse(code, state, x, y, mods=mods)
        return True
    if button != 1:
        return True
    position = consolecellfromxy(x, y)
    if position is None:
        return True
    if state == 'down':
        clearselection(None)
        SELREGION = 'console'
        now = time.monotonic()
        dx = x - LASTCLICKX
        dy = y - LASTCLICKY
        close = (dx * dx + dy * dy) <= (DBLCLICKDIST * DBLCLICKDIST)
        CLICKCOUNT = CLICKCOUNT + 1 if close and now - LASTCLICKTIME <= DBLCLICKWINDOW else 1
        LASTCLICKTIME = now
        LASTCLICKX = x
        LASTCLICKY = y
        SELACTIVE = CLICKCOUNT == 1
        CONSOLE_SELECTING = CLICKCOUNT == 1

        if CLICKCOUNT >= 3:
            SELANCHOR = (position[0], 0)
            SELEND = (position[0], ACTIVE_CONSOLE['display'].cols)
        elif CLICKCOUNT == 2:
            lines = ACTIVE_CONSOLE['display'].all_lines()
            lineindex = max(0, min(len(lines) - 1, position[0]))
            cells = lines[lineindex].cells
            column = max(0, min(len(cells) - 1, position[1]))
            while column > 0 and cells[column].width == 0:
                column -= 1
            char = cells[column].text[:1] if cells[column].text else ' '

            def wordclass(value):
                if value.isspace():
                    return 'space'
                if value.isalnum() or value == '_':
                    return 'word'
                return 'punctuation'

            category = wordclass(char)
            first = column
            end = column + max(1, cells[column].width)
            while first > 0:
                previous = first - 1
                while previous > 0 and cells[previous].width == 0:
                    previous -= 1
                value = cells[previous].text[:1] if cells[previous].text else ' '
                if wordclass(value) != category:
                    break
                first = previous
            while end < len(cells):
                value = cells[end].text[:1] if cells[end].text else ' '
                if wordclass(value) != category:
                    break
                end += max(1, cells[end].width)
            SELANCHOR = (lineindex, first)
            SELEND = (lineindex, min(len(cells), end))
        else:
            SELANCHOR = position
            SELEND = position
        normaliseselection()
    elif state == 'up':
        SELACTIVE = False
        CONSOLE_SELECTING = False
        SELEND = position
        normaliseselection()
    DIRTY_SCROLL = True
    DIRTY_PROMPT = True
    return True


def consolepointermotion(msg):
    global SELEND, DIRTY_SCROLL, DIRTY_PROMPT
    if not consoleactive():
        return False
    x = int(msg.get('x', 0))
    y = int(msg.get('y', 0))
    display = ACTIVE_CONSOLE['display']
    mods = msg.get('mods', {})
    shift = bool(mods.get('shift', CONSOLE_LAST_MODS.get('shift', False)))
    if display.mouse_mode and not shift and consolemouseenabled(display, motion=True):
        code = 3
        if CONSOLE_BUTTONS:
            code = {1: 0, 2: 1, 3: 2}.get(next(iter(CONSOLE_BUTTONS)), 3)
        consolesendmouse(code, 'down', x, y, mods=mods, motion=True)
        return True
    if CONSOLE_SELECTING and SELREGION == 'console':
        position = consolecellfromxy(x, y)
        if position is not None:
            SELEND = position
            normaliseselection()
            DIRTY_SCROLL = True
            DIRTY_PROMPT = True
    return True


def consolescroll(msg):
    global DIRTY_SCROLL, DIRTY_PROMPT
    if not consoleactive():
        return False
    dy = int(msg.get('dy', 0))
    if not dy:
        return True
    mods = msg.get('mods', {})
    ctrl = bool(mods.get('ctrl', CONSOLE_LAST_MODS.get('ctrl', False)))
    if ctrl:
        changefontmetrics(1 if dy > 0 else -1)
        return True
    display = ACTIVE_CONSOLE['display']
    shift = bool(mods.get('shift', CONSOLE_LAST_MODS.get('shift', False)))
    x = int(msg.get('x', consolegeometry()['x']))
    y = int(msg.get('y', consolegeometry()['y']))
    if display.mouse_mode and not shift:
        code = 64 if dy > 0 else 65
        for _ in range(max(1, abs(dy))):
            consolesendmouse(code, 'down', x, y, mods=mods, wheel=True)
    elif not display.use_alternate:
        display.view_offset += dy * SCROLLSTEP
        display.view_offset = max(0, min(len(display.primary.history), display.view_offset))
        display.changed()
        DIRTY_SCROLL = True
        DIRTY_PROMPT = True
    return True


def consoleblend(foreground, background, amount=0.55):
    foreground = int(foreground)
    background = int(background)
    result = 0
    for shift in (16, 8, 0):
        first = (foreground >> shift) & 0xff
        second = (background >> shift) & 0xff
        value = int(round((first * amount) + (second * (1.0 - amount))))
        result |= max(0, min(255, value)) << shift
    return result


def consolecellappearance(cell, selected=False):
    style = cell.style if isinstance(cell.style, tuple) and len(cell.style) >= 11 else consolestyledefault()
    fg = TEXTCOLOUR if style[0] is None else int(style[0])
    bg = BACKGROUNDCOLOUR if style[1] is None else int(style[1])
    if style[7]:
        fg, bg = bg, fg
    if style[8]:
        fg = bg
    if style[3]:
        fg = consoleblend(fg, bg)
    if style[10] and not CONSOLE_BLINK_ON:
        fg = bg
    if selected:
        fg, bg = bg, fg
        if fg == bg:
            bg = TEXTCOLOUR
            fg = BACKGROUNDCOLOUR
    return fg, bg, bool(style[2]), bool(style[4]), int(style[5]), bool(style[6])


def consoleisselected(lineindex, column):
    if SELREGION != 'console' or SELNORMAL is None:
        return False
    try:
        start, end = SELNORMAL
        point = (int(lineindex), int(column))
        return start <= point < end
    except Exception:
        return False


def consolerowsforpaint():
    session = ACTIVE_CONSOLE
    if not isinstance(session, dict):
        return 0, []
    return session['display'].visible()


def consoleruns(line, lineindex):
    backgrounds = []
    texts = []
    decorations = []
    bgstart = 0
    bgvalue = None
    runstart = None
    runtext = []
    runstyle = None

    def finishtext():
        nonlocal runstart, runtext, runstyle
        if runstart is not None and runtext:
            texts.append((runstart, ''.join(runtext), runstyle))
        runstart = None
        runtext = []
        runstyle = None

    for column, cell in enumerate(line.cells):
        appearance = consolecellappearance(cell, consoleisselected(lineindex, column))
        fg, bg, bold, italic, underline, strike = appearance
        if bgvalue is None:
            bgstart, bgvalue = column, bg
        elif bg != bgvalue:
            if bgvalue != BACKGROUNDCOLOUR:
                backgrounds.append((bgstart, column, bgvalue))
            bgstart, bgvalue = column, bg

        if underline:
            decorations.append((column, max(1, cell.width), fg, 'underline', underline))
        if strike:
            decorations.append((column, max(1, cell.width), fg, 'strike', 1))

        if cell.width == 0:
            continue
        text = cell.text
        textstyle = (fg, bold, italic)
        complexcell = cell.width != 1 or len(text) != 1
        if not text or text == ' ':
            finishtext()
            continue
        if complexcell:
            finishtext()
            texts.append((column, text, textstyle))
            continue
        if runstart is None:
            runstart, runtext, runstyle = column, [text], textstyle
        elif textstyle == runstyle and column == runstart + len(runtext):
            runtext.append(text)
        else:
            finishtext()
            runstart, runtext, runstyle = column, [text], textstyle

    finishtext()
    if bgvalue is not None and bgvalue != BACKGROUNDCOLOUR:
        backgrounds.append((bgstart, len(line.cells), bgvalue))
    return backgrounds, texts, decorations


def consolecursorposition(start):
    session = ACTIVE_CONSOLE
    if not isinstance(session, dict):
        return None
    display = session['display']
    if display.view_offset or not display.cursor_visible:
        return None
    buffer = display.buffer
    absolute = buffer.row if display.use_alternate else len(display.primary.history) + buffer.row
    visible_row = absolute - start
    if not (0 <= visible_row < buffer.rows):
        return None
    return visible_row, buffer.col


def graphicsbuildconsole(commands, clip):
    geometry = consolegeometry()
    contentclip = graphicsclip(
        [geometry['x'], geometry['y'], geometry['width'], geometry['height']],
        geometry['screen_width'], geometry['screen_height'],
    )
    if contentclip is None:
        return
    backgrounds_out = []
    texts_out = []
    overlays_out = []
    start, lines = consolerowsforpaint()
    for row, line in enumerate(lines):
        y = geometry['y'] + (row * LINEHEIGHT)
        backgrounds, texts, decorations = consoleruns(line, start + row)
        for first, end, colour in backgrounds:
            graphicsrect(
                backgrounds_out, geometry['x'] + first * SPACEW, y,
                (end - first) * SPACEW, LINEHEIGHT, colour, contentclip,
            )
        for column, text, style in texts:
            fg, bold, _italic = style
            graphicstext(
                texts_out, geometry['x'] + column * SPACEW, y, text,
                fg, graphicsfont(bold=bold), contentclip,
            )
        for column, width, colour, kind, strength in decorations:
            if kind == 'strike':
                liney = y + max(1, LINEHEIGHT // 2)
            else:
                liney = y + LINEHEIGHT - max(2, LINEHEIGHT // 7)
            graphicsrect(
                overlays_out, geometry['x'] + column * SPACEW, liney,
                max(1, width * SPACEW), max(1, min(2, int(strength))),
                colour, contentclip,
            )

    session = ACTIVE_CONSOLE
    display = session['display'] if isinstance(session, dict) else None
    position = consolecursorposition(start)
    if position is not None and GRAPHICSCURSORON and display is not None:
        row, column = position
        x = geometry['x'] + column * SPACEW
        y = geometry['y'] + row * LINEHEIGHT
        style = display.cursor_style
        if style in (3, 4):
            graphicsrect(overlays_out, x, y + LINEHEIGHT - 2, SPACEW, 2, CURSORCOLOUR, contentclip)
        elif style in (5, 6):
            graphicsrect(overlays_out, x, y, max(1, SPACEW // 5), LINEHEIGHT, CURSORCOLOUR, contentclip)
        else:
            graphicsrect(overlays_out, x, y + CURSOR_Y_OFFSET, SPACEW, CURSORH, CURSORCOLOUR, contentclip)

    if isinstance(session, dict) and session.get('stopped'):
        label = 'paused — ctrl+q continues'
        labelx = max(geometry['x'], geometry['x'] + geometry['width'] - len(label) * SPACEW)
        graphicstext(texts_out, labelx, geometry['y'], label, SUGGESTCOLOUR, graphicsfont(), contentclip)

    commands.append({
        'id': 'brick-console-grid',
        'kind': 'console_grid',
        'rect': list(contentclip),
        'clip': list(contentclip),
        'backgrounds': backgrounds_out,
        'texts': texts_out,
        'overlays': overlays_out,
    })


def drawconsole(cursor_on):
    geometry = consolegeometry()
    fillrectfast(0, geometry['y'], geometry['screen_width'], geometry['screen_height'] - geometry['y'], BACKGROUNDCOLOUR)
    start, lines = consolerowsforpaint()
    for row, line in enumerate(lines):
        y = geometry['y'] + row * LINEHEIGHT
        backgrounds, texts, decorations = consoleruns(line, start + row)
        for first, end, colour in backgrounds:
            fillrectfast(geometry['x'] + first * SPACEW, y, (end - first) * SPACEW, LINEHEIGHT, colour)
        for column, text, style in texts:
            fg, bold, italic = style
            drawtextline(geometry['x'] + column * SPACEW, y, text, colour=fg, bold=bold, italic=italic)
        for column, width, colour, kind, strength in decorations:
            liney = y + (LINEHEIGHT // 2 if kind == 'strike' else LINEHEIGHT - max(2, LINEHEIGHT // 7))
            fillrectfast(
                geometry['x'] + column * SPACEW, liney,
                max(1, width * SPACEW), max(1, min(2, int(strength))), colour,
            )
    session = ACTIVE_CONSOLE
    display = session['display'] if isinstance(session, dict) else None
    position = consolecursorposition(start)
    if position is not None and cursor_on and display is not None:
        row, column = position
        x = geometry['x'] + column * SPACEW
        y = geometry['y'] + row * LINEHEIGHT
        style = display.cursor_style
        if style in (3, 4):
            fillrectfast(x, y + LINEHEIGHT - 2, SPACEW, 2, CURSORCOLOUR)
        elif style in (5, 6):
            fillrectfast(x, y, max(1, SPACEW // 5), LINEHEIGHT, CURSORCOLOUR)
        else:
            drawcursor(x, y)
    if isinstance(session, dict) and session.get('stopped'):
        label = 'paused — ctrl+q continues'
        labelx = max(geometry['x'], geometry['x'] + geometry['width'] - len(label) * SPACEW)
        drawtextline(labelx, geometry['y'], label, colour=SUGGESTCOLOUR)

# misc functions
def measurements():

    global LINEHEIGHT, LEFTPAD, CURSORW, CURSORH, CURSOR_Y_OFFSET, CURSORGAP
    global SPACEW, PROMPTW

    try:

        # Preserve fixed leading so zoom changes both metrics by the same step.
        minlh = FONTSIZE + 3
        if LINEHEIGHT < minlh:
            LINEHEIGHT = minlh

        # left margin derived from font size
        LEFTPAD = max(8, int(FONTSIZE * 0.6))

        # measure one space (cell width) and the prompt width, in pixels
        try:
            SPACEW = max(1, int(measuretext(' ', FONTSIZE)))
            PROMPTW = max(0, int(measuretext(PROMPT, FONTSIZE)))
        except Exception:
            # conservative fallbacks (monospace assumptions)
            SPACEW = max(1, int(FONTSIZE * 0.56))
            PROMPTW = len(PROMPT) * SPACEW

        # cursor geometry: wide block exactly one space wide
        CURSORW = SPACEW
        CURSORH = max(8, int(LINEHEIGHT * 0.90))
        CURSOR_Y_OFFSET = max(0, (LINEHEIGHT - CURSORH) // 2)

        # no extra horizontal gap; the block cursor occupies the next cell
        CURSORGAP = 0

    except Exception as e:

        guiprint(f'> error recalculating measurements {e}', colour=ERRORCOLOUR)


def applyuiscale(w, h):

    global UISCALE, FONTSIZE, LINEHEIGHT, TEXTSCALE, SCROLLBAR_WIDTH, SCROLLBAR_MARGIN, SCROLLBAR_MIN_THUMB, HSCROLLBAR_HEIGHT, DBLCLICKDIST

    if w <= 0 or h <= 0:
        return

    UISCALE = displayuiscale(
        w, h, uiscalefactor(), BASESCREENW, BASESCREENH)

    if UISCALE < 0.50:
        UISCALE = 0.50

    if UISCALE > 3.00:
        UISCALE = 3.00

    FONTSIZE = max(10, int(BASEFONTSIZE * UISCALE))

    LINEHEIGHT = max(10, int(BASELINEHEIGHT * UISCALE))

    if FONTOVERRIDE is not None and LINEHEIGHTOVERRIDE is not None:
        FONTSIZE = int(FONTOVERRIDE)
        LINEHEIGHT = int(LINEHEIGHTOVERRIDE)

    TEXTSCALE = max(1, int(round(BASETEXTSCALE * UISCALE)))

    SCROLLBAR_WIDTH = max(6, int(BASESCROLLBAR_WIDTH * UISCALE))

    SCROLLBAR_MARGIN = max(1, int(BASESCROLLBAR_MARGIN * UISCALE))

    SCROLLBAR_MIN_THUMB = max(10, int(BASESCROLLBAR_MIN_THUMB * UISCALE))

    HSCROLLBAR_HEIGHT = SCROLLBAR_WIDTH

    DBLCLICKDIST = max(3, int(BASEDBLCLICKDIST * UISCALE))


def loadbricksettings():

    global FONTOVERRIDE, LINEHEIGHTOVERRIDE

    try:
        with open(BRICKSETTINGSFILE, 'r', encoding='utf-8') as stream:
            settings = json.load(stream)

        fontsize = int(settings.get('font_size'))
        lineheight = int(settings.get('line_height'))

        if MINFONTSIZE <= fontsize <= MAXFONTSIZE and lineheight >= fontsize:
            FONTOVERRIDE = fontsize
            LINEHEIGHTOVERRIDE = lineheight

    except Exception:
        FONTOVERRIDE = None
        LINEHEIGHTOVERRIDE = None


def savebricksettings():

    directory = os.path.dirname(BRICKSETTINGSFILE)
    temporary = f'{BRICKSETTINGSFILE}.{os.getpid()}.tmp'

    try:
        os.makedirs(directory, exist_ok=True)

        try:
            with open(BRICKSETTINGSFILE, 'r', encoding='utf-8') as stream:
                settings = json.load(stream)
        except Exception:
            settings = {}

        if not isinstance(settings, dict):
            settings = {}

        settings['font_size'] = int(FONTOVERRIDE)
        settings['line_height'] = int(LINEHEIGHTOVERRIDE)

        with open(temporary, 'w', encoding='utf-8') as stream:
            json.dump(settings, stream, sort_keys=True, separators=(',', ':'))
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())

        os.replace(temporary, BRICKSETTINGSFILE)
        return True

    except Exception as e:
        print(formatlog('brick', f'font settings save error {e}'))
        return False

    finally:
        try:
            if os.path.exists(temporary):
                os.unlink(temporary)
        except Exception:
            pass


def changefontmetrics(direction):

    global FONTSIZE, LINEHEIGHT, FONTOVERRIDE, LINEHEIGHTOVERRIDE
    global WRAPCACHEKEY, WRAPCACHEROWS, CONTENTLAYOUTKEY, CONTENTLAYOUTCACHE
    global DIRTY_SCROLL, DIRTY_PROMPT

    delta = FONTSTEP if int(direction) > 0 else -FONTSTEP
    newfontsize = max(MINFONTSIZE, min(MAXFONTSIZE, FONTSIZE + delta))
    actualdelta = newfontsize - FONTSIZE

    if not actualdelta:
        return False

    FONTSIZE = newfontsize
    LINEHEIGHT = max(FONTSIZE + 3, LINEHEIGHT + actualdelta)
    FONTOVERRIDE = FONTSIZE
    LINEHEIGHTOVERRIDE = LINEHEIGHT

    if USE_TTF and CURRENTTTFFONT:
        initttffont(CURRENTTTFFONT, FONTSIZE)

    measurements()
    consolefit()
    WRAPCACHEKEY = None
    WRAPCACHEROWS = []
    CONTENTLAYOUTKEY = None
    CONTENTLAYOUTCACHE = None
    DIRTY_SCROLL = True
    DIRTY_PROMPT = True
    savebricksettings()
    return True


def enterinputmodal():

    global MODAL

    try:

        # raise modal depth
        MODAL += 1

    except Exception as e:

        # modal enter error
        guiprint(f'> error entering modal {e}', colour=ERRORCOLOUR)


def exitinputmodal():

    global MODAL

    try:

        # lower modal depth
        if MODAL > 0:
            MODAL -= 1

    except Exception as e:

        # modal exit error
        guiprint(f'> error leaving modal {e}', colour=ERRORCOLOUR)


def resetshell():

    global SCROLLOFF, INPUTBUF, CURSORPOS, HISTPOS, LASTTABBUF, LASTTABCANDS, PREV_SCROLL_LEN, PREV_SCROLLOFF, \
           PREV_INPUTBUF, PREV_CURSORPOS, PREV_ROWS, PREV_CURSOR_ON, PREV_CWD, DIRTY_SCROLL, DIRTY_PROMPT, \
           PENDINGSCROLL, LASTSMOOTHSCROLL

    try:

        # clear framebuffer so no editor pixels remain
        clear(BACKGROUNDCOLOUR)

        SCROLL.clear()

        STYLES.clear()

        # reset paging and prompt state
        SCROLLOFF = 0
        PENDINGSCROLL = 0
        LASTSMOOTHSCROLL = 0.0

        INPUTBUF = ''

        CURSORPOS = 0

        HISTPOS = None

        LASTTABBUF = ''

        LASTTABCANDS = []

        # reload history from disk (fresh session feel)
        inithistory()

        PREV_SCROLL_LEN = -1

        PREV_SCROLLOFF = -1

        PREV_INPUTBUF = None

        PREV_CURSORPOS = -1

        PREV_ROWS = -1

        PREV_CURSOR_ON = False

        # re-measure layout and redraw header
        measurements()

        PREV_CWD = None

        drawheader()

        # draw an empty content + prompt frame immediately
        drawcontent(cursor_on=False)

        presentbrick()

        DIRTY_SCROLL = True

        DIRTY_PROMPT = True

    except Exception as e:

        # reset shell error
        guiprint(f'> error resetting shell {e}', colour=ERRORCOLOUR)


def checkcwdheader():

    global LASTCWD, SOCK, WINID, DRIVENUMBER

    try:

        loaddrives()

        # get current working directory
        cwd = os.getcwd()

        current = formatlocation(cwd)

    except Exception as e:

        # cwd check error
        guiprint(f'> error checking cwd {e}', colour=ERRORCOLOUR)
        return


    # redraw header if cwd changed
    if current != LASTCWD:

        drawheader()

        LASTCWD = current

        # inform window server of updated current (drive + cwd)
        if SOCK and WINID:
            sendline(SOCK, {"op": "WINDOW_CURRENT_SET", "winid": WINID, "current": current})


def initfont():

    global USE_TTF, CURRENTTTFFONT

    try:

        if os.path.exists(FONTREG):
            initttffont(FONTREG, FONTSIZE)

            USE_TTF = True
            CURRENTTTFFONT = FONTREG
            return

        USE_TTF = False
        CURRENTTTFFONT = None

    except Exception as e:

        # font init error
        guiprint(f'> error loading font {e}', colour=ERRORCOLOUR)


def setttffont(bold=False, semibold=False):

    global CURRENTTTFFONT


    if bold:
        target = FONTBOLD
    elif semibold:
        target = FONTSEMIBOLD
    else:
        target = FONTREG


    if CURRENTTTFFONT == target:
        return


    if not os.path.exists(target):
        return


    initttffont(target, FONTSIZE)
    CURRENTTTFFONT = target

def inithistory():

    global HIST, HISTPOS

    try:

        # load history file
        if os.path.exists(HISTFILE):
            with open(HISTFILE) as f:
                lines = [l.rstrip('\n') for l in f]
        else:
            lines = []

    except Exception as e:

        # history load error
        guiprint(f'> error loading history {e}', colour=ERRORCOLOUR)
        lines = []

    # keep non-empty and cap size
    HIST = [l for l in lines if l]
    if len(HIST) > HISTMAX:
        HIST = HIST[-HISTMAX:]

    # reset position
    HISTPOS = None


def listcommands():

    try:
        # return all dictionary keys as a list
        return list(DIRECTIVES.keys())

    except Exception:
        return []


def physicalnormalize(path):

    try:
        value = os.path.abspath(os.path.normpath(str(path)))
    except Exception:
        value = '/'

    if not value:
        value = '/'

    return value.replace('\\', '/')


def arraylinktarget(path, fileinfo=None):

    """Return the target stored in an ordinary T1OS link file."""

    try:
        info = fileinfo if fileinfo is not None else os.lstat(path)
        if not stat.S_ISREG(info.st_mode):
            return None
        if info.st_size <= len(LINKFILEHEADER) or info.st_size > LINKFILEMAXBYTES:
            return None
        with open(path, 'rb') as stream:
            raw = stream.read(LINKFILEMAXBYTES + 1)
        if len(raw) > LINKFILEMAXBYTES or not raw.startswith(LINKFILEHEADER):
            return None
        payload = json.loads(raw[len(LINKFILEHEADER):].decode('utf-8'))
        if not isinstance(payload, dict) or payload.get('version') != LINKFILEVERSION:
            return None
        target = payload.get('target')
        if not isinstance(target, str) or not target or '\x00' in target:
            return None
        return target
    except Exception:
        return None


def isarraylink(path, fileinfo=None):

    return arraylinktarget(path, fileinfo=fileinfo) is not None


def resolvearraylink(path):

    """Resolve a chain of T1OS links without filesystem symlink support."""

    current = physicalnormalize(path)
    seen = set()

    for _ in range(LINKFILEMAXHOPS):
        target = arraylinktarget(current)
        if target is None:
            return current, None

        key = physicalnormalize(current)
        if key in seen:
            return None, 'link target contains a loop'
        seen.add(key)

        if not os.path.isabs(target):
            target = os.path.join(os.path.dirname(current), target)
        current = physicalnormalize(target)

    if arraylinktarget(current) is not None:
        return None, 'link chain is too long'
    return current, None


def followarraylink(path):

    """Return a consumable target, raising a useful error for an invalid link."""

    original = physicalnormalize(path)
    target, error = resolvearraylink(original)

    if error:
        raise OSError(error)
    if target != original and not os.path.exists(target):
        raise OSError('link target is not available')
    return target


def loaddrives(force=False):

    global DRIVES, DRIVELASTSCAN, DRIVENUMBER

    now = time.time()

    if not force and DRIVES and (now - DRIVELASTSCAN) < DRIVESCANINTERVAL:
        return False

    old = dict(DRIVES)
    found = {1: {
        'number': 1, 'root': '/', 'label': 't1os', 'removable': False,
        'read_only': False, 'filesystem': '', 'source': '', 'device': '',
        'uuid': '',
    }}
    usedroots = {'/'}
    metadata = {}

    try:

        with open(DRIVEMETADATAFILE, 'r', encoding='utf-8', errors='replace') as stream:
            payload = json.load(stream)

        if isinstance(payload, dict) and payload.get('format') == 1:

            for entry in payload.get('volumes', []):

                if not isinstance(entry, dict):
                    continue

                root = physicalnormalize(entry.get('root'))

                if root == DRIVEBACKINGROOT or root.startswith(DRIVEBACKINGROOT + '/'):
                    metadata[root] = dict(entry)

    except Exception:
        pass

    assignments = []

    try:

        with open(DRIVESETTINGSFILE, 'r', encoding='utf-8', errors='replace') as stream:
            settings = json.load(stream)

        if isinstance(settings, dict) and isinstance(settings.get('drive_assignments'), list):
            assignments = settings.get('drive_assignments')

    except Exception:
        pass

    for entry in assignments:

        try:
            number = int(entry.get('number'))
            root = physicalnormalize(entry.get('root'))
        except Exception:
            continue

        if root == '/drives':
            root = DRIVEBACKINGROOT
        elif root.startswith('/drives/'):
            root = DRIVEBACKINGROOT + root[len('/drives'):]
        elif root == '/volumes':
            root = DRIVEBACKINGROOT
        elif root.startswith('/volumes/'):
            root = DRIVEBACKINGROOT + root[len('/volumes'):]

        if number <= 1 or root in usedroots or not os.path.isdir(root):
            continue

        found[number] = {
            'number': number,
            'root': root,
            'label': str(
                metadata.get(root, {}).get('label')
                or entry.get('label')
                or os.path.basename(root)
                or f'drive {number}'
            ),
            'removable': bool(metadata.get(root, {}).get('removable', entry.get('removable', True))),
            'read_only': bool(metadata.get(root, {}).get('read_only', False)),
            'filesystem': str(metadata.get(root, {}).get('filesystem', '')),
            'source': str(metadata.get(root, {}).get('source', '')),
            'device': str(metadata.get(root, {}).get('device', '')),
            'uuid': str(metadata.get(root, {}).get('uuid', '')),
        }
        usedroots.add(root)

    candidates = set(metadata)

    try:

        for name in os.listdir(DRIVEBACKINGROOT):
            root = physicalnormalize(os.path.join(DRIVEBACKINGROOT, name))

            if os.path.isdir(root) and (os.path.ismount(root) or root in metadata):
                candidates.add(root)

    except Exception:
        pass

    number = 2

    for root in sorted(candidates, key=lambda value: value.casefold()):

        if root in usedroots or not os.path.isdir(root):
            continue

        while number in found:
            number += 1

        found[number] = {
            'number': number,
            'root': root,
            'label': str(
                metadata.get(root, {}).get('label')
                or os.path.basename(root)
                or f'drive {number}'
            ),
            'removable': bool(metadata.get(root, {}).get('removable', True)),
            'read_only': bool(metadata.get(root, {}).get('read_only', False)),
            'filesystem': str(metadata.get(root, {}).get('filesystem', '')),
            'source': str(metadata.get(root, {}).get('source', '')),
            'device': str(metadata.get(root, {}).get('device', '')),
            'uuid': str(metadata.get(root, {}).get('uuid', '')),
        }
        usedroots.add(root)
        number += 1

    DRIVES = found
    DRIVELASTSCAN = now

    try:
        DRIVENUMBER = int(driveforpath(os.getcwd()).get('number', 1))
    except Exception:
        DRIVENUMBER = 1

    return old != DRIVES


def driveforpath(path):

    physical = physicalnormalize(path)
    best = DRIVES.get(1, {'number': 1, 'root': '/'})
    bestlen = 1

    for drive in DRIVES.values():

        root = physicalnormalize(drive.get('root', '/'))

        try:
            common = os.path.commonpath((physical, root)).replace('\\', '/')
        except Exception:
            continue

        if common == root and len(root) >= bestlen:
            best = drive
            bestlen = len(root)

    return best


def driverelpath(path, drive=None):

    if drive is None:
        drive = driveforpath(path)

    root = physicalnormalize(drive.get('root', '/'))
    physical = physicalnormalize(path)

    try:
        relative = os.path.relpath(physical, root).replace('\\', '/')
    except Exception:
        relative = ''

    if relative in ('', '.'):
        return '/'

    if relative == '..' or relative.startswith('../'):
        return '/'

    return '/' + relative.lstrip('/')


def drivepath(number, relative='/'):

    try:
        number = int(number)
    except Exception:
        number = 1

    drive = DRIVES.get(number)

    if drive is None:
        return None

    root = physicalnormalize(drive.get('root', '/'))
    relative = str(relative or '/').replace('\\', '/')
    physical = physicalnormalize(os.path.join(root, relative.lstrip('/')))

    try:

        if os.path.commonpath((physical, root)).replace('\\', '/') != root:
            return None

    except Exception:
        return None

    return physical


def parselocation(value, currentdrive=None):

    loaddrives()

    text = str(value or '').strip().replace('\\', '/')
    current = driveforpath(os.getcwd()) if currentdrive is None else DRIVES.get(int(currentdrive))
    number = int(current.get('number', 1)) if current else 1
    match = re.match(r'^([0-9]+)(?:/|$)(.*)$', text)

    if match:
        number = int(match.group(1))
        relative = '/' + match.group(2).lstrip('/')

    elif text.startswith('/'):
        # Preserve a private physical mount path passed back by Brick itself.
        physical = physicalnormalize(text)

        for drive in DRIVES.values():
            root = physicalnormalize(drive.get('root', '/'))

            if root != '/' and (physical == root or physical.startswith(root + '/')):
                return int(drive.get('number', 1)), physical

        relative = text

    else:
        base = driverelpath(os.getcwd(), current or DRIVES.get(1))
        relative = os.path.join(base, text).replace('\\', '/')

    return number, drivepath(number, relative)


def formatlocation(path):

    global DRIVENUMBER

    loaddrives()
    drive = driveforpath(path)
    DRIVENUMBER = int(drive.get('number', 1))
    return f"{DRIVENUMBER}{driverelpath(path, drive)}"


def resolvepath(p):

    number, path = parselocation(p)

    if path is None:

        if number not in DRIVES:
            raise ValueError(f'drive {number} is not available')

        raise ValueError('location cannot leave the drive root')

    return path


def displaytimestamp(value):

    try:
        return timestamp(float(value))
    except Exception:
        return str(value)


def lowertext(value):

    return str(value if value is not None else '').lower()


def lowerrows(records):

    return [
        [lowertext(value) for value in row]
        for row in records
    ]


def formatbytes(value):

    try:
        amount = max(0.0, float(value))
    except (TypeError, ValueError):
        return 'unavailable'
    units = ('bytes', 'kb', 'mb', 'gb', 'tb', 'pb')
    index = 0
    while amount >= 1024.0 and index < len(units) - 1:
        amount /= 1024.0
        index += 1
    if index == 0:
        return '{} {}'.format(int(amount), units[index])
    return '{:.1f} {}'.format(amount, units[index])


def formatpercent(value):

    try:
        return '{:.1f}%'.format(float(value))
    except (TypeError, ValueError):
        return 'unavailable'


def drivemountinformation(root):

    requested = physicalnormalize(root)
    try:
        with open('/the one/drivers/processes/self/mounts', 'r',
                  encoding='utf-8', errors='replace') as stream:
            for line in stream:
                fields = line.split()
                if len(fields) < 4:
                    continue
                target = physicalnormalize(fields[1].replace('\\040', ' '))
                if target != requested:
                    continue
                options = fields[3].split(',')
                return {
                    'source': fields[0].replace('\\040', ' '),
                    'filesystem': fields[2],
                    'read_only': 'ro' in options,
                }
    except OSError:
        pass
    return {}


def drivespace(root):

    try:
        state = os.statvfs(root)
        total = int(state.f_blocks) * int(state.f_frsize)
        available = int(state.f_bavail) * int(state.f_frsize)
        return total, available
    except OSError:
        return None, None


def listdrives(args=None):

    if args:
        guiprint('> list drives does not take an argument', colour=ERRORCOLOUR)
        return 1
    loaddrives(force=True)
    records = []
    for number, drive in sorted(DRIVES.items()):
        root = str(drive.get('root') or '')
        mounted = drivemountinformation(root)
        total, available = drivespace(root)
        records.append([
            str(number),
            drive.get('label', ''),
            drive.get('filesystem') or mounted.get('filesystem') or 'unknown',
            formatbytes(total),
            formatbytes(available),
            'yes' if os.path.isdir(root) else 'no',
            'yes' if drive.get('removable') else 'no',
            'yes' if drive.get('read_only', mounted.get('read_only', False)) else 'no',
        ])
    guiprint()
    showtable(
        ['drive', 'label', 'filesystem', 'capacity', 'available',
         'online', 'removable', 'read only'],
        lowerrows(records))
    guiprint()
    return 0


def drivedetails(args=None):

    if len(args or []) != 1:
        guiprint('> enter one drive number after the drive details directive',
                 colour=ERRORCOLOUR)
        return 1
    try:
        number = int(str(args[0]).rstrip('/'))
    except (TypeError, ValueError):
        guiprint('> the drive number is invalid', colour=ERRORCOLOUR)
        return 1
    loaddrives(force=True)
    drive = DRIVES.get(number)
    if drive is None:
        guiprint('> drive {} is not available'.format(number),
                 colour=ERRORCOLOUR)
        return 1
    root = str(drive.get('root') or '')
    mounted = drivemountinformation(root)
    total, available = drivespace(root)
    records = [
        ['drive', str(number)],
        ['label', drive.get('label', '')],
        ['location', str(number) + '/'],
        ['source', drive.get('source') or mounted.get('source') or 'managed by t1os'],
        ['device', drive.get('device') or 'unavailable'],
        ['filesystem', drive.get('filesystem') or mounted.get('filesystem') or 'unknown'],
        ['uuid', drive.get('uuid') or 'unavailable'],
        ['capacity', formatbytes(total)],
        ['available', formatbytes(available)],
        ['online', 'yes' if os.path.isdir(root) else 'no'],
        ['removable', 'yes' if drive.get('removable') else 'no'],
        ['read only', 'yes' if drive.get(
            'read_only', mounted.get('read_only', False)) else 'no'],
    ]
    guiprint()
    showtable(['detail', 'value'], lowerrows(records))
    guiprint()
    return 0


def pathcandidates(fragment):

    try:

        # split dir and base
        dpart, bpart = os.path.split(fragment)

        # list directory
        base = resolvepath(dpart) if dpart else os.getcwd()
        try:
            names = os.listdir(base)
        except Exception:
            return []

        # filter by prefix
        out = []
        for n in names:
            if n.startswith(bpart):
                cand = os.path.join(dpart, n) if dpart else n
                out.append(cand)

        # sort for stable ordering
        return sorted(out)

    except Exception:
        return []


def showcandidates(cands):

    try:

        # simple two-space separated list
        line = '  '.join(cands[:200])
        appendline(line)

    except Exception as e:

        # show candidates error
        guiprint(f'> error showing candidates {e}', colour=ERRORCOLOUR)


def completionterms(arguments, terms):

    try:

        starts = [0]

        for index, value in enumerate(str(arguments)):

            if value == ' ' and index + 1 < len(arguments):
                starts.append(index + 1)

        for start in starts:

            fragment = str(arguments)[start:]

            if not fragment:
                continue

            matches = sorted([
                str(term)
                for term in terms
                if str(term).startswith(fragment)
            ])

            if matches:
                return fragment, start, matches

    except Exception:
        pass

    return '', 0, []


def completeonce():

    global INPUTBUF, CURSORPOS, LASTTABBUF, LASTTABCANDS, DIRTY_PROMPT

    try:

        # isolate input up to the cursor and the current chained directive
        left = INPUTBUF[:CURSORPOS]
        right = INPUTBUF[CURSORPOS:]

        chainstart = left.rfind(';') + 1
        rawsegment = left[chainstart:]
        leading = len(rawsegment) - len(rawsegment.lstrip(' '))
        segment = rawsegment.lstrip(' ')
        segmentstart = chainstart + leading

        # complete help arguments from the directive catalogue
        if segment.startswith('help '):

            prefix = segment[5:]
            choices = set(DIRECTIVECATEGORIES)
            cands = sorted([name for name in choices if name.startswith(prefix)])
            wstart = segmentstart + 5
            mode = 'cmd'

        else:

            pool = sorted(listcommands())
            matches = [name for name in pool if segment == name or segment.startswith(name + ' ')]
            matched = max(matches, key=len) if matches else None

            # no complete directive yet, so complete the entire plain-English phrase
            if matched is None:

                prefix = segment
                cands = [name for name in pool if name.startswith(prefix)]
                wstart = segmentstart
                mode = 'cmd'

            else:

                argsstart = segmentstart + len(matched)

                if argsstart < len(left) and left[argsstart] == ' ':
                    argsstart += 1

                argtext = left[argsstart:]

                spec = directivespec(matched)
                grammar = dict(spec.get('grammar', {})) if spec else {}
                wordstart = argtext.rfind(' ') + 1
                wordprefix, termstart, termcands = completionterms(argtext, grammar.get('terms', []))

                if termcands and wordprefix:

                    prefix = wordprefix
                    wstart = argsstart + termstart
                    cands = termcands
                    mode = 'cmd'

                elif grammar.get('completion') == 'path':

                    prefix = argtext
                    wstart = argsstart
                    cands = pathcandidates(stripquotes(prefix))
                    mode = 'path'

                else:

                    prefix = argtext[wordstart:]
                    wstart = argsstart + wordstart
                    cands = pathcandidates(stripquotes(prefix))
                    mode = 'path'

        # nothing to do
        if not cands:
            LASTTABBUF = ''
            LASTTABCANDS = []
            DIRTY_PROMPT = True
            return

        # common prefix extension
        common = os.path.commonprefix(cands)

        if common and common != prefix:

            newleft = left[:wstart] + common

            INPUTBUF = newleft + right
            CURSORPOS = len(newleft)

            LASTTABBUF = INPUTBUF
            LASTTABCANDS = cands

            DIRTY_PROMPT = True
            return

        # single candidate -> accept
        if len(cands) == 1:

            comp = cands[0]


            # quote paths containing spaces so args stay intact

            if mode == "path" and ' ' in comp and not (comp.startswith('"') and comp.endswith('"')):
                comp = '"' + comp + '"'

            suffix = ' ' if mode == "cmd" else ''

            newleft = left[:wstart] + comp + suffix

            INPUTBUF = newleft + right
            CURSORPOS = len(newleft)

            LASTTABBUF = INPUTBUF
            LASTTABCANDS = [comp]

            DIRTY_PROMPT = True
            return

        # double-tab behaviour - repeat to show choices
        if LASTTABBUF == INPUTBUF and LASTTABCANDS == cands:
            showcandidates(cands)
            DIRTY_PROMPT = True
            return

        # prime for next tab
        LASTTABBUF = INPUTBUF
        LASTTABCANDS = cands

    except Exception as e:

        # completion error
        guiprint(f'> error completing {e}', colour=ERRORCOLOUR)


def suggestfromhistory(buf, cursorpos):

    try:

        # only suggest when cursor is at end of input
        if cursorpos is None:
            return ""

        if buf is None:
            return ""

        if cursorpos != len(buf):
            return ""

        prefix = str(buf)

        if not prefix:
            return ""

    except Exception:
        return ""

    try:

        # newest match wins
        for line in reversed(HIST):


            if not line:
                continue

            if not isinstance(line, str):
                line = str(line)

            if line.startswith(prefix) and len(line) > len(prefix):
                return line[len(prefix):]

    except Exception:
        return ""

    return ""


def savehistory():

    try:

        # ensure history directory exists
        d = os.path.dirname(HISTFILE)
        if d and not os.path.exists(d):
            os.makedirs(d, exist_ok=True)

        # save recent history
        with open(HISTFILE, 'w') as f:
            for l in HIST[-HISTMAX:]:
                f.write(l + '\n')

        return True

    except Exception as e:

        # history save error
        guiprint(f'> error saving history {lowertext(e)}', colour=ERRORCOLOUR)
        return False


def addhistory(line):

    global HIST

    try:

        # normalise
        s = line.strip()
        if not s:
            return

        # avoid duplicate consecutive entries
        if HIST and HIST[-1] == s:
            return

        # append and cap
        HIST.append(s)
        if len(HIST) > HISTMAX:
            del HIST[0:len(HIST)-HISTMAX]

    except Exception as e:

        # history add error
        guiprint(f'> error adding history {e}', colour=ERRORCOLOUR)


def historydir(args=None):

    values = list(args or [])
    if len(values) > 1:
        guiprint('> history accepts one optional count', colour=ERRORCOLOUR)
        return 1
    count = len(HIST)
    if values:
        try:
            count = int(values[0])
        except (TypeError, ValueError):
            guiprint('> history count must be a number', colour=ERRORCOLOUR)
            return 1
        if count < 1:
            guiprint('> history count must be at least one', colour=ERRORCOLOUR)
            return 1
    selected = HIST[-min(count, len(HIST)):] if HIST else []
    start = max(1, len(HIST) - len(selected) + 1)
    guiprint()
    if selected:
        showtable(
            ['number', 'directive'],
            lowerrows([[str(start + index), line]
                       for index, line in enumerate(selected)]))
    else:
        guiprint('> directive history is empty', colour=TEXTCOLOUR)
    guiprint()
    return 0


def clearhistory(args=None):

    global HISTPOS
    if args:
        guiprint('> clear history does not take an argument', colour=ERRORCOLOUR)
        return 1
    previous = list(HIST)
    HIST.clear()
    HISTPOS = None
    if not savehistory():
        HIST.extend(previous)
        return 1
    guiprint('> directive history cleared', colour=TEXTCOLOUR)
    return 0


def historystep(delta):

    global HISTPOS, INPUTBUF, CURSORPOS, DIRTY_PROMPT

    try:

        # no history to step through
        if not HIST:
            return

        # initial position is "after last entry" (blank line)
        if HISTPOS is None:
            HISTPOS = len(HIST)

        # move within [0, len(HIST)]
        HISTPOS += delta

        # clamp to valid range
        if HISTPOS < 0:
            HISTPOS = 0

        if HISTPOS > len(HIST):
            HISTPOS = len(HIST)

        # len(HIST) means blank new entry (like bash's newest+1 slot)
        if HISTPOS == len(HIST):

            # clear input buffer
            INPUTBUF = ''

            # reset cursor to start
            CURSORPOS = 0

            # mark prompt dirty
            DIRTY_PROMPT = True
            return

        # otherwise load the selected history entry
        INPUTBUF = HIST[HISTPOS]

        # cursor at end of the recalled command
        CURSORPOS = len(INPUTBUF)

        # mark prompt dirty
        DIRTY_PROMPT = True

    except Exception as e:

        # history step error
        guiprint(f'> error stepping history {e}', colour=ERRORCOLOUR)


# content functions
def pagerows():

    try:
        return max(0, int(contentlayout().get('rows', 0)))

    except Exception as e:

        # rows compute error
        guiprint(f'> error computing rows {e}', colour=ERRORCOLOUR)
        return 0


def page(delta):

    global SCROLLOFF, DIRTY_SCROLL, DIRTY_PROMPT

    try:

        cancelsmoothscroll()

        # one page is the visible row count
        rows = pagerows()

        # nothing to do if we have no room
        if rows <= 0:
            return

        # adjust offset (positive = scroll up/back in history)
        SCROLLOFF = max(0, SCROLLOFF + (rows * delta))

        DIRTY_SCROLL = True
        DIRTY_PROMPT = True

    except Exception as e:

        # paging error
        guiprint(f'> error paging {e}', colour=ERRORCOLOUR)


def snapbottom():

    global SCROLLOFF, DIRTY_SCROLL, DIRTY_PROMPT

    try:

        cancelsmoothscroll()

        # reset offset to follow live output
        SCROLLOFF = 0
        DIRTY_SCROLL = True
        DIRTY_PROMPT = True

    except Exception as e:

        # snap error
        guiprint(f'> error snapping to bottom {e}', colour=ERRORCOLOUR)


def queuesmoothscroll(delta):

    global PENDINGSCROLL

    try:

        limit = max(1, SCROLL_MAX)
        PENDINGSCROLL += int(delta)
        PENDINGSCROLL = max(-limit, min(limit, PENDINGSCROLL))
        return bool(PENDINGSCROLL)

    except Exception as e:

        guiprint(f'> error queueing smooth scroll {e}', colour=ERRORCOLOUR)
        return False


def cancelsmoothscroll():

    global PENDINGSCROLL, LASTSMOOTHSCROLL

    PENDINGSCROLL = 0
    LASTSMOOTHSCROLL = 0.0


def flushsmoothscroll(force=False):

    global SCROLLOFF, PENDINGSCROLL, LASTSMOOTHSCROLL
    global DIRTY_SCROLL, DIRTY_PROMPT

    if not PENDINGSCROLL:
        return False

    try:

        now = time.monotonic()
        managed = bool(GRAPHICSSTATE.get("active") and GRAPHICSSTATE.get("managed_only"))
        interval = SCROLLMANAGEDINTERVAL if managed else SCROLLCPUINTERVAL

        if not force and LASTSMOOTHSCROLL and now - LASTSMOOTHSCROLL < interval:
            return False

        layout = contentlayout()
        maxoff = max(0, int(layout.get('total', 0)) - int(layout.get('rows', 0)))
        remaining = int(PENDINGSCROLL)
        magnitude = abs(remaining)

        if force:
            amount = magnitude
        else:
            amount = max(1, int(math.ceil(magnitude * SMOOTHSCROLLEASING)))
            amount = min(amount, SMOOTHSCROLLMAXSTEP)

        delta = amount if remaining > 0 else -amount
        oldoffset = int(SCROLLOFF)
        SCROLLOFF = max(0, min(maxoff, oldoffset + delta))
        PENDINGSCROLL -= delta

        if SCROLLOFF == oldoffset:
            PENDINGSCROLL = 0

        elif (SCROLLOFF == 0 and PENDINGSCROLL < 0) or (SCROLLOFF == maxoff and PENDINGSCROLL > 0):
            PENDINGSCROLL = 0

        LASTSMOOTHSCROLL = now

        if SCROLLOFF != oldoffset:
            DIRTY_SCROLL = True
            DIRTY_PROMPT = True
            return True

    except Exception as e:

        PENDINGSCROLL = 0
        guiprint(f'> error flushing smooth scroll {e}', colour=ERRORCOLOUR)

    return False


def maxcolsvisible(s, e):

    try:

        m = 0

        for i in range(s, e):


            l = len(SCROLL[i])

            if l > m:
                m = l


        pl = len(PROMPT) + 1 + len(INPUTBUF)

        if pl > m:
            m = pl

        return m

    except Exception:

        return 0


def playbackheight():

    # Playback occupies two ordinary scrollback rows instead of reserving a
    # fixed band at the bottom of the shell.
    return 0


def playbacklineindex():

    if not PLAYBACK:

        return None

    playbackid = PLAYBACK.get('id')

    for index, style in enumerate(STYLES):

        if isinstance(style, dict) and style.get('playback') == playbackid and int(style.get('playback_row', -1)) == 0:

            return index

    return None


def playbackappend(playbackid, rows=2):

    rows = max(2, min(64, int(rows)))

    for row in range(rows):

        appendline(('', {'playback': playbackid, 'playback_row': row}))


def playbackfinish(playbackid, message):

    indexes = []

    for index, style in enumerate(STYLES):

        if not isinstance(style, dict) or style.get('playback') != playbackid:

            continue

        indexes.append(index)

    if not indexes:

        guiprint(str(message), colour=TEXTCOLOUR)

        return

    first = indexes[0]
    SCROLL[first] = str(message)
    STYLES[first] = None

    for index in reversed(indexes[1:]):

        try:

            del SCROLL[index]
            del STYLES[index]

        except Exception:

            SCROLL[index] = ''
            STYLES[index] = None


def playbackrows(info):

    if not isinstance(info, dict) or info.get('kind') != 'video':

        return 2

    video = info.get('video', {})
    width = max(1, int(video.get('display_width', video.get('width', 16)) or 16))
    height = max(1, int(video.get('display_height', video.get('height', 9)) or 9))
    screenwidth = max(1, int(getattr(gfx, '_xres', 1920)) - (LEFTPAD * 2))
    screenheight = max(1, int(getattr(gfx, '_yres', 1080)))
    frameheight = min(int(screenwidth * (height / float(width))), int(screenheight * 0.45))
    framerows = max(6, int(math.ceil(max(LINEHEIGHT, frameheight) / float(max(1, LINEHEIGHT)))))
    return min(34, framerows + 2)


def formataudiotime(seconds):

    try:

        seconds = max(0, int(float(seconds)))

    except Exception:

        seconds = 0

    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    remaining = seconds % 60

    if hours > 0:

        return f'{hours}:{minutes:02d}:{remaining:02d}'

    return f'{minutes}:{remaining:02d}'


def playbackgeometry():

    if not PLAYBACK:

        return {}

    index = playbacklineindex()

    if index is None:

        return {}

    layout = contentlayout()
    start = int(layout.get('start', 0))
    end = int(layout.get('end', 0))
    visualindex = None

    for rowindex, row in enumerate(layout.get('visual_rows', [])):

        if int(row[0]) == index:
            visualindex = rowindex
            break

    if visualindex is None:

        return {}

    rows = max(2, int(PLAYBACK.get('rows', 2) or 2))

    if visualindex >= end or visualindex + rows <= start:

        return {}

    screen_w = max(1, int(getattr(gfx, '_xres', 1920)))
    anchor = int(layout.get('y0', 0)) + ((visualindex - start) * LINEHEIGHT)
    contenttop = int(layout.get('top', layout.get('y0', 0)))
    contentbottom = min(
        int(layout.get('screen_h', getattr(gfx, '_yres', 1080))),
        int(layout.get('prompty', getattr(gfx, '_yres', 1080))),
    )
    controlheight = max(1, int(LINEHEIGHT * 2))
    controly = anchor + ((rows - 2) * LINEHEIGHT)
    iconsize = max(10, min(max(10, controlheight - 4), int(LINEHEIGHT * 1.25)))
    centrey = controly + (controlheight // 2)
    icony = centrey - (iconsize // 2)
    gap = max(6, int(8 * UISCALE))
    stopx = LEFTPAD
    togglex = stopx + iconsize + gap
    timetext = (
        f"{formataudiotime(PLAYBACK.get('position', 0.0))} / "
        f"{formataudiotime(PLAYBACK.get('duration', 0.0))}"
    )
    timewidth = max(SPACEW * len(timetext), SPACEW * 11)
    rightedge = screen_w - LEFTPAD

    if int(layout.get('total', 0)) > int(layout.get('rows', 0)):

        rightedge -= SCROLLBAR_WIDTH + SCROLLBAR_MARGIN

    trackx = togglex + iconsize + (gap * 2)
    availablewidth = max(20, rightedge - trackx - (gap * 2) - timewidth)
    preferredwidth = max(120, SPACEW * 28, int(320 * UISCALE))
    trackwidth = max(20, min(availablewidth, preferredwidth))
    trackend = trackx + trackwidth
    timex = trackend + (gap * 2)
    trackheight = max(2, int(2 * UISCALE))
    tracky = centrey - (trackheight // 2)
    thumbsize = max(8, int(10 * UISCALE))
    duration = max(0.0, float(PLAYBACK.get('duration', 0.0) or 0.0))
    position = PLAYBACK_PREVIEW if PLAYBACK_DRAGGING and PLAYBACK_PREVIEW is not None else PLAYBACK.get('position', 0.0)

    try:

        fraction = float(position) / duration if duration > 0.0 else 0.0

    except Exception:

        fraction = 0.0

    fraction = max(0.0, min(1.0, fraction))
    thumbcentre = int(trackx + (fraction * trackwidth))
    videorect = [0, 0, 0, 0]

    if str(PLAYBACK.get('media_kind', 'audio')) == 'video' and rows > 2:

        videorect = [LEFTPAD, anchor, max(1, rightedge - LEFTPAD), max(1, (rows - 2) * LINEHEIGHT)]

    return {
        'x': 0,
        'y': anchor,
        'width': screen_w,
        'height': rows * LINEHEIGHT,
        'clip': [0, contenttop, screen_w, max(1, contentbottom - contenttop)],
        'video': videorect,
        'stop': [stopx, icony, iconsize, iconsize],
        'toggle': [togglex, icony, iconsize, iconsize],
        'track': [trackx, tracky, trackwidth, trackheight],
        'thumb': [thumbcentre - (thumbsize // 2), centrey - (thumbsize // 2), thumbsize, thumbsize],
        'time': [timex, centrey - (LINEHEIGHT // 2), timetext],
    }


def playbackpositionfromx(x):

    geometry = playbackgeometry()
    track = geometry.get('track') if geometry else None
    duration = max(0.0, float(PLAYBACK.get('duration', 0.0) or 0.0))

    if not track or duration <= 0.0:

        return 0.0

    fraction = (float(x) - float(track[0])) / float(max(1, track[2]))
    fraction = max(0.0, min(1.0, fraction))

    return fraction * duration


def pointinrect(x, y, rect):

    return bool(
        rect and
        x >= int(rect[0]) and x < int(rect[0]) + int(rect[2]) and
        y >= int(rect[1]) and y < int(rect[1]) + int(rect[3])
    )


def playbackcommand(command, position=None):

    controlpath = str(PLAYBACK.get('control', '') or '')

    if not controlpath:

        return False

    return audiocontrol(controlpath, command, position=position)


def playbacktoggle():

    global DIRTY_SCROLL, DIRTY_PROMPT

    if not PLAYBACK.get('control'):
        return False

    if str(PLAYBACK.get('state', 'playing')) == 'paused':
        command = 'resume'
        state = 'playing'
    else:
        command = 'pause'
        state = 'paused'

    if not playbackcommand(command):
        return False

    PLAYBACK['state'] = state
    DIRTY_SCROLL = True
    DIRTY_PROMPT = True
    return True


def playbackstatusline(line):

    global PLAYBACK, DIRTY_SCROLL, DIRTY_PROMPT

    text = str(line)

    prefix = ''

    for candidate in (PLAYBACKSTATUSPREFIX, MEDIASTATUSPREFIX, MEDIAFRAMEPREFIX):

        if text.startswith(candidate):

            prefix = candidate
            break

    if not prefix:

        return False

    try:

        status = json.loads(text[len(prefix):])

    except Exception:

        return True

    if not isinstance(status, dict):

        return True

    if status.get('type') == 'media_frame':

        try:

            generation = int(status.get('generation', -1))
            currentgeneration = int(PLAYBACK.get('generation', 0))
            path = os.path.realpath(str(status.get('path', '')))
            root = os.path.realpath('/.ephemeral/media')
            width = int(status.get('width', 0))
            height = int(status.get('height', 0))

            if generation < currentgeneration:

                return True

            if (
                os.path.commonpath((root, path)) != root
                or not os.path.isfile(path)
                or width < 1
                or height < 1
                or width * height > 16777216
                or os.path.getsize(path) < width * height * 4
            ):

                return True

            PLAYBACK['frame'] = dict(status)
            PLAYBACK['media_kind'] = 'video'

        except Exception:

            return True

        DIRTY_SCROLL = True
        DIRTY_PROMPT = True
        return True

    if status.get('type') not in ('audio_status', 'media_status'):

        return True

    PLAYBACK.update(status)
    DIRTY_SCROLL = True
    DIRTY_PROMPT = True

    return True


def playbacksuppressline(line):

    return bool(
        PLAYBACK and
        str(PLAYBACK.get('state', '')) == 'stopped' and
        str(line).strip() == '> playback stopped'
    )


def wrapranges(text, columns):

    text = str(text)
    columns = max(1, int(columns))
    length = len(text)

    if length == 0:

        return [(0, 0)]

    ranges = []
    start = 0

    while start < length:

        end = min(length, start + columns)

        if end < length:

            # Prefer a word boundary, retaining the whitespace in this slice
            # so visual rows still map exactly onto the logical line.
            boundary = end

            while boundary > start and not text[boundary - 1].isspace():
                boundary -= 1

            if boundary > start and text[start:boundary].strip():
                end = boundary

        if end <= start:
            end = min(length, start + columns)

        ranges.append((start, end))
        start = end

    return ranges


def wrappedscrollrows(columns):

    global WRAPCACHEKEY
    global WRAPCACHEROWS

    columns = max(1, int(columns))
    key = (
        columns,
        SCROLL.generation,
        STYLES.generation,
        len(SCROLL),
        len(STYLES),
    )

    if key == WRAPCACHEKEY:
        return WRAPCACHEROWS

    lines = tuple(str(line) for line in SCROLL)
    rows = []

    for index, line in enumerate(lines):

        style = STYLES[index] if index < len(STYLES) else None

        if (
            isinstance(style, dict)
            and (
                isinstance(style.get('image'), dict)
                or style.get('playback') is not None
            )
        ):
            ranges = [(0, len(line))]
        else:
            ranges = wrapranges(line, columns)

        for start, end in ranges:
            rows.append((index, start, end))

    WRAPCACHEKEY = key
    WRAPCACHEROWS = rows
    return rows


def wrappedpromptrows(columns):

    columns = max(1, int(columns))
    text = str(INPUTBUF)
    prefixcolumns = len(PROMPT) + 1
    firstcolumns = max(1, columns - prefixcolumns)

    if not text:

        return [(0, 0, True)]

    rows = []
    firststart, firstend = wrapranges(text, firstcolumns)[0]
    rows.append((firststart, firstend, True))
    offset = firstend

    if offset < len(text):

        for start, end in wrapranges(text[offset:], columns):
            rows.append((offset + start, offset + end, False))

    return rows


def visiblepromptrows(rows, maximum):

    maximum = max(1, int(maximum))

    if len(rows) <= maximum:
        return rows

    cursorrow = len(rows) - 1

    for index, (start, end, showprompt) in enumerate(rows):

        if CURSORPOS < end or index == len(rows) - 1:
            cursorrow = index
            break

    first = max(0, min(cursorrow, len(rows) - maximum))
    return rows[first:first + maximum]


def contentlayout():

    global SCROLLOFF
    global HSCROLL
    global HSCROLL_MAX
    global HSCROLL_VIEWCOLS
    global HSCROLLBAR_VISIBLE
    global CONTENTLAYOUTKEY
    global CONTENTLAYOUTCACHE

    try:

        header_y = TOPBLANKLINES * LINEHEIGHT

        top = header_y + ((1 + SPACERLINES) * LINEHEIGHT)

        screen_w = getattr(gfx, '_xres', 1920)

        screen_h = getattr(gfx, '_yres', 1080)

        cachekey = (
            SCROLL.generation,
            STYLES.generation,
            len(SCROLL),
            len(STYLES),
            SCROLLOFF,
            HSCROLL,
            INPUTBUF,
            CURSORPOS,
            PROMPT,
            screen_w,
            screen_h,
            TOPBLANKLINES,
            SPACERLINES,
            LINEHEIGHT,
            LEFTPAD,
            SPACEW,
            SCROLLBAR_WIDTH,
            SCROLLBAR_MARGIN,
            playbackheight(),
        )

        if cachekey == CONTENTLAYOUTKEY and CONTENTLAYOUTCACHE is not None:
            return CONTENTLAYOUTCACHE

        # Scrollback and the prompt wrap to the live content width.  The
        # vertical scrollbar narrows that width, so settle its state before
        # selecting the visible rows.
        vbar_visible = False
        visualrows = []
        promptrows = []
        avail_cols = 1
        rows = 0

        for unused in range(4):

            reserved = playbackheight()
            right_limit = screen_w

            if vbar_visible:
                right_limit -= SCROLLBAR_WIDTH + SCROLLBAR_MARGIN

            avail_px = max(1, right_limit - LEFTPAD)
            avail_cols = max(1, avail_px // max(1, SPACEW))
            visualrows = wrappedscrollrows(avail_cols)
            promptrows = wrappedpromptrows(avail_cols)
            promptcapacity = max(1, (screen_h - top - reserved) // LINEHEIGHT - 1)
            promptrows = visiblepromptrows(promptrows, promptcapacity)
            rows = max(
                0,
                (screen_h - top - reserved) // LINEHEIGHT
                - len(promptrows)
                - 1,
            )
            new_vbar_visible = len(visualrows) > rows

            if new_vbar_visible == vbar_visible:
                break

            vbar_visible = new_vbar_visible

        # Recompute once with the settled states.
        reserved = playbackheight()
        right_limit = screen_w

        if vbar_visible:
            right_limit -= SCROLLBAR_WIDTH + SCROLLBAR_MARGIN

        avail_px = max(1, right_limit - LEFTPAD)
        avail_cols = max(1, avail_px // max(1, SPACEW))
        visualrows = wrappedscrollrows(avail_cols)
        promptrows = wrappedpromptrows(avail_cols)
        promptcapacity = max(1, (screen_h - top - reserved) // LINEHEIGHT - 1)
        promptrows = visiblepromptrows(promptrows, promptcapacity)
        rows = max(
            0,
            (screen_h - top - reserved) // LINEHEIGHT
            - len(promptrows)
            - 1,
        )
        total = len(visualrows)
        vbar_visible = total > rows
        maxscroll = 0

        maxoff = max(0, total - rows)

        if SCROLLOFF > maxoff:
            SCROLLOFF = maxoff

        if SCROLLOFF < 0:
            SCROLLOFF = 0

        start = max(0, total - rows - SCROLLOFF)
        end = min(total, start + rows)

        HSCROLL_MAX = maxscroll

        HSCROLLBAR_VISIBLE = True if HSCROLL_MAX > 0 else False

        HSCROLL_VIEWCOLS = avail_cols

        if HSCROLL > HSCROLL_MAX:
            HSCROLL = HSCROLL_MAX

        if HSCROLL < 0:
            HSCROLL = 0

        x0 = LEFTPAD
        promptx0 = LEFTPAD

        y0 = top

        drawn = end - start

        prompty = y0 + (drawn * LINEHEIGHT)

        result = {
            "top": top,
            "screen_w": screen_w,
            "screen_h": screen_h,
            "rows": rows,
            "total": total,
            "start": start,
            "end": end,
            "x0": x0,
            "prompt_x0": promptx0,
            "y0": y0,
            "prompty": prompty,
            "wrap_cols": avail_cols,
            "visual_rows": visualrows,
            "visible_rows": visualrows[start:end],
            "prompt_rows": promptrows,
            "vbar_visible": vbar_visible
        }

        CONTENTLAYOUTKEY = (
            SCROLL.generation,
            STYLES.generation,
            len(SCROLL),
            len(STYLES),
            SCROLLOFF,
            HSCROLL,
            INPUTBUF,
            CURSORPOS,
            PROMPT,
            screen_w,
            screen_h,
            TOPBLANKLINES,
            SPACERLINES,
            LINEHEIGHT,
            LEFTPAD,
            SPACEW,
            SCROLLBAR_WIDTH,
            SCROLLBAR_MARGIN,
            playbackheight(),
        )
        CONTENTLAYOUTCACHE = result
        return result

    except Exception:

        return {
            "top": 0,
            "screen_w": 1920,
            "screen_h": 1080,
            "rows": 0,
            "total": 0,
            "start": 0,
            "end": 0,
            "x0": LEFTPAD,
            "prompt_x0": LEFTPAD,
            "y0": 0,
            "prompty": 0,
            "wrap_cols": 1,
            "visual_rows": [],
            "visible_rows": [],
            "prompt_rows": [(0, 0, True)],
            "vbar_visible": False
        }


# window functions
def windowsqrt(scale_w, scale_h):

    return displayuiscale(
        scale_w, scale_h, 1.0, BASESCREENW, BASESCREENH)


def windowrequest():

    try:
        aw = WORKW if WORKW > 0 else SCREENW

        ah = WORKH if WORKH > 0 else SCREENH

    except Exception:
        aw = 0
        ah = 0

    s = windowsqrt(aw, ah)

    w = int(BASEWINDOWW * s)

    h = int(BASEWINDOWH * s)

    x = int(BASEWINDOWX * s)

    y = int(BASEWINDOWY * s)

    if w < WINDOWMINW:
        w = WINDOWMINW

    if h < WINDOWMINH:
        h = WINDOWMINH

    if aw > 0:
        maxw = aw - WINDOWMARGIN

        if maxw > WINDOWMINW and w > maxw:
            w = maxw

    if ah > 0:
        maxh = ah - WINDOWMARGIN

        if maxh > WINDOWMINH and h > maxh:
            h = maxh

    if aw > 0:
        if x < WORKX:
            x = WORKX

        if x + w > WORKX + aw:
            x = (WORKX + aw) - w

    if ah > 0:
        if y < WORKY:
            y = WORKY

        if y + h > WORKY + ah:
            y = (WORKY + ah) - h

    return w, h, x, y


def opensocket():

    try:

        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

        s.connect(WINDOWSOCKPATH)

        s.setblocking(True)

        return s

    except Exception as e:

        print(formatlog('brick', f'window socket error {e}'))
        return None


def updatesocketevents(sock):

    try:

        key = SEL.get_key(sock)
        events = selectors.EVENT_READ

        if OUTBUF:
            events |= selectors.EVENT_WRITE

        if key.events != events:
            SEL.modify(sock, events, data={"kind": "server"})

    except KeyError:
        pass

    except Exception:
        pass


def flushwindowoutput(sock):

    global OUTBUF

    if not sock:
        return False

    try:

        while OUTBUF:

            try:
                sent = sock.send(OUTBUF)

            except BlockingIOError:
                break

            if sent is None or int(sent) <= 0:
                raise BrokenPipeError("window socket stopped accepting output")

            del OUTBUF[:int(sent)]

        updatesocketevents(sock)
        return True

    except Exception as e:

        print(formatlog('brick', f'window flush error {e}'))
        return False


def sendline(sock, obj):

    global OUTBUF

    try:
        data = (json.dumps(obj, separators=(",", ":")) + "\n").encode("utf-8")

        if sock.getblocking():
            sock.sendall(data)
            return True

        if len(OUTBUF) + len(data) > OUTBUFLIMIT:
            raise BufferError("window output queue limit reached")

        OUTBUF.extend(data)
        updatesocketevents(sock)
        return flushwindowoutput(sock)

    except Exception as e:
        print(formatlog('brick', f'window send error {e}'))
        return False


def initsocketevents(sock):

    global INBUF, OUTBUF

    try:

        # make non-blocking and register for read
        sock.setblocking(False)
        INBUF = b""
        OUTBUF = bytearray()
        SEL.register(sock, selectors.EVENT_READ, data={"kind": "server"})

    except PermissionError:

        # permission denied on socket
        guiprint("> permission denied setting socket non-blocking", colour=ERRORCOLOUR)

    except Exception as e:

        # socket init error
        guiprint(f"> socket init error {e}", colour=ERRORCOLOUR)


def handleservermsg(msg):

    global HASFOCUS, CTRLHELD, KEYQUEUE, SCROLLOFF, DIRTY_SCROLL, DIRTY_PROMPT, RUNNING, SOCK

    try:

        # parse op
        op = str(msg.get("op", ""))

        if op == "GRAPHICS_COMMITTED":

            graphicscommitted(msg)
            return

        if op == "GRAPHICS_CLEARED":

            graphicscleared(msg)
            return

        if op in ("GRAPHICS_BEGUN", "GRAPHICS_COMMAND_ADDED", "GRAPHICS_INFO"):
            return

        if op == "ERROR":

            code = str(msg.get("code", ""))

            if code.startswith("graphics_"):
                managedresponse(GRAPHICSSTATE, msg)
                graphicssyncstate()

                if code != "graphics_clear_failed" and not GRAPHICSAVAILABLE and SOCK and WINID:
                    sendline(SOCK, {
                        "op": "GRAPHICS_CLEAR",
                        "winid": WINID,
                        "reason": f"{code}: {msg.get('detail', '')}"[:256],
                    })

                graphicssyncstate()
                graphicsrestorecpu()

            return

        # close event
        if op == "CLOSE":


            # save directive history immediately
            savehistory()

            # tell windowserver we're done saving
            sendline(SOCK, {"op": "CLOSE_ACK", "pid": os.getpid(), "winid": WINID})

            RUNNING = False
            return

        # framebuffer size update
        if op == "FB_SIZE":

            try:

                w = int(msg.get("w", 0))

                h = int(msg.get("h", 0))

            except Exception:

                w = 0

                h = 0

            if w > 0 and h > 0:

                SCREENW = w

                SCREENH = h

                applyuiscale(SCREENW, SCREENH)

                if USE_TTF and CURRENTTTFFONT:
                    initttffont(CURRENTTTFFONT, FONTSIZE)

                measurements()

                consolefit()

                DIRTY_SCROLL = True

                DIRTY_PROMPT = True

            return

        # work area update
        if op == "WORK_AREA":

            try:
                x = int(msg.get("x", 0))

                y = int(msg.get("y", 0))

                w = int(msg.get("w", 0))

                h = int(msg.get("h", 0))

            except Exception:

                x = 0

                y = 0

                w = 0

                h = 0

            if w > 0 and h > 0:

                WORKX = x

                WORKY = y

                WORKW = w

                WORKH = h

            return

        # focus change
        if op == "FOCUS":


            wid = int(msg.get("winid", 0))
            if WINID and wid != WINID:
                return

            state = str(msg.get("state", "out"))

            if state == "in":
                HASFOCUS = True
                if consoleactive() and ACTIVE_CONSOLE['display'].focus_events:
                    consolewrite(b'\x1b[I')
            else:
                HASFOCUS = False
                CTRLHELD = False
                if consoleactive() and ACTIVE_CONSOLE['display'].focus_events:
                    consolewrite(b'\x1b[O')

            DIRTY_PROMPT = True
            return

        # resize event
        if op == "RESIZED":


            wid = int(msg.get("winid", 0))
            if WINID and wid != WINID:
                return

            onresized(msg)
            return

        # text event (printable chars AND ctrl control-codes like \x01, \x18)
        if op == "TEXT":


            wid = int(msg.get("winid", 0))
            if WINID and wid != WINID:
                return

            # WindowServer only directs TEXT to its focused window. Treat the
            # ordered event itself as a focus reaffirmation so a stale local
            # FOCUS cache cannot make a restored terminal discard input.
            if not HASFOCUS:
                HASFOCUS = True
                DIRTY_PROMPT = True


            text = msg.get("text", "")
            if text is None:
                text = ""

            if not isinstance(text, str):
                text = str(text)

            if not text:
                return

            if consoleactive():
                consoletext(text)
                return

            KEYQUEUE.append(text)
            return

        # key event (non-text keys + modifiers)
        if op == "KEY":


            wid = int(msg.get("winid", 0))
            if WINID and wid != WINID:
                return

            # As with TEXT, a directed KEY record is authoritative proof that
            # this window is focused at this point in the server stream.
            if not HASFOCUS:
                HASFOCUS = True
                DIRTY_PROMPT = True

            try:
                state = str(msg.get("state", "down"))
            except Exception:
                state = "down"

            try:
                key = str(msg.get("key", "")).upper()
            except Exception:
                key = ""

            try:
                keymods = msg.get("mods", {})
                if not isinstance(keymods, dict):
                    keymods = {}
                if key in ("CTRL", "CONTROL", "LEFTCTRL", "RIGHTCTRL", "LCTRL", "RCTRL"):
                    CTRLHELD = state in ("down", "repeat")
                else:
                    CTRLHELD = bool(keymods.get("ctrl", CTRLHELD))
            except Exception:
                pass

            if consoleactive():
                consolekeyevent(key, state, keymods)
                return

            # Key-up never performs an action. Repeat is handled below once the
            # key name is known so only navigation/editing keys can auto-repeat.
            if state not in ("down", "repeat"):
                return

            if state == "repeat" and key not in {
                "LEFT", "RIGHT", "UP", "DOWN", "HOME", "END",
                "PGUP", "PAGEUP", "PGDN", "PAGEDOWN",
                "BACKSPACE", "BKSP", "DELETE", "DEL",
            }:
                return

            if key == "PLAYPAUSE":
                playbacktoggle()
                return

            try:
                mods = msg.get("mods", {})
                if not isinstance(mods, dict):
                    mods = {}
            except Exception:
                mods = {}

            try:
                shift = bool(mods.get("shift", False))
                ctrl = bool(mods.get("ctrl", False))
                alt = bool(mods.get("alt", False))
            except Exception:
                shift = False
                ctrl = False
                alt = False

            if ctrl and not alt:

                if key == "C":
                    KEYQUEUE.append("<COPY>")
                    return

                if key == "V":
                    KEYQUEUE.append("<PASTE>")
                    return

                if key == "X":
                    KEYQUEUE.append("<CUT>")
                    return

                if key == "A":
                    KEYQUEUE.append("<SELECTALL>")
                    return

                if key == "S":
                    KEYQUEUE.append(STOPKEY)
                    return

            token = None

            if key in ("LEFT",):
                token = "<SLEFT>" if shift else "<LEFT>"

            elif key in ("RIGHT",):
                token = "<SRIGHT>" if shift else "<RIGHT>"

            elif key in ("UP",):
                token = "<UP>"

            elif key in ("DOWN",):
                token = "<DOWN>"

            elif key in ("HOME",):
                token = "<HOME>"

            elif key in ("END",):
                token = "<END>"

            # accept both PAGEUP/PAGEDOWN and PGUP/PGDN names (input aliases normalize to PGUP/PGDN)
            elif key in ("PGUP", "PAGEUP"):
                token = "<PGUP>"

            elif key in ("PGDN", "PAGEDOWN"):
                token = "<PGDN>"

            # accept both DELETE and DEL; Brick expects <DEL>
            elif key in ("DEL", "DELETE"):
                token = "<DEL>"

            elif key in ("ESC", "ESCAPE"):
                token = "\x1b"

            elif key in ("ENTER", "RETURN"):
                token = "<SENTER>" if shift else "\n"

            elif key in ("TAB",):
                token = "\t"

            elif key in ("BACKSPACE", "BKSP"):
                token = "\b"

            if token is None:
                return

            KEYQUEUE.append(token)
            return

        # scroll event (mouse wheel)
        if op == "SCROLL":


            # ensure message is for this window
            wid = int(msg.get("winid", 0))
            if WINID and wid != WINID:
                return

            # WindowServer sends SCROLL only to its mapped focused window.
            # The directed record therefore repairs a stale local FOCUS cache.
            if not HASFOCUS:
                HASFOCUS = True
                DIRTY_PROMPT = True

            try:

                # read vertical scroll amount (wheel)
                dy = int(msg.get("dy", 0))

            except Exception:
                dy = 0

            try:
                scrollmods = msg.get("mods", {})
                if not isinstance(scrollmods, dict):
                    scrollmods = {}
                ctrl = bool(scrollmods.get("ctrl", CTRLHELD))
            except Exception:
                ctrl = CTRLHELD

            if dy and ctrl:
                # Positive wheel movement zooms in; negative zooms out.
                changefontmetrics(1 if dy > 0 else -1)

            # Accumulate ordinary wheel input and ease it into the viewport at
            # the display frame rate. Positive movement reveals older lines.
            elif dy and consoleactive():
                consolescroll(msg)

            elif dy:
                queuesmoothscroll(dy * SCROLLSTEP)

            return

        # pointer button event (for scrollbar)
        if op == "POINTER_BUTTON":


            wid = int(msg.get("winid", 0))
            if WINID and wid != WINID:
                return

            # WindowServer focuses a clicked window before queueing its button
            # record. Accept that ordered record as authoritative even when a
            # prior FOCUS notification was delayed or lost.
            if not HASFOCUS:
                HASFOCUS = True
                DIRTY_PROMPT = True

            try:
                if consoleactive():
                    consolepointerbutton(msg)
                else:
                    handlepointerbutton(msg)
            except Exception as e:
                guiprint(f'> pointer button handler error {e}', colour=ERRORCOLOUR)

            return

        # pointer motion event (for dragging scrollbar)
        if op == "POINTER_MOTION":


            wid = int(msg.get("winid", 0))
            if WINID and wid != WINID:
                return

            if not HASFOCUS:
                return

            try:
                if consoleactive():
                    consolepointermotion(msg)
                else:
                    handlepointermotion(msg)
            except Exception as e:
                guiprint(f'> pointer motion handler error {e}', colour=ERRORCOLOUR)

            return

    except Exception as e:

        # message handling error
        guiprint(f"> server message error {e}", colour=ERRORCOLOUR)


def termhandler(signum, frame):

    global RUNNING


    savehistory()


    RUNNING = False

def initwindowmode():

    global SOCK, WINID, BUF, SCREENW, SCREENH, WORKX, WORKY, WORKW, WORKH


    try:

        # get current process id
        pid = os.getpid()

    except Exception as e:

        # pid error
        guiprint(f'> error getting pid {e}', colour=ERRORCOLOUR)
        return

    try:

        # open window server socket
        sock = opensocket()

        SOCK = sock

    except ConnectionRefusedError:

        # window server not running
        guiprint(f'> window server connection refused', colour=ERRORCOLOUR)
        return

    except TimeoutError:

        # window server timeout
        guiprint(f'> window server connection timed out', colour=ERRORCOLOUR)
        return

    except Exception as e:

        # socket open error
        guiprint(f'> error opening window server socket {e}', colour=ERRORCOLOUR)
        return

    try:

        # introduce brick to window server
        sendline(sock, {"op": "HELLO"})

    except BrokenPipeError:

        # broken pipe on hello
        guiprint(f'> window server pipe closed', colour=ERRORCOLOUR)
        return

    except Exception as e:

        # hello send error
        guiprint(f'> error sending hello {e}', colour=ERRORCOLOUR)
        return

    try:

        # wait for WELCOME (newline-delimited json)
        buf = b""

        gotwelcome = False

        while True:

            data = sock.recv(4096)

            if not data:

                guiprint(f'> window server closed during welcome', colour=ERRORCOLOUR)
                return

            buf += data

            while True:

                idx = buf.find(b"\n")

                if idx == -1:
                    break

                raw = buf[:idx]

                buf = buf[idx + 1:]

                try:

                    txt = raw.decode("utf-8", "ignore").strip()

                    if not txt:
                        continue

                    msg = json.loads(txt)

                    if str(msg.get("op", "")) != "WELCOME":
                        continue

                    try:

                        fb = msg.get("fb", {})

                        SCREENW = int(fb.get("w", 0))

                        SCREENH = int(fb.get("h", 0))

                        applyuiscale(SCREENW, SCREENH)

                    except Exception:

                        SCREENW = 0

                        SCREENH = 0

                    try:

                        work = msg.get("work", {})

                        WORKX = int(work.get("x", 0))

                        WORKY = int(work.get("y", 0))

                        WORKW = int(work.get("w", 0))

                        WORKH = int(work.get("h", 0))

                    except Exception:

                        WORKX = 0

                        WORKY = 0

                        WORKW = 0

                        WORKH = 0

                    try:

                        graphicsconfigure(msg.get("graphics", {}))

                    except Exception:

                        graphicsconfigure({})

                    gotwelcome = True

                    break

                except Exception:
                    continue

            if gotwelcome:
                break

    except TimeoutError:

        # welcome timeout
        guiprint(f'> timed out waiting for window server welcome', colour=ERRORCOLOUR)
        return

    except Exception as e:

        # welcome receive error
        guiprint(f'> error waiting for welcome {e}', colour=ERRORCOLOUR)
        return

    try:

        try:

            cwd = os.getcwd()

        except Exception:

            cwd = ""

        current = formatlocation(cwd)

        w, h, x, y = windowrequest()

        sendline(sock, {"op": "CREATE_WINDOW",
                        "w": int(w),
                        "h": int(h),
                        "x": int(x),
                        "y": int(y),
                        "title": "brick",
                        "role": "window",
                        "pid": pid,
                        "current": current,
                        "path": f'{BRICKPATH}'})

    except BrokenPipeError:

        # broken pipe on create window
        guiprint(f'> window server pipe closed', colour=ERRORCOLOUR)

        return

    except Exception as e:

        # create window send error
        guiprint(f'> error requesting window {e}', colour=ERRORCOLOUR)

        return

    bufpath = None

    winid = None

    try:

        # wait for WINDOW_CREATED
        while True:

            data = sock.recv(4096)

            if not data:

                guiprint(f'> window server closed during window create', colour=ERRORCOLOUR)
                return

            text = data.decode("utf-8", "ignore")

            if "WINDOW_CREATED" in text:

                msg = json.loads(text.strip())

                bufpath = msg.get("buffer", None)
                winid = msg.get("winid", None)

                break

    except json.JSONDecodeError:

        # bad json from window server
        guiprint(f'> window server sent invalid json for window create', colour=ERRORCOLOUR)
        return

    except TimeoutError:

        # create timeout
        guiprint(f'> timed out waiting for window created', colour=ERRORCOLOUR)
        return

    except Exception as e:

        # create receive error
        guiprint(f'> error waiting for window created {e}', colour=ERRORCOLOUR)
        return


    try:

        # validate window id and buffer path
        if winid is None:

            guiprint(f'> window server did not provide winid', colour=ERRORCOLOUR)
            return

        if bufpath is None:

            guiprint(f'> window server did not provide buffer path', colour=ERRORCOLOUR)
            return

        WINID = int(winid)

        BUF = str(bufpath)

    except Exception as e:

        # winid/buf parse error
        guiprint(f'> invalid window create response {e}', colour=ERRORCOLOUR)
        return


    try:

        # map it
        sendline(sock, {"op": "MAP", "winid": WINID})

    except BrokenPipeError:

        # broken pipe on map
        guiprint(f'> window server pipe closed', colour=ERRORCOLOUR)
        return

    except Exception as e:

        # map send error
        guiprint(f'> error mapping window {e}', colour=ERRORCOLOUR)
        return


    try:

        # register socket events
        initsocketevents(sock)

        # Keep display-derived layout and typography in step with framebuffer
        # changes.  The WELCOME payload only describes the launch resolution;
        # future FB_SIZE and WORK_AREA messages require an explicit subscription.
        sendline(sock, {"op": "SUBSCRIBE", "types": ["fbsize", "workarea"]})

    except Exception as e:

        # socket events init error
        guiprint(f'> error initialising socket events {e}', colour=ERRORCOLOUR)
        return


    try:

        # initialise shared buffer backing store
        w, h, x, y = windowrequest()

        initbuffer(BUF, int(w), int(h))

    except FileNotFoundError:

        # buffer file missing
        guiprint(f'> window buffer not found', colour=ERRORCOLOUR)
        return

    except PermissionError:

        # cannot open buffer
        guiprint(f'> permission denied opening window buffer', colour=ERRORCOLOUR)
        return

    except Exception as e:

        # buffer init error
        guiprint(f'> error initialising window buffer {e}', colour=ERRORCOLOUR)
        return


def pollserver():


    # poll selector once, non-blocking
    events = SEL.select(0)
    if not events:
        return

    for key, mask in events:

        kind = key.data.get("kind") if isinstance(key.data, dict) else None

        if kind == "console":
            if mask & selectors.EVENT_WRITE:
                consoleflushwrite()
            if mask & selectors.EVENT_READ:
                consoleconsume(key.fileobj)
            continue

        if kind != "server":
            continue

        if mask & selectors.EVENT_WRITE:

            if not flushwindowoutput(key.fileobj):
                graphicsdisable("window output failed", clear=False)

        if not (mask & selectors.EVENT_READ):
            continue

        try:

            received = 0
            chunks = []
            closed = False

            while received < 256 * 1024:

                try:
                    data = key.fileobj.recv(
                        min(65536, (256 * 1024) - received)
                    )
                except BlockingIOError:
                    break

                if not data:
                    closed = True
                    break

                chunks.append(data)
                received += len(data)

            # buffer and split by newline
            global INBUF
            if chunks:
                INBUF += b"".join(chunks)

            messages = []

            while True:

                idx = INBUF.find(b"\n")
                if idx == -1:
                    break

                raw = INBUF[:idx]
                INBUF = INBUF[idx + 1:]

                try:
                    txt = raw.decode("utf-8", "ignore")
                    if not txt.strip():
                        continue
                    msg = json.loads(txt)
                    messages.append(msg)
                except Exception:
                    continue

            filtered = []
            pendingmotion = None

            for msg in messages:

                if str(msg.get("op", "")) == "POINTER_MOTION":
                    pendingmotion = msg
                    continue

                if pendingmotion is not None:
                    filtered.append(pendingmotion)
                    pendingmotion = None

                filtered.append(msg)

            if pendingmotion is not None:
                filtered.append(pendingmotion)

            for msg in filtered:
                handleservermsg(msg)

            if closed:
                try:
                    SEL.unregister(key.fileobj)
                except Exception:
                    pass
                return

        except BlockingIOError:
            pass

        except Exception:
            pass


def onresized(msg):

    global RESIZEPENDINGW, RESIZEPENDINGH, RESIZEPENDINGAT

    try:

        # read new geometry
        w = int(msg.get("w", 0))

        h = int(msg.get("h", 0))

        if w <= 0 or h <= 0:
            return

        if RESIZEPENDINGW <= 0 and RESIZEPENDINGH <= 0 and RESIZEAPPLIEDW == w and RESIZEAPPLIEDH == h:
            return

        firstresize = RESIZEPENDINGW <= 0 or RESIZEPENDINGH <= 0

        # coalesce: keep only the most recent resize request
        RESIZEPENDINGW = w

        RESIZEPENDINGH = h

        RESIZEPENDINGAT = time.monotonic()

        if firstresize:
            graphicssuspend()

    except Exception as e:

        # resize handling error
        guiprint(f'> resize handler error {e}', colour=ERRORCOLOUR)


def applypendingresize():

    global RESIZEPENDINGW, RESIZEPENDINGH, RESIZEPENDINGAT
    global RESIZEAPPLIEDW, RESIZEAPPLIEDH
    global DIRTY_SCROLL, DIRTY_PROMPT

    if RESIZEPENDINGW <= 0 or RESIZEPENDINGH <= 0:
        return

    now = time.monotonic()

    if (now - RESIZEPENDINGAT) < RESIZEDELAY:
        return

    w = int(RESIZEPENDINGW)

    h = int(RESIZEPENDINGH)

    if RESIZEAPPLIEDW == w and RESIZEAPPLIEDH == h:

        RESIZEPENDINGW = 0

        RESIZEPENDINGH = 0

        if GRAPHICSSTATE.get("available") and not GRAPHICSSTATE.get("active"):
            GRAPHICSSTATE["need_submit"] = True
            DIRTY_SCROLL = True
            DIRTY_PROMPT = True

        return

    # consume pending
    RESIZEPENDINGW = 0

    RESIZEPENDINGH = 0

    # ensure any previous file-map is fully closed (graphics.close() doesn't handle it)

    # unmap old file buffer if present
    fmap = getattr(gfx, '_FILE_MAP', None)

    if fmap:

        try:

            fmap.close()

        except Exception:

            pass

        try:

            setattr(gfx, '_FILE_MAP', None)

        except Exception:

            pass

    # close old file descriptor if present
    ffd = getattr(gfx, '_FILE_FD', None)

    if ffd:

        try:

            os.close(ffd)

        except Exception:

            pass

        try:
            setattr(gfx, '_FILE_FD', None)

        except Exception:

            pass

    # reset file-buffer flag
    try:

        setattr(gfx, '_IS_FILE_BUFFER', False)

    except Exception:

        pass

    try:

        initbuffer(BUF, w, h)

    except Exception as e:

        guiprint(f'> graphics reinit error {e}', colour=ERRORCOLOUR)

        return

    RESIZEAPPLIEDW = w

    RESIZEAPPLIEDH = h

    # re-measure layout
    measurements()

    consolefit()

    if GRAPHICSSTATE.get("available"):
        GRAPHICSSTATE["need_submit"] = True
        GRAPHICSSTATE["damage"] = []
        managedmarkdamage(GRAPHICSSTATE, [0, 0, w, h], bounds=(w, h))
        graphicssyncstate()

    try:

        # clear whole client area
        clear(BACKGROUNDCOLOUR)

        # force header to repaint across new width
        global PREV_CWD
        PREV_CWD = None

        drawheader()

        drawcontent(cursor_on=False)

        presentbrick()

    except Exception as e:
        guiprint(f'> resize full redraw error {e}', colour=ERRORCOLOUR)

    DIRTY_SCROLL = True

    DIRTY_PROMPT = True


# session operation functions
def jobadd(cmdline, pids, state, mode, stdio):

    global JOBNEXT
    global JOBFORE
    global JOBLAST
    global JOBS

    try:

        # assign job id
        jobid = JOBNEXT
        JOBNEXT = JOBNEXT + 1

        # time now
        now = time.time()

        # create record
        JOBS[str(jobid)] = {
            'jobid': str(jobid),
            'pids': [int(x) for x in pids],
            'cmdline': str(cmdline),
            'state': str(state),
            'mode': str(mode),
            'stdio': str(stdio),
            'started': float(now),
            'ended': None,
            'exitcode': None
        }

        # set last job
        JOBLAST = str(jobid)

        # set foreground job if requested
        if mode == 'front':
            JOBFORE = str(jobid)

        return str(jobid)

    except Exception as e:

        # job add error
        guiprint(f'> error adding session operation {e}', colour=ERRORCOLOUR)
        return None


def procalive(pid):

    try:

        # validate pid
        pid = int(pid)
        if pid <= 0:
            return False

    except Exception:
        return False

    try:

        # probe process existence
        os.kill(pid, 0)

    except ProcessLookupError:

        # pid does not exist
        return False

    except PermissionError:

        # exists but no permission to signal
        return True

    except Exception:

        # unknown state treat as not alive
        return False

    return True


def jobreap():

    global JOBS
    global JOBFORE

    try:

        # snapshot job ids
        jobids = list(JOBS.keys())

    except Exception as e:

        # job list error
        guiprint(f'> error reading session operation {e}', colour=ERRORCOLOUR)
        return

    for jobid in jobids:

        try:

            # skip terminal jobs
            if JOBS[jobid].get('state') in ('done', 'completed', 'failed', 'killed'):
                continue

        except Exception as e:

            # job state read error
            guiprint(f'> error reading session operation state {e}', colour=ERRORCOLOUR)
            continue

        try:

            # read pids
            pids = JOBS[jobid].get('pids', [])

        except Exception:
            pids = []

        try:

            # if any pid alive, job still running
            anyalive = False

            for pid in pids:


                if procalive(pid):

                    anyalive = True
                    break

            if anyalive:
                continue

        except Exception as e:

            # liveness check error
            guiprint(f'> error checking session operation {jobid} {e}', colour=ERRORCOLOUR)
            continue

        try:

            # mark done
            exitcode = None
            completedstate = 'done'

            try:

                _, completed = operationdata()

                for pid in pids:

                    entry = completed.get(str(pid))

                    if entry:

                        exitcode = entry.get('exitcode')
                        completedstate = str(entry.get('state', 'done'))
                        break

            except Exception:
                pass

            JOBS[jobid]['state'] = completedstate

            JOBS[jobid]['ended'] = float(time.time())

            JOBS[jobid]['exitcode'] = exitcode

            if JOBFORE == str(jobid):
                JOBFORE = None

        except Exception as e:

            # mark done error
            guiprint(f'> error closing session operation {jobid} {e}', colour=ERRORCOLOUR)

    try:

        # prune old jobs
        jobprune()

    except Exception as e:

        # prune error
        guiprint(f'> error pruning session operations {e}', colour=ERRORCOLOUR)


def jobprune():

    global JOBS
    global JOBKEEP

    try:

        # if within limit
        if len(JOBS) <= int(JOBKEEP):
            return

        # collect done jobs with ended time
        done = []
        for jobid in JOBS:


            if JOBS[jobid].get('state') == 'done':
                ended = JOBS[jobid].get('ended')
                if ended is None:
                    ended = 0.0
                done.append((float(ended), str(jobid)))

        done.sort(key=lambda x: x[0])

        # delete oldest done jobs first
        while len(JOBS) > int(JOBKEEP) and done:

            victim = done.pop(0)[1]

            del JOBS[victim]
    except Exception as e:

        # job prune error
        guiprint(f'> error pruning {e}', colour=ERRORCOLOUR)


def jobkill(jobid):

    global JOBS

    try:

        # validate job
        if str(jobid) not in JOBS:
            guiprint(f'> session operation {jobid} not found', colour=ERRORCOLOUR)
            return

    except Exception as e:

        # job lookup error
        guiprint(f'> error looking up session operation {e}', colour=ERRORCOLOUR)
        return

    try:

        # kill each pid
        pids = JOBS[str(jobid)].get('pids', [])
        for pid in pids:

            try:

                # try terminate
                os.kill(int(pid), 15)

            except Exception:


                # fallback kill
                os.kill(int(pid), 9)

        guiprint(f'> killed session operation {jobid}', colour=TEXTCOLOUR)

    except Exception as e:

        # kill job error
        guiprint(f'> error killing session operation {jobid} {e}', colour=ERRORCOLOUR)


def kill(args):

    # reap first
    jobreap()
    if not args:
        guiprint('> enter %job or pid after kill', colour=TEXTCOLOUR)
        return

    target = str(args[0]).strip()

    if target.startswith('%'):

        # kill job
        jobid = target.replace('%', '').strip()
        jobkill(jobid)
        return

    try:

        # kill pid
        pid = int(target)

    except Exception:

        guiprint('> invalid pid', colour=ERRORCOLOUR)
        return

    try:

        # terminate then kill
        try:
            os.kill(pid, 15)
        except Exception:
            os.kill(pid, 9)

        guiprint(f'> killed pid {pid}', colour=TEXTCOLOUR)

    except Exception as e:

        # kill pid error
        guiprint(f'> error killing pid {pid} {e}', colour=ERRORCOLOUR)


# operations client functions
def opsrequest(payload, timeout=1.0):

    sock=None
    fileobj=None

    try:

        # connect socket
        sock=socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

        # prevent hangs if server is blocked/down
        sock.settimeout(max(0.1, float(timeout)))

        sock.connect(OPERATIONSSOCKET)

    except FileNotFoundError:

        # socket missing
        return None

    except TimeoutError:

        # socket connect timeout
        return None

    except Exception:

        return None

    try:

        # send request
        reqtext=json.dumps(payload) + '\n'
        sock.sendall(reqtext.encode('utf-8'))

    except TimeoutError:

        # send timeout
        sock.close()
        return None

    except Exception:

        sock.close()
        return None

    try:

        # read response
        fileobj=sock.makefile('rb')

        line=fileobj.readline()

    except TimeoutError:

        # read timeout
        sock.close()
        return None

    except Exception:

        sock.close()
        return None


    sock.close()

    if not line:
        return None

    try:

        # parse json
        text=line.decode('utf-8', errors='replace').strip()

        resp=json.loads(text)

        return resp

    except Exception:
        return None


def opsrequeststream(payload):

    sock=None
    fileobj=None

    try:

        # connect socket
        sock=socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(OPERATIONSSOCKET)

    except FileNotFoundError:

        # socket missing
        return None, None

    except ConnectionRefusedError:

        # connection refused
        return None, None

    except Exception:

        # other connect error
        return None, None

    try:

        # send json line
        text=json.dumps(payload)
        sock.sendall(text.encode('utf-8')+b'\n')

    except Exception:

        # send error
        sock.close()
        return None, None

    try:

        # keep socket open and return a file object for readline()
        fileobj=sock.makefile('rb')

    except Exception:

        # makefile error
        sock.close()
        return None, None

    return sock, fileobj


def missingpythonmodules(path):

    # Settings may install packages while this Brick process remains open.
    # Refresh import directory caches so a just-installed module is visible
    # immediately instead of prompting for it a second time.
    importlib.invalidate_caches()
    try:
        status = os.stat(path, follow_symlinks=True)
        if not stat.S_ISREG(status.st_mode) or status.st_size > 4 * 1024 * 1024:
            return []
        with open(path, 'r', encoding='utf-8') as stream:
            tree = ast.parse(stream.read(), filename=path)
    except (OSError, UnicodeError, SyntaxError):
        return []

    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(
                alias.name.partition('.')[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imports.add(node.module.partition('.')[0])

    scriptdirectory = os.path.dirname(os.path.abspath(path))
    missing = []
    for name in sorted(imports):
        if name in getattr(sys, 'stdlib_module_names', frozenset()):
            continue
        try:
            available = importlib.util.find_spec(name) is not None
        except (ImportError, AttributeError, ValueError):
            available = False
        if not available:
            try:
                available = importlib.machinery.PathFinder.find_spec(
                    name, [scriptdirectory]) is not None
            except (ImportError, AttributeError, ValueError):
                available = False
        if not available:
            missing.append(name)
    return missing


def preparepythonmodules(path):

    missing = missingpythonmodules(path)
    if not missing:
        return True
    # Keep the user-facing question entirely lowercase. Import identifiers are
    # retained separately for package-manager requests.
    names = ', '.join(missing).lower()
    writebrickvmteststatus(
        'python-missing-prompt', python_missing=missing,
        python_script=os.path.abspath(path))
    if HEADLESS:
        guiprint(f'> missing python modules {names}', colour=ERRORCOLOUR)
        return False
    while True:
        answer = arch.guiline(
            f'> missing python modules {names}. install them yes or no ')
        if answer in ('yes', 'no'):
            break
        guiprint('> answer yes or no in lowercase', colour=ERRORCOLOUR)
    writebrickvmteststatus(
        'python-missing-answer', python_missing=missing,
        python_answer=answer, python_script=os.path.abspath(path))
    if answer == 'no':
        guiprint('> python software launch cancelled', colour=TEXTCOLOUR)
        return False
    for name in missing:
        result = pythonmutationcall(
            'install_module', {'name': name}, timeout=900.0)
        if not result.get('ok'):
            guiprint(
                f'> could not install python module {name}',
                colour=ERRORCOLOUR)
            return False
    guiprint('> missing python modules installed', colour=TEXTCOLOUR)
    return True


def opsrun(path, args, name, log, user, mode):

    resp=None

    try:

        target = os.path.normpath(str(path))

        if target in RUNAPPLICATIONPATHS:
            payload = {
                'op': 'LAUNCH_CATALOGUE',
                'path': target,
                'args': [str(value) for value in (args or [])],
                'environment': {},
            }
        # Python files outside the immutable application catalogue are data,
        # not executable identities. Ask Operations to launch the measured
        # Brick entry in its no-window runner mode instead of using the retired
        # arbitrary-path RUN protocol.
        elif target.lower().endswith('.py') and (
            target == '/master' or target.startswith('/master/') or
            target == '/.ephemeral/volumes' or target.startswith('/.ephemeral/volumes/') or
            target == '/software' or target.startswith('/software/')
        ):
            payload = {
                'op': 'LAUNCH_CATALOGUE',
                'path': BRICKPATH,
                'args': ['--run-file', target] + [str(value) for value in (args or [])],
                'environment': {'BRICK_WINDOW': '0'},
            }
        else:
            # Non-catalogue executables remain fail-closed. Operations owns
            # executable identity and rejects this retired request.
            payload={
                'op':'RUN',
                'path':target,
                'args':list(args) if args else [],
                'name':name,
                'log':log,
                'user':user,
                'mode':mode,
                'stream':False,
            }

    except Exception:
        return None

    resp=opsrequest(payload)

    if not resp:
        return None

    try:

        if resp.get('status') != 'ok':
            return None

        return int(resp.get('pid'))

    except Exception:
        return None


def opsrunstream(path, args, name, log, user):

    sock=None
    fileobj=None

    try:

        payload={
            'op':'RUN',
            'path':path,
            'args':list(args) if args else [],
            'name':name,
            'log':log,
            'user':user,
            'mode':'front',
            'stream':True,
        }

    except Exception:
        return None, None, None

    sock, fileobj = opsrequeststream(payload)

    if not sock or not fileobj:
        return None, None, None

    try:

        # read started line
        line = fileobj.readline()

        if not line:
            raise Exception('no started frame')

        text = line.decode('utf-8', errors='replace').strip()

        started = json.loads(text)

        if started.get('status') != 'ok':
            raise Exception('run failed')

        pid = int(started.get('pid'))

        return pid, sock, fileobj

    except Exception:

        if fileobj:
            fileobj.close()
        if sock:
            sock.close()
        return None, None, None


def opsregisterpid(pid, name, script, log, user, mode):

    resp=None

    try:

        payload={
            'op':'REGISTER_PID',
            'pid':int(pid),
            'name':name,
            'script':script,
            'log':log,
            'user':user,
            'mode':mode
        }

    except Exception:
        return False

    resp=opsrequest(payload)

    if not resp:
        return False

    try:

        return resp.get('status') == 'ok'

    except Exception:
        return False


def opscompletepid(pid, exitcode):

    try:
        response = opsrequest({
            'op': 'COMPLETE_PID',
            'pid': int(pid),
            'exitcode': int(exitcode),
        })
        return bool(response and response.get('status') == 'ok')
    except Exception:
        return False


def opslistrequest(resources=False):

    response = opsrequest({'op': 'LIST', 'resources': bool(resources)})

    if not response or response.get('status') != 'ok':
        return None

    return response


def opskill(pid, force=False):

    try:

        response = opsrequest({'op': 'KILL', 'pid': int(pid), 'force': bool(force)})

        return bool(response and response.get('status') == 'ok' and response.get('killed'))

    except Exception:
        return False


def opswait(pid, timeout=60.0):

    try:

        response = opsrequest(
            {'op': 'WAIT', 'pid': int(pid), 'timeout': float(timeout)},
            timeout=max(1.0, float(timeout) + 1.0),
        )

        if not response:
            return None

        return response

    except Exception:
        return None


def operationdata(resources=False):

    response = opslistrequest(resources=resources)

    if response is None:
        return {}, {}

    operations = response.get('operations', {})
    completed = response.get('completed', {})

    if not isinstance(operations, dict):
        operations = {}

    if not isinstance(completed, dict):
        completed = {}

    return operations, completed


def operationmatches(target, operations):

    exact = []
    partial = []
    requested = str(target).strip().casefold()

    for pid, info in operations.items():

        try:

            name = str(info.get('name', ''))
            script = str(info.get('script', ''))
            base = os.path.basename(script)
            values = [name, script, base, os.path.splitext(base)[0]]

            if any(requested == value.casefold() for value in values if value):
                exact.append((str(pid), info))
                continue

            command = ' '.join([script] + [str(value) for value in info.get('args', [])])

            if requested and any(requested in value.casefold() for value in values + [command] if value):
                partial.append((str(pid), info))

        except Exception:
            continue

    return exact if exact else partial


def operationtargets(args, includecompleted=False):

    try:

        tokens = [str(arg) for arg in (args or [])]
        force = False

        if tokens and tokens[-1].lower() == 'force':

            force = True
            tokens = tokens[:-1]

        target = ' '.join(tokens).strip()

    except Exception:
        return [], False, ''

    if not target:
        return [], force, ''

    if target.startswith('%'):

        order = target[1:].strip()

        try:

            record = JOBS.get(str(int(order)))

            if not record:
                return [], force, target

            operations, completed = operationdata()
            found = []

            for pid in record.get('pids', []):

                info = operations.get(str(pid))

                if info is None and includecompleted:
                    info = completed.get(str(pid))

                if info is not None:
                    found.append((str(pid), info))

            return found, force, target

        except Exception:
            return [], force, target

    operations, completed = operationdata()
    choices = dict(operations)

    if includecompleted:

        for pid, info in completed.items():
            choices.setdefault(str(pid), info)

    if target.isdigit():

        info = choices.get(str(int(target)))

        if info is None:
            return [], force, target

        return [(str(int(target)), info)], force, target

    matches = operationmatches(target, operations)

    if not matches and includecompleted:
        matches = operationmatches(target, completed)

    return matches, force, target


def operationallowed(pid, info):

    try:

        script = str(info.get('script', '')).strip()

        if not script:
            return False

        return arch.check(script)

    except Exception:
        return False


def logtail(logpath, pid, stoppable=False):

    try:

        # normalise inputs
        logpath = str(logpath)

        pid = int(pid)

    except Exception:

        # invalid inputs
        guiprint('> invalid log tail parameters', colour=ERRORCOLOUR)
        return

    f = None

    pos = 0

    opened = False

    start = float(time.time())

    try:

        # capture start offset so we do not replay old log content
        if os.path.exists(logpath):
            pos = int(os.path.getsize(logpath))

    except Exception:
        pos = 0

    while True:

        try:

            # if process ended before log exists, do not hang forever
            if not procalive(pid) and not opened:

                try:

                    # allow short grace period for log creation
                    if float(time.time()) - start > 0.5:
                        break

                except Exception:
                    break

        except Exception:
            break

        try:

            # stop if process ended and we already opened the log at least once
            if not procalive(pid) and opened:
                break

        except Exception:
            break

        if not f:

            try:

                # try open log
                f = open(logpath, 'rb')

                opened = True

            except FileNotFoundError:

                # log not created yet
                time.sleep(0.05)
                continue

            except PermissionError:

                # cannot read log
                guiprint('> permission denied reading log', colour=ERRORCOLOUR)
                return 1

            except Exception as e:

                # other open error
                guiprint(f'> error opening log {e}', colour=ERRORCOLOUR)
                return 1


        # seek to last read position
        f.seek(pos)

        try:

            # read new bytes
            data = f.read()

        except Exception:
            data = b''

        if data:


            # update cursor
            pos = f.tell()

            try:

                # decode and print linewise
                text = data.decode('utf-8', errors='replace')

                for line in text.splitlines():
                    guiprint(line, colour=TEXTCOLOUR)

            except Exception as e:

                # decode/print error
                guiprint(f'> error decoding log {e}', colour=ERRORCOLOUR)

        else:

            # nothing new yet
            time.sleep(0.05)

    if f:
        f.close()

    # final flush after exit
    try:
        f = open(logpath, 'rb')
    except Exception:
        return 0

    f.seek(pos)

    data = f.read()

    if data:

        text = data.decode('utf-8', errors='replace')

        for line in text.splitlines():
            guiprint(line, colour=TEXTCOLOUR)

    f.close()
    return 0


def stopfore(pid):

    try:

        pid = int(pid)

    except Exception:

        return False

    guiprint('> stopping...', colour=TEXTCOLOUR)

    try:

        # graceful stop first
        os.kill(pid, 15)

    except PermissionError:

        guiprint('> permission denied stopping operation', colour=ERRORCOLOUR)
        return False

    except ProcessLookupError:

        guiprint('> already stopped', colour=TEXTCOLOUR)
        return True

    except Exception as e:

        guiprint(f'> error stopping operation {e}', colour=ERRORCOLOUR)
        return False

    # brief grace, then force if needed
    t0 = time.time()

    while procalive(pid):

        if time.time() - t0 > 0.5:
            break

        time.sleep(0.01)

    if procalive(pid):

        try:
            os.kill(pid, 9)
        except Exception:
            pass

    guiprint('> stopped', colour=TEXTCOLOUR)

    return True


def opsstreamframes(pid, sock, fileobj):

    global DIRTY_SCROLL, DIRTY_PROMPT

    sel = None

    exitcode = None

    try:

        pid = int(pid)

    except Exception:

        pid = None

    try:

        sel = selectors.DefaultSelector()

    except Exception:

        sel = None

    try:

        if sel and sock:
            sel.register(sock, selectors.EVENT_READ, data='stream')

    except Exception:
        sel = None

    try:

        while True:

            # check ctrl-s while streaming

            for ch in pollchars(timeout_ms=0):

                if ch == STOPKEY or ch == "<STOP>":

                    try:
                        if not playbackcommand('stop'):

                            stopfore(pid)

                    except Exception:
                        pass

            if SOCK:
                pollserver()
            if sel:

                try:
                    events = sel.select(timeout=0.05)
                except Exception:
                    events = []

                if not events:

                    # if process is gone, still keep draining until exit frame/close
                    if pid is not None and not procalive(pid):
                        pass
                    continue

            # read one line frame (non-blocking behaviour via select)
            try:

                line = fileobj.readline()

            except Exception:

                break

            if not line:
                break

            text = line.decode('utf-8', errors='replace').strip()

            if not text:
                continue

            msg = json.loads(text)

            try:

                mtype = msg.get('type')

            except Exception:
                mtype = None

            if mtype == 'out':

                didprint = False
                didupdate = False


                data = msg.get('data', '')

                if data is None:
                    data = ''

                data = str(data)

                data = data.replace('\r\n', '\n').replace('\r', '\n')

                for s in data.splitlines():

                    if playbackstatusline(s):

                        didupdate = True

                    elif playbacksuppressline(s):

                        didupdate = True

                    else:

                        guiprint(s, colour=TEXTCOLOUR)
                        didprint = True

                if didprint or didupdate:


                    DIRTY_SCROLL = True
                    DIRTY_PROMPT = True

                    drawcontent(cursor_on=False)

                    if SOCK:
                        pollserver()

                    presentbrick()

                continue

            if mtype == 'exit':

                try:

                    exitcode = int(msg.get('code'))

                except Exception:

                    exitcode = None


                DIRTY_SCROLL = True
                DIRTY_PROMPT = True

                drawcontent(True)

                if SOCK:
                    pollserver()

                presentbrick()

                break

    finally:

        if sel and sock:

            try:

                sel.unregister(sock)

            except Exception:

                pass

        if fileobj:
            fileobj.close()
        if sock:
            sock.close()

    return exitcode


def streamproc(p, stoppable=False):

    sel=None

    try:

        # build selector
        sel=selectors.DefaultSelector()

    except Exception:
        sel=None

    # register stdout
    if sel and p.stdout:
        sel.register(p.stdout, selectors.EVENT_READ, data='out')

    # register stderr
    if sel and p.stderr:
        sel.register(p.stderr, selectors.EVENT_READ, data='err')

    if not sel:

        # fallback stdout
        if p.stdout:
            for line in iter(p.stdout.readline, b''):
                try:
                    text=line.decode('utf-8', errors='replace').rstrip('\n')
                    if text:
                        guiprint(text, colour=TEXTCOLOUR)
                except Exception as e:
                    guiprint(f'> error decoding output {e}', colour=ERRORCOLOUR)

        # fallback stderr
        if p.stderr:
            for line in iter(p.stderr.readline, b''):
                try:
                    text=line.decode('utf-8', errors='replace').rstrip('\n')
                    if text:
                        guiprint(f'> {text}', colour=ERRORCOLOUR)
                except Exception as e:
                    guiprint(f'> error decoding errors {e}', colour=ERRORCOLOUR)

        try:
            return int(p.wait())
        except Exception:
            return 1

    while True:

        if stoppable:

            try:

                for ch in pollchars(timeout_ms=0):

                    if ch == STOPKEY or ch == '<STOP>':

                        stopfore(p.pid)
                        stoppable = False
                        break

            except Exception:
                pass

        # stop when process ended and no fds registered
        if p.poll() is not None:
            if not sel.get_map():
                break

        try:

            # wait for output
            events=sel.select(timeout=0.1)

        except Exception:
            events=[]

        if not events:

            # if ended and nothing ready, loop again to drain
            if p.poll() is not None:
                pass

        for key, _ in events:

            data=key.data
            fd=key.fileobj

            try:

                # read one line
                line=fd.readline()

            except Exception:
                line=b''

            if not line:

                sel.unregister(fd)
                continue

            if data == 'out':

                try:
                    text=line.decode('utf-8', errors='replace').rstrip('\n')
                    if text:
                        guiprint(text, colour=TEXTCOLOUR)

                except Exception as e:
                    guiprint(f'> error decoding output {e}', colour=ERRORCOLOUR)

            elif data == 'err':

                try:
                    text=line.decode('utf-8', errors='replace').rstrip('\n')
                    if text:
                        guiprint(f'> {text}', colour=ERRORCOLOUR)

                except Exception as e:
                    guiprint(f'> error decoding errors {e}', colour=ERRORCOLOUR)

    try:
        return int(p.wait())
    except Exception:
        return 1


# print functions
def appendline(s):

    global DIRTY_SCROLL, SCROLLOFF

    try:

        style = None

        if isinstance(s, tuple) and len(s) == 2:

            rawtext, given = s

            try:

                text = str(rawtext)

            except Exception:

                text = '<error>'

            try:

                if not isinstance(given, dict):

                    given = {}

                fg = given.get('colour', given.get('color'))

                style = {
                    'colour': normalisecolour(fg),
                    'bg': normalisecolour(given.get('bg')),
                    'bold': bool(given.get('bold', False)),
                    'underline': bool(given.get('underline', False)),
                    'italic': bool(given.get('italic', False)),
                    'playback': given.get('playback'),
                    'playback_row': given.get('playback_row'),
                }

            except Exception:

                style = None

        else:

            try:

                text = str(s)

            except Exception:

                text = '<error>'

            style = None

        was_full = (len(SCROLL) == SCROLL_MAX)

        pool = globals().setdefault('_STYLE_POOL', {})

        if style is not None:

            key = (style.get('colour'), style.get('bg'),
                   style.get('bold'), style.get('underline'), style.get('italic'),
                   style.get('playback'), style.get('playback_row'))

            style = pool.setdefault(key, style)

        SCROLL.append(text)

        STYLES.append(style)

        if was_full:
            if SCROLLOFF > 0:
                SCROLLOFF = max(0, SCROLLOFF - 1)

        DIRTY_SCROLL = True

    except Exception as e:

        SCROLL.append(f'> error appending line {e}')

        STYLES.append(None)

        DIRTY_SCROLL = True


def graphicssyncstate():

    global GRAPHICSCAPS, GRAPHICSAVAILABLE, GRAPHICSACTIVE, GRAPHICSPENDING
    global GRAPHICSPENDINGAT, GRAPHICSNEEDSUBMIT, GRAPHICSLIMIT, GRAPHICSTEXTLIMIT
    global GRAPHICSFAILURE, GRAPHICSERRORS, GRAPHICSFRAMES, GRAPHICSMAXCOMMANDS
    global GRAPHICSLASTCOMMANDS

    GRAPHICSCAPS = dict(GRAPHICSSTATE.get("capabilities", {}))
    GRAPHICSAVAILABLE = bool(GRAPHICSSTATE.get("available", False))
    GRAPHICSACTIVE = bool(GRAPHICSSTATE.get("active", False))
    GRAPHICSPENDING = bool(GRAPHICSSTATE.get("pending", False))
    GRAPHICSPENDINGAT = float(GRAPHICSSTATE.get("pending_at", 0.0))
    GRAPHICSNEEDSUBMIT = bool(GRAPHICSSTATE.get("need_submit", False))
    GRAPHICSLIMIT = int(GRAPHICSSTATE.get("command_limit", 0))
    GRAPHICSTEXTLIMIT = int(GRAPHICSSTATE.get("text_limit", 1024))
    GRAPHICSFAILURE = str(GRAPHICSSTATE.get("failure", ""))
    GRAPHICSERRORS = int(GRAPHICSSTATE.get("errors", 0))
    GRAPHICSFRAMES = int(GRAPHICSSTATE.get("frames", 0))
    GRAPHICSMAXCOMMANDS = int(GRAPHICSSTATE.get("maximum_commands", 0))
    GRAPHICSLASTCOMMANDS = int(GRAPHICSSTATE.get("last_commands", 0))


def graphicsconfigure(capabilities):

    managedconfigure(
        GRAPHICSSTATE,
        capabilities,
        required=("rectangle", "text"),
        cpu=GRAPHICSCPUOVERRIDE or not os.path.isfile(FONTREG),
    )
    graphicssyncstate()


def graphicsdamage():

    try:

        width = max(1, int(getattr(gfx, "_xres", 1)))
        height = max(1, int(getattr(gfx, "_yres", 1)))

        if SOCK and WINID:
            sendline(SOCK, {"op": "DAMAGE", "winid": WINID, "rect": [0, 0, width, height]})

    except Exception:
        pass


def graphicsrestorecpu():

    global DIRTY_SCROLL, DIRTY_PROMPT

    try:

        DIRTY_SCROLL = True
        DIRTY_PROMPT = True
        drawheader()
        drawcontent(GRAPHICSCURSORON)
        presentbrick()
        return True

    except Exception as e:

        try:
            print(formatlog('brick', f'error restoring cpu graphics {e}'))
        except Exception:
            pass

        graphicsdamage()
        return False


def graphicsdisable(reason, clear=True):

    global GRAPHICSSCENE

    if manageddisable(GRAPHICSSTATE, reason):
        GRAPHICSSCENE = []
        graphicssyncstate()
        return True
    GRAPHICSSCENE = []

    try:

        if clear and SOCK and WINID:
            sendline(SOCK, {"op": "GRAPHICS_CLEAR", "winid": WINID, "reason": str(reason)[:256]})

    except Exception:
        pass

    graphicssyncstate()
    graphicsrestorecpu()
    return False


def graphicssuspend():

    global GRAPHICSSCENE

    if not GRAPHICSSTATE.get("available"):
        return

    # Keep the last committed retained scene visible while a resize settles.
    # Windowserver clips that scene to the current client rectangle, and the
    # replacement scene is submitted atomically after the backing buffer has
    # been reopened at the final size.  Clearing here briefly selects the CPU
    # surface and permits a late clear acknowledgement to discard the rebuilt
    # scene during rapid maximise/restore sequences.
    GRAPHICSSCENE = []
    graphicssyncstate()


def graphicscommitted(msg):

    try:

        if WINID and int(msg.get("winid", 0)) != int(WINID):
            return

    except Exception:
        return

    managedresponse(GRAPHICSSTATE, msg)
    graphicssyncstate()

    if not GRAPHICSAVAILABLE:
        graphicsrestorecpu()


def graphicscleared(msg):

    try:

        if WINID and int(msg.get("winid", 0)) != int(WINID):
            return

    except Exception:
        return

    managedresponse(GRAPHICSSTATE, msg)
    graphicssyncstate()


def graphicsfont(bold=False, semibold=False):

    if bold and os.path.isfile(FONTBOLD):
        return FONTBOLD

    if semibold and os.path.isfile(FONTSEMIBOLD):
        return FONTSEMIBOLD

    return FONTREG


def graphicstexty(y, fontpath):

    try:

        face = gfx.getttfface(fontpath)

        if face is None:
            return int(y)

        face.set_pixel_sizes(0, FONTSIZE)
        ascender = int(face.size.ascender >> 6)
        return int(y) + int(FONTSIZE) - ascender

    except Exception:
        return int(y)


def graphicsclip(clip, width, height):

    try:

        x, y, w, h = [int(value) for value in clip]
        x2 = min(int(width), x + w)
        y2 = min(int(height), y + h)
        x = max(0, x)
        y = max(0, y)
        w = x2 - x
        h = y2 - y

        if w < 1 or h < 1:
            return None

        return [x, y, w, h]

    except Exception:
        return None


def graphicsrect(commands, x, y, width, height, colour, clip):

    try:

        x = int(x)
        y = int(y)
        width = int(width)
        height = int(height)
        clipx, clipy, clipwidth, clipheight = [int(value) for value in clip]

        if width < 1 or height < 1:
            return

        left = max(x, clipx)
        top = max(y, clipy)
        right = min(x + width, clipx + clipwidth)
        bottom = min(y + height, clipy + clipheight)

        if right <= left or bottom <= top:
            return

        commands.append({
            "kind": "rectangle",
            "rect": [left, top, right - left, bottom - top],
            "color": int(colour),
            "clip": list(clip),
        })

    except Exception:
        pass


def graphicstext(commands, x, y, text, colour, fontpath, clip):

    try:

        text = str(text)

        if not text:
            return

        x = int(x)
        y = int(y)
        clipx, clipy, clipw, cliph = [int(value) for value in clip]
        right = clipx + clipw
        cell = max(1, int(SPACEW))
        start = 0

        if x >= right:
            return

        if x < clipx:
            start = max(0, int(math.ceil((clipx - x) / float(cell))))

        end = min(len(text), max(start, int(math.ceil((right - x) / float(cell)))))

        if end <= start:
            return

        visible = text[start:end]
        drawx = x + start * cell
        limit = max(1, int(GRAPHICSTEXTLIMIT))
        offset = 0

        while offset < len(visible):

            chunk = visible[offset:offset + limit]

            if chunk:

                commands.append({
                    "kind": "text",
                    "x": int(drawx + offset * cell),
                    "y": graphicstexty(y, fontpath),
                    "text": chunk,
                    "size": int(FONTSIZE),
                    "font": str(fontpath),
                    "color": int(colour),
                    "clip": list(clip),
                })

            offset += len(chunk)

    except Exception:
        pass


def graphicstextselection(commands, x, y, text, selstart, selend, colour, fontpath, clip):

    try:

        text = str(text)
        start = max(0, min(len(text), int(selstart)))
        end = max(0, min(len(text), int(selend)))

        if end < start:
            start, end = end, start

        if end <= start:

            graphicstext(commands, x, y, text, colour, fontpath, clip)
            return

        pre = text[:start]
        middle = text[start:end]
        suffix = text[end:]
        cell = max(1, int(SPACEW))

        if pre:
            graphicstext(commands, x, y, pre, colour, fontpath, clip)

        selectionx = int(x) + start * cell
        graphicsrect(commands, selectionx, y, (end - start) * cell, LINEHEIGHT, colour, clip)

        if middle:
            graphicstext(commands, selectionx, y, middle, BACKGROUNDCOLOUR, fontpath, clip)

        if suffix:
            graphicstext(commands, int(x) + end * cell, y, suffix, colour, fontpath, clip)

    except Exception:
        graphicstext(commands, x, y, text, colour, fontpath, clip)


def promptstylespans(text):

    text = str(text)
    length = len(text)
    boldspans = []
    semispans = []

    try:

        segments = splitchainpos(text) if ";" in text else [(text, 0)]

        for segment, offset in segments:

            start, end = directivebounds(segment)

            if start is not None and end is not None and end > start:
                boldspans.append((offset + start, offset + end))

            for start, end in semiboldbounds(segment):

                if start is not None and end is not None and end > start:
                    semispans.append((offset + start, offset + end))

    except Exception:
        pass

    cuts = {0, length}

    for start, end in boldspans + semispans:

        cuts.add(max(0, min(length, int(start))))
        cuts.add(max(0, min(length, int(end))))

    cuts = sorted(cuts)
    output = []

    for index in range(len(cuts) - 1):

        start = cuts[index]
        end = cuts[index + 1]

        if end <= start:
            continue

        bold = any(start >= left and end <= right for left, right in boldspans)
        semibold = not bold and any(start >= left and end <= right for left, right in semispans)
        output.append((start, end, bold, semibold))

    return output


def graphicspromptspans(text):

    return [
        (start, end, graphicsfont(bold=bold, semibold=semibold))
        for start, end, bold, semibold in promptstylespans(text)
    ]


def graphicsstyledprompt(commands, x, y, text, selstart, selend, clip, source=None, offset=0):

    text = str(text)
    source = text if source is None else str(source)
    offset = max(0, int(offset))
    limit = offset + len(text)

    for spanstart, spanend, fontpath in graphicspromptspans(source):

        start = max(offset, spanstart)
        end = min(limit, spanend)

        if end <= start:
            continue

        segment = source[start:end]
        segmentx = int(x) + (start - offset) * max(1, int(SPACEW))

        if selstart is not None and selend is not None and int(selend) > start and int(selstart) < end:

            localstart = max(0, int(selstart) - start)
            localend = min(len(segment), int(selend) - start)
            graphicstextselection(commands, segmentx, y, segment, localstart, localend, TEXTCOLOUR, fontpath, clip)

        else:
            graphicstext(commands, segmentx, y, segment, TEXTCOLOUR, fontpath, clip)


def graphicsbuildscrollbars(commands, clip):

    try:

        layout = contentlayout()
        rows = int(layout.get('rows', 0))
        total = int(layout.get('total', 0))

        if rows > 0 and total > rows:

            trackx, tracky, trackw, trackh = scrollbargeometry()
            thumbh = max(SCROLLBAR_MIN_THUMB, int(trackh * (rows / float(total))))
            thumbh = min(trackh, thumbh)
            maxoff = max(0, total - rows)
            offset = max(0, min(maxoff, SCROLLOFF))
            fraction = 1.0 if maxoff <= 0 else 1.0 - (offset / float(maxoff))
            thumby = int(tracky + fraction * max(0, trackh - thumbh))
            graphicsrect(commands, trackx, tracky, trackw, trackh, SCROLLBAR_BG, clip)
            graphicsrect(commands, trackx, thumby, trackw, thumbh, SCROLLBAR_THUMB, clip)

        if hscrollbarneeded():

            x, y, width, height = hscrollbargeometry()
            thumbx, thumby, thumbw, thumbh = hscrollthumbgeometry()
            graphicsrect(commands, x, y, width, height, SCROLLBAR_BG, clip)
            graphicsrect(commands, thumbx, thumby, thumbw, thumbh, SCROLLBAR_THUMB, clip)

    except Exception:
        pass


def viewlimits():

    screenwidth = max(1, int(getattr(gfx, '_xres', 1)))
    reserved = (LEFTPAD * 2) + SCROLLBAR_WIDTH + SCROLLBAR_MARGIN
    width = max(1, screenwidth - reserved)
    available = max(1, int(contentlayout().get('rows', 1)))
    rows = max(1, min(24, available - 1 if available > 1 else available))
    return width, max(1, rows * LINEHEIGHT)


def viewrun(source, output, width, height):

    if viewerrequest is None:
        raise ValueError('viewer software not found')

    return viewerrequest(source, output, width, height, LINEHEIGHT)


def viewdecode(source):

    global VIEWNEXT

    viewparent = os.path.dirname(VIEWROOT)
    os.makedirs(viewparent, mode=0o711, exist_ok=True)

    if os.path.islink(viewparent):
        raise ValueError('image surface parent directory cannot be a symbolic link')

    os.chmod(viewparent, 0o711)
    os.makedirs(VIEWROOT, mode=0o711, exist_ok=True)

    if os.path.islink(VIEWROOT):
        raise ValueError('image surface directory cannot be a symbolic link')

    os.chmod(VIEWROOT, 0o711)
    VIEWNEXT += 1
    identifier = VIEWNEXT
    output = os.path.join(VIEWROOT, f'image-{identifier}.bgra')
    maximumwidth, maximumheight = viewlimits()
    payload = viewrun(source, output, maximumwidth, maximumheight)
    sourcesize = list(payload.get('source_size', []))

    if len(sourcesize) != 2 or int(sourcesize[0]) < 1 or int(sourcesize[1]) < 1:
        raise ValueError('decoder did not report valid source dimensions')

    surfacesize = list(payload.get('surface_size', []))

    if len(surfacesize) != 2 or int(surfacesize[0]) < 1 or int(surfacesize[1]) < 1:
        raise ValueError('viewer did not report valid surface dimensions')

    width = int(surfacesize[0])
    height = int(surfacesize[1])

    if height % LINEHEIGHT != 0:
        raise ValueError('viewer did not align the inline image surface')

    rows = max(1, height // LINEHEIGHT)

    return {
        'id': identifier,
        'source': source,
        'path': output,
        'width': width,
        'height': height,
        'rows': rows,
        'format': str(payload.get('format', 'image')),
        'source_size': sourcesize,
        'content_rect': list(payload.get('content_rect', [0, 0, width, height])),
        'animated': bool(payload.get('animated', False)),
    }


def viewappend(image):

    global SCROLLOFF, DIRTY_SCROLL, DIRTY_PROMPT

    rows = max(1, int(image.get('rows', 1)))

    for row in range(rows):

        wasfull = len(SCROLL) == SCROLL_MAX
        SCROLL.append('')
        STYLES.append({
            'image': image,
            'image_row': row,
        })

        if wasfull and SCROLLOFF > 0:
            SCROLLOFF = max(0, SCROLLOFF - 1)

    DIRTY_SCROLL = True
    DIRTY_PROMPT = True


def viewblit(image, row, y, top, bottom):

    try:

        width = int(image.get('width', 0))
        height = int(image.get('height', 0))
        path = str(image.get('path', ''))
        anchor = int(y) - (int(row) * LINEHEIGHT)
        visibletop = max(int(top), anchor)
        visiblebottom = min(int(bottom), anchor + height)

        if width < 1 or height < 1 or visiblebottom <= visibletop or not os.path.isfile(path):
            return

        sourcey = visibletop - anchor
        blitfilepartfast(
            path,
            width,
            0,
            sourcey,
            width,
            visiblebottom - visibletop,
            LEFTPAD,
            visibletop,
            'BGRA32',
        )

    except Exception:
        pass


def viewcleanup():

    try:

        parent = os.path.realpath(os.path.dirname(VIEWROOT))

        if parent != '/.ephemeral/brick' or os.path.islink(VIEWROOT):
            return

        shutil.rmtree(VIEWROOT, ignore_errors=True)

    except Exception:
        pass


def playbackvideoplacement(rect):

    try:

        x, y, width, height = [int(value) for value in rect]
        frame = PLAYBACK.get('frame', {})
        sourcewidth = max(0, int(frame.get('width', 0)))
        sourceheight = max(0, int(frame.get('height', 0)))

    except Exception:

        return [0, 0, 0, 0]

    if width < 1 or height < 1 or sourcewidth < 1 or sourceheight < 1:

        return [0, 0, 0, 0]

    scale = min(width / float(sourcewidth), height / float(sourceheight))
    targetwidth = max(1, int(round(sourcewidth * scale)))
    targetheight = max(1, int(round(sourceheight * scale)))
    return [
        x + ((width - targetwidth) // 2),
        y + ((height - targetheight) // 2),
        targetwidth,
        targetheight,
    ]


def graphicsbuildplayback(commands, clip):

    geometry = playbackgeometry()

    if not geometry:

        return

    videobox = geometry.get('video', [0, 0, 0, 0])

    if videobox[2] > 0 and videobox[3] > 0:

        frameclip = geometry.get('clip', clip)
        graphicsrect(commands, videobox[0], videobox[1], videobox[2], videobox[3], BACKGROUNDCOLOUR, frameclip)
        frame = PLAYBACK.get('frame', {})
        path = str(frame.get('path', '') or '')
        sourcewidth = int(frame.get('width', 0) or 0)
        sourceheight = int(frame.get('height', 0) or 0)
        destination = playbackvideoplacement(videobox)

        if (
            destination[2] > 0
            and destination[3] > 0
            and sourcewidth > 0
            and sourceheight > 0
            and os.path.isfile(path)
        ):

            commands.append({
                'id': 'playback-video',
                'kind': 'image',
                'path': path,
                'source_width': sourcewidth,
                'source_height': sourceheight,
                'format': 'BGRA32',
                'rect': destination,
                'clip': list(frameclip),
            })

    stopx, stopy, stopw, stoph = geometry['stop']
    inset = max(2, stopw // 4)
    graphicsrect(
        commands,
        stopx + inset,
        stopy + inset,
        max(1, stopw - (inset * 2)),
        max(1, stoph - (inset * 2)),
        PLAYBACK_CONTROL_COLOUR,
        clip,
    )
    togglex, toggley, togglew, toggleh = geometry['toggle']
    state = str(PLAYBACK.get('state', 'playing'))

    if state != 'paused':

        barwidth = max(2, togglew // 5)
        gap = max(2, togglew // 5)
        left = togglex + max(1, (togglew - ((barwidth * 2) + gap)) // 2)
        graphicsrect(commands, left, toggley + 2, barwidth, max(1, toggleh - 4), PLAYBACK_CONTROL_COLOUR, clip)
        graphicsrect(commands, left + barwidth + gap, toggley + 2, barwidth, max(1, toggleh - 4), PLAYBACK_CONTROL_COLOUR, clip)

    else:

        trianglewidth = max(3, togglew - 4)

        for offset in range(trianglewidth):

            trim = int((offset / float(max(1, trianglewidth - 1))) * ((toggleh - 4) / 2.0))
            graphicsrect(
                commands,
                togglex + 2 + offset,
                toggley + 2 + trim,
                1,
                max(1, toggleh - 4 - (trim * 2)),
                PLAYBACK_CONTROL_COLOUR,
                clip,
            )

    trackx, tracky, trackw, trackh = geometry['track']
    graphicsrect(commands, trackx, tracky, trackw, trackh, PLAYBACK_TRACK_COLOUR, clip)
    thumbx, thumby, thumbw, thumbh = geometry['thumb']
    graphicsrect(commands, thumbx, thumby, thumbw, thumbh, PLAYBACK_CONTROL_COLOUR, clip)
    timex, timey, timetext = geometry['time']
    graphicstext(commands, timex, timey, timetext, TEXTCOLOUR, graphicsfont(), clip)


def graphicsbuildscene():

    commands = []
    width = max(1, int(getattr(gfx, "_xres", 1)))
    height = max(1, int(getattr(gfx, "_yres", 1)))
    clip = graphicsclip([0, 0, width, height], width, height)

    if clip is None:
        return commands

    graphicsrect(commands, 0, 0, width, height, BACKGROUNDCOLOUR, clip)

    headery = TOPBLANKLINES * LINEHEIGHT

    try:
        header = formatlocation(os.getcwd())

    except Exception:
        header = f"{DRIVENUMBER}/"

    graphicstext(commands, LEFTPAD, headery, header, TEXTCOLOUR, graphicsfont(), clip)

    if consoleactive():
        graphicsbuildconsole(commands, clip)
        return commands

    layout = contentlayout()
    x0 = int(layout.get("x0", LEFTPAD))
    y = int(layout.get("y0", CONTENT_TOP_Y))
    start = int(layout.get("start", 0))
    end = int(layout.get("end", 0))
    visiblerows = layout.get("visible_rows", [])
    promptyvalue = int(layout.get("prompty", y + ((end - start) * LINEHEIGHT)))
    contenttop = int(layout.get("top", y))
    contentclip = graphicsclip([0, contenttop, width, max(1, promptyvalue - contenttop)], width, height)
    renderedimages = set()

    for row in visiblerows:

        index, rowstart, rowend = row
        line = str(SCROLL[index])[rowstart:rowend]
        style = STYLES[index] if index < len(STYLES) else None
        colour = TEXTCOLOUR
        fontpath = graphicsfont()

        if isinstance(style, dict):

            image = style.get('image')

            if isinstance(image, dict):

                identifier = int(image.get('id', 0))

                if identifier not in renderedimages and contentclip is not None:

                    path = str(image.get('path', ''))
                    sourcewidth = int(image.get('width', 0))
                    sourceheight = int(image.get('height', 0))
                    row = int(style.get('image_row', 0))
                    anchory = y - (row * LINEHEIGHT)

                    if path and os.path.isfile(path) and sourcewidth > 0 and sourceheight > 0:
                        commands.append({
                            'kind': 'image',
                            'path': path,
                            'source_width': sourcewidth,
                            'source_height': sourceheight,
                            'format': 'BGRA32',
                            'rect': [LEFTPAD, anchory, sourcewidth, sourceheight],
                            'clip': list(contentclip),
                        })

                    renderedimages.add(identifier)

                y += LINEHEIGHT
                continue

            styledcolour = colourtoint(style.get("colour"))

            if styledcolour is not None:
                colour = styledcolour

            fontpath = graphicsfont(bold=bool(style.get("bold", False)))

        selectionstart = None
        selectionend = None

        if SELREGION == "content" and SELNORMAL is not None:

            try:

                (startline, startcolumn), (endline, endcolumn) = SELNORMAL

                if startline <= index <= endline:

                    logicalstart = startcolumn if index == startline else 0
                    logicalend = endcolumn if index == endline else len(SCROLL[index])
                    selectionstart = max(rowstart, logicalstart) - rowstart
                    selectionend = min(rowend, logicalend) - rowstart

                    if selectionend <= selectionstart:
                        selectionstart = None
                        selectionend = None

            except Exception:
                pass

        if selectionstart is not None and selectionend is not None:

            graphicstextselection(commands, x0, y, line, selectionstart, selectionend, colour, fontpath, clip)

        else:
            graphicstext(commands, x0, y, line, colour, fontpath, clip)

        y += LINEHEIGHT

    promptselectionstart = None
    promptselectionend = None

    if SELREGION == "prompt" and PROMPTSELNORMAL is not None:

        try:
            promptselectionstart, promptselectionend = PROMPTSELNORMAL

        except Exception:
            promptselectionstart = None
            promptselectionend = None

    promptrows = layout.get("prompt_rows", [(0, len(INPUTBUF), True)])
    lastinputx = LEFTPAD
    lastinputend = 0

    for promptrowindex, promptrow in enumerate(promptrows):

        inputstart, inputend, showprompt = promptrow
        rowy = promptyvalue + (promptrowindex * LINEHEIGHT)
        inputx = LEFTPAD

        if showprompt:
            graphicstext(commands, LEFTPAD, rowy, PROMPT, TEXTCOLOUR, graphicsfont(), clip)
            inputx += PROMPTW + SPACEW

        graphicsstyledprompt(
            commands,
            inputx,
            rowy,
            INPUTBUF[inputstart:inputend],
            promptselectionstart,
            promptselectionend,
            clip,
            source=INPUTBUF,
            offset=inputstart,
        )
        lastinputx = inputx
        lastinputend = inputend

    if promptselectionstart is None or promptselectionend is None:

        suggestion = suggestfromhistory(INPUTBUF, CURSORPOS)

        if suggestion:
            suggestiony = promptyvalue + ((len(promptrows) - 1) * LINEHEIGHT)
            graphicstext(
                commands,
                lastinputx + SPACEW * (lastinputend - promptrows[-1][0]),
                suggestiony,
                suggestion,
                SUGGESTCOLOUR,
                graphicsfont(),
                clip,
            )

    if GRAPHICSCURSORON:

        for promptrowindex, (inputstart, inputend, showprompt) in enumerate(promptrows):

            if CURSORPOS < inputend or promptrowindex == len(promptrows) - 1:
                cursorbase = LEFTPAD + (PROMPTW + SPACEW if showprompt else 0)
                cursorx = cursorbase + SPACEW * max(0, CURSORPOS - inputstart)
                cursory = promptyvalue + (promptrowindex * LINEHEIGHT)
                graphicsrect(commands, cursorx, cursory + CURSOR_Y_OFFSET, CURSORW, CURSORH, CURSORCOLOUR, clip)
                break

    graphicsbuildplayback(commands, clip)
    graphicsbuildscrollbars(commands, clip)
    return commands


def graphicspump():

    global GRAPHICSSCENE

    wasavailable = bool(GRAPHICSSTATE.get("available"))

    if not managedtick(GRAPHICSSTATE):

        if wasavailable and SOCK and WINID:
            sendline(SOCK, {"op": "GRAPHICS_CLEAR", "winid": WINID, "reason": str(GRAPHICSSTATE.get("failure", "managed graphics timeout"))[:256]})
            graphicsrestorecpu()

        graphicssyncstate()
        return False

    if not GRAPHICSSTATE.get("available") or not SOCK or not WINID:
        return False

    if GRAPHICSSTATE.get("pending") or not GRAPHICSSTATE.get("need_submit"):
        graphicssyncstate()
        return bool(GRAPHICSSTATE.get("active"))

    commands = graphicsbuildscene()

    if not commands or commands[0].get("kind") != "rectangle" or commands[0].get("rect") != [0, 0, int(getattr(gfx, "_xres", 1)), int(getattr(gfx, "_yres", 1))]:

        graphicsdisable("managed scene does not contain a complete background")
        return False

    beforeavailable = bool(GRAPHICSSTATE.get("available"))
    managedsubmit(GRAPHICSSTATE, lambda request: sendline(SOCK, request), WINID, commands)

    if beforeavailable and not GRAPHICSSTATE.get("available"):

        sendline(SOCK, {
            "op": "GRAPHICS_CLEAR",
            "winid": WINID,
            "reason": str(GRAPHICSSTATE.get("failure", "managed graphics submit failed"))[:256],
        })
        graphicsrestorecpu()

    if GRAPHICSSTATE.get("pending"):
        GRAPHICSSCENE = commands

    graphicssyncstate()
    return bool(GRAPHICSSTATE.get("active"))


def graphicspresent(dirty=None):

    if not GRAPHICSSTATE.get("available"):
        return False

    if dirty is not None:

        managedmarkdamage(
            GRAPHICSSTATE,
            dirty,
            bounds=(int(getattr(gfx, "_xres", 1)), int(getattr(gfx, "_yres", 1))),
        )

    else:
        GRAPHICSSTATE["need_submit"] = True

    graphicspump()
    graphicssyncstate()
    return bool(GRAPHICSSTATE.get("active"))


def presentbrick():

    global SOCK, WINID

    try:

        if GRAPHICSSTATE.get("active") and GRAPHICSSTATE.get("managed_only"):

            graphicspump()
            resetdirty()
            return

        # get dirty region from graphics
        dirty = getdirty()

        # check if region is valid
        if dirty:

            # present only the dirty area to frame buffer
            presentdirty(dirty[0], dirty[1], dirty[2], dirty[3])

            managed = graphicspresent(dirty)

            # handle window damage if running under window server
            if WINID and SOCK and not managed:

                # send damage packet
                sendline(SOCK, {
                    "op": "DAMAGE",
                    "winid": WINID,
                    "rect": [int(dirty[0]), int(dirty[1]), int(dirty[2]), int(dirty[3])]
                })

            # reset dirty tracking for next frame
            resetdirty()

    except Exception as e:

        # handle presentation errors
        print(formatlog('brick', f'error presenting frame {e}'))


def guiprint(*values, sep=' ', end='\n', file=None, flush=False, colour=None, bg=None, bold=False, underline=False, italic=False):

    global DIRECTIVEFAILED

    try:

        # record coloured directive failures without changing visible output
        if DIRECTIVEACTIVE and colour == ERRORCOLOUR:
            DIRECTIVEFAILED = True

    except Exception:
        pass

    try:

        # build text from values
        parts = []
        for v in values:
            try:
                parts.append(str(v))
            except Exception as e:
                parts.append(f'<error {e}>')

        # join with separator
        text = sep.join(parts)

        # apply end
        endstr = '' if end is None else end
        final = text + endstr

    except Exception as e:

        # error building text
        appendline(f'> error building print text {e}')
        return

    # write to a file stream if provided (mirror print)
    if file is not None:
        try:

            # write to stream
            file.write(final)

            # flush if requested
            if flush:
                file.flush()
        except Exception as e:

            # error writing to file
            appendline(f'> error writing to file {e}')
        return

    try:

        # normalise newlines
        s = final.replace('\r\n', '\n').replace('\r', '\n')

        # split into lines, preserving intended blanks inside the text
        lines = s.split('\n')

        # if final ends with a single newline, drop the trailing empty element
        if final.endswith('\n') and lines and lines[-1] == '':
            lines = lines[:-1]

        # build style if any styling provided
        style = None
        try:
            if colour is not None or bg is not None or bold or underline or italic:
                style = {
                    'colour': colour,
                    'bg': bg,
                    'bold': bool(bold),
                    'underline': bool(underline),
                    'italic': bool(italic),
                }
        except Exception:
            style = None

        # append each visual line to the GUI scroll
        for line in lines:

            # expand tabs for consistent spacing
            out = line.expandtabs(4)

            # choose append mode based on style
            if style is None:
                appendline(out)
                continue

            try:
                appendline((out, style))
            except Exception:
                appendline(out)
    except Exception as e:

        # gui print error
        appendline(f'> error printing lines {e}')


def normalisecolour(c):

    try:

        # empty value
        if c is None:
            return None

        # integer like 0xFF0000
        if isinstance(c, int):
            return f'#{c:06X}'

        # string normalisation
        s = str(c).strip()

        # strip leading markers
        if s.startswith('#'):
            s = s[1:]
        elif s.lower().startswith('0x'):
            s = s[2:]

        # ensure 6 hex digits
        s = (s.upper() + '000000')[:6]

        # validate hex
        int(s, 16)

        # return canonical
        return f'#{s}'

    except Exception:

        # invalid colour
        return None


def colourtoint(c):

    try:

        # empty colour
        if c is None:
            return None

        # already an integer
        if isinstance(c, int):
            return c & 0xFFFFFF

        # normalise string
        s = str(c).strip()

        # strip prefixes
        if s.startswith('#'):
            s = s[1:]
        elif s.lower().startswith('0x'):
            s = s[2:]

        # ensure 6 hex digits
        s = (s + '000000')[:6]

        # parse
        v = int(s, 16)
        return v & 0xFFFFFF

    except Exception:

        # invalid colour
        return None


# input functions
def initinput():

    global SOCK, WINID

    try:

        if SOCK and WINID is not None:

            return True

        ok = openkeyboard()

        if not ok:

            guiprint('> no keyboard available', colour=ERRORCOLOUR)

            return False

    except Exception as e:

        # input open error
        guiprint(f'> error opening keyboard {e}', colour=ERRORCOLOUR)

        return False

    return True


def stagepaste(raw):

    global INPUTBUF, CURSORPOS, MULTILINES, DIRTY_PROMPT

    try:

        text = str(raw).replace('\r\n', '\n').replace('\r', '\n')

        if '\n' not in text:
            return 0

        lines = [line.strip() for line in text.split('\n') if line.strip()]

        if not lines:
            return 0

        MULTILINES = list(lines[:-1])
        INPUTBUF = str(lines[-1])
        CURSORPOS = len(INPUTBUF)
        clearselection('prompt')
        DIRTY_PROMPT = True
        return len(lines)

    except Exception:
        return 0


def cancelpaste():

    global INPUTBUF, CURSORPOS, MULTILINES, DIRTY_PROMPT

    if not MULTILINES:
        return False

    MULTILINES = []
    INPUTBUF = ''
    CURSORPOS = 0
    clearselection('prompt')
    DIRTY_PROMPT = True
    return True


def pollchars(timeout_ms):

    global KEYQUEUE, SOCK, WINID

    try:

        if SOCK and WINID is not None:

            out = []

            try:

                if timeout_ms and timeout_ms > 0:
                    deadline = time.time() + (timeout_ms / 1000.0)

                else:
                    deadline = time.time()

            except Exception:
                deadline = time.time()

            while True:

                # pump windowserver so KEYQUEUE is filled
                if SOCK:
                    pollserver()

                if KEYQUEUE:

                    ch = KEYQUEUE.popleft()

                    out.append(ch)

                    continue

                if out:
                    break

                if timeout_ms <= 0:
                    break

                if time.time() >= deadline:
                    break

                time.sleep(0.001)

            return out

        chars = readchars(timeout_ms=timeout_ms)

        if chars is None:

            ch = getchar()

            return [ch] if ch else []

        return chars or []

    except Exception as e:

        # read error
        guiprint(f'> error reading keyboard {e}', colour=ERRORCOLOUR)

        return []


def handleinput(cursor_on):

    global INPUTBUF, CURSORPOS, MULTILINES, DIRTY_PROMPT, SELREGION, PROMPTSELEND, PROMPTSELANCHOR, PROMPTSELNORMAL, SOCK, WINID

    try:

        chars = pollchars(timeout_ms=16)

    except Exception as e:

        # poll chars error
        guiprint(f'> error polling input {e}', colour=ERRORCOLOUR)

        return False

    for ch in chars:

        if ch == '\x1b':

            if cancelpaste():
                guiprint('> pasted directives cancelled', colour=TEXTCOLOUR)

            continue

        if ch == '\t':


            completeonce()

            DIRTY_PROMPT = True
            continue

        if ch == "<SENTER>":

            try:

                line = INPUTBUF

            except Exception:

                line = ""

            # echo the line and move to a new continuation line (PowerShell-like)
            guiprint(f'{PROMPT} {line}', colour=TEXTCOLOUR)


            # store the line for later execution
            if line.strip():
                MULTILINES.append(line.strip())

            # clear prompt for next line
            INPUTBUF = ''

            CURSORPOS = 0

            clearselection("prompt")

            DIRTY_PROMPT = True

            continue

        if ch in ('\n', '\r'):

            try:

                # capture line before clearing prompt
                line = INPUTBUF.strip()

                # multi-line mode - include any stored lines (shift-enter)
                lines_to_run = None
                try:
                    if MULTILINES:
                        lines_to_run = list(MULTILINES)
                except Exception:
                    lines_to_run = None

                if lines_to_run is not None:
                    if line:
                        lines_to_run.append(line)
                    MULTILINES = []
            except Exception:

                line = ""

            if lines_to_run is not None:

                for ln in lines_to_run:
                    if ln and str(ln).strip():
                        addhistory(str(ln).strip())
            elif line:

                addhistory(line)

            # clear prompt immediately so it is not "stuck" during foreground streaming
            INPUTBUF = ''

            CURSORPOS = 0

            DIRTY_PROMPT = True

            # repaint immediately (so the user sees the prompt cleared right away)
            drawcontent(cursor_on=False)

            if SOCK:
                pollserver()

            presentbrick()

            try:

                # now run the directive(s) (may block, e.g. foreground stream)
                if lines_to_run is not None:

                    # earlier lines were already echoed during shift-enter, so don't echo them twice
                    for i, ln in enumerate(lines_to_run):
                        ln = str(ln).strip()
                        if not ln:
                            continue

                        echo = (i == (len(lines_to_run) - 1))
                        runchain(ln, echo=echo)

                elif line:
                    runchain(line)

            except Exception as e:

                # directive run error
                guiprint(f'> error running directive {e}', colour=ERRORCOLOUR)

            return True

        if ch in ('\b', '\x7f'):

            # delete prompt selection if present
            if SELREGION == "prompt" and PROMPTSELNORMAL is not None and not isselectionempty("prompt"):

                ss, se = PROMPTSELNORMAL

                if ss < 0:
                    ss = 0

                if se > len(INPUTBUF):
                    se = len(INPUTBUF)

                if se < ss:
                    ss, se = se, ss

                oldcursor = CURSORPOS

                INPUTBUF = INPUTBUF[:ss] + INPUTBUF[se:]

                # keep cursor in the same logical place relative to the deletion
                if oldcursor > se:
                    CURSORPOS = oldcursor - (se - ss)

                elif oldcursor >= ss:
                    CURSORPOS = ss

                clearselection("prompt")

                DIRTY_PROMPT = True

                continue

            # normal backspace

            if CURSORPOS > 0:

                INPUTBUF = INPUTBUF[:CURSORPOS - 1] + INPUTBUF[CURSORPOS:]

                CURSORPOS -= 1

                DIRTY_PROMPT = True

            continue

        # copy (ctrl-c)
        if ch == "<COPY>":


            # only copy if there is a non-empty selection
            if not isselectionempty("prompt") or not isselectionempty("content"):

                text = selectiontext()

                if text:

                    exset(text, source="brick")

            continue

        # paste (ctrl-v)
        if ch == "<PASTE>":

            try:

                ok, st = exget()

            except Exception:

                ok, st = False, {}

            if ok:

                try:

                    paste = st.get("data", "")

                    if not isinstance(paste, str):
                        paste = str(paste)

                    raw = paste.replace("\r\n", "\n").replace("\r", "\n")

                    # if multi-line paste and prompt is clean, stage it for explicit confirmation
                    if "\n" in raw and not INPUTBUF.strip() and not MULTILINES and (isselectionempty("prompt")):

                        staged = stagepaste(raw)

                        if staged:

                            guiprint(f'> pasted {staged} directives; press enter to run or escape to cancel', colour=TEXTCOLOUR)

                            return True

                    # single-line paste path: flatten newlines
                    paste = raw.replace("\n", " ")

                except Exception:

                    paste = ""

                if paste:

                    # if prompt selection active, replace it
                    if SELREGION == "prompt" and PROMPTSELNORMAL is not None and not isselectionempty("prompt"):

                        ss, se = PROMPTSELNORMAL

                        oldcursor = CURSORPOS

                        INPUTBUF = INPUTBUF[:ss] + paste + INPUTBUF[se:]

                        # keep cursor logically positioned
                        if oldcursor > se:

                            CURSORPOS = oldcursor + len(paste) - (se - ss)

                        elif oldcursor >= ss:

                            CURSORPOS = ss + len(paste)

                        clearselection("prompt")

                        DIRTY_PROMPT = True

                    else:

                        # normal insert at cursor
                        INPUTBUF = INPUTBUF[:CURSORPOS] + paste + INPUTBUF[CURSORPOS:]

                        CURSORPOS += len(paste)

                        DIRTY_PROMPT = True

            continue

        # cut selection (Ctrl-X)
        if ch == "<CUT>":

            # only cut if prompt selection exists
            if SELREGION == "prompt" and PROMPTSELNORMAL is not None and not isselectionempty("prompt"):

                ss, se = PROMPTSELNORMAL

                if ss < 0:
                    ss = 0

                if se > len(INPUTBUF):
                    se = len(INPUTBUF)

                if se < ss:
                    ss, se = se, ss

                # copy to exchange
                exset(INPUTBUF[ss:se])

                oldcursor = CURSORPOS

                # remove selection
                INPUTBUF = INPUTBUF[:ss] + INPUTBUF[se:]

                # keep cursor logically positioned
                if oldcursor > se:
                    CURSORPOS = oldcursor - (se - ss)

                elif oldcursor >= ss:
                    CURSORPOS = ss

                clearselection("prompt")

                DIRTY_PROMPT = True

            continue

        if ch == '<UP>':

            historystep(-1)

            DIRTY_PROMPT = True
            continue

        if ch == '<DOWN>':

            historystep(1)

            DIRTY_PROMPT = True
            continue

        if ch == '<SLEFT>':

            clearselection("content")

            SELREGION = "prompt"

            if PROMPTSELANCHOR is None:
                PROMPTSELANCHOR = CURSORPOS

            if CURSORPOS > 0:
                CURSORPOS -= 1

            PROMPTSELEND = CURSORPOS

            normaliseselection()

            if isselectionempty("prompt"):

                clearselection("prompt")

                continue

            selectiondirty("prompt")

            continue

        if ch == '<SRIGHT>':

            clearselection("content")

            SELREGION = "prompt"

            if PROMPTSELANCHOR is None:
                PROMPTSELANCHOR = CURSORPOS

            if CURSORPOS < len(INPUTBUF):
                CURSORPOS += 1

            PROMPTSELEND = CURSORPOS

            normaliseselection()

            if isselectionempty("prompt"):

                clearselection("prompt")

                continue

            selectiondirty("prompt")

            continue

        if ch == '<LEFT>':

            clearselection("prompt")

            if CURSORPOS > 0:
                CURSORPOS -= 1

            DIRTY_PROMPT = True

            continue

        if ch == '<RIGHT>':

            clearselection("prompt")

            if CURSORPOS == len(INPUTBUF):

                sug = suggestfromhistory(INPUTBUF, CURSORPOS)

                if sug:

                    INPUTBUF = INPUTBUF + sug

                    CURSORPOS = len(INPUTBUF)

                    DIRTY_PROMPT = True

                    continue

            if CURSORPOS < len(INPUTBUF):
                CURSORPOS += 1

            DIRTY_PROMPT = True

            continue

        if ch == '<PGUP>':

            page(1)

            continue

        if ch == '<PGDN>':

            page(-1)

            continue

        # move cursor to start (Home)
        if ch == '<HOME>':

            CURSORPOS = 0

            DIRTY_PROMPT = True

            continue

        # move cursor to end (End)
        if ch == '<END>' or ch == '\x05':

            CURSORPOS = len(INPUTBUF)

            DIRTY_PROMPT = True

            continue

        if ch == '<DEL>':

            # delete prompt selection if present
            if SELREGION == "prompt" and PROMPTSELNORMAL is not None and not isselectionempty("prompt"):

                ss, se = PROMPTSELNORMAL

                if ss < 0:
                    ss = 0

                if se > len(INPUTBUF):
                    se = len(INPUTBUF)

                if se < ss:
                    ss, se = se, ss

                oldcursor = CURSORPOS

                INPUTBUF = INPUTBUF[:ss] + INPUTBUF[se:]

                # keep cursor in the same logical place relative to the deletion
                if oldcursor > se:
                    CURSORPOS = oldcursor - (se - ss)

                elif oldcursor >= ss:
                    CURSORPOS = ss

                clearselection("prompt")

                DIRTY_PROMPT = True

                continue

            # normal forward delete

            if CURSORPOS < len(INPUTBUF):

                INPUTBUF = INPUTBUF[:CURSORPOS] + INPUTBUF[CURSORPOS + 1:]

                DIRTY_PROMPT = True

            continue

        # select all (Ctrl-A)
        if ch == "<SELECTALL>":

            # clear content selection and select all prompt text
            clearselection("content")

            SELREGION = "prompt"

            PROMPTSELANCHOR = 0

            PROMPTSELEND = len(INPUTBUF)

            normaliseselection()

            if isselectionempty("prompt"):

                clearselection("prompt")

                continue

            selectiondirty("prompt")

            continue

        # insert printable character at cursor
        try:

            printable = isinstance(ch, str) and len(ch) == 1 and 32 <= ord(ch) <= 126

        except Exception:

            printable = False

        if printable:

            # if prompt selection active, replace it
            if SELREGION == "prompt" and PROMPTSELNORMAL is not None and not isselectionempty("prompt"):

                ss, se = PROMPTSELNORMAL

                if ss < 0:
                    ss = 0

                if se > len(INPUTBUF):
                    se = len(INPUTBUF)

                if se < ss:
                    ss, se = se, ss

                INPUTBUF = INPUTBUF[:ss] + ch + INPUTBUF[se:]

                CURSORPOS = ss + 1

                clearselection("prompt")

                DIRTY_PROMPT = True

                continue

            # respect max input size
            if len(INPUTBUF) < MAXINPUT:

                INPUTBUF = INPUTBUF[:CURSORPOS] + ch + INPUTBUF[CURSORPOS:]

                CURSORPOS += 1

                DIRTY_PROMPT = True

            continue

    return False


# draw functions
def drawtextline(x, y, text, colour=None, bold=False, semibold=False, underline=False, italic=False):

    try:

        # choose foreground colour
        fg = colourtoint(colour)
        if fg is None:
            fg = TEXTCOLOUR

        # keep a single path so header and content look identical
        if USE_TTF:

            # swap ttf font based on bold flag
            fontpath = graphicsfont(bold=bool(bold), semibold=bool(semibold))
            setttffont(bold=bool(bold), semibold=bool(semibold))

            drawtextttf(x, y, text, fg, FONTSIZE, fontpath=fontpath)
            return

        drawtext(x, y, text, fg, spacing=1, scale=TEXTSCALE)

    except Exception as e:

        # text draw error
        guiprint(f'> error drawing text {e}', colour=ERRORCOLOUR)


def drawtextlinewithselection(x, y, text, selstart, selend, colour=None, bold=False, semibold=False, underline=False, italic=False):

    try:

        # invalid span
        if selstart is None or selend is None:
            drawtextline(x, y, text, colour=colour, bold=bold, semibold=semibold, underline=underline, italic=italic)
            return

        if selend <= selstart:
            drawtextline(x, y, text, colour=colour, bold=bold, semibold=semibold, underline=underline, italic=italic)
            return

        # clamp span
        if selstart < 0:
            selstart = 0

        if selend > len(text):
            selend = len(text)

        # nothing left after clamp
        if selend <= selstart:
            drawtextline(x, y, text, colour=colour, bold=bold, semibold=semibold, underline=underline, italic=italic)
            return

        # resolve foreground
        fg = colourtoint(colour)
        if fg is None:
            fg = TEXTCOLOUR

        # split
        pre = text[:selstart]
        mid = text[selstart:selend]
        suf = text[selend:]

        # draw prefix
        if pre:
            drawtextline(x, y, pre, colour=fg, bold=bold, semibold=semibold, underline=underline, italic=italic)

        # selection background (same as text colour)
        sx = x + (selstart * SPACEW)
        sw = (selend - selstart) * SPACEW

        if sw > 0:
            fillrectfast(sx, y, sw, LINEHEIGHT, fg)

        # draw selected text in background colour
        if mid:
            drawtextline(sx, y, mid, colour=BACKGROUNDCOLOUR, bold=bold, semibold=semibold, underline=underline, italic=italic)

        # draw suffix
        if suf:
            dx = x + (selend * SPACEW)
            drawtextline(dx, y, suf, colour=fg, bold=bold, semibold=semibold, underline=underline, italic=italic)

    except Exception:

        drawtextline(x, y, text, colour=colour, bold=bold, semibold=semibold, underline=underline, italic=italic)


def drawcursor(x, y):

    try:

        # draw a cursor sized/positioned to font metrics
        fillrectfast(x, y + CURSOR_Y_OFFSET, CURSORW, CURSORH, CURSORCOLOUR)

    except Exception as e:

        # cursor draw error
        guiprint(f'> error drawing cursor {e}', colour=ERRORCOLOUR)


def drawheader():

    global PREV_CWD, CONTENT_TOP_Y

    if GRAPHICSSTATE.get("active") and GRAPHICSSTATE.get("managed_only"):

        width = int(getattr(gfx, "_xres", 1))
        height = int(getattr(gfx, "_yres", 1))
        top = max(0, min(height - 1, int(TOPBLANKLINES * LINEHEIGHT)))
        damage = [0, top, width, max(1, min(LINEHEIGHT, height - top))]

        managedmarkdamage(
            GRAPHICSSTATE,
            damage,
            bounds=(width, height),
        )
        return

    try:

        # compute header geometry once
        header_y = TOPBLANKLINES * LINEHEIGHT
        top = header_y + ((1 + SPACERLINES) * LINEHEIGHT)
        CONTENT_TOP_Y = top

        # only repaint header if cwd changes
        cwd = os.getcwd()
        location = formatlocation(cwd)
        if location != PREV_CWD:

            # erase header row only
            screen_w = getattr(gfx, '_xres', 1920)
            fillrectfast(0, header_y, screen_w, LINEHEIGHT, BACKGROUNDCOLOUR)

            # draw header text
            drawtextline(LEFTPAD, header_y, location)

            PREV_CWD = location

    except Exception as e:

        # header once error
        guiprint(f'> error drawing header once {e}', colour=ERRORCOLOUR)


def drawscrollbar():

    try:

        layout = contentlayout()
        rows = int(layout.get('rows', 0))
        total = int(layout.get('total', 0))

        if rows <= 0 or total <= rows:
            return

        track_x, track_y, track_w, track_h = scrollbargeometry()

        if track_w <= 0 or track_h <= 0:
            return

        fillrectfast(track_x, track_y, track_w, track_h, SCROLLBAR_BG)

        try:
            thumb_h = int(track_h * (rows / float(total)))
        except Exception:
            thumb_h = SCROLLBAR_MIN_THUMB

        if thumb_h < SCROLLBAR_MIN_THUMB:
            thumb_h = SCROLLBAR_MIN_THUMB

        if thumb_h > track_h:
            thumb_h = track_h

        maxoff = max(0, total - rows)

        off = SCROLLOFF

        if off < 0:
            off = 0

        if off > maxoff:
            off = maxoff

        if track_h - thumb_h <= 0:

            thumb_y = track_y

        else:

            try:
                frac = 1.0 - (off / float(maxoff))
            except Exception:
                frac = 1.0

            if frac < 0.0:
                frac = 0.0

            if frac > 1.0:
                frac = 1.0

            thumb_y = int(track_y + frac * (track_h - thumb_h))

        fillrectfast(track_x, thumb_y, track_w, thumb_h, SCROLLBAR_THUMB)

    except Exception as e:

        guiprint(f'> error drawing scrollbar {e}', colour=ERRORCOLOUR)


def drawhscrollbar():

    global HSCROLLBAR_VISIBLE

    try:

        if not hscrollbarneeded():
            HSCROLLBAR_VISIBLE = False
            return

    except Exception:

        HSCROLLBAR_VISIBLE = False
        return

    HSCROLLBAR_VISIBLE = True

    x, y, w, h = hscrollbargeometry()

    if w <= 0 or h <= 0:
        return

    fillrectfast(x, y, w, h, SCROLLBAR_BG)

    thumb_x, thumb_y, thumb_w, thumb_h = hscrollthumbgeometry()

    if thumb_w <= 0 or thumb_h <= 0:
        return

    fillrectfast(thumb_x, thumb_y, thumb_w, thumb_h, SCROLLBAR_THUMB)


def contentrows():

    try:
        return max(0, int(contentlayout().get('rows', 0)))

    except Exception as e:

        # rows compute error
        guiprint(f'> error computing content rows {e}', colour=ERRORCOLOUR)
        return 0


def drawlineat(y, text, style=None):

    try:

        # clear the target line region
        screen_w = getattr(gfx, '_xres', 1920)
        fillrectfast(0, y, screen_w, LINEHEIGHT, BACKGROUNDCOLOUR)

        # draw text with optional style
        if isinstance(style, dict):
            fg = colourtoint(style.get('colour'))
            bd = bool(style.get('bold', False))
            ul = bool(style.get('underline', False))
            it = bool(style.get('italic', False))
            drawtextline(LEFTPAD, y, text, colour=fg, bold=bd, underline=ul, italic=it)
            return

        drawtextline(LEFTPAD, y, text)

    except Exception as e:

        # line draw error
        guiprint(f'> error drawing line {e}', colour=ERRORCOLOUR)


def drawpromptandinput(y, cursor_on):

    # use cached widths computed in measurements()
    spacew = SPACEW
    promptw = PROMPTW

    # draw prompt
    x0 = LEFTPAD - (HSCROLL * SPACEW)
    drawtextline(x0, y, PROMPT)

    # input x origin
    sx = x0 + promptw + spacew

    # draw input with selection if active
    if SELREGION == "prompt" and PROMPTSELNORMAL is not None:

        ss, se = PROMPTSELNORMAL

        drawpromptinputstyled(sx, y, INPUTBUF, ss, se)

    else:

        drawpromptinputstyled(sx, y, INPUTBUF)

    # inline history suggestion (ghost text)
    try:

        if (SELREGION != "prompt") or (PROMPTSELNORMAL is None):

            sug = suggestfromhistory(INPUTBUF, CURSORPOS)

            if sug:

                gx = sx + (spacew * len(INPUTBUF))

                drawtextline(gx, y, sug, colour=SUGGESTCOLOUR)

    except Exception:
        pass

    # cursor
    if cursor_on:
        cx = sx + (spacew * CURSORPOS)
        drawcursor(cx, y)


def drawpromptinputstyled(x, y, text, selstart=None, selend=None):

    n = len(text)
    if n <= 0:

        return

    try:

        boldspans = []
        semispans = []

        try:

            if ";" in str(text):

                try:

                    segs = splitchainpos(text)

                except Exception:

                    segs = None

                if segs:

                    for seg, off in segs:

                        b0, b1 = directivebounds(seg)

                        if b0 is not None and b1 is not None and b1 > b0:
                            boldspans.append((off + b0, off + b1))

                        sb = semiboldbounds(seg)

                        for s, e in sb:

                            try:

                                if s is None or e is None:
                                    continue

                                if e <= s:
                                    continue

                                semispans.append((off + s, off + e))

                            except Exception:
                                continue

                else:

                    b0, b1 = directivebounds(text)

                    if b0 is not None and b1 is not None and b1 > b0:
                        boldspans.append((b0, b1))

                    try:

                        semispans = semiboldbounds(text)

                    except Exception:

                        semispans = []

            else:

                b0, b1 = directivebounds(text)

                if b0 is not None and b1 is not None and b1 > b0:
                    boldspans.append((b0, b1))

                try:

                    semispans = semiboldbounds(text)

                except Exception:

                    semispans = []

        except Exception:

            b0, b1 = directivebounds(text)

            if b0 is not None and b1 is not None and b1 > b0:
                
                boldspans.append((b0, b1))

            try:

                semispans = semiboldbounds(text)

            except Exception:

                semispans = []

    except Exception:

        boldspans = []
        semispans = []

    try:

        cuts = set([0, n])

        for s, e in boldspans:

            if s is None or e is None:
                continue
            if e <= s:
                continue

            if s < 0:
                s = 0

            if e > n:
                e = n

            cuts.add(s)
            cuts.add(e)

        for s, e in semispans:

            if s is None or e is None:
                continue
            if e <= s:
                continue

            if s < 0:
                s = 0

            if e > n:
                e = n

            cuts.add(s)
            cuts.add(e)

        cuts = sorted(list(cuts))

    except Exception:

        cuts = [0, n]

    try:

        cx = x

        for i in range(len(cuts) - 1):

            a = cuts[i]
            b = cuts[i + 1]

            if b <= a:
                continue

            seg = text[a:b]

            if not seg:
                continue

            # resolve style for this segment
            segbold = False
            segsemi = False

            try:

                for s, e in boldspans:

                    if a >= s and b <= e:
                        segbold = True
                        break
            except Exception:

                segbold = False

            if not segbold:

                try:

                    for s, e in semispans:

                        if a >= s and b <= e:
                            segsemi = True
                            break
                except Exception:

                    segsemi = False

            # resolve selection overlap for this segment
            if selstart is not None and selend is not None:

                try:

                    ss = selstart
                    se = selend

                    if se < ss:
                        ss, se = se, ss

                    # overlap test
                    if se > a and ss < b:

                        rs = ss - a
                        re = se - a

                        if rs < 0:
                            rs = 0

                        if re > len(seg):
                            re = len(seg)

                        drawtextlinewithselection(cx, y, seg, rs, re, bold=segbold, semibold=segsemi)

                    else:

                        drawtextline(cx, y, seg, bold=segbold, semibold=segsemi)

                except Exception:

                    drawtextline(cx, y, seg, bold=segbold, semibold=segsemi)

            else:

                try:

                    drawtextline(cx, y, seg, bold=segbold, semibold=segsemi)

                except Exception:

                    drawtextline(cx, y, seg)

            cx += SPACEW * len(seg)

    except Exception:

        if selstart is not None and selend is not None:
            
            drawtextlinewithselection(x, y, text, selstart, selend)
            
            return
        
        drawtextline(x, y, text)


def drawwrappedpromptinputstyled(x, y, start, end, selstart=None, selend=None):

    source = str(INPUTBUF)
    start = max(0, min(len(source), int(start)))
    end = max(start, min(len(source), int(end)))

    for spanstart, spanend, bold, semibold in promptstylespans(source):

        drawstart = max(start, spanstart)
        drawend = min(end, spanend)

        if drawend <= drawstart:
            continue

        segment = source[drawstart:drawend]
        segmentx = x + ((drawstart - start) * SPACEW)

        if (
            selstart is not None
            and selend is not None
            and int(selend) > drawstart
            and int(selstart) < drawend
        ):

            localselectionstart = max(0, int(selstart) - drawstart)
            localselectionend = min(len(segment), int(selend) - drawstart)
            drawtextlinewithselection(
                segmentx,
                y,
                segment,
                localselectionstart,
                localselectionend,
                bold=bold,
                semibold=semibold,
            )

        else:

            drawtextline(segmentx, y, segment, bold=bold, semibold=semibold)


def drawwrappedpromptandinput(y, cursor_on, layout):

    promptrows = layout.get('prompt_rows', [(0, len(INPUTBUF), True)])
    selectionstart = None
    selectionend = None

    if SELREGION == 'prompt' and PROMPTSELNORMAL is not None:

        try:
            selectionstart, selectionend = PROMPTSELNORMAL

        except Exception:
            selectionstart = None
            selectionend = None

    lastinputx = LEFTPAD
    lastinputend = 0

    for rowindex, (inputstart, inputend, showprompt) in enumerate(promptrows):

        rowy = y + (rowindex * LINEHEIGHT)
        inputx = LEFTPAD

        if showprompt:
            drawtextline(LEFTPAD, rowy, PROMPT)
            inputx += PROMPTW + SPACEW

        drawwrappedpromptinputstyled(
            inputx,
            rowy,
            inputstart,
            inputend,
            selectionstart,
            selectionend,
        )
        lastinputx = inputx
        lastinputend = inputend

    try:

        if selectionstart is None or selectionend is None:

            suggestion = suggestfromhistory(INPUTBUF, CURSORPOS)

            if suggestion:
                lastrowstart = promptrows[-1][0]
                suggestionx = lastinputx + (SPACEW * (lastinputend - lastrowstart))
                suggestiony = y + ((len(promptrows) - 1) * LINEHEIGHT)
                drawtextline(suggestionx, suggestiony, suggestion, colour=SUGGESTCOLOUR)

    except Exception:
        pass

    if cursor_on:

        for rowindex, (inputstart, inputend, showprompt) in enumerate(promptrows):

            if CURSORPOS < inputend or rowindex == len(promptrows) - 1:
                cursorbase = LEFTPAD + (PROMPTW + SPACEW if showprompt else 0)
                cursorx = cursorbase + (SPACEW * max(0, CURSORPOS - inputstart))
                cursory = y + (rowindex * LINEHEIGHT)
                drawcursor(cursorx, cursory)
                break


def drawplayback():

    geometry = playbackgeometry()

    if not geometry:

        return

    videobox = geometry.get('video', [0, 0, 0, 0])

    if videobox[2] > 0 and videobox[3] > 0:

        frame = PLAYBACK.get('frame', {})
        path = str(frame.get('path', '') or '')
        sourcewidth = int(frame.get('width', 0) or 0)
        sourceheight = int(frame.get('height', 0) or 0)
        destination = playbackvideoplacement(videobox)
        frameclip = geometry.get('clip', [0, 0, int(getattr(gfx, '_xres', 1)), int(getattr(gfx, '_yres', 1))])
        left = max(int(videobox[0]), int(frameclip[0]))
        top = max(int(videobox[1]), int(frameclip[1]))
        right = min(int(videobox[0] + videobox[2]), int(frameclip[0] + frameclip[2]))
        bottom = min(int(videobox[1] + videobox[3]), int(frameclip[1] + frameclip[3]))

        if right > left and bottom > top:

            fillrectfast(left, top, right - left, bottom - top, BACKGROUNDCOLOUR)

        if (
            destination[2] > 0
            and destination[3] > 0
            and sourcewidth > 0
            and sourceheight > 0
            and os.path.isfile(path)
        ):

            blitfilescaledfast(
                path,
                sourcewidth,
                sourceheight,
                destination[0],
                destination[1],
                destination[2],
                destination[3],
                'BGRA32',
                clip=frameclip,
            )

    stopx, stopy, stopw, stoph = geometry['stop']
    inset = max(2, stopw // 4)
    fillrectfast(
        stopx + inset,
        stopy + inset,
        max(1, stopw - (inset * 2)),
        max(1, stoph - (inset * 2)),
        PLAYBACK_CONTROL_COLOUR,
    )
    togglex, toggley, togglew, toggleh = geometry['toggle']
    state = str(PLAYBACK.get('state', 'playing'))

    if state != 'paused':

        barwidth = max(2, togglew // 5)
        gap = max(2, togglew // 5)
        left = togglex + max(1, (togglew - ((barwidth * 2) + gap)) // 2)
        fillrectfast(left, toggley + 2, barwidth, max(1, toggleh - 4), PLAYBACK_CONTROL_COLOUR)
        fillrectfast(left + barwidth + gap, toggley + 2, barwidth, max(1, toggleh - 4), PLAYBACK_CONTROL_COLOUR)

    else:

        trianglewidth = max(3, togglew - 4)

        for offset in range(trianglewidth):

            trim = int((offset / float(max(1, trianglewidth - 1))) * ((toggleh - 4) / 2.0))
            fillrectfast(
                togglex + 2 + offset,
                toggley + 2 + trim,
                1,
                max(1, toggleh - 4 - (trim * 2)),
                PLAYBACK_CONTROL_COLOUR,
            )

    trackx, tracky, trackw, trackh = geometry['track']
    fillrectfast(trackx, tracky, trackw, trackh, PLAYBACK_TRACK_COLOUR)
    thumbx, thumby, thumbw, thumbh = geometry['thumb']
    fillrectfast(thumbx, thumby, thumbw, thumbh, PLAYBACK_CONTROL_COLOUR)
    timex, timey, timetext = geometry['time']
    drawtextline(timex, timey, timetext, colour=TEXTCOLOUR)


def drawcontent(cursor_on):

    global GRAPHICSCURSORON, SCROLLOFF, HSCROLL, HSCROLL_MAX, HSCROLL_VIEWCOLS, HSCROLLBAR_VISIBLE

    GRAPHICSCURSORON = bool(cursor_on)

    if consoleactive():

        if GRAPHICSSTATE.get("active") and GRAPHICSSTATE.get("managed_only"):
            geometry = consolegeometry()
            managedmarkdamage(
                GRAPHICSSTATE,
                [0, geometry['y'], geometry['screen_width'], geometry['screen_height'] - geometry['y']],
                bounds=(geometry['screen_width'], geometry['screen_height']),
            )
            return

        drawconsole(cursor_on)
        return

    if GRAPHICSSTATE.get("active") and GRAPHICSSTATE.get("managed_only"):

        width = int(getattr(gfx, "_xres", 1))
        height = int(getattr(gfx, "_yres", 1))
        layout = contentlayout()

        if DIRTY_SCROLL:
            top = max(0, min(height - 1, int(layout.get("top", 0))))
            damage = [0, top, width, max(1, height - top)]
        else:
            # Prompt edits and cursor blinking only change the wrapped prompt
            # band.  Retained scenes keep the background and scrollback
            # nodes intact, so repainting the complete window here defeats
            # compositor damage tracking and creates large frame spikes.
            top = max(0, min(height - 1, int(layout.get("prompty", height - LINEHEIGHT))))
            promptheight = max(1, len(layout.get('prompt_rows', []))) * LINEHEIGHT

            if PLAYBACK:

                playbacktop = int(playbackgeometry().get('y', top))
                top = min(top, max(0, playbacktop))

            damage = [0, top, width, max(1, min(promptheight, height - top))]

            if PLAYBACK:

                damage = [0, top, width, max(1, height - top)]

        managedmarkdamage(
            GRAPHICSSTATE,
            damage,
            bounds=(width, height),
        )

        if not DIRTY_SCROLL and HSCROLLBAR_VISIBLE:
            bartop = max(0, height - HSCROLLBAR_HEIGHT - SCROLLBAR_MARGIN)
            managedmarkdamage(
                GRAPHICSSTATE,
                [0, bartop, width, height - bartop],
                bounds=(width, height),
            )

        return

    try:

        layout = contentlayout()
        top = int(layout.get('top', CONTENT_TOP_Y))
        screen_w = int(layout.get('screen_w', getattr(gfx, '_xres', 1920)))
        screen_h = int(layout.get('screen_h', getattr(gfx, '_yres', 1080)))

        # clear only the content region if scrollback is dirty
        if DIRTY_SCROLL:
            fillrectfast(0, top, screen_w, screen_h - top, BACKGROUNDCOLOUR)

        x0 = int(layout.get('x0', LEFTPAD))
        visiblerows = layout.get('visible_rows', [])

        # optional parallel styles
        try:
            styles = STYLES
        except NameError:
            styles = []

        # --- draw scrollback (only visible rows) ---
        y = top
        contentbottom = int(layout.get('prompty', top))
        renderedimages = set()

        if DIRTY_SCROLL:

            for row in visiblerows:

                i, rowstart, rowend = row
                line = str(SCROLL[i])[rowstart:rowend]

                sty = styles[i] if i < len(styles) else None

                selstart = None
                selend = None

                if SELREGION == "content" and SELNORMAL is not None:

                    try:

                        (sl, sc), (el, ec) = SELNORMAL

                        if i < sl or i > el:
                            pass

                        elif sl == el and i == sl:
                            logicalstart = sc
                            logicalend = ec

                        elif i == sl:
                            logicalstart = sc
                            logicalend = len(SCROLL[i])

                        elif i == el:
                            logicalstart = 0
                            logicalend = ec

                        else:
                            logicalstart = 0
                            logicalend = len(SCROLL[i])

                        if sl <= i <= el:
                            selstart = max(rowstart, logicalstart) - rowstart
                            selend = min(rowend, logicalend) - rowstart

                            if selend <= selstart:
                                selstart = None
                                selend = None

                    except Exception:

                        selstart = None
                        selend = None

                if isinstance(sty, dict):

                    image = sty.get('image')

                    if isinstance(image, dict):

                        identifier = int(image.get('id', 0))

                        if identifier not in renderedimages:
                            viewblit(image, int(sty.get('image_row', 0)), y, top, contentbottom)
                            renderedimages.add(identifier)

                        y += LINEHEIGHT
                        continue

                    fg = colourtoint(sty.get('colour'))
                    bd = bool(sty.get('bold', False))
                    ul = bool(sty.get('underline', False))
                    it = bool(sty.get('italic', False))

                    if selstart is not None and selend is not None:
                        drawtextlinewithselection(x0, y, line, selstart, selend, colour=fg, bold=bd, underline=ul, italic=it)
                    else:
                        drawtextline(x0, y, line, colour=fg, bold=bd, underline=ul, italic=it)

                else:

                    if selstart is not None and selend is not None:
                        drawtextlinewithselection(x0, y, line, selstart, selend)
                    else:
                        drawtextline(x0, y, line)

                y += LINEHEIGHT

        else:

            # update y for prompt even if skipping scrollback draw
            y += len(visiblerows) * LINEHEIGHT

        # --- draw prompt right after last drawn line (floating) ---
        if DIRTY_PROMPT or DIRTY_SCROLL or (cursor_on != PREV_CURSOR_ON):

            # erase prompt area only (if not already cleared by DIRTY_SCROLL)
            if not DIRTY_SCROLL:
                fillrectfast(0, y, screen_w, screen_h - y, BACKGROUNDCOLOUR)

            drawwrappedpromptandinput(y, cursor_on, layout)

            drawplayback()

        # --- draw scrollbars if either region changed ---
        if DIRTY_SCROLL or DIRTY_PROMPT or (cursor_on != PREV_CURSOR_ON):

            # draw scrollbar on the right edge
            drawscrollbar()

            # draw horizontal scrollbar on the bottom edge
            drawhscrollbar()

    except Exception as e:
        
        guiprint(f'> error drawing content {e}', colour=ERRORCOLOUR)


def updatedirty(cursor_on, lastblink):

    global DIRTY_SCROLL, DIRTY_PROMPT, PREV_SCROLL_LEN, PREV_SCROLLOFF, PREV_INPUTBUF, PREV_CURSORPOS, PREV_ROWS, PREV_CURSOR_ON
    global CONSOLE_BLINK_ON

    # compute blink
    now = time.monotonic()

    if consoleactive():

        display = ACTIVE_CONSOLE['display']

        if now - lastblink >= BLINKINTERVAL and (display.text_blink or (display.cursor_visible and display.cursor_blink)):
            CONSOLE_BLINK_ON = not CONSOLE_BLINK_ON
            if display.cursor_visible and display.cursor_blink:
                cursor_on = CONSOLE_BLINK_ON
            lastblink = now
            DIRTY_SCROLL = bool(display.text_blink) or DIRTY_SCROLL
            DIRTY_PROMPT = True

        if not display.cursor_visible:
            cursor_on = False
        elif not display.cursor_blink:
            cursor_on = True

        if display.dirty:
            DIRTY_SCROLL = True
            DIRTY_PROMPT = True

        if cursor_on != PREV_CURSOR_ON:
            DIRTY_PROMPT = True

        return cursor_on, lastblink

    if now - lastblink >= BLINKINTERVAL:

        cursor_on = not cursor_on

        lastblink = now

        # cursor visibility changed
        DIRTY_PROMPT = True

    # recompute content rows
    rows_now = contentrows()

    if rows_now != PREV_ROWS:

        PREV_ROWS = rows_now

        DIRTY_SCROLL = True
        
        DIRTY_PROMPT = True

    # scrollback length or offset changed
    if len(SCROLL) != PREV_SCROLL_LEN or SCROLLOFF != PREV_SCROLLOFF:

        PREV_SCROLL_LEN = len(SCROLL)
        
        PREV_SCROLLOFF = SCROLLOFF

        DIRTY_SCROLL = True
        
        DIRTY_PROMPT = True

    # input buffer or cursor state changed
    if INPUTBUF != PREV_INPUTBUF or CURSORPOS != PREV_CURSORPOS or cursor_on != PREV_CURSOR_ON:

        PREV_INPUTBUF = INPUTBUF
        
        PREV_CURSORPOS = CURSORPOS
        
        PREV_CURSOR_ON = cursor_on

        DIRTY_PROMPT = True

    return cursor_on, lastblink


def renderframe(cursor_on):

    global DIRTY_SCROLL, DIRTY_PROMPT, SOCK, WINID, PREV_CURSOR_ON, LASTSCROLLFRAME

    # reap finished jobs before drawing
    jobreap()

    scrollframe = bool(DIRTY_SCROLL)

    if scrollframe:

        now = time.monotonic()
        managed = bool(GRAPHICSSTATE.get("active") and GRAPHICSSTATE.get("managed_only"))
        interval = SCROLLMANAGEDINTERVAL if managed else SCROLLCPUINTERVAL

        if LASTSCROLLFRAME and now - LASTSCROLLFRAME < interval:
            return False

    try:

        # decide whether we actually need to push a new frame
        dopresent = False

        if DIRTY_SCROLL:
            dopresent = True

        if DIRTY_PROMPT:
            dopresent = True

        if cursor_on != PREV_CURSOR_ON:
            dopresent = True

    except Exception:
        dopresent = True

    if dopresent:

        # draw content and prompt
        drawcontent(cursor_on)

        # This frame now owns the dirties it drew. Clear them before polling so
        # focus, resize or content events received below remain pending for the
        # following frame instead of being erased after presentation.
        DIRTY_SCROLL = False
        DIRTY_PROMPT = False

        if consoleactive():
            ACTIVE_CONSOLE['display'].dirty = False

        # process any pending server messages before present
        if SOCK:
            pollserver()

        # present frame
        presentbrick()

        # sync cursor state
        PREV_CURSOR_ON = cursor_on

        if scrollframe:
            LASTSCROLLFRAME = time.monotonic()

        return True

    return False


def scrollbargeometry():

    try:

        screen_w = getattr(gfx, '_xres', 1920)
        layout = contentlayout()

        track_w = SCROLLBAR_WIDTH

        track_x = screen_w - track_w - SCROLLBAR_MARGIN

        if track_x < 0:
            track_x = 0

        track_y = int(layout.get('top', CONTENT_TOP_Y))
        track_h = int(layout.get('prompty', track_y)) - track_y

        if track_h < 0:
            track_h = 0

        return track_x, track_y, track_w, track_h

    except Exception as e:

        guiprint(f'> error computing scrollbar geometry {e}', colour=ERRORCOLOUR)
        return 0, 0, 0, 0


def hscrollbargeometry():

    try:

        screen_w = getattr(gfx, '_xres', 1920)

        screen_h = getattr(gfx, '_yres', 1080)

    except Exception:

        screen_w = 1920

        screen_h = 1080

    vbar_visible = False

    try:

        x = LEFTPAD

        h = HSCROLLBAR_HEIGHT

        y = screen_h - h - SCROLLBAR_MARGIN

        right_limit = screen_w

        if vbar_visible:
            right_limit = screen_w - (SCROLLBAR_WIDTH + SCROLLBAR_MARGIN)

        w = right_limit - x

        if w < 0:
            w = 0

    except Exception:

        x = 0

        y = 0

        w = 0

        h = 0

    return x, y, w, h


def hscrollbarneeded():


    if HSCROLL_MAX > 0:
        return True

    return False


def hscrollthumbgeometry():

    try:

        x, y, w, h = hscrollbargeometry()

        if w <= 0 or h <= 0:
            return 0, 0, 0, 0

        view = HSCROLL_VIEWCOLS
        if view <= 0:
            view = 1

        total = view + HSCROLL_MAX
        if total <= 0:
            total = 1

        try:
            thumb_w = int((view / float(total)) * w)
        except Exception:
            thumb_w = SCROLLBAR_MIN_THUMB

        if thumb_w < SCROLLBAR_MIN_THUMB:
            thumb_w = SCROLLBAR_MIN_THUMB

        if thumb_w > w:
            thumb_w = w

        if HSCROLL_MAX <= 0 or (w - thumb_w) <= 0:
            thumb_x = x
            
        else:
            
            try:
                frac = HSCROLL / float(HSCROLL_MAX)
            except Exception:
                frac = 0.0

            if frac < 0.0:
                frac = 0.0

            if frac > 1.0:
                frac = 1.0

            thumb_x = x + int(frac * (w - thumb_w))

        return thumb_x, y, thumb_w, h

    except Exception:

        return 0, 0, 0, 0


def handlehscrollbutton(mx, my, isdown):

    global HSCROLLBAR_DRAGGING, HSCROLLBAR_DRAG_OFFSET, HSCROLL

    try:

        if not hscrollbarneeded():
            return False

        x, y, w, h = hscrollbargeometry()

        if mx < x or mx > x + w:
            return False

        if my < y or my > y + h:
            return False

        if not isdown:
            HSCROLLBAR_DRAGGING = False
            return True

        thumb_x, thumb_y, thumb_w, thumb_h = hscrollthumbgeometry()

        if mx >= thumb_x and mx <= thumb_x + thumb_w:
            
            HSCROLLBAR_DRAGGING = True
            
            HSCROLLBAR_DRAG_OFFSET = mx - thumb_x
            
            return True

        if mx < thumb_x:
            
            HSCROLL = HSCROLL - max(1, (w // SPACEW) // 2)
            
            if HSCROLL < 0:
                HSCROLL = 0
                
            return True

        if mx > thumb_x + thumb_w:
            
            HSCROLL = HSCROLL + max(1, (w // SPACEW) // 2)
            
            if HSCROLL > HSCROLL_MAX:
                HSCROLL = HSCROLL_MAX
                
            return True

    except Exception:
        
        return False

    return False


def handlehscrollmotion(mx, my):

    global HSCROLL

    try:

        if not HSCROLLBAR_DRAGGING:
            return False

        x, y, w, h = hscrollbargeometry()
        thumb_x, thumb_y, thumb_w, thumb_h = hscrollthumbgeometry()

        pos = mx - x - HSCROLLBAR_DRAG_OFFSET
        if pos < 0:
            pos = 0
        if pos > w - thumb_w:
            pos = w - thumb_w

        if w - thumb_w <= 0 or HSCROLL_MAX <= 0:
            HSCROLL = 0
            return True

        ratio = pos / (w - thumb_w)
        HSCROLL = int(ratio * HSCROLL_MAX)

        if HSCROLL < 0:
            HSCROLL = 0

        if HSCROLL > HSCROLL_MAX:
            HSCROLL = HSCROLL_MAX

        return True

    except Exception:
        return False


# selection functions
def prompty():

    try:
        return int(contentlayout().get('prompty', CONTENT_TOP_Y))

    except Exception:

        return CONTENT_TOP_Y


def incontent(x, y):

    try:

        lay = contentlayout()

        if y < lay["y0"]:
            return False

        if y >= lay["prompty"]:
            return False

        return True

    except Exception:

        return False


def inprompt(x, y):

    try:

        lay = contentlayout()

        if y < lay["prompty"]:
            return False

        promptheight = max(1, len(lay.get('prompt_rows', []))) * LINEHEIGHT

        if y >= lay["prompty"] + promptheight:
            return False

        return True

    except Exception:

        return False


def contentposfromxy(x, y):

    try:

        lay = contentlayout()

        visiblerows = lay.get("visible_rows", [])
        drawn = len(visiblerows)

        if drawn <= 0:
            return (0, 0)

        rel = int((y - lay["y0"]) // LINEHEIGHT)

        if rel < 0:
            rel = 0

        if rel >= drawn:
            rel = drawn - 1

        absline, rowstart, rowend = visiblerows[rel]

        if absline < 0:
            absline = 0

        if absline >= len(SCROLL):
            absline = len(SCROLL) - 1

        col = rowstart + int((x - lay["x0"]) // SPACEW)

        if col < rowstart:
            col = rowstart

        if col > rowend:
            col = rowend

        return (absline, col)

    except Exception:

        return (0, 0)


def promptposfromxy(x, y):

    try:

        lay = contentlayout()

        promptrows = lay.get('prompt_rows', [(0, len(INPUTBUF), True)])
        rowindex = int((y - lay['prompty']) // LINEHEIGHT)
        rowindex = max(0, min(len(promptrows) - 1, rowindex))
        inputstart, inputend, showprompt = promptrows[rowindex]
        inputx = LEFTPAD + (PROMPTW + SPACEW if showprompt else 0)
        col = inputstart + int((x - inputx) // SPACEW)
        return max(inputstart, min(inputend, col))

    except Exception:

        return 0


def clearselection(region):

    global SELREGION, SELACTIVE, SELANCHOR, SELEND, SELNORMAL, PROMPTSELANCHOR, PROMPTSELEND, PROMPTSELNORMAL, SELCHANGED, DIRTY_SCROLL, DIRTY_PROMPT
    
    try:

        # clear content selection
        if region in ("content", "console"):

            SELREGION = None

            SELACTIVE = False

            SELANCHOR = None

            SELEND = None

            SELNORMAL = None

            SELCHANGED = True

            DIRTY_SCROLL = True

            return

        # clear prompt selection
        if region == "prompt":

            SELREGION = None

            SELACTIVE = False

            PROMPTSELANCHOR = None

            PROMPTSELEND = None

            PROMPTSELNORMAL = None

            SELCHANGED = True

            DIRTY_PROMPT = True

            return

        # clear everything
        SELREGION = None

        SELACTIVE = False

        SELANCHOR = None

        SELEND = None

        SELNORMAL = None

        PROMPTSELANCHOR = None

        PROMPTSELEND = None

        PROMPTSELNORMAL = None

        SELCHANGED = True

        DIRTY_SCROLL = True

        DIRTY_PROMPT = True

    except Exception:

        SELREGION = None

        SELACTIVE = False

        SELANCHOR = None

        SELEND = None

        SELNORMAL = None

        PROMPTSELANCHOR = None

        PROMPTSELEND = None

        PROMPTSELNORMAL = None

        SELCHANGED = True

        DIRTY_SCROLL = True

        DIRTY_PROMPT = True


def ordercontent(a, b):

    try:

        al, ac = a

        bl, bc = b

    except Exception:

        return (a, b)

    try:

        # a comes first by line
        if al < bl:
            return (a, b)

        # b comes first by line
        if bl < al:
            return (b, a)

        # same line, a comes first by col
        if ac <= bc:
            return (a, b)

        return (b, a)

    except Exception:

        return (a, b)


def orderprompt(a, b):

    try:

        # a comes first
        if a <= b:
            return (a, b)

        return (b, a)

    except Exception:

        return (a, b)


def normaliseselection():

    global SELNORMAL, PROMPTSELNORMAL

    try:

        # normalise content selection
        if SELANCHOR is not None and SELEND is not None:

            start, end = ordercontent(SELANCHOR, SELEND)

            SELNORMAL = (start, end)

        else:

            SELNORMAL = None

    except Exception:

        SELNORMAL = None

    try:

        # normalise prompt selection
        if PROMPTSELANCHOR is not None and PROMPTSELEND is not None:

            start, end = orderprompt(PROMPTSELANCHOR, PROMPTSELEND)

            PROMPTSELNORMAL = (start, end)

        else:

            PROMPTSELNORMAL = None

    except Exception:

        PROMPTSELNORMAL = None


def isselectionempty(region):

    try:

        # content selection empty
        if region in ("content", "console"):

            if SELNORMAL is None:
                return True

            (sl, sc), (el, ec) = SELNORMAL

            if sl == el and sc == ec:
                return True

            return False

        # prompt selection empty
        if region == "prompt":

            if PROMPTSELNORMAL is None:
                return True

            sc, ec = PROMPTSELNORMAL

            if sc == ec:
                return True

            return False

        return True

    except Exception:

        return True


def selectiontext():

    try:

        if SELREGION == "console":

            if not consoleactive() or SELNORMAL is None:
                return ""

            return ACTIVE_CONSOLE['display'].selection_text(SELNORMAL)

        # prompt selection
        if SELREGION == "prompt":

            if PROMPTSELNORMAL is None:
                return ""

            ss, se = PROMPTSELNORMAL

            if ss is None or se is None:
                return ""

            if se <= ss:
                return ""

            if ss < 0:
                ss = 0

            if se > len(INPUTBUF):
                se = len(INPUTBUF)

            if se <= ss:
                return ""

            return INPUTBUF[ss:se]

        # content selection
        if SELREGION == "content":

            if SELNORMAL is None:
                return ""

            (sl, sc), (el, ec) = SELNORMAL

            if sl is None or sc is None or el is None or ec is None:
                return ""

            if el < sl:
                return ""

            if el == sl and ec <= sc:
                return ""

            # clamp lines
            if sl < 0:
                sl = 0

            if el < 0:
                el = 0

            if sl >= len(SCROLL):
                return ""

            if el >= len(SCROLL):
                el = len(SCROLL) - 1

            parts = []

            # single line
            if sl == el:

                line = SCROLL[sl]

                if sc < 0:
                    sc = 0

                if ec > len(line):
                    ec = len(line)

                if ec <= sc:
                    return ""

                return line[sc:ec]

            # first line
            first = SCROLL[sl]

            if sc < 0:
                sc = 0

            if sc > len(first):
                sc = len(first)

            parts.append(first[sc:])

            # middle lines
            i = sl + 1
            while i < el:

                parts.append(SCROLL[i])
                i += 1

            # last line
            last = SCROLL[el]

            if ec < 0:
                ec = 0

            if ec > len(last):
                ec = len(last)

            parts.append(last[:ec])

            return "\n".join(parts)

        return ""

    except Exception:

        return ""


def selectiondirty(region):

    global SELCHANGED, DIRTY_SCROLL, DIRTY_PROMPT

    try:

        SELCHANGED = True

        if region in ("content", "console"):

            DIRTY_SCROLL = True

            return

        if region == "prompt":

            DIRTY_PROMPT = True

            return

        DIRTY_SCROLL = True

        DIRTY_PROMPT = True

    except Exception:

        SELCHANGED = True

        DIRTY_SCROLL = True

        DIRTY_PROMPT = True


def selectpromptall():

    global SELREGION, SELACTIVE, PROMPTSELANCHOR, PROMPTSELEND, DIRTY_PROMPT

    # clear content selection and select all prompt text
    clearselection("content")

    SELREGION = "prompt"

    SELACTIVE = False

    PROMPTSELANCHOR = 0

    PROMPTSELEND = len(INPUTBUF)

    normaliseselection()

    if isselectionempty("prompt"):

        clearselection("prompt")
        return

    selectiondirty("prompt")

    DIRTY_PROMPT = True


def selectpromptword(pos):

    global SELREGION, SELACTIVE, PROMPTSELANCHOR, PROMPTSELEND, CURSORPOS, DIRTY_PROMPT

    s = INPUTBUF
    n = len(s)

    if n <= 0:

        clearselection("prompt")
        return

    if pos < 0:
        pos = 0

    if pos > n:
        pos = n

    # if click is on a space, prefer the char just before it (common terminal behaviour)
    try:

        if pos > 0 and pos < n and s[pos] == ' ' and s[pos - 1] != ' ':
            pos = pos - 1

    except Exception:
        pass

    # if still on whitespace, jump forward to next word if any
    try:

        if pos < n and s[pos] == ' ':

            while pos < n and s[pos] == ' ':
                pos += 1

            if pos >= n:

                clearselection("prompt")
                return

    except Exception:
        pass

    # expand left to word boundary
    start = pos
    try:

        while start > 0 and s[start - 1] != ' ':
            start -= 1

    except Exception:
        start = pos

    # expand right to word boundary
    end = pos
    try:

        while end < n and s[end] != ' ':
            end += 1

    except Exception:
        end = pos

    # include trailing single space if present
    try:

        if end < n and s[end] == ' ':
            end += 1

    except Exception:
        pass

    # apply selection
    clearselection("content")

    SELREGION = "prompt"

    SELACTIVE = False

    PROMPTSELANCHOR = start

    PROMPTSELEND = end

    normaliseselection()

    if isselectionempty("prompt"):

        clearselection("prompt")
        return

    selectiondirty("prompt")

    DIRTY_PROMPT = True


def handleplaybackbutton(x, y, down):

    global PLAYBACK_DRAGGING, PLAYBACK_PREVIEW, DIRTY_SCROLL, DIRTY_PROMPT

    if not PLAYBACK:

        return False

    geometry = playbackgeometry()

    if not geometry:

        return False

    if not down:

        if not PLAYBACK_DRAGGING:

            return False

        position = playbackpositionfromx(x)
        PLAYBACK_PREVIEW = position
        PLAYBACK['position'] = position
        playbackcommand('seek', position=position)
        PLAYBACK_DRAGGING = False
        PLAYBACK_PREVIEW = None
        DIRTY_SCROLL = True
        DIRTY_PROMPT = True

        return True

    if pointinrect(x, y, geometry.get('stop')):

        playbackcommand('stop')
        PLAYBACK['state'] = 'stopping'
        DIRTY_SCROLL = True
        DIRTY_PROMPT = True

        return True

    if pointinrect(x, y, geometry.get('toggle')):

        playbacktoggle()

        return True

    track = geometry.get('track')
    trackhit = [track[0], geometry['y'], track[2], geometry['height']] if track else None

    if pointinrect(x, y, trackhit):

        if float(PLAYBACK.get('duration', 0.0) or 0.0) <= 0.0:

            return True

        PLAYBACK_DRAGGING = True
        PLAYBACK_PREVIEW = playbackpositionfromx(x)
        DIRTY_SCROLL = True
        DIRTY_PROMPT = True

        return True

    return False


def handleplaybackmotion(x, y):

    global PLAYBACK_PREVIEW, DIRTY_SCROLL, DIRTY_PROMPT

    if not PLAYBACK_DRAGGING or not PLAYBACK:

        return False

    PLAYBACK_PREVIEW = playbackpositionfromx(x)
    DIRTY_SCROLL = True
    DIRTY_PROMPT = True

    return True


def handlepointerbutton(msg):

    global SCROLLBAR_DRAGGING, SCROLLBAR_DRAG_OFFSET, HSCROLLBAR_DRAGGING, SCROLLOFF, DIRTY_SCROLL, DIRTY_PROMPT, SELACTIVE, MOUSEDOWN, MOUSEDOWNBTN, MOUSEX, MOUSEY, SELREGION, SELANCHOR, SELEND, \
        PROMPTSELANCHOR, PROMPTSELEND, DOWNINPROMPT, DOWNDRAGGED, LASTCLICKX, LASTCLICKY, LASTCLICKTIME, CLICKCOUNT, DOWNX, DOWNY

    try:

        # read pointer button message
        button = int(msg.get('button', 0))

        state = str(msg.get('state', ''))

        x = int(msg.get('x', 0))

        y = int(msg.get('y', 0))

    except Exception as e:

        # pointer button message read error
        guiprint(f'> error reading pointer button {e}', colour=ERRORCOLOUR)
        return

    # only left button
    if button != 1:
        return

    if state == 'down':
        cancelsmoothscroll()

    if state == 'up' and handleplaybackbutton(x, y, False):

        MOUSEDOWN = False
        MOUSEDOWNBTN = 0
        MOUSEX = x
        MOUSEY = y
        return

    if state == 'down' and handleplaybackbutton(x, y, True):

        MOUSEDOWN = False
        MOUSEDOWNBTN = 0
        MOUSEX = x
        MOUSEY = y
        return

    # button release
    if state == 'up':

        MOUSEDOWN = False

        if DOWNINPROMPT and not DOWNDRAGGED:

            now = time.time()

            dx = x - LASTCLICKX
            dy = y - LASTCLICKY

            close = (dx * dx + dy * dy) <= (DBLCLICKDIST * DBLCLICKDIST)

            if close and (now - LASTCLICKTIME) <= DBLCLICKWINDOW:
                CLICKCOUNT += 1
            else:
                CLICKCOUNT = 1

            LASTCLICKTIME = now
            LASTCLICKX = x
            LASTCLICKY = y

            p = promptposfromxy(x, y)

            if CLICKCOUNT >= 3:

                selectpromptall()
                return

            if CLICKCOUNT == 2:

                selectpromptword(p)
                return

        MOUSEDOWNBTN = 0

        MOUSEX = x

        MOUSEY = y

        SCROLLBAR_DRAGGING = False

        HSCROLLBAR_DRAGGING = False

        # release hscrollbar if needed
        handlehscrollbutton(x, y, False)

        # finish selection drag
        if SELACTIVE:

            SELACTIVE = False

            selectiondirty(SELREGION)

        return

    # ignore other states
    if state != 'down':
        return

    # record mouse down
    MOUSEDOWN = True

    MOUSEDOWNBTN = 1

    MOUSEX = x

    MOUSEY = y

    DOWNX = x

    DOWNY = y

    DOWNDRAGGED = False

    try:
        DOWNINPROMPT = inprompt(x, y)
    except Exception:
        DOWNINPROMPT = False

    # horizontal scrollbar click
    if handlehscrollbutton(x, y, True):

        DIRTY_SCROLL = True

        DIRTY_PROMPT = True

        return

    try:

        # vertical scrollbar click if it exists and the click is inside track
        layout = contentlayout()
        rows = int(layout.get('rows', 0))
        total = int(layout.get('total', 0))

        if rows > 0 and total > rows:

            track_x, track_y, track_w, track_h = scrollbargeometry()

            if track_w > 0 and track_h > 0:

                if (x >= track_x and x < track_x + track_w and
                    y >= track_y and y < track_y + track_h):

                    try:
                        thumb_h = int(track_h * (rows / float(total)))
                    except Exception:
                        thumb_h = SCROLLBAR_MIN_THUMB

                    if thumb_h < SCROLLBAR_MIN_THUMB:
                        thumb_h = SCROLLBAR_MIN_THUMB

                    if thumb_h > track_h:
                        thumb_h = track_h

                    maxoff = max(0, total - rows)

                    off = SCROLLOFF

                    if off < 0:
                        off = 0

                    if off > maxoff:
                        off = maxoff

                    if track_h - thumb_h <= 0:

                        thumb_y = track_y

                    else:

                        try:
                            frac = 1.0 - (off / float(maxoff))
                        except Exception:
                            frac = 1.0

                        if frac < 0.0:
                            frac = 0.0

                        if frac > 1.0:
                            frac = 1.0

                        thumb_y = int(track_y + frac * (track_h - thumb_h))

                    # click on thumb starts drag
                    if y >= thumb_y and y < thumb_y + thumb_h:

                        SCROLLBAR_DRAGGING = True

                        SCROLLBAR_DRAG_OFFSET = y - thumb_y

                        return

                    # page up/down on track
                    if y < thumb_y:

                        page(1)

                        DIRTY_SCROLL = True

                        DIRTY_PROMPT = True

                        return

                    if y >= thumb_y + thumb_h:

                        page(-1)

                        DIRTY_SCROLL = True

                        DIRTY_PROMPT = True

                        return

    except Exception as e:

        # scrollbar click handling error
        guiprint(f'> error handling scrollbar click {e}', colour=ERRORCOLOUR)

    try:

        # start selection if not consumed by scrollbars
        clearselection(None)

        if inprompt(x, y):

            p = promptposfromxy(x, y)

            # single click down: normal drag selection start only
            SELREGION = "prompt"

            SELACTIVE = True

            PROMPTSELANCHOR = p

            PROMPTSELEND = p

            normaliseselection()

            selectiondirty("prompt")

            return

        if incontent(x, y):

            SELREGION = "content"

            SELACTIVE = True

            p = contentposfromxy(x, y)

            SELANCHOR = p

            SELEND = p

            normaliseselection()

            selectiondirty("content")

            return

    except Exception as e:

        # selection start error
        guiprint(f'> error starting selection {e}', colour=ERRORCOLOUR)
        return


def handlepointermotion(msg):

    global SCROLLBAR_DRAGGING, SCROLLBAR_DRAG_OFFSET, HSCROLLBAR_DRAGGING, SCROLLOFF, DIRTY_SCROLL, DIRTY_PROMPT, MOUSEDOWN, MOUSEY, MOUSEX, SELACTIVE, SELREGION, PROMPTSELEND, SELEND, DOWNX, DOWNY, DOWNDRAGGED

    try:

        # read pointer motion message
        x = int(msg.get('x', 0))

        y = int(msg.get('y', 0))

    except Exception as e:

        # pointer motion message read error
        guiprint(f'> error reading pointer motion {e}', colour=ERRORCOLOUR)
        return

    # track mouse
    MOUSEX = x

    MOUSEY = y

    if handleplaybackmotion(x, y):

        return

    if MOUSEDOWN:

        dx = x - DOWNX
        dy = y - DOWNY

        if (dx * dx + dy * dy) > (DBLCLICKDIST * DBLCLICKDIST):
            DOWNDRAGGED = True

    if HSCROLLBAR_DRAGGING:

        # horizontal scrollbar drag
        if handlehscrollmotion(x, y):

            DIRTY_SCROLL = True

            DIRTY_PROMPT = True

        return

    if SCROLLBAR_DRAGGING:

        try:

            # vertical scrollbar drag
            layout = contentlayout()
            rows = int(layout.get('rows', 0))
            total = int(layout.get('total', 0))

            if rows <= 0 or total <= rows:

                SCROLLBAR_DRAGGING = False

                return

            track_x, track_y, track_w, track_h = scrollbargeometry()

            if track_h <= 0:

                SCROLLBAR_DRAGGING = False

                return

            try:
                thumb_h = int(track_h * (rows / float(total)))
            except Exception:
                thumb_h = SCROLLBAR_MIN_THUMB

            if thumb_h < SCROLLBAR_MIN_THUMB:
                thumb_h = SCROLLBAR_MIN_THUMB

            if thumb_h > track_h:
                thumb_h = track_h

            maxoff = max(0, total - rows)

            if maxoff <= 0:

                SCROLLBAR_DRAGGING = False

                return

            new_thumb_y = y - SCROLLBAR_DRAG_OFFSET

            min_y = track_y

            max_y = track_y + track_h - thumb_h

            if new_thumb_y < min_y:
                new_thumb_y = min_y

            if new_thumb_y > max_y:
                new_thumb_y = max_y

            if track_h - thumb_h <= 0:

                frac = 1.0

            else:

                try:
                    frac = (new_thumb_y - track_y) / float(track_h - thumb_h)
                except Exception:
                    frac = 1.0

            if frac < 0.0:
                frac = 0.0

            if frac > 1.0:
                frac = 1.0

            try:
                new_off = int(round((1.0 - frac) * maxoff))
            except Exception:
                new_off = SCROLLOFF

            if new_off < 0:
                new_off = 0

            if new_off > maxoff:
                new_off = maxoff

            SCROLLOFF = new_off

            DIRTY_SCROLL = True

            DIRTY_PROMPT = True

            return

        except Exception as e:

            # vertical scrollbar drag error
            guiprint(f'> error handling scrollbar drag {e}', colour=ERRORCOLOUR)

            SCROLLBAR_DRAGGING = False

            return

    if not MOUSEDOWN:
        return

    if not SELACTIVE:
        return

    if SELREGION == "prompt":

        try:

            # update prompt selection
            p = promptposfromxy(x, y)

            PROMPTSELEND = p

            normaliseselection()

            selectiondirty("prompt")

        except Exception as e:

            guiprint(f'> error updating prompt selection {e}', colour=ERRORCOLOUR)

        return

    if SELREGION == "content":

        try:

            # update content selection
            p = contentposfromxy(x, y)

            SELEND = p

            normaliseselection()

            selectiondirty("content")

        except Exception as e:

            guiprint(f'> error updating content selection {e}', colour=ERRORCOLOUR)

        return


# directive functions
def directiveresult(value=None, directive='', code=None, message=''):

    global LASTDIRECTIVERESULT

    try:

        # preserve a complete result returned by a modern handler
        if isinstance(value, dict) and 'ok' in value:

            result = dict(value)
            result.setdefault('code', 'done' if result.get('ok') else 'failed')
            result.setdefault('message', '')
            result.setdefault('items', [])
            result.setdefault('data', {})

        else:

            ok = not bool(DIRECTIVEFAILED)

            if isinstance(value, bool):
                ok = value and ok

            elif isinstance(value, int):
                ok = value == 0 and ok

            result = {
                'ok': bool(ok),
                'code': code or ('done' if ok else 'failed'),
                'message': str(message or ''),
                'items': [],
                'data': {},
            }

        result['directive'] = str(directive or '')
        LASTDIRECTIVERESULT = result
        return result

    except Exception as e:

        LASTDIRECTIVERESULT = {
            'ok': False,
            'code': 'result_error',
            'message': str(e),
            'items': [],
            'data': {},
            'directive': str(directive or ''),
        }
        return LASTDIRECTIVERESULT


def matcheddirective(parts):

    """Return the longest registered directive prefix and its word count."""

    values = [str(value) for value in (parts or [])]

    for count in range(len(values), 0, -1):

        candidate = ' '.join(values[:count]).casefold()

        if candidate in DIRECTIVES:
            return candidate, count

    return None, 0


def rundirective(line, echo=True):

    global DIRECTIVEACTIVE, DIRECTIVEFAILED, LASTDIRECTIVERESULT

    result = None

    try:

        DIRECTIVEACTIVE = True
        DIRECTIVEFAILED = False

        if echo:
            guiprint(f'{PROMPT} {line}', colour=TEXTCOLOUR)

        try:

            parts = shlex.split(line.strip())

        except Exception:

            parts = line.strip().split()

        if not parts:
            return

        cmd, count = matcheddirective(parts)

        if cmd:

            spec = directivespec(cmd)

            if HEADLESS and spec and not spec.get('headless', True):

                guiprint(f'> {cmd} is not available without the graphical shell', colour=ERRORCOLOUR)
                return directiveresult(None, cmd, code='graphical_only')

            if spec and spec.get('architect'):
                # Python mutation handlers obtain a same-process, short-lived
                # broker authorization immediately before their request.
                pass

            result = DIRECTIVES[cmd](parts[count:])
            return directiveresult(result, cmd)

        unknown(parts[0])
        DIRECTIVEFAILED = True
        return directiveresult(None, parts[0], code='unknown')

    except Exception as e:

        DIRECTIVEFAILED = True
        guiprint(f'> error handling command {e}', colour=ERRORCOLOUR)
        return directiveresult(None, '', code='exception', message=str(e))

    finally:

        DIRECTIVEACTIVE = False


def executeline(cursor_on):

    global INPUTBUF, CURSORPOS, DIRTY_PROMPT, SOCK, WINID

    try:

        # capture line before clearing prompt
        line = INPUTBUF.strip()

    except Exception:

        line = ""

    if line:

        # add to history
        addhistory(line)

    # clear prompt immediately so it is not stuck during foreground execution
    INPUTBUF = ""

    CURSORPOS = 0

    DIRTY_PROMPT = True

    # repaint immediately so user sees cleared prompt
    drawcontent(cursor_on=False)

    if SOCK:
        pollserver()

    presentbrick()

    try:

        # execute directive (may block)
        if line:
            rundirective(line)

    except Exception as e:

        # directive execution error
        guiprint(f'> error running directive {e}', colour=ERRORCOLOUR)


def splitchain(line):

    try:

        if line is None:
            return []

    except Exception:
        return []

    try:

        out = []
        
        buf = ""

        insingle = False
        
        indouble = False
        
        escape = False

        for ch in str(line):

            if escape:

                buf += ch
                
                escape = False
                
                continue

            if ch == "\\":

                buf += ch
                
                escape = True
                
                continue

            if ch == "'" and not indouble:

                insingle = not insingle
                
                buf += ch
                
                continue

            if ch == '"' and not insingle:

                indouble = not indouble
                
                buf += ch
                
                continue

            if ch == ";" and not insingle and not indouble:

                seg = buf.strip()

                if seg:
                    out.append(seg)

                buf = ""
                
                continue

            buf += ch

        seg = buf.strip()

        if seg:
            out.append(seg)

        return out

    except Exception:

        return []


def splitchainpos(line):

    try:

        if line is None:
            return []

    except Exception:
        return []

    try:

        out = []

        buf = ""

        segstart = 0

        insingle = False
        
        indouble = False
        
        escape = False
        
        i = 0
        
        s = str(line)

        for ch in s:

            if escape:

                buf += ch
                escape = False
                i += 1
                continue

            if ch == "\\":

                buf += ch
                escape = True
                i += 1
                continue

            if ch == "'" and not indouble:

                insingle = not insingle
                buf += ch
                i += 1
                continue

            if ch == '"' and not insingle:

                indouble = not indouble
                buf += ch
                i += 1
                continue

            if ch == ";" and not insingle and not indouble:

                raw = buf
                rawstart = segstart

                if raw.strip():
                    out.append((raw, rawstart))

                buf = ""

                segstart = i + 1

                i += 1
                continue

            buf += ch
            
            i += 1

        raw = buf
        
        rawstart = segstart

        if raw.strip():
            out.append((raw, rawstart))

        return out

    except Exception:

        return []


def runchain(line, echo=True):

    segments = splitchain(line)
    results = []

    if not segments:
        return results

    for seg in segments:

        try:
            results.append(rundirective(seg, echo=echo))
        except Exception as e:
            results.append(directiveresult(None, seg, code='exception', message=str(e)))

    return results


def outputfailed(lines):

    prefixes = (
        '> error',
        '> permission denied',
        '> failed',
        '> could not',
        '> no such',
    )

    for line in lines:

        value = str(line).strip().casefold()

        if value.startswith(prefixes):
            return True

    return False


def headlesscommand(args=None):

    global HEADLESS, DIRECTIVEACTIVE, DIRECTIVEFAILED

    command = ' '.join([str(arg) for arg in (args or [])]).strip()

    if not command:

        try:
            command = sys.stdin.read().strip()
        except Exception:
            command = ''

    if not command:

        result = {
            'format': 1,
            'passed': False,
            'command': '',
            'results': [],
            'output': [],
            'stdout': [],
            'stderr': ['no directive given'],
            'cwd': formatlocation(os.getcwd()),
        }
        print(json.dumps(result, sort_keys=True, separators=(',', ':')))
        return 1

    standard = io.StringIO()
    errors = io.StringIO()
    previous = HEADLESS
    HEADLESS = True
    DIRECTIVEACTIVE = False
    DIRECTIVEFAILED = False
    SCROLL.clear()
    STYLES.clear()

    try:

        with contextlib.redirect_stdout(standard), contextlib.redirect_stderr(errors):
            results = runchain(command, echo=False)

    except BaseException as e:

        results = [{
            'ok': False,
            'code': 'headless_exception',
            'message': str(e),
            'items': [],
            'data': {},
            'directive': command,
        }]

    finally:
        HEADLESS = previous

    screen = [str(line) for line in SCROLL]
    stdout = standard.getvalue().splitlines()
    stderr = errors.getvalue().splitlines()
    failedoutput = outputfailed(stdout) or outputfailed(stderr)

    if failedoutput and results and all(bool(result.get('ok')) for result in results):

        results[-1]['ok'] = False
        results[-1]['code'] = 'output_error'
        results[-1]['message'] = 'directive backend reported an error'

    passed = bool(results) and all(bool(result.get('ok')) for result in results) and not stderr and not failedoutput
    result = {
        'format': 1,
        'passed': passed,
        'command': command,
        'results': results,
        'output': screen + stdout,
        'stdout': stdout,
        'stderr': stderr,
        'cwd': formatlocation(os.getcwd()),
    }
    print(json.dumps(result, sort_keys=True, separators=(',', ':'), default=str))
    return 0 if passed else 1


def directivebounds(text):

    try:

        if text is None:
            return (None, None)

    except Exception:
        return (None, None)

    try:

        n = len(text)
        
        if n <= 0:
            return (None, None)

        # skip leading spaces
        i = 0
        
        while i < n and text[i] == ' ':
            i += 1

        if i >= n:
            return (None, None)

        start = i
        words = []
        ends = []

        while i < n:

            wordstart = i

            while i < n and text[i] != ' ':
                i += 1

            words.append(text[wordstart:i])
            ends.append(i)

            while i < n and text[i] == ' ':
                i += 1

        directive, count = matcheddirective(words)

        if directive and count > 0:
            return (start, ends[count - 1])
        
        return (None, None)

    except Exception:
        return (None, None)


def directiveinfo(text):

    try:

        b0, b1 = directivebounds(text)

    except Exception:
        return (None, None, None)

    if b0 is None or b1 is None:
        return (None, None, None)

    try:

        directive = text[b0:b1]

    except Exception:

        directive = None

    try:

        count = len(str(directive).split())

    except Exception:

        count = 1

    return (directive, b0, b1)


def tokenbounds(text):

    try:

        if text is None:
            return []

    except Exception:
        return []

    try:

        n = len(text)
        i = 0
        out = []

        while i < n:

            # skip spaces
            while i < n and text[i] == ' ':
                i += 1

            if i >= n:
                break

            start = i

            # quoted token
            if text[i] in ("'", '"'):

                q = text[i]
                i += 1

                while i < n and text[i] != q:
                    i += 1

                if i < n and text[i] == q:
                    i += 1

                end = i

                tok = text[start:end]
                out.append((tok, start, end))
                continue

            # normal token
            while i < n and text[i] != ' ':
                i += 1

            end = i

            tok = text[start:end]
            out.append((tok, start, end))

        return out

    except Exception:
        return []


def stripquotes(tok):

    try:

        if tok is None:
            return ''

    except Exception:
        return ''

    try:

        if len(tok) >= 2 and ((tok[0] == '"' and tok[-1] == '"') or (tok[0] == "'" and tok[-1] == "'")):
            return tok[1:-1]

        return tok

    except Exception:
        return tok


def joinparts(parts):

    try:

        return ' '.join(parts)

    except Exception:

        return ''


def pathargumentsvalid(tokens, want):

    try:
        parts = [stripquotes(str(token)) for token in tokens if str(token)]
    except Exception:
        return False

    if not parts:
        return False

    joined = joinparts(parts)

    if not any(haswild(part) for part in parts):

        try:
            return sourcekind(os.path.abspath(resolvepath(joined)), want)
        except Exception:
            return False

    def patternvalid(pattern):

        try:
            resolved = os.path.abspath(resolvepath(pattern))
        except Exception:
            return False

        if not haswild(resolved):
            return sourcekind(resolved, want)

        return any(sourcekind(match, want) for match in glob.glob(resolved))

    # A quoted wildcard path may contain spaces and remains one expression.
    if patternvalid(joined):
        return True

    expandedparts = list(parts)

    if len(expandedparts) == 1 and ' ' in expandedparts[0]:
        expandedparts = [part for part in expandedparts[0].split(' ') if part]

    # Connector-free wildcard grammar: an existing spaced tier followed by
    # one or more wildcard patterns.
    for index in range(len(expandedparts) - 1, 0, -1):

        base = joinparts(expandedparts[:index])
        patterns = expandedparts[index:]

        if not patterns or not all(haswild(pattern) for pattern in patterns):
            continue

        try:
            basepath = os.path.abspath(resolvepath(base))
        except Exception:
            continue

        if os.path.isdir(basepath) and all(patternvalid(os.path.join(basepath, pattern)) for pattern in patterns):
            return True

    # Multiple independent sources are valid only when every token resolves;
    # this prevents trailing grammar words from becoming semibold.
    return all(patternvalid(part) for part in parts)


def findexistingdir(tokens):

    try:

        for i in range(len(tokens), 0, -1):

            if pathargumentsvalid(tokens[:i], 'dir'):
                return i

        return None

    except Exception:

        return None


def findexistingfile(tokens):

    try:

        # strip trailing behind flag for run
        if tokens and tokens[-1] == 'behind':
            tokens = tokens[:-1]

        for i in range(len(tokens), 0, -1):

            if pathargumentsvalid(tokens[:i], 'file'):
                return i

        return None

    except Exception:
        return None


def findsplitexisting(tokens, want):

    try:

        if want not in ('file', 'dir'):
            return None

    except Exception:
        return None

    try:

        for i in range(len(tokens), 0, -1):

            if pathargumentsvalid(tokens[:i], want):
                return i

        return None

    except Exception:
        return None


def semiboldbounds(text):

    try:

        directive, b0, b1 = directiveinfo(text)

    except Exception:
        return []

    if directive is None:
        return []

    try:

        if b1 >= len(text) or text[b1] != ' ':
            return []

    except Exception:
        return []

    try:

        dmap = {}

        for spec in DIRECTIVESPECS:

            grammar = dict(spec.get('grammar', {}))
            mode = grammar.get('highlight')
            want = grammar.get('highlight_type')

            if not mode or not want:
                continue

            for name in [spec.get('name', '')] + list(spec.get('aliases', [])):
                dmap[str(name)] = (
                    str(want),
                    str(mode),
                    [str(value).casefold() for value in grammar.get('connectors', [])],
                )

    except Exception:
        return []

    if directive not in dmap:
        return []

    want, mode, connectors = dmap[directive]

    tb = tokenbounds(text)

    try:

        dcount = len(str(directive).split())

    except Exception:

        dcount = 1

    if len(tb) <= dcount:
        return []

    argtb = tb[dcount:]

    args = [stripquotes(t[0]) for t in argtb]

    if mode == 'single':

        if want == 'dir':

            n = findexistingdir(args)

        else:

            n = findexistingfile(args)

        if n is None:
            return []

        s = argtb[0][1]

        e = argtb[n - 1][2]

        return [(s, e)]

    if mode == 'split':

        n = findsplitexisting(args, want)

        if n is None:
            return []

        s = argtb[0][1]

        e = argtb[n - 1][2]

        return [(s, e)]

    if mode == 'pair':

        connectorpositions = [
            index
            for index, value in enumerate(args)
            if str(value).casefold() in connectors
        ]

        for connectorindex in reversed(connectorpositions):

            if connectorindex <= 0 or connectorindex >= len(args) - 1:
                continue

            sources = args[:connectorindex]
            destination = args[connectorindex + 1:]

            if not pathargumentsvalid(sources, want):
                continue

            spans = [(argtb[0][1], argtb[connectorindex - 1][2])]

            if pathargumentsvalid(destination, 'dir'):
                spans.append((argtb[connectorindex + 1][1], argtb[-1][2]))

            return spans

        n = findsplitexisting(args, want)

        if n is None:
            return []

        spans = []

        s0 = argtb[0][1]

        e0 = argtb[n - 1][2]

        spans.append((s0, e0))

        if n < len(args):

            if pathargumentsvalid(args[n:], 'dir'):

                s1 = argtb[n][1]
                e1 = argtb[-1][2]
                spans.append((s1, e1))

        return spans

    if mode == 'writein':

        if len(args) < 2:
            return []

        for i in range(1, len(args)):

            filecand = joinparts(args[i:])

            filecand = stripquotes(filecand)

            try:

                ap = os.path.abspath(resolvepath(filecand))

            except Exception:

                ap = INVALIDPATH

            if os.path.exists(ap) and os.path.isfile(ap):

                s = argtb[i][1]

                e = argtb[-1][2]

                return [(s, e)]

        return []

    if mode == 'rubbish':

        n = findexistingfile(args)

        if n is None:
            return []

        try:

            cand = joinparts(args[:n])

            ap = os.path.abspath(resolvepath(stripquotes(cand)))

        except Exception:
            return []

        try:

            if not ap.startswith('/.rubbish/'):
                return []

        except Exception:
            return []

        s = argtb[0][1]

        e = argtb[n - 1][2]

        return [(s, e)]

    return []


def haswild(text):

    try:
        return ('*' in text) or ('?' in text) or ('[' in text)

    except Exception:
        return False


def expandwild(args):

    try:

        out = []

        for a in args:

            # normalise to absolute path so patterns work from anywhere
            try:

                ap = os.path.abspath(resolvepath(a))

            except Exception:

                ap = INVALIDPATH

            # no wildcard, keep literal
            if not haswild(ap):

                out.append(ap)

                continue

            # expand
            matches = glob.glob(ap)

            # if no matches, keep literal (so you still get a useful "does not exist" error)
            if not matches:

                out.append(ap)

                continue

            # stable order
            matches.sort()

            out.extend(matches)

        return out

    except Exception:
        return args


def sourcekind(path, want=None):

    try:

        if want == 'file':
            return os.path.isfile(path)

        if want == 'dir':
            return os.path.isdir(path)

        return os.path.exists(path)

    except Exception:
        return False


def expandwildsources(tokens, want=None):

    try:
        rawtokens = [str(token) for token in tokens if str(token)]
    except Exception:
        return []

    if not rawtokens:
        return []

    found = []

    def addpattern(pattern):

        try:
            resolved = os.path.abspath(resolvepath(pattern))
        except Exception:
            return

        matches = glob.glob(resolved) if haswild(resolved) else [resolved]

        for match in sorted(matches):

            if sourcekind(match, want) and match not in found:
                found.append(match)

    # A quoted or connector-joined source remains one logical pattern.
    joined = ' '.join(rawtokens).strip()
    addpattern(joined)

    if found:
        return found

    # Without a connector, Brick historically allowed a spaced tier followed
    # by one or more separate wildcard patterns:
    # copy /the one/logs *.log 2/
    parts = list(rawtokens)

    if len(parts) == 1 and ' ' in parts[0]:
        parts = [part for part in parts[0].split(' ') if part]

    for index in range(len(parts) - 1, 0, -1):

        base = ' '.join(parts[:index]).strip()
        patterns = parts[index:]

        if not patterns or not all(haswild(pattern) for pattern in patterns):
            continue

        try:
            basepath = os.path.abspath(resolvepath(base))
        except Exception:
            continue

        if not os.path.isdir(basepath):
            continue

        for pattern in patterns:
            addpattern(os.path.join(basepath, pattern))

        if found:
            return found

    # Also preserve multiple independent literal/pattern sources.
    for token in rawtokens:
        addpattern(token)

    return found


def wildcardarguments(args, want=None, connector='to'):

    try:
        tokens = [str(arg) for arg in args]
    except Exception:
        return [], INVALIDPATH

    positions = [index for index, token in enumerate(tokens) if token.lower() == connector]

    for index in reversed(positions):

        if index <= 0 or index >= len(tokens) - 1:
            continue

        sources = expandwildsources(tokens[:index], want=want)

        try:
            destination = os.path.abspath(resolvepath(' '.join(tokens[index + 1:])))
        except Exception:
            destination = INVALIDPATH

        return sources, destination

    # With no connector, find the split whose left side expands to sources and
    # whose right side is an existing destination tier. This retains the old
    # connector-free grammar while supporting spaces on either side.
    for index in range(1, len(tokens)):

        try:
            destination = os.path.abspath(resolvepath(' '.join(tokens[index:])))
        except Exception:
            continue

        if not os.path.isdir(destination):
            continue

        sources = expandwildsources(tokens[:index], want=want)

        if sources:
            return sources, destination

    # A single expanded source may target a new path rather than an existing
    # tier. Once the source boundary is provable, the remaining tokens are the
    # connector-free destination, including any spaces.
    for index in range(1, len(tokens)):

        sources = expandwildsources(tokens[:index], want=want)

        if not sources:
            continue

        try:
            destination = os.path.abspath(resolvepath(' '.join(tokens[index:])))
        except Exception:
            destination = INVALIDPATH

        return sources, destination

    # Preserve the former last-argument destination fallback so a useful
    # preflight error is returned for a missing destination or empty match.
    if len(tokens) >= 2:

        try:
            destination = os.path.abspath(resolvepath(tokens[-1]))
        except Exception:
            destination = INVALIDPATH

        return expandwildsources(tokens[:-1], want=want), destination

    return [], INVALIDPATH


def bricklsmmutationallowed(path):

    try:

        target = os.path.realpath(os.path.abspath(resolvepath(str(path))))

    except Exception:

        return False

    # The runtime layout invariant is enforced by the kernel for both roles.
    for root in BRICKLSMFORBIDDENROOTS:

        if target == root or target.startswith(root + os.sep):
            return False

    try:

        if not arch.check(target):
            return False

    except Exception:

        return False

    # Brick is not an authorised daemon owner for these process-aware LSM
    # write ACLs. There is no ambient role bypass.
    for root in BRICKLSMMASTERDENIED:

        if target == root or target.startswith(root + os.sep):
            return False

    return True


def allowpaths(paths):

    try:

        # Compatibility check only; authorization is never a mutable role.
        arch.loadrole()

    except Exception as e:

        guiprint(f'> error refreshing architect role {e}', colour=ERRORCOLOUR)
        return False

    try:

        pending = [paths]
        targets = []

        while pending:

            value = pending.pop(0)

            if value is None:
                continue

            if isinstance(value, (list, tuple, set)):

                pending[0:0] = list(value)
                continue

            targets.append(value)

    except Exception as e:

        guiprint(f'> error preparing permission check {e}', colour=ERRORCOLOUR)
        return False

    if not targets:
        return True

    for path in targets:

        try:

            # resolve the complete logical path after Brick has handled spaces
            target = os.path.abspath(resolvepath(str(path)))

            allowed = bricklsmmutationallowed(target)

        except Exception as e:

            # fail closed if architect cannot decide
            guiprint(f'> error checking permission {e}', colour=ERRORCOLOUR)
            return False

        if not allowed:

            guiprint('> permission denied', colour=ERRORCOLOUR)
            return False

    return True


def creationmutationpaths(path):

    if path is None:
        return []

    try:

        target = os.path.abspath(resolvepath(str(path)))

    except Exception:

        return []

    missing = []
    parent = os.path.dirname(target)

    while parent and parent != os.path.dirname(parent) and not os.path.exists(parent):

        missing.append(parent)
        parent = os.path.dirname(parent)

    missing.reverse()
    missing.append(target)
    return missing


def transactiontargets(sources, destination):

    try:

        resolved = [os.path.abspath(resolvepath(str(source))) for source in sources]
        targetroot = os.path.abspath(resolvepath(str(destination)))

        if len(resolved) > 1 and not os.path.isdir(targetroot):
            return None, 'destination must be an existing tier for multiple items'

        targets = []

        for source in resolved:

            target = targetroot

            if os.path.isdir(targetroot):
                target = os.path.join(targetroot, os.path.basename(source))

            targets.append(target)

        if len(set(targets)) != len(targets):
            return None, 'more than one source resolves to the same destination'

        for source, target in zip(resolved, targets):

            if os.path.exists(target):
                return None, f'destination {target} already exists'

            if os.path.isdir(source):

                try:

                    if os.path.commonpath([source, target]) == source:
                        return None, f'cannot place {source} inside itself'

                except Exception:
                    pass

        return list(zip(resolved, targets)), ''

    except Exception as e:
        return None, f'error preparing transaction {e}'


def transactionremove(path):

    try:

        if os.path.isdir(path):
            shutil.rmtree(path)
        elif os.path.exists(path):
            os.unlink(path)

        return True

    except Exception:
        return False


def transactiondiagnosticcopy(source, target, *args, **kwargs):

    global TRANSACTIONCOPYCOUNT

    TRANSACTIONCOPYCOUNT += 1

    if TRANSACTIONCOPYFAILAT and TRANSACTIONCOPYCOUNT == TRANSACTIONCOPYFAILAT:
        raise OSError('diagnostic copy failure')

    return TRANSACTIONCOPYORIGINAL(source, target, *args, **kwargs)


def transactiondiagnosticmove(source, target, *args, **kwargs):

    global TRANSACTIONMOVECOUNT

    TRANSACTIONMOVECOUNT += 1

    if TRANSACTIONMOVEFAILAT and TRANSACTIONMOVECOUNT == TRANSACTIONMOVEFAILAT:
        raise OSError('diagnostic move failure')

    return TRANSACTIONMOVEORIGINAL(source, target, *args, **kwargs)


def transactioncopy(sources, destination):

    pairs, error = transactiontargets(sources, destination)

    if not pairs:

        guiprint(f'> {error}', colour=ERRORCOLOUR)
        return {'ok': False, 'code': 'preflight_failed', 'message': error, 'items': [], 'data': {}}

    if not allowpaths([target for _, target in pairs]):
        return {'ok': False, 'code': 'permission_denied', 'message': 'permission denied', 'items': [], 'data': {}}

    created = []
    items = []

    try:

        for source, target in pairs:

            created.append(target)

            if os.path.isdir(source):
                shutil.copytree(source, target)
            else:
                shutil.copy2(source, target)

            items.append({'source': source, 'target': target, 'state': 'copied'})

    except Exception as e:

        rollback = True

        for target in reversed(created):

            if not transactionremove(target):
                rollback = False

        code = 'rolled_back' if rollback else 'rollback_failed'
        message = f'copy transaction failed {e}'
        guiprint(f'> {message}; {"rolled back" if rollback else "rollback incomplete"}', colour=ERRORCOLOUR)
        return {'ok': False, 'code': code, 'message': message, 'items': items, 'data': {'rolled_back': rollback}}

    names = ', '.join(os.path.basename(source) for source, _ in pairs)
    guiprint(f'> copied {names}', colour=TEXTCOLOUR)
    return {'ok': True, 'code': 'copied', 'message': '', 'items': items, 'data': {'count': len(items)}}


def transactionmove(sources, destination):

    pairs, error = transactiontargets(sources, destination)

    if not pairs:

        guiprint(f'> {error}', colour=ERRORCOLOUR)
        return {'ok': False, 'code': 'preflight_failed', 'message': error, 'items': [], 'data': {}}

    checkpaths = [source for source, _ in pairs] + [target for _, target in pairs]

    if not allowpaths(checkpaths):
        return {'ok': False, 'code': 'permission_denied', 'message': 'permission denied', 'items': [], 'data': {}}

    moved = []
    items = []

    try:

        for source, target in pairs:

            shutil.move(source, target)
            moved.append((source, target))
            items.append({'source': source, 'target': target, 'state': 'moved'})

    except Exception as e:

        rollback = True

        for source, target in reversed(moved):

            try:

                if os.path.exists(source) or not os.path.exists(target):
                    rollback = False
                    continue

                shutil.move(target, source)

            except Exception:
                rollback = False

        code = 'rolled_back' if rollback else 'rollback_failed'
        message = f'move transaction failed {e}'
        guiprint(f'> {message}; {"rolled back" if rollback else "rollback incomplete"}', colour=ERRORCOLOUR)
        return {'ok': False, 'code': code, 'message': message, 'items': items, 'data': {'rolled_back': rollback}}

    names = ', '.join(os.path.basename(source) for source, _ in pairs)
    guiprint(f'> moved {names}', colour=TEXTCOLOUR)
    return {'ok': True, 'code': 'moved', 'message': '', 'items': items, 'data': {'count': len(items)}}


def connectorpaths(args, connector='to', want=None):

    try:

        tokens = [str(arg) for arg in args]

    except Exception:
        return None

    positions = [index for index, token in enumerate(tokens) if token.lower() == connector]

    for index in reversed(positions):

        if index <= 0 or index >= len(tokens) - 1:
            continue

        left = ' '.join(tokens[:index]).strip()
        right = ' '.join(tokens[index + 1:]).strip()

        if not left or not right:
            continue

        try:

            resolvedleft = resolvepath(left)

            if want == 'file' and not os.path.isfile(resolvedleft) and not haswild(left):
                continue

            if want == 'dir' and not os.path.isdir(resolvedleft) and not haswild(left):
                continue

            if want == 'path' and not os.path.exists(resolvedleft) and not haswild(left):
                continue

        except Exception:
            continue

        return left, right

    return None


def catalogueconnector(directive, args, connector=None):

    spec = directivespec(directive)
    grammar = dict(spec.get('grammar', {})) if spec else {}
    connectors = list(grammar.get('connectors', []))

    if connector:
        connectors = [str(connector)] if str(connector) in connectors else []

    want = grammar.get('source')

    for word in connectors:

        connected = connectorpaths(args, str(word), want)

        if connected:
            return connected

    return None


def positionalpair(args, want='path'):

    try:
        tokens = [str(arg) for arg in args]
    except Exception:
        return None

    for index in range(1, len(tokens)):

        left = ' '.join(tokens[:index]).strip()
        right = ' '.join(tokens[index:]).strip()

        try:
            leftpath = resolvepath(left)
            rightpath = resolvepath(right)
        except Exception:
            continue

        if sourcekind(leftpath, want) and sourcekind(rightpath, want):
            return left, right

    return None


def recursivearguments(args, directive=None):

    try:

        tokens = [str(arg) for arg in (args or [])]
        maximum = None
        spec = directivespec(directive) if directive else None
        grammar = dict(spec.get('grammar', {})) if spec else {}
        terms = [str(value).casefold() for value in grammar.get('terms', [])]

        if (
            len(tokens) >= 4
            and tokens[-4].lower() == 'up'
            and tokens[-3].lower() == 'to'
            and tokens[-1].lower() in ('level', 'levels')
            and (not terms or 'up to levels' in terms)
        ):

            maximum = int(tokens[-2])

            if maximum < 0:
                maximum = 0

            tokens = tokens[:-4]

        path = ' '.join(tokens).strip() if tokens else '.'

        return path, maximum

    except Exception:

        return ' '.join([str(arg) for arg in (args or [])]).strip() or '.', None



## directives

# misc directives
def version(args=None):

    # line above
    guiprint()

    # T1OS version line
    guiprint(f'> the one os version {OSVERSION}', colour=TEXTCOLOUR)

    # line below
    guiprint()


def role(args=None):

    # load current role from master file
    current = arch.loadrole()

    # print current role
    guiprint(f'> role {current}', colour=TEXTCOLOUR)


def _retired_architectdir_legacy(args=None):

    try:

        # load current role
        current = arch.loadrole()

    except Exception as e:

        # role load error
        guiprint(f'> error loading role {e}', colour=ERRORCOLOUR)
        return

    # revert to master
    if current == 'architect':

        try:

            # revert prompt
            resp = arch.guiline('> you are currently architect. revert to master? (yes/no) ')

        except (EOFError, KeyboardInterrupt):

            # cancelled
            return

        if resp.lower() != 'yes':

            # remain as architect
            guiprint('> remaining as architect', colour=TEXTCOLOUR)
            return

        # password prompt (brick-side)
        pw = arch.readpass('> enter master password ')

        if not pw:

            # blank or cancelled
            guiprint('> cancelled', colour=TEXTCOLOUR)
            return

        try:

            # call architect cli helper
            res = subprocess.run(
                [sys.executable, '/the one/build/architect/architect.py', 'to-master'],
                input=(pw + '\n').encode('utf-8'),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )

        except FileNotFoundError:

            # helper missing
            guiprint('> architect software not found', colour=ERRORCOLOUR)
            return

        except PermissionError:

            # permission denied
            guiprint('> permission denied', colour=ERRORCOLOUR)
            return

        except Exception as e:

            # spawn error
            guiprint(f'> error running architect {e}', colour=ERRORCOLOUR)
            return

        # forward stdout
        try:

            if res.stdout:

                out = res.stdout.decode('utf-8', errors='replace')

                for line in out.splitlines():

                    guiprint(line, colour=TEXTCOLOUR)

        except Exception as e:

            # stdout decode error
            guiprint(f'> error decoding architect output {e}', colour=ERRORCOLOUR)

        # forward stderr
        try:

            if res.stderr:

                err = res.stderr.decode('utf-8', errors='replace')

                for line in err.splitlines():

                    guiprint(f'> {line}', colour=ERRORCOLOUR)

        except Exception as e:

            # stderr decode error
            guiprint(f'> error decoding architect errors {e}', colour=ERRORCOLOUR)

        # on success, sync in-process role
        if res.returncode == 0:


            arch.currentrole = 'master'

        return

    # become architect
    if current == 'master':

        try:

            # warning prompt
            guiprint('> architect can modify anything in the operating system. becoming so can lead to irreparable damage to the system.', colour=TEXTCOLOUR)

            first = arch.guiline('  do you want to become architect? (yes/no) ')

            if first.lower() != 'yes':

                guiprint('> remaining as master', colour=TEXTCOLOUR)
                return

            confirm = arch.guiline('> are you sure? (yes/no) ')

            if confirm.lower() != 'yes':

                guiprint('> remaining as master', colour=TEXTCOLOUR)
                return

            # password prompt (brick-side)
            pw = arch.readpass('> enter master password ')

            if not pw:

                guiprint('> cancelled', colour=TEXTCOLOUR)
                return

        except (EOFError, KeyboardInterrupt):

            # cancelled
            return

        try:

            # call architect cli helper
            res = subprocess.run(
                [sys.executable, '/the one/build/architect/architect.py', 'to-architect'],
                input=(pw + '\n').encode('utf-8'),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )

        except FileNotFoundError:

            guiprint('> architect software not found', colour=ERRORCOLOUR)
            return

        except PermissionError:

            guiprint('> permission denied', colour=ERRORCOLOUR)
            return

        except Exception as e:

            guiprint(f'> error running architect {e}', colour=ERRORCOLOUR)
            return

        # forward stdout
        try:

            if res.stdout:

                out = res.stdout.decode('utf-8', errors='replace')

                for line in out.splitlines():

                    guiprint(line, colour=TEXTCOLOUR)

        except Exception as e:

            guiprint(f'> error decoding architect output {e}', colour=ERRORCOLOUR)

        # forward stderr
        try:

            if res.stderr:

                err = res.stderr.decode('utf-8', errors='replace')

                for line in err.splitlines():

                    guiprint(f'> {line}', colour=ERRORCOLOUR)

        except Exception as e:

            guiprint(f'> error decoding architect errors {e}', colour=ERRORCOLOUR)

        # on success, sync in-process role
        if res.returncode == 0:


            arch.currentrole = 'architect'


def architectdir(args=None):
    guiprint(
        '> global architect mode is retired; protected actions request one-time authorisation',
        colour=TEXTCOLOUR)
    return {
        'ok': True,
        'authorization': 'trusted application',
        'message': 'protected actions request one-time authorisation.',
    }


def exitdir(args=None):

    global RUNNING

    # print exit message
    guiprint('> exiting', colour=TEXTCOLOUR)

    # stop main loop so it can repaint then fall into finally
    RUNNING = False
    return


def shutdown(args=None):

    global RUNNING

    guiprint('> shutting down', colour=TEXTCOLOUR)
    savehistory()

    try:
        requestpower('poweroff')

        while RUNNING:
            time.sleep(0.05)

    except (PowerRequestError, OSError, ValueError) as error:
        guiprint(f'> shut down failed: {error}', colour=ERRORCOLOUR)


def restart(args=None):

    global RUNNING

    guiprint('> restarting', colour=TEXTCOLOUR)
    savehistory()

    try:
        requestpower('restart')

        while RUNNING:
            time.sleep(0.05)

    except (PowerRequestError, OSError, ValueError) as error:
        guiprint(f'> restart failed: {error}', colour=ERRORCOLOUR)


def logout(args=None):
    guiprint('> logging out', colour=TEXTCOLOUR)
    try:
        requestsessionlogout(timeout=10.0)
    except Exception as error:
        guiprint(f'> log out failed: {error}', colour=ERRORCOLOUR)


def unknown(dir):

    # print unknown directive message
    guiprint(f'> unknown directive {dir}', colour=TEXTCOLOUR)


def cleardir(args=None):

    try:

        SCROLL.clear()

        STYLES.clear()

        drawheader()

    except Exception as e:

        guiprint(f'> error clearing {e}', colour=ERRORCOLOUR)


def timedir(args=None):

    # open atreyan system time file
    try:
        with open('/the one/settings/time/atreyan.txt') as f:
            time = f.read().strip()

    # if the time file cannot be read
    except (FileNotFoundError, PermissionError) as e:
        guiprint(f'> could not read time file {e}', colour=ERRORCOLOUR)
        return

    # line above
    guiprint()

    # print datetime
    guiprint(time, colour=TEXTCOLOUR)

    # line below
    guiprint()


def help(args=None):

    try:
        requested = ' '.join(
            str(arg) for arg in (args or [])).strip().casefold()
        categories = list(DIRECTIVECATEGORIES)
        if requested:
            category = next((
                name for name in categories
                if requested == str(name).casefold()
            ), None)
            if category is None:
                guiprint('> help accepts a directive category',
                         colour=ERRORCOLOUR)
                return 1
            records = []
            for spec in DIRECTIVESPECS:
                if spec.get('category') != category:
                    continue
                aliases = ', '.join(spec.get('aliases', []))
                usage = spec.get('usages', [''])
                records.append([
                    str(spec.get('name', '')),
                    aliases,
                    str(spec.get('description', '')),
                    str(usage[0] if usage else ''),
                ])
            guiprint()
            guiprint(f'{category} directives', colour=TEXTCOLOUR, bold=True)
            guiprint()
            showtable(
                ['directive', 'aliases', 'description', 'usage'], records)
            guiprint()
            return 0

        guiprint('> available directives', colour=TEXTCOLOUR)
        guiprint('> use help <category> to show one category',
                 colour=TEXTCOLOUR)
        for category in categories:
            records = []
            for spec in DIRECTIVESPECS:
                if spec.get('category') != category:
                    continue
                aliases = ', '.join(spec.get('aliases', []))
                records.append([
                    str(spec.get('name', '')),
                    aliases,
                    str(spec.get('description', '')),
                ])
            if not records:
                continue
            guiprint()
            guiprint(str(category), colour=TEXTCOLOUR, bold=True)
            guiprint()
            showtable(['directive', 'aliases', 'description'], records)
        guiprint()
        return 0

    except Exception as e:

        guiprint(f'> error preparing help {e}', colour=ERRORCOLOUR)
        return 1

def togglehidden(args=None):

    # togglehidden will set the global value for SHOWHIDDEN
    global SHOWHIDDEN

    # toggle SHOWHIDDEN
    SHOWHIDDEN = not SHOWHIDDEN

    # if hidden files are exposed
    if SHOWHIDDEN:

        # print exposed message
        guiprint('> hidden files are now exposed', colour=TEXTCOLOUR)

    # if hidden files are hidden
    else:

        # print hidden message
        guiprint('> files hidden', colour=TEXTCOLOUR)


# file directives
def create(args):

    # if no arguments given
    if not args:
        guiprint('> enter the filename after the create directive', colour=TEXTCOLOUR)

    # if arguments are given
    else:

        # define arguments
        name = ' '.join(args)

        # normalise to absolute path
        target = os.path.abspath(resolvepath(name))

        # check the complete space-aware destination path
        if not allowpaths([target]):
            return

        try:

            # create new file
            with open(target, 'x'):
                pass

            # file created message
            guiprint(f'> {name} created', colour=TEXTCOLOUR)

        # file already exists error
        except FileExistsError:
            guiprint(f'> {name} already exists', colour=ERRORCOLOUR)
            return

        except FileNotFoundError:

            # directory for new file doesn't exist
            guiprint(f'> directory to create in not found', colour=ERRORCOLOUR)
            return

        except PermissionError:

            # permission denied error
            guiprint(f'> permission denied', colour=ERRORCOLOUR)
            return

        # other errors
        except OSError as e:
            guiprint(f'> error creating file {e}', colour=ERRORCOLOUR)
            return


def delete(args):

    # if no arguments given
    if not args:
        guiprint('> enter the filename after the delete directive', colour=ERRORCOLOUR)
        return

    # define requested path (wildcards allowed)
    name = ' '.join(args)

    try:

        # if wildcard is used, delete all matched files
        if any(haswild(a) for a in args):

            targets = expandwild(args)

            # filter out missing
            targets = [t for t in targets if os.path.exists(t)]

            # nothing matched
            if not targets:
                guiprint(f'> {name} does not exist', colour=ERRORCOLOUR)
                return

            # reject tiers
            for t in targets:
                if os.path.isdir(t):
                    guiprint(f'> {os.path.basename(t)} is a tier', colour=ERRORCOLOUR)
                    return

        # otherwise behave as before (single path, space-friendly)
        else:

            targets = [os.path.abspath(resolvepath(name))]

            # ensure target exists
            if not os.path.exists(targets[0]):
                guiprint(f'> {name} does not exist', colour=ERRORCOLOUR)
                return

            # ensure it is a file (not a tier)
            if os.path.isdir(targets[0]):
                guiprint(f'> {name} is a tier', colour=ERRORCOLOUR)
                return

    except Exception as e:

        # error resolving path
        guiprint(f'> error resolving file {e}', colour=ERRORCOLOUR)
        return

    try:

        # block deleting the rubbish bin or anything inside it
        rubbishroot = os.path.abspath('/.rubbish')

        for t in targets:

            if os.path.commonpath([t, rubbishroot]) == rubbishroot:
                guiprint('> cannot delete the rubbish bin or its contents', colour=ERRORCOLOUR)
                return

    except Exception as e:

        # error checking rubbish path
        guiprint(f'> error checking rubbish path {e}', colour=ERRORCOLOUR)
        return

    # check every resolved target before changing anything
    if not allowpaths(targets):
        return

    try:

        storepaths(targets)

        # file deleted message
        if len(targets) == 1:

            guiprint(f'> {os.path.basename(targets[0])} put in the rubbish', colour=TEXTCOLOUR)

        else:

            guiprint(f'> {len(targets)} files put in the rubbish', colour=TEXTCOLOUR)

    except ImportError:

        # rubbish module not found
        guiprint('> rubbish software not found', colour=ERRORCOLOUR)

    except PermissionError:

        # permission denied moving to rubbish
        guiprint('> permission denied to move file to rubbish', colour=ERRORCOLOUR)

    except Exception as e:

        # delete error
        guiprint(f'> error deleting file {e}', colour=ERRORCOLOUR)


def destroy(args):

    # if no arguments given
    if not args:
        guiprint('> enter the filename after the destroy directive', colour=TEXTCOLOUR)
        return

    # define arguments
    name = ' '.join(args)

    try:

        # get current tier
        cwd = os.getcwd()

    except OSError as e:

        # error retrieving current tier
        guiprint(f'> could not get current tier {e}', colour=ERRORCOLOUR)
        return

    # if not in rubbish, hard-delete the file as before (wildcards allowed)
    if not cwd.startswith('/.rubbish'):

        try:

            # wildcard mode: destroy many
            if any(haswild(a) for a in args):

                targets = expandwild(args)

                # filter out missing
                targets = [t for t in targets if os.path.exists(t)]

                if not targets:
                    guiprint(f'> {name} does not exist', colour=ERRORCOLOUR)
                    return

                for t in targets:
                    if os.path.isdir(t):
                        guiprint(f'> {os.path.basename(t)} is a tier', colour=ERRORCOLOUR)
                        return

                # check every resolved target before changing anything
                if not allowpaths(targets):
                    return

                for t in targets:
                    os.remove(t)

                guiprint(f'> {len(targets)} files destroyed', colour=TEXTCOLOUR)

                return

            # normal mode: single path
            target = os.path.abspath(resolvepath(name))

            # check the complete space-aware target path
            if not allowpaths([target]):
                return

            # destroy file
            os.remove(target)

            # print file destroyed message
            guiprint(f'> {name} destroyed', colour=TEXTCOLOUR)

        except FileNotFoundError:

            # file not found error
            guiprint(f'> {name} does not exist', colour=ERRORCOLOUR)

        except IsADirectoryError:

            # target is a tier error
            guiprint(f'> {name} is a tier', colour=ERRORCOLOUR)

        except Exception as e:

            # destroy error
            guiprint(f'> error destroying file {e}', colour=ERRORCOLOUR)

        return

    # we are in /.rubbish or a sub-tier: destroy from rubbish + index
    indexfile = '/.rubbish/index.txt'

    # attempt to infer rid from cwd (/.rubbish/<rid>/content/...)
    rid_from_cwd = None
    try:

        # split path components and capture rid if present
        parts = cwd.strip(os.sep).split(os.sep)
        if len(parts) >= 2 and parts[0] == '.rubbish':
            rid_from_cwd = parts[1]

    except Exception:
        rid_from_cwd = None

    # if we are inside a specific rubbish item, destroy it directly
    if rid_from_cwd:

        try:

            # define payload tier
            payload = os.path.join('/.rubbish', rid_from_cwd)

            if not allowpaths([payload, indexfile]):
                return

            # remove payload recursively
            shutil.rmtree(payload, ignore_errors=True)

            # rewrite index without this rid
            try:

                with open(indexfile) as f:
                    lines = f.read().splitlines()

                header = lines[0] if lines else "id\tname\torigpath\tisdir\tsize\tdeletedts\tuser"
                newlines = [header] + [l for l in lines[1:] if not l.startswith(rid_from_cwd + '\t')]

                with open(indexfile, 'w') as f:
                    f.write('\n'.join(newlines) + '\n')

            except FileNotFoundError:

                # index missing, nothing to update
                pass

            # confirmation
            guiprint('> rubbish item destroyed', colour=TEXTCOLOUR)

        except PermissionError:

            # permission denied destroying rubbish item
            guiprint('> permission denied', colour=ERRORCOLOUR)

        except Exception as e:

            # destruction error
            guiprint(f'> error destroying rubbish item {e}', colour=ERRORCOLOUR)

        return

    # we are at /.rubbish root: resolve by NAME (newest->oldest), prompt if duplicates
    try:

        # read index
        with open(indexfile) as f:
            lines = f.read().splitlines()

    except FileNotFoundError:

        # rubbish empty or index missing
        guiprint('> rubbish is empty', colour=TEXTCOLOUR)
        return

    except PermissionError:

        # permission denied reading index
        guiprint('> permission denied', colour=ERRORCOLOUR)
        return

    except Exception as e:

        # other index read error
        guiprint(f'> error reading rubbish index {e}', colour=ERRORCOLOUR)
        return

    try:

        # collect matches by given name
        matches = []
        for line in lines[1:]:
            if not line:
                continue
            cols = line.split('\t')
            if len(cols) < 7:
                continue
            rid, fname, origpath, isdir, size, deletedts, user = cols
            if fname == name:
                try:
                    ts = int(deletedts)
                except Exception:
                    ts = 0
                matches.append((ts, rid, fname, origpath, isdir))

        # no matches
        if not matches:
            guiprint(f'> no such file or tier {name} in rubbish', colour=ERRORCOLOUR)
            return

        # newest first
        matches.sort(key=lambda x: x[0], reverse=True)

        # if multiple, prompt user to choose which to destroy
        if len(matches) > 1:

            # atreyan timestamps
            try:
                from reign.reign import timestamp
                def tsfmt(v): return timestamp(int(v))
            except Exception:
                def tsfmt(v): return str(v)

            for i, (ts, rid, fname, origpath, isdir) in enumerate(matches, start=1):
                guiprint(f'> {i}\t{fname}\t{origpath}\t{tsfmt(ts)}')

            try:
                choice = int(input('> select number to destroy '))
            except ValueError:
                guiprint('> invalid selection', colour=ERRORCOLOUR)
                return

            if choice < 1 or choice > len(matches):
                guiprint('> invalid selection', colour=ERRORCOLOUR)
                return

            ts, rid, fname, origpath, isdir = matches[choice - 1]

        else:

            # single match
            ts, rid, fname, origpath, isdir = matches[0]

        # destroy the selected rid
        try:

            # remove payload
            payload = os.path.join('/.rubbish', rid)

            if not allowpaths([payload, indexfile]):
                return

            shutil.rmtree(payload, ignore_errors=True)

            # rewrite index without this rid
            header = lines[0] if lines else "id\tname\torigpath\tisdir\tsize\tdeletedts\tuser"
            newlines = [header] + [l for l in lines[1:] if not l.startswith(rid + '\t')]

            with open(indexfile, 'w') as f:
                f.write('\n'.join(newlines) + '\n')

            # confirmation
            guiprint(f'> {fname} destroyed', colour=TEXTCOLOUR)

        except PermissionError:

            # permission denied destroying selected item
            guiprint('> permission denied', colour=ERRORCOLOUR)

        except Exception as e:

            # error destroying selected item
            guiprint(f'> error destroying {fname} {e}', colour=ERRORCOLOUR)

    except Exception as e:

        # unexpected error during rubbish destroy flow
        guiprint(f'> error destroying in rubbish {e}', colour=ERRORCOLOUR)


def rename(args):

    connected = catalogueconnector('rename', args, 'to')

    if connected:
        args = [connected[0], connected[1]]

    # if no arguments given
    if len(args) < 2:
        guiprint('> enter the old filename and new filename after the rename directive', colour=TEXTCOLOUR)

    # if arguments are given
    else:

        # define arguments
        tokens = args

        done = False

        for i in range(1, len(tokens)):

            old = ' '.join(tokens[:i])

            new = ' '.join(tokens[i:])

            # normalise paths
            try:

                oldabs = os.path.abspath(resolvepath(old))

                newabs = os.path.abspath(resolvepath(new))

            except Exception:

                oldabs = INVALIDPATH
                newabs = INVALIDPATH

            # if old file exists
            if os.path.exists(oldabs) and os.path.isfile(oldabs):

                if os.path.exists(newabs):

                    guiprint(f'> destination {new} already exists', colour=ERRORCOLOUR)
                    done = True
                    break

                # check the resolved source and destination paths
                if not allowpaths([oldabs, newabs]):

                    done = True

                    break

                try:

                    # rename
                    os.rename(oldabs, newabs)

                    guiprint(f'> {old} renamed to {new}', colour=TEXTCOLOUR)

                    done = True

                    break

                except FileNotFoundError:

                    # old file disappeared
                    guiprint(f'> {old} not found', colour=ERRORCOLOUR)

                    done = True

                    break

                except PermissionError:

                    # permission denied renaming
                    guiprint(f'> permission denied', colour=ERRORCOLOUR)

                    done = True

                    break

                except OSError as e:

                    # other errors
                    guiprint(f'> error renaming file {e}', colour=ERRORCOLOUR)

                    done = True

                    break

        # if file cannot be found
        if not done:
            guiprint('> could not find an existing file to rename', colour=ERRORCOLOUR)


def move(args):

    connected = catalogueconnector('move', args, 'to')

    if connected:
        args = [connected[0], connected[1]]

    # if no arguments given
    if len(args) < 2:
        guiprint('> enter the source filename and destination after the move directive', colour=TEXTCOLOUR)

    # if arguments are given
    else:

        # define arguments
        tokens = args

        done = False

        # wildcard multi-source mode: move <pattern...> <destination>
        if any(haswild(t) for t in tokens[:-1]):

            sources, dstabs = wildcardarguments(tokens, want='file')

            if not sources:
                guiprint('> could not move file ensure source exists and destination is valid', colour=ERRORCOLOUR)
                return

            if len(sources) > 1 and not os.path.isdir(dstabs):

                guiprint('> destination must be an existing tier when moving multiple items', colour=ERRORCOLOUR)

                return

            return transactionmove(sources, dstabs)

        for i in range(1, len(tokens)):

            src = ' '.join(tokens[:i])

            dst = ' '.join(tokens[i:])

            try:
                srcabs = os.path.abspath(resolvepath(src))
                dstabs = os.path.abspath(resolvepath(dst))
            except Exception:
                srcabs = INVALIDPATH
                dstabs = INVALIDPATH

            # if source exists
            if os.path.exists(srcabs):

                # resolve the actual destination before changing either path
                target = dstabs

                if os.path.isdir(dstabs):

                    target = os.path.join(dstabs, os.path.basename(srcabs))

                if os.path.exists(target):

                    guiprint(f'> destination {target} already exists', colour=ERRORCOLOUR)
                    done = True
                    break

                if not allowpaths([srcabs, target]):

                    done = True

                    break

                try:

                    # if destination exists
                    if os.path.isdir(dstabs):

                        # move file
                        shutil.move(srcabs, dstabs)

                        # file moved message
                        guiprint(f'> {os.path.basename(srcabs)} moved to {dst}', colour=TEXTCOLOUR)

                    else:

                        shutil.move(srcabs, dstabs)

                        guiprint(f'> {os.path.basename(srcabs)} moved to {dst}', colour=TEXTCOLOUR)

                except FileNotFoundError:

                    # source file not found
                    guiprint(f'> {os.path.basename(srcabs)} not found', colour=ERRORCOLOUR)

                except PermissionError:

                    # permission denied moving file
                    guiprint(f'> permission denied', colour=ERRORCOLOUR)

                except OSError as e:

                    # other OS-related move error
                    guiprint(f'> error moving {e}', colour=ERRORCOLOUR)

                done = True

                break

        # if file cannot be found
        if not done:
            guiprint('> could not move file ensure source exists and destination is valid', colour=ERRORCOLOUR)


def copy(args):

    connected = catalogueconnector('copy', args, 'to')

    if connected:
        args = [connected[0], connected[1]]

    # resolve a complete existing path as one space-aware source
    singlesource = ' '.join(args) if args else ''

    try:

        singleexists = bool(singlesource) and os.path.isfile(os.path.abspath(resolvepath(singlesource)))

    except Exception:

        singleexists = False

    # if one argument or one complete existing path is given, duplicate in place
    if len(args) == 1 or singleexists:

        src = singlesource

        try:

            srcabs = os.path.abspath(resolvepath(src))

        except Exception:

            srcabs = INVALIDPATH

        if not os.path.isfile(srcabs):

            guiprint(f'> {os.path.basename(srcabs)} not found', colour=ERRORCOLOUR)

            return

        # split filename
        base, ext = os.path.splitext(os.path.basename(srcabs))

        directory = os.path.dirname(srcabs)

        # initial target name
        newname = f"{base} - copy{ext}"

        target = os.path.join(directory, newname)

        count = 2

        while os.path.exists(target):

            newname = f"{base} - copy {count}{ext}"

            target = os.path.join(directory, newname)

            count += 1

        # check the resolved destination path
        if not allowpaths([target]):
            return

        try:

            shutil.copy2(srcabs, target)

            guiprint(f'> {os.path.basename(srcabs)} copied to {newname}', colour=TEXTCOLOUR)

        except PermissionError:

            guiprint('> permission denied', colour=ERRORCOLOUR)

        except Exception as e:

            guiprint(f'> error copying file {e}', colour=ERRORCOLOUR)

        return

    # if arguments are given
    else:

        # define arguments
        tokens = args

        done = False

        # wildcard multi-source mode: copy <pattern...> <destination>
        if any(haswild(t) for t in tokens[:-1]):

            sources, dstabs = wildcardarguments(tokens, want='file')

            if not sources:

                guiprint('> could not copy file ensure source exists and destination is valid', colour=ERRORCOLOUR)

                return

            if len(sources) > 1 and not os.path.isdir(dstabs):

                guiprint('> destination must be an existing tier when copying multiple items', colour=ERRORCOLOUR)

                return

            return transactioncopy(sources, dstabs)

        for i in range(1, len(tokens)):

            src = ' '.join(tokens[:i])

            dst = ' '.join(tokens[i:])

            # normalise paths
            try:

                srcabs = os.path.abspath(resolvepath(src))

                dstabs = os.path.abspath(resolvepath(dst))

            except Exception:

                srcabs = INVALIDPATH
                dstabs = INVALIDPATH

            # if source exists
            if os.path.exists(srcabs) and os.path.isfile(srcabs):

                # resolve and check the actual destination path
                target = dstabs

                if os.path.isdir(dstabs):

                    target = os.path.join(dstabs, os.path.basename(srcabs))

                if os.path.exists(target):

                    guiprint(f'> destination {target} already exists', colour=ERRORCOLOUR)
                    done = True
                    break

                if not allowpaths([target]):

                    done = True

                    break

                try:

                    # if destination exists
                    if os.path.isdir(dstabs):

                        # define target
                        target = os.path.join(dstabs, os.path.basename(srcabs))

                        # copy file
                        shutil.copy2(srcabs, target)

                        # file copied message
                        guiprint(f'> {os.path.basename(srcabs)} copied to {dst}', colour=TEXTCOLOUR)

                        done = True

                        break

                    else:
                        shutil.copy2(srcabs, dstabs)
                        guiprint(f'> {os.path.basename(srcabs)} copied to {dst}', colour=TEXTCOLOUR)

                        done = True

                        break

                except FileNotFoundError:

                    # source file not found error
                    guiprint(f'> {src} not found', colour=ERRORCOLOUR)
                    return

                except PermissionError as e:

                    # permission denied error
                    guiprint(f'> permission denied', colour=ERRORCOLOUR)
                    return

                # other errors
                except OSError as e:
                    guiprint(f'> error copying file {e}', colour=ERRORCOLOUR)
                    return

        # if file cannot be found
        if not done:
            guiprint('> could not copy file ensure source exists and destination is valid', colour=ERRORCOLOUR)


# tier directives
def tier(args=None):

    # try to read drive number and current working tier
    try:
        cwd = os.getcwd()

    # if current tier fails
    except OSError as e:
        guiprint(f"> could not get current tier {e}", colour=ERRORCOLOUR)
        return

    # print drive number and current working tier
    guiprint(formatlocation(cwd), colour=TEXTCOLOUR)


def changetier(args=None):

    global PREVTIER, DRIVENUMBER

    # if no arguments given
    if not args:

        # print enter tier message
        guiprint('> enter the tier name after the change tier directive', colour=TEXTCOLOUR)
        return

    # if arguments are given
    else:

        # define the target tier
        target = ' '.join(args)

        try:

            current = os.getcwd()

        except Exception:

            current = None

        returning = target.lower() == 'back' and not os.path.isdir(target)

        # return to the previous tier unless a real tier named back exists here
        if returning:

            if not PREVTIER:

                guiprint('> no previous tier', colour=ERRORCOLOUR)
                return

            target = PREVTIER

        elif re.match(r'^[0-9]+(?:/|$)', target.replace('\\', '/')):

            number, resolved = parselocation(target)

            if resolved is None:

                if number not in DRIVES:
                    guiprint(f'> drive {number} is not available', colour=ERRORCOLOUR)
                else:
                    guiprint('> location cannot leave the drive root', colour=ERRORCOLOUR)

                return

            target = resolved

        else:
            target = resolvepath(target)

        try:

            # change to target tier
            target = followarraylink(target)
            os.chdir(target)

        # change tier error
        except FileNotFoundError:

            # tier not found
            guiprint(f'> {target} not found', colour=ERRORCOLOUR)

            return

        except PermissionError:

            # permission denied
            guiprint(f'> permission denied', colour=ERRORCOLOUR)

            return

        except OSError as e:

            # other os error
            guiprint(f'> error changing tier {e}', colour=ERRORCOLOUR)

            return

        try:

            if current:
                PREVTIER = current

            # get current working tier
            cwd = os.getcwd()
            DRIVENUMBER = int(driveforpath(cwd).get('number', 1))

        except OSError as e:

            # error retrieving current tier
            guiprint(f'> could not retrieve current tier {e}', colour=ERRORCOLOUR)

            return


def opentier(args=None):

    # define target path or default to current tier
    path = ' '.join(args) if args else '.'

    try:

        # resolve absolute path
        apath = followarraylink(os.path.abspath(resolvepath(path)))

        # handle rubbish root listing with T1OS sorting rules
        if apath == '/.rubbish':

            try:

                # read rubbish index
                with open('/.rubbish/index.txt') as f:

                    lines = f.read().splitlines()

            except FileNotFoundError:

                # rubbish missing or empty
                guiprint('> rubbish is empty', colour=ERRORCOLOUR)

                return

            except PermissionError:

                # permission denied
                guiprint('> permission denied', colour=ERRORCOLOUR)

                return

            except Exception as e:

                # other index open error
                guiprint(f'> error opening rubbish {e}', colour=ERRORCOLOUR)

                return

            try:

                # skip header
                rows = lines[1:] if len(lines) > 1 else []

                # if no rows found
                if not rows:

                    guiprint('> rubbish is empty', colour=TEXTCOLOUR)

                    return

                records = []

                for line in rows:

                    if not line:
                        continue

                    parts = line.split('\t')

                    if len(parts) < 7:
                        continue

                    rid, name, origpath, isdir, size, deletedts, user = parts

                    try:

                        ts = int(deletedts)

                    except Exception:

                        ts = 0

                    kind = 'tier' if isdir == '1' else 'file'
                    deleted = displaytimestamp(ts) if ts else '-'
                    originaltier = os.path.dirname(origpath) or '/'
                    records.append([rid, kind, name, originaltier, size, deleted, user, ts])

                records.sort(key=lambda row: (0 if row[1] == 'tier' else 1, row[2].casefold(), -row[7]))
                guiprint()
                showtable(
                    ['id', 'type', 'name', 'original tier', 'size', 'deleted', 'user'],
                    [row[:7] for row in records],
                )
                guiprint()

                return

            except Exception as e:

                # listing/formatting error
                guiprint(f'> error listing rubbish {e}', colour=ERRORCOLOUR)
                return

        # if user targets /.rubbish/<name>[/*], resolve to latest matching deleted tier content
        if apath.startswith('/.rubbish' + os.sep):

            try:

                # split components
                parts = apath.strip(os.sep).split(os.sep)

                # require /.rubbish/<name> at minimum
                if len(parts) >= 2 and parts[0] == '.rubbish':

                    # requested logical name
                    reqname = parts[1]

                    # read index
                    with open('/.rubbish/index.txt') as f:
                        rows = f.read().splitlines()[1:]

                    # find latest tier with this name
                    best_ts = -1

                    best_rid = None

                    for line in rows:

                        if not line:
                            continue

                        cols = line.split('\t')

                        if len(cols) < 7:
                            continue

                        rid, name, origpath, isdir, size, deletedts, user = cols

                        if name == reqname and isdir == '1':

                            try:

                                ts = int(deletedts)

                            except Exception:

                                ts = 0

                            if ts > best_ts:

                                best_ts = ts

                                best_rid = rid

                    # if found, redirect to stored tier content (preserve deeper tail if given)
                    if best_rid is not None:

                        base = os.path.join('/.rubbish', best_rid, 'content')

                        if len(parts) > 2:

                            tail = os.path.join(*parts[2:])

                            apath = os.path.join(base, tail)

                        else:

                            apath = base

            except FileNotFoundError:

                # rubbish empty/missing index
                guiprint('> rubbish is empty', colour=ERRORCOLOUR)

                return

            except PermissionError:

                # permission denied
                guiprint('> permission denied', colour=ERRORCOLOUR)

                return

            except Exception as e:

                # resolution error
                guiprint(f'> error resolving rubbish {e}', colour=ERRORCOLOUR)

                return

        # normal open behaviour with T1OS sorting: tiers A-Z then files A-Z
        entries = os.listdir(apath)

        dirs, files = [], []

        for entry in entries:

            # check reveal and skip hidden if relevant
            if not SHOWHIDDEN and entry.startswith('.'):
                continue

            # define full path
            full = os.path.join(apath, entry)

            # sort tiers above
            if os.path.isdir(full):
                dirs.append(entry)

            # then sort files below
            else:
                files.append(entry)

        # print tiers
        for entry in sorted(dirs, key=str.casefold):

            guiprint(entry, colour=TEXTCOLOUR)

        # print files
        for entry in sorted(files, key=str.casefold):

            guiprint(entry, colour=TEXTCOLOUR)

    except FileNotFoundError as e:

        # tier not found
        guiprint(f'> {path} not found', colour=ERRORCOLOUR)

        return

    except PermissionError as e:

        # permission denied
        guiprint(f'> permission denied', colour=ERRORCOLOUR)

        return

    except OSError as e:

        # open tier error
        guiprint(f'> error opening tier {e}', colour=ERRORCOLOUR)

        return


def exposetier(args=None):

    # define target path or default to current tier
    path = ' '.join(args) if args else '.'

    try:

        # resolve absolute path
        apath = followarraylink(os.path.abspath(resolvepath(path)))

        # if exposing the rubbish root, list all items with T1OS sorting
        if apath == '/.rubbish':

            # define index file
            indexfile = os.path.join(apath, 'index.txt')

            try:

                # read index
                with open(indexfile) as f:

                    lines = f.read().splitlines()

            except FileNotFoundError:

                # rubbish index missing or empty bin
                guiprint('> rubbish is empty', colour=ERRORCOLOUR)

                return

            except PermissionError:

                # permission denied reading index
                guiprint('> permission denied', colour=ERRORCOLOUR)

                return

            except Exception as e:

                # other errors opening index
                guiprint(f'> error exposing rubbish {e}', colour=ERRORCOLOUR)

                return

            try:

                # skip header and parse rows
                rows = lines[1:] if len(lines) > 1 else []

                # if nothing to show
                if not rows:

                    guiprint('> rubbish is empty', colour=TEXTCOLOUR)

                    return

                # collect groups by name with timestamps, split into dirs and files
                dirgroups = {}

                filegroups = {}

                for line in rows:

                    if not line:
                        continue

                    parts = line.split('\t')

                    if len(parts) < 7:
                        continue

                    rid, name, origpath, isdir, size, deletedts, user = parts

                    try:

                        ts = int(deletedts)

                    except Exception:

                        ts = 0

                    if isdir == '1':

                        dirgroups.setdefault(name, []).append(ts)

                    else:

                        filegroups.setdefault(name, []).append(ts)

                # print tiers A-Z; within each name print duplicates most-recent first
                for name in sorted(dirgroups.keys(), key=str.casefold):

                    for _ in sorted(dirgroups[name], reverse=True):

                        guiprint(name, colour=TEXTCOLOUR)

                # print files A-Z; within each name print duplicates most-recent first
                for name in sorted(filegroups.keys(), key=str.casefold):

                    for _ in sorted(filegroups[name], reverse=True):

                        guiprint(name, colour=TEXTCOLOUR)

                return

            except Exception as e:

                # listing error
                guiprint(f'> error exposing rubbish {e}', colour=ERRORCOLOUR)

                return

        # if user targets /.rubbish/<name>[/*], resolve to latest matching deleted tier content
        if apath.startswith('/.rubbish' + os.sep):

            # split components
            parts = apath.strip(os.sep).split(os.sep)

            # pattern: /.rubbish/<name>[/...]
            if len(parts) >= 2 and parts[0] == '.rubbish':

                # requested logical name under rubbish
                reqname = parts[1]

                # path to index
                indexfile = '/.rubbish/index.txt'

                try:

                    # read index
                    with open(indexfile) as f:
                        rows = f.read().splitlines()

                except FileNotFoundError:

                    # rubbish empty
                    guiprint('> rubbish is empty', colour=ERRORCOLOUR)

                    return

                except PermissionError:

                    # permission denied reading index
                    guiprint('> permission denied', colour=ERRORCOLOUR)

                    return

                except Exception as e:

                    # error opening index
                    guiprint(f'> error exposing rubbish {e}', colour=ERRORCOLOUR)

                    return

                try:

                    # find latest tier with this name
                    best_ts = -1

                    best_rid = None

                    for line in rows[1:]:

                        if not line:
                            continue

                        cols = line.split('\t')

                        if len(cols) < 7:
                            continue

                        rid, name, origpath, isdir, size, deletedts, user = cols

                        if name == reqname and isdir == '1':

                            try:

                                ts = int(deletedts)

                            except Exception:

                                ts = 0

                            if ts > best_ts:

                                best_ts = ts

                                best_rid = rid

                    # if found, redirect apath to its payload content (keep any deeper path if provided)
                    if best_rid is not None:

                        base = os.path.join('/.rubbish', best_rid, 'content')

                        if len(parts) > 2:

                            tail = os.path.join(*parts[2:])

                            apath = os.path.join(base, tail)

                        else:

                            apath = base

                    # if not found, fall through to normal exposure

                except Exception as e:

                    # resolution error
                    guiprint(f'> error exposing rubbish {e}', colour=ERRORCOLOUR)

                    return

        # define files and tiers in working tier (exposed: include hidden)
        entries = os.listdir(apath)

        dirs, files = [], []

        for entry in entries:

            # define tiers to be sorted
            full = os.path.join(apath, entry)

            # sort tiers above
            if os.path.isdir(full):
                dirs.append(entry)

            # then sort files below
            else:
                files.append(entry)

        # print tiers
        for entry in sorted(dirs, key=str.casefold):

            guiprint(entry, colour=TEXTCOLOUR)

        # print files
        for entry in sorted(files, key=str.casefold):

            guiprint(entry, colour=TEXTCOLOUR)

    # expose tier error
    except FileNotFoundError:

        # tier not found
        guiprint(f'> {path} not found', colour=ERRORCOLOUR)

        return

    except PermissionError:

        # permission denied
        guiprint(f'> permission denied', colour=ERRORCOLOUR)

        return

    except OSError as e:

        # expose tier error
        guiprint(f'> error exposing tier {e}', colour=ERRORCOLOUR)

        return


def treetier(apath, includehidden, indent="", maximum=None, depth=0, state=None):

    if state is None:
        state = {'count': 0, 'limited': False}

    if maximum is not None and depth >= maximum:
        return state

    try:

        entries = os.listdir(apath)

    except PermissionError:

        guiprint(f'{indent}> permission denied', colour=ERRORCOLOUR)

        return

    except OSError as e:

        guiprint(f'{indent}> error opening tier {e}', colour=ERRORCOLOUR)

        return

    dirs, files = [], []

    for entry in entries:

        if not includehidden and entry.startswith('.'):
            continue

        full = os.path.join(apath, entry)

        if os.path.isdir(full):
            dirs.append(entry)

        else:
            files.append(entry)

    for entry in sorted(dirs, key=str.casefold):

        if state['count'] >= RECURSIVERESULTLIMIT:
            state['limited'] = True
            return state

        guiprint(f'{indent}{entry}', colour=TEXTCOLOUR)

        state['count'] += 1

        child = os.path.join(apath, entry)

        treetier(child, includehidden, indent + '  ', maximum, depth + 1, state)

        if state.get('limited'):
            return state

    for entry in sorted(files, key=str.casefold):

        if state['count'] >= RECURSIVERESULTLIMIT:
            state['limited'] = True
            return state

        guiprint(f'{indent}{entry}', colour=TEXTCOLOUR)

        state['count'] += 1

    return state


def opentiers(args=None):

    path, maximum = recursivearguments(args, 'open tiers')

    try:

        apath = followarraylink(os.path.abspath(resolvepath(path)))

        if apath == '/.rubbish':

            opentier([path])

            return

        if apath.startswith('/.rubbish' + os.sep):

            parts = apath.strip(os.sep).split(os.sep)

            if len(parts) >= 2 and parts[0] == '.rubbish':

                reqname = parts[1]

                try:

                    with open('/.rubbish/index.txt') as f:

                        rows = f.read().splitlines()[1:]

                    best_ts = -1

                    best_rid = None

                    for line in rows:

                        if not line:
                            continue

                        cols = line.split('\t')

                        if len(cols) < 7:
                            continue

                        rid, name, origpath, isdir, size, deletedts, user = cols

                        if name == reqname and isdir == '1':

                            try:

                                ts = int(deletedts)

                            except Exception:

                                ts = 0

                            if ts > best_ts:

                                best_ts = ts

                                best_rid = rid

                    if best_rid is not None:

                        base = os.path.join('/.rubbish', best_rid, 'content')

                        if len(parts) > 2:

                            tail = os.path.join(*parts[2:])

                            apath = os.path.join(base, tail)

                        else:

                            apath = base

                except FileNotFoundError:

                    guiprint('> rubbish is empty', colour=ERRORCOLOUR)

                    return

                except PermissionError:

                    guiprint('> permission denied', colour=ERRORCOLOUR)

                    return

                except Exception as e:

                    guiprint(f'> error resolving rubbish {e}', colour=ERRORCOLOUR)

                    return

        includehidden = bool(SHOWHIDDEN)

        state = treetier(apath, includehidden, maximum=maximum)

        if state and state.get('limited'):
            guiprint(f'> stopped after {RECURSIVERESULTLIMIT} items', colour=TEXTCOLOUR)

    except FileNotFoundError:

        guiprint(f'> {path} not found', colour=ERRORCOLOUR)

        return

    except PermissionError:

        guiprint(f'> permission denied', colour=ERRORCOLOUR)

        return

    except OSError as e:

        guiprint(f'> error opening tier {e}', colour=ERRORCOLOUR)

        return


def exposetiers(args=None):

    path, maximum = recursivearguments(args, 'expose tiers')

    try:

        apath = followarraylink(os.path.abspath(resolvepath(path)))

        if apath == '/.rubbish':

            exposetier([path])

            return

        if apath.startswith('/.rubbish' + os.sep):

            parts = apath.strip(os.sep).split(os.sep)

            if len(parts) >= 2 and parts[0] == '.rubbish':

                reqname = parts[1]

                try:

                    with open('/.rubbish/index.txt') as f:

                        rows = f.read().splitlines()[1:]

                    best_ts = -1

                    best_rid = None

                    for line in rows:

                        if not line:
                            continue

                        cols = line.split('\t')

                        if len(cols) < 7:
                            continue

                        rid, name, origpath, isdir, size, deletedts, user = cols

                        if name == reqname and isdir == '1':

                            try:

                                ts = int(deletedts)

                            except Exception:

                                ts = 0

                            if ts > best_ts:

                                best_ts = ts

                                best_rid = rid

                    if best_rid is not None:

                        base = os.path.join('/.rubbish', best_rid, 'content')

                        if len(parts) > 2:

                            tail = os.path.join(*parts[2:])

                            apath = os.path.join(base, tail)

                        else:

                            apath = base

                except FileNotFoundError:

                    guiprint('> rubbish is empty', colour=ERRORCOLOUR)

                    return

                except PermissionError:

                    guiprint('> permission denied', colour=ERRORCOLOUR)

                    return

                except Exception as e:

                    guiprint(f'> error resolving rubbish {e}', colour=ERRORCOLOUR)

                    return

        state = treetier(apath, includehidden=True, maximum=maximum)

        if state and state.get('limited'):
            guiprint(f'> stopped after {RECURSIVERESULTLIMIT} items', colour=TEXTCOLOUR)

    except FileNotFoundError:

        guiprint(f'> {path} not found', colour=ERRORCOLOUR)

        return

    except PermissionError:

        guiprint(f'> permission denied', colour=ERRORCOLOUR)

        return

    except OSError as e:

        guiprint(f'> error exposing tier {e}', colour=ERRORCOLOUR)

        return


def createtier(args):

    # if no arguments given
    if not args:

        guiprint('> enter the tier name after the create tier directive', colour=TEXTCOLOUR)

        return

    # if arguments are given
    else:

        # define name of new tier
        name = ' '.join(args)

        # normalise to absolute path
        target = os.path.abspath(resolvepath(name))

        # check the complete space-aware destination path
        if not allowpaths([target]):
            return

        try:

            # create new tier
            os.mkdir(target)

            # tier created message
            guiprint(f'> {name} created', colour=TEXTCOLOUR)

        # create tier error
        except FileExistsError:

            # tier already exists
            guiprint(f'> {name} already exists', colour=ERRORCOLOUR)

            return

        except PermissionError:

            # permission denied
            guiprint(f'> permission denied', colour=ERRORCOLOUR)

            return

        except OSError as e:

            # create tier error
            guiprint(f'> error creating tier {e}', colour=ERRORCOLOUR)

            return


def deletetier(args):

    # if no arguments given
    if not args:

        guiprint('> enter the tier name after the delete tier directive', colour=TEXTCOLOUR)

        return

    # define requested tier name (wildcards allowed)
    name = ' '.join(args)

    try:

        # wildcard mode
        if any(haswild(a) for a in args):

            targets = expandwild(args)

            # filter out missing
            targets = [t for t in targets if os.path.exists(t)]

            if not targets:

                guiprint(f'> {name} does not exist', colour=ERRORCOLOUR)

                return

            for t in targets:

                if not os.path.isdir(t):

                    guiprint(f'> {os.path.basename(t)} is not a tier', colour=ERRORCOLOUR)

                    return

        # normal mode
        else:

            targets = [os.path.abspath(resolvepath(name))]

            if not os.path.exists(targets[0]):

                guiprint(f'> {name} does not exist', colour=ERRORCOLOUR)

                return

            if not os.path.isdir(targets[0]):

                guiprint(f'> {name} is not a tier', colour=ERRORCOLOUR)

                return

    except Exception as e:

        # path resolution error
        guiprint(f'> error resolving tier {e}', colour=ERRORCOLOUR)

        return

    try:

        # block deleting the rubbish bin or contents
        rubbishroot = os.path.abspath('/.rubbish')

        for t in targets:

            if os.path.commonpath([t, rubbishroot]) == rubbishroot:

                guiprint('> cannot delete the rubbish bin or its contents', colour=TEXTCOLOUR)

                return

    except Exception as e:

        # error checking rubbish path
        guiprint(f'> error checking rubbish path {e}', colour=ERRORCOLOUR)

        return

    # check every resolved target before changing anything
    if not allowpaths(targets):
        return

    try:

        storepaths(targets)

        # tier deleted message
        if len(targets) == 1:

            guiprint(f'> {os.path.basename(targets[0])} put in the rubbish', colour=TEXTCOLOUR)

        else:

            guiprint(f'> {len(targets)} tiers put in the rubbish', colour=TEXTCOLOUR)

    except ImportError:

        # rubbish module not found
        guiprint('> rubbish software not found', colour=ERRORCOLOUR)

    except PermissionError:

        # permission denied moving to rubbish
        guiprint('> permission denied to put tier in the rubbish', colour=ERRORCOLOUR)

    except Exception as e:

        # delete tier error
        guiprint(f'> error deleting tier {e}', colour=ERRORCOLOUR)


def destroytier(args):

    # if no arguments given
    if not args:

        guiprint('> enter the tier name after the destroy tier directive', colour=TEXTCOLOUR)

        return

    # define tier name
    name = ' '.join(args)

    try:

        # get current tier
        cwd = os.getcwd()

    except OSError as e:

        # error retrieving current tier
        guiprint(f'> could not get current tier {e}', colour=ERRORCOLOUR)

        return

    # if not in rubbish, hard-destroy the tier as before
    if not cwd.startswith('/.rubbish'):

        try:

            # wildcard mode
            if any(haswild(a) for a in args):

                targets = expandwild(args)

                # filter out missing
                targets = [t for t in targets if os.path.exists(t)]

                if not targets:

                    guiprint(f'> {name} does not exist', colour=ERRORCOLOUR)

                    return

                for t in targets:

                    if not os.path.isdir(t):

                        guiprint(f'> {os.path.basename(t)} is not a tier', colour=ERRORCOLOUR)

                        return

                # check every resolved target before changing anything
                if not allowpaths(targets):
                    return

                for t in targets:

                    shutil.rmtree(t)

                guiprint(f'> {len(targets)} tiers destroyed', colour=TEXTCOLOUR)

                return

            # normal mode
            target = os.path.abspath(resolvepath(name))

            # check the complete space-aware target path
            if not allowpaths([target]):
                return

            shutil.rmtree(target)

            guiprint(f'> {name} destroyed', colour=TEXTCOLOUR)


        except FileNotFoundError:

            # tier not found error
            guiprint(f'> {name} does not exist', colour=ERRORCOLOUR)

        except NotADirectoryError:

            # not a tier error
            guiprint(f'> {name} is not a directory', colour=ERRORCOLOUR)

        except Exception as e:

            # destroy tier error
            guiprint(f'> error destroying tier {e}', colour=ERRORCOLOUR)

        return

    # we are in /.rubbish or a sub-tier: destroy from rubbish + index
    indexfile = '/.rubbish/index.txt'

    # attempt to infer rid from cwd (/.rubbish/<rid>/content/...)
    rid_from_cwd = None

    try:

        # split path components and capture rid if present
        parts = cwd.strip(os.sep).split(os.sep)

        if len(parts) >= 2 and parts[0] == '.rubbish':
            rid_from_cwd = parts[1]

    except Exception:
        rid_from_cwd = None

    # if inside a specific rubbish item, destroy it directly
    if rid_from_cwd:

        try:

            # define payload tier
            payload = os.path.join('/.rubbish', rid_from_cwd)

            if not allowpaths([payload, indexfile]):
                return

            # remove payload recursively
            shutil.rmtree(payload, ignore_errors=True)

            # rewrite index without this rid
            try:

                with open(indexfile) as f:
                    lines = f.read().splitlines()

                header = lines[0] if lines else "id\tname\torigpath\tisdir\tsize\tdeletedts\tuser"

                newlines = [header] + [l for l in lines[1:] if not l.startswith(rid_from_cwd + '\t')]

                with open(indexfile, 'w') as f:
                    f.write('\n'.join(newlines) + '\n')

            except FileNotFoundError:

                # index missing, nothing to update
                pass

            # confirmation
            guiprint('> rubbish item destroyed', colour=ERRORCOLOUR)

        except PermissionError:

            # permission denied destroying rubbish item
            guiprint('> permission denied', colour=ERRORCOLOUR)

        except Exception as e:

            # destroy error
            guiprint(f'> error destroying rubbish item {e}', colour=ERRORCOLOUR)

        return

    # at /.rubbish root: resolve by NAME (newest->oldest), prompt if duplicates
    try:

        # read index
        with open(indexfile) as f:
            lines = f.read().splitlines()

    except FileNotFoundError:

        # rubbish empty or index missing
        guiprint('> rubbish is empty', colour=ERRORCOLOUR)

        return

    except PermissionError:

        # permission denied reading index
        guiprint('> permission denied', colour=ERRORCOLOUR)

        return

    except Exception as e:

        # other index read error
        guiprint(f'> error reading rubbish index {e}', colour=ERRORCOLOUR)

        return

    try:

        # collect tier matches by given name
        matches = []

        for line in lines[1:]:

            if not line:
                continue

            cols = line.split('\t')

            if len(cols) < 7:
                continue

            rid, fname, origpath, isdir, size, deletedts, user = cols

            if fname == name and isdir == '1':

                try:

                    ts = int(deletedts)

                except Exception:

                    ts = 0

                matches.append((ts, rid, fname, origpath))

        # no matches
        if not matches:

            guiprint(f'> no such tier {name} in rubbish', colour=ERRORCOLOUR)

            return

        # newest first
        matches.sort(key=lambda x: x[0], reverse=True)

        # if multiple, prompt user to choose which to destroy
        if len(matches) > 1:

            # atreyan timestamps
            try:

                def tsfmt(v): return timestamp(int(v))

            except Exception:

                def tsfmt(v): return str(v)

            for i, (ts, rid, fname, origpath) in enumerate(matches, start=1):

                guiprint(f'> {i}\t{fname}\t{origpath}\t{tsfmt(ts)}', colour=TEXTCOLOUR)

            try:

                choice = int(input('> select number to destroy '))

            except ValueError:

                guiprint('> invalid selection', colour=ERRORCOLOUR)

                return

            if choice < 1 or choice > len(matches):

                guiprint('> invalid selection', colour=ERRORCOLOUR)

                return

            ts, rid, fname, origpath = matches[choice - 1]

        else:

            # single match
            ts, rid, fname, origpath = matches[0]

        # destroy the selected rid
        try:

            # remove payload
            payload = os.path.join('/.rubbish', rid)

            if not allowpaths([payload, indexfile]):
                return

            shutil.rmtree(payload, ignore_errors=True)

            # rewrite index without this rid
            header = lines[0] if lines else "id\tname\torigpath\tisdir\tsize\tdeletedts\tuser"

            newlines = [header] + [l for l in lines[1:] if not l.startswith(rid + '\t')]

            with open(indexfile, 'w') as f:
                f.write('\n'.join(newlines) + '\n')

            # confirmation
            guiprint(f'> {fname} destroyed', colour=TEXTCOLOUR)

        except PermissionError:

            # permission denied destroying selected tier
            guiprint('> permission denied', colour=ERRORCOLOUR)

        except Exception as e:

            # error destroying selected tier
            guiprint(f'> error destroying {fname} {e}', colour=ERRORCOLOUR)

    except Exception as e:

        # unexpected error during rubbish destroy flow
        guiprint(f'> error destroying tier in rubbish {e}', colour=ERRORCOLOUR)


def renametier(args):

    connected = catalogueconnector('rename tier', args, 'to')

    if connected:
        args = [connected[0], connected[1]]

    # if less than two arguments are given
    if len(args) < 2:
        guiprint('> enter the old tier name and new tier name after the rename tier directive', colour=TEXTCOLOUR)

    # if multiple arguments are given
    else:

        # seperate arguments into old tier name and new tier name
        tokens = args

        done = False

        for i in range(1, len(tokens)):

            old = ' '.join(tokens[:i])

            new = ' '.join(tokens[i:])

            # normalise paths
            try:

                oldabs = os.path.abspath(resolvepath(old))

                newabs = os.path.abspath(resolvepath(new))

            except Exception:

                oldabs = INVALIDPATH
                newabs = INVALIDPATH

            if os.path.exists(oldabs) and os.path.isdir(oldabs):

                if os.path.exists(newabs):

                    guiprint(f'> destination {new} already exists', colour=ERRORCOLOUR)
                    done = True
                    break

                # check the resolved source and destination paths
                if not allowpaths([oldabs, newabs]):

                    done = True

                    break

                try:

                    # rename tier
                    os.rename(oldabs, newabs)

                    # tier remamed message
                    guiprint(f'> {old} renamed to {new}', colour=TEXTCOLOUR)

                    done = True

                    break

                # rename tier error
                except PermissionError:

                    # permission denied when renaming
                    guiprint(f'> permission denied', colour=ERRORCOLOUR)

                    done = True

                    break

                except OSError as e:

                    # other os error
                    guiprint(f'> error renaming tier {e}', colour=ERRORCOLOUR)

                    done = True

                    break

        # if old tier cannot be found
        if not done:
            guiprint('> could not find an existing tier to rename', colour=ERRORCOLOUR)


def movetier(args):

    connected = catalogueconnector('move tier', args, 'to')

    if connected:
        args = [connected[0], connected[1]]

    # if less than two arguments are given
    if len(args) < 2:
        guiprint('> enter the source tier and destination tier after the move tier directive', colour=TEXTCOLOUR)

    # if multiple arguments are given
    else:

        # seperate arguments into source and destination
        tokens = args

        done = False

        # wildcard multi-source mode: movetier <pattern...> <destination_tier>
        if any(haswild(t) for t in tokens[:-1]):

            sources, dstabs = wildcardarguments(tokens, want='dir')

            if not sources:

                guiprint('> could not move tier ensure source exists and destination is an existing tier', colour=ERRORCOLOUR)

                return

            if not os.path.isdir(dstabs):

                guiprint('> could not move tier ensure source exists and destination is an existing tier', colour=ERRORCOLOUR)

                return

            return transactionmove(sources, dstabs)

        for i in range(1, len(tokens)):

            src = ' '.join(tokens[:i])

            dst = ' '.join(tokens[i:])

            try:
                srcabs = os.path.abspath(resolvepath(src))
                dstabs = os.path.abspath(resolvepath(dst))
            except Exception:
                srcabs = INVALIDPATH
                dstabs = INVALIDPATH

            # if destination can be reached
            if os.path.exists(srcabs) and os.path.isdir(dstabs):

                # check the resolved source and actual destination paths
                target = os.path.join(dstabs, os.path.basename(srcabs))

                try:

                    if (
                        os.path.commonpath([
                            os.path.abspath(resolvepath(dst)),
                            os.path.abspath(resolvepath(src)),
                        ])
                        == os.path.abspath(resolvepath(src))
                    ):

                        guiprint(f'> cannot move {src} inside itself', colour=ERRORCOLOUR)
                        done = True
                        break

                except Exception:
                    pass

                if os.path.exists(target):

                    guiprint(f'> destination {target} already exists', colour=ERRORCOLOUR)
                    done = True
                    break

                if not allowpaths([srcabs, target]):

                    done = True

                    break

                try:

                    # move tier
                    shutil.move(srcabs, dstabs)

                    # tier moved message
                    guiprint(f'> tier moved to {dst}', colour=TEXTCOLOUR)

                    done = True

                    break

                # source not found error
                except FileNotFoundError:

                    guiprint(f'> source tier {src} not found', colour=ERRORCOLOUR)

                    done = True

                    break

                # destination invalid error
                except NotADirectoryError:

                    guiprint(f'> destination {dst} not a tier', colour=ERRORCOLOUR)

                    done = True

                    break

                # permission denied error
                except PermissionError:
                    guiprint(f'> permission denied', colour=ERRORCOLOUR)
                    done = True
                    break

                # other errors
                except OSError as e:

                    # move tier error
                    guiprint(f'> error moving tier {e}', colour=ERRORCOLOUR)

                    done = True

                    break

        # if tier cannot be moved
        if not done:
            guiprint('> could not move tier ensure source exists and destination is an existing tier', colour=ERRORCOLOUR)


def copytier(args):

    connected = catalogueconnector('copy tier', args, 'to')

    if connected:
        args = [connected[0], connected[1]]

    # resolve a complete existing path as one space-aware source
    singlesource = ' '.join(args) if args else ''

    try:

        singleexists = bool(singlesource) and os.path.isdir(os.path.abspath(resolvepath(singlesource)))

    except Exception:

        singleexists = False

    # if one argument or one complete existing path is given, duplicate in place
    if len(args) == 1 or singleexists:

        src = singlesource

        try:

            srcabs = os.path.abspath(resolvepath(src))

        except Exception:

            srcabs = INVALIDPATH

        if not os.path.isdir(srcabs):

            guiprint('> source tier not found', colour=ERRORCOLOUR)

            return

        parent = os.path.dirname(srcabs)

        name = os.path.basename(srcabs)

        newname = f"{name} - copy"

        target = os.path.join(parent, newname)

        count = 2

        while os.path.exists(target):

            newname = f"{name} - copy {count}"

            target = os.path.join(parent, newname)

            count += 1

        # check the resolved destination path
        if not allowpaths([target]):
            return

        try:

            shutil.copytree(srcabs, target)

            guiprint(f'> {name} copied to {newname}', colour=TEXTCOLOUR)

        except PermissionError:

            guiprint('> permission denied', colour=ERRORCOLOUR)

        except Exception as e:

            guiprint(f'> error copying tier {e}', colour=ERRORCOLOUR)

        return

    # if multiple arguments are given
    else:

        # seperate arguments into source and destination
        tokens = args

        done = False

        # wildcard multi-source mode: copytier <pattern...> <destination_tier>
        if any(haswild(t) for t in tokens[:-1]):

            sources, dstabs = wildcardarguments(tokens, want='dir')

            if not sources:

                guiprint('> could not copy tier ensure source exists and destination is an existing tier', colour=ERRORCOLOUR)

                return

            if not os.path.isdir(dstabs):

                guiprint('> could not copy tier ensure source exists and destination is an existing tier', colour=ERRORCOLOUR)

                return

            return transactioncopy(sources, dstabs)

        for i in range(1, len(tokens)):

            src = ' '.join(tokens[:i])

            dst = ' '.join(tokens[i:])

            # normalise paths
            try:

                srcabs = os.path.abspath(resolvepath(src))

                dstabs = os.path.abspath(resolvepath(dst))

            except Exception:

                srcabs = INVALIDPATH
                dstabs = INVALIDPATH

            # if source is an exisitng tier
            if os.path.exists(srcabs) and os.path.isdir(srcabs):

                # if destination can be reached
                if os.path.isdir(dstabs):

                    dstabs = os.path.join(dstabs, os.path.basename(srcabs))

                    dst = dstabs

                if os.path.exists(dstabs):

                    guiprint(f'> destination {dst} already exists', colour=ERRORCOLOUR)
                    done = True
                    break

                # check the resolved destination path
                if not allowpaths([dstabs]):

                    done = True

                    break

                try:

                    # copy tier
                    shutil.copytree(srcabs, dstabs)

                    # tier copied message
                    guiprint(f'> {os.path.basename(srcabs)} copied to {dst}', colour=TEXTCOLOUR)

                    done = True

                    break

                # destination already exists error
                except FileExistsError as e:

                    guiprint(f'> destination {dst} already exists', colour=ERRORCOLOUR)

                    return

                # permission denied error
                except PermissionError as e:

                    guiprint(f'> permission denied', colour=ERRORCOLOUR)

                    return

                # other os-related errors
                except OSError as e:

                    guiprint(f'> error copying tier {e}', colour=ERRORCOLOUR)

                    return

        # if tier cannot be copied
        if not done:
            guiprint('> could not copy tier ensure source exists', colour=ERRORCOLOUR)


# text directives
def write(args=None):

    if not args:

        guiprint("> filename required", colour=TEXTCOLOUR)

        return

    try:
        fullpath = followarraylink(resolvepath(" ".join(args)))
    except OSError as error:
        guiprint(f'> could not open link: {error}', colour=ERRORCOLOUR)
        return

    if not allowpaths([fullpath]):
        return

    try:

        writepath = "/the one/build/write/write.py"
        process = popenisolated(
            [sys.executable, writepath, fullpath],
            softwarepath=writepath,
            logpath="/the one/logs/write.py.log",
        )
        process.wait()

    except FileNotFoundError:

        guiprint('> write software missing', colour=ERRORCOLOUR)

        return

    except PermissionError:

        guiprint('> permission denied', colour=ERRORCOLOUR)

        return

    except Exception as e:

        guiprint(f'> error writing {e}', colour=ERRORCOLOUR)

        return

    resetshell()


def writein(args=None):

    # if no arguments given
    if not args or len(args) < 2:

        guiprint("> missing message andor file", colour=TEXTCOLOUR)

        return

    try:

        # preserve the literal as one argument and the complete file path as another
        literal = args[0]

        fullpath = followarraylink(resolvepath(' '.join(args[1:])))

        if not allowpaths([fullpath]):
            return

        # run write in and capture output
        res = subprocess.run(
            [sys.executable, "/the one/build/writein/write in.py", literal, fullpath],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        # track if we've already shown a permission denied line
        permissionprinted = False

        # decode and print stdout
        try:

            if res.stdout:

                out = res.stdout.decode('utf-8', errors='replace')

                for line in out.splitlines():

                    text = line.strip().lower()

                    # permission denied in stdout
                    if 'permission denied' in text:

                        if not permissionprinted:

                            guiprint(f'> {line}', colour=ERRORCOLOUR)

                            permissionprinted = True

                        # skip duplicate printing
                        continue

                    # normal stdout line
                    guiprint(line, colour=TEXTCOLOUR)

        except Exception as e:

            guiprint(f'> error decoding output {e}', colour=ERRORCOLOUR)

        # decode and print stderr
        try:

            if res.stderr:

                err = res.stderr.decode('utf-8', errors='replace')

                for line in err.splitlines():

                    text = line.strip().lower()

                    # permission denied in stderr
                    if 'permission denied' in text:

                        if not permissionprinted:

                            guiprint(f'> {line}', colour=ERRORCOLOUR)

                            permissionprinted = True

                        # skip duplicate printing
                        continue

                    # normal stderr line
                    guiprint(f'> {line}', colour=TEXTCOLOUR)

        except Exception as e:

            guiprint(f'> error decoding errors {e}', colour=ERRORCOLOUR)

    except FileNotFoundError:

        guiprint('> write in software missing', colour=ERRORCOLOUR)

        return

    except PermissionError:

        guiprint('> permission denied', colour=ERRORCOLOUR)

        return

    except Exception as e:

        guiprint(f'> error writing in {e}', colour=ERRORCOLOUR)

        return


def read(args=None):

    if not args:

        guiprint("> filename required", colour=TEXTCOLOUR)

        return

    try:

        tokens = [str(arg) for arg in args]
        suffix = []

        if len(tokens) >= 2 and tokens[-2].lower() == 'with' and tokens[-1].lower() == 'numbers':
            suffix = tokens[-2:]
            tokens = tokens[:-2]

        if len(tokens) >= 4 and tokens[0].lower() == 'last' and tokens[2].lower() == 'from':
            readargs = tokens[:3] + [followarraylink(resolvepath(' '.join(tokens[3:])))] + suffix

        elif len(tokens) >= 5 and tokens[-4].lower() == 'from' and tokens[-2].lower() == 'to':
            readargs = [followarraylink(resolvepath(' '.join(tokens[:-4])))] + tokens[-4:] + suffix

        else:
            readpath = ' '.join(tokens)
            readargs = [readpath if readpath == '-' else followarraylink(resolvepath(readpath))] + suffix

        # line above
        guiprint()

        # run reader and capture stdout/stderr
        res = subprocess.run(
            [sys.executable, "/the one/build/read/read.py", *readargs],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        try:

            # decode stdout (best-effort)
            if res.stdout:

                out = res.stdout.decode('utf-8', errors='replace')

                for line in out.splitlines():

                    guiprint(line, colour=TEXTCOLOUR)

        except Exception as e:

            # stdout decode error
            guiprint(f'> error decoding output {e}', colour=ERRORCOLOUR)

        try:

            # decode stderr and show as errors
            if res.stderr:

                err = res.stderr.decode('utf-8', errors='replace')

                for line in err.splitlines():

                    guiprint(f'> {line}', colour=ERRORCOLOUR)

        except Exception as e:

            # stderr decode error
            guiprint(f'> error decoding errors {e}', colour=ERRORCOLOUR)

        # line below
        guiprint()

        return int(res.returncode)

    except FileNotFoundError:

        # read software missing
        guiprint('> read software missing', colour=ERRORCOLOUR)

    except PermissionError:

        # permission denied
        guiprint('> permission denied', colour=ERRORCOLOUR)

    except Exception as e:

        # other errors starting the reader
        guiprint(f'> error launching read {e}', colour=ERRORCOLOUR)


def search(args=None):

    # if no arguments given
    if not args:

        guiprint('> search terms and filename required', colour=TEXTCOLOUR)

        return

    # line above
    guiprint()

    try:

        searchargs = [str(arg) for arg in args]
        inpositions = [index for index, value in enumerate(searchargs) if value.lower() == 'in']

        if inpositions:
            index = inpositions[-1]

            if index < len(searchargs) - 1:
                searchpath = followarraylink(resolvepath(' '.join(searchargs[index + 1:])))
                searchargs = searchargs[:index + 1] + [searchpath]

        else:

            # Name searches may end in one or more scope tiers without an "in".
            # Resolve each scope from the end using the search helper's grammar.
            remaining = list(searchargs)
            scopes = []

            while remaining:
                matched = False

                for count in range(1, len(remaining) + 1):
                    candidate = ' '.join(remaining[-count:])
                    resolved = followarraylink(resolvepath(candidate))

                    if os.path.isdir(resolved):
                        scopes.append(resolved)
                        remaining = remaining[:-count]
                        matched = True
                        break

                if not matched:
                    break

            if scopes:
                searchargs = remaining + list(reversed(scopes))

        # run search with the current hidden-file state and stream cancellable output
        environment = dict(os.environ)
        environment['T1OS_SEARCH_HIDDEN'] = '1' if SHOWHIDDEN else '0'

        proc = subprocess.Popen(
            [sys.executable, "/the one/build/search/search.py", *searchargs],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment
        )

        code = streamproc(proc, stoppable=True)

    except FileNotFoundError:

        # search script not found
        guiprint('> search software missing', colour=ERRORCOLOUR)

        return

    except PermissionError:

        # permission denied error
        guiprint('> permission denied', colour=ERRORCOLOUR)

        return

    except Exception as e:

        # other errors
        guiprint(f'> error searching {e}', colour=ERRORCOLOUR)

        return

    # line below
    guiprint()

    return code


def readsmallsetting(path, fallback=''):

    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as stream:
            return stream.read(4096).strip()
    except OSError:
        return str(fallback)


def settingenabled(path):

    return readsmallsetting(path).casefold() in ('1', 'true', 'yes', 'on')


def configuredtimezone():

    value = readsmallsetting(BRICKTIMEZONEFILE, 'Australia/Sydney')
    if value in ('10', '+10'):
        value = 'Australia/Sydney'
    return value or 'Australia/Sydney'


def timezoneobject(name):

    name = str(name or '').strip().replace('\\', '/')
    if (
        not name or name.startswith('/') or
        any(part in ('', '.', '..') for part in name.split('/'))
    ):
        raise ValueError('timezone must use an area and city')
    root = os.path.realpath(BRICKTIMEZONEDIR)
    path = os.path.realpath(os.path.join(root, *name.split('/')))
    if os.path.commonpath((root, path)) != root or not os.path.isfile(path):
        raise ValueError('unknown timezone ' + name)
    with open(path, 'rb') as stream:
        return zoneinfo.ZoneInfo.from_file(stream, key=name)


def settimezone(args=None):

    if len(args or []) != 1:
        guiprint('> enter an area and city after the set timezone directive',
                 colour=ERRORCOLOUR)
        return 1
    name = str(args[0]).strip()
    try:
        timezoneobject(name)
        result = settings_time_set(
            name,
            internet=settingenabled(BRICKINTERNETTIMEFILE),
            virtualbox=settingenabled(BRICKVIRTUALBOXTIMEFILE),
            timeout=5.0,
        )
        guiprint('> timezone set to ' + lowertext(result.get('timezone', name)),
                 colour=TEXTCOLOUR)
        return 0
    except Exception as error:
        guiprint('> could not set timezone ' + lowertext(error),
                 colour=ERRORCOLOUR)
        return 1


def setautomatictime(args=None):

    if len(args or []) != 1:
        guiprint(
            '> enter off, internet, virtualbox, or both after the set automatic time directive',
            colour=ERRORCOLOUR)
        return 1
    source = str(args[0]).strip().casefold()
    if source not in ('off', 'internet', 'virtualbox', 'both'):
        guiprint('> automatic time source is not supported', colour=ERRORCOLOUR)
        return 1
    try:
        settings_time_set(
            configuredtimezone(),
            internet=source in ('internet', 'both'),
            virtualbox=source in ('virtualbox', 'both'),
            timeout=5.0,
        )
        guiprint('> automatic time set to ' + source, colour=TEXTCOLOUR)
        return 0
    except Exception as error:
        guiprint('> could not set automatic time ' + lowertext(error),
                 colour=ERRORCOLOUR)
        return 1


def parseatreyandate(value):

    match = re.fullmatch(
        r'\s*(\d{1,2})\.(\d{1,2})\.(\d+)ae\s*',
        str(value), re.IGNORECASE)
    if not match:
        raise ValueError('date must use dd.mm.yae such as 23.07.6ae')
    day, month, atreyanyear = (int(part) for part in match.groups())
    if atreyanyear < 1:
        raise ValueError('atreyan dates begin in 1ae')
    return datetime.date(
        atreyanyear + (ATREYANSTARTYEAR - 1), month, day)


def setdateandtime(args=None):

    if len(args or []) != 2:
        guiprint(
            '> use set date and time <dd.mm.yae> <hh.mm>',
            colour=ERRORCOLOUR)
        return 1
    try:
        date = parseatreyandate(args[0])
        match = re.fullmatch(r'(\d{1,2})\.(\d{2})', str(args[1]).strip())
        if not match:
            raise ValueError('time must use hh.mm')
        hour, minute = (int(value) for value in match.groups())
        if not 0 <= hour <= 23 or not 0 <= minute <= 59:
            raise ValueError('time is outside the supported range')
        name = configuredtimezone()
        zone = timezoneobject(name)
        requested = datetime.datetime.combine(
            date, datetime.time(hour, minute)).replace(tzinfo=zone)
        epoch = requested.timestamp()
        roundtrip = datetime.datetime.fromtimestamp(epoch, zone)
        if roundtrip.replace(tzinfo=None) != requested.replace(tzinfo=None):
            raise ValueError('the local time does not exist in ' + name)
        settings_time_set(
            name, internet=False, virtualbox=False, epoch=epoch, timeout=5.0)
        guiprint(
            '> date and time set to {} {}'.format(
                lowertext(args[0]), lowertext(args[1])),
            colour=TEXTCOLOUR)
        return 0
    except Exception as error:
        guiprint('> could not set date and time ' + lowertext(error),
                 colour=ERRORCOLOUR)
        return 1


def terminalname(args=None):

    if args:
        guiprint('> terminal name does not take an argument', colour=ERRORCOLOUR)
        return 1
    guiprint('> terminal name ' + lowertext(
        readsmallsetting(BRICKTERMINALNAMEFILE, 't1os')),
        colour=TEXTCOLOUR)
    return 0


def setterminalname(args=None):

    if len(args or []) != 1:
        guiprint('> enter one name after the set terminal name directive',
                 colour=ERRORCOLOUR)
        return 1
    try:
        result = settings_hostname_set(str(args[0]), timeout=3.0)
        guiprint('> terminal name set to ' + lowertext(result.get('hostname')),
                 colour=TEXTCOLOUR)
        return 0
    except Exception as error:
        guiprint('> could not set terminal name ' + lowertext(error),
                 colour=ERRORCOLOUR)
        return 1


def masterprofile():

    try:
        with open(BRICKMASTERSETTINGSFILE, 'r', encoding='utf-8',
                  errors='replace') as stream:
            value = json.load(stream)
        if isinstance(value, dict):
            return (
                bool(value.get('use_master_image')),
                str(value.get('image_path') or ''),
            )
    except OSError:
        pass
    return False, ''


def changemastername(args=None):

    if len(args or []) != 1:
        guiprint('> enter one name after the change master name directive',
                 colour=ERRORCOLOUR)
        return 1
    password = ''
    try:
        account = settings_account_get(timeout=3.0)
        password = arch.readpass('> enter current master password ')
        if not password:
            guiprint('> master name change cancelled', colour=TEXTCOLOUR)
            return 1
        useimage, imagepath = masterprofile()
        result = settings_master_update(
            password, str(args[0]), use_master_image=useimage,
            image_path=imagepath, timeout=15.0)
        guiprint('> master name changed from {} to {}'.format(
            lowertext(account.get('username')),
            lowertext(result.get('username'))), colour=TEXTCOLOUR)
        return 0
    except Exception as error:
        guiprint('> could not change master name ' + lowertext(error),
                 colour=ERRORCOLOUR)
        return 1
    finally:
        password = ''


def changemasterpassword(args=None):

    if args:
        guiprint('> change master password does not take an argument',
                 colour=ERRORCOLOUR)
        return 1
    current = new = confirmation = ''
    try:
        current = arch.readpass('> enter current master password ')
        if not current:
            guiprint('> master password change cancelled', colour=TEXTCOLOUR)
            return 1
        new = arch.readpass('> enter new master password ')
        confirmation = arch.readpass('> confirm new master password ')
        if not new or new != confirmation:
            guiprint('> new master passwords do not match', colour=ERRORCOLOUR)
            return 1
        account = settings_account_get(timeout=3.0)
        useimage, imagepath = masterprofile()
        settings_master_update(
            current, account.get('username'), new_password=new,
            use_master_image=useimage, image_path=imagepath, timeout=15.0)
        guiprint('> master password changed', colour=TEXTCOLOUR)
        return 0
    except Exception as error:
        guiprint('> could not change master password ' + lowertext(error),
                 colour=ERRORCOLOUR)
        return 1
    finally:
        current = new = confirmation = ''


# operation directives
def view(args):

    if not args:

        guiprint('> enter an image file after the view directive', colour=TEXTCOLOUR)

        return

    name = ' '.join([str(arg) for arg in args]).strip()

    try:
        target = followarraylink(os.path.abspath(os.path.normpath(resolvepath(name))))
    except OSError as error:
        guiprint(f'> could not open link: {error}', colour=ERRORCOLOUR)
        return

    if not os.path.exists(target):

        guiprint(f'> image file {name} not found', colour=ERRORCOLOUR)

        return

    if not os.path.isfile(target):

        guiprint(f'> {name} is not an image file', colour=ERRORCOLOUR)

        return

    if not os.access(target, os.R_OK):

        guiprint(f'> permission denied reading {name}', colour=ERRORCOLOUR)

        return

    if viewerrequest is None or not os.path.isfile(VIEWERPATH):

        guiprint('> viewer software not found', colour=ERRORCOLOUR)

        return

    try:
        image = viewdecode(target)

    except Exception as error:
        guiprint(f'> could not view {name}: {error}', colour=ERRORCOLOUR)
        return

    size = image.get('source_size', [0, 0])
    guiprint(
        f"> {os.path.basename(target)} {size[0]}x{size[1]} {image.get('format', 'image')}",
        colour=TEXTCOLOUR,
    )
    viewappend(image)


def play(args):

    global PLAYBACK, PLAYBACK_DRAGGING, PLAYBACK_PREVIEW, DIRTY_SCROLL, DIRTY_PROMPT

    if not args:

        guiprint('> enter a media file after the play directive', colour=TEXTCOLOUR)

        return

    name = ' '.join([str(arg) for arg in args]).strip()

    try:
        target = followarraylink(os.path.abspath(os.path.normpath(resolvepath(name))))
    except OSError as error:
        guiprint(f'> could not open link: {error}', colour=ERRORCOLOUR)
        return

    if not os.path.exists(target):

        guiprint(f'> media file {name} not found', colour=ERRORCOLOUR)

        return

    if not os.path.isfile(target):

        guiprint(f'> {name} is not a media file', colour=ERRORCOLOUR)

        return

    if not os.access(target, os.R_OK):

        guiprint(f'> permission denied reading {name}', colour=ERRORCOLOUR)

        return

    if mediaapi is None or not os.path.isfile(MEDIAAPIPATH):

        guiprint('> media software not found', colour=ERRORCOLOUR)

        return

    try:

        info = mediaapi.mediainfo(target)

    except Exception as e:

        guiprint(f'> could not inspect {name}: {e}', colour=ERRORCOLOUR)

        return

    try:

        user = arch.currentrole

    except Exception:

        user = 'master'

    base = os.path.basename(target)

    opname = f'play {base}'

    logpath = '/the one/logs/media.py.log'

    guiprint()

    guiprint(f'> playing {base}', colour=TEXTCOLOUR)

    try:

        pid, sock, fileobj = opsrunstream(
            MEDIAAPIPATH,
            [
                'play',
                '--maximum-width', str(min(1280, max(320, int(getattr(gfx, '_xres', 1920)) - (LEFTPAD * 2)))),
                '--maximum-height', str(min(720, max(180, (playbackrows(info) - 2) * LINEHEIGHT))),
                target,
            ],
            opname,
            logpath,
            user,
        )

        if pid is None:

            raise Exception('operations server failed to start media playback')

    except Exception as e:

        guiprint(f'> error starting media playback {e}', colour=ERRORCOLOUR)

        guiprint()

        return

    jobadd(
        f'{MEDIAAPIPATH} play {target}',
        [int(pid)],
        'running',
        'front',
        logpath,
    )

    rows = playbackrows(info)
    controlroot = 'audio' if info.get('audio') else 'media'
    PLAYBACK = {
        'id': int(pid),
        'pid': int(pid),
        'path': target,
        'state': 'loading',
        'position': 0.0,
        'duration': 0.0,
        'control': f'/.ephemeral/{controlroot}/playback-{int(pid)}.sock',
        'media_kind': str(info.get('kind', 'audio')),
        'generation': 0,
        'rows': rows,
        'info': dict(info),
        'frame': {},
    }
    playbackappend(int(pid), rows=rows)
    PLAYBACK_DRAGGING = False
    PLAYBACK_PREVIEW = None
    DIRTY_SCROLL = True
    DIRTY_PROMPT = True
    drawcontent(cursor_on=False)

    if SOCK:

        pollserver()

    presentbrick()

    exitcode = None
    terminalstate = ''

    try:

        exitcode = opsstreamframes(pid, sock, fileobj)

    except Exception as e:

        guiprint(f'> error streaming media operation {e}', colour=ERRORCOLOUR)

    finally:

        terminalstate = str(PLAYBACK.get('state', ''))
        playbackid = PLAYBACK.get('id', int(pid))

        if terminalstate == 'stopped':

            summary = '> playback stopped'

        elif exitcode == 0:

            summary = '> playback complete'

        else:

            summary = '> playback ended'

        playbackfinish(playbackid, summary)
        PLAYBACK = {}
        PLAYBACK_DRAGGING = False
        PLAYBACK_PREVIEW = None
        DIRTY_SCROLL = True
        DIRTY_PROMPT = True
        drawcontent(cursor_on=True)

        if SOCK:

            pollserver()

        presentbrick()

    jobreap()

    guiprint()


def run(args):

    # if no arguments given
    if not args:

        guiprint("> enter filename after the run directive", colour=TEXTCOLOUR)

        return

    # determine behind context
    behind = False

    if args and args[-1] == 'behind':

        behind = True

        args = args[:-1]

    if HEADLESS and not behind:
        guiprint('> foreground software requires brick console mode', colour=ERRORCOLOUR)
        return 1

    # define target and trailing args
    prog = RUNAPPLICATIONALIASES.get(str(args[0]).strip().casefold())

    prog_args = list(args[1:]) if prog else []

    probe_error = None

    candidates = range(len(args), 0, -1) if prog is None else ()
    for i in candidates:

        candidate = ' '.join(args[:i])

        try:
            candidatepath = resolvepath(candidate)
        except Exception:
            continue

        try:

            os.stat(candidatepath, follow_symlinks=True)

        except OSError as error:

            # exists() deliberately hides EACCES and other policy failures.
            # Keep the final exact-candidate error so `run` can distinguish a
            # missing filename from software the graphical shell cannot access.
            probe_error = error

            continue

        else:

            prog = candidatepath

            prog_args = args[i:]

            break

    # catch missing operation
    if not prog:

        if probe_error is not None and getattr(probe_error, 'errno', None) not in (None, 2):

            guiprint(
                f"> could not access software {' '.join(args)}: {probe_error}",
                colour=ERRORCOLOUR)

        else:

            guiprint(f"> software {' '.join(args)} not found", colour=ERRORCOLOUR)

        return

    # resolve prog path for operations server context
    try:
        prog = followarraylink(os.path.normpath(prog))
    except OSError as error:
        guiprint(f'> could not run link: {error}', colour=ERRORCOLOUR)
        return

    iscatalogueapplication = prog in RUNAPPLICATIONPATHS
    if (str(prog).lower().endswith('.py') and not iscatalogueapplication and
            not preparepythonmodules(prog)):
        return 1

    try:

        # define user
        user = arch.currentrole

    except Exception:
        user = 'master'

    try:

        # derive operation name
        base = os.path.basename(str(prog))

        base = base.lstrip('/')

        name = os.path.splitext(base)[0]

    except Exception:

        # fallback name
        name = prog

    try:

        # define log path
        logpath = f"/the one/logs/{base}.log"

    except Exception:
        logpath = "/the one/logs/unknown.log"

    try:

        # define mode
        mode = 'behind'

        if not behind:

            mode = 'front'

    except Exception:

        mode = 'front'

    # line above
    guiprint()

    # Catalogue applications need their broker-owned security profile and
    # session identity whether they were launched by Expanse or by Brick.
    # They are graphical front applications, so do not attach them to Brick's
    # pseudo-terminal or execute their protected entrypoints directly.
    if iscatalogueapplication:
        pid = opsrun(prog, prog_args, name, logpath, user, 'front')
        if pid is None:
            guiprint(f'> error running {prog}', colour=ERRORCOLOUR)
            guiprint()
            return 1
        guiprint(f'> running {name}', colour=TEXTCOLOUR)
        guiprint(f'> pid {pid} log {logpath}', colour=TEXTCOLOUR)
        guiprint()
        return 0

    # behind path
    if behind:

        try:

            # run via operations server
            pid = opsrun(prog, prog_args, name, logpath, user, mode)

            if pid is None:
                raise Exception('operations server failed to run')

        except FileNotFoundError:

            guiprint(f'> software {prog} not found', colour=ERRORCOLOUR)

            guiprint()

            return

        except PermissionError:

            guiprint(f"> permission denied", colour=ERRORCOLOUR)

            guiprint()

            return

        except Exception as e:

            guiprint(f"> error running {prog} {e}", colour=ERRORCOLOUR)

            guiprint()

            return

        try:

            # build cmdline string
            cmdline = str(prog)

            if prog_args:

                cmdline = str(prog) + ' ' + ' '.join([str(x) for x in prog_args])

        except Exception:

            cmdline = str(prog)

        # add job record
        order = jobadd(cmdline, [int(pid)], 'running', mode, logpath)

        try:

            guiprint(f"> running {prog} behind", colour=TEXTCOLOUR)

        except Exception:
            guiprint(f"> running behind", colour=TEXTCOLOUR)

        if order:
            guiprint(f'> pid {pid} order %{order} log {logpath}', colour=TEXTCOLOUR)

        guiprint()

        return 0

    # foreground path
    try:
        cmdline = str(prog)
        if prog_args:
            cmdline += ' ' + ' '.join([str(value) for value in prog_args])
        startconsole(prog, prog_args, name, logpath, user, cmdline)
        return 0

    except FileNotFoundError:
        guiprint(f'> software {prog} not found', colour=ERRORCOLOUR)
    except PermissionError:
        guiprint('> permission denied', colour=ERRORCOLOUR)
    except Exception as error:
        guiprint(f'> error running {prog} {error}', colour=ERRORCOLOUR)

    guiprint()
    return 1


def showtable(headings, records):

    try:

        widths = [len(str(heading)) for heading in headings]

        for row in records:

            for index, value in enumerate(row):
                widths[index] = max(widths[index], len(str(value)))

        form = '  '.join('{' + str(index) + ':<' + str(width) + '}' for index, width in enumerate(widths))

        guiprint(form.format(*headings), colour=TEXTCOLOUR)
        guiprint()

        for row in records:
            guiprint(form.format(*row), colour=TEXTCOLOUR)

        return True

    except Exception as e:

        guiprint(f'> error formatting table {e}', colour=ERRORCOLOUR)
        return False


def softwarecatalogue():

    try:
        result = listcatalogueapplications(timeout=3.0)
        applications = result.get('applications', [])
        if not isinstance(applications, list):
            raise ValueError('software catalogue response is invalid')
        return [item for item in applications if isinstance(item, dict)]
    except Exception as error:
        guiprint('> could not read the software catalogue ' + lowertext(error),
                 colour=ERRORCOLOUR)
        return None


def listsoftware(args=None):

    if args:
        guiprint('> list software does not take an argument', colour=ERRORCOLOUR)
        return 1
    applications = softwarecatalogue()
    if applications is None:
        return 1
    records = [[
        item.get('name', ''),
        item.get('handler', 'none'),
        item.get('profile', ''),
        'yes' if item.get('startup') else 'no',
        str(item.get('running', 0)),
    ] for item in applications]
    guiprint()
    if records:
        showtable(
            ['software', 'handler', 'profile', 'startup', 'running'],
            lowerrows(records))
    else:
        guiprint('> no software is available', colour=TEXTCOLOUR)
    guiprint()
    return 0


def softwaredetails(args=None):

    requested = ' '.join(str(value) for value in (args or [])).strip().casefold()
    if not requested:
        guiprint('> enter software after the software details directive',
                 colour=ERRORCOLOUR)
        return 1
    applications = softwarecatalogue()
    if applications is None:
        return 1
    exact = [item for item in applications
             if str(item.get('name', '')).casefold() == requested]
    matches = exact or [
        item for item in applications
        if requested in str(item.get('name', '')).casefold()
    ]
    if not matches:
        guiprint('> software not found ' + requested, colour=ERRORCOLOUR)
        return 1
    if len(matches) > 1:
        guiprint('> more than one software entry matches ' + requested,
                 colour=ERRORCOLOUR)
        showtable(['software'], lowerrows([[item.get('name', '')] for item in matches]))
        return 1
    item = matches[0]
    records = [
        ['software', item.get('name', '')],
        ['path', item.get('path', '')],
        ['handler', item.get('handler', 'none')],
        ['security profile', item.get('profile', '')],
        ['startup supported', 'yes' if item.get('startup') else 'no'],
        ['running operations', str(item.get('running', 0))],
    ]
    guiprint()
    showtable(['detail', 'value'], lowerrows(records))
    guiprint()
    return 0


def operationdetails(args=None):

    targets, _, requested = operationtargets(args, includecompleted=True)
    if not requested:
        guiprint('> enter an operation name, pid, or %order', colour=ERRORCOLOUR)
        return 1
    if not targets:
        guiprint('> no operations matching ' + lowertext(requested),
                 colour=ERRORCOLOUR)
        return 1
    if len(targets) > 1:
        guiprint('> more than one operation matches ' + lowertext(requested),
                 colour=ERRORCOLOUR)
        showtable(['pid', 'operation'], lowerrows([
            [pid, info.get('name', '')] for pid, info in targets
        ]))
        return 1
    pid, fallback = targets[0]
    response = opslistrequest(resources=True)
    if response is None:
        guiprint('> operations service is unavailable', colour=ERRORCOLOUR)
        return 1
    info = response.get('operations', {}).get(str(pid))
    if info is None:
        info = response.get('completed', {}).get(str(pid), fallback)
    resources = info.get('resources', {}) if isinstance(info, dict) else {}
    if not isinstance(resources, dict):
        resources = {}
    arguments = ' '.join(str(value) for value in info.get('args', []))
    records = [
        ['operation', info.get('name', '')],
        ['pid', pid],
        ['state', info.get('state', '')],
        ['mode', info.get('mode', '')],
        ['user', info.get('user', '')],
        ['cpu', formatpercent(resources.get('cpu_percent'))],
        ['gpu', formatpercent(resources.get('gpu_percent'))],
        ['memory', formatbytes(resources.get('memory_bytes'))],
        ['peak memory', formatbytes(resources.get(
            'peak_memory_bytes', info.get('peak_memory_bytes')))],
        ['threads', resources.get('threads', 'unavailable')],
        ['children', resources.get('children', 'unavailable')],
        ['read', formatbytes(resources.get('read_bytes'))],
        ['written', formatbytes(resources.get('write_bytes'))],
        ['started', displaytimestamp(info.get('started')) if info.get('started') else 'unavailable'],
        ['ended', displaytimestamp(info.get('ended')) if info.get('ended') else 'running'],
        ['result', info.get('exitcode') if info.get('exitcode') is not None else 'unavailable'],
        ['script', info.get('script', '')],
        ['arguments', arguments],
        ['log', info.get('log', '')],
    ]
    guiprint()
    showtable(['detail', 'value'], lowerrows(records))
    guiprint()
    return 0


def systemperformance(args=None):

    if args:
        guiprint('> system performance does not take an argument',
                 colour=ERRORCOLOUR)
        return 1
    response = opslistrequest(resources=True)
    if response is None:
        guiprint('> operations service is unavailable', colour=ERRORCOLOUR)
        return 1
    system = response.get('system', {})
    if not isinstance(system, dict):
        system = {}
    records = [
        ['cpu', formatpercent(system.get('cpu_percent'))],
        ['gpu', formatpercent(system.get('gpu_percent'))],
        ['graphics processor', system.get('gpu_name') or 'unavailable'],
        ['graphics backend', system.get('gpu_backend') or 'unavailable'],
        ['gpu acceleration', 'active' if system.get('gpu_accelerated') else 'not active'],
        ['memory used', formatbytes(system.get('memory_used_bytes'))],
        ['memory available', formatbytes(system.get('memory_available_bytes'))],
        ['memory total', formatbytes(system.get('memory_total_bytes'))],
        ['running operations', str(len(response.get('operations', {})))],
        ['sample time', str(response.get('sample_ms', 0)) + ' ms'],
    ]
    guiprint()
    showtable(['resource', 'value'], lowerrows(records))
    guiprint()
    return 0


def listops(args):

    operations, completed = operationdata()
    target = ' '.join([str(arg) for arg in (args or [])]).strip()
    source = completed if target.casefold() == 'completed' else operations
    records = []

    for pid, info in source.items():

        try:

            name = str(info.get('name', ''))
            script = str(info.get('script', ''))
            mode = str(info.get('mode', ''))
            state = str(info.get('state', 'completed' if source is completed else 'running'))
            user = str(info.get('user', ''))
            logpath = str(info.get('log', '') or '')

            if target and target.casefold() != 'completed':

                requested = target.casefold()

                if requested in ('front', 'behind'):

                    if mode.casefold() != requested:
                        continue

                elif requested not in name.casefold() and requested not in script.casefold() and requested != str(pid):
                    continue

            startedraw = info.get('started')
            endedraw = info.get('ended')
            exitcode = info.get('exitcode')
            arguments = ' '.join([str(value) for value in info.get('args', [])])
            result = '-' if exitcode is None else str(exitcode)
            duration = '-'

            if startedraw:

                try:
                    stopped = float(endedraw) if endedraw is not None else float(time.time())
                    duration = f'{max(0.0, stopped - float(startedraw)):.1f}s'
                    started = displaytimestamp(startedraw)
                except Exception:
                    started = str(startedraw)

            else:
                started = '-'

            records.append([str(pid), state, mode, user, name, result, duration, script, arguments, started, logpath])

        except Exception:
            continue

    if not records:

        guiprint('> no matching operations' if target else '> no running operations', colour=TEXTCOLOUR)
        return 0

    records.sort(key=lambda row: int(row[0]))
    guiprint()
    showtable(['pid', 'state', 'mode', 'user', 'operation', 'result', 'duration', 'script', 'arguments', 'started', 'log'], records)
    guiprint()
    return 0


def killop(args):

    targets, force, requested = operationtargets(args)

    if not requested:

        guiprint('> enter the operation name, pid, or %order after the kill directive', colour=TEXTCOLOUR)
        return 1

    if not targets:

        guiprint(f'> no operations matching {requested}', colour=ERRORCOLOUR)
        return 1

    if len(targets) > 1 and not requested.startswith('%'):

        records = []

        for pid, info in targets:
            records.append([str(pid), str(info.get('name', '')), str(info.get('script', ''))])

        guiprint(f'> more than one operation matches {requested}', colour=ERRORCOLOUR)
        showtable(['pid', 'operation', 'script'], records)
        guiprint('> use a pid to select one operation', colour=TEXTCOLOUR)
        return 1

    failed = False

    for pid, info in targets:

        if not operationallowed(pid, info):

            guiprint(f'> permission denied killing operation {pid}', colour=ERRORCOLOUR)
            failed = True
            continue

        killed = opskill(pid, force=force)

        if killed:

            wording = 'force killed' if force else 'killed'
            guiprint(f'> operation {pid} {wording}', colour=TEXTCOLOUR)

            for job in JOBS.values():

                if int(pid) in [int(value) for value in job.get('pids', [])]:
                    job['state'] = 'killed'
                    job['ended'] = float(time.time())
                    job['exitcode'] = -9 if force else -15

        else:

            guiprint(f'> failed to kill operation {pid}', colour=ERRORCOLOUR)
            failed = True

    return 1 if failed else 0


def singleoperation(args, includecompleted=False):

    targets, _, requested = operationtargets(args, includecompleted=includecompleted)

    if not requested:

        guiprint('> enter an operation name, pid, or %order', colour=TEXTCOLOUR)
        return None

    if not targets:

        guiprint(f'> no operations matching {requested}', colour=ERRORCOLOUR)
        return None

    if len(targets) > 1:

        records = [[str(pid), str(info.get('name', '')), str(info.get('script', ''))] for pid, info in targets]
        guiprint(f'> more than one operation matches {requested}', colour=ERRORCOLOUR)
        showtable(['pid', 'operation', 'script'], records)
        return None

    return targets[0]


def readlog(args):

    selected = singleoperation(args, includecompleted=True)

    if not selected:
        return 1

    pid, info = selected
    logpath = str(info.get('log', '') or '')

    if not logpath or logpath == '-':

        guiprint(f'> operation {pid} has no log', colour=ERRORCOLOUR)
        return 1

    return read([logpath])


def followlog(args):

    selected = singleoperation(args)

    if not selected:
        return 1

    pid, info = selected
    logpath = str(info.get('log', '') or '')

    if not logpath or logpath == '-':

        guiprint(f'> operation {pid} has no log', colour=ERRORCOLOUR)
        return 1

    guiprint(f'> following {logpath}; press ctrl-s to stop', colour=TEXTCOLOUR)
    return logtail(logpath, int(pid), stoppable=True)


def waitfor(args):

    selected = singleoperation(args, includecompleted=True)

    if not selected:
        return 1

    pid, info = selected
    guiprint(f'> waiting for operation {pid}; press ctrl-s to stop', colour=TEXTCOLOUR)

    while True:

        if stoppable:

            try:

                for ch in pollchars(timeout_ms=0):

                    if ch == STOPKEY or ch == '<STOP>':

                        if f:
                            f.close()

                        guiprint('> stopped following log', colour=TEXTCOLOUR)
                        return 0

            except Exception:
                pass

        try:

            for ch in pollchars(timeout_ms=0):

                if ch == STOPKEY or ch == '<STOP>':

                    guiprint(f'> stopped waiting for operation {pid}', colour=TEXTCOLOUR)
                    return 0

        except Exception:
            pass

        response = opswait(pid, timeout=0.25)

        if not response:

            if not procalive(pid):

                guiprint(f'> operation {pid} completed; result unknown', colour=TEXTCOLOUR)
                return 0

            continue

        if response.get('status') == 'waiting':
            continue

        if response.get('status') != 'ok':

            guiprint(f"> error waiting for operation {pid} {response.get('message', '')}", colour=ERRORCOLOUR)
            return 1

        operation = response.get('operation', {})
        state = str(operation.get('state', 'completed'))
        code = operation.get('exitcode')
        guiprint(f'> operation {pid} {state} result {code if code is not None else "unknown"}', colour=TEXTCOLOUR)

        if code is None:
            return 0

        return 0 if int(code) == 0 else 1


def startupops(args=None):

    if args:
        guiprint('> startup operations does not take an argument',
                 colour=ERRORCOLOUR)
        return 1
    try:
        result = startupoperations(timeout=3.0)
        entries = result.get('operations', [])
        records = [
            [str(index), entry.get('mode', ''), entry.get('software', '')]
            for index, entry in enumerate(entries, 1)
            if isinstance(entry, dict)
        ]
        if not records:
            guiprint('> no startup operations', colour=TEXTCOLOUR)
            return 0
        guiprint()
        showtable(['order', 'mode', 'software'], lowerrows(records))
        guiprint()
        return 0
    except Exception as error:
        guiprint('> could not read startup operations ' + lowertext(error),
                 colour=ERRORCOLOUR)
        return 1


def startuparguments(args, requiremode=False):

    values = [str(value) for value in (args or [])]
    mode = ''
    if requiremode:
        if len(values) < 2 or values[-1].casefold() not in ('front', 'behind'):
            return '', ''
        mode = values.pop().casefold()
    return ' '.join(values).strip().casefold(), mode


def addstartup(args=None):

    software, mode = startuparguments(args, requiremode=True)
    if not software:
        guiprint(
            '> use add startup operation <software> <front or behind>',
            colour=ERRORCOLOUR)
        return 1
    try:
        addstartupoperation(software, mode, timeout=3.0)
        guiprint('> startup operation added ' + software + ' ' + mode,
                 colour=TEXTCOLOUR)
        return 0
    except Exception as error:
        guiprint('> could not add startup operation ' + lowertext(error),
                 colour=ERRORCOLOUR)
        return 1


def removestartup(args=None):

    software, _ = startuparguments(args)
    if not software:
        guiprint('> enter software after the remove startup operation directive',
                 colour=ERRORCOLOUR)
        return 1
    try:
        removestartupoperation(software, timeout=3.0)
        guiprint('> startup operation removed ' + software,
                 colour=TEXTCOLOUR)
        return 0
    except Exception as error:
        guiprint('> could not remove startup operation ' + lowertext(error),
                 colour=ERRORCOLOUR)
        return 1


def changestartup(args=None):

    software, mode = startuparguments(args, requiremode=True)
    if not software:
        guiprint(
            '> use change startup operation <software> <front or behind>',
            colour=ERRORCOLOUR)
        return 1
    try:
        changestartupoperation(software, mode, timeout=3.0)
        guiprint('> startup operation changed ' + software + ' ' + mode,
                 colour=TEXTCOLOUR)
        return 0
    except Exception as error:
        guiprint('> could not change startup operation ' + lowertext(error),
                 colour=ERRORCOLOUR)
        return 1


def sessionops(args):

    global JOBS

    # reap first so output is accurate
    jobreap()

    try:

        # no jobs
        if not JOBS:

            guiprint('> no session operations', colour=TEXTCOLOUR)

            return

    except Exception as e:

        # jobs read error
        guiprint(f'> error reading session operations {e}', colour=ERRORCOLOUR)

        return

    records = []

    try:

        # show jobs in numeric order
        ids = sorted([int(x) for x in JOBS.keys()])

    except Exception:

        ids = list(JOBS.keys())

    try:

        # build rows
        for jid in ids:

            jobid = str(jid)

            state = str(JOBS[jobid].get('state', 'unknown'))

            pids = JOBS[jobid].get('pids', [])

            cmdline = str(JOBS[jobid].get('cmdline', ''))

            pidtext = ' '.join([str(x) for x in pids])

            started = float(JOBS[jobid].get('started', time.time()))
            ended = JOBS[jobid].get('ended')
            stopped = float(ended) if ended is not None else float(time.time())
            duration = f'{max(0.0, stopped - started):.1f}s'
            exitcode = JOBS[jobid].get('exitcode')
            result = '-' if exitcode is None else str(exitcode)
            logpath = str(JOBS[jobid].get('stdio', '') or '')

            records.append([jobid, state, pidtext, duration, result, cmdline, logpath])

    except Exception as e:

        # records build error
        guiprint(f'> error building session operations table {e}', colour=ERRORCOLOUR)

        return

    if not records:
        guiprint('> no session operations', colour=TEXTCOLOUR)

        return

    headings = ['order', 'state', 'pids', 'duration', 'result', 'operation', 'log']

    try:

        # calculate widths
        widths = [len(h) for h in headings]

        for row in records:

            for i, cell in enumerate(row):

                if len(cell) > widths[i]:

                    widths[i] = len(cell)

        # define table format
        fmt = '  '.join('{' + str(i) + ':<' + str(w) + '}' for i, w in enumerate(widths))

    except Exception as e:

        # table format error
        guiprint(f'> error formatting session operation table {e}', colour=ERRORCOLOUR)

        return

    # line above
    guiprint()

    # print headings
    guiprint(fmt.format(*headings), colour=TEXTCOLOUR)

    # spacer
    guiprint()

    # print rows
    for row in records:

        try:

            guiprint(fmt.format(*row), colour=TEXTCOLOUR)

        except Exception as e:

            # row print error
            guiprint(f'> error showing session operation row {e}', colour=ERRORCOLOUR)

    # line below
    guiprint()


# network directives
def networkreadjson(path, fallback=None):

    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as stream:
            value = json.load(stream)
        return value if isinstance(value, dict) else dict(fallback or {})
    except Exception:
        return dict(fallback or {})


def networkreadconfig():

    values = {}

    try:
        with open(BRICKNETWORKFILE, 'r', encoding='utf-8', errors='replace') as stream:
            for rawline in stream:
                line = rawline.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, value = line.split('=', 1)
                key = key.strip().lower()
                if re.fullmatch(r'[a-z][a-z0-9_]*', key):
                    values[key] = value.strip()
    except FileNotFoundError:
        pass

    return values


def networkatomictext(path, content, mode=0o644):

    directory = os.path.dirname(path)
    os.makedirs(directory, mode=0o755, exist_ok=True)
    temporary = '{}.{}.tmp'.format(path, os.getpid())

    try:
        with open(temporary, 'w', encoding='utf-8', newline='\n') as stream:
            stream.write(str(content))
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except OSError:
            pass


def networkwriteconfig(config):

    order = ('interface', 'dns', 'firewall', 'dhcp', 'address', 'netmask', 'gateway')
    keys = [key for key in order if key in config]
    keys.extend(sorted(key for key in config if key not in keys))
    lines = []

    for key in keys:
        value = str(config.get(key, '')).strip()
        if '\n' in value or '\r' in value or '=' in str(key):
            raise ValueError('the network setting contains an unsupported character')
        lines.append(str(key) + '=' + value)

    networkatomictext(BRICKNETWORKFILE, '\n'.join(lines) + '\n')


def networkrequest(path):

    networkatomictext(path, str(int(time.time())) + '\n')


def networkreconfigure(config):

    networkwriteconfig(config)
    networkrequest(BRICKNETWORKREQUEST)


def networkinterfacesdata():

    configured = str(networkreadconfig().get('interface') or '').strip()
    runtime = networkreadjson(BRICKNETWORKSTATE)
    active = str(runtime.get('interface') or '').strip()
    names = set()

    try:
        names.update(
            name for name in os.listdir(BRICKNETSTATE)
            if name != 'lo' and os.path.isdir(os.path.join(BRICKNETSTATE, name)))
    except OSError:
        pass

    for name in (configured, active):
        if name:
            names.add(name)

    records = []
    for name in sorted(names, key=str.casefold):
        lowered = name.casefold()
        wireless = (
            os.path.isdir(os.path.join(BRICKNETSTATE, name, 'wireless')) or
            lowered.startswith(('wl', 'wifi')))
        state = ''
        try:
            with open(os.path.join(BRICKNETSTATE, name, 'operstate'), 'r', encoding='ascii', errors='replace') as stream:
                state = stream.read().strip().lower()
        except OSError:
            pass
        records.append({
            'name': name,
            'type': 'wi-fi' if wireless else 'ethernet',
            'state': 'connected' if name == active and bool(runtime.get('connected')) else (state or 'offline'),
            'preferred': name == configured,
            'active': name == active,
        })
    return records


def networkdetails(args=None):

    if args:
        guiprint('> network details does not take an argument', colour=ERRORCOLOUR)
        return 1

    state = networkreadjson(BRICKNETWORKSTATE)
    config = networkreadconfig()
    interface = str(state.get('interface') or config.get('interface') or '')
    connected = bool(state.get('connected'))
    records = [
        ('connection', 'connected' if connected else 'offline'),
        ('type', str(state.get('type') or 'unavailable')),
        ('interface', interface or 'automatic'),
        ('network', str(state.get('name') or 'unavailable')),
        ('address', str(state.get('address') or 'unavailable')),
        ('gateway', str(state.get('gateway') or 'unavailable')),
        ('dhcp server', str(state.get('server') or 'unavailable')),
        ('mac', str(state.get('mac') or 'unavailable')),
        ('address mode', 'automatic' if str(config.get('dhcp', 'true')).casefold() == 'true' else 'manual'),
    ]
    guiprint()
    showtable(['detail', 'value'], lowerrows(records))
    guiprint()
    return 0


def listnetworkinterfaces(args=None):

    if args:
        guiprint('> list network interfaces does not take an argument', colour=ERRORCOLOUR)
        return 1

    records = networkinterfacesdata()
    guiprint()

    if not records:
        guiprint('> no network interfaces found', colour=ERRORCOLOUR)
        guiprint()
        return 1

    showtable(
        ['interface', 'type', 'state', 'selection'],
        lowerrows([(item['name'], item['type'], item['state'],
          'preferred' if item['preferred'] else ('active' if item['active'] else ''))
         for item in records]))
    guiprint()
    return 0


def usenetworkinterface(args=None):

    if len(args or []) != 1:
        guiprint('> enter automatic or one interface after the use network interface directive', colour=ERRORCOLOUR)
        return 1

    requested = str(args[0]).strip()
    interface = '' if requested.casefold() == 'automatic' else requested

    if interface and re.fullmatch(r'[A-Za-z0-9_.:-]{1,15}', interface) is None:
        guiprint('> the network interface name is invalid', colour=ERRORCOLOUR)
        return 1

    available = {item['name'] for item in networkinterfacesdata()}
    if interface and interface not in available:
        guiprint('> the network interface was not found', colour=ERRORCOLOUR)
        return 1

    try:
        config = networkreadconfig()
        config['interface'] = interface
        networkreconfigure(config)
    except Exception as error:
        guiprint(f'> could not change the network interface {lowertext(error)}', colour=ERRORCOLOUR)
        return 1

    guiprint('> network interface set to ' + lowertext(interface or 'automatic'), colour=TEXTCOLOUR)
    return 0


def setnetworkaddress(args=None):

    values = [str(value).strip() for value in (args or [])]
    automatic = len(values) == 1 and values[0].casefold() == 'automatic'

    if not automatic and len(values) != 3:
        guiprint('> use set network address automatic or set network address <address> <prefix> <gateway>', colour=ERRORCOLOUR)
        return 1

    try:
        config = networkreadconfig()

        if automatic:
            config['dhcp'] = 'true'
            for key in ('address', 'netmask', 'gateway'):
                config.pop(key, None)
        else:
            address = ipaddress.ip_address(values[0])
            gateway = ipaddress.ip_address(values[2])
            prefix = int(values[1])
            if address.version != 4 or gateway.version != 4 or prefix < 0 or prefix > 32:
                raise ValueError('use an ipv4 address, prefix from 0 to 32, and ipv4 gateway')
            config.update({
                'dhcp': 'false',
                'address': str(address),
                'netmask': str(prefix),
                'gateway': str(gateway),
                'dns': 'manual',
            })

            if not networkdnsservers():
                raise ValueError('set at least one dns server before using a manual address')

        networkwriteinterfaceconfig(config)
        networkreconfigure(config)
    except Exception as error:
        guiprint(f'> could not change the network address {lowertext(error)}', colour=ERRORCOLOUR)
        return 1

    guiprint('> automatic network addressing requested' if automatic else '> manual network address requested', colour=TEXTCOLOUR)
    return 0


def networkwriteinterfaceconfig(config):

    interface = str(config.get('interface') or '').strip()
    if not interface:
        return
    lines = ['dhcp=' + ('true' if str(config.get('dhcp', 'true')).casefold() == 'true' else 'false')]
    if lines[0] == 'dhcp=false':
        lines.extend((
            'address=' + str(config.get('address') or ''),
            'netmask=' + str(config.get('netmask') or ''),
            'gateway=' + str(config.get('gateway') or ''),
        ))
    networkatomictext(os.path.join(BRICKNETWORKDIR, interface + '.txt'), '\n'.join(lines) + '\n')


def networkdnsservers():

    servers = []
    try:
        with open(BRICKDNSFILE, 'r', encoding='utf-8', errors='replace') as stream:
            for line in stream:
                fields = line.split()
                if len(fields) == 2 and fields[0].casefold() == 'nameserver':
                    try:
                        value = ipaddress.ip_address(fields[1])
                    except ValueError:
                        continue
                    if value.version == 4 and str(value) not in servers:
                        servers.append(str(value))
    except OSError:
        pass
    return servers[:3]


def dnsstatus(args=None):

    if args:
        guiprint('> dns status does not take an argument', colour=ERRORCOLOUR)
        return 1
    config = networkreadconfig()
    mode = str(config.get('dns') or 'automatic').casefold()
    servers = networkdnsservers()
    guiprint()
    showtable(['detail', 'value'], lowerrows([
        ('mode', 'automatic' if mode == 'automatic' else 'manual'),
        ('primary', servers[0] if servers else 'unavailable'),
        ('secondary', servers[1] if len(servers) > 1 else 'unavailable'),
    ]))
    guiprint()
    return 0


def setdnsautomatic(args=None):

    if args:
        guiprint('> set dns automatic does not take an argument', colour=ERRORCOLOUR)
        return 1
    try:
        config = networkreadconfig()
        if str(config.get('dhcp', 'true')).casefold() != 'true':
            raise ValueError('automatic dns requires automatic network addressing')
        config['dns'] = 'automatic'
        networkreconfigure(config)
    except Exception as error:
        guiprint(f'> could not enable automatic dns {lowertext(error)}', colour=ERRORCOLOUR)
        return 1
    guiprint('> automatic dns requested', colour=TEXTCOLOUR)
    return 0


def setdnsservers(args=None):

    values = [str(value).strip() for value in (args or [])]
    if len(values) not in (1, 2):
        guiprint('> enter one or two addresses after the set dns servers directive', colour=ERRORCOLOUR)
        return 1
    try:
        servers = []
        for value in values:
            address = ipaddress.ip_address(value)
            if address.version != 4:
                raise ValueError('dns servers must be ipv4 addresses')
            if str(address) not in servers:
                servers.append(str(address))
        config = networkreadconfig()
        config['dns'] = 'manual'
        networkatomictext(
            BRICKDNSFILE,
            ''.join('nameserver ' + server + '\n' for server in servers))
        networkreconfigure(config)
    except Exception as error:
        guiprint(f'> could not change the dns servers {lowertext(error)}', colour=ERRORCOLOUR)
        return 1
    guiprint('> manual dns servers requested', colour=TEXTCOLOUR)
    return 0


def firewallstatus(args=None):

    if args:
        guiprint('> firewall status does not take an argument', colour=ERRORCOLOUR)
        return 1
    config = networkreadconfig()
    state = networkreadjson(BRICKFIREWALLSTATE)
    profile = str(state.get('profile') or config.get('firewall') or 'protected')
    active = bool(state.get('active'))
    guiprint()
    showtable(['detail', 'value'], lowerrows([
        ('status', 'active' if active else 'not active'),
        ('profile', profile),
        ('incoming', str(state.get('incoming') or ('allowed' if profile == 'open' else 'blocked'))),
        ('forwarding', str(state.get('forwarding') or 'blocked')),
        ('outgoing', str(state.get('outgoing') or 'allowed')),
    ]))
    guiprint()
    return 0 if active else 1


def setfirewall(args=None):

    if len(args or []) != 1 or str(args[0]).casefold() not in ('protected', 'open'):
        guiprint('> enter protected or open after the set firewall directive', colour=ERRORCOLOUR)
        return 1
    profile = str(args[0]).casefold()
    try:
        config = networkreadconfig()
        config['firewall'] = profile
        networkreconfigure(config)
    except Exception as error:
        guiprint(f'> could not change the firewall {lowertext(error)}', colour=ERRORCOLOUR)
        return 1
    guiprint('> firewall profile ' + profile + ' requested', colour=TEXTCOLOUR)
    return 0


def scanwifi(args=None):

    if args:
        guiprint('> scan wifi does not take an argument', colour=ERRORCOLOUR)
        return 1
    if not any(item['type'] == 'wi-fi' for item in networkinterfacesdata()):
        guiprint('> no wi-fi interface found', colour=ERRORCOLOUR)
        return 1
    try:
        networkrequest(BRICKWIRELESSREQUEST)
    except Exception as error:
        guiprint(f'> could not request a wi-fi scan {lowertext(error)}', colour=ERRORCOLOUR)
        return 1
    guiprint('> wi-fi scan requested', colour=TEXTCOLOUR)
    return 0


def listwifinetworks(args=None):

    if args:
        guiprint('> list wifi networks does not take an argument', colour=ERRORCOLOUR)
        return 1
    state = networkreadjson(BRICKWIRELESSSTATE, {'networks': []})
    records = []
    seen = set()
    for item in state.get('networks', []):
        if not isinstance(item, dict):
            continue
        name = ''.join(character for character in str(item.get('ssid') or '') if character.isprintable()).strip()
        security = str(item.get('security') or 'unknown').casefold()
        if not name or name in seen or security not in ('open', 'wpa2', 'wpa3'):
            continue
        seen.add(name)
        try:
            signalvalue = int(item.get('signal', -999))
        except (TypeError, ValueError):
            signalvalue = -999
        records.append((name, security, str(signalvalue)))
    records.sort(key=lambda row: (-int(row[2]), row[0].casefold()))
    guiprint()
    if not records:
        guiprint('> no wi-fi networks found', colour=ERRORCOLOUR)
        guiprint('> use scan wifi to request a new scan', colour=TEXTCOLOUR)
        guiprint()
        return 1
    showtable(['network', 'security', 'signal'], lowerrows(records))
    guiprint()
    return 0


def netstatus(args=None):

    # line above
    guiprint()

    try:

        # open a netlink socket
        ip = IPRoute()

    except Exception as e:

        # could not open netlink socket error
        guiprint(f"> could not open socket {e}", colour=ERRORCOLOUR)

        # line below
        guiprint()

        return

    try:

        # find the first non-loopback interface
        iface = None

        for link in ip.get_links():

            name = link.get_attr('IFLA_IFNAME')

            if name and name != 'lo':

                iface = name

                break

        # if no suitable interface is found
        if not iface:

            # no valid interface message
            guiprint("no valid interface found", colour=ERRORCOLOUR)

            # line below
            guiprint()

            # close the socket
            ip.close()
            return

        # look up interface index
        idxs = ip.link_lookup(ifname=iface)

        # if not interface is found
        if not idxs:

            # interface not found message
            guiprint(f"interface {iface} not found", colour=ERRORCOLOUR)

            # line below
            guiprint()

            # close socket
            ip.close()
            return

        # define the first matching index
        idx = idxs[0]

        # fetch the link info
        info = ip.get_links(idx)[0]

        # extract the mac address
        mac = info.get_attr('IFLA_ADDRESS')

        # fetch ipv4 address(es)
        addrs = ip.get_addr(index=idx, family=socket.AF_INET)
        if addrs:

            # define the first address
            addr   = addrs[0].get_attr('IFA_ADDRESS')

            # define prefix length
            prefix = addrs[0].get('prefixlen')

        # if no address or prefix are found
        else:

            addr   = None

            prefix = None

        # discover the default gateway
        gw = None

        for r in ip.get_default_routes(family=socket.AF_INET):

            try:

                oif = r.get_attr('RTA_OIF')

            # skip routes without an output-interface attribute
            except KeyError:

                continue

            # if gateway equals index
            if oif == idx:

                try:

                    # extract the gateway ip
                    gw = r.get_attr('RTA_GATEWAY')

                # if gateway cannot be found
                except KeyError:

                    gw = None

                break

    except PermissionError as e:

        # permission denied error
        guiprint(f"> permission denied", colour=ERRORCOLOUR)

        # close socket on error
        ip.close()

        # line below
        guiprint()

        return

    except OSError as e:

        # netstatus: OS error retrieving interface data
        guiprint(f"> error retrieving network data {e}", colour=ERRORCOLOUR)

        # close socket on error
        ip.close()

        # line below
        guiprint()

        return

    except Exception as e:

        # netstatus error
        guiprint(f"> error checking network status {e}", colour=ERRORCOLOUR)

        # close socket on error
        ip.close()

        # line below
        guiprint()

        return

    # close the netlink socket
    ip.close()

    # print interface
    guiprint(f"interface    {iface}", colour=TEXTCOLOUR)

    # print mac address
    guiprint(f"mac          {mac}", colour=TEXTCOLOUR)

    # print ip address and gateway
    if addr:

        guiprint(f"ip           {addr}/{prefix}", colour=TEXTCOLOUR)

    if gw:

        guiprint(f"gateway      {gw}", colour=TEXTCOLOUR)

    # line below
    guiprint()


def ping(args=None):

    # if no arguments given
    if not args:

        guiprint("> enter host after the ping directive", colour=TEXTCOLOUR)

        return

    # define host
    host = args[0]

    try:

        # line above
        guiprint()

        # run ping and capture output
        res = subprocess.run(
            [sys.executable, "/the one/build/ping/ping.py", host],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        try:

            # decode and show stdout (normal text)
            if res.stdout:

                out = res.stdout.decode('utf-8', errors='replace')

                for line in out.splitlines():

                    guiprint(line, colour=TEXTCOLOUR)

        except Exception as e:

            # stdout decode error
            guiprint(f'> error decoding output {e}', colour=ERRORCOLOUR)

        try:

            # decode and show stderr (errors)
            if res.stderr:

                err = res.stderr.decode('utf-8', errors='replace')

                for line in err.splitlines():

                    guiprint(f'> {line}', colour=ERRORCOLOUR)

        except Exception as e:

            # stderr decode error
            guiprint(f'> error decoding errors {e}', colour=ERRORCOLOUR)

        # non-zero exit with no stderr still indicates failure
        if res.returncode != 0 and not res.stderr:

            guiprint('> ping failed', colour=ERRORCOLOUR)

        # line below
        guiprint()

    except FileNotFoundError:

        # script missing error
        guiprint('> ping software not found', colour=ERRORCOLOUR)

    except PermissionError:

        # permission denied error
        guiprint('> permission denied', colour=ERRORCOLOUR)

    except Exception as e:

        # other errors
        guiprint(f'> error pinging {e}', colour=ERRORCOLOUR)


def receive(args=None):

    # if no arguments given
    if not args:

        guiprint("> enter host after the receive directive", colour=TEXTCOLOUR)

        return

    # define host
    host = args[0]

    try:

        # line above
        guiprint()

        # run receive and capture output
        res = subprocess.run(
            [sys.executable, "/the one/build/receive/receive.py", host],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        try:

            # decode and show stdout
            if res.stdout:

                out = res.stdout.decode('utf-8', errors='replace')

                for line in out.splitlines():

                    guiprint(line)

        except Exception as e:

            # stdout decode error
            guiprint(f'> error decoding output {e}', colour=ERRORCOLOUR)

        try:

            # decode and show stderr
            if res.stderr:

                err = res.stderr.decode('utf-8', errors='replace')

                for line in err.splitlines():

                    guiprint(f'> {line}', colour=ERRORCOLOUR)

        except Exception as e:

            # stderr decode error
            guiprint(f'> error decoding errors {e}', colour=ERRORCOLOUR)

        # non-zero exit with no stderr still indicates failure
        if res.returncode != 0 and not res.stderr:

            guiprint('> receive failed', colour=ERRORCOLOUR)

        # line below
        guiprint()

    except FileNotFoundError:

        # script missing error
        guiprint('> receive software not found', colour=ERRORCOLOUR)

    except PermissionError:

        # permission denied error
        guiprint('> permission denied', colour=ERRORCOLOUR)

    except Exception as e:

        # other errors
        guiprint(f'> error receiving {e}', colour=ERRORCOLOUR)


# rubbish directives
def rubbishrestoremutationpaths(rid=None, name=None, originalpath=None):

    try:

        records = list(rubbishapi.readindex())

    except Exception:

        return []

    matches = []

    for record in records:

        try:

            if rid is not None and str(record.get('id')) != str(rid):
                continue

            if name is not None and str(record.get('name')) != str(name):
                continue

            if originalpath is not None and os.path.abspath(str(record.get('origpath'))) != os.path.abspath(str(originalpath)):
                continue

            matches.append(record)

        except Exception:

            continue

    # Name-based restore deliberately asks the backend to resolve ambiguity.
    # No mutation occurs until the request identifies one record.
    if len(matches) != 1:
        return []

    record = matches[0]
    recordid = str(record.get('id'))
    destination = str(record.get('origpath'))
    source = os.path.join('/.rubbish', recordid, 'content')
    return [source, '/.rubbish/index.txt', creationmutationpaths(destination)]


def rubbishrecords():

    records = []
    try:
        with open(BRICKRUBBISHINDEX, 'r', encoding='utf-8',
                  errors='replace') as stream:
            for index, line in enumerate(stream):
                if index == 0:
                    continue
                fields = line.rstrip('\n').split('\t')
                if len(fields) < 7:
                    continue
                records.append({
                    'id': fields[0], 'name': fields[1],
                    'origpath': fields[2], 'isdir': fields[3],
                    'size': fields[4], 'deletedts': fields[5],
                    'user': fields[6],
                })
    except FileNotFoundError:
        return []
    return records


def listrubbish(args=None):

    if args:
        guiprint('> list rubbish does not take an argument', colour=ERRORCOLOUR)
        return 1
    try:
        records = rubbishrecords()
    except Exception as error:
        guiprint('> could not read rubbish ' + lowertext(error),
                 colour=ERRORCOLOUR)
        return 1
    rows = [[
        item.get('id', ''), item.get('name', ''),
        'tier' if item.get('isdir') == '1' else 'file',
        formatbytes(item.get('size')),
        displaytimestamp(item.get('deletedts')),
        item.get('origpath', ''),
    ] for item in records]
    guiprint()
    if rows:
        showtable(
            ['id', 'name', 'type', 'size', 'deleted', 'original location'],
            lowerrows(rows))
    else:
        guiprint('> rubbish is empty', colour=TEXTCOLOUR)
    guiprint()
    return 0


def rubbishdetails(args=None):

    if len(args or []) != 1:
        guiprint('> enter one id after the rubbish details directive',
                 colour=ERRORCOLOUR)
        return 1
    requested = str(args[0]).strip()
    try:
        matches = [item for item in rubbishrecords()
                   if str(item.get('id')) == requested]
    except Exception as error:
        guiprint('> could not read rubbish ' + lowertext(error),
                 colour=ERRORCOLOUR)
        return 1
    if not matches:
        guiprint('> rubbish item not found ' + lowertext(requested),
                 colour=ERRORCOLOUR)
        return 1
    item = matches[0]
    payload = os.path.join('/.rubbish', requested, 'content')
    rows = [
        ['id', requested],
        ['name', item.get('name', '')],
        ['type', 'tier' if item.get('isdir') == '1' else 'file'],
        ['size', formatbytes(item.get('size'))],
        ['deleted', displaytimestamp(item.get('deletedts'))],
        ['user', item.get('user', '')],
        ['original location', item.get('origpath', '')],
        ['payload available', 'yes' if os.path.lexists(payload) else 'no'],
    ]
    guiprint()
    showtable(['detail', 'value'], lowerrows(rows))
    guiprint()
    return 0


def empty(args=None):

    # check if current location is /.rubbish or inside it
    cwd = os.getcwd()

    if not cwd.startswith('/.rubbish'):

        guiprint('> not in rubbish', colour=ERRORCOLOUR)

        return

    try:

        records = list(rubbishapi.readindex())

    except Exception:

        records = []

    mutationpaths = ['/.rubbish/index.txt']

    for record in records:

        try:
            mutationpaths.append(os.path.join('/.rubbish', str(record.get('id'))))
        except Exception:
            continue

    if not allowpaths(mutationpaths):
        return

    try:

        # call rubbish empty function
        emptyrubbish()

        guiprint('> rubbish emptied', colour=TEXTCOLOUR)

    except ImportError:

        # rubbish backend missing
        guiprint('> rubbish software not found', colour=ERRORCOLOUR)

    except PermissionError:

        # permission denied emptying rubbish
        guiprint('> permission denied', colour=ERRORCOLOUR)

    except Exception as e:

        # other errors
        guiprint(f'> error emptying rubbish {e}', colour=ERRORCOLOUR)


def restore(args):

    # if no arguments given
    if not args:

        guiprint('> enter the file or tier name after the restore directive', colour=TEXTCOLOUR)

        return

    try:

        # ensure we are inside the rubbish bin
        cwd = os.path.abspath(os.getcwd())

        if not (cwd == '/.rubbish' or cwd.startswith('/.rubbish' + os.sep)):

            guiprint('> not in rubbish', colour=ERRORCOLOUR)

            return

    except Exception as e:

        # cwd resolution error
        guiprint(f'> error determining current tier {e}', colour=ERRORCOLOUR)

        return

    try:

        if len(args) >= 2 and str(args[0]).lower() == 'id':

            rid = ' '.join(args[1:]).strip()
            mutationpaths = rubbishrestoremutationpaths(rid=rid)

            if mutationpaths and not allowpaths(mutationpaths):
                return 1

            restored = rubbishapi.restorefromrubbishrid(rid)
            return 0 if restored else 1

        frompositions = [index for index, token in enumerate(args) if str(token).lower() == 'from']

        if frompositions:

            index = frompositions[-1]
            name = ' '.join(args[:index]).strip()
            originaltier = ' '.join(args[index + 1:]).strip()

            if not name or not originaltier:

                guiprint('> usage restore <name> from <original tier>', colour=TEXTCOLOUR)
                return 1

            originalpath = os.path.abspath(resolvepath(os.path.join(originaltier, name)))

            mutationpaths = rubbishrestoremutationpaths(name=name, originalpath=originalpath)

            if mutationpaths and not allowpaths(mutationpaths):
                return 1

            restored = restorefromrubbish(name, originalpath)
            return 0 if restored else 1

        # restore one unique logical name
        name = ' '.join(args)

        mutationpaths = rubbishrestoremutationpaths(name=name)

        if mutationpaths and not allowpaths(mutationpaths):
            return 1

        restored = restorefromrubbish(name)
        return 0 if restored else 1

    except PermissionError:

        # permission denied during restore
        guiprint('> permission denied', colour=ERRORCOLOUR)
        return 1

    except Exception as e:

        # other errors
        guiprint(f'> error restoring {name} {e}', colour=ERRORCOLOUR)
        return 1


# development directives
def pathsize(path):

    try:

        if os.path.isfile(path):
            return int(os.path.getsize(path))

        total = 0

        for root, dirs, files in os.walk(path):

            dirs.sort(key=str.casefold)

            for name in files:

                try:
                    total += int(os.path.getsize(os.path.join(root, name)))
                except Exception:
                    pass

        return total

    except Exception:
        return 0


def pathcounts(path):

    tiers = 0
    files = 0

    try:

        for root, dirs, names in os.walk(path):

            tiers += len(dirs)
            files += len(names)

    except Exception:
        pass

    return tiers, files


def pathhash(path):

    digest = hashlib.sha256()

    try:

        with open(path, 'rb') as stream:

            while True:

                chunk = stream.read(1024 * 1024)

                if not chunk:
                    break

                digest.update(chunk)

        return digest.hexdigest()

    except Exception:
        return None


def textfile(path):

    try:

        with open(path, 'rb') as stream:
            return b'\x00' not in stream.read(4096)

    except Exception:
        return False


def protectedpath(path):

    try:

        real = os.path.realpath(path)

        if any(real == item for item in arch.ARCH_PROTECTED_NONRECURSIVE):
            return True

        if any(real == item or real.startswith(item + os.sep) for item in arch.ARCH_PROTECTED_RECURSIVE):
            return True

    except Exception:
        return True

    return False


def showdetails(args):

    path = ' '.join([str(arg) for arg in (args or [])]).strip()

    if not path:

        guiprint('> enter a file or tier after the show details directive', colour=TEXTCOLOUR)
        return 1

    target = os.path.abspath(resolvepath(path))

    if not os.path.exists(target):

        guiprint(f'> {path} not found', colour=ERRORCOLOUR)
        return 1

    try:

        info = os.stat(target)
        linktarget = arraylinktarget(target, fileinfo=info)
        kind = 'link' if linktarget is not None else ('tier' if os.path.isdir(target) else 'file')
        rows = [
            ['type', kind],
            ['path', target],
            ['size', str(pathsize(target))],
            ['modified', displaytimestamp(info.st_mtime)],
            ['readable', 'yes' if os.access(target, os.R_OK) else 'no'],
            ['writable', 'yes' if os.access(target, os.W_OK) else 'no'],
            ['architect protected', 'yes' if protectedpath(target) else 'no'],
        ]

        if kind == 'link':
            resolved, error = resolvearraylink(target)
            rows.extend([
                ['target', linktarget],
                ['target available', 'yes' if error is None and resolved and os.path.exists(resolved) else 'no'],
            ])

        if kind == 'tier':

            tiers, files = pathcounts(target)
            rows.extend([['tiers', str(tiers)], ['files', str(files)]])

        elif kind == 'file':

            digest = pathhash(target)

            if digest:
                rows.append(['sha256', digest])

        guiprint()
        showtable(['detail', 'value'], rows)
        guiprint()
        return 0

    except PermissionError:

        guiprint('> permission denied reading details', colour=ERRORCOLOUR)
        return 1

    except Exception as e:

        guiprint(f'> error reading details {e}', colour=ERRORCOLOUR)
        return 1


def manifest(path):

    entries = {}

    try:

        for root, dirs, files in os.walk(path):

            dirs.sort(key=str.casefold)
            files.sort(key=str.casefold)

            for name in dirs:

                full = os.path.join(root, name)
                relative = os.path.relpath(full, path)
                entries[relative] = ('tier', 0, None)

            for name in files:

                full = os.path.join(root, name)
                relative = os.path.relpath(full, path)
                entries[relative] = ('file', pathsize(full), pathhash(full))

    except Exception:
        return None

    return entries


def compare(args):

    connected = catalogueconnector('compare', args, 'with')

    if not connected:
        connected = positionalpair(args, want='path')

    if not connected:

        guiprint('> enter two files or tiers, optionally separated by with', colour=TEXTCOLOUR)
        return 1

    try:
        left = followarraylink(os.path.abspath(resolvepath(connected[0])))
        right = followarraylink(os.path.abspath(resolvepath(connected[1])))
    except OSError as error:
        guiprint(f'> could not compare link: {error}', colour=ERRORCOLOUR)
        return 1

    if not os.path.exists(left) or not os.path.exists(right):

        guiprint('> both comparison paths must exist', colour=ERRORCOLOUR)
        return 1

    if os.path.isdir(left) != os.path.isdir(right):

        guiprint('> cannot compare a file with a tier', colour=ERRORCOLOUR)
        return 1

    if os.path.isfile(left):

        lefthash = pathhash(left)
        righthash = pathhash(right)

        if lefthash is not None and lefthash == righthash:

            guiprint('> files are identical', colour=TEXTCOLOUR)
            return 0

        guiprint('> files are different', colour=TEXTCOLOUR)

        if not textfile(left) or not textfile(right):
            return 1

        try:

            with open(left, 'r', encoding='utf-8', errors='replace') as stream:
                leftlines = stream.readlines()

            with open(right, 'r', encoding='utf-8', errors='replace') as stream:
                rightlines = stream.readlines()

            differences = list(difflib.unified_diff(leftlines, rightlines, fromfile=left, tofile=right, n=3))

            for line in differences[:500]:
                guiprint(line.rstrip('\n'), colour=TEXTCOLOUR)

            if len(differences) > 500:
                guiprint(f'> stopped after 500 difference lines; {len(differences) - 500} remain', colour=TEXTCOLOUR)

        except Exception as e:

            guiprint(f'> error comparing files {e}', colour=ERRORCOLOUR)

        return 1

    leftmanifest = manifest(left)
    rightmanifest = manifest(right)

    if leftmanifest is None or rightmanifest is None:

        guiprint('> error reading tiers for comparison', colour=ERRORCOLOUR)
        return 1

    rows = []

    for path in sorted(set(leftmanifest) | set(rightmanifest), key=str.casefold):

        if path not in leftmanifest:
            rows.append(['added', path])
        elif path not in rightmanifest:
            rows.append(['missing', path])
        elif leftmanifest[path] != rightmanifest[path]:
            rows.append(['changed', path])

    if not rows:

        guiprint('> tiers are identical', colour=TEXTCOLOUR)
        return 0

    showtable(['state', 'path'], rows[:500])

    if len(rows) > 500:
        guiprint(f'> stopped after 500 differences; {len(rows) - 500} remain', colour=TEXTCOLOUR)

    guiprint(f'> {len(rows)} tier differences', colour=TEXTCOLOUR)
    return 1


def replace(args):

    tokens = [str(arg) for arg in (args or [])]
    replaceall = False
    spec = directivespec('replace')
    grammar = dict(spec.get('grammar', {})) if spec else {}
    connectors = list(grammar.get('connectors', []))
    withword = str(connectors[0]) if len(connectors) > 0 else 'with'
    inword = str(connectors[1]) if len(connectors) > 1 else 'in'

    if tokens and tokens[0].lower() == 'all':

        replaceall = True
        tokens = tokens[1:]

    withpositions = [index for index, token in enumerate(tokens) if token.lower() == withword]
    inpositions = [index for index, token in enumerate(tokens) if token.lower() == inword]
    parsed = None

    def isreplacementfile(value):

        try:
            return os.path.isfile(followarraylink(resolvepath(value)))
        except Exception:
            return False

    # Fully connective form: replace <old> with <new> in <file>.
    for withindex in withpositions:

        for inindex in inpositions:

            if withindex <= 0 or inindex <= withindex + 1 or inindex >= len(tokens) - 1:
                continue

            path = ' '.join(tokens[inindex + 1:]).strip()

            if isreplacementfile(path):

                parsed = (
                    ' '.join(tokens[:withindex]),
                    ' '.join(tokens[withindex + 1:inindex]),
                    path,
                )
                break

        if parsed:
            break

    # Either connector may be omitted independently.
    if not parsed:

        for inindex in inpositions:

            if inindex < 2 or inindex >= len(tokens) - 1:
                continue

            values = tokens[:inindex]
            path = ' '.join(tokens[inindex + 1:]).strip()

            if withword in [value.lower() for value in values] or not isreplacementfile(path):
                continue

            parsed = (values[0], ' '.join(values[1:]), path)
            break

    if not parsed:

        for withindex in withpositions:

            if withindex <= 0 or withindex >= len(tokens) - 2:
                continue

            remainder = tokens[withindex + 1:]

            if inword in [value.lower() for value in remainder]:
                continue

            for pathindex in range(1, len(remainder)):

                path = ' '.join(remainder[pathindex:]).strip()

                if not isreplacementfile(path):
                    continue

                parsed = (
                    ' '.join(tokens[:withindex]),
                    ' '.join(remainder[:pathindex]),
                    path,
                )
                break

            if parsed:
                break

    # Connector-free form. Quotes retain spaces in old/new text while the
    # existing-file suffix identifies the target path.
    if not parsed and not withpositions and not inpositions:

        for pathindex in range(2, len(tokens)):

            path = ' '.join(tokens[pathindex:]).strip()

            if not isreplacementfile(path):
                continue

            parsed = (tokens[0], ' '.join(tokens[1:pathindex]), path)
            break

    if not parsed:

        guiprint('> usage replace [all] "old text" ["with"] "new text" ["in"] <file>', colour=TEXTCOLOUR)
        return 1

    old, new, path = parsed
    try:
        target = followarraylink(os.path.abspath(resolvepath(path)))
    except OSError as error:
        guiprint(f'> could not replace through link: {error}', colour=ERRORCOLOUR)
        return 1

    if not old:

        guiprint('> old text cannot be empty', colour=ERRORCOLOUR)
        return 1

    if not allowpaths([target]):
        return 1

    if not textfile(target):

        guiprint(f'> {path} is a binary file', colour=ERRORCOLOUR)
        return 1

    temporary = os.path.join(os.path.dirname(target), f'.{os.path.basename(target)}.brick-{os.getpid()}.tmp')

    try:

        with open(target, 'r', encoding='utf-8', newline='') as stream:
            content = stream.read()

        count = content.count(old)

        if count == 0:

            guiprint('> old text not found; no changes made', colour=ERRORCOLOUR)
            return 1

        if not replaceall and count != 1:

            guiprint(f'> old text occurs {count} times; use replace all or make the text more specific', colour=ERRORCOLOUR)
            return 1

        changed = content.replace(old, new) if replaceall else content.replace(old, new, 1)
        mode = os.stat(target).st_mode

        with open(temporary, 'x', encoding='utf-8', newline='') as stream:

            stream.write(changed)
            stream.flush()
            os.fsync(stream.fileno())

        os.chmod(temporary, mode)
        os.replace(temporary, target)
        guiprint(f'> replaced {count if replaceall else 1} occurrence in {path}', colour=TEXTCOLOUR)
        return 0

    except PermissionError:

        guiprint('> permission denied replacing text', colour=ERRORCOLOUR)
        return 1

    except Exception as e:

        guiprint(f'> error replacing text {e}', colour=ERRORCOLOUR)
        return 1

    finally:

        try:

            if os.path.exists(temporary):
                os.unlink(temporary)

        except Exception:
            pass


def syntaxpaths(path):

    if os.path.isfile(path):
        return [path] if path.lower().endswith('.py') else []

    found = []

    try:

        for root, dirs, files in os.walk(path):

            dirs[:] = sorted([name for name in dirs if SHOWHIDDEN or not name.startswith('.')], key=str.casefold)

            for name in sorted(files, key=str.casefold):

                if name.lower().endswith('.py') and (SHOWHIDDEN or not name.startswith('.')):
                    found.append(os.path.join(root, name))

    except Exception:
        return []


def directivespec(name):

    requested = str(name or '').casefold()

    for spec in DIRECTIVESPECS:

        names = [spec.get('name', '')] + list(spec.get('aliases', []))

        if requested in [str(value).casefold() for value in names]:
            return spec

    return None

    return found


def checksyntax(args):

    path = ' '.join([str(arg) for arg in (args or [])]).strip()

    if not path:

        guiprint('> enter a python file or tier after the check syntax directive', colour=TEXTCOLOUR)
        return 1

    try:
        target = followarraylink(os.path.abspath(resolvepath(path)))
    except OSError as error:
        guiprint(f'> could not check link: {error}', colour=ERRORCOLOUR)
        return 1

    if not os.path.exists(target):

        guiprint(f'> {path} not found', colour=ERRORCOLOUR)
        return 1

    paths = syntaxpaths(target)

    if not paths:

        guiprint('> no python files found', colour=ERRORCOLOUR)
        return 1

    failures = 0

    for sourcepath in paths:

        try:

            with open(sourcepath, 'r', encoding='utf-8') as stream:
                source = stream.read()

            compile(source, sourcepath, 'exec')

        except SyntaxError as e:

            failures += 1
            guiprint(f'> {sourcepath}:{e.lineno}:{e.offset} {e.msg}', colour=ERRORCOLOUR)

        except Exception as e:

            failures += 1
            guiprint(f'> {sourcepath} {e}', colour=ERRORCOLOUR)

    if failures:

        guiprint(f'> syntax failed in {failures} of {len(paths)} python files', colour=ERRORCOLOUR)
        return 1

    guiprint(f'> syntax passed in {len(paths)} python files', colour=TEXTCOLOUR)
    return 0


def driverstate():

    try:
        with open(BRICKDRIVERSTATE, 'r', encoding='utf-8',
                  errors='replace') as stream:
            value = json.load(stream)
        return value if isinstance(value, dict) else {}
    except OSError:
        return {}


def driverversion(name):

    module = str(name or '').strip().replace('-', '_')
    try:
        with open(os.path.join(BRICKDRIVEMODULESTATE, module, 'version'),
                  'r', encoding='utf-8', errors='replace') as stream:
            return stream.read(256).strip()
    except OSError:
        return ''


def driverdevices(name, state=None):

    name = str(name or '').strip().replace('-', '_')
    devices = []
    roots = (
        '/the one/drivers/state/bus/pci/drivers',
        '/the one/driver-information-state/bus/pci/drivers',
    )
    for root in roots:
        path = os.path.join(root, name)
        try:
            for entry in os.listdir(path):
                if re.fullmatch(
                        r'[0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-7]',
                        entry) and entry not in devices:
                    devices.append(entry)
        except OSError:
            continue
    if name.startswith('nvidia'):
        for item in (state or {}).get('nvidia_devices', []):
            if not isinstance(item, dict):
                continue
            value = str(item.get('bdf') or item.get('device') or '').strip()
            if value and value not in devices:
                devices.append(value)
    return sorted(devices, key=str.casefold)


def listsystemdrivers(args=None):

    if args:
        guiprint('> list system drivers does not take an argument',
                 colour=ERRORCOLOUR)
        return 1
    state = driverstate()
    loaded = {str(value) for value in state.get('loaded', [])}
    skipped = state.get('skipped', {})
    failed = state.get('failed', {})
    if not isinstance(skipped, dict):
        skipped = {}
    if not isinstance(failed, dict):
        failed = {}
    names = sorted(loaded | set(skipped) | set(failed), key=str.casefold)
    records = []
    for name in names:
        condition = 'failed' if name in failed else 'skipped' if name in skipped else 'loaded'
        detail = failed.get(name) or skipped.get(name) or ''
        records.append([
            name, driverversion(name) or 'kernel', condition,
            str(len(driverdevices(name, state))), detail,
        ])
    guiprint()
    if records:
        showtable(
            ['driver', 'version', 'state', 'devices', 'detail'],
            lowerrows(records))
    else:
        guiprint('> no driver state is available', colour=ERRORCOLOUR)
        guiprint()
        return 1
    guiprint()
    return 0


def systemdriverdetails(args=None):

    requested = ' '.join(str(value) for value in (args or [])).strip()
    if not requested:
        guiprint('> enter a driver after the system driver details directive',
                 colour=ERRORCOLOUR)
        return 1
    state = driverstate()
    loaded = {str(value) for value in state.get('loaded', [])}
    skipped = state.get('skipped', {})
    failed = state.get('failed', {})
    parameters = state.get('module_parameters', {})
    if not isinstance(skipped, dict):
        skipped = {}
    if not isinstance(failed, dict):
        failed = {}
    if not isinstance(parameters, dict):
        parameters = {}
    names = loaded | set(skipped) | set(failed)
    exact = [name for name in names if name.casefold() == requested.casefold()]
    matches = exact or [name for name in names
                        if requested.casefold() in name.casefold()]
    if not matches:
        guiprint('> system driver not found ' + lowertext(requested),
                 colour=ERRORCOLOUR)
        return 1
    if len(matches) > 1:
        guiprint('> more than one system driver matches ' + lowertext(requested),
                 colour=ERRORCOLOUR)
        showtable(['driver'], lowerrows([[name] for name in sorted(matches)]))
        return 1
    name = matches[0]
    condition = 'failed' if name in failed else 'skipped' if name in skipped else 'loaded'
    devices = driverdevices(name, state)
    options = parameters.get(name, {})
    if isinstance(options, dict):
        optiontext = ', '.join(
            '{}={}'.format(key, value) for key, value in sorted(options.items()))
    else:
        optiontext = ''
    records = [
        ['driver', name],
        ['version', driverversion(name) or 'kernel'],
        ['state', condition],
        ['devices', ', '.join(devices) if devices else 'none recorded'],
        ['parameters', optiontext or 'none'],
        ['failure', failed.get(name) or 'none'],
        ['skip reason', skipped.get(name) or 'none'],
    ]
    guiprint()
    showtable(['detail', 'value'], lowerrows(records))
    guiprint()
    return 0


def checksystem(args=None):

    rows = []
    failures = 0
    paths = [
        '/the one/build',
        '/the one/settings',
        '/the one/logs',
        '/the one/settings/t1osversion.txt',
        sys.executable,
    ]

    sockets = [
        OPERATIONSSOCKET,
        WINDOWSOCKPATH,
        '/.ephemeral/inputserver/accept.sock',
        '/.ephemeral/audio/accept.sock',
        '/.ephemeral/exchange.sock',
    ]

    for path in paths:

        ok = os.path.exists(path)
        rows.append(['path', 'ok' if ok else 'missing', path])

        if not ok:
            failures += 1

    for path in sockets:

        ok = os.path.exists(path)
        rows.append(['service', 'ok' if ok else 'missing', path])

        if not ok:
            failures += 1

    operations, _ = operationdata()
    rows.append(['operations', 'ok' if operations else 'empty', f'{len(operations)} registered'])

    try:

        disk = os.statvfs('/')
        free = int(disk.f_bavail) * int(disk.f_frsize)
        rows.append(['storage', 'ok', f'{free} bytes free'])

    except Exception as e:

        rows.append(['storage', 'error', str(e)])
        failures += 1

    rows.append(['role', 'ok', str(arch.loadrole())])
    guiprint()
    showtable(['component', 'state', 'detail'], rows)
    guiprint()

    if failures:

        guiprint(f'> system check found {failures} problems', colour=ERRORCOLOUR)
        return 1

    guiprint('> system check passed', colour=TEXTCOLOUR)
    return 0


def test(args):

    target = ' '.join([str(arg) for arg in (args or [])]).strip().casefold()
    tests = {
        'brick': ['/the one/build/brick/brick.py', 'graphics-diagnostic'],
        'directives': ['/the one/build/brick/brick.py', 'directive-diagnostic'],
        'parsing': ['/the one/build/brick/brick.py', 'directive-diagnostic', 'parsing'],
        'files': ['/the one/build/brick/brick.py', 'directive-diagnostic', 'files'],
        'rubbish': ['/the one/build/brick/brick.py', 'directive-diagnostic', 'rubbish'],
        'search': ['/the one/build/brick/brick.py', 'directive-diagnostic', 'search'],
        'operations': ['/the one/build/brick/brick.py', 'directive-diagnostic', 'operations'],
        'development': ['/the one/build/brick/brick.py', 'directive-diagnostic', 'development'],
        'dogfood': ['/the one/build/brick/brick.py', 'directive-diagnostic', 'dogfood'],
        'network': ['/the one/build/brick/brick.py', 'directive-diagnostic', 'network'],
        'image': ['/the one/build/image/image.py', 'diagnostic'],
        'write': ['/the one/build/write/write.py', 'graphics-diagnostic'],
        'write performance': ['/the one/build/write/write.py', 'performance-diagnostic'],
        'array': ['/the one/build/array/array.py', 'graphics-diagnostic'],
        'operations centre': ['/the one/build/operations/operationscentre.py', 'graphics-diagnostic'],
        'expanse': ['/the one/build/expanse/expanse.py', 'graphics-diagnostic'],
        'startup': ['/the one/build/startup/startup.py', 'graphics-diagnostic'],
        'lock screen': ['/the one/build/lock screen/lock screen.py', 'graphics-diagnostic'],
        'window server': ['/the one/build/windows/windowserver.py', 'diagnostic'],
        'operation server': ['/the one/build/operations/operationsserver.py', 'diagnostic'],
    }

    command = tests.get(target)

    if not command:

        guiprint(f"> test one of {', '.join(sorted(tests))}", colour=TEXTCOLOUR)
        return 1

    try:

        guiprint(f'> testing {target}; press ctrl-s to stop', colour=TEXTCOLOUR)
        process = subprocess.Popen([sys.executable, '-B', *command], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        code = streamproc(process, stoppable=True)

        if code == 0:
            guiprint(f'> {target} test passed', colour=TEXTCOLOUR)
        else:
            guiprint(f'> {target} test failed', colour=ERRORCOLOUR)

        return code

    except Exception as e:

        guiprint(f'> error testing {target} {e}', colour=ERRORCOLOUR)
        return 1


# Python directives
def pythoncall(operation, arguments=None, timeout=10.0, quiet=False,
               descriptor=None):

    try:

        result = pythonrequest(
            operation,
            arguments=dict(arguments or {}),
            timeout=float(timeout),
            descriptor=descriptor,
        )

        if not quiet and result.get('message'):
            guiprint(f"> {result.get('message')}", colour=TEXTCOLOUR)

        result.setdefault('items', [])
        result.setdefault('data', {})
        return result

    except PythonManagerError as error:

        guiprint(f'> {error}', colour=ERRORCOLOUR)
        response = dict(getattr(error, 'response', {}) or {})
        data = response.get('data', {})

        if isinstance(data, dict):

            for problem in data.get('problems', [])[:20]:
                guiprint(f'> {problem}', colour=ERRORCOLOUR)

        return {
            'ok': False,
            'code': str(getattr(error, 'code', 'failed')),
            'message': str(error),
            'items': [],
            'data': data if isinstance(data, dict) else {},
        }


def pythonmutationcall(operation, arguments=None, timeout=900.0,
                       descriptor=None):
    result = pythoncall(
        operation, arguments, timeout=timeout, descriptor=descriptor)
    writebrickvmteststatus(
        'python-complete', python_operation=str(operation),
        python_ok=bool(result.get('ok')),
        python_code=str(result.get('code') or ''),
        python_error=str(result.get('message') or ''),
        python_data=dict(result.get('data') or {}))
    return result


def pythonstatus(args=None):

    if args:
        guiprint('> python status takes no arguments', colour=ERRORCOLOUR)
        return {'ok': False, 'code': 'invalid_arguments', 'message': 'python status takes no arguments'}

    result = pythoncall('status', quiet=True)

    if not result.get('ok'):
        return result

    data = result.get('data', {})
    core = data.get('core', {})
    transaction = data.get('transaction', {})
    rows = [
        ['release', str(core.get('release') or 'unrecorded')],
        ['version', str(core.get('version') or 'unknown')],
        ['abi', str(core.get('abi') or 'unknown')],
        ['authorization', str(data.get('authorization') or 'trusted application')],
        ['health', str(data.get('health') or 'unknown')],
        ['transaction', str(data.get('generation') or 'base')],
        ['system modules', str(data.get('system_modules', 0))],
        ['added modules', str(data.get('managed_modules', 0))],
    ]

    if transaction.get('running'):
        rows.append(['change', str(transaction.get('phase') or transaction.get('operation') or 'running')])

    guiprint()
    showtable(['python', 'value'], rows)
    guiprint()
    result['items'] = rows
    return result


def listpythonmodules(args=None):

    if args:
        guiprint('> list python modules takes no arguments', colour=ERRORCOLOUR)
        return {'ok': False, 'code': 'invalid_arguments', 'message': 'list python modules takes no arguments'}

    result = pythoncall('list_modules', quiet=True)

    if not result.get('ok'):
        return result

    modules = result.get('data', {}).get('modules', [])
    rows = []

    for item in modules:
        state = 'system' if item.get('system') else 'requested' if item.get('requested') else 'dependency'

        if item.get('pinned'):
            state += ', pinned'

        rows.append([
            str(item.get('display_name') or item.get('name') or ''),
            str(item.get('version') or ''),
            state,
            ', '.join(item.get('imports', [])),
        ])

    guiprint()

    if rows:
        showtable(['module', 'version', 'state', 'imports'], rows)
    else:
        guiprint('> no python modules are installed', colour=TEXTCOLOUR)

    guiprint()
    result['items'] = modules
    return result


def showpythonmodule(args=None):

    if len(args or []) != 1:
        guiprint('> enter one module name', colour=ERRORCOLOUR)
        return {'ok': False, 'code': 'invalid_arguments', 'message': 'enter one module name'}

    result = pythoncall('show_module', {'name': args[0]}, quiet=True)

    if not result.get('ok'):
        return result

    for item in result.get('data', {}).get('modules', []):
        rows = [
            ['name', str(item.get('display_name') or item.get('name') or '')],
            ['version', str(item.get('version') or '')],
            ['state', 'system' if item.get('system') else 'requested' if item.get('requested') else 'dependency'],
            ['pinned', 'yes' if item.get('pinned') else 'no'],
            ['imports', ', '.join(item.get('imports', [])) or 'none recorded'],
            ['summary', str(item.get('summary') or 'none recorded')],
            ['license', str(item.get('license') or 'none recorded')],
        ]

        if item.get('requires'):
            rows.append(['requires', '; '.join(item.get('requires', []))])

        guiprint()
        showtable(['detail', 'value'], rows)
        guiprint()

    return result


def findpythonmodule(args=None):

    if len(args or []) != 1:
        guiprint('> enter one module name', colour=ERRORCOLOUR)
        return {'ok': False, 'code': 'invalid_arguments', 'message': 'enter one module name'}

    result = pythoncall('find_module', {'name': args[0]}, timeout=30.0, quiet=True)

    if not result.get('ok'):
        return result

    data = result.get('data', {})
    versions = list(data.get('versions', []))
    rows = [
        ['name', str(data.get('name') or '')],
        ['latest', str(data.get('latest') or 'no compatible wheel')],
        ['compatible wheels', str(data.get('compatible_wheels', 0))],
        ['versions', ', '.join(versions[:12]) or 'none'],
    ]
    guiprint()
    showtable(['result', 'value'], rows)
    guiprint()
    result['items'] = versions
    return result


def listpythonupdates(args=None):

    if args:
        guiprint('> list python updates takes no arguments', colour=ERRORCOLOUR)
        return {'ok': False, 'code': 'invalid_arguments', 'message': 'list python updates takes no arguments'}

    result = pythoncall('list_updates', timeout=120.0, quiet=True)

    if not result.get('ok'):
        return result

    updates = result.get('data', {}).get('updates', [])
    rows = [[
        str(item.get('name') or ''),
        str(item.get('installed') or ''),
        str(item.get('latest') or 'unavailable'),
        'pinned' if item.get('pinned') else 'update available' if item.get('available') else 'current',
    ] for item in updates]
    guiprint()

    if rows:
        showtable(['module', 'installed', 'latest', 'state'], rows)
    else:
        guiprint('> no added python modules are installed', colour=TEXTCOLOUR)

    guiprint()
    result['items'] = updates
    return result


def checkpython(args=None):

    if args:
        guiprint('> check python takes no arguments', colour=ERRORCOLOUR)
        return {'ok': False, 'code': 'invalid_arguments', 'message': 'check python takes no arguments'}

    status = pythoncall('status', quiet=True)

    if not status.get('ok'):
        return status

    result = pythoncall('check_modules', timeout=120.0, quiet=True)

    if result.get('ok'):
        data = result.get('data', {})
        guiprint(
            f"> python and {data.get('files', 0)} managed module files are healthy",
            colour=TEXTCOLOUR,
        )

    return result


def pythonhistory(args=None):

    if args:
        guiprint('> python history takes no arguments', colour=ERRORCOLOUR)
        return {'ok': False, 'code': 'invalid_arguments', 'message': 'python history takes no arguments'}

    result = pythoncall('history', {'limit': 50}, quiet=True)

    if not result.get('ok'):
        return result

    history = result.get('data', {}).get('history', [])
    rows = []

    for item in history:
        when = time.strftime('%d-%m-%Y %H:%M:%S', time.localtime(float(item.get('time', 0))))
        rows.append([
            when,
            str(item.get('operation') or ''),
            str(item.get('result') or ''),
            str(item.get('transaction') or item.get('code') or ''),
        ])

    guiprint()

    if rows:
        showtable(['time', 'change', 'result', 'transaction'], rows)
    else:
        guiprint('> python has no module history', colour=TEXTCOLOUR)

    guiprint()
    result['items'] = history
    return result


def installpythonmodule(args=None):

    values = list(args or [])

    if len(values) == 1:
        arguments = {'name': values[0]}
    elif len(values) == 3 and str(values[1]).casefold() == 'version':
        arguments = {'name': values[0], 'version': values[2]}
    else:
        guiprint('> use install python module <name> [version <version>]', colour=ERRORCOLOUR)
        return {'ok': False, 'code': 'invalid_arguments', 'message': 'invalid install syntax'}

    guiprint('> resolving and checking the python module change', colour=TEXTCOLOUR)
    return pythonmutationcall('install_module', arguments, timeout=900.0)


def openpythoninput(value, suffix, maximum, label):
    try:
        path = followarraylink(os.path.abspath(resolvepath(value)))
        if not path.lower().endswith(suffix):
            raise ValueError(f'choose a {suffix} file')
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, 'O_CLOEXEC', 0)
            | getattr(os, 'O_NOFOLLOW', 0),
        )
        status = os.fstat(descriptor)
        if (not stat.S_ISREG(status.st_mode) or status.st_nlink != 1
                or status.st_size <= 0 or status.st_size > maximum):
            raise ValueError(f'{label} is not a safe regular file')
        digest = hashlib.sha256()
        while True:
            block = os.read(descriptor, 1024 * 1024)
            if not block:
                break
            digest.update(block)
        os.lseek(descriptor, 0, os.SEEK_SET)
        return descriptor, path, status.st_size, digest.hexdigest()
    except Exception:
        if 'descriptor' in locals():
            os.close(descriptor)
        raise


def installpythonwheel(args=None):
    value = ' '.join(str(item) for item in (args or [])).strip()
    if not value:
        guiprint('> use install python wheel <file>', colour=ERRORCOLOUR)
        return {'ok': False, 'code': 'invalid_arguments',
                'message': 'enter a wheel file'}
    descriptor = None
    try:
        descriptor, path, size, digest = openpythoninput(
            value, '.whl', 512 * 1024 * 1024, 'python wheel')
        arguments = {
            'filename': os.path.basename(path),
            'size': size,
            'sha256': digest,
        }
        guiprint('> checking and installing a local python wheel',
                 colour=TEXTCOLOUR)
        return pythonmutationcall(
            'install_wheel', arguments, timeout=900.0,
            descriptor=descriptor)
    except Exception as error:
        guiprint(f'> could not open python wheel {error}', colour=ERRORCOLOUR)
        return {'ok': False, 'code': 'invalid_file',
                'message': str(error), 'items': [], 'data': {}}
    finally:
        if descriptor is not None:
            os.close(descriptor)


def pythonmodulechange(operation, usage, args=None):

    if len(args or []) != 1:
        guiprint(f'> use {usage}', colour=ERRORCOLOUR)
        return {'ok': False, 'code': 'invalid_arguments', 'message': 'enter one module name'}

    guiprint('> preparing the python module change', colour=TEXTCOLOUR)
    return pythonmutationcall(operation, {'name': args[0]}, timeout=900.0)


def removepythonmodule(args=None):
    return pythonmodulechange('remove_module', 'remove python module <name>', args)


def updatepythonmodule(args=None):
    return pythonmodulechange('update_module', 'update python module <name>', args)


def pinpythonmodule(args=None):
    return pythonmodulechange('pin_module', 'pin python module <name>', args)


def unpinpythonmodule(args=None):
    return pythonmodulechange('unpin_module', 'unpin python module <name>', args)


def pythonchange(operation, usage, args=None, timeout=900.0):

    if args:
        guiprint(f'> {usage} takes no arguments', colour=ERRORCOLOUR)
        return {'ok': False, 'code': 'invalid_arguments', 'message': usage + ' takes no arguments'}

    return pythonmutationcall(operation, timeout=timeout)


def updatepythonmodules(args=None):
    return pythonchange('update_modules', 'update python modules', args)


def repairpythonmodules(args=None):
    return pythonchange('repair_modules', 'repair python modules', args)


def restorepythonmodules(args=None):
    return pythonchange('restore_modules', 'restore python modules', args)


def pythonlockchange(operation, usage, args=None, timeout=900.0):

    value = ' '.join(str(item) for item in (args or [])).strip()

    if not value:
        guiprint(f'> use {usage}', colour=ERRORCOLOUR)
        return {'ok': False, 'code': 'invalid_arguments', 'message': 'enter a lock file'}

    try:
        path = followarraylink(os.path.abspath(resolvepath(value)))
    except Exception as error:
        guiprint(f'> could not resolve lock file {error}', colour=ERRORCOLOUR)
        return {'ok': False, 'code': 'invalid_path', 'message': str(error)}

    return pythoncall(operation, {'path': path}, timeout=timeout)


def writepythonlock(path, content):
    target = followarraylink(os.path.abspath(resolvepath(path)))
    if not allowpaths([target]):
        raise PermissionError('permission denied')
    parent = os.path.dirname(target)
    name = os.path.basename(target)
    if not name or not os.path.isdir(parent):
        raise FileNotFoundError('destination tier does not exist')
    flags = os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0)
    parent_descriptor = os.open(
        parent, flags | getattr(os, 'O_NOFOLLOW', 0))
    temporary = f'.{name}.brick-{os.getpid()}-{time.time_ns()}.tmp'
    output = None
    try:
        try:
            current = os.stat(
                name, dir_fd=parent_descriptor, follow_symlinks=False)
            if not stat.S_ISREG(current.st_mode) or current.st_nlink != 1:
                raise OSError('destination is not a safe regular file')
            mode = stat.S_IMODE(current.st_mode)
        except FileNotFoundError:
            mode = 0o644
        output = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL
            | getattr(os, 'O_NOFOLLOW', 0),
            mode,
            dir_fd=parent_descriptor,
        )
        offset = 0
        while offset < len(content):
            written = os.write(output, content[offset:])
            if written <= 0:
                raise OSError('short write')
            offset += written
        os.fsync(output)
        os.close(output)
        output = None
        os.replace(
            temporary, name,
            src_dir_fd=parent_descriptor,
            dst_dir_fd=parent_descriptor,
        )
        os.fsync(parent_descriptor)
    finally:
        if output is not None:
            os.close(output)
        try:
            os.unlink(temporary, dir_fd=parent_descriptor)
        except FileNotFoundError:
            pass
        os.close(parent_descriptor)
    return target


def exportpythonlock(args=None):
    value = ' '.join(str(item) for item in (args or [])).strip()
    if not value:
        guiprint('> use export python lock <file>', colour=ERRORCOLOUR)
        return {'ok': False, 'code': 'invalid_arguments',
                'message': 'enter a lock file'}
    result = pythoncall('export_lock', timeout=30.0, quiet=True)
    if not result.get('ok'):
        return result
    try:
        data = dict(result.get('data') or {})
        content = base64.b64decode(str(data.get('content') or ''), validate=True)
        if (not content or len(content) > 1024 * 1024
                or hashlib.sha256(content).hexdigest()
                != str(data.get('sha256') or '').lower()):
            raise ValueError('manager returned an invalid python lock')
        target = writepythonlock(value, content)
        result['data'] = {
            'path': target,
            'sha256': hashlib.sha256(content).hexdigest(),
            'size': len(content),
        }
        result['message'] = 'python lock exported.'
        guiprint('> python lock exported', colour=TEXTCOLOUR)
        return result
    except Exception as error:
        guiprint(f'> could not export python lock {error}', colour=ERRORCOLOUR)
        return {'ok': False, 'code': 'write_failed',
                'message': str(error), 'items': [], 'data': {}}


def applypythonlock(args=None):
    value = ' '.join(str(item) for item in (args or [])).strip()
    if not value:
        guiprint('> use apply python lock <file>', colour=ERRORCOLOUR)
        return {'ok': False, 'code': 'invalid_arguments',
                'message': 'enter a lock file'}
    descriptor = None
    try:
        descriptor, _, size, digest = openpythoninput(
            value, '.toml', 1024 * 1024, 'python lock')
        arguments = {'size': size, 'sha256': digest}
        guiprint('> checking and applying the python lock', colour=TEXTCOLOUR)
        return pythonmutationcall(
            'apply_lock', arguments, timeout=900.0,
            descriptor=descriptor)
    except Exception as error:
        guiprint(f'> could not open python lock {error}', colour=ERRORCOLOUR)
        return {'ok': False, 'code': 'invalid_file',
                'message': str(error), 'items': [], 'data': {}}
    finally:
        if descriptor is not None:
            os.close(descriptor)


# directives
def makegrammar(source=None, connectors=None, terms=None, completion=None, highlight_type=None, highlight=None):

    return {
        'source': source,
        'connectors': list(connectors or []),
        'terms': list(terms or []),
        'completion': completion,
        'highlight_type': highlight_type,
        'highlight': highlight,
    }


def makespec(name, aliases, description, usages, handler, restricted=False, headless=True, grammar=None, category=None, architect=False):

    parsed = dict(grammar or {})

    if category not in DIRECTIVECATEGORIES:
        raise ValueError(f'invalid directive category for {name}')

    return {
        'name': str(name),
        'category': str(category),
        'aliases': list(aliases or []),
        'description': str(description),
        'usages': list(usages or []),
        'handler': handler,
        'restricted': bool(restricted),
        'architect': bool(architect),
        'headless': bool(headless),
        'grammar': parsed,
    }


DIRECTIVECATEGORIES = [
    'tiers',
    'files',
    'inspection',
    'development',
    'media',
    'operations',
    'networking',
    'python',
    'rubbish',
    'system',
]


DIRECTIVESPECS = [
    makespec('tier', ['t'], 'display the current tier', ['tier'], tier, category='tiers'),
    makespec('change tier', ['ct'], 'change to another tier', ['change tier <tier>', 'change tier back'], changetier, grammar=makegrammar('dir', terms=['back'], completion='path', highlight_type='dir', highlight='single'), category='tiers'),
    makespec('open tier', ['ot'], 'open one tier', ['open tier <tier>'], opentier, grammar=makegrammar('dir', completion='path', highlight_type='dir', highlight='single'), category='tiers'),
    makespec('open tiers', ['ots'], 'open tiers recursively', ['open tiers <tier>', 'open tiers <tier> up to <count> levels'], opentiers, grammar=makegrammar('dir', terms=['up to levels'], completion='path', highlight_type='dir', highlight='single'), category='tiers'),
    makespec('expose tier', ['et'], 'open one tier including hidden items', ['expose tier <tier>'], exposetier, grammar=makegrammar('dir', completion='path', highlight_type='dir', highlight='single'), category='tiers'),
    makespec('expose tiers', ['ets'], 'open tiers recursively including hidden items', ['expose tiers <tier>', 'expose tiers <tier> up to <count> levels'], exposetiers, grammar=makegrammar('dir', terms=['up to levels'], completion='path', highlight_type='dir', highlight='single'), category='tiers'),
    makespec('create tier', ['crt'], 'create a tier', ['create tier <name>'], createtier, True, grammar=makegrammar('dir', completion='path'), category='tiers'),
    makespec('delete tier', ['dt'], 'put a tier in the rubbish', ['delete tier <tier or wildcard>'], deletetier, True, grammar=makegrammar('dir', completion='path', highlight_type='dir', highlight='single'), category='tiers'),
    makespec('destroy tier', ['dst'], 'destroy a tier permanently', ['destroy tier <tier or wildcard>'], destroytier, True, grammar=makegrammar('dir', completion='path', highlight_type='dir', highlight='single'), category='tiers'),
    makespec('rename tier', ['rt'], 'rename a tier', ['rename tier <old> <new>', 'rename tier <old> to <new>'], renametier, True, grammar=makegrammar('dir', connectors=['to'], highlight_type='dir', highlight='split'), category='tiers'),
    makespec('move tier', ['mvt'], 'move a tier', ['move tier <source> <destination>', 'move tier <source> to <destination>'], movetier, True, grammar=makegrammar('dir', connectors=['to'], highlight_type='dir', highlight='pair'), category='tiers'),
    makespec('copy tier', ['cpt'], 'copy a tier', ['copy tier <source>', 'copy tier <source> <destination>', 'copy tier <source> to <destination>'], copytier, grammar=makegrammar('dir', connectors=['to'], highlight_type='dir', highlight='pair'), category='tiers'),
    makespec('create', ['cr'], 'create a file', ['create <file>'], create, True, grammar=makegrammar('file', completion='path'), category='files'),
    makespec('delete', ['de'], 'put a file in the rubbish', ['delete <file or wildcard>'], delete, True, grammar=makegrammar('file', completion='path', highlight_type='file', highlight='single'), category='files'),
    makespec('destroy', ['ds'], 'destroy a file permanently', ['destroy <file or wildcard>'], destroy, True, grammar=makegrammar('file', completion='path', highlight_type='file', highlight='single'), category='files'),
    makespec('rename', ['re'], 'rename a file', ['rename <old> <new>', 'rename <old> to <new>'], rename, True, grammar=makegrammar('file', connectors=['to'], highlight_type='file', highlight='split'), category='files'),
    makespec('move', ['mo'], 'move a file', ['move <source> <destination>', 'move <source> to <destination>'], move, True, grammar=makegrammar('file', connectors=['to'], highlight_type='file', highlight='pair'), category='files'),
    makespec('copy', ['co'], 'copy a file', ['copy <source>', 'copy <source> <destination>', 'copy <source> to <destination>'], copy, grammar=makegrammar('file', connectors=['to'], highlight_type='file', highlight='pair'), category='files'),
    makespec('write', [], 'write a text file', ['write <file>'], write, headless=False, grammar=makegrammar('file', completion='path', highlight_type='file', highlight='single'), category='files'),
    makespec('write in', ['wi'], 'append text to a file', ['write in "text" <file>'], writein, grammar=makegrammar('file', highlight_type='file', highlight='writein'), category='files'),
    makespec('read', [], 'read a text file', ['read <file>', 'read <file> from <first> to <last>', 'read last <count> from <file>', 'read <file> with numbers'], read, grammar=makegrammar('file', terms=['last', 'from', 'to', 'with numbers'], completion='path', highlight_type='file', highlight='single'), category='files'),
    makespec('search', ['s'], 'search names or text', ['search <name> [scope tiers]', 'search <text> in <file or tier>', 'search <names|files|tiers> <name> in <tier>', 'search <exact|all> <terms> in <file or tier>'], search, grammar=makegrammar('path', terms=['names', 'files', 'tiers', 'exact', 'all', 'in']), category='inspection'),
    makespec('show details', [], 'show file or tier details', ['show details <file or tier>'], showdetails, grammar=makegrammar('path', completion='path'), category='inspection'),
    makespec('compare', [], 'compare two files or tiers', ['compare <path> <path>', 'compare <path> with <path>'], compare, grammar=makegrammar('path', connectors=['with'], terms=['with']), category='inspection'),
    makespec('replace', [], 'replace exact text in a file', ['replace "old" "new" <file>', 'replace "old" with "new" in <file>', 'replace all "old" "new" <file>', 'replace all "old" with "new" in <file>'], replace, grammar=makegrammar('file', connectors=['with', 'in'], terms=['all', 'with', 'in']), category='files'),
    makespec('check syntax', [], 'check python syntax without running code', ['check syntax <file or tier>'], checksyntax, grammar=makegrammar('path', completion='path'), category='development'),
    makespec('check system', [], 'check critical t1os state', ['check system'], checksystem, category='system'),
    makespec('python status', ['ps'], 'show managed python health', ['python status'], pythonstatus, category='python'),
    makespec('check python', ['cp', 'cpm'], 'check python and added modules', ['check python'], checkpython, category='python'),
    makespec('python history', ['ph'], 'show python module changes', ['python history'], pythonhistory, category='python'),
    makespec('list python modules', ['lpm'], 'list installed python modules', ['list python modules'], listpythonmodules, category='python'),
    makespec('show python module', ['spm'], 'show an installed python module', ['show python module <name>'], showpythonmodule, category='python'),
    makespec('find python module', ['fpm'], 'find compatible module versions', ['find python module <name>'], findpythonmodule, category='python'),
    makespec('list python updates', ['lpu'], 'list available module updates', ['list python updates'], listpythonupdates, category='python'),
    makespec('install python module', ['ipm'], 'install a python module', ['install python module <name>', 'install python module <name> version <version>'], installpythonmodule, True, grammar=makegrammar(terms=['version']), category='python'),
    makespec('install python wheel', ['ipw'], 'install a local python wheel', ['install python wheel <file>'], installpythonwheel, True, grammar=makegrammar('file', completion='path', highlight_type='file', highlight='single'), category='python'),
    makespec('remove python module', ['rpm'], 'remove a python module', ['remove python module <name>'], removepythonmodule, True, category='python'),
    makespec('update python module', ['upm'], 'update one python module', ['update python module <name>'], updatepythonmodule, True, category='python'),
    makespec('update python modules', ['upms'], 'update added python modules', ['update python modules'], updatepythonmodules, True, category='python'),
    makespec('pin python module', ['ppm'], 'hold a module version', ['pin python module <name>'], pinpythonmodule, True, category='python'),
    makespec('unpin python module', ['unpm'], 'allow a module to update', ['unpin python module <name>'], unpinpythonmodule, True, category='python'),
    makespec('repair python modules', ['rprm'], 'rebuild modules from their lock', ['repair python modules'], repairpythonmodules, True, category='python'),
    makespec('restore python modules', ['rspm'], 'restore the previous module set', ['restore python modules'], restorepythonmodules, True, category='python'),
    makespec('export python lock', ['epl'], 'export the exact module lock', ['export python lock <file>'], exportpythonlock, grammar=makegrammar('file', completion='path', highlight_type='file', highlight='single'), category='python'),
    makespec('apply python lock', ['apl'], 'apply an exact module lock', ['apply python lock <file>'], applypythonlock, True, grammar=makegrammar('file', completion='path', highlight_type='file', highlight='single'), category='python'),
    makespec('test', [], 'run an isolated registered diagnostic', ['test <component>'], test, grammar=makegrammar(terms=['brick', 'directives', 'parsing', 'files', 'rubbish', 'search', 'operations', 'development', 'dogfood', 'network']), category='development'),
    makespec('play', [], 'play an audio or video file', ['play <media file>'], play, headless=False, grammar=makegrammar('file', completion='path', highlight_type='file', highlight='single'), category='media'),
    makespec('view', [], 'view an image inline', ['view <image file>'], view, headless=False, grammar=makegrammar('file', completion='path', highlight_type='file', highlight='single'), category='media'),
    makespec('run', ['r'], 'run software', ['run <software> [arguments]', 'run <software> [arguments] behind'], run, grammar=makegrammar('file', terms=['behind'], highlight_type='file', highlight='single'), category='operations'),
    makespec('list software', ['lsw'], 'list broker-approved software', ['list software'], listsoftware, category='operations'),
    makespec('software details', ['sd'], 'show software details and running state', ['software details <software>'], softwaredetails, category='operations'),
    makespec('kill', ['ko'], 'kill one operation', ['kill <pid|name|%order>', 'kill <target> force'], killop, True, grammar=makegrammar(terms=['force']), category='operations'),
    makespec('list operations', ['lo'], 'list running operations', ['list operations [name|front|behind|completed]'], listops, grammar=makegrammar(terms=['front', 'behind', 'completed']), category='operations'),
    makespec('operation details', ['od'], 'show operation resource and lifecycle details', ['operation details <target>'], operationdetails, category='operations'),
    makespec('system performance', ['sp'], 'show system resource and graphics telemetry', ['system performance'], systemperformance, category='operations'),
    makespec('session operations', ['sops'], 'list operations started in this brick session', ['session operations'], sessionops, category='operations'),
    makespec('startup operations', ['suo'], 'list startup operations', ['startup operations'], startupops, category='operations'),
    makespec('add startup operation', ['aso'], 'add broker-approved software at startup', ['add startup operation <software> <front or behind>'], addstartup, True, grammar=makegrammar(terms=['front', 'behind']), category='operations'),
    makespec('remove startup operation', ['rso'], 'remove software from startup', ['remove startup operation <software>'], removestartup, True, category='operations'),
    makespec('change startup operation', ['cso'], 'change startup presentation mode', ['change startup operation <software> <front or behind>'], changestartup, True, grammar=makegrammar(terms=['front', 'behind']), category='operations'),
    makespec('read log', [], 'read an operation log', ['read log <pid|name|%order>'], readlog, category='operations'),
    makespec('follow log', [], 'follow an operation log', ['follow log <pid|name|%order>'], followlog, category='operations'),
    makespec('wait for', [], 'wait for an operation to finish', ['wait for <pid|name|%order>'], waitfor, category='operations'),
    makespec('network', [], 'display network status', ['network'], netstatus, category='networking'),
    makespec('network details', ['nd'], 'show the active connection details', ['network details'], networkdetails, category='networking'),
    makespec('list network interfaces', ['lni'], 'list available network interfaces', ['list network interfaces'], listnetworkinterfaces, category='networking'),
    makespec('use network interface', ['uni'], 'choose the preferred network interface', ['use network interface automatic', 'use network interface <interface>'], usenetworkinterface, True, grammar=makegrammar(terms=['automatic']), category='networking'),
    makespec('set network address', ['sna'], 'use automatic or manual network addressing', ['set network address automatic', 'set network address <address> <prefix> <gateway>'], setnetworkaddress, True, grammar=makegrammar(terms=['automatic']), category='networking'),
    makespec('dns status', ['dns'], 'show the dns mode and servers', ['dns status'], dnsstatus, category='networking'),
    makespec('set dns automatic', ['sda'], 'obtain dns servers automatically', ['set dns automatic'], setdnsautomatic, True, category='networking'),
    makespec('set dns servers', ['sds'], 'set one or two dns servers', ['set dns servers <primary>', 'set dns servers <primary> <secondary>'], setdnsservers, True, category='networking'),
    makespec('firewall status', ['fws'], 'show the active firewall policy', ['firewall status'], firewallstatus, category='networking'),
    makespec('set firewall', ['sfw'], 'choose the protected or open firewall policy', ['set firewall protected', 'set firewall open'], setfirewall, True, grammar=makegrammar(terms=['protected', 'open']), category='networking'),
    makespec('scan wifi', ['sw'], 'request a wi-fi network scan', ['scan wifi'], scanwifi, category='networking'),
    makespec('list wifi networks', ['lwn'], 'list the latest wi-fi scan results', ['list wifi networks'], listwifinetworks, category='networking'),
    makespec('ping', [], 'ping a host', ['ping <host>'], ping, category='networking'),
    makespec('receive', [], 'receive a site page', ['receive <page>'], receive, category='networking'),
    makespec('list drives', ['ld'], 'list t1os drives and availability', ['list drives'], listdrives, category='system'),
    makespec('drive details', ['dd'], 'show capacity and mount details for one drive', ['drive details <number>'], drivedetails, category='system'),
    makespec('list rubbish', ['lr'], 'list items in the rubbish', ['list rubbish'], listrubbish, category='rubbish'),
    makespec('rubbish details', ['rd'], 'show complete metadata for one rubbish item', ['rubbish details <id>'], rubbishdetails, category='rubbish'),
    makespec('empty', [], 'empty the rubbish', ['empty'], empty, category='rubbish'),
    makespec('restore', [], 'restore a file or tier from rubbish', ['restore <name>', 'restore <name> from <original tier>', 'restore id <id>'], restore, grammar=makegrammar('path', terms=['id', 'from'], highlight_type='file', highlight='rubbish'), category='rubbish'),
    makespec('reveal', [], 'toggle hidden item display', ['reveal'], togglehidden, category='tiers'),
    makespec('role', [], 'display the current system role', ['role'], role, category='system'),
    makespec('architect', [], 'change the system role', ['architect'], architectdir, headless=False, category='system'),
    makespec('list system drivers', ['lsd'], 'list loaded, skipped and failed drivers', ['list system drivers'], listsystemdrivers, category='system'),
    makespec('system driver details', ['sdd'], 'show state and recorded driver failure', ['system driver details <name>'], systemdriverdetails, category='system'),
    makespec('time', [], 'display the current date and time', ['time'], timedir, category='system'),
    makespec('set timezone', ['stz'], 'set the system timezone', ['set timezone <area/city>'], settimezone, True, category='system'),
    makespec('set automatic time', ['sat'], 'configure automatic clock sources', ['set automatic time <off or internet or virtualbox or both>'], setautomatictime, True, grammar=makegrammar(terms=['off', 'internet', 'virtualbox', 'both']), category='system'),
    makespec('set date and time', ['sdt'], 'set the manual atreyan date and local time', ['set date and time <dd.mm.yae> <hh.mm>'], setdateandtime, True, category='system'),
    makespec('terminal name', ['tn'], 'show the current terminal name', ['terminal name'], terminalname, category='system'),
    makespec('set terminal name', ['stn'], 'change the terminal hostname', ['set terminal name <name>'], setterminalname, True, category='system'),
    makespec('change master name', ['cmn'], 'change the master account name', ['change master name <name>'], changemastername, True, category='system'),
    makespec('change master password', ['cmp'], 'change the master account password', ['change master password'], changemasterpassword, True, category='system'),
    makespec('history', ['h'], 'show recent brick directives', ['history', 'history <count>'], historydir, category='system'),
    makespec('clear history', ['ch'], 'erase persisted brick history', ['clear history'], clearhistory, True, category='system'),
    makespec('clear', ['cl'], 'clear output', ['clear'], cleardir, category='system'),
    makespec('version', ['v'], 'show the t1os version', ['version'], version, category='system'),
    makespec('help', [], 'show directive categories', ['help', 'help <category>'], help, grammar=makegrammar(terms=DIRECTIVECATEGORIES), category='system'),
    makespec('log out', [], 'log out of t1os', ['log out'], logout, headless=False, category='system'),
    makespec('shut down', [], 'shut down the terminal', ['shut down'], shutdown, headless=False, category='system'),
    makespec('restart', [], 'restart the terminal', ['restart'], restart, headless=False, category='system'),
    makespec('exit', [], 'exit brick', ['exit'], exitdir, headless=False, category='system'),
]

DIRECTIVES = {}
RESTRICTED = set()

for spec in DIRECTIVESPECS:

    names = [spec['name']] + list(spec['aliases'])
    handler = spec['handler']

    for name in names:

        DIRECTIVES[name] = handler

        if spec.get('restricted'):
            RESTRICTED.add(name)



# graphics diagnostic
def graphicsdiagnostic():

    global SCREENW, SCREENH, WORKX, WORKY, WORKW, WORKH
    global INPUTBUF, CURSORPOS, HSCROLL, SCROLLOFF, SELREGION, SELNORMAL
    global GRAPHICSCURSORON, DIRTY_SCROLL, DIRTY_PROMPT
    global RESIZEPENDINGW, RESIZEPENDINGH, RESIZEPENDINGAT, RESIZEAPPLIEDW, RESIZEAPPLIEDH
    global LASTSCROLLFRAME

    result = {
        "format": 1,
        "passed": False,
        "resolution": [2560, 1440],
        "checks": {},
        "performance": {},
        "errors": [],
    }

    try:

        SCREENW = 2560
        SCREENH = 1440
        WORKX = 0
        WORKY = 0
        WORKW = SCREENW
        WORKH = SCREENH
        applyuiscale(SCREENW, SCREENH)
        windowwidth, windowheight, windowx, windowy = windowrequest()
        setattr(gfx, "_xres", int(windowwidth))
        setattr(gfx, "_yres", int(windowheight))
        initfont()
        measurements()
        capabilities = {
            "version": 2,
            "accelerated": True,
            "managed_resources": True,
            "atomic_scene": True,
            "damage_regions": True,
            "commands": ["rectangle", "image", "text"],
            "command_limit": 1024,
            "text_limit": 1024,
            "damage_limit": 64,
        }
        graphicsconfigure(capabilities)

        if not GRAPHICSAVAILABLE:
            raise RuntimeError(f"managed graphics negotiation failed: {GRAPHICSFAILURE}")

        result["checks"]["capability_negotiation"] = True
        SCROLL.clear()
        STYLES.clear()

        for index in range(220):

            if index == 219:
                text = "long " + ("0123456789" * 350)

            else:
                text = f"diagnostic output line {index:04d}"

            SCROLL.append(text)
            STYLES.append({
                "colour": ERRORCOLOUR if index % 17 == 0 else TEXTCOLOUR,
                "bg": None,
                "bold": bool(index % 11 == 0 or index == 219),
                "underline": False,
                "italic": False,
            })

        INPUTBUF = "run /the one/build/brick/brick.py behind"
        CURSORPOS = len(INPUTBUF)
        SCROLLOFF = 0
        HSCROLL = 0
        layout = contentlayout()
        cachedlayout = contentlayout()

        if cachedlayout is not layout:
            raise RuntimeError("unchanged Brick content rebuilt its full layout")

        generation = SCROLL.generation
        SCROLL[-1] = SCROLL[-1]
        changedlayout = contentlayout()

        if SCROLL.generation <= generation or changedlayout is cachedlayout:
            raise RuntimeError("Brick layout cache did not invalidate after scrollback mutation")

        layout = changedlayout
        result["checks"]["idle_layout_cache"] = True
        longrows = [row for row in layout.get("visual_rows", []) if int(row[0]) == 219]

        if len(longrows) <= 1 or HSCROLL_MAX != 0:
            raise RuntimeError("long scrollback output did not wrap within the window")

        originalwidth = int(getattr(gfx, "_xres", windowwidth))
        setattr(gfx, "_xres", max(240, originalwidth // 2))
        narrowlayout = contentlayout()
        narrowlongrows = [row for row in narrowlayout.get("visual_rows", []) if int(row[0]) == 219]
        setattr(gfx, "_xres", originalwidth)
        layout = contentlayout()

        if len(narrowlongrows) <= len(longrows):
            raise RuntimeError("wrapped scrollback did not reflow after a width change")

        result["checks"]["word_wrap"] = {
            "wide_rows": len(longrows),
            "narrow_rows": len(narrowlongrows),
        }
        visiblerows = layout.get("visible_rows", [])
        selectionline = int(visiblerows[0][0]) if visiblerows else 0
        selectioncolumn = int(visiblerows[0][1]) if visiblerows else 0
        SELREGION = "content"
        SELNORMAL = ((selectionline, selectioncolumn + 2), (selectionline, selectioncolumn + 12))
        GRAPHICSCURSORON = True
        started = time.monotonic_ns()
        scenes = []

        for _ in range(12):
            scenes.append(graphicsbuildscene())

        elapsed = (time.monotonic_ns() - started) / 1000000.0
        scene = scenes[-1]
        width = int(getattr(gfx, "_xres", 0))
        height = int(getattr(gfx, "_yres", 0))

        if not scene or scene[0].get("kind") != "rectangle" or scene[0].get("rect") != [0, 0, width, height]:
            raise RuntimeError("managed scene does not begin with an opaque full-window background")

        result["checks"]["opaque_background"] = True

        if len(scene) > int(GRAPHICSLIMIT * 0.75):
            raise RuntimeError(f"managed scene uses too much of the command budget {len(scene)}/{GRAPHICSLIMIT}")

        result["checks"]["command_budget"] = {"commands": len(scene), "limit": GRAPHICSLIMIT}
        textcommands = [command for command in scene if command.get("kind") == "text"]
        rectanglecommands = [command for command in scene if command.get("kind") == "rectangle"]

        if not textcommands or len(rectanglecommands) < 4:
            raise RuntimeError("managed scene did not contain the required text and rectangle primitives")

        if any(len(str(command.get("text", ""))) > GRAPHICSTEXTLIMIT for command in textcommands):
            raise RuntimeError("managed text command exceeded the advertised text limit")

        originalinput = INPUTBUF
        INPUTBUF = originalinput + (" 0123456789" * 200)
        CURSORPOS = len(INPUTBUF)
        HSCROLL = 100
        clippedscene = graphicsbuildscene()
        wrappedpromptlayout = contentlayout()
        clippedtext = [command for command in clippedscene if command.get("kind") == "text"]
        clippedrectangles = [command for command in clippedscene if command.get("kind") == "rectangle"]

        if len(wrappedpromptlayout.get('prompt_rows', [])) <= 1 or HSCROLL_MAX != 0:
            raise RuntimeError("long prompt input did not wrap within the window")

        result["checks"]["word_wrap"]["prompt_rows"] = len(wrappedpromptlayout.get('prompt_rows', []))

        if any(int(command.get("x", -1)) < 0 or int(command.get("x", 0)) >= width for command in clippedtext):
            raise RuntimeError("horizontally clipped managed text retained an invalid x coordinate")

        if any(
            int(command.get("rect", [0, 0, 0, 0])[0]) < 0
            or int(command.get("rect", [0, 0, 0, 0])[1]) < 0
            or int(command.get("rect", [0, 0, 0, 0])[0]) + int(command.get("rect", [0, 0, 0, 0])[2]) > width
            or int(command.get("rect", [0, 0, 0, 0])[1]) + int(command.get("rect", [0, 0, 0, 0])[3]) > height
            for command in clippedrectangles
        ):
            raise RuntimeError("managed rectangle was not clipped to the window")

        if any(not os.path.isfile(str(command.get("font", ""))) for command in textcommands):
            raise RuntimeError("managed text referenced a missing font")

        INPUTBUF = originalinput
        CURSORPOS = len(INPUTBUF)
        HSCROLL = 0
        contentlayout()

        fonts = set(str(command.get("font", "")) for command in textcommands)

        if FONTREG not in fonts or FONTBOLD not in fonts or FONTSEMIBOLD not in fonts:
            raise RuntimeError("regular, bold, and semibold managed font paths were not exercised")

        result["checks"]["text_clipping"] = True
        result["checks"]["font_styles"] = sorted(fonts)

        if not any(command.get("color") == CURSORCOLOUR for command in rectanglecommands):
            raise RuntimeError("managed cursor rectangle was not generated")

        if not any(command.get("color") == SCROLLBAR_THUMB for command in rectanglecommands):
            raise RuntimeError("managed scrollbar thumb was not generated")

        result["checks"]["selection_cursor_scrollbars"] = True
        diagnosticimage = f'/.ephemeral/brick/image-diagnostic-{os.getpid()}.bgra'
        previousscroll = list(SCROLL)
        previousstyles = list(STYLES)
        previousoffset = SCROLLOFF
        previoushscroll = HSCROLL

        try:

            os.makedirs(os.path.dirname(diagnosticimage), mode=0o700, exist_ok=True)
            with open(diagnosticimage, 'wb') as stream:
                stream.write(bytes((0, 0, 255, 255)) * 16)

            SCROLL.clear()
            STYLES.clear()
            SCROLLOFF = 0
            HSCROLL = 0
            viewappend({
                'id': 9876,
                'source': '/the one/resources/image diagnostic.png',
                'path': diagnosticimage,
                'width': 4,
                'height': 4,
                'rows': 1,
                'format': 'BGRA32',
            })
            imagescene = graphicsbuildscene()
            imagecommands = [command for command in imagescene if command.get('kind') == 'image']

            if (
                not imagescene
                or imagescene[0].get('kind') != 'rectangle'
                or imagescene[0].get('rect') != [0, 0, width, height]
                or len(imagecommands) != 1
                or imagecommands[0].get('path') != diagnosticimage
                or imagecommands[0].get('format') != 'BGRA32'
                or imagecommands[0].get('source_width') != 4
                or imagecommands[0].get('source_height') != 4
            ):
                raise RuntimeError('managed inline image scene is invalid')

            result['checks']['image_view_scene'] = True

        finally:

            SCROLL.clear()
            SCROLL.extend(previousscroll)
            STYLES.clear()
            STYLES.extend(previousstyles)
            SCROLLOFF = previousoffset
            HSCROLL = previoushscroll

            try:
                os.unlink(diagnosticimage)

            except Exception:
                pass

        architectpresent = arch.guipresentdiagnostic()

        if not all(bool(value) for value in architectpresent.values()):
            raise RuntimeError("Architect modal presentation did not select Brick managed graphics safely")

        result["checks"]["architect_modal_presentation"] = architectpresent
        requests = []
        managedmarkdamage(GRAPHICSSTATE, [10, 20, 30, 40], bounds=(width, height))
        managedsubmit(GRAPHICSSTATE, lambda request: requests.append(request) or True, 99, scene)

        if len(requests) != 1 or requests[0].get("op") != "GRAPHICS_SCENE":
            raise RuntimeError("managed helper did not submit one atomic scene request")

        if requests[0].get("damage") != [[10, 20, 30, 40]]:
            raise RuntimeError("managed helper did not preserve scene damage")

        managedresponse(GRAPHICSSTATE, {
            "op": "GRAPHICS_COMMITTED",
            "winid": 99,
            "count": len(scene),
            "batch": True,
            "accelerated": True,
            "managed_only": True,
        })
        graphicssyncstate()

        if not GRAPHICSACTIVE or GRAPHICSPENDING:
            raise RuntimeError("managed helper did not activate an acknowledged scene")

        result["checks"]["atomic_scene"] = {
            "messages": len(requests),
            "commands": len(scene),
            "damage": len(requests[0].get("damage", [])),
        }

        LASTSCROLLFRAME = time.monotonic()
        DIRTY_SCROLL = True
        DIRTY_PROMPT = True

        if renderframe(True) or not DIRTY_SCROLL:
            raise RuntimeError("Brick rendered repeated scroll input before the frame interval elapsed")

        LASTSCROLLFRAME = 0.0
        DIRTY_SCROLL = False
        DIRTY_PROMPT = False
        result["checks"]["scroll_frame_throttle"] = True

        resizerequests = []
        managedclear(GRAPHICSSTATE, lambda request: resizerequests.append(request) or True, 99)
        managedmarkdamage(GRAPHICSSTATE, [0, 0, width, height], bounds=(width, height))
        managedsubmit(GRAPHICSSTATE, lambda request: resizerequests.append(request) or True, 99, scene)
        managedresponse(GRAPHICSSTATE, {"op": "GRAPHICS_CLEARED", "winid": 99})

        if not GRAPHICSSTATE.get("pending") or not GRAPHICSSTATE.get("pending_scene"):
            raise RuntimeError("clear acknowledgement discarded a newer resize scene")

        managedresponse(GRAPHICSSTATE, {
            "op": "GRAPHICS_COMMITTED",
            "winid": 99,
            "count": len(scene),
            "batch": True,
            "accelerated": True,
            "managed_only": True,
            "generation": int(GRAPHICSSTATE.get("pending_generation", 0)),
        })

        if not GRAPHICSSTATE.get("active") or len(GRAPHICSSTATE.get("scene", [])) != len(scene):
            raise RuntimeError("resize scene did not activate after clear/commit ordering")

        result["checks"]["resize_clear_commit_order"] = True
        GRAPHICSSTATE["damage"] = []
        GRAPHICSSTATE["need_submit"] = False
        DIRTY_SCROLL = False
        DIRTY_PROMPT = True
        drawcontent(True)
        promptdamage = list(GRAPHICSSTATE.get("damage", []))

        promptlayout = contentlayout()
        prompttop = int(promptlayout.get("prompty", -1))

        if (
            not promptdamage
            or not any(rect[0] == 0 and rect[1] == prompttop and rect[2] == width and rect[3] <= LINEHEIGHT for rect in promptdamage)
            or sum(int(rect[2]) * int(rect[3]) for rect in promptdamage) >= width * height
        ):
            raise RuntimeError(f"managed prompt update did not retain partial damage {promptdamage} layout={contentlayout()} active={GRAPHICSSTATE.get('active')} managed_only={GRAPHICSSTATE.get('managed_only')}")

        result["checks"]["managed_prompt_partial_damage"] = promptdamage
        committedscene = list(GRAPHICSSTATE.get("scene", []))
        graphicssuspend()

        if not GRAPHICSSTATE.get("active") or GRAPHICSSTATE.get("scene") != committedscene:
            raise RuntimeError("resize suspension discarded the last committed managed scene")

        result["checks"]["resize_retains_committed_scene"] = True
        RESIZEPENDINGW = 0
        RESIZEPENDINGH = 0
        RESIZEAPPLIEDW = width
        RESIZEAPPLIEDH = height
        onresized({"w": width, "h": height})

        if RESIZEPENDINGW != 0 or RESIZEPENDINGH != 0 or not GRAPHICSSTATE.get("active"):
            raise RuntimeError("duplicate resize notification suspended an already-current managed scene")

        result["checks"]["duplicate_resize_preserves_managed_scene"] = True
        graphicsconfigure({})

        if GRAPHICSAVAILABLE or GRAPHICSACTIVE:
            raise RuntimeError("missing capabilities did not select the CPU fallback")

        result["checks"]["cpu_fallback"] = True
        result["performance"] = {
            "average_scene_build_ms": round(elapsed / len(scenes), 3),
            "maximum_commands": len(scene),
            "window": [width, height],
        }
        result["passed"] = True

    except Exception as e:

        result["errors"].append(str(e))

    return result


def graphicsdiagnosticcommand():

    result = graphicsdiagnostic()
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result.get("passed") else 1


def viewdiagnosticcommand():

    global SCROLLOFF, HSCROLL, DIRTY_SCROLL, DIRTY_PROMPT

    result = {
        'format': 1,
        'passed': False,
        'checks': {},
        'errors': [],
    }
    root = f'/.ephemeral/brick/view-diagnostic-{os.getpid()}'

    try:

        os.makedirs(root, mode=0o700, exist_ok=False)
        from viewer.viewer import fixture as imagefixture

        source = os.path.join(root, 'sample image.jpg')
        imagefixture(source, 'JPEG', (2, 1), (220, 40, 30, 255))

        setattr(gfx, '_xres', 320)
        setattr(gfx, '_yres', 240)
        measurements()
        SCROLL.clear()
        STYLES.clear()
        SCROLLOFF = 0
        HSCROLL = 0
        view([source])
        imagestyles = [style for style in STYLES if isinstance(style, dict) and isinstance(style.get('image'), dict)]

        if not imagestyles:
            raise RuntimeError('view directive did not append an inline image')

        image = imagestyles[0]['image']
        expected = int(image['width']) * int(image['height']) * 4

        if os.path.getsize(image['path']) != expected:
            raise RuntimeError('image viewer produced the wrong BGRA surface size')

        result['checks']['decode'] = {
            'format': image.get('format'),
            'surface': [image.get('width'), image.get('height')],
            'bytes': expected,
        }
        layout = contentlayout()

        if (
            len(SCROLL) != int(image['rows']) + 1
            or len(STYLES) != int(image['rows']) + 1
            or len(imagestyles) != int(image['rows'])
            or any(style.get('image', {}).get('id') != image['id'] for style in imagestyles)
            or int(layout.get('prompty', 0)) != int(layout.get('top', 0)) + ((int(image['rows']) + 1) * LINEHEIGHT)
        ):
            raise RuntimeError(
                f"image viewer did not reserve inline scrollback rows above the prompt "
                f"scroll={len(SCROLL)} styles={len(STYLES)} rows={image['rows']} "
                f"top={layout.get('top')} prompt={layout.get('prompty')} line={LINEHEIGHT} "
                f"lines={list(SCROLL)}"
            )

        result['checks']['inline_scrollback'] = {
            'rows': int(image['rows']),
            'prompt_y': int(layout.get('prompty', 0)),
        }
        scene = graphicsbuildscene()
        images = [command for command in scene if command.get('kind') == 'image']

        if (
            not scene
            or scene[0].get('kind') != 'rectangle'
            or len(images) != 1
            or images[0].get('path') != image.get('path')
            or images[0].get('format') != 'BGRA32'
        ):
            raise RuntimeError('image viewer did not build a valid managed inline scene')

        result['checks']['managed_scene'] = True

        for index in range(4):
            appendline(f'output after image {index}')

        SCROLLOFF = 1
        scrolledscene = graphicsbuildscene()
        scrolledimages = [command for command in scrolledscene if command.get('kind') == 'image']

        if len(scrolledimages) != 1 or int(scrolledimages[0].get('rect', [0, 0])[1]) >= int(layout.get('top', 0)):
            raise RuntimeError('inline image did not scroll with shell output')

        result['checks']['scrolling'] = True

        for _ in range(4):
            SCROLL.pop()
            STYLES.pop()

        SCROLLOFF = 0
        bufferpath = os.path.join(root, 'cpu framebuffer.bgra')

        with open(bufferpath, 'wb') as stream:
            stream.truncate(320 * 240 * 4)

        initbuffer(bufferpath, 320, 240)
        DIRTY_SCROLL = True
        DIRTY_PROMPT = True
        drawcontent(False)
        layout = contentlayout()
        samplex = int(image['width']) // 2
        sampley = int(image['height']) // 2
        surfaceoffset = (sampley * int(image['width']) + samplex) * 4
        imageindex = next(
            index
            for index in range(int(layout['start']), int(layout['end']))
            if isinstance(STYLES[index], dict) and STYLES[index].get('image', {}).get('id') == image['id']
        )
        imagerow = int(STYLES[imageindex].get('image_row', 0))
        imagey = int(layout['y0']) + ((imageindex - int(layout['start'])) * LINEHEIGHT) - (imagerow * LINEHEIGHT)
        bufferoffset = ((imagey + sampley) * 320 + LEFTPAD + samplex) * 4

        with open(image['path'], 'rb') as stream:
            stream.seek(surfaceoffset)
            expectedpixel = stream.read(4)

        actualpixel = bytes(getattr(gfx, '_buffer', b'')[bufferoffset:bufferoffset + 4])

        if len(expectedpixel) != 4 or actualpixel != expectedpixel or actualpixel[:3] == b'\x00\x00\x00':
            raise RuntimeError('image viewer CPU fallback did not blit the decoded surface')

        result['checks']['cpu_blit'] = True
        result['checks']['directive'] = DIRECTIVES.get('view') is view
        result['passed'] = bool(result['checks']['directive'])

    except Exception as error:
        result['errors'].append(str(error))

    finally:

        SCROLL.clear()
        STYLES.clear()
        SCROLLOFF = 0
        HSCROLL = 0
        shutil.rmtree(root, ignore_errors=True)
        viewcleanup()

    print(json.dumps(result, sort_keys=True, separators=(',', ':')))
    return 0 if result.get('passed') else 1


def diagnosticjson(output):

    try:

        lines = [line for line in str(output).splitlines() if line.startswith('{')]

        if not lines:
            return {}

        return json.loads(lines[-1])

    except Exception:
        return {}


def diagnosticparsing():

    global INPUTBUF, CURSORPOS, DRIVES, DRIVELASTSCAN, DRIVENUMBER

    result = {'suite': 'parsing', 'passed': False, 'checks': {}, 'errors': []}

    try:

        names = []

        for spec in DIRECTIVESPECS:

            names.extend([spec.get('name', '')] + list(spec.get('aliases', [])))

            if not isinstance(spec.get('grammar'), dict):
                raise RuntimeError(f"directive grammar missing for {spec.get('name', '')}")

        if len(names) != len(set(names)) or set(names) != set(DIRECTIVES):
            raise RuntimeError('directive catalogue and dispatch differ')

        pythonspecs = [
            spec for spec in DIRECTIVESPECS
            if spec.get('category') == 'python'
        ]

        if len(pythonspecs) != 18:
            raise RuntimeError('Python directive catalogue is incomplete')

        pythonaliases = {
            'python status': ('ps',),
            'check python': ('cp', 'cpm'),
            'python history': ('ph',),
            'list python modules': ('lpm',),
            'show python module': ('spm',),
            'find python module': ('fpm',),
            'list python updates': ('lpu',),
            'install python module': ('ipm',),
            'install python wheel': ('ipw',),
            'remove python module': ('rpm',),
            'update python module': ('upm',),
            'update python modules': ('upms',),
            'pin python module': ('ppm',),
            'unpin python module': ('unpm',),
            'repair python modules': ('rprm',),
            'restore python modules': ('rspm',),
            'export python lock': ('epl',),
            'apply python lock': ('apl',),
        }

        for spec in pythonspecs:
            expectedaliases = set(
                pythonaliases.get(str(spec.get('name', '')), ()))
            if not expectedaliases.issubset(set(spec.get('aliases', []))):
                raise RuntimeError(
                    f"Python directive alias missing for {spec.get('name', '')}")

        result['checks']['python_aliases'] = True

        selectedaliases = {
            'list software': 'lsw',
            'software details': 'sd',
            'operation details': 'od',
            'system performance': 'sp',
            'list drives': 'ld',
            'drive details': 'dd',
            'list rubbish': 'lr',
            'rubbish details': 'rd',
            'list system drivers': 'lsd',
            'system driver details': 'sdd',
            'add startup operation': 'aso',
            'remove startup operation': 'rso',
            'change startup operation': 'cso',
            'history': 'h',
            'clear history': 'ch',
            'set timezone': 'stz',
            'set automatic time': 'sat',
            'set date and time': 'sdt',
            'terminal name': 'tn',
            'set terminal name': 'stn',
            'change master name': 'cmn',
            'change master password': 'cmp',
        }
        for name, alias in selectedaliases.items():
            if alias not in directivespec(name).get('aliases', []):
                raise RuntimeError('selected directive alias missing for ' + name)
        result['checks']['selected_aliases'] = True

        categories = [spec.get('category', '') for spec in DIRECTIVESPECS]

        if len(DIRECTIVECATEGORIES) != len(set(DIRECTIVECATEGORIES)):
            raise RuntimeError('directive categories are duplicated')

        if set(categories) != set(DIRECTIVECATEGORIES):
            raise RuntimeError('directive categories and catalogue differ')

        SCROLL.clear()
        STYLES.clear()
        help()
        helplines = [str(line).strip() for line in SCROLL]

        for category in DIRECTIVECATEGORIES:

            if str(category) not in helplines:
                raise RuntimeError(f'help category missing for {category}')

        SCROLL.clear()
        STYLES.clear()
        categoryresult = rundirective('help inspection', echo=False)
        categorytext = '\n'.join(str(line) for line in SCROLL)

        if not categoryresult.get('ok') or 'inspection directives' not in categorytext or 'show details' not in categorytext:
            raise RuntimeError('focused category help failed')

        SCROLL.clear()
        STYLES.clear()
        directiveresult = rundirective('help run', echo=False)
        directivetext = '\n'.join(str(line) for line in SCROLL)
        if directiveresult.get('ok') or 'help accepts a directive category' not in directivetext:
            raise RuntimeError('per-directive help was not retired')

        INPUTBUF = 'help oper'
        CURSORPOS = len(INPUTBUF)
        completeonce()

        if not INPUTBUF.startswith('help operations'):
            raise RuntimeError('help category completion failed')

        result['checks']['catalogue_categories'] = True

        expected = {
            'rename': ('file', 'to'),
            'move': ('file', 'to'),
            'copy': ('file', 'to'),
            'rename tier': ('dir', 'to'),
            'move tier': ('dir', 'to'),
            'copy tier': ('dir', 'to'),
            'compare': ('path', 'with'),
        }

        for name, values in expected.items():

            grammar = directivespec(name).get('grammar', {})

            if grammar.get('source') != values[0] or values[1] not in grammar.get('connectors', []):
                raise RuntimeError(f'catalogue grammar invalid for {name}')

        for spec in DIRECTIVESPECS:

            connectors = [str(value).casefold() for value in spec.get('grammar', {}).get('connectors', [])]

            if not connectors:
                continue

            usages = [f" {str(value).casefold()} " for value in spec.get('usages', [])]
            connective = any(any(f' {word} ' in usage for word in connectors) for usage in usages)
            positional = any(not any(f' {word} ' in usage for word in connectors) for usage in usages)

            if not connective or not positional:
                raise RuntimeError(f"connector is not optional in help for {spec.get('name', '')}")

        result['checks']['catalogue_grammar'] = True
        matched, count = matcheddirective(
            shlex.split('install python module example version 1.0')
        )

        if (
            matched != 'install python module'
            or count != 3
            or directivebounds('  install python module example') != (2, 23)
        ):
            raise RuntimeError('longest plain-English directive matching failed')

        result['checks']['long_directives'] = True
        INPUTBUF = 'read some file with n'
        CURSORPOS = len(INPUTBUF)
        completeonce()

        if not INPUTBUF.endswith('with numbers'):
            raise RuntimeError('catalogue keyword completion failed')

        INPUTBUF = ''
        CURSORPOS = 0
        result['checks']['grammar_completion'] = True

        saveddrives = dict(DRIVES)
        savedscan = DRIVELASTSCAN
        savednumber = DRIVENUMBER
        diagnosticdriveroot = '/.ephemeral/volumes/brick-diagnostic-drive'

        try:

            DRIVES = {
                1: {'number': 1, 'root': '/', 'label': 't1os', 'removable': False},
                2: {'number': 2, 'root': diagnosticdriveroot, 'label': 'diagnostic', 'removable': True},
            }
            DRIVELASTSCAN = time.time()

            number, explicit = parselocation('2/photos/example.png')
            _currentnumber, currentabsolute = parselocation('/photos/example.png', currentdrive=2)
            expected = physicalnormalize(diagnosticdriveroot + '/photos/example.png')

            if (
                number != 2
                or explicit != expected
                or currentabsolute != expected
                or formatlocation(expected) != '2/photos/example.png'
                or drivepath(2, '/../../outside') is not None
                or drivepath(9, '/') is not None
            ):
                raise RuntimeError('numeric drive location mapping failed')

            result['checks']['numeric_drive_locations'] = True

        finally:
            DRIVES = saveddrives
            DRIVELASTSCAN = savedscan
            DRIVENUMBER = savednumber

        versionresult = subprocess.run(
            [sys.executable, BRICKPATH, 'execute', 'version'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )
        versionactual = diagnosticjson(versionresult.stdout)

        if versionresult.returncode != 0 or not versionactual.get('passed') or OSVERSION not in '\n'.join(versionactual.get('output', [])):
            raise RuntimeError('headless version execution failed')

        result['checks']['headless_success'] = True
        failresult = subprocess.run(
            [sys.executable, BRICKPATH, 'execute', 'directive that does not exist'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )
        failactual = diagnosticjson(failresult.stdout)

        if failresult.returncode == 0 or failactual.get('passed') or failactual.get('results', [{}])[0].get('code') != 'unknown':
            raise RuntimeError('headless failure result was not structured')

        result['checks']['headless_failure'] = True
        guardresult = subprocess.run(
            [sys.executable, BRICKPATH, 'execute', 'view anything'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )
        guardactual = diagnosticjson(guardresult.stdout)

        if guardresult.returncode == 0 or guardactual.get('results', [{}])[0].get('code') != 'graphical_only':
            raise RuntimeError('headless graphical directive guard failed')

        result['checks']['graphical_guard'] = True
        focusedresult = subprocess.run(
            [sys.executable, BRICKPATH, 'directive-diagnostic', 'search'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=15,
        )
        focusedactual = diagnosticjson(focusedresult.stdout)

        if focusedresult.returncode != 0 or not focusedactual.get('passed') or focusedactual.get('suite') != 'search':
            raise RuntimeError('focused diagnostic command routing failed')

        result['checks']['focused_cli'] = True
        result['passed'] = all(bool(value) for value in result['checks'].values())

    except Exception as e:
        result['errors'].append(str(e))

    return result


def diagnosticfiles():

    global TRANSACTIONCOPYORIGINAL, TRANSACTIONCOPYCOUNT, TRANSACTIONCOPYFAILAT
    global TRANSACTIONMOVEORIGINAL, TRANSACTIONMOVECOUNT, TRANSACTIONMOVEFAILAT
    global DRIVES, DRIVELASTSCAN, DRIVENUMBER

    result = {'suite': 'files', 'passed': False, 'checks': {}, 'errors': []}
    root = f'/.ephemeral/brick/files-diagnostic-{os.getpid()}'
    originalrole = arch.currentrole
    originaldrives = dict(DRIVES)
    originaldrivescan = DRIVELASTSCAN
    originaldrivenumber = DRIVENUMBER

    try:

        shutil.rmtree(root, ignore_errors=True)
        os.makedirs(root, exist_ok=False)
        arch.currentrole = 'architect'
        copydestination = os.path.join(root, 'copy destination')
        movedestination = os.path.join(root, 'move destination')
        os.makedirs(copydestination, exist_ok=False)
        os.makedirs(movedestination, exist_ok=False)
        copysources = [os.path.join(root, 'copy one.txt'), os.path.join(root, 'copy two.txt')]
        movesources = [os.path.join(root, 'move one.txt'), os.path.join(root, 'move two.txt')]
        wildcardtier = os.path.join(root, 'the one', 'logs')
        os.makedirs(wildcardtier, exist_ok=False)

        with open(os.path.join(wildcardtier, 'first.log'), 'w', encoding='utf-8') as stream:
            stream.write('first\n')

        with open(os.path.join(wildcardtier, 'ignored.txt'), 'w', encoding='utf-8') as stream:
            stream.write('ignored\n')

        sourceparts = [os.path.join(root, 'the'), 'one/logs', '*.log']
        withoutconnector, withoutdestination = wildcardarguments(
            sourceparts + [copydestination],
            want='file',
        )
        withconnector, withdestination = wildcardarguments(
            sourceparts + ['to', copydestination],
            want='file',
        )
        expectedwildcard = [os.path.join(wildcardtier, 'first.log')]

        if (
            withoutconnector != expectedwildcard
            or withconnector != expectedwildcard
            or withoutdestination != copydestination
            or withdestination != copydestination
        ):
            raise RuntimeError('optional connector wildcard parsing differs')

        result['checks']['optional_connectors'] = True

        try:

            DRIVES = {
                1: {'number': 1, 'root': '/', 'label': 't1os', 'removable': False},
                2: {'number': 2, 'root': copydestination, 'label': 'diagnostic', 'removable': True},
            }
            DRIVELASTSCAN = time.time()
            sourceexpression = f"{os.path.join(root, 'the')} one/logs *.log"
            plaincommand = f'copy {sourceexpression} 2/'
            connectedcommand = f'copy {sourceexpression} to 2/'

            def styledarguments(command):
                return [command[start:end] for start, end in semiboldbounds(command)]

            if styledarguments('ct 2/') != ['2/']:
                raise RuntimeError('numeric drive location was not semibold')

            if styledarguments(plaincommand) != [sourceexpression, '2/']:
                raise RuntimeError('connector-free wildcard arguments were not semibold')

            if styledarguments(connectedcommand) != [sourceexpression, '2/']:
                raise RuntimeError('connected wildcard arguments were not semibold')

            result['checks']['drive_wildcard_semibold'] = True

        finally:
            DRIVES = originaldrives
            DRIVELASTSCAN = originaldrivescan
            DRIVENUMBER = originaldrivenumber

        for path in copysources + movesources:

            with open(path, 'w', encoding='utf-8') as stream:
                stream.write(path + '\n')

        TRANSACTIONCOPYORIGINAL = shutil.copy2
        TRANSACTIONCOPYCOUNT = 0
        TRANSACTIONCOPYFAILAT = 2
        shutil.copy2 = transactiondiagnosticcopy

        try:
            copied = transactioncopy(copysources, copydestination)
        finally:
            shutil.copy2 = TRANSACTIONCOPYORIGINAL

        if copied.get('ok') or not copied.get('data', {}).get('rolled_back') or os.listdir(copydestination):
            raise RuntimeError('copy transaction did not roll back')

        if not all(os.path.isfile(path) for path in copysources):
            raise RuntimeError('copy rollback damaged a source')

        result['checks']['copy_rollback'] = True
        TRANSACTIONMOVEORIGINAL = shutil.move
        TRANSACTIONMOVECOUNT = 0
        TRANSACTIONMOVEFAILAT = 2
        shutil.move = transactiondiagnosticmove

        try:
            moved = transactionmove(movesources, movedestination)
        finally:
            shutil.move = TRANSACTIONMOVEORIGINAL

        if moved.get('ok') or not moved.get('data', {}).get('rolled_back') or os.listdir(movedestination):
            raise RuntimeError('move transaction did not roll back')

        if not all(os.path.isfile(path) for path in movesources):
            raise RuntimeError('move rollback did not restore every source')

        result['checks']['move_rollback'] = True
        result['passed'] = all(bool(value) for value in result['checks'].values())

    except Exception as e:
        result['errors'].append(str(e))

    finally:

        shutil.copy2 = TRANSACTIONCOPYORIGINAL or shutil.copy2
        shutil.move = TRANSACTIONMOVEORIGINAL or shutil.move
        TRANSACTIONCOPYFAILAT = 0
        TRANSACTIONMOVEFAILAT = 0
        DRIVES = originaldrives
        DRIVELASTSCAN = originaldrivescan
        DRIVENUMBER = originaldrivenumber
        arch.currentrole = originalrole
        shutil.rmtree(root, ignore_errors=True)

    return result


def diagnosticrubbish():

    result = {'suite': 'rubbish', 'passed': False, 'checks': {}, 'errors': []}
    root = f'/.ephemeral/brick/rubbish-diagnostic-{os.getpid()}'
    originalrole = arch.currentrole
    ids = []

    try:

        shutil.rmtree(root, ignore_errors=True)
        os.makedirs(root, exist_ok=False)
        arch.currentrole = 'architect'
        path = os.path.join(root, 'rubbish item with spaces.txt')

        with open(path, 'w', encoding='utf-8') as stream:
            stream.write('rubbish suite\n')

        before = set(str(item.get('id')) for item in rubbishapi.readindex())
        storepaths([path])
        after = rubbishapi.readindex()
        ids = [str(item.get('id')) for item in after if str(item.get('id')) not in before]

        if len(ids) != 1 or os.path.exists(path):
            raise RuntimeError('rubbish suite did not store one item')

        if not rubbishapi.restorefromrubbishrid(ids[0]) or not os.path.isfile(path):
            raise RuntimeError('rubbish suite could not restore by id')

        ids = []
        result['checks']['store_restore_id'] = True
        result['passed'] = True

    except Exception as e:
        result['errors'].append(str(e))

    finally:

        arch.currentrole = 'architect'

        for rid in ids:

            try:
                rubbishapi.restorefromrubbishrid(rid)
            except Exception:
                pass

        arch.currentrole = originalrole
        shutil.rmtree(root, ignore_errors=True)

    return result


def diagnosticsearch():

    result = {'suite': 'search', 'passed': False, 'checks': {}, 'errors': []}
    root = f'/.ephemeral/brick/search-diagnostic-{os.getpid()}'

    try:

        shutil.rmtree(root, ignore_errors=True)
        os.makedirs(os.path.join(root, 'search tier', 'nested tier'), exist_ok=False)
        readpath = os.path.join(root, 'read sample.txt')

        with open(readpath, 'w', encoding='utf-8') as stream:
            stream.write('one\ntwo\nthree\nfour\n')

        matchpath = os.path.join(root, 'search tier', 'nested tier', 'matching file.py')

        with open(matchpath, 'w', encoding='utf-8') as stream:
            stream.write('deep needle\n')

        readresult = subprocess.run(
            [sys.executable, '/the one/build/read/read.py', 'read', 'sample.txt', 'from', '2', 'to', '3', 'with', 'numbers'],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )

        if readresult.returncode != 0 or readresult.stdout.splitlines() != ['2: two', '3: three']:
            raise RuntimeError('focused bounded read failed')

        result['checks']['bounded_read'] = True
        searchresult = subprocess.run(
            [sys.executable, '/the one/build/search/search.py', 'all', 'deep', 'needle', 'in', 'search', 'tier'],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )

        if searchresult.returncode != 0 or 'matching file.py:1 deep needle' not in searchresult.stdout:
            raise RuntimeError('focused recursive search failed')

        result['checks']['recursive_search'] = True
        result['passed'] = True

    except Exception as e:
        result['errors'].append(str(e))

    finally:
        shutil.rmtree(root, ignore_errors=True)

    return result


def diagnosticoperations():

    result = {'suite': 'operations', 'passed': False, 'checks': {}, 'errors': []}

    try:

        process = subprocess.run(
            [sys.executable, '/the one/build/operations/operationsserver.py', 'diagnostic'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )
        actual = diagnosticjson(process.stdout)

        if process.returncode != 0 or not actual.get('passed'):
            raise RuntimeError(f"operation service diagnostic failed {actual.get('errors', process.stderr.strip())}")

        if not actual.get('checks', {}).get('boot_scoped_checkpoint'):
            raise RuntimeError('operation boot-scoped checkpoint was not tested')

        result['checks']['service_lifecycle'] = True
        result['checks']['boot_scoped_checkpoint'] = True
        result['passed'] = True

    except Exception as e:
        result['errors'].append(str(e))

    return result


def diagnosticdevelopment():

    result = {'suite': 'development', 'passed': False, 'checks': {}, 'errors': []}
    root = f'/.ephemeral/brick/development-diagnostic-{os.getpid()}'
    originalcwd = os.getcwd()
    originalrole = arch.currentrole

    try:

        shutil.rmtree(root, ignore_errors=True)
        os.makedirs(root, exist_ok=False)
        os.chdir(root)
        arch.currentrole = 'architect'

        with open('development file.txt', 'w', encoding='utf-8') as stream:
            stream.write('alpha alpha\n')

        shutil.copy2('development file.txt', 'development twin.txt')

        if showdetails(['development', 'file.txt']) != 0:
            raise RuntimeError('focused details failed')

        if compare(['development', 'file.txt', 'with', 'development', 'twin.txt']) != 0:
            raise RuntimeError('focused compare failed')

        if replace(['all', 'alpha', 'with', 'beta', 'in', 'development', 'file.txt']) != 0:
            raise RuntimeError('focused replace failed')

        result['checks']['inspect_compare_replace'] = True

        with open('syntax good.py', 'w', encoding='utf-8') as stream:
            stream.write("raise RuntimeError('must not execute')\n")

        if checksyntax(['syntax', 'good.py']) != 0:
            raise RuntimeError('focused syntax check failed')

        result['checks']['syntax_only'] = True
        systemcode = checksystem()

        if systemcode not in (0, 1):
            raise RuntimeError('focused system report failed')

        result['checks']['system_report'] = True
        result['passed'] = True

    except Exception as e:
        result['errors'].append(str(e))

    finally:

        arch.currentrole = originalrole
        os.chdir(originalcwd)
        shutil.rmtree(root, ignore_errors=True)

    return result


def diagnosticdogfood():

    result = {'suite': 'dogfood', 'passed': False, 'checks': {}, 'errors': []}
    root = f'/.ephemeral/brick/dogfood-diagnostic-{os.getpid()}'

    try:

        shutil.rmtree(root, ignore_errors=True)
        os.makedirs(root, exist_ok=False)
        os.makedirs(os.path.join(root, 'copied tier'), exist_ok=False)
        first = os.path.join(root, 'awkward to in file.txt')
        second = os.path.join(root, 'awkward with twin.txt')

        with open(first, 'w', encoding='utf-8') as stream:
            stream.write('old phrase\n')

        shutil.copy2(first, second)
        command = (
            'show details awkward to in file.txt; '
            'compare awkward to in file.txt with awkward with twin.txt; '
            'replace old phrase with new phrase in awkward to in file.txt; '
            'search exact new phrase in .; '
            'copy awkward *.txt to copied tier'
        )
        process = subprocess.run(
            [sys.executable, BRICKPATH, 'execute', command],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=20,
        )
        actual = diagnosticjson(process.stdout)

        if process.returncode != 0 or not actual.get('passed') or len(actual.get('results', [])) != 5:
            detail = {
                'stderr': actual.get('stderr') or process.stderr.strip(),
                'results': actual.get('results'),
                'output': actual.get('output'),
            }
            raise RuntimeError(f"headless dogfood workflow failed {detail}")

        with open(first, encoding='utf-8') as stream:

            if stream.read() != 'new phrase\n':
                raise RuntimeError('dogfood replacement wrote unexpected content')

        copied = os.path.join(root, 'copied tier')

        if not os.path.isfile(os.path.join(copied, os.path.basename(first))) or not os.path.isfile(os.path.join(copied, os.path.basename(second))):
            raise RuntimeError('dogfood wildcard copy lost a space-aware path')

        result['checks']['headless_workflow'] = True
        result['checks']['connector_words_in_paths'] = True
        result['checks']['wildcard_transaction'] = True
        result['passed'] = True

    except Exception as e:
        result['errors'].append(str(e))

    finally:
        shutil.rmtree(root, ignore_errors=True)

    return result


def diagnosticnetwork():

    global BRICKNETWORKDIR, BRICKNETWORKFILE, BRICKDNSFILE
    global BRICKNETWORKSTATE, BRICKFIREWALLSTATE, BRICKWIRELESSSTATE
    global BRICKWIRELESSREQUEST, BRICKNETWORKREQUEST, BRICKNETSTATE

    result = {'suite': 'network', 'passed': False, 'checks': {}, 'errors': []}
    root = f'/.ephemeral/brick/network-diagnostic-{os.getpid()}'
    originals = {
        'BRICKNETWORKDIR': BRICKNETWORKDIR,
        'BRICKNETWORKFILE': BRICKNETWORKFILE,
        'BRICKDNSFILE': BRICKDNSFILE,
        'BRICKNETWORKSTATE': BRICKNETWORKSTATE,
        'BRICKFIREWALLSTATE': BRICKFIREWALLSTATE,
        'BRICKWIRELESSSTATE': BRICKWIRELESSSTATE,
        'BRICKWIRELESSREQUEST': BRICKWIRELESSREQUEST,
        'BRICKNETWORKREQUEST': BRICKNETWORKREQUEST,
        'BRICKNETSTATE': BRICKNETSTATE,
    }

    try:
        settings = os.path.join(root, 'settings', 'network')
        runtime = os.path.join(root, 'runtime', 'network')
        netstate = os.path.join(root, 'net')
        os.makedirs(settings, mode=0o755, exist_ok=False)
        os.makedirs(runtime, mode=0o755, exist_ok=False)
        os.makedirs(os.path.join(netstate, 'eth0'), mode=0o755, exist_ok=False)
        os.makedirs(os.path.join(netstate, 'wlan0', 'wireless'), mode=0o755, exist_ok=False)

        BRICKNETWORKDIR = settings
        BRICKNETWORKFILE = os.path.join(settings, 'network.txt')
        BRICKDNSFILE = os.path.join(settings, 'dns.txt')
        BRICKNETWORKSTATE = os.path.join(runtime, 'connection.json')
        BRICKFIREWALLSTATE = os.path.join(runtime, 'firewall.json')
        BRICKWIRELESSSTATE = os.path.join(runtime, 'wireless.json')
        BRICKWIRELESSREQUEST = os.path.join(runtime, 'scan.request')
        BRICKNETWORKREQUEST = os.path.join(runtime, 'reconfigure.request')
        BRICKNETSTATE = netstate

        networkatomictext(BRICKNETWORKFILE, 'interface=\ndns=automatic\nfirewall=protected\ndhcp=true\n')
        networkatomictext(BRICKDNSFILE, 'nameserver 10.0.2.3\n')
        networkatomictext(os.path.join(netstate, 'eth0', 'operstate'), 'up\n')
        networkatomictext(os.path.join(netstate, 'wlan0', 'operstate'), 'down\n')

        for path, value in (
            (BRICKNETWORKSTATE, {
                'connected': True, 'interface': 'eth0', 'type': 'ethernet',
                'name': 'diagnostic network', 'address': '10.0.2.15',
                'gateway': '10.0.2.2', 'server': '10.0.2.2',
                'mac': '08:00:27:00:00:01'}),
            (BRICKFIREWALLSTATE, {
                'active': True, 'profile': 'protected', 'incoming': 'blocked',
                'forwarding': 'blocked', 'outgoing': 'allowed'}),
            (BRICKWIRELESSSTATE, {'networks': [
                {'ssid': 'nearby network', 'security': 'wpa2', 'signal': -40},
                {'ssid': 'open network', 'security': 'open', 'signal': -70},
            ]}),
        ):
            networkatomictext(path, json.dumps(value, sort_keys=True) + '\n')

        SCROLL.clear()
        STYLES.clear()
        if not rundirective('nd', echo=False).get('ok'):
            raise RuntimeError('network details alias failed')
        if 'diagnostic network' not in '\n'.join(str(line) for line in SCROLL):
            raise RuntimeError('network details omitted the active connection')
        result['checks']['details'] = True

        if not rundirective('lni', echo=False).get('ok'):
            raise RuntimeError('network interface list failed')
        result['checks']['interfaces'] = True

        if not rundirective('uni wlan0', echo=False).get('ok') or networkreadconfig().get('interface') != 'wlan0':
            raise RuntimeError('preferred network interface did not persist')
        result['checks']['interface_selection'] = True

        if not rundirective('sds 1.1.1.1 8.8.8.8', echo=False).get('ok'):
            raise RuntimeError('manual DNS directive failed')
        if networkdnsservers() != ['1.1.1.1', '8.8.8.8'] or networkreadconfig().get('dns') != 'manual':
            raise RuntimeError('manual DNS settings did not persist')
        if not rundirective('dns', echo=False).get('ok'):
            raise RuntimeError('dns status alias failed')
        result['checks']['dns'] = True

        if not rundirective('sna 192.0.2.10 24 192.0.2.1', echo=False).get('ok'):
            raise RuntimeError('manual address directive failed')
        addressconfig = networkreadconfig()
        if addressconfig.get('dhcp') != 'false' or addressconfig.get('address') != '192.0.2.10':
            raise RuntimeError('manual address did not persist')
        if not os.path.isfile(os.path.join(settings, 'wlan0.txt')):
            raise RuntimeError('selected interface configuration was not updated')
        if rundirective('sda', echo=False).get('ok'):
            raise RuntimeError('automatic DNS was allowed with a manual address')
        if not rundirective('sna automatic', echo=False).get('ok') or not rundirective('sda', echo=False).get('ok'):
            raise RuntimeError('automatic address and DNS directives failed')
        result['checks']['addressing'] = True

        if not rundirective('sfw open', echo=False).get('ok') or networkreadconfig().get('firewall') != 'open':
            raise RuntimeError('firewall profile did not persist')
        if not rundirective('fws', echo=False).get('ok'):
            raise RuntimeError('firewall status alias failed')
        result['checks']['firewall'] = True

        if not rundirective('sw', echo=False).get('ok') or not os.path.isfile(BRICKWIRELESSREQUEST):
            raise RuntimeError('wi-fi scan request failed')
        if not rundirective('lwn', echo=False).get('ok'):
            raise RuntimeError('wi-fi list alias failed')
        if 'nearby network' not in '\n'.join(str(line) for line in SCROLL):
            raise RuntimeError('wi-fi list omitted scan results')
        result['checks']['wifi'] = True

        output = [str(line) for line in SCROLL]
        if any(line != line.lower() for line in output):
            raise RuntimeError('network directive output was not lowercase')
        result['checks']['lowercase_output'] = True

        result['checks']['reconfigure_request'] = os.path.isfile(BRICKNETWORKREQUEST)
        result['passed'] = all(result['checks'].values())

    except Exception as error:
        result['errors'].append(str(error))

    finally:
        BRICKNETWORKDIR = originals['BRICKNETWORKDIR']
        BRICKNETWORKFILE = originals['BRICKNETWORKFILE']
        BRICKDNSFILE = originals['BRICKDNSFILE']
        BRICKNETWORKSTATE = originals['BRICKNETWORKSTATE']
        BRICKFIREWALLSTATE = originals['BRICKFIREWALLSTATE']
        BRICKWIRELESSSTATE = originals['BRICKWIRELESSSTATE']
        BRICKWIRELESSREQUEST = originals['BRICKWIRELESSREQUEST']
        BRICKNETWORKREQUEST = originals['BRICKNETWORKREQUEST']
        BRICKNETSTATE = originals['BRICKNETSTATE']
        SCROLL.clear()
        STYLES.clear()
        shutil.rmtree(root, ignore_errors=True)

    return result


def focuseddirectivediagnosticcommand(suite):

    name = str(suite or '').strip().casefold()
    functions = {
        'parsing': diagnosticparsing,
        'files': diagnosticfiles,
        'rubbish': diagnosticrubbish,
        'search': diagnosticsearch,
        'operations': diagnosticoperations,
        'development': diagnosticdevelopment,
        'dogfood': diagnosticdogfood,
        'network': diagnosticnetwork,
    }
    function = functions.get(name)

    if function is None:

        result = {'suite': name, 'passed': False, 'checks': {}, 'errors': [f'unknown directive diagnostic suite {name}']}
        print(json.dumps(result, sort_keys=True, separators=(',', ':')))
        return 1

    result = function()
    print(json.dumps(result, sort_keys=True, separators=(',', ':')))
    return 0 if result.get('passed') else 1


def directivediagnosticcommand():

    global SCROLLOFF, HSCROLL, INPUTBUF, CURSORPOS, MULTILINES, PREVTIER

    result = {
        'passed': False,
        'checks': {},
        'errors': [],
    }

    root = f'/.ephemeral/brick/directive-diagnostic-{os.getpid()}'

    originalcwd = None

    testrubbishids = []

    try:

        originalcwd = os.getcwd()

    except Exception:

        originalcwd = '/'

    try:

        originalrole = arch.currentrole

    except Exception:

        originalrole = 'master'

    try:

        shutil.rmtree(root, ignore_errors=True)

        os.makedirs(root, exist_ok=False)

        os.chdir(root)

        arch.currentrole = 'architect'

        # verify duplicate copy handles an unquoted file path containing spaces
        with open('source file.txt', 'w') as stream:

            stream.write('copy diagnostic\n')

        copy(['source', 'file.txt'])

        copiedfile = 'source file - copy.txt'

        if not os.path.isfile(copiedfile):

            raise RuntimeError('space-aware duplicate file copy failed')

        result['checks']['copy_file_with_spaces'] = True

        # verify duplicate tier copy handles an unquoted tier path containing spaces
        os.makedirs('source tier', exist_ok=False)

        with open(os.path.join('source tier', 'content.txt'), 'w') as stream:

            stream.write('tier diagnostic\n')

        copytier(['source', 'tier'])

        copiedtier = 'source tier - copy'

        if not os.path.isfile(os.path.join(copiedtier, 'content.txt')):

            raise RuntimeError('space-aware duplicate tier copy failed')

        result['checks']['copy_tier_with_spaces'] = True

        # verify a successful tier move does not fall through to failure output
        os.makedirs('move source tier', exist_ok=False)

        os.makedirs('move destination tier', exist_ok=False)

        SCROLL.clear()

        STYLES.clear()

        movetier(['move', 'source', 'tier', 'move', 'destination', 'tier'])

        movedtier = os.path.join('move destination tier', 'move source tier')

        if not os.path.isdir(movedtier):

            raise RuntimeError('space-aware tier move failed')

        if any('could not move tier' in str(line) for line in SCROLL):

            raise RuntimeError('successful tier move reported failure')

        result['checks']['move_tier_success'] = True

        # verify write in uses its deployed filename and preserves the target path
        if not os.path.isfile('/the one/build/writein/write in.py'):

            raise RuntimeError('deployed write in software was not found')

        writein(['written text', 'written', 'file.txt'])

        with open('written file.txt') as stream:

            written = stream.read()

        if written != 'written text\n':

            raise RuntimeError('write in did not preserve the space-aware target path')

        result['checks']['write_in_with_spaces'] = True

        # verify restore passes the complete logical name to the rubbish backend
        restorename = f'brick restore diagnostic {os.getpid()}.txt'

        restorepath = os.path.join(root, restorename)

        with open(restorepath, 'w') as stream:

            stream.write('restore diagnostic\n')

        beforeids = set(str(item.get('id')) for item in rubbishapi.readindex())

        storepaths([restorepath])

        afterids = set(str(item.get('id')) for item in rubbishapi.readindex())

        testrubbishids = sorted(afterids - beforeids)

        if len(testrubbishids) != 1:

            raise RuntimeError('restore diagnostic was not stored in rubbish')

        os.chdir('/.rubbish')

        restore(restorename.split(' '))

        os.chdir(root)

        if not os.path.isfile(restorepath):

            raise RuntimeError('space-aware rubbish restore failed')

        remainingids = set(str(item.get('id')) for item in rubbishapi.readindex())

        if testrubbishids[0] in remainingids:

            raise RuntimeError('restored item remained in the rubbish index')

        testrubbishids = []

        result['checks']['restore_with_spaces'] = True

        # verify duplicate rubbish names can be selected without an interactive prompt
        duplicatename = f'duplicate restore {os.getpid()}.txt'
        firsttier = os.path.join(root, 'restore first tier')
        secondtier = os.path.join(root, 'restore second tier')
        os.makedirs(firsttier, exist_ok=False)
        os.makedirs(secondtier, exist_ok=False)
        firstpath = os.path.join(firsttier, duplicatename)
        secondpath = os.path.join(secondtier, duplicatename)

        with open(firstpath, 'w') as stream:
            stream.write('first restore\n')

        with open(secondpath, 'w') as stream:
            stream.write('second restore\n')

        beforeids = set(str(item.get('id')) for item in rubbishapi.readindex())
        storepaths([firstpath, secondpath])
        indexed = rubbishapi.readindex()
        afterids = set(str(item.get('id')) for item in indexed)
        testrubbishids = sorted(afterids - beforeids)

        if len(testrubbishids) != 2:
            raise RuntimeError('duplicate restore items were not stored')

        secondid = next(
            str(item.get('id'))
            for item in indexed
            if str(item.get('id')) in testrubbishids and os.path.abspath(item.get('origpath', '')) == os.path.abspath(secondpath)
        )
        os.chdir('/.rubbish')
        SCROLL.clear()
        STYLES.clear()
        opentier()
        rubbishtext = '\n'.join(str(line) for line in SCROLL)

        if 'original tier' not in rubbishtext or secondid not in rubbishtext:
            raise RuntimeError('rubbish listing omitted deterministic restore details')

        restore([duplicatename, 'from', firsttier])

        if not os.path.isfile(firstpath) or os.path.isfile(secondpath):
            raise RuntimeError('restore from original tier selected the wrong item')

        restore(['id', secondid])
        os.chdir(root)

        if not os.path.isfile(secondpath):
            raise RuntimeError('restore id failed')

        testrubbishids = []
        result['checks']['deterministic_restore'] = True

        # verify permission checks receive the complete protected path
        arch.currentrole = 'master'

        SCROLL.clear()

        STYLES.clear()

        originalroleloader = arch.loadrole
        arch.loadrole = lambda: 'master'

        try:

            allowed = allowpaths(['/the one/build/brick/permission test.py'])

        finally:

            arch.loadrole = originalroleloader

        if allowed:

            raise RuntimeError('protected path permission check allowed a master mutation')

        result['checks']['protected_path_with_spaces'] = True

        # verify generated help includes every recursive tier directive
        arch.currentrole = 'architect'

        SCROLL.clear()

        STYLES.clear()

        help()

        helptext = '\n'.join(str(line) for line in SCROLL)

        if 'open tiers' not in helptext or 'expose tiers' not in helptext:

            raise RuntimeError('recursive tier directives are missing from help')

        result['checks']['recursive_tier_help'] = True

        # verify the catalogue drives dispatch, aliases, help, completion, and highlighting metadata
        names = []

        for spec in DIRECTIVESPECS:
            names.extend([spec.get('name', '')] + list(spec.get('aliases', [])))

        if len(names) != len(set(names)) or set(names) != set(DIRECTIVES):
            raise RuntimeError('directive catalogue and dispatch table differ')

        SCROLL.clear()
        STYLES.clear()
        focused = rundirective('help compare', echo=False)

        if not focused.get('ok') or 'compare two files or tiers' not in '\n'.join(str(line) for line in SCROLL):
            raise RuntimeError('focused catalogue help failed')

        INPUTBUF = 'show det'
        CURSORPOS = len(INPUTBUF)
        completeonce()

        if not INPUTBUF.startswith('show details'):
            raise RuntimeError('multiword directive completion failed')

        if not directivespec('ct') or directivespec('ct').get('name') != 'change tier':
            raise RuntimeError('directive alias metadata failed')

        result['checks']['directive_catalogue'] = True

        SCROLL.clear()
        STYLES.clear()
        version()
        versionlines = [str(line) for line in SCROLL if str(line).strip()]

        if versionlines != [f'> The One OS version {OSVERSION}']:
            raise RuntimeError('version directive did not report only the T1OS version')

        result['checks']['t1os_version_only'] = True

        # verify multiline paste is staged and never executed immediately
        INPUTBUF = ''
        CURSORPOS = 0
        MULTILINES = []
        staged = stagepaste('tier\nhelp compare')

        if staged != 2 or MULTILINES != ['tier'] or INPUTBUF != 'help compare':
            raise RuntimeError('multiline paste was not staged for confirmation')

        if not cancelpaste() or MULTILINES or INPUTBUF:
            raise RuntimeError('multiline paste cancellation failed')

        result['checks']['paste_confirmation'] = True

        # verify connective file and tier forms preserve names containing spaces
        with open('connective source.txt', 'w') as stream:
            stream.write('connective file\n')

        rename(['connective', 'source.txt', 'to', 'connective', 'renamed.txt'])

        if not os.path.isfile('connective renamed.txt'):
            raise RuntimeError('connective file rename failed')

        copy(['connective', 'renamed.txt', 'to', 'connective', 'copied.txt'])

        if not os.path.isfile('connective copied.txt'):
            raise RuntimeError('connective file copy failed')

        os.makedirs('connective file destination', exist_ok=False)
        move(['connective', 'copied.txt', 'to', 'connective', 'file', 'destination'])

        if not os.path.isfile(os.path.join('connective file destination', 'connective copied.txt')):
            raise RuntimeError('connective file move failed')

        os.makedirs('connective source tier', exist_ok=False)
        renametier(['connective', 'source', 'tier', 'to', 'connective', 'renamed', 'tier'])

        if not os.path.isdir('connective renamed tier'):
            raise RuntimeError('connective tier rename failed')

        os.makedirs('connective tier destination', exist_ok=False)
        copytier(['connective', 'renamed', 'tier', 'to', 'connective', 'tier', 'destination'])

        if not os.path.isdir(os.path.join('connective tier destination', 'connective renamed tier')):
            raise RuntimeError('connective tier copy failed')

        os.makedirs('connective move source tier', exist_ok=False)
        os.makedirs('connective move destination', exist_ok=False)
        movetier(['connective', 'move', 'source', 'tier', 'to', 'connective', 'move', 'destination'])

        if not os.path.isdir(os.path.join('connective move destination', 'connective move source tier')):
            raise RuntimeError('connective tier move failed')

        result['checks']['connective_paths'] = True

        # verify previous-tier navigation and bounded recursive display
        os.makedirs('navigation one', exist_ok=False)
        os.makedirs('navigation two', exist_ok=False)
        PREVTIER = None
        changetier([os.path.join(root, 'navigation one')])
        changetier([os.path.join(root, 'navigation two')])
        changetier(['back'])

        if os.path.abspath(os.getcwd()) != os.path.abspath(os.path.join(root, 'navigation one')):
            raise RuntimeError('change tier back did not return to the previous tier')

        os.chdir(root)
        os.makedirs(os.path.join('recursive tier', 'child', 'deep'), exist_ok=False)

        with open(os.path.join('recursive tier', 'child', 'deep', 'hidden by depth.txt'), 'w') as stream:
            stream.write('depth diagnostic\n')

        SCROLL.clear()
        STYLES.clear()
        opentiers(['recursive', 'tier', 'up', 'to', '1', 'levels'])
        recursivetext = '\n'.join(str(line) for line in SCROLL)

        if 'child' not in recursivetext or 'hidden by depth.txt' in recursivetext:
            raise RuntimeError('recursive tier depth limit failed')

        result['checks']['navigation_and_depth'] = True

        # verify development inspection and safe text mutation directives
        with open('detail file.txt', 'w') as stream:
            stream.write('alpha alpha\n')

        SCROLL.clear()
        STYLES.clear()

        if showdetails(['detail', 'file.txt']) != 0:
            raise RuntimeError('show details failed')

        detailtext = '\n'.join(str(line) for line in SCROLL)

        if 'sha256' not in detailtext or 'detail file.txt' not in detailtext:
            raise RuntimeError('show details omitted file identity')

        shutil.copy2('detail file.txt', 'detail twin.txt')

        if compare(['detail', 'file.txt', 'with', 'detail', 'twin.txt']) != 0:
            raise RuntimeError('identical file comparison failed')

        if compare(['detail', 'file.txt', 'detail', 'twin.txt']) != 0:
            raise RuntimeError('connector-free file comparison failed')

        if replace(['alpha', 'with', 'beta', 'in', 'detail', 'file.txt']) == 0:
            raise RuntimeError('ambiguous replacement changed a file')

        with open('detail file.txt') as stream:

            if stream.read() != 'alpha alpha\n':
                raise RuntimeError('ambiguous replacement was not atomic')

        if replace(['all', 'alpha', 'with', 'beta', 'in', 'detail', 'file.txt']) != 0:
            raise RuntimeError('replace all failed')

        if replace(['all', 'beta', 'gamma', 'detail', 'file.txt']) != 0:
            raise RuntimeError('connector-free replace all failed')

        with open('detail file.txt') as stream:

            if stream.read() != 'gamma gamma\n':
                raise RuntimeError('connector-free replace all wrote unexpected content')

        if compare(['detail', 'file.txt', 'with', 'detail', 'twin.txt']) == 0:
            raise RuntimeError('different file comparison reported equality')

        result['checks']['details_compare_replace'] = True

        # verify syntax checks compile code without executing it
        with open('syntax good.py', 'w') as stream:
            stream.write("raise RuntimeError('must not execute')\n")

        with open('syntax bad.py', 'w') as stream:
            stream.write('if True print(1)\n')

        if checksyntax(['syntax', 'good.py']) != 0:
            raise RuntimeError('valid Python syntax check failed')

        if checksyntax(['syntax', 'bad.py']) == 0:
            raise RuntimeError('invalid Python syntax check passed')

        result['checks']['syntax_only'] = True

        # verify bounded reads preserve line identity and names containing spaces
        with open('read sample.txt', 'w') as stream:
            stream.write('one\ntwo\nthree\nfour\n')

        readresult = subprocess.run(
            [
                sys.executable,
                '/the one/build/read/read.py',
                'read', 'sample.txt', 'from', '2', 'to', '3', 'with', 'numbers',
            ],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        if readresult.returncode != 0 or readresult.stdout.splitlines() != ['2: two', '3: three']:
            raise RuntimeError(f'bounded read failed {readresult.stderr.strip()}')

        lastresult = subprocess.run(
            [sys.executable, '/the one/build/read/read.py', 'last', '2', 'from', 'read', 'sample.txt'],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        if lastresult.returncode != 0 or lastresult.stdout.splitlines() != ['three', 'four']:
            raise RuntimeError(f'last-line read failed {lastresult.stderr.strip()}')

        result['checks']['bounded_read'] = True

        # verify search expands the existing directive recursively and by item type
        searchroot = os.path.join(root, 'search tier')
        os.makedirs(os.path.join(searchroot, 'nested tier'), exist_ok=False)

        with open(os.path.join(searchroot, 'nested tier', 'matching file.py'), 'w') as stream:
            stream.write('deep needle\n')

        with open(os.path.join(searchroot, '.hidden match.py'), 'w') as stream:
            stream.write('hidden needle\n')

        searchenv = dict(os.environ)
        searchenv['T1OS_SEARCH_HIDDEN'] = '0'
        contentresult = subprocess.run(
            [sys.executable, '/the one/build/search/search.py', 'deep', 'needle', 'in', 'search', 'tier'],
            cwd=root,
            env=searchenv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        if contentresult.returncode != 0 or 'matching file.py:1 deep needle' not in contentresult.stdout:
            raise RuntimeError(f'recursive content search failed {contentresult.stderr.strip()}')

        exactresult = subprocess.run(
            [sys.executable, '/the one/build/search/search.py', 'exact', 'deep', 'needle', 'in', 'search', 'tier'],
            cwd=root,
            env=searchenv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        allresult = subprocess.run(
            [sys.executable, '/the one/build/search/search.py', 'all', 'deep', 'needle', 'in', 'search', 'tier'],
            cwd=root,
            env=searchenv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        if exactresult.returncode != 0 or allresult.returncode != 0 or 'matching file.py:1' not in exactresult.stdout or 'matching file.py:1' not in allresult.stdout:
            raise RuntimeError('exact or all-term content search failed')

        nameresult = subprocess.run(
            [sys.executable, '/the one/build/search/search.py', 'files', '*.py', 'in', 'search', 'tier'],
            cwd=root,
            env=searchenv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        if nameresult.returncode != 0 or 'matching file.py' not in nameresult.stdout or '.hidden match.py' in nameresult.stdout:
            raise RuntimeError(f'typed name search failed {nameresult.stderr.strip()}')

        result['checks']['expanded_search'] = True

        # verify the system check reports every component even when services are offline
        SCROLL.clear()
        STYLES.clear()
        systemcode = checksystem()
        systemtext = '\n'.join(str(line) for line in SCROLL)

        if systemcode not in (0, 1) or 'component' not in systemtext or 'storage' not in systemtext or 'role' not in systemtext:
            raise RuntimeError('system check did not produce a complete report')

        result['checks']['system_report'] = True

        # verify the operation service owns live, completed, waited, and killed state
        operationresult = subprocess.run(
            [sys.executable, '/the one/build/operations/operationsserver.py', 'diagnostic'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )

        operationlines = [line for line in operationresult.stdout.splitlines() if line.startswith('{')]
        operationactual = json.loads(operationlines[-1]) if operationlines else {}

        if operationresult.returncode != 0 or not operationactual.get('passed'):
            raise RuntimeError(f'operations diagnostic failed {operationactual.get("errors", operationresult.stderr.strip())}')

        result['checks']['operations_lifecycle'] = True

        # verify structured outcomes distinguish success and unknown directives
        SCROLL.clear()
        STYLES.clear()
        success = rundirective('help search', echo=False)
        failure = rundirective('directive that does not exist', echo=False)
        chained = runchain('help search; help compare', echo=False)

        if (
            not success.get('ok')
            or failure.get('ok')
            or len(chained) != 2
            or not all(item.get('ok') for item in chained)
            or not LASTDIRECTIVERESULT.get('ok')
        ):
            raise RuntimeError('structured directive outcomes failed')

        result['checks']['directive_outcomes'] = True

        suites = [
            diagnosticparsing(),
            diagnosticfiles(),
            diagnosticrubbish(),
            diagnosticsearch(),
            diagnosticoperations(),
            diagnosticdevelopment(),
            diagnosticdogfood(),
            diagnosticnetwork(),
        ]

        for suite in suites:

            name = str(suite.get('suite', 'unknown'))
            result['checks'][f'{name}_suite'] = bool(suite.get('passed'))

            for error in suite.get('errors', []):
                result['errors'].append(f'{name}: {error}')

        result['passed'] = all(result['checks'].values())

    except Exception as e:

        result['errors'].append(str(e))

    finally:

        try:

            arch.currentrole = 'architect'

            remainingids = set(str(item.get('id')) for item in rubbishapi.readindex())

            for rid in testrubbishids:

                if rid in remainingids:

                    rubbishapi.restorefromrubbishrid(rid)

        except Exception:

            pass

        try:

            arch.currentrole = originalrole

        except Exception:

            pass

        try:

            os.chdir(originalcwd)

        except Exception:

            pass

        shutil.rmtree(root, ignore_errors=True)

        SCROLL.clear()

        STYLES.clear()

        SCROLLOFF = 0

        HSCROLL = 0

    print(json.dumps(result, sort_keys=True, separators=(',', ':')))
    return 0 if result.get('passed') else 1


def consolediagnosticcommand():

    checks = {}

    try:
        display = ConsoleDisplay(3, 8)
        display.feed(b'abc\rX')
        checks['carriage'] = display.buffer.lines[0].text(False).startswith('Xbc')

        display.feed(b'\x1b[2;3H\x1b[31mR')
        cell = display.buffer.lines[1].cells[2]
        checks['cursor_addressing'] = cell.text == 'R'
        checks['colour'] = cell.style[0] == CONSOLE_PALETTE[1]

        display.feed('界'.encode('utf-8'))
        checks['wide_text'] = (
            display.buffer.lines[1].cells[3].width == 2 and
            display.buffer.lines[1].cells[4].width == 0
        )

        display.feed(b'\x1b[?2004h')
        checks['paste_mode'] = bool(display.bracketed_paste)
        display.feed(b'\x1b]2;diagnostic\x07')
        checks['title'] = display.title == 'diagnostic'

        preserved = display.primary.lines[0].text(False)
        display.feed(b'\x1b[?1049hsecondary\x1b[?1049l')
        checks['alternate_buffer'] = (
            not display.use_alternate and
            display.primary.lines[0].text(False) == preserved
        )

        scrolling = ConsoleDisplay(2, 6)
        scrolling.feed(b'one\r\ntwo\r\nthree')
        checks['scroll_history'] = len(scrolling.primary.history) >= 1
        scrolling.resize(4, 12)
        checks['resize'] = scrolling.rows == 4 and scrolling.cols == 12

    except Exception as error:
        checks['exception'] = str(error)

    passed = bool(checks) and all(value is True for value in checks.values())
    print(json.dumps({'passed': passed, 'checks': checks}, sort_keys=True, separators=(',', ':')))
    return 0 if passed else 1


# core function
def main(startupfile=None):

    global PREV_INPUTBUF, PREV_CURSORPOS, PREV_CURSOR_ON, DIRTY_PROMPT

    try:


        # load persisted Brick display preferences before window sizing
        loadbricksettings()

        # tie history saving to exit
        atexit.register(savehistory)

        # remove decoded image surfaces when brick exits
        atexit.register(viewcleanup)

        signal.signal(signal.SIGTERM, termhandler)

        signal.signal(signal.SIGINT, termhandler)

        # initialise window server connection and backing buffer
        initwindowmode()

        # initialise font subsystem
        initfont()

        # compute and cache text/layout measurements
        measurements()

        # load command history from storage
        inithistory()

        # initialise input state for the prompt
        initinput()

        # Array opens selected Python source in Brick's already-confined
        # interactive console.  The mutable source remains an argument to this
        # measured entrypoint and is never treated as a catalogue executable.
        if startupfile is not None:
            run([str(startupfile)])

        # draw the header line (cwd/status)
        drawheader()

        # record current time for cursor blink timing
        lastblink = time.monotonic()

        # set cursor initially visible
        cursor_on = True

        # main gui loop
        while RUNNING:

            # apply any coalesced resize once the user stops dragging
            applypendingresize()

            # drain active software output and observe process state
            consolepollstate()

            # redraw header if the current working directory changed
            checkcwdheader()

            # skip input/draw while a modal state is active
            if MODAL > 0:

                # sleep briefly to avoid busy spinning during modal
                time.sleep(0.010)
                continue

            # poll and process input events for this frame
            if consoleactive():
                pollserver()
                ranline = False
            else:
                ranline = handleinput(cursor_on)

            # if Enter executed a directive (and may have blocked)
            if ranline:

                # reset blink timing after returning from directive
                lastblink = time.monotonic()

                # force cursor visible after directive completes
                cursor_on = True

                # sync previous-input snapshot to current prompt buffer
                PREV_INPUTBUF = INPUTBUF

                # sync previous-cursor snapshot to current cursor position
                PREV_CURSORPOS = CURSORPOS

                # sync previous cursor visibility snapshot
                PREV_CURSOR_ON = cursor_on

                # mark prompt dirty so it will redraw next frame
                DIRTY_PROMPT = True

                # skip the rest of the frame and continue loop
                continue

            # Advance queued wheel movement a small eased step per frame.
            if not consoleactive():
                flushsmoothscroll()

            # update blink/rows/scroll/input dirty flags and return updated blink state
            cursor_on, lastblink = updatedirty(cursor_on, lastblink)

            # if either scroll region or prompt region needs redraw
            if DIRTY_SCROLL or DIRTY_PROMPT:

                # draw the frame and present it, including window damage reporting
                renderframe(cursor_on)

            else:

                # poll window server for incoming events
                pollserver()

            # submit a coalesced managed scene after the previous commit is acknowledged
            graphicspump()

            # sleep briefly to limit cpu usage and control frame pacing
            time.sleep(0.010)

    except Exception as e:

        # main loop errors
        guiprint(f'> gui loop error {e}', colour=ERRORCOLOUR)

    finally:


        # end active interactive software before releasing the window
        consoleclose()

        # save command history to storage
        savehistory()

        # close graphics/resources cleanly
        close()


def runfilewithoutwindow(path, arguments=None):

    """Run an Array-opened Python file without exposing Brick's own window."""

    target = os.path.abspath(os.path.normpath(str(path)))

    if not target.lower().endswith('.py') or not os.path.isfile(target):
        print(formatlog('brick', 'the selected python file is unavailable'), file=sys.stderr)
        return 1

    command = [os.path.realpath(sys.executable), '-u', target]
    command.extend(str(value) for value in (arguments or []))

    try:
        process = subprocess.Popen(command)
        opsregisterpid(
            process.pid,
            os.path.splitext(os.path.basename(target))[0],
            target,
            f'/the one/logs/{os.path.basename(target)}.log',
            'session',
            'front',
        )
        status = int(process.wait())
        opscompletepid(process.pid, status)
        return status

    except Exception as error:
        print(formatlog('brick', f'could not run selected python file — {error}'), file=sys.stderr)
        return 1



# execute main
if __name__ == '__main__':

    if len(sys.argv) > 1 and str(sys.argv[1]).strip().lower() == "execute":

        sys.exit(headlesscommand(sys.argv[2:]))

    if len(sys.argv) > 1 and str(sys.argv[1]).strip().lower() == "graphics-diagnostic":

        sys.exit(graphicsdiagnosticcommand())

    if len(sys.argv) > 1 and str(sys.argv[1]).strip().lower() == "view-diagnostic":

        sys.exit(viewdiagnosticcommand())

    if len(sys.argv) > 1 and str(sys.argv[1]).strip().lower() == "directive-diagnostic":

        if len(sys.argv) > 2:
            sys.exit(focuseddirectivediagnosticcommand(sys.argv[2]))

        sys.exit(directivediagnosticcommand())

    if len(sys.argv) > 1 and str(sys.argv[1]).strip().lower() == "console-diagnostic":

        sys.exit(consolediagnosticcommand())

    if len(sys.argv) >= 3 and str(sys.argv[1]).strip().lower() == "--run-file":

        if str(os.environ.get('BRICK_WINDOW', '1')).strip() == '0':
            sys.exit(runfilewithoutwindow(sys.argv[2], sys.argv[3:]))

        main(sys.argv[2])

    else:

        main()
