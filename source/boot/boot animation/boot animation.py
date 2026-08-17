#!"/the one/software/python/bin/python" -B

# Invoked through the protected T1OS Python interpreter alias.



"""
boot animimation.py

boot animation for The One OS.
"""



## imports
import os
import sys
import time
import json
import socket

sys.path.insert(0, '/the one/build')

import graphics.graphics as gr
from graphics.graphics import *



## globals

# window
STATEBASE = "/.ephemeral/windowserver/state"
CONTROLBASE = "/.ephemeral/boot animation"
CONTROLREQUEST = os.path.join(CONTROLBASE, "request.json")
CONTROLSTATE = os.path.join(CONTROLBASE, "state.json")
POWERCONTROLBASE = "/.ephemeral/power animation"
FATALCONTROLBASE = "/.ephemeral/fatal screen"
FATALCONTENT = os.path.join(FATALCONTROLBASE, "content.json")
WSSOCK = None
WSWINID = 0
SCREENW = 0
SCREENH = 0
WSBUF = ""
WSINBUF = b""
WSDEFERRED = []
REALPRESENT = None

# managed graphics
GRAPHICSCAPS = {}
GRAPHICSAVAILABLE = False
GRAPHICSACTIVE = False
GRAPHICSPENDING = False
GRAPHICSFAILURE = ""
GRAPHICSFRAMES = 0
GRAPHICSMAXCOMMANDS = 0
GRAPHICSLASTCOMMANDS = 0
GRAPHICSBUILDTOTALMS = 0.0
GRAPHICSBUILDMAXIMUMMS = 0.0
GRAPHICSBUILDCOUNT = 0
GRAPHICSCPUOVERRIDE = str(os.environ.get("T1OS_BOOT_GRAPHICS", "")).strip().lower() in ("cpu", "off", "0", "false")
GRAPHICSSTATE = managedstate(cpu=GRAPHICSCPUOVERRIDE)

# boot animation reference
BASEW = 1920
BASEH = 1080
BASEFONT = 48

# derived metrics
BOOTSCALE = 1.0
BOOTFONT = 48
BOOTSPACING = 48
BOOTPADSMALL = 12
BOOTPADBIG = 20
BOOTPHASE = "black"
BOOTINTENSITY = 0
BOOTDOTS = []
BOOTDOTFRAME = 0
POWERLABEL = ""
POWERFONT = "/the one/resources/fonts/atkinsonhyperlegiblenext.ttf"
FATALFONT = "/the one/resources/fonts/firacode.ttf"
FATALBOLDFONT = "/the one/resources/fonts/firacodebold.ttf"
FATALIMAGE = "/the one/resources/system/red_screen_of_death.png"
FATALFAILURE = "system failure - unknown fatal failure"
FATALIMAGECACHE = None
FATALIMAGECACHESIZE = (0, 0)
DOTFRAMETIME = 0.24
DOTMINIMUMTIME = 0.72
BRANDHOLDTIME = 4.0
BRANDFADETIME = 0.32
ANIMATIONREFRESHHZ = 60.0
ANIMATIONFRAMETIME = 1.0 / ANIMATIONREFRESHHZ

_cpuclear = clear
_cpufillrectfast = fillrectfast
_cpudrawtextttf = drawtextttf


## functions

def configurecontrol(mode):

    global CONTROLBASE, CONTROLREQUEST, CONTROLSTATE

    selected = str(mode).strip().lower()

    if selected in ("poweroff", "restart"):
        CONTROLBASE = POWERCONTROLBASE
    elif selected == "fatal":
        CONTROLBASE = FATALCONTROLBASE
    else:
        CONTROLBASE = "/.ephemeral/boot animation"

    CONTROLREQUEST = os.path.join(CONTROLBASE, "request.json")
    CONTROLSTATE = os.path.join(CONTROLBASE, "state.json")


def graphicsmanagedonly():

    return bool(
        GRAPHICSSTATE.get("available")
        and managedstrict(GRAPHICSSTATE)
    )


def clear(color=0):

    if graphicsmanagedonly():
        return

    return _cpuclear(color)


def fillrectfast(x, y, width, height, color):

    if graphicsmanagedonly():
        return

    return _cpufillrectfast(x, y, width, height, color)


def drawtextttf(x, y, text, color, size, fontpath=None):

    if graphicsmanagedonly():
        return

    return _cpudrawtextttf(x, y, text, color, size, fontpath=fontpath)


def controlwrite(path, value):

    try:

        os.makedirs(CONTROLBASE, mode=0o700, exist_ok=True)
        temporary = f"{path}.{os.getpid()}.new"

        with open(temporary, "w", encoding="utf-8") as stream:

            json.dump(value, stream, sort_keys=True, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())

        os.replace(temporary, path)
        return True

    except Exception:

        try:
            os.unlink(temporary)
        except Exception:
            pass

        return False


def controlstate(state, mode="dots"):

    return controlwrite(CONTROLSTATE, {
        "format": 2,
        "pid": int(os.getpid()),
        "mode": str(mode),
        "state": str(state),
        # Keep the last physically submitted dot frame available to the next
        # display owner.  The firmware framebuffer and managed WindowServer
        # are separate processes, but they are one visual animation.
        "dot_frame": int(BOOTDOTFRAME),
    })


def controlprepare():

    try:
        os.makedirs(CONTROLBASE, mode=0o700, exist_ok=True)
    except Exception:
        return False

    for path in (CONTROLREQUEST, CONTROLSTATE):

        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        except Exception:
            pass

    return controlstate("starting")


def controlrequest():

    try:

        with open(CONTROLREQUEST, "r", encoding="utf-8") as stream:
            request = json.load(stream)

    except (FileNotFoundError, PermissionError, OSError, ValueError, TypeError):

        return None

    try:
        os.unlink(CONTROLREQUEST)
    except Exception:
        pass

    try:

        if int(request.get("pid", 0)) != int(os.getpid()):
            return None

        action = str(request.get("action", "")).strip().lower()

    except Exception:

        return None

    if action in ("brand", "lockscreen", "stop"):
        return action

    return None


def normalisefatalfailure(value):

    text = " ".join(str(value or "").split()).lower()
    text = text.replace(":", " -")

    while "  " in text:
        text = text.replace("  ", " ")

    while "- -" in text:
        text = text.replace("- -", "-")

    text = text.strip(" -")

    if not text:
        text = "system failure - unknown fatal failure"

    return text[:512]


def readfatalcontent():

    try:
        with open(FATALCONTENT, "r", encoding="utf-8") as stream:
            content = json.load(stream)
        return normalisefatalfailure(content.get("failure", ""))
    except Exception:
        return "system failure - fatal failure details unavailable"


def fatalimagepixels(width, height):

    global FATALIMAGECACHE, FATALIMAGECACHESIZE

    size = (max(1, int(width)), max(1, int(height)))

    if FATALIMAGECACHE is not None and FATALIMAGECACHESIZE == size:
        return FATALIMAGECACHE

    catalogue = "/the one/catalogue/image"

    if catalogue not in sys.path:
        sys.path.insert(0, catalogue)

    from PIL import Image, ImageOps

    Image.MAX_IMAGE_PIXELS = 32 * 1024 * 1024

    with Image.open(FATALIMAGE) as opened:
        opened.load()

        if str(opened.format or "").upper() != "PNG":
            raise ValueError("fatal screen artwork is not a png")

        image = ImageOps.fit(
            opened.convert("RGB"),
            size,
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.5),
        ).convert("RGBA")
        pixels = image.tobytes("raw", "BGRA")

    if len(pixels) != size[0] * size[1] * 4:
        raise RuntimeError("fatal screen artwork returned an invalid surface")

    FATALIMAGECACHE = pixels
    FATALIMAGECACHESIZE = size
    return pixels


def wrapfatalfailure(text, size, width):

    words = normalisefatalfailure(text).split()
    lines = []
    current = ""

    for word in words:
        candidate = word if not current else current + " " + word

        if not current or measuretext(candidate, int(size), fontpath=FATALFONT) <= int(width):
            current = candidate
            continue

        lines.append(current)
        current = word

        if len(lines) >= 2:
            break

    if current and len(lines) < 3:
        lines.append(current)

    consumed = " ".join(lines)

    if len(consumed) < len(normalisefatalfailure(text)) and lines:
        last = lines[-1]

        while last and measuretext(last + "...", int(size), fontpath=FATALFONT) > int(width):
            last = last[:-1].rstrip()

        lines[-1] = (last + "...") if last else "..."

    return lines or ["system failure - unknown fatal failure"]


def drawfatalcpu():

    width = max(1, int(gr._xres))
    height = max(1, int(gr._yres))
    scale = min(width / float(BASEW), height / float(BASEH))
    titlefont = max(22, int(round(58 * scale)))
    failurefont = max(15, int(round(28 * scale)))
    statusfont = max(15, int(round(26 * scale)))
    maxtextwidth = max(240, int(round(width * 0.58)))

    resetdirty()
    clear(0x000000)

    try:
        pixels = fatalimagepixels(width, height)
        blitbytesfast(pixels, width, height, 0, 0, width, height, 0, 0, "BGRA32")
    except Exception:
        # The error path must remain presentable even if the artwork or image
        # catalogue is the component that failed.
        clear(0x000000)

    title = "FATAL SYSTEM ERROR"
    titlewidth = measuretext(title, titlefont, fontpath=FATALBOLDFONT)
    titley = int(round(height * 0.34))
    drawtextttf(
        (width - titlewidth) // 2,
        titley,
        title,
        0xFF2020,
        titlefont,
        fontpath=FATALBOLDFONT,
    )

    lines = wrapfatalfailure(FATALFAILURE, failurefont, maxtextwidth)
    lineheight = max(failurefont + 8, int(round(failurefont * 1.35)))
    failurey = int(round(height * 0.47))

    for index, line in enumerate(lines):
        linewidth = measuretext(line, failurefont, fontpath=FATALFONT)
        drawtextttf(
            (width - linewidth) // 2,
            failurey + index * lineheight,
            line,
            0xFFFFFF,
            failurefont,
            fontpath=FATALFONT,
        )

    status = "restarting..."
    statuswidth = measuretext(status, statusfont, fontpath=FATALFONT)
    statusy = max(
        failurey + len(lines) * lineheight + int(round(34 * scale)),
        int(round(height * 0.64)),
    )
    drawtextttf(
        (width - statuswidth) // 2,
        statusy,
        status,
        0xFFFFFF,
        statusfont,
        fontpath=FATALFONT,
    )

# window server functions
def wsscreensize():

    try:

        p = f"{STATEBASE}/fb.size"

        with open(p) as f:
            txt = f.read().strip()

        txt = txt.replace("x", " ").replace("X", " ")

        parts = txt.split()

        if len(parts) >= 2:

            return (int(parts[0]), int(parts[1]))

    except FileNotFoundError:

        return (0, 0)

    except PermissionError:

        return (0, 0)

    except Exception:

        return (0, 0)

    return (0, 0)


def wsdamage(WSSOCK, WSWINID):

    try:

        rect = getdirty()

        if rect is None:

            rect = [0, 0, gr._xres, gr._yres]

        else:

            x, y, w, h = rect
            rect = [int(x), int(y), int(w), int(h)]

        wssend(sock, {
            "op": "DAMAGE",
            "winid": int(winid),
            "rect": rect
        })

        resetdirty()

    except Exception:

        try:
            resetdirty()
        except Exception:
            pass


def wsconnect():

    try:

        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

    except Exception:
        return None

    try:

        s.connect('/.ephemeral/windowserver/accept.sock')

    except Exception:

        try:
            s.close()
        except Exception:
            pass

        return None

    try:

        s.settimeout(0.25)

    except Exception:
        pass

    return s


def wssend(sock, obj):

    try:

        if not sock:
            return None

        line = (json.dumps(obj, separators=(",", ":")) + "\n").encode("utf-8")

        sock.sendall(line)

    except Exception:
        return None

    try:

        data = b""

        while b"\n" not in data:

            chunk = sock.recv(4096)

            if not chunk:
                break

            data += chunk

        if not data:
            return None

        raw = data.split(b"\n", 1)[0].decode("utf-8", errors="replace").strip()

        if not raw:
            return None

        return json.loads(raw)

    except Exception:
        return None


def wssendoneway(sock, obj):

    try:

        if not sock:
            return

        line = (json.dumps(obj, separators=(",", ":")) + "\n").encode("utf-8")

        sock.sendall(line)

    except Exception:
        return


def wscursor(enabled):

    sock = wsconnect()

    if not sock:
        return

    try:

        wssend(sock, {"op": "HELLO"})

        wssend(sock, {"op": "CURSOR_SET", "enabled": bool(enabled)})

    except Exception:
        pass

    try:
        sock.close()
    except Exception:
        pass


def wsrecvmsgs():

    global WSSOCK, WSINBUF

    out = []

    if not WSSOCK:
        return out

    try:

        while True:

            chunk = WSSOCK.recv(4096)

            if not chunk:
                break

            WSINBUF += chunk

            while True:

                idx = WSINBUF.find(b"\n")

                if idx == -1:
                    break

                raw = WSINBUF[:idx]

                WSINBUF = WSINBUF[idx + 1:]

                txt = raw.decode("utf-8", errors="replace").strip()

                if not txt:
                    continue

                try:

                    out.append(json.loads(txt))

                except Exception:

                    continue

    except BlockingIOError:

        pass

    except Exception:

        pass

    return out


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


def wswaitresize(winid, w, h, timeout=1.0):

    global WSDEFERRED

    deadline = time.monotonic() + max(0.05, float(timeout))
    deferred = []
    ready = False

    while time.monotonic() < deadline and not ready:

        for msg in wsrecvmsgs():

            if not isinstance(msg, dict):
                continue

            op = str(msg.get("op", ""))

            if op in ("GRAPHICS_COMMITTED", "GRAPHICS_CLEARED"):

                graphicsresponse(msg)
                continue

            if op == "ERROR" and str(msg.get("code", "")).startswith("graphics_"):

                graphicsresponse(msg)
                continue

            if op == "RESIZED":

                try:

                    ready = (
                        int(msg.get("winid", 0)) == int(winid)
                        and int(msg.get("w", 0)) == int(w)
                        and int(msg.get("h", 0)) == int(h)
                    )

                except Exception:

                    ready = False

                continue

            deferred.append(msg)

        if not ready:
            time.sleep(0.005)

    if deferred:
        WSDEFERRED.extend(deferred)

    return bool(ready)


def wshandlemsg(msg):

    global SCREENW, SCREENH, WSSOCK, WSWINID, WSBUF

    try:

        op = str(msg.get("op", ""))

    except Exception:

        op = ""

    if op in ("GRAPHICS_COMMITTED", "GRAPHICS_CLEARED"):

        graphicsresponse(msg)
        return

    if op == "ERROR" and str(msg.get("code", "")).startswith("graphics_"):

        graphicsresponse(msg)
        return

    if op != "FB_SIZE":
        return

    try:

        nw = int(msg.get("w", 0))

        nh = int(msg.get("h", 0))

    except Exception:

        return

    if nw <= 0 or nh <= 0:
        return

    if nw == int(SCREENW) and nh == int(SCREENH):
        return

    if not WSSOCK or int(WSWINID) <= 0 or not WSBUF:

        SCREENW = int(nw)
        SCREENH = int(nh)
        return

    # The shared buffer must not be remapped at a larger size until the
    # windowserver has completed its resize. Mapping beyond the current file
    # length can SIGBUS the animation on the next draw.
    wssendoneway(WSSOCK, {"op": "RESIZE", "winid": int(WSWINID), "w": int(nw), "h": int(nh)})

    if not wswaitresize(WSWINID, nw, nh):
        return

    if not waitbufferready(WSBUF, nw, nh):
        return

    try:

        gr.initbuffer(WSBUF, int(nw), int(nh))

    except Exception:

        return

    SCREENW = int(nw)
    SCREENH = int(nh)

    updatemetrics()

    if not graphicsmanagedonly():

        drawcurrentcpu()

        if REALPRESENT is not None:

            REALPRESENT()

    managedmarkdamage(GRAPHICSSTATE, [0, 0, int(SCREENW), int(SCREENH)], bounds=(int(SCREENW), int(SCREENH)))

    managed = graphicspump()

    if not managed:
        graphicsdamage()

    resetdirty()


def wspoll():

    global WSDEFERRED

    msgs = list(WSDEFERRED)
    WSDEFERRED = []
    msgs.extend(wsrecvmsgs())

    for m in msgs:

        if isinstance(m, dict):

            wshandlemsg(m)


# draw functions
def updatemetrics():

    global SCREENW, SCREENH, BOOTSCALE, BOOTFONT, BOOTSPACING, BOOTPADSMALL, BOOTPADBIG

    w = int(SCREENW)

    h = int(SCREENH)

    if w <= 0 or h <= 0:

        BOOTSCALE = 1.0

        BOOTFONT = int(BASEFONT)

        BOOTSPACING = int(BASEFONT)

        BOOTPADSMALL = 12

        BOOTPADBIG = 20
        return

    sx = w / float(BASEW)

    sy = h / float(BASEH)

    BOOTSCALE = min(sx, sy)

    BOOTFONT = int(round(BASEFONT * BOOTSCALE))

    if BOOTFONT < 8:
        BOOTFONT = 8

    BOOTSPACING = int(round(BASEFONT * BOOTSCALE))

    if BOOTSPACING < 8:
        BOOTSPACING = 8

    BOOTPADSMALL = int(round(12 * BOOTSCALE))

    if BOOTPADSMALL < 2:
        BOOTPADSMALL = 2

    BOOTPADBIG = int(round(20 * BOOTSCALE))

    if BOOTPADBIG < 4:
        BOOTPADBIG = 4


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
        cpu=GRAPHICSCPUOVERRIDE or not os.path.isfile('/the one/resources/fonts/cambria.ttf'),
    )
    graphicssyncstate()


def graphicssend(request):

    if not WSSOCK:
        return False

    wssendoneway(WSSOCK, request)
    return True


def graphicsdamage():

    try:

        if WSSOCK and WSWINID:
            wssendoneway(WSSOCK, {"op": "DAMAGE", "winid": int(WSWINID), "rect": [0, 0, int(SCREENW), int(SCREENH)]})

    except Exception:

        pass


def graphicsrestorecpu():

    try:

        drawcurrentcpu()

        if REALPRESENT is not None:
            REALPRESENT()

        resetdirty()
        graphicsdamage()
        return True

    except Exception:

        graphicsdamage()
        return False


def graphicsdisable(reason, clearcommands=True):

    if manageddisable(GRAPHICSSTATE, reason):
        graphicssyncstate()
        return True

    if clearcommands and WSSOCK and WSWINID:
        wssendoneway(WSSOCK, {"op": "GRAPHICS_CLEAR", "winid": int(WSWINID)})

    graphicssyncstate()
    graphicsrestorecpu()
    return False


def graphicsresponse(msg):

    try:

        if WSWINID and "winid" in msg and int(msg.get("winid", 0)) != int(WSWINID):
            return False

    except Exception:

        return False

    before = bool(GRAPHICSSTATE.get("available"))
    handled = managedresponse(GRAPHICSSTATE, msg)
    graphicssyncstate()

    if before and not GRAPHICSSTATE.get("available"):

        if msg.get("code") != "graphics_clear_failed" and WSSOCK and WSWINID:
            wssendoneway(WSSOCK, {"op": "GRAPHICS_CLEAR", "winid": int(WSWINID)})

        graphicsrestorecpu()

    return bool(handled)


def graphicstexty(y, size):

    try:

        face = getttfface('/the one/resources/fonts/cambria.ttf')

        if face is None:
            return int(y)

        face.set_pixel_sizes(0, int(size))
        ascender = int(face.size.ascender >> 6)
        return int(y) + int(size) - ascender

    except Exception:

        return int(y)


def powerlayout(width):

    label = str(POWERLABEL)
    fullwidth = int(measuretext(label + "...", int(BOOTFONT), fontpath=POWERFONT))
    spacing = int(BOOTSPACING)
    labelx = (int(width) - fullwidth) // 2
    dotpositions = {
        -spacing: labelx + int(measuretext(label, int(BOOTFONT), fontpath=POWERFONT)),
        0: labelx + int(measuretext(label + ".", int(BOOTFONT), fontpath=POWERFONT)),
        spacing: labelx + int(measuretext(label + "..", int(BOOTFONT), fontpath=POWERFONT)),
    }
    return labelx, dotpositions


def graphicsbuildscene():

    global GRAPHICSBUILDTOTALMS, GRAPHICSBUILDMAXIMUMMS, GRAPHICSBUILDCOUNT

    started = time.monotonic_ns()
    width = max(1, int(SCREENW))
    height = max(1, int(SCREENH))
    clip = [0, 0, width, height]
    commands = [{
        "kind": "rectangle",
        "rect": [0, 0, width, height],
        "color": 0x000000,
        "clip": list(clip),
    }]

    try:

        if BOOTPHASE == "title":

            intensity = max(0, min(255, int(BOOTINTENSITY)))
            color = (intensity << 16) | (intensity << 8) | intensity
            text = "The One"
            textwidth = measuretext(text, int(BOOTFONT), fontpath='/the one/resources/fonts/cambria.ttf')
            x = (width - int(textwidth)) // 2
            y = (height - int(BOOTFONT)) // 2
            commands.append({
                "kind": "text",
                "x": int(x),
                "y": graphicstexty(y, BOOTFONT),
                "text": text,
                "size": int(BOOTFONT),
                "font": '/the one/resources/fonts/cambria.ttf',
                "color": int(color),
                "clip": list(clip),
            })

        elif BOOTPHASE == "dots":

            centerx = width // 2
            y = (height - int(BOOTFONT)) // 2

            for offset in BOOTDOTS:

                commands.append({
                    "kind": "text",
                    "x": int(centerx + int(offset)),
                    "y": graphicstexty(y, BOOTFONT),
                    "text": ".",
                    "size": int(BOOTFONT),
                    "font": '/the one/resources/fonts/cambria.ttf',
                    "color": 0xFFFFFF,
                    "clip": list(clip),
                })

        elif BOOTPHASE == "power":

            y = (height - int(BOOTFONT)) // 2
            labelx, dotpositions = powerlayout(width)
            commands.append({
                "kind": "text",
                "x": int(labelx),
                "y": graphicstexty(y, BOOTFONT),
                "text": str(POWERLABEL),
                "size": int(BOOTFONT),
                "font": POWERFONT,
                "color": 0xFFFFFF,
                "clip": list(clip),
            })

            for offset in BOOTDOTS:

                commands.append({
                    "kind": "text",
                    "x": int(dotpositions.get(int(offset), dotpositions[0])),
                    "y": graphicstexty(y, BOOTFONT),
                    "text": ".",
                    "size": int(BOOTFONT),
                    "font": POWERFONT,
                    "color": 0xFFFFFF,
                    "clip": list(clip),
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

        if wasavailable and WSSOCK and WSWINID:
            wssendoneway(WSSOCK, {"op": "GRAPHICS_CLEAR", "winid": int(WSWINID)})
            graphicsrestorecpu()

        graphicssyncstate()
        return False

    if not GRAPHICSSTATE.get("available") or not WSSOCK or not WSWINID:
        return False

    if GRAPHICSSTATE.get("pending") or not GRAPHICSSTATE.get("need_submit"):

        graphicssyncstate()
        return bool(GRAPHICSSTATE.get("active"))

    commands = graphicsbuildscene()

    if not commands or commands[0].get("rect") != [0, 0, int(SCREENW), int(SCREENH)]:

        graphicsdisable("managed boot scene does not contain a complete background")
        return False

    before = bool(GRAPHICSSTATE.get("available"))
    managedsubmit(GRAPHICSSTATE, graphicssend, int(WSWINID), commands)

    if before and not GRAPHICSSTATE.get("available"):

        wssendoneway(WSSOCK, {"op": "GRAPHICS_CLEAR", "winid": int(WSWINID)})
        graphicsrestorecpu()

    graphicssyncstate()
    return bool(GRAPHICSSTATE.get("active"))


def graphicspresent(rect):

    if not GRAPHICSSTATE.get("available"):
        return False

    managedmarkdamage(
        GRAPHICSSTATE,
        rect or [0, 0, int(SCREENW), int(SCREENH)],
        bounds=(int(SCREENW), int(SCREENH)),
    )
    return graphicspump()


def graphicswaitinitial(timeout=0.5):

    deadline = time.monotonic() + max(0.05, float(timeout))

    while (GRAPHICSSTATE.get("pending") or GRAPHICSSTATE.get("need_submit")) and time.monotonic() < deadline:

        if not GRAPHICSSTATE.get("pending") and GRAPHICSSTATE.get("need_submit"):
            graphicspump()

        wspoll()
        time.sleep(0.005)

    if GRAPHICSSTATE.get("pending") or GRAPHICSSTATE.get("need_submit"):
        graphicsdisable("initial managed boot scene did not commit")

    return bool(GRAPHICSSTATE.get("active"))


def bootwait(duration):

    deadline = time.monotonic() + max(0.0, float(duration))

    while time.monotonic() < deadline:

        wspoll()
        graphicspump()
        time.sleep(min(0.01, max(0.0, deadline - time.monotonic())))


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
            bootwait(target - time.monotonic())

        now = time.monotonic()
        progress = animationprogress(started, duration, now)
        yield progress

        if progress >= 1.0:
            return

        elapsedframes = int(max(0.0, now - started) / ANIMATIONFRAMETIME)
        frameindex = max(frameindex + 1, elapsedframes + 1)


def drawcurrentcpu():

    resetdirty()
    clear(0x000000)

    if BOOTPHASE == "title":

        intensity = max(0, min(255, int(BOOTINTENSITY)))
        color = (intensity << 16) | (intensity << 8) | intensity
        width = measuretext("The One", int(BOOTFONT))
        x = (gr._xres - width) // 2
        y = (gr._yres - int(BOOTFONT)) // 2
        drawtextttf(x, y, "The One", color, int(BOOTFONT))

    elif BOOTPHASE == "dots":

        centerx = gr._xres // 2
        y = (gr._yres - int(BOOTFONT)) // 2

        for offset in BOOTDOTS:
            drawtextttf(centerx + int(offset), y, '.', 0xFFFFFF, int(BOOTFONT))

    elif BOOTPHASE == "power":

        y = (gr._yres - int(BOOTFONT)) // 2
        labelx, dotpositions = powerlayout(gr._xres)
        drawtextttf(
            labelx,
            y,
            str(POWERLABEL),
            0xFFFFFF,
            int(BOOTFONT),
            fontpath=POWERFONT
        )

        for offset in BOOTDOTS:
            drawtextttf(
                int(dotpositions.get(int(offset), dotpositions[0])),
                y,
                '.',
                0xFFFFFF,
                int(BOOTFONT),
                fontpath=POWERFONT
            )

    elif BOOTPHASE == "fatal":

        drawfatalcpu()


def presentwrap():

    global REALPRESENT, WSSOCK, WSWINID, SCREENW, SCREENH

    if REALPRESENT is None:
        return

    if not graphicsmanagedonly():

        try:

            REALPRESENT()

        except Exception:

            return

    try:

        rect = getdirty()

        if rect is None:

            rect = [0, 0, int(SCREENW), int(SCREENH)]

        else:

            x, y, w, h = rect
            rect = [int(x), int(y), int(w), int(h)]

        managed = graphicspresent(rect)

        if not managed:
            wssendoneway(WSSOCK, {"op": "DAMAGE", "winid": int(WSWINID), "rect": rect})

        resetdirty()

    except Exception:

        try:
            resetdirty()
        except Exception:
            pass

    # pump any async server events (including FB_SIZE)
    try:

        wspoll()

    except Exception:

        pass


def drawtheone(intensity):

    global BOOTPHASE, BOOTINTENSITY, BOOTDOTS

    BOOTPHASE = "title"
    BOOTINTENSITY = int(intensity)
    BOOTDOTS = []

    clear(0x000000)

    col = (intensity<<16)|(intensity<<8)|intensity

    w = measuretext("The One", int(BOOTFONT))

    x = (gr._xres - w)//2

    y = (gr._yres - int(BOOTFONT))//2

    drawtextttf(x, y, "The One", col, int(BOOTFONT))


def fadein():

    global BOOTPHASE, BOOTINTENSITY, BOOTDOTS

    text = "The One"

    for progress in animationtimeline(BRANDFADETIME):

        intensity = int(round(progress * 0xFF))

        color = (intensity << 16) | (intensity << 8) | intensity

        BOOTPHASE = "title"
        BOOTINTENSITY = int(intensity)
        BOOTDOTS = []

        resetdirty()

        w = measuretext(text, int(BOOTFONT))

        x = (gr._xres - w) // 2

        y = (gr._yres - int(BOOTFONT)) // 2

        pad = int(BOOTPADSMALL)

        fillrectfast(x - pad, y - pad, w + pad * 2, int(BOOTFONT) + pad * 2, 0x000000)

        drawtextttf(x, y, text, color, int(BOOTFONT))

        present()


def fadeout():

    global BOOTPHASE, BOOTINTENSITY, BOOTDOTS

    text = "The One"

    for progress in animationtimeline(BRANDFADETIME):

        intensity = int(round((1.0 - progress) * 0xFF))

        color = (intensity << 16) | (intensity << 8) | intensity

        BOOTPHASE = "title"
        BOOTINTENSITY = int(intensity)
        BOOTDOTS = []

        resetdirty()

        w = measuretext(text, int(BOOTFONT))

        x = (gr._xres - w) // 2

        y = (gr._yres - int(BOOTFONT)) // 2

        pad = int(BOOTPADSMALL)

        fillrectfast(x - pad, y - pad, w + pad * 2, int(BOOTFONT) + pad * 2, 0x000000)

        drawtextttf(x, y, text, color, int(BOOTFONT))

        present()


def dotframes():

    spacing = int(BOOTSPACING)

    return [
        [-spacing],
        [-spacing, 0],
        [-spacing, 0, spacing],
        [0, spacing],
        [spacing],
    ]


def drawdotframe(frame):

    global WSSOCK, WSWINID, BOOTPHASE, BOOTINTENSITY, BOOTDOTS, BOOTDOTFRAME

    spacing = int(BOOTSPACING)

    centx = gr._xres // 2

    centy = (gr._yres - int(BOOTFONT)) // 2

    BOOTPHASE = "dots"
    BOOTINTENSITY = 0
    BOOTDOTS = list(frame)

    try:
        BOOTDOTFRAME = dotframes().index(list(frame))
    except ValueError:
        BOOTDOTFRAME = 0

    resetdirty()

    pad = int(BOOTPADBIG)

    fillrectfast(
        centx - spacing - pad,
        centy - pad,
        (spacing * 2) + (pad * 2),
        int(BOOTFONT) + (pad * 2),
        0x000000
    )

    for offs in frame:
        drawtextttf(centx + offs, centy, '.', 0xFFFFFF, int(BOOTFONT))

    present()


def drawpowerframe(label, frame):

    global BOOTPHASE, BOOTINTENSITY, BOOTDOTS, POWERLABEL

    BOOTPHASE = "power"
    BOOTINTENSITY = 0
    BOOTDOTS = list(frame)
    POWERLABEL = str(label)
    resetdirty()
    clear(0x000000)
    drawcurrentcpu()
    present()


def drawfatalframe():

    global BOOTPHASE, BOOTINTENSITY, BOOTDOTS

    BOOTPHASE = "fatal"
    BOOTINTENSITY = 0
    BOOTDOTS = []
    drawfatalcpu()
    present()


def fatalloop():

    while True:

        if controlrequest() is not None:
            return

        bootwait(0.10)


def powerloop(label):

    frames = dotframes()
    frameindex = 1

    while True:

        if controlrequest() is not None:
            return

        drawpowerframe(label, frames[frameindex])
        frameindex = (frameindex + 1) % len(frames)
        bootwait(DOTFRAMETIME)


def progressloop(firstshown, firstframe=0):

    frames = dotframes()
    frameindex = (int(firstframe) + 1) % len(frames)
    pending = None

    while True:

        if pending is None:
            pending = controlrequest()

        if (
            pending is not None
            and time.monotonic() - float(firstshown) >= float(DOTMINIMUMTIME)
        ):
            return pending

        drawdotframe(frames[frameindex])
        frameindex = (frameindex + 1) % len(frames)
        bootwait(DOTFRAMETIME)


def brandsequence():

    fadein()
    bootwait(BRANDHOLDTIME)
    fadeout()

    global BOOTPHASE, BOOTINTENSITY, BOOTDOTS

    BOOTPHASE = "black"
    BOOTINTENSITY = 0
    BOOTDOTS = []
    resetdirty()
    clear(0x000000)
    present()
    graphicswaitinitial()


def earlydots():

    global SCREENW, SCREENH

    controlprepare()

    try:

        gr.init('/the one/drivers/nodes/fb0', backend='framebuffer')
        SCREENW = int(gr._xres)
        SCREENH = int(gr._yres)
        updatemetrics()
        initttffont('/the one/resources/fonts/cambria.ttf', int(BOOTFONT))
        resetdirty()
        clear(0x000000)
        drawdotframe(dotframes()[0])
        firstshown = time.monotonic()
        controlstate("dots", mode="early-dots")
        progressloop(firstshown)

    except Exception:

        controlstate("unavailable", mode="early-dots")

    finally:

        try:
            gr.close()
        except Exception:
            pass

        controlstate("done", mode="early-dots")

# graphics diagnostic
def graphicsdiagnostic():

    global SCREENW, SCREENH, BOOTPHASE, BOOTINTENSITY, BOOTDOTS, POWERLABEL
    global GRAPHICSBUILDTOTALMS, GRAPHICSBUILDMAXIMUMMS, GRAPHICSBUILDCOUNT
    global WSDEFERRED

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
        updatemetrics()
        initttffont('/the one/resources/fonts/cambria.ttf', int(BOOTFONT))
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
        GRAPHICSBUILDTOTALMS = 0.0
        GRAPHICSBUILDMAXIMUMMS = 0.0
        GRAPHICSBUILDCOUNT = 0
        BOOTPHASE = "black"
        BOOTINTENSITY = 0
        BOOTDOTS = []
        black = graphicsbuildscene()
        BOOTPHASE = "title"
        BOOTINTENSITY = 128
        title = graphicsbuildscene()
        dotcounts = []

        for offsets in ([-BOOTSPACING], [-BOOTSPACING, 0], [-BOOTSPACING, 0, BOOTSPACING]):

            BOOTPHASE = "dots"
            BOOTINTENSITY = 0
            BOOTDOTS = list(offsets)
            dots = graphicsbuildscene()
            dotcounts.append(len([command for command in dots if command.get("kind") == "text"]))

        POWERLABEL = "shutting down"
        powerscenes = []

        for offsets in dotframes():

            BOOTPHASE = "power"
            BOOTDOTS = list(offsets)
            powerscenes.append(graphicsbuildscene())

        BOOTPHASE = "black"
        BOOTDOTS = []
        finalblack = graphicsbuildscene()

        for scene in (black, title, finalblack):

            if not scene or scene[0].get("kind") != "rectangle" or scene[0].get("rect") != [0, 0, 2560, 1440]:
                raise RuntimeError("boot phase did not begin with an opaque full-screen background")

        if len(black) != 1 or len(finalblack) != 1:
            raise RuntimeError("black boot phases contained stale animation commands")

        if len(title) != 2 or title[1].get("text") != "The One":
            raise RuntimeError("title boot phase did not contain The One")

        expectedcolor = (128 << 16) | (128 << 8) | 128

        if int(title[1].get("color", -1)) != expectedcolor:
            raise RuntimeError("title boot phase did not preserve fade intensity")

        fadesamples = [
            animationprogress(10.0, BRANDFADETIME, 10.0),
            animationprogress(10.0, BRANDFADETIME, 10.0 + (BRANDFADETIME / 2.0)),
            animationprogress(10.0, BRANDFADETIME, 10.0 + BRANDFADETIME),
        ]
        minimumfadeframes = int(BRANDFADETIME / ANIMATIONFRAMETIME) + 1

        if (
            any(
                abs(actual - expected) > 0.000001
                for actual, expected in zip(fadesamples, (0.0, 0.5, 1.0))
            ) or
            abs(ANIMATIONREFRESHHZ - 60.0) > 0.001 or
            minimumfadeframes < 20
        ):
            raise RuntimeError("title fade is not time-based at the display animation rate")

        if dotcounts != [1, 2, 3]:
            raise RuntimeError("boot dot phases did not preserve their animation frames")

        powercounts = [
            len([command for command in scene if command.get("kind") == "text"])
            for scene in powerscenes
        ]

        if powercounts != [2, 3, 4, 3, 2]:
            raise RuntimeError("power dots did not preserve the five boot animation frames")

        labelpositions = [
            int(next(command for command in scene if command.get("text") == POWERLABEL).get("x", -1))
            for scene in powerscenes
        ]

        if len(set(labelpositions)) != 1:
            raise RuntimeError("power label moved while its dots animated")

        completepower = powerscenes[2]
        labelcommand = next(command for command in completepower if command.get("text") == POWERLABEL)
        dotcommands = [command for command in completepower if command.get("text") == "."]
        fullwidth = int(measuretext(POWERLABEL + "...", int(BOOTFONT), fontpath=POWERFONT))
        expectedleft = (SCREENW - fullwidth) // 2
        expecteddots = [
            expectedleft + int(measuretext(POWERLABEL + ("." * index), int(BOOTFONT), fontpath=POWERFONT))
            for index in range(3)
        ]

        if int(labelcommand.get("x", -1)) != expectedleft:
            raise RuntimeError("power label and reserved ellipsis were not centered as one block")

        if [int(command.get("x", -1)) for command in dotcommands] != expecteddots:
            raise RuntimeError("power dots did not use their natural positions in the complete string")

        if any(command.get("font") != POWERFONT for command in completepower[1:]):
            raise RuntimeError("power text did not use the Atkinson UI font")

        result["checks"]["opaque_background"] = True
        result["checks"]["first_frame_complete"] = True
        result["checks"]["title_fade"] = True
        result["checks"]["title_fade_pacing"] = {
            "duration_ms": int(round(BRANDFADETIME * 1000.0)),
            "target_hz": float(ANIMATIONREFRESHHZ),
            "minimum_frames": int(minimumfadeframes),
        }
        result["checks"]["dot_frames"] = dotcounts
        result["checks"]["power_dot_frames"] = powercounts
        result["checks"]["power_dot_spacing"] = True
        result["checks"]["power_font"] = POWERFONT
        result["checks"]["power_text_centered"] = True
        result["checks"]["final_black"] = True
        requests = []
        state = managedstate()
        managedconfigure(state, capabilities, required=("rectangle", "text"))
        managedmarkdamage(state, [0, 0, 2560, 1440], bounds=(2560, 1440))
        managedsubmit(state, lambda request: requests.append(request) or True, 101, title)

        if len(requests) != 1 or requests[0].get("op") != "GRAPHICS_SCENE":
            raise RuntimeError("boot animation did not submit one atomic scene")

        managedresponse(state, {
            "op": "GRAPHICS_COMMITTED",
            "winid": 101,
            "count": len(title),
            "batch": True,
            "accelerated": True,
            "managed_only": True,
        })

        if not state.get("active") or state.get("pending"):
            raise RuntimeError("boot animation did not activate after acknowledgement")

        result["checks"]["atomic_scene"] = {
            "messages": len(requests),
            "commands": len(title),
            "damage": len(requests[0].get("damage", [])),
        }

        originalrecv = globals()["wsrecvmsgs"]
        WSDEFERRED = []
        resizeevents = [[
            {"op": "FB_SIZE", "w": 1600, "h": 900},
            {"op": "RESIZED", "winid": 101, "w": 800, "h": 600},
        ]]

        try:

            globals()["wsrecvmsgs"] = lambda: resizeevents.pop(0) if resizeevents else []

            if not wswaitresize(101, 800, 600, timeout=0.05):
                raise RuntimeError("boot resize did not wait for the matching window acknowledgement")

            if len(WSDEFERRED) != 1 or WSDEFERRED[0].get("op") != "FB_SIZE":
                raise RuntimeError("boot resize acknowledgement discarded a newer framebuffer event")

        finally:

            globals()["wsrecvmsgs"] = originalrecv
            WSDEFERRED = []

        result["checks"]["resize_acknowledgement"] = True
        result["checks"]["command_budget"] = {
            "commands": 4,
            "limit": int(state.get("command_limit", 0)),
        }
        fallback = managedstate(cpu=True)
        managedconfigure(fallback, capabilities, required=("rectangle", "text"))
        missing = managedstate()
        managedconfigure(missing, {}, required=("rectangle", "text"))
        rejected = managedstate()
        managedconfigure(rejected, capabilities, required=("rectangle", "text"))
        rejected["winid"] = 102
        managedresponse(rejected, {"op": "ERROR", "winid": 102, "code": "graphics_scene_failed", "detail": "diagnostic"})
        timedout = managedstate()
        managedconfigure(timedout, capabilities, required=("rectangle", "text"))
        timedout["pending"] = True
        timedout["pending_at"] = time.monotonic() - 3.0
        managedtick(timedout, timeout=0.1)

        if fallback.get("available") or missing.get("available"):
            raise RuntimeError("a boot-animation non-GPU fallback path remained managed")

        if not all(
            item.get("available")
            and item.get("active")
            and item.get("managed_only")
            and item.get("need_submit")
            for item in (rejected, timedout)
        ):
            raise RuntimeError("boot-animation recovery escaped strict GPU rendering")

        result["checks"]["cpu_fallback"] = True
        result["checks"]["missing_capability_fallback"] = True
        result["checks"]["error_gpu_retention"] = True
        result["checks"]["timeout_gpu_retention"] = True
        result["checks"]["first_frame_before_map"] = True
        result["checks"]["final_commit_before_unmap"] = True
        result["checks"]["cursor_finally_restore"] = True
        result["performance"] = {
            "average_scene_build_ms": round(GRAPHICSBUILDTOTALMS / max(1, GRAPHICSBUILDCOUNT), 3),
            "maximum_scene_build_ms": round(GRAPHICSBUILDMAXIMUMMS, 3),
            "maximum_commands": 4,
        }
        result["passed"] = True

    except Exception as e:

        result["errors"].append(str(e))

    return result


def graphicsdiagnosticcommand():

    result = graphicsdiagnostic()
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result.get("passed") else 1


# core function
def main(mode="brand"):

    global present, WSSOCK, WSWINID, SCREENW, SCREENH, WSBUF, REALPRESENT
    global GRAPHICSCAPS, BOOTPHASE, BOOTINTENSITY, BOOTDOTS, FATALFAILURE

    mode = str(mode or "brand").strip().lower()
    configurecontrol(mode)

    if mode == "early-dots":
        earlydots()
        return

    # connect windowserver
    sock = wsconnect()

    if not sock:
        return

    # handshake and capture framebuffer size from WELCOME
    try:

        welcome = wssend(sock, {"op": "HELLO"})

    except Exception:

        try:
            sock.close()
        except Exception:
            pass

        return

    sw = 0

    sh = 0

    try:

        fb = welcome.get("fb", {})

        sw = int(fb.get("w", 0))

        sh = int(fb.get("h", 0))

    except Exception:

        sw = 0

        sh = 0

    try:

        GRAPHICSCAPS = dict(welcome.get("graphics", {}))

    except Exception:

        GRAPHICSCAPS = {}

    graphicsconfigure(GRAPHICSCAPS)

    if sw <= 0 or sh <= 0:

        sw = 1920

        sh = 1080

    # handshake and create boot window
    try:

        powertransition = mode in ("poweroff", "restart")
        systemtransition = powertransition or mode == "fatal"
        created = wssend(sock, {
            "op": "CREATE_WINDOW",
            "x": 0,
            "y": 0,
            "w": int(sw),
            "h": int(sh),
            "title": "fatal system error" if mode == "fatal" else (f"{mode} animation" if powertransition else "boot animation"),
            "role": "system animation" if systemtransition else "boot animation",
            "shadow": False
        })

    except Exception:

        try:
            sock.close()
        except Exception:
            pass

        return

    if not created or created.get("op") != "WINDOW_CREATED":

        try:
            sock.close()
        except Exception:
            pass

        return

    try:

        winid = int(created.get("winid", 0))

        bufpath = str(created.get("buffer", ""))

    except Exception:

        try:
            sock.close()
        except Exception:
            pass

        return

    if winid <= 0 or not bufpath:

        try:
            sock.close()
        except Exception:
            pass

        return

    WSSOCK = sock

    WSWINID = int(winid)

    WSBUF = str(bufpath)

    SCREENW = int(sw)

    SCREENH = int(sh)

    updatemetrics()

    # subscribe to fb size change events
    try:

        wssend(sock, {"op": "SUBSCRIBE", "types": ["fbsize"]})

    except Exception:

        pass

    # make socket nonblocking so we can poll async events
    try:

        sock.setblocking(False)

    except Exception:

        pass

    # switch graphics into file-buffer mode
    try:

        gr.initbuffer(WSBUF, int(SCREENW), int(SCREENH))

    except Exception:

        try:
            sock.close()
        except Exception:
            pass

        return

    # wrap present() so all drawing emits DAMAGE and polls FB_SIZE
    REALPRESENT = present

    present = presentwrap

    if mode not in ("dots", "brand", "poweroff", "restart", "fatal"):
        mode = "brand"

    controlled = mode in ("dots", "poweroff", "restart", "fatal")
    powertransition = mode in ("poweroff", "restart")
    powerlabel = "shutting down" if mode == "poweroff" else "restarting"

    if controlled:
        controlprepare()

    if mode == "fatal":
        FATALFAILURE = readfatalcontent()

    initttffont('/the one/resources/fonts/cambria.ttf', int(BOOTFONT))

    firstdotframe = 0

    if mode == "dots":
        try:
            firstdotframe = int(os.environ.get("T1OS_BOOT_DOT_FRAME", "0"))
        except (TypeError, ValueError):
            firstdotframe = 0
        firstdotframe %= len(dotframes())
        drawdotframe(dotframes()[firstdotframe])
    elif powertransition:
        drawpowerframe(powerlabel, dotframes()[0])
    elif mode == "fatal":
        drawfatalframe()
    else:
        resetdirty()
        BOOTPHASE = "black"
        BOOTINTENSITY = 0
        BOOTDOTS = []
        clear(0x000000)
        present()

    # commit the complete opaque first frame before mapping
    graphicswaitinitial()

    mapped = False
    cursorhidden = False

    try:

        wssendoneway(sock, {"op": "MAP", "winid": int(winid)})
        mapped = True

        wscursor(False)
        cursorhidden = True

        if mode == "dots":

            firstshown = time.monotonic()
            controlstate("dots")
            action = progressloop(firstshown, firstdotframe)

            if action == "brand":
                controlstate("branding")
                brandsequence()
            else:
                controlstate("handoff")

        elif powertransition:

            controlstate("visible", mode=mode)
            powerloop(powerlabel)

        elif mode == "fatal":

            controlstate("visible", mode=mode)
            fatalloop()

        else:

            brandsequence()

    finally:

        if mapped:

            try:
                wssendoneway(sock, {"op": "UNMAP", "winid": int(winid)})
            except Exception:
                pass

        if controlled:

            # "done" is the visual handoff barrier, not a process-exit
            # notification.  Publish it as soon as the animation has requested
            # its unmap; cursor restoration uses a separate WindowServer
            # connection and may briefly wait behind the lock-screen page flip.
            # Publishing after that best-effort cleanup made Startup time out,
            # discard an already-presented lock screen, and launch one redundant
            # second boot animation.
            if mode == "dots":
                controlstate("done")
            else:
                controlstate("done", mode=mode)

        if cursorhidden:
            wscursor(True)

        # restore original present() before teardown
        present = REALPRESENT
        REALPRESENT = None

        try:
            sock.close()
        except Exception:
            pass


# execute main
if __name__ == '__main__':

    if len(sys.argv) > 1 and sys.argv[1].strip().lower() == 'graphics-diagnostic':

        sys.exit(graphicsdiagnosticcommand())

    mode = sys.argv[1] if len(sys.argv) > 1 else "brand"
    main(mode)
