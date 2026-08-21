#!"/the one/software/python/bin/python" -B

"""chromium: a guest-native, full Chromium-class browser for The One OS.

Only this Python file is installed as Chromium application code. Maintained ELF
dependencies live in /the one/software/chromium and execute against T1OS's
native path contract.  The engine never contacts or runs on the host.
"""

import errno
import ctypes
import fcntl
import json
import math
import mmap
import os
import re
import select
import shutil
import signal
import socket
import stat
import struct
import subprocess
import sys
import threading
import time
import traceback
import zlib

sys.path.insert(0, '/the one/build')
from GODDESS.GODDESS import formatlog


APPNAME = "chromium"
APPPATH = "/the one/build/chromium/chromium.py"
APPROLE = "window"
WINDOWSOCK = "/.ephemeral/windowserver/accept.sock"
AUDIOSOCK = "/.ephemeral/audio/accept.sock"
ENGINE = "/the one/software/chromium"
PROGRAM = ENGINE + "/program"
TOOLS = ENGINE + "/tools"
LIBRARIES = ENGINE + "/libraries"
RESOURCES = ENGINE + "/resources"
FONTCONFIGROOT = RESOURCES + "/fontconfig-configuration"
FONTCONFIGFILE = FONTCONFIGROOT + "/fonts.conf"
FONTROOT = RESOURCES + "/fonts/truetype"
NOUVEAURENDERER = "angle-swiftshader"
SETTINGROOT = "/the one/settings/chromium"
SETTINGFILE = SETTINGROOT + "/settings.json"
GOOGLEAPICREDENTIALFILE = (
    "/the one/build/chromium/google api credentials.json"
)
GOOGLEAPICREDENTIALMAXBYTES = 4096
GOOGLEAPICREDENTIALENVIRONMENT = {
    "google_api_key": "GOOGLE_API_KEY",
    "google_default_client_id": "GOOGLE_DEFAULT_CLIENT_ID",
    "google_default_client_secret": "GOOGLE_DEFAULT_CLIENT_SECRET",
}
# Chromium shows its missing-Google-API-key infobar only while the API key is
# its compiled-in unset token. T1OS does not ship third-party credentials, so
# use an explicit non-secret sentinel when no architect-provisioned key exists.
# A real protected credential document still replaces this value below.
GOOGLEAPIKEYSUPPRESSIONVALUE = "no"
INSTANCELOCK = SETTINGROOT + "/instance.lock"
INSTANCESOCKET = SETTINGROOT + "/instance.sock"
DISPLAYSETTINGFILE = "/the one/settings/display/settings.json"
GRAPHICSCATALOGUE = "/the one/catalogue/graphics"
LIBVADRIVERPATH = GRAPHICSCATALOGUE + "/drivers"
NVIDIARUNTIMEPATH = GRAPHICSCATALOGUE + "/nvidia"
NVIDIACACHEPATH = "/.ephemeral/cache/nvidia"
NVIDIAEGLVENDORFILE = (
    NVIDIARUNTIMEPATH + "/egl_vendor.d/10_nvidia.json"
)
NVIDIAGBMPATH = NVIDIARUNTIMEPATH + "/gbm"
BASEGRAPHICSLIBRARYPATH = LIBRARIES + ":" + GRAPHICSCATALOGUE
MESAGRAPHICSLIBRARYPATH = GRAPHICSCATALOGUE + ":" + LIBRARIES
MESAGBMPATH = GRAPHICSCATALOGUE + "/gbm"
NVIDIAGRAPHICSLIBRARYPATH = (
    NVIDIARUNTIMEPATH + ":" + GRAPHICSCATALOGUE + ":" + LIBRARIES
)
NVIDIAGPULIBRARYPATHVARIABLE = "SANDBOX_GPU_LD_LIBRARY_PATH"
NVIDIAGPUEGLVENDORVARIABLE = (
    "SANDBOX_GPU_EGL_VENDOR_LIBRARY_FILENAMES"
)
NVIDIAGPUEGLEXTERNALVARIABLE = (
    "SANDBOX_GPU_EGL_EXTERNAL_PLATFORM_CONFIG_DIRS"
)
NVIDIAGPUGBMBACKENDSPATHVARIABLE = "SANDBOX_GPU_GBM_BACKENDS_PATH"
NVIDIAGPUGBMBACKENDVARIABLE = "SANDBOX_GPU_GBM_BACKEND"
SESSIONIDENTITYFILE = "/the one/settings/session/identity.json"
SESSIONIDENTITYMAXBYTES = 1024
SESSIONUSERNAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,31}")
PROFILE = SETTINGROOT + "/profile"
CONFIGROOT = SETTINGROOT + "/config"
LEGACYSETTINGROOT = "/the one/settings/browser"
LOGFILE = "/the one/logs/chromium.py.log"
ENGINEDEBUGLOG = "/the one/logs/chromium-engine-debug.log"
RUNTIME = "/.ephemeral/chromium"
FRAMEBUFFER = RUNTIME + "/framebuffer"
# Network and renderer caches are disposable and must not carry corrupt,
# root-owned entries from one boot or Chromium release into the next.
CACHE = RUNTIME + "/cache"
DISKCACHEBYTES = 256 * 1024 * 1024
MEDIACACHEBYTES = 128 * 1024 * 1024
AUDIO = RUNTIME + "/audio"
AUDIOCLOCK = AUDIO + "/presentation-clock"
SHARED = RUNTIME + "/shared"
DISPLAYROOT = RUNTIME + "/display"
DISPLAYSOCKET = DISPLAYROOT + "/X99"
TEMPORARY = RUNTIME + "/temporary"
RUNTIMEROOT = RUNTIME + "/runtime"
XKBCACHE = RUNTIME + "/xkb"
FONTCACHE = SETTINGROOT + "/font-cache"
SYSTEMROOT = RUNTIME + "/system"
VARIABLEROOT = RUNTIME + "/variable"
PATHPROVIDER = ENGINE + "/t1os-path-provider.so"
RUNTIMEPROVIDER = RUNTIME + "/path-provider.so"
SANDBOX = PROGRAM + "/chrome-sandbox"
SANDBOXROOT = RUNTIME + "/sandbox-root"
CHROMEEXECUTABLE = PROGRAM + "/chrome"
CHROMIUMMANIFEST = ENGINE + "/manifest.json"
SUBPROCESSEXECUTABLE = TOOLS + "/t1os-chrome-subprocess"
SANDBOXEXECUTABLE = "./chrome-sandbox"
PROCESSROOT = "/the one/drivers/processes"
DRMSTATEROOT = "/the one/drivers/state/class/drm"
DRMNODEROOT = "/the one/drivers/nodes/dri"
CHROMIUMLAUNCHVARIABLE = "T1OS_CHROMIUM_LAUNCH_ID"
CHROMIUMDEBUGVARIABLE = "T1OS_CHROMIUM_DEBUG"
HARDWAREDIAGNOSTICPOLICY = (
    "/the one/settings/media/hardware diagnostics.json"
)
HARDWAREDIAGNOSTICFALLBACK = (
    "/the one/build/chromium/hardware diagnostics.json"
)
ENGINEDEBUGLOGLIMIT = 8 * 1024 * 1024
ENGINEDEBUGLOGMINIMUM = 64 * 1024
ENGINEDEBUGLOGMAXIMUM = 16 * 1024 * 1024
ENGINEDEBUGLINELIMIT = 16 * 1024
NVIDIAPRESENTATIONVARIABLE = "T1OS_CHROMIUM_NVIDIA_PRESENTATION"
SINGLETONNAMES = ("SingletonLock", "SingletonSocket", "SingletonCookie")
XWDFILE = FRAMEBUFFER + "/Xvfb_screen0"
DNSFILE = "/the one/settings/network/dns.txt"
VMTESTNETLOGPATH = "/the one/logs/chromium-netlog.json"
FONTFILE = "/the one/resources/fonts/atkinsonhyperlegiblenext.ttf"
BASEWIDTH = 1280
BASEHEIGHT = 900
BASECHROMEHEIGHT = 40
BASECHROMEDRAGWIDTH = 96
CHROMEDEVICESCALEADJUSTMENT = 0.90
MINWIDTH = 640
MINHEIGHT = 480
MAXWIDTH = 3840
MAXHEIGHT = 2160
BACKINGMAXWIDTH = 3840
BACKINGMAXHEIGHT = 2160
ENGINEUID = 1000
ENGINEGID = 1000
DISPLAY = ":99"
XVFBREADYTIMEOUT = 20.0
XWMREADYTIMEOUT = 10.0
# A release-profile cold start registers Chromium's bundled components before
# the first BrowserWindow.  That phase measured 45-50 seconds on the VM's
# freshly cloned VDI, so a 60-second deadline killed a healthy browser during
# native window initialization.  Keep a bounded two-minute startup budget;
# the process-exit check below still fails immediately on a real crash.
CHROMEWINDOWTIMEOUT = 120.0
CHROMEGPURUNTIMETIMEOUT = 15.0
CHROMEDIAGNOSTICTIMEOUT = 90.0
CHROMEDIAGNOSTICVERIFYTIMEOUT = 30.0
CHROMEPROBETIMEOUT = 15.0
CHROMIUMVIDEOCODECS = frozenset(("H264", "VP8", "VP9", "AV1"))
MEDIADECODEPOLICY = "/the one/settings/media/video decode service.json"
MEDIADECODEPACKAGEDPOLICY = (
    "/the one/software/audio/video decode service.json"
)
MEDIADECODESTATE = "/.ephemeral/media/decode-service.json"
MEDIADECODESOCKET = "/.ephemeral/media/decode.sock"
PRESENTATIONSOCKET = "/.ephemeral/windowserver/video.sock"
PRESENTATIONSTREAM = "__t1os_chromium_presentation__"
MEDIADECODEPROTOCOL = "T1MD"
MEDIADECODEPROTOCOLVERSION = 1
MEDIADECODEWORKERUID = 65534
MEDIADECODEWORKERGID = 1000
MEDIADECODESANDBOXFORMAT = 1
MEDIADECODESANDBOXMINIMUMABI = 5
MEDIADECODESANDBOXFLAGS = 255
MEDIADECODESESSIONEXECVISIBLEFDS = 6
MEDIADECODESESSIONREQUIREDIPCFDS = 3
MEDIADECODESESSIONSTDIN = "null"
MEDIADECODESESSIONSTDOUT = "null"
MEDIADECODESESSIONSTDERR = "bounded-nonblocking-relay"
MEDIADECODESESSIONDIAGNOSTICLIMIT = 1048576
MEDIADECODEWATCHDOGCONTRACT = {
    "format": 1,
    "policy_id": "t1md-watchdog-v1",
    "authority": "supervisor",
    "clock": "CLOCK_MONOTONIC",
    "timeout_action": "SIGKILL",
    "idle_timeout_ms": 0,
    "starting_timeout_ms": 15000,
    "hello_timeout_ms": 30000,
    "create_timeout_ms": 15000,
    "decode_timeout_ms": 15000,
    "flush_timeout_ms": 15000,
    "reset_timeout_ms": 10000,
    "release_timeout_ms": 6000,
    "destroy_timeout_ms": 10000,
    "cleanup_timeout_ms": 10000,
    "exiting_timeout_ms": 1000,
}
MEDIADECODEMAXSESSIONS = 8
MEDIADECODEFEATURE = "T1OSVideoDecoder"
PRESENTATIONFEATURE = "T1OSNvidiaPresentation"
MEDIADECODEOUTPUTVARIABLE = "T1OS_MEDIA_DECODE_OUTPUT"
MEDIADECODEOUTPUTSWITCH = "--t1os-video-decode-output="
MEDIADECODEOUTPUTDMABUF = "dma-buf"
MEDIADECODEOUTPUTLINEAR = "linear-memory"
MEDIADECODECHROMIUMREVISION = "24b04c927b23c39cf9c5227cc8dc6f64a744c8e9"
MEDIADECODEPROTOCOLHEADERSHA256 = (
    "11a319c26e499415cf39a3b6b5c59c3801b2e91859500472b92c6be1fcaceba0"
)
MEDIADECODESOURCEOVERLAYSHA256 = (
    "102cea1fe8eb1358493eb2889579ece701ead0edf917d5edcc276a2d23fc0705"
)
MEDIADECODEBUILDMARKER = (
    "T1OS_MEDIA_DECODER=T1MD/1;brokered_socket=1;pool=8;"
    "chromium=24b04c927b23c39cf9c5227cc8dc6f64a744c8e9;"
    "protocol_sha256="
    "11a319c26e499415cf39a3b6b5c59c3801b2e91859500472b92c6be1fcaceba0;"
    "source_sha256="
    "102cea1fe8eb1358493eb2889579ece701ead0edf917d5edcc276a2d23fc0705"
)
MEDIADECODESOCKETSWITCH = "--t1os-video-decode-socket="
# The 2026-07-30 development route that forced nvidia-vaapi-driver through a
# constructor-created NVIDIA/UVM descriptor broker hard-reset the test system
# when the first real web decoder was created. Keep that direct VA/CUDA route
# unavailable; T1MD remains the only permitted NVIDIA hardware decoder.
NVIDIADIRECTVAAPIQUARANTINED = True


RUNNING = True
WSOCK = None
WSBUFFER = b""
WSOUTPUT = None
WINID = None
BUFFERPATH = None
WINW = BASEWIDTH
WINH = BASEHEIGHT
ENGINEW = BASEWIDTH
ENGINEH = BASEHEIGHT
SCREENW = 1920
SCREENH = 1080
WINDOWGRAPHICSCONTRACT = {}
WINDOWREADY = False
GFX = None
FONTREADY = False
ENGINEPID = None
ENGINECHANNEL = None
ENGINEBUFFER = b""
ENGINEOUTPUT = None
ENGINESTATE = "stopped"
ENGINEERROR = ""
ENGINESTART = 0.0
ENGINELOG = None
ENGINELOGREADER = None
XWDFD = None
XWDMAP = None
XWDMETA = None
LASTFRAMECRC = None
LASTTILECRCS = {}
LASTFRAME = 0.0
LASTMOTION = None
LASTMOTIONSENT = 0.0
# Pointer motion is coalesced only while an IPC queue is blocked.  A fixed
# timer here compounded the input and WindowServer timers into visible lag.
POINTERFRAMEINTERVAL = 0.0
PENDINGSCROLLX = 0
PENDINGSCROLLY = 0
LASTSCROLLFRAME = 0.0
SCROLLFRAMEINTERVAL = 1.0 / 60.0
SMOOTHSCROLLEASING = 0.25
SMOOTHSCROLLMAXSTEP = 6
SMOOTHSCROLLLIMIT = 120
ENGINEDAMAGESUPPORTED = False
ENGINEDAMAGE = []
NEEDREDRAW = True
PLACEHOLDER = "starting chromium"
DIRECTBUFFERSTATE = "inactive"
DIRECTBUFFERERROR = ""
DIRECTBUFFERWIDTH = 0
DIRECTBUFFERHEIGHT = 0
FULLSCREEN = False
FULLSCREENREQUEST = None
WEBFULLSCREEN = False
BROWSERCURSORMODE = "arrow"
XCURSORSEMANTICS = None
# Chromium's X11/Ozone backend synthesizes these cursor bitmaps itself instead
# of loading the equivalent images from the configured Xcursor theme.  Their
# fingerprints are therefore part of the bundled Chromium runtime contract.
CHROMIUMCURSORIMAGESEMANTICS = {
    "c084f4980a1b115b": "arrow",
    "71aed559a3c8f918": "text",
    "5a69dc0a3b7c37b3": "link",
    "0020146237c19b34": "busy",
}
FULLSCREENCURSORVISIBLE = True
FULLSCREENCURSORHIDEAT = 0.0
FULLSCREENCURSORDELAY = 2.0
CONFIG = {}
AUDIOSTOP = threading.Event()
AUDIOTHREAD = None
AUDIORATE = 48000
AUDIOCHUNKBYTES = 480 * 2 * 2
AUDIOSTREAMBUFFERSECONDS = 0.04
AUDIOSTREAMPREBUFFERMS = 20
AUDIORELAYLOGINTERVAL = 30.0
# Shared with Chromium's T1OS ALSA delay reader. All integer fields are
# little-endian. The odd/even sequence is a seqlock around updates made by the
# Python FIFO relay while Chromium reads without taking a cross-process lock.
AUDIOCLOCKMAGIC = 0x43413154  # "T1AC"
AUDIOCLOCKVERSION = 1
AUDIOCLOCKFORMAT = struct.Struct("<IIQQQQQQQII")
AUDIOCLOCKSEQUENCEOFFSET = 8
AUDIOFIONREAD = 0x541B
INSTANCELOCKFD = None
INSTANCEHOST = None
INSTANCEOWNED = False
ACTIVATIONPENDING = False
BROWSERTITLE = ""

TRANSPORTQUEUELIMIT = 1024 * 1024
TRANSPORTFLUSHBUDGET = 256 * 1024
ENGINEQUEUELIMIT = 8 * 1024 * 1024
INPUTBRIDGEQUEUELIMIT = 4 * 1024 * 1024
INPUTBRIDGEFLUSHBUDGET = 64 * 1024


def uiscalefactor():
    try:
        with open(DISPLAYSETTINGFILE, 'r', encoding='utf-8') as stream:
            settings = json.load(stream)
        return max(0.5, min(3.0, float(settings.get('ui_scale', 1.0))))
    except Exception:
        return 1.0


def displaydensityscale(width=None, height=None, preference=None):
    """Return the native T1OS density scale for a display."""
    try:
        displaywidth = max(1, int(SCREENW if width is None else width))
        displayheight = max(1, int(SCREENH if height is None else height))
        requested = uiscalefactor() if preference is None else float(preference)
        density = math.sqrt((displaywidth * displayheight) / float(1920 * 1080))
        return max(0.5, min(4.0, density * requested))
    except Exception:
        return 1.0


def chromedevicescale(width=None, height=None, preference=None):
    """Use a slightly denser Chromium UI without changing window geometry."""
    scale = displaydensityscale(width, height, preference)
    return max(0.5, min(4.0, scale * CHROMEDEVICESCALEADJUSTMENT))


def initialwindowsize(width, height, preference=None):
    scale = displaydensityscale(width, height, preference)
    margin = max(50, int(round(100 * scale)))
    return (
        max(MINWIDTH, min(int(round(BASEWIDTH * scale)), int(width) - margin)),
        max(MINHEIGHT, min(int(round(BASEHEIGHT * scale)), int(height) - margin)),
    )


def chromiumbackingsurface():
    """Return the one-time private X root allocation."""
    maximumwidth = min(
        BACKINGMAXWIDTH,
        max(MINWIDTH, int(CONFIG.get("maximum_width", MAXWIDTH))),
    )
    maximumheight = min(
        BACKINGMAXHEIGHT,
        max(MINHEIGHT, int(CONFIG.get("maximum_height", MAXHEIGHT))),
    )
    return maximumwidth, maximumheight


def chromiumbackingratio(displaywidth=None, displayheight=None):
    """Use one display-global scale so resizing cannot change CSS density."""
    displaywidth = max(
        1, int(SCREENW if displaywidth is None else displaywidth),
    )
    displayheight = max(
        1, int(SCREENH if displayheight is None else displayheight),
    )
    maximumwidth, maximumheight = chromiumbackingsurface()
    return min(
        1.0,
        maximumwidth / float(displaywidth),
        maximumheight / float(displayheight),
    )


def chromiumbackingdevicescale(
    displaywidth=None, displayheight=None, preference=None,
):
    displaywidth = max(
        1, int(SCREENW if displaywidth is None else displaywidth),
    )
    displayheight = max(
        1, int(SCREENH if displayheight is None else displayheight),
    )
    return max(
        0.25,
        min(
            4.0,
            chromedevicescale(displaywidth, displayheight, preference)
            * chromiumbackingratio(displaywidth, displayheight),
        ),
    )


def chromiumcommandwindowsize(width, height, device_scale):
    """Return Chromium's DIP command size for a bounded native X11 window."""
    width = max(1, int(width))
    height = max(1, int(height))
    try:
        device_scale = max(0.25, min(4.0, float(device_scale)))
    except Exception:
        device_scale = 1.0
    # --window-size is interpreted in device-independent pixels when a forced
    # device scale is active. Passing the native backing dimensions here made
    # Chromium multiply them by the scale a second time (3840x2083 became
    # 5530x3000 at 1.44), exceeding both the private X root and the tested
    # NVIDIA scanout/export dimensions before the input bridge could resize it.
    # Round down so the first mapped/swap buffer can never exceed the bounded
    # native allocation; t1os-xinput immediately applies the exact pixel size.
    return (
        max(1, int(math.floor(width / device_scale))),
        max(1, int(math.floor(height / device_scale))),
    )


def chromiumbackingsize(
    width, height, displaywidth=None, displayheight=None,
):
    """Scale every private X11 window by the display-global upload ratio."""
    width = max(1, int(width))
    height = max(1, int(height))
    maximumwidth, maximumheight = chromiumbackingsurface()
    scale = min(
        chromiumbackingratio(displaywidth, displayheight),
        maximumwidth / float(width),
        maximumheight / float(height),
    )
    if scale >= 1.0:
        return width, height
    # Even dimensions avoid odd video/canvas backing sizes while retaining the
    # logical aspect ratio to within one source pixel.
    scaledwidth = max(2, int(math.floor(width * scale)) & ~1)
    scaledheight = max(2, int(math.floor(height * scale)) & ~1)
    return min(maximumwidth, scaledwidth), min(maximumheight, scaledheight)


def outputtosourcepoint(x, y, outputwidth=None, outputheight=None, sourcewidth=None, sourceheight=None):
    outputwidth = max(1, int(WINW if outputwidth is None else outputwidth))
    outputheight = max(1, int(WINH if outputheight is None else outputheight))
    sourcewidth = max(1, int(ENGINEW if sourcewidth is None else sourcewidth))
    sourceheight = max(1, int(ENGINEH if sourceheight is None else sourceheight))
    x = max(0, min(outputwidth - 1, int(x)))
    y = max(0, min(outputheight - 1, int(y)))
    return (
        min(sourcewidth - 1, (x * sourcewidth) // outputwidth),
        min(sourceheight - 1, (y * sourceheight) // outputheight),
    )


def logicalmotioncommand(
    point, outputwidth=None, outputheight=None,
    sourcewidth=None, sourceheight=None,
):
    x, y = outputtosourcepoint(
        point[0],
        point[1],
        outputwidth,
        outputheight,
        sourcewidth,
        sourceheight,
    )
    return {"op": "motion", "x": x, "y": y}


def sourcerecttooutput(rect, outputwidth=None, outputheight=None, sourcewidth=None, sourceheight=None):
    outputwidth = max(1, int(WINW if outputwidth is None else outputwidth))
    outputheight = max(1, int(WINH if outputheight is None else outputheight))
    sourcewidth = max(1, int(ENGINEW if sourcewidth is None else sourcewidth))
    sourceheight = max(1, int(ENGINEH if sourceheight is None else sourceheight))
    left, top, width, height = [int(value) for value in rect[:4]]
    left = max(0, min(sourcewidth, left))
    top = max(0, min(sourceheight, top))
    right = max(left, min(sourcewidth, left + max(0, width)))
    bottom = max(top, min(sourceheight, top + max(0, height)))
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


LIBC = ctypes.CDLL(None, use_errno=True)


def logline(message, software='chromium'):
    try:
        # Operations owns Chromium's combined stdout/stderr log.  The
        # Chromium domain cannot append to /the one/logs directly, and the old
        # swallowed PermissionError made every engine failure invisible.
        print(formatlog(software, message), file=sys.stderr, flush=True)
    except Exception:
        pass


class JsonLineQueue:
    """A bounded, partial-write-safe queue for nonblocking JSON sockets.

    Only pointer motion and framebuffer damage may be coalesced. Every other
    record retains FIFO order. A record is encoded completely before it enters
    the byte queue, so a short write can never corrupt the following record.
    """

    def __init__(self, limit=TRANSPORTQUEUELIMIT, motion=False, damage=False):
        self.limit = max(4096, int(limit))
        self.motion = bool(motion)
        self.damage = bool(damage)
        if self.motion and self.damage:
            raise ValueError("a JSON transport queue may coalesce one record kind")
        self.buffer = bytearray()
        self.offset = 0
        self.pendingmotion = None
        self.pendingdamage = None
        self.counters = {
            "blocked_writes": 0,
            "short_writes": 0,
            "motion_coalesced": 0,
            "damage_coalesced": 0,
            "records_queued": 0,
            "bytes_sent": 0,
            "high_water": 0,
        }

    @staticmethod
    def _encoded(message):
        return (
            json.dumps(
                message,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            + b"\n"
        )

    def _queuedbytes(self):
        return max(0, len(self.buffer) - int(self.offset))

    def _appendencoded(self, encoded):
        encoded = bytes(encoded)
        if len(encoded) > self.limit or self._queuedbytes() + len(encoded) > self.limit:
            raise BufferError(
                f"nonblocking JSON transport exceeded its {self.limit}-byte bound"
            )
        if self.offset and (
            self.offset >= 65536
            or self.offset * 2 >= len(self.buffer)
            or len(self.buffer) + len(encoded) > self.limit
        ):
            del self.buffer[:self.offset]
            self.offset = 0
        self.buffer.extend(encoded)
        self.counters["records_queued"] += 1
        self.counters["high_water"] = max(
            self.counters["high_water"], self._queuedbytes()
        )

    def _append(self, message):
        self._appendencoded(self._encoded(message))

    def _coalescedmessage(self):
        if self.pendingmotion is not None:
            return "motion", self.pendingmotion
        if self.pendingdamage is not None:
            return "damage", self.pendingdamage
        return None, None

    def _materializecoalesced(self, force=False):
        kind, message = self._coalescedmessage()
        if message is None:
            return True
        if self._queuedbytes() and not force:
            return False
        encoded = self._encoded(message)
        if len(encoded) > self.limit or self._queuedbytes() + len(encoded) > self.limit:
            return False
        self._appendencoded(encoded)
        if kind == "motion":
            self.pendingmotion = None
        else:
            self.pendingdamage = None
        return True

    def queue(self, message):
        if not isinstance(message, dict):
            raise TypeError("JSON transport records must be objects")
        operation = str(message.get("op", ""))
        if self.motion and operation == "motion":
            if len(self._encoded(message)) > self.limit:
                raise BufferError("motion record exceeds the JSON transport bound")
            if self.pendingmotion is not None:
                self.counters["motion_coalesced"] += 1
            self.pendingmotion = dict(message)
            return True
        if self.damage and operation.lower() == "damage":
            try:
                left, top, width, height = [
                    int(value) for value in message.get("rect", [])[:4]
                ]
            except Exception as error:
                raise ValueError("damage record has invalid geometry") from error
            if width < 1 or height < 1:
                return True
            if len(self._encoded(message)) > self.limit:
                raise BufferError("damage record exceeds the JSON transport bound")
            right = left + width
            bottom = top + height
            if self.pendingdamage is None:
                self.pendingdamage = dict(message)
                self.pendingdamage["rect"] = [left, top, width, height]
            else:
                previous = self.pendingdamage["rect"]
                mergeleft = min(int(previous[0]), left)
                mergetop = min(int(previous[1]), top)
                mergeright = max(int(previous[0]) + int(previous[2]), right)
                mergebottom = max(int(previous[1]) + int(previous[3]), bottom)
                self.pendingdamage["rect"] = [
                    mergeleft,
                    mergetop,
                    mergeright - mergeleft,
                    mergebottom - mergetop,
                ]
                self.counters["damage_coalesced"] += 1
            return True
        # Capacity-check the pending state and transition as one ordered group.
        # A rejected transition must not partially commit the state ahead of it.
        encoded = self._encoded(message)
        _, pendingmessage = self._coalescedmessage()
        pendingencoded = (
            self._encoded(pendingmessage)
            if pendingmessage is not None
            else b""
        )
        if (
            len(pendingencoded) > self.limit
            or len(encoded) > self.limit
            or self._queuedbytes() + len(pendingencoded) + len(encoded) > self.limit
        ):
            raise BufferError(
                "nonblocking JSON transport is full before an ordered record"
            )
        if not self._materializecoalesced(force=True):
            raise BufferError(
                "nonblocking JSON transport is full before an ordered record"
            )
        self._appendencoded(encoded)
        return True

    def pending(self):
        return bool(
            self._queuedbytes()
            or self.pendingmotion is not None
            or self.pendingdamage is not None
        )

    def flush(self, target, budget=TRANSPORTFLUSHBUDGET):
        budget = max(1, int(budget))
        senttotal = 0
        while senttotal < budget:
            self._materializecoalesced()
            queued = self._queuedbytes()
            if not queued:
                if self.offset:
                    self.buffer.clear()
                    self.offset = 0
                break
            amount = min(queued, budget - senttotal)
            try:
                sent = target.send(
                    bytes(self.buffer[self.offset:self.offset + amount])
                )
            except (BlockingIOError, InterruptedError):
                self.counters["blocked_writes"] += 1
                break
            if sent is None:
                sent = 0
            sent = int(sent)
            if sent <= 0:
                raise BrokenPipeError("nonblocking JSON transport closed")
            if sent < amount:
                self.counters["short_writes"] += 1
            self.offset += sent
            if self.offset >= len(self.buffer):
                self.buffer.clear()
                self.offset = 0
            senttotal += sent
            self.counters["bytes_sent"] += sent
        return senttotal


def activateexistinginstance():
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(0.5)
    try:
        client.connect(INSTANCESOCKET)
        client.sendall(b'{"op":"activate"}\n')
        response = client.recv(256)
        return b'"ok":true' in response
    except OSError:
        return False
    finally:
        try:
            client.close()
        except Exception:
            pass


def claiminstance():
    """Own Chromium's shared runtime or activate the process that owns it."""
    global INSTANCELOCKFD, INSTANCEHOST, INSTANCEOWNED
    mkdir(SETTINGROOT, 0o700)
    deadline = time.monotonic() + 5.0
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    while True:
        descriptor = os.open(INSTANCELOCK, flags, 0o600)
        status = os.fstat(descriptor)
        if not stat.S_ISREG(status.st_mode):
            os.close(descriptor)
            raise RuntimeError("Chromium instance lock is not a regular file")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(descriptor)
            if activateexistinginstance():
                logline("forwarded launch to active chromium instance")
                return False
            if time.monotonic() >= deadline:
                raise RuntimeError("Chromium is active but its activation service is unavailable")
            time.sleep(0.05)
            continue
        INSTANCELOCKFD = descriptor
        INSTANCEOWNED = True
        break

    try:
        try:
            status = os.lstat(INSTANCESOCKET)
            if not stat.S_ISSOCK(status.st_mode):
                raise RuntimeError("Chromium instance socket path is not a socket")
            os.unlink(INSTANCESOCKET)
        except FileNotFoundError:
            pass
        host = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        host.bind(INSTANCESOCKET)
        os.chmod(INSTANCESOCKET, 0o600)
        host.listen(4)
        host.setblocking(False)
        INSTANCEHOST = host
        logline("chromium instance service ready")
        return True
    except Exception:
        releaseinstance()
        raise


def dropinheritedinstance():
    """Keep the engine child from extending the application-owner lock."""
    global INSTANCELOCKFD, INSTANCEHOST, INSTANCEOWNED
    if INSTANCEHOST is not None:
        try:
            INSTANCEHOST.close()
        except Exception:
            pass
        INSTANCEHOST = None
    if INSTANCELOCKFD is not None:
        try:
            os.close(INSTANCELOCKFD)
        except Exception:
            pass
        INSTANCELOCKFD = None
    INSTANCEOWNED = False


def activatewindow():
    global ACTIVATIONPENDING
    if WINID is None:
        ACTIVATIONPENDING = True
        return False
    sendws({"op": "MAP", "winid": WINID})
    sendws({"op": "RAISE", "winid": WINID})
    sendws({"op": "FOCUS_SET", "winid": WINID})
    enginecommand({"op": "focus"})
    ACTIVATIONPENDING = False
    logline(f"activated existing chromium window winid={WINID}")
    return True


def serviceinstanceactivations():
    if INSTANCEHOST is None:
        return
    while True:
        try:
            connection, _ = INSTANCEHOST.accept()
        except BlockingIOError:
            break
        except OSError as error:
            logline(f"chromium instance service failed: {error}")
            break
        try:
            connection.settimeout(0.25)
            request = connection.recv(1024)
            if b'"op":"activate"' in request:
                activatewindow()
                connection.sendall(b'{"ok":true}\n')
        except OSError:
            pass
        finally:
            try:
                connection.close()
            except Exception:
                pass


def releaseinstance():
    global INSTANCELOCKFD, INSTANCEHOST, INSTANCEOWNED
    owned = INSTANCEOWNED
    if INSTANCEHOST is not None:
        try:
            INSTANCEHOST.close()
        except Exception:
            pass
        INSTANCEHOST = None
    if owned:
        try:
            status = os.lstat(INSTANCESOCKET)
            if stat.S_ISSOCK(status.st_mode):
                os.unlink(INSTANCESOCKET)
        except FileNotFoundError:
            pass
        except Exception as error:
            logline(f"chromium instance socket cleanup failed: {error}")
    if INSTANCELOCKFD is not None:
        try:
            fcntl.flock(INSTANCELOCKFD, fcntl.LOCK_UN)
        except Exception:
            pass
        try:
            os.close(INSTANCELOCKFD)
        except Exception:
            pass
        INSTANCELOCKFD = None
    INSTANCEOWNED = False


def singletonpid(target):
    """Return Chrome's browser PID from a SingletonLock link target."""
    try:
        suffix = str(target).rsplit("-", 1)[1]
        process = int(suffix, 10)
        return process if process > 0 else None
    except (IndexError, TypeError, ValueError):
        return None


def chromiumprocessalive(process):
    """Check a lock owner through T1OS's process-driver namespace."""
    if process is None:
        return False
    try:
        os.kill(process, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    except OSError:
        return False
    commandpath = f"{PROCESSROOT}/{process}/cmdline"
    try:
        with open(commandpath, "rb") as stream:
            command = stream.read(65536).replace(b"\0", b" ").lower()
    except OSError:
        # A live but unreadable owner is safer to preserve than to race.
        return True
    return b"/chrome " in command


def gpucandidateruntimeready(
    provider,
    decoder_environment,
    library_path,
    launch_scope,
    graphics_environment=True,
):
    """Require one launch-scoped GPU process with no legacy decode authority."""
    return bool(
        provider
        and decoder_environment
        and library_path
        and launch_scope
        and graphics_environment
    )


def gpugraphicsmappingsready(mappings, mesa_gpu_contract=False):

    """Confirm the mapped libraries that prove the selected GPU path."""

    required = (
        ("egl", "gbm", "gallium", "gbm_backend")
        if mesa_gpu_contract
        else ("egl_vendor", "egl_core", "egl_gbm")
    )
    return all(bool(mappings.get(name)) for name in required)


def processdescendantof(process, ancestor):
    """Verify a live process belongs to one bounded Chromium process tree."""
    try:
        current = int(process)
        ancestor = int(ancestor)
    except (TypeError, ValueError):
        return False
    if current <= 0 or ancestor <= 0:
        return False

    visited = set()
    for _ in range(64):
        if current == ancestor:
            return True
        if current <= 1 or current in visited:
            return False
        visited.add(current)
        try:
            with open(
                f"{PROCESSROOT}/{current}/status",
                "r",
                encoding="utf-8",
                errors="replace",
            ) as stream:
                parent = next(
                    (
                        int(line.split(":", 1)[1].strip())
                        for line in stream
                        if line.startswith("PPid:")
                    ),
                    0,
                )
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            return False
        except (OSError, StopIteration, TypeError, ValueError):
            return False
        if parent <= 0 or parent == current:
            return False
        current = parent
    return False


def chromiumdiagnosticswitches(command):
    """Return a fixed allowlist of non-credential child switches."""

    if isinstance(command, bytes):
        parts = command.replace(b"\0", b" ").split()
        parts = [part.decode("utf-8", "replace") for part in parts]
    else:
        parts = str(command or "").split()
    prefixes = (
        "--type=",
        "--utility-sub-type=",
        "--use-gl=",
        "--use-angle=",
        "--use-cmd-decoder=",
        "--ozone-platform=",
    )
    return [
        part[:512]
        for part in parts
        if part.startswith(prefixes)
    ][:12]


def chromiumdiagnosticenvironment(environment):
    """Select only graphics/loader attestation variables for diagnostics."""

    prefixes = (
        b"LD_LIBRARY_PATH=",
        b"SANDBOX_LD_LIBRARY_PATH=",
        NVIDIAGPULIBRARYPATHVARIABLE.encode() + b"=",
        NVIDIAGPUEGLVENDORVARIABLE.encode() + b"=",
        NVIDIAGPUEGLEXTERNALVARIABLE.encode() + b"=",
        NVIDIAGPUGBMBACKENDSPATHVARIABLE.encode() + b"=",
        NVIDIAGPUGBMBACKENDVARIABLE.encode() + b"=",
        b"__EGL_VENDOR_LIBRARY_FILENAMES=",
        b"__EGL_EXTERNAL_PLATFORM_CONFIG_DIRS=",
        b"GBM_BACKENDS_PATH=",
        b"GBM_BACKEND=",
        b"LD_PRELOAD=",
        b"SANDBOX_LD_PRELOAD=",
        b"LIBVA_DRIVER_NAME=",
        b"LIBVA_DRIVERS_PATH=",
        b"NVD_BACKEND=",
        b"NVD_FORCE_INIT=",
        b"NVD_LOG=",
        b"NVD_SINGLE_BUFFER=",
        b"NVD_STATS=",
        b"LIBVA_MESSAGING_LEVEL=",
        b"CUDA_DISABLE_PERF_BOOST=",
        b"T1OS_CHROMIUM_NVIDIA_DEBUG=",
    )
    return sorted(
        value.decode("utf-8", "replace")
        for value in set(environment or ())
        if value.startswith(prefixes)
    )


def zygoteproviderstatus(
    expected_library_path="",
    expected_launch_id="",
    expected_browser_pid=0,
    expected_gpu_library_path="",
):
    """Measure the setuid-sandbox, zygote, and GPU preload chain."""
    expected_library_path = str(expected_library_path or "")
    expected_gpu_library_path = str(expected_gpu_library_path or "")
    expected_launch_id = str(expected_launch_id or "")
    try:
        expected_browser_pid = int(expected_browser_pid or 0)
    except (TypeError, ValueError):
        expected_browser_pid = 0
    expected_library = (
        b"LD_LIBRARY_PATH=" + expected_library_path.encode()
    )
    expected_saved_library = (
        b"SANDBOX_LD_LIBRARY_PATH=" + expected_library_path.encode()
    )
    expected_gpu_library = (
        NVIDIAGPULIBRARYPATHVARIABLE.encode()
        + b"="
        + expected_gpu_library_path.encode()
    )
    mesa_gpu_contract = (
        expected_gpu_library_path == MESAGRAPHICSLIBRARYPATH
    )
    nvidia_gpu_contract = (
        expected_gpu_library_path == NVIDIAGRAPHICSLIBRARYPATH
    )
    expected_saved_gpu_graphics = {
        (
            NVIDIAGPUEGLVENDORVARIABLE
            + "="
            + NVIDIAEGLVENDORFILE
        ).encode(),
        (
            NVIDIAGPUEGLEXTERNALVARIABLE
            + "="
            + NVIDIAGBMPATH
        ).encode(),
        (
            NVIDIAGPUGBMBACKENDSPATHVARIABLE
            + "="
            + NVIDIAGBMPATH
        ).encode(),
        (NVIDIAGPUGBMBACKENDVARIABLE + "=nvidia-drm").encode(),
    }
    gpu_graphics_mapping_markers = {
        "egl_vendor": b"/nvidia/libEGL_nvidia.so.0",
        "egl_core": b"/nvidia/libnvidia-eglcore.so.",
        "egl_gbm": b"/nvidia/libnvidia-egl-gbm.so.1",
        "gbm_backend": b"/nvidia/libnvidia-allocator.so.",
    }
    mesa_gpu_graphics_mapping_markers = {
        "egl": b"/the one/catalogue/graphics/libEGL.so.1",
        "gbm": b"/the one/catalogue/graphics/libgbm.so.1",
        "gallium": b"/the one/catalogue/graphics/libgallium-",
        "gbm_backend": b"/the one/catalogue/graphics/gbm/dri_gbm.so",
    }
    expected_preload = b"LD_PRELOAD=" + RUNTIMEPROVIDER.encode()
    expected_saved_preload = (
        b"SANDBOX_LD_PRELOAD=" + RUNTIMEPROVIDER.encode()
    )
    expected_launch = (
        CHROMIUMLAUNCHVARIABLE.encode()
        + b"="
        + expected_launch_id.encode()
    )
    status = {
        "found": False,
        "provider": False,
        "library_path": False,
        "active": False,
        "sandbox_found": False,
        "sandbox_environment": False,
        "gpu_found": False,
        "gpu_provider": False,
        "gpu_environment": False,
        "gpu_graphics_environment": False,
        "gpu_library_path": False,
        "gpu_runtime_ready": False,
        "gpu_runtime_pid": None,
        "gpu_launch_scope": False,
        "gpu_driver_loaded": False,
        "nvidia_broker_found": False,
        "nvidia_broker_pid": None,
        "utility_found": False,
        "utility_provider": False,
        "utility_library_path": False,
        "utility_launch_scope": False,
        "utility_runtime_ready": False,
        "utility_runtime_pid": None,
        "launch_scoped": bool(expected_launch_id),
        "browser_pid": expected_browser_pid or None,
        "browser_identity": False,
        "browser_environment": False,
        "browser_library_environment": [],
        "library_environment": [],
        "candidates": [],
        "scan_errors": [],
    }
    browser_environment = set()
    if expected_browser_pid > 0:
        try:
            with open(
                f"{PROCESSROOT}/{expected_browser_pid}/cmdline", "rb"
            ) as stream:
                browser_command = stream.read(65536).split(b"\0")
            with open(
                f"{PROCESSROOT}/{expected_browser_pid}/environ", "rb"
            ) as stream:
                browser_environment = set(
                    stream.read(1048576).split(b"\0")
                )
            # Chromium rewrites argv[0] for its process title. Bind this
            # launch to the kernel-owned executable link and the PID returned
            # by Popen; argv remains useful only as a well-formedness check.
            browser_executable = os.readlink(
                f"{PROCESSROOT}/{expected_browser_pid}/exe"
            ) == CHROMEEXECUTABLE
            browser_process = (
                browser_command
                and bool(browser_command[0])
                and browser_executable
            )
            status["browser_identity"] = bool(browser_process)
            browser_library = (
                not expected_library_path
                or expected_library in browser_environment
                or expected_saved_library in browser_environment
            )
            browser_gpu_library = (
                not expected_gpu_library_path
                or mesa_gpu_contract
                or (
                    nvidia_gpu_contract
                    and
                    expected_gpu_library in browser_environment
                    and expected_saved_gpu_graphics.issubset(
                        browser_environment
                    )
                )
            )
            browser_preload = (
                expected_preload in browser_environment
                or expected_saved_preload in browser_environment
            )
            browser_decoder = (
                b"LIBVA_DRIVER_NAME=nvidia" not in browser_environment
                and not any(
                    value.startswith((
                        b"NVD_",
                        b"CUDA_",
                        b"T1OS_CHROMIUM_NVIDIA_",
                    ))
                    for value in browser_environment
                )
            )
            status["browser_environment"] = bool(
                browser_process
                and browser_library
                and browser_gpu_library
                and browser_preload
                and browser_decoder
                and (
                    not expected_launch_id
                    or expected_launch in browser_environment
                )
            )
            status["browser_library_environment"] = (
                chromiumdiagnosticenvironment(browser_environment)
            )
        except (
            FileNotFoundError,
            OSError,
            PermissionError,
            ProcessLookupError,
        ):
            browser_environment = set()
    try:
        entries = os.scandir(PROCESSROOT)
    except OSError:
        return status
    with entries:
        for entry in entries:
            if not entry.name.isdigit():
                continue
            try:
                try:
                    with open(entry.path + "/comm", "rb") as stream:
                        process_name = stream.read(64).strip()
                except (FileNotFoundError, PermissionError, OSError):
                    process_name = b""
                if process_name == b"t1os-nv-broker":
                    if (
                        expected_browser_pid > 0
                        and processdescendantof(
                            int(entry.name), expected_browser_pid,
                        )
                    ):
                        status["nvidia_broker_found"] = True
                        status["nvidia_broker_pid"] = int(entry.name)
                    continue
                with open(entry.path + "/cmdline", "rb") as stream:
                    command = stream.read(65536).replace(b"\0", b" ")
                sandbox = (
                    b"--type=zygote" in command
                    and (
                        command.startswith(b"./chrome-sandbox ")
                        or b"/chrome-sandbox " in command
                    )
                )
                zygote = b"--type=zygote" in command and not sandbox
                gpu = b"--type=gpu-process" in command
                utility = (
                    b"--type=utility " in command
                    and b"--utility-sub-type=" in command
                )
                if not (sandbox or zygote or gpu or utility):
                    continue
                try:
                    with open(entry.path + "/maps", "rb") as stream:
                        mappings = stream.read()
                    with open(entry.path + "/environ", "rb") as stream:
                        environment = set(
                            stream.read(1048576).split(b"\0")
                        )
                except (
                    FileNotFoundError,
                    OSError,
                    PermissionError,
                    ProcessLookupError,
                ) as error:
                    status["scan_errors"].append({
                        "pid": int(entry.name),
                        "switches": chromiumdiagnosticswitches(command),
                        "error": (
                            f"{type(error).__name__}: {error}"
                        )[:1024],
                    })
                    continue
                process_parent = None
                process_state = "unknown"
                process_no_new_privileges = None
                process_seccomp = None
                try:
                    with open(
                        entry.path + "/status",
                        "r",
                        encoding="utf-8",
                        errors="replace",
                    ) as stream:
                        for line in stream:
                            if line.startswith("PPid:"):
                                process_parent = int(
                                    line.split(":", 1)[1].strip()
                                )
                            elif line.startswith("State:"):
                                process_state = line.split(
                                    ":", 1
                                )[1].strip()[:64]
                            elif line.startswith("NoNewPrivs:"):
                                process_no_new_privileges = int(
                                    line.split(":", 1)[1].strip()
                                )
                            elif line.startswith("Seccomp:"):
                                process_seccomp = int(
                                    line.split(":", 1)[1].strip()
                                )
                except (OSError, TypeError, ValueError):
                    pass
                try:
                    executable_identity = (
                        os.readlink(entry.path + "/exe")
                        == CHROMEEXECUTABLE
                    )
                except OSError:
                    executable_identity = False
                provider = RUNTIMEPROVIDER.encode() in mappings
                candidate_library_path = (
                    expected_gpu_library_path
                    if gpu and expected_gpu_library_path
                    else expected_library_path
                )
                candidate_library = (
                    b"LD_LIBRARY_PATH=" + candidate_library_path.encode()
                )
                candidate_saved_library = (
                    b"SANDBOX_LD_LIBRARY_PATH="
                    + candidate_library_path.encode()
                )
                library = (
                    not candidate_library_path
                    or candidate_library in environment
                    or candidate_saved_library in environment
                )
                preload = (
                    expected_preload in environment
                    or expected_saved_preload in environment
                )
                decoder_environment = (
                    b"LIBVA_DRIVER_NAME=nvidia" not in environment
                    and not any(
                        value.startswith((
                            b"NVD_",
                            b"CUDA_",
                            b"T1OS_CHROMIUM_NVIDIA_",
                        ))
                        for value in environment
                    )
                )
                process_launch_scope = (
                    not expected_launch_id
                    or expected_launch in environment
                )
                lineage_scope = bool(
                    status["browser_identity"]
                    and processdescendantof(
                        int(entry.name),
                        expected_browser_pid,
                    )
                )
                launch_scope = process_launch_scope or lineage_scope
                live_gpu_graphics = {
                    "egl_vendor": (
                        "__EGL_VENDOR_LIBRARY_FILENAMES="
                        + NVIDIAEGLVENDORFILE
                    ).encode() in environment,
                    "egl_external": (
                        "__EGL_EXTERNAL_PLATFORM_CONFIG_DIRS="
                        + NVIDIAGBMPATH
                    ).encode() in environment,
                    "gbm_path": (
                        "GBM_BACKENDS_PATH=" + NVIDIAGBMPATH
                    ).encode() in environment,
                    "gbm_backend": b"GBM_BACKEND=nvidia-drm" in environment,
                }
                saved_gpu_graphics = {
                    "egl_vendor": (
                        NVIDIAGPUEGLVENDORVARIABLE
                        + "="
                        + NVIDIAEGLVENDORFILE
                    ).encode() in environment,
                    "egl_external": (
                        NVIDIAGPUEGLEXTERNALVARIABLE
                        + "="
                        + NVIDIAGBMPATH
                    ).encode() in environment,
                    "gbm_path": (
                        NVIDIAGPUGBMBACKENDSPATHVARIABLE
                        + "="
                        + NVIDIAGBMPATH
                    ).encode() in environment,
                    "gbm_backend": (
                        NVIDIAGPUGBMBACKENDVARIABLE + "=nvidia-drm"
                    ).encode() in environment,
                }
                selected_mapping_markers = (
                    mesa_gpu_graphics_mapping_markers
                    if mesa_gpu_contract
                    else gpu_graphics_mapping_markers
                )
                gpu_graphics_mappings = {
                    name: marker in mappings
                    for name, marker in selected_mapping_markers.items()
                }
                mapping_graphics_ready = gpugraphicsmappingsready(
                    gpu_graphics_mappings,
                    mesa_gpu_contract,
                )
                live_graphics_ready = (
                    live_gpu_graphics["gbm_path"]
                    if mesa_gpu_contract
                    else all(live_gpu_graphics.values())
                )
                gpu_graphics_environment = bool(
                    not expected_gpu_library_path
                    or live_graphics_ready
                    or mapping_graphics_ready
                )
                graphics_environment_source = (
                    "not-required"
                    if not expected_gpu_library_path
                    else "live-environment"
                    if live_graphics_ready
                    else "mapped-libraries"
                    if mapping_graphics_ready
                    else "missing"
                )
                if lineage_scope:
                    # Chromium relocates its environment strings before
                    # rewriting process titles, so the kernel's original
                    # process-environment view becomes zero-filled even though
                    # libc retains the values. Bind descendants to the exact
                    # Popen PID, kernel-owned executable identity, preserved
                    # process tree, and provider mapping loaded at exec time.
                    library = library or provider
                    decoder_environment = (
                        decoder_environment
                        or status["browser_environment"]
                    )
                candidate_gpu_ready = (
                    gpu
                    and gpucandidateruntimeready(
                        provider,
                        decoder_environment,
                        library,
                        launch_scope,
                        gpu_graphics_environment,
                    )
                )
                candidate_utility_ready = bool(
                    utility
                    and provider
                    and library
                    and launch_scope
                )
                candidate_runtime_ready = (
                    candidate_gpu_ready or candidate_utility_ready
                )
                candidate_environment = chromiumdiagnosticenvironment(
                    environment
                )
                status["candidates"].append({
                    "pid": int(entry.name),
                    "ppid": process_parent,
                    "state": process_state,
                    "no_new_privileges": process_no_new_privileges,
                    "seccomp": process_seccomp,
                    "kind": (
                        "sandbox" if sandbox
                        else "zygote" if zygote
                        else "gpu" if gpu
                        else "utility"
                    ),
                    "switches": chromiumdiagnosticswitches(command),
                    "executable_identity": executable_identity,
                    "browser_descendant": lineage_scope,
                    "provider": provider,
                    "library_path": library,
                    "preload": preload,
                    "decoder_environment": decoder_environment,
                    "gpu_graphics_environment": gpu_graphics_environment,
                    "graphics_environment_source": (
                        graphics_environment_source
                    ),
                    "live_gpu_graphics": live_gpu_graphics,
                    "saved_gpu_graphics": saved_gpu_graphics,
                    "gpu_graphics_mappings": gpu_graphics_mappings,
                    "launch_scope": launch_scope,
                    "environment_source": (
                        "process"
                        if process_launch_scope
                        else "browser-lineage"
                        if lineage_scope
                        else "unverified"
                    ),
                    "runtime_ready": candidate_runtime_ready,
                    "library_environment": candidate_environment,
                })

                # Preserve all candidates above for diagnosis, but never let a
                # stale or concurrent Chromium launch satisfy this launch.
                if not launch_scope:
                    continue

                if sandbox:
                    status["sandbox_found"] = True
                    sandbox_environment = (
                        library and preload and decoder_environment
                    )
                    status["sandbox_environment"] = (
                        status["sandbox_environment"] or sandbox_environment
                    )
                    status["library_path"] = (
                        status["library_path"] or library
                    )
                    for value in candidate_environment:
                        if value not in status["library_environment"]:
                            status["library_environment"].append(value)
                elif zygote:
                    status["found"] = True
                    status["provider"] = status["provider"] or provider
                elif gpu:
                    status["gpu_found"] = True
                    status["gpu_launch_scope"] = True
                    status["gpu_provider"] = (
                        status["gpu_provider"] or provider
                    )
                    status["gpu_environment"] = (
                        status["gpu_environment"] or decoder_environment
                    )
                    status["gpu_graphics_environment"] = (
                        status["gpu_graphics_environment"]
                        or gpu_graphics_environment
                    )
                    status["gpu_library_path"] = (
                        status["gpu_library_path"] or library
                    )
                    status["gpu_driver_loaded"] = (
                        status["gpu_driver_loaded"]
                        or b"nvidia_drv_video.so" in mappings
                    )
                    if candidate_gpu_ready:
                        status["gpu_runtime_ready"] = True
                        status["gpu_runtime_pid"] = int(entry.name)
                else:
                    status["utility_found"] = True
                    status["utility_launch_scope"] = True
                    status["utility_provider"] = (
                        status["utility_provider"] or provider
                    )
                    status["utility_library_path"] = (
                        status["utility_library_path"] or library
                    )
                    if candidate_utility_ready:
                        status["utility_runtime_ready"] = True
                        status["utility_runtime_pid"] = int(entry.name)
            except (FileNotFoundError, PermissionError, ProcessLookupError):
                continue
    status["library_environment"].sort()
    status["active"] = (
        status["found"]
        and status["provider"]
        and status["sandbox_found"]
        and status["sandbox_environment"]
        and status["gpu_found"]
        and status["gpu_provider"]
        and status["utility_found"]
        and status["utility_provider"]
    )
    # SUID-helper lifecycle and process-driver observability vary across the
    # sandbox transition. Production and diagnostic pass/fail decisions are
    # therefore proven from the launch-scoped live GPU process. Utility
    # processes fork from Chromium's measured zygotes and never own a display
    # surface; their visibility remains a diagnostic, not a rendering gate.
    # `active` remains auxiliary sandbox/zygote observability only.
    return status


def zygoteprovideractive(
    expected_library_path="",
    expected_launch_id="",
    expected_browser_pid=0,
    expected_gpu_library_path="",
):
    """Confirm that a live zygote retained T1OS preload and library paths."""
    return zygoteproviderstatus(
        expected_library_path,
        expected_launch_id,
        expected_browser_pid,
        expected_gpu_library_path,
    ).get("active", False)


def logchromiumprocesses():
    """Record bounded process state when Chromium stalls before its window."""
    reported = 0
    try:
        entries = os.scandir(PROCESSROOT)
    except OSError as error:
        logline(f"chromium process snapshot unavailable: {error}")
        return
    with entries:
        for entry in entries:
            if not entry.name.isdigit():
                continue
            try:
                with open(entry.path + "/cmdline", "rb") as stream:
                    command = stream.read(4096).replace(b"\0", b" ").strip()
                if not any(name in command for name in (
                    b"/chrome", b"chrome-sandbox"
                )):
                    continue
                wanted = {}
                with open(entry.path + "/status", "r", encoding="utf-8") as stream:
                    for line in stream:
                        name, _, value = line.partition(":")
                        if name in ("Name", "State", "Pid", "PPid", "NSpid"):
                            wanted[name] = value.strip()
                try:
                    with open(entry.path + "/wchan", "r", encoding="utf-8") as stream:
                        waitchannel = stream.read(128).strip()
                except OSError:
                    waitchannel = "unavailable"
                logline(
                    f"chromium process snapshot pid={entry.name} "
                    f"state={wanted.get('State', 'unknown')} "
                    f"ppid={wanted.get('PPid', 'unknown')} "
                    f"nspid={wanted.get('NSpid', 'unknown')} "
                    f"wchan={waitchannel or 'none'} "
                    "switches="
                    + json.dumps(
                        chromiumdiagnosticswitches(command),
                        separators=(",", ":"),
                    )
                )
                reported += 1
                if reported >= 32:
                    logline("chromium process snapshot limited to 32 entries")
                    break
            except (FileNotFoundError, PermissionError, ProcessLookupError):
                continue


def loggpucandidatediagnostics(runtime_status, limit=16):
    """Persist a bounded, credential-free explanation of GPU gate failure."""

    runtime_status = (
        runtime_status if isinstance(runtime_status, dict) else {}
    )
    browser_environment = runtime_status.get(
        "browser_library_environment"
    ) or []
    logline(
        "chromium GPU contract diagnostic browser "
        f"pid={runtime_status.get('browser_pid')} "
        f"identity={bool(runtime_status.get('browser_identity'))} "
        f"environment={bool(runtime_status.get('browser_environment'))} "
        "loader_environment="
        + json.dumps(browser_environment[:32], separators=(",", ":"))[:4096]
    )
    candidates = list(runtime_status.get("candidates") or ())
    for candidate in candidates[:max(0, min(int(limit), 32))]:
        if not isinstance(candidate, dict):
            continue
        required = [
            ("provider", candidate.get("provider")),
            ("library", candidate.get("library_path")),
            ("launch-scope", candidate.get("launch_scope")),
        ]
        if candidate.get("kind") == "gpu":
            required.extend([
                ("decoder-clean", candidate.get("decoder_environment")),
                (
                    "measured-egl-gbm",
                    candidate.get("gpu_graphics_environment"),
                ),
            ])
        missing = [name for name, value in required if not bool(value)]
        evidence = {
            "live": candidate.get("live_gpu_graphics") or {},
            "saved": candidate.get("saved_gpu_graphics") or {},
            "mapped": candidate.get("gpu_graphics_mappings") or {},
            "environment": (
                candidate.get("library_environment") or []
            )[:32],
            "switches": (candidate.get("switches") or [])[:12],
        }
        logline(
            "chromium GPU contract candidate "
            f"pid={candidate.get('pid')} ppid={candidate.get('ppid')} "
            f"state={candidate.get('state', 'unknown')} "
            f"no_new_privileges={candidate.get('no_new_privileges')} "
            f"seccomp={candidate.get('seccomp')} "
            f"kind={candidate.get('kind', 'unknown')} "
            f"executable={bool(candidate.get('executable_identity'))} "
            f"descendant={bool(candidate.get('browser_descendant'))} "
            f"provider={bool(candidate.get('provider'))} "
            f"library={bool(candidate.get('library_path'))} "
            f"preload={bool(candidate.get('preload'))} "
            f"decoder_clean={bool(candidate.get('decoder_environment'))} "
            f"environment_source={candidate.get('environment_source', 'unknown')} "
            f"graphics_source="
            f"{candidate.get('graphics_environment_source', 'unknown')} "
            f"runtime_ready={bool(candidate.get('runtime_ready'))} "
            f"missing={','.join(missing) if missing else 'none'} "
            "evidence="
            + json.dumps(evidence, sort_keys=True, separators=(",", ":"))[:8192]
        )
    if len(candidates) > limit:
        logline(
            "chromium GPU contract candidate diagnostics limited "
            f"reported={limit} total={len(candidates)}"
        )
    for error in list(runtime_status.get("scan_errors") or ())[:16]:
        logline(
            "chromium GPU contract scan error "
            + json.dumps(error, sort_keys=True, separators=(",", ":"))[:2048]
        )


def clearstaleprofilelock():
    """Remove only dead Chrome singleton entries from the persistent profile."""
    lockpath = os.path.join(PROFILE, "SingletonLock")
    try:
        target = os.readlink(lockpath)
    except FileNotFoundError:
        target = ""
    except OSError:
        target = ""
    process = singletonpid(target)
    if target and chromiumprocessalive(process):
        raise RuntimeError(
            f"cannot repair the Chromium profile while process {process} owns it"
        )

    removed = []
    for name in SINGLETONNAMES:
        path = os.path.join(PROFILE, name)
        try:
            # Singleton entries are files or links.  Never recurse through a
            # persistent profile entry supplied by the browser.
            os.unlink(path)
            removed.append(name)
        except FileNotFoundError:
            pass
        except IsADirectoryError:
            raise RuntimeError(
                f"Chromium profile singleton is unexpectedly a directory: {path}"
            )
    if removed:
        owner = f" process={process}" if process is not None else ""
        logline(f"removed stale chromium profile singleton entries={','.join(removed)}{owner}")
    return bool(removed)


def atomictext(path, text, mode=0o600):
    directory = os.path.dirname(path)
    os.makedirs(directory, mode=0o700, exist_ok=True)
    temporary = f"{path}.temporary-{os.getpid()}"
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def validategoogleapicredentials(value):
    """Validate the exact non-logging Google credential runtime contract."""

    if not isinstance(value, dict) or set(value) - {
        "format",
        *GOOGLEAPICREDENTIALENVIRONMENT,
    }:
        raise ValueError("Google API credential document has unknown fields")
    if type(value.get("format")) is not int or value.get("format") != 1:
        raise ValueError("Google API credential document format is unsupported")

    def credential(name, *, required=False, maximum=512):
        configured = value.get(name)
        if configured is None and not required:
            return None
        if not isinstance(configured, str):
            raise ValueError(f"Google API credential {name} is not a string")
        if (
            len(configured) < 16
            or len(configured) > int(maximum)
            or configured.startswith("replace-with-")
            or any(ord(character) < 0x21 or ord(character) > 0x7e
                   for character in configured)
        ):
            raise ValueError(f"Google API credential {name} is malformed")
        return configured

    result = {
        "format": 1,
        "google_api_key": credential(
            "google_api_key", required=True, maximum=256,
        ),
    }
    client_id = credential("google_default_client_id")
    client_secret = credential(
        "google_default_client_secret", maximum=256,
    )
    if (client_id is None) != (client_secret is None):
        raise ValueError(
            "Google OAuth client ID and client secret must be configured together"
        )
    if client_id is not None:
        result["google_default_client_id"] = client_id
        result["google_default_client_secret"] = client_secret
    return result


def loadgoogleapicredentials(path=None):
    """Read architect-controlled Google credentials without following links."""

    path = str(path or GOOGLEAPICREDENTIALFILE)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if not nofollow:
        raise RuntimeError("protected Google credentials require O_NOFOLLOW")
    descriptor = None
    try:
        descriptor = os.open(path, flags | nofollow)
        status = os.fstat(descriptor)
        mode = stat.S_IMODE(status.st_mode)
        if not stat.S_ISREG(status.st_mode):
            raise RuntimeError("Google API credential path is not a regular file")
        if status.st_uid == 0:
            if status.st_gid != ENGINEGID or mode not in (0o400, 0o440):
                raise RuntimeError(
                    "root-owned Google API credentials must be root:engine 0400/0440"
                )
        elif status.st_uid == os.geteuid():
            if mode != 0o600:
                raise RuntimeError(
                    "user-owned Google API credentials must have mode 0600"
                )
        else:
            raise RuntimeError("Google API credential owner is not authorized")
        encoded = os.read(descriptor, GOOGLEAPICREDENTIALMAXBYTES + 1)
        if len(encoded) > GOOGLEAPICREDENTIALMAXBYTES:
            raise RuntimeError("Google API credential document is too large")
        try:
            value = json.loads(encoded.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RuntimeError("Google API credential document is invalid") from error
        return validategoogleapicredentials(value)
    except FileNotFoundError:
        return None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def applygoogleapicredentials(environment, credentials):
    """Copy validated credentials into only Chromium's child environment."""

    updated = dict(environment)
    if credentials is None:
        updated[GOOGLEAPICREDENTIALENVIRONMENT["google_api_key"]] = (
            GOOGLEAPIKEYSUPPRESSIONVALUE
        )
        return updated
    validated = validategoogleapicredentials(credentials)
    for name, value in validated.items():
        if name == "format":
            continue
        updated[GOOGLEAPICREDENTIALENVIRONMENT[name]] = value
    return updated


def configureprofilesession(restore_session, single_root=False):
    """Apply T1OS startup policy through Chromium's real profile preference."""

    defaultprofile = os.path.join(PROFILE, "Default")
    # This function runs in the root supervisor after prepareruntime() has
    # repaired the persistent tree, while Chrome itself drops to ENGINEUID.
    # A first launch therefore needs the newly-created Default directory to be
    # handed to Chromium before Preferences or any SQLite stores are opened.
    mkdir(defaultprofile, 0o700)
    safechown(defaultprofile)
    preferencepath = os.path.join(defaultprofile, "Preferences")
    if os.path.islink(preferencepath):
        raise RuntimeError("Chromium Preferences cannot be a symbolic link")
    preferences = {}
    try:
        if os.path.getsize(preferencepath) > 64 * 1024 * 1024:
            raise RuntimeError("Chromium Preferences exceeds the safety limit")
        with open(preferencepath, "r", encoding="utf-8") as stream:
            preferences = json.load(stream)
        if not isinstance(preferences, dict):
            raise ValueError("Chromium Preferences is not an object")
    except FileNotFoundError:
        pass
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise RuntimeError(
            f"could not apply Chromium startup policy: {error}"
        ) from error

    session = preferences.get("session")
    if not isinstance(session, dict):
        session = {}
        preferences["session"] = session
    # Chromium's documented preference values are 1=last session and
    # 5=new-tab/default. Presentation protocol v1 owns one visible root, so it
    # must never restore several previous top-level windows automatically.
    value = 5 if single_root or not restore_session else 1
    session["restore_on_startup"] = value
    atomictext(
        preferencepath,
        json.dumps(preferences, separators=(",", ":"), sort_keys=True),
    )
    safechown(preferencepath)
    logline(
        "chromium startup session policy "
        f"restore={'disabled-single-root' if single_root else bool(restore_session)} "
        f"preference={value}"
    )
    return value


def mastername():
    """Return the authenticated T1OS username without guessing another user."""
    try:
        with open(SESSIONIDENTITYFILE, "rb") as stream:
            raw = stream.read(SESSIONIDENTITYMAXBYTES + 1)
    except OSError as error:
        raise RuntimeError(f"could not read the active T1OS username: {error}") from error

    if len(raw) > SESSIONIDENTITYMAXBYTES:
        raise RuntimeError("the active T1OS session identity is too large")

    try:
        identity = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise RuntimeError("the active T1OS session identity is invalid") from error

    if (
        not isinstance(identity, dict) or
        set(identity) != {"format", "username"} or
        type(identity.get("format")) is not int or
        identity.get("format") != 1
    ):
        raise RuntimeError("the active T1OS session identity is invalid")

    username = identity.get("username")
    if not isinstance(username, str) or not SESSIONUSERNAME.fullmatch(username):
        raise RuntimeError("the active T1OS username is invalid")

    userroot = os.path.join("/master", username)
    if not os.path.isdir(userroot) or os.path.islink(userroot):
        raise RuntimeError(f"the active T1OS user directory is unavailable: {userroot}")
    return username


def flashroot():
    return f"/master/{mastername()}/flash"


def downloaddir():
    return os.path.join(flashroot(), "downloads")


def defaultsettings():
    return {
        "format": 2,
        "home_page": "about:blank",
        "restore_session": True,
        "frames_per_second": 60,
        "maximum_width": MAXWIDTH,
        "maximum_height": MAXHEIGHT,
    }


def validatesettings(value):
    settings = defaultsettings()
    previousformat = 0
    if isinstance(value, dict):
        try:
            previousformat = int(value.get("format", 0))
        except Exception:
            previousformat = 0
        for name in settings:
            if name in value:
                settings[name] = value[name]
    home = str(settings.get("home_page", "about:blank")).strip()
    if not home or len(home) > 8192:
        home = "about:blank"
    settings["home_page"] = home
    settings["restore_session"] = bool(settings.get("restore_session", True))
    settings["frames_per_second"] = max(15, min(60, int(settings.get("frames_per_second", 60))))
    if previousformat < 2 and settings["frames_per_second"] == 30:
        settings["frames_per_second"] = 60
    settings["maximum_width"] = max(BASEWIDTH, min(7680, int(settings.get("maximum_width", MAXWIDTH))))
    settings["maximum_height"] = max(BASEHEIGHT, min(4320, int(settings.get("maximum_height", MAXHEIGHT))))
    settings["format"] = 2
    return settings


def loadsettings():
    if not os.path.lexists(SETTINGROOT) and os.path.isdir(LEGACYSETTINGROOT) and not os.path.islink(LEGACYSETTINGROOT):
        os.replace(LEGACYSETTINGROOT, SETTINGROOT)
    os.makedirs(SETTINGROOT, mode=0o700, exist_ok=True)
    settings = defaultsettings()
    try:
        with open(SETTINGFILE, "r", encoding="utf-8") as stream:
            settings = validatesettings(json.load(stream))
    except FileNotFoundError:
        pass
    except Exception as error:
        logline(f"settings rejected: {error}")
    atomictext(SETTINGFILE, json.dumps(settings, indent=2, sort_keys=True) + "\n")
    return settings


def runtimefiles():
    required = [
        PROGRAM + "/chrome",
        SANDBOX,
        TOOLS + "/dash",
        TOOLS + "/Xvfb",
        TOOLS + "/t1os-xwm",
        TOOLS + "/xclip",
        TOOLS + "/xdotool",
        TOOLS + "/t1os-xinput",
        TOOLS + "/xkbcomp",
        TOOLS + "/xrandr",
        LIBRARIES + "/ld-linux-x86-64.so.2",
        LIBRARIES + "/libX11.so.6",
        LIBRARIES + "/libXdamage.so.1",
        LIBRARIES + "/libXfixes.so.3",
        FONTCONFIGFILE,
        FONTROOT + "/noto/NotoSans-Regular.ttf",
        FONTROOT + "/noto/NotoSerif-Regular.ttf",
        FONTROOT + "/noto/NotoSansMono-Regular.ttf",
        FONTROOT + "/noto/NotoColorEmoji.ttf",
        FONTROOT + "/croscore/Arimo-Regular.ttf",
        FONTROOT + "/croscore/Tinos-Regular.ttf",
        FONTROOT + "/croscore/Cousine-Regular.ttf",
        PATHPROVIDER,
    ]
    missing = [path for path in required if not os.path.isfile(path)]
    if missing:
        raise FileNotFoundError("chromium engine is incomplete: " + ", ".join(missing))

    sandboxstatus = os.stat(SANDBOX, follow_symlinks=False)
    sandboxmode = stat.S_IMODE(sandboxstatus.st_mode)
    if not stat.S_ISREG(sandboxstatus.st_mode):
        raise PermissionError("chromium sandbox is not a regular file")
    if sandboxstatus.st_uid != 0 or sandboxstatus.st_gid != 0 or sandboxmode != 0o4755:
        raise PermissionError(
            f"chromium sandbox must be owned by 0:0 with mode 4755; "
            f"found {sandboxstatus.st_uid}:{sandboxstatus.st_gid} mode {sandboxmode:04o}"
        )


def loadgraphics():
    global GFX
    sys.path.insert(0, "/the one/build")
    import graphics.graphics as graphicsmodule
    GFX = graphicsmodule


def sendws(message):
    if WSOCK is None or WSOUTPUT is None:
        return False
    try:
        WSOUTPUT.queue(message)
        return True
    except BufferError as error:
        # Continuing after losing a control record would leave an apparently
        # live but unusable browser. Make the transport failure explicit.
        raise ConnectionError(f"window server output queue failed: {error}") from error


def flushwsoutput():
    if WSOCK is None or WSOUTPUT is None:
        return 0
    try:
        return WSOUTPUT.flush(WSOCK)
    except (BrokenPipeError, ConnectionResetError) as error:
        raise ConnectionError(f"window server output failed: {error}") from error


def drainjsonoutput(queue, target, timeout=0.5):
    if queue is None or target is None:
        return True
    deadline = time.monotonic() + max(0.0, float(timeout))
    while queue.pending():
        try:
            queue.flush(target)
        except (BrokenPipeError, ConnectionResetError, OSError):
            return False
        if not queue.pending():
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0.0:
            return False
        try:
            _, writable, _ = select.select(
                [], [target], [], min(0.05, remaining)
            )
        except Exception:
            return False
        if not writable:
            continue
    return True


def recvws():
    global WSBUFFER
    if WSOCK is None:
        return []
    try:
        data = WSOCK.recv(65536)
        if not data:
            raise ConnectionError("window server disconnected")
        WSBUFFER += data
    except BlockingIOError:
        return []
    messages = []
    while b"\n" in WSBUFFER:
        line, WSBUFFER = WSBUFFER.split(b"\n", 1)
        if not line:
            continue
        try:
            message = json.loads(line.decode("utf-8"))
            if isinstance(message, dict):
                messages.append(message)
        except Exception as error:
            logline(f"window message rejected: {error}")
    return messages


def connectwindow():
    global WSOCK, WSOUTPUT
    WSOCK = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    WSOCK.connect(WINDOWSOCK)
    WSOCK.setblocking(False)
    WSOUTPUT = JsonLineQueue(damage=True)
    sendws({"op": "HELLO"})
    sendws({"op": "SUBSCRIBE", "types": ["fbsize"]})
    flushwsoutput()


def createwindow():
    scale = chromedevicescale(SCREENW, SCREENH)
    width, height = initialwindowsize(SCREENW, SCREENH)
    sendws({
        "op": "CREATE_WINDOW",
        "role": APPROLE,
        "title": APPNAME,
        "current": browserwindowname(CONFIG.get("home_page", "about:blank")),
        "path": APPPATH,
        "w": width,
        "h": height,
        "x": 50,
        "y": 45,
        "decoration": "client",
        "client_chrome_height": max(40, int(round(BASECHROMEHEIGHT * scale))),
        "client_chrome_drag_width": max(96, int(round(BASECHROMEDRAGWIDTH * scale))),
        "client_chrome_controls": "chromium",
        "pid": os.getpid(),
    })


def browserwindowname(title):
    name = " ".join(str(title or "").split()).strip()
    for suffix in (" - Chromium", " – Chromium", " — Chromium"):
        if name.endswith(suffix):
            name = name[:-len(suffix)].rstrip()
            break
    if name.lower() in ("", "about:blank", "chrome://newtab/"):
        return "new tab"
    return name[:128]


def setbrowserwindowname(title):
    global BROWSERTITLE
    name = browserwindowname(title)
    if WINID is None or name == BROWSERTITLE:
        return
    BROWSERTITLE = name
    sendws({
        "op": "WINDOW_CURRENT_SET",
        "winid": WINID,
        "current": name,
    })
    if os.environ.get("T1OS_VM_TEST") == "1":
        logline(
            "chromium document title changed title="
            + json.dumps(name, ensure_ascii=True)
        )


def setbrowserfullscreen(enabled):
    global FULLSCREENREQUEST
    enabled = bool(enabled)
    if WINID is None or FULLSCREENREQUEST is not None:
        return False
    if enabled == FULLSCREEN:
        return True
    if not sendws({
        "op": "WINDOW_FULLSCREEN_SET",
        "winid": WINID,
        "fullscreen": enabled,
    }):
        return False
    FULLSCREENREQUEST = enabled
    return True


def setbrowsercursor(visible, force=False):
    global FULLSCREENCURSORVISIBLE
    visible = bool(visible)
    if not force and visible == FULLSCREENCURSORVISIBLE:
        return True
    if WINID is None:
        FULLSCREENCURSORVISIBLE = visible
        return False
    if not sendws({
        "op": "CURSOR_MODE_SET",
        "winid": WINID,
        "mode": BROWSERCURSORMODE if visible else "hidden",
    }):
        return False
    FULLSCREENCURSORVISIBLE = visible
    return True


def setbrowsercursormode(name):
    global BROWSERCURSORMODE

    token = str(name or "").strip().lower().replace("-", "_")
    if any(value in token for value in ("hand", "link", "pointer")):
        mode = "link"
    elif any(value in token for value in ("text", "xterm", "ibeam", "i_beam")):
        mode = "text"
    elif any(value in token for value in ("wait", "watch", "progress", "busy")):
        mode = "busy"
    else:
        mode = "arrow"

    if mode == BROWSERCURSORMODE:
        return

    BROWSERCURSORMODE = mode

    if os.environ.get("T1OS_VM_TEST") == "1":
        logline(f"chromium cursor mode changed mode={mode}")

    if WINID is not None and (not FULLSCREEN or FULLSCREENCURSORVISIBLE):
        sendws({
            "op": "CURSOR_MODE_SET",
            "winid": WINID,
            "mode": mode,
        })


def cursorimagehash(width, height, xhot, yhot, pixels):
    value = 1469598103934665603
    for item in (width, height, xhot, yhot):
        value ^= int(item) & 0xFFFFFFFF
        value = (value * 1099511628211) & 0xFFFFFFFFFFFFFFFF
    for item in pixels:
        value ^= int(item) & 0xFFFFFFFF
        value = (value * 1099511628211) & 0xFFFFFFFFFFFFFFFF
    return f"{value:016x}"


def xcursorfilehashes(path):
    try:
        with open(path, "rb") as stream:
            data = stream.read(16 * 1024 * 1024)
        if len(data) < 16 or data[:4] != b"Xcur":
            return set()
        header, _version, count = struct.unpack_from("<III", data, 4)
        if header < 16 or count > 4096 or header + count * 12 > len(data):
            return set()
        hashes = set()
        for index in range(count):
            kind, _size, position = struct.unpack_from(
                "<III", data, header + index * 12,
            )
            if kind != 0xFFFD0002 or position + 36 > len(data):
                continue
            chunkheader, chunktype, _subtype, _chunkversion = struct.unpack_from(
                "<IIII", data, position,
            )
            if chunktype != 0xFFFD0002 or chunkheader < 36:
                continue
            width, height, xhot, yhot, _delay = struct.unpack_from(
                "<IIIII", data, position + 16,
            )
            pixelcount = int(width) * int(height)
            pixelstart = position + chunkheader
            if (
                width < 1 or height < 1 or width > 512 or height > 512
                or pixelstart + pixelcount * 4 > len(data)
            ):
                continue
            pixels = struct.unpack_from(
                f"<{pixelcount}I", data, pixelstart,
            )
            hashes.add(cursorimagehash(width, height, xhot, yhot, pixels))
        return hashes
    except (OSError, ValueError, struct.error):
        return set()


def xcursorsemantics():
    global XCURSORSEMANTICS
    if XCURSORSEMANTICS is not None:
        return XCURSORSEMANTICS
    directory = RESOURCES + "/icons/Adwaita/cursors"
    groups = (
        ("arrow", ("default", "left_ptr", "arrow")),
        ("busy", ("wait", "watch", "progress")),
        ("text", ("text", "xterm", "vertical-text")),
        ("link", ("pointer", "hand1", "hand2")),
    )
    result = dict(CHROMIUMCURSORIMAGESEMANTICS)
    for mode, names in groups:
        for name in names:
            for fingerprint in xcursorfilehashes(os.path.join(directory, name)):
                result[fingerprint] = mode
    XCURSORSEMANTICS = result
    return result


def setbrowsercursorimage(fingerprint, width=0, height=0, xhot=0, yhot=0):
    fingerprint = str(fingerprint).strip().lower()
    mode = xcursorsemantics().get(fingerprint, "arrow")
    if os.environ.get("T1OS_VM_TEST") == "1":
        logline(
            "chromium cursor image observed "
            f"mode={mode} hash={fingerprint} "
            f"size={int(width)}x{int(height)} hotspot={int(xhot)},{int(yhot)}"
        )
    setbrowsercursormode(mode)


def fullscreenpointeractivity():
    global FULLSCREENCURSORHIDEAT
    if not FULLSCREEN:
        return
    setbrowsercursor(True)
    FULLSCREENCURSORHIDEAT = time.monotonic() + FULLSCREENCURSORDELAY


def pumpfullscreencursor():
    global FULLSCREENCURSORHIDEAT
    if (
        not FULLSCREEN
        or not FULLSCREENCURSORVISIBLE
        or FULLSCREENCURSORHIDEAT <= 0.0
        or time.monotonic() < FULLSCREENCURSORHIDEAT
    ):
        return
    setbrowsercursor(False)
    FULLSCREENCURSORHIDEAT = 0.0


def closegraphicsbuffer():
    if GFX is None:
        return
    try:
        mapping = getattr(GFX, "_FILE_MAP", None)
        if mapping:
            mapping.close()
            setattr(GFX, "_FILE_MAP", None)
    except Exception:
        pass
    try:
        descriptor = getattr(GFX, "_FILE_FD", None)
        if descriptor is not None:
            os.close(descriptor)
            setattr(GFX, "_FILE_FD", None)
    except Exception:
        pass


def bindbuffer():
    global WINDOWREADY, FONTREADY
    closegraphicsbuffer()
    GFX.initbuffer(BUFFERPATH, WINW, WINH)
    FONTREADY = False
    try:
        GFX.initttffont(FONTFILE, 20)
        FONTREADY = True
    except Exception:
        pass
    WINDOWREADY = True


def present():
    # Once the measured presentation bridge has been requested, even a
    # temporary placeholder must not enter WindowServer's CPU damage path.
    # Keep the owned buffer untouched until the first brokered GPU frame is
    # imported instead of racing VIDEO_AUTHORIZED with a software paint.
    if (
        WINID is None
        or not WINDOWREADY
        or DIRECTBUFFERSTATE in ("gpu-pending", "gpu")
    ):
        return
    try:
        GFX.presentdirty(0, 0, WINW, WINH)
        sendws({"op": "DAMAGE", "winid": WINID, "rect": [0, 0, WINW, WINH]})
    except Exception as error:
        logline(f"present failed: {error}")


def presentrects(rects):
    if (
        WINID is None
        or not WINDOWREADY
        or DIRECTBUFFERSTATE in ("gpu-pending", "gpu")
    ):
        return
    for rect in rects:
        try:
            x, y, width, height = [int(value) for value in rect[:4]]
            if width < 1 or height < 1:
                continue
            GFX.presentdirty(x, y, width, height)
            sendws({"op": "DAMAGE", "winid": WINID, "rect": [x, y, width, height]})
        except Exception as error:
            logline(f"partial present failed: {error}")


def requestdirectbuffer(refresh=False):
    global DIRECTBUFFERSTATE, DIRECTBUFFERERROR
    global DIRECTBUFFERWIDTH, DIRECTBUFFERHEIGHT
    allowed = ("active", "refreshing") if refresh else ("inactive",)
    if DIRECTBUFFERSTATE not in allowed or WINID is None or XWDMETA is None:
        return False
    metadata = XWDMETA
    if (
        int(metadata.get("width", 0)) < ENGINEW
        or int(metadata.get("height", 0)) < ENGINEH
        or int(metadata.get("stride", 0)) < int(metadata.get("width", 0)) * 4
    ):
        DIRECTBUFFERSTATE = "unavailable"
        DIRECTBUFFERERROR = "Xvfb surface cannot cover the Chromium backing surface"
        return False
    if not sendws({
        "op": "WINDOW_BUFFER_ATTACH",
        "winid": WINID,
        "path": XWDFILE,
        "offset": int(metadata["offset"]),
        "stride": int(metadata["stride"]),
        "source_width": int(ENGINEW),
        "source_height": int(ENGINEH),
        "format": "BGRA32",
    }):
        return False
    DIRECTBUFFERWIDTH = int(ENGINEW)
    DIRECTBUFFERHEIGHT = int(ENGINEH)
    DIRECTBUFFERSTATE = "refreshing" if refresh else "pending"
    DIRECTBUFFERERROR = ""
    return True


def detachdirectbuffer():
    global DIRECTBUFFERSTATE
    if WINID is None or DIRECTBUFFERSTATE not in ("pending", "active", "refreshing"):
        return False
    if not sendws({"op": "WINDOW_BUFFER_DETACH", "winid": WINID}):
        return False
    DIRECTBUFFERSTATE = "detaching"
    return True


def placeholder(text=None):
    if (
        not WINDOWREADY
        or DIRECTBUFFERSTATE in ("gpu-pending", "gpu")
    ):
        return
    message = str(text if text is not None else PLACEHOLDER)
    GFX.fillrectfast(0, 0, WINW, WINH, (247, 248, 250))
    if FONTREADY:
        try:
            title = "chromium"
            tw = GFX.ttftextwidth(title, 30)
            mw = GFX.ttftextwidth(message, 18)
            GFX.drawttftext(max(20, (WINW - tw) // 2), max(30, WINH // 2 - 42), title, 0x16181B, 30)
            GFX.drawttftext(max(20, (WINW - mw) // 2), max(70, WINH // 2 + 8), message, 0x5E6670, 18)
        except Exception:
            pass
    present()


def setclipboard(text):
    try:
        encoded = str(text).encode("utf-8")
        if len(encoded) > 1048576:
            return
        sendws({
            "op": "CLIPBOARD_SET",
            "type": "text/plain",
            "text": encoded.decode("utf-8"),
        })
    except Exception as error:
        logline(f"clipboard copy failed: {error}")


def pasteclipboard(message):
    try:
        if message.get("type") != "text/plain":
            return
        text = str(message.get("text", ""))
        if len(text.encode("utf-8")) <= 1048576:
            enginecommand({"op": "paste", "text": text})
    except Exception as error:
        logline(f"clipboard paste failed: {error}")


def mkdir(path, mode=0o755):
    try:
        os.makedirs(path, mode=mode, exist_ok=True)
        status = os.lstat(path)
        if stat.S_ISLNK(status.st_mode) or not stat.S_ISDIR(status.st_mode):
            raise RuntimeError("path is not a real directory")
        os.chmod(path, mode)
    except Exception as error:
        raise RuntimeError(
            f"could not prepare required Chromium directory {path}: {error}"
        ) from error


def safechown(path, uid=ENGINEUID, gid=ENGINEGID):
    try:
        os.chown(path, uid, gid, follow_symlinks=False)
    except Exception as error:
        raise PermissionError(
            f"could not assign Chromium ownership {uid}:{gid} to {path}: {error}"
        ) from error


def removeruntime():
    """Remove Chromium scratch state, including its mode-000 sandbox root."""
    if not os.path.lexists(RUNTIME):
        return False

    runtimestatus = os.lstat(RUNTIME)
    if stat.S_ISLNK(runtimestatus.st_mode) or not stat.S_ISDIR(
        runtimestatus.st_mode
    ):
        raise RuntimeError("chromium runtime path is not a real directory")

    if os.path.lexists(SANDBOXROOT):
        sandboxstatus = os.lstat(SANDBOXROOT)
        if stat.S_ISLNK(sandboxstatus.st_mode) or not stat.S_ISDIR(
            sandboxstatus.st_mode
        ):
            raise RuntimeError("Chromium sandbox root is not a real directory")
        if (sandboxstatus.st_uid, sandboxstatus.st_gid) not in (
            (ENGINEUID, ENGINEGID),
            (0, 0),
        ):
            raise PermissionError(
                "Chromium sandbox root has unexpected ownership "
                f"{sandboxstatus.st_uid}:{sandboxstatus.st_gid}"
            )
        # chrome-sandbox requires this directory to be inaccessible while the
        # engine is live.  Restore owner traversal only after engine teardown
        # so shutil can inspect and remove the otherwise mode-000 directory.
        os.chmod(SANDBOXROOT, 0o700)

    shutil.rmtree(RUNTIME)
    return True


def chromiumstateobjectkind(mode):
    if stat.S_ISLNK(mode):
        return "symbolic link"
    if stat.S_ISFIFO(mode):
        return "fifo"
    if stat.S_ISSOCK(mode):
        return "socket"
    if stat.S_ISCHR(mode):
        return "character device"
    if stat.S_ISBLK(mode):
        return "block device"
    return "unsupported object"


def repairchromiumownedtree(path, uid=ENGINEUID, gid=ENGINEGID):
    """Securely normalize one browser-owned tree without following links."""
    root = os.path.abspath(path)
    if not hasattr(os, "O_NOFOLLOW"):
        raise RuntimeError("secure Chromium state repair requires O_NOFOLLOW")

    directoryflags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
    fileflags = os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC | os.O_NOFOLLOW

    def repairdirectory(descriptor, displaypath):
        try:
            status = os.fstat(descriptor)
            if not stat.S_ISDIR(status.st_mode):
                raise RuntimeError("opened object is not a directory")
            if status.st_uid != uid or status.st_gid != gid:
                os.fchown(descriptor, uid, gid)
            if stat.S_IMODE(status.st_mode) != 0o700:
                os.fchmod(descriptor, 0o700)
            names = sorted(os.listdir(descriptor))
        except Exception as error:
            raise RuntimeError(
                f"could not secure Chromium owned directory {displaypath}: {error}"
            ) from error

        repaired = 1
        for name in names:
            candidate = os.path.join(displaypath, name)
            try:
                status = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            except Exception as error:
                raise RuntimeError(
                    f"could not inspect Chromium owned state {candidate}: {error}"
                ) from error

            if stat.S_ISLNK(status.st_mode):
                raise RuntimeError(
                    f"unexpected symbolic link in Chromium owned state: {candidate}"
                )

            if stat.S_ISDIR(status.st_mode):
                try:
                    child = os.open(name, directoryflags, dir_fd=descriptor)
                except Exception as error:
                    raise RuntimeError(
                        f"could not securely open Chromium owned directory "
                        f"{candidate}: {error}"
                    ) from error
                try:
                    repaired += repairdirectory(child, candidate)
                finally:
                    os.close(child)
                continue

            if not stat.S_ISREG(status.st_mode):
                kind = chromiumstateobjectkind(status.st_mode)
                raise RuntimeError(
                    f"unexpected {kind} in Chromium owned state: {candidate}"
                )

            try:
                child = os.open(name, fileflags, dir_fd=descriptor)
            except Exception as error:
                raise RuntimeError(
                    f"could not securely open Chromium owned file "
                    f"{candidate}: {error}"
                ) from error
            try:
                opened = os.fstat(child)
                if not stat.S_ISREG(opened.st_mode):
                    kind = chromiumstateobjectkind(opened.st_mode)
                    raise RuntimeError(
                        f"unexpected {kind} in Chromium owned state: {candidate}"
                    )
                if opened.st_uid != uid or opened.st_gid != gid:
                    os.fchown(child, uid, gid)
                if stat.S_IMODE(opened.st_mode) != 0o600:
                    os.fchmod(child, 0o600)
            except Exception as error:
                raise RuntimeError(
                    f"could not secure Chromium owned file {candidate}: {error}"
                ) from error
            finally:
                os.close(child)
            repaired += 1
        return repaired

    try:
        descriptor = os.open(root, directoryflags)
    except Exception as error:
        raise RuntimeError(
            f"could not securely open Chromium owned root {root}: {error}"
        ) from error
    try:
        return repairdirectory(descriptor, root)
    finally:
        os.close(descriptor)


def probechromiumownedroots(paths, uid=ENGINEUID, gid=ENGINEGID):
    """Require create, fsync, and unlink access after dropping to Chromium."""
    if not hasattr(os, "fork") or not hasattr(os, "O_NOFOLLOW"):
        raise RuntimeError("Chromium owned-state probing requires Linux process APIs")

    reader, writer = os.pipe()
    try:
        process = os.fork()
    except Exception:
        os.close(reader)
        os.close(writer)
        raise

    if process == 0:
        os.close(reader)
        activepath = "engine identity"
        try:
            # The catalogue launcher already enters the Chromium script as
            # uid/gid 1000.  Keep this probe usable both there and during the
            # root-owned preparation path without attempting privileged
            # setgroups/setid calls from an already confined child.
            if os.geteuid() == 0:
                os.setgroups([])
                os.setresgid(gid, gid, gid)
                os.setresuid(uid, uid, uid)
            elif (
                tuple(os.getresuid()) != (uid,) * 3
                or tuple(os.getresgid()) != (gid,) * 3
                or os.getgroups()
            ):
                raise PermissionError(
                    "Chromium owned-state probe identity is not confined"
                )
            directoryflags = (
                os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
            )
            fileflags = (
                os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                os.O_CLOEXEC | os.O_NOFOLLOW
            )
            for path in paths:
                activepath = path
                directory = os.open(path, directoryflags)
                filename = f".t1os-write-probe-{os.getpid()}"
                created = False
                descriptor = None
                try:
                    descriptor = os.open(
                        filename,
                        fileflags,
                        0o600,
                        dir_fd=directory,
                    )
                    created = True
                    os.write(descriptor, b"t1os chromium owned-state probe\n")
                    os.fsync(descriptor)
                    os.close(descriptor)
                    descriptor = None
                    os.unlink(filename, dir_fd=directory)
                    created = False
                finally:
                    if descriptor is not None:
                        os.close(descriptor)
                    if created:
                        try:
                            os.unlink(filename, dir_fd=directory)
                        except OSError:
                            pass
                    os.close(directory)
            os.close(writer)
            os._exit(0)
        except BaseException as error:
            message = (
                f"{activepath}: {type(error).__name__}: {error}"
            ).encode("utf-8", "replace")[:4000]
            try:
                os.write(writer, message)
            except OSError:
                pass
            os.close(writer)
            os._exit(1)

    os.close(writer)
    try:
        with os.fdopen(reader, "rb", closefd=True) as stream:
            failure = stream.read(4096).decode("utf-8", "replace")
        waited, status = os.waitpid(process, 0)
    except Exception:
        try:
            os.waitpid(process, 0)
        except Exception:
            pass
        raise
    if (
        waited != process or
        not os.WIFEXITED(status) or
        os.WEXITSTATUS(status) != 0
    ):
        detail = failure or f"child status={status}"
        raise PermissionError(
            f"Chromium UID {uid}:{gid} owned-state write probe failed at {detail}"
        )


def ensurednsconfiguration():
    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        try:
            if os.path.isfile(DNSFILE) and os.path.getsize(DNSFILE) > 0:
                break
        except OSError:
            pass
        time.sleep(0.1)
    if not os.path.isfile(DNSFILE) or os.path.getsize(DNSFILE) <= 0:
        atomictext(DNSFILE, dnsconfiguration(), 0o644)


def dnsconfiguration():
    servers = []
    try:
        with open(DNSFILE, "r", encoding="utf-8") as stream:
            for line in stream:
                fields = line.strip().split()
                if len(fields) >= 2 and fields[0].lower() == "nameserver":
                    value = fields[1]
                    if len(value) <= 64 and all(character.isalnum() or character in ".:-" for character in value):
                        servers.append(value)
    except Exception:
        pass
    if not servers:
        servers = ["10.0.2.3", "1.1.1.1"]
    return "".join(f"nameserver {server}\n" for server in servers[:3]) + "options timeout:2 attempts:3\n"


def audiooutputrate():
    client = None
    try:
        sys.path.insert(0, "/the one/build")
        import audio.audio as audioapi
        client = audioapi.AudioClient(path=AUDIOSOCK, timeout=2.0)
        client.connect()
        device = client.requireoutput()
        outputformat = device.get("format", {}) if isinstance(device, dict) else {}
        rate = int(outputformat.get("samplerate", 48000))
        if 8000 <= rate <= 384000:
            return rate
    except Exception as error:
        logline(f"chromium audio output discovery deferred: {error}")
    finally:
        if client is not None:
            try:
                client.disconnect()
            except Exception:
                pass
    return 48000


def prepareruntime():
    global AUDIORATE, ENGINELOG, ENGINELOGREADER
    downloads = downloaddir()
    if not os.path.isdir(downloads) or os.path.islink(downloads):
        raise RuntimeError(
            f"the T1OS downloads directory is unavailable: {downloads}"
        )
    if os.path.lexists(RUNTIME):
        removeruntime()
    for path, mode in (
        (RUNTIME, 0o700), (FRAMEBUFFER, 0o700), (CACHE, 0o700),
        (AUDIO, 0o700), (SHARED, 0o1777), (DISPLAYROOT, 0o1777),
        (TEMPORARY, 0o1777), (RUNTIMEROOT, 0o700), (XKBCACHE, 0o700),
        (FONTCACHE, 0o700),
        (SYSTEMROOT, 0o755), (VARIABLEROOT, 0o700), (SANDBOXROOT, 0o000),
        (SETTINGROOT, 0o700), (PROFILE, 0o700), (CONFIGROOT, 0o700),
        (SETTINGROOT + "/policies", 0o700),
    ):
        mkdir(path, mode)
    ensurednsconfiguration()
    for path in (
        RUNTIME, SETTINGROOT, PROFILE, SETTINGROOT + "/policies", CACHE, AUDIO,
        CONFIGROOT, FRAMEBUFFER, RUNTIMEROOT, XKBCACHE, FONTCACHE,
        VARIABLEROOT,
    ):
        safechown(path)
    clearstaleprofilelock()
    repaired = sum(
        repairchromiumownedtree(path)
        for path in (PROFILE, CACHE, CONFIGROOT, FONTCACHE)
    )
    logline(f"Chromium owned state secured entries={repaired}")
    ownedroots = (PROFILE, CONFIGROOT, FONTCACHE, CACHE)
    probechromiumownedroots(ownedroots)
    logline(f"Chromium owned state write probes passed roots={len(ownedroots)}")

    shutil.copy2(PATHPROVIDER, RUNTIMEPROVIDER)
    os.chmod(RUNTIMEPROVIDER, 0o555)
    safechown(RUNTIMEPROVIDER)

    atomictext(SYSTEMROOT + "/hosts", "127.0.0.1 localhost\n::1 localhost\n", 0o644)
    atomictext(SYSTEMROOT + "/nsswitch.conf", "hosts: files dns\npasswd: files\ngroup: files\n", 0o644)
    atomictext(SYSTEMROOT + "/passwd", "chromium:x:1000:1000:chromium:/the one/settings/chromium:/false\n", 0o644)
    atomictext(SYSTEMROOT + "/group", "chromium:x:1000:\n", 0o644)
    atomictext(SYSTEMROOT + "/machine-id", os.urandom(16).hex() + "\n", 0o444)
    atomictext(
        SETTINGROOT + "/policies/t1os.json",
        json.dumps({
            "DownloadDirectory": downloads,
            "PromptForDownloadLocation": False,
            "DownloadRestrictions": 0,
        }, sort_keys=True) + "\n",
        0o644,
    )

    AUDIORATE = audiooutputrate()
    asound = """pcm_type.null {
  lib "/the one/software/chromium/libraries/libasound.so.2"
}
pcm_type.file {
  lib "/the one/software/chromium/libraries/libasound.so.2"
}
pcm_type.plug {
  lib "/the one/software/chromium/libraries/libasound.so.2"
}
pcm.t1os_null {
  type null
}
pcm.chromium_capture {
  type file
  slave.pcm "t1os_null"
  file "%s/output.pcm"
  format "raw"
}
pcm.!default {
  type plug
  slave.pcm "chromium_capture"
  slave.format S16_LE
  slave.rate %d
  slave.channels 2
}
""" % (AUDIO, AUDIORATE)
    atomictext(AUDIO + "/asound.conf", asound, 0o644)
    fifo = AUDIO + "/output.pcm"
    os.mkfifo(fifo, 0o600)
    safechown(fifo)
    with open(AUDIOCLOCK, "wb") as stream:
        stream.write(AUDIOCLOCKFORMAT.pack(
            AUDIOCLOCKMAGIC,
            AUDIOCLOCKVERSION,
            0,
            time.monotonic_ns(),
            0,
            0,
            0,
            0,
            0,
            AUDIORATE,
            0,
        ))
    os.chmod(AUDIOCLOCK, 0o644)
    safechown(AUDIOCLOCK)

    if ENGINELOG is None:
        reader, writer = os.pipe()
        ENGINELOGREADER = reader
        ENGINELOG = os.fdopen(writer, 'wb', buffering=0)


def startengineoutputworker():
    """Start log forwarding after process-creation forks have completed."""
    global ENGINELOGREADER
    descriptor = ENGINELOGREADER
    if descriptor is None:
        return False
    ENGINELOGREADER = None
    debug = chromiumdebugconfiguration()
    threading.Thread(
        target=engineoutputworker,
        args=(
            descriptor,
            bool(debug["enabled"]),
            int(debug["engine_log_limit_bytes"]),
        ),
        name='chromium-engine-log',
        daemon=True,
    ).start()
    return True


def closeengineoutputreader():
    """Close an unclaimed log reader in a child or diagnostic cleanup."""
    global ENGINELOGREADER
    descriptor = ENGINELOGREADER
    ENGINELOGREADER = None
    if descriptor is None:
        return
    try:
        os.close(descriptor)
    except OSError:
        pass


def sanitizeengineoutput(message, limit=ENGINEDEBUGLINELIMIT):
    """Remove credentials, URLs, control bytes, and oversized log payloads."""

    text = str(message or "")
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
    text = "".join(
        character
        if character == "\t" or 32 <= ord(character) < 127
        else "?"
        for character in text
    )
    text = re.sub(
        r"(?i)(--t1os-presentation-token=)[^\s]+",
        r"\1<redacted>",
        text,
    )
    text = re.sub(
        r"(?i)\b(?:https?|wss?|file|data|blob|filesystem|"
        r"chrome-extension):[^\s\"'<>]+",
        "<url-redacted>",
        text,
    )
    text = re.sub(
        r"(?i)\b(authorization|cookie|set-cookie|proxy-authorization)"
        r"(\s*[:=]\s*).*$",
        r"\1\2<redacted>",
        text,
    )
    limit = max(256, min(int(limit), ENGINEDEBUGLINELIMIT))
    if len(text) > limit:
        return text[:limit] + " <line-truncated>"
    return text


def productionengineoutput(message):
    """Keep bounded GPU/media lifecycle and crash evidence in production."""

    folded = str(message or "").casefold()
    if any(marker in folded for marker in (
        "fatal:",
        "check failed:",
        "dcheck failed:",
        "received signal",
        "gpu process launch failed",
        "gpu process exited unexpectedly",
        "gpu process crashed",
        "gpu process isn't usable",
        "context lost",
        "context reset",
        "egl_bad_",
        "gl_guilty_context_reset",
        "xio:  fatal io error",
        "segmentation fault",
    )):
        return True
    if "t1os-chrome-subprocess:" in folded:
        return any(marker in folded for marker in (
            "entered",
            "invalid",
            "failed",
            "could not",
            "rejected",
        ))
    if any(marker in folded for marker in (
        "t1os_presentation_bridge",
        "t1osvideodecoder",
        "t1md",
    )):
        return any(marker in folded for marker in (
            "error",
            "failed",
            "failure",
            "fatal",
            "rejected",
            "invalid",
            "context lost",
            "context reset",
            "exited",
            "disconnected",
        ))
    return False


def engineoutputworker(
    descriptor,
    debug=False,
    debuglimit=ENGINEDEBUGLOGLIMIT,
):
    """Drain engine output and retain a separately capped redacted trace."""

    debugstream = None
    debugbytes = 0
    debugtruncated = False
    try:
        if debug:
            debuglimit = max(
                ENGINEDEBUGLOGMINIMUM,
                min(int(debuglimit), ENGINEDEBUGLOGMAXIMUM),
            )
            debugdescriptor = None
            try:
                nofollow = getattr(os, "O_NOFOLLOW", None)
                if nofollow is None:
                    raise RuntimeError("O_NOFOLLOW is unavailable")
                debugdescriptor = os.open(
                    ENGINEDEBUGLOG,
                    os.O_WRONLY | os.O_CREAT | os.O_TRUNC | nofollow,
                    0o600,
                )
                if not stat.S_ISREG(os.fstat(debugdescriptor).st_mode):
                    os.close(debugdescriptor)
                    raise ValueError(
                        "Chromium engine diagnostic path is not a regular file"
                    )
                # This trace is already redacted and bounded.  VM test agents
                # run as the desktop identity, so leave the file readable to
                # that identity; otherwise a real sandbox failure is replaced
                # by a misleading PermissionError in the host report.
                os.fchmod(debugdescriptor, 0o644)
                debugstream = os.fdopen(
                    debugdescriptor,
                    "w",
                    encoding="utf-8",
                    errors="replace",
                    buffering=1,
                )
                debugdescriptor = None
                header = (
                    "T1OS Chromium redacted engine diagnostics "
                    f"limit_bytes={debuglimit}\n"
                )
                debugstream.write(header)
                debugbytes = len(header.encode("utf-8"))
                logline(
                    "chromium engine diagnostics enabled "
                    f"path={ENGINEDEBUGLOG} limit_bytes={debuglimit}"
                )
            except Exception as error:
                if debugdescriptor is not None:
                    try:
                        os.close(debugdescriptor)
                    except OSError:
                        pass
                debugstream = None
                logline(f"chromium engine diagnostic file unavailable: {error}")
        else:
            try:
                if os.path.lexists(ENGINEDEBUGLOG):
                    if os.path.islink(ENGINEDEBUGLOG) or stat.S_ISREG(
                        os.stat(ENGINEDEBUGLOG).st_mode
                    ):
                        os.unlink(ENGINEDEBUGLOG)
                    else:
                        logline(
                            "stale Chromium engine diagnostic path retained "
                            "because it is not a regular file"
                        )
            except OSError as error:
                logline(f"stale Chromium engine diagnostics not cleared: {error}")
        with os.fdopen(descriptor, 'rb', buffering=0) as stream:
            for raw in stream:
                message = sanitizeengineoutput(
                    raw.decode('utf-8', 'replace').rstrip('\r\n')
                )
                if debugstream is not None and not debugtruncated:
                    record = message + "\n"
                    recordbytes = len(record.encode("utf-8"))
                    if debugbytes + recordbytes <= debuglimit:
                        debugstream.write(record)
                        debugbytes += recordbytes
                    else:
                        debugtruncated = True
                        marker = (
                            "T1OS Chromium redacted engine diagnostics truncated "
                            f"at_bytes={debugbytes} limit_bytes={debuglimit}\n"
                        )
                        markerbytes = len(marker.encode("utf-8"))
                        if debugbytes + markerbytes <= debuglimit:
                            debugstream.write(marker)
                            debugbytes += markerbytes
                        logline(
                            "chromium engine diagnostics truncated "
                            f"at_bytes={debugbytes} limit_bytes={debuglimit}"
                        )
                if productionengineoutput(message):
                    logline(message, 'chromium engine')
    except Exception as error:
        logline(f'engine log forwarding failed: {error}')
    finally:
        if debugstream is not None:
            try:
                debugstream.close()
            except Exception:
                pass


def engineenvironment():
    certificate = "/the one/settings/network/cacerts.pem"
    if not os.path.isfile(certificate):
        certificate = RESOURCES + "/ca-certificates.crt"
    environment = {
        "DISPLAY": DISPLAY,
        "HOME": SETTINGROOT,
        "USER": "chromium",
        "LOGNAME": "chromium",
        "PATH": TOOLS + ":" + PROGRAM,
        # Direct utility children are admitted only when this matches the
        # subprocess helper's measured non-NVIDIA loader contract exactly.
        # Keep the base graphics catalogue available for GPU rendering even
        # when NVIDIA VA-API is deliberately quarantined.
        "LD_LIBRARY_PATH": LIBRARIES + ":" + GRAPHICSCATALOGUE,
        "LD_PRELOAD": RUNTIMEPROVIDER,
        "CHROME_DEVEL_SANDBOX": SANDBOXEXECUTABLE,
        "XDG_CONFIG_HOME": CONFIGROOT,
        "XDG_DATA_HOME": CACHE + "/data",
        "XDG_CACHE_HOME": CACHE,
        # Keep NVIDIA's OpenGL shader cache out of HOME/.nv. CUDA/NVDEC is not
        # exposed to Chromium; its isolated service receives CUDA_CACHE_PATH
        # independently from GODDESS.
        "__GL_SHADER_DISK_CACHE_PATH": NVIDIACACHEPATH,
        "XDG_RUNTIME_DIR": RUNTIMEROOT,
        "XKB_CONFIG_ROOT": RESOURCES + "/xkb",
        "XKB_CONFIG_EXTRA_PATH": RESOURCES + "/xkb",
        "XKB_COMPILED_DIR": XKBCACHE,
        "XCURSOR_PATH": RESOURCES + "/icons",
        # XCURSOR_PATH only defines where themes may be found; without an
        # explicit theme libXcursor may fall back to core X11 cursor images.
        # The bridge fingerprints Adwaita images to translate Chromium's
        # cursor into the corresponding native T1OS cursor, so both ends must
        # use the same packaged theme.
        "XCURSOR_THEME": "Adwaita",
        "FONTCONFIG_PATH": FONTCONFIGROOT,
        "FONTCONFIG_FILE": FONTCONFIGFILE,
        "ALSA_CONFIG_PATH": AUDIO + "/asound.conf",
        "T1OS_CHROMIUM_AUDIO_CLOCK_PATH": AUDIOCLOCK,
        "GSETTINGS_BACKEND": "memory",
        "GSETTINGS_SCHEMA_DIR": ENGINE + "/resources/gsettings-schemas",
        "GTK_USE_PORTAL": "0",
        "DBUS_SESSION_BUS_ADDRESS": "unix:path=" + RUNTIMEROOT + "/no-session-bus",
        "DBUS_SYSTEM_BUS_ADDRESS": "unix:path=" + RUNTIMEROOT + "/no-system-bus",
        "SSL_CERT_FILE": certificate,
        "TZ": "Australia/Sydney",
        "NO_AT_BRIDGE": "1",
        "LIBGL_DRIVERS_PATH": LIBRARIES,
        "TMPDIR": TEMPORARY,
    }

    return environment


def validatedwindowgraphicscontract(contract):
    """Validate WindowServer's exact display render-node identity."""
    contract = contract if isinstance(contract, dict) else {}
    driver = str(contract.get("driver", "")).strip().lower().replace("-", "_")
    node = os.path.normpath(str(contract.get("render_node", "")).strip())
    identity = contract.get("render_identity")

    if (
        not driver
        or any(
            character not in "abcdefghijklmnopqrstuvwxyz0123456789_"
            for character in driver
        )
        or os.path.dirname(node) != DRMNODEROOT
        or not os.path.basename(node).startswith("renderD")
        or not os.path.basename(node)[7:].isdigit()
        or not isinstance(identity, dict)
    ):
        return {}

    try:
        expectedmajor = int(identity.get("major"))
        expectedminor = int(identity.get("minor"))
        status = os.stat(node, follow_symlinks=False)
    except (OSError, TypeError, ValueError):
        return {}

    if (
        not stat.S_ISCHR(status.st_mode)
        or int(os.major(status.st_rdev)) != expectedmajor
        or int(os.minor(status.st_rdev)) != expectedminor
    ):
        return {}

    return {
        "driver": driver,
        "render_node": node,
        "render_identity": {
            "major": expectedmajor,
            "minor": expectedminor,
        },
    }


def capturewindowgraphicscontract(graphics):
    """Capture the GPU selected by WindowServer before the engine fork."""
    global WINDOWGRAPHICSCONTRACT
    graphics = graphics if isinstance(graphics, dict) else {}
    surfaces = graphics.get("video_surfaces")
    surfaces = surfaces if isinstance(surfaces, dict) else {}
    WINDOWGRAPHICSCONTRACT = validatedwindowgraphicscontract({
        "driver": surfaces.get("drm_driver"),
        "render_node": surfaces.get("render_node"),
        "render_identity": surfaces.get("render_identity"),
    })
    return bool(WINDOWGRAPHICSCONTRACT)


def windowgraphicscontract():
    """Return the still-valid WindowServer GPU selection."""
    return validatedwindowgraphicscontract(WINDOWGRAPHICSCONTRACT)


def activegraphicsdriver():
    """Return the T1OS driver backing the connected physical display."""
    contract = windowgraphicscontract()
    if contract:
        return contract["driver"]

    drmroot = DRMSTATEROOT

    try:
        entries = sorted(os.listdir(drmroot))
    except OSError:
        return ""

    for entry in entries:
        if "-" not in entry or not entry.startswith("card"):
            continue

        statuspath = os.path.join(drmroot, entry, "status")

        try:
            with open(statuspath, "r", encoding="ascii", errors="replace") as stream:
                connected = stream.read(32).strip().lower() == "connected"
        except OSError:
            continue

        if not connected:
            continue

        card = entry.split("-", 1)[0]
        modulepath = os.path.join(drmroot, card, "device", "driver", "module")

        try:
            return os.path.basename(os.path.realpath(modulepath)).replace("-", "_")
        except OSError:
            return ""

    return ""


def activegraphicsrendernode(
    drmroot=DRMSTATEROOT,
    noderoot=DRMNODEROOT,
):
    """Return the render node belonging to the connected display card."""
    if drmroot == DRMSTATEROOT and noderoot == DRMNODEROOT:
        contract = windowgraphicscontract()
        if contract:
            return contract["render_node"]

    try:
        entries = sorted(os.listdir(drmroot))
    except OSError:
        return ""

    for entry in entries:
        if "-" not in entry or not entry.startswith("card"):
            continue

        statuspath = os.path.join(drmroot, entry, "status")

        try:
            with open(statuspath, "r", encoding="ascii", errors="replace") as stream:
                connected = stream.read(32).strip().lower() == "connected"
        except OSError:
            continue

        if not connected:
            continue

        card = entry.split("-", 1)[0]
        renderroot = os.path.join(drmroot, card, "device", "drm")

        try:
            rendernodes = sorted(os.listdir(renderroot))
        except OSError:
            continue

        for name in rendernodes:
            if not (
                name.startswith("renderD")
                and name[7:].isdigit()
            ):
                continue

            node = os.path.join(noderoot, name)

            try:
                status = os.stat(node)
            except OSError:
                continue

            if stat.S_ISCHR(status.st_mode):
                return node

    return ""


def booleanoption(value):
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in ("1", "true", "yes", "on", "enabled"):
        return True
    if text in ("0", "false", "no", "off", "disabled"):
        return False
    return None


def kernelcommandlineoption(option):
    try:
        with open(PROCESSROOT + "/cmdline", "rb") as stream:
            return str(option).encode("ascii") in stream.read(65536).split()
    except (OSError, UnicodeError):
        return False


def nvidiapresentationenabled():
    """Default to the hardware bridge; retain the legacy rollback switch."""

    environment = booleanoption(
        os.environ.get(NVIDIAPRESENTATIONVARIABLE)
    )
    if environment is not None:
        return environment
    return not kernelcommandlineoption(
        "t1os.chromium.nvidia-presentation=0"
    )


def hardwarediagnosticpolicy(path=None):
    """Read the bounded, removable-media hardware diagnostic policy."""

    result = {
        "enabled": False,
        "chromium_engine": False,
        "media_service": False,
        "engine_log_limit_bytes": ENGINEDEBUGLOGLIMIT,
        "source": "default-off",
    }
    explicitpath = path is not None
    paths = (
        (str(path),)
        if explicitpath
        else (HARDWAREDIAGNOSTICPOLICY, HARDWAREDIAGNOSTICFALLBACK)
    )
    for index, candidate in enumerate(paths):
        try:
            if (
                os.path.islink(candidate)
                or not stat.S_ISREG(os.stat(candidate).st_mode)
            ):
                raise ValueError(
                    "hardware diagnostic policy is not a regular file"
                )
            with open(candidate, "r", encoding="utf-8") as stream:
                encoded = stream.read(16385)
            if len(encoded.encode("utf-8")) > 16384:
                raise ValueError("hardware diagnostic policy is too large")
            configured = json.loads(encoded)
            if not isinstance(configured, dict):
                raise ValueError("hardware diagnostic policy is not an object")
            if type(configured.get("format")) is not int:
                raise ValueError(
                    "hardware diagnostic policy format is not an integer"
                )
            if configured.get("format") != 1:
                raise ValueError("unsupported hardware diagnostic policy format")
            for option in ("enabled", "chromium_engine", "media_service"):
                if type(configured.get(option)) is not bool:
                    raise ValueError(
                        f"hardware diagnostic policy {option} is not a JSON Boolean"
                    )
            limit = configured.get(
                "engine_log_limit_bytes",
                ENGINEDEBUGLOGLIMIT,
            )
            if (
                type(limit) is not int
                or limit < ENGINEDEBUGLOGMINIMUM
                or limit > ENGINEDEBUGLOGMAXIMUM
            ):
                raise ValueError(
                    "hardware diagnostic engine log limit is unsafe"
                )
            result.update({
                "enabled": configured["enabled"],
                "chromium_engine": configured["chromium_engine"],
                "media_service": configured["media_service"],
                "engine_log_limit_bytes": limit,
                "source": (
                    "launcher-fallback"
                    if not explicitpath and index == 1
                    else "settings"
                ),
            })
            return result
        except FileNotFoundError:
            continue
        except Exception as error:
            result["source"] = (
                "invalid-launcher-fallback"
                if not explicitpath and index == 1
                else "invalid-settings"
            )
            result["error"] = f"{type(error).__name__}: {error}"[:1024]
            return result
    return result


def chromiumdebugconfiguration():
    """Resolve Chromium diagnostics with one-boot controls taking priority."""

    policy = hardwarediagnosticpolicy()
    if os.environ.get("T1OS_VM_TEST") == "1":
        return {
            **policy,
            "enabled": True,
            "chromium_engine": True,
            "source": "vm-test",
        }
    environment = booleanoption(os.environ.get(CHROMIUMDEBUGVARIABLE))
    if environment is not None:
        return {
            **policy,
            "enabled": environment,
            "chromium_engine": environment,
            "source": "environment-on" if environment else "environment-off",
        }
    if kernelcommandlineoption("t1os.chromium.debug=1"):
        return {
            **policy,
            "enabled": True,
            "chromium_engine": True,
            "source": "kernel-on",
        }
    return {
        **policy,
        "enabled": bool(policy["enabled"] and policy["chromium_engine"]),
    }


def chromiumdebugenabled():
    """Enable bounded Chromium diagnostics only by explicit opt-in."""

    return chromiumdebugconfiguration()["enabled"]


def chromiumdebugarguments():
    """Return GPU/media diagnostics independently of T1MD availability."""

    if not chromiumdebugenabled():
        return []
    arguments = [
        "--enable-logging=stderr",
        (
            "--vmodule=*t1os*=1,*gpu_process_host*=1,*gpu_init*=1,"
            "*host_resolver*=2,*dns*=2,*network_service*=2,"
            "*transport_connect_job*=2,*url_request*=1"
        ),
    ]
    if os.environ.get("T1OS_VM_TEST") == "1":
        arguments.extend([
            "--log-net-log=" + VMTESTNETLOGPATH,
            "--net-log-capture-mode=Default",
        ])
    return arguments


def t1osmediadecoderconfiguration(graphicsdriver):
    """Validate the opt-in service and patched browser before enabling it."""

    driver = str(graphicsdriver or "").strip().lower().replace("-", "_")
    if driver not in ("nvidia", "nvidia_drm"):
        return None, "display-driver-not-nvidia"

    policypath = MEDIADECODEPOLICY
    if (
        not os.path.isfile(policypath)
        and os.path.isfile(MEDIADECODEPACKAGEDPOLICY)
    ):
        policypath = MEDIADECODEPACKAGEDPOLICY

    try:
        with open(policypath, "r", encoding="utf-8") as stream:
            policy = json.load(stream)
        if not isinstance(policy, dict):
            raise ValueError("policy is not an object")
        for option in (
            "enabled",
            "kill_switch",
            "development_debug",
        ):
            if option in policy and type(policy[option]) is not bool:
                raise ValueError(
                    f"policy {option} is not a JSON Boolean"
                )
    except FileNotFoundError:
        policy = {}
    except Exception as error:
        return None, f"policy-invalid:{type(error).__name__}"

    environmentpolicy = booleanoption(
        os.environ.get("T1OS_MEDIA_DECODE_SERVICE")
    )
    killed = (
        booleanoption(policy.get("kill_switch")) is True
        or environmentpolicy is False
        or kernelcommandlineoption("t1os.media-decode-service=0")
    )
    enabled = (
        booleanoption(policy.get("enabled")) is True
        or environmentpolicy is True
        or kernelcommandlineoption("t1os.media-decode-service=1")
    )

    if killed:
        return None, "kill-switch"
    if not enabled:
        return None, "policy-disabled"
    policyprotocol = policy.get(
        "protocol_version",
        MEDIADECODEPROTOCOLVERSION,
    )
    if type(policyprotocol) is not int:
        return None, "policy-protocol-invalid"
    if policyprotocol != MEDIADECODEPROTOCOLVERSION:
        return None, "policy-protocol-mismatch"
    policymaxsessions = policy.get(
        "max_sessions",
        MEDIADECODEMAXSESSIONS,
    )
    if (
        type(policymaxsessions) is not int
        or policymaxsessions != MEDIADECODEMAXSESSIONS
    ):
        return None, "session-ceiling-mismatch"

    try:
        with open(CHROMIUMMANIFEST, "r", encoding="utf-8") as stream:
            manifest = json.load(stream)
        capability = manifest.get("t1os_media_decoder")
        if not isinstance(capability, dict):
            raise ValueError("runtime capability marker is absent")
        if (
            capability.get("available") is not True
            or capability.get("protocol") != MEDIADECODEPROTOCOL
            or type(capability.get("protocol_version")) is not int
            or capability.get("protocol_version")
            != MEDIADECODEPROTOCOLVERSION
            or capability.get("feature") != MEDIADECODEFEATURE
            or capability.get("brokered_socket") is not True
            or type(capability.get("descriptor_pool_size")) is not int
            or capability.get("descriptor_pool_size") != MEDIADECODEMAXSESSIONS
            or capability.get("chromium_revision")
            != MEDIADECODECHROMIUMREVISION
            or capability.get("protocol_header_sha256")
            != MEDIADECODEPROTOCOLHEADERSHA256
            or capability.get("source_overlay_sha256")
            != MEDIADECODESOURCEOVERLAYSHA256
            or capability.get("build_marker")
            != MEDIADECODEBUILDMARKER
        ):
            raise ValueError("runtime capability marker does not match")
    except Exception as error:
        return None, f"chromium-runtime-unpatched:{type(error).__name__}"

    try:
        socketstatus = os.stat(MEDIADECODESOCKET, follow_symlinks=False)
        socketmode = stat.S_IMODE(socketstatus.st_mode)
        if not stat.S_ISSOCK(socketstatus.st_mode):
            raise ValueError("service path is not a socket")
        if socketmode & stat.S_IWOTH:
            raise PermissionError("service socket is world-writable")
        if not (
            (
                int(socketstatus.st_uid) == ENGINEUID
                and bool(socketmode & stat.S_IWUSR)
            )
            or (
                int(socketstatus.st_gid) == ENGINEGID
                and bool(socketmode & stat.S_IWGRP)
            )
        ):
            raise PermissionError("Chromium identity cannot connect")

        with open(MEDIADECODESTATE, "r", encoding="utf-8") as stream:
            state = json.load(stream)
        sandbox = state.get("sandbox")
        watchdog = state.get("watchdog")
        servicepid = state.get("pid")
        if (
            state.get("state") != "ready"
            or state.get("protocol") != MEDIADECODEPROTOCOL
            or type(state.get("protocol_version")) is not int
            or state.get("protocol_version")
            != MEDIADECODEPROTOCOLVERSION
            or os.path.normpath(str(state.get("socket", "")))
            != MEDIADECODESOCKET
            or type(state.get("worker_uid")) is not int
            or state.get("worker_uid")
            != MEDIADECODEWORKERUID
            or type(state.get("worker_gid")) is not int
            or state.get("worker_gid")
            != MEDIADECODEWORKERGID
            or type(state.get("maximum_sessions")) is not int
            or state.get("maximum_sessions") != MEDIADECODEMAXSESSIONS
            or type(state.get("maximum_connections")) is not int
            or state.get("maximum_connections") != MEDIADECODEMAXSESSIONS
            or not isinstance(sandbox, dict)
            or type(sandbox.get("format")) is not int
            or sandbox.get("format") != MEDIADECODESANDBOXFORMAT
            or type(sandbox.get("landlock_abi")) is not int
            or sandbox.get("landlock_abi")
            < MEDIADECODESANDBOXMINIMUMABI
            or type(sandbox.get("landlock_minimum_abi")) is not int
            or sandbox.get("landlock_minimum_abi")
            != MEDIADECODESANDBOXMINIMUMABI
            or sandbox.get("landlock_filesystem")
            != "deny-by-default-all-through-ioctl-dev"
            or sandbox.get("landlock_network")
            != "deny-tcp-bind-connect"
            or sandbox.get("seccomp") != "filter"
            or sandbox.get("seccomp_tsync") is not True
            or sandbox.get("runtime_filesystem") != "read-only"
            or sandbox.get("device_filesystem")
            != "read-write-ioctl"
            or sandbox.get("network_creation") != "denied"
            or sandbox.get("process_creation") != "threads-only"
            or sandbox.get("session_stdin") != MEDIADECODESESSIONSTDIN
            or sandbox.get("session_stdout") != MEDIADECODESESSIONSTDOUT
            or sandbox.get("session_stderr") != MEDIADECODESESSIONSTDERR
            or type(sandbox.get("session_diagnostic_limit")) is not int
            or sandbox.get("session_diagnostic_limit")
            != MEDIADECODESESSIONDIAGNOSTICLIMIT
            or type(sandbox.get("session_exec_visible_fds")) is not int
            or sandbox.get("session_exec_visible_fds")
            != MEDIADECODESESSIONEXECVISIBLEFDS
            or type(sandbox.get("session_required_ipc_fds")) is not int
            or sandbox.get("session_required_ipc_fds")
            != MEDIADECODESESSIONREQUIREDIPCFDS
            or type(
                sandbox.get("session_unexpected_inherited_fds")
            ) is not int
            or sandbox.get("session_unexpected_inherited_fds") != 0
            or type(sandbox.get("policy_flags")) is not int
            or sandbox.get("policy_flags") != MEDIADECODESANDBOXFLAGS
            or not isinstance(watchdog, dict)
            or set(watchdog) != set(MEDIADECODEWATCHDOGCONTRACT)
            or not all(
                type(watchdog.get(name)) is type(value)
                and watchdog.get(name) == value
                for name, value in MEDIADECODEWATCHDOGCONTRACT.items()
            )
            or type(servicepid) is not int
            or servicepid <= 1
        ):
            raise ValueError("service readiness contract does not match")
        try:
            os.kill(servicepid, 0)
        except PermissionError:
            pass
    except Exception as error:
        return None, f"service-not-ready:{type(error).__name__}"

    return {
        "feature": MEDIADECODEFEATURE,
        "socket": MEDIADECODESOCKET,
        "protocol": MEDIADECODEPROTOCOL,
        "protocol_version": MEDIADECODEPROTOCOLVERSION,
        "service_pid": servicepid,
        "brokered_socket": True,
        "development_debug": (
            booleanoption(policy.get("development_debug")) is True
        ),
    }, "ready"


def t1osmediadecoderarguments(configuration):
    configuration = (
        configuration
        if isinstance(configuration, dict)
        else None
    )
    if not configuration:
        return []
    outputmode = str(
        configuration.get("output_mode", MEDIADECODEOUTPUTLINEAR)
    )
    if outputmode not in (
        MEDIADECODEOUTPUTDMABUF,
        MEDIADECODEOUTPUTLINEAR,
    ):
        raise ValueError(f"unsupported T1MD output mode: {outputmode}")
    arguments = [
        "--enable-features=" + MEDIADECODEFEATURE,
        MEDIADECODESOCKETSWITCH + str(configuration["socket"]),
        MEDIADECODEOUTPUTSWITCH + outputmode,
    ]
    return arguments


def t1osmediadecoderoutputmode(presentationbridge):
    """Select an import-safe T1MD output independently of decoder readiness."""

    return (
        MEDIADECODEOUTPUTDMABUF
        if presentationbridge
        else MEDIADECODEOUTPUTLINEAR
    )


def mergechromiumfeaturearguments(arguments):
    """Return one authoritative enable/disable feature switch of each kind."""

    result = []
    enabled = []
    disabled = []
    prefixes = (
        ("--enable-features=", enabled),
        ("--disable-features=", disabled),
    )
    for argument in arguments:
        matched = False
        for prefix, features in prefixes:
            if not str(argument).startswith(prefix):
                continue
            for feature in str(argument)[len(prefix):].split(","):
                feature = feature.strip()
                if feature and feature not in features:
                    features.append(feature)
            matched = True
            break
        if not matched:
            result.append(argument)

    disabledset = set(disabled)
    enabled = [feature for feature in enabled if feature not in disabledset]
    if enabled:
        result.append("--enable-features=" + ",".join(enabled))
    if disabled:
        result.append("--disable-features=" + ",".join(disabled))
    return result


def servicechromiumenvironment(environment):
    """Remove every legacy NVIDIA decode capability from Chromium's process tree."""

    result = dict(environment)
    for name in tuple(result):
        if (
            name.startswith("NVD_")
            or name.startswith("CUDA_")
            or name.startswith("LIBVA_")
            or name.startswith("T1OS_CHROMIUM_NVIDIA_")
            or name.startswith("T1OS_MEDIA_DECODE_")
        ):
            result.pop(name, None)
    return result


def chromiumgraphicsenvironment(
    environment,
    graphicsdriver,
    presentationbridge=True,
):
    """Select display GL libraries without granting NVIDIA decode authority."""

    result = dict(environment)
    for name in (
        NVIDIAGPULIBRARYPATHVARIABLE,
        NVIDIAGPUEGLVENDORVARIABLE,
        NVIDIAGPUEGLEXTERNALVARIABLE,
        NVIDIAGPUGBMBACKENDSPATHVARIABLE,
        NVIDIAGPUGBMBACKENDVARIABLE,
        "__EGL_VENDOR_LIBRARY_FILENAMES",
        "__EGL_EXTERNAL_PLATFORM_CONFIG_DIRS",
        "GBM_BACKENDS_PATH",
        "GBM_BACKEND",
    ):
        result.pop(name, None)
    driver = str(graphicsdriver or "").replace("-", "_")
    if driver not in ("nvidia", "nvidia_drm"):
        if presentationbridge:
            # The browser and utility processes must retain Chromium's private
            # dependency closure.  The direct GPU helper promotes only the GPU
            # process to the coherent compositor Mesa EGL/GBM/Gallium stack;
            # exporting that stack here breaks utility Mojo bootstrap.
            result["LD_LIBRARY_PATH"] = BASEGRAPHICSLIBRARYPATH
            result.pop("GBM_BACKENDS_PATH", None)
        return result
    if not presentationbridge:
        return result

    # NVIDIA EGL rendering is independent of VA-API/NVDEC.  The Chromium
    # path provider maps only nvidiactl, numeric display-GPU nodes, and DRM;
    # CUDA/UVM and the decoder remain exclusively in t1-media-decoderd. Give
    # only the direct GPU subprocess a coherent NVIDIA + canonical graphics
    # loader path; the browser, renderers, and utilities retain their private
    # dependency closure.
    result[NVIDIAGPULIBRARYPATHVARIABLE] = NVIDIAGRAPHICSLIBRARYPATH
    result[NVIDIAGPUEGLVENDORVARIABLE] = NVIDIAEGLVENDORFILE
    result[NVIDIAGPUEGLEXTERNALVARIABLE] = NVIDIAGBMPATH
    result[NVIDIAGPUGBMBACKENDSPATHVARIABLE] = NVIDIAGBMPATH
    result[NVIDIAGPUGBMBACKENDVARIABLE] = "nvidia-drm"
    result.pop("LIBGL_DRIVERS_PATH", None)
    return result


def vaapiconfiguration(graphicsdriver):
    """Select the same packaged VA-API backend used by T1OS Media."""
    if str(graphicsdriver or "").replace("-", "_") in (
        "nvidia",
        "nvidia_drm",
    ):
        # NVIDIA decode belongs exclusively to t1-media-decoderd. Never expose
        # the vendor VA/CUDA stack to Chromium, even if someone later changes
        # the software-decode rollback constant.
        return None
    try:
        from media.media import browservideoacceleration

        acceleration = browservideoacceleration(graphicsdriver)
        # A successful shared-policy lookup returning None is authoritative:
        # it means this backend has no packaged, permitted VA-API driver.
        return acceleration
    except Exception as error:
        logline(f"shared T1OS browser video acceleration probe failed: {error}")

    candidates = {
        "i915": ("iHD",),
        "xe": ("iHD",),
        "amdgpu": ("radeonsi",),
        "radeon": ("radeonsi", "r600"),
        "nouveau": ("nouveau",),
        "vmwgfx": ("vmwgfx",),
        "virtio_gpu": ("virtio_gpu",),
    }.get(str(graphicsdriver or "").replace("-", "_"), ())

    for driver in candidates:
        path = os.path.join(LIBVADRIVERPATH, f"{driver}_drv_video.so")
        if os.path.isfile(path):
            return {
                "driver": driver,
                "driver_path": LIBVADRIVERPATH,
                "library_path": GRAPHICSCATALOGUE,
                "environment": {},
                "hardware_required": False,
            }

    return None


def rendererconfiguration(graphicsdriver, presentationbridge=True):
    """Return Chromium's stable renderer mode and command-line arguments."""
    proprietarynvidia = str(graphicsdriver or "").replace("-", "_") in (
        "nvidia",
        "nvidia_drm",
    )
    if graphicsdriver == "nouveau" or (
        proprietarynvidia and not presentationbridge
    ):
        # T1OS's NVK runtime is intentionally built without conventional
        # X11/XCB dependencies and therefore does not advertise
        # VK_KHR_xcb_surface. ANGLE Vulkan cannot present to Chromium's
        # private Xvfb display in that configuration. Use Chromium's bundled
        # software GLES implementation so the GPU process remains stable.
        mode = (
            "angle-swiftshader-rollback"
            if proprietarynvidia
            else NOUVEAURENDERER
        )
        return mode, [
            "--use-gl=angle",
            "--use-angle=swiftshader",
            "--enable-unsafe-swiftshader",
            "--disable-features=Vulkan,DefaultANGLEVulkan,VulkanFromANGLE",
        ]
    return "automatic", []


def browsergpuarguments(
    graphicsdriver,
    acceleration,
    servicedecoder=None,
    presentationbridge=True,
):
    """Return GPU feature policy independently of video-decoder availability."""
    driver = str(graphicsdriver or "").replace("-", "_")
    proprietarynvidia = driver in ("nvidia", "nvidia_drm")
    arguments = []

    # The proprietary NVIDIA kernel/EGL stack is version-pinned and validated
    # by the T1OS hardware contract. Chromium nevertheless blocklists parts of
    # Linux VA-API and WebGL on its private X11 display.
    if acceleration or presentationbridge:
        arguments.append("--ignore-gpu-blocklist")

    if acceleration and not proprietarynvidia:
        arguments.append("--disable-gpu-driver-bug-workarounds")

    if proprietarynvidia and presentationbridge:
        # T1OS Ozone binds native EGL/GLES directly to the brokered NVIDIA EGL
        # device. ANGLE gl-egl binds its EGL display to X11 instead; under Xvfb
        # that display does not advertise NVIDIA's RGB DMA-BUF scanout formats.
        # Upstream VA-API-on-NVIDIA remains disabled because decoding belongs
        # exclusively to the independent T1OS media service.
        # The T1OS Chromium source adapter makes the exact --gpu-launcher
        # helper bypass only the GPU zygote. Utilities and renderers retain
        # Chromium's supported zygotes and the GPU process still applies its
        # kGpu sandbox after the helper installs the measured loader.
        arguments.extend([
            "--use-gl=egl",
            "--use-cmd-decoder=validating",
            "--disable-features=AcceleratedVideoDecodeLinuxGL,"
            "VaapiOnNvidiaGPUs",
        ])
        if not servicedecoder:
            arguments.append("--disable-accelerated-video-decode")
    elif presentationbridge:
        # The brokered render-node descriptor and RGB DMA-BUF transport are
        # driver-neutral.  EGL/GBM is therefore also the authoritative path on
        # Mesa backends such as vmwgfx; X11 remains input/window discovery only.
        arguments.extend([
            "--use-gl=egl",
        ])
    elif proprietarynvidia:
        # Hardware presentation was unavailable or explicitly rolled back.
        # Keep Chromium usable through the Xvfb/SwiftShader buffer while a
        # ready T1MD service independently supplies linear-memory frames.
        arguments.extend([
            "--disable-features=AcceleratedVideoDecodeLinuxGL,"
            "VaapiOnNvidiaGPUs",
        ])
        if not servicedecoder:
            arguments.append("--disable-accelerated-video-decode")

    return arguments


def requirevideoacceleration(graphicsdriver, acceleration, rendernode=""):
    """Reject proprietary NVIDIA startup unless the NVDEC runtime is complete."""
    proprietarynvidia = (
        str(graphicsdriver or "").replace("-", "_") in ("nvidia", "nvidia_drm")
    )

    if proprietarynvidia and (
        not acceleration
        or not acceleration.get("hardware_required")
        or not str(rendernode or "").strip()
    ):
        raise RuntimeError(
            "NVIDIA NVDEC/VA-API is required, but its packaged driver "
            "runtime dependencies, or display render node are unavailable"
        )

    return acceleration


def measurevideoacceleration(acceleration, rendernode):
    """Prove a hardware-required VA runtime on Chromium's selected DRM node."""
    acceleration = acceleration if isinstance(acceleration, dict) else None

    if not acceleration or not acceleration.get("hardware_required"):
        return acceleration

    diagnostics = []

    try:
        from media.media import videoacceleration

        measured = videoacceleration(
            {},
            refresh=True,
            diagnostics=diagnostics,
            preferrednode=rendernode,
            processidentity=dropengineidentity,
            probetimeout=CHROMEPROBETIMEOUT,
        )
    except Exception as error:
        measured = None
        diagnostics.append({
            "result": "probe-error",
            "error": str(error),
            "node": str(rendernode or ""),
        })

    measuredcodecs = {
        str(codec or "").strip().upper()
        for codec in (
            measured.get("codecs", ())
            if isinstance(measured, dict)
            else ()
        )
        if str(codec or "").strip()
    }
    browsercodecs = measuredcodecs & CHROMIUMVIDEOCODECS

    if (
        not measured
        or str(measured.get("driver", ""))
        != str(acceleration.get("driver", ""))
        or str(measured.get("device", ""))
        != str(rendernode or "")
        or not browsercodecs
    ):
        detail = json.dumps(
            diagnostics[-4:],
            sort_keys=True,
            separators=(",", ":"),
        )[-4096:]
        raise RuntimeError(
            "NVIDIA NVDEC/VA-API hardware probe failed for Chromium "
            f"device={rendernode or 'missing'} "
            f"measured_codecs={sorted(measuredcodecs)} detail={detail}"
        )

    result = dict(acceleration)
    result.update({
        "device": str(measured.get("device", "")),
        "probe": str(measured.get("probe", "")),
        "vendor": str(measured.get("vendor", "")),
        "codecs": tuple(measured.get("codecs") or ()),
    })
    return result


def cachearguments():
    """Bound Chromium's disposable tmpfs-backed network and media caches."""
    return [
        "--disk-cache-dir=" + CACHE,
        f"--disk-cache-size={DISKCACHEBYTES}",
        f"--media-cache-size={MEDIACACHEBYTES}",
    ]


def elf(path, *arguments):
    # Every shipped helper has a pinned PT_INTERP and RUNPATH. Direct exec
    # preserves the measured executable identity; invoking a generic loader
    # would make the security domain depend on attacker-controlled argv.
    return [path, *map(str, arguments)]


def dropengineidentity():
    # Chromium itself already enters the engine uid/gid before the first
    # Python opcode.  Child pre-exec hooks must therefore be idempotent: an
    # unprivileged process cannot call setgroups(2), even to request the empty
    # group set it already has.
    if os.geteuid() == 0:
        os.setgroups([])
        os.setresgid(ENGINEGID, ENGINEGID, ENGINEGID)
        os.setresuid(ENGINEUID, ENGINEUID, ENGINEUID)
        return
    if (tuple(os.getresuid()) != (ENGINEUID,) * 3 or
            tuple(os.getresgid()) != (ENGINEGID,) * 3 or
            os.getgroups()):
        raise PermissionError("Chromium engine identity is not confined")


def runtool(name, arguments, *, inputdata=None, output=False, timeout=3.0, background=False, environment=None):
    command = elf(TOOLS + "/" + name, *arguments)
    if background:
        process = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=ENGINELOG, stderr=ENGINELOG,
            env=environment, preexec_fn=dropengineidentity,
        )
        return process
    completed = subprocess.run(
        command,
        input=inputdata if inputdata is not None else b"",
        stdout=subprocess.PIPE if output else ENGINELOG,
        stderr=ENGINELOG,
        timeout=timeout,
        check=False,
        env=environment,
        preexec_fn=dropengineidentity,
    )
    return completed.stdout if output and completed.returncode == 0 else b""


KEYNAMES = {
    "BACKSPACE": "BackSpace", "DELETE": "Delete", "LEFT": "Left", "RIGHT": "Right",
    "UP": "Up", "DOWN": "Down", "HOME": "Home", "END": "End", "PAGEUP": "Page_Up",
    "PAGEDOWN": "Page_Down", "ENTER": "Return", "RETURN": "Return", "TAB": "Tab",
    "ESC": "Escape", "ESCAPE": "Escape", "SPACE": "space", "INSERT": "Insert",
    "F1": "F1", "F2": "F2", "F3": "F3", "F4": "F4", "F5": "F5", "F6": "F6",
    "F7": "F7", "F8": "F8", "F9": "F9", "F10": "F10", "F11": "F11", "F12": "F12",
    "MINUS": "minus", "EQUAL": "equal", "COMMA": "comma", "PERIOD": "period",
    "SLASH": "slash", "SEMICOLON": "semicolon", "APOSTROPHE": "apostrophe",
    "LEFTBRACKET": "bracketleft", "RIGHTBRACKET": "bracketright", "BACKSLASH": "backslash",
    "GRAVE": "grave", "PLAYPAUSE": "XF86AudioPlay",
}


def xdotool(arguments, **options):
    environment = engineenvironment()
    return runtool("xdotool", arguments, environment=environment, **options)


class ChromiumInputBridgeError(RuntimeError):
    pass


class PersistentInputBridge:
    """A bounded nonblocking connection to the persistent X11 input helper."""

    def __init__(self, process, windowid):
        self.process = process
        self.windowid = int(windowid)
        self.output = bytearray()
        self.outputoffset = 0
        self.pendingmotion = None
        os.set_blocking(self.process.stdin.fileno(), False)

    def _requirealive(self):
        status = self.process.poll()
        if status is not None:
            raise ChromiumInputBridgeError(
                f"persistent Chromium input bridge exited with status {status}"
            )

    def _queuedbytes(self):
        return max(0, len(self.output) - int(self.outputoffset))

    def _appendencoded(self, encoded):
        encoded = bytes(encoded)
        if (
            len(encoded) > INPUTBRIDGEQUEUELIMIT
            or self._queuedbytes() + len(encoded) > INPUTBRIDGEQUEUELIMIT
        ):
            raise ChromiumInputBridgeError(
                "persistent Chromium input bridge queue exceeded "
                f"{INPUTBRIDGEQUEUELIMIT} bytes"
            )
        if self.outputoffset and (
            self.outputoffset >= INPUTBRIDGEFLUSHBUDGET
            or self.outputoffset * 2 >= len(self.output)
            or len(self.output) + len(encoded) > INPUTBRIDGEQUEUELIMIT
        ):
            del self.output[:self.outputoffset]
            self.outputoffset = 0
        self.output.extend(encoded)

    def _materializemotion(self, force=False):
        if self.pendingmotion is None:
            return True
        if self._queuedbytes() and not force:
            return False
        encoded = self.pendingmotion
        if self._queuedbytes() + len(encoded) > INPUTBRIDGEQUEUELIMIT:
            return False
        self._appendencoded(encoded)
        self.pendingmotion = None
        return True

    def pending(self):
        return bool(self._queuedbytes() or self.pendingmotion is not None)

    def send(self, command):
        self._requirealive()
        encoded = (str(command) + "\n").encode("utf-8")
        if len(encoded) > INPUTBRIDGEQUEUELIMIT:
            raise ChromiumInputBridgeError(
                "persistent Chromium input bridge record is too large"
            )
        if str(command).startswith("M "):
            self.pendingmotion = encoded
        else:
            pendingbytes = len(self.pendingmotion or b"")
            if (
                self._queuedbytes() + pendingbytes + len(encoded)
                > INPUTBRIDGEQUEUELIMIT
            ):
                raise ChromiumInputBridgeError(
                    "persistent Chromium input bridge cannot queue an ordered transition"
                )
            self._materializemotion(force=True)
            self._appendencoded(encoded)
        self.flush()
        return True

    def flush(self, budget=INPUTBRIDGEFLUSHBUDGET):
        self._requirealive()
        budget = max(1, int(budget))
        senttotal = 0
        while senttotal < budget:
            self._materializemotion()
            queued = self._queuedbytes()
            if not queued:
                if self.outputoffset:
                    self.output.clear()
                    self.outputoffset = 0
                break
            amount = min(queued, budget - senttotal)
            try:
                sent = os.write(
                    self.process.stdin.fileno(),
                    bytes(
                        self.output[
                            self.outputoffset:self.outputoffset + amount
                        ]
                    ),
                )
            except (BlockingIOError, InterruptedError):
                break
            except BrokenPipeError as error:
                raise ChromiumInputBridgeError(
                    "persistent Chromium input bridge pipe closed"
                ) from error
            except OSError as error:
                raise ChromiumInputBridgeError(
                    f"persistent Chromium input bridge write failed: {error}"
                ) from error
            if int(sent) <= 0:
                raise ChromiumInputBridgeError(
                    "persistent Chromium input bridge write made no progress"
                )
            self.outputoffset += int(sent)
            senttotal += int(sent)
            if self.outputoffset >= len(self.output):
                self.output.clear()
                self.outputoffset = 0
        return senttotal

    def drain(self, timeout=0.5):
        deadline = time.monotonic() + max(0.0, float(timeout))
        while self.pending():
            self.flush()
            if not self.pending():
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0.0:
                raise ChromiumInputBridgeError(
                    "persistent Chromium input bridge remained backpressured"
                )
            try:
                _, writable, _ = select.select(
                    [], [self.process.stdin], [], min(0.05, remaining)
                )
            except Exception as error:
                raise ChromiumInputBridgeError(
                    f"persistent Chromium input bridge wait failed: {error}"
                ) from error
            if not writable:
                self._requirealive()
        return True

    def motion(self, x, y):
        self.send(f"M {max(0, int(x))} {max(0, int(y))}")

    def button(self, button, pressed):
        self.send(f"{'D' if pressed else 'U'} {max(1, min(7, int(button)))}")

    def click(self, button):
        self.send(f"C {max(1, min(7, int(button)))}")

    def key(self, sequence):
        if not sequence or len(sequence) > 256 or any(character in "\r\n" for character in sequence):
            raise ValueError("invalid Chromium input key sequence")
        self.send("K " + sequence)

    def text(self, value):
        encoded = str(value).encode("utf-8")[:1048576].hex()
        if encoded:
            self.send("T " + encoded)

    def resize(self, width, height):
        self.send(f"W {self.windowid} {int(width)} {int(height)}")

    def focus(self):
        self.send(f"F {self.windowid}")

    def ping(self):
        self.send("P")
        self.drain()
        try:
            readable, _, _ = select.select(
                [self.process.stdout], [], [], 2.0
            )
            response = self.process.stdout.readline() if readable else b""
        except Exception as error:
            raise ChromiumInputBridgeError(
                f"Chromium input bridge round-trip failed: {error}"
            ) from error
        if response != b"PONG\n":
            raise ChromiumInputBridgeError(
                "Chromium input bridge round-trip timed out"
            )
        return True

    def fullscreen(self):
        self.send(f"S {self.windowid}")
        self.drain()
        try:
            readable, _, _ = select.select(
                [self.process.stdout], [], [], 1.0
            )
            response = (
                self.process.stdout.readline().strip().split()
                if readable
                else []
            )
        except Exception as error:
            raise ChromiumInputBridgeError(
                f"Chromium fullscreen state query failed: {error}"
            ) from error
        if not readable:
            raise ChromiumInputBridgeError(
                "Chromium fullscreen state query timed out"
            )
        if len(response) != 2 or response[0] != b"FULLSCREEN":
            raise ChromiumInputBridgeError(
                "Chromium input bridge returned an invalid fullscreen state"
            )
        return response[1] == b"1"

    def quit(self):
        self.send(f"Q {self.windowid}")
        self.drain(timeout=0.25)

    def close(self):
        try:
            self.process.stdin.close()
        except Exception:
            pass
        try:
            self.process.stdout.close()
        except Exception:
            pass


def startinputbridge(environment, windowid):
    process = subprocess.Popen(
        elf(TOOLS + "/t1os-xinput"),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=ENGINELOG,
        env=environment,
        preexec_fn=dropengineidentity,
    )
    try:
        readable, _, _ = select.select([process.stdout], [], [], 3.0)
        if not readable or process.stdout.readline() != b"READY\n":
            status = process.poll()
            raise RuntimeError(
                "persistent Chromium input bridge did not connect"
                + (f" (status {status})" if status is not None else "")
            )
        logline("persistent Chromium input bridge connected")
        return PersistentInputBridge(process, windowid)
    except Exception:
        try:
            process.terminate()
            process.wait(timeout=1.0)
        except Exception:
            pass
        raise


def processenginecommand(message, environment, inputbridge):
    operation = str(message.get("op", ""))
    if operation == "motion":
        inputbridge.motion(message.get("x", 0), message.get("y", 0))
    elif operation == "button":
        button = max(1, min(7, int(message.get("button", 1))))
        inputbridge.button(button, message.get("state") == "down")
    elif operation == "scroll":
        dx = int(message.get("dx", 0))
        dy = int(message.get("dy", 0))
        # WindowServer follows T1OS's content-direction convention: positive
        # vertical deltas move toward earlier content. X11 uses button 4 for
        # that direction and button 5 for later content.
        button = 4 if dy > 0 else 5
        for _ in range(min(12, max(0, abs(dy)))):
            inputbridge.click(button)
        button = 7 if dx > 0 else 6
        for _ in range(min(12, max(0, abs(dx)))):
            inputbridge.click(button)
    elif operation == "text":
        text = str(message.get("text", ""))[:4096]
        if text:
            inputbridge.text(text)
    elif operation == "key":
        key = str(message.get("key", "")).upper()
        state = str(message.get("state", "down")).lower()
        modifiers = message.get("mods", {}) if isinstance(message.get("mods"), dict) else {}
        mapped = KEYNAMES.get(key, key.lower() if len(key) == 1 else "")
        if not mapped:
            return None
        prefixes = []
        if modifiers.get("ctrl"):
            prefixes.append("ctrl")
        if modifiers.get("alt"):
            prefixes.append("alt")
        if modifiers.get("shift"):
            prefixes.append("shift")
        if modifiers.get("meta"):
            prefixes.append("super")
        chord = "+".join(prefixes + [mapped])
        if prefixes:
            if state in ("down", "repeat"):
                inputbridge.key(chord)
        elif state in ("down", "repeat"):
            inputbridge.key(mapped)
        if modifiers.get("ctrl") and key == "C" and state == "down":
            time.sleep(0.08)
            try:
                data = runtool(
                    "xclip", ["-selection", "clipboard", "-out"],
                    output=True, timeout=1.0, environment=environment,
                )
            except subprocess.TimeoutExpired:
                data = b""
            if data:
                return {"op": "clipboard", "text": data.decode("utf-8", "replace")[:1048576]}
    elif operation == "paste":
        text = str(message.get("text", ""))[:1048576]
        if text:
            inputbridge.text(text)
    elif operation == "resize":
        # Logical T1OS windows retain MINWIDTH/MINHEIGHT. Their globally scaled
        # private X backing may intentionally be smaller on a high-DPI display.
        width = max(2, min(int(message.get("width", BASEWIDTH)), int(CONFIG.get("maximum_width", MAXWIDTH))))
        height = max(2, min(int(message.get("height", BASEHEIGHT)), int(CONFIG.get("maximum_height", MAXHEIGHT))))
        inputbridge.resize(width, height)
    elif operation == "focus":
        inputbridge.focus()
    elif operation == "input-diagnostic":
        if not inputbridge.ping():
            raise RuntimeError("persistent Chromium input bridge did not complete its event round trip")
        return {
            "op": "input-diagnostic",
            "ok": True,
            "fullscreen": inputbridge.fullscreen(),
        }
    return None


def enginesupervisor(
    channel, width, height, screenwidth=None, screenheight=None,
    logicalscreenwidth=None, logicalscreenheight=None,
    logicalwindowwidth=None, logicalwindowheight=None,
    presentationtoken=None,
):
    children = []
    chrome = None
    inputbridge = None
    environment = None
    servicedecoder = None
    controloutput = None
    controlopen = True
    stopreason = "chromium process exited"
    try:
        environment = engineenvironment()

        # The private X screen represents the real T1OS display.  Making it
        # larger than the display caused EWMH/theatre/fullscreen requests to
        # expand Chromium into a hidden 3840x2160 viewport and then crop it
        # back into the T1OS window.
        maxwidth = max(width, int(screenwidth if screenwidth is not None else width))
        maxheight = max(height, int(screenheight if screenheight is not None else height))
        densitywidth = int(
            logicalscreenwidth if logicalscreenwidth is not None else maxwidth
        )
        densityheight = int(
            logicalscreenheight if logicalscreenheight is not None else maxheight
        )
        logicalwidth = max(
            1, int(logicalwindowwidth if logicalwindowwidth is not None else width),
        )
        logicalheight = max(
            1, int(logicalwindowheight if logicalwindowheight is not None else height),
        )
        devicescale = chromiumbackingdevicescale(
            densitywidth, densityheight,
        )
        commandwidth, commandheight = chromiumcommandwindowsize(
            width, height, devicescale,
        )
        xvfb = subprocess.Popen(
            elf(TOOLS + "/Xvfb", DISPLAY, "-screen", "0", f"{maxwidth}x{maxheight}x24", "-fbdir", FRAMEBUFFER, "-nolisten", "tcp", "-noreset", "-nocursor"),
            stdin=subprocess.PIPE, stdout=ENGINELOG, stderr=ENGINELOG, env=environment, preexec_fn=dropengineidentity,
        )
        xvfb.stdin.close()
        children.append(xvfb)
        deadline = time.monotonic() + XVFBREADYTIMEOUT
        while time.monotonic() < deadline and not os.path.exists(DISPLAYSOCKET):
            if xvfb.poll() is not None:
                raise RuntimeError(f"Xvfb exited with status {xvfb.returncode}")
            time.sleep(0.05)
        if not os.path.exists(DISPLAYSOCKET):
            raise TimeoutError("Xvfb did not create its private display")

        xwmready = RUNTIME + "/xwm.ready"
        environment["T1OS_XWM_READY"] = xwmready
        environment["T1OS_XWM_ROOT_WIDTH"] = str(width)
        environment["T1OS_XWM_ROOT_HEIGHT"] = str(height)
        windowmanager = subprocess.Popen(
            elf(TOOLS + "/t1os-xwm"),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=ENGINELOG,
            env=environment, preexec_fn=dropengineidentity,
        )
        windowmanager.stdin.close()
        children.append(windowmanager)
        deadline = time.monotonic() + XWMREADYTIMEOUT
        while time.monotonic() < deadline and not os.path.isfile(xwmready):
            if windowmanager.poll() is not None:
                raise RuntimeError(
                    f"T1OS Chromium X11 protocol bridge exited with status {windowmanager.returncode}"
                )
            time.sleep(0.01)
        if not os.path.isfile(xwmready):
            raise TimeoutError("T1OS Chromium X11 protocol bridge did not become ready")
        os.set_blocking(windowmanager.stdout.fileno(), False)

        graphicsdriver = activegraphicsdriver()
        graphicsrendernode = activegraphicsrendernode()
        proprietarynvidia = graphicsdriver in ("nvidia", "nvidia_drm")
        presentationbridge = bool(presentationtoken and graphicsrendernode)
        servicedecoder, servicedecoderreason = (
            t1osmediadecoderconfiguration(graphicsdriver)
            if proprietarynvidia
            else (None, "display-driver-not-nvidia")
        )
        if servicedecoder:
            servicedecoder = dict(servicedecoder)
            servicedecoder["output_mode"] = t1osmediadecoderoutputmode(
                presentationbridge
            )
        debugconfiguration = chromiumdebugconfiguration()
        if debugconfiguration.get("source") in (
            "invalid-settings",
            "invalid-launcher-fallback",
        ):
            logline(
                "chromium hardware diagnostic policy rejected "
                f"detail={debugconfiguration.get('error', 'unknown')}"
            )
        elif debugconfiguration["enabled"]:
            logline(
                "chromium bounded diagnostics selected "
                f"source={debugconfiguration.get('source')} "
                f"engine_log_limit_bytes="
                f"{debugconfiguration['engine_log_limit_bytes']}"
            )

        # Chromium never receives NVIDIA's decode authority. The browser-side
        # T1MD implementation only consumes pre-opened service descriptors;
        # the software rollback needs the same guarantee when the service is
        # disabled or unavailable.
        if proprietarynvidia:
            environment = servicechromiumenvironment(environment)

        if proprietarynvidia and servicedecoder:
            acceleration = None
            logline(
                "chromium T1OS media decoder selected "
                f"protocol={servicedecoder['protocol']}/"
                f"{servicedecoder['protocol_version']} "
                f"service_pid={servicedecoder['service_pid']} "
                "channel=browser-brokered "
                f"output={servicedecoder['output_mode']} "
                f"debug={debugconfiguration['enabled']} "
                "nvidia_vaapi_environment=disabled "
                "cuda_uvm_access=service-only"
            )
        elif proprietarynvidia and NVIDIADIRECTVAAPIQUARANTINED:
            acceleration = None
            logline(
                "chromium direct NVIDIA VA-API disabled "
                "reason=host-reset-on-first-decoder "
                f"gpu_rendering={'nvidia-egl' if presentationbridge else 'swiftshader'} "
                "software_video_decode=enabled "
                "nvidia_vaapi_environment=disabled broker=disabled "
                f"service={servicedecoderreason}"
            )
        else:
            acceleration = requirevideoacceleration(
                graphicsdriver,
                vaapiconfiguration(graphicsdriver),
                rendernode=graphicsrendernode,
            )
            acceleration = measurevideoacceleration(
                acceleration,
                graphicsrendernode,
            )

        environment = chromiumgraphicsenvironment(
            environment,
            graphicsdriver,
            presentationbridge=presentationbridge,
        )
        configureprofilesession(
            CONFIG.get("restore_session", True),
            single_root=presentationbridge,
        )
        if acceleration:
            environment["LIBVA_DRIVERS_PATH"] = acceleration["driver_path"]
            environment["LIBVA_DRIVER_NAME"] = acceleration["driver"]
            if presentationbridge and not proprietarynvidia:
                # Keep non-GPU processes on Chromium's closure.  The direct
                # subprocess helper installs the matched Mesa catalogue only
                # after it has verified a GPU-process launch boundary.
                environment["LD_LIBRARY_PATH"] = BASEGRAPHICSLIBRARYPATH
            else:
                environment["LD_LIBRARY_PATH"] = (
                    LIBRARIES + ":" + acceleration["library_path"]
                )
            for name, value in dict(
                acceleration.get("environment") or {}
            ).items():
                if str(name).strip() and str(value).strip():
                    environment[str(name)] = str(value)
        chrome_arguments = [
            # Execute Chromium and its zygote children from the persistent
            # T1OS software directory. The preload provider redirects only
            # Chromium's initial setuid-helper discovery to the relative
            # sandbox name; the browser and zygote executable identity stays
            # this persistent absolute path.
            CHROMEEXECUTABLE, "--ozone-platform=x11",
            "--browser-subprocess-path=" + CHROMEEXECUTABLE,
            "--gpu-launcher=" + SUBPROCESSEXECUTABLE,
            "--user-data-dir=" + PROFILE,
            *cachearguments(), "--no-first-run", "--no-default-browser-check",
            "--disable-session-crashed-bubble", "--hide-crash-restore-bubble",
            "--password-store=basic",
            "--disable-dev-shm-usage", "--disable-breakpad",
            "--disable-crash-reporter", "--disable-crashpad",
            f"--log-level={0 if debugconfiguration['enabled'] else 2}",
            "--enable-gpu",
            "--force-color-profile=srgb",
            "--enable-smooth-scrolling",
            f"--force-device-scale-factor={devicescale:g}",
            f"--window-size={commandwidth},{commandheight}",
            f"--window-position=0,0",
        ]
        if acceleration:
            chrome_arguments.append(
                "--enable-features=AcceleratedVideoDecodeLinuxGL"
                + (
                    ",VaapiOnNvidiaGPUs"
                    if proprietarynvidia or graphicsdriver == "nouveau"
                    else ""
                )
            )
            if acceleration.get("device") or graphicsrendernode:
                chrome_arguments.append(
                    "--hardware-video-device-path="
                    + str(acceleration.get("device") or graphicsrendernode)
                )
        # T1OS has selected and packaged the display driver through its
        # hardware contract. GPU feature policy remains independent of whether
        # that driver also exposes a supported browser video decoder.
        chrome_arguments.extend(
            browsergpuarguments(
                graphicsdriver,
                acceleration,
                servicedecoder=servicedecoder,
                presentationbridge=presentationbridge,
            )
        )
        chrome_arguments.extend(
            t1osmediadecoderarguments(servicedecoder)
        )
        chrome_arguments.extend(chromiumdebugarguments())
        if presentationbridge:
            chrome_arguments.append(
                "--enable-features=" + PRESENTATIONFEATURE
            )
            chrome_arguments.extend([
                "--t1os-presentation-socket=" + PRESENTATIONSOCKET,
                "--t1os-presentation-token=" + str(presentationtoken),
                "--t1os-presentation-render-node=" + str(graphicsrendernode),
            ])
            environment["T1OS_PRESENTATION_BRIDGE"] = "1"
            environment["T1OS_PRESENTATION_RENDER_NODE"] = str(
                graphicsrendernode
            )
            logline(
                "chromium T1OS surfaceless presentation selected "
                f"render_node={graphicsrendernode} brokered_socket=1"
            )

        renderer_mode, renderer_arguments = rendererconfiguration(
            graphicsdriver,
            presentationbridge=presentationbridge,
        )
        chrome_arguments.extend(renderer_arguments)
        chrome_arguments = mergechromiumfeaturearguments(chrome_arguments)

        logline(
            f"chromium renderer requested mode="
            f"{renderer_mode} "
            f"driver={graphicsdriver or 'unknown'} containment="
            f"chromium-sandbox+architect-policy gl_provider="
            f"{'nvidia-egl' if proprietarynvidia and presentationbridge else ('egl-gbm' if presentationbridge else 'base')} "
            f"gpu_launch="
            f"{'direct-measured-helper' if presentationbridge else 'default'} "
            f"vaapi="
            f"{acceleration.get('driver') if acceleration else 'unavailable'} "
            f"video_device="
            f"{(acceleration.get('device') if acceleration else graphicsrendernode if presentationbridge else 'unavailable')} "
            f"video_decode="
            f"{'t1os-' + servicedecoder['output_mode'] if servicedecoder else ('software-direct-vaapi-quarantine' if proprietarynvidia and NVIDIADIRECTVAAPIQUARANTINED else 'hardware')} "
            f"media_service="
            f"{servicedecoderreason} "
            f"scale={devicescale:g} "
            f"backing={width}x{height} surface={maxwidth}x{maxheight} "
            f"command_dip={commandwidth}x{commandheight} "
            f"logical={logicalwidth}x{logicalheight} "
            f"backing_ratio={chromiumbackingratio(densitywidth, densityheight):.6f} "
            f"output={densitywidth}x{densityheight}"
        )
        chrome_arguments.append(str(CONFIG.get("home_page", "about:blank")))
        chrome_environment = dict(environment)
        google_api_credentials = loadgoogleapicredentials()
        chrome_environment = applygoogleapicredentials(
            chrome_environment,
            google_api_credentials,
        )
        logline(
            "chromium Google API credential contract "
            f"configured={google_api_credentials is not None} "
            f"oauth={bool(google_api_credentials and google_api_credentials.get('google_default_client_id'))} "
            "source=architect-protected-runtime"
        )
        if servicedecoder:
            chrome_environment = servicechromiumenvironment(
                chrome_environment
            )
            chrome_environment[MEDIADECODEOUTPUTVARIABLE] = (
                servicedecoder["output_mode"]
            )
        chrome_environment["T1OS_CHROMIUM_SANDBOX_DISCOVERY"] = "1"
        launch_id = os.urandom(16).hex()
        chrome_environment[CHROMIUMLAUNCHVARIABLE] = launch_id
        chrome_environment["SANDBOX_LD_PRELOAD"] = (
            chrome_environment["LD_PRELOAD"]
        )
        chrome_environment["SANDBOX_LD_LIBRARY_PATH"] = (
            chrome_environment["LD_LIBRARY_PATH"]
        )
        # An empty value means this launch intentionally has no vendor GPU
        # contract (for example, the explicit SwiftShader rollback).  Do not
        # substitute the base path here: zygoteproviderstatus uses presence of
        # this value to require the NVIDIA EGL/GBM environment as well.
        expected_gpu_library_path = chrome_environment.get(
            NVIDIAGPULIBRARYPATHVARIABLE,
            MESAGRAPHICSLIBRARYPATH
            if presentationbridge and not proprietarynvidia
            else "",
        )
        chrome = subprocess.Popen(
            chrome_arguments, stdin=subprocess.PIPE, stdout=ENGINELOG, stderr=ENGINELOG,
            env=chrome_environment, cwd=PROGRAM, preexec_fn=dropengineidentity,
        )
        chrome.stdin.close()
        children.append(chrome)

        # Do not report readiness merely because the browser process was
        # spawned. Wait until it owns a visible X11 window so the application
        # never gets stuck presenting an empty Xvfb surface.
        # Native SUID sandbox and GPU initialization can take materially
        # longer on first boot from removable storage than in the VM.
        windowdeadline = time.monotonic() + CHROMEWINDOWTIMEOUT
        window = b""
        startupxwmincoming = b""

        while time.monotonic() < windowdeadline:
            if chrome.poll() is not None:
                raise RuntimeError(f"Chromium exited before creating a window (status {chrome.returncode})")

            readable, _, _ = select.select(
                [windowmanager.stdout], [], [], 0.20
            )
            if readable:
                try:
                    startupdata = windowmanager.stdout.read(65536)
                    if startupdata:
                        startupxwmincoming += startupdata
                except BlockingIOError:
                    pass
                while b"\n" in startupxwmincoming:
                    line, startupxwmincoming = startupxwmincoming.split(b"\n", 1)
                    parts = line.split()
                    if len(parts) == 2 and parts[0] == b"WINDOW":
                        window = parts[1]
                        break

            if window:
                break

        if not window:
            logchromiumprocesses()
            raise TimeoutError("Chromium did not create a visible window")

        windowid = window.splitlines()[0].decode("ascii", "replace")
        inputbridge = startinputbridge(environment, windowid)
        children.append(inputbridge.process)
        inputbridge.resize(width, height)
        runtime_status = {}
        runtime_deadline = (
            time.monotonic() + CHROMEGPURUNTIMETIMEOUT
        )

        while time.monotonic() < runtime_deadline:
            runtime_status = zygoteproviderstatus(
                chrome_environment.get("LD_LIBRARY_PATH", ""),
                launch_id,
                chrome.pid,
                expected_gpu_library_path,
            )

            if (
                runtime_status.get("gpu_runtime_ready")
                and not runtime_status.get("nvidia_broker_found")
            ):
                break

            if chrome.poll() is not None:
                break

            time.sleep(0.05)

        logline(
            "chromium GPU runtime contract "
            f"ready={bool(runtime_status.get('gpu_runtime_ready'))} "
            f"launch_scope={bool(runtime_status.get('gpu_launch_scope'))} "
            f"gpu_pid={runtime_status.get('gpu_runtime_pid')} "
            f"zygote_provider={bool(runtime_status.get('provider'))} "
            f"gpu_provider={bool(runtime_status.get('gpu_provider'))} "
            f"gpu_environment={bool(runtime_status.get('gpu_environment'))} "
            f"gpu_graphics_environment="
            f"{bool(runtime_status.get('gpu_graphics_environment'))} "
            f"gpu_library_path={bool(runtime_status.get('gpu_library_path'))} "
            f"gpu_loader="
            f"{'nvidia-canonical' if expected_gpu_library_path == NVIDIAGRAPHICSLIBRARYPATH else 'mesa-canonical' if expected_gpu_library_path == MESAGRAPHICSLIBRARYPATH else 'base'} "
            f"nvidia_broker="
            f"{bool(runtime_status.get('nvidia_broker_found'))} "
            f"nvidia_broker_pid={runtime_status.get('nvidia_broker_pid')} "
            f"utility_ready="
            f"{bool(runtime_status.get('utility_runtime_ready'))} "
            f"utility_pid={runtime_status.get('utility_runtime_pid')} "
            f"utility_provider="
            f"{bool(runtime_status.get('utility_provider'))} "
            f"candidates={len(runtime_status.get('candidates') or ())} "
            f"scan_errors={len(runtime_status.get('scan_errors') or ())} "
            f"va_driver_loaded_at_ready="
            f"{bool(runtime_status.get('gpu_driver_loaded'))} "
            f"video_device="
            f"{acceleration.get('device') if acceleration else graphicsrendernode if presentationbridge else 'unavailable'} "
            f"media_decoder="
            f"{servicedecoder.get('feature') if servicedecoder else 'unavailable'} "
            f"media_service_pid="
            f"{servicedecoder.get('service_pid') if servicedecoder else 'unavailable'} "
            f"media_channel="
            f"{'browser-brokered' if servicedecoder else 'none'}"
        )

        gpu_contract_failed = bool(
            presentationbridge
            and not runtime_status.get("gpu_runtime_ready")
        )
        nvidia_contract_failed = bool(
            proprietarynvidia and runtime_status.get("nvidia_broker_found")
        )
        utility_contract_failed = not runtime_status.get(
            "utility_runtime_ready"
        )
        if gpu_contract_failed or nvidia_contract_failed or utility_contract_failed:
            logline(
                "chromium GPU contract failure snapshot "
                f"browser_pid={chrome.pid} browser_status={chrome.poll()} "
                f"gpu_contract_failed={gpu_contract_failed} "
                f"nvidia_contract_failed={nvidia_contract_failed} "
                f"utility_contract_failed={utility_contract_failed}"
            )
            loggpucandidatediagnostics(runtime_status)
            logchromiumprocesses()

        if nvidia_contract_failed:
            raise RuntimeError(
                "Chromium quarantined NVIDIA/UVM decode broker detected"
            )
        if gpu_contract_failed:
            raise RuntimeError(
                "Chromium rendering contract failed: no launch-scoped GPU "
                "process proved the selected EGL/GBM environment"
            )
        if utility_contract_failed:
            logline(
                "chromium utility process was not directly observable; "
                "continuing because utilities inherit Chromium's measured "
                "zygote loader and do not own presentation"
            )

        logline(
            f"chromium window ready id={windowid} renderer="
            f"{renderer_mode} "
            f"size={width}x{height}"
        )
        channel.sendall(json.dumps({
            "op": "ready",
            "damage": True,
            "library_path": environment.get("LD_LIBRARY_PATH", ""),
            "gpu_library_path": expected_gpu_library_path,
            "launch_id": launch_id,
            "browser_pid": chrome.pid,
            "video_driver": (
                acceleration.get("driver") if acceleration else ""
            ),
            "video_decoder": (
                servicedecoder.get("feature") if servicedecoder else ""
            ),
            "video_decode_service_pid": (
                servicedecoder.get("service_pid") if servicedecoder else None
            ),
            "video_decode_output": (
                servicedecoder.get("output_mode") if servicedecoder else "software"
            ),
        }, separators=(",", ":")).encode("utf-8") + b"\n")
        # XDamage may have reported Chromium's first paint while the top-level
        # window was still being discovered. Seed one complete presentation so
        # the parent never waits forever for a second browser repaint.
        channel.sendall(json.dumps({
            "op": "damage",
            "rect": [0, 0, width, height],
        }, separators=(",", ":")).encode("utf-8") + b"\n")
        channel.setblocking(False)
        controloutput = JsonLineQueue(limit=ENGINEQUEUELIMIT, damage=True)
        incoming = b""
        xwmincoming = startupxwmincoming
        browserfullscreen = False
        browsertitle = ""
        nexttitlecheck = 0.0

        def processwindowmanageroutput():
            nonlocal xwmincoming, browserfullscreen
            while b"\n" in xwmincoming:
                line, xwmincoming = xwmincoming.split(b"\n", 1)
                parts = line.split()
                if (
                    len(parts) == 2
                    and parts[0] == b"FULLSCREEN"
                    and parts[1] in (b"0", b"1")
                ):
                    currentfullscreen = parts[1] == b"1"
                    if currentfullscreen != browserfullscreen:
                        browserfullscreen = currentfullscreen
                        controloutput.queue({
                            "op": "web-fullscreen",
                            "fullscreen": browserfullscreen,
                        })
                    continue
                if len(parts) == 2 and parts[0] == b"CURSOR":
                    controloutput.queue({
                        "op": "cursor",
                        "name": parts[1].decode("ascii", "replace"),
                    })
                    continue
                if len(parts) == 6 and parts[0] == b"CURSOR_IMAGE":
                    controloutput.queue({
                        "op": "cursor-image",
                        "width": int(parts[1]),
                        "height": int(parts[2]),
                        "xhot": int(parts[3]),
                        "yhot": int(parts[4]),
                        "hash": parts[5].decode("ascii", "replace"),
                    })
                    continue
                if len(parts) != 5 or parts[0] != b"DAMAGE":
                    continue
                try:
                    rect = [int(value) for value in parts[1:]]
                    controloutput.queue({
                        "op": "damage",
                        "rect": rect,
                    })
                except ValueError:
                    pass

        # Preserve protocol records that followed WINDOW in the same startup
        # read instead of waiting for another pipe-readability edge.
        processwindowmanageroutput()
        while chrome.poll() is None:
            if windowmanager.poll() is not None:
                raise RuntimeError(
                    f"T1OS Chromium X11 protocol bridge exited with status {windowmanager.returncode}"
                )
            inputbridge._requirealive()
            now = time.monotonic()
            if now >= nexttitlecheck:
                nexttitlecheck = now + 0.5
                try:
                    rawtitle = runtool(
                        "xdotool",
                        ["getwindowname", windowid],
                        output=True,
                        timeout=0.25,
                        environment=environment,
                    )
                except subprocess.TimeoutExpired:
                    # Window titles are ancillary metadata.  A temporarily
                    # busy X server must not terminate the browser engine.
                    rawtitle = b""
                if rawtitle:
                    title = browserwindowname(
                        rawtitle.decode("utf-8", "replace")
                    )
                    if title != browsertitle:
                        browsertitle = title
                        controloutput.queue({
                            "op": "title",
                            "title": browsertitle,
                        })
            writabletargets = [channel] if controloutput.pending() else []
            if inputbridge.pending():
                writabletargets.append(inputbridge.process.stdin)
            readable, writable, _ = select.select(
                [channel, windowmanager.stdout], writabletargets, [], 0.004
            )
            if channel in writable:
                try:
                    controloutput.flush(channel)
                except (BrokenPipeError, ConnectionResetError):
                    controlopen = False
                    stopreason = "application control channel broke"
            if inputbridge.process.stdin in writable:
                inputbridge.flush()
            if channel in readable:
                data = channel.recv(65536)
                if not data:
                    controlopen = False
                    stopreason = "application control channel closed"
                    break
                incoming += data
                while b"\n" in incoming:
                    line, incoming = incoming.split(b"\n", 1)
                    if not line:
                        continue
                    try:
                        response = processenginecommand(
                            json.loads(line.decode("utf-8")), environment, inputbridge
                        )
                        if response:
                            controloutput.queue(response)
                    except (BufferError, ChromiumInputBridgeError):
                        raise
                    except Exception as error:
                        logline(f"engine command failed: {error}")
            if windowmanager.stdout in readable:
                try:
                    data = windowmanager.stdout.read(65536)
                except BlockingIOError:
                    data = b""
                if data:
                    xwmincoming += data
                    processwindowmanageroutput()
            if not controlopen:
                break
        status = chrome.poll()
        if status is None:
            logline(f"chromium engine stopping reason={stopreason}")
        else:
            logline(f"chromium engine exited status={status}")
        if controlopen:
            controloutput.queue({"op": "stopped", "status": status})
            deadline = time.monotonic() + 0.5
            while controloutput.pending() and time.monotonic() < deadline:
                _, writable, _ = select.select([], [channel], [], 0.05)
                if channel in writable:
                    controloutput.flush(channel)
    except BaseException as error:
        try:
            if controloutput is None:
                channel.sendall(
                    JsonLineQueue._encoded({
                        "op": "error",
                        "message": str(error)[:1024],
                    })
                )
            else:
                controloutput.queue({
                    "op": "error",
                    "message": str(error)[:1024],
                })
                deadline = time.monotonic() + 0.5
                while controloutput.pending() and time.monotonic() < deadline:
                    _, writable, _ = select.select([], [channel], [], 0.05)
                    if channel in writable:
                        controloutput.flush(channel)
        except Exception:
            pass
        logline(
            "engine supervisor failed "
            f"type={type(error).__name__} detail={error}"
        )
        logline(
            "engine supervisor traceback="
            + sanitizeengineoutput(traceback.format_exc(), 8192)
        )
    finally:
        try:
            logline(
                "chromium teardown begin "
                f"chrome_pid={getattr(chrome, 'pid', None)} "
                f"chrome_status={chrome.poll() if chrome is not None else None} "
                "children="
                + ",".join(
                    f"{getattr(child, 'pid', None)}:{child.poll()}"
                    for child in children[:16]
                )
            )
        except Exception:
            pass
        if chrome is not None and chrome.poll() is None:
            try:
                if inputbridge is not None:
                    inputbridge.quit()
                chrome.wait(timeout=2.0)
            except Exception:
                try:
                    chrome.terminate()
                    chrome.wait(timeout=1.0)
                except Exception:
                    pass
        if inputbridge is not None:
            inputbridge.close()
        for child in reversed(children):
            try:
                if child.poll() is None:
                    child.terminate()
            except Exception:
                pass
        deadline = time.monotonic() + 2.0
        for child in reversed(children):
            try:
                remaining = max(0.0, deadline - time.monotonic())
                child.wait(timeout=remaining)
            except Exception:
                try:
                    child.kill()
                except Exception:
                    pass
        try:
            logline(
                "chromium teardown complete "
                f"chrome_status={chrome.poll() if chrome is not None else None} "
                "children="
                + ",".join(
                    f"{getattr(child, 'pid', None)}:{child.poll()}"
                    for child in children[:16]
                )
            )
        except Exception:
            pass
        clearstaleprofilelock()
        try:
            channel.close()
        except Exception:
            pass
        os._exit(0)


def startengine():
    global ENGINEPID, ENGINECHANNEL, ENGINEBUFFER, ENGINEOUTPUT
    global ENGINESTATE, ENGINEERROR, ENGINESTART, AUDIOTHREAD
    global ENGINEW, ENGINEH, DIRECTBUFFERSTATE
    if ENGINEPID is not None:
        return
    ENGINEW, ENGINEH = chromiumbackingsize(
        WINW, WINH, SCREENW, SCREENH,
    )
    runtimefiles()
    prepareruntime()
    presentationtoken = None
    graphicsdriver = activegraphicsdriver()
    graphicsrendernode = activegraphicsrendernode()
    proprietarynvidia = graphicsdriver in ("nvidia", "nvidia_drm")
    if nvidiapresentationenabled() and graphicsrendernode:
        presentationtoken = os.urandom(32).hex()
        # Enter this state before queuing authorization so no caller can
        # present a software placeholder in the asynchronous reply window.
        DIRECTBUFFERSTATE = "gpu-pending"
        if not sendws({
            "op": "VIDEO_AUTHORIZE",
            "winid": WINID,
            "token": presentationtoken,
            "stream": PRESENTATIONSTREAM,
            "surface_type": "presentation",
        }):
            presentationtoken = None
            logline(
                "chromium hardware presentation authorization failed "
                "fallback=unavailable"
            )
            raise RuntimeError(
                "Chromium GPU presentation authorization could not be queued"
            )
    elif proprietarynvidia and graphicsrendernode:
        logline(
            "chromium NVIDIA hardware presentation rollback selected "
            "policy=disabled "
            "presentation=direct-xvfb "
            "t1md_import=linear-memory-if-service-ready"
        )
    parent, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        process = os.fork()
    except BaseException:
        parent.close()
        child.close()
        startengineoutputworker()
        raise
    if process == 0:
        parent.close()
        closeengineoutputreader()
        dropinheritedinstance()
        # Allocate the complete bounded root once. Chromium still starts at
        # ENGINEW/H, but a later display-mode growth can use the remaining root
        # without restarting Xvfb or reallocating a 4K shared framebuffer.
        surfacewidth, surfaceheight = chromiumbackingsurface()
        enginesupervisor(
            child,
            ENGINEW,
            ENGINEH,
            surfacewidth,
            surfaceheight,
            SCREENW,
            SCREENH,
            WINW,
            WINH,
            presentationtoken,
        )
    child.close()
    startengineoutputworker()
    parent.setblocking(False)
    ENGINEPID = process
    ENGINECHANNEL = parent
    ENGINEBUFFER = b""
    ENGINEOUTPUT = JsonLineQueue(limit=ENGINEQUEUELIMIT, motion=True)
    ENGINESTATE = "starting"
    ENGINEERROR = ""
    ENGINESTART = time.monotonic()
    AUDIOSTOP.clear()
    AUDIOTHREAD = threading.Thread(target=audioloop, name="chromium audio", daemon=True)
    AUDIOTHREAD.start()


def enginecommand(message):
    global LASTMOTION, LASTMOTIONSENT
    if ENGINECHANNEL is None or ENGINESTATE not in ("starting", "ready"):
        return False
    try:
        if ENGINEOUTPUT is None:
            raise ConnectionError("Chromium engine output queue is unavailable")
        # A click/key/text transition must never overtake the most recent
        # pointer location merely because the motion throttle has not fired.
        if str(message.get("op", "")) != "motion" and LASTMOTION is not None:
            ENGINEOUTPUT.queue(logicalmotioncommand(LASTMOTION))
            LASTMOTION = None
            LASTMOTIONSENT = time.monotonic()
        ENGINEOUTPUT.queue(message)
        flushengineoutput()
        return True
    except BufferError as error:
        raise ConnectionError(f"Chromium engine output queue failed: {error}") from error


def flushengineoutput():
    if ENGINECHANNEL is None or ENGINEOUTPUT is None:
        return 0
    try:
        return ENGINEOUTPUT.flush(ENGINECHANNEL)
    except (BrokenPipeError, ConnectionResetError) as error:
        raise ConnectionError(f"Chromium engine transport failed: {error}") from error


def receiveengine():
    global ENGINEBUFFER, ENGINESTATE, ENGINEERROR, NEEDREDRAW, PLACEHOLDER, WEBFULLSCREEN
    global ENGINEDAMAGESUPPORTED, ENGINEDAMAGE
    if ENGINECHANNEL is None:
        return
    try:
        while True:
            data = ENGINECHANNEL.recv(65536)
            if not data:
                ENGINESTATE = "stopped"
                break
            ENGINEBUFFER += data
            if len(data) < 65536:
                break
    except BlockingIOError:
        pass
    except Exception as error:
        ENGINESTATE = "stopped"
        ENGINEERROR = str(error)
    while b"\n" in ENGINEBUFFER:
        line, ENGINEBUFFER = ENGINEBUFFER.split(b"\n", 1)
        try:
            message = json.loads(line.decode("utf-8"))
        except Exception:
            continue
        operation = message.get("op")
        if operation == "ready":
            ENGINESTATE = "ready"
            ENGINEDAMAGESUPPORTED = bool(message.get("damage"))
            PLACEHOLDER = "loading"
            NEEDREDRAW = True
        elif operation == "damage":
            try:
                rect = [int(value) for value in message.get("rect", [])[:4]]
            except Exception:
                rect = []
            if len(rect) == 4 and rect[2] > 0 and rect[3] > 0:
                ENGINEDAMAGE.append(rect)
                if len(ENGINEDAMAGE) > 64:
                    left = min(value[0] for value in ENGINEDAMAGE)
                    top = min(value[1] for value in ENGINEDAMAGE)
                    right = max(value[0] + value[2] for value in ENGINEDAMAGE)
                    bottom = max(value[1] + value[3] for value in ENGINEDAMAGE)
                    ENGINEDAMAGE = [[left, top, right - left, bottom - top]]
        elif operation == "clipboard":
            setclipboard(message.get("text", ""))
        elif operation == "title":
            setbrowserwindowname(message.get("title", ""))
        elif operation == "cursor":
            setbrowsercursormode(message.get("name", ""))
        elif operation == "cursor-image":
            setbrowsercursorimage(
                message.get("hash", ""),
                message.get("width", 0),
                message.get("height", 0),
                message.get("xhot", 0),
                message.get("yhot", 0),
            )
        elif operation == "web-fullscreen":
            WEBFULLSCREEN = bool(message.get("fullscreen"))
            setbrowserfullscreen(WEBFULLSCREEN)
        elif operation == "error":
            ENGINESTATE = "error"
            ENGINEERROR = str(message.get("message", "chromium engine failed"))
            PLACEHOLDER = ENGINEERROR
            NEEDREDRAW = True
            detachdirectbuffer()
            if FULLSCREEN or FULLSCREENREQUEST is True:
                setbrowserfullscreen(False)
        elif operation == "stopped":
            ENGINESTATE = "stopped"
            PLACEHOLDER = "chromium engine stopped"
            NEEDREDRAW = True
            detachdirectbuffer()
            if FULLSCREEN or FULLSCREENREQUEST is True:
                setbrowserfullscreen(False)


def closexwd():
    global XWDFD, XWDMAP, XWDMETA, LASTFRAMECRC, LASTTILECRCS, ENGINEDAMAGE
    try:
        if XWDMAP is not None:
            XWDMAP.close()
    except Exception:
        pass
    try:
        if XWDFD is not None:
            os.close(XWDFD)
    except Exception:
        pass
    XWDFD = None
    XWDMAP = None
    XWDMETA = None
    LASTFRAMECRC = None
    LASTTILECRCS = {}
    ENGINEDAMAGE = []


def parsexwd(header):
    if len(header) < 100:
        raise ValueError("Xvfb framebuffer header is incomplete")
    values = struct.unpack(">25I", header[:100])
    endian = ">"
    if values[1] != 7:
        values = struct.unpack("<25I", header[:100])
        endian = "<"
    if values[1] != 7:
        raise ValueError("Xvfb framebuffer has an unsupported XWD version")
    header_size, _, _, depth, pixmap_width, pixmap_height = values[:6]
    byte_order = values[7]
    bits_per_pixel = values[11]
    bytes_per_line = values[12]
    red_mask, green_mask, blue_mask = values[14:17]
    colours = values[19]
    if depth not in (24, 32) or bits_per_pixel != 32:
        raise ValueError("Xvfb did not create a 32-bit pixel surface")
    offset = header_size + colours * 12
    return {
        "endian": endian, "offset": offset, "width": pixmap_width, "height": pixmap_height,
        "stride": bytes_per_line, "byte_order": byte_order, "red": red_mask, "green": green_mask,
        "blue": blue_mask,
    }


def openxwd():
    global XWDFD, XWDMAP, XWDMETA
    if XWDMAP is not None:
        return True
    try:
        descriptor = os.open(XWDFILE, os.O_RDONLY)
        size = os.fstat(descriptor).st_size
        if size < 100:
            os.close(descriptor)
            return False
        mapping = mmap.mmap(descriptor, size, mmap.MAP_SHARED, mmap.PROT_READ)
        metadata = parsexwd(mapping[:100])
        required = metadata["offset"] + metadata["stride"] * metadata["height"]
        if required > size:
            mapping.close()
            os.close(descriptor)
            return False
        XWDFD, XWDMAP, XWDMETA = descriptor, mapping, metadata
        requestdirectbuffer()
        return True
    except (FileNotFoundError, PermissionError):
        return False
    except Exception as error:
        logline(f"framebuffer open failed: {error}")
        closexwd()
        return False


def changedframerects(width, height, tilewidth=256, tileheight=128):
    global LASTTILECRCS
    offset = int(XWDMETA["offset"])
    stride = int(XWDMETA["stride"])
    view = memoryview(XWDMAP)
    current = {}
    dirtyrows = []

    try:
        top = 0
        while top < height:
            tileh = min(tileheight, height - top)
            runs = []
            runleft = None
            runright = None
            left = 0

            while left < width:
                tilew = min(tilewidth, width - left)
                checksum = 0

                for row in range(tileh):
                    start = offset + (top + row) * stride + left * 4
                    checksum = zlib.crc32(view[start:start + tilew * 4], checksum)

                key = (left, top, tilew, tileh)
                current[key] = checksum
                changed = LASTTILECRCS.get(key) != checksum

                if changed:
                    if runleft is None:
                        runleft = left
                    runright = left + tilew
                elif runleft is not None:
                    runs.append([runleft, top, runright - runleft, tileh])
                    runleft = None
                    runright = None

                left += tilew

            if runleft is not None:
                runs.append([runleft, top, runright - runleft, tileh])

            dirtyrows.append(runs)
            top += tileh
    finally:
        del view

    LASTTILECRCS = current
    rectangles = []
    active = {}

    for runs in dirtyrows:
        continuing = {}

        for rect in runs:
            key = (rect[0], rect[2])
            previous = active.get(key)

            if previous is not None and previous[1] + previous[3] == rect[1]:
                previous[3] += rect[3]
                continuing[key] = previous
            else:
                rectangles.append(rect)
                continuing[key] = rect

        active = continuing

    if len(rectangles) > 64:
        left = min(rect[0] for rect in rectangles)
        top = min(rect[1] for rect in rectangles)
        right = max(rect[0] + rect[2] for rect in rectangles)
        bottom = max(rect[1] + rect[3] for rect in rectangles)
        rectangles = [[left, top, right - left, bottom - top]]

    return rectangles


def consumeenginedamage(width, height):
    global ENGINEDAMAGE
    pending = ENGINEDAMAGE
    ENGINEDAMAGE = []
    rectangles = []

    for value in pending:
        left = max(0, int(value[0]))
        top = max(0, int(value[1]))
        right = min(int(width), int(value[0]) + int(value[2]))
        bottom = min(int(height), int(value[1]) + int(value[3]))

        if right <= left or bottom <= top:
            continue

        incoming = [left, top, right - left, bottom - top]
        merged = []

        for existing in rectangles:
            existingright = existing[0] + existing[2]
            existingbottom = existing[1] + existing[3]
            incomingright = incoming[0] + incoming[2]
            incomingbottom = incoming[1] + incoming[3]

            if (
                incoming[0] <= existingright
                and existing[0] <= incomingright
                and incoming[1] <= existingbottom
                and existing[1] <= incomingbottom
            ):
                mergeleft = min(incoming[0], existing[0])
                mergetop = min(incoming[1], existing[1])
                mergeright = max(incomingright, existingright)
                mergebottom = max(incomingbottom, existingbottom)
                incoming = [
                    mergeleft, mergetop,
                    mergeright - mergeleft, mergebottom - mergetop,
                ]
            else:
                merged.append(existing)

        merged.append(incoming)
        rectangles = merged

    if len(rectangles) > 32:
        left = min(rect[0] for rect in rectangles)
        top = min(rect[1] for rect in rectangles)
        right = max(rect[0] + rect[2] for rect in rectangles)
        bottom = max(rect[1] + rect[3] for rect in rectangles)
        rectangles = [[left, top, right - left, bottom - top]]

    return rectangles


def captureframe():
    global LASTFRAMECRC, LASTFRAME
    if DIRECTBUFFERSTATE in ("gpu-pending", "gpu"):
        closexwd()
        return False
    if not WINDOWREADY or ENGINESTATE != "ready" or not openxwd():
        return False
    width = min(ENGINEW, int(XWDMETA["width"]))
    height = min(ENGINEH, int(XWDMETA["height"]))
    if width <= 0 or height <= 0:
        return False
    if (
        DIRECTBUFFERSTATE in ("active", "refreshing")
        and (DIRECTBUFFERWIDTH != width or DIRECTBUFFERHEIGHT != height)
    ):
        requestdirectbuffer(refresh=True)
    rectangles = (
        consumeenginedamage(width, height)
        if ENGINEDAMAGESUPPORTED
        else changedframerects(width, height)
    )
    if not rectangles:
        return False

    LASTFRAME = time.monotonic()

    if DIRECTBUFFERSTATE in ("active", "refreshing"):
        for rect in rectangles:
            sendws({"op": "DAMAGE", "winid": WINID, "rect": rect})
        return True

    offset = int(XWDMETA["offset"])
    stride = int(XWDMETA["stride"])
    if width != WINW or height != WINH:
        outputrectangles = []
        GFX.beginscaledfileframe()
        try:
            for rect in rectangles:
                outputrect = sourcerecttooutput(
                    rect, WINW, WINH, width, height,
                )
                if outputrect[2] < 1 or outputrect[3] < 1:
                    continue
                if not GFX.blitfilescaledfast(
                    XWDFILE,
                    width,
                    height,
                    0,
                    0,
                    WINW,
                    WINH,
                    "BGRA32",
                    clip=outputrect,
                    stride=stride,
                    source_offset=offset,
                ):
                    return False
                outputrectangles.append(outputrect)
        finally:
            scaledmetrics = GFX.endscaledfileframe()
            if int(scaledmetrics.get("source_reads", 0)) > 1:
                logline(
                    "Chromium CPU scaled frame reread its source "
                    f"metrics={scaledmetrics}"
                )
        if not outputrectangles:
            return False
        rectangles = outputrectangles
        LASTFRAMECRC = tuple(
            LASTTILECRCS.get(key)
            for key in sorted(LASTTILECRCS)
        )
        presentrects(rectangles)
        return True

    view = memoryview(XWDMAP)

    try:
        for left, top, tilewidth, tileheight in rectangles:
            rowbytes = tilewidth * 4
            pixels = bytearray(rowbytes * tileheight)

            for row in range(tileheight):
                source = offset + (top + row) * stride + left * 4
                destination = row * rowbytes
                pixels[destination:destination + rowbytes] = view[source:source + rowbytes]

            pixels[3::4] = b"\xff" * (tilewidth * tileheight)

            if not GFX.blitbytesfast(
                pixels, tilewidth, tileheight, 0, 0,
                tilewidth, tileheight, left, top, "BGRA32",
            ):
                return False
    finally:
        del view

    LASTFRAMECRC = tuple(
        LASTTILECRCS.get(key)
        for key in sorted(LASTTILECRCS)
    )
    presentrects(rectangles)
    return True


def audiolatencymilliseconds(bytecount, samplerate=None):
    """Convert interleaved stereo S16 bytes to their playback duration."""

    rate = int(AUDIORATE if samplerate is None else samplerate)
    if rate < 1:
        return 0.0
    return max(0.0, float(bytecount) * 1000.0 / float(rate * 4))


def audiofifoqueuedbytes(descriptor):
    """Return bytes waiting between ALSA's file PCM and the Python relay."""

    try:
        value = fcntl.ioctl(
            descriptor,
            AUDIOFIONREAD,
            struct.pack("I", 0),
        )
        return max(0, int(struct.unpack("I", value[:4])[0]))
    except Exception:
        return 0


def writeaudioclock(clockdescriptor, sequence, descriptor, streamid, status):
    """Publish the complete downstream playback delay using a seqlock."""

    status = status if isinstance(status, dict) else {}
    rate = max(1, int(status.get("samplerate", AUDIORATE)))
    fifoframes = audiofifoqueuedbytes(descriptor) // 4
    serverqueuedframes = max(0, int(status.get("queued", 0))) // 4
    hardwarependingframes = max(
        0,
        int(status.get("hardware_pending_frames", 0)),
    )
    presentedframes = max(0, int(status.get("presented_bytes", 0))) // 4
    underruns = max(0, int(status.get("underruns", 0)))
    sequence = (max(0, int(sequence)) + 2) & ((1 << 64) - 2)
    if sequence == 0:
        sequence = 2
    updating = sequence - 1
    payload = AUDIOCLOCKFORMAT.pack(
        AUDIOCLOCKMAGIC,
        AUDIOCLOCKVERSION,
        updating,
        time.monotonic_ns(),
        fifoframes,
        serverqueuedframes,
        hardwarependingframes,
        presentedframes,
        underruns,
        rate,
        max(0, int(streamid or 0)) & 0xFFFFFFFF,
    )
    os.pwrite(
        clockdescriptor,
        struct.pack("<Q", updating),
        AUDIOCLOCKSEQUENCEOFFSET,
    )
    os.pwrite(clockdescriptor, payload, 0)
    os.pwrite(
        clockdescriptor,
        struct.pack("<Q", sequence),
        AUDIOCLOCKSEQUENCEOFFSET,
    )
    return sequence, {
        "fifo_frames": fifoframes,
        "server_queued_frames": serverqueuedframes,
        "hardware_pending_frames": hardwarependingframes,
        "presented_frames": presentedframes,
        "underruns": underruns,
        "samplerate": rate,
    }


def audioloop():
    client = None
    streamid = None
    descriptor = None
    clockdescriptor = None
    clocksequence = 0
    nextattempt = 0.0
    failurelogged = False
    pending = bytearray()
    relaywrites = 0
    relaybytes = 0
    relaymaximumqueued = 0
    lastrelaylog = 0.0
    try:
        deadline = time.monotonic() + 15.0
        fifo = AUDIO + "/output.pcm"
        while not AUDIOSTOP.is_set() and time.monotonic() < deadline:
            try:
                descriptor = os.open(fifo, os.O_RDONLY | os.O_NONBLOCK)
                break
            except FileNotFoundError:
                time.sleep(0.05)
        if descriptor is None:
            return
        clockdescriptor = os.open(AUDIOCLOCK, os.O_RDWR | os.O_CLOEXEC)
        sys.path.insert(0, "/the one/build")
        import audio.audio as audioapi
        while not AUDIOSTOP.is_set():
            now = time.monotonic()
            if streamid is None and now >= nextattempt:
                candidate = None
                try:
                    candidate = audioapi.AudioClient(path=AUDIOSOCK, timeout=5.0)
                    candidate.connect()
                    candidate_stream, streamstatus = candidate.openstream(
                        AUDIORATE,
                        # The private ALSA file/null bridge cannot report the
                        # real downstream T1OS hardware delay to Chromium.
                        # Keep only one PCM chunk of application prebuffer on
                        # top of AudioServer's measured hardware queue.  The
                        # ring remains large enough to absorb a short Python
                        # scheduling stall without accumulating half a second
                        # of invisible A/V latency.
                        bufferseconds=AUDIOSTREAMBUFFERSECONDS,
                        prebufferms=AUDIOSTREAMPREBUFFERMS,
                        latencyclass="interactive",
                    )
                    client = candidate
                    streamid = candidate_stream
                    clocksequence, _ = writeaudioclock(
                        clockdescriptor,
                        clocksequence,
                        descriptor,
                        streamid,
                        streamstatus,
                    )
                    failurelogged = False
                    logline("chromium audio stream connected")
                except Exception as error:
                    if candidate is not None:
                        try:
                            candidate.disconnect()
                        except Exception:
                            pass
                    if not failurelogged:
                        logline(
                            "chromium audio output unavailable; continuing muted: "
                            f"{error}"
                        )
                        failurelogged = True
                    nextattempt = time.monotonic() + 1.0

            readable, _, _ = select.select([descriptor], [], [], 0.25)
            if not readable:
                continue
            data = os.read(descriptor, AUDIOCHUNKBYTES)
            if not data:
                time.sleep(0.02)
                continue
            pending.extend(data)
            usable = len(pending) - (len(pending) % 4)
            if usable and streamid is not None:
                payload = bytes(pending[:usable])
                del pending[:usable]
                try:
                    response = client.writestream(
                        streamid,
                        payload,
                        stopcheck=AUDIOSTOP.is_set,
                    )
                    relaywrites += 1
                    relaybytes += len(payload)
                    queued = max(0, int(response.get("queued", 0)))
                    capacity = max(0, int(response.get("capacity", 0)))
                    relaymaximumqueued = max(relaymaximumqueued, queued)
                    clocksequence, clockstatus = writeaudioclock(
                        clockdescriptor,
                        clocksequence,
                        descriptor,
                        streamid,
                        response,
                    )
                    loggedat = time.monotonic()
                    if (
                        lastrelaylog <= 0.0
                        or loggedat - lastrelaylog >= AUDIORELAYLOGINTERVAL
                    ):
                        logline(
                            "chromium audio relay healthy "
                            f"stream={streamid} writes={relaywrites} "
                            f"bytes={relaybytes} "
                            f"queued_ms={audiolatencymilliseconds(queued):.1f} "
                            f"maximum_queued_ms="
                            f"{audiolatencymilliseconds(relaymaximumqueued):.1f} "
                            f"capacity_ms="
                            f"{audiolatencymilliseconds(capacity):.1f} "
                            f"fifo_ms="
                            f"{audiolatencymilliseconds(clockstatus['fifo_frames'] * 4):.1f} "
                            f"hardware_ms="
                            f"{audiolatencymilliseconds(clockstatus['hardware_pending_frames'] * 4):.1f} "
                            f"downstream_ms="
                            f"{audiolatencymilliseconds((clockstatus['fifo_frames'] + clockstatus['server_queued_frames'] + clockstatus['hardware_pending_frames']) * 4):.1f} "
                            f"presented_ms="
                            f"{audiolatencymilliseconds(clockstatus['presented_frames'] * 4):.1f} "
                            f"underruns={clockstatus['underruns']} "
                            f"prebuffer_ms={AUDIOSTREAMPREBUFFERMS}"
                        )
                        lastrelaylog = loggedat
                except Exception as error:
                    logline(
                        "chromium audio stream interrupted; continuing muted: "
                        f"{error}"
                    )
                    try:
                        client.disconnect()
                    except Exception:
                        pass
                    client = None
                    streamid = None
                    clocksequence, _ = writeaudioclock(
                        clockdescriptor,
                        clocksequence,
                        descriptor,
                        0,
                        {"samplerate": AUDIORATE},
                    )
                    failurelogged = True
                    nextattempt = time.monotonic() + 1.0
            elif usable:
                del pending[:usable]
    except Exception as error:
        logline(f"chromium audio failed: {error}")
    finally:
        if clockdescriptor is not None:
            try:
                writeaudioclock(
                    clockdescriptor,
                    clocksequence,
                    descriptor,
                    0,
                    {"samplerate": AUDIORATE},
                )
            except Exception:
                pass
            try:
                os.close(clockdescriptor)
            except Exception:
                pass
        if descriptor is not None:
            try:
                os.close(descriptor)
            except Exception:
                pass
        if client is not None:
            try:
                if streamid is not None:
                    client.closestream(streamid, drain=False)
                client.disconnect()
            except Exception:
                pass


def keyinput(message):
    key = str(message.get("key", "")).upper()
    state = str(message.get("state", "down")).lower()
    modifiers = message.get("mods", {}) if isinstance(message.get("mods"), dict) else {}
    ctrl = bool(modifiers.get("ctrl"))
    alt = bool(modifiers.get("alt"))
    meta = bool(modifiers.get("meta"))
    if state == "down":
        cancelsmoothscroll()
    # Printable unmodified keys arrive through TEXT with the final keyboard
    # layout already applied.  Sending both events would duplicate characters.
    printable = len(key) == 1 or key in {
        "SPACE", "MINUS", "EQUAL", "COMMA", "PERIOD", "SLASH", "SEMICOLON",
        "APOSTROPHE", "LEFTBRACKET", "RIGHTBRACKET", "BACKSLASH", "GRAVE",
    }
    if printable and not (ctrl or alt or meta):
        return
    if ctrl and key == "V" and state == "down":
        sendws({"op": "CLIPBOARD_GET", "types": ["text/plain"]})
        return
    enginecommand({"op": "key", "key": key, "state": state, "mods": modifiers})


def textinput(message):
    text = str(message.get("text", ""))
    if text:
        cancelsmoothscroll()
        enginecommand({"op": "text", "text": text[:4096]})


def queuesmoothscroll(dx=0, dy=0):
    global PENDINGSCROLLX, PENDINGSCROLLY

    try:
        PENDINGSCROLLX = max(
            -SMOOTHSCROLLLIMIT,
            min(SMOOTHSCROLLLIMIT, PENDINGSCROLLX + int(dx)),
        )
        PENDINGSCROLLY = max(
            -SMOOTHSCROLLLIMIT,
            min(SMOOTHSCROLLLIMIT, PENDINGSCROLLY + int(dy)),
        )
        return bool(PENDINGSCROLLX or PENDINGSCROLLY)
    except Exception as error:
        logline(f"smooth scroll queue failed: {error}")
        return False


def cancelsmoothscroll():
    global PENDINGSCROLLX, PENDINGSCROLLY, LASTSCROLLFRAME

    PENDINGSCROLLX = 0
    PENDINGSCROLLY = 0
    LASTSCROLLFRAME = 0.0


def smoothscrollstep(value, force=False):
    value = int(value)
    if not value:
        return 0

    magnitude = abs(value)
    if force:
        amount = magnitude
    else:
        amount = max(1, int(math.ceil(magnitude * SMOOTHSCROLLEASING)))
        amount = min(amount, SMOOTHSCROLLMAXSTEP)

    return amount if value > 0 else -amount


def flushsmoothscroll(force=False):
    global PENDINGSCROLLX, PENDINGSCROLLY, LASTSCROLLFRAME

    if not PENDINGSCROLLX and not PENDINGSCROLLY:
        return False

    now = time.monotonic()
    if not force and LASTSCROLLFRAME and now - LASTSCROLLFRAME < SCROLLFRAMEINTERVAL:
        return False

    dx = smoothscrollstep(PENDINGSCROLLX, force=force)
    dy = smoothscrollstep(PENDINGSCROLLY, force=force)

    if not enginecommand({"op": "scroll", "dx": dx, "dy": dy}):
        return False

    PENDINGSCROLLX -= dx
    PENDINGSCROLLY -= dy
    LASTSCROLLFRAME = now
    return True


def handlewindow(message):
    global SCREENW, SCREENH, WINID, BUFFERPATH, WINW, WINH, RUNNING, NEEDREDRAW, LASTMOTION
    global ENGINEW, ENGINEH, ENGINEDAMAGE
    global FULLSCREEN, FULLSCREENREQUEST, FULLSCREENCURSORHIDEAT
    global DIRECTBUFFERSTATE, DIRECTBUFFERERROR, DIRECTBUFFERWIDTH, DIRECTBUFFERHEIGHT
    operation = str(message.get("op", ""))
    if operation == "WELCOME":
        framebuffer = message.get("fb", {})
        SCREENW = max(1, int(framebuffer.get("w", SCREENW)))
        SCREENH = max(1, int(framebuffer.get("h", SCREENH)))
        if capturewindowgraphicscontract(message.get("graphics")):
            logline(
                "Chromium accepted WindowServer graphics contract "
                f"driver={WINDOWGRAPHICSCONTRACT.get('driver')} "
                f"render_node={WINDOWGRAPHICSCONTRACT.get('render_node')} "
                f"render_identity="
                f"{WINDOWGRAPHICSCONTRACT.get('render_identity')}"
            )
        else:
            logline(
                "Chromium WindowServer graphics contract unavailable or "
                "invalid; connector discovery remains the fallback"
            )
        createwindow()
    elif operation == "FB_SIZE":
        SCREENW = max(1, int(message.get("w", SCREENW)))
        SCREENH = max(1, int(message.get("h", SCREENH)))
    elif operation == "WINDOW_CREATED":
        WINID = int(message.get("winid", 0))
        BUFFERPATH = str(message.get("buffer", ""))
        WINW = max(MINWIDTH, int(message.get("w", BASEWIDTH)))
        WINH = max(MINHEIGHT, int(message.get("h", BASEHEIGHT)))
        bindbuffer()
        sendws({"op": "MAP", "winid": WINID})
        sendws({"op": "RAISE", "winid": WINID})
        sendws({"op": "FOCUS_SET", "winid": WINID})
        try:
            startengine()
            placeholder("starting chromium")
        except Exception as error:
            globals()["ENGINESTATE"] = "error"
            globals()["ENGINEERROR"] = str(error)
            globals()["PLACEHOLDER"] = str(error)
            logline(f"engine start failed: {error}")
            placeholder(str(error))
        if ACTIVATIONPENDING:
            activatewindow()
    elif operation == "RESIZED":
        WINW = max(MINWIDTH, int(message.get("w", WINW)))
        WINH = max(MINHEIGHT, int(message.get("h", WINH)))
        ENGINEW, ENGINEH = chromiumbackingsize(
            WINW, WINH, SCREENW, SCREENH,
        )
        bindbuffer()
        if (
            DIRECTBUFFERSTATE in ("active", "refreshing")
            and XWDMETA is not None
            and (DIRECTBUFFERWIDTH != ENGINEW or DIRECTBUFFERHEIGHT != ENGINEH)
        ):
            requestdirectbuffer(refresh=True)
        closexwd()
        ENGINEDAMAGE = [[0, 0, ENGINEW, ENGINEH]]
        if DIRECTBUFFERSTATE not in ("active", "refreshing"):
            placeholder("resizing")
        enginecommand({"op": "resize", "width": ENGINEW, "height": ENGINEH})
    elif operation == "WINDOW_STATE" and int(message.get("winid", 0)) == int(WINID or 0):
        previous = FULLSCREEN
        FULLSCREEN = (
            bool(message.get("fullscreen"))
            or str(message.get("state", "")).lower() == "fullscreen"
        )
        FULLSCREENREQUEST = None
        if FULLSCREEN != previous:
            FULLSCREENCURSORHIDEAT = 0.0
            setbrowsercursor(not FULLSCREEN, force=True)
        if FULLSCREEN != WEBFULLSCREEN:
            setbrowserfullscreen(WEBFULLSCREEN)
    elif (
        operation == "WINDOW_BUFFER_ATTACHED"
        and int(message.get("winid", 0)) == int(WINID or 0)
        and DIRECTBUFFERSTATE != "gpu"
    ):
        DIRECTBUFFERSTATE = "active"
        DIRECTBUFFERERROR = ""
        logline(
            "Chromium direct Xvfb presentation buffer attached "
            f"source={DIRECTBUFFERWIDTH}x{DIRECTBUFFERHEIGHT} "
            f"output={WINW}x{WINH}"
        )
    elif (
        operation == "WINDOW_BUFFER_DETACHED"
        and int(message.get("winid", 0)) == int(WINID or 0)
        and DIRECTBUFFERSTATE != "gpu"
    ):
        DIRECTBUFFERSTATE = "inactive"
        DIRECTBUFFERERROR = ""
        DIRECTBUFFERWIDTH = 0
        DIRECTBUFFERHEIGHT = 0
    elif (
        operation == "VIDEO_AUTHORIZED"
        and int(message.get("winid", 0)) == int(WINID or 0)
        and str(message.get("surface_type", "")) == "presentation"
        and str(message.get("stream", "")) == PRESENTATIONSTREAM
    ):
        if DIRECTBUFFERSTATE in ("pending", "active", "refreshing"):
            sendws({"op": "WINDOW_BUFFER_DETACH", "winid": WINID})
        DIRECTBUFFERSTATE = "gpu"
        DIRECTBUFFERERROR = ""
        DIRECTBUFFERWIDTH = int(ENGINEW)
        DIRECTBUFFERHEIGHT = int(ENGINEH)
        closexwd()
        logline("Chromium T1OS GPU presentation authorized")
    elif operation == "ERROR":
        errorcode = str(message.get("code", ""))
        if errorcode == "fullscreen_denied":
            FULLSCREENREQUEST = None
            setbrowsercursor(True, force=True)
        if errorcode.startswith("external_buffer_"):
            DIRECTBUFFERSTATE = "unavailable"
            DIRECTBUFFERERROR = str(message.get("detail", errorcode))
            DIRECTBUFFERWIDTH = 0
            DIRECTBUFFERHEIGHT = 0
            logline(f"direct Chromium presentation unavailable: {DIRECTBUFFERERROR}")
    elif operation == "POINTER_MOTION":
        fullscreenpointeractivity()
        LASTMOTION = (
            int(message.get("x", 0)),
            int(message.get("y", 0)),
        )
    elif operation == "POINTER_BUTTON":
        fullscreenpointeractivity()
        if str(message.get("state", "down")) == "down":
            cancelsmoothscroll()
        enginecommand({
            "op": "button", "button": int(message.get("button", 1)),
            "state": str(message.get("state", "down")),
        })
    elif operation == "SCROLL":
        dx = int(message.get("dx", 0))
        dy = int(message.get("dy", 0))
        queuesmoothscroll(
            0 if dx == 0 else (1 if dx > 0 else -1),
            0 if dy == 0 else (1 if dy > 0 else -1),
        )
    elif operation == "KEY":
        keyinput(message)
    elif operation == "TEXT":
        textinput(message)
    elif operation == "CLIPBOARD_DATA":
        pasteclipboard(message)
    elif operation == "FOCUS":
        focusstate = str(message.get("state", "in")).strip().lower()
        focused = bool(message.get("focused", focusstate in ("in", "focused", "focus", "1", "true")))
        if focused:
            enginecommand({"op": "focus"})
    elif operation in ("CLOSE", "WINDOW_DESTROYED"):
        logline(
            f"window lifecycle operation={operation} "
            f"winid={message.get('winid', WINID)} pid={os.getpid()}"
        )
        RUNNING = False
        if operation == "CLOSE":
            sendws({"op": "CLOSE_ACK", "pid": os.getpid()})


def reapengine():
    global ENGINEPID, ENGINESTATE, NEEDREDRAW, PLACEHOLDER
    if ENGINEPID is None:
        return
    try:
        process, status = os.waitpid(ENGINEPID, os.WNOHANG)
    except ChildProcessError:
        process, status = ENGINEPID, 0
    if process == ENGINEPID:
        ENGINEPID = None
        if ENGINESTATE not in ("error", "stopped"):
            ENGINESTATE = "stopped"
            PLACEHOLDER = f"chromium engine stopped ({status})"
            NEEDREDRAW = True


def pulsewaittimeout(now, interval):
    timeout = 0.05

    if LASTMOTION is not None:
        timeout = 0.0

    if PENDINGSCROLLX or PENDINGSCROLLY:
        remaining = (
            0.0
            if not LASTSCROLLFRAME
            else SCROLLFRAMEINTERVAL - (now - LASTSCROLLFRAME)
        )
        timeout = min(timeout, max(0.0, remaining))

    if not ENGINEDAMAGESUPPORTED or ENGINEDAMAGE:
        timeout = min(timeout, max(0.0, interval - (now - LASTFRAME)))

    if (
        FULLSCREEN
        and FULLSCREENCURSORVISIBLE
        and FULLSCREENCURSORHIDEAT > 0.0
    ):
        timeout = min(timeout, max(0.0, FULLSCREENCURSORHIDEAT - now))

    if NEEDREDRAW and ENGINESTATE != "ready":
        timeout = 0.0

    return timeout


def pulse():
    global LASTMOTION, LASTMOTIONSENT, NEEDREDRAW
    serviceinstanceactivations()
    now = time.monotonic()
    interval = 1.0 / max(15, int(CONFIG.get("frames_per_second", 60)))
    readers = [
        stream
        for stream in (WSOCK, ENGINECHANNEL, INSTANCEHOST)
        if stream is not None
    ]
    writers = []
    if WSOCK is not None and WSOUTPUT is not None and WSOUTPUT.pending():
        writers.append(WSOCK)
    if (
        ENGINECHANNEL is not None
        and ENGINEOUTPUT is not None
        and ENGINEOUTPUT.pending()
    ):
        writers.append(ENGINECHANNEL)
    try:
        readable, writable, _ = select.select(
            readers,
            writers,
            [],
            pulsewaittimeout(now, interval),
        )
    except Exception:
        readable = []
        writable = []
    # A non-blocking transport that has already reported EAGAIN must only be
    # retried after the selector reports write readiness.  Retrying both
    # queues unconditionally on every XDamage/read pulse made a blocked
    # Chromium control channel perform millions of failed send attempts and
    # consume a CPU core during otherwise GPU-driven video playback.
    if WSOCK is not None and WSOCK in writable:
        flushwsoutput()
    if ENGINECHANNEL is not None and ENGINECHANNEL in writable:
        flushengineoutput()
    if WSOCK is not None and WSOCK in readable:
        for message in recvws():
            handlewindow(message)
    if INSTANCEHOST is not None and INSTANCEHOST in readable:
        serviceinstanceactivations()
    receiveengine()
    reapengine()
    flushsmoothscroll()
    now = time.monotonic()
    if LASTMOTION is not None and now - LASTMOTIONSENT >= POINTERFRAMEINTERVAL:
        enginecommand(logicalmotioncommand(LASTMOTION))
        LASTMOTION = None
        LASTMOTIONSENT = now
    if (
        now - LASTFRAME >= interval
        and (not ENGINEDAMAGESUPPORTED or bool(ENGINEDAMAGE))
    ):
        captureframe()
    pumpfullscreencursor()
    if NEEDREDRAW and ENGINESTATE != "ready":
        placeholder(PLACEHOLDER)
        NEEDREDRAW = False


def stopengine():
    global ENGINEPID, ENGINECHANNEL, ENGINEOUTPUT
    AUDIOSTOP.set()
    if ENGINECHANNEL is not None:
        if ENGINEOUTPUT is not None:
            logline(f"engine transport counters={json.dumps(ENGINEOUTPUT.counters, sort_keys=True)}")
        try:
            ENGINECHANNEL.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        try:
            ENGINECHANNEL.close()
        except Exception:
            pass
        ENGINECHANNEL = None
        ENGINEOUTPUT = None
    if ENGINEPID is not None:
        deadline = time.monotonic() + 4.0
        while time.monotonic() < deadline:
            try:
                process, _ = os.waitpid(ENGINEPID, os.WNOHANG)
                if process == ENGINEPID:
                    ENGINEPID = None
                    break
            except ChildProcessError:
                ENGINEPID = None
                break
            time.sleep(0.05)
    if ENGINEPID is not None:
        try:
            os.kill(ENGINEPID, signal.SIGTERM)
        except Exception:
            pass
        deadline = time.monotonic() + 1.0
        while ENGINEPID is not None and time.monotonic() < deadline:
            try:
                process, _ = os.waitpid(ENGINEPID, os.WNOHANG)
                if process == ENGINEPID:
                    ENGINEPID = None
                    break
            except ChildProcessError:
                ENGINEPID = None
                break
            time.sleep(0.02)
    if ENGINEPID is not None:
        process = ENGINEPID
        try:
            os.kill(process, signal.SIGKILL)
        except Exception:
            pass
        deadline = time.monotonic() + 1.0
        while ENGINEPID is not None and time.monotonic() < deadline:
            try:
                reaped, _ = os.waitpid(process, os.WNOHANG)
                if reaped == process:
                    ENGINEPID = None
                    break
            except ChildProcessError:
                ENGINEPID = None
                break
            time.sleep(0.02)
        if ENGINEPID is not None:
            logline(f"Chromium engine did not reap after SIGKILL pid={process}")
            ENGINEPID = None


def cleanup():
    global WSOUTPUT
    if WINID is not None:
        detachdirectbuffer()
        setbrowsercursor(True, force=True)
    if WSOCK is not None:
        predrained = drainjsonoutput(WSOUTPUT, WSOCK, timeout=0.5)
        if not predrained:
            logline(
                "window transport remained backpressured before engine teardown"
            )
    stopengine()
    closexwd()
    if WSOCK is not None:
        drained = drainjsonoutput(WSOUTPUT, WSOCK, timeout=0.5)
        if WSOUTPUT is not None:
            logline(
                f"window transport drained={drained} "
                f"pending={WSOUTPUT.pending()} "
                f"counters={json.dumps(WSOUTPUT.counters, sort_keys=True)}"
            )
        try:
            WSOCK.close()
        except Exception:
            pass
    WSOUTPUT = None
    closegraphicsbuffer()
    if ENGINELOG is not None:
        try:
            ENGINELOG.close()
        except Exception:
            pass
    closeengineoutputreader()
    try:
        removeruntime()
    except Exception as error:
        logline(f"runtime cleanup failed: {error}")
    releaseinstance()


def transportselftest():
    class PartialSocket:
        def __init__(self, short=1, blocked=(2, 5)):
            self.calls = 0
            self.received = bytearray()
            self.short = max(1, int(short))
            self.blocked = set(blocked)

        def send(self, data):
            self.calls += 1
            if self.calls in self.blocked:
                raise BlockingIOError(errno.EAGAIN, "diagnostic backpressure")
            amount = min(len(data), self.short)
            self.received.extend(data[:amount])
            return amount

    motionqueue = JsonLineQueue(limit=16384, motion=True)
    motionqueue.queue({"op": "motion", "x": 1, "y": 2})
    motionqueue.queue({"op": "motion", "x": 30, "y": 40})
    motionqueue.queue({"op": "button", "button": 1, "state": "down"})
    motionqueue.queue({"op": "key", "key": "A", "state": "down"})
    motiontarget = PartialSocket()
    maximumflush = 0
    for _ in range(512):
        before = len(motiontarget.received)
        motionqueue.flush(motiontarget, budget=11)
        maximumflush = max(maximumflush, len(motiontarget.received) - before)
        if not motionqueue.pending():
            break

    damagequeue = JsonLineQueue(limit=16384, damage=True)
    damagequeue.queue({"op": "damage", "rect": [10, 10, 20, 20]})
    damagequeue.queue({"op": "damage", "rect": [25, 5, 20, 15]})
    damagequeue.queue({"op": "key", "key": "B", "state": "down"})
    damagetarget = PartialSocket(short=4096, blocked=())
    damagequeue.flush(damagetarget)

    resizequeue = JsonLineQueue(limit=16384, motion=True)
    resizequeue.queue(logicalmotioncommand(
        (1919, 1079), 3840, 2160, 2560, 1440,
    ))
    resizequeue.queue({"op": "button", "button": 1, "state": "down"})
    resizetarget = PartialSocket(short=4096, blocked=())
    resizequeue.flush(resizetarget)

    # Reject an ordered group atomically when a nearly-full queue cannot fit
    # both its pending motion and the transition that follows it.
    atomicqueue = JsonLineQueue(limit=4096, motion=True)
    atomicqueue.queue({"op": "bulk", "value": "x" * 4030})
    atomicqueue.queue({"op": "motion", "x": 8, "y": 9})
    atomicbytes = atomicqueue._queuedbytes()
    atomicmotion = dict(atomicqueue.pendingmotion)
    atomicrejected = False
    try:
        atomicqueue.queue({"op": "button", "button": 1, "state": "up"})
    except BufferError:
        atomicrejected = True

    exclusivity = False
    try:
        JsonLineQueue(motion=True, damage=True)
    except ValueError:
        exclusivity = True

    shutdownqueue = JsonLineQueue()
    shutdownqueue.queue({"op": "CLOSE_ACK", "pid": 123})
    shutdownsent = False
    shutdownleft = None
    shutdownright = None
    try:
        shutdownleft, shutdownright = socket.socketpair()
        shutdownleft.setblocking(False)
        shutdownright.setblocking(False)
        shutdownsent = drainjsonoutput(
            shutdownqueue, shutdownleft, timeout=0.25
        )
        shutdownrecord = json.loads(
            shutdownright.recv(4096).strip().decode("utf-8")
        )
        shutdownsent = (
            shutdownsent
            and not shutdownqueue.pending()
            and shutdownrecord.get("op") == "CLOSE_ACK"
        )
    except Exception:
        shutdownsent = False
    finally:
        for endpoint in (shutdownleft, shutdownright):
            if endpoint is not None:
                endpoint.close()

    try:
        motionrecords = [
            json.loads(line.decode("utf-8"))
            for line in bytes(motiontarget.received).splitlines()
        ]
        damagerecords = [
            json.loads(line.decode("utf-8"))
            for line in bytes(damagetarget.received).splitlines()
        ]
        resizerecords = [
            json.loads(line.decode("utf-8"))
            for line in bytes(resizetarget.received).splitlines()
        ]
    except Exception:
        return False
    return (
        not motionqueue.pending()
        and not damagequeue.pending()
        and [record.get("op") for record in motionrecords]
        == ["motion", "button", "key"]
        and motionrecords[0].get("x") == 30
        and motionrecords[0].get("y") == 40
        and [record.get("op") for record in damagerecords]
        == ["damage", "key"]
        and damagerecords[0].get("rect") == [10, 5, 35, 25]
        and [record.get("op") for record in resizerecords]
        == ["motion", "button"]
        and resizerecords[0].get("x") == 1279
        and resizerecords[0].get("y") == 719
        and motionqueue.counters["motion_coalesced"] == 1
        and damagequeue.counters["damage_coalesced"] == 1
        and motionqueue.counters["blocked_writes"] == 2
        and motionqueue.counters["short_writes"] > 0
        and maximumflush <= 11
        and atomicrejected
        and atomicqueue._queuedbytes() == atomicbytes
        and atomicqueue.pendingmotion == atomicmotion
        and exclusivity
        and shutdownsent
    )


def diagnostic():
    checks = {}
    settings = validatesettings({"frames_per_second": 500, "maximum_width": 1, "home_page": ""})
    checks["settings"] = (
        settings["format"] == 2
        and settings["frames_per_second"] == 60
        and settings["maximum_width"] == BASEWIDTH
    )
    checks["display_scale"] = (
        abs(chromedevicescale(1920, 1080, 1.0) - 0.90) < 0.0001
        and abs(chromedevicescale(3840, 2160, 1.0) - 1.80) < 0.0001
        and initialwindowsize(1920, 1080, 1.0) == (1280, 900)
        and initialwindowsize(3840, 2160, 1.0) == (2560, 1800)
    )
    cursorenvironment = engineenvironment()
    cursorsemantics = xcursorsemantics()
    checks["cursor_policy"] = (
        cursorenvironment.get("XCURSOR_PATH") == RESOURCES + "/icons"
        and cursorenvironment.get("XCURSOR_THEME") == "Adwaita"
        and set(cursorsemantics.values()) >= {"arrow", "link", "text", "busy"}
        and all(
            xcursorfilehashes(
                os.path.join(RESOURCES, "icons", "Adwaita", "cursors", name)
            )
            for name in ("left_ptr", "pointer", "text", "wait")
        )
    )
    checks["bounded_backing_surface"] = (
        chromiumbackingsurface() == (3840, 2160)
        and abs(chromiumbackingratio(3840, 2160) - 1.0) < 0.0001
        and chromiumbackingsize(
            1920, 1080, 1920, 1080,
        ) == (1920, 1080)
        and chromiumbackingsize(
            2560, 1800, 3840, 2160,
        ) == (2560, 1800)
        and chromiumbackingsize(
            3840, 2160, 3840, 2160,
        ) == (3840, 2160)
        and chromiumbackingsize(
            3440, 1440, 3440, 1440,
        ) == (3440, 1440)
        and abs(
            chromiumbackingdevicescale(3840, 2160, 0.8) - 1.44
        ) < 0.0001
        and abs(
            chromiumbackingdevicescale(3840, 2160, 1.0)
            - chromedevicescale(3840, 2160, 1.0)
        ) < 0.0001
        and abs(
            chromiumbackingdevicescale(3840, 2160, 1.0)
            - chromedevicescale(3840, 2160, 1.0)
        ) < 0.0001
        and chromiumcommandwindowsize(3840, 2083, 1.44)
        == (2666, 1446)
        and chromiumcommandwindowsize(1920, 1080, 0.9)
        == (2133, 1200)
        and chromiumcommandwindowsize(800, 600, "invalid")
        == (800, 600)
        and outputtosourcepoint(
            3839, 2159, 3840, 2160, 3840, 2160,
        ) == (3839, 2159)
        and logicalmotioncommand(
            (3439, 1439), 3440, 1440, 3440, 1440,
        ) == {"op": "motion", "x": 3439, "y": 1439}
        and sourcerecttooutput(
            [1920, 1080, 1920, 1080],
            3840,
            2160,
            3840,
            2160,
        ) == [1920, 1080, 1920, 1080]
    )
    checks["media_window_policy"] = (
        FULLSCREENCURSORDELAY == 2.0
        and XWDFILE == "/.ephemeral/chromium/framebuffer/Xvfb_screen0"
        and vaapiconfiguration("simpledrm") is None
    )
    checks["audio_relay_policy"] = (
        AUDIOCHUNKBYTES == 1920
        and AUDIOSTREAMBUFFERSECONDS == 0.04
        and AUDIOSTREAMPREBUFFERMS == 20
        and AUDIORELAYLOGINTERVAL >= 30.0
        and AUDIOCLOCKMAGIC == 0x43413154
        and AUDIOCLOCKVERSION == 1
        and AUDIOCLOCKFORMAT.size == 72
        and AUDIOCLOCKSEQUENCEOFFSET == 8
        and abs(audiolatencymilliseconds(AUDIOCHUNKBYTES, 48000) - 10.0)
        < 0.0001
    )
    sample = list(range(25))
    sample[0], sample[1], sample[3], sample[4], sample[5] = 100, 7, 24, 10, 8
    sample[7], sample[11], sample[12] = 0, 32, 40
    sample[14], sample[15], sample[16], sample[19] = 0xFF0000, 0x00FF00, 0x0000FF, 0
    metadata = parsexwd(struct.pack(">25I", *sample))
    checks["xwd"] = metadata["offset"] == 100 and metadata["stride"] == 40 and metadata["width"] == 10
    checks["keymap"] = (
        KEYNAMES.get("BACKSPACE") == "BackSpace"
        and KEYNAMES.get("LEFT") == "Left"
        and KEYNAMES.get("PLAYPAUSE") == "XF86AudioPlay"
    )
    scrollclicks = []
    keysequences = []

    class DiagnosticInputBridge:

        def click(self, button):
            scrollclicks.append(int(button))

        def key(self, sequence):
            keysequences.append(str(sequence))

    processenginecommand(
        {"op": "scroll", "dx": 0, "dy": 1},
        {},
        DiagnosticInputBridge(),
    )
    processenginecommand(
        {"op": "scroll", "dx": 0, "dy": -1},
        {},
        DiagnosticInputBridge(),
    )
    processenginecommand(
        {"op": "key", "key": "PLAYPAUSE", "state": "down", "mods": {}},
        {},
        DiagnosticInputBridge(),
    )
    checks["scroll_direction"] = scrollclicks == [4, 5]
    checks["media_key"] = keysequences == ["XF86AudioPlay"]
    checks["nonblocking_transport"] = transportselftest()
    sample_google_credentials = validategoogleapicredentials({
        "format": 1,
        "google_api_key": "A" * 32,
        "google_default_client_id": "B" * 32,
        "google_default_client_secret": "C" * 32,
    })
    google_pair_rejected = False
    try:
        validategoogleapicredentials({
            "format": 1,
            "google_api_key": "A" * 32,
            "google_default_client_id": "B" * 32,
        })
    except ValueError:
        google_pair_rejected = True
    google_placeholder_rejected = False
    try:
        validategoogleapicredentials({
            "format": 1,
            "google_api_key": "replace-with-a-restricted-google-api-key",
        })
    except ValueError:
        google_placeholder_rejected = True
    checks["google_api_credentials"] = (
        GOOGLEAPICREDENTIALFILE
        == "/the one/build/chromium/google api credentials.json"
        and GOOGLEAPIKEYSUPPRESSIONVALUE == "no"
        and applygoogleapicredentials(
            {"UNCHANGED": "1"}, None,
        ).get("GOOGLE_API_KEY") == GOOGLEAPIKEYSUPPRESSIONVALUE
        and set(sample_google_credentials)
        == {"format", *GOOGLEAPICREDENTIALENVIRONMENT}
        and applygoogleapicredentials(
            {"UNCHANGED": "1"}, sample_google_credentials,
        ).get("GOOGLE_API_KEY") == "A" * 32
        and google_pair_rejected
        and google_placeholder_rejected
    )
    checks["paths"] = (
        SETTINGROOT == "/the one/settings/chromium" and
        CACHE == "/.ephemeral/chromium/cache" and
        FONTCACHE == "/the one/settings/chromium/font-cache" and
        "/flash/chromium" not in " ".join(globals().values() if False else ()) and
        CHROMEEXECUTABLE == "/the one/software/chromium/program/chrome" and
        SUBPROCESSEXECUTABLE
        == "/the one/software/chromium/tools/t1os-chrome-subprocess" and
        SANDBOXEXECUTABLE == "./chrome-sandbox" and
        DNSFILE == "/the one/settings/network/dns.txt" and
        MEDIADECODESTATE
        == "/.ephemeral/media/decode-service.json" and
        MEDIADECODESOCKET == "/.ephemeral/media/decode.sock"
    )
    checks["subprocess_base_loader_contract"] = (
        engineenvironment().get("LD_LIBRARY_PATH")
        == BASEGRAPHICSLIBRARYPATH
    )
    nvidia_graphics_environment = chromiumgraphicsenvironment(
        engineenvironment(),
        "nvidia_drm",
    )
    checks["nvidia_graphics_loader_contract"] = (
        nvidia_graphics_environment.get("LD_LIBRARY_PATH")
        == BASEGRAPHICSLIBRARYPATH
        and nvidia_graphics_environment.get(
            NVIDIAGPULIBRARYPATHVARIABLE
        ) == NVIDIAGRAPHICSLIBRARYPATH
        and nvidia_graphics_environment.get(
            NVIDIAGPUEGLVENDORVARIABLE
        ) == NVIDIAEGLVENDORFILE
        and nvidia_graphics_environment.get(
            NVIDIAGPUEGLEXTERNALVARIABLE
        ) == NVIDIAGBMPATH
        and nvidia_graphics_environment.get(
            NVIDIAGPUGBMBACKENDSPATHVARIABLE
        )
        == NVIDIAGBMPATH
        and nvidia_graphics_environment.get(
            NVIDIAGPUGBMBACKENDVARIABLE
        ) == "nvidia-drm"
        and "__EGL_VENDOR_LIBRARY_FILENAMES"
        not in nvidia_graphics_environment
        and "GBM_BACKENDS_PATH" not in nvidia_graphics_environment
        and "LIBGL_DRIVERS_PATH" not in nvidia_graphics_environment
    )
    cache_arguments = cachearguments()
    checks["cache_policy"] = (
        DISKCACHEBYTES == 256 * 1024 * 1024 and
        MEDIACACHEBYTES == 128 * 1024 * 1024 and
        "--disk-cache-dir=/.ephemeral/chromium/cache" in cache_arguments and
        "--disk-cache-size=268435456" in cache_arguments and
        "--media-cache-size=134217728" in cache_arguments
    )
    renderer_mode, renderer_arguments = rendererconfiguration("nouveau")
    checks["gpu_safe"] = (
        renderer_mode == "angle-swiftshader" and
        "--use-angle=swiftshader" in renderer_arguments and
        "--enable-unsafe-swiftshader" in renderer_arguments and
        not any("use-angle=vulkan" in argument for argument in renderer_arguments) and
        not any(argument.startswith("--enable-features=Vulkan") for argument in renderer_arguments)
    )
    nvidia_acceleration = {"hardware_required": True}
    nvidia_gpu_arguments = browsergpuarguments(
        "nvidia",
        nvidia_acceleration,
    )
    checks["nvidia_webgl_policy"] = (
        "--ignore-gpu-blocklist" in nvidia_gpu_arguments
        and "--disable-gpu-driver-bug-workarounds"
        not in nvidia_gpu_arguments
    )
    mesa_presentation_arguments = browsergpuarguments(
        "vmwgfx",
        None,
        presentationbridge=True,
    )
    checks["mesa_presentation_policy"] = (
        "--ignore-gpu-blocklist" in mesa_presentation_arguments
        and "--use-gl=egl" in mesa_presentation_arguments
        and not any(
            "swiftshader" in argument
            for argument in mesa_presentation_arguments
        )
        and chromiumgraphicsenvironment(
            engineenvironment(),
            "vmwgfx",
            presentationbridge=True,
        ).get("LD_LIBRARY_PATH") == BASEGRAPHICSLIBRARYPATH
        and not chromiumgraphicsenvironment(
            engineenvironment(),
            "vmwgfx",
            presentationbridge=True,
        ).get("GBM_BACKENDS_PATH")
        and "--no-unsandboxed-zygote" not in mesa_presentation_arguments
    )
    checks["nvidia_vaapi_policy"] = (
        NVIDIADIRECTVAAPIQUARANTINED
        and "--no-unsandboxed-zygote" not in nvidia_gpu_arguments
        and "--use-gl=egl" in nvidia_gpu_arguments
        and "--use-cmd-decoder=validating" in nvidia_gpu_arguments
        and not any(
            argument.startswith("--use-angle=")
            for argument in nvidia_gpu_arguments
        )
        and "--disable-accelerated-video-decode" in nvidia_gpu_arguments
        and (
            "--disable-features=AcceleratedVideoDecodeLinuxGL,"
            "VaapiOnNvidiaGPUs"
        ) in nvidia_gpu_arguments
        and not any(
            "FallbackAfterDecodeError" in argument
            or "Dav1dVideoDecoder" in argument
            for argument in nvidia_gpu_arguments
        )
        and nvidia_acceleration["hardware_required"]
        and vaapiconfiguration("nvidia") is None
    )
    service_configuration = {
        "feature": MEDIADECODEFEATURE,
        "socket": MEDIADECODESOCKET,
        "protocol": MEDIADECODEPROTOCOL,
        "protocol_version": MEDIADECODEPROTOCOLVERSION,
        "service_pid": 123,
        "brokered_socket": True,
        "output_mode": MEDIADECODEOUTPUTDMABUF,
    }
    nvidia_service_arguments = browsergpuarguments(
        "nvidia",
        None,
        servicedecoder=service_configuration,
    )
    nvidia_linear_service_arguments = browsergpuarguments(
        "nvidia",
        None,
        servicedecoder=service_configuration,
        presentationbridge=False,
    )
    service_arguments = t1osmediadecoderarguments(
        service_configuration
    )
    isolated_environment = servicechromiumenvironment(
        chromiumgraphicsenvironment({
            "LD_LIBRARY_PATH": BASEGRAPHICSLIBRARYPATH,
            "LIBVA_DRIVER_NAME": "nvidia",
            "NVD_BACKEND": "direct",
            "CUDA_DISABLE_PERF_BOOST": "1",
            "T1OS_CHROMIUM_NVIDIA_DEBUG": "1",
            "DISPLAY": DISPLAY,
            "LIBGL_DRIVERS_PATH": LIBRARIES,
        }, "nvidia_drm")
    )
    checks["t1os_media_service_policy"] = (
        NVIDIADIRECTVAAPIQUARANTINED
        and "--disable-accelerated-video-decode"
        not in nvidia_service_arguments
        and "--disable-accelerated-video-decode"
        not in nvidia_linear_service_arguments
        and "--use-gl=egl" not in nvidia_linear_service_arguments
        and (
            "--disable-features=AcceleratedVideoDecodeLinuxGL,"
            "VaapiOnNvidiaGPUs"
        ) in nvidia_service_arguments
        and service_arguments == [
            "--enable-features=T1OSVideoDecoder",
            "--t1os-video-decode-socket=/.ephemeral/media/decode.sock",
            "--t1os-video-decode-output=dma-buf",
        ]
        and isolated_environment == {
            "LD_LIBRARY_PATH": BASEGRAPHICSLIBRARYPATH,
            NVIDIAGPULIBRARYPATHVARIABLE: NVIDIAGRAPHICSLIBRARYPATH,
            "DISPLAY": DISPLAY,
            NVIDIAGPUEGLVENDORVARIABLE: NVIDIAEGLVENDORFILE,
            NVIDIAGPUEGLEXTERNALVARIABLE: NVIDIAGBMPATH,
            NVIDIAGPUGBMBACKENDSPATHVARIABLE: NVIDIAGBMPATH,
            NVIDIAGPUGBMBACKENDVARIABLE: "nvidia-drm",
        }
        and MEDIADECODECHROMIUMREVISION
        == "24b04c927b23c39cf9c5227cc8dc6f64a744c8e9"
        and MEDIADECODESOURCEOVERLAYSHA256
        == "102cea1fe8eb1358493eb2889579ece701ead0edf917d5edcc276a2d23fc0705"
        and MEDIADECODEBUILDMARKER.endswith(
            "source_sha256=" + MEDIADECODESOURCEOVERLAYSHA256
        )
        and t1osmediadecoderoutputmode(True) == MEDIADECODEOUTPUTDMABUF
        and t1osmediadecoderoutputmode(False) == MEDIADECODEOUTPUTLINEAR
        and mergechromiumfeaturearguments([
            "--enable-features=T1OSVideoDecoder",
            "--enable-features=T1OSNvidiaPresentation",
            "--disable-features=VaapiOnNvidiaGPUs",
            "--disable-features=Vulkan,VaapiOnNvidiaGPUs",
        ]) == [
            "--enable-features=T1OSVideoDecoder,T1OSNvidiaPresentation",
            "--disable-features=VaapiOnNvidiaGPUs,Vulkan",
        ]
    )
    checks["launch_scoped_gpu_runtime"] = (
        not gpucandidateruntimeready(True, False, False, True)
        and not gpucandidateruntimeready(False, True, True, True)
        and not gpucandidateruntimeready(True, True, True, False)
        and not gpucandidateruntimeready(True, True, True, True, False)
        and gpucandidateruntimeready(True, True, True, True)
        and CHROMEGPURUNTIMETIMEOUT >= 15.0
        and CHROMEPROBETIMEOUT >= 15.0
    )
    checks["mapped_gpu_graphics_runtime"] = (
        gpugraphicsmappingsready({
            "egl_vendor": True,
            "egl_core": True,
            "egl_gbm": True,
            "gbm_backend": False,
        })
        and not gpugraphicsmappingsready({
            "egl_vendor": True,
            "egl_core": True,
            "egl_gbm": False,
            "gbm_backend": True,
        })
        and gpugraphicsmappingsready({
            "egl": True,
            "gbm": True,
            "gallium": True,
            "gbm_backend": True,
        }, mesa_gpu_contract=True)
        and not gpugraphicsmappingsready({
            "egl": True,
            "gbm": True,
            "gallium": True,
            "gbm_backend": False,
        }, mesa_gpu_contract=True)
    )
    try:
        requirevideoacceleration(
            "nvidia_drm",
            None,
            rendernode="/the one/drivers/nodes/dri/renderD129",
        )
        checks["nvidia_decode_fail_closed"] = False
    except RuntimeError:
        checks["nvidia_decode_fail_closed"] = (
            requirevideoacceleration(
                "nvidia-drm",
                nvidia_acceleration,
                rendernode="/the one/drivers/nodes/dri/renderD129",
            ) is nvidia_acceleration
        )
    checks["client_chrome"] = APPNAME == "chromium"
    checks["singleton_lock"] = (
        singletonpid("TERMINAL-1234") == 1234 and
        singletonpid("TERMINAL-invalid") is None and
        SINGLETONNAMES == ("SingletonLock", "SingletonSocket", "SingletonCookie")
    )
    if os.path.isdir(ENGINE):
        try:
            runtimefiles()
            checks["engine"] = True
        except Exception:
            checks["engine"] = False
    result = {"ok": all(checks.values()), "checks": checks, "installed_python_files": [APPPATH]}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["ok"] else 1


def instancediagnostic():
    result = {"ok": False, "owner": False, "second_launch_activated": False, "error": ""}
    process = None
    try:
        result["owner"] = claiminstance()
        if not result["owner"]:
            raise RuntimeError("could not acquire the Chromium instance lock")
        process = os.fork()
        if process == 0:
            dropinheritedinstance()
            try:
                becameowner = claiminstance()
                if becameowner:
                    releaseinstance()
                    os._exit(2)
                os._exit(0)
            except Exception:
                os._exit(3)

        deadline = time.monotonic() + 8.0
        status = None
        while time.monotonic() < deadline:
            serviceinstanceactivations()
            child, childstatus = os.waitpid(process, os.WNOHANG)
            if child == process:
                status = childstatus
                process = None
                break
            time.sleep(0.01)
        if status is None:
            raise TimeoutError("second Chromium launch did not complete")
        exitstatus = os.waitstatus_to_exitcode(status)
        result["second_launch_activated"] = exitstatus == 0
        if not result["second_launch_activated"]:
            raise RuntimeError(f"second Chromium launch exited with status {exitstatus}")
        result["ok"] = True
    except Exception as error:
        result["error"] = str(error)
    finally:
        if process is not None:
            try:
                os.kill(process, signal.SIGTERM)
                os.waitpid(process, 0)
            except Exception:
                pass
        releaseinstance()
    print(json.dumps(result, sort_keys=True))
    return 0 if result["ok"] else 1


def audiodiagnostic():
    global ENGINELOG
    result = {
        "ok": False,
        "device_path_converted": False,
        "pcm_open": False,
        "pcm_frames": 0,
        "fifo_bytes": 0,
        "error": "",
    }
    descriptor = None
    handle = ctypes.c_void_p()
    alsa = None
    try:
        runtimefiles()
        prepareruntime()
        startengineoutputworker()
        library = LIBRARIES + "/libasound.so.2"
        with open(library, "rb") as stream:
            data = stream.read()
        conventional_null = bytes((47, 100, 101, 118, 47, 110, 117, 108, 108, 0))
        result["device_path_converted"] = (
            conventional_null not in data and
            b"/the one/drivers/nodes/null\0" in data
        )
        if not result["device_path_converted"]:
            raise RuntimeError("ALSA null PCM still contains a conventional device path")

        descriptor = os.open(AUDIO + "/output.pcm", os.O_RDONLY | os.O_NONBLOCK)
        environment_value = os.environ.get("ALSA_CONFIG_PATH")
        os.environ["ALSA_CONFIG_PATH"] = AUDIO + "/asound.conf"
        try:
            # Chromium links libasound into its global process namespace.
            # Match that loader visibility so built-in plug/file/null PCM
            # constructors resolve exactly as they do in the browser.
            alsa = ctypes.CDLL(library, mode=ctypes.RTLD_GLOBAL)
            alsa.snd_pcm_open.argtypes = [
                ctypes.POINTER(ctypes.c_void_p), ctypes.c_char_p,
                ctypes.c_int, ctypes.c_int,
            ]
            alsa.snd_pcm_open.restype = ctypes.c_int
            alsa.snd_pcm_set_params.argtypes = [
                ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                ctypes.c_uint, ctypes.c_uint, ctypes.c_int,
                ctypes.c_uint,
            ]
            alsa.snd_pcm_set_params.restype = ctypes.c_int
            alsa.snd_pcm_writei.argtypes = [
                ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong,
            ]
            alsa.snd_pcm_writei.restype = ctypes.c_long
            alsa.snd_pcm_drain.argtypes = [ctypes.c_void_p]
            alsa.snd_pcm_drain.restype = ctypes.c_int
            alsa.snd_pcm_close.argtypes = [ctypes.c_void_p]
            alsa.snd_pcm_close.restype = ctypes.c_int
            alsa.snd_strerror.argtypes = [ctypes.c_int]
            alsa.snd_strerror.restype = ctypes.c_char_p

            status = alsa.snd_pcm_open(
                ctypes.byref(handle), b"default", 0, 1
            )
            if status < 0:
                detail = alsa.snd_strerror(status).decode("utf-8", "replace")
                raise RuntimeError(f"could not open T1OS Chromium PCM: {detail}")
            result["pcm_open"] = True

            # SND_PCM_FORMAT_S16_LE=2 and
            # SND_PCM_ACCESS_RW_INTERLEAVED=3 in the stable ALSA ABI.
            status = alsa.snd_pcm_set_params(
                handle, 2, 3, 2, AUDIORATE, 1, 100000
            )
            if status < 0:
                detail = alsa.snd_strerror(status).decode("utf-8", "replace")
                raise RuntimeError(f"could not configure T1OS Chromium PCM: {detail}")

            silence = (ctypes.c_ubyte * 1920)()
            frames = int(alsa.snd_pcm_writei(handle, silence, 480))
            if frames < 0:
                detail = alsa.snd_strerror(frames).decode("utf-8", "replace")
                raise RuntimeError(f"could not write T1OS Chromium PCM: {detail}")
            result["pcm_frames"] = frames
            status = alsa.snd_pcm_drain(handle)
            if status < 0:
                detail = alsa.snd_strerror(status).decode("utf-8", "replace")
                raise RuntimeError(f"could not drain T1OS Chromium PCM: {detail}")
            alsa.snd_pcm_close(handle)
            handle.value = None
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline and result["fifo_bytes"] == 0:
                try:
                    result["fifo_bytes"] = len(os.read(descriptor, 65536))
                except BlockingIOError:
                    time.sleep(0.01)
        finally:
            if environment_value is None:
                os.environ.pop("ALSA_CONFIG_PATH", None)
            else:
                os.environ["ALSA_CONFIG_PATH"] = environment_value

        result["ok"] = (
            result["device_path_converted"] and
            result["pcm_open"] and
            result["pcm_frames"] == 480 and
            result["fifo_bytes"] == 1920
        )
        if not result["ok"]:
            raise RuntimeError("T1OS Chromium PCM did not complete its FIFO round trip")
    except Exception as error:
        result["error"] = str(error)
    finally:
        if handle.value and alsa is not None:
            try:
                alsa.snd_pcm_close(handle)
            except Exception:
                pass
        if descriptor is not None:
            try:
                os.close(descriptor)
            except Exception:
                pass
        if ENGINELOG is not None:
            try:
                ENGINELOG.close()
            except Exception:
                pass
            ENGINELOG = None
        closeengineoutputreader()
        try:
            removeruntime()
        except Exception:
            pass
    print(json.dumps(result, sort_keys=True))
    return 0 if result["ok"] else 1


def enginediagnostic():
    global CONFIG
    result = {
        "ok": False,
        "ready": False,
        "input_roundtrip": False,
        "zygote_provider": False,
        "zygote_library_path": False,
        "zygote_verified": False,
        "zygote_found": False,
        "sandbox_found": False,
        "sandbox_environment": False,
        "gpu_found": False,
        "gpu_provider": False,
        "gpu_environment": False,
        "gpu_graphics_environment": False,
        "gpu_library_path": False,
        "gpu_launch_scope": False,
        "gpu_runtime_ready": False,
        "gpu_runtime_pid": None,
        "gpu_driver_loaded": False,
        "utility_found": False,
        "utility_provider": False,
        "utility_library_path": False,
        "utility_launch_scope": False,
        "utility_runtime_ready": False,
        "utility_runtime_pid": None,
        "sandbox_chain_active": False,
        "zygote_library_environment": [],
        "zygote_candidates": [],
        "zygote_scan_errors": [],
        "expected_library_path": "",
        "expected_gpu_library_path": "",
        "expected_launch_id": "",
        "expected_browser_pid": 0,
        "video_driver": "",
        "stable_seconds": 0.0,
        "error": "",
    }
    parent = None
    process = None
    try:
        CONFIG = defaultsettings()
        CONFIG["home_page"] = "about:blank"
        runtimefiles()
        prepareruntime()
        parent, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            process = os.fork()
        except BaseException:
            parent.close()
            child.close()
            startengineoutputworker()
            raise
        if process == 0:
            parent.close()
            closeengineoutputreader()
            enginesupervisor(child, 800, 600)
        child.close()
        startengineoutputworker()
        parent.setblocking(False)
        deadline = time.monotonic() + CHROMEDIAGNOSTICTIMEOUT
        stable_until = None
        verification_until = None
        incoming = b""
        diagnosticoutput = JsonLineQueue(
            limit=ENGINEQUEUELIMIT,
            motion=True,
        )
        while time.monotonic() < deadline:
            writabletargets = [parent] if diagnosticoutput.pending() else []
            readable, writable, _ = select.select(
                [parent], writabletargets, [], 0.1
            )
            if parent in writable:
                diagnosticoutput.flush(parent)
            if readable:
                data = parent.recv(65536)
                if not data:
                    break
                incoming += data
                while b"\n" in incoming:
                    line, incoming = incoming.split(b"\n", 1)
                    if not line:
                        continue
                    message = json.loads(line.decode("utf-8"))
                    operation = str(message.get("op", ""))
                    if operation == "ready" and not result["ready"]:
                        result["ready"] = True
                        result["expected_library_path"] = str(
                            message.get("library_path", "")
                        )
                        result["expected_gpu_library_path"] = str(
                            message.get("gpu_library_path", "")
                        )
                        result["expected_launch_id"] = str(
                            message.get("launch_id", "")
                        )
                        result["expected_browser_pid"] = int(
                            message.get("browser_pid", 0) or 0
                        )
                        if not result["expected_launch_id"]:
                            result["error"] = (
                                "Chromium engine omitted its launch-scoping "
                                "marker"
                            )
                            stable_until = None
                            break
                        result["video_driver"] = str(
                            message.get("video_driver", "")
                        )
                        commands = [
                            {"op": "motion", "x": 10 + index, "y": 10 + index}
                            for index in range(32)
                        ]
                        commands.append({"op": "input-diagnostic"})
                        for command in commands:
                            diagnosticoutput.queue(command)
                        stable_until = time.monotonic() + 5.0
                        verification_until = (
                            time.monotonic()
                            + CHROMEDIAGNOSTICVERIFYTIMEOUT
                        )
                    elif operation == "input-diagnostic":
                        result["input_roundtrip"] = bool(message.get("ok"))
                    elif operation == "error":
                        result["error"] = str(message.get("message", operation))
                        stable_until = None
                        break
                    elif operation == "stopped":
                        result["error"] = f"stopped status={message.get('status')}"
                        stable_until = None
                        break
            if result["ready"] and not result["zygote_verified"]:
                zygote_status = zygoteproviderstatus(
                    result["expected_library_path"],
                    result["expected_launch_id"],
                    result["expected_browser_pid"],
                    result["expected_gpu_library_path"],
                )
                result["zygote_found"] = zygote_status["found"]
                result["zygote_provider"] = zygote_status["provider"]
                result["zygote_library_path"] = zygote_status["library_path"]
                result["sandbox_chain_active"] = zygote_status["active"]
                result["sandbox_found"] = zygote_status["sandbox_found"]
                result["sandbox_environment"] = (
                    zygote_status["sandbox_environment"]
                )
                result["gpu_found"] = zygote_status["gpu_found"]
                result["gpu_provider"] = zygote_status["gpu_provider"]
                result["gpu_environment"] = (
                    zygote_status["gpu_environment"]
                )
                result["gpu_graphics_environment"] = (
                    zygote_status["gpu_graphics_environment"]
                )
                result["gpu_library_path"] = (
                    zygote_status["gpu_library_path"]
                )
                result["gpu_launch_scope"] = (
                    zygote_status["gpu_launch_scope"]
                )
                result["gpu_runtime_ready"] = (
                    zygote_status["gpu_runtime_ready"]
                )
                result["gpu_runtime_pid"] = (
                    zygote_status["gpu_runtime_pid"]
                )
                result["utility_found"] = zygote_status["utility_found"]
                result["utility_provider"] = (
                    zygote_status["utility_provider"]
                )
                result["utility_library_path"] = (
                    zygote_status["utility_library_path"]
                )
                result["utility_launch_scope"] = (
                    zygote_status["utility_launch_scope"]
                )
                result["utility_runtime_ready"] = (
                    zygote_status["utility_runtime_ready"]
                )
                result["utility_runtime_pid"] = (
                    zygote_status["utility_runtime_pid"]
                )
                # Retain the legacy output field for diagnostic consumers,
                # but bind readiness to the launch-scoped GPU presentation
                # process. Utility children inherit a measured zygote and do
                # not own rendering.
                result["zygote_verified"] = bool(
                    result["gpu_runtime_ready"]
                )
                result["gpu_driver_loaded"] = (
                    zygote_status["gpu_driver_loaded"]
                )
                result["zygote_library_environment"] = list(
                    zygote_status["library_environment"]
                )
                result["zygote_candidates"] = list(
                    zygote_status["candidates"]
                )
                result["zygote_scan_errors"] = list(
                    zygote_status["scan_errors"]
                )
            if (
                stable_until is not None and
                result["gpu_runtime_ready"] and
                result["input_roundtrip"] and
                time.monotonic() >= stable_until
            ):
                result["stable_seconds"] = 5.0
                result["ok"] = True
                break
            if (
                verification_until is not None and
                result["input_roundtrip"] and
                not result["zygote_verified"] and
                time.monotonic() >= verification_until
            ):
                result["error"] = (
                    "Chromium sandbox/zygote/GPU/utility verification "
                    "did not converge"
                )
                break
            if result["error"]:
                break
        if not result["ok"] and not result["error"]:
            result["error"] = "Chromium engine did not remain ready for five seconds"
    except Exception as error:
        result["error"] = str(error)
    finally:
        if parent is not None:
            try:
                parent.close()
            except Exception:
                pass
        if process:
            deadline = time.monotonic() + 8.0
            while time.monotonic() < deadline:
                try:
                    child_pid, _ = os.waitpid(process, os.WNOHANG)
                    if child_pid == process:
                        process = None
                        break
                except ChildProcessError:
                    process = None
                    break
                time.sleep(0.05)
            if process:
                try:
                    os.kill(process, signal.SIGTERM)
                    os.waitpid(process, 0)
                except Exception:
                    pass
        if ENGINELOG is not None:
            try:
                ENGINELOG.close()
            except Exception:
                pass
        closeengineoutputreader()
        try:
            removeruntime()
        except Exception:
            pass
    if not result["ok"]:
        try:
            with open(LOGFILE, "r", encoding="utf-8", errors="replace") as stream:
                result["log_tail"] = stream.read()[-32768:].splitlines()[-80:]
        except Exception as error:
            result["log_tail_error"] = str(error)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["ok"] else 1


def main():
    global CONFIG, RUNNING
    if len(sys.argv) > 1 and sys.argv[1] == "diagnostic":
        return diagnostic()
    if len(sys.argv) > 1 and sys.argv[1] == "instance-diagnostic":
        return instancediagnostic()
    if len(sys.argv) > 1 and sys.argv[1] == "audio-diagnostic":
        return audiodiagnostic()
    if len(sys.argv) > 1 and sys.argv[1] == "engine-diagnostic":
        return enginediagnostic()
    try:
        if not claiminstance():
            return 0
    except Exception as error:
        print(formatlog('chromium', f'could not coordinate instance: {error}'), file=sys.stderr)
        logline(f"instance coordination failed: {error}")
        return 1
    logline(f"=== chromium session started pid={os.getpid()} ===")
    try:
        CONFIG = loadsettings()
        loadgraphics()
        connectwindow()
    except Exception as error:
        print(formatlog('chromium', f'could not start: {error}'), file=sys.stderr)
        logline(f"startup failed: {error}")
        cleanup()
        logline(f"=== chromium session stopped pid={os.getpid()} ===")
        return 1
    try:
        while RUNNING:
            pulse()
    except KeyboardInterrupt:
        RUNNING = False
    except Exception as error:
        logline(f"main loop failed: {error}")
        return 1
    finally:
        cleanup()
        logline(f"=== chromium session stopped pid={os.getpid()} ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
