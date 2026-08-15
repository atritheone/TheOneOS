"""Exercise the private Chromium X11 protocol bridge on an existing display."""

import ctypes
import json
import sys
import time


Display = ctypes.c_void_p
Window = ctypes.c_ulong
Atom = ctypes.c_ulong
Cursor = ctypes.c_ulong


class ClientMessageData(ctypes.Union):

    _fields_ = [
        ("bytes", ctypes.c_char * 20),
        ("shorts", ctypes.c_short * 10),
        ("longs", ctypes.c_long * 5),
    ]


class ClientMessageEvent(ctypes.Structure):

    _fields_ = [
        ("type", ctypes.c_int),
        ("serial", ctypes.c_ulong),
        ("send_event", ctypes.c_int),
        ("display", Display),
        ("window", Window),
        ("message_type", Atom),
        ("format", ctypes.c_int),
        ("data", ClientMessageData),
    ]


class Event(ctypes.Union):

    _fields_ = [
        ("type", ctypes.c_int),
        ("client", ClientMessageEvent),
        ("padding", ctypes.c_long * 24),
    ]


def loadx11():

    x11 = ctypes.CDLL("libX11.so.6")
    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XOpenDisplay.restype = Display
    x11.XDefaultRootWindow.argtypes = [Display]
    x11.XDefaultRootWindow.restype = Window
    x11.XCreateSimpleWindow.argtypes = [
        Display, Window, ctypes.c_int, ctypes.c_int,
        ctypes.c_uint, ctypes.c_uint, ctypes.c_uint,
        ctypes.c_ulong, ctypes.c_ulong,
    ]
    x11.XCreateSimpleWindow.restype = Window
    x11.XInternAtom.argtypes = [Display, ctypes.c_char_p, ctypes.c_int]
    x11.XInternAtom.restype = Atom
    x11.XGetGeometry.argtypes = [
        Display, Window, ctypes.POINTER(Window),
        ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint),
        ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint),
    ]
    x11.XGetGeometry.restype = ctypes.c_int
    x11.XSendEvent.argtypes = [
        Display, Window, ctypes.c_int, ctypes.c_long, ctypes.POINTER(Event),
    ]
    x11.XSendEvent.restype = ctypes.c_int
    x11.XClearArea.argtypes = [
        Display, Window, ctypes.c_int, ctypes.c_int,
        ctypes.c_uint, ctypes.c_uint, ctypes.c_int,
    ]
    x11.XClearArea.restype = ctypes.c_int
    x11.XGetImage.argtypes = [
        Display, Window, ctypes.c_int, ctypes.c_int,
        ctypes.c_uint, ctypes.c_uint, ctypes.c_ulong, ctypes.c_int,
    ]
    x11.XGetImage.restype = ctypes.c_void_p
    x11.XGetPixel.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
    x11.XGetPixel.restype = ctypes.c_ulong
    x11.XDestroyImage.argtypes = [ctypes.c_void_p]
    x11.XDestroyImage.restype = ctypes.c_int
    x11.XCreateFontCursor.argtypes = [Display, ctypes.c_uint]
    x11.XCreateFontCursor.restype = Cursor
    x11.XDefineCursor.argtypes = [Display, Window, Cursor]
    x11.XDefineCursor.restype = ctypes.c_int
    x11.XFreeCursor.argtypes = [Display, Cursor]
    x11.XFreeCursor.restype = ctypes.c_int
    return x11


def main():

    arguments = [int(value) for value in sys.argv[1:]]
    if arguments and len(arguments) % 2:
        raise ValueError("fullscreen dimensions must be width/height pairs")
    expectedsizes = list(zip(arguments[0::2], arguments[1::2]))
    if not expectedsizes:
        expectedsizes = [(1920, 1080)]
    x11 = loadx11()
    xfixes = ctypes.CDLL("libXfixes.so.3")
    xfixes.XFixesQueryVersion.argtypes = [
        Display, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
    ]
    xfixes.XFixesQueryVersion.restype = ctypes.c_int
    xfixes.XFixesSetCursorName.argtypes = [Display, Cursor, ctypes.c_char_p]
    xfixes.XFixesSetCursorName.restype = None
    display = x11.XOpenDisplay(None)

    if not display:
        raise RuntimeError("could not connect to the private Chromium X display")

    fixesmajor = ctypes.c_int(2)
    fixesminor = ctypes.c_int(0)
    if not xfixes.XFixesQueryVersion(
        display, ctypes.byref(fixesmajor), ctypes.byref(fixesminor),
    ) or fixesmajor.value < 2:
        raise RuntimeError("XFixes cursor names are unavailable")

    root = x11.XDefaultRootWindow(display)
    window = x11.XCreateSimpleWindow(
        display, root, 37, 29, 800, 600, 0, 0, 0x223344,
    )
    x11.XStoreName(display, window, b"T1OS Chromium XWM diagnostic")
    x11.XMapWindow(display, window)
    x11.XSync(display, 0)
    cursors = []

    def setnamedcursor(shape, name):

        cursor = x11.XCreateFontCursor(display, int(shape))
        if not cursor:
            raise RuntimeError(f"could not create the {name} diagnostic cursor")
        cursors.append(cursor)
        xfixes.XFixesSetCursorName(display, cursor, name.encode("ascii"))
        x11.XDefineCursor(display, window, cursor)
        x11.XSync(display, 0)
        time.sleep(0.03)

    def geometry():

        returnedroot = Window()
        x = ctypes.c_int()
        y = ctypes.c_int()
        width = ctypes.c_uint()
        height = ctypes.c_uint()
        border = ctypes.c_uint()
        depth = ctypes.c_uint()

        if not x11.XGetGeometry(
            display, window, ctypes.byref(returnedroot),
            ctypes.byref(x), ctypes.byref(y),
            ctypes.byref(width), ctypes.byref(height),
            ctypes.byref(border), ctypes.byref(depth),
        ):
            raise RuntimeError("could not query the diagnostic X window")

        return [x.value, y.value, width.value, height.value]

    def waitgeometry(width, height, x=None, y=None):

        deadline = time.monotonic() + 3.0
        latest = None

        while time.monotonic() < deadline:
            x11.XSync(display, 0)
            latest = geometry()

            if (
                latest[2:] == [width, height]
                and (x is None or latest[0] == x)
                and (y is None or latest[1] == y)
            ):
                return latest

            time.sleep(0.02)

        raise RuntimeError(
            f"X window did not become {x},{y} {width}x{height}: {latest}"
        )

    def fullscreen(action):

        state = x11.XInternAtom(display, b"_NET_WM_STATE", 0)
        fullscreenatom = x11.XInternAtom(
            display, b"_NET_WM_STATE_FULLSCREEN", 0,
        )
        event = Event()
        event.client.type = 33
        event.client.send_event = 1
        event.client.display = display
        event.client.window = window
        event.client.message_type = state
        event.client.format = 32
        event.client.data.longs[0] = int(action)
        event.client.data.longs[1] = fullscreenatom
        event.client.data.longs[3] = 1
        mask = (1 << 19) | (1 << 20)

        if not x11.XSendEvent(
            display, root, 0, mask, ctypes.byref(event),
        ):
            raise RuntimeError("X server rejected the fullscreen request")

        x11.XSync(display, 0)

    def paint(rect, color):

        x, y, width, height = rect
        x11.XSetWindowBackground(display, window, int(color))
        x11.XClearArea(
            display, window, x, y, width, height, 0,
        )

    def pixels(points):

        image = x11.XGetImage(
            display, window, 0, 0, 1200, 700, 0xFFFFFFFFFFFFFFFF, 2,
        )
        if not image:
            raise RuntimeError("could not capture the diagnostic X window")
        try:
            return [
                int(x11.XGetPixel(image, int(x), int(y))) & 0xFFFFFF
                for x, y in points
            ]
        finally:
            x11.XDestroyImage(image)

    try:
        for shape, name in ((60, "pointer"), (152, "text"), (150, "wait")):
            setnamedcursor(shape, name)
        initial = waitgeometry(800, 600)
        x11.XResizeWindow(display, window, 1200, 700)
        theatre = waitgeometry(1200, 700)
        fullscreens = []
        for expectedwidth, expectedheight in expectedsizes:
            fullscreen(1)
            waitgeometry(1200, 700, 0, 0)
            x11.XResizeWindow(
                display, window, expectedwidth, expectedheight,
            )
            fullscreens.append(
                waitgeometry(expectedwidth, expectedheight, 0, 0)
            )
            fullscreen(0)
            restored = waitgeometry(1200, 700, 37, 29)

        # Queue disjoint and overlapping updates faster than the XWM can fence
        # each one. Delta-rectangle reporting must preserve the disjoint
        # additions, while the final shared surface must contain the newest
        # value from every repeatedly repainted overlap.
        stressrects = [
            ([20, 20, 80, 60], 0x1122CC),
            ([260, 20, 90, 60], 0x22CC33),
            ([500, 20, 90, 60], 0x8844DD),
            ([20, 260, 80, 70], 0xCC4422),
            ([260, 260, 90, 70], 0x55AA11),
        ]
        for rect, color in stressrects:
            paint(rect, color)
        overlap = [100, 100, 120, 90]
        overlapcolors = [
            0x101010, 0xE03020, 0x20D040, 0x3040E0,
            0xF0A010, 0x10A0F0, 0x5A12C3,
        ]
        for _ in range(32):
            for color in overlapcolors:
                paint(overlap, color)
        x11.XSync(display, 0)
        sampled = pixels(
            [
                (60, 50), (300, 50), (540, 50),
                (60, 295), (300, 295), (160, 145),
            ],
        )
        expectedpixels = [
            color for _, color in stressrects
        ] + [overlapcolors[-1]]
        if sampled != expectedpixels:
            raise RuntimeError(
                f"repaint stress left stale pixels {sampled} != {expectedpixels}"
            )
        time.sleep(0.15)
    finally:
        for cursor in cursors:
            x11.XFreeCursor(display, cursor)
        x11.XDestroyWindow(display, window)
        x11.XCloseDisplay(display)

    print(json.dumps({
        "fullscreen": fullscreens[-1],
        "fullscreen_resizes": fullscreens,
        "initial": initial,
        "restored": restored,
        "repaint_cycles": len(stressrects) + len(overlapcolors) * 32,
        "repaint_pixels": sampled,
        "theatre_resize": theatre,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
