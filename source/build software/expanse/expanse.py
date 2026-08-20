#!"/the one/software/python/bin/python" -B

"""
expanse.py

expanse is the desktop and taskbar for The One OS.
"""



## imports
import os
import sys
import json
import time
import math
import struct
import stat
import shutil
import signal
import socket
import ctypes
import hashlib
import warnings
import freetype
import selectors
import traceback
import subprocess
import threading
import queue
import re
from pyroute2 import IPRoute

sys.path.insert(0, '/the one/build')

from reign.reign import timestamp
from GODDESS.GODDESS import formatlog, popenisolated, softwarelogpath
from operations.operations import (
    OperationsRequestError,
    PowerRequestError,
    createdesktopitem,
    renamedesktopitem,
    requestpower,
)
from exchange.exchange import exmeta
from graphics.graphics import fillbufferfile, initbuffer, clear, present, drawrect, drawline, initttffont, drawtextttf, measuretext, getttfface
from graphics.graphics import managedstate, managedconfigure, manageddisable, managedmarkdamage, managedclear, managedtick, managedsubmit, managedresponse, uiscalefactor, displayuiscale
from search.search import iterfindnames as searchiterfindnames



## globals

# paths
LOGFILE = "/the one/logs/expanse.py.log"
SOCKPATH = "/.ephemeral/windowserver/accept.sock"
STATEBASE = "/the one/build/state"
STATEBASE_ALT = "/.ephemeral/windowserver/state"
ICONRESOURCEROOT = "/the one/resources/logos"
IMAGECATALOGUE = "/the one/catalogue/image"
ICONCACHEROOT = f"/.ephemeral/expanse/icons-{os.getpid()}"
SURFACESTAGINGROOT = f"/.ephemeral/expanse/surfaces-{os.getpid()}"
SEARCHHANDOFFROOT = "/.ephemeral/expanse/search-handoffs"
T1OSLOGOPATH = "/the one/resources/logos/t1os/t1oslogo.png"
T1OSLOGOMUTEDPATH = "/the one/resources/logos/t1os/t1oslogomuted.png"
POWERLOGOPATH = "/the one/resources/logos/powerbutt/powerbutt.png"
POWERLOGOMUTEDPATH = "/the one/resources/logos/powerbutt/powerbuttmuted.png"
NETWORKICONPATH = "/the one/resources/logos/network/networkicon.png"
GREYNETWORKICONPATH = "/the one/resources/logos/network/greynetworkicon.png"
AUDIOICONBASE = "/the one/resources/logos/audio"
AUDIOZEROICONPATH = "/the one/resources/logos/audio/audiozero.png"
AUDIOLOWICONPATH = "/the one/resources/logos/audio/audiolow.png"
AUDIOMEDICONPATH = "/the one/resources/logos/audio/audiomedium.png"
AUDIOFULLICONPATH = "/the one/resources/logos/audio/audiofull.png"
AUDIOUNAVAILICONPATH = "/the one/resources/logos/audio/audiounavailable.png"
AUDIOSOCK = "/.ephemeral/audio/accept.sock"
NETWORKCONNECTIONSTATE = "/.ephemeral/network/connection.json"
NETWORKSETTINGS = "/the one/settings/network"
ETHERNETNAMESFILE = "/the one/settings/network/ethernet-names.json"
NETWORKSTATE = "/the one/drivers/state/class/net"
FONTPATH = "/the one/resources/fonts/atkinsonhyperlegiblenext.ttf"
SESSIONIDENTITYFILE = '/the one/settings/session/identity.json'
SESSIONIDENTITYMAXBYTES = 1024
SESSIONUSERNAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,31}')
MASTERSETTINGSFILE = '/the one/settings/master/settings.json'

# software icons
SOFTWAREICONS = {
    "array": {
        "path": "/the one/resources/logos/array/arraylogo.png"
    },
    "brick": {
        "path": "/the one/resources/logos/brick/bricklogo.png"
    },
    "calculator": {
        "path": "/the one/resources/logos/calculator/calculatorlogo.png"
    },
    "operations centre": {
        "path": "/the one/resources/logos/operations centre/operationscentrelogo.png"
    },
    "operations": {
        "path": "/the one/resources/logos/operations centre/operationscentrelogo.png"
    },
    "chromium": {
        "path": "/the one/resources/logos/chromium/chromiumlogo.png"
    },
    "player": {
        "path": "/the one/resources/logos/player/playerlogo.png"
    },
    "settings": {
        "path": "/the one/resources/logos/settings/settingslogo.png"
    },
    "snap": {
        "path": "/the one/resources/logos/snap/snaplogo.png"
    },
    "viewer": {
        "path": "/the one/resources/logos/viewer/viewerlogo.png"
    },
    "write": {
        "path": "/the one/resources/logos/write/writelogo.png"
    }
}

# misc
DEBUGEXPANSE = False
ALLOWINLINEFALLBACK = False
RUN = True
SEL = selectors.DefaultSelector()

# scaling
BASE_DESKTOPW = 1920
BASE_DESKTOPH = 1080
SCALE = 1.0
ICONPIXELLIMIT = 16777216
ICONCONVERTERVERSION = 2
ICONMASTERINFO = {}
MASTERIMAGEINFO = {}
ICONCACHE = {}
ICONCACHEFAILURES = set()
ICONCACHEHITS = 0
ICONCACHEMISSES = 0
PILIMAGE = None

# font
TTFFACE = None
BASE_BRICKFONTSIZE = 18
BASE_CLOCKFONTSIZE = 14
BASE_HOVERFONTSIZE = 14
BASE_STARTTITLESIZE = 18
BASE_STARTITEMSIZE = 16
BRICKFONTSIZE = BASE_BRICKFONTSIZE
CLOCKFONTSIZE = BASE_CLOCKFONTSIZE
HOVERFONTSIZE = BASE_HOVERFONTSIZE
STARTTITLESIZE = BASE_STARTTITLESIZE
STARTITEMSIZE = BASE_STARTITEMSIZE
STARTTITLECOLOR = 0xEFEFEF
STARTITEMCOLOR = 0xE0E0E0
HOVERCOLOR = 0xEFEFEF

# desktop
DESKTOPW = BASE_DESKTOPW
DESKTOPH = BASE_DESKTOPH
BASE_TASKBARH = 48
BASE_LAUNCHX = 12
BASE_LAUNCHW = 140
BASE_LAUNCHH = 24
BASE_LEFTPAD = 10
BASE_CLOCKPADX = 12
BASE_MASTERIMAGE_SIZE = 30
BASE_SEARCHW = 224
BASE_SEARCHH = 34
BASE_SEARCHPANELW = 420
BASE_SEARCHROWH = 36
BASE_SEARCHFILTERH = 24
BASE_SEARCHPAD = 12
BASE_SEARCHFONTSIZE = 14
TASKBARH = BASE_TASKBARH
LAUNCHX = BASE_LAUNCHX
LAUNCHW = BASE_LAUNCHW
LAUNCHH = BASE_LAUNCHH
LEFTPAD = BASE_LEFTPAD
CLOCKPADX = BASE_CLOCKPADX
MASTERIMAGE_SIZE = BASE_MASTERIMAGE_SIZE
SEARCHW = BASE_SEARCHW
SEARCHH = BASE_SEARCHH
SEARCHPANELW = BASE_SEARCHPANELW
SEARCHROWH = BASE_SEARCHROWH
SEARCHFILTERH = BASE_SEARCHFILTERH
SEARCHPAD = BASE_SEARCHPAD
SEARCHFONTSIZE = BASE_SEARCHFONTSIZE

# taskbar
TASKBARREQ = 0.0
TASKBARTRY = 0
TASKBARROLE = "taskbar"
TASKBARREQUESTED = False
TASKBARCREATED = False
TASKBARCREATETS = 0.0

# buffers
DESKTOPID = None
DESKTOPBUF = None
TASKBARID = None
TASKBARBUF = None
STARTID = None
STARTBUF = None
TOOLTIPID = None
TOOLTIPBUF = None
SEARCHID = None
SEARCHBUF = None

# mapping
GOTWELCOME = False
AWAITMAP = {}
STARTVISIBLE = False
STARTMAPPED = False
STARTWANTED = False
STARTMENUPAINTERROR = ""
TOOLTIPMAPPED = False
SEARCHMAPPED = False
SEARCHINPUTFOCUSED = False

# colours
BRICKBG = (80, 80, 80)
BRICKBG_DOWN = (64, 64, 64)
LOGOBG = (0, 0, 0)
DESKTOPBG = (0, 0, 0)
STARTLEFTBG = (0, 0, 0)
STARTRIGHTBG = (0, 0, 0)

# start menu
BASE_STARTW = 400
BASE_STARTH = 520
BASE_STARTPAD = 12
BASE_STARTLEFTINSET = 6
BASE_STARTLEFTW = 220
BASE_STARTITEMH = 28
STARTW = BASE_STARTW
STARTH = BASE_STARTH
STARTPAD = BASE_STARTPAD
STARTLEFTW = BASE_STARTLEFTW
STARTITEMH = BASE_STARTITEMH
STARTLEFTINSET = BASE_STARTLEFTINSET
STARTPLACEITEMS = []
STARTSOFTITEMS = []
LOGOX = 0
LOGOY = 0
LOGOW = 0
LOGOH = 0
BASE_LOGOGAP = 8
LOGOGAP = BASE_LOGOGAP

# windows
WINDOWITEMS = {}
WINDOWORDER = []
ACTIVEWID = None
BASE_WINDOWBOXSIZE = 48
BASE_WINDOWLOGOSIZE = 24
BASE_WINDOWGAP = 10
WINDOWBOXSIZE = BASE_WINDOWBOXSIZE
WINDOWLOGOSIZE = BASE_WINDOWLOGOSIZE
WINDOWGAP = BASE_WINDOWGAP

# instances
LISTID = None
LISTBUF = None
LISTMAPPED = False
LISTRECT = None
LISTANCHOR = None
LISTHOVERWID = None
LISTITEMRECTS = []
LISTCLOSERECTS = []
LISTGROUP = None
LISTREQUESTED = False
LISTPENDINGGROUP = None
LISTPENDINGANCHOR = None
LISTGRACETS = 0.0
LISTGRACE = 0.9
TASKBARGROUPS = []
TASKBARGROUPITEMS = {}
TASKBARGROUPRECTS = {}

# taskbar search
SEARCHRECT = None
SEARCHPANELRECT = None
SEARCHPENDING = False
SEARCHTEXT = ""
SEARCHCARETPOS = 0
SEARCHRESULTS = []
SEARCHRESULTRECTS = []
SEARCHFILTERRECTS = []
SEARCHOPENARRAYRECT = None
SEARCHFILTERS = set()
SEARCHSELECTED = 0
SEARCHHOVER = None
SEARCHSCROLL = 0
SEARCHVISIBLEMAX = 10
SEARCHMAXRESULTS = 250
SEARCHCARETSTART = time.monotonic()
SEARCHCARETSTATE = None
SEARCHPATHLIMIT = 200
SEARCHHANDOFFLIMIT = 10000
SEARCHPATHRESULTS = []
SEARCHQUERYGENERATION = 0
SEARCHQUERYQUEUE = queue.Queue()
SEARCHEVENTQUEUE = queue.Queue()
SEARCHWORKER = None
SEARCHINDEXING = False
SEARCHCOMPLETE = False
SEARCHHANDOFF = None
SEARCHHANDOFFWAKE = threading.Event()
TASKBARCURSORMODE = "arrow"
SEARCHSETTINGS = (
    ("display", "display", "screen monitor"),
    ("resolution", "display", "screen size"),
    ("ui scale", "display", "interface scaling"),
    ("brightness", "display", "screen light"),
    ("contrast", "display", "screen"),
    ("saturation", "display", "screen colour color"),
    ("night light", "display", "screen temperature colour color"),
    ("audio", "audio", "sound speaker"),
    ("volume", "audio", "sound gain speaker"),
    ("mute", "audio", "sound speaker"),
    ("audio device", "audio", "sound output speaker"),
    ("mouse", "mouse", "pointer cursor"),
    ("cursor speed", "mouse", "pointer"),
    ("cursor size", "mouse", "pointer"),
    ("network", "network", "internet connection"),
    ("wi-fi", "network", "wifi wireless internet"),
    ("ethernet", "network", "wired internet"),
    ("ip address", "network", "internet network address"),
    ("gateway", "network", "internet router"),
    ("dns", "network", "internet nameserver"),
    ("time & date", "time & date", "clock date time"),
    ("time zone", "time & date", "timezone clock"),
    ("internet time", "time & date", "clock sync"),
    ("master", "master", "account profile"),
    ("master name", "master", "account profile name"),
    ("password", "master", "account security"),
    ("master image", "master", "account profile picture"),
    ("about", "about", "system information"),
    ("terminal name", "about", "system hostname"),
    ("hardware", "about", "system graphics ram storage"),
    ("drivers", "about", "system graphics audio network"),
    ("version", "about", "operating system"),
)

# task menu
TASKMENUID = None
TASKMENUBUF = None
TASKMENUMAPPED = False
TASKMENURECT = None
TASKMENUANCHOR = None
TASKMENUGROUP = None
TASKMENUCONTEXT = None
TASKMENUTASKBAR = False
TASKMENUDESKTOP = None
TASKMENUDESKTOPVIEW = False
TASKMENUITEMRECTS = []
TASKMENUPENDINGGROUP = None
TASKMENUPENDINGANCHOR = None
TASKMENUPENDINGCONTEXT = None
TASKMENUPENDINGTASKBAR = False
TASKMENUPENDINGDESKTOP = None
BASE_TASKMENUW = 240
BASE_TASKMENUITEMH = 34
BASE_TASKMENUPAD = 12
BASE_TASKMENUFONTSIZE = 14
BASE_MENUMAXW = 520
TASKMENUW = BASE_TASKMENUW
TASKMENUITEMH = BASE_TASKMENUITEMH
TASKMENUPAD = BASE_TASKMENUPAD
TASKMENUFONTSIZE = BASE_TASKMENUFONTSIZE
MENUMAXW = BASE_MENUMAXW
TASKBARPINSFILE = "/the one/settings/expanse/taskbarpins.json"
TASKBARPINS = []
TASKBARSEEN = []
TASKBARORDERFILE = "/the one/settings/expanse/taskbarorder.json"
TASKBARORDER = []
TASKBARSETTINGSFILE = "/the one/settings/expanse/taskbar.json"
TASKBARSEARCHVISIBLE = True
DRAGTASKGROUP = None
DRAGTASKACTIVE = False
DRAGTASKMOVED = False
DRAGTASKSTARTX = 0
DRAGTASKSTARTY = 0
DRAGTASKX = 0
DRAGTASKY = 0
DRAGTASKOFFSETX = 0
DRAGTASKTHRESH = 6

# desktop tier
DESKTOPROOT = ""
DESKTOPSETTINGSFILE = "/the one/settings/expanse/desktop.json"
DESKTOPSHOW = True
DESKTOPITEMSIZE = "medium"
DESKTOPORDER = []
DESKTOPPOSITIONS = {}
DESKTOPEXPANDED = set()
DESKTOPITEMS = []
DESKTOPITEMRECTS = []
DESKTOPSELECTED = None
DESKTOPHOVER = None
DESKTOPLASTCLICKPATH = None
DESKTOPLASTCLICKAT = 0.0
DESKTOPDOUBLECLICK = 0.45
DESKTOPNEXTSCAN = 0.0
DESKTOPSCANSIGNATURE = None
DESKTOPDRAGPATH = None
DESKTOPDRAGSTART = None
DESKTOPDRAGOFFSET = None
DESKTOPDRAGACTIVE = False
DESKTOPCREATEACTIVE = False
DESKTOPCREATEKIND = None
DESKTOPCREATETEXT = ""
DESKTOPCREATECARETPOS = 0
DESKTOPCREATECELL = None
DESKTOPCREATETARGET = None
DESKTOPCREATESELECTION = None
DESKTOPCREATEERROR = ""
DESKTOPCREATEBUSY = False

# network
NETICONX = 0
NETICONY = 0
NETICONW = 0
NETICONH = 0
BASE_NETICON = 16
BASE_NETICONGAP = 24
NETICONGAP = BASE_NETICONGAP
LASTNETSTATE = None
LASTNETADDR = None
LASTNETGW = None
NET_NEXT_TS = 0.0
NET_INTERVAL = 1.0

# audio
AUDIOICONX = None
AUDIOICONY = None
AUDIOICONW = None
AUDIOICONH = None
AUDIOICONRECT = None
BASE_AUDIOICON = 16
BASE_AUDIOICONGAP = 24
AUDIOICONGAP = BASE_AUDIOICONGAP
AUDIOMAGIC = b'T1AU'
AUDIOPROTO = 1
AUDIOHDRSZ = 12
AUDIOMAXMSG = 1024 * 1024
AUDIO_MSGHELLO = 1
AUDIO_MSGDEVLIST = 10
AUDIO_MSGVOLUME = 30
AUDIO_MSGMUTE = 31
AUDIO_MSGSUBSCRIBE = 40
AUDIO_MSGNOTIFY = 41
AUDIOSRVSOCK = None
AUDIOSRVINBUF = b""
AUDIOSRVOUTBUF = b""
AUDIOSRVCONNECTED = False
AUDIOSRVHELLO = False
AUDIOGOTDEV = False
AUDIOGOTVOL = False
AUDIOSUBREADY = False
CURRENTAUDIOAVAIL = False
CURRENTAUDIOVOL = 0
CURRENTAUDIOMUTE = False
CURRENTAUDIOACTIVE = None
LASTAUDIOAVAIL = None
LASTAUDIOVOL = None
LASTAUDIOMUTE = None
AUDIONEXTCONNECT = 0.0
AUDIOCONNECTINTERVAL = 1.0
AUDIODIRTY = False
AUDIOFORCE = False

# volumebar popup
VOLUMEID = None
VOLUMEBUF = None
VOLUMEMAPPED = False
VOLUMEPENDING = False
VOLUMERECT = None
VOLUMEDRAG = False
VOLUMEDRAGVOL = None
VOLUMEDRAGDIRTY = False
VOLUMELASTFRAME = 0.0
VOLUMEFRAMEINTERVAL = 1.0 / 60.0
VOLUMEAUTOCLOSEAT = 0.0
VOLUMEAUTOCLOSEDELAY = 2.0
VOLUMEWHEELSTEP = 2
BASE_VOLUMEW = 44
BASE_VOLUMEH = 210
BASE_VOLUMETEXT = 12
BASE_VOLUMEPAD = 8
BASE_VOLUMETRACKW = 10
BASE_VOLUMEKNOBW = 22
BASE_VOLUMEKNOBH = 12
BASE_VOLUMEGAP = 8
BASE_VOLUMETOP = 26
BASE_VOLUMEBOT = 16
VOLUMEW = BASE_VOLUMEW
VOLUMEH = BASE_VOLUMEH
VOLUMETEXT = BASE_VOLUMETEXT
VOLUMEPAD = BASE_VOLUMEPAD
VOLUMETRACKW = BASE_VOLUMETRACKW
VOLUMEKNOBW = BASE_VOLUMEKNOBW
VOLUMEKNOBH = BASE_VOLUMEKNOBH
VOLUMEGAP = BASE_VOLUMEGAP
VOLUMETOP = BASE_VOLUMETOP
VOLUMEBOT = BASE_VOLUMEBOT

# hover
HOVERNET = False
HOVERPENDINGNET = False
HOVERPENDINGNETTS = 0.0
HOVERPINGTS = 0.0
HOVERPINGINTERVAL = 0.12
HOVERCLOCK = False
HOVERPENDINGCLOCK = False
HOVERPENDINGCLOCKTS = 0.0
HOVERAUDIO = False
HOVERPENDINGAUDIO = False
HOVERPENDINGAUDIOTS = 0.0
HOVERWID = None
HOVERPENDINGWID = None
HOVERPENDINGTS = 0.0
HOVERRECT = None
HOVERSTART = False
HOVERPENDINGSTART = False
HOVERPENDINGSTARTTS = 0.0
HOVERLOGO = False
HOVERGROUP = None
TASKBARHOVERGROUP = None
HOVERPENDINGGROUP = None
HOVERPENDINGGROUPTS = 0.0
HOVERLISTGROUP = None
HOVERTOOLTIPGROUP = None
HOVERLISTTS = 0.0
HOVERTOOLTIPTS = 0.0
HOVERLISTDELAY = 1.0
HOVERTOOLTIPDELAY = HOVERLISTDELAY * 2
DISABLETASKBARTOOLTIP = True
TASKMENUHOVER = None
HOVERAUDIOLABEL = ""
HOVERAUDIOLABELTS = 0.0
HOVERAUDIODRAWLABEL = ""
HOVERAUDIODRAWRECT = None

# power menu
POWERITEMRECT = None
POWERMENUOPEN = False
POWERMENUITEMS = []

# clock
CLOCK_LAST_T = ""
CLOCK_LAST_D = ""
CLOCK_WMAX = 0
CLOCK_CX = 0
CLOCK_NEXT_TS = 0.0
CLOCKCLEARPAD = 1

# show desktop
BASE_SHOWDESKTOP_W = 8
SHOWDESKTOP_W = BASE_SHOWDESKTOP_W
SHOWDESKTOP_RECT = None

# optional master image
MASTERIMAGEENABLED = False
MASTERIMAGEPATH = ""
MASTERIMAGESTATE = None
MASTERIMAGE_NEXT_TS = 0.0
MASTERIMAGERECT = None

# managed graphics
GRAPHICSCAPS = {}
GRAPHICSSTATES = {}
GRAPHICSSCENES = {}
GRAPHICSSURFACES = {}
GRAPHICSBUILDING = False
GRAPHICSPAINTING = set()
GRAPHICSTOOLTIPDATA = None
GRAPHICSCPUOVERRIDE = str(os.environ.get("T1OS_EXPANSE_GRAPHICS", "")).strip().lower() in ("cpu", "off", "0", "false")



## functions

# misc functions
def log(msg):
    if not DEBUGEXPANSE:
        return

    try:
        os.makedirs(os.path.dirname(LOGFILE), exist_ok=True)
    except Exception:
        pass

    line = formatlog('expanse', msg) + '\n'

    with open(LOGFILE, "a") as f:

        f.write(line)

        f.flush()

        os.fsync(f.fileno())


# managed graphics functions
_CPUFILLBUFFERFILE = fillbufferfile


def graphicsstrictgpu():

    return bool(
        not GRAPHICSCPUOVERRIDE
        and GRAPHICSCAPS.get("accelerated")
        and GRAPHICSCAPS.get("managed_resources")
    )


def fillbufferfile(*args, **kwargs):

    # Once the retained GPU protocol is available, shell painting must never
    # rasterize into the shared CPU buffer.  graphicscapture temporarily
    # replaces this wrapper while it records equivalent GPU commands.
    if graphicsstrictgpu() and not GRAPHICSBUILDING:
        return True

    return _CPUFILLBUFFERFILE(*args, **kwargs)


def graphicsrequired(role):

    if role == "desktop":
        return ("rectangle",)

    if role in ("taskbar", "startmenu"):
        return ("rectangle", "text", "image")

    return ("rectangle", "text")


def graphicsdimensions(role):

    surface = GRAPHICSSURFACES.get(role, {})

    try:
        width = int(surface.get("w", 0))
        height = int(surface.get("h", 0))
    except Exception:
        width = 0
        height = 0

    if width > 0 and height > 0:
        return width, height

    if role == "desktop":
        return int(DESKTOPW), int(DESKTOPH)

    if role == "taskbar":
        return int(DESKTOPW), int(TASKBARH)

    if role == "startmenu":
        return int(STARTW), int(STARTH)

    if role == "search" and SEARCHPANELRECT:
        return int(SEARCHPANELRECT[2]), int(SEARCHPANELRECT[3])

    if role == "volumebar":
        return int(VOLUMEW), int(VOLUMEH)

    if role == "instancelist" and LISTRECT:
        return int(LISTRECT[2]), int(LISTRECT[3])

    if role == "taskmenu" and TASKMENURECT:
        return int(TASKMENURECT[2]), int(TASKMENURECT[3])

    if role == "tooltip" and HOVERRECT:
        return int(HOVERRECT[2]), int(HOVERRECT[3])

    return 0, 0


def graphicswinid(role):

    try:
        wid = int(GRAPHICSSURFACES.get(role, {}).get("winid", 0))

        if wid > 0:
            return wid
    except Exception:
        pass

    values = {
        "desktop": DESKTOPID,
        "taskbar": TASKBARID,
        "startmenu": STARTID,
        "tooltip": TOOLTIPID,
        "instancelist": LISTID,
        "taskmenu": TASKMENUID,
        "volumebar": VOLUMEID,
        "search": SEARCHID,
    }

    try:
        return int(values.get(role, 0) or 0)
    except Exception:
        return 0


def graphicsregister(role, winid, bufferpath, width, height):

    try:

        role = str(role)

        old = GRAPHICSSURFACES.get(role, {})
        oldwid = int(old.get("winid", 0) or 0)

        if oldwid and oldwid != int(winid):
            GRAPHICSSTATES.pop(oldwid, None)

        state = managedstate(cpu=GRAPHICSCPUOVERRIDE)

        managedconfigure(
            state,
            GRAPHICSCAPS,
            required=graphicsrequired(role),
            cpu=GRAPHICSCPUOVERRIDE,
        )

        if role in ("startmenu", "tooltip", "instancelist", "taskmenu", "volumebar"):
            state["need_submit"] = False

        GRAPHICSSTATES[int(winid)] = state
        GRAPHICSSURFACES[role] = {
            "winid": int(winid),
            "buffer": bufferpath,
            "w": max(0, int(width)),
            "h": max(0, int(height)),
        }
        GRAPHICSSCENES.pop(role, None)

        if state.get("available"):
            log(f"managed graphics available role={role} winid={winid}")
        else:
            log(f"managed graphics CPU role={role} reason={state.get('failure', '')}")

        return bool(state.get("available"))

    except Exception as e:

        log(f"graphics register error role={role} {e}")
        return False


def graphicsupdategeometry(role, width, height, bufferpath=None):

    try:

        surface = GRAPHICSSURFACES.setdefault(str(role), {})
        surface["w"] = max(0, int(width))
        surface["h"] = max(0, int(height))

        if bufferpath is not None:
            surface["buffer"] = bufferpath

        wid = int(surface.get("winid", 0) or 0)
        state = GRAPHICSSTATES.get(wid)

        if state is not None and state.get("available"):
            state["need_submit"] = True

    except Exception as e:

        log(f"graphics geometry error role={role} {e}")


def graphicsstatefor(role):

    wid = graphicswinid(role)

    if wid <= 0:
        return None

    return GRAPHICSSTATES.get(wid)


def graphicscolour(colour):

    try:

        if isinstance(colour, int):
            return int(colour) & 0xFFFFFF

        red, green, blue = colour[:3]
        return ((int(red) & 0xFF) << 16) | ((int(green) & 0xFF) << 8) | (int(blue) & 0xFF)

    except Exception:

        return 0


def graphicsclip(role, rect, outer=None):

    try:

        width, height = graphicsdimensions(role)

        x, y, rw, rh = [int(value) for value in rect]
        left = max(0, x)
        top = max(0, y)
        right = min(width, x + rw)
        bottom = min(height, y + rh)

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


def graphicsrect(commands, role, x, y, width, height, colour, clip=None):

    commandclip = graphicsclip(role, clip or [0, 0, *graphicsdimensions(role)])
    clipped = graphicsclip(role, [x, y, width, height], commandclip)

    if commandclip is None or clipped is None:
        return False

    commands.append({
        "kind": "rectangle",
        "rect": clipped,
        "color": graphicscolour(colour),
        "clip": commandclip,
    })

    return True


def graphicsborder(commands, role, x, y, width, height, colour, clip=None):

    try:

        x = int(x)
        y = int(y)
        width = int(width)
        height = int(height)

        if width < 1 or height < 1:
            return

        graphicsrect(commands, role, x, y, width, 1, colour, clip)

        if height > 1:
            graphicsrect(commands, role, x, y + height - 1, width, 1, colour, clip)

        if height > 2:
            graphicsrect(commands, role, x, y + 1, 1, height - 2, colour, clip)

            if width > 1:
                graphicsrect(commands, role, x + width - 1, y + 1, 1, height - 2, colour, clip)

    except Exception:
        pass


def graphicsline(commands, role, x0, y0, x1, y1, colour, clip=None):

    try:

        x0 = int(x0)
        y0 = int(y0)
        x1 = int(x1)
        y1 = int(y1)

        if y0 == y1:
            graphicsrect(commands, role, min(x0, x1), y0, abs(x1 - x0) + 1, 1, colour, clip)
            return

        if x0 == x1:
            graphicsrect(commands, role, x0, min(y0, y1), 1, abs(y1 - y0) + 1, colour, clip)
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

            span = rows.setdefault(y, [x, x])
            span[0] = min(span[0], x)
            span[1] = max(span[1], x)

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
            graphicsrect(commands, role, span[0], rowy, span[1] - span[0] + 1, 1, colour, clip)

    except Exception:
        pass


def graphicstexty(y, size, fontpath=FONTPATH):

    try:

        face = getttfface(fontpath)

        if face is None:
            return int(y)

        face.set_pixel_sizes(0, int(size))
        ascender = int(face.size.ascender >> 6)
        return int(y) + int(size) - ascender

    except Exception:

        return int(y)


def graphicstext(commands, role, x, y, text, colour, size, fontpath=FONTPATH, clip=None):

    try:

        text = str(text)
        size = max(1, int(size))
        fontpath = str(fontpath or FONTPATH)
        commandclip = graphicsclip(role, clip or [0, 0, *graphicsdimensions(role)])

        if not text or commandclip is None:
            return

        clipx, clipy, clipw, cliph = commandclip

        if int(y) + size + 4 <= clipy or int(y) >= clipy + cliph:
            return

        drawx = int(x)
        shown = text

        while shown and drawx < clipx:

            try:
                advance = int(measuretext(shown[0], size, fontpath))
            except Exception:
                advance = max(1, size // 2)

            drawx += max(1, advance)
            shown = shown[1:]

        if not shown or drawx >= clipx + clipw:
            return

        state = graphicsstatefor(role) or {}
        limit = max(1, int(state.get("text_limit", 1024)))
        offset = 0

        while offset < len(shown):

            chunk = shown[offset:offset + limit]

            if not chunk:
                break

            try:
                prefixwidth = int(measuretext(shown[:offset], size, fontpath)) if offset else 0
            except Exception:
                prefixwidth = offset * max(1, size // 2)

            chunkx = drawx + prefixwidth

            if chunkx >= clipx + clipw:
                break

            commands.append({
                "kind": "text",
                "x": max(0, int(chunkx)),
                "y": max(0, int(graphicstexty(y, size, fontpath))),
                "text": chunk,
                "size": size,
                "font": fontpath,
                "color": graphicscolour(colour),
                "clip": commandclip,
            })

            offset += len(chunk)

    except Exception:
        pass


def graphicsimage(commands, role, path, sourcewidth, sourceheight, x, y, width, height, clip=None):

    try:

        sourcewidth = int(sourcewidth)
        sourceheight = int(sourceheight)
        commandclip = graphicsclip(role, clip or [0, 0, *graphicsdimensions(role)])
        destination = graphicsclip(role, [x, y, width, height], commandclip)

        if sourcewidth < 1 or sourceheight < 1 or commandclip is None or destination is None:
            return False

        if not os.path.isabs(str(path)) or not os.path.isfile(str(path)):
            return False

        commands.append({
            "kind": "image",
            "path": str(path),
            "source_width": sourcewidth,
            "source_height": sourceheight,
            "format": "BGRA32",
            "rect": destination,
            "clip": commandclip,
        })

        return True

    except Exception:

        return False


def graphicscapture(role, painter):

    global GRAPHICSBUILDING

    commands = []
    width, height = graphicsdimensions(role)

    if width < 1 or height < 1:
        return commands

    names = (
        "fillbufferfile", "drawttffile", "blitrawscaledintobuffer",
        "initbuffer", "clear", "present", "drawrect", "drawline",
        "drawtextttf", "sendline", "startmenubegin", "startmenucommit",
        "startmenucleanup", "volumebarbegin", "volumebarcommit",
        "volumebarcleanup",
    )
    previous = {name: globals().get(name) for name in names}
    stateprevious = {
        name: globals().get(name)
        for name in ("STARTMAPPED", "STARTVISIBLE", "STARTWANTED", "TOOLTIPMAPPED", "LISTMAPPED", "TASKMENUMAPPED", "VOLUMEMAPPED", "SEARCHMAPPED")
    }
    previousbuilding = GRAPHICSBUILDING

    def capturefill(path, totalwidth, x, y, rw, rh, colour):
        return graphicsrect(commands, role, x, y, rw, rh, colour)

    def capturetextfile(path, totalwidth, totalheight, x, y, text, colour, size):
        return graphicstext(commands, role, x, y, text, colour, size, FONTPATH)

    def captureimage(sourcepath, sourcewidth, sourceheight, destinationpath, destinationwidth, x, y, rw, rh):
        return graphicsimage(commands, role, sourcepath, sourcewidth, sourceheight, x, y, rw, rh)

    def captureclear(colour=0):
        return graphicsrect(commands, role, 0, 0, width, height, colour)

    def capturerect(x, y, rw, rh, colour):
        return graphicsborder(commands, role, x, y, rw, rh, colour)

    def captureline(x0, y0, x1, y1, colour):
        return graphicsline(commands, role, x0, y0, x1, y1, colour)

    def capturetext(x, y, text, colour, size, fontpath=None):
        return graphicstext(commands, role, x, y, text, colour, size, fontpath or FONTPATH)

    globals()["fillbufferfile"] = capturefill
    globals()["drawttffile"] = capturetextfile
    globals()["blitrawscaledintobuffer"] = captureimage
    globals()["initbuffer"] = lambda *args, **kwargs: True
    globals()["clear"] = captureclear
    globals()["present"] = lambda *args, **kwargs: True
    globals()["drawrect"] = capturerect
    globals()["drawline"] = captureline
    globals()["drawtextttf"] = capturetext
    globals()["sendline"] = lambda *args, **kwargs: True

    if role == "startmenu":
        globals()["startmenubegin"] = lambda: (STARTBUF, STARTBUF)
        globals()["startmenucommit"] = lambda *args, **kwargs: True
        globals()["startmenucleanup"] = lambda *args, **kwargs: True

    if role == "volumebar":
        globals()["volumebarbegin"] = lambda: (VOLUMEBUF, VOLUMEBUF)
        globals()["volumebarcommit"] = lambda *args, **kwargs: True
        globals()["volumebarcleanup"] = lambda *args, **kwargs: True

    GRAPHICSBUILDING = True

    try:
        painter()
    finally:

        GRAPHICSBUILDING = previousbuilding

        for name, value in previous.items():

            if value is None:
                globals().pop(name, None)
            else:
                globals()[name] = value

        for name, value in stateprevious.items():
            globals()[name] = value

    return commands


def graphicsbuildinstancelist():

    commands = []
    role = "instancelist"
    width, height = graphicsdimensions(role)

    if width < 1 or height < 1:
        return commands

    graphicsrect(commands, role, 0, 0, width, height, (0, 0, 0))

    group = TASKBARGROUPITEMS.get(LISTGROUP, {})
    rows = []

    for wid in list(group.get("wids", [])):

        item = WINDOWITEMS.get(wid)

        if item:
            current = str(
                item.get("current", "")
                or item.get("title", "")
                or LISTGROUP
            )
            rows.append([current, wid])

    rows.sort(key=lambda row: (row[0] or "").lower())

    linesize = s(14, 7)
    lineheight = TASKMENUITEMH
    leftpad = s(8, 4)

    for index, row in enumerate(rows):

        current, wid = row
        y = index * lineheight
        ty = textbaseliney(y, lineheight, linesize)
        graphicstext(commands, role, leftpad, ty, current, 0xEFEFEF, linesize, FONTPATH)

        if ACTIVEWID is not None and wid == ACTIVEWID:
            graphicsborder(commands, role, 0, y, width, lineheight, (255, 255, 255))
        elif LISTHOVERWID is not None and wid == LISTHOVERWID:
            graphicsborder(commands, role, 0, y, width, lineheight, (96, 96, 96))

        closeinfo = next((entry for entry in LISTCLOSERECTS if len(entry) >= 5 and entry[4] == wid), None)

        if closeinfo:

            cx, cy, closewidth, closeheight, _ = closeinfo
            glyphsize = min(closewidth, closeheight, s(8, 4))
            x1 = cx + (closewidth - glyphsize) // 2
            y1 = cy + (closeheight - glyphsize) // 2
            x2 = x1 + glyphsize - 1
            y2 = y1 + glyphsize - 1
            graphicsline(commands, role, x1, y1, x2, y2, (0xEF, 0xEF, 0xEF))
            graphicsline(commands, role, x1, y2, x2, y1, (0xEF, 0xEF, 0xEF))

    return commands


def graphicsbuildscene(role):

    try:

        if role == "desktop":

            return graphicscapture(role, desktoppaintcontent)

        if role == "taskbar":

            def buildtaskbar():
                taskbarpaintbase()
                taskbarpaintlauncher()
                taskbarpaintsearch()
                taskbarpaintclock()
                taskbarpaintmasterimage()
                taskbarpaintaudio(None, force=True)
                taskbarpaintnetwork(None)
                taskbarpaintwindowicons()
                taskbarpaintshowdesktop()

            return graphicscapture(role, buildtaskbar)

        if role == "startmenu":
            return graphicscapture(role, lambda: paintstartmenu(None))

        if role == "tooltip":

            data = GRAPHICSTOOLTIPDATA

            if data:

                commands = []
                width, height = graphicsdimensions(role)
                graphicsrect(commands, role, 0, 0, width, height, (0, 0, 0))
                graphicstext(
                    commands,
                    role,
                    int(data.get("x", 10)),
                    int(data.get("y", 10)),
                    str(data.get("text", "")),
                    int(data.get("color", HOVERCOLOR)),
                    int(data.get("size", HOVERFONTSIZE)),
                    FONTPATH,
                )
                return commands

            previouslabel = HOVERAUDIODRAWLABEL
            previousrect = HOVERAUDIODRAWRECT

            globals()["HOVERAUDIODRAWLABEL"] = ""
            globals()["HOVERAUDIODRAWRECT"] = None

            try:
                return graphicscapture(role, lambda: taskbarpainttooltips(None))
            finally:
                globals()["HOVERAUDIODRAWLABEL"] = previouslabel
                globals()["HOVERAUDIODRAWRECT"] = previousrect

        if role == "instancelist":
            return graphicsbuildinstancelist()

        if role == "taskmenu":
            return graphicscapture(role, lambda: painttaskmenu(None))

        if role == "search":
            return graphicscapture(role, lambda: paintsearch(None))

        if role == "volumebar":
            return graphicscapture(role, lambda: paintvolumebar(None))

    except Exception as e:

        log(f"managed scene build error role={role} {e}")

    return []


def graphicssend(sock, request):

    try:

        if sock is None:
            return False

        sendline(sock, request)
        return True

    except Exception:

        return False


def graphicscpudamage(sock, role, rect, force=False):

    try:

        # Once the compositor advertises the strict managed GPU contract,
        # never submit a legacy CPU DAMAGE request--including during the
        # interval before a surface's first asynchronous scene commit.  The
        # retained scene submission owns that initial presentation too.
        if graphicsstrictgpu():
            return False

        state = graphicsstatefor(role)

        if not force and state is not None and state.get("active"):
            return False

        wid = graphicswinid(role)

        if sock is None or wid <= 0:
            return False

        sendline(sock, {"op": "DAMAGE", "winid": wid, "rect": [int(value) for value in rect]})
        return True

    except Exception:

        return False


def graphicsfallback(sock, role, reason, clear=True):

    state = graphicsstatefor(role)

    if state is None:
        return False

    manageddisable(state, reason)
    GRAPHICSSCENES.pop(role, None)
    wid = graphicswinid(role)

    log(f"managed graphics disabled role={role} winid={wid} reason={reason}")

    if graphicsstrictgpu():
        # Preserve the last committed GPU scene.  A managed-protocol failure
        # must be visible as a failure, never hidden by CPU raster fallback.
        log(f"strict GPU mode suppressed CPU fallback role={role} winid={wid}")
        return False

    if clear and sock is not None and wid > 0:

        try:
            sendline(sock, {"op": "GRAPHICS_CLEAR", "winid": wid})
        except Exception:
            pass

    width, height = graphicsdimensions(role)

    if not graphicsrestorecpu(sock, role) and width > 0 and height > 0:
        graphicscpudamage(sock, role, [0, 0, width, height], force=True)

    return False


def graphicspump(sock, role):

    if GRAPHICSBUILDING:
        return False

    state = graphicsstatefor(role)

    if state is None:
        return False

    if state.get("_suspended"):
        return False

    wasavailable = bool(state.get("available"))

    if not managedtick(state):

        if wasavailable:
            return graphicsfallback(sock, role, state.get("failure", "managed graphics commit timed out"))

        return False

    if not state.get("available"):
        return False

    if state.get("pending") or not state.get("need_submit"):
        return bool(state.get("active"))

    commands = graphicsbuildscene(role)
    width, height = graphicsdimensions(role)

    if (
        not commands
        or commands[0].get("kind") != "rectangle"
        or commands[0].get("rect") != [0, 0, int(width), int(height)]
    ):
        return graphicsfallback(sock, role, "managed scene does not contain a complete background")

    total = len(commands)

    for otherrole, otherscene in GRAPHICSSCENES.items():

        if otherrole != role:
            total += len(otherscene)

    try:
        totallimit = max(1, int(GRAPHICSCAPS.get("total_command_limit", 8192)))
    except Exception:
        totallimit = 8192

    if total > totallimit:
        return graphicsfallback(sock, role, f"managed total command limit exceeded {total}/{totallimit}")

    beforeavailable = bool(state.get("available"))
    managedsubmit(state, lambda request: graphicssend(sock, request), graphicswinid(role), commands)

    if beforeavailable and not state.get("available"):
        return graphicsfallback(sock, role, state.get("failure", "managed scene submission failed"))

    if state.get("pending"):
        GRAPHICSSCENES[role] = commands

    return bool(state.get("active"))


def graphicspresent(sock, role, dirty=None):

    if GRAPHICSBUILDING or role in GRAPHICSPAINTING:
        return False

    state = graphicsstatefor(role)

    if state is None or not state.get("available"):
        return False

    state["_suspended"] = False

    width, height = graphicsdimensions(role)

    if dirty is None:
        dirty = [0, 0, width, height]

    managedmarkdamage(state, dirty, bounds=(width, height))
    return graphicspump(sock, role)


def graphicsmanagedpaint(sock, role, dirty=None):

    if GRAPHICSBUILDING:
        return False

    state = graphicsstatefor(role)

    if state is None or not state.get("available"):
        # Under an active system-wide GPU contract, do not enter the CPU paint
        # path just because one surface encountered a protocol error.
        return bool(graphicsstrictgpu())

    width, height = graphicsdimensions(role)

    if dirty is None:
        dirty = [0, 0, width, height]

    presented = bool(graphicspresent(sock, role, dirty))

    # A managed scene commit is asynchronous.  While its acknowledgement is
    # pending the GPU path already owns this surface, so falling through to
    # the CPU painter would race the retained scene and violates managed-only
    # presentation.  Treat an accepted pending submission as handled.
    if graphicsstrictgpu() and state.get("available"):
        return bool(
            presented
            or state.get("active")
            or state.get("pending")
            or state.get("need_submit")
        )

    return presented


def graphicsrestorecpu(sock, role):

    if GRAPHICSBUILDING:
        return False

    try:

        if role == "desktop":
            paintdesktop(sock)
            return True

        if role == "taskbar":
            painttaskbar(sock)
            return True

        if role == "startmenu" and STARTMAPPED:
            paintstartmenu(sock)
            return True

        if role == "volumebar" and VOLUMEMAPPED:
            paintvolumebar(sock)
            return True

    except Exception as e:

        log(f"CPU graphics restore error role={role} {e}")

    return False


def graphicssuspend(sock, role):

    state = graphicsstatefor(role)
    wid = graphicswinid(role)
    GRAPHICSSCENES.pop(role, None)

    if state is None or not state.get("available") or wid <= 0:
        return False

    # Retain the last committed scene while resize requests settle.  Clearing
    # here temporarily selected the shared CPU surface and allowed a delayed
    # clear acknowledgement to erase the replacement Start-menu scene.
    state["_suspended"] = True
    state["need_submit"] = False
    return True


def graphicsresponse(sock, msg):

    try:
        wid = int(msg.get("winid", 0))
    except Exception:
        return False

    state = GRAPHICSSTATES.get(wid)

    if state is None:
        return False

    role = next((name for name, surface in GRAPHICSSURFACES.items() if int(surface.get("winid", 0) or 0) == wid), None)

    if role is None:
        return False

    wasmanaged = bool(state.get("available") or state.get("active") or state.get("pending"))
    handled = managedresponse(state, msg)

    if str(msg.get("op", "")) == "GRAPHICS_CLEARED" and state.get("_suspended"):
        state["need_submit"] = False

    if wasmanaged and not state.get("available"):

        GRAPHICSSCENES.pop(role, None)
        log(f"managed graphics response fallback role={role} reason={state.get('failure', '')}")

        if graphicsstrictgpu():
            log(f"strict GPU mode retained last scene role={role} winid={wid}")
            return handled

        try:
            sendline(sock, {"op": "GRAPHICS_CLEAR", "winid": wid})
        except Exception:
            pass

        width, height = graphicsdimensions(role)

        if not graphicsrestorecpu(sock, role):
            graphicscpudamage(sock, role, [0, 0, width, height], force=True)

    return handled


def graphicspumpall(sock):

    for role in list(GRAPHICSSURFACES):

        try:
            graphicspump(sock, role)
        except Exception as e:
            graphicsfallback(sock, role, f"managed graphics pump failed {e}")


def getfbsize():

    try:

        p = os.path.join(STATEBASE_ALT, "fb.size")

        if not os.path.exists(p):
            p = os.path.join(STATEBASE, "fb.size")

        if not os.path.exists(p):
            return

        txt = open(p, "r").read().strip()

        w, h = map(int, txt.split("x"))

        globals()["DESKTOPW"] = w

        globals()["DESKTOPH"] = h

        log(f"fb.size {w}x{h}")

    except Exception as e:

        log(f"fb.size read error {e}")


def readfbsize():

    try:

        p = os.path.join(STATEBASE_ALT, "fb.size")

        if not os.path.exists(p):
            p = os.path.join(STATEBASE, "fb.size")

        if not os.path.exists(p):
            return 0, 0

        txt = open(p, "r").read().strip()

        w, h = map(int, txt.split("x"))

        return int(w), int(h)

    except Exception as e:

        log(f"fb.size read error {e}")

        return 0, 0


def scalefromfb(w, h):

    return displayuiscale(
        w, h, 1.0, BASE_DESKTOPW, BASE_DESKTOPH)


def s(value, minval=1):

    try:

        v = int(round(float(value) * float(SCALE)))

        if v < int(minval):
            v = int(minval)

        return int(v)

    except Exception:
        return int(minval)


def applyscale(preference=None):

    try:

        if preference is None:
            preference = uiscalefactor()
        preference = max(0.5, min(3.0, float(preference)))
        globals()["SCALE"] = max(
            0.5,
            min(3.0, scalefromfb(DESKTOPW, DESKTOPH) * preference),
        )

        globals()["BRICKFONTSIZE"] = s(BASE_BRICKFONTSIZE, 9)

        globals()["CLOCKFONTSIZE"] = s(BASE_CLOCKFONTSIZE, 7)

        globals()["HOVERFONTSIZE"] = s(BASE_HOVERFONTSIZE, 7)

        globals()["STARTTITLESIZE"] = s(BASE_STARTTITLESIZE, 9)

        globals()["STARTITEMSIZE"] = s(BASE_STARTITEMSIZE, 8)

        globals()["TASKBARH"] = s(BASE_TASKBARH, 24)

        globals()["LAUNCHX"] = s(BASE_LAUNCHX, 6)

        globals()["LAUNCHH"] = s(BASE_LAUNCHH, 12)

        globals()["LAUNCHW"] = globals()["TASKBARH"]

        globals()["LEFTPAD"] = s(BASE_LEFTPAD, 5)

        globals()["CLOCKPADX"] = s(BASE_CLOCKPADX, 6)

        globals()["MASTERIMAGE_SIZE"] = s(BASE_MASTERIMAGE_SIZE, 15)

        globals()["SEARCHW"] = s(BASE_SEARCHW, 140)

        globals()["SEARCHH"] = s(BASE_SEARCHH, 17)

        globals()["SEARCHPANELW"] = s(BASE_SEARCHPANELW, 210)

        globals()["SEARCHROWH"] = s(BASE_SEARCHROWH, 18)

        globals()["SEARCHFILTERH"] = s(BASE_SEARCHFILTERH, 12)

        globals()["SEARCHPAD"] = s(BASE_SEARCHPAD, 6)

        globals()["SEARCHFONTSIZE"] = s(BASE_SEARCHFONTSIZE, 7)

        globals()["WINDOWBOXSIZE"] = s(BASE_WINDOWBOXSIZE, 24)

        globals()["WINDOWLOGOSIZE"] = s(BASE_WINDOWLOGOSIZE, 12)

        globals()["WINDOWGAP"] = s(BASE_WINDOWGAP, 5)

        globals()["LOGOGAP"] = s(BASE_LOGOGAP, 4)

        globals()["SHOWDESKTOP_W"] = s(BASE_SHOWDESKTOP_W, 4)

        globals()["STARTW"] = s(BASE_STARTW, 200)

        globals()["STARTH"] = s(BASE_STARTH, 260)

        globals()["STARTPAD"] = s(BASE_STARTPAD, 6)

        globals()["STARTLEFTINSET"] = s(BASE_STARTLEFTINSET, 3)

        globals()["STARTLEFTW"] = s(BASE_STARTLEFTW, 110)

        globals()["STARTITEMH"] = s(BASE_STARTITEMH, 14)

        globals()["TASKMENUW"] = s(BASE_TASKMENUW, 120)

        globals()["TASKMENUITEMH"] = s(BASE_TASKMENUITEMH, 17)

        globals()["TASKMENUPAD"] = s(BASE_TASKMENUPAD, 6)

        globals()["TASKMENUFONTSIZE"] = s(BASE_TASKMENUFONTSIZE, 7)

        globals()["MENUMAXW"] = s(BASE_MENUMAXW, 260)

        globals()["NETICONGAP"] = s(BASE_NETICONGAP, 12)

        globals()["AUDIOICONGAP"] = s(BASE_AUDIOICONGAP, 12)

        globals()["CLOCKCLEARPAD"] = s(4, 2)

        globals()["VOLUMEW"] = s(BASE_VOLUMEW, 22)

        globals()["VOLUMEH"] = s(BASE_VOLUMEH, 105)

        globals()["VOLUMETEXT"] = s(BASE_VOLUMETEXT, 6)

        globals()["VOLUMEPAD"] = s(BASE_VOLUMEPAD, 4)

        globals()["VOLUMETRACKW"] = s(BASE_VOLUMETRACKW, 5)

        globals()["VOLUMEKNOBW"] = s(BASE_VOLUMEKNOBW, 11)

        globals()["VOLUMEKNOBH"] = s(BASE_VOLUMEKNOBH, 6)

        globals()["VOLUMEGAP"] = s(BASE_VOLUMEGAP, 4)

        globals()["VOLUMETOP"] = s(BASE_VOLUMETOP, 13)

        globals()["VOLUMEBOT"] = s(BASE_VOLUMEBOT, 8)

    except Exception as e:

        log(f"applyscale error {e}")


def iconcatalogue():

    global PILIMAGE

    if PILIMAGE is not None:
        return PILIMAGE

    if IMAGECATALOGUE not in sys.path:
        sys.path.insert(0, IMAGECATALOGUE)

    try:
        from PIL import Image as loadedimage
    except Exception as e:
        raise RuntimeError(f"image catalogue unavailable: {e}")

    PILIMAGE = loadedimage
    return PILIMAGE


def iconmasterpaths():

    paths = [
        T1OSLOGOPATH,
        T1OSLOGOMUTEDPATH,
        POWERLOGOPATH,
        POWERLOGOMUTEDPATH,
        NETWORKICONPATH,
        GREYNETWORKICONPATH,
        AUDIOZEROICONPATH,
        AUDIOLOWICONPATH,
        AUDIOMEDICONPATH,
        AUDIOFULLICONPATH,
        AUDIOUNAVAILICONPATH,
    ]

    for icon in SOFTWAREICONS.values():

        path = str(icon.get("path", ""))

        if path:
            paths.append(path)

    return list(dict.fromkeys(paths))


def iconmasterinfo(path):

    path = str(path)
    cached = ICONMASTERINFO.get(path)

    if cached is not None:
        return cached

    if not os.path.isabs(path) or os.path.islink(path):
        raise ValueError("icon source must be an absolute regular file")

    realpath = os.path.realpath(path)
    resourceroot = os.path.realpath(ICONRESOURCEROOT)

    if os.path.commonpath((resourceroot, realpath)) != resourceroot:
        raise ValueError("icon source is outside the Expanse resource tree")

    if not os.path.isfile(realpath):
        raise FileNotFoundError(realpath)

    state = os.stat(realpath)
    identity = (int(state.st_size), int(state.st_mtime_ns))

    imagemodule = iconcatalogue()
    imagemodule.MAX_IMAGE_PIXELS = ICONPIXELLIMIT

    with warnings.catch_warnings():

        warnings.simplefilter("error", imagemodule.DecompressionBombWarning)

        with imagemodule.open(realpath) as image:

            image.load()
            form = str(image.format or "").upper()
            width, height = [int(value) for value in image.size]
            animated = bool(getattr(image, "is_animated", False))

    if form != "PNG":
        raise ValueError("icon source is not a PNG")

    if animated:
        raise ValueError("animated PNG icons are not supported")

    if width < 1 or height < 1 or width * height > ICONPIXELLIMIT:
        raise ValueError("icon source dimensions are invalid")

    if width != height:
        raise ValueError("taskbar icon masters must use a square canvas")

    cached = {
        "path": realpath,
        "width": width,
        "height": height,
        "identity": identity,
    }
    ICONMASTERINFO[path] = cached
    ICONMASTERINFO[realpath] = cached
    return cached


def masterimageinfo(path):

    path = str(path)
    realpath = os.path.realpath(path)

    if not os.path.isabs(path) or not os.path.isfile(realpath):
        raise ValueError("master image must be an absolute regular file")

    state = os.stat(realpath)
    identity = (int(state.st_size), int(state.st_mtime_ns))
    cached = MASTERIMAGEINFO.get(realpath)

    if cached is not None and cached.get("identity") == identity:
        return cached

    imagemodule = iconcatalogue()
    imagemodule.MAX_IMAGE_PIXELS = ICONPIXELLIMIT

    with warnings.catch_warnings():

        warnings.simplefilter("error", imagemodule.DecompressionBombWarning)

        with imagemodule.open(realpath) as image:

            image.seek(0)
            image.load()
            form = str(image.format or "").upper()
            width, height = [int(value) for value in image.size]

    if form not in ("PNG", "JPEG", "WEBP", "BMP", "GIF"):
        raise ValueError("master image format is not supported")

    if width < 1 or height < 1 or width * height > ICONPIXELLIMIT:
        raise ValueError("master image dimensions are invalid")

    cached = {
        "path": realpath,
        "width": width,
        "height": height,
        "identity": identity,
    }
    MASTERIMAGEINFO[realpath] = cached
    MASTERIMAGEINFO[path] = cached
    return cached


def iconcachedir():

    parent = os.path.realpath("/.ephemeral/expanse")
    root = os.path.abspath(ICONCACHEROOT)

    # Expanse is the owner of this private runtime namespace.  A clean boot or
    # isolated diagnostic may legitimately be the first process to create it.
    os.makedirs(parent, mode=0o700, exist_ok=True)

    parentstatus = os.lstat(parent)

    if (
            not stat.S_ISDIR(parentstatus.st_mode) or
            stat.S_ISLNK(parentstatus.st_mode) or
            parentstatus.st_uid != os.geteuid()
    ):
        raise RuntimeError("Expanse runtime directory is unsafe")

    if os.path.lexists(root) and os.path.islink(root):
        raise RuntimeError("icon cache directory cannot be a symbolic link")

    os.makedirs(root, mode=0o711, exist_ok=True)
    realroot = os.path.realpath(root)

    if os.path.commonpath((parent, realroot)) != parent:
        raise RuntimeError("icon cache directory is outside /.ephemeral/expanse")

    rootstatus = os.lstat(realroot)

    if (
            not stat.S_ISDIR(rootstatus.st_mode) or
            stat.S_ISLNK(rootstatus.st_mode) or
            rootstatus.st_uid != os.geteuid()
    ):
        raise RuntimeError("icon cache directory is unsafe")

    # WindowServer consumes these derived, non-confidential public icon
    # surfaces in the managed renderer. Traverse/read permission is required,
    # while the LSM keeps every mutation confined to the Expanse domain.
    os.chmod(realroot, 0o711)

    return realroot


def surfacestagingdir():

    parent = os.path.realpath("/.ephemeral/expanse")
    root = os.path.abspath(SURFACESTAGINGROOT)

    if os.path.lexists(root) and os.path.islink(root):
        raise RuntimeError("surface staging directory cannot be a symbolic link")

    os.makedirs(root, mode=0o700, exist_ok=True)
    realroot = os.path.realpath(root)

    if os.path.commonpath((parent, realroot)) != parent:
        raise RuntimeError("surface staging directory is outside /.ephemeral/expanse")

    status = os.lstat(realroot)

    if (
            not stat.S_ISDIR(status.st_mode) or
            stat.S_ISLNK(status.st_mode) or
            status.st_uid != os.geteuid()
    ):
        raise RuntimeError("surface staging directory is unsafe")

    os.chmod(realroot, 0o700)
    return realroot


def surfacestagingpath(role):

    name = str(role).strip().lower()

    if name not in ("taskbar", "startmenu", "volumebar"):
        raise ValueError("unsupported Expanse staging surface")

    return os.path.join(surfacestagingdir(), f"{name}.raw")


def commitcpusurface(staged, live, expected):

    if graphicsstrictgpu() and not GRAPHICSBUILDING:
        return True

    expected = int(expected)

    if expected < 4:
        raise ValueError("invalid CPU surface size")

    stagedstatus = os.stat(staged, follow_symlinks=False)
    livestatus = os.stat(live, follow_symlinks=False)

    if (
            not stat.S_ISREG(stagedstatus.st_mode) or
            stat.S_ISLNK(stagedstatus.st_mode) or
            stagedstatus.st_uid != os.geteuid() or
            int(stagedstatus.st_size) != expected
    ):
        raise RuntimeError("unsafe staged CPU surface")

    if (
            not stat.S_ISREG(livestatus.st_mode) or
            stat.S_ISLNK(livestatus.st_mode) or
            int(livestatus.st_size) != expected
    ):
        raise RuntimeError("unsafe live CPU surface")

    # BUFBASE is deliberately non-writable to desktop clients. Preserve the
    # server-owned inode and copy through the already-authorized file instead
    # of trying to create or rename a sibling there. Damage is sent only after
    # this complete copy has been synchronized.
    with open(staged, "rb", buffering=0) as source, open(live, "r+b", buffering=0) as destination:
        remaining = expected
        destination.seek(0)

        while remaining:
            block = source.read(min(1024 * 1024, remaining))

            if not block:
                raise RuntimeError("staged CPU surface ended early")

            written = destination.write(block)

            if written != len(block):
                raise RuntimeError("live CPU surface write was incomplete")

            remaining -= written

        destination.flush()
        os.fsync(destination.fileno())


def prepareicon(path, width, height, masterimage=False):

    global ICONCACHEHITS, ICONCACHEMISSES

    try:

        width = int(width)
        height = int(height)

        if width < 1 or height < 1 or width * height > ICONPIXELLIMIT:
            raise ValueError("prepared icon dimensions are invalid")

        info = (
            masterimageinfo(path) if masterimage
            else iconmasterinfo(path))

        if (
            not masterimage and
            (width > int(info["width"]) or height > int(info["height"]))
        ):
            raise ValueError(
                f"icon master {info['width']}x{info['height']} is smaller than target {width}x{height}"
            )

        key = (
            info["path"],
            info["identity"],
            width,
            height,
            bool(masterimage),
            ICONCONVERTERVERSION,
        )
        cached = ICONCACHE.get(key)
        expected = width * height * 4

        # The process-owned cache is mutation-protected by the Expanse LSM
        # domain. Its derived public-icon surfaces remain readable by the
        # root-owned WindowServer managed renderer.
        if cached is not None:
            ICONCACHEHITS += 1
            return cached, width, height

        ICONCACHEMISSES += 1
        imagemodule = iconcatalogue()

        with warnings.catch_warnings():

            warnings.simplefilter("error", imagemodule.DecompressionBombWarning)

            with imagemodule.open(info["path"]) as opened:

                opened.load()
                image = opened.convert("RGBA")

                # Keep the PNG's alpha intact.  Both the retained graphics path
                # and the CPU taskbar blitter composite this surface over the
                # button that has already been painted.
                canvas = imagemodule.new("RGBA", (width, height), (0, 0, 0, 0))
                if masterimage:
                    ratio = min(
                        float(width) / max(1, image.width),
                        float(height) / max(1, image.height))
                    targetwidth = max(
                        1, min(width, int(round(image.width * ratio))))
                    targetheight = max(
                        1, min(height, int(round(image.height * ratio))))
                    if image.size != (targetwidth, targetheight):
                        image = image.resize(
                            (targetwidth, targetheight),
                            imagemodule.Resampling.LANCZOS,
                            reducing_gap=3.0,
                        )
                    canvas.alpha_composite(
                        image,
                        ((width - targetwidth) // 2,
                         (height - targetheight) // 2))
                else:
                    if image.size != (width, height):
                        image = image.resize(
                            (width, height),
                            imagemodule.Resampling.LANCZOS,
                            reducing_gap=3.0,
                        )
                    canvas.alpha_composite(image, (0, 0))
                pixels = canvas.tobytes("raw", "BGRA")

        if len(pixels) != expected:
            raise RuntimeError(f"icon decoder returned {len(pixels)} bytes, expected {expected}")

        digestsource = "\0".join((
            info["path"],
            str(info["identity"][0]),
            str(info["identity"][1]),
            str(width),
            str(height),
            "master" if masterimage else "icon",
            str(ICONCONVERTERVERSION),
        ))
        digest = hashlib.sha256(digestsource.encode("utf-8")).hexdigest()[:20]
        stem = os.path.splitext(os.path.basename(info["path"]))[0]
        output = os.path.join(iconcachedir(), f"{stem}-{width}x{height}-{digest}.bgra")
        temporary = f"{output}.tmp-{time.monotonic_ns()}"

        try:

            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)

            with os.fdopen(descriptor, "wb") as stream:
                stream.write(pixels)
                stream.flush()
                os.fsync(stream.fileno())

            os.replace(temporary, output)
            os.chmod(output, 0o644)

        finally:

            if os.path.exists(temporary):
                os.remove(temporary)

        ICONCACHE[key] = output
        return output, width, height

    except Exception as e:

        failure = (
            str(path), str(width), str(height),
            bool(masterimage), str(e))

        if failure not in ICONCACHEFAILURES:
            ICONCACHEFAILURES.add(failure)
            log(f"icon prepare error path={path} target={width}x{height} error={e}")

        return None, 0, 0


def loadmasterimagesettings(force=False):

    global MASTERIMAGEENABLED, MASTERIMAGEPATH, MASTERIMAGESTATE

    try:
        settingsstate = os.stat(MASTERSETTINGSFILE)
        settingsstamp = (
            int(settingsstate.st_size),
            int(settingsstate.st_mtime_ns))
        with open(MASTERSETTINGSFILE, "r", encoding="utf-8") as stream:
            configured = json.load(stream)
        if not isinstance(configured, dict):
            configured = {}
    except Exception:
        settingsstamp = None
        configured = {}

    rawenabled = configured.get("use_master_image", False)
    enabled = (
        rawenabled if isinstance(rawenabled, bool)
        else str(rawenabled).strip().lower() in ("1", "true", "yes", "on"))
    path = str(configured.get("image_path", "") or "").strip()
    path = os.path.abspath(path) if path else ""

    try:
        sourcestate = os.stat(os.path.realpath(path)) if path else None
        sourcestamp = (
            int(sourcestate.st_size),
            int(sourcestate.st_mtime_ns)) if sourcestate else None
    except Exception:
        sourcestamp = None

    state = (settingsstamp, bool(enabled), path, sourcestamp)

    if not force and state == MASTERIMAGESTATE:
        return False

    oldvisual = (
        bool(MASTERIMAGEENABLED),
        str(MASTERIMAGEPATH),
        MASTERIMAGESTATE[3] if MASTERIMAGESTATE else None)
    MASTERIMAGESTATE = state

    try:
        if not enabled or not path:
            raise ValueError("master image is disabled")
        MASTERIMAGEINFO.pop(path, None)
        MASTERIMAGEINFO.pop(os.path.realpath(path), None)
        masterimageinfo(path)
        active = True
    except Exception as error:
        active = False
        if enabled:
            log(f"master image unavailable path={path} error={error}")

    MASTERIMAGEENABLED = active
    MASTERIMAGEPATH = path
    globals()["MASTERIMAGERECT"] = None
    newvisual = (bool(active), path, sourcestamp)
    return bool(force or oldvisual != newvisual)


def masterimageactive():

    return bool(MASTERIMAGEENABLED and MASTERIMAGEPATH)


def masterimagereservedwidth():

    return MASTERIMAGE_SIZE + CLOCKPADX if masterimageactive() else 0


def taskbarclockx(width):

    return max(
        0,
        DESKTOPW - SHOWDESKTOP_W - int(width) -
        CLOCKPADX - masterimagereservedwidth())


def masterimagesettingstick(sock):

    now = time.monotonic()

    if now < MASTERIMAGE_NEXT_TS:
        return

    globals()["MASTERIMAGE_NEXT_TS"] = now + 0.5

    if loadmasterimagesettings():
        globals()["CLOCK_LAST_T"] = ""
        globals()["CLOCK_LAST_D"] = ""
        globals()["CLOCKRECT"] = None
        globals()["CLOCKRECT_DW"] = 0
        if TASKBARID is not None and TASKBARBUF is not None:
            painttaskbar(sock)


def readmasterrole():
    # Compatibility display metadata only; never an authorization input.
    return "session"


def ensurefont():
    global TTFFACE

    try:

        if TTFFACE is not None:
            return True

        # hard fail if the interface font is not present – no fallback
        if not os.path.exists(FONTPATH):
            log(f"interface font not found at {FONTPATH}")
            return False

        TTFFACE = freetype.Face(FONTPATH)

        return True

    except Exception as e:

        log(f"ensurefont error {e}")

        return False


def initstartitems(username=None):

    try:

        if username is None:
            username = getusername()

        globals()["STARTPLACEITEMS"] = [
            {"label": "root", "path": "/", "rect": None},
            {"label": "software", "path": "/software", "rect": None},
            {"label": f"{username}", "path": f"/master/{username}", "rect": None},
            {"label": "flash", "path": f"/master/{username}/flash", "rect": None},
            {"label": "reference", "path": f"/master/{username}/reference", "rect": None},
            {"label": "downloads", "path": f"/master/{username}/flash/downloads", "rect": None},
            {"label": "images", "path": f"/master/{username}/flash/images", "rect": None},
            {"label": "music", "path": f"/master/{username}/flash/music", "rect": None},
            {"label": "videos", "path": f"/master/{username}/flash/videos", "rect": None},
        ]

        globals()["STARTSOFTITEMS"] = [
            {
                "label": "array",
                "name": "array",
                "path": "/the one/build/array/array.py",
                "role": "",
                "logpath": "",
                "env": {},
                "rect": None
            },
            {
                "label": "brick",
                "name": "brick",
                "path": "/the one/build/brick/brick.py",
                "role": "",
                "logpath": "",
                "env": {"BRICK_WINDOW": "1"},
                "rect": None
            },
            {
                "label": "calculator",
                "name": "calculator",
                "path": "/the one/build/calculator/calculator.py",
                "role": "",
                "logpath": "/the one/logs/calculator.py.log",
                "env": {},
                "rect": None
            },
            {
                "label": "operations centre",
                "name": "operations centre",
                "path": "/the one/build/operations/operationscentre.py",
                "role": "",
                "logpath": "/the one/logs/operationscentre.py.log",
                "env": {},
                "rect": None
            },
            {
                "label": "chromium",
                "name": "chromium",
                "path": "/the one/build/chromium/chromium.py",
                "role": "",
                "logpath": "/the one/logs/chromium.py.log",
                "env": {},
                "rect": None
            },
            {
                "label": "player",
                "name": "player",
                "path": "/the one/build/player/player.py",
                "role": "",
                "logpath": "",
                "env": {},
                "rect": None
            },
            {
                "label": "settings",
                "name": "settings",
                "path": "/the one/build/settings/settings.py",
                "role": "",
                "logpath": "/the one/logs/settings.py.log",
                "env": {},
                "rect": None
            },
            {
                "label": "snap",
                "name": "snap",
                "path": "/the one/build/snap/snap.py",
                "role": "",
                "logpath": "/the one/logs/snap.py.log",
                "env": {},
                "rect": None
            },
            {
                "label": "viewer",
                "name": "viewer",
                "path": "/the one/build/viewer/viewer.py",
                "role": "",
                "logpath": "/the one/logs/viewer.py.log",
                "env": {},
                "rect": None
            },
            {
                "label": "write",
                "name": "write",
                "path": "/the one/build/write/write.py",
                "role": "",
                "logpath": "",
                "env": {},
                "rect": None
            }
        ]

        globals()["POWERMENUITEMS"] = [
            {"label": "log out", "rect": None, "action": "logout"},
            {"label": "shut down", "rect": None, "action": "shutdown"},
            {"label": "restart", "rect": None, "action": "restart"}
        ]

    except Exception as e:

        log(f"initstartitems error {e}")


def reapchildren():

    try:

        while True:

            try:

                # reap any dead child without blocking
                pid, status = os.waitpid(-1, os.WNOHANG)

            except ChildProcessError:

                # no child processes
                break

            except OSError:

                # other waitpid error (e.g. no children)
                break

            # if no more dead children
            if pid == 0:
                break

    except Exception as e:

        # reap children error
        log(f"reapchildren error {e}")


def handlesignal(signum, frame):

    globals()["RUN"] = False


def opensocket():

    try:

        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

        s.connect(SOCKPATH)

        s.setblocking(False)

        SEL.register(s, selectors.EVENT_READ, data={"kind": "server"})

        log("socket connected")

        return s

    except Exception as e:

        log(f"socket error {e}")

        return None


def sendline(sock, obj):

    try:

        # encode compact json line
        data = (json.dumps(obj, separators=(",", ":")) + "\n").encode("utf-8")

        # attempt to fully send even on non-blocking sockets
        sent = 0

        tries = 0

        while sent < len(data):

            try:

                n = sock.send(data[sent:])

                if n is None or n <= 0:

                    tries += 1

                    if tries > 50:
                        raise RuntimeError("send stalled")

                    time.sleep(0.01)

                    continue

                sent += n

                tries = 0

            except BlockingIOError:

                # kernel buffer full; back off briefly and retry
                tries += 1

                if tries > 50:
                    raise

                time.sleep(0.01)

    except Exception as e:

        try:

            op = obj.get('op', '?')

        except Exception:

            op = '?'

        log(f"send error {op} {e}")


def recvlines(sock):

    try:

        if not hasattr(recvlines, "buf"):
            recvlines.buf = b""

        received = 0
        chunks = []

        while received < 256 * 1024:

            try:
                data = sock.recv(min(65536, (256 * 1024) - received))
            except BlockingIOError:
                break

            if not data:
                break

            chunks.append(data)
            received += len(data)

        if chunks:
            recvlines.buf += b"".join(chunks)

        out = []

        while True:

            i = recvlines.buf.find(b"\n")

            if i == -1:
                break

            raw = recvlines.buf[:i]

            recvlines.buf = recvlines.buf[i + 1:]

            try:
                out.append(json.loads(raw.decode("utf-8", errors="replace")))
            except Exception:
                continue

        # Pointer motion is replaceable state. Collapse only consecutive
        # samples so buttons, focus, map/unmap and graphics acknowledgements
        # retain exact stream order.
        filtered = []
        pendingmotion = None

        for message in out:

            if str(message.get("op", "")) == "POINTER_MOTION":
                pendingmotion = message
                continue

            if pendingmotion is not None:
                filtered.append(pendingmotion)
                pendingmotion = None

            filtered.append(message)

        if pendingmotion is not None:
            filtered.append(pendingmotion)

        return filtered

    except BlockingIOError:

        return []

    except Exception as e:

        log(f"recv error {e}")

        return []


def readatreyantime():
    try:

        p = "/the one/settings/time/atreyan.txt"

        with open(p, "r") as f:

            s = f.read().strip()

        if not s:
            return ("", "")

        parts = s.split()

        if len(parts) >= 3:
            t = " ".join(parts[0:2])

            d = parts[2]

            return (t, d)

        if len(parts) == 2:
            return (parts[0], parts[1])

        return (s, "")

    except Exception as e:

        log(f"atreyan time read error {e}")
        return ("", "")


def readatreyanstruct():
    try:

        from reign.reign import currenttime

        return currenttime()

    except Exception:

        return time.localtime()


def ensureclockrect():

    global DESKTOPW, DESKTOPH, TASKBARH, CLOCKPADX, SHOWDESKTOP_W, CLOCKFONTSIZE

    rect = globals().get("CLOCKRECT")

    if rect and len(rect) >= 4:

        try:

            w = int(rect[2])

            x = int(rect[0])

            dw = int(globals().get("CLOCKRECT_DW", 0))

            if w > 0 and dw == DESKTOPW and DESKTOPW > 0 and x >= 0 and x + w <= DESKTOPW:
                return

        except Exception:

            rect = None

    globals()["CLOCKRECT_DW"] = DESKTOPW

    t, d = readatreyantime()

    tsz = CLOCKFONTSIZE

    try:

        tw = measurettffile(t, tsz)

    except Exception:

        tw = 0

    try:

        dw = measurettffile(d, tsz)

    except Exception:

        dw = 0

    wmax = max(tw, dw, 0)

    cx = taskbarclockx(wmax)

    if cx < 0:
        cx = 0

    globals()["CLOCK_WMAX"] = wmax

    globals()["CLOCK_CX"] = cx

    globals()["CLOCKRECT"] = [cx, max(0, DESKTOPH - TASKBARH), max(0, wmax), TASKBARH]


def updateclock(sock):

    try:

        if TASKBARID is None:
            return

        if TASKBARBUF is None:
            return

        # rate-limit updates
        now = time.time()

        if now < CLOCK_NEXT_TS:
            return

        globals()["CLOCK_NEXT_TS"] = now + 1.0

        # read new time/date
        t, d = readatreyantime()

        # if nothing changed and we have a valid width, skip
        if t == CLOCK_LAST_T and d == CLOCK_LAST_D and CLOCK_WMAX > 0:
            return

        if graphicsmanagedpaint(sock, "taskbar", [0, 0, DESKTOPW, TASKBARH]):
            return

        tsz = CLOCKFONTSIZE

        # measure new strings
        tw = measurettffile(t, tsz)

        dw = measurettffile(d, tsz)

        wmax = max(tw, dw, 0)

        # new clock anchor (right aligned)
        cx = taskbarclockx(wmax)

        # compute erase band covering both old + new positions, with padding
        left = min(CLOCK_CX, cx) - CLOCKCLEARPAD

        if left < 0:
            left = 0

        right = max(CLOCK_CX + CLOCK_WMAX, cx + wmax) + CLOCKCLEARPAD

        if right > DESKTOPW:
            right = DESKTOPW

        w = right - left

        # clear only if there is something to clear
        if w > 0 and TASKBARBUF is not None:
            fillbufferfile(
                TASKBARBUF,
                DESKTOPW,
                left,
                0,
                w,
                TASKBARH,
                (0, 0, 0)
            )

        # compute baselines to match initial draw
        b1, b2 = clockbaselines(TASKBARH, tsz)

        ty = b1 - tsz

        dy = b2 - tsz

        # draw new time
        drawttffile(
            TASKBARBUF,
            DESKTOPW,
            TASKBARH,
            cx + (wmax - max(tw, 0)) // 2,
            ty,
            t,
            0xEFEFEF,
            tsz
        )

        # draw new date
        drawttffile(
            TASKBARBUF,
            DESKTOPW,
            TASKBARH,
            cx + (wmax - max(dw, 0)) // 2,
            dy,
            d,
            0xEFEFEF,
            tsz
        )

        # update globals
        globals()["CLOCK_LAST_T"] = t

        globals()["CLOCK_LAST_D"] = d

        globals()["CLOCK_WMAX"] = wmax

        globals()["CLOCK_CX"] = cx

        globals()["CLOCKRECT"] = [cx, max(0, DESKTOPH - TASKBARH), max(0, wmax), TASKBARH]

        try:

            sx = DESKTOPW - SHOWDESKTOP_W
            sy = 0
            sw = SHOWDESKTOP_W
            sh = TASKBARH

            fillbufferfile(
                TASKBARBUF,
                DESKTOPW,
                sx,
                sy,
                sw,
                sh,
                (0, 0, 0)
            )

            # left vertical grey line
            fillbufferfile(
                TASKBARBUF,
                DESKTOPW,
                sx,
                sy,
                1,
                sh,
                (96, 96, 96)
            )

            absx = sx

            absy = DESKTOPH - TASKBARH

            globals()["SHOWDESKTOP_RECT"] = [absx, absy, sw, sh]

            graphicscpudamage(sock, "taskbar", [sx, sy, sw, sh])

        except Exception as e:
            log(f"show desktop paint error {e}")

        # damage the clock band only
        if w > 0 and TASKBARID is not None:
            graphicscpudamage(sock, "taskbar", [left, 0, w, TASKBARH])

        if w > 0:
            graphicspresent(sock, "taskbar", [left, 0, DESKTOPW - left, TASKBARH])

    except Exception as e:

        log(f"updateclock error {e}")


def clockbaselines(recth, size):

    try:

        if not ensurefont():

            mid = recth // 2

            gap = max(2, size // 10)

            asc = size

            lineh = size

            totalh = lineh * 2 + gap

            if totalh > recth:
                totalh = recth

                gap = max(1, recth - 2 * lineh)

            top = (recth - totalh) // 2

            b1 = top + asc

            b2 = top + lineh + gap + asc

            return (b1, b2)

        TTFFACE.set_pixel_sizes(0, size)

        asc = TTFFACE.size.ascender >> 6

        desc = -(TTFFACE.size.descender >> 6)

        lineh = asc + desc

        gap = max(2, size // 10)

        totalh = lineh * 2 + gap

        if totalh > recth:

            spare = recth - (2 * lineh)

            gap = max(1, spare)

            if gap < 1:

                gap = 1

                totalh = 2 * lineh + gap

                if totalh > recth:
                    scale = recth / float(totalh)

                    lineh = max(1, int(lineh * scale))

                    asc = min(asc, lineh)

                    totalh = 2 * lineh + gap

        top = (recth - totalh) // 2

        b1 = top + asc

        b2 = top + lineh + gap + asc

        return (b1, b2)

    except Exception:

        mid = recth // 2

        gap = max(2, size // 10)

        asc = size

        lineh = size

        totalh = lineh * 2 + gap

        if totalh > recth:
            totalh = recth

            gap = max(1, recth - 2 * lineh)

        top = (recth - totalh) // 2

        b1 = top + asc

        b2 = top + lineh + gap + asc

        return (b1, b2)


def sendworkarea(sock):

    try:

        sendline(sock, {"op": "WORKAREA_SET", "taskbarh": int(TASKBARH)})

        log(f"workarea set taskbarh {TASKBARH}")

    except Exception as e:

        log(f"sendworkarea error {e}")


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


# desktop tier functions
def desktopsecurepath(path):

    if not DESKTOPROOT:
        return None

    try:
        root = os.path.abspath(DESKTOPROOT)
        candidate = os.path.abspath(str(path))
        if os.path.commonpath((root, candidate)) != root:
            return None
        return candidate
    except Exception:
        return None


def desktoprelative(path):

    candidate = desktopsecurepath(path)
    if candidate is None:
        return None

    relative = os.path.relpath(candidate, DESKTOPROOT).replace("\\", "/")
    return "" if relative == "." else relative


def desktoppath(relative):

    value = str(relative or "").replace("\\", "/").strip("/")
    return desktopsecurepath(os.path.join(DESKTOPROOT, value))


def desktophidden(path, name):

    if str(name).startswith("."):
        return True

    try:
        os.getxattr(path, "user.hidden", follow_symlinks=False)
        return True
    except (AttributeError, OSError, TypeError):
        return False


def desktopnaturalkey(value):

    return tuple(
        int(part) if part.isdigit() else part
        for part in re.split(r"([0-9]+)", str(value).casefold())
    )


def desktopvisiblechildren(path):

    children = []

    try:
        with os.scandir(path) as entries:
            for entry in entries:
                if desktophidden(entry.path, entry.name):
                    continue
                children.append(entry)
    except OSError:
        return []

    children.sort(key=lambda entry: desktopnaturalkey(entry.name))
    children.sort(key=lambda entry: not entry.is_dir(follow_symlinks=False))
    return children


def desktopwalk(path, depth, output):

    for entry in desktopvisiblechildren(path):
        entrypath = desktopsecurepath(entry.path)
        if entrypath is None:
            continue

        try:
            isdirectory = bool(entry.is_dir(follow_symlinks=False))
            information = entry.stat(follow_symlinks=False)
            stamp = (
                int(getattr(information, "st_mtime_ns", 0)),
                int(getattr(information, "st_size", 0)),
                int(getattr(information, "st_mode", 0)),
            )
        except OSError:
            isdirectory = False
            stamp = (0, 0, 0)

        children = desktopvisiblechildren(entrypath) if isdirectory else []
        expanded = bool(isdirectory and entrypath in DESKTOPEXPANDED)
        output.append({
            "name": str(entry.name),
            "path": entrypath,
            "isdir": isdirectory,
            "haskids": bool(children),
            "expanded": expanded,
            "depth": int(depth),
            "stamp": stamp,
        })

        if expanded:
            desktopwalk(entrypath, depth + 1, output)


def desktopsortroots(items):

    roots = []
    children = {}

    for item in items:
        if int(item.get("depth", 0)) == 0:
            roots.append(item)
            children[item["path"]] = []
            current = item["path"]
        elif roots:
            children[current].append(item)

    order = {name: index for index, name in enumerate(DESKTOPORDER)}
    roots.sort(key=lambda item: (
        order.get(str(item.get("name", "")), len(order)),
        desktopnaturalkey(item.get("name", "")),
    ))

    flattened = []
    for root in roots:
        flattened.append(root)
        flattened.extend(children.get(root["path"], []))
    return flattened


def desktopbuildtree():

    items = []

    if DESKTOPROOT and os.path.isdir(DESKTOPROOT):
        desktopwalk(DESKTOPROOT, 0, items)

    return desktopsortroots(items)


def desktopmetrics():

    modes = {
        "small": (190, 30, 12, 7, 16),
        "medium": (250, 38, 14, 9, 19),
        "large": (320, 48, 18, 11, 24),
    }
    width, height, fontsize, padding, indent = modes.get(
        DESKTOPITEMSIZE, modes["medium"])
    return {
        "width": s(width, 120),
        "height": s(height, 22),
        "font": s(fontsize, 9),
        "padding": s(padding, 4),
        "indent": s(indent, 11),
        "gap": s(8, 4),
        "margin": s(12, 6),
    }


def desktopblocks():

    blocks = []
    for item in DESKTOPITEMS:
        if int(item.get("depth", 0)) == 0:
            blocks.append([item])
        elif blocks:
            blocks[-1].append(item)
    return blocks


def desktopgrid(metrics=None):

    metrics = metrics or desktopmetrics()
    availableheight = max(
        1, int(DESKTOPH - TASKBARH - metrics["margin"] * 2))
    availablewidth = max(1, int(DESKTOPW - metrics["margin"] * 2))
    return (
        max(1, availablewidth // int(metrics["width"])),
        max(1, availableheight // int(metrics["height"])),
    )


def desktopblockcells(column, row, count, rows):

    cells = []
    for offset in range(max(1, int(count))):
        linearrow = int(row) + offset
        cells.append((int(column) + linearrow // rows, linearrow % rows))
    return cells


def desktopfindcell(desired, count, columns, rows, occupied):

    column = max(0, min(int(desired[0]), columns - 1))
    row = max(0, min(int(desired[1]), rows - 1))
    candidates = [
        (candidatecolumn, candidaterow)
        for candidatecolumn in range(columns)
        for candidaterow in range(rows)
    ]
    candidates.sort(key=lambda cell: (
        abs(cell[0] - column) + abs(cell[1] - row),
        cell[0],
        cell[1],
    ))

    for candidate in candidates:
        cells = desktopblockcells(candidate[0], candidate[1], count, rows)
        if all(cell[0] < columns and cell not in occupied for cell in cells):
            return candidate, cells

    cells = desktopblockcells(column, row, count, rows)
    return (column, row), cells


def desktoplayout():

    global DESKTOPITEMRECTS

    DESKTOPITEMRECTS = []
    if not DESKTOPSHOW:
        return DESKTOPITEMRECTS

    metrics = desktopmetrics()
    columns, rows = desktopgrid(metrics)
    occupied = set()
    automaticindex = 0

    for block in desktopblocks():
        root = block[0]
        name = str(root.get("name", ""))
        desired = DESKTOPPOSITIONS.get(name)
        if not (
            isinstance(desired, (list, tuple))
            and len(desired) == 2
            and all(type(value) is int and value >= 0 for value in desired)
        ):
            desired = [automaticindex // rows, automaticindex % rows]

        placement, cells = desktopfindcell(
            desired, len(block), columns, rows, occupied)
        if name not in DESKTOPPOSITIONS:
            DESKTOPPOSITIONS[name] = [placement[0], placement[1]]
        occupied.update(cells)
        automaticindex += len(block)

        for item, (column, row) in zip(block, cells):
            x = metrics["margin"] + column * metrics["width"]
            y = metrics["margin"] + row * metrics["height"]
            if x >= DESKTOPW or y >= DESKTOPH - TASKBARH:
                continue

            width = max(1, metrics["width"] - metrics["gap"])
            width = min(width, max(1, DESKTOPW - x))
            arrowx = (
                x + metrics["padding"]
                + int(item.get("depth", 0)) * metrics["indent"]
            )
            record = dict(item)
            record.update({
                "grid": [column, row],
                "rootpath": root.get("path"),
                "rect": [x, y, width, metrics["height"]],
                "arrowrect": [arrowx, y, metrics["indent"], metrics["height"]],
            })
            DESKTOPITEMRECTS.append(record)

    return DESKTOPITEMRECTS


def desktopitemat(x, y):

    for item in reversed(DESKTOPITEMRECTS):
        rx, ry, rw, rh = item["rect"]
        if rx <= x < rx + rw and ry <= y < ry + rh:
            return item
    return None


def desktoptoplevelitem(path):

    target = desktopsecurepath(path)
    if target is None:
        return None

    for item in DESKTOPITEMS:
        if int(item.get("depth", 0)) != 0:
            continue
        root = item.get("path")
        try:
            if os.path.commonpath((root, target)) == root:
                return item
        except Exception:
            continue
    return None


def desktopgridcell(x, y, offset=None):

    metrics = desktopmetrics()
    columns, rows = desktopgrid(metrics)
    offsetx, offsety = offset if offset is not None else (0, 0)
    cellx = float(x) - float(offsetx) - metrics["margin"]
    celly = float(y) - float(offsety) - metrics["margin"]
    column = int(round(cellx / max(1, metrics["width"])))
    row = int(round(celly / max(1, metrics["height"])))
    return [
        max(0, min(column, columns - 1)),
        max(0, min(row, rows - 1)),
    ]


def desktopnextfreecell():

    metrics = desktopmetrics()
    columns, rows = desktopgrid(metrics)
    occupied = {
        tuple(item.get("grid", ()))
        for item in desktoplayout()
        if len(item.get("grid", ())) == 2
    }
    for column in range(columns):
        for row in range(rows):
            if (column, row) not in occupied:
                return [column, row]
    return [max(0, columns - 1), max(0, rows - 1)]


def desktopcreationrect():

    if not DESKTOPCREATEACTIVE:
        return None
    if DESKTOPCREATETARGET is not None:
        target = desktopsecurepath(DESKTOPCREATETARGET)
        record = next((
            item for item in desktoplayout()
            if item.get("path") == target
        ), None)
        return list(record.get("rect")) if record is not None else None
    if not isinstance(DESKTOPCREATECELL, list):
        return None
    metrics = desktopmetrics()
    column, row = DESKTOPCREATECELL
    x = metrics["margin"] + int(column) * metrics["width"]
    y = metrics["margin"] + int(row) * metrics["height"]
    if x >= DESKTOPW or y >= DESKTOPH - TASKBARH:
        return None
    return [
        x,
        y,
        min(max(1, metrics["width"] - metrics["gap"]), max(1, DESKTOPW - x)),
        metrics["height"],
    ]


def desktopcancelcreate(sock=None):

    globals()["DESKTOPCREATEACTIVE"] = False
    globals()["DESKTOPCREATEKIND"] = None
    globals()["DESKTOPCREATETEXT"] = ""
    globals()["DESKTOPCREATECARETPOS"] = 0
    globals()["DESKTOPCREATECELL"] = None
    globals()["DESKTOPCREATETARGET"] = None
    globals()["DESKTOPCREATESELECTION"] = None
    globals()["DESKTOPCREATEERROR"] = ""
    globals()["DESKTOPCREATEBUSY"] = False
    if sock is not None and DESKTOPBUF is not None:
        paintdesktop(sock)


def desktopstartcreate(sock, kind):

    kind = str(kind or "").strip().lower()
    if kind not in ("file", "tier") or not DESKTOPROOT:
        return False
    globals()["DESKTOPCREATEACTIVE"] = True
    globals()["DESKTOPCREATEKIND"] = kind
    globals()["DESKTOPCREATETEXT"] = ""
    globals()["DESKTOPCREATECARETPOS"] = 0
    globals()["DESKTOPCREATECELL"] = desktopnextfreecell()
    globals()["DESKTOPCREATETARGET"] = None
    globals()["DESKTOPCREATESELECTION"] = None
    globals()["DESKTOPCREATEERROR"] = ""
    globals()["DESKTOPCREATEBUSY"] = False
    globals()["DESKTOPSELECTED"] = None
    if sock is not None and DESKTOPID is not None:
        sendline(sock, {"op": "FOCUS_SET", "winid": DESKTOPID})
    if sock is not None and DESKTOPBUF is not None:
        paintdesktop(sock)
    return True


def desktopstartrename(sock, path):

    target = desktopsecurepath(path)
    if target is None or not os.path.lexists(target) or os.path.islink(target):
        return False
    record = next((
        item for item in desktoplayout()
        if item.get("path") == target
    ), None)
    if record is None:
        return False
    name = os.path.basename(target)
    if os.path.isdir(target):
        selectionend = len(name)
        kind = "tier"
    else:
        stem, extension = os.path.splitext(name)
        selectionend = len(stem) if stem and extension else len(name)
        kind = "file"
    globals()["DESKTOPCREATEACTIVE"] = True
    globals()["DESKTOPCREATEKIND"] = kind
    globals()["DESKTOPCREATETEXT"] = name
    globals()["DESKTOPCREATECARETPOS"] = selectionend
    globals()["DESKTOPCREATECELL"] = list(record.get("grid", [0, 0]))
    globals()["DESKTOPCREATETARGET"] = target
    globals()["DESKTOPCREATESELECTION"] = [0, selectionend]
    globals()["DESKTOPCREATEERROR"] = ""
    globals()["DESKTOPCREATEBUSY"] = False
    globals()["DESKTOPSELECTED"] = target
    if sock is not None and DESKTOPID is not None:
        sendline(sock, {"op": "FOCUS_SET", "winid": DESKTOPID})
    if sock is not None and DESKTOPBUF is not None:
        paintdesktop(sock)
    return True


def desktopeditselection():

    selection = DESKTOPCREATESELECTION
    if not isinstance(selection, (list, tuple)) or len(selection) != 2:
        return None
    start = max(0, min(int(selection[0]), len(DESKTOPCREATETEXT)))
    end = max(0, min(int(selection[1]), len(DESKTOPCREATETEXT)))
    if start == end:
        return None
    return (min(start, end), max(start, end))


def desktopdeletemarkedtext():

    selection = desktopeditselection()
    if selection is None:
        return False
    start, end = selection
    globals()["DESKTOPCREATETEXT"] = (
        DESKTOPCREATETEXT[:start] + DESKTOPCREATETEXT[end:]
    )
    globals()["DESKTOPCREATECARETPOS"] = start
    globals()["DESKTOPCREATESELECTION"] = None
    return True


def desktopcommitcreate(sock=None):

    if not DESKTOPCREATEACTIVE or DESKTOPCREATEBUSY:
        return False
    name = str(DESKTOPCREATETEXT).strip()
    if not name:
        globals()["DESKTOPCREATEERROR"] = "enter a name"
        if sock is not None and DESKTOPBUF is not None:
            paintdesktop(sock)
        return False

    globals()["DESKTOPCREATEBUSY"] = True
    renaming = DESKTOPCREATETARGET is not None
    globals()["DESKTOPCREATEERROR"] = "renaming" if renaming else "creating"
    if sock is not None and DESKTOPBUF is not None:
        paintdesktop(sock)
    try:
        oldpath = desktopsecurepath(DESKTOPCREATETARGET) if renaming else None
        response = (
            renamedesktopitem(desktoprelative(oldpath), name)
            if renaming else createdesktopitem(DESKTOPCREATEKIND, name)
        )
        path = desktopsecurepath(response.get("path"))
        expectedparent = (
            os.path.dirname(oldpath) if renaming else os.path.abspath(DESKTOPROOT)
        )
        if path is None or os.path.dirname(path) != expectedparent:
            raise OperationsRequestError(
                "rename returned an invalid path" if renaming
                else "creation returned an invalid path"
            )
        cell = list(DESKTOPCREATECELL or desktopnextfreecell())
        if renaming:
            oldname = os.path.basename(oldpath)
            newname = os.path.basename(path)
            if os.path.dirname(oldpath) == os.path.abspath(DESKTOPROOT):
                DESKTOPPOSITIONS.pop(oldname, None)
                DESKTOPPOSITIONS[newname] = cell
                globals()["DESKTOPORDER"] = [
                    newname if item == oldname else item
                    for item in DESKTOPORDER
                ]
            globals()["DESKTOPEXPANDED"] = {
                path + expanded[len(oldpath):]
                if expanded == oldpath or expanded.startswith(oldpath + os.sep)
                else expanded
                for expanded in DESKTOPEXPANDED
            }
        else:
            DESKTOPPOSITIONS[os.path.basename(path)] = cell
        desktopcancelcreate(None)
        globals()["DESKTOPSELECTED"] = path
        savedesktopsettings()
        desktoprefresh(sock, force=True)
        return True
    except Exception as error:
        message = " ".join(str(error).strip().lower().replace(":", " ").split())
        globals()["DESKTOPCREATEBUSY"] = False
        globals()["DESKTOPCREATEERROR"] = message or (
            "rename failed" if renaming else "creation failed")
        if sock is not None and DESKTOPBUF is not None:
            paintdesktop(sock)
        return False


def desktopmoveitem(sock, sourcepath, x, y, offset=None):

    source = desktoptoplevelitem(sourcepath)
    if source is None:
        return False

    sourcerecord = next((
        item for item in DESKTOPITEMRECTS
        if int(item.get("depth", 0)) == 0
        and item.get("path") == source.get("path")
    ), None)
    if sourcerecord is None:
        return False

    source_name = str(source.get("name", ""))
    oldcell = list(sourcerecord.get("grid", [0, 0]))
    newcell = desktopgridcell(x, y, offset=offset)
    if newcell == oldcell:
        return False

    displaced = next((
        item for item in DESKTOPITEMRECTS
        if item.get("rootpath") != source.get("path")
        and list(item.get("grid", [])) == newcell
    ), None)
    if displaced is not None:
        target = desktoptoplevelitem(displaced.get("rootpath"))
        if target is not None:
            DESKTOPPOSITIONS[str(target.get("name", ""))] = oldcell

    DESKTOPPOSITIONS[source_name] = newcell
    savedesktopsettings()
    desktoplayout()
    if sock is not None and DESKTOPID is not None and DESKTOPBUF is not None:
        paintdesktop(sock)
    return True


def desktoparrowat(item, x, y):

    if not item or not item.get("isdir"):
        return False

    rx, ry, rw, rh = item.get("arrowrect", [0, 0, 0, 0])
    return rx <= x < rx + rw and ry <= y < ry + rh


def desktopscanstate(items):

    return tuple(
        (
            desktoprelative(item.get("path")),
            bool(item.get("isdir")),
            bool(item.get("haskids")),
            bool(item.get("expanded")),
            int(item.get("depth", 0)),
            tuple(item.get("stamp", ())),
        )
        for item in items
    )


def desktoprefresh(sock=None, force=False):

    global DESKTOPITEMS, DESKTOPSCANSIGNATURE, DESKTOPNEXTSCAN, DESKTOPSELECTED

    now = time.monotonic()
    if not force and now < DESKTOPNEXTSCAN:
        return False

    DESKTOPNEXTSCAN = now + 1.0
    items = desktopbuildtree()
    signature = desktopscanstate(items)
    changed = bool(force or signature != DESKTOPSCANSIGNATURE)

    if changed:
        DESKTOPITEMS = items
        DESKTOPSCANSIGNATURE = signature
        visiblepaths = {item["path"] for item in items}
        if DESKTOPSELECTED not in visiblepaths:
            DESKTOPSELECTED = None
        desktoplayout()
        if sock is not None and DESKTOPID is not None and DESKTOPBUF is not None:
            paintdesktop(sock)

    return changed


def loaddesktopsettings():

    global DESKTOPSHOW, DESKTOPITEMSIZE, DESKTOPORDER, DESKTOPPOSITIONS, DESKTOPEXPANDED

    DESKTOPSHOW = True
    DESKTOPITEMSIZE = "medium"
    DESKTOPORDER = []
    DESKTOPPOSITIONS = {}
    DESKTOPEXPANDED = set()

    try:
        with open(DESKTOPSETTINGSFILE, "r") as stream:
            data = json.load(stream)
    except FileNotFoundError:
        return
    except Exception as error:
        log(f"load desktop settings error {error}")
        return

    if not isinstance(data, dict):
        return
    if isinstance(data.get("show"), bool):
        DESKTOPSHOW = bool(data["show"])
    if data.get("size") in ("large", "medium", "small"):
        DESKTOPITEMSIZE = str(data["size"])
    if isinstance(data.get("order"), list):
        DESKTOPORDER = [
            str(name) for name in data["order"]
            if isinstance(name, str) and name and "/" not in name and "\\" not in name
        ]
    if isinstance(data.get("positions"), dict):
        for name, position in data["positions"].items():
            if (
                isinstance(name, str)
                and name
                and "/" not in name
                and "\\" not in name
                and isinstance(position, list)
                and len(position) == 2
                and all(type(value) is int and value >= 0 for value in position)
            ):
                DESKTOPPOSITIONS[name] = list(position)
    if isinstance(data.get("expanded"), list):
        for relative in data["expanded"]:
            if not isinstance(relative, str):
                continue
            path = desktoppath(relative)
            if path is not None and path != DESKTOPROOT:
                DESKTOPEXPANDED.add(path)


def savedesktopsettings():

    temporary = ""

    try:
        directory = os.path.dirname(DESKTOPSETTINGSFILE)
        os.makedirs(directory, exist_ok=True)
        temporary = f"{DESKTOPSETTINGSFILE}.{os.getpid()}.temporary"
        expanded = sorted(
            relative for relative in (
                desktoprelative(path) for path in DESKTOPEXPANDED
            )
            if relative
        )
        data = {
            "show": bool(DESKTOPSHOW),
            "size": str(DESKTOPITEMSIZE),
            "order": list(DESKTOPORDER),
            "positions": {
                str(name): list(position)
                for name, position in DESKTOPPOSITIONS.items()
                if (
                    isinstance(name, str)
                    and name
                    and isinstance(position, (list, tuple))
                    and len(position) == 2
                    and all(type(value) is int and value >= 0 for value in position)
                )
            },
            "expanded": expanded,
        }
        with open(temporary, "w") as stream:
            json.dump(data, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, DESKTOPSETTINGSFILE)
    except Exception as error:
        log(f"save desktop settings error {error}")
        try:
            if temporary and os.path.exists(temporary):
                os.remove(temporary)
        except Exception:
            pass


def initdesktop(username):

    global DESKTOPROOT

    DESKTOPROOT = os.path.abspath(f"/master/{username}/expanse")
    try:
        os.makedirs(DESKTOPROOT, exist_ok=True)
    except OSError as error:
        log(f"create desktop tier error {error}")
    loaddesktopsettings()
    desktoprefresh(force=True)


# taskbar functions
def taskbarbegin():

    global TASKBARBUF

    if TASKBARBUF is None or fillbufferfile is None:
        return None, None

    realbuf = TASKBARBUF

    tmpbuf = surfacestagingpath("taskbar")

    # prepare temp buffer file so we never paint directly into the live buffer
    try:

        if os.path.exists(realbuf):

            try:

                shutil.copyfile(realbuf, tmpbuf)

            except Exception:

                with open(realbuf, "rb") as rf:

                    data = rf.read()

                with open(tmpbuf, "wb") as wf:

                    wf.write(data)

        else:

            with open(tmpbuf, "wb") as f:

                f.truncate(DESKTOPW * TASKBARH * 4)

    except Exception as e:

        log(f"taskbar tmp prepare error {e}")

        return None, None

    # redirect all taskbar painting to the temp buffer
    globals()["TASKBARBUF"] = tmpbuf

    return realbuf, tmpbuf


def taskbarpaintbase():

    try:

        # clear whole taskbar
        fillbufferfile(
            TASKBARBUF,
            DESKTOPW,
            0,
            0,
            DESKTOPW,
            TASKBARH,
            (0, 0, 0)
        )

        # invalidate cached network state so icon is redrawn after a full repaint
        globals()["LASTNETSTATE"] = None

        globals()["LASTNETADDR"] = None

        globals()["LASTNETGW"] = None

    except Exception as e:

        log(f"taskbar base paint error {e}")


def taskbarpaintlauncher():

    try:

        logo_target_h = int(TASKBARH * 0.55)

        # Icon masters use a square canvas; layout is independent of source pixels.
        logo_h = max(1, logo_target_h)
        logo_w = logo_h

        # launcher box padding around logo
        pad = max(3, int(TASKBARH * 0.13))

        box_w = logo_w + pad * 2

        box_h = logo_h + pad * 2

        box_x = LEFTPAD

        box_y = (TASKBARH - box_h) // 2

        # paint launcher background
        fillbufferfile(
            TASKBARBUF,
            DESKTOPW,
            box_x,
            box_y,
            box_w,
            box_h,
            (0, 0, 0)
        )

        # cache launcher geometry (box) so later code can place window buttons
        globals()["LAUNCHX"] = box_x

        globals()["LAUNCHY"] = box_y

        globals()["LAUNCHW"] = box_w

        globals()["LAUNCHH"] = box_h

        # choose draw asset (hover changes visual only, not geometry)
        if HOVERLOGO:

            usepath = T1OSLOGOMUTEDPATH

        else:

            usepath = T1OSLOGOPATH

        cachedpath, sw, sh = prepareicon(usepath, logo_w, logo_h)
        out_w = logo_w
        out_h = logo_h
        logo_x = box_x + (box_w - out_w) // 2
        logo_y = box_y + (box_h - out_h) // 2

        if sw > 0 and sh > 0 and cachedpath is not None:

            blitrawscaledintobuffer(
                cachedpath,
                sw,
                sh,
                TASKBARBUF,
                DESKTOPW,
                logo_x,
                logo_y,
                out_w,
                out_h
            )

        try:

            globals()["LOGOX"] = logo_x

            globals()["LOGOY"] = logo_y

            globals()["LOGOW"] = out_w

            globals()["LOGOH"] = out_h

        except Exception as e:

            log(f"logo geom store error {e}")

    except Exception as e:

        log(f"taskbar launcher paint error {e}")


def searchfittext(text, width, size):

    value = str(text or "")

    try:

        while value and measurettffile(value, size) > int(width):
            value = value[1:]

    except Exception:
        pass

    return value


def searchresultfittext(text, width, size):

    value = str(text or "")

    try:
        if measurettffile(value, size) <= int(width):
            return value
        suffix = "…"
        while value and measurettffile(value + suffix, size) > int(width):
            value = value[:-1]
        return value + suffix
    except Exception:
        return value


def resetsearchcaret():

    globals()["SEARCHCARETSTART"] = time.monotonic()
    globals()["SEARCHCARETSTATE"] = True
    state = graphicsstatefor("taskbar")
    if state is not None and state.get("available"):
        state["need_submit"] = True


def searchcaretvisible():

    elapsed = max(0.0, time.monotonic() - float(SEARCHCARETSTART))
    return int(elapsed / 0.5) % 2 == 0


def updatesearchcaret(sock):

    global SEARCHCARETSTATE

    if not SEARCHINPUTFOCUSED:
        SEARCHCARETSTATE = None
        return

    visible = searchcaretvisible()
    if visible == SEARCHCARETSTATE:
        return

    SEARCHCARETSTATE = visible
    if TASKBARBUF is not None:
        state = graphicsstatefor("taskbar")
        if state is not None and state.get("available"):
            state["need_submit"] = True
        painttaskbar(sock)


def taskbarpaintsearch():

    try:

        if not TASKBARSEARCHVISIBLE:
            globals()["SEARCHRECT"] = None
            return

        gap = int(WINDOWGAP)
        boxx = int(LAUNCHX + LAUNCHW + gap)
        boxw = min(int(SEARCHW), max(1, int(DESKTOPW - boxx - gap)))
        boxh = min(int(SEARCHH), int(TASKBARH))
        boxy = int((TASKBARH - boxh) // 2)
        border = max(1, s(1, 1))

        # Array's dark field treatment: black fill with its divider colour.
        fillbufferfile(TASKBARBUF, DESKTOPW, boxx, boxy, boxw, boxh, (58, 58, 58))
        if boxw > border * 2 and boxh > border * 2:
            fillbufferfile(
                TASKBARBUF,
                DESKTOPW,
                boxx + border,
                boxy + border,
                boxw - border * 2,
                boxh - border * 2,
                (0, 0, 0),
            )

        text = SEARCHTEXT if SEARCHTEXT else ("" if SEARCHINPUTFOCUSED else "search")
        avail = max(1, boxw - (SEARCHPAD * 2))
        shown = searchfittext(text, avail, SEARCHFONTSIZE)
        tx = boxx + SEARCHPAD
        ty = textbaseliney(boxy, boxh, SEARCHFONTSIZE)
        drawttffile(
            TASKBARBUF,
            DESKTOPW,
            TASKBARH,
            tx,
            ty,
            shown,
            0xEFEFEF,
            SEARCHFONTSIZE,
        )

        if SEARCHINPUTFOCUSED and searchcaretvisible():
            visible_start = max(0, len(SEARCHTEXT) - len(shown))
            visible_caret = max(visible_start, min(len(SEARCHTEXT), SEARCHCARETPOS))
            prefix = SEARCHTEXT[visible_start:visible_caret]
            caret_x = tx + measurettffile(prefix, SEARCHFONTSIZE)
            caret_x = min(boxx + boxw - SEARCHPAD, max(tx, caret_x))
            fillbufferfile(
                TASKBARBUF,
                DESKTOPW,
                caret_x,
                boxy + max(3, SEARCHPAD // 2),
                1,
                max(1, boxh - max(6, SEARCHPAD)),
                (239, 239, 239),
            )

        globals()["SEARCHRECT"] = [
            boxx,
            DESKTOPH - TASKBARH + boxy,
            boxw,
            boxh,
        ]

    except Exception as e:

        log(f"taskbar search paint error {e}")


def taskbarend(realbuf, tmpbuf, committed):

    # always restore live buffer path, even on early error
    globals()["TASKBARBUF"] = realbuf

    # if commit never happened, tmp may still exist
    try:

        if os.path.exists(tmpbuf):

            os.remove(tmpbuf)

    except Exception as e:

        log(f"taskbar tmp cleanup error {e}")


def taskbarpainttooltips(sock):

    global TOOLTIPMAPPED, CLOCKRECT, HOVERAUDIOLABEL, HOVERAUDIOLABELTS, HOVERAUDIODRAWLABEL, HOVERAUDIODRAWRECT, GRAPHICSTOOLTIPDATA


    try:

        # start tooltip when hovering the T1OS logo
        if HOVERSTART:

            label = "start"

            try:

                tw = measurettffile(label, HOVERFONTSIZE)

            except Exception:

                tw = 0

            if tw > 0 and TOOLTIPID is not None and TOOLTIPBUF is not None:

                # center text horizontally over the logo
                tx = int(LOGOX + (LOGOW // 2) - (tw // 2))

                if tx < 4:
                    tx = 4

                if tx + tw > DESKTOPW - 4:
                    tx = DESKTOPW - tw - 4

                # place tooltip above the taskbar with descent safety
                descentpad = max(3, HOVERFONTSIZE // 6)

                ty = DESKTOPH - TASKBARH - 4 - descentpad - HOVERFONTSIZE

                if ty < 0:
                    ty = 0

                rx = max(0, int(tx - 3))

                ry = max(0, int(ty - 3))

                rw = int(min(DESKTOPW - rx, tw + 6))

                rh = int(min(DESKTOPH - ry, HOVERFONTSIZE + 6))

                globals()["HOVERRECT"] = [rx, ry, rw, rh]

                # paint tooltip window
                try:

                    fillbufferfile(
                        TOOLTIPBUF,
                        rw,
                        0,
                        0,
                        rw,
                        rh,
                        (0, 0, 0)
                    )

                except Exception as e:

                    log(f"hover start tooltip fill error {e}")

                    rw = 0

                if rw > 0:

                    try:

                        drawttffile(
                            TOOLTIPBUF,
                            rw,
                            rh,
                            int(tx - rx),
                            int(ty - ry),
                            label,
                            HOVERCOLOR,
                            HOVERFONTSIZE
                        )

                    except Exception as e:

                        log(f"hover start tooltip text error {e}")

                    try:

                        sendline(sock, {"op": "MOVE", "winid": TOOLTIPID, "x": rx, "y": ry})

                        sendline(sock, {"op": "RESIZE", "winid": TOOLTIPID, "w": rw, "h": rh})

                    except Exception as e:

                        log(f"hover start tooltip move/resize error {e}")

                    try:

                        graphicscpudamage(sock, "tooltip", [0, 0, rw, rh])

                    except Exception as e:

                        log(f"hover start tooltip damage error {e}")

        # clock tooltip when hovering the clock
        if HOVERCLOCK:

            label = ""

            try:

                tstr, dstr = readatreyantime()

            except Exception:

                tstr = ""
                dstr = ""

            try:

                wdays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

                mons = [
                    "January", "February", "March", "April", "May", "June",
                    "July", "August", "September", "October", "November", "December"
                ]

                t = readatreyanstruct()

                wdayname = wdays[max(0, min(6, int(getattr(t, "tm_wday", 0))))]

                daynum = int(getattr(t, "tm_mday", 1))

                monidx = int(getattr(t, "tm_mon", 1)) - 1

                monname = mons[max(0, min(11, monidx))]

                ayear = ""

                try:

                    if dstr and "/" in dstr:
                        parts = dstr.split("/")

                        if len(parts) >= 3:
                            ayear = parts[2]

                except Exception:

                    ayear = ""

                if ayear:

                    label = f"{wdayname}, {daynum} {monname} {ayear}"

                else:

                    label = f"{wdayname}, {daynum} {monname}"

            except Exception as e:

                log(f"clock hover label build error {e}")

                label = ""

            try:

                tw = measurettffile(label, HOVERFONTSIZE)

            except Exception:

                tw = 0

            if tw > 0 and TOOLTIPID is not None and TOOLTIPBUF is not None:

                ensureclockrect()

                rect = globals().get("CLOCKRECT")

                if rect and len(rect) >= 4:

                    cx = rect[0]

                    cw = rect[2]

                else:

                    cx = 0

                    cw = 0

                if cw > 0:

                    tx = cx + (cw - tw) // 2

                    if tx < 0:
                        tx = 0

                    if tx + tw > DESKTOPW:
                        tx = max(0, DESKTOPW - tw)

                else:

                    tx = taskbarclockx(tw)

                    if tx < 0:
                        tx = 0

                    if tx + tw > DESKTOPW:
                        tx = max(0, DESKTOPW - tw)

                descentpad = max(3, HOVERFONTSIZE // 6)

                ty = DESKTOPH - TASKBARH - 4 - descentpad - HOVERFONTSIZE

                if ty < 0:
                    ty = 0

                rx = max(0, int(tx - 3))

                ry = max(0, int(ty - 3))

                rw = int(min(DESKTOPW - rx, tw + 6))

                rh = int(min(DESKTOPH - ry, HOVERFONTSIZE + 6))

                globals()["HOVERRECT"] = [rx, ry, rw, rh]

                try:

                    sendline(sock, {"op": "RESIZE", "winid": TOOLTIPID, "w": rw, "h": rh})

                    sendline(sock, {"op": "MOVE", "winid": TOOLTIPID, "x": rx, "y": ry})

                except Exception as e:

                    log(f"hover clock tooltip move/resize error {e}")

                try:

                    fillbufferfile(
                        TOOLTIPBUF,
                        rw,
                        0,
                        0,
                        rw,
                        rh,
                        (0, 0, 0)
                    )

                except Exception as e:

                    log(f"hover clock tooltip fill error {e}")

                    rw = 0

                if rw > 0:

                    try:

                        drawttffile(
                            TOOLTIPBUF,
                            rw,
                            rh,
                            int(tx - rx),
                            int(ty - ry),
                            label,
                            HOVERCOLOR,
                            HOVERFONTSIZE
                        )

                    except Exception as e:

                        log(f"hover clock tooltip text error {e}")

                    try:

                        graphicscpudamage(sock, "tooltip", [0, 0, rw, rh])

                    except Exception as e:

                        log(f"hover clock tooltip damage error {e}")

                    try:

                        graphicscpudamage(sock, "tooltip", [0, 0, rw, rh])

                    except Exception as e:

                        log(f"hover clock tooltip damage error {e}")

        # audio tooltip when hovering the audio icon
        if HOVERAUDIO and (not VOLUMEMAPPED) and (not VOLUMEPENDING):

            now = time.time()

            newlabel = makeaudiolabel()

            newlabel = str(newlabel or "").strip()

            if not newlabel:
                newlabel = "unavailable"

            # debounce flapping audio state (prevents tooltip flashing)
            if not HOVERAUDIOLABEL:

                HOVERAUDIOLABEL = newlabel

                HOVERAUDIOLABELTS = now

            else:

                if newlabel != HOVERAUDIOLABEL:

                    if now - HOVERAUDIOLABELTS >= 0.25:
                        HOVERAUDIOLABEL = newlabel

                        HOVERAUDIOLABELTS = now

                else:

                    HOVERAUDIOLABELTS = now

            label = HOVERAUDIOLABEL

            if TOOLTIPID is None or TOOLTIPBUF is None:
                return

            try:

                tw = measurettffile(label, HOVERFONTSIZE)

            except Exception:

                tw = 0

            padx = s(6, 3)

            pady = s(6, 3)

            rw = max(s(40, 20), int(tw + padx * 2))

            rh = int(HOVERFONTSIZE + pady * 2)

            rx = int(AUDIOICONX + (AUDIOICONW - rw) // 2)

            ry = int(DESKTOPH - TASKBARH - 4 - rh)

            if rx < 0:
                rx = 0

            if ry < 0:
                ry = 0

            newrect = [rx, ry, rw, rh]

            globals()["HOVERRECT"] = newrect

            if TOOLTIPMAPPED and HOVERAUDIODRAWLABEL == label and HOVERAUDIODRAWRECT == newrect:
                return

            try:

                sendline(sock, {"op": "RESIZE", "winid": TOOLTIPID, "w": rw, "h": rh})

                sendline(sock, {"op": "MOVE", "winid": TOOLTIPID, "x": rx, "y": ry})

            except Exception as e:

                log(f"hover audio tooltip move/resize error {e}")

            try:

                fillbufferfile(
                    TOOLTIPBUF,
                    rw,
                    0,
                    0,
                    rw,
                    rh,
                    (0, 0, 0)
                )

            except Exception as e:

                log(f"hover audio tooltip fill error {e}")

                rw = 0

            if rw > 0:

                try:

                    drawttffile(
                        TOOLTIPBUF,
                        rw,
                        rh,
                        padx,
                        pady,
                        label,
                        HOVERCOLOR,
                        HOVERFONTSIZE
                    )

                except Exception as e:

                    log(f"hover audio tooltip text error {e}")

                try:

                        graphicscpudamage(sock, "tooltip", [0, 0, rw, rh])

                except Exception as e:

                    log(f"hover audio tooltip damage error {e}")

            HOVERAUDIODRAWLABEL = label

            HOVERAUDIODRAWRECT = newrect

        # network tooltip when hovering the network icon
        if HOVERNET:

            state, iface, addr, gw, mac = readnetworkstatus()

            state = (state or "").lower()

            online = bool(
                state == "online"
                and iface
            )

            if TOOLTIPID is None or TOOLTIPBUF is None:
                return

            if online:

                labels = networktooltiplabels(iface)
                textwidth = 0

                for label in labels:

                    try:
                        textwidth = max(textwidth, measurettffile(label, HOVERFONTSIZE))
                    except Exception:
                        pass

                padx = 6

                pady = 6

                linegap = max(2, HOVERFONTSIZE // 4)

                tw = textwidth

                th = len(labels) * HOVERFONTSIZE + max(0, len(labels) - 1) * linegap

                rw = tw + padx * 2

                rh = th + pady * 2

                # anchor tooltip above the network icon
                rx = int(NETICONX + (NETICONW - rw) // 2)

                ry = int(DESKTOPH - TASKBARH - 4 - rh)

                if rx < 0:
                    rx = 0

                if rx + rw > DESKTOPW:
                    rx = max(0, DESKTOPW - rw)

                if ry < 0:
                    ry = 0

                globals()["HOVERRECT"] = [rx, ry, rw, rh]

                try:

                    sendline(sock, {"op": "RESIZE", "winid": TOOLTIPID, "w": rw, "h": rh})

                    sendline(sock, {"op": "MOVE", "winid": TOOLTIPID, "x": rx, "y": ry})

                except Exception as e:

                    log(f"hover net tooltip move/resize error {e}")

                try:

                    fillbufferfile(
                        TOOLTIPBUF,
                        rw,
                        0,
                        0,
                        rw,
                        rh,
                        (0, 0, 0)
                    )

                except Exception as e:

                    log(f"hover net tooltip fill error {e}")

                    rw = 0

                if rw > 0:

                    y = pady

                    for label in labels:

                        drawttffile(
                            TOOLTIPBUF,
                            rw,
                            rh,
                            padx,
                            y,
                            label,
                            HOVERCOLOR,
                            HOVERFONTSIZE
                        )

                        y += HOVERFONTSIZE + linegap

                    try:

                        graphicscpudamage(sock, "tooltip", [0, 0, rw, rh])

                    except Exception as e:

                        log(f"hover net tooltip damage error {e}")

            else:

                label = makenetworklabel()

                label = str(label or "").strip()

                if not label:
                    label = "offline"

                try:

                    tw = measurettffile(label, HOVERFONTSIZE)

                except Exception:

                    tw = 0

                padx = s(6, 3)

                pady = s(6, 3)

                rw = max(s(40, 20), int(tw + padx * 2))

                rh = int(HOVERFONTSIZE + pady * 2)

                # anchor tooltip above the network icon
                rx = int(NETICONX + (NETICONW - rw) // 2)

                ry = int(DESKTOPH - TASKBARH - 4 - rh)

                if rx < 0:
                    rx = 0

                if rx + rw > DESKTOPW:
                    rx = max(0, DESKTOPW - rw)

                if ry < 0:
                    ry = 0

                globals()["HOVERRECT"] = [rx, ry, rw, rh]

                try:

                    sendline(sock, {"op": "RESIZE", "winid": TOOLTIPID, "w": rw, "h": rh})

                    sendline(sock, {"op": "MOVE", "winid": TOOLTIPID, "x": rx, "y": ry})

                except Exception as e:

                    log(f"hover net tooltip move/resize error {e}")

                try:

                    fillbufferfile(
                        TOOLTIPBUF,
                        rw,
                        0,
                        0,
                        rw,
                        rh,
                        (0, 0, 0)
                    )

                except Exception as e:

                    log(f"hover net tooltip fill error {e}")

                    rw = 0

                if rw > 0:

                    try:

                        drawttffile(
                            TOOLTIPBUF,
                            rw,
                            rh,
                            padx,
                            pady,
                            label,
                            HOVERCOLOR,
                            HOVERFONTSIZE
                        )

                    except Exception as e:

                        log(f"hover net tooltip text error {e}")

                    try:

                        graphicscpudamage(sock, "tooltip", [0, 0, rw, rh])

                    except Exception as e:

                        log(f"hover net tooltip damage error {e}")

        if HOVERRECT and len(HOVERRECT) == 4 and TOOLTIPBUF is not None:

            GRAPHICSTOOLTIPDATA = None
            graphicsupdategeometry("tooltip", HOVERRECT[2], HOVERRECT[3], TOOLTIPBUF)
            graphicspresent(sock, "tooltip", [0, 0, HOVERRECT[2], HOVERRECT[3]])

            if not TOOLTIPMAPPED:

                sendline(sock, {"op": "MAP", "winid": TOOLTIPID})
                globals()["TOOLTIPMAPPED"] = True

    except Exception as e:

        log(f"hover net label block error {e}")


def taskbarpaintshowdesktop():

    try:

        sx = DESKTOPW - SHOWDESKTOP_W

        sy = 0

        sw = SHOWDESKTOP_W

        sh = TASKBARH

        fillbufferfile(
            TASKBARBUF,
            DESKTOPW,
            sx,
            sy,
            sw,
            sh,
            (0, 0, 0)
        )

        # left vertical grey line
        fillbufferfile(
            TASKBARBUF,
            DESKTOPW,
            sx,
            sy,
            1,
            sh,
            (96, 96, 96)
        )

        absx = sx

        absy = DESKTOPH - TASKBARH + sy

        globals()["SHOWDESKTOP_RECT"] = [absx, absy, sw, sh]

    except Exception as e:

        log(f"show desktop paint error {e}")


def taskbarpaintclock():

    try:

        # draw clock on right
        t, d = readatreyantime()

        tsz = CLOCKFONTSIZE

        tw = measurettffile(t, tsz)

        dw = measurettffile(d, tsz)

        wmax = max(tw, dw, 0)

        cx = taskbarclockx(wmax)

        b1, b2 = clockbaselines(TASKBARH, tsz)

        ty = b1 - tsz

        dy = b2 - tsz

        drawttffile(
            TASKBARBUF,
            DESKTOPW,
            TASKBARH,
            cx + (wmax - max(tw, 0)) // 2,
            ty,
            t,
            0xEFEFEF,
            tsz
        )

        drawttffile(
            TASKBARBUF,
            DESKTOPW,
            TASKBARH,
            cx + (wmax - max(dw, 0)) // 2,
            dy,
            d,
            0xEFEFEF,
            tsz
        )

        globals()["CLOCK_LAST_T"] = t

        globals()["CLOCK_LAST_D"] = d

        globals()["CLOCK_WMAX"] = wmax

        globals()["CLOCK_CX"] = cx

        globals()["CLOCKRECT"] = [cx, max(0, DESKTOPH - TASKBARH), max(0, wmax), TASKBARH]

    except Exception as e:

        log(f"clock initial draw error {e}")


def taskbarpaintmasterimage():

    globals()["MASTERIMAGERECT"] = None

    if not masterimageactive():
        return

    try:

        size = max(1, min(int(MASTERIMAGE_SIZE), int(TASKBARH)))
        imagex = (
            DESKTOPW - SHOWDESKTOP_W - CLOCKPADX - size)
        imagey = max(0, (TASKBARH - size) // 2)
        cachedpath, sourcewidth, sourceheight = prepareicon(
            MASTERIMAGEPATH, size, size, masterimage=True)

        if cachedpath is None or sourcewidth < 1 or sourceheight < 1:
            return

        blitrawscaledintobuffer(
            cachedpath,
            sourcewidth,
            sourceheight,
            TASKBARBUF,
            DESKTOPW,
            imagex,
            imagey,
            size,
            size)

        globals()["MASTERIMAGERECT"] = [
            imagex,
            DESKTOPH - TASKBARH + imagey,
            size,
            size,
        ]

    except Exception as e:

        log(f"master image paint error {e}")


def taskbarpaintnetwork(sock):

    try:

        updatenetworkicon(sock)

    except Exception as e:

        log(f"network icon draw error {e}")


def taskbarpaintwindowicons():

    try:

        # starting x for first window button (after launcher and search field)
        if SEARCHRECT and len(SEARCHRECT) == 4:
            startx = int(SEARCHRECT[0] + SEARCHRECT[2] + WINDOWGAP)
        else:
            startx = LAUNCHX + LAUNCHW + WINDOWGAP

        try:

            clockleft = CLOCK_CX

        except Exception:

            clockleft = DESKTOPW - 200

        # stop before clock
        maxx = clockleft - WINDOWGAP

        boxw = int(WINDOWBOXSIZE)

        boxh = boxw

        # logo inside button
        logoh = int(TASKBARH * 0.70)

        if logoh < 1:
            logoh = 1

        if logoh > boxh:
            logoh = boxh

        logow = logoh

        pad = (boxw - logow) // 2

        if pad < 1:
            pad = 1

        boxy = (TASKBARH - boxh) // 2

        buildtaskbargroups()

        dragpaint = False

        if DRAGTASKACTIVE and DRAGTASKGROUP is not None and DRAGTASKMOVED:
            dragpaint = True

        for title in list(TASKBARGROUPS):

            g = TASKBARGROUPITEMS.get(title)

            if not g:
                continue

            wids = list(g.get("wids", []))

            if not wids and not bool(g.get("pinned")):
                continue

            # no space left for another button
            if startx + boxw > maxx:
                break

            boxx = startx

            # button background
            background = (0, 0, 0)

            if title == TASKBARHOVERGROUP and not dragpaint:
                # Reuse Expanse's darker pressed-button grey for window hover.
                background = BRICKBG_DOWN

            fillbufferfile(
                TASKBARBUF,
                DESKTOPW,
                boxx,
                boxy,
                boxw,
                boxh,
                background
            )

            absx = boxx

            absy = DESKTOPH - TASKBARH + boxy

            TASKBARGROUPRECTS[title] = [absx, absy, boxw, boxh]

            # if dragging: draw a placeholder slot where the dragged icon "belongs"
            if dragpaint and title == DRAGTASKGROUP:

                # subtle placeholder to show the slot
                fillbufferfile(
                    TASKBARBUF,
                    DESKTOPW,
                    boxx + 6,
                    boxy + 6,
                    boxw - 12,
                    boxh - 12,
                    (24, 24, 24)
                )

                startx += boxw + WINDOWGAP

                continue

            rep = {}

            if wids:
                repwid = wids[0]

                rep = WINDOWITEMS.get(repwid, {})

            try:

                softname = str(g.get("name", "")).strip().lower()

                if not softname:
                    softname = str(rep.get("name", "")).strip().lower()

                if not softname:

                    base = str(title).strip()

                    if " - " in base:
                        base = base.split(" - ", 1)[0]

                    if " " in base:
                        base = base.split(" ", 1)[0]

                    softname = base.lower()

                iconinfo = SOFTWAREICONS.get(softname)

                if not iconinfo:
                    iconinfo = SOFTWAREICONS.get("brick")

                iconpath = iconinfo["path"]

                cachedpath, sw, sh = prepareicon(iconpath, logow, logoh)

                if sw > 0 and sh > 0 and cachedpath is not None:

                    out_h = logoh
                    out_w = logow

                    logo_x = boxx + (boxw - out_w) // 2

                    logo_y = boxy + (boxh - out_h) // 2

                    blitrawscaledintobuffer(
                        cachedpath,
                        sw,
                        sh,
                        TASKBARBUF,
                        DESKTOPW,
                        logo_x,
                        logo_y,
                        out_w,
                        out_h
                    )

            except Exception as e:

                log(f"taskbar group icon logo error {e}")

            focused = False

            running = False

            try:

                running = bool(wids)

                for wid in wids:

                    it = WINDOWITEMS.get(wid)

                    if not it:
                        continue

                    if ACTIVEWID is not None and wid == ACTIVEWID and bool(it.get("mapped")):
                        focused = True

            except Exception:
                pass

            # draw underline for any running group (minimized or visible)
            if running:

                if focused:
                    color = (239, 239, 239)
                else:
                    color = (96, 96, 96)

                fillbufferfile(
                    TASKBARBUF,
                    DESKTOPW,
                    boxx,
                    TASKBARH - 3,
                    boxw,
                    3,
                    color
                )

            startx += boxw + WINDOWGAP

        # floating dragged icon painted on top
        if dragpaint:

            g = TASKBARGROUPITEMS.get(DRAGTASKGROUP)

            if g:

                wids = list(g.get("wids", []))

            else:

                wids = []

            rep = {}

            if wids:
                repwid = wids[0]

                rep = WINDOWITEMS.get(repwid, {})

            taskbartop = DESKTOPH - TASKBARH

            px = int(DRAGTASKX)

            py = int(DRAGTASKY)

            localx = int(px)

            localy = int(py - taskbartop)

            flox = int(localx - int(DRAGTASKOFFSETX))

            floy = 0

            if flox < 0:
                flox = 0

            if flox + boxw > DESKTOPW:
                flox = max(0, DESKTOPW - boxw)

            # "floating" background block
            fillbufferfile(
                TASKBARBUF,
                DESKTOPW,
                flox,
                floy,
                boxw,
                boxh,
                (32, 32, 32)
            )

            try:

                softname = ""

                try:

                    if g:
                        softname = str(g.get("name", "")).strip().lower()

                except Exception:

                    softname = ""

                if not softname:
                    softname = str(rep.get("name", "")).strip().lower()

                if not softname:
                    softname = str(DRAGTASKGROUP).strip().lower()

                iconinfo = SOFTWAREICONS.get(softname)

                if not iconinfo:
                    iconinfo = SOFTWAREICONS.get("brick")

                iconpath = iconinfo["path"]

                cachedpath, sw, sh = prepareicon(iconpath, logow, logoh)

                if sw > 0 and sh > 0 and cachedpath is not None:

                    out_h = logoh
                    out_w = logow

                    logo_x = flox + (boxw - out_w) // 2

                    logo_y = floy + (boxh - out_h) // 2

                    blitrawscaledintobuffer(
                        cachedpath,
                        sw,
                        sh,
                        TASKBARBUF,
                        DESKTOPW,
                        logo_x,
                        logo_y,
                        out_w,
                        out_h
                    )

            except Exception as e:

                log(f"floating taskbar icon paint error {e}")

    except Exception as e:

        log(f"taskbar icon paint error {e}")


def taskbarcommit(sock, realbuf, tmpbuf):

    try:

        # Publish the complete staged frame into the existing server-owned inode.
        try:

            commitcpusurface(
                tmpbuf,
                realbuf,
                int(DESKTOPW) * int(TASKBARH) * 4,
            )

        except Exception as e:

            log(f"taskbar tmp commit error {e}")
            raise

        # restore live buffer path
        globals()["TASKBARBUF"] = realbuf

        graphicsupdategeometry("taskbar", DESKTOPW, TASKBARH, realbuf)
        graphicscpudamage(sock, "taskbar", [0, 0, DESKTOPW, TASKBARH])

    except Exception as e:

        log(f"taskbar commit error {e}")


def taskbarcleanup(realbuf, tmpbuf):

    # always restore live buffer path, even on early error
    globals()["TASKBARBUF"] = realbuf

    # remove temp buffer if it still exists
    try:

        if os.path.exists(tmpbuf):

            os.remove(tmpbuf)

    except Exception as e:

        log(f"taskbar tmp cleanup error {e}")


# start menu functions
def launchsoftware(soft):

    try:

        path = soft.get("path")

        if not path:
            log("launchsoftware missing path")
            return

        name = soft.get("name", "")

        if not name:

            try:

                name = os.path.splitext(os.path.basename(path))[0]

            except Exception:

                name = "app"

        env = dict(os.environ)

        extra = soft.get("env") or {}

        try:

            for k, v in extra.items():
                env[str(k)] = str(v)

        except Exception as e:

            log(f"launchsoftware env merge error {e}")

        args = soft.get("args") or []

        cmd = [sys.executable, path]

        try:

            for a in args:
                cmd.append(str(a))

        except Exception as e:

            log(f"launchsoftware args build error {e}")

        try:

            logpath = softwarelogpath(path, soft.get("logpath", ""))
            # Expanse must not execute start-menu paths directly.  The
            # credential-bound Operations broker owns the application
            # catalogue, validates the requested entry, applies the immutable
            # LSM domain, and drops the application to the desktop uid/gid.
            from operations.operations import launchcatalogueapplication
            result = launchcatalogueapplication(
                path,
                args=[str(value) for value in args],
                name=name,
                logpath=logpath,
                environment=extra,
            )
            pid = int((result or {}).get("pid", 0))
            if pid <= 1:
                raise PermissionError("Operations broker rejected the application launch")

        except PermissionError:

            log(f"launchsoftware permission denied for {path}")

            return

        except FileNotFoundError:

            log(f"launchsoftware file not found {path}")

            return

        except Exception as e:

            log(f"launchsoftware spawn error {e}")

            return

        try:

            usedrole = soft.get("role", "")

            if not usedrole:
                usedrole = readmasterrole()

        except Exception as e:

            log(f"launchsoftware role resolve error {e}")

            usedrole = "master"

        try:

            # user resolved from master file (master / architect)
            useduser = usedrole

            # GUI/start-menu apps (including brick) run in front
            usedmode = "front"

            # Catalogue launches are registered by OperationsServer after the
            # child has successfully entered its constrained profile.
            log(f"operations catalogue launch registered pid={pid} name={name}")

        except Exception as e:

            log(f"launchsoftware register error {e}")

    except Exception as e:

        log(f"launchsoftware error {e}")


def openstartmenu(sock):

    try:

        if SEARCHINPUTFOCUSED:
            closesearch(sock)

        globals()["STARTWANTED"] = True

        # dynamically size start menu height to content
        placecount = 0

        softcount = 0

        try:

            placecount = len(STARTPLACEITEMS)

        except Exception:
            placecount = 0

        try:

            softcount = len(STARTSOFTITEMS)

        except Exception:
            softcount = 0

        ph = s(24, 12)

        maxavail = DESKTOPH - TASKBARH

        if maxavail < 0:
            maxavail = 0

        block_places = STARTPAD + STARTTITLESIZE + STARTPAD + (placecount * STARTITEMH)

        block_soft = STARTPAD + STARTTITLESIZE + STARTPAD + (softcount * STARTITEMH)

        desired = max(block_places, block_soft) + (STARTPAD * 4) + ph

        if maxavail and desired > maxavail:
            desired = maxavail

        if desired < ph + (STARTPAD * 2):
            desired = ph + (STARTPAD * 2)

        if desired != STARTH:

            globals()["STARTH"] = desired

            if STARTID is not None:

                x = 0

                y = DESKTOPH - TASKBARH - STARTH

                if y < 0:
                    y = 0

                sendline(sock, {"op": "RESIZE", "winid": STARTID, "w": STARTW, "h": STARTH})

                sendline(sock, {"op": "MOVE", "winid": STARTID, "x": x, "y": y})

                graphicsupdategeometry("startmenu", STARTW, STARTH, STARTBUF)

        if STARTID is None:

            x = 0

            y = DESKTOPH - TASKBARH - STARTH

            if y < 0:
                y = 0

            sendline(sock, {
                "op": "CREATE_WINDOW",
                "w": STARTW,
                "h": STARTH,
                "x": x,
                "y": y,
                "title": "start",
                "role": "startmenu"
            })

            log(f"start menu create sent at {x},{y}")

            return

        if not STARTMAPPED:

            try:

                if STARTBUF is not None:
                    paintstartmenu(sock)

            except Exception as e:

                log(f"openstartmenu immediate paint error {e}")

            mapwin(sock, STARTID, "startmenu")

        # Focus Start while it is visible so typed text can be handed directly
        # to taskbar search without first clicking the search field.
        sendline(sock, {"op": "FOCUS_SET", "winid": STARTID})

        globals()["STARTVISIBLE"] = True

    except Exception as e:

        log(f"openstartmenu error {e}")


def closestartmenu(sock):

    try:

        globals()["STARTWANTED"] = False

        if STARTID is None:
            return

        # reset power menu state when start closes

        globals()["POWERMENUOPEN"] = False

        for item in POWERMENUITEMS:
            item["rect"] = None

        if not STARTMAPPED:
            globals()["STARTVISIBLE"] = False

            return

        # unmap start window
        AWAITMAP.pop(STARTID, None)
        graphicssuspend(sock, "startmenu")

        sendline(sock, {"op": "UNMAP", "winid": STARTID})

        globals()["STARTMAPPED"] = False

        globals()["STARTVISIBLE"] = False

    except Exception as e:

        log(f"closestartmenu error {e}")


def togglestartmenu(sock):

    try:

        if not STARTWANTED:

            openstartmenu(sock)

        else:

            closestartmenu(sock)

        globals()["CLOCK_LAST_T"] = ""

        globals()["CLOCK_LAST_D"] = ""

    except Exception as e:

        log(f"togglestartmenu error {e}")


def handlestartmenutoggle(sock, msg):

    try:

        togglestartmenu(sock)

    except Exception as e:

        log(f"handlestartmenutoggle error {e}")


def handlestartmenuclick(sock, msg):

    global POWERITEMRECT, POWERMENUOPEN, POWERMENUITEMS

    try:

        if STARTID is None:
            return

        wid = int(msg.get("winid", 0))

        if wid != STARTID:
            return

        st = str(msg.get("state", "down"))

        if st != "up":
            return

        try:

            lx = int(msg.get("x", 0))

            ly = int(msg.get("y", 0))

        except Exception:

            lx = 0

            ly = 0

        try:

            inside_icon = False

            if POWERITEMRECT and len(POWERITEMRECT) == 4:

                px, py, pw, ph = POWERITEMRECT

                if px <= lx < px + pw and py <= ly < py + ph:
                    inside_icon = True

            if inside_icon:
                POWERMENUOPEN = not POWERMENUOPEN

                paintstartmenu(sock)

                return

            if POWERMENUOPEN:

                clicked = False

                for item in POWERMENUITEMS:

                    rect = item.get("rect")

                    if not rect or len(rect) != 4:
                        continue

                    x, y, w, h = rect

                    if x <= lx < x + w and y <= ly < y + h:

                        clicked = True

                        action = item.get("action", "")

                        if action == "logout":

                            logout()

                        elif action == "shutdown":

                            shutdown()

                        elif action == "restart":

                            restart()

                        return

                if not clicked:

                    POWERMENUOPEN = False

                    paintstartmenu(sock)

                    return

        except Exception as e:

            log(f"start power click error {e}")

        try:

            for item in STARTSOFTITEMS:

                rect = item.get("rect")

                if not rect or len(rect) != 4:
                    continue

                x, y, w, h = rect

                if x <= lx < x + w and y <= ly < y + h:
                    launchsoftware(item)

                    closestartmenu(sock)

                    return

        except Exception as e:

            log(f"start software click error {e}")

        try:

            for item in STARTPLACEITEMS:

                rect = item.get("rect")

                if not rect or len(rect) != 4:
                    continue

                x, y, w, h = rect

                if x <= lx < x + w and y <= ly < y + h:
                    target = item.get("path", "/")

                    soft = {
                        "label": "array",
                        "name": "array",
                        "path": "/the one/build/array/array.py",
                        "args": [target]
                    }

                    launchsoftware(soft)

                    closestartmenu(sock)

                    return

        except Exception as e:

            log(f"start place click error {e}")

    except Exception as e:

        log(f"handlestartmenuclick error {e}")


# window functions
def handletaskbarcreated(sock, msg):

    global WINDOWITEMS, WINDOWORDER

    try:

        wid = int(msg.get("winid", 0))

        if wid <= 0:
            return

        role = str(msg.get("role", ""))

        if role != 'window':
            return

        title = str(msg.get("title", ""))

        name = str(msg.get("name", ""))

        current = str(msg.get("current", ""))

        path = str(msg.get("path", ""))

        if wid not in WINDOWITEMS:

            WINDOWITEMS[wid] = {
                "wid": wid,
                "title": title,
                "role": role,
                "name": name,
                "current": current,
                "path": path,
                "rect": None,
                "mapped": False
            }

            WINDOWORDER.append(wid)

        else:

            WINDOWITEMS[wid]["title"] = title

            WINDOWITEMS[wid]["role"] = role

            WINDOWITEMS[wid]["name"] = name

            WINDOWITEMS[wid]["current"] = current

            WINDOWITEMS[wid]["path"] = path

        if TASKBARID is not None and TASKBARBUF is not None:
            painttaskbar(sock)

    except Exception as e:

        log(f"handletaskbarcreated error {e}")


def handletaskbarmapped(sock, msg):

    try:

        wid = int(msg.get("winid", 0))

        if wid in WINDOWITEMS:
            WINDOWITEMS[wid]["mapped"] = True

        if TASKBARID is not None and TASKBARBUF is not None:
            painttaskbar(sock)

    except Exception as e:

        log(f"handletaskbarmapped error {e}")


def handletaskbarunmapped(sock, msg):

    try:

        wid = int(msg.get("winid", 0))

        if wid in WINDOWITEMS:
            WINDOWITEMS[wid]["mapped"] = False

        if TASKBARID is not None and TASKBARBUF is not None:
            painttaskbar(sock)

    except Exception as e:

        log(f"handletaskbarunmapped error {e}")


def handletaskbardestroyed(sock, msg):

    global WINDOWITEMS, WINDOWORDER, ACTIVEWID

    try:

        wid = int(msg.get("winid", 0))

        if wid in WINDOWITEMS:
            WINDOWITEMS.pop(wid, None)

        if wid in WINDOWORDER:
            WINDOWORDER.remove(wid)

        if ACTIVEWID == wid:
            ACTIVEWID = None

        if TASKBARID is not None and TASKBARBUF is not None:
            painttaskbar(sock)

    except Exception as e:

        log(f"handletaskbardestroyed error {e}")


def handletaskbarfocus(sock, msg):

    global ACTIVEWID

    try:

        wid = int(msg.get("winid", 0))

        if wid <= 0:

            ACTIVEWID = None

        else:

            ACTIVEWID = wid

        if TASKBARID is not None and TASKBARBUF is not None:
            painttaskbar(sock)

    except Exception as e:

        log(f"handletaskbarfocus error {e}")


def handletaskbarcurrent(sock, msg):
    try:

        wid = int(msg.get("winid", 0))

        current = str(msg.get("current", ""))

    except Exception as e:

        log(f"handletaskbarcurrent parse error {e}")

        return

    try:

        if wid in WINDOWITEMS:
            WINDOWITEMS[wid]["current"] = current

        if TASKBARID is not None and TASKBARBUF is not None:
            painttaskbar(sock)

    except Exception as e:

        log(f"handletaskbarcurrent error {e}")


def handletaskbarpinhotkey(sock, msg):

    try:

        idx = int(msg.get("index", 0))

    except Exception as e:

        log(f"handletaskbarpinhotkey parse error {e}")

        return

    if idx <= 0:
        return

    try:

        buildtaskbargroups()

        if idx > len(TASKBARGROUPS):
            return

        group = TASKBARGROUPS[idx - 1]

        g = TASKBARGROUPITEMS.get(group)

        if not g:
            return

        wids = list(g.get("wids", []))

        if wids:

            wid = pickgroupwid(group)

            if wid is not None:
                toggletaskbarwindow(sock, wid)

            return

        if g.get("pinned"):
            launchgroup(group)

    except Exception as e:

        log(f"handletaskbarpinhotkey error {e}")


def findtaskbarwindowat(ax, ay):
    try:

        for wid in list(WINDOWORDER):

            item = WINDOWITEMS.get(wid)

            if not item:
                continue

            rect = item.get("rect")

            if not rect or len(rect) != 4:
                continue

            x, y, w, h = rect

            if x <= ax < x + w and y <= ay < y + h:
                return wid

    except Exception as e:

        log(f"findtaskbarwindowat error {e}")

    return None


def findtaskbargroupat(ax, ay):
    try:

        for title in list(TASKBARGROUPS):

            rect = TASKBARGROUPRECTS.get(title)

            if not rect or len(rect) != 4:
                continue

            x, y, w, h = rect

            if x <= ax < x + w and y <= ay < y + h:
                return title

    except Exception as e:

        log(f"findtaskbargroupat error {e}")

    return None


def buildtaskbargroups():

    global TASKBARGROUPS, TASKBARGROUPITEMS, TASKBARGROUPRECTS, TASKBARSEEN, TASKBARORDER

    TASKBARGROUPITEMS = {}

    TASKBARGROUPRECTS = {}

    pinnedorder = []

    for pin in list(TASKBARPINS):

        try:

            p = str(pin.get("path", "")).strip()

            n = str(pin.get("name", "")).strip()

        except Exception:

            p = ""

            n = ""

        if not p:
            continue

        if not n:

            try:

                n = os.path.splitext(os.path.basename(p))[0]

            except Exception:

                n = "app"

        group = n

        if group not in pinnedorder:
            pinnedorder.append(group)

        if group not in TASKBARGROUPITEMS:
            TASKBARGROUPITEMS[group] = {"wids": [], "path": p, "name": n, "pinned": True}

    present = []

    for wid in list(WINDOWORDER):

        item = WINDOWITEMS.get(wid)

        if not item:
            continue

        name = str(item.get("name", "")).strip()

        title = str(item.get("title", "")).strip()

        path = str(item.get("path", "")).strip()

        group = name

        if not group:
            group = title

        if not group:
            group = f"window {wid}"

        if group not in present:
            present.append(group)

        if group not in TASKBARGROUPITEMS:
            TASKBARGROUPITEMS[group] = {"wids": [], "path": path, "name": name, "pinned": False}

        if (not TASKBARGROUPITEMS[group].get("path")) and path:
            TASKBARGROUPITEMS[group]["path"] = path

        if (not TASKBARGROUPITEMS[group].get("name")) and name:
            TASKBARGROUPITEMS[group]["name"] = name

        TASKBARGROUPITEMS[group]["wids"].append(wid)

    # keep a stable "first-seen" order for non-pinned groups
    for g in present:

        if g in pinnedorder:
            continue

        if g not in TASKBARSEEN:
            TASKBARSEEN.append(g)

    # drop non-pinned groups that no longer exist (no windows)
    alive = []

    for g in list(TASKBARSEEN):

        if g in pinnedorder:
            continue

        meta = TASKBARGROUPITEMS.get(g)

        if not meta:
            continue

        if meta.get("wids"):
            alive.append(g)

    TASKBARSEEN = alive

    # merge: pinned + seen/open
    merged = list(pinnedorder) + list(TASKBARSEEN)

    # order by saved order first, then append anything new
    ordered = []

    for g in list(TASKBARORDER):

        if g in merged and g not in ordered:
            ordered.append(g)

    for g in list(merged):

        if g not in ordered:
            ordered.append(g)

    TASKBARGROUPS = ordered

    # keep TASKBARORDER in sync (but only persisted on drop)
    TASKBARORDER = list(ordered)


def pickgroupwid(group):
    
    try:

        g = TASKBARGROUPITEMS.get(group)

        if not g:
            return None

        wids = list(g.get("wids", []))

        try:

            if ACTIVEWID is not None and ACTIVEWID in wids:
                return int(ACTIVEWID)

        except Exception:
            pass

        rows = []

        for wid in wids:

            item = WINDOWITEMS.get(wid)

            if not item:
                continue

            cur = str(
                item.get("current", "")
                or item.get("title", "")
                or group
            )

            rows.append([cur, wid])

        rows.sort(key=lambda r: (r[0] or "").lower())

        if rows:
            return int(rows[0][1])

    except Exception as e:

        log(f"pickgroupwid error {e}")

    return None


def findlistitemat(ax, ay):

    try:

        if not LISTRECT or len(LISTRECT) != 4:
            return None

        lx, ly, lw, lh = LISTRECT

        rx = ax - lx

        ry = ay - ly

        for r in list(LISTITEMRECTS):

            if len(r) < 5:
                continue

            x, y, w, h, wid = r

            if x <= rx < x + w and y <= ry < y + h:
                return int(wid)

    except Exception as e:

        log(f"findlistitemat error {e}")

    return None


def findlistcloseat(ax, ay):

    try:

        if not LISTRECT or len(LISTRECT) != 4:
            return None

        lx, ly, lw, lh = LISTRECT

        rx = ax - lx

        ry = ay - ly

        for r in list(LISTCLOSERECTS):

            if len(r) < 5:
                continue

            x, y, w, h, wid = r

            if x <= rx < x + w and y <= ry < y + h:
                return int(wid)

    except Exception as e:

        log(f"findlistcloseat error {e}")

    return None


def showdesktop(sock):

    try:

        # send toggle request to window server
        sendline(sock, {"op": "SHOW_DESKTOP"})

    except Exception as e:

        log(f"showdesktop error {e}")


def toggletaskbarwindow(sock, wid):

    try:

        if wid is None or wid <= 0:
            return

        # ask window server to restore/raise/focus this window
        sendline(sock, {"op": "TASKBAR_ACTIVATE", "winid": wid})

    except Exception as e:

        log(f"toggletaskbarwindow error {e}")


def showinstancelist(sock, group, anchorrect):

    global LISTRECT, LISTANCHOR, LISTITEMRECTS, LISTCLOSERECTS, LISTMAPPED, LISTGROUP, LISTPENDINGGROUP, LISTPENDINGANCHOR, LISTHOVERWID

    try:

        g = TASKBARGROUPITEMS.get(group)

        if not g:
            return

        wids = list(g.get("wids", []))

        rows = []

        for wid in wids:

            item = WINDOWITEMS.get(wid)

            if not item:
                continue

            cur = str(
                item.get("current", "")
                or item.get("title", "")
                or group
            )

            rows.append([cur, wid])

        rows.sort(key=lambda r: (r[0] or "").lower())

        pad = 0

        textclosegap = s(16, 8)

        leftpad = s(8, 4)

        rightpad = leftpad

        if not rows:
            return

        linesz = s(14, 7)

        lineh = TASKMENUITEMH

        closebox = s(18, 9)

        maxtextw = 0

        for cur, _ in rows:

            tw = measurettffile(cur, linesz)

            if tw > maxtextw:
                maxtextw = tw

        wmin = s(160, 80)

        wmax = int(MENUMAXW)

        w = max(
            wmin,
            min(maxtextw + leftpad + rightpad + textclosegap + closebox, wmax)
        )

        h = pad * 2 + len(rows) * lineh

        if LISTID is None:
            LISTPENDINGGROUP = group

            LISTPENDINGANCHOR = anchorrect

            sendline(sock, {
                "op": "CREATE_WINDOW",
                "w": int(w),
                "h": int(h),
                "role": "instancelist",
                "title": "instances"
            })

            return

        if LISTBUF is None:
            return

        ax, ay, aw, ah = anchorrect

        gx = ax + aw // 2 - w // 2

        if gx < 8:
            gx = 8

        if gx + w > DESKTOPW - 8:
            gx = DESKTOPW - 8 - w

        gap = max(3, int(6 * SCALE))

        gy = ay - h - gap

        if gy < gap:
            gy = gap

        LISTANCHOR = anchorrect

        sendline(sock, {"op": "RESIZE", "winid": LISTID, "w": int(w), "h": int(h)})

        sendline(sock, {"op": "MOVE", "winid": LISTID, "x": int(gx), "y": int(gy)})

        graphicsupdategeometry("instancelist", w, h, LISTBUF)

        initbuffer(LISTBUF, w, h)

        clear((0, 0, 0))

        LISTITEMRECTS = []
        LISTCLOSERECTS = []

        y = 0

        for cur, wid in rows:

            ty = textbaseliney(y, lineh, linesz)

            drawtextttf(
                leftpad,
                ty,
                cur,
                0xEFEFEF,
                linesz,
                fontpath=FONTPATH
            )

            LISTITEMRECTS.append([0, y, w, lineh, wid])

            cx = w - rightpad - closebox

            cy = y + (lineh - closebox) // 2

            LISTCLOSERECTS.append([cx, cy, closebox, closebox, wid])

            glyphsize = min(closebox, s(8, 4))
            x1 = cx + (closebox - glyphsize) // 2
            y1 = cy + (closebox - glyphsize) // 2
            x2 = x1 + glyphsize - 1
            y2 = y1 + glyphsize - 1

            drawline(x1, y1, x2, y2, (0xEF, 0xEF, 0xEF))
            drawline(x1, y2, x2, y1, (0xEF, 0xEF, 0xEF))

            if ACTIVEWID is not None and wid == ACTIVEWID:
                drawrect(0, y, w, lineh, (255, 255, 255))

            y += lineh

        if LISTHOVERWID is not None:

            for rx, ry, rw, rh, rwid in LISTITEMRECTS:

                if rwid == LISTHOVERWID:

                    if rwid != ACTIVEWID:

                        drawrect(0, ry, w, rh, (96, 96, 96))

                    break

        LISTRECT = [gx, gy, w, h]

        LISTGROUP = group

        present()

        graphicscpudamage(sock, "instancelist", [0, 0, int(w), int(h)])
        graphicspresent(sock, "instancelist", [0, 0, int(w), int(h)])

        now = time.time()

        globals()["LISTGRACETS"] = now

        if not LISTMAPPED:
            sendline(sock, {"op": "MAP", "winid": LISTID})

            LISTMAPPED = True

        # keep it above windows and force redraw
        sendline(sock, {"op": "RAISE", "winid": LISTID})

        globals()["LISTGRACETS"] = time.time()

    except Exception as e:

        log(f"showinstancelist error {e}")


def closeinstancelist(sock):

    global LISTMAPPED, LISTRECT, LISTANCHOR, LISTHOVERWID, LISTITEMRECTS, LISTCLOSERECTS, LISTGROUP, LISTREQUESTED

    try:

        oldlistrect = LISTRECT

        LISTRECT = None

        LISTANCHOR = None

        LISTHOVERWID = None

        LISTITEMRECTS = []

        LISTCLOSERECTS = []

        LISTGROUP = None

        LISTREQUESTED = False

        if LISTMAPPED and LISTID is not None:

            graphicssuspend(sock, "instancelist")

            sendline(sock, {"op": "UNMAP", "winid": LISTID})

            LISTMAPPED = False

            if oldlistrect:
                sendline(sock, {"op": "OVERLAY_DAMAGE", "rect": oldlistrect})

    except Exception as e:

        log(f"closeinstancelist error {e}")


# pinning functions
def loadtaskbarpins():

    global TASKBARPINS

    try:

        if not os.path.exists(TASKBARPINSFILE):
            TASKBARPINS = []

            return

        raw = open(TASKBARPINSFILE, "r").read()

        data = json.loads(raw)

        if isinstance(data, list):
            TASKBARPINS = data

        else:
            TASKBARPINS = []

    except Exception as e:

        TASKBARPINS = []

        log(f"loadtaskbarpins error {e}")


def savetaskbarpins():

    try:

        os.makedirs(os.path.dirname(TASKBARPINSFILE), exist_ok=True)

        raw = json.dumps(list(TASKBARPINS), indent=2)

        with open(TASKBARPINSFILE, "w") as f:

            f.write(raw)

            f.flush()

            os.fsync(f.fileno())

    except Exception as e:

        log(f"savetaskbarpins error {e}")


def loadtaskbarorder():

    global TASKBARORDER

    try:

        if not os.path.exists(TASKBARORDERFILE):
            TASKBARORDER = []

            return

        raw = open(TASKBARORDERFILE, "r").read()

        data = json.loads(raw)

        if isinstance(data, list):
            TASKBARORDER = data

        else:
            TASKBARORDER = []

    except Exception as e:

        TASKBARORDER = []

        log(f"loadtaskbarorder error {e}")


def savetaskbarorder():

    try:

        os.makedirs(os.path.dirname(TASKBARORDERFILE), exist_ok=True)

        raw = json.dumps(list(TASKBARORDER), indent=2)

        with open(TASKBARORDERFILE, "w") as f:

            f.write(raw)

            f.flush()

            os.fsync(f.fileno())

    except Exception as e:

        log(f"savetaskbarorder error {e}")


def loadtaskbarsettings():

    global TASKBARSEARCHVISIBLE

    TASKBARSEARCHVISIBLE = True

    try:

        if not os.path.exists(TASKBARSETTINGSFILE):
            return

        with open(TASKBARSETTINGSFILE, "r") as f:
            data = json.load(f)

        if isinstance(data, dict) and isinstance(data.get("search"), bool):
            TASKBARSEARCHVISIBLE = bool(data["search"])

    except Exception as e:

        TASKBARSEARCHVISIBLE = True
        log(f"loadtaskbarsettings error {e}")


def savetaskbarsettings():

    temporary = ""

    try:

        directory = os.path.dirname(TASKBARSETTINGSFILE)
        os.makedirs(directory, exist_ok=True)
        temporary = f"{TASKBARSETTINGSFILE}.{os.getpid()}.temporary"

        with open(temporary, "w") as f:
            json.dump({"search": bool(TASKBARSEARCHVISIBLE)}, f, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())

        os.replace(temporary, TASKBARSETTINGSFILE)

    except Exception as e:

        log(f"savetaskbarsettings error {e}")

        try:
            if temporary and os.path.exists(temporary):
                os.remove(temporary)
        except Exception:
            pass


def grouppinned(group):

    try:

        g = TASKBARGROUPITEMS.get(group)

        if not g:
            return False

        return bool(g.get("pinned"))

    except Exception:
        return False


def pintaskbar(group):

    try:

        g = TASKBARGROUPITEMS.get(group)

        if not g:
            return

        path = str(g.get("path", "")).strip()

        if not path:
            return

        name = str(g.get("name", "")).strip()

        if not name:
            name = str(group).strip()

        for pin in list(TASKBARPINS):

            if str(pin.get("path", "")).strip() == path:
                return

        TASKBARPINS.append({"name": name, "path": path})

        savetaskbarpins()

    except Exception as e:

        log(f"pintaskbar error {e}")


def unpintaskbar(group):

    try:

        g = TASKBARGROUPITEMS.get(group)

        if not g:
            return

        path = str(g.get("path", "")).strip()

        if not path:
            return

        out = []

        for pin in list(TASKBARPINS):

            if str(pin.get("path", "")).strip() == path:
                continue

            out.append(pin)

        globals()["TASKBARPINS"] = out

        savetaskbarpins()

    except Exception as e:

        log(f"unpintaskbar error {e}")


def launchgroup(group):

    try:

        g = TASKBARGROUPITEMS.get(group)

        if not g:
            return

        path = str(g.get("path", "")).strip()

        if not path:
            return

        name = str(g.get("name", "")).strip()

        if not name:

            try:

                name = os.path.splitext(os.path.basename(path))[0]

            except Exception:

                name = "app"

        launchsoftware({"name": name, "path": path, "env": {}})

    except Exception as e:

        log(f"launchgroup error {e}")


def closegroup(sock, group):

    try:

        g = TASKBARGROUPITEMS.get(group)

        if not g:
            return

        wids = list(g.get("wids", []))

        for wid in wids:

            try:

                sendline(sock, {"op": "WINDOW_CLOSE", "winid": int(wid)})

            except Exception:
                pass

    except Exception as e:

        log(f"closegroup error {e}")


# taskbar search functions
def searchscopes():

    candidates = [
        "/master",
        "/software",
        "/.ephemeral/volumes",
    ]
    scopes = []

    for path in candidates:
        try:
            if os.path.isdir(path) and path not in scopes:
                scopes.append(path)
        except Exception:
            pass

    return scopes


def searchhandoffactive(generation):

    handoff = SEARCHHANDOFF
    return bool(
        isinstance(handoff, dict)
        and int(handoff.get("generation", -1)) == int(generation)
    )


def writesearchhandoff(results=None, done=None, error=None, force=False):

    handoff = SEARCHHANDOFF
    if not isinstance(handoff, dict):
        return False

    now = time.monotonic()
    if not force and now - float(handoff.get("written", 0.0)) < 0.1:
        return False

    path = str(handoff.get("path", ""))
    if not path:
        return False

    payload = {
        "format": 1,
        "producer": "expanse",
        "pid": os.getpid(),
        "generation": int(handoff.get("generation", -1)),
        "query": str(handoff.get("query", "")),
        "filters": list(handoff.get("filters", [])),
        "results": list(SEARCHPATHRESULTS if results is None else results),
        "done": bool(handoff.get("done", False) if done is None else done),
        "error": str(handoff.get("error", "") if error is None else (error or "")),
        "updated": time.time(),
    }
    temporary = f"{path}.tmp-{os.getpid()}"

    try:
        os.makedirs(SEARCHHANDOFFROOT, mode=0o700, exist_ok=True)
        with open(temporary, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        handoff["written"] = now
        handoff["done"] = payload["done"]
        handoff["error"] = payload["error"]
        return True
    except Exception as writeerror:
        log(f"search handoff write error {writeerror}")
        try:
            if os.path.exists(temporary):
                os.remove(temporary)
        except Exception:
            pass
        return False


def createsearchhandoff(querytext):

    global SEARCHHANDOFF

    try:
        os.makedirs(SEARCHHANDOFFROOT, mode=0o700, exist_ok=True)
        name = f"search-{os.getpid()}-{SEARCHQUERYGENERATION}-{time.monotonic_ns()}.json"
        path = os.path.join(SEARCHHANDOFFROOT, name)
        SEARCHHANDOFF = {
            "path": path,
            "query": str(querytext),
            "filters": sorted(str(value) for value in SEARCHFILTERS),
            "generation": int(SEARCHQUERYGENERATION),
            "written": 0.0,
            "done": False,
            "error": "",
        }
        done = bool(SEARCHCOMPLETE)
        writesearchhandoff(done=done, force=True)
        SEARCHHANDOFFWAKE.set()
        return path
    except Exception as error:
        SEARCHHANDOFF = None
        log(f"search handoff create error {error}")
        return None


def searchqueryworker():

    while True:

        request = SEARCHQUERYQUEUE.get()
        if request is None:
            return

        generation, querytext, scopes = request

        try:
            terms = [term for term in str(querytext).split() if term]
            partial = []
            lastupdate = 0.0

            for record in searchiterfindnames(
                terms,
                scopes,
                kind="both",
                mode="all",
                cancelled=lambda: int(generation) != int(SEARCHQUERYGENERATION),
            ):
                partial.append(record)
                now = time.monotonic()
                if len(partial) == 1 or len(partial) % 100 == 0 or now - lastupdate >= 0.1:
                    SEARCHEVENTQUEUE.put((generation, list(partial), None, True, False))
                    lastupdate = now

                if len(partial) >= SEARCHHANDOFFLIMIT:
                    break

                if len(partial) >= SEARCHPATHLIMIT and not searchhandoffactive(generation):
                    # Keep the live iterator parked at the taskbar result cap.
                    # Array can then resume this exact traversal on handoff.
                    SEARCHEVENTQUEUE.put((generation, list(partial), None, False, False))
                    while (
                        int(generation) == int(SEARCHQUERYGENERATION)
                        and not searchhandoffactive(generation)
                    ):
                        SEARCHHANDOFFWAKE.wait(0.1)
                        SEARCHHANDOFFWAKE.clear()

                    if int(generation) != int(SEARCHQUERYGENERATION):
                        break

            if int(generation) == int(SEARCHQUERYGENERATION):
                SEARCHEVENTQUEUE.put((generation, list(partial), None, False, True))
        except Exception as error:
            SEARCHEVENTQUEUE.put((generation, [], str(error), False, True))
        finally:
            SEARCHQUERYQUEUE.task_done()


def startsearchqueryworker():

    global SEARCHWORKER

    if SEARCHWORKER is not None and SEARCHWORKER.is_alive():
        return

    SEARCHWORKER = threading.Thread(
        target=searchqueryworker,
        name="expanse-search",
        daemon=True,
    )
    SEARCHWORKER.start()


def searchquerychanged(sock):

    global SEARCHQUERYGENERATION, SEARCHPATHRESULTS, SEARCHINDEXING, SEARCHCOMPLETE
    global SEARCHRESULTS, SEARCHSELECTED, SEARCHHOVER, SEARCHSCROLL
    global SEARCHHANDOFF

    if searchhandoffactive(SEARCHQUERYGENERATION) and not SEARCHHANDOFF.get("done"):
        writesearchhandoff(done=True, error="search continuation stopped", force=True)
    SEARCHHANDOFF = None
    SEARCHQUERYGENERATION += 1
    SEARCHHANDOFFWAKE.set()
    SEARCHPATHRESULTS = []
    SEARCHSCROLL = 0
    querytext = str(SEARCHTEXT or "").strip()
    SEARCHINDEXING = bool(querytext)
    SEARCHCOMPLETE = not bool(querytext)

    try:
        while True:
            SEARCHQUERYQUEUE.get_nowait()
            SEARCHQUERYQUEUE.task_done()
    except queue.Empty:
        pass

    if not querytext:
        SEARCHRESULTS = []
        SEARCHSELECTED = -1
        SEARCHHOVER = None
        hidesearchresults(sock, focus=True)
        return

    startsearchqueryworker()
    SEARCHQUERYQUEUE.put((SEARCHQUERYGENERATION, querytext, searchscopes()))
    refreshsearch(sock)


def searchpump(sock):

    global SEARCHPATHRESULTS, SEARCHINDEXING, SEARCHCOMPLETE

    changed = False
    latesterror = None

    while True:
        try:
            generation, results, error, partial, complete = SEARCHEVENTQUEUE.get_nowait()
        except queue.Empty:
            break

        if int(generation) == int(SEARCHQUERYGENERATION):
            SEARCHPATHRESULTS = list(results or [])
            SEARCHINDEXING = bool(partial)
            SEARCHCOMPLETE = bool(complete)
            changed = True
            latesterror = error
            if error:
                log(f"search api error {error}")

    if changed and searchhandoffactive(SEARCHQUERYGENERATION):
        writesearchhandoff(
            done=SEARCHCOMPLETE,
            error=latesterror,
            force=SEARCHCOMPLETE,
        )

    if changed and SEARCHMAPPED:
        refreshsearch(sock, focus=False)


def searchresultcategory(result):

    kind = str((result or {}).get("kind", "")).strip().lower()
    if kind == "file":
        return "file"
    if kind in ("tier", "place"):
        return "tier"
    if kind == "software":
        return "software"
    return "other"


def updatesearchresults():

    global SEARCHRESULTS, SEARCHSELECTED, SEARCHHOVER, SEARCHSCROLL

    try:

        needle = str(SEARCHTEXT or "").strip().lower()
        candidates = []
        order = 0
        seenpaths = set()

        for soft in list(STARTSOFTITEMS):
            label = str(soft.get("label", soft.get("name", ""))).strip()
            if label:
                candidates.append({
                    "label": label,
                    "kind": "software",
                    "detail": "software",
                    "value": soft,
                    "order": order,
                })
                order += 1

        settingssoft = next((
            item for item in STARTSOFTITEMS
            if str(item.get("name", "")).strip().lower() == "settings"
        ), None)

        if settingssoft:
            for label, section, keywords in SEARCHSETTINGS:
                soft = dict(settingssoft)
                env = dict(soft.get("env") or {})
                env["T1OS_SETTINGS_SECTION"] = section
                env["T1OS_SETTINGS_TARGET"] = label
                soft["env"] = env
                candidates.append({
                    "label": label,
                    "kind": "setting",
                    "detail": "setting",
                    "value": soft,
                    "search": f"{label} {section} {keywords}",
                    "order": order,
                })
                order += 1

        for place in list(STARTPLACEITEMS):
            label = str(place.get("label", "")).strip()
            if label:
                path = os.path.abspath(str(place.get("path", "/")))
                seenpaths.add(path)
                candidates.append({
                    "label": label,
                    "kind": "place",
                    "detail": "tier",
                    "value": place,
                    "order": order,
                })
                order += 1

        if needle:
            for record in list(SEARCHPATHRESULTS):
                path = str(record.get("path", "")).strip()
                if not path:
                    continue
                absolute = os.path.abspath(path)
                if absolute in seenpaths:
                    continue
                seenpaths.add(absolute)
                istier = bool(record.get("is_tier"))
                candidates.append({
                    "label": os.path.basename(path.rstrip("/")) or path,
                    "kind": "tier" if istier else "file",
                    "detail": "tier" if istier else "file",
                    "value": path,
                    "order": order,
                })
                order += 1

        ranked = []

        for result in candidates:
            label = result["label"].lower()
            haystack = str(result.get("search", label)).lower()

            if SEARCHFILTERS and searchresultcategory(result) not in SEARCHFILTERS:
                continue

            if needle:
                terms = [term for term in needle.split() if term]
                if not all(term in haystack for term in terms):
                    continue
                if label == needle:
                    rank = 0
                elif label.startswith(needle):
                    rank = 1
                elif all(any(word.startswith(term) for word in haystack.split()) for term in terms):
                    rank = 2
                else:
                    rank = 3
            else:
                rank = 0

            ranked.append((rank, int(result["order"]), label, result))

        ranked.sort(key=lambda value: (value[0], value[1], value[2]))
        SEARCHRESULTS = [value[3] for value in ranked[:SEARCHMAXRESULTS]]
        SEARCHSCROLL = min(SEARCHSCROLL, searchmaxscroll())
        SEARCHSELECTED = SEARCHSCROLL if SEARCHRESULTS else -1
        SEARCHHOVER = None

    except Exception as e:

        SEARCHRESULTS = []
        SEARCHSELECTED = -1
        SEARCHHOVER = None
        SEARCHSCROLL = 0
        log(f"search results update error {e}")


def searchvisiblecount():

    return max(1, min(int(SEARCHVISIBLEMAX), len(SEARCHRESULTS)))


def searchmaxscroll():

    return max(0, len(SEARCHRESULTS) - int(SEARCHVISIBLEMAX))


def searchensureselectedvisible():

    global SEARCHSCROLL

    if SEARCHSELECTED < 0:
        return
    if SEARCHSELECTED < SEARCHSCROLL:
        SEARCHSCROLL = SEARCHSELECTED
    elif SEARCHSELECTED >= SEARCHSCROLL + int(SEARCHVISIBLEMAX):
        SEARCHSCROLL = SEARCHSELECTED - int(SEARCHVISIBLEMAX) + 1
    SEARCHSCROLL = max(0, min(SEARCHSCROLL, searchmaxscroll()))


def searchmatchspans(text):

    value = str(text or "")
    lowered = value.lower()
    spans = []
    terms = [term.strip("*?") for term in str(SEARCHTEXT or "").lower().split()]

    for term in terms:
        if not term:
            continue
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


def drawsearchresultlabel(label, x, y, rowy):

    spans = searchmatchspans(label)
    if not spans:
        drawtextttf(x, y, label, 0xEFEFEF, SEARCHFONTSIZE, fontpath=FONTPATH)
        return

    positions = []
    cursor = 0
    drawx = int(x)
    for start, end in spans:
        if start > cursor:
            segment = label[cursor:start]
            positions.append((drawx, segment, False))
            drawx += measurettffile(segment, SEARCHFONTSIZE)
        segment = label[start:end]
        positions.append((drawx, segment, True))
        drawx += measurettffile(segment, SEARCHFONTSIZE)
        cursor = end
    if cursor < len(label):
        positions.append((drawx, label[cursor:], False))

    for segmentx, segment, matched in positions:
        if matched:
            segmentw = max(1, measurettffile(segment, SEARCHFONTSIZE))
            fillbufferfile(
                SEARCHBUF,
                int(SEARCHPANELRECT[2]),
                segmentx,
                rowy + max(3, s(4, 2)),
                segmentw,
                max(1, SEARCHROWH - max(6, s(8, 4))),
                (239, 239, 239),
            )

    for segmentx, segment, matched in positions:
        drawtextttf(
            segmentx,
            y,
            segment,
            0x000000 if matched else 0xEFEFEF,
            SEARCHFONTSIZE,
            fontpath=FONTPATH,
        )


def searchpanelgeometry():

    count = searchvisiblecount()
    width = min(int(SEARCHPANELW), max(1, int(DESKTOPW)))
    availableheight = max(1, int(DESKTOPH - TASKBARH))
    resultheight = min(
        count * int(SEARCHROWH),
        max(1, availableheight - int(SEARCHFILTERH)),
    )
    height = min(int(SEARCHFILTERH) + resultheight, availableheight)

    if SEARCHRECT and len(SEARCHRECT) == 4:
        x = int(SEARCHRECT[0])
    else:
        x = int(LEFTPAD + LAUNCHW + WINDOWGAP)

    x = max(0, min(x, int(DESKTOPW - width)))
    gap = max(2, s(4, 2))
    y = max(0, int(DESKTOPH - TASKBARH - height - gap))
    return [x, y, width, height]


def findsearchresultat(x, y):

    try:

        for rx, ry, rw, rh, index in list(SEARCHRESULTRECTS):
            if rx <= int(x) < rx + rw and ry <= int(y) < ry + rh:
                return int(index)

    except Exception:
        pass

    return None


def findsearchcontrolat(x, y):

    try:
        px = int(x)
        py = int(y)

        if SEARCHOPENARRAYRECT:
            rx, ry, rw, rh = SEARCHOPENARRAYRECT
            if rx <= px < rx + rw and ry <= py < ry + rh:
                return "open-array"

        for rx, ry, rw, rh, category in list(SEARCHFILTERRECTS):
            if rx <= px < rx + rw and ry <= py < ry + rh:
                return str(category)
    except Exception:
        pass

    return None


def paintsearch(sock):

    global SEARCHRESULTRECTS, SEARCHFILTERRECTS, SEARCHOPENARRAYRECT

    try:

        if SEARCHID is None or SEARCHBUF is None or not SEARCHPANELRECT:
            return

        _, _, width, height = SEARCHPANELRECT
        width = int(width)
        height = int(height)
        initbuffer(SEARCHBUF, width, height)
        clear((0, 0, 0))
        SEARCHRESULTRECTS = []
        SEARCHFILTERRECTS = []
        SEARCHOPENARRAYRECT = None

        # Match Array's compact column-header treatment: text-only controls,
        # muted while inactive and bright while selected.
        filtery = 0
        filterh = min(int(SEARCHFILTERH), height)
        arroww = filterh
        filtersright = max(0, width - arroww)
        filterx = 0
        texty = textbaseliney(filtery, filterh, SEARCHFONTSIZE)

        for category in ("file", "tier", "software", "other"):
            labelw = measurettffile(category, SEARCHFONTSIZE)
            controlw = max(s(24, 12), labelw + (SEARCHPAD * 2))
            if filterx + controlw > filtersright:
                break
            drawtextttf(
                filterx + SEARCHPAD,
                texty,
                category,
                0xEFEFEF if category in SEARCHFILTERS else 0x6A6A6A,
                SEARCHFONTSIZE,
                fontpath=FONTPATH,
            )
            SEARCHFILTERRECTS.append([
                filterx,
                filtery,
                controlw,
                filterh,
                category,
            ])
            filterx += controlw

        arrowx = max(0, width - arroww)
        SEARCHOPENARRAYRECT = [arrowx, filtery, arroww, filterh]
        drawline(arrowx, filtery + s(3, 1), arrowx, filtery + filterh - s(3, 1), (106, 106, 106))
        arrowsize = max(s(8, 4), min(s(12, 6), filterh - s(8, 4)))
        ax1 = arrowx + max(1, (arroww - arrowsize) // 2)
        ay1 = filtery + filterh - max(1, (filterh - arrowsize) // 2) - 1
        ax2 = ax1 + arrowsize
        ay2 = ay1 - arrowsize
        drawline(ax1, ay1, ax2, ay2, (239, 239, 239))
        drawline(ax2 - max(2, arrowsize // 3), ay2, ax2, ay2, (239, 239, 239))
        drawline(ax2, ay2, ax2, ay2 + max(2, arrowsize // 3), (239, 239, 239))

        active = SEARCHHOVER if SEARCHHOVER is not None else SEARCHSELECTED

        if not SEARCHRESULTS:
            label = "searching…" if SEARCHINDEXING else "no results"
            drawtextttf(
                SEARCHPAD,
                textbaseliney(filterh, SEARCHROWH, SEARCHFONTSIZE),
                label,
                0x6A6A6A,
                SEARCHFONTSIZE,
                fontpath=FONTPATH,
            )
        else:
            y = filterh
            start = max(0, min(int(SEARCHSCROLL), searchmaxscroll()))
            stop = min(len(SEARCHRESULTS), start + int(SEARCHVISIBLEMAX))
            for index in range(start, stop):
                result = SEARCHRESULTS[index]
                if index == active:
                    fillbufferfile(
                        SEARCHBUF,
                        width,
                        0,
                        y,
                        width,
                        SEARCHROWH,
                        (36, 36, 36),
                    )
                    fillbufferfile(SEARCHBUF, width, 0, y, width, 1, (58, 58, 58))
                    fillbufferfile(
                        SEARCHBUF,
                        width,
                        0,
                        y + SEARCHROWH - 1,
                        width,
                        1,
                        (58, 58, 58),
                    )

                label = searchresultfittext(
                    result.get("label", ""),
                    max(1, width - (SEARCHPAD * 2) - s(100, 50)),
                    SEARCHFONTSIZE,
                )
                detail = str(result.get("detail", ""))
                ty = textbaseliney(y, SEARCHROWH, SEARCHFONTSIZE)
                drawsearchresultlabel(label, SEARCHPAD, ty, y)
                detailw = measurettffile(detail, SEARCHFONTSIZE)
                drawtextttf(
                    max(SEARCHPAD, width - SEARCHPAD - detailw),
                    ty,
                    detail,
                    0x6A6A6A,
                    SEARCHFONTSIZE,
                    fontpath=FONTPATH,
                )
                SEARCHRESULTRECTS.append([0, y, width, SEARCHROWH, index])
                y += SEARCHROWH

        # Array-style divider around the black result surface.
        drawrect(0, 0, width, height, (58, 58, 58))
        present()
        graphicsupdategeometry("search", width, height, SEARCHBUF)
        graphicscpudamage(sock, "search", [0, 0, width, height])
        graphicspresent(sock, "search", [0, 0, width, height])

    except Exception as e:

        log(f"search paint error {e}")


def refreshsearch(sock, focus=True):

    global SEARCHPANELRECT

    try:

        updatesearchresults()
        SEARCHPANELRECT = searchpanelgeometry()

        if SEARCHID is None:
            return

        x, y, width, height = SEARCHPANELRECT
        sendline(sock, {"op": "RESIZE", "winid": SEARCHID, "w": width, "h": height})
        sendline(sock, {"op": "MOVE", "winid": SEARCHID, "x": x, "y": y})
        graphicsupdategeometry("search", width, height, SEARCHBUF)
        paintsearch(sock)

        if SEARCHMAPPED:
            sendline(sock, {"op": "RAISE", "winid": SEARCHID})
            if focus:
                sendline(sock, {"op": "FOCUS_SET", "winid": SEARCHID})

    except Exception as e:

        log(f"search refresh error {e}")


def hidesearchresults(sock, focus=False):

    global SEARCHMAPPED, SEARCHPANELRECT, SEARCHRESULTRECTS
    global SEARCHFILTERRECTS, SEARCHOPENARRAYRECT

    oldrect = SEARCHPANELRECT

    if SEARCHMAPPED and SEARCHID is not None:
        graphicssuspend(sock, "search")
        sendline(sock, {"op": "UNMAP", "winid": SEARCHID})

    SEARCHMAPPED = False
    SEARCHPANELRECT = None
    SEARCHRESULTRECTS = []
    SEARCHFILTERRECTS = []
    SEARCHOPENARRAYRECT = None

    if oldrect:
        sendline(sock, {"op": "OVERLAY_DAMAGE", "rect": oldrect})

    if focus and SEARCHINPUTFOCUSED and TASKBARID is not None:
        sendline(sock, {"op": "FOCUS_SET", "winid": TASKBARID})

    if TASKBARID is not None and TASKBARBUF is not None:
        painttaskbar(sock)


def focussearchinput(sock):

    global SEARCHINPUTFOCUSED

    SEARCHINPUTFOCUSED = True
    resetsearchcaret()
    closestartmenu(sock)
    closeinstancelist(sock)
    closetaskmenu(sock)
    hidevolumebar(sock)

    if not str(SEARCHTEXT or "").strip():
        hidesearchresults(sock, focus=False)

    if TASKBARID is not None:
        sendline(sock, {"op": "FOCUS_SET", "winid": TASKBARID})

    if TASKBARBUF is not None:
        painttaskbar(sock)


def showsearch(sock):

    global SEARCHPENDING, SEARCHPANELRECT, SEARCHINPUTFOCUSED

    try:

        SEARCHINPUTFOCUSED = True
        resetsearchcaret()

        if not str(SEARCHTEXT or "").strip():
            focussearchinput(sock)
            return

        closestartmenu(sock)
        closeinstancelist(sock)
        closetaskmenu(sock)
        hidevolumebar(sock)
        updatesearchresults()
        SEARCHPANELRECT = searchpanelgeometry()
        x, y, width, height = SEARCHPANELRECT

        if SEARCHID is None:
            if SEARCHPENDING:
                return
            SEARCHPENDING = True
            sendline(sock, {
                "op": "CREATE_WINDOW",
                "w": width,
                "h": height,
                "x": x,
                "y": y,
                "title": "search",
                "role": "search",
            })
            return

        sendline(sock, {"op": "RESIZE", "winid": SEARCHID, "w": width, "h": height})
        sendline(sock, {"op": "MOVE", "winid": SEARCHID, "x": x, "y": y})
        graphicsupdategeometry("search", width, height, SEARCHBUF)
        paintsearch(sock)

        if not SEARCHMAPPED:
            sendline(sock, {"op": "MAP", "winid": SEARCHID})
            globals()["SEARCHMAPPED"] = True

        sendline(sock, {"op": "RAISE", "winid": SEARCHID})
        sendline(sock, {"op": "FOCUS_SET", "winid": SEARCHID})
        painttaskbar(sock)

    except Exception as e:

        SEARCHPENDING = False
        log(f"show search error {e}")


def closesearch(sock, repaint=True, preservesearch=False):

    global SEARCHMAPPED, SEARCHPANELRECT, SEARCHRESULTRECTS
    global SEARCHFILTERRECTS, SEARCHOPENARRAYRECT, SEARCHFILTERS
    global SEARCHTEXT, SEARCHCARETPOS, SEARCHRESULTS, SEARCHSELECTED, SEARCHHOVER
    global SEARCHQUERYGENERATION, SEARCHPATHRESULTS, SEARCHINDEXING, SEARCHCOMPLETE
    global SEARCHHANDOFF
    global SEARCHINPUTFOCUSED, SEARCHSCROLL, SEARCHCARETSTATE

    try:

        oldrect = SEARCHPANELRECT
        if SEARCHMAPPED and SEARCHID is not None:
            graphicssuspend(sock, "search")
            sendline(sock, {"op": "UNMAP", "winid": SEARCHID})
        SEARCHMAPPED = False
        SEARCHPANELRECT = None
        SEARCHRESULTRECTS = []
        SEARCHFILTERRECTS = []
        SEARCHOPENARRAYRECT = None
        SEARCHFILTERS = set()
        SEARCHTEXT = ""
        SEARCHCARETPOS = 0
        SEARCHRESULTS = []
        SEARCHSELECTED = 0
        SEARCHHOVER = None
        SEARCHSCROLL = 0
        SEARCHINPUTFOCUSED = False
        SEARCHCARETSTATE = None
        if not preservesearch:
            if searchhandoffactive(SEARCHQUERYGENERATION) and not SEARCHHANDOFF.get("done"):
                writesearchhandoff(done=True, error="search continuation stopped", force=True)
            SEARCHHANDOFF = None
            SEARCHQUERYGENERATION += 1
            SEARCHHANDOFFWAKE.set()
            SEARCHPATHRESULTS = []
            SEARCHINDEXING = False
            SEARCHCOMPLETE = True

        if oldrect:
            sendline(sock, {"op": "OVERLAY_DAMAGE", "rect": oldrect})
        if repaint and TASKBARID is not None and TASKBARBUF is not None:
            painttaskbar(sock)

    except Exception as e:

        log(f"close search error {e}")


def togglesearchfilter(sock, category):

    global SEARCHFILTERS

    category = str(category or "").strip().lower()
    if category not in ("file", "tier", "software", "other"):
        return

    selected = set(SEARCHFILTERS)
    if category in selected:
        selected.remove(category)
    else:
        selected.add(category)
    SEARCHFILTERS = selected
    refreshsearch(sock, focus=False)


def opensearchinarray(sock):

    querytext = str(SEARCHTEXT or "").strip()
    if not querytext:
        return

    sessionpath = createsearchhandoff(querytext)
    closesearch(sock, preservesearch=bool(sessionpath))
    launchsoftware({
        "label": "array",
        "name": "array",
        "path": "/the one/build/array/array.py",
        "args": ["--search-session", sessionpath, querytext] if sessionpath else ["--search", querytext],
    })


def activatesearchresult(sock, index=None):

    try:

        if index is None:
            index = SEARCHHOVER if SEARCHHOVER is not None else SEARCHSELECTED
        index = int(index)
        if index < 0 or index >= len(SEARCHRESULTS):
            return

        result = SEARCHRESULTS[index]
        kind = str(result.get("kind", ""))
        value = result.get("value")
        closesearch(sock)

        if kind == "software":
            launchsoftware(value)
        elif kind == "setting":
            launchsoftware(value)
        elif kind == "place":
            launchsoftware({
                "label": "array",
                "name": "array",
                "path": "/the one/build/array/array.py",
                "args": ["--open-item", value.get("path", "/")],
            })
        elif kind == "tier":
            launchsoftware({
                "label": "array",
                "name": "array",
                "path": "/the one/build/array/array.py",
                "args": ["--open-item", value],
            })
        elif kind == "file":
            launchsoftware({
                "label": "array",
                "name": "array",
                "path": "/the one/build/array/array.py",
                "args": ["--open-item", value],
            })
    except Exception as e:

        log(f"search result activation error {e}")


def handlesearchkey(sock, msg):

    global SEARCHTEXT, SEARCHCARETPOS, SEARCHSELECTED, SEARCHHOVER

    try:

        wid = int(msg.get("winid", 0))

        if STARTID is not None and wid == int(STARTID) and STARTWANTED:
            key = str(msg.get("key", "")).upper()
            if str(msg.get("state", "down")) in ("down", "repeat") and key in ("ESC", "ESCAPE"):
                closestartmenu(sock)
            # Printable keys arrive in the following TEXT record.
            return

        searchwindow = bool(
            SEARCHMAPPED and SEARCHID is not None and wid == int(SEARCHID)
        )
        searchfield = bool(
            SEARCHINPUTFOCUSED and TASKBARID is not None and wid == int(TASKBARID)
        )

        if not searchwindow and not searchfield:
            return
        if str(msg.get("state", "down")) not in ("down", "repeat"):
            return

        key = str(msg.get("key", "")).upper()
        resetsearchcaret()

        if key in ("ESC", "ESCAPE"):
            closesearch(sock)
            return
        if key in ("ENTER", "RETURN"):
            activatesearchresult(sock)
            return
        if key == "UP" and SEARCHRESULTS:
            SEARCHHOVER = None
            SEARCHSELECTED = (max(0, SEARCHSELECTED) - 1) % len(SEARCHRESULTS)
            searchensureselectedvisible()
            paintsearch(sock)
            return
        if key == "DOWN" and SEARCHRESULTS:
            SEARCHHOVER = None
            SEARCHSELECTED = (max(-1, SEARCHSELECTED) + 1) % len(SEARCHRESULTS)
            searchensureselectedvisible()
            paintsearch(sock)
            return
        if key == "HOME":
            SEARCHCARETPOS = 0
        elif key == "END":
            SEARCHCARETPOS = len(SEARCHTEXT)
        elif key == "LEFT":
            SEARCHCARETPOS = max(0, SEARCHCARETPOS - 1)
        elif key == "RIGHT":
            SEARCHCARETPOS = min(len(SEARCHTEXT), SEARCHCARETPOS + 1)
        elif key in ("BACKSPACE", "BKSP") and SEARCHCARETPOS > 0:
            SEARCHTEXT = SEARCHTEXT[:SEARCHCARETPOS - 1] + SEARCHTEXT[SEARCHCARETPOS:]
            SEARCHCARETPOS -= 1
            searchquerychanged(sock)
        elif key in ("DELETE", "DEL") and SEARCHCARETPOS < len(SEARCHTEXT):
            SEARCHTEXT = SEARCHTEXT[:SEARCHCARETPOS] + SEARCHTEXT[SEARCHCARETPOS + 1:]
            searchquerychanged(sock)
        else:
            return

        painttaskbar(sock)

    except Exception as e:

        log(f"search key error {e}")


def handlesearchtext(sock, msg):

    global SEARCHTEXT, SEARCHCARETPOS

    try:

        wid = int(msg.get("winid", 0))
        fromstart = bool(
            STARTID is not None
            and wid == int(STARTID)
            and (STARTWANTED or SEARCHPENDING or SEARCHMAPPED)
        )
        fromfield = bool(
            SEARCHINPUTFOCUSED
            and TASKBARID is not None
            and wid == int(TASKBARID)
        )

        if not fromstart and not fromfield and (
            not SEARCHMAPPED or SEARCHID is None or wid != int(SEARCHID)
        ):
            return
        value = str(msg.get("text", ""))
        if not value:
            return
        value = "".join(ch for ch in value if ch >= " " and ch != "\x7f")
        if not value:
            return

        if fromstart and STARTWANTED:
            closestartmenu(sock)

        SEARCHTEXT = SEARCHTEXT[:SEARCHCARETPOS] + value + SEARCHTEXT[SEARCHCARETPOS:]
        SEARCHCARETPOS += len(value)
        resetsearchcaret()
        searchquerychanged(sock)

        if fromstart or fromfield:
            showsearch(sock)

        painttaskbar(sock)

    except Exception as e:

        log(f"search text error {e}")


def handlesearchscroll(sock, msg):

    global SEARCHSCROLL, SEARCHSELECTED, SEARCHHOVER

    try:
        wid = int(msg.get("winid", 0))
        overresults = SEARCHID is not None and wid == int(SEARCHID) and SEARCHMAPPED
        overfield = TASKBARID is not None and wid == int(TASKBARID) and SEARCHINPUTFOCUSED
        if not overresults and not overfield:
            return

        delta = int(msg.get("dy", 0))
        if not delta or len(SEARCHRESULTS) <= int(SEARCHVISIBLEMAX):
            return

        previous = SEARCHSCROLL
        SEARCHSCROLL += -1 if delta > 0 else 1
        SEARCHSCROLL = max(0, min(SEARCHSCROLL, searchmaxscroll()))
        if SEARCHSCROLL != previous:
            SEARCHHOVER = None
            if not (
                SEARCHSCROLL <= SEARCHSELECTED
                < SEARCHSCROLL + int(SEARCHVISIBLEMAX)
            ):
                SEARCHSELECTED = SEARCHSCROLL
            paintsearch(sock)

    except Exception as e:
        log(f"search scroll error {e}")


# task menu functions
def searchresultpath(result):

    try:
        kind = str((result or {}).get("kind", "")).strip().lower()
        value = (result or {}).get("value")
        if kind == "place" and isinstance(value, dict):
            return os.path.abspath(str(value.get("path", "/")))
        if kind in ("tier", "file"):
            return os.path.abspath(str(value))
    except Exception:
        pass

    return None


def searchcontextmenuitems(result):

    path = searchresultpath(result)
    if path is None:
        return [{"label": "open", "action": "open"}]

    isfolder = os.path.isdir(path)
    isfile = os.path.isfile(path)
    isopenable = isfolder
    isrunable = False

    if isfile:
        extension = os.path.splitext(path.lower())[1]
        text = {
            ".txt", ".md", ".log", ".csv", ".json", ".toml", ".ini",
            ".cfg", ".conf", ".yaml", ".yml", ".xml", ".html", ".css",
            ".js", ".jsx", ".ts", ".tsx",
        }
        audio = {".mp3", ".flac", ".wav", ".ogg", ".opus", ".m4a", ".aac", ".wma"}
        try:
            isrunable = extension == ".py" or bool(os.stat(path).st_mode & 0o111)
        except Exception:
            isrunable = extension == ".py"
        isopenable = isrunable or extension in text or extension in audio

    items = []
    if isopenable:
        items.append({"label": "open", "action": "open"})
    if isfolder:
        items.extend([
            {"label": "open in a new window", "action": "opennew"},
            {"label": "pin to sidebar", "action": "sidebarpin"},
            {"label": "new file", "action": "newfile"},
            {"label": "new tier", "action": "newtier"},
        ])

        try:
            clipboardok, clipboard = exmeta()
            if (
                clipboardok
                and str(clipboard.get("type", "")) == "files"
                and int(clipboard.get("bytes", 0)) > 0
            ):
                items.append({"label": "paste", "action": "paste"})
        except Exception:
            pass

    items.extend([
        {"label": "copy", "action": "copy"},
        {"label": "copy as path", "action": "copypath"},
        {"label": "cut", "action": "cut"},
        {"label": "rename", "action": "rename"},
    ])
    rubbishroot = os.path.abspath("/.rubbish")
    try:
        inrubbish = os.path.commonpath((path, rubbishroot)) == rubbishroot
    except Exception:
        inrubbish = False
    if inrubbish:
        if path != rubbishroot:
            items.append({"label": "restore", "action": "restore"})
    else:
        items.extend([
            {"label": "delete", "action": "delete"},
            {"label": "destroy", "action": "destroy"},
        ])
    if isrunable:
        items.append({"label": "run", "action": "run"})
    items.append({"label": "open file location", "action": "filelocation"})
    if not isfolder:
        items.append({"label": "open with...", "action": "openwith"})
        if path.lower().endswith(".zip"):
            items.append({"label": "extract all", "action": "extract"})
    items.extend([
        {"label": "create link", "action": "createlink"},
        {"label": "compress to zip", "action": "compress"},
        {"label": "properties", "action": "properties"},
    ])
    return items


def desktopcontextmenuitems(context):

    if TASKMENUDESKTOPVIEW:
        return [
            {
                "label": "show expanse",
                "action": "desktop-show",
                "checked": bool(DESKTOPSHOW),
            },
            {
                "label": "large",
                "action": "desktop-size-large",
                "checked": DESKTOPITEMSIZE == "large",
            },
            {
                "label": "medium",
                "action": "desktop-size-medium",
                "checked": DESKTOPITEMSIZE == "medium",
            },
            {
                "label": "small",
                "action": "desktop-size-small",
                "checked": DESKTOPITEMSIZE == "small",
            },
        ]

    kind = str((context or {}).get("kind", "empty"))
    target = desktopsecurepath((context or {}).get("path", DESKTOPROOT))

    if kind == "row" and target is not None:
        result = {
            "kind": "tier" if os.path.isdir(target) else "file",
            "value": target,
        }
        return [
            item for item in searchcontextmenuitems(result)
            if item.get("action") != "filelocation"
        ]

    items = [{"label": "view >", "action": "desktop-view"}]
    if target is not None and os.path.isdir(target):
        items.extend([
            {"label": "new file", "action": "newfile"},
            {"label": "new tier", "action": "newtier"},
        ])
        try:
            clipboardok, clipboard = exmeta()
            if (
                clipboardok
                and str(clipboard.get("type", "")) == "files"
                and int(clipboard.get("bytes", 0)) > 0
            ):
                items.append({"label": "paste", "action": "paste"})
        except Exception:
            pass
    items.append({"label": "settings", "action": "desktop-settings"})
    return items


def taskmenuitems():

    if TASKMENUTASKBAR:
        return [
            {
                "label": "search",
                "action": "taskbar-search",
                "checked": bool(TASKBARSEARCHVISIBLE),
            },
            {"label": "show expanse", "action": "show-expanse"},
            {"label": "settings", "action": "settings"},
            {"label": "operations centre", "action": "operations-centre"},
        ]

    if TASKMENUDESKTOP is not None:
        return desktopcontextmenuitems(TASKMENUDESKTOP)

    if TASKMENUCONTEXT is not None:
        return searchcontextmenuitems(TASKMENUCONTEXT)

    g = TASKBARGROUPITEMS.get(TASKMENUGROUP)
    if not g:
        return []

    wids = list(g.get("wids", []))
    name = str(g.get("name", "")).strip() or str(TASKMENUGROUP).strip()
    pinlabel = "unpin from taskbar" if bool(g.get("pinned")) else "pin to taskbar"
    items = [
        {"label": name, "action": "launch"},
        {"label": pinlabel, "action": "pin"},
    ]
    if wids:
        items.append({"label": "close all" if len(wids) > 1 else "close", "action": "close"})
    return items


def taskmenucompactfontsize():

    return s(12, 8)


def taskmenucompactpad():

    return s(10, 6)


def taskmenuitemheight():

    if TASKMENUCONTEXT is not None or TASKMENUTASKBAR or TASKMENUDESKTOP is not None:
        return max(s(22, 11), taskmenucompactfontsize() + s(6, 3))
    return int(TASKMENUITEMH)


def closetaskmenu(sock):

    global TASKMENUMAPPED, TASKMENURECT, TASKMENUGROUP, TASKMENUCONTEXT, TASKMENUTASKBAR
    global TASKMENUDESKTOP, TASKMENUDESKTOPVIEW
    global TASKMENUITEMRECTS, TASKMENUHOVER

    try:

        if TASKMENUID is None:
            return

        if not TASKMENUMAPPED:
            TASKMENURECT = None

            TASKMENUGROUP = None

            TASKMENUCONTEXT = None

            TASKMENUTASKBAR = False

            TASKMENUDESKTOP = None

            TASKMENUDESKTOPVIEW = False

            TASKMENUITEMRECTS = []

            TASKMENUHOVER = None

            return

        graphicssuspend(sock, "taskmenu")

        sendline(sock, {"op": "UNMAP", "winid": TASKMENUID})

        globals()["TASKMENUMAPPED"] = False

        TASKMENURECT = None

        TASKMENUGROUP = None

        TASKMENUCONTEXT = None

        TASKMENUTASKBAR = False

        TASKMENUDESKTOP = None

        TASKMENUDESKTOPVIEW = False

        TASKMENUITEMRECTS = []

        TASKMENUHOVER = None

    except Exception as e:

        log(f"closetaskmenu error {e}")


def findtaskmenuitemat(ax, ay):

    try:

        if not TASKMENURECT or len(TASKMENURECT) != 4:
            return None

        mx, my, mw, mh = TASKMENURECT

        rx = ax - mx

        ry = ay - my

        for r in list(TASKMENUITEMRECTS):

            if len(r) < 5:
                continue

            x, y, w, h, action = r

            if x <= rx < x + w and y <= ry < y + h:
                return str(action)

    except Exception as e:

        log(f"findtaskmenuitemat error {e}")

    return None


def painttaskmenu(sock):

    global TASKMENUITEMRECTS, TASKMENURECT, TASKMENUHOVER

    try:

        if TASKMENUID is None or TASKMENUBUF is None:
            return

        if (
            not TASKMENUGROUP
            and TASKMENUCONTEXT is None
            and not TASKMENUTASKBAR
            and TASKMENUDESKTOP is None
        ):
            return

        items = taskmenuitems()
        if not items:
            return

        itemheight = taskmenuitemheight()
        h = itemheight * len(items)

        w = TASKMENUW

        if TASKMENURECT and len(TASKMENURECT) == 4:

            rw = int(TASKMENURECT[2])

            rh = int(TASKMENURECT[3])

            if rw > 0:
                w = rw

            if rh > 0:
                h = rh

        initbuffer(TASKMENUBUF, w, h)

        clear((0, 0, 0))

        TASKMENUITEMRECTS = []

        y = 0

        compact = (
            TASKMENUCONTEXT is not None
            or TASKMENUTASKBAR
            or TASKMENUDESKTOP is not None
        )

        pad = taskmenucompactpad() if compact else int(TASKMENUPAD)

        fsz = taskmenucompactfontsize() if compact else int(TASKMENUFONTSIZE)

        checkboxsize = max(s(12, 6), min(itemheight - s(6, 3), s(16, 8)))

        checkboxgap = s(8, 4)

        for it in items:

            if TASKMENUHOVER == it["action"]:
                fillbufferfile(
                    TASKMENUBUF,
                    w,
                    1,
                    y,
                    max(1, w - 2),
                    itemheight,
                    (36, 36, 36) if compact else (96, 96, 96),
                )

            textx = pad

            checkcolumn = bool(
                TASKMENUDESKTOP is not None and TASKMENUDESKTOPVIEW)

            if checkcolumn:
                textx += checkboxsize + checkboxgap

            if "checked" in it:
                if TASKMENUTASKBAR:
                    checkboxx = (
                        textx
                        + measurettffile(str(it.get("label", "")), fsz)
                        + checkboxgap
                    )
                else:
                    checkboxx = pad
                checkboxy = y + (itemheight - checkboxsize) // 2
                fillbufferfile(
                    TASKMENUBUF,
                    w,
                    checkboxx,
                    checkboxy,
                    checkboxsize,
                    checkboxsize,
                    (239, 239, 239) if it.get("checked") else (0, 0, 0),
                )
                drawrect(
                    checkboxx, checkboxy, checkboxsize, checkboxsize,
                    (58, 58, 58))

                if it.get("checked"):
                    inset = max(2, checkboxsize // 4)
                    fillbufferfile(
                        TASKMENUBUF,
                        w,
                        checkboxx + inset,
                        checkboxy + inset,
                        max(1, checkboxsize - inset * 2),
                        max(1, checkboxsize - inset * 2),
                        (0, 0, 0),
                    )

            drawtextttf(
                textx,
                y + (itemheight - fsz) // 2,
                str(it["label"]),
                0xEFEFEF,
                fsz,
                fontpath=FONTPATH
            )

            TASKMENUITEMRECTS.append([0, y, w, itemheight, it["action"]])

            if compact and y + itemheight < h:
                fillbufferfile(TASKMENUBUF, w, 0, y + itemheight - 1, w, 1, (58, 58, 58))

            y += itemheight

        if compact:
            drawrect(0, 0, w, h, (58, 58, 58))

        present()

        graphicsupdategeometry("taskmenu", w, h, TASKMENUBUF)
        graphicscpudamage(sock, "taskmenu", [0, 0, int(w), int(h)])
        graphicspresent(sock, "taskmenu", [0, 0, int(w), int(h)])

    except Exception as e:

        log(f"painttaskmenu error {e}")


def showtaskmenu(sock, group, anchorrect):

    global TASKMENURECT, TASKMENUANCHOR, TASKMENUGROUP, TASKMENUCONTEXT, TASKMENUTASKBAR
    global TASKMENUDESKTOP, TASKMENUDESKTOPVIEW
    global TASKMENUPENDINGGROUP, TASKMENUPENDINGANCHOR, TASKMENUPENDINGCONTEXT, TASKMENUPENDINGTASKBAR

    try:

        if group is None:
            return

        if anchorrect is None or len(anchorrect) != 4:
            return

        closeinstancelist(sock)
        TASKMENUCONTEXT = None
        TASKMENUTASKBAR = False
        TASKMENUDESKTOP = None
        TASKMENUDESKTOPVIEW = False
        TASKMENUPENDINGCONTEXT = None
        TASKMENUPENDINGTASKBAR = False
        globals()["TASKMENUPENDINGDESKTOP"] = None
        globals()["TASKMENUHOVER"] = None

        ax, ay, aw, ah = anchorrect

        w = TASKMENUW

        items = [
            {"label": str(group).strip(), "action": "launch"},
            {"label": "pin to taskbar", "action": "pin"},
        ]

        g = TASKBARGROUPITEMS.get(group)

        if g:

            wids = list(g.get("wids", []))

            name = str(g.get("name", "")).strip()

            if not name:
                name = str(group).strip()

            pinlabel = "pin to taskbar"

            if bool(g.get("pinned")):
                pinlabel = "unpin from taskbar"

            closelabel = "close"

            if len(wids) > 1:
                closelabel = "close all"

            items = [
                {"label": name, "action": "launch"},
                {"label": pinlabel, "action": "pin"},
            ]

            if wids:
                items.append({"label": closelabel, "action": "close"})

            size = int(TASKMENUFONTSIZE)

            leftpad = int(TASKMENUPAD)

            rightpad = int(TASKMENUPAD)

            maxtextw = 0

            for it in items:

                tw = measurettffile(str(it.get("label", "")), size)

                if tw > maxtextw:
                    maxtextw = tw

            w = maxtextw + leftpad + rightpad

            if w > int(MENUMAXW):
                w = int(MENUMAXW)

            if w < (leftpad + rightpad + 1):
                w = leftpad + rightpad + 1

        h = TASKMENUITEMH * len(items)

        # center menu over the taskbar icon
        x = ax + aw // 2 - w // 2

        taskbartop = DESKTOPH - TASKBARH

        gap = max(2, int(4 * SCALE))

        y = taskbartop - h - gap

        if y < 0:
            y = ay + ah

        if x < 0:
            x = 0

        if x + w > DESKTOPW:
            x = max(0, DESKTOPW - w)

        if TASKMENUID is None:

            TASKMENUPENDINGGROUP = group

            TASKMENUPENDINGANCHOR = anchorrect

            sendline(sock, {
                "op": "CREATE_WINDOW",
                "w": w,
                "h": h,
                "x": x,
                "y": y,
                "title": "taskmenu",
                "role": "taskmenu"
            })

            return

        sendline(sock, {"op": "RESIZE", "winid": TASKMENUID, "w": w, "h": h})

        sendline(sock, {"op": "MOVE", "winid": TASKMENUID, "x": x, "y": y})

        TASKMENURECT = [x, y, w, h]

        TASKMENUANCHOR = anchorrect

        TASKMENUGROUP = group

        graphicsupdategeometry("taskmenu", w, h, TASKMENUBUF)

        painttaskmenu(sock)

        sendline(sock, {"op": "MAP", "winid": TASKMENUID})

        globals()["TASKMENUMAPPED"] = True

    except Exception as e:

        log(f"showtaskmenu error {e}")


def showsearchcontextmenu(sock, result, anchorrect):

    global TASKMENURECT, TASKMENUANCHOR, TASKMENUGROUP, TASKMENUCONTEXT, TASKMENUTASKBAR
    global TASKMENUDESKTOP, TASKMENUDESKTOPVIEW
    global TASKMENUPENDINGGROUP, TASKMENUPENDINGANCHOR, TASKMENUPENDINGCONTEXT, TASKMENUPENDINGTASKBAR

    try:
        if result is None or anchorrect is None or len(anchorrect) != 4:
            return

        closeinstancelist(sock)
        TASKMENUGROUP = None
        TASKMENUCONTEXT = dict(result)
        TASKMENUTASKBAR = False
        TASKMENUDESKTOP = None
        TASKMENUDESKTOPVIEW = False
        TASKMENUPENDINGTASKBAR = False
        globals()["TASKMENUPENDINGDESKTOP"] = None
        globals()["TASKMENUHOVER"] = None
        items = taskmenuitems()
        if not items:
            return

        pad = taskmenucompactpad()
        size = taskmenucompactfontsize()
        w = max(
            measurettffile(str(item.get("label", "")), size)
            for item in items
        ) + (pad * 2)
        w = max(pad * 2 + 1, min(w, int(MENUMAXW)))
        h = taskmenuitemheight() * len(items)

        ax, ay, _, _ = [int(value) for value in anchorrect]
        x = max(0, min(ax, int(DESKTOPW) - w))
        y = max(0, min(ay, int(DESKTOPH) - h))

        if TASKMENUID is None:
            TASKMENUPENDINGGROUP = None
            TASKMENUPENDINGANCHOR = list(anchorrect)
            TASKMENUPENDINGCONTEXT = dict(result)
            sendline(sock, {
                "op": "CREATE_WINDOW",
                "w": w,
                "h": h,
                "x": x,
                "y": y,
                "title": "taskmenu",
                "role": "taskmenu",
            })
            return

        sendline(sock, {"op": "RESIZE", "winid": TASKMENUID, "w": w, "h": h})
        sendline(sock, {"op": "MOVE", "winid": TASKMENUID, "x": x, "y": y})
        TASKMENURECT = [x, y, w, h]
        TASKMENUANCHOR = list(anchorrect)
        graphicsupdategeometry("taskmenu", w, h, TASKMENUBUF)
        painttaskmenu(sock)
        sendline(sock, {"op": "MAP", "winid": TASKMENUID})
        globals()["TASKMENUMAPPED"] = True

    except Exception as e:
        log(f"show search context menu error {e}")


def showtaskbarcontextmenu(sock, anchorrect):

    global TASKMENURECT, TASKMENUANCHOR, TASKMENUGROUP, TASKMENUCONTEXT, TASKMENUTASKBAR
    global TASKMENUDESKTOP, TASKMENUDESKTOPVIEW
    global TASKMENUPENDINGGROUP, TASKMENUPENDINGANCHOR, TASKMENUPENDINGCONTEXT, TASKMENUPENDINGTASKBAR

    try:

        if anchorrect is None or len(anchorrect) != 4:
            return

        closeinstancelist(sock)
        TASKMENUGROUP = None
        TASKMENUCONTEXT = None
        TASKMENUTASKBAR = True
        TASKMENUDESKTOP = None
        TASKMENUDESKTOPVIEW = False
        TASKMENUPENDINGGROUP = None
        TASKMENUPENDINGCONTEXT = None
        globals()["TASKMENUPENDINGDESKTOP"] = None
        globals()["TASKMENUHOVER"] = None

        items = taskmenuitems()
        pad = taskmenucompactpad()
        size = taskmenucompactfontsize()
        itemheight = taskmenuitemheight()
        checkboxsize = max(s(12, 6), min(itemheight - s(6, 3), s(16, 8)))
        checkboxgap = s(8, 4)
        w = max(
            measurettffile(str(item.get("label", "")), size)
            + (checkboxsize + checkboxgap if "checked" in item else 0)
            for item in items
        ) + (pad * 2)
        w = max(pad * 2 + 1, min(w, int(MENUMAXW)))
        h = itemheight * len(items)

        ax, ay, _, _ = [int(value) for value in anchorrect]
        x = max(0, min(ax, int(DESKTOPW) - w))
        y = max(0, min(ay - h, int(DESKTOPH) - h))

        if TASKMENUID is None:
            TASKMENUPENDINGANCHOR = list(anchorrect)
            TASKMENUPENDINGTASKBAR = True
            sendline(sock, {
                "op": "CREATE_WINDOW",
                "w": w,
                "h": h,
                "x": x,
                "y": y,
                "title": "taskmenu",
                "role": "taskmenu",
            })
            return

        TASKMENUPENDINGTASKBAR = False
        sendline(sock, {"op": "RESIZE", "winid": TASKMENUID, "w": w, "h": h})
        sendline(sock, {"op": "MOVE", "winid": TASKMENUID, "x": x, "y": y})
        TASKMENURECT = [x, y, w, h]
        TASKMENUANCHOR = list(anchorrect)
        graphicsupdategeometry("taskmenu", w, h, TASKMENUBUF)
        painttaskmenu(sock)
        sendline(sock, {"op": "MAP", "winid": TASKMENUID})
        globals()["TASKMENUMAPPED"] = True

    except Exception as e:

        log(f"show taskbar context menu error {e}")


def showdesktopcontextmenu(sock, context, anchorrect, view=False):

    global TASKMENURECT, TASKMENUANCHOR, TASKMENUGROUP, TASKMENUCONTEXT, TASKMENUTASKBAR
    global TASKMENUDESKTOP, TASKMENUDESKTOPVIEW, TASKMENUPENDINGDESKTOP
    global TASKMENUPENDINGGROUP, TASKMENUPENDINGANCHOR, TASKMENUPENDINGCONTEXT, TASKMENUPENDINGTASKBAR

    try:
        if context is None or anchorrect is None or len(anchorrect) != 4:
            return

        closeinstancelist(sock)
        TASKMENUGROUP = None
        TASKMENUCONTEXT = None
        TASKMENUTASKBAR = False
        TASKMENUDESKTOP = dict(context)
        TASKMENUDESKTOPVIEW = bool(view)
        TASKMENUPENDINGGROUP = None
        TASKMENUPENDINGCONTEXT = None
        TASKMENUPENDINGTASKBAR = False
        globals()["TASKMENUHOVER"] = None

        items = taskmenuitems()
        if not items:
            return

        pad = taskmenucompactpad()
        size = taskmenucompactfontsize()
        itemheight = taskmenuitemheight()
        checkboxsize = max(s(12, 6), min(itemheight - s(6, 3), s(16, 8)))
        checkboxgap = s(8, 4)
        checkcolumn = bool(TASKMENUDESKTOPVIEW)
        w = max(
            measurettffile(str(item.get("label", "")), size)
            for item in items
        ) + (pad * 2)
        if checkcolumn:
            w += checkboxsize + checkboxgap
        w = max(pad * 2 + 1, min(w, int(MENUMAXW)))
        h = itemheight * len(items)

        ax, ay, _, _ = [int(value) for value in anchorrect]
        x = max(0, min(ax, int(DESKTOPW) - w))
        y = max(0, min(ay, int(DESKTOPH - TASKBARH) - h))

        if TASKMENUID is None:
            TASKMENUPENDINGANCHOR = list(anchorrect)
            TASKMENUPENDINGDESKTOP = {
                "context": dict(context),
                "view": bool(view),
            }
            sendline(sock, {
                "op": "CREATE_WINDOW",
                "w": w,
                "h": h,
                "x": x,
                "y": y,
                "title": "taskmenu",
                "role": "taskmenu",
            })
            return

        TASKMENUPENDINGDESKTOP = None
        sendline(sock, {"op": "RESIZE", "winid": TASKMENUID, "w": w, "h": h})
        sendline(sock, {"op": "MOVE", "winid": TASKMENUID, "x": x, "y": y})
        TASKMENURECT = [x, y, w, h]
        TASKMENUANCHOR = list(anchorrect)
        graphicsupdategeometry("taskmenu", w, h, TASKMENUBUF)
        painttaskmenu(sock)
        sendline(sock, {"op": "MAP", "winid": TASKMENUID})
        globals()["TASKMENUMAPPED"] = True

    except Exception as error:
        log(f"show desktop context menu error {error}")


def launcharrayopen(path):

    target = desktopsecurepath(path)
    if target is None:
        return False
    launchsoftware({
        "label": "array",
        "name": "array",
        "path": "/the one/build/array/array.py",
        "args": ["--open-item", target],
    })
    return True


def launcharraycontext(action, path):

    target = desktopsecurepath(path)
    if target is None:
        return False
    launchsoftware({
        "label": "array",
        "name": "array",
        "path": "/the one/build/array/array.py",
        "args": ["--context-action", str(action), target],
    })
    return True


def rundesktopcontextaction(sock, context, action):

    action = str(action or "").strip().lower()
    target = desktopsecurepath((context or {}).get("path", DESKTOPROOT))

    if action == "desktop-show":
        globals()["DESKTOPSHOW"] = not bool(DESKTOPSHOW)
        savedesktopsettings()
        desktoprefresh(sock, force=True)
        return

    if action.startswith("desktop-size-"):
        size = action.removeprefix("desktop-size-")
        if size in ("large", "medium", "small"):
            globals()["DESKTOPITEMSIZE"] = size
            savedesktopsettings()
            desktoplayout()
            if DESKTOPID is not None and DESKTOPBUF is not None:
                paintdesktop(sock)
        return

    if action == "desktop-settings":
        launchstartsoftware("settings")
        return

    if action == "newfile":
        desktopstartcreate(sock, "file")
        return

    if action == "newtier":
        desktopstartcreate(sock, "tier")
        return

    if target is None:
        return

    if action == "rename":
        desktopstartrename(sock, target)
        return

    if action == "open":
        launcharrayopen(target)
        return

    launcharraycontext(action, target)


def desktopactivate(path):

    return launcharrayopen(path)


def desktoptoggleexpanded(sock, path):

    target = desktopsecurepath(path)
    if target is None or not os.path.isdir(target):
        return
    if target in DESKTOPEXPANDED:
        DESKTOPEXPANDED.remove(target)
    else:
        DESKTOPEXPANDED.add(target)
    savedesktopsettings()
    desktoprefresh(sock, force=True)


def launchstartsoftware(name):

    wanted = str(name or "").strip().lower()

    for software in STARTSOFTITEMS:

        if str(software.get("name", software.get("label", ""))).strip().lower() == wanted:
            launchsoftware(software)
            return True

    log(f"taskbar context software not found {wanted}")
    return False


def runtaskbarcontextaction(sock, action):

    action = str(action or "").strip().lower()

    if action == "taskbar-search":
        globals()["TASKBARSEARCHVISIBLE"] = not bool(TASKBARSEARCHVISIBLE)

        if not TASKBARSEARCHVISIBLE:
            closesearch(sock)

        savetaskbarsettings()

        if TASKBARID is not None and TASKBARBUF is not None:
            painttaskbar(sock)
        return

    if action == "show-expanse":
        showdesktop(sock)
        return

    if action == "settings":
        launchstartsoftware("settings")
        return

    if action == "operations-centre":
        launchstartsoftware("operations centre")


def runsearchcontextaction(sock, result, action):

    try:
        action = str(action or "").strip().lower()
        if action == "open":
            try:
                index = SEARCHRESULTS.index(result)
            except ValueError:
                index = None
            activatesearchresult(sock, index)
            return

        path = searchresultpath(result)
        if path is None:
            return

        closesearch(sock)
        launchsoftware({
            "label": "array",
            "name": "array",
            "path": "/the one/build/array/array.py",
            "args": ["--context-action", action, path],
        })
    except Exception as e:
        log(f"search context action error {e}")


# volume slider functions
def volumeposy(y, h):

    try:

        top = int(VOLUMETOP)

        bot = int(VOLUMEBOT)

        trackh = int(h - top - bot)

        if trackh <= 1:
            return int(CURRENTAUDIOVOL)

        yy = int(y - top)

        if yy < 0:
            yy = 0

        if yy > trackh:
            yy = trackh

        t = float(1.0 - (float(yy) / float(trackh)))

        v = int(round(t * 100.0))

        if v < 0:
            v = 0

        if v > 100:
            v = 100

        return int(v)

    except Exception:

        return int(CURRENTAUDIOVOL)


def volumevaluey(vol, h):

    try:

        top = int(VOLUMETOP)

        bot = int(VOLUMEBOT)

        trackh = int(h - top - bot)

        if trackh <= 1:
            return int(top)

        t = float(int(vol)) / 100.0

        if t < 0.0:
            t = 0.0

        if t > 1.0:
            t = 1.0

        yy = int(round((1.0 - t) * float(trackh)))

        return int(top + yy)

    except Exception:

        return int(VOLUMETOP)


def volumedisplayvalue():

    try:

        if VOLUMEDRAG and VOLUMEDRAGVOL is not None:
            return int(VOLUMEDRAGVOL)

        return int(CURRENTAUDIOVOL)

    except Exception:

        return 0


def volumedragvalue(vol):

    v = max(0, min(100, int(vol)))

    if VOLUMEDRAGVOL is None or int(VOLUMEDRAGVOL) != v:
        globals()["VOLUMEDRAGDIRTY"] = True

    globals()["VOLUMEDRAGVOL"] = v
    globals()["CURRENTAUDIOVOL"] = v
    return v


def volumeflushdrag(sock, force=False):

    if not VOLUMEDRAG or VOLUMEDRAGVOL is None:
        return False

    if not VOLUMEDRAGDIRTY and not force:
        return False

    now = time.monotonic()

    if not force and now - float(VOLUMELASTFRAME) < float(VOLUMEFRAMEINTERVAL):
        return False

    value = max(0, min(100, int(VOLUMEDRAGVOL)))
    globals()["VOLUMEDRAGDIRTY"] = False
    globals()["VOLUMELASTFRAME"] = now
    volumeset(value)
    paintvolumebar(sock)
    return True


def volumeenddrag():

    value = VOLUMEDRAGVOL

    globals()["VOLUMEDRAG"] = False
    globals()["VOLUMEDRAGVOL"] = None
    globals()["VOLUMEDRAGDIRTY"] = False

    if value is None:
        return None

    value = max(0, min(100, int(value)))
    globals()["CURRENTAUDIOVOL"] = value
    return value


def volumeset(vol):

    try:

        v = int(vol)

        if v < 0:
            v = 0

        if v > 100:
            v = 100

        gain = float(v) / 100.0

        audiosend(AUDIO_MSGVOLUME, {"gain": float(gain)})

    except Exception as e:

        log(f"volumeset error {e}")


def volumebarbegin():

    global VOLUMEBUF

    if VOLUMEBUF is None or fillbufferfile is None:
        return None, None

    realbuf = VOLUMEBUF

    tmpbuf = surfacestagingpath("volumebar")

    try:

        with open(tmpbuf, "wb") as f:

            f.truncate(int(VOLUMEW) * int(VOLUMEH) * 4)

    except Exception as e:

        log(f"volumebar tmp prepare error {e}")

        return None, None

    VOLUMEBUF = tmpbuf

    return realbuf, tmpbuf


def volumebarcommit(sock, realbuf, tmpbuf):

    try:

        try:

            commitcpusurface(
                tmpbuf,
                realbuf,
                int(VOLUMEW) * int(VOLUMEH) * 4,
            )

        except Exception as e:

            log(f"volumebar tmp commit error {e}")
            return False

        globals()["VOLUMEBUF"] = realbuf

        graphicsupdategeometry("volumebar", VOLUMEW, VOLUMEH, realbuf)
        graphicscpudamage(sock, "volumebar", [0, 0, int(VOLUMEW), int(VOLUMEH)])
        graphicspresent(sock, "volumebar", [0, 0, int(VOLUMEW), int(VOLUMEH)])
        return True

    except Exception as e:

        log(f"volumebar commit error {e}")
        return False


def volumebarcleanup(realbuf, tmpbuf, committed):

    try:

        if realbuf is not None:
            globals()["VOLUMEBUF"] = realbuf

        if tmpbuf and tmpbuf != realbuf and os.path.exists(tmpbuf):
            os.remove(tmpbuf)

    except Exception as e:

        log(f"volumebar tmp cleanup error {e}")


def paintvolumebar(sock):

    try:

        if VOLUMEID is None or VOLUMEBUF is None:
            return

        if graphicsmanagedpaint(sock, "volumebar", [0, 0, int(VOLUMEW), int(VOLUMEH)]):
            return

        realbuf, tmpbuf = volumebarbegin()

        if realbuf is None or tmpbuf is None:
            return

        committed = False

        w = int(VOLUMEW)

        h = int(VOLUMEH)

        try:

            fillbufferfile(
                VOLUMEBUF,
                w,
                0,
                0,
                w,
                h,
                (0, 0, 0)
            )

            # Audio acknowledgements can arrive between pointer events.  While
            # dragging, retain the user's requested value for both CPU and
            # managed rendering instead of repainting an older acknowledgement.
            vol = int(volumedisplayvalue())

            if vol < 0:
                vol = 0

            if vol > 100:
                vol = 100

            label = str(vol)

            tw = measurettffile(label, int(VOLUMETEXT))

            tx = int((w // 2) - (tw // 2))

            if tx < 0:
                tx = 0

            drawttffile(
                VOLUMEBUF,
                w,
                h,
                tx,
                int(VOLUMEPAD),
                label,
                0xFFFFFF,
                int(VOLUMETEXT)
            )

            top = int(VOLUMETOP)

            bot = int(VOLUMEBOT)

            trackw = int(VOLUMETRACKW)

            trackh = int(h - top - bot)

            if trackh < 8:
                trackh = 8

            cx = int(w // 2)

            x0 = int(cx - (trackw // 2))

            # track border (white)
            fillbufferfile(
                VOLUMEBUF,
                w,
                x0,
                top,
                trackw,
                trackh,
                (255, 255, 255)
            )

            # track inner (black) to make it a border
            if trackw > 2 and trackh > 2:

                fillbufferfile(
                    VOLUMEBUF,
                    w,
                    x0 + 1,
                    top + 1,
                    trackw - 2,
                    trackh - 2,
                    (0, 0, 0)
                )

            ky = volumevaluey(vol, h)

            knobw = int(VOLUMEKNOBW)

            knobh = int(VOLUMEKNOBH)

            kx = int((w // 2) - (knobw // 2))

            ky = int(ky - (knobh // 2))

            if ky < top:
                ky = top

            if ky + knobh > top + trackh:
                ky = top + trackh - knobh

            fillbufferfile(
                VOLUMEBUF,
                w,
                kx,
                ky,
                knobw,
                knobh,
                (255, 255, 255)
            )

            committed = bool(volumebarcommit(sock, realbuf, tmpbuf))

        finally:

            volumebarcleanup(realbuf, tmpbuf, committed)

    except Exception as e:

        log(f"paintvolumebar error {e}")


def showvolumebar(sock):

    global VOLUMEMAPPED, VOLUMERECT, VOLUMEPENDING

    try:

        # close hover tooltip when opening the volume slider
        if TOOLTIPMAPPED:
            clearhovertooltip(sock)

        if VOLUMEID is None or VOLUMEBUF is None:

            # Key repeat can deliver several volume changes before the window
            # server acknowledges the first CREATE_WINDOW request.  Keep one
            # pending request so later acknowledgements cannot replace the
            # tracked popup with an unmapped duplicate.
            if not VOLUMEPENDING:

                VOLUMEPENDING = True

                requestvolumebar(sock)

            return

        rect = globals().get("AUDIOICONRECT")

        if not rect or len(rect) != 4:
            return

        ax, ay, aw, ah = rect

        w = int(VOLUMEW)

        h = int(VOLUMEH)

        x = int(ax + (aw // 2) - (w // 2))

        y = int(ay - h - 6)

        if x < 0:
            x = 0

        if y < 0:
            y = 0

        VOLUMERECT = [x, y, w, h]

        sendline(sock, {"op": "RESIZE", "winid": VOLUMEID, "w": w, "h": h})

        sendline(sock, {"op": "MOVE", "winid": VOLUMEID, "x": x, "y": y})

        graphicsupdategeometry("volumebar", w, h, VOLUMEBUF)

        VOLUMEPENDING = False

        paintvolumebar(sock)

        if not VOLUMEMAPPED:

            sendline(sock, {"op": "MAP", "winid": VOLUMEID})

            VOLUMEMAPPED = True

    except Exception as e:

        log(f"showvolumebar error {e}")


def renewvolumetimeout():

    globals()["VOLUMEAUTOCLOSEAT"] = (
        time.monotonic() + float(VOLUMEAUTOCLOSEDELAY)
    )


def handlevolumehotkey(sock, msg):

    try:

        gain = max(0.0, min(1.0, float(msg.get("gain", 0.0))))
        globals()["CURRENTAUDIOVOL"] = int(round(gain * 100.0))

        if "mute" in msg:
            globals()["CURRENTAUDIOMUTE"] = bool(msg.get("mute"))

        # Every key press/repeat is activity.  Replacing the deadline makes the
        # popup close only after a full quiet period following the last change.
        renewvolumetimeout()
        showvolumebar(sock)

    except Exception as e:

        log(f"volume hotkey handler error {e}")


def handlevolumescroll(sock, msg):

    try:

        wid = int(msg.get("winid", 0))

        if (
                not VOLUMEMAPPED or
                VOLUMEID is None or
                wid != int(VOLUMEID)
        ):
            return

        delta = int(msg.get("dy", 0))

        if not delta:
            return

        current = max(0, min(100, int(volumedisplayvalue())))
        value = current + (int(VOLUMEWHEELSTEP) if delta > 0 else -int(VOLUMEWHEELSTEP))
        value = max(0, min(100, value))

        # Treat the wheel as popup activity even at either limit so the popup
        # does not close while the user is still interacting with it.
        renewvolumetimeout()

        if value == current:
            return

        globals()["CURRENTAUDIOVOL"] = value
        volumeset(value)
        paintvolumebar(sock)

    except Exception as e:

        log(f"volume scroll handler error {e}")


def updatevolumetimeout(sock):

    try:

        deadline = float(VOLUMEAUTOCLOSEAT)

        if deadline <= 0.0 or VOLUMEDRAG:
            return

        if time.monotonic() >= deadline:
            hidevolumebar(sock)

    except Exception as e:

        log(f"volume timeout error {e}")


def hidevolumebar(sock):

    global VOLUMEMAPPED, VOLUMEPENDING, VOLUMERECT

    try:

        globals()["VOLUMEAUTOCLOSEAT"] = 0.0
        VOLUMEPENDING = False

        value = volumeenddrag()

        if value is not None:
            volumeset(value)

        VOLUMERECT = None

        if VOLUMEMAPPED and VOLUMEID is not None:

            graphicssuspend(sock, "volumebar")

            sendline(sock, {"op": "UNMAP", "winid": VOLUMEID})

            VOLUMEMAPPED = False

    except Exception as e:

        log(f"hidevolumebar error {e}")


# input functions
def handledesktopmotion(sock, msg):

    x = int(msg.get("x", 0))
    y = int(msg.get("y", 0))
    item = desktopitemat(x, y)
    hover = item.get("path") if item else None

    if DESKTOPDRAGPATH is not None and DESKTOPDRAGSTART is not None:
        startx, starty = DESKTOPDRAGSTART
        if abs(x - startx) >= s(6, 4) or abs(y - starty) >= s(6, 4):
            globals()["DESKTOPDRAGACTIVE"] = True

    if hover != DESKTOPHOVER:
        globals()["DESKTOPHOVER"] = hover
        if DESKTOPBUF is not None:
            paintdesktop(sock)


def handledesktopbutton(sock, msg):

    state = str(msg.get("state", "down"))
    button = int(msg.get("button", 1))
    x = int(msg.get("x", msg.get("absx", 0)))
    y = int(msg.get("y", msg.get("absy", 0)))
    item = desktopitemat(x, y)

    if state == "down" and DESKTOPID is not None:
        sendline(sock, {"op": "FOCUS_SET", "winid": DESKTOPID})

    if state == "down" and DESKTOPCREATEACTIVE:
        desktopcancelcreate(sock)

    if button in (2, 3):
        globals()["DESKTOPDRAGPATH"] = None
        globals()["DESKTOPDRAGSTART"] = None
        globals()["DESKTOPDRAGOFFSET"] = None
        globals()["DESKTOPDRAGACTIVE"] = False
        if state == "down":
            globals()["DESKTOPSELECTED"] = item.get("path") if item else None
            if DESKTOPBUF is not None:
                paintdesktop(sock)
            return
        if state == "up":
            context = {
                "kind": "row" if item else "empty",
                "path": item.get("path") if item else DESKTOPROOT,
            }
            showdesktopcontextmenu(sock, context, [
                int(msg.get("absx", x)),
                int(msg.get("absy", y)),
                1,
                1,
            ])
        return

    if button != 1:
        return

    if state == "down":
        globals()["DESKTOPSELECTED"] = item.get("path") if item else None
        globals()["DESKTOPHOVER"] = item.get("path") if item else None
        rootitem = desktoptoplevelitem(item.get("path")) if item else None
        if (
            rootitem is not None
            and rootitem.get("path") == item.get("path")
            and not desktoparrowat(item, x, y)
        ):
            globals()["DESKTOPDRAGPATH"] = item.get("path")
            globals()["DESKTOPDRAGSTART"] = (x, y)
            rx, ry, _, _ = item.get("rect", [x, y, 0, 0])
            globals()["DESKTOPDRAGOFFSET"] = (x - rx, y - ry)
        else:
            globals()["DESKTOPDRAGPATH"] = None
            globals()["DESKTOPDRAGSTART"] = None
            globals()["DESKTOPDRAGOFFSET"] = None
        globals()["DESKTOPDRAGACTIVE"] = False
        if DESKTOPBUF is not None:
            paintdesktop(sock)
        return

    if state != "up":
        return

    dragpath = DESKTOPDRAGPATH
    dragoffset = DESKTOPDRAGOFFSET
    dragactive = bool(DESKTOPDRAGACTIVE)
    globals()["DESKTOPDRAGPATH"] = None
    globals()["DESKTOPDRAGSTART"] = None
    globals()["DESKTOPDRAGOFFSET"] = None
    globals()["DESKTOPDRAGACTIVE"] = False

    if dragpath is not None and dragactive:
        desktopmoveitem(sock, dragpath, x, y, offset=dragoffset)
        globals()["DESKTOPLASTCLICKPATH"] = None
        globals()["DESKTOPLASTCLICKAT"] = 0.0
        return

    if item is None:
        globals()["DESKTOPLASTCLICKPATH"] = None
        globals()["DESKTOPLASTCLICKAT"] = 0.0
        return

    if desktoparrowat(item, x, y):
        globals()["DESKTOPLASTCLICKPATH"] = None
        globals()["DESKTOPLASTCLICKAT"] = 0.0
        desktoptoggleexpanded(sock, item.get("path"))
        return

    now = time.monotonic()
    path = item.get("path")
    if (
        path == DESKTOPLASTCLICKPATH
        and now - float(DESKTOPLASTCLICKAT) <= float(DESKTOPDOUBLECLICK)
    ):
        globals()["DESKTOPLASTCLICKPATH"] = None
        globals()["DESKTOPLASTCLICKAT"] = 0.0
        desktopactivate(path)
        return

    globals()["DESKTOPLASTCLICKPATH"] = path
    globals()["DESKTOPLASTCLICKAT"] = now


def handledesktopkey(sock, msg):

    try:
        if DESKTOPID is None or int(msg.get("winid", 0)) != int(DESKTOPID):
            return
        if str(msg.get("state", "down")) not in ("down", "repeat"):
            return
        key = str(msg.get("key", "")).strip().upper()
        if DESKTOPCREATEACTIVE:
            if key in ("ESC", "ESCAPE"):
                desktopcancelcreate(sock)
            elif key in ("ENTER", "RETURN"):
                desktopcommitcreate(sock)
            elif key == "HOME":
                globals()["DESKTOPCREATECARETPOS"] = 0
                globals()["DESKTOPCREATESELECTION"] = None
            elif key == "END":
                globals()["DESKTOPCREATECARETPOS"] = len(DESKTOPCREATETEXT)
                globals()["DESKTOPCREATESELECTION"] = None
            elif key == "LEFT":
                selection = desktopeditselection()
                globals()["DESKTOPCREATECARETPOS"] = (
                    selection[0] if selection is not None
                    else max(0, DESKTOPCREATECARETPOS - 1)
                )
                globals()["DESKTOPCREATESELECTION"] = None
            elif key == "RIGHT":
                selection = desktopeditselection()
                globals()["DESKTOPCREATECARETPOS"] = (
                    selection[1] if selection is not None
                    else min(len(DESKTOPCREATETEXT), DESKTOPCREATECARETPOS + 1)
                )
                globals()["DESKTOPCREATESELECTION"] = None
            elif key in ("BACKSPACE", "BKSP"):
                if not desktopdeletemarkedtext() and DESKTOPCREATECARETPOS > 0:
                    position = DESKTOPCREATECARETPOS
                    globals()["DESKTOPCREATETEXT"] = (
                        DESKTOPCREATETEXT[:position - 1] + DESKTOPCREATETEXT[position:]
                    )
                    globals()["DESKTOPCREATECARETPOS"] = position - 1
                globals()["DESKTOPCREATEERROR"] = ""
            elif key in ("DELETE", "DEL"):
                if (
                    not desktopdeletemarkedtext() and
                    DESKTOPCREATECARETPOS < len(DESKTOPCREATETEXT)
                ):
                    position = DESKTOPCREATECARETPOS
                    globals()["DESKTOPCREATETEXT"] = (
                        DESKTOPCREATETEXT[:position] + DESKTOPCREATETEXT[position + 1:]
                    )
                globals()["DESKTOPCREATEERROR"] = ""
            else:
                return
            if sock is not None and DESKTOPBUF is not None and DESKTOPCREATEACTIVE:
                paintdesktop(sock)
            return
        target = desktopsecurepath(DESKTOPSELECTED)
        if target is None:
            return
        if key in ("ENTER", "RETURN", "SPACE"):
            desktopactivate(target)
        elif key in ("DELETE", "DEL"):
            launcharraycontext("delete", target)
        elif key == "F2":
            desktopstartrename(sock, target)
        elif key == "RIGHT" and os.path.isdir(target):
            if target not in DESKTOPEXPANDED:
                desktoptoggleexpanded(sock, target)
        elif key == "LEFT" and target in DESKTOPEXPANDED:
            desktoptoggleexpanded(sock, target)
    except Exception as error:
        log(f"desktop key error {error}")


def desktopinserttext(value):

    value = "".join(
        character for character in str(value or "")
        if character >= " " and character != "\x7f" and character != "/"
    )
    if not value:
        return False
    selection = desktopeditselection()
    if selection is not None:
        position = selection[0]
        candidate = (
            DESKTOPCREATETEXT[:selection[0]] + value +
            DESKTOPCREATETEXT[selection[1]:]
        )
    else:
        position = DESKTOPCREATECARETPOS
        candidate = (
            DESKTOPCREATETEXT[:position] + value + DESKTOPCREATETEXT[position:]
        )
    if len(candidate.encode("utf-8")) > 255:
        globals()["DESKTOPCREATEERROR"] = "name is too long"
        return False
    globals()["DESKTOPCREATETEXT"] = candidate
    globals()["DESKTOPCREATECARETPOS"] = position + len(value)
    globals()["DESKTOPCREATESELECTION"] = None
    globals()["DESKTOPCREATEERROR"] = ""
    return True


def handledesktoptext(sock, msg):

    try:
        if (
            not DESKTOPCREATEACTIVE or DESKTOPCREATEBUSY or
            DESKTOPID is None or int(msg.get("winid", 0)) != int(DESKTOPID)
        ):
            return
        if not desktopinserttext(msg.get("text", "")):
            return
        if sock is not None and DESKTOPBUF is not None:
            paintdesktop(sock)
    except Exception as error:
        log(f"desktop text error {error}")


def settaskbarcursor(sock, mode):

    global TASKBARCURSORMODE

    mode = "text" if str(mode) == "text" else "arrow"

    if mode == TASKBARCURSORMODE:
        return

    TASKBARCURSORMODE = mode

    if TASKBARID is not None:
        sendline(sock, {
            "op": "CURSOR_MODE_SET",
            "winid": TASKBARID,
            "mode": mode,
        })


def settaskbarwindowhover(sock, group):

    global TASKBARHOVERGROUP

    if group == TASKBARHOVERGROUP:
        return

    TASKBARHOVERGROUP = group

    if TASKBARBUF is not None:
        painttaskbar(sock)


def handlepointermotion(sock, msg):

    global HOVERPENDINGWID, HOVERPENDINGTS, HOVERPENDINGSTART, HOVERPENDINGSTARTTS, HOVERPENDINGNET, HOVERPENDINGNETTS, HOVERPENDINGCLOCK, HOVERPENDINGCLOCKTS
    global HOVERPENDINGGROUP, HOVERPENDINGGROUPTS, HOVERLISTGROUP, HOVERLISTTS, HOVERTOOLTIPGROUP, HOVERTOOLTIPTS
    global HOVERRECT, HOVERPINGTS, TOOLTIPMAPPED, LISTMAPPED, LISTGRACETS
    global LISTHOVERWID, LISTANCHOR

    try:

        try:

            wid = int(msg.get("winid", 0))

        except Exception:

            wid = 0

        if DESKTOPID is not None and wid == DESKTOPID:
            settaskbarcursor(sock, "arrow")
            settaskbarwindowhover(sock, None)
            if HOVERRECT is not None or TOOLTIPMAPPED or LISTMAPPED:
                clearhovertooltip(sock)
            handledesktopmotion(sock, msg)
            return

        try:

            if SEARCHID is not None and wid == SEARCHID:

                newhover = findsearchresultat(
                    int(msg.get("x", 0)),
                    int(msg.get("y", 0)),
                )
                if newhover != SEARCHHOVER:
                    globals()["SEARCHHOVER"] = newhover
                    paintsearch(sock)
                return

        except Exception as e:

            log(f"search motion handler error {e}")

        try:

            if VOLUMEID is not None and wid == VOLUMEID:

                if not VOLUMEMAPPED:
                    return

                if not VOLUMEDRAG:
                    return

                try:

                    ay = int(msg.get("absy", 0))

                except Exception:

                    ay = 0

                if VOLUMERECT and len(VOLUMERECT) == 4:

                    vx, vy, vw, vh = VOLUMERECT

                    y = int(ay - vy)

                else:

                    y = 0

                v = volumeposy(int(y), int(VOLUMEH))

                # Always repaint a drag frame.  CURRENTAUDIOVOL may have been
                # changed by an asynchronous audio acknowledgement without a
                # corresponding volume-bar paint.
                v = volumedragvalue(v)

                volumeflushdrag(sock)

                return

        except Exception as e:

            log(f"volumebar motion handler error {e}")

        # leaving taskbar: clear launcher hover state so logo doesn't stick muted
        if TASKBARID is not None and wid != TASKBARID:

            settaskbarcursor(sock, "arrow")

            settaskbarwindowhover(sock, None)

            if HOVERLOGO:

                globals()["HOVERLOGO"] = False

                if TASKBARBUF is not None:
                    painttaskbar(sock)

            if HOVERPENDINGSTART:
                HOVERPENDINGSTART = False

                HOVERPENDINGSTARTTS = 0.0

        # treat taskbar + hover windows as the same hover context
        if TASKBARID is not None and wid == TASKBARID:

            handletaskbarmotion(sock, msg)

            return

        if LISTID is not None and wid == LISTID:

            ax = int(msg.get("absx", 0))

            ay = int(msg.get("absy", 0))

            if LISTGROUP is not None:
                now = time.time()

                HOVERPENDINGGROUP = LISTGROUP

                HOVERPENDINGGROUPTS = now

                LISTGRACETS = now

            newhover = None

            try:

                if LISTRECT and len(LISTRECT) == 4 and LISTITEMRECTS:

                    lx, ly, lw, lh = LISTRECT

                    rx = ax - lx

                    ry = ay - ly

                    for ix, iy, iw, ih, iwid in LISTITEMRECTS:

                        if 0 <= rx < iw and iy <= ry < iy + ih:
                            newhover = iwid

                            break

            except Exception:

                newhover = None

            if newhover != LISTHOVERWID:

                LISTHOVERWID = newhover

                if LISTGROUP is not None and LISTANCHOR is not None:
                    showinstancelist(sock, LISTGROUP, LISTANCHOR)

            return

        if TOOLTIPID is not None and wid == TOOLTIPID:
            return

        # robust hover: if pointer is physically inside list/tooltip rects, do not clear
        ax = int(msg.get("absx", 0))

        ay = int(msg.get("absy", 0))

        if LISTMAPPED and LISTRECT and len(LISTRECT) == 4:

            lx, ly, lw, lh = LISTRECT

            # 1) inside list
            if lx <= ax < lx + lw and ly <= ay < ly + lh:
                return

            # 2) corridor between taskbar and list (lets the pointer travel upward)
            taskbartop = DESKTOPH - TASKBARH

            listbottom = ly + lh

            if lx <= ax < lx + lw and listbottom <= ay < taskbartop:
                LISTGRACETS = time.time()

                return

        if TOOLTIPMAPPED and HOVERRECT and len(HOVERRECT) == 4:

            tx, ty, tw, th = HOVERRECT

            if tx <= ax < tx + tw and ty <= ay < ty + th:
                return

        if LISTMAPPED:

            now = time.time()

            taskbartop = DESKTOPH - TASKBARH

            # only apply grace while we're still in the taskbar band
            if ay >= taskbartop:

                if LISTGRACETS > 0.0 and (now - LISTGRACETS) < LISTGRACE:
                    return

        # otherwise: clear taskbar hover state
        HOVERPENDINGWID = None

        HOVERPENDINGTS = 0.0

        HOVERPENDINGGROUP = None

        HOVERPENDINGGROUPTS = 0.0

        HOVERPENDINGSTART = False

        HOVERPENDINGSTARTTS = 0.0

        HOVERPENDINGNET = False

        HOVERPENDINGNETTS = 0.0

        HOVERPENDINGCLOCK = False

        HOVERPENDINGCLOCKTS = 0.0

        # allow re-show on next hover (same group included)
        HOVERLISTGROUP = None

        HOVERLISTTS = 0.0

        HOVERTOOLTIPGROUP = None

        HOVERTOOLTIPTS = 0.0

        if TASKMENUID is not None and wid == TASKMENUID:

            ax = int(msg.get("absx", 0))

            ay = int(msg.get("absy", 0))

            newhover = findtaskmenuitemat(ax, ay)

            if newhover != TASKMENUHOVER:
                globals()["TASKMENUHOVER"] = newhover

                painttaskmenu(sock)

            return

        # clear any visible hover windows (tooltip OR list)
        if HOVERRECT is not None or TOOLTIPMAPPED or LISTMAPPED:

            clearhovertooltip(sock)

    except Exception as e:

        log(f"handlepointermotion error {e}")


def handletaskbarmotion(sock, msg):

    global HOVERPENDINGWID, HOVERPENDINGTS, HOVERPENDINGSTART, HOVERPENDINGSTARTTS, HOVERPENDINGNET, HOVERPENDINGNETTS, HOVERPENDINGCLOCK, HOVERPENDINGCLOCKTS
    global HOVERPENDINGGROUP, HOVERPENDINGGROUPTS, LISTGRACETS
    global DRAGTASKGROUP, DRAGTASKACTIVE, DRAGTASKMOVED, DRAGTASKSTARTX, DRAGTASKSTARTY, DRAGTASKX, DRAGTASKY, DRAGTASKOFFSETX
    global TASKBARGROUPS, TASKBARORDER, HOVERPENDINGAUDIO, HOVERPENDINGAUDIOTS

    try:

        try:

            wid = int(msg.get("winid", 0))

        except Exception:

            wid = 0

        if TASKBARID is None:
            return

        if wid != TASKBARID:

            settaskbarcursor(sock, "arrow")

            settaskbarwindowhover(sock, None)

            if HOVERLOGO:

                globals()["HOVERLOGO"] = False

                if TASKBARBUF is not None:
                    painttaskbar(sock)

            if HOVERPENDINGWID is not None:
                HOVERPENDINGWID = None

                HOVERPENDINGTS = 0.0

            if HOVERPENDINGSTART:
                HOVERPENDINGSTART = False

                HOVERPENDINGSTARTTS = 0.0

            if HOVERPENDINGNET:
                HOVERPENDINGNET = False

                HOVERPENDINGNETTS = 0.0

            if HOVERPENDINGCLOCK:
                HOVERPENDINGCLOCK = False

                HOVERPENDINGCLOCKTS = 0.0

            return

        try:

            ax = int(msg.get("absx", 0))

            ay = int(msg.get("absy", 0))

        except Exception:

            ax = 0

            ay = 0

        if SEARCHHOVER is not None:
            globals()["SEARCHHOVER"] = None
            if SEARCHMAPPED:
                paintsearch(sock)

        try:
            searchfieldhit = False
            if SEARCHRECT and len(SEARCHRECT) == 4:
                sx, sy, sw, sh = SEARCHRECT
                searchfieldhit = sx <= ax < sx + sw and sy <= ay < sy + sh

            settaskbarcursor(sock, "text" if searchfieldhit else "arrow")

            if searchfieldhit:
                settaskbarwindowhover(sock, None)
                HOVERPENDINGGROUP = None
                HOVERPENDINGGROUPTS = 0.0
                HOVERPENDINGWID = None
                HOVERPENDINGTS = 0.0
                return
        except Exception:
            settaskbarcursor(sock, "arrow")

        # drag: track pointer + reorder while dragging
        if DRAGTASKACTIVE and DRAGTASKGROUP is not None:

            settaskbarwindowhover(sock, None)

            globals()["DRAGTASKX"] = int(ax)

            globals()["DRAGTASKY"] = int(ay)

            dx = abs(int(ax) - int(DRAGTASKSTARTX))

            dy = abs(int(ay) - int(DRAGTASKSTARTY))

            if (not DRAGTASKMOVED) and (dx >= DRAGTASKTHRESH or dy >= DRAGTASKTHRESH):
                globals()["DRAGTASKMOVED"] = True

            if DRAGTASKMOVED:

                # determine current + target slot based on pointer x vs each icon center
                curidx = None

                try:

                    if DRAGTASKGROUP in TASKBARORDER:
                        curidx = TASKBARORDER.index(DRAGTASKGROUP)

                    elif DRAGTASKGROUP in TASKBARGROUPS:
                        curidx = TASKBARGROUPS.index(DRAGTASKGROUP)

                except Exception:

                    curidx = None

                targetidx = None

                try:

                    centers = []

                    for g in list(TASKBARGROUPS):

                        r = TASKBARGROUPRECTS.get(g)

                        if not r or len(r) != 4:
                            continue

                        rx, ry, rw, rh = r

                        cx = int(rx + rw // 2)

                        centers.append([g, cx])

                    # fallback if rects not built yet
                    if centers:

                        before = 0

                        for g, cx in centers:

                            if int(ax) < int(cx):
                                break

                            before += 1

                        # "before" is the insertion index in visible order
                        targetgroup = None

                        try:

                            if before <= 0:
                                targetgroup = centers[0][0]
                                targetidx = 0

                            elif before >= len(centers):
                                targetgroup = centers[-1][0]
                                targetidx = len(centers) - 1

                            else:
                                targetgroup = centers[before][0]
                                targetidx = before

                        except Exception:

                            targetgroup = None
                            targetidx = None

                except Exception:

                    targetidx = None

                # apply reorder to TASKBARORDER (and mirror into TASKBARGROUPS)
                try:

                    if curidx is not None and targetidx is not None:

                        if targetidx != curidx:

                            order = list(TASKBARORDER)

                            if DRAGTASKGROUP in order:
                                order.remove(DRAGTASKGROUP)

                            # clamp
                            if targetidx < 0:
                                targetidx = 0

                            if targetidx > len(order):
                                targetidx = len(order)

                            order.insert(int(targetidx), DRAGTASKGROUP)

                            globals()["TASKBARORDER"] = list(order)

                            globals()["TASKBARGROUPS"] = list(order)

                except Exception as e:

                    log(f"drag reorder apply error {e}")

            # while dragging we don't do normal hover logic; just repaint for floating icon
            if TASKBARBUF is not None:
                painttaskbar(sock)

            return

        # first, check if pointer is over the T1OS logo / launcher
        try:

            abs_y0 = DESKTOPH - TASKBARH + (TASKBARH - LAUNCHH) // 2

            inside_logo = (
                    LOGOX <= ax < LOGOX + LOGOW and
                    abs_y0 <= ay < abs_y0 + LOGOH
            )

        except Exception:

            inside_logo = False

        if inside_logo:

            settaskbarwindowhover(sock, None)

            if not HOVERLOGO:

                globals()["HOVERLOGO"] = True

                if TASKBARBUF is not None:
                    painttaskbar(sock)

            # hovering logo: start pending start-tooltip timer
            HOVERPENDINGSTART = True

            HOVERPENDINGSTARTTS = time.time()

            # do not track other hovers at the same time
            HOVERPENDINGWID = None

            HOVERPENDINGTS = 0.0

            HOVERPENDINGNET = False

            HOVERPENDINGNETTS = 0.0

            HOVERPENDINGCLOCK = False

            HOVERPENDINGCLOCKTS = 0.0

            return

        if HOVERLOGO:

            globals()["HOVERLOGO"] = False

            if TASKBARBUF is not None:
                painttaskbar(sock)

        # not over logo: clear any pending start hover
        if HOVERPENDINGSTART:
            HOVERPENDINGSTART = False

            HOVERPENDINGSTARTTS = 0.0

        # check if pointer is over the audio icon
        inside_audio = False

        try:

            rect = globals().get("AUDIOICONRECT")

            if rect and len(rect) == 4:

                axx, ayy, aww, ahh = rect

                if axx <= ax < axx + aww and ayy <= ay < ayy + ahh:
                    inside_audio = True

        except Exception as e:

            log(f"audio hover rect error {e}")

            inside_audio = False

        if inside_audio:

            settaskbarwindowhover(sock, None)

            if VOLUMEMAPPED or VOLUMEPENDING:
                return

            HOVERPENDINGAUDIO = True

            HOVERPENDINGAUDIOTS = time.time()

            HOVERPENDINGWID = None

            HOVERPENDINGTS = 0.0

            HOVERPENDINGNET = False

            HOVERPENDINGNETTS = 0.0

            HOVERPENDINGCLOCK = False

            HOVERPENDINGCLOCKTS = 0.0

            return

        if HOVERPENDINGAUDIO:

            HOVERPENDINGAUDIO = False

            HOVERPENDINGAUDIOTS = 0.0

        inside_net = False

        try:

            rect = globals().get("NETICONRECT")

            if rect and len(rect) == 4:

                nx, ny, nw, nh = rect

                if nx <= ax < nx + nw and ny <= ay < ny + nh:
                    inside_net = True

        except Exception as e:

            log(f"network hover rect error {e}")

            inside_net = False

        if inside_net:
            settaskbarwindowhover(sock, None)
            # hovering network icon: start pending net-tooltip timer
            if not HOVERPENDINGNET:
                HOVERPENDINGNET = True

                HOVERPENDINGNETTS = time.time()

            # clear competing hovers
            HOVERPENDINGWID = None

            HOVERPENDINGTS = 0.0

            HOVERPENDINGCLOCK = False

            HOVERPENDINGCLOCKTS = 0.0

            return

        # not over network icon: clear any pending net hover
        if HOVERPENDINGNET:
            HOVERPENDINGNET = False

            HOVERPENDINGNETTS = 0.0

        # check if pointer is over the clock area
        inside_clock = False

        try:

            rect = globals().get("CLOCKRECT")

            if rect and len(rect) == 4:

                cx, cy, cw, ch = rect

                if cx <= ax < cx + cw and cy <= ay < cy + ch:
                    inside_clock = True

        except Exception as e:

            log(f"clock hover rect error {e}")

            inside_clock = False

        if inside_clock:
            settaskbarwindowhover(sock, None)
            if not HOVERPENDINGCLOCK:

                HOVERPENDINGCLOCK = True

                HOVERPENDINGCLOCKTS = time.time()

            HOVERPENDINGWID = None

            HOVERPENDINGTS = 0.0

            return

        if HOVERPENDINGCLOCK:

            HOVERPENDINGCLOCK = False

            HOVERPENDINGCLOCKTS = 0.0

        try:

            newgroup = findtaskbargroupat(ax, ay)

        except Exception as e:

            log(f"taskbar motion group find error {e}")

            newgroup = None

        if newgroup is None:

            settaskbarwindowhover(sock, None)

            if LISTMAPPED and LISTRECT and len(LISTRECT) == 4:

                lx, ly, lw, lh = LISTRECT

                if lx <= ax < lx + lw and ly <= ay < ly + lh:

                    if LISTGROUP is not None:
                        HOVERPENDINGGROUP = LISTGROUP

                        HOVERPENDINGGROUPTS = time.time()

                    return

            if HOVERPENDINGGROUP is not None:
                HOVERPENDINGGROUP = None

                HOVERPENDINGGROUPTS = 0.0

            return

        settaskbarwindowhover(sock, newgroup)

        if newgroup == HOVERPENDINGGROUP:
            return

        now = time.time()

        HOVERPENDINGGROUP = newgroup

        HOVERPENDINGGROUPTS = now

        LISTGRACETS = now

    except Exception as e:

        log(f"handletaskbarmotion error {e}")


# hover functions
def showtooltip(sock, x, y, w, h, text):

    global TOOLTIPMAPPED, HOVERRECT, GRAPHICSTOOLTIPDATA

    try:

        if TOOLTIPID is None or TOOLTIPBUF is None:
            return

        HOVERRECT = [int(x), int(y), int(w), int(h)]

        GRAPHICSTOOLTIPDATA = {
            "x": 10,
            "y": 10,
            "text": str(text),
            "color": int(HOVERCOLOR),
            "size": int(HOVERFONTSIZE),
        }

        try:

            sendline(sock, {"op": "RESIZE", "winid": TOOLTIPID, "w": int(w), "h": int(h)})

            sendline(sock, {"op": "MOVE", "winid": TOOLTIPID, "x": int(x), "y": int(y)})

        except Exception as e:

            log(f"tooltip move/resize error {e}")

        try:

            fillbufferfile(
                TOOLTIPBUF,
                w,
                0,
                0,
                w,
                h,
                (0, 0, 0)
            )

        except Exception as e:

            log(f"tooltip fill error {e}")

            return

        try:

            drawttffile(
                TOOLTIPBUF,
                w,
                h,
                10,
                10,
                text,
                HOVERCOLOR,
                HOVERFONTSIZE
            )

        except Exception as e:

            log(f"tooltip text draw error {e}")

        graphicsupdategeometry("tooltip", w, h, TOOLTIPBUF)
        graphicscpudamage(sock, "tooltip", [0, 0, int(w), int(h)])
        graphicspresent(sock, "tooltip", [0, 0, int(w), int(h)])

        try:

            if not TOOLTIPMAPPED:
                sendline(sock, {"op": "MAP", "winid": TOOLTIPID})

                TOOLTIPMAPPED = True

        except Exception as e:

            log(f"tooltip map error {e}")

    except Exception as e:

        log(f"showtooltip error {e}")


def clearhovertooltip(sock):

    global HOVERRECT, HOVERPINGTS, TOOLTIPMAPPED, LISTMAPPED, LISTRECT, LISTANCHOR, LISTITEMRECTS, LISTGROUP, LISTHOVERWID
    global HOVERLISTGROUP, HOVERLISTTS, HOVERTOOLTIPGROUP, HOVERTOOLTIPTS, LISTGRACETS, LISTCLOSERECTS, HOVERAUDIODRAWLABEL, HOVERAUDIODRAWRECT, GRAPHICSTOOLTIPDATA

    try:

        oldhoverrect = None
        if HOVERRECT and len(HOVERRECT) == 4:
            oldhoverrect = [int(HOVERRECT[0]), int(HOVERRECT[1]), int(HOVERRECT[2]), int(HOVERRECT[3])]

        oldlistrect = None
        if LISTRECT and len(LISTRECT) == 4:
            oldlistrect = [int(LISTRECT[0]), int(LISTRECT[1]), int(LISTRECT[2]), int(LISTRECT[3])]

        HOVERRECT = None

        GRAPHICSTOOLTIPDATA = None

        HOVERPINGTS = 0.0

        LISTGRACETS = 0.0

        # reset "already shown" guards so we can show again reliably
        HOVERLISTGROUP = None

        HOVERLISTTS = 0.0

        HOVERTOOLTIPGROUP = None

        HOVERTOOLTIPTS = 0.0

        HOVERAUDIODRAWLABEL = ""

        HOVERAUDIODRAWRECT = None

        if TOOLTIPMAPPED and TOOLTIPID is not None:

            graphicssuspend(sock, "tooltip")

            sendline(sock, {"op": "UNMAP", "winid": TOOLTIPID})

            TOOLTIPMAPPED = False

            if oldhoverrect:
                sendline(sock, {"op": "OVERLAY_DAMAGE", "rect": oldhoverrect})

        LISTRECT = None

        LISTANCHOR = None

        LISTHOVERWID = None

        LISTITEMRECTS = []

        LISTCLOSERECTS = []

        LISTGROUP = None

        if LISTMAPPED and LISTID is not None:

            graphicssuspend(sock, "instancelist")

            sendline(sock, {"op": "UNMAP", "winid": LISTID})

            LISTMAPPED = False

            if oldlistrect:
                sendline(sock, {"op": "OVERLAY_DAMAGE", "rect": oldlistrect})

    except Exception as e:

        log(f"clearhovertooltip error {e}")


def updatehover(sock):

    global HOVERWID, HOVERPENDINGWID, HOVERPENDINGTS, HOVERSTART, HOVERPENDINGSTART, HOVERPENDINGSTARTTS, HOVERNET, HOVERPENDINGNET, HOVERPENDINGNETTS, HOVERRECT, HOVERPINGTS, HOVERPINGINTERVAL, HOVERCLOCK, HOVERPENDINGCLOCK, HOVERPENDINGCLOCKTS
    global HOVERPENDINGGROUPTS, HOVERLISTGROUP, HOVERLISTTS, HOVERTOOLTIPTS, HOVERTOOLTIPGROUP, HOVERAUDIO, HOVERPENDINGAUDIO, HOVERPENDINGAUDIOTS, HOVERAUDIOLABEL, HOVERAUDIOLABELTS, HOVERAUDIODRAWLABEL, HOVERAUDIODRAWRECT

    try:

        now = time.time()

        # if nothing is pending, clear any visible tooltip
        if (
                HOVERPENDINGWID is None and
                HOVERPENDINGGROUP is None and
                not HOVERPENDINGSTART and
                not HOVERPENDINGNET and
                not HOVERPENDINGAUDIO and
                not HOVERPENDINGCLOCK
        ):

            if HOVERWID is not None or HOVERSTART or HOVERNET or HOVERAUDIO or HOVERCLOCK:

                clearhovertooltip(sock)

                HOVERWID = None

                HOVERSTART = False

                HOVERNET = False

                HOVERAUDIO = False

                HOVERCLOCK = False

            return

        # start logo pending hover
        if HOVERPENDINGSTART:

            # wait for 1 second over logo
            if HOVERPENDINGSTARTTS <= 0.0:

                HOVERPENDINGSTARTTS = now

                return

            if now - HOVERPENDINGSTARTTS < 1.0:
                return

            # switching from a window tooltip or net tooltip to start tooltip
            if HOVERWID is not None or HOVERNET:

                clearhovertooltip(sock)

                HOVERWID = None

                HOVERNET = False

            if not HOVERSTART:

                HOVERSTART = True

                if TASKBARBUF is not None:
                    painttaskbar(sock)

            return

        # clock pending hover
        if HOVERPENDINGCLOCK:

            if HOVERPENDINGCLOCKTS <= 0.0:
                HOVERPENDINGCLOCKTS = now

                return

            if now - HOVERPENDINGCLOCKTS < 1.0:
                return

            if HOVERWID is not None or HOVERSTART or HOVERNET:
                clearhovertooltip(sock)

                HOVERWID = None

                HOVERSTART = False

                HOVERNET = False

            if not HOVERCLOCK:

                HOVERCLOCK = True

                if TASKBARBUF is not None:
                    painttaskbar(sock)

            return

        # audio icon pending hover
        if HOVERPENDINGAUDIO:

            if VOLUMEMAPPED or VOLUMEPENDING:

                HOVERPENDINGAUDIO = False

                HOVERPENDINGAUDIOTS = 0.0

                return

            if HOVERPENDINGAUDIOTS <= 0.0:
                HOVERPENDINGAUDIOTS = now

                return

            if now - HOVERPENDINGAUDIOTS < 1.0:
                return

            if HOVERWID is not None or HOVERSTART or HOVERNET or HOVERCLOCK:
                clearhovertooltip(sock)

                HOVERWID = None

                HOVERSTART = False

                HOVERNET = False

                HOVERCLOCK = False

            if not HOVERAUDIO:

                HOVERAUDIO = True

                HOVERAUDIOLABEL = ""

                HOVERAUDIOLABELTS = 0.0

                HOVERAUDIODRAWLABEL = ""

                HOVERAUDIODRAWRECT = None

                if TASKBARBUF is not None:
                    painttaskbar(sock)

            return

        # network icon pending hover
        if HOVERPENDINGNET:

            # wait for 1 second over network icon
            if HOVERPENDINGNETTS <= 0.0:
                HOVERPENDINGNETTS = now

                return

            if now - HOVERPENDINGNETTS < 1.0:
                return

            # switching from window or start tooltip to net tooltip
            if HOVERWID is not None or HOVERSTART:
                clearhovertooltip(sock)

                HOVERWID = None

                HOVERSTART = False

            if not HOVERNET:

                HOVERNET = True

                if TASKBARBUF is not None:
                    painttaskbar(sock)

            return

        if HOVERPENDINGGROUP is not None:

            if TASKMENUMAPPED:
                return

            if HOVERPENDINGGROUPTS <= 0.0:
                HOVERPENDINGGROUPTS = now

                HOVERLISTTS = 0.0

                HOVERTOOLTIPTS = 0.0

                HOVERLISTGROUP = None

                HOVERTOOLTIPGROUP = None

                return

            dt = now - HOVERPENDINGGROUPTS

            if dt >= HOVERLISTDELAY and HOVERLISTGROUP != HOVERPENDINGGROUP:

                g = TASKBARGROUPITEMS.get(HOVERPENDINGGROUP)

                if g:

                    wids = list(g.get("wids", []))

                else:

                    wids = []

                if len(wids) >= 1:

                    rect = TASKBARGROUPRECTS.get(HOVERPENDINGGROUP)

                    if rect and len(rect) == 4:
                        showinstancelist(sock, HOVERPENDINGGROUP, rect)

                        HOVERLISTGROUP = HOVERPENDINGGROUP

                        HOVERLISTTS = now

            if (not DISABLETASKBARTOOLTIP) and dt >= HOVERTOOLTIPDELAY and HOVERTOOLTIPGROUP != HOVERPENDINGGROUP:

                rect = TASKBARGROUPRECTS.get(HOVERPENDINGGROUP)

                if rect and len(rect) == 4 and LISTRECT and len(LISTRECT) == 4:

                    label = str(HOVERPENDINGGROUP).strip()

                    if not label:
                        label = " "

                    try:

                        tw = measurettffile(label, HOVERFONTSIZE)

                    except Exception:

                        tw = 0

                    w = max(s(40, 20), int(tw + s(20, 10)))

                    h = int(HOVERFONTSIZE + s(16, 8))

                    tx = int(LISTRECT[0] + (LISTRECT[2] - w) // 2)

                    if tx < 0:
                        tx = 0

                    if tx + w > DESKTOPW:
                        tx = max(0, DESKTOPW - w)

                    ty = int(LISTRECT[1] - h - 6)

                    if ty < 8:
                        ty = 8

                    showtooltip(sock, tx, ty, w, h, label)

                HOVERTOOLTIPGROUP = HOVERPENDINGGROUP

                if TASKBARBUF is not None:
                    painttaskbar(sock)

            return

        # already showing this tooltip
        if HOVERWID is not None and HOVERWID == HOVERPENDINGWID:
            return

        if HOVERPENDINGTS <= 0.0:
            HOVERPENDINGTS = now

            return

        if now - HOVERPENDINGTS < 1.0:
            return

        # switching from start or net tooltip to window tooltip
        if HOVERSTART or HOVERNET or HOVERCLOCK:
            clearhovertooltip(sock)

            HOVERSTART = False

            HOVERNET = False

            HOVERCLOCK = False

        if HOVERWID is not None and HOVERWID != HOVERPENDINGWID:
            clearhovertooltip(sock)

            HOVERWID = None

        HOVERWID = HOVERPENDINGWID

        if TASKBARBUF is not None:
            painttaskbar(sock)

    except Exception as e:

        log(f"updatehover error {e}")


# power functions
def logout(args=None):
    log("> logging out")
    try:
        from operations.operations import requestsessionlogout
        requestsessionlogout()
    except Exception as error:
        # Fail closed: Expanse owns neither arbitrary signals nor the Startup
        # executable.  If the authenticated supervisor cannot transition the
        # session, keep the current desktop alive and report the failure.
        log(f"logout supervisor request failed {error}")
        return

    try:
        # OperationsServer has accepted ownership of this session transition.
        os._exit(0)

    except Exception as e:

        log(f"logout exit error {e}")


def shutdown():
    global RUN

    try:
        requestpower("poweroff")

        while RUN:
            time.sleep(0.05)

    except (PowerRequestError, OSError, ValueError) as error:
        log(f"shutdown request failed {error}")


def restart():
    global RUN

    try:
        requestpower("restart")

        while RUN:
            time.sleep(0.05)

    except (PowerRequestError, OSError, ValueError) as error:
        log(f"restart request failed {error}")


# audio status functions
def audioreset():

    global AUDIOSRVSOCK, AUDIOSRVINBUF, AUDIOSRVOUTBUF, AUDIOSRVCONNECTED, AUDIOSRVHELLO
    global AUDIOGOTDEV, AUDIOGOTVOL, AUDIOSUBREADY
    global CURRENTAUDIOAVAIL, CURRENTAUDIOVOL, CURRENTAUDIOMUTE, CURRENTAUDIOACTIVE

    try:

        if AUDIOSRVSOCK:
            try:
                SEL.unregister(AUDIOSRVSOCK)
            except Exception:
                pass

            try:
                AUDIOSRVSOCK.close()
            except Exception:
                pass

    except Exception:
        pass

    AUDIOSRVSOCK = None

    AUDIOSRVINBUF = b""
    AUDIOSRVOUTBUF = b""

    AUDIOSRVCONNECTED = False
    AUDIOSRVHELLO = False

    AUDIOGOTDEV = False
    AUDIOGOTVOL = False

    AUDIOSUBREADY = False

    CURRENTAUDIOAVAIL = False
    CURRENTAUDIOVOL = 0
    CURRENTAUDIOMUTE = False
    CURRENTAUDIOACTIVE = None


def audiopack(msgtype, payload):

    body = b""

    if payload is not None:
        try:
            body = json.dumps(payload).encode("utf-8")
        except Exception:
            body = b""

    flags = 0

    header = struct.pack(
        ">4sBBHI",
        AUDIOMAGIC,
        AUDIOPROTO,
        int(msgtype),
        int(flags),
        int(len(body))
    )

    return header + body


def audiosend(msgtype, payload):

    global AUDIOSRVOUTBUF

    if not AUDIOSRVSOCK:
        return

    pkt = audiopack(msgtype, payload)

    AUDIOSRVOUTBUF += pkt


def audioservicewrite():

    global AUDIOSRVOUTBUF

    if not AUDIOSRVSOCK:
        return

    outbuf = AUDIOSRVOUTBUF

    if not outbuf:
        return

    try:

        sent = AUDIOSRVSOCK.send(outbuf)

        if sent > 0:
            AUDIOSRVOUTBUF = outbuf[sent:]

    except BlockingIOError:

        return

    except Exception:

        audioreset()


def audiohandle(msgtype, payload):

    global AUDIOSRVHELLO, AUDIOGOTDEV, AUDIOGOTVOL, AUDIOSUBREADY
    global CURRENTAUDIOAVAIL, CURRENTAUDIOVOL, CURRENTAUDIOMUTE, CURRENTAUDIOACTIVE
    global AUDIODIRTY, AUDIOFORCE

    if int(msgtype) == AUDIO_MSGHELLO:

        AUDIOSRVHELLO = True

        audiosend(AUDIO_MSGDEVLIST, None)

        audiosend(AUDIO_MSGSUBSCRIBE, {"topic": "volume"})

        audiosend(AUDIO_MSGSUBSCRIBE, {"topic": "mute"})

        audiosend(AUDIO_MSGVOLUME, None)

        audiosend(AUDIO_MSGMUTE, None)

        return

    if int(msgtype) == AUDIO_MSGDEVLIST:

        active = None

        devices = []

        if isinstance(payload, dict):

            active = payload.get("active")

            devices = payload.get("devices", [])

        CURRENTAUDIOACTIVE = active

        avail = False

        if active and isinstance(devices, list):

            for dev in devices:

                if isinstance(dev, dict) and dev.get("id") == active:

                    avail = bool(
                        dev.get("ready") or
                        dev.get("prepared") or
                        dev.get("active")
                    )

                    break

        CURRENTAUDIOAVAIL = bool(avail)

        AUDIOGOTDEV = True

        AUDIODIRTY = True

        AUDIOFORCE = True

        if AUDIOGOTDEV and AUDIOGOTVOL:
            AUDIOSUBREADY = True

        return

    if int(msgtype) == AUDIO_MSGVOLUME:

        gain = 0.0

        mute = False

        oldvol = int(CURRENTAUDIOVOL)

        oldmute = bool(CURRENTAUDIOMUTE)

        if isinstance(payload, dict):
            gain = float(payload.get("gain", 0.0))
            mute = bool(payload.get("mute", False))

        vol = int(round(gain * 100.0))

        if vol < 0:
            vol = 0

        if vol > 100:
            vol = 100

        CURRENTAUDIOVOL = int(vol)

        CURRENTAUDIOMUTE = bool(mute)

        volumechanged = (int(vol) != int(oldvol) or bool(mute) != bool(oldmute))

        if volumechanged and float(VOLUMEAUTOCLOSEAT) > 0.0:
            renewvolumetimeout()

        if VOLUMEMAPPED and (not VOLUMEDRAG) and volumechanged:
            paintvolumebar(globals().get("SOCK"))

        AUDIOGOTVOL = True

        AUDIODIRTY = True

        AUDIOFORCE = True

        if AUDIOGOTDEV and AUDIOGOTVOL:
            AUDIOSUBREADY = True

        return

    if int(msgtype) == AUDIO_MSGMUTE:

        mute = False

        gain = 0.0

        oldvol = int(CURRENTAUDIOVOL)

        oldmute = bool(CURRENTAUDIOMUTE)

        if isinstance(payload, dict):
            mute = bool(payload.get("mute", False))
            gain = float(payload.get("gain", 0.0))

        CURRENTAUDIOMUTE = bool(mute)

        vol = int(round(gain * 100.0))

        if vol < 0:
            vol = 0

        if vol > 100:
            vol = 100

        CURRENTAUDIOVOL = int(vol)

        volumechanged = (int(vol) != int(oldvol) or bool(mute) != bool(oldmute))

        if volumechanged and float(VOLUMEAUTOCLOSEAT) > 0.0:
            renewvolumetimeout()

        if VOLUMEMAPPED and (not VOLUMEDRAG) and volumechanged:
            paintvolumebar(globals().get("SOCK"))

        AUDIOGOTVOL = True

        AUDIODIRTY = True

        AUDIOFORCE = True

        if AUDIOGOTDEV and AUDIOGOTVOL:
            AUDIOSUBREADY = True

        return


def audioparse():

    global AUDIOSRVINBUF

    buf = AUDIOSRVINBUF

    while True:

        if len(buf) < AUDIOHDRSZ:
            break

        try:

            magic, proto, mtype, flags, length = struct.unpack(">4sBBHI", buf[:AUDIOHDRSZ])

        except Exception:

            audioreset()
            return

        if magic != AUDIOMAGIC or int(proto) != int(AUDIOPROTO):

            audioreset()
            return

        if int(length) < 0 or int(length) > int(AUDIOMAXMSG):

            audioreset()
            return

        need = int(AUDIOHDRSZ + length)

        if len(buf) < need:
            break

        body = buf[AUDIOHDRSZ:need]

        buf = buf[need:]

        payload = None

        if body:
            try:
                payload = json.loads(body.decode("utf-8"))
            except Exception:
                payload = None

        audiohandle(mtype, payload)

    AUDIOSRVINBUF = buf


def audioserviceread():

    global AUDIOSRVINBUF

    if not AUDIOSRVSOCK:
        return

    try:

        data = AUDIOSRVSOCK.recv(4096)

    except BlockingIOError:

        return

    except Exception:

        audioreset()
        return

    if not data:

        audioreset()
        return

    AUDIOSRVINBUF += data

    audioparse()


def audioconnect():

    global AUDIOSRVSOCK, AUDIOSRVCONNECTED

    audioreset()

    try:

        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

        s.setblocking(False)

        s.connect(AUDIOSOCK)

        AUDIOSRVSOCK = s
        AUDIOSRVCONNECTED = True

    except BlockingIOError:

        AUDIOSRVSOCK = s
        AUDIOSRVCONNECTED = True

    except Exception:

        try:
            s.close()
        except Exception:
            pass

        audioreset()

        return

    try:

        SEL.register(s, selectors.EVENT_READ | selectors.EVENT_WRITE, {"kind": "audio"})

    except Exception:

        audioreset()

        return

    audiosend(AUDIO_MSGHELLO, {"client": "expanse", "time": timestamp()})


def audiotick():

    global AUDIONEXTCONNECT

    if AUDIOSRVSOCK:
        return

    now = time.time()

    if now < float(AUDIONEXTCONNECT):
        return

    AUDIONEXTCONNECT = float(now + AUDIOCONNECTINTERVAL)

    audioconnect()


def makeaudiolabel():

    if not bool(CURRENTAUDIOAVAIL):
        return "unavailable"

    v = int(CURRENTAUDIOVOL)

    return f"volume {v}%"


def pickaudioicon(volpct, available):

    if not available:
        return AUDIOUNAVAILICONPATH

    v = int(volpct)

    if v <= 0:
        return AUDIOZEROICONPATH

    if 1 <= v <= 33:
        return AUDIOLOWICONPATH

    if 34 <= v <= 66:
        return AUDIOMEDICONPATH

    return AUDIOFULLICONPATH


def updateaudioicon(sock, force=False):

    global LASTAUDIOAVAIL, LASTAUDIOVOL, LASTAUDIOMUTE, AUDIOICONX, AUDIOICONY, AUDIOICONW, AUDIOICONH, AUDIOICONRECT

    try:

        if TASKBARBUF is None:
            return

        if AUDIOGOTDEV:

            avail = bool(CURRENTAUDIOAVAIL)

        else:

            avail = False

        if AUDIOGOTVOL:

            vol = int(CURRENTAUDIOVOL)

            mute = bool(CURRENTAUDIOMUTE)

        else:

            vol = 0

            mute = False

        if (
                not force and
                avail == LASTAUDIOAVAIL and
                vol == LASTAUDIOVOL and
                mute == LASTAUDIOMUTE
        ):
            return

        if graphicsmanagedpaint(sock, "taskbar", [0, 0, DESKTOPW, TASKBARH]):
            return

        aud_h = s(BASE_AUDIOICON, 12)

        aud_w = aud_h

        aud_y = (TASKBARH - aud_h) // 2

        clockrect = globals().get("CLOCKRECT")

        if clockrect:
            clockleft = int(clockrect[0])
        else:
            clockleft = int(CLOCK_CX)

        aud_x = clockleft - CLOCKCLEARPAD - AUDIOICONGAP - aud_w

        aud_x = int(aud_x)

        if aud_x + aud_w > DESKTOPW:
            aud_x = DESKTOPW - aud_w

        if aud_x < 0:
            aud_x = 0

        path = pickaudioicon(vol, avail)

        fillbufferfile(
            TASKBARBUF,
            DESKTOPW,
            aud_x,
            aud_y,
            aud_w,
            aud_h,
            (0, 0, 0)
        )

        cachedpath, sw, sh = prepareicon(path, aud_w, aud_h)

        if sw > 0 and sh > 0 and cachedpath is not None:

            blitrawscaledintobuffer(
                cachedpath,
                sw,
                sh,
                TASKBARBUF,
                DESKTOPW,
                aud_x,
                aud_y,
                aud_w,
                aud_h
            )

        else:

            fillbufferfile(
                TASKBARBUF,
                DESKTOPW,
                aud_x,
                aud_y,
                aud_w,
                aud_h,
                (96, 96, 96)
            )

        LASTAUDIOAVAIL = bool(avail)

        LASTAUDIOVOL = int(vol)

        LASTAUDIOMUTE = bool(mute)

        try:

            absx = aud_x

            absy = DESKTOPH - TASKBARH + aud_y

            AUDIOICONX = aud_x

            AUDIOICONY = aud_y

            AUDIOICONW = aud_w

            AUDIOICONH = aud_h

            AUDIOICONRECT = [absx, absy, aud_w, aud_h]

        except Exception as e:

            log(f"audio icon geom store error {e}")

        graphicscpudamage(sock, "taskbar", [aud_x, aud_y, aud_w, aud_h])
        graphicspresent(sock, "taskbar", [aud_x, aud_y, aud_w, aud_h])

    except Exception as e:

        log(f"update audio icon error {e}")


def taskbarpaintaudio(sock, force=False):

    try:

        updateaudioicon(sock, force=force)

    except Exception as e:

        log(f"audio icon draw error {e}")


# network status functions
def networkconnectiontype(iface):

    iface = str(iface or '').strip()
    lowered = iface.lower()
    state = os.path.join(NETWORKSTATE, iface)

    if os.path.isdir(os.path.join(state, 'wireless')) or lowered.startswith(('wl', 'wifi')):
        return 'wi-fi'
    if lowered.startswith(('ww', 'ppp', 'rmnet', 'cdc-wdm')):
        return 'mobile'
    if lowered.startswith(('bnep', 'bt')):
        return 'bluetooth'
    if lowered.startswith(('tun', 'tap', 'wg')):
        return 'vpn'
    if lowered.startswith(('usb', 'rndis')):
        return 'usb'
    return 'ethernet'


def networkdisplayname(value):

    # Preserve the router's capitalization exactly while excluding characters
    # that cannot safely be painted in a one-line tooltip.
    return ''.join(
        character for character in str(value or '')
        if character.isprintable() and character not in ('\r', '\n')
    ).strip()


def customethernetname(runtime):

    key = str((runtime or {}).get('connection_id') or '').strip()

    if not key.startswith('ethernet-') or len(key) > 96:
        return ''

    try:
        with open(ETHERNETNAMESFILE, 'r', encoding='utf-8') as stream:
            names = json.load(stream)
    except Exception:
        return ''

    if not isinstance(names, dict):
        return ''

    return networkdisplayname(names.get(key, ''))


def readnetworkidentity(iface):

    iface = str(iface or '').strip()
    kind = networkconnectiontype(iface)
    name = ''

    try:
        with open(NETWORKCONNECTIONSTATE, 'r', encoding='utf-8') as stream:
            runtime = json.load(stream)
    except Exception:
        runtime = {}

    if (
        str(runtime.get('interface') or '').strip() == iface and
        bool(runtime.get('connected'))
    ):
        publishedtype = ' '.join(str(runtime.get('type') or '').split()).strip().lower()
        if publishedtype:
            kind = publishedtype
        name = networkdisplayname(runtime.get('name'))

    if (
        not name and kind == 'ethernet' and
        str(runtime.get('interface') or '').strip() == iface and
        bool(runtime.get('connected'))
    ):
        name = customethernetname(runtime)

    if not name and kind == 'wi-fi':
        paths = [
            os.path.join(NETWORKSETTINGS, iface + '.wireless.txt'),
            os.path.join(NETWORKSETTINGS, 'wireless.txt'),
        ]
        for path in paths:
            try:
                with open(path, 'r', encoding='utf-8', errors='replace') as stream:
                    values = dict(
                        line.strip().split('=', 1)
                        for line in stream
                        if '=' in line and not line.lstrip().startswith('#')
                    )
                name = networkdisplayname(values.get('ssid'))
            except Exception:
                continue
            if name:
                break

    return name or 'network', kind.lower()


def networktooltiplabels(iface):

    name, kind = readnetworkidentity(iface)
    return [name, kind, 'online']


def readnetworkstatus():
    try:

        # open netlink socket
        try:

            ip = IPRoute()

        except Exception as e:

            # could not open netlink socket
            log(f"network status socket error {e}")

            return "offline", "", "", "", ""

        try:

            # find the first non-loopback interface
            iface = None

            idx = None

            mac = ""

            for link in ip.get_links():

                name = link.get_attr('IFLA_IFNAME')

                if not name or name == 'lo':
                    continue

                idxs = ip.link_lookup(ifname=name)

                if not idxs:
                    continue

                iface = name

                idx = idxs[0]

                try:

                    mac = link.get_attr('IFLA_ADDRESS') or ""

                except Exception:

                    mac = ""

                break

            # if no suitable interface is found
            if not iface or idx is None:
                # no valid interface
                return "offline", "", "", "", ""

            # fetch ipv4 address for this interface
            addr = ""

            prefix = None

            try:

                addrs = ip.get_addr(index=idx, family=socket.AF_INET)

            except Exception:

                addrs = []

            if addrs:

                try:

                    addr = addrs[0].get_attr('IFA_ADDRESS') or ""

                except Exception:

                    addr = ""

                try:

                    prefix = addrs[0].get('prefixlen')

                except Exception:

                    prefix = None

            # combine address and prefix if available
            if addr and prefix is not None:

                ipaddr = f"{addr}/{prefix}"

            else:

                ipaddr = addr

            # discover default gateway for this interface
            gw = ""

            try:

                routes = ip.get_default_routes(family=socket.AF_INET)

            except Exception:

                routes = []

            for r in routes:

                try:

                    oif = r.get_attr('RTA_OIF')

                except KeyError:

                    continue

                except Exception:

                    continue

                if oif != idx:
                    continue

                try:

                    gw = r.get_attr('RTA_GATEWAY') or ""

                except KeyError:

                    gw = ""

                except Exception:

                    gw = ""

                break

            # derive state from presence of address / gateway
            if ipaddr and gw:

                state = "online"

            elif ipaddr:

                state = "linked"

            else:

                state = "offline"

            return state, (iface or ""), (ipaddr or ""), (gw or ""), (mac or "")

        except PermissionError:

            # permission denied reading netlink
            log("network status permission denied")

            return "offline", "", "", "", ""

        except Exception as e:

            # other error reading status
            log(f"network status read error {e}")

            return "offline", "", "", "", ""

        finally:

            ip.close()
    except Exception as e:

        # outer error
        log(f"network status outer error {e}")

        return "offline", "", "", "", ""


def makenetworklabel():

    try:

        # read status from kernel via netlink
        state, iface, addr, gw, mac = readnetworkstatus()

        state = (state or "").lower()

        # online: show iface and address if present
        if state == "online":

            parts = ["online"]

            if iface:
                parts.append(iface)

            if addr:
                parts.append(addr)

            return " ".join(parts)

        # linked but no default route
        if state == "linked":

            parts = ["linked"]

            if iface:
                parts.append(iface)

            if addr:
                parts.append(addr)

            return " ".join(parts)

        # default label
        return "offline"

    except Exception as e:

        # label construction error
        log(f"network label error {e}")

        return "offline"


def updatenetworkicon(sock):
    global LASTNETSTATE, LASTNETADDR, LASTNETGW

    try:

        if TASKBARBUF is None:
            return

        # read status
        state, iface, addr, gw, mac = readnetworkstatus()

        if (
                state == LASTNETSTATE and
                addr == LASTNETADDR and
                gw == LASTNETGW
        ):
            return

        if graphicsmanagedpaint(sock, "taskbar", [0, 0, DESKTOPW, TASKBARH]):
            return

        state = (state or "").lower()

        # only full ip + gateway counts as online
        is_online = (state == "online" and addr and gw)

        # desired icon size
        net_h = s(BASE_NETICON, 12)

        net_w = net_h

        # vertical centering
        net_y = (TASKBARH - net_h) // 2

        clockrect = globals().get("CLOCKRECT")

        if clockrect:

            clockleft = int(clockrect[0])

        else:

            clockleft = int(CLOCK_CX)

        audx = globals().get("AUDIOICONX")

        audw = globals().get("AUDIOICONW")

        if audx is not None and audw is not None:

            net_x = int(audx) - NETICONGAP - net_w

        else:

            net_x = clockleft - CLOCKCLEARPAD - NETICONGAP - net_w

        net_x = int(net_x)

        if net_x + net_w > DESKTOPW:
            net_x = DESKTOPW - net_w

        if net_x < 0:
            net_x = 0

        # choose icon path
        if is_online:

            path = NETWORKICONPATH

        else:

            path = GREYNETWORKICONPATH

        # clear icon area
        fillbufferfile(
            TASKBARBUF,
            DESKTOPW,
            net_x,
            net_y,
            net_w,
            net_h,
            (0, 0, 0)
        )

        cachedpath, sw, sh = prepareicon(path, net_w, net_h)

        if sw > 0 and sh > 0 and cachedpath is not None:

            blitrawscaledintobuffer(
                cachedpath,
                sw,
                sh,
                TASKBARBUF,
                DESKTOPW,
                net_x,
                net_y,
                net_w,
                net_h
            )

        else:

            # fallback solid box
            fillbufferfile(
                TASKBARBUF,
                DESKTOPW,
                net_x,
                net_y,
                net_w,
                net_h,
                (96, 96, 96)
            )

        LASTNETSTATE = state

        LASTNETADDR = addr

        LASTNETGW = gw

        try:

            # store absolute rect for hover hit-testing
            absx = net_x

            absy = DESKTOPH - TASKBARH + net_y

            globals()["NETICONX"] = net_x

            globals()["NETICONY"] = net_y

            globals()["NETICONW"] = net_w

            globals()["NETICONH"] = net_h

            globals()["NETICONRECT"] = [absx, absy, net_w, net_h]

        except Exception as e:

            log(f"network icon geom store error {e}")

        graphicscpudamage(sock, "taskbar", [net_x, net_y, net_w, net_h])
        graphicspresent(sock, "taskbar", [net_x, net_y, net_w, net_h])

    except Exception as e:

        log(f"update network icon error {e}")


# painting
def desktoppaintcontent():

    fillbufferfile(DESKTOPBUF, DESKTOPW, 0, 0, DESKTOPW, DESKTOPH, DESKTOPBG)
    rows = desktoplayout()
    metrics = desktopmetrics()

    for item in rows:
        x, y, width, height = item["rect"]
        selected = item.get("path") == DESKTOPSELECTED
        hovered = item.get("path") == DESKTOPHOVER

        if selected:
            fillbufferfile(DESKTOPBUF, DESKTOPW, x, y, width, height, (36, 36, 36))
            fillbufferfile(DESKTOPBUF, DESKTOPW, x, y, width, 1, (239, 239, 239))
        elif hovered:
            fillbufferfile(DESKTOPBUF, DESKTOPW, x, y, width, height, (18, 18, 18))

        fillbufferfile(
            DESKTOPBUF, DESKTOPW, x, y + height - 1, width, 1, (58, 58, 58))

        arrowx, _, arrowwidth, _ = item["arrowrect"]
        texty = y + (height - metrics["font"]) // 2

        if item.get("isdir"):
            if item.get("expanded"):
                middlex = arrowx + arrowwidth // 2
                middley = y + height // 2 + max(1, metrics["font"] // 6)
                span = max(2, metrics["font"] // 4)
                drawline(
                    arrowx + max(1, arrowwidth // 5),
                    middley - span,
                    middlex,
                    middley,
                    (239, 239, 239),
                )
                drawline(
                    middlex,
                    middley,
                    arrowx + arrowwidth - max(2, arrowwidth // 5),
                    middley - span,
                    (239, 239, 239),
                )
            else:
                drawtextttf(
                    arrowx,
                    texty,
                    ">",
                    0xEFEFEF if item.get("haskids") else 0x8A8A8A,
                    metrics["font"],
                    fontpath=FONTPATH,
                )

        namex = arrowx + arrowwidth
        available = max(1, x + width - metrics["padding"] - namex)
        label = searchfittext(str(item.get("name", "")), available, metrics["font"])
        drawtextttf(
            namex,
            texty,
            label,
            0xEFEFEF,
            metrics["font"],
            fontpath=FONTPATH,
        )

    creationrect = desktopcreationrect()
    if creationrect is not None:
        x, y, width, height = creationrect
        fillbufferfile(DESKTOPBUF, DESKTOPW, x, y, width, height, (36, 36, 36))
        fillbufferfile(DESKTOPBUF, DESKTOPW, x, y, width, 1, (239, 239, 239))
        fillbufferfile(
            DESKTOPBUF, DESKTOPW, x, y + height - 1, width, 1, (58, 58, 58))

        arrowx = x + metrics["padding"]
        arrowwidth = metrics["indent"]
        namex = arrowx + arrowwidth
        if DESKTOPCREATEKIND == "tier":
            drawtextttf(
                arrowx,
                y + (height - metrics["font"]) // 2,
                ">",
                0x8A8A8A,
                metrics["font"],
                fontpath=FONTPATH,
            )

        boxpad = max(2, metrics["padding"] // 2)
        boxx = namex - boxpad
        boxy = y + max(2, metrics["padding"] // 2)
        boxw = max(1, x + width - metrics["padding"] - boxx)
        status = str(DESKTOPCREATEERROR or "").lower()
        boxh = max(
            metrics["font"] + boxpad * 2,
            height - metrics["padding"] - (metrics["font"] if status else 0),
        )
        boxh = min(boxh, max(1, height - max(2, metrics["padding"] // 2)))
        drawrect(
            boxx,
            boxy,
            boxw,
            boxh,
            (190, 96, 96)
            if status and status not in ("creating", "renaming")
            else (239, 239, 239),
        )

        available = max(1, boxw - boxpad * 2)
        text = str(DESKTOPCREATETEXT)
        caret = max(0, min(int(DESKTOPCREATECARETPOS), len(text)))
        visible_start = 0
        while (
            visible_start < caret and
            measurettffile(text[visible_start:caret], metrics["font"]) > available
        ):
            visible_start += 1
        visible_end = len(text)
        while (
            visible_end > caret and
            measurettffile(text[visible_start:visible_end], metrics["font"]) > available
        ):
            visible_end -= 1
        visible = text[visible_start:visible_end]
        texty = boxy + max(1, (boxh - metrics["font"]) // 2)
        drawtextttf(
            boxx + boxpad,
            texty,
            visible,
            0xEFEFEF,
            metrics["font"],
            fontpath=FONTPATH,
        )
        selection = desktopeditselection()
        if selection is not None:
            selectedstart = max(visible_start, selection[0])
            selectedend = min(visible_end, selection[1])
            if selectedstart < selectedend:
                selectedx = (
                    boxx + boxpad +
                    measurettffile(
                        text[visible_start:selectedstart], metrics["font"])
                )
                selectedwidth = max(
                    1,
                    measurettffile(
                        text[selectedstart:selectedend], metrics["font"]),
                )
                fillbufferfile(
                    DESKTOPBUF,
                    DESKTOPW,
                    selectedx,
                    texty,
                    selectedwidth,
                    metrics["font"] + 1,
                    (239, 239, 239),
                )
                drawtextttf(
                    selectedx,
                    texty,
                    text[selectedstart:selectedend],
                    0x000000,
                    metrics["font"],
                    fontpath=FONTPATH,
                )
        caretx = (
            boxx + boxpad +
            measurettffile(text[visible_start:caret], metrics["font"])
        )
        drawline(
            caretx,
            texty,
            caretx,
            min(boxy + boxh - 2, texty + metrics["font"]),
            (239, 239, 239),
        )
        if status:
            statussize = max(s(9, 7), metrics["font"] - s(3, 2))
            statuslabel = searchfittext(
                status, max(1, width - metrics["padding"] * 2), statussize)
            drawtextttf(
                namex,
                max(y, y + height - statussize - 2),
                statuslabel,
                0xC97979
                if status not in ("creating", "renaming") else 0x8A8A8A,
                statussize,
                fontpath=FONTPATH,
            )


def paintdesktop(sock):

    if graphicsmanagedpaint(sock, "desktop"):
        return

    try:

        if DESKTOPBUF is None or fillbufferfile is None:
            return

        desktoppaintcontent()

        graphicsupdategeometry("desktop", DESKTOPW, DESKTOPH, DESKTOPBUF)
        graphicscpudamage(sock, "desktop", [0, 0, DESKTOPW, DESKTOPH])
        graphicspresent(sock, "desktop", [0, 0, DESKTOPW, DESKTOPH])

        log("desktop painted")

    except Exception as e:

        log(f"desktop paint error {e}")


def painttaskbar(sock):

    if graphicsmanagedpaint(sock, "taskbar"):
        # CPU taskbar painting reaches this through the normal paint sequence.
        # Managed-only taskbar painting returns early, so paint the independent
        # tooltip surface explicitly to preserve the same hover behaviour.
        taskbarpainttooltips(sock)
        return

    try:

        if TASKBARBUF is None or fillbufferfile is None:
            return

        realbuf, tmpbuf = taskbarbegin()

        committed = False

        GRAPHICSPAINTING.add("taskbar")

        try:

            taskbarpaintbase()

            taskbarpaintlauncher()

            taskbarpaintsearch()

            taskbarpaintclock()

            taskbarpaintmasterimage()

            taskbarpaintaudio(sock, force=True)

            taskbarpaintnetwork(sock)

            taskbarpaintwindowicons()

            taskbarpaintshowdesktop()

            taskbarpainttooltips(sock)

            taskbarcommit(sock, realbuf, tmpbuf)

            committed = True

        finally:

            taskbarend(realbuf, tmpbuf, committed)

            GRAPHICSPAINTING.discard("taskbar")

        graphicsupdategeometry("taskbar", DESKTOPW, TASKBARH, TASKBARBUF)
        graphicspresent(sock, "taskbar", [0, 0, DESKTOPW, TASKBARH])

    except Exception as e:

        log(f"taskbar paint error {e}")


def startmenubegin():

    global STARTBUF

    if STARTBUF is None or fillbufferfile is None:
        return None, None

    realbuf = STARTBUF
    tmpbuf = surfacestagingpath("startmenu")

    try:

        with open(tmpbuf, "wb") as f:
            f.truncate(int(STARTW) * int(STARTH) * 4)

    except Exception as e:

        log(f"start menu tmp prepare error {e}")
        return None, None

    STARTBUF = tmpbuf
    return realbuf, tmpbuf


def startmenucommit(sock, realbuf, tmpbuf):

    global STARTBUF

    commitcpusurface(
        tmpbuf,
        realbuf,
        int(STARTW) * int(STARTH) * 4,
    )
    STARTBUF = realbuf
    graphicsupdategeometry("startmenu", STARTW, STARTH, realbuf)
    graphicscpudamage(sock, "startmenu", [0, 0, STARTW, STARTH])
    graphicspresent(sock, "startmenu", [0, 0, STARTW, STARTH])


def startmenucleanup(realbuf, tmpbuf):

    global STARTBUF

    if realbuf is not None:
        STARTBUF = realbuf

    try:

        if tmpbuf and os.path.exists(tmpbuf):
            os.remove(tmpbuf)

    except Exception as e:

        log(f"start menu tmp cleanup error {e}")


def paintstartmenu(sock):

    global POWERITEMRECT, POWERMENUITEMS, STARTMENUPAINTERROR

    realbuf = None
    tmpbuf = None
    STARTMENUPAINTERROR = ""

    if graphicsmanagedpaint(sock, "startmenu"):
        return

    try:

        if STARTBUF is None or fillbufferfile is None:
            return

        realbuf, tmpbuf = startmenubegin()

        if realbuf is None or tmpbuf is None:
            return

        fillbufferfile(STARTBUF, STARTW, 0, 0, STARTW, STARTH, (0, 0, 0))

        try:

            fillbufferfile(STARTBUF, STARTW, 0, 0, STARTLEFTW, STARTH, STARTLEFTBG)

        except Exception as e:

            log(f"start left fill error {e}")

        try:

            rightw = STARTW - STARTLEFTW

            if rightw < 0:
                rightw = 0

            fillbufferfile(STARTBUF, STARTW, STARTLEFTW, 0, rightw, STARTH, STARTRIGHTBG)

        except Exception as e:

            log(f"start right fill error {e}")

        try:

            y = STARTPAD + STARTTITLESIZE + STARTPAD

            for item in STARTPLACEITEMS:

                bx = STARTPAD + STARTLEFTINSET

                bw = STARTLEFTW - STARTPAD * 2 - STARTLEFTINSET

                if bw < 0:
                    bw = 0

                bh = STARTITEMH

                label = str(item.get("label", ""))

                tx = bx + 6

                ty = y + (bh - STARTITEMSIZE) // 2

                drawttffile(
                    STARTBUF,
                    STARTW,
                    STARTH,
                    tx,
                    ty,
                    label,
                    STARTITEMCOLOR,
                    STARTITEMSIZE
                )

                item["rect"] = [bx, y, bw, bh]

                y += bh

        except Exception as e:

            log(f"start places draw error {e}")

        try:

            title = "software"

            tx = STARTLEFTW + STARTPAD

            ty = STARTPAD

            drawttffile(STARTBUF, STARTW, STARTH, tx, ty, title, STARTTITLECOLOR, STARTTITLESIZE)

            # draw tiers heading
            title = "tiers"

            tx = STARTPAD + STARTLEFTINSET

            ty = STARTPAD

            drawttffile(
                STARTBUF,
                STARTW,
                STARTH,
                tx,
                ty,
                title,
                STARTTITLECOLOR,
                STARTTITLESIZE
            )

            # start places list below tiers heading
            y = STARTPAD + STARTTITLESIZE + STARTPAD

            for item in STARTSOFTITEMS:
                bx = STARTLEFTW + STARTPAD

                bw = STARTW - STARTLEFTW - STARTPAD * 2

                bh = STARTITEMH

                label = str(item.get("label", ""))

                # Align application names with the software heading.  The
                # row rectangle already begins at the heading inset; applying
                # STARTPAD a second time made every name look indented.
                tx = bx

                ty = y + (bh - STARTITEMSIZE) // 2

                drawttffile(STARTBUF, STARTW, STARTH, tx, ty, label, STARTITEMCOLOR, STARTITEMSIZE)

                item["rect"] = [bx, y, bw, bh]

                y += bh

        except Exception as e:

            log(f"start software draw error {e}")

        try:

            bw = 2

            col = (60, 60, 60)

            fillbufferfile(STARTBUF, STARTW, 0, 0, STARTW, bw, col)

            fillbufferfile(STARTBUF, STARTW, STARTW - bw, 0, bw, STARTH, col)

        except Exception as e:

            log(f"start border draw error {e}")

        try:

            px = STARTPAD

            ph = s(24, 12)

            if ph > STARTH - STARTPAD * 2:
                ph = STARTH - STARTPAD * 2

            pw = ph

            py = STARTH - STARTPAD - ph

            fillbufferfile(STARTBUF, STARTW, px, py, pw, ph, (0, 0, 0))

            powerpath, sw, sh = prepareicon(POWERLOGOPATH, pw, ph)
            out_h = ph
            out_w = pw

            px2 = px + (pw - out_w) // 2

            py2 = py + (ph - out_h) // 2

            if powerpath is not None and sw > 0 and sh > 0:

                blitrawscaledintobuffer(
                    powerpath,
                    sw,
                    sh,
                    STARTBUF,
                    STARTW,
                    px2,
                    py2,
                    out_w,
                    out_h
                )

            POWERITEMRECT = [px, py, pw, ph]

        except Exception as e:

            log(f"start power icon error {e}")
            POWERITEMRECT = None

        try:

            if POWERMENUOPEN and POWERMENUITEMS:

                gap = s(15, 6)

                maxw = 0

                for item in POWERMENUITEMS:

                    label = str(item.get("label", ""))

                    try:

                        tw = measurettffile(label, STARTITEMSIZE)

                    except Exception:

                        tw = 0

                    if tw > maxw:
                        maxw = tw

                lineh = STARTITEMSIZE

                innerw = maxw + gap * 2

                count = len(POWERMENUITEMS)

                innerh = gap + count * lineh + (count - 1) * gap + gap

                bordw = s(1, 1)

                outerw = innerw + bordw * 2

                outerh = innerh + bordw * 2

                bx = px + pw

                by = py - outerh

                if bx + outerw > STARTW - STARTPAD:
                    bx = STARTW - STARTPAD - outerw

                if by < STARTPAD:
                    by = STARTPAD

                fillbufferfile(
                    STARTBUF,
                    STARTW,
                    bx,
                    by,
                    outerw,
                    outerh,
                    STARTLEFTBG
                )

                bordcol = (60, 60, 60)

                fillbufferfile(
                    STARTBUF,
                    STARTW,
                    bx,
                    by,
                    outerw,
                    bordw,
                    bordcol
                )

                fillbufferfile(
                    STARTBUF,
                    STARTW,
                    bx,
                    by + outerh - bordw,
                    outerw,
                    bordw,
                    bordcol
                )

                fillbufferfile(
                    STARTBUF,
                    STARTW,
                    bx,
                    by,
                    bordw,
                    outerh,
                    bordcol
                )

                fillbufferfile(
                    STARTBUF,
                    STARTW,
                    bx + outerw - bordw,
                    by,
                    bordw,
                    outerh,
                    bordcol
                )

                cx = bx + bordw

                cy = by + bordw

                sloty = cy + gap

                for item in POWERMENUITEMS:
                    label = str(item.get("label", ""))

                    tx = cx + gap

                    ty = textbaseliney(sloty, lineh, STARTITEMSIZE)

                    drawttffile(
                        STARTBUF,
                        STARTW,
                        STARTH,
                        tx,
                        ty,
                        label,
                        STARTITEMCOLOR,
                        STARTITEMSIZE
                    )

                    item["rect"] = [cx, sloty, innerw, lineh]

                    sloty += lineh + gap

            else:

                for item in POWERMENUITEMS:
                    item["rect"] = None

        except Exception as e:

            log(f"start power menu error {e}")

        startmenucommit(sock, realbuf, tmpbuf)

        log("start menu painted")

    except Exception as e:

        STARTMENUPAINTERROR = str(e)
        log(f"paintstartmenu error {e}")

    finally:

        startmenucleanup(realbuf, tmpbuf)


def blitrawscaledintobuffer(srcpath, srcw, srch, dstpath, dsttotalw, dstx, dsty, outw, outh):

    if graphicsstrictgpu() and not GRAPHICSBUILDING:
        return True

    try:

        srcw = int(srcw)
        srch = int(srch)
        dsttotalw = int(dsttotalw)
        dstx = int(dstx)
        dsty = int(dsty)
        outw = int(outw)
        outh = int(outh)

        if srcw <= 0 or srch <= 0:
            return

        if outw <= 0 or outh <= 0:
            return

        def compositepixel(source, destination):

            alpha = int(source[3])

            if alpha <= 0:
                return destination

            if alpha >= 255:
                return source

            inverse = 255 - alpha
            return bytes((
                (int(source[0]) * alpha + int(destination[0]) * inverse + 127) // 255,
                (int(source[1]) * alpha + int(destination[1]) * inverse + 127) // 255,
                (int(source[2]) * alpha + int(destination[2]) * inverse + 127) // 255,
                alpha + (int(destination[3]) * inverse + 127) // 255,
            ))

        # Prepared PNG icons already match their destination size. Composite a
        # row at a time so transparent pixels reveal the painted taskbar button.
        if srcw == outw and srch == outh:

            if dsttotalw <= 0 or dstx < 0 or dsty < 0 or dstx + outw > dsttotalw:
                return

            destinationbytes = os.path.getsize(dstpath)
            destinationrowbytes = dsttotalw * 4

            if destinationrowbytes < 4 or (dsty + outh) * destinationrowbytes > destinationbytes:
                return

            rowbytes = srcw * 4

            if os.path.getsize(srcpath) < rowbytes * srch:
                return

            with open(srcpath, "rb") as sf, open(dstpath, "r+b") as df:

                for row in range(srch):

                    pixels = sf.read(rowbytes)

                    if len(pixels) != rowbytes:
                        return

                    doff = ((dsty + row) * dsttotalw + dstx) * 4
                    df.seek(doff)
                    destination = df.read(rowbytes)

                    if len(destination) != rowbytes:
                        return

                    output = bytearray(destination)

                    for offset in range(0, rowbytes, 4):
                        sourcepixel = pixels[offset:offset + 4]
                        output[offset:offset + 4] = compositepixel(
                            sourcepixel,
                            destination[offset:offset + 4])

                    df.seek(doff)
                    df.write(output)

            return

        with open(srcpath, "rb") as sf, open(dstpath, "r+b") as df:

            for row in range(outh):

                try:

                    if outh <= 1:
                        sy = 0

                    else:
                        sy = int(round((row * (srch - 1)) / float(outh - 1)))

                    if sy < 0: sy = 0

                    if sy >= srch: sy = srch - 1

                except Exception:

                    sy = 0

                for col in range(outw):

                    try:

                        if outw <= 1:
                            sx = 0

                        else:
                            sx = int(round((col * (srcw - 1)) / float(outw - 1)))

                        if sx < 0: sx = 0

                        if sx >= srcw: sx = srcw - 1

                    except Exception:

                        sx = 0

                    soff = (sy * srcw + sx) * 4

                    sf.seek(soff)

                    px = sf.read(4)

                    if not px or len(px) < 4:
                        continue

                    dx = dstx + col

                    dy = dsty + row

                    doff = (dy * dsttotalw + dx) * 4

                    df.seek(doff)
                    destination = df.read(4)

                    if len(destination) < 4:
                        continue

                    df.seek(doff)
                    df.write(compositepixel(px, destination))

    except Exception as e:

        log(f"logo blit error {e}")


def fillrectfile(path, totalw, x, y, w, h, color):
    try:

        if w <= 0 or h <= 0:
            return

        try:

            r, g, b = color

            r = int(r) & 0xFF

            g = int(g) & 0xFF

            b = int(b) & 0xFF

        except Exception:

            r = (int(color) >> 16) & 0xFF

            g = (int(color) >> 8) & 0xFF

            b = int(color) & 0xFF

        rowpix = bytes((b, g, r, 0xFF)) * int(w)

        with open(path, "r+b") as f:

            for row in range(h):

                yy = y + row

                if yy < 0:
                    continue

                off = (yy * totalw + x) * 4

                f.seek(off)

                f.write(rowpix)

    except Exception as e:

        log(f"fillrectfile error {e}")


def measurettffile(text, size):
    try:

        if not ensurefont():
            return 0

        TTFFACE.set_pixel_sizes(0, size)

        w = 0

        for ch in text:
            TTFFACE.load_char(ch)

            w += (TTFFACE.glyph.advance.x >> 6)

        return int(w)

    except Exception:
        return 0


def textbaseliney(by, recth, size):
    try:

        if not ensurefont():
            return by + (recth - size) // 2

        try:

            TTFFACE.set_pixel_sizes(0, size)

        except Exception:

            return by + (recth - size) // 2

        asc = TTFFACE.size.ascender >> 6

        desc = -(TTFFACE.size.descender >> 6)

        lineh = asc + desc

        base = by + (recth - lineh) // 2 + asc

        return base - size

    except Exception as e:

        log(f"textbaseline error {e}")
        return by + (recth - size) // 2


def drawttffile(path, totalw, totalh, x, y, text, color, size):

    if graphicsstrictgpu() and not GRAPHICSBUILDING:
        return True

    try:

        if not ensurefont():
            return

        TTFFACE.set_pixel_sizes(0, size)

        r_fg = (int(color) >> 16) & 0xFF

        g_fg = (int(color) >> 8) & 0xFF

        b_fg = int(color) & 0xFF

        pen_x = int(x)

        pen_y = int(y) + size

        with open(path, "r+b") as df:

            for ch in text:

                TTFFACE.load_char(ch)

                TTFFACE.glyph.render(0)

                bmp = TTFFACE.glyph.bitmap

                buf = bmp.buffer

                bw = bmp.width

                bh = bmp.rows

                top = TTFFACE.glyph.bitmap_top

                left = TTFFACE.glyph.bitmap_left

                pitch = bmp.pitch

                for row in range(bh):

                    rowStart = row * pitch

                    for col in range(bw):

                        try:

                            a = buf[rowStart + col] / 255.0

                        except Exception:

                            a = 0.0

                        if a <= 0.0:
                            continue

                        fx = pen_x + left + col

                        fy = pen_y - top + row

                        if fx < 0 or fy < 0 or fx >= totalw or fy >= totalh:
                            continue

                        try:

                            off = (fy * totalw + fx) * 4

                            df.seek(off)

                            bg = df.read(4)

                            if not bg or len(bg) < 4:
                                bg_b = bg_g = bg_r = 0

                            else:

                                bg_b, bg_g, bg_r, _ = bg[0], bg[1], bg[2], bg[3]

                        except Exception:

                            bg_b = bg_g = bg_r = 0

                        inv = 1.0 - a

                        r = int(r_fg * a + bg_r * inv + 0.5) & 0xFF

                        g = int(g_fg * a + bg_g * inv + 0.5) & 0xFF

                        b = int(b_fg * a + bg_b * inv + 0.5) & 0xFF

                        df.seek(off)

                        df.write(bytes((b, g, r, 0xFF)))

                pen_x += (TTFFACE.glyph.advance.x >> 6)

    except Exception as e:

        log(f"drawttffile error {e}")


# window functions
def mapwin(sock, wid, role):
    try:

        sendline(sock, {"op": "MAP", "winid": wid})

        AWAITMAP[wid] = {"t": time.time(), "role": role}

        log(f"map sent {role} {wid}")

    except Exception as e:

        log(f"map error {e}")


def mapretry(sock):
    try:

        now = time.time()

        for wid, meta in list(AWAITMAP.items()):

            if meta.get("role") == "startmenu" and not STARTWANTED:
                AWAITMAP.pop(wid, None)
                continue

            tries = meta.get("n", 0)

            if tries >= 10:
                role = meta.get("role", "?")

                log(f"map timeout {role} {wid}")

                AWAITMAP.pop(wid, None)

                continue

            if now - meta["t"] >= 0.5:

                meta["t"] = now

                meta["n"] = tries + 1

                sendline(sock, {"op": "MAP", "winid": wid})

                if (tries % 3) == 0:
                    log(f"remap {meta.get('role', '?')} {wid} try={meta['n']}")

    except Exception as e:

        log(f"mapretry error {e}")


def requesttaskbar(sock):
    try:

        # set role and location
        globals()["TASKBARROLE"] = "taskbar"

        y = DESKTOPH - TASKBARH

        # send create
        sendline(sock, {
            "op": "CREATE_WINDOW",
            "w": DESKTOPW,
            "h": TASKBARH,
            "x": 0,
            "y": y,
            "title": "taskbar",
            "role": TASKBARROLE
        })

        # old float timestamp (kept for inline fallback timing)
        globals()["TASKBARREQ"] = time.time()

        # new boolean guards for the retry gate
        globals()["TASKBARREQUESTED"] = True

        globals()["TASKBARCREATETS"] = time.time()

        # bump try count
        globals()["TASKBARTRY"] = TASKBARTRY + 1

        # log
        log(f"taskbar create sent try={TASKBARTRY} role={TASKBARROLE} at 0,{y}")

    except Exception as e:

        # request taskbar error
        log(f"requesttaskbar error {e}")


def taskbarresizegeometry():
    """Publish final taskbar surface geometry before a managed repaint."""
    y = max(0, int(DESKTOPH) - int(TASKBARH))
    graphicsupdategeometry("taskbar", DESKTOPW, TASKBARH, TASKBARBUF)
    return y


def requesttooltip(sock):
    try:

        if TOOLTIPID is not None:
            return

        sendline(sock, {
            "op": "CREATE_WINDOW",
            "w": s(320, 160),
            "h": s(64, 32),
            "x": 0,
            "y": 0,
            "title": "tooltip",
            "role": "tooltip"
        })

        log("tooltip create sent")

    except Exception as e:

        log(f"requesttooltip error {e}")


def requestvolumebar(sock):

    try:

        if VOLUMEID is not None:
            return

        sendline(sock, {
            "op": "CREATE_WINDOW",
            "w": int(VOLUMEW),
            "h": int(VOLUMEH),
            "x": 0,
            "y": 0,
            "title": "volumebar",
            "role": "volumebar"
        })

        log("volumebar create sent")

    except Exception as e:

        log(f"requestvolumebar error {e}")


def requestinstancelist(sock):
    global LISTREQUESTED

    try:

        LISTREQUESTED = True

        return

    except Exception as e:

        log(f"requestinstancelist error {e}")


def retrysendtaskbar(sock):
    try:

        # already have an id
        if TASKBARID is not None:
            return

        # never requested
        if not TASKBARREQUESTED:
            return

        # already created, waiting on MAP
        if TASKBARCREATED:
            return

        # another taskbar is waiting to map
        for wid, meta in list(AWAITMAP.items()):

            if meta.get("role") == "taskbar":
                return

        # rate limit
        if (time.time() - TASKBARCREATETS) < 0.5:
            return

        # resend single request
        requesttaskbar(sock)

    except Exception as e:

        # retry send taskbar error
        log(f"retrysendtaskbar error {e}")


# events
def handlewelcome(sock, msg):

    try:

        globals()["GOTWELCOME"] = True

        globals()["GRAPHICSCAPS"] = dict(msg.get("graphics") or {})

        try:

            fb = msg.get("fb") or {}

            w = int(fb.get("w", 0))

            h = int(fb.get("h", 0))

        except Exception:

            w = 0

            h = 0

        if w > 0 and h > 0:

            globals()["DESKTOPW"] = w

            globals()["DESKTOPH"] = h

            log(f"welcome fb {w}x{h}")

        preference = msg.get("ui_scale", uiscalefactor())
        applyscale(preference)

        initttffont(FONTPATH, BRICKFONTSIZE)

        # redundancy: read fb.size only as a fallback / sanity check
        filew, fileh = readfbsize()

        if filew > 0 and fileh > 0:

            if DESKTOPW <= 0 or DESKTOPH <= 0:

                globals()["DESKTOPW"] = filew

                globals()["DESKTOPH"] = fileh

                applyscale(preference)

                initttffont(FONTPATH, BRICKFONTSIZE)

                log(f"fb.size fallback {DESKTOPW}x{DESKTOPH}")

            elif filew != DESKTOPW or fileh != DESKTOPH:

                log(f"fb.size mismatch {filew}x{fileh} vs welcome {DESKTOPW}x{DESKTOPH}")

        sendline(sock, {"op": "CREATE_WINDOW", "w": DESKTOPW, "h": DESKTOPH, "x": 0, "y": 0, "title": "expanse", "role": "desktop"})

        log("desktop create sent")

    except Exception as e:

        log(f"welcome handler error {e}")


def handleerror(sock, msg):
    try:

        graphicsresponse(sock, msg)

        code = str(msg.get("code", ""))

        wid = int(msg.get("winid", 0))

        # log server error
        detail = msg.get("detail", "")

        log(f"server error code={code} winid={wid} detail={detail}")

        # Only a MAP failure invalidates a pending map.  Graphics/DAMAGE
        # errors can arrive while the first asynchronous managed scene is
        # awaiting its acknowledgement; treating those as MAP failures used
        # to create replacement taskbars until the client window limit was
        # exhausted.
        if wid in AWAITMAP and code in ("map_failed", "unknown_window", "not_owner"):

            AWAITMAP.pop(wid, None)

            if wid == TASKBARID:
                log("map failed for taskbar; will request a new taskbar window")

                globals()["TASKBARID"] = None

                globals()["TASKBARBUF"] = None

                requesttaskbar(sock)

    except Exception as e:

        log(f"handleerror error {e}")


def handlecreated(sock, msg):
    try:

        wid = int(msg.get("winid", 0))

        buf = msg.get("buffer") or msg.get("buf") or msg.get("bufpath")

        role = str(msg.get("role", ""))

        createdw = int(msg.get("w", 0) or 0)

        createdh = int(msg.get("h", 0) or 0)

    except Exception as e:

        log(f"created parse error {e}")

        return

    if wid <= 0 or not buf:
        log("created without buffer/winid; ignoring")

        return

    try:

        if role == "desktop" or (not role and DESKTOPID is None):

            globals()["DESKTOPID"] = wid

            globals()["DESKTOPBUF"] = buf

            graphicsregister("desktop", wid, buf, DESKTOPW, DESKTOPH)

            log(f"desktop created {wid} buffer {buf}")

            paintdesktop(sock)

            mapwin(sock, wid, "desktop")

            sendworkarea(sock)

            return

        if role == "taskbar" or (not role and TASKBARID is None):

            globals()["TASKBARID"] = wid

            globals()["TASKBARBUF"] = buf

            globals()["TASKBARCREATED"] = True

            graphicsregister("taskbar", wid, buf, DESKTOPW, TASKBARH)

            log(f"taskbar created {wid} buffer {buf}")

            painttaskbar(sock)

            mapwin(sock, wid, "taskbar")

            return

        if role == "startmenu":

            globals()["STARTID"] = wid

            globals()["STARTBUF"] = buf

            graphicsregister("startmenu", wid, buf, STARTW, STARTH)

            log(f"start menu created {wid} buffer {buf}")

            if not STARTWANTED:
                return

            paintstartmenu(sock)

            mapwin(sock, wid, "startmenu")

            return

        if role == "tooltip":

            globals()["TOOLTIPID"] = wid

            globals()["TOOLTIPBUF"] = buf

            globals()["TOOLTIPMAPPED"] = False

            graphicsregister(
                "tooltip", wid, buf,
                createdw or s(320, 160),
                createdh or s(64, 32))

            log(f"tooltip created id={wid}")

            return

        if role == "volumebar":

            globals()["VOLUMEID"] = wid

            globals()["VOLUMEBUF"] = buf

            globals()["VOLUMEMAPPED"] = False

            graphicsregister("volumebar", wid, buf, createdw or VOLUMEW, createdh or VOLUMEH)

            log(f"volumebar created id={wid}")

            if VOLUMEPENDING:

                showvolumebar(sock)

            return

        if role == "instancelist":

            globals()["LISTID"] = wid

            globals()["LISTBUF"] = buf

            globals()["LISTMAPPED"] = False

            graphicsregister("instancelist", wid, buf, createdw or 1, createdh or 1)

            log(f"instancelist created id={wid}")

            if LISTPENDINGGROUP is not None and LISTPENDINGANCHOR is not None:
                g = LISTPENDINGGROUP

                a = LISTPENDINGANCHOR

                globals()["LISTPENDINGGROUP"] = None

                globals()["LISTPENDINGANCHOR"] = None

                showinstancelist(sock, g, a)

            return

        if role == "taskmenu":

            globals()["TASKMENUID"] = wid

            globals()["TASKMENUBUF"] = buf

            globals()["TASKMENUMAPPED"] = False

            graphicsregister("taskmenu", wid, buf, createdw or TASKMENUW, createdh or TASKMENUITEMH)

            log(f"taskmenu created id={wid}")

            if TASKMENUPENDINGDESKTOP is not None and TASKMENUPENDINGANCHOR is not None:
                pending = dict(TASKMENUPENDINGDESKTOP)
                anchor = list(TASKMENUPENDINGANCHOR)
                globals()["TASKMENUPENDINGDESKTOP"] = None
                globals()["TASKMENUPENDINGANCHOR"] = None
                showdesktopcontextmenu(
                    sock,
                    pending.get("context", {}),
                    anchor,
                    view=bool(pending.get("view")),
                )

            elif TASKMENUPENDINGTASKBAR and TASKMENUPENDINGANCHOR is not None:
                anchor = list(TASKMENUPENDINGANCHOR)
                globals()["TASKMENUPENDINGTASKBAR"] = False
                globals()["TASKMENUPENDINGANCHOR"] = None
                showtaskbarcontextmenu(sock, anchor)

            elif TASKMENUPENDINGGROUP is not None and TASKMENUPENDINGANCHOR is not None:
                g = TASKMENUPENDINGGROUP

                a = TASKMENUPENDINGANCHOR

                globals()["TASKMENUPENDINGGROUP"] = None

                globals()["TASKMENUPENDINGANCHOR"] = None

                showtaskmenu(sock, g, a)

            elif TASKMENUPENDINGCONTEXT is not None and TASKMENUPENDINGANCHOR is not None:
                result = dict(TASKMENUPENDINGCONTEXT)
                anchor = list(TASKMENUPENDINGANCHOR)
                globals()["TASKMENUPENDINGCONTEXT"] = None
                globals()["TASKMENUPENDINGANCHOR"] = None
                showsearchcontextmenu(sock, result, anchor)

            return

        if role == "search":

            globals()["SEARCHID"] = wid
            globals()["SEARCHBUF"] = buf
            globals()["SEARCHMAPPED"] = False
            globals()["SEARCHPENDING"] = False
            width = createdw or SEARCHPANELW
            height = createdh or SEARCHROWH
            graphicsregister("search", wid, buf, width, height)
            log(f"search created id={wid}")
            showsearch(sock)
            return

    except Exception as e:

        log(f"created handle error {e}")

        return


def handlemapped(sock, msg):
    try:

        wid = int(msg.get("winid", 0))

    except Exception as e:

        log(f"mapped parse error {e}")

        return

    if wid == DESKTOPID:
        log("desktop mapped")

        AWAITMAP.pop(wid, None)

        requesttaskbar(sock)

        requesttooltip(sock)

        requestinstancelist(sock)

        return

    if wid == TASKBARID:
        log("taskbar mapped")

        AWAITMAP.pop(wid, None)

        return

    if wid == STARTID:
        log("start menu mapped")

        AWAITMAP.pop(wid, None)

        if not STARTWANTED:
            globals()["STARTMAPPED"] = False
            globals()["STARTVISIBLE"] = False
            graphicssuspend(sock, "startmenu")
            sendline(sock, {"op": "UNMAP", "winid": wid})
            return

        globals()["STARTMAPPED"] = True

        globals()["STARTVISIBLE"] = True

        sendline(sock, {"op": "FOCUS_SET", "winid": wid})

        return

    if wid == LISTID:

        globals()["LISTMAPPED"] = True

        return

    if wid == TASKMENUID:

        globals()["TASKMENUMAPPED"] = True

        return

    if wid == SEARCHID:

        globals()["SEARCHMAPPED"] = True
        globals()["SEARCHPENDING"] = False
        sendline(sock, {"op": "FOCUS_SET", "winid": wid})
        painttaskbar(sock)
        return

    if wid != DESKTOPID and wid != TASKBARID and wid != STARTID and wid != TOOLTIPID and wid != LISTID and wid != SEARCHID:
        sendline(sock, {"op": "FOCUS_SET", "winid": wid})


def handleunmapped(sock, msg):

    try:
        wid = int(msg.get("winid", 0))
    except Exception:
        return

    if wid == STARTID:
        globals()["STARTMAPPED"] = False
        globals()["STARTVISIBLE"] = False

        # WINDOW_UNMAPPED is observed server state, not user intent. A close
        # followed immediately by reopen can receive this acknowledgement
        # after a newer MAP was queued. Reassert the desired open state and
        # replace its retry record rather than cancelling the newer request.
        if STARTWANTED:

            try:
                paintstartmenu(sock)
            except Exception as error:
                log(f"start menu remap paint error {error}")

            mapwin(sock, wid, "startmenu")
        else:
            AWAITMAP.pop(wid, None)

        return

    if wid == SEARCHID:
        globals()["SEARCHMAPPED"] = False
        globals()["SEARCHPENDING"] = False
        return

    AWAITMAP.pop(wid, None)


def handlefbsize(sock, msg):

    try:

        w = int(msg.get("w", 0))

        h = int(msg.get("h", 0))

    except Exception as e:

        log(f"fb_size parse error {e}")

        return

    if w <= 0 or h <= 0:
        return

    try:
        preference = max(
            0.5,
            min(3.0, float(msg.get(
                "ui_scale", uiscalefactor()))))
    except Exception:
        preference = uiscalefactor()

    sizechanged = bool(w != DESKTOPW or h != DESKTOPH)
    targetscale = max(
        0.5,
        min(3.0, scalefromfb(w, h) * preference),
    )
    scalechanged = abs(float(targetscale) - float(SCALE)) > 0.001

    if not sizechanged and not scalechanged:
        return

    for role in list(GRAPHICSSURFACES):
        graphicssuspend(sock, role)

    globals()["DESKTOPW"] = w

    globals()["DESKTOPH"] = h

    applyscale(preference)

    initttffont(FONTPATH, BRICKFONTSIZE)

    log(f"fb_size update {w}x{h} scale={SCALE:.3f}")

    # redundancy check: fb.size file (do not override authoritative FB_SIZE)
    filew, fileh = readfbsize()

    if filew > 0 and fileh > 0:

        if DESKTOPW <= 0 or DESKTOPH <= 0:

            globals()["DESKTOPW"] = filew

            globals()["DESKTOPH"] = fileh

            applyscale(preference)

            initttffont(FONTPATH, BRICKFONTSIZE)

            log(f"fb.size fallback after FB_SIZE {DESKTOPW}x{DESKTOPH}")

        elif filew != DESKTOPW or fileh != DESKTOPH:

            log(f"fb.size mismatch {filew}x{fileh} vs FB_SIZE {DESKTOPW}x{DESKTOPH}")

    try:

        if DESKTOPID is not None:
            # WindowServer owns display-driven desktop resizing.  Update the
            # retained scene geometry without issuing the client-forbidden
            # desktop RESIZE request.
            graphicsupdategeometry(
                "desktop", DESKTOPW, DESKTOPH, DESKTOPBUF)
            paintdesktop(sock)

    except Exception as e:

        log(f"desktop resize/paint error {e}")

    try:

        if TASKBARID is not None:
            # Managed drawing clips every command to the registered surface.
            # Update that surface before building the new taskbar scene so
            # right-anchored controls are not clipped to the previous mode.
            y = taskbarresizegeometry()

            sendline(sock, {"op": "RESIZE", "winid": TASKBARID, "w": DESKTOPW, "h": TASKBARH})

            sendline(sock, {"op": "MOVE", "winid": TASKBARID, "x": 0, "y": y})

            painttaskbar(sock)

            sendworkarea(sock)

    except Exception as e:

        log(f"taskbar resize/move/paint error {e}")

    try:

        clearhovertooltip(sock)
        closetaskmenu(sock)
        hidevolumebar(sock)
        closesearch(sock)

    except Exception as e:

        log(f"transient resize cleanup error {e}")

    try:

        if STARTID is not None:

            y = max(0, DESKTOPH - TASKBARH - STARTH)
            sendline(sock, {
                "op": "RESIZE",
                "winid": STARTID,
                "w": STARTW,
                "h": STARTH,
            })
            sendline(sock, {
                "op": "MOVE",
                "winid": STARTID,
                "x": 0,
                "y": y,
            })
            graphicsupdategeometry(
                "startmenu", STARTW, STARTH, STARTBUF)

            # Build the resized retained scene even while the menu is hidden,
            # so its next map cannot expose stale CPU pixels or old scale.
            paintstartmenu(sock)

            if STARTMAPPED:
                openstartmenu(sock)

    except Exception as e:

        log(f"start menu resize/paint error {e}")


def handlebutton(sock, msg):

    try:

        wid = int(msg.get("winid", 0))

    except Exception as e:

        log(f"button parse error {e}")

        return

    try:

        if SEARCHID is not None and wid == SEARCHID:

            if str(msg.get("state", "down")) != "up":
                return

            button = int(msg.get("button", 1))
            if button not in (1, 2, 3):
                return

            index = findsearchresultat(
                int(msg.get("x", 0)),
                int(msg.get("y", 0)),
            )

            if button in (2, 3):
                if index is None:
                    closetaskmenu(sock)
                    return
                globals()["SEARCHSELECTED"] = index
                globals()["SEARCHHOVER"] = index
                paintsearch(sock)
                showsearchcontextmenu(sock, SEARCHRESULTS[index], [
                    int(msg.get("absx", 0)),
                    int(msg.get("absy", 0)),
                    1,
                    1,
                ])
                return

            if TASKMENUMAPPED:
                closetaskmenu(sock)

            control = findsearchcontrolat(
                int(msg.get("x", 0)),
                int(msg.get("y", 0)),
            )

            if control == "open-array":
                opensearchinarray(sock)
                return

            if control is not None:
                togglesearchfilter(sock, control)
                return

            if index is None:
                return

            activatesearchresult(sock, index)
            return

    except Exception as e:

        log(f"search click handler error {e}")

    try:

        if VOLUMEID is not None and wid == VOLUMEID:

            st = str(msg.get("state", "down"))

            if st == "down":

                globals()["VOLUMEAUTOCLOSEAT"] = 0.0

                try:

                    ay = int(msg.get("absy", 0))

                except Exception:

                    ay = 0

                if VOLUMERECT and len(VOLUMERECT) == 4:

                    vx, vy, vw, vh = VOLUMERECT

                    y = int(ay - vy)

                else:

                    y = 0

                globals()["VOLUMEDRAG"] = True

                v = volumeposy(int(y), int(VOLUMEH))

                v = volumedragvalue(v)

                volumeflushdrag(sock, force=True)

                return

            if st == "up":

                v = volumeenddrag()

                if v is not None:

                    # Reassert and repaint the final pointer value so a delayed
                    # service acknowledgement cannot leave the released slider
                    # showing an intermediate frame.
                    volumeset(v)

                    paintvolumebar(sock)

                return

    except Exception as e:

        log(f"volumebar click handler error {e}")

    try:

        if LISTID is not None and wid == LISTID:

            st = str(msg.get("state", "down"))

            if st != "up":
                return

            ax = int(msg.get("absx", 0))

            ay = int(msg.get("absy", 0))

            closehit = findlistcloseat(ax, ay)

            if closehit is not None and closehit > 0:

                sendline(sock, {"op": "WINDOW_CLOSE", "winid": int(closehit)})

                clearhovertooltip(sock)

                return

            hit = findlistitemat(ax, ay)

            if hit is not None and hit > 0:

                toggletaskbarwindow(sock, hit)

                clearhovertooltip(sock)

                # Selecting a window ends the current instance-list hover.
                # Otherwise the pending group can map the list again on the
                # next hover update while the pointer is still over its row.
                globals()["HOVERPENDINGGROUP"] = None

                globals()["HOVERPENDINGGROUPTS"] = 0.0

                return

            clearhovertooltip(sock)

            return

    except Exception as e:

        log(f"instancelist click handler error {e}")

    try:

        if TASKMENUID is not None and wid == TASKMENUID:

            st = str(msg.get("state", "down"))

            if st != "up":
                return

            ax = int(msg.get("absx", 0))

            ay = int(msg.get("absy", 0))

            action = findtaskmenuitemat(ax, ay)

            if not action:
                closetaskmenu(sock)

                return

            context = dict(TASKMENUCONTEXT) if TASKMENUCONTEXT is not None else None
            taskbarcontext = bool(TASKMENUTASKBAR)
            desktopcontext = dict(TASKMENUDESKTOP) if TASKMENUDESKTOP is not None else None
            group = TASKMENUGROUP

            if desktopcontext is not None and action == "desktop-view":
                showdesktopcontextmenu(
                    sock,
                    desktopcontext,
                    TASKMENUANCHOR or [ax, ay, 1, 1],
                    view=True,
                )
                return

            closetaskmenu(sock)

            if context is not None:
                runsearchcontextaction(sock, context, action)
                return

            if taskbarcontext:
                runtaskbarcontextaction(sock, action)
                return

            if desktopcontext is not None:
                rundesktopcontextaction(sock, desktopcontext, action)
                return

            if not group:
                return

            if action == "launch":
                launchgroup(group)

                if TASKBARID is not None and TASKBARBUF is not None:
                    painttaskbar(sock)

                return

            if action == "pin":

                if grouppinned(group):
                    unpintaskbar(group)

                else:
                    pintaskbar(group)

                if TASKBARID is not None and TASKBARBUF is not None:
                    painttaskbar(sock)

                return

            if action == "close":
                closegroup(sock, group)

                return

            return

    except Exception as e:

        log(f"taskmenu click handler error {e}")

    try:

        # close start menu if open and click is outside start menu and taskbar
        if STARTVISIBLE and STARTMAPPED and wid != STARTID and wid != TASKBARID:

            st = str(msg.get("state", "down"))

            if st == "up":
                closestartmenu(sock)

                return

    except Exception as e:

        log(f"startmenu outside click close error {e}")

    try:

        if wid == STARTID:
            handlestartmenuclick(sock, msg)

            return

    except Exception as e:

        log(f"start click dispatch error {e}")

    try:

        if DESKTOPID is not None and wid == DESKTOPID:
            handledesktopbutton(sock, msg)
            return

    except Exception as e:

        log(f"desktop click dispatch error {e}")

    try:

        if TASKBARID is not None and wid != TASKBARID:
            return

        if TASKBARID is None and wid != DESKTOPID:
            return

        st = str(msg.get("state", "down"))

        btn = int(msg.get("button", 1))

        ax = int(msg.get("absx", 0))

        ay = int(msg.get("absy", 0))

        try:
            taskbartarget = findtaskbargroupat(ax, ay)
        except Exception:
            taskbartarget = None

        if btn in (2, 3) and taskbartarget is None:
            if st == "up":
                showtaskbarcontextmenu(sock, [ax, ay, 1, 1])
            return

        # The search field owns the band between Start and the window buttons.
        try:
            searchhit = False
            if SEARCHRECT and len(SEARCHRECT) == 4:
                sx, sy, sw, sh = SEARCHRECT
                searchhit = sx <= ax < sx + sw and sy <= ay < sy + sh

            if searchhit:
                if btn == 1 and st == "up":
                    focussearchinput(sock)
                return

            if SEARCHINPUTFOCUSED and st == "down":
                closesearch(sock)

        except Exception as e:
            log(f"taskbar search click error {e}")

        # audio icon click toggles volumebar
        try:

            rect = globals().get("AUDIOICONRECT")

            if rect and len(rect) == 4:

                axx, ayy, aww, ahh = rect

                if axx <= ax < axx + aww and ayy <= ay < ayy + ahh:

                    if btn == 1 and st == "down":

                        if not CURRENTAUDIOAVAIL:
                            return

                        globals()["VOLUMEAUTOCLOSEAT"] = 0.0

                        if VOLUMEMAPPED:
                            hidevolumebar(sock)

                        else:
                            showvolumebar(sock)

                    clearhovertooltip(sock)

                    return

        except Exception as e:

            log(f"audio click rect error {e}")

        if LISTMAPPED and LISTRECT and len(LISTRECT) == 4 and st == "up":

            wid = findlistitemat(ax, ay)

            if wid is not None and wid > 0:
                toggletaskbarwindow(sock, wid)

                clearhovertooltip(sock)

                return

            lx, ly, lw, lh = LISTRECT

            if not (lx <= ax < lx + lw and ly <= ay < ly + lh):
                clearhovertooltip(sock)

        # show desktop strip hit-test
        try:

            rect = globals().get("SHOWDESKTOP_RECT")

            if rect and len(rect) == 4:

                sx, sy, sw, sh = rect

                if sx <= ax < sx + sw and sy <= ay < sy + sh:

                    if st == "up":
                        showdesktop(sock)

                        return

        except Exception as e:

            log(f"showdesktop click error {e}")

        if TASKMENUMAPPED and TASKMENURECT and len(TASKMENURECT) == 4 and st == "up":

            mx, my, mw, mh = TASKMENURECT

            if not (mx <= ax < mx + mw and my <= ay < my + mh):
                closetaskmenu(sock)

        # end drag on left button UP no matter where we release
        if btn == 1 and st == "up":

            if DRAGTASKACTIVE and DRAGTASKGROUP is not None:

                moved = bool(DRAGTASKMOVED)

                globals()["DRAGTASKACTIVE"] = False

                globals()["DRAGTASKGROUP"] = None

                if moved:

                    savetaskbarorder()

                    if TASKBARID is not None and TASKBARBUF is not None:
                        painttaskbar(sock)

                    return

        try:

            target = taskbartarget

        except Exception:

            target = None

        if target is not None:

            # start drag on left click DOWN
            if btn == 1 and st == "down":

                r = TASKBARGROUPRECTS.get(target)

                if r and len(r) == 4:
                    rx, ry, rw, rh = r

                    globals()["DRAGTASKGROUP"] = target

                    globals()["DRAGTASKACTIVE"] = True

                    globals()["DRAGTASKMOVED"] = False

                    globals()["DRAGTASKSTARTX"] = int(ax)

                    globals()["DRAGTASKSTARTY"] = int(ay)

                    globals()["DRAGTASKX"] = int(ax)

                    globals()["DRAGTASKY"] = int(ay)

                    globals()["DRAGTASKOFFSETX"] = int(ax - rx)

                return

            # right click DOWN: if instancelist is open, close it immediately
            if btn in (2, 3) and st == "down":

                if LISTMAPPED:
                    clearhovertooltip(sock)

                return

            # right click UP opens task menu (and list stays closed)
            if btn in (2, 3) and st == "up":

                anchorrect = TASKBARGROUPRECTS.get(target)

                if anchorrect and len(anchorrect) == 4:

                    if LISTMAPPED:
                        clearhovertooltip(sock)

                    showtaskmenu(sock, target, anchorrect)

                return

            # left click UP: if we were dragging, drop (and do NOT treat as click)
            if btn == 1 and st == "up":

                if DRAGTASKACTIVE and DRAGTASKGROUP == target:

                    globals()["DRAGTASKACTIVE"] = False

                    globals()["DRAGTASKGROUP"] = None

                    if DRAGTASKMOVED:
                        savetaskbarorder()

                    if TASKBARID is not None and TASKBARBUF is not None:
                        painttaskbar(sock)

                    return

            if st != "up":
                return

            # normal click behavior (only happens if not dragging)
            g = TASKBARGROUPITEMS.get(target)

            if g:

                wids = list(g.get("wids", []))

            else:

                wids = []

            if len(wids) > 1:

                anchorrect = TASKBARGROUPRECTS.get(target)

                if anchorrect and len(anchorrect) == 4:
                    showinstancelist(sock, target, anchorrect)

                return

            if len(wids) == 1:

                wid = int(wids[0])

                if wid > 0:
                    toggletaskbarwindow(sock, wid)

                return

            if len(wids) == 0:

                launchgroup(target)

                if TASKBARID is not None and TASKBARBUF is not None:
                    painttaskbar(sock)

                return

            return

        abs_y0 = DESKTOPH - TASKBARH + (TASKBARH - LAUNCHH) // 2

        inside_logo = (
                LOGOX <= ax < LOGOX + LOGOW and
                abs_y0 <= ay < abs_y0 + LOGOH
        )

        if not inside_logo:
            return

        if st == "up":
            togglestartmenu(sock)

    except Exception as e:

        log(f"button handler error {e}")


def handlebuttonglobal(sock, msg):

    global DRAGTASKACTIVE, DRAGTASKGROUP, DRAGTASKMOVED

    try:

        try:

            wid = int(msg.get("winid", 0))

        except Exception:

            wid = 0

        st = str(msg.get("state", "down"))

        try:

            btn = int(msg.get("button", 1))

        except Exception:

            btn = 1

        if st == "up" and btn == 1:

            if DRAGTASKACTIVE and DRAGTASKGROUP is not None:

                moved = bool(DRAGTASKMOVED)

                globals()["DRAGTASKACTIVE"] = False

                globals()["DRAGTASKGROUP"] = None

                if moved:

                    savetaskbarorder()

                if TASKBARID is not None and TASKBARBUF is not None:
                    painttaskbar(sock)

        if st == "down":

            if SEARCHINPUTFOCUSED and wid not in (SEARCHID, TASKBARID):
                closesearch(sock)

            if STARTVISIBLE and STARTMAPPED:

                if wid != STARTID and wid != TASKBARID:
                    closestartmenu(sock)

            if TASKMENUMAPPED:

                if wid != TASKMENUID:
                    closetaskmenu(sock)

            if VOLUMEMAPPED:

                try:

                    ax = int(msg.get("absx", 0))

                    ay = int(msg.get("absy", 0))

                except Exception:

                    ax = 0

                    ay = 0

                inside = False

                if VOLUMERECT and len(VOLUMERECT) == 4:

                    vx, vy, vw, vh = VOLUMERECT

                    if vx <= ax < vx + vw and vy <= ay < vy + vh:
                        inside = True

                onicon = False

                if AUDIOICONRECT and len(AUDIOICONRECT) == 4:

                    ix, iy, iw, ih = AUDIOICONRECT

                    if ix <= ax < ix + iw and iy <= ay < iy + ih:
                        onicon = True

                if (not inside) and (not onicon) and wid != VOLUMEID:
                    hidevolumebar(sock)

    except Exception as e:

        log(f"handlebuttonglobal error {e}")


# main
def main():

    global NET_NEXT_TS, NET_INTERVAL, GOTWELCOME

    try:

        log("expanse starting")

        initttffont(FONTPATH, BRICKFONTSIZE)

        username = getusername()

        initstartitems(username)

        initdesktop(username)

        s = opensocket()

        loadtaskbarpins()

        loadtaskbarorder()

        loadtaskbarsettings()

        loadmasterimagesettings(force=True)

        if s is None:
            log("cannot open window server socket; aborting")

            return

        sendline(s, {"op": "HELLO"})

        sendline(s, {"op": "SUBSCRIBE", "types": ["fbsize"]})

        t0 = time.time()

        audiotick()

        while RUN:

            try:

                events = SEL.select(timeout=0.05)

            except Exception as e:

                log(f"select error {e}")

                events = []

            for key, mask in events:

                kind = key.data.get("kind")

                if kind == "server":

                    for m in recvlines(key.fileobj):

                        op = m.get("op", "")

                        if op == "WELCOME":
                            handlewelcome(s, m)

                        elif op == "FB_SIZE":
                            handlefbsize(s, m)

                        elif op == "ERROR":
                            handleerror(s, m)

                        elif op in ("GRAPHICS_COMMITTED", "GRAPHICS_CLEARED"):
                            graphicsresponse(s, m)

                        elif op == "WINDOW_CREATED":
                            handlecreated(s, m)

                        elif op == "WINDOW_MAPPED":
                            handlemapped(s, m)

                        elif op == "WINDOW_UNMAPPED":
                            handleunmapped(s, m)

                        elif op == "POINTER_BUTTON":

                            # try:
                            #     log(
                            #         f"input mouse button "
                            #         f"winid={m.get('winid')} "
                            #         f"state={m.get('state')} "
                            #         f"absx={m.get('absx')} "
                            #         f"absy={m.get('absy')}"
                            #     )
                            # except Exception:
                            #     pass

                            handlebutton(s, m)

                        elif op == "POINTER_BUTTON_GLOBAL":

                            # try:
                            #     log(
                            #         f"input mouse button global "
                            #         f"winid={m.get('winid')} "
                            #         f"state={m.get('state')}"
                            #     )
                            # except Exception:
                            #     pass

                            handlebuttonglobal(s, m)

                        elif op == "POINTER_MOTION":

                            # try:
                            #     log(
                            #         f"input mouse motion "
                            #         f"winid={m.get('winid')} "
                            #         f"absx={m.get('absx')} "
                            #         f"absy={m.get('absy')}"
                            #     )
                            # except Exception:
                            #     pass

                            handlepointermotion(s, m)

                        elif op == "SCROLL":

                            handlevolumescroll(s, m)
                            handlesearchscroll(s, m)

                        elif op == "KEY":

                            handlesearchkey(s, m)

                            handledesktopkey(s, m)

                        elif op == "TEXT":

                            handlesearchtext(s, m)

                            handledesktoptext(s, m)

                        elif op == "TASKBAR_WINDOW_CREATED":
                            handletaskbarcreated(s, m)

                        elif op == "TASKBAR_WINDOW_MAPPED":
                            handletaskbarmapped(s, m)

                        elif op == "TASKBAR_WINDOW_UNMAPPED":
                            handletaskbarunmapped(s, m)

                        elif op == "TASKBAR_WINDOW_DESTROYED":
                            handletaskbardestroyed(s, m)

                        elif op == "TASKBAR_WINDOW_FOCUS":
                            handletaskbarfocus(s, m)

                        if op == "TASKBAR_WINDOW_CURRENT":
                            handletaskbarcurrent(s, m)

                        elif op == "TASKBAR_PIN_HOTKEY":
                            handletaskbarpinhotkey(s, m)

                        elif op == "TASKBAR_VOLUME_HOTKEY":
                            handlevolumehotkey(s, m)

                        elif op == "STARTMENU_TOGGLE":
                            handlestartmenutoggle(s, m)

                elif kind == "audio":

                    if mask & selectors.EVENT_READ:
                        audioserviceread()

                    if mask & selectors.EVENT_WRITE:
                        audioservicewrite()

                    if TASKBARBUF is not None:

                        updateaudioicon(s)

                        if HOVERAUDIO:

                            taskbarpainttooltips(s)

            mapretry(s)

            searchpump(s)

            graphicspumpall(s)

            retrysendtaskbar(s)

            updateclock(s)

            updatesearchcaret(s)

            masterimagesettingstick(s)

            desktoprefresh(s)

            reapchildren()

            updatehover(s)

            volumeflushdrag(s)

            updatevolumetimeout(s)

            now = time.time()

            if now >= NET_NEXT_TS:
                NET_NEXT_TS = now + NET_INTERVAL

                updatenetworkicon(s)

            if not GOTWELCOME and (time.time() - t0) > 1.0:
                GOTWELCOME = True

                # redundancy path if welcome never arrives
                getfbsize()

                log("no welcome within 1s; creating desktop anyway")

                sendline(s,
                         {"op": "CREATE_WINDOW", "w": DESKTOPW, "h": DESKTOPH, "title": "expanse", "role": "desktop"})

    except Exception as e:

        tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))

        log(f"fatal error {e}\n{tb}")



def startmenupaintdiagnostic(emit=True):

    result = {
        "format": 1,
        "passed": False,
        "checks": {},
        "errors": []
    }
    names = (
        "STARTID", "STARTBUF", "STARTW", "STARTH", "STARTLEFTW",
        "STARTPLACEITEMS", "STARTSOFTITEMS", "POWERMENUOPEN", "STARTMENUPAINTERROR",
        "GRAPHICSCPUOVERRIDE"
    )
    previous = {name: globals().get(name) for name in names}
    path = f"/the one/logs/.expanse-startmenu-{os.getpid()}.buf"
    left = None
    right = None

    try:

        globals()["STARTID"] = 99
        globals()["STARTBUF"] = path
        globals()["STARTW"] = 400
        globals()["STARTH"] = 360
        globals()["STARTLEFTW"] = 180
        globals()["STARTPLACEITEMS"] = []
        globals()["STARTSOFTITEMS"] = []
        globals()["POWERMENUOPEN"] = False
        # This diagnostic deliberately validates the recovery renderer used
        # only when GPU-managed graphics is unavailable.
        globals()["GRAPHICSCPUOVERRIDE"] = True
        os.makedirs(os.path.dirname(path), mode=0o755, exist_ok=True)
        with open(path, "wb") as surface:
            surface.truncate(int(STARTW) * int(STARTH) * 4)
        left, right = socket.socketpair()
        paintstartmenu(left)

        if not os.path.exists(path):
            raise RuntimeError(f"atomic start-menu buffer was not committed: {STARTMENUPAINTERROR}")

        expected = int(STARTW) * int(STARTH) * 4

        if os.path.getsize(path) != expected:
            raise RuntimeError("committed start-menu buffer has the wrong size")

        if os.path.exists(f"{path}.tmp"):
            raise RuntimeError("start-menu temporary buffer remained after commit")

        right.settimeout(1.0)
        data = right.recv(4096).decode("utf-8", errors="replace")
        messages = [json.loads(line) for line in data.splitlines() if line.strip()]
        damage = messages[-1] if messages else {}

        if damage.get("op") != "DAMAGE" or damage.get("rect") != [0, 0, STARTW, STARTH]:
            raise RuntimeError("atomic start-menu commit did not send full-window damage")

        result["checks"]["atomic_buffer"] = True
        result["checks"]["full_damage"] = True
        result["checks"]["buffer_bytes"] = expected
        result["passed"] = True

    except Exception as e:

        result["errors"].append(str(e))

    finally:

        if left is not None:
            left.close()

        if right is not None:
            right.close()

        for candidate in (path, f"{path}.tmp"):

            try:

                if os.path.exists(candidate):
                    os.remove(candidate)

            except Exception:
                pass

        for name, value in previous.items():
            globals()[name] = value

    if emit:
        print(json.dumps(result, separators=(",", ":"), sort_keys=True))
        return bool(result["passed"])

    return result


def graphicsdiagnostic():

    result = {
        "format": 1,
        "passed": False,
        "resolution": [2560, 1440],
        "surfaces": {},
        "checks": {},
        "performance": {},
        "errors": [],
    }

    originalnetwork = globals().get("readnetworkstatus")
    originaltime = globals().get("readatreyantime")
    desktopdiagnosticroot = None

    try:

        globals()["DESKTOPW"] = 2560
        globals()["DESKTOPH"] = 1440
        applyscale()
        initttffont(FONTPATH, BRICKFONTSIZE)

        if (
            abs(float(SCALE) - (4.0 / 3.0)) > 0.001
            or int(TASKBARH) != 64
            or abs(float(scalefromfb(2560, 1600)) - (4.0 / 3.0)) > 0.001
        ):
            raise RuntimeError(
                f"Expanse uniform display scale is inconsistent "
                f"scale={SCALE} taskbar={TASKBARH} aspect={scalefromfb(2560, 1600)}"
            )

        result["checks"]["uniform_display_scale"] = {
            "scale_1440p": round(float(SCALE), 4),
            "taskbar_height": int(TASKBARH),
            "scale_2560x1600": round(float(scalefromfb(2560, 1600)), 4),
        }

        masterpaths = iconmasterpaths()

        if len(masterpaths) != 21:
            raise RuntimeError(f"Expanse defines {len(masterpaths)} PNG icon masters, expected 21")

        dedicatedsoftwareicons = {
            "calculator": "/the one/resources/logos/calculator/calculatorlogo.png",
            "chromium": "/the one/resources/logos/chromium/chromiumlogo.png",
            "player": "/the one/resources/logos/player/playerlogo.png",
            "settings": "/the one/resources/logos/settings/settingslogo.png",
            "snap": "/the one/resources/logos/snap/snaplogo.png",
            "viewer": "/the one/resources/logos/viewer/viewerlogo.png",
            "operations centre": "/the one/resources/logos/operations centre/operationscentrelogo.png",
        }

        for softwarename, expectedpath in dedicatedsoftwareicons.items():

            if SOFTWAREICONS.get(softwarename, {}).get("path") != expectedpath:
                raise RuntimeError(f"{softwarename} does not use its dedicated PNG icon")

        for masterpath in masterpaths:

            info = iconmasterinfo(masterpath)

            if int(info["width"]) != 512 or int(info["height"]) != 512:
                raise RuntimeError(f"icon master is not 512x512: {masterpath}")

        result["checks"]["png_icons"] = len(masterpaths)
        result["checks"]["dedicated_software_icons"] = True
        cachehits = int(ICONCACHEHITS)
        firsticon = prepareicon(T1OSLOGOPATH, 37, 37)
        secondicon = prepareicon(T1OSLOGOPATH, 37, 37)
        largeicon = prepareicon(T1OSLOGOPATH, 53, 53)

        if (
                firsticon[0] is None or
                secondicon != firsticon or
                largeicon[0] is None or
                largeicon[0] == firsticon[0] or
                int(ICONCACHEHITS) <= cachehits
        ):
            raise RuntimeError(
                "PNG icon cache did not preserve hits and resolution-specific surfaces "
                f"first={firsticon} second={secondicon} large={largeicon} "
                f"hits={ICONCACHEHITS}/{cachehits} failures={sorted(ICONCACHEFAILURES)}"
            )

        for prepared in (firsticon, largeicon):

            path, width, height = prepared

            if os.path.getsize(path) != int(width) * int(height) * 4:
                raise RuntimeError("prepared PNG icon surface has the wrong byte size")

            if os.path.commonpath((os.path.realpath("/.ephemeral/expanse"), os.path.realpath(path))) != os.path.realpath("/.ephemeral/expanse"):
                raise RuntimeError("prepared PNG icon surface is outside the Expanse cache")

        result["checks"]["png_icon_cache"] = {
            "hit": True,
            "resolution_variants": 2,
            "surface_bytes": os.path.getsize(firsticon[0]) + os.path.getsize(largeicon[0]),
        }
        # The graphics diagnostic runs outside an authenticated desktop
        # session, so give discovery a valid synthetic identity rather than
        # depending on the production session-authorisation file.
        initstartitems("diagnostic")

        playeritems = [
            item for item in STARTSOFTITEMS
            if item.get("name") == "player"
            and item.get("path") == "/the one/build/player/player.py"
        ]

        if len(playeritems) != 1:
            raise RuntimeError("player is missing from the Expanse software list")

        result["checks"]["player_software"] = True

        calculatoritems = [
            item for item in STARTSOFTITEMS
            if item.get("name") == "calculator"
            and item.get("path") == "/the one/build/calculator/calculator.py"
        ]

        if len(calculatoritems) != 1:
            raise RuntimeError("calculator is missing from the Expanse software list")

        result["checks"]["calculator_software"] = True

        settingsitems = [
            item for item in STARTSOFTITEMS
            if item.get("name") == "settings"
            and item.get("path") == "/the one/build/settings/settings.py"
        ]

        if len(settingsitems) != 1:
            raise RuntimeError("settings is missing from the Expanse software list")

        result["checks"]["settings_software"] = True

        snapitems = [
            item for item in STARTSOFTITEMS
            if item.get("name") == "snap"
            and item.get("path") == "/the one/build/snap/snap.py"
        ]

        if len(snapitems) != 1:
            raise RuntimeError("snap is missing from the Expanse software list")

        result["checks"]["snap_software"] = True

        operationscentreitems = [
            item for item in STARTSOFTITEMS
            if item.get("name") == "operations centre"
            and item.get("path") == "/the one/build/operations/operationscentre.py"
        ]

        if len(operationscentreitems) != 1:
            raise RuntimeError("operations centre is missing from the Expanse software list")

        result["checks"]["operations_centre_software"] = True

        original_launchsoftware = globals().get("launchsoftware")
        original_showdesktop = globals().get("showdesktop")
        original_closesearch = globals().get("closesearch")
        original_savetaskbarsettings = globals().get("savetaskbarsettings")
        taskbarcontextevents = []

        try:
            globals()["launchsoftware"] = lambda software: taskbarcontextevents.append(
                ("launch", str(software.get("name", "")))
            )
            globals()["showdesktop"] = lambda sock: taskbarcontextevents.append(("show", "expanse"))
            globals()["closesearch"] = lambda sock: taskbarcontextevents.append(("close", "search"))
            globals()["savetaskbarsettings"] = lambda: taskbarcontextevents.append(
                ("save", bool(TASKBARSEARCHVISIBLE))
            )
            globals()["TASKBARSEARCHVISIBLE"] = True
            runtaskbarcontextaction(None, "taskbar-search")
            runtaskbarcontextaction(None, "show-expanse")
            runtaskbarcontextaction(None, "settings")
            runtaskbarcontextaction(None, "operations-centre")
        finally:
            globals()["launchsoftware"] = original_launchsoftware
            globals()["showdesktop"] = original_showdesktop
            globals()["closesearch"] = original_closesearch
            globals()["savetaskbarsettings"] = original_savetaskbarsettings

        expectedtaskbarcontextevents = [
            ("close", "search"),
            ("save", False),
            ("show", "expanse"),
            ("launch", "settings"),
            ("launch", "operations centre"),
        ]

        if taskbarcontextevents != expectedtaskbarcontextevents:
            raise RuntimeError(f"taskbar context actions failed {taskbarcontextevents}")

        globals()["TASKBARSEARCHVISIBLE"] = True
        result["checks"]["taskbar_context_actions"] = True

        originaltaskbarsettingsfile = TASKBARSETTINGSFILE
        diagnostictaskbarsettings = "/.ephemeral/expanse/taskbar-context-diagnostic.json"
        globals()["TASKBARSETTINGSFILE"] = diagnostictaskbarsettings
        globals()["TASKBARSEARCHVISIBLE"] = False
        savetaskbarsettings()
        globals()["TASKBARSEARCHVISIBLE"] = True
        loadtaskbarsettings()

        if TASKBARSEARCHVISIBLE:
            raise RuntimeError("taskbar search visibility did not persist its disabled state")

        globals()["TASKBARSEARCHVISIBLE"] = True
        savetaskbarsettings()
        globals()["TASKBARSEARCHVISIBLE"] = False
        loadtaskbarsettings()

        if not TASKBARSEARCHVISIBLE:
            raise RuntimeError("taskbar search visibility did not persist its enabled state")

        try:
            os.remove(diagnostictaskbarsettings)
        except FileNotFoundError:
            pass

        globals()["TASKBARSETTINGSFILE"] = originaltaskbarsettingsfile
        result["checks"]["taskbar_search_persistence"] = True

        mixedcasename = "MyHomeWiFi-AX"

        if networkdisplayname(mixedcasename) != mixedcasename:
            raise RuntimeError("network name capitalization was changed before tooltip rendering")

        result["checks"]["network_name_case"] = True

        vieweritems = [
            item for item in STARTSOFTITEMS
            if item.get("name") == "viewer"
            and item.get("path") == "/the one/build/viewer/viewer.py"
        ]

        if len(vieweritems) != 1:
            raise RuntimeError("viewer is missing from the Expanse software list")

        result["checks"]["viewer_software"] = True

        chromiumitems = [
            item for item in STARTSOFTITEMS
            if item.get("name") == "chromium"
            and item.get("path") == "/the one/build/chromium/chromium.py"
        ]

        if len(chromiumitems) != 1:
            raise RuntimeError("chromium is missing from the Expanse software list")

        result["checks"]["chromium_software"] = True

        globals()["readnetworkstatus"] = lambda: ("online", "eth0", "10.0.2.15/24", "10.0.2.2", "00:11:22:33:44:55")
        globals()["readatreyantime"] = lambda: ("10:27 pm", "17:07:6AE")

        desktopdiagnosticroot = f"/.ephemeral/expanse/desktop-diagnostic-{os.getpid()}"
        desktopdiagnosticsettings = os.path.join(desktopdiagnosticroot, ".settings.json")
        alphatier = os.path.join(desktopdiagnosticroot, "alpha tier")
        betatier = os.path.join(desktopdiagnosticroot, "beta tier")
        childfile = os.path.join(alphatier, "child.txt")
        testfile = os.path.join(desktopdiagnosticroot, "test.txt")
        os.makedirs(alphatier, exist_ok=True)
        os.makedirs(betatier, exist_ok=True)
        with open(childfile, "w") as stream:
            stream.write("child")
        with open(testfile, "w") as stream:
            stream.write("desktop")

        globals()["DESKTOPROOT"] = desktopdiagnosticroot
        globals()["DESKTOPSETTINGSFILE"] = desktopdiagnosticsettings
        globals()["DESKTOPSHOW"] = True
        globals()["DESKTOPITEMSIZE"] = "medium"
        globals()["DESKTOPORDER"] = []
        globals()["DESKTOPPOSITIONS"] = {}
        globals()["DESKTOPEXPANDED"] = {alphatier}
        globals()["DESKTOPSCANSIGNATURE"] = None
        globals()["DESKTOPSELECTED"] = testfile
        desktoprefresh(force=True)

        expecteddesktoprows = [
            ("alpha tier", 0, True),
            ("child.txt", 1, False),
            ("beta tier", 0, True),
            ("test.txt", 0, False),
        ]
        actualdesktoprows = [
            (
                str(item.get("name", "")),
                int(item.get("depth", -1)),
                bool(item.get("isdir")),
            )
            for item in DESKTOPITEMS
        ]
        if actualdesktoprows != expecteddesktoprows:
            raise RuntimeError(f"desktop tier expansion is incorrect {actualdesktoprows}")

        if desktopsecurepath(os.path.join(desktopdiagnosticroot, "..", "outside")) is not None:
            raise RuntimeError("desktop path confinement accepted a path outside the expanse tier")

        metrics = desktopmetrics()
        layouts = desktoplayout()
        if len(layouts) != 4 or any(
            (int(item["rect"][0]) - metrics["margin"]) % metrics["width"] != 0
            or (int(item["rect"][1]) - metrics["margin"]) % metrics["height"] != 0
            for item in layouts
        ):
            raise RuntimeError("desktop items did not snap to the active grid")

        rootgridsbefore = {
            str(item.get("name", "")): list(item.get("grid", []))
            for item in layouts
            if int(item.get("depth", -1)) == 0
        }
        movedcell = [1, 2]
        movedx = metrics["margin"] + movedcell[0] * metrics["width"]
        movedy = metrics["margin"] + movedcell[1] * metrics["height"]
        if not desktopmoveitem(None, betatier, movedx, movedy, offset=(0, 0)):
            raise RuntimeError("desktop tier could not be moved to an independent grid cell")
        rootgridsafter = {
            str(item.get("name", "")): list(item.get("grid", []))
            for item in DESKTOPITEMRECTS
            if int(item.get("depth", -1)) == 0
        }
        if (
            rootgridsafter.get("beta tier") != movedcell
            or rootgridsafter.get("alpha tier") != rootgridsbefore.get("alpha tier")
            or rootgridsafter.get("test.txt") != rootgridsbefore.get("test.txt")
        ):
            raise RuntimeError(
                f"desktop item movement changed unrelated grid positions {rootgridsafter}"
            )

        originaldesktopsettingsfile = DESKTOPSETTINGSFILE
        globals()["DESKTOPSHOW"] = False
        globals()["DESKTOPITEMSIZE"] = "small"
        savedesktopsettings()
        globals()["DESKTOPSHOW"] = True
        globals()["DESKTOPITEMSIZE"] = "large"
        globals()["DESKTOPEXPANDED"] = set()
        loaddesktopsettings()
        if (
            DESKTOPSHOW
            or DESKTOPITEMSIZE != "small"
            or alphatier not in DESKTOPEXPANDED
            or DESKTOPPOSITIONS.get("beta tier") != movedcell
        ):
            raise RuntimeError(
                "desktop visibility, size, expansion, or grid positions did not persist"
            )

        globals()["DESKTOPSHOW"] = True
        globals()["DESKTOPITEMSIZE"] = "medium"
        globals()["DESKTOPEXPANDED"] = {alphatier}
        globals()["DESKTOPSETTINGSFILE"] = originaldesktopsettingsfile
        desktoprefresh(force=True)
        result["checks"]["desktop_filesystem_and_grid"] = {
            "root": "/master/<username>/expanse",
            "rows": [item[0] for item in expecteddesktoprows],
            "expanded_depth": 1,
            "grid": "medium",
            "independent_position": movedcell,
        }
        result["checks"]["desktop_settings_persistence"] = True
        result["checks"]["desktop_path_confinement"] = True

        globals()["TASKMENUDESKTOP"] = {
            "kind": "empty",
            "path": desktopdiagnosticroot,
        }
        globals()["TASKMENUDESKTOPVIEW"] = False
        desktopmainmenu = taskmenuitems()
        desktopmainactions = [str(item.get("action", "")) for item in desktopmainmenu]
        requiredmainactions = [
            "desktop-view", "newfile", "newtier", "desktop-settings",
        ]
        if any(action not in desktopmainactions for action in requiredmainactions):
            raise RuntimeError(f"desktop context menu is incomplete {desktopmainactions}")
        if "sidebarpin" in desktopmainactions:
            raise RuntimeError("desktop context menu still exposes sidebar pinning")
        if desktopmainactions[0] != "desktop-view" or desktopmainactions[-1] != "desktop-settings":
            raise RuntimeError("desktop view and settings actions are out of order")

        globals()["TASKMENUDESKTOPVIEW"] = True
        desktopviewmenu = taskmenuitems()
        expectedviewactions = [
            "desktop-show",
            "desktop-size-large",
            "desktop-size-medium",
            "desktop-size-small",
        ]
        if [str(item.get("action", "")) for item in desktopviewmenu] != expectedviewactions:
            raise RuntimeError("desktop view choices are missing or out of order")
        if not desktopviewmenu[0].get("checked") or not desktopviewmenu[2].get("checked"):
            raise RuntimeError("desktop view choices did not mark show expanse and medium")

        globals()["TASKMENUDESKTOP"] = {"kind": "row", "path": testfile}
        globals()["TASKMENUDESKTOPVIEW"] = False
        desktopfileactions = [
            str(item.get("action", "")) for item in taskmenuitems()
        ]
        if (
            "open" not in desktopfileactions
            or "delete" not in desktopfileactions
            or "properties" not in desktopfileactions
            or "filelocation" in desktopfileactions
        ):
            raise RuntimeError(f"desktop file actions differ from Array {desktopfileactions}")

        desktopactionevents = []
        originallaunchsoftware = globals().get("launchsoftware")
        originalcreatedesktopitem = globals().get("createdesktopitem")
        originalrenamedesktopitem = globals().get("renamedesktopitem")

        def diagnosticdesktopcreate(kind, name):
            path = os.path.join(desktopdiagnosticroot, str(name))
            if str(kind) == "tier":
                os.mkdir(path)
            else:
                with open(path, "x"):
                    pass
            return {"status": "ok", "kind": str(kind), "path": path}

        def diagnosticdesktoprename(relative, name):
            source = os.path.join(desktopdiagnosticroot, str(relative))
            destination = os.path.join(os.path.dirname(source), str(name))
            os.rename(source, destination)
            return {"status": "ok", "path": destination}

        try:
            globals()["launchsoftware"] = lambda software: desktopactionevents.append({
                "name": str(software.get("name", "")),
                "args": list(software.get("args", [])),
            })
            globals()["createdesktopitem"] = diagnosticdesktopcreate
            globals()["renamedesktopitem"] = diagnosticdesktoprename
            rundesktopcontextaction(
                None,
                {"kind": "empty", "path": desktopdiagnosticroot},
                "newfile",
            )
            if not DESKTOPCREATEACTIVE or DESKTOPCREATEKIND != "file":
                raise RuntimeError("desktop file naming field did not open")
            globals()["DESKTOPCREATETEXT"] = "new note.txt"
            globals()["DESKTOPCREATECARETPOS"] = len(DESKTOPCREATETEXT)
            if not desktopcommitcreate(None):
                raise RuntimeError("desktop file naming field did not create the file")
            creatednote = os.path.join(desktopdiagnosticroot, "new note.txt")
            if not os.path.isfile(creatednote) or DESKTOPSELECTED != creatednote:
                raise RuntimeError("desktop file creation did not refresh its selection")

            rundesktopcontextaction(
                None,
                {"kind": "empty", "path": desktopdiagnosticroot},
                "newtier",
            )
            globals()["DESKTOPCREATETEXT"] = "new tier"
            globals()["DESKTOPCREATECARETPOS"] = len(DESKTOPCREATETEXT)
            if not desktopcommitcreate(None):
                raise RuntimeError("desktop tier naming field did not create the tier")
            if not os.path.isdir(os.path.join(desktopdiagnosticroot, "new tier")):
                raise RuntimeError("desktop tier was not created")

            renamesource = os.path.join(
                desktopdiagnosticroot, "rename source.txt")
            with open(renamesource, "x"):
                pass
            desktoprefresh(force=True)
            rundesktopcontextaction(
                None, {"kind": "row", "path": renamesource}, "rename")
            if (
                not DESKTOPCREATEACTIVE or
                DESKTOPCREATETARGET != renamesource or
                desktopeditselection() != (0, len("rename source"))
            ):
                raise RuntimeError("desktop inline rename field did not open")
            if not desktopinserttext("renamed") or DESKTOPCREATETEXT != "renamed.txt":
                raise RuntimeError("desktop inline rename did not replace the file stem")
            if not desktopcommitcreate(None):
                raise RuntimeError("desktop inline rename did not commit")
            renamedpath = os.path.join(desktopdiagnosticroot, "renamed.txt")
            if (
                os.path.exists(renamesource) or
                not os.path.isfile(renamedpath) or
                DESKTOPSELECTED != renamedpath
            ):
                raise RuntimeError("desktop inline rename did not refresh the row")

            rundesktopcontextaction(None, {"kind": "row", "path": testfile}, "open")
            rundesktopcontextaction(None, {"kind": "row", "path": testfile}, "properties")
            rundesktopcontextaction(
                None,
                {"kind": "empty", "path": desktopdiagnosticroot},
                "desktop-settings",
            )
        finally:
            globals()["launchsoftware"] = originallaunchsoftware
            globals()["createdesktopitem"] = originalcreatedesktopitem
            globals()["renamedesktopitem"] = originalrenamedesktopitem
            desktopcancelcreate(None)

        if (
            len(desktopactionevents) != 3
            or desktopactionevents[0].get("args") != ["--open-item", testfile]
            or desktopactionevents[1].get("args") != ["--context-action", "properties", testfile]
            or desktopactionevents[2].get("name") != "settings"
        ):
            raise RuntimeError(f"desktop Array and Settings dispatch failed {desktopactionevents}")

        globals()["TASKMENUDESKTOP"] = None
        globals()["TASKMENUDESKTOPVIEW"] = False
        result["checks"]["desktop_context_menu"] = {
            "view": [str(item.get("label", "")) for item in desktopviewmenu],
            "array_file_actions": True,
            "settings": True,
        }
        result["checks"]["desktop_array_dispatch"] = True
        result["checks"]["desktop_inline_creation"] = {
            "file": "new note.txt",
            "tier": "new tier",
            "array_opened": False,
        }
        result["checks"]["desktop_inline_rename"] = {
            "source": "rename source.txt",
            "destination": "renamed.txt",
            "array_opened": False,
        }

        capabilities = {
            "version": 2,
            "accelerated": True,
            "managed_resources": True,
            "atomic_scene": True,
            "retained_scene": True,
            "stable_node_ids": True,
            "damage_regions": True,
            "commands": ["rectangle", "image", "text"],
            "command_limit": 1024,
            "total_command_limit": 8192,
            "text_limit": 1024,
            "image_pixel_limit": 16777216,
            "damage_limit": 64,
        }

        GRAPHICSCAPS.clear()
        GRAPHICSCAPS.update(capabilities)
        GRAPHICSSTATES.clear()
        GRAPHICSSCENES.clear()
        GRAPHICSSURFACES.clear()

        globals()["DESKTOPID"] = 91
        globals()["DESKTOPBUF"] = "/the one/logs/.expanse-desktop-diagnostic.buf"
        globals()["TASKBARID"] = 92
        globals()["TASKBARBUF"] = "/the one/logs/.expanse-taskbar-diagnostic.buf"
        globals()["STARTID"] = 93
        globals()["STARTBUF"] = "/the one/logs/.expanse-start-diagnostic.buf"
        globals()["TOOLTIPID"] = 94
        globals()["TOOLTIPBUF"] = "/the one/logs/.expanse-tooltip-diagnostic.buf"
        globals()["LISTID"] = 95
        globals()["LISTBUF"] = "/the one/logs/.expanse-list-diagnostic.buf"
        globals()["TASKMENUID"] = 96
        globals()["TASKMENUBUF"] = "/the one/logs/.expanse-taskmenu-diagnostic.buf"
        globals()["VOLUMEID"] = 97
        globals()["VOLUMEBUF"] = "/the one/logs/.expanse-volume-diagnostic.buf"

        startwidth = int(STARTW)
        startheight = max(int(STARTH), int(STARTITEMH * 8))
        globals()["STARTH"] = startheight
        listwidth = s(360, 240)
        listheight = int(TASKMENUITEMH * 3)
        menuwidth = s(260, 180)
        menuheight = int(TASKMENUITEMH * 3)
        tooltipwidth = s(250, 180)
        tooltipheight = s(38, 28)

        definitions = {
            "desktop": (DESKTOPID, DESKTOPBUF, DESKTOPW, DESKTOPH),
            "taskbar": (TASKBARID, TASKBARBUF, DESKTOPW, TASKBARH),
            "startmenu": (STARTID, STARTBUF, startwidth, startheight),
            "tooltip": (TOOLTIPID, TOOLTIPBUF, tooltipwidth, tooltipheight),
            "instancelist": (LISTID, LISTBUF, listwidth, listheight),
            "taskmenu": (TASKMENUID, TASKMENUBUF, menuwidth, menuheight),
            "volumebar": (VOLUMEID, VOLUMEBUF, VOLUMEW, VOLUMEH),
        }

        for role, definition in definitions.items():

            winid, bufferpath, width, height = definition

            if not graphicsregister(role, winid, bufferpath, width, height):
                raise RuntimeError(f"managed capability negotiation failed for {role}")

        result["checks"]["capability_negotiation"] = True

        if any(graphicsstatefor(role).get("need_submit") for role in ("startmenu", "tooltip", "instancelist", "taskmenu", "volumebar")):
            raise RuntimeError("an inactive transient surface attempted to submit before its first paint")

        result["checks"]["inactive_transients_deferred"] = True

        globals()["WINDOWORDER"] = [201, 202, 203, 204]
        globals()["WINDOWITEMS"] = {
            201: {"name": "array", "title": "array", "current": "/master", "path": "/the one/build/array/array.py", "mapped": True},
            202: {"name": "brick", "title": "brick one", "current": "1/master", "path": "/the one/build/brick/brick.py", "mapped": True},
            203: {"name": "brick", "title": "brick two", "current": "1/software", "path": "/the one/build/brick/brick.py", "mapped": True},
            204: {"name": "write", "title": "write", "current": "/master/diagnostic.txt", "path": "/the one/build/write/write.py", "mapped": True},
        }
        globals()["ACTIVEWID"] = 202
        globals()["TASKBARPINS"] = [{"name": "array", "path": "/the one/build/array/array.py"}]
        globals()["TASKBARSEEN"] = []
        globals()["TASKBARORDER"] = []
        globals()["DRAGTASKGROUP"] = "write"
        globals()["DRAGTASKACTIVE"] = True
        globals()["DRAGTASKMOVED"] = True
        globals()["DRAGTASKX"] = s(700, 500)
        globals()["DRAGTASKY"] = DESKTOPH - (TASKBARH // 2)
        globals()["DRAGTASKOFFSETX"] = WINDOWBOXSIZE // 2
        globals()["AUDIOGOTDEV"] = True
        globals()["AUDIOGOTVOL"] = True
        globals()["CURRENTAUDIOAVAIL"] = True
        globals()["CURRENTAUDIOVOL"] = 58
        globals()["CURRENTAUDIOMUTE"] = False
        globals()["LASTAUDIOAVAIL"] = None
        globals()["LASTAUDIOVOL"] = None
        globals()["LASTAUDIOMUTE"] = None
        globals()["LASTNETSTATE"] = None
        globals()["LASTNETADDR"] = None
        globals()["LASTNETGW"] = None
        globals()["HOVERLOGO"] = False
        globals()["POWERMENUOPEN"] = True

        buildtaskbargroups()
        globals()["LISTGROUP"] = "brick"
        globals()["LISTRECT"] = [100, 100, listwidth, listheight]
        globals()["LISTANCHOR"] = [500, DESKTOPH - TASKBARH, WINDOWBOXSIZE, TASKBARH]
        globals()["LISTHOVERWID"] = 203
        globals()["LISTCLOSERECTS"] = []

        closebox = s(18, 9)
        rightpad = s(8, 6)

        for index, wid in enumerate((202, 203)):

            rowy = index * TASKMENUITEMH
            closex = listwidth - rightpad - closebox
            closey = rowy + (TASKMENUITEMH - closebox) // 2
            LISTCLOSERECTS.append([closex, closey, closebox, closebox, wid])

        globals()["TASKMENUGROUP"] = "array"
        globals()["TASKMENURECT"] = [300, 300, menuwidth, menuheight]
        globals()["TASKMENUHOVER"] = "pin"
        globals()["VOLUMERECT"] = [2200, 1000, VOLUMEW, VOLUMEH]
        globals()["GRAPHICSTOOLTIPDATA"] = {
            "x": 10,
            "y": 8,
            "text": "online eth0 10.0.2.15/24",
            "color": HOVERCOLOR,
            "size": HOVERFONTSIZE,
        }
        globals()["HOVERRECT"] = [100, 100, tooltipwidth, tooltipheight]

        desktopstartcreate(None, "file")
        globals()["DESKTOPCREATETEXT"] = "draft.txt"
        globals()["DESKTOPCREATECARETPOS"] = len(DESKTOPCREATETEXT)
        globals()["DESKTOPSELECTED"] = testfile

        scenes = {}
        maximumcommands = 0
        totalcommands = 0

        for role in definitions:

            scene = graphicsbuildscene(role)
            scenes[role] = scene
            width, height = graphicsdimensions(role)

            if not scene or scene[0].get("kind") != "rectangle" or scene[0].get("rect") != [0, 0, width, height]:
                raise RuntimeError(f"{role} scene does not begin with a complete opaque background")

            state = graphicsstatefor(role)
            limit = int(state.get("command_limit", 0))

            if len(scene) >= int(limit * 0.75):
                raise RuntimeError(f"{role} scene uses too much of the command budget {len(scene)}/{limit}")

            maximumcommands = max(maximumcommands, len(scene))
            totalcommands += len(scene)
            result["surfaces"][role] = {
                "commands": len(scene),
                "kinds": sorted(set(str(command.get("kind", "")) for command in scene)),
                "size": [width, height],
            }

        if totalcommands >= int(capabilities["total_command_limit"] * 0.75):
            raise RuntimeError(f"Expanse scenes use too much of the total command budget {totalcommands}")

        result["checks"]["opaque_backgrounds"] = len(scenes)
        result["checks"]["command_budget"] = {
            "maximum_surface": maximumcommands,
            "aggregate": totalcommands,
            "surface_limit": capabilities["command_limit"],
            "total_limit": capabilities["total_command_limit"],
        }

        if set(command.get("kind") for command in scenes["desktop"]) != {"rectangle", "text"}:
            raise RuntimeError("desktop scene contains unexpected commands")

        desktoptexts = {
            str(command.get("text", "")): command
            for command in scenes["desktop"]
            if command.get("kind") == "text"
        }
        if any(name not in desktoptexts for name in ("alpha tier", "child.txt", "beta tier", "test.txt", ">")):
            raise RuntimeError(f"desktop scene did not render tiers, carets, and files {sorted(desktoptexts)}")
        if int(desktoptexts["child.txt"].get("x", 0)) <= int(desktoptexts["alpha tier"].get("x", 0)):
            raise RuntimeError("expanded desktop child was not indented under its tier")
        if "draft.txt" not in desktoptexts:
            raise RuntimeError("desktop scene did not render the inline naming field")
        result["checks"]["desktop_inline_creation_gpu_scene"] = True
        desktopcancelcreate(None)

        if not desktopstartrename(None, renamedpath):
            raise RuntimeError("desktop rename field could not enter its managed scene")
        globals()["DESKTOPSELECTED"] = testfile
        renamescene = graphicsbuildscene("desktop")
        if not any(
            command.get("kind") == "text"
            and command.get("text") == "renamed"
            and command.get("color") == graphicscolour(0x000000)
            for command in renamescene
        ):
            raise RuntimeError("desktop managed scene did not render rename selection")
        result["checks"]["desktop_inline_rename_gpu_scene"] = True
        desktopcancelcreate(None)

        selecteddesktop = next(
            item for item in DESKTOPITEMRECTS if item.get("path") == testfile
        )
        if not any(
            command.get("kind") == "rectangle"
            and command.get("rect") == selecteddesktop.get("rect")
            and command.get("color") == graphicscolour((36, 36, 36))
            for command in scenes["desktop"]
        ):
            raise RuntimeError("desktop selected row did not use Array's selection treatment")
        result["checks"]["desktop_managed_scene"] = {
            "tiers": 2,
            "files": 2,
            "selected": "test.txt",
            "gpu_managed": True,
        }

        if not any(command.get("kind") == "image" for command in scenes["taskbar"]):
            raise RuntimeError("taskbar scene did not preserve prepared PNG icon surfaces")

        if not any(command.get("kind") == "text" for command in scenes["taskbar"]):
            raise RuntimeError("taskbar scene did not preserve the clock")

        if not any(command.get("kind") == "image" and "powerbutt" in str(command.get("path", "")) for command in scenes["startmenu"]):
            raise RuntimeError("start menu scene did not preserve the power image")

        if not any(command.get("kind") == "text" and command.get("text") == "software" for command in scenes["startmenu"]):
            raise RuntimeError("start menu scene did not preserve its headings")

        softwareheading = next(
            command for command in scenes["startmenu"]
            if command.get("kind") == "text"
            and command.get("text") == "software"
            and int(command.get("x", -1)) == int(STARTLEFTW + STARTPAD)
        )
        softwarelabels = {
            str(item.get("label", "")) for item in STARTSOFTITEMS
        }
        softwarecommands = [
            command for command in scenes["startmenu"]
            if command.get("kind") == "text"
            and command.get("text") in softwarelabels
            and int(command.get("x", -1)) == int(softwareheading.get("x", -2))
        ]
        if any(
            not any(
                command.get("text") == str(item.get("label", ""))
                for command in softwarecommands
            )
            for item in STARTSOFTITEMS
        ):
            raise RuntimeError(
                "start menu software names do not align with their heading "
                f"heading={softwareheading.get('x')}"
            )
        result["checks"]["startmenu_software_alignment"] = int(
            softwareheading["x"]
        )

        if not any(command.get("kind") == "text" for command in scenes["tooltip"]):
            raise RuntimeError("tooltip scene did not preserve its text")

        if not any(command.get("kind") == "text" and "1/software" in str(command.get("text", "")) for command in scenes["instancelist"]):
            raise RuntimeError("instance-list scene did not preserve rows")

        if not any(command.get("kind") == "text" and "pin" in str(command.get("text", "")) for command in scenes["taskmenu"]):
            raise RuntimeError("task-menu scene did not preserve actions")

        globals()["TASKMENUGROUP"] = None
        globals()["TASKMENUCONTEXT"] = None
        globals()["TASKMENUTASKBAR"] = True
        globals()["TASKMENUHOVER"] = "settings"
        taskbarcontextitems = taskmenuitems()
        expectedtaskbarcontext = [
            ("search", "taskbar-search"),
            ("show expanse", "show-expanse"),
            ("settings", "settings"),
            ("operations centre", "operations-centre"),
        ]

        if [
            (str(item.get("label", "")), str(item.get("action", "")))
            for item in taskbarcontextitems
        ] != expectedtaskbarcontext:
            raise RuntimeError("taskbar context menu options are missing or out of order")

        if not taskbarcontextitems[0].get("checked"):
            raise RuntimeError("taskbar context menu search checkbox is not enabled by default")

        contextheight = taskmenuitemheight() * len(taskbarcontextitems)
        contextpad = taskmenucompactpad()
        contextfont = taskmenucompactfontsize()
        contextcheckbox = max(s(12, 6), min(taskmenuitemheight() - s(6, 3), s(16, 8)))
        contextgap = s(8, 4)
        contextwidth = max(
            measurettffile(str(item.get("label", "")), contextfont)
            + (contextcheckbox + contextgap if "checked" in item else 0)
            for item in taskbarcontextitems
        ) + (contextpad * 2)
        contextwidth = max(
            contextpad * 2 + 1,
            min(contextwidth, int(MENUMAXW)),
        )
        globals()["TASKMENURECT"] = [300, 300, contextwidth, contextheight]
        graphicsupdategeometry("taskmenu", contextwidth, contextheight, TASKMENUBUF)
        taskbarcontextscene = graphicsbuildscene("taskmenu")
        contexttexts = [
            command for command in taskbarcontextscene
            if command.get("kind") == "text"
            and command.get("text") in {item[0] for item in expectedtaskbarcontext}
        ]

        if len(contexttexts) != 4 or len({int(command.get("x", -1)) for command in contexttexts}) != 1:
            raise RuntimeError("taskbar context menu labels are not aligned")

        checkboxrect = [
            contextpad + measurettffile("search", contextfont) + contextgap,
            (taskmenuitemheight() - contextcheckbox) // 2,
            contextcheckbox,
            contextcheckbox,
        ]

        if not any(
            command.get("kind") == "rectangle"
            and command.get("rect") == checkboxrect
            and command.get("color") == graphicscolour((239, 239, 239))
            for command in taskbarcontextscene
        ):
            raise RuntimeError("taskbar context menu did not render the enabled search checkbox")

        settingsrow = taskmenuitemheight() * 2

        if not any(
            command.get("kind") == "rectangle"
            and command.get("color") == graphicscolour((36, 36, 36))
            and int(command.get("rect", [0, -1])[1]) == settingsrow
            for command in taskbarcontextscene
        ):
            raise RuntimeError("taskbar context menu did not render the Array hover treatment")

        globals()["TASKMENUTASKBAR"] = False
        globals()["TASKMENUGROUP"] = "array"
        globals()["TASKMENUHOVER"] = "pin"
        globals()["TASKMENURECT"] = [300, 300, menuwidth, menuheight]
        graphicsupdategeometry("taskmenu", menuwidth, menuheight, TASKMENUBUF)
        result["checks"]["taskbar_context_menu"] = {
            "options": [item[0] for item in expectedtaskbarcontext],
            "search_checked": True,
            "array_hover": True,
            "aligned": True,
        }

        if not any(command.get("kind") == "text" and command.get("text") == "58" for command in scenes["volumebar"]):
            raise RuntimeError("volume scene did not preserve its value")

        result["checks"]["desktop"] = True
        result["checks"]["taskbar"] = True
        result["checks"]["startmenu"] = True
        result["checks"]["tooltip"] = True
        result["checks"]["instancelist"] = True
        result["checks"]["taskmenu"] = True
        result["checks"]["volumebar"] = True

        imagecommands = [
            command
            for scene in scenes.values()
            for command in scene
            if command.get("kind") == "image"
        ]

        if not imagecommands:
            raise RuntimeError("diagnostic did not exercise managed images")

        for command in imagecommands:

            if command.get("format") != "BGRA32" or not os.path.isfile(command.get("path", "")):
                raise RuntimeError("managed image command is not a valid BGRA32 resource")

            imagepath = os.path.realpath(command["path"])

            if (
                    not imagepath.endswith(".bgra") or
                    os.path.commonpath((os.path.realpath("/.ephemeral/expanse"), imagepath)) != os.path.realpath("/.ephemeral/expanse")
            ):
                raise RuntimeError("managed image command did not use the prepared PNG icon cache")

            expectedbytes = int(command.get("source_width", 0)) * int(command.get("source_height", 0)) * 4

            if expectedbytes < 4 or os.path.getsize(command["path"]) < expectedbytes:
                raise RuntimeError("managed image dimensions exceed the raw resource")

        textcommands = [
            command
            for scene in scenes.values()
            for command in scene
            if command.get("kind") == "text"
        ]

        if not textcommands or any(command.get("font") != FONTPATH for command in textcommands):
            raise RuntimeError("managed text did not consistently use Atkinson Hyperlegible Next")

        probe = []
        graphicstext(probe, "taskmenu", -20, 10, "variable width " * 20, 0xEFEFEF, TASKMENUFONTSIZE, FONTPATH, [20, 0, 180, 60])

        if not probe or any(command.get("x", 0) < 20 or command.get("clip") != [20, 0, 180, 60] for command in probe):
            raise RuntimeError("managed variable-width text was not safely clipped")

        result["checks"]["bgra_images"] = len(imagecommands)
        result["checks"]["atkinson_baseline"] = True
        result["checks"]["variable_width_clipping"] = True

        requests = {}

        for role, scene in scenes.items():

            state = graphicsstatefor(role)
            width, height = graphicsdimensions(role)
            managedmarkdamage(state, [10, 10, 60, 40], bounds=(width, height))
            managedmarkdamage(state, [40, 20, 70, 50], bounds=(width, height))
            queued = []
            managedsubmit(state, lambda request: queued.append(request) or True, graphicswinid(role), scene)

            if len(queued) != 1 or queued[0].get("op") != "GRAPHICS_SCENE" or len(queued[0].get("damage", [])) != 1:
                raise RuntimeError(f"{role} did not submit one damage-aware atomic scene")

            managedresponse(state, {
                "op": "GRAPHICS_COMMITTED",
                "winid": graphicswinid(role),
                "count": len(scene),
                "batch": True,
                "accelerated": True,
                "managed_only": True,
            })

            if not state.get("active") or state.get("pending"):
                raise RuntimeError(f"{role} acknowledgement did not activate managed rendering")

            requests[role] = len(queued)

        result["checks"]["atomic_scenes"] = requests
        result["checks"]["damage_coalescing"] = True
        result["checks"]["first_frame_complete"] = True

        taskbarstate = graphicsstatefor("taskbar")
        taskbarstate["need_submit"] = True
        nooprequests = []
        managedsubmit(
            taskbarstate,
            lambda request: nooprequests.append(request) or True,
            graphicswinid("taskbar"),
            list(taskbarstate.get("scene", [])),
        )

        if nooprequests or taskbarstate.get("pending") or taskbarstate.get("need_submit"):
            raise RuntimeError("unchanged retained taskbar scene was not suppressed")

        result["checks"]["idle_taskbar_suppressed"] = True
        tooltipstate = graphicsstatefor("tooltip")
        managedresponse(tooltipstate, {
            "op": "ERROR",
            "winid": graphicswinid("tooltip"),
            "code": "graphics_scene_failed",
            "detail": "diagnostic",
        })

        if (
            not tooltipstate.get("available")
            or not tooltipstate.get("active")
            or not tooltipstate.get("managed_only")
            or not tooltipstate.get("need_submit")
            or not taskbarstate.get("active")
        ):
            raise RuntimeError("managed failure escaped strict GPU rendering")

        cpustate = managedstate(cpu=True)

        if managedconfigure(cpustate, capabilities, required=("rectangle", "text"), cpu=True):
            raise RuntimeError("Expanse CPU override unexpectedly enabled managed rendering")

        missingstate = managedstate()

        if managedconfigure(missingstate, {}, required=("rectangle", "text")):
            raise RuntimeError("Expanse missing capabilities unexpectedly enabled managed rendering")

        timeoutstate = managedstate()
        managedconfigure(timeoutstate, capabilities, required=("rectangle", "text"))
        timeoutstate["need_submit"] = True
        managedsubmit(timeoutstate, lambda request: True, 500, [scenes["desktop"][0]])
        timeoutstate["pending_at"] = time.monotonic() - 3.0

        if (
            not managedtick(timeoutstate, timeout=2.0)
            or not timeoutstate.get("active")
            or not timeoutstate.get("managed_only")
            or not timeoutstate.get("need_submit")
        ):
            raise RuntimeError("Expanse managed timeout escaped strict GPU rendering")

        result["checks"]["cpu_fallback"] = True
        result["checks"]["missing_capability_fallback"] = True
        result["checks"]["error_gpu_retention"] = True
        result["checks"]["timeout_gpu_retention"] = True
        result["checks"]["surface_failure_isolation"] = True

        samples = {role: [] for role in definitions}
        maximums = {role: 0 for role in definitions}

        for _ in range(25):

            for role in definitions:

                started = time.monotonic_ns()
                measured = graphicsbuildscene(role)
                elapsed = (time.monotonic_ns() - started) / 1000000.0
                samples[role].append(elapsed)
                maximums[role] = max(maximums[role], len(measured))

        rolesperformance = {}

        for role in definitions:

            values = samples[role]
            rolesperformance[role] = {
                "average_scene_build_ms": round(sum(values) / max(1, len(values)), 3),
                "maximum_scene_build_ms": round(max(values) if values else 0.0, 3),
                "maximum_commands": int(maximums[role]),
            }

        result["performance"] = {
            "roles": rolesperformance,
            "maximum_surface_commands": max(maximums.values()),
            "aggregate_commands": totalcommands,
        }

        # Reproduce the final mode and preference from the captured failing
        # boot.  Taskbar geometry must be current before its managed scene is
        # built or every right-anchored command is clipped to the old width.
        globals()["DESKTOPW"] = 3839
        globals()["DESKTOPH"] = 1974
        applyscale(0.8)
        taskbary = taskbarresizegeometry()
        resizedtaskbar = graphicsbuildscene("taskbar")
        taskbarwidth, taskbarheight = graphicsdimensions("taskbar")
        rightmost = max(
            (
                int(command.get("x", command.get("rect", [0])[0]))
                for command in resizedtaskbar
                if command.get("kind") in ("rectangle", "text")
            ),
            default=0,
        )

        if (
            (taskbarwidth, taskbarheight) != (DESKTOPW, TASKBARH)
            or not resizedtaskbar
            or resizedtaskbar[0].get("rect") != [0, 0, DESKTOPW, TASKBARH]
            or taskbary + TASKBARH != DESKTOPH
            or rightmost < DESKTOPW - max(200, TASKBARH * 4)
        ):
            raise RuntimeError(
                "3839x1974 taskbar resize did not retain its complete right edge "
                f"surface={taskbarwidth}x{taskbarheight} y={taskbary} "
                f"rightmost={rightmost}"
            )

        result["checks"]["taskbar_rapid_resize_final_geometry"] = {
            "display": [DESKTOPW, DESKTOPH],
            "surface": [taskbarwidth, taskbarheight],
            "y": taskbary,
            "rightmost_command": rightmost,
            "ui_preference": 0.8,
            "effective_scale": round(float(SCALE), 4),
        }

        GRAPHICSSTATES.clear()
        GRAPHICSSCENES.clear()
        GRAPHICSSURFACES.clear()
        atomic = startmenupaintdiagnostic(emit=False)

        if not atomic.get("passed"):
            raise RuntimeError("atomic CPU start-menu fallback failed: " + "; ".join(atomic.get("errors", [])))

        result["checks"]["atomic_cpu_startmenu"] = atomic.get("checks", {})
        result["passed"] = True

    except Exception as e:

        result["errors"].append(str(e))

    finally:

        if originalnetwork is not None:
            globals()["readnetworkstatus"] = originalnetwork

        if originaltime is not None:
            globals()["readatreyantime"] = originaltime

        if desktopdiagnosticroot:
            try:
                if os.path.isdir(desktopdiagnosticroot):
                    shutil.rmtree(desktopdiagnosticroot)
            except Exception:
                pass

    print(json.dumps(result, separators=(",", ":"), sort_keys=True))
    return bool(result["passed"])


# execute main
if __name__ == "__main__":

    if len(sys.argv) > 1 and str(sys.argv[1]).strip().lower() == "graphics-diagnostic":
        raise SystemExit(0 if graphicsdiagnostic() else 1)

    if len(sys.argv) > 1 and str(sys.argv[1]).strip().lower() == "startmenu-diagnostic":
        raise SystemExit(0 if startmenupaintdiagnostic() else 1)

    signal.signal(signal.SIGINT, handlesignal)

    signal.signal(signal.SIGTERM, handlesignal)

    main()
