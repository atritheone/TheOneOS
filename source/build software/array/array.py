#!"/the one/software/python/bin/python" -B

"""
array.py

array is the file explorer of The One OS.
"""



## imports
import os
import sys
import time
import math
import json
import socket
import shutil
import selectors
import re
import stat
import queue
import zipfile
import mimetypes
import threading
import fnmatch
import shlex
from bisect import bisect_right

# build path
sys.path.insert(0, '/the one/build')

# t1os modules
import graphics.graphics as gfx
from GODDESS.GODDESS import formatlog
import architect.architect as arch
from exchange.exchange import exmeta, exget, exclear, exset, exsetfiles
from rubbish.rubbish import storepaths, restorefromrubbishrid, emptyrubbish
from graphics.graphics import initbuffer, presentdirty as gfxpresentdirty, present as gfxpresent
from graphics.graphics import fillrectfast, drawrect, drawline, drawtextttf, measuretext, measurelineadvances, ttfbbox, initttffont
from graphics.graphics import managedstate, managedconfigure, manageddisable, managedstrict, managedmarkdamage, managedclear, managedtick, managedsubmit, managedresponse, uiscalefactor, displayuiscale
from media.capabilities import (
    AUDIO_EXTENSIONS as MEDIAAUDIOEXTENSIONS,
    VIDEO_EXTENSIONS as MEDIAVIDEOEXTENSIONS,
)
try:
    from viewer.viewer import supports as viewersupports

except Exception:
    viewersupports = None

## globals

# misc
LOGFILE = "/the one/logs/array.py.log"
ARRAYPATH = "/the one/build/array/array.py"
SESSIONIDENTITYFILE = "/the one/settings/session/identity.json"
SESSIONIDENTITYMAXBYTES = 1024
SESSIONUSERNAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,31}")
RUNNING = True
DEBUGARRAY = False

# window
APPNAME = "array"
APPROLE = "window"
WINID = None
BUF = None
WINW = 0
WINH = 0
sel = selectors.DefaultSelector()
WSOCK = None
INBUF = b""
OUTBUF = b""
BASEWINW = 960
BASEWINH = 640
NEEDWINDOW = True

# picker mode. Normal Array leaves PICKERSESSION unset and follows its existing
# explorer behaviour. Window Server supplies all picker configuration after a
# PID-bound session attachment.
PICKERSESSION = None
PICKERCONFIG = None
PICKERMODE = None
PICKERTITLE = ""
PICKERFILTERS = []
PICKERFILTERINDEX = 0
PICKERALLOWMULTIPLE = False
PICKERNAME = ""
PICKERNAMECARETPOS = 0
PICKERNAMEFOCUSED = False
PICKERNAMESELECTALL = False
PICKERNAMESELANCHOR = None
PICKERNAMEDRAGGING = False
PICKERDEFAULTEXTENSION = ""
PICKERTERMINAL = False
PICKEROVERWRITEPATH = None
PICKERMAP = {}
BASEPICKERSTATUSH = 62

# graphics
COLOURBG = 0x000000
COLOURTEXT = 0xEFEFEF
COLOURSTATUS = 0x242424
COLOURDIVIDER = 0x3A3A3A
COLOURROWOUTLINE = COLOURDIVIDER
COLOURHILITETEXT = 0x000000
COLOURMUTED = 0x6A6A6A
COLOURERROR = 0xFF0000
COLOURCONTEXTBG = COLOURBG
COLOURCONTEXTTEXT = COLOURTEXT
COLOURCONTEXTDIVIDER = COLOURROWOUTLINE
NEEDREDRAW = False
DIRTYRECT = None
SCREENW = 0
SCREENH = 0

# managed graphics
GRAPHICSSCENE = []
GRAPHICSTEXTBASELINES = {}
GRAPHICSTEXTADVANCES = {}
GRAPHICSCPUOVERRIDE = str(os.environ.get("T1OS_ARRAY_GRAPHICS", "")).strip().lower() in ("cpu", "off", "0", "false")
GRAPHICSSTATE = managedstate(cpu=GRAPHICSCPUOVERRIDE)

# text
FONT = "/the one/resources/fonts/atkinsonhyperlegiblenext.ttf"
BASESCREENW = 1920
BASESCREENH = 1080
UISCALE = 1.0
BASEFONTSIZEHEADER = 23
BASEFONTSIZEROW = 14
BASEFONTSIZESTATUS = 12
BASECONFIRMFONTSIZE = 17
FONTSIZEHEADER = BASEFONTSIZEHEADER
FONTSIZEROW = BASEFONTSIZEROW
FONTSIZESTATUS = BASEFONTSIZESTATUS
CONFIRMFONTSIZE = BASECONFIRMFONTSIZE

# layout
BASEPAD = 8
BASEROWH = 24
BASETITLEH = 26
BASESTATUSH = 26
BASESIDEBARW = 180
BASEDIVW = 1
BASETREEINDENT = 18
BASEARROWW = 18
BASEHEADERGAP = 25
BASETOOLBARH = 34
BASEDETAILHEADERH = 24
BASEPROPERTIESW = 280
PAD = BASEPAD
ROWH = BASEROWH
TITLEH = BASETITLEH
STATUSH = BASESTATUSH
SIDEBARW = BASESIDEBARW
DIVW = BASEDIVW
TREEINDENT = BASETREEINDENT
ARROWW = BASEARROWW
SCROLLSTEP = 3
HEADERGAP = BASEHEADERGAP
HEADERH = TITLEH + (HEADERGAP * 2)
TOOLBARH = BASETOOLBARH
EXPLORERTOP = HEADERH + TOOLBARH
DETAILHEADERH = BASEDETAILHEADERH
PROPERTIESW = BASEPROPERTIESW
CONTENTTOP = EXPLORERTOP
SELECTINDEX = 0

# filesystem
CWD = "/"
LAUNCHCWD = None
LAUNCHOPENITEM = None
LAUNCHCONTEXTACTION = None
LAUNCHCONTEXTITEM = None
LAUNCHSEARCHTEXT = None
LAUNCHSEARCHSESSION = None
DRIVENUMBER = 1
SHOWHIDDEN = False
HIDDENFILE = "/the one/settings/array/hidden.txt"
SETTINGSFILE = "/the one/settings/array/settings.json"
SETTINGSVERSION = 4
SETTINGS = {}
SIDEBARLINKS = []
TREE = []
EXPANDED = set()
SELECTED = None
SELECTEDMS = 0
SELECTEDSET = set()
SELECTANCHOR = None
HOVERED = None
HEADERMAP = {}

# Numeric drive locations are public (for example, 2/); their Linux mount
# targets are private implementation details beneath the ephemeral runtime.
DRIVES = {}
DRIVEASSIGNMENTS = {}
DRIVELASTSCAN = 0.0
DRIVESCANINTERVAL = 2.0
DRIVEBACKINGROOT = "/.ephemeral/volumes"
DRIVEMETADATAFILE = "/.ephemeral/drivers/volumes.json"
LEGACYDRIVEROOTS = ("/drives", "/volumes")
DRIVESCANROOTS = (DRIVEBACKINGROOT,)
DRIVEPSEUDOPREFIXES = (
    "/the one/drivers/processes", "/the one/drivers/state",
    "/the one/drivers/nodes", "/.ephemeral", "/the one/software/python",
)
ARRAYLSMFORBIDDENROOTS = tuple(
    f"/{name}"
    for name in (
        "bin", "sbin", "lib", "lib64", "usr", "etc",
        "dev", "proc", "sys", "run", "var", "tmp",
        "home", "root", "media", "mnt", "opt", "srv",
    )
)
ARRAYLSMMASTERDENIED = (
    "/the one/settings/operations",
    "/the one/settings/windowserver",
    "/the one/drivers",
)
LINKFILEHEADER = b"T1OS link\n"
LINKFILEVERSION = 1
LINKFILEMAXBYTES = 16384
LINKFILEMAXHOPS = 16

# sidebar
SIDBARENTRIES = []
SIDEBARSELECTED = None
SIDEBARSELECTEDDRIVE = None
SIDEBARHOVERINDEX = None
SIDEBARDRAGGING = False
SIDEBARDRAGINDEX = None
SIDEBARDROPINDEX = None
SIDEBARDRAGSTART = None
SIDEBARDRIVEGAPROWS = 2

# view and metadata
VIEWMODE = "tier"
SORTKEY = "name"
SORTDESC = False
FOLDERSFIRST = True
SHOWEXTENSIONS = True
SHOWITEMCHECKS = False
PROPERTIESPANE = False
DETAILCOLUMNS = ["name", "modified", "type", "size"]
COLUMNWIDTHS = {"name": 360, "modified": 150, "type": 110, "size": 90}
COLUMNMAP = {}
COLUMNRESIZING = None
COLUMNRESIZESTARTX = 0
COLUMNRESIZESTARTW = 0
COLUMNCURSORMODE = "arrow"
ITEMCACHE = {}
TYPESELECTTEXT = ""
TYPESELECTUNTIL = 0
TOPBARMAP = {}
SCENECAPTURECOMMANDS = None

# filesystem watching
WATCHSNAPSHOT = {}
WATCHLASTSCAN = 0.0
WATCHINTERVAL = 0.75
WATCHDIRTYAT = 0.0
WATCHDEBOUNCE = 0.15

# actions
RENAMEEDIT = False
RENAMETEXT = ""
RENAMECARETPOS = 0
RENAMESELANCHOR = None
RENAMEUNDO = []
RENAMEREDO = []
RENAMEHISTLIMIT = 50
RENAMEDRAGGING = False
RENAMEPATH = None
RENAMEORIGINAL = ""
RENAMESKIPNEXTCLICK = True
RENAMEBLINKMS = 530
RENAMELASTBLINK = False

# scrolling
SCROLL = 0
HSCROLL = 0
PENDINGSCROLL = 0
LASTSCROLLFRAME = 0.0
SCROLLMANAGEDINTERVAL = 1.0 / 60.0
SCROLLCPUINTERVAL = 1.0 / 12.0
SMOOTHSCROLLEASING = 0.25
SMOOTHSCROLLMAXSTEP = 6
VISIBLECOUNT = 0
VISIBLEWIDTH = 0
MAXDEPTH = 0
CONTENTWIDTH = 0
BASEVSCROLL_WIDTH = 12
BASEVSCROLL_MARGIN = 2
BASEVSCROLL_MIN_THUMB = 20
VSCROLL_WIDTH = BASEVSCROLL_WIDTH
VSCROLL_MARGIN = BASEVSCROLL_MARGIN
VSCROLL_MIN_THUMB = BASEVSCROLL_MIN_THUMB
VSCROLLDRAGGING = False
VSCROLL_DRAG_CURSOR_OFFSET = 0
BASEHSCROLL_HEIGHT = 12
HSCROLL_HEIGHT = BASEHSCROLL_HEIGHT
HSCROLL_MIN_THUMB = 20
HSCROLLDRAGGING = False
HSCROLL_DRAG_CURSOR_OFFSET = 0

# header
HEADEREDIT = False
HEADEREDITTEXT = ""
HEADERCARETPOS = 0
HEADERSELSTART = None
HEADERSELEND = None
HEADERLASTCLICK = {
    "t": 0,
    "count": 0,
    "button": 0
}
HEADERBLINKMS = 530
CARETOFFSETY = -2
HEADERHELD = None
HEADERHELDDOWNMS = 0
HEADERHELDLASTMS = 0
HEADERREPEATDELAYMS = 350
HEADERREPEATMS = 45
HEADERHELDKIND = None
HEADERLASTTEXT = ""
HEADERLASTBLINK = False

# navigation
NAVHIST = []
NAVPOS = -1

# click tracking
LASTCLICK = {
    "path": None,
    "t": 0.0,
    "button": 0
}
DBLCLICKMS = 530
PENDINGRENAMEPATH = None
PENDINGRENAMEAT = 0
RENAMECLICKDELAYMS = DBLCLICKMS + 100

# status bar
ACTIONS = []
ACTIONMAP = {}
ACTIONVIS = {}
STATUSXSTART = PAD + 14
STATUSMESSAGE = ""
STATUSMESSAGEERROR = False
STATUSMESSAGEUNTIL = 0
STATUSMESSAGEDURATION = 2500
ACTIONSLOTS = [
    {"id": "open", "label": "open"},
    {"id": "new", "label": "new"},
    {"id": "copy", "label": "copy"},
    {"id": "cut", "label": "cut"},
    {"id": "paste", "label": "paste"},
    {"id": "delete", "label": "delete"},
    {"id": "rename", "label": "rename"},
    {"id": "run", "label": "run"},
    {"id": "reveal", "label": "reveal"},
    {"id": "undo", "label": "undo"},
    {"id": "redo", "label": "redo"},
    {"id": "empty", "label": "empty"},
    {"id": "restore", "label": "restore"},
]
CLIPBOARDHAS = False
CUTSET = set()
UNDO = []
REDO = []
UNDOLIMIT = 50
STATUSMENUOPEN = False
STATUSMENUKIND = None
STATUSMENU_PANEL = None
STATUSMENU_RECTS = {}
BASESTATUSMENU_PAD_X = 10
BASESTATUSMENU_PAD_Y = 6
BASESTATUSMENU_ITEM_H = 22
CONTEXTMENU_PAD_Y = 0
STATUSMENU_PAD_X = BASESTATUSMENU_PAD_X
STATUSMENU_PAD_Y = BASESTATUSMENU_PAD_Y
STATUSMENU_ITEM_H = BASESTATUSMENU_ITEM_H

# background file jobs
JOBQUEUE = queue.Queue()
JOBEVENTS = queue.Queue()
JOBTHREAD = None
JOBSTOP = threading.Event()
JOBS = {}
ACTIVEJOB = None
JOBSEQ = 0
JOBCONFLICTDEFAULT = "keepboth"

# integrated search
SEARCHOPEN = False
SEARCHFOCUSED = False
SEARCHTEXT = ""
SEARCHCARETPOS = 0
SEARCHRESULTS = []
SEARCHRUNNING = False
SEARCHGENERATION = 0
SEARCHQUEUE = queue.Queue()
SEARCHEVENTS = queue.Queue()
SEARCHTHREAD = None
SEARCHSCOPE = "tier"
SEARCHERROR = ""
SEARCHCARETSTART = time.monotonic()
SEARCHCARETSTATE = None
SEARCHSESSIONPATH = None
SEARCHSESSIONSTAMP = None
SEARCHSESSIONQUERY = ""
SEARCHSESSIONROOT = "/.ephemeral/expanse/search-handoffs"

# properties and input dialogs
PROPERTIESOPEN = False
PROPERTIESDATA = []
PROPERTIESSCROLL = 0
PROPERTIESPATH = None
PROPERTIESISDIR = False
PROPERTIESMODE = None
PROPERTIESHIDDEN = False
PROPERTIESDROPDOWN = False
PROPERTIESDROPDOWNHOVER = None
PROPERTIESCONTROLS = {}
SIDEPROPERTIESPATH = None
SIDEPROPERTIESDROPDOWN = False
SIDEPROPERTIESDROPDOWNHOVER = None
SIDEPROPERTIESCONTROLS = {}
INPUTOPEN = False
INPUTTITLE = ""
INPUTTEXT = ""
INPUTCARETPOS = 0
INPUTACTION = None
INPUTPAYLOAD = None

# internal item drag/drop
ITEMDRAGGING = False
ITEMDRAGSTART = None
ITEMDRAGPATHS = []
ITEMDRAGTARGET = None
ITEMDRAGMODS = {}
ITEMDRAGSTARTED = False
EXTERNALDRAGTARGET = None

# operations
OPERATIONSSOCKET = "/.ephemeral/operations/control.sock"
WRITEPROG = "/the one/build/write/write.py"
PLAYERPROG = "/the one/build/player/player.py"
BRICKPROG = "/the one/build/brick/brick.py"
VIEWERPROG = "/the one/build/viewer/viewer.py"
AUDIOEXTENSIONS = MEDIAAUDIOEXTENSIONS
VIDEOEXTENSIONS = MEDIAVIDEOEXTENSIONS

# context menu
CONTEXTMENUOPEN = False
CONTEXTMENUKIND = None
CONTEXTMENU_ANCHOR = None
CONTEXTMENU_PANEL = None
CONTEXTMENU_RECTS = {}
CONTEXTMENUTARGET = None
CONTEXTMENUHOVERACTION = None
ACTIONFROMCONTEXT = False
ACTIONCONTEXTTARGET = None

# drag box
DRAGBOX = False
DRAGBOXSX = 0
DRAGBOXSY = 0
DRAGBOXEX = 0
DRAGBOXEY = 0
DRAGBOXADD = False
DRAGBOXBASESET = set()
DRAGBOXBASEFOCUS = None
DRAGBOXBASEANCHOR = None

# confirm dialog
CONFIRMOPEN = False
CONFIRMWAITING = False
CONFIRMDIALOGID = None
CONFIRMDIALOGWIN = None
CONFIRMACTION = None
CONFIRMPATHS = []
CONFIRMFOCUS = 0
CONFIRMRECTS = {}
CONFIRMORDER = []
CONFIRMPANEL = None
BASECONFIRMW = 420
BASECONFIRMH = 160
BASECONFIRMBTNW = 120
BASECONFIRMBTNH = 28
BASECONFIRMPAD = 14
BASECONFIRMGAP = 10
CONFIRMW = BASECONFIRMW
CONFIRMH = BASECONFIRMH
CONFIRMBTNW = BASECONFIRMBTNW
CONFIRMBTNH = BASECONFIRMBTNH
CONFIRMPAD = BASECONFIRMPAD
CONFIRMGAP = BASECONFIRMGAP

# server-owned standard text-entry dialog
TEXTDIALOGWAITING = False
TEXTDIALOGID = None
TEXTDIALOGWIN = None
TEXTDIALOGTITLE = ""
TEXTDIALOGINITIAL = ""
TEXTDIALOGACTION = None
TEXTDIALOGPAYLOAD = None



## functions

# misc functions
def log(msg):

    if not DEBUGARRAY:
        return

    try:

        os.makedirs(os.path.dirname(LOGFILE), exist_ok=True)

    except Exception:

        pass

    line = formatlog('array', msg) + '\n'

    with open(LOGFILE, "a") as f:

        f.write(line)

        f.flush()

        os.fsync(f.fileno())


def nowms():

    try:

        # get current time in milliseconds
        return int(time.time() * 1000)

    except Exception:

        # fallback zero
        return 0


def setstatus(message, error=False, duration=None):

    global STATUSMESSAGE, STATUSMESSAGEERROR, STATUSMESSAGEUNTIL

    try:

        STATUSMESSAGE = str(message)

    except Exception:

        STATUSMESSAGE = ""

    STATUSMESSAGEERROR = bool(error)

    try:

        timeout = STATUSMESSAGEDURATION if duration is None else int(duration)

        STATUSMESSAGEUNTIL = nowms() + max(0, timeout)

    except Exception:

        STATUSMESSAGEUNTIL = nowms() + STATUSMESSAGEDURATION

    try:

        invalidaterect(0, WINH - STATUSH, WINW, STATUSH)

    except Exception:

        pass


def clearstatus():

    global STATUSMESSAGE, STATUSMESSAGEERROR, STATUSMESSAGEUNTIL

    if STATUSMESSAGE == "":
        return

    STATUSMESSAGE = ""

    STATUSMESSAGEERROR = False

    STATUSMESSAGEUNTIL = 0

    try:

        invalidaterect(0, WINH - STATUSH, WINW, STATUSH)

    except Exception:

        pass


def statusactive():

    if STATUSMESSAGE == "":
        return False

    try:

        return nowms() < int(STATUSMESSAGEUNTIL)

    except Exception:

        return False


def permissiondenied():

    setstatus("permission denied", error=True)


def arraylsmmutationallowed(path):

    try:

        target = os.path.realpath(os.path.abspath(str(path)))

    except Exception:

        return False

    # The kernel enforces its runtime-layout invariant for both master and
    # architect. Match it here so Array reports the denial before a syscall.
    for root in ARRAYLSMFORBIDDENROOTS:

        if target == root or target.startswith(root + os.sep):
            return False

    try:

        if not arch.check(target):
            return False

    except Exception:

        return False

    # These paths have process-aware LSM write ACLs. Array is not one of their
    # authorised daemon owners. There is no ambient role bypass.
    for root in ARRAYLSMMASTERDENIED:

        if target == root or target.startswith(root + os.sep):
            return False

    return True


def permissionpaths(*paths):

    # Architect/LSM path rules govern mutation, not visibility. Callers must
    # pass only paths that their operation will create, replace, move, rename,
    # or delete; read-only inputs do not belong in this check.
    targets = []

    for path in paths:

        if path is None:
            continue

        if isinstance(path, (list, tuple, set)):

            for item in path:

                if item is not None:
                    targets.append(item)

            continue

        targets.append(path)

    if not targets:
        return True

    try:

        # The compatibility check is fail-closed; authority remains in kernel
        # domains and typed brokers rather than a mutable global role.
        arch.loadrole()

    except Exception as e:

        log(f"architect role refresh error {e}")
        permissiondenied()
        return False

    for path in targets:

        try:

            target = os.path.abspath(str(path))

        except Exception as e:

            log(f"architect path normalisation error {e}")
            permissiondenied()
            return False

        try:

            if not arraylsmmutationallowed(target):

                permissiondenied()
                return False

        except Exception as e:

            log(f"architect permission check error {target} {e}")
            permissiondenied()
            return False

    return True


def creationmutationpaths(path):

    if path is None:
        return []

    try:

        target = os.path.abspath(str(path))

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


def clamp(v, lo, hi):

    try:

        # clamp lower bound
        if v < lo:
            return lo

        # clamp upper bound
        if v > hi:
            return hi

        # within bounds
        return v

    except Exception:

        # fallback to lower bound
        return lo


def normalisepath(p):

    try:

        # ensure string
        path = str(p)

    except Exception:

        # invalid path input
        return "/"

    try:

        # empty becomes root
        if path == "":
            return "/"

        # replace double slashes
        while "//" in path:
            path = path.replace("//", "/")

        # ensure leading slash
        if not path.startswith("/"):
            path = "/" + path

        # remove trailing slashes except root
        while path.endswith("/") and len(path) > 1:
            path = path[:-1]

        return path

    except Exception:

        # path normalisation failure
        return "/"


def uniquepath(destdir, name, reserved=None):

    base = str(name)

    used = set(reserved or [])

    candidate = os.path.join(destdir, base)

    if not os.path.exists(candidate) and candidate not in used:
        return candidate

    root, ext = os.path.splitext(base)

    i = 1

    while True:

        if i == 1:

            alt = f"{root} copy{ext}"
        else:

            alt = f"{root} copy {i}{ext}"

        candidate = os.path.join(destdir, alt)

        if not os.path.exists(candidate) and candidate not in used:
            return candidate

        i += 1


def flushfilesystem(*paths):

    targets = []

    for path in paths:

        if path is None:
            continue

        if isinstance(path, (list, tuple, set)):

            for item in path:
                targets.append(item)

            continue

        targets.append(path)

    seen = set()

    for path in targets:

        try:

            p = os.path.abspath(str(path))

        except Exception:

            continue

        checks = []

        try:

            if os.path.exists(p) and not os.path.isdir(p):
                checks.append(p)

        except Exception:

            pass

        try:

            if os.path.isdir(p):
                checks.append(p)
            else:
                parent = os.path.dirname(p)

                if parent:
                    checks.append(parent)

        except Exception:

            pass

        for target in checks:

            if not target or target in seen:
                continue

            seen.add(target)

            try:

                if os.path.isdir(target):

                    flags = os.O_RDONLY

                    try:

                        flags = flags | os.O_DIRECTORY

                    except Exception:

                        pass

                    fd = os.open(target, flags)

                    try:
                        os.fsync(fd)
                    finally:
                        os.close(fd)

                elif os.path.exists(target):

                    with open(target, "rb") as f:
                        os.fsync(f.fileno())

            except Exception:

                pass

    try:

        if hasattr(os, "sync"):
            os.sync()

    except Exception:

        pass


def refreshclipboard():

    global CLIPBOARDHAS

    ok, meta = exmeta()

    if not ok:
        CLIPBOARDHAS = False
        return

    # array can only paste file payloads
    if str(meta.get("type")) != "files":
        CLIPBOARDHAS = False
        return

    # optional safety: must have data bytes
    try:
        if int(meta.get("bytes", 0)) <= 0:
            CLIPBOARDHAS = False
            return
    except Exception:
        CLIPBOARDHAS = False
        return

    CLIPBOARDHAS = True


# persistent explorer settings and numeric-drive locations
def defaultsettings():

    return {
        "version": SETTINGSVERSION,
        "sidebar": [],
        "drive_assignments": [],
        "drive_labels": {},
        "view_mode": "tier",
        "sort_key": "name",
        "sort_descending": False,
        "folders_first": True,
        "show_extensions": True,
        "show_item_checks": False,
        "properties_pane": False,
        "detail_columns": ["name", "modified", "type", "size"],
        "column_widths": {"name": 360, "modified": 150, "type": 110, "size": 90},
        "search_scope": "tier",
        "associations": {},
    }


def _physicalnormalize(path):

    try:
        value = os.path.abspath(os.path.normpath(str(path)))
    except Exception:
        value = "/"

    if not value:
        value = "/"

    return value.replace("\\", "/")


def arraylinktarget(path, fileinfo=None):

    """Return the target stored in an ordinary T1OS link file."""

    try:
        info = fileinfo if fileinfo is not None else os.lstat(path)
        if not stat.S_ISREG(info.st_mode):
            return None
        if info.st_size <= len(LINKFILEHEADER) or info.st_size > LINKFILEMAXBYTES:
            return None
        with open(path, "rb") as f:
            raw = f.read(LINKFILEMAXBYTES + 1)
        if len(raw) > LINKFILEMAXBYTES or not raw.startswith(LINKFILEHEADER):
            return None
        payload = json.loads(raw[len(LINKFILEHEADER):].decode("utf-8"))
        if not isinstance(payload, dict) or payload.get("version") != LINKFILEVERSION:
            return None
        target = payload.get("target")
        if not isinstance(target, str) or not target or "\x00" in target:
            return None
        return target
    except Exception:
        return None


def isarraylink(path, fileinfo=None):

    return arraylinktarget(path, fileinfo=fileinfo) is not None


def writearraylink(path, target):

    """Create a T1OS link as a regular file, never as a filesystem symlink."""

    destination = _physicalnormalize(path)
    linktarget = _physicalnormalize(target)
    payload = json.dumps(
        {"version": LINKFILEVERSION, "target": linktarget},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    data = LINKFILEHEADER + payload + b"\n"
    if len(data) > LINKFILEMAXBYTES:
        raise ValueError("link target is too long")

    with open(destination, "xb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())

    flushfilesystem(os.path.dirname(destination))


def resolvearraylink(path):

    """Resolve a chain of T1OS link files without relying on symlink support."""

    current = _physicalnormalize(path)
    seen = set()

    for _ in range(LINKFILEMAXHOPS):
        target = arraylinktarget(current)
        if target is None:
            return current, None

        key = _physicalnormalize(current)
        if key in seen:
            return None, "link target contains a loop"
        seen.add(key)

        if not os.path.isabs(target):
            target = os.path.join(os.path.dirname(current), target)
        current = _physicalnormalize(target)

    if arraylinktarget(current) is not None:
        return None, "link chain is too long"
    return current, None


def loadvolumemetadata():

    found = {}
    try:
        with open(DRIVEMETADATAFILE, "r", encoding="utf-8", errors="replace") as f:
            payload = json.load(f)
    except Exception:
        return found

    if not isinstance(payload, dict) or payload.get("format") != 1:
        return found

    for entry in payload.get("volumes", []):
        if not isinstance(entry, dict):
            continue
        root = _physicalnormalize(entry.get("root"))
        if root == "/" or not (
            root == DRIVEBACKINGROOT or root.startswith(DRIVEBACKINGROOT + "/")
        ):
            continue
        found[root] = {
            "label": str(entry.get("label") or "").strip(),
            "uuid": str(entry.get("uuid") or "").strip(),
            "filesystem": str(entry.get("filesystem") or "").strip(),
            "read_only": bool(entry.get("read_only", False)),
            "removable": bool(entry.get("removable", True)),
        }
    return found


def drivemountcandidate(source, mount):

    source = str(source or "")
    mount = _physicalnormalize(mount)

    if source.startswith("/the one/drivers/nodes/"):
        return True

    return any(mount == root or mount.startswith(root + "/") for root in DRIVESCANROOTS)


def migratedriveroot(root):

    value = _physicalnormalize(root)
    for legacy in LEGACYDRIVEROOTS:
        if value == legacy:
            return DRIVEBACKINGROOT
        if value.startswith(legacy + "/"):
            return DRIVEBACKINGROOT + value[len(legacy):]
    return value


def loaddrives(force=False):

    global DRIVES, DRIVELASTSCAN

    now = time.time()

    if not force and DRIVES and (now - DRIVELASTSCAN) < DRIVESCANINTERVAL:
        return False

    old = dict(DRIVES)
    labels = SETTINGS.get("drive_labels", {}) if isinstance(SETTINGS, dict) else {}
    if not isinstance(labels, dict):
        labels = {}
    mainlabel = str(labels.get("1") or "T1OS").strip() or "T1OS"
    found = {1: {"number": 1, "root": "/", "label": mainlabel, "removable": False}}
    usedroots = {"/"}
    metadata = loadvolumemetadata()

    assignments = SETTINGS.get("drive_assignments", []) if isinstance(SETTINGS, dict) else []

    if isinstance(assignments, list):
        for entry in assignments:
            try:
                number = int(entry.get("number"))
                root = migratedriveroot(entry.get("root"))
            except Exception:
                continue

            if number <= 1 or not os.path.isdir(root) or root in usedroots:
                continue

            found[number] = {
                "number": number,
                "root": root,
                "label": str(
                    labels.get(str(number))
                    or metadata.get(root, {}).get("label")
                    or entry.get("label")
                    or os.path.basename(root)
                    or f"drive {number}"
                ),
                "removable": bool(metadata.get(root, {}).get("removable", entry.get("removable", True))),
                "read_only": bool(metadata.get(root, {}).get("read_only", False)),
                "filesystem": str(metadata.get(root, {}).get("filesystem", "")),
            }
            usedroots.add(root)

    # Volume discovery is authoritative even when the backing tier is not
    # reported as a conventional mount by the runtime process view.
    candidates = list(metadata)

    try:
        with open("/the one/drivers/processes/self/mounts", "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                parts = line.split()
                if len(parts) < 2:
                    continue
                source = parts[0].replace("\\040", " ")
                mount = _physicalnormalize(parts[1].replace("\\040", " "))
                if mount == "/":
                    continue
                if any(mount == root or mount.startswith(root + "/") for root in DRIVESCANROOTS):
                    candidates.append(mount)
                    continue
                if mount.startswith(DRIVEPSEUDOPREFIXES):
                    continue
                if drivemountcandidate(source, mount):
                    candidates.append(mount)
    except Exception:
        pass

    for base in DRIVESCANROOTS:
        try:
            for name in os.listdir(base):
                mount = _physicalnormalize(os.path.join(base, name))
                if os.path.isdir(mount) and (os.path.ismount(mount) or mount in candidates):
                    candidates.append(mount)
        except Exception:
            pass

    number = 2
    for mount in sorted(set(candidates), key=lambda p: p.casefold()):
        if mount in usedroots:
            continue
        while number in found:
            number += 1
        found[number] = {
            "number": number,
            "root": mount,
            "label": str(
                labels.get(str(number))
                or metadata.get(mount, {}).get("label")
                or os.path.basename(mount)
                or f"drive {number}"
            ),
            "removable": bool(metadata.get(mount, {}).get("removable", True)),
            "read_only": bool(metadata.get(mount, {}).get("read_only", False)),
            "filesystem": str(metadata.get(mount, {}).get("filesystem", "")),
        }
        usedroots.add(mount)
        number += 1

    DRIVES = found
    DRIVELASTSCAN = now
    return old != DRIVES


def driveforpath(path):

    physical = _physicalnormalize(path)
    best = DRIVES.get(1, {"number": 1, "root": "/"})
    bestlen = 1

    for drive in DRIVES.values():
        root = _physicalnormalize(drive.get("root", "/"))
        try:
            common = os.path.commonpath((physical, root)).replace("\\", "/")
        except Exception:
            continue
        if common == root and len(root) >= bestlen:
            best = drive
            bestlen = len(root)

    return best


def driverelpath(path, drive=None):

    if drive is None:
        drive = driveforpath(path)
    root = _physicalnormalize(drive.get("root", "/"))
    physical = _physicalnormalize(path)

    try:
        rel = os.path.relpath(physical, root).replace("\\", "/")
    except Exception:
        rel = ""

    if rel in ("", "."):
        return "/"
    if rel == ".." or rel.startswith("../"):
        return "/"
    return "/" + rel.lstrip("/")


def drivepath(number, relative="/"):

    try:
        number = int(number)
    except Exception:
        number = 1

    drive = DRIVES.get(number)
    if drive is None:
        return None

    root = _physicalnormalize(drive.get("root", "/"))
    relative = str(relative or "/").replace("\\", "/")
    physical = _physicalnormalize(os.path.join(root, relative.lstrip("/")))

    try:
        if os.path.commonpath((physical, root)).replace("\\", "/") != root:
            return None
    except Exception:
        return None

    return physical


def parselocation(value, currentdrive=None):

    text = str(value or "").strip().replace("\\", "/")
    drive = driveforpath(CWD) if currentdrive is None else DRIVES.get(int(currentdrive))
    number = int(drive.get("number", 1)) if drive else 1

    match = re.match(r"^([0-9]+)(?:/|$)(.*)$", text)
    if match:
        number = int(match.group(1))
        relative = "/" + match.group(2).lstrip("/")
    elif text.startswith("/"):
        relative = text
    else:
        base = driverelpath(CWD, DRIVES.get(number, DRIVES.get(1)))
        relative = os.path.join(base, text).replace("\\", "/")

    return number, drivepath(number, relative)


def formatlocation(path):

    drive = driveforpath(path)
    return f"{int(drive.get('number', 1))}{driverelpath(path, drive)}"


def applypickerconfig(config):

    global PICKERCONFIG, PICKERMODE, PICKERTITLE, PICKERFILTERS, PICKERFILTERINDEX
    global PICKERALLOWMULTIPLE, PICKERNAME, PICKERNAMECARETPOS, PICKERNAMEFOCUSED
    global PICKERNAMESELECTALL, PICKERNAMESELANCHOR, PICKERNAMEDRAGGING
    global PICKERDEFAULTEXTENSION, LAUNCHCWD, APPNAME

    if not isinstance(config, dict):
        raise ValueError("picker configuration is not an object")

    mode = str(config.get("mode", "")).strip().lower()
    if mode not in ("open_file", "select_tier", "save_location", "save_as"):
        raise ValueError("unsupported picker mode")

    filters = []
    for entry in config.get("filters", []):
        if not isinstance(entry, dict):
            continue
        values = [str(value).lower() for value in entry.get("extensions", [])]
        if values:
            filters.append({
                "id": str(entry.get("id", "filter")),
                "label": str(entry.get("label", "files")),
                "extensions": values,
            })
    if not filters:
        filters = [{"id": "all", "label": "all files", "extensions": ["*"]}]

    PICKERCONFIG = dict(config)
    PICKERMODE = mode
    PICKERTITLE = str(config.get("title", "array"))[:128]
    PICKERFILTERS = filters
    PICKERFILTERINDEX = 0
    PICKERALLOWMULTIPLE = bool(config.get("allow_multiple", False)) if mode == "open_file" else False
    PICKERNAME = str(config.get("suggested_name", ""))[:255]
    PICKERNAMECARETPOS = len(PICKERNAME)
    PICKERNAMEFOCUSED = (mode == "save_as")
    PICKERNAMESELECTALL = bool(PICKERNAME)
    PICKERNAMESELANCHOR = 0 if PICKERNAME else None
    PICKERNAMEDRAGGING = False
    PICKERDEFAULTEXTENSION = str(config.get("default_extension", "")).lower()
    APPNAME = PICKERTITLE

    initial = str(config.get("initial_path", "")).strip()
    if initial:
        initial = _physicalnormalize(initial)
        if os.path.isfile(initial):
            if mode == "save_as" and not PICKERNAME:
                PICKERNAME = os.path.basename(initial)
                PICKERNAMECARETPOS = len(PICKERNAME)
                PICKERNAMESELECTALL = bool(PICKERNAME)
                PICKERNAMESELANCHOR = 0 if PICKERNAME else None
            initial = os.path.dirname(initial)
        LAUNCHCWD = initial


def pickeractivefilter():

    if not PICKERFILTERS:
        return {"id": "all", "label": "all files", "extensions": ["*"]}

    return PICKERFILTERS[PICKERFILTERINDEX % len(PICKERFILTERS)]


def pickerpathmatches(path):

    if not PICKERMODE or os.path.isdir(path):
        return True

    values = pickeractivefilter().get("extensions", ["*"])
    if "*" in values:
        return True

    return os.path.splitext(str(path))[1].lower() in values


def pickerfiltercycle():

    global PICKERFILTERINDEX

    if len(PICKERFILTERS) <= 1:
        return

    PICKERFILTERINDEX = (PICKERFILTERINDEX + 1) % len(PICKERFILTERS)
    clearselection()
    buildtree()
    setstatus(f"showing {pickeractivefilter().get('label', 'files')}")


def pickerprimarylabel():

    return {
        "open_file": "open",
        "select_tier": "select tier",
        "save_location": "save here",
        "save_as": "save",
    }.get(PICKERMODE, "select")


def pickerwritabledirectory(path):

    try:
        target = _physicalnormalize(path)
        drive = driveforpath(target)
        if bool(drive.get("read_only", False)):
            return False
        if not os.path.isdir(target) or not os.access(target, os.W_OK):
            return False
        readonly = getattr(os, "ST_RDONLY", 1)
        return not bool(os.statvfs(target).f_flag & readonly)
    except Exception:
        return False


def pickerfinish(paths=None, overwrite=False):

    global PICKERTERMINAL

    if PICKERTERMINAL:
        return

    chosen = [_physicalnormalize(path) for path in list(paths or [])]
    locations = [formatlocation(path) for path in chosen]
    PICKERTERMINAL = True
    sendws({
        "op": "PICKER_FINISH",
        "request_id": PICKERSESSION,
        "status": "accepted",
        "paths": chosen,
        "locations": locations,
        "overwrite_approved": bool(overwrite),
    })
    flushws()


def pickercancel():

    global PICKERTERMINAL

    if PICKERTERMINAL:
        return

    PICKERTERMINAL = True
    sendws({
        "op": "PICKER_FINISH",
        "request_id": PICKERSESSION,
        "status": "cancelled",
        "paths": [],
        "locations": [],
    })
    flushws()


def pickerconfirm(overwrite=False):

    global PICKERNAME, PICKERNAMECARETPOS, PICKEROVERWRITEPATH

    if not PICKERMODE or PICKERTERMINAL:
        return

    if PICKERMODE == "open_file":
        paths = []
        for path in selectedpaths():
            resolved, error = resolvearraylink(path)
            if error is None and os.path.isfile(resolved) and pickerpathmatches(resolved):
                paths.append(resolved)
        if not PICKERALLOWMULTIPLE:
            paths = paths[:1]
        if not paths:
            setstatus("select a file to open", error=True)
            return
        pickerfinish(paths)
        return

    if PICKERMODE == "select_tier":
        path = SELECTED if SELECTED and os.path.isdir(SELECTED) else CWD
        if not os.path.isdir(path):
            setstatus("select a tier", error=True)
            return
        pickerfinish([path])
        return

    if PICKERMODE == "save_location":
        if not pickerwritabledirectory(CWD):
            setstatus("this location is read-only", error=True)
            return
        pickerfinish([CWD])
        return

    name = str(PICKERNAME).strip()
    if not name or name in (".", ".."):
        setstatus("enter a file name", error=True)
        return
    if name != os.path.basename(name) or "/" in name or "\\" in name:
        setstatus("the file name cannot contain a path", error=True)
        return
    if any(ord(char) < 32 for char in name) or "\x00" in name:
        setstatus("the file name contains unsupported characters", error=True)
        return
    if len(name.encode("utf-8", errors="ignore")) > 255:
        setstatus("the file name is too long", error=True)
        return

    if not os.path.splitext(name)[1] and PICKERDEFAULTEXTENSION:
        name += PICKERDEFAULTEXTENSION
        PICKERNAME = name
        PICKERNAMECARETPOS = len(name)

    if not pickerwritabledirectory(CWD):
        setstatus("this location is read-only", error=True)
        return

    destination = _physicalnormalize(os.path.join(CWD, name))
    try:
        common = _physicalnormalize(os.path.commonpath((destination, _physicalnormalize(CWD))))
        if common != _physicalnormalize(CWD):
            setstatus("invalid save location", error=True)
            return
    except Exception:
        setstatus("invalid save location", error=True)
        return

    if os.path.isdir(destination):
        setstatus("a tier already uses that name", error=True)
        return

    if isarraylink(destination):
        setstatus("a link cannot be replaced from save as", error=True)
        return

    if os.path.exists(destination) and not overwrite:
        PICKEROVERWRITEPATH = destination
        openconfirm("picker_overwrite", [destination])
        return

    pickerfinish([destination], overwrite=bool(overwrite))


def pickernamefromselection(path):

    global PICKERNAME, PICKERNAMECARETPOS, PICKERNAMEFOCUSED, PICKERNAMESELECTALL, PICKERNAMESELANCHOR

    if PICKERMODE != "save_as" or not os.path.isfile(path):
        return

    PICKERNAME = os.path.basename(path)[:255]
    PICKERNAMECARETPOS = len(PICKERNAME)
    PICKERNAMEFOCUSED = True
    PICKERNAMESELECTALL = True
    PICKERNAMESELANCHOR = 0
    invalidaterect(0, WINH - STATUSH, WINW, STATUSH)


def pathsetting(path, label=None):

    drive = driveforpath(path)
    return {
        "label": str(label or os.path.basename(str(path).rstrip("/")) or drive.get("label") or "root"),
        "drive": int(drive.get("number", 1)),
        "path": driverelpath(path, drive),
    }


def defaultsidebar():

    username = getusername()
    paths = [
        ("root", "/"),
        ("software", "/software"),
        (username, f"/master/{username}"),
        ("expanse", f"/master/{username}/expanse"),
        ("flash", f"/master/{username}/flash"),
        ("reference", f"/master/{username}/reference"),
        ("downloads", f"/master/{username}/flash/downloads"),
        ("images", f"/master/{username}/flash/images"),
        ("music", f"/master/{username}/flash/music"),
        ("videos", f"/master/{username}/flash/videos"),
        ("rubbish", "/.rubbish"),
    ]
    return [pathsetting(path, label) for label, path in paths]


def applysettings(data):

    global SETTINGS, SIDBARENTRIES, VIEWMODE, SORTKEY, SORTDESC, FOLDERSFIRST
    global SHOWEXTENSIONS, SHOWITEMCHECKS, PROPERTIESPANE, DETAILCOLUMNS
    global COLUMNWIDTHS, SEARCHSCOPE

    merged = defaultsettings()
    if isinstance(data, dict):
        migrated = dict(data)
        if "sidebar" not in migrated and "quick_access" in migrated:
            migrated["sidebar"] = migrated.get("quick_access")
        if "properties_pane" not in migrated:
            migrated["properties_pane"] = bool(migrated.get("preview_pane") or migrated.get("details_pane"))
        assignments = migrated.get("drive_assignments")
        if isinstance(assignments, list):
            assignments = [dict(entry) for entry in assignments if isinstance(entry, dict)]
            for entry in assignments:
                if entry.get("root"):
                    entry["root"] = migratedriveroot(entry["root"])
            migrated["drive_assignments"] = assignments
        merged.update(migrated)
    merged.pop("quick_access", None)
    merged.pop("preview_pane", None)
    merged.pop("details_pane", None)
    SETTINGS = merged

    VIEWMODE = merged.get("view_mode") if merged.get("view_mode") in ("tier", "details") else "tier"
    SORTKEY = merged.get("sort_key") if merged.get("sort_key") in ("name", "modified", "type", "size") else "name"
    SORTDESC = bool(merged.get("sort_descending", False))
    FOLDERSFIRST = bool(merged.get("folders_first", True))
    SHOWEXTENSIONS = bool(merged.get("show_extensions", True))
    SHOWITEMCHECKS = bool(merged.get("show_item_checks", False))
    PROPERTIESPANE = bool(merged.get("properties_pane", False))
    SEARCHSCOPE = merged.get("search_scope") if merged.get("search_scope") in ("tier", "drive", "terminal") else "tier"

    columns = merged.get("detail_columns")
    if isinstance(columns, list):
        clean = [v for v in columns if v in ("name", "modified", "type", "size")]
        if "name" not in clean:
            clean.insert(0, "name")
        DETAILCOLUMNS = clean or ["name", "modified", "type", "size"]

    widths = merged.get("column_widths")
    if isinstance(widths, dict):
        for key in ("name", "modified", "type", "size"):
            try:
                COLUMNWIDTHS[key] = max(50, min(900, int(widths.get(key, COLUMNWIDTHS[key]))))
            except Exception:
                pass

    loaddrives(force=True)

    savedsidebar = merged.get("sidebar")
    SIDBARENTRIES = []
    if isinstance(savedsidebar, list):
        for entry in savedsidebar:
            try:
                number = int(entry.get("drive", 1))
                relative = str(entry.get("path", "/"))
                label = str(entry.get("label") or "location")
            except Exception:
                continue
            SIDBARENTRIES.append({"label": label, "drive": number, "path": relative})

    if not SIDBARENTRIES:
        SIDBARENTRIES = defaultsidebar()


def loadsettings():

    data = {}
    try:
        with open(SETTINGSFILE, "r", encoding="utf-8") as f:
            loaded = json.load(f)
            if isinstance(loaded, dict):
                data = loaded
    except Exception:
        data = {}

    applysettings(data)


def savesettings():

    global SETTINGS

    SETTINGS.pop("quick_access", None)
    SETTINGS.pop("preview_pane", None)
    SETTINGS.pop("details_pane", None)

    SETTINGS.update({
        "version": SETTINGSVERSION,
        "sidebar": list(SIDBARENTRIES),
        "view_mode": VIEWMODE,
        "sort_key": SORTKEY,
        "sort_descending": bool(SORTDESC),
        "folders_first": bool(FOLDERSFIRST),
        "show_extensions": bool(SHOWEXTENSIONS),
        "show_item_checks": bool(SHOWITEMCHECKS),
        "properties_pane": bool(PROPERTIESPANE),
        "detail_columns": list(DETAILCOLUMNS),
        "column_widths": dict(COLUMNWIDTHS),
        "search_scope": SEARCHSCOPE,
    })

    folder = os.path.dirname(SETTINGSFILE)
    temporary = f"{SETTINGSFILE}.tmp.{os.getpid()}"
    try:
        os.makedirs(folder, exist_ok=True)
        with open(temporary, "w", encoding="utf-8") as f:
            json.dump(SETTINGS, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, SETTINGSFILE)
        return True
    except Exception:
        try:
            if os.path.exists(temporary):
                os.unlink(temporary)
        except Exception:
            pass
        return False


def sidebarentrypath(entry):

    try:
        return drivepath(int(entry.get("drive", 1)), entry.get("path", "/"))
    except Exception:
        return None


def sidebarpin(path, label=None):

    physical = _physicalnormalize(path)
    for entry in SIDBARENTRIES:
        if sidebarentrypath(entry) == physical:
            return False
    SIDBARENTRIES.append(pathsetting(physical, label))
    buildsidebarlinks()
    savesettings()
    return True


def sidebarunpin(index):

    try:
        del SIDBARENTRIES[int(index)]
    except Exception:
        return False
    buildsidebarlinks()
    savesettings()
    return True


def sidebarmove(source, target):

    try:
        source = int(source)
        target = max(0, min(len(SIDBARENTRIES) - 1, int(target)))
        entry = SIDBARENTRIES.pop(source)
        SIDBARENTRIES.insert(target, entry)
    except Exception:
        return False
    buildsidebarlinks()
    savesettings()
    return True


def sidebarrename(index, label):

    try:
        value = str(label).strip()
        if not value:
            return False
        SIDBARENTRIES[int(index)]["label"] = value
    except Exception:
        return False
    buildsidebarlinks()
    savesettings()
    return True


def driverename(number, label):

    try:
        number = int(number)
        value = str(label).strip()
        if number not in DRIVES or not value:
            return False
    except Exception:
        return False

    labels = SETTINGS.get("drive_labels")
    if not isinstance(labels, dict):
        labels = {}
    labels[str(number)] = value
    SETTINGS["drive_labels"] = labels
    DRIVES[number]["label"] = value

    assignments = SETTINGS.get("drive_assignments")
    if isinstance(assignments, list):
        for entry in assignments:
            try:
                if int(entry.get("number")) == number:
                    entry["label"] = value
            except Exception:
                continue

    buildsidebarlinks()
    savesettings()
    return True


# long-running filesystem work stays inside Array and runs on one worker thread
def jobsize(paths, tracker=None):

    total = 0
    for source in paths:
        try:
            if os.path.isdir(source) and not os.path.islink(source):
                for root, dirs, files in os.walk(source):
                    if tracker is not None and tracker["cancel"].is_set():
                        raise InterruptedError("cancelled")
                    for name in files:
                        try:
                            full = os.path.join(root, name)
                            amount = os.path.getsize(full)
                            total += amount
                            if tracker is not None:
                                jobprogress(tracker, amount, full)
                        except Exception:
                            pass
            else:
                amount = os.path.getsize(source)
                total += amount
                if tracker is not None:
                    jobprogress(tracker, amount, source)
        except InterruptedError:
            raise
        except Exception:
            pass
    return total


def jobprogress(job, amount=0, current=None):

    job["done_bytes"] = int(job.get("done_bytes", 0)) + int(amount or 0)
    now = time.monotonic()
    if current is not None:
        job["current"] = str(current)
    if (now - float(job.get("last_event", 0.0))) >= 0.08:
        job["last_event"] = now
        JOBEVENTS.put({
            "event": "progress",
            "id": job["id"],
            "done": int(job.get("done_bytes", 0)),
            "total": int(job.get("total_bytes", 0)),
            "current": job.get("current", ""),
        })


def jobcopyfile(source, target, job):

    os.makedirs(os.path.dirname(target), exist_ok=True)
    if os.path.islink(source):
        linktarget = os.readlink(source)
        if not os.path.isabs(linktarget):
            linktarget = os.path.join(os.path.dirname(source), linktarget)
        writearraylink(target, linktarget)
        jobprogress(job, 0, source)
        return
    with open(source, "rb") as src, open(target, "wb") as dst:
        while True:
            if job["cancel"].is_set():
                raise InterruptedError("cancelled")
            block = src.read(1024 * 1024)
            if not block:
                break
            dst.write(block)
            jobprogress(job, len(block), source)
    try:
        # External filesystems do not necessarily support T1OS/Unix ownership,
        # modes, timestamps, flags, or extended attributes. The file contents
        # are the required result; preserve compatible metadata when possible.
        shutil.copystat(source, target, follow_symlinks=False)
    except OSError:
        pass


def jobcopytree(source, target, job):

    os.makedirs(target, exist_ok=True)
    for root, dirs, files in os.walk(source):
        if job["cancel"].is_set():
            raise InterruptedError("cancelled")
        relative = os.path.relpath(root, source)
        outroot = target if relative == "." else os.path.join(target, relative)
        os.makedirs(outroot, exist_ok=True)
        for dirname in list(dirs):
            sourcechild = os.path.join(root, dirname)
            targetchild = os.path.join(outroot, dirname)
            if os.path.islink(sourcechild):
                linktarget = os.readlink(sourcechild)
                if not os.path.isabs(linktarget):
                    linktarget = os.path.join(os.path.dirname(sourcechild), linktarget)
                writearraylink(targetchild, linktarget)
                dirs.remove(dirname)
            else:
                os.makedirs(targetchild, exist_ok=True)
        for filename in files:
            jobcopyfile(os.path.join(root, filename), os.path.join(outroot, filename), job)
    try:
        shutil.copystat(source, target, follow_symlinks=False)
    except Exception:
        pass


def jobdestination(dest, name, reserved, strategy="keepboth"):

    target = os.path.join(dest, name)
    if target in reserved or os.path.exists(target):
        if strategy == "skip":
            return None
        if strategy == "replace":
            if os.path.isdir(target) and not os.path.islink(target):
                shutil.rmtree(target)
            else:
                os.unlink(target)
        else:
            target = uniquepath(dest, name, reserved)
    reserved.add(target)
    return target


def jobsafeextract(archive, target, job):

    root = _physicalnormalize(target)
    with zipfile.ZipFile(archive, "r") as zf:
        infos = zf.infolist()
        job["total_bytes"] = sum(max(0, int(info.file_size)) for info in infos)
        for info in infos:
            if job["cancel"].is_set():
                raise InterruptedError("cancelled")
            out = _physicalnormalize(os.path.join(root, info.filename))
            if os.path.commonpath((root, out)).replace("\\", "/") != root:
                raise ValueError("archive contains an unsafe path")
            if info.is_dir():
                os.makedirs(out, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with zf.open(info, "r") as src, open(out, "wb") as dst:
                while True:
                    block = src.read(1024 * 1024)
                    if not block:
                        break
                    dst.write(block)
                    jobprogress(job, len(block), info.filename)


def jobzipfile(zf, source, arcname, job):

    with open(source, "rb") as src, zf.open(str(arcname).replace("\\", "/"), "w", force_zip64=True) as dst:
        while True:
            if job["cancel"].is_set():
                raise InterruptedError("cancelled")
            block = src.read(1024 * 1024)
            if not block:
                break
            dst.write(block)
            jobprogress(job, len(block), source)


def jobexecute(job):

    kind = job.get("kind")
    sources = [str(path) for path in job.get("sources", []) if path]
    result = {"paths": [], "undo": []}

    if kind in ("copy", "move"):
        dest = _physicalnormalize(job.get("dest", CWD))
        strategy = job.get("conflict", JOBCONFLICTDEFAULT)
        job["total_bytes"] = jobsize(sources)
        try:
            required = job["total_bytes"] if kind == "copy" else sum(jobsize([source]) for source in sources if os.stat(source).st_dev != os.stat(dest).st_dev)
            if required > shutil.disk_usage(dest).free:
                raise OSError("not enough free space on the destination drive")
        except OSError:
            raise
        except Exception:
            pass
        reserved = set()
        for source in sources:
            if job["cancel"].is_set():
                raise InterruptedError("cancelled")
            if not os.path.exists(source):
                continue
            if kind == "move" and _physicalnormalize(os.path.dirname(source)) == dest:
                result["paths"].append(source)
                continue
            if os.path.isdir(source) and not os.path.islink(source):
                try:
                    inside_source = os.path.commonpath((_physicalnormalize(dest), _physicalnormalize(source))).replace("\\", "/") == _physicalnormalize(source)
                except Exception:
                    inside_source = False
                if inside_source:
                    raise ValueError("a tier cannot be copied or moved into itself")
            target = jobdestination(dest, os.path.basename(source.rstrip("/")), reserved, strategy)
            if target is None:
                continue
            job["partial"] = target
            job["partial_source"] = source
            if kind == "move":
                same_device = False
                try:
                    same_device = os.stat(source).st_dev == os.stat(dest).st_dev
                except Exception:
                    pass
                if same_device:
                    shutil.move(source, target)
                    jobprogress(job, jobsize([target]), source)
                else:
                    if os.path.isdir(source) and not os.path.islink(source):
                        jobcopytree(source, target, job)
                        shutil.rmtree(source)
                    else:
                        jobcopyfile(source, target, job)
                        os.unlink(source)
            else:
                if os.path.isdir(source) and not os.path.islink(source):
                    jobcopytree(source, target, job)
                else:
                    jobcopyfile(source, target, job)
            result["paths"].append(target)
            result["undo"].append({"src": normalisepath(source), "dst": normalisepath(target)})
            job["partial"] = None
            job["partial_source"] = None
        result["undo_type"] = "move" if kind == "move" else "copy"

    elif kind == "delete":
        before = rubbishids()
        job["delete_before"] = before
        job["total_bytes"] = jobsize(sources)
        for source in sources:
            if job["cancel"].is_set():
                raise InterruptedError("cancelled")
            amount = jobsize([source])
            storepaths([source])
            jobprogress(job, amount, source)
        result["undo"] = newrubbishitems(before, sources)
        result["undo_type"] = "delete"

    elif kind == "destroy":
        job["total_bytes"] = jobsize(sources)
        for target in sources:
            if job["cancel"].is_set():
                raise InterruptedError("cancelled")
            absolute = _physicalnormalize(target)
            amount = jobsize([absolute])
            if absolute == _physicalnormalize("/.rubbish"):
                continue
            if absolute.startswith(_physicalnormalize("/.rubbish") + "/"):
                rid = absolute[len(_physicalnormalize("/.rubbish")) + 1:].split("/", 1)[0]
                payload = os.path.join("/.rubbish", rid)
                if os.path.isdir(payload):
                    shutil.rmtree(payload)
                try:
                    records = rubbishrecords()
                    with open("/.rubbish/index.txt", "w") as f:
                        f.write("id\tname\torigpath\tisdir\tsize\tdeletedts\tuser\n")
                        for record in records:
                            if str(record.get("id")) == rid:
                                continue
                            f.write("\t".join(str(record.get(k, "")) for k in ("id", "name", "origpath", "isdir", "size", "deletedts", "user")) + "\n")
                except Exception:
                    pass
            elif os.path.isdir(absolute) and not os.path.islink(absolute):
                shutil.rmtree(absolute)
            elif os.path.lexists(absolute):
                os.unlink(absolute)
            jobprogress(job, amount, absolute)

    elif kind == "zip":
        dest = _physicalnormalize(job.get("dest", CWD))
        basename = job.get("name") or (os.path.basename(sources[0].rstrip("/")) if len(sources) == 1 else "archive")
        target = uniquepath(dest, f"{basename}.zip")
        job["partial"] = target
        job["total_bytes"] = jobsize(sources)
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
            for source in sources:
                baseparent = os.path.dirname(source.rstrip("/"))
                if os.path.isdir(source):
                    for root, dirs, files in os.walk(source):
                        for filename in files:
                            if job["cancel"].is_set():
                                raise InterruptedError("cancelled")
                            full = os.path.join(root, filename)
                            jobzipfile(zf, full, os.path.relpath(full, baseparent), job)
                else:
                    jobzipfile(zf, source, os.path.basename(source), job)
        result["paths"] = [target]
        job["partial"] = None

    elif kind == "extract":
        archive = sources[0]
        dest = _physicalnormalize(job.get("dest", CWD))
        name = os.path.splitext(os.path.basename(archive))[0]
        target = uniquepath(dest, name)
        job["partial"] = target
        os.makedirs(target, exist_ok=True)
        jobsafeextract(archive, target, job)
        result["paths"] = [target]
        job["partial"] = None

    elif kind == "size":
        result["size"] = jobsize(sources, job)

    return result


def jobworker():

    while not JOBSTOP.is_set():
        try:
            job = JOBQUEUE.get(timeout=0.25)
        except queue.Empty:
            continue
        if job is None:
            break
        JOBEVENTS.put({"event": "started", "id": job["id"], "kind": job["kind"]})
        try:
            result = jobexecute(job)
            if job["cancel"].is_set():
                raise InterruptedError("cancelled")
            JOBEVENTS.put({"event": "done", "id": job["id"], "result": result})
        except InterruptedError:
            partial = job.get("partial")
            source = job.get("partial_source")
            try:
                safe = job.get("kind") != "move" or (source and os.path.exists(source))
                if partial and safe and os.path.lexists(partial):
                    if os.path.isdir(partial) and not os.path.islink(partial):
                        shutil.rmtree(partial)
                    else:
                        os.unlink(partial)
            except Exception:
                pass
            if job.get("kind") == "delete":
                partialresult = {
                    "paths": [],
                    "undo": newrubbishitems(job.get("delete_before", set()), job.get("sources", [])),
                    "undo_type": "delete",
                    "partial": True,
                }
                JOBEVENTS.put({"event": "done", "id": job["id"], "result": partialresult})
            else:
                JOBEVENTS.put({"event": "cancelled", "id": job["id"]})
        except Exception as error:
            JOBEVENTS.put({"event": "error", "id": job["id"], "error": str(error)})
        finally:
            JOBQUEUE.task_done()


def startjobworker():

    global JOBTHREAD
    if JOBTHREAD is not None and JOBTHREAD.is_alive():
        return
    JOBSTOP.clear()
    JOBTHREAD = threading.Thread(target=jobworker, name="array-file-jobs", daemon=True)
    JOBTHREAD.start()


def prunepaths(paths):

    clean = []
    for path in sorted(set(_physicalnormalize(value) for value in paths if value), key=len):
        nested = False
        for parent in clean:
            try:
                if os.path.isdir(parent) and os.path.commonpath((path, parent)).replace("\\", "/") == parent:
                    nested = True
                    break
            except Exception:
                pass
        if not nested:
            clean.append(path)
    return clean


def plannedjobtarget(dest, name, reserved, strategy="keepboth"):

    target = os.path.join(dest, name)

    if target in reserved or os.path.exists(target):

        if strategy == "skip":
            return None

        if strategy != "replace":
            target = uniquepath(dest, name, reserved)

    reserved.add(target)
    return target


def jobpermissionpaths(kind, sources=None, dest=None, **options):

    operation = str(kind or "").lower()
    sources = list(sources or [])
    checks = []
    destination = _physicalnormalize(dest) if dest else None

    # Copy, zip, and extract only read their inputs. Master may read protected
    # system tiers, while move/delete/destroy change or remove their sources.
    if operation in ("delete", "destroy"):
        checks.extend(sources)

    elif operation in ("copy", "move") and destination:

        strategy = str(options.get("conflict", JOBCONFLICTDEFAULT))
        reserved = set()

        for source in sources:

            if not os.path.exists(source):
                continue

            if operation == "move" and _physicalnormalize(os.path.dirname(source)) == destination:
                continue

            name = os.path.basename(str(source).rstrip("/"))
            target = plannedjobtarget(destination, name, reserved, strategy)

            if target is None:
                continue

            if operation == "move":
                checks.append(source)

            checks.extend(creationmutationpaths(target))

    elif operation == "zip" and destination and sources:

        basename = options.get("name") or (
            os.path.basename(str(sources[0]).rstrip("/"))
            if len(sources) == 1 else "archive"
        )
        checks.extend(creationmutationpaths(uniquepath(destination, f"{basename}.zip")))

    elif operation == "extract" and destination and sources:

        name = os.path.splitext(os.path.basename(str(sources[0])))[0]
        checks.extend(creationmutationpaths(uniquepath(destination, name)))

    return checks


def enqueuejob(kind, sources=None, dest=None, **options):

    global JOBSEQ
    sources = prunepaths(sources or [])
    operation = str(kind or "").lower()
    if operation in ("copy", "move", "delete", "destroy", "zip", "extract"):
        checks = jobpermissionpaths(operation, sources, dest, **options)
        if not permissionpaths(checks):
            return None
    startjobworker()
    JOBSEQ += 1
    job = {
        "id": JOBSEQ,
        "kind": str(kind),
        "sources": sources,
        "dest": dest,
        "cancel": threading.Event(),
        "done_bytes": 0,
        "total_bytes": 0,
        "last_event": 0.0,
        "status": "queued",
    }
    job.update(options)
    JOBS[JOBSEQ] = job
    JOBQUEUE.put(job)
    setstatus(f"{kind} queued", duration=60000)
    return JOBSEQ


def cancelactivejob():

    if ACTIVEJOB is None:
        return False
    job = JOBS.get(ACTIVEJOB)
    if not job:
        return False
    job["cancel"].set()
    setstatus("cancelling operation", duration=60000)
    return True


def jobpump():

    global ACTIVEJOB, CUTSET, PROPERTIESDATA
    changed = False
    while True:
        try:
            event = JOBEVENTS.get_nowait()
        except queue.Empty:
            break
        job = JOBS.get(event.get("id"), {})
        kind = job.get("kind", "operation")
        if event.get("event") == "started":
            ACTIVEJOB = event.get("id")
            job["status"] = "running"
            setstatus(f"{kind} started — Esc to cancel", duration=60000)
        elif event.get("event") == "progress":
            total = int(event.get("total", 0))
            done = int(event.get("done", 0))
            percent = int((done * 100) / total) if total > 0 else 0
            setstatus(f"{kind} {percent}%  {os.path.basename(str(event.get('current', '')))} — Esc to cancel", duration=60000)
        elif event.get("event") == "done":
            job["status"] = "done"
            result = event.get("result", {})
            undo = result.get("undo") or []
            if undo and result.get("undo_type"):
                pushundo({"type": result.get("undo_type"), "items": undo})
            if kind == "move" and job.get("clipboard"):
                exclear(source="array")
                CUTSET = set()
                refreshclipboard()
            if kind == "size" and PROPERTIESOPEN:
                PROPERTIESDATA = [(k, formatfilesize(result.get("size", 0)) if k == "total size" else v) for k, v in PROPERTIESDATA]
            paths = result.get("paths") or []
            ACTIVEJOB = None
            setstatus(f"{kind} stopped" if result.get("partial") else f"{kind} complete")
            buildtree()
            if paths:
                selectpath(paths[0])
                scrolltopath(paths[0])
            changed = True
        elif event.get("event") == "cancelled":
            job["status"] = "cancelled"
            ACTIVEJOB = None
            setstatus(f"{kind} cancelled")
            buildtree()
            changed = True
        elif event.get("event") == "error":
            job["status"] = "error"
            ACTIVEJOB = None
            setstatus(f"{kind} failed: {event.get('error', 'unknown error')}", error=True, duration=6000)
            buildtree()
            changed = True
    if changed:
        invalidaterect(0, 0, WINW, WINH)


def parsesizefilter(value):

    match = re.match(r"^([0-9]+(?:\.[0-9]+)?)(b|kb|mb|gb|tb)?$", str(value).strip().lower())
    if not match:
        return None
    amount = float(match.group(1))
    multiplier = {None: 1, "b": 1, "kb": 1024, "mb": 1024 ** 2, "gb": 1024 ** 3, "tb": 1024 ** 4}.get(match.group(2), 1)
    return int(amount * multiplier)


def comparefilter(actual, expression, parser=lambda value: value):

    match = re.match(r"^(<=|>=|<|>|=)?(.*)$", str(expression).strip())
    if not match:
        return False
    operator = match.group(1) or "="
    expected = parser(match.group(2))
    if expected is None:
        return False
    if operator == "<":
        return actual < expected
    if operator == ">":
        return actual > expected
    if operator == "<=":
        return actual <= expected
    if operator == ">=":
        return actual >= expected
    return actual == expected


def searchmatches(path, name, isdir, terms):

    lowered = str(name).casefold()
    metadata = None
    for term in terms:
        key, separator, value = term.partition(":")
        key = key.casefold()
        value = value.casefold()
        if not separator:
            if ("*" in term or "?" in term):
                if not fnmatch.fnmatch(lowered, term.casefold()):
                    return False
            elif term.casefold() not in lowered:
                return False
        elif key == "name":
            if value not in lowered:
                return False
        elif key in ("ext", "extension"):
            if os.path.splitext(lowered)[1].lstrip(".") != value.lstrip("."):
                return False
        elif key in ("kind", "type"):
            if key == "kind" and value in ("tier", "folder", "directory"):
                if not isdir:
                    return False
            elif key == "kind" and value == "file":
                if isdir:
                    return False
            elif value not in typelabel(name, isdir).casefold():
                return False
        elif key == "size":
            if isdir:
                return False
            try:
                actual = os.path.getsize(path)
            except Exception:
                return False
            if not comparefilter(actual, value, parsesizefilter):
                return False
        elif key in ("modified", "date"):
            try:
                actual = int(time.strftime("%Y%m%d", time.localtime(os.path.getmtime(path))))
                parser = lambda text: int(str(text).replace("-", "")) if re.match(r"^[0-9]{4}-?[0-9]{2}-?[0-9]{2}$", str(text)) else None
                if not comparefilter(actual, value, parser):
                    return False
            except Exception:
                return False
        elif key == "content":
            if isdir:
                return False
            try:
                if os.path.getsize(path) > 2 * 1024 * 1024:
                    return False
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    if value not in f.read().casefold():
                        return False
            except Exception:
                return False
    return True


def searchnameterms(query):

    """Return the parts of a search query that can match an item's name."""

    try:
        terms = shlex.split(str(query or ""))
    except Exception:
        terms = str(query or "").split()

    result = []
    for term in terms:
        key, separator, value = str(term).partition(":")
        if separator:
            if key.casefold() != "name":
                continue
            term = value

        # Match Expanse's presentation of wildcard searches: the wildcard is
        # useful to the matcher, but is not itself part of the visible text.
        visible = str(term).strip("*?").lower()
        if visible:
            result.append(visible)

    return result


def searchrelevance(name, query):

    """Rank name matches using Expanse's exact/prefix/word/substring tiers."""

    label = str(name or "").lower()
    terms = searchnameterms(query)
    if not terms:
        return 0

    needle = " ".join(terms)
    if label == needle:
        return 0
    if label.startswith(needle):
        return 1

    words = label.split()
    if all(any(word.startswith(term) for word in words) for term in terms):
        return 2
    if all(term in label for term in terms):
        return 3
    return 4


def sortsearchitems(items, query):

    # Keep Array's configured sort and folders-first behavior as the stable
    # tie-breaker, but never let it outrank relevance during a search.
    ordered = sortitems(list(items or []))
    ordered.sort(key=lambda item: searchrelevance(item.get("name", ""), query))
    return ordered


def searchmatchspans(text, query=None):

    value = str(text or "")
    lowered = value.lower()
    spans = []

    for term in searchnameterms(SEARCHTEXT if query is None else query):
        start = 0
        while True:
            found = lowered.find(term, start)
            if found < 0:
                break
            spans.append((found, found + len(term)))
            start = found + len(term)

    merged = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def searchwalkroots(roots, showhidden, cancelled=None):

    """Yield entries from every root without letting one drive starve another."""

    normalizedroots = []
    for root in roots:
        normalized = _physicalnormalize(root)
        if normalized not in normalizedroots and os.path.isdir(normalized):
            normalizedroots.append(normalized)

    walkers = []
    allroots = set(normalizedroots)
    for root in normalizedroots:
        walkers.append({
            "root": root,
            "otherroots": allroots - {root},
            "iterator": os.walk(root),
        })

    # Advance one tier from each drive per pass.  A serial walk of 1/ can take
    # long enough (or fill the result limit) that removable drives are never
    # visited by a terminal-wide search.
    while walkers:
        active = []
        for walker in walkers:
            if cancelled is not None and cancelled():
                return

            try:
                folder, dirs, files = next(walker["iterator"])
            except StopIteration:
                continue
            except Exception:
                continue

            active.append(walker)
            dirs[:] = [
                name for name in dirs
                if showhidden or not itemishidden(os.path.join(folder, name), name)
            ]
            dirs[:] = [
                name for name in dirs
                if _physicalnormalize(os.path.join(folder, name)) not in walker["otherroots"]
            ]
            if walker["root"] == "/":
                dirs[:] = [
                    name for name in dirs
                    if _physicalnormalize(os.path.join(folder, name)) not in DRIVEPSEUDOPREFIXES
                ]

            for name in list(dirs) + files:
                if cancelled is not None and cancelled():
                    return
                path = os.path.join(folder, name).replace("\\", "/")
                if not showhidden and itemishidden(path, name):
                    continue
                yield path, name, name in dirs

        walkers = active


def validsearchsessionpath(path):

    try:
        root = os.path.realpath(SEARCHSESSIONROOT)
        candidate = os.path.realpath(str(path))
        return os.path.commonpath((root, candidate)) == root
    except Exception:
        return False


def detachsearchsession(remove=False):

    global SEARCHSESSIONPATH, SEARCHSESSIONSTAMP, SEARCHSESSIONQUERY

    path = SEARCHSESSIONPATH
    SEARCHSESSIONPATH = None
    SEARCHSESSIONSTAMP = None
    SEARCHSESSIONQUERY = ""

    if remove and path and validsearchsessionpath(path):
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass


def searchsessionpump(force=False):

    global SEARCHSESSIONSTAMP, SEARCHRUNNING, SEARCHRESULTS, SEARCHERROR
    global TREE, SCROLL

    path = SEARCHSESSIONPATH
    if not path or not validsearchsessionpath(path):
        return False

    try:
        state = os.stat(path)
        stamp = (int(getattr(state, "st_ino", 0)), int(state.st_mtime_ns), int(state.st_size))
        if not force and stamp == SEARCHSESSIONSTAMP:
            return False

        with open(path, "r", encoding="utf-8") as stream:
            payload = json.load(stream)

        if not isinstance(payload, dict) or int(payload.get("format", 0)) != 1:
            raise RuntimeError("invalid search handoff format")
        if str(payload.get("producer", "")) != "expanse":
            raise RuntimeError("invalid search handoff producer")
        if str(payload.get("query", "")).strip() != str(SEARCHSESSIONQUERY).strip():
            raise RuntimeError("search handoff query changed")

        existing = {
            os.path.abspath(str(item.get("realpath", item.get("path", "")))): item
            for item in SEARCHRESULTS
        }
        filters = {
            str(value).strip().lower()
            for value in list(payload.get("filters") or [])
            if str(value).strip()
        }
        items = []
        seen = set()
        for record in list(payload.get("results") or [])[:10000]:
            if not isinstance(record, dict):
                continue
            category = "tier" if bool(record.get("is_tier")) else "file"
            if filters and category not in filters:
                continue
            pathvalue = str(record.get("path", "")).strip()
            if not pathvalue:
                continue
            absolute = os.path.abspath(pathvalue)
            if absolute in seen:
                continue
            name = os.path.basename(pathvalue.rstrip("/")) or pathvalue
            if not SHOWHIDDEN and itemishidden(pathvalue, name):
                continue
            seen.add(absolute)
            item = existing.get(absolute)
            if item is None:
                item = enrichitem(name, pathvalue, forceddir=bool(record.get("is_tier")))
            items.append(item)

        SEARCHRESULTS = sortsearchitems(items, SEARCHTEXT)
        TREE = []
        for item in SEARCHRESULTS:
            entry = dict(item)
            entry.update({"depth": 0, "haskids": False, "expanded": False})
            TREE.append(entry)

        SEARCHSESSIONSTAMP = stamp
        SEARCHERROR = str(payload.get("error", "") or "")
        SEARCHRUNNING = not bool(payload.get("done", False))
        SCROLL = 0
        layout()
        computecontentwidth()
        invalidaterect(0, 0, WINW, WINH)

        if SEARCHRUNNING:
            setstatus(f"searching terminal — {len(TREE)} found", duration=60000)
        elif SEARCHERROR:
            setstatus(SEARCHERROR, error=True, duration=6000)
            detachsearchsession(remove=True)
        else:
            setstatus(f"{len(TREE)} search result{'s' if len(TREE) != 1 else ''}")
            detachsearchsession(remove=True)
        return True
    except FileNotFoundError:
        return False
    except Exception as error:
        SEARCHERROR = str(error)
        SEARCHRUNNING = False
        setstatus(SEARCHERROR, error=True, duration=6000)
        detachsearchsession(remove=False)
        invalidaterect(0, 0, WINW, WINH)
        return False


def adoptsearchsession(path, query):

    global SEARCHSESSIONPATH, SEARCHSESSIONSTAMP, SEARCHSESSIONQUERY
    global SEARCHTEXT, SEARCHCARETPOS, SEARCHSCOPE, SEARCHOPEN, SEARCHFOCUSED
    global SEARCHRUNNING, SEARCHERROR

    if not validsearchsessionpath(path):
        return False

    SEARCHSESSIONPATH = str(path)
    SEARCHSESSIONSTAMP = None
    SEARCHSESSIONQUERY = str(query or "").strip()
    SEARCHTEXT = SEARCHSESSIONQUERY
    SEARCHCARETPOS = len(SEARCHTEXT)
    SEARCHSCOPE = "terminal"
    SEARCHOPEN = True
    SEARCHFOCUSED = True
    SEARCHRUNNING = True
    SEARCHERROR = ""
    resetsearchcaret()
    setstatus("continuing taskbar search", duration=60000)
    return searchsessionpump(force=True)


def searchworker():

    while True:
        request = SEARCHQUEUE.get()
        if request is None:
            return
        generation = request["generation"]
        roots = request["roots"]
        query = request["query"]
        try:
            terms = shlex.split(query)
        except Exception:
            terms = query.split()
        showhidden = request["showhidden"]
        results = []
        lastpartial = 0.0
        try:
            cancelled = lambda: generation != SEARCHGENERATION
            for path, name, isdir in searchwalkroots(roots, showhidden, cancelled=cancelled):
                if not searchmatches(path, name, isdir, terms):
                    continue
                if PICKERMODE and not isdir and not pickerpathmatches(path):
                    continue
                results.append(enrichitem(name, path))
                now = time.monotonic()
                if len(results) == 1 or len(results) % 100 == 0 or (now - lastpartial) >= 0.1:
                    SEARCHEVENTS.put({"event": "partial", "generation": generation, "results": list(results)})
                    lastpartial = now
                if len(results) >= 10000:
                    break
            if generation == SEARCHGENERATION:
                SEARCHEVENTS.put({"event": "done", "generation": generation, "results": results})
        except Exception as error:
            SEARCHEVENTS.put({"event": "error", "generation": generation, "error": str(error)})
        finally:
            SEARCHQUEUE.task_done()


def startsearchworker():

    global SEARCHTHREAD
    if SEARCHTHREAD is not None and SEARCHTHREAD.is_alive():
        return
    SEARCHTHREAD = threading.Thread(target=searchworker, name="array-search", daemon=True)
    SEARCHTHREAD.start()


def resetsearchcaret():

    global SEARCHCARETSTART, SEARCHCARETSTATE
    SEARCHCARETSTART = time.monotonic()
    SEARCHCARETSTATE = True


def searchcaretvisible():

    elapsed = max(0.0, time.monotonic() - float(SEARCHCARETSTART))
    return int(elapsed / 0.5) % 2 == 0


def updatesearchcaret():

    global SEARCHCARETSTATE
    if not SEARCHFOCUSED:
        SEARCHCARETSTATE = None
        return
    visible = searchcaretvisible()
    if visible == SEARCHCARETSTATE:
        return
    SEARCHCARETSTATE = visible
    invalidaterect(0, 0, WINW, HEADERH)


def searchopen():

    global SEARCHOPEN, SEARCHFOCUSED, SEARCHTEXT, SEARCHCARETPOS, SEARCHRESULTS, SEARCHERROR
    SEARCHOPEN = True
    SEARCHFOCUSED = True
    resetsearchcaret()
    invalidaterect(0, 0, WINW, WINH)


def searchstart():

    global SEARCHGENERATION, SEARCHRUNNING, SEARCHRESULTS, SEARCHERROR, TREE, SCROLL
    query = SEARCHTEXT.strip()
    if not query:
        return
    detachsearchsession(remove=False)
    startsearchworker()
    SEARCHGENERATION += 1
    SEARCHRUNNING = True
    SEARCHRESULTS = []
    SEARCHERROR = ""
    TREE = []
    SCROLL = 0
    layout()
    computecontentwidth()
    while True:
        try:
            SEARCHQUEUE.get_nowait()
            SEARCHQUEUE.task_done()
        except queue.Empty:
            break
    roots = [CWD]
    if SEARCHSCOPE == "drive":
        roots = [driveforpath(CWD).get("root", "/")]
    elif SEARCHSCOPE == "terminal":
        # A terminal search is commonly launched immediately after a drive is
        # attached.  Refresh here rather than relying on the periodic cache.
        loaddrives(force=True)
        roots = []
        for number in sorted(DRIVES):
            root = _physicalnormalize(DRIVES[number].get("root", "/"))
            if root not in roots:
                roots.append(root)
        if not roots:
            roots = ["/"]
    SEARCHQUEUE.put({
        "generation": SEARCHGENERATION,
        "roots": roots,
        "query": query,
        "showhidden": SHOWHIDDEN,
    })
    location = "terminal" if SEARCHSCOPE == "terminal" else formatlocation(roots[0])
    setstatus(f"searching {location}", duration=60000)
    invalidaterect(0, 0, WINW, WINH)


def searchtextchanged():

    if SEARCHTEXT.strip():
        searchstart()
    else:
        searchclear()


def searchclose(rebuild=True):

    global SEARCHOPEN, SEARCHFOCUSED, SEARCHRUNNING, SEARCHGENERATION, SEARCHRESULTS, SEARCHERROR, SEARCHCARETSTATE
    detachsearchsession(remove=False)
    SEARCHGENERATION += 1
    SEARCHOPEN = False
    SEARCHFOCUSED = False
    SEARCHRUNNING = False
    SEARCHRESULTS = []
    SEARCHERROR = ""
    SEARCHCARETSTATE = None
    clearstatus()
    if rebuild:
        buildtree()


def searchclear():

    global SEARCHOPEN, SEARCHFOCUSED, SEARCHTEXT, SEARCHCARETPOS
    global SEARCHRUNNING, SEARCHGENERATION, SEARCHRESULTS, SEARCHERROR
    detachsearchsession(remove=False)
    SEARCHGENERATION += 1
    SEARCHOPEN = True
    SEARCHFOCUSED = True
    SEARCHTEXT = ""
    SEARCHCARETPOS = 0
    SEARCHRUNNING = False
    SEARCHRESULTS = []
    SEARCHERROR = ""
    resetsearchcaret()
    clearstatus()
    buildtree()
    watchreset()
    invalidaterect(0, 0, WINW, WINH)


def searchpump():

    global SEARCHRUNNING, SEARCHRESULTS, SEARCHERROR, TREE, SCROLL
    searchsessionpump()
    while True:
        try:
            event = SEARCHEVENTS.get_nowait()
        except queue.Empty:
            break
        if int(event.get("generation", -1)) != int(SEARCHGENERATION):
            continue
        kind = event.get("event")
        if kind in ("partial", "done"):
            SEARCHRESULTS = sortsearchitems(event.get("results", []), SEARCHTEXT)
            TREE = []
            for item in SEARCHRESULTS:
                entry = dict(item)
                entry.update({"depth": 0, "haskids": False, "expanded": False})
                TREE.append(entry)
            SCROLL = 0
            layout()
            computecontentwidth()
            invalidaterect(0, 0, WINW, WINH)
            if kind == "done":
                SEARCHRUNNING = False
                setstatus(f"{len(TREE)} search result{'s' if len(TREE) != 1 else ''}")
        elif kind == "error":
            SEARCHRUNNING = False
            SEARCHERROR = str(event.get("error", "search failed"))
            setstatus(SEARCHERROR, error=True)


def searchboxrect():

    width = min(scalesize(420), max(scalesize(180), WINW // 3))
    x = WINW - width - PAD
    y = HEADERGAP
    h = TITLEH
    return x, y, width, h


def searchboxhit(x, y):

    bx, by, bw, bh = searchboxrect()
    if x < bx or x > bx + bw or y < by or y > by + bh:
        return None
    clearw = scalesize(26) if SEARCHTEXT else 0
    scopew = scalesize(54)
    if clearw and x >= bx + bw - clearw:
        return "clear"
    return "scope" if x >= bx + bw - clearw - scopew else "field"


def searchcaretfromx(x):

    bx, _, bw, _ = searchboxrect()
    clearw = scalesize(26) if SEARCHTEXT else 0
    scopew = scalesize(54)
    localx = max(0, min(int(x) - bx - PAD, bw - scopew - clearw - (PAD * 2)))
    advance = 0
    for index, character in enumerate(SEARCHTEXT):
        width = max(1, measuretext(character, FONTSIZEROW, FONT))
        if advance + (width // 2) >= localx:
            return index
        advance += width
    return len(SEARCHTEXT)


def drawsearchbox():

    x, y, width, h = searchboxrect()
    clearw = scalesize(26) if SEARCHTEXT else 0
    scopew = scalesize(54)
    textw = max(1, width - scopew - clearw)
    fillrectfast(x, y, width, h, COLOURBG)
    drawrect(x, y, width, h, COLOURTEXT if SEARCHOPEN else COLOURMUTED)
    drawline(x + textw, y, x + textw, y + h, COLOURMUTED)
    prompts = {
        "tier": "search this tier",
        "drive": "search this drive",
        "terminal": "search this terminal",
    }
    prompt = SEARCHTEXT if SEARCHTEXT else prompts.get(SEARCHSCOPE, "search")
    colour = COLOURTEXT if SEARCHTEXT else COLOURMUTED
    shown = textview(prompt, FONTSIZEROW, FONT, 0, textw - (PAD * 2))
    drawtextttf(x + PAD, y + (h // 2) - (FONTSIZEROW // 2), shown, colour, FONTSIZEROW, FONT)
    scopelabel = SEARCHSCOPE
    scopex = x + textw + max(1, (scopew - measuretext(scopelabel, FONTSIZESTATUS, FONT)) // 2)
    drawtextttf(scopex, y + (h // 2) - (FONTSIZESTATUS // 2), scopelabel, COLOURMUTED, FONTSIZESTATUS, FONT)
    if clearw:
        clearx = x + width - clearw
        drawline(clearx, y, clearx, y + h, COLOURMUTED)
        cross = "×"
        crossx = clearx + max(1, (clearw - measuretext(cross, FONTSIZEROW, FONT)) // 2)
        try:
            miny, maxy = ttfbbox(cross, FONTSIZEROW, fontpath=FONT)
            crossy = y + ((h - (int(maxy) - int(miny))) // 2) - int(miny)
        except Exception:
            crossy = y + (h // 2) - (FONTSIZEROW // 2)
        drawtextttf(crossx, crossy, cross, COLOURTEXT, FONTSIZEROW, FONT)
    if SEARCHRUNNING:
        drawtextttf(x + textw - scalesize(24), y + (h // 2) - (FONTSIZEROW // 2), "...", COLOURMUTED, FONTSIZEROW, FONT)
    if SEARCHFOCUSED and searchcaretvisible():
        try:
            caret = measuretext(SEARCHTEXT[:SEARCHCARETPOS], FONTSIZEROW, FONT)
            caretx = min(x + textw - PAD, x + PAD + caret)
            drawline(caretx, y + 4, caretx, y + h - 4, COLOURTEXT)
        except Exception:
            pass


def openinput(title, initial, action, payload=None):

    global INPUTOPEN, INPUTTITLE, INPUTTEXT, INPUTCARETPOS, INPUTACTION, INPUTPAYLOAD
    INPUTOPEN = True
    INPUTTITLE = str(title)
    INPUTTEXT = str(initial or "")
    INPUTCARETPOS = len(INPUTTEXT)
    INPUTACTION = action
    INPUTPAYLOAD = payload
    invalidaterect(0, 0, WINW, WINH)


def opentextdialog(title, message, initial, action, payload=None, maxlength=256):

    global TEXTDIALOGWAITING, TEXTDIALOGID, TEXTDIALOGWIN, TEXTDIALOGTITLE
    global TEXTDIALOGINITIAL, TEXTDIALOGACTION, TEXTDIALOGPAYLOAD

    TEXTDIALOGWAITING = True
    TEXTDIALOGID = f"array-input-{os.getpid()}-{nowms()}"
    TEXTDIALOGWIN = None
    TEXTDIALOGTITLE = str(title)
    TEXTDIALOGINITIAL = str(initial or "")
    TEXTDIALOGACTION = action
    TEXTDIALOGPAYLOAD = payload
    closestatusmenu()
    closecontextmenu()
    sendws({
        "op": "CREATE_DIALOG",
        "parent": WINID,
        "dialog_id": TEXTDIALOGID,
        "title": TEXTDIALOGTITLE,
        "message": str(message),
        "input": {
            "value": TEXTDIALOGINITIAL,
            "select_all": True,
            "max_length": max(1, int(maxlength)),
            "allow_empty": False,
        },
        "buttons": [
            {"id": "ok", "label": "save"},
            {"id": "cancel", "label": "cancel", "cancel": True},
        ],
        "default": 0,
    })


def closetextdialog():

    global TEXTDIALOGWAITING, TEXTDIALOGID, TEXTDIALOGWIN, TEXTDIALOGTITLE
    global TEXTDIALOGINITIAL, TEXTDIALOGACTION, TEXTDIALOGPAYLOAD

    TEXTDIALOGWAITING = False
    TEXTDIALOGID = None
    TEXTDIALOGWIN = None
    TEXTDIALOGTITLE = ""
    TEXTDIALOGINITIAL = ""
    TEXTDIALOGACTION = None
    TEXTDIALOGPAYLOAD = None


def committextdialog(action, payload, value):

    value = str(value).strip()
    if not value:
        return
    if action == "sidebarrename":
        sidebarrename(payload, value)
        invalidaterect(0, 0, WINW, WINH)
    elif action == "driverename":
        driverename(payload, value)
        invalidaterect(0, 0, WINW, WINH)
    elif action == "openwith":
        setassociation(payload, value)
    elif action == "createlink":
        createlink(payload, value)


def closeinput():

    global INPUTOPEN, INPUTTITLE, INPUTTEXT, INPUTCARETPOS, INPUTACTION, INPUTPAYLOAD
    INPUTOPEN = False
    INPUTTITLE = ""
    INPUTTEXT = ""
    INPUTCARETPOS = 0
    INPUTACTION = None
    INPUTPAYLOAD = None
    invalidaterect(0, 0, WINW, WINH)


def setassociation(target, program):

    extension = os.path.splitext(str(target))[1].lower()
    if not extension or not os.path.isfile(program):
        setstatus("application is not available", error=True)
        return False
    associations = SETTINGS.get("associations")
    if not isinstance(associations, dict):
        associations = {}
    associations[extension] = _physicalnormalize(program)
    SETTINGS["associations"] = associations
    savesettings()
    return launchassociation(target, program)


def launchassociation(target, program):

    if not os.path.isfile(program):
        return False
    try:
        user = getusername()
        base = os.path.basename(program)
        opsrun(
            program, [target], os.path.splitext(base)[0],
            None, user, "front", await_window=True,
        )
        return True
    except Exception:
        setstatus("could not open application", error=True)
        return False


def createlink(target, name=None, destination=None):

    destination = destination or os.path.dirname(target)
    basename = name or (os.path.basename(target.rstrip("/")) + " link")
    out = uniquepath(destination, basename)
    if not permissionpaths(creationmutationpaths(out)):
        return False
    try:
        writearraylink(out, target)
        buildtree()
        selectpath(out)
        return True
    except Exception as error:
        setstatus(f"could not create link: {error}", error=True)
        return False


def commitinput():

    action = INPUTACTION
    value = INPUTTEXT.strip()
    payload = INPUTPAYLOAD
    closeinput()
    if action == "sidebarrename":
        sidebarrename(payload, value)
        invalidaterect(0, 0, WINW, WINH)
    elif action == "driverename":
        driverename(payload, value)
        invalidaterect(0, 0, WINW, WINH)
    elif action == "openwith":
        setassociation(payload, value)
    elif action == "createlink":
        createlink(payload, value)


def drawinput():

    if not INPUTOPEN:
        return
    width = min(scalesize(620), WINW - (PAD * 4))
    height = scalesize(150)
    x = (WINW - width) // 2
    y = (WINH - height) // 2
    fillrectfast(x, y, width, height, COLOURBG)
    drawrect(x, y, width, height, COLOURTEXT)
    drawtextttf(x + PAD, y + PAD, INPUTTITLE, COLOURTEXT, FONTSIZEROW, FONT)
    boxy = y + PAD + ROWH
    drawrect(x + PAD, boxy, width - (PAD * 2), ROWH, COLOURTEXT)
    shown = textview(INPUTTEXT, FONTSIZEROW, FONT, 0, width - (PAD * 4))
    drawtextttf(x + PAD * 2, boxy + (ROWH // 2) - (FONTSIZEROW // 2), shown, COLOURTEXT, FONTSIZEROW, FONT)
    drawtextttf(x + PAD, y + height - PAD - FONTSIZESTATUS, "Enter to save   Esc to cancel", COLOURMUTED, FONTSIZESTATUS, FONT)


def hiddenattribute(path):

    """Return whether a path carries an explicit filesystem hidden flag."""

    try:
        if int(getattr(os.lstat(path), "st_flags", 0)) & int(getattr(stat, "UF_HIDDEN", 0)):
            return True
    except Exception:
        pass
    try:
        os.getxattr(path, "user.hidden", follow_symlinks=False)
        return True
    except (AttributeError, OSError, TypeError):
        return False


def itemishidden(path, name=None):

    basename = os.path.basename(str(path).rstrip("/")) if name is None else str(name)
    return basename.startswith(".") or hiddenattribute(path)


def propertiesmodeoptions(isdir):

    if isdir:
        return [
            (0o700, "private"),
            (0o555, "read only"),
            (0o755, "read and write"),
            (0o777, "unrestricted"),
        ]
    return [
        (0o600, "private"),
        (0o444, "read only"),
        (0o644, "read and write"),
        (0o755, "executable"),
        (0o666, "unrestricted"),
    ]


def propertiesmodelabel(mode, isdir):

    permissionbits = stat.S_IMODE(int(mode or 0))
    for value, label in propertiesmodeoptions(isdir):
        if value == permissionbits:
            return label
    return "custom"


def drawpropertiesdropdown(rect, text, opened=False):

    x, y, width, height = [int(value) for value in rect]
    fillrectfast(x, y, width, height, COLOURSTATUS)
    drawrect(x, y, width, height, COLOURDIVIDER)
    drawtextttf(x + PAD, y + max(1, (height - FONTSIZEROW) // 2), str(text), COLOURTEXT, FONTSIZEROW, FONT)
    centrex = x + width - max(8, height // 2)
    centrey = y + height // 2
    arrow = max(3, height // 9)
    if opened:
        drawline(centrex - arrow, centrey + arrow // 2, centrex, centrey - arrow // 2, COLOURTEXT)
        drawline(centrex, centrey - arrow // 2, centrex + arrow, centrey + arrow // 2, COLOURTEXT)
    else:
        drawline(centrex - arrow, centrey - arrow // 2, centrex, centrey + arrow // 2, COLOURTEXT)
        drawline(centrex, centrey + arrow // 2, centrex + arrow, centrey - arrow // 2, COLOURTEXT)


def drawpropertiesdropdownmenu(rect, labels, selected=None, hovered=None):

    x, y, width, height = [int(value) for value in rect]
    fillrectfast(x, y, width, height, COLOURSTATUS)
    drawrect(x, y, width, height, COLOURDIVIDER)
    for index, label in enumerate(labels):
        rowy = y + 1 + (index * ROWH)
        if index == hovered:
            drawrect(x + 2, rowy + 1, width - 4, ROWH - 2, COLOURDIVIDER)
        if index == selected:
            fillrectfast(x + 3, rowy + 4, 2, max(1, ROWH - 8), COLOURTEXT)
        drawtextttf(x + PAD, rowy + max(1, (ROWH - FONTSIZEROW) // 2), label, COLOURTEXT, FONTSIZEROW, FONT)


def openproperties(paths):

    global PROPERTIESOPEN, PROPERTIESDATA, PROPERTIESSCROLL, PROPERTIESPATH
    global PROPERTIESISDIR, PROPERTIESMODE, PROPERTIESHIDDEN
    global PROPERTIESDROPDOWN, PROPERTIESDROPDOWNHOVER
    clean = [path for path in paths if path]
    if not clean:
        return
    PROPERTIESOPEN = True
    PROPERTIESSCROLL = 0
    PROPERTIESPATH = clean[0] if len(clean) == 1 else None
    PROPERTIESDROPDOWN = False
    PROPERTIESDROPDOWNHOVER = None
    if len(clean) == 1:
        path = clean[0]
        item = enrichitem(os.path.basename(path.rstrip("/")) or path, path)
        PROPERTIESISDIR = bool(item.get("isdir"))
        PROPERTIESMODE = stat.S_IMODE(int(item.get("mode", 0)))
        PROPERTIESHIDDEN = hiddenattribute(path)
        PROPERTIESDATA = [
            ("name", item.get("name", "")),
            ("type", item.get("type", "")),
            ("location", formatlocation(os.path.dirname(path))),
            ("size", item.get("sizestr", "calculating...") if not item.get("isdir") else "calculating..."),
            ("modified", item.get("modifiedstr", "")),
            ("created", formatfiletime(item.get("created", 0))),
            ("numeric drive", str(driveforpath(path).get("number", 1))),
        ]
        if item.get("islink"):
            target = item.get("linktarget", "")
            PROPERTIESDATA.append(("target", formatlocation(target) if target else "unavailable"))
        if item.get("isdir"):
            PROPERTIESDATA.append(("total size", "calculating..."))
            enqueuejob("size", [path])
    else:
        PROPERTIESISDIR = False
        PROPERTIESMODE = None
        PROPERTIESHIDDEN = False
        PROPERTIESDATA = [
            ("items", str(len(clean))),
            ("location", formatlocation(CWD)),
            ("total size", "calculating..."),
        ]
        enqueuejob("size", clean)
    invalidaterect(0, 0, WINW, WINH)


def closeproperties():

    global PROPERTIESOPEN, PROPERTIESDATA, PROPERTIESPATH, PROPERTIESDROPDOWN
    PROPERTIESOPEN = False
    PROPERTIESDATA = []
    PROPERTIESPATH = None
    PROPERTIESDROPDOWN = False
    invalidaterect(0, 0, WINW, WINH)


def drawproperties():

    global PROPERTIESCONTROLS
    if not PROPERTIESOPEN:
        return
    width = min(scalesize(620), WINW - (PAD * 4))
    height = min(scalesize(520), WINH - (PAD * 4))
    x = (WINW - width) // 2
    y = (WINH - height) // 2
    fillrectfast(x, y, width, height, COLOURBG)
    drawrect(x, y, width, height, COLOURTEXT)
    drawtextttf(x + PAD, y + PAD, "properties", COLOURTEXT, FONTSIZEHEADER, FONT)
    footer_y = y + height - PAD - FONTSIZESTATUS
    controls_top = footer_y - (ROWH * 2) - (PAD * 3) if PROPERTIESPATH else footer_y
    liney = y + PAD + ROWH
    for label, value in PROPERTIESDATA[PROPERTIESSCROLL:]:
        if liney + ROWH >= controls_top:
            break
        drawtextttf(x + PAD, liney, str(label), COLOURMUTED, FONTSIZEROW, FONT)
        shown = textview(str(value), FONTSIZEROW, FONT, 0, width - scalesize(190))
        drawtextttf(x + scalesize(170), liney, shown, COLOURTEXT, FONTSIZEROW, FONT)
        liney += ROWH
    PROPERTIESCONTROLS = {}
    if PROPERTIESPATH:
        liney = controls_top
        valuex = x + scalesize(170)
        valuew = max(scalesize(180), width - scalesize(190))
        drawtextttf(x + PAD, liney, "mode", COLOURMUTED, FONTSIZEROW, FONT)
        moderect = [valuex, liney - scalesize(4), valuew, ROWH]
        drawpropertiesdropdown(
            moderect, propertiesmodelabel(PROPERTIESMODE, PROPERTIESISDIR),
            opened=PROPERTIESDROPDOWN,
        )
        PROPERTIESCONTROLS["mode"] = moderect
        liney += ROWH + PAD
        drawtextttf(x + PAD, liney, "hidden", COLOURMUTED, FONTSIZEROW, FONT)
        box = [valuex, liney, scalesize(16), scalesize(16)]
        drawrect(*box, COLOURTEXT)
        if PROPERTIESHIDDEN:
            drawline(box[0] + 3, box[1] + box[3] // 2, box[0] + box[2] // 2, box[1] + box[3] - 4, COLOURTEXT)
            drawline(box[0] + box[2] // 2, box[1] + box[3] - 4, box[0] + box[2] - 3, box[1] + 3, COLOURTEXT)
        PROPERTIESCONTROLS["hidden"] = [valuex, liney - PAD, valuew, ROWH + PAD]
    drawtextttf(x + PAD, footer_y, "Esc to close", COLOURMUTED, FONTSIZESTATUS, FONT)
    if PROPERTIESDROPDOWN and PROPERTIESCONTROLS.get("mode"):
        options = propertiesmodeoptions(PROPERTIESISDIR)
        popup, _ = gfx.dropdownpopuprect(PROPERTIESCONTROLS["mode"], len(options), WINH, rowheight=ROWH, maximumvisible=8)
        selected = next((index for index, option in enumerate(options) if option[0] == PROPERTIESMODE), None)
        drawpropertiesdropdownmenu(
            popup, [label for _, label in options],
            selected=selected, hovered=PROPERTIESDROPDOWNHOVER,
        )
        PROPERTIESCONTROLS["modepopup"] = popup


def setpathpropertiesmode(path, mode):

    if not path or not permissionpaths(path):
        return False
    try:
        os.chmod(path, int(mode))
        buildtree()
        invalidaterect(0, 0, WINW, WINH)
        return True
    except (OSError, TypeError) as error:
        setstatus(f"could not change mode: {error}", error=True)
        return False


def setpropertiesmode(mode):

    global PROPERTIESMODE, PROPERTIESDROPDOWN
    if not setpathpropertiesmode(PROPERTIESPATH, mode):
        return False
    PROPERTIESMODE = int(mode)
    PROPERTIESDROPDOWN = False
    return True


def setpathpropertieshidden(path, hidden):

    if not path or not permissionpaths(path):
        return False
    try:
        if hidden:
            os.setxattr(path, "user.hidden", b"1", follow_symlinks=False)
        else:
            try:
                os.removexattr(path, "user.hidden", follow_symlinks=False)
            except OSError as error:
                if getattr(error, "errno", None) not in (61, 93):
                    raise
        buildtree()
        invalidaterect(0, 0, WINW, WINH)
        return True
    except (AttributeError, OSError, TypeError) as error:
        setstatus(f"could not change hidden attribute: {error}", error=True)
        return False


def setpropertieshidden(hidden):

    global PROPERTIESHIDDEN
    if not setpathpropertieshidden(PROPERTIESPATH, hidden):
        return False
    PROPERTIESHIDDEN = bool(hidden)
    return True


def propertiespointer(msg):

    global PROPERTIESDROPDOWN, PROPERTIESDROPDOWNHOVER
    if not msg.get("pressed") or int(msg.get("button", 1)) != 1:
        return
    x, y = int(msg.get("x", 0)), int(msg.get("y", 0))
    if PROPERTIESDROPDOWN:
        options = propertiesmodeoptions(PROPERTIESISDIR)
        popup = PROPERTIESCONTROLS.get("modepopup")
        index = gfx.dropdownindexat(x, y, popup, len(options), rowheight=ROWH) if popup else None
        if index is not None:
            setpropertiesmode(options[index][0])
            return
        PROPERTIESDROPDOWN = False
    def inside(rect):
        return bool(rect and rect[0] <= x < rect[0] + rect[2] and rect[1] <= y < rect[1] + rect[3])

    if inside(PROPERTIESCONTROLS.get("mode")):
        PROPERTIESDROPDOWN = True
        PROPERTIESDROPDOWNHOVER = None
    elif inside(PROPERTIESCONTROLS.get("hidden")):
        setpropertieshidden(not PROPERTIESHIDDEN)
    invalidaterect(0, 0, WINW, WINH)


def propertiespointermotion(x, y):

    global PROPERTIESDROPDOWNHOVER
    if not PROPERTIESDROPDOWN:
        return
    options = propertiesmodeoptions(PROPERTIESISDIR)
    popup = PROPERTIESCONTROLS.get("modepopup")
    hovered = gfx.dropdownindexat(x, y, popup, len(options), rowheight=ROWH) if popup else None
    if hovered != PROPERTIESDROPDOWNHOVER:
        PROPERTIESDROPDOWNHOVER = hovered
        invalidaterect(0, 0, WINW, WINH)


def itemdragmotion(x, y):

    global ITEMDRAGSTARTED, ITEMDRAGTARGET
    if ITEMDRAGSTART is None:
        return False
    sx, sy = ITEMDRAGSTART
    if not ITEMDRAGSTARTED and (abs(int(x) - int(sx)) + abs(int(y) - int(sy))) < scalesize(8):
        return False

    cancelpendingrename()

    starting = not ITEMDRAGSTARTED
    ITEMDRAGSTARTED = True

    if starting and WINID and ITEMDRAGPATHS:
        sendws({"op": "DND_GUEST_START", "winid": WINID, "kind": "files", "paths": list(ITEMDRAGPATHS)})
    target = None
    sidelink = sidebarlinkat(x, y)
    if sidelink and sidelink.get("path") and os.path.isdir(sidelink.get("path")):
        target = sidelink.get("path")
    else:
        row = rowat(x, y)
        if row is not None:
            candidate = TREE[row]
            if candidate.get("isdir"):
                target = candidate.get("path")
    if target:
        for source in ITEMDRAGPATHS:
            try:
                if target == source or os.path.commonpath((target, source)) == source:
                    target = None
                    break
            except Exception:
                pass
    ITEMDRAGTARGET = target
    invalidaterect(0, HEADERH, WINW, WINH - HEADERH - STATUSH)
    return True


def finishitemdrag():

    global ITEMDRAGSTART, ITEMDRAGPATHS, ITEMDRAGTARGET, ITEMDRAGSTARTED, ITEMDRAGMODS
    if ITEMDRAGSTARTED and WINID:
        sendws({"op": "DND_GUEST_CLEAR", "winid": WINID})

    if ITEMDRAGSTARTED and ITEMDRAGTARGET and ITEMDRAGPATHS:
        copy = bool(ITEMDRAGMODS.get("ctrl"))
        if not ITEMDRAGMODS.get("shift") and not copy:
            try:
                copy = driveforpath(ITEMDRAGPATHS[0]).get("number") != driveforpath(ITEMDRAGTARGET).get("number")
            except Exception:
                pass
        if ITEMDRAGMODS.get("alt"):
            for source in ITEMDRAGPATHS:
                createlink(source, destination=ITEMDRAGTARGET)
        else:
            enqueuejob("copy" if copy else "move", ITEMDRAGPATHS, ITEMDRAGTARGET)
    ITEMDRAGSTART = None
    ITEMDRAGPATHS = []
    ITEMDRAGTARGET = None
    ITEMDRAGSTARTED = False
    ITEMDRAGMODS = {}
    invalidaterect(0, 0, WINW, WINH)


def drawdragtarget():

    if ITEMDRAGSTARTED and ITEMDRAGTARGET:
        for index, item in enumerate(TREE):
            if item.get("path") == ITEMDRAGTARGET:
                x, y, w, h = rowrect(index)
                drawrect(x + 1, y + 1, w - 2, h - 2, COLOURTEXT)
                break
    if EXTERNALDRAGTARGET:
        for index, item in enumerate(TREE):
            if item.get("path") == EXTERNALDRAGTARGET:
                x, y, w, h = rowrect(index)
                drawrect(x + 1, y + 1, w - 2, h - 2, COLOURTEXT)
                break
    if SIDEBARDRAGGING and SIDEBARDROPINDEX is not None:
        y = HEADERH + (int(SIDEBARDROPINDEX) * ROWH)
        drawline(PAD, y, SIDEBARW - PAD, y, COLOURTEXT)


def externaldroptarget(x, y):

    target = None
    sidelink = sidebarlinkat(x, y)

    if sidelink and sidelink.get("path") and os.path.isdir(sidelink.get("path")):
        target = sidelink.get("path")
    else:
        row = rowat(x, y)
        if row is not None:
            candidate = TREE[row]
            if candidate.get("isdir"):
                target = candidate.get("path")
        elif os.path.isdir(CWD):
            target = CWD

    return target


def externaldragmotion(msg):

    global EXTERNALDRAGTARGET

    if PICKERMODE:
        sendws({"op": "DND_STATUS", "winid": WINID, "accepted": False})
        return

    EXTERNALDRAGTARGET = externaldroptarget(msg.get("x", 0), msg.get("y", 0))
    invalidaterect(0, HEADERH, WINW, WINH - HEADERH - STATUSH)


def externaldragleave():

    global EXTERNALDRAGTARGET

    EXTERNALDRAGTARGET = None
    invalidaterect(0, HEADERH, WINW, WINH - HEADERH - STATUSH)


def externaldrop(msg):

    global EXTERNALDRAGTARGET

    if PICKERMODE:
        EXTERNALDRAGTARGET = None
        return

    target = EXTERNALDRAGTARGET or externaldroptarget(msg.get("x", 0), msg.get("y", 0))
    EXTERNALDRAGTARGET = None

    if not target or not os.path.isdir(target):
        return

    kind = str(msg.get("kind", ""))

    if kind in ("files", "image"):
        paths = msg.get("paths", [])
        if kind == "image" and msg.get("image"):
            paths = [msg.get("image")]
        if not isinstance(paths, list):
            paths = []
        sources = [os.path.abspath(str(path)) for path in paths if os.path.exists(os.path.abspath(str(path)))]
        if sources:
            enqueuejob("copy", sources, target, conflict=JOBCONFLICTDEFAULT)
        return

    if kind in ("text", "html"):
        value = str(msg.get(kind, ""))
        name = "dropped text.html" if kind == "html" else "dropped text.txt"
        output = uniquepath(target, name)
        if not permissionpaths(output):
            return
        try:
            with open(output, "w", encoding="utf-8") as file:
                file.write(value)
            flushfilesystem(output)
            buildtree()
            selectpath(output)
        except PermissionError:
            permissiondenied()
        except Exception as error:
            setstatus(f"drop failed: {error}")


def initfont():

    global FONT, FONTSIZEROW, FONTSIZEHEADER, FONTSIZESTATUS, CONFIRMFONTSIZE

    try:

        # initialise all UI font sizes used by array
        initttffont(FONT, FONTSIZEROW)

        initttffont(FONT, FONTSIZEHEADER)

        initttffont(FONT, FONTSIZESTATUS)

        initttffont(FONT, CONFIRMFONTSIZE)

    except Exception:

        return None


def squarerootscale(w, h, basew, baseh):

    return displayuiscale(w, h, 1.0, basew, baseh)


def scalesize(v):

    global UISCALE

    try:

        out = int(round(float(v) * float(UISCALE)))

    except Exception:

        out = int(v)

    if out < 1:
        out = 1

    return out


def applyuiscale():

    global UISCALE, FONTSIZEHEADER, FONTSIZEROW, FONTSIZESTATUS, CONFIRMFONTSIZE, PAD, ROWH, TITLEH, STATUSH, SIDEBARW, DIVW, TREEINDENT, ARROWW, HEADERGAP, HEADERH, VSCROLL_WIDTH, VSCROLL_MARGIN, VSCROLL_MIN_THUMB
    global HSCROLL_HEIGHT, STATUSMENU_PAD_X, STATUSMENU_PAD_Y, STATUSMENU_ITEM_H, STATUSXSTART, CONFIRMW, CONFIRMH, CONFIRMBTNW, CONFIRMBTNH, CONFIRMPAD, CONFIRMGAP
    global TOOLBARH, EXPLORERTOP, DETAILHEADERH, PROPERTIESW, CONTENTTOP

    UISCALE = displayuiscale(
        SCREENW, SCREENH, uiscalefactor(), BASESCREENW, BASESCREENH)

    FONTSIZEHEADER = scalesize(BASEFONTSIZEHEADER)

    FONTSIZEROW = scalesize(BASEFONTSIZEROW)

    FONTSIZESTATUS = scalesize(BASEFONTSIZESTATUS)

    CONFIRMFONTSIZE = scalesize(BASECONFIRMFONTSIZE)

    CONFIRMW = scalesize(BASECONFIRMW)

    CONFIRMH = scalesize(BASECONFIRMH)

    CONFIRMBTNW = scalesize(BASECONFIRMBTNW)

    CONFIRMBTNH = scalesize(BASECONFIRMBTNH)

    CONFIRMPAD = scalesize(BASECONFIRMPAD)

    CONFIRMGAP = scalesize(BASECONFIRMGAP)

    PAD = scalesize(BASEPAD)

    ROWH = scalesize(BASEROWH)

    TITLEH = scalesize(BASETITLEH)

    STATUSH = scalesize(BASEPICKERSTATUSH if PICKERMODE else BASESTATUSH)

    SIDEBARW = scalesize(BASESIDEBARW)

    # Separators remain one physical pixel, matching the horizontal row lines.
    DIVW = BASEDIVW

    TREEINDENT = scalesize(BASETREEINDENT)

    ARROWW = scalesize(BASEARROWW)

    HEADERGAP = scalesize(BASEHEADERGAP)

    HEADERH = int(TITLEH + (HEADERGAP * 2))

    TOOLBARH = scalesize(BASETOOLBARH)

    EXPLORERTOP = HEADERH + TOOLBARH

    DETAILHEADERH = scalesize(BASEDETAILHEADERH)

    PROPERTIESW = scalesize(BASEPROPERTIESW)

    CONTENTTOP = EXPLORERTOP + (DETAILHEADERH if VIEWMODE == "details" else 0)

    VSCROLL_WIDTH = scalesize(BASEVSCROLL_WIDTH)

    VSCROLL_MARGIN = scalesize(BASEVSCROLL_MARGIN)

    VSCROLL_MIN_THUMB = scalesize(BASEVSCROLL_MIN_THUMB)

    HSCROLL_HEIGHT = scalesize(BASEHSCROLL_HEIGHT)

    STATUSMENU_PAD_X = scalesize(BASESTATUSMENU_PAD_X)

    STATUSMENU_PAD_Y = scalesize(BASESTATUSMENU_PAD_Y)

    STATUSMENU_ITEM_H = scalesize(BASESTATUSMENU_ITEM_H)

    STATUSXSTART = int(PAD + scalesize(14))



# managed graphics functions
def graphicssend(request):

    try:

        sendws(request)

        return True

    except Exception:

        return False


def graphicsconfigure(capabilities):

    return managedconfigure(
        GRAPHICSSTATE,
        capabilities,
        required=("rectangle", "text"),
        cpu=GRAPHICSCPUOVERRIDE or not os.path.isfile(FONT),
    )


def graphicsdamage():

    try:

        if WINID and WINW > 0 and WINH > 0:

            sendws({
                "op": "DAMAGE",
                "winid": WINID,
                "rect": [0, 0, int(WINW), int(WINH)]
            })

    except Exception:

        pass


def graphicsrestorecpu():

    try:

        if BUF is None or WINW <= 0 or WINH <= 0:
            return False

        drawregion(0, 0, int(WINW), int(WINH))
        gfxpresent()
        graphicsdamage()
        return True

    except Exception as e:

        try:
            log(f"CPU graphics restore failed {e}")
        except Exception:
            pass

        graphicsdamage()
        return False


def graphicsdisable(reason, clear=True):

    global GRAPHICSSCENE

    if manageddisable(GRAPHICSSTATE, reason):
        GRAPHICSSCENE = []
        return True

    try:

        log(f"managed graphics disabled {reason}")

    except Exception:

        pass

    GRAPHICSSCENE = []

    try:

        if clear and WINID:

            sendws({"op": "GRAPHICS_CLEAR", "winid": WINID})

    except Exception:

        pass

    graphicsrestorecpu()

    return False


def graphicssuspend():

    global GRAPHICSSCENE

    if not GRAPHICSSTATE.get("available"):
        return False

    GRAPHICSSCENE = []

    if WINID:

        managedclear(GRAPHICSSTATE, graphicssend, WINID)

    graphicsdamage()

    return True


def graphicscommitted(msg):

    try:

        if WINID and int(msg.get("winid", 0)) != int(WINID):
            return False

    except Exception:

        return False

    handled = managedresponse(GRAPHICSSTATE, msg)

    if not GRAPHICSSTATE.get("available"):

        graphicsrestorecpu()

    return handled


def graphicscleared(msg):

    try:

        if WINID and int(msg.get("winid", 0)) != int(WINID):
            return False

    except Exception:

        return False

    return managedresponse(GRAPHICSSTATE, msg)


def graphicsservererror(msg):

    global GRAPHICSSCENE

    wasmanaged = bool(
        GRAPHICSSTATE.get("available")
        or GRAPHICSSTATE.get("active")
        or GRAPHICSSTATE.get("pending")
    )

    managedresponse(GRAPHICSSTATE, msg)

    if wasmanaged and not GRAPHICSSTATE.get("available"):

        GRAPHICSSCENE = []

        try:

            if WINID:

                sendws({"op": "GRAPHICS_CLEAR", "winid": WINID})

        except Exception:

            pass

        graphicsrestorecpu()


# windowserver functions
def connectws():

    global WSOCK

    try:

        # create unix socket
        WSOCK = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

        # connect to windowserver socket
        WSOCK.connect("/.ephemeral/windowserver/accept.sock")

        # non blocking
        WSOCK.setblocking(False)

        # register socket for read/write
        sel.register(WSOCK, selectors.EVENT_READ | selectors.EVENT_WRITE)

    except FileNotFoundError:

        log("windowserver socket not found")

        sys.exit(1)

    except PermissionError:

        log("permission denied connecting to windowserver")

        sys.exit(1)

    except Exception as e:

        log(f"windowserver connection error {e}")

        sys.exit(1)


def sendws(obj):

    global OUTBUF

    try:

        # encode json line
        data = json.dumps(obj).encode("utf-8") + b"\n"

        # queue for send
        OUTBUF += data

    except Exception as e:

        log(f"ipc send error {e}")


def setpointercursor(mode):

    global COLUMNCURSORMODE

    mode = str(mode or "arrow")

    if mode == COLUMNCURSORMODE:
        return

    COLUMNCURSORMODE = mode

    sendws({
        "op": "CURSOR_MODE_SET",
        "winid": WINID,
        "mode": mode
    })


def flushws():

    global OUTBUF

    if not OUTBUF:
        return

    try:

        # send pending data
        sent = WSOCK.send(OUTBUF)

        # trim buffer
        OUTBUF = OUTBUF[sent:]

    except BlockingIOError:

        # socket not ready
        return

    except Exception as e:

        log(f"ipc flush error {e}")

        sys.exit(1)


def recvws():

    global INBUF

    try:

        # receive data
        data = WSOCK.recv(4096)

        if not data:

            log("windowserver disconnected")

            sys.exit(1)

        INBUF += data

    except BlockingIOError:

        return []

    except Exception as e:

        log(f"ipc recv error {e}")

        sys.exit(1)

    lines = []

    while b"\n" in INBUF:

        line, INBUF = INBUF.split(b"\n", 1)

        lines.append(json.loads(line.decode("utf-8")))

    return lines


def handlewsmsg(msg):

    global WINID, BUF, WINW, WINH, SCROLL, RUNNING, SCREENH, SCREENW, NEEDWINDOW
    global CONFIRMOPEN, CONFIRMWAITING, CONFIRMDIALOGID, CONFIRMDIALOGWIN
    global TEXTDIALOGWAITING, TEXTDIALOGID, TEXTDIALOGWIN
    global PICKERTERMINAL

    op = msg.get("op")

    if op == "PICKER_CONFIG":

        try:
            applypickerconfig(msg)
            applyuiscale()
            if NEEDWINDOW:
                NEEDWINDOW = False
                createwindow()
        except Exception as error:
            log(f"picker configuration error {error}")
            pickercancel()
        return

    if op == "GRAPHICS_COMMITTED":

        graphicscommitted(msg)

        return

    if op == "GRAPHICS_CLEARED":

        graphicscleared(msg)

        return

    if op in ("GRAPHICS_BEGUN", "GRAPHICS_COMMAND_ADDED", "GRAPHICS_INFO"):

        return

    if op == "WELCOME":

        fb = msg.get("fb", {})

        try:

            SCREENW = int(fb.get("w", 0))

        except Exception:

            SCREENW = 0

        try:

            SCREENH = int(fb.get("h", 0))

        except Exception:

            SCREENH = 0

        applyuiscale()

        try:

            graphicsconfigure(msg.get("graphics", {}))

        except Exception:

            graphicsconfigure({})

        if PICKERSESSION and PICKERCONFIG is None:
            sendws({"op": "PICKER_ATTACH", "request_id": PICKERSESSION})

        elif NEEDWINDOW:

            NEEDWINDOW = False

            createwindow()

        return

    if op == "FB_SIZE":

        try:

            SCREENW = int(msg.get("w", 0))

        except Exception:

            SCREENW = 0

        try:

            SCREENH = int(msg.get("h", 0))

        except Exception:

            SCREENH = 0

        applyuiscale()

        if NEEDWINDOW and (not PICKERSESSION or PICKERCONFIG is not None):

            NEEDWINDOW = False

            createwindow()

        if BUF and WINW and WINH:

            initfont()

            layout()

            invalidaterect(0, 0, WINW, WINH)

        return

    if op == "WINDOW_CREATED":

        WINID = msg.get("winid")

        BUF = msg.get("buffer")

        WINW = msg.get("w")

        WINH = msg.get("h")

        # bind graphics to this window's backing buffer
        initbuffer(BUF, WINW, WINH)

        applyuiscale()

        initfont()

        # first paint
        invalidaterect(0, 0, WINW, WINH)

        # compute layout for this window size
        layout()

        # build sidebar links
        buildsidebarlinks()

        try:

            if LAUNCHCWD:

                setcwd(LAUNCHCWD)

            else:

                username = getusername()

                setcwd(f"/master/{username}")

        except Exception:

            setcwd("/")

        # build initial view state
        buildtree()

        buildactions()

        return

    if op in ("DND_ENTER", "DND_MOVE", "DND_DROP_PENDING"):

        externaldragmotion(msg)
        return

    if op == "DND_LEAVE":

        externaldragleave()
        return

    if op == "DND_DROP":

        externaldrop(msg)
        return

    if op == "WINDOW_MAPPED":

        # remap should not rebind graphics (can desync stride if WINW/WINH are stale)
        if msg.get("winid") == WINID:
            invalidaterect(0, 0, WINW, WINH)

        return

    if op == "WINDOW_DESTROYED":

        if msg.get("winid") == WINID:
            RUNNING = False
        return

    if op == "QUIT":

        RUNNING = False
        return

    if op == "DIALOG_CREATED":

        if CONFIRMWAITING and str(msg.get("dialog_id", "")) == str(CONFIRMDIALOGID or ""):
            CONFIRMDIALOGWIN = msg.get("winid")

        if TEXTDIALOGWAITING and str(msg.get("dialog_id", "")) == str(TEXTDIALOGID or ""):
            TEXTDIALOGWIN = msg.get("winid")

        return

    if op == "DIALOG_RESULT":

        if CONFIRMWAITING and str(msg.get("dialog_id", "")) == str(CONFIRMDIALOGID or ""):
            confirmdo(str(msg.get("result", "cancel")))

        elif TEXTDIALOGWAITING and str(msg.get("dialog_id", "")) == str(TEXTDIALOGID or ""):
            result = str(msg.get("result", "cancel"))
            action = TEXTDIALOGACTION
            payload = TEXTDIALOGPAYLOAD
            value = msg.get("value", TEXTDIALOGINITIAL)
            closetextdialog()
            if result == "ok":
                committextdialog(action, payload, value)

        return

    if op == "RESIZED":

        onresized(msg)
        return

    if op == "CLOSE":

        if msg.get("winid") not in (None, WINID):
            return

        sendws({"op": "CLOSE_ACK", "pid": os.getpid()})

        if PICKERMODE:
            pickercancel()
        else:
            RUNNING = False

        return

    if op == "ERROR":

        code = str(msg.get("code", ""))

        if PICKERMODE and code.startswith("picker_"):
            if code == "picker_result_invalid":
                PICKERTERMINAL = False
            setstatus("the selected location is no longer available", error=True)

        # Compatibility with a window server that predates CREATE_DIALOG: keep
        # the original in-window confirmation available instead of losing the
        # destructive-action prompt.
        if CONFIRMWAITING and (
            code.startswith("dialog_")
            or (code == "unknown_op" and str(msg.get("detail", "")) == "CREATE_DIALOG")
        ):
            CONFIRMWAITING = False
            CONFIRMDIALOGID = None
            CONFIRMDIALOGWIN = None
            CONFIRMOPEN = True
            invalidaterect(0, 0, WINW, WINH)

        if TEXTDIALOGWAITING and (
            code.startswith("dialog_")
            or (code == "unknown_op" and str(msg.get("detail", "")) == "CREATE_DIALOG")
        ):
            title = TEXTDIALOGTITLE
            initial = TEXTDIALOGINITIAL
            action = TEXTDIALOGACTION
            payload = TEXTDIALOGPAYLOAD
            closetextdialog()
            openinput(title, initial, action, payload)

        try:

            if code.startswith("graphics_"):

                graphicsservererror(msg)

        except Exception:

            pass

        log(f"windowserver error code={msg.get('code')} detail={msg.get('detail')}")

        return


def createwindow():

    try:

        request = {
            "op": "CREATE_WINDOW",
            "role": APPROLE,
            "title": APPNAME,
            "current": formatlocation(CWD),
            "path": f"{ARRAYPATH}",
            "w": scalesize(BASEWINW),
            "h": scalesize(BASEWINH),
            "x": 100,
            "y": 100,
            "pid": os.getpid(),
            "drop_types": [] if PICKERMODE else ["files", "text", "html", "image"],
        }

        if PICKERMODE:
            request["picker_session"] = PICKERSESSION
            request["theme"] = "dialog"

        sendws(request)

    except Exception as e:

        log(f"create window error {e}")

        sys.exit(1)


def mapwindow():

    try:

        sendws({
            "op": "MAP",
            "winid": WINID
        })

    except Exception as e:

        log(f"map window error {e}")

        sys.exit(1)


def requestredraw():

    sendws({
        "op": "DAMAGE",
        "winid": WINID,
        "rect": [0, 0, WINW, WINH]
    })


def onresized(msg):

    global WINW, WINH, BUF, SCROLL

    # remove the old managed scene before changing the backing-buffer geometry
    graphicssuspend()

    WINW = msg.get("w")

    WINH = msg.get("h")

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

    initbuffer(BUF, WINW, WINH)

    initfont()

    layout()

    maxscroll = max(0, len(TREE) - VISIBLECOUNT)

    SCROLL = clamp(SCROLL, 0, maxscroll)

    invalidaterect(0, 0, WINW, WINH)


# rubbish functions
def rubbishrootlist():

    items = []

    indexfile = "/.rubbish/index.txt"

    try:

        if not os.path.exists("/.rubbish"):
            os.makedirs("/.rubbish", exist_ok=True)

        if not os.path.exists(indexfile):
            with open(indexfile, "w") as f:
                f.write("id\tname\torigpath\tisdir\tsize\tdeletedts\tuser\n")

        with open(indexfile, "r") as f:
            lines = f.read().splitlines()

    except Exception as e:

        log(f"rubbishrootlist error {e}")

        return []

    if not lines:
        return []

    try:

        rows = lines[1:]

    except Exception:

        rows = []

    dirgroups = {}
    filegroups = {}

    for row in rows:

        if not row:
            continue

        try:

            parts = row.split("\t")

        except Exception:

            continue

        if len(parts) < 7:
            continue

        rid, name, origpath, isdirraw, size, deletedts, user = parts[:7]

        try:

            isdir = str(isdirraw).strip().lower() in ("1", "true", "yes", "dir", "folder")

        except Exception:

            isdir = False

        try:

            ts = float(deletedts)

        except Exception:

            ts = 0.0

        if isdir:

            if name not in dirgroups:
                dirgroups[name] = []

            dirgroups[name].append((ts, rid))

        else:

            if name not in filegroups:
                filegroups[name] = []

            filegroups[name].append((ts, rid))

    for name in sorted(dirgroups.keys(), key=str.casefold):

        tslist = sorted(dirgroups[name], key=lambda x: x[0], reverse=True)

        for ts, rid in tslist:

            items.append({
                "name": name,
                "path": f"/.rubbish/{rid}",
                "isdir": True
            })

    for name in sorted(filegroups.keys(), key=str.casefold):

        tslist = sorted(filegroups[name], key=lambda x: x[0], reverse=True)

        for ts, rid in tslist:

            items.append({
                "name": name,
                "path": f"/.rubbish/{rid}",
                "isdir": False
            })

    return items


def isrubbish(path):

    try:

        p = normalisepath(path)

    except Exception:

        return False

    try:

        rubbishroot = os.path.abspath("/.rubbish")

    except Exception:

        rubbishroot = "/.rubbish"

    try:

        target = os.path.abspath(p)

    except Exception:

        target = p

    try:

        return os.path.commonpath([target, rubbishroot]) == rubbishroot

    except Exception:

        return False


def rubbishhas():

    rubbishroot = "/.rubbish"

    try:

        entries = os.listdir(rubbishroot)

    except Exception:

        entries = []

    for name in entries:

        if name == "index.txt":
            continue

        return True

    return False


def emptyrubbish():

    rubbishroot = "/.rubbish"

    indexfile = "/.rubbish/index.txt"

    try:

        entries = os.listdir(rubbishroot)

    except Exception:

        entries = []

    mutationpaths = [indexfile]

    for name in entries:

        if name != "index.txt":
            mutationpaths.append(f"/.rubbish/{name}")

    if not permissionpaths(mutationpaths):
        return False

    for name in entries:

        if name == "index.txt":
            continue

        payload = f"/.rubbish/{name}"

        try:

            if os.path.isdir(payload):
                shutil.rmtree(payload)

            else:
                os.remove(payload)

        except PermissionError:

            permissiondenied()
            return False

    try:

        with open(indexfile, "r") as f:
            lines = f.read().splitlines()

    except Exception:

        lines = []

    try:

        header = lines[0] if lines else ""

    except Exception:

        header = ""

    if header:
        out = header + "\n"
    else:
        out = ""

    try:

        with open(indexfile, "w") as f:
            f.write(out)

    except PermissionError:

        permissiondenied()
        return False

    flushfilesystem(rubbishroot, indexfile)

    return True


def restoreitem(path, record=True):

    global SELECTED

    if path is None:
        return None

    try:

        target = os.path.abspath(str(path))

    except Exception:

        return

    rubbishroot = os.path.abspath("/.rubbish")

    try:

        if os.path.commonpath([target, rubbishroot]) != rubbishroot:
            return None

    except Exception:

        return None

    rid = None

    try:

        parts = target.strip(os.sep).split(os.sep)

        if len(parts) >= 2 and parts[0] == ".rubbish":
            rid = parts[1]

    except Exception:

        rid = None

    if not rid:
        return None

    recordpath = None

    try:

        for record in rubbishrecords():

            if record.get("id") == rid:

                recordpath = record.get("origpath")

                break

    except Exception:

        recordpath = None

    if recordpath is None or not permissionpaths(creationmutationpaths(recordpath)):
        return None

    try:

        restorefromrubbishrid(rid)

    except PermissionError:

        permissiondenied()
        return None

    undoitem = None

    if recordpath is not None and os.path.exists(recordpath):

        flushfilesystem(recordpath, "/.rubbish", "/.rubbish/index.txt")

        undoitem = {
            "rid": rid,
            "path": recordpath,
        }

    if record and undoitem is not None:

        pushundo({
            "type": "restore",
            "items": [undoitem],
        })

    buildtree()

    if SELECTED is not None:
        SELECTED = None

    return undoitem


# undo functions
def undoavailable():

    return len(UNDO) > 0


def redoavailable():

    return len(REDO) > 0


def trimundostack():

    while len(UNDO) > UNDOLIMIT:

        UNDO.pop(0)


def pushundo(op):

    global REDO

    if not op:
        return

    UNDO.append(op)

    trimundostack()

    REDO = []

    buildactions()

    invalidaterect(0, WINH - STATUSH, WINW, STATUSH)


def refreshafterundo(paths=None):

    buildtree()

    chosen = None

    try:

        for p in paths or []:

            if p is not None and os.path.exists(p):
                chosen = p
                break

    except Exception:

        chosen = None

    if chosen is not None:

        selectpath(chosen)

        scrolltopath(chosen)

    else:

        clearselection()


def removepath(path):

    try:

        target = os.path.abspath(str(path))

    except Exception:

        return True

    if not permissionpaths(target):
        return False

    try:

        if not os.path.exists(target):
            return True

        if os.path.isdir(target):
            shutil.rmtree(target)
        else:
            os.remove(target)

        flushfilesystem(target)

        return True

    except PermissionError:

        permissiondenied()
        return False

    except Exception:

        return False


def copypath(src, dst):

    try:

        source = os.path.abspath(str(src))

        target = os.path.abspath(str(dst))

        if not permissionpaths(creationmutationpaths(target)):
            return False

        if not os.path.exists(source):
            return False

        if os.path.exists(target):
            return False

        parent = os.path.dirname(target)

        if parent and not os.path.exists(parent):
            os.makedirs(parent, exist_ok=True)

        if os.path.isdir(source):
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)

        flushfilesystem(source, target)

        return True

    except PermissionError:

        permissiondenied()
        return False

    except Exception:

        return False


def movepath(src, dst):

    try:

        source = os.path.abspath(str(src))

        target = os.path.abspath(str(dst))

        if not permissionpaths(source, creationmutationpaths(target)):
            return False

        if not os.path.exists(source):
            return False

        if os.path.exists(target):
            return False

        parent = os.path.dirname(target)

        if parent and not os.path.exists(parent):
            os.makedirs(parent, exist_ok=True)

        shutil.move(source, target)

        flushfilesystem(source, target)

        return True

    except PermissionError:

        permissiondenied()
        return False

    except Exception:

        return False


def renamepath(src, dst):

    try:

        source = os.path.abspath(str(src))

        target = os.path.abspath(str(dst))

        if not permissionpaths(source, creationmutationpaths(target)):
            return False

        if not os.path.exists(source):
            return False

        if os.path.exists(target):
            return False

        parent = os.path.dirname(target)

        if parent and not os.path.exists(parent):
            os.makedirs(parent, exist_ok=True)

        os.rename(source, target)

        flushfilesystem(source, target)

        return True

    except PermissionError:

        permissiondenied()
        return False

    except Exception:

        return False


def rubbishrecords():

    records = []

    try:

        with open("/.rubbish/index.txt", "r") as f:
            lines = f.read().splitlines()

    except Exception:

        return records

    for line in lines[1:]:

        if not line:
            continue

        try:

            parts = line.split("\t")

        except Exception:

            continue

        if len(parts) < 7:
            continue

        records.append({
            "id": parts[0],
            "name": parts[1],
            "origpath": parts[2],
            "isdir": parts[3],
            "size": parts[4],
            "deletedts": parts[5],
            "user": parts[6],
        })

    return records


def rubbishids():

    return set([r.get("id") for r in rubbishrecords()])


def newrubbishitems(beforeids, paths):

    items = []

    targets = set()

    for p in paths or []:

        try:

            targets.add(os.path.abspath(str(p)))

        except Exception:

            pass

    for record in rubbishrecords():

        try:

            rid = record.get("id")

            orig = os.path.abspath(str(record.get("origpath", "")))

        except Exception:

            continue

        if rid in beforeids:
            continue

        if orig not in targets:
            continue

        items.append({
            "rid": rid,
            "path": orig,
        })

    return items


def trashpathsforundo(paths):

    before = rubbishids()

    done = []

    if not permissionpaths(paths or []):
        return done

    for p in paths or []:

        try:

            target = os.path.abspath(str(p))

        except Exception:

            continue

        if not os.path.exists(target):
            continue

        try:

            storepaths([target])

            flushfilesystem(target, "/.rubbish", "/.rubbish/index.txt")

            done.append(target)

        except Exception:

            pass

    return newrubbishitems(before, done)


def historypaths(op):

    paths = []

    try:

        kind = op.get("type")

        items = op.get("items", [])

    except Exception:

        return paths

    if kind == "rename":

        paths.append(op.get("old"))

        paths.append(op.get("new"))

        return [p for p in paths if p is not None]

    for item in items:

        try:

            if kind == "move":

                paths.append(item.get("src"))

                paths.append(item.get("dst"))

            elif kind == "copy":

                paths.append(item.get("dst"))

            else:

                paths.extend(creationmutationpaths(item.get("path")))

        except Exception:

            continue

    return [p for p in paths if p is not None]


def applyundo(op):

    try:

        kind = op.get("type")

    except Exception:

        return False

    changed = False

    if kind == "create":

        for item in op.get("items", []):

            if removepath(item.get("path")):
                changed = True

        refreshafterundo([])

        return changed

    if kind == "rename":

        changed = renamepath(op.get("new"), op.get("old"))

        refreshafterundo([op.get("old")])

        return changed

    if kind == "copy":

        for item in op.get("items", []):

            if removepath(item.get("dst")):
                changed = True

        refreshafterundo([])

        return changed

    if kind == "move":

        for item in reversed(op.get("items", [])):

            if movepath(item.get("dst"), item.get("src")):
                changed = True

        refreshafterundo([i.get("src") for i in op.get("items", [])])

        return changed

    if kind == "delete":

        for item in op.get("items", []):

            try:

                restorefromrubbishrid(item.get("rid"))

                if os.path.exists(item.get("path")):

                    flushfilesystem(item.get("path"), "/.rubbish", "/.rubbish/index.txt")

                    changed = True

            except PermissionError:

                permissiondenied()
                return False

            except Exception:

                pass

        refreshafterundo([i.get("path") for i in op.get("items", [])])

        return changed

    if kind == "restore":

        items = trashpathsforundo([i.get("path") for i in op.get("items", [])])

        if items:

            op["items"] = items

            changed = True

        refreshafterundo([])

        return changed

    return False


def applyredo(op):

    try:

        kind = op.get("type")

    except Exception:

        return False

    changed = False

    if kind == "create":

        for item in op.get("items", []):

            try:

                path = os.path.abspath(str(item.get("path")))

                if os.path.exists(path):
                    continue

                if not permissionpaths(creationmutationpaths(path)):
                    return False

                parent = os.path.dirname(path)

                if parent and not os.path.exists(parent):
                    os.makedirs(parent, exist_ok=True)

                if item.get("isdir"):
                    os.mkdir(path)
                else:
                    with open(path, "x"):
                        pass

                flushfilesystem(path)

                changed = True

            except PermissionError:

                permissiondenied()
                return False

            except Exception:

                pass

        refreshafterundo([i.get("path") for i in op.get("items", [])])

        return changed

    if kind == "rename":

        changed = renamepath(op.get("old"), op.get("new"))

        refreshafterundo([op.get("new")])

        return changed

    if kind == "copy":

        for item in op.get("items", []):

            if copypath(item.get("src"), item.get("dst")):
                changed = True

        refreshafterundo([i.get("dst") for i in op.get("items", [])])

        return changed

    if kind == "move":

        for item in op.get("items", []):

            if movepath(item.get("src"), item.get("dst")):
                changed = True

        refreshafterundo([i.get("dst") for i in op.get("items", [])])

        return changed

    if kind == "delete":

        items = trashpathsforundo([i.get("path") for i in op.get("items", [])])

        if items:

            op["items"] = items

            changed = True

        refreshafterundo([])

        return changed

    if kind == "restore":

        for item in op.get("items", []):

            try:

                restorefromrubbishrid(item.get("rid"))

                if os.path.exists(item.get("path")):

                    flushfilesystem(item.get("path"), "/.rubbish", "/.rubbish/index.txt")

                    changed = True

            except PermissionError:

                permissiondenied()
                return False

            except Exception:

                pass

        refreshafterundo([i.get("path") for i in op.get("items", [])])

        return changed

    return False


def undoaction():

    if not UNDO:
        return

    op = UNDO[-1]

    if not permissionpaths(historypaths(op)):
        return

    op = UNDO.pop()

    if applyundo(op):

        REDO.append(op)

    else:

        UNDO.append(op)

    buildactions()

    invalidaterect(0, WINH - STATUSH, WINW, STATUSH)


def redoaction():

    if not REDO:
        return

    op = REDO[-1]

    if not permissionpaths(historypaths(op)):
        return

    op = REDO.pop()

    if applyredo(op):

        UNDO.append(op)

        trimundostack()

    else:

        REDO.append(op)

    buildactions()

    invalidaterect(0, WINH - STATUSH, WINW, STATUSH)


# scrollbar functions
def walktree(path, depth):

    items = listdir(path)

    for item in items:

        fullpath = item["path"]

        isdir = item["isdir"]

        try:

            haskids = False

            expanded = False

            if isdir:

                try:

                    haskids = haschildren(fullpath)

                except Exception:

                    haskids = False

                try:

                    expanded = fullpath in EXPANDED

                except Exception:

                    expanded = False

        except Exception:

            haskids = False

            expanded = False

        treeitem = dict(item)
        treeitem.update({
            "depth": depth,
            "haskids": haskids,
            "expanded": expanded,
        })
        TREE.append(treeitem)

        if isdir and expanded:
            walktree(fullpath, depth + 1)


def verticalneeded():

    try:

        return len(TREE) > VISIBLECOUNT

    except Exception:

        return False


def horizontalneeded():

    try:

        if VIEWMODE == "details":
            return False

        return CONTENTWIDTH > VISIBLEWIDTH

    except Exception:

        return False


def hscrollvisiblewidth():

    try:

        w = int(VISIBLEWIDTH)

    except Exception:

        w = 0

    w = w - int(PAD) - int(ARROWW) - (int(MAXDEPTH) * int(TREEINDENT))

    try:

        if w < 0:
            w = 0

    except Exception:

        w = 0

    return w


def computecontentwidth():

    global CONTENTWIDTH, MAXDEPTH

    CONTENTWIDTH = 0
    MAXDEPTH = 0

    try:

        for item in TREE:

            try:

                depth = int(item.get("depth", 0))

            except Exception:

                depth = 0


            if depth > MAXDEPTH:
                MAXDEPTH = depth

            try:

                name = str(item.get("displayname", item.get("name", "")))

            except Exception:

                name = ""

            try:

                namew = measuretext(name, FONTSIZEROW, FONT)

            except Exception:

                namew = 0

            try:

                if namew <= 0:
                    namew = len(name) * max(1, (FONTSIZEROW // 2))

            except Exception:

                namew = len(name) * max(1, (FONTSIZEROW // 2))


            # width inside the main pane (independent of HSCROLL)
            w = PAD + ARROWW + (depth * TREEINDENT) + int(namew)

            if w > CONTENTWIDTH:
                CONTENTWIDTH = w

    except Exception:

        CONTENTWIDTH = 0

    if VIEWMODE == "details":
        try:
            CONTENTWIDTH = max(CONTENTWIDTH, sum(int(COLUMNWIDTHS.get(column, 100)) for column in DETAILCOLUMNS))
        except Exception:
            pass


def vscrolltrackgeometry():

    try:

        if not verticalneeded():
            return 0, 0, 0, 0

        track_x = SIDEBARW + DIVW + VISIBLEWIDTH

        track_y = CONTENTTOP

        track_h = WINH - CONTENTTOP - STATUSH

        track_w = VSCROLL_WIDTH

        if track_h < 0:
            track_h = 0

        return int(track_x), int(track_y), int(track_w), int(track_h)

    except Exception:

        return 0, 0, 0, 0


def hscrolltrackgeometry():

    try:

        if not horizontalneeded():
            return 0, 0, 0, 0

        track_x = SIDEBARW + DIVW
        track_y = WINH - STATUSH - HSCROLL_HEIGHT
        track_w = VISIBLEWIDTH
        track_h = HSCROLL_HEIGHT

        if track_w < 0:
            track_w = 0

        return int(track_x), int(track_y), int(track_w), int(track_h)

    except Exception:

        return 0, 0, 0, 0


def vscrollthumbgeometry():

    try:

        track_x, track_y, track_w, track_h = vscrolltrackgeometry()

        if track_w <= 0 or track_h <= 0:
            return None

        total = len(TREE)

        visible = max(1, VISIBLECOUNT)

        maxscroll = max(0, total - visible)

        if maxscroll <= 0:
            return ("thumb", track_x, track_y, track_w, track_h, track_y, track_h)

        try:

            thumb_h = int(track_h * (visible / float(total)))

        except Exception:

            thumb_h = VSCROLL_MIN_THUMB

        if thumb_h < VSCROLL_MIN_THUMB:
            thumb_h = VSCROLL_MIN_THUMB

        if thumb_h > track_h:
            thumb_h = track_h

        if track_h - thumb_h <= 0:
            thumb_y = track_y

        else:

            try:

                frac = SCROLL / float(maxscroll)

            except Exception:

                frac = 0.0

            if frac < 0.0:
                frac = 0.0

            if frac > 1.0:
                frac = 1.0

            thumb_y = int(track_y + frac * (track_h - thumb_h))

        return ("thumb", track_x, track_y, track_w, track_h, thumb_y, thumb_h)

    except Exception:

        return None


def hscrollthumbgeometry():

    try:

        track_x, track_y, track_w, track_h = hscrolltrackgeometry()

        if track_w <= 0:
            return None

        maxscroll = max(0, CONTENTWIDTH - hscrollvisiblewidth())

        if maxscroll <= 0:
            return ("thumb", track_x, track_y, track_w, track_h, track_x, track_w)

        try:

            thumb_w = int(track_w * (hscrollvisiblewidth() / float(CONTENTWIDTH)))

        except Exception:

            thumb_w = HSCROLL_MIN_THUMB

        if thumb_w < HSCROLL_MIN_THUMB:
            thumb_w = HSCROLL_MIN_THUMB

        if thumb_w > track_w:
            thumb_w = track_w

        frac = HSCROLL / float(maxscroll)

        frac = clamp(frac, 0.0, 1.0)

        thumb_x = int(track_x + frac * (track_w - thumb_w))

        return ("thumb", track_x, track_y, track_w, track_h, thumb_x, thumb_w)

    except Exception:

        return None


def vscrollclamp():

    global SCROLL

    try:

        maxscroll = max(0, len(TREE) - VISIBLECOUNT)

        SCROLL = clamp(SCROLL, 0, maxscroll)

    except Exception:

        SCROLL = 0


def hscrollclamp():

    global HSCROLL

    try:

        maxscroll = max(0, CONTENTWIDTH - hscrollvisiblewidth())

        HSCROLL = clamp(HSCROLL, 0, maxscroll)

    except Exception:

        HSCROLL = 0


def vscrollclick(x, y):

    global VSCROLL_DRAG_CURSOR_OFFSET

    try:

        geo = vscrollthumbgeometry()

        if geo is None:
            return None

        _, track_x, track_y, track_w, track_h, thumb_y, thumb_h = geo

        if x < track_x or x > (track_x + track_w):
            return None

        if y < track_y or y > (track_y + track_h):
            return None

        if y >= thumb_y and y <= (thumb_y + thumb_h):

            try:

                VSCROLL_DRAG_CURSOR_OFFSET = int(y - thumb_y)

            except Exception:

                VSCROLL_DRAG_CURSOR_OFFSET = 0

            return "thumb"

        if y < thumb_y:
            return "pageup"

        return "pagedown"

    except Exception:

        return None


def hscrollclick(x, y):

    global HSCROLL_DRAG_CURSOR_OFFSET

    try:

        geo = hscrollthumbgeometry()

        if geo is None:
            return None

        _, track_x, track_y, track_w, track_h, thumb_x, thumb_w = geo

        if y < track_y or y > (track_y + track_h):
            return None

        if x < track_x or x > (track_x + track_w):
            return None

        if x >= thumb_x and x <= (thumb_x + thumb_w):

            HSCROLL_DRAG_CURSOR_OFFSET = int(x - thumb_x)
            return "thumb"

        if x < thumb_x:
            return "pageleft"

        return "pageright"

    except Exception:

        return None


# header functions
def headereditbegin():

    global HEADEREDIT, HEADEREDITTEXT, HEADERCARETPOS, HEADERSELSTART, HEADERSELEND

    HEADEREDIT = True

    HEADEREDITTEXT = formatlocation(CWD)

    HEADERCARETPOS = len(HEADEREDITTEXT)

    HEADERSELSTART = None

    HEADERSELEND = None

    # redraw header
    invalidaterect(0, 0, WINW, HEADERH)


def headereditend(cancel=False):

    global HEADEREDIT, HEADEREDITTEXT, HEADERCARETPOS, HEADERSELSTART, HEADERSELEND

    if cancel:

        HEADEREDIT = False

        HEADEREDITTEXT = ""

        HEADERCARETPOS = 0

        HEADERSELSTART = None

        HEADERSELEND = None

        # redraw header
        invalidaterect(0, 0, WINW, HEADERH)

        return

    # commit and navigate; the editable location includes its numeric drive
    p = str(HEADEREDITTEXT).strip()

    HEADEREDIT = False

    HEADEREDITTEXT = ""

    HEADERCARETPOS = 0

    HEADERSELSTART = None

    HEADERSELEND = None

    setcwd(p)


def headerclearselection():

    global HEADERSELSTART, HEADERSELEND

    HEADERSELSTART = None

    HEADERSELEND = None

    # redraw header
    invalidaterect(0, 0, WINW, HEADERH)


def headerhasselection():

    try:

        if HEADERSELSTART is None or HEADERSELEND is None:
            return False

        if HEADERSELSTART == HEADERSELEND:
            return False

        return True

    except Exception:

        return False


def headernormsel():

    try:

        if HEADERSELSTART is None or HEADERSELEND is None:
            return None, None

        a = int(HEADERSELSTART)

        b = int(HEADERSELEND)

        if a < 0:
            a = 0

        if b < 0:
            b = 0

        if a > b:
            a, b = b, a

        a = clamp(a, 0, len(HEADEREDITTEXT))

        b = clamp(b, 0, len(HEADEREDITTEXT))

        return a, b

    except Exception:

        return None, None


def headerdeleteselection():

    global HEADEREDITTEXT, HEADERCARETPOS

    if not headerhasselection():
        return

    a, b = headernormsel()

    if a is None:
        return

    HEADEREDITTEXT = HEADEREDITTEXT[:a] + HEADEREDITTEXT[b:]

    HEADERCARETPOS = a

    headerclearselection()


def headerinserttext(s):

    global HEADEREDITTEXT, HEADERCARETPOS

    if s is None:
        return

    text = str(s)

    if text == "":
        return

    if headerhasselection():
        headerdeleteselection()

    pos = clamp(HEADERCARETPOS, 0, len(HEADEREDITTEXT))

    HEADEREDITTEXT = HEADEREDITTEXT[:pos] + text + HEADEREDITTEXT[pos:]

    HEADERCARETPOS = pos + len(text)

    # redraw header
    invalidaterect(0, 0, WINW, HEADERH)


def headerbackspace():

    global HEADEREDITTEXT, HEADERCARETPOS

    if headerhasselection():

        headerdeleteselection()

        return

    if HEADERCARETPOS <= 0:
        return

    pos = clamp(HEADERCARETPOS, 0, len(HEADEREDITTEXT))

    HEADEREDITTEXT = HEADEREDITTEXT[:pos - 1] + HEADEREDITTEXT[pos:]

    HEADERCARETPOS = pos - 1

    # redraw header
    invalidaterect(0, 0, WINW, HEADERH)


def headerdelete():

    global HEADEREDITTEXT, HEADERCARETPOS

    if headerhasselection():

        headerdeleteselection()

        return

    pos = clamp(HEADERCARETPOS, 0, len(HEADEREDITTEXT))

    if pos >= len(HEADEREDITTEXT):
        return

    HEADEREDITTEXT = HEADEREDITTEXT[:pos] + HEADEREDITTEXT[pos + 1:]

    # redraw header
    invalidaterect(0, 0, WINW, HEADERH)


def headerselectall():

    global HEADERSELSTART, HEADERSELEND, HEADERCARETPOS

    HEADERSELSTART = 0

    HEADERSELEND = len(HEADEREDITTEXT)

    HEADERCARETPOS = len(HEADEREDITTEXT)

    # redraw header
    invalidaterect(0, 0, WINW, HEADERH)


def headerselectwordat(idx):

    global HEADERSELSTART, HEADERSELEND, HEADERCARETPOS

    try:

        i = clamp(int(idx), 0, len(HEADEREDITTEXT))

    except Exception:

        i = 0

    # treat "word" as a path segment between slashes
    left = i

    right = i

    while left > 0 and HEADEREDITTEXT[left - 1] != "/":
        left -= 1

    while right < len(HEADEREDITTEXT) and HEADEREDITTEXT[right] != "/":
        right += 1

    HEADERSELSTART = left

    HEADERSELEND = right

    HEADERCARETPOS = right

    # redraw header
    invalidaterect(0, 0, WINW, HEADERH)


def headercaretfromx(x, textx, viewstart):

    try:

        localx = int(x) - int(textx)

        if localx <= 0:
            return viewstart

    except Exception:

        return viewstart

    try:

        # walk forward measuring until we pass localx
        shown = HEADEREDITTEXT[viewstart:]

        acc = 0

        for i, ch in enumerate(shown):

            w = measuretext(ch, FONTSIZEHEADER, FONT)

            if w <= 0:
                w = max(1, (FONTSIZEHEADER // 2))

            if (acc + (w // 2)) >= localx:
                return viewstart + i

            acc += w

        return viewstart + len(shown)

    except Exception:

        return viewstart


def headercomputeview(availw):

    try:

        full = HEADEREDITTEXT

        caret = clamp(HEADERCARETPOS, 0, len(full))

    except Exception:

        return 0, full, False

    if availw <= 10:
        return 0, "", False

    fullw = measuretext(full, FONTSIZEHEADER, FONT)

    if fullw <= availw:
        return 0, full, False

    try:

        ell = "…"

        ellw = measuretext(ell, FONTSIZEHEADER, FONT)

        if ellw <= 0:
            ellw = max(8, (FONTSIZEHEADER // 2))

        limit = availw - int(ellw)

        if limit < 1:
            limit = 1

    except Exception:

        ellw = max(8, (FONTSIZEHEADER // 2))

        limit = max(1, availw - int(ellw))

    try:

        start = clamp(caret - 1, 0, len(full))

    except Exception:

        start = 0

    # ensure the visible substring fits, without pushing start past caret
    while start < len(full):

        try:

            s = full[start:]

            w = measuretext(s, FONTSIZEHEADER, FONT)

        except Exception:

            w = limit + 1

        if w <= limit:
            break

        if start >= caret:
            break

        start += 1

    # if caret is left of view, bring view back to caret
    if caret < start:
        start = caret

    # now expand left as much as we can to show more context
    while start > 0:

        try:

            s = full[start - 1:]

            w = measuretext(s, FONTSIZEHEADER, FONT)

        except Exception:

            break

        if w > limit:
            break

        start -= 1

    try:

        shown = full[start:]

        prefix = (start > 0)

        return start, shown, prefix

    except Exception:

        return 0, str(HEADEREDITTEXT), False


def headerrepeat():

    global HEADERHELD, HEADERHELDDOWNMS, HEADERHELDLASTMS, HEADERCARETPOS

    if not HEADEREDIT:
        return

    if HEADERHELD is None:
        return

    t = nowms()

    if int(t - int(HEADERHELDDOWNMS)) < int(HEADERREPEATDELAYMS):
        return


    if int(t - int(HEADERHELDLASTMS)) < int(HEADERREPEATMS):
        return

    key = str(HEADERHELD)

    HEADERHELDLASTMS = int(t)

    if HEADERHELDKIND == "TEXT":

        try:

            if HEADERLASTTEXT:
                headerinserttext(HEADERLASTTEXT)

            return

        except Exception:

            return

    if key == "LEFT":

        headerclearselection()

        HEADERCARETPOS = clamp(HEADERCARETPOS - 1, 0, len(HEADEREDITTEXT))

        return

    if key == "RIGHT":

        headerclearselection()

        HEADERCARETPOS = clamp(HEADERCARETPOS + 1, 0, len(HEADEREDITTEXT))

        return

    if key == "HOME":

        headerclearselection()

        HEADERCARETPOS = 0

        return

    if key == "END":

        headerclearselection()

        HEADERCARETPOS = len(HEADEREDITTEXT)

        return

    if key == "BACKSPACE":

        headerbackspace()

        return

    if key == "DELETE":

        headerdelete()

        return


def navrecord(path):

    global NAVHIST, NAVPOS

    p = normalisepath(path)

    if NAVPOS >= 0 and NAVPOS < len(NAVHIST):

        try:

            if NAVHIST[NAVPOS] == p:
                return

        except Exception:

            pass

    try:

        if NAVPOS < (len(NAVHIST) - 1):
            NAVHIST = NAVHIST[:NAVPOS + 1]

    except Exception:

        pass

    NAVHIST.append(p)

    NAVPOS = len(NAVHIST) - 1


def navcanback():

    try:

        return NAVPOS > 0

    except Exception:

        return False


def navcanforward():

    try:

        return NAVPOS >= 0 and NAVPOS < (len(NAVHIST) - 1)

    except Exception:

        return False


def navback():

    global NAVPOS

    if not navcanback():
        return

    NAVPOS = NAVPOS - 1

    try:

        target = NAVHIST[NAVPOS]

    except Exception:

        return

    setcwd(target, record=False)


def navforward():

    global NAVPOS

    if not navcanforward():
        return

    NAVPOS = NAVPOS + 1

    try:

        target = NAVHIST[NAVPOS]

    except Exception:

        return

    setcwd(target, record=False)


# status menu functions
def closestatusmenu():

    global STATUSMENUOPEN, STATUSMENU_PANEL, STATUSMENU_RECTS

    STATUSMENUOPEN = False

    STATUSMENU_PANEL = None

    STATUSMENU_RECTS = {}

    return


def statusmenuitems():

    try:

        if STATUSMENUKIND == "new":
            return [
                ("new file", "newfile"),
                ("new tier", "newtier")
            ]

        if STATUSMENUKIND == "delete":
            return [
                ("delete", "delete"),
                ("destroy", "destroy")
            ]

        return []

    except Exception:

        return []


def computestatusmenupanel():

    global STATUSMENU_PANEL, STATUSMENU_RECTS, STATUSMENUKIND

    STATUSMENU_PANEL = None

    STATUSMENU_RECTS = {}

    try:

        if STATUSMENUKIND == "new":

            anchor = ACTIONMAP.get("new_anchor", None)

        elif STATUSMENUKIND == "delete":

            anchor = ACTIONMAP.get("delete_anchor", None)

        else:

            anchor = None

        if anchor is None:
            return None

    except Exception:

        return None

    try:

        x0, y0, x1, y1 = anchor

        items = statusmenuitems()

        if not items:
            return None

    except Exception:

        return None

    try:

        maxw = 0

        for label, _ in items:

            try:

                w = measuretext(str(label), FONTSIZESTATUS, FONT)

            except Exception:

                w = len(str(label)) * max(1, (FONTSIZESTATUS // 2))

            if w > maxw:
                maxw = w

    except Exception:

        maxw = 120

    try:

        pw = int(STATUSMENU_PAD_X + maxw + STATUSMENU_PAD_X)

        ph = int((len(items) * STATUSMENU_ITEM_H) + (STATUSMENU_PAD_Y * 2))

        px = int(x0)

        py = int((WINH - STATUSH) - ph)

        if py < 0:
            py = 0

        if px + pw > WINW:
            px = max(0, WINW - pw)

        STATUSMENU_PANEL = (px, py, pw, ph)

        y = py + STATUSMENU_PAD_Y

        for i, (label, actionid) in enumerate(items):

            iy = y + (i * STATUSMENU_ITEM_H)

            STATUSMENU_RECTS[(px, iy, px + pw, iy + STATUSMENU_ITEM_H)] = actionid

        return STATUSMENU_PANEL

    except Exception:

        STATUSMENU_PANEL = None

        STATUSMENU_RECTS = {}
        return None


def statusmenuhit(x, y):

    try:

        if not STATUSMENUOPEN:
            return None

        if STATUSMENU_PANEL is None:
            return None

    except Exception:

        return None

    try:

        px, py, pw, ph = STATUSMENU_PANEL

        if x < px or x > (px + pw) or y < py or y > (py + ph):
            return None

    except Exception:

        return None

    try:

        for rect, actionid in STATUSMENU_RECTS.items():


            x0, y0, x1, y1 = rect

            if x >= x0 and x <= x1 and y >= y0 and y <= y1:
                return actionid

    except Exception:

        return None

    return None


# sidebar functions
def getusername():

    try:

        with open(SESSIONIDENTITYFILE, "rb") as stream:
            raw = stream.read(SESSIONIDENTITYMAXBYTES + 1)

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


def buildsidebarlinks():

    global SIDEBARLINKS

    SIDEBARLINKS = []

    for index, entry in enumerate(SIDBARENTRIES):
        path = sidebarentrypath(entry)
        SIDEBARLINKS.append({
            "label": str(entry.get("label") or "location"),
            "path": path,
            "drive": int(entry.get("drive", 1)),
            "relative": str(entry.get("path", "/")),
            "index": index,
            "available": bool(path and (path == "/.rubbish" or os.path.isdir(path))),
        })

    for _ in range(SIDEBARDRIVEGAPROWS):
        SIDEBARLINKS.append({"label": "", "path": None, "index": None, "isspacer": True, "available": False})

    for number in sorted(DRIVES):
        drive = DRIVES[number]
        root = drive.get("root", "/")
        SIDEBARLINKS.append({
            "label": f"{number}  {drive.get('label', 'drive')}",
            "path": root,
            "drive": number,
            "relative": "/",
            "index": None,
            "available": os.path.isdir(root),
            "isdrive": True,
        })


# context menu functions
def closecontextmenu():

    global CONTEXTMENUOPEN, CONTEXTMENUKIND, CONTEXTMENU_ANCHOR, CONTEXTMENU_PANEL, CONTEXTMENU_RECTS, CONTEXTMENUTARGET, CONTEXTMENUHOVERACTION

    CONTEXTMENUOPEN = False

    CONTEXTMENUKIND = None

    CONTEXTMENU_ANCHOR = None

    CONTEXTMENU_PANEL = None

    CONTEXTMENU_RECTS = {}

    CONTEXTMENUTARGET = None

    CONTEXTMENUHOVERACTION = None

    return


def opencontextmenu(x, y, kind, targetpath=None):

    global CONTEXTMENUOPEN, CONTEXTMENUKIND, CONTEXTMENU_ANCHOR, CONTEXTMENU_PANEL, CONTEXTMENU_RECTS, CONTEXTMENUTARGET, CONTEXTMENUHOVERACTION

    if PICKERMODE:
        return

    CONTEXTMENUOPEN = True

    CONTEXTMENUKIND = kind

    CONTEXTMENU_ANCHOR = (int(x), int(y))

    CONTEXTMENU_PANEL = None

    CONTEXTMENU_RECTS = {}

    CONTEXTMENUTARGET = targetpath

    CONTEXTMENUHOVERACTION = None

    return


def contextmenuitems():

    items = []

    try:

        buildactions()

    except Exception:

        return items

    try:

        if CONTEXTMENUKIND == "sidebar":

            items.append(("open", "open"))

            if SIDEBARSELECTEDDRIVE is not None:

                items.append(("rename drive", "driverename"))

            elif SIDEBARSELECTED is not None:

                items.append(("rename sidebar item", "sidebarrename"))

                items.append(("remove from sidebar", "sidebarunpin"))

            return items

        # folder/file actions
        isfolder = False

        isopenable = False

        if CONTEXTMENUKIND == "row" and CONTEXTMENUTARGET is not None:

            try:

                if os.path.isdir(CONTEXTMENUTARGET):
                    isfolder = True

                    isopenable = True

                else:

                    isexec = False

                    ispy = False

                    try:

                        st = os.stat(CONTEXTMENUTARGET)

                        isexec = bool(st.st_mode & 0o111)

                    except Exception:

                        isexec = False

                    try:

                        ispy = str(CONTEXTMENUTARGET).lower().endswith(".py")

                    except Exception:

                        ispy = False

                    if ispy or isexec:

                        isopenable = True

                    elif (
                        isarraylink(CONTEXTMENUTARGET)
                        or istextfile(CONTEXTMENUTARGET)
                        or isaudiofile(CONTEXTMENUTARGET)
                    ):

                        isopenable = True

            except Exception:

                isfolder = False

                isopenable = False

        if isopenable:

            items.append(("open", "open"))

        if isfolder:

            items.append(("open in a new window", "opennew"))

            items.append(("pin to sidebar", "sidebarpin"))

        if ACTIONVIS.get("new") and CONTEXTMENUKIND == "empty":

            items.append(("new file", "newfile"))

            items.append(("new tier", "newtier"))

        if ACTIONVIS.get("new") and CONTEXTMENUKIND == "row":

            isdir = False

            try:

                if len(SELECTEDSET) == 1 and SELECTED is not None:

                    for item in TREE:

                        if item["path"] == SELECTED:

                            isdir = bool(item["isdir"])

                            break

            except Exception:

                isdir = False

            if isdir:

                items.append(("new file", "newfile"))

                items.append(("new tier", "newtier"))

        if ACTIONVIS.get("paste"):

            allow = False

            if CONTEXTMENUKIND == "empty":
                allow = True

            if CONTEXTMENUKIND == "row" and CONTEXTMENUTARGET is not None:

                try:

                    if os.path.isdir(CONTEXTMENUTARGET):
                        allow = True

                except Exception:

                    allow = False

            if allow:

                items.append(("paste", "paste"))

        if ACTIONVIS.get("copy"):

            items.append(("copy", "copy"))

            items.append(("copy as path", "copypath"))

        if ACTIONVIS.get("cut"):

            items.append(("cut", "cut"))

        if ACTIONVIS.get("rename"):

            items.append(("rename", "rename"))

        if ACTIONVIS.get("delete"):

            items.append(("delete", "delete"))

            items.append(("destroy", "destroy"))

        if ACTIONVIS.get("run"):

            items.append(("run", "run"))

        if ACTIONVIS.get("empty"):

            items.append(("empty", "empty"))

        if ACTIONVIS.get("restore"):

            items.append(("restore", "restore"))

        if CONTEXTMENUKIND == "row":

            if SEARCHOPEN and SEARCHTEXT.strip():
                items.append(("open file location", "filelocation"))

            if not isfolder:
                items.append(("open with...", "openwith"))

                if str(CONTEXTMENUTARGET).lower().endswith(".zip"):
                    items.append(("extract all", "extract"))

            items.append(("create link", "createlink"))

            items.append(("compress to zip", "compress"))

            items.append(("properties", "properties"))

        if CONTEXTMENUKIND == "empty":

            items.append(("pin current tier to sidebar", "sidebarpin"))

        if undoavailable():

            items.append(("undo", "undo"))

        if redoavailable():

            items.append(("redo", "redo"))

    except Exception:

        return items

    return items


def computecontextmenupanel():

    global CONTEXTMENU_PANEL, CONTEXTMENU_RECTS, CONTEXTMENU_ANCHOR

    CONTEXTMENU_PANEL = None

    CONTEXTMENU_RECTS = {}

    try:

        if not CONTEXTMENUOPEN:
            return None

        if CONTEXTMENU_ANCHOR is None:
            return None

    except Exception:

        return None

    try:

        items = contextmenuitems()

        if not items:
            return None

    except Exception:

        return None

    try:

        ax, ay = CONTEXTMENU_ANCHOR

        ph = (len(items) * STATUSMENU_ITEM_H) + (CONTEXTMENU_PAD_Y * 2)

        maxw = 0

        for label, actionid in items:

            w = measuretext(str(label), FONTSIZESTATUS, FONT)

            if w > maxw:
                maxw = w

        pw = int(maxw) + (STATUSMENU_PAD_X * 2)

        px = int(ax)

        py = int(ay)

        maxy = int(WINH - STATUSH - ph)

        if py > maxy:

            py = maxy

        if py < 0:

            py = 0

        maxx = int(WINW - pw)

        if px > maxx:

            px = maxx

        if px < 0:

            px = 0

        CONTEXTMENU_PANEL = (px, py, pw, ph)

        x = px + STATUSMENU_PAD_X

        y = py + CONTEXTMENU_PAD_Y

        for i, (label, actionid) in enumerate(items):

            iy = y + (i * STATUSMENU_ITEM_H)

            CONTEXTMENU_RECTS[(px, iy, px + pw, iy + STATUSMENU_ITEM_H)] = actionid

        return CONTEXTMENU_PANEL

    except Exception:

        CONTEXTMENU_PANEL = None

        CONTEXTMENU_RECTS = {}

        return None


def contextmenuhit(x, y):

    try:

        if not CONTEXTMENUOPEN:
            return None

        if CONTEXTMENU_PANEL is None:

            computecontextmenupanel()

            if CONTEXTMENU_PANEL is None:
                return None

    except Exception:

        return None

    try:

        px, py, pw, ph = CONTEXTMENU_PANEL

        if x < px or x > (px + pw) or y < py or y > (py + ph):
            return None

    except Exception:

        return None

    try:

        for rect, actionid in CONTEXTMENU_RECTS.items():

            x0, y0, x1, y1 = rect

            if x >= x0 and x <= x1 and y >= y0 and y <= y1:
                return actionid

    except Exception:

        return None

    return None


def updatecontextmenuhover(x, y):

    global CONTEXTMENUHOVERACTION

    actionid = contextmenuhit(x, y) if CONTEXTMENUOPEN else None
    if actionid == CONTEXTMENUHOVERACTION:
        return

    oldpanel = CONTEXTMENU_PANEL
    CONTEXTMENUHOVERACTION = actionid

    if oldpanel is not None:
        px, py, pw, ph = oldpanel
        invalidaterect(px, py, pw, ph)


def clearcontextmenuhover():

    global CONTEXTMENUHOVERACTION

    if CONTEXTMENUHOVERACTION is None:
        return

    CONTEXTMENUHOVERACTION = None

    if CONTEXTMENU_PANEL is not None:
        px, py, pw, ph = CONTEXTMENU_PANEL
        invalidaterect(px, py, pw, ph)


# drag box functions
def mainpanerect():

    try:

        x = SIDEBARW + DIVW

        y = CONTENTTOP

        w = VISIBLEWIDTH

        h = WINH - CONTENTTOP - STATUSH

        if horizontalneeded():
            h = h - HSCROLL_HEIGHT

        if w < 0:
            w = 0

        if h < 0:
            h = 0

        return int(x), int(y), int(w), int(h)

    except Exception:

        return 0, 0, 0, 0


def dragboxrect():

    if not DRAGBOX:
        return None

    try:

        x0 = min(int(DRAGBOXSX), int(DRAGBOXEX))

        y0 = min(int(DRAGBOXSY), int(DRAGBOXEY))

        x1 = max(int(DRAGBOXSX), int(DRAGBOXEX))

        y1 = max(int(DRAGBOXSY), int(DRAGBOXEY))

    except Exception:

        return None

    px, py, pw, ph = mainpanerect()

    try:

        cx0 = clamp(x0, px, px + pw)

        cy0 = clamp(y0, py, py + ph)

        cx1 = clamp(x1, px, px + pw)

        cy1 = clamp(y1, py, py + ph)

    except Exception:

        return None

    w = int(cx1 - cx0)

    h = int(cy1 - cy0)

    if w <= 1 or h <= 1:
        return None

    return int(cx0), int(cy0), int(w), int(h)


def startdragbox(x, y, add):

    global DRAGBOX, DRAGBOXSX, DRAGBOXSY, DRAGBOXEX, DRAGBOXEY, DRAGBOXADD
    global DRAGBOXBASESET, DRAGBOXBASEFOCUS, DRAGBOXBASEANCHOR

    DRAGBOX = True

    DRAGBOXSX = int(x)

    DRAGBOXSY = int(y)

    DRAGBOXEX = int(x)

    DRAGBOXEY = int(y)

    DRAGBOXADD = bool(add)

    DRAGBOXBASESET = set(SELECTEDSET)

    DRAGBOXBASEFOCUS = SELECTED

    DRAGBOXBASEANCHOR = SELECTANCHOR

    px, py, pw, ph = mainpanerect()

    invalidaterect(px, py, pw, ph)


def updatedragbox(x, y):

    global DRAGBOXEX, DRAGBOXEY

    DRAGBOXEX = int(x)

    DRAGBOXEY = int(y)

    r = dragboxrect()

    if r is None:

        px, py, pw, ph = mainpanerect()

        invalidaterect(px, py, pw, ph)

        return

    bx, by, bw, bh = r

    hit = []

    for i in range(len(TREE)):

        rr = rowrect(i)

        if rr is None:
            continue

        rx, ry, rw, rh = rr

        if (rx + rw) < bx:
            continue

        if rx > (bx + bw):
            continue

        if (ry + rh) < by:
            continue

        if ry > (by + bh):
            continue

        try:

            hit.append(TREE[i]["path"])

        except Exception:

            pass

    if DRAGBOXADD:

        merged = set(DRAGBOXBASESET)

        for p in hit:
            merged.add(normalisepath(p))

        focuspath = hit[-1] if hit else DRAGBOXBASEFOCUS

        setselection(list(merged), focuspath=focuspath, anchorpath=DRAGBOXBASEANCHOR)

    else:

        if not hit:

            clearselection()

        else:

            setselection(hit, focuspath=hit[-1], anchorpath=hit[0])

    px, py, pw, ph = mainpanerect()

    invalidaterect(px, py, pw, ph)


def finishdragbox():

    global DRAGBOX

    if not DRAGBOX:
        return

    r = dragboxrect()

    DRAGBOX = False

    px, py, pw, ph = mainpanerect()

    invalidaterect(px, py, pw, ph)

    if r is None:

        if not DRAGBOXADD:
            clearselection()

        return

    bx, by, bw, bh = r

    hit = []

    for i in range(len(TREE)):

        rr = rowrect(i)

        if rr is None:
            continue

        rx, ry, rw, rh = rr

        if (rx + rw) < bx:
            continue

        if rx > (bx + bw):
            continue

        if (ry + rh) < by:
            continue

        if ry > (by + bh):
            continue

        try:

            hit.append(TREE[i]["path"])

        except Exception:

            pass

    if not hit:

        if not DRAGBOXADD:
            clearselection()

        return

    if DRAGBOXADD:

        merged = set(SELECTEDSET)

        for p in hit:
            merged.add(normalisepath(p))

        setselection(list(merged), focuspath=hit[-1], anchorpath=SELECTANCHOR)

        return

    setselection(hit, focuspath=hit[-1], anchorpath=hit[0])


# confirm functions
def openconfirm(actionid, paths):

    global CONFIRMOPEN, CONFIRMWAITING, CONFIRMDIALOGID, CONFIRMDIALOGWIN
    global CONFIRMACTION, CONFIRMPATHS, CONFIRMFOCUS, CONFIRMRECTS, CONFIRMPANEL

    if not paths:
        return

    CONFIRMOPEN = False

    CONFIRMWAITING = True

    CONFIRMDIALOGID = f"array-confirm-{os.getpid()}-{nowms()}"

    CONFIRMDIALOGWIN = None

    CONFIRMACTION = str(actionid)

    CONFIRMPATHS = list(paths)

    CONFIRMRECTS = {}

    CONFIRMPANEL = None

    CONFIRMFOCUS = 0

    closestatusmenu()

    closecontextmenu()

    sendws({
        "op": "CREATE_DIALOG",
        "parent": WINID,
        "dialog_id": CONFIRMDIALOGID,
        "title": (
            "replace file" if CONFIRMACTION == "picker_overwrite"
            else ("destroy" if CONFIRMACTION == "destroy" else "delete")
        ),
        "message": confirmtext(),
        "buttons": [
            {"id": "ok", "label": "replace" if CONFIRMACTION == "picker_overwrite" else "yes"},
            {"id": "cancel", "label": "cancel" if CONFIRMACTION == "picker_overwrite" else "no", "cancel": True},
        ],
        "default": 0,
    })


def closeconfirm():

    global CONFIRMOPEN, CONFIRMWAITING, CONFIRMDIALOGID, CONFIRMDIALOGWIN
    global CONFIRMACTION, CONFIRMPATHS, CONFIRMFOCUS, CONFIRMRECTS, CONFIRMPANEL

    CONFIRMOPEN = False

    CONFIRMWAITING = False

    CONFIRMDIALOGID = None

    CONFIRMDIALOGWIN = None

    CONFIRMACTION = None

    CONFIRMPATHS = []

    CONFIRMFOCUS = 0

    CONFIRMRECTS = {}

    CONFIRMPANEL = None

    invalidaterect(0, 0, WINW, WINH)


def confirmrubbishname(path):

    if path is None:
        return None

    try:

        target = os.path.abspath(str(path))

    except Exception:

        return None

    try:

        parts = target.strip(os.sep).split(os.sep)

        if len(parts) >= 2 and parts[0] == ".rubbish":

            rid = parts[1]

        else:

            return None

    except Exception:

        return None

    indexfile = "/.rubbish/index.txt"

    try:

        with open(indexfile, "r") as f:

            lines = f.read().splitlines()

    except Exception:

        return None

    if not lines:
        return None

    for row in lines[1:]:

        if not row:
            continue

        try:

            cols = row.split("\t")

        except Exception:

            continue

        if len(cols) < 2:
            continue

        try:

            rowrid = cols[0]

            name = cols[1]

        except Exception:

            continue

        if str(rowrid) == str(rid):

            try:

                if name:
                    return str(name)

            except Exception:

                return None

    return None


def confirmdisplayname(path):

    if path is None:
        return "item"

    try:

        if isrubbish(path):

            n = confirmrubbishname(path)

            if n:
                return n

    except Exception:

        pass

    try:

        base = os.path.basename(str(path))

        if base:
            return base

    except Exception:

        pass

    return "item"


def confirmlisttext(paths, limit=3):

    try:

        items = [confirmdisplayname(p) for p in paths if p is not None]

    except Exception:

        items = []

    if not items:
        return "this item"

    if len(items) == 1:
        return f"{items[0]}"

    shown = items[:int(limit)]

    if len(items) <= int(limit):
        return ", ".join([f"{s}" for s in shown])

    more = len(items) - int(limit)

    return ", ".join([f"{s}" for s in shown]) + f", and {more} more"


def confirmtext():

    try:

        n = len(CONFIRMPATHS)

    except Exception:

        n = 0

    names = confirmlisttext(CONFIRMPATHS, limit=3)

    if CONFIRMACTION == "picker_overwrite":
        return f"{names} already exists. replace it?"

    if CONFIRMACTION == "destroy":

        if n == 1:
            return f"are you sure you want to destroy {names}?"

        return f"are you sure you want to destroy {names}?"

    if n == 1:
        return f"are you sure you want to put {names} in the rubbish?"

    return f"are you sure you want to put {names} in the rubbish?"


def confirmbuttons():

    return [("yes", "ok"), ("no", "cancel")]


def computeconfirmpanel():

    global CONFIRMPANEL, CONFIRMRECTS, CONFIRMORDER

    CONFIRMPANEL = None

    CONFIRMRECTS = {}

    CONFIRMORDER = []

    pw = int(CONFIRMW)

    ph = int(CONFIRMH)

    maxw = int(WINW - (PAD * 2))

    maxh = int(WINH - (PAD * 2))

    if pw > maxw:
        pw = maxw

    if ph > maxh:
        ph = maxh

    if pw < 1:
        pw = 1

    if ph < 1:
        ph = 1

    px = int((WINW - pw) // 2)

    py = int((WINH - ph) // 2)

    CONFIRMPANEL = (px, py, pw, ph)

    # buttons bottom-right
    btns = confirmbuttons()

    gap = int(CONFIRMGAP)

    totalw = (len(btns) * CONFIRMBTNW) + ((len(btns) - 1) * gap)

    bx = px + (pw // 2) - (totalw // 2)

    by = py + ph - CONFIRMPAD - CONFIRMBTNH

    for i, (label, kind) in enumerate(btns):

        rx = bx + i * (CONFIRMBTNW + gap)

        r = (rx, by, rx + CONFIRMBTNW, by + CONFIRMBTNH)

        CONFIRMRECTS[r] = kind

        CONFIRMORDER.append(r)

    return CONFIRMPANEL


def confirmhit(x, y):

    for r in CONFIRMORDER:

        x0, y0, x1, y1 = r

        if x >= x0 and x <= x1 and y >= y0 and y <= y1:

            try:

                return CONFIRMRECTS.get(r)

            except Exception:

                return None

    return None


def confirmdo(kind):

    overwrite = (CONFIRMACTION == "picker_overwrite" and kind != "cancel")

    if kind == "cancel":

        closeconfirm()

        return

    # execute the original action now that user confirmed
    if CONFIRMACTION == "delete":
        deleteitems(CONFIRMPATHS)

    elif CONFIRMACTION == "destroy":
        destroyitems(CONFIRMPATHS)

    closeconfirm()

    if overwrite:
        pickerconfirm(overwrite=True)


def confirmkey(msg):

    global CONFIRMFOCUS

    try:

        key = str(msg.get("key", "")).upper()

    except Exception:

        key = ""

    try:

        state = str(msg.get("state", "down")).lower()

    except Exception:

        state = "down"

    try:

        isdown = (state == "down" or state == "repeat")

    except Exception:

        isdown = True

    if not isdown:
        return

    try:

        mods = msg.get("mods", {})

    except Exception:

        mods = {}

    try:

        shift = bool(mods.get("shift"))

    except Exception:

        shift = False

    if key == "ESC":

        confirmdo("cancel")

        return

    if key in ("LEFT", "RIGHT", "TAB"):

        try:

            btns = confirmbuttons()

            count = len(btns)

        except Exception:

            count = 2

        if count <= 1:
            return

        if key == "LEFT":

            CONFIRMFOCUS = (int(CONFIRMFOCUS) - 1) % int(count)

        elif key == "RIGHT":

            CONFIRMFOCUS = (int(CONFIRMFOCUS) + 1) % int(count)

        else:

            if shift:
                CONFIRMFOCUS = (int(CONFIRMFOCUS) - 1) % int(count)
            else:
                CONFIRMFOCUS = (int(CONFIRMFOCUS) + 1) % int(count)

        invalidaterect(0, 0, WINW, WINH)

        return

    if key == "ENTER":

        btns = confirmbuttons()

        try:

            _, kind = btns[CONFIRMFOCUS]

        except Exception:

            kind = "cancel"

        confirmdo(kind)

        return


def wrapconfirmtext(text, maxw, fontsize, font):

    words = text.split(" ")

    lines = []

    current = ""

    for w in words:

        test = w if not current else f"{current} {w}"

        tw = measuretext(test, fontsize, font)

        if tw <= maxw:
            current = test
        else:
            if current:
                lines.append(current)
            current = w

    if current:
        lines.append(current)

    return lines


def confirmpointer(msg):

    x = msg.get("x")

    y = msg.get("y")

    pressed = msg.get("pressed")

    if not pressed:
        return

    hit = confirmhit(x, y)

    if hit is None:
        return

    confirmdo(hit)


def drawconfirm():

    if not CONFIRMOPEN:
        return

    panel = computeconfirmpanel()

    if panel is None:
        return

    px, py, pw, ph = panel

    # panel
    fillrectfast(px, py, pw, ph, COLOURSTATUS)

    drawrect(px, py, pw, ph, COLOURDIVIDER)

    # text (wrapped + centered in the space above the buttons)
    msg = confirmtext()

    top = py + CONFIRMPAD

    try:

        lastbtn = CONFIRMORDER[-1]

        by = int(lastbtn[1])

        textbottom = by - 10

    except Exception:

        textbottom = py + ph - CONFIRMPAD - CONFIRMBTNH - 10

    area_h = int(textbottom - top)

    if area_h < FONTSIZESTATUS:
        area_h = FONTSIZESTATUS

    maxtextw = int(pw - (CONFIRMPAD * 2))

    if maxtextw < 1:
        maxtextw = 1

    lines = wrapconfirmtext(msg, maxtextw, CONFIRMFONTSIZE, FONT)

    linegap = 4

    lineh = int(CONFIRMFONTSIZE + linegap)

    blockh = int(len(lines) * lineh)

    starty = int(top + (area_h // 2) - (blockh // 2))

    ty = int(starty)

    for line in lines:

        try:

            lw = measuretext(line, CONFIRMFONTSIZE, FONT)

        except Exception:

            lw = len(line) * max(1, (CONFIRMFONTSIZE // 2))

        tx = int(px + (pw // 2) - (int(lw) // 2))

        drawtextttf(
            tx,
            ty,
            line,
            COLOURTEXT,
            CONFIRMFONTSIZE,
            FONT
        )

        ty += lineh

    # buttons (no rectangles, just text + focus underline)
    btns = confirmbuttons()

    for i, (label, kind) in enumerate(btns):

        try:

            r = CONFIRMORDER[i]

        except Exception:

            continue

        x0, y0, x1, y1 = r

        bw = int(x1 - x0)

        bh = int(y1 - y0)

        try:

            tw = measuretext(label, CONFIRMFONTSIZE, FONT)

        except Exception:

            tw = len(label) * max(1, (CONFIRMFONTSIZE // 2))

        lx = int(x0 + (bw // 2) - (int(tw) // 2))

        ly = int(y0 + (bh // 2) - (FONTSIZESTATUS // 2) - 1)

        drawtextttf(
            lx,
            ly,
            label,
            COLOURTEXT,
            CONFIRMFONTSIZE,
            FONT
        )

        if i == CONFIRMFOCUS:

            try:

                miny, maxy = ttfbbox(label, CONFIRMFONTSIZE, fontpath=FONT)

                glyphbottom = ly + int(maxy)

                uy = glyphbottom + 2

            except Exception:

                uy = int(y0 + bh - 2)

            drawline(
                int(lx),
                int(uy),
                int(lx + int(tw)),
                int(uy),
                COLOURTEXT
            )


# filesystem functions
def setcwd(path, record=True):

    global CWD, EXPANDED, SCROLL, SELECTED, SELECTEDSET, SELECTANCHOR, SELECTEDMS
    global PENDINGSCROLL, LASTSCROLLFRAME
    global DRIVENUMBER

    raw = str(path or "/").strip()
    if re.match(r"^[0-9]+(?:/|$)", raw.replace("\\", "/")):
        number, newpath = parselocation(raw)
        if newpath is None:
            setstatus(f"drive {number} is not available", error=True)
            return False
    else:
        newpath = _physicalnormalize(raw)

    if not os.path.isdir(newpath):
        setstatus("location is not available", error=True)
        return False

    DRIVENUMBER = int(driveforpath(newpath).get("number", 1))

    oldpath = CWD

    # Navigation leaves the search-results view.  Invalidate its generation
    # before changing CWD so queued partial results cannot populate the new
    # destination after it has been rendered.
    if newpath != oldpath and SEARCHOPEN:
        searchclose(rebuild=False)

    # update cwd
    CWD = newpath

    if newpath != oldpath:

        EXPANDED = set()

    # inform windowserver that our window "current" changed
    if WINID is not None:

        sendws({
            "op": "WINDOW_CURRENT_SET",
            "winid": WINID,
            "current": formatlocation(CWD),
        })

    if record:
        navrecord(newpath)

    # reset view state
    SCROLL = 0
    PENDINGSCROLL = 0
    LASTSCROLLFRAME = 0.0

    SELECTED = None

    SELECTEDSET = set()

    SELECTANCHOR = None

    SELECTEDMS = 0

    # rebuild tree
    buildtree()

    # redraw everything
    invalidaterect(0, 0, WINW, WINH)

    watchreset()
    return True


def naturalkey(value):

    parts = re.split(r"([0-9]+)", str(value).casefold())
    return tuple(int(part) if part.isdigit() else part for part in parts)


def typelabel(name, isdir=False, islink=False):

    if islink:
        return "link"
    if isdir:
        return "tier"
    ext = os.path.splitext(str(name))[1].lower()
    if ext == ".zip":
        return "zip archive"
    guessed = mimetypes.guess_type(str(name))[0]
    if guessed:
        return guessed
    if ext:
        return f"{ext[1:].upper()} file"
    return "file"


def displayname(name, isdir=False):

    value = str(name)
    if SHOWEXTENSIONS or isdir or value.startswith("."):
        return value
    stem, ext = os.path.splitext(value)
    return stem if ext else value


def formatfilesize(size):

    try:
        value = float(size)
    except Exception:
        return ""
    units = ("B", "KB", "MB", "GB", "TB")
    index = 0
    while value >= 1024.0 and index < len(units) - 1:
        value /= 1024.0
        index += 1
    if index == 0:
        return f"{int(value)} B"
    return f"{value:.1f} {units[index]}"


def formatatreyanyear(year):

    try:
        value = int(year)
    except Exception:
        return str(year)
    return f"{value - 2020}AE" if value >= 2021 else str(value)


def formatfiletime(timestamp):

    try:
        value = time.localtime(float(timestamp))
        return f"{value.tm_hour:02d}:{value.tm_min:02d} {value.tm_mday:02d}:{value.tm_mon:02d}:{formatatreyanyear(value.tm_year)}"
    except Exception:
        return ""


def enrichitem(name, virtualpath, realpath=None, forceddir=None):

    real = realpath or virtualpath
    try:
        st = os.lstat(real)
        linktarget = arraylinktarget(real, fileinfo=st)
        islink = linktarget is not None
        isdir = os.path.isdir(real) if forceddir is None else bool(forceddir)
        size = 0 if isdir else int(st.st_size)
        modified = float(st.st_mtime)
        created = float(getattr(st, "st_birthtime", st.st_ctime))
        mode = int(st.st_mode)
    except Exception:
        islink = False
        linktarget = None
        isdir = bool(forceddir)
        size = 0
        modified = 0.0
        created = 0.0
        mode = 0

    return {
        "name": str(name),
        "displayname": displayname(name, isdir),
        "path": str(virtualpath),
        "realpath": str(real),
        "isdir": isdir,
        "islink": islink,
        "linktarget": linktarget,
        "size": size,
        "sizestr": "" if isdir else formatfilesize(size),
        "modified": modified,
        "modifiedstr": formatfiletime(modified),
        "created": created,
        "type": typelabel(name, isdir, islink),
        "mode": mode,
    }


def sortitems(items):

    def value(item):
        if SORTKEY == "modified":
            return float(item.get("modified", 0.0))
        if SORTKEY == "size":
            return int(item.get("size", 0))
        if SORTKEY == "type":
            return (str(item.get("type", "")).casefold(), naturalkey(item.get("name", "")))
        return naturalkey(item.get("name", ""))

    try:
        items.sort(key=value, reverse=bool(SORTDESC))
        if FOLDERSFIRST:
            items.sort(key=lambda item: not bool(item.get("isdir")))
    except Exception:
        pass
    return items


def listdir(path):

    global SHOWHIDDEN

    apath = _physicalnormalize(path)
    if apath == _physicalnormalize("/.rubbish"):
        result = []
        for raw in rubbishrootlist():
            rid = str(raw.get("path", "")).rstrip("/").rsplit("/", 1)[-1]
            real = f"/.rubbish/{rid}/content"
            name = raw.get("name", rid)
            if not SHOWHIDDEN and itemishidden(real, name):
                continue
            result.append(enrichitem(name, raw.get("path"), real, raw.get("isdir")))
        return sortitems(result)

    realpath = path
    virtualbase = path

    try:
        parts = apath.strip("/").split("/")
        if len(parts) >= 2 and parts[0] == ".rubbish":
            rid = parts[1]
            rest = "/".join(parts[2:])
            realpath = f"/.rubbish/{rid}/content"
            virtualbase = f"/.rubbish/{rid}"
            if rest:
                realpath = f"{realpath}/{rest}"
                virtualbase = f"{virtualbase}/{rest}"
    except Exception:
        pass

    items = []
    try:
        with os.scandir(realpath) as entries:
            for entry in entries:
                name = entry.name
                if not SHOWHIDDEN and itemishidden(entry.path, name):
                    continue
                virtual = os.path.join(str(virtualbase), name).replace("\\", "/")
                item = enrichitem(name, virtual, entry.path)
                pickerpath = item.get("linktarget") if item.get("islink") else virtual
                if PICKERMODE and not item.get("isdir") and not pickerpathmatches(pickerpath):
                    continue
                items.append(item)
    except Exception:
        return []

    return sortitems(items)


def haschildren(path):

    global SHOWHIDDEN

    realpath = path

    try:

        apath = os.path.abspath(str(path))

        parts = apath.strip("/").split("/")

        if len(parts) >= 2 and parts[0] == ".rubbish":

            rid = parts[1]

            rest = "/".join(parts[2:])

            realpath = f"/.rubbish/{rid}/content"

            if rest:
                realpath = f"{realpath}/{rest}"

    except Exception:

        realpath = path

    try:

        if not os.path.isdir(realpath):
            return False

    except Exception:

        return False

    try:

        entries = os.listdir(realpath)

    except Exception:

        return False

    try:

        for name in entries:

            if not SHOWHIDDEN and itemishidden(os.path.join(realpath, name), name):
                continue

            # any visible entry means expandable
            return True

    except Exception:

        return False

    return False


def togglehidden():

    global SHOWHIDDEN, SELECTED

    # toggle hidden visibility
    SHOWHIDDEN = not SHOWHIDDEN

    # persist setting
    savehidden()

    # rebuild tree with new visibility
    buildtree()

    # if selected item disappeared, clear selection
    if SELECTED is not None:

        stillthere = False

        for item in TREE:

            if item["path"] == SELECTED:
                stillthere = True
                break

        if not stillthere:
            SELECTED = None

    # rebuild actions and redraw
    buildactions()

    invalidaterect(0, 0, WINW, WINH)


def loadhidden():

    global SHOWHIDDEN

    try:

        folder = os.path.dirname(HIDDENFILE)

        if folder and not os.path.exists(folder):
            os.makedirs(folder, exist_ok=True)

    except Exception:

        pass

    try:

        if not os.path.exists(HIDDENFILE):

            with open(HIDDENFILE, "w") as f:
                f.write("0\n")

            SHOWHIDDEN = False
            return

    except Exception:

        SHOWHIDDEN = False
        return

    try:

        with open(HIDDENFILE, "r") as f:
            val = f.read().strip().lower()

        SHOWHIDDEN = val in ("1", "true", "yes", "on")

    except Exception:

        SHOWHIDDEN = False


def savehidden():

    try:

        folder = os.path.dirname(HIDDENFILE)

        if folder and not os.path.exists(folder):
            os.makedirs(folder, exist_ok=True)

    except Exception:

        pass

    try:

        with open(HIDDENFILE, "w") as f:
            f.write(("1\n" if SHOWHIDDEN else "0\n"))

    except Exception:

        pass

def scrolltopath(path):

    global SCROLL

    cancelsmoothscroll()

    if path is None:
        return

    try:

        target = normalisepath(path)

    except Exception:

        target = str(path)

    idx = None

    for i, item in enumerate(TREE):

        if item["path"] == target:

            idx = i

            break

    if idx is None:
        return

    try:

        top = int(SCROLL)

        bottom = int(SCROLL) + max(0, int(VISIBLECOUNT) - 1)

    except Exception:

        top = 0

        bottom = 0

    try:

        if idx < top:

            SCROLL = int(idx)

        elif idx > bottom:

            SCROLL = int(idx) - max(0, int(VISIBLECOUNT) - 1)

        vscrollclamp()

    except Exception:

        SCROLL = 0

    # main pane changed (scroll)
    invalidaterect(SIDEBARW + DIVW, HEADERH, WINW - (SIDEBARW + DIVW), WINH - HEADERH - STATUSH)


def buildtree():

    global TREE

    TREE = []

    root = CWD

    # start tree walk at cwd
    walktree(root, 0)

    # recompute layout now that TREE length may have changed
    layout()

    # compute intrinsic content width (independent of HSCROLL)
    computecontentwidth()

    # clamp horizontal scroll after recalculating widths
    hscrollclamp()

    # clamp vertical scroll after TREE changed
    vscrollclamp()

    # rebuild status actions based on selection
    buildactions()

    # redraw everything
    invalidaterect(0, 0, WINW, WINH)


def toggleexpand(path):

    p = normalisepath(path)

    if p in EXPANDED:

        EXPANDED.remove(p)

    else:

        EXPANDED.add(p)

    # rebuild tree after toggle
    buildtree()

    # redraw everything
    invalidaterect(0, 0, WINW, WINH)


def selectpath(path):

    global SELECTED, SELECTEDMS, SELECTEDSET, SELECTANCHOR

    try:

        oldset = set(SELECTEDSET)

    except Exception:

        oldset = set()

    p = normalisepath(path)

    SELECTEDSET = set([p])

    SELECTANCHOR = p

    SELECTED = p

    SELECTEDMS = nowms()

    buildactions()

    invalidaterect(SIDEBARW + DIVW, HEADERH, WINW - (SIDEBARW + DIVW), WINH - HEADERH - STATUSH)

    invalidaterect(0, WINH - STATUSH, WINW, STATUSH)


def invalidateselectionrow(path):

    if path is None:
        return

    for i, item in enumerate(TREE):

        if item["path"] == path:

            y = CONTENTTOP + ((i - SCROLL) * ROWH)

            if y < CONTENTTOP:
                return

            if y >= (WINH - STATUSH):
                return

            invalidaterect(SIDEBARW + DIVW, y, WINW - (SIDEBARW + DIVW), ROWH)

            return


def selectedpaths():

    try:

        if SELECTEDSET:
            return [normalisepath(p) for p in list(SELECTEDSET)]

    except Exception:

        pass

    if SELECTED is None:
        return []

    return [normalisepath(SELECTED)]


def ensurefocus(path):

    global SELECTED, SELECTEDMS

    if path is None:
        return

    SELECTED = normalisepath(path)

    SELECTEDMS = nowms()


def setselection(paths, focuspath=None, anchorpath=None):

    global SELECTEDSET, SELECTANCHOR

    try:

        SELECTEDSET = set([normalisepath(p) for p in paths if p is not None])

    except Exception:

        SELECTEDSET = set()

    if focuspath is None:

        try:

            focuspath = next(iter(SELECTEDSET)) if SELECTEDSET else None

        except Exception:

            focuspath = None

    ensurefocus(focuspath)

    if anchorpath is not None:
        SELECTANCHOR = normalisepath(anchorpath)

    buildactions()

    invalidaterect(SIDEBARW + DIVW, HEADERH, WINW - (SIDEBARW + DIVW), WINH - HEADERH - STATUSH)

    invalidaterect(0, WINH - STATUSH, WINW, STATUSH)


def toggleselection(path):

    global SELECTEDSET, SELECTANCHOR

    if path is None:
        return

    p = normalisepath(path)

    if p in SELECTEDSET:

        try:

            SELECTEDSET.remove(p)

        except Exception:

            pass

    else:

        SELECTEDSET.add(p)

    ensurefocus(p)

    SELECTANCHOR = p

    buildactions()

    invalidaterect(SIDEBARW + DIVW, HEADERH, WINW - (SIDEBARW + DIVW), WINH - HEADERH - STATUSH)

    invalidaterect(0, WINH - STATUSH, WINW, STATUSH)


def rangeselection(to_path, add=False):

    global SELECTANCHOR

    if to_path is None:

        return

    tgt = normalisepath(to_path)

    if SELECTANCHOR is None:

        setselection([tgt], focuspath=tgt, anchorpath=tgt)

        return

    aidx = None

    bidx = None

    for i, item in enumerate(TREE):

        if item["path"] == SELECTANCHOR:
            aidx = i

        if item["path"] == tgt:
            bidx = i

    if aidx is None or bidx is None:

        setselection([tgt], focuspath=tgt, anchorpath=tgt)

        return

    lo = min(aidx, bidx)

    hi = max(aidx, bidx)

    paths = []

    for i in range(lo, hi + 1):

        try:

            paths.append(TREE[i]["path"])

        except Exception:

            pass

    if add:

        merged = set(SELECTEDSET)

        for p in paths:

            merged.add(normalisepath(p))

        setselection(list(merged), focuspath=tgt, anchorpath=SELECTANCHOR)

        return

    setselection(paths, focuspath=tgt, anchorpath=SELECTANCHOR)


def movetreeselection(delta, extend=False):

    if not TREE:
        return

    current = None

    for i, item in enumerate(TREE):

        if item.get("path") == SELECTED:
            current = i
            break

    if current is None:
        target = 0

    else:

        try:

            target = clamp(current + int(delta), 0, len(TREE) - 1)

        except Exception:

            target = current

    path = TREE[target].get("path")

    if path is None:
        return

    if extend and SELECTED is not None:

        rangeselection(path)

    else:

        selectpath(path)

    scrolltopath(path)


def clearselection():

    global SELECTEDSET, SELECTED, SELECTEDMS, SELECTANCHOR

    SELECTEDSET = set()

    SELECTED = None

    SELECTEDMS = 0

    SELECTANCHOR = None

    buildactions()

    invalidaterect(SIDEBARW + DIVW, HEADERH, WINW - (SIDEBARW + DIVW), WINH - HEADERH - STATUSH)

    invalidaterect(0, WINH - STATUSH, WINW, STATUSH)


def selectalltree():

    paths = []

    for item in TREE:

        try:

            paths.append(item["path"])

        except Exception:

            pass

    if not paths:

        clearselection()

        return

    setselection(paths, focuspath=paths[-1], anchorpath=paths[0])


def renameselectionrange():

    try:

        if RENAMESELANCHOR is None:
            return None

        a = clamp(int(RENAMESELANCHOR), 0, len(RENAMETEXT))

        b = clamp(int(RENAMECARETPOS), 0, len(RENAMETEXT))

        if a == b:
            return None

        if a < b:
            return a, b

        return b, a

    except Exception:

        return None


def clearrenameselection():

    global RENAMESELANCHOR

    RENAMESELANCHOR = None


def deleterenameselection():

    global RENAMETEXT, RENAMECARETPOS, RENAMESELANCHOR

    r = renameselectionrange()

    if r is None:
        return False

    start, end = r

    try:

        RENAMETEXT = f"{RENAMETEXT[:start]}{RENAMETEXT[end:]}"

        RENAMECARETPOS = start

        RENAMESELANCHOR = None

        return True

    except Exception:

        return False


def renamesnapshot():

    return {
        "text": str(RENAMETEXT),
        "caret": int(RENAMECARETPOS),
        "anchor": RENAMESELANCHOR,
    }


def restorerenamesnapshot(snap):

    global RENAMETEXT, RENAMECARETPOS, RENAMESELANCHOR

    try:

        RENAMETEXT = str(snap.get("text", ""))

        RENAMECARETPOS = clamp(int(snap.get("caret", 0)), 0, len(RENAMETEXT))

        anchor = snap.get("anchor", None)

        if anchor is None:
            RENAMESELANCHOR = None
        else:
            RENAMESELANCHOR = clamp(int(anchor), 0, len(RENAMETEXT))

    except Exception:

        pass


def pushrenameundo():

    global RENAMEREDO

    try:

        snap = renamesnapshot()

        if RENAMEUNDO and RENAMEUNDO[-1].get("text") == snap.get("text"):
            return

        RENAMEUNDO.append(snap)

        while len(RENAMEUNDO) > RENAMEHISTLIMIT:
            RENAMEUNDO.pop(0)

        RENAMEREDO = []

    except Exception:

        pass


def undorenameedit():

    if not RENAMEUNDO:
        return

    RENAMEREDO.append(renamesnapshot())

    snap = RENAMEUNDO.pop()

    restorerenamesnapshot(snap)

    invalidateselectionrow(RENAMEPATH)


def redorenameedit():

    if not RENAMEREDO:
        return

    RENAMEUNDO.append(renamesnapshot())

    snap = RENAMEREDO.pop()

    restorerenamesnapshot(snap)

    invalidateselectionrow(RENAMEPATH)


def renameselectedtext():

    r = renameselectionrange()

    if r is None:
        return ""

    start, end = r

    try:

        return RENAMETEXT[start:end]

    except Exception:

        return ""


def selectallrename():

    global RENAMECARETPOS, RENAMESELANCHOR

    try:

        end = len(RENAMETEXT)

        if RENAMEPATH is not None and not os.path.isdir(RENAMEPATH):

            stem, ext = os.path.splitext(RENAMETEXT)

            if stem and ext:

                stemend = len(stem)

                if renameselectionrange() == (0, stemend):
                    end = len(RENAMETEXT)
                else:
                    end = stemend

    except Exception:

        end = len(RENAMETEXT)

    RENAMESELANCHOR = 0

    RENAMECARETPOS = end


def renamewordleft(pos):

    try:

        i = clamp(int(pos), 0, len(RENAMETEXT))

        while i > 0 and not RENAMETEXT[i - 1].isalnum():
            i -= 1

        while i > 0 and RENAMETEXT[i - 1].isalnum():
            i -= 1

        return i

    except Exception:

        return 0


def renamewordright(pos):

    try:

        i = clamp(int(pos), 0, len(RENAMETEXT))

        n = len(RENAMETEXT)

        while i < n and not RENAMETEXT[i].isalnum():
            i += 1

        while i < n and RENAMETEXT[i].isalnum():
            i += 1

        return i

    except Exception:

        return len(RENAMETEXT)


def moverenamecaretto(pos, shift=False):

    global RENAMECARETPOS, RENAMESELANCHOR

    try:

        oldpos = clamp(int(RENAMECARETPOS), 0, len(RENAMETEXT))

        newpos = clamp(int(pos), 0, len(RENAMETEXT))

    except Exception:

        return

    if shift:

        if RENAMESELANCHOR is None:
            RENAMESELANCHOR = oldpos

        RENAMECARETPOS = newpos

        if RENAMESELANCHOR == RENAMECARETPOS:
            RENAMESELANCHOR = None

    else:

        RENAMECARETPOS = newpos

        RENAMESELANCHOR = None


def moverenamecaret(delta, shift=False):

    global RENAMECARETPOS, RENAMESELANCHOR

    try:

        oldpos = clamp(int(RENAMECARETPOS), 0, len(RENAMETEXT))

        newpos = clamp(oldpos + int(delta), 0, len(RENAMETEXT))

    except Exception:

        return

    moverenamecaretto(newpos, shift=shift)


def replacerenameselection(text):

    global RENAMETEXT, RENAMECARETPOS, RENAMESELANCHOR

    pushrenameundo()

    deleterenameselection()

    try:

        s = str(text)

    except Exception:

        s = ""

    left = RENAMETEXT[:RENAMECARETPOS]

    right = RENAMETEXT[RENAMECARETPOS:]

    RENAMETEXT = f"{left}{s}{right}"

    RENAMECARETPOS = RENAMECARETPOS + len(s)

    RENAMESELANCHOR = None


def copyrenametext(cut=False):

    selected = renameselectedtext()

    if selected == "":
        return

    try:

        exset(selected, source="array")

    except Exception:

        pass

    if cut:

        pushrenameundo()

        deleterenameselection()


def pasterenametext():

    ok, st = exget()

    if not ok:
        return

    try:

        if str(st.get("type", "")) != "text":
            return

        text = str(st.get("data", ""))

    except Exception:

        return

    replacerenameselection(text)


def deleterenameword(left=True):

    global RENAMETEXT, RENAMECARETPOS, RENAMESELANCHOR

    if renameselectionrange() is not None:

        pushrenameundo()

        deleterenameselection()

        return

    try:

        if left:
            start = renamewordleft(RENAMECARETPOS)
            end = RENAMECARETPOS
        else:
            start = RENAMECARETPOS
            end = renamewordright(RENAMECARETPOS)

        if start == end:
            return

        pushrenameundo()

        RENAMETEXT = f"{RENAMETEXT[:start]}{RENAMETEXT[end:]}"

        RENAMECARETPOS = start

        RENAMESELANCHOR = None

    except Exception:

        pass


def renameindexwidth(index):

    try:

        i = clamp(int(index), 0, len(RENAMETEXT))

        return measuretext(RENAMETEXT[:i], FONTSIZEROW, FONT)

    except Exception:

        return 0


def renameeditmetrics(row):

    try:

        if row is None or row < 0 or row >= len(TREE):
            return None

        item = TREE[row]

        if not RENAMEEDIT or item.get("path") != RENAMEPATH:
            return None

        rowy = CONTENTTOP + ((row - SCROLL) * ROWH)

        basex = SIDEBARW + DIVW + PAD + (item["depth"] * TREEINDENT) + (scalesize(18) if SHOWITEMCHECKS else 0)

        arrowspace = ARROWW

        namex = basex + arrowspace

        namey = rowy + (ROWH // 2) - (FONTSIZEROW // 2)

        paneleft = SIDEBARW + DIVW

        paneright = paneleft + VISIBLEWIDTH

        availw = int(paneright - namex)

        if availw < 0:
            availw = 0

        boxpad = 2

        boxh = FONTSIZEROW + 6

        boxy = rowy + (ROWH // 2) - (boxh // 2)

        boxw = int(availw)

        if boxw < 0:
            boxw = 0

        innerw = int(boxw - 4)

        if innerw < 0:
            innerw = 0

        prew = renameindexwidth(RENAMECARETPOS)

        if prew > innerw:
            editscroll = int(prew - innerw)
        else:
            editscroll = 0

        return {
            "namex": namex,
            "namey": namey,
            "boxx": namex - boxpad,
            "boxy": boxy,
            "boxw": boxw + (boxpad * 2),
            "boxh": boxh,
            "innerx": namex + 2,
            "innerw": innerw,
            "editscroll": editscroll,
        }

    except Exception:

        return None


def renameeditrowat(x, y):

    row = rowat(x, y)

    if row is None:
        return None

    metrics = renameeditmetrics(row)

    if metrics is None:
        return None

    try:

        if int(x) < metrics["boxx"] or int(x) > (metrics["boxx"] + metrics["boxw"]):
            return None

        if int(y) < metrics["boxy"] or int(y) > (metrics["boxy"] + metrics["boxh"]):
            return None

        return row

    except Exception:

        return None


def currentrenameeditrow():

    try:

        for i, item in enumerate(TREE):

            if item.get("path") == RENAMEPATH:
                return i

    except Exception:

        pass

    return None


def renamecaretfromx(x, metrics):

    try:

        local = int(x) - int(metrics["innerx"]) + int(metrics["editscroll"])

    except Exception:

        local = 0

    if local <= 0:
        return 0

    best = len(RENAMETEXT)

    for i in range(0, len(RENAMETEXT) + 1):

        try:

            w = renameindexwidth(i)

        except Exception:

            w = 0

        if w >= local:

            if i > 0:

                prev = renameindexwidth(i - 1)

                if abs(local - prev) < abs(w - local):
                    return i - 1

            return i

    return best


def setrenamecaretfrommouse(row, x, shift=False):

    metrics = renameeditmetrics(row)

    if metrics is None:
        return

    caret = renamecaretfromx(x, metrics)

    moverenamecaretto(caret, shift=shift)


def drawrenameselection(namex, namey, boxy, boxh, innerw, editscroll):

    r = renameselectionrange()

    if r is None:
        return

    start, end = r

    leftlimit = int(namex + 2)

    rightlimit = int(namex + 2 + innerw)

    try:

        selx0 = leftlimit + int(renameindexwidth(start) - editscroll)

        selx1 = leftlimit + int(renameindexwidth(end) - editscroll)

    except Exception:

        return

    if selx1 < leftlimit or selx0 > rightlimit:
        return

    drawx0 = clamp(selx0, leftlimit, rightlimit)

    drawx1 = clamp(selx1, leftlimit, rightlimit)

    if drawx1 <= drawx0:
        return

    try:

        fillrectfast(drawx0, boxy + 2, drawx1 - drawx0, boxh - 4, COLOURTEXT)

    except Exception:

        return

    visstart = start

    while visstart < end:

        try:

            charend = leftlimit + int(renameindexwidth(visstart + 1) - editscroll)

        except Exception:

            break

        if charend > leftlimit:
            break

        visstart += 1

    visend = end

    while visend > visstart:

        try:

            charstart = leftlimit + int(renameindexwidth(visend - 1) - editscroll)

        except Exception:

            break

        if charstart < rightlimit:
            break

        visend -= 1

    if visend <= visstart:
        return

    try:

        textx = leftlimit + int(renameindexwidth(visstart) - editscroll)

        drawtextttf(textx, namey, RENAMETEXT[visstart:visend], COLOURBG, FONTSIZEROW, FONT)

    except Exception:

        pass


def cancelpendingrename():

    global PENDINGRENAMEPATH, PENDINGRENAMEAT

    PENDINGRENAMEPATH = None

    PENDINGRENAMEAT = 0


def schedulependingrename(path, now):

    global PENDINGRENAMEPATH, PENDINGRENAMEAT

    try:

        PENDINGRENAMEPATH = normalisepath(path)

    except Exception:

        PENDINGRENAMEPATH = str(path)

    PENDINGRENAMEAT = int(now) + int(RENAMECLICKDELAYMS)


def pendingrenamepump():

    global PENDINGRENAMEPATH, PENDINGRENAMEAT

    if PENDINGRENAMEPATH is None:
        return

    # Do not enter rename while the pointer is still held down. A drag cancels
    # the pending action in itemdragmotion; a stationary click can complete on
    # release and then enter rename after the double-click window.
    if ITEMDRAGSTART is not None:
        return

    try:

        if nowms() < int(PENDINGRENAMEAT):
            return

    except Exception:

        cancelpendingrename()

        return

    path = PENDINGRENAMEPATH

    cancelpendingrename()

    if RENAMEEDIT or len(SELECTEDSET) != 1 or path not in SELECTEDSET:
        return

    renameeditstart(path, skipnextclick=False)


def renameeditstart(path, blank=False, skipnextclick=True):

    global RENAMEEDIT, RENAMETEXT, RENAMECARETPOS, RENAMESELANCHOR, RENAMEUNDO, RENAMEREDO, RENAMEDRAGGING, RENAMEPATH, RENAMEORIGINAL, RENAMESKIPNEXTCLICK

    if path is None:
        return

    RENAMESKIPNEXTCLICK = bool(skipnextclick)

    try:

        RENAMEPATH = normalisepath(path)

    except Exception:

        RENAMEPATH = str(path)

    try:

        RENAMEORIGINAL = os.path.basename(RENAMEPATH)

    except Exception:

        RENAMEORIGINAL = ""

    if blank:

        RENAMETEXT = ""

        RENAMECARETPOS = 0

        RENAMESELANCHOR = None

    else:

        RENAMETEXT = RENAMEORIGINAL

        try:

            if os.path.isdir(RENAMEPATH):

                RENAMESELANCHOR = 0

                RENAMECARETPOS = len(RENAMETEXT)

            else:

                stem, ext = os.path.splitext(RENAMETEXT)

                if stem and ext:

                    RENAMESELANCHOR = 0

                    RENAMECARETPOS = len(stem)

                else:

                    RENAMESELANCHOR = 0

                    RENAMECARETPOS = len(RENAMETEXT)

        except Exception:

            RENAMECARETPOS = len(RENAMETEXT)

            RENAMESELANCHOR = None

    RENAMEUNDO = []

    RENAMEREDO = []

    RENAMEDRAGGING = False

    try:

        RENAMEEDIT = True

    except Exception:

        RENAMEEDIT = False

    selectpath(RENAMEPATH)

    scrolltopath(RENAMEPATH)

    invalidateselectionrow(RENAMEPATH)


def renameeditend(cancel=False):

    global RENAMEEDIT, RENAMETEXT, RENAMECARETPOS, RENAMESELANCHOR, RENAMEUNDO, RENAMEREDO, RENAMEDRAGGING, RENAMEPATH, RENAMEORIGINAL

    RENAMEEDIT = False

    RENAMETEXT = ""

    RENAMECARETPOS = 0

    RENAMESELANCHOR = None

    RENAMEUNDO = []

    RENAMEREDO = []

    RENAMEDRAGGING = False

    RENAMEPATH = None

    RENAMEORIGINAL = ""


def renameconfirm():

    global RENAMEEDIT, RENAMETEXT, RENAMECARETPOS, RENAMEPATH, RENAMEORIGINAL

    if not RENAMEEDIT:
        return

    oldpath = RENAMEPATH

    if oldpath is None:
        return

    try:

        name = str(RENAMETEXT).strip()

    except Exception:

        name = ""

    if name == "":

        renameeditend(cancel=True)

        invalidateselectionrow(oldpath)

        return

    if "/" in name or "\\" in name:
        return

    if name == "." or name == "..":
        return

    parent = os.path.dirname(oldpath)

    newpath = os.path.join(parent, name)

    if normalisepath(newpath) == normalisepath(oldpath):

        renameeditend(cancel=False)
        return

    # no overwrite
    if os.path.exists(newpath):
        return

    if not permissionpaths(oldpath, newpath):
        return

    try:

        os.rename(oldpath, newpath)

        flushfilesystem(oldpath, newpath)

    except PermissionError:

        permissiondenied()
        return

    except FileNotFoundError:

        return

    except Exception:

        return None

    pushundo({
        "type": "rename",
        "old": normalisepath(oldpath),
        "new": normalisepath(newpath),
    })

    renameeditend(cancel=False)

    buildtree()

    selectpath(newpath)

    scrolltopath(newpath)


def opsrequest(payload):

    sock = None

    fileobj = None

    try:

        # connect to operations socket
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

        sock.settimeout(1.0)

        sock.connect(OPERATIONSSOCKET)

    except Exception:

        return None

    try:

        # send request line
        reqtext = json.dumps(payload) + "\n"

        sock.sendall(reqtext.encode("utf-8"))

    except Exception:

        sock.close()

        return None

    try:

        # read response line
        fileobj = sock.makefile("rb")

        line = fileobj.readline()

    except Exception:

        sock.close()

        return None

    sock.close()

    if not line:
        return None

    try:

        # parse json response
        text = line.decode("utf-8", errors="replace").strip()

        return json.loads(text)

    except Exception:

        return None


def opsrun(path, args, name, _log, user, mode, await_window=False):

    resp = None

    try:

        # Operations owns executable identity, profile, name, log, uid and
        # state. Array selects only a measured catalogue entry and its bounded
        # file arguments; the retired arbitrary RUN request cannot launch any
        # current application.
        payload = {
            "op": "LAUNCH_CATALOGUE",
            "path": path,
            "args": list(args) if args else [],
        }

    except Exception:

        return None

    resp = opsrequest(payload)

    if not resp:
        setstatus('Operations Server is unavailable', error=True)
        return None

    try:

        if resp.get("status") != "ok":
            message = str(resp.get('message') or 'application launch was denied')
            setstatus(message, error=True)
            return None

        return int(resp.get("pid"))

    except Exception:

        setstatus('Operations Server returned an invalid launch response', error=True)
        return None


# layout functions
def layout():

    global VISIBLECOUNT, VISIBLEWIDTH, EXPLORERTOP, CONTENTTOP

    try:

        # compute header rectangle
        headerx = 0

        headery = 0

        headerw = WINW

        headerh = HEADERH

        # compute status bar rectangle
        statusx = 0

        statusy = WINH - STATUSH

        statusw = WINW

        statush = STATUSH

        # compute sidebar rectangle
        sidebarx = 0

        sidebary = HEADERH

        sidebarh = WINH - HEADERH - STATUSH

        dividerx = SIDEBARW

        dividery = HEADERH

        dividerh = sidebarh

        mainx = SIDEBARW + DIVW

        EXPLORERTOP = HEADERH + TOOLBARH

        CONTENTTOP = EXPLORERTOP + (DETAILHEADERH if VIEWMODE == "details" else 0)

        mainy = CONTENTTOP

        mainh = WINH - CONTENTTOP - STATUSH

        # compute how many rows are visible
        VISIBLECOUNT = mainh // ROWH

        # compute visible width for horizontal scrolling
        pane = PROPERTIESW if PROPERTIESPANE else 0
        VISIBLEWIDTH = WINW - (SIDEBARW + DIVW) - pane - (VSCROLL_WIDTH if verticalneeded() else 0)

    except Exception:

        VISIBLECOUNT = 0

        VISIBLEWIDTH = 0


def rowat(x, y):

    try:

        # outside vertical list area
        if y < CONTENTTOP:
            return None

        if y > WINH - STATUSH:
            return None

        # outside horizontal list area
        if x < SIDEBARW + DIVW:
            return None

        if x >= (SIDEBARW + DIVW + VISIBLEWIDTH):
            return None

        # compute row index
        rel = y - CONTENTTOP

        idx = (rel // ROWH) + SCROLL

        if idx < 0:
            return None

        if idx >= len(TREE):
            return None

        return idx

    except Exception:

        return None


def sidebarat(x, y):

    try:

        # outside sidebar
        if x < 0 or x > SIDEBARW:
            return None

        if y < TITLEH or y > WINH - STATUSH:
            return None

        rel = y - HEADERH

        idx = rel // ROWH

        if idx < 0:
            return None

        if idx >= len(SIDEBARLINKS):
            return None

        if SIDEBARLINKS[idx].get("isspacer"):
            return None

        return SIDEBARLINKS[idx]["path"]

    except Exception:

        return None


def arrowat(x, y, row):

    try:

        # invalid row
        if row is None:
            return False

        item = TREE[row]

        # not a directory or no children
        if not item["isdir"]:
            return False

        if not item["haskids"]:
            return False

        # compute row y range
        rowy = CONTENTTOP + ((row - SCROLL) * ROWH)

        if y < rowy or y > rowy + ROWH:
            return False

        # compute arrow x range
        depth = item["depth"]

        arrowx0 = SIDEBARW + DIVW + PAD + (depth * TREEINDENT) + (scalesize(18) if SHOWITEMCHECKS else 0)

        arrowx1 = arrowx0 + ARROWW

        if x < arrowx0 or x > arrowx1:
            return False

        return True

    except Exception:

        return False


def statusat(x, y):

    try:

        # outside status bar
        if y < WINH - STATUSH:
            return None

        for rect, action in ACTIONMAP.items():

            # skip non-rect keys (e.g. "new_anchor")
            if not isinstance(rect, tuple) or len(rect) != 4:
                continue

            x0, y0, x1, y1 = rect

            if x >= x0 and x <= x1 and y >= y0 and y <= y1:
                return action

        return None

    except Exception:

        return None


def headerat(x, y):

    try:

        # outside header area
        if y < 0 or y > HEADERH:
            return None

        for rect, target in HEADERMAP.items():

            x0, y0, x1, y1 = rect

            if x >= x0 and x <= x1 and y >= y0 and y <= y1:
                return target

        return None

    except Exception:

        return None


def textview(text, size, fontpath, skipw, availw):

    try:

        s = str(text)

    except Exception:

        return ""

    try:

        if availw <= 0:
            return ""

    except Exception:

        return ""

    try:

        key = (s, int(size), str(fontpath or ""))

        advances = GRAPHICSTEXTADVANCES.get(key)

        if advances is None:

            advances = measurelineadvances(key, s, int(size), fontpath)

            if len(advances) != len(s):

                advances = []

                xpos = 0

                for ch in s:

                    cw = measuretext(ch, size, fontpath)

                    if cw <= 0:
                        cw = max(1, (int(size) // 2))

                    xpos += cw
                    advances.append(xpos)

            if len(GRAPHICSTEXTADVANCES) >= 512:

                oldest = next(iter(GRAPHICSTEXTADVANCES), None)

                if oldest is not None:
                    GRAPHICSTEXTADVANCES.pop(oldest, None)

            GRAPHICSTEXTADVANCES[key] = advances

        if not advances:
            return ""

        start = bisect_right(advances, max(0, int(skipw)))

        if start >= len(s):
            return ""

        base = advances[start - 1] if start > 0 else 0
        end = bisect_right(advances, base + max(0, int(availw)), lo=start)

        return s[start:end]

    except Exception:

        return ""


# managed render functions
def graphicsclip(rect, outer=None):

    try:

        x, y, width, height = [int(value) for value in rect]

        left = max(0, x)

        top = max(0, y)

        right = min(int(WINW), x + width)

        bottom = min(int(WINH), y + height)

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


def sidebarlinkat(x, y):

    try:
        if x < 0 or x > SIDEBARW or y < HEADERH or y > WINH - STATUSH:
            return None
        index = (y - HEADERH) // ROWH
        if index < 0 or index >= len(SIDEBARLINKS):
            return None
        link = SIDEBARLINKS[index]
        if link.get("isspacer"):
            return None
        return link
    except Exception:
        return None


def sidebarhoverindex(x, y):

    try:
        if int(x) < 0 or int(x) >= SIDEBARW or int(y) < HEADERH or int(y) >= WINH - STATUSH:
            return None
        index = (int(y) - HEADERH) // ROWH
        if index < 0 or index >= len(SIDEBARLINKS):
            return None
        if SIDEBARLINKS[index].get("isspacer"):
            return None
        return index
    except Exception:
        return None


def updatesidebarhover(x, y):

    global SIDEBARHOVERINDEX

    index = sidebarhoverindex(x, y)
    if index == SIDEBARHOVERINDEX:
        return
    SIDEBARHOVERINDEX = index
    invalidaterect(0, HEADERH, SIDEBARW, max(0, WINH - HEADERH - STATUSH))


def clearsidebarhover():

    global SIDEBARHOVERINDEX

    if SIDEBARHOVERINDEX is None:
        return
    SIDEBARHOVERINDEX = None
    invalidaterect(0, HEADERH, SIDEBARW, max(0, WINH - HEADERH - STATUSH))


def graphicsrect(commands, x, y, width, height, colour, clip):

    try:

        commandclip = graphicsclip(clip)

        clipped = graphicsclip([x, y, width, height], commandclip)

        if commandclip is None or clipped is None:
            return False

        commands.append({
            "kind": "rectangle",
            "rect": clipped,
            "color": int(colour),
            "clip": commandclip,
        })

        return True

    except Exception:

        return False


def checkboxat(x, y, row):

    if not SHOWITEMCHECKS or row is None or row < 0 or row >= len(TREE):
        return False
    item = TREE[row]
    boxx = SIDEBARW + DIVW + PAD + (int(item.get("depth", 0)) * TREEINDENT)
    boxy = CONTENTTOP + ((row - SCROLL) * ROWH) + (ROWH // 2) - scalesize(6)
    return x >= boxx and x <= boxx + scalesize(12) and y >= boxy and y <= boxy + scalesize(12)


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


def graphicsline(commands, x0, y0, x1, y1, colour, clip):

    try:

        x0 = int(x0)

        y0 = int(y0)

        x1 = int(x1)

        y1 = int(y1)

        if y0 == y1:

            left = min(x0, x1)

            graphicsrect(commands, left, y0, abs(x1 - x0) + 1, 1, colour, clip)

            return

        if x0 == x1:

            top = min(y0, y1)

            graphicsrect(commands, x0, top, 1, abs(y1 - y0) + 1, colour, clip)

            return

        rows = {}

        dx = abs(x1 - x0)

        sx = 1 if x0 < x1 else -1

        dy = -abs(y1 - y0)

        sy = 1 if y0 < y1 else -1

        error = dx + dy

        x = x0

        y = y0

        while True:

            if y not in rows:

                rows[y] = [x, x]

            else:

                rows[y][0] = min(rows[y][0], x)

                rows[y][1] = max(rows[y][1], x)

            if x == x1 and y == y1:
                break

            doubled = error * 2

            if doubled >= dy:

                error += dy

                x += sx

            if doubled <= dx:

                error += dx

                y += sy

        for rowy, span in rows.items():

            graphicsrect(commands, span[0], rowy, span[1] - span[0] + 1, 1, colour, clip)

    except Exception:

        pass


def graphicstexty(y, size, fontpath):

    try:

        key = (str(fontpath), int(size))
        cached = GRAPHICSTEXTBASELINES.get(key)

        if cached is not None:
            return int(y) + int(cached)

        face = gfx.getttfface(fontpath)

        if face is None:
            return int(y)

        face.set_pixel_sizes(0, int(size))

        ascender = int(face.size.ascender >> 6)

        offset = int(size) - ascender
        GRAPHICSTEXTBASELINES[key] = offset
        return int(y) + offset

    except Exception:

        return int(y)


def graphicstext(commands, x, y, text, colour, size, fontpath, clip):

    try:

        text = str(text)

        size = max(1, int(size))

        fontpath = str(fontpath or FONT)

        commandclip = graphicsclip(clip)

        if not text or commandclip is None:
            return

        clipx, clipy, clipw, cliph = commandclip

        if int(y) + size + 4 <= clipy or int(y) >= clipy + cliph:
            return

        drawx = int(x)

        shown = text

        while shown and drawx < clipx:

            try:

                width = int(measuretext(shown[0], size, fontpath))

            except Exception:

                width = max(1, size // 2)

            if width < 1:

                width = max(1, size // 2)

            drawx += width

            shown = shown[1:]

        if not shown or drawx >= clipx + clipw:
            return

        limit = max(1, int(GRAPHICSSTATE.get("text_limit", 1024)))

        offset = 0

        while offset < len(shown):

            chunk = shown[offset:offset + limit]

            if not chunk:
                break

            try:

                prefixw = int(measuretext(shown[:offset], size, fontpath)) if offset else 0

            except Exception:

                prefixw = offset * max(1, size // 2)

            chunkx = drawx + prefixw

            if chunkx >= clipx + clipw:
                break

            commands.append({
                "kind": "text",
                "x": max(0, int(chunkx)),
                "y": max(0, int(graphicstexty(y, size, fontpath))),
                "text": chunk,
                "size": size,
                "font": fontpath,
                "color": int(colour),
                "clip": commandclip,
            })

            offset += len(chunk)

    except Exception:

        pass


def graphicsbuildscene():

    global fillrectfast, drawrect, drawline, drawtextttf, SCENECAPTURECOMMANDS

    commands = []

    windowclip = graphicsclip([0, 0, WINW, WINH])

    if windowclip is None:
        return commands

    SCENECAPTURECOMMANDS = commands

    currentclip = windowclip

    originalfill = fillrectfast

    originalrect = drawrect

    originalline = drawline

    originaltext = drawtextttf

    def capturefill(x, y, width, height, colour, *args, **kwargs):

        return graphicsrect(commands, x, y, width, height, colour, currentclip)

    def capturerect(x, y, width, height, colour, *args, **kwargs):

        commandclip = graphicsclip(currentclip)

        if commandclip is not None and int(width) > 0 and int(height) > 0:
            commands.append({
                "kind": "border",
                "rect": [int(x), int(y), int(width), int(height)],
                "width": 1,
                "color": int(colour),
                "clip": commandclip,
            })

    def captureline(x0, y0, x1, y1, colour, *args, **kwargs):

        commandclip = graphicsclip(currentclip)

        if commandclip is not None:
            commands.append({
                "kind": "line",
                "points": [int(x0), int(y0), int(x1), int(y1)],
                "width": 1,
                "color": int(colour),
                "clip": commandclip,
            })

    def capturetext(x, y, text, colour, size, fontpath=None, *args, **kwargs):

        if fontpath is None:

            fontpath = kwargs.get("fontpath", FONT)

        return graphicstext(commands, x, y, text, colour, size, fontpath, currentclip)

    fillrectfast = capturefill

    drawrect = capturerect

    drawline = captureline

    drawtextttf = capturetext

    try:

        currentclip = windowclip

        drawbg()

        currentclip = graphicsclip([0, 0, WINW, HEADERH])

        if currentclip is not None:

            drawheader()

            drawsearchbox()

        currentclip = graphicsclip([SIDEBARW + DIVW, HEADERH, WINW - SIDEBARW - DIVW, TOOLBARH])
        if currentclip is not None:
            drawtopbar()

        if VIEWMODE == "details":
            currentclip = graphicsclip([SIDEBARW + DIVW, EXPLORERTOP, WINW - SIDEBARW - DIVW, DETAILHEADERH])
            if currentclip is not None:
                drawdetailsheader()

        contentheight = max(0, WINH - HEADERH - STATUSH)

        currentclip = graphicsclip([0, HEADERH, SIDEBARW + DIVW, contentheight])

        if currentclip is not None:

            drawsidebar()

            drawdivider()

        mainclip = graphicsclip(mainpanerect())

        currentclip = mainclip

        if currentclip is not None:

            start = max(0, int(SCROLL))

            end = min(start + max(0, int(VISIBLECOUNT)), len(TREE))

            for row in range(start, end):

                drawrow(row)

            dragrect = dragboxrect()

            if dragrect is not None:

                drawrect(dragrect[0], dragrect[1], dragrect[2], dragrect[3], COLOURTEXT)

        if PROPERTIESPANE:
            currentclip = graphicsclip([WINW - PROPERTIESW, EXPLORERTOP, PROPERTIESW, WINH - EXPLORERTOP - STATUSH])
            if currentclip is not None:
                drawsidepane()

        if horizontalneeded():

            currentclip = graphicsclip(hscrolltrackgeometry())

            if currentclip is not None:

                drawhscrollbar()

        if verticalneeded():

            currentclip = graphicsclip(vscrolltrackgeometry())

            if currentclip is not None:

                drawvscrollbar()

        currentclip = graphicsclip([0, WINH - STATUSH, WINW, STATUSH])

        if currentclip is not None:

            drawstatus()

        if STATUSMENUOPEN:

            panel = computestatusmenupanel()

            currentclip = graphicsclip(panel) if panel is not None else None

            if currentclip is not None:

                drawstatusmenu()

        if CONTEXTMENUOPEN:

            panel = computecontextmenupanel()

            currentclip = graphicsclip(panel) if panel is not None else None

            if currentclip is not None:

                drawcontextmenu()

        if CONFIRMOPEN:

            panel = computeconfirmpanel()

            currentclip = graphicsclip(panel) if panel is not None else None

            if currentclip is not None:

                drawconfirm()

        if PROPERTIESOPEN:
            currentclip = windowclip
            drawproperties()

        if INPUTOPEN:
            currentclip = windowclip
            drawinput()

        currentclip = windowclip
        drawdragtarget()

    finally:

        fillrectfast = originalfill

        drawrect = originalrect

        drawline = originalline

        drawtextttf = originaltext

        SCENECAPTURECOMMANDS = None

    return commands


def graphicspump():

    global GRAPHICSSCENE

    wasavailable = bool(GRAPHICSSTATE.get("available"))

    if not managedtick(GRAPHICSSTATE):

        if wasavailable and WINID:

            try:

                log(f"managed graphics disabled {GRAPHICSSTATE.get('failure', 'commit timeout')}")

            except Exception:

                pass

            try:

                sendws({"op": "GRAPHICS_CLEAR", "winid": WINID})

            except Exception:

                pass

            GRAPHICSSCENE = []

            graphicsrestorecpu()

        return False

    if not GRAPHICSSTATE.get("available") or not WINID:
        return False

    if GRAPHICSSTATE.get("pending") or not GRAPHICSSTATE.get("need_submit"):
        return bool(GRAPHICSSTATE.get("active"))

    try:

        commands = graphicsbuildscene()

    except Exception as e:

        return graphicsdisable(f"managed scene build failed {e}")

    if (
        not commands
        or commands[0].get("kind") != "rectangle"
        or commands[0].get("rect") != [0, 0, int(WINW), int(WINH)]
    ):

        return graphicsdisable("managed scene does not contain a complete background")

    beforeavailable = bool(GRAPHICSSTATE.get("available"))

    managedsubmit(GRAPHICSSTATE, graphicssend, WINID, commands)

    if beforeavailable and not GRAPHICSSTATE.get("available"):

        return graphicsdisable(GRAPHICSSTATE.get("failure", "managed scene submission failed"))

    if GRAPHICSSTATE.get("pending"):

        GRAPHICSSCENE = commands

    return bool(GRAPHICSSTATE.get("active"))


def graphicspresent(dirty=None):

    if not GRAPHICSSTATE.get("available"):
        return False

    if dirty is None:

        GRAPHICSSTATE["need_submit"] = True

    else:

        managedmarkdamage(GRAPHICSSTATE, dirty, bounds=(int(WINW), int(WINH)))

    graphicspump()

    return bool(GRAPHICSSTATE.get("active"))


# render functions
def invalidaterect(x, y, w, h):

    global NEEDREDRAW, DIRTYRECT

    NEEDREDRAW = True

    x0 = int(x)

    y0 = int(y)

    x1 = int(x) + int(w)

    y1 = int(y) + int(h)

    try:

        if DIRTYRECT is None:

            DIRTYRECT = [x0, y0, x1, y1]
            return

    except Exception:

        DIRTYRECT = [x0, y0, x1, y1]
        return

    if x0 < DIRTYRECT[0]: DIRTYRECT[0] = x0

    if y0 < DIRTYRECT[1]: DIRTYRECT[1] = y0

    if x1 > DIRTYRECT[2]: DIRTYRECT[2] = x1

    if y1 > DIRTYRECT[3]: DIRTYRECT[3] = y1


def renderdirty():

    global NEEDREDRAW, DIRTYRECT

    if not NEEDREDRAW:
        return

    try:

        if DIRTYRECT is None:

            NEEDREDRAW = False

            return

    except Exception:

        NEEDREDRAW = False

        return

    try:

        x0, y0, x1, y1 = DIRTYRECT

        w = int(x1 - x0)

        h = int(y1 - y0)

        if w <= 0 or h <= 0:

            NEEDREDRAW = False

            DIRTYRECT = None

            return

    except Exception:

        NEEDREDRAW = False

        DIRTYRECT = None

        return

    # expand dirty rect so gutter/header glyphs cannot be "redrawn off-rect"
    mainx = SIDEBARW + DIVW

    mainy = CONTENTTOP

    mainh = WINH - CONTENTTOP - STATUSH

    yend = y0 + h

    if y0 < HEADERH:

        x0 = 0

        w = WINW

    if y0 < (mainy + mainh) and yend > mainy:

        if x0 > mainx:

            x0 = mainx

        w = WINW - x0

    if GRAPHICSSTATE.get("available") and managedstrict(GRAPHICSSTATE):

        if graphicspresent([int(x0), int(y0), int(w), int(h)]):

            NEEDREDRAW = False
            DIRTYRECT = None
            return

    # draw ONLY the parts that overlap (see section 3)
    drawregion(x0, y0, w, h)

    presentrect(x0, y0, w, h)

    NEEDREDRAW = False

    DIRTYRECT = None


def rowrect(row):

    try:

        y = CONTENTTOP + ((int(row) - int(SCROLL)) * ROWH)

        x = SIDEBARW + DIVW

        w = VISIBLEWIDTH

        h = ROWH

        return (x, y, w, h)

    except Exception:

        return None


def namerect(row):

    if row is None:
        return None

    if row < 0 or row >= len(TREE):
        return None

    r = rowrect(row)

    if r is None:
        return None

    rx, ry, rw, rh = r

    item = TREE[row]

    # base x (matches drawrow/drawtree)
    basex = SIDEBARW + DIVW + PAD + (int(item.get("depth", 0)) * TREEINDENT) + (scalesize(18) if SHOWITEMCHECKS else 0)

    namex = basex + ARROWW

    paneleft = SIDEBARW + DIVW

    paneright = paneleft + VISIBLEWIDTH

    if VIEWMODE == "details":
        namewidth = next((width for column, columnx, width in detailcolumnrects() if column == "name"), COLUMNWIDTHS.get("name", 360))
        availw = int((paneleft + namewidth) - namex - PAD)
    else:
        availw = int(paneright - namex)

    if availw < 0:
        availw = 0

    # rename edit row hitbox = the edit box
    if RENAMEEDIT and item.get("path") == RENAMEPATH:

        boxpad = 2

        boxh = FONTSIZEROW + 6

        boxy = ry + (ROWH // 2) - (boxh // 2)

        boxw = int(availw)

        if boxw < 0:
            boxw = 0

        x0 = int(namex - boxpad)

        y0 = int(boxy)

        x1 = int(namex + boxw + boxpad)

        y1 = int(boxy + boxh)

        return (x0, y0, x1, y1)

    # normal row hitbox = the drawn filename glyph width (plus a small pad)
    shown = textview(item.get("displayname", item.get("name", "")), FONTSIZEROW, FONT, int(HSCROLL), availw)

    try:

        namew = measuretext(shown, FONTSIZEROW, FONT)

    except Exception:

        namew = len(str(shown)) * max(1, (FONTSIZEROW // 2))

    if namew < 0:
        namew = 0

    pad = 4

    x0 = int(namex - pad)

    y0 = int(ry)

    x1 = int(namex + int(namew) + pad)

    y1 = int(ry + ROWH)

    return (x0, y0, x1, y1)


def namehit(x, y, row):

    r = namerect(row)

    if r is None:
        return False

    x0, y0, x1, y1 = r

    try:

        return (int(x) >= x0 and int(x) <= x1 and int(y) >= y0 and int(y) <= y1)

    except Exception:

        return False


def drawsearchresultname(label, x, y, rowy, textcolour):

    spans = searchmatchspans(label)
    if not SEARCHOPEN or not SEARCHTEXT.strip() or not spans:
        drawtextttf(x, y, label, textcolour, FONTSIZEROW, FONT)
        return

    positions = []
    cursor = 0
    drawx = int(x)
    for start, end in spans:
        if start > cursor:
            segment = label[cursor:start]
            positions.append((drawx, segment, False))
            drawx += measuretext(segment, FONTSIZEROW, FONT)
        segment = label[start:end]
        positions.append((drawx, segment, True))
        drawx += measuretext(segment, FONTSIZEROW, FONT)
        cursor = end
    if cursor < len(label):
        positions.append((drawx, label[cursor:], False))

    highlightpad = max(3, scalesize(4))
    for segmentx, segment, matched in positions:
        if matched:
            segmentw = max(1, measuretext(segment, FONTSIZEROW, FONT))
            fillrectfast(
                segmentx,
                rowy + highlightpad,
                segmentw,
                max(1, ROWH - (highlightpad * 2)),
                COLOURTEXT,
            )

    for segmentx, segment, matched in positions:
        drawtextttf(
            segmentx,
            y,
            segment,
            COLOURHILITETEXT if matched else textcolour,
            FONTSIZEROW,
            FONT,
        )


def drawrow(row):


    if row < 0 or row >= len(TREE):
        return

    r = rowrect(row)

    if r is None:
        return

    x, y, w, h = r

    item = TREE[row]

    # Match the sidebar hover treatment for the current file/tier.
    selectedrow = item["path"] in SELECTEDSET

    fillrectfast(
        x,
        y,
        w,
        h,
        COLOURSTATUS if selectedrow else COLOURBG
    )

    if selectedrow and w > 0 and h > 0:
        fillrectfast(x, y, w, 1, COLOURROWOUTLINE)

    textcolour = COLOURTEXT

    # Use a solid one-pixel rectangle here. Managed line antialiasing can make
    # a dark single-pixel rule disappear against the black row background.
    if w > 0 and h > 0:
        fillrectfast(x, y + h - 1, w, 1, COLOURROWOUTLINE)

    if item["path"] in CUTSET:
        textcolour = COLOURMUTED

    basex = SIDEBARW + DIVW + PAD + (item["depth"] * TREEINDENT)

    if SHOWITEMCHECKS:
        box = scalesize(12)
        boxy = y + (ROWH // 2) - (box // 2)
        drawrect(basex, boxy, box, box, COLOURTEXT)
        if item["path"] in SELECTEDSET:
            fillrectfast(basex + scalesize(3), boxy + scalesize(3), max(1, box - scalesize(6)), max(1, box - scalesize(6)), COLOURTEXT)
        basex += scalesize(18)

    arrowspace = ARROWW

    topy = y + (ROWH // 2) - (FONTSIZEROW // 2)

    if item["isdir"]:

        if item["haskids"]:

            if item["expanded"]:

                drawchevrondown(
                    basex,
                    topy,
                    FONTSIZEROW,
                    FONT,
                    COLOURTEXT
                )

            else:

                drawtextttf(
                    basex,
                    topy,
                    ">",
                    COLOURTEXT,
                    FONTSIZEROW,
                    FONT
                )

        else:

            drawtextttf(
                basex,
                topy,
                ">",
                COLOURMUTED,
                FONTSIZEROW,
                FONT
            )

    namex = basex + arrowspace

    namey = topy

    paneleft = SIDEBARW + DIVW

    paneright = paneleft + VISIBLEWIDTH

    if VIEWMODE == "details":
        namewidth = next((width for column, columnx, width in detailcolumnrects() if column == "name"), COLUMNWIDTHS.get("name", 360))
        availw = int((paneleft + namewidth) - namex - PAD)
    else:
        availw = int(paneright - namex)

    if availw < 0:
        availw = 0

    # ------------------------------------------------------------
    # rename edit row
    # ------------------------------------------------------------
    if RENAMEEDIT and item["path"] == RENAMEPATH:

        boxpad = 2

        boxh = FONTSIZEROW + 6

        boxy = y + (ROWH // 2) - (boxh // 2)

        boxw = int(availw)

        if boxw < 0:
            boxw = 0

        # background + border
        fillrectfast(
            namex - boxpad,
            boxy,
            boxw + (boxpad * 2),
            boxh,
            COLOURSTATUS if item["path"] in SELECTEDSET else COLOURBG
        )

        # caret visibility (simple pixel scroll)
        try:

            pre = RENAMETEXT[:RENAMECARETPOS]

        except Exception:

            pre = ""

        try:

            prew = measuretext(pre, FONTSIZEROW, FONT)

        except Exception:

            prew = 0

        innerw = int(boxw - 4)

        if innerw < 0:
            innerw = 0

        if prew > innerw:

            editscroll = int(prew - innerw)

        else:

            editscroll = 0

        shown = textview(RENAMETEXT, FONTSIZEROW, FONT, int(editscroll), int(innerw))

        drawtextttf(namex + 2, namey, shown, COLOURTEXT, FONTSIZEROW, FONT)

        drawrenameselection(namex, namey, boxy, boxh, innerw, editscroll)

        # caret
        caretpx = (namex + 2) + int(prew - editscroll)

        if caretpx < (namex + 2):
            caretpx = (namex + 2)

        if caretpx > (namex + 2 + innerw):
            caretpx = (namex + 2 + innerw)

        t = nowms()

        if (t // RENAMEBLINKMS) % 2 == 0:

            drawline(caretpx, boxy + 2, caretpx, boxy + boxh - 2, COLOURTEXT)

        return

    shown = textview(item.get("displayname", item["name"]), FONTSIZEROW, FONT, int(HSCROLL), availw)

    drawsearchresultname(
        shown,
        namex,
        namey,
        y,
        textcolour,
    )

    if VIEWMODE == "details":
        drawdetailvalues(item, y, COLOURMUTED if item["path"] in CUTSET else COLOURTEXT)


def topbaritems():

    return [
        ("view", None, False),
        ("tier", "viewtier", VIEWMODE == "tier"),
        ("details", "viewdetails", VIEWMODE == "details"),
        ("properties", "propertiespane", PROPERTIESPANE),
        ("hide extensions" if SHOWEXTENSIONS else "show extensions", "extensions", not SHOWEXTENSIONS),
        ("sort", None, False),
        ("name" + (" v" if SORTDESC else " ^") if SORTKEY == "name" else "name", "sortname", SORTKEY == "name"),
        ("modified" + (" v" if SORTDESC else " ^") if SORTKEY == "modified" else "modified", "sortmodified", SORTKEY == "modified"),
        ("type" + (" v" if SORTDESC else " ^") if SORTKEY == "type" else "type", "sorttype", SORTKEY == "type"),
        ("size" + (" v" if SORTDESC else " ^") if SORTKEY == "size" else "size", "sortsize", SORTKEY == "size"),
        ("item checks", "itemchecks", SHOWITEMCHECKS),
        ("tiers first" if FOLDERSFIRST else "mixed tiers", "foldersfirst", not FOLDERSFIRST),
    ]


def drawtopbar():

    global TOPBARMAP
    TOPBARMAP = {}
    x0 = SIDEBARW + DIVW
    y0 = HEADERH
    fillrectfast(x0, y0, max(0, WINW - x0), TOOLBARH, COLOURBG)
    drawline(x0, y0 + TOOLBARH - 1, WINW, y0 + TOOLBARH - 1, COLOURDIVIDER)
    x = x0 + PAD
    buttony = y0 + scalesize(4)
    buttonh = max(1, TOOLBARH - scalesize(8))
    maxx = WINW - PAD

    for label, actionid, active in topbaritems():
        label = str(label)
        width = max(scalesize(24), measuretext(label, FONTSIZESTATUS, FONT) + (PAD * 2))
        if x + width > maxx:
            break
        if actionid is None:
            drawtextttf(x, buttony + (buttonh // 2) - (FONTSIZESTATUS // 2), label, COLOURMUTED, FONTSIZESTATUS, FONT)
            x += width
            continue
        drawtextttf(x + PAD, buttony + (buttonh // 2) - (FONTSIZESTATUS // 2), label, COLOURTEXT if active else COLOURMUTED, FONTSIZESTATUS, FONT)
        TOPBARMAP[(x, buttony, x + width, buttony + buttonh)] = actionid
        x += width + scalesize(3)


def topbarhit(x, y):

    if x < SIDEBARW + DIVW or y < HEADERH or y >= EXPLORERTOP:
        return None
    if not TOPBARMAP:
        return None
    for rect, actionid in TOPBARMAP.items():
        x0, y0, x1, y1 = rect
        if x >= x0 and x <= x1 and y >= y0 and y <= y1:
            return actionid
    return None


def detailcolumnrects():

    x = SIDEBARW + DIVW
    rects = []
    widths = {column: int(COLUMNWIDTHS.get(column, 100)) for column in DETAILCOLUMNS}
    overflow = max(0, sum(widths.values()) - max(0, int(VISIBLEWIDTH)))
    if "name" in widths and overflow:
        widths["name"] = max(scalesize(120), widths["name"] - overflow)
    for column in DETAILCOLUMNS:
        width = widths[column]
        rects.append((column, x, width))
        x += width
    return rects


def drawdetailvalues(item, rowy, colour):

    values = {
        "modified": item.get("modifiedstr", ""),
        "type": item.get("type", ""),
        "size": item.get("sizestr", ""),
    }
    texty = rowy + (ROWH // 2) - (FONTSIZEROW // 2)
    for column, x, width in detailcolumnrects():
        if column == "name":
            continue
        value = str(values.get(column, ""))
        shown = textview(value, FONTSIZEROW, FONT, 0, max(0, width - (PAD * 2)))
        drawtextttf(x + PAD, texty, shown, colour, FONTSIZEROW, FONT)


def drawdetailsheader():

    global COLUMNMAP
    if VIEWMODE != "details":
        COLUMNMAP = {}
        return

    fillrectfast(SIDEBARW + DIVW, EXPLORERTOP, WINW - SIDEBARW - DIVW, DETAILHEADERH, COLOURBG)
    COLUMNMAP = {}
    labels = {"name": "name", "modified": "modified", "type": "type", "size": "size"}
    texty = EXPLORERTOP + (DETAILHEADERH // 2) - (FONTSIZESTATUS // 2)
    for column, x, width in detailcolumnrects():
        label = labels.get(column, column)
        drawtextttf(x + PAD, texty, label, COLOURMUTED, FONTSIZESTATUS, FONT)
        COLUMNMAP[(x, EXPLORERTOP, x + width, EXPLORERTOP + DETAILHEADERH)] = column
        drawline(x + width - 1, EXPLORERTOP + 3, x + width - 1, EXPLORERTOP + DETAILHEADERH - 3, COLOURMUTED)
    drawline(SIDEBARW + DIVW, EXPLORERTOP + DETAILHEADERH - 1, WINW, EXPLORERTOP + DETAILHEADERH - 1, COLOURMUTED)


def drawsidepane():

    global SIDEPROPERTIESPATH, SIDEPROPERTIESDROPDOWN
    global SIDEPROPERTIESDROPDOWNHOVER, SIDEPROPERTIESCONTROLS
    if not PROPERTIESPANE:
        return
    x = WINW - PROPERTIESW
    y = EXPLORERTOP
    h = WINH - EXPLORERTOP - STATUSH
    fillrectfast(x, y, PROPERTIESW, h, COLOURBG)
    drawline(x, y, x, y + h, COLOURMUTED)

    drawtextttf(x + PAD, y + PAD, "properties", COLOURTEXT, FONTSIZEROW, FONT)
    item = None
    if SELECTED:
        item = next((entry for entry in TREE if entry.get("path") == SELECTED), None)
        if item is None and os.path.exists(SELECTED):
            item = enrichitem(os.path.basename(SELECTED), SELECTED)
    SIDEPROPERTIESCONTROLS = {}
    if item is None:
        SIDEPROPERTIESPATH = None
        SIDEPROPERTIESDROPDOWN = False
        SIDEPROPERTIESDROPDOWNHOVER = None
        drawtextttf(x + PAD, y + PAD + ROWH, "no item selected", COLOURMUTED, FONTSIZESTATUS, FONT)
        return

    itempath = item.get("path")
    if itempath != SIDEPROPERTIESPATH:
        SIDEPROPERTIESPATH = itempath
        SIDEPROPERTIESDROPDOWN = False
        SIDEPROPERTIESDROPDOWNHOVER = None

    liney = y + PAD + ROWH
    lines = [
        "name: " + str(item.get("displayname", item.get("name", ""))),
        "type: " + str(item.get("type", "")),
        "size: " + str(item.get("sizestr", "")),
        "modified: " + str(item.get("modifiedstr", "")),
        "created: " + formatfiletime(item.get("created", 0)),
        "location: " + formatlocation(item.get("path", CWD)),
    ]

    maxw = PROPERTIESW - (PAD * 2)
    boxsize = scalesize(16)
    controlsheight = (FONTSIZESTATUS + 5) + ROWH + PAD + max(FONTSIZESTATUS, boxsize) + (PAD * 2)
    controls_top = max(y + PAD + ROWH, y + h - controlsheight)
    metadatacomplete = True
    for value in lines:
        wrapped = wrapconfirmtext(str(value), maxw, FONTSIZESTATUS, FONT) if value else [""]
        for line in wrapped:
            if liney + FONTSIZESTATUS >= controls_top:
                metadatacomplete = False
                break
            drawtextttf(x + PAD, liney, line, COLOURMUTED, FONTSIZESTATUS, FONT)
            liney += FONTSIZESTATUS + 5
        if not metadatacomplete:
            break

    liney = controls_top
    drawtextttf(x + PAD, liney, "mode", COLOURMUTED, FONTSIZESTATUS, FONT)
    liney += FONTSIZESTATUS + 5
    moderect = [x + PAD, liney, maxw, ROWH]
    mode = stat.S_IMODE(int(item.get("mode", 0)))
    drawpropertiesdropdown(
        moderect, propertiesmodelabel(mode, bool(item.get("isdir"))),
        opened=SIDEPROPERTIESDROPDOWN,
    )
    SIDEPROPERTIESCONTROLS["mode"] = moderect

    liney += ROWH + PAD
    drawtextttf(x + PAD, liney, "hidden", COLOURMUTED, FONTSIZESTATUS, FONT)
    box = [x + PROPERTIESW - PAD - boxsize, liney, boxsize, boxsize]
    drawrect(*box, COLOURTEXT)
    if hiddenattribute(itempath):
        drawline(box[0] + 3, box[1] + box[3] // 2, box[0] + box[2] // 2, box[1] + box[3] - 4, COLOURTEXT)
        drawline(box[0] + box[2] // 2, box[1] + box[3] - 4, box[0] + box[2] - 3, box[1] + 3, COLOURTEXT)
    SIDEPROPERTIESCONTROLS["hidden"] = [x + PAD, liney - PAD, maxw, ROWH + PAD]

    if SIDEPROPERTIESDROPDOWN:
        options = propertiesmodeoptions(bool(item.get("isdir")))
        popup, _ = gfx.dropdownpopuprect(moderect, len(options), WINH - STATUSH, rowheight=ROWH, maximumvisible=8)
        selected = next((index for index, option in enumerate(options) if option[0] == mode), None)
        drawpropertiesdropdownmenu(
            popup, [label for _, label in options],
            selected=selected, hovered=SIDEPROPERTIESDROPDOWNHOVER,
        )
        SIDEPROPERTIESCONTROLS["modepopup"] = popup


def sidepropertiespointer(msg):

    global SIDEPROPERTIESDROPDOWN, SIDEPROPERTIESDROPDOWNHOVER
    if not msg.get("pressed"):
        return False

    x, y = int(msg.get("x", 0)), int(msg.get("y", 0))
    insidepane = (
        PROPERTIESPANE
        and WINW - PROPERTIESW <= x < WINW
        and EXPLORERTOP <= y < WINH - STATUSH
    )

    def inside(rect):
        return bool(rect and rect[0] <= x < rect[0] + rect[2] and rect[1] <= y < rect[1] + rect[3])

    if SIDEPROPERTIESDROPDOWN:
        item = next((entry for entry in TREE if entry.get("path") == SIDEPROPERTIESPATH), None)
        options = propertiesmodeoptions(bool(item and item.get("isdir")))
        popup = SIDEPROPERTIESCONTROLS.get("modepopup")
        index = gfx.dropdownindexat(x, y, popup, len(options), rowheight=ROWH) if popup else None
        if index is not None and SIDEPROPERTIESPATH:
            if setpathpropertiesmode(SIDEPROPERTIESPATH, options[index][0]):
                SIDEPROPERTIESDROPDOWN = False
            return True
        SIDEPROPERTIESDROPDOWN = False
        SIDEPROPERTIESDROPDOWNHOVER = None
        invalidaterect(0, 0, WINW, WINH)

    if not insidepane:
        return False
    if int(msg.get("button", 1)) != 1:
        return True
    if inside(SIDEPROPERTIESCONTROLS.get("mode")) and SIDEPROPERTIESPATH:
        SIDEPROPERTIESDROPDOWN = True
        SIDEPROPERTIESDROPDOWNHOVER = None
    elif inside(SIDEPROPERTIESCONTROLS.get("hidden")) and SIDEPROPERTIESPATH:
        setpathpropertieshidden(SIDEPROPERTIESPATH, not hiddenattribute(SIDEPROPERTIESPATH))
    invalidaterect(0, 0, WINW, WINH)
    return True


def sidepropertiespointermotion(x, y):

    global SIDEPROPERTIESDROPDOWNHOVER
    if not SIDEPROPERTIESDROPDOWN:
        return False
    item = next((entry for entry in TREE if entry.get("path") == SIDEPROPERTIESPATH), None)
    options = propertiesmodeoptions(bool(item and item.get("isdir")))
    popup = SIDEPROPERTIESCONTROLS.get("modepopup")
    hovered = gfx.dropdownindexat(x, y, popup, len(options), rowheight=ROWH) if popup else None
    if hovered != SIDEPROPERTIESDROPDOWNHOVER:
        SIDEPROPERTIESDROPDOWNHOVER = hovered
        invalidaterect(0, 0, WINW, WINH)
    return True


def drawregion(x, y, w, h):

    # clear only the dirty area first
    fillrectfast(
        int(x),
        int(y),
        int(w),
        int(h),
        COLOURBG
    )

    # header overlap
    if y < HEADERH:
        drawheader()
        drawsearchbox()

    if (x + w) > (SIDEBARW + DIVW) and y < EXPLORERTOP and (y + h) > HEADERH:
        drawtopbar()

    if VIEWMODE == "details" and y < CONTENTTOP and (y + h) > EXPLORERTOP:
        drawdetailsheader()

    # sidebar/divider overlap
    if x < (SIDEBARW + DIVW):
        drawsidebar()
        drawdivider()

    # main tree overlap: redraw intersecting rows only
    mainx = SIDEBARW + DIVW

    mainy = CONTENTTOP

    mainh = WINH - CONTENTTOP - STATUSH

    if x < (mainx + (WINW - mainx)) and (x + w) > mainx and y < (mainy + mainh) and (y + h) > mainy:

        start = SCROLL

        end = min(SCROLL + VISIBLECOUNT, len(TREE))

        for i in range(start, end):

            rr = rowrect(i)

            if rr is None:
                continue

            rx, ry, rw, rh = rr

            if (ry + rh) <= y:
                continue

            if ry >= (y + h):
                continue

            drawrow(i)

    if PROPERTIESPANE and (x + w) > (WINW - PROPERTIESW) and y < (WINH - STATUSH) and (y + h) > EXPLORERTOP:
        drawsidepane()


    # drag box overlay (not part of rows, must be drawn explicitly in dirty renderer)
    r = dragboxrect()

    if r is not None:

        bx, by, bw, bh = r

        if (bx + bw) > x and bx < (x + w) and (by + bh) > y and by < (y + h):

            drawrect(bx, by, bw, bh, COLOURTEXT)

    # scrollbars/status overlap
    vx, vy, vw, vh = vscrolltrackgeometry()
    if (x + w) > vx and x < (vx + vw) and (y + h) > vy and y < (vy + vh):
        drawvscrollbar()

    if (y + h) > (WINH - STATUSH - HSCROLL_HEIGHT) and y < (WINH - STATUSH) and (x + w) > (SIDEBARW + DIVW):
        drawhscrollbar()

    if (y + h) > (WINH - STATUSH):

        drawstatus()

        drawstatusmenu()

        drawcontextmenu()

    drawconfirm()

    drawproperties()

    drawinput()

    drawdragtarget()


def drawbg():

    # fill entire window background
    fillrectfast(
        0,
        0,
        WINW,
        WINH,
        COLOURBG
    )


def drawheader():

    global CARETOFFSETY

    # header background (single block)
    fillrectfast(
        0,
        0,
        WINW,
        HEADERH,
        COLOURBG
    )

    # reset header click map each draw
    HEADERMAP.clear()

    # header text baseline
    textx = SIDEBARW + DIVW + PAD

    searchx, _, _, _ = searchboxrect()

    addressright = max(textx, searchx - PAD)

    texty = (HEADERH // 2) - (FONTSIZEHEADER // 2)

    # back/forward (use sidebar x and header text y)
    navx = PAD + 14

    backw = measuretext("<", FONTSIZEHEADER, FONT)

    if backw <= 0:
        backw = max(10, (FONTSIZEHEADER // 2))

    forw_w = measuretext(">", FONTSIZEHEADER, FONT)

    if forw_w <= 0:
        forw_w = max(10, (FONTSIZEHEADER // 2))

    navgap = 14

    backcolour = COLOURTEXT if navcanback() else COLOURMUTED

    forwcolour = COLOURTEXT if navcanforward() else COLOURMUTED

    drawtextttf(
        navx,
        texty,
        "<",
        backcolour,
        FONTSIZEHEADER,
        FONT
    )

    drawtextttf(
        navx + int(backw) + navgap,
        texty,
        ">",
        forwcolour,
        FONTSIZEHEADER,
        FONT
    )

    # hit rects (full header height like breadcrumbs)
    backx0 = int(navx)

    backx1 = int(navx + int(backw) + navgap)

    forwx0 = int(navx + int(backw) + navgap)

    forwx1 = int(forwx0 + int(forw_w) + navgap)

    HEADERMAP[(backx0, 0, backx1, HEADERH)] = "__nav_back__"

    HEADERMAP[(forwx0, 0, forwx1, HEADERH)] = "__nav_forward__"

    # available width so header never runs off
    availw = addressright - textx

    if availw < 0:
        availw = 0

    # EDIT MODE (single editable line)
    if HEADEREDIT:

        try:

            # The numeric drive is part of the editable location so users can
            # navigate directly between drives (for example, 2/photos).
            drivew = 0
            avail2 = availw

            if avail2 < 10:
                avail2 = 10

            editx = textx

            # compute visible window for path-only text
            viewstart, shown, prefix = headercomputeview(avail2)

            x = editx

            if prefix:

                drawtextttf(
                    x,
                    texty,
                    "…",
                    COLOURMUTED,
                    FONTSIZEHEADER,
                    FONT
                )

                try:

                    x += measuretext("…", FONTSIZEHEADER, FONT)

                except Exception:

                    x += max(8, (FONTSIZEHEADER // 2))

            # selection highlight (only what is visible) + inverted text, matching directory chip style
            if headerhasselection():

                a, b = headernormsel()

                if a is not None:

                    # clamp selection to visible range
                    va = max(a, viewstart)

                    vb = min(b, viewstart + len(shown))

                    if vb > va:

                        pre = HEADEREDITTEXT[viewstart:va]

                        mid = HEADEREDITTEXT[va:vb]

                        post = HEADEREDITTEXT[vb:viewstart + len(shown)]

                        try:

                            prew = measuretext(pre, FONTSIZEHEADER, FONT)

                        except Exception:

                            prew = 0

                        try:

                            midw = measuretext(mid, FONTSIZEHEADER, FONT)

                        except Exception:

                            midw = 0

                        try:

                            if prew < 0:

                                prew = 0

                        except Exception:

                            prew = 0

                        try:

                            if midw < 0:

                                midw = 0

                        except Exception:

                            midw = 0

                        # draw pre text
                        drawtextttf(
                            x,
                            texty,
                            pre,
                            COLOURTEXT,
                            FONTSIZEHEADER,
                            FONT
                        )

                        # draw chip background for selection (match directory chip colours)
                        pad = 6

                        chiph = FONTSIZEHEADER + 6

                        chipy = (HEADERH // 2) - (chiph // 2)

                        try:

                            fillrectfast(
                                int(x + int(prew) - pad),
                                int(chipy),
                                int(midw) + (pad * 2),
                                int(chiph),
                                COLOURTEXT
                            )

                        except Exception:

                            pass

                        try:

                            drawrect(
                                int(x + int(prew) - pad),
                                int(chipy),
                                int(midw) + (pad * 2),
                                int(chiph),
                                COLOURTEXT
                            )

                        except Exception:

                            pass

                        # draw selected text inverted
                        drawtextttf(
                            x + int(prew),
                            texty,
                            mid,
                            COLOURBG,
                            FONTSIZEHEADER,
                            FONT
                        )

                        # draw post text
                        drawtextttf(
                            x + int(prew) + int(midw),
                            texty,
                            post,
                            COLOURTEXT,
                            FONTSIZEHEADER,
                            FONT
                        )

                    else:

                        # no visible selection width, draw whole text normally
                        drawtextttf(
                            x,
                            texty,
                            shown,
                            COLOURTEXT,
                            FONTSIZEHEADER,
                            FONT
                        )

                else:

                    # selection normalisation failed, draw whole text normally
                    drawtextttf(
                        x,
                        texty,
                        shown,
                        COLOURTEXT,
                        FONTSIZEHEADER,
                        FONT
                    )

            else:

                # no selection, draw whole text normally
                drawtextttf(
                    x,
                    texty,
                    shown,
                    COLOURTEXT,
                    FONTSIZEHEADER,
                    FONT
                )

            # caret blink
            caret = clamp(HEADERCARETPOS, 0, len(HEADEREDITTEXT))

            # caret x is width of visible prefix to caret
            if caret < viewstart:
                caretx = x

            else:

                sub = HEADEREDITTEXT[viewstart:caret]

                caretx = x + int(measuretext(sub, FONTSIZEHEADER, FONT))

            t = nowms()

            if (t // HEADERBLINKMS) % 2 == 0:

                try:

                    miny, maxy = ttfbbox("Ag", FONTSIZEHEADER, fontpath=FONT)

                    y0 = int(texty + int(miny))

                    y1 = int(texty + int(maxy))

                    if y0 < 2:
                        y0 = 2

                    if y1 > HEADERH - 2:
                        y1 = HEADERH - 2

                    if y1 <= y0:

                        y0 = max(2, int(texty))

                        y1 = min(HEADERH - 2, int(texty) + FONTSIZEHEADER)

                except Exception:

                    y0 = max(2, int(texty))

                    y1 = min(HEADERH - 2, int(texty) + FONTSIZEHEADER)

                carety = y0 + CARETOFFSETY

                drawline(
                    int(caretx),
                    carety,
                    int(caretx),
                    y1,
                    COLOURTEXT
                )

            # clickable rect for "the whole address"
            HEADERMAP[(textx, 0, addressright, HEADERH)] = "__header_edit__"

            return

        except Exception:

            return

    # NORMAL MODE (breadcrumbs)
    try:

        # Build breadcrumbs relative to the drive mount, not the host root.
        active = driveforpath(CWD)
        raw = driverelpath(CWD, active)

        # strip any leading slash for display composition
        if raw.startswith("/"):
            raw = raw[1:]

        # build breadcrumb parts: drive + path segments
        parts = []

        parts.append(str(active.get("number", 1)))

        if raw != "":

            for seg in raw.split("/"):

                try:

                    if seg != "":
                        parts.append(seg)

                except Exception:

                    continue

        # measure separator width once (TTF accurate)
        slashw = measuretext("/", FONTSIZEHEADER, FONT)

        if slashw <= 0:
            slashw = max(1, (FONTSIZEHEADER // 2))

        x = textx

        # render each part, track clickable rectangles, but do not overflow window
        for i, part in enumerate(parts):

            try:

                partw = measuretext(part, FONTSIZEHEADER, FONT)

                if partw <= 0:
                    partw = len(part) * max(1, (FONTSIZEHEADER // 2))

                # stop if no space left
                if (x - textx) + partw > availw:

                    # show a tail marker so it never runs off
                    drawtextttf(
                        x,
                        texty,
                        "…",
                        COLOURMUTED,
                        FONTSIZEHEADER,
                        FONT
                    )

                    # make the remaining header area a single hit rect for edit
                    HEADERMAP[(textx, 0, addressright, HEADERH)] = "__header_edit__"
                    return

                # draw the part
                drawtextttf(
                    x,
                    texty,
                    part,
                    COLOURTEXT,
                    FONTSIZEHEADER,
                    FONT
                )

                # compute target path
                if i == 0:
                    target = drivepath(active.get("number", 1), "/")
                else:
                    joined = "/".join(parts[1:i + 1])
                    target = drivepath(active.get("number", 1), f"/{joined}")

                x1 = x + partw

                # root display needs a trailing slash after drive: "1/"
                if i == 0 and len(parts) == 1:

                    if (x1 - textx) + slashw <= availw:

                        drawtextttf(
                            x1,
                            texty,
                            "/",
                            COLOURTEXT,
                            FONTSIZEHEADER,
                            FONT
                        )

                        x1 += slashw

                # store hit rect spanning the header height
                HEADERMAP[(x, 0, x1, HEADERH)] = target

                # commit advance
                x = x1

                # draw separator if not last and it fits
                if i < len(parts) - 1:

                    if (x - textx) + slashw > availw:

                        drawtextttf(
                            x,
                            texty,
                            "…",
                            COLOURMUTED,
                            FONTSIZEHEADER,
                            FONT
                        )

                        HEADERMAP[(textx, 0, addressright, HEADERH)] = "__header_edit__"
                        return

                    drawtextttf(
                        x,
                        texty,
                        "/",
                        COLOURTEXT,
                        FONTSIZEHEADER,
                        FONT
                    )

                    x += slashw

            except Exception:

                continue

        # also map the whole address area so double click anywhere works
        HEADERMAP[(textx, 0, addressright, HEADERH)] = "__header_edit__"

    except Exception:

        return


def drawsidebar():

    y = HEADERH

    x = PAD + 14

    for index, link in enumerate(SIDEBARLINKS):

        try:

            if link.get("isspacer"):
                y += ROWH
                continue

            label = link.get("label", "")

            colour = COLOURTEXT if link.get("available", True) else COLOURMUTED

            if index == SIDEBARHOVERINDEX:
                hoverwidth = max(1, SIDEBARW)
                fillrectfast(0, y, hoverwidth, ROWH, COLOURSTATUS)
                fillrectfast(0, y, hoverwidth, 1, COLOURROWOUTLINE)
                fillrectfast(0, y + ROWH - 1, hoverwidth, 1, COLOURROWOUTLINE)

            try:
                if link.get("path") and _physicalnormalize(link.get("path")) == _physicalnormalize(CWD):
                    colour = COLOURTEXT
                    labelw = max(0, measuretext(label, FONTSIZEROW, FONT))
                    drawline(x, y + ROWH - 2, x + labelw, y + ROWH - 2, COLOURTEXT)
            except Exception:
                pass

            drawtextttf(
                x,
                y + (ROWH // 2) - (FONTSIZEROW // 2),
                label,
                colour,
                FONTSIZEROW,
                FONT
            )

            y += ROWH

        except Exception:

            y += ROWH
            continue


def drawdivider():

    # Permanently occupy the layout strip between the sidebar and right pane.
    # A solid rectangle remains crisp in both CPU and managed rendering modes.
    top = HEADERH
    height = max(0, WINH - STATUSH - top)
    if height > 0:
        fillrectfast(SIDEBARW, top, max(1, DIVW), height, COLOURROWOUTLINE)


def drawchevrondown(x, y, size, fontpath, color):

    try:

        # measure the advance width of ">" at this font size
        advw = measuretext(">", size, fontpath)

    except Exception:

        advw = 0

    try:

        # get the exact rendered bbox for ">" at this size
        miny, maxy = ttfbbox(">", size, fontpath=fontpath)

    except Exception:

        miny = 0

        maxy = int(size)

    try:

        # derive the exact rectangle that drawtextttf would occupy for ">"
        x0 = int(x)

        y0 = int(y + int(miny))

        w = int(advw)

        if w <= 0:
            w = max(6, int(size) // 2)

        h = int(maxy - miny)

        if h <= 0:
            h = int(size)

        x1 = x0 + w - 1

        y1 = y0 + h - 1

    except Exception:

        x0 = int(x)

        y0 = int(y)

        x1 = x0 + 6

        y1 = y0 + 6

    # padding so the chevron doesn't touch bbox edges
    pad = 1

    if (x1 - x0) >= 10:
        pad = 2

    if (y1 - y0) >= 10 and pad < 2:
        pad = 2

    lx = x0 + pad

    rx = x1 - pad

    ty = y0 + pad

    by = y1 - pad

    if rx <= lx:
        rx = lx + 1

    if by <= ty:
        by = ty + 1

    mx = (lx + rx) // 2

    # left stroke
    drawline(
        lx,
        ty,
        mx,
        by,
        color
    )

    # right stroke
    drawline(
        rx,
        ty,
        mx,
        by,
        color
    )


def drawtree():

    start = SCROLL

    end = min(SCROLL + VISIBLECOUNT, len(TREE))

    y = CONTENTTOP

    try:

        xscroll = HSCROLL

    except Exception:

        xscroll = 0

    for i in range(start, end):

        item = TREE[i]

        try:

            rowy = y

            selectedrow = item["path"] in SELECTEDSET

            if selectedrow:
                rowx = SIDEBARW + DIVW
                roww = max(0, VISIBLEWIDTH)
                fillrectfast(rowx, rowy, roww, ROWH, COLOURSTATUS)
                if roww > 0 and ROWH > 0:
                    fillrectfast(rowx, rowy, roww, 1, COLOURROWOUTLINE)
                    fillrectfast(rowx, rowy + ROWH - 1, roww, 1, COLOURROWOUTLINE)

            # base x (NO horizontal scroll here)
            basex = SIDEBARW + DIVW + PAD + (item["depth"] * TREEINDENT) + (scalesize(18) if SHOWITEMCHECKS else 0)

            # always reserve arrow width
            arrowspace = ARROWW

            if item["isdir"]:

                topy = rowy + (ROWH // 2) - (FONTSIZEROW // 2)

                if item["haskids"]:

                    if item["expanded"]:

                        drawchevrondown(
                            basex,
                            topy,
                            FONTSIZEROW,
                            FONT,
                            COLOURTEXT
                        )

                    else:

                        drawtextttf(
                            basex,
                            topy,
                            ">",
                            COLOURTEXT,
                            FONTSIZEROW,
                            FONT
                        )

                else:

                    drawtextttf(
                        basex,
                        topy,
                        ">",
                        COLOURMUTED,
                        FONTSIZEROW,
                        FONT
                    )

            # name column starts AFTER the arrow gutter, and never moves left
            namex = basex + arrowspace

            namey = rowy + (ROWH // 2) - (FONTSIZEROW // 2)

            # compute available width inside main pane for this row
            paneleft = SIDEBARW + DIVW

            paneright = paneleft + VISIBLEWIDTH

            availw = int(paneright - namex)

            if availw < 0:
                availw = 0

            # ------------------------------------------------------------
            # rename edit row (windows explorer style)
            # ------------------------------------------------------------
            if RENAMEEDIT and item["path"] == RENAMEPATH:

                try:

                    boxpad = 2

                    boxh = FONTSIZEROW + 6

                    boxy = rowy + (ROWH // 2) - (boxh // 2)

                    boxw = int(availw)

                    if boxw < 0:
                        boxw = 0

                    # background + border
                    fillrectfast(
                        namex - boxpad,
                        boxy,
                        boxw + (boxpad * 2),
                        boxh,
                        COLOURSTATUS if item["path"] in SELECTEDSET else COLOURBG
                    )

                    # caret visibility (simple pixel scroll)
                    try:

                        pre = RENAMETEXT[:RENAMECARETPOS]

                    except Exception:

                        pre = ""

                    try:

                        prew = measuretext(pre, FONTSIZEROW, FONT)

                    except Exception:

                        prew = 0

                    innerw = int(boxw - 4)

                    if innerw < 0:
                        innerw = 0

                    if prew > innerw:

                        editscroll = int(prew - innerw)

                    else:

                        editscroll = 0

                    shown = textview(RENAMETEXT, FONTSIZEROW, FONT, int(editscroll), int(innerw))

                    drawtextttf(namex + 2, namey, shown, COLOURTEXT, FONTSIZEROW, FONT)

                    drawrenameselection(namex, namey, boxy, boxh, innerw, editscroll)

                    # caret
                    caretpx = (namex + 2) + int(prew - editscroll)

                    if caretpx < (namex + 2):
                        caretpx = (namex + 2)

                    if caretpx > (namex + 2 + innerw):
                        caretpx = (namex + 2 + innerw)

                    t = nowms()

                    if (t // RENAMEBLINKMS) % 2 == 0:

                        drawline(caretpx, boxy + 2, caretpx, boxy + boxh - 2, COLOURTEXT)

                except Exception:

                    pass

            else:

                # apply horizontal scroll ONLY to the filename content
                shown = textview(item.get("displayname", item["name"]), FONTSIZEROW, FONT, int(xscroll), availw)

                textcolour = COLOURMUTED if item["path"] in CUTSET else COLOURTEXT

                # item name (clipped/viewported)
                drawtextttf(
                    namex,
                    namey,
                    shown,
                    textcolour,
                    FONTSIZEROW,
                    FONT
                )

        except Exception:

            pass

        y += ROWH


def pickerfittext(value, width):

    text = str(value)
    if width <= 0:
        return ""
    if measuretext(text, FONTSIZESTATUS, FONT) <= width:
        return text
    suffix = "…"
    while text and measuretext(text + suffix, FONTSIZESTATUS, FONT) > width:
        text = text[:-1]
    return text + suffix if text else suffix


def drawpickerstatus():

    PICKERMAP.clear()
    statusy = WINH - STATUSH
    fillrectfast(0, statusy, WINW, STATUSH, COLOURSTATUS)
    fillrectfast(0, statusy, WINW, 1, COLOURDIVIDER)

    margin = PAD
    buttonh = max(scalesize(28), ROWH)
    buttony = statusy + STATUSH - PAD - buttonh
    primarylabel = pickerprimarylabel()
    primaryw = max(scalesize(84), measuretext(primarylabel, FONTSIZESTATUS, FONT) + PAD * 3)
    cancelw = max(scalesize(72), measuretext("cancel", FONTSIZESTATUS, FONT) + PAD * 3)
    primaryx = WINW - PAD - primaryw
    cancelx = primaryx - PAD - cancelw

    def button(identifier, label, x, width, enabled=True):
        colour = COLOURTEXT if enabled else COLOURMUTED
        drawrect(x, buttony, width, buttonh, colour)
        textw = measuretext(label, FONTSIZESTATUS, FONT)
        drawtextttf(
            x + max(1, (width - textw) // 2),
            buttony + (buttonh // 2) - (FONTSIZESTATUS // 2) - 1,
            label,
            colour,
            FONTSIZESTATUS,
            FONT,
        )
        if enabled:
            PICKERMAP[(x, buttony, x + width, buttony + buttonh)] = identifier

    button("cancel", "cancel", cancelx, cancelw, True)

    enabled = True
    if PICKERMODE == "open_file":
        enabled = any(os.path.isfile(path) and pickerpathmatches(path) for path in selectedpaths())
    elif PICKERMODE == "save_location":
        enabled = pickerwritabledirectory(CWD)
    elif PICKERMODE == "save_as":
        enabled = bool(PICKERNAME.strip()) and pickerwritabledirectory(CWD)
    button("confirm", primarylabel, primaryx, primaryw, enabled)

    controlsleft = cancelx
    if PICKERMODE in ("select_tier", "save_location", "save_as"):
        newlabel = "new tier"
        neww = max(scalesize(84), measuretext(newlabel, FONTSIZESTATUS, FONT) + PAD * 3)
        newx = cancelx - PAD - neww
        button("newtier", newlabel, newx, neww, pickerwritabledirectory(CWD))
        controlsleft = newx

    rightedge = controlsleft - PAD
    filterw = 0
    if PICKERMODE in ("open_file", "save_as") and PICKERFILTERS:
        filterlabel = pickeractivefilter().get("label", "files")
        filterw = min(scalesize(180), max(scalesize(100), measuretext(filterlabel, FONTSIZESTATUS, FONT) + PAD * 3))
        filterx = rightedge - filterw
        button("filter", pickerfittext(filterlabel, filterw - PAD * 2), filterx, filterw, len(PICKERFILTERS) > 1)
        rightedge = filterx - PAD

    if statusactive():
        drawtextttf(
            margin,
            buttony + (buttonh // 2) - (FONTSIZESTATUS // 2) - 1,
            pickerfittext(STATUSMESSAGE, max(1, rightedge - margin)),
            COLOURERROR if STATUSMESSAGEERROR else COLOURTEXT,
            FONTSIZESTATUS,
            FONT,
        )
        return

    labely = statusy + max(2, PAD // 2)
    if PICKERMODE == "save_as":
        drawtextttf(margin, labely, "file name", COLOURMUTED, FONTSIZESTATUS, FONT)
        fieldy = buttony
        fieldw = max(scalesize(80), rightedge - margin)
        drawrect(margin, fieldy, fieldw, buttonh, COLOURTEXT if PICKERNAMEFOCUSED else COLOURMUTED)
        shown = pickerfittext(PICKERNAME, max(1, fieldw - PAD * 2))
        textx = margin + PAD
        texty = fieldy + (buttonh // 2) - (FONTSIZESTATUS // 2) - 1
        selection = pickernameselection() if PICKERNAMEFOCUSED else None
        if selection is not None and shown == PICKERNAME:
            start, end = selection
            prefixw = measuretext(PICKERNAME[:start], FONTSIZESTATUS, FONT)
            selectionw = measuretext(PICKERNAME[:end], FONTSIZESTATUS, FONT) - prefixw
            fillrectfast(textx + prefixw, fieldy + 4, selectionw, buttonh - 8, COLOURTEXT)
            drawtextttf(textx, texty, PICKERNAME[:start], COLOURTEXT, FONTSIZESTATUS, FONT)
            drawtextttf(textx + prefixw, texty, PICKERNAME[start:end], COLOURHILITETEXT, FONTSIZESTATUS, FONT)
            drawtextttf(textx + prefixw + selectionw, texty, PICKERNAME[end:], COLOURTEXT, FONTSIZESTATUS, FONT)
        elif selection is not None and shown:
            selectionw = min(fieldw - PAD * 2, measuretext(shown, FONTSIZESTATUS, FONT))
            fillrectfast(textx, fieldy + 4, selectionw, buttonh - 8, COLOURTEXT)
            drawtextttf(textx, texty, shown, COLOURHILITETEXT, FONTSIZESTATUS, FONT)
        else:
            drawtextttf(textx, texty, shown, COLOURTEXT, FONTSIZESTATUS, FONT)
        PICKERMAP[(margin, fieldy, margin + fieldw, fieldy + buttonh)] = "name"
        if PICKERNAMEFOCUSED and (nowms() // HEADERBLINKMS) % 2 == 0:
            prefix = PICKERNAME[:PICKERNAMECARETPOS]
            caret = min(fieldw - PAD, measuretext(prefix, FONTSIZESTATUS, FONT))
            drawline(margin + PAD + caret, fieldy + 5, margin + PAD + caret, fieldy + buttonh - 5, COLOURTEXT)
        return

    if PICKERMODE == "open_file":
        paths = [path for path in selectedpaths() if os.path.isfile(path) and pickerpathmatches(path)]
        summary = ", ".join(os.path.basename(path) for path in paths) if paths else "select a file"
        label = "selected file"
    elif PICKERMODE == "select_tier":
        path = SELECTED if SELECTED and os.path.isdir(SELECTED) else CWD
        summary = formatlocation(path)
        label = "selected tier"
    else:
        summary = formatlocation(CWD)
        label = "save location"

    drawtextttf(margin, labely, label, COLOURMUTED, FONTSIZESTATUS, FONT)
    drawtextttf(
        margin,
        buttony + (buttonh // 2) - (FONTSIZESTATUS // 2) - 1,
        pickerfittext(summary, max(1, rightedge - margin)),
        COLOURTEXT,
        FONTSIZESTATUS,
        FONT,
    )


def pickerfooterhit(x, y):

    for rect, action in PICKERMAP.items():
        x0, y0, x1, y1 = rect
        if x0 <= x <= x1 and y0 <= y <= y1:
            return action
    return None


def pickernamecaretfromx(x):

    field = next((rect for rect, action in PICKERMAP.items() if action == "name"), None)
    if field is None:
        return len(PICKERNAME)

    try:
        localx = int(x) - int(field[0]) - PAD
    except Exception:
        return len(PICKERNAME)

    if localx <= 0:
        return 0

    previous = 0
    for index in range(1, len(PICKERNAME) + 1):
        current = max(previous, measuretext(PICKERNAME[:index], FONTSIZESTATUS, FONT))
        if localx < previous + ((current - previous) / 2.0):
            return index - 1
        previous = current

    return len(PICKERNAME)


def pickernameselection():

    if PICKERNAMESELECTALL and PICKERNAME:
        return 0, len(PICKERNAME)
    if PICKERNAMESELANCHOR is None or PICKERNAMESELANCHOR == PICKERNAMECARETPOS:
        return None
    return tuple(sorted((PICKERNAMESELANCHOR, PICKERNAMECARETPOS)))


def deletepickernameselection():

    global PICKERNAME, PICKERNAMECARETPOS, PICKERNAMESELECTALL, PICKERNAMESELANCHOR

    selection = pickernameselection()
    if selection is None:
        return False
    start, end = selection
    PICKERNAME = PICKERNAME[:start] + PICKERNAME[end:]
    PICKERNAMECARETPOS = start
    PICKERNAMESELECTALL = False
    PICKERNAMESELANCHOR = None
    return True


def drawstatus():

    if PICKERMODE:
        drawpickerstatus()
        return

    # status bar background
    statusy = WINH - STATUSH
    fillrectfast(
        0,
        statusy,
        WINW,
        STATUSH,
        COLOURSTATUS
    )

    # A subtle top edge keeps the dark-grey bar distinct from the black viewer.
    fillrectfast(0, statusy, WINW, 1, COLOURDIVIDER)

    x = STATUSXSTART

    # optical vertical centering correction for TTF baseline
    baselinefix = -4

    y = WINH - STATUSH + (STATUSH // 2) - (FONTSIZESTATUS // 2) + baselinefix

    ACTIONMAP.clear()

    if statusactive():

        colour = COLOURERROR if STATUSMESSAGEERROR else COLOURTEXT

        drawtextttf(
            x,
            y,
            STATUSMESSAGE,
            colour,
            FONTSIZESTATUS,
            FONT
        )

        return

    for slot in ACTIONSLOTS:

        try:

            aid = slot["id"]

            label = slot["label"]

            if aid == "reveal":
                label = "hide" if SHOWHIDDEN else "reveal"

            try:

                textw = measuretext(label, FONTSIZESTATUS, FONT)

            except Exception:

                textw = len(label) * max(1, (FONTSIZESTATUS // 2))

            try:

                slotw = int(textw) + PAD + PAD

            except Exception:

                slotw = (len(label) * max(1, (FONTSIZESTATUS // 2))) + PAD + PAD

            visible = False

            try:

                visible = bool(ACTIONVIS.get(aid, False))

            except Exception:

                visible = False

            if visible:

                drawtextttf(
                    x,
                    y,
                    label,
                    COLOURTEXT,
                    FONTSIZESTATUS,
                    FONT
                )

                ACTIONMAP[(x, y, x + slotw, y + FONTSIZESTATUS)] = aid

                try:

                    if aid == "new":
                        ACTIONMAP["new_anchor"] = (x, y, x + slotw, y + FONTSIZESTATUS)

                    if aid == "delete":
                        ACTIONMAP["delete_anchor"] = (x, y, x + slotw, y + FONTSIZESTATUS)

                except Exception:

                    pass

            # ALWAYS advance by the slot width (fixed positions)
            x += slotw + PAD

        except Exception:

            # still try to advance a little so later slots stay roughly stable
            try:
                x += 60
            except Exception:
                pass

    try:
        count = len(TREE)
        selected = [item for item in TREE if item.get("path") in SELECTEDSET]
        if selected:
            total = sum(int(item.get("size", 0)) for item in selected if not item.get("isdir"))
            summary = f"{len(selected)} selected"
            if total:
                summary += f"  {formatfilesize(total)}"
        else:
            summary = f"{count} item{'s' if count != 1 else ''}"
        width = measuretext(summary, FONTSIZESTATUS, FONT)
        drawtextttf(WINW - PAD - int(width), y, summary, COLOURMUTED, FONTSIZESTATUS, FONT)
    except Exception:
        pass


def drawstatusmenu():

    if not STATUSMENUOPEN:
        return

    panel = computestatusmenupanel()

    if panel is None:
        return

    px, py, pw, ph = panel

    fillrectfast(px, py, pw, ph, COLOURSTATUS)

    drawrect(px, py, pw, ph, COLOURDIVIDER)

    items = statusmenuitems()

    x = px + STATUSMENU_PAD_X

    y = py + STATUSMENU_PAD_Y

    for i, (label, _) in enumerate(items):

        iy = y + (i * STATUSMENU_ITEM_H)

        drawtextttf(
            x,
            iy + max(0, (STATUSMENU_ITEM_H - FONTSIZESTATUS) // 2),
            str(label),
            COLOURTEXT,
            FONTSIZESTATUS,
            FONT
        )

    return


def drawcontextmenu():

    if not CONTEXTMENUOPEN:
        return

    panel = computecontextmenupanel()

    if panel is None:
        return

    px, py, pw, ph = panel

    fillrectfast(px, py, pw, ph, COLOURCONTEXTBG)

    drawrect(px, py, pw, ph, COLOURCONTEXTDIVIDER)

    try:

        items = contextmenuitems()

    except Exception:

        items = []

    x = px + STATUSMENU_PAD_X

    y = py + CONTEXTMENU_PAD_Y

    for i, (label, actionid) in enumerate(items):

        iy = y + (i * STATUSMENU_ITEM_H)

        if actionid == CONTEXTMENUHOVERACTION:
            hoverx = px + 1
            hoverwidth = max(1, pw - 2)
            fillrectfast(hoverx, iy, hoverwidth, STATUSMENU_ITEM_H, COLOURSTATUS)
            fillrectfast(hoverx, iy, hoverwidth, 1, COLOURROWOUTLINE)
            fillrectfast(hoverx, iy + STATUSMENU_ITEM_H - 1, hoverwidth, 1, COLOURROWOUTLINE)

        drawtextttf(
            x,
            iy + max(0, (STATUSMENU_ITEM_H - FONTSIZESTATUS) // 2),
            str(label),
            COLOURCONTEXTTEXT,
            FONTSIZESTATUS,
            FONT
        )

        if i < len(items) - 1:
            fillrectfast(
                px,
                iy + STATUSMENU_ITEM_H - 1,
                pw,
                1,
                COLOURCONTEXTDIVIDER
            )

    return


def drawvscrollbar():

    if not verticalneeded():
        return

    geo = vscrollthumbgeometry()

    if geo is None:
        return

    _, track_x, track_y, track_w, track_h, thumb_y, thumb_h = geo

    # track
    fillrectfast(track_x, track_y, track_w, track_h, COLOURBG)

    drawrect(track_x, track_y, track_w, track_h, COLOURDIVIDER)

    # thumb
    fillrectfast(track_x, thumb_y, track_w, thumb_h, COLOURBG)

    drawrect(track_x, thumb_y, track_w, thumb_h, COLOURMUTED)


def drawhscrollbar():

    if not horizontalneeded():
        return

    geo = hscrollthumbgeometry()

    if geo is None:
        return

    _, track_x, track_y, track_w, track_h, thumb_x, thumb_w = geo

    # track
    fillrectfast(track_x, track_y, track_w, track_h, COLOURBG)

    drawrect(track_x, track_y, track_w, track_h, COLOURDIVIDER)

    # thumb
    fillrectfast(thumb_x, track_y, thumb_w, track_h, COLOURBG)

    drawrect(thumb_x, track_y, thumb_w, track_h, COLOURMUTED)


def present():

    # copy backbuffer into the window's shared buffer file
    gfxpresent()

    invalidaterect(0, 0, WINW, WINH)


def presentrect(x, y, w, h):

    managed = False

    try:

        managed = graphicspresent([int(x), int(y), int(w), int(h)])

    except Exception as e:

        log(f"managed graphics present error {e}")

    if managed or (GRAPHICSSTATE.get("available") and managedstrict(GRAPHICSSTATE)):
        return

    gfxpresentdirty(x, y, w, h)

    sendws({
        "op": "DAMAGE",
        "winid": WINID,
        "rect": [int(x), int(y), int(w), int(h)]
    })


# input functions
def columnresizehit(x, y):

    if VIEWMODE != "details" or y < EXPLORERTOP or y >= CONTENTTOP:
        return None

    for rect, column in COLUMNMAP.items():
        x0, y0, x1, y1 = rect

        if x >= x0 and x <= x1 and y >= y0 and y <= y1:
            if abs(int(x) - int(x1)) <= scalesize(5):
                return column

    return None


def updatecolumncursor(x, y):

    if COLUMNRESIZING is not None or columnresizehit(x, y) is not None:
        setpointercursor("resize_h")
    elif (
        searchboxhit(x, y) == "field"
        or pickerfooterhit(x, y) == "name"
        or renameeditrowat(x, y) is not None
    ):
        setpointercursor("text")
    else:
        setpointercursor("arrow")


def onpointermotion(msg):

    global VSCROLLDRAGGING, HSCROLLDRAGGING, SCROLL, HSCROLL, DRAGBOX
    global SIDEBARDRAGGING, SIDEBARDROPINDEX
    global PICKERNAMECARETPOS, PICKERNAMESELECTALL

    try:

        x = int(msg.get("x", 0))

    except Exception:

        x = 0

    try:

        y = int(msg.get("y", 0))

    except Exception:

        y = 0

    if PROPERTIESOPEN:
        propertiespointermotion(x, y)
        setpointercursor("arrow")
        return

    if INPUTOPEN:
        setpointercursor("arrow")
        return

    if sidepropertiespointermotion(x, y):
        setpointercursor("arrow")
        return

    updatecolumncursor(x, y)

    updatesidebarhover(x, y)

    updatecontextmenuhover(x, y)

    if PICKERNAMEDRAGGING:
        PICKERNAMECARETPOS = pickernamecaretfromx(x)
        PICKERNAMESELECTALL = False
        invalidaterect(0, WINH - STATUSH, WINW, STATUSH)
        return

    if COLUMNRESIZING is not None:
        COLUMNWIDTHS[COLUMNRESIZING] = max(50, min(900, int(COLUMNRESIZESTARTW) + int(x) - int(COLUMNRESIZESTARTX)))
        layout()
        invalidaterect(SIDEBARW + DIVW, HEADERH, WINW - SIDEBARW - DIVW, WINH - HEADERH - STATUSH)
        return

    if RENAMEEDIT and RENAMEDRAGGING:

        row = currentrenameeditrow()

        if row is not None:

            setrenamecaretfrommouse(row, x, shift=True)

            invalidateselectionrow(RENAMEPATH)

        return

    if SIDEBARDRAGSTART is not None and SIDEBARDRAGINDEX is not None:
        sx, sy = SIDEBARDRAGSTART
        if SIDEBARDRAGGING or (abs(x - sx) + abs(y - sy)) >= scalesize(8):
            SIDEBARDRAGGING = True
            SIDEBARDROPINDEX = max(0, min(len(SIDBARENTRIES) - 1, (y - HEADERH) // ROWH)) if SIDBARENTRIES else None
            invalidaterect(0, HEADERH, SIDEBARW, WINH - HEADERH - STATUSH)
            return

    if ITEMDRAGSTART is not None and itemdragmotion(x, y):
        return

    if DRAGBOX:

        updatedragbox(x, y)

        return

    if VSCROLLDRAGGING:

        geo = vscrollthumbgeometry()

        if geo is None:

            VSCROLLDRAGGING = False

            return

        _, track_x, track_y, track_w, track_h, thumb_y, thumb_h = geo

        total = len(TREE)

        visible = max(1, VISIBLECOUNT)

        maxscroll = max(0, total - visible)

        if maxscroll <= 0:

            VSCROLLDRAGGING = False

            return

        new_thumb_y = y - VSCROLL_DRAG_CURSOR_OFFSET

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

        SCROLL = int(round(frac * maxscroll))

        vscrollclamp()

        invalidaterect(0, 0, WINW, WINH)

        return

    if HSCROLLDRAGGING:

        geo = hscrollthumbgeometry()

        if geo is None:

            HSCROLLDRAGGING = False

            return

        _, track_x, track_y, track_w, track_h, thumb_x, thumb_w = geo

        maxscroll = max(0, CONTENTWIDTH - hscrollvisiblewidth())

        if maxscroll <= 0:

            HSCROLLDRAGGING = False

            return

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

            HSCROLL = int(round(frac * maxscroll))

        except Exception:

            pass

        hscrollclamp()

        invalidaterect(0, 0, WINW, WINH)

        return


def onpointerbutton(msg):

    global VSCROLLDRAGGING, HSCROLLDRAGGING, SCROLL, HSCROLL, STATUSMENUOPEN, STATUSMENUKIND, CONTEXTMENUOPEN, CONTEXTMENUKIND, RENAMESKIPNEXTCLICK, RENAMECARETPOS, RENAMEDRAGGING, RENAMESELANCHOR, ACTIONFROMCONTEXT, ACTIONCONTEXTTARGET, CONTEXTMENUTARGET
    global SIDEBARSELECTED, SIDEBARSELECTEDDRIVE
    global SIDEBARDRAGSTART, SIDEBARDRAGINDEX, SIDEBARDRAGGING, SIDEBARDROPINDEX
    global ITEMDRAGSTART, ITEMDRAGPATHS, ITEMDRAGTARGET, ITEMDRAGMODS, ITEMDRAGSTARTED
    global COLUMNRESIZING, COLUMNRESIZESTARTX, COLUMNRESIZESTARTW
    global SEARCHFOCUSED, SEARCHCARETPOS
    global PICKERNAMEFOCUSED, PICKERNAMECARETPOS, PICKERNAMESELECTALL, PICKERNAMESELANCHOR, PICKERNAMEDRAGGING

    if CONFIRMOPEN:

        confirmpointer(msg)

        return

    if PROPERTIESOPEN:
        propertiespointer(msg)
        return

    if INPUTOPEN:
        return

    if RENAMEEDIT and RENAMESKIPNEXTCLICK:

        RENAMESKIPNEXTCLICK = False

        return

    x = msg.get("x")

    y = msg.get("y")

    button = msg.get("button")

    pressed = msg.get("pressed")

    if pressed:
        cancelsmoothscroll()

    try:

        mods = msg.get("mods", {})

    except Exception:

        mods = {}

    try:

        ctrl = bool(mods.get("ctrl"))

        shift = bool(mods.get("shift"))

    except Exception:

        ctrl = False

        shift = False

    if PICKERMODE and not PICKERALLOWMULTIPLE:
        ctrl = False
        shift = False

    if not pressed:

        PICKERNAMEDRAGGING = False

        if COLUMNRESIZING is not None:
            COLUMNRESIZING = None
            updatecolumncursor(x, y)
            savesettings()
            invalidaterect(0, 0, WINW, WINH)
            return

        if SIDEBARDRAGSTART is not None:
            if SIDEBARDRAGGING and SIDEBARDROPINDEX is not None:
                sidebarmove(SIDEBARDRAGINDEX, SIDEBARDROPINDEX)
            SIDEBARDRAGSTART = None
            SIDEBARDRAGINDEX = None
            SIDEBARDRAGGING = False
            SIDEBARDROPINDEX = None
            invalidaterect(0, 0, WINW, WINH)
            return

        if ITEMDRAGSTART is not None:
            finishitemdrag()
            return

        VSCROLLDRAGGING = False

        HSCROLLDRAGGING = False

        RENAMEDRAGGING = False

        finishdragbox()

        return

    # A pending slow-click rename must yield to any new click. In particular,
    # the second press of a double click cancels rename before opening the item.
    cancelpendingrename()

    try:

        isright = (button == 3 or button == 2)

    except Exception:

        isright = False

    if PICKERMODE:
        if isright:
            return

        pickerhit = pickerfooterhit(x, y)
        if pickerhit == "cancel":
            pickercancel()
            return
        if pickerhit == "confirm":
            pickerconfirm()
            return
        if pickerhit == "filter":
            pickerfiltercycle()
            return
        if pickerhit == "newtier":
            runaction("newtier")
            return
        if pickerhit == "name":
            PICKERNAMEFOCUSED = True
            caret = pickernamecaretfromx(x)
            if not shift or PICKERNAMESELANCHOR is None:
                PICKERNAMESELANCHOR = caret
            PICKERNAMECARETPOS = caret
            PICKERNAMESELECTALL = False
            PICKERNAMEDRAGGING = True
            invalidaterect(0, WINH - STATUSH, WINW, STATUSH)
            return
        if PICKERNAMEFOCUSED:
            PICKERNAMEFOCUSED = False
            PICKERNAMESELECTALL = False
            PICKERNAMESELANCHOR = None
            invalidaterect(0, WINH - STATUSH, WINW, STATUSH)

    # click off rename row commits rename and exits edit
    if RENAMEEDIT:

        row = rowat(x, y)

        if row is None:

            renameconfirm()

            return

        try:

            item = TREE[row]

            if item["path"] != RENAMEPATH:

                renameconfirm()

                return

        except Exception:

            renameconfirm()

            return

        if not isright:

            editrow = renameeditrowat(x, y)

            if editrow is not None:

                metrics = renameeditmetrics(editrow)

                caret = renamecaretfromx(x, metrics)

                if shift:

                    moverenamecaretto(caret, shift=True)

                else:

                    RENAMECARETPOS = caret

                    RENAMESELANCHOR = caret

                RENAMEDRAGGING = True

                invalidateselectionrow(RENAMEPATH)

                return

    try:

        now = nowms()

    except Exception:

        now = 0

    if HEADEREDIT and not RENAMEEDIT:

        headereditend(cancel=True)

    hit = statusmenuhit(x, y)

    ch = contextmenuhit(x, y)

    # click-away closes status menu
    if STATUSMENUOPEN:

        # clicking the anchor is handled later (toggle logic)
        anchor = None

        if STATUSMENUKIND == "new":
            anchor = ACTIONMAP.get("new_anchor")

        elif STATUSMENUKIND == "delete":
            anchor = ACTIONMAP.get("delete_anchor")

        inside_anchor = False

        if anchor:

            ax0, ay0, ax1, ay1 = anchor

            inside_anchor = (x >= ax0 and x <= ax1 and y >= ay0 and y <= ay1)

        # if click is NOT inside menu panel and NOT on its anchor → close
        if not inside_anchor and statusmenuhit(x, y) is None:

            closestatusmenu()

            invalidaterect(0, 0, WINW, WINH)

    # click-away closes context menu
    if CONTEXTMENUOPEN:

        if contextmenuhit(x, y) is None:

            closecontextmenu()

            invalidaterect(0, 0, WINW, WINH)

    if hit is not None:

        closestatusmenu()

        closecontextmenu()

        runaction(hit)

        return

    if ch is not None:

        ACTIONFROMCONTEXT = True

        ACTIONCONTEXTTARGET = CONTEXTMENUTARGET

        closecontextmenu()

        closestatusmenu()

        runaction(ch)

        ACTIONFROMCONTEXT = False

        ACTIONCONTEXTTARGET = None

        return

    if SIDEPROPERTIESDROPDOWN and sidepropertiespointer(msg):
        return

    # status bar click
    action = statusat(x, y)

    if action is not None:

        closecontextmenu()

        if action == "new":

            STATUSMENUKIND = "new"

            STATUSMENUOPEN = not STATUSMENUOPEN

            invalidaterect(0, 0, WINW, WINH)

            return

        if action == "delete":

            STATUSMENUKIND = "delete"

            STATUSMENUOPEN = not STATUSMENUOPEN

            invalidaterect(0, 0, WINW, WINH)

            return

        runaction(action)

        return

    # persistent search field at the right of the location header
    searchhit = searchboxhit(x, y)

    if searchhit == "clear":
        searchclear()
        return

    if searchhit == "scope":
        runaction("searchscope")
        return

    if searchhit == "field":
        searchopen()
        SEARCHCARETPOS = searchcaretfromx(x)
        resetsearchcaret()
        invalidaterect(0, 0, WINW, HEADERH)
        return

    if SEARCHFOCUSED:
        SEARCHFOCUSED = False
        invalidaterect(0, 0, WINW, HEADERH)

    # header click (edit / breadcrumb)
    head = headerat(x, y)

    if head is not None:

        nowh = nowms()

        # click counting (double/triple)
        if (nowh - int(HEADERLASTCLICK["t"])) <= DBLCLICKMS and HEADERLASTCLICK["button"] == button:
            HEADERLASTCLICK["count"] = int(HEADERLASTCLICK["count"]) + 1

        else:

            HEADERLASTCLICK["count"] = 1

        HEADERLASTCLICK["t"] = nowh

        HEADERLASTCLICK["button"] = button

        # if we are already editing, clicks control caret/selection
        if HEADEREDIT:

            # compute same geometry as drawheader
            textx = SIDEBARW + DIVW + PAD

            searchx, _, _, _ = searchboxrect()

            availw = (searchx - PAD) - textx

            if availw < 0:
                availw = 0

            viewstart, shown, prefix = headercomputeview(availw)

            # ellipsis width offset
            off = 0

            if prefix:

                ellw = measuretext("…", FONTSIZEHEADER, FONT)

                if ellw <= 0:

                    ellw = max(8, (FONTSIZEHEADER // 2))

                off = int(ellw)

            caret = headercaretfromx(x, textx + off, viewstart)

            HEADERCARETPOS = clamp(caret, 0, len(HEADEREDITTEXT))

            headerclearselection()

            if int(HEADERLASTCLICK["count"]) == 2:
                headerselectwordat(HEADERCARETPOS)

            if int(HEADERLASTCLICK["count"]) >= 3:
                headerselectall()

            return

        if int(HEADERLASTCLICK["count"]) >= 2:

            headereditbegin()

            return

        if head == "__nav_back__":

            navback()

            return

        if head == "__nav_forward__":

            navforward()

            return

        if head != "__header_edit__":

            setcwd(head)

            return

    topaction = topbarhit(x, y)
    if topaction is not None:
        runaction(topaction)
        return

    if (
        PROPERTIESPANE
        and x >= WINW - PROPERTIESW
        and EXPLORERTOP <= y < WINH - STATUSH
    ):
        sidepropertiespointer(msg)
        return

    if y >= HEADERH and y < EXPLORERTOP and x >= SIDEBARW + DIVW:
        return

    if VIEWMODE == "details" and y >= EXPLORERTOP and y < CONTENTTOP:

        column = columnresizehit(x, y)

        if column is not None:
            COLUMNRESIZING = column
            COLUMNRESIZESTARTX = int(x)
            COLUMNRESIZESTARTW = int(COLUMNWIDTHS.get(column, 100))
            setpointercursor("resize_h")
            return

        for rect in COLUMNMAP:
            x0, y0, x1, y1 = rect

            if x >= x0 and x <= x1 and y >= y0 and y <= y1:
                return

    v = vscrollclick(x, y)

    if v == "thumb":

        VSCROLLDRAGGING = True
        return

    if v == "pageup":

        try:

            SCROLL = int(SCROLL) - int(VISIBLECOUNT)

        except Exception:

            SCROLL = SCROLL

        vscrollclamp()

        invalidaterect(0, 0, WINW, WINH)

        return

    if v == "pagedown":

        try:

            SCROLL = int(SCROLL) + int(VISIBLECOUNT)

        except Exception:

            SCROLL = SCROLL

        vscrollclamp()

        invalidaterect(0, 0, WINW, WINH)

        return

    h = hscrollclick(x, y)

    if h == "thumb":

        HSCROLLDRAGGING = True

        return

    if h == "pageleft":

        try:

            HSCROLL = int(HSCROLL) - int(hscrollvisiblewidth())

        except Exception:

            HSCROLL = HSCROLL

        hscrollclamp()

        invalidaterect(0, 0, WINW, WINH)

        return

    if h == "pageright":

        try:

            HSCROLL = int(HSCROLL) + int(hscrollvisiblewidth())

        except Exception:

            HSCROLL = HSCROLL

        hscrollclamp()

        invalidaterect(0, 0, WINW, WINH)

        return

    # sidebar click
    sidelink = sidebarlinkat(x, y)

    if sidelink is not None:

        SIDEBARSELECTED = sidelink.get("index")

        SIDEBARSELECTEDDRIVE = int(sidelink.get("drive")) if sidelink.get("isdrive") else None

        if isright:
            opencontextmenu(x, y, kind="sidebar", targetpath=sidelink.get("path"))
            invalidaterect(0, 0, WINW, WINH)
            return

        if sidelink.get("path") and sidelink.get("available", True):
            if SIDEBARSELECTED is not None and not PICKERMODE:
                SIDEBARDRAGSTART = (int(x), int(y))
                SIDEBARDRAGINDEX = SIDEBARSELECTED
            setcwd(sidelink.get("path"))
        else:
            setstatus("location is not available", error=True)

        return

    # main tree click
    row = rowat(x, y)

    if row is None:

        if isright:

            clearselection()

            opencontextmenu(x, y, kind="empty", targetpath=CWD)

            invalidaterect(0, 0, WINW, WINH)

            return

        px, py, pw, ph = mainpanerect()

        if x >= px and x <= (px + pw) and y >= py and y <= (py + ph):

            startdragbox(x, y, add=ctrl)

            return

        clearselection()

        return

    item = TREE[row]

    if checkboxat(x, y, row) and not isright:
        toggleselection(item["path"])
        return

    # if click is inside the row but NOT on the name, treat it as empty space
    if not namehit(x, y, row) and not arrowat(x, y, row):

        if isright:

            isdir = False

            try:

                if os.path.isdir(item["path"]):
                    isdir = True

            except Exception:

                isdir = False

            if isdir:

                if item["path"] not in SELECTEDSET:
                    selectpath(item["path"])

                opencontextmenu(x, y, kind="row", targetpath=item["path"])

            else:

                clearselection()

                opencontextmenu(x, y, kind="empty", targetpath=CWD)

            invalidaterect(0, 0, WINW, WINH)

            return

        clearselection()

        startdragbox(x, y, add=ctrl)

        return

    if isright:

        if item["path"] not in SELECTEDSET:

            selectpath(item["path"])

        opencontextmenu(x, y, kind="row", targetpath=item["path"])

        invalidaterect(0, 0, WINW, WINH)

        return

    # arrow click (expand / collapse)
    if arrowat(x, y, row):

        toggleexpand(item["path"])

        return

    # selection
    wasselected = (item["path"] in SELECTEDSET)

    selsince = SELECTEDMS

    if shift:

        rangeselection(item["path"], add=ctrl)

    elif ctrl:

        toggleselection(item["path"])

    else:

        selectpath(item["path"])

    if PICKERMODE == "save_as" and not item.get("isdir"):
        pickernamefromselection(item["path"])

    # double click detection
    if (
        LASTCLICK["path"] == item["path"]
        and (now - LASTCLICK["t"]) <= DBLCLICKMS
        and LASTCLICK["button"] == button
    ):

        LASTCLICK["path"] = None

        LASTCLICK["t"] = 0.0

        LASTCLICK["button"] = 0

        openitem(item["path"])

        return

    # Windows-style rename: defer the selected-item single click until the
    # double-click window has passed. This lets a second click reliably open or
    # run the item instead of the first click immediately entering rename mode.
    if not PICKERMODE and wasselected and not RENAMEEDIT and len(SELECTEDSET) == 1 and not ctrl and not shift:

        try:

            if int(now - int(selsince)) > int(DBLCLICKMS):

                schedulependingrename(item["path"], now)

        except Exception:

            pass

    LASTCLICK["path"] = item["path"]

    LASTCLICK["t"] = now

    LASTCLICK["button"] = button

    if not PICKERMODE:
        ITEMDRAGSTART = (int(x), int(y))
        ITEMDRAGPATHS = selectedpaths()
        ITEMDRAGTARGET = None
        ITEMDRAGMODS = dict(mods)
        ITEMDRAGSTARTED = False


def onscroll(msg):

    global PENDINGSCROLL

    if PROPERTIESOPEN or INPUTOPEN:
        return

    try:

        delta = int(msg.get("delta", 0)) * int(SCROLLSTEP)
        limit = max(1, len(TREE))
        PENDINGSCROLL += delta
        PENDINGSCROLL = clamp(PENDINGSCROLL, -limit, limit)

    except Exception as e:

        log(f"scroll queue error {e}")


def cancelsmoothscroll():

    global PENDINGSCROLL, LASTSCROLLFRAME

    PENDINGSCROLL = 0
    LASTSCROLLFRAME = 0.0


def flushscroll(force=False):

    global SCROLL, PENDINGSCROLL, LASTSCROLLFRAME

    if not PENDINGSCROLL:
        return False

    now = time.monotonic()
    managed = bool(GRAPHICSSTATE.get("active") and GRAPHICSSTATE.get("managed_only"))
    interval = SCROLLMANAGEDINTERVAL if managed else SCROLLCPUINTERVAL

    if not force and LASTSCROLLFRAME and now - LASTSCROLLFRAME < interval:
        return False

    remaining = int(PENDINGSCROLL)
    magnitude = abs(remaining)

    if force:
        amount = magnitude
    else:
        amount = max(1, int(math.ceil(magnitude * SMOOTHSCROLLEASING)))
        amount = min(amount, SMOOTHSCROLLMAXSTEP)

    delta = amount if remaining > 0 else -amount
    PENDINGSCROLL -= delta
    oldscroll = int(SCROLL)
    SCROLL -= delta
    maxscroll = max(0, len(TREE) - VISIBLECOUNT)
    SCROLL = clamp(SCROLL, 0, maxscroll)

    if SCROLL == oldscroll:
        PENDINGSCROLL = 0

    elif (SCROLL == 0 and PENDINGSCROLL > 0) or (SCROLL == maxscroll and PENDINGSCROLL < 0):
        PENDINGSCROLL = 0

    LASTSCROLLFRAME = now

    if SCROLL != oldscroll:
        invalidaterect(0, 0, WINW, WINH)

    return True


def setview(mode):

    global VIEWMODE, CONTENTTOP
    if mode not in ("tier", "details"):
        return False
    VIEWMODE = mode
    CONTENTTOP = EXPLORERTOP + (DETAILHEADERH if VIEWMODE == "details" else 0)
    savesettings()
    buildtree()
    return True


def setsort(column):

    global SORTKEY, SORTDESC
    if column not in ("name", "modified", "type", "size"):
        return False
    if SORTKEY == column:
        SORTDESC = not SORTDESC
    else:
        SORTKEY = column
        SORTDESC = False
    savesettings()
    buildtree()
    return True


def togglepropertiespane():

    global PROPERTIESPANE, SIDEPROPERTIESDROPDOWN, SIDEPROPERTIESDROPDOWNHOVER
    global SIDEPROPERTIESCONTROLS
    PROPERTIESPANE = not PROPERTIESPANE
    if not PROPERTIESPANE:
        SIDEPROPERTIESDROPDOWN = False
        SIDEPROPERTIESDROPDOWNHOVER = None
        SIDEPROPERTIESCONTROLS = {}
    savesettings()
    layout()
    invalidaterect(0, 0, WINW, WINH)


def watchsignature():

    roots = {CWD}
    roots.update(path for path in EXPANDED if os.path.isdir(path))
    signature = {}

    for root in roots:
        try:
            st = os.stat(root)
            children = []
            try:
                with os.scandir(root) as entries:
                    for index, entry in enumerate(entries):
                        if index >= 2048:
                            break
                        if not SHOWHIDDEN and itemishidden(entry.path, entry.name):
                            continue
                        try:
                            childstat = entry.stat(follow_symlinks=False)
                            children.append((entry.name, int(childstat.st_mtime_ns), int(childstat.st_size), int(childstat.st_mode)))
                        except Exception:
                            children.append((entry.name, 0, 0, 0))
            except Exception:
                pass
            signature[root] = (int(st.st_mtime_ns), int(st.st_size), tuple(children))
        except Exception:
            signature[root] = None

    return signature


def watchreset():

    global WATCHSNAPSHOT, WATCHLASTSCAN, WATCHDIRTYAT
    WATCHSNAPSHOT = watchsignature()
    WATCHLASTSCAN = time.time()
    WATCHDIRTYAT = 0.0


def watchpump():

    global WATCHSNAPSHOT, WATCHLASTSCAN, WATCHDIRTYAT

    if SEARCHOPEN and SEARCHTEXT.strip():
        return

    now = time.time()
    if (now - WATCHLASTSCAN) < WATCHINTERVAL:
        return
    WATCHLASTSCAN = now
    current = watchsignature()
    if current != WATCHSNAPSHOT:
        WATCHSNAPSHOT = current
        if WATCHDIRTYAT == 0.0:
            WATCHDIRTYAT = now

    if WATCHDIRTYAT and (now - WATCHDIRTYAT) >= WATCHDEBOUNCE:
        WATCHDIRTYAT = 0.0
        selected = set(SELECTEDSET)
        buildtree()
        selected.intersection_update(item.get("path") for item in TREE)
        if selected:
            setselection(selected, focuspath=SELECTED if SELECTED in selected else next(iter(selected)))


def drivepump():

    if loaddrives(force=False):
        buildsidebarlinks()
        invalidaterect(0, HEADERH, SIDEBARW, WINH - HEADERH - STATUSH)
        if not os.path.isdir(CWD):
            setstatus("the current drive was disconnected", error=True)
            setcwd(DRIVES.get(1, {}).get("root", "/"))


def pickerkey(key, mods, isdown):

    global PICKERNAME, PICKERNAMECARETPOS, PICKERNAMEFOCUSED, PICKERNAMESELECTALL, PICKERNAMESELANCHOR

    if not PICKERMODE:
        return False
    if RENAMEEDIT:
        return False
    if not isdown:
        return True

    ctrl = bool(mods.get("ctrl"))
    shift = bool(mods.get("shift"))
    alt = bool(mods.get("alt"))

    if key == "ESC":
        pickercancel()
        return True

    if key == "TAB":
        if PICKERMODE == "save_as":
            PICKERNAMEFOCUSED = not PICKERNAMEFOCUSED
            invalidaterect(0, WINH - STATUSH, WINW, STATUSH)
        return True

    if PICKERNAMEFOCUSED and PICKERMODE == "save_as":
        if key == "ENTER":
            pickerconfirm()
        elif key in ("BACKSPACE", "DELETE") and deletepickernameselection():
            invalidaterect(0, WINH - STATUSH, WINW, STATUSH)
        elif key == "BACKSPACE" and PICKERNAMECARETPOS > 0:
            PICKERNAME = PICKERNAME[:PICKERNAMECARETPOS - 1] + PICKERNAME[PICKERNAMECARETPOS:]
            PICKERNAMECARETPOS -= 1
            PICKERNAMESELANCHOR = None
            invalidaterect(0, WINH - STATUSH, WINW, STATUSH)
        elif key == "DELETE" and PICKERNAMECARETPOS < len(PICKERNAME):
            PICKERNAME = PICKERNAME[:PICKERNAMECARETPOS] + PICKERNAME[PICKERNAMECARETPOS + 1:]
            PICKERNAMESELANCHOR = None
            invalidaterect(0, WINH - STATUSH, WINW, STATUSH)
        elif key == "LEFT":
            PICKERNAMESELECTALL = False
            if shift:
                if PICKERNAMESELANCHOR is None:
                    PICKERNAMESELANCHOR = PICKERNAMECARETPOS
                PICKERNAMECARETPOS = max(0, PICKERNAMECARETPOS - 1)
            else:
                selection = pickernameselection()
                PICKERNAMECARETPOS = selection[0] if selection else max(0, PICKERNAMECARETPOS - 1)
                PICKERNAMESELANCHOR = None
            invalidaterect(0, WINH - STATUSH, WINW, STATUSH)
        elif key == "RIGHT":
            PICKERNAMESELECTALL = False
            if shift:
                if PICKERNAMESELANCHOR is None:
                    PICKERNAMESELANCHOR = PICKERNAMECARETPOS
                PICKERNAMECARETPOS = min(len(PICKERNAME), PICKERNAMECARETPOS + 1)
            else:
                selection = pickernameselection()
                PICKERNAMECARETPOS = selection[1] if selection else min(len(PICKERNAME), PICKERNAMECARETPOS + 1)
                PICKERNAMESELANCHOR = None
            invalidaterect(0, WINH - STATUSH, WINW, STATUSH)
        elif key == "HOME":
            PICKERNAMESELECTALL = False
            PICKERNAMECARETPOS = 0
            PICKERNAMESELANCHOR = None
            invalidaterect(0, WINH - STATUSH, WINW, STATUSH)
        elif key == "END":
            PICKERNAMESELECTALL = False
            PICKERNAMECARETPOS = len(PICKERNAME)
            PICKERNAMESELANCHOR = None
            invalidaterect(0, WINH - STATUSH, WINW, STATUSH)
        elif ctrl and key == "A":
            PICKERNAMESELECTALL = True
            PICKERNAMESELANCHOR = 0
            PICKERNAMECARETPOS = len(PICKERNAME)
            invalidaterect(0, WINH - STATUSH, WINW, STATUSH)
        elif ctrl and key == "F":
            PICKERNAMEFOCUSED = False
            searchopen()
        return True

    if ctrl and shift and key == "N":
        if PICKERMODE in ("select_tier", "save_location", "save_as"):
            runaction("newtier")
        return True

    if ctrl and not shift and key == "O":
        pickerconfirm()
        return True

    if (
        key in ("DELETE", "F2")
        or (ctrl and key in ("N", "X", "C", "V", "Z", "Y", "ENTER"))
        or (ctrl and shift and key in ("O", "C"))
    ):
        return True

    # Navigation, search, address editing, refresh and row activation continue
    # through Array's existing key handler.
    return False


def onkey(msg):

    global HEADERCARETPOS, HEADERHELD, HEADERHELDDOWNMS, HEADERHELDLASTMS, HEADERHELDKIND, HEADERLASTTEXT, RENAMETEXT, RENAMECARETPOS, RENAMESELANCHOR
    global SEARCHTEXT, SEARCHCARETPOS, SEARCHFOCUSED
    global INPUTTEXT, INPUTCARETPOS
    global PROPERTIESDROPDOWN, PROPERTIESDROPDOWNHOVER

    if CONFIRMOPEN:

        confirmkey(msg)

        return

    key = str(msg.get("key", ""))

    key = key.upper()

    try:

        mods = msg.get("mods", {})

    except Exception:

        mods = {}

    try:

        ctrl = bool(mods.get("ctrl"))

        shift = bool(mods.get("shift"))

    except Exception:

        ctrl = False

        shift = False

    try:

        state = str(msg.get("state", "down")).lower()

    except Exception:

        state = "down"

    try:

        isrepeat = (state == "repeat")

    except Exception:

        isrepeat = False

    try:

        isdown = (state == "down" or state == "repeat")

    except Exception:

        isdown = True

    if isdown:
        cancelpendingrename()

    if PROPERTIESOPEN:
        if not isdown:
            return
        if PROPERTIESDROPDOWN:
            options = propertiesmodeoptions(PROPERTIESISDIR)
            selected = next((index for index, option in enumerate(options) if option[0] == PROPERTIESMODE), 0)
            if key == "ESC":
                PROPERTIESDROPDOWN = False
            elif key in ("UP", "DOWN"):
                current = selected if PROPERTIESDROPDOWNHOVER is None else int(PROPERTIESDROPDOWNHOVER)
                PROPERTIESDROPDOWNHOVER = max(0, min(len(options) - 1, current + (-1 if key == "UP" else 1)))
            elif key == "ENTER":
                index = selected if PROPERTIESDROPDOWNHOVER is None else int(PROPERTIESDROPDOWNHOVER)
                setpropertiesmode(options[index][0])
            invalidaterect(0, 0, WINW, WINH)
            return
        if key in ("ESC", "ENTER"):
            closeproperties()
        return

    if INPUTOPEN:
        if not isdown:
            return
        if key == "ESC":
            closeinput()
        elif key == "ENTER":
            commitinput()
        elif key == "BACKSPACE" and INPUTCARETPOS > 0:
            INPUTTEXT = INPUTTEXT[:INPUTCARETPOS - 1] + INPUTTEXT[INPUTCARETPOS:]
            INPUTCARETPOS -= 1
            invalidaterect(0, 0, WINW, WINH)
        elif key == "DELETE" and INPUTCARETPOS < len(INPUTTEXT):
            INPUTTEXT = INPUTTEXT[:INPUTCARETPOS] + INPUTTEXT[INPUTCARETPOS + 1:]
            invalidaterect(0, 0, WINW, WINH)
        elif key == "LEFT":
            INPUTCARETPOS = max(0, INPUTCARETPOS - 1)
        elif key == "RIGHT":
            INPUTCARETPOS = min(len(INPUTTEXT), INPUTCARETPOS + 1)
        elif key == "HOME":
            INPUTCARETPOS = 0
        elif key == "END":
            INPUTCARETPOS = len(INPUTTEXT)
        return

    if isdown and ctrl and key == "F" and not RENAMEEDIT and not HEADEREDIT:
        searchopen()
        return

    if SEARCHFOCUSED:
        if not isdown:
            return
        if key == "ESC":
            searchclose()
        elif key == "ENTER":
            searchstart()
        elif key == "BACKSPACE" and SEARCHCARETPOS > 0:
            SEARCHTEXT = SEARCHTEXT[:SEARCHCARETPOS - 1] + SEARCHTEXT[SEARCHCARETPOS:]
            SEARCHCARETPOS -= 1
            resetsearchcaret()
            searchtextchanged()
        elif key == "DELETE" and SEARCHCARETPOS < len(SEARCHTEXT):
            SEARCHTEXT = SEARCHTEXT[:SEARCHCARETPOS] + SEARCHTEXT[SEARCHCARETPOS + 1:]
            resetsearchcaret()
            searchtextchanged()
        elif key == "LEFT":
            SEARCHCARETPOS = max(0, SEARCHCARETPOS - 1)
            resetsearchcaret()
            invalidaterect(0, 0, WINW, HEADERH)
        elif key == "RIGHT":
            SEARCHCARETPOS = min(len(SEARCHTEXT), SEARCHCARETPOS + 1)
            resetsearchcaret()
            invalidaterect(0, 0, WINW, HEADERH)
        elif key == "HOME":
            SEARCHCARETPOS = 0
            resetsearchcaret()
            invalidaterect(0, 0, WINW, HEADERH)
        elif key == "END":
            SEARCHCARETPOS = len(SEARCHTEXT)
            resetsearchcaret()
            invalidaterect(0, 0, WINW, HEADERH)
        return

    if isdown and key == "ESC" and SEARCHOPEN:
        searchclose()
        return

    if isdown and key == "ESC" and ACTIVEJOB is not None:
        cancelactivejob()
        return

    if pickerkey(key, mods, isdown):
        return

    if RENAMEEDIT:

        if not isdown:
            return

        # Only caret movement and deletion are repeatable while renaming. This
        # keeps Enter, Escape, and command shortcuts edge-triggered while still
        # allowing a held Backspace/Delete to remove multiple characters.
        if isrepeat and key not in ("HOME", "END", "LEFT", "RIGHT", "BACKSPACE", "DELETE"):
            return

        if key == "ESC":

            renameeditend(cancel=True)

            clearselection()

            return

        if key == "ENTER":

            renameconfirm()
            return

        if ctrl and not shift and key == "Z":

            undorenameedit()

            return

        if ctrl and not shift and key == "Y":

            redorenameedit()

            return

        if ctrl and not shift and key == "A":

            selectallrename()

            invalidateselectionrow(RENAMEPATH)

            return

        if ctrl and not shift and key == "C":

            copyrenametext(cut=False)

            return

        if ctrl and not shift and key == "X":

            copyrenametext(cut=True)

            invalidateselectionrow(RENAMEPATH)

            return

        if ctrl and not shift and key == "V":

            pasterenametext()

            invalidateselectionrow(RENAMEPATH)

            return

        if key == "HOME":

            moverenamecaretto(0, shift=shift)

            invalidateselectionrow(RENAMEPATH)

            return

        if key == "END":

            moverenamecaretto(len(RENAMETEXT), shift=shift)

            invalidateselectionrow(RENAMEPATH)

            return

        if key == "LEFT":

            try:

                if ctrl:
                    moverenamecaretto(renamewordleft(RENAMECARETPOS), shift=shift)
                else:
                    moverenamecaret(-1, shift=shift)

            except Exception:

                pass

            invalidateselectionrow(RENAMEPATH)

            return

        if key == "RIGHT":

            try:

                if ctrl:
                    moverenamecaretto(renamewordright(RENAMECARETPOS), shift=shift)
                else:
                    moverenamecaret(1, shift=shift)

            except Exception:

                pass

            invalidateselectionrow(RENAMEPATH)

            return

        if key == "BACKSPACE":

            try:

                if ctrl:

                    deleterenameword(left=True)

                elif renameselectionrange() is not None:

                    pushrenameundo()

                    deleterenameselection()

                    pass

                elif RENAMECARETPOS > 0:

                    pushrenameundo()

                    left = RENAMETEXT[:RENAMECARETPOS - 1]
                    right = RENAMETEXT[RENAMECARETPOS:]

                    RENAMETEXT = f"{left}{right}"

                    RENAMECARETPOS = RENAMECARETPOS - 1

                    RENAMESELANCHOR = None

            except Exception:

                pass

            invalidateselectionrow(RENAMEPATH)

            return

        if key == "DELETE":

            try:

                if ctrl:

                    deleterenameword(left=False)

                elif renameselectionrange() is not None:

                    pushrenameundo()

                    deleterenameselection()

                    pass

                elif RENAMECARETPOS < len(RENAMETEXT):

                    pushrenameundo()

                    left = RENAMETEXT[:RENAMECARETPOS]
                    right = RENAMETEXT[RENAMECARETPOS + 1:]

                    RENAMETEXT = f"{left}{right}"

                    RENAMESELANCHOR = None

            except Exception:

                pass

            invalidateselectionrow(RENAMEPATH)

            return

    if HEADEREDIT:

        if not isdown:

            # stop repeating for navigation/edit keys
            if HEADERHELD == key:

                HEADERHELD = None

                HEADERHELDKIND = None

                return


            if HEADERHELD == "__TEXT__":

                if key == "SPACE" or (isinstance(key, str) and len(key) == 1):

                    HEADERHELD = None

                    HEADERHELDKIND = None

                    return

            return

        # Native keyboard repeat may arrive in addition to the header's timed
        # fallback. Accept it only for navigation/deletion; printable text is
        # repeated by headerrepeat() using the last TEXT event.
        if isrepeat and key not in ("HOME", "END", "LEFT", "RIGHT", "BACKSPACE", "DELETE"):
            return

        if key == "ENTER":

            headereditend(cancel=False)

            return

        if key == "ESC":

            headereditend(cancel=True)

            renameeditend(cancel=True)

            return

        if key == "BACKSPACE":

            headerbackspace()

            HEADERHELD = "BACKSPACE"

            HEADERHELDDOWNMS = nowms()

            HEADERHELDLASTMS = HEADERHELDDOWNMS

            return

        if key == "DELETE":

            headerdelete()

            HEADERHELD = "DELETE"

            HEADERHELDDOWNMS = nowms()

            HEADERHELDLASTMS = HEADERHELDDOWNMS

            return

        if key == "LEFT":

            headerclearselection()

            HEADERCARETPOS = clamp(HEADERCARETPOS - 1, 0, len(HEADEREDITTEXT))

            HEADERHELD = "LEFT"

            HEADERHELDDOWNMS = nowms()

            HEADERHELDLASTMS = HEADERHELDDOWNMS

            return

        if key == "RIGHT":

            headerclearselection()

            HEADERCARETPOS = clamp(HEADERCARETPOS + 1, 0, len(HEADEREDITTEXT))

            HEADERHELD = "RIGHT"

            HEADERHELDDOWNMS = nowms()

            HEADERHELDLASTMS = HEADERHELDDOWNMS

            return

        if key == "HOME":

            headerclearselection()

            HEADERCARETPOS = 0

            HEADERHELD = "HOME"

            HEADERHELDDOWNMS = nowms()

            HEADERHELDLASTMS = HEADERHELDDOWNMS

            return

        if key == "END":

            headerclearselection()

            HEADERCARETPOS = len(HEADEREDITTEXT)

            HEADERHELD = "END"

            HEADERHELDDOWNMS = nowms()

            HEADERHELDLASTMS = HEADERHELDDOWNMS

            return

        if isdown:

            if key == "SPACE":

                # arm text repeat only on the initial press
                if not isrepeat and (HEADERHELDKIND != "TEXT" or HEADERHELD != "__TEXT__"):

                    HEADERHELD = "__TEXT__"
                    HEADERHELDKIND = "TEXT"

                    HEADERHELDDOWNMS = nowms()
                    HEADERHELDLASTMS = HEADERHELDDOWNMS

                return

            if isinstance(key, str) and len(key) == 1:

                # arm text repeat only on the initial press
                if not isrepeat and (HEADERHELDKIND != "TEXT" or HEADERHELD != "__TEXT__"):

                    HEADERHELD = "__TEXT__"
                    HEADERHELDKIND = "TEXT"

                    HEADERHELDDOWNMS = nowms()
                    HEADERHELDLASTMS = HEADERHELDDOWNMS

                return

        return

    if not isdown:
        return

    # Repeats outside a text editor must not retrigger file operations or global
    # shortcuts. Text-edit repeats have already been consumed above.
    if isrepeat and key not in ("UP", "DOWN"):
        return

    if ctrl and not shift and key == "Z":

        undoaction()

        return

    if ctrl and not shift and key == "Y":

        redoaction()

        return

    if ctrl and not shift and key == "N":
        openarraywindow(CWD)

        return

    if ctrl and shift and key == "N":
        runaction("newtier")

        return

    if key == "DELETE" and shift:
        runaction("destroy")

        return

    if key == "DELETE":
        runaction("delete")

        return

    if ctrl and shift and key == "C":
        runaction("copypath")
        return

    if ctrl and not shift and key == "C":
        runaction("copy")

        return

    if ctrl and not shift and key == "X":
        runaction("cut")

        return

    if ctrl and not shift and key == "V":
        runaction("paste")

        return

    if ctrl and not shift and key == "A":
        selectalltree()

        return

    if key == "F2":
        runaction("rename")

        return

    if ctrl and not shift and key == "R":
        buildtree()
        watchreset()

        return

    if ctrl and not shift and key == "O":
        runaction("open")

        return

    if ctrl and not shift and key in ("L", "D"):
        headereditbegin()
        headerselectall()
        return

    if key == "F4":
        headereditbegin()
        headerselectall()
        return

    if key == "F5":
        buildtree()
        watchreset()
        return

    if bool(mods.get("alt")) and key == "LEFT":
        navback()
        return

    if bool(mods.get("alt")) and key == "RIGHT":
        navforward()
        return

    if bool(mods.get("alt")) and key == "UP":
        drive = driveforpath(CWD)
        if driverelpath(CWD, drive) != "/":
            setcwd(os.path.dirname(CWD))
        return

    if bool(mods.get("alt")) and key == "ENTER":
        runaction("properties")
        return

    if ctrl and shift and key == "O":
        runaction("opennew")

        return

    if ctrl and not shift and key == "ENTER":
        runaction("run")

        return

    if key == "UP":
        extend = shift and (not PICKERMODE or PICKERALLOWMULTIPLE)
        movetreeselection(-1, extend=extend)
        return

    if key == "DOWN":
        extend = shift and (not PICKERMODE or PICKERALLOWMULTIPLE)
        movetreeselection(1, extend=extend)
        return

    if key == "HOME" and TREE:
        selectpath(TREE[0]["path"])
        scrolltopath(TREE[0]["path"])
        return

    if key == "END" and TREE:
        selectpath(TREE[-1]["path"])
        scrolltopath(TREE[-1]["path"])
        return

    if key in ("PAGEUP", "PAGEDOWN") and TREE:
        current = next((index for index, item in enumerate(TREE) if item.get("path") == SELECTED), 0)
        step = max(1, VISIBLECOUNT - 1)
        targetindex = max(0, current - step) if key == "PAGEUP" else min(len(TREE) - 1, current + step)
        selectpath(TREE[targetindex]["path"])
        scrolltopath(TREE[targetindex]["path"])
        return

    if key == "RIGHT" and SELECTED:
        item = next((entry for entry in TREE if entry.get("path") == SELECTED), None)
        if item and item.get("isdir"):
            if item.get("haskids") and not item.get("expanded"):
                toggleexpand(SELECTED)
            else:
                openitem(SELECTED)
        return

    if key == "LEFT" and SELECTED:
        item = next((entry for entry in TREE if entry.get("path") == SELECTED), None)
        if item and item.get("expanded"):
            toggleexpand(SELECTED)
        elif item and item.get("depth", 0) > 0:
            selectpath(os.path.dirname(SELECTED))
        return

    if key == "ENTER":

        for item in TREE:

            if item["path"] == SELECTED:

                openitem(item["path"])

                return

    if key == "BACKSPACE":

        if navcanback():
            navback()

        return


def onfocus(msg):

    cancelpendingrename()

    # redraw on focus change
    invalidaterect(0, 0, WINW, WINH)


def ontext(msg):

    global HEADERLASTTEXT, HEADERHELD, HEADERHELDLASTMS, HEADERHELDDOWNMS, HEADERHELDKIND, RENAMETEXT, RENAMECARETPOS, RENAMESELANCHOR
    global SEARCHTEXT, SEARCHCARETPOS
    global INPUTTEXT, INPUTCARETPOS
    global TYPESELECTTEXT, TYPESELECTUNTIL
    global PICKERNAME, PICKERNAMECARETPOS, PICKERNAMESELECTALL, PICKERNAMESELANCHOR

    if INPUTOPEN:
        value = str(msg.get("text", ""))
        if value and all(ord(char) >= 32 for char in value):
            INPUTTEXT = INPUTTEXT[:INPUTCARETPOS] + value + INPUTTEXT[INPUTCARETPOS:]
            INPUTCARETPOS += len(value)
            invalidaterect(0, 0, WINW, WINH)
        return

    if SEARCHFOCUSED:
        value = str(msg.get("text", ""))
        if value and all(ord(char) >= 32 for char in value):
            SEARCHTEXT = SEARCHTEXT[:SEARCHCARETPOS] + value + SEARCHTEXT[SEARCHCARETPOS:]
            SEARCHCARETPOS += len(value)
            resetsearchcaret()
            searchtextchanged()
        return

    if PICKERMODE == "save_as" and PICKERNAMEFOCUSED and not RENAMEEDIT:
        value = str(msg.get("text", ""))
        value = "".join(char for char in value if ord(char) >= 32 and char not in ("/", "\\", "\x00"))
        if value:
            deletepickernameselection()
            room = max(0, 255 - len(PICKERNAME))
            value = value[:room]
            PICKERNAME = PICKERNAME[:PICKERNAMECARETPOS] + value + PICKERNAME[PICKERNAMECARETPOS:]
            PICKERNAMECARETPOS += len(value)
            PICKERNAMESELANCHOR = None
            invalidaterect(0, WINH - STATUSH, WINW, STATUSH)
        return

    if RENAMEEDIT:

        try:

            t = str(msg.get("text", ""))

        except Exception:

            t = ""

        if t == "":
            return

        replacerenameselection(t)

        # redraw main pane rows
        invalidaterect(SIDEBARW + DIVW, HEADERH, WINW - (SIDEBARW + DIVW), WINH - HEADERH - STATUSH)

        return

    if not HEADEREDIT:
        value = str(msg.get("text", ""))
        if value and all(ord(char) >= 32 for char in value):
            now = nowms()
            if now > TYPESELECTUNTIL:
                TYPESELECTTEXT = ""
            TYPESELECTTEXT += value.casefold()
            TYPESELECTUNTIL = now + 1100
            for item in TREE:
                if str(item.get("displayname", item.get("name", ""))).casefold().startswith(TYPESELECTTEXT):
                    selectpath(item.get("path"))
                    scrolltopath(item.get("path"))
                    break
        return

    s = str(msg.get("text", ""))

    if len(s) != 1:
        return

    if ord(s) < 32:
        return

    if isinstance(s, str) and len(s) == 1:

        # update last text for repeat to use (preserves real typed char)
        HEADERLASTTEXT = s

        # do not reset repeat timers here; KEY down arms repeat

    headerinserttext(s)


# action functions
def buildactions():

    global ACTIONS, ACTIONVIS

    ACTIONS = []

    ACTIONVIS = {}

    # default: everything hidden
    for slot in ACTIONSLOTS:
        ACTIONVIS[slot["id"]] = False

    if PICKERMODE:
        ACTIONVIS["new"] = PICKERMODE in ("select_tier", "save_location", "save_as")
        ACTIONVIS["reveal"] = True
        if len(SELECTEDSET) == 1:
            try:
                pickerpath, linkerror = resolvearraylink(SELECTED)
                ACTIONVIS["open"] = bool(
                    linkerror is None
                    and (
                        os.path.isdir(pickerpath)
                        or (PICKERMODE == "open_file" and os.path.isfile(pickerpath) and pickerpathmatches(pickerpath))
                    )
                )
            except Exception:
                ACTIONVIS["open"] = False
        return

    refreshclipboard()

    # always visible
    ACTIONVIS["new"] = True

    ACTIONVIS["reveal"] = True

    ACTIONVIS["undo"] = undoavailable()

    ACTIONVIS["redo"] = redoavailable()

    # paste when clipboard has something (independent of selection)
    if CLIPBOARDHAS:
        ACTIONVIS["paste"] = True

    # show empty only inside /.rubbish (and subdirs)
    if isrubbish(CWD) and rubbishhas():
        ACTIONVIS["empty"] = True

    # nothing selected: stop here
    if not SELECTEDSET:
        return

    # if something selected (file OR folder)
    ACTIONVIS["copy"] = True

    ACTIONVIS["cut"] = True

    if not isrubbish(SELECTED):
        ACTIONVIS["delete"] = True

    ACTIONVIS["rename"] = (len(SELECTEDSET) == 1)

    if isrubbish(SELECTED) and os.path.abspath(str(SELECTED)) != os.path.abspath("/.rubbish"):
        ACTIONVIS["restore"] = True

    try:

        # determine selected item type
        isdir = False

        if len(SELECTEDSET) != 1:
            return

        for item in TREE:

            if item["path"] == SELECTED:

                isdir = item["isdir"]

                break

    except Exception:

        isdir = False

    # Links are ordinary files, but remain openable like Windows shortcuts.
    islink = isarraylink(SELECTED) if len(SELECTEDSET) == 1 else False

    # open when a single item is selected and it is a folder or link
    if isdir or islink:

        ACTIONVIS["open"] = True

    # run only when a file is selected AND it is executable OR a .py file
    if not isdir:

        if len(SELECTEDSET) != 1:
            return

        ispy = False

        isexec = False

        try:

            ispy = SELECTED.lower().endswith(".py")

        except Exception:

            ispy = False

        try:

            st = os.stat(SELECTED)

            isexec = bool(st.st_mode & 0o111)

        except FileNotFoundError:

            isexec = False

        except PermissionError:

            isexec = False

        except Exception:

            isexec = False

        isopenable = False

        if ispy or isexec:
            isopenable = True

        elif istextfile(SELECTED) or isaudiofile(SELECTED):
            isopenable = True

        if isopenable:
            ACTIONVIS["open"] = True

        if ispy or isexec:
            ACTIONVIS["run"] = True


def openarraywindow(folder):

    if not os.path.isdir(folder):
        return False
    try:
        base = os.path.basename(ARRAYPATH)
        opsrun(
            ARRAYPATH, [folder], os.path.splitext(base)[0],
            None, "session", "behind", await_window=True,
        )
        return True
    except Exception:
        setstatus("could not open a new Array window", error=True)
        return False


def runaction(actionid):

    global SELECTED
    global SHOWEXTENSIONS, SHOWITEMCHECKS, FOLDERSFIRST
    global SEARCHSCOPE
    global PICKERNAMEFOCUSED, PICKERNAMESELECTALL

    if PICKERMODE and actionid not in {
        "viewtier", "viewdetails", "propertiespane",
        "sortname", "sortmodified", "sorttype", "sortsize",
        "extensions", "itemchecks", "foldersfirst",
        "search", "searchscope", "filelocation",
        "open", "newtier", "reveal",
    }:
        return

    target = ACTIONCONTEXTTARGET if ACTIONFROMCONTEXT and ACTIONCONTEXTTARGET is not None else SELECTED

    if actionid == "sidebarpin":
        if target:
            if not sidebarpin(target):
                setstatus("location is already in the sidebar")
            invalidaterect(0, 0, WINW, WINH)
        return

    if actionid == "sidebarunpin":
        if SIDEBARSELECTED is not None:
            sidebarunpin(SIDEBARSELECTED)
            invalidaterect(0, 0, WINW, WINH)
        return

    if actionid == "sidebarrename":
        if SIDEBARSELECTED is not None and SIDEBARSELECTED < len(SIDBARENTRIES):
            opentextdialog(
                "rename sidebar item",
                "enter a new name for this sidebar item",
                SIDBARENTRIES[SIDEBARSELECTED].get("label", ""),
                "sidebarrename",
                SIDEBARSELECTED,
                maxlength=64,
            )
        return

    if actionid == "driverename":
        if SIDEBARSELECTEDDRIVE in DRIVES:
            opentextdialog(
                "rename drive",
                f"enter a new name for drive {SIDEBARSELECTEDDRIVE}",
                DRIVES[SIDEBARSELECTEDDRIVE].get("label", ""),
                "driverename",
                SIDEBARSELECTEDDRIVE,
                maxlength=64,
            )
        return

    if actionid == "viewtier":
        setview("tier")
        return

    if actionid == "viewdetails":
        setview("details")
        return

    if actionid == "propertiespane":
        togglepropertiespane()
        return

    if actionid.startswith("sort") and actionid in ("sortname", "sortmodified", "sorttype", "sortsize"):
        setsort(actionid[4:])
        return

    if actionid == "extensions":
        SHOWEXTENSIONS = not SHOWEXTENSIONS
        savesettings()
        buildtree()
        return

    if actionid == "itemchecks":
        SHOWITEMCHECKS = not SHOWITEMCHECKS
        savesettings()
        invalidaterect(0, 0, WINW, WINH)
        return

    if actionid == "foldersfirst":
        FOLDERSFIRST = not FOLDERSFIRST
        savesettings()
        buildtree()
        return

    if actionid == "search":
        searchopen()
        return

    if actionid == "searchscope":
        scopes = ("tier", "drive", "terminal")
        SEARCHSCOPE = scopes[(scopes.index(SEARCHSCOPE) + 1) % len(scopes)] if SEARCHSCOPE in scopes else "tier"
        savesettings()
        if SEARCHOPEN and SEARCHTEXT.strip():
            searchstart()
        else:
            setstatus(f"search scope: {SEARCHSCOPE}")
            invalidaterect(0, 0, WINW, HEADERH)
        return

    if actionid == "properties":
        openproperties(selectedpaths() or ([target] if target else []))
        return

    if actionid == "filelocation":
        if target:
            searchclose()
            revealitem(target)
        return

    if actionid == "openwith":
        if target:
            extension = os.path.splitext(target)[1].lower()
            initial = str((SETTINGS.get("associations") or {}).get(extension, ""))
            opentextdialog("open with", "enter the application path", initial, "openwith", target, maxlength=4096)
        return

    if actionid == "createlink":
        if target:
            opentextdialog(
                "link name",
                "enter a name for the link",
                os.path.basename(target.rstrip("/")) + " link",
                "createlink",
                target,
                maxlength=255,
            )
        return

    if actionid == "compress":
        paths = selectedpaths() or ([target] if target else [])
        if paths:
            enqueuejob("zip", paths, os.path.dirname(paths[0]) if len(paths) == 1 else CWD)
        return

    if actionid == "extract":
        if target and str(target).lower().endswith(".zip"):
            enqueuejob("extract", [target], os.path.dirname(target))
        return

    if actionid == "copypath":
        paths = selectedpaths() or ([target] if target else [])
        if paths:
            exset("\n".join(formatlocation(path) for path in paths), source="array")
            setstatus("path copied")
        return

    if actionid == "undo":

        undoaction()

        return

    if actionid == "redo":

        redoaction()

        return

    if actionid == "open":

        target = None

        if ACTIONFROMCONTEXT and ACTIONCONTEXTTARGET is not None:
            target = ACTIONCONTEXTTARGET

        else:
            target = SELECTED

        if target is None:
            return

        try:

            path = normalisepath(target)

        except Exception:

            return

        try:

            if os.path.isdir(path):

                setcwd(path)

                return

        except Exception:

            pass

        openitem(target)

        return

    if actionid == "opennew":

        target = None

        if ACTIONFROMCONTEXT and ACTIONCONTEXTTARGET is not None:
            target = ACTIONCONTEXTTARGET

        else:
            target = SELECTED

        if target is None:
            return

        try:

            folder = normalisepath(target)

        except Exception:

            return

        try:

            if not os.path.isdir(folder):
                return

        except Exception:

            return

        try:

            prog = ARRAYPATH

            base = os.path.basename(str(prog))

            name = os.path.splitext(base)[0]

        except Exception:

            prog = ARRAYPATH

            name = "array"

        # Launch identity is fixed session metadata. Authorization is enforced
        # by Operations and must never be inferred from mutable role state.
        user = "session"

        try:

            opsrun(prog, [folder], name, None, user, "behind", await_window=True)

        except Exception:

            return

        return

    if actionid == "newfile":

        try:

            target = CWD

            for item in TREE:

                if item["path"] == SELECTED and item["isdir"]:

                    target = SELECTED

                    break

        except Exception:

            target = CWD

        newfile(target)

        return

    if actionid == "newtier":

        if PICKERMODE:
            PICKERNAMEFOCUSED = False
            PICKERNAMESELECTALL = False

        try:

            target = CWD

            for item in TREE:

                if item["path"] == SELECTED and item["isdir"]:

                    target = SELECTED

                    break

        except Exception:

            target = CWD

        newtier(target)

        return

    if actionid == "paste":

        target = CWD

        if ACTIONFROMCONTEXT and ACTIONCONTEXTTARGET is not None:

            try:

                if os.path.isdir(ACTIONCONTEXTTARGET):
                    target = ACTIONCONTEXTTARGET

            except Exception:

                target = CWD

        pasteinto(target)

        return

    if actionid == "copy":

        copyitems(selectedpaths())

        return

    if actionid == "cut":

        cutitems(selectedpaths())

        return

    if actionid == "delete":

        openconfirm("delete", selectedpaths())

        return

    if actionid == "destroy":

        openconfirm("destroy", selectedpaths())

        return

    if actionid == "rename":

        if SELECTED is None:
            return

        renameeditstart(SELECTED)

        return

    if actionid == "run":

        runitem(SELECTED)

        return

    if actionid == "reveal":

        togglehidden()

        return

    if actionid == "empty":

        if isrubbish(CWD):

            if not emptyrubbish():
                return

            buildtree()

            if SELECTED is not None:
                SELECTED = None

        return

    if actionid == "restore":

        restoreitem(SELECTED)

        return


def newfile(targetdir):

    # normalise target directory
    target = os.path.abspath(str(targetdir))

    if not os.path.isdir(target):
        return

    # auto expand the selected tier so the created item becomes visible
    try:

        parent = normalisepath(targetdir)

    except Exception:

        parent = None

    # determine base name (windows explorer style: newfile, newfile1, newfile2...)
    name = "newfile"

    created = None

    i = 0

    while True:

        try:

            if i == 0:

                fname = name

            else:

                fname = f"{name}{i}"

        except Exception:

            fname = name

        try:

            path = os.path.join(target, fname)

        except Exception:

            return

        if not permissionpaths(path):
            return

        try:

            # create without overwrite (brick create directive style)
            with open(path, "x"):
                pass

            flushfilesystem(path)

            created = path
            break

        except FileExistsError:

            i += 1

            continue

        except FileNotFoundError:

            return

        except PermissionError:

            permissiondenied()
            return

        except Exception:

            return

    # refresh view
    if parent:

        EXPANDED.add(parent)

    buildtree()

    # windows explorer behaviour: select it and ensure it is visible
    scrolltopath(created)

    selectpath(created)

    pushundo({
        "type": "create",
        "items": [{
            "path": normalisepath(created),
            "isdir": False,
        }],
    })

    renameeditstart(created, blank=True)


def newtier(targetdir):

    # normalise target directory
    target = os.path.abspath(str(targetdir))

    if not os.path.isdir(target):
        return

    # auto expand the selected tier so the created tier becomes visible
    try:

        parent = normalisepath(targetdir)

    except Exception:

        parent = None

    # base tier name (placeholder, user will rename)
    name = "newtier"

    created = None

    i = 0

    while True:

        if i == 0:

            tname = name

        else:

            tname = f"{name}{i}"

        path = os.path.join(target, tname)

        if not permissionpaths(path):
            return

        try:

            os.mkdir(path)

            flushfilesystem(path)

            created = path

            break

        except FileExistsError:

            i += 1
            continue

        except PermissionError:

            permissiondenied()
            return

        except Exception:

            return

    # refresh view
    if parent:

        EXPANDED.add(parent)

    buildtree()

    scrolltopath(created)

    selectpath(created)

    pushundo({
        "type": "create",
        "items": [{
            "path": normalisepath(created),
            "isdir": True,
        }],
    })

    renameeditstart(created, blank=True)


def copyitem(path):

    if path is None:
        return

    selectpath(path)

    scrolltopath(path)

    payload = {
        "mode": "copy",
        "paths": [normalisepath(path)],
        "source": "array",
        "ts": nowms()
    }

    exsetfiles(payload, source="array")

    refreshclipboard()

    buildactions()

    invalidaterect(0, WINH - STATUSH, WINW, STATUSH)


def cutitem(path):

    if path is None:
        return

    selectpath(path)

    scrolltopath(path)

    payload = {
        "mode": "cut",
        "paths": [normalisepath(path)],
        "source": "array",
        "ts": nowms()
    }

    exsetfiles(payload, source="array")

    refreshclipboard()

    buildactions()

    invalidaterect(0, WINH - STATUSH, WINW, STATUSH)


def pasteinto(targetdir):

    global CUTSET

    ok, st = exget()

    if not ok:
        return

    if str(st.get("type", "empty")) != "files":
        return

    try:

        payload = json.loads(str(st.get("data", "")))

    except Exception:

        return

    try:

        mode = str(payload.get("mode", "copy")).lower()

    except Exception:

        mode = "copy"

    try:

        paths = payload.get("paths", [])

    except Exception:

        paths = []

    if not isinstance(paths, list) or not paths:
        return

    dest = os.path.abspath(str(targetdir))

    if not os.path.isdir(dest):
        dest = os.path.dirname(dest)

    sources = [_physicalnormalize(path) for path in paths if os.path.exists(_physicalnormalize(path))]
    if not sources:
        return
    enqueuejob("move" if mode == "cut" else "copy", sources, dest, clipboard=(mode == "cut"), conflict=JOBCONFLICTDEFAULT)


def deleteitem(path, record=True):

    global SELECTED

    if path is None:
        return None

    target = os.path.abspath(str(path))

    rubbishroot = os.path.abspath("/.rubbish")

    if os.path.commonpath([target, rubbishroot]) == rubbishroot:
        return None

    if not permissionpaths(target):
        return None

    before = rubbishids()

    try:

        storepaths([target])

    except PermissionError:

        permissiondenied()
        return None

    flushfilesystem(target, "/.rubbish", "/.rubbish/index.txt")

    items = newrubbishitems(before, [target])

    if record and items:

        pushundo({
            "type": "delete",
            "items": items,
        })

    buildtree()

    # clear selection if deleted item no longer exists
    if SELECTED == path:

        exists = False

        for item in TREE:

            if item["path"] == path:

                exists = True

                break

        if not exists:
            SELECTED = None

    return items[0] if items else None


def destroyitem(path):

    global SELECTED

    if path is None:
        return

    target = os.path.abspath(str(path))

    # never destroy the rubbish root itself
    if target == os.path.abspath("/.rubbish"):
        return

    if not permissionpaths(target):
        return

    rubbishroot = os.path.abspath("/.rubbish")

    # if the selected thing is inside /.rubbish, destroy the whole rubbish item + update index
    if os.path.commonpath([target, rubbishroot]) == rubbishroot:

        rid = None

        try:

            parts = target.strip(os.sep).split(os.sep)

            if len(parts) >= 2 and parts[0] == ".rubbish":

                rid = parts[1]

        except Exception:

            rid = None

        if rid:

            payload = os.path.join("/.rubbish", rid)

            try:

                shutil.rmtree(payload)

            except PermissionError:

                permissiondenied()
                return

            flushfilesystem(payload, "/.rubbish")

            indexfile = "/.rubbish/index.txt"

            try:

                with open(indexfile, "r") as f:

                    lines = f.read().splitlines()

            except FileNotFoundError:

                lines = []

            except Exception:

                lines = []

            if lines:

                header = lines[0]

                newlines = [header] + [l for l in lines[1:] if not l.startswith(rid + "\t")]

                try:

                    with open(indexfile, "w") as f:

                        f.write("\n".join(newlines) + "\n")

                except PermissionError:

                    permissiondenied()
                    return

                flushfilesystem(indexfile, "/.rubbish")

        buildtree()

        # clear selection if it vanished
        if SELECTED is not None:

            stillthere = False

            for item in TREE:

                if item["path"] == SELECTED:

                    stillthere = True

                    break

            if not stillthere:

                SELECTED = None

        return

    if os.path.isdir(target):

        try:

            shutil.rmtree(target)

        except PermissionError:

            permissiondenied()
            return

    else:

        try:

            os.remove(target)

        except PermissionError:

            permissiondenied()
            return

    flushfilesystem(target)

    buildtree()

    # clear selection if it vanished
    if SELECTED is not None:

        stillthere = False

        for item in TREE:

            if item["path"] == SELECTED:

                stillthere = True

                break

        if not stillthere:

            SELECTED = None


def copyitems(paths):

    global CUTSET

    if not paths:
        return

    selectpath(paths[0])

    scrolltopath(paths[0])

    CUTSET = set()

    payload = {
        "mode": "copy",
        "paths": [normalisepath(p) for p in paths],
        "source": "array",
        "ts": nowms()
    }

    exsetfiles(payload, source="array")

    refreshclipboard()

    buildactions()

    invalidaterect(0, WINH - STATUSH, WINW, STATUSH)


def cutitems(paths):

    global CUTSET

    if not paths:
        return

    selectpath(paths[0])

    scrolltopath(paths[0])

    CUTSET = set([normalisepath(p) for p in paths])

    payload = {
        "mode": "cut",
        "paths": [normalisepath(p) for p in paths],
        "source": "array",
        "ts": nowms()
    }

    exsetfiles(payload, source="array")

    refreshclipboard()

    buildactions()

    invalidaterect(0, WINH - STATUSH, WINW, STATUSH)

    invalidaterect(SIDEBARW + DIVW, HEADERH, WINW - (SIDEBARW + DIVW), WINH - HEADERH - STATUSH)


def deleteitems(paths):

    if not paths:
        return

    if not permissionpaths(paths):
        return

    enqueuejob("delete", paths)
    clearselection()


def destroyitems(paths):

    if not paths:
        return

    if not permissionpaths(paths):
        return
    enqueuejob("destroy", paths)
    clearselection()


def restorepaths(paths):

    destinations = []

    records = {}

    for record in rubbishrecords():

        try:

            records[str(record.get("id"))] = record.get("origpath")

        except Exception:

            continue

    for path in paths or []:

        try:

            target = os.path.abspath(str(path))

            parts = target.strip(os.sep).split(os.sep)

            if len(parts) < 2 or parts[0] != ".rubbish":
                continue

            destination = records.get(str(parts[1]))

            if destination is not None:
                destinations.append(destination)

        except Exception:

            continue

    return destinations


def restoreitems(paths):

    if not paths:
        return

    if not permissionpaths(paths):
        return

    destinations = restorepaths(paths)

    destinationchecks = []

    for destination in destinations:
        destinationchecks.extend(creationmutationpaths(destination))

    if not destinations or not permissionpaths(destinationchecks):
        return

    undoitems = []

    for p in paths:

        try:

            item = restoreitem(p, record=False)

            if item:

                undoitems.append(item)

        except Exception:

            pass

    if undoitems:

        pushundo({
            "type": "restore",
            "items": undoitems,
        })

    buildtree()

    clearselection()


def renameitem(path):

    # placeholder rename scheme
    newname = path + "_renamed"

    sendws({
        "cmd": "rename",
        "path": path,
        "new": newname
    })

    buildtree()


def runitem(path):

    try:

        # User Python is data, not a catalogue executable.  Open the measured
        # Brick shell and let its existing confined console run the file.
        target = normalisepath(path)
        ispython = str(target).lower().endswith('.py')
        prog = BRICKPROG if ispython else target
        arguments = ['--run-file', target] if ispython else []

    except Exception:

        return

    try:

        # derive operation name
        base = os.path.basename(str(target))
        name = os.path.splitext(base)[0]

    except Exception:

        name = "unknown"

    # Launch identity is fixed session metadata. Authorization is enforced by
    # Operations and must never be inferred from mutable role state.
    user = "session"

    try:

        # run via operations server (foreground)
        pid = opsrun(prog, arguments, name, None, user, "front", await_window=True)

        if pid is None:
            return

    except Exception:

        return


def revealitem(path):

    # reveal item by opening parent and selecting
    parent = path.rsplit("/", 1)[0]

    setcwd(parent)

    selectpath(path)


def istextfile(path):

    try:

        p = str(path).lower()

    except Exception:

        return False

    exts = [
        ".txt", ".md", ".log", ".csv",
        ".json", ".toml", ".ini", ".cfg", ".conf",
        ".yaml", ".yml", ".xml",
        ".html", ".css",
        ".js", ".jsx", ".ts", ".tsx"
    ]

    for e in exts:

        if p.endswith(e):
            return True

    return False


def isaudiofile(path):

    try:

        extension = os.path.splitext(str(path).lower())[1]

    except Exception:

        return False

    return extension in AUDIOEXTENSIONS


def isvideofile(path):

    try:

        extension = os.path.splitext(str(path).lower())[1]

    except Exception:

        return False

    return extension in VIDEOEXTENSIONS


def openwithviewer(path):

    if viewersupports is None:
        return

    try:

        target = normalisepath(path)

    except Exception:

        return

    try:

        user = getusername()

    except Exception:

        return

    try:

        opsrun(VIEWERPROG, [target], "viewer", None, user, "front", await_window=True)

    except Exception:

        return


def openwithwrite(path):

    try:

        target = normalisepath(path)

    except Exception:

        return

    try:

        user = getusername()

    except Exception:

        return

    try:

        opsrun(WRITEPROG, [target], "write", None, user, "front", await_window=True)

    except Exception:

        return


def openwithplayer(path):

    try:

        target = normalisepath(path)

    except Exception:

        return

    try:

        user = getusername()

    except Exception:

        return

    try:

        opsrun(PLAYERPROG, [target], "player", None, user, "front", await_window=True)

    except Exception:

        return


def openitem(path):

    cancelpendingrename()

    if path is None:
        return

    try:

        p = normalisepath(path)

    except Exception:

        return

    if isarraylink(p):
        p, error = resolvearraylink(p)
        if error:
            setstatus(error, error=True)
            return
        if not os.path.exists(p):
            setstatus("link target is not available", error=True)
            return

    if os.path.isdir(p):

        setcwd(p)

        return

    if PICKERMODE:
        if PICKERMODE == "open_file":
            if pickerpathmatches(p):
                if p not in SELECTEDSET:
                    selectpath(p)
                pickerconfirm()
            else:
                setstatus("this file does not match the selected type", error=True)
            return

        if PICKERMODE == "save_as":
            pickernamefromselection(p)
            pickerconfirm()
            return

        setstatus("select a tier, not a file", error=True)
        return

    try:
        extension = os.path.splitext(p)[1].lower()
        program = (SETTINGS.get("associations") or {}).get(extension)
        if program and launchassociation(p, program):
            return
    except Exception:
        pass

    if isaudiofile(p) or isvideofile(p):

        openwithplayer(p)

        return

    if viewersupports is not None and viewersupports(p):

        openwithviewer(p)

        return

    try:

        st = os.stat(p)

        isexec = bool(st.st_mode & 0o111)

    except Exception:

        isexec = False

    try:

        ispy = str(p).lower().endswith(".py")

    except Exception:

        ispy = False

    if ispy or isexec:

        runitem(p)

        return

    if istextfile(p):

        openwithwrite(p)

        return

    opentextdialog("open with", "enter the application path", "", "openwith", p, maxlength=4096)


def openitemheadlesssupported(path):

    """Return whether openitem can complete without Array window UI."""

    try:
        target = normalisepath(path)
    except Exception:
        return False

    if isarraylink(target):
        target, error = resolvearraylink(target)
        if error or not target:
            return False

    if not os.path.isfile(target):
        return False

    try:
        extension = os.path.splitext(target)[1].lower()
        program = (SETTINGS.get("associations") or {}).get(extension)
        if program and os.path.isfile(program):
            return True
    except Exception:
        pass

    if isaudiofile(target) or isvideofile(target):
        return True

    if viewersupports is not None and viewersupports(target):
        return True

    try:
        if bool(os.stat(target).st_mode & 0o111):
            return True
    except Exception:
        pass

    if str(target).lower().endswith(".py") or istextfile(target):
        return True

    return False


# diagnostic functions
def graphicsdiagnostic():

    result = {
        "format": 1,
        "passed": False,
        "resolution": [2560, 1440],
        "window": [1200, 800],
        "checks": {},
        "performance": {},
        "errors": [],
    }

    try:

        state = globals()

        state["SCREENW"] = 2560

        state["SCREENH"] = 1440

        # Diagnostics must not inherit the scale selected in the last live VM
        # session; their geometry fixtures are expressed at 100 percent.
        state["uiscalefactor"] = lambda: 1.0

        applyuiscale()

        state["WINW"] = 1200

        state["WINH"] = 800

        initfont()

        GRAPHICSSTATE.clear()

        GRAPHICSSTATE.update(managedstate())

        capabilities = {
            "version": 2,
            "accelerated": True,
            "managed_resources": True,
            "atomic_scene": True,
            "damage_regions": True,
            "commands": ["rectangle", "border", "line", "image", "text"],
            "command_limit": 1024,
            "text_limit": 1024,
            "damage_limit": 64,
        }

        if not graphicsconfigure(capabilities):

            raise RuntimeError(f"managed capability negotiation failed {GRAPHICSSTATE.get('failure', '')}")

        result["checks"]["capability_negotiation"] = True

        # Core Explorer invariants that do not require a live filesystem.
        saveddrives = dict(DRIVES)
        savedsidebarlinks = list(SIDEBARLINKS)
        try:
            DRIVES.clear()
            DRIVES[1] = {"number": 1, "root": "/", "label": "T1OS", "removable": False}
            driveprobe = drivepath(1, "/master/example")
            if driveprobe is None or driverelpath(driveprobe, DRIVES[1]) != "/master/example" or formatlocation(_physicalnormalize("/")) != "1/":
                raise RuntimeError("numeric drive location mapping is invalid")
            result["checks"]["numeric_drive_locations"] = True

            DRIVES[2] = {"number": 2, "root": "/.ephemeral/volumes/host_files", "label": "host_files", "removable": True}
            buildsidebarlinks()
            driveprobe = drivepath(2, "/photos/example.png")
            driveentry = next((entry for entry in SIDEBARLINKS if entry.get("isdrive") and entry.get("drive") == 2), None)
            if driveprobe != "/.ephemeral/volumes/host_files/photos/example.png" or formatlocation(driveprobe) != "2/photos/example.png":
                raise RuntimeError("VirtualBox shared-folder drive location mapping is invalid")
            if driveentry is None or driveentry.get("path") != "/.ephemeral/volumes/host_files" or driveentry.get("label") != "2  host_files":
                raise RuntimeError("VirtualBox shared-folder drive is absent from the Drives sidebar")
            if not drivemountcandidate("host_files", "/.ephemeral/volumes/host_files") or drivemountcandidate("vboxsf", "/the one/resources/media/music"):
                raise RuntimeError("drive and multimedia mount namespaces overlap")
            if (
                migratedriveroot("/drives/host_files") != "/.ephemeral/volumes/host_files"
                or migratedriveroot("/volumes/host_files") != "/.ephemeral/volumes/host_files"
                or "/drives" in DRIVESCANROOTS
                or "/volumes" in DRIVESCANROOTS
            ):
                raise RuntimeError("legacy public drive roots are still active")
            result["checks"]["virtualbox_shared_folder_drive_sidebar"] = {
                "number": 2,
                "location": "2/",
                "backing_root_private": True,
                "legacy_roots_migrated": True,
            }
        finally:
            DRIVES.clear()
            DRIVES.update(saveddrives)
            state["SIDEBARLINKS"] = savedsidebarlinks

        savedpicker = {
            name: state.get(name)
            for name in (
                "PICKERCONFIG", "PICKERMODE", "PICKERTITLE", "PICKERFILTERS",
                "PICKERFILTERINDEX", "PICKERALLOWMULTIPLE", "PICKERNAME",
                "PICKERNAMECARETPOS", "PICKERNAMEFOCUSED",
                "PICKERNAMESELECTALL", "PICKERNAMESELANCHOR",
                "PICKERNAMEDRAGGING", "PICKERDEFAULTEXTENSION",
                "LAUNCHCWD", "APPNAME",
            )
        }
        savedpickermap = dict(PICKERMAP)
        try:
            for mode in ("open_file", "select_tier", "save_location", "save_as"):
                applypickerconfig({
                    "mode": mode,
                    "title": f"diagnostic {mode}",
                    "initial_path": "/",
                    "allow_multiple": True,
                    "suggested_name": "report",
                    "default_extension": ".txt",
                    "filters": [
                        {"id": "text", "label": "text", "extensions": [".txt", ".md"]},
                        {"id": "all", "label": "all", "extensions": ["*"]},
                    ],
                })
                if PICKERMODE != mode:
                    raise RuntimeError(f"picker mode configuration failed for {mode}")
                if mode != "open_file" and PICKERALLOWMULTIPLE:
                    raise RuntimeError(f"picker allowed multiple selection in {mode}")

            state["PICKERFILTERINDEX"] = 0
            if not pickerpathmatches("/diagnostic/report.TXT") or pickerpathmatches("/diagnostic/image.png"):
                raise RuntimeError("picker extension filtering is invalid")
            state["PICKERFILTERINDEX"] = 1
            if not pickerpathmatches("/diagnostic/image.png"):
                raise RuntimeError("picker all-files filter is invalid")
            result["checks"]["picker_modes_and_filters"] = list(("open_file", "select_tier", "save_location", "save_as"))

            state["PICKERNAME"] = "report.txt"
            PICKERMAP.clear()
            PICKERMAP[(20, 20, 220, 48)] = "name"
            thirdcaret = 20 + PAD + measuretext("rep", FONTSIZESTATUS, FONT)
            if (
                pickernamecaretfromx(20 + PAD) != 0
                or pickernamecaretfromx(thirdcaret) != 3
                or pickernamecaretfromx(220 - PAD) != len(PICKERNAME)
            ):
                raise RuntimeError("save-as filename click did not position the caret")
            result["checks"]["picker_filename_click_caret"] = True

            state["PICKERNAMESELANCHOR"] = 2
            state["PICKERNAMECARETPOS"] = 7
            state["PICKERNAMESELECTALL"] = False
            if pickernameselection() != (2, 7):
                raise RuntimeError("save-as filename drag selection is invalid")
            if not deletepickernameselection() or PICKERNAME != "retxt":
                raise RuntimeError("save-as filename drag selection was not replaceable")
            result["checks"]["picker_filename_drag_selection"] = True
        finally:
            for name, value in savedpicker.items():
                state[name] = value
            PICKERMAP.clear()
            PICKERMAP.update(savedpickermap)

        if not searchmatches("/example/report10.txt", "report10.txt", False, ["report*", "ext:txt", "kind:file"]):
            raise RuntimeError("integrated search filters are invalid")
        result["checks"]["search_filters"] = True

        relevanceprobe = [
            {"name": "notes report.txt", "isdir": False},
            {"name": "report archive.txt", "isdir": False},
            {"name": "report", "isdir": False},
            {"name": "annual report.txt", "isdir": False},
        ]
        relevanceprobe = sortsearchitems(relevanceprobe, "report")
        if [item["name"] for item in relevanceprobe] != [
            "report", "report archive.txt", "annual report.txt", "notes report.txt",
        ]:
            raise RuntimeError("integrated search relevance ordering is invalid")
        if searchmatchspans("Annual Report Report", "report") != [(7, 13), (14, 20)]:
            raise RuntimeError("integrated search highlighting spans are invalid")
        if searchmatchspans("report.txt", "name:report ext:txt") != [(0, 6)]:
            raise RuntimeError("integrated search filter highlighting is invalid")
        result["checks"]["search_relevance_and_highlighting"] = True

        if JOBTHREAD is not None and JOBTHREAD.is_alive() and JOBTHREAD.name != "array-file-jobs":
            raise RuntimeError("file jobs are not using Array's in-process worker")
        result["checks"]["in_process_jobs"] = True

        originalsendws = sendws
        dragmessages = []
        saveddrag = {
            "WINID": WINID,
            "ITEMDRAGSTART": ITEMDRAGSTART,
            "ITEMDRAGPATHS": list(ITEMDRAGPATHS),
            "ITEMDRAGTARGET": ITEMDRAGTARGET,
            "ITEMDRAGSTARTED": ITEMDRAGSTARTED,
            "ITEMDRAGMODS": dict(ITEMDRAGMODS),
        }
        try:
            state["sendws"] = lambda obj: dragmessages.append(dict(obj))
            state["WINID"] = 99
            state["ITEMDRAGSTART"] = (0, 0)
            state["ITEMDRAGPATHS"] = [__file__]
            state["ITEMDRAGTARGET"] = None
            state["ITEMDRAGSTARTED"] = False
            state["ITEMDRAGMODS"] = {}
            itemdragmotion(scalesize(20), scalesize(20))
            finishitemdrag()
        finally:
            state["sendws"] = originalsendws
            for name, value in saveddrag.items():
                state[name] = value

        dragops = [message.get("op") for message in dragmessages]
        if dragops != ["DND_GUEST_START", "DND_GUEST_CLEAR"]:
            raise RuntimeError(f"VirtualBox guest drag lifecycle is invalid {dragops}")
        result["checks"]["virtualbox_guest_drag_lifecycle"] = dragops

        launchpayloads = []
        originalopsrequest = opsrequest
        try:
            state["opsrequest"] = lambda payload: launchpayloads.append(dict(payload)) or {
                "status": "ok",
                "pid": 699,
            }
            pid = opsrun(
                PLAYERPROG, ["/master/music/example.flac"], "example",
                "/the one/logs/forbidden.log", "master", "front",
            )
            if (
                pid != 699
                or launchpayloads != [{
                    "op": "LAUNCH_CATALOGUE",
                    "path": PLAYERPROG,
                    "args": ["/master/music/example.flac"],
                }]
            ):
                raise RuntimeError(
                    "Array did not use the typed Operations catalogue launch"
                )
            result["checks"]["operations_typed_catalogue_launch"] = True
        finally:
            state["opsrequest"] = originalopsrequest

        associationcalls = []
        originalopsrun = opsrun
        originalgetusername = getusername

        try:

            state["opsrun"] = lambda path, args, name, logpath, user, mode, await_window=False: associationcalls.append({
                "path": path,
                "args": list(args),
                "name": name,
                "log": logpath,
                "mode": mode,
                "await_window": bool(await_window),
            }) or 700
            state["getusername"] = lambda: "master"
            audiopath = "/master/music/diagnostic track with spaces.flac"
            imagepath = "/master/images/diagnostic image with spaces.png"
            openitem(audiopath)

            if (
                not isaudiofile(audiopath)
                or isaudiofile("/master/music/not audio.txt")
                or len(associationcalls) != 1
                or associationcalls[0].get("path") != PLAYERPROG
                or associationcalls[0].get("args") != [audiopath]
                or associationcalls[0].get("name") != "player"
                or associationcalls[0].get("log") is not None
                or associationcalls[0].get("mode") != "front"
                or not associationcalls[0].get("await_window")
            ):

                raise RuntimeError(
                    f"Array audio double-click association is invalid "
                    f"audio={isaudiofile(audiopath)} text={isaudiofile('/master/music/not audio.txt')} "
                    f"calls={associationcalls} player={PLAYERPROG}"
                )

            result["checks"]["audio_association_without_log"] = True
            associationcalls.clear()
            videopath = "/master/videos/diagnostic film with spaces.mp4"
            openitem(videopath)

            if (
                not isvideofile(videopath)
                or isvideofile("/master/videos/not video.txt")
                or len(associationcalls) != 1
                or associationcalls[0].get("path") != PLAYERPROG
                or associationcalls[0].get("args") != [videopath]
                or associationcalls[0].get("name") != "player"
                or associationcalls[0].get("log") is not None
                or associationcalls[0].get("mode") != "front"
                or not associationcalls[0].get("await_window")
            ):

                raise RuntimeError("Array video double-click association is invalid")

            result["checks"]["video_association_without_log"] = True
            associationcalls.clear()
            pythonpath = "/master/development/diagnostic script with spaces.py"
            openitem(pythonpath)

            if (
                len(associationcalls) != 1
                or associationcalls[0].get("path") != BRICKPROG
                or associationcalls[0].get("args") != ["--run-file", pythonpath]
                or associationcalls[0].get("name") != "diagnostic script with spaces"
                or associationcalls[0].get("log") is not None
                or associationcalls[0].get("mode") != "front"
                or not associationcalls[0].get("await_window")
            ):

                raise RuntimeError("Array Python association did not use confined Brick")

            result["checks"]["python_association_through_brick"] = True
            associationcalls.clear()
            openitem(imagepath)

            if (
                viewersupports is None
                or not viewersupports(imagepath)
                or viewersupports("/master/images/not image.txt")
                or len(associationcalls) != 1
                or associationcalls[0].get("path") != VIEWERPROG
                or associationcalls[0].get("args") != [imagepath]
                or associationcalls[0].get("name") != "viewer"
                or associationcalls[0].get("log") is not None
                or associationcalls[0].get("mode") != "front"
                or not associationcalls[0].get("await_window")
            ):

                raise RuntimeError("Array image double-click association is invalid")

            result["checks"]["image_association_without_log"] = True
            associationcalls.clear()
            textpath = "/master/documents/diagnostic notes.txt"
            openwithwrite(textpath)

            if (
                len(associationcalls) != 1
                or associationcalls[0].get("path") != WRITEPROG
                or associationcalls[0].get("args") != [textpath]
                or associationcalls[0].get("name") != "write"
                or associationcalls[0].get("log") is not None
                or associationcalls[0].get("mode") != "front"
                or not associationcalls[0].get("await_window")
            ):

                raise RuntimeError("Array Write association creates a document log")

            result["checks"]["write_association_without_log"] = True
            associationcalls.clear()
            launchassociation(textpath, __file__)

            if (
                len(associationcalls) != 1
                or associationcalls[0].get("path") != __file__
                or associationcalls[0].get("args") != [textpath]
                or associationcalls[0].get("log") is not None
                or associationcalls[0].get("mode") != "front"
                or not associationcalls[0].get("await_window")
            ):

                raise RuntimeError("Array custom file association creates a document log")

            result["checks"]["custom_association_without_log"] = True

        finally:

            state["opsrun"] = originalopsrun
            state["getusername"] = originalgetusername

        state["CWD"] = "/master/diagnostic"

        state["SIDEBARLINKS"] = [
            {"label": "root", "path": "/"},
            {"label": "software", "path": "/the one/software"},
            {"label": "diagnostic", "path": "/master/diagnostic"},
        ]

        tree = []

        tree.append({"name": "expanded tier", "path": "/diagnostic/expanded", "isdir": True, "depth": 0, "haskids": True, "expanded": True})

        tree.append({"name": "collapsed tier", "path": "/diagnostic/collapsed", "isdir": True, "depth": 1, "haskids": True, "expanded": False})

        tree.append({"name": "empty tier", "path": "/diagnostic/empty", "isdir": True, "depth": 1, "haskids": False, "expanded": False})

        tree.append({"name": "rename original.txt", "path": "/diagnostic/rename.txt", "isdir": False, "depth": 1, "haskids": False, "expanded": False})

        tree.append({"name": "selected diagnostic file.txt", "path": "/diagnostic/selected.txt", "isdir": False, "depth": 0, "haskids": False, "expanded": False})

        tree.append({"name": "very long diagnostic filename " + ("wide " * 40) + ".txt", "path": "/diagnostic/long.txt", "isdir": False, "depth": 3, "haskids": False, "expanded": False})

        for index in range(34):

            tree.append({
                "name": f"diagnostic-file-{index:02d}.txt",
                "path": f"/diagnostic/file-{index:02d}.txt",
                "isdir": False,
                "depth": index % 3,
                "haskids": False,
                "expanded": False,
            })

        state["TREE"] = tree

        state["SELECTED"] = tree[4]["path"]

        state["SELECTEDSET"] = {tree[4]["path"]}

        state["SELECTANCHOR"] = tree[4]["path"]

        state["CUTSET"] = {tree[6]["path"]}

        state["EXPANDED"] = {tree[0]["path"]}

        state["NAVHIST"] = ["/", "/master", "/master/diagnostic"]

        state["NAVPOS"] = 2

        state["ACTIONVIS"] = {slot["id"]: True for slot in ACTIONSLOTS}

        state["SHOWHIDDEN"] = False

        state["SCROLL"] = 0

        state["HSCROLL"] = 40

        state["RENAMEEDIT"] = True

        state["RENAMEPATH"] = tree[3]["path"]

        state["RENAMETEXT"] = "renamed diagnostic item.txt"

        state["RENAMECARETPOS"] = 18

        state["RENAMESELANCHOR"] = 8

        state["RENAMEBLINKMS"] = 1000000000000000

        state["DRAGBOX"] = True

        state["DRAGBOXSX"] = SIDEBARW + DIVW + 20

        state["DRAGBOXSY"] = CONTENTTOP + 20

        state["DRAGBOXEX"] = SIDEBARW + DIVW + 280

        state["DRAGBOXEY"] = CONTENTTOP + 150

        state["HEADEREDIT"] = False

        state["STATUSMENUOPEN"] = True

        state["STATUSMENUKIND"] = "new"

        state["CONTEXTMENUOPEN"] = False

        state["CONFIRMOPEN"] = False

        layout()

        computecontentwidth()

        layout()

        scene = graphicsbuildscene()

        if not scene or scene[0].get("kind") != "rectangle" or scene[0].get("rect") != [0, 0, WINW, WINH] or int(scene[0].get("color", -1)) != int(COLOURBG):

            raise RuntimeError("managed scene does not begin with a complete opaque background")

        result["checks"]["opaque_background"] = True

        kinds = set(str(command.get("kind", "")) for command in scene)

        if not {"rectangle", "text"}.issubset(kinds) or not kinds.issubset({"rectangle", "text", "border", "line"}):

            raise RuntimeError(f"managed scene contains unexpected command kinds {sorted(kinds)}")

        result["checks"]["rectangle_text_only"] = sorted(kinds)

        limit = int(GRAPHICSSTATE.get("command_limit", 0))

        if len(scene) >= int(limit * 0.75):

            raise RuntimeError(f"managed scene uses too much of the command budget {len(scene)}/{limit}")

        result["checks"]["command_budget"] = {"commands": len(scene), "limit": limit}

        textcommands = [command for command in scene if command.get("kind") == "text"]

        if not textcommands or any(command.get("font") != FONT for command in textcommands):

            raise RuntimeError("managed scene did not consistently use Atkinson Hyperlegible Next")

        if any(len(str(command.get("text", ""))) > int(GRAPHICSSTATE.get("text_limit", 1024)) for command in textcommands):

            raise RuntimeError("managed text exceeded the advertised text limit")

        headerclip = [0, 0, WINW, HEADERH]

        if not any(command.get("kind") == "text" and command.get("clip") == headerclip for command in scene):

            raise RuntimeError("managed header text was not clipped to the header")

        mainclip = list(mainpanerect())

        maintext = [command for command in textcommands if command.get("clip") == mainclip]

        if not maintext:

            raise RuntimeError("managed tree text was not clipped to the main pane")

        if any(command.get("clip")[0] + command.get("clip")[2] > mainclip[0] + mainclip[2] for command in maintext):

            raise RuntimeError("managed tree content overlaps reserved scrollbar space")

        result["checks"]["tree_clipping"] = True

        collapsed = [command for command in maintext if command.get("text") == ">"]

        if not collapsed:

            raise RuntimeError("managed tree did not preserve collapsed directory arrows")

        selectedtext = [command for command in maintext if "file.txt" in str(command.get("text", "")) and int(command.get("color", -1)) == int(COLOURTEXT)]

        renametext = [command for command in maintext if "renamed diagnostic" in str(command.get("text", ""))]

        if not selectedtext or not renametext:

            raise RuntimeError("managed tree did not preserve selection and rename text")

        selectedrowrect = rowrect(4)

        if selectedrowrect is None or not any(
            command.get("kind") == "rectangle"
            and command.get("rect") == list(selectedrowrect)
            and int(command.get("color", -1)) == int(COLOURSTATUS)
            for command in scene
        ):

            raise RuntimeError("managed tree did not preserve sidebar-style selection")

        dragrect = dragboxrect()

        if dragrect is None or not any(
            (command.get("kind") == "border" and command.get("rect") == list(dragrect))
            or (command.get("kind") == "rectangle" and command.get("rect") == [dragrect[0], dragrect[1], dragrect[2], 1])
            for command in scene
        ):

            raise RuntimeError("managed drag-selection rectangle was not emitted")

        result["checks"]["tree_selection_rename"] = True

        result["checks"]["drag_box"] = True

        savedview = VIEWMODE
        savedproperties = PROPERTIESPANE
        try:
            for item in TREE:
                item.setdefault("displayname", item.get("name", ""))
                item.setdefault("modifiedstr", "2026-01-01 00:00")
                item.setdefault("type", "tier" if item.get("isdir") else "text/plain")
                item.setdefault("sizestr", "1 KB" if not item.get("isdir") else "")
                item.setdefault("size", 1024 if not item.get("isdir") else 0)
                item.setdefault("mode", (stat.S_IFDIR if item.get("isdir") else stat.S_IFREG) | 0o644)
            state["VIEWMODE"] = "details"
            state["PROPERTIESPANE"] = True
            layout()
            detailsscene = graphicsbuildscene()
            detailtexts = [str(command.get("text", "")) for command in detailsscene if command.get("kind") == "text"]
            if (
                not any("modified" in text for text in detailtexts)
                or "properties" not in detailtexts
                or not any("size: 1 KB" in text for text in detailtexts)
                or "mode" not in detailtexts
                or "read and write" not in detailtexts
                or "hidden" not in detailtexts
            ):
                raise RuntimeError("managed details and properties panes were not emitted")
            modecontrol = SIDEPROPERTIESCONTROLS.get("mode")
            hiddencontrol = SIDEPROPERTIESCONTROLS.get("hidden")
            if not modecontrol or not hiddencontrol:
                raise RuntimeError("properties pane mode and hidden controls are not interactive")
            sidepropertiespointer({
                "pressed": True,
                "button": 1,
                "x": modecontrol[0] + 1,
                "y": modecontrol[1] + 1,
            })
            dropdownscene = graphicsbuildscene()
            dropdowntexts = [str(command.get("text", "")) for command in dropdownscene if command.get("kind") == "text"]
            if not SIDEPROPERTIESDROPDOWN or "executable" not in dropdowntexts:
                raise RuntimeError("properties pane mode selector did not open")
            if not any("hide extensions" in text or "show extensions" in text for text in detailtexts):
                raise RuntimeError("managed explorer top bar was not emitted")
            result["checks"]["details_properties_topbar_scene"] = True
        finally:
            state["SIDEPROPERTIESDROPDOWN"] = False
            state["SIDEPROPERTIESDROPDOWNHOVER"] = None
            state["VIEWMODE"] = savedview
            state["PROPERTIESPANE"] = savedproperties
            layout()

        vtrack = list(vscrolltrackgeometry())

        htrack = list(hscrolltrackgeometry())

        if vtrack[2] < 1 or htrack[2] < 1:

            raise RuntimeError("diagnostic did not exercise both scrollbars")

        vbackgrounds = [command for command in scene if command.get("kind") == "rectangle" and command.get("rect") == vtrack and int(command.get("color", -1)) == int(COLOURBG)]

        hbackgrounds = [command for command in scene if command.get("kind") == "rectangle" and command.get("rect") == htrack and int(command.get("color", -1)) == int(COLOURBG)]

        if len(vbackgrounds) != 1 or len(hbackgrounds) != 1:

            raise RuntimeError("managed scrollbars do not contain one opaque track each")

        statusrect = [0, WINH - STATUSH, WINW, STATUSH]

        statusbackground = next((command for command in scene if command.get("kind") == "rectangle" and command.get("rect") == statusrect and int(command.get("color", -1)) == int(COLOURSTATUS)), None)

        if statusbackground is None:

            raise RuntimeError("managed status bar background was not emitted")

        if scene.index(vbackgrounds[0]) >= scene.index(statusbackground) or scene.index(hbackgrounds[0]) >= scene.index(statusbackground):

            raise RuntimeError("managed scrollbars are not layered before the status bar")

        result["checks"]["scrollbar_geometry"] = {"vertical": vtrack, "horizontal": htrack, "opaque": True}

        originalroleloader = arch.loadrole

        originalpermissioncheck = arch.check

        originalrole = arch.currentrole

        checkedpaths = []

        originalstatuspanel = STATUSMENU_PANEL

        originaldeleteitem = deleteitem

        originalapplyundo = applyundo

        originalapplyredo = applyredo

        originalundo = UNDO

        originalredo = REDO

        try:

            arch.loadrole = lambda: "master"

            arch.check = lambda path: checkedpaths.append(path) or not str(path).endswith("blocked")

            if permissionpaths("/diagnostic/allowed", "/diagnostic/blocked"):
                raise RuntimeError("Array Architect permission helper allowed a denied path")

            if len(checkedpaths) != 2:
                raise RuntimeError("Array Architect permission helper did not check every path before denial")

            checkedcount = len(checkedpaths)

            mutationcalls = []

            state["deleteitem"] = lambda path, record=False: mutationcalls.append(path)

            deleteitems(["/diagnostic/allowed", "/diagnostic/blocked"])

            if mutationcalls:
                raise RuntimeError("Array multi-item permission preflight allowed a partial mutation")

            historycalls = []

            state["UNDO"] = [{
                "type": "create",
                "items": [{"path": "/diagnostic/blocked", "isdir": False}],
            }]

            state["REDO"] = [{
                "type": "create",
                "items": [{"path": "/diagnostic/blocked", "isdir": False}],
            }]

            state["applyundo"] = lambda op: historycalls.append("undo") or True

            state["applyredo"] = lambda op: historycalls.append("redo") or True

            undoaction()

            redoaction()

            if historycalls or len(UNDO) != 1 or len(REDO) != 1:
                raise RuntimeError("Array denied history operation changed its stack or mutation state")

            permissionstatusscene = graphicsbuildscene()

            permissiontext = next((
                command for command in permissionstatusscene
                if command.get("kind") == "text"
                and command.get("text") == "permission denied"
                and int(command.get("color", -1)) == int(COLOURERROR)
                and command.get("clip") == statusrect
            ), None)

            if permissiontext is None:
                raise RuntimeError("Array permission denial was not rendered in the status bar")

            arch.check = None

            if permissionpaths("/diagnostic/error"):
                raise RuntimeError("Array Architect permission helper failed open after a check error")

            result["checks"]["permission_status"] = True

            result["checks"]["permission_checks"] = {
                "denied": True,
                "fail_closed": True,
                "checked_paths": checkedcount,
                "batch_preflight": True,
                "history_preflight": True,
            }

        finally:

            arch.loadrole = originalroleloader

            arch.check = originalpermissioncheck

            arch.currentrole = originalrole

            state["deleteitem"] = originaldeleteitem

            state["applyundo"] = originalapplyundo

            state["applyredo"] = originalapplyredo

            state["UNDO"] = originalundo

            state["REDO"] = originalredo

            clearstatus()

            state["STATUSMENU_PANEL"] = originalstatuspanel

        statuspanel = STATUSMENU_PANEL

        if statuspanel is None:

            raise RuntimeError("managed status menu panel was not calculated")

        statusmenubackground = next((command for command in scene if command.get("kind") == "rectangle" and command.get("rect") == list(statuspanel) and int(command.get("color", -1)) == int(COLOURSTATUS)), None)

        if statusmenubackground is None or scene.index(statusmenubackground) <= scene.index(statusbackground):

            raise RuntimeError("managed status menu was not layered over the status bar")

        state["STATUSMENUOPEN"] = False

        state["HEADEREDIT"] = True

        state["HEADEREDITTEXT"] = "master/diagnostic/a very long selected path"

        state["HEADERCARETPOS"] = len(HEADEREDITTEXT)

        state["HEADERSELSTART"] = 7

        state["HEADERSELEND"] = 17

        state["HEADERBLINKMS"] = 1000000000000000

        state["CONTEXTMENUOPEN"] = True

        state["CONTEXTMENUKIND"] = "empty"

        state["CONTEXTMENU_ANCHOR"] = (WINW - 220, WINH - STATUSH - 180)

        state["CONTEXTMENUTARGET"] = CWD

        state["CONTEXTMENUHOVERACTION"] = "newfile"

        originalcontextitems = contextmenuitems

        state["contextmenuitems"] = lambda: [("open", "open"), ("new file", "newfile"), ("paste", "paste")]

        try:

            editscene = graphicsbuildscene()

        finally:

            state["contextmenuitems"] = originalcontextitems

        edittext = [command for command in editscene if command.get("kind") == "text" and command.get("clip") == headerclip]

        if not any("selected path" in str(command.get("text", "")) for command in edittext):

            raise RuntimeError("managed header edit text was not emitted")

        if not any(command.get("kind") == "rectangle" and int(command.get("color", -1)) == int(COLOURTEXT) and command.get("clip") == headerclip for command in editscene):

            raise RuntimeError("managed header selection or caret geometry was not emitted")

        contextpanel = CONTEXTMENU_PANEL

        if contextpanel is None:

            raise RuntimeError("managed context menu panel was not calculated")

        contextbackground = next((command for command in editscene if command.get("kind") == "rectangle" and command.get("rect") == list(contextpanel) and int(command.get("color", -1)) == int(COLOURCONTEXTBG)), None)

        if contextbackground is None:

            raise RuntimeError("managed context menu background was not emitted")

        contexthovery = int(contextpanel[1]) + int(CONTEXTMENU_PAD_Y) + int(STATUSMENU_ITEM_H)

        contexthover = next((
            command for command in editscene
            if command.get("kind") == "rectangle"
            and command.get("rect") == [int(contextpanel[0]) + 1, contexthovery, max(1, int(contextpanel[2]) - 2), int(STATUSMENU_ITEM_H)]
            and int(command.get("color", -1)) == int(COLOURSTATUS)
        ), None)

        if contexthover is None:

            raise RuntimeError("managed context menu hover treatment was not emitted")

        contextseparators = [
            command for command in editscene
            if command.get("kind") == "rectangle"
            and int(command.get("color", -1)) == int(COLOURCONTEXTDIVIDER)
            and int(command.get("rect", [0, 0, 0, 0])[2]) == int(contextpanel[2])
            and int(command.get("rect", [0, 0, 0, 0])[3]) == 1
            and int(command.get("rect", [0, 0, 0, 0])[0]) == int(contextpanel[0])
        ]

        if len(contextseparators) < 2:

            raise RuntimeError("managed context menu separators were not emitted")

        result["checks"]["header_modes"] = True

        state["CONTEXTMENUOPEN"] = False

        state["CONTEXTMENUHOVERACTION"] = None

        state["HEADEREDIT"] = False

        state["CONFIRMOPEN"] = True

        state["CONFIRMACTION"] = "delete"

        state["CONFIRMPATHS"] = ["/diagnostic/selected.txt"]

        state["CONFIRMFOCUS"] = 0

        confirmscene = graphicsbuildscene()

        confirmpanel = CONFIRMPANEL

        if confirmpanel is None:

            raise RuntimeError("managed confirmation panel was not calculated")

        confirmbackground = next((command for command in confirmscene if command.get("kind") == "rectangle" and command.get("rect") == list(confirmpanel) and int(command.get("color", -1)) == int(COLOURSTATUS)), None)

        if confirmbackground is None or confirmscene.index(confirmbackground) <= confirmscene.index(statusbackground):

            raise RuntimeError("managed confirmation panel was not the final overlay")

        def bordercount(commands, rect, colour):

            x, y, width, height = [int(value) for value in rect]

            if any(
                command.get("kind") == "border"
                and [int(value) for value in command.get("rect", [])] == [x, y, width, height]
                and int(command.get("color", -1)) == int(colour)
                for command in commands
            ):
                return 4

            expected = {
                (x, y, width, 1),
                (x, y + height - 1, width, 1),
                (x, y + 1, 1, height - 2),
                (x + width - 1, y + 1, 1, height - 2),
            }

            found = {
                tuple(command.get("rect", []))
                for command in commands
                if command.get("kind") == "rectangle" and int(command.get("color", -1)) == int(colour)
            }

            return len(expected.intersection(found))

        if bordercount(scene, statuspanel, COLOURDIVIDER) != 4 or bordercount(editscene, contextpanel, COLOURDIVIDER) != 4 or bordercount(confirmscene, confirmpanel, COLOURDIVIDER) != 4:

            raise RuntimeError("managed overlay panels did not preserve four-edge outlines")

        result["checks"]["overlay_order"] = True

        result["checks"]["outlined_panels"] = {"status": 4, "context": 4, "confirm": 4}

        expectedrow = next(index for index, item in enumerate(TREE) if "diagnostic-file-" in item["name"])

        expectedy = CONTENTTOP + ((expectedrow - SCROLL) * ROWH) + (ROWH // 2) - (FONTSIZEROW // 2)

        expectedtexty = int(graphicstexty(expectedy, FONTSIZEROW, FONT))

        filecommand = next((
            command for command in scene
            if command.get("kind") == "text"
            and command.get("clip") == mainclip
            and int(command.get("y", -1)) == expectedtexty
            and str(command.get("text", ""))
        ), None)

        if filecommand is None:

            raise RuntimeError("managed diagnostic file row was not emitted")

        if int(filecommand.get("y", -1)) != expectedtexty:

            raise RuntimeError("managed Atkinson baseline does not match the CPU text baseline")

        result["checks"]["atkinson_baseline"] = True

        probe = []

        graphicstext(probe, -20, 20, "variable width " * 10, COLOURTEXT, FONTSIZEROW, FONT, [40, 0, 180, 80])

        if not probe or any(command.get("x", 0) < 40 or command.get("clip") != [40, 0, 180, 80] for command in probe):

            raise RuntimeError("managed variable-width text was not safely clipped")

        result["checks"]["variable_width_clipping"] = True

        state["CONFIRMOPEN"] = False

        state["RENAMEEDIT"] = False

        state["DRAGBOX"] = False

        samples = []

        maximumcommands = 0

        for _ in range(25):

            started = time.monotonic_ns()

            measuredscene = graphicsbuildscene()

            samples.append((time.monotonic_ns() - started) / 1000000.0)

            maximumcommands = max(maximumcommands, len(measuredscene))

        managedmarkdamage(GRAPHICSSTATE, [10, 20, 60, 40], bounds=(WINW, WINH))

        managedmarkdamage(GRAPHICSSTATE, [40, 40, 80, 40], bounds=(WINW, WINH))

        if len(GRAPHICSSTATE.get("damage", [])) != 1:

            raise RuntimeError("overlapping managed damage rectangles were not coalesced")

        result["checks"]["damage_coalescing"] = len(GRAPHICSSTATE.get("damage", []))

        requests = []

        managedsubmit(GRAPHICSSTATE, lambda request: requests.append(request) or True, 99, scene)

        if len(requests) != 1 or requests[0].get("op") != "GRAPHICS_SCENE" or len(requests[0].get("commands", [])) != len(scene):

            raise RuntimeError("Array did not submit one complete atomic scene")

        if len(requests[0].get("damage", [])) != 1:

            raise RuntimeError("Array atomic scene did not retain coalesced damage")

        managedresponse(GRAPHICSSTATE, {
            "op": "GRAPHICS_COMMITTED",
            "winid": 99,
            "count": len(scene),
            "batch": True,
            "accelerated": True,
            "managed_only": True,
        })

        if not GRAPHICSSTATE.get("active") or GRAPHICSSTATE.get("pending"):

            raise RuntimeError("Array managed scene acknowledgement did not activate rendering")

        result["checks"]["atomic_scene"] = {"messages": len(requests), "commands": len(scene), "damage": len(requests[0].get("damage", []))}

        state["SCROLL"] = 0
        state["PENDINGSCROLL"] = 0
        state["LASTSCROLLFRAME"] = 0.0

        for _ in range(1000):
            onscroll({"delta": -1})

        if SCROLL != 0 or PENDINGSCROLL != -len(TREE):
            raise RuntimeError(f"Array rapid wheel input was not coalesced {SCROLL}/{PENDINGSCROLL}")

        if not flushscroll(force=True):
            raise RuntimeError("Array coalesced wheel input did not flush")

        expectedscroll = max(0, len(TREE) - VISIBLECOUNT)

        if SCROLL != expectedscroll or PENDINGSCROLL != 0:
            raise RuntimeError(f"Array coalesced wheel input produced the wrong viewport {SCROLL}/{PENDINGSCROLL}")

        result["checks"]["scroll_coalescing"] = {"events": 1000, "redraws": 1}

        cpustate = managedstate(cpu=True)

        if managedconfigure(cpustate, capabilities, required=("rectangle", "text"), cpu=True):

            raise RuntimeError("Array CPU override unexpectedly enabled managed rendering")

        missingstate = managedstate()

        if managedconfigure(missingstate, {}, required=("rectangle", "text")):

            raise RuntimeError("Array missing capabilities unexpectedly enabled managed rendering")

        errorstate = managedstate()

        managedconfigure(errorstate, capabilities, required=("rectangle", "text"))

        managedresponse(errorstate, {"op": "ERROR", "code": "graphics_scene_failed", "detail": "diagnostic"})

        if (
            not errorstate.get("available")
            or not errorstate.get("active")
            or not errorstate.get("managed_only")
            or not errorstate.get("need_submit")
        ):

            raise RuntimeError("Array graphics error escaped strict GPU rendering")

        timeoutstate = managedstate()

        managedconfigure(timeoutstate, capabilities, required=("rectangle", "text"))

        managedsubmit(timeoutstate, lambda request: True, 99, [scene[0]])

        timeoutstate["pending_at"] = time.monotonic() - 3.0

        if (
            not managedtick(timeoutstate, timeout=2.0)
            or not timeoutstate.get("active")
            or not timeoutstate.get("managed_only")
            or not timeoutstate.get("need_submit")
        ):

            raise RuntimeError("Array managed timeout escaped strict GPU rendering")

        result["checks"]["cpu_fallback"] = True

        result["checks"]["missing_capability_fallback"] = True

        result["checks"]["error_gpu_retention"] = True

        result["checks"]["timeout_gpu_retention"] = True

        result["checks"]["first_frame_complete"] = True

        result["performance"] = {
            "average_scene_build_ms": round(sum(samples) / max(1, len(samples)), 3),
            "maximum_scene_build_ms": round(max(samples) if samples else 0.0, 3),
            "maximum_commands": maximumcommands,
            "visible_rows": int(VISIBLECOUNT),
            "window": [WINW, WINH],
        }

        result["passed"] = True

    except Exception as e:

        result["errors"].append(str(e))

    print(json.dumps(result, separators=(",", ":"), sort_keys=True))

    return bool(result["passed"])


# core functions
def initapp():

    global NEEDWINDOW

    try:

        log("initapp start")

        # load show hidden setting
        loadhidden()

        loadsettings()

        startjobworker()

        # connect to windowserver
        connectws()

        log("connectws ok")

    except Exception as e:

        log(f"initapp connectws exception {e}")

        sys.exit(1)

    sendws({"op": "HELLO"})

    sendws({"op": "SUBSCRIBE", "types": ["fbsize"]})

    NEEDWINDOW = True

    try:

        # wait for window_created message
        log("waiting for window_created")

        loops = 0

        while WINID is None:

            loops += 1

            events = sel.select(timeout=0.1)

            log(f"wait loop {loops} events={len(events)} winid={WINID} outbuf={len(OUTBUF)} inbuf={len(INBUF)}")

            for key, _ in events:

                if key.fileobj is WSOCK:

                    msgs = recvws()

                    log(f"recvws returned {len(msgs)} msgs")

                    for msg in msgs:

                        try:
                            log(f"ws msg op={msg.get('op')}")
                        except Exception:
                            log("ws msg op read failed")

                        handlewsmsg(msg)

                        log(f"after handlewsmsg winid={WINID} w={WINW} h={WINH} buf={'set' if BUF else 'none'}")

            flushws()

    except Exception as e:

        log(f"initapp wait loop exception {e}")

        sys.exit(1)

    # apply launch cwd (if provided)
    if LAUNCHCWD is not None:

        if os.path.isdir(LAUNCHCWD):

            setcwd(LAUNCHCWD, record=False)

    # paint and present a complete frame before making the window visible
    invalidaterect(0, 0, WINW, WINH)

    renderdirty()

    flushws()

    try:

        # map the fully painted window so its first visible frame is complete
        mapwindow()

        # ensure it's topmost and focused
        sendws({"op": "RAISE", "winid": WINID})

        sendws({"op": "FOCUS_SET", "winid": WINID})

        flushws()

    except Exception as e:

        log(f"initapp post-create map/focus exception {e}")

        sys.exit(1)


def pulse():

    global HEADERLASTBLINK, RENAMELASTBLINK, RUNNING

    # Keep the loop responsive while an eased wheel animation is active.
    events = sel.select(timeout=0.01 if PENDINGSCROLL else 0.05)

    for key, mask in events:

        if key.fileobj is WSOCK:

            if mask & selectors.EVENT_READ:

                msgs = recvws()

                for msg in msgs:

                    handlewsmsg(msg)

                    op = msg.get("op")

                    if op == "POINTER_MOTION":

                        onpointermotion(msg)

                    elif op == "POINTER_LEAVE":

                        clearsidebarhover()
                        clearcontextmenuhover()
                        setpointercursor("arrow")

                    elif op == "POINTER_BUTTON":

                        try:

                            msg["pressed"] = (str(msg.get("state", "down")) == "down")

                        except Exception:

                            msg["pressed"] = True

                        onpointerbutton(msg)

                    elif op == "SCROLL":

                        try:

                            # array expects a single delta; windowserver provides dx/dy
                            msg["delta"] = int(msg.get("dy", 0))

                        except Exception:

                            msg["delta"] = 0

                        onscroll(msg)

                    elif op == "KEY":

                        onkey(msg)

                    elif op == "TEXT":

                        ontext(msg)

                    elif op == "FOCUS":
                        onfocus(msg)

            if mask & selectors.EVENT_WRITE:

                flushws()

    headerrepeat()

    pendingrenamepump()

    # handle header cursor blink
    if HEADEREDIT:

        t = nowms()

        # toggle state every HEADERBLINKMS
        state = (t // HEADERBLINKMS) % 2 == 0

        if state != HEADERLASTBLINK:

            HEADERLASTBLINK = state

            # invalidate header area to force redraw
            invalidaterect(0, 0, WINW, HEADERH)

    # handle rename cursor blink
    if RENAMEEDIT:

        t = nowms()

        state = (t // RENAMEBLINKMS) % 2 == 0

        if state != RENAMELASTBLINK:

            RENAMELASTBLINK = state

            invalidateselectionrow(RENAMEPATH)

    if STATUSMESSAGE != "" and not statusactive():

        clearstatus()

    # Advance queued wheel movement in eased, frame-paced steps.
    flushscroll()

    drivepump()

    watchpump()

    jobpump()

    searchpump()

    updatesearchcaret()

    # only draw when something requested it
    renderdirty()

    # flush deferred scenes and enforce managed commit timeouts
    graphicspump()


def main():

    global RUNNING, LAUNCHCWD, LAUNCHOPENITEM, LAUNCHSEARCHTEXT, LAUNCHSEARCHSESSION, PICKERSESSION
    global LAUNCHCONTEXTACTION, LAUNCHCONTEXTITEM
    global ACTIONFROMCONTEXT, ACTIONCONTEXTTARGET
    global SEARCHTEXT, SEARCHCARETPOS, SEARCHSCOPE

    # launch argument parsing
    if len(sys.argv) > 2 and str(sys.argv[1]).strip().lower() == "--picker-session":

        PICKERSESSION = str(sys.argv[2]).strip()

    elif len(sys.argv) > 3 and str(sys.argv[1]).strip().lower() == "--context-action":

        try:
            LAUNCHCONTEXTACTION = str(sys.argv[2]).strip().lower()
            LAUNCHCONTEXTITEM = normalisepath(sys.argv[3])
            # Open the parent so the target exists as a selectable row; Array's
            # actions intentionally operate through its normal selection model.
            LAUNCHCWD = os.path.dirname(LAUNCHCONTEXTITEM.rstrip("/")) or "/"
        except Exception:
            LAUNCHCONTEXTACTION = None
            LAUNCHCONTEXTITEM = None
            LAUNCHCWD = None

    elif len(sys.argv) > 2 and str(sys.argv[1]).strip().lower() == "--open-item":

        try:

            LAUNCHOPENITEM = normalisepath(sys.argv[2])

            if os.path.isdir(LAUNCHOPENITEM):
                LAUNCHCWD = LAUNCHOPENITEM
            else:
                LAUNCHCWD = os.path.dirname(LAUNCHOPENITEM) or "/"

        except Exception:

            LAUNCHOPENITEM = None
            LAUNCHCWD = None

    elif len(sys.argv) > 3 and str(sys.argv[1]).strip().lower() == "--search-session":

        LAUNCHSEARCHSESSION = str(sys.argv[2]).strip()
        LAUNCHSEARCHTEXT = str(sys.argv[3]).strip()
        LAUNCHCWD = "/"

    elif len(sys.argv) > 2 and str(sys.argv[1]).strip().lower() == "--search":

        LAUNCHSEARCHTEXT = str(sys.argv[2]).strip()
        LAUNCHCWD = "/"

    elif len(sys.argv) > 1:

        try:

            LAUNCHCWD = normalisepath(sys.argv[1])

        except Exception:

            LAUNCHCWD = None

    if LAUNCHOPENITEM is not None and os.path.isfile(LAUNCHOPENITEM):

        # Search activation uses Array's real openitem operation.  Known file
        # types need no explorer surface; unknown types still open Array so its
        # normal "open with" dialog remains available.
        loadsettings()

        if openitemheadlesssupported(LAUNCHOPENITEM):
            target = LAUNCHOPENITEM
            LAUNCHOPENITEM = None
            openitem(target)
            return

    initapp()

    if LAUNCHSEARCHSESSION and LAUNCHSEARCHTEXT:

        if not adoptsearchsession(LAUNCHSEARCHSESSION, LAUNCHSEARCHTEXT):
            # If the producer disappeared between launch and initialisation,
            # preserve the old behavior so the requested search still works.
            SEARCHTEXT = LAUNCHSEARCHTEXT
            SEARCHCARETPOS = len(SEARCHTEXT)
            SEARCHSCOPE = "terminal"
            searchopen()
            searchstart()

    elif LAUNCHSEARCHTEXT:

        SEARCHTEXT = LAUNCHSEARCHTEXT
        SEARCHCARETPOS = len(SEARCHTEXT)
        SEARCHSCOPE = "terminal"
        searchopen()
        searchstart()

    if LAUNCHOPENITEM is not None:

        target = LAUNCHOPENITEM
        LAUNCHOPENITEM = None
        openitem(target)

    if LAUNCHCONTEXTACTION and LAUNCHCONTEXTITEM:

        action = LAUNCHCONTEXTACTION
        target = LAUNCHCONTEXTITEM
        LAUNCHCONTEXTACTION = None
        LAUNCHCONTEXTITEM = None
        selectpath(target)
        scrolltopath(target)
        ACTIONFROMCONTEXT = True
        ACTIONCONTEXTTARGET = target
        try:
            runaction(action)
        finally:
            ACTIONFROMCONTEXT = False
            ACTIONCONTEXTTARGET = None

    while RUNNING:

        pulse()



# execute main
if __name__ == "__main__":

    if len(sys.argv) > 1 and str(sys.argv[1]).strip().lower() == "graphics-diagnostic":

        sys.exit(0 if graphicsdiagnostic() else 1)

    main()
