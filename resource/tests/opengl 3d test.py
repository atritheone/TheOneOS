#!/bin/python3.13



"""
opengl 3d test.py

opengl 3d test is a standalone window for the controlled T1OS 3D graphics
API.  It does not change the appearance or behaviour of existing software.
"""



## imports
import os
import sys
import json
import time
import socket
import select

sys.path.insert(0, "/the one/build")

from graphics.graphics import initbuffer, clear, fillrectfast, drawtextttf, present
from graphics.graphics import managedstate, managedconfigure, manageddisable, managedclear
from graphics.graphics import managedmarkdamage, managedsubmit, managedresponse, managedtick
from graphics.graphics import managednode, managedrectangle, managedtext
from graphics.graphics import managedcamera3d, managedmaterial3d, managedmesh3d, managedscene3d



## globals

# paths
WINDOWSOCK = "/.ephemeral/windowserver/accept.sock"
WINDOWPATH = os.path.abspath(__file__)
IMAGEBASE = "/.ephemeral/opengl-3d-test"
IMAGEPATH = os.path.join(IMAGEBASE, "checker.raw")
STATUSPATH = os.path.join(IMAGEBASE, "status.json")
FONTFILE = "/the one/resources/fonts/atkinsonhyperlegiblenext.ttf"
RESULTPATH = "/the one/logs/opengl 3d test.json"
PROGRESSPATH = "/the one/logs/opengl 3d test progress.json"

# window
WINDOWTITLE = "OpenGL 3D capability test"
WINDOWWIDTH = 1220
WINDOWHEIGHT = 780
WINID = None
WINBUFFER = None
WINW = WINDOWWIDTH
WINH = WINDOWHEIGHT
MAPPED = False
RUNNING = True

# socket
SOCK = None
INBUF = b""
OUTBUF = b""

# graphics
CAPABILITIES = {}
GRAPHICSSTATE = managedstate()
GRAPHICSERROR = ""
GRAPHICSCLEARACK = False
SCENEDIRTY = False
SCENEDAMAGE = []
TELEMETRYTEXT = "waiting for graphics telemetry"
TELEMETRYDETAIL = "the server owns the shaders, depth resources, and animation clock"
LASTTELEMETRY = 0.0
BUTTONS = []
EFFECTS = ("none", "grayscale", "invert", "sepia")
EFFECTINDEX = 0
FOGENABLED = True
PERSPECTIVE = True
WIREFRAME = False
ANIMATING = True
FALLBACKRENDERS = 0

# automated live validation
ARGUMENTS = [str(value).strip().lower() for value in sys.argv[1:]]
AUTOTEST = any(value in ("live-test", "automated", "3dgputest", "3dsofttest", "3dcputest") for value in ARGUMENTS)
AUTOEXPECT = (
    "cpu"
    if "3dcputest" in ARGUMENTS or "cpu" in ARGUMENTS
    else ("software" if "3dsofttest" in ARGUMENTS or "software" in ARGUMENTS else "gpu")
)
AUTOPHASE = "wait"
AUTOPHASESTART = time.monotonic()
AUTOTELEMETRYPENDING = False
AUTOBASELINE = {}
AUTOERRORS = []
SOCKETPOLLINTERVAL = 0.005

# colours
BACKGROUND = 0x101217
PANEL = 0x181C23
PANELDARK = 0x0D1016
PANELBORDER = 0x343B48
TEXT = 0xF0F0F0
MUTED = 0x98A2B2
ACCENT = 0x68A8FF
GREEN = 0x52D68A
ORANGE = 0xFFB45C
PURPLE = 0xB28CFF
CYAN = 0x57D5E6



## socket functions
def sendmessage(message):

    global OUTBUF

    try:

        OUTBUF += json.dumps(message, separators=(",", ":")).encode("utf-8") + b"\n"
        return True

    except Exception:

        return False


def flushmessages():

    global OUTBUF

    if SOCK is None or not OUTBUF:
        return

    try:

        sent = SOCK.send(OUTBUF)
        OUTBUF = OUTBUF[sent:]

    except BlockingIOError:

        return


def receivemessages():

    global INBUF, RUNNING

    messages = []

    if SOCK is None:
        return messages

    try:

        while True:

            chunk = SOCK.recv(65536)

            if not chunk:

                RUNNING = False
                break

            INBUF += chunk

            if len(chunk) < 65536:
                break

    except BlockingIOError:

        pass

    while b"\n" in INBUF:

        line, INBUF = INBUF.split(b"\n", 1)

        if not line.strip():
            continue

        try:

            messages.append(json.loads(line.decode("utf-8")))

        except Exception:

            continue

    return messages


def pumpsocket(timeout=SOCKETPOLLINTERVAL):

    if SOCK is None:
        return

    readable = [SOCK]
    writable = [SOCK] if OUTBUF else []

    try:

        readyread, readywrite, _ = select.select(readable, writable, [], max(0.0, float(timeout)))

    except Exception:

        readyread = []
        readywrite = []

    if readywrite:
        flushmessages()

    if readyread:

        for message in receivemessages():
            handlemessage(message)

    if OUTBUF:
        flushmessages()



## texture functions
def writestatus(stage, **detail):

    try:
        os.makedirs(IMAGEBASE, exist_ok=True)
        os.chmod(IMAGEBASE, 0o711)
        payload = {
            "format": 1,
            "pid": os.getpid(),
            "stage": str(stage),
            "window_id": int(WINID) if WINID is not None else None,
            "active": bool(GRAPHICSSTATE.get("active")),
            "available": bool(GRAPHICSSTATE.get("available")),
            "pending": bool(GRAPHICSSTATE.get("pending")),
            "failure": str(GRAPHICSSTATE.get("failure") or GRAPHICSERROR),
        }
        payload.update(detail)
        with open(STATUSPATH, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
        os.chmod(STATUSPATH, 0o604)
    except Exception:
        pass


def createimage():

    os.makedirs(IMAGEBASE, exist_ok=True)
    os.chmod(IMAGEBASE, 0o711)
    width = 128
    height = 128

    with open(IMAGEPATH, "wb") as output:

        for y in range(height):

            for x in range(width):

                tile = ((x // 16) + (y // 16)) % 2
                red = 56 + int(145 * x / max(1, width - 1))
                green = 72 + int(125 * y / max(1, height - 1))
                blue = 235 if tile else 72
                output.write(bytes((blue, green, red, 255)))

    os.chmod(IMAGEPATH, 0o604)
    writestatus("image-ready", image_bytes=os.path.getsize(IMAGEPATH))


def removeimage():

    try:

        if os.path.isfile(IMAGEPATH):
            os.unlink(IMAGEPATH)

        if os.path.isdir(IMAGEBASE) and not os.listdir(IMAGEBASE):
            os.rmdir(IMAGEBASE)

    except Exception:

        pass



## 3D scene functions
def pyramidvertices():

    vertices = []

    def triangle(a, b, c, normal):

        vertices.extend((
            [*a, *normal, 0.0, 1.0],
            [*b, *normal, 1.0, 1.0],
            [*c, *normal, 0.5, 0.0],
        ))

    triangle((-1, -1, 1), (1, -1, 1), (0, 1, 0), (0, 0.707, 0.707))
    triangle((1, -1, 1), (1, -1, -1), (0, 1, 0), (0.707, 0.707, 0))
    triangle((1, -1, -1), (-1, -1, -1), (0, 1, 0), (0, 0.707, -0.707))
    triangle((-1, -1, -1), (-1, -1, 1), (0, 1, 0), (-0.707, 0.707, 0))
    triangle((-1, -1, -1), (1, -1, -1), (1, -1, 1), (0, -1, 0))
    triangle((-1, -1, -1), (1, -1, 1), (-1, -1, 1), (0, -1, 0))
    return vertices


def rotationspeed(value):

    return value if ANIMATING else (0.0, 0.0, 0.0)


def texturedmaterial():

    return managedmaterial3d(
        color=0xFFFFFF,
        texture=IMAGEPATH,
        texture_width=128,
        texture_height=128,
        texture_format="BGRA32",
        shininess=42,
    )


def mainmeshes():

    return [
        managedmesh3d(
            "plane",
            position=(0.0, -1.65, 0.0),
            scale=(4.6, 1.0, 2.7),
            material=managedmaterial3d(color=0x303A49, shininess=8),
        ),
        managedmesh3d(
            "cube",
            position=(-2.35, 0.15, 0.15),
            rotation=(14.0, 24.0, 0.0),
            scale=(0.9, 0.9, 0.9),
            rotation_speed=rotationspeed((17.0, 34.0, 8.0)),
            material=texturedmaterial(),
            wireframe=WIREFRAME,
            line_width=2.0,
        ),
        managedmesh3d(
            "sphere",
            position=(0.0, 0.2, 0.0),
            scale=(1.05, 1.05, 1.05),
            rotation_speed=rotationspeed((0.0, -27.0, 0.0)),
            material=managedmaterial3d(color=CYAN, shininess=96),
            wireframe=WIREFRAME,
            line_width=1.5,
            subdivisions=16,
        ),
        managedmesh3d(
            "custom",
            position=(2.35, 0.05, 0.1),
            rotation=(0.0, -18.0, 0.0),
            scale=(0.95, 0.95, 0.95),
            rotation_speed=rotationspeed((0.0, 29.0, 0.0)),
            material=managedmaterial3d(color=PURPLE, shininess=54),
            vertices=pyramidvertices(),
            indices=list(range(18)),
            wireframe=WIREFRAME,
            line_width=2.0,
        ),
        managedmesh3d(
            "cube",
            position=(0.85, 0.75, -2.35),
            rotation=(20.0, 20.0, 0.0),
            scale=(0.72, 0.72, 0.72),
            rotation_speed=rotationspeed((31.0, -23.0, 11.0)),
            material=managedmaterial3d(color=ORANGE, opacity=0.38, shininess=72),
        ),
    ]


def orthographicmeshes():

    return [
        managedmesh3d(
            "cube",
            position=(0.0, 0.8, 0.0),
            rotation=(25.0, 35.0, 0.0),
            scale=(1.25, 1.25, 1.25),
            rotation_speed=rotationspeed((20.0, 32.0, 6.0)),
            material=managedmaterial3d(color=ACCENT, unlit=True),
            wireframe=True,
            line_width=2.0,
        ),
        managedmesh3d(
            "sphere",
            position=(0.0, -1.75, 0.0),
            scale=(0.75, 0.75, 0.75),
            rotation_speed=rotationspeed((0.0, 26.0, 0.0)),
            material=texturedmaterial(),
            subdivisions=10,
        ),
    ]


def compactscene(width, height):

    commands = [managedrectangle([0, 0, width, height], BACKGROUND, nodeid="background")]
    commands.append(managedtext(24, 24, WINDOWTITLE, 25, FONTFILE, TEXT, nodeid="compact-title"))
    commands.append(managedtext(
        24,
        67,
        "Increase the window size to display the complete controlled 3D test.",
        16,
        FONTFILE,
        MUTED,
        nodeid="compact-detail",
        clip=[20, 60, max(1, width - 40), max(1, height - 80)],
    ))
    return commands


def buildscene(width=None, height=None):

    global BUTTONS

    width = max(1, int(WINW if width is None else width))
    height = max(1, int(WINH if height is None else height))

    if width < 900 or height < 620:

        BUTTONS = []
        return compactscene(width, height)

    margin = 22
    headerheight = 78
    footerheight = 78
    gap = 14
    contenty = headerheight + 10
    contentheight = height - contenty - footerheight - margin
    contentwidth = width - margin * 2
    mainwidth = max(540, int(contentwidth * 0.70))
    sidewidth = contentwidth - mainwidth - gap
    mainx = margin
    sidex = mainx + mainwidth + gap
    commands = [managedrectangle([0, 0, width, height], BACKGROUND, nodeid="background")]
    commands.append(managedtext(margin, 17, WINDOWTITLE, 27, FONTFILE, TEXT, nodeid="title"))
    commands.append(managedtext(
        margin,
        50,
        TELEMETRYTEXT,
        14,
        FONTFILE,
        MUTED,
        nodeid="telemetry",
        clip=[margin, 45, width - margin * 2, 25],
    ))
    commands.append(managedrectangle([mainx, contenty, mainwidth, contentheight], PANELDARK, nodeid="main-panel"))
    commands.append(managednode(
        "border",
        nodeid="main-border",
        rect=[mainx, contenty, mainwidth, contentheight],
        width=1,
        color=PANELBORDER,
    ))
    mainprojection = "perspective" if PERSPECTIVE else "orthographic"
    maincamera = managedcamera3d(
        position=(0.0, 2.6, 8.6),
        target=(0.0, -0.25, 0.0),
        projection=mainprojection,
        fov=48.0,
        near=0.1,
        far=40.0,
        orthographic_size=4.1,
    )
    commands.append(managedscene3d(
        [mainx + 1, contenty + 1, mainwidth - 2, contentheight - 2],
        maincamera,
        mainmeshes(),
        nodeid="main-3d-scene",
        ambient={"color": 0xDDE8FF, "intensity": 0.28},
        light={"direction": [-0.45, -0.8, -0.55], "color": 0xFFF2DD, "intensity": 1.15},
        fog={"enabled": FOGENABLED, "color": PANELDARK, "near": 7.0, "far": 14.5},
        postprocess=EFFECTS[EFFECTINDEX],
        antialias="auto",
    ))
    commands.append(managedtext(
        mainx + 16,
        contenty + 14,
        f"{mainprojection} camera  |  depth-tested lighting  |  {EFFECTS[EFFECTINDEX]}",
        14,
        FONTFILE,
        TEXT,
        nodeid="main-label",
        clip=[mainx + 12, contenty + 8, mainwidth - 24, 28],
    ))
    commands.append(managedtext(
        mainx + 16,
        contenty + contentheight - 29,
        "textured cube   lit sphere   custom mesh   transparent mesh   fog",
        13,
        FONTFILE,
        MUTED,
        nodeid="main-detail",
        clip=[mainx + 12, contenty + contentheight - 34, mainwidth - 24, 27],
    ))
    commands.append(managedrectangle([sidex, contenty, sidewidth, contentheight], PANELDARK, nodeid="side-panel"))
    commands.append(managednode(
        "border",
        nodeid="side-border",
        rect=[sidex, contenty, sidewidth, contentheight],
        width=1,
        color=PANELBORDER,
    ))
    sidecamera = managedcamera3d(
        position=(0.0, 0.4, 7.0),
        target=(0.0, -0.25, 0.0),
        projection="orthographic",
        near=0.1,
        far=30.0,
        orthographic_size=3.6,
    )
    commands.append(managedscene3d(
        [sidex + 1, contenty + 1, sidewidth - 2, contentheight - 2],
        sidecamera,
        orthographicmeshes(),
        nodeid="orthographic-3d-scene",
        ambient={"color": 0xFFFFFF, "intensity": 0.34},
        light={"direction": [0.35, -0.75, -0.45], "color": 0xDDE8FF, "intensity": 0.95},
        fog={"enabled": False},
        postprocess="sepia",
        antialias="auto",
    ))
    commands.append(managedtext(
        sidex + 14,
        contenty + 14,
        "orthographic + wireframe",
        14,
        FONTFILE,
        TEXT,
        nodeid="side-label",
        clip=[sidex + 10, contenty + 8, sidewidth - 20, 28],
    ))
    commands.append(managedtext(
        sidex + 14,
        contenty + contentheight - 29,
        "server-owned sepia pass",
        13,
        FONTFILE,
        MUTED,
        nodeid="side-detail",
        clip=[sidex + 10, contenty + contentheight - 34, sidewidth - 20, 27],
    ))

    buttony = height - footerheight + 14
    buttonwidth = 120
    buttonheight = 34
    buttonx = margin
    BUTTONS = []
    labels = (
        ("animation", "pause" if ANIMATING else "animate"),
        ("projection", "orthographic" if PERSPECTIVE else "perspective"),
        ("fog", "fog off" if FOGENABLED else "fog on"),
        ("effect", f"effect: {EFFECTS[EFFECTINDEX]}"),
        ("wireframe", "solid" if WIREFRAME else "wireframe"),
    )

    for index, (name, label) in enumerate(labels):

        currentwidth = 150 if name in ("projection", "effect") else buttonwidth
        rect = [buttonx, buttony, currentwidth, buttonheight]
        BUTTONS.append({"name": name, "rect": rect})
        commands.append(managedrectangle(rect, PANEL, nodeid=f"button-{name}"))
        commands.append(managednode(
            "border",
            nodeid=f"button-{name}-border",
            rect=rect,
            width=1,
            color=ACCENT if index == 0 else PANELBORDER,
        ))
        commands.append(managedtext(
            buttonx + 11,
            buttony + 8,
            label,
            13,
            FONTFILE,
            TEXT,
            nodeid=f"button-{name}-label",
            clip=[buttonx + 7, buttony + 4, currentwidth - 14, buttonheight - 7],
        ))
        buttonx += currentwidth + 9

    commands.append(managedtext(
        max(buttonx + 8, width - 330),
        buttony + 8,
        "depth + animation stay inside windowserver",
        12,
        FONTFILE,
        MUTED,
        nodeid="security-note",
        clip=[max(0, width - 335), buttony + 4, 315, 25],
    ))
    return commands


def invalidatescene(rect=None):

    global SCENEDIRTY, SCENEDAMAGE

    SCENEDIRTY = True

    if rect is None:
        rect = [0, 0, int(WINW), int(WINH)]

    SCENEDAMAGE.append([int(value) for value in rect])


def submitscene():

    global SCENEDIRTY, SCENEDAMAGE, GRAPHICSERROR

    if not GRAPHICSSTATE.get("available") or WINID is None:
        return False

    if not managedtick(GRAPHICSSTATE):

        GRAPHICSERROR = str(GRAPHICSSTATE.get("failure", "managed graphics timeout"))
        renderfallback(GRAPHICSERROR)
        return False

    if GRAPHICSSTATE.get("pending"):
        return bool(GRAPHICSSTATE.get("active"))

    if not SCENEDIRTY and not GRAPHICSSTATE.get("need_submit"):
        return bool(GRAPHICSSTATE.get("active"))

    try:

        commands = buildscene()

        for rect in SCENEDAMAGE or [[0, 0, int(WINW), int(WINH)]]:
            managedmarkdamage(GRAPHICSSTATE, rect, bounds=(int(WINW), int(WINH)))

        SCENEDIRTY = False
        SCENEDAMAGE = []
        managedsubmit(GRAPHICSSTATE, sendmessage, int(WINID), commands)
        writestatus("scene-submitted", commands=len(commands), scene3d=2)
        return bool(GRAPHICSSTATE.get("available"))

    except Exception as error:

        GRAPHICSERROR = str(error)
        manageddisable(GRAPHICSSTATE, GRAPHICSERROR)
        writestatus("scene-build-failed", error=GRAPHICSERROR)
        sendmessage({"op": "GRAPHICS_CLEAR", "winid": int(WINID)})
        renderfallback(GRAPHICSERROR)
        return False



## fallback functions
def cpufallbackallowed():

    # CPU drawing exists only for the explicit 3dcputest diagnostic.  A normal
    # or GPU test must fail closed if the managed renderer is unavailable;
    # otherwise the fallback frame hides a broken accelerated path.
    return AUTOEXPECT == "cpu" and not bool(GRAPHICSSTATE.get("available"))


def renderpreparing():

    if not WINBUFFER or not cpufallbackallowed():
        return False

    try:

        clear(BACKGROUND)
        fillrectfast(20, 20, max(1, int(WINW) - 40), 54, PANEL)
        drawtextttf(34, 31, WINDOWTITLE, TEXT, 24, fontpath=FONTFILE)
        drawtextttf(34, 105, "Preparing the controlled hardware 3D scene...", TEXT, 18, fontpath=FONTFILE)
        drawtextttf(34, 140, "Waiting for a physical accelerated presentation receipt.", MUTED, 15, fontpath=FONTFILE)
        present()
        sendmessage({"op": "DAMAGE", "winid": int(WINID), "rect": [0, 0, int(WINW), int(WINH)]})
        return True

    except Exception:

        return False


def renderfallback(reason="controlled OpenGL 3D is unavailable"):

    global FALLBACKRENDERS

    if not WINBUFFER or not cpufallbackallowed():
        return False

    try:

        clear(BACKGROUND)
        fillrectfast(20, 20, max(1, int(WINW) - 40), 54, PANEL)
        drawtextttf(34, 31, WINDOWTITLE, TEXT, 24, fontpath=FONTFILE)
        drawtextttf(34, 105, "The controlled GPU 3D path is unavailable.", ORANGE, 18, fontpath=FONTFILE)
        drawtextttf(34, 140, str(reason)[:160], MUTED, 15, fontpath=FONTFILE)
        drawtextttf(34, 185, "This frame is limited to the explicit 3dcputest diagnostic.", TEXT, 15, fontpath=FONTFILE)
        present()
        FALLBACKRENDERS += 1
        sendmessage({"op": "DAMAGE", "winid": int(WINID), "rect": [0, 0, int(WINW), int(WINH)]})
        return True

    except Exception:

        return False



## interaction functions
def activate(name):

    global ANIMATING, PERSPECTIVE, FOGENABLED, EFFECTINDEX, WIREFRAME

    if name == "animation":
        ANIMATING = not ANIMATING

    elif name == "projection":
        PERSPECTIVE = not PERSPECTIVE

    elif name == "fog":
        FOGENABLED = not FOGENABLED

    elif name == "effect":
        EFFECTINDEX = (EFFECTINDEX + 1) % len(EFFECTS)

    elif name == "wireframe":
        WIREFRAME = not WIREFRAME

    else:
        return

    invalidatescene()


def pointerbutton(message):

    if str(message.get("state", "down")) != "down" or int(message.get("button", 0)) != 1:
        return

    try:

        x = int(message.get("x", -1))
        y = int(message.get("y", -1))

    except Exception:

        return

    for button in BUTTONS:

        bx, by, bw, bh = button["rect"]

        if bx <= x < bx + bw and by <= y < by + bh:

            activate(button["name"])
            return


def keypress(message):

    global RUNNING

    if str(message.get("state", "down")) != "down":
        return

    key = str(message.get("key", "")).upper()

    if key in ("ESC", "ESCAPE"):

        RUNNING = False
        return

    mapping = {
        "SPACE": "animation",
        "P": "projection",
        "F": "fog",
        "E": "effect",
        "W": "wireframe",
    }

    if key in mapping:
        activate(mapping[key])



## window functions
def mapwindow():

    global MAPPED

    if WINID is None or MAPPED:
        return

    sendmessage({"op": "MAP", "winid": int(WINID), "transition": True, "transition_ms": 240})
    sendmessage({"op": "RAISE", "winid": int(WINID)})
    sendmessage({"op": "FOCUS_SET", "winid": int(WINID)})
    MAPPED = True


def createwindow():

    sendmessage({
        "op": "CREATE_WINDOW",
        "role": "window",
        "title": WINDOWTITLE,
        "current": WINDOWPATH,
        "path": WINDOWPATH,
        "w": WINDOWWIDTH,
        "h": WINDOWHEIGHT,
        "x": 150,
        "y": 90,
        "pid": os.getpid(),
    })


def resized(message):

    global WINW, WINH

    try:

        width = max(1, int(message.get("w", WINW)))
        height = max(1, int(message.get("h", WINH)))

    except Exception:

        return

    if width == WINW and height == WINH:
        return

    managedclear(GRAPHICSSTATE, sendmessage, int(WINID))
    WINW = width
    WINH = height

    try:

        initbuffer(WINBUFFER, WINW, WINH)

    except Exception as error:

        manageddisable(GRAPHICSSTATE, str(error))

    renderpreparing()
    invalidatescene()
    submitscene()


def updatetelemetry(message):

    global TELEMETRYTEXT, TELEMETRYDETAIL

    state = message.get("state", {}) if isinstance(message.get("state"), dict) else {}
    telemetry = state.get("telemetry", {}) if isinstance(state.get("telemetry"), dict) else {}
    renderer = str(state.get("renderer", "OpenGL")).split(";")[0]
    hardware = bool(state.get("hardware_accelerated", False))
    mode = "hardware" if hardware else "software"
    presentations = int(telemetry.get("presentation_samples", 0))
    presentedfps = float(telemetry.get("presented_fps", 0.0))
    presentationtext = (
        f"{presentedfps:.1f} displayed FPS"
        if presentations
        else "display cadence measuring"
    )
    TELEMETRYTEXT = (
        f"{mode} {str(state.get('window_compositor', 'gpu')).upper()} | {renderer} | "
        f"{int(telemetry.get('mesh_3d_triangles', 0)):,} triangles | "
        f"{presentationtext}"
    )
    TELEMETRYDETAIL = (
        f"{int(telemetry.get('depth_buffer_count', 0))} depth targets | "
        f"{int(telemetry.get('mesh_3d_draws', 0)):,} mesh draws | "
        f"{float(telemetry.get('average_frame_ms', 0.0)):.2f} ms render average"
    )
    invalidatescene([0, 0, WINW, 78])


def handlemessage(message):

    global CAPABILITIES, WINID, WINBUFFER, WINW, WINH, RUNNING, GRAPHICSERROR
    global GRAPHICSCLEARACK, AUTOTELEMETRYPENDING

    operation = str(message.get("op", ""))

    if operation == "WELCOME":

        CAPABILITIES = dict(message.get("graphics", {})) if isinstance(message.get("graphics"), dict) else {}
        managedconfigure(GRAPHICSSTATE, CAPABILITIES, required=("rectangle", "text", "scene3d"))
        controlled = CAPABILITIES.get("controlled_3d", {}) if isinstance(CAPABILITIES.get("controlled_3d"), dict) else {}

        antialiasing = controlled.get("antialiasing", []) if isinstance(controlled.get("antialiasing"), list) else []

        if (
            int(CAPABILITIES.get("version", 0)) < 4
            or not controlled.get("depth_buffer")
            or not controlled.get("server_animation")
            or not all(value in antialiasing for value in ("auto", "analytic", "quality"))
        ):
            manageddisable(GRAPHICSSTATE, "graphics API version 4 controlled 3D antialiasing is required")

        if CAPABILITIES.get("raw_shaders"):
            manageddisable(GRAPHICSSTATE, "the public graphics API must not expose raw shaders")

        createwindow()
        return

    if operation == "WINDOW_CREATED":

        WINID = int(message.get("winid", 0))
        WINBUFFER = str(message.get("buffer", ""))
        WINW = max(1, int(message.get("w", WINDOWWIDTH)))
        WINH = max(1, int(message.get("h", WINDOWHEIGHT)))
        writestatus("window-created")

        try:

            initbuffer(WINBUFFER, WINW, WINH)
            renderpreparing()

        except Exception as error:

            GRAPHICSERROR = str(error)
            manageddisable(GRAPHICSSTATE, GRAPHICSERROR)

        if GRAPHICSSTATE.get("available"):

            # Mapping first makes the server's commit response a receipt for
            # a physically displayed GPU frame, not merely an off-screen
            # accelerated render into an unmapped window.
            mapwindow()
            invalidatescene()
            submitscene()

        else:

            renderfallback(GRAPHICSSTATE.get("failure", GRAPHICSERROR))
            mapwindow()

        return

    if operation in ("GRAPHICS_COMMITTED", "GRAPHICS_CLEARED", "GRAPHICS_ANIMATING"):

        managedresponse(GRAPHICSSTATE, message)

        if operation == "GRAPHICS_COMMITTED":

            writestatus(
                "scene-committed",
                generation=int(message.get("generation", 0) or 0),
                accelerated=message.get("accelerated") is True,
                managed_only=message.get("managed_only") is True,
                presented=message.get("presented") is True,
            )

            if not bool(message.get("presented", False)):
                GRAPHICSERROR = str(message.get("presentation_reason", "the accelerated frame was not physically presented"))
                manageddisable(GRAPHICSSTATE, GRAPHICSERROR)
                renderfallback(GRAPHICSERROR)
                mapwindow()

        elif operation == "GRAPHICS_CLEARED":
            GRAPHICSCLEARACK = True

        return

    if operation == "GRAPHICS_TELEMETRY":

        AUTOTELEMETRYPENDING = False

        if AUTOTEST:
            autotelemetry(message)
        else:
            updatetelemetry(message)

        return

    if operation == "RESIZED":

        resized(message)
        return

    if operation == "POINTER_BUTTON":

        pointerbutton(message)
        return

    if operation == "KEY":

        keypress(message)
        return

    if operation == "CLOSE":

        RUNNING = False
        sendmessage({"op": "CLOSE_ACK", "pid": os.getpid()})
        return

    if operation == "ERROR":

        code = str(message.get("code", ""))

        if code.startswith("graphics_"):

            managedresponse(GRAPHICSSTATE, message)
            GRAPHICSERROR = str(GRAPHICSSTATE.get("failure", message.get("detail", code)))
            writestatus("scene-rejected", code=code, error=GRAPHICSERROR)
            renderfallback(GRAPHICSERROR)
            mapwindow()

            if AUTOTEST:
                AUTOERRORS.append(GRAPHICSERROR)



## automated validation functions
def writejson(path, value):

    temporary = path + ".tmp"

    try:

        os.makedirs(os.path.dirname(path), exist_ok=True)

        with open(temporary, "w") as output:

            json.dump(value, output, sort_keys=True, separators=(",", ":"))
            output.flush()
            os.fsync(output.fileno())

        os.replace(temporary, path)
        return True

    except Exception:

        try:
            if os.path.exists(temporary):
                os.remove(temporary)
        except Exception:
            pass

        return False


def autoreset():

    if not AUTOTEST:
        return

    for path in (
        RESULTPATH,
        PROGRESSPATH,
        os.path.join(IMAGEBASE, "live-test.json"),
        os.path.join(IMAGEBASE, "progress.json"),
    ):

        try:

            if os.path.isfile(path):
                os.unlink(path)

        except Exception:

            pass


def autoprogress(stage, **values):

    if not AUTOTEST:
        return

    result = {
        "format": 1,
        "stage": str(stage),
        "expected_path": AUTOEXPECT,
        "phase": AUTOPHASE,
        "window_id": int(WINID or 0),
        "managed_active": bool(GRAPHICSSTATE.get("active")),
        "elapsed_seconds": round(time.monotonic() - AUTOPHASESTART, 3),
    }
    result.update(values)
    writejson(PROGRESSPATH, result)
    writejson(os.path.join(IMAGEBASE, "progress.json"), result)


def autoowned(message):

    windows = message.get("windows", []) if isinstance(message.get("windows"), list) else []
    return next((value for value in windows if int(value.get("winid", 0)) == int(WINID or 0)), {})


def autometrics(message):

    state = message.get("state", {}) if isinstance(message.get("state"), dict) else {}
    telemetry = state.get("telemetry", {}) if isinstance(state.get("telemetry"), dict) else {}
    return state, telemetry, autoowned(message)


def autorequest(stage):

    global AUTOTELEMETRYPENDING

    if AUTOTELEMETRYPENDING:
        return

    AUTOTELEMETRYPENDING = True
    autoprogress(stage)
    sendmessage({"op": "GRAPHICS_TELEMETRY"})


def autofinalize(message):

    global AUTOPHASE

    state, telemetry, owned = autometrics(message)
    basemetrics = AUTOBASELINE.get("telemetry", {}) if isinstance(AUTOBASELINE.get("telemetry"), dict) else {}
    baseowned = AUTOBASELINE.get("owned", {}) if isinstance(AUTOBASELINE.get("owned"), dict) else {}

    def growth(name):
        return int(telemetry.get(name, 0)) - int(basemetrics.get(name, 0))

    controlled = CAPABILITIES.get("controlled_3d", {}) if isinstance(CAPABILITIES.get("controlled_3d"), dict) else {}
    antialiasing = controlled.get("antialiasing", []) if isinstance(controlled.get("antialiasing"), list) else []

    checks = {
        "runtime_telemetry_received": bool(state),
        "no_managed_command_errors": int(message.get("command_errors", 0)) == 0,
        "raw_shaders_not_exposed": not bool(CAPABILITIES.get("raw_shaders", False)),
        "controlled_3d_negotiated": bool(controlled),
        "antialiasing_negotiated": all(value in antialiasing for value in ("auto", "analytic", "quality")),
    }

    if AUTOEXPECT == "cpu":

        checks.update({
            "cpu_compositor_selected": str(state.get("window_compositor", "")) == "cpu",
            "managed_scene_disabled": not bool(GRAPHICSSTATE.get("active")),
            "shared_buffer_fallback_rendered": int(FALLBACKRENDERS) > 0,
            "no_failed_frames": growth("failed_frames") == 0,
        })

    else:

        checks.update({
            "gpu_compositor_selected": str(state.get("window_compositor", "")) == "gpu",
            "expected_hardware_state": bool(state.get("hardware_accelerated", False)) == (AUTOEXPECT == "gpu"),
            "managed_only_scene_active": bool(GRAPHICSSTATE.get("active")) and bool(owned.get("managed_only", False)),
            "two_3d_scene_commands_retained": int(owned.get("commands", 0)) >= 2,
            "server_animation_without_resubmission": int(owned.get("scene_commits", 0)) == int(baseowned.get("scene_commits", 0)),
            "mesh_draws_advanced": growth("mesh_3d_draws") >= (20 if AUTOEXPECT == "gpu" else 1),
            "triangles_rendered": growth("mesh_3d_triangles") > 0,
            "vertices_rendered": growth("mesh_3d_vertices") > 0,
            "depth_cleared_each_scene": growth("mesh_3d_depth_clears") > 0,
            "depth_buffers_allocated": int(telemetry.get("depth_buffer_count", 0)) >= 1 and int(telemetry.get("depth_buffer_bytes", 0)) > 0,
            "wireframes_use_analytic_ribbons": growth("aa_3d_wire_segments") > 0,
            "managed_gpu_memory_bounded": int(telemetry.get("managed_gpu_bytes", 0)) <= int(telemetry.get("texture_byte_limit", 0)),
            "no_failed_frames": growth("failed_frames") == 0,
            "no_gpu_fallbacks": growth("fallbacks") == 0 and not bool(message.get("gpu_failed", False)),
        })

        if AUTOEXPECT == "gpu":

            checks.update({
                "hardware_quality_supersampling_active": growth("aa_supersample_scenes") > 0,
                "hardware_quality_target_allocated": int(telemetry.get("aa_target_count", 0)) > 0 and int(telemetry.get("aa_target_bytes", 0)) > 0,
                "hardware_quality_no_fallbacks": growth("aa_quality_fallbacks") == 0,
            })

        else:

            checks.update({
                "software_analytic_antialiasing_active": growth("aa_analytic_scenes") > 0,
                "software_supersampling_avoided": growth("aa_supersample_scenes") == 0,
            })

    errors = list(AUTOERRORS)

    for name, passed in checks.items():

        if not passed:
            errors.append(f"check failed: {name}")

    result = {
        "format": 1,
        "passed": not errors,
        "expected_path": AUTOEXPECT,
        "checks": checks,
        "growth": {
            "mesh_draws": growth("mesh_3d_draws"),
            "triangles": growth("mesh_3d_triangles"),
            "vertices": growth("mesh_3d_vertices"),
            "depth_clears": growth("mesh_3d_depth_clears"),
            "wire_segments": growth("aa_3d_wire_segments"),
            "analytic_scenes": growth("aa_analytic_scenes"),
            "supersample_scenes": growth("aa_supersample_scenes"),
            "supersample_pixels": growth("aa_supersample_pixels"),
            "quality_fallbacks": growth("aa_quality_fallbacks"),
            "failed_frames": growth("failed_frames"),
            "fallbacks": growth("fallbacks"),
        },
        "final": {
            "backend": state.get("backend"),
            "renderer": state.get("renderer"),
            "hardware_accelerated": bool(state.get("hardware_accelerated", False)),
            "window_compositor": state.get("window_compositor"),
            "owned_window": owned,
            "telemetry": telemetry,
        },
        "errors": list(dict.fromkeys(errors)),
    }
    written = []

    for path in (RESULTPATH, os.path.join(IMAGEBASE, "live-test.json")):

        if writejson(path, result):
            written.append(path)

    result["written"] = written
    AUTOPHASE = "finished"
    autoprogress("finished", passed=bool(result["passed"]), result_paths=written)


def autotelemetry(message):

    global AUTOBASELINE, AUTOPHASE, AUTOPHASESTART

    state, telemetry, owned = autometrics(message)

    if AUTOPHASE == "wait":

        if AUTOEXPECT == "cpu":

            AUTOBASELINE = {"telemetry": dict(telemetry), "owned": dict(owned)}
            autofinalize(message)
            return

        AUTOBASELINE = {"telemetry": dict(telemetry), "owned": dict(owned)}
        AUTOPHASE = "render"
        AUTOPHASESTART = time.monotonic()
        autoprogress("baseline", scene_commits=int(owned.get("scene_commits", 0)))
        return

    if AUTOPHASE == "final":
        autofinalize(message)


def autopulse(now):

    global AUTOPHASE, AUTOPHASESTART

    if not AUTOTEST or not MAPPED or AUTOPHASE == "finished":
        return

    if AUTOPHASE == "wait" and not AUTOTELEMETRYPENDING:

        if AUTOEXPECT == "cpu" or GRAPHICSSTATE.get("active"):
            autorequest("request-baseline")

        return

    duration = 4.0 if AUTOEXPECT == "gpu" else 12.0

    if AUTOPHASE == "render" and now - AUTOPHASESTART >= duration and not AUTOTELEMETRYPENDING:

        AUTOPHASE = "final"
        AUTOPHASESTART = now
        autorequest("request-final")



## diagnostic functions
def diagnostic():

    result = {"format": 1, "passed": False, "checks": {}, "errors": []}

    try:

        commands = buildscene(WINDOWWIDTH, WINDOWHEIGHT)
        kinds = [str(command.get("kind", "")) for command in commands]
        scenes = [command for command in commands if command.get("kind") == "scene3d"]

        if commands[0].get("kind") != "rectangle" or commands[0].get("rect") != [0, 0, WINDOWWIDTH, WINDOWHEIGHT]:
            raise RuntimeError("the 3D test does not begin with a complete opaque background")

        if len(scenes) != 2:
            raise RuntimeError("the 3D test must contain perspective and orthographic scenes")

        if {scene.get("camera", {}).get("projection") for scene in scenes} != {"perspective", "orthographic"}:
            raise RuntimeError("the 3D test does not exercise both camera projections")

        primitives = {mesh.get("primitive") for scene in scenes for mesh in scene.get("meshes", [])}

        if not {"cube", "plane", "sphere", "custom"}.issubset(primitives):
            raise RuntimeError("the 3D test does not exercise every controlled mesh primitive")

        custom = next(mesh for scene in scenes for mesh in scene.get("meshes", []) if mesh.get("primitive") == "custom")

        if len(custom.get("vertices", [])) != 18 or len(custom.get("indices", [])) != 18:
            raise RuntimeError("the custom pyramid is malformed")

        identifiers = [str(command.get("id")) for command in commands if command.get("id")]

        if len(identifiers) != len(set(identifiers)):
            raise RuntimeError("the 3D test contains duplicate retained node ids")

        capabilities = {
            "version": 4,
            "accelerated": True,
            "managed_resources": True,
            "raw_shaders": False,
            "atomic_scene": True,
            "retained_scene": True,
            "commands": ["rectangle", "border", "text", "scene3d"],
            "command_limit": 1024,
            "text_limit": 1024,
            "damage_limit": 64,
            "controlled_3d": {
                "depth_buffer": True,
                "server_animation": True,
                "antialiasing": ["auto", "analytic", "quality"],
                "hardware_supersample": 2,
            },
        }
        state = managedstate()

        if not managedconfigure(state, capabilities, required=("rectangle", "text", "scene3d")):
            raise RuntimeError("the 3D test could not negotiate graphics API version 4")

        requests = []
        managedmarkdamage(state, [0, 0, WINDOWWIDTH, WINDOWHEIGHT], bounds=(WINDOWWIDTH, WINDOWHEIGHT))
        managedsubmit(state, lambda request: requests.append(request) or True, 91, commands)

        if len(requests) != 1 or requests[0].get("op") != "GRAPHICS_SCENE":
            raise RuntimeError("the 3D test did not submit one atomic managed scene")

        if any(kind == "shader" for kind in kinds):
            raise RuntimeError("the 3D test attempted to own a raw shader")

        result["checks"] = {
            "complete_background": True,
            "scene_nodes": len(scenes),
            "projections": sorted({scene.get("camera", {}).get("projection") for scene in scenes}),
            "primitives": sorted(primitives),
            "custom_vertices": len(custom.get("vertices", [])),
            "textured_material": any(mesh.get("material", {}).get("texture") for scene in scenes for mesh in scene.get("meshes", [])),
            "transparent_material": any(float(mesh.get("material", {}).get("opacity", 1.0)) < 1.0 for scene in scenes for mesh in scene.get("meshes", [])),
            "wireframe": any(mesh.get("wireframe") for scene in scenes for mesh in scene.get("meshes", [])),
            "fog": any(scene.get("fog", {}).get("enabled") for scene in scenes),
            "postprocess": any(scene.get("postprocess") != "none" for scene in scenes),
            "server_animation": any(any(abs(float(value)) > 0.0 for value in mesh.get("rotation_speed", [])) for scene in scenes for mesh in scene.get("meshes", [])),
            "automatic_antialiasing": all(scene.get("antialias") == "auto" for scene in scenes),
            "atomic_scene": True,
            "raw_shaders_not_exposed": True,
            "single_python_file": True,
        }
        result["passed"] = all(bool(value) for value in result["checks"].values())

    except Exception as error:

        result["errors"].append(str(error))

    print(json.dumps(result, separators=(",", ":"), sort_keys=True))
    return 0 if result["passed"] else 1



## core functions
def connectwindowserver():

    global SOCK

    SOCK = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    SOCK.connect(WINDOWSOCK)
    SOCK.setblocking(False)
    sendmessage({"op": "HELLO"})
    sendmessage({"op": "SUBSCRIBE", "types": ["fbsize"]})


def pulse():

    global LASTTELEMETRY

    pumpsocket(SOCKETPOLLINTERVAL)
    submitscene()
    now = time.monotonic()
    autopulse(now)

    if AUTOTEST:
        return

    if MAPPED and GRAPHICSSTATE.get("active") and now - LASTTELEMETRY >= 1.5:

        LASTTELEMETRY = now
        sendmessage({"op": "GRAPHICS_TELEMETRY"})


def cleanup():

    global GRAPHICSCLEARACK

    try:

        if SOCK is not None and WINID is not None:

            GRAPHICSCLEARACK = False
            managedclear(GRAPHICSSTATE, sendmessage, int(WINID))
            flushmessages()
            deadline = time.monotonic() + 12.0

            while not GRAPHICSCLEARACK and time.monotonic() < deadline:
                pumpsocket(0.05)

    except Exception:

        pass

    try:

        if SOCK is not None:
            SOCK.close()

    except Exception:

        pass

    removeimage()


def main():

    writestatus("starting")
    autoreset()
    autoprogress("started")
    createimage()
    connectwindowserver()
    deadline = time.monotonic() + 8.0

    while RUNNING and WINID is None and time.monotonic() < deadline:
        pumpsocket(0.05)

    if WINID is None:
        raise RuntimeError("windowserver did not create the OpenGL 3D capability test window")

    while RUNNING:
        pulse()



# execute
if __name__ == "__main__":

    if len(sys.argv) > 1 and str(sys.argv[1]).strip().lower() in ("diagnostic", "graphics-diagnostic"):
        sys.exit(diagnostic())

    try:

        main()

    except KeyboardInterrupt:

        pass

    except Exception as error:

        writestatus("fatal", error=str(error))
        raise

    finally:

        cleanup()
