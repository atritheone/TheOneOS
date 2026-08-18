#!"/the one/software/python/bin/python" -B

"""
write.py

write is the graphical text editor for T1OS.
"""




## imports
import os
import sys
import time
import math
import json
import io
import socket
import select
import bisect
import heapq
import threading
import codecs
import subprocess
import re
import secrets
import stat
from collections import OrderedDict

sys.path.insert(0, '/the one/build')

from architect.architect import check
from GODDESS.GODDESS import formatlog
from exchange.exchange import exset, exget
from graphics.graphics import initbuffer, fillbufferfile, initttffont, drawtextttf, measuretext, clear, presentdirty, drawrect, setpixel, fillrect, fillrectfast, getdirty, resetdirty, measurelineadvances
from graphics.graphics import managedstate, managedconfigure, manageddisable, managedmarkdamage, managedclear, managedtick, managedsubmit, managedresponse, uiscalefactor, displayuiscale
import graphics.graphics as gfx



## globals

# misc
WRITEPATH = '/the one/build/write/write.py'
WRITELOGBASE = "/the one/logs"
WRITESETTINGSVERSION = 2
DEFAULTDIR = None
SESSIONIDENTITYFILE = "/the one/settings/session/identity.json"
SESSIONIDENTITYMAXBYTES = 1024
MAXDOCUMENTBYTES = 64 * 1024 * 1024
SESSIONUSERNAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,31}")

# sockets
SOCKPATH = '/.ephemeral/windowserver/accept.sock'
ws_sock = None
ws_inbuf = b''

# state
APP_RUNNING = False
HAS_FOCUS = True
INPUT_MODE = 'edit'
PROMPT_TEXT = ''
PROMPT_BUFFER = ''

# window
WINDOW_ID = None
POINTER_CURSOR_MODE = 'arrow'
BASE_WIN_W = 800
BASE_WIN_H = 600
WIN_W = BASE_WIN_W
WIN_H = BASE_WIN_H
WIN_FORMAT = 'BGRA32'
BUFFER_PATH = None

# font
FONT_PATH = '/the one/resources/fonts/atkinsonhyperlegiblenext.ttf'
FONT_SIZE_BASE = 14
FONT_SIZE = FONT_SIZE_BASE
DOC_FONTSTAMP = None

# layout
LINE_PAD = 6
LINE_HEIGHT = FONT_SIZE + LINE_PAD
MENUBAR_HEIGHT = 24
MARGIN_LEFT = 10
MARGIN_TOP = 10 + MENUBAR_HEIGHT
STATUSBAR_HEIGHT = 22
SHOW_STATUSBAR = True
CURSOR_WIDTH = 2
VISIBLE_LINES = 0
FIRST_VISIBLE_ROW = 0
FIRST_VISIBLE_X = 0
WORD_WRAP = False
TAB_WIDTH = 4
INDENT_USE_TABS = False
WRAP_CACHE_KEY = None
WRAP_CACHE_SEGMENTS = []
WRAP_LAYOUT_KEY = None
WRAP_LINE_SEGMENTS = []
WRAP_LINE_COUNTS = []
WRAP_COUNT_TREE = []
WRAP_DIRTY_ROWS = set()
WRAP_REFLOW_FROM = None
WRAP_LINE_CACHE = OrderedDict()
WRAP_LINE_CACHE_BYTES = 0
WRAP_LINE_CACHE_LIMIT = 16 * 1024 * 1024
WRAP_LINES_MEASURED = 0
DOCUMENT_REFLOW_ROW = None
LASTDRAWNROW = -1
LASTDRAWNCOL = -1
SCROLLSTEP = 3
PENDING_SCROLL = 0
LAST_SCROLL_FRAME = 0.0
SCROLL_MANAGED_INTERVAL = 1.0 / 60.0
SCROLL_CPU_INTERVAL = 1.0 / 60.0
SMOOTH_SCROLL_EASING = 0.25
SMOOTH_SCROLL_MAX_STEP = 6
INTERACTION_CPU_INTERVAL = 1.0 / 60.0
SCROLL_REDRAWS = 0
PENDING_INTERACTION_REDRAW = 0
LAST_INTERACTION_FRAME = 0.0
INTERACTION_REDRAWS = 0

# graphics
BASE_W = 1920
BASE_H = 1080
UISCALE = 1.0
SCREENSIZE = [0, 0]
BG_COLOR = (255, 255, 255)
TEXT_COLOR = 0x000000
STATUS_ERROR_COLOR = 0xFF0000
CURSOR_COLOR = (0, 0, 0)
MENUBAR_BG = (230, 230, 230)
MENU_TEXT = 0x000000
MENUBAR_TEXT = MENU_TEXT
MENU_BG = (230, 230, 230)
MENU_BORDER = (180, 180, 180)
MENU_HOVER_BG = (240, 240, 240)
MENU_ROW_OUTLINE = MENU_BORDER
MENU_DISABLED_TEXT = 0x888888
SCROLLBAR_BG_COLOR = (230, 230, 230)
SCROLLBAR_THUMB_COLOR = (160, 160, 160)
HSCROLL_BG_COLOR = SCROLLBAR_BG_COLOR
HSCROLL_THUMB_COLOR = SCROLLBAR_THUMB_COLOR
SELBACKGROUND = (0, 0, 0)

# managed graphics
GRAPHICSSCENE = []
GRAPHICSREBUILD = False
GRAPHICSCPUOVERRIDE = str(os.environ.get('T1OS_WRITE_GRAPHICS', '')).strip().lower() in ('cpu', 'off', '0', 'false')
GRAPHICSSTATE = managedstate(cpu=GRAPHICSCPUOVERRIDE)
GRAPHICS_RETRY_AT = 0.0
GRAPHICS_RETRY_COUNT = 0
GRAPHICS_RETRY_LIMIT = 3
GRAPHICS_RETRY_INTERVAL = 1.0

# menu
MENU_ITEM_H_BASE = 22
MENU_PAD_X_BASE = 10
MENU_PAD_Y_BASE = 0
CONTEXT_MENU_PAD_Y = 0
MENU_GAP_BASE = 16
MENU_ITEM_H = MENU_ITEM_H_BASE
MENU_PAD_X = MENU_PAD_X_BASE
MENU_PAD_Y = MENU_PAD_Y_BASE
MENU_GAP = MENU_GAP_BASE
MENUBAR_RECTS = {}
MENUBAR_OPEN = None
MENU_PANEL = None
MENU_HOVER_ACTION = None
CONTEXT_MENU_OPEN = False
CONTEXT_MENU_X = 0
CONTEXT_MENU_Y = 0
CONTEXT_MENU_PANEL = None
CONTEXT_MENU_HOVER_ACTION = None
CONTEXT_PASTE_AVAILABLE = False

# document
DOC_LINES = []
DOC_LINEW = []
DOC_MAXW = 0
DOC_MAXW_DIRTY = True
DOC_WIDTH_COUNTS = {}
DOC_WIDTH_HEAP = []
DOC_WIDTH_INDEX_ROW = 0
DOC_WIDTH_INDEX_ACTIVE = False
DOC_LINE_IDS = []
DOC_LINE_VERSIONS = []
NEXT_LINE_ID = 1
CUR_ROW = 0
CUR_COL = 0
IS_DIRTY = False
FILE_PATH = None
FILE_NAME = 'untitled.txt'
FILE_ENCODING = 'utf-8'
FILE_BOM = False
FILE_NEWLINE = '\n'
RECENT_FILES = []
RECENT_FILE_LIMIT = 8
OVERWRITE_MODE = False

# editor prompts and search
FIND_QUERY = ''
REPLACE_QUERY = ''
FIND_MATCH_CASE = False
REPLACE_ALL_PENDING = False
PENDING_DESTRUCTIVE_ACTION = None
AFTER_SAVE_ACTION = None
DIALOG_WAITING = False
DIALOG_ID = None
DIALOG_WIN = None
DIALOG_ACTION = None
DIALOG_PAYLOAD = None
DIALOG_SEQUENCE = 0
PICKER_VERSION = 0
PICKER_PENDING = None

# status
LAST_STATUS_MESSAGE = ''
LAST_STATUS_TIME = 0.0
CURSOR_VISIBLE = True
LAST_CURSOR_TOGGLE = 0.0

# scrollbars
SCROLLBAR_WIDTH = 12
SCROLLBAR_MARGIN = 2
SCROLLBAR_MIN_THUMB = 20
SCROLLBAR_DRAGGING = False
SCROLLBAR_DRAG_CURSOR_OFFSET = 0
HSCROLL_HEIGHT = SCROLLBAR_WIDTH
HSCROLL_MARGIN = SCROLLBAR_MARGIN
HSCROLL_MIN_THUMB = SCROLLBAR_MIN_THUMB
HSCROLL_DRAGGING = False
HSCROLL_DRAG_CURSOR_OFFSET = 0

# undo / redo
UNDO_STACK = []
REDO_STACK = []
UNDO_LIMIT = 200
UNDO_BYTE_LIMIT = 16 * 1024 * 1024
UNDO_BYTES = 0
CURRENT_REVISION = 0
SAVED_REVISION = 0
NEXT_REVISION = 1

# selection
SEL_ACTIVE = False
SEL_ANCHOR_ROW = 0
SEL_ANCHOR_COL = 0
SEL_ROW = 0
SEL_COL = 0
MOUSE_SELECTING = False
SEL_LAST_MOUSE_ROW = 0
SEL_LAST_MOUSE_COL = 0
SEL_PAD_Y = 2

# mouse / clicks
CLICKTIME = 0.0
CLICKCOUNT = 0
CLICKROW = -1
CLICKCOL = -1
CLICKTHRESH = 0.4

# rendering scheduler
RENDER_BATCH_DEPTH = 0
PENDING_RENDER_MODE = 0
PENDING_RENDER_HORIZONTAL = False
PENDING_RENDER_VERTICAL = False
LAST_PRESENTED_FIRST_ROW = None
LAST_PRESENTED_VIEWPORT = None

# asynchronous file I/O
FILE_IO_THREAD = None
FILE_IO_RESULT = None
FILE_IO_LOCK = threading.Lock()
FILE_IO_KIND = None

# opt-in performance telemetry
PERF_ENABLED = str(os.environ.get('T1OS_WRITE_PERF', '')).strip().lower() in ('1', 'true', 'yes', 'on')
PERF_SAMPLES = {}
PERF_SAMPLE_LIMIT = 512



## functions

# misc functions
def logmsg(text):

    try:

        print(f'{time.time():.6f} write {text}', file=sys.stderr, flush=True)

    except Exception:

        pass


def perfstart():

    if not PERF_ENABLED:
        return 0

    return time.monotonic_ns()


def perfrecord(name, started, **metadata):

    if not PERF_ENABLED or not started:
        return

    try:
        elapsed = (time.monotonic_ns() - int(started)) / 1000000.0
        samples = PERF_SAMPLES.setdefault(str(name), [])
        samples.append({
            'ms': elapsed,
            **metadata,
        })

        if len(samples) > PERF_SAMPLE_LIMIT:
            del samples[:len(samples) - PERF_SAMPLE_LIMIT]

    except Exception:
        pass


def perfsnapshot(reset=False):

    result = {}

    try:

        for name, values in PERF_SAMPLES.items():

            timings = sorted(float(value.get('ms', 0.0)) for value in values)

            if not timings:
                continue

            p95index = min(len(timings) - 1, int((len(timings) - 1) * 0.95))
            p99index = min(len(timings) - 1, int((len(timings) - 1) * 0.99))
            result[name] = {
                'count': len(timings),
                'average_ms': sum(timings) / len(timings),
                'p95_ms': timings[p95index],
                'p99_ms': timings[p99index],
                'maximum_ms': timings[-1],
            }

        if reset:
            PERF_SAMPLES.clear()

    except Exception:
        pass

    return result


def loadsettings():

    global WORD_WRAP, TAB_WIDTH, INDENT_USE_TABS, FONT_SIZE_BASE
    global RECENT_FILES, FIND_MATCH_CASE

    try:
        path = writesettingspath()
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
        )
        try:
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode) or
                metadata.st_uid != 1000 or
                metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH) or
                metadata.st_nlink != 1 or
                metadata.st_size > 65536
            ):
                raise PermissionError('unsafe Write settings file')
            raw = os.read(descriptor, 65537)
            if len(raw) > 65536:
                raise ValueError('Write settings file is too large')
            data = json.loads(raw.decode('utf-8', errors='strict'))
        finally:
            os.close(descriptor)

    except FileNotFoundError:

        return

    except Exception as e:

        logmsg(f'> error loading write settings {e}')

        return

    try:

        value = data.get('word_wrap') if isinstance(data, dict) else None

        if isinstance(value, bool):

            WORD_WRAP = value

        tabwidth = int(data.get('tab_width', TAB_WIDTH))

        if 1 <= tabwidth <= 16:
            TAB_WIDTH = tabwidth

        INDENT_USE_TABS = bool(data.get('indent_use_tabs', INDENT_USE_TABS))
        FIND_MATCH_CASE = bool(data.get('find_match_case', FIND_MATCH_CASE))
        fontsize = int(data.get('font_size', FONT_SIZE_BASE))

        if 8 <= fontsize <= 48:
            FONT_SIZE_BASE = fontsize

        recent = data.get('recent_files', [])

        if isinstance(recent, list):
            RECENT_FILES = [
                str(path)
                for path in recent
                if str(path).strip()
            ][:RECENT_FILE_LIMIT]

        gfx.TEXTTABWIDTH = int(TAB_WIDTH)

    except Exception as e:

        logmsg(f'> error applying write settings {e}')


def savesettings():

    data = {
        'version': WRITESETTINGSVERSION,
        'word_wrap': bool(WORD_WRAP),
        'tab_width': int(TAB_WIDTH),
        'indent_use_tabs': bool(INDENT_USE_TABS),
        'find_match_case': bool(FIND_MATCH_CASE),
        'font_size': int(FONT_SIZE_BASE),
        'recent_files': list(RECENT_FILES[:RECENT_FILE_LIMIT]),
    }

    try:
        payload = json.dumps(data, indent=2, sort_keys=True) + '\n'
        writeuserfilesnapshot(
            writesettingspath(),
            (payload,),
            'utf-8',
            False,
            '\n',
        )

    except Exception as e:

        logmsg(f'> error saving write settings {e}')


def setscreensize(w, h):

    global SCREENSIZE

    try:

        sw = int(w)
        sh = int(h)

    except Exception:

        return

    if sw < 1:
        sw = 1

    if sh < 1:
        sh = 1

    SCREENSIZE[0] = sw

    SCREENSIZE[1] = sh

    applyuiscale(sw, sh)

    return


def applyuiscale(w, h):

    global UISCALE, FONT_SIZE, LINE_PAD, LINE_HEIGHT, MENUBAR_HEIGHT, STATUSBAR_HEIGHT, MARGIN_LEFT, MARGIN_TOP, CURSOR_WIDTH, SCROLLBAR_WIDTH, HSCROLL_HEIGHT, MENU_ITEM_H, MENU_PAD_X, MENU_PAD_Y, MENU_GAP, MENU_ITEM_H_BASE, MENU_PAD_X_BASE, MENU_PAD_Y_BASE, MENU_GAP_BASE

    try:

        UISCALE = displayuiscale(w, h, uiscalefactor())

    except Exception:

        UISCALE = 1.0

    FONT_SIZE = max(8, int(FONT_SIZE_BASE * UISCALE))

    LINE_PAD = max(2, int(6 * UISCALE))

    LINE_HEIGHT = FONT_SIZE + LINE_PAD

    MENUBAR_HEIGHT = max(16, int(24 * UISCALE))

    STATUSBAR_HEIGHT = max(14, int(22 * UISCALE))

    MARGIN_LEFT = max(6, int(10 * UISCALE))

    MARGIN_TOP = MARGIN_LEFT + MENUBAR_HEIGHT

    CURSOR_WIDTH = max(1, int(2 * UISCALE))

    SCROLLBAR_WIDTH = max(8, int(12 * UISCALE))

    HSCROLL_HEIGHT = SCROLLBAR_WIDTH

    MENU_ITEM_H = max(12, int(MENU_ITEM_H_BASE * UISCALE))

    MENU_PAD_X = max(4, int(MENU_PAD_X_BASE * UISCALE))

    MENU_PAD_Y = max(0, int(MENU_PAD_Y_BASE * UISCALE))

    MENU_GAP = max(6, int(MENU_GAP_BASE * UISCALE))


# menu functions
def addrecentfile(path):

    global RECENT_FILES

    try:
        value = os.path.abspath(str(path))

        if not value:
            return

        RECENT_FILES = [
            entry
            for entry in RECENT_FILES
            if os.path.abspath(str(entry)) != value
        ]
        RECENT_FILES.insert(0, value)
        del RECENT_FILES[RECENT_FILE_LIMIT:]
        savesettings()

    except Exception as e:
        logmsg(f'> recent file update error {e}')


def menudefinitions():

    try:

        fileitems = [
            ('new', 'ctrl+n', 'file_new'),
            ('open', 'ctrl+o', 'file_open'),
            ('save', 'ctrl+s', 'file_save'),
            ('save as', 'ctrl+shift+s', 'file_saveas'),
            ('print', 'ctrl+p', 'file_print'),
        ]

        for index, path in enumerate(RECENT_FILES[:RECENT_FILE_LIMIT]):
            fileitems.append((
                f'open recent {index + 1}: {os.path.basename(path) or path}',
                '',
                f'file_recent_{index}',
            ))

        fileitems.extend([
            ('exit', '', 'file_exit'),
        ])

        edititems = [
            ('undo', 'ctrl+z', 'edit_undo'),
            ('redo', 'ctrl+y', 'edit_redo'),
            ('cut', 'ctrl+x', 'edit_cut'),
            ('copy', 'ctrl+c', 'edit_copy'),
            ('paste', 'ctrl+v', 'edit_paste'),
            ('find', 'ctrl+f', 'edit_find'),
            ('find next', 'f3', 'edit_find_next'),
            ('find previous', 'shift+f3', 'edit_find_previous'),
            ('replace', 'ctrl+h', 'edit_replace'),
            ('replace all', '', 'edit_replace_all'),
            ('go to line', 'ctrl+g', 'edit_goto'),
            ('duplicate line', 'ctrl+d', 'edit_duplicate_line'),
            ('delete line', 'ctrl+shift+k', 'edit_delete_line'),
            ('uppercase', '', 'edit_uppercase'),
            ('lowercase', '', 'edit_lowercase'),
            ('indent', 'tab', 'edit_indent'),
            ('outdent', 'shift+tab', 'edit_outdent'),
            ('select all', 'ctrl+a', 'edit_selectall'),
        ]

        optionsitems = [
            ((('[x] ' if WORD_WRAP else '[ ] ') + 'word wrap'), '', 'options_wordwrap'),
            ((('[x] ' if FIND_MATCH_CASE else '[ ] ') + 'match case'), '', 'options_match_case'),
            ((('[x] ' if INDENT_USE_TABS else '[ ] ') + 'indent with tabs'), '', 'options_indent_tabs'),
            (f'tab width: {TAB_WIDTH}', '', 'options_tab_width'),
            ('zoom in', 'ctrl++', 'options_zoom_in'),
            ('zoom out', 'ctrl+-', 'options_zoom_out'),
            ('reset zoom', 'ctrl+0', 'options_zoom_reset'),
            ((('[x] ' if OVERWRITE_MODE else '[ ] ') + 'overwrite mode'), 'insert', 'options_overwrite'),
        ]

        return {
            'file': fileitems,
            'edit': edititems,
            'options': optionsitems,
        }

    except Exception as e:

        logmsg(f'> menu definitions error {e}')
        return {'file': [], 'edit': []}


def contextmenudefinitions():

    return [
        ('undo', 'ctrl+z', 'edit_undo'),
        ('redo', 'ctrl+y', 'edit_redo'),
        ('cut', 'ctrl+x', 'edit_cut'),
        ('copy', 'ctrl+c', 'edit_copy'),
        ('paste', 'ctrl+v', 'edit_paste'),
        ('delete', 'delete', 'edit_delete_selection'),
        ('select all', 'ctrl+a', 'edit_selectall'),
    ]


def iscontextpointerbutton(button):

    try:
        # Windowserver maps evdev BTN_RIGHT to 2. Button 3 is accepted for
        # clients that use conventional left/middle/right numbering.
        return int(button) in (2, 3)
    except Exception:
        return False


def clipboardhastext():

    try:

        ok, state = exget()

        if not ok:
            return False

        return str(state.get('type', '')) in ('text', 'html') and bool(str(state.get('data', '')))

    except Exception:

        return False


def contextactionenabled(action):

    try:

        if action == 'edit_undo':
            return bool(UNDO_STACK)

        if action == 'edit_redo':
            return bool(REDO_STACK)

        if action in ('edit_cut', 'edit_copy', 'edit_delete_selection'):
            return hasselection()

        if action == 'edit_paste':
            return bool(CONTEXT_PASTE_AVAILABLE)

        if action == 'edit_selectall':
            return bool(DOC_LINES) and (len(DOC_LINES) > 1 or bool(str(DOC_LINES[0])))

        return True

    except Exception:

        return False


def runmenuaction(action):

    global APP_RUNNING, WORD_WRAP, FIRST_VISIBLE_ROW, FIRST_VISIBLE_X
    global FIND_MATCH_CASE, INDENT_USE_TABS, TAB_WIDTH, OVERWRITE_MODE

    try:

        if action == 'file_new':

            requestdestructiveaction('new')
            return

        if action == 'file_open':

            requestdestructiveaction('open')
            return

        if action == 'file_save':

            if FILE_PATH:

                savedocumenttofile(FILE_PATH)

            else:

                startsavepathprompt()

            redrawfull()
            return

        if action == 'file_saveas':

            startsavepathprompt()

            redrawfull()
            return

        if action == 'file_print':

            printdocument()
            redrawstatusbar()
            return

        if str(action).startswith('file_recent_'):

            index = int(str(action).rsplit('_', 1)[-1])

            if 0 <= index < len(RECENT_FILES):
                requestdestructiveaction(('open_recent', RECENT_FILES[index]))

            return

        if action == 'options_wordwrap':

            WORD_WRAP = not WORD_WRAP
            savesettings()
            FIRST_VISIBLE_X = 0
            invalidatewrapcache()
            FIRST_VISIBLE_ROW = cursorvisualindex(CUR_ROW, CUR_COL) if WORD_WRAP else CUR_ROW
            ensurecursorvisible()
            redrawfull()
            return

        if action == 'file_exit':

            requestdestructiveaction('exit')
            return

        if action == 'edit_find':
            starttextprompt('find', 'find ', FIND_QUERY)
            redrawfull()
            return

        if action == 'edit_find_next':
            findnext()
            redrawviewport()
            return

        if action == 'edit_find_previous':
            findnext(reverse=True)
            redrawviewport()
            return

        if action in ('edit_replace', 'edit_replace_all'):
            startreplaceprompt(replace_all=action == 'edit_replace_all')
            redrawfull()
            return

        if action == 'edit_goto':
            starttextprompt('goto_line', 'go to line ', str(CUR_ROW + 1))
            redrawfull()
            return

        if action == 'edit_duplicate_line':
            duplicatelines()
            ensurecursorvisible()
            redrawregionaroundcursororline()
            return

        if action == 'edit_delete_line':
            deletelines()
            ensurecursorvisible()
            redrawregionaroundcursororline()
            return

        if action == 'edit_uppercase':
            transformselection('upper')
            redrawregionaroundcursororline()
            return

        if action == 'edit_lowercase':
            transformselection('lower')
            redrawregionaroundcursororline()
            return

        if action in ('edit_indent', 'edit_outdent'):

            if handleindentation(outdent=action == 'edit_outdent'):
                ensurecursorvisible()
                redrawregionaroundcursororline()

            return

        if action == 'edit_undo':

            undo()

            clearselection()

            ensurecursorvisible()

            redrawfull()
            return

        if action == 'edit_redo':

            redo()

            clearselection()

            ensurecursorvisible()

            redrawfull()
            return

        if action == 'edit_cut':

            editcut()

            ensurecursorvisible()

            redrawfull()
            return

        if action == 'edit_copy':

            editcopy()

            redrawfull()
            return

        if action == 'edit_paste':

            editpaste()

            redrawfull()
            return

        if action == 'options_match_case':
            FIND_MATCH_CASE = not FIND_MATCH_CASE
            savesettings()
            redrawfull()
            return

        if action == 'options_indent_tabs':
            INDENT_USE_TABS = not INDENT_USE_TABS
            savesettings()
            redrawfull()
            return

        if action == 'options_tab_width':
            TAB_WIDTH = {2: 4, 4: 8, 8: 2}.get(int(TAB_WIDTH), 4)
            gfx.TEXTTABWIDTH = int(TAB_WIDTH)
            savesettings()
            invalidatewrapcache(drop_lines=True)
            docwidthreset()
            redrawfull()
            return

        if action == 'options_zoom_in':
            changezoom(1)
            return

        if action == 'options_zoom_out':
            changezoom(-1)
            return

        if action == 'options_zoom_reset':
            changezoom(0, reset=True)
            return

        if action == 'options_overwrite':
            OVERWRITE_MODE = not OVERWRITE_MODE
            redrawstatusbar()
            return

        if action == 'edit_delete_selection':

            if hasselection():
                deleteselection()
                ensurecursorvisible()

            redrawfull()
            return

        if action == 'edit_selectall':

            editselectall()

            redrawfull()
            return

    except Exception as e:

        logmsg(f'> menu action error {e}')

    return


def drawmenubar():

    global MENUBAR_RECTS

    try:

        fillrectfast(0, 0, WIN_W, MENUBAR_HEIGHT, MENUBAR_BG)

    except Exception as e:

        logmsg(f'> error drawing menubar bg {e}')
        return

    try:

        MENUBAR_RECTS = {}

        labels = ['file', 'edit', 'options']

        x = MARGIN_LEFT

        y = max(0, (MENUBAR_HEIGHT - FONT_SIZE) // 2)

        for lab in labels:

            drawtextttf(x, y, lab, MENUBAR_TEXT, FONT_SIZE)

            try:
                w = measuretext(lab, FONT_SIZE)
            except Exception:
                w = 0

            MENUBAR_RECTS[lab] = (int(x - 4), 0, int(w + 8), int(MENUBAR_HEIGHT))

            x = x + int(w) + MENU_GAP

    except Exception as e:

        logmsg(f'> error drawing menubar labels {e}')
        return

    return


def computemenupanel(menu_name):

    global MENU_PANEL

    try:

        MENU_PANEL = None

        if not menu_name:
            return None

        menus = menudefinitions()

        items = menus.get(menu_name, [])

        rect = MENUBAR_RECTS.get(menu_name, None)

        if not rect:
            return None

        mx, my, mw, mh = rect

        leftw = 0
        rightw = 0

        for label, shortcut, _ in items:

            try:
                lw = measuretext(str(label), FONT_SIZE)
            except Exception:
                lw = 0

            if lw > leftw:
                leftw = lw

            try:
                rw = measuretext(str(shortcut), FONT_SIZE)
            except Exception:
                rw = 0

            if rw > rightw:
                rightw = rw

        panel_w = int(MENU_PAD_X + leftw + 24 + rightw + MENU_PAD_X)

        panel_h = int((len(items) * MENU_ITEM_H) + (MENU_PAD_Y * 2))

        px = int(mx)
        py = int(MENUBAR_HEIGHT)

        if px + panel_w > WIN_W:
            px = max(0, WIN_W - panel_w)

        MENU_PANEL = (px, py, panel_w, panel_h, menu_name)

        return MENU_PANEL

    except Exception as e:

        logmsg(f'> menu panel compute error {e}')
        MENU_PANEL = None
        return None


def drawopenmenu():

    global MENU_PANEL

    if not MENUBAR_OPEN:
        MENU_PANEL = None
        return

    panel = computemenupanel(MENUBAR_OPEN)

    if not panel:
        return

    px, py, pw, ph, menu_name = panel

    try:

        fillrectfast(px, py, pw, ph, MENU_BG)

        drawrect(px, py, pw, ph, MENU_BORDER)

    except Exception as e:

        logmsg(f'> error drawing menu panel {e}')
        return

    try:

        menus = menudefinitions()
        items = menus.get(menu_name, [])

        y = py + MENU_PAD_Y

        for i, (label, shortcut, action) in enumerate(items):

            item_y = y + (i * MENU_ITEM_H)

            lx = px + MENU_PAD_X

            if action == MENU_HOVER_ACTION:
                hoverx = px + 1
                hoverwidth = max(1, pw - 2)
                fillrectfast(hoverx, item_y, hoverwidth, MENU_ITEM_H, MENU_HOVER_BG)
                fillrectfast(hoverx, item_y, hoverwidth, 1, MENU_ROW_OUTLINE)
                fillrectfast(hoverx, item_y + MENU_ITEM_H - 1, hoverwidth, 1, MENU_ROW_OUTLINE)

            drawtextttf(lx, item_y + max(0, (MENU_ITEM_H - FONT_SIZE) // 2), str(label), MENU_TEXT, FONT_SIZE)

            if shortcut:

                try:
                    sw = measuretext(str(shortcut), FONT_SIZE)
                except Exception:
                    sw = 0

                rx = (px + pw) - MENU_PAD_X - sw

                drawtextttf(rx, item_y + max(0, (MENU_ITEM_H - FONT_SIZE) // 2), str(shortcut), MENU_TEXT, FONT_SIZE)

            if i < len(items) - 1:
                fillrectfast(px, item_y + MENU_ITEM_H - 1, pw, 1, MENU_BORDER)

    except Exception as e:

        logmsg(f'> error drawing menu items {e}')

    return


def closemenu():

    global MENUBAR_OPEN
    global MENU_PANEL
    global MENU_HOVER_ACTION


    MENUBAR_OPEN = None

    MENU_PANEL = None
    MENU_HOVER_ACTION = None

    return


def computecontextpanel():

    global CONTEXT_MENU_PANEL

    try:

        if not CONTEXT_MENU_OPEN:
            CONTEXT_MENU_PANEL = None
            return None

        items = contextmenudefinitions()
        leftwidth = 0
        rightwidth = 0

        for label, shortcut, _ in items:

            leftwidth = max(leftwidth, int(measuretext(str(label), FONT_SIZE)))
            rightwidth = max(rightwidth, int(measuretext(str(shortcut), FONT_SIZE)))

        panelwidth = int(MENU_PAD_X + leftwidth + 24 + rightwidth + MENU_PAD_X)
        panelheight = int((len(items) * MENU_ITEM_H) + (CONTEXT_MENU_PAD_Y * 2))
        vx, vy, vw, vh = viewportgeometry()
        right = max(int(vx), int(vx + vw))
        bottom = max(int(vy), int(vy + vh))
        panelx = max(int(vx), min(int(CONTEXT_MENU_X), right - panelwidth))
        panely = max(int(vy), min(int(CONTEXT_MENU_Y), bottom - panelheight))
        CONTEXT_MENU_PANEL = (panelx, panely, panelwidth, panelheight)
        return CONTEXT_MENU_PANEL

    except Exception as e:

        logmsg(f'> context menu panel compute error {e}')
        CONTEXT_MENU_PANEL = None
        return None


def opencontextmenu(x, y):

    global CONTEXT_MENU_OPEN
    global CONTEXT_MENU_X
    global CONTEXT_MENU_Y
    global CONTEXT_PASTE_AVAILABLE
    global CONTEXT_MENU_HOVER_ACTION

    closemenu()
    CONTEXT_MENU_OPEN = True
    CONTEXT_MENU_X = int(x)
    CONTEXT_MENU_Y = int(y)
    CONTEXT_MENU_HOVER_ACTION = None
    CONTEXT_PASTE_AVAILABLE = clipboardhastext()
    computecontextpanel()
    return True


def closecontextmenu():

    global CONTEXT_MENU_OPEN
    global CONTEXT_MENU_PANEL
    global CONTEXT_PASTE_AVAILABLE
    global CONTEXT_MENU_HOVER_ACTION

    CONTEXT_MENU_OPEN = False
    CONTEXT_MENU_PANEL = None
    CONTEXT_MENU_HOVER_ACTION = None
    CONTEXT_PASTE_AVAILABLE = False


def contextmenuhit(x, y):

    try:

        panel = CONTEXT_MENU_PANEL if CONTEXT_MENU_OPEN else None

        if not panel:
            return None, False

        px, py, pw, ph = panel

        if not pointinrect(x, y, panel):
            return None, False

        relativey = int(y) - (int(py) + int(CONTEXT_MENU_PAD_Y))

        if relativey < 0:
            return None, True

        index = relativey // int(MENU_ITEM_H)
        items = contextmenudefinitions()

        if 0 <= index < len(items):
            action = items[int(index)][2]
            return action, True

        return None, True

    except Exception:

        return None, False


def updatecontextmenuhover(x, y):

    global CONTEXT_MENU_HOVER_ACTION

    action, inside = contextmenuhit(x, y) if CONTEXT_MENU_OPEN else (None, False)

    if not inside:
        action = None

    if action == CONTEXT_MENU_HOVER_ACTION:
        return

    CONTEXT_MENU_HOVER_ACTION = action
    redrawfull()


def updatemenuhover(x, y):

    global MENUBAR_OPEN
    global MENU_HOVER_ACTION

    zone, name, action = menuhit(x, y) if MENUBAR_OPEN else (None, None, None)

    # Once a menu has been opened by clicking, moving across the menu bar
    # should switch dropdowns without requiring another click.
    if zone == 'menubar' and name and name != MENUBAR_OPEN:
        MENUBAR_OPEN = name
        MENU_HOVER_ACTION = None
        redrawfull()
        return

    if zone != 'menu':
        action = None

    if action == MENU_HOVER_ACTION:
        return

    MENU_HOVER_ACTION = action
    redrawfull()


def drawcontextmenu():

    if not CONTEXT_MENU_OPEN:
        return

    panel = computecontextpanel()

    if not panel:
        return

    px, py, pw, ph = panel

    try:

        fillrectfast(px, py, pw, ph, MENU_BG)
        drawrect(px, py, pw, ph, MENU_BORDER)

        items = contextmenudefinitions()

        for index, (label, shortcut, action) in enumerate(items):

            itemy = py + CONTEXT_MENU_PAD_Y + index * MENU_ITEM_H
            texty = itemy + max(0, (MENU_ITEM_H - FONT_SIZE) // 2)
            colour = MENU_TEXT

            if action == CONTEXT_MENU_HOVER_ACTION:
                hoverx = px + 1
                hoverwidth = max(1, pw - 2)
                fillrectfast(hoverx, itemy, hoverwidth, MENU_ITEM_H, MENU_HOVER_BG)
                fillrectfast(hoverx, itemy, hoverwidth, 1, MENU_ROW_OUTLINE)
                fillrectfast(hoverx, itemy + MENU_ITEM_H - 1, hoverwidth, 1, MENU_ROW_OUTLINE)

            drawtextttf(px + MENU_PAD_X, texty, str(label), colour, FONT_SIZE)

            if shortcut:
                width = int(measuretext(str(shortcut), FONT_SIZE))
                drawtextttf(px + pw - MENU_PAD_X - width, texty, str(shortcut), colour, FONT_SIZE)

            if index < len(items) - 1:
                fillrectfast(px, itemy + MENU_ITEM_H - 1, pw, 1, MENU_BORDER)

    except Exception as e:

        logmsg(f'> error drawing context menu {e}')


def pointinrect(x, y, rect):

    try:

        rx, ry, rw, rh = rect

        if x >= rx and x < rx + rw and y >= ry and y < ry + rh:
            return True

    except Exception:
        return False

    return False


def menuhit(x, y):

    try:

        if y < MENUBAR_HEIGHT:

            for name, rect in MENUBAR_RECTS.items():

                if pointinrect(x, y, rect):

                    return ('menubar', name, None)

            return ('menubar', None, None)

        if MENUBAR_OPEN and MENU_PANEL:

            px, py, pw, ph, menu_name = MENU_PANEL

            if x >= px and x < px + pw and y >= py and y < py + ph:

                rel_y = y - (py + MENU_PAD_Y)

                if rel_y < 0:
                    return ('menu', menu_name, None)

                idx = rel_y // MENU_ITEM_H

                menus = menudefinitions()
                items = menus.get(menu_name, [])

                if idx >= 0 and idx < len(items):

                    _, _, action = items[int(idx)]

                    return ('menu', menu_name, action)

                return ('menu', menu_name, None)

        return (None, None, None)

    except Exception as e:

        logmsg(f'> menu hit error {e}')
        return (None, None, None)


# selection functions
def clearselection():

    try:

        # clear active selection flag
        global SEL_ACTIVE
        SEL_ACTIVE = False

        # align anchor to caret
        global SEL_ANCHOR_ROW, SEL_ANCHOR_COL
        SEL_ANCHOR_ROW = CUR_ROW
        SEL_ANCHOR_COL = CUR_COL

        # align active end to caret
        global SEL_ROW, SEL_COL
        SEL_ROW = CUR_ROW
        SEL_COL = CUR_COL

    except Exception as e:

        # unexpected selection clear error
        print(formatlog('write', f'selection clear error {e}'))


def setselectionanchor(row, col):

    try:

        # normalise incoming caret position
        nrow, ncol = normalisecaret(row, col)

        # set anchor position
        global SEL_ANCHOR_ROW, SEL_ANCHOR_COL
        SEL_ANCHOR_ROW = nrow
        SEL_ANCHOR_COL = ncol

        # initialise active end to anchor
        global SEL_ROW, SEL_COL
        SEL_ROW = nrow
        SEL_COL = ncol

        # do not activate selection yet
        global SEL_ACTIVE
        SEL_ACTIVE = False

    except Exception as e:

        # unexpected anchor set error
        print(formatlog('write', f'selection anchor error {e}'))


def updateselectionend(row, col):

    try:

        # normalise incoming caret position
        nrow, ncol = normalisecaret(row, col)

        # update active end
        global SEL_ROW, SEL_COL
        SEL_ROW = nrow
        SEL_COL = ncol

        # activate selection only if anchor differs
        global SEL_ACTIVE
        SEL_ACTIVE = not (
            SEL_ANCHOR_ROW == SEL_ROW and
            SEL_ANCHOR_COL == SEL_COL
        )

    except Exception as e:

        # unexpected selection update error
        print(formatlog('write', f'selection update error {e}'))


def selectionbounds():

    try:

        # fetch anchor and active end
        ar = SEL_ANCHOR_ROW
        ac = SEL_ANCHOR_COL
        br = SEL_ROW
        bc = SEL_COL

        # anchor comes before end
        if (ar < br) or (ar == br and ac <= bc):

            return ar, ac, br, bc

        # anchor comes after end
        return br, bc, ar, ac

    except Exception as e:

        # unexpected bounds error
        print(formatlog('write', f'selection bounds error {e}'))
        return 0, 0, 0, 0


def hasselection():

    try:

        # inactive selection
        if not SEL_ACTIVE:
            return False

        # get ordered bounds
        sr, sc, er, ec = selectionbounds()

        # empty selection
        if sr == er and sc == ec:
            return False

        return True

    except Exception as e:

        # unexpected selection check error
        print(formatlog('write', f'selection check error {e}'))
        return False


def positioninselection(row, col):

    try:

        if not hasselection():
            return False

        sr, sc, er, ec = selectionbounds()
        row = int(row)
        col = int(col)

        if row < sr or row > er:
            return False

        if sr == er:
            return row == sr and sc <= col < ec

        if row == sr:
            return col >= sc

        if row == er:
            return col < ec

        return True

    except Exception:

        return False


def normalisecaret(row, col):

    try:

        # clamp row
        if row < 0:
            row = 0

        if row >= len(DOC_LINES):
            row = len(DOC_LINES) - 1

        # fetch line length
        line = DOC_LINES[row]
        linelen = len(line)

        # clamp column
        if col < 0:
            col = 0

        if col > linelen:
            col = linelen

        return row, col

    except Exception as e:

        # unexpected caret normalisation error
        print(formatlog('write', f'caret normalise error {e}'))
        return 0, 0


def iswordchar(ch):

    try:

        if ch is None:
            return False

        c = str(ch)

        if c == '':
            return False

        if c.isalnum():
            return True

        if c == '_' or c == "'":
            return True

        return False

    except Exception:
        return False


def selectwordat(row, col):

    global DOC_LINES
    global CUR_ROW
    global CUR_COL

    try:

        if not DOC_LINES:
            return

        if row < 0:
            row = 0

        if row >= len(DOC_LINES):
            row = len(DOC_LINES) - 1

        line = str(DOC_LINES[row])

        if col < 0:
            col = 0

        if col > len(line):
            col = len(line)

        idx = col

        if idx >= len(line) and len(line) > 0:
            idx = len(line) - 1

        # if click is on whitespace, prefer the next word; otherwise fall back to previous
        if len(line) > 0 and (idx < len(line)) and (not iswordchar(line[idx])):

            j = idx

            while j < len(line) and (not iswordchar(line[j])):
                j += 1

            if j < len(line):
                idx = j
            else:
                j = idx - 1
                while j >= 0 and (not iswordchar(line[j])):
                    j -= 1
                if j >= 0:
                    idx = j
                else:
                    # no word on this line
                    setselectionanchor(row, col)
                    updateselectionend(row, col)
                    return

        # expand to word boundaries
        s = idx
        while s > 0 and iswordchar(line[s - 1]):
            s -= 1

        e = idx
        while e < len(line) and iswordchar(line[e]):
            e += 1

        # include trailing space after the word if present
        if e < len(line) and line[e] == ' ':
            e += 1

        setselectionanchor(row, s)
        updateselectionend(row, e)

        CUR_ROW = row
        CUR_COL = e

    except Exception as e:

        logmsg(f'> select word error {e}')

    return


def selectline(row):

    global DOC_LINES
    global CUR_ROW
    global CUR_COL

    try:

        if not DOC_LINES:
            return

        if row < 0:
            row = 0

        if row >= len(DOC_LINES):
            row = len(DOC_LINES) - 1

        line = str(DOC_LINES[row])
        endcol = len(line)

        setselectionanchor(row, 0)
        updateselectionend(row, endcol)

        CUR_ROW = row
        CUR_COL = endcol

    except Exception as e:

        logmsg(f'> select line error {e}')

    return


def nextlineid():

    global NEXT_LINE_ID

    value = int(NEXT_LINE_ID)
    NEXT_LINE_ID += 1
    return value


def documentmetadatareset():

    global DOC_LINE_IDS, DOC_LINE_VERSIONS, NEXT_LINE_ID
    global DOCUMENT_REFLOW_ROW

    DOC_LINE_IDS = []
    DOC_LINE_VERSIONS = []
    NEXT_LINE_ID = 1
    DOCUMENT_REFLOW_ROW = None

    for _ in DOC_LINES:
        DOC_LINE_IDS.append(nextlineid())
        DOC_LINE_VERSIONS.append(0)

    invalidatewrapcache(drop_lines=True)


def documentmetadataensure():

    if len(DOC_LINE_IDS) == len(DOC_LINES) and len(DOC_LINE_VERSIONS) == len(DOC_LINES):
        return

    documentmetadatareset()


def wraptreebuild():

    global WRAP_COUNT_TREE

    count = len(WRAP_LINE_COUNTS)
    WRAP_COUNT_TREE = [0] * (count + 1)

    for index, value in enumerate(WRAP_LINE_COUNTS, 1):

        cursor = index

        while cursor <= count:
            WRAP_COUNT_TREE[cursor] += max(1, int(value))
            cursor += cursor & -cursor


def wraptreeupdate(row, delta):

    cursor = int(row) + 1

    while cursor < len(WRAP_COUNT_TREE):
        WRAP_COUNT_TREE[cursor] += int(delta)
        cursor += cursor & -cursor


def wraptreeprefix(row):

    cursor = max(0, min(len(WRAP_LINE_COUNTS), int(row)))
    total = 0

    while cursor > 0:
        total += int(WRAP_COUNT_TREE[cursor])
        cursor -= cursor & -cursor

    return total


def wraptreetotal():

    return wraptreeprefix(len(WRAP_LINE_COUNTS))


def wraptreefind(index):

    if not WRAP_LINE_COUNTS:
        return 0

    target = max(0, min(max(0, wraptreetotal() - 1), int(index)))
    position = 0
    accumulated = 0
    bit = 1 << max(0, (len(WRAP_COUNT_TREE) - 1).bit_length() - 1)

    while bit:

        candidate = position + bit

        if candidate < len(WRAP_COUNT_TREE) and accumulated + WRAP_COUNT_TREE[candidate] <= target:
            position = candidate
            accumulated += WRAP_COUNT_TREE[candidate]

        bit >>= 1

    return min(len(WRAP_LINE_COUNTS) - 1, position)


def wrapcacheput(key, segments, line):

    global WRAP_LINE_CACHE_BYTES

    value = tuple((int(start), int(end)) for start, end in segments)
    size = max(64, len(str(line)) + (len(value) * 24))

    previous = WRAP_LINE_CACHE.pop(key, None)

    if previous is not None:
        WRAP_LINE_CACHE_BYTES -= int(previous[1])

    WRAP_LINE_CACHE[key] = (value, size)
    WRAP_LINE_CACHE_BYTES += size

    while WRAP_LINE_CACHE and WRAP_LINE_CACHE_BYTES > WRAP_LINE_CACHE_LIMIT:
        _, removed = WRAP_LINE_CACHE.popitem(last=False)
        WRAP_LINE_CACHE_BYTES -= int(removed[1])

    return list(value)


def wrapline(row, width):

    global WRAP_LINES_MEASURED

    documentmetadataensure()
    row = max(0, min(len(DOC_LINES) - 1, int(row)))
    line = str(DOC_LINES[row])
    lineid = DOC_LINE_IDS[row]
    version = DOC_LINE_VERSIONS[row]
    key = (int(lineid), int(version), int(FONT_SIZE), int(width), str(FONT_PATH))
    cached = WRAP_LINE_CACHE.get(key)

    if cached is not None:
        WRAP_LINE_CACHE.move_to_end(key)
        return list(cached[0])

    WRAP_LINES_MEASURED += 1

    if not line:
        return wrapcacheput(key, [(0, 0)], line)

    advances = measurelineadvances(('wrap-line', lineid, version), line, FONT_SIZE, FONT_PATH)

    if len(advances) != len(line):
        return wrapcacheput(key, [(0, len(line))], line)

    segments = []
    start = 0

    while start < len(line):

        startx = advances[start - 1] if start > 0 else 0
        limitx = startx + int(width)
        end = bisect.bisect_right(advances, limitx, lo=start)

        if end <= start:
            end = start + 1

        if end < len(line):

            wordend = end

            while wordend > start and not line[wordend - 1].isspace():
                wordend -= 1

            if wordend > start:
                end = wordend

        segments.append((start, end))
        start = end

    return wrapcacheput(key, segments or [(0, 0)], line)


def wraplayoutwidth():

    _, _, width, _ = viewportgeometry_noscrollbars()
    return max(1, int(width) - int(SCROLLBAR_WIDTH))


def ensurewrapindex():

    global WRAP_LAYOUT_KEY, WRAP_LINE_SEGMENTS, WRAP_LINE_COUNTS
    global WRAP_REFLOW_FROM, WRAP_CACHE_KEY, WRAP_CACHE_SEGMENTS
    global WRAP_DIRTY_ROWS

    if not WORD_WRAP:
        return

    documentmetadataensure()
    width = wraplayoutwidth()
    layoutkey = (int(FONT_SIZE), int(width), str(FONT_PATH))
    fullbuild = (
        WRAP_LAYOUT_KEY != layoutkey
        or len(WRAP_LINE_SEGMENTS) != len(DOC_LINES)
        or len(WRAP_LINE_COUNTS) != len(DOC_LINES)
    )

    if fullbuild:
        WRAP_LAYOUT_KEY = layoutkey
        WRAP_LINE_SEGMENTS = [None] * len(DOC_LINES)
        WRAP_LINE_COUNTS = [1] * len(DOC_LINES)
        wraptreebuild()
        WRAP_REFLOW_FROM = None
        WRAP_DIRTY_ROWS = set(range(len(DOC_LINES)))

    dirtyrows = sorted(WRAP_DIRTY_ROWS)
    WRAP_DIRTY_ROWS.clear()

    for row in dirtyrows:

        if row < 0 or row >= len(DOC_LINES) or WRAP_LINE_SEGMENTS[row] is not None:
            continue

        oldcount = max(1, int(WRAP_LINE_COUNTS[row]))
        segments = wrapline(row, width)
        newcount = max(1, len(segments))
        WRAP_LINE_SEGMENTS[row] = segments
        WRAP_LINE_COUNTS[row] = newcount

        if newcount != oldcount:
            visualstart = wraptreeprefix(row)
            wraptreeupdate(row, newcount - oldcount)

            if not fullbuild:

                if WRAP_REFLOW_FROM is None:
                    WRAP_REFLOW_FROM = visualstart
                else:
                    WRAP_REFLOW_FROM = min(int(WRAP_REFLOW_FROM), visualstart)

    WRAP_CACHE_KEY = None
    WRAP_CACHE_SEGMENTS = []


def wrapmetadatareplace(start, removed, replacement_count):

    global WRAP_LINE_SEGMENTS, WRAP_LINE_COUNTS, WRAP_REFLOW_FROM
    global WRAP_DIRTY_ROWS

    start = max(0, int(start))
    removed = max(0, int(removed))
    replacement_count = max(1, int(replacement_count))

    if len(WRAP_LINE_SEGMENTS) != len(DOC_LINES) - replacement_count + removed:
        invalidatewrapcache(drop_lines=True)
        return

    visualstart = wraptreeprefix(min(start, len(WRAP_LINE_COUNTS)))
    oldcounts = WRAP_LINE_COUNTS[start:start + removed]
    WRAP_LINE_SEGMENTS[start:start + removed] = [None] * replacement_count

    if removed == replacement_count:
        replacementcounts = list(oldcounts)
    else:
        replacementcounts = [oldcounts[0] if oldcounts else 1]
        replacementcounts.extend([1] * (replacement_count - 1))

    WRAP_LINE_COUNTS[start:start + removed] = replacementcounts

    if removed != replacement_count:
        wraptreebuild()
    shifted = set()

    for row in WRAP_DIRTY_ROWS:

        if row < start:
            shifted.add(row)
        elif row >= start + removed:
            shifted.add(row - removed + replacement_count)

    shifted.update(range(start, start + replacement_count))
    WRAP_DIRTY_ROWS = shifted

    if removed != replacement_count:

        if WRAP_REFLOW_FROM is None:
            WRAP_REFLOW_FROM = visualstart
        else:
            WRAP_REFLOW_FROM = min(int(WRAP_REFLOW_FROM), visualstart)


def invalidatewrapcache(drop_lines=False):

    global WRAP_CACHE_KEY, WRAP_CACHE_SEGMENTS, WRAP_LAYOUT_KEY
    global WRAP_LINE_SEGMENTS, WRAP_LINE_COUNTS, WRAP_COUNT_TREE, WRAP_REFLOW_FROM
    global WRAP_DIRTY_ROWS

    WRAP_CACHE_KEY = None
    WRAP_CACHE_SEGMENTS = []
    WRAP_LAYOUT_KEY = None
    WRAP_REFLOW_FROM = None
    WRAP_DIRTY_ROWS = set()

    if drop_lines:
        WRAP_LINE_SEGMENTS = []
        WRAP_LINE_COUNTS = []
        WRAP_COUNT_TREE = []


def wrapsegments():

    global WRAP_CACHE_KEY, WRAP_CACHE_SEGMENTS

    if not WORD_WRAP:
        return [(row, 0, len(str(line))) for row, line in enumerate(DOC_LINES)]

    try:
        ensurewrapindex()
        key = (
            WRAP_LAYOUT_KEY,
            int(CURRENT_REVISION),
            len(DOC_LINES),
            wraptreetotal(),
        )

        if WRAP_CACHE_KEY == key:
            return WRAP_CACHE_SEGMENTS

        segments = []

        for row, values in enumerate(WRAP_LINE_SEGMENTS):

            for start, end in values or [(0, 0)]:
                segments.append((row, start, end))

        WRAP_CACHE_KEY = key
        WRAP_CACHE_SEGMENTS = segments or [(0, 0, 0)]
        return WRAP_CACHE_SEGMENTS

    except Exception as e:
        logmsg(f'> error building word wrap layout {e}')
        return [(row, 0, len(str(line))) for row, line in enumerate(DOC_LINES)] or [(0, 0, 0)]


def displaylinecount():

    if not WORD_WRAP:
        return len(DOC_LINES)

    ensurewrapindex()
    return wraptreetotal()


def displaysegment(index):

    if not WORD_WRAP:

        if not DOC_LINES:
            return 0, 0, 0

        row = max(0, min(len(DOC_LINES) - 1, int(index)))
        return row, 0, len(str(DOC_LINES[row]))

    ensurewrapindex()

    if not WRAP_LINE_COUNTS:
        return 0, 0, 0

    index = max(0, min(max(0, wraptreetotal() - 1), int(index)))
    row = wraptreefind(index)
    offset = index - wraptreeprefix(row)
    values = WRAP_LINE_SEGMENTS[row] or [(0, 0)]
    start, end = values[max(0, min(len(values) - 1, offset))]
    return row, start, end


def cursorvisualindex(row, col):

    if not WORD_WRAP:
        return int(row)

    ensurewrapindex()

    if not DOC_LINES:
        return 0

    row = max(0, min(len(DOC_LINES) - 1, int(row)))
    line = str(DOC_LINES[row])
    col = max(0, min(len(line), int(col)))
    values = WRAP_LINE_SEGMENTS[row] or [(0, 0)]
    local = len(values) - 1

    for index, (_, end) in enumerate(values):

        if col < end or (col == end and end == len(line)):
            local = index
            break

    return wraptreeprefix(row) + local


def linecacheidentity(row, purpose, segment_start=0):

    try:
        documentmetadataensure()
        row = int(row)

        if 0 <= row < len(DOC_LINE_IDS):
            return (
                str(purpose),
                int(DOC_LINE_IDS[row]),
                int(DOC_LINE_VERSIONS[row]),
                int(segment_start),
            )

    except Exception:
        pass

    return (str(purpose), int(row), int(segment_start))


def pointtodocpos(x, y):

    try:

        # empty document safety
        if not DOC_LINES:
            return 0, 0

        # map y to a logical row or a wrapped visual segment
        if y < MARGIN_TOP:
            displayrow = FIRST_VISIBLE_ROW
        else:
            displayrow = FIRST_VISIBLE_ROW + ((y - MARGIN_TOP) // LINE_HEIGHT)

        if WORD_WRAP:
            row, segstart, segend = displaysegment(displayrow)
        else:
            row, segstart, segend = displayrow, 0, None

        # clamp row
        if row < 0:
            row = 0

        if row >= len(DOC_LINES):
            row = len(DOC_LINES) - 1

        # get line text
        try:
            line = str(DOC_LINES[row])
        except Exception:
            line = ''

        # map x to document-space x, respecting horizontal scroll
        xdoc = x - MARGIN_LEFT + (0 if WORD_WRAP else FIRST_VISIBLE_X)

        if xdoc < 0:
            xdoc = 0

        # fast column find using cached advances from graphics
        try:

            segment = line[segstart:segend]
            purpose = 'hit-wrap' if WORD_WRAP else 'metrics'
            advances = measurelineadvances(linecacheidentity(row, purpose, segstart), segment, FONT_SIZE, FONT_PATH)

        except Exception:

            advances = []

        try:

            if not advances:

                if xdoc <= 0:
                    return row, segstart

                return row, segend if segend is not None else len(line)

        except Exception:

            return row, 0

        lo = 0
        hi = len(advances) - 1
        col = len(advances)

        while lo <= hi:

            mid = (lo + hi) // 2

            if advances[mid] >= xdoc:

                col = mid
                hi = mid - 1

            else:

                lo = mid + 1

        return row, min(segend if segend is not None else len(line), segstart + col)

    except Exception as e:

        logmsg(f'> point to doc position error {e}')
        return 0, 0


def visiblelineslice(row, line_text, xbase, clipx, clipwidth, segment_start=0, fully_visible=False):

    try:

        line = str(line_text)
        clipwidth = max(0, int(clipwidth))

        if not line or clipwidth <= 0:
            return '', int(xbase), int(segment_start)

        purpose = 'visible-wrap' if WORD_WRAP else 'metrics'
        advances = measurelineadvances(
            linecacheidentity(row, purpose, segment_start),
            line,
            FONT_SIZE,
            FONT_PATH,
        )

        if len(advances) != len(line):
            return line, int(xbase), int(segment_start)

        leftdistance = int(clipx) - int(xbase)
        rightdistance = leftdistance + clipwidth
        start = bisect.bisect_right(advances, leftdistance)
        end = min(len(line), bisect.bisect_left(advances, rightdistance) + 1)

        # CPU text drawing has no clip rectangle. Do not return the first
        # partially visible glyph on that path or it can paint into the left
        # gutter while horizontally scrolling. Managed text has an exact clip.
        if fully_visible and start < end:
            startx = int(xbase) + (advances[start - 1] if start > 0 else 0)

            if startx < int(clipx):
                start += 1

        if end <= start:
            return '', int(xbase), int(segment_start) + start

        startx = int(xbase) + (advances[start - 1] if start > 0 else 0)
        return line[start:end], int(startx), int(segment_start) + start

    except Exception:

        return str(line_text), int(xbase), int(segment_start)


def lineadvanceat(row, line_text, col, segment_start=0):

    try:

        line = str(line_text)
        col = max(0, min(len(line), int(col)))
        segment_start = max(0, min(col, int(segment_start)))

        if col <= segment_start:
            return 0

        purpose = 'line-wrap' if WORD_WRAP else 'metrics'
        advances = measurelineadvances(
            linecacheidentity(row, purpose, segment_start),
            line,
            FONT_SIZE,
            FONT_PATH,
        )

        if len(advances) == len(line):
            endx = advances[col - 1]
            startx = advances[segment_start - 1] if segment_start > 0 else 0
            return int(endx) - int(startx)

        return int(measuretext(line[segment_start:col], FONT_SIZE, FONT_PATH))

    except Exception:

        return 0


def selectedspanforline(row, line_text):

    try:

        # no active selection
        if not hasselection():
            return None

        # get ordered selection bounds
        sr, sc, er, ec = selectionbounds()

        # row not covered by selection
        if row < sr or row > er:
            return None

        # line length clamp
        try:
            linelen = len(line_text)
        except Exception:
            linelen = 0

        # single line selection
        if sr == er:

            if sc < 0:
                sc = 0

            if ec < 0:
                ec = 0

            if sc > linelen:
                sc = linelen

            if ec > linelen:
                ec = linelen

            if sc == ec:
                return None

            return sc, ec

        # first line of multi-line selection
        if row == sr:

            if sc < 0:
                sc = 0

            if sc > linelen:
                sc = linelen

            if sc == linelen:
                return None

            return sc, linelen

        # last line of multi-line selection
        if row == er:

            if ec < 0:
                ec = 0

            if ec > linelen:
                ec = linelen

            if ec == 0:
                return None

            return 0, ec

        # middle lines of multi-line selection
        if linelen == 0:
            return None

        return 0, linelen

    except Exception as e:

        logmsg(f'> selected span error {e}')
        return None


def drawdocumenttext(x, y, text, colour, background, tab_column=0):

    renderer = getattr(gfx, 'drawtextttfopaque', None)
    shown = expanddisplaytabs(text, tab_column)

    if callable(renderer):
        renderer(
            int(x),
            int(y),
            shown,
            colour,
            background,
            FONT_SIZE,
            fontpath=FONT_PATH,
            height=LINE_HEIGHT,
        )
        return

    drawtextttf(int(x), int(y), shown, colour, FONT_SIZE, FONT_PATH)


def drawlinewithselection(xbase, y, row, line_text, segment_start=0):

    try:

        # ensure string
        try:
            line = str(line_text)
        except Exception:
            line = ''

        # Intersect the logical-line selection with this visual segment.
        full_line = str(DOC_LINES[row]) if 0 <= row < len(DOC_LINES) else line
        basecolumn = displaycolumn(full_line[:max(0, int(segment_start))])
        span = selectedspanforline(row, full_line)

        if span and segment_start:
            span = (max(0, span[0] - segment_start), min(len(line), span[1] - segment_start))
            if span[0] >= span[1]:
                span = None

        # no selection on this line
        if not span:

            drawdocumenttext(xbase, y, line, TEXT_COLOR, BG_COLOR, basecolumn)
            return

        # unpack span
        s, e = span

        # clamp span
        if s < 0:
            s = 0

        if e < 0:
            e = 0

        if s > len(line):
            s = len(line)

        if e > len(line):
            e = len(line)

        if s == e:

            drawdocumenttext(xbase, y, line, TEXT_COLOR, BG_COLOR, basecolumn)
            return

        # split segments
        left = line[:s]
        mid = line[s:e]
        right = line[e:]

        # measure left and mid widths
        try:
            leftw = measuretext(expanddisplaytabs(left, basecolumn), FONT_SIZE)
        except Exception:
            leftw = 0

        try:
            middlecolumn = displaycolumn(left, basecolumn)
            midw = measuretext(expanddisplaytabs(mid, middlecolumn), FONT_SIZE)
        except Exception:
            midw = 0

        # compute x positions
        xsel = int(xbase + leftw)
        xright = int(xsel + midw)

        # draw left normal
        if left:

            drawdocumenttext(xbase, y, left, TEXT_COLOR, BG_COLOR, basecolumn)

        # draw selection background
        if midw <= 0:
            midw = 1

        fillrect(int(xsel), int(y), int(midw), int(LINE_HEIGHT), SELBACKGROUND)

        # draw selected text inverted
        if mid:
            drawdocumenttext(int(xsel), int(y), mid, 0xFFFFFF, SELBACKGROUND, middlecolumn)

        # draw right normal
        if right:

            drawdocumenttext(
                xright,
                y,
                right,
                TEXT_COLOR,
                BG_COLOR,
                displaycolumn(mid, middlecolumn),
            )

    except Exception as e:

        logmsg(f'> draw line selection error {e}')
        return

    return


def deleteselection():

    try:

        if not hasselection():
            return

        sr, sc, er, ec = selectionbounds()
        editreplace(sr, sc, er, ec, '')

    except Exception as e:

        logmsg(f'> delete selection error {e}')

    return


def replaceselectionwithtext(text):

    try:

        if hasselection():
            sr, sc, er, ec = selectionbounds()
        else:
            sr, sc, er, ec = CUR_ROW, CUR_COL, CUR_ROW, CUR_COL

        value = '' if text is None else str(text)
        editreplace(sr, sc, er, ec, value)

    except Exception as e:

        logmsg(f'> replace selection error {e}')

    return


def selectedtext():

    try:

        if not hasselection():
            return ''

        sr, sc, er, ec = selectionbounds()

        if sr < 0:
            sr = 0

        if er < 0:
            er = 0

        if sr >= len(DOC_LINES):
            return ''

        if er >= len(DOC_LINES):
            er = len(DOC_LINES) - 1

        if sr == er:

            line = str(DOC_LINES[sr])

            if sc < 0:
                sc = 0

            if ec < 0:
                ec = 0

            if sc > len(line):
                sc = len(line)

            if ec > len(line):
                ec = len(line)

            return line[sc:ec]

        parts = []

        first = str(DOC_LINES[sr])

        if sc < 0:
            sc = 0

        if sc > len(first):
            sc = len(first)

        parts.append(first[sc:])

        for r in range(sr + 1, er):

            parts.append(str(DOC_LINES[r]))

        last = str(DOC_LINES[er])

        if ec < 0:
            ec = 0

        if ec > len(last):
            ec = len(last)

        parts.append(last[:ec])

        return '\n'.join(parts)

    except Exception as e:

        logmsg(f'> selected text error {e}')
        return ''


def inserttextblock(text):

    try:

        value = '' if text is None else str(text)
        editreplace(CUR_ROW, CUR_COL, CUR_ROW, CUR_COL, value)

    except Exception as e:

        logmsg(f'> insert text block error {e}')

    return


def replaceselectionwithtextblock(text):

    try:

        if hasselection():
            sr, sc, er, ec = selectionbounds()
        else:
            sr, sc, er, ec = CUR_ROW, CUR_COL, CUR_ROW, CUR_COL

        value = '' if text is None else str(text)
        editreplace(sr, sc, er, ec, value)

    except Exception as e:

        logmsg(f'> replace selection text block error {e}')

    return


def editcopy():

    try:

        if not hasselection():
            return

        txt = selectedtext()

        if not txt:
            return

        exset(txt, source='write')

    except Exception as e:

        logmsg(f'> copy error {e}')

    return


def editcut():

    try:

        if not hasselection():
            return

        txt = selectedtext()

        if not txt:
            return

        exset(txt, source='write')

        deleteselection()

    except Exception as e:

        logmsg(f'> cut error {e}')

    return


def editpaste():

    try:

        ok, st = exget()

        if not ok:
            return

        txt = str(st.get('data', ''))

        if txt == '':
            return

        replaceselectionwithtextblock(txt)

        clearselection()

        ensurecursorvisible()

        # A paste can replace most of the visible document in one edit.  Do
        # not express that structural change as a retained-scene patch: the
        # compositor must replace the scene so every newly visible row is
        # painted atomically.
        graphicsrequestscenerebuild()

    except Exception as e:

        logmsg(f'> paste error {e}')

    return


def editselectall():

    global SEL_ACTIVE
    global SEL_ANCHOR_ROW
    global SEL_ANCHOR_COL
    global SEL_ROW
    global SEL_COL
    global CUR_ROW
    global CUR_COL

    try:

        if not DOC_LINES:
            return

        SEL_ANCHOR_ROW = 0
        SEL_ANCHOR_COL = 0

        lastrow = len(DOC_LINES) - 1

        lastline = str(DOC_LINES[lastrow])

        SEL_ROW = lastrow
        SEL_COL = len(lastline)

        SEL_ACTIVE = True

        CUR_ROW = lastrow
        CUR_COL = len(lastline)

        ensurecursorvisible()

    except Exception as e:

        logmsg(f'> select all error {e}')

    return


def indentationremoval(line):

    text = str(line)

    if text.startswith('\t'):
        return 1

    count = 0

    while count < min(TAB_WIDTH, len(text)) and text[count] == ' ':
        count += 1

    return count


def handleindentation(outdent=False):

    global CUR_ROW
    global CUR_COL
    global SEL_ACTIVE
    global SEL_ANCHOR_ROW
    global SEL_ANCHOR_COL
    global SEL_ROW
    global SEL_COL
    global DOCUMENT_REFLOW_ROW

    try:

        if not DOC_LINES:
            return False

        if not hasselection():

            row, col = normalisecaret(CUR_ROW, CUR_COL)

            if not outdent:
                if INDENT_USE_TABS:
                    return editreplace(row, col, row, col, '\t')

                count = TAB_WIDTH - (displaycolumn(str(DOC_LINES[row])[:col]) % TAB_WIDTH)
                return editreplace(row, col, row, col, ' ' * count)

            count = indentationremoval(DOC_LINES[row])

            if count <= 0:
                return False

            editreplace(row, 0, row, count, '')
            CUR_ROW = row
            CUR_COL = max(0, col - count)
            DOCUMENT_REFLOW_ROW = row
            return True

        anchor = (int(SEL_ANCHOR_ROW), int(SEL_ANCHOR_COL))
        endpoint = (int(SEL_ROW), int(SEL_COL))
        caret = (int(CUR_ROW), int(CUR_COL))
        sr, sc, er, ec = selectionbounds()
        lastrow = er - 1 if er > sr and ec == 0 else er
        lastrow = max(sr, lastrow)
        removals = {}
        replacement = []

        for row in range(sr, lastrow + 1):
            line = str(DOC_LINES[row])

            if outdent:
                count = indentationremoval(line)
                removals[row] = count
                replacement.append(line[count:])
            else:
                replacement.append(('\t' if INDENT_USE_TABS else (' ' * TAB_WIDTH)) + line)

        if outdent and not any(removals.values()):
            return False

        editreplace(
            sr,
            0,
            lastrow,
            len(str(DOC_LINES[lastrow])),
            '\n'.join(replacement),
        )

        def adjusted(position):

            row, col = position

            if sr <= row <= lastrow:

                if outdent:
                    col = max(0, col - int(removals.get(row, 0)))
                else:
                    col += 1 if INDENT_USE_TABS else TAB_WIDTH

            return int(row), int(col)

        SEL_ANCHOR_ROW, SEL_ANCHOR_COL = adjusted(anchor)
        SEL_ROW, SEL_COL = adjusted(endpoint)
        CUR_ROW, CUR_COL = adjusted(caret)
        SEL_ACTIVE = (SEL_ANCHOR_ROW, SEL_ANCHOR_COL) != (SEL_ROW, SEL_COL)
        DOCUMENT_REFLOW_ROW = sr
        return True

    except Exception as e:

        logmsg(f'> indentation error {e}')
        return False


def selectedlinerange():

    if hasselection():
        sr, _, er, ec = selectionbounds()
        last = er - 1 if er > sr and ec == 0 else er
        return sr, max(sr, last)

    row, _ = normalisecaret(CUR_ROW, CUR_COL)
    return row, row


def duplicatelines():

    global CUR_ROW, CUR_COL, DOCUMENT_REFLOW_ROW

    try:
        first, last = selectedlinerange()
        block = '\n'.join(str(DOC_LINES[row]) for row in range(first, last + 1))
        endcol = len(str(DOC_LINES[last]))
        editreplace(last, endcol, last, endcol, '\n' + block)
        clearselection()
        CUR_ROW = last + 1
        CUR_COL = min(CUR_COL, len(str(DOC_LINES[CUR_ROW])))
        DOCUMENT_REFLOW_ROW = first
        return True
    except Exception as e:
        logmsg(f'> duplicate lines error {e}')
        return False


def deletelines():

    global CUR_ROW, CUR_COL, DOCUMENT_REFLOW_ROW

    try:
        first, last = selectedlinerange()

        if first == 0 and last == len(DOC_LINES) - 1:
            editreplace(0, 0, last, len(str(DOC_LINES[last])), '')
        elif last + 1 < len(DOC_LINES):
            editreplace(first, 0, last + 1, 0, '')
        else:
            previous = first - 1
            editreplace(previous, len(str(DOC_LINES[previous])), last, len(str(DOC_LINES[last])), '')

        clearselection()
        CUR_ROW = min(first, len(DOC_LINES) - 1)
        CUR_COL = min(CUR_COL, len(str(DOC_LINES[CUR_ROW])))
        DOCUMENT_REFLOW_ROW = max(0, first - 1)
        return True
    except Exception as e:
        logmsg(f'> delete lines error {e}')
        return False


def transformselection(mode):

    global CUR_ROW, CUR_COL

    try:
        if not hasselection():
            return False

        sr, sc, er, ec = selectionbounds()
        value = selectedtext()
        transformed = value.upper() if str(mode) == 'upper' else value.lower()

        if transformed == value:
            return False

        editreplace(sr, sc, er, ec, transformed)
        setselectionanchor(sr, sc)
        CUR_ROW, CUR_COL = textpositionafter(sr, sc, transformed)
        updateselectionend(CUR_ROW, CUR_COL)
        return True
    except Exception as e:
        logmsg(f'> selection case conversion error {e}')
        return False


def iswordcharacter(character):

    return bool(character) and (str(character).isalnum() or str(character) == '_')


def wordpositionleft(row, col):

    row, col = normalisecaret(row, col)

    if col == 0:
        if row == 0:
            return 0, 0
        row -= 1
        col = len(str(DOC_LINES[row]))

    line = str(DOC_LINES[row])

    while col > 0 and line[col - 1].isspace():
        col -= 1

    if col > 0:
        word = iswordcharacter(line[col - 1])

        while col > 0 and not line[col - 1].isspace() and iswordcharacter(line[col - 1]) == word:
            col -= 1

    return row, col


def wordpositionright(row, col):

    row, col = normalisecaret(row, col)
    line = str(DOC_LINES[row])

    if col >= len(line):
        if row + 1 >= len(DOC_LINES):
            return row, len(line)
        return row + 1, 0

    word = iswordcharacter(line[col])

    while col < len(line) and not line[col].isspace() and iswordcharacter(line[col]) == word:
        col += 1

    while col < len(line) and line[col].isspace():
        col += 1

    return row, col


def movecursorword(reverse=False):

    global CUR_ROW, CUR_COL

    if reverse:
        CUR_ROW, CUR_COL = wordpositionleft(CUR_ROW, CUR_COL)
    else:
        CUR_ROW, CUR_COL = wordpositionright(CUR_ROW, CUR_COL)


def deleteword(reverse=False):

    try:
        if reverse:
            row, col = wordpositionleft(CUR_ROW, CUR_COL)
            return editreplace(row, col, CUR_ROW, CUR_COL, '')

        row, col = wordpositionright(CUR_ROW, CUR_COL)
        return editreplace(CUR_ROW, CUR_COL, row, col, '')
    except Exception as e:
        logmsg(f'> delete word error {e}')
        return False


def displaycolumn(text, initial=0):

    column = max(0, int(initial))

    for character in str(text):
        if character == '\t':
            column += TAB_WIDTH - (column % TAB_WIDTH)
        else:
            column += 1

    return column


def expanddisplaytabs(text, initial=0):

    column = max(0, int(initial))
    parts = []

    for character in str(text):
        if character == '\t':
            count = TAB_WIDTH - (column % TAB_WIDTH)
            parts.append(' ' * count)
            column += count
        else:
            parts.append(character)
            column += 1

    return ''.join(parts)


def findlineindex(line, query, start=0, reverse=False):

    haystack = str(line)
    needle = str(query)

    if not FIND_MATCH_CASE:
        haystack = haystack.lower()
        needle = needle.lower()

    if reverse:
        return haystack.rfind(needle, 0, max(0, int(start)))

    return haystack.find(needle, max(0, int(start)))


def findnext(reverse=False, query=None):

    global FIND_QUERY, CUR_ROW, CUR_COL

    try:
        value = FIND_QUERY if query is None else str(query)

        if not value:
            setstatus('enter text to find')
            return False

        FIND_QUERY = value
        startrow, startcol = normalisecaret(CUR_ROW, CUR_COL)

        if hasselection():
            sr, sc, er, ec = selectionbounds()

            if selectionmatches(value):
                startrow, startcol = (sr, sc) if reverse else (er, ec)

        rows = len(DOC_LINES)

        for offset in range(rows + 1):
            row = (startrow - offset) % rows if reverse else (startrow + offset) % rows
            line = str(DOC_LINES[row])

            if reverse:
                boundary = startcol if offset == 0 else len(line) + 1
                index = findlineindex(line, value, boundary, reverse=True)
            else:
                boundary = startcol if offset == 0 else 0
                index = findlineindex(line, value, boundary)

            if index >= 0:
                setselectionanchor(row, index)
                CUR_ROW = row
                CUR_COL = index + len(value)
                updateselectionend(CUR_ROW, CUR_COL)
                ensurecursorvisible()
                setstatus(f'found {value}')
                return True

        clearselection()
        setstatus(f'not found: {value}')
        return False

    except Exception as e:
        logmsg(f'> find error {e}')
        return False


def selectionmatches(query):

    value = selectedtext()

    if FIND_MATCH_CASE:
        return value == str(query)

    return value.lower() == str(query).lower()


def replaceone():

    global CUR_ROW, CUR_COL

    try:
        if not FIND_QUERY:
            return False

        if not hasselection() or not selectionmatches(FIND_QUERY):
            if not findnext(query=FIND_QUERY):
                return False

        sr, sc, er, ec = selectionbounds()
        editreplace(sr, sc, er, ec, REPLACE_QUERY)
        CUR_ROW, CUR_COL = textpositionafter(sr, sc, REPLACE_QUERY)
        clearselection()
        findnext(query=FIND_QUERY)
        return True
    except Exception as e:
        logmsg(f'> replace error {e}')
        return False


def replaceall():

    try:
        if not FIND_QUERY:
            return 0

        flagsensitive = bool(FIND_MATCH_CASE)
        total = 0
        replacement = []

        for line in DOC_LINES:
            value = str(line)

            if flagsensitive:
                count = value.count(FIND_QUERY)
                changed = value.replace(FIND_QUERY, REPLACE_QUERY)
            else:
                lowered = value.lower()
                needle = FIND_QUERY.lower()
                parts = []
                position = 0
                count = 0

                while True:
                    found = lowered.find(needle, position)

                    if found < 0:
                        parts.append(value[position:])
                        break

                    parts.append(value[position:found])
                    parts.append(REPLACE_QUERY)
                    position = found + len(FIND_QUERY)
                    count += 1

                changed = ''.join(parts)

            total += count
            replacement.append(changed)

        if total:
            last = len(DOC_LINES) - 1
            editreplace(0, 0, last, len(str(DOC_LINES[last])), '\n'.join(replacement))
            clearselection()

        setstatus(f'replaced {total}')
        return total
    except Exception as e:
        logmsg(f'> replace all error {e}')
        return 0


def gotoline(value):

    global CUR_ROW, CUR_COL

    try:
        row = int(str(value).strip()) - 1
        row = max(0, min(len(DOC_LINES) - 1, row))
        CUR_ROW = row
        CUR_COL = 0
        clearselection()
        ensurecursorvisible()
        setstatus(f'line {row + 1}')
        return True
    except Exception:
        setstatus('invalid line number')
        return False


def changezoom(delta, reset=False):

    global FONT_SIZE_BASE

    try:
        FONT_SIZE_BASE = 14 if reset else max(8, min(48, int(FONT_SIZE_BASE) + int(delta)))
        width = int(SCREENSIZE[0]) if int(SCREENSIZE[0]) > 0 else BASE_W
        height = int(SCREENSIZE[1]) if int(SCREENSIZE[1]) > 0 else BASE_H
        applyuiscale(width, height)
        initttffont(FONT_PATH, FONT_SIZE)
        invalidatewrapcache(drop_lines=True)
        docwidthreset()
        savesettings()
        updatelayoutonresize(redraw=False)
        ensurecursorvisible()
        redrawfull()
        setstatus(f'zoom {FONT_SIZE_BASE}')
        return True
    except Exception as e:
        logmsg(f'> zoom error {e}')
        return False


# windowserver functions
def connectwindowserver():

    global ws_sock
    global ws_inbuf

    try:

        # create unix socket
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

    except PermissionError:

        # permission denied creating socket
        logmsg('> permission denied creating window server socket')
        sys.exit(1)

    except Exception as e:

        # other errors creating socket
        logmsg(f'> error creating window server socket {e}')
        sys.exit(1)

    try:

        # connect to window server
        sock.connect(SOCKPATH)

    except FileNotFoundError:

        # socket path not found
        logmsg('> window server socket not found')
        sys.exit(1)

    except PermissionError:

        # permission denied connecting
        logmsg('> permission denied connecting to window server')
        sys.exit(1)

    except ConnectionRefusedError:

        # server refused connection
        logmsg('> window server refused connection')
        sys.exit(1)

    except Exception as e:

        # other connect errors
        logmsg(f'> error connecting to window server {e}')
        sys.exit(1)

    # assign socket and reset buffer
    ws_sock = sock

    ws_inbuf = b''

    return


def sendmsg(msg):

    global ws_sock

    if ws_sock is None:

        # no socket to send on
        logmsg('> window server socket is not connected')
        return False

    try:

        # encode message as json
        data = json.dumps(msg, separators=(',', ':')).encode('utf-8')

    except TypeError as e:

        # invalid data for json
        logmsg(f'> error encoding window message {e}')
        return False

    except Exception as e:

        # other encoding errors
        logmsg(f'> error encoding window message {e}')
        return False

    try:

        # append newline terminator
        payload = data + b'\n'

    except Exception as e:

        # payload build error
        logmsg(f'> error building window message payload {e}')
        return False

    try:

        # send payload
        ws_sock.sendall(payload)

    except BrokenPipeError:

        # connection closed by server
        logmsg('> window server connection closed while sending')
        return False

    except PermissionError:

        # permission error sending
        logmsg('> permission denied sending to window server')
        return False

    except Exception as e:

        # other send errors
        logmsg(f'> error sending message to window server {e}')
        return False

    return True


def setpointercursor(mode):

    global POINTER_CURSOR_MODE

    mode = str(mode or 'arrow')

    if mode == POINTER_CURSOR_MODE or not WINDOW_ID:
        return

    if sendmsg({
        'op': 'CURSOR_MODE_SET',
        'winid': int(WINDOW_ID),
        'mode': mode,
    }):
        POINTER_CURSOR_MODE = mode


def readlines(nonblocking=False):

    global ws_sock
    global ws_inbuf
    global APP_RUNNING

    lines = []

    if ws_sock is None:

        # no socket available
        return lines

    try:

        # read from socket
        chunk = ws_sock.recv(4096)

    except BlockingIOError:

        # non-blocking read with no data
        return lines

    except PermissionError:

        # permission denied reading
        logmsg('> permission denied reading from window server socket')
        APP_RUNNING = False
        return lines

    except Exception as e:

        # other read errors
        logmsg(f'> error reading from window server socket {e}')
        APP_RUNNING = False
        return lines

    if not chunk:

        # server closed connection
        logmsg('> window server closed connection')
        APP_RUNNING = False
        return lines

    try:

        # append to incoming buffer
        ws_inbuf += chunk

    except Exception as e:

        # buffer append error
        logmsg(f'> error buffering window server data {e}')
        APP_RUNNING = False
        return lines

    while True:

        try:

            # locate line terminator
            idx = ws_inbuf.find(b'\n')

        except Exception as e:

            # search error
            logmsg(f'> error scanning window server buffer {e}')
            APP_RUNNING = False
            return lines

        if idx == -1:

            # no complete line
            break

        try:

            # slice one line
            raw = ws_inbuf[:idx]

            # remove line from buffer
            ws_inbuf = ws_inbuf[idx + 1:]

        except Exception as e:

            # slice error
            logmsg(f'> error slicing window server buffer {e}')
            APP_RUNNING = False
            return lines

        try:

            # decode utf-8 line
            text = raw.decode('utf-8', errors='replace')

        except Exception as e:

            # decode error
            logmsg(f'> error decoding window server line {e}')
            continue

        lines.append(text)

    return lines


def sendhello():

    global ws_sock
    global PICKER_VERSION

    # send initial hello
    sendmsg({"op": "HELLO"})

    if ws_sock is None:

        # no socket to wait on
        return

    try:

        # wait for welcome message
        attempts = 0

        while attempts < 50:

            attempts += 1

            try:

                # poll socket for readability
                rlist, _, _ = select.select([ws_sock], [], [], 0.1)

            except PermissionError:

                # permission error selecting
                logmsg('> permission denied waiting for window server welcome')
                return

            except Exception as e:

                # other select errors
                logmsg(f'> error waiting for window server welcome {e}')
                return

            if not rlist:

                # no data yet
                continue

            try:

                # read lines from socket
                lines = readlines()

            except Exception as e:

                # readlines error
                logmsg(f'> error reading window server welcome {e}')
                return

            for line in lines:

                try:

                    # parse json message
                    msg = json.loads(line)

                except json.JSONDecodeError:

                    # invalid json from server
                    logmsg('> invalid json from window server during hello')
                    continue

                except Exception as e:

                    # other decode errors
                    logmsg(f'> error decoding window server hello {e}')
                    continue

                try:

                    # extract operation
                    op = str(msg.get('op', ''))

                except Exception as e:

                    # op access error
                    logmsg(f'> error reading window server hello op {e}')
                    continue

                if op == 'WELCOME':

                    try:
                        PICKER_VERSION = int(msg.get('pickers', {}).get('version', 0))
                    except Exception:
                        PICKER_VERSION = 0

                    # derive screen size from welcome payload
                    try:

                        fb = msg.get('fb', {})

                        sw = int(fb.get('w', 0))

                        sh = int(fb.get('h', 0))

                        if sw > 0 and sh > 0:
                            setscreensize(sw, sh)

                    except Exception as e:

                        logmsg(f'> error reading fb size from welcome {e}')

                    try:

                        graphicsconfigure(msg.get('graphics', {}))

                    except Exception as e:

                        logmsg(f'> error reading managed graphics capabilities {e}')
                        graphicsconfigure({})

                    # subscribe for future fb size updates
                    try:

                        sendmsg({"op": "SUBSCRIBE", "types": ["fbsize"]})

                    except Exception as e:

                        logmsg(f'> error subscribing fbsize {e}')

                    # got welcome, handshake complete
                    return

                try:

                    # dispatch any other early messages
                    dispatchmessage(msg)

                except Exception as e:

                    # dispatch error
                    logmsg(f'> error dispatching early window server message {e}')

                    continue

    except Exception as e:

        # outer hello error
        logmsg(f'> error during window server hello {e}')
        return

    return


def createwindow():

    global WINDOW_ID, WIN_W, WIN_H, BUFFER_PATH, FILE_NAME
    global BASE_WIN_W, BASE_WIN_H, UISCALE, SCREENSIZE

    title = 'write'

    try:

        req_w = int(BASE_WIN_W * UISCALE)
        req_h = int(BASE_WIN_H * UISCALE)

    except Exception:

        req_w = int(BASE_WIN_W)
        req_h = int(BASE_WIN_H)

    if req_w < 64:
        req_w = 64

    if req_h < 64:
        req_h = 64

    try:

        # keep the request on-screen if we know the framebuffer size
        sw = int(SCREENSIZE[0])
        sh = int(SCREENSIZE[1])

        if sw > 0 and req_w > sw:
            req_w = sw

        if sh > 0 and req_h > sh:
            req_h = sh

    except Exception:
        pass

    try:

        # build create window request
        msg = {
            'op': 'CREATE_WINDOW',
            'role': 'window',
            'title': title,
            'current': str(FILE_NAME),
            'path': f'{WRITEPATH}',
            'x': 100,
            'y': 100,
            'w': int(req_w),
            'h': int(req_h)
        }

    except Exception as e:

        # error building create window message
        logmsg(f'error building create window request {e}')
        return

    except Exception as e:

        # error building create window message
        logmsg(f'error building create window request {e}')
        return

    # send create window request
    sendmsg(msg)

    if ws_sock is None:

        # not connected
        logmsg('createwindow: ws_sock is None after send')
        return

    try:

        # wait for window created response
        attempts = 0

        while attempts < 100:

            attempts += 1

            try:

                # poll socket for readability
                rlist, _, _ = select.select([ws_sock], [], [], 0.1)

            except PermissionError:

                # permission error selecting
                logmsg('permission denied waiting for window create')
                return

            except Exception as e:

                # other select errors
                logmsg(f'error waiting for window create {e}')
                return

            if not rlist:

                # no data yet
                continue

            try:

                # read lines from socket
                lines = readlines()

            except Exception as e:

                # readlines error
                logmsg(f'error reading window create response {e}')
                return

            for line in lines:

                try:

                    # decode json message
                    msg = json.loads(line)

                except json.JSONDecodeError:

                    # invalid json
                    logmsg('invalid json from window server during create')
                    continue

                except Exception as e:

                    # other decode errors
                    logmsg(f'error decoding window create message {e}')
                    continue

                try:

                    # extract operation
                    op = str(msg.get('op', ''))

                except Exception as e:

                    # op extraction error
                    logmsg(f'error reading window create op {e}')
                    continue

                if op == 'ERROR':

                    try:

                        # extract error code and detail
                        code = str(msg.get('code', ''))
                        detail = str(msg.get('detail', ''))

                    except Exception:

                        code = 'unknown'
                        detail = ''

                    # report create error
                    logmsg(f'window create error {code} {detail}')
                    return

                if op == 'WINDOW_CREATED':

                    try:

                        # assign window id
                        WINDOW_ID = int(msg.get('winid', 0))

                    except Exception:

                        WINDOW_ID = 0

                    try:

                        # assign buffer path
                        BUFFER_PATH = str(msg.get('buffer', ''))

                    except Exception:

                        BUFFER_PATH = ''


                    # assign width and height
                    WIN_W = int(msg.get('w', WIN_W))
                    WIN_H = int(msg.get('h', WIN_H))

                    logmsg(f'WINDOW_CREATED winid={WINDOW_ID} w={WIN_W} h={WIN_H}')
                    return

                try:

                    # dispatch any other messages
                    dispatchmessage(msg)

                except Exception as e:

                    # dispatch error
                    logmsg(f'error dispatching message during window create {e}')
                    continue

    except Exception as e:

        # outer window create error
        logmsg(f'error during window create {e}')
        return

    return


def mapwindow():

    global WINDOW_ID

    if not WINDOW_ID:

        # cannot map before window is created
        logmsg('cannot map window, WINDOW_ID is not set')
        return

    try:

        # reset pointer state on map
        resetpointerstate()

        # build map message
        msg = {
            'op': 'MAP',
            'winid': int(WINDOW_ID)
        }

    except Exception as e:

        # error building map request
        logmsg(f'error building map request {e}')
        return

    # send map request
    sendmsg(msg)

    try:

        # build raise message
        raise_msg = {
            'op': 'RAISE',
            'winid': int(WINDOW_ID)
        }

    except Exception as e:

        # error building raise request
        logmsg(f'error building raise request {e}')
        raise_msg = None

    if raise_msg is not None:

        # send raise request
        sendmsg(raise_msg)

    try:

        # build focus set message
        focus_msg = {
            'op': 'FOCUS_SET',
            'winid': int(WINDOW_ID)
        }

    except Exception as e:

        # error building focus set request
        logmsg(f'error building focus set request {e}')
        focus_msg = None

    logmsg(f'MAP sent for winid={WINDOW_ID}')

    if focus_msg is not None:

        # send focus set request
        sendmsg(focus_msg)

    return


def senddamage(x, y, w, h):

    global WINDOW_ID

    if WINDOW_ID is None:

        # cannot send damage before window exists
        return

    try:

        # build damage request
        msg = {
            'op': 'DAMAGE',
            'winid': int(WINDOW_ID),
            'rect': [int(x), int(y), int(w), int(h)]
        }

    except Exception as e:

        # error building damage message
        logmsg(f'> error building damage request {e}')
        return

    # send damage
    sendmsg(msg)

    return


def pollwindowevents(timeout):

    global ws_sock
    global APP_RUNNING

    if not APP_RUNNING:

        # application is not running
        return

    if ws_sock is None:

        # no socket to poll
        time.sleep(timeout)
        return

    try:

        # wait for socket readability
        rlist, _, _ = select.select([ws_sock], [], [], timeout)

    except PermissionError:

        # permission denied polling
        logmsg('> permission denied polling window server socket')
        APP_RUNNING = False
        return

    except Exception as e:

        # other poll errors
        logmsg(f'> error polling window server socket {e}')
        APP_RUNNING = False
        return

    if not rlist:

        # no events
        return

    try:

        # read pending lines
        lines = readlines()

    except Exception as e:

        # readlines error
        logmsg(f'> error reading window server events {e}')
        APP_RUNNING = False
        return

    beginrenderbatch()

    for line in lines:

        try:

            # decode json message
            msg = json.loads(line)

        except json.JSONDecodeError:

            # invalid json
            logmsg('> invalid json from window server')
            continue

        except Exception as e:

            # other decode errors
            logmsg(f'> error decoding window server message {e}')
            continue

        try:

            # dispatch decoded message
            dispatchmessage(msg)

        except Exception as e:

            # dispatch error
            logmsg(f'> error dispatching window server message {e}')
            continue

    endrenderbatch(flush=True)
    return


def dispatchmessage(msg):

    global APP_RUNNING, DIALOG_WIN
    global PICKER_PENDING
    global AFTER_SAVE_ACTION, PENDING_DESTRUCTIVE_ACTION

    try:

        # extract operation
        op = str(msg.get('op', ''))

    except Exception as e:

        # op extraction error
        logmsg(f'> error reading window server message op {e}')
        return

    try:

        # extract operation
        op = str(msg.get('op', ''))

    except Exception as e:

        # op extraction error
        logmsg(f'> error reading window server message op {e}')
        return

    if op == 'GRAPHICS_COMMITTED':

        graphicscommitted(msg)
        return

    if op == 'GRAPHICS_CLEARED':

        graphicscleared(msg)
        return

    if op in ('GRAPHICS_BEGUN', 'GRAPHICS_COMMAND_ADDED', 'GRAPHICS_INFO'):

        return

    if op == 'PICKER_CREATED':

        if PICKER_PENDING is not None:
            PICKER_PENDING['request_id'] = str(msg.get('request_id', ''))
            setstatus('select a location in Array')
            redrawstatusbar()
        return

    if op == 'PICKER_RESULT':

        handlepickerresult(msg)
        return

    if op == 'ERROR':

        code = str(msg.get('code', ''))

        if code.startswith('graphics_'):

            managedresponse(GRAPHICSSTATE, msg)
            graphicsscheduleretry()

            if (
                code != 'graphics_clear_failed'
                and not GRAPHICSSTATE.get('available')
                and ws_sock is not None
                and WINDOW_ID
            ):
                sendmsg({
                    'op': 'GRAPHICS_CLEAR',
                    'winid': int(WINDOW_ID),
                    'reason': f"{code}: {str(msg.get('detail', ''))}"[:256],
                })

            graphicsrestorecpu()

        if DIALOG_WAITING and code.startswith('dialog_'):
            failedaction = DIALOG_ACTION
            closedialogstate()

            if failedaction in ('confirm_unsaved', 'save_path'):
                canceldestructiveflow()

            setstatus('dialog unavailable')
            redrawstatusbar()

        if PICKER_PENDING is not None and code.startswith('picker_'):
            if PICKER_PENDING.get('kind') == 'save' and AFTER_SAVE_ACTION is not None:
                AFTER_SAVE_ACTION = None
                PENDING_DESTRUCTIVE_ACTION = None
            PICKER_PENDING = None
            setstatus('Array picker unavailable')
            redrawstatusbar()

        return

    if op == 'FB_SIZE':

        try:

            sw = int(msg.get('w', 0))

            sh = int(msg.get('h', 0))

        except Exception as e:

            logmsg(f'> error reading FB_SIZE payload {e}')
            return

        if sw > 0 and sh > 0:
            setscreensize(sw, sh)

            if WINDOW_ID and BUFFER_PATH:
                redrawfull()

        return

    if op == 'TEXT':

        try:

            # route TEXT as a key-style message
            text = str(msg.get('text', ''))

            state = str(msg.get('state', 'down'))

            mods = str(msg.get('mods', ''))

            tmsg = {
                'text': text,
                'state': state if state else 'down',
                'mods': mods,
            }

        except Exception as e:

            logmsg(f'> error building TEXT passthrough {e}')
            return

        try:

            handlekey(tmsg)

        except Exception as e:

            logmsg(f'> error handling TEXT message {e}')

        return

    if op == 'KEY':

        try:

            # convert windowserver KEY message into write's expected shape
            nmsg = normalisekeymsg(msg)

        except Exception as e:

            logmsg(f'> error normalising KEY message {e}')
            nmsg = None

        if not nmsg:
            return

        try:
            handlekey(nmsg)
        except Exception as e:
            logmsg(f'> error handling KEY message {e}')

        return

    if op == 'DIALOG_CREATED':

        if DIALOG_WAITING and str(msg.get('dialog_id', '')) == str(DIALOG_ID or ''):
            DIALOG_WIN = msg.get('winid')

        return

    if op == 'DIALOG_RESULT':

        handledialogresult(msg)
        return

    if op == 'POINTER_BUTTON':

        try:
            handlepointerbutton(msg)
        except Exception as e:
            logmsg(f'> error handling POINTER_BUTTON message {e}')
        return

    if op == 'POINTER_MOTION':

        try:
            handlepointermotion(msg)
        except Exception as e:
            logmsg(f'> error handling POINTER_MOTION message {e}')
        return

    if op == 'SCROLL':

        try:
            handlescroll(msg)
        except Exception as e:
            logmsg(f'> error handling SCROLL message {e}')
        return

    if op in ('DND_ENTER', 'DND_MOVE', 'DND_DROP_PENDING'):

        kind = str(msg.get('kind', ''))
        setstatus('drop to open' if kind in ('files', 'image') else 'drop to insert')
        redrawstatusbar()
        return

    if op == 'DND_LEAVE':

        setstatus('')
        redrawstatusbar()
        return

    if op == 'DND_DROP':

        kind = str(msg.get('kind', ''))

        if kind in ('files', 'image'):
            paths = msg.get('paths', [])

            if kind == 'image' and msg.get('image'):
                paths = [msg.get('image')]

            if isinstance(paths, list):
                target = next((os.path.abspath(str(path)) for path in paths if os.path.isfile(os.path.abspath(str(path)))), None)

                if target:
                    requestdestructiveaction(('open_recent', target))

        elif kind in ('text', 'html'):
            value = str(msg.get(kind, ''))

            if value:
                replaceselectionwithtextblock(value)
                ensurecursorvisible()
                redrawregionaroundcursororline()

        return

    if op == 'FOCUS':

        try:
            handlefocus(msg)
        except Exception as e:
            logmsg(f'> error handling FOCUS message {e}')
        return

    if op == 'CLOSE':

        sendmsg({'op': 'CLOSE_ACK', 'pid': os.getpid()})
        requestdestructiveaction('exit')
        return

    if op == 'WINDOW_DESTROYED':

        # window destroyed, stop application
        APP_RUNNING = False
        return

    if op == 'RESIZED':

        try:
            handleresize(msg)
        except Exception as e:
            logmsg(f'> error handling RESIZED message {e}')
        return

    if op == 'DAMAGE':

        try:
            handledamage(msg)
        except Exception as e:
            logmsg(f'> error handling DAMAGE message {e}')
        return

    # unhandled messages are ignored for now
    return


def setwindowcurrent():

    global WINDOW_ID, FILE_NAME, ws_sock

    if ws_sock is None:
        return

    if not WINDOW_ID:
        return

    try:

        current = str(FILE_NAME)

    except Exception:

        current = ''

    try:

        msg = {
            'op': 'WINDOW_CURRENT_SET',
            'winid': int(WINDOW_ID),
            'current': current
        }

    except Exception as e:

        logmsg(f'> error building WINDOW_CURRENT_SET {e}')
        return

    sendmsg(msg)

    return


# graphics functions
def initgraphics():

    global BUFFER_PATH
    global WIN_W
    global WIN_H
    global FONT_PATH
    global FONT_SIZE

    try:

        # initialise window buffer mapping
        if not BUFFER_PATH:

            logmsg('> no buffer path for graphics initialisation')
            return

        initbuffer(BUFFER_PATH, WIN_W, WIN_H)

    except PermissionError:

        # permission denied initialising buffer
        logmsg('> permission denied initialising graphics buffer')
        return

    except Exception as e:

        # other buffer initialisation errors
        logmsg(f'> error initialising graphics buffer {e}')
        return

    try:

        # initialise ttf font
        initttffont(FONT_PATH, FONT_SIZE)

    except FileNotFoundError:

        # font file not found
        logmsg(f'> font file not found {FONT_PATH}')
        return

    except PermissionError:

        # permission denied loading font
        logmsg(f'> permission denied loading font {FONT_PATH}')
        return

    except Exception as e:

        # other ttf font errors
        logmsg(f'> error loading ttf font {e}')
        return

    return


def graphicsconfigure(capabilities):

    return managedconfigure(
        GRAPHICSSTATE,
        capabilities,
        required=('rectangle', 'text'),
        cpu=GRAPHICSCPUOVERRIDE or not os.path.isfile(FONT_PATH),
    )


def graphicsdamage():

    try:

        if ws_sock is not None and WINDOW_ID:
            return sendmsg({
                'op': 'DAMAGE',
                'winid': int(WINDOW_ID),
                'rect': [0, 0, int(WIN_W), int(WIN_H)],
            })

    except Exception:
        pass

    return False


def graphicsrequestscenerebuild():

    global GRAPHICSREBUILD

    GRAPHICSREBUILD = True
    GRAPHICSSTATE['need_submit'] = True

    try:
        managedmarkdamage(
            GRAPHICSSTATE,
            [0, 0, int(WIN_W), int(WIN_H)],
            bounds=(int(WIN_W), int(WIN_H)),
        )
    except Exception:
        pass


def graphicsscheduleretry():

    global GRAPHICS_RETRY_AT

    if GRAPHICSCPUOVERRIDE:
        return False

    capabilities = GRAPHICSSTATE.get('capabilities', {})

    if not isinstance(capabilities, dict):
        return False

    if not capabilities.get('accelerated') or not capabilities.get('managed_resources'):
        return False

    GRAPHICS_RETRY_AT = time.monotonic() + GRAPHICS_RETRY_INTERVAL
    return True


def graphicsretry():

    global GRAPHICS_RETRY_AT
    global GRAPHICS_RETRY_COUNT

    if GRAPHICSSTATE.get('available') or GRAPHICSCPUOVERRIDE:
        return False

    if GRAPHICS_RETRY_COUNT >= GRAPHICS_RETRY_LIMIT:
        return False

    if not GRAPHICS_RETRY_AT or time.monotonic() < GRAPHICS_RETRY_AT:
        return False

    capabilities = dict(GRAPHICSSTATE.get('capabilities', {}))
    GRAPHICS_RETRY_AT = 0.0
    GRAPHICS_RETRY_COUNT += 1

    if not graphicsconfigure(capabilities):
        graphicsscheduleretry()
        return False

    graphicsrequestscenerebuild()
    logmsg(f'> retrying managed graphics {GRAPHICS_RETRY_COUNT}/{GRAPHICS_RETRY_LIMIT}')
    return True


def graphicspreparescenerebuild():

    global GRAPHICSREBUILD

    if not GRAPHICSREBUILD or GRAPHICSSTATE.get('pending'):
        return False

    # An empty local retained scene makes managedsubmit use GRAPHICS_SCENE
    # instead of GRAPHICS_PATCH.  The window server then replaces the old
    # scene and repaints the supplied full-window damage in one commit.
    GRAPHICSSTATE['scene'] = []
    GRAPHICSREBUILD = False
    return True


def graphicsrestorecpu():

    try:

        if WIN_W <= 0 or WIN_H <= 0:
            return False

        redrawfull()
        return True

    except Exception as e:

        logmsg(f'> error restoring CPU graphics {e}')
        graphicsdamage()
        return False


def graphicsdisable(reason, clear=True):

    global GRAPHICSSCENE

    if manageddisable(GRAPHICSSTATE, reason):
        GRAPHICSSCENE = []
        graphicsscheduleretry()
        return True
    GRAPHICSSCENE = []
    graphicsscheduleretry()

    try:

        if clear and ws_sock is not None and WINDOW_ID:
            sendmsg({
                'op': 'GRAPHICS_CLEAR',
                'winid': int(WINDOW_ID),
                'reason': str(reason)[:256],
            })

    except Exception:
        pass

    graphicsrestorecpu()
    return False


def graphicssuspend():

    global GRAPHICSSCENE

    if not GRAPHICSSTATE.get('available'):
        return False

    GRAPHICSSCENE = []

    if ws_sock is not None and WINDOW_ID:
        managedclear(GRAPHICSSTATE, sendmsg, WINDOW_ID)

    graphicsdamage()
    return True


def graphicscommitted(msg):

    global GRAPHICS_RETRY_AT
    global GRAPHICS_RETRY_COUNT

    try:

        if WINDOW_ID and int(msg.get('winid', 0)) != int(WINDOW_ID):
            return False

    except Exception:
        return False

    handled = managedresponse(GRAPHICSSTATE, msg)

    if handled and GRAPHICSSTATE.get('active'):
        GRAPHICS_RETRY_AT = 0.0
        GRAPHICS_RETRY_COUNT = 0

    if not GRAPHICSSTATE.get('available'):
        graphicsrestorecpu()

    return handled


def graphicscleared(msg):

    try:

        if WINDOW_ID and int(msg.get('winid', 0)) != int(WINDOW_ID):
            return False

    except Exception:
        return False

    return managedresponse(GRAPHICSSTATE, msg)


def graphicsclip(rect, outer=None):

    try:

        x, y, width, height = [int(value) for value in rect]
        left = max(0, x)
        top = max(0, y)
        right = min(int(WIN_W), x + width)
        bottom = min(int(WIN_H), y + height)

        if outer is not None:

            ox, oy, ow, oh = [int(value) for value in outer]
            left = max(left, ox)
            top = max(top, oy)
            right = min(right, ox + ow)
            bottom = min(bottom, oy + oh)

        if right <= left or bottom <= top:
            return None

        return [left, top, right - left, bottom - top]

    except Exception:
        return None


def graphicsrect(commands, x, y, width, height, colour, clip, nodeid=None):

    try:

        clipped = graphicsclip([x, y, width, height], clip)
        commandclip = graphicsclip(clip)

        if clipped is None or commandclip is None:
            return False

        command = {
            'kind': 'rectangle',
            'rect': clipped,
            'color': colour,
            'clip': commandclip,
        }

        if nodeid is None:

            colourkey = str(colour).replace(' ', '')
            baseid = f'write:rect:{clipped[0]}:{clipped[1]}:{clipped[2]}:{clipped[3]}:{colourkey}'
            duplicate = sum(1 for value in commands if str(value.get('id', '')).startswith(baseid + ':'))
            nodeid = f'{baseid}:{duplicate}'

        command['id'] = str(nodeid)
        commands.append(command)
        return True

    except Exception:
        return False


def graphicsborder(commands, x, y, width, height, colour, clip):

    try:

        x = int(x)
        y = int(y)
        width = int(width)
        height = int(height)

        if width < 1 or height < 1:
            return

        graphicsrect(commands, x, y, width, 1, colour, clip)

        if height > 1:
            graphicsrect(commands, x, y + height - 1, width, 1, colour, clip)

        if height > 2:
            graphicsrect(commands, x, y + 1, 1, height - 2, colour, clip)

            if width > 1:
                graphicsrect(commands, x + width - 1, y + 1, 1, height - 2, colour, clip)

    except Exception:
        pass


def graphicstexty(y, fontpath):

    try:

        face = gfx.getttfface(fontpath)

        if face is None:
            return int(y)

        face.set_pixel_sizes(0, int(FONT_SIZE))
        ascender = int(face.size.ascender >> 6)
        return int(y) + int(FONT_SIZE) - ascender

    except Exception:
        return int(y)


def graphicstext(commands, x, y, text, colour, fontpath, clip, rowkey=None):

    try:

        text = str(text)
        commandclip = graphicsclip(clip)

        if not text or commandclip is None:
            return

        clipx, clipy, clipwidth, clipheight = commandclip

        if int(y) + int(LINE_HEIGHT) <= clipy or int(y) >= clipy + clipheight:
            return

        key = rowkey if rowkey is not None else ('graphics', text, int(y))
        advances = measurelineadvances(key, text, FONT_SIZE, fontpath)

        if len(advances) != len(text):
            advances = []
            width = 0

            for character in text:

                width += int(measuretext(character, FONT_SIZE, fontpath))
                advances.append(width)

        if not advances:
            return

        logicalx = int(x)
        leftdistance = max(0, clipx - logicalx)
        rightdistance = max(0, clipx + clipwidth - logicalx)
        start = bisect.bisect_right(advances, leftdistance)
        end = min(len(text), bisect.bisect_left(advances, rightdistance) + 1)

        while start < end:

            startx = logicalx + (advances[start - 1] if start > 0 else 0)

            if startx >= 0:
                break

            start += 1

        if end <= start:
            return

        limit = max(1, int(GRAPHICSSTATE.get('text_limit', 1024)))
        offset = start

        while offset < end:

            finish = min(end, offset + limit)
            chunk = text[offset:finish]
            chunkx = logicalx + (advances[offset - 1] if offset > 0 else 0)

            if chunk and chunkx < int(WIN_W):

                commands.append({
                    'id': f'write:text:{str(key)}:{offset}',
                    'kind': 'text',
                    'x': max(0, int(chunkx)),
                    'y': graphicstexty(y, fontpath),
                    'text': chunk,
                    'size': int(FONT_SIZE),
                    'font': str(fontpath),
                    'color': colour,
                    'clip': commandclip,
                })

            offset = finish

    except Exception:
        pass


def graphicsselection(commands, x, y, row, line, clip, segment_start=0):

    try:

        line = str(line)
        full_line = str(DOC_LINES[row]) if 0 <= row < len(DOC_LINES) else line
        basecolumn = displaycolumn(full_line[:max(0, int(segment_start))])
        span = selectedspanforline(row, full_line)

        if span and segment_start:
            span = (max(0, span[0] - segment_start), min(len(line), span[1] - segment_start))
            if span[0] >= span[1]:
                span = None

        if not span:

            graphicstext(
                commands,
                x,
                y,
                expanddisplaytabs(line, basecolumn),
                TEXT_COLOR,
                FONT_PATH,
                clip,
                rowkey=('document', row, segment_start),
            )
            return

        start, end = span
        start = max(0, min(len(line), int(start)))
        end = max(start, min(len(line), int(end)))
        left = line[:start]
        middle = line[start:end]
        right = line[end:]
        shownleft = expanddisplaytabs(left, basecolumn)
        middlecolumn = displaycolumn(left, basecolumn)
        shownmiddle = expanddisplaytabs(middle, middlecolumn)
        rightcolumn = displaycolumn(middle, middlecolumn)
        shownright = expanddisplaytabs(right, rightcolumn)
        leftwidth = int(measuretext(shownleft, FONT_SIZE, FONT_PATH)) if shownleft else 0
        middlewidth = int(measuretext(shownmiddle, FONT_SIZE, FONT_PATH)) if shownmiddle else 0
        selectionx = int(x) + leftwidth

        if shownleft:
            graphicstext(commands, x, y, shownleft, TEXT_COLOR, FONT_PATH, clip, rowkey=('selection-left', row, segment_start, start))

        graphicsrect(commands, selectionx, y, max(1, middlewidth), LINE_HEIGHT, SELBACKGROUND, clip)

        if shownmiddle:
            graphicstext(commands, selectionx, y, shownmiddle, 0xFFFFFF, FONT_PATH, clip, rowkey=('selection-middle', row, segment_start, start, end))

        if shownright:
            graphicstext(commands, selectionx + middlewidth, y, shownright, TEXT_COLOR, FONT_PATH, clip, rowkey=('selection-right', row, segment_start, end))

    except Exception:
        graphicstext(
            commands,
            x,
            y,
            expanddisplaytabs(line),
            TEXT_COLOR,
            FONT_PATH,
            clip,
            rowkey=('document-fallback', row, segment_start),
        )


def graphicsbuildmenubar(commands, clip):

    global MENUBAR_RECTS

    graphicsrect(commands, 0, 0, WIN_W, MENUBAR_HEIGHT, MENUBAR_BG, clip)
    MENUBAR_RECTS = {}
    x = int(MARGIN_LEFT)
    y = max(0, (int(MENUBAR_HEIGHT) - int(FONT_SIZE)) // 2)

    for label in ('file', 'edit', 'options'):

        graphicstext(commands, x, y, label, MENUBAR_TEXT, FONT_PATH, clip, rowkey=('menubar', label))
        width = int(measuretext(label, FONT_SIZE, FONT_PATH))
        MENUBAR_RECTS[label] = (int(x - 4), 0, int(width + 8), int(MENUBAR_HEIGHT))
        x += width + int(MENU_GAP)


def graphicsbuilddocument(commands, clip):

    global VISIBLE_LINES

    viewport = graphicsclip(viewportgeometry(), clip)

    if viewport is None or LINE_HEIGHT < 1:
        VISIBLE_LINES = 0
        return

    _, _, _, viewportheight = viewport
    visible = max(0, int(viewportheight) // int(LINE_HEIGHT))
    VISIBLE_LINES = visible
    xbase = int(MARGIN_LEFT) - (0 if WORD_WRAP else int(FIRST_VISIBLE_X))

    for index in range(visible):

        displayrow = int(FIRST_VISIBLE_ROW) + index

        if WORD_WRAP:
            row, start, end = displaysegment(displayrow)
            line = str(DOC_LINES[row])[start:end] if 0 <= row < len(DOC_LINES) else ''
        else:
            row, start = displayrow, 0
            line = str(DOC_LINES[row]) if 0 <= row < len(DOC_LINES) else ''
        y = int(MARGIN_TOP) + index * int(LINE_HEIGHT)
        rowclip = graphicsclip(
            [viewport[0], y, viewport[2], int(LINE_HEIGHT)],
            viewport,
        )

        if rowclip is not None:
            line, linex, start = visiblelineslice(
                row,
                line,
                xbase,
                rowclip[0],
                rowclip[2],
                start,
            )
            # Give each document row its own managed clip.  Besides keeping
            # glyphs inside their line box, this prevents the compositor from
            # batching text across omitted blank rows and dropping the final
            # non-blank row of a multiline paste.
            graphicsselection(commands, linex, y, row, line, rowclip, start)


def graphicsbuildscrollbars(commands, clip, horizontal=False):

    try:

        if not horizontal and VISIBLE_LINES > 0 and displaylinecount() > VISIBLE_LINES:

            trackx, tracky, trackwidth, trackheight = scrollbartrackgeometry()
            thumbx, thumby, thumbwidth, thumbheight = scrollbarthumbgeometry()
            graphicsrect(commands, trackx, tracky, trackwidth, trackheight, BG_COLOR, clip)
            graphicsborder(commands, trackx, tracky, trackwidth, trackheight, SCROLLBAR_BG_COLOR, clip)

            if thumbwidth > 0 and thumbheight > 0:
                graphicsborder(commands, thumbx, thumby, thumbwidth, thumbheight, SCROLLBAR_THUMB_COLOR, clip)

        if horizontal and horizontalneeded():

            trackx, tracky, trackwidth, trackheight = hscrolltrackgeometry()
            graphicsrect(commands, trackx, tracky, trackwidth, trackheight, BG_COLOR, clip)
            graphicsborder(commands, trackx, tracky, trackwidth, trackheight, HSCROLL_BG_COLOR, clip)
            _, _, viewportwidth, _ = viewportgeometry()
            contentwidth = maxlinewidth()
            scrollrange = max(0, contentwidth - viewportwidth)
            thumbwidth = max(int(HSCROLL_MIN_THUMB), int(trackwidth * (viewportwidth / float(max(1, contentwidth)))))
            thumbwidth = min(trackwidth, thumbwidth)
            fraction = max(0.0, min(1.0, FIRST_VISIBLE_X / float(max(1, scrollrange))))
            thumbx = int(trackx + fraction * max(0, trackwidth - thumbwidth))
            graphicsborder(commands, thumbx, tracky, thumbwidth, trackheight, HSCROLL_THUMB_COLOR, clip)

    except Exception:
        pass


def graphicsbuildcursor(commands, clip):

    box = cursorbox(CUR_ROW, CUR_COL)

    if box is not None:
        graphicsrect(commands, box[0], box[1], box[2], box[3], CURSOR_COLOR, clip)


def graphicsbuildmenu(commands, clip):

    if not MENUBAR_OPEN:
        return

    panel = computemenupanel(MENUBAR_OPEN)

    if not panel:
        return

    panelx, panely, panelwidth, panelheight, name = panel
    panelclip = graphicsclip([panelx, panely, panelwidth, panelheight], clip)

    if panelclip is None:
        return

    graphicsrect(commands, panelx, panely, panelwidth, panelheight, MENU_BG, panelclip)
    graphicsborder(commands, panelx, panely, panelwidth, panelheight, MENU_BORDER, panelclip)
    items = menudefinitions().get(name, [])

    for index, (label, shortcut, action) in enumerate(items):

        itemy = panely + MENU_PAD_Y + index * MENU_ITEM_H
        texty = itemy + max(0, (MENU_ITEM_H - FONT_SIZE) // 2)

        if action == MENU_HOVER_ACTION:
            hoverx = panelx + 1
            hoverwidth = max(1, panelwidth - 2)
            graphicsrect(commands, hoverx, itemy, hoverwidth, MENU_ITEM_H, MENU_HOVER_BG, panelclip)
            graphicsrect(commands, hoverx, itemy, hoverwidth, 1, MENU_ROW_OUTLINE, panelclip)
            graphicsrect(commands, hoverx, itemy + MENU_ITEM_H - 1, hoverwidth, 1, MENU_ROW_OUTLINE, panelclip)

        graphicstext(commands, panelx + MENU_PAD_X, texty, str(label), MENU_TEXT, FONT_PATH, panelclip, rowkey=('menu', name, index, 'label'))

        if shortcut:

            shortcutwidth = int(measuretext(str(shortcut), FONT_SIZE, FONT_PATH))
            shortcutx = panelx + panelwidth - MENU_PAD_X - shortcutwidth
            graphicstext(commands, shortcutx, texty, str(shortcut), MENU_TEXT, FONT_PATH, panelclip, rowkey=('menu', name, index, 'shortcut'))

        if index < len(items) - 1:
            graphicsrect(commands, panelx, itemy + MENU_ITEM_H - 1, panelwidth, 1, MENU_BORDER, panelclip)


def graphicsbuildcontextmenu(commands, clip):

    if not CONTEXT_MENU_OPEN:
        return

    panel = computecontextpanel()

    if not panel:
        return

    panelx, panely, panelwidth, panelheight = panel
    panelclip = graphicsclip(panel, clip)

    if panelclip is None:
        return

    graphicsrect(commands, panelx, panely, panelwidth, panelheight, MENU_BG, panelclip, nodeid='write:context:background')
    graphicsborder(commands, panelx, panely, panelwidth, panelheight, MENU_BORDER, panelclip)

    items = contextmenudefinitions()

    for index, (label, shortcut, action) in enumerate(items):

        itemy = panely + CONTEXT_MENU_PAD_Y + index * MENU_ITEM_H
        texty = itemy + max(0, (MENU_ITEM_H - FONT_SIZE) // 2)
        colour = MENU_TEXT

        if action == CONTEXT_MENU_HOVER_ACTION:
            hoverx = panelx + 1
            hoverwidth = max(1, panelwidth - 2)
            graphicsrect(commands, hoverx, itemy, hoverwidth, MENU_ITEM_H, MENU_HOVER_BG, panelclip)
            graphicsrect(commands, hoverx, itemy, hoverwidth, 1, MENU_ROW_OUTLINE, panelclip)
            graphicsrect(commands, hoverx, itemy + MENU_ITEM_H - 1, hoverwidth, 1, MENU_ROW_OUTLINE, panelclip)

        graphicstext(
            commands,
            panelx + MENU_PAD_X,
            texty,
            str(label),
            colour,
            FONT_PATH,
            panelclip,
            rowkey=('context', index, 'label', bool(contextactionenabled(action))),
        )

        if shortcut:

            shortcutwidth = int(measuretext(str(shortcut), FONT_SIZE, FONT_PATH))
            shortcutx = panelx + panelwidth - MENU_PAD_X - shortcutwidth
            graphicstext(
                commands,
                shortcutx,
                texty,
                str(shortcut),
                colour,
                FONT_PATH,
                panelclip,
                rowkey=('context', index, 'shortcut', bool(contextactionenabled(action))),
            )

        if index < len(items) - 1:
            graphicsrect(commands, panelx, itemy + MENU_ITEM_H - 1, panelwidth, 1, MENU_BORDER, panelclip)


def graphicsbuildstatusbar(commands, clip):

    if not SHOW_STATUSBAR:
        return

    statusx, statusy, statuswidth, statusheight = statusbargeometry()
    statusclip = graphicsclip([statusx, statusy, statuswidth, statusheight], clip)

    if statusclip is None:
        return

    graphicsrect(commands, statusx, statusy, statuswidth, statusheight, (240, 240, 240), statusclip)

    if INPUT_MODE in ('open_path', 'save_path'):

        label = PROMPT_TEXT or ('open path ' if INPUT_MODE == 'open_path' else 'save as ')
        text = f'{label} {PROMPT_BUFFER}' if PROMPT_BUFFER else str(label)

    else:

        parts = [str(FILE_NAME or 'untitled.txt')]

        if IS_DIRTY:
            parts.append('(modified)')

        if LAST_STATUS_MESSAGE:
            parts.extend(('-', str(LAST_STATUS_MESSAGE)))

        text = ' '.join(parts)

    colour = STATUS_ERROR_COLOR if LAST_STATUS_MESSAGE == 'permission denied' else TEXT_COLOR
    texty = statusy + max(0, (statusheight - FONT_SIZE) // 2)
    graphicstext(commands, MARGIN_LEFT, texty, text, colour, FONT_PATH, statusclip, rowkey=('status', text))
    metrics = statusmetrictext()
    metricswidth = int(measuretext(metrics, FONT_SIZE, FONT_PATH)) if metrics else 0
    metricsx = max(MARGIN_LEFT, statusx + statuswidth - MARGIN_LEFT - metricswidth)

    if metrics and metricsx > MARGIN_LEFT + int(measuretext(text, FONT_SIZE, FONT_PATH)) + MARGIN_LEFT:
        graphicstext(
            commands,
            metricsx,
            texty,
            metrics,
            TEXT_COLOR,
            FONT_PATH,
            statusclip,
            rowkey=('status-metrics', metrics),
        )


def graphicsbuildscene():

    commands = []
    clip = graphicsclip([0, 0, WIN_W, WIN_H])

    if clip is None:
        return commands

    graphicsrect(commands, 0, 0, WIN_W, WIN_H, BG_COLOR, clip)
    graphicsbuildmenubar(commands, clip)
    graphicsbuilddocument(commands, clip)
    graphicsbuildcursor(commands, clip)
    graphicsbuildmenu(commands, clip)
    graphicsbuildcontextmenu(commands, clip)
    graphicsbuildstatusbar(commands, clip)
    graphicsbuildscrollbars(commands, clip, horizontal=True)
    graphicsbuildscrollbars(commands, clip)

    return commands


def graphicspump():

    global GRAPHICSSCENE

    wasavailable = bool(GRAPHICSSTATE.get('available'))

    if not managedtick(GRAPHICSSTATE):

        if wasavailable and ws_sock is not None and WINDOW_ID:
            sendmsg({
                'op': 'GRAPHICS_CLEAR',
                'winid': int(WINDOW_ID),
                'reason': str(GRAPHICSSTATE.get('failure', 'managed graphics timeout'))[:256],
            })
            graphicsscheduleretry()
            graphicsrestorecpu()

        return False

    if not GRAPHICSSTATE.get('available') or ws_sock is None or not WINDOW_ID:
        return False

    if GRAPHICSSTATE.get('pending') or not GRAPHICSSTATE.get('need_submit'):
        return bool(GRAPHICSSTATE.get('active'))

    graphicspreparescenerebuild()
    commands = graphicsbuildscene()

    if not commands or commands[0].get('kind') != 'rectangle' or commands[0].get('rect') != [0, 0, int(WIN_W), int(WIN_H)]:
        return graphicsdisable('managed scene does not contain a complete background')

    beforeavailable = bool(GRAPHICSSTATE.get('available'))
    managedsubmit(GRAPHICSSTATE, sendmsg, WINDOW_ID, commands)

    if beforeavailable and not GRAPHICSSTATE.get('available'):

        sendmsg({
            'op': 'GRAPHICS_CLEAR',
            'winid': int(WINDOW_ID),
            'reason': str(GRAPHICSSTATE.get('failure', 'managed scene submission failed'))[:256],
        })
        graphicsscheduleretry()
        graphicsdamage()

    if GRAPHICSSTATE.get('pending'):
        GRAPHICSSCENE = commands

    return bool(GRAPHICSSTATE.get('active'))


def graphicspresent(dirty=None):

    if not GRAPHICSSTATE.get('available'):
        return False

    if dirty is None:
        GRAPHICSSTATE['need_submit'] = True

    else:
        managedmarkdamage(GRAPHICSSTATE, dirty, bounds=(int(WIN_W), int(WIN_H)))

    graphicspump()
    return bool(GRAPHICSSTATE.get('active'))


def graphicsmanagedredraw(rect):

    if not GRAPHICSSTATE.get('active') or not GRAPHICSSTATE.get('managed_only'):
        return False

    try:

        rects = rect if rect and isinstance(rect[0], (list, tuple)) else [rect]

        for value in rects:
            managedmarkdamage(GRAPHICSSTATE, value, bounds=(int(WIN_W), int(WIN_H)))

        graphicspump()

        if not GRAPHICSSTATE.get('active'):
            return False

    except Exception:
        return False

    try:
        resetdirty()
    except Exception:
        pass

    return True


def presentchanges():

    global WIN_W, WIN_H

    try:

        # get dirty region from graphics
        dirty = getdirty()

        if not dirty:

            # nothing to present
            return

        x, y, w, h = dirty

    except Exception:

        # fall back to full window
        x, y, w, h = 0, 0, WIN_W, WIN_H

    try:

        # present only the dirty region
        presentdirty(x, y, w, h)

    except Exception as e:

        # present dirty error
        logmsg(f"> error presenting dirty region {e}")
        return

    managed = False

    try:

        managed = graphicspresent([x, y, w, h])

    except Exception as e:

        logmsg(f"> error submitting managed graphics scene {e}")

    if not managed:

        try:

            # tell window server about the CPU buffer change
            senddamage(x, y, w, h)

        except Exception as e:

            # send damage error
            logmsg(f"> error sending damage for dirty region {e}")


    # reset dirty tracking for next frame
    resetdirty()

    return


def clearwindow():

    global BG_COLOR

    try:

        # clear full window to background color
        clear(BG_COLOR)

    except Exception as e:

        # clear error
        logmsg(f'> error clearing window {e}')
        return

    return


def queuedeferredredraw(mode, horizontal=False, vertical=False):

    global PENDING_RENDER_MODE
    global PENDING_RENDER_HORIZONTAL
    global PENDING_RENDER_VERTICAL

    PENDING_RENDER_MODE = max(int(PENDING_RENDER_MODE), int(mode))
    PENDING_RENDER_HORIZONTAL = bool(PENDING_RENDER_HORIZONTAL or horizontal)
    PENDING_RENDER_VERTICAL = bool(PENDING_RENDER_VERTICAL or vertical)


def beginrenderbatch():

    global RENDER_BATCH_DEPTH
    RENDER_BATCH_DEPTH += 1


def endrenderbatch(flush=True):

    global RENDER_BATCH_DEPTH

    RENDER_BATCH_DEPTH = max(0, int(RENDER_BATCH_DEPTH) - 1)

    if flush and RENDER_BATCH_DEPTH == 0:
        flushdeferredredraw()


def flushdeferredredraw():

    global PENDING_RENDER_MODE
    global PENDING_RENDER_HORIZONTAL
    global PENDING_RENDER_VERTICAL

    if RENDER_BATCH_DEPTH or not PENDING_RENDER_MODE:
        return False

    mode = int(PENDING_RENDER_MODE)
    horizontal = bool(PENDING_RENDER_HORIZONTAL)
    vertical = bool(PENDING_RENDER_VERTICAL)
    PENDING_RENDER_MODE = 0
    PENDING_RENDER_HORIZONTAL = False
    PENDING_RENDER_VERTICAL = False

    if mode >= 4:
        redrawfull()
    elif mode == 3:
        redrawviewport(horizontal=horizontal, vertical=vertical)
    elif mode == 2:
        redrawregionaroundcursororline()
    else:
        redrawstatusbar()

    return True


def rectunion(a, b):

    if not a:
        return b

    if not b:
        return a

    ax, ay, aw, ah = a
    bx, by, bw, bh = b

    x0 = min(ax, bx)
    y0 = min(ay, by)

    x1 = max(ax + aw, bx + bw)
    y1 = max(ay + ah, by + bh)

    return x0, y0, (x1 - x0), (y1 - y0)


def cliprect(r):

    if not r:
        return None

    x, y, w, h = r

    if w <= 0 or h <= 0:
        return None

    x0 = max(0, x)
    y0 = max(0, y)

    x1 = min(WIN_W, x + w)
    y1 = min(WIN_H, y + h)

    w2 = x1 - x0
    h2 = y1 - y0

    if w2 <= 0 or h2 <= 0:
        return None

    return x0, y0, w2, h2


def linebox(docrow):

    try:

        vx, vy, vw, vh = viewportgeometry()

        if vw <= 0 or vh <= 0 or LINE_HEIGHT <= 0:
            return None

        visible = vh // LINE_HEIGHT

        if visible <= 0:
            return None

        if WORD_WRAP:
            ensurewrapindex()
            docrow = max(0, min(len(DOC_LINES) - 1, int(docrow)))
            firstvisual = wraptreeprefix(docrow)
            count = max(1, int(WRAP_LINE_COUNTS[docrow]))
            lastvisual = firstvisual + count - 1
            visiblefirst = max(firstvisual, int(FIRST_VISIBLE_ROW))
            visiblelast = min(lastvisual, int(FIRST_VISIBLE_ROW) + visible - 1)

            if visiblelast < visiblefirst:
                return None

            rowoff = visiblefirst - int(FIRST_VISIBLE_ROW)
            height = (visiblelast - visiblefirst + 1) * int(LINE_HEIGHT)
            return int(vx), int(vy + rowoff * LINE_HEIGHT), int(vw), int(height)

        rowoff = int(docrow) - int(FIRST_VISIBLE_ROW)

        if rowoff < 0 or rowoff >= visible:
            return None

        return int(vx), int(vy + rowoff * LINE_HEIGHT), int(vw), int(LINE_HEIGHT)

    except Exception as e:

        logmsg(f'> error computing line box {e}')
        return None


def cursorbox(row, col):

    if not HAS_FOCUS:
        return None

    if not CURSOR_VISIBLE:
        return None

    try:

        vx, vy, vw, vh = viewportgeometry()

        if vh <= 0 or LINE_HEIGHT <= 0:
            return None

        visible = vh // LINE_HEIGHT

        if visible <= 0:
            return None

        visualrow = cursorvisualindex(row, col)
        rowoff = visualrow - FIRST_VISIBLE_ROW

        if rowoff < 0 or rowoff >= visible:
            return None

        if row < 0 or row >= len(DOC_LINES):
            line = ''
        else:
            try:
                line = str(DOC_LINES[row])
            except Exception:
                line = ''

        if col < 0:
            col = 0

        if col > len(line):
            col = len(line)

        segmentstart = displaysegment(visualrow)[1] if WORD_WRAP else 0
        pw = lineadvanceat(row, line, col, segmentstart)

        x = (MARGIN_LEFT - (0 if WORD_WRAP else FIRST_VISIBLE_X)) + pw
        y = MARGIN_TOP + (rowoff * LINE_HEIGHT)

        h = LINE_HEIGHT

        if h <= 0:
            h = FONT_SIZE

        if h <= 0:
            h = 1

        return int(x), int(y), int(CURSOR_WIDTH), int(h)

    except Exception as e:

        logmsg(f'> error computing cursor box {e}')
        return None


def drawstatusbar():

    global SHOW_STATUSBAR
    global FILE_NAME
    global IS_DIRTY
    global LAST_STATUS_MESSAGE
    global FONT_SIZE
    global MARGIN_LEFT
    global TEXT_COLOR
    global INPUT_MODE
    global PROMPT_TEXT
    global PROMPT_BUFFER

    if not SHOW_STATUSBAR:

        # status bar disabled
        return

    try:

        sx, sy, sw, sh = statusbargeometry()

        if sw <= 0 or sh <= 0:
            return

        # draw status bar background
        status_bg = (240, 240, 240)

        fillrectfast(sx, sy, sw, sh, status_bg)

    except Exception as e:

        # error drawing status bar background
        logmsg(f'> error drawing status bar background {e}')
        return

    try:

        # build main status text (left side)
        if INPUT_MODE == 'open_path' or INPUT_MODE == 'save_path':

            try:

                label = PROMPT_TEXT

                if not label:

                    if INPUT_MODE == 'open_path':

                        label = 'open path '

                    else:

                        label = 'save as '

            except Exception:

                if INPUT_MODE == 'open_path':

                    label = 'open path '

                else:

                    label = 'save as '

            try:

                buf = str(PROMPT_BUFFER)

            except Exception:

                buf = ''

            if buf:

                status_text = f'{label} {buf}'

            else:

                status_text = str(label)

        else:

            parts = []

            if FILE_NAME:

                parts.append(str(FILE_NAME))

            else:

                parts.append('untitled.txt')

            if IS_DIRTY:

                parts.append('(modified)')

            if LAST_STATUS_MESSAGE:

                parts.append('-')
                parts.append(str(LAST_STATUS_MESSAGE))

            status_text = ' '.join(parts)

        # vertical position shared by both texts
        text_y = sy + max(0, (sh - FONT_SIZE) // 2)

        # compute positions
        left_x = MARGIN_LEFT

        left_colour = TEXT_COLOR


        if LAST_STATUS_MESSAGE == 'permission denied':

            status_text = 'permission denied'
            left_colour = STATUS_ERROR_COLOR

        drawtextttf(left_x, text_y, status_text, left_colour, FONT_SIZE)
        metrics = statusmetrictext()

        if metrics:
            metricswidth = int(measuretext(metrics, FONT_SIZE, FONT_PATH))
            metricsx = max(MARGIN_LEFT, sx + sw - MARGIN_LEFT - metricswidth)

            if metricsx > left_x + int(measuretext(status_text, FONT_SIZE, FONT_PATH)) + MARGIN_LEFT:
                drawtextttf(metricsx, text_y, metrics, TEXT_COLOR, FONT_SIZE, FONT_PATH)

    except Exception as e:

        # error drawing status bar text
        logmsg(f'> error drawing status bar text {e}')
        return

    return


    if not SHOW_STATUSBAR:

        # status bar disabled
        return

    try:

        # compute status bar geometry
        y0 = WIN_H - STATUSBAR_HEIGHT

        if y0 < 0:

            y0 = 0

        # draw status bar background
        status_bg = (240, 240, 240)

        drawrect(0, y0, WIN_W, STATUSBAR_HEIGHT, status_bg)

    except Exception as e:

        # error drawing status bar background
        logmsg(f'> error drawing status bar background {e}')
        return

    try:

        # build main status text (left side)
        if INPUT_MODE == 'open_path' or INPUT_MODE == 'save_path':

            try:

                label = PROMPT_TEXT

                if not label:

                    if INPUT_MODE == 'open_path':

                        label = 'open path '

                    else:

                        label = 'save as '

            except Exception:

                if INPUT_MODE == 'open_path':

                    label = 'open path '

                else:

                    label = 'save as '

            try:

                buf = str(PROMPT_BUFFER)

            except Exception:

                buf = ''

            if buf:

                status_text = f'{label} {buf}'

            else:

                status_text = str(label)

        else:

            parts = []

            if FILE_NAME:

                parts.append(str(FILE_NAME))

            else:

                parts.append('untitled.txt')

            if IS_DIRTY:

                parts.append('(modified)')

            if LAST_STATUS_MESSAGE:

                parts.append('-')
                parts.append(str(LAST_STATUS_MESSAGE))

            status_text = ' '.join(parts)

        # shortcut hint text (right side)
        shortcut_text = 'ctr-n to start anew  ctrl-o to open  ctrl-s to save  ctrl-g to save as'

        # vertical position shared by both texts
        text_y = y0 + max(0, (STATUSBAR_HEIGHT - FONT_SIZE) // 2)

        # measure widths for layout
        try:

            left_width = measuretext(status_text, FONT_SIZE)

        except Exception:

            left_width = 0

        try:

            right_width = measuretext(shortcut_text, FONT_SIZE)

        except Exception:

            right_width = 0

        # compute positions
        left_x = MARGIN_LEFT

        right_margin = MARGIN_LEFT

        right_x = WIN_W - right_margin - right_width

        # ensure right text does not go off-screen
        if right_x < 0:

            right_x = 0

        # choose left text and colour (permission denied overrides filename)
        left_colour = TEXT_COLOR


        if LAST_STATUS_MESSAGE == 'permission denied':

            status_text = 'permission denied'
            left_colour = STATUS_ERROR_COLOR

        drawtextttf(left_x, text_y, status_text, left_colour, FONT_SIZE)

        # draw right shortcut help text
        drawtextttf(right_x, text_y, shortcut_text, TEXT_COLOR, FONT_SIZE)

    except Exception as e:

        # error drawing status bar text
        logmsg(f'> error drawing status bar text {e}')
        return

    return


def drawscrollbar():

    global DOC_LINES
    global FIRST_VISIBLE_ROW
    global VISIBLE_LINES
    global SCROLLBAR_MIN_THUMB
    global SCROLLBAR_BG_COLOR
    global SCROLLBAR_THUMB_COLOR

    try:

        if VISIBLE_LINES <= 0 or displaylinecount() <= VISIBLE_LINES:
            return

        track_x, track_y, track_w, track_h = scrollbartrackgeometry()
        thumb_x, thumb_y, thumb_w, thumb_h = scrollbarthumbgeometry()

        if track_w <= 0 or track_h <= 0 or thumb_w <= 0 or thumb_h <= 0:
            return

        fillrectfast(track_x, track_y, track_w, track_h, BG_COLOR)
        drawrect(track_x, track_y, track_w, track_h, SCROLLBAR_BG_COLOR)
        drawrect(thumb_x, thumb_y, thumb_w, thumb_h, SCROLLBAR_THUMB_COLOR)

    except Exception as e:

        logmsg(f'> error drawing scrollbar {e}')
        return

    return


def drawhscrollbar():

    global FIRST_VISIBLE_X
    global HSCROLL_MIN_THUMB
    global HSCROLL_BG_COLOR
    global HSCROLL_THUMB_COLOR

    try:

        if not horizontalneeded():
            return

        track_x, track_y, track_w, track_h = hscrolltrackgeometry()

        if track_w <= 0 or track_h <= 0:
            return

        fillrectfast(track_x, track_y, track_w, track_h, BG_COLOR)
        drawrect(track_x, track_y, track_w, track_h, HSCROLL_BG_COLOR)

        vx, vy, vw, vh = viewportgeometry()

        content_w = maxlinewidth()

        scroll_range = content_w - vw

        if scroll_range <= 0:
            return

        try:
            thumb_w = int(track_w * (vw / float(content_w)))
        except Exception:
            thumb_w = HSCROLL_MIN_THUMB

        if thumb_w < HSCROLL_MIN_THUMB:
            thumb_w = HSCROLL_MIN_THUMB

        if thumb_w > track_w:
            thumb_w = track_w

        if track_w - thumb_w <= 0:
            thumb_x = track_x
        else:
            try:
                frac = FIRST_VISIBLE_X / float(scroll_range)
            except Exception:
                frac = 0.0

            if frac < 0.0:
                frac = 0.0

            if frac > 1.0:
                frac = 1.0

            thumb_x = int(track_x + frac * (track_w - thumb_w))

        drawrect(thumb_x, track_y, thumb_w, track_h, HSCROLL_THUMB_COLOR)

    except Exception as e:

        logmsg(f'> error drawing horizontal scrollbar {e}')
        return

    return


def drawdisplayrow(displayrow, viewport=None):

    if viewport is None:
        viewport = viewportgeometry()

    viewport_x, viewport_y, viewport_width, viewport_height = viewport
    visibleindex = int(displayrow) - int(FIRST_VISIBLE_ROW)

    if visibleindex < 0 or visibleindex * LINE_HEIGHT >= viewport_height:
        return

    if WORD_WRAP:
        docrow, start, end = displaysegment(displayrow)
    else:
        docrow, start, end = int(displayrow), 0, None

    if docrow < 0 or docrow >= len(DOC_LINES):
        line = ''
    else:
        docwidthindexline(docrow)
        line = str(DOC_LINES[docrow])[start:end]

    xbase = MARGIN_LEFT - (0 if WORD_WRAP else FIRST_VISIBLE_X)
    y = viewport_y + visibleindex * LINE_HEIGHT
    line, linex, start = visiblelineslice(
        docrow,
        line,
        xbase,
        viewport_x,
        viewport_width,
        start,
        fully_visible=True,
    )
    drawlinewithselection(linex, y, docrow, line, start)


def drawdisplayrange(firstrow, lastrow, viewport=None):

    if viewport is None:
        viewport = viewportgeometry()

    total = displaylinecount()
    firstrow = max(int(FIRST_VISIBLE_ROW), int(firstrow))
    lastvisible = int(FIRST_VISIBLE_ROW) + max(0, int(VISIBLE_LINES)) - 1
    lastrow = min(lastvisible, int(lastrow), max(0, total - 1))

    for displayrow in range(firstrow, lastrow + 1):
        drawdisplayrow(displayrow, viewport=viewport)


def drawdocumentlines():

    global DOC_LINES
    global FIRST_VISIBLE_ROW
    global MARGIN_TOP
    global MARGIN_LEFT
    global LINE_HEIGHT
    global FONT_SIZE
    global TEXT_COLOR
    global VISIBLE_LINES
    global FIRST_VISIBLE_X
    global WIN_H
    global SHOW_STATUSBAR
    global STATUSBAR_HEIGHT

    try:

        viewport_x, viewport_y, viewport_width, viewport_height = viewportgeometry()

        if viewport_width <= 0 or viewport_height <= 0 or LINE_HEIGHT <= 0:

            VISIBLE_LINES = 0
            return

        # Use the same viewport as clearing, hit-testing, and managed drawing.
        # This reserves both scrollbar tracks and the status bar while scrolling.
        visible_count = viewport_height // LINE_HEIGHT

        VISIBLE_LINES = visible_count

        if visible_count <= 0:
            return

        drawdisplayrange(
            FIRST_VISIBLE_ROW,
            FIRST_VISIBLE_ROW + visible_count - 1,
            viewport=(viewport_x, viewport_y, viewport_width, viewport_height),
        )

    except Exception as e:

        # error drawing document lines
        logmsg(f'> error drawing document lines {e}')
        return

    return


def drawcursor():

    global DOC_LINES
    global CUR_ROW
    global CUR_COL
    global FIRST_VISIBLE_ROW
    global MARGIN_TOP
    global MARGIN_LEFT
    global LINE_HEIGHT
    global FONT_SIZE
    global CURSOR_WIDTH
    global CURSOR_COLOR
    global HAS_FOCUS
    global CURSOR_VISIBLE
    global FIRST_VISIBLE_X

    if not HAS_FOCUS:

        return

    if not CURSOR_VISIBLE:

        return

    try:

        vx, vy, vw, vh = viewportgeometry()

        if vh <= 0 or LINE_HEIGHT <= 0:
            return

        visible_count = vh // LINE_HEIGHT

        if visible_count <= 0:
            return

        visualrow = cursorvisualindex(CUR_ROW, CUR_COL)
        row_offset = visualrow - FIRST_VISIBLE_ROW

        if row_offset < 0 or row_offset >= visible_count:
            return

        if CUR_ROW < 0 or CUR_ROW >= len(DOC_LINES):

            line_text = ''

        else:

            try:
                line_text = DOC_LINES[CUR_ROW]
            except Exception:
                line_text = ''

        line_text = str(line_text)

        if CUR_COL < 0:
            CUR_COL = 0

        if CUR_COL > len(line_text):
            CUR_COL = len(line_text)

        segmentstart = displaysegment(visualrow)[1] if WORD_WRAP else 0
        prefix_width = lineadvanceat(CUR_ROW, line_text, CUR_COL, segmentstart)

        x = (MARGIN_LEFT - (0 if WORD_WRAP else FIRST_VISIBLE_X)) + prefix_width

        y = MARGIN_TOP + (row_offset * LINE_HEIGHT)

        height = LINE_HEIGHT

        if height <= 0:
            height = FONT_SIZE

        if height <= 0:
            height = 1

        fillrectfast(int(x), int(y), CURSOR_WIDTH, int(height), CURSOR_COLOR)

    except Exception as e:

        logmsg(f'> error drawing cursor {e}')
        return

    return


def redrawfull():

    global WIN_W
    global WIN_H
    global LASTDRAWNROW
    global LASTDRAWNCOL
    global LAST_PRESENTED_FIRST_ROW
    global LAST_PRESENTED_VIEWPORT

    if RENDER_BATCH_DEPTH:
        queuedeferredredraw(4)
        return

    clampxscroll()

    if graphicsmanagedredraw([0, 0, int(WIN_W), int(WIN_H)]):
        LASTDRAWNROW = CUR_ROW
        LASTDRAWNCOL = CUR_COL
        LAST_PRESENTED_FIRST_ROW = int(FIRST_VISIBLE_ROW)
        LAST_PRESENTED_VIEWPORT = tuple(viewportgeometry())
        return

    try:

        clearwindow()

    except Exception as e:

        logmsg(f'> error in redraw clear {e}')
        return

    try:

        drawmenubar()

    except Exception as e:

        logmsg(f'> error drawing menubar in redraw {e}')
        return

    try:

        drawdocumentlines()

    except Exception as e:

        logmsg(f'> error drawing document in redraw {e}')
        return

    try:

        drawcursor()

    except Exception as e:

        logmsg(f'> error drawing cursor in redraw {e}')
        return

    try:

        drawopenmenu()

    except Exception as e:

        logmsg(f'> error drawing open menu in redraw {e}')

    try:

        drawcontextmenu()

    except Exception as e:

        logmsg(f'> error drawing context menu in redraw {e}')

    try:

        drawstatusbar()

    except Exception as e:

        logmsg(f'> error drawing status bar in redraw {e}')
        return

    try:

        drawhscrollbar()

    except Exception as e:

        logmsg(f'> error drawing horizontal scrollbar in redraw {e}')
        return

    try:

        # The vertical scrollbar owns the full right edge, including the
        # status and horizontal-scrollbar bands beneath it.
        drawscrollbar()

    except Exception as e:

        logmsg(f'> error drawing scrollbar in redraw {e}')
        return

    try:

        # update display with changes
        presentchanges()

    except Exception as e:

        logmsg(f'> error updating display in redraw full {e}')

    LASTDRAWNROW = CUR_ROW
    LASTDRAWNCOL = CUR_COL
    LAST_PRESENTED_FIRST_ROW = int(FIRST_VISIBLE_ROW)
    LAST_PRESENTED_VIEWPORT = tuple(viewportgeometry())
    return


def redrawviewport(horizontal=False, vertical=False):

    global BG_COLOR
    global LASTDRAWNROW
    global LASTDRAWNCOL
    global LAST_PRESENTED_FIRST_ROW
    global LAST_PRESENTED_VIEWPORT
    global VISIBLE_LINES

    if RENDER_BATCH_DEPTH:
        queuedeferredredraw(3, horizontal=horizontal, vertical=vertical)
        return

    clampxscroll()

    try:

        vx, vy, vw, vh = viewportgeometry()

    except Exception as e:

        logmsg(f'> error computing viewport geometry {e}')

        return

    if vw <= 0 or vh <= 0:

        return

    if graphicsmanagedredraw(viewportredrawdamage(horizontal=horizontal, vertical=vertical)):
        LASTDRAWNROW = CUR_ROW
        LASTDRAWNCOL = CUR_COL
        LAST_PRESENTED_FIRST_ROW = int(FIRST_VISIBLE_ROW)
        LAST_PRESENTED_VIEWPORT = (int(vx), int(vy), int(vw), int(vh))
        return

    visible = max(0, int(vh) // max(1, int(LINE_HEIGHT)))
    VISIBLE_LINES = visible
    scrolled = False
    delta = 0

    try:

        if (
            vertical
            and not horizontal
            and visible > 0
            and LAST_PRESENTED_FIRST_ROW is not None
            and tuple(LAST_PRESENTED_VIEWPORT or ()) == (int(vx), int(vy), int(vw), int(vh))
        ):
            delta = int(FIRST_VISIBLE_ROW) - int(LAST_PRESENTED_FIRST_ROW)

            if 0 < abs(delta) < visible:
                documentheight = visible * int(LINE_HEIGHT)
                scrolled = bool(gfx.scrollrect(0, vy, vx + vw, documentheight, dy=-delta * int(LINE_HEIGHT)))

        if scrolled:

            exposed = abs(delta)

            if delta > 0:
                firstscreenrow = visible - exposed
                firstdisplayrow = int(FIRST_VISIBLE_ROW) + firstscreenrow
            else:
                firstscreenrow = 0
                firstdisplayrow = int(FIRST_VISIBLE_ROW)

            exposedtop = int(vy) + firstscreenrow * int(LINE_HEIGHT)
            exposedheight = exposed * int(LINE_HEIGHT)
            fillrectfast(0, exposedtop, vx + vw, exposedheight, BG_COLOR)
            drawdisplayrange(
                firstdisplayrow,
                firstdisplayrow + exposed - 1,
                viewport=(vx, vy, vw, vh),
            )

        else:
            # Include the left gutter. CPU text has no hardware clip, so this
            # also removes edge pixels left by partially visible glyphs.
            fillrectfast(0, vy, vx + vw, vh, BG_COLOR)
            drawdocumentlines()

    except Exception as e:

        logmsg(f'> error updating viewport pixels {e}')

        return

    try:

        drawhscrollbar()

    except Exception as e:

        logmsg(f'> error drawing hscrollbar in viewport redraw {e}')

        return

    try:

        drawcursor()

    except Exception as e:

        logmsg(f'> error drawing cursor in viewport redraw {e}')

        return

    try:

        # Draw this last so document, status, and horizontal content cannot
        # enter the right-edge scrollbar column.
        drawscrollbar()

    except Exception as e:

        logmsg(f'> error drawing scrollbar in viewport redraw {e}')

        return

    try:

        presentchanges()

    except Exception as e:

        logmsg(f'> error presenting viewport redraw {e}')

    LASTDRAWNROW = CUR_ROW
    LASTDRAWNCOL = CUR_COL
    LAST_PRESENTED_FIRST_ROW = int(FIRST_VISIBLE_ROW)
    LAST_PRESENTED_VIEWPORT = tuple(viewportgeometry())
    return


def redrawstatusbar():

    if RENDER_BATCH_DEPTH:
        queuedeferredredraw(1)
        return

    try:

        sx, sy, sw, sh = statusbargeometry()

        if sw < 1 or sh < 1:
            return

        if graphicsmanagedredraw([int(sx), int(sy), int(sw), int(sh)]):
            return

        fillrectfast(sx, sy, sw, sh, BG_COLOR)
        drawstatusbar()
        drawscrollbar()
        presentchanges()

    except Exception as e:

        logmsg(f'> error redrawing status bar {e}')

    return


def redrawrowspan(oldrow, newrow):

    try:
        oldrow = int(oldrow)
        newrow = int(newrow)
    except Exception:
        return ()

    if oldrow >= 0 and newrow >= 0:
        return range(min(oldrow, newrow), max(oldrow, newrow) + 1)

    return tuple(dict.fromkeys((oldrow, newrow)))


def redrawregionaroundcursororline():

    global LASTDRAWNROW
    global LASTDRAWNCOL
    global WRAP_REFLOW_FROM
    global DOCUMENT_REFLOW_ROW

    if RENDER_BATCH_DEPTH:
        queuedeferredredraw(2)
        return

    if MENUBAR_OPEN or CONTEXT_MENU_OPEN:

        redrawfull()
        return

    try:

        # figure out what changed (old caret vs new caret)
        oldrow = LASTDRAWNROW
        oldcol = LASTDRAWNCOL

        newrow = CUR_ROW
        newcol = CUR_COL

        dirty = None

        if WORD_WRAP:
            ensurewrapindex()

        reflowvisual = None

        if DOCUMENT_REFLOW_ROW is not None:
            reflowrow = max(0, min(len(DOC_LINES) - 1, int(DOCUMENT_REFLOW_ROW)))
            reflowvisual = cursorvisualindex(reflowrow, 0) if WORD_WRAP else reflowrow
            DOCUMENT_REFLOW_ROW = None

        if WORD_WRAP and WRAP_REFLOW_FROM is not None:

            if reflowvisual is None:
                reflowvisual = int(WRAP_REFLOW_FROM)
            else:
                reflowvisual = min(int(reflowvisual), int(WRAP_REFLOW_FROM))

            WRAP_REFLOW_FROM = None

        if reflowvisual is not None:
            vx, vy, vw, vh = viewportgeometry()
            firstdirty = max(int(FIRST_VISIBLE_ROW), int(reflowvisual))
            lastvisible = int(FIRST_VISIBLE_ROW) + max(0, int(VISIBLE_LINES)) - 1

            if firstdirty <= lastvisible:
                top = int(vy) + (firstdirty - int(FIRST_VISIBLE_ROW)) * int(LINE_HEIGHT)
                dirty = (int(vx), top, int(vw), max(0, int(vy + vh - top)))

        dirty = rectunion(dirty, linebox(oldrow))
        dirty = rectunion(dirty, linebox(newrow))

        dirty = rectunion(dirty, cursorbox(oldrow, oldcol))
        dirty = rectunion(dirty, cursorbox(newrow, newcol))

        dirty = cliprect(dirty)

        if not dirty:

            # nothing visible changed
            LASTDRAWNROW = newrow
            LASTDRAWNCOL = newcol
            return

        dx, dy, dw, dh = dirty

    except Exception as e:

        logmsg(f'> error computing redraw region {e}')
        return

    if graphicsmanagedredraw([int(dx), int(dy), int(dw), int(dh)]):

        LASTDRAWNROW = newrow
        LASTDRAWNCOL = newcol
        return

    try:

        # clear only the dirty region
        fillrectfast(dx, dy, dw, dh, BG_COLOR)

    except Exception as e:

        logmsg(f'> error clearing redraw region {e}')
        return

    try:

        vx, vy, vw, vh = viewportgeometry()
        firstdisplay = int(FIRST_VISIBLE_ROW) + max(
            0,
            (int(dy) - int(vy)) // max(1, int(LINE_HEIGHT)),
        )
        lastdisplay = int(FIRST_VISIBLE_ROW) + max(
            0,
            (int(dy + dh - 1) - int(vy)) // max(1, int(LINE_HEIGHT)),
        )
        drawdisplayrange(
            firstdisplay,
            lastdisplay,
            viewport=(vx, vy, vw, vh),
        )

    except Exception as e:

        logmsg(f'> error redrawing affected lines {e}')
        return

    try:

        # redraw cursor at its new position
        drawcursor()

    except Exception as e:

        logmsg(f'> error redrawing cursor {e}')
        return

    try:

        # update display with changes
        presentchanges()

    except Exception as e:

        logmsg(f'> error updating display in redraw region {e}')

    try:

        # Retained rendering already refreshed its status nodes.  Keep CPU
        # status damage separate so a one-line edit does not copy the full
        # height between the document row and the status bar.
        drawstatusbar()
        presentchanges()

    except Exception as e:

        logmsg(f'> error updating live status metrics {e}')


    # update last drawn caret
    LASTDRAWNROW = newrow
    LASTDRAWNCOL = newcol

    return


def updatelayoutonresize(redraw=True):

    global BUFFER_PATH
    global WIN_W
    global WIN_H
    global DOC_LINES
    global FIRST_VISIBLE_ROW
    global VISIBLE_LINES

    try:

        if BUFFER_PATH:

            initbuffer(BUFFER_PATH, WIN_W, WIN_H)

    except Exception as e:

        logmsg(f'> error reinitialising graphics buffer after resize {e}')
        return

    try:

        vx, vy, vw, vh = viewportgeometry()

        if vh <= 0:

            VISIBLE_LINES = 0

        else:

            if LINE_HEIGHT > 0:
                VISIBLE_LINES = vh // LINE_HEIGHT
            else:
                VISIBLE_LINES = 0

        max_first = 0

        if VISIBLE_LINES > 0 and displaylinecount() > VISIBLE_LINES:

            max_first = displaylinecount() - VISIBLE_LINES

        if FIRST_VISIBLE_ROW > max_first:

            FIRST_VISIBLE_ROW = max_first

        if FIRST_VISIBLE_ROW < 0:

            FIRST_VISIBLE_ROW = 0

        clampxscroll()

    except Exception as e:

        logmsg(f'> error updating layout after resize {e}')

    if redraw:

        try:

            redrawfull()

        except Exception as e:

            logmsg(f'> error redrawing after resize {e}')

    return


    try:

        # reinitialise buffer with new dimensions
        if BUFFER_PATH:

            initbuffer(BUFFER_PATH, WIN_W, WIN_H)

    except Exception as e:

        # error reinitialising buffer
        logmsg(f'> error reinitialising graphics buffer after resize {e}')
        return

    try:

        # recompute visible lines
        bottom_limit = WIN_W

        bottom_limit = WIN_H

        if SHOW_STATUSBAR:
            bottom_limit -= STATUSBAR_HEIGHT

        usable_height = bottom_limit - MARGIN_TOP

        if usable_height <= 0 or LINE_HEIGHT <= 0:

            VISIBLE_LINES = 0

        else:

            VISIBLE_LINES = usable_height // LINE_HEIGHT

        # clamp scroll offset so last lines can still be reached
        max_first = 0

        if VISIBLE_LINES > 0 and len(DOC_LINES) > VISIBLE_LINES:

            max_first = len(DOC_LINES) - VISIBLE_LINES

        if FIRST_VISIBLE_ROW > max_first:

            FIRST_VISIBLE_ROW = max_first

        if FIRST_VISIBLE_ROW < 0:

            FIRST_VISIBLE_ROW = 0

    except Exception as e:

        # error updating layout metrics
        logmsg(f'> error updating layout after resize {e}')

    try:

        # redraw to reflect new size
        redrawfull()

    except Exception as e:

        # redraw error after resize
        logmsg(f'> error redrawing after resize {e}')

    return


def scrollbartrackgeometry():

    global WIN_W
    global WIN_H
    global MARGIN_TOP
    global STATUSBAR_HEIGHT
    global SHOW_STATUSBAR
    global SCROLLBAR_WIDTH
    global SCROLLBAR_MARGIN
    global HSCROLL_HEIGHT

    try:

        track_x = WIN_W - SCROLLBAR_WIDTH

        if track_x < 0:
            track_x = 0

        track_y = MARGIN_TOP

        track_h = WIN_H - track_y

        if track_h < 0:
            track_h = 0

        return track_x, track_y, SCROLLBAR_WIDTH, track_h

    except Exception as e:

        logmsg(f'> error computing scrollbar track geometry {e}')
        return 0, 0, 0, 0


def scrollbarthumbgeometry():

    global DOC_LINES
    global FIRST_VISIBLE_ROW
    global VISIBLE_LINES
    global SCROLLBAR_MIN_THUMB

    try:

        total_lines = displaylinecount()
        track_x, track_y, track_w, track_h = scrollbartrackgeometry()

        if VISIBLE_LINES <= 0 or total_lines <= VISIBLE_LINES or track_w <= 0 or track_h <= 0:
            return 0, 0, 0, 0

        scroll_range = total_lines - VISIBLE_LINES
        thumb_h = int(track_h * (VISIBLE_LINES / float(total_lines)))
        thumb_h = max(int(SCROLLBAR_MIN_THUMB), min(int(track_h), int(thumb_h)))
        fraction = FIRST_VISIBLE_ROW / float(max(1, scroll_range))
        fraction = max(0.0, min(1.0, fraction))
        thumb_y = int(track_y + fraction * max(0, track_h - thumb_h))
        return int(track_x), int(thumb_y), int(track_w), int(thumb_h)

    except Exception as e:

        logmsg(f'> error computing scrollbar thumb geometry {e}')
        return 0, 0, 0, 0

def viewportgeometry():

    global WIN_W
    global WIN_H
    global MARGIN_LEFT
    global MARGIN_TOP
    global STATUSBAR_HEIGHT
    global SHOW_STATUSBAR
    global SCROLLBAR_WIDTH
    global SCROLLBAR_MARGIN
    global HSCROLL_HEIGHT

    try:

        bottom = WIN_H

        if horizontalneeded():
            bottom -= HSCROLL_HEIGHT

        if SHOW_STATUSBAR:
            bottom -= STATUSBAR_HEIGHT

        if bottom < 0:
            bottom = 0

        right = WIN_W

        if verticalneeded():
            right -= SCROLLBAR_WIDTH

        if right < 0:
            right = 0

        x0 = MARGIN_LEFT
        y0 = MARGIN_TOP

        w = right - x0
        h = bottom - y0

        if w < 0:
            w = 0

        if h < 0:
            h = 0

        return x0, y0, w, h

    except Exception as e:

        logmsg(f'> error computing viewport geometry {e}')
        return 0, 0, 0, 0


def viewportredrawdamage(horizontal=False, vertical=False):

    try:

        vx, vy, vw, vh = viewportgeometry()
        damage = [[0, int(vy), max(0, int(vx) + int(vw)), max(0, int(vh))]]
        htrack = hscrolltrackgeometry() if horizontal else (0, 0, 0, 0)

        if htrack[2] > 0 and htrack[3] > 0:
            damage.append([int(value) for value in htrack])

        vtrack = scrollbartrackgeometry() if vertical else (0, 0, 0, 0)

        if vertical and vtrack[2] > 0 and vtrack[3] > 0:
            damage.append([int(value) for value in vtrack])

        return damage

    except Exception as e:

        logmsg(f'> error computing viewport redraw damage {e}')
        return [[0, int(MARGIN_TOP), max(0, int(WIN_W)), max(0, int(WIN_H) - int(MARGIN_TOP))]]


def viewportgeometry_noscrollbars():

    global WIN_W
    global WIN_H
    global MARGIN_LEFT
    global MARGIN_TOP
    global STATUSBAR_HEIGHT
    global SHOW_STATUSBAR

    try:

        bottom = WIN_H

        if SHOW_STATUSBAR:
            bottom -= STATUSBAR_HEIGHT

        if bottom < 0:
            bottom = 0

        right = WIN_W

        x0 = MARGIN_LEFT
        y0 = MARGIN_TOP

        w = right - x0
        h = bottom - y0

        if w < 0:
            w = 0

        if h < 0:
            h = 0

        return x0, y0, w, h

    except Exception:
        return 0, 0, 0, 0


def verticalneeded():

    global DOC_LINES
    global VISIBLE_LINES

    try:

        if VISIBLE_LINES <= 0:
            return False

        return displaylinecount() > VISIBLE_LINES

    except Exception:
        return False


def docwidthmeasure(line):

    try:

        return int(measuretext(expanddisplaytabs(line), FONT_SIZE))

    except Exception:

        return 0


def docwidthbeginindex():

    global DOC_LINEW
    global DOC_MAXW
    global DOC_MAXW_DIRTY
    global DOC_WIDTH_COUNTS
    global DOC_WIDTH_HEAP
    global DOC_WIDTH_INDEX_ROW
    global DOC_WIDTH_INDEX_ACTIVE
    global DOC_FONTSTAMP

    DOC_LINEW = [None] * len(DOC_LINES)
    DOC_MAXW = 0
    DOC_MAXW_DIRTY = False
    DOC_WIDTH_COUNTS = {}
    DOC_WIDTH_HEAP = []
    DOC_WIDTH_INDEX_ROW = 0
    DOC_WIDTH_INDEX_ACTIVE = bool(DOC_LINES)
    DOC_FONTSTAMP = FONT_SIZE


def docwidthindexline(row):

    global DOC_MAXW

    try:
        row = int(row)

        if row < 0 or row >= len(DOC_LINES) or row >= len(DOC_LINEW):
            return False

        if DOC_LINEW[row] is not None:
            return False

        width = int(docwidthmeasure(DOC_LINES[row]))
        DOC_LINEW[row] = width
        DOC_WIDTH_COUNTS[width] = int(DOC_WIDTH_COUNTS.get(width, 0)) + 1
        heapq.heappush(DOC_WIDTH_HEAP, -width)
        DOC_MAXW = max(int(DOC_MAXW), width)
        return True

    except Exception:
        return False


def docwidthindexstep(budget_ms=2.0):

    global DOC_WIDTH_INDEX_ROW
    global DOC_WIDTH_INDEX_ACTIVE

    if not DOC_WIDTH_INDEX_ACTIVE:
        return False

    oldmaximum = int(DOC_MAXW)
    deadline = time.monotonic() + max(0.00025, float(budget_ms) / 1000.0)

    while DOC_WIDTH_INDEX_ROW < len(DOC_LINES) and time.monotonic() < deadline:
        docwidthindexline(DOC_WIDTH_INDEX_ROW)
        DOC_WIDTH_INDEX_ROW += 1

    completed = DOC_WIDTH_INDEX_ROW >= len(DOC_LINES)

    if completed:
        DOC_WIDTH_INDEX_ACTIVE = False
        docwidthmaximum()

    _, _, available, _ = viewportgeometry_noscrollbars()
    oldneeded = oldmaximum > int(available)
    newneeded = int(DOC_MAXW) > int(available)
    return bool(oldneeded != newneeded or completed)


def docwidthmaximum():

    global DOC_MAXW
    global DOC_MAXW_DIRTY
    global DOC_WIDTH_HEAP

    try:

        while DOC_WIDTH_HEAP:

            candidate = -int(DOC_WIDTH_HEAP[0])

            if int(DOC_WIDTH_COUNTS.get(candidate, 0)) > 0:
                break

            heapq.heappop(DOC_WIDTH_HEAP)

        DOC_MAXW = -int(DOC_WIDTH_HEAP[0]) if DOC_WIDTH_HEAP else 0
        DOC_MAXW_DIRTY = False

    except Exception as e:

        logmsg(f'> error finding maximum document width {e}')
        DOC_MAXW = 0
        DOC_MAXW_DIRTY = True


def docwidthreplace(start, removed, lines, widths=None):

    global DOC_LINEW
    global DOC_MAXW_DIRTY
    global DOC_WIDTH_INDEX_ROW

    try:

        start = max(0, int(start))
        removed = max(0, int(removed))
        replacement = list(lines)

        if len(DOC_LINEW) + len(replacement) - removed != len(DOC_LINES):

            docwidthreset()
            return

        oldwidths = DOC_LINEW[start:start + removed]

        for width in oldwidths:

            if width is None:
                continue

            remaining = int(DOC_WIDTH_COUNTS.get(int(width), 0)) - 1

            if remaining > 0:
                DOC_WIDTH_COUNTS[int(width)] = remaining
            else:
                DOC_WIDTH_COUNTS.pop(int(width), None)

        if widths is None:
            replacementwidths = [docwidthmeasure(line) for line in replacement]
        else:
            replacementwidths = [max(0, int(width)) for width in widths]

            if len(replacementwidths) != len(replacement):
                replacementwidths = [docwidthmeasure(line) for line in replacement]

        DOC_LINEW[start:start + removed] = replacementwidths

        if DOC_WIDTH_INDEX_ACTIVE:
            DOC_WIDTH_INDEX_ROW = min(int(DOC_WIDTH_INDEX_ROW), int(start))

        for width in replacementwidths:
            width = int(width)
            DOC_WIDTH_COUNTS[width] = int(DOC_WIDTH_COUNTS.get(width, 0)) + 1
            heapq.heappush(DOC_WIDTH_HEAP, -width)

        docwidthmaximum()

    except Exception as e:

        logmsg(f'> error replacing document widths {e}')
        DOC_MAXW_DIRTY = True


def docwidthreset():

    global DOC_LINES
    global DOC_LINEW
    global DOC_MAXW
    global DOC_MAXW_DIRTY
    global DOC_FONTSTAMP
    global FONT_SIZE
    global DOC_WIDTH_COUNTS
    global DOC_WIDTH_HEAP
    global DOC_WIDTH_INDEX_ROW
    global DOC_WIDTH_INDEX_ACTIVE

    DOC_LINEW = []
    DOC_MAXW = 0
    DOC_WIDTH_COUNTS = {}
    DOC_WIDTH_HEAP = []
    DOC_WIDTH_INDEX_ROW = 0
    DOC_WIDTH_INDEX_ACTIVE = False

    try:

        for line in DOC_LINES:

            w = docwidthmeasure(line)

            DOC_LINEW.append(w)
            DOC_WIDTH_COUNTS[w] = int(DOC_WIDTH_COUNTS.get(w, 0)) + 1
            heapq.heappush(DOC_WIDTH_HEAP, -int(w))

            if w > DOC_MAXW:
                DOC_MAXW = w

    except Exception as e:

        logmsg(f'> error rebuilding doc width cache {e}')

        DOC_LINEW = []
        DOC_MAXW = 0
        DOC_WIDTH_COUNTS = {}
        DOC_WIDTH_HEAP = []
        DOC_MAXW_DIRTY = True
        return

    DOC_FONTSTAMP = FONT_SIZE
    DOC_MAXW_DIRTY = False


def docwidthsetline(row):

    global DOC_LINES
    global DOC_LINEW
    global DOC_MAXW
    global DOC_MAXW_DIRTY
    global FONT_SIZE

    try:

        if row < 0:
            return

        if row >= len(DOC_LINES):
            return

        if len(DOC_LINEW) != len(DOC_LINES):
            DOC_MAXW_DIRTY = True
            return

        oldw = DOC_LINEW[row]

    except Exception:

        DOC_MAXW_DIRTY = True
        return

    try:

        neww = docwidthmeasure(DOC_LINES[row])

        DOC_LINEW[row] = neww

        if oldw is not None:
            remaining = int(DOC_WIDTH_COUNTS.get(int(oldw), 0)) - 1

            if remaining > 0:
                DOC_WIDTH_COUNTS[int(oldw)] = remaining
            else:
                DOC_WIDTH_COUNTS.pop(int(oldw), None)

        DOC_WIDTH_COUNTS[int(neww)] = int(DOC_WIDTH_COUNTS.get(int(neww), 0)) + 1
        heapq.heappush(DOC_WIDTH_HEAP, -int(neww))
        docwidthmaximum()

    except Exception as e:

        logmsg(f'> error updating doc width cache line {e}')
        DOC_MAXW_DIRTY = True
        return


def maxlinewidth():

    global DOC_LINES
    global DOC_LINEW
    global DOC_MAXW
    global DOC_MAXW_DIRTY
    global DOC_FONTSTAMP
    global FONT_SIZE

    try:

        if DOC_FONTSTAMP != FONT_SIZE:

            if DOC_WIDTH_INDEX_ACTIVE:
                docwidthbeginindex()
            else:
                DOC_MAXW_DIRTY = True

        if DOC_MAXW_DIRTY:
            docwidthreset()

        if len(DOC_LINEW) != len(DOC_LINES):
            DOC_MAXW_DIRTY = True
            docwidthreset()

    except Exception as e:

        logmsg(f'> error checking doc width cache {e}')
        return 0

    return int(DOC_MAXW)


def horizontalneeded():

    try:

        if WORD_WRAP:
            return False

        vx, vy, vw, vh = viewportgeometry_noscrollbars()

        if vw <= 0:
            return False

        content = maxlinewidth()

        return content > vw

    except Exception:
        return False


def hscrolltrackgeometry():

    global WIN_W
    global WIN_H
    global SCROLLBAR_WIDTH
    global SCROLLBAR_MARGIN
    global HSCROLL_HEIGHT

    try:

        if not horizontalneeded():
            return 0, 0, 0, 0

        track_y = WIN_H - HSCROLL_HEIGHT

        if track_y < 0:
            track_y = 0

        track_x = 0

        track_w = WIN_W

        if verticalneeded():
            track_w -= SCROLLBAR_WIDTH

        if track_w < 0:
            track_w = 0

        return track_x, track_y, track_w, HSCROLL_HEIGHT

    except Exception as e:

        logmsg(f'> error computing horizontal scrollbar track geometry {e}')
        return 0, 0, 0, 0


def statusbargeometry():

    global WIN_H
    global STATUSBAR_HEIGHT
    global SHOW_STATUSBAR
    global HSCROLL_HEIGHT
    global WIN_W

    if not SHOW_STATUSBAR:
        return 0, 0, 0, 0

    try:

        y0 = WIN_H - STATUSBAR_HEIGHT

        if horizontalneeded():
            y0 -= HSCROLL_HEIGHT

        if y0 < 0:
            y0 = 0

        return 0, y0, WIN_W, STATUSBAR_HEIGHT

    except Exception as e:

        logmsg(f'> error computing status bar geometry {e}')
        return 0, 0, 0, 0


def clampxscroll():

    global FIRST_VISIBLE_X

    try:

        if WORD_WRAP:
            FIRST_VISIBLE_X = 0
            return

        vx, vy, vw, vh = viewportgeometry()

        if vw <= 0:
            FIRST_VISIBLE_X = 0
            return

        content = maxlinewidth()

        max_first = content - vw

        if max_first < 0:
            max_first = 0

        if FIRST_VISIBLE_X < 0:
            FIRST_VISIBLE_X = 0

        if FIRST_VISIBLE_X > max_first:
            FIRST_VISIBLE_X = max_first

    except Exception as e:

        logmsg(f'> error clamping horizontal scroll {e}')
        FIRST_VISIBLE_X = 0

    return


def ensurecursorvisiblex():

    global DOC_LINES
    global CUR_ROW
    global CUR_COL
    global FIRST_VISIBLE_X
    global FONT_SIZE
    global CURSOR_WIDTH

    try:

        if WORD_WRAP:
            FIRST_VISIBLE_X = 0
            return

        vx, vy, vw, vh = viewportgeometry()

        if vw <= 0:
            FIRST_VISIBLE_X = 0
            return

        if not DOC_LINES:
            FIRST_VISIBLE_X = 0
            return

        if CUR_ROW < 0:
            CUR_ROW = 0

        if CUR_ROW >= len(DOC_LINES):
            CUR_ROW = len(DOC_LINES) - 1

        line = str(DOC_LINES[CUR_ROW])

        if CUR_COL < 0:
            CUR_COL = 0

        if CUR_COL > len(line):
            CUR_COL = len(line)

        cx = lineadvanceat(CUR_ROW, line, CUR_COL)

        if cx < FIRST_VISIBLE_X:
            FIRST_VISIBLE_X = cx

        elif cx > FIRST_VISIBLE_X + max(0, vw - CURSOR_WIDTH):
            FIRST_VISIBLE_X = cx - max(0, vw - CURSOR_WIDTH)

        clampxscroll()

    except Exception as e:

        logmsg(f'> error ensuring horizontal cursor visibility {e}')

    return


def scrollbyx(delta):

    global FIRST_VISIBLE_X

    try:

        FIRST_VISIBLE_X += int(delta)

        clampxscroll()

    except Exception as e:

        logmsg(f'> error scrolling horizontally {e}')

    return


# document functions
def initialisedocument():

    global DOC_LINES, CUR_ROW, CUR_COL, FIRST_VISIBLE_ROW, FIRST_VISIBLE_X, IS_DIRTY, FILE_PATH, FILE_NAME
    global PENDING_SCROLL, LAST_SCROLL_FRAME, PENDING_INTERACTION_REDRAW, LAST_INTERACTION_FRAME
    global FILE_ENCODING, FILE_BOM, FILE_NEWLINE

    try:

        # reset document lines
        DOC_LINES = ['']
        documentmetadatareset()

        # reset cursor position
        CUR_ROW = 0
        CUR_COL = 0

        # reset scroll position
        FIRST_VISIBLE_ROW = 0
        FIRST_VISIBLE_X = 0
        PENDING_SCROLL = 0
        LAST_SCROLL_FRAME = 0.0
        PENDING_INTERACTION_REDRAW = 0
        LAST_INTERACTION_FRAME = 0.0

        docwidthreset()

        historyreset()

        # reset dirty state
        IS_DIRTY = False

        # reset file association
        FILE_PATH = None
        FILE_NAME = 'untitled.txt'
        FILE_ENCODING = 'utf-8'
        FILE_BOM = False
        FILE_NEWLINE = '\n'

        setwindowcurrent()

    except Exception as e:

        # error initialising document
        logmsg(f'> error initialising document {e}')
        return

    return


def loaddocumentfromlines(lines, lazy_widths=False, take_ownership=False, metadata=None):

    global DOC_LINES, CUR_ROW, CUR_COL, FIRST_VISIBLE_ROW, FIRST_VISIBLE_X, IS_DIRTY
    global PENDING_SCROLL, LAST_SCROLL_FRAME, PENDING_INTERACTION_REDRAW, LAST_INTERACTION_FRAME
    global DOC_LINE_IDS, DOC_LINE_VERSIONS, NEXT_LINE_ID, DOCUMENT_REFLOW_ROW
    global FILE_ENCODING, FILE_BOM, FILE_NEWLINE

    try:
        if take_ownership and isinstance(lines, list):
            values = lines
        else:
            values = [str(line) for line in lines]

        if not values:
            values = ['']

        # assign lines to document
        DOC_LINES = values

        lineids = metadata.get('ids') if isinstance(metadata, dict) else None
        lineversions = metadata.get('versions') if isinstance(metadata, dict) else None

        if (
            isinstance(lineids, list)
            and isinstance(lineversions, list)
            and len(lineids) == len(DOC_LINES)
            and len(lineversions) == len(DOC_LINES)
        ):
            DOC_LINE_IDS = lineids
            DOC_LINE_VERSIONS = lineversions
            NEXT_LINE_ID = max(lineids, default=0) + 1
            DOCUMENT_REFLOW_ROW = None
            invalidatewrapcache(drop_lines=True)
        else:
            documentmetadatareset()

        fileformat = metadata.get('format') if isinstance(metadata, dict) else None

        if isinstance(fileformat, dict):
            FILE_ENCODING = str(fileformat.get('encoding', 'utf-8'))
            FILE_BOM = bool(fileformat.get('bom', False))
            newline = str(fileformat.get('newline', '\n'))
            FILE_NEWLINE = newline if newline in ('\n', '\r\n', '\r') else '\n'

        # start view at top
        FIRST_VISIBLE_ROW = 0
        FIRST_VISIBLE_X = 0
        PENDING_SCROLL = 0
        LAST_SCROLL_FRAME = 0.0
        PENDING_INTERACTION_REDRAW = 0
        LAST_INTERACTION_FRAME = 0.0

        if lazy_widths:
            docwidthbeginindex()
        else:
            docwidthreset()

        historyreset()

        # move cursor to start of document
        CUR_ROW = 0

        CUR_COL = 0

        # loaded from disk, not yet modified
        IS_DIRTY = False

    except Exception as e:

        logmsg(f'> error loading document lines {e}')
        return

    return


def loaddocumentfromtext(text):

    try:

        if text is None:
            text = ''

        text = str(text).replace('\r\n', '\n').replace('\r', '\n')
        loaddocumentfromlines(text.split('\n'))

    except Exception as e:
        logmsg(f'> error loading document from text {e}')

    return


def getdocumenttext():

    global DOC_LINES

    try:

        # ensure there is at least one line
        if not DOC_LINES:
            return ''

        # join lines with newline
        text = '\n'.join(str(line) for line in DOC_LINES)

        return text

    except Exception as e:

        # error generating document text
        logmsg(f'> error getting document text {e}')
        return ''


def textpositionafter(row, col, text):

    chunks = str(text).split('\n')

    if len(chunks) == 1:
        return int(row), int(col) + len(chunks[0])

    return int(row) + len(chunks) - 1, len(chunks[-1])


def historysize(action):

    try:

        removed = str(action.get('removed', '')).encode('utf-8', errors='replace')
        inserted = str(action.get('inserted', '')).encode('utf-8', errors='replace')
        return len(removed) + len(inserted) + 256

    except Exception:

        return 256


def historyreset():

    global UNDO_STACK
    global REDO_STACK
    global UNDO_BYTES
    global CURRENT_REVISION
    global SAVED_REVISION
    global NEXT_REVISION
    global IS_DIRTY

    UNDO_STACK.clear()
    REDO_STACK.clear()
    UNDO_BYTES = 0
    CURRENT_REVISION = 0
    SAVED_REVISION = 0
    NEXT_REVISION = 1
    IS_DIRTY = False


def historypush(action):

    global UNDO_BYTES

    try:

        action['bytes'] = historysize(action)
        action['time'] = time.monotonic()

        if UNDO_STACK:

            previous = UNDO_STACK[-1]
            previousend = textpositionafter(previous['start'][0], previous['start'][1], previous.get('inserted', ''))

            if (
                previous.get('removed', '') == ''
                and action.get('removed', '') == ''
                and '\n' not in previous.get('inserted', '')
                and '\n' not in action.get('inserted', '')
                and tuple(action.get('start', ())) == tuple(previousend)
                and int(previous.get('afterrev', -1)) == int(action.get('beforerev', -2))
                and int(previous.get('afterrev', -1)) != int(SAVED_REVISION)
                and float(action['time']) - float(previous.get('time', 0.0)) <= 1.0
            ):

                UNDO_BYTES -= int(previous.get('bytes', 0))
                previous['inserted'] += action.get('inserted', '')
                previous['after'] = action.get('after')
                previous['afterrev'] = action.get('afterrev')
                previous['time'] = action['time']
                previous['bytes'] = historysize(previous)
                UNDO_BYTES += int(previous['bytes'])
                REDO_STACK.clear()
                return

        UNDO_STACK.append(action)
        UNDO_BYTES += int(action['bytes'])
        REDO_STACK.clear()

        while UNDO_STACK and (
            (UNDO_LIMIT and len(UNDO_STACK) > UNDO_LIMIT)
            or (UNDO_BYTE_LIMIT and UNDO_BYTES > UNDO_BYTE_LIMIT)
        ):

            removed = UNDO_STACK.pop(0)
            UNDO_BYTES -= int(removed.get('bytes', 0))

    except Exception as e:

        logmsg(f'> error pushing undo action {e}')


def editapply(sr, sc, er, ec, text):

    global DOC_LINES
    global DOC_LINE_IDS
    global DOC_LINE_VERSIONS
    global CUR_ROW
    global CUR_COL
    global DOCUMENT_REFLOW_ROW

    if not DOC_LINES:
        DOC_LINES = ['']
        documentmetadatareset()
        docwidthreset()

    documentmetadataensure()
    sr, sc = normalisecaret(sr, sc)
    er, ec = normalisecaret(er, ec)

    if (er, ec) < (sr, sc):
        sr, sc, er, ec = er, ec, sr, sc

    first = str(DOC_LINES[sr])
    last = str(DOC_LINES[er])
    prefix = first[:sc]
    suffix = last[ec:]

    if sr == er:
        removed = first[sc:ec]
    else:
        parts = [first[sc:]]
        parts.extend(str(DOC_LINES[row]) for row in range(sr + 1, er))
        parts.append(last[:ec])
        removed = '\n'.join(parts)

    inserted = str(text).replace('\r\n', '\n').replace('\r', '\n')
    chunks = inserted.split('\n')
    replacementwidths = None

    if len(chunks) == 1:
        replacement = [prefix + chunks[0] + suffix]

        if (
            sr == er
            and len(DOC_LINEW) == len(DOC_LINES)
            and DOC_LINEW[sr] is not None
            and '\t' not in first
            and '\t' not in chunks[0]
        ):
            oldwidth = int(DOC_LINEW[sr])
            replacementwidths = [
                max(
                    0,
                    oldwidth
                    - docwidthmeasure(removed)
                    + docwidthmeasure(chunks[0]),
                )
            ]
    else:
        replacement = [prefix + chunks[0]]
        replacement.extend(chunks[1:-1])
        replacement.append(chunks[-1] + suffix)

    preservedid = DOC_LINE_IDS[sr] if sr < len(DOC_LINE_IDS) else nextlineid()
    preservedversion = DOC_LINE_VERSIONS[sr] if sr < len(DOC_LINE_VERSIONS) else 0
    replacementids = [preservedid]
    replacementversions = [int(preservedversion) + 1]

    for _ in replacement[1:]:
        replacementids.append(nextlineid())
        replacementversions.append(0)

    removedcount = er - sr + 1
    DOC_LINES[sr:er + 1] = replacement
    DOC_LINE_IDS[sr:er + 1] = replacementids
    DOC_LINE_VERSIONS[sr:er + 1] = replacementversions
    wrapmetadatareplace(sr, removedcount, len(replacement))

    if removedcount != len(replacement):

        if DOCUMENT_REFLOW_ROW is None:
            DOCUMENT_REFLOW_ROW = int(sr)
        else:
            DOCUMENT_REFLOW_ROW = min(int(DOCUMENT_REFLOW_ROW), int(sr))

    docwidthreplace(sr, er - sr + 1, replacement, widths=replacementwidths)

    CUR_ROW, CUR_COL = textpositionafter(sr, sc, inserted)
    clearselection()

    return removed, inserted


def editreplace(sr, sc, er, ec, text):

    global CURRENT_REVISION
    global NEXT_REVISION
    global IS_DIRTY

    before = (int(CUR_ROW), int(CUR_COL), int(FIRST_VISIBLE_ROW), int(FIRST_VISIBLE_X))
    beforerev = int(CURRENT_REVISION)
    start = normalisecaret(sr, sc)
    end = normalisecaret(er, ec)

    if end < start:
        start, end = end, start

    removed, inserted = editapply(start[0], start[1], end[0], end[1], text)

    if removed == inserted:
        return False

    afterrev = int(NEXT_REVISION)
    NEXT_REVISION += 1
    CURRENT_REVISION = afterrev
    IS_DIRTY = CURRENT_REVISION != SAVED_REVISION

    action = {
        'start': tuple(start),
        'removed': removed,
        'inserted': inserted,
        'before': before,
        'after': (int(CUR_ROW), int(CUR_COL), int(FIRST_VISIBLE_ROW), int(FIRST_VISIBLE_X)),
        'beforerev': beforerev,
        'afterrev': afterrev,
    }

    historypush(action)
    return True


def undo():

    global UNDO_BYTES
    global CURRENT_REVISION
    global IS_DIRTY
    global CUR_ROW
    global CUR_COL
    global FIRST_VISIBLE_ROW
    global FIRST_VISIBLE_X

    try:

        if not UNDO_STACK:
            return

        action = UNDO_STACK.pop()
        UNDO_BYTES -= int(action.get('bytes', 0))
        sr, sc = action['start']
        er, ec = textpositionafter(sr, sc, action.get('inserted', ''))
        editapply(sr, sc, er, ec, action.get('removed', ''))
        CUR_ROW, CUR_COL, FIRST_VISIBLE_ROW, FIRST_VISIBLE_X = action['before']
        CURRENT_REVISION = int(action.get('beforerev', 0))
        IS_DIRTY = CURRENT_REVISION != SAVED_REVISION
        REDO_STACK.append(action)
        clearselection()

    except Exception as e:

        logmsg(f'> error in undo {e}')


def redo():

    global UNDO_BYTES
    global CURRENT_REVISION
    global IS_DIRTY
    global CUR_ROW
    global CUR_COL
    global FIRST_VISIBLE_ROW
    global FIRST_VISIBLE_X

    try:

        if not REDO_STACK:
            return

        action = REDO_STACK.pop()
        sr, sc = action['start']
        er, ec = textpositionafter(sr, sc, action.get('removed', ''))
        editapply(sr, sc, er, ec, action.get('inserted', ''))
        CUR_ROW, CUR_COL, FIRST_VISIBLE_ROW, FIRST_VISIBLE_X = action['after']
        CURRENT_REVISION = int(action.get('afterrev', CURRENT_REVISION))
        IS_DIRTY = CURRENT_REVISION != SAVED_REVISION
        UNDO_STACK.append(action)
        UNDO_BYTES += int(action.get('bytes', 0))
        clearselection()

    except Exception as e:

        logmsg(f'> error in redo {e}')


def insertcharacter(ch):

    try:

        ch = str(ch)

        if ch == '\n':
            handlenewline()
            return

        row, col = normalisecaret(CUR_ROW, CUR_COL)
        endcol = col + 1 if OVERWRITE_MODE and col < len(str(DOC_LINES[row])) else col
        editreplace(row, col, row, endcol, ch)

    except Exception as e:

        logmsg(f'> error inserting character {e}')

    return


def insertnewline():

    try:

        editreplace(CUR_ROW, CUR_COL, CUR_ROW, CUR_COL, '\n')

    except Exception as e:

        logmsg(f'> insert newline error {e}')

    return


def handlebackspace():

    try:

        if not DOC_LINES:
            return

        row, col = normalisecaret(CUR_ROW, CUR_COL)

        if row == 0 and col == 0:
            return

        if col > 0:
            editreplace(row, col - 1, row, col, '')
            return

        previous = str(DOC_LINES[row - 1])
        editreplace(row - 1, len(previous), row, 0, '')

    except Exception as e:

        logmsg(f'> error handling backspace {e}')

    return


def handledelete():

    try:

        if not DOC_LINES:
            return

        row, col = normalisecaret(CUR_ROW, CUR_COL)
        line = str(DOC_LINES[row])

        if col < len(line):
            editreplace(row, col, row, col + 1, '')
            return

        if row + 1 < len(DOC_LINES):
            editreplace(row, col, row + 1, 0, '')

    except Exception as e:

        logmsg(f'> error handling delete {e}')

    return


def handlenewline():

    try:

        row, col = normalisecaret(CUR_ROW, CUR_COL)
        editreplace(row, col, row, col, newlinevalue(row, col))

    except Exception as e:

        logmsg(f'> error handling newline {e}')

    return


def newlinevalue(row, col):

    try:
        line = str(DOC_LINES[int(row)])
        col = max(0, min(len(line), int(col)))
        limit = 0

        while limit < len(line) and line[limit] in (' ', '\t'):
            limit += 1

        return '\n' + line[:min(limit, col)]
    except Exception:
        return '\n'


def movecursorleft():

    global DOC_LINES
    global CUR_ROW
    global CUR_COL

    try:

        # nothing to move on empty document
        if not DOC_LINES:
            DOC_LINES = ['']
            CUR_ROW = 0
            CUR_COL = 0
            return

        # clamp row
        if CUR_ROW < 0:
            CUR_ROW = 0

        if CUR_ROW >= len(DOC_LINES):
            CUR_ROW = len(DOC_LINES) - 1

        # get current line
        line = str(DOC_LINES[CUR_ROW])

        # clamp column
        if CUR_COL < 0:
            CUR_COL = 0

        if CUR_COL > len(line):
            CUR_COL = len(line)

        if CUR_COL > 0:

            # move cursor left within line
            CUR_COL -= 1
            return

        # move to end of previous line
        if CUR_ROW > 0:

            CUR_ROW -= 1
            prev_line = str(DOC_LINES[CUR_ROW])
            CUR_COL = len(prev_line)

    except Exception as e:

        # error moving cursor left
        logmsg(f'> error moving cursor left {e}')
        return

    return


def movecursorright():

    global DOC_LINES
    global CUR_ROW
    global CUR_COL

    try:

        # nothing to move on empty document
        if not DOC_LINES:
            DOC_LINES = ['']
            CUR_ROW = 0
            CUR_COL = 0
            return

        # clamp row
        if CUR_ROW < 0:
            CUR_ROW = 0

        if CUR_ROW >= len(DOC_LINES):
            CUR_ROW = len(DOC_LINES) - 1

        # get current line
        line = str(DOC_LINES[CUR_ROW])

        # clamp column
        if CUR_COL < 0:
            CUR_COL = 0

        if CUR_COL > len(line):
            CUR_COL = len(line)

        if CUR_COL < len(line):

            # move cursor right within line
            CUR_COL += 1
            return

        # move to start of next line
        if CUR_ROW + 1 < len(DOC_LINES):

            CUR_ROW += 1
            CUR_COL = 0

    except Exception as e:

        # error moving cursor right
        logmsg(f'> error moving cursor right {e}')
        return

    return


def movecursorup():

    global DOC_LINES
    global CUR_ROW
    global CUR_COL

    try:

        # nothing to move on empty document
        if not DOC_LINES:
            DOC_LINES = ['']
            CUR_ROW = 0
            CUR_COL = 0
            return

        # move up a row if possible
        if CUR_ROW > 0:
            CUR_ROW -= 1

        # clamp row
        if CUR_ROW < 0:
            CUR_ROW = 0

        if CUR_ROW >= len(DOC_LINES):
            CUR_ROW = len(DOC_LINES) - 1

        # clamp column to new line length
        line = str(DOC_LINES[CUR_ROW])

        if CUR_COL < 0:
            CUR_COL = 0

        if CUR_COL > len(line):
            CUR_COL = len(line)

    except Exception as e:

        # error moving cursor up
        logmsg(f'> error moving cursor up {e}')
        return

    return


def movecursordown():

    global DOC_LINES
    global CUR_ROW
    global CUR_COL

    try:

        # nothing to move on empty document
        if not DOC_LINES:
            DOC_LINES = ['']
            CUR_ROW = 0
            CUR_COL = 0
            return

        # move down a row if possible
        if CUR_ROW + 1 < len(DOC_LINES):
            CUR_ROW += 1

        # clamp row
        if CUR_ROW < 0:
            CUR_ROW = 0

        if CUR_ROW >= len(DOC_LINES):
            CUR_ROW = len(DOC_LINES) - 1

        # clamp column to new line length
        line = str(DOC_LINES[CUR_ROW])

        if CUR_COL < 0:
            CUR_COL = 0

        if CUR_COL > len(line):
            CUR_COL = len(line)

    except Exception as e:

        # error moving cursor down
        logmsg(f'> error moving cursor down {e}')
        return

    return


def movecursorhome():

    global CUR_COL, CUR_ROW

    try:

        line = str(DOC_LINES[max(0, min(len(DOC_LINES) - 1, CUR_ROW))])
        firsttext = len(line) - len(line.lstrip(' \t'))
        CUR_COL = 0 if CUR_COL == firsttext else firsttext

    except Exception as e:

        # error moving cursor home
        logmsg(f'> error moving cursor home {e}')
        return

    return


def movecursorend():

    global DOC_LINES
    global CUR_ROW
    global CUR_COL

    try:

        # nothing to move on empty document
        if not DOC_LINES:
            DOC_LINES = ['']
            CUR_ROW = 0
            CUR_COL = 0
            return

        # clamp row
        if CUR_ROW < 0:
            CUR_ROW = 0

        if CUR_ROW >= len(DOC_LINES):
            CUR_ROW = len(DOC_LINES) - 1

        # move to end of line
        line = str(DOC_LINES[CUR_ROW])
        CUR_COL = len(line)

    except Exception as e:

        # error moving cursor end
        logmsg(f'> error moving cursor end {e}')
        return

    return


def scrollbylines(delta):

    global FIRST_VISIBLE_ROW
    global DOC_LINES
    global VISIBLE_LINES

    try:

        # no lines means nothing to scroll
        if VISIBLE_LINES <= 0 or not DOC_LINES:
            FIRST_VISIBLE_ROW = 0
            return

        # compute maximum first visible row
        max_first = 0

        if displaylinecount() > VISIBLE_LINES:
            max_first = displaylinecount() - VISIBLE_LINES

        # adjust scroll
        FIRST_VISIBLE_ROW += int(delta)

        if FIRST_VISIBLE_ROW < 0:
            FIRST_VISIBLE_ROW = 0

        if FIRST_VISIBLE_ROW > max_first:
            FIRST_VISIBLE_ROW = max_first

    except Exception as e:

        # error scrolling document
        logmsg(f'> error scrolling document {e}')
        return

    return


def pageup():

    global VISIBLE_LINES, CUR_ROW, CUR_COL

    try:

        # nothing to page if we do not yet know the page size
        if VISIBLE_LINES <= 0:

            scrollbylines(0)
            return

        CUR_ROW = max(0, CUR_ROW - VISIBLE_LINES)
        CUR_COL = min(CUR_COL, len(str(DOC_LINES[CUR_ROW])))
        scrollbylines(-VISIBLE_LINES)

    except Exception as e:

        # error handling page up
        logmsg(f'> error handling page up {e}')
        return

    return


def pagedown():

    global VISIBLE_LINES, CUR_ROW, CUR_COL

    try:

        # nothing to page if we do not yet know the page size
        if VISIBLE_LINES <= 0:

            scrollbylines(0)
            return

        CUR_ROW = min(len(DOC_LINES) - 1, CUR_ROW + VISIBLE_LINES)
        CUR_COL = min(CUR_COL, len(str(DOC_LINES[CUR_ROW])))
        scrollbylines(VISIBLE_LINES)

    except Exception as e:

        # error handling page down
        logmsg(f'> error handling page down {e}')
        return

    return


def ensurecursorvisible():

    global CUR_ROW
    global FIRST_VISIBLE_ROW
    global VISIBLE_LINES
    global DOC_LINES
    global PENDING_SCROLL

    try:

        # Explicit caret navigation takes precedence over queued wheel motion.
        PENDING_SCROLL = 0

        if VISIBLE_LINES <= 0:
            ensurecursorvisiblex()
            return

        if not DOC_LINES:
            CUR_ROW = 0
            FIRST_VISIBLE_ROW = 0
            ensurecursorvisiblex()
            return

        if CUR_ROW < 0:
            CUR_ROW = 0

        if CUR_ROW >= len(DOC_LINES):
            CUR_ROW = len(DOC_LINES) - 1

        cursorrow = cursorvisualindex(CUR_ROW, CUR_COL)

        if cursorrow < FIRST_VISIBLE_ROW:
            FIRST_VISIBLE_ROW = cursorrow

        bottom_row = FIRST_VISIBLE_ROW + VISIBLE_LINES - 1

        if cursorrow > bottom_row:
            FIRST_VISIBLE_ROW = cursorrow - VISIBLE_LINES + 1

        max_first = 0

        if displaylinecount() > VISIBLE_LINES:
            max_first = displaylinecount() - VISIBLE_LINES

        if FIRST_VISIBLE_ROW < 0:
            FIRST_VISIBLE_ROW = 0

        if FIRST_VISIBLE_ROW > max_first:
            FIRST_VISIBLE_ROW = max_first

        ensurecursorvisiblex()

    except Exception as e:

        logmsg(f'> error ensuring cursor visibility {e}')
        return

    return


    try:

        # nothing to ensure if no visible area
        if VISIBLE_LINES <= 0:
            return

        # clamp row into document
        if not DOC_LINES:
            CUR_ROW = 0
            FIRST_VISIBLE_ROW = 0
            return

        if CUR_ROW < 0:
            CUR_ROW = 0

        if CUR_ROW >= len(DOC_LINES):
            CUR_ROW = len(DOC_LINES) - 1

        # ensure cursor row not above view
        if CUR_ROW < FIRST_VISIBLE_ROW:
            FIRST_VISIBLE_ROW = CUR_ROW

        # ensure cursor row not below view
        bottom_row = FIRST_VISIBLE_ROW + VISIBLE_LINES - 1

        if CUR_ROW > bottom_row:
            FIRST_VISIBLE_ROW = CUR_ROW - VISIBLE_LINES + 1

        # clamp first visible row within bounds
        max_first = 0

        if len(DOC_LINES) > VISIBLE_LINES:
            max_first = len(DOC_LINES) - VISIBLE_LINES

        if FIRST_VISIBLE_ROW < 0:
            FIRST_VISIBLE_ROW = 0

        if FIRST_VISIBLE_ROW > max_first:
            FIRST_VISIBLE_ROW = max_first

    except Exception as e:

        # error ensuring cursor visibility
        logmsg(f'> error ensuring cursor visible {e}')
        return

    return


# file functions
def getusername():

    try:
        descriptor = os.open(
            SESSIONIDENTITYFILE,
            os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
        )

        try:
            metadata = os.fstat(descriptor)

            if (
                not stat.S_ISREG(metadata.st_mode) or
                metadata.st_uid != 0 or
                metadata.st_gid != 1000 or
                stat.S_IMODE(metadata.st_mode) != 0o640 or
                metadata.st_nlink != 1
            ):
                raise PermissionError('unsafe active session identity')

            with os.fdopen(descriptor, "rb", closefd=True) as stream:
                descriptor = -1
                raw = stream.read(SESSIONIDENTITYMAXBYTES + 1)

        finally:
            if descriptor >= 0:
                os.close(descriptor)

    except OSError as error:

        raise RuntimeError(
            "the active session identity is unavailable") from error

    if len(raw) > SESSIONIDENTITYMAXBYTES:

        raise RuntimeError("the active session identity is too large")

    try:

        identity = json.loads(raw.decode("utf-8"))

    except (UnicodeDecodeError, ValueError) as error:

        raise RuntimeError("the active session identity is invalid") from error

    if (
        not isinstance(identity, dict) or
        set(identity) != {"format", "username"} or
        type(identity.get("format")) is not int or
        identity.get("format") != 1
    ):

        raise RuntimeError("the active session identity is invalid")

    username = identity.get("username")
    if not isinstance(username, str) or not SESSIONUSERNAME.fullmatch(username):

        raise RuntimeError("the active session username is invalid")

    return username


def writesettingspath():

    # Preferences are user data, not a global system-setting mutation.  The
    # provisioner creates the private expanse directory in every user home.
    return f'/master/{getusername()}/expanse/write settings.json'


def parseargs():

    global FILE_PATH
    global FILE_NAME
    global DEFAULTDIR

    try:

        # no file argument
        if len(sys.argv) <= 1:

            FILE_PATH = None
            FILE_NAME = 'untitled.txt'

            username = getusername()
            DEFAULTDIR = f"/master/{username}/reference"

            return

        # file argument provided
        raw = sys.argv[1]
        p = normalisepath(raw)

        if not p:

            FILE_PATH = None

            FILE_NAME = 'untitled.txt'

            return

        FILE_PATH = p

        try:

            FILE_NAME = os.path.basename(p)

        except Exception:

            FILE_NAME = p

        setwindowcurrent()

    except Exception as e:

        FILE_PATH = None

        FILE_NAME = 'untitled.txt'

        DEFAULTDIR = None

        if len(sys.argv) <= 1:
            raise RuntimeError(
                'Write cannot determine the active session directory') from e

    return


def normalisepath(raw):

    try:

        # normalise to string
        s = str(raw)

    except Exception:

        return ''

    return s


def fileiocomplete(result):

    global FILE_IO_RESULT

    with FILE_IO_LOCK:
        FILE_IO_RESULT = dict(result)


def detectfileformatsample(sample):

    if sample.startswith(codecs.BOM_UTF8):
        return 'utf-8', True, 'utf-8-sig'

    if sample.startswith(codecs.BOM_UTF32_LE):
        return 'utf-32-le', True, 'utf-32'

    if sample.startswith(codecs.BOM_UTF32_BE):
        return 'utf-32-be', True, 'utf-32'

    if sample.startswith(codecs.BOM_UTF16_LE):
        return 'utf-16-le', True, 'utf-16'

    if sample.startswith(codecs.BOM_UTF16_BE):
        return 'utf-16-be', True, 'utf-16'

    try:
        decoder = codecs.getincrementaldecoder('utf-8')('strict')
        decoder.decode(sample, final=False)
        return 'utf-8', False, 'utf-8'
    except UnicodeDecodeError:
        return 'latin-1', False, 'latin-1'


def detectfileformat(path):

    descriptor = os.open(
        path,
        os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK,
    )
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise PermissionError('document is not a regular file')
        return detectfileformatsample(os.read(descriptor, 65536))
    finally:
        os.close(descriptor)


def filelineending(value):

    text = str(value)

    if text.endswith('\r\n'):
        return text[:-2], '\r\n'

    if text.endswith('\n'):
        return text[:-1], '\n'

    if text.endswith('\r'):
        return text[:-1], '\r'

    return text, ''


def readfilepayload(path):

    path = userreadpath(path)
    descriptor = os.open(
        path,
        os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK,
    )
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode) or
            metadata.st_uid not in (0, os.geteuid()) or
            metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH) or
            metadata.st_nlink != 1 or
            metadata.st_size > MAXDOCUMENTBYTES
        ):
            raise PermissionError('unsafe document input')
        sample = os.read(descriptor, 65536)
        os.lseek(descriptor, 0, os.SEEK_SET)
        encoding, bom, readencoding = detectfileformatsample(sample)
        # Read a bounded byte snapshot from the already validated descriptor.
        # A same-UID peer may append after fstat; relying on the initial size
        # while iterating to EOF would make that race an unbounded allocation.
        os.lseek(descriptor, 0, os.SEEK_SET)
        chunks = []
        remaining = MAXDOCUMENTBYTES + 1
        while remaining:
            block = os.read(descriptor, min(1024 * 1024, remaining))
            if not block:
                break
            chunks.append(block)
            remaining -= len(block)
        payload = b''.join(chunks)
        if len(payload) > MAXDOCUMENTBYTES:
            raise PermissionError('document input exceeds the size limit')
        text = payload.decode(readencoding, errors='strict')
        stream = io.StringIO(text, newline='')
        os.close(descriptor)
        descriptor = -1
    except Exception:
        if descriptor >= 0:
            os.close(descriptor)
        raise

    lines = []
    newlinecounts = {'\n': 0, '\r\n': 0, '\r': 0}
    firstnewline = None
    endedwithnewline = False

    with stream:

        for value in stream:
            line, ending = filelineending(value)
            lines.append(line)
            endedwithnewline = bool(ending)

            if ending:
                newlinecounts[ending] += 1

                if firstnewline is None:
                    firstnewline = ending

    if endedwithnewline:
        lines.append('')

    maximum = max(newlinecounts.values(), default=0)
    newline = firstnewline or '\n'

    if maximum:
        candidates = [key for key, count in newlinecounts.items() if count == maximum]

        if newline not in candidates:
            newline = candidates[0]

    values = lines or ['']
    count = len(values)
    return {
        'kind': 'load',
        'ok': True,
        'path': path,
        'lines': values,
        'metadata': {
            'ids': list(range(1, count + 1)),
            'versions': [0] * count,
            'format': {
                'encoding': encoding,
                'bom': bool(bom),
                'newline': newline,
            },
        },
    }


def encodingbom(encoding):

    return {
        'utf-8': codecs.BOM_UTF8,
        'utf-16-le': codecs.BOM_UTF16_LE,
        'utf-16-be': codecs.BOM_UTF16_BE,
        'utf-32-le': codecs.BOM_UTF32_LE,
        'utf-32-be': codecs.BOM_UTF32_BE,
    }.get(str(encoding).lower(), b'')


def writefilesnapshot(path, lines, encoding, bom, newline):

    with open(path, 'wb') as stream:
        writefilesnapshotstream(stream, lines, encoding, bom, newline)


def writefilesnapshotstream(stream, lines, encoding, bom, newline):

    codec = str(encoding or 'utf-8').lower()
    separator = str(newline) if str(newline) in ('\n', '\r\n', '\r') else '\n'

    if bom:
        stream.write(encodingbom(codec))

    last = len(lines) - 1

    for index, value in enumerate(lines):
        stream.write(str(value).encode(codec, errors='strict'))

        if index != last:
            stream.write(separator.encode(codec, errors='strict'))

    stream.flush()
    os.fsync(stream.fileno())


def usersavepath(raw):

    """Return an absolute user-home save path and descriptor-walk parts."""

    try:
        value = os.fspath(raw)
    except TypeError as error:
        raise PermissionError('invalid save path') from error

    if not isinstance(value, str) or not value or '\x00' in value:
        raise PermissionError('invalid save path')

    if not os.path.isabs(value):
        raise PermissionError('save path must be absolute')

    username = getusername()
    root = os.path.normpath(f'/master/{username}')
    path = os.path.normpath(value)

    try:
        contained = os.path.commonpath((root, path)) == root
    except ValueError:
        contained = False

    if not contained or path == root:
        raise PermissionError('save path is outside the active user home')

    relative = os.path.relpath(path, root)
    parts = relative.split(os.sep)

    if (
        not parts or
        any(not part or part in ('.', '..') for part in parts) or
        os.sep in parts[-1]
    ):
        raise PermissionError('invalid save path')

    return path, root, parts


def userreadpath(raw):

    """Return a bounded document path from a user-visible file namespace."""

    try:
        value = os.fspath(raw)
    except TypeError as error:
        raise PermissionError('invalid document path') from error

    if not isinstance(value, str) or not value or '\x00' in value:
        raise PermissionError('invalid document path')

    if not os.path.isabs(value):
        raise PermissionError('document path must be absolute')

    path = os.path.normpath(value)
    roots = (
        os.path.normpath(f'/master/{getusername()}'),
        '/.ephemeral/volumes',
        '/software',
    )
    contained = False

    for root in roots:

        try:

            if path != root and os.path.commonpath((root, path)) == root:
                contained = True
                break

        except ValueError:

            continue

    if not contained:
        raise PermissionError('document path is outside user-visible storage')

    return path


def validateduserdirectory(fd):

    metadata = os.fstat(fd)
    expecteduid = 1000

    if os.geteuid() != expecteduid:
        raise PermissionError('Write is not running as the desktop user')

    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != expecteduid:
        raise PermissionError('save directory is not owned by the desktop user')

    if metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise PermissionError('save directory is writable by another identity')


def openusersaveparent(raw):

    path, root, parts = usersavepath(raw)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
    descriptor = os.open(root, flags)

    try:
        validateduserdirectory(descriptor)

        for component in parts[:-1]:
            child = os.open(component, flags, dir_fd=descriptor)

            try:
                validateduserdirectory(child)
            except Exception:
                os.close(child)
                raise

            os.close(descriptor)
            descriptor = child

        return path, descriptor, parts[-1]

    except Exception:
        os.close(descriptor)
        raise


def validateusersavetarget(parentfd, name):

    try:
        metadata = os.stat(name, dir_fd=parentfd, follow_symlinks=False)
    except FileNotFoundError:
        return

    if not stat.S_ISREG(metadata.st_mode):
        raise PermissionError('save target is not a regular file')

    if metadata.st_uid != os.geteuid():
        raise PermissionError('save target is owned by another identity')

    if metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise PermissionError('save target is writable by another identity')


def writeuserfilesnapshot(path, lines, encoding, bom, newline):

    """Atomically save beneath the active user home without following links."""

    canonical, parentfd, name = openusersaveparent(path)
    temporary = f'.write-{os.getpid()}-{secrets.token_hex(16)}.tmp'
    temporarycreated = False

    try:
        validateusersavetarget(parentfd, name)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW
        descriptor = os.open(temporary, flags, 0o600, dir_fd=parentfd)
        temporarycreated = True

        try:
            metadata = os.fstat(descriptor)

            if (
                not stat.S_ISREG(metadata.st_mode) or
                metadata.st_uid != os.geteuid() or
                metadata.st_nlink != 1
            ):
                raise PermissionError('unsafe temporary save file')

            with os.fdopen(descriptor, 'wb', closefd=True) as stream:
                descriptor = -1
                writefilesnapshotstream(stream, lines, encoding, bom, newline)

        finally:
            if descriptor >= 0:
                os.close(descriptor)

        # Re-check immediately before the descriptor-relative replacement.  A
        # changed target is still never followed, but must remain a regular,
        # desktop-owned file.
        validateusersavetarget(parentfd, name)
        os.replace(
            temporary,
            name,
            src_dir_fd=parentfd,
            dst_dir_fd=parentfd,
        )
        temporarycreated = False
        os.fsync(parentfd)
        return canonical

    finally:
        if temporarycreated:
            try:
                os.unlink(temporary, dir_fd=parentfd)
            except OSError:
                pass

        os.close(parentfd)


def fileloadworker(path):

    try:
        fileiocomplete(readfilepayload(path))

    except FileNotFoundError:
        logmsg(f'file load failed path={path!r} error=file not found')
        fileiocomplete({'kind': 'load', 'ok': False, 'path': path, 'message': 'file not found'})
    except PermissionError as error:
        logmsg(f'file load failed path={path!r} error={error}')
        fileiocomplete({'kind': 'load', 'ok': False, 'path': path, 'message': 'permission denied'})
    except Exception as e:
        logmsg(f'file load failed path={path!r} error={type(e).__name__}: {e}')
        fileiocomplete({'kind': 'load', 'ok': False, 'path': path, 'message': f'load error {e}'})


def filesaveworker(path, lines, revision, encoding, bom, newline):

    try:
        path = writeuserfilesnapshot(path, lines, encoding, bom, newline)

        fileiocomplete({
            'kind': 'save',
            'ok': True,
            'path': path,
            'revision': int(revision),
        })

    except PermissionError:
        fileiocomplete({'kind': 'save', 'ok': False, 'path': path, 'message': 'permission denied'})
    except Exception as e:
        fileiocomplete({'kind': 'save', 'ok': False, 'path': path, 'message': f'save error {e}'})


def startfileio(kind, target, lines=None, revision=0, encoding='utf-8', bom=False, newline='\n'):

    global FILE_IO_THREAD
    global FILE_IO_RESULT
    global FILE_IO_KIND
    global LAST_STATUS_MESSAGE
    global LAST_STATUS_TIME

    # A completed worker still owns a result until pollfileio applies it.
    # Starting another operation in that interval would discard the result.
    if FILE_IO_THREAD is not None:
        setstatus(f'{FILE_IO_KIND or "file"} in progress')
        return False

    with FILE_IO_LOCK:
        FILE_IO_RESULT = None

    FILE_IO_KIND = str(kind)

    if kind == 'load':
        worker = threading.Thread(target=fileloadworker, args=(target,), daemon=False)
        LAST_STATUS_MESSAGE = 'loading'
    else:
        worker = threading.Thread(
            target=filesaveworker,
            args=(
                target,
                tuple(lines or ()),
                int(revision),
                str(encoding),
                bool(bom),
                str(newline),
            ),
            daemon=False,
        )
        LAST_STATUS_MESSAGE = 'saving'

    LAST_STATUS_TIME = time.time()
    FILE_IO_THREAD = worker
    worker.start()
    redrawstatusbar()
    return True


def pollfileio():

    global FILE_IO_THREAD
    global FILE_IO_RESULT
    global FILE_IO_KIND
    global FILE_PATH
    global FILE_NAME
    global SAVED_REVISION
    global IS_DIRTY

    with FILE_IO_LOCK:
        result = FILE_IO_RESULT
        FILE_IO_RESULT = None

    if result is None:
        return False

    FILE_IO_THREAD = None
    FILE_IO_KIND = None

    if not result.get('ok'):

        if result.get('kind') == 'save':
            canceldestructiveflow()

        setstatus(result.get('message', 'file operation failed'))
        redrawstatusbar()
        return True

    path = str(result.get('path', ''))

    if result.get('kind') == 'load':
        resetpointerstate()
        loaddocumentfromlines(
            result.get('lines', ['']),
            lazy_widths=True,
            take_ownership=True,
            metadata=result.get('metadata'),
        )
        FILE_PATH = path
        FILE_NAME = os.path.basename(path) if path else 'untitled.txt'
        addrecentfile(path)
        setwindowcurrent()
        ensurecursorvisible()
        setstatus('loaded')
        redrawfull()
        return True

    FILE_PATH = path
    FILE_NAME = os.path.basename(path) if path else FILE_NAME
    setwindowcurrent()
    revision = int(result.get('revision', -1))

    if CURRENT_REVISION == revision:
        SAVED_REVISION = revision
        IS_DIRTY = False
    else:
        # The user edited while the background snapshot was being written.
        # Keep the new revision dirty, but do not unexpectedly execute an old
        # close/new/open request on some later save.
        canceldestructiveflow()

    addrecentfile(path)
    setstatus('saved')
    redrawstatusbar()
    completeaftersave()
    return True


def loaddocumentfromfile(path):

    global FILE_PATH
    global FILE_NAME
    global IS_DIRTY
    global LAST_STATUS_MESSAGE

    try:

        # reset pointer state on load
        resetpointerstate()

        # normalise path
        p = normalisepath(path)

        if not p:

            LAST_STATUS_MESSAGE = 'invalid path'
            return

        if APP_RUNNING:
            startfileio('load', p)
            return

        payload = readfilepayload(p)
        loaddocumentfromlines(
            payload.get('lines', ['']),
            take_ownership=True,
            metadata=payload.get('metadata'),
        )

        FILE_PATH = p

        try:

            FILE_NAME = os.path.basename(p)

        except Exception:

            FILE_NAME = p

        setwindowcurrent()
        addrecentfile(p)

        IS_DIRTY = False

        try:

            # ensure cursor is within view when opening in a running window
            ensurecursorvisible()

        except Exception as e:

            # error ensuring visibility after load
            logmsg(f'> error ensuring cursor visible after load {e}')

        LAST_STATUS_MESSAGE = 'loaded'

    except FileNotFoundError as error:

        # file does not exist
        LAST_STATUS_MESSAGE = 'file not found'
        logmsg(f'> document load failed path={path!r} error={error}')
        return

    except PermissionError as error:

        # permission denied
        LAST_STATUS_MESSAGE = 'permission denied'
        logmsg(f'> document load denied path={path!r} error={error}')
        return

    except Exception as e:

        # general load error
        LAST_STATUS_MESSAGE = f'load error {e}'
        logmsg(f'> document load failed path={path!r} error={e}')
        return

    return


def savedocumenttofile(path):

    global FILE_PATH
    global FILE_NAME
    global IS_DIRTY
    global SAVED_REVISION

    try:

        # Write is intentionally not a privileged file-mutation broker.  It
        # can save only beneath the active desktop user's home; the actual
        # write repeats this validation using a no-follow descriptor walk.
        p, _root, _parts = usersavepath(path)

        if APP_RUNNING:
            return startfileio(
                'save',
                p,
                lines=tuple(str(line) for line in DOC_LINES),
                revision=CURRENT_REVISION,
                encoding=FILE_ENCODING,
                bom=FILE_BOM,
                newline=FILE_NEWLINE,
            )

        try:
            p = writeuserfilesnapshot(
                p,
                tuple(str(line) for line in DOC_LINES),
                FILE_ENCODING,
                FILE_BOM,
                FILE_NEWLINE,
            )

        except PermissionError:
            setstatus('permission denied')
            return

        except Exception as e:
            setstatus(f'error saving file {e}')
            return

        # update file association
        FILE_PATH = p

        try:

            FILE_NAME = os.path.basename(p)

        except Exception:

            FILE_NAME = p

        setwindowcurrent()
        addrecentfile(p)

        # saved document is clean
        SAVED_REVISION = CURRENT_REVISION
        IS_DIRTY = False

        # success status
        setstatus('saved')
        completeaftersave()
        return True

    except Exception as e:

        # unexpected save error
        setstatus(f'save error {e}')
        return False


def printcommand(path):
    # Direct process execution from a desktop editor is intentionally retired.
    # Printing will return when a typed broker can accept a bounded document FD
    # and a fixed printer ID; environment commands and PATH lookup are never an
    # authorization mechanism.
    del path
    return []


def printdocument():

    temporary = ''

    try:
        username = getusername()
        temporary = os.path.join(
            f'/master/{username}',
            f'.write-print-{os.getpid()}-{secrets.token_hex(16)}.txt',
        )
        command = printcommand(temporary)

        if not command:
            setstatus('printing unavailable')
            return False

        temporary = writeuserfilesnapshot(
            temporary,
            tuple(str(line) for line in DOC_LINES),
            'utf-8',
            False,
            FILE_NEWLINE,
        )
        result = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            check=False,
        )

        if result.returncode != 0:
            detail = result.stderr.decode('utf-8', errors='replace').strip()
            setstatus(f'print failed {detail}'[:160])
            return False

        setstatus('sent to printer')
        return True

    except subprocess.TimeoutExpired:
        setstatus('print timed out')
        return False
    except Exception as e:
        setstatus(f'print error {e}')
        return False
    finally:
        try:
            if temporary:
                _canonical, parentfd, name = openusersaveparent(temporary)

                try:
                    validateusersavetarget(parentfd, name)
                    os.unlink(name, dir_fd=parentfd)
                    os.fsync(parentfd)
                finally:
                    os.close(parentfd)
        except Exception:
            pass



def dialogrequest(dialogid, title, message, buttons, inputrequest=None, default=0):

    request = {
        'op': 'CREATE_DIALOG',
        'parent': WINDOW_ID,
        'dialog_id': str(dialogid),
        'title': str(title),
        'message': str(message),
        'buttons': list(buttons),
        'default': int(default),
    }

    if inputrequest is not None:
        request['input'] = dict(inputrequest)

    return request


def opendialog(action, title, message, buttons, payload=None, inputrequest=None, default=0):

    global DIALOG_WAITING, DIALOG_ID, DIALOG_WIN, DIALOG_ACTION, DIALOG_PAYLOAD
    global DIALOG_SEQUENCE

    if DIALOG_WAITING:
        setstatus('dialog already open')
        return False

    if not WINDOW_ID or ws_sock is None:
        setstatus('dialog unavailable')
        return False

    DIALOG_SEQUENCE += 1
    DIALOG_ID = f'write-{os.getpid()}-{DIALOG_SEQUENCE}'
    DIALOG_WIN = None
    DIALOG_ACTION = str(action)
    DIALOG_PAYLOAD = payload
    DIALOG_WAITING = True
    resetpointerstate()
    sendmsg(dialogrequest(
        DIALOG_ID,
        title,
        message,
        buttons,
        inputrequest=inputrequest,
        default=default,
    ))
    return True


def closedialogstate():

    global DIALOG_WAITING, DIALOG_ID, DIALOG_WIN, DIALOG_ACTION, DIALOG_PAYLOAD

    DIALOG_WAITING = False
    DIALOG_ID = None
    DIALOG_WIN = None
    DIALOG_ACTION = None
    DIALOG_PAYLOAD = None


def canceldestructiveflow():

    global AFTER_SAVE_ACTION, PENDING_DESTRUCTIVE_ACTION

    AFTER_SAVE_ACTION = None
    PENDING_DESTRUCTIVE_ACTION = None


def starttextprompt(action, title, initial='', message='', allow_empty=False, payload=None, oklabel='ok'):

    return opendialog(
        action,
        title,
        message or title,
        [
            {'id': 'ok', 'label': oklabel},
            {'id': 'cancel', 'label': 'cancel', 'cancel': True},
        ],
        payload=payload,
        inputrequest={
            'value': str(initial or ''),
            'select_all': True,
            'max_length': 4096,
            'allow_empty': bool(allow_empty),
        },
    )


def startreplaceprompt(replace_all=False):

    global REPLACE_ALL_PENDING

    REPLACE_ALL_PENDING = bool(replace_all)
    return starttextprompt(
        'replace_find',
        'replace',
        FIND_QUERY,
        'find text',
        allow_empty=False,
        payload={'all': bool(replace_all)},
        oklabel='next',
    )


def performdestructiveaction(action):

    global APP_RUNNING

    try:
        if action == 'new':
            initialisedocument()
            clearselection()
            redrawfull()
            return True

        if action == 'open':
            startopenpathprompt()
            return True

        if action == 'exit':
            APP_RUNNING = False
            return True

        if isinstance(action, tuple) and action and action[0] == 'open_recent':
            loaddocumentfromfile(action[1])
            return True

    except Exception as e:
        logmsg(f'> destructive action error {e}')

    return False


def requestdestructiveaction(action):

    global PENDING_DESTRUCTIVE_ACTION

    if not IS_DIRTY:
        return performdestructiveaction(action)

    PENDING_DESTRUCTIVE_ACTION = action
    return opendialog(
        'confirm_unsaved',
        'unsaved changes',
        f'{FILE_NAME or "this document"} has unsaved changes.',
        [
            {'id': 'save', 'label': 'save'},
            {'id': 'discard', 'label': 'discard'},
            {'id': 'cancel', 'label': 'cancel', 'cancel': True},
        ],
        payload=action,
        default=0,
    )


def completeaftersave():

    global AFTER_SAVE_ACTION, PENDING_DESTRUCTIVE_ACTION

    if AFTER_SAVE_ACTION is None or IS_DIRTY:
        return False

    action = AFTER_SAVE_ACTION
    AFTER_SAVE_ACTION = None
    PENDING_DESTRUCTIVE_ACTION = None
    return performdestructiveaction(action)


def handledialogresult(msg):

    global FIND_QUERY, REPLACE_QUERY, REPLACE_ALL_PENDING
    global AFTER_SAVE_ACTION, PENDING_DESTRUCTIVE_ACTION

    if not DIALOG_WAITING or str(msg.get('dialog_id', '')) != str(DIALOG_ID or ''):
        return False

    result = str(msg.get('result', 'cancel'))
    value = str(msg.get('value', ''))
    action = DIALOG_ACTION
    payload = DIALOG_PAYLOAD
    closedialogstate()

    if result == 'cancel':

        if action in ('confirm_unsaved', 'save_path'):
            canceldestructiveflow()

        setstatus('cancelled')
        return True

    if action == 'confirm_unsaved':

        if result == 'discard':
            PENDING_DESTRUCTIVE_ACTION = None
            performdestructiveaction(payload)
        elif result == 'save':
            AFTER_SAVE_ACTION = payload

            if FILE_PATH:
                savedocumenttofile(FILE_PATH)
                completeaftersave()
            else:
                startsavepathprompt()

        return True

    if result != 'ok':
        return True

    if action == 'open_path':
        loaddocumentfromfile(value)
    elif action == 'save_path':
        savedocumenttofile(value)
        completeaftersave()
    elif action == 'find':
        FIND_QUERY = value
        findnext(query=value)
    elif action == 'replace_find':
        FIND_QUERY = value
        starttextprompt(
            'replace_with',
            'replace',
            REPLACE_QUERY,
            f'replace {value} with',
            allow_empty=True,
            payload=payload,
            oklabel='replace all' if bool((payload or {}).get('all')) else 'replace',
        )
    elif action == 'replace_with':
        REPLACE_QUERY = value

        if bool((payload or {}).get('all')):
            replaceall()
        else:
            replaceone()
    elif action == 'goto_line':
        gotoline(value)

    redrawfull()
    return True


def startfilepicker(kind):

    global PICKER_PENDING

    if PICKER_PENDING is not None:
        return True

    if PICKER_VERSION < 1 or not WINDOW_ID:
        return False

    mode = 'open_file' if kind == 'open' else 'save_as'
    if FILE_PATH:
        initial = os.path.dirname(os.path.abspath(str(FILE_PATH)))
    else:
        initial = DEFAULTDIR or '/'

    suggested = ''
    if mode == 'save_as':
        suggested = os.path.basename(str(FILE_PATH)) if FILE_PATH else (FILE_NAME or 'untitled.txt')

    request = {
        'op': 'CREATE_PICKER',
        'parent': int(WINDOW_ID),
        'mode': mode,
        'title': 'open document' if mode == 'open_file' else 'save document as',
        'initial_path': str(initial),
        'allow_multiple': False,
        'filters': [
            {
                'id': 'text',
                'label': 'text documents',
                'extensions': [
                    '.txt', '.md', '.py', '.json', '.csv', '.tsv',
                    '.html', '.htm', '.css', '.js', '.xml', '.yaml', '.yml',
                    '.ini', '.cfg', '.conf', '.log',
                ],
            },
            {'id': 'all', 'label': 'all files', 'extensions': ['*']},
        ],
    }

    if mode == 'save_as':
        request['suggested_name'] = str(suggested)
        request['default_extension'] = '.txt'

    PICKER_PENDING = {
        'kind': str(kind),
        'request_id': None,
    }
    sendmsg(request)
    setstatus('opening Array')
    redrawstatusbar()
    return True


def handlepickerresult(msg):

    global PICKER_PENDING
    global AFTER_SAVE_ACTION, PENDING_DESTRUCTIVE_ACTION

    if PICKER_PENDING is None:
        return False

    requestid = str(msg.get('request_id', ''))
    expected = PICKER_PENDING.get('request_id')
    if expected and requestid != str(expected):
        return False

    kind = PICKER_PENDING.get('kind')
    PICKER_PENDING = None
    status = str(msg.get('status', 'cancelled'))
    paths = msg.get('paths', [])

    if status != 'accepted' or not isinstance(paths, list) or not paths:
        if kind == 'save' and AFTER_SAVE_ACTION is not None:
            AFTER_SAVE_ACTION = None
            PENDING_DESTRUCTIVE_ACTION = None
        setstatus('cancelled')
        redrawstatusbar()
        return True

    path = os.path.abspath(str(paths[0]))

    if kind == 'open':
        try:
            if not check(path):
                setstatus('permission denied')
                redrawstatusbar()
                return True
        except Exception as error:
            logmsg(f'> architect check error on picker result {error}')
            setstatus('permission check unavailable')
            redrawstatusbar()
            return True

    if kind == 'open':
        if not os.path.isfile(path):
            setstatus('file not found')
        else:
            loaddocumentfromfile(path)
    elif kind == 'save':
        savedocumenttofile(path)
    else:
        setstatus('invalid picker result')

    redrawfull()
    return True


def startopenpathprompt():

    global INPUT_MODE
    global PROMPT_TEXT
    global PROMPT_BUFFER
    global LAST_STATUS_MESSAGE

    try:

        resetpointerstate()

        if startfilepicker('open'):
            return

        initial = f'{DEFAULTDIR}/' if DEFAULTDIR else ''
        starttextprompt(
            'open_path',
            'open',
            initial,
            'enter a file path',
            allow_empty=False,
            oklabel='open',
        )

    except Exception as e:

        # error starting open path prompt
        logmsg(f'> error starting open path prompt {e}')

    return


def startsavepathprompt():

    global INPUT_MODE
    global PROMPT_TEXT
    global PROMPT_BUFFER
    global FILE_PATH
    global LAST_STATUS_MESSAGE
    global DEFAULTDIR

    try:

        # reset pointer state on prompt
        resetpointerstate()

        if startfilepicker('save'):
            return

        if FILE_PATH:
            initial = str(FILE_PATH)
        elif DEFAULTDIR:
            initial = f'{DEFAULTDIR}/'
        else:
            initial = ''

        starttextprompt(
            'save_path',
            'save as',
            initial,
            'enter a file path',
            allow_empty=False,
            oklabel='save',
        )

    except Exception as e:

        # error starting save path prompt
        logmsg(f'> error starting save path prompt {e}')

    return


def confirmpathprompt():

    global INPUT_MODE
    global PROMPT_BUFFER
    global LAST_STATUS_MESSAGE

    try:

        p = normalisepath(PROMPT_BUFFER)

        if not p:

            LAST_STATUS_MESSAGE = 'invalid path'
            INPUT_MODE = 'edit'

            redrawfull()
            return

        if INPUT_MODE == 'open_path':

            loaddocumentfromfile(p)

            INPUT_MODE = 'edit'

            redrawfull()
            return

        if INPUT_MODE == 'save_path':

            savedocumenttofile(p)

            INPUT_MODE = 'edit'

            resetpointerstate()

            redrawfull()
            return

        # unknown mode
        INPUT_MODE = 'edit'

        redrawfull()

    except Exception as e:

        LAST_STATUS_MESSAGE = f'path error {e}'
        INPUT_MODE = 'edit'

        try:
            redrawfull()
        except Exception as er:
            logmsg(f'> error redrawing after path error {er}')

    return


def cancelpathprompt():

    global INPUT_MODE
    global PROMPT_BUFFER
    global PROMPT_TEXT
    global LAST_STATUS_MESSAGE

    try:

        # reset pointer state on cancel
        resetpointerstate()

        INPUT_MODE = 'edit'
        PROMPT_BUFFER = ''
        PROMPT_TEXT = ''
        LAST_STATUS_MESSAGE = 'cancelled'

        redrawfull()

    except Exception as e:

        logmsg(f'> error cancelling prompt {e}')

    return


# input functions
def resetpointerstate():

    global SCROLLBAR_DRAGGING
    global SCROLLBAR_DRAG_CURSOR_OFFSET
    global HSCROLL_DRAGGING
    global HSCROLL_DRAG_CURSOR_OFFSET
    global MOUSE_SELECTING
    global PENDING_INTERACTION_REDRAW


    SCROLLBAR_DRAGGING = False
    SCROLLBAR_DRAG_CURSOR_OFFSET = 0

    HSCROLL_DRAGGING = False
    HSCROLL_DRAG_CURSOR_OFFSET = 0

    MOUSE_SELECTING = False
    PENDING_INTERACTION_REDRAW = 0
    closemenu()
    closecontextmenu()

    return


def keytoken(name):

    if name is None:
        return None

    try:
        k = str(name).strip().upper()
    except Exception:
        return None

    if not k:
        return None

    # canonical navigation/edit keys
    if k in ('ESC', 'ENTER', 'TAB', 'BACKSPACE', 'DELETE', 'HOME', 'END', 'PGUP', 'PGDN', 'UP', 'DOWN', 'LEFT', 'RIGHT', 'INS'):
        return f'<{k}>'

    # function keys
    if k.startswith('F') and len(k) <= 3:
        # F1..F12 style
        return f'<{k}>'

    return None


def hascommandmods(rawmods):


    if isinstance(rawmods, dict):

        if rawmods.get('ctrl', False) or rawmods.get('alt', False) or rawmods.get('win', False):
            return True

        return False

    s = str(rawmods).lower()

    if 'ctrl' in s or 'alt' in s or 'win' in s or 'meta' in s or 'super' in s:
        return True

    return False


def normalisekeymsg(msg):

    try:

        keyname = msg.get('key', '')
        state = msg.get('state', '')
        mods = msg.get('mods', '')

    except Exception:
        return None

    # map known non-text keys into write tokens
    tok = keytoken(keyname)

    if tok is not None:

        return {
            'text': tok,
            'state': state,
            'mods': mods,
        }

    try:

        k = str(keyname)

    except Exception:
        return None

    if len(k) == 1 and k.isprintable():

        if hascommandmods(mods):

            return {
                'text': k,
                'state': state,
                'mods': mods,
            }

        return None

    return None


def handlekey(msg):

    global INPUT_MODE
    global PROMPT_BUFFER
    global PROMPT_TEXT
    global LAST_STATUS_MESSAGE
    global FILE_PATH
    global CUR_ROW
    global CUR_COL
    global DOC_LINES
    global OVERWRITE_MODE

    try:

        # extract key text, state, and modifiers
        text = str(msg.get('text', ''))
        state = str(msg.get('state', ''))
        mods = str(msg.get('mods', ''))

    except Exception as e:

        # error reading key message
        logmsg(f'> error reading KEY message {e}')
        return

    logmsg(f'> key text={repr(text)} state={state} mods={mods}')

    try:

        # normalise escape key
        if text == '\x1b':

            text = '<ESC>'

        # normalise backspace variants
        if text == '\b' or text == '\x7f':

            text = '<BACKSPACE>'

        # normalise delete from input daemon
        if text == '<DEL>':

            text = '<DELETE>'

        try:

            # normalise modifiers to lowercase for checks
            mods_lower = mods.lower()

        except Exception:

            mods_lower = ''

    except Exception as e:

        # error normalising key text
        logmsg(f'> error normalising key text {e}')
        return

    # act only on key down and repeat events
    if state != 'down' and state != 'repeat':

        return

    # allow repeats only for navigation / edit keys
    if state == 'repeat':

        repeatok = {
            '<LEFT>',
            '<RIGHT>',
            '<UP>',
            '<DOWN>',
            '<BACKSPACE>',
            '<DELETE>',
            '<HOME>',
            '<END>',
            '<PGUP>',
            '<PGDN>',
        }

        if text not in repeatok:

            return

    # -------------------------
    # PATH PROMPT MODE
    # -------------------------
    if INPUT_MODE == 'open_path' or INPUT_MODE == 'save_path':

        try:

            # backspace to delete characters
            if text == '<BACKSPACE>':

                if PROMPT_BUFFER:

                    PROMPT_BUFFER = PROMPT_BUFFER[:-1]

                    redrawstatusbar()

                return

            # confirm path
            if text == '<ENTER>' or text == '\n':

                confirmpathprompt()
                return

            # tab (insert 4 spaces)
            if text == '\t' or text == '<TAB>':

                PROMPT_BUFFER += '    '
                redrawstatusbar()
                return

            # cancel path prompt
            if text == '<ESC>':

                cancelpathprompt()
                return

            # printable normal character input
            if len(text) == 1 and text.isprintable():

                PROMPT_BUFFER += text

                redrawstatusbar()

                return

        except Exception as e:

            # error handling prompt key
            logmsg(f'> error handling prompt key {e}')
            return

        return

    # -------------------------
    # NORMAL EDIT MODE
    # -------------------------
    try:

        if text != '<ESC>' and (MENUBAR_OPEN or CONTEXT_MENU_OPEN):

            closemenu()
            closecontextmenu()
            redrawfull()

        # handle escape: clear status bar
        if text == '<ESC>':

            if MENUBAR_OPEN or CONTEXT_MENU_OPEN:

                closemenu()
                closecontextmenu()
                redrawfull()
                return

            LAST_STATUS_MESSAGE = ''

            try:

                # redraw to clear status bar visually
                redrawstatusbar()

            except Exception as e:

                # error redrawing after ESC
                logmsg(f'> error redrawing after ESC {e}')

            return

        # -------------------------
        # CONTROL SHORTCUTS
        # -------------------------

        try:

            # normalise modifiers into a token set (supports dict or string)
            modtokens = set()

            rawmods = msg.get('mods', '')

            if isinstance(rawmods, dict):

                for k, v in rawmods.items():

                    if v:
                        modtokens.add(str(k).lower())

            else:

                try:
                    mods_lower = str(rawmods).lower()
                except Exception:
                    mods_lower = ''

                cur = ''
                for ch in mods_lower:

                    if ch.isalnum():
                        cur += ch
                        continue

                    if cur:
                        modtokens.add(cur)
                        cur = ''

                if cur:
                    modtokens.add(cur)

        except Exception:

            modtokens = set()

        # treat both control characters and ctrl+letter with mods
        is_ctrl = ('ctrl' in modtokens) or ('lctrl' in modtokens) or ('rctrl' in modtokens)

        # shift for selection extension
        is_shift = ('shift' in modtokens) or ('lshift' in modtokens) or ('rshift' in modtokens)
        is_alt = ('alt' in modtokens) or ('lalt' in modtokens) or ('ralt' in modtokens)

        # Standard editor commands that would otherwise overlap older Write
        # shortcuts.
        if is_ctrl and is_shift and text.lower() == 's':
            startsavepathprompt()
            return

        if is_ctrl and text.lower() == 'f':
            starttextprompt('find', 'find', FIND_QUERY, 'find text', allow_empty=False, oklabel='find')
            return

        if is_ctrl and text.lower() == 'h':
            startreplaceprompt(replace_all=is_shift)
            return

        if is_ctrl and text.lower() == 'g':
            starttextprompt('goto_line', 'go to line', str(CUR_ROW + 1), 'line number', oklabel='go')
            return

        if is_ctrl and text.lower() == 'p':
            printdocument()
            redrawstatusbar()
            return

        if is_ctrl and text.lower() == 'd':
            duplicatelines()
            ensurecursorvisible()
            redrawregionaroundcursororline()
            return

        if is_ctrl and is_shift and text.lower() == 'k':
            deletelines()
            ensurecursorvisible()
            redrawregionaroundcursororline()
            return

        if is_ctrl and text in ('+', '='):
            changezoom(1)
            return

        if is_ctrl and text == '-':
            changezoom(-1)
            return

        if is_ctrl and text == '0':
            changezoom(0, reset=True)
            return

        # Ctrl+N : new document
        if text == '\x0e' or (is_ctrl and text.lower() == 'n'):

            try:

                requestdestructiveaction('new')

            except Exception as e:

                logmsg(f'> error starting new document with Ctrl+N {e}')

            return

        # Ctrl+O : open path prompt
        if text == '\x0f' or (is_ctrl and text.lower() == 'o'):

            try:

                requestdestructiveaction('open')

            except Exception as e:

                logmsg(f'> error starting open path with Ctrl+O {e}')

            return

        # Ctrl+S : save to existing path or prompt for one
        if text == '\x13' or (is_ctrl and text.lower() == 's'):

            try:

                if FILE_PATH:

                    savedocumenttofile(FILE_PATH)

                else:

                    startsavepathprompt()

                redrawfull()

            except Exception as e:

                # error saving via Ctrl+S
                logmsg(f'> error saving document with Ctrl+S {e}')

            return

        # Ctrl+Z : undo
        if text == '\x1a' or (is_ctrl and text.lower() == 'z' and not is_shift):

            try:

                undo()
                clearselection()
                ensurecursorvisible()
                redrawregionaroundcursororline()

            except Exception as e:

                # error performing undo
                logmsg(f'> error performing undo with Ctrl+Z {e}')

            return

        # Ctrl+Y : redo
        if text == '\x19' or (is_ctrl and text.lower() == 'y'):

            try:

                redo()
                clearselection()
                ensurecursorvisible()
                redrawregionaroundcursororline()

            except Exception as e:

                # error performing redo
                logmsg(f'> error performing redo with Ctrl+Y {e}')

            return

        # Ctrl+A : select all
        if text == '\x01' or (is_ctrl and text.lower() == 'a'):

            editselectall()
            redrawviewport()
            return

        if is_ctrl and is_shift and text.lower() == 'z':
            redo()
            clearselection()
            ensurecursorvisible()
            redrawregionaroundcursororline()
            return

        # Ctrl+C : copy
        if text == '\x03' or (is_ctrl and text.lower() == 'c'):

            editcopy()
            return

        # Ctrl+X : cut
        if text == '\x18' or (is_ctrl and text.lower() == 'x'):

            editcut()
            ensurecursorvisible()

            redrawregionaroundcursororline()

            return

        # Ctrl+V : paste
        if text == '\x16' or (is_ctrl and text.lower() == 'v'):

            editpaste()
            redrawregionaroundcursororline()
            return


        # -------------------------
        # CURSOR MOVEMENT
        # -------------------------

        # left
        if text == '<LEFT>':

            if is_shift:

                if not hasselection():

                    setselectionanchor(CUR_ROW, CUR_COL)

                movecursorword(reverse=True) if is_ctrl else movecursorleft()

                updateselectionend(CUR_ROW, CUR_COL)

            else:

                movecursorword(reverse=True) if is_ctrl else movecursorleft()

                clearselection()

            ensurecursorvisible()

            redrawregionaroundcursororline()

            return

        # right
        if text == '<RIGHT>':

            if is_shift:

                if not hasselection():

                    setselectionanchor(CUR_ROW, CUR_COL)

                movecursorword() if is_ctrl else movecursorright()

                updateselectionend(CUR_ROW, CUR_COL)

            else:

                movecursorword() if is_ctrl else movecursorright()

                clearselection()

            ensurecursorvisible()

            redrawregionaroundcursororline()

            return

        # up
        if text == '<UP>':

            if is_shift:

                if not hasselection():

                    setselectionanchor(CUR_ROW, CUR_COL)

                movecursorup()

                updateselectionend(CUR_ROW, CUR_COL)

            else:

                movecursorup()

                clearselection()

            ensurecursorvisible()

            redrawregionaroundcursororline()

            return

        # down
        if text == '<DOWN>':

            if is_shift:

                if not hasselection():

                    setselectionanchor(CUR_ROW, CUR_COL)

                movecursordown()

                updateselectionend(CUR_ROW, CUR_COL)

            else:

                movecursordown()

                clearselection()

            ensurecursorvisible()

            redrawregionaroundcursororline()

            return

        # home
        if text == '<HOME>':

            if is_ctrl:

                if is_shift and not hasselection():
                    setselectionanchor(CUR_ROW, CUR_COL)

                CUR_ROW = 0
                CUR_COL = 0

                if is_shift:
                    updateselectionend(CUR_ROW, CUR_COL)
                else:
                    clearselection()

                ensurecursorvisible()
                redrawregionaroundcursororline()
                return

            if is_shift:

                if not hasselection():

                    setselectionanchor(CUR_ROW, CUR_COL)

                movecursorhome()

                updateselectionend(CUR_ROW, CUR_COL)

            else:

                movecursorhome()

                clearselection()

            ensurecursorvisible()

            redrawregionaroundcursororline()

            return

        # end
        if text == '<END>':

            if is_ctrl:

                if is_shift and not hasselection():
                    setselectionanchor(CUR_ROW, CUR_COL)

                CUR_ROW = len(DOC_LINES) - 1
                CUR_COL = len(str(DOC_LINES[CUR_ROW]))

                if is_shift:
                    updateselectionend(CUR_ROW, CUR_COL)
                else:
                    clearselection()

                ensurecursorvisible()
                redrawregionaroundcursororline()
                return

            if is_shift:

                if not hasselection():

                    setselectionanchor(CUR_ROW, CUR_COL)

                movecursorend()

                updateselectionend(CUR_ROW, CUR_COL)

            else:

                movecursorend()

                clearselection()

            ensurecursorvisible()

            redrawregionaroundcursororline()

            return

        # page up
        if text == '<PGUP>':

            if is_shift and not hasselection():
                setselectionanchor(CUR_ROW, CUR_COL)

            pageup()

            if is_shift:
                updateselectionend(CUR_ROW, CUR_COL)
            else:
                clearselection()

            ensurecursorvisible()
            redrawviewport(vertical=True)
            return

        # page down
        if text == '<PGDN>':

            if is_shift and not hasselection():
                setselectionanchor(CUR_ROW, CUR_COL)

            pagedown()

            if is_shift:
                updateselectionend(CUR_ROW, CUR_COL)
            else:
                clearselection()

            ensurecursorvisible()
            redrawviewport(vertical=True)
            return

        # -------------------------
        # EDITING KEYS
        # -------------------------

        # Tab indents to a four-column stop. With a selection it indents each
        # selected logical line; Shift+Tab reverses the operation.
        if text == '\t' or text == '<TAB>':

            if hascommandmods(rawmods):
                return

            if handleindentation(outdent=is_shift):
                ensurecursorvisible()
                redrawregionaroundcursororline()

            return

        # newline
        if text == '<ENTER>' or text == '\n':

            if hasselection():

                sr, sc, er, ec = selectionbounds()
                editreplace(sr, sc, er, ec, newlinevalue(sr, sc))

                ensurecursorvisible()
                redrawregionaroundcursororline()
                return

            handlenewline()
            clearselection()
            ensurecursorvisible()

            redrawregionaroundcursororline()

            return

        # backspace
        if text == '<BACKSPACE>':

            if hasselection():

                deleteselection()

                ensurecursorvisible()
                redrawregionaroundcursororline()
                return

            deleteword(reverse=True) if is_ctrl else handlebackspace()
            clearselection()
            ensurecursorvisible()

            redrawregionaroundcursororline()

            return

        # delete
        if text == '<DELETE>':

            if hasselection():

                deleteselection()

                ensurecursorvisible()
                redrawregionaroundcursororline()
                return

            deleteword() if is_ctrl else handledelete()
            clearselection()
            ensurecursorvisible()

            redrawregionaroundcursororline()

            return

        if text == '<INS>':

            OVERWRITE_MODE = not OVERWRITE_MODE
            redrawstatusbar()
            return

        # -------------------------
        # FUNCTION-STYLE SHORTCUTS
        # (still supported if F-keys are ever mapped)
        # -------------------------

        # open path prompt keybinding
        if text == '<F2>':

            requestdestructiveaction('open')
            return

        # find next / previous
        if text == '<F3>':

            findnext(reverse=is_shift)
            redrawviewport()
            return

        # save-as keybinding
        if text == '<F4>':

            startsavepathprompt()
            redrawfull()
            return

        # -------------------------
        # PRINTABLE CHARACTERS
        # -------------------------

        if len(text) == 1 and text.isprintable():

            if hasselection():

                sr, sc, er, ec = selectionbounds()
                editreplace(sr, sc, er, ec, text)

                ensurecursorvisible()
                redrawregionaroundcursororline()
                return

            insertcharacter(text)
            clearselection()
            ensurecursorvisible()

            redrawregionaroundcursororline()

            return

    except Exception as e:

        # generic key handling error
        logmsg(f'> error handling key {e}')
        return


handlekeycore = handlekey


def handlekey(msg):

    started = perfstart()

    try:
        return handlekeycore(msg)
    finally:
        perfrecord(
            'input_to_present',
            started,
            backend='managed' if GRAPHICSSTATE.get('active') else 'cpu',
            wrap=bool(WORD_WRAP),
            lines=len(DOC_LINES),
        )


def handlepointerbutton(msg):

    global FIRST_VISIBLE_ROW
    global CUR_ROW
    global CUR_COL
    global DOC_LINES
    global MARGIN_TOP
    global MARGIN_LEFT
    global LINE_HEIGHT
    global VISIBLE_LINES
    global SCROLLBAR_DRAGGING
    global SCROLLBAR_DRAG_CURSOR_OFFSET
    global HSCROLL_DRAGGING
    global HSCROLL_DRAG_CURSOR_OFFSET
    global FIRST_VISIBLE_X
    global MOUSE_SELECTING
    global MENUBAR_OPEN
    global MENU_HOVER_ACTION

    try:

        button = int(msg.get('button', 0))
        state = str(msg.get('state', ''))
        x = int(msg.get('x', 0))
        y = int(msg.get('y', 0))
        mods = msg.get('mods', '')

    except Exception as e:

        logmsg(f'> error reading POINTER_BUTTON {e}')
        return

    if state == 'down':
        cancelsmoothscroll()

    # check for shift modifier
    try:

        is_shift = False

        if isinstance(mods, dict):

            if mods.get('shift', False) or mods.get('lshift', False) or mods.get('rshift', False):
                is_shift = True

        else:

            m = str(mods).lower()
            if 'shift' in m:
                is_shift = True

    except Exception:
        is_shift = False

    if iscontextpointerbutton(button):

        if state != 'down':
            return

        try:

            resetpointerstate()
            vx, vy, vw, vh = viewportgeometry()

            if not pointinrect(x, y, (vx, vy, vw, vh)):
                redrawfull()
                return

            row, col = pointtodocpos(x, y)

            if not positioninselection(row, col):
                CUR_ROW = row
                CUR_COL = col
                clearselection()

            opencontextmenu(x, y)
            redrawfull()

        except Exception as e:

            logmsg(f'> error opening context menu {e}')

        return

    if button != 1:
        return

    if state == 'down':

        try:

            if CONTEXT_MENU_OPEN:

                contextaction, insidecontext = contextmenuhit(x, y)
                enabled = bool(contextaction and contextactionenabled(contextaction))
                closecontextmenu()

                if insidecontext:

                    if enabled:
                        runmenuaction(contextaction)
                    else:
                        redrawfull()

                    return

                redrawfull()

            zone, name, action = menuhit(x, y)

            if zone == 'menubar':

                if name:

                    closecontextmenu()

                    if MENUBAR_OPEN == name:

                        closemenu()

                    else:

                        MENUBAR_OPEN = name
                        MENU_HOVER_ACTION = None

                    redrawfull()
                    return

                if MENUBAR_OPEN:

                    closemenu()

                    redrawfull()
                    return

            if zone == 'menu':

                if action:

                    closemenu()

                    runmenuaction(action)
                    return

                if MENUBAR_OPEN:

                    closemenu()

                    redrawfull()
                    return

            if MENUBAR_OPEN:

                closemenu()

                redrawfull()

        except Exception as e:

            logmsg(f'> error handling menubar click {e}')

    if state == 'up':

        SCROLLBAR_DRAGGING = False
        HSCROLL_DRAGGING = False

        MOUSE_SELECTING = False
        flushinteractionredraw(force=True)

        if not hasselection():

            clearselection()

        return

    if state != 'down' and state != 'repeat':

        return

    try:

        if horizontalneeded():

            htx, hty, htw, hth = hscrolltrackgeometry()

            if htw > 0 and hth > 0 and x >= htx and x < htx + htw and y >= hty and y < hty + hth:

                vx, vy, vw, vh = viewportgeometry()

                content_w = maxlinewidth()

                scroll_range = content_w - vw

                if scroll_range <= 0:
                    return

                try:
                    thumb_w = int(htw * (vw / float(content_w)))
                except Exception:
                    thumb_w = HSCROLL_MIN_THUMB

                if thumb_w < HSCROLL_MIN_THUMB:
                    thumb_w = HSCROLL_MIN_THUMB

                if thumb_w > htw:
                    thumb_w = htw

                try:
                    thumb_x = htx + int((FIRST_VISIBLE_X / float(scroll_range)) * (htw - thumb_w))
                except Exception:
                    thumb_x = htx

                if x >= thumb_x and x < thumb_x + thumb_w:

                    HSCROLL_DRAGGING = True
                    HSCROLL_DRAG_CURSOR_OFFSET = x - thumb_x
                    return

                if x < thumb_x:

                    scrollbyx(-vw)
                    redrawviewport(horizontal=True)
                    return

                if x >= thumb_x + thumb_w:

                    scrollbyx(vw)
                    redrawviewport(horizontal=True)
                    return

    except Exception as e:

        logmsg(f'> error handling horizontal scrollbar click {e}')
        return

    try:

        total_lines = displaylinecount()

        track_x, track_y, track_w, track_h = scrollbartrackgeometry()

        in_scrollbar = False

        if track_w > 0 and track_h > 0 and total_lines > VISIBLE_LINES:

            if x >= track_x and x < track_x + track_w and y >= track_y and y < track_y + track_h:

                in_scrollbar = True

        if in_scrollbar:

            scroll_range = total_lines - VISIBLE_LINES

            if scroll_range <= 0:
                return

            thumb_x, thumb_y, thumb_w, thumb_h = scrollbarthumbgeometry()

            if thumb_w <= 0 or thumb_h <= 0:
                return

            if y >= thumb_y and y < thumb_y + thumb_h:

                SCROLLBAR_DRAGGING = True
                SCROLLBAR_DRAG_CURSOR_OFFSET = y - thumb_y
                return

            if y < thumb_y:

                pageup()
                redrawfull()
                return

            if y >= thumb_y + thumb_h:

                pagedown()
                redrawfull()
                return

    except Exception as e:

        logmsg(f'> error handling scrollbar click {e}')
        return

    try:

        row, col = pointtodocpos(x, y)

        # click counting (same row/col within threshold)
        now = time.time()

        global CLICKTIME, CLICKCOUNT, CLICKROW, CLICKCOL, CLICKTHRESH

        if (now - CLICKTIME) <= CLICKTHRESH and row == CLICKROW and col == CLICKCOL:

            CLICKCOUNT += 1

        else:

            CLICKCOUNT = 1

        CLICKTIME = now
        CLICKROW = row
        CLICKCOL = col

        CUR_ROW = row
        CUR_COL = col

        # double click: select word (+ trailing space if present)
        if CLICKCOUNT == 2:

            selectwordat(row, col)

            MOUSE_SELECTING = True

            ensurecursorvisible()

            redrawregionaroundcursororline()

            return

        # triple click: select whole line
        if CLICKCOUNT >= 3:

            selectline(row)

            MOUSE_SELECTING = True

            ensurecursorvisible()

            redrawregionaroundcursororline()

            return

        # single click: caret placement
        setselectionanchor(row, col)
        updateselectionend(row, col)

        MOUSE_SELECTING = True

        ensurecursorvisible()
        redrawfull()

    except Exception as e:

        logmsg(f'> error handling pointer button {e}')
        return

    return


def handlepointermotion(msg):

    global SCROLLBAR_DRAGGING
    global SCROLLBAR_DRAG_CURSOR_OFFSET
    global FIRST_VISIBLE_ROW
    global DOC_LINES
    global VISIBLE_LINES
    global HSCROLL_DRAGGING
    global HSCROLL_DRAG_CURSOR_OFFSET
    global FIRST_VISIBLE_X
    global MOUSE_SELECTING
    global CUR_ROW
    global CUR_COL

    try:

        x = int(msg.get('x', 0))
        y = int(msg.get('y', 0))

    except Exception as e:

        logmsg(f'> error reading POINTER_MOTION {e}')
        return

    vx, vy, vw, vh = viewportgeometry()
    setpointercursor(
        'text'
        if not CONTEXT_MENU_OPEN and not MENUBAR_OPEN
        and pointinrect(x, y, (vx, vy, vw, vh))
        else 'arrow'
    )

    if CONTEXT_MENU_OPEN:

        updatecontextmenuhover(x, y)
        return

    if MENUBAR_OPEN:

        updatemenuhover(x, y)
        return

    if HSCROLL_DRAGGING:

        try:

            vx, vy, vw, vh = viewportgeometry()

            content_w = maxlinewidth()

            if vw <= 0 or content_w <= vw:
                HSCROLL_DRAGGING = False
                FIRST_VISIBLE_X = 0
                return

            track_x, track_y, track_w, track_h = hscrolltrackgeometry()

            if track_w <= 0:
                HSCROLL_DRAGGING = False
                return

            scroll_range = content_w - vw

            if scroll_range <= 0:
                HSCROLL_DRAGGING = False
                return

            try:
                thumb_w = int(track_w * (vw / float(content_w)))
            except Exception:
                thumb_w = HSCROLL_MIN_THUMB

            if thumb_w < HSCROLL_MIN_THUMB:
                thumb_w = HSCROLL_MIN_THUMB

            if thumb_w > track_w:
                thumb_w = track_w

            new_thumb_x = x - HSCROLL_DRAG_CURSOR_OFFSET

            min_x = track_x
            max_x = track_x + track_w - thumb_w

            if new_thumb_x < min_x:
                new_thumb_x = min_x

            if new_thumb_x > max_x:
                new_thumb_x = max_x

            if track_w - thumb_w <= 0:
                frac = 0.0
            else:
                try:
                    frac = (new_thumb_x - track_x) / float(track_w - thumb_w)
                except Exception:
                    frac = 0.0

            if frac < 0.0:
                frac = 0.0

            if frac > 1.0:
                frac = 1.0

            try:
                new_first = int(round(frac * scroll_range))
            except Exception:
                new_first = FIRST_VISIBLE_X

            old_first = FIRST_VISIBLE_X
            FIRST_VISIBLE_X = new_first

            clampxscroll()

            if FIRST_VISIBLE_X != old_first:
                queueinteractionredraw(viewport=True, horizontal=True)

        except Exception as e:

            logmsg(f'> error handling horizontal scrollbar drag {e}')
            return

        return

    if SCROLLBAR_DRAGGING:

        try:

            total_lines = displaylinecount()

            if VISIBLE_LINES <= 0 or total_lines <= VISIBLE_LINES:
                SCROLLBAR_DRAGGING = False
                return

            track_x, track_y, track_w, track_h = scrollbartrackgeometry()

            if track_h <= 0:
                SCROLLBAR_DRAGGING = False
                return

            scroll_range = total_lines - VISIBLE_LINES

            if scroll_range <= 0:
                SCROLLBAR_DRAGGING = False
                return

            thumb_x, thumb_y, thumb_w, thumb_h = scrollbarthumbgeometry()

            if thumb_w <= 0 or thumb_h <= 0:
                SCROLLBAR_DRAGGING = False
                return

            new_thumb_y = y - SCROLLBAR_DRAG_CURSOR_OFFSET

            min_y = track_y
            max_y = track_y + track_h - thumb_h

            if new_thumb_y < min_y:
                new_thumb_y = min_y

            if new_thumb_y > max_y:
                new_thumb_y = max_y

            if track_h - thumb_h <= 0:
                frac = 0.0
            else:
                try:
                    frac = (new_thumb_y - track_y) / float(track_h - thumb_h)
                except Exception:
                    frac = 0.0

            if frac < 0.0:
                frac = 0.0

            if frac > 1.0:
                frac = 1.0

            try:
                new_first = int(round(frac * scroll_range))
            except Exception:
                new_first = FIRST_VISIBLE_ROW

            if new_first < 0:
                new_first = 0

            if new_first > scroll_range:
                new_first = scroll_range

            old_first = FIRST_VISIBLE_ROW
            FIRST_VISIBLE_ROW = new_first

            if FIRST_VISIBLE_ROW != old_first:
                queueinteractionredraw(viewport=True, vertical=True)

        except Exception as e:

            logmsg(f'> error handling scrollbar drag {e}')
            return

        return

    if not MOUSE_SELECTING:
        return

    try:

        oldrow = CUR_ROW
        oldcol = CUR_COL
        oldfirstrow = FIRST_VISIBLE_ROW
        oldfirstx = FIRST_VISIBLE_X
        row, col = pointtodocpos(x, y)

        if row == oldrow and col == oldcol:
            return

        CUR_ROW = row
        CUR_COL = col

        updateselectionend(row, col)

        ensurecursorvisible()

        queueinteractionredraw(
            viewport=(FIRST_VISIBLE_ROW != oldfirstrow or FIRST_VISIBLE_X != oldfirstx),
            horizontal=(FIRST_VISIBLE_X != oldfirstx),
            vertical=(FIRST_VISIBLE_ROW != oldfirstrow),
        )

    except Exception as e:

        logmsg(f'> error handling selection drag {e}')
        return

    return


def handlescroll(msg):

    global LINE_HEIGHT, SCROLLSTEP

    if MENUBAR_OPEN or CONTEXT_MENU_OPEN:
        closemenu()
        closecontextmenu()

    try:

        # read dy from message
        dy = int(msg.get('dy', 0))

        # invert scroll direction so wheel down scrolls down
        dy = -dy

    except Exception as e:

        # error reading scroll amount
        logmsg(f'> error reading SCROLL {e}')
        return

    try:

        # scale scroll so it matches array (3 lines per tick)
        delta = int(dy) * int(SCROLLSTEP)

        if delta:
            queuescroll(delta)

    except Exception as e:

        # error handling scroll
        logmsg(f'> error handling scroll {e}')
        return

    return


def handlefocus(msg):

    global HAS_FOCUS
    global CURSOR_VISIBLE

    try:

        # reset pointer state on focus change
        resetpointerstate()

        state = str(msg.get('state', ''))

        if state == 'in':

            HAS_FOCUS = True
            CURSOR_VISIBLE = True

        elif state == 'out':

            HAS_FOCUS = False
            CURSOR_VISIBLE = False

        redrawfull()

    except Exception as e:

        logmsg(f'> error handling focus {e}')
        return

    return


def handledamage(msg):

    global WIN_W
    global WIN_H

    try:

        # extract damaged region if provided
        x = int(msg.get('x', 0))
        y = int(msg.get('y', 0))
        w = int(msg.get('w', WIN_W))
        h = int(msg.get('h', WIN_H))

    except Exception as e:

        # error reading damage message
        logmsg(f'> error reading DAMAGE message {e}')
        return

    try:

        # for now redraw the whole window
        # (can be optimised later to only repaint the damaged rect)
        redrawfull()

    except Exception as e:

        # error redrawing on damage
        logmsg(f'> error redrawing on DAMAGE {e}')
        return

    return


def handleresize(msg):

    global WIN_W
    global WIN_H

    try:

        # reset pointer state on resize
        resetpointerstate()

        # remove the old managed scene before the buffer geometry changes
        graphicssuspend()

        w = int(msg.get('w', WIN_W))
        h = int(msg.get('h', WIN_H))

        WIN_W = w
        WIN_H = h

        updatelayoutonresize()

    except Exception as e:

        logmsg(f'> error handling resize {e}')
        return

    return



# status functions
def selectionlength():

    try:
        if not hasselection():
            return 0

        sr, sc, er, ec = selectionbounds()

        if sr == er:
            return max(0, ec - sc)

        total = len(str(DOC_LINES[sr])) - sc
        total += ec
        total += max(0, er - sr)

        for row in range(sr + 1, er):
            total += len(str(DOC_LINES[row]))

        return total
    except Exception:
        return 0


def statusmetrictext():

    try:
        encoding = str(FILE_ENCODING).upper()

        if FILE_BOM:
            encoding += ' BOM'

        eol = {'\n': 'LF', '\r\n': 'CRLF', '\r': 'CR'}.get(FILE_NEWLINE, 'LF')
        mode = 'OVR' if OVERWRITE_MODE else 'INS'
        parts = [f'Ln {CUR_ROW + 1}', f'Col {CUR_COL + 1}']
        selected = selectionlength()

        if selected:
            parts.append(f'Sel {selected}')

        parts.extend((encoding, eol, mode, f'{FONT_SIZE_BASE}pt'))
        return '  '.join(parts)
    except Exception:
        return ''


def setstatus(message):

    global LAST_STATUS_MESSAGE
    global LAST_STATUS_TIME

    try:

        # store new message
        LAST_STATUS_MESSAGE = str(message)

        # record timestamp
        LAST_STATUS_TIME = time.time()

    except Exception as e:

        # error setting status
        logmsg(f'> error setting status {e}')
        return

    return


def clearstatusifstale():

    global LAST_STATUS_MESSAGE
    global LAST_STATUS_TIME

    try:

        # if no message, nothing to clear
        if not LAST_STATUS_MESSAGE:
            return

        timeout = 5

        now = time.time()

        if now - LAST_STATUS_TIME > timeout:

            LAST_STATUS_MESSAGE = ''
            LAST_STATUS_TIME = 0.0

            try:

                # repaint so the status bar visually clears
                redrawstatusbar()

            except Exception as e:

                logmsg(f'> error redrawing after clearing stale status {e}')

    except Exception as e:

        # error clearing stale status
        logmsg(f'> error clearing stale status {e}')
        return

    return


# main functions
def initapp():

    global APP_RUNNING
    global FILE_PATH

    loadsettings()

    try:

        # parse command line arguments
        parseargs()

    except Exception as e:

        # argument parsing error
        logmsg(f'> error during argument parsing {e}')
        return

    try:

        # load initial document
        if FILE_PATH:

            loaddocumentfromfile(FILE_PATH)

        else:

            initialisedocument()

    except Exception as e:

        # document init error
        logmsg(f'> error initialising document {e}')
        return

    try:

        # connect to window server
        connectwindowserver()

    except SystemExit:

        # connection errors already reported
        return

    except Exception as e:

        # unexpected connection error
        logmsg(f'> error during window server connection {e}')
        return

    try:

        # perform hello handshake
        sendhello()

    except Exception as e:

        # handshake error
        logmsg(f'> error during window server hello {e}')
        return

    try:

        # create application window
        createwindow()

    except Exception as e:

        # window creation error
        logmsg(f'> error during window creation {e}')
        return

    if WINDOW_ID is None or not BUFFER_PATH:

        # window did not initialise correctly
        logmsg('> window was not created correctly')
        return

    try:

        # initialise graphics for window
        initgraphics()

    except Exception as e:

        # graphics init error
        logmsg(f'> error initialising graphics {e}')
        return

    try:

        # update layout metrics for current size
        updatelayoutonresize(redraw=False)

    except Exception as e:

        # layout update error
        logmsg(f'> error updating layout {e}')
        return

    try:

        # draw first frame
        redrawfull()

    except Exception as e:

        # initial redraw error
        logmsg(f'> error drawing initial frame {e}')
        return

    try:

        # map and focus window
        mapwindow()

    except Exception as e:

        # map error
        logmsg(f'> error mapping window {e}')
        return

    # application is now running
    APP_RUNNING = True

    return


def mainloop():

    global APP_RUNNING, LAST_CURSOR_TOGGLE, CURSOR_VISIBLE

    # only enter loop if app is running
    if not APP_RUNNING:
        return

    try:

        # frame timing
        last_frame_time = time.time()
        frame_interval = 0.05

        while APP_RUNNING:

            # poll window events
            pollwindowevents(0.01)
            pollfileio()

            if docwidthindexstep():
                redrawviewport(horizontal=True)

            # Advance queued wheel movement in eased, frame-paced steps.
            flushscroll()
            flushinteractionredraw()

            # clear stale status messages
            clearstatusifstale()

            # flush deferred managed scenes and enforce commit timeouts
            graphicsretry()
            graphicspump()

            # toggle cursor visibility
            try:

                now2 = time.time()

                if now2 - LAST_CURSOR_TOGGLE >= 0.5:

                    CURSOR_VISIBLE = not CURSOR_VISIBLE

                    LAST_CURSOR_TOGGLE = now2

                    redrawregionaroundcursororline()

            except Exception as e:

                # cursor toggle error
                logmsg(f'> error toggling cursor {e}')
                pass


    except Exception as e:

        # unexpected main loop error
        logmsg(f'> error in main loop {e}')
        APP_RUNNING = False

    return


def queuescroll(delta):

    global PENDING_SCROLL

    try:

        limit = max(1, displaylinecount())
        PENDING_SCROLL += int(delta)
        PENDING_SCROLL = max(-limit, min(limit, PENDING_SCROLL))

    except Exception as e:

        logmsg(f'> error queueing document scroll {e}')
        return False

    return bool(PENDING_SCROLL)


def cancelsmoothscroll():

    global PENDING_SCROLL, LAST_SCROLL_FRAME

    PENDING_SCROLL = 0
    LAST_SCROLL_FRAME = 0.0


def queueinteractionredraw(viewport=False, horizontal=False, vertical=False):

    global PENDING_INTERACTION_REDRAW

    try:

        requested = 2 if viewport else 1

        if horizontal:
            requested |= 4

        if vertical:
            requested |= 8

        if viewport:
            PENDING_INTERACTION_REDRAW &= ~1
        elif PENDING_INTERACTION_REDRAW & 2:
            requested &= ~1

        PENDING_INTERACTION_REDRAW |= requested

        return True

    except Exception as e:

        logmsg(f'> error queueing interaction redraw {e}')
        return False


def flushinteractionredraw(force=False, redraw=True):

    global PENDING_INTERACTION_REDRAW
    global LAST_INTERACTION_FRAME
    global INTERACTION_REDRAWS

    if not PENDING_INTERACTION_REDRAW:
        return False

    try:

        now = time.monotonic()
        managed = bool(GRAPHICSSTATE.get('active') and GRAPHICSSTATE.get('managed_only'))
        interval = SCROLL_MANAGED_INTERVAL if managed else INTERACTION_CPU_INTERVAL

        if not force and LAST_INTERACTION_FRAME and now - LAST_INTERACTION_FRAME < interval:
            return False

        redrawmode = int(PENDING_INTERACTION_REDRAW)
        PENDING_INTERACTION_REDRAW = 0

        if redraw:

            if redrawmode & 2:
                redrawviewport(horizontal=bool(redrawmode & 4), vertical=bool(redrawmode & 8))
            else:
                redrawregionaroundcursororline()

        LAST_INTERACTION_FRAME = now
        INTERACTION_REDRAWS += 1
        return True

    except Exception as e:

        logmsg(f'> error flushing interaction redraw {e}')
        return False


def flushscroll(force=False, redraw=True):

    global PENDING_SCROLL
    global LAST_SCROLL_FRAME
    global SCROLL_REDRAWS

    if not PENDING_SCROLL:
        return False

    try:

        now = time.monotonic()
        managed = bool(GRAPHICSSTATE.get('active') and GRAPHICSSTATE.get('managed_only'))
        interval = SCROLL_MANAGED_INTERVAL if managed else SCROLL_CPU_INTERVAL

        if not force and LAST_SCROLL_FRAME and now - LAST_SCROLL_FRAME < interval:
            return False

        remaining = int(PENDING_SCROLL)
        magnitude = abs(remaining)

        if force:
            amount = magnitude
        else:
            amount = max(1, int(math.ceil(magnitude * SMOOTH_SCROLL_EASING)))
            amount = min(amount, SMOOTH_SCROLL_MAX_STEP)

        delta = amount if remaining > 0 else -amount
        PENDING_SCROLL -= delta
        oldfirst = int(FIRST_VISIBLE_ROW)
        scrollbylines(delta)

        if FIRST_VISIBLE_ROW == oldfirst:
            PENDING_SCROLL = 0

        if redraw and FIRST_VISIBLE_ROW != oldfirst:
            redrawviewport(vertical=True)

        LAST_SCROLL_FRAME = now
        SCROLL_REDRAWS += 1
        return True

    except Exception as e:

        logmsg(f'> error flushing document scroll {e}')
        return False


def editorfeaturechecks():

    global CUR_ROW, CUR_COL, FIRST_VISIBLE_ROW, VISIBLE_LINES
    global FILE_ENCODING, FILE_BOM, FILE_NEWLINE
    global WORD_WRAP, TAB_WIDTH, INDENT_USE_TABS, OVERWRITE_MODE
    global FIND_QUERY, REPLACE_QUERY, FIND_MATCH_CASE, RECENT_FILES

    snapshot = getdocumenttext()
    savedcursor = (CUR_ROW, CUR_COL, FIRST_VISIBLE_ROW, VISIBLE_LINES)
    savedformat = (FILE_ENCODING, FILE_BOM, FILE_NEWLINE)
    savedoptions = (WORD_WRAP, TAB_WIDTH, INDENT_USE_TABS, OVERWRITE_MODE)
    savedsearch = (FIND_QUERY, REPLACE_QUERY, FIND_MATCH_CASE)
    savedrecent = list(RECENT_FILES)
    formatinput = os.path.join(WRITELOGBASE, f'write-format-input-{os.getpid()}.txt')
    formatoutput = os.path.join(WRITELOGBASE, f'write-format-output-{os.getpid()}.txt')
    checks = {}

    try:
        request = dialogrequest(
            'write-diagnostic',
            'diagnostic',
            'enter text',
            [
                {'id': 'ok', 'label': 'ok'},
                {'id': 'cancel', 'label': 'cancel', 'cancel': True},
            ],
            inputrequest={
                'value': 'sample',
                'select_all': True,
                'max_length': 256,
                'allow_empty': False,
            },
        )

        if request.get('op') != 'CREATE_DIALOG' or not request.get('input') or len(request.get('buttons', [])) != 2:
            raise RuntimeError('native text dialog request is incomplete')

        confirm = dialogrequest(
            'write-confirm-diagnostic',
            'unsaved changes',
            'save changes?',
            [
                {'id': 'save', 'label': 'save'},
                {'id': 'discard', 'label': 'discard'},
                {'id': 'cancel', 'label': 'cancel', 'cancel': True},
            ],
        )

        if 'input' in confirm or [button['id'] for button in confirm['buttons']] != ['save', 'discard', 'cancel']:
            raise RuntimeError('native confirmation dialog request is incomplete')

        checks['native_dialogs'] = True

        TAB_WIDTH = 4
        INDENT_USE_TABS = False
        gfx.TEXTTABWIDTH = TAB_WIDTH
        loaddocumentfromtext('a\tb')
        advances = measurelineadvances(('metrics', 'feature-tab', 1), DOC_LINES[0], FONT_SIZE, FONT_PATH)
        shown = expanddisplaytabs(DOC_LINES[0])

        if shown != 'a   b' or int(advances[-1]) != int(measuretext(shown, FONT_SIZE, FONT_PATH)):
            raise RuntimeError('literal tab rendering does not follow tab stops')

        loaddocumentfromtext('    item')
        CUR_ROW, CUR_COL = 0, len(DOC_LINES[0])
        handlenewline()

        if DOC_LINES != ['    item', '    ']:
            raise RuntimeError('Enter did not preserve leading indentation')

        loaddocumentfromtext('abc')
        OVERWRITE_MODE = True
        CUR_ROW, CUR_COL = 0, 1
        insertcharacter('X')

        if DOC_LINES != ['aXc']:
            raise RuntimeError('overwrite mode inserted instead of replacing')

        OVERWRITE_MODE = False
        loaddocumentfromtext('hello world')
        CUR_ROW, CUR_COL = 0, len(DOC_LINES[0])
        movecursorword(reverse=True)

        if (CUR_ROW, CUR_COL) != (0, 6):
            raise RuntimeError('word-left navigation stopped at the wrong column')

        CUR_COL = len(DOC_LINES[0])
        deleteword(reverse=True)

        if DOC_LINES != ['hello ']:
            raise RuntimeError('Ctrl+Backspace deleted the wrong word')

        loaddocumentfromtext('Alpha beta\nalpha beta')
        FIND_MATCH_CASE = False
        FIND_QUERY = 'alpha'
        REPLACE_QUERY = 'omega'
        CUR_ROW = CUR_COL = 0

        if not findnext() or selectedtext() != 'Alpha':
            raise RuntimeError('case-insensitive Find failed')

        if not replaceone() or str(DOC_LINES[0]) != 'omega beta':
            raise RuntimeError('Replace failed')

        if replaceall() != 1 or DOC_LINES != ['omega beta', 'omega beta']:
            raise RuntimeError('Replace All failed')

        loaddocumentfromtext('one\ntwo\nthree')

        if not gotoline('3') or (CUR_ROW, CUR_COL) != (2, 0):
            raise RuntimeError('Go to Line failed')

        CUR_ROW, CUR_COL = 0, 0
        duplicatelines()

        if DOC_LINES != ['one', 'one', 'two', 'three']:
            raise RuntimeError('Duplicate Line failed')

        deletelines()

        if DOC_LINES != ['one', 'two', 'three']:
            raise RuntimeError('Delete Line failed')

        loaddocumentfromtext('mixed Case')
        setselectionanchor(0, 0)
        CUR_ROW, CUR_COL = 0, len(DOC_LINES[0])
        updateselectionend(CUR_ROW, CUR_COL)
        transformselection('upper')

        if DOC_LINES != ['MIXED CASE']:
            raise RuntimeError('selection case conversion failed')

        loaddocumentfromtext('   home')
        CUR_ROW, CUR_COL = 0, len(DOC_LINES[0])
        movecursorhome()

        if CUR_COL != 3:
            raise RuntimeError('smart Home did not stop at the first non-whitespace column')

        movecursorhome()

        if CUR_COL != 0:
            raise RuntimeError('second smart Home did not move to column zero')

        loaddocumentfromlines([str(index) for index in range(10)])
        VISIBLE_LINES = 3
        CUR_ROW, CUR_COL = 5, 0
        pageup()

        if CUR_ROW != 2:
            raise RuntimeError('Page Up did not move the caret')

        pagedown()

        if CUR_ROW != 5:
            raise RuntimeError('Page Down did not move the caret')

        FILE_ENCODING = 'utf-8'
        FILE_BOM = True
        FILE_NEWLINE = '\r\n'
        metric = statusmetrictext()

        if 'Ln 6' not in metric or 'UTF-8 BOM' not in metric or 'CRLF' not in metric:
            raise RuntimeError('status metrics omitted caret or file format details')

        os.makedirs(WRITELOGBASE, exist_ok=True)
        expectedbytes = codecs.BOM_UTF8 + b'alpha\r\nbeta\r\n'

        with open(formatinput, 'wb') as stream:
            stream.write(expectedbytes)

        payload = readfilepayload(formatinput)
        fileformat = payload.get('metadata', {}).get('format', {})

        if (
            payload.get('lines') != ['alpha', 'beta', '']
            or fileformat.get('encoding') != 'utf-8'
            or not fileformat.get('bom')
            or fileformat.get('newline') != '\r\n'
        ):
            raise RuntimeError('UTF-8 BOM/CRLF detection failed')

        writefilesnapshot(
            formatoutput,
            tuple(payload['lines']),
            fileformat['encoding'],
            fileformat['bom'],
            fileformat['newline'],
        )

        with open(formatoutput, 'rb') as stream:
            actualbytes = stream.read()

        if actualbytes != expectedbytes:
            raise RuntimeError('encoding and line-ending round trip changed file bytes')

        RECENT_FILES.append(formatinput)
        recentmenu = menudefinitions()['file']

        checks.update({
            'literal_tabs': True,
            'auto_indent': True,
            'overwrite_mode': True,
            'word_navigation': True,
            'find_replace': True,
            'goto_line': True,
            'line_operations': True,
            'case_conversion': True,
            'smart_home': True,
            'page_caret': True,
            'status_metrics': True,
            'file_fidelity': True,
            'print_backend': isinstance(printcommand(formatoutput), list),
            'recent_files_menu': any(
                action.startswith('file_recent_')
                for _, _, action in recentmenu
            ),
        })

        return checks

    finally:
        for path in (formatinput, formatoutput):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass

        WORD_WRAP, TAB_WIDTH, INDENT_USE_TABS, OVERWRITE_MODE = savedoptions
        gfx.TEXTTABWIDTH = TAB_WIDTH
        FIND_QUERY, REPLACE_QUERY, FIND_MATCH_CASE = savedsearch
        RECENT_FILES = savedrecent
        loaddocumentfromtext(snapshot)
        FILE_ENCODING, FILE_BOM, FILE_NEWLINE = savedformat
        CUR_ROW = max(0, min(len(DOC_LINES) - 1, savedcursor[0]))
        CUR_COL = max(0, min(len(str(DOC_LINES[CUR_ROW])), savedcursor[1]))
        FIRST_VISIBLE_ROW = savedcursor[2]
        VISIBLE_LINES = savedcursor[3]
        clearselection()
        historyreset()


def writeperformancediagnostic():

    global WIN_W, WIN_H, CUR_ROW, CUR_COL, FIRST_VISIBLE_ROW, FIRST_VISIBLE_X
    global FILE_NAME, LAST_STATUS_MESSAGE, INPUT_MODE, PROMPT_TEXT, PROMPT_BUFFER
    global HAS_FOCUS, CURSOR_VISIBLE, MENUBAR_OPEN, SEL_ACTIVE, VISIBLE_LINES
    global SAVED_REVISION, IS_DIRTY
    global PENDING_SCROLL, LAST_SCROLL_FRAME, SCROLL_REDRAWS
    global PENDING_INTERACTION_REDRAW, LAST_INTERACTION_FRAME, INTERACTION_REDRAWS
    global WORD_WRAP, WRAP_LINES_MEASURED, WRAP_REFLOW_FROM
    global GRAPHICSSTATE, LASTDRAWNROW, LASTDRAWNCOL

    result = {
        'format': 1,
        'passed': False,
        'errors': [],
    }

    try:

        candidates = [
            '/the one/build/brick/brick.py',
            os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'brick', 'brick.py')),
        ]
        sourcepath = next((path for path in candidates if os.path.isfile(path)), None)

        if sourcepath:
            with open(sourcepath, 'r', encoding='utf-8') as f:
                source = f.read()
        else:
            source = '\n'.join(
                f'def diagnostic_{row}(value): return value + {row}'
                for row in range(12500)
            )
            sourcepath = 'synthetic-brick.py'

        setscreensize(2560, 1440)
        WIN_W = 1200
        WIN_H = 800
        initttffont(FONT_PATH, FONT_SIZE)
        gfx.TTFADVANCES.clear()
        gfx.ADVCACHE.clear()

        started = time.monotonic_ns()
        loaddocumentfromtext(source)
        loadms = (time.monotonic_ns() - started) / 1000000.0

        FILE_NAME = 'brick.py'
        LAST_STATUS_MESSAGE = 'ready'
        INPUT_MODE = 'edit'
        PROMPT_TEXT = ''
        PROMPT_BUFFER = ''
        HAS_FOCUS = True
        CURSOR_VISIBLE = True
        MENUBAR_OPEN = None
        SEL_ACTIVE = False
        FIRST_VISIBLE_ROW = 0
        FIRST_VISIBLE_X = 0
        VISIBLE_LINES = 0

        original = getdocumenttext()
        row = min(max(0, len(DOC_LINES) // 2), len(DOC_LINES) - 1)
        CUR_ROW = row
        CUR_COL = len(str(DOC_LINES[row]))

        operationms = {}

        started = time.monotonic_ns()
        insertcharacter('x')
        operationms['character_insert'] = (time.monotonic_ns() - started) / 1000000.0

        started = time.monotonic_ns()
        undo()
        operationms['undo_character'] = (time.monotonic_ns() - started) / 1000000.0

        if getdocumenttext() != original:
            raise RuntimeError('character undo did not restore the document')

        started = time.monotonic_ns()
        redo()
        operationms['redo_character'] = (time.monotonic_ns() - started) / 1000000.0
        undo()

        CUR_ROW = row
        CUR_COL = max(0, len(str(DOC_LINES[row])) // 2)
        started = time.monotonic_ns()
        handlenewline()
        operationms['newline_insert'] = (time.monotonic_ns() - started) / 1000000.0
        undo()

        if getdocumenttext() != original:
            raise RuntimeError('newline undo did not restore the document')

        CUR_ROW = min(row + 1, len(DOC_LINES) - 1)
        CUR_COL = 0
        started = time.monotonic_ns()
        handlebackspace()
        operationms['backspace_line_join'] = (time.monotonic_ns() - started) / 1000000.0
        undo()

        if getdocumenttext() != original:
            raise RuntimeError('line-join backspace undo did not restore the document')

        CUR_ROW = row
        CUR_COL = len(str(DOC_LINES[row]))
        started = time.monotonic_ns()
        handledelete()
        operationms['delete_line_join'] = (time.monotonic_ns() - started) / 1000000.0
        undo()

        if getdocumenttext() != original:
            raise RuntimeError('line-join delete undo did not restore the document')

        erow = min(row + 1, len(DOC_LINES) - 1)
        started = time.monotonic_ns()
        editreplace(row, 1, erow, min(7, len(str(DOC_LINES[erow]))), 'replacement')
        operationms['selection_replace'] = (time.monotonic_ns() - started) / 1000000.0
        undo()

        if getdocumenttext() != original:
            raise RuntimeError('selection replacement undo did not restore the document')

        # Tab uses column-aligned spaces without a selection and line-based
        # indent/outdent for selections. Both forms must remain one-step
        # undoable edits.
        historyreset()
        CUR_ROW = row
        CUR_COL = min(3, len(str(DOC_LINES[row])))
        tabline = str(DOC_LINES[row])
        tabcolumn = int(CUR_COL)
        tabcount = TAB_WIDTH - (tabcolumn % TAB_WIDTH)

        if not handleindentation() or str(DOC_LINES[row]) != tabline[:tabcolumn] + (' ' * tabcount) + tabline[tabcolumn:]:
            raise RuntimeError('Tab did not insert spaces to the next tab stop')

        undo()

        if getdocumenttext() != original:
            raise RuntimeError('single-caret Tab undo did not restore the document')

        historyreset()
        indentfirst = row
        indentlast = min(row + 2, len(DOC_LINES) - 1)
        indentbefore = [str(DOC_LINES[index]) for index in range(indentfirst, indentlast + 1)]
        setselectionanchor(indentfirst, min(1, len(indentbefore[0])))

        if indentlast + 1 < len(DOC_LINES):
            CUR_ROW = indentlast + 1
            CUR_COL = 0
        else:
            CUR_ROW = indentlast
            CUR_COL = len(indentbefore[-1])

        updateselectionend(CUR_ROW, CUR_COL)

        if not handleindentation():
            raise RuntimeError('selected-line Tab did not make an edit')

        if any(
            str(DOC_LINES[index]) != (' ' * TAB_WIDTH) + indentbefore[index - indentfirst]
            for index in range(indentfirst, indentlast + 1)
        ):
            raise RuntimeError('selected-line Tab did not indent every selected line')

        if not handleindentation(outdent=True):
            raise RuntimeError('selected-line Shift+Tab did not make an edit')

        if [
            str(DOC_LINES[index])
            for index in range(indentfirst, indentlast + 1)
        ] != indentbefore:
            raise RuntimeError('selected-line Shift+Tab did not restore the selected lines')

        undo()
        undo()

        if getdocumenttext() != original:
            raise RuntimeError('selected indentation undo did not restore the document')

        historyreset()
        CUR_ROW = row
        CUR_COL = len(str(DOC_LINES[row]))
        edits = []

        for _ in range(200):
            started = time.monotonic_ns()
            insertcharacter('x')
            edits.append((time.monotonic_ns() - started) / 1000000.0)

        if len(UNDO_STACK) != 1:
            raise RuntimeError(f'200 adjacent inserts produced {len(UNDO_STACK)} undo records')

        historybytes = int(UNDO_BYTES)
        undo()

        if getdocumenttext() != original:
            raise RuntimeError('coalesced typing undo did not restore the document')

        typingcoalesced = len(UNDO_STACK) == 0
        historyreset()
        CUR_ROW = row
        CUR_COL = len(str(DOC_LINES[row]))
        insertcharacter('s')
        SAVED_REVISION = CURRENT_REVISION
        IS_DIRTY = False
        insertcharacter('x')
        undo()

        if IS_DIRTY or not str(DOC_LINES[row]).endswith('s'):
            raise RuntimeError('undo did not return to the saved revision')

        undo()
        historyreset()

        if getdocumenttext() != original:
            raise RuntimeError('saved revision test did not restore the document')

        expectedwidths = [int(measuretext(str(line), FONT_SIZE)) for line in DOC_LINES]

        if DOC_LINEW != expectedwidths or int(DOC_MAXW) != max(expectedwidths, default=0):
            raise RuntimeError('incremental document widths do not match full measurement')

        # A single wrapped-line edit must not invalidate or remeasure the
        # complete document.
        WORD_WRAP = True
        invalidatewrapcache(drop_lines=True)
        ensurewrapindex()
        wrappedcount = displaylinecount()
        proberow = min(max(1, len(DOC_LINES) // 2), len(DOC_LINES) - 2)
        neighboursegments = WRAP_LINE_SEGMENTS[proberow + 1]
        CUR_ROW = proberow
        CUR_COL = len(str(DOC_LINES[proberow]))
        measuredbefore = int(WRAP_LINES_MEASURED)
        started = time.monotonic_ns()
        insertcharacter('w')
        ensurewrapindex()
        wrappededitms = (time.monotonic_ns() - started) / 1000000.0
        measurededit = int(WRAP_LINES_MEASURED) - measuredbefore

        if measurededit > 1:
            raise RuntimeError(f'wrapped edit remeasured {measurededit} lines')

        if WRAP_LINE_SEGMENTS[proberow + 1] is not neighboursegments:
            raise RuntimeError('wrapped edit invalidated an unchanged neighbouring line')

        if displaylinecount() < len(DOC_LINES) or wrappedcount < len(DOC_LINES):
            raise RuntimeError('wrapped visual row index is incomplete')

        undo()
        ensurewrapindex()
        WORD_WRAP = False
        WRAP_REFLOW_FROM = None
        invalidatewrapcache()

        # Large asynchronous loads start with a sparse width index.  Visible
        # rows can be measured immediately while the rest advances in bounded
        # main-loop slices.
        docwidthbeginindex()
        docwidthindexline(proberow)

        if sum(1 for value in DOC_LINEW if value is not None) != 1:
            raise RuntimeError('lazy width index measured more than the requested visible line')

        while DOC_WIDTH_INDEX_ACTIVE:
            docwidthindexstep(budget_ms=1000.0)

        if DOC_LINEW != expectedwidths or int(DOC_MAXW) != max(expectedwidths, default=0):
            raise RuntimeError('lazy width index differs from the complete width index')

        iopath = os.path.join(WRITELOGBASE, f'write-io-{os.getpid()}.txt')

        try:
            filesaveworker(
                iopath,
                tuple(DOC_LINES),
                CURRENT_REVISION,
                FILE_ENCODING,
                FILE_BOM,
                FILE_NEWLINE,
            )

            with FILE_IO_LOCK:
                saveresult = dict(FILE_IO_RESULT or {})

            if not saveresult.get('ok'):
                raise RuntimeError(f'streaming save failed {saveresult}')

            fileloadworker(iopath)

            with FILE_IO_LOCK:
                loadresult = dict(FILE_IO_RESULT or {})

            if not loadresult.get('ok') or '\n'.join(loadresult.get('lines', [])) != original:
                raise RuntimeError('streaming load/save round trip differs from the document')

            loadmetadata = loadresult.get('metadata', {})

            if (
                len(loadmetadata.get('ids', [])) != len(loadresult.get('lines', []))
                or len(loadmetadata.get('versions', [])) != len(loadresult.get('lines', []))
            ):
                raise RuntimeError('streaming load did not prepare document metadata off-thread')

        finally:

            try:
                if os.path.exists(iopath):
                    os.remove(iopath)
            except Exception:
                pass

        graphicsbuildscene()
        scenes = []

        for _ in range(25):
            started = time.monotonic_ns()
            graphicsbuildscene()
            scenes.append((time.monotonic_ns() - started) / 1000000.0)

        maximumedit = max(edits + list(operationms.values()))
        averagescene = sum(scenes) / max(1, len(scenes))
        maximumscene = max(scenes, default=0.0)
        sortededits = sorted(edits)
        percentile95 = sortededits[min(len(sortededits) - 1, int(len(sortededits) * 0.95))]

        FIRST_VISIBLE_ROW = 0
        PENDING_SCROLL = 0
        LAST_SCROLL_FRAME = 0.0
        redrawsbefore = int(SCROLL_REDRAWS)

        for _ in range(1000):
            handlescroll({'dy': -1})

        if FIRST_VISIBLE_ROW != 0 or PENDING_SCROLL != 3000:
            raise RuntimeError(f'rapid wheel input was not coalesced {FIRST_VISIBLE_ROW}/{PENDING_SCROLL}')

        if not flushscroll(force=True, redraw=False):
            raise RuntimeError('coalesced wheel input did not flush')

        expectedscroll = min(3000, max(0, len(DOC_LINES) - VISIBLE_LINES))

        if FIRST_VISIBLE_ROW != expectedscroll or SCROLL_REDRAWS != redrawsbefore + 1:
            raise RuntimeError(f'coalesced wheel input produced the wrong viewport {FIRST_VISIBLE_ROW}/{SCROLL_REDRAWS}')

        PENDING_INTERACTION_REDRAW = 0
        LAST_INTERACTION_FRAME = 0.0
        interactionbefore = int(INTERACTION_REDRAWS)

        for _ in range(1000):
            queueinteractionredraw()

        queueinteractionredraw(viewport=True)

        if PENDING_INTERACTION_REDRAW != 2:
            raise RuntimeError(f'rapid pointer input was not coalesced {PENDING_INTERACTION_REDRAW}')

        if not flushinteractionredraw(force=True, redraw=False):
            raise RuntimeError('coalesced pointer input did not flush')

        if INTERACTION_REDRAWS != interactionbefore + 1:
            raise RuntimeError(f'coalesced pointer input produced {INTERACTION_REDRAWS - interactionbefore} redraws')

        longline = ''.join(f'horizontal-{index:05d} ' for index in range(10000))
        longwidth = max(1, int(measuretext(longline, FONT_SIZE, FONT_PATH)))
        visibletext, visiblex, visiblestart = visiblelineslice(
            0,
            longline,
            MARGIN_LEFT - (longwidth // 2),
            MARGIN_LEFT,
            1200,
        )

        if not visibletext or len(visibletext) >= len(longline) or visiblestart <= 0:
            raise RuntimeError('horizontal clipping retained the complete off-screen line')

        if historybytes > 65536:
            raise RuntimeError(f'coalesced typing history used {historybytes} bytes')

        # Exercise the complete CPU fallback path, including rasterization,
        # shared-buffer presentation, selection damage, scrolling, and wrap.
        bufferpath = os.path.join(WRITELOGBASE, f'write-performance-{os.getpid()}.buffer')
        cpusamples = {}

        try:
            with open(bufferpath, 'wb') as stream:
                stream.truncate(int(WIN_W) * int(WIN_H) * 4)

            initbuffer(bufferpath, WIN_W, WIN_H)
            GRAPHICSSTATE = managedstate(cpu=True)
            WORD_WRAP = False
            invalidatewrapcache(drop_lines=True)
            CUR_ROW = min(100, len(DOC_LINES) - 1)
            CUR_COL = min(10, len(str(DOC_LINES[CUR_ROW])))
            FIRST_VISIBLE_ROW = max(0, CUR_ROW - 5)
            FIRST_VISIBLE_X = 0
            LASTDRAWNROW = CUR_ROW
            LASTDRAWNCOL = CUR_COL
            redrawfull()

            def sampleoperation(name, function, count):
                values = []

                for _ in range(count):
                    started = time.monotonic_ns()
                    function()
                    values.append((time.monotonic_ns() - started) / 1000000.0)

                cpusamples[name] = {
                    'average_ms': sum(values) / max(1, len(values)),
                    'maximum_ms': max(values, default=0.0),
                }

            sampleoperation('full_redraw', redrawfull, 3)
            sampleoperation(
                'typing',
                lambda: handlekey({'text': 'x', 'state': 'down', 'mods': ''}),
                8,
            )
            clearselection()
            CUR_COL = 0
            sampleoperation(
                'shift_selection',
                lambda: handlekey({'text': '<RIGHT>', 'state': 'down', 'mods': 'shift'}),
                8,
            )
            clearselection()
            FIRST_VISIBLE_ROW = max(0, CUR_ROW - 5)
            redrawfull()
            sampleoperation(
                'scroll',
                lambda: (scrollbylines(3), redrawviewport(vertical=True)),
                8,
            )
            WORD_WRAP = True
            invalidatewrapcache(drop_lines=True)
            ensurecursorvisible()
            redrawfull()
            sampleoperation(
                'wrapped_typing',
                lambda: handlekey({'text': 'w', 'state': 'down', 'mods': ''}),
                8,
            )

        finally:
            WORD_WRAP = False
            invalidatewrapcache(drop_lines=True)

            try:
                gfx.close()
            except Exception:
                pass

            try:
                if os.path.exists(bufferpath):
                    os.remove(bufferpath)
            except Exception:
                pass

        if cpusamples.get('typing', {}).get('maximum_ms', 1000.0) > 33.0:
            raise RuntimeError(f"CPU typing exceeded 33 ms {cpusamples['typing']}")

        if cpusamples.get('shift_selection', {}).get('maximum_ms', 1000.0) > 33.0:
            raise RuntimeError(f"CPU selection exceeded 33 ms {cpusamples['shift_selection']}")

        if cpusamples.get('scroll', {}).get('maximum_ms', 1000.0) > 33.0:
            raise RuntimeError(f"CPU scroll exceeded 33 ms {cpusamples['scroll']}")

        if cpusamples.get('wrapped_typing', {}).get('maximum_ms', 1000.0) > 33.0:
            raise RuntimeError(f"CPU wrapped typing exceeded 33 ms {cpusamples['wrapped_typing']}")

        # Keep a compact advance index for pathological one-line documents.
        # The cold scan is deliberately separated from the edit samples: once
        # indexed, ordinary append/backspace editing must remain frame-fast.
        gfx.ADVCACHE.clear()
        gfx.ADVCACHESIZES.clear()
        gfx.ADVCACHEBYTES = 0
        gfx.ADVRECENT.clear()
        gfx.ADVRECENTBYTES = 0
        stressline = ('abcdef0123456789 ' * 58824)[:1000000]
        stressidentity = ('metrics', 'million-character-line', 0)
        started = time.monotonic_ns()
        stressadvances = gfx.measurelineadvances(
            stressidentity,
            stressline,
            FONT_SIZE,
            FONT_PATH,
        )
        longlinecoldms = (time.monotonic_ns() - started) / 1000000.0

        if len(stressadvances) != len(stressline):
            raise RuntimeError('million-character line advance index is incomplete')

        if getattr(stressadvances, 'itemsize', 0) != 4:
            raise RuntimeError('million-character line advance index is not compact')

        longlineedits = []

        for version in range(1, 13):
            stressline += 'x'
            started = time.monotonic_ns()
            stressadvances = gfx.measurelineadvances(
                ('metrics', 'million-character-line', version),
                stressline,
                FONT_SIZE,
                FONT_PATH,
            )
            bisect.bisect_left(stressadvances, int(stressadvances[-1]) // 2)
            longlineedits.append((time.monotonic_ns() - started) / 1000000.0)

        longlinemaximum = max(longlineedits, default=0.0)

        if longlinemaximum > 33.0:
            raise RuntimeError(f'million-character line edit exceeded 33 ms ({longlinemaximum:.3f} ms)')

        if int(gfx.ADVCACHEBYTES) > int(gfx.ADVCACHEBYTELIMIT):
            raise RuntimeError('advance cache exceeded its byte limit')

        if int(gfx.ADVRECENTBYTES) > int(gfx.ADVRECENTLIMIT):
            raise RuntimeError('recent advance cache exceeded its byte limit')

        if int(WRAP_LINE_CACHE_BYTES) > int(WRAP_LINE_CACHE_LIMIT):
            raise RuntimeError('wrap cache exceeded its byte limit')

        # Exercise the line metadata, Fenwick wrap index, width multiset, and
        # undo path together under deterministic mixed edits.
        mixededitsnapshot = getdocumenttext()
        mixedreference = mixededitsnapshot.split('\n')
        historyreset()
        WORD_WRAP = True
        invalidatewrapcache(drop_lines=True)
        ensurewrapindex()
        mixedseed = 0x51A7
        mixededitcount = 96

        for editindex in range(mixededitcount):
            mixedseed = (mixedseed * 1103515245 + 12345) & 0x7fffffff
            sr = mixedseed % len(mixedreference)
            sc = (mixedseed >> 5) % (len(mixedreference[sr]) + 1)
            er = sr

            if (mixedseed & 7) == 0 and sr + 1 < len(mixedreference):
                er = sr + 1

            ec = (mixedseed >> 11) % (len(mixedreference[er]) + 1)
            replacement = ('q', '', '\n', 'uv\nwx')[(mixedseed >> 17) & 3]

            if (er, ec) < (sr, sc):
                sr, sc, er, ec = er, ec, sr, sc

            prefix = mixedreference[sr][:sc]
            suffix = mixedreference[er][ec:]
            mixedreference[sr:er + 1] = (prefix + replacement + suffix).split('\n')
            editreplace(sr, sc, er, ec, replacement)
            ensurewrapindex()

            actualmixed = getdocumenttext()
            expectedmixed = '\n'.join(mixedreference)

            if actualmixed != expectedmixed:
                mismatch = next(
                    (
                        offset
                        for offset, pair in enumerate(zip(actualmixed, expectedmixed))
                        if pair[0] != pair[1]
                    ),
                    min(len(actualmixed), len(expectedmixed)),
                )
                raise RuntimeError(
                    f'mixed edit {editindex} diverged at {mismatch} '
                    f'op=({sr},{sc})-({er},{ec}) replacement={replacement!r} '
                    f'lengths={len(actualmixed)}/{len(expectedmixed)}'
                )

            visualrow = cursorvisualindex(CUR_ROW, CUR_COL)
            mappedrow, _, _ = displaysegment(visualrow)

            if mappedrow != CUR_ROW:
                raise RuntimeError(f'mixed edit {editindex} corrupted the wrap row index')

        while UNDO_STACK:
            undo()
            ensurewrapindex()

        if getdocumenttext() != mixededitsnapshot:
            raise RuntimeError('mixed-edit undo did not restore the document')

        historyreset()
        WORD_WRAP = False
        invalidatewrapcache(drop_lines=True)

        if maximumedit > 100.0:
            raise RuntimeError(f'large-file edit exceeded 100 ms ({maximumedit:.3f} ms)')

        if maximumscene > 100.0:
            raise RuntimeError(f'large-file scene build exceeded 100 ms ({maximumscene:.3f} ms)')

        featurechecks = editorfeaturechecks()

        result['document'] = {
            'source': sourcepath,
            'bytes': len(source.encode('utf-8')),
            'lines': len(DOC_LINES),
        }
        result['checks'] = {
            'document_round_trip': True,
            'incremental_widths': True,
            'operation_undo_redo': True,
            'tab_indentation': True,
            'saved_revision': True,
            'typing_coalesced': bool(typingcoalesced),
            'advance_cache_entries': len(gfx.TTFADVANCES),
            'scroll_events_coalesced': 1000,
            'scroll_redraws': int(SCROLL_REDRAWS - redrawsbefore),
            'pointer_events_coalesced': 1001,
            'pointer_redraws': int(INTERACTION_REDRAWS - interactionbefore),
            'horizontal_visible_characters': len(visibletext),
            'incremental_wrap_lines': measurededit,
            'lazy_width_index': True,
            'bounded_advance_cache': True,
            'bounded_wrap_cache': True,
            'streaming_io': True,
            'compact_long_line_index': True,
            'mixed_edit_model': mixededitcount,
            **featurechecks,
            'editor_completeness': all(featurechecks.values()),
        }
        result['performance'] = {
            'initial_load_ms': round(loadms, 3),
            'operations_ms': {name: round(value, 3) for name, value in operationms.items()},
            'typing_average_ms': round(sum(edits) / max(1, len(edits)), 3),
            'typing_percentile_95_ms': round(percentile95, 3),
            'maximum_edit_ms': round(maximumedit, 3),
            'average_scene_build_ms': round(averagescene, 3),
            'maximum_scene_build_ms': round(maximumscene, 3),
            'undo_bytes_for_200_characters': historybytes,
            'wrapped_edit_ms': round(wrappededitms, 3),
            'million_character_line': {
                'cold_index_ms': round(longlinecoldms, 3),
                'edit_average_ms': round(sum(longlineedits) / max(1, len(longlineedits)), 3),
                'edit_maximum_ms': round(longlinemaximum, 3),
            },
            'cpu': {
                name: {
                    'average_ms': round(value['average_ms'], 3),
                    'maximum_ms': round(value['maximum_ms'], 3),
                }
                for name, value in cpusamples.items()
            },
        }
        result['passed'] = True

    except Exception as e:
        result['errors'].append(str(e))

    print(json.dumps(result, separators=(',', ':'), sort_keys=True))
    return bool(result['passed'])


def writegraphicsdiagnostic():

    global WIN_W, WIN_H, DOC_LINES, CUR_ROW, CUR_COL, FIRST_VISIBLE_ROW, FIRST_VISIBLE_X
    global IS_DIRTY, FILE_NAME, LAST_STATUS_MESSAGE, INPUT_MODE, PROMPT_TEXT, PROMPT_BUFFER
    global HAS_FOCUS, CURSOR_VISIBLE, MENUBAR_OPEN, SEL_ACTIVE, SEL_ANCHOR_ROW, SEL_ANCHOR_COL
    global SEL_ROW, SEL_COL, VISIBLE_LINES
    global CONTEXT_MENU_OPEN, CONTEXT_MENU_X, CONTEXT_MENU_Y, CONTEXT_MENU_PANEL
    global CONTEXT_MENU_HOVER_ACTION, MENU_HOVER_ACTION
    global CONTEXT_PASTE_AVAILABLE

    result = {
        'format': 1,
        'passed': False,
        'resolution': [2560, 1440],
        'window': [1200, 800],
        'checks': {},
        'performance': {},
        'errors': [],
    }

    capabilities = {
        'version': 2,
        'accelerated': True,
        'managed_resources': True,
        'raw_shaders': False,
        'commands': ['rectangle', 'image', 'text'],
        'command_limit': 1024,
        'total_command_limit': 8192,
        'text_limit': 1024,
        'damage_limit': 64,
        'atomic_scene': True,
        'damage_regions': True,
        'legacy_transactions': True,
        'retained_scene': True,
    }

    try:

        setscreensize(2560, 1440)
        WIN_W = 1200
        WIN_H = 800
        initttffont(FONT_PATH, FONT_SIZE)
        longline = ''.join(f'variable width {index:04d} ' for index in range(300))
        DOC_LINES = [longline, 'selected Atkinson text', 'third visible line']
        DOC_LINES.extend(f'diagnostic line {index}' for index in range(3, 80))
        CUR_ROW = 0
        CUR_COL = 38
        FIRST_VISIBLE_ROW = 0
        FIRST_VISIBLE_X = 240
        IS_DIRTY = True
        FILE_NAME = 'managed write.txt'
        LAST_STATUS_MESSAGE = 'ready'
        INPUT_MODE = 'edit'
        PROMPT_TEXT = ''
        PROMPT_BUFFER = ''
        HAS_FOCUS = True
        CURSOR_VISIBLE = True
        MENUBAR_OPEN = 'file'
        MENU_HOVER_ACTION = 'file_open'
        CONTEXT_MENU_OPEN = False
        CONTEXT_MENU_X = 0
        CONTEXT_MENU_Y = 0
        CONTEXT_MENU_PANEL = None
        CONTEXT_PASTE_AVAILABLE = False
        SEL_ACTIVE = True
        SEL_ANCHOR_ROW = 0
        SEL_ANCHOR_COL = 30
        SEL_ROW = 0
        SEL_COL = 46
        VISIBLE_LINES = 0
        docwidthreset()

        if not graphicsconfigure(capabilities):
            raise RuntimeError('managed capability negotiation failed')

        graphicsbuildscene()
        started = time.monotonic_ns()
        samples = []
        scene = []

        for _ in range(25):

            sampleat = time.monotonic_ns()
            scene = graphicsbuildscene()
            samples.append((time.monotonic_ns() - sampleat) / 1000000.0)

        horizontalsamples = []

        for offset in range(0, 1200, 40):

            FIRST_VISIBLE_X = offset
            sampleat = time.monotonic_ns()
            graphicsbuildscene()
            horizontalsamples.append((time.monotonic_ns() - sampleat) / 1000000.0)

        FIRST_VISIBLE_X = 240
        scene = graphicsbuildscene()
        elapsed = (time.monotonic_ns() - started) / 1000000.0

        if not scene or scene[0].get('kind') != 'rectangle' or scene[0].get('rect') != [0, 0, WIN_W, WIN_H]:
            raise RuntimeError('managed scene does not begin with the complete opaque background')

        kinds = set(str(command.get('kind', '')) for command in scene)

        if not kinds or not kinds.issubset({'rectangle', 'text'}):
            raise RuntimeError(f'managed scene contains unexpected commands {sorted(kinds)}')

        textcommands = [command for command in scene if command.get('kind') == 'text']
        rectanglecommands = [command for command in scene if command.get('kind') == 'rectangle']

        if not textcommands or any(command.get('font') != FONT_PATH for command in textcommands):
            raise RuntimeError('managed text does not consistently use Atkinson Hyperlegible Next')

        if any(len(str(command.get('text', ''))) > int(capabilities['text_limit']) for command in textcommands):
            raise RuntimeError('managed text command exceeded the advertised text limit')

        viewport = list(viewportgeometry())
        cpuvisible, cpuvisiblex, _ = visiblelineslice(
            0,
            longline,
            MARGIN_LEFT - FIRST_VISIBLE_X,
            viewport[0],
            viewport[2],
            fully_visible=True,
        )

        if not cpuvisible or cpuvisiblex < viewport[0]:
            raise RuntimeError('CPU horizontal clipping allowed a glyph into the left gutter')

        redrawdamage = viewportredrawdamage(horizontal=True, vertical=True)
        expecteddocumentdamage = [0, viewport[1], viewport[0] + viewport[2], viewport[3]]
        expectedhtrack = list(hscrolltrackgeometry())
        expectedvtrack = list(scrollbartrackgeometry())

        if not redrawdamage or redrawdamage[0] != expecteddocumentdamage:
            raise RuntimeError(f'viewport damage did not clear the left gutter {redrawdamage}')

        if expectedhtrack not in redrawdamage or expectedvtrack not in redrawdamage:
            raise RuntimeError(f'viewport damage omitted a scrollbar track {redrawdamage}')

        documenttext = [
            command for command in textcommands
            if str(command.get('id', '')).startswith((
                "write:text:('document',",
                "write:text:('selection-",
            ))
        ]

        if not documenttext or any(int(command.get('x', -1)) < 0 for command in documenttext):
            raise RuntimeError('variable-width document clipping produced invalid text coordinates')

        if any(longline == str(command.get('text', '')) for command in documenttext):
            raise RuntimeError('the complete horizontally-scrolled line was submitted instead of its visible span')

        if not any(command.get('color') == SELBACKGROUND for command in rectanglecommands):
            raise RuntimeError('selection background was not represented in the managed scene')

        if not any(command.get('color') == 0xFFFFFF for command in textcommands):
            raise RuntimeError('selected text was not inverted in the managed scene')

        if not any(command.get('rect', [0, 0, 0, 0])[2] == CURSOR_WIDTH and command.get('rect', [0, 0, 0, 0])[3] == LINE_HEIGHT for command in rectanglecommands):
            raise RuntimeError('managed caret geometry was not emitted')

        CURSOR_VISIBLE = False
        hiddenscene = graphicsbuildscene()
        hiddenrectangles = [command for command in hiddenscene if command.get('kind') == 'rectangle']

        if any(command.get('rect', [0, 0, 0, 0])[2] == CURSOR_WIDTH and command.get('rect', [0, 0, 0, 0])[3] == LINE_HEIGHT for command in hiddenrectangles):
            raise RuntimeError('managed caret remained in the scene while hidden')

        CURSOR_VISIBLE = True

        if not any('managed write.txt' in str(command.get('text', '')) for command in textcommands):
            raise RuntimeError('managed status bar text was not emitted')

        INPUT_MODE = 'save_path'
        PROMPT_TEXT = 'save as '
        PROMPT_BUFFER = '/1/master/document.txt'
        promptscene = graphicsbuildscene()

        if not any('/1/master/document.txt' in str(command.get('text', '')) for command in promptscene if command.get('kind') == 'text'):
            raise RuntimeError('managed path prompt text was not emitted')

        INPUT_MODE = 'edit'
        PROMPT_TEXT = ''
        PROMPT_BUFFER = ''

        if MENU_PANEL is None:
            raise RuntimeError('managed menu panel geometry was not calculated')

        panelx, panely, panelwidth, panelheight, _ = MENU_PANEL
        expectedmenuborders = [
            [panelx, panely, panelwidth, 1],
            [panelx, panely + panelheight - 1, panelwidth, 1],
            [panelx, panely + 1, 1, panelheight - 2],
            [panelx + panelwidth - 1, panely + 1, 1, panelheight - 2],
        ]
        menuborders = [
            list(command.get('rect', []))
            for command in rectanglecommands
            if (
                command.get('color') == MENU_BORDER
                and list(command.get('clip', []))
                == [panelx, panely, panelwidth, panelheight]
                and list(command.get('rect', [])) in expectedmenuborders
            )
        ]

        if menuborders != expectedmenuborders:
            raise RuntimeError(
                f'managed menu border differs from its four edges '
                f'{menuborders} != {expectedmenuborders}')

        menuitems = menudefinitions()['file']
        menuhovery = panely + MENU_PAD_Y + (1 * MENU_ITEM_H)

        if not any(
            command.get('rect') == [panelx + 1, menuhovery, max(1, panelwidth - 2), MENU_ITEM_H]
            and command.get('color') == MENU_HOVER_BG
            for command in rectanglecommands
        ):
            raise RuntimeError('menu hover treatment was not emitted')

        for index in range(len(menuitems) - 1):
            expectedseparator = [panelx, panely + MENU_PAD_Y + ((index + 1) * MENU_ITEM_H) - 1, panelwidth, 1]

            if not any(
                command.get('rect') == expectedseparator and command.get('color') == MENU_BORDER
                for command in rectanglecommands
            ):
                raise RuntimeError('menu row separator was not emitted')

        closemenu()
        CONTEXT_MENU_OPEN = True
        CONTEXT_MENU_X = WIN_W - 1
        CONTEXT_MENU_Y = WIN_H - 1
        CONTEXT_PASTE_AVAILABLE = False
        CONTEXT_MENU_HOVER_ACTION = 'edit_copy'
        contextpanel = computecontextpanel()

        if contextpanel is None:
            raise RuntimeError('context menu panel geometry was not calculated')

        contextx, contexty, contextwidth, contextheight = contextpanel
        viewportx, viewporty, viewportwidth, viewportheight = viewportgeometry()

        if contextheight != len(contextmenudefinitions()) * MENU_ITEM_H:
            raise RuntimeError('context menu retained top or bottom padding')

        topaction, topinside = contextmenuhit(contextx + MENU_PAD_X, contexty)
        bottomaction, bottominside = contextmenuhit(contextx + MENU_PAD_X, contexty + contextheight - 1)

        if not topinside or topaction != 'edit_undo' or not bottominside or bottomaction != 'edit_selectall':
            raise RuntimeError('context menu edge pixels were not included in item hit areas')

        if (
            contextx < viewportx
            or contexty < viewporty
            or contextx + contextwidth > viewportx + viewportwidth
            or contexty + contextheight > viewporty + viewportheight
        ):
            raise RuntimeError('context menu was not clamped inside the document viewport')

        contextscene = graphicsbuildscene()
        contextrectangles = [command for command in contextscene if command.get('kind') == 'rectangle']
        expectedhovery = contexty + (3 * MENU_ITEM_H)

        if not any(
            command.get('rect') == [contextx + 1, expectedhovery, max(1, contextwidth - 2), MENU_ITEM_H]
            and command.get('color') == MENU_HOVER_BG
            for command in contextrectangles
        ):
            raise RuntimeError('context menu hover treatment was not emitted')

        for index in range(len(contextmenudefinitions()) - 1):
            expectedseparator = [contextx, contexty + ((index + 1) * MENU_ITEM_H) - 1, contextwidth, 1]

            if not any(
                command.get('rect') == expectedseparator and command.get('color') == MENU_BORDER
                for command in contextrectangles
            ):
                raise RuntimeError('context menu row separator was not emitted')

        contexttext = [
            command for command in contextscene
            if command.get('kind') == 'text'
            and str(command.get('id', '')).startswith("write:text:('context',")
        ]
        contextlabels = {str(command.get('text', '')) for command in contexttext}
        expectedcontextlabels = {'undo', 'redo', 'cut', 'copy', 'paste', 'delete', 'select all'}

        if not expectedcontextlabels.issubset(contextlabels):
            raise RuntimeError(f'context menu is missing expected actions {sorted(expectedcontextlabels - contextlabels)}')

        if any(command.get('color') != MENU_TEXT for command in contexttext):
            raise RuntimeError('context menu text did not match the main menu text colour')

        copyy = contexty + CONTEXT_MENU_PAD_Y + (3 * MENU_ITEM_H) + (MENU_ITEM_H // 2)
        contextaction, insidecontext = contextmenuhit(contextx + MENU_PAD_X, copyy)

        if not insidecontext or contextaction != 'edit_copy' or not contextactionenabled(contextaction):
            raise RuntimeError('context menu did not route the enabled copy action')

        outsideaction, outsidecontext = contextmenuhit(contextx - 1, contexty - 1)

        if outsidecontext or outsideaction is not None:
            raise RuntimeError('context menu treated an outside click as an action')

        if not positioninselection(0, 35) or positioninselection(0, 10):
            raise RuntimeError('right-click selection preservation bounds are incorrect')

        if not iscontextpointerbutton(2) or iscontextpointerbutton(1):
            raise RuntimeError('windowserver right-click button mapping is incorrect')

        closecontextmenu()
        MENUBAR_OPEN = 'file'
        MENU_HOVER_ACTION = 'file_open'
        computemenupanel(MENUBAR_OPEN)

        if not any(command.get('color') == SCROLLBAR_THUMB_COLOR for command in rectanglecommands):
            raise RuntimeError('managed scrollbar thumb was not emitted')

        trackx, tracky, trackwidth, trackheight = scrollbartrackgeometry()
        thumbx, thumby, thumbwidth, thumbheight = scrollbarthumbgeometry()

        def expectedborder(x, y, width, height):

            edges = [[int(x), int(y), int(width), 1]]

            if height > 1:
                edges.append([int(x), int(y + height - 1), int(width), 1])

            if height > 2:
                edges.append([int(x), int(y + 1), 1, int(height - 2)])

                if width > 1:
                    edges.append([int(x + width - 1), int(y + 1), 1, int(height - 2)])

            return edges

        expectedtrack = expectedborder(trackx, tracky, trackwidth, trackheight)
        expectedthumb = expectedborder(thumbx, thumby, thumbwidth, thumbheight)
        opaquetrack = [
            command for command in rectanglecommands
            if command.get('color') == BG_COLOR and list(command.get('rect', [])) == [trackx, tracky, trackwidth, trackheight]
        ]
        trackcommands = [
            list(command.get('rect', [])) for command in rectanglecommands
            if command.get('color') == SCROLLBAR_BG_COLOR and list(command.get('rect', [])) in expectedtrack
        ]
        thumbcommands = [
            list(command.get('rect', [])) for command in rectanglecommands
            if command.get('color') == SCROLLBAR_THUMB_COLOR and list(command.get('rect', [])) in expectedthumb
        ]

        if trackcommands != expectedtrack:
            raise RuntimeError(f'managed vertical scrollbar track differs from CPU geometry {trackcommands} != {expectedtrack}')

        if thumbcommands != expectedthumb:
            raise RuntimeError(f'managed vertical scrollbar thumb differs from CPU geometry {thumbcommands} != {expectedthumb}')

        if len(opaquetrack) != 1:
            raise RuntimeError('managed vertical scrollbar does not mask underlying document pixels')

        statusx, statusy, statuswidth, statusheight = statusbargeometry()
        statusbackground = next((
            command for command in rectanglecommands
            if command.get('color') == (240, 240, 240) and list(command.get('rect', [])) == [statusx, statusy, statuswidth, statusheight]
        ), None)

        if viewport[0] + viewport[2] > trackx or viewport[1] + viewport[3] > statusy:
            raise RuntimeError('document viewport overlaps the vertical scrollbar or status bar')

        if trackx + trackwidth != WIN_W or viewport[0] + viewport[2] != trackx:
            raise RuntimeError('vertical scrollbar does not occupy the complete right edge')

        if statusbackground is None or scene.index(opaquetrack[0]) <= scene.index(statusbackground):
            raise RuntimeError('status bar is not layered beneath the vertical scrollbar')

        menuy = max(0, (MENUBAR_HEIGHT - FONT_SIZE) // 2)
        filecommand = next((command for command in textcommands if command.get('text') == 'file'), None)

        if filecommand is None or int(filecommand.get('y', -1)) != graphicstexty(menuy, FONT_PATH):
            raise RuntimeError('managed Atkinson baseline does not match the CPU text baseline')

        requests = []
        managedmarkdamage(GRAPHICSSTATE, [10, 20, 60, 40], bounds=(WIN_W, WIN_H))
        managedmarkdamage(GRAPHICSSTATE, [40, 40, 80, 40], bounds=(WIN_W, WIN_H))

        if len(GRAPHICSSTATE.get('damage', [])) != 1:
            raise RuntimeError('overlapping managed damage rectangles were not coalesced')

        managedsubmit(GRAPHICSSTATE, lambda request: requests.append(request) or True, 99, scene)

        if len(requests) != 1 or requests[0].get('op') != 'GRAPHICS_SCENE' or len(requests[0].get('commands', [])) != len(scene):
            raise RuntimeError('Write did not submit one complete atomic scene')

        if len(requests[0].get('damage', [])) != 1:
            raise RuntimeError('atomic scene did not carry the coalesced damage region')

        managedresponse(GRAPHICSSTATE, {
            'op': 'GRAPHICS_COMMITTED',
            'winid': 99,
            'count': len(scene),
            'batch': True,
            'generation': int(GRAPHICSSTATE.get('pending_generation', 0)),
            'accelerated': True,
            'managed_only': True,
        })

        if not GRAPHICSSTATE.get('active') or GRAPHICSSTATE.get('pending'):
            raise RuntimeError('atomic scene acknowledgement did not activate managed rendering')

        oldcursor = cursorbox(CUR_ROW, CUR_COL)
        CUR_COL += 1
        newcursor = cursorbox(CUR_ROW, CUR_COL)

        if oldcursor is not None:
            managedmarkdamage(GRAPHICSSTATE, oldcursor, bounds=(WIN_W, WIN_H))

        if newcursor is not None:
            managedmarkdamage(GRAPHICSSTATE, newcursor, bounds=(WIN_W, WIN_H))

        patchscene = graphicsbuildscene()
        managedsubmit(GRAPHICSSTATE, lambda request: requests.append(request) or True, 99, patchscene)

        if len(requests) != 2 or requests[1].get('op') != 'GRAPHICS_PATCH':
            raise RuntimeError('Write did not use a retained scene patch for cursor movement')

        if len(requests[1].get('upsert', [])) > 2 or len(requests[1].get('remove', [])) > 2:
            raise RuntimeError(
                'cursor movement replaced unrelated retained scene nodes '
                f'upsert={len(requests[1].get("upsert", []))} '
                f'remove={requests[1].get("remove", [])}')

        managedresponse(GRAPHICSSTATE, {
            'op': 'GRAPHICS_COMMITTED',
            'winid': 99,
            'count': len(patchscene),
            'batch': True,
            'patch': True,
            'generation': int(GRAPHICSSTATE.get('pending_generation', 0)),
            'accelerated': True,
            'managed_only': True,
        })

        FIRST_VISIBLE_X = 0
        pasted = '\n'.join(
            '' if row % 5 in (1, 3) else f'pasted diagnostic line {row}'
            for row in range(80)
        )
        editreplace(CUR_ROW, CUR_COL, CUR_ROW, CUR_COL, pasted)
        ensurecursorvisible()
        graphicsrequestscenerebuild()

        if not graphicspreparescenerebuild():
            raise RuntimeError('multiline paste did not request a complete managed-scene rebuild')

        if list(redrawrowspan(0, 2)) != [0, 1, 2]:
            raise RuntimeError('cursor repaint did not preserve rows between the old and new caret')

        pastescene = graphicsbuildscene()
        managedsubmit(GRAPHICSSTATE, lambda request: requests.append(request) or True, 99, pastescene)

        if len(requests) != 3 or requests[2].get('op') != 'GRAPHICS_SCENE':
            raise RuntimeError('multiline paste was submitted as a retained patch instead of a complete scene')

        if requests[2].get('damage') != [[0, 0, WIN_W, WIN_H]]:
            raise RuntimeError('multiline paste scene did not request a complete repaint')

        pastedocument = [
            command for command in requests[2].get('commands', [])
            if command.get('kind') == 'text'
            and str(command.get('id', '')).startswith("write:text:('document',")
        ]
        visiblepasterows = range(FIRST_VISIBLE_ROW, FIRST_VISIBLE_ROW + VISIBLE_LINES)
        expectedpasterows = sum(
            1 for row in visiblepasterows
            if 0 <= row < len(DOC_LINES) and str(DOC_LINES[row])
        )

        if len(pastedocument) != expectedpasterows:
            raise RuntimeError(f'multiline paste painted {len(pastedocument)}/{expectedpasterows} non-blank visible rows')

        pasteclips = {tuple(command.get('clip', [])) for command in pastedocument}

        if len(pasteclips) != len(pastedocument):
            raise RuntimeError('multiline paste batched text across blank document rows')

        managedresponse(GRAPHICSSTATE, {
            'op': 'GRAPHICS_COMMITTED',
            'winid': 99,
            'count': len(pastescene),
            'batch': True,
            'generation': int(GRAPHICSSTATE.get('pending_generation', 0)),
            'accelerated': True,
            'managed_only': True,
        })

        cpustate = managedstate(cpu=True)

        if managedconfigure(cpustate, capabilities, required=('rectangle', 'text'), cpu=True):
            raise RuntimeError('CPU override unexpectedly enabled managed rendering')

        errorstate = managedstate()
        managedconfigure(errorstate, capabilities, required=('rectangle', 'text'))
        managedresponse(errorstate, {'op': 'ERROR', 'code': 'graphics_scene_failed', 'detail': 'diagnostic'})

        if (
            not errorstate.get('available')
            or not errorstate.get('active')
            or not errorstate.get('managed_only')
            or not errorstate.get('need_submit')
        ):
            raise RuntimeError('managed graphics error escaped strict GPU rendering')

        timeoutstate = managedstate()
        managedconfigure(timeoutstate, capabilities, required=('rectangle', 'text'))
        timeoutstate['pending'] = True
        timeoutstate['pending_at'] = time.monotonic() - 3.0

        if (
            not managedtick(timeoutstate, timeout=2.0)
            or not timeoutstate.get('active')
            or not timeoutstate.get('managed_only')
            or not timeoutstate.get('need_submit')
        ):
            raise RuntimeError('managed graphics timeout escaped strict GPU rendering')

        result['checks'] = {
            'capability_negotiation': True,
            'cpu_fallback': True,
            'error_gpu_retention': True,
            'timeout_gpu_retention': True,
            'opaque_background': True,
            'rectangle_text_only': sorted(kinds),
            'atkinson_baseline': True,
            'variable_width_clipping': True,
            'cpu_left_gutter_clipping': {
                'first_text_x': int(cpuvisiblex),
                'viewport_x': int(viewport[0]),
            },
            'viewport_scroll_damage': redrawdamage,
            'selection_cursor_scrollbars': True,
            'vertical_scrollbar_geometry': {
                'track': expectedtrack,
                'thumb': expectedthumb,
                'opaque': len(opaquetrack),
            },
            'document_viewport_reserved_ui': True,
            'right_edge_scrollbar': True,
            'status_beneath_scrollbar': True,
            'cursor_visibility': True,
            'status_path_prompt': True,
            'outlined_menu': len(menuborders),
            'context_menu': {
                'actions': sorted(expectedcontextlabels),
                'panel': list(contextpanel),
                'viewport_clamped': True,
                'disabled_actions': True,
                'selection_preserved': True,
                'right_button': 2,
                'copy_dispatch': contextaction,
            },
            'damage_coalescing': len(requests[0].get('damage', [])),
            'atomic_scene': {
                'messages': 1,
                'commands': len(scene),
                'damage': len(requests[0].get('damage', [])),
            },
            'retained_cursor_patch': {
                'upsert': len(requests[1].get('upsert', [])),
                'remove': len(requests[1].get('remove', [])),
            },
            'multiline_paste_repaint': {
                'request': requests[2].get('op'),
                'damage': requests[2].get('damage'),
                'visible_rows': len(pastedocument),
                'cursor_rows': list(redrawrowspan(0, 2)),
            },
            'command_budget': {
                'commands': len(scene),
                'limit': int(capabilities['command_limit']),
            },
        }
        result['performance'] = {
            'average_scene_build_ms': round(sum(samples) / max(1, len(samples)), 3),
            'maximum_scene_build_ms': round(max(samples) if samples else elapsed, 3),
            'average_horizontal_scene_build_ms': round(sum(horizontalsamples) / max(1, len(horizontalsamples)), 3),
            'maximum_horizontal_scene_build_ms': round(max(horizontalsamples) if horizontalsamples else elapsed, 3),
            'maximum_commands': len(scene),
            'visible_lines': int(VISIBLE_LINES),
            'window': [int(WIN_W), int(WIN_H)],
        }
        result['passed'] = True

    except Exception as e:
        result['errors'].append(str(e))

    print(json.dumps(result, separators=(',', ':'), sort_keys=True))
    return bool(result['passed'])


def main():

    global ws_sock

    logmsg('write starting')

    try:

        # initialise application
        initapp()

        # only enter loop if app is running
        if not APP_RUNNING:
            return

        # run main loop
        mainloop()

    except Exception as e:

        # unexpected top-level error
        logmsg(f'> fatal error in write {e}')

    finally:


        # close window server socket if open
        if ws_sock is not None:
            ws_sock.close()

    return


if __name__ == '__main__':

    if len(sys.argv) > 1 and str(sys.argv[1]).strip().lower() == 'performance-diagnostic':
        sys.exit(0 if writeperformancediagnostic() else 1)

    if len(sys.argv) > 1 and str(sys.argv[1]).strip().lower() == 'graphics-diagnostic':
        sys.exit(0 if writegraphicsdiagnostic() else 1)

    main()
