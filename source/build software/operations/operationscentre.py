#!"/the one/software/python/bin/python" -B

"""
operationscentre.py

operations centre displays and manages operations in The One OS.
"""



# imports
import os
import sys
import json
import time
import queue
import socket
import signal
import atexit
import shutil
import threading
import selectors
import subprocess

sys.path.insert(0, '/the one/build')

from GODDESS.GODDESS import formatlog, popenisolated, softwarelogpath
import graphics.graphics as gfx
from graphics.graphics import initbuffer, fillrectfast, drawrect, drawline, drawtextttf
from graphics.graphics import initttffont, measuretext, present as gfxpresent
from graphics.graphics import managedstate, managedconfigure, manageddisable, managedclear
from graphics.graphics import managedmarkdamage, managedtick, managedsubmit, managedresponse, uiscalefactor, displayuiscale



# globals

# paths
APPPATH = '/the one/build/operations/operationscentre.py'
LOGFILE = '/the one/logs/operationscentre.py.log'
SETTINGSPATH = '/the one/settings/operations centre/settings.json'
STARTUPPATH = '/the one/settings/procedures/startup/startup.txt'
WINDOWSOCK = '/.ephemeral/windowserver/accept.sock'
OPERATIONSSOCK = '/.ephemeral/operations/control.sock'
FONT = '/the one/resources/fonts/atkinsonhyperlegiblenext.ttf'

# application
APPNAME = 'operations centre'
APPROLE = 'window'
VERSION = 2
RUNNING = True
FOCUSED = True
PAUSED = False
ONLINE = False
LASTERROR = ''
STATUS = ''
STATUSERROR = False
STATUSUNTIL = 0.0
VIEW = 'operations'
VIEWS = ('operations', 'performance', 'history', 'startup')
SEARCHING = False
SEARCHTEXT = ''
SEARCHCARETPOS = 0
SEARCHLASTBLINK = None
SORTCOLUMN = 'name'
SORTREVERSE = False
SELECTED = None
SCROLL = 0
HOVERROW = None
CONFIRM = None
CONTEXT = None
LASTCLICK = {'row': None, 'time': 0.0}
SNAPSHOT = {
    'status': 'waiting',
    'version': 2,
    'sampled': 0.0,
    'sample_ms': 0,
    'system': {},
    'operations': {},
    'completed': {},
}
HISTORYCPU = []
HISTORYGPU = []
HISTORYMEMORY = []
HISTORYKEEP = 120
REFRESHINTERVAL = 1.0
ROWMAP = {}
NAVMAP = {}
HEADERMAP = {}
ACTIONMAP = {}
COLUMNMAP = {}
COLUMNORDER = ('name', 'state', 'cpu', 'gpu', 'memory', 'mode', 'runtime', 'user', 'pid')
COLUMNWIDTHS = {
    'name': 230,
    'state': 76,
    'cpu': 58,
    'gpu': 58,
    'memory': 84,
    'mode': 64,
    'runtime': 74,
    'user': 70,
    'pid': 58,
}
COLUMNRESIZING = None
COLUMNRESIZENEXT = None
COLUMNRESIZESTARTX = 0
COLUMNRESIZESTARTW = 0
COLUMNRESIZENEXTW = 0
COLUMNCURSORMODE = 'arrow'
DETAILMAP = {}
CONTEXTMAP = {}

# sampler
SAMPLEQUEUE = queue.Queue(maxsize=1)
SAMPLESTOP = threading.Event()
SAMPLER = None

# window
BASEWINW = 1120
BASEWINH = 700
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

# graphics
COLOURBG = 0x000000
COLOURTEXT = 0xEFEFEF
COLOURSTATUS = 0x242424
COLOURDIVIDER = 0x3A3A3A
COLOURMUTED = 0x6A6A6A
COLOURERROR = 0xFF0000
COLOURHILITETEXT = 0x000000
GRAPHICSCPUOVERRIDE = str(os.environ.get('T1OS_OPERATIONS_CENTRE_GRAPHICS', '')).strip().lower() in ('cpu', 'off', '0', 'false')
GRAPHICSSTATE = managedstate(cpu=GRAPHICSCPUOVERRIDE)
GRAPHICSSCENE = []
REDRAW = True

# base measurements
BASEPAD = 9
BASEHEADERH = 78
BASETOOLBARH = 34
BASESTATUSH = 32
BASENAVW = 154
BASEROWH = 28
BASECOLUMNH = 27
BASEDETAILW = 286
BASEFONTSIZE = 14
BASESMALLFONT = 12
BASETITLEFONT = 24
BASESCROLLW = 12

# scaled measurements
PAD = BASEPAD
HEADERH = BASEHEADERH
TOOLBARH = BASETOOLBARH
STATUSH = BASESTATUSH
NAVW = BASENAVW
ROWH = BASEROWH
COLUMNH = BASECOLUMNH
DETAILW = BASEDETAILW
FONTSIZE = BASEFONTSIZE
SMALLFONT = BASESMALLFONT
TITLEFONT = BASETITLEFONT
SCROLLW = BASESCROLLW



# general functions
def log(message):

    try:

        directory = os.path.dirname(LOGFILE)

        if directory:
            os.makedirs(directory, exist_ok=True)

        with open(LOGFILE, 'a', encoding='utf-8') as stream:
            stream.write(formatlog('operations centre', str(message)) + '\n')

    except Exception:
        pass


def scale(value):

    try:
        return max(1, int(round(float(value) * float(UISCALE))))
    except Exception:
        return max(1, int(value))


def applyscale():

    global UISCALE, PAD, HEADERH, TOOLBARH, STATUSH, NAVW, ROWH, COLUMNH
    global DETAILW, FONTSIZE, SMALLFONT, TITLEFONT, SCROLLW

    try:

        UISCALE = displayuiscale(SCREENW, SCREENH, uiscalefactor())

    except Exception:
        UISCALE = 1.0

    PAD = scale(BASEPAD)
    HEADERH = scale(BASEHEADERH)
    TOOLBARH = scale(BASETOOLBARH)
    STATUSH = scale(BASESTATUSH)
    NAVW = scale(BASENAVW)
    ROWH = scale(BASEROWH)
    COLUMNH = scale(BASECOLUMNH)
    DETAILW = scale(BASEDETAILW)
    FONTSIZE = scale(BASEFONTSIZE)
    SMALLFONT = scale(BASESMALLFONT)
    TITLEFONT = scale(BASETITLEFONT)
    SCROLLW = scale(BASESCROLLW)


def setstatus(message, error=False, duration=3.0):

    global STATUS, STATUSERROR, STATUSUNTIL

    STATUS = str(message)
    STATUSERROR = bool(error)
    STATUSUNTIL = time.monotonic() + max(0.0, float(duration))
    redraw()


def statusmessage():

    global STATUS, STATUSERROR, STATUSUNTIL

    if STATUS and time.monotonic() >= STATUSUNTIL:
        STATUS = ''
        STATUSERROR = False
        STATUSUNTIL = 0.0
        redraw()

    return STATUS


def formatbytes(value):

    try:
        number = max(0.0, float(value))
    except Exception:
        return '-'

    units = ('B', 'KB', 'MB', 'GB', 'TB')
    used = units[0]

    for unit in units:

        used = unit

        if number < 1024.0 or unit == units[-1]:
            break

        number /= 1024.0

    if used == 'B':
        return f'{int(number)} {used}'

    if number < 10.0:
        return f'{number:.1f} {used}'

    return f'{number:.0f} {used}'


def formatpercent(value):

    try:
        return f'{max(0.0, float(value)):.1f}%'
    except Exception:
        return '-'


def formatduration(started, ended=None):

    try:

        start = float(started)
        stop = float(ended) if ended is not None else time.time()
        seconds = max(0, int(stop - start))
        days, seconds = divmod(seconds, 86400)
        hours, seconds = divmod(seconds, 3600)
        minutes, seconds = divmod(seconds, 60)

        if days:
            return f'{days}d {hours}h'

        if hours:
            return f'{hours}h {minutes}m'

        if minutes:
            return f'{minutes}m {seconds}s'

        return f'{seconds}s'

    except Exception:
        return '-'


def fittext(value, width, size=None):

    text = str(value)
    usedsize = FONTSIZE if size is None else int(size)

    if width <= 0:
        return ''

    try:

        if measuretext(text, usedsize, FONT) <= width:
            return text

        suffix = '…'

        while text and measuretext(text + suffix, usedsize, FONT) > width:
            text = text[:-1]

        return text + suffix if text else suffix

    except Exception:
        return text[:max(0, width // max(1, usedsize // 2))]


def pointin(x, y, rect):

    try:

        left, top, width, height = [int(value) for value in rect]
        return left <= int(x) < left + width and top <= int(y) < top + height

    except Exception:
        return False


def loadsettings():

    global VIEW, SORTCOLUMN, SORTREVERSE, REFRESHINTERVAL, COLUMNWIDTHS

    try:

        with open(SETTINGSPATH, encoding='utf-8') as stream:
            settings = json.load(stream)

        view = str(settings.get('view', VIEW))

        if view in VIEWS:
            VIEW = view

        column = str(settings.get('sort', SORTCOLUMN))

        if column in COLUMNORDER:
            SORTCOLUMN = column

        SORTREVERSE = bool(settings.get('reverse', SORTREVERSE))
        # Version 1 accidentally persisted the reverse-alphabetical default.
        # Preserve deliberate non-name sorts, but migrate that old default.
        if int(settings.get('version', 0) or 0) < 2 and SORTCOLUMN == 'name':
            SORTREVERSE = False
        REFRESHINTERVAL = max(0.5, min(5.0, float(settings.get('refresh', REFRESHINTERVAL))))
        widths = settings.get('column_widths', {})

        if isinstance(widths, dict):

            for identifier in COLUMNORDER:

                try:
                    COLUMNWIDTHS[identifier] = max(42, min(900, int(widths.get(identifier, COLUMNWIDTHS[identifier]))))
                except Exception:
                    pass

    except Exception:
        pass


def savesettings():

    temporary = f'{SETTINGSPATH}.tmp.{os.getpid()}'

    try:

        os.makedirs(os.path.dirname(SETTINGSPATH), exist_ok=True)

        with open(temporary, 'w', encoding='utf-8') as stream:
            json.dump({
                'version': VERSION,
                'view': VIEW,
                'sort': SORTCOLUMN,
                'reverse': SORTREVERSE,
                'refresh': REFRESHINTERVAL,
                'column_widths': dict(COLUMNWIDTHS),
            }, stream, sort_keys=True, separators=(',', ':'))
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())

        os.replace(temporary, SETTINGSPATH)

    except Exception:

        try:

            if os.path.exists(temporary):
                os.unlink(temporary)

        except Exception:
            pass



# operations functions
def opsrequest(payload, timeout=0.8):

    connection = None

    try:

        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.settimeout(max(0.1, float(timeout)))
        connection.connect(OPERATIONSSOCK)
        connection.sendall(json.dumps(payload, separators=(',', ':')).encode('utf-8') + b'\n')
        stream = connection.makefile('rb')
        line = stream.readline()

        if not line:
            raise ConnectionError('operations server returned no response')

        response = json.loads(line.decode('utf-8', errors='replace'))

        if not isinstance(response, dict):
            raise ValueError('operations response is not an object')

        return response

    except FileNotFoundError:
        return {'status': 'error', 'message': 'operations server is offline'}

    except ConnectionRefusedError:
        return {'status': 'error', 'message': 'operations server refused the connection'}

    except TimeoutError:
        return {'status': 'error', 'message': 'operations server timed out'}

    except Exception as error:
        return {'status': 'error', 'message': str(error)}

    finally:

        try:

            if connection is not None:
                connection.close()

        except Exception:
            pass


def queuesample(response):

    try:

        while True:
            SAMPLEQUEUE.get_nowait()

    except queue.Empty:
        pass

    try:
        SAMPLEQUEUE.put_nowait(response)
    except queue.Full:
        pass


def sampler():

    while not SAMPLESTOP.is_set():

        started = time.monotonic()

        if not PAUSED:
            queuesample(opsrequest({'op': 'LIST', 'resources': True, 'completed': True}))

        elapsed = time.monotonic() - started
        SAMPLESTOP.wait(max(0.1, float(REFRESHINTERVAL) - elapsed))


def startsampler():

    global SAMPLER

    if SAMPLER is not None and SAMPLER.is_alive():
        return

    SAMPLESTOP.clear()
    SAMPLER = threading.Thread(target=sampler, name='operations-centre-sampler', daemon=True)
    SAMPLER.start()


def samplepump():

    global SNAPSHOT, ONLINE, LASTERROR, SELECTED

    newest = None

    try:

        while True:
            newest = SAMPLEQUEUE.get_nowait()

    except queue.Empty:
        pass

    if newest is None:
        return

    if newest.get('status') != 'ok':

        ONLINE = False
        LASTERROR = str(newest.get('message', 'operations server is unavailable'))
        redraw()
        return

    SNAPSHOT = newest
    ONLINE = True
    LASTERROR = ''
    system = newest.get('system', {})
    cpu = system.get('cpu_percent')
    total = system.get('memory_total_bytes')
    used = system.get('memory_used_bytes')

    if cpu is not None:
        HISTORYCPU.append(float(cpu))
        del HISTORYCPU[:-HISTORYKEEP]

    gpu = system.get('gpu_percent')

    if gpu is not None:
        HISTORYGPU.append(float(gpu))
        del HISTORYGPU[:-HISTORYKEEP]

    if total and used is not None:
        HISTORYMEMORY.append((float(used) / float(total)) * 100.0)
        del HISTORYMEMORY[:-HISTORYKEEP]

    if SELECTED is not None:

        available = {}
        available.update(newest.get('operations', {}))
        available.update(newest.get('completed', {}))

        if str(SELECTED) not in available:
            SELECTED = None

    clampscroll()
    redraw()


def selectedentry():

    if SELECTED is None:
        return None

    if VIEW == 'history':
        return SNAPSHOT.get('completed', {}).get(str(SELECTED))

    if VIEW == 'startup':

        for entry in startuprows():

            if str(entry.get('pid')) == str(SELECTED):
                return entry

        return None

    if VIEW != 'operations':
        return None

    return SNAPSHOT.get('operations', {}).get(str(SELECTED))


def operationsortvalue(entry):

    resources = entry.get('resources', {})

    if SORTCOLUMN == 'cpu':
        return float(resources.get('cpu_percent') or 0.0)

    if SORTCOLUMN == 'gpu':
        return float(resources.get('gpu_percent') or 0.0)

    if SORTCOLUMN == 'memory':
        return int(resources.get('memory_bytes') or 0)

    if SORTCOLUMN == 'runtime':
        return float(entry.get('started') or 0.0)

    if SORTCOLUMN == 'pid':
        return int(entry.get('pid') or 0)

    return str(entry.get(SORTCOLUMN, '')).casefold()


def operationrows():

    source = SNAPSHOT.get('completed', {}) if VIEW == 'history' else SNAPSHOT.get('operations', {})
    rows = []
    requested = SEARCHTEXT.strip().casefold()

    for pid, info in source.items():

        try:

            if VIEW == 'operations' and str(info.get('state', 'running')).casefold() == 'starting':
                continue

            entry = dict(info)
            entry['pid'] = int(pid)
            entry.setdefault('name', 'operation')
            entry.setdefault('state', 'completed' if VIEW == 'history' else 'running')
            entry.setdefault('mode', '')
            entry.setdefault('user', '')
            entry.setdefault('script', '')
            entry.setdefault('args', [])
            entry.setdefault('resources', {})
            searchable = ' '.join([
                str(entry.get('pid', '')),
                str(entry.get('name', '')),
                str(entry.get('script', '')),
                ' '.join(str(value) for value in entry.get('args', [])),
            ]).casefold()

            if requested and requested not in searchable:
                continue

            rows.append(entry)

        except Exception:
            continue

    rows.sort(key=operationsortvalue, reverse=bool(SORTREVERSE))
    return rows


def startuprows():

    rows = []

    try:

        with open(STARTUPPATH, encoding='utf-8') as stream:
            lines = [line.strip() for line in stream if line.strip() and not line.lstrip().startswith('#')]

        for index in range(0, len(lines), 2):
            rows.append({
                'pid': index // 2 + 1,
                'name': os.path.splitext(os.path.basename(lines[index]))[0],
                'script': lines[index],
                'mode': lines[index + 1] if index + 1 < len(lines) else 'invalid',
                'state': 'startup',
                'user': '',
                'args': [],
                'resources': {},
            })

    except Exception:
        return []

    return rows


def currentrows():

    if VIEW == 'startup':

        rows = startuprows()
        requested = SEARCHTEXT.strip().casefold()

        if requested:
            rows = [
                entry for entry in rows
                if requested in ' '.join([
                    str(entry.get('name', '')),
                    str(entry.get('script', '')),
                    str(entry.get('mode', '')),
                ]).casefold()
            ]

        rows.sort(key=operationsortvalue, reverse=bool(SORTREVERSE))
        return rows

    if VIEW in ('operations', 'history'):
        return operationrows()

    return []


def tableitems():

    rows = currentrows()

    if SORTCOLUMN != 'name' or VIEW not in ('operations', 'history') or not rows:
        return rows

    groups = (
        ('front', [entry for entry in rows if str(entry.get('mode', '')).casefold() == 'front']),
        ('behind', [entry for entry in rows if str(entry.get('mode', '')).casefold() != 'front']),
    )
    items = []

    for label, entries in groups:

        if not entries:
            continue

        if items:
            items.append({'_operation_group_gap': True})

        items.append({'_operation_group': label})
        items.extend(entries)

    return items


def killselected(force=False):

    entry = selectedentry()

    if entry is None:
        setstatus('select an operation first', error=True)
        return False

    response = opsrequest({
        'op': 'KILL',
        'pid': int(entry.get('pid', SELECTED)),
        'identity': str(entry.get('identity', '')),
        'tree': True,
        'force': bool(force),
    }, timeout=1.5)

    if response.get('status') != 'ok':
        setstatus(str(response.get('message', 'could not kill operation')), error=True)
        return False

    count = len(response.get('signalled', []))
    wording = 'force killed' if force else 'killed'
    setstatus(f'{wording} {entry.get("name", "operation")}  {count} process{"es" if count != 1 else ""}')
    queuesample(opsrequest({'op': 'LIST', 'resources': True, 'completed': True}))
    return True


def openlog():

    entry = selectedentry()

    if entry is None:
        setstatus('select an operation first', error=True)
        return False

    path = str(entry.get('log', '')).strip()

    if not path or path == '-' or not os.path.isfile(path):
        setstatus('this operation has no readable log', error=True)
        return False

    try:

        readpath = '/the one/build/read/read.py'
        readlog = softwarelogpath(readpath)
        process = popenisolated(
            [sys.executable, readpath, path],
            softwarepath=readpath,
            logpath=readlog,
        )
        opsrequest({
            'op': 'REGISTER_PID',
            'pid': int(process.pid),
            'name': 'read log',
            'script': readpath,
            'log': readlog,
            'user': str(entry.get('user', 'master')),
            'mode': 'front',
            'state': 'starting',
        })
        return True

    except Exception as error:
        setstatus(f'could not open log {error}', error=True)
        return False



# layout functions
def contenttop():

    return HEADERH + TOOLBARH + COLUMNH


def contentbottom():

    return max(contenttop(), WINH - STATUSH)


def detailvisible():

    return WINW >= scale(980) and VIEW in ('operations', 'history') and selectedentry() is not None


def mainrect():

    left = NAVW + 1
    right = WINW - (DETAILW + 1 if detailvisible() else 0)
    return [left, contenttop(), max(1, right - left), max(1, contentbottom() - contenttop())]


def columns():

    left = NAVW + 1
    right = WINW - (DETAILW + 1 if detailvisible() else 0) - SCROLLW
    available = max(scale(420), right - left)
    widths = {
        identifier: max(scale(80 if identifier == 'name' else 42), scale(COLUMNWIDTHS.get(identifier, 60)))
        for identifier in COLUMNORDER
    }
    total = sum(widths.values())

    if total < available:
        widths['name'] += available - total

    elif total > available:

        excess = total - available

        for identifier in COLUMNORDER:

            minimum = scale(80 if identifier == 'name' else 42)
            reduction = min(excess, max(0, widths[identifier] - minimum))
            widths[identifier] -= reduction
            excess -= reduction

            if excess <= 0:
                break

    result = []
    x = left

    labels = {
        'name': 'operation',
        'state': 'state',
        'cpu': 'CPU',
        'gpu': 'GPU',
        'memory': 'memory',
        'mode': 'mode',
        'runtime': 'runtime',
        'user': 'user',
        'pid': 'PID',
    }

    for identifier in COLUMNORDER:

        label = labels[identifier]
        width = widths[identifier]
        result.append({'id': identifier, 'label': label, 'rect': [x, HEADERH + TOOLBARH, width, COLUMNH]})
        x += width

    return result


def columnresizehit(x, y):

    if VIEW == 'performance':
        return None

    layout = columns()

    for index, column in enumerate(layout[:-1]):

        rect = column['rect']
        edge = int(rect[0]) + int(rect[2])

        if (
            abs(int(x) - edge) <= scale(5)
            and int(rect[1]) <= int(y) < int(rect[1]) + int(rect[3])
        ):
            return column['id'], layout[index + 1]['id']

    return None


def freezecolumnwidths():

    factor = max(0.01, float(UISCALE))

    for column in columns():
        COLUMNWIDTHS[column['id']] = max(42, min(900, int(round(column['rect'][2] / factor))))


def setpointercursor(mode):

    global COLUMNCURSORMODE

    mode = str(mode or 'arrow')

    if mode == COLUMNCURSORMODE:
        return

    COLUMNCURSORMODE = mode
    sendws({
        'op': 'CURSOR_MODE_SET',
        'winid': WINID,
        'mode': mode,
    })


def updatecolumncursor(x, y):

    if COLUMNRESIZING is not None or columnresizehit(x, y) is not None:
        setpointercursor('resize_h')
    else:
        setpointercursor('arrow')


def visiblerows():

    _, _, _, height = mainrect()
    return max(1, height // ROWH)


def clampscroll():

    global SCROLL

    count = len(tableitems())
    maximum = max(0, count - visiblerows())
    SCROLL = max(0, min(int(SCROLL), maximum))


def rowrect(index):

    left, top, width, _ = mainrect()
    return [left, top + ((int(index) - int(SCROLL)) * ROWH), width - SCROLLW, ROWH]


def scrollbar():

    count = len(tableitems())
    visible = visiblerows()
    left, top, width, height = mainrect()
    track = [left + width - SCROLLW, top, SCROLLW, height]

    if count <= visible:
        return track, None

    thumbheight = max(scale(28), int(height * (visible / float(count))))
    travel = max(1, height - thumbheight)
    maximum = max(1, count - visible)
    thumby = top + int(travel * (SCROLL / float(maximum)))
    return track, [track[0], thumby, track[2], thumbheight]


def actionitems():

    selected = selectedentry() is not None and VIEW == 'operations'

    return [
        ('kill', 'kill', selected),
        ('force kill', 'forcekill', selected),
        ('read log', 'log', selectedentry() is not None and VIEW in ('operations', 'history')),
        ('resume' if PAUSED else 'pause', 'pause', True),
        ('refresh', 'refresh', True),
    ]



# managed graphics functions
def graphicssend(request):

    try:
        sendws(request)
        return True
    except Exception:
        return False


def graphicsconfigure(capabilities):

    return managedconfigure(
        GRAPHICSSTATE,
        capabilities,
        required=('rectangle', 'line', 'text'),
        cpu=GRAPHICSCPUOVERRIDE or not os.path.isfile(FONT),
    )


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


def rectnode(rect, colour, clip=None):

    usedclip = [0, 0, WINW, WINH] if clip is None else list(clip)
    return {'kind': 'rectangle', 'rect': [int(value) for value in rect], 'color': int(colour), 'clip': usedclip}


def linenode(x1, y1, x2, y2, colour, clip=None):

    usedclip = [0, 0, WINW, WINH] if clip is None else list(clip)
    return {
        'kind': 'line',
        'points': [int(x1), int(y1), int(x2), int(y2)],
        'width': 1,
        'color': int(colour),
        'clip': usedclip,
    }


def textnode(x, y, text, colour, size, clip):

    return {
        'kind': 'text',
        'x': max(0, int(x)),
        'y': max(0, int(baseline(y, size))),
        'text': str(text)[:1024],
        'size': int(size),
        'font': FONT,
        'color': int(colour),
        'clip': [int(value) for value in clip],
    }


def addtext(commands, x, y, text, colour, size, clip):

    commands.append(textnode(x, y, text, colour, size, clip))


def buildheader(commands):

    global HEADERMAP

    HEADERMAP = {}
    clip = [0, 0, WINW, HEADERH]
    addtext(commands, NAVW + PAD, PAD + scale(8), 'operations centre', COLOURTEXT, TITLEFONT, clip)
    system = SNAPSHOT.get('system', {})
    cpu = formatpercent(system.get('cpu_percent'))
    gpu = formatpercent(system.get('gpu_percent'))
    used = formatbytes(system.get('memory_used_bytes'))
    total = formatbytes(system.get('memory_total_bytes'))
    summary = f'CPU {cpu}   GPU {gpu}   memory {used} / {total}'
    width = measuretext(summary, SMALLFONT, FONT)
    addtext(commands, max(NAVW + PAD, WINW - PAD - width), PAD + scale(14), summary, COLOURMUTED, SMALLFONT, clip)

    searchwidth = min(scale(300), max(scale(160), WINW - NAVW - (PAD * 2)))
    searchrect = [WINW - PAD - searchwidth, HEADERH - PAD - scale(27), searchwidth, scale(27)]
    commands.append(rectnode([searchrect[0], searchrect[1], searchrect[2], 1], COLOURTEXT if SEARCHING else COLOURDIVIDER, clip))
    label = SEARCHTEXT if SEARCHTEXT else 'search operations'
    colour = COLOURTEXT if SEARCHTEXT else COLOURMUTED
    addtext(commands, searchrect[0], searchrect[1] + scale(4), fittext(label, searchrect[2], SMALLFONT), colour, SMALLFONT, searchrect)
    HEADERMAP['search'] = searchrect

    if SEARCHING and (int(time.monotonic() * 2) % 2) == 0:
        prefix = SEARCHTEXT[:SEARCHCARETPOS]
        caret = min(searchrect[2], measuretext(prefix, SMALLFONT, FONT))
        commands.append(linenode(searchrect[0] + caret, searchrect[1] + 3, searchrect[0] + caret, searchrect[1] + searchrect[3] - 3, COLOURTEXT, searchrect))


def buildnav(commands):

    global NAVMAP

    NAVMAP = {}
    commands.append(linenode(NAVW, 0, NAVW, WINH - STATUSH, COLOURDIVIDER))
    y = HEADERH + PAD

    for view in VIEWS:

        rect = [0, y, NAVW, ROWH]

        if VIEW == view:
            commands.append(rectnode(rect, COLOURSTATUS))

        addtext(commands, PAD + scale(10), y + max(0, (ROWH - FONTSIZE) // 2), view, COLOURTEXT if VIEW == view else COLOURMUTED, FONTSIZE, rect)
        NAVMAP[view] = rect
        y += ROWH


def buildtoolbar(commands):

    clip = [NAVW + 1, HEADERH, WINW - NAVW - 1, TOOLBARH]
    commands.append(linenode(NAVW + 1, HEADERH + TOOLBARH - 1, WINW, HEADERH + TOOLBARH - 1, COLOURDIVIDER))
    title = windowname()
    addtext(commands, NAVW + PAD, HEADERH + max(0, (TOOLBARH - FONTSIZE) // 2), title, COLOURTEXT, FONTSIZE, clip)
    state = 'paused' if PAUSED else ('live' if ONLINE else 'offline')
    width = measuretext(state, SMALLFONT, FONT)
    addtext(commands, WINW - PAD - width, HEADERH + max(0, (TOOLBARH - SMALLFONT) // 2), state, COLOURMUTED if ONLINE else COLOURERROR, SMALLFONT, clip)


def buildcolumns(commands):

    global COLUMNMAP

    COLUMNMAP = {}
    y = HEADERH + TOOLBARH
    commands.append(linenode(NAVW + 1, y + COLUMNH - 1, WINW, y + COLUMNH - 1, COLOURDIVIDER))

    for column in columns():

        identifier = column['id']
        rect = column['rect']
        label = column['label']

        if SORTCOLUMN == identifier:
            label += ' v' if SORTREVERSE else ' ^'

        addtext(commands, rect[0] + PAD, rect[1] + max(0, (rect[3] - SMALLFONT) // 2), label, COLOURMUTED, SMALLFONT, rect)
        commands.append(linenode(rect[0] + rect[2] - 1, rect[1] + 4, rect[0] + rect[2] - 1, rect[1] + rect[3] - 4, COLOURDIVIDER, rect))
        COLUMNMAP[identifier] = rect


def rowvalue(entry, identifier):

    resources = entry.get('resources', {})

    if identifier == 'name':
        return entry.get('name', 'operation')

    if identifier == 'cpu':
        return formatpercent(resources.get('cpu_percent'))

    if identifier == 'gpu':
        return formatpercent(resources.get('gpu_percent'))

    if identifier == 'memory':
        return formatbytes(resources.get('memory_bytes'))

    if identifier == 'runtime':
        return formatduration(entry.get('started'), entry.get('ended'))

    if identifier == 'pid':
        return str(entry.get('pid', ''))

    return str(entry.get(identifier, ''))


def buildtable(commands):

    global ROWMAP

    ROWMAP = {}
    items = tableitems()
    end = min(len(items), SCROLL + visiblerows())

    for index in range(SCROLL, end):

        entry = items[index]
        rect = rowrect(index)

        if '_operation_group_gap' in entry:
            continue

        if '_operation_group' in entry:

            if index:
                commands.append(linenode(rect[0], rect[1], rect[0] + rect[2], rect[1], COLOURDIVIDER))

            addtext(
                commands,
                rect[0] + PAD,
                rect[1] + max(0, (rect[3] - SMALLFONT) // 2),
                entry['_operation_group'],
                COLOURMUTED,
                SMALLFONT,
                rect,
            )
            continue

        if str(entry.get('pid')) == str(SELECTED):
            commands.append(rectnode(rect, COLOURSTATUS))

        commands.append(rectnode([rect[0], rect[1] + rect[3] - 1, rect[2], 1], COLOURDIVIDER, rect))

        for column in columns():

            columnrect = column['rect']
            cell = [columnrect[0], rect[1], columnrect[2], rect[3]]
            value = fittext(rowvalue(entry, column['id']), max(1, cell[2] - (PAD * 2)), FONTSIZE)
            colour = COLOURTEXT if column['id'] == 'name' else COLOURMUTED
            addtext(commands, cell[0] + PAD, cell[1] + max(0, (cell[3] - FONTSIZE) // 2), value, colour, FONTSIZE, cell)

        ROWMAP[index] = rect

    track, thumb = scrollbar()
    commands.append(rectnode(track, COLOURBG))
    commands.append(rectnode([track[0], track[1], 1, track[3]], COLOURDIVIDER))

    if thumb is not None:
        commands.append(rectnode(thumb, COLOURSTATUS))
        commands.append(rectnode([thumb[0], thumb[1], 1, thumb[3]], COLOURMUTED))

    if not items:

        message = 'no matching operations' if SEARCHTEXT else {
            'operations': 'no running operations',
            'history': 'no completed operations',
            'startup': 'no startup operations',
        }.get(VIEW, 'no information')
        left, top, width, height = mainrect()
        addtext(commands, left + PAD, top + PAD, message, COLOURMUTED, FONTSIZE, [left, top, width, height])


def builddetails(commands):

    global DETAILMAP

    DETAILMAP = {}

    if not detailvisible():
        return

    entry = selectedentry()
    left = WINW - DETAILW
    top = HEADERH + TOOLBARH
    bottom = WINH - STATUSH
    clip = [left, top, DETAILW, bottom - top]
    commands.append(rectnode(clip, COLOURBG))
    commands.append(linenode(left, top, left, bottom, COLOURDIVIDER))
    addtext(commands, left + PAD, top + PAD, 'details', COLOURTEXT, FONTSIZE, clip)
    resources = entry.get('resources', {})
    arguments = ' '.join(str(value) for value in entry.get('args', []))
    lines = [
        ('operation', entry.get('name', '')),
        ('state', entry.get('state', '')),
        ('PID', entry.get('pid', '')),
        ('user', entry.get('user', '')),
        ('mode', entry.get('mode', '')),
        ('CPU', formatpercent(resources.get('cpu_percent'))),
        ('GPU', formatpercent(resources.get('gpu_percent'))),
        ('memory', formatbytes(resources.get('memory_bytes'))),
        ('peak memory', formatbytes(resources.get('peak_memory_bytes', entry.get('peak_memory_bytes')))),
        ('threads', resources.get('threads', '-')),
        ('children', resources.get('children', '-')),
        ('read', formatbytes(resources.get('read_bytes'))),
        ('written', formatbytes(resources.get('write_bytes'))),
        ('runtime', formatduration(entry.get('started'), entry.get('ended'))),
        ('result', entry.get('exitcode', '-')),
        ('script', entry.get('script', '')),
        ('arguments', arguments),
        ('log', entry.get('log', '')),
    ]
    y = top + PAD + ROWH

    for label, value in lines:

        if y + (SMALLFONT * 2) + PAD >= bottom:
            break

        addtext(commands, left + PAD, y, str(label), COLOURMUTED, SMALLFONT, clip)
        y += SMALLFONT + scale(2)
        addtext(commands, left + PAD, y, fittext(str(value), DETAILW - (PAD * 2), SMALLFONT), COLOURTEXT, SMALLFONT, clip)
        y += SMALLFONT + scale(8)


def graphnodes(commands, rect, values, label, summary):

    commands.append(rectnode(rect, COLOURBG))
    commands.append(rectnode([rect[0], rect[1], rect[2], 1], COLOURDIVIDER))
    commands.append(rectnode([rect[0], rect[1] + rect[3] - 1, rect[2], 1], COLOURDIVIDER))
    commands.append(rectnode([rect[0], rect[1], 1, rect[3]], COLOURDIVIDER))
    commands.append(rectnode([rect[0] + rect[2] - 1, rect[1], 1, rect[3]], COLOURDIVIDER))
    addtext(commands, rect[0] + PAD, rect[1] + PAD, label, COLOURTEXT, FONTSIZE, rect)
    width = measuretext(summary, SMALLFONT, FONT)
    addtext(commands, rect[0] + rect[2] - PAD - width, rect[1] + PAD, summary, COLOURMUTED, SMALLFONT, rect)

    if not values:
        return

    graphleft = rect[0] + PAD
    graphtop = rect[1] + PAD + ROWH
    graphwidth = max(1, rect[2] - (PAD * 2))
    graphheight = max(1, rect[3] - (PAD * 2) - ROWH)
    if len(values) == 1:
        value = max(0.0, min(100.0, float(values[0])))
        y = graphtop + graphheight - int((value / 100.0) * graphheight)
        commands.append(linenode(graphleft, y, graphleft + graphwidth, y, COLOURTEXT, rect))
        return

    step = graphwidth / float(len(values) - 1)

    for index in range(1, len(values)):

        x1 = graphleft + int(round((index - 1) * step))
        x2 = graphleft + int(round(index * step))
        y1 = graphtop + graphheight - int((max(0.0, min(100.0, values[index - 1])) / 100.0) * graphheight)
        y2 = graphtop + graphheight - int((max(0.0, min(100.0, values[index])) / 100.0) * graphheight)
        commands.append(linenode(x1, y1, x2, y2, COLOURTEXT, rect))


def buildperformance(commands):

    left = NAVW + PAD
    top = HEADERH + TOOLBARH + PAD
    width = max(1, WINW - NAVW - (PAD * 2))
    height = max(1, WINH - STATUSH - top - PAD)
    gap = PAD
    graphheight = max(scale(105), (height - (gap * 2)) // 3)
    system = SNAPSHOT.get('system', {})
    cpu = formatpercent(system.get('cpu_percent'))
    gpu = formatpercent(system.get('gpu_percent'))
    gpuname = str(system.get('gpu_name', 'graphics processor')).strip() or 'graphics processor'
    memoryused = system.get('memory_used_bytes')
    memorytotal = system.get('memory_total_bytes')
    memory = f'{formatbytes(memoryused)} / {formatbytes(memorytotal)}'
    graphnodes(commands, [left, top, width, graphheight], HISTORYCPU, 'CPU', cpu)
    graphnodes(
        commands,
        [left, top + graphheight + gap, width, graphheight],
        HISTORYGPU,
        'GPU',
        f'{gpu}  {fittext(gpuname, max(scale(120), width // 2), SMALLFONT)}',
    )
    graphnodes(
        commands,
        [left, top + ((graphheight + gap) * 2), width, graphheight],
        HISTORYMEMORY,
        'memory',
        memory,
    )


def buildstatus(commands):

    global ACTIONMAP

    ACTIONMAP = {}
    y = WINH - STATUSH
    rect = [0, y, WINW, STATUSH]
    commands.append(rectnode(rect, COLOURSTATUS))
    commands.append(rectnode([0, y, WINW, 1], COLOURDIVIDER))
    message = statusmessage()

    if message:
        addtext(commands, PAD, y + max(0, (STATUSH - SMALLFONT) // 2), fittext(message, WINW - (PAD * 2), SMALLFONT), COLOURERROR if STATUSERROR else COLOURTEXT, SMALLFONT, rect)
        return

    x = PAD

    for label, action, enabled in actionitems():

        width = measuretext(label, SMALLFONT, FONT) + (PAD * 2)
        button = [x, y, width, STATUSH]
        addtext(commands, x + PAD, y + max(0, (STATUSH - SMALLFONT) // 2), label, COLOURTEXT if enabled else COLOURMUTED, SMALLFONT, button)

        if enabled:
            ACTIONMAP[action] = button

        x += width + PAD

    operations = SNAPSHOT.get('operations', {})
    starting = sum(
        1 for entry in operations.values()
        if str(entry.get('state', 'running')).casefold() == 'starting'
    )
    count = max(0, len(operations) - starting)
    summary = f'{count} running'

    if starting:
        summary += f'  {starting} starting'

    if not ONLINE:
        summary = LASTERROR or 'operations server offline'

    width = measuretext(summary, SMALLFONT, FONT)
    addtext(commands, max(x, WINW - PAD - width), y + max(0, (STATUSH - SMALLFONT) // 2), fittext(summary, WINW - x - PAD, SMALLFONT), COLOURMUTED if ONLINE else COLOURERROR, SMALLFONT, rect)


def buildconfirm(commands):

    if not CONFIRM:
        return

    width = min(scale(520), WINW - (PAD * 2))
    height = scale(190)
    left = max(PAD, (WINW - width) // 2)
    top = max(PAD, (WINH - height) // 2)
    rect = [left, top, width, height]
    commands.append(rectnode(rect, COLOURSTATUS))
    commands.append(rectnode([left, top, width, 1], COLOURTEXT))
    commands.append(rectnode([left, top + height - 1, width, 1], COLOURTEXT))
    commands.append(rectnode([left, top, 1, height], COLOURTEXT))
    commands.append(rectnode([left + width - 1, top, 1, height], COLOURTEXT))
    entry = selectedentry() or {}
    title = 'force kill operation' if CONFIRM.get('force') else 'kill operation'
    message = f'{entry.get("name", "operation")}  PID {entry.get("pid", SELECTED)}'
    resources = entry.get('resources', {})
    children = int(resources.get('children', 0) or 0)
    detail = f'This will signal the operation and {children} child process{"es" if children != 1 else ""}.'
    addtext(commands, left + PAD, top + PAD, title, COLOURERROR if CONFIRM.get('force') else COLOURTEXT, TITLEFONT, rect)
    addtext(commands, left + PAD, top + PAD + ROWH + scale(12), fittext(message, width - (PAD * 2), FONTSIZE), COLOURTEXT, FONTSIZE, rect)
    addtext(commands, left + PAD, top + PAD + (ROWH * 2) + scale(12), fittext(detail, width - (PAD * 2), SMALLFONT), COLOURMUTED, SMALLFONT, rect)
    addtext(commands, left + PAD, top + height - PAD - SMALLFONT, 'Enter to confirm   Esc to cancel', COLOURMUTED, SMALLFONT, rect)


def buildcontext(commands):

    global CONTEXTMAP

    CONTEXTMAP = {}

    if not CONTEXT or selectedentry() is None:
        return

    items = [
        ('details', 'details', True),
        ('read log', 'log', True),
        ('kill', 'kill', VIEW == 'operations'),
        ('force kill', 'forcekill', VIEW == 'operations'),
    ]
    width = scale(150)
    height = (len(items) * ROWH) + (PAD * 2)
    left = min(int(CONTEXT.get('x', 0)), max(PAD, WINW - width - PAD))
    top = min(int(CONTEXT.get('y', 0)), max(PAD, WINH - STATUSH - height - PAD))
    panel = [left, top, width, height]
    commands.append(rectnode(panel, COLOURSTATUS))
    commands.append(rectnode([left, top, width, 1], COLOURDIVIDER))
    commands.append(rectnode([left, top + height - 1, width, 1], COLOURDIVIDER))
    commands.append(rectnode([left, top, 1, height], COLOURDIVIDER))
    commands.append(rectnode([left + width - 1, top, 1, height], COLOURDIVIDER))
    y = top + PAD

    for label, identifier, enabled in items:

        rect = [left + 1, y, width - 2, ROWH]
        addtext(commands, left + PAD, y + max(0, (ROWH - SMALLFONT) // 2), label, COLOURTEXT if enabled else COLOURMUTED, SMALLFONT, rect)

        if enabled:
            CONTEXTMAP[identifier] = rect

        y += ROWH


def buildscene():

    commands = [rectnode([0, 0, WINW, WINH], COLOURBG)]
    buildheader(commands)
    buildnav(commands)
    buildtoolbar(commands)

    if VIEW == 'performance':
        buildperformance(commands)

    else:
        buildcolumns(commands)
        buildtable(commands)
        builddetails(commands)

    buildstatus(commands)
    buildcontext(commands)
    buildconfirm(commands)
    return commands


def submitscene():

    global GRAPHICSSCENE

    if not GRAPHICSSTATE.get('available') or not WINID:
        return False

    try:

        commands = buildscene()
        managedmarkdamage(GRAPHICSSTATE, [0, 0, WINW, WINH], bounds=(WINW, WINH))
        managedsubmit(GRAPHICSSTATE, graphicssend, WINID, commands)

        if GRAPHICSSTATE.get('pending'):
            GRAPHICSSCENE = commands

        return bool(GRAPHICSSTATE.get('available'))

    except Exception as error:

        retained = manageddisable(GRAPHICSSTATE, f'operations centre scene failed {error}')
        log(f'managed graphics disabled {error}')
        return bool(retained)


def graphicsresponse(message):

    global GRAPHICSSCENE

    handled = managedresponse(GRAPHICSSTATE, message)

    if not GRAPHICSSTATE.get('available'):
        GRAPHICSSCENE = []
        redraw()

    return handled



# CPU graphics functions
def drawcpu():

    try:

        commands = buildscene()
        fillrectfast(0, 0, WINW, WINH, COLOURBG)

        for command in commands[1:]:

            kind = command.get('kind')

            if kind == 'rectangle':

                x, y, width, height = command.get('rect', [0, 0, 0, 0])
                fillrectfast(x, y, width, height, int(command.get('color', COLOURBG)))

            elif kind == 'line':

                points = command.get('points', [0, 0, 0, 0])
                drawline(points[0], points[1], points[2], points[3], int(command.get('color', COLOURTEXT)))

            elif kind == 'text':

                size = int(command.get('size', FONTSIZE))
                y = int(command.get('y', 0)) - int(baseline(0, size))
                drawtextttf(
                    int(command.get('x', 0)),
                    y,
                    str(command.get('text', '')),
                    int(command.get('color', COLOURTEXT)),
                    size,
                    FONT,
                )

        gfxpresent()

        if WINID and not GRAPHICSSTATE.get('available'):
            sendws({'op': 'DAMAGE', 'winid': WINID, 'rect': [0, 0, WINW, WINH]})

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

    if GRAPHICSSTATE.get('available'):
        submitscene()
    else:
        drawcpu()



# window server functions
def connectws():

    global WSOCK

    WSOCK = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    WSOCK.connect(WINDOWSOCK)
    WSOCK.setblocking(False)
    SEL.register(WSOCK, selectors.EVENT_READ | selectors.EVENT_WRITE)


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


def createwindow():

    sendws({
        'op': 'CREATE_WINDOW',
        'role': APPROLE,
        'title': APPNAME,
        'current': windowname(),
        'path': APPPATH,
        'w': scale(BASEWINW),
        'h': scale(BASEWINH),
        'x': 110,
        'y': 85,
        'pid': os.getpid(),
    })


def mapwindow():

    sendws({'op': 'MAP', 'winid': WINID})


def windowcurrent():

    if WINID:
        sendws({
            'op': 'WINDOW_CURRENT_SET',
            'winid': WINID,
            'current': windowname(),
        })


def windowname():

    return {
        'operations': 'running operations',
        'performance': 'system performance',
        'history': 'completed operations',
        'startup': 'startup operations',
    }.get(VIEW, VIEW)


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
    initbuffer(BUF, WINW, WINH)


def resized(message):

    global WINW, WINH, BUF

    if GRAPHICSSTATE.get('available') and WINID:
        managedclear(GRAPHICSSTATE, graphicssend, WINID)

    WINW = max(1, int(message.get('w', WINW)))
    WINH = max(1, int(message.get('h', WINH)))
    BUF = message.get('buffer', BUF)
    rebind()
    clampscroll()
    redraw()


def handlews(message):

    global WINID, BUF, WINW, WINH, SCREENW, SCREENH, NEEDWINDOW, RUNNING, FOCUSED
    global COLUMNRESIZING, COLUMNRESIZENEXT

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
        initttffont(FONT, SMALLFONT)
        initttffont(FONT, TITLEFONT)
        redraw()
        return

    if operation == 'RESIZED':
        resized(message)
        return

    if operation == 'FOCUS':
        FOCUSED = bool(message.get('focused', message.get('value', True)))

        if not FOCUSED and COLUMNRESIZING is not None:
            COLUMNRESIZING = None
            COLUMNRESIZENEXT = None
            setpointercursor('arrow')
            savesettings()

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
def setview(view):

    global VIEW, SELECTED, SCROLL, CONFIRM, CONTEXT

    if view not in VIEWS:
        return

    VIEW = view
    SELECTED = None
    SCROLL = 0
    CONFIRM = None
    CONTEXT = None
    windowcurrent()
    savesettings()
    redraw()


def selectmove(delta):

    global SELECTED, SCROLL

    rows = currentrows()

    if not rows:
        SELECTED = None
        return

    current = 0

    for index, entry in enumerate(rows):

        if str(entry.get('pid')) == str(SELECTED):
            current = index
            break

    current = max(0, min(len(rows) - 1, current + int(delta)))
    SELECTED = str(rows[current].get('pid'))

    displayindex = current

    for index, item in enumerate(tableitems()):

        if str(item.get('pid')) == str(SELECTED):
            displayindex = index
            break

    if displayindex < SCROLL:
        SCROLL = displayindex

    if displayindex >= SCROLL + visiblerows():
        SCROLL = displayindex - visiblerows() + 1

    redraw()


def togglepause():

    global PAUSED

    PAUSED = not PAUSED
    setstatus('updates paused' if PAUSED else 'updates resumed')

    if not PAUSED:
        queuesample(opsrequest({'op': 'LIST', 'resources': True, 'completed': True}))


def sortcolumn(column):

    global SORTCOLUMN, SORTREVERSE, SCROLL

    if SORTCOLUMN == column:
        SORTREVERSE = not SORTREVERSE
    else:
        SORTCOLUMN = column
        SORTREVERSE = column in ('cpu', 'gpu', 'memory', 'runtime', 'pid')

    SCROLL = 0
    savesettings()
    redraw()


def action(action):

    global CONFIRM

    if action == 'kill':
        CONFIRM = {'force': False}

    elif action == 'forcekill':
        CONFIRM = {'force': True}

    elif action == 'log':
        openlog()

    elif action == 'pause':
        togglepause()

    elif action == 'refresh':
        queuesample(opsrequest({'op': 'LIST', 'resources': True, 'completed': True}))

    redraw()


def keyinput(message):

    global RUNNING, SEARCHING, SEARCHTEXT, SEARCHCARETPOS, CONFIRM, SCROLL

    state = str(message.get('state', 'down')).lower()

    if state not in ('down', 'repeat'):
        return

    key = str(message.get('key', '')).upper()
    mods = message.get('mods', {})
    control = bool(mods.get('ctrl') or mods.get('control'))
    shift = bool(mods.get('shift'))

    if CONFIRM:

        if key == 'ESC':
            CONFIRM = None
            redraw()

        elif key in ('ENTER', 'RETURN'):
            force = bool(CONFIRM.get('force'))
            CONFIRM = None
            killselected(force=force)

        return

    if control and key == 'F':
        SEARCHING = True
        redraw()
        return

    if key == 'ESC':

        if SEARCHING:
            SEARCHING = False
            redraw()
            return

        RUNNING = False
        return

    if SEARCHING:

        if key == 'BACKSPACE' and SEARCHCARETPOS > 0:
            SEARCHTEXT = SEARCHTEXT[:SEARCHCARETPOS - 1] + SEARCHTEXT[SEARCHCARETPOS:]
            SEARCHCARETPOS -= 1
            SCROLL = 0
            redraw()

        elif key == 'DELETE' and SEARCHCARETPOS < len(SEARCHTEXT):
            SEARCHTEXT = SEARCHTEXT[:SEARCHCARETPOS] + SEARCHTEXT[SEARCHCARETPOS + 1:]
            SCROLL = 0
            redraw()

        elif key == 'LEFT':
            SEARCHCARETPOS = max(0, SEARCHCARETPOS - 1)
            redraw()

        elif key == 'RIGHT':
            SEARCHCARETPOS = min(len(SEARCHTEXT), SEARCHCARETPOS + 1)
            redraw()

        elif key in ('ENTER', 'RETURN'):
            SEARCHING = False
            redraw()

        return

    if key == 'UP':
        selectmove(-1)

    elif key == 'DOWN':
        selectmove(1)

    elif key == 'PAGEUP':
        selectmove(-visiblerows())

    elif key == 'PAGEDOWN':
        selectmove(visiblerows())

    elif key == 'HOME':
        SCROLL = 0
        selectmove(-1000000)

    elif key == 'END':
        selectmove(1000000)

    elif key == 'DELETE' and VIEW == 'operations':
        CONFIRM = {'force': bool(shift)}
        redraw()

    elif key in ('ENTER', 'RETURN') and selectedentry() is not None:
        redraw()

    elif key == 'F5':
        queuesample(opsrequest({'op': 'LIST', 'resources': True, 'completed': True}))

    elif key == 'SPACE':
        togglepause()


def textinput(message):

    global SEARCHTEXT, SEARCHCARETPOS, SCROLL

    if not SEARCHING:
        return

    text = str(message.get('text', ''))

    if not text or any(ord(character) < 32 for character in text):
        return

    SEARCHTEXT = (SEARCHTEXT[:SEARCHCARETPOS] + text + SEARCHTEXT[SEARCHCARETPOS:])[:256]
    SEARCHCARETPOS = min(len(SEARCHTEXT), SEARCHCARETPOS + len(text))
    SCROLL = 0
    redraw()


def scrollinput(message):

    global SCROLL

    if VIEW == 'performance':
        return

    try:
        delta = int(message.get('dy', message.get('delta', 0)))
    except Exception:
        delta = 0

    if delta == 0:
        return

    SCROLL += -3 if delta > 0 else 3
    clampscroll()
    redraw()


def pointermotion(message):

    global COLUMNWIDTHS

    x = int(message.get('x', 0))
    y = int(message.get('y', 0))
    updatecolumncursor(x, y)

    if COLUMNRESIZING is None or COLUMNRESIZENEXT is None:
        return

    leftminimum = scale(80 if COLUMNRESIZING == 'name' else 42)
    rightminimum = scale(80 if COLUMNRESIZENEXT == 'name' else 42)
    delta = int(x) - int(COLUMNRESIZESTARTX)
    delta = max(leftminimum - int(COLUMNRESIZESTARTW), delta)
    delta = min(int(COLUMNRESIZENEXTW) - rightminimum, delta)
    leftwidth = int(COLUMNRESIZESTARTW) + delta
    rightwidth = int(COLUMNRESIZENEXTW) - delta
    factor = max(0.01, float(UISCALE))
    COLUMNWIDTHS[COLUMNRESIZING] = max(42, min(900, int(round(leftwidth / factor))))
    COLUMNWIDTHS[COLUMNRESIZENEXT] = max(42, min(900, int(round(rightwidth / factor))))
    redraw()


def pointerbutton(message):

    global SELECTED, SEARCHING, SEARCHCARETPOS, LASTCLICK, CONFIRM, CONTEXT
    global COLUMNRESIZING, COLUMNRESIZENEXT, COLUMNRESIZESTARTX
    global COLUMNRESIZESTARTW, COLUMNRESIZENEXTW

    pressed = message.get('pressed')

    if pressed is None:
        pressed = str(message.get('state', 'down')).lower() == 'down'

    x = int(message.get('x', 0))
    y = int(message.get('y', 0))

    if not pressed:

        if COLUMNRESIZING is not None:
            COLUMNRESIZING = None
            COLUMNRESIZENEXT = None
            updatecolumncursor(x, y)
            savesettings()
            redraw()

        return

    button = int(message.get('button', 1))

    if CONFIRM:
        return

    resize = columnresizehit(x, y)

    if resize is not None and button == 1:

        freezecolumnwidths()
        layout = {column['id']: column['rect'] for column in columns()}
        COLUMNRESIZING, COLUMNRESIZENEXT = resize
        COLUMNRESIZESTARTX = x
        COLUMNRESIZESTARTW = int(layout[COLUMNRESIZING][2])
        COLUMNRESIZENEXTW = int(layout[COLUMNRESIZENEXT][2])
        setpointercursor('resize_h')
        return

    if CONTEXT:

        for identifier, rect in CONTEXTMAP.items():

            if pointin(x, y, rect):
                CONTEXT = None

                if identifier != 'details':
                    action(identifier)

                else:
                    redraw()

                return

        CONTEXT = None

    if pointin(x, y, HEADERMAP.get('search', [-1, -1, 0, 0])):
        SEARCHING = True
        SEARCHCARETPOS = len(SEARCHTEXT)
        redraw()
        return

    SEARCHING = False

    for view, rect in NAVMAP.items():

        if pointin(x, y, rect):
            setview(view)
            return

    for column, rect in COLUMNMAP.items():

        if pointin(x, y, rect):
            sortcolumn(column)
            return

    items = tableitems()

    for index, rect in ROWMAP.items():

        if not pointin(x, y, rect) or index >= len(items):
            continue

        entry = items[index]
        SELECTED = str(entry.get('pid'))
        now = time.monotonic()

        if button == 3:
            CONTEXT = {'x': x, 'y': y}

        elif LASTCLICK.get('row') == SELECTED and now - float(LASTCLICK.get('time', 0.0)) < 0.45:
            CONTEXT = {'x': x, 'y': y}

        LASTCLICK = {'row': SELECTED, 'time': now}
        redraw()
        return

    for identifier, rect in ACTIONMAP.items():

        if pointin(x, y, rect):
            action(identifier)
            return

    SELECTED = None
    CONTEXT = None
    redraw()



# diagnostic functions
def graphicsdiagnostic():

    global WINW, WINH, BUF, SNAPSHOT, VIEW, SELECTED, HISTORYCPU, HISTORYGPU, HISTORYMEMORY
    global SETTINGSPATH, SORTCOLUMN, SORTREVERSE, COLUMNRESIZING, COLUMNRESIZENEXT
    global COLUMNCURSORMODE

    result = {'version': VERSION, 'passed': False, 'checks': {}, 'errors': []}
    root = f'/.ephemeral/operations-centre-diagnostic-{os.getpid()}'
    original = {
        'WINW': WINW,
        'WINH': WINH,
        'BUF': BUF,
        'SNAPSHOT': SNAPSHOT,
        'VIEW': VIEW,
        'SELECTED': SELECTED,
        'SETTINGSPATH': SETTINGSPATH,
        'SORTCOLUMN': SORTCOLUMN,
        'SORTREVERSE': SORTREVERSE,
        'HISTORYCPU': list(HISTORYCPU),
        'HISTORYGPU': list(HISTORYGPU),
        'HISTORYMEMORY': list(HISTORYMEMORY),
        'COLUMNWIDTHS': dict(COLUMNWIDTHS),
        'COLUMNRESIZING': COLUMNRESIZING,
        'COLUMNRESIZENEXT': COLUMNRESIZENEXT,
        'COLUMNCURSORMODE': COLUMNCURSORMODE,
        'OUTBUF': bytes(OUTBUF),
    }

    try:

        if (COLOURBG, COLOURTEXT, COLOURSTATUS, COLOURDIVIDER, COLOURMUTED, COLOURERROR) != (
            0x000000,
            0xEFEFEF,
            0x242424,
            0x3A3A3A,
            0x6A6A6A,
            0xFF0000,
        ):
            raise RuntimeError('operations centre palette does not match Array')

        result['checks']['array_palette'] = True
        os.makedirs(root, mode=0o700, exist_ok=False)
        bufferpath = os.path.join(root, 'window.bgra')
        SETTINGSPATH = os.path.join(root, 'settings.json')
        WINW = 1120
        WINH = 700
        VIEW = 'operations'
        SELECTED = '101'
        SORTCOLUMN = 'name'
        SORTREVERSE = False
        HISTORYCPU = [10.0, 30.0, 20.0]
        HISTORYGPU = [15.0, 35.0, 25.0]
        HISTORYMEMORY = [40.0, 42.0, 41.0]
        SNAPSHOT = {
            'status': 'ok',
            'version': 2,
            'sampled': time.time(),
            'sample_ms': 500,
            'system': {
                'cpu_percent': 20.0,
                'gpu_percent': 35.0,
                'gpu_name': 'diagnostic GPU',
                'gpu_backend': 'opengl',
                'gpu_accelerated': True,
                'memory_total_bytes': 16 * 1024 * 1024 * 1024,
                'memory_used_bytes': 8 * 1024 * 1024 * 1024,
            },
            'operations': {
                '101': {
                    'pid': 101,
                    'identity': '101:77',
                    'name': 'diagnostic operation',
                    'state': 'running',
                    'mode': 'front',
                    'user': 'master',
                    'script': '/diagnostic.py',
                    'args': ['sample'],
                    'started': time.time() - 65,
                    'log': '/diagnostic.log',
                    'resources': {
                        'cpu_percent': 12.5,
                        'gpu_percent': 7.5,
                        'memory_bytes': 128 * 1024 * 1024,
                        'peak_memory_bytes': 140 * 1024 * 1024,
                        'threads': 3,
                        'children': 2,
                        'read_bytes': 4096,
                        'write_bytes': 8192,
                    },
                },
                '102': {
                    'name': 'alpha front operation',
                    'mode': 'front',
                    'resources': {},
                },
                '103': {
                    'name': 'zulu front operation',
                    'mode': 'front',
                    'resources': {},
                },
                '104': {
                    'name': 'bravo behind operation',
                    'mode': 'behind',
                    'resources': {},
                },
                '105': {
                    'name': 'zulu behind operation',
                    'mode': 'behind',
                    'resources': {},
                },
                '106': {
                    'name': 'hidden starting operation',
                    'state': 'starting',
                    'mode': 'front',
                    'resources': {},
                },
            },
            'completed': {},
        }

        with open(bufferpath, 'wb') as stream:
            stream.truncate(WINW * WINH * 4)

        BUF = bufferpath
        initbuffer(BUF, WINW, WINH)
        initttffont(FONT, FONTSIZE)
        scene = buildscene()

        if not scene or scene[0].get('rect') != [0, 0, WINW, WINH] or scene[0].get('color') != COLOURBG:
            raise RuntimeError('operations centre did not build a complete opaque scene')

        texts = [str(command.get('text', '')) for command in scene if command.get('kind') == 'text']

        for expected in ('operations centre', 'diagnostic operation', '12.5%', '7.5%', 'details'):

            if not any(expected in value for value in texts):
                raise RuntimeError(f'operations centre scene is missing {expected}')

        for expected in ('kill', 'force kill'):

            if expected not in texts:
                raise RuntimeError(f'operations centre action bar is missing {expected}')

        result['checks']['operations_scene'] = True
        result['checks']['kill_actions'] = True

        if 'gpu' not in COLUMNMAP or 'GPU' not in texts:
            raise RuntimeError('operations centre scene is missing the GPU column')

        result['checks']['gpu_column'] = True

        if SORTCOLUMN != 'name' or SORTREVERSE:
            raise RuntimeError('operations did not default to alphabetical sort')

        result['checks']['default_sort'] = {'column': SORTCOLUMN, 'descending': SORTREVERSE}
        grouped = tableitems()

        if any(entry.get('name') == 'hidden starting operation' for entry in grouped):
            raise RuntimeError('starting GUI operation was visible before window readiness')

        result['checks']['starting_operations_hidden'] = True
        grouping = [
            entry.get('_operation_group', 'gap' if '_operation_group_gap' in entry else entry.get('name'))
            for entry in grouped
        ]

        if grouping != [
            'front',
            'alpha front operation',
            'diagnostic operation',
            'zulu front operation',
            'gap',
            'behind',
            'bravo behind operation',
            'zulu behind operation',
        ]:
            raise RuntimeError(f'operations were not grouped by mode within operation sort: {grouping}')

        SORTCOLUMN = 'cpu'
        ungrouped = tableitems()

        if len(ungrouped) != 5 or any('_operation_group' in entry for entry in ungrouped):
            raise RuntimeError('operations remained grouped for a non-operation sort')

        SORTCOLUMN = 'name'
        result['checks']['operation_groups'] = True
        behindindex = next(
            index
            for index, entry in enumerate(grouped)
            if entry.get('_operation_group') == 'behind'
        )
        behindrect = rowrect(behindindex)
        lastfrontindex = max(
            index
            for index, entry in enumerate(grouped[:behindindex])
            if '_operation_group' not in entry and '_operation_group_gap' not in entry
        )
        lastfrontrect = rowrect(lastfrontindex)

        if behindrect[1] - (lastfrontrect[1] + lastfrontrect[3]) != ROWH:
            raise RuntimeError('operations centre did not leave a one-row gap between operation groups')

        result['checks']['operation_group_gap'] = True
        separatorpoints = [
            behindrect[0],
            behindrect[1],
            behindrect[0] + behindrect[2],
            behindrect[1],
        ]
        groupseparators = [
            command
            for command in scene
            if (
                command.get('kind') == 'line'
                and command.get('color') == COLOURDIVIDER
                and command.get('points') == separatorpoints
                and command.get('clip') == [0, 0, WINW, WINH]
            )
        ]

        if len(groupseparators) != 1:
            raise RuntimeError('operations centre did not separate the front entries from the behind header')

        result['checks']['operation_group_separator'] = True
        layout = columns()
        firstcolumn = layout[0]['rect']
        beforefirst = int(firstcolumn[2])
        beforesecond = int(layout[1]['rect'][2])
        separatorx = int(firstcolumn[0]) + beforefirst
        separatory = int(firstcolumn[1]) + (int(firstcolumn[3]) // 2)
        OUTBUF.clear()
        pointerbutton({'x': separatorx, 'y': separatory, 'button': 1, 'pressed': True})
        pointermotion({'x': separatorx + scale(20), 'y': separatory})
        resizedlayout = columns()
        pointerbutton({'x': separatorx + scale(20), 'y': separatory, 'button': 1, 'pressed': False})

        if (
            int(resizedlayout[0]['rect'][2]) <= beforefirst
            or int(resizedlayout[1]['rect'][2]) >= beforesecond
            or b'resize_h' not in bytes(OUTBUF)
        ):
            raise RuntimeError('operations centre column resizing or resize cursor did not work')

        result['checks']['column_resize'] = {
            'left_before': beforefirst,
            'left_after': int(resizedlayout[0]['rect'][2]),
            'right_before': beforesecond,
            'right_after': int(resizedlayout[1]['rect'][2]),
            'cursor': 'resize_h',
        }
        drawcpu()
        result['checks']['cpu_fallback'] = os.path.getsize(bufferpath) == WINW * WINH * 4
        VIEW = 'performance'
        performance = buildscene()
        performancetexts = [
            str(command.get('text', ''))
            for command in performance
            if command.get('kind') == 'text'
        ]

        if 'GPU' not in performancetexts or not any('diagnostic GPU' in value for value in performancetexts):
            raise RuntimeError('performance scene is missing GPU telemetry')

        result['checks']['gpu_performance'] = True

        lines = [command for command in performance if command.get('kind') == 'line']

        if not lines:
            raise RuntimeError('performance scene did not render graph lines')

        for command in lines:

            points = command.get('points')

            if (
                not isinstance(points, list)
                or len(points) != 4
                or points == [0, 0, 0, 0]
                or not all(isinstance(value, int) for value in points)
                or not (0 <= points[0] < WINW and 0 <= points[2] <= WINW)
                or not (0 <= points[1] < WINH and 0 <= points[3] < WINH)
            ):
                raise RuntimeError('performance graph line does not match the managed graphics contract')

        result['checks']['performance_graphs'] = True
        result['checks']['performance_line_contract'] = True

        if not drawcpu():
            raise RuntimeError('CPU fallback did not render performance graphs')

        result['checks']['performance_cpu_fallback'] = True
        HISTORYCPU = [25.0]
        HISTORYGPU = [30.0]
        HISTORYMEMORY = [50.0]
        immediate = buildscene()
        immediatelines = [
            command
            for command in immediate
            if command.get('kind') == 'line' and command.get('color') == COLOURTEXT
        ]

        if len(immediatelines) != 3 or not all(
            command.get('points', [0, 0, 0, 0])[0] < command.get('points', [0, 0, 0, 0])[2]
            for command in immediatelines
        ):
            raise RuntimeError('performance graphs did not render their first sample')

        result['checks']['performance_first_sample'] = True

        if len(scene) > 1024 or len(performance) > 1024 or len(immediate) > 1024:
            raise RuntimeError('operations centre exceeded the managed command budget')

        result['checks']['command_budget'] = max(len(scene), len(performance), len(immediate))
        result['passed'] = True

    except Exception as error:
        result['errors'].append(str(error))

    finally:

        WINW = original['WINW']
        WINH = original['WINH']
        BUF = original['BUF']
        SNAPSHOT = original['SNAPSHOT']
        VIEW = original['VIEW']
        SELECTED = original['SELECTED']
        SETTINGSPATH = original['SETTINGSPATH']
        SORTCOLUMN = original['SORTCOLUMN']
        SORTREVERSE = original['SORTREVERSE']
        HISTORYCPU = original['HISTORYCPU']
        HISTORYGPU = original['HISTORYGPU']
        HISTORYMEMORY = original['HISTORYMEMORY']
        COLUMNWIDTHS.clear()
        COLUMNWIDTHS.update(original['COLUMNWIDTHS'])
        COLUMNRESIZING = original['COLUMNRESIZING']
        COLUMNRESIZENEXT = original['COLUMNRESIZENEXT']
        COLUMNCURSORMODE = original['COLUMNCURSORMODE']
        OUTBUF.clear()
        OUTBUF.extend(original['OUTBUF'])
        shutil.rmtree(root, ignore_errors=True)

    print(json.dumps(result, sort_keys=True, separators=(',', ':')))
    return 0 if result['passed'] else 1



# core functions
def cleanup():

    SAMPLESTOP.set()
    savesettings()

    try:

        if WSOCK is not None:
            setpointercursor('arrow')
            flushws()
            WSOCK.close()

    except Exception:
        pass


def terminate(signum, frame):

    global RUNNING

    RUNNING = False


def initapp():

    global NEEDWINDOW

    loadsettings()
    startsampler()
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

    samplepump()
    paint()
    flushws()
    mapwindow()
    sendws({'op': 'RAISE', 'winid': WINID})
    sendws({'op': 'FOCUS_SET', 'winid': WINID})
    flushws()


def pulse():

    global RUNNING, SEARCHLASTBLINK

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

                elif operation == 'TEXT':
                    textinput(message)

                elif operation == 'SCROLL':
                    scrollinput(message)

                elif operation == 'POINTER_MOTION':
                    pointermotion(message)

                elif operation == 'POINTER_BUTTON':
                    pointerbutton(message)

        if mask & selectors.EVENT_WRITE:
            flushws()

    samplepump()
    statusmessage()

    blink = (int(time.monotonic() * 2) % 2) == 0

    if SEARCHING and blink != SEARCHLASTBLINK:
        SEARCHLASTBLINK = blink
        redraw()

    if not SEARCHING:
        SEARCHLASTBLINK = None

    if GRAPHICSSTATE.get('available') and not managedtick(GRAPHICSSTATE):

        if WINID:
            sendws({'op': 'GRAPHICS_CLEAR', 'winid': WINID})

        redraw()

    paint()
    flushws()


def main():

    atexit.register(cleanup)
    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)
    initapp()

    while RUNNING:
        pulse()

    flushws()
    return 0


# execute main
if __name__ == '__main__':

    if len(sys.argv) > 1 and sys.argv[1] == 'graphics-diagnostic':
        raise SystemExit(graphicsdiagnostic())

    raise SystemExit(main())
