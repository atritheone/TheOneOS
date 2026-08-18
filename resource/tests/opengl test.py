#!/bin/python3.13



"""
opengl test.py

opengl test is a standalone window that demonstrates the controlled T1OS
graphics API without changing the appearance of any existing software.
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
from graphics.graphics import managedanimate, managednode, managedrectangle, managedtext, managedimage



## globals

# paths
WINDOWSOCK = "/.ephemeral/windowserver/accept.sock"
WINDOWPATH = os.path.abspath(__file__)
IMAGEBASE = "/.ephemeral/opengl-test"
IMAGEPATH = os.path.join(IMAGEBASE, "image.raw")
STATUSPATH = os.path.join(IMAGEBASE, "status.json")
FONTFILE = "/the one/resources/fonts/atkinsonhyperlegiblenext.ttf"

# window
WINDOWTITLE = "OpenGL capability test"
WINDOWWIDTH = 1120
WINDOWHEIGHT = 720
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
SCENEDIRTY = False
SCENEDAMAGE = []
TELEMETRYTEXT = "waiting for graphics telemetry"
TELEMETRYDETAIL = "retained scene has not committed"
LASTTELEMETRY = 0.0
LASTANIMATION = 0.0
ANIMATIONUNTIL = 0.0
ANIMATIONFORWARD = False
SOCKETPOLLINTERVAL = 0.005
EFFECTINDEX = 0
EFFECTS = ("none", "grayscale", "invert", "sepia")
STRESSMODE = False
BLURMODE = False
BUTTONS = []

# animation values retained by the client display list
TRANSFORMROTATION = 0.0
MOTIONTRANSLATE = [0.0, 0.0]
PULSESCALE = [1.0, 1.0]
FADEOPACITY = 0.35

# colours
BACKGROUND = 0x111318
PANEL = 0x1A1E25
PANELBORDER = 0x353B46
TEXT = 0xF0F0F0
MUTED = 0x9AA3B2
ACCENT = 0x68A8FF
GREEN = 0x52D68A
ORANGE = 0xFFB45C
RED = 0xFF7080
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

        return

    if readywrite:
        flushmessages()

    if readyread:

        for message in receivemessages():
            handlemessage(message)

    if OUTBUF:
        flushmessages()



## image functions
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
    width = 64
    height = 64

    with open(IMAGEPATH, "wb") as output:

        for y in range(height):

            for x in range(width):

                tile = ((x // 8) + (y // 8)) % 2
                red = 52 + int(170 * x / max(1, width - 1))
                green = 70 + int(130 * y / max(1, height - 1))
                blue = 225 if tile else 90
                output.write(bytes((blue, green, red, 255)))

    # WindowServer validates and imports this file in its own process.  The
    # directory must therefore be traversable and the immutable surface must
    # be readable without making the application's scratch area writable.
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



## scene functions
def addcard(commands, x, y, width, height, title, nodeid):

    commands.append(managednode(
        "rounded_rectangle",
        nodeid=f"{nodeid}-background",
        rect=[x, y, width, height],
        radius=14,
        color=PANEL,
    ))
    commands.append(managednode(
        "border",
        nodeid=f"{nodeid}-border",
        rect=[x, y, width, height],
        width=1,
        color=PANELBORDER,
    ))
    commands.append(managedtext(
        x + 18,
        y + 15,
        title,
        17,
        FONTFILE,
        TEXT,
        nodeid=f"{nodeid}-title",
        clip=[x + 12, y + 8, width - 24, 32],
    ))


def compactscene(width, height):

    commands = [managedrectangle([0, 0, width, height], BACKGROUND, nodeid="background")]
    commands.append(managedtext(24, 24, WINDOWTITLE, 26, FONTFILE, TEXT, nodeid="compact-title"))
    commands.append(managedtext(
        24,
        68,
        "Increase the window size to display the complete OpenGL capability test.",
        16,
        FONTFILE,
        MUTED,
        nodeid="compact-message",
        clip=[20, 60, max(1, width - 40), max(1, height - 80)],
    ))
    commands.append(managednode(
        "gradient",
        nodeid="compact-gradient",
        rect=[24, min(height - 70, 110), max(1, width - 48), 46],
        color=ACCENT,
        color2=PURPLE,
        direction="horizontal",
    ))
    return commands


def buildscene(width=None, height=None):

    global BUTTONS

    width = max(1, int(WINW if width is None else width))
    height = max(1, int(WINH if height is None else height))

    if width < 820 or height < 580:

        BUTTONS = []
        return compactscene(width, height)

    margin = 22
    gap = 14
    header = 82
    footer = 108
    contenty = header + margin
    contentheight = height - header - footer - margin * 2
    cardwidth = (width - margin * 2 - gap * 2) // 3
    cardheight = (contentheight - gap) // 2
    commands = [managedrectangle([0, 0, width, height], BACKGROUND, nodeid="background")]

    # header and live backend status
    commands.append(managedtext(24, 18, WINDOWTITLE, 28, FONTFILE, TEXT, nodeid="header-title"))
    commands.append(managedtext(
        25,
        53,
        "A separate public-API demonstration; existing T1OS software is unchanged.",
        14,
        FONTFILE,
        MUTED,
        nodeid="header-subtitle",
        clip=[20, 48, max(1, width - 480), 28],
    ))
    statuswidth = min(440, max(220, width // 2 - 20))
    statusx = width - statuswidth - 24
    commands.append(managednode(
        "rounded_rectangle",
        nodeid="status-background",
        rect=[statusx, 18, statuswidth, 42],
        radius=21,
        color=0x202834,
    ))
    commands.append(managednode(
        "circle",
        nodeid="status-light",
        cx=statusx + 20,
        cy=39,
        radius=6,
        color=GREEN if GRAPHICSSTATE.get("active") else ORANGE,
    ))
    commands.append(managedtext(
        statusx + 36,
        28,
        TELEMETRYTEXT,
        14,
        FONTFILE,
        TEXT,
        nodeid="status-text",
        clip=[statusx + 34, 20, statuswidth - 46, 30],
    ))

    cards = []

    for row in range(2):

        for column in range(3):

            cards.append((
                margin + column * (cardwidth + gap),
                contenty + row * (cardheight + gap),
                cardwidth,
                cardheight,
            ))

    # primitives
    x, y, cw, ch = cards[0]
    addcard(commands, x, y, cw, ch, "Primitives and gradients", "primitives")
    commands.append(managednode(
        "gradient",
        nodeid="primitive-gradient",
        rect=[x + 18, y + 52, cw - 36, 42],
        color=ACCENT,
        color2=PURPLE,
        direction="horizontal",
    ))
    commands.append(managednode(
        "rounded_rectangle",
        nodeid="primitive-rounded",
        rect=[x + 20, y + 112, 105, 54],
        radius=16,
        color=GREEN,
    ))
    commands.append(managednode(
        "circle",
        nodeid="primitive-circle",
        cx=x + 174,
        cy=y + 139,
        radius=27,
        color=ORANGE,
    ))
    commands.append(managednode(
        "line",
        nodeid="primitive-line",
        points=[x + 220, y + 114, x + cw - 25, y + 164],
        width=7,
        color=RED,
    ))
    commands.append(managednode(
        "border",
        nodeid="primitive-outline",
        rect=[x + 18, y + ch - 42, cw - 36, 24],
        width=2,
        color=CYAN,
    ))

    # clipping, grouping, scaling, and rotation
    x, y, cw, ch = cards[1]
    addcard(commands, x, y, cw, ch, "Transforms and clipping", "transforms")
    clip = [0, 0, cw - 36, ch - 68]
    groupx = x + 18
    groupy = y + 50
    commands.append(managednode(
        "group",
        nodeid="transform-group",
        translate=[groupx, groupy],
        rotation=TRANSFORMROTATION,
        clip=clip,
    ))
    commands.append(managednode(
        "gradient",
        nodeid="transform-surface",
        parent="transform-group",
        rect=[0, 0, cw - 12, 70],
        color=CYAN,
        color2=ACCENT,
        direction="horizontal",
        opacity=0.9,
        clip=[0, 0, cw - 36, ch - 68],
    ))
    commands.append(managednode(
        "rounded_rectangle",
        nodeid="transform-block",
        parent="transform-group",
        rect=[38, 36, 105, 64],
        radius=14,
        color=PURPLE,
        opacity=0.85,
    ))
    commands.append(managednode(
        "circle",
        nodeid="transform-dot",
        parent="transform-group",
        cx=194,
        cy=68,
        radius=29,
        color=ORANGE,
    ))
    commands.append(managedtext(
        x + 20,
        y + ch - 42,
        "The oversized group is clipped to this card.",
        13,
        FONTFILE,
        MUTED,
        nodeid="transform-note",
        clip=[x + 18, y + ch - 48, cw - 36, 30],
    ))

    # image scaling, text, and controlled colour effects
    x, y, cw, ch = cards[2]
    addcard(commands, x, y, cw, ch, "Images, text and effects", "images")
    commands.append(managedimage(
        IMAGEPATH,
        64,
        64,
        [x + 20, y + 55, 112, 112],
        nodeid="scaled-image",
        effect=EFFECTS[EFFECTINDEX],
    ))
    commands.append(managedtext(
        x + 151,
        y + 56,
        "GPU-scaled image",
        18,
        FONTFILE,
        TEXT,
        nodeid="image-title",
        clip=[x + 145, y + 50, cw - 160, 30],
    ))
    commands.append(managedtext(
        x + 151,
        y + 88,
        f"effect: {EFFECTS[EFFECTINDEX]}",
        14,
        FONTFILE,
        ACCENT,
        nodeid="image-effect",
        clip=[x + 145, y + 82, cw - 160, 28],
    ))
    commands.append(managedtext(
        x + 151,
        y + 120,
        "Atkinson glyph atlas",
        14,
        FONTFILE,
        MUTED,
        nodeid="image-font",
        clip=[x + 145, y + 114, cw - 160, 28],
    ))
    commands.append(managedtext(
        x + 20,
        y + ch - 42,
        "This deliberately long line demonstrates text clipping at the card edge.",
        13,
        FONTFILE,
        TEXT,
        nodeid="clipped-text",
        clip=[x + 18, y + ch - 47, cw - 36, 28],
    ))

    # offscreen layer and alpha composition
    x, y, cw, ch = cards[3]
    addcard(commands, x, y, cw, ch, "Offscreen layer and alpha", "layers")
    layerrect = [x + 18, y + 50, cw - 36, ch - 68]
    commands.append(managednode(
        "layer",
        nodeid="alpha-layer",
        rect=layerrect,
        opacity=0.88,
        clip=layerrect,
    ))
    commands.append(managednode(
        "gradient",
        nodeid="layer-background",
        parent="alpha-layer",
        rect=[x + 25, y + 58, cw - 50, ch - 84],
        color=0x243654,
        color2=0x40285B,
        direction="horizontal",
    ))
    commands.append(managednode(
        "circle",
        nodeid="layer-circle-a",
        parent="alpha-layer",
        cx=x + cw // 2 - 38,
        cy=y + ch // 2 + 12,
        radius=58,
        color=ACCENT,
        opacity=0.72,
    ))
    commands.append(managednode(
        "circle",
        nodeid="layer-circle-b",
        parent="alpha-layer",
        cx=x + cw // 2 + 38,
        cy=y + ch // 2 + 12,
        radius=58,
        color=RED,
        opacity=0.66,
    ))
    commands.append(managedtext(
        x + 34,
        y + 64,
        "Rendered to one managed layer",
        14,
        FONTFILE,
        TEXT,
        nodeid="layer-label",
        parent="alpha-layer",
        clip=layerrect,
    ))

    # server-side animation
    x, y, cw, ch = cards[4]
    addcard(commands, x, y, cw, ch, "Server-side animation", "animation")
    trackx = x + 24
    tracky = y + 91
    trackwidth = max(80, cw - 94)
    commands.append(managednode(
        "border",
        nodeid="motion-track",
        rect=[trackx, tracky - 18, trackwidth + 44, 36],
        width=2,
        color=PANELBORDER,
    ))
    commands.append(managednode(
        "circle",
        nodeid="motion-node",
        cx=trackx + 20,
        cy=tracky,
        radius=15,
        color=ACCENT,
        translate=MOTIONTRANSLATE,
    ))
    commands.append(managednode(
        "group",
        nodeid="pulse-group",
        translate=[x + 35, y + 142],
        scale=PULSESCALE,
        clip=[0, 0, 105, 60],
    ))
    commands.append(managednode(
        "rounded_rectangle",
        nodeid="pulse-node",
        parent="pulse-group",
        rect=[0, 0, 80, 42],
        radius=12,
        color=GREEN,
        clip=[0, 0, 105, 60],
    ))
    commands.append(managednode(
        "line",
        nodeid="spin-node",
        points=[x + cw - 105, y + 145, x + cw - 45, y + 180],
        width=8,
        color=ORANGE,
        rotation=TRANSFORMROTATION,
        opacity=FADEOPACITY,
    ))
    commands.append(managedtext(
        x + 24,
        y + 54,
        "Translation, scale, rotation and opacity",
        13,
        FONTFILE,
        MUTED,
        nodeid="animation-note",
        clip=[x + 18, y + 48, cw - 36, 28],
    ))

    # controlled effects or batched stress geometry
    x, y, cw, ch = cards[5]
    addcard(commands, x, y, cw, ch, "Batched stress geometry" if STRESSMODE else "Controlled colour effects", "effects")

    if STRESSMODE:

        columns = 9
        rows = 4
        left = x + 24
        top = y + 62
        spacingx = max(22, (cw - 48) // columns)
        spacingy = max(25, (ch - 86) // rows)

        for row in range(rows):

            for column in range(columns):

                index = row * columns + column
                color = (ACCENT, GREEN, ORANGE, RED, PURPLE, CYAN)[index % 6]
                commands.append(managednode(
                    "circle",
                    nodeid=f"stress-{index}",
                    cx=left + column * spacingx,
                    cy=top + row * spacingy,
                    radius=7 + index % 5,
                    color=color,
                    opacity=0.55 + (index % 4) * 0.12,
                ))

    else:

        swatchwidth = max(48, (cw - 64) // 3)

        for index, effect in enumerate(("grayscale", "invert", "sepia")):

            swatchx = x + 18 + index * (swatchwidth + 8)
            commands.append(managednode(
                "rounded_rectangle",
                nodeid=f"effect-{effect}",
                rect=[swatchx, y + 62, swatchwidth, 82],
                radius=12,
                color=(RED, ACCENT, ORANGE)[index],
                effect=effect,
            ))
            commands.append(managedtext(
                swatchx + 7,
                y + 156,
                effect,
                12,
                FONTFILE,
                MUTED,
                nodeid=f"effect-{effect}-label",
                clip=[swatchx, y + 150, swatchwidth, 26],
            ))

    # footer controls and retained-scene telemetry
    footery = height - footer + 14
    commands.append(managedtext(
        24,
        footery,
        TELEMETRYDETAIL,
        14,
        FONTFILE,
        MUTED,
        nodeid="telemetry-detail",
        clip=[20, footery - 4, width - 40, 28],
    ))
    buttony = height - 54
    definitions = [
        ("animate", "A  animate", 132),
        ("stress", f"S  stress {'on' if STRESSMODE else 'off'}", 142),
        ("effect", f"E  effect {EFFECTS[EFFECTINDEX]}", 174),
        ("blur", f"B  blur {'on' if BLURMODE else 'off'}", 132),
    ]
    BUTTONS = []
    buttonx = 24

    for name, label, buttonwidth in definitions:

        rect = [buttonx, buttony, buttonwidth, 34]
        BUTTONS.append({"name": name, "rect": rect})
        commands.append(managednode(
            "rounded_rectangle",
            nodeid=f"button-{name}",
            rect=rect,
            radius=8,
            color=0x27303D if name not in ("stress", "blur") else (0x24533A if (name == "stress" and STRESSMODE) or (name == "blur" and BLURMODE) else 0x27303D),
        ))
        commands.append(managedtext(
            buttonx + 12,
            buttony + 8,
            label,
            13,
            FONTFILE,
            TEXT,
            nodeid=f"button-{name}-label",
            clip=[buttonx + 8, buttony + 4, buttonwidth - 16, 26],
        ))
        buttonx += buttonwidth + 10

    commands.append(managedtext(
        max(buttonx + 8, width - 255),
        buttony + 8,
        "Esc closes the test",
        13,
        FONTFILE,
        MUTED,
        nodeid="close-note",
        clip=[max(0, width - 260), buttony + 4, 236, 26],
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
        writestatus("scene-submitted", commands=len(commands))
        return bool(GRAPHICSSTATE.get("available"))

    except Exception as error:

        GRAPHICSERROR = str(error)
        manageddisable(GRAPHICSSTATE, GRAPHICSERROR)
        writestatus("scene-build-failed", error=GRAPHICSERROR)
        sendmessage({"op": "GRAPHICS_CLEAR", "winid": int(WINID)})
        return False



## fallback functions
def renderfallback(reason="managed OpenGL is unavailable"):
    # The OpenGL capability test is GPU-only.  A rejected retained scene must
    # fail closed; drawing a shared-buffer explanation would itself violate
    # the graphics contract it is intended to test.
    return False



## interaction functions
def startanimation():

    global ANIMATIONFORWARD, ANIMATIONUNTIL, LASTANIMATION
    global TRANSFORMROTATION, MOTIONTRANSLATE, PULSESCALE, FADEOPACITY

    if not GRAPHICSSTATE.get("active"):
        return

    ANIMATIONFORWARD = not ANIMATIONFORWARD
    duration = 1100
    trackdistance = max(80.0, float((WINW - 44 - 28) // 3 - 138))

    if ANIMATIONFORWARD:

        rotation = 360.0
        motion = [trackdistance, 0.0]
        scale = [1.35, 1.35]
        opacity = 1.0

    else:

        rotation = 0.0
        motion = [0.0, 0.0]
        scale = [1.0, 1.0]
        opacity = 0.35

    try:

        managedanimate(GRAPHICSSTATE, sendmessage, WINID, "transform-group", "rotation", rotation, duration=duration, easing="ease_in_out", start=TRANSFORMROTATION)
        managedanimate(GRAPHICSSTATE, sendmessage, WINID, "motion-node", "translate", motion, duration=duration, easing="ease_in_out", start=MOTIONTRANSLATE)
        managedanimate(GRAPHICSSTATE, sendmessage, WINID, "pulse-group", "scale", scale, duration=duration, easing="ease_in_out", start=PULSESCALE)
        managedanimate(GRAPHICSSTATE, sendmessage, WINID, "spin-node", "rotation", rotation, duration=duration, easing="ease_in_out", start=TRANSFORMROTATION)
        managedanimate(GRAPHICSSTATE, sendmessage, WINID, "spin-node", "opacity", opacity, duration=duration, easing="linear", start=FADEOPACITY)
        TRANSFORMROTATION = rotation
        MOTIONTRANSLATE = list(motion)
        PULSESCALE = list(scale)
        FADEOPACITY = opacity
        LASTANIMATION = time.monotonic()
        ANIMATIONUNTIL = LASTANIMATION + duration / 1000.0 + 0.1

    except Exception:

        pass


def toggleblur():

    global BLURMODE

    if WINID is None:
        return

    BLURMODE = not BLURMODE
    sendmessage({
        "op": "WINDOW_EFFECTS",
        "winid": int(WINID),
        "opacity": 0.9 if BLURMODE else 1.0,
        "blur": 12 if BLURMODE else 0,
        "shadow": True,
        "transition": True,
        "transition_ms": 220,
    })
    invalidatescene([0, max(0, WINH - 70), WINW, 70])


def activate(name):

    global STRESSMODE, EFFECTINDEX

    if name == "animate":
        startanimation()

    elif name == "stress":

        STRESSMODE = not STRESSMODE
        invalidatescene()

    elif name == "effect":

        EFFECTINDEX = (EFFECTINDEX + 1) % len(EFFECTS)
        invalidatescene()

    elif name == "blur":
        toggleblur()


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

    if key == "A":
        activate("animate")

    elif key == "S":
        activate("stress")

    elif key == "E":
        activate("effect")

    elif key == "B":
        activate("blur")



## window functions
def mapwindow():

    global MAPPED

    if WINID is None or MAPPED:
        return

    sendmessage({"op": "MAP", "winid": int(WINID), "transition": True, "transition_ms": 280})
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
        "x": 180,
        "y": 120,
        "pid": os.getpid(),
    })


def resized(message):

    global WINW, WINH, ANIMATIONFORWARD
    global TRANSFORMROTATION, MOTIONTRANSLATE, PULSESCALE, FADEOPACITY

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
    ANIMATIONFORWARD = False
    TRANSFORMROTATION = 0.0
    MOTIONTRANSLATE = [0.0, 0.0]
    PULSESCALE = [1.0, 1.0]
    FADEOPACITY = 0.35

    try:

        initbuffer(WINBUFFER, WINW, WINH)

    except Exception as error:

        manageddisable(GRAPHICSSTATE, str(error))

    renderfallback("preparing resized retained scene")
    invalidatescene()
    submitscene()


def updatetelemetry(message):

    global TELEMETRYTEXT, TELEMETRYDETAIL

    state = message.get("state", {}) if isinstance(message.get("state"), dict) else {}
    telemetry = state.get("telemetry", {}) if isinstance(state.get("telemetry"), dict) else {}
    windows = message.get("windows", []) if isinstance(message.get("windows"), list) else []
    owned = next((value for value in windows if int(value.get("winid", 0)) == int(WINID or 0)), {})
    renderer = str(state.get("renderer", "OpenGL")).strip() or "OpenGL"
    renderer = renderer.split(";")[0]
    hardware = bool(state.get("hardware_accelerated", False))
    compositor = str(state.get("window_compositor", "gpu")).upper()
    average = float(telemetry.get("average_frame_ms", 0.0))
    percentile = float(telemetry.get("percentile_95_frame_ms", 0.0))
    presentations = int(telemetry.get("presentation_samples", 0))
    presentedfps = float(telemetry.get("presented_fps", 0.0))
    draws = float(telemetry.get("draw_calls_per_frame", 0.0))
    texturemegabytes = float(telemetry.get("texture_bytes", 0)) / (1024.0 * 1024.0)
    mode = "hardware" if hardware else "software"
    TELEMETRYTEXT = f"{mode} {compositor} | {renderer}"
    presentationtext = (
        f"{presentedfps:.1f} displayed FPS"
        if presentations
        else "display cadence measuring"
    )
    TELEMETRYDETAIL = (
        f"{presentationtext}  |  {average:.2f} ms render average  |  "
        f"{percentile:.2f} ms render p95  |  {draws:.1f} draws/frame  |  "
        f"{texturemegabytes:.1f} MB textures  |  {int(owned.get('patch_commits', 0))} retained patches"
    )
    invalidatescene([0, 0, WINW, 82])
    invalidatescene([0, max(0, WINH - 108), WINW, 108])


def handlemessage(message):

    global CAPABILITIES, WINID, WINBUFFER, WINW, WINH, RUNNING, GRAPHICSERROR

    operation = str(message.get("op", ""))

    if operation == "WELCOME":

        CAPABILITIES = dict(message.get("graphics", {})) if isinstance(message.get("graphics"), dict) else {}
        required = (
            "rectangle",
            "rounded_rectangle",
            "border",
            "line",
            "circle",
            "gradient",
            "image",
            "text",
            "group",
            "layer",
        )
        managedconfigure(GRAPHICSSTATE, CAPABILITIES, required=required)

        if not CAPABILITIES.get("atomic_scene") or not CAPABILITIES.get("retained_scene"):
            manageddisable(GRAPHICSSTATE, "graphics API version 2 retained scenes are required")

        createwindow()
        return

    if operation == "WINDOW_CREATED":

        WINID = int(message.get("winid", 0))
        WINBUFFER = str(message.get("buffer", ""))
        WINW = max(1, int(message.get("w", WINDOWWIDTH)))
        WINH = max(1, int(message.get("h", WINDOWHEIGHT)))
        writestatus("window-created")

        if GRAPHICSSTATE.get("available"):

            invalidatescene()
            submitscene()
            # Commit acknowledgements are deliberately tied to a real DRM
            # presentation.  Mapping only after GRAPHICS_COMMITTED deadlocks:
            # an unmapped window cannot be presented, so its receipt cannot be
            # released.  Map the already managed-only scene now; no shared
            # buffer is exposed while the first GPU frame is pending.
            mapwindow()

        else:

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
            )
            mapwindow()

        return

    if operation == "GRAPHICS_TELEMETRY":

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



## diagnostic functions
def diagnostic():

    global TELEMETRYTEXT

    result = {"format": 1, "passed": False, "checks": {}, "errors": []}

    try:

        commands = buildscene(WINDOWWIDTH, WINDOWHEIGHT)
        kinds = set(str(command.get("kind", "")) for command in commands)
        required = {
            "rectangle",
            "rounded_rectangle",
            "border",
            "line",
            "circle",
            "gradient",
            "image",
            "text",
            "group",
            "layer",
        }

        if commands[0].get("kind") != "rectangle" or commands[0].get("rect") != [0, 0, WINDOWWIDTH, WINDOWHEIGHT]:
            raise RuntimeError("the showcase scene does not begin with a complete opaque background")

        if not required.issubset(kinds):
            raise RuntimeError(f"the showcase scene is missing commands {sorted(required - kinds)}")

        identifiers = [str(command.get("id")) for command in commands if command.get("id")]

        if len(identifiers) != len(set(identifiers)):
            raise RuntimeError("the showcase scene contains duplicate stable node ids")

        if len(commands) > 256:
            raise RuntimeError(f"the showcase scene uses an excessive command count {len(commands)}")

        capabilities = {
            "version": 2,
            "accelerated": True,
            "managed_resources": True,
            "atomic_scene": True,
            "retained_scene": True,
            "commands": sorted(required),
            "command_limit": 1024,
            "text_limit": 1024,
            "damage_limit": 64,
            "node_animation": {
                "properties": ["opacity", "translate", "scale", "rotation"],
                "easings": ["linear", "ease_in", "ease_out", "ease_in_out"],
                "duration_limit_ms": 5000,
            },
        }
        state = managedstate()

        if not managedconfigure(state, capabilities, required=tuple(sorted(required))):
            raise RuntimeError("the showcase did not negotiate the controlled graphics API")

        requests = []
        managedmarkdamage(state, [0, 0, WINDOWWIDTH, WINDOWHEIGHT], bounds=(WINDOWWIDTH, WINDOWHEIGHT))
        managedsubmit(state, lambda request: requests.append(request) or True, 77, commands)

        if len(requests) != 1 or requests[0].get("op") != "GRAPHICS_SCENE":
            raise RuntimeError("the initial showcase did not submit one atomic scene")

        managedresponse(state, {
            "op": "GRAPHICS_COMMITTED",
            "winid": 77,
            "accelerated": True,
            "managed_only": True,
            "generation": 1,
            "count": len(commands),
        })
        TELEMETRYTEXT = "hardware GPU | diagnostic renderer"
        updated = buildscene(WINDOWWIDTH, WINDOWHEIGHT)
        managedmarkdamage(state, [0, 0, WINDOWWIDTH, 82], bounds=(WINDOWWIDTH, WINDOWHEIGHT))
        managedsubmit(state, lambda request: requests.append(request) or True, 77, updated)

        if len(requests) != 2 or requests[-1].get("op") != "GRAPHICS_PATCH" or not requests[-1].get("upsert"):
            raise RuntimeError("the showcase telemetry update did not use a retained-scene patch")

        managedresponse(state, {
            "op": "GRAPHICS_COMMITTED",
            "winid": 77,
            "accelerated": True,
            "managed_only": True,
            "generation": 2,
            "patch": True,
            "count": len(updated),
        })
        managedanimate(
            state,
            lambda request: requests.append(request) or True,
            77,
            "motion-node",
            "translate",
            [100.0, 0.0],
            duration=800,
            easing="ease_in_out",
            start=[0.0, 0.0],
        )

        if requests[-1].get("op") != "GRAPHICS_ANIMATE":
            raise RuntimeError("the showcase did not use controlled server-side animation")

        if any(str(command.get("kind", "")) == "shader" for command in commands):
            raise RuntimeError("the showcase attempted to own a raw shader")

        result["checks"] = {
            "complete_background": True,
            "command_kinds": sorted(kinds),
            "commands": len(commands),
            "stable_node_ids": len(identifiers),
            "atomic_scene": True,
            "retained_patch": True,
            "damage_regions": requests[1].get("damage", []),
            "controlled_animation": True,
            "raw_shaders": False,
            "single_python_file": True,
        }
        result["passed"] = True

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

    if MAPPED and GRAPHICSSTATE.get("active") and now - LASTTELEMETRY >= 1.5 and now >= ANIMATIONUNTIL:

        LASTTELEMETRY = now
        sendmessage({"op": "GRAPHICS_TELEMETRY"})

    if MAPPED and GRAPHICSSTATE.get("active") and now - LASTANIMATION >= 4.0 and now >= ANIMATIONUNTIL:
        startanimation()


def cleanup():

    try:

        if SOCK is not None and WINID is not None:

            sendmessage({"op": "GRAPHICS_CLEAR", "winid": int(WINID)})
            flushmessages()

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
    createimage()
    connectwindowserver()
    deadline = time.monotonic() + 8.0

    while RUNNING and WINID is None and time.monotonic() < deadline:
        pumpsocket(0.05)

    if WINID is None:
        raise RuntimeError("windowserver did not create the OpenGL capability test window")

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
