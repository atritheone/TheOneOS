#!"/the one/software/python/bin/python" -B

"""
player.py

player is the audio and video player of The One OS.
"""



## imports
import os
import sys
import time
import json
import queue
import signal
import socket
import shutil
import functools
import selectors
import threading
import secrets

BUILDROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _prefer_build_root():
    while BUILDROOT in sys.path:
        sys.path.remove(BUILDROOT)
    sys.path.insert(0, BUILDROOT)


_prefer_build_root()

import audio.audio as audioapi
_prefer_build_root()
import media.media as mediaapi
_prefer_build_root()
import graphics.graphics as gfx
_prefer_build_root()
import viewer.viewer as viewerapi
from graphics.graphics import initbuffer, initttffont, measuretext
from graphics.graphics import fillrectfast, blitfilepartfast, blitfilescaledfast, drawtextttf, present as gfxpresent
from graphics.graphics import managedstate, managedconfigure, manageddisable
from graphics.graphics import managedmarkdamage, managedclear, managedtick
from graphics.graphics import managedsubmit, managedresponse, uiscalefactor, displayuiscale



## globals

# software
PLAYERPATH = '/the one/build/player/player.py'
VMTESTSTATUSPATH = '/.ephemeral/media/vm-player-status.json'
RUNNING = True
CLOSING = False

# window
SOCKPATH = '/.ephemeral/windowserver/accept.sock'
SOCK = None
SELECTOR = selectors.DefaultSelector()
INBUF = b''
OUTBUF = bytearray()
WINID = None
BUFFER = None
WINW = 780
WINH = 370
BASEWINW = 780
BASEWINH = 370
BASEVIDEOW = 1320
BASEVIDEOH = 900
SCREENW = 1920
SCREENH = 1080
UISCALE = 1.0
HASFOCUS = True
NEEDWINDOW = True
MAPPED = False
FULLSCREEN = False
FULLSCREENREQUEST = None
VIDEOCURSORVISIBLE = True
VIDEOCURSORHIDEAT = 0.0
VIDEOPOINTERACTIVE = False
FULLSCREENCONTROLSVISIBLE = False
VIDEOCURSORDELAY = 2.0
LASTVIDEOCLICK = 0.0
LASTVIDEOCLICKPOS = [0, 0]

# graphics
FONT = '/the one/resources/fonts/atkinsonhyperlegiblenext.ttf'
BASEFONT = 14
BASESMALLFONT = 12
BASETITLEFONT = 22
FONTSIZE = BASEFONT
SMALLFONT = BASESMALLFONT
TITLEFONT = BASETITLEFONT
BACKGROUND = 0x000000
TEXTCOLOUR = 0xEFEFEF
MUTEDCOLOUR = 0x6A6A6A
TRACKCOLOUR = 0x3A3A3A
ERRORCOLOUR = 0xFF0000
PROMPTCOLOUR = 0x242424
ARTCOLOUR = BACKGROUND
NEEDREDRAW = True
REDRAWDAMAGE = []
GRAPHICSSCENE = []
GRAPHICSCPU = str(os.environ.get('T1OS_PLAYER_GRAPHICS', '')).strip().lower() in ('cpu', 'off', '0', 'false')
GRAPHICSSTATE = managedstate(cpu=GRAPHICSCPU)
GRAPHICSVIDEO = {}

# layout
BASEPAD = 18
BASEICONSIZE = 26
BASEGAP = 12
BASETRACKHEIGHT = 3
BASETHUMBSIZE = 12
BASEARTSIZE = 240
PAD = BASEPAD
ICONSIZE = BASEICONSIZE
GAP = BASEGAP
TRACKHEIGHT = BASETRACKHEIGHT
THUMBSIZE = BASETHUMBSIZE

# playback
TRACKPATH = ''
TRACKNAME = ''
TRACKINFO = {}
ARTWORK = {}
MEDIAKIND = 'audio'
VIDEOFRAME = {}
VIDEORESIZED = False
VIDEOCONTROLPATH = ''
VIDEODECODESIZE = [0, 0]
PENDINGVIDEOSIZE = [0, 0]
VIDEORESIZEAT = 0.0
VIDEORESIZEDELAY = 0.20
VIDEOTRANSPORT = {}
PLAYSTATE = 'empty'
POSITION = 0.0
DURATION = 0.0
CONTROLPATH = ''
PLAYERROR = ''
MUTED = False
PLAYTHREAD = None
PLAYEVENTS = queue.SimpleQueue()
PLAYGEN = 0
LASTMEDIASTATUS = {}
PENDINGPATH = ''
PENDINGPLAYOPTIONS = {}
SELECTEDTRACKS = {
    'video_stream_index': None,
    'audio_stream_index': None,
    'subtitle_stream_index': -1,
}
DRAGGING = False
PREVIEW = None
INFOTHREAD = None
PENDINGART = {}
ARTWORKPENDING = False
INFOROOT = f'/.ephemeral/player/{os.getpid()}'
ARTWORKDELAY = 0.0
ARTWORKFALLBACK = 3.0

# general functions
def log(message):

    # Operations owns the persistent log descriptor.  Writing the log path
    # directly from the confined video domain is denied by design, so emit to
    # the inherited stream and let the trusted launcher persist it.
    try:

        print(f'{time.time():.6f} player {message}', file=sys.stderr, flush=True)

    except Exception:

        pass


def writevmteststatus():

    """Publish bounded playback evidence only in a disposable VM test."""
    if os.environ.get('T1OS_VM_TEST') != '1':
        return

    try:
        frame = VIDEOFRAME if isinstance(VIDEOFRAME, dict) else {}
        payload = {
            'format': 1,
            'pid': os.getpid(),
            'media_path': TRACKPATH,
            'media_kind': MEDIAKIND,
            'state': PLAYSTATE,
            'position': round(max(0.0, float(POSITION)), 3),
            'duration': round(max(0.0, float(DURATION)), 3),
            'error': str(PLAYERROR or '')[:512],
            'frame_ready': bool(
                int(frame.get('width', 0) or 0) > 0 and
                int(frame.get('height', 0) or 0) > 0 and
                (bool(frame.get('surface')) or bool(frame.get('path')))
            ),
            'frame_width': max(0, int(frame.get('width', 0) or 0)),
            'frame_height': max(0, int(frame.get('height', 0) or 0)),
            'frame_number': max(0, int(frame.get('frame', 0) or 0)),
        }
        encoded = (json.dumps(
            payload, sort_keys=True, separators=(',', ':'),
        ) + '\n').encode('utf-8')
        if len(encoded) > 4096:
            return
        temporary = (
            f'{VMTESTSTATUSPATH}.{os.getpid()}.{secrets.token_hex(8)}.new'
        )
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL |
            getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_CLOEXEC', 0),
            0o600,
        )
        try:
            offset = 0
            while offset < len(encoded):
                written = os.write(descriptor, encoded[offset:])
                if written <= 0:
                    raise OSError('short VM playback status write')
                offset += written
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(temporary, VMTESTSTATUSPATH)
    except Exception:
        try:
            if 'temporary' in locals():
                os.unlink(temporary)
        except Exception:
            pass


def clamp(value, minimum, maximum):

    try:

        value = float(value)
        minimum = float(minimum)
        maximum = float(maximum)

    except Exception:

        return minimum

    if value < minimum:

        return minimum

    if value > maximum:

        return maximum

    return value


def scalesize(value):

    try:

        return max(1, int(round(float(value) * float(UISCALE))))

    except Exception:

        return max(1, int(value))


def applyscale(width=None, height=None):

    global SCREENW, SCREENH, UISCALE
    global FONTSIZE, SMALLFONT, TITLEFONT, PAD, ICONSIZE, GAP, TRACKHEIGHT, THUMBSIZE

    try:

        if width is not None:

            SCREENW = max(1, int(width))

        if height is not None:

            SCREENH = max(1, int(height))

        UISCALE = displayuiscale(SCREENW, SCREENH, uiscalefactor())

    except Exception:

        UISCALE = 1.0

    FONTSIZE = max(9, scalesize(BASEFONT))
    SMALLFONT = max(8, scalesize(BASESMALLFONT))
    TITLEFONT = max(14, scalesize(BASETITLEFONT))
    PAD = max(8, scalesize(BASEPAD))
    ICONSIZE = max(18, scalesize(BASEICONSIZE))
    GAP = max(7, scalesize(BASEGAP))
    TRACKHEIGHT = max(2, scalesize(BASETRACKHEIGHT))
    THUMBSIZE = max(8, scalesize(BASETHUMBSIZE))


def formattime(seconds):

    try:

        seconds = max(0, int(float(seconds)))

    except Exception:

        seconds = 0

    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    remaining = seconds % 60

    if hours > 0:

        return f'{hours}:{minutes:02d}:{remaining:02d}'

    return f'{minutes}:{remaining:02d}'


def textwidth(text, size=None):

    if size is None:

        size = FONTSIZE

    try:

        return max(0, int(measuretext(str(text), int(size), FONT)))

    except Exception:

        return len(str(text)) * max(1, int(size) // 2)


def fittext(text, width, size=None):

    text = str(text)
    width = max(0, int(width))

    if textwidth(text, size) <= width:

        return text

    suffix = '...'

    if textwidth(suffix, size) > width:

        return ''

    shown = text

    while shown and textwidth(shown + suffix, size) > width:

        shown = shown[:-1]

    return shown + suffix


def metavalue(name):

    try:

        tags = TRACKINFO.get('tags', {})

        if not isinstance(tags, dict):

            return ''

        return str(tags.get(str(name), '') or '').strip()

    except Exception:

        return ''


def displaytitle():

    title = metavalue('title')

    if title:

        return title

    name = TRACKNAME or 'player'
    stem = os.path.splitext(name)[0]
    return stem or name


def displayartist():

    return metavalue('artist') or metavalue('albumartist')


def displayalbum():

    album = metavalue('album')
    date = metavalue('date')

    if album and date:

        return f'{album} · {date}'

    return album or date


def displaydetails():

    values = []
    track = metavalue('track')
    disc = metavalue('disc')
    genre = metavalue('genre')

    if track:

        values.append(f'Track {track}')

    if disc:

        values.append(f'Disc {disc}')

    if genre:

        values.append(genre)

    return ' · '.join(values)


def displaycredits():

    values = []
    artist = metavalue('artist')
    albumartist = metavalue('albumartist')
    composer = metavalue('composer')
    label = metavalue('label')

    if albumartist and albumartist != artist:

        values.append(f'Album artist: {albumartist}')

    if composer:

        values.append(f'Composer: {composer}')

    if label:

        values.append(f'Label: {label}')

    return ' · '.join(values)


def formatsize(size):

    try:

        size = max(0, int(size))

    except Exception:

        return ''

    if size >= 1024 * 1024 * 1024:

        return f'{size / float(1024 * 1024 * 1024):.1f} GB'

    if size >= 1024 * 1024:

        return f'{size / float(1024 * 1024):.1f} MB'

    if size >= 1024:

        return f'{size / float(1024):.1f} KB'

    return f'{size} B' if size else ''


def formatrate(rate):

    try:

        rate = max(0, int(rate))

    except Exception:

        return ''

    if rate <= 0:

        return ''

    value = rate / 1000.0

    if abs(value - round(value)) < 0.001:

        return f'{int(round(value))} kHz'

    return f'{value:.1f} kHz'


def displaytechnical():

    if MEDIAKIND == 'video':

        values = []
        video = TRACKINFO.get('video', {})
        audio = TRACKINFO.get('audio', {})
        form = str(TRACKINFO.get('format', '') or '').strip()

        if form:

            values.append(form)

        codec = str(video.get('codec', '') or '').strip()
        profile = str(video.get('profile', '') or '').strip()

        if codec:

            values.append(f'{codec} {profile}'.strip())

        width = int(video.get('display_width', video.get('width', 0)) or 0)
        height = int(video.get('display_height', video.get('height', 0)) or 0)

        if width > 0 and height > 0:

            values.append(f'{width}×{height}')

        framerate = float(video.get('frame_rate', 0.0) or 0.0)

        if framerate > 0.0:

            values.append(f'{framerate:.3f}'.rstrip('0').rstrip('.') + ' fps')

        depth = int(video.get('bit_depth', 0) or 0)

        if depth > 8:

            values.append(f'{depth}-bit')

        audiocodec = str(audio.get('codec', '') or '').strip()

        if audiocodec:

            values.append(audiocodec)

        rate = formatrate(audio.get('sample_rate', 0))

        if rate:

            values.append(rate)

        channels = str(audio.get('channels', '') or '').strip()

        if channels:

            values.append(channels[:1].upper() + channels[1:])

        for kind, prefix in (('video', 'V'), ('audio', 'A')):

            tracks = TRACKINFO.get(f'{kind}_tracks', [])

            if not isinstance(tracks, list) or len(tracks) < 2:

                continue

            selected = TRACKINFO.get(f'selected_{kind}_stream')
            ordinal = 0

            for index, track in enumerate(tracks, 1):

                if isinstance(track, dict) and track.get('index') == selected:

                    ordinal = index
                    break

            values.append(f'{prefix}{ordinal or "–"}/{len(tracks)}')

        size = formatsize(TRACKINFO.get('file_size', 0))

        if size:

            values.append(size)

        return ' · '.join(values)

    values = []
    form = str(TRACKINFO.get('format', '') or '').strip()
    codec = str(TRACKINFO.get('codec', '') or '').strip()

    if form:

        values.append(form)

    if codec and codec.lower() != form.lower():

        values.append(codec)

    if TRACKINFO.get('lossless'):

        values.append('Lossless')

    try:

        depth = max(0, int(TRACKINFO.get('bit_depth', 0) or 0))

    except Exception:

        depth = 0

    if depth:

        values.append(f'{depth}-bit')

    rate = formatrate(TRACKINFO.get('sample_rate', 0))

    if rate:

        values.append(rate)

    channels = str(TRACKINFO.get('channels', '') or '').strip()

    if channels:

        values.append(channels[:1].upper() + channels[1:])

    try:

        bitrate = max(0, int(TRACKINFO.get('bit_rate', 0) or 0))

    except Exception:

        bitrate = 0

    if bitrate:

        values.append(f'{bitrate:,} kbps')

    size = formatsize(TRACKINFO.get('file_size', 0))

    if size:

        values.append(size)

    return ' · '.join(values)


def pointinrect(x, y, rect):

    try:

        rx, ry, rw, rh = [int(value) for value in rect]

        return bool(x >= rx and x < rx + rw and y >= ry and y < ry + rh)

    except Exception:

        return False


def playbackactive():

    return PLAYSTATE in ('loading', 'playing', 'paused', 'seeking', 'draining', 'stopping')


def videowindowsize():

    width = min(
        max(scalesize(BASEVIDEOW), int(WINW)),
        max(1, int(SCREENW) - scalesize(80)),
    )
    height = min(
        max(scalesize(BASEVIDEOH), int(WINH)),
        max(1, int(SCREENH) - scalesize(120)),
    )
    return [max(1, int(width)), max(1, int(height))]


def videodecodelimits():

    if MEDIAKIND == 'video':

        rect = playbackgeometry().get('video', [0, 0, WINW, WINH])
        width = max(2, int(rect[2]))
        height = max(2, int(rect[3]))

    else:

        width = max(2, int(WINW) - (PAD * 2))
        controls = PAD + TITLEFONT + (SMALLFONT * 2) + ICONSIZE + (GAP * 5)
        height = max(2, int(WINH) - controls)

    return [min(max(2, int(SCREENW)), width), min(max(2, int(SCREENH)), height)]


def initialvideodecodelimits():

    width, height = videowindowsize()
    rect = playbackgeometry(
        windowwidth=width,
        windowheight=height,
        mediakind='video',
    ).get('video', [0, 0, width, height])
    return [
        min(max(2, int(SCREENW)), max(2, int(rect[2]))),
        min(max(2, int(SCREENH)), max(2, int(rect[3]))),
    ]


def substantialvideochange(current, desired):

    try:

        currentwidth, currentheight = [max(2, int(value)) for value in current]
        desiredwidth, desiredheight = [max(2, int(value)) for value in desired]

    except Exception:

        return True

    currentarea = currentwidth * currentheight
    desiredarea = desiredwidth * desiredheight

    if desiredarea >= currentarea * 1.40 or desiredarea <= currentarea * 0.60:

        return True

    return desiredwidth >= currentwidth * 1.30 or desiredheight >= currentheight * 1.30


def schedulevideoquality():

    global PENDINGVIDEOSIZE, VIDEORESIZEAT

    if MEDIAKIND != 'video' or not playbackactive():

        return False

    desired = videodecodelimits()

    if not substantialvideochange(VIDEODECODESIZE, desired):

        PENDINGVIDEOSIZE = [0, 0]
        return False

    PENDINGVIDEOSIZE = desired
    VIDEORESIZEAT = time.monotonic() + VIDEORESIZEDELAY
    return True


def pumpvideoquality():

    global VIDEODECODESIZE, PENDINGVIDEOSIZE

    if not PENDINGVIDEOSIZE or PENDINGVIDEOSIZE == [0, 0]:

        return False

    if time.monotonic() < VIDEORESIZEAT or not VIDEOCONTROLPATH:

        return False

    width, height = PENDINGVIDEOSIZE

    if not audioapi.sendcontrol(VIDEOCONTROLPATH, 'resize', width=width, height=height):

        return False

    VIDEODECODESIZE = [int(width), int(height)]
    PENDINGVIDEOSIZE = [0, 0]
    return True


def resizeforvideo():

    global VIDEORESIZED

    if VIDEORESIZED or WINID is None:

        return False

    width, height = videowindowsize()
    sendws({
        'op': 'RESIZE',
        'winid': WINID,
        'w': width,
        'h': height,
    })
    VIDEORESIZED = True
    return True


def redraw(rect=None):

    global NEEDREDRAW, REDRAWDAMAGE

    NEEDREDRAW = True

    if rect is None:

        REDRAWDAMAGE = [[0, 0, max(1, int(WINW)), max(1, int(WINH))]]

    else:

        try:

            damage = [int(value) for value in rect]

            if damage[2] > 0 and damage[3] > 0 and REDRAWDAMAGE != [[0, 0, max(1, int(WINW)), max(1, int(WINH))]]:

                REDRAWDAMAGE.append(damage)

        except Exception:

            REDRAWDAMAGE = [[0, 0, max(1, int(WINW)), max(1, int(WINH))]]

    if GRAPHICSSTATE.get('available') and WINW > 0 and WINH > 0:

        for damage in REDRAWDAMAGE:

            managedmarkdamage(GRAPHICSSTATE, damage, bounds=(WINW, WINH))


# path functions
def normalisefile(path):

    try:

        path = str(path).strip()

    except Exception:

        return '', 'enter a media file path'

    if not path:

        return '', 'enter a media file path'

    try:

        target = os.path.realpath(os.path.abspath(os.path.normpath(path)))

    except Exception as error:

        return '', f'invalid media path: {error}'

    if not os.path.exists(target):

        return '', f'media file not found: {path}'

    if not os.path.isfile(target):

        return '', f'not a media file: {path}'

    if not os.access(target, os.R_OK):

        return '', f'media file is not readable: {path}'

    return target, ''


def sendcurrent():

    if WINID is None:

        return

    sendws({
        'op': 'WINDOW_CURRENT_SET',
        'winid': WINID,
        'current': displaytitle(),
    })


# metadata functions
def unlinkinfo(path):

    try:

        path = os.path.abspath(os.path.normpath(str(path)))
        root = os.path.abspath(INFOROOT)

        if os.path.commonpath((path, root)) != root or path == root:

            return

        if os.path.isfile(path) and not os.path.islink(path):

            os.unlink(path)

    except Exception:

        pass


def discardart(artwork):

    if not isinstance(artwork, dict):

        return

    unlinkinfo(artwork.get('output', ''))
    unlinkinfo(artwork.get('source', ''))


def clearart():

    global ARTWORK

    oldart = ARTWORK
    ARTWORK = {}
    discardart(oldart)


def clearvideo():

    global VIDEOFRAME

    oldframe = VIDEOFRAME
    VIDEOFRAME = {}

    try:

        mediaapi.cleanupframe(oldframe.get('path', ''))

    except Exception:

        pass


def infoworker(generation, path, knowninfo=None):

    info = dict(knowninfo) if isinstance(knowninfo, dict) else {}
    artwork = {}
    errors = []

    try:

        if not info:

            info = mediaapi.mediainfo(path)

    except Exception as error:

        errors.append(str(error))
        info = {
            'version': 1,
            'path': path,
            'kind': 'unknown',
            'format': os.path.splitext(path)[1].lstrip('.').upper() or 'MEDIA',
            'file_size': os.path.getsize(path) if os.path.isfile(path) else 0,
            'tags': {},
        }

    artpath = os.path.join(INFOROOT, f'cover-{int(generation)}.image')
    surfacepath = os.path.join(INFOROOT, f'cover-{int(generation)}.bgra')

    try:

        os.makedirs(INFOROOT, mode=0o700, exist_ok=True)

        if os.path.islink(INFOROOT):

            raise ValueError('player artwork directory is not safe')

        if mediaapi.extractart(path, artpath):

            maximum = max(64, scalesize(BASEARTSIZE))
            # Player already imported the measured Viewer renderer.  Spawning
            # viewer.py here would ask the video domain to execute the Python
            # interpreter, which the LSM correctly reserves for Brick. Render
            # the extracted cover in-process instead.
            artwork = viewerapi.render(
                artpath,
                surfacepath,
                maximum,
                maximum,
                1,
            )
            info['artwork'] = True

        else:

            unlinkinfo(artpath)

    except Exception as error:

        errors.append(str(error))
        discardart({'source': artpath, 'output': surfacepath})
        artwork = {}

    try:

        PLAYEVENTS.put({
            'kind': 'info',
            'generation': int(generation),
            'info': dict(info),
            'artwork': dict(artwork),
            'errors': errors,
            'artwork_pending': False,
        })

    except Exception:

        discardart(artwork)


def startinfo(generation, path, knowninfo=None):

    global INFOTHREAD

    INFOTHREAD = threading.Thread(
        target=infoworker,
        args=(int(generation), str(path), dict(knowninfo) if isinstance(knowninfo, dict) else None),
        daemon=True,
        name=f'player-info-{int(generation)}',
    )
    INFOTHREAD.start()


def startpendingartwork():

    global PENDINGART

    pending = PENDINGART

    if not isinstance(pending, dict) or not pending:

        return False

    if int(pending.get('generation', -1)) != int(PLAYGEN):

        PENDINGART = {}
        return False

    if INFOTHREAD is not None and INFOTHREAD.is_alive():

        return False

    now = time.monotonic()
    ready = POSITION >= ARTWORKDELAY
    ready = ready or PLAYSTATE in ('complete', 'stopped', 'error')
    ready = ready or now >= float(pending.get('fallback_at', now))

    if not ready:

        return False

    PENDINGART = {}
    startinfo(
        pending.get('generation', PLAYGEN),
        pending.get('path', TRACKPATH),
        knowninfo=pending.get('info', {}),
    )
    return True


def shutdowninfo():

    thread = INFOTHREAD

    if thread is not None and thread.is_alive():

        thread.join(timeout=0.2)


# playback functions
def playreport(generation, status):

    try:

        PLAYEVENTS.put({
            'kind': 'status',
            'generation': int(generation),
            'status': dict(status),
        })

    except Exception:

        pass


def playinfo(generation, path, info):

    try:

        PLAYEVENTS.put({
            'kind': 'info',
            'generation': int(generation),
            'path': str(path),
            'info': dict(info),
            'artwork': {},
            'errors': [],
            'artwork_pending': True,
        })

    except Exception:

        pass


def playframe(generation, frame):

    try:

        PLAYEVENTS.put({
            'kind': 'frame',
            'generation': int(generation),
            'frame': dict(frame),
        })

        if frame.get('surface'):

            log(
                'video surface event queued '
                f'generation={int(generation)} '
                f'stream={frame.get("stream", "")} '
                f'frame={int(frame.get("frame", 0) or 0)}'
            )

    except Exception:

        pass


def playworker(
    generation,
    path,
    maximumwidth,
    maximumheight,
    video_transport=None,
    playoptions=None,
):

    try:

        mediaapi.STOPREQUESTED = False
        result = mediaapi.play(
            path,
            statuscallback=functools.partial(playreport, generation),
            framecallback=functools.partial(playframe, generation),
            infocallback=functools.partial(playinfo, generation, path),
            controls=True,
            maximumwidth=maximumwidth,
            maximumheight=maximumheight,
            retainframe=True,
            video_transport=dict(video_transport or {}),
            **dict(playoptions or {}),
        )

        PLAYEVENTS.put({
            'kind': 'complete',
            'generation': int(generation),
            'result': dict(result),
        })

    except mediaapi.MediaCancelled:

        PLAYEVENTS.put({
            'kind': 'stopped',
            'generation': int(generation),
        })

    except mediaapi.MediaError as error:

        PLAYEVENTS.put({
            'kind': 'error',
            'generation': int(generation),
            'error': str(error),
        })

    except Exception as error:

        PLAYEVENTS.put({
            'kind': 'error',
            'generation': int(generation),
            'error': f'media playback failed: {error}',
        })


def startplay(path, playoptions=None):

    global TRACKPATH, TRACKNAME, TRACKINFO, PLAYSTATE, POSITION, DURATION
    global CONTROLPATH, PLAYERROR, PLAYTHREAD, PLAYGEN, PENDINGPATH, LASTMEDIASTATUS
    global PENDINGPLAYOPTIONS, SELECTEDTRACKS
    global DRAGGING, PREVIEW, MEDIAKIND, VIDEORESIZED, PENDINGART, ARTWORKPENDING
    global VIDEOCONTROLPATH, VIDEODECODESIZE, PENDINGVIDEOSIZE, VIDEORESIZEAT, VIDEOTRANSPORT

    target, error = normalisefile(path)
    options = dict(playoptions or {})

    for key in tuple(options):

        if key not in (
            'video_stream_index',
            'audio_stream_index',
            'subtitle_stream_index',
            'startseconds',
        ):

            options.pop(key, None)

    if error:

        PLAYERROR = error

        if not playbackactive():

            PLAYSTATE = 'error'

        redraw()

        return False

    if PLAYTHREAD is not None and PLAYTHREAD.is_alive():

        PENDINGPATH = target
        PENDINGPLAYOPTIONS = dict(options)
        stopplay()

        return True

    if FULLSCREEN:
        setfullscreen(False)

    TRACKPATH = target
    TRACKNAME = os.path.basename(target) or target
    TRACKINFO = {}
    clearart()
    clearvideo()
    MEDIAKIND = 'audio'
    VIDEORESIZED = False
    VIDEOCONTROLPATH = ''
    VIDEODECODESIZE = initialvideodecodelimits()
    PENDINGVIDEOSIZE = [0, 0]
    VIDEORESIZEAT = 0.0
    VIDEOTRANSPORT = {}
    PENDINGART = {}
    ARTWORKPENDING = True
    PLAYSTATE = 'loading'
    POSITION = 0.0
    DURATION = 0.0
    CONTROLPATH = ''
    PLAYERROR = ''
    LASTMEDIASTATUS = {}
    PENDINGPATH = ''
    PENDINGPLAYOPTIONS = {}
    DRAGGING = False
    PREVIEW = None
    PLAYGEN += 1
    mediaapi.STOPREQUESTED = False

    if not options:

        SELECTEDTRACKS = {
            'video_stream_index': None,
            'audio_stream_index': None,
            'subtitle_stream_index': -1,
        }

    else:

        for key in SELECTEDTRACKS:

            if key in options:

                SELECTEDTRACKS[key] = options[key]

    if GRAPHICSSTATE.get('available') and (
        GRAPHICSVIDEO.get('drm_driver') or
        GRAPHICSVIDEO.get('render_node')
    ):

        # Keep the measured display backend even when WindowServer cannot
        # expose its native video-surface socket. Media uses this identity to
        # enforce fail-closed decode policy on proprietary NVIDIA hardware.
        VIDEOTRANSPORT = {
            'drm_driver': str(GRAPHICSVIDEO.get('drm_driver') or ''),
            'render_node': str(GRAPHICSVIDEO.get('render_node') or ''),
            'render_identity': dict(
                GRAPHICSVIDEO.get('render_identity') or {}
            ),
            'import_capabilities': dict(
                GRAPHICSVIDEO.get('import_capabilities') or {}
            ),
        }

    if (
        WINID is not None
        and GRAPHICSSTATE.get('available')
        and GRAPHICSVIDEO.get('available')
        and GRAPHICSVIDEO.get('socket')
    ):

        token = secrets.token_hex(32)
        stream = f'player-{os.getpid()}-{PLAYGEN}'

        if sendws({
            'op': 'VIDEO_AUTHORIZE',
            'winid': WINID,
            'token': token,
            'stream': stream,
        }):

            VIDEOTRANSPORT.update({
                'socket': str(GRAPHICSVIDEO['socket']),
                'token': token,
                'stream': stream,
            })

    PLAYTHREAD = threading.Thread(
        target=playworker,
        args=(
            PLAYGEN,
            TRACKPATH,
            VIDEODECODESIZE[0],
            VIDEODECODESIZE[1],
            dict(VIDEOTRANSPORT),
            dict(options),
        ),
        daemon=True,
        name=f'player-{PLAYGEN}',
    )
    PLAYTHREAD.start()
    sendcurrent()
    redraw()

    return True


def stopplay(cancel=False):

    global PLAYSTATE, PENDINGPATH, PENDINGPLAYOPTIONS

    if cancel:

        PENDINGPATH = ''
        PENDINGPLAYOPTIONS = {}

    if PLAYTHREAD is None or not PLAYTHREAD.is_alive():

        if TRACKPATH:

            PLAYSTATE = 'stopped'
            redraw()

        return False

    sent = audioapi.sendcontrol(CONTROLPATH, 'stop')

    if not sent:

        try:

            mediaapi.requeststop()

        except Exception:

            pass

    PLAYSTATE = 'stopping'
    redraw()

    return True


def toggleplay():

    global PLAYSTATE

    if PLAYSTATE == 'paused':

        if audioapi.sendcontrol(CONTROLPATH, 'resume'):

            PLAYSTATE = 'playing'
            redraw()

            return True

        return False

    if PLAYSTATE in ('playing', 'draining'):

        if audioapi.sendcontrol(CONTROLPATH, 'pause'):

            PLAYSTATE = 'paused'
            redraw()

            return True

        return False

    if TRACKPATH and PLAYSTATE in ('stopped', 'complete', 'error'):

        return startplay(TRACKPATH)

    return False


def togglemute():

    global MUTED

    MUTED = not MUTED

    if CONTROLPATH:

        audioapi.sendcontrol(CONTROLPATH, 'mute', muted=MUTED)

    redraw()
    return True


def seekplay(position):

    global POSITION, PLAYSTATE

    if not playbackactive() or PLAYSTATE in ('loading', 'stopping'):

        return False

    if DURATION <= 0.0:

        return False

    position = clamp(position, 0.0, DURATION)

    if not audioapi.sendcontrol(CONTROLPATH, 'seek', position=position):

        return False

    POSITION = position
    PLAYSTATE = 'seeking'
    redraw()

    return True


def drainplayevents():

    global PLAYSTATE, POSITION, DURATION, CONTROLPATH, PLAYERROR
    global PLAYTHREAD, PENDINGPATH, PENDINGPLAYOPTIONS, DRAGGING, PREVIEW
    global TRACKINFO, ARTWORK, INFOTHREAD, MEDIAKIND, VIDEOFRAME, VIDEORESIZED, PENDINGART, ARTWORKPENDING
    global VIDEOCONTROLPATH, LASTMEDIASTATUS, SELECTEDTRACKS

    changed = False
    fullchange = False
    framechange = False
    statuschange = False

    while True:

        try:

            event = PLAYEVENTS.get_nowait()

        except queue.Empty:

            break

        except Exception:

            break

        try:

            generation = int(event.get('generation', -1))

        except Exception:

            generation = -1

        kind = str(event.get('kind', ''))

        if generation != PLAYGEN:

            if kind == 'info':

                discardart(event.get('artwork', {}))

            continue

        if kind == 'status':

            status = event.get('status', {})

            if not isinstance(status, dict) or status.get('type') not in ('audio_status', 'media_status'):

                continue

            LASTMEDIASTATUS = dict(status)
            oldkind = MEDIAKIND
            MEDIAKIND = str(status.get('media_kind', MEDIAKIND) or MEDIAKIND)

            if MEDIAKIND != oldkind:

                fullchange = True

                if MEDIAKIND == 'video':

                    resizeforvideo()

            PLAYSTATE = str(status.get('state', PLAYSTATE))

            try:

                POSITION = max(0.0, float(status.get('position', POSITION)))

            except Exception:

                pass

            try:

                DURATION = max(0.0, float(status.get('duration', DURATION)))

            except Exception:

                pass

            oldcontrol = CONTROLPATH
            CONTROLPATH = str(status.get('control', CONTROLPATH) or CONTROLPATH)

            if CONTROLPATH and CONTROLPATH != oldcontrol and MUTED:

                audioapi.sendcontrol(CONTROLPATH, 'mute', muted=True)
            oldvideocontrol = VIDEOCONTROLPATH
            VIDEOCONTROLPATH = str(status.get('video_control', VIDEOCONTROLPATH) or VIDEOCONTROLPATH)

            if VIDEOCONTROLPATH and not oldvideocontrol and MEDIAKIND == 'video':

                schedulevideoquality()

            changed = True
            statuschange = True

            continue

        if kind == 'frame':

            frame = event.get('frame', {})

            if not isinstance(frame, dict) or frame.get('type') != 'media_frame':

                continue

            path = str(frame.get('path', '') or '')
            surface = bool(frame.get('surface')) and bool(frame.get('stream'))
            width = int(frame.get('width', 0) or 0)
            height = int(frame.get('height', 0) or 0)

            if (
                width > 0
                and height > 0
                and (
                    (surface and GRAPHICSVIDEO.get('available'))
                    or (path and os.path.isfile(path))
                )
            ):

                VIDEOFRAME = dict(frame)
                MEDIAKIND = 'video'
                changed = True
                framechange = True

                if surface:

                    log(
                        'video surface event accepted '
                        f'generation={generation} '
                        f'stream={frame.get("stream", "")} '
                        f'frame={int(frame.get("frame", 0) or 0)}'
                    )

            elif surface:

                log(
                    'video surface event rejected '
                    f'generation={generation} '
                    f'size={width}x{height} '
                    f'graphics_available={bool(GRAPHICSVIDEO.get("available"))}'
                )

            continue

        if kind == 'info':

            info = event.get('info', {})
            artwork = event.get('artwork', {})
            TRACKINFO = dict(info) if isinstance(info, dict) else {}
            MEDIAKIND = str(TRACKINFO.get('kind', MEDIAKIND) or MEDIAKIND)
            SELECTEDTRACKS = {
                'video_stream_index': TRACKINFO.get('selected_video_stream'),
                'audio_stream_index': TRACKINFO.get('selected_audio_stream'),
                'subtitle_stream_index': TRACKINFO.get('selected_subtitle_stream', -1),
            }
            clearart()
            ARTWORK = dict(artwork) if isinstance(artwork, dict) else {}
            INFOTHREAD = None

            if event.get('artwork_pending') and MEDIAKIND != 'video':

                ARTWORKPENDING = True
                now = time.monotonic()
                PENDINGART = {
                    'generation': generation,
                    'path': str(event.get('path', TRACKPATH) or TRACKPATH),
                    'info': dict(TRACKINFO),
                    'fallback_at': now + ARTWORKFALLBACK,
                }

            else:

                ARTWORKPENDING = False
                PENDINGART = {}

            try:

                duration = max(0.0, float(TRACKINFO.get('duration', 0.0) or 0.0))

                if DURATION <= 0.0 and duration > 0.0:

                    DURATION = duration

            except Exception:

                pass

            for error in event.get('errors', []):

                log(f'metadata notice {error}')

            if MEDIAKIND == 'video':

                resizeforvideo()

            sendcurrent()
            changed = True
            fullchange = True
            continue

        PLAYTHREAD = None
        CONTROLPATH = ''
        DRAGGING = False
        PREVIEW = None

        if PENDINGPATH and not CLOSING:

            target = PENDINGPATH
            options = dict(PENDINGPLAYOPTIONS)
            PENDINGPATH = ''
            PENDINGPLAYOPTIONS = {}
            startplay(target, playoptions=options)
            changed = True
            fullchange = True

            continue

        if kind == 'complete':

            PLAYSTATE = 'complete'

            if DURATION > 0.0:

                POSITION = DURATION

        elif kind == 'stopped':

            PLAYSTATE = 'stopped'

        elif kind == 'error':

            PLAYSTATE = 'error'
            PLAYERROR = str(event.get('error', 'media playback failed'))
            log(f'playback error {PLAYERROR}')

            if not PENDINGART:
                ARTWORKPENDING = False

        if MEDIAKIND == 'video' and kind in ('complete', 'stopped', 'error'):

            hardwarefailure = str(LASTMEDIASTATUS.get('hardware_failure', '') or '').strip()

            if hardwarefailure:

                log(f'video hardware fallback {hardwarefailure}')

            log(
                'video playback terminal '
                f'state={PLAYSTATE} '
                f'error={PLAYERROR!r} '
                f'backend={LASTMEDIASTATUS.get("video_backend", "unknown")} '
                f'hardware_decode={bool(LASTMEDIASTATUS.get("hardware_decode"))} '
                f'zero_copy={bool(LASTMEDIASTATUS.get("zero_copy"))} '
                f'drm_driver={LASTMEDIASTATUS.get("video_drm_driver", "")} '
                f'va_driver={LASTMEDIASTATUS.get("video_driver", "")} '
                f'decoded_frames={int(LASTMEDIASTATUS.get("decoded_frames", 0) or 0)} '
                f'submitted_frames={int(LASTMEDIASTATUS.get("submitted_frames", 0) or 0)} '
                f'presented_frames={int(LASTMEDIASTATUS.get("presented_frames", 0) or 0)} '
                f'dropped_frames={int(LASTMEDIASTATUS.get("dropped_frames", 0) or 0)} '
                f'compositor_dropped_frames={int(LASTMEDIASTATUS.get("compositor_dropped_frames", 0) or 0)} '
                f'audio_underruns={int(LASTMEDIASTATUS.get("audio_underruns", 0) or 0)} '
                f'maximum_av_drift_ms={float(LASTMEDIASTATUS.get("maximum_av_drift_ms", 0.0) or 0.0):.3f} '
                f'percentile_95_av_drift_ms={float(LASTMEDIASTATUS.get("percentile_95_av_drift_ms", 0.0) or 0.0):.3f} '
                f'surface_frame={bool(VIDEOFRAME.get("surface"))} '
                f'surface_stream={VIDEOFRAME.get("stream", "")}'
            )

        changed = True

    if changed:

        writevmteststatus()

        if fullchange or MEDIAKIND != 'video':

            redraw()

        else:

            geometry = playbackgeometry()

            if framechange:

                redraw(geometry.get('video', [0, 0, WINW, WINH]))

            if statuschange:

                status = geometry.get('status', [0, 0, WINW, WINH])
                top = max(0, int(status[1]))
                redraw([0, top, WINW, max(1, WINH - top)])

            if not framechange and not statuschange:

                redraw()

    return changed


def shutdownplay():

    global PENDINGPATH, PENDINGPLAYOPTIONS

    PENDINGPATH = ''
    PENDINGPLAYOPTIONS = {}

    thread = PLAYTHREAD

    if thread is None or not thread.is_alive():

        return

    stopplay()
    thread.join(timeout=1.0)

    if thread.is_alive():

        try:

            mediaapi.requeststop()

        except Exception:

            pass

        thread.join(timeout=1.0)


# layout functions
def statusmessage():

    if PLAYERROR:

        return PLAYERROR or 'media playback failed', ERRORCOLOUR

    messages = {
        'empty': 'open a media file',
        'loading': 'loading',
        'paused': 'paused',
        'seeking': 'seeking',
        'draining': 'finishing playback',
        'complete': 'playback complete',
        'stopped': 'playback stopped',
        'stopping': 'stopping',
    }

    message = messages.get(PLAYSTATE, '')

    if MUTED and not message:
        message = 'muted'

    return message, MUTEDCOLOUR


def playbackgeometry(windowwidth=None, windowheight=None, mediakind=None):

    width = max(1, int(WINW if windowwidth is None else windowwidth))
    height = max(1, int(WINH if windowheight is None else windowheight))
    kind = MEDIAKIND if mediakind is None else str(mediakind)

    if FULLSCREEN and kind == 'video':

        if FULLSCREENCONTROLSVISIBLE:

            panelheight = max(scalesize(72), ICONSIZE + (PAD * 2))
            paneltop = max(0, height - panelheight)
            controlcentre = paneltop + panelheight // 2
            icony = max(paneltop, min(height - ICONSIZE, controlcentre - ICONSIZE // 2))
            stoprect = [PAD, icony, ICONSIZE, ICONSIZE]
            togglerect = [PAD + ICONSIZE + GAP, icony, ICONSIZE, ICONSIZE]
            timetext = f'{formattime(PREVIEW if DRAGGING and PREVIEW is not None else POSITION)} / {formattime(DURATION)}'
            timewidth = max(textwidth(timetext, SMALLFONT), textwidth('0:00 / 0:00', SMALLFONT))
            timex = max(togglerect[0] + ICONSIZE + GAP, width - PAD - timewidth)
            trackx = togglerect[0] + ICONSIZE + (GAP * 2)
            trackright = timex - (GAP * 2)
            trackwidth = max(12, trackright - trackx)
            tracky = controlcentre - TRACKHEIGHT // 2
            duration = max(0.0, float(DURATION))
            position = PREVIEW if DRAGGING and PREVIEW is not None else POSITION
            fraction = clamp(float(position) / duration if duration > 0.0 else 0.0, 0.0, 1.0)
            thumbcentre = trackx + int(fraction * trackwidth)
            thumbrect = [thumbcentre - THUMBSIZE // 2, controlcentre - THUMBSIZE // 2, THUMBSIZE, THUMBSIZE]

        else:

            paneltop = height
            stoprect = [0, 0, 0, 0]
            togglerect = [0, 0, 0, 0]
            trackx = 0
            tracky = 0
            trackwidth = 0
            icony = 0
            thumbrect = [0, 0, 0, 0]
            timex = 0
            controlcentre = 0
            timetext = ''

        return {
            'compact': True,
            'art': [0, 0, 0, 0],
            'video': [0, 0, width, height],
            'info': [0, 0, 0, 0],
            'name': [0, 0, 0, 0],
            'status': [0, 0, 0, 0],
            'stop': stoprect,
            'toggle': togglerect,
            'track': [trackx, tracky, trackwidth, TRACKHEIGHT if trackwidth else 0],
            'trackhit': [trackx, icony, trackwidth, ICONSIZE if trackwidth else 0],
            'thumb': thumbrect,
            'time': [timex, controlcentre - SMALLFONT // 2, timetext],
            'controls_panel': [0, paneltop, width, max(0, height - paneltop)],
        }

    compact = width < scalesize(560) or height < scalesize(250)
    controlcentre = height - PAD - ICONSIZE // 2

    controlcentre = max(PAD + ICONSIZE // 2, controlcentre)
    icony = max(0, min(height - ICONSIZE, controlcentre - ICONSIZE // 2))
    statusy = max(PAD, icony - GAP - SMALLFONT)
    infobottom = max(PAD, statusy - GAP)
    stoprect = [PAD, icony, ICONSIZE, ICONSIZE]
    togglerect = [PAD + ICONSIZE + GAP, icony, ICONSIZE, ICONSIZE]
    timetext = f'{formattime(PREVIEW if DRAGGING and PREVIEW is not None else POSITION)} / {formattime(DURATION)}'
    timewidth = max(textwidth(timetext, SMALLFONT), textwidth('0:00 / 0:00', SMALLFONT))
    timex = max(togglerect[0] + ICONSIZE + GAP, width - PAD - timewidth)
    trackx = togglerect[0] + ICONSIZE + (GAP * 2)
    trackright = timex - (GAP * 2)
    trackwidth = max(12, trackright - trackx)
    tracky = controlcentre - TRACKHEIGHT // 2
    duration = max(0.0, float(DURATION))
    position = PREVIEW if DRAGGING and PREVIEW is not None else POSITION
    fraction = clamp(float(position) / duration if duration > 0.0 else 0.0, 0.0, 1.0)
    thumbcentre = trackx + int(fraction * trackwidth)
    thumbrect = [thumbcentre - THUMBSIZE // 2, controlcentre - THUMBSIZE // 2, THUMBSIZE, THUMBSIZE]
    artrect = [0, 0, 0, 0]
    videorect = [0, 0, 0, 0]
    infox = PAD

    if kind == 'video':

        headerheight = (TITLEFONT if not compact else FONTSIZE) + SMALLFONT + GAP
        videotop = PAD + headerheight + GAP
        videorect = [PAD, videotop, max(1, width - (PAD * 2)), max(1, infobottom - videotop)]
        infox = PAD

    elif not compact:

        artsize = min(scalesize(BASEARTSIZE), max(0, infobottom - PAD))

        if artsize >= scalesize(64):

            artrect = [PAD, PAD, artsize, artsize]
            infox = PAD + artsize + (GAP * 2)

    inforight = max(infox, width - PAD)
    infowidth = max(0, inforight - infox)
    namewidth = infowidth
    infoheight = max(0, infobottom - PAD)

    if kind == 'video':

        infoheight = max(0, videorect[1] - PAD - GAP)

    return {
        'compact': compact,
        'art': artrect,
        'video': videorect,
        'info': [infox, PAD, infowidth, infoheight],
        'name': [infox, PAD, namewidth, TITLEFONT if not compact else FONTSIZE],
        'status': [PAD, statusy, max(1, width - (PAD * 2)), SMALLFONT],
        'stop': stoprect,
        'toggle': togglerect,
        'track': [trackx, tracky, trackwidth, TRACKHEIGHT],
        'trackhit': [trackx, icony, trackwidth, ICONSIZE],
        'thumb': thumbrect,
        'time': [timex, controlcentre - SMALLFONT // 2, timetext],
        'controls_panel': [0, 0, 0, 0],
    }


def positionfromx(x):

    geometry = playbackgeometry()
    track = geometry.get('track')

    if not track or DURATION <= 0.0:

        return 0.0

    fraction = (float(x) - float(track[0])) / float(max(1, track[2]))

    return clamp(fraction, 0.0, 1.0) * DURATION


def artplacement(rect):

    try:

        x, y, width, height = [int(value) for value in rect]
        size = ARTWORK.get('surface_size', [0, 0])
        artwidth = max(0, int(size[0]))
        artheight = max(0, int(size[1]))

    except Exception:

        return [0, 0, 0, 0]

    if width < 1 or height < 1 or artwidth < 1 or artheight < 1:

        return [0, 0, 0, 0]

    return [
        x + ((width - artwidth) // 2),
        y + ((height - artheight) // 2),
        artwidth,
        artheight,
    ]


def videoplacement(rect):

    try:

        x, y, width, height = [int(value) for value in rect]
        sourcewidth = max(0, int(VIDEOFRAME.get('width', 0)))
        sourceheight = max(0, int(VIDEOFRAME.get('height', 0)))

    except Exception:

        return [0, 0, 0, 0]

    if width < 1 or height < 1 or sourcewidth < 1 or sourceheight < 1:

        return [0, 0, 0, 0]

    scale = min(width / float(sourcewidth), height / float(sourceheight))
    targetwidth = max(1, int(round(sourcewidth * scale)))
    targetheight = max(1, int(round(sourceheight * scale)))
    return [
        x + ((width - targetwidth) // 2),
        y + ((height - targetheight) // 2),
        targetwidth,
        targetheight,
    ]


def metalines(compact=False):

    title = displaytitle()

    if MEDIAKIND == 'video':

        secondary = ' · '.join(value for value in (displayartist(), displayalbum()) if value)
        return [
            ('trackname', title, TEXTCOLOUR, FONTSIZE if compact else TITLEFONT),
            ('secondary', secondary or displaytechnical(), MUTEDCOLOUR, SMALLFONT),
            ('technical', displaytechnical() if secondary else '', MUTEDCOLOUR, SMALLFONT),
        ]

    if compact:

        secondary = displayartist() or displaytechnical() or TRACKNAME
        return [
            ('trackname', title, TEXTCOLOUR, FONTSIZE),
            ('secondary', secondary, MUTEDCOLOUR, SMALLFONT),
        ]

    values = [
        ('trackname', title, TEXTCOLOUR, TITLEFONT),
        ('artist', displayartist(), TEXTCOLOUR, FONTSIZE),
        ('album', displayalbum(), MUTEDCOLOUR, FONTSIZE),
        ('details', displaydetails(), MUTEDCOLOUR, SMALLFONT),
        ('credits', displaycredits(), MUTEDCOLOUR, SMALLFONT),
        ('technical', displaytechnical(), TEXTCOLOUR, SMALLFONT),
    ]

    if TRACKNAME and TRACKNAME != title:

        values.append(('filename', TRACKNAME, MUTEDCOLOUR, SMALLFONT))

    return values


def addrect(commands, name, rect, colour):

    try:

        x, y, width, height = [int(value) for value in rect]

    except Exception:

        return

    if width < 1 or height < 1:

        return

    commands.append({
        'id': str(name),
        'kind': 'rectangle',
        'rect': [x, y, width, height],
        'color': int(colour),
        'clip': [0, 0, int(WINW), int(WINH)],
    })


def addtext(commands, name, x, y, text, colour, size):

    text = str(text)

    if not text:

        return

    commands.append({
        'id': str(name),
        'kind': 'text',
        'x': int(x),
        'y': int(y),
        'text': text,
        'size': int(size),
        'font': FONT,
        'color': int(colour),
        'clip': [0, 0, int(WINW), int(WINH)],
    })


def addimage(commands, name, path, rect, size, clip, revision=None):

    try:

        x, y, width, height = [int(value) for value in rect]
        sourcewidth = max(1, int(size[0]))
        sourceheight = max(1, int(size[1]))
        clip = [int(value) for value in clip]
        path = str(path)

    except Exception:

        return

    if width < 1 or height < 1 or not os.path.isfile(path):

        return

    command = {
        'id': str(name),
        'kind': 'image',
        'path': path,
        'source_width': sourcewidth,
        'source_height': sourceheight,
        'format': 'BGRA32',
        'rect': [x, y, width, height],
        'clip': clip,
    }

    if revision is not None:

        command['revision'] = max(0, int(revision))

    commands.append(command)


def addtransportcontrols(commands, geometry):

    active = playbackactive()
    controlcolour = TEXTCOLOUR if active else MUTEDCOLOUR
    stopx, stopy, stopw, stoph = geometry['stop']
    stopinset = max(3, stopw // 4)
    addrect(
        commands,
        'stop',
        [stopx + stopinset, stopy + stopinset, max(1, stopw - stopinset * 2), max(1, stoph - stopinset * 2)],
        controlcolour,
    )
    togglex, toggley, togglew, toggleh = geometry['toggle']

    if PLAYSTATE in ('playing', 'draining'):

        barwidth = max(2, togglew // 5)
        bargap = max(2, togglew // 5)
        left = togglex + max(1, (togglew - ((barwidth * 2) + bargap)) // 2)
        addrect(commands, 'pauseleft', [left, toggley + 2, barwidth, max(1, toggleh - 4)], TEXTCOLOUR)
        addrect(commands, 'pauseright', [left + barwidth + bargap, toggley + 2, barwidth, max(1, toggleh - 4)], TEXTCOLOUR)

    else:

        playcolour = TEXTCOLOUR if TRACKPATH or PLAYSTATE == 'empty' else MUTEDCOLOUR
        trianglewidth = max(3, togglew - 4)

        for offset in range(trianglewidth):

            trim = int((offset / float(max(1, trianglewidth - 1))) * ((toggleh - 4) / 2.0))
            addrect(
                commands,
                f'play{offset}',
                [togglex + 2 + offset, toggley + 2 + trim, 1, max(1, toggleh - 4 - trim * 2)],
                playcolour,
            )

    trackcolour = TRACKCOLOUR if DURATION > 0.0 else MUTEDCOLOUR
    addrect(commands, 'track', geometry['track'], trackcolour)
    addrect(commands, 'thumb', geometry['thumb'], controlcolour)
    timex, timey, timetext = geometry['time']
    addtext(commands, 'time', timex, timey, timetext, TEXTCOLOUR, SMALLFONT)


def buildscene():

    commands = []
    geometry = playbackgeometry()
    addrect(commands, 'background', [0, 0, WINW, WINH], BACKGROUND)
    artbox = geometry['art']

    if artbox[2] > 0 and artbox[3] > 0:

        addrect(commands, 'artbackground', artbox, ARTCOLOUR)
        artrect = artplacement(artbox)
        output = str(ARTWORK.get('output', '') or '')
        size = ARTWORK.get('surface_size', [0, 0])

        if artrect[2] > 0 and artrect[3] > 0 and os.path.isfile(output):

            addimage(commands, 'artwork', output, artrect, size, artbox)

        else:

            pendingart = bool(ARTWORKPENDING or PENDINGART)
            label = 'loading artwork' if pendingart else ('no artwork' if TRACKPATH else 'player')
            labelwidth = textwidth(label, SMALLFONT)
            addtext(
                commands,
                'artplaceholder',
                artbox[0] + max(0, (artbox[2] - labelwidth) // 2),
                artbox[1] + max(0, (artbox[3] - SMALLFONT) // 2),
                label,
                MUTEDCOLOUR,
                SMALLFONT,
            )

    videobox = geometry.get('video', [0, 0, 0, 0])

    if MEDIAKIND == 'video' and videobox[2] > 0 and videobox[3] > 0:

        addrect(commands, 'videobackground', videobox, ARTCOLOUR)
        videorect = videoplacement(videobox)
        output = str(VIDEOFRAME.get('path', '') or '')
        size = [VIDEOFRAME.get('width', 0), VIDEOFRAME.get('height', 0)]

        if (
            videorect[2] > 0
            and videorect[3] > 0
            and VIDEOFRAME.get('surface')
            and VIDEOFRAME.get('stream')
            and GRAPHICSVIDEO.get('available')
        ):

            commands.append({
                'id': 'videoframe',
                'kind': 'video',
                'stream': str(VIDEOFRAME['stream']),
                'rect': list(videorect),
                'clip': list(videobox),
            })

        elif videorect[2] > 0 and videorect[3] > 0 and os.path.isfile(output):

            addimage(
                commands,
                'videoframe',
                output,
                videorect,
                size,
                videobox,
                revision=VIDEOFRAME.get('frame', 0),
            )

        else:

            label = 'loading video' if TRACKPATH else 'player'
            labelwidth = textwidth(label, SMALLFONT)
            addtext(
                commands,
                'videoplaceholder',
                videobox[0] + max(0, (videobox[2] - labelwidth) // 2),
                videobox[1] + max(0, (videobox[3] - SMALLFONT) // 2),
                label,
                MUTEDCOLOUR,
                SMALLFONT,
            )

    if FULLSCREEN and MEDIAKIND == 'video':

        panel = geometry.get('controls_panel', [0, 0, 0, 0])

        if panel[2] > 0 and panel[3] > 0:

            addrect(commands, 'fullscreencontrolsbackground', panel, PROMPTCOLOUR)
            addtransportcontrols(commands, geometry)

        return commands

    infobox = geometry['info']
    namebox = geometry['name']
    liney = infobox[1]
    infobottom = infobox[1] + infobox[3]

    for index, (name, value, colour, size) in enumerate(metalines(geometry['compact'])):

        if not value:

            continue

        if liney + size > infobottom:

            break

        linewidth = namebox[2] if index == 0 else infobox[2]
        addtext(commands, name, infobox[0], liney, fittext(value, linewidth, size), colour, size)
        liney += size + max(4, GAP // 2)

    message, colour = statusmessage()
    statusbox = geometry['status']
    addtext(commands, 'status', statusbox[0], statusbox[1], fittext(message, statusbox[2], SMALLFONT), colour, SMALLFONT)
    addtransportcontrols(commands, geometry)

    return commands


# graphics functions
def graphicssend(request):

    return sendws(request)


def graphicsconfigure(capabilities):

    global GRAPHICSVIDEO

    surfaces = capabilities.get('video_surfaces', {}) if isinstance(capabilities, dict) else {}
    GRAPHICSVIDEO = dict(surfaces) if isinstance(surfaces, dict) else {}

    return managedconfigure(
        GRAPHICSSTATE,
        capabilities,
        required=('rectangle', 'image', 'text'),
        cpu=GRAPHICSCPU or not os.path.isfile(FONT),
    )


def graphicsdisable(reason, clear=True):

    global GRAPHICSSCENE

    if manageddisable(GRAPHICSSTATE, reason):
        GRAPHICSSCENE = []
        return True
    GRAPHICSSCENE = []

    if clear and WINID is not None:

        sendws({'op': 'GRAPHICS_CLEAR', 'winid': WINID})

    redraw()
    return False


def graphicssuspend():

    global GRAPHICSSCENE

    GRAPHICSSCENE = []

    if GRAPHICSSTATE.get('available') and WINID is not None:

        managedclear(GRAPHICSSTATE, graphicssend, WINID)


def drawcpu(commands):

    for command in commands:

        try:

            kind = command.get('kind')

            if kind == 'rectangle':

                x, y, width, height = command.get('rect', [0, 0, 0, 0])
                fillrectfast(x, y, width, height, command.get('color', BACKGROUND))

            elif kind == 'text':

                drawtextttf(
                    command.get('x', 0),
                    command.get('y', 0),
                    command.get('text', ''),
                    command.get('color', TEXTCOLOUR),
                    command.get('size', FONTSIZE),
                    fontpath=command.get('font', FONT),
                )

            elif kind == 'image':

                x, y, width, height = command.get('rect', [0, 0, 0, 0])
                sourcewidth = int(command.get('source_width', width))
                sourceheight = int(command.get('source_height', height))

                if width == sourcewidth and height == sourceheight:

                    blitfilepartfast(
                        command.get('path', ''),
                        sourcewidth,
                        0,
                        0,
                        sourcewidth,
                        sourceheight,
                        x,
                        y,
                        'BGRA32',
                    )

                else:

                    blitfilescaledfast(
                        command.get('path', ''),
                        sourcewidth,
                        sourceheight,
                        x,
                        y,
                        width,
                        height,
                        'BGRA32',
                    )

        except Exception as error:

            log(f'draw command error {error}')


def cpupresent(commands):

    if BUFFER is None or WINID is None:

        return False

    try:

        drawcpu(commands)
        gfxpresent()
        sendws({
            'op': 'DAMAGE',
            'winid': WINID,
            'rect': [0, 0, int(WINW), int(WINH)],
        })

        return True

    except Exception as error:

        log(f'cpu present error {error}')

        return False


def graphicspump():

    global GRAPHICSSCENE

    wasavailable = bool(GRAPHICSSTATE.get('available'))

    if not managedtick(GRAPHICSSTATE):

        if wasavailable:

            GRAPHICSSCENE = []
            redraw()

        return False

    if not GRAPHICSSTATE.get('available') or WINID is None:

        return False

    if GRAPHICSSTATE.get('pending') or not GRAPHICSSTATE.get('need_submit'):

        return bool(GRAPHICSSTATE.get('active'))

    commands = buildscene()
    beforeavailable = bool(GRAPHICSSTATE.get('available'))
    managedsubmit(GRAPHICSSTATE, graphicssend, WINID, commands)

    if beforeavailable and not GRAPHICSSTATE.get('available'):

        graphicsdisable(GRAPHICSSTATE.get('failure', 'managed graphics submission failed'))

        return False

    if GRAPHICSSTATE.get('pending'):

        GRAPHICSSCENE = commands

    return bool(GRAPHICSSTATE.get('active'))


def render():

    global NEEDREDRAW, GRAPHICSSCENE, REDRAWDAMAGE

    if not NEEDREDRAW or BUFFER is None or WINID is None:

        return False

    commands = buildscene()

    if GRAPHICSSTATE.get('available'):

        GRAPHICSSTATE['need_submit'] = True

        if not REDRAWDAMAGE:

            REDRAWDAMAGE = [[0, 0, WINW, WINH]]

        for damage in REDRAWDAMAGE:

            managedmarkdamage(GRAPHICSSTATE, damage, bounds=(WINW, WINH))

        GRAPHICSSCENE = commands
        graphicspump()

    if not GRAPHICSSTATE.get('active'):

        cpupresent(commands)

    NEEDREDRAW = False
    REDRAWDAMAGE = []

    return True


# window functions
def sendws(message):

    global OUTBUF

    try:

        OUTBUF.extend(json.dumps(message, separators=(',', ':')).encode('utf-8') + b'\n')

        return True

    except Exception as error:

        log(f'window message queue error {error}')

        return False


def flushws():

    global OUTBUF

    if SOCK is None or not OUTBUF:

        return

    try:

        sent = SOCK.send(OUTBUF)

        if sent > 0:

            del OUTBUF[:sent]

    except (BlockingIOError, InterruptedError):

        return

    except Exception as error:

        log(f'window message send error {error}')


def recvws():

    global INBUF, RUNNING

    messages = []

    if SOCK is None:

        return messages

    try:

        data = SOCK.recv(65536)

    except (BlockingIOError, InterruptedError):

        return messages

    except Exception as error:

        log(f'window message receive error {error}')
        RUNNING = False

        return messages

    if not data:

        RUNNING = False

        return messages

    INBUF += data

    while b'\n' in INBUF:

        line, INBUF = INBUF.split(b'\n', 1)

        if not line.strip():

            continue

        try:

            message = json.loads(line.decode('utf-8'))

            if isinstance(message, dict):

                messages.append(message)

        except Exception as error:

            log(f'window message decode error {error}')

    return messages


def connectws():

    global SOCK

    try:

        SOCK = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        SOCK.connect(SOCKPATH)
        SOCK.setblocking(False)
        SELECTOR.register(SOCK, selectors.EVENT_READ | selectors.EVENT_WRITE)

        return True

    except Exception as error:

        log(f'windowserver connection error {error}')

        return False


def createwindow():

    sendws({
        'op': 'CREATE_WINDOW',
        'role': 'window',
        'title': 'player',
        'current': displaytitle(),
        'path': PLAYERPATH,
        'restore_size': False,
        'w': max(scalesize(BASEWINW), 360),
        'h': max(scalesize(BASEWINH), 120),
        'x': 100,
        'y': 100,
        'pid': os.getpid(),
    })


def mapwindow():

    global MAPPED

    if WINID is None:

        return

    sendws({'op': 'MAP', 'winid': WINID})
    sendws({'op': 'RAISE', 'winid': WINID})
    sendws({'op': 'FOCUS_SET', 'winid': WINID})
    MAPPED = True


def setfullscreen(enabled):

    global FULLSCREENREQUEST

    enabled = bool(enabled)

    if WINID is None or (enabled and MEDIAKIND != 'video'):
        return False

    if FULLSCREENREQUEST is not None:
        return False

    if enabled == FULLSCREEN:
        return True

    if not sendws({
        'op': 'WINDOW_FULLSCREEN_SET',
        'winid': WINID,
        'fullscreen': enabled,
    }):
        return False

    FULLSCREENREQUEST = enabled
    return True


def setplaycursor(visible, force=False):

    global VIDEOCURSORVISIBLE

    visible = bool(visible)

    if not force and visible == VIDEOCURSORVISIBLE:
        return True

    if WINID is None:
        VIDEOCURSORVISIBLE = visible
        return False

    if not sendws({
        'op': 'CURSOR_MODE_SET',
        'winid': WINID,
        'mode': 'arrow' if visible else 'hidden',
    }):
        return False

    VIDEOCURSORVISIBLE = visible
    return True


def videopointeractivity(x, y):

    global VIDEOCURSORHIDEAT, VIDEOPOINTERACTIVE, FULLSCREENCONTROLSVISIBLE

    geometry = playbackgeometry()
    videobox = geometry.get('video', [0, 0, 0, 0])
    active = MEDIAKIND == 'video' and (
        FULLSCREEN or pointinrect(int(x), int(y), videobox)
    )

    if not active:

        VIDEOPOINTERACTIVE = False
        VIDEOCURSORHIDEAT = 0.0
        setplaycursor(True)
        return

    VIDEOPOINTERACTIVE = True
    setplaycursor(True)
    VIDEOCURSORHIDEAT = time.monotonic() + VIDEOCURSORDELAY

    if not FULLSCREEN:
        return

    panelheight = max(scalesize(72), ICONSIZE + (PAD * 2))
    controlsvisible = int(y) >= max(0, WINH - panelheight)

    if controlsvisible != FULLSCREENCONTROLSVISIBLE:

        FULLSCREENCONTROLSVISIBLE = controlsvisible
        redraw()


def pumpvideocursor():

    global VIDEOCURSORHIDEAT, VIDEOPOINTERACTIVE, FULLSCREENCONTROLSVISIBLE

    if MEDIAKIND != 'video':

        VIDEOPOINTERACTIVE = False
        VIDEOCURSORHIDEAT = 0.0

        if not VIDEOCURSORVISIBLE:

            setplaycursor(True)

        return

    if (
        not VIDEOPOINTERACTIVE
        or not VIDEOCURSORVISIBLE
        or VIDEOCURSORHIDEAT <= 0.0
        or DRAGGING
        or time.monotonic() < VIDEOCURSORHIDEAT
    ):
        return

    setplaycursor(False)
    VIDEOCURSORHIDEAT = 0.0

    if FULLSCREEN and FULLSCREENCONTROLSVISIBLE:

        FULLSCREENCONTROLSVISIBLE = False
        redraw()


def togglefullscreen():

    desired = not (FULLSCREENREQUEST if FULLSCREENREQUEST is not None else FULLSCREEN)
    return setfullscreen(desired)


def closebuffer():

    filemap = getattr(gfx, '_FILE_MAP', None)

    if filemap:

        try:

            filemap.close()

        except Exception:

            pass

        try:

            setattr(gfx, '_FILE_MAP', None)

        except Exception:

            pass

    filefd = getattr(gfx, '_FILE_FD', None)

    if filefd:

        try:

            os.close(filefd)

        except Exception:

            pass

        try:

            setattr(gfx, '_FILE_FD', None)

        except Exception:

            pass

    try:

        setattr(gfx, '_IS_FILE_BUFFER', False)

    except Exception:

        pass


def resizewindow(message, force=False):

    global WINW, WINH, DRAGGING, PREVIEW

    try:

        width = max(1, int(message.get('w', WINW)))
        height = max(1, int(message.get('h', WINH)))

    except Exception:

        return False

    if not force and width == WINW and height == WINH:

        redraw()
        return False

    graphicssuspend()
    DRAGGING = False
    PREVIEW = None
    WINW = width
    WINH = height

    closebuffer()
    initbuffer(BUFFER, WINW, WINH)

    try:

        initttffont(FONT, FONTSIZE)

    except Exception:

        pass

    redraw()
    schedulevideoquality()
    return True


def handlewelcome(message):

    global SCREENW, SCREENH, NEEDWINDOW

    framebuffer = message.get('fb', {})

    if str(message.get('op', '')) == 'FB_SIZE':

        framebuffer = message

    try:

        SCREENW = max(1, int(framebuffer.get('w', SCREENW)))
        SCREENH = max(1, int(framebuffer.get('h', SCREENH)))

    except Exception:

        pass

    applyscale(SCREENW, SCREENH)

    # WELCOME owns the negotiated graphics capabilities.  FB_SIZE is also
    # routed through this handler, but deliberately contains no graphics
    # object; treating that omission as an empty capability set disabled the
    # retained OpenGL scene and erased the DMA-BUF video transport before
    # playback could start.
    if isinstance(message.get('graphics'), dict):

        graphicsconfigure(message['graphics'])

    if NEEDWINDOW:

        NEEDWINDOW = False
        createwindow()


def handlecreated(message):

    global WINID, BUFFER, WINW, WINH

    WINID = message.get('winid')
    BUFFER = message.get('buffer')
    WINW = max(1, int(message.get('w', WINW)))
    WINH = max(1, int(message.get('h', WINH)))
    initbuffer(BUFFER, WINW, WINH)

    try:

        initttffont(FONT, FONTSIZE)

    except Exception:

        pass

    redraw()


def handlews(message):

    global RUNNING, CLOSING, HASFOCUS
    global FULLSCREEN, FULLSCREENREQUEST, VIDEOCURSORHIDEAT, VIDEOPOINTERACTIVE, FULLSCREENCONTROLSVISIBLE

    operation = str(message.get('op', ''))

    if operation in ('WELCOME', 'FB_SIZE'):

        handlewelcome(message)

        return

    if operation == 'WINDOW_CREATED':

        handlecreated(message)

        return

    if operation in ('GRAPHICS_COMMITTED', 'GRAPHICS_CLEARED'):

        managedresponse(GRAPHICSSTATE, message)

        if not GRAPHICSSTATE.get('available'):

            redraw()

        return

    if operation == 'ERROR':

        if str(message.get('code', '')).startswith('graphics_'):

            managedresponse(GRAPHICSSTATE, message)
            log(
                'retained graphics error '
                f'code={message.get("code", "")} '
                f'detail={message.get("detail", "")}'
            )
            redraw()

        if str(message.get('code', '')) == 'fullscreen_denied':
            FULLSCREENREQUEST = None

        return

    if operation == 'RESIZED':

        resizewindow(message)

        return

    if operation == 'WINDOW_STATE':

        if message.get('winid') == WINID:

            previous = FULLSCREEN
            FULLSCREEN = bool(message.get('fullscreen')) or str(message.get('state', '')) == 'fullscreen'
            FULLSCREENREQUEST = None
            changed = FULLSCREEN != previous

            if changed:

                VIDEOCURSORHIDEAT = 0.0
                VIDEOPOINTERACTIVE = FULLSCREEN and MEDIAKIND == 'video'
                FULLSCREENCONTROLSVISIBLE = False

            if 'w' in message and 'h' in message:

                resizewindow(message, force=changed)

            else:

                redraw()
                schedulevideoquality()

            if changed:

                setplaycursor(not FULLSCREEN, force=True)

        return

    if operation == 'DAMAGE':

        redraw()

        return

    if operation == 'FOCUS':

        focusstate = str(message.get('state', 'in')).strip().lower()
        HASFOCUS = focusstate in ('in', 'focused', 'focus', '1', 'true')
        redraw()

        return

    if operation == 'POINTER_BUTTON':

        handlebutton(message)

        return

    if operation == 'POINTER_MOTION':

        handlemotion(message)

        return

    if operation == 'KEY':

        handlekey(message)

        return

    if operation == 'CLOSE':

        CLOSING = True
        RUNNING = False
        sendws({'op': 'CLOSE_ACK', 'pid': os.getpid()})

        return

    if operation == 'WINDOW_DESTROYED':

        CLOSING = True
        RUNNING = False


# input functions
def leftbutton(message):

    try:

        button = message.get('button', 1)

        return button in (1, '1', 'left', 'LEFT')

    except Exception:

        return True


def handlebutton(message):

    global DRAGGING, PREVIEW, POSITION, LASTVIDEOCLICK, LASTVIDEOCLICKPOS

    if not leftbutton(message):

        return

    try:

        x = int(message.get('x', 0))
        y = int(message.get('y', 0))
        down = str(message.get('state', 'down')).lower() == 'down'

    except Exception:

        return

    videopointeractivity(x, y)

    geometry = playbackgeometry()

    if not down:

        if DRAGGING:

            position = positionfromx(x)
            PREVIEW = position
            DRAGGING = False
            seekplay(position)
            PREVIEW = None
            redraw()

        return

    videobox = geometry.get('video', [0, 0, 0, 0])
    controlpanel = geometry.get('controls_panel', [0, 0, 0, 0])

    if MEDIAKIND == 'video' and pointinrect(x, y, videobox) and not pointinrect(x, y, controlpanel):

        now = time.monotonic()
        distance = max(abs(x - LASTVIDEOCLICKPOS[0]), abs(y - LASTVIDEOCLICKPOS[1]))
        doubleclick = (now - LASTVIDEOCLICK) <= 0.40 and distance <= scalesize(10)
        LASTVIDEOCLICK = now
        LASTVIDEOCLICKPOS = [x, y]

        if doubleclick:

            LASTVIDEOCLICK = 0.0
            togglefullscreen()
            return

    if pointinrect(x, y, geometry.get('stop')):

        stopplay(cancel=True)

        return

    if pointinrect(x, y, geometry.get('toggle')):

        toggleplay()

        return

    if pointinrect(x, y, geometry.get('trackhit')):

        if playbackactive() and PLAYSTATE not in ('loading', 'stopping') and DURATION > 0.0:

            DRAGGING = True
            PREVIEW = positionfromx(x)
            redraw()


def handlemotion(message):

    global PREVIEW

    try:

        x = int(message.get('x', 0))
        y = int(message.get('y', 0))

    except Exception:

        return

    videopointeractivity(x, y)

    if not DRAGGING:

        return

    PREVIEW = positionfromx(x)
    redraw()


def cycletrack(kind):

    if kind not in ('video', 'audio') or not TRACKPATH:

        return False

    tracks = TRACKINFO.get(f'{kind}_tracks', [])

    if not isinstance(tracks, list) or len(tracks) < 2:

        return False

    indexes = [
        int(track.get('index'))
        for track in tracks
        if isinstance(track, dict) and track.get('index') is not None
    ]

    if len(indexes) < 2:

        return False

    key = f'{kind}_stream_index'
    selected = SELECTEDTRACKS.get(key)

    try:

        nextindex = indexes[(indexes.index(int(selected)) + 1) % len(indexes)]

    except (TypeError, ValueError):

        nextindex = indexes[0]

    options = dict(SELECTEDTRACKS)
    options[key] = nextindex
    options['startseconds'] = max(0.0, float(POSITION))
    return startplay(TRACKPATH, playoptions=options)


def handlekey(message):

    if not HASFOCUS:

        return

    try:

        key = str(message.get('key', '')).upper()
        state = str(message.get('state', 'down')).lower()
        modifiers = message.get('mods', {})
        ctrl = bool(modifiers.get('ctrl'))

    except Exception:

        return

    if state not in ('down', 'repeat'):

        return

    repeat = state == 'repeat'

    if repeat and key not in ('LEFT', 'RIGHT'):

        return

    if ctrl and key == 'S':

        stopplay(cancel=True)

        return

    if key in ('SPACE', ' ', 'PLAYPAUSE'):

        toggleplay()

        return

    if key == 'M':

        togglemute()

        return

    if key == 'A' and MEDIAKIND == 'video':

        cycletrack('audio')

        return

    if key == 'V' and MEDIAKIND == 'video':

        cycletrack('video')

        return

    if key in ('ENTER', 'RETURN') and MEDIAKIND == 'video':

        togglefullscreen()

        return

    if key in ('ESC', 'ESCAPE') and (FULLSCREEN or FULLSCREENREQUEST is True):

        setfullscreen(False)

        return

    if key == 'LEFT':

        seekplay(POSITION - 5.0)

        return

    if key == 'RIGHT':

        seekplay(POSITION + 5.0)


# diagnostic functions
def metadatadiagnostic(path):

    global WINW, WINH, TRACKPATH, TRACKNAME, TRACKINFO, ARTWORK, PLAYSTATE
    global POSITION, DURATION, MEDIAKIND

    result = {
        'format': 1,
        'passed': False,
        'checks': {},
        'errors': [],
    }
    artwork = {}

    try:

        target, error = normalisefile(path)

        if error:

            raise RuntimeError(error)

        applyscale(1920, 1080)
        infoworker(1, target)
        event = PLAYEVENTS.get(timeout=30.0)

        if event.get('kind') != 'info' or int(event.get('generation', 0)) != 1:

            raise RuntimeError('player metadata worker returned an invalid event')

        info = event.get('info', {})
        artwork = event.get('artwork', {})
        tags = info.get('tags', {}) if isinstance(info, dict) else {}

        if not info.get('format') or not info.get('codec') or not tags.get('title') or not tags.get('artist') or not tags.get('album'):

            raise RuntimeError(f'player metadata worker did not return modern track fields: {info}')

        result['checks']['metadata'] = {
            'title': tags.get('title'),
            'artist': tags.get('artist'),
            'album': tags.get('album'),
            'format': info.get('format'),
            'codec': info.get('codec'),
            'sample_rate': info.get('sample_rate'),
            'bit_depth': info.get('bit_depth'),
            'channels': info.get('channels'),
            'bit_rate': info.get('bit_rate'),
        }
        size = artwork.get('surface_size', []) if isinstance(artwork, dict) else []
        output = str(artwork.get('output', '') or '') if isinstance(artwork, dict) else ''

        if len(size) != 2 or int(size[0]) < 1 or int(size[1]) < 1 or not os.path.isfile(output):

            raise RuntimeError(f'player did not decode embedded artwork: {artwork}')

        if os.path.getsize(output) != int(size[0]) * int(size[1]) * 4:

            raise RuntimeError('player embedded artwork surface has the wrong size')

        result['checks']['artwork'] = {
            'surface': [int(size[0]), int(size[1])],
            'format': artwork.get('format'),
        }
        WINW = BASEWINW
        WINH = BASEWINH
        TRACKPATH = target
        TRACKNAME = os.path.basename(target)
        TRACKINFO = dict(info)
        MEDIAKIND = str(TRACKINFO.get('kind', 'audio') or 'audio')
        ARTWORK = dict(artwork)
        PLAYSTATE = 'playing'
        POSITION = 0.0
        DURATION = max(0.0, float(info.get('duration', 0.0) or 0.0))
        scene = buildscene()

        if not any(command.get('id') == 'artwork' and command.get('kind') == 'image' for command in scene):

            raise RuntimeError('player did not place decoded artwork in its scene')

        if not any(command.get('id') == 'trackname' and command.get('text') == tags.get('title') for command in scene):

            raise RuntimeError('player did not place the metadata title in its scene')

        result['checks']['scene'] = True
        result['passed'] = True

    except Exception as error:

        result['errors'].append(str(error))

    finally:

        discardart(artwork)

        try:

            if os.path.isdir(INFOROOT) and not os.path.islink(INFOROOT):

                os.rmdir(INFOROOT)

        except Exception:

            pass

    print(json.dumps(result, sort_keys=True, separators=(',', ':')))
    return 0 if result.get('passed') else 1


def diagnosticplay(
    path,
    statuscallback=None,
    framecallback=None,
    controls=False,
    maximumwidth=1280,
    maximumheight=720,
    retainframe=False,
    infocallback=None,
    video_transport=None,
):

    if infocallback is not None:

        infocallback(diagnosticinfo(path))

    if statuscallback is not None:

        statuscallback({
            'type': 'media_status',
            'media_kind': 'audio',
            'state': 'playing',
            'position': 0.1,
            'duration': 0.25,
            'control': '/.ephemeral/audio/diagnostic.sock',
            'path': path,
        })

    return {'path': path, 'kind': 'audio', 'duration': 0.25}


def diagnosticinfo(path):

    return {
        'version': 1,
        'kind': 'audio',
        'path': path,
        'format': 'FLAC',
        'codec': 'FLAC',
        'duration': 0.25,
        'sample_rate': 48000,
        'bit_depth': 16,
        'channels': 'stereo',
        'lossless': True,
        'file_size': os.path.getsize(path),
        'artwork': False,
        'tags': {
            'title': 'Worker Metadata',
            'artist': 'Background Reader',
        },
    }


def graphicsdiagnostic():

    global WINW, WINH, TRACKPATH, TRACKNAME, TRACKINFO, ARTWORK, PLAYSTATE, POSITION, DURATION
    global DRAGGING, PREVIEW
    global BUFFER, INFOTHREAD, MEDIAKIND, VIDEOFRAME, VIDEORESIZED
    global GRAPHICSVIDEO, VIDEOTRANSPORT
    global WINID, CONTROLPATH, FULLSCREEN, FULLSCREENREQUEST, MUTED
    global LASTVIDEOCLICK, LASTVIDEOCLICKPOS, ARTWORKPENDING
    global VIDEOCURSORVISIBLE, VIDEOCURSORHIDEAT, VIDEOPOINTERACTIVE, FULLSCREENCONTROLSVISIBLE

    result = {
        'format': 1,
        'passed': False,
        'checks': {},
        'errors': [],
    }
    diagnosticpath = f'/the one/logs/.player graphics {os.getpid()}.bgra'
    diagnosticart = f'/the one/logs/.player artwork {os.getpid()}.bgra'
    diagnosticvideo = f'/.ephemeral/player-video-{os.getpid()}.bgra'

    try:

        applyscale(1920, 1080)

        if (
            BACKGROUND,
            TEXTCOLOUR,
            PROMPTCOLOUR,
            TRACKCOLOUR,
            MUTEDCOLOUR,
            ERRORCOLOUR,
        ) != (0x000000, 0xEFEFEF, 0x242424, 0x3A3A3A, 0x6A6A6A, 0xFF0000):

            raise RuntimeError('player palette does not match Array')

        result['checks']['array_palette'] = True
        WINW = 780
        WINH = 370
        MEDIAKIND = 'audio'
        compactdecode = videodecodelimits()
        predicteddecode = initialvideodecodelimits()
        expectedwindow = videowindowsize()
        WINW, WINH = expectedwindow
        MEDIAKIND = 'video'
        expandeddecode = videodecodelimits()

        if (
            expandeddecode[0] <= compactdecode[0]
            or expandeddecode[1] <= compactdecode[1]
            or expandeddecode[0] > SCREENW
            or expandeddecode[1] > SCREENH
            or not substantialvideochange(compactdecode, expandeddecode)
            or substantialvideochange(predicteddecode, expandeddecode)
        ):

            raise RuntimeError(
                'player adaptive video decode sizing is invalid: '
                f'{compactdecode}/{predicteddecode}/{expandeddecode}'
            )

        result['checks']['adaptive_video_decode'] = {
            'compact': compactdecode,
            'initial': predicteddecode,
            'expanded': expandeddecode,
            'window': expectedwindow,
            'framebuffer': [SCREENW, SCREENH],
        }
        WINW = 780
        WINH = 370
        TRACKPATH = '/master/music/Signal Fires.flac'
        TRACKNAME = 'Signal Fires.flac'
        MEDIAKIND = 'audio'
        VIDEOFRAME = {}
        VIDEORESIZED = False
        TRACKINFO = {
            'format': 'FLAC',
            'codec': 'FLAC',
            'lossless': True,
            'bit_depth': 24,
            'sample_rate': 96000,
            'channels': 'stereo',
            'bit_rate': 2304,
            'file_size': 52428800,
            'tags': {
                'title': 'Signal Fires',
                'artist': 'The Diagnostics',
                'album': 'Native Audio',
                'albumartist': 'T1OS Ensemble',
                'composer': 'Ada Signal',
                'genre': 'Electronic',
                'date': '2026',
                'track': '3/12',
                'disc': '1/2',
            },
        }
        os.makedirs(os.path.dirname(diagnosticart), exist_ok=True)
        artwidth = 120
        artheight = 120
        artpixel = b'\xd2\x50\x1e\xff'

        with open(diagnosticart, 'wb') as stream:

            stream.write(artpixel * artwidth * artheight)

        ARTWORK = {
            'output': diagnosticart,
            'surface_size': [artwidth, artheight],
            'pixel_format': 'BGRA32',
        }
        PLAYSTATE = 'playing'
        POSITION = 30.0
        DURATION = 120.0
        geometry = playbackgeometry()

        if geometry['track'][2] <= 20:

            raise RuntimeError('player timeline is too narrow')

        expected = geometry['track'][0] + int(geometry['track'][2] * 0.25)

        if abs((geometry['thumb'][0] + THUMBSIZE // 2) - expected) > 1:

            raise RuntimeError('player thumb does not reflect playback position')

        if abs(positionfromx(geometry['track'][0] + geometry['track'][2] // 2) - 60.0) > 1.0:

            raise RuntimeError('player seek geometry is not proportional')

        result['checks']['geometry'] = True
        scene = buildscene()
        ids = set(str(command.get('id', '')) for command in scene)

        if 'background' not in ids or 'pauseleft' not in ids or 'pauseright' not in ids or 'artwork' not in ids:

            raise RuntimeError('playing scene is missing native controls or artwork')

        expectedids = {'trackname', 'artist', 'album', 'details', 'credits', 'technical'}

        if not expectedids.issubset(ids):

            raise RuntimeError(f'player metadata scene is incomplete: {sorted(ids)}')

        if displaytitle() != 'Signal Fires' or '24-bit' not in displaytechnical() or '96 kHz' not in displaytechnical():

            raise RuntimeError('player metadata presentation is invalid')

        result['checks']['metadata_scene'] = True
        result['checks']['embedded_artwork'] = True

        textcommands = [command for command in scene if command.get('kind') == 'text']

        if not textcommands or any(command.get('font') != FONT for command in textcommands):

            raise RuntimeError('player interface did not consistently use Atkinson Hyperlegible Next')

        result['checks']['playing_scene'] = True
        result['checks']['atkinson_font'] = True
        GRAPHICSSTATE.clear()
        GRAPHICSSTATE.update(managedstate())
        capabilities = {
            'version': 2,
            'accelerated': True,
            'managed_resources': True,
            'atomic_scene': True,
            'retained_scene': True,
            'stable_node_ids': True,
            'damage_regions': True,
            'commands': ['rectangle', 'image', 'text', 'video'],
            'command_limit': 1024,
            'text_limit': 1024,
            'damage_limit': 64,
            'video_surfaces': {
                'available': True,
                'socket': '/.ephemeral/windowserver/video.sock',
                'zero_copy_decode': True,
                'gpu_copy_composition': True,
            },
        }

        if not graphicsconfigure(capabilities):

            raise RuntimeError(f'player managed capability negotiation failed {GRAPHICSSTATE.get("failure", "")}')

        requests = []
        managedmarkdamage(GRAPHICSSTATE, [0, 0, WINW, WINH], bounds=(WINW, WINH))
        managedsubmit(GRAPHICSSTATE, lambda request: requests.append(request) or True, 99, scene)

        if len(requests) != 1 or requests[0].get('op') != 'GRAPHICS_SCENE':

            raise RuntimeError('player did not submit one atomic managed scene')

        managedresponse(GRAPHICSSTATE, {
            'op': 'GRAPHICS_COMMITTED',
            'winid': 99,
            'count': len(scene),
            'batch': True,
            'accelerated': True,
        })

        if not GRAPHICSSTATE.get('active') or GRAPHICSSTATE.get('pending'):

            raise RuntimeError('player managed scene did not become active')

        cpustate = managedstate(cpu=True)

        if managedconfigure(cpustate, capabilities, required=('rectangle', 'image', 'text'), cpu=True):

            raise RuntimeError('player CPU override enabled managed rendering')

        missingstate = managedstate()

        if managedconfigure(missingstate, {}, required=('rectangle', 'image', 'text')):

            raise RuntimeError('player accepted missing managed capabilities')

        errorstate = managedstate()
        managedconfigure(errorstate, capabilities, required=('rectangle', 'image', 'text'))
        errorstate['pending'] = True
        managedresponse(errorstate, {'op': 'ERROR', 'code': 'graphics_scene_failed'})

        if (
            not errorstate.get('available')
            or not errorstate.get('active')
            or not errorstate.get('managed_only')
            or not errorstate.get('need_submit')
        ):

            raise RuntimeError('player escaped strict GPU rendering after a server error')

        timeoutstate = managedstate()
        managedconfigure(timeoutstate, capabilities, required=('rectangle', 'image', 'text'))
        timeoutstate['pending'] = True
        timeoutstate['pending_at'] = time.monotonic() - 10.0

        if (
            not managedtick(timeoutstate, timeout=0.1)
            or not timeoutstate.get('active')
            or not timeoutstate.get('managed_only')
            or not timeoutstate.get('need_submit')
        ):

            raise RuntimeError('player escaped strict GPU rendering after a commit timeout')

        result['checks']['managed_graphics'] = True
        result['checks']['error_gpu_retention'] = True
        result['checks']['timeout_gpu_retention'] = True
        result['checks']['cpu_fallback'] = True
        PLAYSTATE = 'paused'
        paused = buildscene()

        if not any(str(command.get('id', '')).startswith('play') for command in paused):

            raise RuntimeError('paused scene is missing the play control')

        result['checks']['paused_scene'] = True
        DRAGGING = True
        PREVIEW = 90.0

        if '1:30 / 2:00' != playbackgeometry()['time'][2]:

            raise RuntimeError('drag preview time is incorrect')

        DRAGGING = False
        PREVIEW = None
        result['checks']['drag_preview'] = True

        if formattime(3661) != '1:01:01' or formattime(61) != '1:01':

            raise RuntimeError('audio time formatting is incorrect')

        result['checks']['time_format'] = True
        WINW = 360
        WINH = 120
        narrow = playbackgeometry()

        if narrow['track'][2] < 12 or narrow['toggle'][0] <= narrow['stop'][0]:

            raise RuntimeError('compact player geometry is invalid')

        result['checks']['compact_layout'] = True
        WINW = 780
        WINH = 370
        cpuscene = buildscene()
        handlews({'op': 'FOCUS', 'state': 'out'})

        if HASFOCUS:

            raise RuntimeError('player accepted input focus after focus-out')

        handlews({'op': 'FOCUS', 'state': 'in'})

        if not HASFOCUS:

            raise RuntimeError('player did not restore input focus')

        result['checks']['focus_input'] = True
        os.makedirs(os.path.dirname(diagnosticpath), exist_ok=True)

        with open(diagnosticpath, 'wb') as stream:

            stream.truncate(WINW * WINH * 4)

        BUFFER = diagnosticpath
        initbuffer(BUFFER, WINW, WINH)
        drawcpu(cpuscene)
        gfxpresent()

        with open(diagnosticpath, 'rb') as stream:

            pixels = stream.read()

        if len(pixels) != WINW * WINH * 4 or not any(pixels):

            raise RuntimeError('player CPU fallback did not paint its controls')

        cpuart = artplacement(playbackgeometry()['art'])
        artx = cpuart[0] + cpuart[2] // 2
        arty = cpuart[1] + cpuart[3] // 2
        artoffset = ((arty * WINW) + artx) * 4

        if pixels[artoffset:artoffset + 4] != artpixel:

            raise RuntimeError('player CPU fallback did not paint embedded artwork')

        result['checks']['cpu_paint'] = True
        originalplay = mediaapi.play
        originalinfo = mediaapi.mediainfo

        try:

            mediaapi.play = diagnosticplay
            mediaapi.mediainfo = diagnosticinfo

            if not startplay(diagnosticpath):

                raise RuntimeError('player did not start a path containing spaces')

            worker = PLAYTHREAD

            if worker is None:

                raise RuntimeError('player did not create its playback worker')

            worker.join(timeout=1.0)
            drainplayevents()

            if PLAYSTATE != 'complete' or TRACKPATH != diagnosticpath or POSITION != DURATION:

                raise RuntimeError('player worker did not reach a clean completed state')

            technical = displaytechnical()

            if metavalue('title') != 'Worker Metadata' or not all(value in technical for value in ('FLAC', 'Lossless', '16-bit', '48 kHz', 'Stereo')):

                raise RuntimeError(f'player did not apply asynchronous metadata: {TRACKINFO}')

            if not PENDINGART:

                raise RuntimeError('player did not defer artwork work until playback was buffered')

            pendingartscene = buildscene()
            pendinglabels = [
                command.get('text')
                for command in pendingartscene
                if command.get('id') == 'artplaceholder'
            ]

            if pendinglabels != ['loading artwork']:
                raise RuntimeError(f'player exposed a false no-artwork state while extraction was pending: {pendinglabels}')

            result['checks']['metadata_worker'] = True
            result['checks']['deferred_artwork'] = True
            result['checks']['pending_artwork_state'] = True

            completedposition = POSITION
            PLAYEVENTS.put({
                'kind': 'status',
                'generation': PLAYGEN - 1,
                'status': {
                    'type': 'audio_status',
                    'state': 'playing',
                    'position': 0.0,
                    'duration': 1.0,
                },
            })
            drainplayevents()

            if POSITION != completedposition or PLAYSTATE != 'complete':

                raise RuntimeError('player accepted stale playback status')

        finally:

            mediaapi.play = originalplay
            mediaapi.mediainfo = originalinfo
            shutdownplay()
            shutdowninfo()

        result['checks']['playback_lifecycle'] = True
        WINW = 780
        WINH = 370
        MEDIAKIND = 'video'
        TRACKPATH = '/master/videos/Signal Film.mp4'
        TRACKNAME = 'Signal Film.mp4'
        TRACKINFO = {
            'kind': 'video',
            'format': 'MP4',
            'file_size': 8388608,
            'tags': {
                'title': 'Signal Film',
                'artist': 'The Diagnostics',
            },
            'video': {
                'codec': 'H264',
                'profile': 'High',
                'display_width': 1920,
                'display_height': 1080,
                'frame_rate': 23.976,
                'bit_depth': 10,
            },
            'audio': {
                'codec': 'AAC',
                'sample_rate': 48000,
                'channels': 'stereo',
            },
        }
        PLAYSTATE = 'paused'
        videopixel = bytes((0x33, 0x66, 0x99, 0xff))
        os.makedirs(os.path.dirname(diagnosticvideo), exist_ok=True)

        with open(diagnosticvideo, 'wb') as stream:

            stream.write(videopixel * 4)

        VIDEOFRAME = {
            'type': 'media_frame',
            'path': diagnosticvideo,
            'width': 2,
            'height': 2,
            'frame': 1,
            'generation': 0,
        }
        videoscene = buildscene()

        if not any(
            command.get('id') == 'videoframe'
            and command.get('kind') == 'image'
            and command.get('revision') == 1
            for command in videoscene
        ):

            raise RuntimeError('player video scene did not include the decoded frame revision')

        VIDEOFRAME = {
            'type': 'media_frame',
            'surface': True,
            'stream': 'diagnostic-video-stream',
            'width': 1920,
            'height': 1080,
            'frame': 2,
            'generation': 0,
        }
        VIDEOTRANSPORT = {
            'socket': '/.ephemeral/windowserver/video.sock',
            'stream': 'diagnostic-video-stream',
        }
        surfacescene = buildscene()

        if not any(
            command.get('id') == 'videoframe'
            and command.get('kind') == 'video'
            and command.get('stream') == 'diagnostic-video-stream'
            for command in surfacescene
        ):

            raise RuntimeError('player video scene did not retain the native GPU surface stream')

        if any(
            command.get('id') == 'videoframe'
            and command.get('kind') == 'image'
            for command in surfacescene
        ):

            raise RuntimeError('player copied a native GPU video surface into an image scene')

        result['checks']['video_surface_scene'] = True
        FULLSCREEN = True
        FULLSCREENCONTROLSVISIBLE = False
        fullscreenscene = buildscene()
        fullscreenvideo = next(
            (
                command
                for command in fullscreenscene
                if command.get('id') == 'videoframe'
            ),
            None,
        )

        if (
            fullscreenvideo is None
            or fullscreenvideo.get('clip') != [0, 0, WINW, WINH]
            or any(command.get('id') in ('open', 'stop', 'track', 'time') for command in fullscreenscene)
        ):
            raise RuntimeError('player fullscreen scene retained windowed chrome or controls')

        FULLSCREEN = False
        FULLSCREENREQUEST = None
        result['checks']['fullscreen_video_scene'] = True

        originalsendcontrol = audioapi.sendcontrol
        originalsendws = globals()['sendws']
        inputcontrols = []
        windowrequests = []

        try:

            audioapi.sendcontrol = lambda path, command, **values: inputcontrols.append((path, command, values)) or True
            globals()['sendws'] = lambda message: windowrequests.append(dict(message)) or True
            WINID = 99
            CONTROLPATH = '/.ephemeral/audio/diagnostic.sock'
            PLAYSTATE = 'playing'
            MUTED = False
            handlekey({'key': 'PLAYPAUSE', 'state': 'down', 'mods': {}})
            handlekey({'key': 'M', 'state': 'down', 'mods': {}})
            handlekey({'key': 'ENTER', 'state': 'down', 'mods': {}})

            if (
                [value[1] for value in inputcontrols[:2]] != ['pause', 'mute']
                or not MUTED
                or not windowrequests
                or windowrequests[-1].get('op') != 'WINDOW_FULLSCREEN_SET'
                or not windowrequests[-1].get('fullscreen')
            ):
                raise RuntimeError('player hardcoded media play/pause, M, or Enter binding failed')

            handlews({
                'op': 'WINDOW_STATE',
                'winid': WINID,
                'state': 'fullscreen',
                'fullscreen': True,
            })

            if (
                not windowrequests
                or windowrequests[-1].get('op') != 'CURSOR_MODE_SET'
                or windowrequests[-1].get('mode') != 'hidden'
            ):
                raise RuntimeError('player did not hide the cursor on fullscreen entry')

            handlemotion({'x': WINW // 2, 'y': WINH - 1})
            fullscreencontrolscene = buildscene()
            fullscreencontrolids = set(str(command.get('id', '')) for command in fullscreencontrolscene)

            if (
                not FULLSCREENCONTROLSVISIBLE
                or windowrequests[-1].get('op') != 'CURSOR_MODE_SET'
                or windowrequests[-1].get('mode') != 'arrow'
                or not {'fullscreencontrolsbackground', 'stop', 'track', 'time'}.issubset(fullscreencontrolids)
            ):
                raise RuntimeError('player did not reveal its fullscreen cursor and transport controls on bottom-edge motion')

            togglerect = playbackgeometry()['toggle']
            requestcount = len(windowrequests)
            handlebutton({
                'button': 1,
                'state': 'down',
                'x': togglerect[0] + togglerect[2] // 2,
                'y': togglerect[1] + togglerect[3] // 2,
            })

            if (
                not inputcontrols
                or inputcontrols[-1][1] != 'resume'
                or len(windowrequests) != requestcount
            ):
                raise RuntimeError('player fullscreen transport controls were not usable')

            VIDEOCURSORHIDEAT = time.monotonic() - 0.1
            pumpvideocursor()

            if (
                VIDEOCURSORVISIBLE
                or FULLSCREENCONTROLSVISIBLE
                or windowrequests[-1].get('op') != 'CURSOR_MODE_SET'
                or windowrequests[-1].get('mode') != 'hidden'
            ):
                raise RuntimeError('player did not hide its fullscreen cursor and controls after two seconds idle')

            handlekey({'key': 'ESC', 'state': 'down', 'mods': {}})

            if not windowrequests or windowrequests[-1].get('fullscreen') is not False:
                raise RuntimeError('player Escape binding did not exit fullscreen')

            handlews({
                'op': 'WINDOW_STATE',
                'winid': WINID,
                'state': 'normal',
                'fullscreen': False,
            })

            if (
                not VIDEOCURSORVISIBLE
                or windowrequests[-1].get('op') != 'CURSOR_MODE_SET'
                or windowrequests[-1].get('mode') != 'arrow'
                or not {'stop', 'track', 'time'}.issubset(
                    set(str(command.get('id', '')) for command in buildscene())
                )
            ):
                raise RuntimeError('player did not restore its cursor and complete windowed scene after fullscreen')

            videobox = playbackgeometry()['video']
            clickx = videobox[0] + max(0, videobox[2] // 2)
            clicky = videobox[1] + max(0, videobox[3] // 2)
            handlemotion({'x': clickx, 'y': clicky})
            VIDEOCURSORHIDEAT = time.monotonic() - 0.1
            pumpvideocursor()

            if (
                VIDEOCURSORVISIBLE
                or not VIDEOPOINTERACTIVE
                or windowrequests[-1].get('op') != 'CURSOR_MODE_SET'
                or windowrequests[-1].get('mode') != 'hidden'
            ):
                raise RuntimeError('player did not hide the idle cursor over windowed video')

            togglerect = playbackgeometry()['toggle']
            handlemotion({
                'x': togglerect[0] + togglerect[2] // 2,
                'y': togglerect[1] + togglerect[3] // 2,
            })

            if (
                not VIDEOCURSORVISIBLE
                or VIDEOPOINTERACTIVE
                or windowrequests[-1].get('op') != 'CURSOR_MODE_SET'
                or windowrequests[-1].get('mode') != 'arrow'
            ):
                raise RuntimeError('player did not restore the cursor outside windowed video')

            LASTVIDEOCLICK = 0.0
            LASTVIDEOCLICKPOS = [0, 0]
            handlebutton({'button': 1, 'state': 'down', 'x': clickx, 'y': clicky})
            handlebutton({'button': 1, 'state': 'down', 'x': clickx, 'y': clicky})

            if not windowrequests or windowrequests[-1].get('fullscreen') is not True:
                raise RuntimeError('player video double-click binding did not enter fullscreen')

        finally:

            audioapi.sendcontrol = originalsendcontrol
            globals()['sendws'] = originalsendws
            FULLSCREEN = False
            FULLSCREENREQUEST = None
            VIDEOCURSORVISIBLE = True
            VIDEOCURSORHIDEAT = 0.0
            VIDEOPOINTERACTIVE = False
            FULLSCREENCONTROLSVISIBLE = False
            WINID = None

        result['checks']['hardcoded_media_bindings'] = True
        result['checks']['fullscreen_cursor_controls'] = True
        result['checks']['fullscreen_exit_repaint'] = True
        result['checks']['windowed_video_cursor'] = True
        VIDEOFRAME = {
            'type': 'media_frame',
            'path': diagnosticvideo,
            'width': 2,
            'height': 2,
            'frame': 1,
            'generation': 0,
        }
        VIDEOTRANSPORT = {}
        technical = displaytechnical()

        if not all(value in technical for value in ('MP4', 'H264 High', '1920×1080', '23.976 fps', '10-bit', 'AAC', '48 kHz', 'Stereo')):

            raise RuntimeError(f'player video technical metadata is incomplete: {technical}')

        closebuffer()

        with open(diagnosticpath, 'wb') as stream:

            stream.truncate(WINW * WINH * 4)

        BUFFER = diagnosticpath
        initbuffer(BUFFER, WINW, WINH)
        drawcpu(videoscene)
        gfxpresent()
        video = videoplacement(playbackgeometry()['video'])
        samplex = video[0] + video[2] // 2
        sampley = video[1] + video[3] // 2

        with open(diagnosticpath, 'rb') as stream:

            stream.seek(((sampley * WINW) + samplex) * 4)
            sample = stream.read(4)

        if sample != videopixel:

            raise RuntimeError('player CPU fallback did not scale the decoded video frame')

        result['checks']['video_scene'] = True
        result['checks']['video_cpu_paint'] = True
        result['passed'] = all(result['checks'].values())

    except Exception as error:

        result['errors'].append(str(error))

    finally:

        closebuffer()

        try:

            if os.path.exists(diagnosticpath):

                os.remove(diagnosticpath)

            if os.path.exists(diagnosticart):

                os.remove(diagnosticart)

            if os.path.exists(diagnosticvideo):

                os.remove(diagnosticvideo)

        except Exception:

            pass

    print(json.dumps(result, sort_keys=True, separators=(',', ':')))

    return 0 if result.get('passed') else 1


# core functions
def termhandler(signum=None, frame=None):

    global RUNNING, CLOSING

    CLOSING = True
    RUNNING = False

    try:

        stopplay()

    except Exception:

        pass


def initialise():

    if not connectws():

        return False

    sendws({'op': 'HELLO'})
    sendws({'op': 'SUBSCRIBE', 'types': ['fbsize']})

    while RUNNING and WINID is None:

        events = SELECTOR.select(timeout=0.1)

        for key, mask in events:

            if key.fileobj is SOCK and mask & selectors.EVENT_READ:

                for message in recvws():

                    handlews(message)

            if key.fileobj is SOCK and mask & selectors.EVENT_WRITE:

                flushws()

        flushws()

    if WINID is None:

        return False

    render()
    flushws()
    mapwindow()
    flushws()

    return True


def mainloop():

    while RUNNING:

        timeout = 0.008 if MEDIAKIND == 'video' and playbackactive() else 0.02
        events = SELECTOR.select(timeout=timeout)

        for key, mask in events:

            if key.fileobj is not SOCK:

                continue

            if mask & selectors.EVENT_READ:

                for message in recvws():

                    handlews(message)

            if mask & selectors.EVENT_WRITE:

                flushws()

        drainplayevents()
        pumpvideoquality()
        pumpvideocursor()
        startpendingartwork()
        render()
        graphicspump()
        flushws()


def cleanup():

    shutdownplay()
    shutdowninfo()
    clearart()
    clearvideo()

    try:

        root = os.path.abspath(INFOROOT)

        if root.startswith('/.ephemeral/player/') and os.path.isdir(root) and not os.path.islink(root):

            shutil.rmtree(root, ignore_errors=True)

    except Exception:

        pass

    if WINID is not None and GRAPHICSSTATE.get('available'):

        try:

            managedclear(GRAPHICSSTATE, graphicssend, WINID)
            flushws()

        except Exception:

            pass

    if SOCK is not None:

        try:

            SELECTOR.unregister(SOCK)

        except Exception:

            pass

        try:

            SOCK.close()

        except Exception:

            pass

    closebuffer()


def main(path=''):

    signal.signal(signal.SIGTERM, termhandler)
    signal.signal(signal.SIGINT, termhandler)

    try:

        if not initialise():

            return 1

        if path:

            startplay(path)

        mainloop()

    except Exception as error:

        log(f'fatal player error {error}')

        return 1

    finally:

        cleanup()

    return 0


if __name__ == '__main__':

    arguments = list(sys.argv[1:])

    if arguments and str(arguments[0]).strip().lower() == 'graphics-diagnostic':

        sys.exit(graphicsdiagnostic())

    if arguments and str(arguments[0]).strip().lower() == 'metadata-diagnostic':

        metadatapath = ' '.join(str(argument) for argument in arguments[1:]).strip()
        sys.exit(metadatadiagnostic(metadatapath))

    launchpath = ' '.join(str(argument) for argument in arguments).strip()
    sys.exit(main(launchpath))
