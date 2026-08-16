#!"/the one/software/python/bin/python" -B

"""
windowserver.py

window server is the compositor for The One OS.
"""



## imports
import os
import re
import sys
import json
import time
import math
import struct
import signal
import random
import socket
import select
import selectors
import subprocess
import array
import stat
import queue
import threading
import faulthandler

sys.path.insert(0, '/the one/build')

from reign.reign import (
    currenttime,
    formatatreyandate,
    timestamp,
)
from GODDESS.GODDESS import (
    dropdesktopidentity,
    formatlog,
    popenisolated,
    softwarelogpath,
)
from exchange.exchange import exsetfiles
from graphics.graphics import init as ginit, close as gclose, clear as gclear, present as gpresent
from graphics.graphics import beginscaledfileframe, endscaledfileframe, blitfilepartfast, blitfilescaledfast, fillrectfast, drawcursor, cursorbox, drawline, drawrect, drawtextttf, setpixel, getscreensize, refreshfb, measuretext
from graphics.graphics import backendinfo, framebufferpresentationproof, screenshotpng
from graphics.graphics import setdisplayadjustment, refreshdisplayadjustment, displayadjustment, displayadjustregions
from graphics.graphics import GPUDeviceLostError
from graphics.graphics import gpuavailable, gpuhealthcheck, gpumetrics, gpubeginregions, gpusetregion, gpuframestats, gpuinvalidatesurface
from graphics.graphics import gpubegin, gpuend, gpuabort, gpufallback, gpusetframebudget, gpureadpixel
from graphics.graphics import kmspresentationfd, kmspresentationpending, kmspresentationstalled
from graphics.graphics import kmshandlepresentationevent, kmsseteventdriven, kmswaitflip
from graphics.graphics import gputexturecreate, gputextureupdate, gputexturedestroy, gputextureinfo
from graphics.graphics import gputargetcreate, gputargetdestroy, gputargetbegin, gputargetend
from graphics.graphics import gpudrawtexture, gpudrawrect, gpubatchrects, gpudrawroundedrect, gpudrawcircle, gpudrawgradient, gpudrawline
from graphics.graphics import gpubatchroundedrects, gpubatchcircles, gpubatchgradients, gpubatchlines
from graphics.graphics import gpudrawshadow, gpudrawblur, gpudrawimage, gpudrawtext, gpubatchtexts, gpuprewarmtext, gpudrawcursor
from graphics.graphics import gpudrawscene3d
from graphics.graphics import gpuvideoavailable, gpuvideoinitialise, gpuvideoimportcapabilities, gpuvideosurfacecreate, gpuvideosurfacedestroy, gpuvideosurfaceinfo, gpudrawvideosurface
from graphics.graphics import gpupresentationbufferavailable, gpupresentationbuffercreate, gpupresentationbufferrelease
from graphics.graphics import CURSORS, GPUUPLOADSTAGINGLIMIT, loadcursor, opengloffscreen, openglclose
from graphics.graphics import log as graphicslog




## globals

# paths
EPHBASE = "/.ephemeral/windowserver"
SETTINGS = "/the one/settings/window server"
WINDOWATTRIBUTEPATH = os.path.join(SETTINGS, "window attributes.json")
DISPLAYSETTINGS = "/the one/settings/display/settings.json"
SOCKPATH = "/.ephemeral/windowserver/accept.sock"
VIDEOSOCKPATH = "/.ephemeral/windowserver/video.sock"
CHROMIUMXWDBUFFER = "/.ephemeral/chromium/framebuffer/Xvfb_screen0"
BUFBASE = "/.ephemeral/windowserver/buffers"
STATEBASE = "/.ephemeral/windowserver/state"
ACCELERATEDREADYPATH = "/.ephemeral/windowserver/state/accelerated-lockscreen-ready.json"
ACCELERATEDBOOTREADYPATH = "/.ephemeral/windowserver/state/accelerated-boot-ready.json"
ACCELERATIONUNAVAILABLEPATH = "/.ephemeral/windowserver/state/acceleration-unavailable.json"
GRAPHICSCAPABILITYPATH = "/.ephemeral/windowserver/state/graphics-capability.json"
LOCKSCREENREADYPATH = "/.ephemeral/windowserver/state/lockscreen-ready.json"
CLIPBASE = "/.ephemeral/windowserver/clip"
SCREENSHOTBASE = "/.ephemeral/windowserver/screenshots"
FBNODE = "/the one/drivers/nodes/fb0"
INPUTSOCKPATH = "/.ephemeral/inputserver/accept.sock"
AUDIOSOCKPATH = "/.ephemeral/audio/accept.sock"
LOGFILE = "/the one/logs/windowserver.py.log"
PROCESSROOT = "/the one/drivers/processes"
TELEMETRYPATH = "/the one/logs/graphics telemetry.json"
WINDOWFONT = "/the one/resources/fonts/atkinsonhyperlegiblenext.ttf"
BOOTANIMATIONFONT = "/the one/resources/fonts/cambria.ttf"

# misc
DEBUGWINDOWSERVER = False
STARTLOGFD = None
LOGOPS = True
GPUDEVICEFAILUREEXIT = 70
BACKENDINITFAILUREEXIT = 71
GPUCOMPOSITORFAILUREEXIT = 72
SHOWDESKTOPSTATE = {"active": False, "windows": []}
SERVERRUN = True
SERVERID = None
VIDEOSERVER = None
GRAPHICSPRESENTFD = None
sel = selectors.DefaultSelector()
CFG = None
WINDOWATTRIBUTES = {}
WINDOWATTRIBUTESDIRTY = False
WINDOWATTRIBUTESDIRTYAT = 0.0
WINDOWATTRIBUTESLASTSAVE = 0.0
GPUCOMPOSITOR = False
GPUFAILED = False
GPUCHROMETEXTURES = {}
GPUCOMMANDAPIVERSION = 5
GPUCOMMANDLIMIT = 1024
GPUCOMMANDTOTALLIMIT = 8192
GPUCOMMANDTEXTLIMIT = 1024
GPUCOMMANDIMAGEPIXELS = 16777216
GPUCOMMANDDAMAGELIMIT = 64
GPUCOMMANDLAYERLIMIT = 8
GPUCOMMANDGRIDITEMLIMIT = 32768
GPUCOMMAND3DMESHLIMIT = 32
GPUCOMMAND3DVERTEXLIMIT = 8192
GPUCOMMAND3DINDEXLIMIT = 24576
CLIENTINBUFLIMIT = 4 * 1024 * 1024
CLIENTOUTBUFLIMIT = 4 * 1024 * 1024
CLIENTLIMIT = 128
CLIENTWINDOWLIMIT = 64
VIDEOCLIENTLIMIT = 32
CLIENTBUFFERMULTIPLIER = 8
GLOBALBUFFERMULTIPLIER = 32
# Preserve motion coalescing for blocked clients without imposing a timer on
# the normal input path.
CLIENTPOINTERINTERVAL = 0.0
CLIENTPOINTERCOALESCED = 0
CLIENTOUTBUFPEAK = 0
CLIENTOUTPUTDROPS = 0
MAXRECTS = 32
GPUCOMMANDERRORS = 0
GPUCOMMANDLASTERROR = ""
GPUOCCLUSION = True
GPUOCCLUSIONCULLED = 0
GPUOCCLUSIONLAST = 0
GPUFULLFRAMEFALLBACKS = 0
GPUWORKLOADS = {"full": [], "partial": [], "animation": []}
GPUSCENEUPDATESQUEUED = 0
GPUSCENEUPDATESCOMPLETED = 0
GPUSCENEUPDATEPEAK = 0
GPUSCENEUPDATEMS = 0.0
GPUFRAMESEQUENCE = 0
GPUPENDINGCOMMITRECEIPTS = []
GPUCAPTUREDCOMMITRECEIPTS = []
GPUDEFERREDCOMMITRECEIPTS = []
GPUCAPTUREDCHROMIUMPRESENTATIONS = []
GPUPENDINGCHROMIUMPRESENTATIONS = []
FRAMEBUFFERFRAMESEQUENCE = 0
GPUPRESENTATIONGATEWAITS = 0
GPUPRESENTATIONGATERELEASES = 0
GPUPRESENTATIONGATEWAITMS = 0.0
GPUPRESENTATIONGATEMAXMS = 0.0
ACCELERATEDBOOTREADY = False
ACCELERATEDLOCKSCREENREADY = False
ACCELERATEDLOCKSCREENPOSTHANDOFFREADY = False
FRAMEBUFFERLOCKSCREENREADY = False
FRAMEBUFFERLOCKSCREENPOSTHANDOFFREADY = False
FRAMEBUFFERPROOFLASTLOG = 0.0
RETAINEDSYSTEMFRAMELOGGED = False
STARTUPFRAMEWAITLOGGED = False
GPUFIRSTFRAMESTARTED = False
GPUFIRSTFRAMECOMPLETED = False
VIDEOAUTH = {}
VIDEOCLIENTS = {}
VIDEORETIRED = []
VIDEOPACKETLIMIT = 65536
VIDEOMAXFDS = 4
VIDEOMAXSTREAMS = 32
VIDEOMAXINFLIGHT = 16
PRESENTATIONMAXINFLIGHT = 3
VIDEOTELEMETRY = {
    "connections": 0,
    "frames": 0,
    "presented_frames": 0,
    "page_flip_presented_frames": 0,
    "presentation_receipts_pending": 0,
    "superseded_frames": 0,
    "composed_frames": 0,
    "planar_frames": 0,
    "gpu_scaled_frames": 0,
    "native_resolution_frames": 0,
    "partial_damage_frames": 0,
    "full_damage_frames": 0,
    "direct_composition_draws": 0,
    "maximum_active_surfaces": 0,
    "releases": 0,
    "drops": 0,
    "commands": 0,
    "missing_surfaces": 0,
    "draw_failures": 0,
    "protocol_errors": 0,
}
GPUSHADOWS = True
GPUTRANSITIONS = True
GPUTRANSITIONMS = 140
GPUSHADOWRADIUS = 18
GPUSHADOWOPACITY = 0.35
GPUBLUR = True
GPUBLURRADIUS = 12
GPUUISCALE = 1.0
GRAPHICSTHEME = "classic"
GRAPHICSTHEMES = {
    "classic": {
        "title": (0, 0, 0),
        "border": (60, 60, 60),
        "close": (239, 239, 239),
        "max": (192, 192, 192),
        "min": (145, 145, 145),
    },
    "dialog": {
        "title": (0, 0, 0),
        "border": (58, 58, 58),
        "close": (239, 239, 239),
        "max": (0, 0, 0),
        "min": (0, 0, 0),
    },
    "graphite": {
        "title": (24, 27, 32),
        "border": (83, 91, 104),
        "close": (255, 112, 112),
        "max": (224, 229, 237),
        "min": (168, 178, 194),
    },
    "high_contrast": {
        "title": (0, 0, 0),
        "border": (255, 255, 255),
        "close": (255, 255, 0),
        "max": (255, 255, 255),
        "min": (255, 255, 255),
    },
}

# Standard modal dialog protocol:
#   CREATE_DIALOG {parent, dialog_id, title, message,
#                  buttons:[{id, label, cancel?}], default?,
#                  input?:{value, select_all?, max_length?, allow_empty?, secret?}}
#   CREATE_PASSWORD_PROMPT {parent, dialog_id, title?, message?,
#                           max_length?, submit_label?, cancel_label?}
#   DIALOG_CREATED {dialog_id, winid, parent}
#   DIALOG_RESULT  {dialog_id, winid, parent, result, value?}
# The server owns the child window, rendering, focus, input, and cleanup.
DIALOGBACKGROUND = 0x000000
DIALOGTEXT = 0xEFEFEF
DIALOGOUTLINE = 0x3A3A3A
DIALOGBASEW = 480
DIALOGBASEH = 210
DIALOGBUTTONW = 112
DIALOGBUTTONH = 34
DIALOGPAD = 24
DIALOGGAP = 12
DIALOGINPUTH = 36
DIALOGINPUTPAD = 9
DIALOGINPUTHISTORY = 50
DIALOGINPUTBLINK = 0.53

# Array picker protocol:
#   CREATE_PICKER {parent, mode, title?, initial_path?, suggested_name?,
#                  default_extension?, allow_multiple?, filters?}
#   PICKER_CREATED {request_id, parent, mode}
#   PICKER_ATTACH {request_id}
#   PICKER_CONFIG {request_id, ...validated request}
#   PICKER_FINISH {request_id, status, paths?, locations?, overwrite_approved?}
#   PICKER_RESULT {request_id, parent, mode, status, paths, locations,
#                  overwrite_approved?}
# Window Server launches the trusted Array process, binds it to the requesting
# parent as a client-rendered modal child, and owns result/lifecycle routing.
PICKERVERSION = 1
PICKERMODES = ("open_file", "select_tier", "save_location", "save_as")
PICKERSESSIONS = {}
PICKERMAXFILTERS = 16
PICKERMAXEXTENSIONS = 64
PICKERARRAYPYTHON = "/the one/software/python/bin/python"
PICKERARRAYPATH = "/the one/build/array/array.py"
PICKERLASTPULSE = 0.0
PICKERSTARTTIMEOUT = 10.0
GPUANIMATIONLIMIT = 32
GPUANIMATIONDURATIONLIMIT = 5000
GPUANIMATIONEASINGS = ("linear", "ease_in", "ease_out", "ease_in_out")
GPUANIMATIONPROPERTIES = ("opacity", "translate", "scale", "rotation")
GPUANIMATIONS = {}
LASTGRAPHICSSTATE = 0.0
LASTGRAPHICSSTATEERROR = ""
LASTGRAPHICSSTATEERRORAT = 0.0
LASTDISPLAYADJUSTMENT = 0.0
LASTTELEMETRY = 0.0
TELEMETRYWRITEQUEUE = queue.Queue(maxsize=1)
TELEMETRYWRITER = None
TELEMETRYWRITERLOCK = threading.Lock()
TELEMETRYWRITESTOP = False
TELEMETRYWRITESTATS = {
    "queued": 0,
    "completed": 0,
    "coalesced": 0,
    "failures": 0,
    "last_write_ms": 0.0,
    "maximum_write_ms": 0.0,
    "last_queue_delay_ms": 0.0,
    "last_error": "",
}
AUDIOSTEP = 0.02
AUDIOGAIN = 1.0
AUDIOMUTE = False

# input
INPUTCID = None
INPUTCONN = None
INPUTINBUF = b""
INPUTOUTBUF = b""
INPUTLATENCYHISTORY = []
INPUTLATENCYCAP = 240
INPUTDRAINLIMIT = 256 * 1024
INPUTBYTESDRAINED = 0
INPUTDRAINCAPS = 0
INPUTPOINTERCOALESCED = 0
INPUTIDENTITY = None
INPUTRECONNECTAT = 0.0
TRUSTEDPARENTPID = os.getppid()
TRUSTEDPARENTSTART = None
PEERAUTHDIAGNOSTICS = set()
POINTERSAVEINTERVAL = 0.25
POINTERSAVELAST = 0.0
POINTERSAVEDIRTY = False

# screen
SCREENW = 1920
SCREENH = 1080
WORKX = 0
WORKY = 0
WORKW = SCREENW
WORKH = SCREENH
LASTFBPOLL = 0.0

# base chrome
BASEFRAMEW = 2
BASETITLEH = 28
BASEBTNWH = 20
BASEBTNGAP = 6
BASEPLACEDELTA = 32
BASESNAPTOP = 8
BASESNAPSIDE = 16
BASEHITEDGE = 6
BASEHITCORNER = 12

# scaled chrome
FRAMEW = 2
TITLEH = 28
BTNWH = 20
BTNGAP = 6
PLACEDELTA = 32
SNAPTOP = 8
SNAPSIDE = 16
HITEDGE = 6
HITCORNER = 12

# focus, hover, and pointer state
FOCUSWID = None
FOCUSPENDING = None
HOVERWID = None
HOVERBUTTON = None
POINTERX = SCREENW // 2
POINTERY = SCREENH // 2
BTNDOWN = set()
POINTERGRAB = {"wid": None, "btn": 0}

# Match Array's sidebar-item hover treatment.
WINDOWBUTTONHOVER = 0x242424

# cursor
LASTCURSOR = [0, 0, 0, 0]
CURSORDIRTY = True
CURSORENABLED = True
BOOTCURSORHIDE = True
STARTUPCURSORWAIT = True
CURSORMODE = "arrow"
CURSORSIZES = {}
CURSORCENTERED = ("text", "busy", "resize_h", "resize_v", "resize_diag1", "resize_diag2")

# clients
clients = {}
windows = {}
zorder = []
DESKTOPCLIENTS = set()

# damage and overlay
DAMAGERECTS = []
OVERLAYRECTS = []
OVERLAYACTIVE = []
OVERLAYTTLMS = 250
OVERLAYMAX = 64

# placement
PLACEX = 0
PLACEY = 0
PLACEDELTA = 32

# clipboard
clipboard = {"type": None, "path": None}
CLIPBOARDGESTURESECONDS = 2.0

# drag
DRAGINFO = {"wid": None, "kind": None, "btn": 0, "sx": 0, "sy": 0, "ox": 0, "oy": 0, "ow": 0, "oh": 0}
WINSTATE = {"held": False, "used": False}
VBOXDND = {"wid": None, "kind": None, "format": "", "x": 0, "y": 0, "dropped": False}
SNAPTOP = 8
SNAPSIDE = 16
SNAPPREVIEW = None

# kill queue
PENDINGKILLS = {}

# launcher
ARRAYPID = None
ARRAYLAST = 0.0
ARRAYCOOLDOWN = 0.35
BRICKPID = None
BRICKLAST = 0.0
BRICKCOOLDOWN = 0.35
OPERATIONSCENTREPID = None
OPERATIONSCENTRELAST = 0.0
OPERATIONSCENTRECOOLDOWN = 0.35
OPERATIONSCENTREPATH = "/the one/build/operations/operationscentre.py"
LOCKSCREENPID = None
LOCKSESSIONPROCESS = None
LOCKSCREENIDENTITY = None
SESSIONLOCKED = False
LOCKSCREENLAST = 0.0
LOCKSCREENCOOLDOWN = 0.35
STARTUPPATH = "/the one/build/startup/startup.py"
VBOXDNDBASE = "/.ephemeral/virtualbox/dnd"
SESSIONUID = int(os.environ.get("T1OS_SESSION_UID", "1000"))
SESSIONGID = int(os.environ.get("T1OS_SESSION_GID", "1000"))
KERNELDOMAINS = frozenset((
    "goddess", "startup", "architect", "operations", "procedures",
    "window", "brick", "audio", "driver", "input", "network", "reign",
    "python", "exchange", "expanse", "virtualbox", "boot-animation",
    "desktop", "video", "settings", "snap", "chromium", "picker",
    "lockscreen",
))


class GPUAccelerationUnavailableError(RuntimeError):
    pass


class GPUCompositorError(RuntimeError):
    pass


## functions

# misc functions
def readprocessstat(pid):

    try:
        with open(os.path.join(PROCESSROOT, str(int(pid)), "stat"), "r", encoding="utf-8") as stream:
            value = stream.read(8192)

        end = value.rfind(")")
        fields = value[end + 2:].split() if end >= 0 else []
        if len(fields) <= 19:
            return None

        return {"ppid": int(fields[1]), "starttime": int(fields[19])}
    except (OSError, TypeError, ValueError):
        return None


def processsecuritydomain(pid):

    try:
        with open(
            os.path.join(PROCESSROOT, str(int(pid)), "attr", "current"),
            "r",
            encoding="utf-8",
            errors="strict",
        ) as stream:
            label = stream.read(256).strip().split("\0", 1)[0]
    except (OSError, TypeError, ValueError, UnicodeError):
        return None

    prefix = "t1os:"
    if not label.startswith(prefix):
        return None

    domain = label[len(prefix):]
    return domain if domain in KERNELDOMAINS else None


def processscriptpath(pid, executable, arguments):

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
        with open(os.path.join(PROCESSROOT, str(pid), "cmdline"), "rb") as stream:
            raw = stream.read(64 * 1024)
        arguments = [part for part in raw.split(b"\0") if part]
    except OSError:
        return None

    # The kernel domain and PID/start generation are authorization.  The exe
    # symlink is optional path metadata and can be unreadable under hardened
    # procfs even when cmdline and the T1OS getprocattr label are available.
    try:
        executable = os.path.realpath(os.readlink(
            os.path.join(PROCESSROOT, str(pid), "exe")))
    except OSError:
        executable = ""

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

    # The label and pidfd reads happen after the first generation check. Read
    # the process generation once more so exit/reuse between those operations
    # can never splice an old executable identity to a new security domain.
    final = readprocessstat(pid)
    if not final or int(final["starttime"]) != int(first["starttime"]):
        closeprocessidentity(identity)
        return None

    return identity


def waitforprocessidentity(pid, domain, timeout=1.0):

    """Capture one exact launched process after its kernel domain transition."""

    generation = readprocessstat(pid)
    if not generation:
        return None

    starttime = int(generation["starttime"])
    deadline = time.monotonic() + max(0.05, float(timeout))

    while time.monotonic() <= deadline:
        current = readprocessstat(pid)
        if not current or int(current["starttime"]) != starttime:
            return None

        identity = processidentity(pid, capturepidfd=True)
        if (
            identity
            and int(identity.get("starttime", -1)) == starttime
            and identity.get("domain") == str(domain)
            and processidentityalive(identity)
        ):
            return identity

        closeprocessidentity(identity)
        time.sleep(0.01)

    return None


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

    if isinstance(identity, dict) and identity.get("trusted_launcher") is True:
        current = readprocessstat(identity.get("pid"))
        return bool(
            int(identity.get("pid", 0)) == int(TRUSTEDPARENTPID)
            and current
            and int(current.get("starttime", -1)) ==
                int(TRUSTEDPARENTSTART or -2)
        )

    return bool(
        processidentityalive(identity)
        and processsecuritydomain(identity.get("pid")) == identity.get("domain")
    )


def sameprocessidentity(left, right):

    return bool(
        isinstance(left, dict)
        and isinstance(right, dict)
        and int(left.get("pid", 0)) == int(right.get("pid", -1))
        and int(left.get("starttime", 0)) == int(right.get("starttime", -1))
    )


def initializeipcidentity():

    global TRUSTEDPARENTPID, TRUSTEDPARENTSTART

    TRUSTEDPARENTPID = os.getppid()
    parent = readprocessstat(TRUSTEDPARENTPID)
    TRUSTEDPARENTSTART = parent.get("starttime") if parent else None
    return TRUSTEDPARENTSTART is not None


def identityistrustedsibling(identity):

    if not isinstance(identity, dict) or TRUSTEDPARENTSTART is None:
        return False

    parent = readprocessstat(identity.get("ppid"))
    return bool(
        int(identity.get("ppid", 0)) == int(TRUSTEDPARENTPID)
        and parent
        and int(parent["starttime"]) == int(TRUSTEDPARENTSTART)
    )


def socketpeeridentity(conn):

    if not hasattr(socket, "SO_PEERCRED"):
        return None

    try:
        raw = conn.getsockopt(
            socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        pid, uid, gid = struct.unpack("3i", raw)
    except (OSError, struct.error):
        return None

    servicepeer = uid == os.geteuid()
    sessionpeer = uid == SESSIONUID and gid == SESSIONGID
    # WindowServer drops to the desktop identity, while its measured GODDESS
    # parent remains root and must perform the bounded HELLO used as PID 1's
    # readiness barrier.  Admit that one captured PID/start-time generation
    # only; no other root process gains access through this exception.  The
    # relationship is authoritative even while early domain reporting is
    # still converging.
    current = readprocessstat(pid)
    trustedlauncher = bool(
        uid == 0
        and int(pid) == int(TRUSTEDPARENTPID)
        and current
        and int(current.get("starttime", -1)) == int(TRUSTEDPARENTSTART or -2)
    )
    identity = (
        {
            "pid": int(pid),
            "ppid": int(current.get("ppid", 0)),
            "starttime": int(current["starttime"]),
            "executable": "",
            "script": "",
            "domain": "goddess",
            "pidfd": None,
            "trusted_launcher": True,
        }
        if trustedlauncher else
        processidentity(pid, capturepidfd=True)
    )
    if identity is None and (servicepeer or sessionpeer) and not trustedlauncher:
        # A freshly exec'd local peer can become visible through the socket
        # before every procfs identity leaf is readable.  Retry only while the
        # exact PID/start generation remains unchanged; authority still comes
        # exclusively from the final kernel domain and measured executable.
        generation = current
        deadline = time.monotonic() + 0.25
        while generation and time.monotonic() < deadline:
            time.sleep(0.005)
            now = readprocessstat(pid)
            if (
                not now
                or int(now.get("starttime", -1)) !=
                    int(generation.get("starttime", -2))
            ):
                break
            identity = processidentity(pid, capturepidfd=True)
            if identity is not None:
                break
        if identity is None:
            diagnostic = ("identity-unavailable", int(pid), int(uid), int(gid))
            if diagnostic not in PEERAUTHDIAGNOSTICS:
                PEERAUTHDIAGNOSTICS.add(diagnostic)
                details = []
                try:
                    details.append(
                        "exe=" + os.readlink(
                            os.path.join(PROCESSROOT, str(int(pid)), "exe")
                        )
                    )
                except OSError as error:
                    details.append(f"exe_error={type(error).__name__}:{error}")
                try:
                    with open(
                        os.path.join(PROCESSROOT, str(int(pid)), "cmdline"), "rb"
                    ) as stream:
                        details.append(f"cmdline_bytes={len(stream.read(65536))}")
                except OSError as error:
                    details.append(f"cmdline_error={type(error).__name__}:{error}")
                graphicslog(
                    f"> graphics local peer identity unavailable after retry "
                    f"pid={pid} uid={uid} gid={gid} generation={generation} "
                    f"current={readprocessstat(pid)} "
                    f"domain={processsecuritydomain(pid)} {' '.join(details)}"
                )
    if identity:
        identity["uid"] = int(uid)
        identity["gid"] = int(gid)
        sessiondiagnostic = (
            "session-peer", int(pid), int(identity.get("starttime", 0))
        )
        if sessionpeer and sessiondiagnostic not in PEERAUTHDIAGNOSTICS:
            PEERAUTHDIAGNOSTICS.add(sessiondiagnostic)
            graphicslog(
                f"> graphics session peer captured pid={pid} uid={uid} gid={gid} "
                f"domain={identity.get('domain')} executable={identity.get('executable')} "
                f"script={identity.get('script')} start={identity.get('starttime')}"
            )
    if not (servicepeer or sessionpeer or trustedlauncher):
        diagnostic = (int(pid), int(uid), int(gid), bool(identity))
        if diagnostic not in PEERAUTHDIAGNOSTICS:
            PEERAUTHDIAGNOSTICS.add(diagnostic)
            graphicslog(
                f"> graphics peer rejected pid={pid} uid={uid} gid={gid} "
                f"identity={bool(identity)} expected_parent={TRUSTEDPARENTPID} "
                f"parent_start={TRUSTEDPARENTSTART}"
            )
        closeprocessidentity(identity)
        return None
    if identity is None:
        return None
    if trustedlauncher and "trusted-launcher" not in PEERAUTHDIAGNOSTICS:
        PEERAUTHDIAGNOSTICS.add("trusted-launcher")
        graphicslog(
            f"> graphics trusted launcher accepted pid={pid} uid={uid} "
            f"start={current.get('starttime')}"
        )
    return identity


def authenticateinputserverpeer(conn):

    identity = socketpeeridentity(conn)
    authorized = bool(
        identity
        and identityistrustedsibling(identity)
        and identity.get("domain") == "input"
    )
    if not authorized:
        closeprocessidentity(identity)
        return None
    return identity


def peercapabilities(identity):

    capabilities = set()

    if not processidentitycurrent(identity):
        return capabilities

    domain = str(identity.get("domain", ""))

    if domain == "expanse":
        capabilities.update(("desktop_controller", "desktop_surfaces"))

    if domain == "virtualbox":
        capabilities.add("guest_integration")

    if domain == "snap":
        capabilities.update(("screen_capture", "snap_surfaces"))

    if domain == "settings":
        capabilities.update(("display_settings", "protected_auth_surface"))

    if domain == "startup":
        capabilities.add("startup_surface")

    if domain == "lockscreen":
        capabilities.update(("session_authentication", "lockscreen_surface"))

    if domain == "boot-animation":
        capabilities.add("system_animation_surface")

    return capabilities


def clienthascapability(cid, capability, requirealive=True):

    state = clients.get(cid)
    if not state or capability not in state.get("capabilities", set()):
        return False
    return not requirealive or processidentitycurrent(state.get("identity"))


def verifiedclientpath(cid):

    state = clients.get(cid, {})
    identity = state.get("identity")
    # Path is display/placement metadata only. Prefer the interpreted script,
    # but preserve native-client compatibility with the kernel executable path.
    return (
        str(identity.get("script") or identity.get("executable") or "")
        if isinstance(identity, dict)
        else ""
    )


def authorizedwindowrole(cid, role):

    role = str(role)
    if role == "window":
        return True

    rolecapabilities = {
        "desktop": "desktop_surfaces",
        "expanse": "desktop_surfaces",
        "startmenu": "desktop_surfaces",
        "taskbar": "desktop_surfaces",
        "instancelist": "desktop_surfaces",
        "search": "desktop_surfaces",
        "taskmenu": "desktop_surfaces",
        "tooltip": "desktop_surfaces",
        "volumebar": "desktop_surfaces",
        "snap_overlay": "snap_surfaces",
        "startup": "startup_surface",
        "lockscreen": "lockscreen_surface",
        "boot": "system_animation_surface",
        "splash": "system_animation_surface",
        "boot animation": "system_animation_surface",
        "bootanimation": "system_animation_surface",
        "boot_animation": "system_animation_surface",
        "system animation": "system_animation_surface",
    }
    capability = rolecapabilities.get(role)
    return bool(capability and clienthascapability(cid, capability))


def clienthasinteractivefocus(cid):

    win = windows.get(FOCUSWID)
    return bool(
        not SESSIONLOCKED
        and win
        and win.get("cid") == cid
        and win.get("mapped")
        and str(win.get("role", "")) == "window"
        and processidentitycurrent(clients.get(cid, {}).get("identity"))
    )


def markclipboardgesture(cid):

    state = clients.get(cid)
    if state and clienthasinteractivefocus(cid):
        state["clipboard_gesture_until"] = (
            time.monotonic() + float(CLIPBOARDGESTURESECONDS))
        return True
    return False


def markphysicalgesture(cid, seconds=5.0):

    state = clients.get(cid)
    if state and clienthasinteractivefocus(cid):
        state["physical_gesture_until"] = (
            time.monotonic() + max(0.1, float(seconds)))
        return True
    return False


def clienthasphysicalgesture(cid, consume=True):

    state = clients.get(cid)
    if not state or not clienthasinteractivefocus(cid):
        return False
    try:
        permitted = time.monotonic() <= float(
            state.get("physical_gesture_until", 0.0))
    except (TypeError, ValueError):
        permitted = False
    if permitted and consume:
        state["physical_gesture_until"] = 0.0
    return permitted


def clienthasclipboardaccess(cid, consume=True):

    state = clients.get(cid)
    if not state or not clienthasinteractivefocus(cid):
        return False

    try:
        permitted = time.monotonic() <= float(
            state.get("clipboard_gesture_until", 0.0))
    except (TypeError, ValueError):
        permitted = False

    if permitted and consume:
        state["clipboard_gesture_until"] = 0.0
    return permitted


def securedirectory(path, mode=0o700, group=None):

    parent = os.path.dirname(os.path.abspath(path))
    parentinfo = os.lstat(parent)
    if (
        not stat.S_ISDIR(parentinfo.st_mode)
        or stat.S_ISLNK(parentinfo.st_mode)
        or parentinfo.st_uid != os.geteuid()
        or stat.S_IMODE(parentinfo.st_mode) & 0o022
    ):
        raise PermissionError(f"unsafe WindowServer parent directory {parent}")

    os.makedirs(path, mode=mode, exist_ok=True)
    info = os.lstat(path)
    if (
        not stat.S_ISDIR(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or info.st_uid != os.geteuid()
    ):
        raise PermissionError(f"unsafe WindowServer directory {path}")
    if group is not None:
        os.chown(path, -1, int(group))
    os.chmod(path, mode)


def removestalesocket(path):

    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return

    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.geteuid():
        raise PermissionError(f"unsafe stale WindowServer socket {path}")
    os.unlink(path)


def allocatedwindowbytes(cid=None):

    total = 0
    selected = (
        clients.get(cid, {}).get("windows", [])
        if cid is not None
        else windows
    )
    for wid in list(selected):
        win = windows.get(wid)
        if not win:
            continue
        path = win.get("_owned_buffer", win.get("buffer"))
        try:
            total += max(0, int(os.path.getsize(path)))
        except (OSError, TypeError, ValueError):
            pass
    return total


def windowbufferallocationpermitted(cid, additional):

    additional = max(0, int(additional))
    screenbytes = max(1, int(SCREENW)) * max(1, int(SCREENH)) * 4
    clientlimit = max(
        64 * 1024 * 1024, screenbytes * CLIENTBUFFERMULTIPLIER)
    globallimit = max(
        256 * 1024 * 1024, screenbytes * GLOBALBUFFERMULTIPLIER)
    return bool(
        allocatedwindowbytes(cid) + additional <= clientlimit
        and allocatedwindowbytes() + additional <= globallimit
    )


def makepaths():

    try:

        # Keep compositor control sockets, buffers, clipboard state, and capture
        # data private to the OS service identity.
        securedirectory(EPHBASE, 0o750, SESSIONGID)

        # create buffers subtier
        securedirectory(BUFBASE, 0o710, SESSIONGID)

        # create state subtier
        securedirectory(STATEBASE, 0o750, SESSIONGID)

        # A WindowServer restart must never inherit an earlier renderer's
        # accelerated-readiness proofs.
        for readinesspath in (
            ACCELERATEDBOOTREADYPATH,
            ACCELERATEDREADYPATH,
            ACCELERATIONUNAVAILABLEPATH,
            GRAPHICSCAPABILITYPATH,
            LOCKSCREENREADYPATH,
        ):

            try:
                os.unlink(readinesspath)
            except FileNotFoundError:
                pass

        # create clipboard subtier
        securedirectory(CLIPBASE, 0o700)
        clearclipboard()

        # create screenshot clipboard source tier
        securedirectory(SCREENSHOTBASE, 0o710, SESSIONGID)

        # create settings tier if needed
        os.makedirs(SETTINGS, exist_ok=True)

    except PermissionError:

        # permission denied creating tiers
        log(f"permission denied creating window server tiers")
        sys.exit(1)

    except OSError as e:

        # os error creating tiers
        log(f"error creating window server tiers {e}")
        sys.exit(1)


def writefbsize(w, h):

    # normalise
    sw = int(w)
    sh = int(h)

    if sw < 1:
        sw = 1

    if sh < 1:
        sh = 1

    text = f"{sw}x{sh}"

    # write windowserver state fb.size
    p = os.path.join(STATEBASE, "fb.size")

    with open(p, "w") as f:
        f.write(text)


def writepresentationreceipt(path, payload):

    temporary = f"{path}.{os.getpid()}.new"

    with open(temporary, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, sort_keys=True, separators=(",", ":"))
        stream.flush()
        os.fsync(stream.fileno())

    os.replace(temporary, path)
    return True


def writegraphicscapabilityreceipt():

    state = backendinfo()
    backend = str(state.get("backend", ""))
    renderer = str(state.get("renderer", ""))
    hardware = bool(state.get("hardware_accelerated", False))
    software = bool(state.get("software_renderer", False))

    if (
        backend == "opengl"
        and GPUCOMPOSITOR
        and not GPUFAILED
        and software
        and not hardware
    ):
        capability = "acceleration-unavailable"
    elif (
        backend == "opengl"
        and GPUCOMPOSITOR
        and not GPUFAILED
        and hardware
    ):
        capability = "accelerated-candidate"
    else:
        capability = "display-backend"

    payload = {
        "format": 1,
        "windowserver_pid": int(os.getpid()),
        "server": str(SERVERID or ""),
        "state": capability,
        "backend": backend,
        "renderer": renderer,
        "drm_driver": str(state.get("drm_driver", "")),
        "software_renderer": software,
        "hardware_accelerated": hardware,
        "gpu_compositor": bool(GPUCOMPOSITOR),
        "gpu_failed": bool(GPUFAILED),
    }
    writepresentationreceipt(GRAPHICSCAPABILITYPATH, payload)
    graphicslog(
        f"> graphics capability state={capability} "
        f"renderer={renderer or 'unknown'} "
        f"driver={payload['drm_driver'] or 'unknown'}"
    )
    return payload


def topmostpresentationwindow(role):

    for wid in reversed(zorder):
        win = windows.get(wid)

        if win is None or not win.get("mapped"):
            continue

        if float(win.get("opacity", 1.0)) <= 0.0:
            continue

        return int(wid) if str(win.get("role", "")) == str(role) else None

    return None


def invalidatelockscreenpresentation():

    global ACCELERATEDLOCKSCREENREADY, ACCELERATEDLOCKSCREENPOSTHANDOFFREADY
    global FRAMEBUFFERLOCKSCREENREADY, FRAMEBUFFERLOCKSCREENPOSTHANDOFFREADY

    if not (
        ACCELERATEDLOCKSCREENREADY or
        ACCELERATEDLOCKSCREENPOSTHANDOFFREADY or
        FRAMEBUFFERLOCKSCREENREADY or
        FRAMEBUFFERLOCKSCREENPOSTHANDOFFREADY or
        os.path.lexists(LOCKSCREENREADYPATH)
    ):
        return True

    try:
        os.unlink(LOCKSCREENREADYPATH)
    except FileNotFoundError:
        pass
    except OSError as error:
        graphicslog(f"> graphics could not invalidate lock-screen readiness {error}")
        return False

    ACCELERATEDLOCKSCREENREADY = False
    ACCELERATEDLOCKSCREENPOSTHANDOFFREADY = False
    FRAMEBUFFERLOCKSCREENREADY = False
    FRAMEBUFFERLOCKSCREENPOSTHANDOFFREADY = False
    return True


def presentationprocessidentity(window, role):

    identity = clients.get(window.get("cid"), {}).get("identity")
    expected = {
        "lockscreen": "lockscreen",
        "boot animation": "boot-animation",
    }.get(str(role))

    if (
        not expected or
        not processidentitycurrent(identity) or
        str(identity.get("domain", "")) != expected
    ):
        raise PermissionError(f"{role} presentation owner is not current")

    return {
        "presenter_pid": int(identity.get("pid", 0)),
        "presenter_starttime": int(identity.get("starttime", 0)),
        "presenter_domain": expected,
    }


def windowservergeneration():

    identity = readprocessstat(os.getpid())

    if not identity or int(identity.get("starttime", 0)) <= 0:
        raise RuntimeError("window server process generation is unavailable")

    return int(identity["starttime"])


def writeacceleratedpresentationready(seen, role, path, operation):

    presentedwindows = [
        int(wid)
        for wid in seen
        if wid in windows
        and windows[wid].get("mapped")
        and windows[wid].get("role") == role
    ]

    if not presentedwindows:
        return False

    topmost = topmostpresentationwindow(role)

    if topmost is None or topmost not in presentedwindows:
        return False

    presentationwindow = windows.get(topmost, {})
    presentationidentity = presentationprocessidentity(presentationwindow, role)
    fullcoverage = bool(
        int(presentationwindow.get("x", 0)) <= 0
        and int(presentationwindow.get("y", 0)) <= 0
        and int(presentationwindow.get("x", 0))
        + int(presentationwindow.get("w", 0)) >= int(SCREENW)
        and int(presentationwindow.get("y", 0))
        + int(presentationwindow.get("h", 0)) >= int(SCREENH)
    )

    if not fullcoverage:
        return False

    if not kmswaitflip(waitpulse=graphicspresentationpulse):
        raise RuntimeError(f"accelerated {operation} page flip did not complete")

    gpuhealthcheck(
        synchronize=True,
        operation=f"accelerated {operation} presentation",
    )
    state = backendinfo()

    if (
        state.get("backend") != "opengl"
        or not GPUCOMPOSITOR
        or GPUFAILED
    ):
        raise RuntimeError(f"{operation} GPU presentation owner was not usable")

    if not state.get("hardware_accelerated", False):
        # A software GL renderer can successfully render, synchronize and page
        # flip without providing GPU acceleration. This is a capability
        # absence, not a lost DRM device. Publish a PID-bound receipt so PID 1
        # can replace this owner with the CPU-rendered KMS backend without
        # pointlessly resetting a healthy display device.
        unavailable = {
            "format": 1,
            "windowserver_pid": int(os.getpid()),
            "server": str(SERVERID or ""),
            "role": str(role),
            "backend": str(state.get("backend", "")),
            "renderer": str(state.get("renderer", "")),
            "drm_driver": str(state.get("drm_driver", "")),
            "software_renderer": bool(state.get("software_renderer", False)),
            "hardware_accelerated": False,
            "gpu_failed": False,
            "presentation_completed": True,
            "full_coverage": True,
            "frame_sequence": int(GPUFRAMESEQUENCE),
            "reason": "hardware-acceleration-unavailable",
        }
        writepresentationreceipt(ACCELERATIONUNAVAILABLEPATH, unavailable)
        graphicslog(
            f"> graphics hardware acceleration unavailable "
            f"renderer={unavailable['renderer'] or 'unknown'} "
            f"driver={unavailable['drm_driver'] or 'unknown'} "
            f"role={role}; requesting CPU KMS owner"
        )
        raise GPUAccelerationUnavailableError(
            f"{operation} used a software renderer"
        )

    payload = {
        "format": 1,
        "windowserver_pid": int(os.getpid()),
        "windowserver_starttime": windowservergeneration(),
        "server": str(SERVERID or ""),
        "role": str(role),
        "backend": str(state.get("backend", "")),
        "renderer": str(state.get("renderer", "")),
        "drm_driver": str(state.get("drm_driver", "")),
        "hardware_accelerated": True,
        "gpu_failed": False,
        "frame_sequence": int(GPUFRAMESEQUENCE),
        "windows": presentedwindows,
        "topmost_window": int(topmost),
        "topmost_role": str(role),
        "full_coverage": True,
        "boot_active": bool(bootactive()),
    }
    payload.update(presentationidentity)
    writepresentationreceipt(path, payload)
    return payload


def writeacceleratedbootready(seen):

    global ACCELERATEDBOOTREADY

    if ACCELERATEDBOOTREADY:
        return True

    payload = writeacceleratedpresentationready(
        seen,
        "boot animation",
        ACCELERATEDBOOTREADYPATH,
        "boot-animation",
    )

    if not payload:
        return False

    ACCELERATEDBOOTREADY = True
    graphicslog(
        "> graphics first accelerated boot-animation presentation ready "
        f"renderer={payload['renderer']} driver={payload['drm_driver']}"
    )
    return True


def writeacceleratedlockscreenready(seen):

    global ACCELERATEDLOCKSCREENREADY, ACCELERATEDLOCKSCREENPOSTHANDOFFREADY

    if topmostpresentationwindow("lockscreen") is None:
        if not invalidatelockscreenpresentation():
            raise SystemExit(
                "lock-screen presentation could not be invalidated safely")
        return False

    if ACCELERATEDLOCKSCREENPOSTHANDOFFREADY:
        return True

    if ACCELERATEDLOCKSCREENREADY and bootactive():
        return True

    payload = writeacceleratedpresentationready(
        seen,
        "lockscreen",
        ACCELERATEDREADYPATH,
        "lock-screen",
    )

    if not payload:
        return False

    writepresentationreceipt(LOCKSCREENREADYPATH, payload)

    if not ACCELERATEDLOCKSCREENREADY:
        ACCELERATEDLOCKSCREENREADY = True
        graphicslog(
            "> graphics first accelerated lock-screen presentation ready "
            f"renderer={payload['renderer']} driver={payload['drm_driver']}"
        )

    if not payload.get("boot_active", True):
        ACCELERATEDLOCKSCREENPOSTHANDOFFREADY = True
        graphicslog("> graphics post-handoff accelerated lock-screen presentation ready")

    return True


def writeframebufferlockscreenready(seen):

    global FRAMEBUFFERLOCKSCREENREADY, FRAMEBUFFERLOCKSCREENPOSTHANDOFFREADY
    global FRAMEBUFFERPROOFLASTLOG

    if topmostpresentationwindow("lockscreen") is None:
        if not invalidatelockscreenpresentation():
            raise SystemExit(
                "lock-screen presentation could not be invalidated safely")
        return False

    if FRAMEBUFFERLOCKSCREENPOSTHANDOFFREADY:
        return True

    state = backendinfo()

    if state.get("backend") not in ("framebuffer", "kms-framebuffer"):
        return False

    paintedwindows = {
        int(wid)
        for wid in seen
        if wid in windows
    }
    lockwindows = [
        int(wid)
        for wid, win in windows.items()
        if (
            win.get("mapped")
            and win.get("role") == "lockscreen"
            and int(wid) in paintedwindows
        )
    ]

    if not lockwindows:
        return False

    topmost = topmostpresentationwindow("lockscreen")

    if topmost is None or topmost not in lockwindows:
        return False

    lockwindow = windows[topmost]
    presentationidentity = presentationprocessidentity(lockwindow, "lockscreen")
    fullcoverage = (
        int(lockwindow.get("x", 0)) <= 0
        and int(lockwindow.get("y", 0)) <= 0
        and int(lockwindow.get("x", 0)) + int(lockwindow.get("w", 0)) >= int(SCREENW)
        and int(lockwindow.get("y", 0)) + int(lockwindow.get("h", 0)) >= int(SCREENH)
    )

    if not fullcoverage:
        return False

    proof = framebufferpresentationproof(require_nonblack=True)

    if not proof.get("verified", False):
        now = time.monotonic()

        if now - FRAMEBUFFERPROOFLASTLOG >= 1.0:
            FRAMEBUFFERPROOFLASTLOG = now
            graphicslog(
                "> graphics framebuffer lock-screen composed but "
                "presentation unverified "
                f"backend={state.get('backend')} "
                f"expected_fb={proof.get('expected_framebuffer')} "
                f"current_fb={proof.get('framebuffer')} "
                f"mode_valid={proof.get('mode_valid')} "
                f"mode_matches={proof.get('mode_matches')} "
                f"connector={proof.get('connector')} "
                f"connected={proof.get('connector_connected')} "
                f"route={proof.get('connector_crtc')} "
                f"routed={proof.get('connector_routed')} "
                f"link={proof.get('connector_link_status')} "
                f"scanout={proof.get('scanout')} "
                f"write_committed={proof.get('write_committed')} "
                f"present_sequence={proof.get('present_sequence')} "
                f"dirty_status={proof.get('dirty_status')} "
                f"boundary={proof.get('presentation_boundary')} "
                f"vblank_supported="
                f"{(proof.get('vblank_sequence') or {}).get('supported')} "
                f"vblank_unsupported="
                f"{(proof.get('vblank_sequence') or {}).get('unsupported')} "
                f"vblank_advanced="
                f"{(proof.get('vblank_sequence') or {}).get('advanced')} "
                f"vblank_error="
                f"{(proof.get('vblank_sequence') or {}).get('error')} "
                f"readback={proof.get('readback')} "
                f"readback_mismatch_offset="
                f"{proof.get('readback_mismatch_offset')} "
                f"nonblack={proof.get('nonblack')} "
                f"legacy_conflicting_drm="
                f"{proof.get('legacy_conflicting_drm')} "
                f"error={proof.get('error', '')}"
            )
        return False

    payload = {
        "format": 1,
        "windowserver_pid": int(os.getpid()),
        "windowserver_starttime": windowservergeneration(),
        "server": str(SERVERID or ""),
        "role": "lockscreen",
        "backend": str(state.get("backend", "")),
        "renderer": str(state.get("renderer", "")),
        "drm_driver": str(state.get("drm_driver", "")),
        "hardware_accelerated": False,
        "gpu_failed": False,
        "frame_sequence": int(FRAMEBUFFERFRAMESEQUENCE),
        "windows": lockwindows,
        "topmost_window": int(topmost),
        "topmost_role": "lockscreen",
        "full_coverage": True,
        "boot_active": bool(bootactive()),
        "presentation_proof": proof,
    }
    payload.update(presentationidentity)
    writepresentationreceipt(LOCKSCREENREADYPATH, payload)

    if not FRAMEBUFFERLOCKSCREENREADY:
        FRAMEBUFFERLOCKSCREENREADY = True
        graphicslog("> graphics first verified framebuffer lock-screen presentation ready")

    if not payload["boot_active"]:
        FRAMEBUFFERLOCKSCREENPOSTHANDOFFREADY = True
        graphicslog("> graphics post-handoff framebuffer lock-screen presentation ready")

    return True


def telemetrywriterinfo():

    with TELEMETRYWRITERLOCK:
        result = dict(TELEMETRYWRITESTATS)

    result["pending"] = int(TELEMETRYWRITEQUEUE.qsize())
    result["writer_alive"] = bool(
        TELEMETRYWRITER is not None and TELEMETRYWRITER.is_alive()
    )
    return result


def telemetrywriterloop():

    while True:

        item = TELEMETRYWRITEQUEUE.get()

        if item is None:
            return

        path, state, queued = item
        started = time.monotonic_ns()
        temporary = f"{path}.pending"
        error = ""

        try:

            os.makedirs(os.path.dirname(path), exist_ok=True)

            with open(temporary, "w", encoding="utf-8") as handle:
                json.dump(state, handle, sort_keys=True, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())

            os.replace(temporary, path)

        except Exception as exception:

            error = str(exception)[:512]

            try:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            except Exception:
                pass

        elapsed = max(
            0.0,
            (time.monotonic_ns() - started) / 1000000.0,
        )
        queuedelay = max(
            0.0,
            (started - int(queued)) / 1000000.0,
        )

        with TELEMETRYWRITERLOCK:

            previouserror = str(TELEMETRYWRITESTATS["last_error"])
            TELEMETRYWRITESTATS["last_write_ms"] = round(elapsed, 3)
            TELEMETRYWRITESTATS["maximum_write_ms"] = round(
                max(
                    float(TELEMETRYWRITESTATS["maximum_write_ms"]),
                    elapsed,
                ),
                3,
            )
            TELEMETRYWRITESTATS["last_queue_delay_ms"] = round(
                queuedelay,
                3,
            )
            TELEMETRYWRITESTATS["last_error"] = error

            if error:
                TELEMETRYWRITESTATS["failures"] += 1
            else:
                TELEMETRYWRITESTATS["completed"] += 1

        if error and error != previouserror:
            graphicslog(
                f"> graphics telemetry persistence failed "
                f"{error}"
            )
        elif not error and previouserror:
            graphicslog("> graphics telemetry persistence recovered")


def queuetelemetrywrite(path, state):

    global TELEMETRYWRITER

    with TELEMETRYWRITERLOCK:

        if TELEMETRYWRITER is None or not TELEMETRYWRITER.is_alive():
            TELEMETRYWRITER = threading.Thread(
                target=telemetrywriterloop,
                name="graphics-telemetry-writer",
                daemon=True,
            )
            TELEMETRYWRITER.start()

    item = (str(path), state, time.monotonic_ns())

    try:
        TELEMETRYWRITEQUEUE.put_nowait(item)

    except queue.Full:

        try:
            TELEMETRYWRITEQUEUE.get_nowait()
        except queue.Empty:
            pass

        with TELEMETRYWRITERLOCK:
            TELEMETRYWRITESTATS["coalesced"] += 1

        try:
            TELEMETRYWRITEQUEUE.put_nowait(item)
        except queue.Full:
            return False

    with TELEMETRYWRITERLOCK:
        TELEMETRYWRITESTATS["queued"] += 1

    return True


def stoptelemetrywriter(timeout=2.0):

    thread = TELEMETRYWRITER

    if thread is None or not thread.is_alive():
        return True

    try:
        TELEMETRYWRITEQUEUE.put(None, timeout=max(0.0, float(timeout) / 4.0))
    except queue.Full:
        return False

    thread.join(timeout=max(0.0, float(timeout)))
    return not thread.is_alive()


def writegraphicsstate():

    global LASTTELEMETRY, LASTGRAPHICSSTATEERROR, LASTGRAPHICSSTATEERRORAT

    try:

        state = backendinfo()
        state["sampled"] = time.time()
        state["window_compositor"] = "gpu" if GPUCOMPOSITOR else "cpu"
        state["gpu_failed"] = bool(GPUFAILED)
        state["mapped_windows"] = sum(1 for win in windows.values() if win.get("mapped"))
        inputlatencies = sorted(float(value) for value in INPUTLATENCYHISTORY)
        inputp95 = max(
            0,
            min(
                len(inputlatencies) - 1,
                ((len(inputlatencies) * 95 + 99) // 100) - 1,
            ),
        ) if inputlatencies else 0
        state["input_telemetry"] = {
            "samples": len(inputlatencies),
            "last_dispatch_ms": round(float(INPUTLATENCYHISTORY[-1]), 3) if INPUTLATENCYHISTORY else 0.0,
            "average_dispatch_ms": round(sum(inputlatencies) / len(inputlatencies), 3) if inputlatencies else 0.0,
            "percentile_95_dispatch_ms": round(inputlatencies[inputp95], 3) if inputlatencies else 0.0,
            "maximum_dispatch_ms": round(inputlatencies[-1], 3) if inputlatencies else 0.0,
            "socket_bytes_drained": int(INPUTBYTESDRAINED),
            "socket_drain_caps": int(INPUTDRAINCAPS),
            "pointer_events_coalesced": int(INPUTPOINTERCOALESCED),
            "client_pointer_events_coalesced": int(CLIENTPOINTERCOALESCED),
            "client_output_pending_bytes": sum(
                len(state.get("outbuf", b""))
                + len(state.get("pending_motion") or b"")
                for state in clients.values()
            ),
            "client_output_pending_motions": sum(
                1
                for state in clients.values()
                if state.get("pending_motion") is not None
            ),
            "client_output_peak_bytes": int(CLIENTOUTBUFPEAK),
            "client_output_drops": int(CLIENTOUTPUTDROPS),
        }
        state["persistence_telemetry"] = telemetrywriterinfo()
        state["work_area"] = {
            "x": int(WORKX),
            "y": int(WORKY),
            "w": int(WORKW),
            "h": int(WORKH),
        }
        perwindow = []

        for wid, win in windows.items():

            frame = winframerect(win)

            framecontained = (
                int(frame[0]) >= int(WORKX)
                and int(frame[1]) >= int(WORKY)
                and int(frame[0]) + int(frame[2]) <= int(WORKX) + int(WORKW)
                and int(frame[1]) + int(frame[3]) <= int(WORKY) + int(WORKH)
            )

            perwindow.append({
                "id": int(wid),
                "pid": int(win.get("pid") or 0),
                "title": str(win.get("title", ""))[:128],
                "role": str(win.get("role", ""))[:32],
                "decoration": str(win.get("decoration", "server"))[:16],
                "mapped": bool(win.get("mapped")),
                "x": int(win.get("x", 0)),
                "y": int(win.get("y", 0)),
                "w": int(win.get("w", 0)),
                "h": int(win.get("h", 0)),
                "frame": [int(value) for value in frame],
                "frame_contained": bool(framecontained),
                "maximized": bool(win.get("_max", False)),
                "snap": str(win.get("_snap", "")),
                "managed": bool(win.get("gpu_commands")),
                "managed_only": bool(win.get("_managed_only", False)),
                "managed_commands": len(win.get("gpu_commands", [])),
                "managed_generation": int(win.get("_gpu_command_generation", 0)),
                "managed_presented_generation": int(
                    win.get("_gpu_presented_generation", 0)
                ),
                "managed_presentation_receipts_pending": len(
                    win.get("_gpu_commit_receipts", [])
                ),
                "scene_commits": int(win.get("_telemetry_scene_commits", 0)),
                "scene_clears": int(win.get("_telemetry_scene_clears", 0)),
                "batch_commits": int(win.get("_telemetry_batch_commits", 0)),
                "patch_commits": int(win.get("_telemetry_patch_commits", 0)),
                "damage_pixels": int(win.get("_telemetry_damage_pixels", 0)),
                "composited_pixels": int(win.get("_telemetry_composited_pixels", 0)),
                "cpu_damage_bytes": int(win.get("_telemetry_cpu_damage_bytes", 0)),
                "cpu_damage_events": int(win.get("_telemetry_cpu_damage_events", 0)),
                "cpu_damage_coalesces": int(win.get("_telemetry_cpu_damage_coalesces", 0)),
                "cpu_damage_pending_peak": int(win.get("_telemetry_cpu_damage_pending_peak", 0)),
                "gpu_upload_bytes": int(win.get("_telemetry_gpu_upload_bytes", 0)),
                "gpu_draw_calls": int(win.get("_telemetry_gpu_draw_calls", 0)),
                "gpu_frames": int(win.get("_telemetry_gpu_frames", 0)),
                "scene_texture_renders": int(win.get("_telemetry_scene_texture_renders", 0)),
                "scene_texture_hits": int(win.get("_telemetry_scene_texture_hits", 0)),
                "scene_texture_full_renders": int(win.get("_telemetry_scene_texture_full_renders", 0)),
                "scene_texture_partial_renders": int(win.get("_telemetry_scene_texture_partial_renders", 0)),
                "scene_texture_damage_pixels": int(win.get("_telemetry_scene_texture_damage_pixels", 0)),
                "scene_commands_considered": int(win.get("_telemetry_scene_commands_considered", 0)),
                "scene_commands_culled": int(win.get("_telemetry_scene_commands_culled", 0)),
                "scene_commands_drawn": int(win.get("_telemetry_scene_commands_drawn", 0)),
                "layer_texture_renders": int(win.get("_telemetry_layer_texture_renders", 0)),
                "layer_texture_hits": int(win.get("_telemetry_layer_texture_hits", 0)),
                "fallbacks": int(win.get("_telemetry_fallbacks", 0)),
                "last_fallback": str(win.get("_telemetry_last_fallback", ""))[:256],
            })

        state["window_telemetry"] = {
            "damage_rects": len(DAMAGERECTS),
            "presentation_gate_waits": int(GPUPRESENTATIONGATEWAITS),
            "presentation_gate_flip_releases": int(GPUPRESENTATIONGATERELEASES),
            "presentation_gate_average_wait_ms": round(
                float(GPUPRESENTATIONGATEWAITMS)
                / max(1, int(GPUPRESENTATIONGATEWAITS)),
                3,
            ),
            "presentation_gate_maximum_wait_ms": round(
                float(GPUPRESENTATIONGATEMAXMS),
                3,
            ),
            "managed_commands": sum(len(win.get("gpu_commands", [])) for win in windows.values()),
            "managed_presentation_receipts_pending": (
                len(GPUPENDINGCOMMITRECEIPTS)
                + len(GPUCAPTUREDCOMMITRECEIPTS)
                + len(GPUDEFERREDCOMMITRECEIPTS)
                + sum(
                    len(win.get("_gpu_commit_receipts", []))
                    for win in windows.values()
                )
            ),
            "managed_presentation_receipts_page_flip": len(
                GPUPENDINGCOMMITRECEIPTS
            ),
            "managed_presentation_receipts_captured": len(
                GPUCAPTUREDCOMMITRECEIPTS
            ),
            "managed_presentation_receipts_deferred": len(
                GPUDEFERREDCOMMITRECEIPTS
            ),
            "managed_command_errors": int(GPUCOMMANDERRORS),
            "managed_command_last_error": str(GPUCOMMANDLASTERROR),
            "occlusion_culled_windows": int(GPUOCCLUSIONLAST),
            "occlusion_culled_windows_total": int(GPUOCCLUSIONCULLED),
            "full_frame_fallbacks": int(GPUFULLFRAMEFALLBACKS),
            "scene_updates_queued": int(GPUSCENEUPDATESQUEUED),
            "scene_updates_completed": int(GPUSCENEUPDATESCOMPLETED),
            "scene_update_peak": int(GPUSCENEUPDATEPEAK),
            "scene_update_ms": round(float(GPUSCENEUPDATEMS), 3),
            "scene_partial_renders": sum(int(win.get("_telemetry_scene_texture_partial_renders", 0)) for win in windows.values()),
            "scene_command_culls": sum(int(win.get("_telemetry_scene_commands_culled", 0)) for win in windows.values()),
            "layer_texture_renders": sum(int(win.get("_telemetry_layer_texture_renders", 0)) for win in windows.values()),
            "layer_texture_hits": sum(int(win.get("_telemetry_layer_texture_hits", 0)) for win in windows.values()),
            "windows": perwindow,
        }
        state["video_telemetry"] = {
            **VIDEOTELEMETRY,
            "active_connections": len(VIDEOCLIENTS),
            "active_surfaces": sum(
                1
                for win in windows.values()
                for surface in win.get("_video_streams", {}).values()
                if int(surface.get("handle", 0)) > 0
            ),
            "retired_surfaces": len(VIDEORETIRED),
        }
        metrics = state.get("telemetry", {})
        state["workload_telemetry"] = gpuworkloadmetrics()
        samples = int(metrics.get("frame_samples", 0))
        average = float(metrics.get("average_frame_ms", 0.0))
        percentile50 = float(metrics.get("percentile_50_frame_ms", 0.0))
        percentile95 = float(metrics.get("percentile_95_frame_ms", 0.0))
        maximum = float(metrics.get("maximum_frame_ms", 0.0))
        steady = metrics.get("frame_profiles", {}).get("steady_partial", {})
        steadysamples = int(steady.get("samples", 0))
        steadyp95 = float(steady.get("percentile_95_ms", 0.0))
        framebudget = max(
            1.0,
            float(metrics.get("frame_budget_ms", 16.667)),
        )
        inputp95value = float(
            state["input_telemetry"]["percentile_95_dispatch_ms"]
        )
        inputmaximum = float(
            state["input_telemetry"]["maximum_dispatch_ms"]
        )
        inputsamples = int(state["input_telemetry"]["samples"])
        missedpercent = float(metrics.get("missed_frame_percent", 0.0))
        pageflipaverage = float(metrics.get("average_page_flip_ms", 0.0))
        presentationsamples = int(metrics.get("presentation_samples", 0))
        presentedfps = float(metrics.get("presented_fps", 0.0))
        presentationp95 = float(
            metrics.get("percentile_95_presentation_interval_ms", 0.0)
        )
        targetfps = 1000.0 / framebudget if framebudget > 0.0 else 0.0
        gates = {
            "runtime_hardware_renderer": bool(state.get("backend") == "opengl" and state.get("hardware_accelerated", False)),
            "drm_driver_recorded": bool(state.get("drm_driver")),
            "frame_budget_measured": bool(samples >= 120),
            "interactive_median_within_33ms": bool(samples < 120 or percentile50 <= 33.0),
            "average_within_40ms": bool(samples < 120 or average <= 40.0),
            "steady_partial_measured": bool(samples < 120 or steadysamples >= 120),
            "steady_partial_p95_within_67ms": bool(samples < 120 or steadyp95 <= 67.0),
            "lifecycle_p95_within_150ms": bool(samples < 120 or percentile95 <= 150.0),
            "maximum_spike_within_350ms": bool(samples < 120 or maximum <= 350.0),
            "steady_partial_p95_refresh_bound": bool(samples < 120 or steadyp95 <= max(25.0, framebudget * 1.5)),
            "lifecycle_p95_refresh_bound": bool(samples < 120 or percentile95 <= max(25.0, framebudget * 1.5)),
            "maximum_spike_refresh_bound": bool(samples < 120 or maximum <= max(100.0, framebudget * 6.0)),
            "missed_frames_within_10_percent": bool(samples < 120 or missedpercent <= 10.0),
            "page_flip_average_refresh_bound": bool(samples < 120 or pageflipaverage <= framebudget * 1.25),
            "presentation_rate_refresh_bound": bool(
                presentationsamples < 120
                or presentedfps >= targetfps * 0.90
            ),
            "presentation_p95_refresh_bound": bool(
                presentationsamples < 120
                or presentationp95 <= framebudget * 1.25
            ),
            "input_p95_within_25ms": bool(inputsamples == 0 or inputp95value <= 25.0),
            "input_maximum_within_75ms": bool(inputsamples == 0 or inputmaximum <= 75.0),
            "no_failed_frames": int(metrics.get("failed_frames", 0)) == 0,
            "no_gpu_fallbacks": int(metrics.get("fallbacks", 0)) == 0 and not bool(GPUFAILED),
            "no_managed_command_errors": int(GPUCOMMANDERRORS) == 0,
            "texture_count_within_limit": int(metrics.get("texture_count", 0)) <= int(metrics.get("texture_limit", 0)),
            "texture_bytes_within_limit": int(metrics.get("texture_bytes", 0)) <= int(metrics.get("texture_byte_limit", 0)),
            "managed_only_windows": sum(1 for win in windows.values() if win.get("_managed_only", False)),
        }
        gates["passed"] = all(bool(value) for key, value in gates.items() if key != "managed_only_windows")
        state["performance_gates"] = gates
        path = os.path.join(STATEBASE, "graphics.json")

        with open(path, "w") as f:
            json.dump(state, f, sort_keys=True, separators=(",", ":"))

        now = time.monotonic()

        if now - LASTTELEMETRY >= 5.0:

            LASTTELEMETRY = now
            queuetelemetrywrite(TELEMETRYPATH, state)

        if LASTGRAPHICSSTATEERROR:
            graphicslog("> graphics state writing recovered")
            LASTGRAPHICSSTATEERROR = ""
            LASTGRAPHICSSTATEERRORAT = 0.0

    except Exception as e:

        detail = f"{type(e).__name__}: {e}"
        now = time.monotonic()

        if (
            detail != LASTGRAPHICSSTATEERROR
            or now - float(LASTGRAPHICSSTATEERRORAT) >= 30.0
        ):
            graphicslog(f"> graphics state write failed {detail}")
            LASTGRAPHICSSTATEERROR = detail
            LASTGRAPHICSSTATEERRORAT = now


def softwarewindowkey(path):

    try:
        key = os.path.normpath(str(path or "").strip())
    except Exception:
        return ""

    if not key or key == ".":
        return ""

    return key[:1024]


def loadwindowattributes():

    global WINDOWATTRIBUTES, WINDOWATTRIBUTESDIRTY

    WINDOWATTRIBUTES = {}
    WINDOWATTRIBUTESDIRTY = False

    try:

        with open(WINDOWATTRIBUTEPATH, "r", encoding="utf-8") as stream:
            payload = json.load(stream)

        if not isinstance(payload, dict):
            return

        software = payload.get("software", {})

        if not isinstance(software, dict):
            return

        for rawkey, rawattributes in software.items():

            key = softwarewindowkey(rawkey)

            if not key or not isinstance(rawattributes, dict):
                continue

            geometry = rawattributes.get("geometry")

            if not isinstance(geometry, (list, tuple)) or len(geometry) < 4:
                continue

            try:
                x, y, w, h = [int(value) for value in geometry[:4]]
            except Exception:
                continue

            if w < 1 or h < 1:
                continue

            try:
                updated = float(rawattributes.get("updated", 0.0))
            except Exception:
                updated = 0.0

            if not math.isfinite(updated):
                updated = 0.0

            snap = str(rawattributes.get("snap", ""))

            if snap not in ("left", "right"):
                snap = None

            WINDOWATTRIBUTES[key] = {
                "geometry": [x, y, w, h],
                "maximized": bool(rawattributes.get("maximized", False)),
                "snap": snap,
                "updated": updated,
            }

        if len(WINDOWATTRIBUTES) > 256:

            newest = sorted(
                WINDOWATTRIBUTES.items(),
                key=lambda item: float(item[1].get("updated", 0.0)),
                reverse=True,
            )[:256]
            WINDOWATTRIBUTES = dict(newest)

    except FileNotFoundError:
        pass

    except Exception as error:
        log(f"window attributes load failed {error}")


def savewindowattributes(force=False):

    global WINDOWATTRIBUTESDIRTY, WINDOWATTRIBUTESLASTSAVE

    if not WINDOWATTRIBUTESDIRTY:
        return True

    now = time.monotonic()

    if not force:

        if now - float(WINDOWATTRIBUTESDIRTYAT) < 0.35:
            return False

        if now - float(WINDOWATTRIBUTESLASTSAVE) < 1.0:
            return False

    WINDOWATTRIBUTESLASTSAVE = now
    temporary = f"{WINDOWATTRIBUTEPATH}.{os.getpid()}.new"

    try:

        os.makedirs(os.path.dirname(WINDOWATTRIBUTEPATH), exist_ok=True)

        payload = {
            "format": 1,
            "software": WINDOWATTRIBUTES,
        }

        with open(temporary, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, sort_keys=True, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())

        os.replace(temporary, WINDOWATTRIBUTEPATH)
        WINDOWATTRIBUTESDIRTY = False
        return True

    except Exception as error:

        try:
            if os.path.exists(temporary):
                os.unlink(temporary)
        except Exception:
            pass

        log(f"window attributes save failed {error}")
        return False


def persistentwindowattributes(path):

    key = softwarewindowkey(path)

    if not key:
        return None

    attributes = WINDOWATTRIBUTES.get(key)

    if not isinstance(attributes, dict):
        return None

    return dict(attributes)


def persistedwindowplacement(attributes, decoration, requestedsize=None):

    if not isinstance(attributes, dict):
        return None

    geometry = attributes.get("geometry")

    if not isinstance(geometry, (list, tuple)) or len(geometry) < 4:
        return None

    try:
        x, y, w, h = [int(value) for value in geometry[:4]]
    except Exception:
        return None

    # A client can keep its saved position while supplying a launch-specific
    # size. In that case the saved maximized/snap state must not override it.
    if isinstance(requestedsize, (list, tuple)) and len(requestedsize) >= 2:

        try:
            w, h = [int(value) for value in requestedsize[:2]]
        except Exception:
            return None

    draft = {
        "role": "window",
        "decoration": str(decoration),
    }
    insetleft, insettop, insetright, insetbottom = windowframeinsets(draft)
    maxw = max(1, int(WORKW) - insetleft - insetright)
    maxh = max(1, int(WORKH) - insettop - insetbottom)
    w = max(1, min(w, maxw))
    h = max(1, min(h, maxh))
    minx = int(WORKX) + insetleft
    miny = int(WORKY) + insettop
    maxx = int(WORKX) + int(WORKW) - insetright - w
    maxy = int(WORKY) + int(WORKH) - insetbottom - h
    x = max(minx, min(maxx, x))
    y = max(miny, min(maxy, y))
    restore = [x, y, w, h]
    maximized = (
        bool(attributes.get("maximized", False))
        and requestedsize is None
    )
    snap = str(attributes.get("snap", ""))

    if snap not in ("left", "right"):
        snap = None

    if maximized:

        if snap in ("left", "right"):
            half = int(WORKW) // 2
            x = int(WORKX) + insetleft

            if snap == "right":
                x += half

            y = int(WORKY) + insettop
            w = max(1, half - insetleft - insetright)
            h = max(1, int(WORKH) - insettop - insetbottom)

        else:
            x = int(WORKX) + insetleft
            y = int(WORKY) + insettop
            w = max(1, int(WORKW) - insetleft - insetright)
            h = max(1, int(WORKH) - insettop - insetbottom)

    return {
        "geometry": [x, y, w, h],
        "restore": restore,
        "maximized": maximized,
        "snap": snap if maximized else None,
    }


def recordwindowattributes(win):

    global WINDOWATTRIBUTESDIRTY, WINDOWATTRIBUTESDIRTYAT

    try:

        if (
            not win
            or str(win.get("role", "")) != "window"
            or modalwindow(win)
        ):
            return False

        key = softwarewindowkey(win.get("path", ""))

        if not key:
            return False

        maximized = bool(win.get("_max", False))
        snap = win.get("_snap") if maximized else None
        geometry = win.get("_restore") if maximized else None

        if isfullscreen(win):
            fullscreenrestore = win.get("_fullscreen_restore")

            if isinstance(fullscreenrestore, dict):
                maximized = bool(fullscreenrestore.get("max", False))
                snap = fullscreenrestore.get("snap") if maximized else None
                geometry = fullscreenrestore.get("geometry")

                if maximized:
                    restore = fullscreenrestore.get("restore")

                    if isinstance(restore, (list, tuple)) and len(restore) >= 4:
                        geometry = restore

        if not isinstance(geometry, (list, tuple)) or len(geometry) < 4:
            geometry = [win["x"], win["y"], win["w"], win["h"]]

        x, y, w, h = [int(value) for value in geometry[:4]]
        attributes = {
            "geometry": [x, y, max(1, w), max(1, h)],
            "maximized": maximized,
            "snap": snap if snap in ("left", "right") else None,
            "updated": time.time(),
        }

        previous = WINDOWATTRIBUTES.get(key)

        if isinstance(previous, dict):

            if (
                previous.get("geometry") == attributes["geometry"]
                and bool(previous.get("maximized", False))
                == attributes["maximized"]
                and previous.get("snap") == attributes["snap"]
            ):
                return False

        WINDOWATTRIBUTES[key] = attributes

        if len(WINDOWATTRIBUTES) > 256:
            oldest = min(
                WINDOWATTRIBUTES,
                key=lambda item: float(
                    WINDOWATTRIBUTES.get(item, {}).get("updated", 0.0)
                ),
            )

            WINDOWATTRIBUTES.pop(oldest, None)

        WINDOWATTRIBUTESDIRTY = True
        WINDOWATTRIBUTESDIRTYAT = time.monotonic()
        return True

    except Exception as error:
        log(f"window attributes update failed {error}")
        return False


def lastsoftwarewindow(wid):

    win = windows.get(wid)

    if not win:
        return False

    key = softwarewindowkey(win.get("path", ""))

    if not key:
        return False

    for otherwid, other in windows.items():

        if int(otherwid) == int(wid):
            continue

        if (
            str(other.get("role", "")) == "window"
            and not modalwindow(other)
            and softwarewindowkey(other.get("path", "")) == key
        ):
            return False

    return True


def loadsettings():

    cfg = {
        "fb_enabled": True,
        "graphics_backend": "auto",
        "desktop_pin": True,
        "cursor_enabled": True,
        "boot_cursor_hide": True,
        "frame_interval_ms": 16,
        "max_rects": 32,
        "log_ops": False,
        "taskbar_height": 44,
        "gpu_compositor": True,
        "gpu_shadows": True,
        "gpu_transitions": True,
        "gpu_occlusion_culling": True,
        "gpu_transition_ms": 140,
        "gpu_shadow_radius": 18,
        "gpu_shadow_opacity": 0.35,
        "gpu_blur": True,
        "gpu_blur_radius": 12,
        "gpu_glyph_prewarm": True,
        "graphics_theme": "classic",
        "ui_scale": 1.0
    }

    path = os.path.join(SETTINGS, "config.json")

    if os.path.exists(path):

        with open(path, "r") as f:
            raw = f.read()

        usercfg = json.loads(raw)

        cfg.update(usercfg)

    try:
        with open(DISPLAYSETTINGS, 'r', encoding='utf-8') as stream:
            displaysettings = json.load(stream)
        cfg['ui_scale'] = max(
            0.5, min(3.0, float(displaysettings.get('ui_scale', 1.0))))
    except Exception:
        pass

    try:

        commandline = open("/the one/drivers/processes/cmdline", "r").read().split()

        if str(os.environ.get("T1OS_GRAPHICS", "")).strip().lower() == "cpu" or "t1os.graphics=cpu" in commandline:
            cfg["gpu_compositor"] = False
            cfg["graphics_backend"] = "framebuffer"

    except Exception:

        if str(os.environ.get("T1OS_GRAPHICS", "")).strip().lower() == "cpu":
            cfg["gpu_compositor"] = False
            cfg["graphics_backend"] = "framebuffer"

    return cfg


def setworkarea(cfg):


    global WORKX, WORKY, WORKW, WORKH

    left = int(cfg.get("work_left", 0))

    top = int(cfg.get("work_top", 0))

    right = int(cfg.get("work_right", 0))

    bottom = int(cfg.get("taskbar_height", 44))

    if left < 0: left = 0

    if top < 0: top = 0

    if right < 0: right = 0

    if bottom < 0: bottom = 0

    w = SCREENW - left - right

    h = SCREENH - top - bottom

    if w < 100: w = SCREENW

    if h < 100: h = SCREENH

    WORKX = left

    WORKY = top

    WORKW = w

    WORKH = h

def logopen():

    global STARTLOGFD

    if not DEBUGWINDOWSERVER:
        return

    try:

        # ensure parent tier exists
        os.makedirs("/the one/logs", exist_ok=True)

    except PermissionError:

        # permission denied creating logs directory
        print(formatlog('window server', 'permission denied creating logs directory'))
        return False

    except Exception as e:

        # other error creating logs directory
        print(formatlog('window server', f'error creating logs directory {e}'))
        return False

    try:

        # open or create the startup log file
        STARTLOGFD = open(LOGFILE, "a")

        # ensure file opened
        if not STARTLOGFD:
            log("could not open window server log file")
            return False

    except PermissionError:

        # permission denied opening log file
        print(formatlog('window server', 'permission denied opening window server log file'))
        return False

    except Exception as e:

        # opening log file error
        print(formatlog('window server', f'error opening startup log file {e}'))
        return False


def log(msg):

    if not DEBUGWINDOWSERVER:
        return

    global STARTLOGFD
    if STARTLOGFD is None:
        ok = logopen()
        if not ok:
            return

    try:

        # normalize message
        text = str(msg)

        # write log line
        STARTLOGFD.write(formatlog('window server', text) + '\n')

        # flush python buffer
        STARTLOGFD.flush()

        # flush OS buffer
        os.fsync(STARTLOGFD.fileno())

    except PermissionError:

        # permission denied writing log file
        print(formatlog('window server', 'permission denied writing window server log file'))

    except Exception as e:

        # writing log file error
        print(formatlog('window server', f'error writing window server log file {e}'))


def bootactive():


    for wid in reversed(zorder):


        if wid not in windows:
            continue

        win = windows[wid]

        if not win.get("mapped"):
            continue

        role = str(win.get("role", ""))

        if role in (
            "boot",
            "splash",
            "boot animation",
            "bootanimation",
            "boot_animation",
            "system animation",
        ):

            return True

    return False


def lockscreenactive():


    for wid in reversed(zorder):


        if wid not in windows:
            continue

        win = windows[wid]

        if not win.get("mapped"):
            continue

        role = str(win.get("role", ""))

        if role == "lockscreen":

            return True

    return False


def sessionlockactive():

    global LOCKSCREENPID, LOCKSESSIONPROCESS, LOCKSCREENIDENTITY

    process = LOCKSESSIONPROCESS

    if process is None:
        # Operations owns broker-launched lock helpers, so WindowServer has no
        # Popen handle. The pidfd/start-generation/domain identity captured
        # directly from procfs is the authoritative liveness object.
        if processidentitycurrent(LOCKSCREENIDENTITY):
            return True
        if LOCKSCREENIDENTITY is not None:
            log(f"session lock helper identity ended pid={LOCKSCREENPID}")
        LOCKSCREENPID = None
        closeprocessidentity(LOCKSCREENIDENTITY)
        LOCKSCREENIDENTITY = None
        return False

    try:
        status = process.poll()
    except Exception:
        # Losing the ability to query a process is not proof that the
        # authentication owner has stopped.
        return True

    if status is None:
        return True

    log(
        f"session lock helper exited pid={LOCKSCREENPID} "
        f"status={status} locked={SESSIONLOCKED}"
    )
    LOCKSESSIONPROCESS = None
    LOCKSCREENPID = None
    closeprocessidentity(LOCKSCREENIDENTITY)
    LOCKSCREENIDENTITY = None
    return False


def sessionlockvisible():

    for wid in reversed(zorder):

        if wid not in windows:
            continue

        win = windows[wid]

        if not win.get("mapped"):
            continue

        if str(win.get("role", "")) in ("lockscreen", "startup"):
            return True

    return False


def startupactive():


    for wid in reversed(zorder):


        if wid not in windows:
            continue

        win = windows[wid]

        if not win.get("mapped"):
            continue

        role = str(win.get("role", ""))

        if role == "startup":

            return True

    return False


def winshortcutsallowed():


    if SESSIONLOCKED:
        return False

    if bootactive():
        return False

    if lockscreenactive():
        return False

    if startupactive():
        return False

    return True


def squarerootscale():

    basew = 1920

    baseh = 1080

    if SCREENW <= 0 or SCREENH <= 0:
        return 1.0

    bdiag = (float(basew) * float(basew) + float(baseh) * float(baseh)) ** 0.5

    sdiag = (float(SCREENW) * float(SCREENW) + float(SCREENH) * float(SCREENH)) ** 0.5

    if bdiag <= 0.0 or sdiag <= 0.0:
        return 1.0

    ratio = sdiag / bdiag

    if ratio <= 0.0:
        return 1.0

    return (ratio ** 0.5) * max(0.5, min(3.0, float(GPUUISCALE)))


def scalesize(value):

    s = squarerootscale()

    out = int(round(float(value) * s))

    if out < 1:
        out = 1

    return out


def graphicswindowthemename(win=None):

    name = str((win or {}).get("theme", GRAPHICSTHEME)).lower()
    return name if name in GRAPHICSTHEMES else "classic"


def graphicswindowtheme(win=None):

    return GRAPHICSTHEMES[graphicswindowthemename(win)]


def clientchromemode(win):

    try:
        return str(win.get("role", "")) == "window" and str(win.get("decoration", "server")) == "client"
    except Exception:
        return False


def isfullscreen(win):

    try:
        return bool(win.get("_fullscreen", False))
    except Exception:
        return False


def clientchromecontrols(win):

    try:
        style = str(win.get("client_chrome_controls", "default")).lower()
        path = str(win.get("path", ""))

        if clientchromemode(win) and style == "chromium" and path == "/the one/build/chromium/chromium.py":
            return "chromium"

    except Exception:
        pass

    return "default"


def windowcontrolcolors(win):

    colors = dict(graphicswindowtheme(win))

    if clientchromecontrols(win) == "chromium":
        blue = (0x46, 0x88, 0xF4)
        colors["close"] = blue
        colors["max"] = blue
        colors["min"] = blue

    return colors


def clientchromeheight(win):

    try:
        height = int(win.get("client_chrome_height", TITLEH))
    except Exception:
        height = int(TITLEH)

    return max(BTNWH, min(max(1, int(win.get("h", height))), height))


def windowframeinsets(win):

    if str(win.get("role", "")) != "window" or clientchromemode(win) or isfullscreen(win):
        return 0, 0, 0, 0

    return FRAMEW, TITLEH + FRAMEW, FRAMEW, FRAMEW


def windowbuttonrects(win):

    if clientchromemode(win):
        gx, gy, gw, _ = windowgeo(win)
        # Keep client-rendered chrome controls at the same top-right offsets as
        # server-rendered controls.  Chromium's toolbar is taller than TITLEH,
        # but that extra height belongs to its content and drag region; using it
        # to lay out the controls shifts them down and spreads them apart.
        return buttonrects(gx, gy, gw)

    gx, gy, gw, _ = windowgeo(win)
    fx = gx - FRAMEW
    fy = gy - (TITLEH + FRAMEW)
    fw = gw + FRAMEW * 2
    return buttonrects(fx, fy, fw)


def windowbuttonhoverrects(win):

    if clientchromecontrols(win) == "chromium":
        return {}

    gx, gy, _, _ = windowgeo(win)
    close_x, close_y, max_x, max_y, min_x, min_y = windowbuttonrects(win)

    if clientchromemode(win):
        chrome_y = gy
        chrome_h = clientchromeheight(win)
    else:
        chrome_y = gy - TITLEH
        chrome_h = TITLEH

    chrome_h = max(1, int(chrome_h))

    def hoverrect(button_x):

        center_x = int(button_x) + BTNWH // 2
        return center_x - chrome_h // 2, int(chrome_y), chrome_h, chrome_h

    rects = {
        "close": hoverrect(close_x),
    }

    if not win.get("standard_dialog") and not win.get("modal_child"):
        rects["max"] = hoverrect(max_x)
        rects["min"] = hoverrect(min_x)

    return rects


def windowbuttonhoverarea(win):

    try:
        if HOVERBUTTON and int(HOVERBUTTON[0]) == int(win.get("id", 0)):
            area = str(HOVERBUTTON[1])

            if area in windowbuttonhoverrects(win):
                return area
    except Exception:
        pass

    return None


def windowbuttonhoverat(x, y):

    wid = topmostwindowat(int(x), int(y))

    if wid not in windows:
        return None

    win = windows[wid]

    if (
        win.get("role") != "window"
        or isfullscreen(win)
        or clientchromecontrols(win) == "chromium"
    ):
        return None

    matches = []

    for area, rect in windowbuttonhoverrects(win).items():
        rx, ry, rw, rh = rect

        if rx <= x < rx + rw and ry <= y < ry + rh:
            center = rx + rw / 2.0
            matches.append((abs(float(x) - center), area))

    if not matches:
        return None

    matches.sort(key=lambda value: value[0])
    return int(wid), matches[0][1]


def setwindowbuttonhover(value):

    global HOVERBUTTON

    if value == HOVERBUTTON:
        return

    old = HOVERBUTTON
    HOVERBUTTON = value

    for state in (old, value):
        if not state:
            continue

        wid, area = state

        if wid not in windows:
            continue

        win = windows[wid]

        if GPUCOMPOSITOR:
            DAMAGERECTS.append(gpuvisualrect(win))
            continue

        rect = windowbuttonhoverrects(win).get(area)

        if rect is not None:
            DAMAGERECTS.append(list(rect))


def updatewindowbuttonhover(x, y):

    setwindowbuttonhover(windowbuttonhoverat(x, y))


def clientdragrect(win):

    if not clientchromemode(win):
        return None

    try:
        width = max(0, int(win.get("client_chrome_drag_width", 0)))
    except Exception:
        width = 0

    if width < 1:
        return None

    _, _, _, _, min_x, _ = windowbuttonrects(win)
    gx, gy, _, _ = windowgeo(win)
    right = min_x - BTNGAP
    left = max(gx, right - width)
    return left, gy, max(0, right - left), clientchromeheight(win)


def applyuiscale():

    global FRAMEW, TITLEH, BTNWH, BTNGAP, PLACEDELTA, SNAPTOP, SNAPSIDE, HITEDGE, HITCORNER

    FRAMEW = scalesize(BASEFRAMEW)

    BTNWH = scalesize(BASEBTNWH)

    BTNGAP = scalesize(BASEBTNGAP)

    TITLEH = scalesize(BASETITLEH)

    PLACEDELTA = scalesize(BASEPLACEDELTA)

    SNAPTOP = scalesize(BASESNAPTOP)

    SNAPSIDE = scalesize(BASESNAPSIDE)

    HITEDGE = scalesize(BASEHITEDGE)

    HITCORNER = scalesize(BASEHITCORNER)

    if FRAMEW < 1:
        FRAMEW = 1

    if BTNWH < 8:
        BTNWH = 8

    if BTNGAP < 1:
        BTNGAP = 1

    if TITLEH < (BTNWH + BTNGAP * 2):

        TITLEH = (BTNWH + BTNGAP * 2)


# placement functions
def rectsoverlap(ax, ay, aw, ah, bx, by, bw, bh):

    try:

        ax2 = ax + aw

        ay2 = ay + ah

        bx2 = bx + bw

        by2 = by + bh

        if ax2 <= bx:
            return False

        if bx2 <= ax:
            return False

        if ay2 <= by:
            return False

        if by2 <= ay:
            return False

        return True

    except Exception:

        return False


def wantautoplace(req):

    try:

        x = int(req.get("x", 0))

        y = int(req.get("y", 0))

        if x == 0 and y == 0:
            return True

    except Exception:
        return True

    return False


def overlapswindow(x, y, w, h):

    for wid in zorder:

        if wid not in windows:
            continue

        win = windows[wid]

        if not win.get("mapped"):
            continue

        if str(win.get("role", "")) != "window":
            continue

        if rectsoverlap(x, y, w, h, int(win["x"]), int(win["y"]), int(win["w"]), int(win["h"])):
            return True

    return False


def nextplace(w, h):

    global PLACEX, PLACEY

    try:

        if PLACEX == 0 and PLACEY == 0:

            PLACEX = WORKX + 40

            PLACEY = WORKY + 60

        x = int(PLACEX)

        y = int(PLACEY)

        # wrap if we would exceed work area
        if x + w > WORKX + WORKW:

            x = WORKX + 40

            y = y + PLACEDELTA

        if y + h > WORKY + WORKH:
            x = WORKX + 40

            y = WORKY + 60

        # advance for next time
        PLACEX = x + PLACEDELTA

        PLACEY = y + PLACEDELTA

        return x, y

    except Exception:

        return WORKX + 40, WORKY + 60


def ensuresrestore(win):

    if not win.get("_restore"):

        win["_restore"] = [win["x"], win["y"], win["w"], win["h"]]


# snapping functions
def snapkind(x, y):

    try:

        px = int(x)

        py = int(y)

    except Exception:

        return None

    try:

        # side snaps first so top doesn't steal near-corner snaps
        if px <= WORKX + SNAPSIDE:
            return "left"

        if px >= (WORKX + WORKW) - SNAPSIDE:
            return "right"

        if py <= WORKY + SNAPTOP:
            return "max"

    except Exception:

        return None

    return None


def snapapply(wid, kind):

    if wid not in windows:
        return

    win = windows[wid]

    role = str(win.get("role", ""))

    if role not in "window":
        return

    ensuresrestore(win)

    insetleft, insettop, insetright, insetbottom = windowframeinsets(win)

    if kind == "max":

        nx = WORKX + insetleft

        ny = WORKY + insettop

        nw = WORKW - insetleft - insetright

        nh = WORKH - insettop - insetbottom

        if nw < 1: nw = 1

        if nh < 1: nh = 1

        resizewindow(win["cid"], {"winid": wid, "w": nw, "h": nh})

        movewindow(win["cid"], {"winid": wid, "x": nx, "y": ny})

        win["_max"] = True

        win["_snap"] = None

        recordwindowattributes(win)

        return

    if kind in ("left", "right"):

        half = WORKW // 2

        nx = WORKX + insetleft

        if kind == "right":
            nx = WORKX + half + insetleft

        ny = WORKY + insettop

        nw = half - insetleft - insetright

        nh = WORKH - insettop - insetbottom

        if nw < 1: nw = 1

        if nh < 1: nh = 1

        resizewindow(win["cid"], {"winid": wid, "w": nw, "h": nh})

        movewindow(win["cid"], {"winid": wid, "x": nx, "y": ny})

        win["_max"] = True

        win["_snap"] = kind

        recordwindowattributes(win)

        return


def unsnapdrag(wid, mx, my):

    if wid not in windows:
        return

    win = windows[wid]

    if not win.get("_max"):
        return

    if "_restore" not in win:
        return

    rx, ry, rw, rh = win["_restore"]

    rw = int(rw)

    rh = int(rh)

    # keep grab point proportional across restore width
    try:

        denom = int(win["w"])

        if denom < 1:
            denom = 1

        ratio = (int(mx) - int(win["x"])) / float(denom)

    except Exception:

        ratio = 0.5

    if ratio < 0.0:
        ratio = 0.0

    if ratio > 1.0:
        ratio = 1.0

    ox = int(rw * ratio)

    nx = int(mx) - ox

    # Keep the pointer in the server titlebar or the client's declared drag strip.
    if clientchromemode(win):
        ny = int(my) - (clientchromeheight(win) // 2)
    else:
        ny = int(my) + (TITLEH // 2)

    # clamp to work area so it doesn't spawn off-screen
    if nx < WORKX: nx = WORKX

    if ny < WORKY: ny = WORKY

    if nx + rw > WORKX + WORKW:
        nx = (WORKX + WORKW) - rw

    if ny + rh > WORKY + WORKH:
        ny = (WORKY + WORKH) - rh

    resizewindow(win["cid"], {"winid": wid, "w": rw, "h": rh})

    movewindow(win["cid"], {"winid": wid, "x": nx, "y": ny})

    win["_max"] = False

    win["_snap"] = None

    recordwindowattributes(win)


def snappreviewrect(kind):

    try:

        if not kind:
            return None

        if kind == "max":

            nx = WORKX + FRAMEW

            ny = WORKY + TITLEH + FRAMEW

            nw = WORKW - (FRAMEW * 2)

            nh = WORKH - TITLEH - (FRAMEW * 2)

        elif kind in ("left", "right"):

            half = WORKW // 2

            nx = WORKX + FRAMEW

            if kind == "right":
                nx = WORKX + half + FRAMEW

            ny = WORKY + TITLEH + FRAMEW

            nw = half - (FRAMEW * 2)

            nh = WORKH - TITLEH - (FRAMEW * 2)

        else:

            return None

        if nw < 1: nw = 1

        if nh < 1: nh = 1

        fx = nx - FRAMEW

        fy = ny - (TITLEH + FRAMEW)

        fw = nw + (FRAMEW * 2)

        fh = nh + TITLEH + (FRAMEW * 2)

        if fw < 1: fw = 1

        if fh < 1: fh = 1

        return (int(fx), int(fy), int(fw), int(fh))

    except Exception:

        return None


def setsnappreview(rect):

    global SNAPPREVIEW

    try:

        old = SNAPPREVIEW

        SNAPPREVIEW = rect

        if old and len(old) == 4:
            DAMAGERECTS.append([int(old[0]), int(old[1]), int(old[2]), int(old[3])])

        if rect and len(rect) == 4:
            DAMAGERECTS.append([int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3])])

    except Exception:

        SNAPPREVIEW = rect


# operation functions
def operationssend(request):

    try:

        # create unix domain socket
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

    except Exception as e:

        # socket create error
        log(f"operations send socket create error {e}")
        return None

    try:

        # connect to operations server socket
        sock.connect('/.ephemeral/operations/control.sock')

    except FileNotFoundError:

        # server socket not found
        log(f"operations server socket not found")

        sock.close()
        return None

    except PermissionError:

        # permission denied connecting socket
        log(f"operations server socket permission denied")

        sock.close()
        return None

    except Exception as e:

        # socket connect error
        log(f"operations send socket connect error {e}")

        sock.close()
        return None

    try:

        # encode request as json line
        text = json.dumps(request)
        data = text.encode('utf-8') + b'\n'

        # send request
        sock.sendall(data)

    except Exception as e:

        # send error
        log(f"operations send send error {e}")

        sock.close()
        return None

    try:

        # read single response line
        fileobj = sock.makefile('rb')
        line = fileobj.readline()
        fileobj.close()

    except Exception as e:

        # receive error
        log(f"operations send receive error {e}")

        sock.close()
        return None


    # close socket
    sock.close()

    if not line:
        return None

    try:

        # decode response text
        text = line.decode('utf-8', errors='replace').strip()

        # parse json response
        response = json.loads(text)

        return response

    except Exception as e:

        # response parse error
        log(f"operations send response parse error {e}")
        return None


def operationsregisterpid(pid, name, script, logpath, user, mode, state="running"):

    try:

        # convert pid to int
        ipid = int(pid)

    except Exception:

        # invalid pid format
        log(f"operations registerpid invalid pid {pid}")
        return None

    try:

        # build register request payload
        request = {}

        # operation code
        request['op'] = 'REGISTER_PID'

        # pid and metadata
        request['pid'] = ipid
        request['name'] = name if name else 'operation'
        request['script'] = script if script else '-'
        request['log'] = logpath if logpath else '-'

        # user (master / architect from settings)
        request['user'] = user if user else 'master'

        # mode (front / behind)
        request['mode'] = mode if mode else 'behind'
        request['state'] = 'starting' if str(state).strip().lower() == 'starting' else 'running'

    except Exception as e:

        # prepare error
        log(f"operations registerpid prepare error {e}")
        return None

    # send to operations server
    response = operationssend(request)

    if response is None:
        return None

    try:

        status = response.get('status', None)

        if status != 'ok':

            message = response.get('message', 'unknown error')
            log(f"operations server register error {message}")
            return None

        rp = response.get('pid', None)

        return rp

    except Exception as e:

        # response handling error
        log(f"operations registerpid response error {e}")
        return None


def operationsreadypid(pid):

    try:
        ipid = int(pid)
    except Exception:
        return None

    if ipid <= 0:
        return None

    response = operationssend({'op': 'READY_PID', 'pid': ipid})

    if not isinstance(response, dict) or response.get('status') != 'ok':
        return None

    return ipid


def operationskill(pid):

    try:

        ipid = int(pid)

    except Exception:

        # invalid pid format
        log(f"operations kill invalid pid {pid}")
        return False

    try:

        # build kill request
        request = {}
        request['op'] = 'KILL'
        request['pid'] = ipid

    except Exception as e:

        # prepare error
        log(f"operations kill prepare error {e}")
        return False

    # send to operations server
    response = operationssend(request)

    if response is None:
        return False

    try:

        status = response.get('status', None)

        if status != 'ok':
            message = response.get('message', 'unknown error')
            log(f"operations server kill error {message}")
            return False

        return True

    except Exception as e:

        # response handling error
        log(f"operations kill response error {e}")
        return False


def openarray():

    global ARRAYPID, ARRAYLAST

    try:

        now = time.time()

    except Exception:

        now = 0.0

    # simple cooldown so win+e spam doesn't fork-bomb
    if now - float(ARRAYLAST) < float(ARRAYCOOLDOWN):
        return

    ARRAYLAST = now

    try:

        # launch array via trusted python
        arraypath = "/the one/build/array/array.py"
        arraylog = softwarelogpath(arraypath)
        p = popenisolated(
            [arraypath],
            softwarepath=arraypath,
            logpath=arraylog,
            security_profile="desktop",
            preexec_fn=dropdesktopidentity,
        )

        ARRAYPID = int(p.pid)

    except Exception as e:

        log(f"openarray launch error {e}")
        return

    user = "session"

    # register with operations server if available (non-fatal)
    operationsregisterpid(
        ARRAYPID,
        "array",
        arraypath,
        arraylog,
        user,
        "front",
        "starting",
    )


def takescreenshot():

    try:
        now = time.time()
        localtime = currenttime(now)
        date = formatatreyandate(localtime).replace(":", "-")
        stamp = f"{date} {time.strftime('%H.%M.%S', localtime)}"
        milliseconds = int((now - int(now)) * 1000.0)
        capturetoken = f"{random.getrandbits(128):032x}"
        filename = f"Screenshot {stamp}.{milliseconds:03d}-{capturetoken}.png"
        path = os.path.join(SCREENSHOTBASE, filename)
        suffix = 2

        while os.path.exists(path):
            path = os.path.join(
                SCREENSHOTBASE,
                f"Screenshot {stamp}.{milliseconds:03d}-{capturetoken} ({suffix}).png",
            )
            suffix += 1

        screenshotpng(path)
        os.chown(path, -1, SESSIONGID)
        os.chmod(path, 0o640)
        payload = {
            "mode": "copy",
            "paths": [path],
            "source": "windowserver:screenshot",
            "ts": int(now * 1000.0),
        }
        ok, response = exsetfiles(payload, source="windowserver:screenshot")

        if not ok:

            try:
                os.unlink(path)
            except OSError:
                pass

            raise RuntimeError(response.get("error", "exchange rejected screenshot"))

        # The Exchange clipboard points to the newest source. Keep a small
        # history so a copy already queued by Array cannot lose its input.
        captures = []

        for name in os.listdir(SCREENSHOTBASE):
            candidate = os.path.join(SCREENSHOTBASE, name)

            if name.lower().endswith(".png") and os.path.isfile(candidate):
                captures.append((os.path.getmtime(candidate), candidate))

        captures.sort(reverse=True)

        for _modified, candidate in captures[16:]:

            try:
                os.unlink(candidate)
            except OSError:
                pass

        log(f"screenshot copied to Exchange clipboard {path}")
        return True

    except Exception as error:
        log(f"screenshot capture error {error}")
        return False


def snapcapture(cid, req):

    """Capture the composed display for the trusted Snap selection client."""

    requestid = str(req.get("request_id", ""))[:128]

    try:
        parent = int(req.get("parent", 0))
    except Exception:
        parent = 0

    try:
        parentwin = windows.get(parent)

        if (
            not requestid
            or not clienthascapability(cid, "screen_capture")
            or not parentwin
            or parentwin.get("cid") != cid
            or str(parentwin.get("role", "")) != "window"
        ):
            raise PermissionError("Snap capture is restricted to its owning application window")

        if parentwin.get("mapped"):
            raise RuntimeError("Snap must hide its application window before capture")

        if SESSIONLOCKED or any(
            win.get("mapped") and str(win.get("role", "")) in ("lockscreen", "startup")
            for win in windows.values()
        ):
            raise PermissionError("screen capture is unavailable while the session is locked")

        now = time.time()
        localtime = currenttime(now)
        date = formatatreyandate(localtime).replace(":", "-")
        stamp = f"{date} {time.strftime('%H.%M.%S', localtime)}"
        milliseconds = int((now - int(now)) * 1000.0)
        capturetoken = f"{random.getrandbits(128):032x}"
        filename = f"Snap Capture {stamp}.{milliseconds:03d}-{capturetoken}.png"
        path = os.path.join(SCREENSHOTBASE, filename)
        suffix = 2

        while os.path.exists(path):
            path = os.path.join(
                SCREENSHOTBASE,
                f"Snap Capture {stamp}.{milliseconds:03d}-{capturetoken} ({suffix}).png",
            )
            suffix += 1

        captured = screenshotpng(path)
        os.chown(path, -1, SESSIONGID)
        os.chmod(path, 0o640)
        selectable = []

        # Keep back-to-front compositor order. Snap walks this list in reverse
        # so window mode always resolves the actually visible topmost window.
        for wid in list(zorder):
            win = windows.get(wid)

            if (
                not win
                or not win.get("mapped")
                or str(win.get("role", "")) != "window"
                or win.get("cid") == cid
            ):
                continue

            fx, fy, fw, fh = winframerect(win)
            left = max(0, int(fx))
            top = max(0, int(fy))
            right = min(int(SCREENW), int(fx) + int(fw))
            bottom = min(int(SCREENH), int(fy) + int(fh))

            if right <= left or bottom <= top:
                continue

            selectable.append({
                "winid": int(wid),
                "title": str(win.get("title", "window"))[:128],
                "rect": [left, top, right - left, bottom - top],
            })

        captures = []

        for name in os.listdir(SCREENSHOTBASE):
            candidate = os.path.join(SCREENSHOTBASE, name)

            if name.lower().endswith(".png") and os.path.isfile(candidate):
                captures.append((os.path.getmtime(candidate), candidate))

        captures.sort(reverse=True)

        for _modified, candidate in captures[32:]:
            try:
                os.unlink(candidate)
            except OSError:
                pass

        sendjson(cid, {
            "op": "SCREEN_CAPTURED",
            "request_id": requestid,
            "path": str(captured.get("path", path)),
            "width": int(captured.get("width", SCREENW)),
            "height": int(captured.get("height", SCREENH)),
            "windows": selectable,
        })
        log(
            f"Snap capture complete request={requestid} "
            f"size={captured.get('width')}x{captured.get('height')}"
        )
        return True

    except PermissionError as error:
        sendjson(cid, {
            "op": "SCREEN_CAPTURE_FAILED",
            "request_id": requestid,
            "code": "denied",
            "detail": str(error),
        })
        log(f"Snap capture denied cid={cid} request={requestid}: {error}")
        return False

    except Exception as error:
        sendjson(cid, {
            "op": "SCREEN_CAPTURE_FAILED",
            "request_id": requestid,
            "code": "capture_failed",
            "detail": str(error),
        })
        log(f"Snap capture error cid={cid} request={requestid}: {error}")
        return False


def openbrick():

    global BRICKPID, BRICKLAST

    try:

        now = time.time()

    except Exception:

        now = 0.0

    # simple cooldown so win+e spam doesn't fork-bomb
    if now - float(BRICKLAST) < float(BRICKCOOLDOWN):
        return

    BRICKLAST = now

    try:

        # launch brick via trusted python
        brickpath = "/the one/build/brick/brick.py"
        bricklog = softwarelogpath(brickpath)
        p = popenisolated(
            [brickpath],
            softwarepath=brickpath,
            logpath=bricklog,
            security_profile="brick",
            preexec_fn=dropdesktopidentity,
        )

        BRICKPID = int(p.pid)

    except Exception as e:

        log(f"openbrick launch error {e}")
        return

    user = "session"

    # register with operations server if available (non-fatal)
    operationsregisterpid(
        BRICKPID,
        "brick",
        brickpath,
        bricklog,
        user,
        "front",
        "starting",
    )


def openoperationscentre():

    global OPERATIONSCENTREPID, OPERATIONSCENTRELAST

    try:

        for wid, window in windows.items():

            if str(window.get("path", "")) != OPERATIONSCENTREPATH:
                continue

            cid = window.get("cid")
            identity = clients.get(cid, {}).get("identity")
            if (
                not processidentitycurrent(identity)
                or str(identity.get("domain", "")) != "desktop"
            ):
                continue

            if not window.get("mapped"):
                mapwindow(cid, {"winid": int(wid)})

            raisewindow(cid, {"winid": int(wid)})
            setfocus(int(wid))
            return

    except Exception as e:
        log(f"operations centre focus error {e}")

    try:
        now = time.time()
    except Exception:
        now = 0.0

    if now - float(OPERATIONSCENTRELAST) < float(OPERATIONSCENTRECOOLDOWN):
        return

    OPERATIONSCENTRELAST = now

    try:

        operationslog = softwarelogpath(
            OPERATIONSCENTREPATH,
            "/the one/logs/operationscentre.py.log",
        )
        process = popenisolated(
            [OPERATIONSCENTREPATH],
            softwarepath=OPERATIONSCENTREPATH,
            logpath=operationslog,
            security_profile="desktop",
            preexec_fn=dropdesktopidentity,
        )
        OPERATIONSCENTREPID = int(process.pid)

    except Exception as e:
        log(f"operations centre launch error {e}")
        return

    operationsregisterpid(
        OPERATIONSCENTREPID,
        "operations centre",
        OPERATIONSCENTREPATH,
        operationslog,
        "session",
        "front",
        "starting",
    )


def locksession():

    global LOCKSCREENPID, LOCKSCREENLAST, LOCKSESSIONPROCESS, SESSIONLOCKED
    global LOCKSCREENIDENTITY

    # The session helper remains alive across the lock-screen -> login
    # transition. Checking the process, rather than only the currently mapped
    # role, closes the gap in which a second Win+L used to start another lock.
    if SESSIONLOCKED or sessionlockactive() or lockscreenactive() or startupactive():
        return

    try:
        now = time.time()
    except Exception:
        now = 0.0

    if now - float(LOCKSCREENLAST) < float(LOCKSCREENCOOLDOWN):
        return

    LOCKSCREENLAST = now

    try:
        lockscreenlog = "/the one/logs/startup.py.log"
        response = operationssend({"action": "SESSION_LOCK_START"})
        if not isinstance(response, dict) or response.get("status") != "ok":
            raise RuntimeError("operations broker denied the session lock")
        LOCKSESSIONPROCESS = None
        LOCKSCREENPID = int(response.get("pid", 0))
        if LOCKSCREENPID < 2:
            raise RuntimeError("operations broker returned an invalid session lock")
        LOCKSCREENIDENTITY = waitforprocessidentity(
            LOCKSCREENPID, "lockscreen", timeout=1.0)
        if not LOCKSCREENIDENTITY:
            LOCKSESSIONPROCESS = None
            LOCKSCREENPID = None
            raise RuntimeError("could not capture session-lock process identity")
        brokeridentity = str(response.get("identity", ""))
        localidentity = (
            f"{LOCKSCREENPID}:"
            f"{int(LOCKSCREENIDENTITY.get('starttime', 0))}"
        )
        if brokeridentity != localidentity:
            closeprocessidentity(LOCKSCREENIDENTITY)
            LOCKSCREENIDENTITY = None
            LOCKSCREENPID = None
            raise RuntimeError("session-lock broker identity mismatch")
        SESSIONLOCKED = True
        clearclipboard()
        log(f"session lock launched pid={LOCKSCREENPID}")
    except Exception as e:
        log(f"lock session launch error {e}")
        return

    # Operations created and registered the exact Startup child itself.


# input functions
def disconnectinputserver(reason):

    global INPUTCONN, INPUTCID, INPUTINBUF, INPUTOUTBUF, INPUTIDENTITY

    connection = INPUTCONN
    INPUTCONN = None
    INPUTCID = None
    INPUTINBUF = b""
    INPUTOUTBUF = b""
    identity = INPUTIDENTITY
    INPUTIDENTITY = None

    if connection is not None:
        try:
            sel.unregister(connection)
        except Exception:
            pass
        try:
            connection.close()
        except Exception:
            pass

    closeprocessidentity(identity)
    log(f"inputserver disconnected ({reason})")


def connectinputserver(maxattempts=50):

    global INPUTCONN, INPUTCID, INPUTINBUF, INPUTOUTBUF, INPUTIDENTITY

    tries = 0

    while tries < max(1, int(maxattempts)):

        tries += 1


        # attempt note
        log(f"inputserver connect attempt {tries} path={INPUTSOCKPATH}")

        try:

            # create client socket
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

        except Exception as e:

            # socket create error
            log(f"inputserver socket create error {e}")
            return False

        try:

            info = os.lstat(INPUTSOCKPATH)
            if (
                not stat.S_ISSOCK(info.st_mode)
                or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) & 0o077
            ):
                raise PermissionError("unsafe inputserver socket metadata")

            # connect to inputserver
            s.connect(INPUTSOCKPATH)

        except FileNotFoundError:

            # socket not created yet (inputserver not up)
            log(f"inputserver socket not found at {INPUTSOCKPATH}")

            s.close()
            time.sleep(0.1)
            continue

        except ConnectionRefusedError:

            # listener not accepting yet
            log(f"inputserver connection refused at {INPUTSOCKPATH}")

            s.close()
            time.sleep(0.1)
            continue

        except PermissionError:

            # permission denied
            log(f"inputserver socket permission denied")

            s.close()
            return False

        except Exception as e:

            # connect error
            log(f"inputserver connect error {e}")

            s.close()
            time.sleep(0.1)
            continue

        identity = authenticateinputserverpeer(s)
        if not identity:
            log("inputserver peer identity rejected")
            s.close()
            return False

        try:

            # nonblocking + register in main selector
            s.setblocking(False)

            state = {
                "kind": "inputserver",
                "sock": s,
            }

            sel.register(s, selectors.EVENT_READ, data=state)

            INPUTCONN = s
            INPUTCID = 1
            INPUTINBUF = b""
            INPUTOUTBUF = b""
            INPUTIDENTITY = identity

        except Exception as e:

            # register error
            log(f"inputserver register error {e}")

            closeprocessidentity(identity)
            s.close()
            return False

        try:

            # subscribe to the event kinds we care about
            sendinputjson({"op": "HELLO"})

            # Establish the compositor coordinate space before subscribing.
            # Input Server publishes its current pointer as part of that
            # subscription, so the first state sample must already use the
            # real display bounds.
            sendinputjson({"op": "FB_SIZE", "w": int(SCREENW), "h": int(SCREENH)})

            sendinputjson({"op": "SUBSCRIBE", "types": ["pointer", "button", "scroll", "key", "text"]})

        except Exception as e:

            # subscribe queue error (still consider socket connected)
            log(f"inputserver subscribe queue error {e}")

        log(f"connected to inputserver at {INPUTSOCKPATH}")
        return True

    log(f"inputserver connect failed after {tries} attempts path={INPUTSOCKPATH}")
    return False


def cursorstartupsceneactive():

    # An accelerated candidate can be replaced after Startup has already
    # completed its visible handoff. The fresh CPU-KMS owner must release the
    # startup cursor latch when the authenticated desktop (or lock screen) is
    # its first mapped OS scene; requiring a role="startup" frame forever hides
    # an otherwise live pointer on that recovery path.
    for wid in reversed(zorder):

        if wid not in windows:
            continue

        win = windows[wid]

        if not win.get("mapped"):
            continue

        if str(win.get("role", "")) in (
                "startup", "lockscreen", "desktop", "taskbar"):
            return True

    return False


def maintaininputserver():

    global INPUTRECONNECTAT

    if INPUTCONN is not None:
        if processidentitycurrent(INPUTIDENTITY):
            return True
        disconnectinputserver("authenticated identity ended")

    now = time.monotonic()
    if now < float(INPUTRECONNECTAT):
        return False

    INPUTRECONNECTAT = now + 0.5
    return connectinputserver(maxattempts=1)


def sendinputjson(obj):

    global INPUTOUTBUF


    if INPUTCONN is None:
        return

    # encode newline delimited json
    line = (json.dumps(obj, separators=(",", ":")) + "\n").encode("utf-8")

    INPUTOUTBUF += line


    # ensure selector also watches write when we have pending output
    if INPUTCONN is not None and INPUTOUTBUF:

        st = {"kind": "inputserver", "sock": INPUTCONN}

        sel.modify(INPUTCONN, selectors.EVENT_READ | selectors.EVENT_WRITE, data=st)

def flushinputserver():

    global INPUTOUTBUF

    try:

        if INPUTCONN is None:
            return

        if not INPUTOUTBUF:
            return

        sent = INPUTCONN.send(INPUTOUTBUF)

        if sent > 0:
            INPUTOUTBUF = INPUTOUTBUF[sent:]

        # if fully drained, we no longer need write notifications
        if not INPUTOUTBUF:


            st = {"kind": "inputserver", "sock": INPUTCONN}
            sel.modify(INPUTCONN, selectors.EVENT_READ, data=st)

    except BlockingIOError:
        pass

    except Exception as e:

        log(f"inputserver flush error {e}")
        disconnectinputserver(f"flush error {e}")


def recvinputlines():

    global INPUTINBUF, INPUTBYTESDRAINED, INPUTDRAINCAPS
    global INPUTPOINTERCOALESCED

    out = []
    rawlines = []

    try:

        if INPUTCONN is None:
            return out

        if not processidentitycurrent(INPUTIDENTITY):
            disconnectinputserver("authenticated identity ended")
            return out

        received = 0

        while received < int(INPUTDRAINLIMIT):

            try:
                data = INPUTCONN.recv(
                    min(65536, int(INPUTDRAINLIMIT) - received)
                )
            except BlockingIOError:
                break

            if not data:

                # inputserver disconnected
                disconnectinputserver("peer closed")
                break

            INPUTINBUF += data
            received += len(data)

        INPUTBYTESDRAINED += int(received)

        if received >= int(INPUTDRAINLIMIT):
            INPUTDRAINCAPS += 1

        while True:

            idx = INPUTINBUF.find(b"\n")

            if idx == -1:
                break

            raw = INPUTINBUF[:idx]
            INPUTINBUF = INPUTINBUF[idx + 1:]
            txt = raw.decode("utf-8", errors="replace").strip()

            if txt:
                rawlines.append(txt)

    except BlockingIOError:
        pass

    except Exception as e:

        log(f"inputserver recv error {e}")

    # Pointer motion is state, not a loss-sensitive transition.  Collapse only
    # consecutive motion reports, flushing the newest position before every
    # key, button or scroll record so ordering remains exact.
    pendingpointer = None

    for txt in rawlines:

        pointer = False

        try:

            message = json.loads(txt)
            event = (
                message.get("ev")
                if str(message.get("op", "")) == "EVENT"
                and isinstance(message.get("ev"), dict)
                else message
            )
            pointer = str(event.get("kind", "")) == "pointer"

        except Exception:
            pointer = False

        if pointer:

            if pendingpointer is not None:
                INPUTPOINTERCOALESCED += 1

            pendingpointer = txt
            continue

        if pendingpointer is not None:
            out.append(pendingpointer)
            pendingpointer = None

        out.append(txt)

    if pendingpointer is not None:
        out.append(pendingpointer)

    return out


def audiopack(msgtype, payload):

    body = b""

    if payload is not None:

        try:

            body = json.dumps(payload).encode("utf-8")

        except Exception:

            body = b""

    header = struct.pack(
        ">4sBBHI",
        b"T1AU",
        1,
        int(msgtype) & 0xFF,
        0,
        len(body)
    )

    return header + body


def audiounpack(buf):

    if len(buf) < 12:

        return None, None, buf

    try:

        magic, proto, mtype, flags, length = struct.unpack(
            ">4sBBHI",
            buf[:12]
        )

    except Exception:

        return None, None, buf

    if magic != b"T1AU" or proto != 1:

        return None, None, buf

    if len(buf) < 12 + length:

        return None, None, buf

    payload = buf[12:12 + length]

    rest = buf[12 + length:]

    data = None

    if payload:

        try:

            data = json.loads(payload.decode("utf-8"))

        except Exception:

            data = None

    return int(mtype), data, rest


def audiosend(msgtype, payload):

    global AUDIOSOCKPATH

    s = None

    try:

        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

        s.connect(AUDIOSOCKPATH)

        s.sendall(audiopack(msgtype, payload))

        buf = b""

        while True:

            chunk = s.recv(4096)

            if not chunk:
                break

            buf += chunk

            rtype, rdata, rest = audiounpack(buf)

            if rtype is not None:

                return rtype, rdata

    except Exception:

        return None, None

    if s:

        try:

            s.close()

        except Exception:

            pass

    return None, None


def audiovolume(delta):

    global AUDIOGAIN, AUDIOSTEP

    # AUDIOGAIN is only a cache and starts at 1.0.  Read the authoritative
    # service value before applying a media-key step so the first press after
    # startup (or an external volume change) cannot jump from e.g. 20% to 100%.
    current = float(AUDIOGAIN)

    rtype, rdata = audiosend(30, None)

    if rtype == 30 and rdata and "gain" in rdata:

        try:

            current = float(rdata["gain"])

        except Exception:

            pass

    gain = current + float(delta)

    if gain < 0.0:
        gain = 0.0

    if gain > 1.0:
        gain = 1.0

    rtype, rdata = audiosend(30, {"gain": gain})

    if rtype == 30 and rdata and "gain" in rdata:

        try:

            AUDIOGAIN = float(rdata["gain"])

        except Exception:

            AUDIOGAIN = gain

    else:

        AUDIOGAIN = gain

    return float(AUDIOGAIN)


def audiomutetoggle():

    global AUDIOMUTE

    mute = not bool(AUDIOMUTE)

    rtype, rdata = audiosend(31, {"mute": mute})

    if rtype == 31 and rdata and "mute" in rdata:

        AUDIOMUTE = bool(rdata["mute"])

    else:

        AUDIOMUTE = mute


def handleinputevent(msg):

    try:

        kind = str(msg.get("kind", ""))

    except Exception:

        kind = ""

    # A session helper is authoritative from Win+L until Startup proves a
    # successful password check over its peer-credential-bound connection.
    # During its short visibility handoff, keep compositor pointer state live
    # but withhold all application dispatch. Freezing pointer state here made
    # the first post-login sample jump forward and feel delayed; forwarding it
    # would leak hover/input to the still-mapped desktop underneath.
    protectedhandoff = SESSIONLOCKED and not sessionlockvisible()

    if protectedhandoff and kind != "pointer":
        return

    # inputserver -> windowserver visibility
    # log(f"input rx kind={kind} msg={msg}")

    # ------------------------------------------------------------
    # pointer motion
    # ------------------------------------------------------------
    if kind == "pointer":

        x = int(msg.get("x", 0))
        y = int(msg.get("y", 0))

        inputpointer({"x": x, "y": y, "mods": msg.get("mods", {})}, dispatch=not protectedhandoff)

        return

    # ------------------------------------------------------------
    # mouse buttons
    # ------------------------------------------------------------
    if kind == "button":

        b = int(msg.get("button", 0))

        # inputserver uses evdev BTN_* codes; windowserver expects 1/2/3
        if b == 0x110:
            btn = 1
        elif b == 0x111:
            btn = 2
        elif b == 0x112:
            btn = 3
        else:
            btn = 0

        st = str(msg.get("state", "down"))

        mods = msg.get("mods", {})

        if btn != 0:
            inputbutton({"button": btn, "state": st, "mods": mods})

        return

    # ------------------------------------------------------------
    # scroll
    # ------------------------------------------------------------
    if kind == "scroll":

        dx = int(msg.get("dx", 0))
        dy = int(msg.get("dy", 0))
        mods = msg.get("mods", {})

        # Wheel input follows the pointer.  This also lets non-focusable
        # transient surfaces such as Expanse's volume popup receive scrolling.
        wid = HOVERWID

        if (
            wid in windows
            and windows[wid].get("mapped")
            and not windows[wid].get("standard_dialog")
        ):

            sendjson(windows[wid]["cid"], {
                "op": "SCROLL",
                "winid": wid,
                "dx": dx,
                "dy": dy,
                "x": int(POINTERX - windows[wid]["x"]),
                "y": int(POINTERY - windows[wid]["y"]),
                "mods": mods,
            })

        return

    # ------------------------------------------------------------
    # key
    # ------------------------------------------------------------
    if kind == "key":

        try:

            key = str(msg.get("key", ""))

            st = str(msg.get("state", "down"))

            mods = msg.get("mods", {})

        except Exception:

            key = ""
            st = ""
            mods = {}

        if st in ("down", "repeat"):

            if (
                key.upper() in ("C", "X", "V")
                and bool(mods.get("ctrl") or mods.get("control"))
                and FOCUSWID in windows
                and not windows[FOCUSWID].get("standard_dialog")
            ):
                markclipboardgesture(windows[FOCUSWID].get("cid"))

            if key == "VOLUP":

                gain = audiovolume(+AUDIOSTEP)

                broadcasttaskbarevent({
                    "op": "TASKBAR_VOLUME_HOTKEY",
                    "gain": float(gain),
                    "mute": bool(AUDIOMUTE),
                })

                return

            if key == "VOLDOWN":

                gain = audiovolume(-AUDIOSTEP)

                broadcasttaskbarevent({
                    "op": "TASKBAR_VOLUME_HOTKEY",
                    "gain": float(gain),
                    "mute": bool(AUDIOMUTE),
                })

                return

        if st == "down":

            if key == "MUTE":

                audiomutetoggle()

                return

        allowed = winshortcutsallowed()

        if not allowed:

            WINSTATE["held"] = False

            WINSTATE["used"] = False

            WINSTATE["suppresstext"] = []

            if key in ("LWIN", "RWIN"):
                return

        if allowed and key in ("PRTSCR", "PRINT"):

            if st == "down":
                takescreenshot()

            return

        if (
            allowed
            and key in ("ESC", "ESCAPE")
            and bool(mods.get("shift"))
            and bool(mods.get("ctrl") or mods.get("control"))
        ):

            if st == "down":
                openoperationscentre()

            return

        if allowed:

            # win key -> start menu toggle (tap only), same behavior as old pumpkeyboard()
            if key in ("LWIN", "RWIN"):

                if st == "down":
                    WINSTATE["held"] = True

                    WINSTATE["used"] = False

                    WINSTATE["suppresstext"] = []

                    return

                if st == "up":

                    if WINSTATE.get("held") and not WINSTATE.get("used"):
                        broadcaststartmenutoggle()

                    WINSTATE["held"] = False

                    WINSTATE["suppresstext"] = []

                    return

                # if win is held and another key is pressed, mark as used
            if WINSTATE.get("held") and st == "down":
                WINSTATE["used"] = True

            # win+l -> lock the active session
            if WINSTATE.get("held") and key == "L":

                if st == "down":

                    WINSTATE["suppresstext"].append("l")

                    locksession()

                return

            # win+e -> open array (global, windowserver launched)
            if WINSTATE.get("held") and st == "down" and key == "E":

                WINSTATE["suppresstext"].append("e")

                openarray()

                return

            # win+b -> open brick
            if WINSTATE.get("held") and st == "down" and key == "B":

                WINSTATE["suppresstext"].append("b")

                openbrick()

                return

            # win+x -> end focused window process
            if WINSTATE.get("held") and st == "down" and key == "X":

                WINSTATE["suppresstext"].append("x")

                wid = FOCUSWID

                if wid in windows:

                    win = windows[wid]

                    role = str(win.get("role", ""))

                    if role == "window":

                        cid = win.get("cid", None)

                        pid = win.get("pid", None)

                        if cid is not None:

                            # ask client to close cleanly
                            sendjson(cid, {"op": "CLOSE", "winid": wid})

                            # offer to kill it if it doesn't exit
                            if pid is not None:

                                pendingkilladd(pid, cid, wid, timeout=0.35)

                return

            # win+space -> toggle maximise focused window
            if WINSTATE.get("held") and st == "down" and key == "SPACE":

                WINSTATE["suppresstext"].append(" ")

                wid = FOCUSWID

                if wid in windows:

                    win = windows[wid]

                    role = str(win.get("role", ""))

                    if role == "window":

                        if ismaximized(win):

                            restorewindow(wid)

                        else:

                            maximizewindow(wid)

                return

            # win+backspace -> minimise focused window
            if WINSTATE.get("held") and st == "down" and key == "BACKSPACE":

                WINSTATE["suppresstext"].append("\b")

                WINSTATE["suppresstext"].append("\x08")

                wid = FOCUSWID

                if wid in windows:

                    win = windows[wid]

                    role = str(win.get("role", ""))

                    if role == "window":

                        minimizewindow(wid)

                return

            # win+1..win+9 (win+0 -> 10) -> launch/activate pinned taskbar slot
            if WINSTATE.get("held") and st == "down" and key in ("1", "2", "3", "4", "5", "6", "7", "8", "9", "0"):

                WINSTATE["suppresstext"].append(key)

                try:

                    if key == "0":
                        idx = 10

                    else:
                        idx = int(key)

                except Exception:

                    idx = 0

                if idx > 0:

                    broadcasttaskbarevent({"op": "TASKBAR_PIN_HOTKEY", "index": idx})

                return

        # forward physical key event to focused window
        wid = FOCUSWID

        if wid in windows and windows[wid].get("mapped"):

            if windows[wid].get("standard_dialog"):
                dialogkey(wid, msg)
            else:
                sendjson(windows[wid]["cid"], {
                    "op": "KEY",
                    "winid": wid,
                    "code": int(msg.get("code", 0)),
                    "key": key,
                    "state": st,
                    "mods": mods
                })

        return

    # ------------------------------------------------------------
    # text
    # ------------------------------------------------------------
    if kind == "text":

        s = str(msg.get("text", ""))

        # never type into apps while Win key is held
        if WINSTATE.get("held"):
            return

        # swallow any queued text created by Win+hotkey combos (covers ordering quirks)
        sup = WINSTATE.get("suppresstext", [])

        if s in sup:

            sup.remove(s)

            WINSTATE["suppresstext"] = sup
            return

        wid = FOCUSWID

        if (
            wid in windows
            and windows[wid].get("mapped")
            and windows[wid].get("standard_dialog")
        ):
            dialogtext(wid, s)

        elif wid in windows and windows[wid].get("mapped") and s:

            # log(f"send TEXT winid={wid} text={repr(s)}")

            sendjson(windows[wid]["cid"], {
                "op": "TEXT",
                "winid": wid,
                "text": s
            })

        return


def handleinputserverline(line):

    if not processidentitycurrent(INPUTIDENTITY):
        disconnectinputserver("authenticated identity ended")
        return

    msg = json.loads(line)

    try:

        op = str(msg.get("op", ""))

    except Exception:
        op = ""

    # inputserver control replies (HELLO/SUBSCRIBE acks)
    if op in ("WELCOME", "OK"):
        return

    if op == "ERROR":
        return

    # inputserver emits raw events like {"kind":"pointer",...}

    if "kind" in msg:
        recordinputlatency(msg)
        handleinputevent(msg)
        return


    if op == "EVENT" and isinstance(msg.get("ev"), dict):
        recordinputlatency(msg["ev"])
        handleinputevent(msg["ev"])
        return


def recordinputlatency(msg):

    try:

        source = int(msg.get("source_monotonic_ns", 0))

        if source <= 0:
            return

        milliseconds = max(0.0, (time.monotonic_ns() - source) / 1000000.0)
        INPUTLATENCYHISTORY.append(milliseconds)

        if len(INPUTLATENCYHISTORY) > int(INPUTLATENCYCAP):
            del INPUTLATENCYHISTORY[:-int(INPUTLATENCYCAP)]

    except Exception:
        pass

def hittest(x, y):

    try:

        desktop_candidate = None

        for wid in reversed(zorder):

            if not windows[wid]["mapped"]:
                continue

            if windows[wid]["role"] == "desktop":
                desktop_candidate = wid
                continue

            wx = windows[wid]["x"]
            wy = windows[wid]["y"]
            ww = windows[wid]["w"]
            wh = windows[wid]["h"]

            if wx <= x < wx + ww and wy <= y < wy + wh:
                return wid

        return desktop_candidate

    except Exception:
        return None


def mappedfocusfallback(exclude=None):

    for candidate in reversed(zorder):

        if candidate == exclude or candidate not in windows:
            continue

        win = windows[candidate]

        if not win.get("mapped"):
            continue

        if str(win.get("role", "")) not in ("lockscreen", "startup", "window"):
            continue

        return candidate

    return None


def setfocus(wid, reaffirm=False):

    global FOCUSWID

    if wid in windows and not windows[wid].get("mapped"):
        wid = mappedfocusfallback(exclude=wid)

    seen = set()
    while wid not in seen:
        seen.add(wid)
        modalwid = modaldialogfor(wid)
        if modalwid not in windows:
            break
        wid = modalwid
        if wid in zorder:
            zorder.remove(wid)
        zorder.append(wid)

    if wid in windows and not windows[wid].get("mapped"):
        wid = mappedfocusfallback(exclude=wid)

    if wid == FOCUSWID:

        if reaffirm and wid in windows:
            sendjson(
                windows[wid]["cid"],
                {"op": "FOCUS", "winid": wid, "state": "in"},
            )

        return

    old = FOCUSWID
    FOCUSWID = wid

    # damage old focus (frame + client) so uncovered areas repaint cleanly
    if old in windows:

        orole = str(windows[old].get("role", ""))

        if windows[old].get("mapped") and orole == "window":

            DAMAGERECTS.append(framedamagerect(windows[old]))

            DAMAGERECTS.append([windows[old]["x"], windows[old]["y"], windows[old]["w"], windows[old]["h"]])

    # damage new focus (frame + client) so focus transition can't leave stale strips
    if wid in windows:

        nrole = str(windows[wid].get("role", ""))

        if windows[wid].get("mapped") and nrole == "window":

            DAMAGERECTS.append(framedamagerect(windows[wid]))

            DAMAGERECTS.append([windows[wid]["x"], windows[wid]["y"], windows[wid]["w"], windows[wid]["h"]])

    # notify old
    if old in windows:
        sendjson(windows[old]["cid"], {"op": "FOCUS", "winid": old, "state": "out"})
    if wid in windows:
        sendjson(windows[wid]["cid"], {"op": "FOCUS", "winid": wid, "state": "in"})

    # broadcast focused window to desktop taskbar
    if wid in windows:

        role = str(windows[wid].get("role", ""))

        if role == "window" and not modalwindow(windows[wid]):

            ev = {
                "op": "TASKBAR_WINDOW_FOCUS",
                "winid": wid
            }

            broadcasttaskbarevent(ev)


def focusset(cid, msg):

    try:

        wid = int(msg.get("winid", 0))

        if wid in windows and windows[wid]["cid"] == cid:
            setfocus(wid)
            sendjson(cid, {"op": "FOCUS", "winid": wid, "state": "in"})
        else:
            sendjson(cid, {"op": "ERROR", "code": "unknown_window"})

    except Exception as e:

        sendjson(cid, {"op": "ERROR", "code": "focus_failed", "detail": str(e)})


def pulsefocus():

    global FOCUSPENDING

    if FOCUSPENDING is None:
        return

    wid = FOCUSPENDING
    FOCUSPENDING = None


    if wid not in windows:
        return

    if not windows[wid].get("mapped"):
        return

    role = str(windows[wid].get("role", ""))

    if role not in ("window", "lockscreen", "startup"):
        return

    setfocus(wid)


def savewindowpointerpos(force=False):

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

        path = os.path.join(STATEBASE, "pointer.pos")

        with open(path, "w") as handle:
            handle.write(f"{POINTERX},{POINTERY}")

        POINTERSAVELAST = now
        POINTERSAVEDIRTY = False
        return True

    except Exception:
        return False


def schedulewindowpointerpossave():

    global POINTERSAVEDIRTY

    POINTERSAVEDIRTY = True


def refreshcursormode():

    global CURSORMODE, CURSORDIRTY, LASTCURSOR

    oldmode = str(CURSORMODE)
    oldbox = list(LASTCURSOR) if LASTCURSOR else [0, 0, 0, 0]

    try:
        newmode = computecursormode(POINTERX, POINTERY)
    except Exception:
        newmode = "arrow"

    newbox = pointercursorbox(POINTERX, POINTERY, newmode)
    CURSORMODE = newmode
    LASTCURSOR = newbox

    if oldmode == newmode and oldbox == newbox:
        return False

    CURSORDIRTY = True

    if len(oldbox) == 4 and oldbox[2] > 0 and oldbox[3] > 0:
        DAMAGERECTS.append(oldbox)

    if newbox and len(newbox) == 4 and newbox[2] > 0 and newbox[3] > 0:
        DAMAGERECTS.append(newbox)

    return True


def inputpointer(msg, dispatch=True):

    global POINTERX, POINTERY, HOVERWID, CURSORDIRTY, LASTCURSOR, CURSORMODE

    x = msg.get("x", msg.get("absx", 0))
    y = msg.get("y", msg.get("absy", 0))
    x = int(x)
    y = int(y)

    if x < 0:
        x = 0

    if y < 0:
        y = 0

    if x > SCREENW - 1:
        x = SCREENW - 1

    if y > SCREENH - 1:
        y = SCREENH - 1

    POINTERX = x
    POINTERY = y

    CURSORDIRTY = True


    schedulewindowpointerpossave()

    refreshcursormode()

    # Coordinate and cursor rendering state remain authoritative even while a
    # protected session transition has no visible owner. Do not let that state
    # update become hover, drag, or motion input for a client underneath.
    if not dispatch:
        return

    if DRAGINFO.get("wid"):
        setwindowbuttonhover(None)
    else:
        updatewindowbuttonhover(POINTERX, POINTERY)


    # drag/resize if active
    if DRAGINFO.get("wid") in windows and windows[DRAGINFO["wid"]].get("role") == "window":

        wid = DRAGINFO["wid"]

        win = windows[wid]

        dx = x - DRAGINFO.get("sx", x)

        dy = y - DRAGINFO.get("sy", y)

        if DRAGINFO.get("kind") == "move":

            nx = DRAGINFO.get("ox", win["x"]) + dx

            ny = DRAGINFO.get("oy", win["y"]) + dy

            movewindow(win["cid"], {"winid": wid, "x": nx, "y": ny})

            if not modalwindow(win):
                sk = snapkind(x, y)

                pr = snappreviewrect(sk)

                setsnappreview(pr)

        elif DRAGINFO.get("kind") in (

            "left", "right", "top", "bottom",

            "topleft", "topright", "bottomleft", "bottomright"):

            nx = win["x"]

            ny = win["y"]

            nw = DRAGINFO.get("ow", win["w"])

            nh = DRAGINFO.get("oh", win["h"])

            kind = DRAGINFO.get("kind", "")

            if "left" in kind:

                nx = DRAGINFO.get("ox", win["x"]) + dx

                nw = DRAGINFO.get("ow", win["w"]) - dx

            if "right" in kind and "left" not in kind:
                nw = DRAGINFO.get("ow", win["w"]) + dx

            if "top" in kind:

                ny = DRAGINFO.get("oy", win["y"]) + dy

                nh = DRAGINFO.get("oh", win["h"]) - dy

            if "bottom" in kind and "top" not in kind:
                nh = DRAGINFO.get("oh", win["h"]) + dy

            if nw < 160:
                nw = 160

            if nh < 120:
                nh = 120

            movewindow(win["cid"], {"winid": wid, "x": nx, "y": ny})

            resizewindow(win["cid"], {"winid": wid, "w": nw, "h": nh})


    if DRAGINFO.get("wid"):
        return


    gwid = POINTERGRAB.get("wid")

    gbtn = int(POINTERGRAB.get("btn", 0))

    if gwid in windows and gbtn in BTNDOWN:

        if windows[gwid].get("standard_dialog"):
            dialogmotion(gwid, x - windows[gwid]["x"], y - windows[gwid]["y"])
            return

        wx = windows[gwid]["x"]
        wy = windows[gwid]["y"]

        # log(f"send POINTER_MOTION winid={wid} x={lx} y={ly} absx={x} absy={y}")

        sendjson(
            windows[gwid]["cid"],
            {
                "op": "POINTER_MOTION",
                "winid": gwid,
                "x": x - wx,
                "y": y - wy,
                "absx": x,
                "absy": y,
                "mods": msg.get("mods", {}),
            }
        )

        return

    wid = hittest(x, y)

    modalwid = modaldialogfor(wid)
    if modalwid in windows:
        wid = modalwid


    framewid = topmostwindowat(x, y)

    if framewid in windows and windows[framewid].get("role") != "window":

        wid = framewid

    if wid != HOVERWID:

        if HOVERWID in windows:

            if not windows[HOVERWID].get("standard_dialog"):
                sendjson(windows[HOVERWID]["cid"], {"op": "POINTER_LEAVE", "winid": HOVERWID})
        if wid in windows:

            if not windows[wid].get("standard_dialog"):
                sendjson(windows[wid]["cid"], {"op": "POINTER_ENTER", "winid": wid})
        HOVERWID = wid

    # normal motion to client content
    if wid in windows and windows[wid].get("mapped"):

        if windows[wid].get("standard_dialog"):
            return

        wx = windows[wid]["x"]
        wy = windows[wid]["y"]
        lx = x - wx
        ly = y - wy

        # try:
        #
        #     log(f"input tx op=POINTER_MOTION winid={wid} absx={x} absy={y} cid={windows[wid]['cid']}")
        #
        # except Exception:
        #
        #     pass

        sendjson(
            windows[wid]["cid"],
            {
                "op": "POINTER_MOTION",
                "winid": wid,
                "x": lx,
                "y": ly,
                "absx": x,
                "absy": y,
                "mods": msg.get("mods", {}),
            }
        )

def sendbuttonglobal(wid, btn, st, x, y):

    try:

        # collect clients that own a desktop window
        targets = set()

        for win in windows.values():


            if win.get("role") == "desktop":

                cid = win.get("cid")

                if cid is not None:

                    targets.add(cid)

        if not targets:
            return

        # build event payload
        ev = {
            "op":    "POINTER_BUTTON_GLOBAL",
            "winid": int(wid),
            "button": int(btn),
            "state": str(st),
            "absx":  int(x),
            "absy":  int(y)
        }

        # send to each desktop client
        for cid in list(targets):


            # log(
            #     f"send POINTER_BUTTON_GLOBAL winid={wid} "
            #     f"button={btn} state={st} absx={x} absy={y}"
            # )

            sendjson(cid, ev)

    except Exception as e:

        # button global send error
        log(f"button global send error {e}")


def inputbutton(msg):

    btn = int(msg.get("button", 0))
    st = str(msg.get("state", "down"))
    x = int(POINTERX)
    y = int(POINTERY)

    physicalwid = topmostwindowat(x, y)

    if physicalwid not in windows:
        physicalwid = hittest(x, y)

    if physicalwid not in windows:
        physicalwid = 0

    try:
        routeinputbutton(msg)
    finally:
        # Click-away behavior describes where the physical event happened,
        # independent of pointer grabs and every local routing early-return.
        sendbuttonglobal(physicalwid, btn, st, x, y)

        # A clipboard request following a real click (for example a context
        # menu command) receives a short, focused user-activation grant.
        if (
            st == "down"
            and physicalwid in windows
            and int(FOCUSWID or 0) == int(physicalwid)
            and not windows[physicalwid].get("standard_dialog")
        ):
            gesturecid = windows[physicalwid].get("cid")
            markclipboardgesture(gesturecid)
            markphysicalgesture(gesturecid)

        if st == "up":
            refreshcursormode()


def routeinputbutton(msg):

    btn = int(msg.get("button", 0))
    st  = str(msg.get("state", "down"))
    mods = msg.get("mods", {})

    # absolute pointer at time of click
    x = POINTERX
    y = POINTERY

    # end active window drags on mouse up (even if cursor left the title/edge area)
    if st == "up":

        BTNDOWN.discard(btn)

        if DRAGINFO.get("wid") in windows and DRAGINFO.get("kind") == "move" and int(DRAGINFO.get("btn", 0)) == btn:


            dwid = DRAGINFO.get("wid")

            if not windows[dwid].get("standard_dialog"):
                sk = snapkind(x, y)

                if sk:
                    snapapply(dwid, sk)

            setsnappreview(None)

            DRAGINFO["wid"] = None
            DRAGINFO["kind"] = None
            DRAGINFO["btn"] = 0

            POINTERGRAB["wid"] = None
            POINTERGRAB["btn"] = 0

            return

        if DRAGINFO.get("wid") in windows and DRAGINFO.get("kind") in (

            "left", "right", "top", "bottom",

            "topleft", "topright", "bottomleft", "bottomright") and int(DRAGINFO.get("btn", 0)) == btn:


            setsnappreview(None)

            DRAGINFO["wid"] = None
            DRAGINFO["kind"] = None
            DRAGINFO["btn"] = 0

            POINTERGRAB["wid"] = None
            POINTERGRAB["btn"] = 0

            return

    # if a grab is active, route UP to the grabbed window
    if st == "up":

        try:

            gwid = POINTERGRAB.get("wid")

            gbtn = int(POINTERGRAB.get("btn", 0))

            if gwid in windows and gbtn == btn:

                wid = gwid

            else:

                wid = topmostwindowat(x, y)

                if wid not in windows:
                    wid = hittest(x, y)

        except Exception:

            wid = topmostwindowat(x, y)

            if wid not in windows:
                wid = hittest(x, y)

    else:

        # normal DOWN routing by hit-test
        wid = topmostwindowat(x, y)

        if wid not in windows:
            wid = hittest(x, y)

    if wid not in windows:
        return

    # An owned standard dialog is modal to its parent. Clicking the parent
    # raises the dialog and routes the click there instead of reaching the app.
    modalwid = modaldialogfor(wid)
    if modalwid in windows:
        wid = modalwid
        setfocus(wid)
        raisewindow(windows[wid]["cid"], {"winid": wid})


    win  = windows[wid]
    kind = None
    area = None

    # run frame hit-test on the chosen window (handles title/close/max/min/resize)
    if win.get("role") == "window":

        hit = framehittest(x, y, win)

        if hit:
            kind, area = hit


    if kind == "button" and st == "up":


        if area == "close":

            setwindowbuttonhover(None)

            if win.get("standard_dialog"):
                dialogfinish(wid, dialogcancelid(win))
                return

            sendjson(win["cid"], {"op": "CLOSE", "winid": wid})


            # show a kill/cancel prompt if the client doesn't exit quickly
            pid = win.get("pid", None)

            if pid is not None:
                pendingkilladd(pid, win["cid"], wid, timeout=0.35)

            return


        if area == "min":

            if win.get("standard_dialog"):
                return

            minimizewindow(wid)
            updatewindowbuttonhover(POINTERX, POINTERY)

            return


        if area == "max":

            if win.get("standard_dialog"):
                return

            if ismaximized(win):

                restorewindow(wid)

            else:

                maximizewindow(wid)

            updatewindowbuttonhover(POINTERX, POINTERY)

            return


    # start drags on title and edges
    if kind == "title":

        if st == "down":

            setfocus(wid)

            raisewindow(win["cid"], {"winid": wid})

            if not modalwindow(win):
                unsnapdrag(wid, x, y)

            win = windows[wid]

            DRAGINFO["wid"] = wid

            DRAGINFO["kind"] = "move"

            DRAGINFO["btn"] = btn

            DRAGINFO["sx"] = x

            DRAGINFO["sy"] = y

            DRAGINFO["ox"] = win["x"]

            DRAGINFO["oy"] = win["y"]

            return


    if kind == "resize":

        if st == "down":

            setfocus(wid)

            raisewindow(win["cid"], {"winid": wid})

            DRAGINFO["wid"]  = wid

            DRAGINFO["kind"] = area

            DRAGINFO["btn"]  = btn

            DRAGINFO["sx"]   = x

            DRAGINFO["sy"]   = y

            DRAGINFO["ox"]   = win["x"]

            DRAGINFO["oy"]   = win["y"]

            DRAGINFO["ow"]   = win["w"]

            DRAGINFO["oh"]   = win["h"]

            return


        if st == "up" and DRAGINFO.get("wid") == wid and int(DRAGINFO.get("btn", 0)) == btn:

            DRAGINFO["wid"] = None
            DRAGINFO["kind"] = None
            DRAGINFO["btn"] = 0

            return


    # Standard dialogs own their client input; their parent application only
    # receives the final DIALOG_RESULT event.
    if win.get("standard_dialog"):
        if st == "down":
            BTNDOWN.add(btn)
            POINTERGRAB["wid"] = wid
            POINTERGRAB["btn"] = btn
            setfocus(wid)
            raisewindow(win["cid"], {"winid": wid})
        dialogpointer(wid, st, x - win["x"], y - win["y"], btn, mods)
        if st == "up" and POINTERGRAB.get("wid") == wid and int(POINTERGRAB.get("btn", 0)) == btn:
            POINTERGRAB["wid"] = None
            POINTERGRAB["btn"] = 0
        return

    # clicks inside client → forward to app
    if st == "down":


        BTNDOWN.add(btn)


        POINTERGRAB["wid"] = wid

        POINTERGRAB["btn"] = btn

        setfocus(wid)

        raisewindow(win["cid"], {"winid": wid})


    wx = win["x"]
    wy = win["y"]


    sendjson(win["cid"], {
        "op": "POINTER_BUTTON",
        "winid": wid,
        "button": btn,
        "state": st,
        "absx": x,
        "absy": y,
        "x": x - wx,
        "y": y - wy,
        "mods": mods
    })


    if st == "up":


        if POINTERGRAB.get("wid") == wid and int(POINTERGRAB.get("btn", 0)) == btn:

            POINTERGRAB["wid"] = None

            POINTERGRAB["btn"] = 0

def inputkey(msg):


    # simple key routing to focused window
    wid = FOCUSWID

    if wid in windows and windows[wid].get("mapped"):

        mods = msg.get("mods", {})
        if (
            str(msg.get("state", "down")) in ("down", "repeat")
            and str(msg.get("key", "")).upper() in ("C", "X", "V")
            and bool(mods.get("ctrl") or mods.get("control"))
            and not windows[wid].get("standard_dialog")
        ):
            markclipboardgesture(windows[wid].get("cid"))

        if windows[wid].get("standard_dialog"):
            dialogkey(wid, msg)
            return

        sendjson(windows[wid]["cid"], {
            "op": "KEY",
            "winid": wid,
            "code": int(msg.get("code", 0)),
            "key":  str(msg.get("key", "")),
            "state": str(msg.get("state", "down")),
            "mods": msg.get("mods", {})
        })
def startserver():

    try:

        # ensure accept directory exists
        sockdir = os.path.dirname(SOCKPATH)

        try:

            # create accept directory if missing
            if not os.path.exists(sockdir):
                os.makedirs(sockdir, exist_ok=True)

        except PermissionError:

            # permission denied creating accept directory
            log(f"permission denied creating accept directory")
            sys.exit(1)

        except OSError as e:

            # os error creating accept directory
            log(f"accept directory error {e}")
            sys.exit(1)

        try:

            info = os.lstat(sockdir)
            if (
                not stat.S_ISDIR(info.st_mode)
                or stat.S_ISLNK(info.st_mode)
                or info.st_uid != os.geteuid()
            ):
                raise PermissionError("unsafe WindowServer socket directory")

            # Publish only to the exact desktop-session group. Privileged
            # operations still require immutable kernel-domain capabilities.
            os.chown(sockdir, -1, SESSIONGID)
            os.chmod(sockdir, 0o750)

        except PermissionError:

            # permission denied chmod accept directory
            log(f"permission denied chmod accept directory")
            sys.exit(1)

        except OSError as e:

            # os error chmod accept directory
            log(f"chmod accept directory error {e}")
            sys.exit(1)

        # remove only an owned Unix socket, never a substituted file or symlink
        removestalesocket(SOCKPATH)

        # create unix domain socket
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

        # bind without a permissive umask window
        previousumask = os.umask(0o077)
        try:
            srv.bind(SOCKPATH)
        finally:
            os.umask(previousumask)

        try:

            os.chown(SOCKPATH, -1, SESSIONGID)
            os.chmod(SOCKPATH, 0o660)

        except PermissionError:

            # permission denied chmod accept socket
            log(f"permission denied chmod accept socket")
            sys.exit(1)

        except OSError as e:

            # os error chmod accept socket
            log(f"chmod accept socket error {e}")
            sys.exit(1)

        # listen for clients
        srv.listen(16)

        # register with selector
        srv.setblocking(False)
        sel.register(srv, selectors.EVENT_READ, data={"kind": "listener"})

        # write server id
        sid = random.randint(1000, 9999)
        return srv, sid

    except PermissionError:

        # permission denied binding socket
        log(f"permission denied creating accept socket")
        sys.exit(1)

    except OSError as e:

        # os error starting server
        log(f"server socket error {e}")
        sys.exit(1)


def startvideoserver():

    if not GPUCOMPOSITOR or not gpuvideoavailable():
        graphicslog(
            "> graphics video surface server disabled: "
            "DMA-BUF import entry points unavailable"
        )
        return None

    try:
        if not gpuvideoinitialise():
            raise RuntimeError(
                "external-image video shaders did not initialise"
            )

        importcapabilities = gpuvideoimportcapabilities(
            include_modifiers=False,
            probe=True,
        )

        if (
            not bool(importcapabilities.get("available"))
            or bool(importcapabilities.get("deferred"))
            or not importcapabilities.get("formats")
        ):
            raise RuntimeError(
                "DMA-BUF format query returned no usable formats "
                f"capabilities={importcapabilities}"
            )

        graphicslog(
            f"> graphics video surface import gate passed "
            f"formats={len(importcapabilities.get('formats', []))} "
            f"modifier_query="
            f"{bool(importcapabilities.get('modifier_query'))}"
        )

        removestalesocket(VIDEOSOCKPATH)

        server = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        previousumask = os.umask(0o077)
        try:
            server.bind(VIDEOSOCKPATH)
        finally:
            os.umask(previousumask)
        os.chown(VIDEOSOCKPATH, -1, SESSIONGID)
        os.chmod(VIDEOSOCKPATH, 0o660)
        server.listen(8)
        server.setblocking(False)
        sel.register(server, selectors.EVENT_READ, data={"kind": "video_listener"})
        return server
    except Exception as e:
        log(f"video surface server unavailable {e}")
        try:
            if "server" in locals():
                sel.unregister(server)
        except Exception:
            pass
        try:
            if "server" in locals():
                server.close()
        except Exception:
            pass
        try:
            removestalesocket(VIDEOSOCKPATH)
        except Exception:
            pass
        return None


def videoauthorizationvalid(authorization, peeridentity):

    if not isinstance(authorization, dict) or not processidentitycurrent(peeridentity):
        return False

    owner = clients.get(int(authorization.get("cid", -1)), {})
    owneridentity = owner.get("identity")
    ownerwindow = windows.get(int(authorization.get("wid", 0)))
    if not (
        processidentitycurrent(owneridentity)
        and int(owneridentity.get("pid", -1))
            == int(authorization.get("owner_pid", 0))
        and int(owneridentity.get("starttime", -1))
            == int(authorization.get("owner_starttime", 0))
        and str(owneridentity.get("domain", ""))
            == str(authorization.get("owner_domain", ""))
        and ownerwindow
        and int(ownerwindow.get("cid", -1))
            == int(authorization.get("cid", -2))
    ):
        return False

    peerdomain = str(peeridentity.get("domain", ""))
    ownerdomain = str(authorization.get("owner_domain", ""))
    if str(authorization.get("surface_type", "")) == "presentation":
        return peerdomain == "chromium"
    return peerdomain in (ownerdomain, "video")


def videoauthorize(cid, req):

    request = req if isinstance(req, dict) else {}
    try:
        wid = int(request.get("winid", 0))
        token = str(request.get("token", ""))
        stream = str(request.get("stream", ""))[:128]
        surface_type = str(request.get("surface_type", "video")).strip().lower()

        owneridentity = clients.get(cid, {}).get("identity")
        if (
            wid not in windows
            or int(windows[wid].get("cid", -1)) != int(cid)
            or not processidentitycurrent(owneridentity)
        ):
            raise ValueError("unknown_window")

        if len(token) < 32 or len(token) > 256 or not stream:
            raise ValueError("invalid video authorisation")

        if surface_type not in ("video", "presentation"):
            raise ValueError("invalid surface type")

        if surface_type == "presentation":
            if (
                str(clients.get(cid, {}).get("identity", {}).get("domain", ""))
                != "chromium"
                or str(windows[wid].get("role", "")) != "window"
                or stream != "__t1os_chromium_presentation__"
            ):
                raise PermissionError("GPU presentation surfaces are restricted to Chromium")

        if len(windows[wid].get("_video_streams", {})) >= VIDEOMAXSTREAMS:
            raise ValueError("video stream limit reached")

        for oldtoken, authorization in list(VIDEOAUTH.items()):
            if (
                int(authorization.get("cid", -1)) == int(cid)
                and int(authorization.get("wid", -1)) == wid
                and str(authorization.get("stream", "")) == stream
            ):
                VIDEOAUTH.pop(oldtoken, None)

        VIDEOAUTH[token] = {
            "cid": int(cid),
            "wid": wid,
            "stream": stream,
            "surface_type": surface_type,
            "token": token,
            "reusable": surface_type == "presentation",
            "expires": time.monotonic() + (86400.0 if surface_type == "presentation" else 15.0),
            "owner_pid": int(owneridentity.get("pid", 0)),
            "owner_starttime": int(owneridentity.get("starttime", 0)),
            "owner_domain": str(owneridentity.get("domain", "")),
        }
        if surface_type == "presentation":
            windows[wid]["_presentation_stream"] = stream
        windows[wid].setdefault("_video_streams", {}).setdefault(stream, {
            "pending": True,
            "frame": 0,
            "handle": 0,
            "connection": 0,
        })
        windows[wid].setdefault("_video_queues", {}).setdefault(stream, [])
        sendjson(cid, {
            "op": "VIDEO_AUTHORIZED",
            "winid": wid,
            "stream": stream,
            "socket": VIDEOSOCKPATH,
            "surface_type": surface_type,
        })
        graphicslog(
            "> graphics video authorization issued "
            f"client={int(cid)} window={wid} "
            f"stream_class="
            f"{'chromium-presentation' if stream == '__t1os_chromium_presentation__' else 'video'} "
            f"stream_length={len(stream)} "
            f"surface_type={surface_type} reusable="
            f"{surface_type == 'presentation'}"
        )
    except Exception as e:
        requestedwindow = request.get("winid", "unknown")
        if isinstance(requestedwindow, (int, str)):
            requestedwindow = str(requestedwindow)[:64]
        else:
            requestedwindow = type(requestedwindow).__name__
        requestedstream = request.get("stream", "")
        requestedstreamlength = (
            min(len(requestedstream), VIDEOPACKETLIMIT)
            if isinstance(requestedstream, str)
            else -1
        )
        requestedsurfacetype = request.get("surface_type", "video")
        requestedsurfacetype = (
            requestedsurfacetype[:32]
            if isinstance(requestedsurfacetype, str)
            else type(requestedsurfacetype).__name__
        )
        diagnosticdetail = str(e)
        if diagnosticdetail not in (
            "unknown_window",
            "invalid video authorisation",
            "invalid surface type",
            "GPU presentation surfaces are restricted to Chromium",
            "video stream limit reached",
        ):
            diagnosticdetail = type(e).__name__
        graphicslog(
            "> graphics video authorization rejected "
            f"client={cid} window={json.dumps(requestedwindow)} "
            f"stream_length={requestedstreamlength} "
            f"surface_type={json.dumps(requestedsurfacetype)} "
            f"detail={json.dumps(diagnosticdetail)}"
        )
        sendjson(cid, {"op": "ERROR", "code": "video_authorize_failed", "detail": str(e)})


def acceptvideoclient(server):

    connection = None
    identity = None
    identifier = None
    try:
        connection, _ = server.accept()
        if len(VIDEOCLIENTS) >= VIDEOCLIENTLIMIT:
            connection.close()
            log("rejected video client at connection limit")
            return
        identity = socketpeeridentity(connection)
        if not identity:
            connection.close()
            log("rejected video client without an authenticated peer identity")
            return
        connection.setblocking(False)
        identifier = random.randint(100000, 999999)

        while identifier in VIDEOCLIENTS:
            identifier = random.randint(100000, 999999)

        state = {
            "kind": "video_client",
            "id": identifier,
            "sock": connection,
            "identity": identity,
            "authorization": None,
            "out": [],
        }
        VIDEOCLIENTS[identifier] = state
        sel.register(connection, selectors.EVENT_READ, data=state)
        VIDEOTELEMETRY["connections"] += 1
    except BlockingIOError:
        return
    except Exception as e:
        log(f"video accept error {e}")
        if identifier is not None:
            VIDEOCLIENTS.pop(identifier, None)
        if connection is not None:
            try:
                sel.unregister(connection)
            except Exception:
                pass
        closeprocessidentity(identity)
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass


def updatevideoevents(state):

    try:
        mask = selectors.EVENT_READ

        if state.get("out"):
            mask |= selectors.EVENT_WRITE

        sel.modify(state["sock"], mask, data=state)
    except Exception:
        pass


def flushvideoclient(state):

    try:
        while state.get("out"):
            queued = state["out"][0]
            packet = queued.get("packet", b"") if isinstance(queued, dict) else queued
            descriptors = queued.get("fds", []) if isinstance(queued, dict) else []

            if descriptors:
                rights = array.array("i", [int(value) for value in descriptors])
                sent = state["sock"].sendmsg(
                    [packet],
                    [(socket.SOL_SOCKET, socket.SCM_RIGHTS, rights)],
                )
            else:
                sent = state["sock"].send(packet)

            if sent != len(packet):
                raise RuntimeError("partial video control packet")

            del state["out"][0]

            for descriptor in descriptors:
                try:
                    os.close(int(descriptor))
                except Exception:
                    pass

        updatevideoevents(state)
    except BlockingIOError:
        updatevideoevents(state)
    except Exception as e:
        dropvideoclient(int(state.get("id", 0)), f"send error {e}")


def videorelease(connectionid, frame, generation=None):

    payload = {
        "op": "release",
        "frame": int(frame),
    }

    if generation is not None:
        payload["generation"] = int(generation)

    return videoevent(connectionid, payload, release=True)


def videoevent(connectionid, payload, release=False):

    state = VIDEOCLIENTS.get(int(connectionid))

    if state is None:
        return False

    packet = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    state["out"].append(packet)
    if release:
        VIDEOTELEMETRY["releases"] += 1
    updatevideoevents(state)
    flushvideoclient(state)
    return True


def videoeventfds(connectionid, payload, fds):

    state = VIDEOCLIENTS.get(int(connectionid))

    if state is None:
        return False

    packet = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    state["out"].append({"packet": packet, "fds": [int(value) for value in fds]})
    updatevideoevents(state)
    flushvideoclient(state)
    return True


def videodestroyresource(resource, wait=False):

    if not isinstance(resource, dict):
        return False

    # A presentation frame borrows its generation's retained render target.
    # Only an explicitly owned target may be destroyed with the frame; the
    # configuration teardown destroys the shared target exactly once.
    retained = (
        int(resource.pop("retained_handle", 0) or 0)
        if bool(resource.pop("retained_owned", False))
        else 0
    )
    resource["retained_ready"] = False

    try:
        handle = int(resource.get("handle", 0) or 0)

        if handle:
            gpuvideosurfacedestroy(handle, wait=bool(wait))

    finally:

        if retained:
            gputargetdestroy(retained)

    return True


def videoretire(resource, wid, wait=False):

    if not isinstance(resource, dict):
        return

    handle = int(resource.get("handle", 0))

    if not handle:
        return

    if wait:
        videodestroyresource(resource, wait=True)
        videorelease(
            resource.get("connection", 0),
            resource.get("frame", 0),
            generation=(
                resource.get("generation")
                if bool(resource.get("presentation_dmabuf", False))
                else None
            ),
        )
        return

    VIDEORETIRED.append({
        **resource,
        "wid": int(wid),
        "after": int(GPUFRAMESEQUENCE) + 3,
        "deadline": time.monotonic() + 0.125,
    })


def videoreleasepulse(force=False):

    remaining = []
    now = time.monotonic()

    for resource in VIDEORETIRED:
        ready = (
            force
            or int(GPUFRAMESEQUENCE) >= int(resource.get("after", 0))
            or now >= float(resource.get("deadline", now))
        )

        if not ready:
            remaining.append(resource)
            continue

        deadlinewait = not force and now >= float(resource.get("deadline", now))
        videodestroyresource(resource, wait=bool(force or deadlinewait))
        videorelease(
            resource.get("connection", 0),
            resource.get("frame", 0),
            generation=(
                resource.get("generation")
                if bool(resource.get("presentation_dmabuf", False))
                else None
            ),
        )

    VIDEORETIRED[:] = remaining


def videowindowrelease(win, wait=True):

    for token, authorization in list(VIDEOAUTH.items()):
        if int(authorization.get("wid", -1)) == int(win.get("id", 0)):
            VIDEOAUTH.pop(token, None)

    streams = win.get("_video_streams", {})

    if not isinstance(streams, dict):
        streams = {}

    for resource in list(streams.values()):
        try:
            videoretire(resource, win.get("id", 0), wait=wait)
        except Exception:
            pass

    queues = win.get("_video_queues", {})

    if isinstance(queues, dict):
        for resources in list(queues.values()):
            for resource in list(resources) if isinstance(resources, list) else []:
                try:
                    videoretire(resource, win.get("id", 0), wait=wait)
                except Exception:
                    pass

    win["_video_streams"] = {}
    win["_video_queues"] = {}
    win.pop("_presentation_stream", None)

    for resource in list(VIDEORETIRED):
        if int(resource.get("wid", -1)) != int(win.get("id", 0)):
            continue

        try:
            VIDEORETIRED.remove(resource)
            videodestroyresource(resource, wait=wait)
            videorelease(resource.get("connection", 0), resource.get("frame", 0))
        except Exception:
            pass


def dropvideoclient(identifier, reason):

    state = VIDEOCLIENTS.pop(int(identifier), None)

    if state is None:
        return

    authorization = state.get("authorization")

    if isinstance(authorization, dict):
        authorizedstream = str(authorization.get("stream", ""))[:128]
        graphicslog(
            "> graphics video connection closing "
            f"connection={identifier} "
            f"window={authorization.get('wid')} "
            f"stream_class="
            f"{'chromium-presentation' if authorizedstream == '__t1os_chromium_presentation__' else 'video'} "
            f"stream_length={len(authorizedstream)} "
            f"surface_type={authorization.get('surface_type', 'unknown')} "
            f"reason={json.dumps(str(reason)[:256])}"
        )
        win = windows.get(int(authorization.get("wid", 0)))
        stream = str(authorization.get("stream", ""))

        if win is not None:
            streams = win.get("_video_streams", {})
            resource = streams.get(stream)
            if (
                isinstance(resource, dict)
                and int(resource.get("connection", -1)) == int(identifier)
            ):
                streams.pop(stream, None)
            else:
                resource = None

            queued = []
            queuedresources = win.get("_video_queues", {}).get(stream, [])
            remaining = []
            for pending in queuedresources if isinstance(queuedresources, list) else []:
                if int(pending.get("connection", -1)) == int(identifier):
                    queued.append(pending)
                else:
                    remaining.append(pending)
            if remaining:
                win.get("_video_queues", {})[stream] = remaining
            else:
                win.get("_video_queues", {}).pop(stream, None)

            if isinstance(resource, dict) and int(resource.get("handle", 0)) > 0:
                try:
                    videodestroyresource(resource, wait=True)
                except Exception:
                    pass

            for pending in queued if isinstance(queued, list) else []:
                try:
                    videodestroyresource(pending, wait=True)
                except Exception:
                    pass

            win["_gpu_generation"] = int(win.get("_gpu_generation", 0)) + 1
            fulldamage(win)

    configuration = state.pop("presentation", None)
    if isinstance(configuration, dict):
        target = int(configuration.get("retained_handle", 0) or 0)
        if target:
            try:
                gputargetdestroy(target)
            except Exception:
                pass

    for win in list(windows.values()):
        streams = win.get("_video_streams", {})

        for stream, resource in list(streams.items()):
            if int(resource.get("connection", -1)) != int(identifier):
                continue

            streams.pop(stream, None)

            try:
                videodestroyresource(resource, wait=True)
            except Exception:
                pass

            win["_gpu_generation"] = int(win.get("_gpu_generation", 0)) + 1
            fulldamage(win)

        queues = win.get("_video_queues", {})

        for stream, resources in list(queues.items()):
            remaining = []

            for resource in resources if isinstance(resources, list) else []:
                if int(resource.get("connection", -1)) != int(identifier):
                    remaining.append(resource)
                    continue

                try:
                    videodestroyresource(resource, wait=True)
                except Exception:
                    pass

            if remaining:
                queues[stream] = remaining
            else:
                queues.pop(stream, None)

    for resource in list(VIDEORETIRED):
        if int(resource.get("connection", -1)) != int(identifier):
            continue

        VIDEORETIRED.remove(resource)

        try:
            videodestroyresource(resource, wait=True)
        except Exception:
            pass

    # A blocked SCM_RIGHTS response remains owned by WindowServer until it is
    # sent. Closing a failed client must close those queued descriptors too.
    for queued in state.get("out", []):
        if not isinstance(queued, dict):
            continue
        for descriptor in queued.get("fds", []):
            try:
                os.close(int(descriptor))
            except Exception:
                pass
    state["out"] = []

    try:
        sel.unregister(state["sock"])
    except Exception:
        pass

    try:
        state["sock"].close()
    except Exception:
        pass

    closeprocessidentity(state.get("identity"))

    log(f"video client {identifier} dropped ({reason})")


def videoframedamage(win, stream):

    if str(win.get("_presentation_stream", "")) == str(stream):
        graphicsmanageddamage(win, None)
        VIDEOTELEMETRY["full_damage_frames"] += 1
        return False

    regions = []

    for command in win.get("gpu_commands", []):

        if (
            not isinstance(command, dict)
            or str(command.get("kind", "")) != "video"
            or str(command.get("stream", "")) != str(stream)
        ):
            continue

        if command.get("parent") or abs(float(command.get("rotation", 0.0))) > 0.0001:
            regions = []
            break

        try:
            rect = [int(value) for value in command.get("rect", [])]
            clip = [int(value) for value in command.get(
                "clip",
                [0, 0, int(win.get("w", 0)), int(win.get("h", 0))],
            )]

            if len(rect) != 4 or len(clip) != 4:
                regions = []
                break

            region = list(rectintersect(*rect, *clip))

            if region[2] > 0 and region[3] > 0:
                regions.append(region)

        except Exception:
            regions = []
            break

    if regions:
        graphicsmanageddamage(win, regions)
        VIDEOTELEMETRY["partial_damage_frames"] += 1
        return True

    graphicsmanageddamage(win, None)
    VIDEOTELEMETRY["full_damage_frames"] += 1
    return False


def handlevideoframe(state, descriptor, fds):

    authorization = state.get("authorization")

    if not isinstance(authorization, dict):
        raise ValueError("video connection is not authorised")

    wid = int(authorization["wid"])
    stream = str(authorization["stream"])

    if wid not in windows or int(windows[wid].get("cid", -1)) != int(authorization["cid"]):
        raise ValueError("video window no longer exists")

    frame = int(descriptor.get("frame", 0))
    if frame < 1:
        raise ValueError("video frame id is invalid")

    win = windows[wid]
    previous = win.setdefault("_video_streams", {}).get(stream)
    queueframes = win.setdefault("_video_queues", {}).setdefault(stream, [])
    latest = queueframes[-1] if queueframes else previous

    if isinstance(latest, dict) and frame <= int(latest.get("frame", 0)):
        VIDEOTELEMETRY["drops"] += 1
        videorelease(state["id"], frame)
        return

    descriptor = dict(descriptor)
    descriptor["stream"] = stream
    handle = gpuvideosurfacecreate(descriptor, fds)
    resource = {
        "handle": int(handle),
        "frame": frame,
        "pts_ns": int(descriptor.get("pts_ns", 0)),
        "connection": int(state["id"]),
        "width": int(descriptor.get("width", 0)),
        "height": int(descriptor.get("height", 0)),
        "coded_width": int(descriptor.get("coded_width", descriptor.get("width", 0))),
        "coded_height": int(descriptor.get("coded_height", descriptor.get("height", 0))),
        "bit_depth": int(descriptor.get("bit_depth", 0)),
        "export_mode": str(descriptor.get("export_mode", "composed")),
        "gpu_scaled": bool(descriptor.get("gpu_scaled", False)),
        "presented": False,
    }

    queued = (
        isinstance(previous, dict)
        and int(previous.get("handle", 0)) > 0
        and not bool(previous.get("presented", False))
    )

    if queued:
        if len(queueframes) >= VIDEOMAXINFLIGHT - 1:
            videodestroyresource(resource, wait=True)
            videoevent(
                resource.get("connection", 0),
                {
                    "op": "dropped",
                    "frame": int(resource.get("frame", 0)),
                    "pts_ns": int(resource.get("pts_ns", 0)),
                    "reason": "presentation-queue-full",
                },
            )
            videorelease(resource.get("connection", 0), resource.get("frame", 0))
            VIDEOTELEMETRY["drops"] += 1
            return

        queueframes.append(resource)
    else:
        win["_video_streams"][stream] = resource

        if isinstance(previous, dict):
            videoretire(previous, wid)

        win["_gpu_generation"] = int(win.get("_gpu_generation", 0)) + 1
        videoframedamage(win, stream)

    VIDEOTELEMETRY["frames"] += 1
    if len(descriptor.get("layers", [])) == 2:
        VIDEOTELEMETRY["planar_frames"] += 1
    else:
        VIDEOTELEMETRY["composed_frames"] += 1
    if bool(descriptor.get("gpu_scaled", False)):
        VIDEOTELEMETRY["gpu_scaled_frames"] += 1
    else:
        VIDEOTELEMETRY["native_resolution_frames"] += 1
    VIDEOTELEMETRY["maximum_active_surfaces"] = max(
        int(VIDEOTELEMETRY["maximum_active_surfaces"]),
        sum(
            1
            for current in windows.values()
            for surface in current.get("_video_streams", {}).values()
            if int(surface.get("handle", 0)) > 0
        ) + sum(
            1
            for current in windows.values()
            for resources in current.get("_video_queues", {}).values()
            for surface in resources if isinstance(resources, list)
            if int(surface.get("handle", 0)) > 0
        ),
    )


def _presentationauthorization(state):

    authorization = state.get("authorization")

    if (
        not isinstance(authorization, dict)
        or str(authorization.get("surface_type", "")) != "presentation"
    ):
        raise PermissionError("RGB DMA-BUF transport is restricted to Chromium presentation")

    wid = int(authorization["wid"])
    win = windows.get(wid)

    if win is None or int(win.get("cid", -1)) != int(authorization["cid"]):
        raise ValueError("presentation window no longer exists")

    return authorization, win, wid, str(authorization["stream"])


def _presentationrelease(resource, dropped=None):

    if not isinstance(resource, dict):
        return False

    handle = int(resource.get("handle", 0) or 0)
    frame = int(resource.get("frame", 0) or 0)
    generation = int(resource.get("generation", 0) or 0)
    connection = int(resource.get("connection", 0) or 0)

    if dropped and frame > 0:
        videoevent(connection, {
            "op": "dropped",
            "generation": generation,
            "frame": frame,
            "reason": str(dropped),
        })

    if handle > 0:
        gpupresentationbufferrelease(handle)
        resource["handle"] = 0

    resource["ready"] = False

    if frame > 0:
        resource["frame"] = 0
        videorelease(connection, frame, generation=generation)

    return True


def clearpresentation(state, requested_generation=None, acknowledge=True):

    authorization, win, wid, stream = _presentationauthorization(state)
    configuration = state.get("presentation")
    generation = int(requested_generation or 0)

    if isinstance(configuration, dict):
        activegeneration = int(configuration.get("generation", 0))

        if generation and generation != activegeneration:
            if generation < activegeneration:
                if acknowledge:
                    videoevent(state["id"], {
                        "op": "cleared",
                        "generation": generation,
                    })
                return True
            raise ValueError("presentation clear names a future generation")

        generation = activegeneration
        current = win.get("_video_streams", {}).pop(stream, None)
        queued = win.get("_video_queues", {}).pop(stream, [])

        if (
            isinstance(current, dict)
            and int(current.get("connection", -1)) == int(state["id"])
        ):
            _presentationrelease(current, dropped="generation-cleared")

        for pending in queued if isinstance(queued, list) else []:
            if int(pending.get("connection", -1)) == int(state["id"]):
                _presentationrelease(pending, dropped="generation-cleared")

        target = int(configuration.get("retained_handle", 0) or 0)
        if target:
            gputargetdestroy(target)

        state["presentation"] = None
        state["presentation_last_generation"] = max(
            int(state.get("presentation_last_generation", 0)),
            generation,
        )
        win["_gpu_generation"] = int(win.get("_gpu_generation", 0)) + 1
        fulldamage(win)
        graphicslog(
            f"> graphics Chromium RGB DMA-BUF generation cleared "
            f"window={wid} generation={generation}"
        )

    if acknowledge:
        videoevent(state["id"], {
            "op": "cleared",
            "generation": generation,
        })

    return True


def handlepresentationconfigure(state, descriptor):

    authorization, win, wid, stream = _presentationauthorization(state)

    if not gpupresentationbufferavailable():
        raise RuntimeError("OpenGL RGB DMA-BUF presentation import is unavailable")

    generation = int(descriptor.get("generation", 0))
    width = int(descriptor.get("width", 0))
    height = int(descriptor.get("height", 0))
    queue_depth = int(descriptor.get("queue_depth", 0))
    fourcc = int(descriptor.get("fourcc", 0))

    activeconfiguration = state.get("presentation")
    minimumgeneration = max(
        int(state.get("presentation_last_generation", 0)),
        int(activeconfiguration.get("generation", 0))
        if isinstance(activeconfiguration, dict)
        else 0,
    )

    if generation <= minimumgeneration:
        raise ValueError("presentation configuration generation is not newer")

    if (
        str(descriptor.get("transport", "")) != "rgb-gbm-dmabuf-v1"
        or str(descriptor.get("sync_mode", "")) != "glfinish-producer-consumer"
        or fourcc != 0x34325258
        or width < 1
        or height < 1
        or width > 8192
        or height > 8192
        or queue_depth != PRESENTATIONMAXINFLIGHT
    ):
        raise ValueError("presentation configuration violates the RGB DMA-BUF contract")

    if isinstance(state.get("presentation"), dict):
        clearpresentation(
            state,
            requested_generation=int(state["presentation"].get("generation", 0)),
            acknowledge=False,
        )

    target = gputargetcreate(
        width,
        height,
        owner=f"chromium-presentation:{wid}:{generation}"[:128],
    )
    state["presentation"] = {
        "generation": generation,
        "width": width,
        "height": height,
        "fourcc": fourcc,
        "queue_depth": queue_depth,
        "last_frame": 0,
        "retained_handle": int(target),
        "retained_ready": False,
    }
    state["presentation_last_generation"] = generation - 1
    videoevent(state["id"], {
        "op": "configured",
        "generation": generation,
        "queue_depth": queue_depth,
        "sync_mode": "glfinish-producer-consumer",
    })
    graphicslog(
        f"> graphics Chromium RGB GBM DMA-BUF consumer ready "
        f"window={wid} generation={generation} size={width}x{height} "
        f"queue_depth={queue_depth} producer_sync=glFinish "
        "consumer_sync=glFinish consumer_release=drm-page-flip "
        "feedback_clock=drm-page-flip native_sync_file=0 retained_gpu_copy=1"
    )


def handlepresentationframe(state, descriptor, fds):

    authorization, win, wid, stream = _presentationauthorization(state)
    configuration = state.get("presentation")

    if not isinstance(configuration, dict):
        raise ValueError("presentation frame arrived before configuration")

    generation = int(descriptor.get("generation", 0))
    frame = int(descriptor.get("frame", 0))
    width = int(descriptor.get("width", 0))
    height = int(descriptor.get("height", 0))
    layers = descriptor.get("layers", [])
    layer = layers[0] if isinstance(layers, list) and len(layers) == 1 else {}

    if (
        generation != int(configuration.get("generation", 0))
        or frame < 1
        or frame <= int(configuration.get("last_frame", 0))
        or width != int(configuration.get("width", 0))
        or height != int(configuration.get("height", 0))
        or int(layer.get("fourcc", 0)) != int(configuration.get("fourcc", 0))
        or str(descriptor.get("transport", "")) != "rgb-gbm-dmabuf-v1"
        or str(descriptor.get("sync_mode", "")) != "glfinish-producer-consumer"
        or str(descriptor.get("origin", "")) != "bottom-left"
    ):
        raise ValueError("presentation frame does not match its active generation")

    streams = win.setdefault("_video_streams", {})
    queues = win.setdefault("_video_queues", {})
    current = streams.get(stream)
    queueframes = queues.setdefault(stream, [])
    active = int(
        isinstance(current, dict)
        and bool(current.get("ready", False))
        and int(current.get("handle", 0)) > 0
    )

    if active + len(queueframes) >= int(configuration.get("queue_depth", 0)):
        videoevent(state["id"], {
            "op": "dropped",
            "generation": generation,
            "frame": frame,
            "reason": "presentation-queue-full",
        })
        videorelease(state["id"], frame, generation=generation)
        VIDEOTELEMETRY["drops"] += 1
        return

    descriptor = dict(descriptor)
    descriptor["stream"] = stream
    handle = gpupresentationbuffercreate(descriptor, fds)
    if not bool(configuration.get("orientation_logged", False)):
        graphicslog(
            f"> graphics Chromium RGB orientation contract "
            f"window={wid} generation={generation} "
            "producer_origin=bottom-left dmabuf_row_order=top-left "
            "retained_target_flip=1"
        )
        configuration["orientation_logged"] = True
    resource = {
        "handle": int(handle),
        "retained_handle": int(configuration["retained_handle"]),
        "retained_owned": False,
        "retained_ready": bool(configuration.get("retained_ready", False)),
        "frame": frame,
        "pts_ns": int(descriptor.get("pts_ns", 0)),
        "connection": int(state["id"]),
        "width": width,
        "height": height,
        "coded_width": width,
        "coded_height": height,
        "export_mode": "composed",
        "presentation_dmabuf": True,
        "generation": generation,
        "presented": False,
        "ready": True,
    }
    configuration["last_frame"] = frame

    if active:
        queueframes.append(resource)
    else:
        streams[stream] = resource
        if isinstance(current, dict):
            videodestroyresource(current, wait=False)
        win["_gpu_generation"] = int(win.get("_gpu_generation", 0)) + 1
        videoframedamage(win, stream)

    VIDEOTELEMETRY["frames"] += 1
    VIDEOTELEMETRY["composed_frames"] += 1


def retainpresentationframe(surface):

    if not isinstance(surface, dict) or not bool(surface.get("presentation_dmabuf", False)):
        return False

    if not bool(surface.get("ready", False)):
        return bool(surface.get("retained_ready", False))

    # A presentation can intersect more than one compositor damage region.
    # Once its retained copy belongs to the pending DRM flip, do not copy the
    # same producer buffer again while waiting for physical presentation.
    if bool(surface.get("presentation_captured", False)):
        return bool(surface.get("retained_ready", False))

    target = int(surface.get("retained_handle", 0) or 0)
    width = int(surface.get("width", 0) or 0)
    height = int(surface.get("height", 0) or 0)

    if target < 1 or width < 1 or height < 1:
        return False

    targetstate = None

    try:
        # The imported DMA-BUF is producer-owned after its release receipt.
        # Copy the complete browser output into a WindowServer-owned GPU target
        # before that ownership transition, then retain the target across KMS
        # page flips and partial repairs without reading a recycled GBM BO.
        targetstate = gputargetbegin(
            target,
            clearcolor=(0, 0, 0, 255),
            clear=True,
        )
        copied = gpudrawvideosurface(
            int(surface.get("handle", 0)),
            0,
            0,
            width=width,
            height=height,
            opacity=1.0,
            clip=[0, 0, width, height],
        )
    finally:

        if targetstate is not None:
            gputargetend(targetstate)

    if not copied:
        return False

    surface["retained_ready"] = True
    state = VIDEOCLIENTS.get(int(surface.get("connection", 0)))
    configuration = state.get("presentation") if isinstance(state, dict) else None
    if (
        isinstance(configuration, dict)
        and int(configuration.get("generation", 0))
        == int(surface.get("generation", 0))
    ):
        configuration["retained_ready"] = True
    return True


def releasepresentationframe(surface):

    if not isinstance(surface, dict) or not bool(surface.get("presentation_dmabuf", False)):
        return False

    frame = int(surface.get("frame", 0))

    if frame < 1 or not bool(surface.get("ready", False)):
        return False

    # This is called at the DRM completion boundary on the normal path.
    # gpupresentationbufferrelease retains the protocol-v1 consumer glFinish
    # as a fail-safe, but by this point the retained copy has already reached
    # scan-out and the finish is no longer a composition-path stall.
    return _presentationrelease(surface)


def capturechromiumpresentation(win, stream, surface):

    global GPUCAPTUREDCHROMIUMPRESENTATIONS

    if (
        not isinstance(win, dict)
        or not isinstance(surface, dict)
        or not bool(surface.get("presentation_dmabuf", False))
        or not bool(surface.get("ready", False))
        or bool(surface.get("presentation_captured", False))
    ):
        return False

    frame = int(surface.get("frame", 0) or 0)
    generation = int(surface.get("generation", 0) or 0)

    if frame < 1 or generation < 1:
        return False

    surface["presentation_captured"] = True
    surface["presented"] = True
    GPUCAPTUREDCHROMIUMPRESENTATIONS.append({
        "wid": int(win.get("id", 0) or 0),
        "stream": str(stream),
        "frame": frame,
        "generation": generation,
        "surface": surface,
    })
    VIDEOTELEMETRY["presentation_receipts_pending"] = (
        len(GPUCAPTUREDCHROMIUMPRESENTATIONS)
        + len(GPUPENDINGCHROMIUMPRESENTATIONS)
    )
    return True


def stagechromiumpresentations():

    global GPUCAPTUREDCHROMIUMPRESENTATIONS
    global GPUPENDINGCHROMIUMPRESENTATIONS

    if not GPUCAPTUREDCHROMIUMPRESENTATIONS:
        return 0

    # The compositor gate admits a new render only after the preceding DRM
    # flip. Therefore all captures staged here belong to the gpuend() that has
    # just submitted one physical presentation.
    GPUPENDINGCHROMIUMPRESENTATIONS.extend(
        GPUCAPTUREDCHROMIUMPRESENTATIONS
    )
    staged = len(GPUCAPTUREDCHROMIUMPRESENTATIONS)
    GPUCAPTUREDCHROMIUMPRESENTATIONS = []
    VIDEOTELEMETRY["presentation_receipts_pending"] = len(
        GPUPENDINGCHROMIUMPRESENTATIONS
    )
    return staged


def cancelcapturedchromiumpresentations(reason):

    global GPUCAPTUREDCHROMIUMPRESENTATIONS

    captured = list(GPUCAPTUREDCHROMIUMPRESENTATIONS)
    GPUCAPTUREDCHROMIUMPRESENTATIONS = []

    for receipt in captured:
        surface = receipt.get("surface")

        if isinstance(surface, dict) and bool(surface.get("ready", False)):
            surface["presentation_captured"] = False
            _presentationrelease(surface, dropped=str(reason))

    VIDEOTELEMETRY["presentation_receipts_pending"] = len(
        GPUPENDINGCHROMIUMPRESENTATIONS
    )
    return len(captured)


def finishchromiumpresentations():

    global GPUPENDINGCHROMIUMPRESENTATIONS

    if kmspresentationpending() or not GPUPENDINGCHROMIUMPRESENTATIONS:
        return 0

    receipts = list(GPUPENDINGCHROMIUMPRESENTATIONS)
    GPUPENDINGCHROMIUMPRESENTATIONS = []
    completed = 0
    presented_ns = time.monotonic_ns()

    for receipt in receipts:
        surface = receipt.get("surface")
        wid = int(receipt.get("wid", 0) or 0)
        stream = str(receipt.get("stream", ""))
        win = windows.get(wid)
        current = (
            win.get("_video_streams", {}).get(stream)
            if isinstance(win, dict)
            else None
        )

        if (
            not isinstance(surface, dict)
            or not bool(surface.get("ready", False))
            or int(surface.get("frame", 0) or 0)
            != int(receipt.get("frame", 0) or 0)
            or int(surface.get("generation", 0) or 0)
            != int(receipt.get("generation", 0) or 0)
        ):
            continue

        surface["presentation_captured"] = False

        if current is not surface:
            _presentationrelease(
                surface,
                dropped="presentation-owner-changed-before-page-flip",
            )
            continue

        videoevent(
            surface.get("connection", 0),
            {
                "op": "presented",
                "generation": int(surface.get("generation", 0)),
                "frame": int(surface.get("frame", 0)),
                "pts_ns": int(surface.get("pts_ns", 0)),
                "presented_ns": presented_ns,
            },
        )
        VIDEOTELEMETRY["presented_frames"] += 1
        VIDEOTELEMETRY["page_flip_presented_frames"] += 1
        releasepresentationframe(surface)
        videopromotepending(win, stream, surface)
        completed += 1

    VIDEOTELEMETRY["presentation_receipts_pending"] = 0
    return completed


def videopromotepending(win, stream, current):

    queueframes = win.get("_video_queues", {}).get(str(stream), [])

    if not isinstance(queueframes, list) or not queueframes:
        return False

    resource = queueframes.pop(0)
    if bool(resource.get("presentation_dmabuf", False)):
        resource["retained_ready"] = bool(current.get("retained_ready", False))
    win.setdefault("_video_streams", {})[str(stream)] = resource
    videoretire(current, win.get("id", 0))
    win["_gpu_generation"] = int(win.get("_gpu_generation", 0)) + 1
    videoframedamage(win, stream)
    return True


def clearvideostream(state, descriptor=None):

    authorization = state.get("authorization")

    if not isinstance(authorization, dict):
        return

    if str(authorization.get("surface_type", "")) == "presentation":
        return clearpresentation(
            state,
            requested_generation=int((descriptor or {}).get("generation", 0)),
            acknowledge=True,
        )

    wid = int(authorization.get("wid", 0))
    stream = str(authorization.get("stream", ""))
    win = windows.get(wid)

    if win is not None:
        resource = win.get("_video_streams", {}).pop(stream, None)
        queued = win.get("_video_queues", {}).pop(stream, [])
        generation = (
            int(resource.get("generation", 0))
            if isinstance(resource, dict)
            else 0
        )

        if isinstance(resource, dict):
            videoretire(resource, wid, wait=True)
            win["_gpu_generation"] = int(win.get("_gpu_generation", 0)) + 1
            fulldamage(win)

        for pending in queued if isinstance(queued, list) else []:
            videoretire(pending, wid, wait=True)

        graphicslog(f"> graphics video stream cleared window={wid}")

    packet = json.dumps({"op": "cleared"}, separators=(",", ":")).encode("utf-8")
    state["out"].append(packet)
    updatevideoevents(state)
    flushvideoclient(state)


def recvvideoclient(state):

    fds = []

    try:
        peeridentity = state.get("identity")
        if not processidentitycurrent(peeridentity):
            raise PermissionError("video peer identity ended")
        if (
            state.get("authorization") is not None
            and not videoauthorizationvalid(
                state.get("authorization"), peeridentity)
        ):
            raise PermissionError("video authorization owner ended")

        data, ancillary, flags, _ = state["sock"].recvmsg(
            VIDEOPACKETLIMIT,
            socket.CMSG_SPACE(VIDEOMAXFDS * array.array("i").itemsize),
        )

        if not data:
            dropvideoclient(state["id"], "closed")
            return

        if flags & (getattr(socket, "MSG_TRUNC", 0) | getattr(socket, "MSG_CTRUNC", 0)):
            raise ValueError("truncated video packet")

        for level, kind, payload in ancillary:
            if level != socket.SOL_SOCKET or kind != socket.SCM_RIGHTS:
                continue

            values = array.array("i")
            usable = len(payload) - (len(payload) % values.itemsize)
            values.frombytes(payload[:usable])
            fds.extend(int(value) for value in values)

        if len(fds) > VIDEOMAXFDS:
            raise ValueError("too many video DMA-BUF handles")

        message = json.loads(data.decode("utf-8"))

        if not isinstance(message, dict):
            raise ValueError("video packet is not an object")

        if state.get("authorization") is None:
            if message.get("op") != "auth" or fds:
                raise ValueError("first video packet must authorise the connection")

            token = str(message.get("token", ""))
            authorization = VIDEOAUTH.get(token)

            if (
                not isinstance(authorization, dict)
                or time.monotonic() > float(authorization.get("expires", 0.0))
            ):
                raise ValueError("video authorisation expired or is invalid")

            if not videoauthorizationvalid(authorization, peeridentity):
                raise PermissionError("video peer does not match the live owner")

            if not bool(authorization.get("reusable", False)):
                VIDEOAUTH.pop(token, None)

            if str(authorization.get("surface_type", "")) == "presentation":
                # One token names one Chromium root presentation owner. A GPU
                # process restart supersedes the old peer for that window and
                # stream so two producers can never share a generation queue.
                superseded = [
                    identifier
                    for identifier, peer in list(VIDEOCLIENTS.items())
                    if int(identifier) != int(state["id"])
                    and isinstance(peer.get("authorization"), dict)
                    and int(peer["authorization"].get("wid", -1))
                    == int(authorization.get("wid", -2))
                    and str(peer["authorization"].get("stream", ""))
                    == str(authorization.get("stream", ""))
                    and str(peer["authorization"].get("surface_type", ""))
                    == "presentation"
                ]
                for identifier in superseded:
                    dropvideoclient(identifier, "superseded presentation connection")

            state["authorization"] = authorization
            authorizedstream = str(authorization.get("stream", ""))[:128]
            graphicslog(
                "> graphics video connection authorized "
                f"connection={int(state.get('id', 0))} "
                f"window={authorization.get('wid')} "
                f"stream_class="
                f"{'chromium-presentation' if authorizedstream == '__t1os_chromium_presentation__' else 'video'} "
                f"stream_length={len(authorizedstream)} "
                f"surface_type="
                f"{authorization.get('surface_type', 'unknown')}"
            )
            videoevent(state["id"], {"op": "authorized"})
            return

        if message.get("op") == "clear" and not fds:
            clearvideostream(state, message)
            return

        if message.get("op") == "configure" and not fds:
            handlepresentationconfigure(state, message)
            return

        if (
            message.get("op") == "frame"
            and fds
            and str(state.get("authorization", {}).get("surface_type", ""))
            == "presentation"
        ):
            handlepresentationframe(state, message, fds)
            return

        if message.get("op") != "frame" or not fds:
            raise ValueError("video connection accepts only configured DMA-BUF frames")

        handlevideoframe(state, message, fds)
    except BlockingIOError:
        return
    except Exception as e:
        VIDEOTELEMETRY["protocol_errors"] += 1

        operation = "unknown"
        if isinstance(locals().get("message"), dict):
            operation = str(message.get("op", "unknown"))
        graphicslog(
            f"> graphics video protocol error connection={int(state.get('id', 0))} "
            f"operation={operation} detail={e}"
        )

        try:
            if isinstance(locals().get("message"), dict) and int(message.get("frame", 0)) > 0:
                generation = message.get("generation")
                videorelease(
                    state["id"],
                    int(message["frame"]),
                    generation=int(generation) if generation is not None else None,
                )
        except Exception:
            pass

        # Return the compositor's exact import failure before closing the
        # transport. Development logs must distinguish malformed descriptors,
        # modifier negotiation, and an EGL driver rejection from a generic
        # peer close.
        try:
            videoevent(state["id"], {
                "op": "error",
                "detail": str(e),
            })
        except Exception:
            pass

        dropvideoclient(state["id"], f"protocol error {e}")
    finally:
        for descriptor in fds:
            try:
                os.close(descriptor)
            except Exception:
                pass


def acceptclient(srv):

    try:

        # accept new client
        conn, _ = srv.accept()

        if len(clients) >= CLIENTLIMIT:
            conn.close()
            log("rejected client at compositor connection limit")
            return None

        # Every client gets an immutable kernel-derived process identity. JSON
        # PID/path/role claims are never authority. Missing credentials or a
        # process-generation race are fail-closed.
        identity = socketpeeridentity(conn)
        if not identity:
            conn.close()
            log("rejected client without an authenticated peer identity")
            return None

        peerpid = int(identity["pid"])
        peeruid = int(identity["uid"])
        peergid = int(identity["gid"])

        # set nonblocking
        conn.setblocking(False)

        # create client id and state
        cid = random.randint(100000, 999999)

        state = {
            "kind": "client",
            "id": cid,
            "sock": conn,
            "inbuf": b"",
            "outbuf": bytearray(),
            "pending_motion": None,
            "motion_next_at": 0.0,
            "events": selectors.EVENT_READ,
            "windows": [],
            "subs": set(),
            "integration": "",
            "peer_pid": peerpid,
            "peer_uid": peeruid,
            "peer_gid": peergid,
            "identity": identity,
            "capabilities": peercapabilities(identity),
        }

        # register for read only at first
        sel.register(conn, selectors.EVENT_READ, data=state)

        # store
        clients[cid] = state

        if str(identity.get("domain", "")) in ("lockscreen", "startup"):
            graphicslog(
                f"> graphics privileged surface peer accepted cid={cid} "
                f"pid={peerpid} uid={peeruid} gid={peergid} "
                f"domain={identity.get('domain')} "
                f"start={identity.get('starttime')} "
                f"capabilities={','.join(sorted(state['capabilities']))}"
            )

        # note
        log(f"client {cid} connected")
        return cid

    except BlockingIOError:
        return None

    except Exception as e:

        # accept error
        log(f"accept error {e}")
        closeprocessidentity(locals().get("identity"))
        try:
            conn.close()
        except Exception:
            pass
        return None


def appendclientoutput(cid, line):

    global CLIENTOUTBUFPEAK, CLIENTOUTPUTDROPS

    state = clients.get(cid)

    if state is None:
        return False

    outbuf = state.get("outbuf")

    if not isinstance(outbuf, bytearray):
        outbuf = bytearray(outbuf or b"")
        state["outbuf"] = outbuf

    if len(outbuf) + len(line) > int(CLIENTOUTBUFLIMIT):
        CLIENTOUTPUTDROPS += 1
        dropclient(cid, "output queue limit reached")
        return False

    outbuf.extend(line)
    CLIENTOUTBUFPEAK = max(int(CLIENTOUTBUFPEAK), len(outbuf))
    return True


def materializeclientmotion(cid, force=False):

    state = clients.get(cid)

    if state is None:
        return False

    line = state.get("pending_motion")

    if line is None:
        return False

    now = time.monotonic()

    if not force:

        if state.get("outbuf"):
            return False

        if now < float(state.get("motion_next_at", 0.0)):
            return False

    state["pending_motion"] = None

    if not appendclientoutput(cid, line):
        return False

    state = clients.get(cid)

    if state is not None:
        state["motion_next_at"] = now + float(CLIENTPOINTERINTERVAL)

    return True


def flushclientmotions():

    for cid in list(clients):

        if materializeclientmotion(cid):
            updateclientevents(cid)
            flushclient(cid)


def sendjson(cid, obj):

    global CLIENTPOINTERCOALESCED

    try:

        # Encode newline-delimited JSON. Pointer motion is replaceable state;
        # all other records are loss-sensitive ordered transitions.
        line = (json.dumps(obj, separators=(",", ":")) + "\n").encode("utf-8")
        state = clients[cid]

        if str(obj.get("op", "")) == "POINTER_MOTION":

            if state.get("pending_motion") is not None:
                CLIENTPOINTERCOALESCED += 1

            state["pending_motion"] = line
            materializeclientmotion(cid)

        else:

            # The newest pointer position must precede the click/key/control
            # record that follows it, even when this client is backpressured.
            materializeclientmotion(cid, force=True)

            if cid not in clients or not appendclientoutput(cid, line):
                return

        # Watch only materialised bytes. A not-yet-due pointer sample is
        # released by the compositor pulse instead of making a writable Unix
        # socket spin the selector.
        updateclientevents(cid)

        # Opportunistic immediate flush.
        flushclient(cid)

    except KeyError:

        # unknown client
        return

    except Exception as e:

        # queueing error
        dropclient(cid, f"send queue error {e}")


def recvlines(cid):

    lines = []

    try:

        # receive bytes
        data = clients[cid]["sock"].recv(4096)

        # if zero bytes then closed
        if not data:
            dropclient(cid, "closed")
            return lines

        # append to buffer
        clients[cid]["inbuf"] += data

        if len(clients[cid]["inbuf"]) > CLIENTINBUFLIMIT:
            dropclient(cid, "input queue limit reached")
            return lines

        # split on newline boundaries
        while True:

            idx = clients[cid]["inbuf"].find(b"\n")

            if idx == -1:
                break

            # extract one line without newline
            raw = clients[cid]["inbuf"][:idx]
            clients[cid]["inbuf"] = clients[cid]["inbuf"][idx + 1:]


            # decode text
            txt = raw.decode("utf-8", errors="replace")

            # ignore empty keepalives
            if txt:
                lines.append(txt)

    except BlockingIOError:
        pass

    except ConnectionResetError:
        dropclient(cid, "reset")

    except Exception as e:
        dropclient(cid, f"recv error {e}")

    return lines


def dropclient(cid, reason):

    try:
        pickerclientgone(cid)

        for token, authorization in list(VIDEOAUTH.items()):
            if int(authorization.get("cid", -1)) == int(cid):
                VIDEOAUTH.pop(token, None)

        # close windows owned by client
        if cid in clients:
            for wid in list(clients[cid]["windows"]):
                destroywindow(wid, note=f"client {cid} gone")

        # unregister selector
        if cid in clients:
            sel.unregister(clients[cid]["sock"])
        if cid in clients:
            clients[cid]["sock"].close()
        if cid in clients:
            closeprocessidentity(clients[cid].get("identity"))
        if cid in clients:
            del clients[cid]

        try:

            # remove from desktop client set if present
            if cid in DESKTOPCLIENTS:
                DESKTOPCLIENTS.remove(cid)

        except Exception as e:

            # desktop client removal error
            log(f"desktop client remove error {e}")

        # client drop
        log(f"client {cid} dropped ({reason})")

    except Exception as e:

        # error during drop
        log(f"drop client error {e}")


def updateclientevents(cid):

    try:

        # always read; add write if pending bytes
        mask = selectors.EVENT_READ

        if clients[cid]["outbuf"]:
            mask |= selectors.EVENT_WRITE

        # modify selector registration
        sel.modify(clients[cid]["sock"], mask, data=clients[cid])

        # stash mask for debugging
        clients[cid]["events"] = mask

    except KeyError:
        pass

    except Exception:
        pass


def flushclient(cid):

    try:

        for _ in range(2):

            if cid not in clients:
                return

            state = clients[cid]
            outbuf = state.get("outbuf")

            if not isinstance(outbuf, bytearray):
                outbuf = bytearray(outbuf or b"")
                state["outbuf"] = outbuf

            if not outbuf:

                materializeclientmotion(cid)

                if cid not in clients:
                    return

                outbuf = clients[cid]["outbuf"]

                if not outbuf:
                    updateclientevents(cid)
                    return

            sent = clients[cid]["sock"].send(outbuf)

            if sent == 0:
                dropclient(cid, "zero-byte socket write")
                return

            del outbuf[:sent]

            if outbuf:
                break

        if cid in clients:
            updateclientevents(cid)

    except BlockingIOError:
        # socket would block; keep bytes queued
        pass

    except BrokenPipeError:
        dropclient(cid, "broken pipe")

    except Exception as e:
        dropclient(cid, f"flush error {e}")


def drain(seconds):

    out = []


    end = time.time() + seconds

    while time.time() < end:

        got = recvlines(end)

        if got:
            out.extend(got)

        else:
            time.sleep(0.01)

    return [json.loads(x) for x in out if x.strip()]


def waitforop(opname, seconds):

    end = time.time() + seconds
    seen = []


    while time.time() < end:

        for ln in recvlines(end):

            log(f"<<< {ln}")

            msg = json.loads(ln)
            seen.append(msg)

            if msg.get("op") == opname:
                return msg, seen

        time.sleep(0.01)

    return None, seen


def modalwindow(win):

    return bool(win and (win.get("standard_dialog") or win.get("modal_child")))


def pickerfilterrequest(source):

    filters = []

    if not isinstance(source, list):
        source = []

    for index, entry in enumerate(source[:PICKERMAXFILTERS]):

        if not isinstance(entry, dict):
            continue

        identifier = str(entry.get("id", f"filter{index}"))[:64]
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", identifier):
            identifier = f"filter{index}"

        label = str(entry.get("label", identifier)).strip()[:80] or identifier
        extensions = []
        rawextensions = entry.get("extensions", [])

        if isinstance(rawextensions, list):
            for raw in rawextensions[:PICKERMAXEXTENSIONS]:
                value = str(raw).strip().lower()
                if value == "*":
                    extensions = ["*"]
                    break
                if not value.startswith("."):
                    value = "." + value
                if re.fullmatch(r"\.[A-Za-z0-9][A-Za-z0-9._+-]{0,31}", value):
                    extensions.append(value)

        if extensions:
            filters.append({
                "id": identifier,
                "label": label,
                "extensions": list(dict.fromkeys(extensions)),
            })

    if not filters:
        filters = [{"id": "all", "label": "all files", "extensions": ["*"]}]

    return filters


def pickerpathwritable(path):

    try:
        target = os.path.abspath(str(path))
        if not os.path.isdir(target) or not os.access(target, os.W_OK):
            return False
        readonly = getattr(os, "ST_RDONLY", 1)
        return not bool(os.statvfs(target).f_flag & readonly)
    except Exception:
        return False


def pickerfilematches(path, filters):

    extension = os.path.splitext(str(path))[1].lower()

    for entry in filters:
        values = entry.get("extensions", [])
        if "*" in values or extension in values:
            return True

    return False


def pickerstopprocess(session):

    process = session.get("process") if isinstance(session, dict) else None

    if process is None:
        if isinstance(session, dict):
            closeprocessidentity(session.get("expected_identity"))
            session["expected_identity"] = None
        return

    try:
        running = process.poll() is None
    except Exception:
        running = False

    if running:
        try:
            process.terminate()
        except Exception:
            pass

    try:
        process.wait(timeout=0.25)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except Exception:
            pass

        try:
            process.wait(timeout=0.25)
        except Exception:
            pass
    except Exception:
        pass

    session["process"] = None
    closeprocessidentity(session.get("expected_identity"))
    session["expected_identity"] = None


def createpicker(cid, req):

    parent = None
    requestid = None

    try:
        parent = int(req.get("parent", 0))
        if parent not in windows or windows[parent].get("cid") != cid:
            sendjson(cid, {"op": "ERROR", "code": "picker_parent_invalid"})
            return None

        if modaldialogfor(parent) in windows:
            raise ValueError("parent already has a modal child")
        if any(
            not session.get("terminal")
            and session.get("owner_cid") == cid
            and session.get("parent") == parent
            for session in PICKERSESSIONS.values()
        ):
            raise ValueError("parent already has a pending picker")

        mode = str(req.get("mode", "")).strip().lower()
        if mode not in PICKERMODES:
            raise ValueError("unsupported picker mode")

        titledefaults = {
            "open_file": "open file",
            "select_tier": "select tier",
            "save_location": "select save location",
            "save_as": "save as",
        }
        title = str(req.get("title", titledefaults[mode])).strip()[:128] or titledefaults[mode]
        initialpath = str(req.get("initial_path", "")).strip()[:4096]
        suggested = str(req.get("suggested_name", ""))[:255]
        defaultextension = str(req.get("default_extension", "")).strip().lower()[:32]
        if defaultextension and not defaultextension.startswith("."):
            defaultextension = "." + defaultextension
        if defaultextension and not re.fullmatch(r"\.[A-Za-z0-9][A-Za-z0-9._+-]{0,31}", defaultextension):
            defaultextension = ""

        requestid = f"picker-{random.getrandbits(96):024x}"
        config = {
            "version": PICKERVERSION,
            "request_id": requestid,
            "mode": mode,
            "title": title,
            "initial_path": initialpath,
            "suggested_name": suggested,
            "default_extension": defaultextension,
            "allow_multiple": bool(req.get("allow_multiple", False)) if mode == "open_file" else False,
            "filters": pickerfilterrequest(req.get("filters", [])),
        }

        arraylog = softwarelogpath(PICKERARRAYPATH)
        process = popenisolated(
            [PICKERARRAYPATH, "--picker-session", requestid],
            softwarepath=PICKERARRAYPATH,
            logpath=arraylog,
            security_profile="picker",
            preexec_fn=dropdesktopidentity,
        )
        expectedidentity = waitforprocessidentity(
            int(process.pid), "picker", timeout=1.0)
        if not expectedidentity:
            try:
                process.terminate()
            except Exception:
                pass
            closeprocessidentity(expectedidentity)
            raise RuntimeError("could not authenticate launched Array picker")

        PICKERSESSIONS[requestid] = {
            "request_id": requestid,
            "owner_cid": cid,
            "parent": parent,
            "expected_pid": int(process.pid),
            "expected_identity": expectedidentity,
            "array_cid": None,
            "winid": None,
            "config": config,
            "terminal": False,
            "created_at": time.monotonic(),
            "process": process,
        }

        operationsregisterpid(
            int(process.pid), "array picker", PICKERARRAYPATH, arraylog,
            "session", "front", "starting",
        )

        sendjson(cid, {
            "op": "PICKER_CREATED",
            "request_id": requestid,
            "parent": parent,
            "mode": mode,
        })
        return requestid

    except Exception as error:
        if requestid:
            PICKERSESSIONS.pop(requestid, None)
        sendjson(cid, {
            "op": "ERROR",
            "code": "picker_create_failed",
            "detail": str(error),
        })
        log(f"picker_create_failed cid={cid} parent={parent} {error}")
        return None


def pickerattach(cid, req):

    requestid = str(req.get("request_id", ""))
    session = PICKERSESSIONS.get(requestid)

    if not session or session.get("terminal"):
        sendjson(cid, {"op": "ERROR", "code": "picker_session_invalid"})
        return False

    try:
        expected = int(session.get("expected_pid", 0))
        peerpid = int(clients.get(cid, {}).get("peer_pid", 0))
    except Exception:
        expected = 0
        peerpid = 0

    peeridentity = clients.get(cid, {}).get("identity")
    expectedidentity = session.get("expected_identity")
    if (
        expected <= 0
        or peerpid != expected
        or str((peeridentity or {}).get("domain", "")) != "picker"
        or not sameprocessidentity(peeridentity, expectedidentity)
        or not processidentitycurrent(expectedidentity)
    ):
        sendjson(cid, {"op": "ERROR", "code": "picker_attach_denied"})
        log(f"picker attach denied request={requestid} expected={expected} peer={peerpid}")
        return False

    if session.get("array_cid") not in (None, cid):
        sendjson(cid, {"op": "ERROR", "code": "picker_already_attached"})
        return False

    session["array_cid"] = cid
    clients[cid]["picker_session"] = requestid
    sendjson(cid, {"op": "PICKER_CONFIG", **dict(session["config"])})
    return True


def pickerfinish(cid, req):

    requestid = str(req.get("request_id", ""))
    session = PICKERSESSIONS.get(requestid)

    if not session or session.get("terminal") or session.get("array_cid") != cid:
        sendjson(cid, {"op": "ERROR", "code": "picker_finish_denied"})
        return False

    status = str(req.get("status", "cancelled")).lower()
    if status not in ("accepted", "cancelled"):
        sendjson(cid, {"op": "ERROR", "code": "picker_result_invalid"})
        return False

    config = session["config"]
    mode = config["mode"]
    paths = []
    locations = []

    if status == "accepted":
        rawpaths = req.get("paths", [])
        if not isinstance(rawpaths, list):
            rawpaths = []
        limit = 32 if mode == "open_file" and config.get("allow_multiple") else 1

        for raw in rawpaths[:limit]:
            value = str(raw)
            if not value or "\x00" in value or len(value) > 4096:
                continue
            paths.append(os.path.abspath(os.path.normpath(value)))

        valid = bool(paths)

        # The authenticated Picker process has already performed filesystem and
        # writability checks in its own uid/domain.  WindowServer must not repeat
        # those probes from the compositor domain: private user tiers can be
        # inaccessible there even though the picker and requesting application
        # can legitimately use them.  The recipient remains responsible for
        # opening or creating the returned path under its own LSM authority.
        if mode == "open_file":
            valid = valid and all(
                pickerfilematches(path, config["filters"])
                for path in paths
            )
        elif mode == "select_tier":
            valid = len(paths) == 1
        elif mode == "save_location":
            valid = len(paths) == 1
        elif mode == "save_as":
            valid = (
                len(paths) == 1
                and os.path.basename(paths[0]) not in ("", ".", "..")
            )

        if not valid:
            sendjson(cid, {"op": "ERROR", "code": "picker_result_invalid"})
            return False

        rawlocations = req.get("locations", [])
        if isinstance(rawlocations, list):
            locations = [str(value)[:4096] for value in rawlocations[:len(paths)]]
        while len(locations) < len(paths):
            locations.append(paths[len(locations)])

    ownercid = session.get("owner_cid")
    response = {
        "op": "PICKER_RESULT",
        "request_id": requestid,
        "parent": session.get("parent"),
        "mode": mode,
        "status": status,
        "paths": paths,
        "locations": locations,
        "overwrite_approved": bool(req.get("overwrite_approved", False)),
    }

    session["terminal"] = True
    if ownercid in clients:
        sendjson(ownercid, response)

    pickerwid = session.get("winid")
    if pickerwid in windows:
        destroywindow(pickerwid, note="picker finished")
    else:
        PICKERSESSIONS.pop(requestid, None)
        pickerstopprocess(session)

    return True


def pickercancelwindow(wid):

    for requestid, session in list(PICKERSESSIONS.items()):
        if session.get("winid") != wid:
            continue

        if not session.get("terminal"):
            ownercid = session.get("owner_cid")
            if ownercid in clients:
                sendjson(ownercid, {
                    "op": "PICKER_RESULT",
                    "request_id": requestid,
                    "parent": session.get("parent"),
                    "mode": session.get("config", {}).get("mode"),
                    "status": "cancelled",
                    "paths": [],
                    "locations": [],
                    "overwrite_approved": False,
                })

        PICKERSESSIONS.pop(requestid, None)
        pickerstopprocess(session)
        return


def pickerclientgone(cid):

    for requestid, session in list(PICKERSESSIONS.items()):
        if session.get("owner_cid") == cid:
            session["terminal"] = True
            pickerwid = session.get("winid")
            if pickerwid in windows:
                destroywindow(pickerwid, note="picker owner gone")
            else:
                PICKERSESSIONS.pop(requestid, None)
                pickerstopprocess(session)
            continue

        if session.get("array_cid") == cid and not session.get("terminal"):
            ownercid = session.get("owner_cid")
            if ownercid in clients:
                sendjson(ownercid, {
                    "op": "PICKER_RESULT",
                    "request_id": requestid,
                    "parent": session.get("parent"),
                    "mode": session.get("config", {}).get("mode"),
                    "status": "cancelled",
                    "paths": [],
                    "locations": [],
                    "overwrite_approved": False,
                })
            session["terminal"] = True
            if session.get("winid") not in windows:
                PICKERSESSIONS.pop(requestid, None)
                pickerstopprocess(session)


def pickerpulse():

    global PICKERLASTPULSE

    now = time.monotonic()
    if now - PICKERLASTPULSE < 0.5:
        return
    PICKERLASTPULSE = now

    for requestid, session in list(PICKERSESSIONS.items()):
        if session.get("terminal"):
            continue

        ownercid = session.get("owner_cid")
        parent = session.get("parent")
        process = session.get("process")
        failed = ownercid not in clients or parent not in windows

        try:
            failed = failed or (process is not None and process.poll() is not None)
        except Exception:
            pass

        if session.get("winid") is None:
            try:
                failed = failed or now - float(session.get("created_at", now)) > PICKERSTARTTIMEOUT
            except Exception:
                failed = True

        if not failed:
            continue

        if ownercid in clients:
            sendjson(ownercid, {
                "op": "PICKER_RESULT",
                "request_id": requestid,
                "parent": parent,
                "mode": session.get("config", {}).get("mode"),
                "status": "cancelled",
                "paths": [],
                "locations": [],
                "overwrite_approved": False,
            })

        session["terminal"] = True
        pickerwid = session.get("winid")
        if pickerwid in windows:
            destroywindow(pickerwid, note="picker unavailable")
        else:
            PICKERSESSIONS.pop(requestid, None)
            pickerstopprocess(session)


def createwindow(cid, req, responseop="WINDOW_CREATED", internal=False):

    bufpath = None
    try:

        # parse parameters
        identity = clients.get(cid, {}).get("identity")
        w = max(1, min(int(SCREENW), int(req.get("w", 640))))
        h = max(1, min(int(SCREENH), int(req.get("h", 480))))
        if len(clients.get(cid, {}).get("windows", [])) >= CLIENTWINDOWLIMIT:
            raise PermissionError("client window limit reached")
        if not windowbufferallocationpermitted(cid, w * h * 4):
            raise PermissionError("client window-buffer budget exceeded")
        title = str(req.get("title", "window"))
        role = str(req.get("role", ""))
        current = str(req.get("current", "")).strip()[:128]
        path = str(req.get("path", ""))
        decoration = str(req.get("decoration", "server")).lower()
        # Underscore compositor state is never client authority. Only the
        # server's own dialog constructor may create a protected server-drawn
        # surface.
        standard_dialog = bool(internal and req.get("_standard_dialog", False))
        restore_size = bool(req.get("restore_size", True))
        pickerid = str(req.get("picker_session", ""))
        pickersession = PICKERSESSIONS.get(pickerid) if pickerid else None
        modal_child = False
        modal_parent = None

        if pickerid:
            if (
                not pickersession
                or pickersession.get("terminal")
                or pickersession.get("array_cid") != cid
                or pickersession.get("winid") is not None
            ):
                raise ValueError("invalid picker window session")
            modal_child = True
            modal_parent = int(pickersession.get("parent", 0))
            if modal_parent not in windows:
                raise ValueError("picker parent is no longer available")
            role = "window"
            title = str(pickersession.get("config", {}).get("title", title))[:128]
            path = PICKERARRAYPATH

        if not modal_child:
            if not authorizedwindowrole(cid, role):
                raise PermissionError(f"window role denied: {role or '<empty>'}")
            path = verifiedclientpath(cid)
            if not path:
                raise PermissionError("client executable identity is unavailable")

        if decoration not in ("server", "client") or role != "window":
            decoration = "server"

        try:
            client_chrome_height = int(req.get("client_chrome_height", TITLEH))
        except Exception:
            client_chrome_height = int(TITLEH)

        client_chrome_height = max(BTNWH, min(max(1, h), client_chrome_height))

        try:
            client_chrome_drag_width = max(0, min(w, int(req.get("client_chrome_drag_width", 0))))
        except Exception:
            client_chrome_drag_width = 0

        client_chrome_controls = str(req.get("client_chrome_controls", "default")).lower()

        if (
            decoration != "client"
            or client_chrome_controls != "chromium"
            or str(identity.get("domain", "")) != "chromium"
        ):
            client_chrome_controls = "default"

        drop_types = set()

        for value in req.get("drop_types", []):

            value = vboxdndkind(value)

            if value in ("files", "text", "html", "image"):
                drop_types.add(value)

        # Window ownership always comes from SO_PEERCRED. Client-supplied PIDs
        # are metadata only and cannot redirect lifecycle/kill operations.
        pid = int(identity.get("pid", 0)) if isinstance(identity, dict) else 0

        if pid <= 1:
            raise PermissionError("client process identity is unavailable")

        # honor initial position (default 100,100)
        x = int(req.get("x", 100))

        y = int(req.get("y", 100))

        persistentplacement = None

        if role == "window" and not standard_dialog and not modal_child:
            persistentplacement = persistedwindowplacement(
                persistentwindowattributes(path),
                decoration,
                None if restore_size else [w, h],
            )

        if persistentplacement:
            x, y, w, h = persistentplacement["geometry"]

        if modal_child:
            parentwin = windows[modal_parent]
            x = int(parentwin.get("x", 0)) + (int(parentwin.get("w", w)) - w) // 2
            y = int(parentwin.get("y", 0)) + (int(parentwin.get("h", h)) - h) // 2

        # only independent normal windows participate in auto-placement
        if role == "window" and not standard_dialog and not modal_child:

            # auto-place if client didn't request a real position, or it would overlap
            if persistentplacement:
                pass

            elif wantautoplace(req):

                x, y = nextplace(w, h)

            else:

                if overlapswindow(x, y, w, h):

                    x, y = nextplace(w, h)

        # assign id
        wid = random.randint(1, 2**31 - 1)

        # Use an unguessable group-writable buffer name. Session applications
        # can open the path returned to them, but cannot enumerate BUFBASE.
        bufpath = os.path.join(
            BUFBASE,
            f"{cid}-{wid}-{random.getrandbits(128):032x}.raw",
        )

        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(bufpath, flags, 0o660)
        try:
            os.ftruncate(descriptor, w * h * 4)
            os.fchown(descriptor, -1, SESSIONGID)
            os.fchmod(descriptor, 0o660)
        finally:
            os.close(descriptor)

        try:
            opacity = max(0.0, min(1.0, float(req.get("opacity", 1.0))))
        except Exception:
            opacity = 1.0

        try:
            scale = max(0.25, min(4.0, float(req.get("scale", 1.0))))
        except Exception:
            scale = 1.0

        shadow = bool(req.get("shadow", role == "window"))
        pixelalpha = bool(req.get("pixel_alpha", False))
        theme = str(req.get("theme", GRAPHICSTHEME)).lower()

        if theme not in GRAPHICSTHEMES:
            theme = GRAPHICSTHEME if GRAPHICSTHEME in GRAPHICSTHEMES else "classic"

        try:
            rawblur = req.get("blur", 0.0)
            blur = float(GPUBLURRADIUS) if rawblur is True else max(0.0, min(32.0, float(rawblur)))
        except Exception:
            blur = 0.0

        # create window state
        win = {
            "id": wid,
            "cid": cid,
            "title": title,
            "role": role,
            "current": current,
            "path": path,
            "decoration": decoration,
            "client_chrome_height": client_chrome_height,
            "client_chrome_drag_width": client_chrome_drag_width,
            "client_chrome_controls": client_chrome_controls,
            "drop_types": drop_types,
            "x": x,
            "y": y,
            "w": w,
            "h": h,
            "mapped": False,
            "cursor_mode": "arrow",
            "buffer": bufpath,
            "_owned_buffer": bufpath,
            "_external_buffer": False,
            "buffer_offset": 0,
            "buffer_stride": w * 4,
            "buffer_source_width": w,
            "buffer_source_height": h,
            "damage": [[0, 0, w, h]],
            "opacity": opacity,
            "scale": scale,
            "shadow": shadow,
            "pixel_alpha": pixelalpha,
            "blur": blur,
            "theme": theme,
            "transition_style": "fade_scale",
            "transition_easing": "ease_out",
            "gpu_commands": [],
            "_gpu_commands_pending": None,
            "_managed_only": False,
            "_gpu_generation": 0,
            "_gpu_command_generation": 0,
            "_gpu_presented_generation": 0,
            "_gpu_commit_receipts": [],
            "_gpu_texture": None,
            "_gpu_scene": None,
            "_gpu_scene_damage": [],
            "_gpu_layers": {},
            "_video_streams": {},
            "_presentation_stream": None,
            "_gpu_width": 0,
            "_gpu_height": 0,
            "_telemetry_scene_commits": 0,
            "_telemetry_scene_clears": 0,
            "_telemetry_batch_commits": 0,
            "_telemetry_patch_commits": 0,
            "_telemetry_damage_pixels": 0,
            "_telemetry_composited_pixels": 0,
            "_telemetry_cpu_damage_bytes": 0,
            "_telemetry_cpu_damage_events": 0,
            "_telemetry_cpu_damage_coalesces": 0,
            "_telemetry_cpu_damage_pending_peak": 0,
            "_telemetry_gpu_upload_bytes": 0,
            "_telemetry_gpu_draw_calls": 0,
            "_telemetry_gpu_frames": 0,
            "_telemetry_scene_texture_renders": 0,
            "_telemetry_scene_texture_hits": 0,
            "_telemetry_scene_texture_full_renders": 0,
            "_telemetry_scene_texture_partial_renders": 0,
            "_telemetry_scene_texture_damage_pixels": 0,
            "_telemetry_scene_commands_considered": 0,
            "_telemetry_scene_commands_culled": 0,
            "_telemetry_scene_commands_drawn": 0,
            "_telemetry_layer_texture_renders": 0,
            "_telemetry_layer_texture_hits": 0,
            "_telemetry_fallbacks": 0,
            "_telemetry_last_fallback": "",
            "_fullscreen": False,
            "_fullscreen_restore": None,
            "_max": bool(
                persistentplacement
                and persistentplacement.get("maximized", False)
            ),
            "_snap": (
                persistentplacement.get("snap")
                if persistentplacement
                else None
            ),
            "pid": pid,
            "modal_child": modal_child,
            "modal_parent": modal_parent,
            "picker_session": pickerid or None,
        }

        win["standard_dialog"] = standard_dialog

        if persistentplacement and persistentplacement.get("maximized", False):
            win["_restore"] = list(persistentplacement["restore"])

        # store window
        windows[wid] = win
        clients[cid]["windows"].append(wid)

        if modal_child:
            pickersession["winid"] = wid

        # register owners of desktop windows as desktop clients
        if role == "desktop":

            registerdesktopclient(cid)

        # broadcast taskbar creation for non-desktop/expanse windows
        if role == "window" and not modalwindow(win):

            ev = {
                "op": "TASKBAR_WINDOW_CREATED",
                "winid": wid,
                "title": title,
                "role": role,
                "current": current,
                "path": path,
                "pid": pid if pid is not None else 0
            }

            broadcasttaskbarevent(ev)

        if responseop:
            sendjson(cid, {
                "op": str(responseop),
                "winid": wid,
                "buffer": bufpath,
                "role": role,
                "title": title,
                "current": current,
                "path": path,
                "decoration": decoration,
                "client_chrome_height": client_chrome_height,
                "client_chrome_drag_width": client_chrome_drag_width,
                "client_chrome_controls": client_chrome_controls,
                "x": x,
                "y": y,
                "w": w,
                "h": h,
                "state": "maximized" if ismaximized(win) else "normal",
                "pid": pid if pid is not None else 0
            })

        log(f"window {wid} create {w}x{h} '{title}' role='{role}'")
        return wid

    except PermissionError as error:

        if bufpath and not any(
            win.get("_owned_buffer") == bufpath for win in windows.values()
        ):
            try:
                os.unlink(bufpath)
            except OSError:
                pass
        sendjson(cid, {"op": "ERROR", "code": "denied", "detail": str(error)})

    except Exception as e:

        if bufpath and not any(
            win.get("_owned_buffer") == bufpath for win in windows.values()
        ):
            try:
                os.unlink(bufpath)
            except OSError:
                pass
        sendjson(cid, {"op": "ERROR", "code": "create_failed", "detail": str(e)})


def dialogwraptext(text, limit, maxlines=5):

    words = str(text or "").split()
    lines = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = word
        if len(lines) >= maxlines:
            break
    if current and len(lines) < maxlines:
        lines.append(current)
    if not lines:
        lines = [""]
    if len(words) and len(" ".join(lines)) < len(" ".join(words)):
        lines[-1] = lines[-1][:max(1, limit - 1)].rstrip() + "…"
    return lines[:maxlines]


def dialogbuttonrects(win):

    return list(win.get("dialog_button_rects", []))


def dialogtextwidth(text, size):

    try:
        return max(1, int(measuretext(str(text), int(size), WINDOWFONT)))
    except Exception:
        return max(1, int(len(str(text)) * int(size) * 0.56))


def dialoginputselection(win):

    anchor = win.get("dialog_input_anchor")
    if anchor is None:
        return None
    text = str(win.get("dialog_input_text", ""))
    anchor = max(0, min(len(text), int(anchor)))
    caret = max(0, min(len(text), int(win.get("dialog_input_caret", 0))))
    if anchor == caret:
        return None
    return (anchor, caret) if anchor < caret else (caret, anchor)


def dialoginputdisplaytext(win):

    text = str(win.get("dialog_input_text", ""))
    if win.get("dialog_input_secret"):
        return "\u2022" * len(text)
    return text


def dialoginputactivity(win):

    win["dialog_input_caret_visible"] = True
    win["dialog_input_blink_at"] = time.monotonic()


def dialoginputsnapshot(win):

    return {
        "text": str(win.get("dialog_input_text", "")),
        "caret": int(win.get("dialog_input_caret", 0)),
        "anchor": win.get("dialog_input_anchor"),
    }


def dialoginputrestore(win, snapshot):

    text = str(snapshot.get("text", ""))[:int(win.get("dialog_input_max_length", 256))]
    win["dialog_input_text"] = text
    win["dialog_input_caret"] = max(0, min(len(text), int(snapshot.get("caret", 0))))
    anchor = snapshot.get("anchor")
    win["dialog_input_anchor"] = None if anchor is None else max(0, min(len(text), int(anchor)))


def dialoginputpushundo(win):

    # Secret prompts intentionally have no undo/redo history: retaining each
    # previous password value multiplies sensitive copies in compositor memory.
    if win.get("dialog_input_secret"):
        win["dialog_input_undo"] = []
        win["dialog_input_redo"] = []
        return

    history = win.setdefault("dialog_input_undo", [])
    snapshot = dialoginputsnapshot(win)
    if not history or history[-1].get("text") != snapshot["text"]:
        history.append(snapshot)
        del history[:-DIALOGINPUTHISTORY]
    win["dialog_input_redo"] = []


def dialoginputdelete(win):

    selection = dialoginputselection(win)
    if selection is None:
        return False
    start, end = selection
    text = str(win.get("dialog_input_text", ""))
    win["dialog_input_text"] = text[:start] + text[end:]
    win["dialog_input_caret"] = start
    win["dialog_input_anchor"] = None
    return True


def dialoginputreplace(win, value):

    value = str(value).replace("\r", "").replace("\n", "")
    value = "".join(character for character in value if ord(character) >= 32)
    if not value:
        return False
    dialoginputpushundo(win)
    dialoginputdelete(win)
    text = str(win.get("dialog_input_text", ""))
    caret = max(0, min(len(text), int(win.get("dialog_input_caret", 0))))
    remaining = max(0, int(win.get("dialog_input_max_length", 256)) - len(text))
    value = value[:remaining]
    if not value:
        return False
    win["dialog_input_text"] = text[:caret] + value + text[caret:]
    win["dialog_input_caret"] = caret + len(value)
    win["dialog_input_anchor"] = None
    return True


def dialoginputword(win, position, right=False):

    text = str(win.get("dialog_input_text", ""))
    index = max(0, min(len(text), int(position)))
    if right:
        while index < len(text) and not text[index].isalnum():
            index += 1
        while index < len(text) and text[index].isalnum():
            index += 1
    else:
        while index > 0 and not text[index - 1].isalnum():
            index -= 1
        while index > 0 and text[index - 1].isalnum():
            index -= 1
    return index


def dialoginputmovecaret(win, position, shift=False):

    text = str(win.get("dialog_input_text", ""))
    old = max(0, min(len(text), int(win.get("dialog_input_caret", 0))))
    position = max(0, min(len(text), int(position)))
    if shift:
        if win.get("dialog_input_anchor") is None:
            win["dialog_input_anchor"] = old
        win["dialog_input_caret"] = position
        if win.get("dialog_input_anchor") == position:
            win["dialog_input_anchor"] = None
    else:
        win["dialog_input_caret"] = position
        win["dialog_input_anchor"] = None


def dialoginputprefixwidth(win, index, fontsize):

    text = dialoginputdisplaytext(win)
    index = max(0, min(len(text), int(index)))
    if index == 0:
        return 0
    return dialogtextwidth(text[:index], fontsize)


def dialoginputensurevisible(win, innerwidth, fontsize):

    caretwidth = dialoginputprefixwidth(win, win.get("dialog_input_caret", 0), fontsize)
    scroll = max(0, int(win.get("dialog_input_scroll", 0)))
    margin = scalesize(3)
    if caretwidth < scroll:
        scroll = caretwidth
    elif caretwidth > scroll + innerwidth - margin:
        scroll = caretwidth - innerwidth + margin
    total = dialoginputprefixwidth(win, len(str(win.get("dialog_input_text", ""))), fontsize)
    win["dialog_input_scroll"] = max(0, min(scroll, max(0, total - innerwidth + margin)))


def dialoginputindexfromx(win, x):

    rect = win.get("dialog_input_rect")
    if not rect:
        return 0
    fontsize = scalesize(16)
    innerx = int(rect[0]) + scalesize(DIALOGINPUTPAD)
    wanted = max(0, int(x) - innerx + int(win.get("dialog_input_scroll", 0)))
    text = str(win.get("dialog_input_text", ""))
    previous = 0
    for index in range(1, len(text) + 1):
        current = dialoginputprefixwidth(win, index, fontsize)
        if wanted < (previous + current) // 2:
            return index - 1
        previous = current
    return len(text)


def dialogclipboardsettext(value):

    try:
        os.makedirs(CLIPBASE, exist_ok=True)
        path = os.path.join(CLIPBASE, "current.txt")
        with open(path, "w", encoding="utf-8") as output:
            output.write(str(value))
        clipboard["type"] = "text/plain"
        clipboard["path"] = path
        return True
    except Exception as error:
        log(f"dialog clipboard set error {error}")
        return False


def dialogclipboardgettext():

    try:
        if clipboard.get("type") != "text/plain" or not clipboard.get("path"):
            return None
        with open(clipboard["path"], "r", encoding="utf-8") as source:
            return source.read(1048576)
    except Exception:
        return None


def dialogrender(win):

    width = int(win.get("w", DIALOGBASEW))
    height = int(win.get("h", DIALOGBASEH))
    pad = scalesize(DIALOGPAD)
    fontsize = scalesize(16)
    lineheight = scalesize(24)
    buttonw = scalesize(DIALOGBUTTONW)
    buttonh = scalesize(DIALOGBUTTONH)
    gap = scalesize(DIALOGGAP)
    buttons = list(win.get("dialog_buttons", []))
    active = max(0, min(len(buttons) - 1, int(win.get("dialog_focus", 0)))) if buttons else 0
    inputenabled = bool(win.get("dialog_input_enabled", False))
    inputfocused = inputenabled and bool(win.get("dialog_input_focused", False))
    if buttons:
        availablebuttonw = max(1, width - pad * 2 - gap * max(0, len(buttons) - 1))
        buttonw = min(buttonw, max(scalesize(60), availablebuttonw // len(buttons)))
    totalw = (buttonw * len(buttons)) + (gap * max(0, len(buttons) - 1))
    bx = max(pad, (width - totalw) // 2)
    by = max(pad, height - pad - buttonh)
    rects = []
    commands = [{"kind": "rectangle", "rect": [0, 0, width, height], "color": DIALOGBACKGROUND}]

    inputh = scalesize(DIALOGINPUTH)
    inputy = by - gap - inputh if inputenabled else None
    charlimit = max(16, int((width - pad * 2) / max(5, fontsize * 0.58)))
    messagelines = dialogwraptext(win.get("dialog_message", ""), charlimit)
    messageheight = max(fontsize, len(messagelines) * lineheight)
    messagebottom = inputy if inputenabled else by
    messageareaheight = max(fontsize, messagebottom - gap - pad)
    messagey = pad + max(0, (messageareaheight - messageheight) // 2)
    for index, line in enumerate(messagelines):
        if line:
            linew = min(max(1, width - pad * 2), dialogtextwidth(line, fontsize))
            commands.append({
                "kind": "text", "x": max(pad, (width - linew) // 2), "y": messagey + index * lineheight,
                "text": line, "size": fontsize, "font": WINDOWFONT, "color": DIALOGTEXT,
            })

    if inputenabled:
        inputrect = [pad, inputy, max(1, width - pad * 2), inputh]
        win["dialog_input_rect"] = inputrect
        commands.append({"kind": "border", "rect": inputrect, "width": 1, "color": DIALOGOUTLINE})
        innerpad = scalesize(DIALOGINPUTPAD)
        innerx = inputrect[0] + innerpad
        innerw = max(1, inputrect[2] - innerpad * 2)
        texty = inputrect[1] + max(2, (inputrect[3] - fontsize) // 2)
        clip = [innerx, inputrect[1] + 2, innerw, max(1, inputrect[3] - 4)]
        dialoginputensurevisible(win, innerw, fontsize)
        scroll = int(win.get("dialog_input_scroll", 0))
        text = dialoginputdisplaytext(win)
        startindex = 0
        while startindex < len(text) and dialoginputprefixwidth(win, startindex + 1, fontsize) <= scroll:
            startindex += 1
        startwidth = dialoginputprefixwidth(win, startindex, fontsize)
        drawx = max(0, innerx - max(0, scroll - startwidth))
        selection = dialoginputselection(win)
        if selection is not None:
            start, end = selection
            sx = innerx + dialoginputprefixwidth(win, start, fontsize) - scroll
            ex = innerx + dialoginputprefixwidth(win, end, fontsize) - scroll
            left = max(innerx, sx)
            right = min(innerx + innerw, ex)
            if right > left:
                commands.append({
                    "kind": "rectangle", "rect": [left, inputrect[1] + 3, right - left, inputrect[3] - 6],
                    "clip": clip, "color": DIALOGOUTLINE,
                })
        if text[startindex:]:
            commands.append({
                "kind": "text", "x": drawx, "y": texty, "text": text[startindex:],
                "size": fontsize, "font": WINDOWFONT, "color": DIALOGTEXT, "clip": clip,
            })
        if inputfocused and win.get("dialog_input_caret_visible", True):
            caretx = innerx + dialoginputprefixwidth(win, win.get("dialog_input_caret", 0), fontsize) - scroll
            caretx = max(innerx, min(innerx + innerw - 1, caretx))
            commands.append({
                "kind": "line", "points": [caretx, inputrect[1] + 6, caretx, inputrect[1] + inputrect[3] - 6],
                "width": 1, "color": DIALOGTEXT, "clip": clip,
            })
    else:
        win["dialog_input_rect"] = None

    for index, button in enumerate(buttons):
        x = bx + index * (buttonw + gap)
        rect = [x, by, buttonw, buttonh]
        rects.append({"rect": rect, "id": button["id"]})
        commands.append({"kind": "border", "rect": rect, "width": 1, "color": DIALOGOUTLINE})
        label = button["label"]
        labelw = min(max(1, buttonw - 8), dialogtextwidth(label, fontsize))
        labelx = x + max(4, (buttonw - labelw) // 2)
        labely = by + max(2, (buttonh - fontsize) // 2)
        commands.append({
            "kind": "text", "x": labelx, "y": labely,
            "text": label, "size": fontsize, "font": WINDOWFONT, "color": DIALOGTEXT,
        })
        if index == active and not inputfocused:
            underliney = min(by + buttonh - 5, labely + fontsize + 2)
            commands.append({
                "kind": "line", "points": [labelx, underliney, min(x + buttonw - 4, labelx + labelw), underliney],
                "width": 1, "color": DIALOGTEXT,
            })

    win["dialog_button_rects"] = rects
    try:
        validated = [graphicscommand(win, command, command["kind"]) for command in commands]
        graphicscommandbudget(win, len(validated))
        graphicsvalidatescene(validated)
        win["gpu_commands"] = validated
        win["_gpu_commands_pending"] = None
        win["_gpu_generation"] = int(win.get("_gpu_generation", 0)) + 1
        win["_gpu_command_generation"] = int(win.get("_gpu_command_generation", 0)) + 1
        win["_managed_only"] = False
        win["_gpu_scene_damage"] = [[0, 0, width, height]]
        gpuwindowlayersprune(win)
    except Exception as error:
        log(f"standard dialog render error wid={win.get('id')} {error}")
    win["damage"] = [[0, 0, width, height]]
    if win.get("dialog_input_secret"):
        # Password entry must never expose a partially reconstructed security
        # surface when the KMS scanout rotates backing buffers. Recompose the
        # complete desktop for these infrequent edits so the parent, message,
        # controls and masked value remain visible in the same frame.
        DAMAGERECTS.append([0, 0, int(SCREENW), int(SCREENH)])
    else:
        DAMAGERECTS.append(framedamagerect(win))


def createdialog(cid, req):

    wid = None
    try:
        parent = int(req.get("parent", 0))
        if parent not in windows or windows[parent].get("cid") != cid:
            sendjson(cid, {"op": "ERROR", "code": "dialog_parent_invalid"})
            return None

        dialogid = str(req.get("dialog_id", "dialog"))[:128]
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", dialogid):
            raise ValueError("dialog_id contains unsupported characters")
        sourcebuttons = req.get("buttons", [])
        if not isinstance(sourcebuttons, list) or not 1 <= len(sourcebuttons) <= 4:
            raise ValueError("dialog requires one to four buttons")
        buttons = []
        for index, entry in enumerate(sourcebuttons):
            if not isinstance(entry, dict):
                raise ValueError("dialog button must be an object")
            buttonid = str(entry.get("id", f"button{index}"))[:64]
            if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", buttonid):
                raise ValueError("dialog button id contains unsupported characters")
            label = str(entry.get("label", buttonid)).strip()[:48]
            if not label:
                raise ValueError("dialog button label is empty")
            buttons.append({"id": buttonid, "label": label, "cancel": bool(entry.get("cancel", False))})

        inputrequest = req.get("input")
        inputenabled = inputrequest is not None
        if inputenabled and not isinstance(inputrequest, dict):
            raise ValueError("dialog input must be an object")
        inputrequest = inputrequest if inputenabled else {}
        inputmaxlength = max(1, min(4096, int(inputrequest.get("max_length", 256))))
        inputtext = str(inputrequest.get("value", ""))[:inputmaxlength]

        parentwin = windows[parent]
        existing = modaldialogfor(parent)
        if existing in windows:
            raise ValueError("parent already has a modal dialog")
        width = max(scalesize(360), min(scalesize(720), int(req.get("w", scalesize(DIALOGBASEW)))))
        height = max(scalesize(160), min(scalesize(420), int(req.get("h", scalesize(DIALOGBASEH)))))
        x = int(parentwin.get("x", 0)) + (int(parentwin.get("w", width)) - width) // 2
        y = int(parentwin.get("y", 0)) + (int(parentwin.get("h", height)) - height) // 2
        x = max(WORKX, min(WORKX + WORKW - width, x))
        y = max(WORKY + TITLEH + FRAMEW, min(WORKY + WORKH - height, y))
        internal = {
            "role": "window", "title": str(req.get("title", "dialog"))[:128],
            "w": width, "h": height, "x": x, "y": y, "pid": 0,
            "shadow": True, "theme": "dialog", "_standard_dialog": True,
        }
        wid = createwindow(cid, internal, responseop=None, internal=True)
        if wid not in windows:
            raise RuntimeError("dialog window creation failed")
        win = windows[wid]
        win.update({
            "dialog_id": dialogid,
            "dialog_parent": parent,
            "modal_parent": parent,
            "dialog_message": str(req.get("message", ""))[:2048],
            "dialog_buttons": buttons,
            "dialog_focus": max(0, min(len(buttons) - 1, int(req.get("default", 0)))),
            "dialog_pressed": None,
            "dialog_input_enabled": inputenabled,
            "dialog_input_text": inputtext,
            "dialog_input_original": inputtext,
            "dialog_input_caret": len(inputtext),
            "dialog_input_anchor": 0 if inputenabled and bool(inputrequest.get("select_all", False)) and inputtext else None,
            "dialog_input_scroll": 0,
            "dialog_input_focused": inputenabled,
            "dialog_input_dragging": False,
            "dialog_input_max_length": inputmaxlength,
            "dialog_input_allow_empty": bool(inputrequest.get("allow_empty", True)),
            "dialog_input_secret": bool(inputrequest.get("secret", False)),
            "dialog_input_undo": [],
            "dialog_input_redo": [],
            "dialog_input_caret_visible": True,
            "dialog_input_blink_at": time.monotonic(),
        })
        try:
            with open(win["buffer"], "r+b") as output:
                output.write(bytes((0, 0, 0, 255)) * (width * height))
        except Exception:
            pass
        dialogrender(win)
        mapwindow(cid, {"winid": wid, "transition": True})
        if not windows.get(wid, {}).get("mapped"):
            raise RuntimeError("dialog window mapping failed")
        setfocus(wid)
        sendjson(cid, {"op": "DIALOG_CREATED", "dialog_id": dialogid, "winid": wid, "parent": parent})
        return wid
    except Exception as error:
        if wid in windows:
            destroywindow(wid, note="standard dialog create failed")
        sendjson(cid, {
            "op": "ERROR", "code": "dialog_create_failed", "detail": str(error),
            "dialog_id": str(req.get("dialog_id", "dialog"))[:128],
        })
        log(f"dialog_create_failed cid={cid} {error}")
        return None


def createpasswordprompt(cid, req):

    if (
        not clienthascapability(cid, "protected_auth_surface")
        or not clienthasinteractivefocus(cid)
    ):
        sendjson(cid, {"op": "ERROR", "code": "password_prompt_denied"})
        return None

    try:
        parent = int(req.get("parent", 0))
    except Exception:
        parent = 0

    parentwin = windows.get(parent)
    if (
        not parentwin
        or parentwin.get("cid") != cid
        or parent != FOCUSWID
        or not parentwin.get("mapped")
        or str(parentwin.get("role", "")) != "window"
    ):
        sendjson(cid, {"op": "ERROR", "code": "password_prompt_denied"})
        return None

    request = dict(req)
    request["title"] = str(
        req.get("title", "authentication required"))[:128]
    request["message"] = str(
        req.get("message", "Enter the current master password to continue."))[:2048]
    request["buttons"] = [
        {
            "id": "submit",
            "label": str(req.get("submit_label", "continue"))[:48],
        },
        {
            "id": "cancel",
            "label": str(req.get("cancel_label", "cancel"))[:48],
            "cancel": True,
        },
    ]
    request["default"] = 0
    request["input"] = {
        "value": "",
        "max_length": req.get("max_length", 256),
        "allow_empty": False,
        "secret": True,
    }
    return createdialog(cid, request)


def dialogcancelid(win):

    buttons = list(win.get("dialog_buttons", []))
    for button in buttons:
        if button.get("cancel"):
            return button.get("id")
    return buttons[-1].get("id") if buttons else "cancel"


def dialogfinish(wid, result=None):

    if wid not in windows or not windows[wid].get("standard_dialog"):
        return False
    win = windows[wid]
    result = str(result if result is not None else dialogcancelid(win))
    killpid = win.get("_kill_prompt_pid")
    if killpid is not None:
        try:
            killpid = int(killpid)
        except Exception:
            killpid = None
        if killpid is not None:
            killinfo = PENDINGKILLS.pop(killpid, None)
            killauthorized = pendingkillidentityvalid(killinfo, killpid)
            if killinfo is not None:
                parent = windows.get(killinfo.get("wid"))
                if parent is not None:
                    parent.pop("cursor_busy", None)
        destroywindow(wid, note="unresponsive operation prompt")
        refreshcursormode()
        if result == "kill" and killpid is not None and killauthorized:
            try:
                if not operationskill(killpid):
                    log(f"operations kill failed for pid {killpid}")
            except Exception as error:
                log(f"operations kill error {error}")
        elif result == "kill" and killpid is not None:
            log(f"refused stale process kill for pid {killpid}")
        return True
    if win.get("dialog_input_enabled") and result != str(dialogcancelid(win)):
        if not win.get("dialog_input_allow_empty", True) and not str(win.get("dialog_input_text", "")).strip():
            win["dialog_input_focused"] = True
            dialogrender(win)
            return False
    response = {
        "op": "DIALOG_RESULT", "dialog_id": win.get("dialog_id", "dialog"),
        "winid": wid, "parent": win.get("dialog_parent"), "result": result,
    }
    if (
        win.get("dialog_input_enabled")
        and not (
            win.get("dialog_input_secret")
            and result == str(dialogcancelid(win))
        )
    ):
        response["value"] = str(win.get("dialog_input_text", ""))
    sendjson(win["cid"], response)
    if win.get("dialog_input_secret"):
        win["dialog_input_text"] = ""
        win["dialog_input_original"] = ""
        win["dialog_input_undo"] = []
        win["dialog_input_redo"] = []
    destroywindow(wid, note="standard dialog result")
    return True


def dialogpointer(wid, state, x, y, button=1, mods=None):

    if wid not in windows or not windows[wid].get("standard_dialog"):
        return False
    if int(button) != 1:
        return True
    win = windows[wid]
    inputrect = win.get("dialog_input_rect")
    inputhit = False
    if inputrect:
        rx, ry, rw, rh = inputrect
        inputhit = rx <= x < rx + rw and ry <= y < ry + rh
    hit = None
    for index, entry in enumerate(dialogbuttonrects(win)):
        rx, ry, rw, rh = entry["rect"]
        if rx <= x < rx + rw and ry <= y < ry + rh:
            hit = index
            break
    if state == "down":
        if inputhit:
            position = dialoginputindexfromx(win, x)
            if bool((mods or {}).get("shift")):
                dialoginputmovecaret(win, position, shift=True)
            else:
                win["dialog_input_anchor"] = position
                win["dialog_input_caret"] = position
            win["dialog_input_focused"] = True
            win["dialog_input_dragging"] = True
            dialoginputactivity(win)
            win["dialog_pressed"] = None
            dialogrender(win)
            return True
        win["dialog_pressed"] = hit
        if hit is not None:
            win["dialog_focus"] = hit
            win["dialog_input_focused"] = False
            dialogrender(win)
    elif state == "up":
        win["dialog_input_dragging"] = False
        if win.get("dialog_input_anchor") == win.get("dialog_input_caret"):
            win["dialog_input_anchor"] = None
        pressed = win.get("dialog_pressed")
        win["dialog_pressed"] = None
        if hit is not None and pressed == hit:
            buttons = list(win.get("dialog_buttons", []))
            if 0 <= hit < len(buttons):
                dialogfinish(wid, buttons[hit]["id"])
    return True


def dialogmotion(wid, x, y):

    if wid not in windows or not windows[wid].get("standard_dialog"):
        return False
    win = windows[wid]
    if not win.get("dialog_input_enabled") or not win.get("dialog_input_dragging"):
        return True
    win["dialog_input_caret"] = dialoginputindexfromx(win, x)
    dialoginputactivity(win)
    dialogrender(win)
    return True


def dialogtext(wid, value):

    if wid not in windows or not windows[wid].get("standard_dialog"):
        return False
    win = windows[wid]
    if win.get("dialog_input_enabled") and win.get("dialog_input_focused"):
        if dialoginputreplace(win, value):
            dialoginputactivity(win)
            dialogrender(win)
    return True


def dialogkey(wid, msg):

    if wid not in windows or not windows[wid].get("standard_dialog"):
        return False
    if str(msg.get("state", "down")) not in ("down", "repeat"):
        return True
    win = windows[wid]
    buttons = list(win.get("dialog_buttons", []))
    if not buttons:
        return True
    key = str(msg.get("key", "")).upper()
    mods = msg.get("mods", {}) or {}
    ctrl = bool(mods.get("ctrl") or mods.get("control"))
    shift = bool(mods.get("shift"))
    if key == "ESC":
        dialogfinish(wid, dialogcancelid(win))
        return True
    inputenabled = bool(win.get("dialog_input_enabled"))
    inputfocused = inputenabled and bool(win.get("dialog_input_focused"))
    if key == "TAB" and inputenabled:
        if inputfocused:
            win["dialog_input_focused"] = False
            win["dialog_focus"] = len(buttons) - 1 if shift else 0
        else:
            nextindex = int(win.get("dialog_focus", 0)) + (-1 if shift else 1)
            if nextindex < 0 or nextindex >= len(buttons):
                win["dialog_input_focused"] = True
                dialoginputactivity(win)
            else:
                win["dialog_focus"] = nextindex
        dialogrender(win)
        return True
    if inputfocused:
        dialoginputactivity(win)
        text = str(win.get("dialog_input_text", ""))
        caret = max(0, min(len(text), int(win.get("dialog_input_caret", 0))))
        selection = dialoginputselection(win)
        if key == "ENTER":
            index = max(0, min(len(buttons) - 1, int(win.get("dialog_focus", 0))))
            dialogfinish(wid, buttons[index]["id"])
            return True
        if ctrl and key == "A":
            win["dialog_input_anchor"] = 0
            win["dialog_input_caret"] = len(text)
        elif ctrl and key in ("C", "X"):
            if selection is not None:
                start, end = selection
                if not win.get("dialog_input_secret"):
                    dialogclipboardsettext(text[start:end])
                if key == "X":
                    dialoginputpushundo(win)
                    dialoginputdelete(win)
        elif ctrl and key == "V":
            value = dialogclipboardgettext()
            if value is not None:
                dialoginputreplace(win, value)
        elif ctrl and key == "Z":
            history = win.setdefault("dialog_input_undo", [])
            if history:
                win.setdefault("dialog_input_redo", []).append(dialoginputsnapshot(win))
                dialoginputrestore(win, history.pop())
        elif ctrl and key == "Y":
            history = win.setdefault("dialog_input_redo", [])
            if history:
                win.setdefault("dialog_input_undo", []).append(dialoginputsnapshot(win))
                dialoginputrestore(win, history.pop())
        elif key in ("HOME", "END"):
            dialoginputmovecaret(win, 0 if key == "HOME" else len(text), shift=shift)
        elif key in ("LEFT", "RIGHT"):
            if selection is not None and not shift and not ctrl:
                dialoginputmovecaret(win, selection[0] if key == "LEFT" else selection[1])
            else:
                destination = dialoginputword(win, caret, right=(key == "RIGHT")) if ctrl else caret + (-1 if key == "LEFT" else 1)
                dialoginputmovecaret(win, destination, shift=shift)
        elif key in ("BACKSPACE", "DELETE"):
            if selection is not None:
                dialoginputpushundo(win)
                dialoginputdelete(win)
            else:
                start = caret
                end = caret
                if key == "BACKSPACE":
                    start = dialoginputword(win, caret, right=False) if ctrl else max(0, caret - 1)
                else:
                    end = dialoginputword(win, caret, right=True) if ctrl else min(len(text), caret + 1)
                if start != end:
                    dialoginputpushundo(win)
                    win["dialog_input_text"] = text[:start] + text[end:]
                    win["dialog_input_caret"] = start
                    win["dialog_input_anchor"] = None
        dialogrender(win)
        return True
    if key in ("TAB", "LEFT", "RIGHT"):
        delta = -1 if key == "LEFT" or (key == "TAB" and shift) else 1
        win["dialog_focus"] = (int(win.get("dialog_focus", 0)) + delta) % len(buttons)
        dialogrender(win)
        return True
    if key in ("ENTER", "SPACE"):
        index = max(0, min(len(buttons) - 1, int(win.get("dialog_focus", 0))))
        dialogfinish(wid, buttons[index]["id"])
        return True
    return True


def dialogpulse():

    now = time.monotonic()
    for win in list(windows.values()):
        if not win.get("mapped") or not win.get("standard_dialog"):
            continue
        if not win.get("dialog_input_enabled") or not win.get("dialog_input_focused"):
            continue
        if now - float(win.get("dialog_input_blink_at", now)) < DIALOGINPUTBLINK:
            continue
        win["dialog_input_blink_at"] = now
        win["dialog_input_caret_visible"] = not bool(win.get("dialog_input_caret_visible", True))
        dialogrender(win)


def modaldialogfor(wid):

    try:
        parent = int(wid)
    except Exception:
        return None

    for candidate in reversed(zorder):
        win = windows.get(candidate)
        try:
            childparent = int(win.get("modal_parent", win.get("dialog_parent", 0))) if win else 0
        except Exception:
            childparent = 0
        if win and win.get("mapped") and modalwindow(win) and childparent == parent:
            return candidate
    return None


def mapwindow(cid, req):

    global FOCUSPENDING

    try:

        wid = int(req.get("winid", 0))

        if wid not in windows:
            sendjson(cid, {"op": "ERROR", "code": "unknown_window"})
            log(f"MAP unknown_window wid={wid} from cid={cid}")
            return

        if windows[wid]["cid"] != cid:
            sendjson(cid, {"op": "ERROR", "code": "not_owner"})
            log(f"MAP not_owner wid={wid} from cid={cid}")
            return

        windows[wid]["mapped"] = True

        if str(windows[wid].get("role", "")) == "window":

            fitwindowtoworkarea(wid)

        sourcewidth, sourceheight = windowbufferdimensions(windows[wid])
        windows[wid]["damage"] = [[0, 0, sourcewidth, sourceheight]]

        # Mapping must always expose a complete final frame.  Transitions are
        # opt-in through MAP or WINDOW_EFFECTS so client content and the
        # server-owned chrome cannot be stranded at partial opacity/scale.
        windows[wid].pop("_gpu_transition_start", None)

        if GPUTRANSITIONS and bool(req.get("transition", False)):
            windows[wid]["_gpu_transition_start"] = time.monotonic()
            windows[wid]["_gpu_transition_ms"] = max(0, min(5000, int(req.get("transition_ms", GPUTRANSITIONMS))))

        if windows[wid]["role"] == "desktop":

            if wid in zorder:
                zorder.remove(wid)

            zorder.insert(0, wid)

            # large map → tile the initial damage so IO can interleave
            tildamage(windows[wid], tilesz=256)

            try:

                # if nothing is focused yet, focus the desktop so keys have a target
                if (FOCUSWID is None) or (FOCUSWID not in windows):

                    setfocus(wid)

            except Exception as e:

                # focus error is non-fatal
                log(f"focus on desktop map error {e}")

        else:

            if wid in zorder:
                zorder.remove(wid)

            role = str(windows[wid].get("role", ""))

            if role == "system animation":

                zorder.append(wid)

            elif role == "startup":

                inserted = False

                for i, zwid in enumerate(zorder):

                    if str(windows.get(zwid, {}).get("role", "")) == "system animation":
                        zorder.insert(i, wid)
                        inserted = True
                        break

                if inserted is False:
                    zorder.append(wid)

            elif role == "expanse":

                inserted = False

                for i, zwid in enumerate(zorder):


                    zrole = str(windows.get(zwid, {}).get("role", ""))

                    if zrole in ("startup", "lockscreen", "system animation"):

                        zorder.insert(i, wid)
                        inserted = True
                        break

                if inserted is False:

                    zorder.append(wid)

            else:

                inserted = False

                for i, zwid in enumerate(zorder):

                    if str(windows.get(zwid, {}).get("role", "")) == "system animation":
                        zorder.insert(i, wid)
                        inserted = True
                        break

                if inserted is False:
                    zorder.append(wid)

            fulldamage(windows[wid])

            if role == "system animation":
                setfocus(wid)

        refreshcursormode()

        if not windows[wid].get("_operation_ready_notified"):

            pid = windows[wid].get("pid")

            if operationsreadypid(pid) is not None:
                windows[wid]["_operation_ready_notified"] = True

        sendjson(cid, {"op": "WINDOW_MAPPED", "winid": wid})

        try:

            # broadcast taskbar map and focus for non-desktop windows
            role = str(windows[wid].get("role", ""))

            if role == "window":

                if not modalwindow(windows[wid]):
                    ev = {
                        "op": "TASKBAR_WINDOW_MAPPED",
                        "winid": wid
                    }

                    broadcasttaskbarevent(ev)

                try:

                    # queue focus after the map settles (prevents double taskbar repaint flashes)
                    FOCUSPENDING = wid

                except Exception as e:

                    # focus error is non-fatal
                    log(f"focus on map error {e}")

            if role in ("startup", "lockscreen"):

                try:

                    FOCUSPENDING = wid

                except Exception as e:

                    log(f"focus on map error {e}")

            if role in ("tooltip", "taskmenu", "instancelist"):

                # tooltips never steal focus; keep current focus intact
                pass

        except Exception as e:

            # taskbar or focus handling error
            log(f"map post-handlers error {e}")

        # Mapping can change the surface beneath a stationary pointer. Deliver
        # its current position now so ownership transfers without requiring an
        # artificial nudge or waiting for the next physical mouse report.
        inputpointer(
            {"x": POINTERX, "y": POINTERY},
            dispatch=not (SESSIONLOCKED and not sessionlockvisible()),
        )

        log(f"window {wid} mapped by cid={cid}")

    except Exception as e:
        sendjson(cid, {"op": "ERROR", "code": "map_failed", "detail": str(e)})
        log(f"map_failed wid={req.get('winid')} err={e}")


def releasewindowinteraction(wid):

    released = False

    if POINTERGRAB.get("wid") == wid:
        BTNDOWN.discard(int(POINTERGRAB.get("btn", 0)))
        POINTERGRAB["wid"] = None
        POINTERGRAB["btn"] = 0
        released = True

    if DRAGINFO.get("wid") == wid:
        BTNDOWN.discard(int(DRAGINFO.get("btn", 0)))
        DRAGINFO["wid"] = None
        DRAGINFO["kind"] = None
        DRAGINFO["btn"] = 0
        released = True

    if released:
        setsnappreview(None)
        setwindowbuttonhover(None)

    return released


def unmapwindow(cid, req):

    try:

        wid = int(req.get("winid", 0))

        if wid not in windows or windows[wid]["cid"] != cid:
            sendjson(cid, {"op": "ERROR", "code": "unknown_window"})
            return

        # damage the current frame + client area being removed
        DAMAGERECTS.append(framedamagerect(windows[wid]))
        DAMAGERECTS.append([windows[wid]["x"], windows[wid]["y"], windows[wid]["w"], windows[wid]["h"]])
        windows[wid]["mapped"] = False
        graphicscancelcommitreceipts(
            windows[wid],
            "window was unmapped before presentation",
        )
        releasewindowinteraction(wid)
        videowindowrelease(windows[wid], wait=True)
        gpuwindowrelease(windows[wid])
        GPUANIMATIONS.pop(int(wid), None)

        if wid in zorder:
            zorder.remove(wid)

        if FOCUSWID == wid:
            setfocus(mappedfocusfallback(exclude=wid))

        # Reconcile hover and motion ownership with the newly exposed surface
        # even if the physical pointer is stationary during the handoff.
        inputpointer(
            {"x": POINTERX, "y": POINTERY},
            dispatch=not (SESSIONLOCKED and not sessionlockvisible()),
        )

        sendjson(cid, {"op": "WINDOW_UNMAPPED", "winid": wid})


        # broadcast taskbar unmap for non-desktop windows
        role = str(windows[wid].get("role", ""))

        if role == "window" and not modalwindow(windows[wid]):

            ev = {
                "op": "TASKBAR_WINDOW_UNMAPPED",
                "winid": wid
            }

            broadcasttaskbarevent(ev)

        log(f"window {wid} unmapped")

    except Exception as e:
        sendjson(cid, {"op": "ERROR", "code": "unmap_failed", "detail": str(e)})


def destroywindow(wid, note=""):

    try:

        global FOCUSWID


        # check present
        if wid not in windows:
            return

        if windows[wid].get("dialog_input_secret"):
            windows[wid]["dialog_input_text"] = ""
            windows[wid]["dialog_input_original"] = ""
            windows[wid]["dialog_input_undo"] = []
            windows[wid]["dialog_input_redo"] = []

        # Close any modal children before removing their parent.
        children = [
            childwid for childwid, child in list(windows.items())
            if modalwindow(child)
            and int(child.get("modal_parent", child.get("dialog_parent", 0)) or 0) == int(wid)
        ]
        for childwid in children:
            if childwid in windows:
                if windows[childwid].get("standard_dialog"):
                    dialogfinish(childwid, dialogcancelid(windows[childwid]))
                else:
                    pickerid = windows[childwid].get("picker_session")
                    if pickerid in PICKERSESSIONS:
                        PICKERSESSIONS[pickerid]["terminal"] = True
                    destroywindow(childwid, note="modal parent destroyed")

        # The final independent window is authoritative for the next launch of
        # this software. Commit it before any backing resources are removed.
        if lastsoftwarewindow(wid):
            recordwindowattributes(windows[wid])
            savewindowattributes(force=True)


        # capture focus state before removal
        try:

            wasfocused = (FOCUSWID == wid)

        except Exception:

            wasfocused = False


        # capture current window geometry for damage
        try:

            dx = windows[wid]["x"]
            dy = windows[wid]["y"]
            dw = windows[wid]["w"]
            dh = windows[wid]["h"]

            dframe = framedamagerect(windows[wid])

        except Exception:

            dx = None
            dy = None
            dw = None
            dh = None
            dframe = None


        # remove from zorder
        releasewindowinteraction(wid)

        if wid in zorder:
            zorder.remove(wid)


        videowindowrelease(windows[wid], wait=True)
        gpuwindowrelease(windows[wid])
        GPUANIMATIONS.pop(int(wid), None)
        graphicscancelcommitreceipts(
            windows[wid],
            "window was destroyed before presentation",
        )


        # Only unlink the backing file created by WindowServer.  A validated
        # external producer buffer (currently Chromium's private Xvfb surface)
        # remains owned by that producer.
        os.unlink(windows[wid].get("_owned_buffer", windows[wid]["buffer"]))
        cid = windows[wid]["cid"]

        if cid in clients and wid in clients[cid]["windows"]:
            clients[cid]["windows"].remove(wid)


        # damage rects for old region

        if dx is not None:
            DAMAGERECTS.append([dx, dy, dw, dh])

        if dframe is not None:
            DAMAGERECTS.append(dframe)

        try:

            role = str(windows[wid].get("role", ""))

        except Exception:

            role = ""



        # notify owning client explicitly about destruction
        if cid in clients:
            sendjson(cid, {"op": "WINDOW_DESTROYED", "winid": wid})


        # broadcast taskbar destroy for non-desktop/taskbar/startmenu
        if role == "window" and not modalwindow(windows[wid]):

            ev = {
                "op": "TASKBAR_WINDOW_DESTROYED",
                "winid": wid
            }

            broadcasttaskbarevent(ev)

        pickercancelwindow(wid)

        del windows[wid]

        # Client disconnects destroy Startup's final surface directly rather
        # than unmapping it first. Transfer the stationary pointer to the newly
        # exposed desktop on this path as well.
        inputpointer(
            {"x": POINTERX, "y": POINTERY},
            dispatch=not (SESSIONLOCKED and not sessionlockvisible()),
        )

        if wasfocused:

            newfocus = None

            for twid in reversed(zorder):


                if twid not in windows:
                    continue

                twin = windows[twid]

                if not twin.get("mapped"):
                    continue

                trole = str(twin.get("role", ""))

                if trole not in ("lockscreen", "startup", "window"):
                    continue

                newfocus = twid
                break

            if newfocus is not None:

                setfocus(newfocus)

            else:

                FOCUSWID = None

        endclientifnowindows(cid)

        if note:
            log(f"window {wid} destroy ({note})")
        else:
            log(f"window {wid} destroy")

    except Exception as e:

        # destroy error
        log(f"window destroy error {e}")


def clampwindow(win, allowpartial=False):


    # clamp size
    if win["w"] < 1:
        win["w"] = 1

    if win["h"] < 1:
        win["h"] = 1

    if win["w"] > SCREENW:
        win["w"] = SCREENW

    if win["h"] > SCREENH:
        win["h"] = SCREENH

    # normal windows may cross a work-area edge while enough of the titlebar
    # remains visible to drag them back. pinned/maximised roles stay contained.
    role = str(win.get("role", ""))

    if allowpartial and role == "window" and not clientchromemode(win) and not ismaximized(win):

        left = int(WORKX)
        top = int(WORKY)
        right = left + max(1, int(WORKW))
        bottom = top + max(1, int(WORKH))
        controls = (BTNGAP + BTNWH) * 3 + BTNGAP
        titlewidth = int(win["w"]) - controls

        if titlewidth > 0:

            horizontalgrab = min(titlewidth, max(BTNWH, HITCORNER * 2))
            verticalgrab = min(TITLEH, max(HITEDGE, TITLEH // 2))
            minx = left + horizontalgrab - titlewidth
            maxx = right - horizontalgrab
            miny = top + verticalgrab
            maxy = bottom + TITLEH - verticalgrab

            if win["x"] < minx:
                win["x"] = minx

            if win["x"] > maxx:
                win["x"] = maxx

            if win["y"] < miny:
                win["y"] = miny

            if win["y"] > maxy:
                win["y"] = maxy

            return

    # constrained roles and resizing retain the original whole-client bounds
    if win["x"] < 0:
        win["x"] = 0

    if win["y"] < 0:
        win["y"] = 0

    if win["x"] > SCREENW - win["w"]:
        win["x"] = SCREENW - win["w"]

    if win["y"] > SCREENH - win["h"]:
        win["y"] = SCREENH - win["h"]


def fulldamage(win):

    # queue client area damage in screen space
    gx = int(win["x"])

    gy = int(win["y"])

    gw = int(win["w"])

    gh = int(win["h"])

    if gw > 0 and gh > 0:
        DAMAGERECTS.append([gx, gy, gw, gh])

    # only queue the chrome (frame + titlebar) area for framed windows
    try:

        role = str(win.get("role", ""))

    except Exception:

        role = ""

    if role == "window":

        fr = framedamagerect(win)

        if fr[2] > 0 and fr[3] > 0:
            DAMAGERECTS.append(fr)


def ismaximized(win):

    try:

        return bool(win.get("_max", False))

    except Exception:

        return False


def maximizewindow(wid):

    if wid not in windows:
        return

    win = windows[wid]

    ensuresrestore(win)

    insetleft, insettop, insetright, insetbottom = windowframeinsets(win)

    nx = WORKX + insetleft

    ny = WORKY + insettop

    nw = WORKW - insetleft - insetright

    nh = WORKH - insettop - insetbottom

    if nw < 1: nw = 1

    if nh < 1: nh = 1

    movewindow(win["cid"], {"winid": wid, "x": nx, "y": ny})

    resizewindow(win["cid"], {"winid": wid, "w": nw, "h": nh})

    win["_snap"] = None

    win["_max"] = True

    recordwindowattributes(win)


def fullscreenwindow(wid, enabled=True):

    if wid not in windows:
        return False

    win = windows[wid]

    if str(win.get("role", "")) != "window" or modalwindow(win):
        return False

    enabled = bool(enabled)

    if enabled == isfullscreen(win):
        return True

    oldvisual = gpuvisualrect(win) if GPUCOMPOSITOR else framedamagerect(win)
    DAMAGERECTS.append(list(oldvisual))

    if enabled:

        win["_fullscreen_restore"] = {
            "geometry": [int(win["x"]), int(win["y"]), int(win["w"]), int(win["h"])],
            "max": bool(win.get("_max", False)),
            "snap": win.get("_snap"),
            "restore": list(win["_restore"]) if isinstance(win.get("_restore"), (list, tuple)) else None,
            "scale": float(win.get("scale", 1.0)),
            "opacity": float(win.get("opacity", 1.0)),
            "blur": float(win.get("blur", 0.0)),
        }
        win["_fullscreen"] = True
        win["_max"] = False
        win["_snap"] = None
        win["scale"] = 1.0
        win["opacity"] = 1.0
        win["blur"] = 0.0
        movewindow(win["cid"], {
            "winid": wid,
            "x": 0,
            "y": 0,
            "_fullscreen_internal": True,
        })
        resizewindow(win["cid"], {
            "winid": wid,
            "w": int(SCREENW),
            "h": int(SCREENH),
            "_fullscreen_internal": True,
        })

    else:

        saved = win.get("_fullscreen_restore")
        win["_fullscreen"] = False
        win["_fullscreen_restore"] = None

        if isinstance(saved, dict):
            geometry = saved.get("geometry", [WORKX, WORKY, min(640, WORKW), min(480, WORKH)])
            rx, ry, rw, rh = [int(value) for value in geometry[:4]]
            movewindow(win["cid"], {
                "winid": wid,
                "x": rx,
                "y": ry,
                "_fullscreen_internal": True,
            })
            resizewindow(win["cid"], {
                "winid": wid,
                "w": rw,
                "h": rh,
                "_fullscreen_internal": True,
            })
            win["_max"] = bool(saved.get("max", False))
            win["_snap"] = saved.get("snap")
            if saved.get("restore") is None:
                win.pop("_restore", None)
            else:
                win["_restore"] = list(saved["restore"])
            win["scale"] = float(saved.get("scale", 1.0))
            win["opacity"] = float(saved.get("opacity", 1.0))
            win["blur"] = float(saved.get("blur", 0.0))

        fitwindowtoworkarea(wid)

    raisewindow(win["cid"], {"winid": wid})
    setfocus(wid)
    fulldamage(win)
    recordwindowattributes(win)
    return True


def setwindowfullscreen(cid, req):

    try:
        wid = int(req.get("winid", 0))
    except Exception:
        wid = 0

    if wid not in windows or windows[wid].get("cid") != cid:
        sendjson(cid, {"op": "ERROR", "code": "unknown_window"})
        return

    enabled = bool(req.get("fullscreen", True))

    if not fullscreenwindow(wid, enabled):
        sendjson(cid, {
            "op": "ERROR",
            "code": "fullscreen_denied",
            "detail": "only normal application windows can enter fullscreen",
        })
        return

    sendjson(cid, {
        "op": "WINDOW_STATE",
        "winid": wid,
        "state": "fullscreen" if enabled else ("maximized" if ismaximized(windows[wid]) else "normal"),
        "fullscreen": bool(enabled),
        "x": int(windows[wid]["x"]),
        "y": int(windows[wid]["y"]),
        "w": int(windows[wid]["w"]),
        "h": int(windows[wid]["h"]),
    })


def minimizewindow(wid):

    global FOCUSWID

    if wid not in windows:
        return

    win = windows[wid]

    role = str(win.get("role", ""))

    if role != "window" or modalwindow(win):
        return

    cid = win["cid"]

    # unmap the window so it disappears from the desktop
    unmapwindow(cid, {"winid": wid})

    # if this window had focus, move focus or clear it

    if FOCUSWID == wid:

        newfocus = None

        for twid in reversed(zorder):

            try:

                if twid in windows:

                    twin = windows[twid]

                    # skip unmapped or non-application roles
                    try:

                        trole = str(twin.get("role", ""))

                    except Exception:

                        trole = ""

                    if not twin.get("mapped"):
                        continue

                    if trole != "window":
                        continue

                    newfocus = twid
                    break

            except Exception:

                # ignore bad entries and keep scanning
                continue

        if newfocus is not None:

            try:

                setfocus(newfocus)

            except Exception:

                # focus change failure is non-fatal
                pass

        else:

            # no suitable window to focus
            FOCUSWID = None

            try:

                # tell taskbar/desktop that no window is focused
                ev = {
                    "op": "TASKBAR_WINDOW_FOCUS",
                    "winid": 0,
                    "current": str(windows[wid].get("current", ""))
                }

                broadcasttaskbarevent(ev)

            except Exception:

                # taskbar notification failure is non-fatal
                pass

def restorewindow(wid):

    if wid not in windows:
        return

    win = windows[wid]

    if "_restore" not in win:
        return

    rx, ry, rw, rh = win["_restore"]

    movewindow(win["cid"], {"winid": wid, "x": int(rx), "y": int(ry)})

    resizewindow(win["cid"], {"winid": wid, "w": int(rw), "h": int(rh)})

    win["_max"] = False

    win["_snap"] = None

    recordwindowattributes(win)


def endclientifnowindows(cid):


    if cid in clients and not clients[cid]["windows"]:

        sendjson(cid, {"op": "QUIT"})
        dropclient(cid, "no windows remain")

def movewindow(cid, req):

    try:

        wid = int(req.get("winid", 0))
        nx = int(req.get("x", 0))
        ny = int(req.get("y", 0))

        if wid not in windows or windows[wid]["cid"] != cid:
            sendjson(cid, {"op": "ERROR", "code": "unknown_window"})
            return

        if windows[wid]["role"] == "desktop":
            sendjson(cid, {"op": "ERROR", "code": "denied", "detail": "desktop pinned"})
            return

        if isfullscreen(windows[wid]) and not req.get("_fullscreen_internal"):
            sendjson(cid, {"op": "ERROR", "code": "denied", "detail": "fullscreen window geometry is pinned"})
            return

        # damage the old frame + client area
        DAMAGERECTS.append(framedamagerect(windows[wid]))
        DAMAGERECTS.append([windows[wid]["x"], windows[wid]["y"], windows[wid]["w"], windows[wid]["h"]])
        windows[wid]["x"] = nx
        windows[wid]["y"] = ny

        # normal windows may be partly off-screen if their titlebar is recoverable
        clampwindow(windows[wid], allowpartial=True)

        recordwindowattributes(windows[wid])

        # damage new frame + client
        fulldamage(windows[wid])

        sendjson(cid, {"op": "MOVED", "winid": wid, "x": windows[wid]["x"], "y": windows[wid]["y"]})

        log(f"window {wid} moved to {windows[wid]['x']},{windows[wid]['y']}")

    except Exception as e:
        sendjson(cid, {"op": "ERROR", "code": "move_failed", "detail": str(e)})


def topmostwindowat(x, y):

    try:

        for wid in reversed(zorder):

            if not windows[wid]["mapped"]:
                continue

            if windows[wid].get("role") == "tooltip":
                continue
            fx, fy, fw, fh = winframerect(windows[wid])

            if fx <= x < fx + fw and fy <= y < fy + fh:
                return wid

        return None

    except Exception:

        return None


def windowbufferdimensions(win):
    if win.get("_external_buffer"):
        return (
            max(1, int(win.get("buffer_source_width", win.get("w", 1)))),
            max(1, int(win.get("buffer_source_height", win.get("h", 1)))),
        )
    return max(1, int(win.get("w", 1))), max(1, int(win.get("h", 1)))


def windowbufferrecttooutput(win, rect, filtermargin=0):
    sourcewidth, sourceheight = windowbufferdimensions(win)
    outputwidth = max(1, int(win.get("w", 1)))
    outputheight = max(1, int(win.get("h", 1)))
    left, top, width, height = [int(value) for value in rect[:4]]
    margin = max(0, int(filtermargin))
    right = left + max(0, width) + margin
    bottom = top + max(0, height) + margin
    left -= margin
    top -= margin
    left = max(0, min(sourcewidth, left))
    top = max(0, min(sourceheight, top))
    right = max(left, min(sourcewidth, right))
    bottom = max(top, min(sourceheight, bottom))
    outputleft = (left * outputwidth) // sourcewidth
    outputtop = (top * outputheight) // sourceheight
    outputright = ((right * outputwidth) + sourcewidth - 1) // sourcewidth
    outputbottom = ((bottom * outputheight) + sourceheight - 1) // sourceheight
    return [
        outputleft,
        outputtop,
        max(0, outputright - outputleft),
        max(0, outputbottom - outputtop),
    ]


def resizewindow(cid, req):

    try:

        # parse resize request
        wid = int(req.get("winid", 0))

        nw = int(req.get("w", 0))

        nh = int(req.get("h", 0))

        # verify window ownership
        if wid not in windows or windows[wid]["cid"] != cid:
            sendjson(cid, {"op": "ERROR", "code": "unknown_window"})
            return

        # disallow desktop resize
        if windows[wid]["role"] == "desktop":
            sendjson(cid, {"op": "ERROR", "code": "denied", "detail": "desktop pinned"})
            return

        if isfullscreen(windows[wid]) and not req.get("_fullscreen_internal"):
            sendjson(cid, {"op": "ERROR", "code": "denied", "detail": "fullscreen window geometry is pinned"})
            return

        nw = max(1, min(int(SCREENW), nw))
        nh = max(1, min(int(SCREENH), nh))
        ownedpath = windows[wid].get(
            "_owned_buffer", windows[wid].get("buffer"))
        try:
            currentallocation = max(0, int(os.path.getsize(ownedpath)))
        except (OSError, TypeError, ValueError):
            currentallocation = 0
        growth = max(0, nw * nh * 4 - currentallocation)
        if not windowbufferallocationpermitted(cid, growth):
            sendjson(cid, {
                "op": "ERROR",
                "code": "denied",
                "detail": "client window-buffer budget exceeded",
            })
            return

        # damage old frame + client
        DAMAGERECTS.append(framedamagerect(windows[wid]))
        DAMAGERECTS.append([
            windows[wid]["x"],
            windows[wid]["y"],
            windows[wid]["w"],
            windows[wid]["h"]
        ])
        # apply logical size
        windows[wid]["w"] = nw

        windows[wid]["h"] = nh

        # clamp to screen
        clampwindow(windows[wid])

        # Keep the WindowServer-owned fallback usable while a validated
        # external producer buffer is attached. Never resize producer files.
        try:

            bufpath = windows[wid].get("_owned_buffer", windows[wid]["buffer"])

            try:
                current_bytes = os.path.getsize(bufpath)
            except Exception:
                current_bytes = 0

            target_bytes = windows[wid]["w"] * windows[wid]["h"] * 4

            if target_bytes < current_bytes:
                target_bytes = current_bytes

            # grow buffer file if needed
            if target_bytes > current_bytes:

                with open(bufpath, "r+b") as bf:

                    bf.truncate(target_bytes)

            if windows[wid].get("_external_buffer"):
                sourcepath = windows[wid]["buffer"]
                sourceoffset = max(0, int(windows[wid].get("buffer_offset", 0)))
                sourcestride = max(0, int(windows[wid].get("buffer_stride", 0)))
                sourcewidth, sourceheight = windowbufferdimensions(windows[wid])
                required = (
                    sourceoffset
                    + max(0, sourceheight - 1) * sourcestride
                    + sourcewidth * 4
                )

                if (
                    sourcestride < sourcewidth * 4
                    or os.path.getsize(sourcepath) < required
                ):
                    raise ValueError("external window buffer no longer covers its source surface")

        except PermissionError:

            sendjson(cid, {"op": "ERROR", "code": "denied", "detail": "buffer resize"})
            return

        except Exception as e:

            sendjson(cid, {"op": "ERROR", "code": "buffer_resize_failed", "detail": str(e)})
            return

        if not windows[wid].get("_external_buffer"):
            windows[wid]["buffer_stride"] = int(windows[wid]["w"]) * 4
            windows[wid]["buffer_offset"] = 0
            windows[wid]["buffer_source_width"] = int(windows[wid]["w"])
            windows[wid]["buffer_source_height"] = int(windows[wid]["h"])
            gpuwindowrelease(windows[wid])
            windows[wid]["damage"] = [[
                0,
                0,
                int(windows[wid]["w"]),
                int(windows[wid]["h"]),
            ]]
        # A logical-only resize scales an attached source texture to the new
        # output rectangle; it must redraw the output without re-uploading the
        # unchanged source pixels.
        fulldamage(windows[wid])

        # queue pending resize notify (coalesced in composeloop)
        windows[wid]["_resize_pending"] = True

        windows[wid]["_resize_pw"] = int(windows[wid]["w"])

        windows[wid]["_resize_ph"] = int(windows[wid]["h"])

        windows[wid]["_resize_pat"] = time.time()

        recordwindowattributes(windows[wid])

    except Exception as e:

        sendjson(cid, {"op": "ERROR", "code": "resize_failed", "detail": str(e)})


def raisewindow(cid, req):

    try:

        # parse
        wid = int(req.get("winid", 0))

        # verify
        if wid not in windows or windows[wid]["cid"] != cid:
            sendjson(cid, {"op": "ERROR", "code": "unknown_window"})
            return

        modalwid = modaldialogfor(wid)
        if modalwid in windows:
            wid = modalwid

        # desktop stays pinned at bottom
        if windows[wid]["role"] == "desktop":
            sendjson(cid, {"op": "RAISED", "winid": wid})
            return

        # adjust zorder
        if wid in zorder:
            zorder.remove(wid)

        zorder.append(wid)

        refreshcursormode()

        # mark damage
        fulldamage(windows[wid])

        # ack
        sendjson(cid, {"op": "RAISED", "winid": wid})

        # raise note
        log(f"window {wid} raised")

    except Exception as e:

        # raise error
        sendjson(cid, {"op": "ERROR", "code": "raise_failed", "detail": str(e)})


def setwindowcurrent(cid, msg):

    try:

        wid = int(msg.get("winid", 0))

        current = str(msg.get("current", "")).strip()[:128]

    except Exception as e:

        sendjson(cid, {"op": "ERROR", "code": "current_set_failed", "detail": str(e)})
        return

    if wid not in windows:

        sendjson(cid, {"op": "ERROR", "code": "unknown_window"})
        return

    owner = windows[wid].get("cid", None)

    if owner != cid:

        sendjson(cid, {"op": "ERROR", "code": "not_owner"})
        return

    windows[wid]["current"] = current

    sendjson(cid, {"op": "OK"})

    try:

        role = str(windows[wid].get("role", ""))

        if role == "window" and not modalwindow(windows[wid]):

            ev = {
                "op": "TASKBAR_WINDOW_CURRENT",
                "winid": wid,
                "current": current
            }

            broadcasttaskbarevent(ev)

    except Exception as e:

        log(f"current broadcast error {e}")


# kill functions
def pendingkillidentityvalid(info, pid=None):

    if not isinstance(info, dict):
        return False

    state = clients.get(info.get("cid"))
    expected = info.get("identity")
    current = state.get("identity") if state else None

    if not isinstance(expected, dict):
        return False

    if pid is not None and int(expected.get("pid", 0)) != int(pid):
        return False

    return bool(
        sameprocessidentity(current, expected)
        and processidentityalive(current)
    )


def pendingkilladd(pid, cid, wid, timeout=0.35):

    ipid = int(pid)

    existing = PENDINGKILLS.get(ipid)
    if existing is not None:
        dialogwid = existing.get("dialog_wid")
        if dialogwid in windows:
            setfocus(dialogwid)
            raisewindow(windows[dialogwid]["cid"], {"winid": dialogwid})
        return

    PENDINGKILLS[ipid] = {
        "cid": cid,
        "wid": wid,
        "deadline": time.time() + float(timeout),
        "dialog_wid": None,
        "identity": clients.get(cid, {}).get("identity"),
    }

    win = windows.get(wid)
    if win is not None:
        win["cursor_busy"] = True
        refreshcursormode()


def pendingkillremove(pid):

    ipid = int(pid)
    info = PENDINGKILLS.pop(ipid, None)
    if info is None:
        return

    win = windows.get(info.get("wid"))
    if win is not None:
        win.pop("cursor_busy", None)
        refreshcursormode()

    dialogwid = info.get("dialog_wid")
    if (
        dialogwid in windows
        and windows[dialogwid].get("_kill_prompt_pid") == ipid
    ):
        destroywindow(dialogwid, note="close acknowledged")


def pendingkillpulse():

    now = time.time()

    for ipid, info in list(PENDINGKILLS.items()):


        if now < float(info.get("deadline", 0)):
            continue

        dialogwid = info.get("dialog_wid")
        if dialogwid in windows:
            continue

        cid = info.get("cid")
        wid = info.get("wid")
        win = windows.get(wid)
        try:
            livepid = int(win.get("pid")) if win is not None else None
        except Exception:
            livepid = None

        if (
            win is None
            or cid not in clients
            or win.get("cid") != cid
            or livepid != ipid
            or not pendingkillidentityvalid(info, ipid)
        ):
            PENDINGKILLS.pop(ipid, None)
            continue

        # Attach the prompt to the topmost modal descendant so it remains
        # reachable even if the application already has a dialog open.
        promptparent = wid
        seen = set()
        while promptparent not in seen:
            seen.add(promptparent)
            childwid = modaldialogfor(promptparent)
            if childwid not in windows:
                break
            promptparent = childwid

        promptcid = windows[promptparent].get("cid")
        if promptcid not in clients:
            PENDINGKILLS.pop(ipid, None)
            continue

        dialogwid = createdialog(promptcid, {
            "parent": promptparent,
            "dialog_id": f"windowserver.kill.{ipid}",
            "title": "operation not responding",
            "message": "this operation is not responding. kill operation?",
            "buttons": [
                {"id": "kill", "label": "kill"},
                {"id": "cancel", "label": "cancel", "cancel": True},
            ],
            "default": 1,
        })

        if dialogwid in windows:
            windows[dialogwid]["_kill_prompt_pid"] = ipid
            info["dialog_wid"] = dialogwid
        else:
            # A transient modal/lifecycle race should not make closing the
            # window destructive. Try to present the choice again later.
            info["deadline"] = now + 1.0


# show desktop functions
def showdesktop(cid):


    # only allow desktop/taskbar controllers
    if cid not in DESKTOPCLIENTS:

        return

    try:

        # check current toggle state
        active = bool(SHOWDESKTOPSTATE.get("active"))

    except Exception:

        active = False

    # --------------------------------------------------
    # first press: capture visible app windows and minimise
    # --------------------------------------------------
    if not active:


        # reset stored window list
        SHOWDESKTOPSTATE["windows"] = []


        # walk zorder so we remember them in front-to-back order
        for wid in list(zorder):

            try:

                if wid not in windows:
                    continue

                win = windows[wid]

                role = str(win.get("role", ""))

                # skip system surfaces
                if role != "window":
                    continue

                # only capture currently visible windows
                if not win.get("mapped"):
                    continue

                SHOWDESKTOPSTATE["windows"].append(wid)

            except Exception:

                continue


        # minimise each captured window
        for wid in list(SHOWDESKTOPSTATE.get("windows", [])):

            try:

                minimizewindow(wid)

            except Exception:

                # minimise failure for one window is non-fatal
                continue


        # mark show desktop as active
        SHOWDESKTOPSTATE["active"] = True

        return

    # --------------------------------------------------
    # second press: restore previously captured windows
    # --------------------------------------------------
    prev = []

    try:

        prev = list(SHOWDESKTOPSTATE.get("windows", []))

    except Exception:

        prev = []


    for wid in prev:

        try:

            if wid not in windows:
                continue

            win = windows[wid]

            role = str(win.get("role", ""))

            # still skip system roles
            if role != "window":
                continue

            # if already mapped (user restored manually), skip
            if win.get("mapped"):
                continue

            owner = win.get("cid", None)

            # mark as mapped again
            win["mapped"] = True

            try:

                # restore zorder and damage just like TASKBAR_ACTIVATE does
                if role == "desktop":

                    if wid in zorder:
                        zorder.remove(wid)

                    zorder.insert(0, wid)

                    tildamage(win, tilesz=256)

                else:

                    if wid in zorder:
                        zorder.remove(wid)

                    zorder.append(wid)

                    fulldamage(win)

            except Exception:

                pass

            try:

                # notify owning client
                if owner is not None and owner in clients:

                    sendjson(owner, {"op": "WINDOW_MAPPED", "winid": wid})

            except Exception:

                pass

            try:

                # re-broadcast to taskbar for normal app windows
                if role == "window" and not modalwindow(win):

                    ev = {
                        "op": "TASKBAR_WINDOW_MAPPED",
                        "winid": wid
                    }

                    broadcasttaskbarevent(ev)

            except Exception:

                pass

        except Exception:

            continue


    # restore focus to the frontmost window we just brought back
    refreshcursormode()

    for wid in reversed(prev):

        try:

            if wid in windows and windows[wid].get("mapped"):

                setfocus(wid)

                break

        except Exception:

            continue


    # clear toggle state
    SHOWDESKTOPSTATE["active"] = False

    SHOWDESKTOPSTATE["windows"] = []


def windowclose(cid, msg):

    try:

        wid = int(msg.get("winid", 0))

        if wid not in windows:

            sendjson(cid, {"op": "ERROR", "code": "unknown_window"})

            return

        if cid not in DESKTOPCLIENTS:

            sendjson(cid, {"op": "ERROR", "code": "denied"})

            return

        win = windows[wid]

        role = str(win.get("role", ""))

        if role != "window":

            sendjson(cid, {"op": "ERROR", "code": "denied"})

            return

        owner = win.get("cid", None)

        if owner is None or owner not in clients:

            sendjson(cid, {"op": "ERROR", "code": "not_owner"})

            return

        sendjson(owner, {"op": "CLOSE", "winid": wid})

        pid = win.get("pid", None)

        if pid is not None:
            pendingkilladd(pid, owner, wid, timeout=0.35)

    except Exception as e:

        sendjson(cid, {"op": "ERROR", "code": "close_failed", "detail": str(e)})


def taskbaractivate(cid, msg):

    try:

        wid = int(msg.get("winid", 0))

        if wid not in windows:

            sendjson(cid, {"op": "ERROR", "code": "unknown_window"})
            return

        # only allow desktop/taskbar controllers to do this
        if cid not in DESKTOPCLIENTS:

            sendjson(cid, {"op": "ERROR", "code": "denied"})
            return

        win = windows[wid]

        try:
            role = str(win.get("role", ""))
        except Exception:
            role = ""

        try:
            owner = win.get("cid", None)
        except Exception:
            owner = None

        try:
            ismapped = bool(win.get("mapped"))
        except Exception:
            ismapped = False

        # determine if this window is the topmost "normal" app in zorder
        try:

            topnormal = None

            for twid in reversed(zorder):


                twin = windows.get(twid)

                if not twin:
                    continue

                trole = str(twin.get("role", ""))

                if trole != "window":
                    continue

                topnormal = twid
                break

            isfrontapp = (topnormal == wid)

        except Exception:

            isfrontapp = False


        # if this is the frontmost mapped app window, toggle to minimized
        if ismapped and isfrontapp and role == "window":

            minimizewindow(wid)
            return

        if not win.get("mapped"):

            win["mapped"] = True


            if role == "desktop":

                if wid in zorder:
                    zorder.remove(wid)

                zorder.insert(0, wid)

                tildamage(win, tilesz=256)

            else:

                if wid in zorder:
                    zorder.remove(wid)

                zorder.append(wid)

                fulldamage(win)


            # notify owning client that its window is mapped again
            if owner is not None and owner in clients:

                sendjson(owner, {"op": "WINDOW_MAPPED", "winid": wid})


            # re-broadcast taskbar mapped event for normal app windows
            if role == "window" and not modalwindow(win):

                ev = {
                    "op": "TASKBAR_WINDOW_MAPPED",
                    "winid": wid
                }

                broadcasttaskbarevent(ev)

        else:

            # already visible: just raise and damage

            if wid in zorder:
                zorder.remove(wid)

            zorder.append(wid)

            fulldamage(win)


        # make this the focused window (will also drive TASKBAR_WINDOW_FOCUS)
        refreshcursormode()
        setfocus(wid, reaffirm=True)

    except Exception as e:

        sendjson(cid, {"op": "ERROR", "code": "taskbar_activate_failed", "detail": str(e)})
def windowgeo(win):

    try:
        x = int(win["x"])
        y = int(win["y"])
        w = int(win["w"])
        h = int(win["h"])
        return x, y, w, h
    except Exception:
        return 0, 0, 1, 1


def getcursorsize(mode):

    try:

        if mode in CURSORSIZES:

            return CURSORSIZES[mode]

        box = cursorbox(0, 0, mode)

        try:

            w = int(box[2])
            h = int(box[3])

        except Exception:

            w = 24
            h = 24

        if w <= 0:
            w = 24

        if h <= 0:
            h = 24

        CURSORSIZES[mode] = (w, h)

        return w, h

    except Exception:

        return 24, 24



def pointercursorbox(x, y, mode):

    try:

        mx = int(x)
        my = int(y)

        if mode == "hidden":

            return [mx, my, 0, 0]

        if mode in CURSORCENTERED:

            w, h = getcursorsize(mode)

            cx = mx - w // 2
            cy = my - h // 2

            return [cx, cy, w, h]

        if mode == "link":

            w, h = getcursorsize(mode)

            # The hand artwork's active fingertip is seven pixels into its
            # 32-pixel source. Keep that point fixed on the logical pointer.
            return [mx - int(round(w * (7.0 / 32.0))), my, w, h]

        box = cursorbox(mx, my, mode)

        try:

            bx = int(box[0])
            by = int(box[1])
            bw = int(box[2])
            bh = int(box[3])

            return [bx, by, bw, bh]

        except Exception:

            return [mx, my, 0, 0]

    except Exception:

        try:

            box = cursorbox(int(x), int(y), mode)

            return [int(box[0]), int(box[1]), int(box[2]), int(box[3])]

        except Exception:

            return [int(x), int(y), 0, 0]


def computecursormode(x, y):

    try:

        mx = int(x)

        my = int(y)

        gwid = POINTERGRAB.get("wid")
        gbtn = int(POINTERGRAB.get("btn", 0))

        if (
            gwid in windows
            and windows[gwid].get("mapped")
            and gbtn in BTNDOWN
            and not DRAGINFO.get("wid")
        ):
            return str(windows[gwid].get("cursor_mode", "arrow"))

        wid = topmostwindowat(mx, my)

        if wid not in windows:

            return "arrow"

        win = windows[wid]

        if win.get("role") != "window":

            # System-owned surfaces such as the taskbar still have interactive
            # controls. Honour their requested cursor mode on hover; their
            # default remains the normal arrow.
            return str(win.get("cursor_mode", "arrow"))

        hit = framehittest(mx, my, win)

        if not hit:

            return "arrow"

        kind, area = hit

        if kind == "client":

            if bool(win.get("cursor_busy")):

                return "busy"

            if win.get("standard_dialog"):

                inputrect = win.get("dialog_input_rect")

                if isinstance(inputrect, (list, tuple)) and len(inputrect) == 4:

                    localx = mx - int(win.get("x", 0))
                    localy = my - int(win.get("y", 0))
                    rx, ry, rw, rh = [int(value) for value in inputrect]

                    if rx <= localx < rx + rw and ry <= localy < ry + rh:

                        return "text"

            return str(win.get("cursor_mode", "arrow"))

        if kind != "resize" or not area:

            return "arrow"

        if area in ("left", "right"):

            return "resize_h"

        if area in ("top", "bottom"):

            return "resize_v"

        if area in ("topleft", "bottomright"):

            return "resize_diag2"

        if area in ("topright", "bottomleft"):

            return "resize_diag1"

        return "arrow"

    except Exception:

        return "arrow"


def cursormodeset(cid, msg):

    try:

        wid = int(msg.get("winid", 0))

        if wid not in windows or windows[wid]["cid"] != cid:
            sendjson(cid, {"op": "ERROR", "code": "unknown_window"})
            return

        mode = str(msg.get("mode", "arrow"))
        allowed = (
            "arrow", "link", "text", "busy", "hidden",
            "resize_h", "resize_v", "resize_diag1", "resize_diag2",
        )

        if mode not in allowed:
            sendjson(cid, {"op": "ERROR", "code": "invalid_cursor_mode", "detail": mode})
            return

        windows[wid]["cursor_mode"] = mode
        refreshcursormode()

        sendjson(cid, {"op": "OK"})

    except Exception as e:

        sendjson(cid, {"op": "ERROR", "code": "cursor_mode_set_failed", "detail": str(e)})


def cursorset(cid, msg):

    try:

        # only allow desktop controllers to toggle cursor globally
        if cid not in DESKTOPCLIENTS:

            sendjson(cid, {"op": "ERROR", "code": "denied"})
            return

    except Exception:

        sendjson(cid, {"op": "ERROR", "code": "denied"})
        return

    try:

        enabled = bool(msg.get("enabled", True))

    except Exception:

        enabled = True

    try:

        global CURSORENABLED, CURSORDIRTY

        CURSORENABLED = enabled

        CURSORDIRTY = True

        # ensure repaint happens (cursor box damage)

        if LASTCURSOR and len(LASTCURSOR) == 4:

            DAMAGERECTS.append(LASTCURSOR)

        sendjson(cid, {"op": "OK"})

    except Exception as e:

        sendjson(cid, {"op": "ERROR", "code": "cursor_set_failed", "detail": str(e)})
def framehittest(x, y, win):

    try:

        gx, gy, gw, gh = windowgeo(win)

        fx, fy, fw, fh = winframerect(win)

        if not (fx <= x < fx + fw and fy <= y < fy + fh):
            return None

        if isfullscreen(win):
            return ("client", None)

        close_x, close_y, max_x, max_y, min_x, min_y = windowbuttonrects(win)
        hoverrects = windowbuttonhoverrects(win)
        close = hoverrects.get("close", (close_x, close_y, BTNWH, BTNWH))
        maxb = hoverrects.get("max", (max_x, max_y, BTNWH, BTNWH))
        minb = hoverrects.get("min", (min_x, min_y, BTNWH, BTNWH))

        if close[0] <= x < close[0] + close[2] and close[1] <= y < close[1] + close[3]:
            return ("button", "close")

        # Dialog chrome exposes only the close control. The remaining titlebar
        # is draggable and the dialog body/edges stay fixed-size.
        if win.get("standard_dialog"):
            tx = fx + FRAMEW
            if tx <= x < close_x - BTNGAP and fy + FRAMEW <= y < fy + FRAMEW + TITLEH:
                return ("title", None)
            return ("client", None)

        if win.get("modal_child"):
            tx = fx + FRAMEW
            if tx <= x < close_x - BTNGAP and fy + FRAMEW <= y < fy + FRAMEW + TITLEH:
                return ("title", None)

        elif maxb[0] <= x < maxb[0] + maxb[2] and maxb[1] <= y < maxb[1] + maxb[3]:
            return ("button", "max")

        if not win.get("modal_child") and minb[0] <= x < minb[0] + minb[2] and minb[1] <= y < minb[1] + minb[3]:
            return ("button", "min")

        if clientchromemode(win):
            dragrect = clientdragrect(win)

            if dragrect is not None:
                dragx, dragy, dragw, dragh = dragrect

                if dragx <= x < dragx + dragw and dragy <= y < dragy + dragh:
                    return ("title", None)

        else:
            tx = fx + FRAMEW
            tw = fw - FRAMEW * 2 - (BTNGAP + BTNWH) * 3 - BTNGAP

            if tx <= x < tx + tw and fy + FRAMEW <= y < fy + FRAMEW + TITLEH:
                return ("title", None)

        if ismaximized(win):
            return ("client", None)

        edge = HITEDGE

        corner = HITCORNER

        frame_left = fx

        frame_top = fy

        frame_right = fx + fw

        frame_bottom = fy + fh

        on_left_edge = (frame_left <= x < frame_left + edge)

        on_right_edge = (frame_right - edge <= x < frame_right)

        on_top_edge = (frame_top <= y < frame_top + edge)

        on_bottom_edge = (frame_bottom - edge <= y < frame_bottom)

        near_left = (frame_left <= x < frame_left + corner)

        near_right = (frame_right - corner <= x < frame_right)

        near_top = (frame_top <= y < frame_top + corner)

        near_bottom = (frame_bottom - corner <= y < frame_bottom)

        if near_left and near_top:
            return ("resize", "topleft")

        if near_right and near_top:
            return ("resize", "topright")

        if near_left and near_bottom:
            return ("resize", "bottomleft")

        if near_right and near_bottom:
            return ("resize", "bottomright")

        if on_left_edge and frame_top <= y < frame_bottom:
            return ("resize", "left")

        if on_right_edge and frame_top <= y < frame_bottom:
            return ("resize", "right")

        if on_top_edge and frame_left <= x < frame_right:
            return ("resize", "top")

        if on_bottom_edge and frame_left <= x < frame_right:
            return ("resize", "bottom")

        return ("client", None)

    except Exception:

        return None


# damage and compose functions
def setwindoweffects(cid, req):

    try:

        wid = int(req.get("winid", 0))

        if wid not in windows or windows[wid]["cid"] != cid:
            sendjson(cid, {"op": "ERROR", "code": "unknown_window"})
            return

        win = windows[wid]
        oldvisual = gpuvisualrect(win) if GPUCOMPOSITOR else framedamagerect(win)

        if "opacity" in req:
            win["opacity"] = max(0.0, min(1.0, float(req["opacity"])))

        if "scale" in req:
            win["scale"] = max(0.25, min(4.0, float(req["scale"])))

        if "shadow" in req:
            win["shadow"] = bool(req["shadow"])

        if "blur" in req:
            win["blur"] = float(GPUBLURRADIUS) if req["blur"] is True else max(0.0, min(32.0, float(req["blur"])))

        if "theme" in req:
            theme = str(req["theme"]).lower()

            if theme not in GRAPHICSTHEMES:
                raise ValueError("unsupported graphics theme")

            win["theme"] = theme

        if "transition_style" in req:
            style = str(req["transition_style"]).lower()

            if style not in ("fade", "scale", "slide", "fade_scale"):
                raise ValueError("unsupported transition style")

            win["transition_style"] = style

        if "transition_easing" in req:
            easing = str(req["transition_easing"]).lower()

            if easing not in GPUANIMATIONEASINGS:
                raise ValueError("unsupported transition easing")

            win["transition_easing"] = easing

        if "pixel_alpha" in req:

            pixelalpha = bool(req["pixel_alpha"])

            if pixelalpha != bool(win.get("pixel_alpha", False)):
                win["pixel_alpha"] = pixelalpha
                gpuwindowrelease(win)

        if req.get("transition", False) or "transition_ms" in req:
            duration = int(req.get("transition_ms", GPUTRANSITIONMS))
            win["_gpu_transition_start"] = time.monotonic()
            win["_gpu_transition_ms"] = max(0, min(5000, duration))

        DAMAGERECTS.append(oldvisual)
        fulldamage(win)
        sendjson(cid, {
            "op": "WINDOW_EFFECTS_SET",
            "winid": wid,
            "opacity": float(win.get("opacity", 1.0)),
            "scale": float(win.get("scale", 1.0)),
            "shadow": bool(win.get("shadow", False)),
            "pixel_alpha": bool(win.get("pixel_alpha", False)),
            "blur": float(win.get("blur", 0.0)),
            "theme": graphicswindowthemename(win),
            "transition_style": str(win.get("transition_style", "fade_scale")),
            "transition_easing": str(win.get("transition_easing", "ease_out")),
        })

    except Exception as e:
        sendjson(cid, {"op": "ERROR", "code": "effects_failed", "detail": str(e)})


def graphicscapabilities():

    state = backendinfo()
    videosurfaces = bool(GPUCOMPOSITOR and gpuvideoavailable() and VIDEOSERVER is not None)

    return {
        "version": GPUCOMMANDAPIVERSION,
        "backend": str(state.get("backend", "none")),
        "connector": state.get("connector"),
        "display_adjustment": displayadjustment(),
        "accelerated": bool(GPUCOMPOSITOR and gpuavailable()),
        "managed_resources": True,
        "raw_shaders": False,
        "fallback": "shared_buffer",
        "fallback_required": True,
        "atomic_scene": True,
        "retained_scene": True,
        "stable_node_ids": True,
        "offscreen_layers": True,
        "offscreen_layer_cache": True,
        "partial_scene_rendering": True,
        "primitive_batching": ["rectangle", "rounded_rectangle", "border", "circle", "line", "gradient", "text"],
        "controlled_effects": ["opacity", "scale", "rotation", "shadow", "transition", "backdrop_blur", "grayscale", "invert", "sepia"],
        "controlled_3d": {
            "depth_buffer": True,
            "projections": ["perspective", "orthographic"],
            "primitives": ["cube", "plane", "sphere", "custom"],
            "lighting": ["ambient", "directional", "specular"],
            "postprocess": ["none", "grayscale", "invert", "sepia"],
            "fog": True,
            "wireframe": True,
            "antialiasing": ["auto", "analytic", "quality"],
            "hardware_supersample": 2,
            "server_animation": True,
            "mesh_limit": GPUCOMMAND3DMESHLIMIT,
            "vertex_limit": GPUCOMMAND3DVERTEXLIMIT,
            "index_limit": GPUCOMMAND3DINDEXLIMIT,
        },
        "themes": sorted(GRAPHICSTHEMES),
        "theme": GRAPHICSTHEME,
        "ui_scale": float(GPUUISCALE),
        "backdrop_blur": bool(GPUBLUR),
        "node_animation": {
            "properties": list(GPUANIMATIONPROPERTIES),
            "easings": list(GPUANIMATIONEASINGS),
            "duration_limit_ms": GPUANIMATIONDURATIONLIMIT,
            "window_limit": GPUANIMATIONLIMIT,
        },
        "damage_regions": True,
        "legacy_transactions": True,
        "commands": ["rectangle", "rounded_rectangle", "border", "line", "circle", "gradient", "image", "text", "group", "layer", "scene3d", *(["video"] if videosurfaces else [])],
        "video_surfaces": {
            "available": videosurfaces,
            "socket": VIDEOSOCKPATH if videosurfaces else None,
            "transport": "dma_buf",
            "zero_copy_decode": videosurfaces,
            "gpu_copy_composition": videosurfaces,
            "maximum_streams": VIDEOMAXSTREAMS,
            "maximum_in_flight": 16,
            "drm_driver": state.get("drm_driver"),
            "render_node": state.get("render_node"),
            "render_identity": state.get("render_identity"),
            "import_capabilities": gpuvideoimportcapabilities(
                include_modifiers=False,
                probe=False,
            ) if videosurfaces else {
                "available": False,
                "formats": [],
                "modifier_query": False,
            },
        },
        "command_limit": GPUCOMMANDLIMIT,
        "total_command_limit": GPUCOMMANDTOTALLIMIT,
        "text_limit": GPUCOMMANDTEXTLIMIT,
        "console_grid_item_limit": GPUCOMMANDGRIDITEMLIMIT,
        "image_pixel_limit": GPUCOMMANDIMAGEPIXELS,
        "damage_limit": GPUCOMMANDDAMAGELIMIT,
        "layer_limit": GPUCOMMANDLAYERLIMIT,
    }


def gpuanimationeased(progress, easing):

    progress = max(0.0, min(1.0, float(progress)))
    easing = str(easing).lower()

    if easing == "ease_in":
        return progress * progress * progress

    if easing == "ease_out":
        return 1.0 - ((1.0 - progress) ** 3)

    if easing == "ease_in_out":
        return 4.0 * progress * progress * progress if progress < 0.5 else 1.0 - ((-2.0 * progress + 2.0) ** 3) / 2.0

    return progress


def gpuanimationvalue(propertyname, value):

    propertyname = str(propertyname).lower()

    if propertyname == "opacity":
        return max(0.0, min(1.0, float(value)))

    if propertyname == "rotation":
        return max(-3600.0, min(3600.0, float(value)))

    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"graphics {propertyname} animation requires two values")

    if propertyname == "translate":
        return [max(-1000000.0, min(1000000.0, float(item))) for item in value]

    if propertyname == "scale":
        return [max(0.01, min(16.0, float(item))) for item in value]

    raise ValueError("unsupported graphics animation property")


def graphicsanimate(cid, req):

    try:
        wid, win = graphicswindow(cid, req)
        nodeid = str(req.get("id", ""))[:128]
        propertyname = str(req.get("property", "")).lower()
        easing = str(req.get("easing", "ease_out")).lower()
        duration = max(1, min(GPUANIMATIONDURATIONLIMIT, int(req.get("duration_ms", 180))))

        if not nodeid or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", nodeid):
            raise ValueError("graphics animation requires a stable node id")

        if propertyname not in GPUANIMATIONPROPERTIES:
            raise ValueError("unsupported graphics animation property")

        if easing not in GPUANIMATIONEASINGS:
            raise ValueError("unsupported graphics animation easing")

        command = next((value for value in win.get("gpu_commands", []) if str(value.get("id", "")) == nodeid), None)

        if command is None:
            raise ValueError("graphics animation node does not exist")

        default = 1.0 if propertyname == "opacity" else (0.0 if propertyname == "rotation" else ([1.0, 1.0] if propertyname == "scale" else [0.0, 0.0]))
        startvalue = gpuanimationvalue(propertyname, req.get("from", command.get(propertyname, default)))
        endvalue = gpuanimationvalue(propertyname, req.get("to"))
        animations = GPUANIMATIONS.setdefault(wid, [])
        animations[:] = [value for value in animations if not (value["id"] == nodeid and value["property"] == propertyname)]

        if len(animations) >= GPUANIMATIONLIMIT:
            raise ValueError("graphics animation limit reached")

        animations.append({
            "id": nodeid,
            "property": propertyname,
            "from": startvalue,
            "to": endvalue,
            "start": time.monotonic(),
            "duration": duration / 1000.0,
            "easing": easing,
        })
        DAMAGERECTS.append(gpuvisualrect(win) if GPUCOMPOSITOR else framedamagerect(win))
        sendjson(cid, {
            "op": "GRAPHICS_ANIMATING",
            "winid": wid,
            "id": nodeid,
            "property": propertyname,
            "duration_ms": duration,
            "easing": easing,
        })

    except KeyError:
        sendjson(cid, {"op": "ERROR", "code": "unknown_window"})
    except Exception as e:
        sendjson(cid, {"op": "ERROR", "code": "graphics_animation_failed", "detail": str(e)})
        log(f"graphics_animation_failed wid={req.get('winid')} err={e}")


def gpuanimationoverrides(win):

    wid = int(win.get("id", 0))
    animations = GPUANIMATIONS.get(wid, [])

    if not animations:
        return {}

    commands = {str(command.get("id", "")): command for command in win.get("gpu_commands", []) if command.get("id")}
    now = time.monotonic()
    output = {}
    remaining = []

    for animation in animations:
        command = commands.get(animation["id"])

        if command is None:
            continue

        progress = (now - float(animation["start"])) / max(0.001, float(animation["duration"]))
        eased = gpuanimationeased(progress, animation["easing"])
        startvalue = animation["from"]
        endvalue = animation["to"]

        if isinstance(startvalue, list):
            current = [float(startvalue[index]) + (float(endvalue[index]) - float(startvalue[index])) * eased for index in range(2)]
        else:
            current = float(startvalue) + (float(endvalue) - float(startvalue)) * eased

        output.setdefault(animation["id"], {})[animation["property"]] = current

        if progress < 1.0:
            remaining.append(animation)
        else:
            command[animation["property"]] = endvalue

    if remaining:
        GPUANIMATIONS[wid] = remaining
    else:
        GPUANIMATIONS.pop(wid, None)

    return output


def graphicstelemetry(cid):

    owned = []
    state = backendinfo()
    state["window_compositor"] = "gpu" if GPUCOMPOSITOR else "cpu"
    state["gpu_failed"] = bool(GPUFAILED)

    for wid in clients.get(cid, {}).get("windows", []):

        win = windows.get(wid)

        if win is None:
            continue

        owned.append({
            "winid": int(wid),
            "role": str(win.get("role", ""))[:32],
            "mapped": bool(win.get("mapped")),
            "managed_only": bool(win.get("_managed_only", False)),
            "commands": len(win.get("gpu_commands", [])),
            "generation": int(win.get("_gpu_command_generation", 0)),
            "presented_generation": int(
                win.get("_gpu_presented_generation", 0)
            ),
            "presentation_receipts_pending": len(
                win.get("_gpu_commit_receipts", [])
            ),
            "scene_commits": int(win.get("_telemetry_scene_commits", 0)),
            "scene_clears": int(win.get("_telemetry_scene_clears", 0)),
            "patch_commits": int(win.get("_telemetry_patch_commits", 0)),
                "cpu_damage_bytes": int(win.get("_telemetry_cpu_damage_bytes", 0)),
                "cpu_damage_events": int(win.get("_telemetry_cpu_damage_events", 0)),
                "cpu_damage_coalesces": int(win.get("_telemetry_cpu_damage_coalesces", 0)),
                "cpu_damage_pending_peak": int(win.get("_telemetry_cpu_damage_pending_peak", 0)),
                "gpu_upload_bytes": int(win.get("_telemetry_gpu_upload_bytes", 0)),
            "gpu_draw_calls": int(win.get("_telemetry_gpu_draw_calls", 0)),
            "scene_texture_renders": int(win.get("_telemetry_scene_texture_renders", 0)),
            "scene_texture_hits": int(win.get("_telemetry_scene_texture_hits", 0)),
            "scene_texture_full_renders": int(win.get("_telemetry_scene_texture_full_renders", 0)),
            "scene_texture_partial_renders": int(win.get("_telemetry_scene_texture_partial_renders", 0)),
            "scene_texture_damage_pixels": int(win.get("_telemetry_scene_texture_damage_pixels", 0)),
            "scene_commands_considered": int(win.get("_telemetry_scene_commands_considered", 0)),
            "scene_commands_culled": int(win.get("_telemetry_scene_commands_culled", 0)),
            "scene_commands_drawn": int(win.get("_telemetry_scene_commands_drawn", 0)),
            "layer_texture_renders": int(win.get("_telemetry_layer_texture_renders", 0)),
            "layer_texture_hits": int(win.get("_telemetry_layer_texture_hits", 0)),
            "fallbacks": int(win.get("_telemetry_fallbacks", 0)),
        })

    sendjson(cid, {
        "op": "GRAPHICS_TELEMETRY",
        "state": state,
        "windows": owned,
        "compositor": {
            "scene_partial_renders": sum(int(win.get("_telemetry_scene_texture_partial_renders", 0)) for win in windows.values()),
            "scene_command_culls": sum(int(win.get("_telemetry_scene_commands_culled", 0)) for win in windows.values()),
            "layer_texture_renders": sum(int(win.get("_telemetry_layer_texture_renders", 0)) for win in windows.values()),
            "layer_texture_hits": sum(int(win.get("_telemetry_layer_texture_hits", 0)) for win in windows.values()),
            "presentation_receipts_pending": (
                len(GPUPENDINGCOMMITRECEIPTS)
                + len(GPUCAPTUREDCOMMITRECEIPTS)
                + len(GPUDEFERREDCOMMITRECEIPTS)
                + sum(
                    len(win.get("_gpu_commit_receipts", []))
                    for win in windows.values()
                )
            ),
            "presentation_receipts_page_flip": len(
                GPUPENDINGCOMMITRECEIPTS
            ),
            "presentation_receipts_captured": len(
                GPUCAPTUREDCOMMITRECEIPTS
            ),
            "presentation_receipts_deferred": len(
                GPUDEFERREDCOMMITRECEIPTS
            ),
            "managed_command_errors": int(GPUCOMMANDERRORS),
            "managed_command_last_error": str(GPUCOMMANDLASTERROR),
        },
        "command_errors": int(GPUCOMMANDERRORS),
        "gpu_failed": bool(GPUFAILED),
    })


def graphicswindow(cid, req):

    wid = int(req.get("winid", 0))

    if wid not in windows or windows[wid].get("cid") != cid:
        raise KeyError("unknown_window")

    return wid, windows[wid]


def graphicscolor(value, default=(255, 255, 255, 255)):

    if value is None:
        return list(default)

    if isinstance(value, int):
        return [
            (int(value) >> 16) & 0xFF,
            (int(value) >> 8) & 0xFF,
            int(value) & 0xFF,
            255,
        ]

    if isinstance(value, str) and value.startswith("#") and len(value) in (7, 9):

        raw = value[1:]
        output = [int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)]

        if len(raw) == 8:
            output.append(int(raw[6:8], 16))
        else:
            output.append(255)

        return output

    if not isinstance(value, (list, tuple)) or len(value) not in (3, 4):
        raise ValueError("color must contain RGB or RGBA channels")

    output = [max(0, min(255, int(channel))) for channel in value]

    if len(output) == 3:
        output.append(255)

    return output


def graphicslocalrect(win, value, default=None):

    if value is None:
        value = default

    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError("rectangle must contain x, y, width, and height")

    x, y, width, height = [int(item) for item in value]
    limitwidth = int(win.get("w", 0))
    limitheight = int(win.get("h", 0))

    if x < 0:
        width += x
        x = 0

    if y < 0:
        height += y
        y = 0

    width = min(width, limitwidth - x)
    height = min(height, limitheight - y)

    if width < 1 or height < 1:
        raise ValueError("rectangle is outside the window")

    return [x, y, width, height]


def graphicsdestinationrect(win, value):

    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError("rectangle must contain x, y, width, and height")

    x, y, width, height = [int(item) for item in value]

    if width < 1 or height < 1:
        raise ValueError("rectangle dimensions must be positive")

    intersection = rectintersect(x, y, width, height, 0, 0, int(win.get("w", 0)), int(win.get("h", 0)))

    if intersection[2] < 1 or intersection[3] < 1:
        raise ValueError("rectangle is outside the window")

    return [x, y, width, height]


def graphicsbegin(cid, req):

    try:

        wid, win = graphicswindow(cid, req)
        win["_gpu_commands_pending"] = []
        sendjson(cid, {"op": "GRAPHICS_BEGUN", "winid": wid, "limit": GPUCOMMANDLIMIT})

    except KeyError:
        sendjson(cid, {"op": "ERROR", "code": "unknown_window"})
    except Exception as e:
        sendjson(cid, {"op": "ERROR", "code": "graphics_begin_failed", "detail": str(e)})
        log(f"graphics_begin_failed wid={req.get('winid')} err={e}")


def graphicsnodemetadata(req, value):

    output = dict(value)
    nodeid = str(req.get("id", ""))[:128]
    parent = str(req.get("parent", ""))[:128]

    if nodeid:

        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", nodeid):
            raise ValueError("graphics node id contains unsupported characters")

        output["id"] = nodeid

    if parent:

        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", parent):
            raise ValueError("graphics parent id contains unsupported characters")

        output["parent"] = parent

    translate = req.get("translate", [0.0, 0.0])
    scale = req.get("scale", [1.0, 1.0])
    scroll = req.get("scroll", [0.0, 0.0])

    if isinstance(scale, (int, float)):
        scale = [scale, scale]

    if not isinstance(translate, (list, tuple)) or len(translate) != 2:
        raise ValueError("graphics translate must contain x and y")

    if not isinstance(scale, (list, tuple)) or len(scale) != 2:
        raise ValueError("graphics scale must contain x and y")

    if not isinstance(scroll, (list, tuple)) or len(scroll) != 2:
        raise ValueError("graphics scroll must contain x and y")

    tx, ty = [max(-1000000.0, min(1000000.0, float(item))) for item in translate]
    sx, sy = [max(0.01, min(16.0, float(item))) for item in scale]
    scrollx, scrolly = [max(-1000000.0, min(1000000.0, float(item))) for item in scroll]
    rotation = max(-3600.0, min(3600.0, float(req.get("rotation", 0.0))))
    effect = str(req.get("effect", "none")).lower()

    if effect not in ("none", "grayscale", "invert", "sepia"):
        raise ValueError("unsupported controlled graphics effect")

    if tx or ty:
        output["translate"] = [tx, ty]

    if sx != 1.0 or sy != 1.0:
        output["scale"] = [sx, sy]

    if scrollx or scrolly:
        output["scroll"] = [scrollx, scrolly]

    if rotation:
        output["rotation"] = rotation

    if effect != "none":
        output["effect"] = effect

    return output


def graphicsvector3(value, name, default=(0.0, 0.0, 0.0), minimum=-10000.0, maximum=10000.0):

    if value is None:
        value = default

    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(f"controlled 3D {name} must contain x, y, and z")

    return [max(float(minimum), min(float(maximum), float(item))) for item in value]


def graphicscamera3d(value):

    value = value if isinstance(value, dict) else {}
    projection = str(value.get("projection", "perspective")).lower()

    if projection not in ("perspective", "orthographic"):
        raise ValueError("controlled 3D camera projection must be perspective or orthographic")

    near = max(0.001, min(1000.0, float(value.get("near", 0.1))))
    far = max(near + 0.01, min(100000.0, float(value.get("far", 100.0))))
    return {
        "position": graphicsvector3(value.get("position"), "camera position", default=(0, 0, 6)),
        "target": graphicsvector3(value.get("target"), "camera target"),
        "up": graphicsvector3(value.get("up"), "camera up", default=(0, 1, 0), minimum=-1.0, maximum=1.0),
        "projection": projection,
        "fov": max(10.0, min(150.0, float(value.get("fov", 50.0)))),
        "near": near,
        "far": far,
        "orthographic_size": max(0.01, min(10000.0, float(value.get("orthographic_size", 5.0)))),
    }


def graphicsmaterial3d(value):

    value = value if isinstance(value, dict) else {}
    output = {
        "color": graphicscolor(value.get("color"), default=[255, 255, 255, 255]),
        "opacity": max(0.0, min(1.0, float(value.get("opacity", 1.0)))),
        "shininess": max(1.0, min(256.0, float(value.get("shininess", 24.0)))),
        "unlit": bool(value.get("unlit", False)),
    }
    texture = value.get("texture")

    if texture:

        path = os.path.realpath(str(texture))
        roots = (os.path.realpath("/the one/resources"), os.path.realpath("/.ephemeral"))
        width = int(value.get("texture_width", 0))
        height = int(value.get("texture_height", 0))
        fmt = str(value.get("texture_format", "BGRA32")).upper()

        if not os.path.isabs(path) or not os.path.isfile(path):
            raise ValueError("controlled 3D texture path must name an existing absolute file")

        if not any(os.path.commonpath((root, path)) == root for root in roots):
            raise ValueError("controlled 3D texture must be a T1OS resource or an ephemeral application surface")

        info = os.stat(path, follow_symlinks=False)
        if (
            stat.S_ISLNK(info.st_mode)
            or not stat.S_ISREG(info.st_mode)
            or info.st_uid not in (os.geteuid(), SESSIONUID)
        ):
            raise ValueError("controlled 3D texture source is not a trusted regular file")

        if width < 1 or height < 1 or width * height > GPUCOMMANDIMAGEPIXELS:
            raise ValueError("controlled 3D texture dimensions exceed the managed graphics limit")

        if fmt not in ("BGRA32", "RGBA32") or os.path.getsize(path) < width * height * 4:
            raise ValueError("controlled 3D texture format or file size is invalid")

        output.update({
            "texture": path,
            "texture_width": width,
            "texture_height": height,
            "texture_format": fmt,
        })

    return output


def graphicsmesh3d(value):

    if not isinstance(value, dict):
        raise ValueError("controlled 3D mesh must be an object")

    primitive = str(value.get("primitive", "cube")).lower()

    if primitive not in ("cube", "plane", "sphere", "custom"):
        raise ValueError(f"unsupported controlled 3D primitive {primitive}")

    output = {
        "primitive": primitive,
        "position": graphicsvector3(value.get("position"), "mesh position"),
        "rotation": graphicsvector3(value.get("rotation"), "mesh rotation", minimum=-3600.0, maximum=3600.0),
        "scale": graphicsvector3(value.get("scale"), "mesh scale", default=(1, 1, 1), minimum=0.001, maximum=1000.0),
        "rotation_speed": graphicsvector3(value.get("rotation_speed"), "mesh rotation speed", minimum=-720.0, maximum=720.0),
        "wireframe": bool(value.get("wireframe", False)),
        "line_width": max(1.0, min(8.0, float(value.get("line_width", 1.0)))),
        "subdivisions": max(6, min(32, int(value.get("subdivisions", 16)))),
        "material": graphicsmaterial3d(value.get("material")),
    }

    if primitive == "custom":

        sourcevertices = value.get("vertices")
        sourceindices = value.get("indices", [])

        if not isinstance(sourcevertices, list) or len(sourcevertices) < 3 or len(sourcevertices) > GPUCOMMAND3DVERTEXLIMIT:
            raise ValueError("controlled custom 3D mesh vertex count is outside the managed limit")

        vertices = []

        for vertex in sourcevertices:

            if not isinstance(vertex, (list, tuple)) or len(vertex) != 8:
                raise ValueError("controlled custom 3D vertices require position, normal, and texture coordinates")

            vertices.append([
                *[max(-10000.0, min(10000.0, float(item))) for item in vertex[:3]],
                *[max(-1.0, min(1.0, float(item))) for item in vertex[3:6]],
                *[max(-1000.0, min(1000.0, float(item))) for item in vertex[6:8]],
            ])

        if not isinstance(sourceindices, list) or len(sourceindices) > GPUCOMMAND3DINDEXLIMIT:
            raise ValueError("controlled custom 3D mesh index count exceeds the managed limit")

        indices = [int(item) for item in sourceindices]

        if not indices:
            indices = list(range(len(vertices)))

        if len(indices) % 3 or any(index < 0 or index >= len(vertices) for index in indices):
            raise ValueError("controlled custom 3D mesh indices do not form bounded triangles")

        output["vertices"] = vertices
        output["indices"] = indices

    return output


def graphicsscene3d(win, req, clip, opacity):

    meshes = req.get("meshes")

    if not isinstance(meshes, list) or not meshes or len(meshes) > GPUCOMMAND3DMESHLIMIT:
        raise ValueError("controlled 3D scene mesh count is outside the managed limit")

    rect = graphicsdestinationrect(win, req.get("rect", [0, 0, int(win["w"]), int(win["h"])]))
    ambient = req.get("ambient") if isinstance(req.get("ambient"), dict) else {}
    light = req.get("light") if isinstance(req.get("light"), dict) else {}
    fog = req.get("fog") if isinstance(req.get("fog"), dict) else {}
    fognear = max(0.0, min(100000.0, float(fog.get("near", 5.0))))
    postprocess = str(req.get("postprocess", "none")).lower()
    antialias = str(req.get("antialias", "auto")).lower()

    if postprocess not in ("none", "grayscale", "invert", "sepia"):
        raise ValueError("unsupported controlled 3D post-processing effect")

    if antialias not in ("auto", "analytic", "quality"):
        raise ValueError("unsupported controlled 3D antialiasing mode")

    return graphicsnodemetadata(req, {
        "kind": "scene3d",
        "rect": rect,
        "clip": list(rectintersect(*clip, *rect)),
        "opacity": opacity,
        "camera": graphicscamera3d(req.get("camera")),
        "meshes": [graphicsmesh3d(value) for value in meshes],
        "ambient": {
            "color": graphicscolor(ambient.get("color"), default=[255, 255, 255, 255]),
            "intensity": max(0.0, min(4.0, float(ambient.get("intensity", 0.25)))),
        },
        "light": {
            "direction": graphicsvector3(light.get("direction"), "light direction", default=(-0.4, -0.8, -0.6), minimum=-1.0, maximum=1.0),
            "color": graphicscolor(light.get("color"), default=[255, 255, 255, 255]),
            "intensity": max(0.0, min(8.0, float(light.get("intensity", 0.9)))),
        },
        "fog": {
            "enabled": bool(fog.get("enabled", False)),
            "color": graphicscolor(fog.get("color"), default=[17, 19, 24, 255]),
            "near": fognear,
            "far": max(fognear + 0.01, min(100000.0, float(fog.get("far", 14.0)))),
        },
        "postprocess": postprocess,
        "antialias": antialias,
        "animation_started": time.monotonic(),
    })


def graphicscommand(win, req, kind):

    kind = str(kind).lower()
    clip = graphicslocalrect(win, req.get("clip"), default=[0, 0, int(win["w"]), int(win["h"])])
    opacity = max(0.0, min(1.0, float(req.get("opacity", 1.0))))

    if kind == "rectangle":

        rect = graphicslocalrect(
            win,
            req.get("rect", [req.get("x", 0), req.get("y", 0), req.get("w", 0), req.get("h", 0)]),
        )
        return graphicsnodemetadata(req, {
            "kind": kind,
            "rect": rect,
            "clip": clip,
            "color": graphicscolor(req.get("color")),
            "opacity": opacity,
        })

    if kind in ("rounded_rectangle", "border", "gradient"):

        rect = graphicslocalrect(
            win,
            req.get("rect", [req.get("x", 0), req.get("y", 0), req.get("w", 0), req.get("h", 0)]),
        )
        value = {
            "kind": kind,
            "rect": rect,
            "clip": clip,
            "color": graphicscolor(req.get("color")),
            "opacity": opacity,
        }

        if kind == "rounded_rectangle":
            value["radius"] = max(0.0, min(float(req.get("radius", 8.0)), min(rect[2], rect[3]) * 0.5))

        elif kind == "border":
            value["width"] = max(1.0, min(float(req.get("width", 1.0)), min(rect[2], rect[3]) * 0.5))

        else:
            value["color2"] = graphicscolor(req.get("color2"), default=value["color"])
            value["direction"] = "horizontal" if str(req.get("direction", "vertical")).lower() == "horizontal" else "vertical"

        return graphicsnodemetadata(req, value)

    if kind == "line":

        points = req.get("points", [req.get("x0", 0), req.get("y0", 0), req.get("x1", 0), req.get("y1", 0)])

        if not isinstance(points, (list, tuple)) or len(points) != 4:
            raise ValueError("line points must contain x0, y0, x1, and y1")

        return graphicsnodemetadata(req, {
            "kind": kind,
            "points": [max(-1000000.0, min(1000000.0, float(item))) for item in points],
            "width": max(0.5, min(256.0, float(req.get("width", 1.0)))),
            "clip": clip,
            "color": graphicscolor(req.get("color")),
            "opacity": opacity,
        })

    if kind == "circle":

        radius = max(0.5, min(100000.0, float(req.get("radius", 1.0))))
        cx = float(req.get("cx", req.get("x", 0)))
        cy = float(req.get("cy", req.get("y", 0)))

        if rectintersect(int(cx - radius), int(cy - radius), int(radius * 2), int(radius * 2), 0, 0, int(win["w"]), int(win["h"]))[2] < 1:
            raise ValueError("circle is outside the window")

        return graphicsnodemetadata(req, {
            "kind": kind,
            "center": [cx, cy],
            "radius": radius,
            "clip": clip,
            "color": graphicscolor(req.get("color")),
            "opacity": opacity,
        })

    if kind in ("group", "layer"):

        value = {
            "kind": kind,
            "clip": clip,
            "opacity": opacity,
        }

        if kind == "layer":
            value["rect"] = graphicslocalrect(win, req.get("rect"), default=clip)
            value["clip"] = list(rectintersect(*value["clip"], *value["rect"]))

        return graphicsnodemetadata(req, value)

    if kind == "video":

        stream = str(req.get("stream", ""))[:128]

        if not stream or stream not in win.get("_video_streams", {}):
            raise ValueError("video command names no authorised video stream")

        rect = graphicsdestinationrect(
            win,
            req.get("rect", [req.get("x", 0), req.get("y", 0), req.get("w", win["w"]), req.get("h", win["h"])]),
        )
        return graphicsnodemetadata(req, {
            "kind": kind,
            "stream": stream,
            "rect": rect,
            "clip": clip,
            "opacity": opacity,
        })

    if kind == "image":

        path = os.path.realpath(str(req.get("path", "")))
        imageroots = (os.path.realpath("/the one/resources"), os.path.realpath("/.ephemeral"))
        sourcewidth = int(req.get("source_width", req.get("sw", 0)))
        sourceheight = int(req.get("source_height", req.get("sh", 0)))
        fmt = str(req.get("format", "BGRA32")).upper()
        revision = max(0, int(req.get("revision", 0))) if "revision" in req else None

        if not os.path.isabs(path) or not os.path.isfile(path):
            raise ValueError("image path must name an existing absolute file")

        if not any(os.path.commonpath((root, path)) == root for root in imageroots):
            raise ValueError("image must be a T1OS resource or an ephemeral application surface")

        info = os.stat(path, follow_symlinks=False)
        if (
            stat.S_ISLNK(info.st_mode)
            or not stat.S_ISREG(info.st_mode)
            or info.st_uid not in (os.geteuid(), SESSIONUID)
        ):
            raise ValueError("image source is not a trusted regular file")

        if sourcewidth < 1 or sourceheight < 1 or sourcewidth * sourceheight > GPUCOMMANDIMAGEPIXELS:
            raise ValueError("image dimensions exceed the managed graphics limit")

        if fmt not in ("BGRA32", "RGBA32"):
            raise ValueError("unsupported image format")

        if os.path.getsize(path) < sourcewidth * sourceheight * 4:
            raise ValueError("image file is smaller than its declared dimensions")

        rect = graphicsdestinationrect(
            win,
            req.get("rect", [req.get("x", 0), req.get("y", 0), req.get("w", sourcewidth), req.get("h", sourceheight)]),
        )
        value = {
            "kind": kind,
            "path": path,
            "source_width": sourcewidth,
            "source_height": sourceheight,
            "format": fmt,
            "rect": rect,
            "clip": clip,
            "opacity": opacity,
        }

        if revision is not None:
            value["revision"] = revision

        return graphicsnodemetadata(req, value)

    if kind == "text":

        text = str(req.get("text", ""))[:GPUCOMMANDTEXTLIMIT]
        size = max(1, min(256, int(req.get("size", 16))))
        font = os.path.realpath(str(req.get("font", WINDOWFONT) or WINDOWFONT))
        fontroot = os.path.realpath("/the one/resources/fonts")

        if not text:
            raise ValueError("text command is empty")

        if not os.path.isfile(font) or os.path.commonpath((fontroot, font)) != fontroot:
            raise ValueError("font must be an installed T1OS resource")

        x = max(0, min(int(win["w"]) - 1, int(req.get("x", 0))))
        y = max(0, min(int(win["h"]) - 1, int(req.get("y", 0))))
        return graphicsnodemetadata(req, {
            "kind": kind,
            "x": x,
            "y": y,
            "text": text,
            "size": size,
            "font": font,
            "clip": clip,
            "color": graphicscolor(req.get("color")),
            "opacity": opacity,
        })

    if kind == "console_grid":

        groups = {}
        total = 0

        for group, allowed in (
            ('backgrounds', {'rectangle'}),
            ('texts', {'text'}),
            ('overlays', {'rectangle', 'text'}),
        ):
            source = req.get(group, [])

            if not isinstance(source, list):
                raise ValueError("console grid groups must be lists")

            total += len(source)

            if total > GPUCOMMANDGRIDITEMLIMIT:
                raise ValueError("console grid exceeds its item limit")

            values = []

            for item in source:
                if not isinstance(item, dict):
                    raise ValueError("console grid item must be an object")
                itemkind = str(item.get('kind', '')).lower()
                if itemkind not in allowed:
                    raise ValueError("unsupported console grid item")
                values.append(graphicscommand(win, item, itemkind))

            groups[group] = values

        return graphicsnodemetadata(req, {
            'kind': kind,
            'rect': graphicslocalrect(win, req.get('rect'), default=clip),
            'clip': clip,
            'opacity': opacity,
            **groups,
        })

    if kind == "scene3d":
        return graphicsscene3d(win, req, clip, opacity)

    raise ValueError("unsupported managed graphics command")


def graphicscommandbudget(win, count):

    count = int(count)

    if count < 0 or count > GPUCOMMANDLIMIT:
        raise RuntimeError("managed graphics command limit reached")

    totalcommands = count

    for other in windows.values():

        if other is not win:
            totalcommands += len(other.get("gpu_commands", []))

    if totalcommands > GPUCOMMANDTOTALLIMIT:
        raise RuntimeError("managed graphics total command limit reached")


def graphicsvalidatescene(commands):

    nodes = {}
    layers = 0

    for command in commands:

        nodeid = str(command.get("id", ""))

        if nodeid:

            if nodeid in nodes:
                raise ValueError(f"duplicate graphics node id {nodeid}")

            nodes[nodeid] = command

        if str(command.get("kind", "")) == "layer":

            if not nodeid:
                raise ValueError("offscreen graphics layer requires a stable id")

            layers += 1

    if layers > GPUCOMMANDLAYERLIMIT:
        raise ValueError(f"managed graphics layer limit reached {layers}/{GPUCOMMANDLAYERLIMIT}")

    for command in commands:

        parentid = str(command.get("parent", ""))

        if not parentid:
            continue

        parent = nodes.get(parentid)

        if parent is None or str(parent.get("kind", "")) not in ("group", "layer"):
            raise ValueError(f"graphics parent does not name a group or layer {parentid}")

        seen = set()
        current = command
        layerancestors = 0

        while current.get("parent"):

            currentid = str(current.get("parent"))

            if currentid in seen:
                raise ValueError("graphics scene contains a parent cycle")

            seen.add(currentid)
            current = nodes.get(currentid)

            if current is None:
                break

            if str(current.get("kind", "")) == "layer":
                layerancestors += 1

        if (str(command.get("kind", "")) == "layer" and layerancestors > 0) or layerancestors > 1:
            raise ValueError("nested graphics layers are not supported")

    return True


def graphicsmanageddamage(win, values=None):

    if values is None:

        width = max(0, int(win.get("w", 0)))
        height = max(0, int(win.get("h", 0)))
        win["_gpu_scene_damage"] = [[0, 0, width, height]]
        win["_telemetry_damage_pixels"] = int(win.get("_telemetry_damage_pixels", 0)) + width * height
        fulldamage(win)
        return 1

    if not isinstance(values, (list, tuple)):
        raise ValueError("managed scene damage must be a list")

    if len(values) > GPUCOMMANDDAMAGELIMIT:
        raise ValueError("managed scene damage limit reached")

    output = []

    for value in values:

        try:
            rect = graphicslocalrect(win, value)
        except ValueError:
            continue

        output.append(rect)

    if not output:
        return graphicsmanageddamage(win, None)

    gx = int(win.get("x", 0))
    gy = int(win.get("y", 0))
    pixels = 0

    for x, y, width, height in output:
        DAMAGERECTS.append([gx + x, gy + y, width, height])
        pixels += int(width) * int(height)

    existing = [list(value) for value in win.get("_gpu_scene_damage", []) if isinstance(value, (list, tuple)) and len(value) == 4]
    full = [0, 0, max(0, int(win.get("w", 0))), max(0, int(win.get("h", 0)))]

    if full not in existing:
        existing.extend([list(value) for value in output])

    win["_gpu_scene_damage"] = [full] if len(existing) > GPUCOMMANDDAMAGELIMIT else existing
    win["_telemetry_damage_pixels"] = int(win.get("_telemetry_damage_pixels", 0)) + pixels
    return len(output)


def graphicsappend(cid, req, kind):

    try:

        wid, win = graphicswindow(cid, req)
        pending = win.get("_gpu_commands_pending")

        if not isinstance(pending, list):
            raise RuntimeError("GRAPHICS_BEGIN is required before drawing commands")

        graphicscommandbudget(win, len(pending) + 1)
        pending.append(graphicscommand(win, req, kind))
        sendjson(cid, {"op": "GRAPHICS_COMMAND_ADDED", "winid": wid, "kind": kind, "count": len(pending)})

    except KeyError:
        sendjson(cid, {"op": "ERROR", "code": "unknown_window"})
    except Exception as e:
        sendjson(cid, {"op": "ERROR", "code": "graphics_command_failed", "detail": str(e)})
        log(f"graphics_command_failed wid={req.get('winid')} err={e}")


def graphicspresentationresponse(cid, win, response):

    # Managed clients use GRAPHICS_COMMITTED as their release signal.  Sending
    # it while merely accepting a scene lets the client replace that scene
    # during the compositor's pre-paint I/O drains, so transient text can be
    # cleared without ever reaching scan-out. Once the real DRM presentation
    # fd is active, a mapped window's response is held until the exact managed
    # generation drawn into a submitted frame has completed its page flip.
    if GPUCOMPOSITOR and GRAPHICSPRESENTFD is not None:

        receipt = {
            "cid": int(cid),
            "winid": int(win.get("id", response.get("winid", 0))),
            "generation": int(
                response.get(
                    "generation",
                    win.get("_gpu_command_generation", 0),
                )
            ),
            "response": dict(response),
        }

        if not bool(win.get("mapped")):
            graphicsdefercommitreceipt(
                receipt,
                "window is not mapped",
                superseded=False,
            )
            return True

        receipts = win.setdefault("_gpu_commit_receipts", [])

        if len(receipts) >= GPUCOMMANDDAMAGELIMIT:
            raise RuntimeError("managed presentation receipt limit reached")

        receipts.append(receipt)
        return True

    sendjson(cid, response)
    return True


def graphicsframecommitreceipts(renderedgenerations):

    global GPUCAPTUREDCOMMITRECEIPTS

    if GPUCAPTUREDCOMMITRECEIPTS:
        raise RuntimeError(
            "managed presentation receipt capture survived its frame submission"
        )

    renderedgenerations = {
        int(wid): int(generation)
        for wid, generation in dict(renderedgenerations or {}).items()
    }
    output = []

    for wid, win in list(windows.items()):

        receipts = win.get("_gpu_commit_receipts")

        if not isinstance(receipts, list) or not receipts:
            continue

        renderedgeneration = renderedgenerations.get(int(wid))
        retained = []

        for receipt in list(receipts):

            generation = int(receipt.get("generation", 0))

            if renderedgeneration is not None and generation <= renderedgeneration:
                presented = generation == renderedgeneration
                output.append({
                    "receipt": receipt,
                    "presented": bool(presented),
                    "superseded": not bool(presented),
                    "presentation_reason": (
                        ""
                        if presented
                        else "newer managed generation was drawn"
                    ),
                })
                continue

            if not bool(win.get("mapped")):
                output.append({
                    "receipt": receipt,
                    "presented": False,
                    "superseded": True,
                    "presentation_reason": "window was unmapped before presentation",
                })
                continue

            if renderedgeneration is None:
                output.append({
                    "receipt": receipt,
                    "presented": False,
                    "superseded": False,
                    "presentation_reason": "window was not visible in the submitted frame",
                })
                continue

            # A generation newer than the one already rendered can only arrive
            # through I/O serviced while scan-out waits for an earlier flip.
            # Keep it queued for the next compositor frame.
            retained.append(receipt)

        win["_gpu_commit_receipts"] = retained

    GPUCAPTUREDCOMMITRECEIPTS = list(output)
    return output


def graphicsrestorecommitreceipts(receipts):

    global GPUCAPTUREDCOMMITRECEIPTS

    restored = {}

    for entry in receipts or []:

        receipt = entry.get("receipt") if isinstance(entry, dict) else None

        if not isinstance(receipt, dict):
            continue

        wid = int(receipt.get("winid", 0))

        if wid in windows:
            restored.setdefault(wid, []).append(receipt)

    for wid, values in restored.items():
        pending = windows[wid].setdefault("_gpu_commit_receipts", [])
        windows[wid]["_gpu_commit_receipts"] = list(values) + list(pending)

    GPUCAPTUREDCOMMITRECEIPTS = []
    return sum(len(values) for values in restored.values())


def graphicscommitreceiptvalue(
    receipt,
    presented,
    frame_sequence=None,
    superseded=False,
    reason="",
):

    value = dict(receipt)
    response = dict(value.get("response") or {})
    response["presented"] = bool(presented)

    if frame_sequence is None:
        response.pop("frame_sequence", None)
        value.pop("frame_sequence", None)
    else:
        response["frame_sequence"] = int(frame_sequence)
        value["frame_sequence"] = int(frame_sequence)

    if presented:
        response.pop("superseded", None)
        response.pop("presentation_reason", None)
    else:
        response["superseded"] = bool(superseded)
        response["presentation_reason"] = str(
            reason or "managed state was not presented"
        )

    value["response"] = response
    return value


def graphicscommitreceiptoutstanding(wid):

    wid = int(wid)

    for entry in GPUCAPTUREDCOMMITRECEIPTS:
        receipt = entry.get("receipt") if isinstance(entry, dict) else None

        if isinstance(receipt, dict) and int(receipt.get("winid", 0)) == wid:
            return True

    return any(
        int(receipt.get("winid", 0)) == wid
        for receipt in GPUPENDINGCOMMITRECEIPTS
        if isinstance(receipt, dict)
    )


def graphicsdelivercommitreceipt(receipt):

    cid = int(receipt.get("cid", 0))
    wid = int(receipt.get("winid", 0))
    generation = int(receipt.get("generation", 0))
    response = dict(receipt.get("response") or {})

    if wid in windows and bool(response.get("presented", False)):
        windows[wid]["_gpu_presented_generation"] = max(
            int(windows[wid].get("_gpu_presented_generation", 0)),
            generation,
        )

    if cid not in clients:
        return 0

    sendjson(cid, response)
    return 1


def graphicsfinishdeferredcommitreceipts():

    global GPUDEFERREDCOMMITRECEIPTS

    retained = []
    delivered = 0

    for receipt in GPUDEFERREDCOMMITRECEIPTS:

        if graphicscommitreceiptoutstanding(receipt.get("winid", 0)):
            retained.append(receipt)
            continue

        delivered += graphicsdelivercommitreceipt(receipt)

    GPUDEFERREDCOMMITRECEIPTS = retained
    return delivered


def graphicsdefercommitreceipt(receipt, reason, superseded=True):

    global GPUDEFERREDCOMMITRECEIPTS

    value = graphicscommitreceiptvalue(
        receipt,
        False,
        superseded=bool(superseded),
        reason=str(reason),
    )

    if graphicscommitreceiptoutstanding(value.get("winid", 0)):
        GPUDEFERREDCOMMITRECEIPTS.append(value)
        return 0

    return graphicsdelivercommitreceipt(value)


def graphicsstagecommitreceipts(receipts):

    global GPUPENDINGCOMMITRECEIPTS, GPUCAPTUREDCOMMITRECEIPTS

    if not receipts:
        GPUCAPTUREDCOMMITRECEIPTS = []
        graphicsfinishdeferredcommitreceipts()
        return 0

    if GPUPENDINGCOMMITRECEIPTS:
        raise RuntimeError(
            "managed presentation receipts survived the preceding page flip"
        )

    staged = []

    for entry in receipts:

        receipt = entry.get("receipt") if isinstance(entry, dict) else None

        if not isinstance(receipt, dict):
            continue

        staged.append(
            graphicscommitreceiptvalue(
                receipt,
                bool(entry.get("presented", False)),
                frame_sequence=int(GPUFRAMESEQUENCE),
                superseded=bool(entry.get("superseded", False)),
                reason=str(entry.get("presentation_reason", "")),
            )
        )

    GPUPENDINGCOMMITRECEIPTS = staged
    GPUCAPTUREDCOMMITRECEIPTS = []
    return len(staged)


def graphicsfinishcommitreceipts():

    global GPUPENDINGCOMMITRECEIPTS

    receipts = list(GPUPENDINGCOMMITRECEIPTS)
    GPUPENDINGCOMMITRECEIPTS = []
    delivered = sum(
        graphicsdelivercommitreceipt(receipt)
        for receipt in receipts
    )
    return delivered + graphicsfinishdeferredcommitreceipts()


def graphicscancelcommitreceipts(win, reason, superseded=True):

    receipts = list(win.get("_gpu_commit_receipts", []))
    win["_gpu_commit_receipts"] = []
    delivered = 0

    for receipt in receipts:
        delivered += graphicsdefercommitreceipt(
            receipt,
            reason,
            superseded=bool(superseded),
        )

    return delivered


def graphicsdrmpresentationevent():

    completed = bool(kmshandlepresentationevent())

    if completed:
        graphicsfinishcommitreceipts()
        finishchromiumpresentations()

    return completed


def graphicspresentationpulse():

    # graphics.kmswaitflip() owns and consumes a readable DRM event itself.
    # Its wait callback therefore cannot rely on the selector seeing that same
    # fd. Reconcile the receipt after every raw wait pulse as well as after the
    # ordinary selector wrapper so synchronous resize/readiness waits cannot
    # strand a completed frame's acknowledgements.
    iopulse()

    if not kmspresentationpending():
        if GPUPENDINGCOMMITRECEIPTS:
            graphicsfinishcommitreceipts()
        finishchromiumpresentations()


def graphicsscene(cid, req):

    try:

        wid, win = graphicswindow(cid, req)
        source = req.get("commands")
        initialscene = not bool(win.get("gpu_commands"))

        if not isinstance(source, list):
            raise ValueError("managed scene commands must be a list")

        graphicscommandbudget(win, len(source))
        commands = []

        for value in source:

            if not isinstance(value, dict):
                raise ValueError("managed scene command must be an object")

            commands.append(graphicscommand(win, value, value.get("kind", "")))

        graphicsvalidatescene(commands)
        # The first managed scene replaces the window's still-blank CPU surface.
        # It therefore needs one complete repaint even when the application has
        # only accumulated a small dirty rectangle (for example a text cursor).
        # Retained scene patches continue to use the supplied partial damage.
        damagecount = graphicsmanageddamage(
            win,
            None if initialscene else (req.get("damage") if "damage" in req else None),
        )
        win["gpu_commands"] = commands
        gpuwindowlayersprune(win)
        win["_gpu_commands_pending"] = None
        win["_gpu_generation"] = int(win.get("_gpu_generation", 0)) + 1
        win["_gpu_command_generation"] = int(win.get("_gpu_command_generation", 0)) + 1
        win["_managed_only"] = bool(gpuwindowmanagedonly(win))

        if (
            str(win.get("role", "")).strip().lower()
            in ("boot animation", "system animation", "lockscreen", "startup")
            and not bool(win.get("_gpu_system_commit_logged", False))
        ):
            graphicslog(
                f"> graphics system scene committed "
                f"role={str(win.get('role', 'unknown'))} "
                f"managed_only={bool(win.get('_managed_only', False))} "
                f"window={int(win.get('w', 0))}x{int(win.get('h', 0))} "
                f"display={int(SCREENW)}x{int(SCREENH)}"
            )
            win["_gpu_system_commit_logged"] = True

        if win["_managed_only"]:
            gpuwindowcpurelease(win)
        else:
            gpuwindowscenerelease(win)

        win["_telemetry_scene_commits"] = int(win.get("_telemetry_scene_commits", 0)) + 1
        win["_telemetry_batch_commits"] = int(win.get("_telemetry_batch_commits", 0)) + 1
        graphicspresentationresponse(cid, win, {
            "op": "GRAPHICS_COMMITTED",
            "winid": wid,
            "count": len(commands),
            "damage_count": int(damagecount),
            "batch": True,
            "accelerated": bool(GPUCOMPOSITOR and gpuavailable()),
            "managed_only": bool(win.get("_managed_only", False)),
            "generation": int(win.get("_gpu_command_generation", 0)),
            "fallback": "shared_buffer",
        })

    except KeyError:
        sendjson(cid, {"op": "ERROR", "code": "unknown_window"})
    except Exception as e:
        sendjson(cid, {"op": "ERROR", "code": "graphics_scene_failed", "detail": str(e)})
        log(f"graphics_scene_failed wid={req.get('winid')} err={e}")


def graphicscommit(cid, req):

    try:

        wid, win = graphicswindow(cid, req)
        pending = win.get("_gpu_commands_pending")

        if not isinstance(pending, list):
            raise RuntimeError("GRAPHICS_BEGIN is required before GRAPHICS_COMMIT")

        graphicsvalidatescene(pending)
        win["gpu_commands"] = list(pending)
        gpuwindowlayersprune(win)
        win["_gpu_commands_pending"] = None
        win["_gpu_generation"] = int(win.get("_gpu_generation", 0)) + 1
        win["_gpu_command_generation"] = int(win.get("_gpu_command_generation", 0)) + 1
        win["_managed_only"] = bool(gpuwindowmanagedonly(win))
        win["_gpu_scene_damage"] = [[0, 0, int(win.get("w", 0)), int(win.get("h", 0))]]

        if win["_managed_only"]:
            gpuwindowcpurelease(win)
        else:
            gpuwindowscenerelease(win)

        win["_telemetry_scene_commits"] = int(win.get("_telemetry_scene_commits", 0)) + 1
        win["_telemetry_damage_pixels"] = int(win.get("_telemetry_damage_pixels", 0)) + int(win.get("w", 0)) * int(win.get("h", 0))
        fulldamage(win)
        graphicspresentationresponse(cid, win, {
            "op": "GRAPHICS_COMMITTED",
            "winid": wid,
            "count": len(win["gpu_commands"]),
            "batch": False,
            "accelerated": bool(GPUCOMPOSITOR and gpuavailable()),
            "managed_only": bool(win.get("_managed_only", False)),
            "generation": int(win.get("_gpu_command_generation", 0)),
            "fallback": "shared_buffer",
        })

    except KeyError:
        sendjson(cid, {"op": "ERROR", "code": "unknown_window"})
    except Exception as e:
        sendjson(cid, {"op": "ERROR", "code": "graphics_commit_failed", "detail": str(e)})
        log(f"graphics_commit_failed wid={req.get('winid')} err={e}")


def graphicsclear(cid, req):

    try:

        wid, win = graphicswindow(cid, req)
        gpuwindowlayersrelease(win)
        gpuwindowscenerelease(win)
        win["gpu_commands"] = []
        win["_gpu_scene_damage"] = []
        win["_gpu_commands_pending"] = None
        win["_managed_only"] = False
        win["_gpu_generation"] = int(win.get("_gpu_generation", 0)) + 1
        win["_gpu_command_generation"] = int(win.get("_gpu_command_generation", 0)) + 1
        win["_telemetry_scene_clears"] = int(win.get("_telemetry_scene_clears", 0)) + 1
        reason = str(req.get("reason", ""))[:256]

        if reason:
            win["_telemetry_fallbacks"] = int(win.get("_telemetry_fallbacks", 0)) + 1
            win["_telemetry_last_fallback"] = reason

        fulldamage(win)
        graphicspresentationresponse(
            cid,
            win,
            {
                "op": "GRAPHICS_CLEARED",
                "winid": wid,
                "generation": int(win.get("_gpu_command_generation", 0)),
            },
        )

    except KeyError:
        sendjson(cid, {"op": "ERROR", "code": "unknown_window"})
    except Exception as e:
        sendjson(cid, {"op": "ERROR", "code": "graphics_clear_failed", "detail": str(e)})


def graphicspatch(cid, req):

    try:

        wid, win = graphicswindow(cid, req)
        generation = int(req.get("generation", -1))
        currentgeneration = int(win.get("_gpu_command_generation", 0))

        if generation != currentgeneration:
            raise RuntimeError(f"stale scene generation {generation}/{currentgeneration}")

        sourceupsert = req.get("upsert", [])
        sourceremove = req.get("remove", [])
        sourceorder = req.get("order", [])

        if not isinstance(sourceupsert, list) or not isinstance(sourceremove, list) or not isinstance(sourceorder, list):
            raise ValueError("scene patch fields must be lists")

        if len(sourceupsert) > GPUCOMMANDLIMIT or len(sourceremove) > GPUCOMMANDLIMIT or len(sourceorder) > GPUCOMMANDLIMIT:
            raise RuntimeError("managed scene patch limit reached")

        nodes = {}

        for index, command in enumerate(win.get("gpu_commands", [])):

            nodeid = str(command.get("id", f"legacy:{index}"))[:128]
            value = dict(command)
            value["id"] = nodeid
            nodes[nodeid] = value

        for rawid in sourceremove:
            nodes.pop(str(rawid)[:128], None)

        for raw in sourceupsert:

            if not isinstance(raw, dict):
                raise ValueError("scene patch node must be an object")

            nodeid = str(raw.get("id", ""))[:128]

            if not nodeid:
                raise ValueError("scene patch node requires an id")

            value = graphicscommand(win, raw, raw.get("kind", ""))
            value["id"] = nodeid
            nodes[nodeid] = value

        order = [str(value)[:128] for value in sourceorder]

        if len(order) != len(set(order)) or set(order) != set(nodes):
            raise ValueError("scene patch order must contain every node exactly once")

        graphicscommandbudget(win, len(order))
        commands = [nodes[nodeid] for nodeid in order]
        graphicsvalidatescene(commands)
        damagecount = graphicsmanageddamage(win, req.get("damage") if "damage" in req else None)
        win["gpu_commands"] = commands
        gpuwindowlayersprune(win)
        win["_gpu_commands_pending"] = None
        win["_gpu_generation"] = int(win.get("_gpu_generation", 0)) + 1
        win["_gpu_command_generation"] = currentgeneration + 1
        win["_managed_only"] = bool(gpuwindowmanagedonly(win))

        if win["_managed_only"]:
            gpuwindowcpurelease(win)
        else:
            gpuwindowscenerelease(win)

        win["_telemetry_scene_commits"] = int(win.get("_telemetry_scene_commits", 0)) + 1
        win["_telemetry_patch_commits"] = int(win.get("_telemetry_patch_commits", 0)) + 1
        graphicspresentationresponse(cid, win, {
            "op": "GRAPHICS_COMMITTED",
            "winid": wid,
            "count": len(commands),
            "damage_count": int(damagecount),
            "batch": True,
            "patch": True,
            "upserted": len(sourceupsert),
            "removed": len(sourceremove),
            "generation": int(win["_gpu_command_generation"]),
            "accelerated": bool(GPUCOMPOSITOR and gpuavailable()),
            "managed_only": bool(win.get("_managed_only", False)),
            "fallback": "shared_buffer",
        })

    except KeyError:
        sendjson(cid, {"op": "ERROR", "code": "unknown_window"})
    except Exception as e:
        sendjson(cid, {"op": "ERROR", "code": "graphics_patch_failed", "detail": str(e)})
        log(f"graphics_patch_failed wid={req.get('winid')} err={e}")


def setwindowexternalbuffer(cid, req, attached=True):

    try:

        wid = int(req.get("winid", 0))

        if wid not in windows or windows[wid]["cid"] != cid:
            sendjson(cid, {"op": "ERROR", "code": "unknown_window"})
            return

        win = windows[wid]

        if (
            str(clients.get(cid, {}).get("identity", {}).get("domain", ""))
            != "chromium"
            or str(win.get("role", "")) != "window"
        ):
            sendjson(cid, {
                "op": "ERROR",
                "code": "external_buffer_denied",
                "detail": "external browser buffers are restricted to Chromium",
            })
            return

        if not attached:
            win["buffer"] = win["_owned_buffer"]
            win["_external_buffer"] = False
            win["buffer_offset"] = 0
            win["buffer_stride"] = int(win["w"]) * 4
            win["buffer_source_width"] = int(win["w"])
            win["buffer_source_height"] = int(win["h"])
            win["format"] = "BGRA32"
            gpuwindowrelease(win)
            win["damage"] = [[0, 0, int(win["w"]), int(win["h"])]]
            fulldamage(win)
            sendjson(cid, {
                "op": "WINDOW_BUFFER_DETACHED",
                "winid": wid,
            })
            return

        path = os.path.abspath(str(req.get("path", "")))

        if path != CHROMIUMXWDBUFFER or os.path.islink(path):
            raise PermissionError("Chromium supplied an untrusted external buffer path")

        status = os.lstat(path)

        if not stat.S_ISREG(status.st_mode):
            raise ValueError("Chromium external buffer is not a regular file")

        offset = int(req.get("offset", 0))
        stride = int(req.get("stride", 0))
        sourcewidth = int(req.get("source_width", 0))
        sourceheight = int(req.get("source_height", 0))
        formatname = str(req.get("format", "BGRA32")).upper()

        if (
            formatname != "BGRA32"
            or offset < 100
            or offset > 16 * 1024 * 1024
            or sourcewidth < 1
            or sourceheight < 1
            or sourcewidth > 16384
            or sourceheight > 16384
            or stride < sourcewidth * 4
            or stride > 16384 * 4
        ):
            raise ValueError("Chromium supplied invalid external buffer geometry")

        required = offset + max(0, sourceheight - 1) * stride + sourcewidth * 4

        if int(status.st_size) < required:
            raise ValueError("Chromium external buffer file is incomplete")

        win["buffer"] = path
        win["_external_buffer"] = True
        win["buffer_offset"] = offset
        win["buffer_stride"] = stride
        win["buffer_source_width"] = sourcewidth
        win["buffer_source_height"] = sourceheight
        win["format"] = formatname
        gpuwindowrelease(win)
        win["damage"] = [[0, 0, sourcewidth, sourceheight]]
        fulldamage(win)
        sendjson(cid, {
            "op": "WINDOW_BUFFER_ATTACHED",
            "winid": wid,
            "direct": True,
            "source_width": sourcewidth,
            "source_height": sourceheight,
            "output_width": int(win["w"]),
            "output_height": int(win["h"]),
        })

    except PermissionError as error:
        sendjson(cid, {
            "op": "ERROR",
            "code": "external_buffer_denied",
            "detail": str(error),
        })
    except Exception as error:
        sendjson(cid, {
            "op": "ERROR",
            "code": "external_buffer_invalid",
            "detail": str(error),
        })


def markdamage(cid, req):

    try:

        wid = int(req.get("winid", 0))

        if wid not in windows or windows[wid]["cid"] != cid:
            sendjson(cid, {"op": "ERROR", "code": "unknown_window"})
            return

        win = windows[wid]
        gx = int(win["x"])
        gy = int(win["y"])
        gw = int(win["w"])
        gh = int(win["h"])
        sourcewidth, sourceheight = windowbufferdimensions(win)
        rect = req.get("rect", [0, 0, sourcewidth, sourceheight])

        try:
            x = int(rect[0])
            y = int(rect[1])
            w = int(rect[2])
            h = int(rect[3])
        except Exception:
            x = 0
            y = 0
            w = sourcewidth
            h = sourceheight

        if x < 0:
            w += x
            x = 0

        if y < 0:
            h += y
            y = 0

        if x + w > sourcewidth:
            w = sourcewidth - x

        if y + h > sourceheight:
            h = sourceheight - y

        if w > 0 and h > 0:
            pending = list(win.get("damage", []))
            incoming = [x, y, w, h]
            combined = coalescerects(pending + [incoming], 16)
            win["damage"] = combined
            win["_telemetry_cpu_damage_events"] = int(win.get("_telemetry_cpu_damage_events", 0)) + 1
            win["_telemetry_cpu_damage_pending_peak"] = max(
                int(win.get("_telemetry_cpu_damage_pending_peak", 0)),
                len(combined),
            )

            if len(combined) < len(pending) + 1:
                win["_telemetry_cpu_damage_coalesces"] = int(win.get("_telemetry_cpu_damage_coalesces", 0)) + 1

            scaledexternal = (
                bool(win.get("_external_buffer"))
                and (sourcewidth != gw or sourceheight != gh)
            )
            # GL_LINEAR samples the neighboring source texel at a scaled
            # damage edge. Expand the compositor clip by one source pixel so a
            # retained output surface cannot preserve a stale interpolation
            # seam beside an otherwise-correct partial texture upload.
            outputrect = windowbufferrecttooutput(
                win,
                incoming,
                filtermargin=1 if scaledexternal else 0,
            )
            screenrect = [
                gx + outputrect[0],
                gy + outputrect[1],
                outputrect[2],
                outputrect[3],
            ]
            screenpending = coalescerects(DAMAGERECTS + [screenrect], MAXRECTS)
            DAMAGERECTS[:] = screenpending
            sourcepixels = int(w) * int(h)
            outputpixels = int(outputrect[2]) * int(outputrect[3])
            win["_telemetry_damage_pixels"] = int(win.get("_telemetry_damage_pixels", 0)) + outputpixels
            win["_telemetry_cpu_damage_bytes"] = int(win.get("_telemetry_cpu_damage_bytes", 0)) + sourcepixels * 4

    except Exception as e:
        sendjson(cid, {"op": "ERROR", "code": "damage_failed", "detail": str(e)})


def markrectdamage(cid, req):

    rect = req.get("rect", [0, 0, 0, 0])

    # only allow desktop owners to submit screen damage
    if cid not in DESKTOPCLIENTS:
        return

    x = int(rect[0]); y = int(rect[1]); w = int(rect[2]); h = int(rect[3])

    if w <= 0 or h <= 0:
        return

    # clip to screen bounds
    if x < 0:
        w += x
        x = 0

    if y < 0:
        h += y
        y = 0

    if x >= SCREENW or y >= SCREENH:
        return

    if x + w > SCREENW:
        w = SCREENW - x

    if y + h > SCREENH:
        h = SCREENH - y

    if w <= 0 or h <= 0:
        return

    # request repaint of this region (no overlay semantics)
    DAMAGERECTS.append([x, y, w, h])


def markoverlay(cid, req):


    rect = req.get("rect", [0, 0, 0, 0])

    # only allow desktop owners to submit overlays
    if cid not in DESKTOPCLIENTS:
        return
    x = int(rect[0]); y = int(rect[1]); w = int(rect[2]); h = int(rect[3])
    if w <= 0 or h <= 0:
        return

    # clip to screen bounds
    if x < 0:
        w += x
        x = 0
    if y < 0:
        h += y
        y = 0
    if x >= SCREENW or y >= SCREENH:
        return
    if x + w > SCREENW:
        w = SCREENW - x
    if y + h > SCREENH:
        h = SCREENH - y
    if w <= 0 or h <= 0:
        return

    # enqueue overlay rect so it is drawn above windows (this-frame)
    OVERLAYRECTS.append([x, y, w, h])

    # also enqueue damage so compositor runs for this region
    DAMAGERECTS.append([x, y, w, h])

    # persist overlay with TTL so it remains steady across frames
    nowm = time.monotonic()
    ttl = max(50, int(OVERLAYTTLMS)) / 1000.0
    exp = nowm + ttl

    # refresh existing overlapping entry, else append
    updated = False
    for i in range(len(OVERLAYACTIVE)):
        try:
            ax, ay, aw, ah, aexp = OVERLAYACTIVE[i]
        except Exception:
            continue

        # overlap or touching adjacency
        if not (x > ax + aw or ax > x + w or y > ay + ah or ay > y + h):
            nx = min(x, ax)
            ny = min(y, ay)
            nx2 = max(x + w, ax + aw)
            ny2 = max(y + h, ay + ah)
            OVERLAYACTIVE[i] = [nx, ny, nx2 - nx, ny2 - ny, exp]
            updated = True
            break

    if not updated:
        OVERLAYACTIVE.append([x, y, w, h, exp])

    # cap overlays; if too many, collapse to one bounding box
    if len(OVERLAYACTIVE) > OVERLAYMAX:
        try:
            xs = [r[0] for r in OVERLAYACTIVE]
            ys = [r[1] for r in OVERLAYACTIVE]
            xe = [r[0] + r[2] for r in OVERLAYACTIVE]
            ye = [r[1] + r[3] for r in OVERLAYACTIVE]
            bb = [min(xs), min(ys), max(xe) - min(xs), max(ye) - min(ys), exp]
            OVERLAYACTIVE.clear()
            OVERLAYACTIVE.append(bb)
        except Exception:
            pass


def gpuwindowrelease(win):

    gpuwindowlayersrelease(win)
    gpuwindowscenerelease(win)
    gpuwindowcpurelease(win)


def gpuwindowcpurelease(win):

    try:

        handle = win.get("_gpu_texture")

        if handle is not None:
            gputexturedestroy(handle)

    except Exception:
        pass

    win["_gpu_texture"] = None
    win["_gpu_width"] = 0
    win["_gpu_height"] = 0


def gpuwindowscenerelease(win):

    resource = win.get("_gpu_scene")

    try:

        if isinstance(resource, dict) and resource.get("handle") is not None:
            gputargetdestroy(int(resource["handle"]))

    except Exception:
        pass

    win["_gpu_scene"] = None
    win["_gpu_scene_damage"] = []


def gpuwindowlayersrelease(win):

    layers = win.get("_gpu_layers", {})

    if not isinstance(layers, dict):
        layers = {}

    for resource in list(layers.values()):

        try:

            handle = int(resource.get("handle", 0))

            if handle:
                gputargetdestroy(handle)

        except Exception:
            pass

    win["_gpu_layers"] = {}


def gpuwindowlayersprune(win):

    layers = win.get("_gpu_layers", {})

    if not isinstance(layers, dict) or not layers:
        win["_gpu_layers"] = {} if not isinstance(layers, dict) else layers
        return 0

    active = {
        str(command.get("id", ""))
        for command in win.get("gpu_commands", [])
        if str(command.get("kind", "")) == "layer" and command.get("id")
    }
    removed = 0

    for layerid in list(layers):

        if str(layerid) in active:
            continue

        resource = layers.pop(layerid, None)

        try:
            if isinstance(resource, dict) and resource.get("handle") is not None:
                gputargetdestroy(int(resource["handle"]))
        except Exception:
            pass

        removed += 1

    return removed


def gpuwindowmanagedonly(win):

    commands = win.get("gpu_commands", [])

    if not isinstance(commands, list) or not commands:
        return False

    first = commands[0]

    if not isinstance(first, dict) or str(first.get("kind", "")) != "rectangle":
        return False

    try:

        width = int(win.get("w", 0))
        height = int(win.get("h", 0))
        rect = [int(value) for value in first.get("rect", [])]
        clip = [int(value) for value in first.get("clip", [0, 0, width, height])]
        color = list(first.get("color", []))
        alpha = int(color[3]) if len(color) > 3 else 255
        return (
            width > 0
            and height > 0
            and rect == [0, 0, width, height]
            and clip[0] <= 0
            and clip[1] <= 0
            and clip[0] + clip[2] >= width
            and clip[1] + clip[3] >= height
            and alpha >= 255
            and float(first.get("opacity", 1.0)) >= 0.9999
        )

    except Exception:
        return False


def gpuwindowretainedsystem(win):

    # Complete managed system scenes are rendered into their retained texture
    # and resolved to scan-out with one simple draw on every provider. Besides
    # keeping uploads and complex scene work out of the scan-out pass, this
    # makes it unnecessary to copy a just-completed full-screen system frame
    # back into the compositor preservation texture.
    if not bool(win.get("_managed_only", False)):
        return False

    commands = win.get("gpu_commands", [])

    if (
        gpuwindowdynamicvideo(win)
        or any(str(command.get("kind", "")) == "layer" for command in commands)
    ):
        return False

    role = str(win.get("role", "")).strip().lower()

    return role in ("boot animation", "system animation", "lockscreen", "startup")


def gpuwindowdynamicvideo(win):

    return any(
        isinstance(command, dict)
        and str(command.get("kind", "")) == "video"
        and str(command.get("stream", "")) in win.get("_video_streams", {})
        for command in win.get("gpu_commands", [])
    )


def gpuwindowscenedirty(win):

    commands = win.get("gpu_commands", [])

    if (
        not gpuwindowmanagedonly(win)
        or gpuwindowdynamicvideo(win)
        or any(str(command.get("kind", "")) == "layer" for command in commands)
    ):
        return False

    resource = win.get("_gpu_scene")

    if not isinstance(resource, dict):
        return True

    if (
        int(resource.get("width", 0)) != max(1, int(win.get("w", 0)))
        or int(resource.get("height", 0)) != max(1, int(win.get("h", 0)))
        or int(resource.get("generation", -1)) != int(win.get("_gpu_generation", 0))
        or gputextureinfo(resource.get("handle")) is None
    ):
        return True

    return bool(GPUANIMATIONS.get(int(win.get("id", 0)))) or gpuwindow3danimated(win)


def gpuprewarmwindowtexts(win):

    grouped = {}

    for command in win.get("gpu_commands", []):

        values = [command]

        if str(command.get("kind", "")) == "console_grid":
            values = list(command.get('texts', [])) + [
                value for value in command.get('overlays', [])
                if str(value.get('kind', '')) == 'text'
            ]

        for value in values:

            if str(value.get("kind", "")) != "text":
                continue

            text = str(value.get("text", ""))

            if not text:
                continue

            key = (
                max(1, min(256, int(value.get("size", 16)))),
                str(value.get("font", WINDOWFONT) or WINDOWFONT),
            )
            grouped[key] = grouped.get(key, "") + text

    warmed = 0

    for (size, font), text in grouped.items():
        warmed += int(gpuprewarmtext(text, sizes=(size,), fontpath=font))

    return warmed


def gpuprewarmretainedsystemtexts():

    warmed = 0
    roles = []

    # Complete demand-loaded text uploads before gpubeginregions() touches the
    # scan-out target. The system commands themselves are then rendered into a
    # retained off-screen target and resolved to scan-out as one texture draw.
    for wid in zorder:

        win = windows.get(wid)

        if win is None or not win.get("mapped") or not gpuwindowretainedsystem(win):
            continue

        created = int(gpuprewarmwindowtexts(win))

        if created:
            warmed += created
            roles.append(str(win.get("role", "system")))

    if warmed:
        graphicslog(
            f"> graphics retained system glyph uploads complete "
            f"glyphs={int(warmed)} roles={roles}"
        )

    return warmed


def gpupreparewindowscenes(regions, culled=None):

    global GPUSCENEUPDATESQUEUED, GPUSCENEUPDATESCOMPLETED, GPUSCENEUPDATEPEAK, GPUSCENEUPDATEMS

    culled = set() if culled is None else set(culled)
    candidates = []

    for index, wid in enumerate(zorder):

        win = windows.get(wid)

        if (
            win is None
            or not win.get("mapped")
            or wid in culled
            or not gpuwindowscenedirty(win)
        ):
            continue

        visual = gpuvisualrect(win)

        if not any(rectintersect(*visual, *region)[2] > 0 for region in regions):
            continue

        candidates.append((0 if int(wid) == int(FOCUSWID or -1) else 1, -index, win))

    candidates.sort(key=lambda value: (value[0], value[1]))
    queued = len(candidates)
    GPUSCENEUPDATESQUEUED += queued
    GPUSCENEUPDATEPEAK = max(int(GPUSCENEUPDATEPEAK), queued)
    started = time.monotonic_ns()
    completed = 0

    for _, _, win in candidates:

        gpuprewarmwindowtexts(win)
        gpuwindowscenetexture(win)
        completed += 1

    GPUSCENEUPDATESCOMPLETED += completed
    GPUSCENEUPDATEMS += (time.monotonic_ns() - started) / 1000000.0
    return completed


def gpuwindowscenetexture(win):

    commands = win.get("gpu_commands", [])

    if not gpuwindowmanagedonly(win) or any(str(command.get("kind", "")) == "layer" for command in commands):
        gpuwindowscenerelease(win)
        return None

    width = max(1, int(win.get("w", 0)))
    height = max(1, int(win.get("h", 0)))
    generation = int(win.get("_gpu_generation", 0))
    animationstamp = int(time.monotonic() * 60.0) if GPUANIMATIONS.get(int(win.get("id", 0))) or gpuwindow3danimated(win) else None
    resource = win.get("_gpu_scene")
    recreate = not isinstance(resource, dict)

    if not recreate:
        recreate = (
            int(resource.get("width", 0)) != width
            or int(resource.get("height", 0)) != height
            or gputextureinfo(resource.get("handle")) is None
        )

    if recreate:

        gpuwindowscenerelease(win)
        handle = gputargetcreate(width, height, owner=f"window:{int(win.get('id', 0))}:managed-scene"[:128])
        resource = {
            "handle": int(handle),
            "width": width,
            "height": height,
            "generation": -1,
            "animation_stamp": None,
            "prepared_frame": -1,
        }
        win["_gpu_scene"] = resource
        win["_gpu_scene_damage"] = [[0, 0, width, height]]

    unchanged = (
        int(resource.get("generation", -1)) == generation
        and (
            int(resource.get("prepared_frame", -1)) == int(GPUFRAMESEQUENCE)
            or resource.get("animation_stamp") == animationstamp
        )
    )

    if unchanged:
        win["_telemetry_scene_texture_hits"] = int(win.get("_telemetry_scene_texture_hits", 0)) + 1
        return int(resource["handle"])

    damage = [list(value) for value in win.get("_gpu_scene_damage", []) if isinstance(value, (list, tuple)) and len(value) == 4]

    if recreate or animationstamp is not None or not damage:
        damage = [[0, 0, width, height]]
    else:
        damage = coalescerects(damage, GPUCOMMANDDAMAGELIMIT)

    targetstate = gputargetbegin(resource["handle"], clearcolor=(0, 0, 0, 0), clear=bool(recreate))

    try:

        full = len(damage) == 1 and [int(value) for value in damage[0]] == [0, 0, width, height]
        context = gpucommandcontext(win, width, height)
        statistics = {"considered": 0, "culled": 0, "drawn": 0}

        if full:
            gpudrawwindowcommands(win, 0, 0, width, height, 1.0, damageclip=None, context=context, statistics=statistics)
        else:

            for localclip in damage:
                gpudrawwindowcommands(win, 0, 0, width, height, 1.0, damageclip=localclip, context=context, statistics=statistics)

    except Exception:

        gputargetend(targetstate)
        gpuwindowscenerelease(win)
        raise

    else:
        gputargetend(targetstate)

    resource["generation"] = generation
    resource["animation_stamp"] = animationstamp
    resource["prepared_frame"] = int(GPUFRAMESEQUENCE)
    win["_gpu_scene_damage"] = []
    win["_telemetry_scene_texture_renders"] = int(win.get("_telemetry_scene_texture_renders", 0)) + 1
    win["_telemetry_scene_texture_full_renders" if full else "_telemetry_scene_texture_partial_renders"] = int(
        win.get("_telemetry_scene_texture_full_renders" if full else "_telemetry_scene_texture_partial_renders", 0)
    ) + 1
    win["_telemetry_scene_texture_damage_pixels"] = int(win.get("_telemetry_scene_texture_damage_pixels", 0)) + sum(
        max(0, int(value[2])) * max(0, int(value[3])) for value in damage
    )
    win["_telemetry_scene_commands_considered"] = int(win.get("_telemetry_scene_commands_considered", 0)) + int(statistics["considered"])
    win["_telemetry_scene_commands_culled"] = int(win.get("_telemetry_scene_commands_culled", 0)) + int(statistics["culled"])
    win["_telemetry_scene_commands_drawn"] = int(win.get("_telemetry_scene_commands_drawn", 0)) + int(statistics["drawn"])
    return int(resource["handle"])


def gpuwindowtexture(win):

    width, height = windowbufferdimensions(win)

    if width < 1 or height < 1:
        return None

    handle = win.get("_gpu_texture")
    recreate = handle is None or gputextureinfo(handle) is None
    recreate = recreate or int(win.get("_gpu_width", 0)) != width
    recreate = recreate or int(win.get("_gpu_height", 0)) != height

    if recreate:

        gpuwindowrelease(win)
        handle = gputexturecreate(
            width,
            height,
            fmt=win.get("format", "BGRA32"),
            owner=f"window:{int(win.get('id', 0))}",
            alpha=bool(win.get("pixel_alpha", False)),
        )
        win["_gpu_texture"] = handle
        win["_gpu_width"] = width
        win["_gpu_height"] = height
        win["damage"] = [[0, 0, width, height]]

    damage = list(win.get("damage", []))

    if damage:

        damage = coalescerects(damage, 64)

        for x, y, w, h in damage:

            x = max(0, int(x))
            y = max(0, int(y))
            w = min(width - x, int(w))
            h = min(height - y, int(h))

            if w < 1 or h < 1:
                continue

            uploaded = gputextureupdate(
                handle,
                x,
                y,
                w,
                h,
                path=win["buffer"],
                stride=int(win.get("buffer_stride", width * 4)),
                fmt=win.get("format", "BGRA32"),
                source_offset=int(win.get("buffer_offset", 0)),
            )
            win["_telemetry_gpu_upload_bytes"] = int(win.get("_telemetry_gpu_upload_bytes", 0)) + int(uploaded)

        win["damage"] = []

    return handle


def gpuwindoweffect(win):

    opacity = max(0.0, min(1.0, float(win.get("opacity", 1.0))))
    scale = max(0.25, min(4.0, float(win.get("scale", 1.0))))
    offsetx = 0.0
    offsety = 0.0
    start = win.get("_gpu_transition_start")

    if GPUTRANSITIONS and start is not None:

        duration = max(0, int(win.get("_gpu_transition_ms", GPUTRANSITIONMS))) / 1000.0

        if duration > 0.0:

            progress = (time.monotonic() - float(start)) / duration

            if progress < 1.0:

                progress = max(0.0, progress)
                eased = gpuanimationeased(progress, win.get("transition_easing", "ease_out"))
                style = str(win.get("transition_style", "fade_scale"))

                if style in ("fade", "fade_scale"):
                    opacity *= eased

                if style in ("scale", "fade_scale"):
                    scale *= 0.96 + (0.04 * eased)

                if style == "slide":
                    offsety = float(scalesize(20)) * (1.0 - eased)

            else:
                win.pop("_gpu_transition_start", None)

        else:
            win.pop("_gpu_transition_start", None)

    return opacity, scale, offsetx, offsety


def gpuwindow3danimated(win):

    if not isinstance(win, dict) or not win.get("mapped"):
        return False

    for command in win.get("gpu_commands", []):

        if str(command.get("kind", "")) != "scene3d":
            continue

        for mesh in command.get("meshes", []):

            if any(abs(float(value)) > 0.0001 for value in mesh.get("rotation_speed", [])):
                return True

    return False


def gpuanimationsactive():

    if not GPUCOMPOSITOR:
        return False

    if GPUTRANSITIONS:

        for win in windows.values():

            if not win.get("mapped"):
                continue

            start = win.get("_gpu_transition_start")

            if start is None:
                continue

            # Keep scheduling the transition until gpuwindoweffect() has painted
            # and removed it.  In particular, an expired transition still needs
            # one final frame at full opacity and scale; otherwise the last
            # partially faded frame remains until unrelated damage arrives.
            return True

    for wid, animations in list(GPUANIMATIONS.items()):

        if animations and wid in windows and windows[wid].get("mapped"):
            return True

    if any(gpuwindow3danimated(win) for win in windows.values()):
        return True

    return False


def gpuwindowiconpixels(kind, size, ratio=1.0, maximized=False, colors=None):

    size = max(1, int(size))
    ratio = max(0.25, min(4.0, float(ratio)))
    pixels = bytearray(size * size * 4)

    colors = graphicswindowtheme() if colors is None else colors

    if kind == "close":
        color = tuple(colors["close"]) + (255,)
    elif kind == "max":
        color = tuple(colors["max"]) + (255,)
    elif kind == "min":
        color = tuple(colors["min"]) + (255,)
    else:
        raise ValueError(f"unknown window icon {kind}")

    def setpoint(px, py):

        if px < 0 or py < 0 or px >= size or py >= size:
            return

        offset = (int(py) * size + int(px)) * 4
        pixels[offset:offset + 4] = bytes(color)

    if kind == "close":

        pad = max(1, int(round(scalesize(4) * ratio)))
        extent = size - pad * 2

        for index in range(max(0, extent)):
            setpoint(pad + index, pad + index)
            setpoint(pad + index, size - pad - 1 - index)

    elif kind == "max":

        pad = max(1, int(round(scalesize(4) * ratio)))
        innerstart = pad
        innerend = size - pad - 1
        innerwidth = innerend - innerstart + 1

        def square(left, top, width):

            if width < 1:
                return

            right = left + width - 1
            bottom = top + width - 1

            for px in range(left, right + 1):
                setpoint(px, top)
                setpoint(px, bottom)

            for py in range(top, bottom + 1):
                setpoint(left, py)
                setpoint(right, py)

        if innerwidth > 0 and maximized:

            delta = max(1, int(round(scalesize(2) * ratio)))
            squarewidth = innerwidth - delta

            if squarewidth < 2:
                squarewidth = innerwidth
                delta = 0

            square(innerstart, innerstart, squarewidth)
            square(innerstart + delta, innerstart + delta, squarewidth)

        elif innerwidth > 0:
            square(innerstart, innerstart, innerwidth)

    elif kind == "min":

        pad = max(1, int(round(scalesize(5) * ratio)))
        start = pad
        end = size - pad
        py = size - pad

        for px in range(start, end + 1):
            setpoint(px, py)

    return bytes(pixels)


def gpuwindowicontexture(kind, size, ratio=1.0, maximized=False, colors=None):

    ratio = max(0.25, min(4.0, float(ratio)))
    colors = graphicswindowtheme() if colors is None else colors
    iconcolor = tuple(colors[str(kind)])
    key = (
        str(kind),
        int(size),
        bool(maximized),
        iconcolor,
        max(1, int(round(scalesize(2) * ratio))),
        max(1, int(round(scalesize(4) * ratio))),
        max(1, int(round(scalesize(5) * ratio))),
    )
    handle = GPUCHROMETEXTURES.get(key)

    if handle is not None and gputextureinfo(handle) is not None:
        return handle

    pixels = gpuwindowiconpixels(kind, size, ratio=ratio, maximized=maximized, colors=colors)
    handle = gputexturecreate(
        int(size),
        int(size),
        fmt="RGBA32",
        data=pixels,
        owner=f"window-chrome:{kind}",
        alpha=True,
    )
    GPUCHROMETEXTURES[key] = handle
    return handle


def gpuframegeometry(win, x, y, width, height, opacity, clip=None):

    role = str(win.get("role", ""))

    if role != "window" or isfullscreen(win):
        return

    originalwidth = max(1.0, float(win.get("w", width)))
    ratio = max(0.25, min(4.0, float(width) / originalwidth))
    frame = max(1, int(round(FRAMEW * ratio)))
    title = max(8, int(round(TITLEH * ratio)))
    button = max(8, int(round(BTNWH * ratio)))
    gap = max(2, int(round(BTNGAP * ratio)))
    hoverarea = windowbuttonhoverarea(win)

    def drawhover(buttonx, chromey, chromeheight):

        if hoverarea is None:
            return

        side = max(1, int(chromeheight))
        hoverx = float(buttonx) + button / 2.0 - side / 2.0
        hovercolor = tuple(graphicscolor(WINDOWBUTTONHOVER))
        gpubatchrects([
            (hoverx, chromey, side, side, hovercolor, opacity),
        ], clip=clip)

    if clientchromemode(win):
        chromeh = max(button, int(round(clientchromeheight(win) * ratio)))
        titleheight = max(button, int(round(TITLEH * ratio)))
        button_gap = max(gap, titleheight - button)
        closex = float(x) + float(width) - frame - gap - button
        buttony = float(y) + max(0, (titleheight - button) // 2)
        maxx = closex - button_gap - button
        minx = maxx - button_gap - button
        colors = windowcontrolcolors(win)

        if clientchromecontrols(win) != "chromium":
            titlecolor = tuple(colors["title"]) + (255,)
            gpubatchrects([
                (closex, buttony, button, button, titlecolor, opacity),
                (maxx, buttony, button, button, titlecolor, opacity),
                (minx, buttony, button, button, titlecolor, opacity),
            ], clip=clip)

            hoverx = {"close": closex, "max": maxx, "min": minx}.get(hoverarea)

            if hoverx is not None:
                drawhover(hoverx, float(y), chromeh)

        closeicon = gpuwindowicontexture("close", button, ratio=ratio, colors=colors)
        maxicon = gpuwindowicontexture("max", button, ratio=ratio, maximized=ismaximized(win), colors=colors)
        minicon = gpuwindowicontexture("min", button, ratio=ratio, colors=colors)
        gpudrawtexture(closeicon, closex, buttony, button, button, opacity=opacity, clip=clip)
        gpudrawtexture(maxicon, maxx, buttony, button, button, opacity=opacity, clip=clip)
        gpudrawtexture(minicon, minx, buttony, button, button, opacity=opacity, clip=clip)
        return

    fx = float(x) - frame
    fy = float(y) - title - frame
    fw = float(width) + frame * 2
    fh = float(height) + title + frame * 2
    colors = windowcontrolcolors(win)
    titlecolor = tuple(colors["title"]) + (255,)
    bordercolor = tuple(colors["border"]) + (255,)
    gpubatchrects([
        (fx + frame, fy + frame, fw - frame * 2, title, titlecolor, opacity),
        (fx, fy, fw, frame, bordercolor, opacity),
        (fx, fy + fh - frame, fw, frame, bordercolor, opacity),
        (fx, fy, frame, fh, bordercolor, opacity),
        (fx + fw - frame, fy, frame, fh, bordercolor, opacity),
    ], clip=clip)
    closex = fx + fw - frame - gap - button
    buttony = fy + max(0, (title - button) // 2)
    button_gap = max(gap, title - button)
    maxx = closex - button_gap - button
    minx = maxx - button_gap - button
    hoverx = {"close": closex, "max": maxx, "min": minx}.get(hoverarea)

    if hoverx is not None:
        drawhover(hoverx, fy + frame, title)

    closeicon = gpuwindowicontexture("close", button, ratio=ratio, colors=colors)
    maxicon = gpuwindowicontexture("max", button, ratio=ratio, maximized=ismaximized(win), colors=colors)
    minicon = gpuwindowicontexture("min", button, ratio=ratio, colors=colors)
    gpudrawtexture(closeicon, closex, buttony, button, button, opacity=opacity, clip=clip)
    gpudrawtexture(maxicon, maxx, buttony, button, button, opacity=opacity, clip=clip)
    gpudrawtexture(minicon, minx, buttony, button, button, opacity=opacity, clip=clip)


def gpucommandstates(commands, width, height, overrides=None):

    nodes = {
        str(command.get("id")): command
        for command in commands
        if command.get("id") and str(command.get("kind", "")) in ("group", "layer")
    }
    states = {}
    overrides = {} if overrides is None else overrides

    def resolve(command, stack=None):

        key = str(command.get("id", f"object:{id(command)}"))

        if key in states:
            return states[key]

        stack = set() if stack is None else set(stack)

        if key in stack:
            raise RuntimeError("graphics scene contains a parent cycle")

        stack.add(key)
        parent = nodes.get(str(command.get("parent", "")))

        if parent is None:
            state = {
                "translate": [0.0, 0.0],
                "scale": [1.0, 1.0],
                "rotation": 0.0,
                "rotation_origin": None,
                "opacity": 1.0,
                "effect": "none",
                "clip": [0.0, 0.0, float(width), float(height)],
            }
        else:
            state = dict(resolve(parent, stack))
            state["translate"] = list(state["translate"])
            state["scale"] = list(state["scale"])
            state["clip"] = list(state["clip"])

        properties = dict(command)
        properties.update(overrides.get(str(command.get("id", "")), {}))
        translate = properties.get("translate", [0.0, 0.0])
        scale = properties.get("scale", [1.0, 1.0])
        scroll = command.get("scroll", [0.0, 0.0])
        parenttranslate = list(state["translate"])
        parentscale = list(state["scale"])
        tx = parenttranslate[0] + (float(translate[0]) - float(scroll[0])) * parentscale[0]
        ty = parenttranslate[1] + (float(translate[1]) - float(scroll[1])) * parentscale[1]
        sx = parentscale[0] * float(scale[0])
        sy = parentscale[1] * float(scale[1])
        rotation = float(state["rotation"]) + float(properties.get("rotation", 0.0))
        rotationorigin = state.get("rotation_origin")

        if float(properties.get("rotation", 0.0)):
            rotationorigin = [tx, ty]

        commandclip = command.get("clip", [0, 0, int(width), int(height)])
        transformedclip = [
            tx + float(commandclip[0]) * sx,
            ty + float(commandclip[1]) * sy,
            float(commandclip[2]) * sx,
            float(commandclip[3]) * sy,
        ]
        parentclip = state["clip"]
        clipped = rectintersect(*transformedclip, *parentclip)
        output = {
            "translate": [tx, ty],
            "scale": [sx, sy],
            "rotation": rotation,
            "rotation_origin": rotationorigin,
            "opacity": float(state["opacity"]) * max(0.0, min(1.0, float(properties.get("opacity", 1.0)))),
            "effect": str(properties.get("effect", state.get("effect", "none"))).lower(),
            "clip": [float(value) for value in clipped],
        }
        states[key] = output
        return output

    for command in commands:
        resolve(command)

    return states


def gpucommandcontext(win, width, height):

    commands = win.get("gpu_commands", [])
    animationoverrides = gpuanimationoverrides(win)
    states = gpucommandstates(commands, int(width), int(height), overrides=animationoverrides)
    nodes = {
        str(command.get("id")): command
        for command in commands
        if command.get("id") and str(command.get("kind", "")) in ("group", "layer")
    }
    layerowners = {}

    for command in commands:

        current = nodes.get(str(command.get("parent", "")))
        owner = None
        seen = set()

        while current is not None:

            currentid = str(current.get("id", ""))

            if currentid in seen:
                break

            seen.add(currentid)

            if str(current.get("kind", "")) == "layer":
                owner = currentid
                break

            current = nodes.get(str(current.get("parent", "")))

        layerowners[id(command)] = owner

    return {
        "states": states,
        "nodes": nodes,
        "layerowners": layerowners,
        "animation_overrides": animationoverrides,
    }


def gpucommandclip(command, state, x, y, ratio, width, height, damageclip=None):

    clip = state.get("clip", [0, 0, int(width), int(height)])
    clipx = int(round(float(x) + float(clip[0]) * ratio))
    clipy = int(round(float(y) + float(clip[1]) * ratio))
    clipwidth = max(1, int(round(float(clip[2]) * ratio)))
    clipheight = max(1, int(round(float(clip[3]) * ratio)))
    windowx = int(round(float(x)))
    windowy = int(round(float(y)))
    windowwidth = max(1, int(round(float(width))))
    windowheight = max(1, int(round(float(height))))
    output = rectintersect(clipx, clipy, clipwidth, clipheight, windowx, windowy, windowwidth, windowheight)

    if damageclip is not None:
        output = rectintersect(output[0], output[1], output[2], output[3], *[int(value) for value in damageclip])

    return output


def gpucommandpoint(px, py, state, x, y, ratio):

    localx = float(state["translate"][0]) + float(px) * float(state["scale"][0])
    localy = float(state["translate"][1]) + float(py) * float(state["scale"][1])
    return float(x) + localx * ratio, float(y) + localy * ratio


def gpucommandorigin(state, x, y, ratio):

    origin = state.get("rotation_origin")

    if origin is None:
        return None

    return float(x) + float(origin[0]) * ratio, float(y) + float(origin[1]) * ratio


def gpucommandrotatepoint(point, rotation, origin):

    if not float(rotation) or origin is None:
        return point

    px, py = [float(value) for value in point]
    ox, oy = [float(value) for value in origin]
    radians = math.radians(float(rotation))
    cosine = math.cos(radians)
    sine = math.sin(radians)
    dx = px - ox
    dy = py - oy
    return ox + dx * cosine - dy * sine, oy + dx * sine + dy * cosine


def gpucommandintersects(command, kind, state, x, y, ratio, clip):

    # Scissoring limits fragment work, but constructing glyph quads and
    # submitting every retained command still costs CPU time.  Reject commands
    # whose conservative transformed bounds do not touch this damage region.
    # Rotated nodes retain the established path because their axis-aligned
    # bounds require a corner transform and animations make that uncommon case
    # more important for correctness than this fast-path optimisation.
    if abs(float(state.get("rotation", 0.0))) > 0.0001:
        return True

    scalex = float(state["scale"][0])
    scaley = float(state["scale"][1])
    bounds = None

    if kind in ("rectangle", "rounded_rectangle", "border", "gradient", "image", "video", "layer", "scene3d", "console_grid"):

        rx, ry, rw, rh = command.get("rect", [0, 0, 0, 0])
        drawx, drawy = gpucommandpoint(rx, ry, state, x, y, ratio)
        bounds = [drawx, drawy, float(rw) * scalex * ratio, float(rh) * scaley * ratio]

    elif kind == "circle":

        cx, cy = command.get("center", [0, 0])
        centerx, centery = gpucommandpoint(cx, cy, state, x, y, ratio)
        radius = float(command.get("radius", 0.0)) * max(scalex, scaley) * ratio
        bounds = [centerx - radius, centery - radius, radius * 2.0, radius * 2.0]

    elif kind == "line":

        x0, y0, x1, y1 = command.get("points", [0, 0, 0, 0])
        point0 = gpucommandpoint(x0, y0, state, x, y, ratio)
        point1 = gpucommandpoint(x1, y1, state, x, y, ratio)
        padding = max(1.0, float(command.get("width", 1.0)) * max(scalex, scaley) * ratio)
        left = min(point0[0], point1[0]) - padding
        top = min(point0[1], point1[1]) - padding
        bounds = [left, top, abs(point1[0] - point0[0]) + padding * 2.0, abs(point1[1] - point0[1]) + padding * 2.0]

    elif kind == "text":

        drawx, drawy = gpucommandpoint(command.get("x", 0), command.get("y", 0), state, x, y, ratio)
        fontsize = max(1.0, float(command.get("size", 1.0)) * min(scalex, scaley) * ratio)
        length = max(1, len(str(command.get("text", ""))))
        # The installed UI fonts normally advance at roughly 0.6 em.  A 1.5
        # em bound plus vertical margins is deliberately conservative so a
        # valid glyph is never removed merely to improve damage rendering.
        bounds = [drawx - fontsize, drawy - fontsize * 0.25, length * fontsize * 1.5 + fontsize * 2.0, fontsize * 2.0]

    if bounds is None:
        return True

    bx = int(math.floor(float(bounds[0])))
    by = int(math.floor(float(bounds[1])))
    bw = max(1, int(math.ceil(float(bounds[2]))))
    bh = max(1, int(math.ceil(float(bounds[3]))))
    return rectintersect(bx, by, bw, bh, *[int(value) for value in clip])[2] > 0


def gpudrawwindowcommands(win, x, y, width, height, opacity, damageclip=None, layerid=None, opacitydivisor=1.0, context=None, statistics=None):

    global GPUCOMMANDERRORS, GPUCOMMANDLASTERROR

    commands = win.get("gpu_commands", [])

    if not isinstance(commands, list) or not commands:
        return 0

    originalwidth = max(1.0, float(win.get("w", width)))
    ratio = max(0.25, min(4.0, float(width) / originalwidth))
    context = context if isinstance(context, dict) else gpucommandcontext(win, int(win.get("w", width)), int(win.get("h", height)))
    states = context["states"]
    layerowners = context["layerowners"]
    statistics = statistics if isinstance(statistics, dict) else {}
    statistics.setdefault("considered", 0)
    statistics.setdefault("culled", 0)
    startingdraws = 0

    drawn = 0
    rectanglebatch = []
    rectangleclip = None
    rectangleeffect = None
    textbatch = []
    textclip = None
    texteffect = None
    roundedbatch = []
    roundedkey = None
    roundedclip = None
    roundedeffect = None
    circlebatch = []
    circlekey = None
    circleclip = None
    circleeffect = None
    linebatch = []
    lineclip = None
    lineeffect = None
    gradientbatch = []
    gradientclip = None
    gradienteffect = None

    def flushrectangles():

        nonlocal drawn, rectanglebatch, rectangleclip, rectangleeffect

        if rectanglebatch:
            gpubatchrects(rectanglebatch, clip=rectangleclip, effect=rectangleeffect or "none")
            drawn += len(rectanglebatch)

        rectanglebatch = []
        rectangleclip = None
        rectangleeffect = None

    def flushtexts():

        nonlocal drawn, textbatch, textclip, texteffect

        if textbatch:
            gpubatchtexts(textbatch, clip=textclip, effect=texteffect or "none")
            drawn += len(textbatch)

        textbatch = []
        textclip = None
        texteffect = None

    def flushrounded():

        nonlocal drawn, roundedbatch, roundedkey, roundedclip, roundedeffect

        if roundedbatch:
            gpubatchroundedrects(roundedbatch, clip=roundedclip, effect=roundedeffect or "none")
            drawn += len(roundedbatch)

        roundedbatch = []
        roundedkey = None
        roundedclip = None
        roundedeffect = None

    def flushcircles():

        nonlocal drawn, circlebatch, circlekey, circleclip, circleeffect

        if circlebatch:
            gpubatchcircles(circlebatch, clip=circleclip, effect=circleeffect or "none")
            drawn += len(circlebatch)

        circlebatch = []
        circlekey = None
        circleclip = None
        circleeffect = None

    def flushlines():

        nonlocal drawn, linebatch, lineclip, lineeffect

        if linebatch:
            gpubatchlines(linebatch, clip=lineclip, effect=lineeffect or "none")
            drawn += len(linebatch)

        linebatch = []
        lineclip = None
        lineeffect = None

    def flushgradients():

        nonlocal drawn, gradientbatch, gradientclip, gradienteffect

        if gradientbatch:
            gpubatchgradients(gradientbatch, clip=gradientclip, effect=gradienteffect or "none")
            drawn += len(gradientbatch)

        gradientbatch = []
        gradientclip = None
        gradienteffect = None

    def flushbatches():

        flushrectangles()
        flushtexts()
        flushrounded()
        flushcircles()
        flushlines()
        flushgradients()

    for command in commands[:GPUCOMMANDLIMIT]:

        try:

            kind = str(command.get("kind", ""))
            owner = layerowners.get(id(command))

            if layerid is None:

                if owner is not None:
                    continue

            elif owner != str(layerid):
                continue

            statistics["considered"] += 1

            statekey = str(command.get("id", f"object:{id(command)}"))
            state = states[statekey]
            clip = gpucommandclip(command, state, x, y, ratio, width, height, damageclip=damageclip)

            if clip[2] < 1 or clip[3] < 1:
                statistics["culled"] += 1
                continue

            if not gpucommandintersects(command, kind, state, x, y, ratio, clip):
                statistics["culled"] += 1
                continue

            commandopacity = opacity * float(state["opacity"]) / max(0.000001, float(opacitydivisor))
            commandopacity = max(0.0, min(1.0, commandopacity))
            commandeffect = str(state.get("effect", "none"))
            rotation = float(state.get("rotation", 0.0))
            origin = gpucommandorigin(state, x, y, ratio)

            if kind == "layer":

                flushbatches()

                if layerid is None:
                    drawn += gpudrawwindowlayer(win, command, state, x, y, width, height, opacity, clip, context=context)

                continue

            if kind == "group":
                flushbatches()
                continue

            if kind == "console_grid":

                flushbatches()

                for phase in ('backgrounds', 'texts', 'overlays'):
                    rectangles = []
                    texts = []

                    for item in command.get(phase, []):
                        itemkind = str(item.get('kind', ''))
                        itemopacity = commandopacity * max(0.0, min(1.0, float(item.get('opacity', 1.0))))

                        if itemkind == 'rectangle':
                            rx, ry, rw, rh = item['rect']
                            drawx, drawy = gpucommandpoint(rx, ry, state, x, y, ratio)
                            rectangles.append((
                                drawx,
                                drawy,
                                float(rw) * float(state['scale'][0]) * ratio,
                                float(rh) * float(state['scale'][1]) * ratio,
                                item['color'],
                                itemopacity,
                            ))

                        elif itemkind == 'text':
                            drawx, drawy = gpucommandpoint(item['x'], item['y'], state, x, y, ratio)
                            texts.append({
                                'x': drawx,
                                'y': drawy,
                                'text': item['text'],
                                'color': item['color'],
                                'size': max(1, min(256, int(round(
                                    float(item['size']) * min(float(state['scale'][0]), float(state['scale'][1])) * ratio
                                )))),
                                'font': item['font'],
                                'opacity': itemopacity,
                                'rotation': rotation,
                                'origin': origin,
                            })

                    if rectangles:
                        gpubatchrects(rectangles, clip=clip, effect=commandeffect)
                        drawn += len(rectangles)

                    if texts:
                        gpubatchtexts(texts, clip=clip, effect=commandeffect)
                        drawn += len(texts)

                continue

            if kind == "rectangle":

                flushtexts()
                flushrounded()
                flushcircles()
                flushlines()
                flushgradients()

                rx, ry, rw, rh = command["rect"]
                drawx, drawy = gpucommandpoint(rx, ry, state, x, y, ratio)
                drawwidth = float(rw) * float(state["scale"][0]) * ratio
                drawheight = float(rh) * float(state["scale"][1]) * ratio
                currentclip = tuple(int(value) for value in clip)

                if rectanglebatch and (currentclip != rectangleclip or rotation or commandeffect != rectangleeffect):
                    flushrectangles()

                if rotation:

                    gpudrawrect(
                        drawx,
                        drawy,
                        drawwidth,
                        drawheight,
                        command["color"],
                        opacity=commandopacity,
                        clip=clip,
                        rotation=rotation,
                        origin=origin,
                        effect=commandeffect,
                    )
                    drawn += 1
                    continue

                rectangleclip = currentclip
                rectangleeffect = commandeffect
                rectanglebatch.append((
                    drawx,
                    drawy,
                    drawwidth,
                    drawheight,
                    command["color"],
                    commandopacity,
                ))
                continue

            elif kind == "rounded_rectangle":

                flushrectangles()
                flushtexts()
                flushcircles()
                flushlines()
                flushgradients()
                rx, ry, rw, rh = command["rect"]
                drawx, drawy = gpucommandpoint(rx, ry, state, x, y, ratio)
                drawwidth = float(rw) * float(state["scale"][0]) * ratio
                drawheight = float(rh) * float(state["scale"][1]) * ratio
                radius = float(command.get("radius", 0.0)) * min(float(state["scale"][0]), float(state["scale"][1])) * ratio
                currentclip = tuple(int(value) for value in clip)
                currentkey = (round(drawwidth, 4), round(drawheight, 4), round(radius, 4), currentclip, commandeffect)

                if roundedbatch and currentkey != roundedkey:
                    flushrounded()

                roundedkey = currentkey
                roundedclip = currentclip
                roundedeffect = commandeffect
                roundedbatch.append((
                    drawx,
                    drawy,
                    drawwidth,
                    drawheight,
                    command["color"],
                    radius,
                    commandopacity,
                    rotation,
                    origin,
                ))
                continue

            elif kind == "border":

                rx, ry, rw, rh = command["rect"]
                drawx, drawy = gpucommandpoint(rx, ry, state, x, y, ratio)
                drawwidth = float(rw) * float(state["scale"][0]) * ratio
                drawheight = float(rh) * float(state["scale"][1]) * ratio
                borderwidth = max(1.0, float(command.get("width", 1.0)) * ratio)
                strips = [
                    (drawx, drawy, drawwidth, borderwidth),
                    (drawx, drawy + drawheight - borderwidth, drawwidth, borderwidth),
                    (drawx, drawy, borderwidth, drawheight),
                    (drawx + drawwidth - borderwidth, drawy, borderwidth, drawheight),
                ]
                flushbatches()

                if rotation:

                    for stripx, stripy, stripwidth, stripheight in strips:
                        gpudrawrect(stripx, stripy, stripwidth, stripheight, command["color"], opacity=commandopacity, clip=clip, rotation=rotation, origin=origin, effect=commandeffect)

                else:

                    gpubatchrects([
                        (stripx, stripy, stripwidth, stripheight, command["color"], commandopacity)
                        for stripx, stripy, stripwidth, stripheight in strips
                    ], clip=clip, effect=commandeffect)

                drawn += 4
                continue

            elif kind == "gradient":

                flushrectangles()
                flushtexts()
                flushrounded()
                flushcircles()
                flushlines()
                rx, ry, rw, rh = command["rect"]
                drawx, drawy = gpucommandpoint(rx, ry, state, x, y, ratio)
                currentclip = tuple(int(value) for value in clip)

                if gradientbatch and (currentclip != gradientclip or commandeffect != gradienteffect):
                    flushgradients()

                gradientclip = currentclip
                gradienteffect = commandeffect
                gradientbatch.append((
                    drawx,
                    drawy,
                    float(rw) * float(state["scale"][0]) * ratio,
                    float(rh) * float(state["scale"][1]) * ratio,
                    command["color"],
                    command["color2"],
                    command.get("direction", "vertical"),
                    commandopacity,
                    rotation,
                    origin,
                ))
                continue

            elif kind == "line":

                flushrectangles()
                flushtexts()
                flushrounded()
                flushcircles()
                flushgradients()
                x0, y0, x1, y1 = command["points"]
                point0 = gpucommandrotatepoint(gpucommandpoint(x0, y0, state, x, y, ratio), rotation, origin)
                point1 = gpucommandrotatepoint(gpucommandpoint(x1, y1, state, x, y, ratio), rotation, origin)
                currentclip = tuple(int(value) for value in clip)

                if linebatch and (currentclip != lineclip or commandeffect != lineeffect):
                    flushlines()

                lineclip = currentclip
                lineeffect = commandeffect
                linebatch.append((
                    point0[0], point0[1], point1[0], point1[1], command["color"],
                    float(command.get("width", 1.0)) * min(float(state["scale"][0]), float(state["scale"][1])) * ratio,
                    commandopacity,
                ))
                continue

            elif kind == "circle":

                flushrectangles()
                flushtexts()
                flushrounded()
                flushlines()
                flushgradients()
                cx, cy = command["center"]
                center = gpucommandrotatepoint(gpucommandpoint(cx, cy, state, x, y, ratio), rotation, origin)
                radius = float(command["radius"]) * min(float(state["scale"][0]), float(state["scale"][1])) * ratio
                currentclip = tuple(int(value) for value in clip)
                currentkey = (round(radius, 4), currentclip, commandeffect)

                if circlebatch and currentkey != circlekey:
                    flushcircles()

                circlekey = currentkey
                circleclip = currentclip
                circleeffect = commandeffect
                circlebatch.append((
                    center[0], center[1],
                    radius,
                    command["color"],
                    commandopacity,
                ))
                continue

            elif kind == "scene3d":

                flushbatches()
                rx, ry, rw, rh = command["rect"]
                drawx, drawy = gpucommandpoint(rx, ry, state, x, y, ratio)
                sceneelapsed = max(0.0, time.monotonic() - float(command.get("animation_started", time.monotonic())))
                drawn += gpudrawscene3d(
                    command,
                    drawx,
                    drawy,
                    float(rw) * float(state["scale"][0]) * ratio,
                    float(rh) * float(state["scale"][1]) * ratio,
                    opacity=commandopacity,
                    clip=clip,
                    elapsed=sceneelapsed,
                )
                continue

            elif kind == "video":

                flushbatches()
                VIDEOTELEMETRY["commands"] += 1
                surface = win.get("_video_streams", {}).get(str(command.get("stream", "")))

                if not isinstance(surface, dict):
                    VIDEOTELEMETRY["missing_surfaces"] += 1
                    continue

                rx, ry, rw, rh = command["rect"]
                drawx, drawy = gpucommandpoint(rx, ry, state, x, y, ratio)
                if gpudrawvideosurface(
                    int(surface.get("handle", 0)),
                    drawx,
                    drawy,
                    width=float(rw) * float(state["scale"][0]) * ratio,
                    height=float(rh) * float(state["scale"][1]) * ratio,
                    opacity=commandopacity,
                    clip=clip,
                ):
                    drawn += 1
                    if not bool(surface.get("presented", False)):
                        surface["presented"] = True
                        videoevent(
                            surface.get("connection", 0),
                            {
                                "op": "presented",
                                "frame": int(surface.get("frame", 0)),
                                "pts_ns": int(surface.get("pts_ns", 0)),
                                "presented_ns": time.monotonic_ns(),
                            },
                        )
                        VIDEOTELEMETRY["presented_frames"] += 1
                        releasepresentationframe(surface)
                        videopromotepending(
                            win,
                            str(command.get("stream", "")),
                            surface,
                        )
                else:
                    VIDEOTELEMETRY["draw_failures"] += 1
                continue

            elif kind == "image":

                flushbatches()

                rx, ry, rw, rh = command["rect"]
                drawx, drawy = gpucommandpoint(rx, ry, state, x, y, ratio)
                gpudrawimage(
                    command["path"],
                    command["source_width"],
                    command["source_height"],
                    drawx,
                    drawy,
                    width=float(rw) * float(state["scale"][0]) * ratio,
                    height=float(rh) * float(state["scale"][1]) * ratio,
                    fmt=command["format"],
                    revision=command.get("revision"),
                    opacity=commandopacity,
                    clip=clip,
                    rotation=rotation,
                    origin=origin,
                    effect=commandeffect,
                )

            elif kind == "text":

                flushrectangles()
                flushrounded()
                flushcircles()
                flushlines()
                flushgradients()
                drawx, drawy = gpucommandpoint(command["x"], command["y"], state, x, y, ratio)
                currentclip = tuple(int(value) for value in clip)

                if textbatch and (currentclip != textclip or commandeffect != texteffect):
                    flushtexts()

                textclip = currentclip
                texteffect = commandeffect
                textbatch.append({
                    "x": drawx,
                    "y": drawy,
                    "text": command["text"],
                    "color": command["color"],
                    "size": max(1, min(256, int(round(float(command["size"]) * min(float(state["scale"][0]), float(state["scale"][1])) * ratio)))),
                    "font": command["font"],
                    "opacity": commandopacity,
                    "rotation": rotation,
                    "origin": origin,
                })
                continue

            else:
                continue

            drawn += 1

        except Exception as e:

            GPUCOMMANDERRORS += 1
            GPUCOMMANDLASTERROR = f"window {win.get('id')} command {command.get('kind', '')} {e}"

            if win.get("_gpu_command_error") != str(e):
                win["_gpu_command_error"] = str(e)
                log(f"managed graphics command failed window {win.get('id')} {e}")

    flushbatches()

    statistics["drawn"] = int(statistics.get("drawn", 0)) + max(0, int(drawn) - startingdraws)

    return drawn


def gpudrawwindowlayer(win, command, state, x, y, width, height, opacity, clip, context=None):

    layerid = str(command.get("id", ""))

    if not layerid:
        raise RuntimeError("offscreen graphics layer requires a stable id")

    logicalwidth = max(1, int(win.get("w", width)))
    logicalheight = max(1, int(win.get("h", height)))
    context = context if isinstance(context, dict) else gpucommandcontext(win, logicalwidth, logicalheight)
    layerowners = context.get("layerowners", {})
    animationoverrides = context.get("animation_overrides", {})
    layercommand = dict(command)
    layercommand.pop("opacity", None)
    ownedcommands = [
        value
        for value in win.get("gpu_commands", [])
        if layerowners.get(id(value)) == layerid
    ]
    ownedids = {str(value.get("id", "")) for value in ownedcommands if value.get("id")}
    ownedids.add(layerid)
    signature = json.dumps({
        "layer": layercommand,
        "commands": ownedcommands,
        "animations": {
            nodeid: value
            for nodeid, value in animationoverrides.items()
            if str(nodeid) in ownedids
        },
    }, sort_keys=True, separators=(",", ":"))
    layers = win.setdefault("_gpu_layers", {})
    resource = layers.get(layerid)

    if resource is not None and (
        int(resource.get("width", 0)) != logicalwidth
        or int(resource.get("height", 0)) != logicalheight
        or gputextureinfo(resource.get("handle")) is None
    ):

        try:
            gputargetdestroy(resource.get("handle"))
        except Exception:
            pass

        layers.pop(layerid, None)
        resource = None

    if resource is None:

        handle = gputargetcreate(
            logicalwidth,
            logicalheight,
            owner=f"window:{int(win.get('id', 0))}:layer:{layerid}"[:128],
        )
        resource = {
            "handle": int(handle),
            "width": logicalwidth,
            "height": logicalheight,
            "signature": None,
        }
        layers[layerid] = resource

    dirty = resource.get("signature") != signature

    if dirty:

        targetstate = gputargetbegin(resource["handle"], clearcolor=(0, 0, 0, 0), clear=True)

        try:

            layeropacity = max(0.000001, float(state.get("opacity", 1.0)))
            gpudrawwindowcommands(
                win,
                0,
                0,
                logicalwidth,
                logicalheight,
                1.0,
                damageclip=None,
                layerid=layerid,
                opacitydivisor=layeropacity,
                context=context,
            )

        except Exception:

            gputargetend(targetstate)
            layers.pop(layerid, None)
            gputargetdestroy(resource["handle"])
            raise

        else:
            gputargetend(targetstate)
            resource["signature"] = signature
            win["_telemetry_layer_texture_renders"] = int(win.get("_telemetry_layer_texture_renders", 0)) + 1

    else:

        win["_telemetry_layer_texture_hits"] = int(win.get("_telemetry_layer_texture_hits", 0)) + 1

    layeropacity = max(0.0, min(1.0, float(state.get("opacity", 1.0))))

    if layeropacity <= 0.0:
        return 0

    return 1 if gpudrawtexture(
        resource["handle"],
        x,
        y,
        width,
        height,
        opacity=float(opacity) * layeropacity,
        clip=clip,
        flip_y=True,
        effect=state.get("effect", "none"),
    ) else 0


def gpudrawwindow(win, clip=None):

    global RETAINEDSYSTEMFRAMELOGGED

    managedonly = bool(win.get("_managed_only", False))
    retainedsystem = bool(gpuwindowretainedsystem(win))
    dynamicvideo = bool(managedonly and gpuwindowdynamicvideo(win))
    presentationstream = str(win.get("_presentation_stream") or "")
    presentationsurface = (
        win.get("_video_streams", {}).get(presentationstream)
        if presentationstream
        else None
    )
    if (
        not isinstance(presentationsurface, dict)
        or (
            int(presentationsurface.get("handle", 0)) < 1
            and not bool(presentationsurface.get("retained_ready", False))
        )
        or (
            not bool(presentationsurface.get("ready", False))
            and not bool(presentationsurface.get("retained_ready", False))
        )
    ):
        presentationsurface = None
    handle = None if managedonly or presentationsurface is not None else gpuwindowtexture(win)

    if handle is None and not managedonly and presentationsurface is None:
        return False

    opacity, scale, offsetx, offsety = gpuwindoweffect(win)
    originalx = float(win.get("x", 0))
    originaly = float(win.get("y", 0))
    originalwidth = float(win.get("w", 0))
    originalheight = float(win.get("h", 0))
    width = originalwidth * scale
    height = originalheight * scale
    x = originalx - (width - originalwidth) * 0.5 + offsetx
    y = originaly - (height - originalheight) * 0.5 + offsety
    role = str(win.get("role", ""))
    beforedraws = int(gpuframestats().get("draw_calls", 0))
    scenehandle = (
        gpuwindowscenetexture(win)
        if managedonly and not dynamicvideo
        else None
    )

    if retainedsystem:

        if not RETAINEDSYSTEMFRAMELOGGED:
            graphicslog(
                f"> graphics retained system scene ready "
                f"role={str(win.get('role', 'unknown'))}"
            )
            RETAINEDSYSTEMFRAMELOGGED = True

    if role == "window" and not isfullscreen(win) and GPUSHADOWS and bool(win.get("shadow", True)):

        ratio = width / max(1.0, originalwidth)
        insetleft, insettop, insetright, insetbottom = windowframeinsets(win)
        frameleft = max(0.0, insetleft * ratio)
        frametop = max(0.0, insettop * ratio)
        frameright = max(0.0, insetright * ratio)
        framebottom = max(0.0, insetbottom * ratio)
        shadowopacity = float(GPUSHADOWOPACITY)

        if int(win.get("id", 0)) == FOCUSWID:
            shadowopacity = min(1.0, shadowopacity * 1.25)

        gpudrawshadow(
            x - frameleft,
            y - frametop,
            width + frameleft + frameright,
            height + frametop + framebottom,
            radius=GPUSHADOWRADIUS,
            opacity=shadowopacity * opacity,
            clip=clip,
        )

    blur = max(0.0, min(32.0, float(win.get("blur", 0.0))))

    if GPUBLUR and blur > 0.0:
        gpudrawblur(x, y, width, height, radius=blur or GPUBLURRADIUS, opacity=opacity, clip=clip)

    if presentationsurface is not None:
        newpresentation = bool(presentationsurface.get("ready", False))
        retained = retainpresentationframe(presentationsurface)
        retainedhandle = int(presentationsurface.get("retained_handle", 0) or 0)
        drawn = bool(
            retained
            and retainedhandle > 0
            and gpudrawtexture(
                retainedhandle,
                x,
                y,
                width,
                height,
                opacity=opacity,
                clip=clip,
                flip_y=True,
            )
        )

        if drawn:
            VIDEOTELEMETRY["direct_composition_draws"] += 1

            if newpresentation and not bool(presentationsurface.get("presented", False)):
                # Capture ownership now, but report presentation and return
                # the DMA-BUF only after the DRM event for this gpuend(). This
                # makes Chromium's feedback use the physical display clock and
                # moves the protocol-v1 consumer finish out of composition.
                if not capturechromiumpresentation(
                    win,
                    presentationstream,
                    presentationsurface,
                ):
                    videoevent(
                        presentationsurface.get("connection", 0),
                        {
                            "op": "dropped",
                            "generation": int(
                                presentationsurface.get("generation", 0)
                            ),
                            "frame": int(presentationsurface.get("frame", 0)),
                            "reason": "presentation-receipt-capture-failed",
                        },
                    )
                    VIDEOTELEMETRY["drops"] += 1
                    releasepresentationframe(presentationsurface)
                    videopromotepending(
                        win,
                        presentationstream,
                        presentationsurface,
                    )

        elif newpresentation:
            videoevent(
                presentationsurface.get("connection", 0),
                {
                    "op": "dropped",
                    "generation": int(presentationsurface.get("generation", 0)),
                    "frame": int(presentationsurface.get("frame", 0)),
                    "reason": "presentation-retain-failed",
                },
            )
            releasepresentationframe(presentationsurface)
            videopromotepending(win, presentationstream, presentationsurface)

    elif scenehandle is not None:
        gpudrawtexture(scenehandle, x, y, width, height, opacity=opacity, clip=clip, flip_y=True)

    elif handle is not None:
        gpudrawtexture(handle, x, y, width, height, opacity=opacity, clip=clip)

    if scenehandle is None and presentationsurface is None:
        if dynamicvideo:
            VIDEOTELEMETRY["direct_composition_draws"] += 1
        statistics = {"considered": 0, "culled": 0, "drawn": 0}
        gpudrawwindowcommands(win, x, y, width, height, opacity, damageclip=clip, statistics=statistics)
        win["_telemetry_scene_commands_considered"] = int(win.get("_telemetry_scene_commands_considered", 0)) + int(statistics["considered"])
        win["_telemetry_scene_commands_culled"] = int(win.get("_telemetry_scene_commands_culled", 0)) + int(statistics["culled"])
        win["_telemetry_scene_commands_drawn"] = int(win.get("_telemetry_scene_commands_drawn", 0)) + int(statistics["drawn"])

    gpuframegeometry(win, x, y, width, height, opacity, clip=clip)
    afterdraws = int(gpuframestats().get("draw_calls", 0))
    win["_telemetry_gpu_draw_calls"] = int(win.get("_telemetry_gpu_draw_calls", 0)) + max(0, afterdraws - beforedraws)
    return True


def gpueffectiverects():

    result = []

    for source in (OVERLAYRECTS, getactiveoverlays()):

        for rect in source:

            try:
                x, y, width, height = [int(value) for value in rect[:4]]
            except Exception:
                continue

            if width > 0 and height > 0:
                result.append([x, y, width, height])

    return result


def gpuoverlaydesktop(desktopwid, rects, clip=None):

    if desktopwid is None or desktopwid not in windows:
        return

    desktop = windows[desktopwid]
    handle = gpuwindowtexture(desktop)

    if handle is None:
        return

    dx = int(desktop.get("x", 0))
    dy = int(desktop.get("y", 0))
    dw = int(desktop.get("w", 0))
    dh = int(desktop.get("h", 0))

    for x, y, width, height in rects:

        ix, iy, iw, ih = rectintersect(x, y, width, height, dx, dy, dw, dh)

        if clip is not None:
            ix, iy, iw, ih = rectintersect(ix, iy, iw, ih, *[int(value) for value in clip])

        if iw < 1 or ih < 1:
            continue

        gpudrawtexture(
            handle,
            ix,
            iy,
            iw,
            ih,
            src=(ix - dx, iy - dy, iw, ih),
            clip=(ix, iy, iw, ih),
        )


def gpuwindowstable(win):

    if abs(float(win.get("scale", 1.0)) - 1.0) > 0.0001:
        return False

    if GPUANIMATIONS.get(int(win.get("id", 0))):
        return False

    start = win.get("_gpu_transition_start")

    if start is not None:

        duration = max(0, int(win.get("_gpu_transition_ms", GPUTRANSITIONMS))) / 1000.0

        if duration > 0.0 and time.monotonic() - float(start) < duration:
            return False

    return True


def gpuwindowopaque(win):

    return (
        bool(win.get("mapped"))
        and gpuwindowstable(win)
        and float(win.get("opacity", 1.0)) >= 0.9999
        and not bool(win.get("pixel_alpha", False))
    )


def gpuvisualrect(win):

    role = str(win.get("role", ""))
    originalx = float(win.get("x", 0))
    originaly = float(win.get("y", 0))
    originalwidth = max(1.0, float(win.get("w", 0)))
    originalheight = max(1.0, float(win.get("h", 0)))
    scale = max(0.25, min(4.0, float(win.get("scale", 1.0))))
    clientwidth = originalwidth * scale
    clientheight = originalheight * scale
    clientx = originalx - (clientwidth - originalwidth) * 0.5
    clienty = originaly - (clientheight - originalheight) * 0.5

    if role == "window":

        insetleft, insettop, insetright, insetbottom = windowframeinsets(win)
        left = float(insetleft) * scale
        top = float(insettop) * scale
        right = float(insetright) * scale
        bottom = float(insetbottom) * scale
        x = int(clientx - left)
        y = int(clienty - top)
        width = int(clientwidth + left + right + 0.9999)
        height = int(clientheight + top + bottom + 0.9999)

    else:
        x = int(clientx)
        y = int(clienty)
        width = int(clientwidth + 0.9999)
        height = int(clientheight + 0.9999)

    if role == "window" and not isfullscreen(win) and GPUSHADOWS and bool(win.get("shadow", True)):

        radius = max(1, int(GPUSHADOWRADIUS))
        x -= radius
        y -= radius
        width += radius * 2
        height += radius * 2

    if win.get("_gpu_transition_start") is not None and str(win.get("transition_style", "")) == "slide":
        slide = max(1, int(scalesize(20)))
        height += slide

    return [x, y, width, height]


def gpuoccludedwindows():

    if not GPUOCCLUSION:
        return set()

    culled = set()
    ordered = [wid for wid in zorder if wid in windows and windows[wid].get("mapped")]

    for index, wid in enumerate(ordered):

        win = windows[wid]

        if str(win.get("role", "")) != "window" or not gpuwindowstable(win):
            continue

        tx, ty, tw, th = gpuvisualrect(win)

        if tw < 1 or th < 1:
            continue

        for upperwid in ordered[index + 1:]:

            upper = windows[upperwid]

            if not gpuwindowopaque(upper):
                continue

            ux = int(upper.get("x", 0))
            uy = int(upper.get("y", 0))
            uw = int(upper.get("w", 0))
            uh = int(upper.get("h", 0))

            if ux <= tx and uy <= ty and ux + uw >= tx + tw and uy + uh >= ty + th:
                culled.add(wid)
                break

    return culled


def _rectsubtract(rect, cover):

    x, y, width, height = [int(value) for value in rect]
    cx, cy, cwidth, cheight = [int(value) for value in cover]
    ix, iy, iwidth, iheight = rectintersect(x, y, width, height, cx, cy, cwidth, cheight)

    if iwidth < 1 or iheight < 1:
        return [[x, y, width, height]]

    output = []
    right = x + width
    bottom = y + height
    iright = ix + iwidth
    ibottom = iy + iheight

    if iy > y:
        output.append([x, y, width, iy - y])

    if ibottom < bottom:
        output.append([x, ibottom, width, bottom - ibottom])

    if ix > x:
        output.append([x, iy, ix - x, iheight])

    if iright < right:
        output.append([iright, iy, right - iright, iheight])

    return [value for value in output if value[2] > 0 and value[3] > 0]


def gpuopaquerect(win):

    rect = gpuvisualrect(win)

    if str(win.get("role", "")) == "window" and not isfullscreen(win) and GPUSHADOWS and bool(win.get("shadow", True)):

        radius = max(1, int(GPUSHADOWRADIUS))
        rect = [rect[0] + radius, rect[1] + radius, rect[2] - radius * 2, rect[3] - radius * 2]

    return rect


def gpuvisibleclips(wid, region, limit=32):

    if not GPUOCCLUSION or wid not in zorder or wid not in windows:
        intersection = rectintersect(*gpuvisualrect(windows[wid]), *region)
        return [list(intersection)] if intersection[2] > 0 and intersection[3] > 0 else []

    intersection = rectintersect(*gpuvisualrect(windows[wid]), *region)

    if intersection[2] < 1 or intersection[3] < 1:
        return []

    visible = [list(intersection)]
    index = zorder.index(wid)

    for upperwid in zorder[index + 1:]:

        upper = windows.get(upperwid)

        if upper is None or not gpuwindowopaque(upper):
            continue

        cover = gpuopaquerect(upper)
        nextvisible = []

        for value in visible:
            nextvisible.extend(_rectsubtract(value, cover))

        if len(nextvisible) > int(limit):
            return [list(intersection)]

        visible = nextvisible

        if not visible:
            break

    if len(visible) > 1:

        originalpixels = max(1, int(intersection[2]) * int(intersection[3]))
        visiblepixels = sum(int(value[2]) * int(value[3]) for value in visible)
        savedfraction = 1.0 - (visiblepixels / float(originalpixels))

        # Scissoring a fragmented region repeats every draw in the window.
        # Keep the original clip unless fragment work buys a substantial fill
        # reduction with a small number of pieces.
        if len(visible) > 4 or savedfraction < 0.5:
            return [list(intersection)]

    return visible


def gpuworkloadrecord(kind, milliseconds):

    history = GPUWORKLOADS.setdefault(str(kind), [])
    history.append(max(0.0, float(milliseconds)))

    if len(history) > 240:
        del history[0:len(history) - 240]


def gpuworkloadmetrics():

    output = {}

    for kind, values in GPUWORKLOADS.items():

        ordered = sorted(float(value) for value in values)

        if not ordered:

            output[kind] = {"samples": 0, "average_ms": 0.0, "percentile_95_ms": 0.0, "maximum_ms": 0.0}
            continue

        percentile = max(0, min(len(ordered) - 1, ((len(ordered) * 95 + 99) // 100) - 1))
        output[kind] = {
            "samples": len(ordered),
            "average_ms": round(sum(ordered) / len(ordered), 3),
            "percentile_95_ms": round(ordered[percentile], 3),
            "maximum_ms": round(ordered[-1], 3),
        }

    return output


def gpupaintregions(clipped):

    global STARTUPCURSORWAIT, GPUOCCLUSIONCULLED, GPUOCCLUSIONLAST, GPUFULLFRAMEFALLBACKS, GPUFRAMESEQUENCE
    global GPUFIRSTFRAMESTARTED, GPUFIRSTFRAMECOMPLETED

    requested = [list(region) for region in clipped]
    requestedfull = len(requested) == 1 and requested[0] == [0, 0, int(SCREENW), int(SCREENH)]
    workload = "animation" if gpuanimationsactive() else ("full" if requestedfull else "partial")
    workloadstarted = time.monotonic_ns()

    firstframe = not GPUFIRSTFRAMESTARTED

    # This must precede gpubeginregions(): keep glyph texture uploads out of the
    # GBM scan-out render pass.
    gpuprewarmretainedsystemtexts()

    if firstframe:
        mappedroles = [
            str(windows[wid].get("role", "unknown"))
            for wid in zorder
            if wid in windows and windows[wid].get("mapped")
        ]
        graphicslog(
            f"> graphics first GPU frame begin "
            f"mapped_roles={mappedroles} requested={requested}"
        )
        GPUFIRSTFRAMESTARTED = True

    regions = gpubeginregions(requested, (0, 0, 0, 255))

    if not regions:
        return False

    commitreceipts = []
    receiptsstaged = False
    presentationsstaged = False

    try:

        GPUFRAMESEQUENCE += 1

        desktopwid = None

        for wid in zorder:

            if wid in windows and windows[wid].get("mapped") and windows[wid].get("role") == "desktop":
                desktopwid = wid
                break

        culled = gpuoccludedwindows()
        GPUOCCLUSIONLAST = len(culled)
        GPUOCCLUSIONCULLED += len(culled)
        gpupreparewindowscenes(regions, culled=culled)
        overlays = gpueffectiverects()
        seen = set()
        renderedgenerations = {}
        framestate = gpuframestats()

        if not requestedfull and bool(framestate.get("full", False)):
            GPUFULLFRAMEFALLBACKS += 1

        show = bool(CURSORENABLED) and CURSORMODE != "hidden"

        if STARTUPCURSORWAIT:

            if cursorstartupsceneactive():
                STARTUPCURSORWAIT = False
            else:
                show = False

        if BOOTCURSORHIDE and bootactive():
            show = False

        cursorrect = pointercursorbox(POINTERX, POINTERY, CURSORMODE) if show else None

        for region in regions:

            gpusetregion(region)

            for wid in zorder:

                if wid not in windows or not windows[wid].get("mapped"):
                    continue

                if windows[wid].get("role") == "tooltip":
                    continue

                if wid in culled:
                    continue

                visibleclips = gpuvisibleclips(wid, region)

                if not visibleclips:
                    continue

                for visibleclip in visibleclips:
                    gpudrawwindow(windows[wid], clip=visibleclip)

                visiblepixels = sum(int(value[2]) * int(value[3]) for value in visibleclips)
                windows[wid]["_telemetry_composited_pixels"] = int(windows[wid].get("_telemetry_composited_pixels", 0)) + visiblepixels
                seen.add(wid)
                renderedgenerations[int(wid)] = int(
                    windows[wid].get("_gpu_command_generation", 0)
                )

            gpuoverlaydesktop(desktopwid, overlays, clip=region)

            for wid in zorder:

                if wid not in windows or not windows[wid].get("mapped"):
                    continue

                if windows[wid].get("role") != "tooltip":
                    continue

                visual = gpuvisualrect(windows[wid])
                intersection = rectintersect(*visual, *region)

                if intersection[2] < 1 or intersection[3] < 1:
                    continue

                gpudrawwindow(windows[wid], clip=region)
                windows[wid]["_telemetry_composited_pixels"] = int(windows[wid].get("_telemetry_composited_pixels", 0)) + int(intersection[2]) * int(intersection[3])
                seen.add(wid)
                renderedgenerations[int(wid)] = int(
                    windows[wid].get("_gpu_command_generation", 0)
                )

            gpuoverlaydesktop(desktopwid, overlays, clip=region)

            if SNAPPREVIEW:

                x, y, width, height = [int(value) for value in SNAPPREVIEW]
                gpudrawrect(x, y, width, 1, (255, 255, 255, 255), clip=region)
                gpudrawrect(x, y + height - 1, width, 1, (255, 255, 255, 255), clip=region)
                gpudrawrect(x, y, 1, height, (255, 255, 255, 255), clip=region)
                gpudrawrect(x + width - 1, y, 1, height, (255, 255, 255, 255), clip=region)

            if cursorrect:

                cursorintersection = rectintersect(*cursorrect, *region)

                if cursorintersection[2] > 0 and cursorintersection[3] > 0:

                    gpudrawcursor(
                        int(cursorrect[0]), int(cursorrect[1]),
                        CURSORMODE, clip=region,
                    )

        retainedsystemseen = any(
            wid in windows and gpuwindowretainedsystem(windows[wid])
            for wid in seen
        )
        # Remove the exact receipts represented by this render before gpuend()
        # can service more client I/O while waiting for an earlier flip. New
        # requests then remain queued for the next frame instead of being
        # accidentally attached to this already-rendered one.
        commitreceipts = graphicsframecommitreceipts(renderedgenerations)

        # A complete retained system texture was already resolved directly to
        # the GBM target. Avoid a redundant full-screen preservation copy for
        # that full frame. A later partial request may rebuild and preserve the
        # compositor cache once, after which ordinary partial composition
        # continues normally.
        gpuend(
            waitpulse=graphicspresentationpulse,
            preserve=not (retainedsystemseen and requestedfull),
        )
        graphicsstagecommitreceipts(commitreceipts)
        receiptsstaged = True
        stagechromiumpresentations()
        presentationsstaged = True

        if firstframe and not GPUFIRSTFRAMECOMPLETED:
            graphicslog(
                f"> graphics first GPU frame complete "
                f"retained_system={bool(retainedsystemseen)}"
            )
            GPUFIRSTFRAMECOMPLETED = True

        # Boot is not allowed to treat a client-side render as proof that the
        # accelerated desktop is visible. For the first mapped lock screen,
        # wait for its KMS page flip and synchronize Mesa so asynchronous
        # NVK/Zink device loss is observed here.
        writeacceleratedbootready(seen)
        writeacceleratedlockscreenready(seen)

        # The first modeset and the startup readiness barriers can complete
        # synchronously rather than through WindowServer's selector callback.
        # Release their managed scene only after that confirmed presentation.
        if not kmspresentationpending():
            graphicsfinishcommitreceipts()
            finishchromiumpresentations()

        gpuworkloadrecord(workload, (time.monotonic_ns() - workloadstarted) / 1000000.0)

        for wid in seen:

            if wid in windows:
                windows[wid]["_telemetry_gpu_frames"] = int(windows[wid].get("_telemetry_gpu_frames", 0)) + 1

        return True

    except Exception:

        if commitreceipts and not receiptsstaged:
            graphicsrestorecommitreceipts(commitreceipts)

        if not presentationsstaged:
            cancelcapturedchromiumpresentations(
                "composition-aborted-before-page-flip"
            )

        gpuabort()
        raise


def gpustartupworkloadgate():

    texture = None
    target = None
    targetstate = None
    frameactive = False
    width, height = getscreensize()
    width = max(1, int(width))
    height = max(1, int(height))
    renderer = str(backendinfo().get("renderer") or "")
    targetwidth = width
    targetheight = height

    # The full native-size retained target is specifically required to
    # reproduce the physical NVK failure. Other drivers already have their
    # own full-size system-scene presentation after startup; cap this extra
    # preflight allocation so a 512 MiB VM is not destabilized by diagnostics.
    if "nvk" not in renderer.casefold():
        targetscale = min(1.0, 1280.0 / width, 720.0 / height)
        targetwidth = max(1, int(round(width * targetscale)))
        targetheight = max(1, int(round(height * targetscale)))

    bootscale = min(width / 1920.0, height / 1080.0)
    bootsize = max(8, min(256, int(round(48.0 * bootscale))))
    glyphs = 0

    graphicslog(
        f"> graphics startup representative GPU workload begin "
        f"display={width}x{height} target={targetwidth}x{targetheight} "
        f"boot_glyph={bootsize} renderer={renderer or 'unknown'}"
    )

    try:
        # Exercise the same transfer path used by a new glyph atlas while no
        # render target is active. OpenGL submission order carries these
        # uploads into the representative frame without an intermediate,
        # blocking glFinish.
        texture = gputexturecreate(
            2,
            2,
            fmt="RGBA32",
            data=bytes((
                255, 255, 255, 255,
                255, 255, 255, 0,
                255, 255, 255, 0,
                255, 255, 255, 255,
            )),
            owner="startup-health-gate",
            alpha=True,
        )

        if os.path.isfile(BOOTANIMATIONFONT):
            glyphs = int(gpuprewarmtext(
                ".The One",
                sizes=(bootsize,),
                fontpath=BOOTANIMATIONFONT,
            ))

        # Reproduce the physical NVK boot path before opening protocol sockets:
        # render a complete managed scene into an off-screen target, resolve it
        # to GBM with one texture draw, and complete multiple KMS presentations.
        # The second and third iterations are essential because the failed Ada
        # boot reported device loss on the submit following its hung first flip.
        graphicslog(
            f"> graphics startup retained target create begin "
            f"size={targetwidth}x{targetheight}"
        )
        target = gputargetcreate(
            targetwidth,
            targetheight,
            owner="startup-retained-system-gate",
        )
        graphicslog("> graphics startup retained target create complete")

        for dotcount in (1, 2, 3):
            graphicslog(
                f"> graphics startup retained GPU frame {dotcount}/3 "
                f"offscreen begin"
            )
            # Render targets are nested inside a managed GPU frame.  Beginning
            # the target first made gputargetbegin() reject every accelerated
            # WindowServer during its startup health gate, which sent boot into
            # the software-recovery loop before the lock screen could own input.
            regions = gpubeginregions(
                [[0, 0, int(width), int(height)]],
                (0, 0, 0, 255),
            )

            if not regions:
                raise RuntimeError("representative retained GPU frame could not begin")

            frameactive = True
            targetstate = gputargetbegin(
                target,
                clearcolor=(0, 0, 0, 255),
                clear=True,
            )
            gpudrawrect(
                0,
                0,
                min(8, targetwidth),
                min(8, targetheight),
                (0, 0, 0, 255),
            )
            gpudrawtexture(
                texture,
                max(0, targetwidth // 2 - 1),
                max(0, targetheight // 2 - 1),
                width=2,
                height=2,
            )

            if glyphs:
                gpudrawtext(
                    targetwidth // 2,
                    max(0, (targetheight - bootsize) // 2),
                    "." * dotcount,
                    (255, 255, 255, 255),
                    bootsize,
                    fontpath=BOOTANIMATIONFONT,
                )

            gputargetend(targetstate)
            targetstate = None
            graphicslog(
                f"> graphics startup retained GPU frame {dotcount}/3 "
                f"offscreen complete"
            )
            gpudrawtexture(
                target,
                0,
                0,
                width=width,
                height=height,
                flip_y=True,
            )

            graphicslog(
                f"> graphics startup retained GPU frame {dotcount}/3 "
                f"scanout submit begin"
            )
            # The third frame exercises the default-framebuffer preservation
            # path used when a full frame seeds subsequent partial damage.
            # This is the path that a strict NVIDIA GLES implementation
            # rejected when its RGB scan-out buffer was copied into RGBA
            # storage, so it must be part of the physical startup gate.
            preserveframe = dotcount == 3

            if not gpuend(
                present=True,
                waitpulse=graphicspresentationpulse,
                preserve=preserveframe,
            ):
                raise RuntimeError("representative retained GPU frame could not complete")

            frameactive = False
            graphicslog(
                f"> graphics startup retained GPU frame {dotcount}/3 "
                f"scanout submit complete preserve_copy={preserveframe}"
            )

            if not kmswaitflip(waitpulse=graphicspresentationpulse):
                raise RuntimeError("representative retained GPU frame page flip did not complete")

            graphicslog(
                f"> graphics startup retained GPU frame {dotcount}/3 "
                f"page flip complete"
            )
            gpuhealthcheck(
                synchronize=True,
                operation=f"WindowServer startup retained GPU presentation {dotcount}/3",
            )
            graphicslog(
                f"> graphics startup retained GPU frame {dotcount}/3 "
                f"synchronization complete"
            )

        graphicslog(
            f"> graphics startup representative GPU workload complete "
            f"glyphs={int(glyphs)} frames=3 retained_system=True"
        )
        return True

    finally:

        if targetstate is not None:
            gputargetend(targetstate)

        if frameactive:
            gpuabort()

        if target is not None:
            gputargetdestroy(target)

        if texture is not None:
            gputexturedestroy(texture)


def gpupresentationgate(timeout):

    global GPUPRESENTATIONGATEWAITS, GPUPRESENTATIONGATERELEASES
    global GPUPRESENTATIONGATEWAITMS, GPUPRESENTATIONGATEMAXMS

    if not GPUCOMPOSITOR or GRAPHICSPRESENTFD is None:
        return True

    if not kmspresentationpending():
        return True

    if kmspresentationstalled():
        raise GPUCompositorError(
            "DRM page flip did not complete inside the presentation watchdog"
        )

    started = time.monotonic_ns()
    GPUPRESENTATIONGATEWAITS += 1

    # Keep servicing the shared selector while scan-out owns the previous
    # buffer. Input and client damage continue to accumulate, but no new frame
    # is rendered until the DRM completion event establishes the next vblank
    # boundary. This removes the independent timer/page-flip race on physical
    # displays without turning the steady path into a blocking poll.
    serveio(timeout=max(0.001, min(0.1, float(timeout))))

    elapsed = max(
        0.0,
        (time.monotonic_ns() - started) / 1000000.0,
    )
    GPUPRESENTATIONGATEWAITMS += elapsed
    GPUPRESENTATIONGATEMAXMS = max(
        float(GPUPRESENTATIONGATEMAXMS),
        elapsed,
    )

    if kmspresentationpending():
        return False

    GPUPRESENTATIONGATERELEASES += 1
    return True


def composeloop(cfg):

    global LASTFBPOLL, LASTGRAPHICSSTATE, LASTDISPLAYADJUSTMENT, SCREENW, SCREENH, CURSORDIRTY, POINTERX, POINTERY

    try:

        interval = max(
            1.0,
            float(cfg.get("frame_interval_ms", 16.667)),
        ) / 1000.0

        while SERVERRUN:

            loopstarted = time.monotonic()
            now = time.time()

            pickerpulse()
            drainio(cycles=4)
            savewindowpointerpos()

            if now - LASTGRAPHICSSTATE >= 1.0:

                LASTGRAPHICSSTATE = now
                # Presentation and input always outrank telemetry snapshot
                # construction, even though durable persistence is delegated.
                drainio(cycles=8)
                writegraphicsstate()

            if now - LASTDISPLAYADJUSTMENT >= 1.0:

                LASTDISPLAYADJUSTMENT = now

                if refreshdisplayadjustment():
                    gpuinvalidatesurface()
                    DAMAGERECTS.append([0, 0, int(SCREENW), int(SCREENH)])

            if (now - LASTFBPOLL) >= 0.25:

                LASTFBPOLL = now

                changed = False

                try:

                    changed = refreshfb(
                        waitpulse=graphicspresentationpulse
                    )

                except (GPUDeviceLostError, GPUCompositorError):
                    raise
                except Exception as error:
                    raise GPUCompositorError(
                        f"DRM display refresh failed: {error}"
                    ) from error

                if changed:

                    gpuinvalidatesurface()

                    if GPUCOMPOSITOR:

                        refreshed = float(
                            backendinfo().get("refresh_hz") or 0.0
                        )

                        if 10.0 <= refreshed <= 1000.0:
                            interval = 1.0 / refreshed
                            cfg["frame_interval_ms"] = interval * 1000.0
                            gpusetframebudget(
                                cfg["frame_interval_ms"]
                            )

                    previouswork = (int(WORKX), int(WORKY), int(WORKW), int(WORKH))

                    try:

                        SCREENW, SCREENH = getscreensize()

                    except Exception:

                        pass

                    CURSORSIZES.clear()

                    loadcursor()

                    applyuiscale()

                    # clamp pointer and repaint everything
                    if POINTERX < 0: POINTERX = 0

                    if POINTERY < 0: POINTERY = 0

                    if POINTERX >= SCREENW: POINTERX = SCREENW - 1

                    if POINTERY >= SCREENH: POINTERY = SCREENH - 1

                    writefbsize(SCREENW, SCREENH)

                    setworkarea(cfg)

                    refreshwindows(previouswork)

                    broadcastworkarea()

                    DAMAGERECTS.append([0, 0, int(SCREENW), int(SCREENH)])

                    CURSORDIRTY = True

                    broadcastfbsize()

            # prune expired overlays regularly
            pruneoverlays()
            videoreleasepulse()

            drainio(cycles=8)
            flushclientmotions()

            pulsefocus()

            dialogpulse()

            savewindowattributes()

            # flush coalesced resize notifications once stable
            nowt = time.time()

            for wid, win in windows.items():

                if not win.get("_resize_pending", False):
                    continue

                pat = float(win.get("_resize_pat", 0.0))

                if (nowt - pat) < 0.08:
                    continue

                win["_resize_pending"] = False

                fulldamage(win)

                try:
                    sendjson(win["cid"], {
                        "op": "RESIZED",
                        "winid": int(wid),
                        "w": int(win.get("_resize_pw", win["w"])),
                        "h": int(win.get("_resize_ph", win["h"]))
                    })
                except Exception:
                    pass

            animating = gpuanimationsactive()

            # A physical page flip is the compositor's frame clock. An early
            # timer or unrelated input wake may service state, but it must not
            # start rendering the next frame while scan-out still owns the
            # preceding one.
            if not gpupresentationgate(interval):
                continue

            # Selector activity inside the presentation gate can map, unmap,
            # or stop an animation, so derive the requested frame again.
            animating = gpuanimationsactive()

            if animating:

                for wid, win in windows.items():

                    if win.get("mapped") and (win.get("_gpu_transition_start") is not None or GPUANIMATIONS.get(int(wid)) or gpuwindow3danimated(win)):
                        DAMAGERECTS.append(gpuvisualrect(win))

            if DAMAGERECTS or CURSORDIRTY or animating:

                drainio(cycles=4)

                paintregions()

                drainio(cycles=4)
                flushclientmotions()

            elapsed = time.monotonic() - loopstarted
            remaining = interval - elapsed

            if remaining > 0.0:
                # Wait on Window Server's selector instead of sleeping.  Input
                # Server activity now interrupts the frame wait, so keyboard
                # and pointer damage can be composed immediately while the
                # normal frame interval remains the idle/animation budget.
                serveio(timeout=remaining)

    except KeyboardInterrupt:
        return 0

    except GPUDeviceLostError as e:
        graphicslog(f"> graphics compose loop GPU device loss {e}")
        return GPUDEVICEFAILUREEXIT

    except GPUCompositorError as e:
        graphicslog(f"> graphics compose loop compositor failure {e}")
        return GPUCOMPOSITORFAILUREEXIT

    except Exception as e:
        graphicslog(f"> graphics compose loop error {type(e).__name__}: {e}")
        return GPUCOMPOSITORFAILUREEXIT

    return 0


def coalescerects(rects, maxrects):

    try:

        merged = []

        for r in rects:

            x = int(r[0]); y = int(r[1]); w = int(r[2]); h = int(r[3])
            if w <= 0 or h <= 0:
                continue

            placed = False

            for i in range(len(merged)):

                mx, my, mw, mh = merged[i]

                # overlap or touching adjacency
                if not (x > mx + mw or mx > x + w or y > my + mh or my > y + h):

                    nx = min(x, mx)
                    ny = min(y, my)
                    nx2 = max(x + w, mx + mw)
                    ny2 = max(y + h, my + mh)

                    merged[i] = [nx, ny, nx2 - nx, ny2 - ny]
                    placed = True
                    break

            if not placed:
                merged.append([x, y, w, h])

        # collapse to one big box if too many small rects
        if len(merged) > maxrects:

            xs = [x for x, y, w, h in merged]
            ys = [y for x, y, w, h in merged]
            xe = [x + w for x, y, w, h in merged]
            ye = [y + h for x, y, w, h in merged]

            return [[min(xs), min(ys), max(xe) - min(xs), max(ye) - min(ys)]]

        return merged

    except Exception:
        return rects


def pruneoverlays():


    nowm = time.monotonic()

    i = 0

    while i < len(OVERLAYACTIVE):

        try:
            x, y, w, h, exp = OVERLAYACTIVE[i]
        except Exception:
            # malformed entry
            del OVERLAYACTIVE[i]
            continue

        if exp <= nowm or w <= 0 or h <= 0:
            del OVERLAYACTIVE[i]
            continue

        i += 1

def getactiveoverlays():

    try:

        nowm = time.monotonic()

        out = []

        for r in OVERLAYACTIVE:

            x, y, w, h, exp = r
            if w > 0 and h > 0 and exp > nowm:
                out.append([x, y, w, h])

        return out

    except Exception:
        return []


def rectintersect(ax, ay, aw, ah, bx, by, bw, bh):

    try:

        ix = max(ax, bx)
        iy = max(ay, by)
        ix2 = min(ax + aw, bx + bw)
        iy2 = min(ay + ah, by + bh)

        if ix2 <= ix or iy2 <= iy:
            return (0, 0, 0, 0)

        return (ix, iy, ix2 - ix, iy2 - iy)

    except Exception:
        return (0, 0, 0, 0)


def winframerect(win):

    try:

        insetleft, insettop, insetright, insetbottom = windowframeinsets(win)
        fx = int(win["x"]) - insetleft
        fy = int(win["y"]) - insettop
        fw = int(win["w"]) + insetleft + insetright
        fh = int(win["h"]) + insettop + insetbottom

        return fx, fy, fw, fh

    except Exception:

        return int(win.get("x", 0)), int(win.get("y", 0)), int(win.get("w", 0)), int(win.get("h", 0))


def cpudrawdialogcommands(win, damageclip):

    """Draw a server-owned retained dialog scene in the CPU compositor."""

    if not win.get("standard_dialog"):
        return

    try:

        originx = int(win.get("x", 0))
        originy = int(win.get("y", 0))
        clientclip = [originx, originy, int(win.get("w", 0)), int(win.get("h", 0))]

        def clipped(first, second):

            return list(rectintersect(
                int(first[0]), int(first[1]), int(first[2]), int(first[3]),
                int(second[0]), int(second[1]), int(second[2]), int(second[3]),
            ))

        baseclip = clipped(clientclip, damageclip)

        if baseclip[2] < 1 or baseclip[3] < 1:
            return

        def commandclip(command):

            local = command.get("clip", [0, 0, clientclip[2], clientclip[3]])
            translated = [originx + int(local[0]), originy + int(local[1]), int(local[2]), int(local[3])]
            return clipped(baseclip, translated)

        def rgb(command):

            color = list(command.get("color", [255, 255, 255, 255]))
            return tuple(int(value) & 0xFF for value in color[:3])

        def colorint(command):

            red, green, blue = rgb(command)
            return (red << 16) | (green << 8) | blue

        def fill(rect, color, clip):

            translated = [originx + int(rect[0]), originy + int(rect[1]), int(rect[2]), int(rect[3])]
            visible = clipped(translated, clip)

            if visible[2] > 0 and visible[3] > 0:
                fillrectfast(*visible, color)

        for command in win.get("gpu_commands", [])[:GPUCOMMANDLIMIT]:

            kind = str(command.get("kind", ""))
            clip = commandclip(command)

            if clip[2] < 1 or clip[3] < 1:
                continue

            if kind == "rectangle":

                fill(command["rect"], rgb(command), clip)

            elif kind == "border":

                x, y, width, height = [int(value) for value in command["rect"]]
                borderwidth = max(1, int(round(float(command.get("width", 1.0)))))
                fill([x, y, width, borderwidth], rgb(command), clip)
                fill([x, y + height - borderwidth, width, borderwidth], rgb(command), clip)
                fill([x, y, borderwidth, height], rgb(command), clip)
                fill([x + width - borderwidth, y, borderwidth, height], rgb(command), clip)

            elif kind == "line":

                x0, y0, x1, y1 = [int(round(float(value))) for value in command["points"]]
                linewidth = max(1, int(round(float(command.get("width", 1.0)))))

                if y0 == y1:
                    fill([min(x0, x1), y0, abs(x1 - x0) + 1, linewidth], rgb(command), clip)
                elif x0 == x1:
                    fill([x0, min(y0, y1), linewidth, abs(y1 - y0) + 1], rgb(command), clip)

            elif kind == "text":

                drawtextttf(
                    originx + int(command["x"]),
                    originy + int(command["y"]),
                    str(command["text"]),
                    colorint(command),
                    int(command["size"]),
                    command.get("font") or WINDOWFONT,
                    clip=clip,
                )

    except Exception as error:

        if win.get("_cpu_dialog_render_error") != str(error):
            win["_cpu_dialog_render_error"] = str(error)
            log(f"standard dialog CPU render error wid={win.get('id')} {error}")


def blitwindowregion(win, clip):
    outputx = int(win.get("x", 0))
    outputy = int(win.get("y", 0))
    outputwidth = int(win.get("w", 0))
    outputheight = int(win.get("h", 0))
    if outputwidth < 1 or outputheight < 1:
        return False
    clipx, clipy, clipwidth, clipheight = [int(value) for value in clip]
    left = max(outputx, clipx)
    top = max(outputy, clipy)
    right = min(outputx + outputwidth, clipx + clipwidth)
    bottom = min(outputy + outputheight, clipy + clipheight)
    if right <= left or bottom <= top:
        return False
    sourcewidth, sourceheight = windowbufferdimensions(win)
    if (
        win.get("_external_buffer")
        and (sourcewidth != outputwidth or sourceheight != outputheight)
    ):
        return blitfilescaledfast(
            win["buffer"],
            sourcewidth,
            sourceheight,
            outputx,
            outputy,
            outputwidth,
            outputheight,
            win.get("format", "BGRA32"),
            clip=[left, top, right - left, bottom - top],
            stride=int(win.get("buffer_stride", sourcewidth * 4)),
            source_offset=int(win.get("buffer_offset", 0)),
        )
    blitfilepartfast(
        win["buffer"],
        sourcewidth,
        left - outputx,
        top - outputy,
        right - left,
        bottom - top,
        left,
        top,
        win.get("format", "BGRA32"),
        stride=int(win.get("buffer_stride", sourcewidth * 4)),
        source_offset=int(win.get("buffer_offset", 0)),
    )
    return True


def paintregions():

    global CURSORDIRTY, STARTUPCURSORWAIT, GPUCOMPOSITOR, GPUFAILED, STARTUPFRAMEWAITLOGGED
    global FRAMEBUFFERFRAMESEQUENCE

    if not DAMAGERECTS and not CURSORDIRTY:
        return

    # The startup cursor is deliberately hidden until the first OS scene is
    # mapped.  Pointer discovery and input events can still mark it dirty
    # before that point.  Do not turn that invisible cursor damage into an
    # empty compositor frame: on NVK the invalid retained surface promotes it
    # to a full default-framebuffer render followed by a framebuffer-to-texture
    # copy, which is the operation that loses the Ada GPU before the boot
    # animation can commit on a strict GLES implementation. Mapping the first
    # system scene supplies its own complete damage and starts presentation
    # through the retained system path.
    if STARTUPCURSORWAIT and not any(
        win.get("mapped")
        for win in windows.values()
    ):
        DAMAGERECTS.clear()
        CURSORDIRTY = False

        if not STARTUPFRAMEWAITLOGGED:
            graphicslog(
                "> graphics startup compositor waiting for first mapped scene"
            )
            STARTUPFRAMEWAITLOGGED = True

        return

    if not DAMAGERECTS and CURSORDIRTY:

        box = pointercursorbox(POINTERX, POINTERY, CURSORMODE)

        if box and len(box) == 4 and box[2] > 0 and box[3] > 0:

            DAMAGERECTS.append(box)

    rects = DAMAGERECTS[:]

    DAMAGERECTS.clear()

    clipped = []

    for r in rects:

        x = int(r[0])
        y = int(r[1])
        w = int(r[2])
        h = int(r[3])

        if w <= 0 or h <= 0:
            continue

        if x < 0:
            w += x
            x = 0

        if y < 0:
            h += y
            y = 0

        if x >= SCREENW or y >= SCREENH:
            continue

        if x + w > SCREENW:
            w = SCREENW - x

        if y + h > SCREENH:
            h = SCREENH - y

        if w > 0 and h > 0:
            clipped.append([x, y, w, h])

    try:

        maxrects = MAXRECTS

    except Exception:

        maxrects = 32

    clipped = coalescerects(clipped, maxrects)

    if not clipped:
        # A mapped window can be entirely outside the current output. Its
        # damage then clips to nothing, so no page flip exists on which to
        # attach a receipt. Resolve that accepted state explicitly instead of
        # leaving the client blocked until an unrelated visible repaint.
        if GPUCOMPOSITOR and GRAPHICSPRESENTFD is not None:

            for win in windows.values():
                graphicscancelcommitreceipts(
                    win,
                    "window damage was outside the display",
                    superseded=False,
                )

        CURSORDIRTY = False
        return

    if GPUCOMPOSITOR:

        try:

            if gpupaintregions(clipped):
                CURSORDIRTY = False
                OVERLAYRECTS.clear()
                return

        except GPUAccelerationUnavailableError as e:

            graphicslog(
                f"> graphics acceleration unavailable; process replacement "
                f"required reason={e}"
            )
            raise

        except GPUDeviceLostError as e:

            GPUFAILED = True
            gpufallback()
            graphicslog(
                f"> graphics GPU device lost; driver recovery required "
                f"reason={e}"
            )
            raise

        except Exception as e:

            GPUFAILED = True
            gpufallback()
            reason = str(e)
            graphicslog(
                f"> graphics compositor API failed; process replacement required "
                f"reason={reason}"
            )
            raise GPUCompositorError(
                f"GPU compositor failed; fresh WindowServer required: {reason}"
            ) from e

    start = time.monotonic()
    beginscaledfileframe()

    budget = 0.006

    # cache desktop window for overlay blits
    try:

        desktopwid = None

        for dwid in zorder:

            if windows[dwid].get("role") == "desktop" and windows[dwid].get("mapped"):

                desktopwid = dwid

                break

    except Exception:

        desktopwid = None

    seen = set()

    for x, y, w, h in clipped:

        fillrectfast(x, y, w, h, (0, 0, 0))

        for wid in zorder:

            if not windows[wid]["mapped"]:
                continue

            try:

                if windows[wid].get("role") == "tooltip":

                    continue

            except Exception:

                pass

            wx = int(windows[wid]["x"])

            wy = int(windows[wid]["y"])

            ww = int(windows[wid]["w"])

            wh = int(windows[wid]["h"])

            # intersect with client
            ix = max(x, wx)
            iy = max(y, wy)
            ix2 = min(x + w, wx + ww)
            iy2 = min(y + h, wy + wh)
            iw = ix2 - ix
            ih = iy2 - iy

            # intersect with frame
            fx, fy, fw, fh = winframerect(windows[wid])
            fix = max(x, fx)
            fiy = max(y, fy)
            fix2 = min(x + w, fx + fw)
            fiy2 = min(y + h, fy + fh)
            fiw = fix2 - fix
            fih = fiy2 - fiy

            # skip only if neither client nor frame intersects
            if (iw <= 0 or ih <= 0) and (fiw <= 0 or fih <= 0):
                continue

            # draw client (if intersecting)
            if iw > 0 and ih > 0:
                sx = ix - wx
                sy = iy - wy

                blitwindowregion(windows[wid], [ix, iy, iw, ih])
                seen.add(wid)

                cpudrawdialogcommands(windows[wid], [x, y, w, h])

            # draw frame (if intersecting)
            if fiw > 0 and fih > 0:
                paintframeclipped(windows[wid], x, y, w, h)

        if desktopwid is not None:

            # gather overlays: current-frame + active TTL ones
            eff = []
            try:
                if OVERLAYRECTS:
                    for r in OVERLAYRECTS:
                        try:
                            rx, ry, rw2, rh2 = int(r[0]), int(r[1]), int(r[2]), int(r[3])
                        except Exception:
                            continue
                        if rw2 > 0 and rh2 > 0:
                            eff.append([rx, ry, rw2, rh2])
            except Exception:
                pass

            try:
                active = getactiveoverlays()
                if active:
                    eff.extend(active)
            except Exception:
                pass

            for orx, ory, orw, orh in eff:

                # intersect overlay rect with current clip rect
                ox = max(x, orx)
                oy = max(y, ory)
                ox2 = min(x + w, orx + orw)
                oy2 = min(y + h, ory + orh)
                ow = ox2 - ox
                oh = oy2 - oy

                if ow <= 0 or oh <= 0:
                    continue

                # source on desktop buffer is the same screen-space coords relative to desktop at (0,0)
                blitfilepartfast(
                    windows[desktopwid]["buffer"],
                    int(windows[desktopwid]["w"]),
                    ox, oy,
                    ow, oh,
                    ox, oy,
                    windows[desktopwid].get("format", "BGRA32")
                )

        for wid in zorder:

            if not windows[wid]["mapped"]:
                continue

            try:
                if windows[wid].get("role") != "tooltip":
                    continue
            except Exception:
                continue

            wx = int(windows[wid]["x"])
            wy = int(windows[wid]["y"])
            ww = int(windows[wid]["w"])
            wh = int(windows[wid]["h"])

            # intersect with client
            ix = max(x, wx)
            iy = max(y, wy)
            ix2 = min(x + w, wx + ww)
            iy2 = min(y + h, wy + wh)
            iw = ix2 - ix
            ih = iy2 - iy

            # intersect with frame
            fx, fy, fw, fh = winframerect(windows[wid])
            fix = max(x, fx)
            fiy = max(y, fy)
            fix2 = min(x + w, fx + fw)
            fiy2 = min(y + h, fy + fh)
            fiw = fix2 - fix
            fih = fiy2 - fiy

            # skip only if neither client nor frame intersects
            if (iw <= 0 or ih <= 0) and (fiw <= 0 or fih <= 0):
                continue

            # draw client (if intersecting)
            if iw > 0 and ih > 0:
                sx = ix - wx
                sy = iy - wy

                blitwindowregion(windows[wid], [ix, iy, iw, ih])
                seen.add(wid)

            # draw frame (if intersecting)
            if fiw > 0 and fih > 0:
                paintframeclipped(windows[wid], x, y, w, h)

        if desktopwid is not None:

            # gather overlays: current-frame + active TTL ones
            eff = []
            try:
                if OVERLAYRECTS:
                    for r in OVERLAYRECTS:
                        try:
                            rx, ry, rw2, rh2 = int(r[0]), int(r[1]), int(r[2]), int(r[3])
                        except Exception:
                            continue
                        if rw2 > 0 and rh2 > 0:
                            eff.append([rx, ry, rw2, rh2])
            except Exception:
                pass

            try:
                active = getactiveoverlays()
                if active:
                    eff.extend(active)
            except Exception:
                pass

            for orx, ory, orw, orh in eff:

                # intersect overlay rect with current clip rect
                ox = max(x, orx)
                oy = max(y, ory)
                ox2 = min(x + w, orx + orw)
                oy2 = min(y + h, ory + orh)
                ow = ox2 - ox
                oh = oy2 - oy

                if ow <= 0 or oh <= 0:
                    continue

                # source on desktop buffer is the same screen-space coords relative to desktop at (0,0)
                blitfilepartfast(
                    windows[desktopwid]["buffer"],
                    int(windows[desktopwid]["w"]),
                    ox, oy,
                    ow, oh,
                    ox, oy,
                    windows[desktopwid].get("format", "BGRA32")
                )

        if time.monotonic() - start > budget:

            iopulse()

            start = time.monotonic()

    # Every scaled external surface was snapshotted at most once for this
    # complete CPU compositor frame, even when several damage clips intersect
    # it. This is the bounded fallback path used after GPU replacement.
    endscaledfileframe()

    if SNAPPREVIEW:
        x, y, w, h = SNAPPREVIEW

        drawrect(int(x), int(y), int(w), int(h), (255, 255, 255))

    # cursor visibility policy
    show = True

    try:

        if not CURSORENABLED or CURSORMODE == "hidden":
            show = False

        # hide cursor until startup window has appeared once
        if STARTUPCURSORWAIT:

            if cursorstartupsceneactive():

                STARTUPCURSORWAIT = False

            else:

                show = False

        # hide cursor when boot/splash surface is active
        if BOOTCURSORHIDE and bootactive():
            show = False

    except Exception:
        pass

    if show:

        cursorrect = pointercursorbox(POINTERX, POINTERY, CURSORMODE)
        drawcursor(int(cursorrect[0]), int(cursorrect[1]), CURSORMODE)

    try:
        if str(backendinfo().get("backend", "")) in ("framebuffer", "kms-framebuffer"):
            displayadjustregions(clipped)
    except Exception as error:
        graphicslog(f"> graphics display adjustment failed {error}")

    if not gpresent():
        raise GPUCompositorError(
            "framebuffer presentation did not commit the composed frame"
        )

    FRAMEBUFFERFRAMESEQUENCE += 1
    writeframebufferlockscreenready(seen)
    CURSORDIRTY = False

    # overlays handled, reset queue
    OVERLAYRECTS.clear()


def paintframe(win):


    if win.get("role") != "window" or isfullscreen(win):
        return

    gx, gy, gw, gh = windowgeo(win)
    clientchrome = clientchromemode(win)
    fx, fy, fw, fh = winframerect(win)
    colors = windowcontrolcolors(win)
    title_color = tuple(colors["title"])
    border_color = tuple(colors["border"])

    # Client-chrome windows already painted their own top surface; only overlay
    # the T1OS controls. Server-chrome windows retain the normal frame.
    if not clientchrome:
        fillrectfast(fx, fy, fw, fh, title_color)
        fillrectfast(fx + FRAMEW, fy + FRAMEW, fw - FRAMEW * 2, TITLEH, title_color)
        fillrectfast(fx, fy, fw, FRAMEW, border_color)
        fillrectfast(fx, fy + fh - FRAMEW, fw, FRAMEW, border_color)
        fillrectfast(fx, fy, FRAMEW, fh, border_color)
        fillrectfast(fx + fw - FRAMEW, fy, FRAMEW, fh, border_color)


    close_x, close_y, max_x, max_y, min_x, min_y = windowbuttonrects(win)

    close_color = tuple(colors["close"])
    max_color = tuple(colors["max"])
    min_color = tuple(colors["min"])

    # Chromium integrates its toolbar with the window controls, so preserve the
    # browser-painted surface beneath its blue glyphs.
    if clientchromecontrols(win) != "chromium":
        fillrectfast(close_x, close_y, BTNWH, BTNWH, title_color)
        fillrectfast(max_x, max_y, BTNWH, BTNWH, title_color)
        fillrectfast(min_x, min_y, BTNWH, BTNWH, title_color)

        hoverarea = windowbuttonhoverarea(win)
        hoverrect = windowbuttonhoverrects(win).get(hoverarea)

        if hoverrect is not None:
            hx, hy, hw, hh = hoverrect
            fillrectfast(hx, hy, hw, hh, WINDOWBUTTONHOVER)

    # close (pixel X)
    pad_close = scalesize(4)

    if pad_close < 1:
        pad_close = 1

    size_close = BTNWH - pad_close * 2

    for i in range(size_close):

        x0 = close_x + pad_close + i
        y0 = close_y + pad_close + i

        setpixel(x0, y0, close_color)

        x1 = close_x + pad_close + i
        y1 = close_y + BTNWH - pad_close - 1 - i

        setpixel(x1, y1, close_color)

    # maximise (single square when normal, double offset squares when maximised)
    pad_max = scalesize(4)

    if pad_max < 1:
        pad_max = 1

    inner_min_x = max_x + pad_max

    inner_min_y = max_y + pad_max

    inner_max_x = max_x + BTNWH - pad_max - 1

    inner_max_y = max_y + BTNWH - pad_max - 1

    mw_full = inner_max_x - inner_min_x + 1

    mh_full = inner_max_y - inner_min_y + 1

    if mw_full > 0 and mh_full > 0:

        if ismaximized(win):

            dx = scalesize(2)

            dy = scalesize(2)

            if dx < 1:
                dx = 1

            if dy < 1:
                dy = 1

            size = min(mw_full - dx, mh_full - dy)

            if size < 2:

                size = min(mw_full, mh_full)

                dx = 0

                dy = 0

            # back square (top-left)
            bx = inner_min_x
            by = inner_min_y

            for x in range(bx, bx + size):

                setpixel(x, by, max_color)

                setpixel(x, by + size - 1, max_color)

            for y in range(by, by + size):

                setpixel(bx, y, max_color)

                setpixel(bx + size - 1, y, max_color)

            # front square (bottom-right, offset by dx, dy)
            fx0 = inner_min_x + dx
            fy0 = inner_min_y + dy

            for x in range(fx0, fx0 + size):

                setpixel(x, fy0, max_color)

                setpixel(x, fy0 + size - 1, max_color)

            for y in range(fy0, fy0 + size):

                setpixel(fx0, y, max_color)

                setpixel(fx0 + size - 1, y, max_color)

        else:

            # normal single square maximise icon using full inner box
            mx = inner_min_x
            my = inner_min_y

            for x in range(mx, inner_max_x + 1):

                setpixel(x, my, max_color)

                setpixel(x, inner_max_y, max_color)

            for y in range(my, inner_max_y + 1):

                setpixel(mx, y, max_color)

                setpixel(inner_max_x, y, max_color)

    # minimise (pixel horizontal line)
    pad_min = scalesize(5)

    if pad_min < 1:
        pad_min = 1

    nx0 = min_x + pad_min

    nx1 = min_x + BTNWH - pad_min

    ny = min_y + BTNWH - pad_min

    if nx1 >= nx0:

        for x in range(nx0, nx1 + 1):

            setpixel(x, ny, min_color)


def paintframeclipped(win, rx, ry, rw, rh):

    if win.get("role") != "window" or isfullscreen(win):
        return

    gx = int(win.get("x", 0))

    gy = int(win.get("y", 0))

    gw = int(win.get("w", 1))

    gh = int(win.get("h", 1))
    clientchrome = clientchromemode(win)
    fx, fy, fw, fh = winframerect(win)
    colors = windowcontrolcolors(win)
    title_color = tuple(colors["title"])
    border_color = tuple(colors["border"])

    ix, iy, iw, ih = rectintersect(fx, fy, fw, fh, rx, ry, rw, rh)

    if iw <= 0 or ih <= 0:
        return

    cx, cy, cw, ch = ix, iy, iw, ih

    if not clientchrome:
        # titlebar
        ix2, iy2, iw2, ih2 = rectintersect(fx + FRAMEW, fy + FRAMEW, fw - FRAMEW * 2, TITLEH, cx, cy, cw, ch)

        if iw2 > 0 and ih2 > 0:
            fillrectfast(ix2, iy2, iw2, ih2, title_color)

        # border lines
        for bx, by, bw, bh in (
            (fx, fy, fw, FRAMEW),
            (fx, fy + fh - FRAMEW, fw, FRAMEW),
            (fx, fy, FRAMEW, fh),
            (fx + fw - FRAMEW, fy, FRAMEW, fh),
        ):
            ix2, iy2, iw2, ih2 = rectintersect(bx, by, bw, bh, cx, cy, cw, ch)

            if iw2 > 0 and ih2 > 0:
                fillrectfast(ix2, iy2, iw2, ih2, border_color)

    # buttons

    close_x, close_y, max_x, max_y, min_x, min_y = windowbuttonrects(win)

    close_color = tuple(colors["close"])
    max_color = tuple(colors["max"])
    min_color = tuple(colors["min"])

    # clip helper
    clip_x0 = cx
    clip_y0 = cy
    clip_x1 = cx + cw - 1
    clip_y1 = cy + ch - 1
    hoverarea = windowbuttonhoverarea(win)
    hoverrect = windowbuttonhoverrects(win).get(hoverarea)

    if hoverrect is not None:
        hx, hy, hw, hh = hoverrect
        ix2, iy2, iw2, ih2 = rectintersect(hx, hy, hw, hh, cx, cy, cw, ch)

        if iw2 > 0 and ih2 > 0:
            fillrectfast(ix2, iy2, iw2, ih2, WINDOWBUTTONHOVER)

    # close button region
    ix2, iy2, iw2, ih2 = rectintersect(close_x, close_y, BTNWH, BTNWH, cx, cy, cw, ch)

    if iw2 > 0 and ih2 > 0:

        if clientchromecontrols(win) != "chromium" and hoverarea != "close":
            fillrectfast(ix2, iy2, iw2, ih2, title_color)

        pad_close = 4

        size_close = BTNWH - pad_close * 2

        for i in range(size_close):

            x0 = close_x + pad_close + i
            y0 = close_y + pad_close + i

            if x0 >= clip_x0 and x0 <= clip_x1 and y0 >= clip_y0 and y0 <= clip_y1:

                setpixel(x0, y0, close_color)

            x1 = close_x + pad_close + i
            y1 = close_y + BTNWH - pad_close - 1 - i

            if x1 >= clip_x0 and x1 <= clip_x1 and y1 >= clip_y0 and y1 <= clip_y1:

                setpixel(x1, y1, close_color)

    # maximise button region
    ix2, iy2, iw2, ih2 = rectintersect(max_x, max_y, BTNWH, BTNWH, cx, cy, cw, ch)

    if iw2 > 0 and ih2 > 0:

        if clientchromecontrols(win) != "chromium" and hoverarea != "max":
            fillrectfast(ix2, iy2, iw2, ih2, title_color)

        pad_max = 4

        inner_min_x = max_x + pad_max
        inner_min_y = max_y + pad_max
        inner_max_x = max_x + BTNWH - pad_max - 1
        inner_max_y = max_y + BTNWH - pad_max - 1

        mw_full = inner_max_x - inner_min_x + 1
        mh_full = inner_max_y - inner_min_y + 1

        if mw_full > 0 and mh_full > 0:

            if ismaximized(win):

                dx = scalesize(2)

                dy = scalesize(2)

                if dx < 1:
                    dx = 1

                if dy < 1:
                    dy = 1

                size = min(mw_full - dx, mh_full - dy)

                if size < 2:

                    size = min(mw_full, mh_full)

                    dx = 0

                    dy = 0

                # back square (top-left)
                bx = inner_min_x

                by = inner_min_y

                for x in range(bx, bx + size):

                    if x < clip_x0 or x > clip_x1:
                        continue

                    y0 = by

                    y1 = by + size - 1

                    if y0 >= clip_y0 and y0 <= clip_y1:

                        setpixel(x, y0, max_color)

                    if y1 >= clip_y0 and y1 <= clip_y1:

                        setpixel(x, y1, max_color)

                for y in range(by, by + size):

                    if y < clip_y0 or y > clip_y1:
                        continue

                    x0 = bx

                    x1 = bx + size - 1

                    if x0 >= clip_x0 and x0 <= clip_x1:

                        setpixel(x0, y, max_color)

                    if x1 >= clip_x0 and x1 <= clip_x1:

                        setpixel(x1, y, max_color)

                # front square (bottom-right)
                fx0 = inner_min_x + dx

                fy0 = inner_min_y + dy

                for x in range(fx0, fx0 + size):

                    if x < clip_x0 or x > clip_x1:
                        continue

                    y0 = fy0

                    y1 = fy0 + size - 1

                    if y0 >= clip_y0 and y0 <= clip_y1:

                        setpixel(x, y0, max_color)

                    if y1 >= clip_y0 and y1 <= clip_y1:

                        setpixel(x, y1, max_color)

                for y in range(fy0, fy0 + size):

                    if y < clip_y0 or y > clip_y1:
                        continue

                    x0 = fx0

                    x1 = fx0 + size - 1

                    if x0 >= clip_x0 and x0 <= clip_x1:

                        setpixel(x0, y, max_color)

                    if x1 >= clip_x0 and x1 <= clip_x1:

                        setpixel(x1, y, max_color)

            else:

                # normal single square maximise icon
                mx = inner_min_x

                my = inner_min_y

                for x in range(mx, inner_max_x + 1):

                    if x < clip_x0 or x > clip_x1:
                        continue

                    y0 = my

                    y1 = inner_max_y

                    if y0 >= clip_y0 and y0 <= clip_y1:

                        setpixel(x, y0, max_color)

                    if y1 >= clip_y0 and y1 <= clip_y1:

                        setpixel(x, y1, max_color)

                for y in range(my, inner_max_y + 1):

                    if y < clip_y0 or y > clip_y1:
                        continue

                    x0 = mx

                    x1 = inner_max_x

                    if x0 >= clip_x0 and x0 <= clip_x1:

                        setpixel(x0, y, max_color)

                    if x1 >= clip_x0 and x1 <= clip_x1:

                        setpixel(x1, y, max_color)

    # minimise button region
    ix2, iy2, iw2, ih2 = rectintersect(min_x, min_y, BTNWH, BTNWH, cx, cy, cw, ch)

    if iw2 > 0 and ih2 > 0:

        if clientchromecontrols(win) != "chromium" and hoverarea != "min":
            fillrectfast(ix2, iy2, iw2, ih2, title_color)

        pad_min = 5

        nx0 = min_x + pad_min

        nx1 = min_x + BTNWH - pad_min

        ny = min_y + BTNWH - pad_min

        if nx1 >= nx0 and ny >= clip_y0 and ny <= clip_y1:

            for x in range(nx0, nx1 + 1):

                if x >= clip_x0 and x <= clip_x1:

                    setpixel(x, ny, min_color)


def buttonrects(fx, fy, fw):

    bx2 = fx + fw - FRAMEW - BTNGAP

    by = fy + (TITLEH - BTNWH) // 2

    close_x = bx2 - BTNWH

    close_y = by

    button_gap = max(BTNGAP, TITLEH - BTNWH)

    max_x = close_x - button_gap - BTNWH

    max_y = by

    min_x = max_x - button_gap - BTNWH

    min_y = by

    return close_x, close_y, max_x, max_y, min_x, min_y


def framedamagerect(win):

    try:

        if GPUCOMPOSITOR:
            return gpuvisualrect(win)

        # non-framed roles have no chrome
        role = str(win.get("role", ""))

        if role != "window":
            return [int(win["x"]), int(win["y"]), int(win["w"]), int(win["h"])]

        return list(winframerect(win))

    except Exception:

        # fall back to client rect if anything goes wrong
        return [int(win.get("x", 0)), int(win.get("y", 0)), int(win.get("w", 0)), int(win.get("h", 0))]


def blitwindow(win):
    if not win.get("mapped"):
        return
    blitwindowregion(
        win,
        [
            int(win.get("x", 0)),
            int(win.get("y", 0)),
            int(win.get("w", 0)),
            int(win.get("h", 0)),
        ],
    )
def tildamage(win, tilesz=256):


    gw = int(win["w"])
    gh = int(win["h"])
    gx = int(win["x"])
    gy = int(win["y"])

    if gw <= 0 or gh <= 0:
        return

    # split into tiles in screen space so compositor can yield between tiles
    y = 0
    while y < gh:
        h = tilesz if y + tilesz < gh else gh - y
        x = 0
        while x < gw:
            w = tilesz if x + tilesz < gw else gw - x
            DAMAGERECTS.append([gx + x, gy + y, w, h])
            x += tilesz
        y += tilesz

def registerdesktopclient(cid):

    try:

        if not clienthascapability(cid, "desktop_controller"):
            raise PermissionError("desktop controller capability is required")

        # track clients that own a desktop window
        DESKTOPCLIENTS.add(cid)

    except Exception as e:

        # desktop client register error
        log(f"desktop client register error {e}")


def broadcasttaskbarevent(obj):

    try:

        # send taskbar-related events to all desktop clients
        for dcid in list(DESKTOPCLIENTS):


            if dcid in clients:

                sendjson(dcid, obj)

    except Exception as e:

        # broadcast error
        log(f"taskbar broadcast error {e}")


def broadcaststartmenutoggle():

    try:

        obj = {"op": "STARTMENU_TOGGLE"}

        for dcid in list(DESKTOPCLIENTS):


            if dcid in clients:

                sendjson(dcid, obj)

    except Exception as e:

        log(f"startmenu toggle broadcast error {e}")


def broadcastfbsize():

    try:

        if INPUTCONN is not None:

            sendinputjson({"op": "FB_SIZE", "w": int(SCREENW), "h": int(SCREENH)})

    except Exception:

        pass

    for cid in list(clients.keys()):

        try:

            subs = clients[cid].get("subs")

            if not subs:
                continue

            if "fbsize" not in subs:
                continue

            sendjson(cid, {
                "op": "FB_SIZE",
                "w": int(SCREENW),
                "h": int(SCREENH),
                "ui_scale": float(GPUUISCALE),
            })

        except Exception:

            continue


def broadcastworkarea():

    for cid in list(clients.keys()):

        try:

            subs = clients[cid].get("subs")

            if not subs:
                continue

            if "workarea" not in subs:
                continue

            sendjson(cid, {"op": "WORK_AREA", "x": int(WORKX), "y": int(WORKY), "w": int(WORKW), "h": int(WORKH)})

        except Exception:

            continue


def fitwindowtoworkarea(wid):

    if wid not in windows:
        return

    win = windows[wid]

    if str(win.get("role", "")) != "window":
        return

    if win.get("_max"):
        return

    insetleft, insettop, insetright, insetbottom = windowframeinsets(win)

    maxw = WORKW - insetleft - insetright

    maxh = WORKH - insettop - insetbottom

    if maxw < 1: maxw = 1

    if maxh < 1: maxh = 1

    nw = min(int(win["w"]), int(maxw))

    nh = min(int(win["h"]), int(maxh))

    if nw != int(win["w"]) or nh != int(win["h"]):

        resizewindow(win["cid"], {"winid": wid, "w": nw, "h": nh})

        win = windows.get(wid)

        if not win:
            return

    minx = int(WORKX + insetleft)

    miny = int(WORKY + insettop)

    maxx = int(WORKX + WORKW - insetright - int(win["w"]))

    maxy = int(WORKY + WORKH - insetbottom - int(win["h"]))

    if maxx < minx: maxx = minx

    if maxy < miny: maxy = miny

    nx = max(minx, min(maxx, int(win["x"])))

    ny = max(miny, min(maxy, int(win["y"])))

    if nx != int(win["x"]) or ny != int(win["y"]):

        movewindow(win["cid"], {"winid": wid, "x": nx, "y": ny})


def scalewindowtoworkarea(wid, previouswork):

    if wid not in windows or not previouswork:
        return

    try:
        oldx, oldy, oldw, oldh = [int(value) for value in previouswork]
    except Exception:
        return

    if oldw <= 0 or oldh <= 0 or WORKW <= 0 or WORKH <= 0:
        return

    win = windows[wid]

    if str(win.get("role", "")) != "window":
        return

    if isfullscreen(win):
        return

    scalex = float(WORKW) / float(oldw)
    scaley = float(WORKH) / float(oldh)

    def geometry(values):
        return [
            int(WORKX + round((int(values[0]) - oldx) * scalex)),
            int(WORKY + round((int(values[1]) - oldy) * scaley)),
            max(1, int(round(int(values[2]) * scalex))),
            max(1, int(round(int(values[3]) * scaley))),
        ]

    restore = win.get("_restore")

    if isinstance(restore, (list, tuple)) and len(restore) >= 4:
        win["_restore"] = geometry(restore)

    if win.get("_max"):
        return

    nx, ny, nw, nh = geometry([win["x"], win["y"], win["w"], win["h"]])

    if nw != int(win["w"]) or nh != int(win["h"]):
        resizewindow(win["cid"], {"winid": wid, "w": nw, "h": nh})

    win = windows.get(wid)

    if win and (nx != int(win["x"]) or ny != int(win["y"])):
        movewindow(win["cid"], {"winid": wid, "x": nx, "y": ny})


def refreshwindows(previouswork=None):

    for wid in list(windows.keys()):

        win = windows.get(wid)

        if not win:
            continue

        if str(win.get("role", "")) != "window":
            continue

        if isfullscreen(win):
            movewindow(win["cid"], {
                "winid": wid,
                "x": 0,
                "y": 0,
                "_fullscreen_internal": True,
            })
            resizewindow(win["cid"], {
                "winid": wid,
                "w": int(SCREENW),
                "h": int(SCREENH),
                "_fullscreen_internal": True,
            })
            continue

        if previouswork:
            scalewindowtoworkarea(wid, previouswork)

            win = windows.get(wid)

            if not win:
                continue

        if not win.get("_max"):

            fitwindowtoworkarea(wid)
            continue

        snap = str(win.get("_snap", ""))

        if snap in ("left", "right"):

            snapapply(wid, snap)

        else:

            maximizewindow(wid)


def broadcastvboxdnd(obj):

    for cid in list(clients.keys()):

        try:

            if "vbox_dnd" not in clients[cid].get("subs", set()):
                continue

            sendjson(cid, obj)

        except Exception:

            continue


def vboxdndkind(value):

    value = str(value or "").lower()

    if "uri-list" in value or value == "files":
        return "files"

    if "html" in value:
        return "html"

    if "image" in value or "bitmap" in value:
        return "image"

    if value:
        return "text"

    return None


def vboxdndtarget(x, y, kind):

    wid = hittest(int(x), int(y))

    if wid not in windows:
        return None

    if kind not in windows[wid].get("drop_types", set()):
        return None

    return wid


def vboxdndnotify(wid, op, x=None, y=None, kind=None, **values):

    if wid not in windows:
        return

    event = {"op": op, "winid": wid}

    if x is not None and y is not None:
        event["x"] = int(x) - int(windows[wid]["x"])
        event["y"] = int(y) - int(windows[wid]["y"])
        event["absx"] = int(x)
        event["absy"] = int(y)

    if kind:
        event["kind"] = kind

    event.update(values)
    sendjson(windows[wid]["cid"], event)


def vboxdndleave():

    old = VBOXDND.get("wid")

    if old in windows:
        vboxdndnotify(old, "DND_LEAVE")

    VBOXDND.update({"wid": None, "kind": None, "format": "", "x": 0, "y": 0, "dropped": False})


def vboxhoststagingpath(value):

    try:
        base = os.path.realpath(VBOXDNDBASE)
        path = os.path.realpath(os.path.abspath(str(value)))
        if os.path.commonpath((base, path)) != base:
            return None
        info = os.lstat(path)
        if stat.S_ISLNK(info.st_mode) or not (
            stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)
        ):
            return None
        return path
    except (OSError, TypeError, ValueError):
        return None


def vboxdndhost(cid, msg):

    if (
        clients.get(cid, {}).get("integration") != "guestadditions"
        or not clienthascapability(cid, "guest_integration")
    ):
        sendjson(cid, {"op": "ERROR", "code": "denied"})
        return

    op = str(msg.get("op", ""))

    if op == "VBOX_DND_HOST_ENTER":
        vboxdndleave()
        VBOXDND["format"] = str(msg.get("format", ""))
        VBOXDND["kind"] = vboxdndkind(VBOXDND["format"])
        return

    if op in ("VBOX_DND_HOST_LEAVE", "VBOX_DND_HOST_CANCEL"):
        vboxdndleave()
        return

    try:
        x = int(msg.get("x", VBOXDND.get("x", 0)))
        y = int(msg.get("y", VBOXDND.get("y", 0)))
    except Exception:
        x, y = 0, 0

    kind = vboxdndkind(msg.get("kind", VBOXDND.get("kind")))
    target = vboxdndtarget(x, y, kind)
    old = VBOXDND.get("wid")

    if target != old:
        if old in windows:
            vboxdndnotify(old, "DND_LEAVE")
        if target in windows:
            vboxdndnotify(target, "DND_ENTER", x, y, kind, format=str(msg.get("format", VBOXDND.get("format", ""))))

    VBOXDND.update({"wid": target, "kind": kind, "x": x, "y": y})

    if op == "VBOX_DND_HOST_MOVE":
        if target in windows:
            vboxdndnotify(target, "DND_MOVE", x, y, kind)
        return

    if op == "VBOX_DND_HOST_DROP":
        VBOXDND["dropped"] = True
        if target in windows:
            vboxdndnotify(target, "DND_DROP_PENDING", x, y, kind)
        return

    if op == "VBOX_DND_HOST_DATA":
        target = VBOXDND.get("wid")
        if target in windows and VBOXDND.get("dropped"):
            payload = {"format": str(msg.get("format", ""))[:256]}
            if kind == "files":
                rawpaths = msg.get("paths", [])
                if not isinstance(rawpaths, list):
                    rawpaths = []
                paths = []
                for value in rawpaths[:128]:
                    path = vboxhoststagingpath(value)
                    if path:
                        paths.append(path)
                if paths:
                    payload["paths"] = paths
            elif kind in ("text", "html"):
                data = str(msg.get(kind, ""))
                if len(data.encode("utf-8", errors="replace")) <= 1048576:
                    payload[kind] = data
            if any(key in payload for key in ("paths", "text", "html")):
                vboxdndnotify(
                    target,
                    "DND_DROP",
                    VBOXDND.get("x", x),
                    VBOXDND.get("y", y),
                    kind,
                    **payload,
                )
        vboxdndleave()


def vboxdndguest(cid, msg):

    try:
        wid = int(msg.get("winid", 0))
    except Exception:
        wid = 0

    if wid not in windows or windows[wid].get("cid") != cid:
        sendjson(cid, {"op": "ERROR", "code": "unknown_window"})
        return

    op = str(msg.get("op", ""))

    if op == "DND_GUEST_CLEAR":
        broadcastvboxdnd({"op": "VBOX_DND_GUEST_CLEAR", "winid": wid})
        return

    if not clienthasphysicalgesture(cid):
        sendjson(cid, {"op": "ERROR", "code": "user_gesture_required"})
        return

    kind = vboxdndkind(msg.get("kind", ""))

    if kind not in windows[wid].get("drop_types", set()):
        sendjson(cid, {"op": "ERROR", "code": "unsupported_type"})
        return

    event = {"op": "VBOX_DND_GUEST_START", "winid": wid, "kind": kind}

    if kind == "files":
        rawpaths = msg.get("paths", [])
        if not isinstance(rawpaths, list):
            sendjson(cid, {"op": "ERROR", "code": "bad_paths"})
            return
        paths = []
        for value in rawpaths[:128]:
            path = os.path.abspath(str(value))
            if "\x00" not in path and os.path.exists(path):
                paths.append(path)
        if not paths:
            sendjson(cid, {"op": "ERROR", "code": "missing_source"})
            return
        event["paths"] = paths
    else:
        data = str(msg.get(kind, msg.get("data", "")))
        if len(data.encode("utf-8", errors="replace")) > 1048576:
            sendjson(cid, {"op": "ERROR", "code": "too_large"})
            return
        event[kind] = data

    broadcastvboxdnd(event)


# clipboard functions
def clearclipboard():

    """Remove compositor-owned clipboard bytes and reset all public state."""

    path = os.path.join(CLIPBASE, "current.txt")
    clipboard["type"] = None
    clipboard["path"] = None

    try:
        info = os.lstat(path)
    except FileNotFoundError:
        info = None
    except OSError:
        return False

    if info is not None and (
        not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)
    ):
        # CLIPBASE is root-only; remove a stale name itself, never its target.
        try:
            os.unlink(path)
        except OSError:
            return False
        info = None

    if info is not None:
        descriptor = None
        try:
            flags = os.O_WRONLY | getattr(os, "O_CLOEXEC", 0)
            flags |= getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(path, flags)
            current = os.fstat(descriptor)
            if not stat.S_ISREG(current.st_mode) or current.st_uid != os.geteuid():
                raise PermissionError("unsafe clipboard object")

            # Best-effort in-place overwrite before unlink. This is not a
            # promise against flash translation layers, but avoids retaining
            # ordinary tmpfs pages and makes lock/clear semantics immediate.
            remaining = min(int(current.st_size), 1024 * 1024)
            zeros = b"\0" * min(65536, max(1, remaining))
            while remaining > 0:
                written = os.write(
                    descriptor, zeros[:min(len(zeros), remaining)])
                if written <= 0:
                    break
                remaining -= written
            os.ftruncate(descriptor, 0)
            os.fsync(descriptor)
        except OSError:
            pass
        finally:
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass

        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        except OSError:
            return False

    # A crash between O_EXCL creation and atomic replace must not preserve an
    # orphaned clipboard payload across a compositor restart or explicit clear.
    try:
        for entry in os.scandir(CLIPBASE):
            if not (
                entry.name.startswith("current.txt.")
                and entry.name.endswith(".new")
            ):
                continue
            info = entry.stat(follow_symlinks=False)
            if info.st_uid == os.geteuid() and (
                stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)
            ):
                os.unlink(entry.path)
    except OSError:
        return False
    return True


def clipclear(cid):

    if not clienthasclipboardaccess(cid):
        sendjson(cid, {"op": "ERROR", "code": "denied"})
        return False

    cleared = clearclipboard()
    if cleared:
        sendjson(cid, {"op": "CLIPBOARD_EMPTY"})
    else:
        sendjson(cid, {"op": "ERROR", "code": "clip_clear_failed"})
    return cleared


def clipset(cid, req):

    temporary = None

    try:

        if not clienthasclipboardaccess(cid):
            raise PermissionError(
                "clipboard access requires focused physical user activation")

        # Clipboard bytes travel inline. WindowServer must never become a
        # privileged pathname reader for a less-trusted application domain.
        contenttype = str(req.get("type", "text/plain"))
        text = req.get("text")
        if contenttype != "text/plain" or not isinstance(text, str):
            sendjson(cid, {"op": "ERROR", "code": "unsupported_type"})
            return
        data = text.encode("utf-8", errors="strict")
        if len(data) > 1024 * 1024:
            raise ValueError("clipboard text exceeds 1 MiB")

        # define destination
        dst = os.path.join(CLIPBASE, "current.txt")

        # Replace atomically with a private regular file.
        temporary = f"{dst}.{os.getpid()}.{cid}.{random.getrandbits(64):016x}.new"
        outputfd = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
            0o600,
        )
        try:
            view = memoryview(data)
            while view:
                written = os.write(outputfd, view)
                if written <= 0:
                    raise OSError("clipboard write made no progress")
                view = view[written:]
            os.fsync(outputfd)
        finally:
            os.close(outputfd)
        os.replace(temporary, dst)
        os.chmod(dst, 0o600)

        # update state
        clipboard["type"] = "text/plain"
        clipboard["path"] = dst

        # ack
        sendjson(cid, {"op": "CLIPBOARD_OWNED", "type": "text/plain"})

    except PermissionError:

        # permission denied copying clipboard
        if temporary:
            try:
                os.unlink(temporary)
            except OSError:
                pass
        sendjson(cid, {"op": "ERROR", "code": "denied"})

    except Exception as e:

        # clipboard set error
        if temporary:
            try:
                os.unlink(temporary)
            except OSError:
                pass
        sendjson(cid, {"op": "ERROR", "code": "clip_set_failed", "detail": str(e)})


def clipget(cid, req):

    try:

        if not clienthasclipboardaccess(cid):
            raise PermissionError(
                "clipboard access requires focused physical user activation")

        # if clipboard empty
        if not clipboard["path"] or not os.path.exists(clipboard["path"]):
            sendjson(cid, {"op": "CLIPBOARD_EMPTY"})
            return

        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(clipboard["path"], flags)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_size > 1024 * 1024:
                raise PermissionError("unsafe clipboard object")
            data = b""
            while len(data) <= 1024 * 1024:
                chunk = os.read(descriptor, min(65536, 1024 * 1024 + 1 - len(data)))
                if not chunk:
                    break
                data += chunk
        finally:
            os.close(descriptor)

        if len(data) > 1024 * 1024:
            raise PermissionError("clipboard object is too large")

        text = data.decode("utf-8", errors="strict")
        sendjson(cid, {
            "op": "CLIPBOARD_DATA",
            "type": clipboard["type"],
            "text": text,
        })

    except Exception as e:

        # clipboard get error
        sendjson(cid, {"op": "ERROR", "code": "clip_get_failed", "detail": str(e)})


# protocol functions
def sessionauthenticated(cid, msg):

    global SESSIONLOCKED

    state = clients.get(cid)

    if not SESSIONLOCKED or not state:
        sendjson(cid, {
            "op": "ERROR",
            "code": "session_authentication_denied",
        })
        return False

    try:
        peerpid = int(state.get("peer_pid") or 0)
        ownerpid = int(LOCKSCREENPID or 0)
        winid = int(msg.get("winid", 0))
    except Exception:
        peerpid = 0
        ownerpid = 0
        winid = 0

    win = windows.get(winid)
    processactive = sessionlockactive()
    authorized = bool(
        processactive
        and ownerpid > 0
        and peerpid == ownerpid
        and clienthascapability(cid, "session_authentication")
        and sameprocessidentity(state.get("identity"), LOCKSCREENIDENTITY)
        and processidentitycurrent(LOCKSCREENIDENTITY)
        and win
        and win.get("cid") == cid
        and win.get("mapped")
        and str(win.get("role", "")) == "lockscreen"
        and str(win.get("path", "")) == os.path.realpath(STARTUPPATH)
    )

    if not authorized:
        log(
            f"session authentication denied cid={cid} "
            f"peer={peerpid} owner={ownerpid} winid={winid}"
        )
        sendjson(cid, {
            "op": "ERROR",
            "code": "session_authentication_denied",
        })
        return False

    if not invalidatelockscreenpresentation():
        log(
            f"session authentication denied cid={cid} "
            f"peer={peerpid} because presentation invalidation failed"
        )
        sendjson(cid, {
            "op": "ERROR",
            "code": "session_authentication_denied",
        })
        return False

    SESSIONLOCKED = False
    log(
        f"session authentication accepted cid={cid} "
        f"peer={peerpid} winid={winid}"
    )
    sendjson(cid, {
        "op": "SESSION_AUTHENTICATED",
        "authenticated": True,
    })
    return True


def handleline(cid, line):

    global GPUUISCALE, CFG, CURSORDIRTY, LASTCURSOR

    state = clients.get(cid)
    identity = state.get("identity") if state else None
    if not state or not processidentitycurrent(identity):
        if isinstance(identity, dict) and int(identity.get("uid", -1)) == SESSIONUID:
            current = readprocessstat(identity.get("pid"))
            graphicslog(
                f"> graphics privileged surface peer became noncurrent "
                f"cid={cid} pid={identity.get('pid')} "
                f"captured_domain={identity.get('domain')} "
                f"current_domain={processsecuritydomain(identity.get('pid'))} "
                f"captured_start={identity.get('starttime')} current={current}"
            )
        dropclient(cid, "authenticated process identity ended")
        return

    try:

        msg = json.loads(line)

    except json.JSONDecodeError:

        sendjson(cid, {"op": "ERROR", "code": "bad_json"})
        return

    op = msg.get("op", "")

    if op == "CREATE_WINDOW" and str((identity or {}).get("domain", "")) in (
        "lockscreen", "startup"
    ):
        graphicslog(
            f"> graphics privileged CREATE_WINDOW cid={cid} "
            f"pid={identity.get('pid')} domain={identity.get('domain')} "
            f"role={msg.get('role')} size={msg.get('w')}x{msg.get('h')}"
        )

    if state.get("identity", {}).get("trusted_launcher") is True and op != "HELLO":
        sendjson(cid, {"op": "ERROR", "code": "launcher_control_denied"})
        return

    if LOGOPS:

        log(f"rx op={op} cid={cid}")

    if op == "HELLO":
        role = str(msg.get("role", ""))

        if role == "guestadditions":
            if not clienthascapability(cid, "guest_integration"):
                sendjson(cid, {"op": "ERROR", "code": "integration_denied"})
                return
            clients[cid]["integration"] = role

        sendjson(cid, {
            "op": "WELCOME",
            "server": SERVERID,
            "windowserver_pid": int(os.getpid()),
            "fb": {"w": int(SCREENW), "h": int(SCREENH)},
            "ui_scale": float(GPUUISCALE),
            "work": {"x": int(WORKX), "y": int(WORKY), "w": int(WORKW), "h": int(WORKH)},
            "window_states": ["normal", "maximized", "fullscreen"],
            "graphics": graphicscapabilities(),
            "pickers": {
                "version": PICKERVERSION,
                "modes": list(PICKERMODES),
            },
            "dialogs": {
                "version": 2,
                "types": ["message", "input", "password"],
            },
            "screen_capture": {
                "version": 1,
                "modes": ["rectangular", "window", "full_screen"],
                "authority": "kernel-domain:snap",
            },
        })

    elif op == "SUBSCRIBE":

        types = msg.get("types")

        if not isinstance(types, list):
            sendjson(cid, {"op": "ERROR", "code": "bad_subscribe"})
            return

        requested = {str(value) for value in types}
        if not requested.issubset({"fbsize", "workarea", "vbox_dnd"}):
            sendjson(cid, {"op": "ERROR", "code": "bad_subscribe"})
            return
        if "vbox_dnd" in requested and not clienthascapability(cid, "guest_integration"):
            sendjson(cid, {"op": "ERROR", "code": "integration_denied"})
            return

        subs = clients[cid].get("subs")

        if subs is None:
            clients[cid]["subs"] = set()

            subs = clients[cid]["subs"]

        for t in requested:

            try:
                subs.add(str(t))
            except Exception:
                pass

        sendjson(cid, {"op": "OK", "ref": "SUBSCRIBE"})

        # push current state immediately for convenience
        if "fbsize" in subs:

            sendjson(cid, {
                "op": "FB_SIZE",
                "w": int(SCREENW),
                "h": int(SCREENH),
                "ui_scale": float(GPUUISCALE),
            })

        if "workarea" in subs:

            sendjson(cid, {"op": "WORK_AREA", "x": int(WORKX), "y": int(WORKY), "w": int(WORKW), "h": int(WORKH)})

    elif op == "GET_FBSIZE":

        sendjson(cid, {
            "op": "FB_SIZE",
            "w": int(SCREENW),
            "h": int(SCREENH),
            "ui_scale": float(GPUUISCALE),
        })

    elif op == "SESSION_AUTHENTICATED":
        sessionauthenticated(cid, msg)

    elif op == "DISPLAY_SETTINGS_SET":

        try:
            wid = int(msg.get("winid", 0))
        except Exception:
            wid = 0

        win = windows.get(wid)

        if not win or win.get("cid") != cid or not clienthascapability(cid, "display_settings"):
            sendjson(cid, {"op": "ERROR", "code": "denied"})
            return

        try:
            GPUUISCALE = max(
                0.5, min(3.0, float(msg.get("ui_scale", 1.0))))
            CFG["ui_scale"] = GPUUISCALE
            applyuiscale()
            adjustment = setdisplayadjustment(
                msg.get("brightness", 100),
                msg.get("contrast", 100),
                msg.get("saturation", 100),
                **{
                    key: value for key, value in msg.items()
                    if str(key).startswith("night_light_")
                },
            )
            gpuinvalidatesurface()
            DAMAGERECTS.append([0, 0, int(SCREENW), int(SCREENH)])
            broadcastfbsize()
            sendjson(cid, {"op": "DISPLAY_SETTINGS_SET", "ui_scale": GPUUISCALE, **adjustment})
        except Exception as error:
            sendjson(cid, {"op": "ERROR", "code": "display_settings_failed", "detail": str(error)})

    elif op == "MOUSE_SETTINGS_SET":

        try:
            wid = int(msg.get("winid", 0))
        except Exception:
            wid = 0

        win = windows.get(wid)

        if not win or win.get("cid") != cid or not clienthascapability(cid, "display_settings"):
            sendjson(cid, {"op": "ERROR", "code": "denied"})
            return

        try:
            pointerspeed = max(
                0.25, min(2.0, float(msg.get("cursor_speed", 1.0))))
            oldbox = list(LASTCURSOR) if LASTCURSOR else pointercursorbox(
                POINTERX, POINTERY, CURSORMODE)
            loadcursor()
            CURSORSIZES.clear()
            newbox = pointercursorbox(POINTERX, POINTERY, CURSORMODE)
            LASTCURSOR = newbox
            CURSORDIRTY = True

            if oldbox and len(oldbox) == 4:
                DAMAGERECTS.append(oldbox)
            if newbox and len(newbox) == 4:
                DAMAGERECTS.append(newbox)

            if INPUTCONN is None or not processidentitycurrent(INPUTIDENTITY):
                raise RuntimeError("authenticated input service is unavailable")
            sendinputjson({"op": "POINTER_SPEED_SET", "speed": pointerspeed})

            sendjson(cid, {
                "op": "MOUSE_SETTINGS_SET",
                "cursor_speed": pointerspeed,
            })
        except Exception as error:
            sendjson(cid, {"op": "ERROR", "code": "mouse_settings_failed", "detail": str(error)})

    elif op == "CREATE_WINDOW":
        createwindow(cid, msg)

    elif op == "CREATE_DIALOG":
        createdialog(cid, msg)

    elif op == "CREATE_PASSWORD_PROMPT":
        createpasswordprompt(cid, msg)

    elif op == "CREATE_PICKER":
        createpicker(cid, msg)

    elif op == "SCREEN_CAPTURE_REQUEST":
        snapcapture(cid, msg)

    elif op == "PICKER_ATTACH":
        pickerattach(cid, msg)

    elif op == "PICKER_FINISH":
        pickerfinish(cid, msg)

    elif op in ("VBOX_DND_HOST_ENTER", "VBOX_DND_HOST_MOVE", "VBOX_DND_HOST_DROP", "VBOX_DND_HOST_DATA", "VBOX_DND_HOST_LEAVE", "VBOX_DND_HOST_CANCEL"):
        vboxdndhost(cid, msg)

    elif op in ("DND_GUEST_START", "DND_GUEST_CLEAR"):
        vboxdndguest(cid, msg)

    elif op == "WORKAREA_SET":

        if cid not in DESKTOPCLIENTS or not clienthascapability(cid, "desktop_controller"):
            sendjson(cid, {"op": "ERROR", "code": "denied"})
            return

        try:

            taskbarh = int(msg.get("taskbarh", msg.get("taskbar_height", 0)))

        except Exception:

            taskbarh = 0

        if taskbarh < 0:
            taskbarh = 0

        if taskbarh > SCREENH:
            taskbarh = SCREENH

        if CFG is None:
            CFG = loadsettings()

        CFG["taskbar_height"] = taskbarh

        setworkarea(CFG)

        broadcastworkarea()

        refreshwindows()

        sendjson(cid, {"op": "OK", "ref": "WORKAREA_SET"})

    elif op == "MAP":
        mapwindow(cid, msg)

    elif op == "UNMAP":
        unmapwindow(cid, msg)

    elif op == "CLOSE_ACK":

        identity = clients.get(cid, {}).get("identity")
        peerpid = int(identity.get("pid", 0)) if isinstance(identity, dict) else 0
        try:
            claimedpid = int(msg.get("pid", peerpid))
        except Exception:
            claimedpid = 0

        if peerpid <= 1 or claimedpid != peerpid:
            sendjson(cid, {"op": "ERROR", "code": "close_ack_denied"})
            return

        for pendingpid, info in list(PENDINGKILLS.items()):
            if (
                int(pendingpid) == peerpid
                and info.get("cid") == cid
                and pendingkillidentityvalid(info, peerpid)
            ):
                pendingkillremove(pendingpid)

    elif op == "DAMAGE":
        markdamage(cid, msg)

    elif op == "WINDOW_BUFFER_ATTACH":
        setwindowexternalbuffer(cid, msg, attached=True)

    elif op == "WINDOW_BUFFER_DETACH":
        setwindowexternalbuffer(cid, msg, attached=False)

    elif op == "WINDOW_EFFECTS":
        setwindoweffects(cid, msg)

    elif op == "GRAPHICS_INFO":
        sendjson(cid, {"op": "GRAPHICS_INFO", **graphicscapabilities()})

    elif op == "VIDEO_AUTHORIZE":
        videoauthorize(cid, msg)

    elif op == "GRAPHICS_TELEMETRY":
        graphicstelemetry(cid)

    elif op == "GRAPHICS_ANIMATE":
        graphicsanimate(cid, msg)

    elif op == "GRAPHICS_BEGIN":
        graphicsbegin(cid, msg)

    elif op == "GRAPHICS_RECTANGLE":
        graphicsappend(cid, msg, "rectangle")

    elif op == "GRAPHICS_IMAGE":
        graphicsappend(cid, msg, "image")

    elif op == "GRAPHICS_TEXT":
        graphicsappend(cid, msg, "text")

    elif op == "GRAPHICS_COMMIT":
        graphicscommit(cid, msg)

    elif op == "GRAPHICS_SCENE":
        graphicsscene(cid, msg)

    elif op == "GRAPHICS_PATCH":
        graphicspatch(cid, msg)

    elif op == "GRAPHICS_CLEAR":
        graphicsclear(cid, msg)

    elif op == "OVERLAY_DAMAGE":
        markrectdamage(cid, msg)

    elif op == "MOVE":
        movewindow(cid, msg)

    elif op == "RESIZE":
        resizewindow(cid, msg)

    elif op == "WINDOW_FULLSCREEN_SET":
        setwindowfullscreen(cid, msg)

    elif op == "RAISE":
        raisewindow(cid, msg)

    elif op == "CLIPBOARD_SET":
        clipset(cid, msg)

    elif op == "CLIPBOARD_GET":
        clipget(cid, msg)

    elif op == "CLIPBOARD_CLEAR":
        clipclear(cid)

    elif op in ("INPUT_POINTER", "INPUT_BUTTON", "INPUT_KEY"):
        # Raw input is accepted only on the separately authenticated
        # InputServer channel. The public client protocol cannot inject it.
        sendjson(cid, {"op": "ERROR", "code": "input_injection_denied"})

    elif op == "FOCUS_SET":
        focusset(cid, msg)

    elif op == "CURSOR_SET":
        cursorset(cid, msg)

    elif op == "CURSOR_MODE_SET":
        cursormodeset(cid, msg)

    elif op == "TASKBAR_ACTIVATE":
        taskbaractivate(cid, msg)

    elif op == "WINDOW_CLOSE":
        windowclose(cid, msg)

    elif op == "SHOW_DESKTOP":
        showdesktop(cid)

    elif op == "WINDOW_CURRENT_SET":
        setwindowcurrent(cid, msg)

    else:
        sendjson(cid, {"op": "ERROR", "code": "unknown_op", "detail": op})


# io service functions
def serveio(timeout=0.001):

    try:

        maintaininputserver()

        events = sel.select(timeout)

        for key, mask in events:

            if key.data.get("kind") == "graphics":
                try:
                    graphicsdrmpresentationevent()
                except (GPUDeviceLostError, GPUCompositorError):
                    raise
                except Exception as error:
                    raise GPUCompositorError(
                        f"DRM presentation event failed: {error}"
                    ) from error
                continue

            if key.data.get("kind") == "listener":
                acceptclient(key.fileobj)
                continue

            if key.data.get("kind") == "video_listener":
                acceptvideoclient(key.fileobj)
                continue

            if key.data.get("kind") == "video_client":
                if mask & selectors.EVENT_READ:
                    recvvideoclient(key.data)
                if mask & selectors.EVENT_WRITE and key.data.get("id") in VIDEOCLIENTS:
                    flushvideoclient(key.data)
                continue

            if key.data.get("kind") == "inputserver":

                lines = recvinputlines()

                for ln in lines:
                    handleinputserverline(ln)

                flushinputserver()
                continue

            if key.data.get("kind") == "client":

                cid = key.data["id"]

                if mask & selectors.EVENT_READ:

                    lines = recvlines(cid)

                    for ln in lines:
                        if cid not in clients:
                            break
                        handleline(cid, ln)

                if mask & selectors.EVENT_WRITE and cid in clients:

                    # drain queued bytes aggressively
                    for _ in range(4):
                        if cid not in clients or not clients[cid]["outbuf"]:
                            break
                        flushclient(cid)
    except (GPUDeviceLostError, GPUCompositorError):
        raise

    except PermissionError:

        sendjson(cid, {"op": "ERROR", "code": "denied"})

    except Exception as e:

        log(f"selector error {e}")


def iopulse():


    # quick non-blocking service of i/o
    events = sel.select(0)

    for key, mask in events:

        if key.data.get("kind") == "graphics":
            graphicsdrmpresentationevent()
            continue

        if key.data.get("kind") == "inputserver":

            lines = recvinputlines()

            for ln in lines:
                handleinputserverline(ln)

            flushinputserver()
            continue

        if key.data.get("kind") == "video_listener":
            acceptvideoclient(key.fileobj)
            continue

        if key.data.get("kind") == "video_client":
            if mask & selectors.EVENT_READ:
                recvvideoclient(key.data)
            if mask & selectors.EVENT_WRITE and key.data.get("id") in VIDEOCLIENTS:
                flushvideoclient(key.data)
            continue

        if key.data.get("kind") == "client":

            cid = key.data["id"]

            if mask & selectors.EVENT_READ:

                lines = recvlines(cid)

                for ln in lines:
                    handleline(cid, ln)

            if mask & selectors.EVENT_WRITE:
                flushclient(cid)

        elif key.data.get("kind") == "listener":
            acceptclient(key.fileobj)


    pendingkillpulse()

def drainio(cycles=4):


    for _ in range(int(cycles)):

        events = sel.select(0)

        if not events:
            break

        for key, mask in events:

            if key.data.get("kind") == "graphics":
                graphicsdrmpresentationevent()
                continue

            if key.data.get("kind") == "listener":
                acceptclient(key.fileobj)
                continue

            if key.data.get("kind") == "video_listener":
                acceptvideoclient(key.fileobj)
                continue

            if key.data.get("kind") == "video_client":
                if mask & selectors.EVENT_READ:
                    recvvideoclient(key.data)
                if mask & selectors.EVENT_WRITE and key.data.get("id") in VIDEOCLIENTS:
                    flushvideoclient(key.data)
                continue

            if key.data.get("kind") == "inputserver":

                lines = recvinputlines()

                for ln in lines:
                    handleinputserverline(ln)

                flushinputserver()
                continue

            if key.data.get("kind") == "client":

                cid = key.data["id"]

                if mask & selectors.EVENT_READ:

                    lines = recvlines(cid)

                    for ln in lines:
                        handleline(cid, ln)

                if mask & selectors.EVENT_WRITE:
                    flushclient(cid)

def handlesignal(signum, frame):

    # request shutdown
    global SERVERRUN

    SERVERRUN = False


def windowcompositordiagnostic():

    global SCREENW, SCREENH, WORKX, WORKY, WORKW, WORKH, BUFBASE, CHROMIUMXWDBUFFER
    global GPUCOMPOSITOR, GPUFAILED, GPUSHADOWS, GPUTRANSITIONS, GPUOCCLUSION
    global STARTUPCURSORWAIT, BOOTCURSORHIDE, CURSORENABLED, FOCUSWID
    global POINTERX, POINTERY, GPUCOMMANDERRORS, GPUCOMMANDLASTERROR, GPUFULLFRAMEFALLBACKS
    global GPUUISCALE, STATEBASE, TELEMETRYPATH, LASTTELEMETRY

    result = {
        "format": 1,
        "passed": False,
        "resolution": [2560, 1440],
        "checks": {},
        "telemetry": {},
        "performance": {},
        "graphics_api": {},
        "errors": [],
    }
    diagnosticbase = "/.ephemeral/windowserver-diagnostic"
    originalbufbase = BUFBASE
    originalchromiumxwdbuffer = CHROMIUMXWDBUFFER
    originalstatebase = STATEBASE
    originaltelemetrypath = TELEMETRYPATH
    originallasttelemetry = LASTTELEMETRY
    originalsendjson = sendjson
    originalopenoperationscentre = openoperationscentre
    originallocksession = locksession
    originaltakescreenshot = takescreenshot
    replies = []
    createdpaths = []

    def diagnosticreply(cid, obj):
        replies.append(dict(obj))

    def writecolor(path, width, height, color):

        pixel = bytes(color)

        with open(path, "wb") as output:

            row = pixel * int(width)

            for _ in range(int(height)):
                output.write(row)

    def writepatch(path, totalwidth, x, y, width, height, color):

        row = bytes(color) * int(width)

        with open(path, "r+b") as output:

            for offsety in range(int(height)):
                output.seek(((int(y) + offsety) * int(totalwidth) + int(x)) * 4)
                output.write(row)

    def diagnosticwindow(wid, role, x, y, width, height, color, title):

        path = os.path.join(diagnosticbase, f"{wid}.raw")
        writecolor(path, width, height, color)
        createdpaths.append(path)
        return {
            "id": int(wid),
            "cid": 1,
            "title": str(title),
            "role": str(role),
            "current": "diagnostic",
            "path": "",
            "x": int(x),
            "y": int(y),
            "w": int(width),
            "h": int(height),
            "mapped": True,
            "buffer": path,
            "damage": [[0, 0, int(width), int(height)]],
            "opacity": 1.0,
            "scale": 1.0,
            "shadow": False,
            "pixel_alpha": False,
            "gpu_commands": [],
            "_gpu_commands_pending": None,
            "_managed_only": False,
            "_gpu_generation": 0,
            "_gpu_command_generation": 0,
            "_gpu_texture": None,
            "_gpu_scene": None,
            "_gpu_scene_damage": [],
            "_gpu_layers": {},
            "_gpu_width": 0,
            "_gpu_height": 0,
            "_telemetry_scene_commits": 0,
            "_telemetry_scene_clears": 0,
            "_telemetry_batch_commits": 0,
            "_telemetry_patch_commits": 0,
            "_telemetry_damage_pixels": 0,
            "_telemetry_composited_pixels": 0,
            "_telemetry_cpu_damage_bytes": 0,
            "_telemetry_gpu_upload_bytes": 0,
            "_telemetry_gpu_draw_calls": 0,
            "_telemetry_gpu_frames": 0,
            "_telemetry_scene_texture_renders": 0,
            "_telemetry_scene_texture_hits": 0,
            "_telemetry_fallbacks": 0,
            "_telemetry_last_fallback": "",
            "pid": None,
        }

    def near(name, actual, expected, tolerance=3):

        values = [int(value) for value in actual[:len(expected)]]

        if any(abs(value - int(wanted)) > int(tolerance) for value, wanted in zip(values, expected)):
            raise RuntimeError(f"{name} expected {list(expected)} got {values}")

        result["checks"][name] = values

    def paint(regions=None):

        if regions is None:
            regions = [[0, 0, SCREENW, SCREENH]]

        if not gpupaintregions(regions):
            raise RuntimeError("managed compositor did not paint a diagnostic frame")

    try:

        os.makedirs(diagnosticbase, exist_ok=True)
        BUFBASE = diagnosticbase
        STATEBASE = diagnosticbase
        TELEMETRYPATH = os.path.join(diagnosticbase, "graphics-telemetry.json")
        LASTTELEMETRY = time.monotonic()
        globals()["sendjson"] = diagnosticreply
        SCREENW = 2560
        SCREENH = 1440
        WORKX = 0
        WORKY = 0
        WORKW = SCREENW
        WORKH = SCREENH
        POINTERX = SCREENW // 2
        POINTERY = SCREENH // 2
        STARTUPCURSORWAIT = False
        BOOTCURSORHIDE = False
        CURSORENABLED = False
        GPUFAILED = False
        GPUCOMPOSITOR = True
        GPUSHADOWS = False
        GPUTRANSITIONS = False
        GPUOCCLUSION = True
        GPUCOMMANDERRORS = 0
        GPUCOMMANDLASTERROR = ""
        GPUFULLFRAMEFALLBACKS = 0
        FOCUSWID = None
        windows.clear()
        zorder.clear()
        DAMAGERECTS.clear()
        OVERLAYRECTS.clear()
        OVERLAYACTIVE.clear()
        clients.clear()
        clients[1] = {
            "kind": "client",
            "id": 1,
            "sock": None,
            "inbuf": b"",
            "outbuf": bytearray(),
            "pending_motion": None,
            "motion_next_at": 0.0,
            "events": 0,
            "windows": [1, 2, 3],
            "subs": set(),
        }

        pickerfilters = pickerfilterrequest([
            {"id": "text", "label": "text", "extensions": ["txt", ".MD", "../bad"]},
            {"id": "all", "label": "all", "extensions": ["*"]},
        ])
        if (
            len(pickerfilters) != 2
            or pickerfilters[0].get("extensions") != [".txt", ".md"]
            or not pickerfilematches("/diagnostic/report.TXT", pickerfilters)
            or not pickerfilematches("/diagnostic/image.png", pickerfilters)
            or not modalwindow({"modal_child": True})
            or not modalwindow({"standard_dialog": True})
            or modalwindow({})
        ):
            raise RuntimeError("Array picker protocol validation is invalid")
        result["checks"]["array_picker_protocol"] = {
            "version": PICKERVERSION,
            "modes": list(PICKERMODES),
            "pid_bound": True,
            "modal": True,
        }

        opengloffscreen(SCREENW, SCREENH)
        gpusetframebudget(33.0)
        originaluiscale = GPUUISCALE
        GPUUISCALE = 1.0
        automaticuiscale = squarerootscale()
        GPUUISCALE = 1.5
        configureduiscale = squarerootscale()
        GPUUISCALE = 0.5
        reduceduiscale = squarerootscale()
        GPUUISCALE = originaluiscale

        if (
            abs(configureduiscale - automaticuiscale * 1.5) > 0.001 or
            abs(reduceduiscale - automaticuiscale * 0.5) > 0.001
        ):
            raise RuntimeError(
                "configured UI scale did not multiply automatic display scaling")

        result["checks"]["high_dpi_ui_scale"] = {
            "automatic": round(automaticuiscale, 4),
            "configured": round(configureduiscale, 4),
            "reduced": round(reduceduiscale, 4),
        }
        applyuiscale()
        loadcursor()

        if not gpubegin((0, 0, 0, 255)):
            raise RuntimeError("controlled 3D diagnostic could not start an OpenGL frame")

        threedtarget = gputargetcreate(256, 256, owner="diagnostic-3d")
        threedstate = gputargetbegin(threedtarget, clearcolor=(0, 0, 0, 255), clear=True)

        try:
            beforethreed = gpumetrics()
            gpudrawscene3d({
                "camera": {"position": [0, 0, 6], "target": [0, 0, 0], "up": [0, 1, 0], "projection": "perspective", "fov": 50, "near": 0.1, "far": 100},
                "ambient": {"color": [255, 255, 255, 255], "intensity": 1.0},
                "light": {"direction": [-0.4, -0.8, -0.6], "color": [255, 255, 255, 255], "intensity": 0.0},
                "fog": {"enabled": False, "color": [0, 0, 0, 255], "near": 5.0, "far": 14.0},
                "postprocess": "none",
                "antialias": "analytic",
                "meshes": [
                    {"primitive": "cube", "position": [0, 0, 0], "rotation": [0, 0, 0], "scale": [1, 1, 1], "rotation_speed": [0, 0, 0], "wireframe": False, "material": {"color": [255, 0, 0, 255], "opacity": 1.0, "shininess": 24, "unlit": True}},
                    {"primitive": "cube", "position": [0, 0, -2], "rotation": [0, 0, 0], "scale": [1, 1, 1], "rotation_speed": [0, 0, 0], "wireframe": False, "material": {"color": [0, 255, 0, 255], "opacity": 1.0, "shininess": 24, "unlit": True}},
                    {"primitive": "cube", "position": [2.4, 0, -0.5], "rotation": [0, 0, 0], "scale": [0.65, 0.65, 0.65], "rotation_speed": [0, 0, 0], "wireframe": True, "line_width": 2.0, "material": {"color": [255, 255, 255, 255], "opacity": 1.0, "shininess": 24, "unlit": True}},
                ],
            }, 0, 0, 256, 256, clip=[0, 0, 256, 256])
            near("controlled_3d_depth", gpureadpixel(128, 128), [255, 0, 0, 255])

            gpudrawline(32, 24, 96, 24, [255, 255, 255, 255], width=2.0, clip=[0, 0, 256, 256])
            linecoverage = [int(gpureadpixel(64, sampley)[0]) for sampley in range(19, 30)]
            afterthreed = gpumetrics()

            if int(afterthreed.get("mesh_3d_draws", 0)) - int(beforethreed.get("mesh_3d_draws", 0)) != 3:
                raise RuntimeError("controlled 3D diagnostic did not draw all bounded meshes")

            if int(afterthreed.get("mesh_3d_depth_clears", 0)) <= int(beforethreed.get("mesh_3d_depth_clears", 0)):
                raise RuntimeError("controlled 3D diagnostic did not clear its managed depth buffer")

            if int(afterthreed.get("aa_2d_line_segments", 0)) <= int(beforethreed.get("aa_2d_line_segments", 0)):
                raise RuntimeError("managed 2D line diagnostic did not use the analytic line renderer")

            if max(linecoverage) < 180 or min(linecoverage) > 5 or not any(5 < value < 250 for value in linecoverage):
                raise RuntimeError(f"managed 2D line diagnostic did not produce smooth edge coverage {linecoverage}")

            if int(afterthreed.get("aa_3d_wire_segments", 0)) <= int(beforethreed.get("aa_3d_wire_segments", 0)):
                raise RuntimeError("controlled 3D wireframe diagnostic did not use analytic triangle ribbons")

            if int(afterthreed.get("aa_analytic_scenes", 0)) <= int(beforethreed.get("aa_analytic_scenes", 0)):
                raise RuntimeError("controlled 3D diagnostic did not honor analytic antialiasing")

            result["checks"]["controlled_3d_meshes"] = {
                "draws": 3,
                "triangles": int(afterthreed.get("mesh_3d_triangles", 0)) - int(beforethreed.get("mesh_3d_triangles", 0)),
                "depth": True,
                "analytic_wire_segments": int(afterthreed.get("aa_3d_wire_segments", 0)) - int(beforethreed.get("aa_3d_wire_segments", 0)),
            }
            result["checks"]["analytic_2d_line_coverage"] = linecoverage

            gpudrawrect(0, 128, 64, 64, [0, 0, 255, 255], clip=[0, 0, 256, 256])
            beforequality = gpumetrics()
            gpudrawscene3d({
                "camera": {"position": [0, 0, 6], "target": [0, 0, 0], "up": [0, 1, 0], "projection": "perspective", "fov": 50, "near": 0.1, "far": 100},
                "ambient": {"color": [255, 255, 255, 255], "intensity": 1.0},
                "light": {"direction": [-0.4, -0.8, -0.6], "color": [255, 255, 255, 255], "intensity": 0.0},
                "fog": {"enabled": False, "color": [0, 0, 0, 255], "near": 5.0, "far": 14.0},
                "postprocess": "none",
                "antialias": "quality",
                "meshes": [
                    {"primitive": "cube", "position": [0, 0, 0], "rotation": [0, 0, 0], "scale": [1, 1, 1], "rotation_speed": [0, 0, 0], "wireframe": False, "material": {"color": [255, 0, 0, 255], "opacity": 1.0, "shininess": 24, "unlit": True}},
                ],
            }, 0, 128, 64, 64, clip=[0, 128, 64, 64])
            afterquality = gpumetrics()
            near("quality_3d_center", gpureadpixel(32, 160), [255, 0, 0, 255])
            near("quality_3d_transparent_background", gpureadpixel(2, 130), [0, 0, 255, 255])

            if int(afterquality.get("aa_supersample_scenes", 0)) <= int(beforequality.get("aa_supersample_scenes", 0)):
                raise RuntimeError("controlled 3D quality diagnostic did not use the supersample target")

            if int(afterquality.get("aa_target_count", 0)) < 1 or int(afterquality.get("aa_target_bytes", 0)) < 1:
                raise RuntimeError("controlled 3D quality diagnostic did not retain a bounded supersample target")

            if int(afterquality.get("aa_quality_fallbacks", 0)) != int(beforequality.get("aa_quality_fallbacks", 0)):
                raise RuntimeError("controlled 3D quality diagnostic unexpectedly fell back")

            result["checks"]["controlled_3d_quality_supersampling"] = {
                "scale": 2,
                "target_bytes": int(afterquality.get("aa_target_bytes", 0)),
                "resolve_ms": float(afterquality.get("aa_supersample_resolve_ms", 0.0)) - float(beforequality.get("aa_supersample_resolve_ms", 0.0)),
                "transparent_background": True,
            }

        finally:
            gputargetend(threedstate)
            gpuend(present=False)
            gputargetdestroy(threedtarget)

        desktop = diagnosticwindow(1, "desktop", 0, 0, SCREENW, SCREENH, (30, 20, 10, 255), "desktop")
        first = diagnosticwindow(2, "window", 300, 300, 800, 600, (0, 0, 255, 255), "first")
        second = diagnosticwindow(3, "window", 650, 500, 900, 650, (0, 255, 0, 255), "second")
        first["pid"] = 4242
        windows.update({1: desktop, 2: first, 3: second})
        zorder.extend([1, 2, 3])
        writegraphicsstate()
        createdpaths.append(os.path.join(STATEBASE, "graphics.json"))

        with open(os.path.join(STATEBASE, "graphics.json"), encoding="utf-8") as stream:
            graphicsstate = json.load(stream)

        firsttelemetry = next(
            (
                value
                for value in graphicsstate.get("window_telemetry", {}).get("windows", [])
                if int(value.get("id", 0)) == 2
            ),
            {},
        )

        if float(graphicsstate.get("sampled", 0.0)) <= 0.0 or int(firsttelemetry.get("pid", 0)) != 4242:
            raise RuntimeError("graphics state did not expose sampled per-process GPU telemetry")

        result["checks"]["gpu_process_telemetry"] = {
            "pid": int(firsttelemetry.get("pid", 0)),
            "sampled": True,
        }
        FOCUSWID = 2
        shortcutcalls = []

        def diagnosticopenoperationscentre():
            shortcutcalls.append(True)

        globals()["openoperationscentre"] = diagnosticopenoperationscentre
        replies.clear()

        for state in ("down", "repeat", "up"):
            handleinputevent({
                "kind": "key",
                "key": "ESC",
                "state": state,
                "mods": {"ctrl": True, "shift": True},
            })

        if len(shortcutcalls) != 1 or replies:
            raise RuntimeError(
                "Ctrl+Shift+Esc was not handled as an exclusive global Operations Centre shortcut")

        result["checks"]["operations_centre_global_shortcut"] = {
            "launches": len(shortcutcalls),
            "focused_window_events": len(replies),
        }
        globals()["openoperationscentre"] = originalopenoperationscentre

        screenshotcalls = []

        def diagnostictakescreenshot():
            screenshotcalls.append(True)
            return True

        globals()["takescreenshot"] = diagnostictakescreenshot
        replies.clear()

        for state in ("down", "repeat", "up"):
            handleinputevent({
                "kind": "key",
                "key": "PRTSCR",
                "state": state,
                "mods": {},
            })

        if len(screenshotcalls) != 1 or replies:
            raise RuntimeError(
                "Print Screen was not handled as an exclusive global screenshot shortcut")

        result["checks"]["print_screen_global_shortcut"] = {
            "captures": len(screenshotcalls),
            "focused_window_events": len(replies),
        }
        globals()["takescreenshot"] = originaltakescreenshot

        lockcalls = []

        def diagnosticlocksession():
            lockcalls.append(True)

        globals()["locksession"] = diagnosticlocksession
        WINSTATE["held"] = False
        WINSTATE["used"] = False
        WINSTATE["suppresstext"] = []
        replies.clear()

        handleinputevent({
            "kind": "key",
            "key": "LWIN",
            "state": "down",
            "mods": {"win": True},
        })

        for state in ("down", "repeat", "up"):
            handleinputevent({
                "kind": "key",
                "key": "L",
                "state": state,
                "mods": {"win": True},
            })

        handleinputevent({
            "kind": "key",
            "key": "LWIN",
            "state": "up",
            "mods": {},
        })

        if len(lockcalls) != 1 or replies:
            raise RuntimeError(
                "Win+L was not handled as an exclusive session lock shortcut")

        result["checks"]["session_lock_global_shortcut"] = {
            "launches": len(lockcalls),
            "focused_window_events": len(replies),
        }
        globals()["locksession"] = originallocksession

        browser = diagnosticwindow(7, "window", 40, 40, 64, 48, (0, 0, 0, 255), "chromium")
        browser["path"] = "/the one/build/chromium/chromium.py"
        browser["_owned_buffer"] = browser["buffer"]
        browser["_external_buffer"] = False
        browser["buffer_offset"] = 0
        browser["buffer_stride"] = int(browser["w"]) * 4
        browser["buffer_source_width"] = int(browser["w"])
        browser["buffer_source_height"] = int(browser["h"])
        externalpath = os.path.join(diagnosticbase, "chromium-xwd.raw")
        externaloffset = 128
        externalsourcewidth = 32
        externalsourceheight = 24
        externalstride = 40 * 4

        with open(externalpath, "wb") as external:
            external.write(b"\0" * externaloffset)
            for _ in range(externalsourceheight):
                external.write(bytes((25, 50, 75, 0)) * externalsourcewidth)
                external.write(b"\0" * ((40 - externalsourcewidth) * 4))

        createdpaths.append(externalpath)
        CHROMIUMXWDBUFFER = externalpath
        windows[7] = browser
        clients[1]["windows"].append(7)
        replies.clear()
        setwindowexternalbuffer(1, {
            "winid": 7,
            "path": externalpath,
            "offset": externaloffset,
            "stride": externalstride,
            "source_width": externalsourcewidth,
            "source_height": externalsourceheight,
            "format": "BGRA32",
        })

        if (
            not browser.get("_external_buffer")
            or browser.get("buffer") != externalpath
            or not replies
            or replies[-1].get("op") != "WINDOW_BUFFER_ATTACHED"
        ):
            raise RuntimeError("validated Chromium external buffer was not attached")

        beginscaledfileframe()
        firstscaled = blitwindowregion(browser, [40, 40, 16, 16])
        secondscaled = blitwindowregion(browser, [72, 64, 16, 16])
        scaledmetrics = endscaledfileframe()

        if (
            not firstscaled
            or not secondscaled
            or int(scaledmetrics.get("source_reads", 0)) != 1
            or int(scaledmetrics.get("cache_hits", 0)) != 1
            or int(scaledmetrics.get("regions", 0)) != 2
        ):
            raise RuntimeError(
                "scaled Chromium CPU fallback reread its full source "
                f"{scaledmetrics}"
            )

        texture = gpuwindowtexture(browser)

        textureinfo = gputextureinfo(texture) if texture is not None else None

        if (
            textureinfo is None
            or int(textureinfo.get("width", 0)) != externalsourcewidth
            or int(textureinfo.get("height", 0)) != externalsourceheight
        ):
            raise RuntimeError("Chromium external buffer was not uploaded with its source offset")

        browser["damage"] = []
        DAMAGERECTS.clear()
        markdamage(1, {
            "winid": 7,
            "rect": [
                externalsourcewidth // 2,
                externalsourceheight // 2,
                externalsourcewidth // 2,
                externalsourceheight // 2,
            ],
        })
        expectedscreen = [70, 62, 34, 26]

        if (
            browser.get("damage") != [[16, 12, 16, 12]]
            or DAMAGERECTS != [expectedscreen]
        ):
            raise RuntimeError(
                "Chromium source damage was not transformed to logical output "
                f"damage={browser.get('damage')} screen={DAMAGERECTS}"
            )

        scaledmapping = {
            "_external_buffer": True,
            "buffer_source_width": 2560,
            "buffer_source_height": 1070,
            "w": 3440,
            "h": 1440,
        }
        if (
            windowbufferrecttooutput(
                scaledmapping, [1280, 535, 1, 1], filtermargin=1,
            ) != [1718, 718, 5, 5]
            or windowbufferrecttooutput(
                scaledmapping, [0, 0, 1, 1], filtermargin=1,
            ) != [0, 0, 3, 3]
            or windowbufferrecttooutput(
                scaledmapping, [2559, 1069, 1, 1], filtermargin=1,
            ) != [3437, 1437, 3, 3]
        ):
            raise RuntimeError(
                "scaled Chromium filter-footprint damage mapping is incorrect"
            )

        browser["damage"] = []
        DAMAGERECTS.clear()
        resizewindow(1, {"winid": 7, "w": 96, "h": 72})

        if (
            browser.get("_gpu_texture") != texture
            or windowbufferdimensions(browser)
            != (externalsourcewidth, externalsourceheight)
        ):
            raise RuntimeError(
                "logical Chromium resize recreated or resized its source texture"
            )

        setwindowexternalbuffer(1, {"winid": 7}, attached=False)

        if (
            browser.get("_external_buffer")
            or browser.get("buffer") != browser.get("_owned_buffer")
            or not os.path.exists(externalpath)
            or replies[-1].get("op") != "WINDOW_BUFFER_DETACHED"
        ):
            raise RuntimeError("Chromium external buffer detach did not restore the owned buffer")

        result["checks"]["chromium_external_buffer"] = {
            "offset": externaloffset,
            "stride": externalstride,
            "source": [externalsourcewidth, externalsourceheight],
            "output": [96, 72],
            "damage_output": expectedscreen,
            "filter_footprint": True,
            "scaled_cpu_frame": scaledmetrics,
            "logical_resize_reused_texture": True,
            "detached": True,
        }

        second["drop_types"] = {"files", "text", "html", "image"}
        clients[2] = {
            "kind": "client", "id": 2, "sock": None, "inbuf": b"",
            "outbuf": bytearray(), "pending_motion": None, "motion_next_at": 0.0,
            "events": 0, "windows": [], "subs": {"vbox_dnd"}, "integration": "guestadditions",
            "identity": processidentity(os.getpid()),
            "capabilities": {"guest_integration"},
        }
        replies.clear()
        vboxdndhost(2, {"op": "VBOX_DND_HOST_ENTER", "format": "text/uri-list"})
        vboxdndhost(2, {"op": "VBOX_DND_HOST_MOVE", "x": 700, "y": 550})
        vboxdndhost(2, {"op": "VBOX_DND_HOST_DROP", "x": 700, "y": 550})
        vboxdndhost(2, {"op": "VBOX_DND_HOST_DATA", "kind": "files", "paths": [second["buffer"]]})
        dropops = [value.get("op") for value in replies]
        for required in ("DND_ENTER", "DND_MOVE", "DND_DROP_PENDING", "DND_DROP", "DND_LEAVE"):
            if required not in dropops:
                raise RuntimeError(f"VirtualBox host drag route omitted {required}")
        replies.clear()
        vboxdndguest(1, {"op": "DND_GUEST_START", "winid": 3, "kind": "files", "paths": [second["buffer"]]})
        if not any(value.get("op") == "VBOX_DND_GUEST_START" for value in replies):
            raise RuntimeError("VirtualBox guest drag was not delivered to the integration subscriber")
        result["checks"]["virtualbox_drag_and_drop_route"] = {
            "host": dropops,
            "guest": [value.get("op") for value in replies],
        }
        clients.pop(2, None)

        initialmanaged = diagnosticwindow(6, "diagnostic", 1700, 100, 320, 180, (0, 0, 0, 255), "initial managed")
        windows[6] = initialmanaged
        clients[1]["windows"].append(6)
        DAMAGERECTS.clear()
        repliesbeforeinitial = len(replies)
        graphicsscene(1, {
            "winid": 6,
            "damage": [[16, 120, 12, 24]],
            "commands": [
                {"id": "initial-background", "kind": "rectangle", "rect": [0, 0, 320, 180], "color": [0, 0, 0, 255]},
                {"id": "initial-label", "kind": "text", "x": 16, "y": 40, "text": "first scene", "size": 24, "font": WINDOWFONT, "color": [255, 255, 255, 255]},
            ],
        })
        initialreplies = replies[repliesbeforeinitial:]

        if not initialreplies or initialreplies[-1].get("op") != "GRAPHICS_COMMITTED":
            raise RuntimeError(f"initial managed scene did not commit {initialreplies}")

        if [1700, 100, 320, 180] not in DAMAGERECTS:
            raise RuntimeError(f"initial managed scene preserved partial damage {DAMAGERECTS}")

        result["checks"]["initial_managed_full_damage"] = True
        clients[1]["windows"].remove(6)
        gpuwindowrelease(initialmanaged)
        windows.pop(6, None)
        DAMAGERECTS.clear()

        paint()
        fullcomposition = gpuframestats()
        near("desktop", gpureadpixel(2300, 1200), [10, 20, 30, 255])
        near("first_window", gpureadpixel(400, 400), [255, 0, 0, 255])
        near("initial_stacking", gpureadpixel(1000, 800), [0, 255, 0, 255])

        cursorinfo = CURSORS.get("arrow") or {}
        cursordata = cursorinfo.get("data") or b""
        cursorwidth = int(cursorinfo.get("w", 0))
        cursorheight = int(cursorinfo.get("h", 0))
        cursorpixel = None

        for offset in range(0, len(cursordata) - 3, 4):

            if int(cursordata[offset + 3]) == 255:
                cursorpixel = (offset // 4 % cursorwidth, offset // 4 // cursorwidth, [int(cursordata[offset + 2]), int(cursordata[offset + 1]), int(cursordata[offset]), 255])
                break

        if cursorwidth < 1 or cursorheight < 1 or cursorpixel is None:
            raise RuntimeError("the 1440p arrow cursor did not provide an opaque diagnostic pixel")

        CURSORENABLED = True
        POINTERX = 2300
        POINTERY = 100
        cursorold = pointercursorbox(POINTERX, POINTERY, "arrow")
        paint([cursorold])
        near("cursor_partial", gpureadpixel(POINTERX + cursorpixel[0], POINTERY + cursorpixel[1]), cursorpixel[2])
        POINTERX = 2400
        POINTERY = 180
        cursornew = pointercursorbox(POINTERX, POINTERY, "arrow")
        paint([cursorold, cursornew])
        near("cursor_old_region", gpureadpixel(2300 + cursorpixel[0], 100 + cursorpixel[1]), [10, 20, 30, 255])
        near("cursor_new_region", gpureadpixel(POINTERX + cursorpixel[0], POINTERY + cursorpixel[1]), cursorpixel[2])
        CURSORENABLED = False
        paint([cursornew])
        near("cursor_removed", gpureadpixel(POINTERX + cursorpixel[0], POINTERY + cursorpixel[1]), [10, 20, 30, 255])

        oldsecond = gpuvisualrect(second)
        second["x"] = 1400
        second["y"] = 600
        newsecond = gpuvisualrect(second)
        paint([oldsecond, newsecond])
        near("move_old_region", gpureadpixel(1000, 800), [255, 0, 0, 255])
        near("move_new_region", gpureadpixel(1500, 700), [0, 255, 0, 255])

        beforepartial = int(gpumetrics().get("partial_uploads", 0))
        writepatch(first["buffer"], first["w"], 50, 50, 40, 40, (0, 255, 255, 255))
        first["damage"] = [[50, 50, 40, 40]]
        beforepartialframes = int(gpumetrics().get("partial_frames", 0))
        paint([[350, 350, 40, 40]])
        partialcomposition = gpuframestats()
        near("partial_damage", gpureadpixel(360, 360), [255, 255, 0, 255])
        near("partial_preserved", gpureadpixel(2400, 1300), [10, 20, 30, 255])

        if int(gpumetrics().get("partial_uploads", 0)) <= beforepartial:
            raise RuntimeError("partial damage did not produce a partial texture upload")

        if int(gpumetrics().get("partial_frames", 0)) <= beforepartialframes:
            raise RuntimeError("partial damage did not produce a partial compositor frame")

        if int(partialcomposition.get("draw_calls", 0)) >= int(fullcomposition.get("draw_calls", 0)):
            raise RuntimeError(f"partial composition did not reduce draw calls {fullcomposition.get('draw_calls')} -> {partialcomposition.get('draw_calls')}")

        if int(partialcomposition.get("damage_pixels", 0)) >= SCREENW * SCREENH:
            raise RuntimeError("partial composition unexpectedly covered the complete framebuffer")

        result["checks"]["partial_upload"] = True
        result["checks"]["partial_composition"] = {
            "full_draw_calls": int(fullcomposition.get("draw_calls", 0)),
            "partial_draw_calls": int(partialcomposition.get("draw_calls", 0)),
            "draw_calls_saved": int(fullcomposition.get("draw_calls", 0)) - int(partialcomposition.get("draw_calls", 0)),
            "damage_pixels": int(partialcomposition.get("damage_pixels", 0)),
            "frame_pixels": int(SCREENW * SCREENH),
        }
        uploadmetrics = gpumetrics()
        stagingpeak = int(uploadmetrics.get("maximum_upload_staging_bytes", 0))

        if stagingpeak < 1 or stagingpeak > int(GPUUPLOADSTAGINGLIMIT):
            raise RuntimeError(f"CPU upload staging was not bounded {stagingpeak}/{GPUUPLOADSTAGINGLIMIT}")

        result["checks"]["bounded_upload_staging"] = {
            "peak_bytes": stagingpeak,
            "limit_bytes": int(GPUUPLOADSTAGINGLIMIT),
            "upload_calls": int(uploadmetrics.get("upload_calls", 0)),
        }

        first["damage"] = []
        coalescesbefore = int(first.get("_telemetry_cpu_damage_coalesces", 0))

        for _ in range(1000):
            markdamage(1, {"winid": 2, "rect": [50, 50, 40, 40]})

        if len(first.get("damage", [])) != 1:
            raise RuntimeError(f"repeated CPU damage was not coalesced {first.get('damage')}")

        coalesced = int(first.get("_telemetry_cpu_damage_coalesces", 0)) - coalescesbefore

        if coalesced != 999:
            raise RuntimeError(f"CPU damage coalescing telemetry was incorrect {coalesced}/999")

        result["checks"]["cpu_damage_coalescing"] = {"events": 1000, "coalesces": coalesced, "pending": 1}
        first["damage"] = []
        DAMAGERECTS.clear()

        beforefullfallback = int(GPUFULLFRAMEFALLBACKS)
        gpuinvalidatesurface()
        paint([[350, 350, 4, 4]])

        if int(GPUFULLFRAMEFALLBACKS) <= beforefullfallback:
            raise RuntimeError("invalid persistent surface did not select a full GPU frame")

        near("full_frame_fallback", gpureadpixel(2400, 1300), [10, 20, 30, 255])

        movewindow(1, {"winid": 2, "x": -300, "y": 300})

        if first["x"] != -300:
            raise RuntimeError(f"partly off-screen move was unexpectedly constrained to {first['x']}")

        paint()
        near("partially_offscreen_window", gpureadpixel(50, 400), [255, 0, 0, 255])
        movewindow(1, {"winid": 2, "x": -100000, "y": 100000})
        lefttitle = framehittest(WORKX + max(1, BTNWH // 2), WORKY + WORKH - max(1, TITLEH // 4), first)

        if lefttitle != ("title", None):
            raise RuntimeError("left/bottom off-screen clamp did not retain a reachable titlebar")

        movewindow(1, {"winid": 2, "x": 100000, "y": -100000})
        righttitle = framehittest(WORKX + WORKW - max(1, BTNWH // 2), WORKY + max(1, TITLEH // 4), first)

        if righttitle != ("title", None):
            raise RuntimeError("right/top off-screen clamp did not retain a reachable titlebar")

        result["checks"]["offscreen_titlebar_recovery"] = True
        movewindow(1, {"winid": 2, "x": 300, "y": 300})

        imagepath = os.path.join(diagnosticbase, "managed-image.raw")
        writecolor(imagepath, 4, 4, (255, 0, 0, 255))
        createdpaths.append(imagepath)
        graphicsbegin(1, {"winid": 2})
        graphicsappend(1, {
            "winid": 2,
            "rect": [100, 100, 120, 80],
            "color": [255, 0, 255, 255],
        }, "rectangle")
        graphicsappend(1, {
            "winid": 2,
            "path": imagepath,
            "source_width": 4,
            "source_height": 4,
            "rect": [260, 100, 80, 80],
            "format": "BGRA32",
            "revision": 1,
        }, "image")
        graphicsappend(1, {
            "winid": 2,
            "x": 100,
            "y": 220,
            "text": "managed GPU text",
            "size": 24,
            "color": "#FFFFFF",
        }, "text")
        graphicscommit(1, {"winid": 2})

        if any(reply.get("op") == "ERROR" for reply in replies):
            raise RuntimeError(f"managed graphics protocol returned an error {replies}")

        paint()
        managedfulldraws = int(gpuframestats().get("draw_calls", 0))
        near("managed_rectangle", gpureadpixel(420, 420), [255, 0, 255, 255])
        near("managed_image", gpureadpixel(580, 420), [0, 0, 255, 255])

        if len(first.get("gpu_commands", [])) != 3 or first["gpu_commands"][1].get("revision") != 1:
            raise RuntimeError("managed graphics commit did not publish all commands")

        result["graphics_api"] = graphicscapabilities()
        result["graphics_api"]["committed_commands"] = len(first["gpu_commands"])
        repliesbeforebatch = len(replies)
        graphicsscene(1, {
            "winid": 2,
            "damage": [[100, 100, 120, 80]],
            "commands": [
                {
                    "kind": "rectangle",
                    "rect": [100, 100, 120, 80],
                    "color": [0, 255, 255, 255],
                },
                {
                    "kind": "image",
                    "path": imagepath,
                    "source_width": 4,
                    "source_height": 4,
                    "rect": [260, 100, 80, 80],
                    "format": "BGRA32",
                    "revision": 2,
                },
                {
                    "kind": "text",
                    "x": 100,
                    "y": 220,
                    "text": "managed GPU text",
                    "size": 24,
                    "color": "#FFFFFF",
                },
            ],
        })
        batchreplies = replies[repliesbeforebatch:]

        if len(batchreplies) != 1 or batchreplies[0].get("op") != "GRAPHICS_COMMITTED" or not batchreplies[0].get("batch"):
            raise RuntimeError(f"atomic managed scene returned unexpected replies {batchreplies}")

        paint([[400, 400, 120, 80]])
        managedpartialdraws = int(gpuframestats().get("draw_calls", 0))
        near("managed_batch", gpureadpixel(420, 420), [0, 255, 255, 255])

        if managedpartialdraws >= managedfulldraws:
            raise RuntimeError(f"managed command damage culling did not reduce draw calls {managedfulldraws} -> {managedpartialdraws}")

        result["checks"]["managed_command_damage_culling"] = {
            "full_draw_calls": managedfulldraws,
            "partial_draw_calls": managedpartialdraws,
            "draw_calls_saved": managedfulldraws - managedpartialdraws,
        }
        committed = list(first.get("gpu_commands", []))
        repliesbeforeinvalid = len(replies)
        graphicsscene(1, {
            "winid": 2,
            "damage": [[0, 0, 10, 10]],
            "commands": [{"kind": "shader", "source": "not allowed"}],
        })
        invalidreplies = replies[repliesbeforeinvalid:]

        if not invalidreplies or invalidreplies[-1].get("code") != "graphics_scene_failed":
            raise RuntimeError("invalid atomic managed scene was not rejected")

        if first.get("gpu_commands", []) != committed:
            raise RuntimeError("invalid atomic managed scene replaced the committed scene")

        result["graphics_api"]["batch_messages"] = len(batchreplies)
        result["graphics_api"]["batch_commands"] = len(committed)
        result["checks"]["atomic_scene"] = True
        uhdwin = {"w": 3840, "h": 2160}
        uhdscene = [
            graphicscommand(uhdwin, {"id": "uhd-background", "rect": [0, 0, 3840, 2160], "color": 0x000000}, "rectangle"),
            graphicscommand(uhdwin, {"id": "uhd-group", "translate": [1920, 1080], "scale": [2.0, 2.0]}, "group"),
            graphicscommand(uhdwin, {"id": "uhd-label", "parent": "uhd-group", "x": 0, "y": 0, "text": "3840x2160", "size": 48, "font": WINDOWFONT}, "text"),
        ]
        graphicsvalidatescene(uhdscene)

        if uhdscene[0].get("rect") != [0, 0, 3840, 2160]:
            raise RuntimeError("4K managed scene geometry was clipped unexpectedly")

        result["checks"]["managed_scene_4k"] = {"resolution": [3840, 2160], "commands": len(uhdscene)}
        repliesbeforev2 = len(replies)
        graphicsscene(1, {
            "winid": 2,
            "commands": [
                {"id": "background", "kind": "rectangle", "rect": [0, 0, 800, 600], "color": [20, 20, 20, 255]},
                {"id": "content", "kind": "group", "translate": [40, 40], "clip": [0, 0, 720, 520]},
                {"id": "group-rectangle", "parent": "content", "kind": "rectangle", "rect": [0, 0, 100, 80], "color": [255, 0, 0, 255]},
                {"id": "rounded", "kind": "rounded_rectangle", "rect": [180, 40, 100, 80], "radius": 18, "color": [0, 0, 255, 255]},
                {"id": "gradient", "kind": "gradient", "rect": [320, 40, 100, 100], "color": [255, 0, 0, 255], "color2": [0, 0, 255, 255]},
                {"id": "circle", "kind": "circle", "cx": 500, "cy": 90, "radius": 40, "color": [0, 255, 0, 255]},
                {"id": "line", "kind": "line", "points": [580, 40, 700, 120], "width": 8, "color": [255, 255, 255, 255]},
                {"id": "border", "kind": "border", "rect": [40, 180, 160, 100], "width": 4, "color": [255, 255, 0, 255]},
            ],
        })
        v2replies = replies[repliesbeforev2:]

        if not v2replies or v2replies[-1].get("op") != "GRAPHICS_COMMITTED" or not v2replies[-1].get("managed_only"):
            raise RuntimeError(f"managed-only v2 scene did not commit {v2replies}")

        if not first.get("_managed_only") or first.get("_gpu_texture") is not None:
            raise RuntimeError("opaque managed scene retained a redundant CPU backing texture")

        preparedbefore = int(GPUSCENEUPDATESCOMPLETED)
        paint([gpuvisualrect(first)])

        if int(GPUSCENEUPDATESCOMPLETED) <= preparedbefore:
            raise RuntimeError("dirty managed scene was not prepared by the frame scheduler")

        result["checks"]["managed_scene_update_scheduler"] = {
            "queued": int(GPUSCENEUPDATESQUEUED),
            "completed": int(GPUSCENEUPDATESCOMPLETED),
            "peak": int(GPUSCENEUPDATEPEAK),
        }
        near("managed_only_background", gpureadpixel(1050, 780), [20, 20, 20, 255])
        near("managed_group_transform", gpureadpixel(350, 350), [255, 0, 0, 255])
        near("managed_rounded_rectangle", gpureadpixel(530, 380), [0, 0, 255, 255])
        gradienttop = gpureadpixel(670, 350)
        gradientbottom = gpureadpixel(670, 430)

        if int(gradienttop[0]) <= int(gradienttop[2]) or int(gradientbottom[2]) <= int(gradientbottom[0]):
            raise RuntimeError(f"managed gradient did not interpolate vertically {gradienttop} {gradientbottom}")

        result["checks"]["managed_gradient"] = {"top": gradienttop, "bottom": gradientbottom}
        near("managed_circle", gpureadpixel(800, 390), [0, 255, 0, 255])
        near("managed_line", gpureadpixel(940, 380), [255, 255, 255, 255])
        cacherenders = int(first.get("_telemetry_scene_texture_renders", 0))
        cachehits = int(first.get("_telemetry_scene_texture_hits", 0))
        paint([[340, 340, 20, 20]])

        if int(first.get("_telemetry_scene_texture_renders", 0)) != cacherenders or int(first.get("_telemetry_scene_texture_hits", 0)) <= cachehits:
            raise RuntimeError("unchanged managed scene was not reused from its GPU texture")

        near("managed_scene_texture_cache", gpureadpixel(350, 350), [255, 0, 0, 255])
        generation = int(first.get("_gpu_command_generation", 0))
        partialrenders = int(first.get("_telemetry_scene_texture_partial_renders", 0))
        commandculls = int(first.get("_telemetry_scene_commands_culled", 0))
        repliesbeforepatch = len(replies)
        graphicspatch(1, {
            "winid": 2,
            "generation": generation,
            "damage": [[40, 40, 100, 80]],
            "upsert": [
                {"id": "group-rectangle", "parent": "content", "kind": "rectangle", "rect": [0, 0, 100, 80], "color": [0, 255, 0, 255]},
            ],
            "remove": [],
            "order": ["background", "content", "group-rectangle", "rounded", "gradient", "circle", "line", "border"],
        })
        patchreplies = replies[repliesbeforepatch:]

        if not patchreplies or not patchreplies[-1].get("patch") or int(patchreplies[-1].get("generation", 0)) != generation + 1:
            raise RuntimeError(f"retained managed scene patch returned an unexpected reply {patchreplies}")

        paint([[340, 340, 100, 80]])
        near("managed_scene_patch", gpureadpixel(350, 350), [0, 255, 0, 255])

        if int(first.get("_telemetry_scene_texture_partial_renders", 0)) <= partialrenders:
            raise RuntimeError("retained patch did not use partial scene-texture rendering")

        if int(first.get("_telemetry_scene_commands_culled", 0)) <= commandculls:
            raise RuntimeError("retained patch did not cull commands outside its damage")

        result["checks"]["partial_scene_texture"] = {
            "partial_renders": int(first.get("_telemetry_scene_texture_partial_renders", 0)),
            "commands_culled": int(first.get("_telemetry_scene_commands_culled", 0)),
            "damage_pixels": int(first.get("_telemetry_scene_texture_damage_pixels", 0)),
        }
        result["checks"]["managed_only_surface"] = True
        result["checks"]["retained_scene_patch"] = True
        repliesbeforeeffects = len(replies)
        graphicsscene(1, {
            "winid": 2,
            "commands": [
                {"id": "effects-background", "kind": "rectangle", "rect": [0, 0, 800, 600], "color": [20, 20, 20, 255]},
                {"id": "grayscale", "kind": "rectangle", "rect": [40, 40, 80, 80], "color": [255, 0, 0, 255], "effect": "grayscale"},
                {"id": "invert", "kind": "rectangle", "rect": [140, 40, 80, 80], "color": [0, 0, 255, 255], "effect": "invert"},
                {"id": "sepia", "kind": "rectangle", "rect": [240, 40, 80, 80], "color": [120, 160, 220, 255], "effect": "sepia"},
                {"id": "animated", "kind": "rectangle", "rect": [100, 320, 60, 60], "color": [0, 255, 0, 255]},
            ],
        })
        effectreplies = replies[repliesbeforeeffects:]

        if not effectreplies or effectreplies[-1].get("op") != "GRAPHICS_COMMITTED":
            raise RuntimeError(f"controlled effect scene did not commit {effectreplies}")

        paint([gpuvisualrect(first)])
        grayscale = gpureadpixel(360, 360)

        if max(grayscale[:3]) - min(grayscale[:3]) > 3 or not 70 <= int(grayscale[0]) <= 82:
            raise RuntimeError(f"grayscale effect produced an unexpected pixel {grayscale}")

        near("managed_effect_invert", gpureadpixel(460, 360), [255, 255, 0, 255], tolerance=4)
        sepia = gpureadpixel(560, 360)

        if not int(sepia[0]) >= int(sepia[1]) >= int(sepia[2]):
            raise RuntimeError(f"sepia effect produced an unexpected pixel {sepia}")

        result["checks"]["managed_effect_grayscale"] = grayscale
        result["checks"]["managed_effect_sepia"] = sepia
        repliesbeforeanimation = len(replies)
        graphicsanimate(1, {
            "winid": 2,
            "id": "animated",
            "property": "translate",
            "from": [0, 0],
            "to": [100, 0],
            "duration_ms": 100,
            "easing": "linear",
        })
        animationreplies = replies[repliesbeforeanimation:]

        if not animationreplies or animationreplies[-1].get("op") != "GRAPHICS_ANIMATING" or not gpuanimationsactive():
            raise RuntimeError(f"controlled node animation did not start {animationreplies}")

        GPUANIMATIONS[2][0]["start"] = time.monotonic() - 1.0
        paint([gpuvisualrect(first)])
        near("managed_animation_old", gpureadpixel(430, 650), [20, 20, 20, 255])
        near("managed_animation_final", gpureadpixel(530, 650), [0, 255, 0, 255])

        if GPUANIMATIONS.get(2):
            raise RuntimeError("completed controlled node animation remained scheduled")

        result["checks"]["managed_animation"] = True
        repliesbeforelayer = len(replies)
        graphicsscene(1, {
            "winid": 2,
            "commands": [
                {"id": "layer-background", "kind": "rectangle", "rect": [0, 0, 800, 600], "color": [20, 20, 20, 255]},
                {"id": "glass-layer", "kind": "layer", "rect": [100, 100, 200, 150], "opacity": 0.5},
                {"id": "glass-fill", "parent": "glass-layer", "kind": "rectangle", "rect": [100, 100, 200, 150], "color": [255, 0, 0, 255]},
                {"id": "outside-layer", "kind": "rectangle", "rect": [400, 100, 80, 80], "color": [0, 255, 0, 255]},
            ],
        })
        layerreplies = replies[repliesbeforelayer:]

        if not layerreplies or layerreplies[-1].get("op") != "GRAPHICS_COMMITTED":
            raise RuntimeError(f"offscreen layer scene did not commit {layerreplies}")

        paint([gpuvisualrect(first)])
        near("managed_offscreen_layer", gpureadpixel(420, 420), [138, 10, 10, 255], tolerance=6)
        near("managed_layer_sibling", gpureadpixel(720, 420), [0, 255, 0, 255])

        layermetrics = gpumetrics()

        if int(layermetrics.get("render_target_count", 0)) != int(layermetrics.get("aa_target_count", 0)) + 1:
            raise RuntimeError(f"offscreen layer did not retain exactly one non-AA render target {layermetrics.get('render_target_count')}")

        layerhandle = int(first.get("_gpu_layers", {}).get("glass-layer", {}).get("handle", 0))
        layerrenders = int(first.get("_telemetry_layer_texture_renders", 0))
        layerhits = int(first.get("_telemetry_layer_texture_hits", 0))
        graphicspatch(1, {
            "winid": 2,
            "generation": int(first.get("_gpu_command_generation", 0)),
            "upsert": [
                {"id": "outside-layer", "kind": "rectangle", "rect": [400, 100, 80, 80], "color": [0, 255, 255, 255]},
            ],
            "remove": [],
            "order": ["layer-background", "glass-layer", "glass-fill", "outside-layer"],
            "damage": [[0, 0, 800, 600]],
        })
        paint([gpuvisualrect(first)])

        if int(first.get("_gpu_layers", {}).get("glass-layer", {}).get("handle", 0)) != layerhandle:
            raise RuntimeError("an unrelated retained patch recreated the offscreen layer texture")

        if int(first.get("_telemetry_layer_texture_renders", 0)) != layerrenders:
            raise RuntimeError("an unrelated retained patch rerendered unchanged offscreen layer content")

        if int(first.get("_telemetry_layer_texture_hits", 0)) <= layerhits:
            raise RuntimeError("an unrelated retained patch did not reuse the offscreen layer texture")

        result["checks"]["offscreen_layer_cache"] = {
            "handle": layerhandle,
            "renders": int(first.get("_telemetry_layer_texture_renders", 0)),
            "hits": int(first.get("_telemetry_layer_texture_hits", 0)),
        }

        committedlayer = list(first.get("gpu_commands", []))
        repliesbeforecycle = len(replies)
        graphicsscene(1, {
            "winid": 2,
            "commands": [
                {"id": "cycle-a", "kind": "group", "parent": "cycle-b"},
                {"id": "cycle-b", "kind": "group", "parent": "cycle-a"},
            ],
        })
        cyclereplies = replies[repliesbeforecycle:]

        if not cyclereplies or cyclereplies[-1].get("code") != "graphics_scene_failed" or first.get("gpu_commands") != committedlayer:
            raise RuntimeError("cyclic retained scene was not rejected atomically")

        result["checks"]["managed_offscreen_layer"] = True
        result["checks"]["scene_cycle_rejected"] = True
        graphicsclear(1, {"winid": 2})

        cleanupmetrics = gpumetrics()

        if int(cleanupmetrics.get("render_target_count", 0)) != int(cleanupmetrics.get("aa_target_count", 0)):
            raise RuntimeError("offscreen layer render target leaked after scene clear")

        result["checks"]["layer_cleanup"] = True
        tooltip = diagnosticwindow(5, "tooltip", 2000, 200, 180, 80, (255, 255, 255, 255), "tooltip")
        windows[5] = tooltip
        clients[1]["windows"].append(5)
        zorder.append(5)
        tooltipold = gpuvisualrect(tooltip)
        paint([tooltipold])
        near("tooltip_partial", gpureadpixel(2050, 230), [255, 255, 255, 255])
        tooltip["x"] = 2200
        tooltip["y"] = 300
        tooltipnew = gpuvisualrect(tooltip)
        paint([tooltipold, tooltipnew])
        near("tooltip_old_region", gpureadpixel(2050, 230), [10, 20, 30, 255])
        near("tooltip_new_region", gpureadpixel(2250, 330), [255, 255, 255, 255])
        zorder.remove(5)
        clients[1]["windows"].remove(5)
        gpuwindowrelease(tooltip)
        windows.pop(5, None)
        paint([tooltipnew])
        near("tooltip_removed", gpureadpixel(2250, 330), [10, 20, 30, 255])

        second["x"] = 650
        second["y"] = 500
        zorder[:] = [1, 3, 2]
        paint()
        near("raised_first", gpureadpixel(1000, 800), [255, 0, 0, 255])
        zorder[:] = [1, 2, 3]
        paint()
        near("raised_second", gpureadpixel(1000, 800), [0, 255, 0, 255])

        POINTERX = 700
        POINTERY = int(first["y"]) - FRAMEW - max(1, TITLEH // 2)
        inputbutton({"button": 1, "state": "down"})

        if FOCUSWID != 2 or zorder[-1] != 2:
            raise RuntimeError("title-bar activation did not focus and raise the window")

        inputbutton({"button": 1, "state": "up"})
        result["checks"]["title_activation"] = True

        second["mapped"] = False
        paint()
        near("minimized_window", gpureadpixel(1000, 800), [255, 0, 0, 255])
        second["mapped"] = True

        second["x"] = 1400
        second["y"] = 600
        second["w"] = 700
        second["h"] = 500
        writecolor(second["buffer"], second["w"], second["h"], (0, 255, 0, 255))
        gpuwindowrelease(second)
        second["damage"] = [[0, 0, second["w"], second["h"]]]
        paint()
        near("resized_window", gpureadpixel(1500, 700), [0, 255, 0, 255])

        second["opacity"] = 0.5
        paint()
        near("window_opacity", gpureadpixel(1500, 700), [5, 138, 15], tolerance=4)
        second["opacity"] = 1.0
        second["scale"] = 0.75
        paint()
        near("window_scaling", gpureadpixel(1750, 800), [0, 255, 0, 255])
        second["scale"] = 1.0

        GPUSHADOWS = True
        GPUTRANSITIONS = True
        second["shadow"] = True
        second["_gpu_transition_start"] = time.monotonic() - 0.05
        second["_gpu_transition_ms"] = 100

        if not gpuanimationsactive():
            raise RuntimeError("active transition stopped scheduling frames")

        paint()
        second["_gpu_transition_start"] = time.monotonic() - 0.2

        if not gpuanimationsactive():
            raise RuntimeError("expired transition did not schedule its final frame")

        paint()

        if second.get("_gpu_transition_start") is not None:
            raise RuntimeError("final transition frame did not clear transition state")

        if gpuanimationsactive():
            raise RuntimeError("completed transition remained active after its final frame")

        near("transition_final_frame", gpureadpixel(1500, 700), [0, 255, 0, 255])
        second["shadow"] = False
        GPUSHADOWS = False
        result["checks"]["shadow_transition"] = True
        result["checks"]["transition_final_frame"] = True

        startmenuwid = createwindow(1, {
            "w": 320,
            "h": 240,
            "x": 0,
            "y": 1000,
            "title": "start",
            "role": "startmenu",
        })
        createdpaths.append(windows[startmenuwid]["buffer"])
        writecolor(windows[startmenuwid]["buffer"], 320, 240, (0, 0, 0, 255))
        mapwindow(1, {"winid": startmenuwid})

        if windows[startmenuwid].get("_gpu_transition_start") is not None:
            raise RuntimeError("start menu received a non-final automatic transition frame")

        destroywindow(startmenuwid, note="diagnostic")
        result["checks"]["startmenu_final_map"] = True

        chromewid = createwindow(1, {
            "w": 300,
            "h": 200,
            "x": 2100,
            "y": 1000,
            "title": "chrome",
            "role": "window",
        })
        createdpaths.append(windows[chromewid]["buffer"])
        writecolor(windows[chromewid]["buffer"], 300, 200, (255, 255, 255, 255))
        mapwindow(1, {"winid": chromewid})

        if windows[chromewid].get("_gpu_transition_start") is not None:
            raise RuntimeError("normal window map did not begin at its final frame")

        paint([gpuvisualrect(windows[chromewid])])
        clientx = int(windows[chromewid]["x"])
        clienty = int(windows[chromewid]["y"])
        near("window_chrome_first_frame", gpureadpixel(clientx + 20, clienty - max(1, TITLEH // 2)), [0, 0, 0, 255])
        button = max(8, int(BTNWH))
        gap = max(2, int(BTNGAP))
        frame = max(1, int(FRAMEW))
        closex = clientx + int(windows[chromewid]["w"]) - gap - button
        buttony = clienty - int(TITLEH) - frame + max(0, (int(TITLEH) - button) // 2)
        pad = max(1, int(round(scalesize(4))))
        near("window_button_first_frame", gpureadpixel(closex + pad, buttony + pad), [239, 239, 239, 255])
        setwindoweffects(1, {
            "winid": chromewid,
            "theme": "graphite",
            "transition_style": "slide",
            "transition_easing": "ease_in_out",
        })
        paint([gpuvisualrect(windows[chromewid])])
        near("window_theme_title", gpureadpixel(clientx + 20, clienty - max(1, TITLEH // 2)), [24, 27, 32, 255], tolerance=3)
        near("window_theme_button", gpureadpixel(closex + pad, buttony + pad), [255, 112, 112, 255], tolerance=3)
        beforeblur = int(gpumetrics().get("blur_copies", 0))
        setwindoweffects(1, {"winid": chromewid, "opacity": 0.75, "blur": True})
        paint([gpuvisualrect(windows[chromewid])])

        if int(gpumetrics().get("blur_copies", 0)) <= beforeblur:
            raise RuntimeError("translucent window did not execute bounded backdrop blur")

        result["checks"]["window_backdrop_blur"] = True
        destroywindow(chromewid, note="diagnostic")
        result["checks"]["window_final_map"] = True

        clientchromewid = createwindow(1, {
            "w": 640,
            "h": 480,
            "x": 400,
            "y": 300,
            "title": "client chrome",
            "role": "window",
            "decoration": "client",
            "client_chrome_height": 40,
            "client_chrome_drag_width": 96,
        })
        createdpaths.append(windows[clientchromewid]["buffer"])
        clientchromewin = windows[clientchromewid]

        expectedclientframe = (
            int(clientchromewin["x"]),
            int(clientchromewin["y"]),
            int(clientchromewin["w"]),
            int(clientchromewin["h"]),
        )

        if winframerect(clientchromewin) != expectedclientframe:
            raise RuntimeError("client-chrome window retained a server frame")

        closex, closey, _, _, minx, _ = windowbuttonrects(clientchromewin)

        expectedcontrols = buttonrects(
            int(clientchromewin["x"]),
            int(clientchromewin["y"]),
            int(clientchromewin["w"]),
        )

        if windowbuttonrects(clientchromewin) != expectedcontrols:
            raise RuntimeError("client-chrome controls did not match server-frame offsets")

        if framehittest(closex + BTNWH // 2, closey + BTNWH // 2, clientchromewin) != ("button", "close"):
            raise RuntimeError("client-chrome close control was not overlaid on the client")

        dragrect = clientdragrect(clientchromewin)

        if dragrect is None or framehittest(dragrect[0] + 1, dragrect[1] + 1, clientchromewin) != ("title", None):
            raise RuntimeError("client-chrome drag strip was not active")

        clientleft = int(clientchromewin["x"])
        clientright = clientleft + int(clientchromewin["w"])

        if minx < clientleft or closex + BTNWH > clientright:
            raise RuntimeError("client-chrome controls escaped the client surface")

        maximizewindow(clientchromewid)
        clientchromewin = windows[clientchromewid]

        if [clientchromewin["x"], clientchromewin["y"], clientchromewin["w"], clientchromewin["h"]] != [WORKX, WORKY, WORKW, WORKH]:
            raise RuntimeError("client-chrome maximize did not use the complete work area")

        destroywindow(clientchromewid, note="diagnostic")
        result["checks"]["client_chrome"] = True
        GPUTRANSITIONS = False

        lifecyclewid = createwindow(1, {
            "w": 240,
            "h": 180,
            "x": 100,
            "y": 100,
            "title": "lifecycle",
            "role": "window",
        })

        if lifecyclewid not in windows:
            raise RuntimeError("window lifecycle create failed")

        lifecyclepath = windows[lifecyclewid]["buffer"]
        createdpaths.append(lifecyclepath)
        writecolor(lifecyclepath, 240, 180, (255, 255, 255, 255))
        mapwindow(1, {"winid": lifecyclewid})
        maximizewindow(lifecyclewid)

        if not ismaximized(windows[lifecyclewid]):
            raise RuntimeError("window lifecycle maximize failed")

        restorewindow(lifecyclewid)

        if ismaximized(windows[lifecyclewid]) or windows[lifecyclewid]["w"] != 240 or windows[lifecyclewid]["h"] != 180:
            raise RuntimeError("window lifecycle restore failed")

        lifecyclegeometry = [
            int(windows[lifecyclewid]["x"]),
            int(windows[lifecyclewid]["y"]),
            int(windows[lifecyclewid]["w"]),
            int(windows[lifecyclewid]["h"]),
        ]

        if not fullscreenwindow(lifecyclewid, True):
            raise RuntimeError("window lifecycle fullscreen entry failed")

        lifecyclewin = windows[lifecyclewid]

        if (
            not isfullscreen(lifecyclewin)
            or [lifecyclewin["x"], lifecyclewin["y"], lifecyclewin["w"], lifecyclewin["h"]]
            != [0, 0, SCREENW, SCREENH]
            or windowframeinsets(lifecyclewin) != (0, 0, 0, 0)
            or framehittest(SCREENW // 2, SCREENH // 2, lifecyclewin) != ("client", None)
        ):
            raise RuntimeError("fullscreen window did not become a borderless framebuffer-sized client")

        if not fullscreenwindow(lifecyclewid, False):
            raise RuntimeError("window lifecycle fullscreen exit failed")

        lifecyclewin = windows[lifecyclewid]

        if isfullscreen(lifecyclewin) or [
            lifecyclewin["x"],
            lifecyclewin["y"],
            lifecyclewin["w"],
            lifecyclewin["h"],
        ] != lifecyclegeometry:
            raise RuntimeError("fullscreen window did not restore its previous geometry")

        result["checks"]["fullscreen_window_state"] = True
        cursormodeset(1, {"winid": lifecyclewid, "mode": "hidden"})

        if (
            windows[lifecyclewid].get("cursor_mode") != "hidden"
            or pointercursorbox(POINTERX, POINTERY, "hidden")[2:] != [0, 0]
            or not replies
            or replies[-1].get("op") != "OK"
        ):
            raise RuntimeError("per-window hidden cursor mode was not accepted")

        cursormodeset(1, {"winid": lifecyclewid, "mode": "arrow"})
        result["checks"]["per_window_hidden_cursor"] = True
        minimizewindow(lifecyclewid)

        if windows[lifecyclewid].get("mapped"):
            raise RuntimeError("window lifecycle minimize failed")

        mapwindow(1, {"winid": lifecyclewid})
        destroywindow(lifecyclewid, note="diagnostic")

        if lifecyclewid in windows:
            raise RuntimeError("window lifecycle destroy failed")

        result["checks"]["window_lifecycle"] = True

        reflowwid = createwindow(1, {
            "w": 800,
            "h": 560,
            "x": 40,
            "y": 40,
            "title": "display reflow",
            "role": "window",
        })
        createdpaths.append(windows[reflowwid]["buffer"])
        writecolor(windows[reflowwid]["buffer"], 800, 560, (255, 255, 255, 255))
        mapwindow(1, {"winid": reflowwid})
        previouswork = (WORKX, WORKY, WORKW, WORKH)
        SCREENW = 800
        SCREENH = 600
        WORKX = 0
        WORKY = 0
        WORKW = 800
        WORKH = 560
        applyuiscale()
        refreshwindows(previouswork)
        reflowwin = windows[reflowwid]
        reflowframe = winframerect(reflowwin)

        expectedw = int(round(800 * (WORKW / previouswork[2])))
        expectedh = int(round(560 * (WORKH / previouswork[3])))

        if int(reflowwin["w"]) != expectedw or int(reflowwin["h"]) != expectedh:
            raise RuntimeError(
                f"display resize did not scale normal window geometry "
                f"expected={expectedw}x{expectedh} actual={reflowwin['w']}x{reflowwin['h']}"
            )

        if (
            reflowframe[0] < WORKX
            or reflowframe[1] < WORKY
            or reflowframe[0] + reflowframe[2] > WORKX + WORKW
            or reflowframe[1] + reflowframe[3] > WORKY + WORKH
        ):
            raise RuntimeError("display resize did not contain a normal window inside the new work area")

        if (
            not reflowwin.get("_resize_pending")
            or int(reflowwin.get("_resize_pw", 0)) != int(reflowwin["w"])
            or int(reflowwin.get("_resize_ph", 0)) != int(reflowwin["h"])
        ):
            raise RuntimeError("display resize did not queue the constrained application size")

        result["checks"]["display_resize_window_reflow"] = {
            "screen": [SCREENW, SCREENH],
            "work_area": [WORKX, WORKY, WORKW, WORKH],
            "window": [reflowwin["x"], reflowwin["y"], reflowwin["w"], reflowwin["h"]],
            "frame": list(reflowframe),
        }
        previouswork = (WORKX, WORKY, WORKW, WORKH)
        destroywindow(reflowwid, note="diagnostic")
        SCREENW = 2560
        SCREENH = 1440
        WORKX = 0
        WORKY = 0
        WORKW = SCREENW
        WORKH = SCREENH
        applyuiscale()
        refreshwindows(previouswork)

        cover = diagnosticwindow(4, "window", 200, 150, 1100, 900, (255, 255, 255, 255), "cover")
        windows[4] = cover
        clients[1]["windows"].append(4)
        zorder[:] = [1, 2, 4, 3]
        GPUSHADOWS = True
        first["shadow"] = True

        if 2 not in gpuoccludedwindows():
            raise RuntimeError("opaque-window occlusion culling did not identify the covered window")

        GPUOCCLUSION = False
        paint()
        unculleddraws = int(gpumetrics().get("frame_draw_calls", 0))
        GPUOCCLUSION = True
        paint()
        culleddraws = int(gpumetrics().get("frame_draw_calls", 0))

        if GPUOCCLUSIONLAST < 1:
            raise RuntimeError("occlusion culling telemetry did not record the covered window")

        if culleddraws >= unculleddraws:
            raise RuntimeError(f"occlusion culling did not reduce draw calls {unculleddraws} -> {culleddraws}")

        result["checks"]["occlusion_culling"] = {
            "windows": int(GPUOCCLUSIONLAST),
            "draw_calls_before": unculleddraws,
            "draw_calls_after": culleddraws,
            "draw_calls_saved": unculleddraws - culleddraws,
        }
        first["shadow"] = False
        GPUSHADOWS = False
        zorder.remove(4)
        gpuwindowrelease(cover)
        windows.pop(4, None)
        clients[1]["windows"].remove(4)

        graphicsclear(1, {"winid": 2})
        paint()
        near("managed_clear", gpureadpixel(420, 420), [255, 0, 0, 255])

        for index in range(12):

            second["x"] = 900 + index * 30
            second["y"] = 420 + (index % 4) * 20
            paint()

        result["checks"]["movement_stress_frames"] = 12
        beforelifecycle = int(gpumetrics().get("texture_count", 0))

        for index in range(8):

            transient = diagnosticwindow(100 + index, "window", 10, 10, 64, 64, (index, index, index, 255), "transient")
            gpuwindowtexture(transient)
            gpuwindowrelease(transient)

        afterlifecycle = int(gpumetrics().get("texture_count", 0))

        if afterlifecycle != beforelifecycle:
            raise RuntimeError(f"transient window textures leaked {beforelifecycle} -> {afterlifecycle}")

        result["checks"]["transient_texture_leaks"] = 0
        firsttelemetry = {
            "scene_commits": int(first.get("_telemetry_scene_commits", 0)),
            "batch_commits": int(first.get("_telemetry_batch_commits", 0)),
            "damage_pixels": int(first.get("_telemetry_damage_pixels", 0)),
            "composited_pixels": int(first.get("_telemetry_composited_pixels", 0)),
            "gpu_upload_bytes": int(first.get("_telemetry_gpu_upload_bytes", 0)),
            "gpu_draw_calls": int(first.get("_telemetry_gpu_draw_calls", 0)),
            "gpu_frames": int(first.get("_telemetry_gpu_frames", 0)),
        }

        if firsttelemetry["scene_commits"] < 2 or firsttelemetry["batch_commits"] < 1:
            raise RuntimeError(f"per-window scene telemetry was not recorded {firsttelemetry}")

        if firsttelemetry["damage_pixels"] < 1 or firsttelemetry["composited_pixels"] < 1 or firsttelemetry["gpu_upload_bytes"] < 1:
            raise RuntimeError(f"per-window damage/upload telemetry was not recorded {firsttelemetry}")

        if firsttelemetry["gpu_draw_calls"] < 1 or firsttelemetry["gpu_frames"] < 1:
            raise RuntimeError(f"per-window draw telemetry was not recorded {firsttelemetry}")

        result["checks"]["window_telemetry"] = firsttelemetry
        windowtexturecount = sum(1 for win in (desktop, first, second) if win.get("_gpu_texture") is not None)
        beforewindowrelease = int(gpumetrics().get("texture_count", 0))

        for win in (desktop, first, second):
            gpuwindowrelease(win)

        afterwindowrelease = int(gpumetrics().get("texture_count", 0))

        if beforewindowrelease - afterwindowrelease != windowtexturecount:
            raise RuntimeError("window texture release count did not match allocated window textures")

        metrics = gpumetrics()

        if int(metrics.get("failed_frames", 0)) != 0:
            raise RuntimeError(f"managed compositor reported failed frames {metrics.get('failed_frames')}")

        if int(metrics.get("fallbacks", 0)) != 0:
            raise RuntimeError(f"managed compositor reported fallbacks {metrics.get('fallbacks')}")

        if int(GPUCOMMANDERRORS) != 0:
            raise RuntimeError(f"managed graphics commands reported {GPUCOMMANDERRORS} render errors")

        if int(metrics.get("frame_samples", 0)) < 20:
            raise RuntimeError("performance telemetry collected too few compositor frames")

        workloads = gpuworkloadmetrics()

        if int(workloads.get("full", {}).get("samples", 0)) < 1 or int(workloads.get("partial", {}).get("samples", 0)) < 1:
            raise RuntimeError(f"workload telemetry did not separate full and partial frames {workloads}")

        result["telemetry"] = metrics
        result["workload_telemetry"] = workloads
        result["checks"]["workload_telemetry"] = True
        result["performance"] = {
            "average_frame_ms": metrics.get("average_frame_ms", 0.0),
            "percentile_95_frame_ms": metrics.get("percentile_95_frame_ms", 0.0),
            "maximum_frame_ms": metrics.get("maximum_frame_ms", 0.0),
            "frame_budget_ms": metrics.get("frame_budget_ms", 0.0),
            "missed_frame_budget": metrics.get("missed_frame_budget", 0),
            "missed_frame_percent": metrics.get("missed_frame_percent", 0.0),
            "draw_calls_per_frame": metrics.get("draw_calls_per_frame", 0.0),
            "upload_bytes_per_frame": metrics.get("upload_bytes_per_frame", 0.0),
            "texture_bytes": metrics.get("texture_bytes", 0),
            "maximum_texture_bytes": metrics.get("maximum_texture_bytes", 0),
            "maximum_texture_count": metrics.get("maximum_texture_count", 0),
        }
        opengloffscreen(3840, 2160)

        if not gpubegin((12, 34, 56, 255)):
            raise RuntimeError("4K OpenGL framebuffer did not begin a frame")

        gpudrawrect(3832, 2152, 8, 8, (220, 40, 80, 255))

        if not gpuend(present=False):
            raise RuntimeError("4K OpenGL framebuffer did not finish a frame")

        uhdbackground = gpureadpixel(0, 0)
        uhdedge = gpureadpixel(3839, 2159)

        if any(abs(int(value) - int(wanted)) > 2 for value, wanted in zip(uhdbackground, [12, 34, 56, 255])):
            raise RuntimeError(f"4K OpenGL framebuffer background produced an unexpected pixel {uhdbackground}")

        if any(abs(int(value) - int(wanted)) > 2 for value, wanted in zip(uhdedge, [220, 40, 80, 255])):
            raise RuntimeError(f"4K OpenGL framebuffer edge produced an unexpected pixel {uhdedge}")

        result["checks"]["opengl_framebuffer_4k"] = {
            "resolution": [3840, 2160],
            "background": uhdbackground,
            "edge": uhdedge,
        }
        result["passed"] = True

    except Exception as e:
        result["errors"].append(str(e))

    finally:

        globals()["sendjson"] = originalsendjson
        globals()["openoperationscentre"] = originalopenoperationscentre
        globals()["locksession"] = originallocksession
        globals()["takescreenshot"] = originaltakescreenshot
        BUFBASE = originalbufbase
        CHROMIUMXWDBUFFER = originalchromiumxwdbuffer
        STATEBASE = originalstatebase
        TELEMETRYPATH = originaltelemetrypath
        LASTTELEMETRY = originallasttelemetry

        try:

            for win in list(windows.values()):
                gpuwindowrelease(win)

        except Exception:
            pass

        try:
            openglclose()
        except Exception:
            pass

        windows.clear()
        zorder.clear()
        clients.clear()

        for path in createdpaths:

            try:

                if os.path.exists(path):
                    os.unlink(path)

            except Exception:
                pass

        try:

            if os.path.isdir(diagnosticbase) and not os.listdir(diagnosticbase):
                os.rmdir(diagnosticbase)

        except Exception:
            pass

    return result


def windowcompositordiagnosticcommand():

    result = windowcompositordiagnostic()
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result.get("passed") else 1


def main():

    global MAXRECTS, LOGOPS, SCREENW, SCREENH, POINTERX, POINTERY, LASTCURSOR, CURSORDIRTY, SERVERID, CURSORENABLED, BOOTCURSORHIDE, CFG
    global GRAPHICSPRESENTFD, VIDEOSERVER
    global GPUCOMPOSITOR, GPUFAILED, GPUSHADOWS, GPUTRANSITIONS, GPUTRANSITIONMS, GPUSHADOWRADIUS, GPUSHADOWOPACITY, GPUOCCLUSION
    global GPUBLUR, GPUBLURRADIUS, GPUUISCALE, GRAPHICSTHEME

    if not initializeipcidentity():
        log("could not establish launcher process identity")
        sys.exit(1)

    makepaths()

    loadwindowattributes()

    # SIGUSR2 is reserved for the PID 1 graphics supervisor. If a vendor EGL
    # or DRM ctypes call stops making progress, faulthandler records the exact
    # Python call site and every Python thread before the owner is replaced.
    # Keep the stream alive for the process lifetime.
    try:
        hangtrace = open(
            LOGFILE,
            "a",
            encoding="utf-8",
            buffering=1,
        )
        hangtrace.write(
            f"\n===== WindowServer pid={os.getpid()} "
            f"time={time.time():.6f} =====\n"
        )
        hangtrace.flush()
        os.fsync(hangtrace.fileno())
        faulthandler.register(
            signal.SIGUSR2,
            file=hangtrace,
            all_threads=True,
            chain=False,
        )
    except Exception as error:
        hangtrace = None
        log(f"GPU hang Python traceback registration failed {error}")

    cfg = loadsettings()
    backendoverride = str(
        os.environ.get("T1OS_WINDOWSERVER_GRAPHICS_BACKEND", "")
    ).strip().lower()

    if backendoverride in ("opengl", "framebuffer", "kms-framebuffer"):
        cfg["graphics_backend"] = backendoverride
        cfg["gpu_compositor"] = backendoverride == "opengl"
        graphicslog(
            f"> graphics backend selected by boot recovery policy "
            f"backend={backendoverride}"
        )

    CFG = cfg

    # apply settings to globals
    MAXRECTS = int(cfg.get("max_rects", 32))
    LOGOPS   = bool(cfg.get("log_ops", False))

    # cursor policy
    CURSORENABLED = bool(cfg.get("cursor_enabled", True))
    BOOTCURSORHIDE = bool(cfg.get("boot_cursor_hide", True))
    GPUSHADOWS = bool(cfg.get("gpu_shadows", True))
    GPUTRANSITIONS = bool(cfg.get("gpu_transitions", True))
    GPUOCCLUSION = bool(cfg.get("gpu_occlusion_culling", True))
    GPUTRANSITIONMS = max(0, min(5000, int(cfg.get("gpu_transition_ms", 140))))
    GPUSHADOWRADIUS = max(1, min(128, int(cfg.get("gpu_shadow_radius", 18))))
    GPUSHADOWOPACITY = max(0.0, min(1.0, float(cfg.get("gpu_shadow_opacity", 0.35))))
    GPUBLUR = bool(cfg.get("gpu_blur", True))
    GPUBLURRADIUS = max(1, min(32, int(cfg.get("gpu_blur_radius", 12))))
    GPUUISCALE = max(
        0.5, min(3.0, float(cfg.get("ui_scale", 1.0))))
    requestedtheme = str(cfg.get("graphics_theme", "classic")).lower()
    GRAPHICSTHEME = requestedtheme if requestedtheme in GRAPHICSTHEMES else "classic"
    gpusetframebudget(
        max(1.0, float(cfg.get("frame_interval_ms", 16.667)))
    )

    try:

        ginit(backend=cfg.get("graphics_backend", "auto"))

        graphicsstate = backendinfo()

        if graphicsstate.get("backend") not in (
            "framebuffer",
            "kms-framebuffer",
            "opengl",
        ):
            raise RuntimeError(
                f"no usable graphics backend: {json.dumps(graphicsstate, sort_keys=True)}"
            )

    except GPUDeviceLostError as e:

        log(f"graphics init reported GPU device loss {e}")

        sys.exit(GPUDEVICEFAILUREEXIT)

    except Exception as e:

        log(f"graphics init failed {e}")

        sys.exit(BACKENDINITFAILUREEXIT)

    GPUFAILED = False
    GPUCOMPOSITOR = bool(cfg.get("gpu_compositor", True)) and gpuavailable()

    if GPUCOMPOSITOR:

        refresh = float(graphicsstate.get("refresh_hz") or 0.0)

        if 10.0 <= refresh <= 1000.0:
            cfg["frame_interval_ms"] = 1000.0 / refresh
            gpusetframebudget(cfg["frame_interval_ms"])
            graphicslog(
                f"> graphics compositor pacing "
                f"{cfg['frame_interval_ms']:.3f}ms from {refresh:.3f}Hz DRM mode"
            )

        graphicslog("> graphics GPU window compositor ready")

    if GPUCOMPOSITOR and bool(cfg.get("gpu_glyph_prewarm", True)):

        renderer = str(graphicsstate.get("renderer") or "")

        if "nvk" in renderer.casefold():
            # NVK can lose the Vulkan device while Zink submits the burst of
            # texture uploads produced by startup glyph warming. Glyph warming
            # is optional; normal demand-loaded glyph caching remains enabled.
            graphicslog("> graphics bounded glyph prewarm skipped for NVK")

        else:
            ratio = squarerootscale()
            sizes = sorted(set(max(1, min(256, int(round(value * ratio)))) for value in (14, 16, 20, 24, 32)))
            # Glyph warming is an optimisation, not a readiness dependency.
            # Keep it inside a tight budget so slow virtual GPUs cannot delay
            # the WindowServer protocol handshake and hold PID 1 at boot.
            graphicslog("> graphics bounded glyph prewarm begin")
            warmed = gpuprewarmtext(
                "".join(chr(value) for value in range(32, 127)),
                sizes=sizes,
                fontpath=WINDOWFONT,
                budget_ms=250,
            )
            graphicslog(f"> graphics bounded glyph prewarm complete glyphs={int(warmed)}")

    if GPUCOMPOSITOR:

        try:
            # Complete the first connector/mode stability poll before the GPU
            # is advertised to clients. Physical outputs retain their active
            # DRM framebuffer mode unless the user explicitly selected a T1OS
            # display mode; virtual drivers may adopt a host-requested mode.
            modechanged = bool(refreshfb(force_physical=True))
            graphicslog(
                f"> graphics startup DRM mode stability check complete "
                f"changed={modechanged}"
            )

            # Validate transfers, shaders, default-framebuffer rendering and
            # synchronization before opening any WindowServer sockets.  An
            # idle glFinish() is not evidence that a Vulkan submission works.
            gpustartupworkloadgate()
            graphicslog("> graphics startup GPU health gate passed")

        except GPUDeviceLostError as e:
            graphicslog(f"> graphics startup GPU device health gate failed {e}")
            graphicslog(
                "> graphics refusing in-process backend substitution; "
                "GODDESS must replace the GPU owner"
            )
            sys.exit(GPUDEVICEFAILUREEXIT)

        except Exception as e:
            graphicslog(f"> graphics startup compositor API gate failed {e}")
            graphicslog(
                "> graphics refusing in-process backend substitution; "
                "GODDESS must replace the compositor owner without resetting "
                "the bound DRM device"
            )
            sys.exit(GPUCOMPOSITORFAILUREEXIT)

    GRAPHICSPRESENTFD = kmspresentationfd()

    if GRAPHICSPRESENTFD is not None:
        sel.register(
            GRAPHICSPRESENTFD,
            selectors.EVENT_READ,
            data={"kind": "graphics"},
        )
        kmsseteventdriven(True)

    # Capture the real dimensions only after the GPU health gate has selected
    # the backend that will actually serve the desktop.
    try:

        SCREENW, SCREENH = getscreensize()

    except Exception:

        SCREENW, SCREENH = (SCREENW, SCREENH)

    graphicslog("> graphics initial state write begin")
    writegraphicsstate()
    graphicslog("> graphics initial state write complete")

    applyuiscale()

    # ensure pointer starts inside real bounds
    if POINTERX < 0: POINTERX = 0

    if POINTERY < 0: POINTERY = 0

    if POINTERX >= SCREENW: POINTERX = SCREENW - 1

    if POINTERY >= SCREENH: POINTERY = SCREENH - 1

    sizepath = os.path.join(STATEBASE, "fb.size")

    writefbsize(SCREENW, SCREENH)

    setworkarea(cfg)

    broadcastworkarea()

    refreshwindows()

    # try load last pointer position
    try:

        p = os.path.join(STATEBASE, "pointer.pos")

        if os.path.exists(p):

            txt = open(p, "r").read().strip()

            parts = txt.split(",")

            if len(parts) == 2:

                POINTERX = int(parts[0])
                POINTERY = int(parts[1])

        else:

            try:

                ip = os.path.join(os.path.dirname(INPUTSOCKPATH), "pointer.pos")

                if os.path.exists(ip):

                    txt = open(ip, "r").read().strip()

                    parts = txt.split(",")

                    if len(parts) == 2:

                        POINTERX = int(parts[0])
                        POINTERY = int(parts[1])

                else:

                    POINTERX = SCREENW // 2
                    POINTERY = SCREENH // 2

            except Exception:

                POINTERX = SCREENW // 2
                POINTERY = SCREENH // 2

    except Exception:

        POINTERX = SCREENW // 2
        POINTERY = SCREENH // 2

    LASTCURSOR = pointercursorbox(POINTERX, POINTERY, "arrow")

    # The cursor remains hidden during boot.  Its first visible owner will
    # dirty it after a system scene is mapped, so there is no startup frame to
    # schedule here.
    CURSORDIRTY = False

    srv, sid = startserver()
    VIDEOSERVER = startvideoserver()
    graphicslog("> graphics WindowServer protocol sockets ready")

    connectinputserver()

    SERVERID = sid
    writegraphicscapabilityreceipt()

    log(f"accept at {SOCKPATH} server {SERVERID}")

    if VIDEOSERVER is not None:
        log(f"video surfaces at {VIDEOSOCKPATH}")

    signal.signal(signal.SIGINT, handlesignal)
    signal.signal(signal.SIGTERM, handlesignal)

    composeexit = composeloop(cfg)

    if GRAPHICSPRESENTFD is not None:

        try:
            sel.unregister(GRAPHICSPRESENTFD)
        except Exception:
            pass

        kmsseteventdriven(False)

    videoreleasepulse(force=True)

    for identifier in list(VIDEOCLIENTS):
        dropvideoclient(identifier, "window server stop")

    if VIDEOSERVER is not None:
        try:
            sel.unregister(VIDEOSERVER)
        except Exception:
            pass

        VIDEOSERVER.close()

    sel.close()

    srv.close()

    try:
        removestalesocket(SOCKPATH)
    except FileNotFoundError:
        pass

    try:
        removestalesocket(VIDEOSOCKPATH)
    except FileNotFoundError:
        pass

    savewindowpointerpos(force=True)

    savewindowattributes(force=True)

    if not stoptelemetrywriter(timeout=2.0):
        graphicslog(
            "> graphics telemetry writer did not drain before shutdown"
        )

    try:
        gclose()
    except Exception as error:
        graphicslog(f"> graphics close failed {error}")

    log(f"window server stop")

    if composeexit:
        raise SystemExit(int(composeexit))

if __name__ == "__main__":

    if len(sys.argv) > 1 and sys.argv[1] == "diagnostic":
        raise SystemExit(windowcompositordiagnosticcommand())

    main()
