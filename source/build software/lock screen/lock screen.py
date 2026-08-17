#!"/the one/software/python/bin/python" -B

"""
lockscreen.py

lock screen for The One OS.
"""



## imports
import os
import re
import sys
import time
import json
import socket
import select

# t1os build path
sys.path.insert(0, '/the one/build')

# t1os modules
from reign.reign import currenttime, timestamp
from GODDESS.GODDESS import formatlog
from graphics.graphics import init as initfb
from graphics.graphics import *



## globals

# paths and protocol
TIMEFILE = '/the one/settings/time/atreyan.txt'
WS_SOCK = '/.ephemeral/windowserver/accept.sock'
STATEBASE = '/.ephemeral/windowserver/state'
WS_FB_NAME = 'fb.size'
ACCELERATEDREADYPATH = '/.ephemeral/windowserver/state/accelerated-lockscreen-ready.json'
LOCKSCREENREADYPATH = '/.ephemeral/windowserver/state/lockscreen-ready.json'
LOGFILE = '/the one/logs/lock screen.py.log'
LIFECYCLEBASE = '/.ephemeral/lock screen'
LIFECYCLESTATE = os.path.join(LIFECYCLEBASE, 'state.json')
POSTHANDOFFSTATE = os.path.join(LIFECYCLEBASE, 'post-handoff-ready.json')
DEBUGLOCKSCREEN = False
WINDOWCREATETIMEOUT = 60.0

# visual constants
BGCOLOR = 0x000000
TEXTCOLOR = 0xEFEFEF
LEFT_PAD_FRAC = 0.035
BOTTOM_PAD_FRAC = 0.09
REFRESH_HZ = 2.0
INPUT_POLL_HZ = 120.0
TIME_SCALE = 0.13
DATE_SCALE = 0.05

# font sources
TTF_CANDIDATES = [
    '/the one/resources/fonts/cambria.ttf'
]

# windowserver state
_ws = None
_winid = None
_bufpath = None
DESKTOPW = 1920
DESKTOPH = 1080
_screenw = DESKTOPW
_screenh = DESKTOPH
_wsbuf = ''
_wsqueue = []
_windowserverid = ''
_windowserverpid = 0

# graphics
_gfx_ready = False
_directfb = False
_last_timerect = None
_last_daterect = None
_graphicscaps = {}
_graphicsavailable = False
_graphicsactive = False
_graphicspending = False
_graphicsfailure = ''
_graphicsframes = 0
_graphicsmaximumcommands = 0
_graphicslastcommands = 0
_graphicsbuildtotalms = 0.0
_graphicsbuildmaximumms = 0.0
_graphicsbuildcount = 0
_graphicsmode = str(os.environ.get('T1OS_LOCKSCREEN_GRAPHICS', 'cpu')).strip().lower()
_graphicscpuoverride = _graphicsmode not in ('managed', 'gpu', 'on', '1', 'true')
_graphicsstate = managedstate(cpu=_graphicscpuoverride)

# font state
_ttf_ready = False
_fontpath = None
_font_time_size = 0
_font_date_size = 0

# time caching
_cached_time_raw = None
_cached_time_mtime = 0.0
_last_timestr = None
_last_datestr = None
_next_tick = 0.0
_unlocknotbefore = 0.0

# lifecycle flags
_running = True
_lifecyclelaststate = ''
_lastdiagnostic = ''



# logging functions
def lifecyclewrite(state, detail=''):

    global _lifecyclelaststate

    temporary = f'{LIFECYCLESTATE}.{os.getpid()}.new'

    try:

        os.makedirs(LIFECYCLEBASE, mode=0o700, exist_ok=True)

        with open(temporary, 'w', encoding='utf-8') as stream:

            json.dump({
                'format': 1,
                'pid': int(os.getpid()),
                'state': str(state),
                'detail': str(detail),
            }, stream, sort_keys=True, separators=(',', ':'))
            stream.flush()
            os.fsync(stream.fileno())

        os.replace(temporary, LIFECYCLESTATE)
        _lifecyclelaststate = str(state).strip().lower()
        return True

    except Exception:

        try:
            os.unlink(temporary)
        except Exception:
            pass

        return False


def logline(msg):

    global _lastdiagnostic

    # Normal boots avoid per-frame diagnostic writes, but first-frame failures
    # must remain recoverable after a headless or black-screen boot.
    diagnostic = str(msg).lower()

    if not DEBUGLOCKSCREEN and not any(
        token in diagnostic
        for token in ('failed', 'error', 'exception', 'returned false', 'unavailable')
    ):

        return

    _lastdiagnostic = str(msg).strip()


    # build line
    line = formatlog('lock screen', msg) + '\n'


    # The supervised launch owns the fixed root log and drains this process's
    # stdout into it.  The lock screen itself runs as the desktop uid and must
    # never need write access to the sealed system log tier merely to report an
    # initialization failure.
    print(line, end='', flush=True)

def logexc(tag, e):

    try:

        # stringify exception
        etype = type(e).__name__

        msg = str(e)

    except Exception:

        etype = 'Exception'
        msg = 'unknown'


    # write error line
    logline(f'{tag} {etype} {msg}')

def logstate(tag):


    # snapshot critical state
    logline(f'{tag} winid={_winid} bufpath={_bufpath} screen={_screenw}x{_screenh} ttf={_ttf_ready}')

def logstamp():

    try:

        # local timestamp without any t1os dependencies
        return timestamp()

    except Exception:

        value = time.localtime()
        year = value.tm_year - 2020
        hour = value.tm_hour % 12 or 12
        ampm = 'AM' if value.tm_hour < 12 else 'PM'
        return f'[{value.tm_mday:02}:{value.tm_mon:02}:{year}AE {hour}:{value.tm_min:02}:{value.tm_sec:02} {ampm}]'


def safeint(x, default):

    try:

        # convert to integer
        return int(x)

    except (TypeError, ValueError):

        # conversion failure
        return default

    except Exception:

        # other errors
        return default


def clamp(v, lo, hi):

    try:

        # ensure numeric comparison
        if v < lo:

            return lo

        if v > hi:

            return hi

        return v

    except Exception:

        # fallback to lower bound
        return lo


# time and date functions
def readatreyanraw():

    global _cached_time_raw
    global _cached_time_mtime

    try:

        # stat time file for mtime caching
        st = os.stat(TIMEFILE)
        mtime = st.st_mtime

    except FileNotFoundError:

        return ''

    except PermissionError:

        return ''

    except Exception:

        return ''


    # return cached value if unchanged
    if _cached_time_raw is not None and _cached_time_mtime == mtime:

        return _cached_time_raw

    try:

        # open time file
        with open(TIMEFILE, 'r', encoding='utf-8', errors='strict') as f:

            for line in f:

                # strip non-printable
                s = ''.join(ch for ch in line.strip() if ch.isprintable())

                if s:

                    _cached_time_raw = s
                    _cached_time_mtime = mtime

                    return _cached_time_raw


        _cached_time_raw = ''
        _cached_time_mtime = mtime

        return ''

    except FileNotFoundError:

        return ''

    except PermissionError:

        return ''

    except UnicodeDecodeError:

        return ''

    except Exception:

        return ''


def parseatreyanclock(raw):

    try:

        # empty raw guard
        if not raw:

            return ''

        # match "H:MM am" or "HH:MM PM"
        m = re.match(r'\s*([0-9]{1,2}:[0-9]{2})\s*([AaPp][Mm])\b', raw)

        if not m:

            return ''

        # return hh:mm
        hhmm = m.group(1)

        return f'{hhmm}'

    except Exception:

        return ''


def fallbackclock():

    try:

        # local fallback
        lt = time.localtime()

        hh = lt.tm_hour % 12

        if hh == 0:

            hh = 12

        mm = f'{lt.tm_min:02d}'

        return f'{hh}:{mm}'

    except Exception:

        return '--:--'


def formattoday():
    try:

        # use the same named timezone and system clock as reign
        t = currenttime()

        # day and month maps
        days = [
            'Monday',
            'Tuesday',
            'Wednesday',
            'Thursday',
            'Friday',
            'Saturday',
            'Sunday'
        ]

        months = [
            'January',
            'February',
            'March',
            'April',
            'May',
            'June',
            'July',
            'August',
            'September',
            'October',
            'November',
            'December'
        ]

        # bounds safety
        if t.tm_wday < 0 or t.tm_wday > 6:

            return ''

        if t.tm_mon < 1 or t.tm_mon > 12:

            return ''

        dayname = days[t.tm_wday]
        monthname = months[t.tm_mon - 1]

        return f'{dayname}, {t.tm_mday} {monthname}'

    except Exception:

        return ''


def buildstrings():

    try:

        # read raw atreyan time
        raw = readatreyanraw()

    except Exception:

        raw = ''

    try:

        # parse formatted clock
        timestr = parseatreyanclock(raw)

    except Exception:

        timestr = ''

    try:

        # fallback if parse failed
        if not timestr:

            timestr = fallbackclock()

    except Exception:

        timestr = '--:--'

    try:

        # format date
        datestr = formattoday()

    except Exception:

        datestr = ''

    return timestr, datestr


# windowserver ipc functions
def wsconnect():

    global _ws

    try:

        # close existing socket if present
        if _ws is not None:

            _ws.close()

            _ws = None

    except Exception:

        # ignore close errors
        _ws = None


    try:

        # create unix socket
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

        # connect to windowserver
        s.connect(WS_SOCK)

        # set non-blocking mode
        s.setblocking(False)

        _ws = s

        return True

    except FileNotFoundError:

        # windowserver socket missing
        _ws = None

        return False

    except ConnectionRefusedError:

        # windowserver not accepting
        _ws = None

        return False

    except Exception:

        # other connection failure
        _ws = None

        return False


def wssend(obj):

    try:

        # ensure socket exists
        if _ws is None:

            return False

        # encode json line
        line = json.dumps(obj) + '\n'

        # send data
        _ws.sendall(line.encode('utf-8'))

        return True

    except BrokenPipeError:

        # connection dropped
        return False

    except Exception:

        # other send failure
        return False


def wsrecv(timeout):

    global _wsbuf
    global _wsqueue

    try:

        # ensure socket exists
        if _ws is None:

            logline('wsrecv socket none')

            return None

    except Exception:

        return None


    # return queued packets first
    if _wsqueue:

        try:

            pkt = _wsqueue.pop(0)

            return pkt

        except Exception:

            _wsqueue = []

    try:

        # wait for data
        r, _, _ = select.select([_ws], [], [], timeout)

        if not r:

            return None

    except Exception as e:

        logexc('wsrecv select', e)

        return None

    try:

        # receive bytes
        data = _ws.recv(4096)

        if not data:

            logline('wsrecv empty read')

            return None

    except Exception as e:

        logexc('wsrecv recv', e)

        return None

    try:

        # append to stream buffer
        chunk = data.decode('utf-8', errors='ignore')

        _wsbuf = _wsbuf + chunk

    except Exception as e:

        logexc('wsrecv decode', e)

        return None

    try:

        # parse complete newline-delimited json packets
        while True:

            try:

                idx = _wsbuf.find('\n')

            except Exception:

                break

            if idx < 0:

                break

            try:

                line = _wsbuf[:idx]

                _wsbuf = _wsbuf[idx + 1:]

            except Exception:

                break


            line = line.strip()

            if not line:

                continue

            try:

                pkt = json.loads(line)

                _wsqueue.append(pkt)

            except json.JSONDecodeError as e:

                logexc('wsrecv json decode', e)

                logline(f'wsrecv raw {line[:200]}')

                continue

            except Exception as e:

                logexc('wsrecv json parse', e)

                continue

    except Exception as e:

        logexc('wsrecv parse loop', e)

        return None

    try:

        # return first parsed packet, if any
        if _wsqueue:

            try:

                pkt = _wsqueue.pop(0)

                return pkt

            except Exception:

                _wsqueue = []

                return None

        return None

    except Exception:

        return None


def wshello():

    global _screenw, _screenh, _graphicscaps, _windowserverid, _windowserverpid

    try:

        # send hello packet
        ok = wssend({
            'op': 'HELLO'
        })

        if not ok:

            return False

    except Exception:

        return False

    try:

        # wait for welcome reply (consume it so wscreate doesn't read it)
        t0 = time.time()

        while True:

            # timeout guard
            if time.time() - t0 > 1.0:

                return False

            # attempt to read a packet
            reply = wsrecv(0.2)

            if reply is None:

                continue

            # accept welcome
            if reply.get('op') == 'WELCOME':

                _windowserverid = str(reply.get('server', ''))
                _windowserverpid = safeint(reply.get('windowserver_pid'), 0)

                try:

                    fb = reply.get('fb', {})

                    sw = safeint(fb.get('w'), 0)

                    sh = safeint(fb.get('h'), 0)

                    if sw > 0 and sh > 0:

                        _screenw = sw
                        _screenh = sh

                except Exception:

                    pass

                try:

                    # retain the advertised managed graphics capabilities
                    _graphicscaps = dict(reply.get('graphics', {}))

                except Exception:

                    _graphicscaps = {}

                graphicsconfigure(_graphicscaps)

                return True

            # ignore any other packets during hello
            continue

    except Exception:

        return False


def wscreate(w, h):

    global _winid, _bufpath

    requestedw = safeint(w, 0)

    requestedh = safeint(h, 0)

    try:

        # send create request
        ok = wssend({
            'op': 'CREATE_WINDOW',
            'w': w,
            'h': h,
            'x': 0,
            'y': 0,
            'title': 'lock screen',
            'role': 'lockscreen'
        })

        if not ok:

            return False

        # wait for WINDOW_CREATED without losing framebuffer changes which race
        # the lock-screen surface into existence
        deadline = time.monotonic() + WINDOWCREATETIMEOUT

        while True:

            if time.monotonic() >= deadline:

                return False

            reply = wsrecv(0.2)

            if reply is None:

                continue

            try:

                op = reply.get('op')

            except Exception:

                continue

            if op == 'WINDOW_CREATED':

                try:

                    _winid = reply.get('winid')
                    _bufpath = reply.get('buffer')

                except Exception:

                    return False

                if _winid is None or not _bufpath:

                    return False

                if _screenw != requestedw or _screenh != requestedh:

                    if not wsresize(_winid, _screenw, _screenh):

                        return False

                    if not waitbufferready(_bufpath, _screenw, _screenh):

                        return False

                return True

            if op == 'FB_SIZE':

                notefbsize(reply.get('w'), reply.get('h'))

                continue

            if op == 'ERROR':

                code = str(reply.get('code', 'unknown'))[:64]

                detail = str(reply.get('detail', ''))[:512]

                logline(
                    f'wscreate server error code={code} detail={detail}'
                )

                return False

            continue

    except Exception:

        return False


def wsmap(winid):

    try:

        # send map request
        return wssend({
            'op': 'MAP',
            'winid': winid
        })

    except Exception:

        return False


def wsfocus(winid, timeout=0.75):

    global _wsqueue
    deferred = []

    try:

        # Do not declare the lock screen ready merely because the focus request
        # entered the socket. WindowServer acknowledges after setfocus(), which
        # closes the short race where the first Space/Enter still went to the
        # previously focused surface.
        if not wssend({
            'op': 'FOCUS_SET',
            'winid': winid
        }):
            return False

        deadline = time.monotonic() + max(0.05, float(timeout))
        while time.monotonic() < deadline:

            reply = wsrecv(min(0.02, max(0.0, deadline - time.monotonic())))

            if reply is None:
                continue

            if (
                str(reply.get('op', '')) == 'FOCUS'
                and safeint(reply.get('winid'), 0) == safeint(winid, 0)
                and str(reply.get('state', '')) == 'in'
            ):
                _wsqueue = deferred + _wsqueue
                return True

            # Preserve every unrelated packet, including an activation key
            # that raced the acknowledgement, for the normal run loop.
            deferred.append(reply)

        _wsqueue = deferred + _wsqueue
        return False

    except Exception:

        _wsqueue = deferred + _wsqueue
        return False


def wsdamage(winid, rect):

    try:

        # send damage notification
        return wssend({
            'op': 'DAMAGE',
            'winid': winid,
            'rect': rect
        })

    except Exception:

        return False


def wsclose():

    global _ws


    # close socket
    if _ws is not None:

        _ws.close()

    _ws = None


def wssubscribe(types):

    wantsfbsize = 'fbsize' in types

    sawok = False

    sawfbsize = not wantsfbsize

    try:

        # send subscribe request
        ok = wssend({
            'op': 'SUBSCRIBE',
            'types': types
        })

        if not ok:

            return False

    except Exception:

        return False

    try:

        # Windowserver sends OK followed by the current FB_SIZE. Consume both so
        # CREATE_WINDOW cannot be issued with stale WELCOME dimensions.
        t0 = time.time()

        while True:

            if time.time() - t0 > 0.75:

                return sawok

            reply = wsrecv(0.05)

            if reply is None:

                continue

            if reply.get('op') == 'OK':

                sawok = True

                if sawfbsize:

                    return True

                continue

            if reply.get('op') == 'FB_SIZE':

                notefbsize(reply.get('w'), reply.get('h'))

                sawfbsize = True

                if sawok:

                    return True

                continue

            if reply.get('op') == 'ERROR':

                return False

            continue

    except Exception:

        return True


def wsresize(winid, w, h):

    try:

        # send resize request
        return wssend({
            'op': 'RESIZE',
            'winid': int(winid),
            'w': int(w),
            'h': int(h)
        })

    except Exception:

        return False


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


def notefbsize(w, h):

    global _screenw, _screenh, _last_timerect, _last_daterect, _last_timestr, _last_datestr

    sw = safeint(w, 0)

    sh = safeint(h, 0)

    if sw < 1 or sh < 1:

        return False

    changed = sw != _screenw or sh != _screenh

    _screenw = sw

    _screenh = sh

    if changed:

        _last_timerect = None

        _last_daterect = None

        _last_timestr = None

        _last_datestr = None

    return changed


def applyfbsize(w, h):

    global _screenw, _screenh, _gfx_ready, _last_daterect, _last_timestr, _last_datestr

    changed = notefbsize(w, h)

    if not changed and (_directfb or _gfx_ready):

        return False

    if _directfb:

        try:

            computefonts()

            initfonts()

        except Exception:

            pass

        return True

    if _winid is None or not _bufpath:

        return False

    try:

        if not wsresize(_winid, _screenw, _screenh):

            return False

    except Exception:

        return False

    if not waitbufferready(_bufpath, _screenw, _screenh):

        logline(f'buffer did not grow for framebuffer {_screenw}x{_screenh}')

        return False

    try:

        initbuffer(_bufpath, _screenw, _screenh)

        _gfx_ready = True

    except Exception:

        _gfx_ready = False

        return False

    try:

        computefonts()

        initfonts()

    except Exception:

        pass

    try:

        renderframe(force=True)

    except Exception:

        pass

    return True


# screen and font sizing functions
def getfbsizedimensions():

    try:

        p = os.path.join(STATEBASE, WS_FB_NAME)

        with open(p, 'r') as f:

            data = f.read().strip()

        w, h = data.split('x', 1)

        sw = safeint(w, 0)
        sh = safeint(h, 0)

        if sw > 0 and sh > 0:

            return sw, sh

    except Exception:

        pass

    return DESKTOPW, DESKTOPH


def readfbsize():

    global _screenw, _screenh

    _screenw, _screenh = getfbsizedimensions()

    return True


def computefonts():

    global _font_time_size
    global _font_date_size

    try:

        # compute time font size
        tsize = int(_screenh * TIME_SCALE)

        if tsize < 48:

            tsize = 48

        # compute date font size
        dsize = int(_screenh * DATE_SCALE)

        if dsize < 16:

            dsize = 16

        _font_time_size = tsize
        _font_date_size = dsize

        return True

    except Exception:

        _font_time_size = 0
        _font_date_size = 0

        return False


def initfonts():

    global _ttf_ready
    global _fontpath

    _ttf_ready = False
    _fontpath = None

    try:

        # ensure font sizes are computed
        if _font_time_size <= 0 or _font_date_size <= 0:

            return False

        # try font candidates
        for path in TTF_CANDIDATES:

            try:

                # set a default face in graphics (graphics keeps it globally)
                initttffont(path, _font_time_size)

                # remember the chosen font path for later calls
                _fontpath = path

                _ttf_ready = True

                return True

            except FileNotFoundError:

                continue

            except PermissionError:

                continue

            except Exception:

                continue

        return False

    except Exception:

        _ttf_ready = False
        _fontpath = None

        return False


# managed graphics functions
def graphicssyncstate():

    global _graphicscaps, _graphicsavailable, _graphicsactive, _graphicspending
    global _graphicsfailure, _graphicsframes, _graphicsmaximumcommands, _graphicslastcommands

    _graphicscaps = dict(_graphicsstate.get('capabilities', {}))
    _graphicsavailable = bool(_graphicsstate.get('available', False))
    _graphicsactive = bool(_graphicsstate.get('active', False))
    _graphicspending = bool(_graphicsstate.get('pending', False))
    _graphicsfailure = str(_graphicsstate.get('failure', ''))
    _graphicsframes = int(_graphicsstate.get('frames', 0))
    _graphicsmaximumcommands = int(_graphicsstate.get('maximum_commands', 0))
    _graphicslastcommands = int(_graphicsstate.get('last_commands', 0))


def graphicsconfigure(capabilities):

    managedconfigure(
        _graphicsstate,
        capabilities,
        required=('rectangle', 'text'),
        cpu=_graphicscpuoverride or not any(os.path.isfile(path) for path in TTF_CANDIDATES),
    )

    graphicssyncstate()


def graphicsdamage():

    try:

        if not _directfb and _winid is not None:
            wsdamage(_winid, [0, 0, int(_screenw), int(_screenh)])

    except Exception:

        pass


def graphicsrestorecpu():

    try:

        if not _gfx_ready:
            return False

        timestr, datestr = buildstrings()
        drawbackground(None)
        drawstrings(timestr, datestr)
        present()

        if not _directfb:
            commitdamage([[0, 0, int(_screenw), int(_screenh)]])

        return True

    except Exception:

        graphicsdamage()
        return False


def graphicsdisable(reason, clear=True):

    manageddisable(_graphicsstate, reason)

    try:

        if clear and _ws is not None and _winid is not None:
            wssend({'op': 'GRAPHICS_CLEAR', 'winid': int(_winid)})

    except Exception:

        pass

    graphicssyncstate()
    graphicsrestorecpu()


def graphicsresponse(msg):

    try:

        if _winid is not None and 'winid' in msg and int(msg.get('winid', 0)) != int(_winid):
            return False

    except Exception:

        return False
    before = bool(_graphicsstate.get('available'))
    handled = managedresponse(_graphicsstate, msg)
    graphicssyncstate()

    if before and not _graphicsstate.get('available'):

        try:

            if msg.get('code') != 'graphics_clear_failed' and _ws is not None and _winid is not None:
                wssend({'op': 'GRAPHICS_CLEAR', 'winid': int(_winid)})

        except Exception:

            pass

        graphicsrestorecpu()

    return bool(handled)


def graphicstexty(y, size):

    try:

        face = getttfface(_fontpath)

        if face is None:
            return int(y)

        face.set_pixel_sizes(0, int(size))
        ascender = int(face.size.ascender >> 6)
        return int(y) + int(size) - ascender

    except Exception:

        return int(y)


def graphicsbuildscene(timestr, datestr):

    global _graphicsbuildtotalms, _graphicsbuildmaximumms, _graphicsbuildcount

    started = time.monotonic_ns()
    width = max(1, int(_screenw))
    height = max(1, int(_screenh))
    clip = [0, 0, width, height]
    commands = [{
        'kind': 'rectangle',
        'rect': [0, 0, width, height],
        'color': int(BGCOLOR),
        'clip': list(clip),
    }]

    try:

        left = int(width * LEFT_PAD_FRAC)
        bottompad = int(height * BOTTOM_PAD_FRAC)
        timey, datey, _ = layout(left, bottompad)

        if timestr:
            commands.append({
                'kind': 'text',
                'x': int(left),
                'y': graphicstexty(timey, _font_time_size),
                'text': str(timestr),
                'size': int(_font_time_size),
                'font': str(_fontpath),
                'color': int(TEXTCOLOR),
                'clip': list(clip),
            })

        if datestr:
            commands.append({
                'kind': 'text',
                'x': int(left),
                'y': graphicstexty(datey, _font_date_size),
                'text': str(datestr),
                'size': int(_font_date_size),
                'font': str(_fontpath),
                'color': int(TEXTCOLOR),
                'clip': list(clip),
            })

    finally:

        elapsed = (time.monotonic_ns() - started) / 1000000.0
        _graphicsbuildtotalms += elapsed
        _graphicsbuildmaximumms = max(_graphicsbuildmaximumms, elapsed)
        _graphicsbuildcount += 1

    return commands


def graphicspump(timestr=None, datestr=None):

    wasavailable = bool(_graphicsstate.get('available'))

    if not managedtick(_graphicsstate):

        if wasavailable and _ws is not None and _winid is not None:

            wssend({'op': 'GRAPHICS_CLEAR', 'winid': int(_winid)})
            graphicsrestorecpu()

        graphicssyncstate()
        return False

    if not _graphicsstate.get('available') or _ws is None or _winid is None:
        return False

    if _graphicsstate.get('pending') or not _graphicsstate.get('need_submit'):

        graphicssyncstate()
        return bool(_graphicsstate.get('active'))

    if timestr is None or datestr is None:

        try:

            timestr, datestr = buildstrings()

        except Exception:

            return bool(_graphicsstate.get('active'))

    commands = graphicsbuildscene(timestr, datestr)

    if not commands or commands[0].get('rect') != [0, 0, int(_screenw), int(_screenh)]:

        graphicsdisable('managed scene does not contain a complete background')
        return False

    before = bool(_graphicsstate.get('available'))
    managedsubmit(_graphicsstate, wssend, int(_winid), commands)

    if before and not _graphicsstate.get('available'):

        wssend({'op': 'GRAPHICS_CLEAR', 'winid': int(_winid)})
        graphicsrestorecpu()

    graphicssyncstate()
    return bool(_graphicsstate.get('active'))


def graphicspresent(rects, timestr, datestr):

    if not _graphicsstate.get('available'):
        return False

    for rect in rects or [[0, 0, int(_screenw), int(_screenh)]]:

        managedmarkdamage(
            _graphicsstate,
            rect,
            bounds=(int(_screenw), int(_screenh)),
        )

    return graphicspump(timestr, datestr)


def graphicswaitinitial(timeout=0.5):

    deadline = time.monotonic() + max(0.05, float(timeout))

    while _graphicsstate.get('pending') and time.monotonic() < deadline:

        msg = wsrecv(0.02)

        if not msg:
            continue

        op = str(msg.get('op', ''))

        if op in ('GRAPHICS_COMMITTED', 'GRAPHICS_CLEARED') or (op == 'ERROR' and str(msg.get('code', '')).startswith('graphics_')):

            graphicsresponse(msg)
            continue

        if op == 'FB_SIZE':

            applyfbsize(msg.get('w'), msg.get('h'))

    if _graphicsstate.get('pending'):

        managedtick(_graphicsstate, timeout=max(0.1, float(timeout)))
        graphicssyncstate()

        if not _graphicsstate.get('available'):

            try:

                wssend({'op': 'GRAPHICS_CLEAR', 'winid': int(_winid)})

            except Exception:

                pass

            graphicsdamage()

    return bool(_graphicsstate.get('active'))


def lockscreenreceiptphysicallyverified(state):

    if not isinstance(state, dict):
        return False

    backend = str(state.get('backend', '')).strip().lower()

    if backend == 'opengl':
        proof = state.get('presentation_proof')
        return (
            state.get('hardware_accelerated') is True
            and state.get('full_coverage') is True
            and str(state.get('renderer', '')).strip()
            and int(state.get('frame_sequence', 0)) > 0
            and isinstance(proof, dict)
            and proof.get('verified') is True
            and proof.get('scanout') is True
            and proof.get('nonblack') is True
            and proof.get('contrast') is True
        )

    if backend not in ('framebuffer', 'kms-framebuffer'):
        return False

    proof = state.get('presentation_proof')
    common = (
        state.get('hardware_accelerated') is False
        and state.get('full_coverage') is True
        and int(state.get('frame_sequence', 0)) > 0
        and isinstance(proof, dict)
        and proof.get('verified') is True
        and proof.get('scanout') is True
        and proof.get('nonblack') is True
    )

    if backend == 'kms-framebuffer':
        vblank = proof.get('vblank_sequence', {})
        boundary = proof.get('presentation_boundary')
        physicalboundary = bool(
            (
                boundary == 'drm-crtc-sequence'
                and isinstance(vblank, dict)
                and vblank.get('advanced') is True
            )
            or (
                str(state.get('drm_driver', '')).strip().lower()
                in ('virtio_gpu', 'vmwgfx')
                and boundary in (
                    'virtio-resource-flush', 'vmwgfx-dirtyfb-flush'
                )
                and (
                    (str(state.get('drm_driver', '')).strip().lower()
                     == 'virtio_gpu'
                     and boundary == 'virtio-resource-flush')
                    or
                    (str(state.get('drm_driver', '')).strip().lower()
                     == 'vmwgfx'
                     and boundary == 'vmwgfx-dirtyfb-flush')
                )
                and isinstance(vblank, dict)
                and vblank.get('unsupported') is True
                and proof.get('dirty_status') == 'complete'
                and int(proof.get('present_sequence', 0)) >= 2
            )
            or (
                str(state.get('drm_driver', '')).strip().lower()
                == 'nvidia-drm'
                and boundary == 'nvidia-continuous-scanout'
                and isinstance(vblank, dict)
                and vblank.get('unsupported') is True
                and int(vblank.get('errno') or 0) == 95
                and proof.get('dirty_status') == 'unsupported:38'
                and proof.get('flush_status')
                == 'not-required:drm-ioctl-boundary'
                and int(proof.get('present_sequence', 0)) >= 2
                and int(proof.get('modeset_sequence', 0)) > 0
            )
        )
        return (
            common
            and proof.get('connector_connected') is True
            and proof.get('connector_routed') is True
            and proof.get('connector_link_status') != 'bad'
            and physicalboundary
            and proof.get('write_committed') is True
            and proof.get('mode_matches') is True
            and proof.get('readback') is False
            and proof.get('readback_skipped')
            == 'write-combined-device-mapping'
        )

    firmwareproof = bool(
        proof.get('readback') is True
        and proof.get('legacy_firmware_framebuffer') is True
        and proof.get('firmware_framebuffer_boot') is True
    )
    vblank = proof.get('vblank_sequence', {})
    boundary = proof.get('presentation_boundary')
    nativeboundary = bool(
        (
            boundary == 'drm-crtc-sequence'
            and isinstance(vblank, dict)
            and vblank.get('advanced') is True
        )
        or (
            proof.get('legacy_driver_family') == 'virtio'
            and boundary == 'virtio-fbdev-pan'
            and isinstance(vblank, dict)
            and vblank.get('unsupported') is True
        )
    )
    nativeproof = bool(
        proof.get('readback') is False
        and proof.get('readback_skipped')
        == 'native-drm-fbdev-write-combined-mapping'
        and proof.get('legacy_console_owned') is True
        and proof.get('legacy_pan_committed') is True
        and proof.get('legacy_owner_connected') is True
        and nativeboundary
        and proof.get('connector_link_status') != 'bad'
    )
    return bool(
        common
        and proof.get('legacy_page_zero') is True
        and (firmwareproof or nativeproof)
    )


def waitacceleratedpresentation(timeout=12.0):

    accelerated = bool(_graphicscaps.get('accelerated', False))

    deadline = time.monotonic() + max(0.1, float(timeout))

    while time.monotonic() < deadline:

        try:

            with open(LOCKSCREENREADYPATH, 'r', encoding='utf-8') as stream:
                state = json.load(stream)

            common = (
                state.get('role') == 'lockscreen'
                and int(state.get('windowserver_pid', 0)) == int(_windowserverpid)
                and str(state.get('server', '')) == str(_windowserverid)
                and state.get('gpu_failed') is False
                and bool(state.get('windows'))
                and state.get('topmost_role') == 'lockscreen'
                and int(state.get('topmost_window', 0)) in [
                    int(value) for value in state.get('windows', [])
                ]
            )

            ready = bool(
                common
                and lockscreenreceiptphysicallyverified(state)
                and (
                    (accelerated and state.get('backend') == 'opengl')
                    or (
                        not accelerated
                        and state.get('backend')
                        in ('framebuffer', 'kms-framebuffer')
                    )
                )
            )

            if ready:
                return True

        except (
            FileNotFoundError,
            json.JSONDecodeError,
            OSError,
            TypeError,
            ValueError,
        ):
            pass

        time.sleep(0.01)

    return False


# rendering functions
def rectclip(rect):

    try:

        x = int(rect[0])
        y = int(rect[1])
        w = int(rect[2])
        h = int(rect[3])

    except Exception:

        return None

    try:

        if w <= 0 or h <= 0:
            return None

        if x < 0:
            w += x
            x = 0

        if y < 0:
            h += y
            y = 0

        if x >= _screenw or y >= _screenh:
            return None

        if x + w > _screenw:
            w = _screenw - x

        if y + h > _screenh:
            h = _screenh - y

        if w <= 0 or h <= 0:
            return None

        return [x, y, w, h]

    except Exception:

        return None


def rectunion(a, b):

    try:

        if not a:
            return b

        if not b:
            return a

        ax, ay, aw, ah = a
        bx, by, bw, bh = b

        x0 = min(ax, bx)
        y0 = min(ay, by)

        x1 = max(ax + aw, bx + bw)
        y1 = max(ay + ah, by + bh)

        return [x0, y0, x1 - x0, y1 - y0]

    except Exception:

        return a if a else b


def measuretextrect(x, y, text, size):

    try:

        tw = measuretext(text, size, fontpath=_fontpath)

    except Exception:

        tw = 0

    try:

        yoff, lineh = ttflinebox(size, fontpath=_fontpath)

    except Exception:

        lineh = 0

    try:

        if tw <= 0 or lineh <= 0:
            return None

        pad = 6

        rx = int(x) - pad
        ry = int(y) + int(yoff) - pad
        rw = int(tw) + (pad * 2)
        rh = int(lineh) + (pad * 2)

        return [rx, ry, rw, rh]

    except Exception:

        return None


def builddamagerects(timestr, datestr):

    global _last_timerect
    global _last_daterect

    try:

        # compute padding
        left = int(_screenw * LEFT_PAD_FRAC)

        bottompad = int(_screenh * BOTTOM_PAD_FRAC)

    except Exception:

        left = 0
        bottompad = 0

    try:

        time_y, date_y, _ = layout(left, bottompad)

    except Exception:

        return []

    try:

        # current rects
        timerect = measuretextrect(left, time_y, timestr, _font_time_size)

        daterect = measuretextrect(left, date_y, datestr, _font_date_size)

    except Exception:

        timerect = None
        daterect = None


    # union current rects with previous rects to erase old glyphs cleanly
    timerect = rectunion(timerect, _last_timerect)

    daterect = rectunion(daterect, _last_daterect)

    try:

        # clip to screen
        out = []

        r1 = rectclip(timerect) if timerect else None

        r2 = rectclip(daterect) if daterect else None

        if r1:
            out.append(r1)

        if r2:
            out.append(r2)

    except Exception:

        out = []


    # update last rects for next tick (store unclipped is ok, but clipped is safer)
    _last_timerect = timerect

    _last_daterect = daterect

    return out


def commitdamage(rects):

    try:

        if _directfb:
            return True

    except Exception:

        return False

    try:

        if _winid is None:
            return False

    except Exception:

        return False

    try:

        # if we have explicit rects, send them; else full-window
        if rects:

            for r in rects:


                wsdamage(_winid, [int(r[0]), int(r[1]), int(r[2]), int(r[3])])

            return True

        else:

            wsdamage(_winid, [0, 0, _screenw, _screenh])

            return True

    except Exception:

        return False


def layout(left, bottompad):

    try:

        # measure line heights via graphics freetype helpers
        _, time_h = ttflinebox(_font_time_size, fontpath=_fontpath)

    except Exception:

        time_h = 0

    try:

        _, date_h = ttflinebox(_font_date_size, fontpath=_fontpath)

    except Exception:

        date_h = 0

    try:

        # spacing between time and date
        spacing = int(time_h * 0.35)

    except Exception:

        spacing = 0

    try:

        # compute vertical positions
        date_y = _screenh - bottompad - date_h

        time_y = date_y - spacing - time_h

        return time_y, date_y, spacing

    except Exception:

        return 0, 0, 0


def drawbackground(rects=None):

    try:

        if not _gfx_ready:
            return False

    except Exception:

        return False


    # first frame or forced redraw: full clear
    if not rects:

        clear(BGCOLOR)
        return True

    try:

        # partial clear using dirty rects
        for r in rects:


            x = int(r[0])
            y = int(r[1])
            w = int(r[2])
            h = int(r[3])


            fillrectfast(x, y, w, h, BGCOLOR)

        return True

    except Exception:

        return False


def drawstrings(timestr, datestr):

    try:

        # compute padding
        left = int(_screenw * LEFT_PAD_FRAC)

        bottompad = int(_screenh * BOTTOM_PAD_FRAC)

    except Exception:

        left = 0
        bottompad = 0

    try:

        # compute layout
        time_y, date_y, _ = layout(left, bottompad)

    except Exception:

        return False


    # draw time string
    drawtextttf(
        left,
        time_y,
        timestr,
        TEXTCOLOR,
        _font_time_size,
        fontpath=_fontpath
    )


    # draw date string
    drawtextttf(
        left,
        date_y,
        datestr,
        TEXTCOLOR,
        _font_date_size,
        fontpath=_fontpath
    )

    return True


def renderframe(force=False):

    global _last_timestr
    global _last_datestr
    global _last_timerect
    global _last_daterect

    try:

        # build current strings
        timestr, datestr = buildstrings()

    except Exception:

        return False

    # detect content change
    changed = False

    if timestr != _last_timestr or datestr != _last_datestr:

        changed = True

    # skip redraw if unchanged
    if not force and not changed:

        return True

    # redraw strategy
    rects = None

    if force:

        # establish the current text bounds for the next partial update
        builddamagerects(timestr, datestr)

        rects = [[0, 0, _screenw, _screenh]]

    elif changed:

        rects = builddamagerects(timestr, datestr)

    if (
        not _directfb
        and _graphicsstate.get('active')
        and _graphicsstate.get('managed_only')
        and graphicspresent(rects, timestr, datestr)
    ):

        _last_timestr = timestr
        _last_datestr = datestr
        return True

    try:

        ok = drawbackground(rects)

        if not ok:
            return False

    except Exception:

        return False

    # draw strings
    drawstrings(timestr, datestr)

    if _gfx_ready:

        present()

    if not _directfb:

        managed = graphicspresent(rects, timestr, datestr)

        if not managed:

            commitdamage(rects)

    _last_timestr = timestr

    _last_datestr = datestr

    return True


# input functions
def initinput():

    try:

        if _ws is None:

            return False

    except Exception:

        return False

    return True


def settlefbsize(timeout=0.2):

    deadline = time.monotonic() + max(0.05, float(timeout))

    try:

        wssend({'op': 'GET_FBSIZE'})

    except Exception:

        return

    while time.monotonic() < deadline:

        msg = wsrecv(min(0.02, max(0.0, deadline - time.monotonic())))

        if not msg:

            continue

        op = msg.get('op')

        if op == 'FB_SIZE':

            applyfbsize(msg.get('w'), msg.get('h'))

        elif op in ('GRAPHICS_COMMITTED', 'GRAPHICS_CLEARED') or (op == 'ERROR' and str(msg.get('code', '')).startswith('graphics_')):

            graphicsresponse(msg)


def unlockrequest(msg, winid=None):

    # A queued firmware/VM activation key must not make the process exit in
    # the narrow interval between publishing its verified first frame and
    # Startup observing that lifecycle state.  Events inside this grace
    # period are consumed but cannot unlock; visible interaction is unchanged
    # once the supervisor's 20 ms poll has crossed the barrier.
    if time.monotonic() < _unlocknotbefore:
        return False

    # Startup is the authority that removes the boot animation and verifies
    # physical presentation.  Do not accept an activation key until its
    # acknowledgement is bound to this exact lock-screen process.
    try:
        with open(POSTHANDOFFSTATE, 'r', encoding='utf-8') as stream:
            handoff = json.load(stream)
        if not (
            isinstance(handoff, dict)
            and handoff.get('format') == 1
            and handoff.get('state') == 'ready'
            and int(handoff.get('pid', 0)) == int(os.getpid())
            and handoff.get('boot_active') is False
            and handoff.get('physically_verified') is True
        ):
            return False
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        detail = (
            'post-handoff authorization unavailable '
            + type(error).__name__
            + ': '
            + str(error)
        )
        if _lastdiagnostic != detail:
            logline(detail)
        return False

    try:
        target = int(_winid if winid is None else winid)
        eventwin = int(msg.get('winid', 0))
    except Exception:
        return False

    if target <= 0 or eventwin != target:
        return False

    op = str(msg.get('op', ''))
    state = str(msg.get('state', ''))

    if op == 'KEY':
        key = str(msg.get('key', '')).strip().upper()
        return state == 'down' and key in ('SPACE', 'ENTER')

    if op == 'POINTER_BUTTON':
        try:
            return state == 'down' and int(msg.get('button', 0)) == 1
        except (TypeError, ValueError):
            return False

    return False


def pollunlock(timeout_s=None):

    try:

        if _ws is None:

            return False

    except Exception:

        return False

    try:

        if timeout_s is None:
            timeout_s = 1.0 / INPUT_POLL_HZ

        end = time.monotonic() + max(0.0, float(timeout_s))

    except Exception:

        return False

    while True:

        try:

            now = time.monotonic()

            if now >= end:

                return False

            timeout = end - now

        except Exception:

            return False

        try:

            msg = wsrecv(timeout)

        except Exception:

            return False

        try:

            if not msg:

                return False

        except Exception:

            return False


        if msg.get("op") == "FB_SIZE":

            try:

                applyfbsize(msg.get("w"), msg.get("h"))

            except Exception:

                pass

            continue

        if msg.get('op') in ('GRAPHICS_COMMITTED', 'GRAPHICS_CLEARED'):

            graphicsresponse(msg)
            continue

        if msg.get('op') == 'ERROR' and str(msg.get('code', '')).startswith('graphics_'):

            graphicsresponse(msg)
            continue

        if unlockrequest(msg):

            settlefbsize()

            return True


def draininput(ms):

    global _wsqueue

    # invalid ms guard
    if ms is None:

        return

    if ms <= 0:

        return

    if _ws is None:

        return

    end = time.time() + (ms / 1000.0)

    while True:

        if time.time() >= end:

            return

        # non-blocking drain
        msg = wsrecv(0.0)

        # An activation event addressed to this lock-screen window is not
        # stale input. Put it back at the head of the queue so pollunlock()
        # observes the user's first Space/Enter.
        if msg and unlockrequest(msg):

            _wsqueue.insert(0, msg)
            return

        time.sleep(0.001)

def initlock():

    global _running, _directfb, _gfx_ready, _screenw, _screenh
    global _unlocknotbefore

    logline('initlock entered')

    _directfb = False

    logline('initlock step wsconnect')

    try:

        ok = wsconnect()

    except Exception as e:

        logexc('initlock wsconnect exception', e)

        ok = False

    if not ok:

        logline('initlock windowserver unavailable -> direct framebuffer mode')

        logline('initlock step initfb')

        try:

            initfb()

        except Exception as e:

            logexc('initlock initfb exception', e)

            _gfx_ready = False

            return False


        logline('initlock step readfbsize')

        try:

            ok = readfbsize()

            if not ok:

                logline('initlock readfbsize failed')

                return False

        except Exception as e:

            logexc('initlock readfbsize exception', e)

            return False

        logline(f'initlock fb {_screenw}x{_screenh}')

        _gfx_ready = True

        _directfb = True

    else:

        logline('initlock step wshello')

        try:

            if not wshello():
                logline('initlock wshello failed')
                return False

        except Exception as e:

            logexc('initlock wshello exception', e)

            return False

        logline(f'initlock welcome fb {_screenw}x{_screenh}')

        logline('initlock step wssubscribe fbsize')

        try:

            wssubscribe(['fbsize'])

        except Exception as e:

            logexc('initlock wssubscribe exception', e)

        logline('initlock step wscreate')

        try:

            ok = wscreate(_screenw, _screenh)

            if not ok:

                logline('initlock wscreate failed')

                return False

        except Exception as e:

            logexc('initlock wscreate exception', e)

            return False

        logstate('initlock after create')

        logline('initlock step initbuffer')

        try:

            initbuffer(_bufpath, _screenw, _screenh)

            _gfx_ready = True

        except Exception as e:

            logexc('initlock initbuffer exception', e)

            _gfx_ready = False

            return False


        try:

            # Reconcile the state file without changing dimensions behind the
            # existing mapping.
            sw2, sh2 = getfbsizedimensions()

            if sw2 > 0 and sh2 > 0:

                if sw2 != _screenw or sh2 != _screenh:

                    if not applyfbsize(sw2, sh2):

                        raise RuntimeError('failed to reconcile initial framebuffer size')

        except Exception as e:

            logexc('initlock framebuffer reconcile exception', e)

            return False

    logline('initlock step computefonts')

    try:

        ok = computefonts()

        if not ok:

            logline('initlock computefonts failed')

            return False

    except Exception as e:

        logexc('initlock computefonts exception', e)

        return False

    logline(f'initlock fonts time={_font_time_size} date={_font_date_size}')

    logline('initlock step initfonts')

    try:

        ok = initfonts()

        if not ok:

            logline('initlock initfonts failed')

            return False

    except Exception as e:

        logexc('initlock initfonts exception', e)

        return False

    logline('initlock step initinput')

    try:

        ok = initinput()

        if not ok:

            logline('initlock initinput failed')

            return False

    except Exception as e:

        logexc('initlock initinput exception', e)

        return False

    logline('initlock step draininput')

    try:

        draininput(150)

    except Exception as e:

        logexc('initlock draininput exception', e)

    logline('initlock step first render')

    try:

        ok = renderframe(force=True)

        if not ok:

            logline('initlock first render returned false')

        else:

            logline('initlock first render ok')

    except Exception as e:

        logexc('initlock first render exception', e)

    if not _directfb:

        # do not expose the surface until both render paths contain a complete frame
        graphicswaitinitial()

        logline('initlock step wsmap')

        try:

            ok = wsmap(_winid)

            if not ok:

                logline('initlock wsmap failed')

                return False

        except Exception as e:

            logexc('initlock wsmap exception', e)

            return False

        logline('initlock step wsfocus')

        try:

            ok = wsfocus(_winid)

            if not ok:

                logline('initlock wsfocus failed')

                return False

        except Exception as e:

            logexc('initlock wsfocus exception', e)

            return False

        logline('initlock step accelerated presentation barrier')

        if not waitacceleratedpresentation():

            logline('initlock accelerated presentation barrier failed')

            return False

    _running = True
    _unlocknotbefore = time.monotonic() + 0.25

    # This is the visual handoff barrier. In accelerated mode WindowServer has
    # now completed the lock-screen KMS page flip and synchronized the GPU;
    # safe mode completes after its framebuffer presentation.
    lifecyclewrite('ready')

    logline('initlock ok')

    return True


def runlock():

    global _running, _next_tick

    logline('runlock entered')

    try:

        # initialise lockscreen
        ok = initlock()

        if not ok:

            detail = _lastdiagnostic or 'initialisation returned false'
            logline('runlock initlock returned false')
            lifecyclewrite(
                'failed',
                detail,
            )

            return

    except Exception as e:

        logexc('runlock initlock exception', e)
        lifecyclewrite('failed', f'{type(e).__name__}: {e}')

        return

    try:

        # Clock/date rendering is intentionally slow, but input must remain
        # interactive.  Keep a separate visual deadline instead of sleeping
        # the input loop until the next 2 Hz clock refresh.
        _next_tick = time.monotonic() + (1.0 / REFRESH_HZ)

    except Exception:

        _next_tick = 0.0

    while True:

        try:

            # stop if no longer running
            if not _running:

                break

        except Exception:

            break

        # Check input at interactive frequency even though the clock itself is
        # only redrawn at REFRESH_HZ. This removes the former 500 ms worst-case
        # delay that made the first few Space/Enter presses appear to be lost.
        if pollunlock(1.0 / INPUT_POLL_HZ):

            lifecyclewrite('unlocked', 'verified activation request')
            break

        # submit any scene coalesced while the previous commit was pending
        graphicspump()

        try:

            now = time.monotonic()

            if now < _next_tick:
                continue

            # Advance the slow visual clock without delaying input polling.
            _next_tick += (1.0 / REFRESH_HZ)

            if _next_tick <= now:
                _next_tick = now + (1.0 / REFRESH_HZ)

            ok = renderframe()

            if not ok:
                raise RuntimeError('render failed')

        except Exception:

            try:

                # attempt reconnect
                wsclose()

                time.sleep(0.2)

                ok = initlock()

                if not ok:

                    time.sleep(0.5)

                    continue

                # force redraw after recovery and restart the visual deadline
                renderframe(force=True)
                _next_tick = time.monotonic() + (1.0 / REFRESH_HZ)

            except Exception:

                time.sleep(0.5)

                continue

    # shutdown cleanly
    shutdown()


def shutdown():

    global _running, _last_timestr, _last_datestr

    _running = False

    # close windowserver connection
    wsclose()

    # reset runtime state
    _last_timestr = None

    _last_datestr = None


def graphicsdiagnostic():

    global _screenw, _screenh, _fontpath, _font_time_size, _font_date_size
    global _graphicsbuildtotalms, _graphicsbuildmaximumms, _graphicsbuildcount

    result = {
        'format': 1,
        'passed': False,
        'resolution': [2560, 1440],
        'checks': {},
        'performance': {},
        'errors': [],
    }

    try:

        _screenw = 2560
        _screenh = 1440
        _fontpath = TTF_CANDIDATES[0]
        computefonts()
        initttffont(_fontpath, _font_time_size)
        capabilities = {
            'version': 2,
            'accelerated': True,
            'managed_resources': True,
            'atomic_scene': True,
            'damage_regions': True,
            'commands': ['rectangle', 'image', 'text'],
            'command_limit': 1024,
            'text_limit': 1024,
            'damage_limit': 64,
        }
        managedconfigure(_graphicsstate, capabilities, required=('rectangle', 'text'), cpu=False)
        graphicssyncstate()

        if not _graphicsavailable:
            raise RuntimeError(f'managed graphics negotiation failed: {_graphicsfailure}')

        result['checks']['capability_negotiation'] = True
        _graphicsbuildtotalms = 0.0
        _graphicsbuildmaximumms = 0.0
        _graphicsbuildcount = 0
        scenes = []

        for _ in range(20):
            scenes.append(graphicsbuildscene('10:27 PM', '17:07:6AE'))

        scene = scenes[-1]

        if not scene or scene[0].get('kind') != 'rectangle' or scene[0].get('rect') != [0, 0, 2560, 1440]:
            raise RuntimeError('managed scene does not begin with an opaque full-screen background')

        if int(scene[0].get('color', -1)) != int(BGCOLOR):
            raise RuntimeError('managed background is not the lock-screen background colour')

        textcommands = [command for command in scene if command.get('kind') == 'text']

        if len(textcommands) != 2:
            raise RuntimeError('managed lock screen did not contain the time and date')

        if any(command.get('font') != _fontpath for command in textcommands):
            raise RuntimeError('managed lock-screen text did not use Cambria')

        if any(int(command.get('y', -1)) < 0 or int(command.get('y', 0)) >= _screenh for command in textcommands):
            raise RuntimeError('managed text baseline was outside the lock screen')

        result['checks']['opaque_background'] = True
        result['checks']['first_frame_complete'] = True
        result['checks']['cambria_baseline'] = True
        result['checks']['time_date_layout'] = True
        requests = []
        managedmarkdamage(_graphicsstate, [50, 1100, 700, 210], bounds=(_screenw, _screenh))
        managedmarkdamage(_graphicsstate, [50, 1320, 500, 80], bounds=(_screenw, _screenh))
        managedsubmit(_graphicsstate, lambda request: requests.append(request) or True, 81, scene)

        if len(requests) != 1 or requests[0].get('op') != 'GRAPHICS_SCENE':
            raise RuntimeError('managed helper did not submit one atomic scene')

        if len(requests[0].get('damage', [])) != 2:
            raise RuntimeError('managed helper did not preserve time and date damage')

        managedresponse(_graphicsstate, {
            'op': 'GRAPHICS_COMMITTED',
            'winid': 81,
            'count': len(scene),
            'batch': True,
            'accelerated': True,
        })
        graphicssyncstate()

        if not _graphicsactive or _graphicspending:
            raise RuntimeError('managed scene did not activate after acknowledgement')

        result['checks']['atomic_scene'] = {
            'messages': len(requests),
            'commands': len(scene),
            'damage': len(requests[0].get('damage', [])),
        }
        result['checks']['command_budget'] = {
            'commands': len(scene),
            'limit': int(_graphicsstate.get('command_limit', 0)),
        }

        _screenw = 800
        _screenh = 600

        if not notefbsize(2560, 1440) or _screenw != 2560 or _screenh != 1440:
            raise RuntimeError('lock-screen protocol did not preserve the final grow notification')

        result['checks']['shrink_grow_protocol_state'] = True

        if not unlockrequest({
                'op': 'KEY',
                'winid': 81,
                'key': 'SPACE',
                'state': 'down',
        }, winid=81):
            raise RuntimeError('Space did not advance the lock screen')

        if not unlockrequest({
                'op': 'KEY',
                'winid': 81,
                'key': 'ENTER',
                'state': 'down',
        }, winid=81):
            raise RuntimeError('Enter did not advance the lock screen')

        if (
                unlockrequest({
                    'op': 'KEY',
                    'winid': 81,
                    'key': 'A',
                    'state': 'down',
                }, winid=81)
                or unlockrequest({
                    'op': 'POINTER_MOTION',
                    'winid': 81,
                }, winid=81)
                or unlockrequest({
                    'op': 'KEY',
                    'winid': 82,
                    'key': 'ENTER',
                    'state': 'down',
                }, winid=81)
                or unlockrequest({
                    'op': 'POINTER_BUTTON',
                    'winid': 81,
                    'button': 1,
                    'state': 'up',
                }, winid=81)):
            raise RuntimeError('lock screen advanced for a non-activation event')

        if not unlockrequest({
                'op': 'POINTER_BUTTON',
                'winid': 81,
                'button': 1,
                'state': 'down',
        }, winid=81):
            raise RuntimeError('primary click did not advance the lock screen')

        result['checks']['session_activation_input'] = True

        fallback = managedstate(cpu=True)
        managedconfigure(fallback, capabilities, required=('rectangle', 'text'))

        if fallback.get('available') or fallback.get('active'):
            raise RuntimeError('CPU override did not disable managed graphics')

        missing = managedstate()
        managedconfigure(missing, {}, required=('rectangle', 'text'))

        if missing.get('available'):
            raise RuntimeError('missing capabilities did not select CPU fallback')

        rejected = managedstate()
        managedconfigure(rejected, capabilities, required=('rectangle', 'text'))
        rejected['winid'] = 82
        managedresponse(rejected, {'op': 'ERROR', 'winid': 82, 'code': 'graphics_scene_failed', 'detail': 'diagnostic'})

        if rejected.get('available') or rejected.get('active'):
            raise RuntimeError('managed error did not select CPU fallback')

        timedout = managedstate()
        managedconfigure(timedout, capabilities, required=('rectangle', 'text'))
        timedout['pending'] = True
        timedout['pending_at'] = time.monotonic() - 3.0
        managedtick(timedout, timeout=0.1)

        if timedout.get('available') or timedout.get('pending'):
            raise RuntimeError('managed commit timeout did not select CPU fallback')

        result['checks']['cpu_fallback'] = True
        result['checks']['missing_capability_fallback'] = True
        result['checks']['error_fallback'] = True
        result['checks']['timeout_fallback'] = True
        result['checks']['direct_framebuffer_fallback'] = True
        result['checks']['first_frame_before_map'] = True
        result['performance'] = {
            'average_scene_build_ms': round(_graphicsbuildtotalms / max(1, _graphicsbuildcount), 3),
            'maximum_scene_build_ms': round(_graphicsbuildmaximumms, 3),
            'maximum_commands': len(scene),
        }
        result['passed'] = True

    except Exception as e:

        result['errors'].append(str(e))

    return result


def graphicsdiagnosticcommand():

    result = graphicsdiagnostic()
    print(json.dumps(result, sort_keys=True, separators=(',', ':')))
    return 0 if result.get('passed') else 1


def main():

    global _lifecyclelaststate

    try:

        # boot marker
        lifecyclewrite('starting')
        logline('main entered')

        # run lockscreen
        runlock()

        # A normal lock-screen process only returns after a verified Space or
        # Enter request.  Any other return is a lifecycle failure, even if the
        # rendering code happened not to raise an exception.
        if _lifecyclelaststate not in ('failed', 'unlocked'):
            lifecyclewrite(
                'failed',
                f'unexpected run-loop return state={_lifecyclelaststate or "missing"}',
            )

    except KeyboardInterrupt:

        logline('main keyboard interrupt')

    except Exception as e:

        logexc('main error', e)
        lifecyclewrite('failed', f'{type(e).__name__}: {e}')

    finally:

        shutdown()

        # Preserve the exact terminal transition for Startup.  In particular,
        # never rewrite a failed or verified-unlock state as a generic "done".
        sys.exit(1 if _lifecyclelaststate == 'failed' else 0)



# execute main
if __name__ == '__main__':

    if len(sys.argv) > 1 and sys.argv[1].strip().lower() == 'graphics-diagnostic':

        sys.exit(graphicsdiagnosticcommand())

    main()
