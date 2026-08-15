#!"/the one/software/python/bin/python" -B

"""
viewer.py

viewer is the image viewer and shared image surface API of The One OS.
"""



# imports
import os
import sys
import time
import math
import json
import shutil
import socket
import signal
import atexit
import warnings
import selectors
import subprocess

sys.path.insert(0, '/the one/build')

import graphics.graphics as gfx
from graphics.graphics import initbuffer, fillrectfast, blitfilepartfast, drawtextttf
from graphics.graphics import initttffont, present as gfxpresent
from graphics.graphics import managedstate, managedconfigure, manageddisable, managedclear
from graphics.graphics import managedmarkdamage, managedtick, managedsubmit, managedresponse, uiscalefactor



# globals

# paths
VIEWERPATH = '/the one/build/viewer/viewer.py'
CATALOGUE = '/the one/catalogue/image'
EPHEMERAL = '/.ephemeral'
VIEWROOT = f'/.ephemeral/viewer/{os.getpid()}'
WINDOWSOCK = '/.ephemeral/windowserver/accept.sock'
FONT = '/the one/resources/fonts/atkinsonhyperlegiblenext.ttf'

# image limits
VERSION = 1
PIXELLIMIT = 16777216
SOURCELIMIT = 40000000
FORMATS = {
    'BMP',
    'DDS',
    'GIF',
    'ICO',
    'JPEG',
    'PCX',
    'PNG',
    'PPM',
    'QOI',
    'TGA',
    'TIFF',
    'WEBP',
}
EXTENSIONS = {
    '.bmp',
    '.dds',
    '.dib',
    '.gif',
    '.icb',
    '.ico',
    '.jfif',
    '.jpe',
    '.jpeg',
    '.jpg',
    '.pbm',
    '.pcx',
    '.pgm',
    '.png',
    '.pnm',
    '.ppm',
    '.qoi',
    '.tga',
    '.tif',
    '.tiff',
    '.vda',
    '.vst',
    '.webp',
}

# Pillow modules
PILIMAGE = None
PILOPS = None
PILERROR = None

# application state
RUNNING = True
SOURCE = None
IMAGE = {}
ERROR = ''
LOADING = False
MODE = 'fit'
ZOOM = 1.0
PANX = 0
PANY = 0
DRAGGING = False
DRAGX = 0
DRAGY = 0
DRAGPANX = 0
DRAGPANY = 0
FOCUSED = True

# window state
APPNAME = 'viewer'
APPROLE = 'window'
BASEWINW = 960
BASEWINH = 640
WINID = None
BUF = None
WINW = BASEWINW
WINH = BASEWINH
SCREENW = 0
SCREENH = 0
UISCALE = 1.0
NEEDWINDOW = True
WSOCK = None
INBUF = b''
OUTBUF = bytearray()
SEL = selectors.DefaultSelector()

# layout
BASETOOLBARH = 38
BASESTATUSH = 26
BASEPAD = 8
BASEFONTSIZE = 14
TOOLBARH = BASETOOLBARH
STATUSH = BASESTATUSH
PAD = BASEPAD
FONTSIZE = BASEFONTSIZE

# colours
COLOURBG = 0x000000
COLOURTEXT = 0xEFEFEF
COLOURERROR = 0xFF0000

# managed graphics
GRAPHICSCPUOVERRIDE = str(os.environ.get('T1OS_VIEWER_GRAPHICS', '')).strip().lower() in ('cpu', 'off', '0', 'false')
GRAPHICSSTATE = managedstate(cpu=GRAPHICSCPUOVERRIDE)
GRAPHICSSCENE = []
REDRAW = True

# worker state
WORKER = None
WORKEROUTPUT = ''
WORKERGEN = 0
REQUESTGEN = 0
FINISHEDGEN = 0
REQUESTAT = 0.0
REQUESTDELAY = 0.12
SURFACENEXT = 0



# log functions
def log(message):

    # Persistent viewer logging is intentionally disabled.
    return



# shared image functions
def catalogue():

    global PILIMAGE, PILOPS, PILERROR

    if PILIMAGE is not None and PILOPS is not None and PILERROR is not None:
        return PILIMAGE, PILOPS, PILERROR

    if CATALOGUE not in sys.path:
        sys.path.insert(0, CATALOGUE)

    try:

        from PIL import Image as loadedimage
        from PIL import ImageOps as loadedops
        from PIL import UnidentifiedImageError as loadederror

    except Exception as error:
        raise RuntimeError(f'image catalogue unavailable: {error}')

    PILIMAGE = loadedimage
    PILOPS = loadedops
    PILERROR = loadederror
    return PILIMAGE, PILOPS, PILERROR


def supports(path):

    try:
        return os.path.splitext(str(path).lower())[1] in EXTENSIONS

    except Exception:
        return False


def within(path, parent):

    try:

        target = os.path.abspath(path)
        root = os.path.abspath(parent)
        return os.path.commonpath((target, root)) == root

    except Exception:
        return False


def validatesource(source):

    source = os.path.abspath(os.path.normpath(str(source)))

    if not os.path.isfile(source):
        raise ValueError('source is not a readable image file')

    if os.path.islink(source):
        raise ValueError('symbolic links are not accepted as image sources')

    if not os.access(source, os.R_OK):
        raise PermissionError('permission denied reading the image source')

    return source


def validateoutput(source, output):

    output = os.path.abspath(os.path.normpath(str(output)))

    if source == output:
        raise ValueError('source and output paths must be different')

    if not within(output, EPHEMERAL):
        raise ValueError('decoded images must be written below /.ephemeral')

    parent = os.path.dirname(output)

    if not os.path.isdir(parent) or os.path.islink(parent):
        raise ValueError('decoded image directory is unavailable')

    if not within(os.path.realpath(parent), os.path.realpath(EPHEMERAL)):
        raise ValueError('decoded image directory is outside /.ephemeral')

    if os.path.lexists(output) and os.path.islink(output):
        raise ValueError('decoded image output cannot be a symbolic link')

    return output


def inspect(source):

    imagemodule, _, _ = catalogue()
    source = validatesource(source)
    imagemodule.MAX_IMAGE_PIXELS = SOURCELIMIT

    with warnings.catch_warnings():

        warnings.simplefilter('error', imagemodule.DecompressionBombWarning)

        with imagemodule.open(source) as image:

            form = str(image.format or '').upper()
            size = tuple(image.size)
            animated = bool(getattr(image, 'is_animated', False))

            try:
                orientation = int(image.getexif().get(274, 1))

            except Exception:
                orientation = 1

            if form not in FORMATS:
                raise ValueError(f'unsupported image format {form or "unknown"}')

            if size[0] <= 0 or size[1] <= 0:
                raise ValueError('image has invalid dimensions')

            if size[0] * size[1] > SOURCELIMIT:
                raise ValueError(f'image exceeds the {SOURCELIMIT} source pixel limit')


        with imagemodule.open(source) as verified:
            verified.verify()

    if orientation in (5, 6, 7, 8):
        size = (size[1], size[0])

    return form, size, animated


def fit(size, bounds, alignment=1):

    sourcewidth = int(size[0])
    sourceheight = int(size[1])
    maximumwidth = int(bounds[0])
    maximumheight = int(bounds[1])
    alignment = max(1, int(alignment))

    if sourcewidth < 1 or sourceheight < 1:
        raise ValueError('image has invalid dimensions')

    if maximumwidth < 1 or maximumheight < 1:
        raise ValueError('image surface dimensions must be positive')

    scale = min(maximumwidth / float(sourcewidth), maximumheight / float(sourceheight))
    contentwidth = max(1, min(maximumwidth, int(round(sourcewidth * scale))))
    contentheight = max(1, min(maximumheight, int(round(sourceheight * scale))))
    surfacewidth = contentwidth
    surfaceheight = int(math.ceil(contentheight / float(alignment))) * alignment
    surfaceheight = max(contentheight, min(maximumheight, surfaceheight))
    contentx = max(0, (surfacewidth - contentwidth) // 2)
    contenty = max(0, (surfaceheight - contentheight) // 2)

    if surfacewidth * surfaceheight > PIXELLIMIT:
        raise ValueError(f'image surface exceeds the {PIXELLIMIT} pixel limit')

    return [surfacewidth, surfaceheight], [contentx, contenty, contentwidth, contentheight]


def convert(source, width, height):

    imagemodule, opsmodule, _ = catalogue()
    imagemodule.MAX_IMAGE_PIXELS = SOURCELIMIT

    with warnings.catch_warnings():

        warnings.simplefilter('error', imagemodule.DecompressionBombWarning)

        with imagemodule.open(source) as opened:

            opened.seek(0)
            image = opsmodule.exif_transpose(opened)
            image = opsmodule.contain(image, (width, height), imagemodule.Resampling.LANCZOS)
            image = image.convert('RGBA')
            canvas = imagemodule.new('RGBA', (width, height), (0, 0, 0, 255))
            x = (width - image.width) // 2
            y = (height - image.height) // 2
            canvas.alpha_composite(image, (x, y))
            pixels = canvas.tobytes('raw', 'BGRA')

    expected = width * height * 4

    if len(pixels) != expected:
        raise RuntimeError(f'decoder returned {len(pixels)} bytes, expected {expected}')

    return pixels


def store(output, pixels):

    temporary = f'{output}.tmp-{os.getpid()}'

    try:

        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)

        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(pixels)
            stream.flush()
            os.fsync(stream.fileno())

        os.replace(temporary, output)
        os.chmod(output, 0o600)

    finally:

        if os.path.exists(temporary):
            os.unlink(temporary)


def render(source, output, maximumwidth, maximumheight, alignment=1):

    source = validatesource(source)
    output = validateoutput(source, output)
    maximumwidth = int(maximumwidth)
    maximumheight = int(maximumheight)
    alignment = max(1, int(alignment))

    if maximumwidth < 1 or maximumheight < 1:
        raise ValueError('image surface dimensions must be positive')

    form, size, animated = inspect(source)
    surfacesize, contentrect = fit(size, (maximumwidth, maximumheight), alignment)
    width, height = surfacesize
    pixels = convert(source, width, height)
    store(output, pixels)

    return {
        'version': VERSION,
        'ok': True,
        'source': source,
        'output': output,
        'format': form,
        'source_size': list(size),
        'surface_size': [width, height],
        'content_rect': contentrect,
        'pixel_format': 'BGRA32',
        'animated': animated,
        'frame': 0,
    }


def command(source, output, maximumwidth, maximumheight, alignment=1):

    return [
        sys.executable,
        '-B',
        VIEWERPATH,
        '--render',
        str(source),
        str(output),
        str(int(maximumwidth)),
        str(int(maximumheight)),
        str(max(1, int(alignment))),
    ]


def parse(returncode, stdout, stderr, output):

    lines = [line.strip() for line in str(stdout).splitlines() if line.strip()]

    try:
        payload = json.loads(lines[-1]) if lines else {}

    except Exception as error:
        raise ValueError(f'image worker returned invalid JSON: {error}')

    if int(returncode) != 0 or not payload.get('ok'):

        message = payload.get('error') or str(stderr).strip() or f'image worker exited {returncode}'
        raise ValueError(str(message)[:512])

    if int(payload.get('version', 0)) != VERSION:
        raise ValueError('image worker returned an unsupported response version')

    if str(payload.get('pixel_format', '')).upper() != 'BGRA32':
        raise ValueError('image worker returned an unsupported pixel format')

    size = list(payload.get('surface_size', []))

    if len(size) != 2 or int(size[0]) < 1 or int(size[1]) < 1:
        raise ValueError('image worker returned invalid surface dimensions')

    expected = int(size[0]) * int(size[1]) * 4

    if not os.path.isfile(output) or os.path.getsize(output) != expected:
        raise ValueError('decoded image surface has the wrong size')

    if os.path.abspath(str(payload.get('output', ''))) != os.path.abspath(output):
        raise ValueError('image worker returned the wrong output path')

    return payload


def request(source, output, maximumwidth, maximumheight, alignment=1, timeout=30):

    completed = subprocess.run(
        command(source, output, maximumwidth, maximumheight, alignment),
        input='',
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
        check=False,
    )

    return parse(completed.returncode, completed.stdout, completed.stderr, output)


def emit(payload):

    print(json.dumps(payload, sort_keys=True, separators=(',', ':')))


def rendercommand(args):

    if len(args) != 5:

        emit({
            'version': VERSION,
            'ok': False,
            'error': 'usage: viewer.py --render <source> <output> <maximum width> <maximum height> <alignment>',
        })
        return 2

    source, output, widthtext, heighttext, alignmenttext = args

    try:

        payload = render(source, output, int(widthtext), int(heighttext), int(alignmenttext))
        emit(payload)
        return 0

    except Exception as error:

        emit({
            'version': VERSION,
            'ok': False,
            'error': str(error),
        })
        return 4



# shared diagnostic functions
def fixture(path, form, size, colour):

    imagemodule, _, _ = catalogue()
    image = imagemodule.new('RGBA', size, colour)

    if form == 'JPEG':
        image = image.convert('RGB')

    image.save(path, format=form)


def diagnostic():

    result = {
        'version': VERSION,
        'passed': False,
        'checks': {},
        'errors': [],
    }
    root = f'{EPHEMERAL}/viewer-diagnostic-{os.getpid()}'

    try:

        os.makedirs(root, mode=0o700, exist_ok=False)
        png = os.path.join(root, 'wide image.png')
        jpeg = os.path.join(root, 'portrait.jpg')
        oriented = os.path.join(root, 'oriented.jpg')
        corrupt = os.path.join(root, 'corrupt.png')
        text = os.path.join(root, 'words.txt')
        output = os.path.join(root, 'decoded.bgra')
        fixture(png, 'PNG', (8, 4), (220, 30, 40, 128))
        fixture(jpeg, 'JPEG', (3, 7), (20, 160, 60, 255))
        imagemodule, _, _ = catalogue()
        orientedimage = imagemodule.new('RGB', (6, 3), (30, 80, 210))
        exif = imagemodule.Exif()
        exif[274] = 6
        orientedimage.save(oriented, format='JPEG', exif=exif)

        with open(corrupt, 'wb') as stream:
            stream.write(b'\x89PNG\r\n\x1a\ncorrupt')

        with open(text, 'w', encoding='utf-8') as stream:
            stream.write('not an image')

        pngresult = render(png, output, 16, 12, 4)

        if pngresult.get('surface_size') != [16, 8]:
            raise RuntimeError(f'PNG fit returned {pngresult.get("surface_size")} instead of [16, 8]')

        if os.path.getsize(output) != 16 * 8 * 4:
            raise RuntimeError('PNG output has the wrong byte count')

        result['checks']['png'] = {
            'format': pngresult.get('format'),
            'surface': pngresult.get('surface_size'),
            'content': pngresult.get('content_rect'),
        }

        jpegresult = render(jpeg, output, 16, 12, 4)

        if jpegresult.get('surface_size', [0, 0])[1] % 4 != 0:
            raise RuntimeError('JPEG surface was not aligned')

        result['checks']['jpeg'] = {
            'format': jpegresult.get('format'),
            'surface': jpegresult.get('surface_size'),
            'content': jpegresult.get('content_rect'),
        }

        orientedresult = render(oriented, output, 12, 12, 1)

        if orientedresult.get('source_size') != [3, 6] or orientedresult.get('surface_size') != [6, 12]:
            raise RuntimeError('EXIF orientation was not applied before fitting')

        result['checks']['orientation'] = {
            'source': orientedresult.get('source_size'),
            'surface': orientedresult.get('surface_size'),
        }

        with open(output, 'rb') as stream:
            pixels = stream.read()

        if len(pixels) != os.path.getsize(output):
            raise RuntimeError('BGRA surface could not be read completely')

        result['checks']['bgra_surface'] = True
        rejected = []

        for candidate in (corrupt, text):

            try:
                inspect(candidate)

            except Exception:
                rejected.append(os.path.basename(candidate))

        if len(rejected) != 2:
            raise RuntimeError('invalid image inputs were not rejected')

        outside = os.path.join(os.path.dirname(EPHEMERAL), f'viewer-outside-{os.getpid()}.bgra')

        try:
            render(png, outside, 4, 4, 1)

        except Exception:
            result['checks']['outside_rejected'] = True

        if not result['checks'].get('outside_rejected'):
            raise RuntimeError('output outside /.ephemeral was not rejected')

        if not supports('picture.JPEG') or supports('notes.txt'):
            raise RuntimeError('image extension association is invalid')

        result['checks']['invalid_rejected'] = rejected
        result['checks']['extensions'] = True
        result['checks']['catalogue'] = catalogue()[0].__version__
        result['passed'] = True

    except Exception as error:
        result['errors'].append(str(error))

    finally:
        shutil.rmtree(root, ignore_errors=True)

    emit(result)
    return 0 if result['passed'] else 1



# layout functions
def scale(value):

    try:
        return max(1, int(round(float(value) * float(UISCALE))))

    except Exception:
        return max(1, int(value))


def applyscale():

    global UISCALE, TOOLBARH, STATUSH, PAD, FONTSIZE

    if SCREENW > 0 and SCREENH > 0:
        automatic = max(0.75, min(2.0, min(SCREENW / 1920.0, SCREENH / 1080.0)))
        UISCALE = automatic * uiscalefactor()

    TOOLBARH = scale(BASETOOLBARH)
    STATUSH = scale(BASESTATUSH)
    PAD = scale(BASEPAD)
    FONTSIZE = scale(BASEFONTSIZE)


def viewport():

    x = PAD
    y = TOOLBARH + PAD
    width = max(1, int(WINW) - (PAD * 2))
    height = max(1, int(WINH) - TOOLBARH - STATUSH - (PAD * 2))
    return [x, y, width, height]


def buttons():

    height = max(22, TOOLBARH - (PAD * 2))
    y = max(0, (TOOLBARH - height) // 2)
    x = PAD
    values = []

    for name, label, width in (
        ('minus', '-', 30),
        ('plus', '+', 30),
        ('actual', '100%', 58),
        ('fit', 'fit', 44),
    ):

        buttonwidth = scale(width)
        values.append({
            'name': name,
            'label': label,
            'rect': [x, y, buttonwidth, height],
        })
        x += buttonwidth + scale(6)

    return values


def clamp(value, minimum, maximum):

    return max(minimum, min(maximum, value))


def clamppan():

    global PANX, PANY

    if not IMAGE:

        PANX = 0
        PANY = 0
        return

    _, _, viewwidth, viewheight = viewport()
    size = IMAGE.get('surface_size', [0, 0])
    width = int(size[0])
    height = int(size[1])

    if width <= viewwidth:
        PANX = 0

    else:
        PANX = clamp(int(PANX), viewwidth - width, 0)

    if height <= viewheight:
        PANY = 0

    else:
        PANY = clamp(int(PANY), viewheight - height, 0)


def placement():

    viewx, viewy, viewwidth, viewheight = viewport()

    if not IMAGE:
        return [viewx, viewy, 0, 0]

    size = IMAGE.get('surface_size', [0, 0])
    width = int(size[0])
    height = int(size[1])
    clamppan()

    if width <= viewwidth:
        x = viewx + ((viewwidth - width) // 2)

    else:
        x = viewx + int(PANX)

    if height <= viewheight:
        y = viewy + ((viewheight - height) // 2)

    else:
        y = viewy + int(PANY)

    return [x, y, width, height]


def zoomtext():

    if not IMAGE:
        return ''

    source = IMAGE.get('source_size', [0, 0])
    content = IMAGE.get('content_rect', [0, 0, 0, 0])

    try:

        percent = int(round((int(content[2]) / float(int(source[0]))) * 100.0))
        return f'{percent}%'

    except Exception:
        return ''


def statustext():

    if ERROR:
        return ERROR

    if LOADING:
        return 'loading image'

    if not IMAGE:
        return 'open an image from Array or run viewer with an image path'

    size = IMAGE.get('source_size', [0, 0])
    form = IMAGE.get('format', 'image')
    animated = ' animated first frame' if IMAGE.get('animated') else ''
    name = os.path.basename(str(IMAGE.get('source', SOURCE or 'image')))
    return f'{name}  {size[0]}x{size[1]}  {form}{animated}  {zoomtext()}'



# worker functions
def makedir():

    os.makedirs(VIEWROOT, mode=0o700, exist_ok=True)

    if os.path.islink(VIEWROOT):
        raise ValueError('image surface directory cannot be a symbolic link')

    os.chmod(VIEWROOT, 0o700)


def bounds():

    _, _, viewwidth, viewheight = viewport()

    if MODE == 'fit' or not IMAGE:
        return max(1, viewwidth), max(1, viewheight)

    source = IMAGE.get('source_size', [viewwidth, viewheight])
    sourcewidth = max(1, int(source[0]))
    sourceheight = max(1, int(source[1]))
    maximumzoom = math.sqrt(PIXELLIMIT / float(sourcewidth * sourceheight))
    usedzoom = max(0.05, min(float(ZOOM), maximumzoom))
    return max(1, int(round(sourcewidth * usedzoom))), max(1, int(round(sourceheight * usedzoom)))


def queue(delay=True):

    global REQUESTGEN, REQUESTAT, LOADING, ERROR

    if not SOURCE:
        return

    REQUESTGEN += 1
    REQUESTAT = time.monotonic() + (REQUESTDELAY if delay else 0.0)
    LOADING = True
    ERROR = ''
    redraw()


def startworker():

    global WORKER, WORKEROUTPUT, WORKERGEN, SURFACENEXT

    if WORKER is not None or not SOURCE:
        return False

    try:

        makedir()
        SURFACENEXT += 1
        output = os.path.join(VIEWROOT, f'image-{SURFACENEXT}.bgra')
        width, height = bounds()
        WORKER = subprocess.Popen(
            command(SOURCE, output, width, height, 1),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        WORKEROUTPUT = output
        WORKERGEN = REQUESTGEN
        return True

    except Exception as error:

        workererror(error)
        return False


def workererror(error):

    global ERROR, LOADING, WORKER, WORKEROUTPUT, FINISHEDGEN

    ERROR = str(error)[:512]
    LOADING = False
    FINISHEDGEN = max(int(FINISHEDGEN), int(WORKERGEN), int(REQUESTGEN))
    WORKER = None

    if WORKEROUTPUT and os.path.isfile(WORKEROUTPUT):

        try:
            os.unlink(WORKEROUTPUT)

        except Exception:
            pass

    WORKEROUTPUT = ''
    redraw()


def pollworker():

    global WORKER, WORKEROUTPUT, IMAGE, LOADING, ERROR, PANX, PANY, FINISHEDGEN

    if WORKER is None:

        if SOURCE and REQUESTGEN > FINISHEDGEN and time.monotonic() >= REQUESTAT:
            startworker()

        return

    returncode = WORKER.poll()

    if returncode is None:
        return

    process = WORKER
    output = WORKEROUTPUT
    generation = WORKERGEN
    WORKER = None
    WORKEROUTPUT = ''

    try:

        stdout, stderr = process.communicate()
        payload = parse(returncode, stdout, stderr, output)

        if generation != REQUESTGEN:

            FINISHEDGEN = max(int(FINISHEDGEN), int(generation))

            if os.path.isfile(output):
                os.unlink(output)

            return

        previous = str(IMAGE.get('output', '')) if IMAGE else ''
        IMAGE = payload
        ERROR = ''
        LOADING = False
        FINISHEDGEN = max(int(FINISHEDGEN), int(generation))
        PANX = 0
        PANY = 0
        windowcurrent(payload.get('source', SOURCE))

        if previous and previous != output and os.path.isfile(previous):
            os.unlink(previous)

        redraw()

    except Exception as error:
        workererror(error)



# managed graphics functions
def graphicssend(requestdata):

    try:

        sendws(requestdata)
        return True

    except Exception:
        return False


def graphicsconfigure(capabilities):

    return managedconfigure(
        GRAPHICSSTATE,
        capabilities,
        required=('rectangle', 'image', 'text'),
        cpu=GRAPHICSCPUOVERRIDE or not os.path.isfile(FONT),
    )


def graphicsclip(rect):

    try:

        x, y, width, height = [int(value) for value in rect]
        left = max(0, x)
        top = max(0, y)
        right = min(int(WINW), x + width)
        bottom = min(int(WINH), y + height)

        if right <= left or bottom <= top:
            return None

        return [left, top, right - left, bottom - top]

    except Exception:
        return None


def baseline(y, size):

    try:

        face = gfx.getttfface(FONT)

        if face is None:
            return int(y)

        face.set_pixel_sizes(0, int(size))
        ascender = int(face.size.ascender >> 6)
        return int(y) + int(size) - ascender

    except Exception:
        return int(y)


def textnode(x, y, text, colour, clip):

    return {
        'kind': 'text',
        'x': max(0, int(x)),
        'y': max(0, int(baseline(y, FONTSIZE))),
        'text': str(text)[:1024],
        'size': int(FONTSIZE),
        'font': FONT,
        'color': int(colour),
        'clip': list(clip),
    }


def buildscene():

    commands = [{
        'kind': 'rectangle',
        'rect': [0, 0, int(WINW), int(WINH)],
        'color': COLOURBG,
        'clip': [0, 0, int(WINW), int(WINH)],
    }]
    for button in buttons():

        x, y, width, height = button['rect']
        active = (button['name'] == MODE) or (button['name'] == 'actual' and MODE == 'zoom' and abs(ZOOM - 1.0) < 0.001)
        commands.append(textnode(x + scale(8), y + max(0, (height - FONTSIZE) // 2), button['label'], COLOURTEXT, [x, y, width, height]))

        if active:
            commands.append({
                'kind': 'rectangle',
                'rect': [x, y + height - 1, width, 1],
                'color': COLOURTEXT,
                'clip': [0, 0, int(WINW), int(TOOLBARH)],
            })

    viewclip = graphicsclip(viewport())

    if IMAGE and viewclip is not None:

        x, y, width, height = placement()
        surface = IMAGE.get('surface_size', [0, 0])

        if width > 0 and height > 0 and os.path.isfile(str(IMAGE.get('output', ''))):
            commands.append({
                'kind': 'image',
                'path': str(IMAGE.get('output')),
                'source_width': int(surface[0]),
                'source_height': int(surface[1]),
                'format': 'BGRA32',
                'rect': [x, y, width, height],
                'clip': viewclip,
            })

    statuscolour = COLOURERROR if ERROR else COLOURTEXT
    statusy = max(0, int(WINH) - int(STATUSH) + max(0, (int(STATUSH) - int(FONTSIZE)) // 2))
    commands.append(textnode(PAD, statusy, statustext(), statuscolour, [0, max(0, WINH - STATUSH), WINW, STATUSH]))
    return commands


def submitscene():

    global GRAPHICSSCENE

    if not GRAPHICSSTATE.get('available') or not WINID:
        return False

    try:

        commands = buildscene()
        managedmarkdamage(GRAPHICSSTATE, [0, 0, int(WINW), int(WINH)], bounds=(int(WINW), int(WINH)))
        managedsubmit(GRAPHICSSTATE, graphicssend, WINID, commands)

        if GRAPHICSSTATE.get('pending'):
            GRAPHICSSCENE = commands

        return bool(GRAPHICSSTATE.get('available'))

    except Exception as error:

        manageddisable(GRAPHICSSTATE, f'viewer scene failed: {error}')
        log(f'managed graphics disabled {error}')
        return False


def graphicsresponse(message):

    global GRAPHICSSCENE

    handled = managedresponse(GRAPHICSSTATE, message)

    if not GRAPHICSSTATE.get('available'):
        GRAPHICSSCENE = []
        redraw()

    return handled



# CPU graphics functions
def drawimage():

    if not IMAGE:
        return

    try:

        path = str(IMAGE.get('output', ''))
        size = IMAGE.get('surface_size', [0, 0])
        width = int(size[0])
        height = int(size[1])
        imagex, imagey, _, _ = placement()
        viewx, viewy, viewwidth, viewheight = viewport()
        left = max(imagex, viewx)
        top = max(imagey, viewy)
        right = min(imagex + width, viewx + viewwidth)
        bottom = min(imagey + height, viewy + viewheight)

        if not os.path.isfile(path) or right <= left or bottom <= top:
            return

        sourcex = left - imagex
        sourcey = top - imagey
        blitfilepartfast(
            path,
            width,
            sourcex,
            sourcey,
            right - left,
            bottom - top,
            left,
            top,
            'BGRA32',
        )

    except Exception as error:
        log(f'image draw error {error}')


def drawcpu():

    try:

        fillrectfast(0, 0, int(WINW), int(WINH), COLOURBG)

        for button in buttons():

            x, y, width, height = button['rect']
            active = (button['name'] == MODE) or (button['name'] == 'actual' and MODE == 'zoom' and abs(ZOOM - 1.0) < 0.001)
            drawtextttf(x + scale(8), y + max(0, (height - FONTSIZE) // 2), button['label'], COLOURTEXT, FONTSIZE, FONT)

            if active:
                fillrectfast(x, y + height - 1, width, 1, COLOURTEXT)

        drawimage()
        statusy = max(0, int(WINH) - int(STATUSH) + max(0, (int(STATUSH) - int(FONTSIZE)) // 2))
        drawtextttf(PAD, statusy, statustext(), COLOURERROR if ERROR else COLOURTEXT, FONTSIZE, FONT)
        gfxpresent()

        if WINID and not GRAPHICSSTATE.get('available'):
            sendws({
                'op': 'DAMAGE',
                'winid': WINID,
                'rect': [0, 0, int(WINW), int(WINH)],
            })

        return True

    except Exception as error:

        log(f'CPU draw error {error}')
        return False


def redraw():

    global REDRAW

    REDRAW = True


def paint():

    global REDRAW

    if not REDRAW or not BUF or WINW < 1 or WINH < 1:
        return

    REDRAW = False
    drawcpu()

    if GRAPHICSSTATE.get('available'):
        submitscene()



# windowserver functions
def connectws():

    global WSOCK

    try:

        WSOCK = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        WSOCK.connect(WINDOWSOCK)
        WSOCK.setblocking(False)
        SEL.register(WSOCK, selectors.EVENT_READ | selectors.EVENT_WRITE)

    except Exception as error:

        log(f'windowserver connection error {error}')
        raise


def sendws(message):

    global OUTBUF

    try:
        OUTBUF.extend(json.dumps(message, separators=(',', ':')).encode('utf-8') + b'\n')

    except Exception as error:
        log(f'windowserver send error {error}')


def flushws():

    global OUTBUF

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


def createwindow():

    sendws({
        'op': 'CREATE_WINDOW',
        'role': APPROLE,
        'title': APPNAME,
        'current': windowname(SOURCE),
        'path': VIEWERPATH,
        'w': scale(BASEWINW),
        'h': scale(BASEWINH),
        'x': 120,
        'y': 100,
        'pid': os.getpid(),
    })


def mapwindow():

    sendws({
        'op': 'MAP',
        'winid': WINID,
    })


def windowcurrent(path):

    if WINID:
        sendws({
            'op': 'WINDOW_CURRENT_SET',
            'winid': WINID,
            'current': windowname(path),
        })


def windowname(path):

    source = str(path or '').strip()
    return os.path.basename(source) or source or APPNAME


def rebind():

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
    initbuffer(BUF, int(WINW), int(WINH))


def resized(message):

    global WINW, WINH, BUF, PANX, PANY

    if GRAPHICSSTATE.get('available') and WINID:
        managedclear(GRAPHICSSTATE, graphicssend, WINID)

    WINW = max(1, int(message.get('w', WINW)))
    WINH = max(1, int(message.get('h', WINH)))
    BUF = message.get('buffer', BUF)
    rebind()
    PANX = 0
    PANY = 0

    if SOURCE and MODE == 'fit':
        queue(delay=True)

    redraw()


def handlews(message):

    global WINID, BUF, WINW, WINH, SCREENW, SCREENH, NEEDWINDOW, RUNNING, FOCUSED

    operation = str(message.get('op', ''))

    if operation in ('GRAPHICS_COMMITTED', 'GRAPHICS_CLEARED'):

        graphicsresponse(message)
        return

    if operation in ('GRAPHICS_BEGUN', 'GRAPHICS_COMMAND_ADDED', 'GRAPHICS_INFO'):
        return

    if operation == 'WELCOME':

        framebuffer = message.get('fb', {})
        SCREENW = int(framebuffer.get('w', 0))
        SCREENH = int(framebuffer.get('h', 0))
        applyscale()
        graphicsconfigure(message.get('graphics', {}))

        if NEEDWINDOW:

            NEEDWINDOW = False
            createwindow()

        return

    if operation == 'FB_SIZE':

        SCREENW = int(message.get('w', SCREENW))
        SCREENH = int(message.get('h', SCREENH))
        applyscale()

        if NEEDWINDOW:

            NEEDWINDOW = False
            createwindow()

        redraw()
        return

    if operation == 'WINDOW_CREATED':

        WINID = int(message.get('winid'))
        BUF = message.get('buffer')
        WINW = max(1, int(message.get('w', WINW)))
        WINH = max(1, int(message.get('h', WINH)))
        initbuffer(BUF, WINW, WINH)
        initttffont(FONT, FONTSIZE)

        if SOURCE:
            queue(delay=False)

        redraw()
        return

    if operation == 'WINDOW_MAPPED':

        redraw()
        return

    if operation == 'RESIZED':

        resized(message)
        return

    if operation == 'FOCUS':

        FOCUSED = bool(message.get('focused', message.get('value', True)))
        return

    if operation == 'CLOSE':

        RUNNING = False
        sendws({'op': 'CLOSE_ACK', 'pid': os.getpid()})
        return

    if operation == 'ERROR':

        if str(message.get('code', '')).startswith('graphics_'):
            graphicsresponse(message)

        log(f'windowserver error code={message.get("code")} detail={message.get("detail")}')



# input functions
def setfit():

    global MODE, PANX, PANY

    MODE = 'fit'
    PANX = 0
    PANY = 0
    queue(delay=False)


def setzoom(value):

    global MODE, ZOOM, PANX, PANY

    if not SOURCE:
        return

    MODE = 'zoom'
    ZOOM = max(0.05, min(16.0, float(value)))
    PANX = 0
    PANY = 0
    queue(delay=False)


def keyinput(message):

    global PANX, PANY

    state = str(message.get('state', 'down')).lower()

    if state not in ('down', 'repeat'):
        return

    key = str(message.get('key', '')).upper()
    step = scale(32)

    if key in ('F', 'HOME'):

        setfit()
        return

    if key in ('1', 'NUM1'):

        setzoom(1.0)
        return

    if key in ('+', '=', 'PLUS', 'EQUAL'):

        setzoom((ZOOM if MODE == 'zoom' else max(0.05, float(zoomtext().rstrip('%') or 100) / 100.0)) * 1.25)
        return

    if key in ('-', 'MINUS'):

        setzoom((ZOOM if MODE == 'zoom' else max(0.05, float(zoomtext().rstrip('%') or 100) / 100.0)) / 1.25)
        return

    if key == 'LEFT':
        PANX += step

    elif key == 'RIGHT':
        PANX -= step

    elif key == 'UP':
        PANY += step

    elif key == 'DOWN':
        PANY -= step

    else:
        return

    clamppan()
    redraw()


def scrollinput(message):

    try:

        delta = int(message.get('dy', message.get('delta', 0)))

        if delta > 0:
            setzoom((ZOOM if MODE == 'zoom' else max(0.05, float(zoomtext().rstrip('%') or 100) / 100.0)) * 1.25)

        elif delta < 0:
            setzoom((ZOOM if MODE == 'zoom' else max(0.05, float(zoomtext().rstrip('%') or 100) / 100.0)) / 1.25)

    except Exception:
        pass


def pointerbutton(message):

    global DRAGGING, DRAGX, DRAGY, DRAGPANX, DRAGPANY

    pressed = str(message.get('state', 'down')).lower() == 'down'
    button = int(message.get('button', 1))
    x = int(message.get('x', 0))
    y = int(message.get('y', 0))

    if not pressed:

        DRAGGING = False
        return

    if button != 1:
        return

    for item in buttons():

        bx, by, width, height = item['rect']

        if bx <= x < bx + width and by <= y < by + height:

            if item['name'] == 'minus':
                setzoom((ZOOM if MODE == 'zoom' else max(0.05, float(zoomtext().rstrip('%') or 100) / 100.0)) / 1.25)

            elif item['name'] == 'plus':
                setzoom((ZOOM if MODE == 'zoom' else max(0.05, float(zoomtext().rstrip('%') or 100) / 100.0)) * 1.25)

            elif item['name'] == 'actual':
                setzoom(1.0)

            elif item['name'] == 'fit':
                setfit()

            return

    viewx, viewy, viewwidth, viewheight = viewport()

    if viewx <= x < viewx + viewwidth and viewy <= y < viewy + viewheight:

        DRAGGING = True
        DRAGX = x
        DRAGY = y
        DRAGPANX = PANX
        DRAGPANY = PANY


def pointermotion(message):

    global PANX, PANY

    if not DRAGGING:
        return

    x = int(message.get('x', 0))
    y = int(message.get('y', 0))
    PANX = int(DRAGPANX) + (x - int(DRAGX))
    PANY = int(DRAGPANY) + (y - int(DRAGY))
    clamppan()
    redraw()



# application diagnostic functions
def graphicsdiagnostic():

    global WINW, WINH, BUF, IMAGE, SOURCE, ERROR, LOADING, MODE, ZOOM, PANX, PANY
    global WORKER, WORKEROUTPUT, WORKERGEN, REQUESTGEN, FINISHEDGEN, REQUESTAT, SURFACENEXT

    result = {
        'version': VERSION,
        'passed': False,
        'checks': {},
        'errors': [],
    }
    root = f'{EPHEMERAL}/viewer-graphics-diagnostic-{os.getpid()}'
    original = {
        'WINW': WINW,
        'WINH': WINH,
        'BUF': BUF,
        'IMAGE': IMAGE,
        'SOURCE': SOURCE,
        'ERROR': ERROR,
        'LOADING': LOADING,
        'MODE': MODE,
        'ZOOM': ZOOM,
        'PANX': PANX,
        'PANY': PANY,
        'WORKER': WORKER,
        'WORKEROUTPUT': WORKEROUTPUT,
        'WORKERGEN': WORKERGEN,
        'REQUESTGEN': REQUESTGEN,
        'FINISHEDGEN': FINISHEDGEN,
        'REQUESTAT': REQUESTAT,
        'SURFACENEXT': SURFACENEXT,
    }

    try:

        if (
            COLOURBG,
            COLOURTEXT,
            COLOURERROR,
        ) != (0x000000, 0xEFEFEF, 0xFF0000):
            raise RuntimeError('viewer palette does not match Player')

        result['checks']['player_palette'] = True

        os.makedirs(root, mode=0o700, exist_ok=False)
        source = os.path.join(root, 'sample.png')
        output = os.path.join(root, 'surface.bgra')
        bufferpath = os.path.join(root, 'window.bgra')
        fixture(source, 'PNG', (4, 2), (220, 40, 30, 255))
        descriptor = render(source, output, 200, 100, 1)
        WINW = 320
        WINH = 240
        SOURCE = source
        IMAGE = descriptor
        ERROR = ''
        LOADING = False
        MODE = 'fit'
        ZOOM = 1.0
        PANX = 0
        PANY = 0

        with open(bufferpath, 'wb') as stream:
            stream.truncate(WINW * WINH * 4)

        BUF = bufferpath
        initbuffer(BUF, WINW, WINH)
        scene = buildscene()
        images = [item for item in scene if item.get('kind') == 'image']
        rectangles = [item for item in scene if item.get('kind') == 'rectangle']

        if not scene or scene[0].get('rect') != [0, 0, WINW, WINH] or len(images) != 1:
            raise RuntimeError('viewer did not build a complete managed image scene')

        if not rectangles or rectangles[0].get('color') != COLOURBG:
            raise RuntimeError('viewer introduced a non-black bar or control surface')

        if any(item.get('color') not in (COLOURBG, COLOURTEXT) for item in rectangles):
            raise RuntimeError('viewer introduced a grey surface')

        if any(item.get('rect', [0, 0, 0, 0])[3] != 1 for item in rectangles[1:]):
            raise RuntimeError('viewer introduced a filled control surface')

        result['checks']['black_surfaces'] = True

        if images[0].get('path') != output or images[0].get('format') != 'BGRA32':
            raise RuntimeError('viewer managed image scene has the wrong surface')

        result['checks']['managed_scene'] = True
        drawcpu()
        imagex, imagey, imagewidth, imageheight = placement()
        samplex = imagewidth // 2
        sampley = imageheight // 2
        surfaceoffset = (sampley * imagewidth + samplex) * 4
        bufferoffset = ((imagey + sampley) * WINW + imagex + samplex) * 4

        with open(output, 'rb') as stream:
            stream.seek(surfaceoffset)
            expected = stream.read(4)

        with open(bufferpath, 'rb') as stream:
            stream.seek(bufferoffset)
            actual = stream.read(4)

        if len(expected) != 4 or actual != expected or actual[:3] == b'\x00\x00\x00':
            raise RuntimeError('viewer CPU fallback did not blit the decoded surface')

        result['checks']['cpu_blit'] = True
        MODE = 'zoom'
        ZOOM = 2.0
        IMAGE = dict(descriptor)
        IMAGE['surface_size'] = [640, 400]
        PANX = 1000
        PANY = -1000
        clamppan()
        _, _, viewwidth, viewheight = viewport()

        if PANX > 0 or PANX < viewwidth - 640 or PANY > 0 or PANY < viewheight - 400:
            raise RuntimeError('viewer pan bounds are invalid')

        result['checks']['pan_clamp'] = [PANX, PANY]
        result['checks']['controls'] = [item['name'] for item in buttons()]
        WORKER = None
        WORKEROUTPUT = ''
        WORKERGEN = 0
        REQUESTGEN = 0
        FINISHEDGEN = 0
        REQUESTAT = 0.0
        SURFACENEXT = 0
        MODE = 'fit'
        IMAGE = descriptor
        ERROR = ''
        queue(delay=False)
        deadline = time.monotonic() + 10.0

        while time.monotonic() < deadline and FINISHEDGEN < REQUESTGEN:

            pollworker()
            time.sleep(0.01)

        if FINISHEDGEN != REQUESTGEN or ERROR or not IMAGE or not os.path.isfile(str(IMAGE.get('output', ''))):
            raise RuntimeError(f'viewer asynchronous worker did not complete {ERROR}')

        surfacecount = SURFACENEXT

        for _ in range(5):
            pollworker()

        if SURFACENEXT != surfacecount:
            raise RuntimeError('viewer restarted a completed surface request')

        result['checks']['async_worker'] = {
            'generation': FINISHEDGEN,
            'surfaces': SURFACENEXT,
        }
        result['passed'] = True

    except Exception as error:
        result['errors'].append(str(error))

    finally:

        if WORKER is not None and WORKER is not original['WORKER']:

            try:

                if WORKER.poll() is None:
                    WORKER.terminate()

                WORKER.communicate(timeout=1)

            except Exception:
                pass

        WINW = original['WINW']
        WINH = original['WINH']
        BUF = original['BUF']
        IMAGE = original['IMAGE']
        SOURCE = original['SOURCE']
        ERROR = original['ERROR']
        LOADING = original['LOADING']
        MODE = original['MODE']
        ZOOM = original['ZOOM']
        PANX = original['PANX']
        PANY = original['PANY']
        WORKER = original['WORKER']
        WORKEROUTPUT = original['WORKEROUTPUT']
        WORKERGEN = original['WORKERGEN']
        REQUESTGEN = original['REQUESTGEN']
        FINISHEDGEN = original['FINISHEDGEN']
        REQUESTAT = original['REQUESTAT']
        SURFACENEXT = original['SURFACENEXT']
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(VIEWROOT, ignore_errors=True)

    emit(result)
    return 0 if result['passed'] else 1



# core functions
def sourcepath(path):

    if path is None:
        return None

    try:

        target = os.path.abspath(os.path.normpath(str(path)))

        if not os.path.exists(target):
            raise FileNotFoundError(f'image file {path} not found')

        if not os.path.isfile(target):
            raise ValueError(f'{path} is not an image file')

        if os.path.islink(target):
            raise ValueError('symbolic links are not accepted as image sources')

        if not os.access(target, os.R_OK):
            raise PermissionError(f'permission denied reading {path}')

        return target

    except Exception:
        raise


def cleanup():

    global WORKER

    try:

        if WORKER is not None:

            if WORKER.poll() is None:
                WORKER.terminate()

            try:
                WORKER.communicate(timeout=1)

            except subprocess.TimeoutExpired:

                WORKER.kill()
                WORKER.communicate()

    except Exception:
        pass

    WORKER = None

    try:

        parent = os.path.realpath(os.path.dirname(VIEWROOT))

        if parent == '/.ephemeral/viewer' and not os.path.islink(VIEWROOT):
            shutil.rmtree(VIEWROOT, ignore_errors=True)

    except Exception:
        pass

    try:

        if WSOCK is not None:
            WSOCK.close()

    except Exception:
        pass


def terminate(signum, frame):

    global RUNNING

    RUNNING = False


def initapp():

    global NEEDWINDOW

    connectws()
    sendws({'op': 'HELLO'})
    sendws({'op': 'SUBSCRIBE', 'types': ['fbsize']})
    NEEDWINDOW = True

    while RUNNING and WINID is None:

        events = SEL.select(timeout=0.1)

        for key, mask in events:

            if key.fileobj is WSOCK and mask & selectors.EVENT_READ:

                for message in recvws():
                    handlews(message)

            if key.fileobj is WSOCK and mask & selectors.EVENT_WRITE:
                flushws()

        flushws()

    paint()
    flushws()
    mapwindow()
    sendws({'op': 'RAISE', 'winid': WINID})
    sendws({'op': 'FOCUS_SET', 'winid': WINID})
    flushws()


def pulse():

    global RUNNING

    events = SEL.select(timeout=0.04)

    for key, mask in events:

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

                if operation == 'KEY':
                    keyinput(message)

                elif operation == 'SCROLL':
                    scrollinput(message)

                elif operation == 'POINTER_BUTTON':
                    pointerbutton(message)

                elif operation == 'POINTER_MOTION':
                    pointermotion(message)

        if mask & selectors.EVENT_WRITE:
            flushws()

    pollworker()

    if GRAPHICSSTATE.get('available') and not managedtick(GRAPHICSSTATE):

        if WINID:
            sendws({'op': 'GRAPHICS_CLEAR', 'winid': WINID})

        redraw()

    paint()
    flushws()


def main(args):

    global SOURCE, ERROR

    if args:

        try:
            SOURCE = sourcepath(' '.join(args))

        except Exception as error:

            ERROR = str(error)[:512]
            SOURCE = None

    atexit.register(cleanup)
    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)
    initapp()

    while RUNNING:
        pulse()

    flushws()
    return 0


if __name__ == '__main__':

    arguments = list(sys.argv[1:])

    if arguments and arguments[0] == '--render':
        raise SystemExit(rendercommand(arguments[1:]))

    if arguments and arguments[0] == '--diagnostic':
        raise SystemExit(diagnostic())

    if arguments and arguments[0] == '--graphics-diagnostic':
        raise SystemExit(graphicsdiagnostic())

    raise SystemExit(main(arguments))
