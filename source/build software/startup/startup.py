#!"/the one/software/python/bin/python" -B

"""
startup.py

startup handles the creation of master and logging in to The One OS.
"""



## imports
import os
import sys
import time
import hmac
import json
import socket
import hashlib
import binascii
import selectors
import subprocess
import signal
import warnings
import stat

sys.path.insert(0, '/the one/build')

from graphics.graphics import *
from reign.reign import timestamp
from GODDESS.GODDESS import formatlog, popenisolated, dropdesktopidentity
from operations.operations import session_auth_verify
from broker import broker as authbroker
_cpuclear = clear
_cpudrawline = drawline
_cpudrawtextttf = drawtextttf



## globals

# misc
DEBUGSTARTUP = False
STARTLOGFD   = None

# paths
MASTERTIER = "/the one/master"
MASTERFILE = os.path.join(MASTERTIER, "master.txt")
MASTERSETTINGSFILE = "/the one/settings/master/settings.json"
HOME_BASE = "/master"
STARTLOGFILE = "/the one/logs/startup.py.log"
BOOTANIMATIONSCRIPT = "/boot/boot animation/boot animation.py"
BOOTANIMATIONBASE = "/.ephemeral/boot animation"
BOOTANIMATIONREQUEST = os.path.join(BOOTANIMATIONBASE, "request.json")
BOOTANIMATIONSTATE = os.path.join(BOOTANIMATIONBASE, "state.json")
LOCKSCREENSCRIPT = "/the one/build/lock screen/lock screen.py"
LOCKSCREENLOG = "/the one/logs/lock screen.py.log"
LOCKSCREENBASE = "/.ephemeral/lock screen"
LOCKSCREENSTATE = os.path.join(LOCKSCREENBASE, "state.json")
LOCKSCREENPOSTHANDOFFSTATE = os.path.join(
    LOCKSCREENBASE, "post-handoff-ready.json"
)
LOCKSCREENREADYPATH = "/.ephemeral/windowserver/state/lockscreen-ready.json"
STARTUPSCRIPT = "/the one/build/startup/startup.py"
WINDOWCREATETIMEOUT = 60.0
IMAGECATALOGUE = "/the one/catalogue/image"
MASTERIMAGECACHEBASE = "/.ephemeral/startup"
MASTERIMAGECACHEPATH = os.path.join(
    MASTERIMAGECACHEBASE, f"master-image-{os.getpid()}.bgra")
LOGINREADYPATH = os.path.join(MASTERIMAGECACHEBASE, "login-ready.json")
SESSIONIDENTITYFILE = "/the one/settings/session/identity.json"
SESSIONIDENTITYMAXBYTES = 1024

# password
AUTH_RATE_FILE = "/.ephemeral/authentication/attempts.json"

# graphics
SCREEN_W = 1920
SCREEN_H = 1080
Y_TEXT = 540
Y_LINE = 660
WELCOME_Y   = 360
NAME_Y      = 540
PWD_Y       = NAME_Y + 120
CONFIRM_Y   = PWD_Y  + 120
SUCCESS_Y   = CONFIRM_Y + 250
BACKGROUNDCOLOUR = 0x000000
BASE_W = 1920
BASE_H = 1080
SCALE = 1.0
OFFX = 0
OFFY = 0
FONTSIZE_BASE = 48
MASTERIMAGE_MAX_W = 154
MASTERIMAGE_MAX_H = 154
MASTERIMAGE_LOGIN_GAP = 48
MASTERIMAGEPIXELLIMIT = 16777216

# window
WINSOCKPATH = "/.ephemeral/windowserver/accept.sock"
WSSEL = selectors.DefaultSelector()
WSSOCK = None
WSRXBUF = ""
WSDEFERREDMSGS = []
WINID = None
WINBUF_PATH = None
WINROLE = "startup"
WINTITLE = "startup"
WINMAPPED = False

# managed graphics
GRAPHICSCAPS = {}
GRAPHICSAVAILABLE = False
GRAPHICSACTIVE = False
GRAPHICSPENDING = False
GRAPHICSFAILURE = ""
GRAPHICSFRAMES = 0
GRAPHICSMAXCOMMANDS = 0
GRAPHICSLASTCOMMANDS = 0
GRAPHICSDISPLAYLIST = []
GRAPHICSBUILDTOTALMS = 0.0
GRAPHICSBUILDMAXIMUMMS = 0.0
GRAPHICSBUILDCOUNT = 0
GRAPHICSDIRTYRECT = None
GRAPHICSCPUOVERRIDE = str(os.environ.get("T1OS_STARTUP_GRAPHICS", "")).strip().lower() in ("cpu", "off", "0", "false")
GRAPHICSSTATE = managedstate(cpu=GRAPHICSCPUOVERRIDE)

# first-run animation pacing
ANIMATIONREFRESHHZ = 60.0
ANIMATIONFRAMETIME = 1.0 / ANIMATIONREFRESHHZ
TITLECHARACTERTIME = 0.12
LABELFADETIME = 0.30
ANIMATIONCOMMITACKS = 0

# text
FONTFILE = '/the one/resources/fonts/atkinsonhyperlegiblenext.ttf'
BRANDFONT = '/the one/resources/fonts/cambria.ttf'
FONTSIZE = 48
TEXTCOLOUR = 0xEFEFEF
ERRORCOLOUR = 0xFF0000
CAPSLOCKNOTICE = "caps lock is on"
CAPSLOCKON = False

# error timing
ERRORMSG = None
ERRORRECT = None
ERROREXPIRES = 0.0
ERRORDURATION = 3.0
PILIMAGE = None
PILIMAGEOPS = None


## functions

# retained drawing functions
def graphicscliprect(x, y, w, h):

    try:

        x = int(x)
        y = int(y)
        w = int(w)
        h = int(h)
        right = min(int(SCREEN_W), x + w)
        bottom = min(int(SCREEN_H), y + h)
        x = max(0, x)
        y = max(0, y)
        w = right - x
        h = bottom - y

        if w < 1 or h < 1:
            return None

        return [x, y, w, h]

    except Exception:

        return None


def graphicscontains(outer, inner):

    try:

        ox, oy, ow, oh = [int(value) for value in outer]
        ix, iy, iw, ih = [int(value) for value in inner]
        return ox <= ix and oy <= iy and ox + ow >= ix + iw and oy + oh >= iy + ih

    except Exception:

        return False


def graphicsintersectrect(first, second):

    try:

        ax, ay, aw, ah = [int(value) for value in first]
        bx, by, bw, bh = [int(value) for value in second]
        left = max(ax, bx)
        top = max(ay, by)
        right = min(ax + aw, bx + bw)
        bottom = min(ay + ah, by + bh)

        if right <= left or bottom <= top:
            return None

        return [left, top, right - left, bottom - top]

    except Exception:

        return None


def graphicsmarkdirty(rect):

    global GRAPHICSDIRTYRECT

    try:

        incoming = graphicscliprect(*rect)

        if incoming is None:
            return False

        if GRAPHICSDIRTYRECT is None:

            GRAPHICSDIRTYRECT = list(incoming)
            return True

        x, y, w, h = [int(value) for value in GRAPHICSDIRTYRECT]
        nx, ny, nw, nh = [int(value) for value in incoming]
        left = min(x, nx)
        top = min(y, ny)
        right = max(x + w, nx + nw)
        bottom = max(y + h, ny + nh)
        GRAPHICSDIRTYRECT = [left, top, right - left, bottom - top]
        return True

    except Exception:

        return False


def graphicsgetdirty():

    if GRAPHICSDIRTYRECT is None:
        return None

    return list(GRAPHICSDIRTYRECT)


def graphicsresetdirty():

    global GRAPHICSDIRTYRECT
    GRAPHICSDIRTYRECT = None


def graphicsrecordrectangle(x, y, w, h, color):

    global GRAPHICSDISPLAYLIST

    rect = graphicscliprect(x, y, w, h)

    if rect is None:
        return

    command = {
        "kind": "rectangle",
        "rect": list(rect),
        "color": int(color),
        "clip": [0, 0, int(SCREEN_W), int(SCREEN_H)],
    }
    item = {"command": command, "bounds": list(rect)}
    graphicsmarkdirty(rect)

    if rect == [0, 0, int(SCREEN_W), int(SCREEN_H)]:

        GRAPHICSDISPLAYLIST = [item]
        return

    # opaque clears replace any older objects that they fully cover
    kept = []

    for current in GRAPHICSDISPLAYLIST:

        if graphicscontains(rect, current.get("bounds", [])) and current is not GRAPHICSDISPLAYLIST[0]:
            continue

        kept.append(current)

    kept.append(item)
    GRAPHICSDISPLAYLIST = kept


def graphicstextbaseline(y, size, fontpath):

    try:

        face = getttfface(fontpath)

        if face is None:
            return int(y)

        face.set_pixel_sizes(0, int(size))
        ascender = int(face.size.ascender >> 6)
        return int(y) + int(size) - ascender

    except Exception:

        return int(y)


def graphicsrecordtext(x, y, text, color, size, fontpath=None, clip=None):

    if not text:
        return

    path = str(fontpath or FONTFILE)

    try:

        width = max(1, int(measuretext(str(text), int(size), fontpath=path)))
        yoff, height = ttflinebox(int(size), fontpath=path)

    except Exception:

        width = max(1, int(size) * len(str(text)))
        yoff = 0
        height = max(1, int(size))

    bounds = graphicscliprect(int(x), int(y) + int(yoff), width, height)

    if bounds is None:
        return

    commandclip = [0, 0, int(SCREEN_W), int(SCREEN_H)]

    if clip is not None:

        commandclip = graphicscliprect(*clip)

        if commandclip is None:
            return

        bounds = graphicsintersectrect(bounds, commandclip)

        if bounds is None:
            return

    command = {
        "kind": "text",
        "x": max(0, int(x)),
        "y": graphicstextbaseline(y, size, path),
        "text": str(text),
        "size": int(size),
        "font": path,
        "color": int(color),
        "clip": list(commandclip),
    }
    GRAPHICSDISPLAYLIST.append({"command": command, "bounds": list(bounds), "cpu_y": int(y)})
    graphicsmarkdirty(bounds)


def graphicsrecordimage(path, sourcew, sourceh, x, y, w, h):

    rect = graphicscliprect(x, y, w, h)

    if rect is None:
        return

    command = {
        "kind": "image",
        "path": str(path),
        "source_width": int(sourcew),
        "source_height": int(sourceh),
        "format": "BGRA32",
        "rect": list(rect),
        "clip": [0, 0, int(SCREEN_W), int(SCREEN_H)],
    }
    GRAPHICSDISPLAYLIST.append({
        "command": command,
        "bounds": list(rect),
    })
    graphicsmarkdirty(rect)


def clear(color=BACKGROUNDCOLOUR):

    if not (GRAPHICSSTATE.get("available") and managedstrict(GRAPHICSSTATE)):
        _cpuclear(color)

    graphicsrecordrectangle(0, 0, int(SCREEN_W), int(SCREEN_H), color)


def drawline(x1, y1, x2, y2, color):

    if not (GRAPHICSSTATE.get("available") and managedstrict(GRAPHICSSTATE)):
        _cpudrawline(x1, y1, x2, y2, color)

    left = min(int(x1), int(x2))
    top = min(int(y1), int(y2))
    width = abs(int(x2) - int(x1)) + 1
    height = abs(int(y2) - int(y1)) + 1
    graphicsrecordrectangle(left, top, width, height, color)


def drawtextttf(x, y, text, color, size, fontpath=None, clip=None):

    if not (GRAPHICSSTATE.get("available") and managedstrict(GRAPHICSSTATE)):
        _cpudrawtextttf(
            x,
            y,
            text,
            color,
            size,
            fontpath=fontpath,
            clip=clip,
        )

    graphicsrecordtext(
        x,
        y,
        text,
        color,
        size,
        fontpath=fontpath,
        clip=clip,
    )


def drawimage(path, sourcew, sourceh, x, y, w, h):

    if not (GRAPHICSSTATE.get("available") and managedstrict(GRAPHICSSTATE)):
        blitfilescaledfast(
            path,
            int(sourcew),
            int(sourceh),
            int(x),
            int(y),
            int(w),
            int(h),
            "BGRA32",
        )

    graphicsrecordimage(path, sourcew, sourceh, x, y, w, h)


# misc functions
def cleartobrick():

    # clear to black
    clear(BACKGROUNDCOLOUR)


def fillrect(x, y, w, h, color):

    # fill over password characters
    if not (GRAPHICSSTATE.get("available") and managedstrict(GRAPHICSSTATE)):

        for yy in range(y, y + h):
            _cpudrawline(x, yy, x + w, yy, color)

    graphicsrecordrectangle(x, y, w, h, color)


def updatelayout():

    global SCALE, OFFX, OFFY, SCREEN_W, SCREEN_H

    try:

        sx = float(SCREEN_W) / float(BASE_W)

        sy = float(SCREEN_H) / float(BASE_H)

        SCALE = min(sx, sy)

        OFFX = int((float(SCREEN_W) - (float(BASE_W) * SCALE)) * 0.5)

        OFFY = int((float(SCREEN_H) - (float(BASE_H) * SCALE)) * 0.5)

    except Exception:

        SCALE = 1.0

        OFFX = 0

        OFFY = 0


def scx(x):

    try:

        return int(OFFX + (float(x) * float(SCALE)) + 0.5)

    except Exception:

        return int(x)


def scy(y):

    try:

        return int(OFFY + (float(y) * float(SCALE)) + 0.5)

    except Exception:

        return int(y)


def scs(v):

    try:

        v = int((float(v) * float(SCALE)) + 0.5)

    except Exception:

        v = int(v)

    if v < 12:

        v = 12

    return v


def masterimagecatalogue():

    global PILIMAGE, PILIMAGEOPS

    if PILIMAGE is not None and PILIMAGEOPS is not None:
        return PILIMAGE, PILIMAGEOPS

    if IMAGECATALOGUE not in sys.path:
        sys.path.insert(0, IMAGECATALOGUE)

    from PIL import Image as loadedimage
    from PIL import ImageOps as loadedops

    PILIMAGE = loadedimage
    PILIMAGEOPS = loadedops
    return PILIMAGE, PILIMAGEOPS


def masterimagesetting():

    try:

        with open(MASTERSETTINGSFILE, "r", encoding="utf-8") as stream:
            configured = json.load(stream)

        if not isinstance(configured, dict):
            return ""

        rawenabled = configured.get("use_master_image", False)
        enabled = (
            rawenabled
            if isinstance(rawenabled, bool)
            else str(rawenabled).strip().lower() in ("1", "true", "yes", "on")
        )
        path = str(configured.get("image_path", "") or "").strip()

        if not enabled or not path:
            return ""

        path = os.path.abspath(path)

        if not os.path.isfile(os.path.realpath(path)):
            return ""

        return path

    except Exception:

        return ""


def masterimagecachedir():

    parent = os.path.realpath("/.ephemeral")
    root = os.path.abspath(MASTERIMAGECACHEBASE)

    os.makedirs(parent, mode=0o700, exist_ok=True)

    if os.path.lexists(root) and os.path.islink(root):
        raise RuntimeError("master image cache cannot be a symbolic link")

    os.makedirs(root, mode=0o700, exist_ok=True)
    realroot = os.path.realpath(root)

    if os.path.commonpath((parent, realroot)) != parent:
        raise RuntimeError("master image cache is outside /.ephemeral")

    os.chmod(realroot, 0o700)
    return realroot


def masterimagesize(sourcewidth, sourceheight):

    sourcewidth = int(sourcewidth)
    sourceheight = int(sourceheight)

    if sourcewidth < 1 or sourceheight < 1:
        raise ValueError("master image dimensions are invalid")

    # Keep the image's layout footprint in the 1920x1080 design coordinate
    # system, but prepare its pixels for the current physical display.  This
    # avoids reducing every image to 154px and then enlarging that cache on
    # high-DPI displays.
    ratio = min(
        float(MASTERIMAGE_MAX_W) / float(sourcewidth),
        float(MASTERIMAGE_MAX_H) / float(sourceheight),
    )
    designwidth = max(
        1, min(MASTERIMAGE_MAX_W, int(round(sourcewidth * ratio))))
    designheight = max(
        1, min(MASTERIMAGE_MAX_H, int(round(sourceheight * ratio))))
    width = max(1, int(round(float(designwidth) * float(SCALE))))
    height = max(1, int(round(float(designheight) * float(SCALE))))
    return designwidth, designheight, width, height


def preparemasterimage():

    path = masterimagesetting()

    if not path:
        return None

    temporary = ""

    try:

        cachepath = os.path.join(
            masterimagecachedir(),
            os.path.basename(MASTERIMAGECACHEPATH),
        )
        temporary = f"{cachepath}.tmp-{time.monotonic_ns()}"
        imagemodule, opsmodule = masterimagecatalogue()
        imagemodule.MAX_IMAGE_PIXELS = MASTERIMAGEPIXELLIMIT

        with warnings.catch_warnings():

            warnings.simplefilter("error", imagemodule.DecompressionBombWarning)

            with imagemodule.open(os.path.realpath(path)) as opened:

                opened.seek(0)
                opened.load()
                form = str(opened.format or "").upper()

                if form not in ("PNG", "JPEG", "WEBP", "BMP", "GIF"):
                    raise ValueError("master image format is not supported")

                image = opsmodule.exif_transpose(opened).convert("RGBA")

                if (
                    image.width < 1 or image.height < 1 or
                    image.width * image.height > MASTERIMAGEPIXELLIMIT
                ):
                    raise ValueError("master image dimensions are invalid")

                designwidth, designheight, width, height = masterimagesize(
                    image.width, image.height)

                if image.size != (width, height):
                    image = image.resize(
                        (width, height),
                        imagemodule.Resampling.LANCZOS,
                        reducing_gap=3.0,
                    )

                canvas = imagemodule.new(
                    "RGBA", (width, height), (0, 0, 0, 255))
                canvas.alpha_composite(image, (0, 0))
                pixels = canvas.tobytes("raw", "BGRA")

        if len(pixels) != width * height * 4:
            raise RuntimeError("master image decoder returned an invalid surface")

        descriptor = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)

        with os.fdopen(descriptor, "wb") as stream:
            stream.write(pixels)
            stream.flush()
            os.fsync(stream.fileno())

        os.replace(temporary, cachepath)
        os.chmod(cachepath, 0o600)
        return {
            "path": cachepath,
            "width": int(width),
            "height": int(height),
            "design_width": int(designwidth),
            "design_height": int(designheight),
        }

    except Exception as error:

        log(f"master image unavailable path={path} error={error}")
        return None

    finally:

        try:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)
        except Exception:
            pass


def loginlayout(masterimage=None):

    layout = {
        "title_y": scy(480),
        "master_y": scy(540),
        "password_y": scy(600),
        "password_clear_y": scy(660) - scy(60),
        "underline_y": scy(660),
        "image_rect": None,
    }

    if not masterimage:
        return layout

    try:

        imagew = max(
            1, int(masterimage.get("design_width", masterimage["width"])))
        imageh = max(
            1, int(masterimage.get("design_height", masterimage["height"])))
        gap = int(MASTERIMAGE_LOGIN_GAP)
        # The separator occupies one pixel. Adjusting the visual gap by at
        # most one pixel lets both outer gaps be exactly equal in the 1080p
        # design coordinate system.
        contentheight = imageh + gap + (660 - 480) + 1

        if (BASE_H - contentheight) % 2:
            gap += 1
            contentheight += 1

        imagetop = (BASE_H - contentheight) // 2
        titley = imagetop + imageh + gap
        master_y = titley + (540 - 480)
        password_y = titley + (600 - 480)
        underline_y = titley + (660 - 480)
        if "design_width" in masterimage and "design_height" in masterimage:
            # preparemasterimage already generated the cache at the exact
            # physical destination size, so render it without another scale.
            draww = max(1, int(masterimage["width"]))
            drawh = max(1, int(masterimage["height"]))
        else:
            # Retain compatibility with synthetic and older descriptors.
            draww = max(1, int(round(float(imagew) * float(SCALE))))
            drawh = max(1, int(round(float(imageh) * float(SCALE))))
        underline_screen_y = scy(underline_y)
        image_screen_y = int(SCREEN_H) - (underline_screen_y + 1)

        layout.update({
            "title_y": scy(titley),
            "master_y": scy(master_y),
            "password_y": scy(password_y),
            "password_clear_y": scy(password_y),
            "underline_y": underline_screen_y,
            "image_rect": [
                (int(SCREEN_W) - draww) // 2,
                image_screen_y,
                draww,
                drawh,
            ],
            "base_image_top": imagetop,
            "base_underline_y": underline_y,
        })

    except Exception:

        pass

    return layout


def showerror(msg, x, y, fontsize):

    global ERRORMSG, ERRORRECT, ERROREXPIRES

    es = max(12, int(fontsize))

    ew = measuretext(msg, es)

    pad = 6

    ex = int(x)

    ey = int(y)

    yoff, h = ttflinebox(es, fontpath=FONTFILE)

    ERRORMSG = (msg, ex, ey, es)

    ERRORRECT = (ex - pad, (ey + yoff) - pad, ew + pad * 2, h + pad * 2)

    ERROREXPIRES = time.time() + ERRORDURATION

    # clear background (full line box including descenders)
    fillrect(ERRORRECT[0], ERRORRECT[1], ERRORRECT[2], ERRORRECT[3], BACKGROUNDCOLOUR)

    # draw text
    drawtextttf(ex, ey, msg, ERRORCOLOUR, es)

    wspresent()


def tickerror():

    global ERRORMSG, ERRORRECT, ERROREXPIRES

    if not ERRORMSG:
        return

    if time.time() < ERROREXPIRES:
        return

    # clear expired error
    x, y, w, h = ERRORRECT

    fillrect(x, y, w, h, BACKGROUNDCOLOUR)

    wspresent()

    ERRORMSG = None

    ERRORRECT = None

    ERROREXPIRES = 0.0


# logging functions
def logopen():

    global STARTLOGFD

    try:

        # GODDESS owns the log tier lifecycle. Startup may run without
        # architect authority, so it only opens its assigned file.
        STARTLOGFD = open(STARTLOGFILE, "a")

        # ensure file opened
        if not STARTLOGFD:
            print(formatlog('startup', 'could not open startup log file'))
            return False

    except PermissionError:

        # permission denied opening log file
        print(formatlog('startup', 'permission denied opening startup log file'))
        return False

    except Exception as e:

        # opening log file error
        print(formatlog('startup', f'error opening startup log file {e}'))
        return False

    return True


def log(msg):

    if not DEBUGSTARTUP:
        return

    global STARTLOGFD
    if STARTLOGFD is None:
        ok = logopen()
        if not ok:
            return

    try:

        # write log line
        STARTLOGFD.write(formatlog('startup', msg) + "\n")

        # flush python buffer
        STARTLOGFD.flush()

        # flush OS buffer
        os.fsync(STARTLOGFD.fileno())

    except PermissionError:

        # permission denied writing log file
        print(formatlog('startup', 'permission denied writing startup log file'))

    except Exception as e:

        # writing log file error
        print(formatlog('startup', f'error writing startup log file {e}'))


def bootanimationpid():

    try:
        pid = int(str(os.environ.get("T1OS_BOOT_ANIMATION_PID", "")).strip())
    except (TypeError, ValueError):
        return 0

    return pid if pid > 1 else 0


def bootanimationalive(pid):

    if int(pid) <= 1:
        return False

    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def bootanimationstate(pid):

    try:

        with open(BOOTANIMATIONSTATE, "r", encoding="utf-8") as stream:
            state = json.load(stream)

        if int(state.get("pid", 0)) != int(pid):
            return ""

        return str(state.get("state", "")).strip().lower()

    except (FileNotFoundError, PermissionError, OSError, ValueError, TypeError):

        return ""


def bootanimationwrite(pid, action):

    temporary = f"{BOOTANIMATIONREQUEST}.{os.getpid()}.new"

    try:

        os.makedirs(BOOTANIMATIONBASE, mode=0o700, exist_ok=True)

        with open(temporary, "w", encoding="utf-8") as stream:

            json.dump({
                "format": 1,
                "pid": int(pid),
                "action": str(action),
            }, stream, sort_keys=True, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())

        os.replace(temporary, BOOTANIMATIONREQUEST)
        return True

    except Exception as error:

        try:
            os.unlink(temporary)
        except Exception:
            pass

        log(f'{timestamp()} [startup] boot animation handoff write failed {error}')
        return False


def stopbootanimationprocess(pid):

    if not bootanimationalive(pid):
        return True

    try:
        os.kill(int(pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        return not bootanimationalive(pid)

    deadline = time.monotonic() + 1.0

    while time.monotonic() < deadline and bootanimationalive(pid):
        time.sleep(0.02)

    if bootanimationalive(pid):

        try:
            os.kill(int(pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass

        deadline = time.monotonic() + 1.0

        while time.monotonic() < deadline and bootanimationalive(pid):
            time.sleep(0.02)

    return not bootanimationalive(pid)


def bootanimationhandoff(action, timeout):

    pid = bootanimationpid()

    if pid and bootanimationalive(pid):

        state = bootanimationstate(pid)

        if state in ("starting", "dots", "branding", "handoff") and bootanimationwrite(pid, action):

            deadline = time.monotonic() + max(0.5, float(timeout))

            while time.monotonic() < deadline:

                if bootanimationstate(pid) == "done" or not bootanimationalive(pid):
                    log(f'{timestamp()} [startup] boot animation handoff completed action={action}')
                    return True

                time.sleep(0.02)

        log(f'{timestamp()} [startup] boot animation handoff timed out action={action}')
        if stopbootanimationprocess(pid):
            log(f'{timestamp()} [startup] boot animation forcibly removed action={action}')
            return True

    if action == "brand":

        try:

            process = popenisolated(
                [BOOTANIMATIONSCRIPT, "brand"],
                softwarepath=BOOTANIMATIONSCRIPT,
                logpath="/the one/logs/boot animation.py.log",
                security_profile="boot-animation",
            )
            returncode = process.wait()

            if returncode:
                raise subprocess.CalledProcessError(
                    returncode,
                    [BOOTANIMATIONSCRIPT, "brand"],
                )

            return True

        except FileNotFoundError:

            log(f'{timestamp()} [startup] boot animation not found')

        except (subprocess.CalledProcessError, OSError) as error:

            log(f'{timestamp()} [startup] first-run branding failed {error}')

    return action == "lockscreen" and not bootanimationalive(pid)


def lockscreenstate(pid):

    try:

        with open(LOCKSCREENSTATE, "r", encoding="utf-8") as stream:
            state = json.load(stream)

        if int(state.get("pid", 0)) != int(pid):
            return ""

        return str(state.get("state", "")).strip().lower()

    except (FileNotFoundError, PermissionError, OSError, ValueError, TypeError):

        return ""


def lockscreenpresentationreceipt():

    try:

        with open(LOCKSCREENREADYPATH, "r", encoding="utf-8") as stream:
            state = json.load(stream)

        if not isinstance(state, dict):
            return None

        if (
            state.get("role") != "lockscreen"
            or state.get("topmost_role") != "lockscreen"
            or int(state.get("topmost_window", 0)) not in [
                int(value) for value in state.get("windows", [])
            ]
            or int(state.get("windowserver_pid", 0)) <= 1
            or not str(state.get("server", "")).strip()
            or state.get("gpu_failed") is not False
        ):
            return None

        return state

    except (FileNotFoundError, PermissionError, OSError, ValueError, TypeError):

        return None


def lockscreenreceiptphysicallyverified(state):

    if not isinstance(state, dict):
        return False

    backend = str(state.get("backend", "")).strip().lower()

    if backend == "opengl":
        proof = state.get("presentation_proof")
        return (
            state.get("hardware_accelerated") is True
            and bool(str(state.get("renderer", "")).strip())
            and int(state.get("frame_sequence", 0)) > 0
            and isinstance(proof, dict)
            and proof.get("verified") is True
            and proof.get("scanout") is True
            and proof.get("nonblack") is True
            and proof.get("contrast") is True
        )

    if backend in ("framebuffer", "kms-framebuffer"):
        proof = state.get("presentation_proof", {})
        common = (
            state.get("hardware_accelerated") is False
            and state.get("full_coverage") is True
            and int(state.get("frame_sequence", 0)) > 0
            and isinstance(proof, dict)
            and proof.get("verified") is True
            and proof.get("nonblack") is True
            and proof.get("scanout") is True
        )

        if backend == "kms-framebuffer":
            # A DRM dumb buffer may be a write-combined device mapping.
            # Reading it back can enter the same wedged vendor driver that
            # forced recovery, so use the exact live CRTC/connector/vblank
            # receipt emitted by WindowServer. This must stay identical to
            # lock screen.py's initial presentation barrier.
            vblank = proof.get("vblank_sequence", {})
            boundary = proof.get("presentation_boundary")
            physicalboundary = bool(
                (
                    boundary == "drm-crtc-sequence"
                    and isinstance(vblank, dict)
                    and vblank.get("advanced") is True
                )
                or (
                    str(state.get("drm_driver", "")).strip().lower()
                    in ("virtio_gpu", "vmwgfx")
                    and boundary in (
                        "virtio-resource-flush", "vmwgfx-dirtyfb-flush"
                    )
                    and (
                        (str(state.get("drm_driver", "")).strip().lower()
                         == "virtio_gpu"
                         and boundary == "virtio-resource-flush")
                        or
                        (str(state.get("drm_driver", "")).strip().lower()
                         == "vmwgfx"
                         and boundary == "vmwgfx-dirtyfb-flush")
                    )
                    and isinstance(vblank, dict)
                    and vblank.get("unsupported") is True
                    and proof.get("dirty_status") == "complete"
                    and int(proof.get("present_sequence", 0)) >= 2
                )
                or (
                    str(state.get("drm_driver", "")).strip().lower()
                    == "nvidia-drm"
                    and boundary == "nvidia-continuous-scanout"
                    and isinstance(vblank, dict)
                    and vblank.get("unsupported") is True
                    and int(vblank.get("errno") or 0) == 95
                    and proof.get("dirty_status") == "unsupported:38"
                    and proof.get("flush_status")
                    == "not-required:drm-ioctl-boundary"
                    and int(proof.get("present_sequence", 0)) >= 2
                    and int(proof.get("modeset_sequence", 0)) > 0
                )
            )
            return (
                common
                and proof.get("connector_connected") is True
                and proof.get("connector_routed") is True
                and proof.get("connector_link_status") != "bad"
                and physicalboundary
                and proof.get("write_committed") is True
                and proof.get("mode_matches") is True
                and proof.get("readback") is False
                and proof.get("readback_skipped")
                == "write-combined-device-mapping"
            )

        firmwareproof = bool(
            proof.get("readback") is True
            and proof.get("legacy_firmware_framebuffer") is True
            and proof.get("firmware_framebuffer_boot") is True
        )
        vblank = proof.get("vblank_sequence", {})
        boundary = proof.get("presentation_boundary")
        nativeboundary = bool(
            (
                boundary == "drm-crtc-sequence"
                and isinstance(vblank, dict)
                and vblank.get("advanced") is True
            )
            or (
                proof.get("legacy_driver_family") == "virtio"
                and boundary == "virtio-fbdev-pan"
                and isinstance(vblank, dict)
                and vblank.get("unsupported") is True
            )
        )
        nativeproof = bool(
            proof.get("readback") is False
            and proof.get("readback_skipped")
            == "native-drm-fbdev-write-combined-mapping"
            and proof.get("legacy_console_owned") is True
            and proof.get("legacy_pan_committed") is True
            and proof.get("legacy_owner_connected") is True
            and nativeboundary
            and proof.get("connector_link_status") != "bad"
        )
        return (
            common
            and proof.get("legacy_page_zero") is True
            and (firmwareproof or nativeproof)
        )

    return False


def currentvisiblelockscreen(previous):

    if not isinstance(previous, dict):
        return None

    current = lockscreenpresentationreceipt()

    if (
        current is None
        or str(current.get("server", ""))
        != str(previous.get("server", ""))
        or int(current.get("windowserver_pid", 0))
        != int(previous.get("windowserver_pid", 0))
        or int(current.get("frame_sequence", 0))
        < int(previous.get("frame_sequence", 0))
        or current.get("boot_active") is not False
        or not lockscreenreceiptphysicallyverified(current)
    ):
        return None

    return current


def waitlockscreenposthandoff(previous, timeout=8.0):

    if not isinstance(previous, dict):
        return None

    server = str(previous.get("server", ""))
    windowserverpid = int(previous.get("windowserver_pid", 0))
    sequence = int(previous.get("frame_sequence", 0))
    deadline = time.monotonic() + max(1.0, float(timeout))

    while time.monotonic() < deadline:

        current = lockscreenpresentationreceipt()

        if (
            current is not None
            and str(current.get("server", "")) == server
            and int(current.get("windowserver_pid", 0)) == windowserverpid
            and int(current.get("frame_sequence", 0)) > sequence
            and current.get("boot_active") is False
        ):

            if lockscreenreceiptphysicallyverified(current):
                return current

        time.sleep(0.02)

    return None


def writeposthandoffstate(pid, receipt):

    temporary = f"{LOCKSCREENPOSTHANDOFFSTATE}.{os.getpid()}.new"

    try:

        if (
            not isinstance(receipt, dict)
            or receipt.get("boot_active") is not False
            or not lockscreenreceiptphysicallyverified(receipt)
        ):
            return False

        os.makedirs(LOCKSCREENBASE, mode=0o700, exist_ok=True)

        proof = receipt.get("presentation_proof", {})
        boundary = (
            str(proof.get("presentation_boundary", "")).strip()
            if isinstance(proof, dict)
            else ""
        )

        with open(temporary, "x", encoding="utf-8") as stream:
            json.dump({
                "format": 1,
                "state": "ready",
                "pid": int(pid),
                "windowserver_pid": int(receipt.get("windowserver_pid", 0)),
                "server": str(receipt.get("server", "")),
                "backend": str(receipt.get("backend", "")),
                "frame_sequence": int(receipt.get("frame_sequence", 0)),
                "boot_active": False,
                "physically_verified": True,
                "presentation_boundary": boundary,
            }, stream, sort_keys=True, separators=(",", ":"))
            stream.flush()
            os.fchown(stream.fileno(), 0, 1000)
            os.fchmod(stream.fileno(), 0o440)
            os.fsync(stream.fileno())

        # Startup is root, while the lock-screen process deliberately runs as
        # the desktop identity. Keep the proof root-owned and immutable to the
        # reader, but make it readable by the exact desktop session group.
        # Without this, the lock screen can never observe the authorization it
        # is required to verify and therefore rejects every activation key.
        os.replace(temporary, LOCKSCREENPOSTHANDOFFSTATE)
        return True

    except Exception as error:

        try:
            os.unlink(temporary)
        except Exception:
            pass

        log(
            f'{timestamp()} [startup] could not publish post-handoff '
            f'lock-screen state {error}'
        )
        return False


def reportlockscreenfailure(pid, detail):

    temporary = f"{LOCKSCREENSTATE}.{os.getpid()}.new"

    try:
        os.makedirs(LOCKSCREENBASE, mode=0o700, exist_ok=True)

        with open(temporary, "w", encoding="utf-8") as stream:
            json.dump({
                "format": 1,
                "pid": int(pid),
                "state": "failed",
                "detail": str(detail),
            }, stream, sort_keys=True, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())

        os.replace(temporary, LOCKSCREENSTATE)
        return True

    except Exception:

        try:
            os.unlink(temporary)
        except Exception:
            pass

        return False


def faillockscreenprocess(process, detail):

    try:
        process.terminate()
        process.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=1.0)
    except Exception:
        pass

    reportlockscreenfailure(process.pid, detail)


def preparelockscreenbase():

    os.makedirs(LOCKSCREENBASE, mode=0o700, exist_ok=True)
    metadata = os.stat(LOCKSCREENBASE, follow_symlinks=False)

    if not stat.S_ISDIR(metadata.st_mode):
        raise PermissionError("unsafe lock-screen lifecycle directory")

    if os.geteuid() == 0:
        os.chown(LOCKSCREENBASE, 1000, 1000, follow_symlinks=False)
        os.chmod(LOCKSCREENBASE, 0o700, follow_symlinks=False)
        metadata = os.stat(LOCKSCREENBASE, follow_symlinks=False)

    if (
        metadata.st_uid != 1000 or metadata.st_gid != 1000 or
        stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise PermissionError("unsafe lock-screen lifecycle ownership")


def runlockscreenwithhandoff(timeout=20.0):

    try:
        preparelockscreenbase()
        for path in (LOCKSCREENSTATE, LOCKSCREENPOSTHANDOFFSTATE):
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
    except OSError as error:
        log(
            f'{timestamp()} [startup] could not reset lock screen '
            f'presentation state {error}'
        )

    process = popenisolated(
        [LOCKSCREENSCRIPT],
        softwarepath=LOCKSCREENSCRIPT,
        logpath=LOCKSCREENLOG,
        security_profile="lockscreen",
        preexec_fn=dropdesktopidentity,
    )
    deadline = time.monotonic() + max(1.0, float(timeout))

    while time.monotonic() < deadline:

        state = lockscreenstate(process.pid)

        if state == "ready":

            firstreceipt = lockscreenpresentationreceipt()

            if firstreceipt is None:
                detail = (
                    "lock screen lifecycle reached ready without a current "
                    "topmost presentation receipt"
                )
                faillockscreenprocess(process, detail)
                raise RuntimeError(detail)

            log(f'{timestamp()} [startup] lock screen first frame ready pid={process.pid}')
            print(formatlog('startup', f'lock screen first frame ready pid={process.pid}'), flush=True)

            if firstreceipt.get("boot_active") is not False:

                if not bootanimationhandoff("lockscreen", 3.0):
                    # Process-state bookkeeping can lag a forced client
                    # teardown (notably a zombie animation owned by PID 1).
                    # The current, PID/server-bound presentation receipt is
                    # the authoritative visual result. Never discard a
                    # verified topmost lockscreen merely because the retired
                    # animation process has not yet been reaped.
                    visible = currentvisiblelockscreen(firstreceipt)

                    if visible is None:
                        detail = "boot animation could not be removed for lock-screen handoff"
                        faillockscreenprocess(process, detail)
                        raise RuntimeError(detail)

                    firstreceipt = visible
                    log(
                        f'{timestamp()} [startup] boot animation process state '
                        f'lagged verified lock-screen handoff'
                    )
            else:
                log(
                    f'{timestamp()} [startup] boot animation already absent '
                    f'at verified lock-screen handoff'
                )

            if firstreceipt.get("boot_active") is not False:
                posthandoffreceipt = waitlockscreenposthandoff(firstreceipt)
            else:
                posthandoffreceipt = currentvisiblelockscreen(firstreceipt)

            if posthandoffreceipt is None:
                detail = (
                    "no verified lock-screen presentation followed "
                    "boot-animation removal"
                )
                faillockscreenprocess(process, detail)
                raise RuntimeError(detail)

            if not writeposthandoffstate(process.pid, posthandoffreceipt):
                detail = (
                    "verified lock-screen presentation could not publish "
                    "its post-handoff supervision state"
                )
                faillockscreenprocess(process, detail)
                raise RuntimeError(detail)

            posthandoffmessage = (
                f'post-handoff lock screen presentation verified pid={process.pid}'
            )
            log(f'{timestamp()} [startup] {posthandoffmessage}')
            print(formatlog('startup', posthandoffmessage), flush=True)
            status = process.wait()

            if status != 0:
                raise subprocess.CalledProcessError(status, process.args)

            return

        status = process.poll()

        if status is not None:
            raise RuntimeError(
                f"lock screen exited before first-frame readiness "
                f"state={state or 'missing'} status={status}"
            )

        if state == "failed":
            raise RuntimeError("lock screen reported first-frame failure")

        time.sleep(0.02)

    detail = "lock screen did not report first-frame readiness"
    faillockscreenprocess(process, detail)
    raise TimeoutError(detail)


# managed graphics functions
def graphicssyncstate():

    global GRAPHICSCAPS, GRAPHICSAVAILABLE, GRAPHICSACTIVE, GRAPHICSPENDING
    global GRAPHICSFAILURE, GRAPHICSFRAMES, GRAPHICSMAXCOMMANDS, GRAPHICSLASTCOMMANDS

    GRAPHICSCAPS = dict(GRAPHICSSTATE.get("capabilities", {}))
    GRAPHICSAVAILABLE = bool(GRAPHICSSTATE.get("available", False))
    GRAPHICSACTIVE = bool(GRAPHICSSTATE.get("active", False))
    GRAPHICSPENDING = bool(GRAPHICSSTATE.get("pending", False))
    GRAPHICSFAILURE = str(GRAPHICSSTATE.get("failure", ""))
    GRAPHICSFRAMES = int(GRAPHICSSTATE.get("frames", 0))
    GRAPHICSMAXCOMMANDS = int(GRAPHICSSTATE.get("maximum_commands", 0))
    GRAPHICSLASTCOMMANDS = int(GRAPHICSSTATE.get("last_commands", 0))


def graphicsconfigure(capabilities):

    managedconfigure(
        GRAPHICSSTATE,
        capabilities,
        required=("rectangle", "text"),
        cpu=GRAPHICSCPUOVERRIDE or not os.path.isfile(FONTFILE),
    )
    graphicssyncstate()


def graphicsdamage():

    try:

        if WSSOCK and WINID:
            wssend({"op": "DAMAGE", "winid": int(WINID), "rect": [0, 0, int(SCREEN_W), int(SCREEN_H)]})

    except Exception:

        pass


def graphicsrestorecpu():

    try:

        graphicsreplaycpu()
        present()
        resetdirty()
        graphicsresetdirty()
        graphicsdamage()
        return True

    except Exception as e:

        log(f"graphics CPU restore error {e}")
        graphicsdamage()
        return False


def graphicsdisable(reason, clearcommands=True):

    if manageddisable(GRAPHICSSTATE, reason):
        graphicssyncstate()
        return True

    try:

        if clearcommands and WSSOCK and WINID:
            wssend({"op": "GRAPHICS_CLEAR", "winid": int(WINID)})

    except Exception:

        pass

    graphicssyncstate()
    graphicsrestorecpu()
    return False


def graphicsresponse(msg):

    try:

        if WINID and "winid" in msg and int(msg.get("winid", 0)) != int(WINID):
            return False

    except Exception:

        return False

    before = bool(GRAPHICSSTATE.get("available"))
    handled = managedresponse(GRAPHICSSTATE, msg)
    graphicssyncstate()

    if before and not GRAPHICSSTATE.get("available"):

        try:

            if msg.get("code") != "graphics_clear_failed" and WSSOCK and WINID:
                wssend({"op": "GRAPHICS_CLEAR", "winid": int(WINID)})

        except Exception:

            pass

        graphicsrestorecpu()

    return bool(handled)


def graphicsbuildscene():

    global GRAPHICSBUILDTOTALMS, GRAPHICSBUILDMAXIMUMMS, GRAPHICSBUILDCOUNT

    started = time.monotonic_ns()
    commands = []
    width = max(1, int(SCREEN_W))
    height = max(1, int(SCREEN_H))
    textlimit = max(1, int(GRAPHICSSTATE.get("text_limit", 1024)))

    try:

        for item in GRAPHICSDISPLAYLIST:

            source = dict(item.get("command", {}))

            if source.get("kind") != "text":

                commands.append(source)
                continue

            text = str(source.get("text", ""))

            if not text:
                continue

            offset = 0

            while offset < len(text):

                chunk = text[offset:offset + textlimit]
                command = dict(source)
                command["text"] = chunk

                if offset:

                    prefix = text[:offset]
                    command["x"] = int(source.get("x", 0)) + int(measuretext(prefix, int(source.get("size", 1)), fontpath=source.get("font")))

                commands.append(command)
                offset += len(chunk)

        if not commands or commands[0].get("kind") != "rectangle" or commands[0].get("rect") != [0, 0, width, height]:

            commands.insert(0, {
                "kind": "rectangle",
                "rect": [0, 0, width, height],
                "color": int(BACKGROUNDCOLOUR),
                "clip": [0, 0, width, height],
            })

    finally:

        elapsed = (time.monotonic_ns() - started) / 1000000.0
        GRAPHICSBUILDTOTALMS += elapsed
        GRAPHICSBUILDMAXIMUMMS = max(GRAPHICSBUILDMAXIMUMMS, elapsed)
        GRAPHICSBUILDCOUNT += 1

    return commands


def graphicspump():

    wasavailable = bool(GRAPHICSSTATE.get("available"))

    if not managedtick(GRAPHICSSTATE):

        if wasavailable and WSSOCK and WINID:

            wssend({"op": "GRAPHICS_CLEAR", "winid": int(WINID)})
            graphicsrestorecpu()

        graphicssyncstate()
        return False

    if not GRAPHICSSTATE.get("available") or not WSSOCK or not WINID:
        return False

    if GRAPHICSSTATE.get("pending") or not GRAPHICSSTATE.get("need_submit"):

        graphicssyncstate()
        return bool(GRAPHICSSTATE.get("active"))

    commands = graphicsbuildscene()

    if not commands or commands[0].get("rect") != [0, 0, int(SCREEN_W), int(SCREEN_H)]:

        graphicsdisable("managed scene does not contain a complete background")
        return False

    before = bool(GRAPHICSSTATE.get("available"))
    managedsubmit(GRAPHICSSTATE, wssend, int(WINID), commands)

    if before and not GRAPHICSSTATE.get("available"):

        wssend({"op": "GRAPHICS_CLEAR", "winid": int(WINID)})
        graphicsrestorecpu()

    graphicssyncstate()
    return bool(GRAPHICSSTATE.get("active"))


def graphicspresent(rect):

    if not GRAPHICSSTATE.get("available"):
        return False

    if rect:

        managedmarkdamage(
            GRAPHICSSTATE,
            rect,
            bounds=(int(SCREEN_W), int(SCREEN_H)),
        )

    else:

        managedmarkdamage(
            GRAPHICSSTATE,
            [0, 0, int(SCREEN_W), int(SCREEN_H)],
            bounds=(int(SCREEN_W), int(SCREEN_H)),
        )

    return graphicspump()


def graphicswaitinitial(timeout=0.5):

    deadline = time.monotonic() + max(0.05, float(timeout))

    while (GRAPHICSSTATE.get("pending") or GRAPHICSSTATE.get("need_submit")) and time.monotonic() < deadline:

        if not GRAPHICSSTATE.get("pending") and GRAPHICSSTATE.get("need_submit"):

            graphicspump()

        for ln in wsrecvlines(timeout=0.02):

            try:

                msg = json.loads(ln)

            except Exception:

                continue

            op = msg.get("op")

            if op in ("GRAPHICS_COMMITTED", "GRAPHICS_CLEARED") or (op == "ERROR" and str(msg.get("code", "")).startswith("graphics_")):

                graphicsresponse(msg)

            elif op == "FB_SIZE":

                wsapplyfbsize(msg.get("w", 0), msg.get("h", 0))

    if GRAPHICSSTATE.get("pending") or GRAPHICSSTATE.get("need_submit"):

        graphicsdisable("initial managed graphics scene did not commit")

        if not GRAPHICSSTATE.get("available"):

            try:

                wssend({"op": "GRAPHICS_CLEAR", "winid": int(WINID)})

            except Exception:

                pass

            graphicsdamage()

    return bool(GRAPHICSSTATE.get("active"))


def wsmapready():

    global WINMAPPED

    if WINMAPPED or not WINID:
        return bool(WINMAPPED)

    graphicswaitinitial()
    if not wssend({"op": "MAP", "winid": int(WINID)}):
        log("window server map request could not be queued")
        return False
    WINMAPPED = True
    return True


def waitwindowmapped(timeout=2.0):

    global WSDEFERREDMSGS

    deadline = time.monotonic() + max(0.1, float(timeout))
    nextmap = 0.0

    while time.monotonic() < deadline:
        now = time.monotonic()
        if WINID and now >= nextmap:
            # MAP is idempotent. Retrying closes the remaining nonblocking
            # socket race while the acknowledgement remains the only proof
            # that the form is visible and eligible for focus.
            wssend({"op": "MAP", "winid": int(WINID)})
            nextmap = now + 0.25

        messages = list(WSDEFERREDMSGS)
        WSDEFERREDMSGS = []

        for line in wsrecvlines(timeout=0.05):
            try:
                messages.append(json.loads(line))
            except Exception:
                continue

        for message in messages:
            if wsmanagedresponse(message):
                continue
            if (
                message.get("op") == "WINDOW_MAPPED"
                and int(message.get("winid", 0)) == int(WINID or 0)
            ):
                return True
            WSDEFERREDMSGS.append(message)

    return False


def clearloginready():

    try:
        os.unlink(LOGINREADYPATH)
    except FileNotFoundError:
        pass
    except OSError as error:
        log(f"could not clear login-ready state {error}")


def writeloginready(username):

    temporary = f"{LOGINREADYPATH}.{os.getpid()}.new"

    try:
        os.makedirs(MASTERIMAGECACHEBASE, mode=0o700, exist_ok=True)
        with open(temporary, "w", encoding="utf-8") as stream:
            json.dump({
                "format": 1,
                "state": "ready",
                "pid": int(os.getpid()),
                "winid": int(WINID or 0),
                "username": str(username),
            }, stream, sort_keys=True, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, LOGINREADYPATH)
        return True
    except OSError as error:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        log(f"could not publish login-ready state {error}")
        return False


def graphicsscaledisplay(oldw, oldh, neww, newh):

    global GRAPHICSDISPLAYLIST

    try:

        scale, offsetx, offsety = graphicsresizetransform(oldw, oldh, neww, newh)
        output = []

        for index, item in enumerate(GRAPHICSDISPLAYLIST):

            command = dict(item.get("command", {}))
            bounds = list(item.get("bounds", [0, 0, 0, 0]))

            if index == 0 and command.get("kind") == "rectangle":

                command["rect"] = [0, 0, int(neww), int(newh)]
                command["clip"] = [0, 0, int(neww), int(newh)]
                output.append({"command": command, "bounds": [0, 0, int(neww), int(newh)]})
                continue

            if command.get("kind") == "rectangle":

                x, y, width, height = command.get("rect", [0, 0, 0, 0])
                command["rect"] = [
                    int(round(offsetx + (float(x) * scale))),
                    int(round(offsety + (float(y) * scale))),
                    max(1, int(round(float(width) * scale))),
                    max(1, int(round(float(height) * scale))),
                ]

            elif command.get("kind") == "text":

                command["x"] = int(round(offsetx + (float(command.get("x", 0)) * scale)))
                command["y"] = int(round(offsety + (float(command.get("y", 0)) * scale)))
                command["size"] = max(12, int(round(float(command.get("size", 12)) * scale)))

            elif command.get("kind") == "image":

                x, y, width, height = command.get("rect", [0, 0, 0, 0])
                command["rect"] = [
                    int(round(offsetx + (float(x) * scale))),
                    int(round(offsety + (float(y) * scale))),
                    max(1, int(round(float(width) * scale))),
                    max(1, int(round(float(height) * scale))),
                ]

            command["clip"] = [0, 0, int(neww), int(newh)]
            scaledbounds = [
                int(round(offsetx + (float(bounds[0]) * scale))),
                int(round(offsety + (float(bounds[1]) * scale))),
                max(1, int(round(float(bounds[2]) * scale))),
                max(1, int(round(float(bounds[3]) * scale))),
            ]
            scaled = {"command": command, "bounds": scaledbounds}

            if "cpu_y" in item:
                scaled["cpu_y"] = int(round(offsety + (float(item.get("cpu_y", 0)) * scale)))

            output.append(scaled)

        GRAPHICSDISPLAYLIST = output

    except Exception:

        pass


def graphicsresizetransform(oldw, oldh, neww, newh):

    oldwidth = float(max(1, int(oldw)))
    oldheight = float(max(1, int(oldh)))
    newwidth = float(max(1, int(neww)))
    newheight = float(max(1, int(newh)))
    scale = min(newwidth / oldwidth, newheight / oldheight)
    offsetx = (newwidth - (oldwidth * scale)) * 0.5
    offsety = (newheight - (oldheight * scale)) * 0.5
    return scale, offsetx, offsety


def graphicsreplaycpu():

    try:

        resetdirty()
        _cpuclear(BACKGROUNDCOLOUR)

        for index, item in enumerate(GRAPHICSDISPLAYLIST):

            command = item.get("command", {})
            kind = command.get("kind")

            if kind == "rectangle":

                if index == 0 and command.get("rect") == [0, 0, int(SCREEN_W), int(SCREEN_H)]:
                    continue

                x, y, width, height = command.get("rect", [0, 0, 0, 0])
                fillrectfast(int(x), int(y), int(width), int(height), int(command.get("color", BACKGROUNDCOLOUR)))

            elif kind == "text":

                _cpudrawtextttf(
                    int(command.get("x", 0)),
                    int(item.get("cpu_y", command.get("y", 0))),
                    str(command.get("text", "")),
                    int(command.get("color", TEXTCOLOUR)),
                    int(command.get("size", FONTSIZE)),
                    fontpath=command.get("font", FONTFILE),
                    clip=command.get("clip"),
                )

            elif kind == "image":

                x, y, width, height = command.get(
                    "rect", [0, 0, 0, 0])
                blitfilescaledfast(
                    command.get("path", ""),
                    int(command.get("source_width", 0)),
                    int(command.get("source_height", 0)),
                    int(x),
                    int(y),
                    int(width),
                    int(height),
                    str(command.get("format", "BGRA32")),
                )

    except Exception as e:

        log(f"graphics CPU replay error {e}")


# window server functions
def wsconnect(wait_s=6.0, retry_s=0.10):

    global WSSOCK
    global WSRXBUF

    deadline = time.time() + float(wait_s)

    last_reason = ""

    while time.time() < deadline:

        try:

            # create socket
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

        except Exception as e:

            # socket create error
            last_reason = f"socket create error {e}"
            log(last_reason)

            time.sleep(retry_s)
            continue

        try:

            # connect
            s.connect(WINSOCKPATH)

        except FileNotFoundError:

            # window server socket not ready yet
            last_reason = "window server socket not found"
            log(last_reason)

            s.close()
            time.sleep(retry_s)
            continue

        except ConnectionRefusedError:

            # window server not accepting yet
            last_reason = "window server refused connection"
            log(last_reason)

            s.close()
            time.sleep(retry_s)
            continue

        except Exception as e:

            # other connect errors
            last_reason = f"window server connect error {e}"
            log(last_reason)

            s.close()
            time.sleep(retry_s)
            continue

        try:

            # non-blocking
            s.setblocking(False)

            # store
            WSSOCK = s
            WSRXBUF = ""

        except Exception as e:

            # setblocking/store error
            last_reason = f"window server setup error {e}"
            log(last_reason)

            s.close()
            time.sleep(retry_s)
            continue

        try:

            # register selector
            WSSEL.register(WSSOCK, selectors.EVENT_READ)

        except Exception as e:

            # selector register error
            last_reason = f"window server selector register error {e}"
            log(last_reason)

            s.close()
            WSSOCK = None

            time.sleep(retry_s)
            continue

        try:

            # hello
            wssend({"op": "HELLO"})

        except Exception as e:

            # hello send error
            last_reason = f"window server hello error {e}"
            log(last_reason)

            s.close()
            WSSOCK = None

            time.sleep(retry_s)
            continue

        return True

    if last_reason:
        log(f"window server connect timeout {last_reason}")
    else:
        log("window server connect timeout")

    return False


def wsclose():

    global WSSOCK, WSRXBUF, WSDEFERREDMSGS, WINMAPPED

    try:

        if WSSOCK is not None:
            WSSEL.unregister(WSSOCK)

    except Exception:

        pass

    try:

        if WSSOCK is not None:
            WSSOCK.close()

    except Exception:

        pass

    WSSOCK = None
    WSRXBUF = ""
    WSDEFERREDMSGS = []
    WINMAPPED = False

    try:

        if os.path.isfile(MASTERIMAGECACHEPATH):
            os.unlink(MASTERIMAGECACHEPATH)

    except Exception:

        pass


def resetsessionwindow():

    global WINID, WINBUF_PATH, WINMAPPED

    wsclose()
    WINID = None
    WINBUF_PATH = None
    WINMAPPED = False


def wssend(obj):

    try:

        if WSSOCK is None:
            return False

        line = json.dumps(obj) + "\n"
        payload = line.encode("utf-8")
        sent = WSSOCK.send(payload)

        if int(sent) != len(payload):

            log(f"window server short send {int(sent)}/{len(payload)}")
            return False

        return True

    except BlockingIOError:

        return False

    except Exception as e:

        log(f"window server send error {e}")
        return False


def wspresent():

    global WINID

    try:

        # capture dirty region before we present
        rect = getdirty()

    except Exception:

        rect = None

    managedonly = bool(
        GRAPHICSSTATE.get("available") and managedstrict(GRAPHICSSTATE)
    )
    retainedrect = graphicsgetdirty()

    if managedonly:

        # Managed-only drawing does not touch the CPU backbuffer, so its dirty
        # area comes from the retained display-list mutations rather than the
        # graphics module's CPU dirty tracker.
        rect = retainedrect

    else:

        if rect is None:
            rect = retainedrect

        # Input fields dirty only a narrow text strip. Copy that region into
        # the window mapping instead of rewriting the complete full-screen
        # buffer for every character or password bullet.
        if rect:
            presentdirty(*rect)

    if rect:

        managed = graphicspresent(rect)

    else:

        managed = graphicspump()

    # no dirty area -> nothing to notify
    if not rect:

        resetdirty()
        graphicsresetdirty()
        return

    x, y, w, h = rect

    if w <= 0 or h <= 0:

        resetdirty()
        graphicsresetdirty()
        return


    if not managed:

        # notify windowserver that this CPU window region changed
        wssend({
            "op": "DAMAGE",
            "winid": int(WINID),
            "rect": [int(x), int(y), int(w), int(h)]
        })


    # reset dirty tracking for next frame
    resetdirty()
    graphicsresetdirty()

def wsrecvlines(timeout=0.01):

    global WSRXBUF

    out = []

    try:

        events = WSSEL.select(timeout)

        if not events:
            return out

        for key, mask in events:

            if mask & selectors.EVENT_READ:

                try:

                    chunk = WSSOCK.recv(65536)

                except BlockingIOError:

                    continue

                if not chunk:
                    return out

                WSRXBUF += chunk.decode("utf-8", errors="ignore")

    except Exception:
        return out

    while "\n" in WSRXBUF:

        ln, WSRXBUF = WSRXBUF.split("\n", 1)

        ln = ln.strip()

        if ln:
            out.append(ln)

    return out


def wsmanagedresponse(msg):

    global ANIMATIONCOMMITACKS

    try:
        operation = str(msg.get("op", ""))
    except Exception:
        return False

    if (
        operation not in ("GRAPHICS_COMMITTED", "GRAPHICS_CLEARED") and
        not (
            operation == "ERROR" and
            str(msg.get("code", "")).startswith("graphics_")
        )
    ):
        return False

    handled = graphicsresponse(msg)

    if (
        operation == "GRAPHICS_COMMITTED"
        and handled
        and bool(msg.get("presented", True))
    ):
        ANIMATIONCOMMITACKS += 1

    return True


def wsanimationpump(timeout=0.0):

    global WSDEFERREDMSGS

    handled = 0

    for line in wsrecvlines(timeout=max(0.0, float(timeout))):

        try:
            msg = json.loads(line)
        except Exception:
            continue

        if wsmanagedresponse(msg):

            handled += 1
            continue

        WSDEFERREDMSGS.append(msg)

    if len(WSDEFERREDMSGS) > 512:
        WSDEFERREDMSGS = WSDEFERREDMSGS[-512:]

    # An acknowledgement can release a newer scene accumulated while the
    # preceding frame was pending. Submit that newest state immediately.
    if (
        GRAPHICSSTATE.get("available") and
        not GRAPHICSSTATE.get("pending") and
        GRAPHICSSTATE.get("need_submit")
    ):
        graphicspump()

    return handled


def graphicspresentationbarrier(timeout=1.0, report_failure=True):

    if not GRAPHICSSTATE.get("available"):
        # A session that began on the CPU path has no managed receipt to wait
        # for. Losing an already-negotiated managed path is different: its
        # failure reason is retained by manageddisable(), so the caller must
        # preserve the last verified frame and abort rather than treating the
        # fallback as proof of presentation.
        return not bool(GRAPHICSSTATE.get("presentation_reason", ""))

    deadline = time.monotonic() + max(0.05, float(timeout))

    while (
        GRAPHICSSTATE.get("available")
        and (
            GRAPHICSSTATE.get("pending")
            or GRAPHICSSTATE.get("need_submit")
        )
        and time.monotonic() < deadline
    ):
        wsanimationpump(
            min(0.01, max(0.0, deadline - time.monotonic()))
        )

    completed = bool(
        GRAPHICSSTATE.get("available")
        and not GRAPHICSSTATE.get("pending")
        and not GRAPHICSSTATE.get("need_submit")
        and GRAPHICSSTATE.get("presented", False)
    )

    if not completed and report_failure:
        log(
            f"{timestamp()} [startup] managed presentation barrier failed "
            f"available={bool(GRAPHICSSTATE.get('available'))} "
            f"pending={bool(GRAPHICSSTATE.get('pending'))} "
            f"queued={bool(GRAPHICSSTATE.get('need_submit'))} "
            f"presented={bool(GRAPHICSSTATE.get('presented'))} "
            f"reason={str(GRAPHICSSTATE.get('presentation_reason', ''))}"
        )

    return completed


def wspresentinput(timeout=0.05):

    # Interactive fields mutate a retained scene while the preceding scene may
    # still be awaiting its physical presentation receipt. Pump that receipt
    # and the newest coalesced scene now, rather than leaving the visible field
    # one character behind until the next input iteration. wsanimationpump()
    # preserves any keys/text that arrive during this bounded wait in
    # WSDEFERREDMSGS for readcharsws().
    wspresent()

    if GRAPHICSSTATE.get("available"):
        graphicspresentationbarrier(
            timeout=max(0.0, float(timeout)),
            report_failure=False,
        )


def animationwaituntil(deadline):

    deadline = float(deadline)

    while True:

        remaining = deadline - time.monotonic()

        if remaining <= 0.0:

            wsanimationpump(0.0)
            return

        wsanimationpump(min(0.005, remaining))


def animationprogress(started, duration, now=None):

    duration = max(0.0, float(duration))

    if duration <= 0.0:
        return 1.0

    if now is None:
        now = time.monotonic()

    started = float(started)
    now = float(now)

    if now <= started:
        return 0.0

    if now >= started + duration:
        return 1.0

    return max(0.0, min(1.0, (now - started) / duration))


def animationtimeline(duration):

    duration = max(0.0, float(duration))
    started = time.monotonic()
    deadline = started + duration
    frameindex = 0

    while True:

        target = min(deadline, started + (frameindex * ANIMATIONFRAMETIME))

        if target > time.monotonic():
            animationwaituntil(target)
        else:
            wsanimationpump(0.0)

        now = time.monotonic()
        progress = animationprogress(started, duration, now)
        yield progress

        if progress >= 1.0:
            return

        elapsedframes = int(max(0.0, now - started) / ANIMATIONFRAMETIME)
        frameindex = max(frameindex + 1, elapsedframes + 1)


def waitbufferready(path, w, h, timeout=1.0):

    try:

        required = int(w) * int(h) * 4

    except Exception:

        return False

    deadline = time.monotonic() + max(0.05, float(timeout))

    while time.monotonic() < deadline:

        try:

            if os.path.getsize(path) >= required:

                return True

        except Exception:

            pass

        time.sleep(0.005)

    return False


def wsnotefbsize(w, h):

    global SCREEN_W, SCREEN_H

    try:

        w = int(w)

        h = int(h)

    except Exception:

        return False

    if w < 1 or h < 1:

        return False

    changed = w != SCREEN_W or h != SCREEN_H

    SCREEN_W = w

    SCREEN_H = h

    if changed:

        updatelayout()

    return changed


def wscreatewindow():

    global WINID, WINBUF_PATH, WINMAPPED

    requestedw = int(SCREEN_W)

    requestedh = int(SCREEN_H)

    try:

        # request window (role != 'window' => borderless by policy)
        wssend({
            "op": "CREATE_WINDOW",
            "w": int(SCREEN_W),
            "h": int(SCREEN_H),
            "x": 0,
            "y": 0,
            "title": WINTITLE,
            "role": WINROLE,
            "pid": os.getpid(),
            "path": STARTUPSCRIPT,
        })

    except Exception as e:

        log(f"create window send error {e}")
        return False

    # A full-screen buffer allocation can temporarily be delayed while the GPU
    # compositor is presenting the preceding system surface. Keep the current
    # surface visible while waiting for the explicit creation acknowledgement.
    deadline = time.monotonic() + WINDOWCREATETIMEOUT

    while time.monotonic() < deadline:

        lines = wsrecvlines(timeout=0.02)

        for ln in lines:

            try:

                msg = json.loads(ln)

            except Exception:

                continue

            if msg.get("op") == "FB_SIZE":

                wsnotefbsize(msg.get("w", 0), msg.get("h", 0))

                continue

            if msg.get("op") == "WINDOW_CREATED":

                try:
                    WINID = int(msg.get("winid", 0))
                except Exception:
                    WINID = 0

                WINBUF_PATH = msg.get("buffer")

        if WINID and WINBUF_PATH:
            break

    if not WINID or not WINBUF_PATH:

        log("window server did not create window")
        return False

    WINMAPPED = False

    if int(SCREEN_W) != requestedw or int(SCREEN_H) != requestedh:

        wssend({"op": "RESIZE", "winid": int(WINID), "w": int(SCREEN_W), "h": int(SCREEN_H)})

        if not waitbufferready(WINBUF_PATH, SCREEN_W, SCREEN_H):

            log(f"window buffer did not grow for initial framebuffer {SCREEN_W}x{SCREEN_H}")

            return False

    return True


def wsapplyfbsize(w, h):

    global SCREEN_W, SCREEN_H, WINID, WINBUF_PATH, FONTSIZE

    oldw = int(SCREEN_W)

    oldh = int(SCREEN_H)

    if not wsnotefbsize(w, h):

        return False

    # Keep subsequent input and error rendering at the same scale as the
    # retained scene reconstructed below.
    FONTSIZE = scs(FONTSIZE_BASE)

    if WINID:

        # ask windowserver to resize our window to match framebuffer
        wssend({"op": "RESIZE", "winid": int(WINID), "w": int(SCREEN_W), "h": int(SCREEN_H)})

        # re-map / re-size our framebuffer view to the new logical size
        if WINBUF_PATH:

            if not waitbufferready(WINBUF_PATH, SCREEN_W, SCREEN_H):

                log(f"window buffer did not grow for framebuffer {SCREEN_W}x{SCREEN_H}")

                return False

            initbuffer(WINBUF_PATH, SCREEN_W, SCREEN_H)

            graphicsscaledisplay(oldw, oldh, SCREEN_W, SCREEN_H)

            graphicsreplaycpu()

            present()

            managedmarkdamage(GRAPHICSSTATE, [0, 0, int(SCREEN_W), int(SCREEN_H)], bounds=(int(SCREEN_W), int(SCREEN_H)))

            graphicspump()

            if not GRAPHICSSTATE.get("active"):
                graphicsdamage()

            resetdirty()
            graphicsresetdirty()

    return True


def wswaitwelcome(wait_s=1.5):

    global SCREEN_W, SCREEN_H, GRAPHICSCAPS

    deadline = time.time() + float(wait_s)

    while time.time() < deadline:

        lines = wsrecvlines(timeout=0.05)

        if not lines:
            continue

        for ln in lines:

            try:

                msg = json.loads(ln)

            except Exception:

                continue

            if msg.get("op") != "WELCOME":
                continue

            fb = msg.get("fb", {})

            try:
                w = int(fb.get("w", 0))

                h = int(fb.get("h", 0))

            except Exception:

                w = 0

                h = 0

            if w > 0 and h > 0:

                SCREEN_W = w

                SCREEN_H = h

            try:

                GRAPHICSCAPS = dict(msg.get("graphics", {}))

            except Exception:

                GRAPHICSCAPS = {}

            graphicsconfigure(GRAPHICSCAPS)

            return True

    return False


def wssubscribefbsize():

    try:

        wssend({"op": "SUBSCRIBE", "types": ["fbsize"]})

    except Exception:

        return False

    sawok = False

    sawfbsize = False

    deadline = time.monotonic() + 0.75

    while time.monotonic() < deadline:

        lines = wsrecvlines(timeout=0.05)

        for ln in lines:

            try:

                msg = json.loads(ln)

            except Exception:

                continue

            op = msg.get("op")

            if op == "OK" and msg.get("ref") == "SUBSCRIBE":

                sawok = True

            elif op == "FB_SIZE":

                wsnotefbsize(msg.get("w", 0), msg.get("h", 0))

                sawfbsize = True

            elif op == "ERROR":

                return False

        if sawok and sawfbsize:

            return True

    return sawok


def readcharsws(timeout_ms=10):

    global WSDEFERREDMSGS, CAPSLOCKON

    deadline = time.monotonic() + (timeout_ms / 1000.0)

    chars = []

    while time.monotonic() < deadline:

        messages = list(WSDEFERREDMSGS)
        WSDEFERREDMSGS = []

        for line in wsrecvlines(timeout=0.001):

            try:
                messages.append(json.loads(line))
            except Exception:
                continue

        if not messages:
            continue

        for msg in messages:

            op = msg.get("op")

            if op == "FB_SIZE":

                wsapplyfbsize(msg.get("w", 0), msg.get("h", 0))

                continue

            if wsmanagedresponse(msg):

                continue

            if op == "EVENT":

                kind = msg.get("kind")

                if kind == "text":

                    t = msg.get("text", "")
                    if isinstance(t, str) and t:
                        chars.append(t)

                elif kind == "key":

                    key = msg.get("key", "")
                    state = msg.get("state", "")
                    mods = msg.get("mods", {})

                    if isinstance(mods, dict) and "caps" in mods:
                        CAPSLOCKON = bool(mods.get("caps"))

                    # Backspace is the only repeatable key in these append-only
                    # startup/login fields. Keep Enter and Escape edge-triggered
                    # so holding either key cannot submit or clear more than once.
                    if state not in ("down", "repeat"):
                        continue

                    if state == "repeat" and key != "BACKSPACE":
                        continue

                    if key == "ENTER":
                        chars.append("\n")

                    elif key == "BACKSPACE":
                        chars.append("\b")

                    elif key == "ESC":
                        chars.append("\x1b")

                continue

            if op == "TEXT":

                t = msg.get("text", "")
                if isinstance(t, str) and t:
                    chars.append(t)

                continue

            if op == "KEY":

                key = msg.get("key", "")
                state = msg.get("state", "")
                mods = msg.get("mods", {})

                if isinstance(mods, dict) and "caps" in mods:
                    CAPSLOCKON = bool(mods.get("caps"))

                # The legacy KEY envelope follows the same repeat contract as
                # EVENT/key above.
                if state not in ("down", "repeat"):
                    continue

                if state == "repeat" and key != "BACKSPACE":
                    continue

                if key == "ENTER":
                    chars.append("\n")

                elif key == "BACKSPACE":
                    chars.append("\b")

                elif key == "ESC":
                    chars.append("\x1b")

                continue

        # If input and a managed-graphics acknowledgement arrive together,
        # let the field update its retained text before submitting again.
        # Pumping here used to submit the previous field contents, leaving the
        # visible text or password bullets one keystroke behind.
        if chars:
            return chars

        if (
            GRAPHICSSTATE.get("available") and
            not GRAPHICSSTATE.get("pending") and
            GRAPHICSSTATE.get("need_submit")
        ):
            graphicspump()

    return chars


# hashing functions
def hashpw(pw):
    """Compatibility wrapper around the central credential broker."""
    try:
        return authbroker.hash_password(pw)
    except Exception as e:
        log(f'{timestamp()} [startup] error deriving password hash {type(e).__name__}')
        return ''


def verifypw(pw, stored):
    """Compatibility wrapper; interactive logins use broker throttling below."""
    return authbroker.verify_password(pw, stored)


def pbkdf2hmac(name, password, salt, iterations, dklen=None):
    """Strict legacy helper retained for callers migrating old credentials."""
    if (
        name != authbroker.LEGACY_PBKDF2_ALGORITHM
        or iterations != authbroker.LEGACY_PBKDF2_ITERATIONS
        or not isinstance(password, (bytes, bytearray))
        or not isinstance(salt, (bytes, bytearray))
        or len(password) > authbroker.MAX_PASSWORD_BYTES
        or len(salt) != 16
        or dklen not in (None, 32)
    ):
        return b''
    return hashlib.pbkdf2_hmac(name, bytes(password), bytes(salt), iterations, dklen=32)


# user functions
def ensureusersfile():
    try:
        authbroker.ensure_private_file(MASTERFILE)
    except PermissionError:
        log(f'{timestamp()} [startup] permission denied creating master tier')
        return
    except Exception as e:
        log(f'{timestamp()} [startup] error creating master tier {type(e).__name__}')
        return


def userexists():

    # ensure master file exists
    ensureusersfile()

    try:

        # open master file
        with open(MASTERFILE, "r") as uf:

            # isolate user variable
            return any(":" in line.strip() for line in uf)

    except FileNotFoundError as e:

        # master file not found error
        log(f'{timestamp()} [startup] master file not found')
        return False

    except PermissionError as e:

        # permission denied error
        log(f'{timestamp()} [startup] permission denied to read the master file')
        return False

    except Exception as e:

        # other errors
        log(f'{timestamp()} [startup] error reading the master file {e}')
        return False


def setupusergeometry():

    # setupuser can remain alive across FB_SIZE events, so derive every
    # account-form coordinate from the current framebuffer on demand.
    font_size = scs(FONTSIZE_BASE)
    title = "Welcome to The One OS"
    success_sample = "master username has been created successfully"
    label_name = "what is your name?"
    prompt_pwd = "enter password"
    prompt_cnf = "confirm password"
    title_y = scy(360)
    name_y = scy(540)
    # Gaps are distances, not absolute Y coordinates.  Using scy here would
    # add OFFY to every gap on letterboxed aspect ratios.
    line_gap = scs(60)
    pwd_y = name_y + line_gap
    confirm_y = pwd_y + line_gap
    success_y = confirm_y + (pwd_y - title_y) - scs(30)

    # Translate the complete form as one unit so its visible top and bottom
    # edges have equal margins.  Use the real glyph bounds because the title
    # and success message use different fonts.
    title_top, title_bottom = ttfbbox(title, font_size, fontpath=BRANDFONT)
    success_top, success_bottom = ttfbbox(
        success_sample, font_size, fontpath=FONTFILE)

    if title_bottom <= title_top:
        title_top, title_height = ttflinebox(
            font_size, fontpath=BRANDFONT)
        title_bottom = title_top + title_height

    if success_bottom <= success_top:
        success_top, success_height = ttflinebox(
            font_size, fontpath=FONTFILE)
        success_bottom = success_top + success_height

    content_top = title_y + title_top
    content_bottom = success_y + success_bottom
    vertical_shift = (
        ((SCREEN_H - (content_bottom - content_top)) // 2) - content_top)
    title_y += vertical_shift
    name_y += vertical_shift
    pwd_y += vertical_shift
    confirm_y += vertical_shift
    success_y += vertical_shift
    content_top += vertical_shift
    content_bottom += vertical_shift

    space_w = measuretext(" ", font_size)
    base_input_x = (SCREEN_W // 2) + (space_w // 2)

    return {
        "font_size": font_size,
        "title": title,
        "title_y": title_y,
        "title_x": (SCREEN_W - measuretext(title, font_size, BRANDFONT)) // 2,
        "label_name": label_name,
        "name_y": name_y,
        "label_x": base_input_x - measuretext(label_name, font_size),
        "input_x": base_input_x + scs(20),
        "pwd_y": pwd_y,
        "pwd_label_x": base_input_x - measuretext(prompt_pwd, font_size),
        "prompt_pwd": prompt_pwd,
        "confirm_y": confirm_y,
        "confirm_label_x": base_input_x - measuretext(prompt_cnf, font_size),
        "prompt_cnf": prompt_cnf,
        "success_y": success_y,
        "content_top": content_top,
        "content_bottom": content_bottom,
        "error_pad": scs(30),
    }


def redrawsetupuser(layout, username="", password_length=None,
                    confirmation_length=None):

    # Rebuild the form from semantic state.  Scaling the retained scene is not
    # sufficient if setupuser then draws a new field using pre-resize locals.
    font_size = layout["font_size"]
    clear(BACKGROUNDCOLOUR)
    drawtextttf(layout["title_x"], layout["title_y"], layout["title"],
                TEXTCOLOUR, font_size, BRANDFONT)
    drawtextttf(layout["label_x"], layout["name_y"], layout["label_name"],
                TEXTCOLOUR, font_size)

    if username:
        drawtextttf(layout["input_x"], layout["name_y"], username,
                    TEXTCOLOUR, font_size)

    if password_length is not None:
        drawtextttf(layout["pwd_label_x"], layout["pwd_y"],
                    layout["prompt_pwd"], TEXTCOLOUR, font_size)
        if password_length:
            drawtextttf(layout["input_x"], layout["pwd_y"],
                        "•" * int(password_length), TEXTCOLOUR, font_size)

    if confirmation_length is not None:
        drawtextttf(layout["confirm_label_x"], layout["confirm_y"],
                    layout["prompt_cnf"], TEXTCOLOUR, font_size)
        if confirmation_length:
            drawtextttf(layout["input_x"], layout["confirm_y"],
                        "•" * int(confirmation_length), TEXTCOLOUR, font_size)

    wspresent()


def animatewelcometitle(layout):

    title = str(layout["title"])
    font_size = int(layout["font_size"])
    title_x = int(layout["title_x"])
    title_y = int(layout["title_y"])
    title_width = max(1, int(measuretext(title, font_size, BRANDFONT)))
    title_yoff, title_height = ttflinebox(
        font_size,
        fontpath=BRANDFONT,
    )
    title_top = title_y + int(title_yoff)
    title_height = max(1, int(title_height))
    title_pad = max(2, scs(2))
    duration = max(
        ANIMATIONFRAMETIME,
        len(title) * TITLECHARACTERTIME,
    )
    frames = 0
    visiblecharacters = -1

    # A write-out effect advances by complete glyphs. A continuously widening
    # clip reads as a linear wipe, especially through the middle of wide
    # letters, so retain 60 Hz event/commit pumping while only repainting when
    # the next complete character becomes due.
    for progress in animationtimeline(duration):

        nextvisible = max(
            0,
            min(
                len(title),
                (int(progress * len(title)) + 1) if title else 0,
            ),
        )

        if progress >= 1.0:
            nextvisible = len(title)

        if nextvisible == visiblecharacters:
            continue

        visiblecharacters = nextvisible
        fillrect(
            title_x - title_pad,
            title_top - title_pad,
            title_width + (title_pad * 2),
            title_height + (title_pad * 2),
            BACKGROUNDCOLOUR,
        )

        if visiblecharacters > 0:

            drawtextttf(
                title_x,
                title_y,
                title[:visiblecharacters],
                TEXTCOLOUR,
                font_size,
                BRANDFONT,
            )

        wspresent()
        frames += 1

    return frames


def animatesetuplabel(layout):

    label = str(layout["label_name"])
    font_size = int(layout["font_size"])
    label_x = int(layout["label_x"])
    label_y = int(layout["name_y"])
    label_width = max(1, int(measuretext(label, font_size)))
    label_yoff, label_height = ttflinebox(
        font_size,
        fontpath=FONTFILE,
    )
    label_top = label_y + int(label_yoff)
    label_height = max(1, int(label_height))
    red = (TEXTCOLOUR >> 16) & 0xFF
    green = (TEXTCOLOUR >> 8) & 0xFF
    blue = TEXTCOLOUR & 0xFF
    frames = 0

    for progress in animationtimeline(LABELFADETIME):

        intensityred = int(round(red * progress))
        intensitygreen = int(round(green * progress))
        intensityblue = int(round(blue * progress))
        color = (
            (intensityred << 16) |
            (intensitygreen << 8) |
            intensityblue
        )
        fillrect(
            label_x,
            label_top,
            label_width,
            label_height,
            BACKGROUNDCOLOUR,
        )
        drawtextttf(
            label_x,
            label_y,
            label,
            color,
            font_size,
            FONTFILE,
        )
        wspresent()
        frames += 1

    return frames


def setupuser():

    try:

        if not wsconnect():
            return None

        wswaitwelcome()

        updatelayout()

        wssubscribefbsize()

        if not wscreatewindow():
            return None

        initbuffer(WINBUF_PATH, SCREEN_W, SCREEN_H)

        updatelayout()

        # load the truetype font face at the scaled size
        initttffont(FONTFILE, scs(FONTSIZE_BASE))

        # set the initial empty dirty-rectangle state
        resetdirty()
        graphicsresetdirty()

    # catch any display/font initialization failure
    except Exception as e:

        # report that display initialization failed
        log(f"display init error {e}")

        # abort user setup
        return None

    # clear the entire screen to the background colour
    clear(BACKGROUNDCOLOUR)

    # expose only the complete opaque first frame
    wspresent()

    wsmapready()

    # Calculate the form from the current framebuffer.  These locals are
    # refreshed again whenever an input loop observes a resize.
    layout = setupusergeometry()
    FONTSIZE = layout["font_size"]
    animationacksbefore = int(ANIMATIONCOMMITACKS)
    titleframes = animatewelcometitle(layout)

    if not graphicspresentationbarrier():
        log(
            f"{timestamp()} [startup] aborting first-run setup because "
            "the completed welcome title was not presented"
        )
        return None

    try:

        # ensure that the users/master file(s) exist before proceeding
        ensureusersfile()

    except PermissionError:

        # permission denied error ensuring users file
        log(f'{timestamp()} [startup] permission denied ensuring users file')
        return None

    except Exception as e:

        # other error ensuring users file
        log(f'{timestamp()} [startup] error ensuring users file {e}')
        return None

    NAME_Y = layout["name_y"]
    PWD_Y = layout["pwd_y"]
    CONFIRM_Y = layout["confirm_y"]
    SUCCESS_Y = layout["success_y"]
    ERR_PAD = layout["error_pad"]
    label_name = layout["label_name"]
    input_x = layout["input_x"]

    # compute TTF clear box that matches drawtextttf pixel coverage
    name_yoff, name_h = ttflinebox(FONTSIZE, fontpath=FONTFILE)
    labelframes = animatesetuplabel(layout)

    if not graphicspresentationbarrier():
        log(
            f"{timestamp()} [startup] aborting first-run setup because "
            "the completed account-name label was not presented"
        )
        return None
    log(
        f"{timestamp()} [startup] first-run animation pacing "
        f"target={ANIMATIONREFRESHHZ:.3f}Hz "
        f"title_duration_ms={len(layout['title']) * TITLECHARACTERTIME * 1000.0:.1f} "
        f"title_frames={int(titleframes)} "
        f"label_duration_ms={LABELFADETIME * 1000.0:.1f} "
        f"label_frames={int(labelframes)} "
        f"managed_commits={max(0, int(ANIMATIONCOMMITACKS) - animationacksbefore)}"
    )

    try:

        # open the keyboard input device before reading keys
        kb_ok = True

    except Exception as e:

        # keyboard open error
        log(f'{timestamp()} [startup] error opening keyboard device {e}')
        return None

    if not kb_ok:

        # report that no input device is available
        log(f'{timestamp()} [startup] no input device available')
        return None

    # buffer to collect typed username characters
    uname_buf = []

    # remember last rendered length to avoid redundant redraws
    last_len  = -1

    # Track which framebuffer the local account-form geometry describes.
    layout_w = int(SCREEN_W)
    layout_h = int(SCREEN_H)

    # loop until a valid, non-duplicate username is entered
    username = None
    while True:

        tickerror()

        try:

            # pull any pending keypresses without blocking long
            chars = readcharsws(timeout_ms=10)

        except Exception as e:

            # keyboard read error
            log(f'{timestamp()} [startup] error reading keyboard input {e}')
            return None

        if int(SCREEN_W) != layout_w or int(SCREEN_H) != layout_h:

            layout = setupusergeometry()
            FONTSIZE = layout["font_size"]
            NAME_Y = layout["name_y"]
            PWD_Y = layout["pwd_y"]
            CONFIRM_Y = layout["confirm_y"]
            SUCCESS_Y = layout["success_y"]
            ERR_PAD = layout["error_pad"]
            label_x = layout["label_x"]
            input_x = layout["input_x"]
            name_label_w = measuretext(label_name, FONTSIZE)
            name_yoff, name_h = ttflinebox(FONTSIZE, fontpath=FONTFILE)
            redrawsetupuser(layout, username=''.join(uname_buf))
            layout_w = int(SCREEN_W)
            layout_h = int(SCREEN_H)
            last_len = len(uname_buf)

        # track whether we need to repaint the input field
        redraw = False

        # handle each character event
        for ch in chars:

            # when Enter is pressed, validate and possibly accept the name
            if ch == '\n':

                # collapse the buffer and strip trailing/leading spaces
                username = ''.join(uname_buf).strip()

                # enforce non-empty username
                if not username:

                    username = None

                    err = "master cannot be empty"

                    es = max(12, FONTSIZE // 2)

                    ey = NAME_Y + FONTSIZE + ERR_PAD

                    ex = (SCREEN_W - measuretext(err, es)) // 2

                    showerror(err, ex, ey, es)

                    continue

                try:
                    username = authbroker.canonicalize_username(username)
                except ValueError:
                    username = None
                    err = "use 1-32 letters, numbers, dots, underscores, or hyphens"
                    es = max(12, FONTSIZE // 2)
                    ey = NAME_Y + FONTSIZE + ERR_PAD
                    ex = (SCREEN_W - measuretext(err, es)) // 2
                    showerror(err, ex, ey, es)
                    continue

                # check whether the chosen username already exists
                try:

                    # assume not found until proven otherwise
                    exists = False

                    # open the master file to scan entries
                    with open(MASTERFILE, "r") as uf:

                        # read each line and look for a "username:..." match
                        for line in uf:
                            if ":" in line and line.split(":", 1)[0] == username:
                                exists = True
                                break

                # handle a missing master file
                except FileNotFoundError:

                    # report missing master file
                    log("master file not found");
                    return None

                # handle insufficient permission to read the file
                except PermissionError:

                    # report the permission error
                    log("permission denied to read the master file");
                    return None

                except Exception as e:

                    # other error reading master file
                    log(f'{timestamp()} [startup] error reading master file {e}')
                    return None

                # if a duplicate user was discovered, inform and continue
                if exists:

                    duplicate_username = username
                    username = None

                    err = f"master '{duplicate_username}' already exists"

                    es = max(12, FONTSIZE // 2)

                    ey = NAME_Y + FONTSIZE + ERR_PAD

                    ex = (SCREEN_W - measuretext(err, es)) // 2

                    showerror(err, ex, ey, es)

                    continue

                # leave the input loop now that we have a valid username
                break

            # when Backspace is pressed, delete the last character if any
            if ch == '\b':
                if uname_buf:
                    uname_buf.pop(); redraw = True
                continue

            # when Escape is pressed, clear any current input
            if ch == '\x1b':
                if uname_buf:
                    uname_buf.clear(); redraw = True
                continue

            # accept printable ASCII characters and append to the buffer
            if (
                isinstance(ch, str)
                and len(ch) == 1
                and 32 <= ord(ch) <= 126
                and len(uname_buf) < 32
            ):
                uname_buf.append(ch); redraw = True

        # once username is set (Enter accepted), draw it and proceed
        if username is not None:

            # clear the input field region
            fillrect(input_x, NAME_Y + name_yoff, SCREEN_W - input_x, name_h, BACKGROUNDCOLOUR)

            # draw the accepted username if non-empty
            if username:
                drawtextttf(input_x, NAME_Y, username, TEXTCOLOUR, FONTSIZE)

            # present the updated field
            wspresentinput()

            # break the outer loop to move to password input
            break

        # repaint only when the buffer length actually changed
        if redraw and last_len != len(uname_buf):

            # update the last drawn length tracker
            last_len = len(uname_buf)

            # clear the input field region
            fillrect(input_x, NAME_Y + name_yoff, SCREEN_W - input_x, name_h, BACKGROUNDCOLOUR)

            # draw the current buffer contents
            if uname_buf:
                drawtextttf(input_x, NAME_Y, ''.join(uname_buf), TEXTCOLOUR, FONTSIZE)

            # present the new characters
            wspresentinput()

    # define the password prompt label text
    prompt_pwd  = layout["prompt_pwd"]

    # measure the password label width for right-edge alignment
    pw_w        = measuretext(prompt_pwd, FONTSIZE)

    # align the label's right edge with the name prompt and input column
    pw_label_x  = layout["pwd_label_x"]

    # draw the password label
    drawtextttf(pw_label_x, PWD_Y, prompt_pwd, TEXTCOLOUR, FONTSIZE)

    # present the label
    wspresent()

    if not graphicspresentationbarrier():
        log(
            f"{timestamp()} [startup] aborting first-run setup because "
            "the password prompt was not presented"
        )
        return None

    # loop until a non-empty password is entered
    while True:

        # read a password while constraining bullets to the underline span
        pwd = readpass(
            prompt_text="",
            prompt_x=input_x, prompt_y=PWD_Y,
            master_line_x=input_x, master_line_w=(SCREEN_W - input_x),
            font_size=FONTSIZE, fg_color=TEXTCOLOUR,
            bg_color=BACKGROUNDCOLOUR,
            caps_notice_y=SUCCESS_Y,
        )

        # readpass handles FB_SIZE events while it waits.  Refresh the outer
        # form before validation, retries, or drawing the next prompt.
        layout = setupusergeometry()
        FONTSIZE = layout["font_size"]
        NAME_Y = layout["name_y"]
        PWD_Y = layout["pwd_y"]
        CONFIRM_Y = layout["confirm_y"]
        SUCCESS_Y = layout["success_y"]
        ERR_PAD = layout["error_pad"]
        input_x = layout["input_x"]
        pw_label_x = layout["pwd_label_x"]
        redrawsetupuser(layout, username=username, password_length=len(pwd))

        # accept a password that meets the bounded creation policy
        if authbroker.MIN_NEW_PASSWORD_CHARS <= len(pwd) <= authbroker.MAX_PASSWORD_CHARS:

            # leave the password entry loop
            break

        err = (
            f"password must contain {authbroker.MIN_NEW_PASSWORD_CHARS}-"
            f"{authbroker.MAX_PASSWORD_CHARS} characters"
        )

        es = max(12, FONTSIZE // 2)

        ey = PWD_Y + FONTSIZE + ERR_PAD

        ex = (SCREEN_W - measuretext(err, es)) // 2

        showerror(err, ex, ey, es)

        # clear the password bullet area for the next attempt
        fillrect(input_x, PWD_Y, SCREEN_W - input_x, FONTSIZE, BACKGROUNDCOLOUR)

        # present the cleared field
        wspresent()

    # define the confirmation prompt label
    prompt_cnf  = layout["prompt_cnf"]

    # measure the confirmation label width for right-edge alignment
    cnf_w       = measuretext(prompt_cnf, FONTSIZE)

    # align the label's right edge with the other prompts and input column
    cnf_label_x = layout["confirm_label_x"]

    # draw the confirmation label
    drawtextttf(cnf_label_x, CONFIRM_Y, prompt_cnf, TEXTCOLOUR, FONTSIZE)

    # present the label
    wspresent()

    if not graphicspresentationbarrier():
        log(
            f"{timestamp()} [startup] aborting first-run setup because "
            "the confirmation prompt was not presented"
        )
        return None

    # loop until confirmation matches the first password
    while True:

        # read the confirmation password bullets under the same constraints
        pwd2 = readpass(
            prompt_text="",
            prompt_x=input_x, prompt_y=CONFIRM_Y,
            master_line_x=input_x, master_line_w=(SCREEN_W - input_x),
            font_size=FONTSIZE, fg_color=TEXTCOLOUR,
            bg_color=BACKGROUNDCOLOUR,
            caps_notice_y=SUCCESS_Y,
        )

        # Confirmation may also span several resizes.  Canonicalize the scene
        # before errors, retries, and the final success message.
        layout = setupusergeometry()
        FONTSIZE = layout["font_size"]
        NAME_Y = layout["name_y"]
        PWD_Y = layout["pwd_y"]
        CONFIRM_Y = layout["confirm_y"]
        SUCCESS_Y = layout["success_y"]
        ERR_PAD = layout["error_pad"]
        input_x = layout["input_x"]
        cnf_label_x = layout["confirm_label_x"]
        redrawsetupuser(
            layout, username=username, password_length=len(pwd),
            confirmation_length=len(pwd2))

        # accept if non-empty and matches the original password
        if pwd2 and pwd2 == pwd:

            # leave the confirmation loop on success
            break

        # choose an error depending on mismatch vs empty
        if not pwd2:

            # explicit empty-confirm error
            err = "password cannot be empty"

        else:

            # non-empty but not equal to the original password
            err = "passwords do not match"

        es = max(12, FONTSIZE // 2)

        ey = CONFIRM_Y + FONTSIZE + ERR_PAD

        ex = (SCREEN_W - measuretext(err, es)) // 2

        showerror(err, ex, ey, es)

        # clear the confirm bullet area for re-entry
        fillrect(input_x, CONFIRM_Y, SCREEN_W - input_x, FONTSIZE, BACKGROUNDCOLOUR)

        # present the cleared field
        wspresent()

    # attempt to hash and store the password securely
    try:

        # compute a stored representation from the plaintext password
        stored = hashpw(pwd)

        # if hashing/storage failed in any way, report and abort
        if not stored:

            err = "error storing password"

            es = max(12, FONTSIZE // 2)

            ey = CONFIRM_Y + FONTSIZE + ERR_PAD

            ex = (SCREEN_W - measuretext(err, es)) // 2

            showerror(err, ex, ey, es)

            return None

    # catch unexpected hashing errors and abort
    except Exception as e:

        # report the hashing error
        log(f"error hashing password {e}")

        # abort user creation
        return None

    # write the new master entry to the master file and create directories
    try:

        # Create the home tree using descriptor-relative, no-follow traversal.
        authbroker.ensure_user_tree(
            HOME_BASE, username, owner_uid=1000, owner_gid=1000)

        # Commit credentials atomically through a no-follow 0600 broker write.
        authbroker.atomic_write_credentials(MASTERFILE, username, stored)

    # on permission error, report and abort
    except PermissionError:

        # report that we could not write the master file
        log("permission denied to write to the master file"); return None

    # on any other IO error, report and abort
    except Exception as e:

        # report the write failure
        log(f"error writing to the master file {e}"); return None

    # build a success message naming the created master
    success = f"master {username} has been created successfully"

    # measure width of success text for centering
    sw = measuretext(success, FONTSIZE)

    # compute centered x coordinate
    sx = (SCREEN_W - sw) // 2

    # use the success baseline calculated from the setup screen's spacing
    sy = SUCCESS_Y

    try:

        # clear the success line area to background
        fillrect(0, sy, SCREEN_W, FONTSIZE, BACKGROUNDCOLOUR)

        # draw the success message
        drawtextttf(sx, sy, success, TEXTCOLOUR, FONTSIZE)

        # present the success message
        wspresent()

        if not graphicspresentationbarrier():
            log(
                f"{timestamp()} [startup] aborting first-run setup because "
                "the account-creation confirmation was not presented"
            )
            return None

    except Exception as e:

        # display error drawing success message
        log(f'{timestamp()} [startup] display error drawing success message {e}')
        return None

    # hold the message on screen briefly
    time.sleep(3)

    # return the created username to the caller
    return username


def sessionusername():

    descriptor = os.open(
        SESSIONIDENTITYFILE,
        os.O_RDONLY | getattr(os, 'O_CLOEXEC', 0) |
        getattr(os, 'O_NOFOLLOW', 0),
    )
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode) or
            metadata.st_uid != 0 or metadata.st_gid != 1000 or
            stat.S_IMODE(metadata.st_mode) != 0o640 or
            metadata.st_nlink != 1 or
            metadata.st_size > SESSIONIDENTITYMAXBYTES
        ):
            raise PermissionError('unsafe session identity')
        raw = os.read(descriptor, SESSIONIDENTITYMAXBYTES + 1)
    finally:
        os.close(descriptor)
    identity = json.loads(raw.decode('utf-8', errors='strict'))
    if (
        not isinstance(identity, dict) or
        set(identity) != {'format', 'username'} or
        identity.get('format') != 1
    ):
        raise ValueError('invalid session identity')
    username = authbroker.canonicalize_username(identity.get('username'))
    return username


def loginuser(sessionbroker=False):

    clearloginready()

    try:

        # connect to window server
        if not wsconnect():
            return None

    except Exception as e:

        log(f"wsconnect error {e}")
        return None

    wswaitwelcome()

    wssubscribefbsize()

    if not wscreatewindow():
        return None

    initbuffer(WINBUF_PATH, SCREEN_W, SCREEN_H)

    try:

        updatelayout()

        # load the truetype font face at scaled size
        initttffont(FONTFILE, scs(FONTSIZE_BASE))

        # use a scaled font size matching the 1080p design
        FONTSIZE = scs(FONTSIZE_BASE)

    except Exception as e:

        log(f"initttffont error {e}")
        return None

    try:

        # reset the dirty rectangles to empty
        resetdirty()
        graphicsresetdirty()

    except Exception as e:

        log(f"resetdirty error {e}")
        return None

    # clear the entire screen to the configured background colour
    clear(BACKGROUNDCOLOUR)

    # Decode the configured master image once for this login. If the setting
    # is disabled or the source is unavailable, loginlayout preserves the
    # original lock-screen coordinates.
    masterimage = preparemasterimage()
    layout = loginlayout(masterimage)

    if masterimage and layout.get("image_rect"):

        image_x, image_y, image_w, image_h = layout["image_rect"]
        drawimage(
            masterimage["path"],
            masterimage["width"],
            masterimage["height"],
            image_x,
            image_y,
            image_w,
            image_h,
        )

    # choose the login title text
    title = "log in"

    # measure the title width for centering
    title_w = measuretext(title, FONTSIZE)

    # draw the centered login title
    drawtextttf(
        (SCREEN_W - title_w) // 2,
        layout["title_y"],
        title,
        TEXTCOLOUR,
        FONTSIZE,
    )

    # present the title
    wspresent()

    # The boot-time Startup domain owns account provisioning and credential
    # migration. The unprivileged lockscreen domain sees only the published
    # username and sends each password to the typed Operations verifier.
    try:
        if sessionbroker:
            username = sessionusername()
        else:
            ensureusersfile()
            username, _storedpw = authbroker.read_credentials(MASTERFILE)

    # handle missing master file with a visible error
    except FileNotFoundError:

        # clear the screen
        clear()

        # draw a centered error about missing master file
        ew = measuretext("master file not found", FONTSIZE)

        drawtextttf((SCREEN_W - ew)//2, scy(540), "master file not found", ERRORCOLOUR, FONTSIZE)

        # present the error
        wspresent()

        wsmapready()

        # abort login
        return None

    # handle permission issues when reading the master file
    except PermissionError:

        # clear the screen
        clear()

        # draw a centered permission error
        ew = measuretext("permission denied to read master file", FONTSIZE)

        drawtextttf((SCREEN_W - ew)//2, scy(540), "permission denied to read master file", ERRORCOLOUR, FONTSIZE)

        # present the error
        wspresent()

        wsmapready()

        # abort login
        return None

    # handle a malformed master entry (no colon)
    except (ValueError, authbroker.AuthenticationError):

        # clear the screen
        clear()

        # draw a centered format error
        ew = measuretext("malformed entry in the master file", FONTSIZE)

        drawtextttf((SCREEN_W - ew)//2, scy(540), "malformed entry in the master file", ERRORCOLOUR, FONTSIZE)

        # present the error
        wspresent()

        wsmapready()

        # abort login
        return None

    # handle any other read error generically
    except Exception as e:

        # clear the screen
        clear()

        # draw a centered generic read error
        msg = f"error reading master file {e}"

        ew = measuretext(msg, FONTSIZE)

        drawtextttf((SCREEN_W - ew)//2, scy(540), msg, ERRORCOLOUR, FONTSIZE)

        # present the error
        wspresent()

        wsmapready()

        # abort login
        return None

    # build the centered line that names the master
    line   = f"master {username}"

    # measure the master line width for centering
    line_w = measuretext(line, FONTSIZE)

    # compute the left x position so the line is centered
    x      = (SCREEN_W - line_w) // 2  # left edge for centered line

    # draw the master label line at the configured baseline
    drawtextttf(x, layout["master_y"], line, TEXTCOLOUR, FONTSIZE)

    # present the label
    wspresent()

    # draw an underline directly under the rendered text span
    underline_y = layout["underline_y"]
    drawline(x, underline_y, x + line_w, underline_y, 0xEFEFEF)

    # present the underline
    wspresent()

    # the title, master label and underline now form the complete first frame
    if wsmapready() and waitwindowmapped():
        writeloginready(username)
    else:
        log("login window did not receive its map acknowledgement")

    # keep asking for the password until it verifies
    while True:

        tickerror()

        # read password bullets bounded by the underline width
        pwd = readpass(
            prompt_text="",
            prompt_x=x + scs(10),
            prompt_y=layout["password_y"],
            master_line_x=x,
            master_line_w=line_w,
            font_size=FONTSIZE,
            fg_color=TEXTCOLOUR,
            bg_color=BACKGROUNDCOLOUR,
            caps_notice_y=(
                underline_y
                + (max(12, FONTSIZE // 2) * 2)
                + scs(10)
            ),
        )

        # readpass can process a resize while waiting.  Refresh the outer
        # geometry before validation, error placement or another attempt.
        FONTSIZE = scs(FONTSIZE_BASE)
        line_w = measuretext(line, FONTSIZE)
        x = (SCREEN_W - line_w) // 2
        layout = loginlayout(masterimage)
        underline_y = layout["underline_y"]

        # Verify through the broker so failures share persistent backoff and a
        # successful legacy login atomically migrates the credential format.
        if sessionbroker:
            try:
                response = session_auth_verify(pwd, timeout=5.0)
                authenticationok = bool(response.get('verified'))
                retryafter = float(response.get('retry_after') or 0.0)
                migrated = bool(response.get('migrated'))
            except Exception:
                authenticationok = False
                retryafter = 0.0
                migrated = False
        else:
            authentication = authbroker.authenticate_master(
                MASTERFILE,
                pwd,
                scope="login",
                rate_path=AUTH_RATE_FILE,
            )
            authenticationok = bool(authentication.ok)
            retryafter = float(authentication.retry_after or 0.0)
            migrated = bool(authentication.migrated)

        if authenticationok:

            if not migrated and not sessionbroker:
                # A non-migrated current-format credential is normal; the
                # broker records migration failures through its result/log.
                pass

            # leave the loop on success
            clearloginready()
            break  # success

        if retryafter:
            wait_seconds = max(1, int(retryafter + 0.999))
            err = "invalid password"
        else:
            wait_seconds = 1
            err = "authentication unavailable"

        err_size = max(12, FONTSIZE // 2)

        err_y = underline_y + err_size

        ex = (SCREEN_W - measuretext(err, err_size)) // 2

        showerror(err, ex, err_y, err_size)

        # clear the bullet line immediately to show it’s ready for input
        fillrect(
            x,
            layout["password_clear_y"],
            line_w,
            FONTSIZE,
            BACKGROUNDCOLOUR,
        )

        # present the cleared bullet line
        wspresent()

        # Enforce the broker's bounded delay in this interactive process too.
        time.sleep(min(wait_seconds, 30))

    # return the username on successful login
    return username


def drawcapslocknotice(enabled, y, font_size, bg_color):

    notice_size = max(12, int(font_size) // 2)
    notice_width = max(1, measuretext(CAPSLOCKNOTICE, notice_size))
    notice_x = (int(SCREEN_W) - notice_width) // 2
    notice_yoff, notice_height = ttflinebox(
        notice_size,
        fontpath=FONTFILE,
    )
    notice_pad = max(2, scs(3))

    fillrect(
        notice_x - notice_pad,
        int(y) + notice_yoff - notice_pad,
        notice_width + (notice_pad * 2),
        notice_height + (notice_pad * 2),
        bg_color,
    )

    if enabled:
        drawtextttf(
            notice_x,
            int(y),
            CAPSLOCKNOTICE,
            TEXTCOLOUR,
            notice_size,
            FONTFILE,
        )


def readpass(prompt_text, prompt_x, prompt_y, master_line_x, master_line_w,
                font_size, fg_color, bg_color, caps_notice_y=None):

    # buffer to store typed password characters (not echoed as text)
    pwd = []

    # track the number of bullets last drawn (to avoid redundant blits)
    last_drawn_len = -1

    # The notice is shown only while a password field is active.  Its state is
    # supplied by the modifier snapshot attached to each WindowServer key event.
    caps_notice_drawn = False

    # measure the prompt text width (0 in your call) to offset bullets
    prompt_w = measuretext(prompt_text, font_size)

    # measure the width of a single bullet glyph
    bullet_unit_w = max(1, measuretext('•', font_size))

    # compute the starting x for bullet rendering (prompt to the left)
    bullets_x = prompt_x + prompt_w

    # set bullets baseline y equal to the prompt baseline y
    bullets_y = prompt_y

    # left x limit of the underline span to respect (clip start)
    clip_x = master_line_x

    # width of the underline span (clip width)
    clip_w = master_line_w

    # compute the maximum number of bullets that fit under the underline
    max_bullets = max(0, (clip_w - (bullets_x - clip_x)) // bullet_unit_w)

    # Remember the framebuffer that the supplied field geometry belongs to.
    # FB_SIZE events are handled inside readcharsws, so this input loop must
    # update its local coordinates before it paints again.
    layout_w = int(SCREEN_W)
    layout_h = int(SCREEN_H)

    # adjust when the bullets start left of the underline start
    if bullets_x < clip_x:

        # compute how many bullet columns we need to skip to align
        shift = (clip_x - bullets_x + bullet_unit_w - 1) // bullet_unit_w

        # move the visual start of bullets onto the underline
        bullets_x = clip_x

        # recompute capacity accounting for the left shift
        max_bullets = max(0, (clip_w // bullet_unit_w) - shift)

    # compute TTF clear box that matches drawtextttf pixel coverage
    bullets_yoff, bullets_h = ttflinebox(font_size)

    # read keys and update the bullet line until Enter is pressed
    while True:

        tickerror()

        # gather a small batch of keypresses to keep latency low
        chars = readcharsws(timeout_ms=8)  # tighter batching -> less lag

        if int(SCREEN_W) != layout_w or int(SCREEN_H) != layout_h:

            scale, offsetx, offsety = graphicsresizetransform(
                layout_w, layout_h, SCREEN_W, SCREEN_H)
            bullets_x = int(round(offsetx + (float(bullets_x) * scale)))
            bullets_y = int(round(offsety + (float(bullets_y) * scale)))
            clip_x = int(round(offsetx + (float(clip_x) * scale)))
            clip_w = max(1, int(round(float(clip_w) * scale)))
            font_size = max(12, int(round(float(font_size) * scale)))
            if caps_notice_y is not None:
                caps_notice_y = int(round(
                    offsety + (float(caps_notice_y) * scale)))
            prompt_w = measuretext(prompt_text, font_size)
            bullet_unit_w = max(1, measuretext('•', font_size))
            max_bullets = max(0, (clip_w - (bullets_x - clip_x)) // bullet_unit_w)
            bullets_yoff, bullets_h = ttflinebox(font_size)
            layout_w = int(SCREEN_W)
            layout_h = int(SCREEN_H)

        # track whether the bullet line needs repainting
        changed = False

        caps_notice_changed = (
            caps_notice_y is not None
            and bool(CAPSLOCKON) != caps_notice_drawn
        )

        if caps_notice_changed:
            drawcapslocknotice(
                bool(CAPSLOCKON),
                caps_notice_y,
                font_size,
                bg_color,
            )
            caps_notice_drawn = bool(CAPSLOCKON)

        # process each key in the batch
        for ch in chars:

            # if Enter is pressed, finalize and return the password
            if ch == '\n':

                caps_notice_cleared = caps_notice_drawn

                if caps_notice_drawn:
                    drawcapslocknotice(
                        False,
                        caps_notice_y,
                        font_size,
                        bg_color,
                    )
                    caps_notice_drawn = False

                # force a final redraw if our on-screen bullets are stale
                if last_drawn_len != len(pwd):

                    # clear the entire underline bullet strip to prevent artifacts
                    fillrect(clip_x, bullets_y + bullets_yoff, clip_w, bullets_h, bg_color)

                    # draw bullets equal to the number of typed characters
                    drawtextttf(bullets_x, bullets_y, '•' * len(pwd), fg_color, font_size)

                    # present the updated bullet line
                    wspresentinput()

                elif caps_notice_changed or caps_notice_cleared:
                    wspresentinput()

                # return the collected characters as a single string
                return ''.join(pwd)

            # if Backspace is pressed, erase last character if present
            if ch == '\b':
                if pwd:
                    pwd.pop()
                    changed = True
                continue

            # if Escape is pressed, clear the entire typed buffer
            if ch == '\x1b':  # ESC clears
                if pwd:
                    pwd.clear()
                    changed = True
                continue

            # accept printable ASCII characters while under the hard cap
            if isinstance(ch, str) and len(ch) == 1 and 32 <= ord(ch) <= 126:
                if len(pwd) < max_bullets:       # <— HARD CAP: never overrun the underline
                    pwd.append(ch)
                    changed = True
                # if over capacity, ignore extra characters silently
                continue

        # repaint the bullet line only when the length actually changed
        if changed and last_drawn_len != len(pwd):

            # update the last-drawn length tracker
            last_drawn_len = len(pwd)

            # clear the entire underline bullet strip to prevent artifacts
            fillrect(clip_x, bullets_y + bullets_yoff, clip_w, bullets_h, bg_color)

            # draw bullets starting at bullets_x representing the length
            if pwd:
                drawtextttf(bullets_x, bullets_y, '•' * len(pwd), fg_color, font_size)

            # present the bullet redraw
            wspresentinput()

        elif caps_notice_changed:
            wspresentinput()


def createuserdirs(username):
    try:
        authbroker.ensure_user_tree(
            HOME_BASE, username, owner_uid=1000, owner_gid=1000)
    except PermissionError:
        log("permission denied to create home tier")
    except (OSError, ValueError, authbroker.AuthenticationError) as e:
        log(f"error creating home tier {type(e).__name__}")


# graphics diagnostic
def graphicsdiagnostic():

    global SCREEN_W, SCREEN_H, FONTSIZE, GRAPHICSDISPLAYLIST
    global GRAPHICSBUILDTOTALMS, GRAPHICSBUILDMAXIMUMMS, GRAPHICSBUILDCOUNT
    global GRAPHICSDIRTYRECT, WSDEFERREDMSGS, ANIMATIONCOMMITACKS

    result = {
        "format": 1,
        "passed": False,
        "resolution": [2560, 1440],
        "checks": {},
        "performance": {},
        "errors": [],
    }

    try:

        SCREEN_W = 2560
        SCREEN_H = 1440
        updatelayout()
        FONTSIZE = scs(FONTSIZE_BASE)
        initttffont(FONTFILE, FONTSIZE)

        unchangedlayout = loginlayout()

        if (
            unchangedlayout["title_y"] != scy(480) or
            unchangedlayout["master_y"] != scy(540) or
            unchangedlayout["password_y"] != scy(600) or
            unchangedlayout["underline_y"] != scy(660) or
            unchangedlayout["image_rect"] is not None
        ):
            raise RuntimeError(
                "disabled master image changed the existing login geometry")

        designwidth, designheight, physicalwidth, physicalheight = (
            masterimagesize(3000, 2000))

        if (
            (designwidth, designheight) != (154, 103) or
            (physicalwidth, physicalheight) != (205, 137)
        ):
            raise RuntimeError(
                "master image cache did not follow the physical display scale")

        diagnosticimage = {
            "path": "/.ephemeral/startup/diagnostic-master-image.bgra",
            "width": physicalwidth,
            "height": physicalheight,
            "design_width": designwidth,
            "design_height": designheight,
        }
        imagelayout = loginlayout(diagnosticimage)

        if (
            imagelayout["base_image_top"] !=
            BASE_H - (imagelayout["base_underline_y"] + 1)
        ):
            raise RuntimeError(
                "master image login layout did not balance its outer gaps")

        image_x, image_y, image_w, image_h = imagelayout["image_rect"]

        if (
            abs((image_x + (image_w // 2)) - (SCREEN_W // 2)) > 1 or
            image_y != SCREEN_H - (imagelayout["underline_y"] + 1) or
            image_w != diagnosticimage["width"] or
            image_h != diagnosticimage["height"] or
            image_y + image_h > imagelayout["title_y"] or
            not (
                imagelayout["title_y"] < imagelayout["master_y"] <
                imagelayout["password_y"] < imagelayout["underline_y"]
            )
        ):
            raise RuntimeError(
                "master image login layout has invalid element ordering")

        result["checks"]["master_image_layout"] = True
        result["checks"]["master_image_physical_resolution"] = True
        result["checks"]["disabled_master_image_geometry"] = True
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
        managedconfigure(GRAPHICSSTATE, capabilities, required=("rectangle", "text"), cpu=False)
        graphicssyncstate()

        if not GRAPHICSAVAILABLE:
            raise RuntimeError(f"managed graphics negotiation failed: {GRAPHICSFAILURE}")

        result["checks"]["capability_negotiation"] = True
        animationsamples = [
            animationprogress(20.0, LABELFADETIME, 20.0),
            animationprogress(
                20.0,
                LABELFADETIME,
                20.0 + (LABELFADETIME / 2.0),
            ),
            animationprogress(20.0, LABELFADETIME, 20.0 + LABELFADETIME),
        ]
        minimumlabelframes = int(LABELFADETIME / ANIMATIONFRAMETIME) + 1
        minimumtitleframes = int(
            (len("Welcome to The One OS") * TITLECHARACTERTIME) /
            ANIMATIONFRAMETIME
        ) + 1

        if (
            any(
                abs(actual - expected) > 0.000001
                for actual, expected in zip(
                    animationsamples,
                    (0.0, 0.5, 1.0),
                )
            ) or
            abs(ANIMATIONREFRESHHZ - 60.0) > 0.001 or
            minimumlabelframes < 18 or
            minimumtitleframes < 120
        ):
            raise RuntimeError("startup animations are not time-based at 60 Hz")

        result["checks"]["animation_pacing"] = {
            "target_hz": float(ANIMATIONREFRESHHZ),
            "title_minimum_frames": int(minimumtitleframes),
            "label_duration_ms": int(round(LABELFADETIME * 1000.0)),
            "label_minimum_frames": int(minimumlabelframes),
        }

        originalstate = json.loads(json.dumps(GRAPHICSSTATE))
        originaldisplaylist = list(GRAPHICSDISPLAYLIST)
        originaldirtyrect = graphicsgetdirty()
        originalgraphicspresent = globals()["graphicspresent"]
        captureddamage = []

        try:

            GRAPHICSSTATE["available"] = True
            GRAPHICSSTATE["active"] = True
            GRAPHICSSTATE["managed_only"] = True
            GRAPHICSSTATE["pending"] = False
            GRAPHICSDISPLAYLIST = []
            graphicsresetdirty()
            resetdirty()
            fillrect(120, 160, 90, 45, TEXTCOLOUR)
            globals()["graphicspresent"] = (
                lambda rect: captureddamage.append(list(rect)) or True
            )
            wspresent()

            if captureddamage != [[120, 160, 90, 45]]:
                raise RuntimeError(
                    "managed-only presentation replaced local damage with "
                    "full-screen damage"
                )

        finally:

            globals()["graphicspresent"] = originalgraphicspresent
            GRAPHICSSTATE.clear()
            GRAPHICSSTATE.update(originalstate)
            graphicssyncstate()
            GRAPHICSDISPLAYLIST = originaldisplaylist
            GRAPHICSDIRTYRECT = (
                list(originaldirtyrect)
                if originaldirtyrect is not None
                else None
            )
            resetdirty()

        result["checks"]["managed_dirty_rect"] = list(captureddamage[0])
        originalstate = json.loads(json.dumps(GRAPHICSSTATE))
        originalrecvlines = globals()["wsrecvlines"]
        originalgraphicspump = globals()["graphicspump"]
        originaldeferred = list(WSDEFERREDMSGS)
        originalcommitacks = int(ANIMATIONCOMMITACKS)
        ackpumpcalls = []
        deferredkey = {
            "op": "EVENT",
            "kind": "key",
            "key": "ENTER",
            "state": "down",
        }
        ackresponses = [[
            json.dumps({
                "op": "GRAPHICS_COMMITTED",
                "winid": 77,
                "count": 2,
                "accelerated": True,
                "managed_only": True,
            }),
            json.dumps(deferredkey),
        ]]

        try:

            GRAPHICSSTATE["available"] = True
            GRAPHICSSTATE["active"] = True
            GRAPHICSSTATE["managed_only"] = True
            GRAPHICSSTATE["pending"] = True
            GRAPHICSSTATE["pending_at"] = time.monotonic()
            GRAPHICSSTATE["need_submit"] = True
            GRAPHICSSTATE["winid"] = 77
            GRAPHICSSTATE["pending_scene"] = [{"kind": "rectangle"}]
            WSDEFERREDMSGS = []
            globals()["wsrecvlines"] = (
                lambda timeout=0.0:
                    ackresponses.pop(0) if ackresponses else []
            )
            globals()["graphicspump"] = (
                lambda: ackpumpcalls.append(True) or True
            )
            wsanimationpump(0.0)

            if (
                GRAPHICSSTATE.get("pending") or
                len(ackpumpcalls) != 1 or
                WSDEFERREDMSGS != [deferredkey] or
                ANIMATIONCOMMITACKS != originalcommitacks + 1
            ):
                raise RuntimeError(
                    "startup animation pump did not release and submit the "
                    "newest managed frame"
                )

        finally:

            globals()["wsrecvlines"] = originalrecvlines
            globals()["graphicspump"] = originalgraphicspump
            GRAPHICSSTATE.clear()
            GRAPHICSSTATE.update(originalstate)
            graphicssyncstate()
            WSDEFERREDMSGS = originaldeferred
            ANIMATIONCOMMITACKS = originalcommitacks

        result["checks"]["animation_ack_pump"] = True
        GRAPHICSDISPLAYLIST = []
        graphicsrecordrectangle(0, 0, SCREEN_W, SCREEN_H, BACKGROUNDCOLOUR)
        graphicsrecordtext(760, 460, "Welcome to The One OS", TEXTCOLOUR, FONTSIZE, BRANDFONT)
        graphicsrecordtext(690, 720, "what is your name?", TEXTCOLOUR, FONTSIZE, FONTFILE)
        graphicsrecordtext(1300, 720, "edward", TEXTCOLOUR, FONTSIZE, FONTFILE)
        graphicsrecordtext(690, 800, "enter password", TEXTCOLOUR, FONTSIZE, FONTFILE)
        graphicsrecordtext(1300, 800, "••••••••", TEXTCOLOUR, FONTSIZE, FONTFILE)
        graphicsrecordtext(690, 880, "confirm password", TEXTCOLOUR, FONTSIZE, FONTFILE)
        graphicsrecordtext(1300, 880, "••••••••", TEXTCOLOUR, FONTSIZE, FONTFILE)
        graphicsrecordtext(1010, 970, "passwords do not match", ERRORCOLOUR, max(12, FONTSIZE // 2), FONTFILE)
        setupscene = graphicsbuildscene()

        if not setupscene or setupscene[0].get("kind") != "rectangle" or setupscene[0].get("rect") != [0, 0, SCREEN_W, SCREEN_H]:
            raise RuntimeError("setup scene does not begin with an opaque full-screen background")

        welcomecommand = next((command for command in setupscene if command.get("text") == "Welcome to The One OS"), None)

        if welcomecommand is None:
            raise RuntimeError("setup scene did not preserve the welcome title")

        if welcomecommand.get("font") != BRANDFONT:
            raise RuntimeError("startup welcome title did not preserve the Cambria brand font")

        expectedprompts = {"what is your name?", "enter password", "confirm password"}
        renderedprompts = {
            str(command.get("text", ""))
            for command in setupscene
            if command.get("kind") == "text"
        }

        if not expectedprompts.issubset(renderedprompts):
            raise RuntimeError("setup scene did not preserve the complete account prompts")

        setupuicommands = [
            command
            for command in setupscene
            if command.get("kind") == "text" and command is not welcomecommand
        ]

        if not setupuicommands or any(command.get("font") != FONTFILE for command in setupuicommands):
            raise RuntimeError("startup account interface did not consistently use Atkinson Hyperlegible Next")

        if sum(1 for command in setupscene if "••••••••" in str(command.get("text", ""))) != 2:
            raise RuntimeError("setup scene did not preserve both masked password fields")

        secret = "diagnostic-plaintext-password"

        if secret in json.dumps(setupscene, sort_keys=True):
            raise RuntimeError("setup scene exposed plaintext authentication material")

        result["checks"]["setup_flow"] = True
        result["checks"]["complete_account_prompts"] = True
        result["checks"]["masked_passwords"] = True
        GRAPHICSDISPLAYLIST = []
        graphicsrecordrectangle(0, 0, SCREEN_W, SCREEN_H, BACKGROUNDCOLOUR)
        graphicsrecordimage(
            diagnosticimage["path"],
            diagnosticimage["width"],
            diagnosticimage["height"],
            image_x,
            image_y,
            image_w,
            image_h,
        )
        graphicsrecordtext(1190, 640, "log in", TEXTCOLOUR, FONTSIZE, FONTFILE)
        graphicsrecordtext(1080, 720, "master edward", TEXTCOLOUR, FONTSIZE, FONTFILE)
        graphicsrecordrectangle(1080, 880, 400, 2, TEXTCOLOUR)
        graphicsrecordtext(1100, 800, "••••", TEXTCOLOUR, FONTSIZE, FONTFILE)
        graphicsrecordtext(1160, 940, "invalid password", ERRORCOLOUR, max(12, FONTSIZE // 2), FONTFILE)
        GRAPHICSBUILDTOTALMS = 0.0
        GRAPHICSBUILDMAXIMUMMS = 0.0
        GRAPHICSBUILDCOUNT = 0
        scenes = []

        for _ in range(20):
            scenes.append(graphicsbuildscene())

        scene = scenes[-1]
        textcommands = [command for command in scene if command.get("kind") == "text"]
        rectanglecommands = [command for command in scene if command.get("kind") == "rectangle"]
        imagecommands = [command for command in scene if command.get("kind") == "image"]

        if not any(command.get("text") == "log in" for command in textcommands):
            raise RuntimeError("login scene did not preserve its title")

        if not any(command.get("text") == "master edward" for command in textcommands):
            raise RuntimeError("login scene did not preserve the master label")

        if len(rectanglecommands) < 2:
            raise RuntimeError("login scene did not preserve its underline")

        if (
            len(imagecommands) != 1 or
            imagecommands[0].get("path") != diagnosticimage["path"] or
            imagecommands[0].get("source_width") != diagnosticimage["width"] or
            imagecommands[0].get("source_height") != diagnosticimage["height"] or
            imagecommands[0].get("format") != "BGRA32"
        ):
            raise RuntimeError(
                "login scene did not preserve the decoded master image")

        if any(command.get("font") != FONTFILE for command in textcommands):
            raise RuntimeError("startup login interface did not use Atkinson Hyperlegible Next")

        result["checks"]["login_flow"] = True
        result["checks"]["master_image_scene"] = True
        result["checks"]["opaque_background"] = True
        result["checks"]["first_frame_complete"] = True
        result["checks"]["typography_roles"] = True
        requests = []
        managedmarkdamage(GRAPHICSSTATE, [1050, 760, 500, 180], bounds=(SCREEN_W, SCREEN_H))
        managedsubmit(GRAPHICSSTATE, lambda request: requests.append(request) or True, 91, scene)

        if len(requests) != 1 or requests[0].get("op") != "GRAPHICS_SCENE":
            raise RuntimeError("startup did not submit one atomic managed scene")

        managedresponse(GRAPHICSSTATE, {
            "op": "GRAPHICS_COMMITTED",
            "winid": 91,
            "count": len(scene),
            "batch": True,
            "accelerated": True,
            "managed_only": True,
        })
        graphicssyncstate()

        if not GRAPHICSACTIVE or GRAPHICSPENDING:
            raise RuntimeError("startup scene did not activate after acknowledgement")

        result["checks"]["atomic_scene"] = {
            "messages": len(requests),
            "commands": len(scene),
            "damage": len(requests[0].get("damage", [])),
        }
        result["checks"]["command_budget"] = {
            "commands": len(scene),
            "limit": int(GRAPHICSSTATE.get("command_limit", 0)),
        }
        oldwidth = SCREEN_W
        oldheight = SCREEN_H
        SCREEN_W = 1920
        SCREEN_H = 1080
        graphicsscaledisplay(oldwidth, oldheight, SCREEN_W, SCREEN_H)
        resized = graphicsbuildscene()

        if resized[0].get("rect") != [0, 0, 1920, 1080]:
            raise RuntimeError("startup resize did not reconstruct the opaque background")

        result["checks"]["resize_reconstruction"] = True

        # A 4:3-to-16:9 grow previously scaled x and y independently.  Text
        # grew by the smaller factor, leaving centred login lines left of the
        # underline and above the rest of the layout.
        GRAPHICSDISPLAYLIST = [
            {
                "command": {"kind": "rectangle", "rect": [0, 0, 800, 600], "color": BACKGROUNDCOLOUR, "clip": [0, 0, 800, 600]},
                "bounds": [0, 0, 800, 600],
            },
            {
                "command": {"kind": "text", "x": 250, "y": 200, "text": "master development", "size": 20, "font": FONTFILE, "color": TEXTCOLOUR, "clip": [0, 0, 800, 600]},
                "bounds": [250, 200, 300, 50],
                "cpu_y": 200,
            },
            {
                "command": {"kind": "rectangle", "rect": [250, 350, 300, 1], "color": TEXTCOLOUR, "clip": [0, 0, 800, 600]},
                "bounds": [250, 350, 300, 1],
            },
        ]
        SCREEN_W = 2560
        SCREEN_H = 1440
        graphicsscaledisplay(800, 600, SCREEN_W, SCREEN_H)
        resizedtext = GRAPHICSDISPLAYLIST[1]
        resizedline = GRAPHICSDISPLAYLIST[2]["command"]["rect"]
        textcenter = resizedtext["command"]["x"] + (resizedtext["bounds"][2] // 2)
        linecenter = resizedline[0] + (resizedline[2] // 2)

        if abs(textcenter - (SCREEN_W // 2)) > 1 or abs(linecenter - (SCREEN_W // 2)) > 1:
            raise RuntimeError("startup resize did not preserve centred login geometry")

        if resizedtext["command"]["size"] != 48:
            raise RuntimeError("startup resize did not preserve uniform text scaling")

        result["checks"]["resize_login_alignment"] = True
        SCREEN_W = 800
        SCREEN_H = 600

        if not wsnotefbsize(2560, 1440) or SCREEN_W != 2560 or SCREEN_H != 1440:
            raise RuntimeError("startup protocol did not preserve the final grow notification")

        result["checks"]["shrink_grow_protocol_state"] = True
        SCREEN_W = 1920
        SCREEN_H = 1080
        updatelayout()
        accountbefore = setupusergeometry()
        SCREEN_W = 800
        SCREEN_H = 600
        updatelayout()
        accountsmall = setupusergeometry()
        SCREEN_W = 1920
        SCREEN_H = 1080
        updatelayout()
        accountafter = setupusergeometry()
        geometrykeys = (
            "font_size", "title_x", "title_y", "label_x", "name_y",
            "input_x", "pwd_y", "confirm_y", "success_y")

        if any(accountbefore[key] != accountafter[key] for key in geometrykeys):
            raise RuntimeError("account setup geometry did not survive shrink and grow")

        if not (
                accountsmall["title_y"] < accountsmall["name_y"]
                < accountsmall["pwd_y"] < accountsmall["confirm_y"]
                < accountsmall["success_y"] < 600):
            raise RuntimeError("account setup resize produced invalid vertical ordering")

        result["checks"]["resize_account_setup_alignment"] = True
        fallback = managedstate(cpu=True)
        managedconfigure(fallback, capabilities, required=("rectangle", "text"))
        missing = managedstate()
        managedconfigure(missing, {}, required=("rectangle", "text"))
        rejected = managedstate()
        managedconfigure(rejected, capabilities, required=("rectangle", "text"))
        rejected["winid"] = 92
        managedresponse(rejected, {"op": "ERROR", "winid": 92, "code": "graphics_scene_failed", "detail": "diagnostic"})
        timedout = managedstate()
        managedconfigure(timedout, capabilities, required=("rectangle", "text"))
        timedout["pending"] = True
        timedout["pending_at"] = time.monotonic() - 3.0
        managedtick(timedout, timeout=0.1)

        if fallback.get("available") or missing.get("available"):
            raise RuntimeError("a startup non-GPU fallback path remained managed")

        if not all(
            item.get("available")
            and item.get("active")
            and item.get("managed_only")
            and item.get("need_submit")
            for item in (rejected, timedout)
        ):
            raise RuntimeError("startup recovery escaped strict GPU rendering")

        result["checks"]["cpu_fallback"] = True
        result["checks"]["missing_capability_fallback"] = True
        result["checks"]["error_gpu_retention"] = True
        result["checks"]["timeout_gpu_retention"] = True
        result["checks"]["first_frame_before_map"] = True
        result["checks"]["authentication_material_absent"] = True
        result["performance"] = {
            "average_scene_build_ms": round(GRAPHICSBUILDTOTALMS / max(1, GRAPHICSBUILDCOUNT), 3),
            "maximum_scene_build_ms": round(GRAPHICSBUILDMAXIMUMMS, 3),
            "maximum_commands": len(scene),
        }
        result["passed"] = True

    except Exception as e:

        result["errors"].append(str(e))

    return result


def graphicsdiagnosticcommand():

    result = graphicsdiagnostic()
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result.get("passed") else 1


def notifysessionauthenticated(timeout=3.0):

    if WSSOCK is None or not WINID:
        log(f"{timestamp()} [startup] session authentication has no window server owner")
        return False

    deadline = time.monotonic() + max(0.25, float(timeout))
    lastsend = 0.0

    while time.monotonic() < deadline:

        now = time.monotonic()

        # wssend deliberately drops a nonblocking write that cannot complete.
        # Retry this small, idempotent control record until its acknowledgement
        # arrives instead of treating local socket backpressure as an unlock.
        if now - lastsend >= 0.25:
            wssend({
                "op": "SESSION_AUTHENTICATED",
                "winid": int(WINID),
            })
            lastsend = now

        wait = min(0.05, max(0.0, deadline - time.monotonic()))

        for line in wsrecvlines(timeout=wait):

            try:
                msg = json.loads(line)
            except Exception:
                continue

            op = str(msg.get("op", ""))

            if op == "SESSION_AUTHENTICATED":

                if msg.get("authenticated") is True:
                    log(f"{timestamp()} [startup] session authentication accepted")
                    return True

                continue

            if (
                    op == "ERROR"
                    and msg.get("code") == "session_authentication_denied"):
                log(f"{timestamp()} [startup] session authentication denied")
                return False

            if op == "FB_SIZE":
                wsapplyfbsize(msg.get("w", 0), msg.get("h", 0))
                continue

            if (
                    op in ("GRAPHICS_COMMITTED", "GRAPHICS_CLEARED")
                    or (
                        op == "ERROR"
                        and str(msg.get("code", "")).startswith("graphics_")
                    )):
                graphicsresponse(msg)

    log(f"{timestamp()} [startup] session authentication acknowledgement timed out")
    return False


def sessionlockmain():

    global WINROLE, WINTITLE

    WINROLE = 'lockscreen'
    WINTITLE = 'lockscreen'

    try:
        sessionusername()
    except Exception:
        log(f"{timestamp()} [startup] session lock refused without an identity")
        return 1

    log(f"{timestamp()} [startup] authenticated session lock started")

    while True:

        try:
            # Use the same verified lock-screen handoff and password verifier as
            # boot login. Only this session mode reports the successful
            # authentication back to WindowServer.
            runlockscreenwithhandoff()
            username = loginuser(sessionbroker=True)

            if not username:
                raise RuntimeError("session login ended without authentication")

            if not notifysessionauthenticated():
                raise RuntimeError(
                    "window server did not accept session authentication"
                )

            cleartobrick()

            if WINID and WINBUF_PATH:
                wspresent()
                graphicswaitinitial(timeout=0.25)

            wsclose()
            log(
                f"{timestamp()} [startup] authenticated session lock complete "
                f"user={username}"
            )
            return 0

        except KeyboardInterrupt:
            resetsessionwindow()
            return 130

        except Exception as error:
            # Remain fail-closed. A transient lock-screen or login failure gets
            # another complete lock -> login attempt while WindowServer keeps
            # desktop input suppressed.
            log(
                f"{timestamp()} [startup] session lock attempt failed "
                f"{type(error).__name__}: {error}"
            )
            resetsessionwindow()
            time.sleep(0.25)


# main
def main():

    # check if master tier and file exist
    ensureusersfile()

    # if master is existing
    if userexists():

        # Keep the dots visible until the lock screen has committed and mapped
        # its first complete frame. This prevents a failed or slow lock screen
        # from becoming an unbounded black screen.
        runlockscreenwithhandoff()

        # move to log in
        loginuser()

    # otherwise
    else:

        # Reuse the already-visible animation window: replace the dots with the
        # first-run The One fade, then release the display to account setup.
        bootanimationhandoff("brand", 8.0)

        # set up new master
        created = setupuser()

        if not created:
            log(
                f"{timestamp()} [startup] first-run setup did not complete; "
                "preserving the last verified frame and aborting startup"
            )
            raise RuntimeError("first-run setup did not complete")

    # clear screen
    cleartobrick()

    if WINID and WINBUF_PATH:

        wspresent()
        graphicswaitinitial(timeout=0.25)

    wsclose()



# execute main
if __name__ == "__main__":

    command = sys.argv[1].strip().lower() if len(sys.argv) > 1 else ""

    if command == "graphics-diagnostic":

        sys.exit(graphicsdiagnosticcommand())

    if command == "session-lock":

        sys.exit(sessionlockmain())

    main()
