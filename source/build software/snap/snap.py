#!"/the one/software/python/bin/python" -B

"""
snap.py

Snap is the standard screen-capture and annotation tool for The One OS.
"""


import atexit
import json
from math import ceil as mathceil, floor as mathfloor
import mmap
import os
import selectors
import shutil
import signal
import socket
import re
import sys
import time
import uuid


DIAGNOSTICMODE = len(sys.argv) > 1 and sys.argv[1] == '--diagnostic'

if not DIAGNOSTICMODE:

    sys.path.insert(0, '/the one/build')

    from reign.reign import currenttime, formatatreyandate
    from GODDESS.GODDESS import formatlog
    from exchange.exchange import exsetimage
    import graphics.graphics as gfx
    from graphics.graphics import blitfilepartfast, drawline, drawrect
    from graphics.graphics import drawtextttf, fillrectfast, initbuffer
    from graphics.graphics import initttffont, measuretext, present as gfxpresent
    from graphics.graphics import uiscalefactor, displayuiscale

else:

    def currenttime(epoch=None):
        return time.localtime(time.time() if epoch is None else epoch)

    def formatatreyandate(value):
        ae_year = value.tm_year - 2020
        return f'{value.tm_mday:02}:{value.tm_mon:02}:{ae_year}AE'

    def formatlog(software, message):
        return f'[{software}] {message}'


# paths
APPPATH = '/the one/build/snap/snap.py'
APPICON = '/the one/resources/expanse/snap/snaplogo.png'
WINDOWSOCK = '/.ephemeral/windowserver/accept.sock'
LOGFILE = '/the one/logs/snap.py.log'
FONT = '/the one/resources/fonts/atkinsonhyperlegiblenext.ttf'
IMAGELIBRARY = '/the one/catalogue/image'
SESSIONIDENTITYFILE = '/the one/settings/session/identity.json'
SESSIONIDENTITYMAXBYTES = 1024
SESSIONUSERNAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,31}')
SNAPROOT = f'/.ephemeral/snap/{os.getpid()}'
CLIPBOARDROOT = '/.ephemeral/snap/clipboard'
PREVIEWRAW = os.path.join(SNAPROOT, 'preview.bgra')
CAPTURERAW = os.path.join(SNAPROOT, 'capture.bgra')
DIMMEDRAW = os.path.join(SNAPROOT, 'capture-dimmed.bgra')

# application
APPNAME = 'snap'
APPROLE = 'window'
VERSION = 1
RUNNING = True
FOCUSED = True
PILIMAGE = None
PILIMAGEDRAW = None

# window state
BASEWINW = 940
BASEWINH = 620
MAINID = None
MAINBUF = None
WINW = BASEWINW
WINH = BASEWINH
OVERLAYID = None
OVERLAYBUF = None
OVERLAYW = 0
OVERLAYH = 0
OVERLAYMAPPED = False
BOUNDBUFFER = None
SCREENW = 0
SCREENH = 0
UISCALE = 1.0
WSOCK = None
INBUF = b''
OUTBUF = bytearray()
SEL = selectors.DefaultSelector()
NEEDMAIN = True

# t1os palette
COLOURBG = 0x000000
COLOURTEXT = 0xEFEFEF
COLOURSTATUS = 0x242424
COLOURDIVIDER = 0x3A3A3A
COLOURMUTED = 0x6A6A6A
COLOURERROR = 0xFF0000
COLOURPEN = 0xE84040
COLOURHIGHLIGHT = 0xF2D64B

# layout
BASEPAD = 8
BASEROWH = 42
BASESTATUSH = 28
BASEFONTSIZE = 15
BASESMALLFONT = 13
PAD = BASEPAD
ROWH = BASEROWH
STATUSH = BASESTATUSH
FONTSIZE = BASEFONTSIZE
SMALLFONT = BASESMALLFONT
HOVER = None

# snapping state
MODES = (
    ('rectangular', 'rectangular'),
    ('window', 'window'),
    ('full_screen', 'full-screen'),
)
DELAYS = (0, 1, 3, 5)
MODE = 'rectangular'
DELAYINDEX = 0
CAPTURESTATE = 'idle'
CAPTUREAT = 0.0
CAPTUREREQUEST = ''
CAPTUREPATH = ''
CAPTUREWINDOWS = []
BASEIMAGE = None
DRAWIMAGE = None
TOOL = None
STROKING = False
LASTIMAGEPOINT = None
STATUS = 'choose a snap mode, then select new'
STATUSERROR = False
PREVIEW = None
PREVIEWDIRTY = True

# overlay selection state
SELECTING = False
SELECTSTART = None
SELECTCURRENT = None
WINDOWHOVER = None
OVERLAYPOINTER = (0, 0)
OVERLAYREADY = False
OVERLAYLASTRECT = None
OVERLAYLASTPOINTER = None
OVERLAYLASTCANCEL = False
OVERLAYPAINTPENDING = False
OVERLAYLASTPAINT = 0.0
OVERLAYFRAMEINTERVAL = 1.0 / 60.0

# The selection overlay repeatedly copies small pieces of these immutable
# surfaces. Keeping them mapped avoids opening, locking, seeking, and reading
# the raw files several times for every pointer update.
CAPTUREMAP = None
DIMMEDMAP = None
CAPTUREFD = None
DIMMEDFD = None

# picker
PICKERVERSION = 0
PICKERPENDING = None


def log(message):

    try:
        os.makedirs(os.path.dirname(LOGFILE), exist_ok=True)
        with open(LOGFILE, 'a', encoding='utf-8') as stream:
            stream.write(formatlog('snap', str(message)) + '\n')
    except Exception:
        pass


def scale(value):

    try:
        return max(1, int(round(float(value) * float(UISCALE))))
    except Exception:
        return max(1, int(value))


def applyscale():

    global UISCALE, PAD, ROWH, STATUSH, FONTSIZE, SMALLFONT

    try:
        factor = uiscalefactor() if not DIAGNOSTICMODE else 1.0
        UISCALE = displayuiscale(SCREENW, SCREENH, factor)
    except Exception:
        UISCALE = 1.0

    PAD = scale(BASEPAD)
    ROWH = scale(BASEROWH)
    STATUSH = scale(BASESTATUSH)
    FONTSIZE = scale(BASEFONTSIZE)
    SMALLFONT = scale(BASESMALLFONT)


def loadpillow():

    global PILIMAGE, PILIMAGEDRAW

    if PILIMAGE is not None and PILIMAGEDRAW is not None:
        return PILIMAGE, PILIMAGEDRAW

    if os.path.isdir(IMAGELIBRARY) and IMAGELIBRARY not in sys.path:
        sys.path.insert(0, IMAGELIBRARY)

    from PIL import Image, ImageDraw
    PILIMAGE = Image
    PILIMAGEDRAW = ImageDraw
    return PILIMAGE, PILIMAGEDRAW


def setstatus(message, error=False):

    global STATUS, STATUSERROR
    STATUS = str(message)[:240]
    STATUSERROR = bool(error)
    redraw()


def makedirs():

    os.makedirs(SNAPROOT, mode=0o700, exist_ok=True)
    os.makedirs(CLIPBOARDROOT, mode=0o700, exist_ok=True)


def pointin(x, y, rect):

    return (
        int(rect[0]) <= int(x) < int(rect[0]) + int(rect[2])
        and int(rect[1]) <= int(y) < int(rect[1]) + int(rect[3])
    )


def cliprect(rect, width, height):

    x, y, w, h = [int(value) for value in rect]
    left = max(0, min(int(width), x))
    top = max(0, min(int(height), y))
    right = max(left, min(int(width), x + max(0, w)))
    bottom = max(top, min(int(height), y + max(0, h)))
    return [left, top, right - left, bottom - top]


def rectfrompoints(first, second):

    x1, y1 = [int(value) for value in first]
    x2, y2 = [int(value) for value in second]
    return [min(x1, x2), min(y1, y2), abs(x2 - x1) + 1, abs(y2 - y1) + 1]


def intersectrect(first, second):

    if first is None or second is None:
        return None
    ax, ay, aw, ah = [int(value) for value in first]
    bx, by, bw, bh = [int(value) for value in second]
    left = max(ax, bx)
    top = max(ay, by)
    right = min(ax + aw, bx + bw)
    bottom = min(ay + ah, by + bh)
    if right <= left or bottom <= top:
        return None
    return [left, top, right - left, bottom - top]


def subtractrect(first, second):

    if first is None:
        return []
    overlap = intersectrect(first, second)
    if overlap is None:
        return [list(first)]

    x, y, width, height = [int(value) for value in first]
    ox, oy, ow, oh = overlap
    right = x + width
    bottom = y + height
    parts = []

    if oy > y:
        parts.append([x, y, width, oy - y])
    if oy + oh < bottom:
        parts.append([x, oy + oh, width, bottom - (oy + oh)])
    if ox > x:
        parts.append([x, oy, ox - x, oh])
    if ox + ow < right:
        parts.append([ox + ow, oy, right - (ox + ow), oh])
    return [part for part in parts if part[2] > 0 and part[3] > 0]


def borderrects(rect, thickness=2):

    if rect is None:
        return []
    x, y, width, height = [int(value) for value in rect]
    thickness = max(1, int(thickness))
    return [
        [x - thickness, y - thickness, width + thickness * 2, thickness * 2 + 1],
        [x - thickness, y + height - 1, width + thickness * 2, thickness * 2 + 1],
        [x - thickness, y, thickness * 2 + 1, height],
        [x + width - 1, y, thickness * 2 + 1, height],
    ]


def crosshairrect(point):

    if point is None:
        return None
    length = scale(11)
    return [int(point[0]) - length, int(point[1]) - length, length * 2 + 1, length * 2 + 1]


def currentmode():

    return next((label for value, label in MODES if value == MODE), MODE)


def hascapture():

    return DRAWIMAGE is not None


def previewarea():

    top = ROWH * 2
    return [PAD, top + PAD, max(1, WINW - PAD * 2), max(1, WINH - top - STATUSH - PAD * 2)]


def imageplacement():

    return list(PREVIEW or [0, 0, 0, 0])


def buttons():

    controls = []

    def add(action, label, x, y, width, enabled=True, selected=False):
        controls.append({
            'action': action,
            'label': label,
            'rect': [int(x), int(y), int(width), int(ROWH)],
            'enabled': bool(enabled),
            'selected': bool(selected),
        })
        return int(x) + int(width) + scale(3)

    x = PAD
    x = add('new', 'new', x, 0, scale(66), enabled=CAPTURESTATE == 'idle')
    x = add('save', 'save', x, 0, scale(62), enabled=hascapture())
    x = add('copy', 'copy', x, 0, scale(62), enabled=hascapture())
    x += scale(8)
    x = add('tool:pen', 'pen', x, 0, scale(58), enabled=hascapture(), selected=TOOL == 'pen')
    x = add('tool:highlighter', 'highlighter', x, 0, scale(98), enabled=hascapture(), selected=TOOL == 'highlighter')
    add('tool:eraser', 'eraser', x, 0, scale(72), enabled=hascapture(), selected=TOOL == 'eraser')

    x = PAD
    for value, label in MODES:
        width = {
            'rectangular': 104,
            'window': 76,
            'full_screen': 100,
        }[value]
        x = add(f'mode:{value}', label, x, ROWH, scale(width), enabled=CAPTURESTATE == 'idle', selected=MODE == value)

    x += scale(10)
    add('delay', f'delay: {DELAYS[DELAYINDEX]}s', x, ROWH, scale(92), enabled=CAPTURESTATE == 'idle')
    return controls


def buttonat(x, y):

    for button in buttons():
        if pointin(x, y, button['rect']):
            return button
    return None


def bindbuffer(path, width, height):

    global BOUNDBUFFER

    key = (os.path.abspath(str(path)), max(1, int(width)), max(1, int(height)))

    if (
        BOUNDBUFFER == key
        and getattr(gfx, '_buffer', None) is not None
        and len(getattr(gfx, '_buffer', b'')) == key[1] * key[2] * 4
    ):
        return

    mapping = getattr(gfx, '_FILE_MAP', None)

    if mapping:
        try:
            mapping.close()
        except Exception:
            pass
        setattr(gfx, '_FILE_MAP', None)

    descriptor = getattr(gfx, '_FILE_FD', None)

    if descriptor:
        try:
            os.close(descriptor)
        except Exception:
            pass
        setattr(gfx, '_FILE_FD', None)

    setattr(gfx, '_IS_FILE_BUFFER', False)
    initbuffer(path, key[1], key[2])
    BOUNDBUFFER = key


def presentrects(path, surfacewidth, surfaceheight, rects, winid):

    if not path or not winid:
        return False

    clipped = []
    seen = set()

    for rect in rects:
        item = cliprect(rect, surfacewidth, surfaceheight)
        key = tuple(item)
        if item[2] > 0 and item[3] > 0 and key not in seen:
            seen.add(key)
            clipped.append(item)

    buffer = getattr(gfx, '_buffer', None)
    stride = int(getattr(gfx, '_line', int(surfacewidth) * 4))

    if not clipped or buffer is None or stride < int(surfacewidth) * 4:
        return False

    try:
        presentdirty = getattr(gfx, 'presentdirty', None)

        if callable(presentdirty):
            for x, y, width, height in clipped:
                presentdirty(x, y, width, height)
        else:
            # Compatibility fallback for older graphics builds. Current t1os
            # keeps the backing file mapped and uses presentdirty above.
            with open(path, 'r+b', buffering=0) as output:
                locked = gfx.lockbuffer(output, exclusive=True)
                try:
                    for x, y, width, height in clipped:
                        rowbytes = int(width) * 4
                        for row in range(int(height)):
                            offset = (int(y) + row) * stride + int(x) * 4
                            output.seek(offset)
                            output.write(buffer[offset:offset + rowbytes])
                finally:
                    if locked:
                        gfx.unlockbuffer(output)

        for rect in clipped:
            sendws({'op': 'DAMAGE', 'winid': int(winid), 'rect': rect})
        return True
    except Exception as error:
        log(f'partial present error {error}')
        return False


def sendws(message):

    try:
        OUTBUF.extend(json.dumps(message, separators=(',', ':')).encode('utf-8') + b'\n')
    except Exception as error:
        log(f'windowserver send error {error}')


def flushws():

    if not OUTBUF or WSOCK is None:
        return

    try:
        sent = WSOCK.send(OUTBUF)
        del OUTBUF[:sent]
    except BlockingIOError:
        return
    except Exception as error:
        log(f'windowserver flush error {error}')


def recvws():

    global INBUF

    try:
        data = WSOCK.recv(65536)
        if not data:
            raise ConnectionError('windowserver disconnected')
        INBUF += data
    except BlockingIOError:
        return []

    messages = []

    while b'\n' in INBUF:
        line, INBUF = INBUF.split(b'\n', 1)
        if line.strip():
            messages.append(json.loads(line.decode('utf-8')))

    return messages


def connectws():

    global WSOCK
    WSOCK = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    WSOCK.connect(WINDOWSOCK)
    WSOCK.setblocking(False)
    SEL.register(WSOCK, selectors.EVENT_READ | selectors.EVENT_WRITE)


def createmain():

    sendws({
        'op': 'CREATE_WINDOW',
        'role': APPROLE,
        'title': APPNAME,
        'current': APPNAME,
        'path': APPPATH,
        'w': scale(BASEWINW),
        'h': scale(BASEWINH),
        'x': 130,
        'y': 90,
        'pid': os.getpid(),
    })


def createoverlay():

    sendws({
        'op': 'CREATE_WINDOW',
        'role': 'snap_overlay',
        'title': 'snap capture',
        'current': 'capture',
        'path': APPPATH,
        'w': int(SCREENW),
        'h': int(SCREENH),
        'x': 0,
        'y': 0,
        'pid': os.getpid(),
        'shadow': False,
        'transition': False,
    })


def cursor(winid, mode):

    if winid:
        sendws({'op': 'CURSOR_MODE_SET', 'winid': int(winid), 'mode': str(mode)})


def mapmain():

    if not MAINID or not MAINBUF:
        return

    bindbuffer(MAINBUF, WINW, WINH)
    rebuildpreview()
    paintmain()
    sendws({'op': 'MAP', 'winid': MAINID})
    sendws({'op': 'RAISE', 'winid': MAINID})
    sendws({'op': 'FOCUS_SET', 'winid': MAINID})


def writebgra(image, path):

    image = image.convert('RGBA')
    temporary = f'{path}.tmp-{os.getpid()}'

    try:
        with open(temporary, 'wb') as stream:
            stream.write(image.tobytes('raw', 'BGRA'))
            stream.flush()
        os.replace(temporary, path)
    finally:
        try:
            if os.path.exists(temporary):
                os.unlink(temporary)
        except OSError:
            pass


def closecapturesurfaces():

    global CAPTUREMAP, DIMMEDMAP, CAPTUREFD, DIMMEDFD

    for mapping in (CAPTUREMAP, DIMMEDMAP):
        if mapping is not None:
            try:
                mapping.close()
            except Exception:
                pass

    for descriptor in (CAPTUREFD, DIMMEDFD):
        if descriptor is not None:
            try:
                os.close(descriptor)
            except Exception:
                pass

    CAPTUREMAP = None
    DIMMEDMAP = None
    CAPTUREFD = None
    DIMMEDFD = None


def mapcapturesurfaces():

    global CAPTUREMAP, DIMMEDMAP, CAPTUREFD, DIMMEDFD

    closecapturesurfaces()
    CAPTUREFD = os.open(CAPTURERAW, os.O_RDONLY)
    DIMMEDFD = os.open(DIMMEDRAW, os.O_RDONLY)
    CAPTUREMAP = mmap.mmap(CAPTUREFD, 0, access=mmap.ACCESS_READ)
    DIMMEDMAP = mmap.mmap(DIMMEDFD, 0, access=mmap.ACCESS_READ)


def blitrawpartfast(source, totalwidth, srcx, srcy, width, height, dstx, dsty):

    buffer = getattr(gfx, '_buffer', None)
    targetstride = int(getattr(gfx, '_line', int(OVERLAYW) * 4))
    totalwidth = int(totalwidth)
    srcx = int(srcx)
    srcy = int(srcy)
    width = int(width)
    height = int(height)
    dstx = int(dstx)
    dsty = int(dsty)

    if source is None or buffer is None or totalwidth < 1 or width < 1 or height < 1:
        return False

    if dstx < 0:
        cut = -dstx
        srcx += cut
        width -= cut
        dstx = 0
    if dsty < 0:
        cut = -dsty
        srcy += cut
        height -= cut
        dsty = 0
    if dstx + width > OVERLAYW:
        width = OVERLAYW - dstx
    if dsty + height > OVERLAYH:
        height = OVERLAYH - dsty

    if width < 1 or height < 1:
        return False

    sourcestride = totalwidth * 4
    rowbytes = width * 4
    sourceview = memoryview(source)

    try:
        if srcx == 0 and dstx == 0 and rowbytes == sourcestride == targetstride:
            sourceoffset = srcy * sourcestride
            targetoffset = dsty * targetstride
            length = height * rowbytes
            buffer[targetoffset:targetoffset + length] = sourceview[sourceoffset:sourceoffset + length]
            return True

        for row in range(height):
            sourceoffset = (srcy + row) * sourcestride + srcx * 4
            targetoffset = (dsty + row) * targetstride + dstx * 4
            buffer[targetoffset:targetoffset + rowbytes] = sourceview[sourceoffset:sourceoffset + rowbytes]
    finally:
        sourceview.release()
    return True


def checkerbackground(width, height, originx=0, originy=0):

    imagemodule, drawmodule = loadpillow()
    image = imagemodule.new('RGBA', (int(width), int(height)), (18, 18, 18, 255))
    painter = drawmodule.Draw(image)
    tile = max(8, scale(12))
    firstx = (int(originx) // tile) * tile
    firsty = (int(originy) // tile) * tile

    for globaly in range(firsty, int(originy) + int(height), tile):
        for globalx in range(firstx, int(originx) + int(width), tile):
            if ((globalx // tile) + (globaly // tile)) % 2:
                left = max(0, globalx - int(originx))
                top = max(0, globaly - int(originy))
                right = min(int(width), globalx + tile - int(originx))
                bottom = min(int(height), globaly + tile - int(originy))
                painter.rectangle((left, top, right, bottom), fill=(30, 30, 30, 255))

    return image


def rebuildpreview():

    global PREVIEW, PREVIEWDIRTY

    if not hascapture():
        PREVIEW = None
        PREVIEWDIRTY = False
        return

    if not PREVIEWDIRTY and PREVIEW and os.path.isfile(PREVIEWRAW):
        return

    imagemodule, _ = loadpillow()
    area = previewarea()
    sourcewidth, sourceheight = DRAWIMAGE.size
    ratio = min(area[2] / float(sourcewidth), area[3] / float(sourceheight))
    width = max(1, int(round(sourcewidth * ratio)))
    height = max(1, int(round(sourceheight * ratio)))
    x = area[0] + (area[2] - width) // 2
    y = area[1] + (area[3] - height) // 2
    resampling = getattr(getattr(imagemodule, 'Resampling', imagemodule), 'LANCZOS')
    resized = DRAWIMAGE.resize((width, height), resampling)

    # A subtle checkerboard keeps captured edges legible without departing
    # from the black and charcoal t1os application palette.
    backdrop = checkerbackground(width, height)
    backdrop.alpha_composite(resized)
    writebgra(backdrop, PREVIEWRAW)
    PREVIEW = [x, y, width, height]
    PREVIEWDIRTY = False


def blitimagepatch(image, x, y):

    buffer = getattr(gfx, '_buffer', None)
    stride = int(getattr(gfx, '_line', int(WINW) * 4))
    x = int(x)
    y = int(y)
    width, height = image.size

    if buffer is None or stride < int(WINW) * 4:
        return False

    raw = image.convert('RGBA').tobytes('raw', 'BGRA')
    rowbytes = width * 4

    for row in range(height):
        sourceoffset = row * rowbytes
        targetoffset = (y + row) * stride + x * 4
        buffer[targetoffset:targetoffset + rowbytes] = raw[sourceoffset:sourceoffset + rowbytes]
    return True


def updatepreviewregion(sourcerect):

    global PREVIEWDIRTY

    if DIAGNOSTICMODE or not hascapture() or not PREVIEW:
        return False

    px, py, previewwidth, previewheight = PREVIEW
    sourcewidth, sourceheight = DRAWIMAGE.size
    sx, sy, sw, sh = cliprect(sourcerect, sourcewidth, sourceheight)

    if sw < 1 or sh < 1:
        return False

    left = max(0, int(mathfloor((sx * previewwidth) / float(sourcewidth))) - 2)
    top = max(0, int(mathfloor((sy * previewheight) / float(sourceheight))) - 2)
    right = min(previewwidth, int(mathceil(((sx + sw) * previewwidth) / float(sourcewidth))) + 2)
    bottom = min(previewheight, int(mathceil(((sy + sh) * previewheight) / float(sourceheight))) + 2)
    width = right - left
    height = bottom - top

    if width < 1 or height < 1:
        return False

    imagemodule, _ = loadpillow()
    resampling = getattr(getattr(imagemodule, 'Resampling', imagemodule), 'BILINEAR')
    sourceleft = max(0, int(mathfloor((left * sourcewidth) / float(previewwidth))))
    sourcetop = max(0, int(mathfloor((top * sourceheight) / float(previewheight))))
    sourceright = min(sourcewidth, int(mathceil((right * sourcewidth) / float(previewwidth))))
    sourcebottom = min(sourceheight, int(mathceil((bottom * sourceheight) / float(previewheight))))
    patch = DRAWIMAGE.crop((sourceleft, sourcetop, sourceright, sourcebottom)).resize(
        (width, height),
        resampling,
    )
    backdrop = checkerbackground(width, height, originx=left, originy=top)
    backdrop.alpha_composite(patch)

    expected = (os.path.abspath(str(MAINBUF)), int(WINW), int(WINH))

    if BOUNDBUFFER != expected:
        PREVIEWDIRTY = True
        paintmain()
        return True

    if not blitimagepatch(backdrop, px + left, py + top):
        return False

    # The on-screen backing buffer is updated immediately. Rebuild the cached
    # full preview only when a later full-window paint actually needs it.
    PREVIEWDIRTY = True
    return presentrects(
        MAINBUF,
        WINW,
        WINH,
        [[px + left, py + top, width, height]],
        MAINID,
    )


def textwidth(text, size=None):

    try:
        return int(measuretext(str(text), int(size or FONTSIZE), FONT))
    except Exception:
        return int(len(str(text)) * int(size or FONTSIZE) * 0.58)


def drawbutton(button):

    x, y, width, height = button['rect']
    hover = HOVER == button['action'] and button['enabled']

    if hover:
        fillrectfast(x, y, width, height, COLOURSTATUS)

    colour = COLOURTEXT if button['enabled'] else COLOURMUTED
    label = button['label']
    tx = x + max(scale(7), (width - textwidth(label)) // 2)
    ty = y + max(0, (height - FONTSIZE) // 2)
    drawtextttf(tx, ty, label, colour, FONTSIZE, FONT, clip=[x, y, width, height])

    if button['selected']:
        fillrectfast(x + scale(5), y + height - scale(2), max(1, width - scale(10)), scale(2), COLOURTEXT)


def drawempty():

    area = previewarea()
    title = 'snap'
    subtitle = 'choose a snap mode, then select new'
    titlefont = scale(34)
    x = area[0] + max(0, (area[2] - textwidth(title, titlefont)) // 2)
    y = area[1] + max(0, area[3] // 2 - scale(42))
    drawtextttf(x, y, title, COLOURTEXT, titlefont, FONT)
    sx = area[0] + max(0, (area[2] - textwidth(subtitle, FONTSIZE)) // 2)
    drawtextttf(sx, y + scale(50), subtitle, COLOURMUTED, FONTSIZE, FONT)


def paintmain():

    if not MAINID or not MAINBUF:
        return

    try:
        bindbuffer(MAINBUF, WINW, WINH)
        fillrectfast(0, 0, WINW, WINH, COLOURBG)
        fillrectfast(0, ROWH - 1, WINW, 1, COLOURDIVIDER)
        fillrectfast(0, ROWH * 2 - 1, WINW, 1, COLOURDIVIDER)

        for button in buttons():
            drawbutton(button)

        if hascapture():
            rebuildpreview()
            x, y, width, height = imageplacement()
            if width > 0 and height > 0 and os.path.isfile(PREVIEWRAW):
                blitfilepartfast(PREVIEWRAW, width, 0, 0, width, height, x, y, 'BGRA32')
                drawrect(x - 1, y - 1, width + 2, height + 2, COLOURDIVIDER)
        else:
            drawempty()

        statusy = max(0, WINH - STATUSH)
        fillrectfast(0, statusy, WINW, STATUSH, COLOURSTATUS)
        message = STATUS
        if hascapture():
            message = f'{STATUS}    {DRAWIMAGE.size[0]} x {DRAWIMAGE.size[1]}'
        drawtextttf(PAD, statusy + max(0, (STATUSH - SMALLFONT) // 2), message, COLOURERROR if STATUSERROR else COLOURTEXT, SMALLFONT, FONT, clip=[0, statusy, WINW, STATUSH])
        gfxpresent()
        sendws({'op': 'DAMAGE', 'winid': MAINID, 'rect': [0, 0, WINW, WINH]})
    except Exception as error:
        log(f'main paint error {error}')


def preparecapturesurfaces():

    imagemodule, _ = loadpillow()
    with imagemodule.open(CAPTUREPATH) as source:
        image = source.convert('RGBA')

    if image.size != (int(SCREENW), int(SCREENH)):
        raise RuntimeError(f'capture size {image.size} does not match display {SCREENW}x{SCREENH}')

    writebgra(image, CAPTURERAW)
    black = imagemodule.new('RGBA', image.size, (0, 0, 0, 255))
    dimmed = imagemodule.blend(image, black, 0.48)
    writebgra(dimmed, DIMMEDRAW)
    mapcapturesurfaces()


def selectionrect():

    if MODE == 'rectangular' and SELECTSTART is not None and SELECTCURRENT is not None:
        return cliprect(rectfrompoints(SELECTSTART, SELECTCURRENT), SCREENW, SCREENH)

    if MODE == 'window' and WINDOWHOVER is not None:
        return cliprect(WINDOWHOVER.get('rect', [0, 0, 0, 0]), SCREENW, SCREENH)

    return None


def overlaycancelrect():

    return [max(0, OVERLAYW - scale(92)), scale(7), scale(82), scale(28)]


def paintcrosshair(x, y):

    length = scale(9)
    drawline(x - length - 1, y, x + length + 1, y, 0x000000)
    drawline(x, y - length - 1, x, y + length + 1, 0x000000)
    drawline(x - length, y, x + length, y, COLOURTEXT)
    drawline(x, y - length, x, y + length, COLOURTEXT)


def drawoverlaychrome():

    fillrectfast(0, 0, OVERLAYW, scale(42), COLOURBG)
    instruction = {
        'rectangular': 'drag to select a rectangular snap',
        'window': 'select a window to snap',
    }.get(MODE, 'select an area to snap')
    drawtextttf(PAD, max(0, (scale(42) - FONTSIZE) // 2), instruction, COLOURTEXT, FONTSIZE, FONT)
    cx, cy, cw, ch = overlaycancelrect()
    if pointin(OVERLAYPOINTER[0], OVERLAYPOINTER[1], [cx, cy, cw, ch]):
        fillrectfast(cx, cy, cw, ch, COLOURSTATUS)
    drawtextttf(cx + scale(10), cy + max(0, (ch - SMALLFONT) // 2), 'cancel', COLOURTEXT, SMALLFONT, FONT)


def paintoverlay(full=False):

    global OVERLAYREADY, OVERLAYLASTRECT, OVERLAYLASTPOINTER, OVERLAYLASTCANCEL
    global OVERLAYPAINTPENDING, OVERLAYLASTPAINT

    if not OVERLAYID or not OVERLAYBUF or DIMMEDMAP is None or CAPTUREMAP is None:
        return

    try:
        expected = (os.path.abspath(str(OVERLAYBUF)), int(OVERLAYW), int(OVERLAYH))

        if BOUNDBUFFER != expected:
            full = True

        bindbuffer(OVERLAYBUF, OVERLAYW, OVERLAYH)
        selected = selectionrect()
        cancelhover = pointin(OVERLAYPOINTER[0], OVERLAYPOINTER[1], overlaycancelrect())

        if full or not OVERLAYREADY:
            blitrawpartfast(DIMMEDMAP, OVERLAYW, 0, 0, OVERLAYW, OVERLAYH, 0, 0)

            if selected and selected[2] > 0 and selected[3] > 0:
                x, y, width, height = selected
                blitrawpartfast(CAPTUREMAP, OVERLAYW, x, y, width, height, x, y)
                drawrect(x, y, width, height, COLOURTEXT)

            drawoverlaychrome()
            paintcrosshair(int(OVERLAYPOINTER[0]), int(OVERLAYPOINTER[1]))
            gfxpresent()
            sendws({'op': 'DAMAGE', 'winid': OVERLAYID, 'rect': [0, 0, OVERLAYW, OVERLAYH]})
            OVERLAYREADY = True
            OVERLAYLASTRECT = list(selected) if selected else None
            OVERLAYLASTPOINTER = tuple(OVERLAYPOINTER)
            OVERLAYLASTCANCEL = bool(cancelhover)
            OVERLAYPAINTPENDING = False
            OVERLAYLASTPAINT = time.monotonic()
            return

        dirty = []

        if selected != OVERLAYLASTRECT:
            dirty.extend(subtractrect(OVERLAYLASTRECT, selected))
            dirty.extend(subtractrect(selected, OVERLAYLASTRECT))
            dirty.extend(borderrects(OVERLAYLASTRECT))
            dirty.extend(borderrects(selected))

        dirty.append(crosshairrect(OVERLAYLASTPOINTER))
        dirty.append(crosshairrect(OVERLAYPOINTER))

        if bool(cancelhover) != bool(OVERLAYLASTCANCEL):
            dirty.append(overlaycancelrect())

        dirty = [
            cliprect(rect, OVERLAYW, OVERLAYH)
            for rect in dirty
            if rect is not None
        ]
        dirty = [rect for rect in dirty if rect[2] > 0 and rect[3] > 0]

        for x, y, width, height in dirty:
            blitrawpartfast(DIMMEDMAP, OVERLAYW, x, y, width, height, x, y)

        if selected and selected[2] > 0 and selected[3] > 0:
            for damaged in dirty:
                visible = intersectrect(selected, damaged)
                if visible:
                    x, y, width, height = visible
                    blitrawpartfast(CAPTUREMAP, OVERLAYW, x, y, width, height, x, y)
            drawrect(selected[0], selected[1], selected[2], selected[3], COLOURTEXT)

        chromerect = [0, 0, OVERLAYW, scale(42)]
        if bool(cancelhover) != bool(OVERLAYLASTCANCEL) or any(
            intersectrect(chromerect, damaged) for damaged in dirty
        ):
            drawoverlaychrome()
        paintcrosshair(int(OVERLAYPOINTER[0]), int(OVERLAYPOINTER[1]))
        presentrects(OVERLAYBUF, OVERLAYW, OVERLAYH, dirty, OVERLAYID)
        OVERLAYLASTRECT = list(selected) if selected else None
        OVERLAYLASTPOINTER = tuple(OVERLAYPOINTER)
        OVERLAYLASTCANCEL = bool(cancelhover)
        OVERLAYPAINTPENDING = False
        OVERLAYLASTPAINT = time.monotonic()
    except Exception as error:
        log(f'overlay paint error {error}')


def requestcapture():

    global CAPTURESTATE, CAPTUREREQUEST
    CAPTURESTATE = 'requesting'
    CAPTUREREQUEST = uuid.uuid4().hex
    sendws({
        'op': 'SCREEN_CAPTURE_REQUEST',
        'request_id': CAPTUREREQUEST,
        'parent': MAINID,
        'mode': MODE,
    })


def beginnew():

    global CAPTURESTATE, CAPTUREAT

    if CAPTURESTATE != 'idle' or not MAINID or PICKERPENDING is not None:
        return

    CAPTURESTATE = 'waiting_unmap'
    CAPTUREAT = 0.0
    delay = DELAYS[DELAYINDEX]
    setstatus('preparing snap' if delay == 0 else f'capturing in {delay} seconds')
    sendws({'op': 'UNMAP', 'winid': MAINID})


def showoverlay():

    global OVERLAYMAPPED

    if OVERLAYID is None:
        createoverlay()
        return

    if OVERLAYW != SCREENW or OVERLAYH != SCREENH:
        sendws({'op': 'RESIZE', 'winid': OVERLAYID, 'w': SCREENW, 'h': SCREENH})
        return

    paintoverlay(full=not OVERLAYREADY)
    OVERLAYMAPPED = True
    sendws({'op': 'MAP', 'winid': OVERLAYID})
    sendws({'op': 'RAISE', 'winid': OVERLAYID})
    sendws({'op': 'FOCUS_SET', 'winid': OVERLAYID})
    cursor(OVERLAYID, 'hidden')


def resetselection():

    global SELECTING, SELECTSTART, SELECTCURRENT, WINDOWHOVER, OVERLAYPAINTPENDING
    SELECTING = False
    SELECTSTART = None
    SELECTCURRENT = None
    WINDOWHOVER = None
    OVERLAYPAINTPENDING = False


def uniqueimagepath(root, prefix='Screenshot'):

    now = time.time()
    localtime = currenttime(now)
    date = formatatreyandate(localtime).replace(':', '-')
    stamp = f"{date} {time.strftime('%H.%M.%S', localtime)}"
    milliseconds = int((now - int(now)) * 1000.0)
    path = os.path.join(root, f'{prefix} {stamp}.{milliseconds:03d}.png')
    suffix = 2

    while os.path.exists(path):
        path = os.path.join(root, f'{prefix} {stamp}.{milliseconds:03d} ({suffix}).png')
        suffix += 1
    return path


def saveimage(image, path):

    destination = os.path.abspath(str(path))
    extension = os.path.splitext(destination)[1].lower()
    if not extension:
        destination += '.png'
        extension = '.png'

    formats = {
        '.png': 'PNG',
        '.jpg': 'JPEG',
        '.jpeg': 'JPEG',
        '.gif': 'GIF',
    }
    imageformat = formats.get(extension)
    if imageformat is None:
        raise ValueError('Snap can save PNG, JPEG, or GIF images')

    os.makedirs(os.path.dirname(destination), exist_ok=True)
    temporary = f'{destination}.tmp-{os.getpid()}'

    try:
        output = image
        if imageformat == 'JPEG':
            imagemodule, _ = loadpillow()
            background = imagemodule.new('RGB', image.size, (255, 255, 255))
            if image.mode == 'RGBA':
                background.paste(image, mask=image.getchannel('A'))
            else:
                background.paste(image.convert('RGB'))
            output = background
        elif imageformat == 'GIF':
            output = image.convert('P', palette=loadpillow()[0].Palette.ADAPTIVE)

        options = {'optimize': True}
        if imageformat == 'JPEG':
            options.update({'quality': 92, 'subsampling': 0})
        output.save(temporary, format=imageformat, **options)
        os.replace(temporary, destination)
    finally:
        try:
            if os.path.exists(temporary):
                os.unlink(temporary)
        except OSError:
            pass
    return destination


def copycapture(automatic=False):

    if not hascapture():
        return False

    try:
        os.makedirs(CLIPBOARDROOT, mode=0o700, exist_ok=True)
        path = uniqueimagepath(CLIPBOARDROOT)
        saveimage(DRAWIMAGE, path)
        ok, response = exsetimage({
            'path': path,
            'mime': 'image/png',
            'width': int(DRAWIMAGE.size[0]),
            'height': int(DRAWIMAGE.size[1]),
        }, source='snap')

        if not ok:
            raise RuntimeError(response.get('error', 'Exchange rejected image'))

        captures = sorted(
            (os.path.getmtime(os.path.join(CLIPBOARDROOT, name)), os.path.join(CLIPBOARDROOT, name))
            for name in os.listdir(CLIPBOARDROOT)
            if name.lower().endswith('.png') and os.path.isfile(os.path.join(CLIPBOARDROOT, name))
        )
        for _modified, candidate in captures[:-16]:
            try:
                os.unlink(candidate)
            except OSError:
                pass
        setstatus('snap copied to Exchange' if automatic else 'copied to Exchange')
        return True
    except Exception as error:
        setstatus(f'copy failed: {error}', error=True)
        log(f'copy failed {error}')
        return False


def finishcapture(rect):

    global BASEIMAGE, DRAWIMAGE, PREVIEWDIRTY, CAPTURESTATE, TOOL

    try:
        imagemodule, _ = loadpillow()
        with imagemodule.open(CAPTUREPATH) as source:
            result = cropselection(source, rect)

        BASEIMAGE = result.copy()
        DRAWIMAGE = result.copy()
        PREVIEWDIRTY = True
        TOOL = None
        CAPTURESTATE = 'idle'
        resetselection()
        copycapture(automatic=True)

        if OVERLAYID and OVERLAYMAPPED:
            cursor(OVERLAYID, 'arrow')
            sendws({'op': 'UNMAP', 'winid': OVERLAYID})
        else:
            mapmain()
        return True

    except Exception as error:
        setstatus(f'snap failed: {error}', error=True)
        log(f'capture finish error {error}')
        cancelcapture('snap cancelled')
        return False


def cancelcapture(message='snap cancelled'):

    global CAPTURESTATE
    CAPTURESTATE = 'idle'
    resetselection()
    setstatus(message)

    if OVERLAYID and OVERLAYMAPPED:
        cursor(OVERLAYID, 'arrow')
        sendws({'op': 'UNMAP', 'winid': OVERLAYID})
    else:
        mapmain()


def cropselection(source, rect):

    source = source.convert('RGBA')
    rect = cliprect(rect, source.size[0], source.size[1])

    if rect[2] < 2 or rect[3] < 2:
        raise ValueError('selection is too small')

    x, y, width, height = rect
    return source.crop((x, y, x + width, y + height))


def windowat(x, y):

    for item in reversed(CAPTUREWINDOWS):
        if pointin(x, y, item.get('rect', [0, 0, 0, 0])):
            return item
    return None


def overlaymotion(message):

    global SELECTCURRENT, WINDOWHOVER, OVERLAYPOINTER, OVERLAYPAINTPENDING
    x = max(0, min(OVERLAYW - 1, int(message.get('x', 0))))
    y = max(0, min(OVERLAYH - 1, int(message.get('y', 0))))
    previouspointer = OVERLAYPOINTER
    previousrect = selectionrect()
    OVERLAYPOINTER = (x, y)

    if MODE == 'rectangular' and SELECTING:
        SELECTCURRENT = (x, y)
    elif MODE == 'window':
        WINDOWHOVER = windowat(x, y)

    if OVERLAYPOINTER != previouspointer or selectionrect() != previousrect:
        OVERLAYPAINTPENDING = True


def overlaybutton(message):

    global SELECTING, SELECTSTART, SELECTCURRENT, OVERLAYPAINTPENDING

    if int(message.get('button', 1)) != 1:
        return

    state = str(message.get('state', 'down')).lower()
    x = max(0, min(OVERLAYW - 1, int(message.get('x', 0))))
    y = max(0, min(OVERLAYH - 1, int(message.get('y', 0))))

    if state == 'down':
        if pointin(x, y, overlaycancelrect()):
            cancelcapture()
            return

        if MODE == 'window':
            target = windowat(x, y)
            if target:
                finishcapture(target['rect'])
            return

        SELECTING = True
        SELECTSTART = (x, y)
        SELECTCURRENT = (x, y)
        OVERLAYPAINTPENDING = False
        paintoverlay()
        return

    if state != 'up' or not SELECTING:
        return

    SELECTING = False
    SELECTCURRENT = (x, y)

    if MODE == 'rectangular':
        finishcapture(rectfrompoints(SELECTSTART, SELECTCURRENT))


def previewtoimage(x, y):

    if not hascapture() or not PREVIEW or not pointin(x, y, PREVIEW):
        return None

    px, py, width, height = PREVIEW
    ix = int((int(x) - px) * DRAWIMAGE.size[0] / float(max(1, width)))
    iy = int((int(y) - py) * DRAWIMAGE.size[1] / float(max(1, height)))
    return (
        max(0, min(DRAWIMAGE.size[0] - 1, ix)),
        max(0, min(DRAWIMAGE.size[1] - 1, iy)),
    )


def annotatesegment(first, second):

    global DRAWIMAGE

    if not hascapture() or TOOL not in ('pen', 'highlighter', 'eraser'):
        return False

    imagemodule, drawmodule = loadpillow()

    if TOOL == 'pen':
        width = max(2, int(round(min(DRAWIMAGE.size) * 0.004)))
    elif TOOL == 'highlighter':
        width = max(7, int(round(min(DRAWIMAGE.size) * 0.018)))
    else:
        width = max(8, int(round(min(DRAWIMAGE.size) * 0.025)))

    margin = max(3, width // 2 + 3)
    dirty = cliprect([
        min(int(first[0]), int(second[0])) - margin,
        min(int(first[1]), int(second[1])) - margin,
        abs(int(second[0]) - int(first[0])) + margin * 2 + 1,
        abs(int(second[1]) - int(first[1])) + margin * 2 + 1,
    ], DRAWIMAGE.size[0], DRAWIMAGE.size[1])
    x, y, regionwidth, regionheight = dirty
    localfirst = (int(first[0]) - x, int(first[1]) - y)
    localsecond = (int(second[0]) - x, int(second[1]) - y)

    if TOOL == 'eraser':
        current = DRAWIMAGE.crop((x, y, x + regionwidth, y + regionheight))
        original = BASEIMAGE.crop((x, y, x + regionwidth, y + regionheight))
        mask = imagemodule.new('L', (regionwidth, regionheight), 0)
        painter = drawmodule.Draw(mask)
        painter.line((localfirst, localsecond), fill=255, width=width)
        current.paste(original, (0, 0), mask)
        DRAWIMAGE.paste(current, (x, y))
    elif TOOL == 'highlighter':
        current = DRAWIMAGE.crop((x, y, x + regionwidth, y + regionheight))
        layer = imagemodule.new('RGBA', (regionwidth, regionheight), (0, 0, 0, 0))
        painter = drawmodule.Draw(layer)
        painter.line((localfirst, localsecond), fill=(242, 214, 75, 105), width=width)
        current = imagemodule.alpha_composite(current, layer)
        DRAWIMAGE.paste(current, (x, y))
    else:
        painter = drawmodule.Draw(DRAWIMAGE)
        painter.line((first, second), fill=(232, 64, 64, 255), width=width)

    if not DIAGNOSTICMODE:
        updatepreviewregion(dirty)
    return True


def defaultfolder():

    try:
        with open(SESSIONIDENTITYFILE, 'rb') as stream:
            raw = stream.read(SESSIONIDENTITYMAXBYTES + 1)
    except OSError as error:
        raise RuntimeError(
            'the active session identity is unavailable') from error
    if len(raw) > SESSIONIDENTITYMAXBYTES:
        raise RuntimeError('the active session identity is too large')
    try:
        identity = json.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, ValueError) as error:
        raise RuntimeError('the active session identity is invalid') from error
    if (
        not isinstance(identity, dict) or
        set(identity) != {'format', 'username'} or
        type(identity.get('format')) is not int or
        identity.get('format') != 1
    ):
        raise RuntimeError('the active session identity is invalid')
    username = identity.get('username')
    if not isinstance(username, str) or not SESSIONUSERNAME.fullmatch(username):
        raise RuntimeError('the active session username is invalid')
    return f'/master/{username}/flash/images'


def startsave():

    global PICKERPENDING

    if not hascapture() or PICKERPENDING is not None:
        return

    if PICKERVERSION < 1:
        try:
            folder = defaultfolder()
            os.makedirs(folder, exist_ok=True)
            path = saveimage(DRAWIMAGE, uniqueimagepath(folder))
            setstatus(f'saved {path}')
        except Exception as error:
            setstatus(f'save failed: {error}', error=True)
        return

    suggested = os.path.basename(uniqueimagepath('/.ephemeral/snap'))
    PICKERPENDING = {'request_id': None}
    sendws({
        'op': 'CREATE_PICKER',
        'parent': int(MAINID),
        'mode': 'save_as',
        'title': 'save snap as',
        'initial_path': defaultfolder(),
        'suggested_name': suggested,
        'default_extension': '.png',
        'allow_multiple': False,
        'filters': [
            {'id': 'png', 'label': 'PNG image', 'extensions': ['.png']},
            {'id': 'jpeg', 'label': 'JPEG image', 'extensions': ['.jpg', '.jpeg']},
            {'id': 'gif', 'label': 'GIF image', 'extensions': ['.gif']},
        ],
    })
    setstatus('opening Array')


def pickerresult(message):

    global PICKERPENDING

    if PICKERPENDING is None:
        return

    expected = PICKERPENDING.get('request_id')
    requestid = str(message.get('request_id', ''))
    if expected and requestid != str(expected):
        return

    PICKERPENDING = None
    paths = message.get('paths', [])

    if str(message.get('status', 'cancelled')) != 'accepted' or not isinstance(paths, list) or not paths:
        setstatus('save cancelled')
        return

    try:
        path = saveimage(DRAWIMAGE, paths[0])
        setstatus(f'saved {path}')
    except Exception as error:
        setstatus(f'save failed: {error}', error=True)


def action(name):

    global MODE, DELAYINDEX, TOOL

    if name == 'new':
        beginnew()
    elif name == 'save':
        startsave()
    elif name == 'copy':
        copycapture()
    elif name == 'delay':
        DELAYINDEX = (DELAYINDEX + 1) % len(DELAYS)
        setstatus(f'delay set to {DELAYS[DELAYINDEX]} seconds')
    elif name.startswith('mode:'):
        MODE = name.split(':', 1)[1]
        setstatus(f'{currentmode()} snap selected')
    elif name.startswith('tool:'):
        selected = name.split(':', 1)[1]
        TOOL = None if TOOL == selected else selected
        setstatus('annotation tool off' if TOOL is None else f'{TOOL} selected')


def mainmotion(message):

    global HOVER, LASTIMAGEPOINT
    x = int(message.get('x', 0))
    y = int(message.get('y', 0))

    if STROKING and TOOL:
        point = previewtoimage(x, y)
        if point is not None and LASTIMAGEPOINT is not None:
            annotatesegment(LASTIMAGEPOINT, point)
            LASTIMAGEPOINT = point
        return

    button = buttonat(x, y)
    hover = button['action'] if button and button['enabled'] else None
    if hover != HOVER:
        HOVER = hover
        cursor(MAINID, 'link' if HOVER else 'arrow')
        redraw()


def mainbutton(message):

    global STROKING, LASTIMAGEPOINT

    if int(message.get('button', 1)) != 1:
        return

    state = str(message.get('state', 'down')).lower()
    x = int(message.get('x', 0))
    y = int(message.get('y', 0))

    if state == 'down':
        button = buttonat(x, y)
        if button and button['enabled']:
            action(button['action'])
            return

        point = previewtoimage(x, y)
        if point is not None and TOOL:
            STROKING = True
            LASTIMAGEPOINT = point
            annotatesegment(point, point)
        return

    if state == 'up':
        STROKING = False
        LASTIMAGEPOINT = None


def keyinput(message):

    if str(message.get('state', 'down')).lower() not in ('down', 'repeat'):
        return

    key = str(message.get('key', '')).upper()
    mods = message.get('mods', {}) if isinstance(message.get('mods', {}), dict) else {}
    control = bool(mods.get('ctrl') or mods.get('control'))

    if key in ('ESC', 'ESCAPE') and CAPTURESTATE != 'idle':
        cancelcapture()
    elif control and key == 'N':
        beginnew()
    elif control and key == 'S':
        startsave()
    elif control and key == 'C':
        copycapture()
    elif key == 'M' and bool(mods.get('alt')):
        values = [value for value, _label in MODES]
        action(f'mode:{values[(values.index(MODE) + 1) % len(values)]}')
    elif key == 'D' and bool(mods.get('alt')):
        action('delay')


def redraw():

    if MAINID and CAPTURESTATE == 'idle' and not OVERLAYMAPPED:
        paintmain()


def handlecapture(message):

    global CAPTUREPATH, CAPTUREWINDOWS, SCREENW, SCREENH, CAPTURESTATE
    global SELECTCURRENT, OVERLAYPOINTER, OVERLAYREADY
    global OVERLAYLASTRECT, OVERLAYLASTPOINTER, OVERLAYLASTCANCEL

    if str(message.get('request_id', '')) != CAPTUREREQUEST:
        return

    try:
        CAPTUREPATH = str(message.get('path', ''))
        SCREENW = int(message.get('width', SCREENW))
        SCREENH = int(message.get('height', SCREENH))
        CAPTUREWINDOWS = list(message.get('windows', []))

        if not os.path.isfile(CAPTUREPATH):
            raise FileNotFoundError('windowserver did not return a capture file')

        if MODE == 'full_screen':
            finishcapture([0, 0, SCREENW, SCREENH])
            return

        preparecapturesurfaces()
        resetselection()
        CAPTURESTATE = 'selecting'
        SELECTCURRENT = (0, 0)
        OVERLAYPOINTER = (SCREENW // 2, SCREENH // 2)
        OVERLAYREADY = False
        OVERLAYLASTRECT = None
        OVERLAYLASTPOINTER = None
        OVERLAYLASTCANCEL = False
        showoverlay()
    except Exception as error:
        log(f'capture response error {error}')
        cancelcapture(f'capture failed: {error}')


def resized(message):

    global WINW, WINH, MAINBUF, OVERLAYW, OVERLAYH, OVERLAYBUF, PREVIEWDIRTY
    global OVERLAYREADY
    winid = int(message.get('winid', 0))

    if winid == MAINID:
        WINW = max(1, int(message.get('w', WINW)))
        WINH = max(1, int(message.get('h', WINH)))
        MAINBUF = str(message.get('buffer', MAINBUF))
        PREVIEWDIRTY = True
        paintmain()
    elif winid == OVERLAYID:
        OVERLAYW = max(1, int(message.get('w', OVERLAYW)))
        OVERLAYH = max(1, int(message.get('h', OVERLAYH)))
        OVERLAYBUF = str(message.get('buffer', OVERLAYBUF))
        OVERLAYREADY = False
        showoverlay()


def handlews(message):

    global MAINID, MAINBUF, WINW, WINH, OVERLAYID, OVERLAYBUF
    global OVERLAYW, OVERLAYH, OVERLAYMAPPED, SCREENW, SCREENH
    global NEEDMAIN, RUNNING, FOCUSED, PICKERVERSION, PICKERPENDING
    global CAPTURESTATE, CAPTUREAT

    operation = str(message.get('op', ''))

    if operation == 'WELCOME':
        framebuffer = message.get('fb', {})
        SCREENW = int(framebuffer.get('w', SCREENW))
        SCREENH = int(framebuffer.get('h', SCREENH))
        PICKERVERSION = int(message.get('pickers', {}).get('version', 0))
        applyscale()
        if NEEDMAIN:
            NEEDMAIN = False
            createmain()
        return

    if operation == 'FB_SIZE':
        SCREENW = int(message.get('w', SCREENW))
        SCREENH = int(message.get('h', SCREENH))
        applyscale()
        return

    if operation == 'WINDOW_CREATED':
        role = str(message.get('role', ''))
        if role == 'snap_overlay':
            OVERLAYID = int(message.get('winid'))
            OVERLAYBUF = str(message.get('buffer'))
            OVERLAYW = int(message.get('w', SCREENW))
            OVERLAYH = int(message.get('h', SCREENH))
            initttffont(FONT, FONTSIZE)
            initttffont(FONT, SMALLFONT)
            showoverlay()
        else:
            MAINID = int(message.get('winid'))
            MAINBUF = str(message.get('buffer'))
            WINW = int(message.get('w', WINW))
            WINH = int(message.get('h', WINH))
            initttffont(FONT, FONTSIZE)
            initttffont(FONT, SMALLFONT)
            paintmain()
        return

    if operation == 'WINDOW_MAPPED':
        if int(message.get('winid', 0)) == OVERLAYID:
            OVERLAYMAPPED = True
        return

    if operation == 'WINDOW_UNMAPPED':
        winid = int(message.get('winid', 0))
        if winid == MAINID and CAPTURESTATE == 'waiting_unmap':
            CAPTURESTATE = 'countdown'
            CAPTUREAT = time.monotonic() + float(DELAYS[DELAYINDEX]) + 0.12
        elif winid == OVERLAYID:
            OVERLAYMAPPED = False
            mapmain()
        return

    if operation == 'RESIZED':
        resized(message)
        return

    if operation == 'SCREEN_CAPTURED':
        handlecapture(message)
        return

    if operation == 'SCREEN_CAPTURE_FAILED':
        if str(message.get('request_id', '')) == CAPTUREREQUEST:
            CAPTURESTATE = 'idle'
            setstatus(str(message.get('detail', 'capture failed')), error=True)
            mapmain()
        return

    if operation == 'PICKER_CREATED':
        if PICKERPENDING is not None:
            PICKERPENDING['request_id'] = str(message.get('request_id', ''))
        return

    if operation == 'PICKER_RESULT':
        pickerresult(message)
        return

    if operation == 'FOCUS':
        FOCUSED = bool(message.get('focused', message.get('value', True)))
        return

    if operation == 'CLOSE':
        RUNNING = False
        sendws({'op': 'CLOSE_ACK', 'pid': os.getpid()})
        return

    if operation == 'ERROR':
        log(f"windowserver error code={message.get('code')} detail={message.get('detail')}")


def diagnostic():

    global BASEIMAGE, DRAWIMAGE, TOOL, MODE, DELAYINDEX, WINW, WINH

    result = {'version': VERSION, 'passed': False, 'checks': {}, 'errors': []}

    try:
        if [value for value, _label in MODES] != ['rectangular', 'window', 'full_screen']:
            raise RuntimeError('snap modes are incomplete')
        if DELAYS != (0, 1, 3, 5):
            raise RuntimeError('Snap delay choices are incomplete')
        result['checks']['capture_modes'] = len(MODES)
        result['checks']['delays'] = list(DELAYS)

        if rectfrompoints((80, 60), (20, 10)) != [20, 10, 61, 51]:
            raise RuntimeError('reverse rectangle selection is incorrect')
        if cliprect([-10, -20, 50, 70], 100, 80) != [0, 0, 40, 50]:
            raise RuntimeError('screen-bound selection clipping is incorrect')
        result['checks']['selection_geometry'] = True

        previous = [100, 100, 1200, 700]
        current = [100, 100, 1208, 706]
        damage = (
            subtractrect(previous, current)
            + subtractrect(current, previous)
            + borderrects(previous)
            + borderrects(current)
        )
        damagepixels = sum(rect[2] * rect[3] for rect in damage)
        screenpixels = 3840 * 2160
        if damagepixels >= screenpixels // 50:
            raise RuntimeError('selection updates are repainting too much of the screen')
        result['checks']['incremental_selection_damage_pixels'] = damagepixels

        imagemodule, _drawmodule = loadpillow()
        source = imagemodule.new('RGBA', (100, 80), (20, 40, 60, 255))
        rectangular = cropselection(source, [10, 15, 50, 30])
        if rectangular.size != (50, 30):
            raise RuntimeError('rectangular snap produced the wrong size')
        result['checks']['capture_cropping'] = ['rectangular']

        BASEIMAGE = imagemodule.new('RGBA', (120, 80), (20, 40, 60, 255))
        DRAWIMAGE = BASEIMAGE.copy()
        TOOL = 'pen'
        before = DRAWIMAGE.getpixel((20, 20))
        annotatesegment((10, 10), (30, 30))
        after = DRAWIMAGE.getpixel((20, 20))
        if before == after:
            raise RuntimeError('pen annotation did not alter the capture')
        TOOL = 'eraser'
        annotatesegment((10, 10), (30, 30))
        if DRAWIMAGE.getpixel((20, 20)) != BASEIMAGE.getpixel((20, 20)):
            raise RuntimeError('eraser did not restore the captured pixels')
        result['checks']['annotation_tools'] = ['pen', 'highlighter', 'eraser']

        WINW = BASEWINW
        WINH = BASEWINH
        MODE = 'rectangular'
        DELAYINDEX = 0
        controlset = buttons()
        actions = {control['action'] for control in controlset}
        expected = {
            'new', 'save', 'copy', 'tool:pen', 'tool:highlighter', 'tool:eraser',
            'mode:rectangular', 'mode:window', 'mode:full_screen', 'delay',
        }
        if not expected.issubset(actions):
            raise RuntimeError('Snap toolbar controls are incomplete')
        result['checks']['toolbar_controls'] = len(controlset)
        result['checks']['t1os_palette'] = (
            COLOURBG, COLOURTEXT, COLOURSTATUS, COLOURDIVIDER, COLOURMUTED
        ) == (0x000000, 0xEFEFEF, 0x242424, 0x3A3A3A, 0x6A6A6A)
        if not result['checks']['t1os_palette']:
            raise RuntimeError('Snap palette does not match t1os')
        result['passed'] = True
    except Exception as error:
        result['errors'].append(str(error))

    print(json.dumps(result, sort_keys=True, separators=(',', ':')))
    return 0 if result['passed'] else 1


def cleanup():

    closecapturesurfaces()
    try:
        if WSOCK is not None:
            WSOCK.close()
    except Exception:
        pass
    try:
        shutil.rmtree(SNAPROOT, ignore_errors=True)
    except Exception:
        pass


def terminate(signum, frame):

    global RUNNING
    RUNNING = False


def initapp():

    connectws()
    sendws({'op': 'HELLO'})
    sendws({'op': 'SUBSCRIBE', 'types': ['fbsize']})

    while RUNNING and MAINID is None:
        for key, mask in SEL.select(timeout=0.1):
            if key.fileobj is WSOCK and mask & selectors.EVENT_READ:
                for message in recvws():
                    handlews(message)
            if key.fileobj is WSOCK and mask & selectors.EVENT_WRITE:
                flushws()
        flushws()

    mapmain()
    flushws()


def pulse():

    global RUNNING, OVERLAYPAINTPENDING

    for key, mask in SEL.select(timeout=0.025):
        if key.fileobj is not WSOCK:
            continue

        if mask & selectors.EVENT_READ:
            try:
                messages = recvws()
            except Exception as error:
                log(f'windowserver receive error {error}')
                RUNNING = False
                return

            for message in messages:
                handlews(message)
                operation = str(message.get('op', ''))
                winid = int(message.get('winid', 0)) if str(message.get('winid', '')).lstrip('-').isdigit() else 0

                if operation == 'KEY':
                    keyinput(message)
                elif operation == 'POINTER_MOTION':
                    overlaymotion(message) if winid == OVERLAYID else mainmotion(message)
                elif operation == 'POINTER_BUTTON':
                    overlaybutton(message) if winid == OVERLAYID else mainbutton(message)

        if mask & selectors.EVENT_WRITE:
            flushws()

    if CAPTURESTATE == 'countdown' and CAPTUREAT and time.monotonic() >= CAPTUREAT:
        requestcapture()

    if (
        OVERLAYPAINTPENDING
        and CAPTURESTATE == 'selecting'
        and time.monotonic() - OVERLAYLASTPAINT >= OVERLAYFRAMEINTERVAL
    ):
        paintoverlay()

    flushws()


def main():

    atexit.register(cleanup)
    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)
    makedirs()
    loadpillow()
    initapp()

    while RUNNING:
        pulse()

    flushws()
    return 0


if __name__ == '__main__':

    if DIAGNOSTICMODE:
        raise SystemExit(diagnostic())

    raise SystemExit(main())
