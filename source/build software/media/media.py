


"""
media.py

media is the audio and video playback API of The One OS.
"""



## imports
import os
import sys
import time
import json
import math
import queue
import re
import signal
import shutil
import threading
import subprocess
import functools
import mmap
import glob
import socket
import struct
import array
import ctypes

sys.path.insert(0, '/the one/build')

import audio.audio as audioapi

try:

    from media import capabilities as capabilityapi

except Exception:

    capabilityapi = None



## paths
FFMPEGPATH = '/the one/software/audio/ffmpeg'
FFPROBEPATH = '/the one/software/audio/ffprobe'
VIDEODECODERPATH = '/the one/software/audio/t1-video-decode'
MEDIAROOT = '/.ephemeral/media'
MEDIALOGPATH = '/the one/logs/media.py.log'
MEDIASTATUSPREFIX = 'T1OS_MEDIA_STATUS '
MEDIAFRAMEPREFIX = 'T1OS_MEDIA_FRAME '



## limits
PROBETIMEOUT = 15.0
STDERRLIMIT = 64 * 1024
MAXWIDTH = 3840
MAXHEIGHT = 2160
MAXFPS = 60.0
MINFPS = 12.0
MAXPIXELRATE = 3840.0 * 2160.0 * 60.0
FRAMEQUEUELIMIT = 3
NATIVEFRAMEQUEUELIMIT = 8
FRAMESLOTS = 6
LATELIMIT = 0.10
STATUSINTERVAL = 0.20
TAGLIMIT = 512
AUDIOBUFFERSECONDS = 6.0
AUDIOPREBUFFERMS = 500
VIDEODECODERNICE = 5
VIDEOCONTROLMAGIC = 0x54315643
VIDEOCONTROLRELEASE = 1
VIDEOCONTROLSTOP = 2
VIDEOCONTROLRESIZE = 3
VIDEOMAXFDS = 4
GRAPHICSCATALOGUE = '/the one/catalogue/graphics'
LIBVADRIVERPATH = GRAPHICSCATALOGUE + '/drivers'
NVIDIARUNTIMEPATH = GRAPHICSCATALOGUE + '/nvidia'
NVIDIACACHEPATH = '/.ephemeral/cache/nvidia'
# LD_PRELOAD tokenises on both colons and whitespace.  The catalogue lives
# below "/the one", so loading the provider from there splits its pathname
# into two invalid preload entries.  GODDESS stages this immutable provider at
# a loader-safe path before any NVIDIA graphics or media process is started.
NVIDIAPATHPROVIDER = '/.ephemeral/graphics/nvidia-path-provider.so'
DRMNODEROOT = '/the one/drivers/nodes/dri'
DRMSTateroot = '/the one/drivers/state/class/drm'
VIDEOCONTRACTPATH = '/the one/drivers/settings/desktop compatibility.json'
MEDIACAPABILITYPATH = '/the one/settings/media/playback capabilities.json'



## playback state
STOPREQUESTED = False
ACTIVEVIDEO = None
VIDEOACCELERATION = {}



## DRM structures
class DRMVersion(ctypes.Structure):

    _fields_ = [
        ('version_major', ctypes.c_int),
        ('version_minor', ctypes.c_int),
        ('version_patchlevel', ctypes.c_int),
        ('name_len', ctypes.c_int),
        ('name', ctypes.c_void_p),
        ('date_len', ctypes.c_int),
        ('date', ctypes.c_void_p),
        ('desc_len', ctypes.c_int),
        ('desc', ctypes.c_void_p),
    ]



## errors
class MediaError(Exception):

    pass


class MediaUnavailable(MediaError):

    pass


class MediaDecodeError(MediaError):

    pass


class MediaHardwareDecodeError(MediaDecodeError):

    pass


class MediaCancelled(MediaError):

    pass


def medialog(message):

    try:

        text = cleanvalue(message)

        if not text:

            return

        # Player runs in the confined video domain and must not append to the
        # persistent log tree.  Operations captures this inherited stream in
        # the owning application's log.
        print(f'{time.time():.6f} media {text}', file=sys.stderr, flush=True)

    except Exception:

        pass



## value functions
def cleanvalue(value):

    try:

        if value is None:

            return ''

        value = str(value).replace('\x00', '').strip()
        value = ' '.join(value.split())
        return value[:TAGLIMIT]

    except Exception:

        return ''


def number(value, default=0.0):

    try:

        result = float(value)

        if not math.isfinite(result):

            return float(default)

        return result

    except Exception:

        return float(default)


def integer(value, default=0):

    try:

        return int(value)

    except Exception:

        return int(default)


def percentile(values, percent):

    ordered = sorted(
        number(value, 0.0)
        for value in values
        if math.isfinite(number(value, 0.0))
    )

    if not ordered:

        return 0.0

    index = int(math.ceil((max(0.0, min(100.0, number(percent, 0.0))) / 100.0) * len(ordered))) - 1
    return ordered[max(0, min(len(ordered) - 1, index))]


def rational(value):

    try:

        text = str(value or '').strip()

        separator = '/' if '/' in text else ':' if ':' in text else ''

        if separator:

            numerator, denominator = text.split(separator, 1)
            denominator = float(denominator)

            if denominator == 0.0:

                return 0.0

            return max(0.0, float(numerator) / denominator)

        return max(0.0, float(text))

    except Exception:

        return 0.0


def kilobits(value):

    return max(0, int(round(number(value) / 1000.0)))


def bitdepth(stream):

    if not isinstance(stream, dict):

        return 0

    for name in ('bits_per_raw_sample', 'bits_per_sample'):

        value = integer(stream.get(name), 0)

        if value > 0:

            return value

    pixel = str(stream.get('pix_fmt', '') or '').lower()
    match = re.search(r'(?:p|le|be)(9|10|12|14|16)', pixel)

    if match:

        return int(match.group(1))

    if pixel:

        return 8

    return 0


def chromasubsampling(stream):

    if not isinstance(stream, dict):

        return ''

    pixel = cleanvalue(stream.get('pix_fmt')).lower()

    if any(value in pixel for value in ('420', 'nv12', 'p010', 'p012', 'p016')):

        return '4:2:0'

    if any(value in pixel for value in ('422', 'yuyv', 'uyvy', 'v210', 'v216')):

        return '4:2:2'

    if any(value in pixel for value in ('444', 'gbr', 'rgb', 'bgr', 'xyz')):

        return '4:4:4'

    if '411' in pixel:

        return '4:1:1'

    if '410' in pixel:

        return '4:1:0'

    return ''


def streamdisposition(stream):

    source = stream.get('disposition', {}) if isinstance(stream, dict) else {}
    source = source if isinstance(source, dict) else {}
    return {
        str(name): bool(integer(value, 0))
        for name, value in source.items()
        if str(name).strip()
    }


def streamsidedata(stream):

    output = []

    if not isinstance(stream, dict):

        return output

    for source in stream.get('side_data_list', ()):

        if not isinstance(source, dict):

            continue

        entry = {}

        for name, value in source.items():

            key = cleanvalue(name)[:64]

            if not key:

                continue

            if isinstance(value, (int, float, bool)):

                entry[key] = value

            elif isinstance(value, str):

                entry[key] = cleanvalue(value)

        if entry:

            output.append(entry)

    return output


def hdrformat(stream):

    if not isinstance(stream, dict):

        return ''

    sidedata = streamsidedata(stream)
    types = ' '.join(
        cleanvalue(entry.get('side_data_type')).lower()
        for entry in sidedata
    )

    if 'dolby vision' in types or 'dovi' in types:

        return 'Dolby Vision'

    if 'hdr10+' in types or 'dynamic hdr plus' in types:

        return 'HDR10+'

    transfer = cleanvalue(stream.get('color_transfer')).lower()

    if transfer in ('smpte2084', 'smpte_st_2084'):

        if 'mastering display' in types or 'content light' in types:

            return 'HDR10'

        return 'PQ'

    if transfer in ('arib-std-b67', 'arib_std_b67'):

        return 'HLG'

    return ''


def tagvalues(*sources):

    aliases = {
        'album_artist': 'albumartist',
        'albumartist': 'albumartist',
        'artist': 'artist',
        'author': 'artist',
        'comment': 'comment',
        'composer': 'composer',
        'copyright': 'copyright',
        'date': 'date',
        'description': 'description',
        'disc': 'disc',
        'disc_number': 'disc',
        'encoder': 'encoder',
        'genre': 'genre',
        'handler_name': 'handler',
        'label': 'label',
        'performer': 'artist',
        'publisher': 'label',
        'show': 'album',
        'synopsis': 'description',
        'title': 'title',
        'track': 'track',
        'track_number': 'track',
        'year': 'date',
    }
    output = {}

    for source in sources:

        if not isinstance(source, dict):

            continue

        for rawname, rawvalue in source.items():

            name = re.sub(r'[^a-z0-9]+', '_', str(rawname).strip().lower()).strip('_')
            name = aliases.get(name, '')
            value = cleanvalue(rawvalue)

            if name and value and name not in output:

                output[name] = value

    return output


def rotationvalue(stream):

    if not isinstance(stream, dict):

        return 0

    tags = stream.get('tags', {})

    if isinstance(tags, dict) and 'rotate' in tags:

        return int(round(number(tags.get('rotate')))) % 360

    for side in stream.get('side_data_list', []):

        if isinstance(side, dict) and 'rotation' in side:

            return int(round(number(side.get('rotation')))) % 360

    return 0


def containername(formatinfo, path):

    extension = os.path.splitext(str(path))[1].lstrip('.').upper()
    names = str(formatinfo.get('format_name', '') or '').lower().split(',')
    mapping = {
        'asf': 'ASF',
        'avi': 'AVI',
        'dv': 'DV',
        'flv': 'FLV',
        'flac': 'FLAC',
        'gxf': 'GXF',
        'h264': 'H.264',
        'hevc': 'HEVC',
        'ivf': 'IVF',
        'matroska': 'MKV',
        'mov': 'MOV',
        'mp3': 'MP3',
        'mp4': 'MP4',
        'mpeg': 'MPEG',
        'mpegts': 'MPEG-TS',
        'mxf': 'MXF',
        'nut': 'NUT',
        'ogg': 'OGG',
        'rm': 'REALMEDIA',
        'vvc': 'VVC',
        'wav': 'WAV',
        'webm': 'WEBM',
        'yuv4mpegpipe': 'Y4M',
    }

    for name in names:

        if name in mapping:

            if name == 'matroska' and extension == 'WEBM':

                return 'WEBM'

            if name == 'mov' and extension in ('MP4', 'M4V', '3GP', '3G2', 'F4V'):

                return extension

            return mapping[name]

    if extension:

        return extension

    return cleanvalue(formatinfo.get('format_long_name')) or 'MEDIA'


def streamdefault(stream):

    try:

        return bool(integer(stream.get('disposition', {}).get('default'), 0))

    except Exception:

        return False


def streamattached(stream):

    try:

        return bool(integer(stream.get('disposition', {}).get('attached_pic'), 0))

    except Exception:

        return False


def selectstream(streams, kind, attached=False):

    candidates = []

    for stream in streams:

        if not isinstance(stream, dict) or str(stream.get('codec_type', '')) != str(kind):

            continue

        if kind == 'video' and streamattached(stream) != bool(attached):

            continue

        candidates.append(stream)

    for stream in candidates:

        if streamdefault(stream):

            return stream

    return candidates[0] if candidates else None


def audiostream(stream):

    if not isinstance(stream, dict):

        return {}

    codec = cleanvalue(stream.get('codec_name')).upper()
    channels = cleanvalue(stream.get('channel_layout'))

    if not channels and integer(stream.get('channels'), 0) > 0:

        channels = f"{integer(stream.get('channels'))} channels"

    return {
        'index': integer(stream.get('index'), -1),
        'codec': codec,
        'codec_detail': cleanvalue(stream.get('codec_long_name')),
        'profile': cleanvalue(stream.get('profile')),
        'sample_rate': integer(stream.get('sample_rate'), 0),
        'channels': channels,
        'channel_count': integer(stream.get('channels'), 0),
        'sample_format': cleanvalue(stream.get('sample_fmt')),
        'bit_depth': bitdepth(stream),
        'bit_rate': kilobits(stream.get('bit_rate')),
        'lossless': codec.lower() in audioapi.LOSSLESSCODECS,
        'language': cleanvalue(stream.get('tags', {}).get('language', '')),
        'title': cleanvalue(stream.get('tags', {}).get('title', '')),
        'codec_tag': cleanvalue(stream.get('codec_tag_string')),
        'disposition': streamdisposition(stream),
    }


def videostream(stream):

    if not isinstance(stream, dict):

        return {}

    width = max(0, integer(stream.get('width'), 0))
    height = max(0, integer(stream.get('height'), 0))
    rotation = rotationvalue(stream)
    displaywidth = width
    displayheight = height

    if rotation in (90, 270):

        displaywidth, displayheight = height, width

    aspect = rational(stream.get('display_aspect_ratio'))

    if aspect <= 0.0 and displayheight > 0:

        aspect = displaywidth / float(displayheight)

    elif rotation in (90, 270) and aspect > 0.0:

        aspect = 1.0 / aspect

    return {
        'index': integer(stream.get('index'), -1),
        'codec': cleanvalue(stream.get('codec_name')).upper(),
        'codec_detail': cleanvalue(stream.get('codec_long_name')),
        'profile': cleanvalue(stream.get('profile')),
        'level': integer(stream.get('level'), 0),
        'width': width,
        'height': height,
        'display_width': displaywidth,
        'display_height': displayheight,
        'display_aspect': aspect,
        'sample_aspect': cleanvalue(stream.get('sample_aspect_ratio')),
        'frame_rate': rational(stream.get('avg_frame_rate') or stream.get('r_frame_rate')),
        'pixel_format': cleanvalue(stream.get('pix_fmt')),
        'bit_depth': bitdepth(stream),
        'chroma_subsampling': chromasubsampling(stream),
        'bit_rate': kilobits(stream.get('bit_rate')),
        'rotation': rotation,
        'field_order': cleanvalue(stream.get('field_order')),
        'color_range': cleanvalue(stream.get('color_range')),
        'color_space': cleanvalue(stream.get('color_space')),
        'color_transfer': cleanvalue(stream.get('color_transfer')),
        'color_primaries': cleanvalue(stream.get('color_primaries')),
        'chroma_location': cleanvalue(stream.get('chroma_location')),
        'hdr_format': hdrformat(stream),
        'side_data': streamsidedata(stream),
        'language': cleanvalue(stream.get('tags', {}).get('language', '')),
        'title': cleanvalue(stream.get('tags', {}).get('title', '')),
        'codec_tag': cleanvalue(stream.get('codec_tag_string')),
        'disposition': streamdisposition(stream),
    }


def subtitlestream(stream):

    if not isinstance(stream, dict):

        return {}

    disposition = streamdisposition(stream)
    tags = stream.get('tags', {})
    tags = tags if isinstance(tags, dict) else {}
    return {
        'index': integer(stream.get('index'), -1),
        'codec': cleanvalue(stream.get('codec_name')).upper(),
        'codec_detail': cleanvalue(stream.get('codec_long_name')),
        'codec_tag': cleanvalue(stream.get('codec_tag_string')),
        'language': cleanvalue(tags.get('language')),
        'title': cleanvalue(tags.get('title')),
        'default': bool(disposition.get('default')),
        'forced': bool(disposition.get('forced')),
        'hearing_impaired': bool(disposition.get('hearing_impaired')),
        'disposition': disposition,
    }


def parseprobe(payload, path=''):

    if not isinstance(payload, dict):

        raise MediaDecodeError('media probe returned invalid data')

    streams = payload.get('streams', [])
    streams = streams if isinstance(streams, list) else []
    formatinfo = payload.get('format', {})
    formatinfo = formatinfo if isinstance(formatinfo, dict) else {}
    videoentries = [
        stream for stream in streams
        if isinstance(stream, dict)
        and stream.get('codec_type') == 'video'
        and not streamattached(stream)
    ]
    audioentries = [
        stream for stream in streams
        if isinstance(stream, dict) and stream.get('codec_type') == 'audio'
    ]
    subtitleentries = [
        stream for stream in streams
        if isinstance(stream, dict) and stream.get('codec_type') == 'subtitle'
    ]
    videoentry = selectstream(videoentries, 'video', attached=False)
    audioentry = selectstream(audioentries, 'audio')
    artworkentry = selectstream(streams, 'video', attached=True)
    video = videostream(videoentry)
    audio = audiostream(audioentry)
    videotracks = [videostream(stream) for stream in videoentries]
    audiotracks = [audiostream(stream) for stream in audioentries]
    subtitletracks = [subtitlestream(stream) for stream in subtitleentries]
    duration = number(formatinfo.get('duration'), 0.0)

    if duration <= 0.0:

        duration = max((number(stream.get('duration'), 0.0) for stream in streams if isinstance(stream, dict)), default=0.0)

    tagsources = [formatinfo.get('tags', {})]

    if videoentry:

        tagsources.append(videoentry.get('tags', {}))

    if audioentry:

        tagsources.append(audioentry.get('tags', {}))

    kind = 'video' if video else 'audio' if audio else 'unknown'
    container = containername(formatinfo, path)
    info = {
        'version': 1,
        'kind': kind,
        'path': str(path),
        'format': container,
        'container': container,
        'duration': max(0.0, duration),
        'bit_rate': kilobits(formatinfo.get('bit_rate')),
        'file_size': max(0, integer(formatinfo.get('size'), 0)),
        'artwork': bool(artworkentry),
        'tags': tagvalues(*tagsources),
        'video': video,
        'audio': audio,
        'video_tracks': videotracks,
        'audio_tracks': audiotracks,
        'subtitle_tracks': subtitletracks,
        'selected_video_stream': integer(video.get('index'), -1),
        'selected_audio_stream': integer(audio.get('index'), -1),
        'selected_subtitle_stream': -1,
        'video_streams': len(videotracks),
        'audio_streams': len(audiotracks),
        'subtitle_streams': len(subtitletracks),
        'chapters': [
            {
                'id': integer(chapter.get('id'), index),
                'start': number(chapter.get('start_time'), 0.0),
                'end': number(chapter.get('end_time'), 0.0),
                'title': cleanvalue(
                    (chapter.get('tags') or {}).get('title')
                    if isinstance(chapter.get('tags'), dict)
                    else ''
                ),
            }
            for index, chapter in enumerate(payload.get('chapters', ()))
            if isinstance(chapter, dict)
        ],
    }

    if kind == 'audio':

        info.update(audio)

    return info


def selecttracks(
    info,
    video_stream_index=None,
    audio_stream_index=None,
    subtitle_stream_index=None,
):

    if not isinstance(info, dict):

        raise MediaDecodeError('media stream inventory is invalid')

    selections = (
        ('video', 'video_tracks', 'selected_video_stream', video_stream_index),
        ('audio', 'audio_tracks', 'selected_audio_stream', audio_stream_index),
        ('subtitle', 'subtitle_tracks', 'selected_subtitle_stream', subtitle_stream_index),
    )

    for kind, collection, selectedname, requested in selections:

        if requested is None:

            continue

        try:

            requested = int(requested)

        except Exception:

            raise MediaDecodeError(f'{kind} stream selection is invalid')

        if kind in ('audio', 'subtitle') and requested < 0:

            info[kind] = {}
            info[selectedname] = -1
            continue

        track = next(
            (
                value for value in info.get(collection, ())
                if isinstance(value, dict)
                and integer(value.get('index'), -1) == requested
            ),
            None,
        )

        if track is None:

            raise MediaDecodeError(
                f'{kind} stream {requested} is not present in this file'
            )

        info[kind] = dict(track)
        info[selectedname] = requested

    info['kind'] = 'video' if info.get('video') else 'audio' if info.get('audio') else 'unknown'
    return info



## probe functions
def probecommand(path, ffprobepath=FFPROBEPATH):

    return [
        str(ffprobepath),
        '-v', 'error',
        '-show_format',
        '-show_streams',
        '-show_chapters',
        '-of', 'json',
        str(path),
    ]


def fallbackinfo(path, ffmpegpath=FFMPEGPATH):

    try:

        info = audioapi.audioinfo(path, ffmpegpath=ffmpegpath)
        info = dict(info)
        info['kind'] = 'audio'
        info['audio'] = {
            'index': 0,
            'codec': info.get('codec', ''),
            'sample_rate': info.get('sample_rate', 0),
            'channels': info.get('channels', ''),
            'bit_depth': info.get('bit_depth', 0),
            'bit_rate': info.get('bit_rate', 0),
            'lossless': info.get('lossless', False),
        }
        info['video'] = {}
        info['video_tracks'] = []
        info['audio_tracks'] = [dict(info['audio'])]
        info['subtitle_tracks'] = []
        info['selected_video_stream'] = -1
        info['selected_audio_stream'] = 0
        info['selected_subtitle_stream'] = -1
        info['video_streams'] = 0
        info['audio_streams'] = 1
        info['subtitle_streams'] = 0
        info['chapters'] = []
        return info

    except Exception as error:

        raise MediaDecodeError(str(error))


def mergeaudio(info, path, ffmpegpath=FFMPEGPATH):

    if not isinstance(info, dict) or info.get('kind') != 'audio':

        return info

    try:

        legacy = audioapi.audioinfo(path, ffmpegpath=ffmpegpath)

    except Exception:

        return info

    tags = info.get('tags', {})
    tags = dict(tags) if isinstance(tags, dict) else {}

    for name, value in legacy.get('tags', {}).items():

        if value and name not in tags:

            tags[name] = value

    info['tags'] = tags
    info['artwork'] = bool(info.get('artwork') or legacy.get('artwork'))

    for name in ('codec', 'codec_detail', 'sample_rate', 'bit_depth', 'channels', 'lossless'):

        if not info.get(name) and legacy.get(name):

            info[name] = legacy.get(name)

            if isinstance(info.get('audio'), dict):

                info['audio'][name] = legacy.get(name)

    return info


def mediainfo(path, ffprobepath=FFPROBEPATH, ffmpegpath=FFMPEGPATH):

    target = os.path.realpath(os.path.abspath(os.path.normpath(str(path))))

    if not os.path.isfile(target) or not os.access(target, os.R_OK):

        raise MediaDecodeError('media file is not readable')

    if not os.path.isfile(ffprobepath):

        return fallbackinfo(target, ffmpegpath=ffmpegpath)

    try:

        completed = subprocess.run(
            probecommand(target, ffprobepath),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=PROBETIMEOUT,
            check=False,
            env=audioapi.mediasandboxenvironment(target),
        )

    except FileNotFoundError:

        raise MediaUnavailable('media probe is not installed')

    except PermissionError:

        raise MediaUnavailable('media probe is not executable')

    except subprocess.TimeoutExpired:

        raise MediaDecodeError('media inspection timed out')

    except Exception as error:

        raise MediaDecodeError(f'cannot inspect media: {error}')

    if completed.returncode != 0:

        detail = completed.stderr.decode('utf-8', errors='replace').strip()
        raise MediaDecodeError(detail or 'media could not be inspected')

    try:

        payload = json.loads(completed.stdout.decode('utf-8', errors='replace'))

    except Exception as error:

        raise MediaDecodeError(f'media probe returned invalid JSON: {error}')

    info = parseprobe(payload, target)

    if info.get('kind') == 'unknown':

        raise MediaDecodeError('file contains no supported audio or video stream')

    if not info.get('file_size'):

        try:

            info['file_size'] = max(0, int(os.path.getsize(target)))

        except Exception:

            pass

    return mergeaudio(info, target, ffmpegpath=ffmpegpath)


def extractart(path, output, ffmpegpath=FFMPEGPATH):

    return audioapi.extractart(path, output, ffmpegpath=ffmpegpath)



## video decoder functions
def fitsize(width, height, maximumwidth=MAXWIDTH, maximumheight=MAXHEIGHT, aspect=0.0):

    width = max(1, integer(width, 1))
    height = max(1, integer(height, 1))
    maximumwidth = max(2, integer(maximumwidth, MAXWIDTH))
    maximumheight = max(2, integer(maximumheight, MAXHEIGHT))
    aspect = number(aspect, 0.0)

    if aspect <= 0.0:

        aspect = width / float(height)

    targetwidth = min(maximumwidth, width)
    targetheight = max(1, int(round(targetwidth / aspect)))

    if targetheight > maximumheight:

        targetheight = maximumheight
        targetwidth = max(1, int(round(targetheight * aspect)))

    targetwidth = max(2, targetwidth - (targetwidth % 2))
    targetheight = max(2, targetheight - (targetheight % 2))
    return [targetwidth, targetheight]


def outputframerate(video, width, height):

    sourcefps = number(video.get('frame_rate'), 0.0)

    if sourcefps <= 0.0:

        sourcefps = 25.0

    pixels = max(1, int(width) * int(height))
    pixelratefps = MAXPIXELRATE / float(pixels)
    return max(1.0, min(sourcefps, MAXFPS, max(MINFPS, pixelratefps)))


def drmbackend(node):

    name = os.path.basename(str(node))
    candidates = [
        os.path.join(DRMSTateroot, name, 'device', 'driver'),
        os.path.join('/the one/drivers/state/dev/char', name, 'device', 'driver'),
    ]

    try:

        status = os.stat(node)
        device = status.st_rdev
        candidates.append(os.path.join(
            '/the one/drivers/state/dev/char',
            f'{os.major(device)}:{os.minor(device)}',
            'device',
            'driver',
        ))

    except Exception:

        pass

    for candidate in candidates:

        try:

            if not os.path.exists(candidate):

                continue

            backend = os.path.basename(os.path.realpath(candidate)).strip().lower()

            if backend:

                return backend

        except Exception:

            pass

    descriptor = None
    versionpointer = None
    library = None

    try:

        library = ctypes.CDLL(
            os.path.join(GRAPHICSCATALOGUE, 'libdrm.so.2'),
            mode=ctypes.RTLD_GLOBAL,
            use_errno=True,
        )
        library.drmGetVersion.argtypes = [ctypes.c_int]
        library.drmGetVersion.restype = ctypes.POINTER(DRMVersion)
        library.drmFreeVersion.argtypes = [ctypes.POINTER(DRMVersion)]
        library.drmFreeVersion.restype = None
        descriptor = os.open(node, os.O_RDWR | getattr(os, 'O_CLOEXEC', 0))
        versionpointer = library.drmGetVersion(descriptor)

        if versionpointer:

            version = versionpointer.contents

            if version.name and version.name_len:

                return ctypes.string_at(
                    version.name,
                    version.name_len,
                ).decode('utf-8', errors='replace').strip().lower()

    except Exception:

        pass

    finally:

        try:

            if versionpointer and library is not None:

                library.drmFreeVersion(versionpointer)

        except Exception:

            pass

        try:

            if descriptor is not None:

                os.close(descriptor)

        except Exception:

            pass

    return ''


def drmnodedetails(node):

    details = {
        'node': str(node),
        'node_type': None,
        'uid': int(os.getuid()),
        'gid': int(os.getgid()),
        'groups': [int(group) for group in os.getgroups()],
    }
    descriptor = None

    try:

        status = os.stat(node)
        device = status.st_rdev
        major = os.major(device)
        minor = os.minor(device)
        details['major'] = int(major)
        details['minor'] = int(minor)
        details['character_device'] = (status.st_mode & 0o170000) == 0o020000
        details['owner_uid'] = int(status.st_uid)
        details['owner_gid'] = int(status.st_gid)
        details['mode'] = format(status.st_mode & 0o7777, '04o')
        details['state_drm_backlink'] = os.path.exists(os.path.join(
            '/the one/drivers/state/dev/char',
            f'{major}:{minor}',
            'device',
            'drm',
        ))

        details['step'] = 'load-libdrm'
        library = ctypes.CDLL(
            os.path.join(GRAPHICSCATALOGUE, 'libdrm.so.2'),
            mode=ctypes.RTLD_GLOBAL,
            use_errno=True,
        )
        details['libdrm_loaded'] = True
        library.drmGetNodeTypeFromFd.argtypes = [ctypes.c_int]
        library.drmGetNodeTypeFromFd.restype = ctypes.c_int
        details['step'] = 'open-render-node'
        descriptor = os.open(node, os.O_RDWR | getattr(os, 'O_CLOEXEC', 0))
        details['render_node_opened'] = True
        details['step'] = 'classify-render-node'
        details['node_type'] = int(library.drmGetNodeTypeFromFd(descriptor))
        details['errno'] = int(ctypes.get_errno())
        details['step'] = 'complete'

    except Exception as error:

        details['error'] = cleanvalue(repr(error))

    finally:

        try:

            if descriptor is not None:

                os.close(descriptor)

        except Exception:

            pass

    return details


def defaultvideobackends():

    return [
        {
            'drm_drivers': ['i915', 'xe'],
            'vaapi_drivers': ['iHD'],
            'class': 'physical',
        },
        {
            'drm_drivers': ['amdgpu'],
            'vaapi_drivers': ['radeonsi'],
            'class': 'physical',
        },
        {
            'drm_drivers': ['radeon'],
            'vaapi_drivers': ['radeonsi', 'r600'],
            'class': 'physical',
        },
        {
            'drm_drivers': ['nvidia', 'nvidia-drm'],
            'vaapi_drivers': ['nvidia'],
            'required_files': [
                'drivers/nvidia_drv_video.so',
                'nvidia/libcuda.so.1',
                'nvidia/libnvcuvid.so.1',
            ],
            'class': 'physical',
            'hardware_decode': 'capability-probed',
            'decode_backend': 'nvdec-direct',
            'software_fallback': False,
        },
        {
            'drm_drivers': ['nouveau'],
            'vaapi_drivers': ['nouveau'],
            'class': 'physical',
        },
        {
            'drm_drivers': ['vmwgfx'],
            'vaapi_drivers': ['vmwgfx'],
            'class': 'virtual',
        },
        {
            'drm_drivers': ['virtio_gpu'],
            'vaapi_drivers': ['virtio_gpu'],
            'class': 'virtual',
        },
    ]


def videobackends(contractpath=VIDEOCONTRACTPATH):

    try:

        with open(contractpath, 'r', encoding='utf-8') as stream:

            contract = json.load(stream)

        backends = contract.get('video_decode', {}).get('backends', [])

        if not isinstance(backends, list):

            raise ValueError('video backend contract is not a list')

        validated = []

        for backend in backends:

            if not isinstance(backend, dict):

                continue

            drm = [
                cleanvalue(value).lower().replace('-', '_')
                for value in backend.get('drm_drivers', [])
                if cleanvalue(value)
            ]
            vaapi = [
                cleanvalue(value)
                for value in backend.get('vaapi_drivers', [])
                if cleanvalue(value)
            ]
            requiredfiles = [
                cleanvalue(value)
                for value in backend.get('required_files', [])
                if cleanvalue(value)
            ]

            if drm and vaapi:

                validated.append({
                    'drm_drivers': drm,
                    'vaapi_drivers': vaapi,
                    'class': cleanvalue(backend.get('class')) or 'unknown',
                    'hardware_decode': cleanvalue(
                        backend.get('hardware_decode')
                    ),
                    'decode_backend': cleanvalue(
                        backend.get('decode_backend')
                    ),
                    'software_fallback': (
                        backend.get('software_fallback')
                        if isinstance(backend.get('software_fallback'), bool)
                        else True
                    ),
                    'required_files': requiredfiles,
                })

        if validated:

            return validated

    except Exception:

        pass

    return defaultvideobackends()


def vaapicandidates(backend, contractpath=VIDEOCONTRACTPATH):

    backend = cleanvalue(backend).lower().replace('-', '_')

    for entry in videobackends(contractpath=contractpath):

        entrydrivers = {
            cleanvalue(value).lower().replace('-', '_')
            for value in entry.get('drm_drivers', ())
            if cleanvalue(value)
        }

        if backend in entrydrivers:

            return [
                {
                    'driver': driver,
                    'class': entry.get('class', 'unknown'),
                    'hardware_decode': entry.get('hardware_decode', ''),
                    'decode_backend': entry.get('decode_backend', ''),
                    'software_fallback': entry.get('software_fallback', True),
                    'required_files': list(entry.get('required_files', ())),
                }
                for driver in entry.get('vaapi_drivers', ())
            ]

    return []


def vaapiruntimeconfiguration(backend, driver, metadata=None):

    """Return process environment requirements for one packaged VA driver."""
    backend = cleanvalue(backend).lower()
    driver = cleanvalue(driver)
    metadata = metadata if isinstance(metadata, dict) else {}
    librarypaths = [GRAPHICSCATALOGUE]
    variables = {}
    unsetvariables = []
    pathprovider = ''

    if driver == 'nvidia':

        librarypaths.insert(0, NVIDIARUNTIMEPATH)
        variables.update({
            'NVD_BACKEND': 'direct',
            # T1OS mounts procfs at /the one/drivers/processes. The pinned
            # nvidia-vaapi-driver otherwise treats the intentionally absent
            # conventional kernel-version pseudo-file as a sandbox and
            # returns before loading CUDA/NVDEC.
            'NVD_FORCE_INIT': '1',
            # NVIDIA 580+ otherwise raises the CUDA performance state for the
            # lifetime of web playback. NVDEC remains a dedicated engine.
            'CUDA_DISABLE_PERF_BOOST': '1',
            # HOME is / for system-launched applications. Without an explicit
            # path, CUDA consequently creates /.nv/ComputeCache on the root
            # filesystem instead of using T1OS's disposable runtime tier.
            'CUDA_CACHE_PATH': NVIDIACACHEPATH,
        })
        # nvidia-vaapi-driver treats the presence of NVD_SINGLE_BUFFER as an
        # instruction to synthesize one common-modifier allocation, even when
        # its value is "0".  T1OS uses the patched natural per-plane exporter.
        unsetvariables.append('NVD_SINGLE_BUFFER')
        pathprovider = NVIDIAPATHPROVIDER

    return {
        'backend': backend,
        'driver': driver,
        'driver_path': LIBVADRIVERPATH,
        'library_path': ':'.join(librarypaths),
        'library_paths': librarypaths,
        'environment': variables,
        'unset_environment': unsetvariables,
        'path_provider': pathprovider,
        'hardware_required': metadata.get('software_fallback') is False,
        'decode_backend': cleanvalue(metadata.get('decode_backend')),
    }


def videoaccelerationenvironment(
    acceleration,
    environment=None,
    preload_path_provider=False,
):

    """Apply a selected VA runtime without discarding the caller's paths."""
    acceleration = acceleration if isinstance(acceleration, dict) else {}
    result = dict(os.environ if environment is None else environment)
    result['LIBVA_DRIVERS_PATH'] = cleanvalue(
        acceleration.get('driver_path')
    ) or LIBVADRIVERPATH
    result['LIBVA_DRIVER_NAME'] = cleanvalue(acceleration.get('driver'))

    for name in acceleration.get('unset_environment', ()):

        name = cleanvalue(name)

        if name:

            result.pop(name, None)

    librarypaths = acceleration.get('library_paths', ())

    if not isinstance(librarypaths, (list, tuple)):

        librarypaths = cleanvalue(
            acceleration.get('library_path')
        ).split(':')

    existing = cleanvalue(result.get('LD_LIBRARY_PATH')).split(':')
    merged = []

    for path in (*librarypaths, *existing):

        path = cleanvalue(path)

        if path and path not in merged:

            merged.append(path)

    if merged:

        result['LD_LIBRARY_PATH'] = ':'.join(merged)

    for name, value in dict(acceleration.get('environment') or {}).items():

        name = cleanvalue(name)
        value = cleanvalue(value)

        if name and value:

            result[name] = value

    pathprovider = cleanvalue(acceleration.get('path_provider'))

    if preload_path_provider and pathprovider:

        preload = [
            cleanvalue(path)
            for path in cleanvalue(result.get('LD_PRELOAD')).split(':')
            if cleanvalue(path)
        ]

        if pathprovider not in preload:

            preload.insert(0, pathprovider)

        result['LD_PRELOAD'] = ':'.join(preload)

    return result


def browservideoacceleration(backend, contractpath=VIDEOCONTRACTPATH):

    """Return the packaged VA-API runtime contract for a browser process."""
    for candidate in vaapicandidates(backend, contractpath=contractpath):

        driver = cleanvalue(candidate.get('driver'))
        driverfile = os.path.join(LIBVADRIVERPATH, f'{driver}_drv_video.so')
        requiredfiles = [
            os.path.join(GRAPHICSCATALOGUE, cleanvalue(relative))
            for relative in candidate.get('required_files', ())
            if cleanvalue(relative)
        ]

        if (
            driver
            and os.path.isfile(driverfile)
            and all(os.path.isfile(path) for path in requiredfiles)
        ):

            result = vaapiruntimeconfiguration(backend, driver, candidate)
            result.update({
                'driver_file': driverfile,
                'class': cleanvalue(candidate.get('class')) or 'unknown',
            })
            return result

    return None


def vaapilabel(backend, driver):

    backend = cleanvalue(backend).lower().replace('_', '-')
    labels = {
        ('i915', 'iHD'): 'intel-i915-iHD-vaapi',
        ('xe', 'iHD'): 'intel-xe-iHD-vaapi',
        ('amdgpu', 'radeonsi'): 'amd-radeonsi-vaapi',
        ('radeon', 'radeonsi'): 'amd-radeon-radeonsi-vaapi',
        ('radeon', 'r600'): 'amd-r600-vaapi',
        ('nvidia', 'nvidia'): 'nvidia-nvdec-vaapi',
        ('nvidia-drm', 'nvidia'): 'nvidia-nvdec-vaapi',
        ('nouveau', 'nouveau'): 'nvidia-nouveau-vaapi',
        ('vmwgfx', 'vmwgfx'): 'virtualbox-vmsvga-vaapi',
        ('virtio_gpu', 'virtio_gpu'): 'virtio-gpu-vaapi',
    }
    return labels.get(
        (backend, cleanvalue(driver)),
        f'{backend}-{cleanvalue(driver)}-vaapi',
    )


def normalizedprofile(value):

    return re.sub(r'[^a-z0-9]+', '', cleanvalue(value).lower())


def vaapiprofilematches(profile, video):

    if not isinstance(profile, dict):

        return False

    codec = cleanvalue(video.get('codec')).upper()

    if cleanvalue(profile.get('codec')).upper() != codec:

        return False

    width = max(0, integer(video.get('width'), 0))
    height = max(0, integer(video.get('height'), 0))
    maximumwidth = max(0, integer(profile.get('max_width'), 0))
    maximumheight = max(0, integer(profile.get('max_height'), 0))

    if maximumwidth and width > maximumwidth:

        return False

    if maximumheight and height > maximumheight:

        return False

    requesteddepth = max(0, integer(video.get('bit_depth'), 0))
    depths = {
        max(0, integer(value, 0))
        for value in profile.get('bit_depths', [])
        if max(0, integer(value, 0))
    }

    if requesteddepth and depths and requesteddepth not in depths:

        return False

    requestedchroma = cleanvalue(video.get('chroma_subsampling'))
    formats = [
        value for value in profile.get('formats', ())
        if isinstance(value, dict)
    ]

    if formats and (requesteddepth or requestedchroma):

        compatible = any(
            (
                not requesteddepth
                or integer(value.get('bit_depth'), 0) == requesteddepth
            )
            and (
                not requestedchroma
                or cleanvalue(value.get('chroma')) == requestedchroma
            )
            for value in formats
        )

        if not compatible:

            return False

    requested = normalizedprofile(video.get('profile'))
    available = normalizedprofile(profile.get('name'))

    if not requested or not available or available == 'unknown':

        return True

    aliases = {
        'baseline': 'h264constrainedbaseline',
        'constrainedbaseline': 'h264constrainedbaseline',
        'main': 'main',
        'high': 'high',
        'main10': 'main10',
        'main12': 'main12',
        'profile0': 'profile0',
        'profile1': 'profile1',
        'profile2': 'profile2',
        'profile3': 'profile3',
    }
    expected = aliases.get(requested, requested)

    if codec == 'H264':

        return expected in available

    if codec == 'HEVC':

        return expected in available

    if codec == 'AV1':

        av1profiles = {
            'main': 'profile0',
            'high': 'profile1',
            'professional': 'profile2',
        }
        expected = av1profiles.get(expected, expected)
        return expected in available

    if codec in ('VP9', 'AV1') and requested.startswith('profile'):

        return requested in available

    return requested in available or available in requested


def videoaccelerationkey(video, preferrednode=''):

    video = video if isinstance(video, dict) else {}
    return (
        cleanvalue(preferrednode),
        cleanvalue(video.get('codec')).upper(),
        normalizedprofile(video.get('profile')),
        max(0, integer(video.get('bit_depth'), 0)),
        cleanvalue(video.get('chroma_subsampling')),
        cleanvalue(video.get('field_order')).lower(),
        max(0, integer(video.get('width'), 0)),
        max(0, integer(video.get('height'), 0)),
    )


def hardwaredecoderequired(
    preferrednode='',
    backend='',
    contractpath=VIDEOCONTRACTPATH,
):

    """Whether the selected display backend forbids silent CPU decoding."""
    preferrednode = cleanvalue(preferrednode)
    backend = cleanvalue(backend).lower().replace('-', '_')

    if not backend and preferrednode:

        backend = drmbackend(preferrednode)

    if not backend:

        return False

    return any(
        candidate.get('software_fallback') is False
        for candidate in vaapicandidates(
            backend,
            contractpath=contractpath,
        )
    )


def parsevideoaccelerationprobeoutput(payload):

    """Split an optional NVIDIA adapter trace from the probe's final JSON."""
    if isinstance(payload, bytes):

        text = payload.decode('utf-8', errors='replace')

    else:

        text = str(payload or '')

    lines = text.splitlines()
    capability = None
    capabilityline = None

    for index in range(len(lines) - 1, -1, -1):

        candidate = lines[index].strip()

        if not candidate.startswith('{') or not candidate.endswith('}'):

            continue

        try:

            parsed = json.loads(candidate)

        except (TypeError, ValueError, json.JSONDecodeError):

            continue

        if isinstance(parsed, dict):

            capability = parsed
            capabilityline = index
            break

    adapterlines = (
        lines[:capabilityline]
        if capabilityline is not None
        else lines
    )
    adapterlog = '\n'.join(adapterlines).strip()[-4096:]
    return capability, adapterlog, text[-4096:]


def videoacceleration(
    video=None,
    refresh=False,
    diagnostics=None,
    preferrednode='',
    contractpath=VIDEOCONTRACTPATH,
    processidentity=None,
    probetimeout=5.0,
):

    global VIDEOACCELERATION

    video = video if isinstance(video, dict) else {}
    codec = cleanvalue(video.get('codec')).upper()
    key = videoaccelerationkey(video, preferrednode=preferrednode)

    if not refresh and key in VIDEOACCELERATION:

        cached = dict(VIDEOACCELERATION.get(key) or {})

        return cached or None

    result = None
    nodes = sorted(glob.glob(os.path.join(DRMNODEROOT, 'renderD*')))
    preferrednode = cleanvalue(preferrednode)

    if preferrednode:

        nodes = [preferrednode]

    for node in nodes:

        baseattempt = {
            'node': node,
            'preferred': bool(preferrednode and node == preferrednode),
            'exists': os.path.exists(node),
        }

        if not baseattempt['exists']:

            baseattempt['result'] = 'missing-device'

            if diagnostics is not None:

                diagnostics.append(baseattempt)

            continue

        baseattempt.update(drmnodedetails(node))
        backend = drmbackend(node)
        baseattempt['drm_driver'] = backend
        candidates = vaapicandidates(backend, contractpath=contractpath)

        if not candidates:

            baseattempt['result'] = 'unsupported-drm-driver'

            if diagnostics is not None:

                diagnostics.append(baseattempt)

            continue

        for candidate in candidates:

            driver = cleanvalue(candidate.get('driver'))
            driverfile = os.path.join(
                LIBVADRIVERPATH,
                f'{driver}_drv_video.so',
            )
            attempt = dict(baseattempt)
            attempt['driver'] = driver
            attempt['driver_file'] = driverfile
            attempt['decoder'] = VIDEODECODERPATH

            if diagnostics is not None:

                diagnostics.append(attempt)

            if not os.path.isfile(driverfile):

                attempt['result'] = 'missing-va-driver'
                continue

            if not os.path.isfile(VIDEODECODERPATH):

                attempt['result'] = 'missing-video-decoder'
                continue

            runtime = vaapiruntimeconfiguration(backend, driver, candidate)
            environment = videoaccelerationenvironment(
                runtime,
                preload_path_provider=True,
            )
            # The adapter's own trace is the only evidence which distinguishes
            # CUDA/NVDEC loading, direct-exporter, and CUDA-context failures.
            # Enable it only for this short capability probe. Normal native
            # playback keeps its stdout reserved for the frame protocol.
            if driver == 'nvidia':

                environment['NVD_LOG'] = '1'

            try:

                probe = subprocess.run(
                    [VIDEODECODERPATH, '--probe', '--device', node],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=max(1.0, float(probetimeout)),
                    check=False,
                    env=environment,
                    preexec_fn=processidentity,
                )
                attempt['probe_return_code'] = int(probe.returncode)
                capability, adapterlog, stdouttext = (
                    parsevideoaccelerationprobeoutput(probe.stdout)
                )
                attempt['probe_stdout'] = stdouttext

                if adapterlog:

                    attempt['adapter_log'] = adapterlog

                attempt['probe_stderr'] = probe.stderr.decode(
                    'utf-8',
                    errors='replace',
                )[-4096:]

                if probe.returncode != 0:

                    attempt['result'] = 'probe-failed'
                    continue

                if capability is None:

                    attempt['result'] = 'invalid-probe-output'
                    continue

                profiles = capability.get('profiles', [])
                profiles = profiles if isinstance(profiles, list) else []
                matched = [
                    profile
                    for profile in profiles
                    if vaapiprofilematches(profile, video)
                ]
                codecs = tuple(sorted({
                    cleanvalue(profile.get('codec')).upper()
                    for profile in profiles
                    if cleanvalue(profile.get('codec')).upper() not in ('', 'UNKNOWN')
                }))

                if not profiles:

                    attempt['result'] = 'no-codecs'
                    continue

                if codec and not matched:

                    attempt['result'] = 'incompatible-stream'
                    attempt['codecs'] = list(codecs)
                    continue

                result = {
                    'backend': vaapilabel(backend, driver),
                    'drm_driver': backend,
                    'driver': driver,
                    'device': node,
                    'device_class': candidate.get('class', 'unknown'),
                    'preferred_device': bool(preferrednode and node == preferrednode),
                    'codecs': codecs,
                    'profiles': profiles,
                    'matched_profiles': matched,
                    'vendor': cleanvalue(capability.get('vendor')),
                    'probe': 'vaapi-runtime',
                }
                result.update(runtime)
                # Keep the measured label as the public backend name after
                # adding the lower-level process runtime configuration.
                result['backend'] = vaapilabel(backend, driver)
                attempt['result'] = 'available'
                attempt['codecs'] = list(codecs)
                attempt['matched_profiles'] = len(matched)
                break

            except Exception as error:

                attempt['result'] = 'probe-error'
                attempt['error'] = cleanvalue(repr(error))
                continue

        if result:

            break

    VIDEOACCELERATION[key] = dict(result) if result is not None else {}

    if not result:

        return None

    return dict(result)


def videoaccelerationattemptsummary(attempts):

    """Return one bounded, user-actionable VA/NVDEC probe result."""
    attempts = attempts if isinstance(attempts, list) else []
    attempt = next(
        (
            value
            for value in reversed(attempts)
            if isinstance(value, dict) and cleanvalue(value.get('result'))
        ),
        {},
    )

    if not attempt:

        return 'probe produced no diagnostic result'

    result = cleanvalue(attempt.get('result')) or 'unknown'
    parts = [
        f'result={result}',
        f'node={cleanvalue(attempt.get("node")) or "none"}',
        f'driver={cleanvalue(attempt.get("driver")) or "none"}',
    ]

    if 'probe_return_code' in attempt:

        parts.append(
            f'return_code={integer(attempt.get("probe_return_code"), -1)}'
        )

    adapterlog = cleanvalue(attempt.get('adapter_log'))

    if adapterlog:

        adapterlog = ' '.join(adapterlog.split())[-512:]
        parts.append(f'adapter={adapterlog}')

    detail = cleanvalue(
        attempt.get('probe_stderr')
        or attempt.get('error')
        or attempt.get('probe_stdout')
    )

    if detail:

        detail = ' '.join(detail.split())[:512]
        parts.append(f'detail={detail}')

    return ' '.join(parts)


def videocommand(
    path,
    video,
    startseconds=0.0,
    ffmpegpath=FFMPEGPATH,
    maximumwidth=MAXWIDTH,
    maximumheight=MAXHEIGHT,
    acceleration=None,
):

    width = integer(video.get('display_width') or video.get('width'), 0)
    height = integer(video.get('display_height') or video.get('height'), 0)
    aspect = number(video.get('display_aspect'), 0.0)
    targetwidth, targetheight = fitsize(width, height, maximumwidth, maximumheight, aspect=aspect)
    targetfps = outputframerate(video, targetwidth, targetheight)
    command = [
        str(ffmpegpath),
        '-hide_banner',
        '-loglevel', 'info',
        '-nostats',
        '-nostdin',
    ]
    acceleration = dict(acceleration or {})

    fieldorder = cleanvalue(video.get('field_order')).lower()
    interlaced = fieldorder not in ('', 'unknown', 'progressive')

    if acceleration:

        command.extend([
            '-hwaccel', 'vaapi',
            '-hwaccel_device', str(acceleration['device']),
            '-hwaccel_output_format', 'vaapi',
        ])

    startseconds = max(0.0, number(startseconds, 0.0))

    if startseconds > 0.0:

        command.extend(['-ss', f'{startseconds:.6f}'])

    if acceleration:

        filters = (
            f'setpts=PTS-STARTPTS,'
            + ('deinterlace_vaapi=rate=frame:auto=1,' if interlaced else '')
            + f'scale_vaapi=w={targetwidth}:h={targetheight}:format=bgra,'
            + f'hwdownload,format=bgra,'
            + f'fps=fps={targetfps:.6f}:round=near,format=bgra'
        )

    else:

        filters = (
            'setpts=PTS-STARTPTS,'
            + (
                'bwdif=mode=send_frame:parity=auto:deint=interlaced,'
                if interlaced
                else ''
            )
            + f'fps=fps={targetfps:.6f}:round=near,'
            + f'scale={targetwidth}:{targetheight},format=bgra'
        )

    command.extend([
        '-i', str(path),
        '-map', f"0:{integer(video.get('index'), 0)}",
        '-an',
        '-sn',
        '-dn',
        '-vf', filters,
        '-c:v', 'rawvideo',
        '-pix_fmt', 'bgra',
        '-f', 'rawvideo',
        'pipe:1',
    ])
    return command, targetwidth, targetheight, targetfps


def readexactinto(pipe, target, size):

    view = memoryview(target)
    offset = 0

    try:

        while offset < size:

            count = pipe.readinto(view[offset:size])

            if not count:

                break

            offset += int(count)

    finally:

        view.release()

    return offset


def makeframeslots(session, framesize):

    slots = []
    pendingpath = ''
    token = f"{integer(session.get('generation'), 0)}-{time.monotonic_ns()}"

    try:

        for index in range(FRAMESLOTS):

            path = os.path.join(session['root'], f'stream-{token}-{index}.bgra')
            pendingpath = path
            descriptor = os.open(
                path,
                os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, 'O_CLOEXEC', 0),
                0o600,
            )

            try:

                size = int(framesize)
                if size <= 0:
                    raise MediaDecodeError('shared video frame size is invalid')
                os.lseek(descriptor, size - 1, os.SEEK_SET)
                if os.write(descriptor, b'\0') != 1:
                    raise MediaDecodeError('shared video frame allocation was short')
                os.lseek(descriptor, 0, os.SEEK_SET)
                buffer = bytearray(size)
            except Exception:
                os.close(descriptor)
                raise

            slots.append({
                'path': path,
                'descriptor': descriptor,
                'buffer': buffer,
            })
            pendingpath = ''

        return slots

    except Exception:

        if pendingpath:

            try:

                os.unlink(pendingpath)

            except Exception:

                pass

        for slot in slots:

            try:

                os.close(slot['descriptor'])

            except Exception:

                pass

            try:

                os.unlink(slot['path'])

            except Exception:

                pass

        raise


def frameworker(context):

    pipe = context.get('stdout')
    framesize = int(context.get('framesize', 0))
    index = 0

    try:

        while not context['stop'].is_set():

            slot = context['slots'][index % len(context['slots'])]
            length = readexactinto(pipe, slot['buffer'], framesize)

            if not length:

                break

            if length != framesize:

                context['frameerror'] = 'video decoder returned an incomplete frame'
                break

            offset = 0
            while offset < framesize:
                written = os.pwrite(
                    slot['descriptor'], slot['buffer'][offset:], offset,
                )
                if written <= 0:
                    raise MediaDecodeError('shared video frame publication was short')
                offset += written

            while not context['stop'].is_set():

                try:

                    context['frames'].put((index, slot['path']), timeout=0.05)
                    break

                except queue.Full:

                    continue

            index += 1

    except Exception as error:

        context['frameerror'] = str(error)

    finally:

        context['framedone'].set()


def stderrworker(context):

    storage = context['stderr']

    try:

        while not context['stop'].is_set():

            line = context['stderrpipe'].readline()

            if not line:

                break

            if len(storage) < STDERRLIMIT:

                storage.extend(line[:max(0, STDERRLIMIT - len(storage))])

            if context.get('native'):

                medialog(line.decode('utf-8', errors='replace'))

    except Exception as error:

        context['stderrerror'] = str(error)

    finally:

        context['stderrdone'].set()


def nativecontrol(context, kind, frame=0):

    connection = context.get('decoder_socket')

    if connection is None:

        return False

    try:

        packet = struct.pack(
            '<IIQ',
            VIDEOCONTROLMAGIC,
            int(kind),
            max(0, int(frame)),
        )
        return connection.send(packet) == len(packet)

    except Exception:

        return False


def nativeresize(context, width, height):

    width = max(2, min(65535, integer(width, 2))) & ~1
    height = max(2, min(65535, integer(height, 2))) & ~1
    packed = (int(width) << 32) | int(height)
    changed = nativecontrol(context, VIDEOCONTROLRESIZE, packed)

    if changed:

        context['presentation_width'] = width
        context['presentation_height'] = height

    return changed


def releasenativeframe(context, frame):

    if not isinstance(frame, dict):

        return

    for descriptor in frame.get('fds', []):

        try:

            os.close(int(descriptor))

        except Exception:

            pass

    frame['fds'] = []
    nativecontrol(context, VIDEOCONTROLRELEASE, frame.get('frame', 0))


def nativeframeworker(context):

    connection = context.get('decoder_socket')

    try:

        while not context['stop'].is_set():

            data, ancillary, flags, _ = connection.recvmsg(
                65536,
                socket.CMSG_SPACE(VIDEOMAXFDS * array.array('i').itemsize),
            )

            if not data:

                break

            descriptors = []

            for level, kind, payload in ancillary:

                if level != socket.SOL_SOCKET or kind != socket.SCM_RIGHTS:

                    continue

                values = array.array('i')
                usable = len(payload) - (len(payload) % values.itemsize)
                values.frombytes(payload[:usable])
                descriptors.extend(int(value) for value in values)

            try:

                if flags & (getattr(socket, 'MSG_TRUNC', 0) | getattr(socket, 'MSG_CTRUNC', 0)):

                    raise MediaDecodeError('native video decoder returned a truncated frame')

                message = json.loads(data.decode('utf-8'))

                if message.get('op') == 'eof':

                    context['native_eof'] = True
                    break

                if message.get('op') != 'frame' or not descriptors:

                    raise MediaDecodeError('native video decoder returned an invalid frame')

                if len(descriptors) > VIDEOMAXFDS:

                    raise MediaDecodeError('native video decoder returned too many DMA-BUF handles')

                message['fds'] = descriptors
                descriptors = []
                queued = False

                while not context['stop'].is_set():

                    try:

                        context['frames'].put(message, timeout=0.01)
                        queued = True
                        break

                    except queue.Full:
                        # Keep decoder backpressure intact.  Evicting the
                        # oldest queued GPU surface lets a fast decoder run
                        # the entire file ahead of the audio clock, producing
                        # only a few widely spaced frames.  Blocking here
                        # fills the decoder's bounded surface pool instead;
                        # presentation then releases surfaces at playback
                        # cadence, and only the audio-master timing stage
                        # below drops frames that are genuinely late.
                        continue

                if not queued:

                    releasenativeframe(context, message)

            finally:

                for descriptor in descriptors:

                    try:

                        os.close(descriptor)

                    except Exception:

                        pass

    except Exception as error:

        if not context['stop'].is_set():

            context['frameerror'] = str(error)

    finally:

        context['framedone'].set()


def connectvideosurface(transport, timeout=3.0):

    path = str((transport or {}).get('socket', ''))
    token = str((transport or {}).get('token', ''))

    if not path or not token:

        raise MediaHardwareDecodeError('window server video surface transport is unavailable')

    deadline = time.monotonic() + max(0.1, float(timeout))
    lastdetail = ''

    while time.monotonic() < deadline:

        connection = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)

        try:

            connection.connect(path)
            connection.send(json.dumps(
                {'op': 'auth', 'token': token},
                separators=(',', ':'),
            ).encode('utf-8'))
            connection.setblocking(False)
            return connection

        except Exception as error:

            lastdetail = str(error)
            connection.close()
            time.sleep(0.02)

    raise MediaHardwareDecodeError(f'cannot connect GPU video surface transport: {lastdetail}')


def startnativevideo(session, startseconds, acceleration):

    global ACTIVEVIDEO

    transport = dict(session.get('video_transport') or {})
    videosocket = connectvideosurface(transport)
    parent = None
    child = None

    try:

        parent, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        sourcevideo = session['info']['video']
        targetwidth, targetheight = fitsize(
            integer(sourcevideo.get('display_width') or sourcevideo.get('width'), 0),
            integer(sourcevideo.get('display_height') or sourcevideo.get('height'), 0),
            session['maximumwidth'],
            session['maximumheight'],
            aspect=number(sourcevideo.get('display_aspect'), 0.0),
        )
        environment = videoaccelerationenvironment(
            acceleration,
            preload_path_provider=True,
        )
        command = [
            VIDEODECODERPATH,
            '--input', session['path'],
            '--device', acceleration['device'],
            '--socket-fd', str(child.fileno()),
            '--start', f'{max(0.0, number(startseconds, 0.0)):.6f}',
            '--stream-index', str(integer(session['info']['video'].get('index'), 0)),
            '--output-width', str(targetwidth),
            '--output-height', str(targetheight),
            '--rotation', str(integer(sourcevideo.get('rotation'), 0) % 360),
        ]
        importformats = sorted({
            integer(item.get('fourcc'), 0)
            for item in transport.get('import_capabilities', {}).get('formats', [])
            if isinstance(item, dict) and integer(item.get('fourcc'), 0) > 0
        })

        if importformats:

            command.extend([
                '--import-fourcc',
                ','.join(str(value) for value in importformats),
            ])
        process = subprocess.Popen(
            command,
            # T1OS exposes managed device nodes below /the one/drivers. A pipe
            # keeps the child's descriptor lifecycle explicit in stopvideo().
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
            start_new_session=True,
            pass_fds=(child.fileno(),),
            env=environment,
        )
        child.close()
        child = None
        medialog(
            'native video decoder started '
            f'pid={process.pid} backend={acceleration.get("backend", "vaapi")} '
            f'driver={acceleration.get("driver", "")} '
            f'device={acceleration.get("device", "")}'
        )
    except Exception as error:

        videosocket.close()

        for connection in (parent, child):

            if connection is not None:

                connection.close()

        if isinstance(error, MediaError):

            raise

        raise MediaHardwareDecodeError(f'cannot start native GPU video decoder: {error}')

    decodernice = None

    try:

        if hasattr(os, 'setpriority') and hasattr(os, 'PRIO_PROCESS'):

            os.setpriority(os.PRIO_PROCESS, process.pid, VIDEODECODERNICE)
            decodernice = int(os.getpriority(os.PRIO_PROCESS, process.pid))

    except Exception:

        decodernice = None

    context = {
        'session': session,
        'native': True,
        'process': process,
        'stdout': process.stdout,
        'stderrpipe': process.stderr,
        'stderr': bytearray(),
        'decoder_socket': parent,
        'video_socket': videosocket,
        'video_transport': transport,
        'width': integer(session['info']['video'].get('display_width') or session['info']['video'].get('width'), 0),
        'height': integer(session['info']['video'].get('display_height') or session['info']['video'].get('height'), 0),
        'presentation_width': targetwidth,
        'presentation_height': targetheight,
        'framerate': max(1.0, number(session['info']['video'].get('frame_rate'), 25.0)),
        'framesize': 0,
        'slots': [],
        'frames': queue.Queue(maxsize=NATIVEFRAMEQUEUELIMIT),
        'stop': threading.Event(),
        'framedone': threading.Event(),
        'stderrdone': threading.Event(),
        'frameerror': '',
        'stderrerror': '',
        'native_eof': False,
        'outstanding': set(),
        'presented_frames': set(),
        'dropped_frames': set(),
        'last_submitted_frame': 0,
        'decoder_nice': decodernice,
        'decoder_backend': acceleration.get('backend', 'vaapi'),
        'hardware_decode': True,
        'zero_copy': True,
    }

    with session['lock']:

        session['video_backend'] = context['decoder_backend']
        session['hardware_decode'] = True
        session['zero_copy'] = True
        session['native_video'] = True
        session['video_driver'] = cleanvalue(acceleration.get('driver'))
        session['video_drm_driver'] = cleanvalue(acceleration.get('drm_driver'))
        session['video_device'] = cleanvalue(acceleration.get('device'))
        session['video_vendor'] = cleanvalue(acceleration.get('vendor'))
        session['coded_width'] = context['width']
        session['coded_height'] = context['height']
        session['presentation_width'] = targetwidth
        session['presentation_height'] = targetheight
        session['native_context'] = context

    context['framethread'] = threading.Thread(
        target=nativeframeworker,
        args=(context,),
        daemon=True,
        name='media-native-frames',
    )
    context['stderrthread'] = threading.Thread(
        target=stderrworker,
        args=(context,),
        daemon=True,
        name='media-native-stderr',
    )
    ACTIVEVIDEO = process
    context['framethread'].start()
    context['stderrthread'].start()
    return context


def startvideo(session, startseconds, hardware=True):

    global ACTIVEVIDEO

    acceleration = videoacceleration(
        session['info']['video'],
        preferrednode=session.get('video_transport', {}).get('render_node', ''),
    ) if hardware else None

    if acceleration and session.get('video_transport'):

        return startnativevideo(session, startseconds, acceleration)

    command, width, height, framerate = videocommand(
        session['path'],
        session['info']['video'],
        startseconds=startseconds,
        ffmpegpath=session['ffmpegpath'],
        maximumwidth=session['maximumwidth'],
        maximumheight=session['maximumheight'],
        acceleration=acceleration,
    )
    environment = None

    if acceleration:

        environment = videoaccelerationenvironment(
            acceleration,
            preload_path_provider=True,
        )

    try:

        environment = audioapi.mediasandboxenvironment(
            session['path'],
            environment=environment,
        )

    except audioapi.AudioError as error:

        raise MediaUnavailable(str(error))

    try:

        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
            start_new_session=True,
            env=environment,
        )

    except FileNotFoundError:

        raise MediaUnavailable('media decoder is not installed')

    except PermissionError:

        raise MediaUnavailable('media decoder is not executable')

    except Exception as error:

        raise MediaUnavailable(f'cannot start video decoder: {error}')

    decodernice = None

    try:

        if hasattr(os, 'setpriority') and hasattr(os, 'PRIO_PROCESS'):

            os.setpriority(os.PRIO_PROCESS, process.pid, VIDEODECODERNICE)
            decodernice = int(os.getpriority(os.PRIO_PROCESS, process.pid))

    except Exception:

        decodernice = None

    framesize = width * height * 4

    try:

        slots = makeframeslots(session, framesize)

    except Exception as error:

        audioapi.terminateprocess(process)
        raise MediaUnavailable(f'cannot allocate shared video frames: {error}')

    context = {
        'session': session,
        'process': process,
        'stdout': process.stdout,
        'stderrpipe': process.stderr,
        'stderr': bytearray(),
        'width': width,
        'height': height,
        'framerate': framerate,
        'framesize': framesize,
        'slots': slots,
        'frames': queue.Queue(maxsize=FRAMEQUEUELIMIT),
        'stop': threading.Event(),
        'framedone': threading.Event(),
        'stderrdone': threading.Event(),
        'frameerror': '',
        'stderrerror': '',
        'decoder_nice': decodernice,
        'decoder_backend': acceleration.get('backend', 'software') if acceleration else 'software',
        'hardware_decode': bool(acceleration),
    }
    with session['lock']:

        session['video_backend'] = context['decoder_backend']
        session['hardware_decode'] = context['hardware_decode']
        session['zero_copy'] = False
        session['native_video'] = False
        session['video_driver'] = cleanvalue(
            acceleration.get('driver') if acceleration else ''
        )
        session['video_drm_driver'] = cleanvalue(
            acceleration.get('drm_driver') if acceleration else ''
        )
        session['video_device'] = cleanvalue(
            acceleration.get('device') if acceleration else ''
        )
        session['video_vendor'] = cleanvalue(
            acceleration.get('vendor') if acceleration else ''
        )

    context['framethread'] = threading.Thread(
        target=frameworker,
        args=(context,),
        daemon=True,
        name='media-frames',
    )
    context['stderrthread'] = threading.Thread(
        target=stderrworker,
        args=(context,),
        daemon=True,
        name='media-stderr',
    )
    ACTIVEVIDEO = process
    context['framethread'].start()
    context['stderrthread'].start()
    return context


def pollvideosurface(context):

    connection = context.get('video_socket')
    handled = 0

    if connection is None:

        return handled

    while True:

        try:

            data = connection.recv(65536)

            if not data:

                raise MediaHardwareDecodeError('window server closed the GPU video surface transport')

            message = json.loads(data.decode('utf-8'))

            if message.get('op') == 'release':

                frame = int(message.get('frame', 0))
                context.setdefault('outstanding', set()).discard(frame)
                nativecontrol(context, VIDEOCONTROLRELEASE, frame)
                handled += 1

            elif message.get('op') == 'cleared':

                context['surface_cleared'] = True
                handled += 1

            elif message.get('op') == 'presented':

                frame = int(message.get('frame', 0))
                presented = context.setdefault('presented_frames', set())

                if frame > 0 and frame not in presented:

                    presented.add(frame)
                    session = context.get('session')

                    if isinstance(session, dict):

                        pts = max(
                            0.0,
                            number(message.get('pts_ns'), 0.0) / 1000000000.0,
                        )
                        presentedat = (
                            number(message.get('presented_ns'), 0.0)
                            / 1000000000.0
                        )
                        drift = abs(
                            sessionclock(
                                session,
                                moment=presentedat if presentedat > 0.0 else None,
                            )
                            - pts
                        ) * 1000.0

                        with session['lock']:

                            samples = session.setdefault(
                                'av_drift_ms_samples',
                                [],
                            )
                            samples.append(drift)
                            if len(samples) > 4096:
                                del samples[:len(samples) - 4096]
                            session['maximum_av_drift_ms'] = max(
                                number(
                                    session.get('maximum_av_drift_ms'),
                                    0.0,
                                ),
                                drift,
                            )
                            session['presented'] = integer(
                                session.get('presented'),
                                0,
                            ) + 1

                handled += 1

            elif message.get('op') == 'dropped':

                frame = int(message.get('frame', 0))
                if frame > 0:
                    context.setdefault('dropped_frames', set()).add(frame)
                session = context.get('session')

                if isinstance(session, dict):

                    with session['lock']:

                        session['compositor_dropped_frames'] = integer(
                            session.get('compositor_dropped_frames'),
                            0,
                        ) + 1
                        session['dropped'] = integer(
                            session.get('dropped'),
                            0,
                        ) + 1

                handled += 1

            elif message.get('op') == 'error':

                detail = cleanvalue(message.get('detail'))
                raise MediaHardwareDecodeError(
                    detail or 'window server rejected the GPU video surface'
                )

        except BlockingIOError:

            break

        except MediaError:

            raise

        except Exception as error:

            raise MediaHardwareDecodeError(f'invalid GPU video surface control: {error}')

    return handled


def sendnativeframe(context, frame):

    descriptors = [int(value) for value in frame.get('fds', [])]

    if not descriptors:

        raise MediaHardwareDecodeError('decoded video frame has no DMA-BUF handles')

    message = dict(frame)
    message.pop('fds', None)
    message['stream'] = str(context.get('video_transport', {}).get('stream', ''))
    packet = json.dumps(message, separators=(',', ':')).encode('utf-8')
    ancillary = [(
        socket.SOL_SOCKET,
        socket.SCM_RIGHTS,
        array.array('i', descriptors),
    )]
    sent = False

    try:

        for attempt in range(2):

            connection = context.get('video_socket')

            try:

                if connection is None:

                    raise BrokenPipeError('video surface socket is closed')

                length = connection.sendmsg([packet], ancillary)

                if length != len(packet):

                    raise MediaHardwareDecodeError('partial GPU video surface packet')

                sent = True
                break

            except (BrokenPipeError, ConnectionResetError, ConnectionRefusedError):

                try:

                    if connection is not None:

                        connection.close()

                except Exception:

                    pass

                context['video_socket'] = connectvideosurface(
                    context.get('video_transport'),
                    timeout=1.0,
                )

        if not sent:

            raise MediaHardwareDecodeError('could not submit decoded GPU video surface')

        context.setdefault('outstanding', set()).add(int(frame.get('frame', 0)))
        context['last_submitted_frame'] = int(frame.get('frame', 0))

    except Exception:

        nativecontrol(context, VIDEOCONTROLRELEASE, frame.get('frame', 0))
        raise

    finally:

        for descriptor in descriptors:

            try:

                os.close(descriptor)

            except Exception:

                pass

        frame['fds'] = []


def clearvideosurface(context, timeout=0.75):

    connection = context.get('video_socket')

    if connection is None:

        return

    try:

        context['surface_cleared'] = False
        connection.send(json.dumps({'op': 'clear'}, separators=(',', ':')).encode('utf-8'))
    except Exception:

        return

    deadline = time.monotonic() + max(0.0, float(timeout))

    while time.monotonic() < deadline:

        try:

            pollvideosurface(context)

        except Exception:

            break

        if context.get('surface_cleared') and not context.get('outstanding'):

            break

        time.sleep(0.005)


def stopvideo(context):

    global ACTIVEVIDEO

    if not isinstance(context, dict):

        return

    if context.get('native'):

        clearvideosurface(context)
        context['stop'].set()

        try:

            while True:

                pending = context['frames'].get_nowait()

                for descriptor in pending.get('fds', []):

                    try:

                        os.close(int(descriptor))

                    except Exception:

                        pass

        except Exception:

            pass

        nativecontrol(context, VIDEOCONTROLSTOP)

        try:

            context.get('decoder_socket').shutdown(socket.SHUT_RDWR)

        except Exception:

            pass

        try:

            context.get('video_socket').close()

        except Exception:

            pass

        try:

            context.get('process').wait(timeout=0.5)

        except Exception:

            audioapi.terminateprocess(context.get('process'))

    else:

        context['stop'].set()
        audioapi.terminateprocess(context.get('process'))

    try:

        while True:

            context['frames'].get_nowait()

    except Exception:

        pass

    for name in ('stdout', 'stderrpipe', 'decoder_socket'):

        try:

            pipe = context.get(name)

            if pipe is not None:

                pipe.close()

        except Exception:

            pass

    for name in ('framethread', 'stderrthread'):

        thread = context.get(name)

        if thread is not None and thread.is_alive():

            thread.join(timeout=0.3)

    for slot in context.get('slots', []):

        try:

            descriptor = slot.get('descriptor')
            if descriptor is not None:
                os.close(descriptor)

        except Exception:

            pass

    if ACTIVEVIDEO is context.get('process'):

        ACTIVEVIDEO = None

    session = context.get('session')

    if isinstance(session, dict):

        with session.get('lock', threading.RLock()):

            if session.get('native_context') is context:

                session['native_context'] = None


def decoderdetail(context):

    text = bytes(context.get('stderr', b'')).decode('utf-8', errors='replace')
    lines = []

    for line in text.replace('\r', '\n').split('\n'):

        line = line.strip()

        if line and 'Parsed_showinfo' not in line:

            lines.append(line)

    return lines[-1][:500] if lines else 'video file could not be decoded'



## session functions
def newsession(path, info, statuscallback, framecallback, ffmpegpath, maximumwidth, maximumheight, retainframe, video_transport=None, startseconds=0.0):

    token = f"{os.getpid()}-{time.monotonic_ns()}"
    root = os.path.join(MEDIAROOT, f'session-{token}')
    os.makedirs(root, mode=0o700, exist_ok=False)

    if os.path.islink(root):

        raise MediaUnavailable('media frame directory is not safe')

    startseconds = max(0.0, number(startseconds, 0.0))
    duration = max(0.0, number(info.get('duration'), 0.0))

    if duration > 0.0:

        startseconds = min(startseconds, max(0.0, duration - 0.05))

    return {
        'path': path,
        'info': info,
        'kind': info.get('kind', 'unknown'),
        'duration': duration,
        'position': startseconds,
        'reportedat': time.monotonic(),
        'state': 'loading',
        'control': '',
        'generation': 0,
        'seekposition': startseconds,
        'statuscallback': statuscallback,
        'framecallback': framecallback,
        'ffmpegpath': ffmpegpath,
        'maximumwidth': max(2, integer(maximumwidth, MAXWIDTH)),
        'maximumheight': max(2, integer(maximumheight, MAXHEIGHT)),
        'retainframe': bool(retainframe),
        'root': root,
        'slot': 0,
        'frameid': 0,
        'framepath': '',
        'framewidth': 0,
        'frameheight': 0,
        'framepts': 0.0,
        'frame_surface': False,
        'frame_stream': '',
        'dropped': 0,
        'video_done': False,
        'audio_done': not bool(info.get('audio')),
        'audio_error': '',
        'audio_cancelled': False,
        'audio_thread': None,
        'controller': None,
        'video_control': '',
        'transport_controller': False,
        'lock': threading.RLock(),
        'laststatus': 0.0,
        'video_backend': 'pending',
        'hardware_decode': False,
        'zero_copy': False,
        'native_context': None,
        'coded_width': integer(info.get('video', {}).get('width'), 0),
        'coded_height': integer(info.get('video', {}).get('height'), 0),
        'presentation_width': 0,
        'presentation_height': 0,
        'hardware_failure': '',
        'video_transport': dict(video_transport or {}),
        'presented': 0,
        'submitted_frames': 0,
        'compositor_dropped_frames': 0,
        'decoded_frames': 0,
        'gpu_scaled_frames': 0,
        'composed_frames': 0,
        'planar_frames': 0,
        'av_drift_ms_samples': [],
        'scheduler_drift_ms_samples': [],
        'maximum_av_drift_ms': 0.0,
        'maximum_scheduler_drift_ms': 0.0,
        'audio_underruns': 0,
        'video_driver': '',
        'video_drm_driver': '',
        'video_device': '',
        'video_vendor': '',
    }


def sessionclock(session, moment=None):

    with session['lock']:

        position = max(0.0, number(session.get('position'), 0.0))
        state = str(session.get('state', 'loading'))
        reportedat = number(session.get('reportedat'), time.monotonic())
        duration = max(0.0, number(session.get('duration'), 0.0))

    if state in ('playing', 'draining'):

        current = (
            time.monotonic()
            if moment is None
            else max(0.0, number(moment, time.monotonic()))
        )
        position += max(0.0, current - reportedat)

    if duration > 0.0:

        position = min(position, duration)

    return position


def sessionpayload(session, state=None):

    with session['lock']:

        drifts = list(session.get('av_drift_ms_samples', []))
        schedulerdrifts = list(session.get('scheduler_drift_ms_samples', []))
        payload = {
            'type': 'media_status',
            'state': str(state or session.get('state', 'loading')),
            'media_kind': str(session.get('kind', 'unknown')),
            'position': sessionclock(session),
            'duration': max(0.0, number(session.get('duration'), 0.0)),
            'control': str(session.get('control', '') or ''),
            'video_control': str(session.get('video_control', '') or ''),
            'path': str(session.get('path', '')),
            'generation': integer(session.get('generation'), 0),
            'dropped_frames': integer(session.get('dropped'), 0),
            'video_backend': str(session.get('video_backend', 'pending')),
            'hardware_decode': bool(session.get('hardware_decode')),
            'zero_copy': bool(session.get('zero_copy')),
            'hardware_failure': str(session.get('hardware_failure', '') or ''),
            'presented_frames': integer(session.get('presented'), 0),
            'submitted_frames': integer(session.get('submitted_frames'), 0),
            'compositor_dropped_frames': integer(
                session.get('compositor_dropped_frames'),
                0,
            ),
            'decoded_frames': integer(session.get('decoded_frames'), 0),
            'gpu_scaled_frames': integer(session.get('gpu_scaled_frames'), 0),
            'composed_frames': integer(session.get('composed_frames'), 0),
            'planar_frames': integer(session.get('planar_frames'), 0),
            'maximum_av_drift_ms': round(number(session.get('maximum_av_drift_ms'), 0.0), 3),
            'percentile_50_av_drift_ms': round(percentile(drifts, 50.0), 3),
            'percentile_95_av_drift_ms': round(percentile(drifts, 95.0), 3),
            'maximum_scheduler_drift_ms': round(
                number(session.get('maximum_scheduler_drift_ms'), 0.0),
                3,
            ),
            'percentile_95_scheduler_drift_ms': round(
                percentile(schedulerdrifts, 95.0),
                3,
            ),
            'audio_underruns': integer(session.get('audio_underruns'), 0),
            'video_driver': str(session.get('video_driver', '')),
            'video_drm_driver': str(session.get('video_drm_driver', '')),
            'video_device': str(session.get('video_device', '')),
            'video_vendor': str(session.get('video_vendor', '')),
            'coded_resolution': [
                integer(session.get('coded_width'), 0),
                integer(session.get('coded_height'), 0),
            ],
            'presentation_surface_resolution': [
                integer(session.get('presentation_width'), 0),
                integer(session.get('presentation_height'), 0),
            ],
            'video': dict(session.get('info', {}).get('video', {})),
            'audio': dict(session.get('info', {}).get('audio', {})),
        }

    return payload


def emitstatus(session, state=None, force=False):

    now = time.monotonic()

    with session['lock']:

        if not force and now - number(session.get('laststatus'), 0.0) < STATUSINTERVAL:

            return

        session['laststatus'] = now
        callback = session.get('statuscallback')

    if callback is None:

        return

    try:

        callback(sessionpayload(session, state=state))

    except Exception:

        pass


def audiochanged(session, status):

    if not isinstance(status, dict):

        return

    state = str(status.get('state', 'loading'))
    now = time.monotonic()

    with session['lock']:

        previous = str(session.get('state', 'loading'))
        session['position'] = max(0.0, number(status.get('position'), session.get('position', 0.0)))
        session['reportedat'] = now
        session['duration'] = max(session.get('duration', 0.0), number(status.get('duration'), 0.0))
        session['control'] = str(status.get('control', '') or session.get('control', ''))
        session['audio_underruns'] = max(
            integer(session.get('audio_underruns'), 0),
            integer(status.get('audio_underruns'), 0),
        )

        if state == 'seeking' and previous != 'seeking':

            session['generation'] = integer(session.get('generation'), 0) + 1
            session['seekposition'] = session['position']

        if state == 'complete':

            session['audio_done'] = True
            session['state'] = 'complete' if session.get('video_done') else 'playing'

        else:

            session['state'] = state

        if state == 'stopped':

            session['audio_cancelled'] = True

    emitstatus(session, force=state in ('loading', 'paused', 'playing', 'seeking', 'stopped'))


def sessionstopped(session):

    if STOPREQUESTED:

        return True

    with session['lock']:

        return bool(session.get('audio_cancelled'))


def audioworker(session):

    try:

        audioapi.STOPREQUESTED = False
        audioapi.play(
            session['path'],
            ffmpegpath=session['ffmpegpath'],
            stopcheck=functools.partial(sessionstopped, session),
            statuscallback=functools.partial(audiochanged, session),
            controls=True,
            controlroot=MEDIAROOT,
            bufferseconds=AUDIOBUFFERSECONDS,
            prebufferms=AUDIOPREBUFFERMS,
            durationseconds=session.get('duration', 0.0),
            streamindex=session.get('info', {}).get('selected_audio_stream'),
            startseconds=session.get('seekposition', 0.0),
        )

        with session['lock']:

            session['audio_done'] = True

    except audioapi.AudioCancelled:

        with session['lock']:

            session['audio_cancelled'] = True
            session['audio_done'] = True

    except Exception as error:

        with session['lock']:

            session['audio_error'] = str(error)
            session['audio_done'] = True


def startsessionaudio(session):

    with session['lock']:

        if not bool(session.get('info', {}).get('audio')):

            return False

        if session.get('audio_thread') is not None:

            return False

        thread = threading.Thread(
            target=audioworker,
            args=(session,),
            daemon=True,
            name='media-audio',
        )
        session['audio_thread'] = thread

    thread.start()
    return True


def videocontrol(session):

    controller = session.get('controller')

    if controller is None:

        return ''

    controller.poll()

    resizesize = controller.takeresize()

    if resizesize is not None:

        width = max(2, integer(resizesize[0], session.get('maximumwidth', MAXWIDTH)))
        height = max(2, integer(resizesize[1], session.get('maximumheight', MAXHEIGHT)))

        if session.get('native_video'):

            context = session.get('native_context')
            sourcevideo = session.get('info', {}).get('video', {})
            targetwidth, targetheight = fitsize(
                integer(sourcevideo.get('display_width') or sourcevideo.get('width'), 0),
                integer(sourcevideo.get('display_height') or sourcevideo.get('height'), 0),
                width,
                height,
                aspect=number(sourcevideo.get('display_aspect'), 0.0),
            )

            if (
                isinstance(context, dict)
                and nativeresize(context, targetwidth, targetheight)
            ):

                with session['lock']:

                    session['maximumwidth'] = width
                    session['maximumheight'] = height
                    session['presentation_width'] = targetwidth
                    session['presentation_height'] = targetheight

                return ''

        position = sessionclock(session)

        with session['lock']:

            session['maximumwidth'] = width
            session['maximumheight'] = height
            session['position'] = position
            session['reportedat'] = time.monotonic()
            session['seekposition'] = position
            session['generation'] = integer(session.get('generation'), 0) + 1

        emitstatus(session, force=True)
        return 'resize'

    if not session.get('transport_controller'):

        return ''

    if controller.stopped:

        with session['lock']:

            session['audio_cancelled'] = True

        return 'stop'

    seekposition = controller.takeseek()

    if seekposition is not None:

        with session['lock']:

            duration = max(0.0, number(session.get('duration'), 0.0))
            position = max(0.0, number(seekposition, 0.0))

            if duration > 0.0:

                position = min(position, max(0.0, duration - 0.05))

            session['position'] = position
            session['reportedat'] = time.monotonic()
            session['seekposition'] = position
            session['generation'] = integer(session.get('generation'), 0) + 1
            session['state'] = 'seeking'

        emitstatus(session, force=True)
        return 'seek'

    with session['lock']:

        state = str(session.get('state', 'loading'))

    if controller.paused and state != 'paused':

        position = sessionclock(session)

        with session['lock']:

            session['position'] = position
            session['reportedat'] = time.monotonic()
            session['state'] = 'paused'

        emitstatus(session, force=True)
        return 'pause'

    if not controller.paused and state == 'paused':

        with session['lock']:

            session['reportedat'] = time.monotonic()
            session['state'] = 'playing'

        emitstatus(session, force=True)
        return 'resume'

    return ''


def checksession(session, generation):

    if session.get('controller') is not None:

        action = videocontrol(session)

        if action in ('stop', 'seek', 'resize'):

            return action

    if STOPREQUESTED or session.get('audio_cancelled'):

        return 'stop'

    if session.get('audio_error'):

        raise MediaDecodeError(session.get('audio_error'))

    if integer(session.get('generation'), 0) != int(generation):

        return 'seek'

    with session['lock']:

        hasaudiostream = bool(session.get('info', {}).get('audio'))
        audiodone = bool(session.get('audio_done'))
        duration = max(0.0, number(session.get('duration'), 0.0))
        state = str(session.get('state', 'loading'))

    if hasaudiostream and audiodone:

        return 'complete'

    if duration > 0.0 and state in ('playing', 'draining') and sessionclock(session) >= duration:

        return 'complete'

    return ''


def announceframe(session, path, width, height, pts):

    expected = int(width) * int(height) * 4

    if not os.path.isfile(path) or os.path.getsize(path) < expected:

        raise MediaDecodeError('shared video frame has an invalid size')

    with session['lock']:

        session['frameid'] = integer(session.get('frameid'), 0) + 1
        session['framepath'] = str(path)
        session['framewidth'] = int(width)
        session['frameheight'] = int(height)
        session['framepts'] = max(0.0, number(pts, 0.0))
        callback = session.get('framecallback')
        event = {
            'type': 'media_frame',
            'path': str(path),
            'width': int(width),
            'height': int(height),
            'pts': session['framepts'],
            'frame': session['frameid'],
            'generation': integer(session.get('generation'), 0),
            'media_kind': 'video',
        }

    if callback is not None:

        try:

            callback(event)

        except Exception:

            pass

    return event


def announcesurface(session, stream, width, height, pts, frame):

    with session['lock']:

        changed = (
            not session.get('frame_surface')
            or str(session.get('frame_stream', '')) != str(stream)
            or int(session.get('framewidth', 0)) != int(width)
            or int(session.get('frameheight', 0)) != int(height)
        )
        session['frameid'] = max(integer(session.get('frameid'), 0), int(frame))
        session['framepath'] = ''
        session['frame_surface'] = True
        session['frame_stream'] = str(stream)
        session['framewidth'] = int(width)
        session['frameheight'] = int(height)
        session['framepts'] = max(0.0, number(pts, 0.0))
        callback = session.get('framecallback')
        event = {
            'type': 'media_frame',
            'surface': True,
            'stream': str(stream),
            'width': int(width),
            'height': int(height),
            'pts': session['framepts'],
            'frame': int(frame),
            'generation': integer(session.get('generation'), 0),
            'media_kind': 'video',
        }

    if changed and callback is not None:

        try:

            callback(event)
            medialog(
                'native video surface announced '
                f'stream={stream} frame={int(frame)} size={int(width)}x{int(height)}'
            )

        except Exception:

            pass

    return event


def snapshotframe(session, sourcepath, width, height, pts):

    expected = int(width) * int(height) * 4

    if not os.path.isfile(sourcepath) or os.path.getsize(sourcepath) < expected:

        raise MediaDecodeError('decoded video frame has an invalid size')

    slot = integer(session.get('slot'), 0) % FRAMESLOTS
    path = os.path.join(session['root'], f'frame-{slot}.bgra')
    temporary = os.path.join(session['root'], f'.frame-{slot}-{threading.get_ident()}.tmp')
    source = None
    destination = None

    try:

        source = os.open(sourcepath, os.O_RDONLY | getattr(os, 'O_CLOEXEC', 0))
        destination = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_CLOEXEC', 0),
            0o600,
        )
        copied = 0

        if hasattr(os, 'copy_file_range'):

            try:

                while copied < expected:

                    count = os.copy_file_range(source, destination, expected - copied)

                    if count <= 0:

                        raise OSError('shared video frame copy ended early')

                    copied += int(count)

            except OSError:

                os.lseek(source, 0, os.SEEK_SET)
                os.lseek(destination, 0, os.SEEK_SET)
                os.ftruncate(destination, 0)
                copied = 0

        while copied < expected:

            block = os.read(source, min(1024 * 1024, expected - copied))

            if not block:

                raise MediaDecodeError('shared video frame copy ended early')

            offset = 0

            while offset < len(block):

                count = os.write(destination, block[offset:])

                if count <= 0:

                    raise MediaDecodeError('shared video frame copy ended early')

                offset += int(count)

            copied += len(block)

        os.close(source)
        source = None
        os.close(destination)
        destination = None
        os.replace(temporary, path)

    except Exception as error:

        if isinstance(error, MediaError):

            raise

        raise MediaDecodeError(f'cannot snapshot shared video frame: {error}')

    finally:

        for descriptor in (source, destination):

            if descriptor is not None:

                try:

                    os.close(descriptor)

                except Exception:

                    pass

        try:

            if os.path.exists(temporary):

                os.unlink(temporary)

        except Exception:

            pass

    with session['lock']:

        session['slot'] = (slot + 1) % FRAMESLOTS

    return announceframe(session, path, width, height, pts)


def publishframe(session, data, width, height, pts):

    expected = int(width) * int(height) * 4

    if len(data) != expected:

        raise MediaDecodeError('video frame has an invalid size')

    slot = integer(session.get('slot'), 0) % FRAMESLOTS
    path = os.path.join(session['root'], f'frame-{slot}.bgra')
    temporary = os.path.join(session['root'], f'.frame-{slot}-{threading.get_ident()}.tmp')
    descriptor = None

    try:

        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)

        with os.fdopen(descriptor, 'wb') as stream:

            descriptor = None
            stream.write(data)
            stream.flush()

        os.replace(temporary, path)

    except Exception as error:

        raise MediaDecodeError(f'cannot publish video frame: {error}')

    finally:

        if descriptor is not None:

            try:

                os.close(descriptor)

            except Exception:

                pass

        try:

            if os.path.exists(temporary):

                os.unlink(temporary)

        except Exception:

            pass

    with session['lock']:

        session['slot'] = (slot + 1) % FRAMESLOTS

    return announceframe(session, path, width, height, pts)


def _decodenativecontext(session, generation, startseconds, context):

    lastpresentpts = None
    framesseen = 0
    stream = str(context.get('video_transport', {}).get('stream', ''))

    while True:

        action = checksession(session, generation)

        if action:

            return action

        pollvideosurface(context)

        try:

            frame = context['frames'].get(timeout=0.01)

        except queue.Empty:

            if context['framedone'].is_set() and context['frames'].empty():

                break

            emitstatus(session)
            continue

        framesseen += 1
        targetpts = max(0.0, number(frame.get('pts_ns'), 0.0) / 1000000000.0)

        with session['lock']:

            session['decoded_frames'] = integer(
                session.get('decoded_frames'),
                0,
            ) + 1
            session['coded_width'] = integer(
                frame.get('coded_width'),
                session.get('coded_width', 0),
            )
            session['coded_height'] = integer(
                frame.get('coded_height'),
                session.get('coded_height', 0),
            )

        if targetpts + LATELIMIT < max(0.0, float(startseconds)):

            releasenativeframe(context, frame)

            with session['lock']:

                session['dropped'] = integer(session.get('dropped'), 0) + 1

            continue

        while True:

            action = checksession(session, generation)

            if action:

                releasenativeframe(context, frame)
                return action

            pollvideosurface(context)

            with session['lock']:

                state = str(session.get('state', 'loading'))

            if state == 'paused':

                time.sleep(0.01)
                continue

            if state in ('loading', 'seeking') and lastpresentpts is not None:

                time.sleep(0.01)
                emitstatus(session)
                continue

            clock = sessionclock(session)

            if targetpts > clock + 0.003 and state not in ('loading', 'seeking'):

                time.sleep(min(0.01, targetpts - clock))
                emitstatus(session)
                continue

            break

        clock = sessionclock(session)
        drift = clock - targetpts

        if (
            (lastpresentpts is not None and targetpts <= lastpresentpts)
            or drift > LATELIMIT
        ):

            releasenativeframe(context, frame)

            with session['lock']:

                session['dropped'] = integer(session.get('dropped'), 0) + 1

            continue

        with session['lock']:

            drifts = session.setdefault('scheduler_drift_ms_samples', [])
            drifts.append(abs(drift) * 1000.0)
            if len(drifts) > 4096:
                del drifts[:len(drifts) - 4096]
            session['maximum_scheduler_drift_ms'] = max(
                number(session.get('maximum_scheduler_drift_ms'), 0.0),
                abs(drift) * 1000.0,
            )

        firstsubmission = lastpresentpts is None
        sendnativeframe(context, frame)
        lastpresentpts = targetpts

        with session['lock']:

            session['submitted_frames'] = integer(
                session.get('submitted_frames'),
                0,
            ) + 1
            if bool(frame.get('gpu_scaled', False)):
                session['gpu_scaled_frames'] = integer(
                    session.get('gpu_scaled_frames'),
                    0,
                ) + 1
            if len(frame.get('layers', [])) == 2:
                session['planar_frames'] = integer(
                    session.get('planar_frames'),
                    0,
                ) + 1
            else:
                session['composed_frames'] = integer(
                    session.get('composed_frames'),
                    0,
                ) + 1
            session['presentation_width'] = integer(
                frame.get('width'),
                session.get('presentation_width', 0),
            )
            session['presentation_height'] = integer(
                frame.get('height'),
                session.get('presentation_height', 0),
            )

        announcesurface(
            session,
            stream,
            integer(frame.get('width'), context.get('width', 0)),
            integer(frame.get('height'), context.get('height', 0)),
            targetpts,
            integer(frame.get('frame'), framesseen),
        )

        if firstsubmission and bool(
            session.get('info', {}).get('audio')
        ):
            firstframe = integer(frame.get('frame'), framesseen)
            readinessdeadline = time.monotonic() + 2.0

            while (
                firstframe not in context.get('presented_frames', set())
                and firstframe not in context.get('dropped_frames', set())
                and time.monotonic() < readinessdeadline
            ):
                pollvideosurface(context)
                time.sleep(0.002)

            # Begin the audio clock only after the first GPU surface is wired
            # into the player's retained scene.  This is the normal A/V
            # prebuffer boundary: decoder and compositor setup time must not
            # become a permanent video delay.
            startsessionaudio(session)

        emitstatus(session)

    lastframe = integer(context.get('last_submitted_frame'), 0)
    presentationdeadline = time.monotonic() + 0.20

    while (
        lastframe > 0
        and lastframe not in context.get('presented_frames', set())
        and lastframe not in context.get('dropped_frames', set())
        and time.monotonic() < presentationdeadline
    ):

        pollvideosurface(context)
        time.sleep(0.002)

    pollvideosurface(context)

    if context.get('frameerror'):

        raise MediaHardwareDecodeError(context.get('frameerror'))

    if not context.get('native_eof'):

        raise MediaHardwareDecodeError(decoderdetail(context))

    if framesseen <= 0:

        raise MediaHardwareDecodeError('native GPU decoder produced no video frames')

    return 'complete'


def _decodegeneration(session, generation, startseconds, hardware):

    context = startvideo(session, startseconds, hardware=hardware)

    if context.get('native'):

        try:

            return _decodenativecontext(
                session,
                generation,
                startseconds,
                context,
            )

        finally:

            stopvideo(context)

    framerate = max(1.0, number(context.get('framerate'), 25.0))
    framestep = 1.0 / framerate
    lastpresentpts = None
    framesseen = 0

    try:

        while True:

            action = checksession(session, generation)

            if action:

                return action

            try:

                index, framepath = context['frames'].get(timeout=0.03)

            except queue.Empty:

                if context['framedone'].is_set() and context['frames'].empty():

                    break

                emitstatus(session)
                continue

            pts = index * framestep
            framesseen += 1
            targetpts = max(0.0, float(startseconds) + pts)

            with session['lock']:

                session['decoded_frames'] = integer(
                    session.get('decoded_frames'),
                    0,
                ) + 1

            while True:

                action = checksession(session, generation)

                if action:

                    return action

                with session['lock']:

                    state = str(session.get('state', 'loading'))

                if state == 'paused':

                    time.sleep(0.02)
                    continue

                if state in ('loading', 'seeking') and lastpresentpts is not None:

                    time.sleep(0.02)
                    emitstatus(session)
                    continue

                clock = sessionclock(session)

                if targetpts > clock + 0.005 and state not in ('loading', 'seeking'):

                    time.sleep(min(0.02, targetpts - clock))
                    emitstatus(session)
                    continue

                break

            clock = sessionclock(session)
            late = clock - targetpts
            tooearly = (
                lastpresentpts is not None
                and targetpts < lastpresentpts + (1.0 / MAXFPS) - 0.001
            )

            if tooearly or late > LATELIMIT:

                with session['lock']:

                    session['dropped'] = integer(session.get('dropped'), 0) + 1

                continue

            with session['lock']:

                drifts = session.setdefault('av_drift_ms_samples', [])
                drifts.append(abs(late) * 1000.0)
                if len(drifts) > 4096:
                    del drifts[:len(drifts) - 4096]
                session['maximum_av_drift_ms'] = max(
                    number(session.get('maximum_av_drift_ms'), 0.0),
                    abs(late) * 1000.0,
                )

            firstpresentation = lastpresentpts is None
            snapshotframe(session, framepath, context['width'], context['height'], targetpts)

            if firstpresentation:
                startsessionaudio(session)

            lastpresentpts = targetpts

            with session['lock']:

                session['presented'] = integer(session.get('presented'), 0) + 1

            emitstatus(session)

        process = context.get('process')

        try:

            code = process.wait(timeout=1.0)

        except subprocess.TimeoutExpired:

            frameerror = str(context.get('frameerror', '') or '').strip()
            detail = decoderdetail(context)
            if frameerror:
                raise MediaDecodeError(f'video frame reader failed: {frameerror}')
            raise MediaDecodeError(
                'video decoder did not exit'
                + (f': {detail}' if detail else '')
            )

        if context.get('frameerror'):

            if hardware and framesseen <= 0:

                raise MediaHardwareDecodeError(context.get('frameerror'))

            raise MediaDecodeError(context.get('frameerror'))

        if int(code) != 0:

            error = decoderdetail(context)

            if hardware and framesseen <= 0:

                raise MediaHardwareDecodeError(error)

            raise MediaDecodeError(error)

        if framesseen <= 0:

            if hardware:

                raise MediaHardwareDecodeError('hardware decoder produced no video frames')

            raise MediaDecodeError('file contains no decodable video frames')

        return 'complete'

    finally:

        stopvideo(context)


def decodegeneration(session, generation, startseconds):

    transport = session.get('video_transport', {})
    rendernode = transport.get('render_node', '')
    video = session.get('info', {}).get('video', {})
    attempts = []
    acceleration = videoacceleration(
        video,
        diagnostics=attempts,
        preferrednode=rendernode,
    )

    # A cached negative result has no attempt records. Re-run only that failed
    # probe so playback logs contain the real native return code and stderr;
    # successful selections and seeks continue to use the cache.
    if not acceleration and not attempts:

        acceleration = videoacceleration(
            video,
            refresh=True,
            diagnostics=attempts,
            preferrednode=rendernode,
        )

    streamdiagnostic = {
        'codec': cleanvalue(video.get('codec')),
        'profile': cleanvalue(video.get('profile')),
        'pixel_format': cleanvalue(video.get('pixel_format')),
        'bit_depth': integer(video.get('bit_depth'), 0),
        'width': integer(video.get('width'), 0),
        'height': integer(video.get('height'), 0),
        'preferred_node': cleanvalue(rendernode),
    }
    medialog(
        'video acceleration probe '
        + json.dumps(
            {
                'stream': streamdiagnostic,
                'attempts': attempts,
                'selected': (
                    {
                        'backend': acceleration.get('backend'),
                        'drm_driver': acceleration.get('drm_driver'),
                        'driver': acceleration.get('driver'),
                        'device': acceleration.get('device'),
                        'vendor': acceleration.get('vendor'),
                        'matched_profiles': acceleration.get(
                            'matched_profiles',
                            [],
                        ),
                    }
                    if acceleration
                    else None
                ),
            },
            sort_keys=True,
            separators=(',', ':'),
        )
    )
    required = bool(
        acceleration and acceleration.get('hardware_required')
    ) or hardwaredecoderequired(
        rendernode,
        backend=transport.get('drm_driver', ''),
    )

    if not acceleration:

        if required:

            failure = (
                'hardware video decode is required for the active GPU; '
                + videoaccelerationattemptsummary(attempts)
            )

            with session['lock']:

                session['hardware_failure'] = failure

            emitstatus(session, force=True)
            raise MediaHardwareDecodeError(
                failure
            )

        return _decodegeneration(session, generation, startseconds, False)

    try:

        return _decodegeneration(session, generation, startseconds, True)

    except MediaHardwareDecodeError as error:

        if required:

            with session['lock']:

                session['hardware_failure'] = cleanvalue(str(error))

            raise

        fallbackstart = max(float(startseconds), sessionclock(session))

        with session['lock']:

            session['video_backend'] = 'software-fallback'
            session['hardware_decode'] = False
            session['zero_copy'] = False
            session['native_video'] = False
            session['hardware_failure'] = cleanvalue(str(error))

        return _decodegeneration(session, generation, fallbackstart, False)


def waitaudio(session, generation):

    while True:

        action = checksession(session, generation)

        if action:

            return action

        with session['lock']:

            done = bool(session.get('audio_done'))

        if done:

            return 'complete'

        emitstatus(session)
        time.sleep(0.02)


def cleanupframe(path):

    try:

        target = os.path.realpath(str(path))
        root = os.path.realpath(MEDIAROOT)
        parent = target if os.path.isdir(target) else os.path.dirname(target)

        if os.path.commonpath((root, parent)) != root or parent == root:

            return False

        if not os.path.basename(parent).startswith('session-') or os.path.islink(parent):

            return False

        shutil.rmtree(parent, ignore_errors=True)
        return not os.path.exists(parent)

    except Exception:

        return False


def playvideo(session):

    info = session['info']
    hasaudiostream = bool(info.get('audio'))

    try:

        session['controller'] = audioapi.PlaybackController(root=MEDIAROOT)
        session['video_control'] = session['controller'].path
        session['transport_controller'] = not hasaudiostream

    except Exception as error:

        raise MediaUnavailable(f'cannot create media playback controls: {error}')

    if not hasaudiostream:

        session['control'] = session['controller'].path
        session['state'] = 'playing'
        session['reportedat'] = time.monotonic()

    emitstatus(session, force=True)

    while True:

        with session['lock']:

            generation = integer(session.get('generation'), 0)
            startseconds = max(0.0, number(session.get('seekposition'), 0.0))
            session['video_done'] = False

            if session.get('controller') is not None and session.get('transport_controller'):

                session['position'] = startseconds
                session['reportedat'] = time.monotonic()
                session['state'] = 'paused' if session['controller'].paused else 'playing'

        if session.get('controller') is not None:

            emitstatus(session, force=True)

        result = decodegeneration(session, generation, startseconds)

        if result == 'stop':

            raise MediaCancelled('playback stopped')

        if result in ('seek', 'resize'):

            continue

        with session['lock']:

            session['video_done'] = True

        if not hasaudiostream:

            break

        result = waitaudio(session, generation)

        if result in ('seek', 'resize'):

            continue

        if result == 'stop':

            raise MediaCancelled('playback stopped')

        break

    with session['lock']:

        session['position'] = sessionclock(session)
        session['reportedat'] = time.monotonic()
        session['state'] = 'complete'

    emitstatus(session, force=True)

    return {
        'path': session['path'],
        'kind': 'video',
        'duration': session['duration'],
        'frame_path': session.get('framepath', ''),
        'frame_size': [session.get('framewidth', 0), session.get('frameheight', 0)],
        'frames': session.get('frameid', 0),
        'dropped_frames': session.get('dropped', 0),
        'root': session.get('root', ''),
    }


def playaudiostatus(callback, status):

    if callback is None or not isinstance(status, dict):

        return

    payload = dict(status)
    payload['type'] = 'media_status'
    payload['media_kind'] = 'audio'
    payload['generation'] = 0
    payload['dropped_frames'] = 0

    try:

        callback(payload)

    except Exception:

        pass


def play(
    path,
    ffmpegpath=FFMPEGPATH,
    ffprobepath=FFPROBEPATH,
    statuscallback=None,
    framecallback=None,
    controls=True,
    maximumwidth=MAXWIDTH,
    maximumheight=MAXHEIGHT,
    retainframe=False,
    infocallback=None,
    video_transport=None,
    video_stream_index=None,
    audio_stream_index=None,
    subtitle_stream_index=None,
    startseconds=0.0,
):

    target = os.path.realpath(os.path.abspath(os.path.normpath(str(path))))

    if not os.path.exists(target):

        raise MediaDecodeError(f'media file not found: {target}')

    if not os.path.isfile(target):

        raise MediaDecodeError(f'not a media file: {target}')

    if not os.access(target, os.R_OK):

        raise MediaDecodeError(f'media file is not readable: {target}')

    info = mediainfo(target, ffprobepath=ffprobepath, ffmpegpath=ffmpegpath)
    info = selecttracks(
        info,
        video_stream_index=video_stream_index,
        audio_stream_index=audio_stream_index,
        subtitle_stream_index=subtitle_stream_index,
    )

    if infocallback is not None:

        try:

            infocallback(dict(info))

        except Exception:

            pass

    if info.get('kind') == 'audio':

        try:

            audioapi.STOPREQUESTED = False
            result = audioapi.play(
                target,
                ffmpegpath=ffmpegpath,
                statuscallback=functools.partial(playaudiostatus, statuscallback),
                controls=controls,
                controlroot=MEDIAROOT,
                bufferseconds=AUDIOBUFFERSECONDS,
                prebufferms=AUDIOPREBUFFERMS,
                durationseconds=info.get('duration', 0.0),
                streamindex=info.get('selected_audio_stream'),
                startseconds=startseconds,
            )
            result['kind'] = 'audio'
            return result

        except audioapi.AudioCancelled as error:

            raise MediaCancelled(str(error))

        except audioapi.AudioError as error:

            raise MediaDecodeError(str(error))

    if info.get('kind') != 'video':

        raise MediaDecodeError('file contains no supported audio or video stream')

    session = newsession(
        target,
        info,
        statuscallback,
        framecallback,
        ffmpegpath,
        maximumwidth,
        maximumheight,
        retainframe,
        video_transport=video_transport,
        startseconds=startseconds,
    )
    emitstatus(session, force=True)

    try:

        return playvideo(session)

    except MediaCancelled:

        with session['lock']:

            session['state'] = 'stopped'

        emitstatus(session, force=True)
        raise

    except MediaError:

        with session['lock']:

            session['state'] = 'error'

        emitstatus(session, force=True)
        raise

    finally:

        control = str(session.get('control', '') or '')
        thread = session.get('audio_thread')

        if thread is not None and thread.is_alive():

            audioapi.sendcontrol(control, 'stop')
            audioapi.requeststop()
            thread.join(timeout=1.0)

        controller = session.get('controller')

        if controller is not None:

            controller.close()

        if not session.get('retainframe') or not session.get('framepath'):

            cleanupframe(session.get('root', ''))



## signal functions
def requeststop(signum=None, frame=None):

    global STOPREQUESTED

    STOPREQUESTED = True
    audioapi.STOPREQUESTED = True
    audioapi.requeststop(signum, frame)
    process = ACTIVEVIDEO

    if process is not None:

        audioapi.terminateprocess(process)



## diagnostic functions
def diagnosticcontrolworker(state, path):

    try:

        state['result'] = play(
            path,
            statuscallback=state['statuses'].append,
            framecallback=state['frames'].append,
            maximumwidth=64,
            maximumheight=36,
        )

    except MediaCancelled:

        state['cancelled'] = True

    except Exception as error:

        state['error'] = str(error)

    finally:

        state['done'].set()


def diagnosticaudio(
    path,
    ffmpegpath=FFMPEGPATH,
    socketpath=audioapi.AUDIOSOCK,
    stopcheck=None,
    statuscallback=None,
    controls=False,
    bufferseconds=None,
    prebufferms=None,
    durationseconds=None,
):

    controller = audioapi.PlaybackController() if controls else None
    controlpath = controller.path if controller is not None else ''
    duration = 2.0
    baseposition = 0.0
    started = time.monotonic()
    pausedat = 0.0
    audioapi.playbackstatus(statuscallback, 'loading', 0.0, duration, controlpath, path)

    try:

        while baseposition < duration:

            if controller is not None:

                controller.poll()

                if controller.stopped:

                    raise audioapi.AudioCancelled('playback stopped')

                seekposition = controller.takeseek()

                if seekposition is not None:

                    baseposition = max(0.0, min(duration, number(seekposition, 0.0)))
                    started = time.monotonic()
                    audioapi.playbackstatus(statuscallback, 'seeking', baseposition, duration, controlpath, path)

                if controller.paused:

                    if pausedat <= 0.0:

                        pausedat = time.monotonic()

                    audioapi.playbackstatus(statuscallback, 'paused', baseposition, duration, controlpath, path)
                    time.sleep(0.02)
                    continue

                if pausedat > 0.0:

                    started += time.monotonic() - pausedat
                    pausedat = 0.0

            if stopcheck is not None and stopcheck():

                raise audioapi.AudioCancelled('playback stopped')

            position = min(duration, baseposition + max(0.0, time.monotonic() - started))
            audioapi.playbackstatus(statuscallback, 'playing', position, duration, controlpath, path)

            if position >= duration:

                baseposition = duration
                break

            time.sleep(0.02)

        audioapi.playbackstatus(statuscallback, 'complete', duration, duration, controlpath, path)
        return {'path': path, 'duration': duration, 'decoded_bytes': 1}

    finally:

        if controller is not None:

            controller.close()


def diagnostic(paths=None):

    result = {
        'format': 1,
        'passed': False,
        'checks': {},
        'errors': [],
    }
    root = f'/.ephemeral/media-diagnostic-{os.getpid()}'

    try:

        build = subprocess.run(
            [FFMPEGPATH, '-hide_banner', '-buildconf'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5.0,
            check=False,
        )
        buildtext = (build.stdout + build.stderr).decode('utf-8', errors='replace')

        if build.returncode != 0 or '--disable-x86asm' in buildtext:

            raise MediaDecodeError('media decoder is missing required x86 optimizations')

        result['checks']['decoder_optimizations'] = True

        payload = {
            'format': {
                'format_name': 'mov,mp4,m4a,3gp,3g2,mj2',
                'duration': '12.5',
                'size': '4096',
                'bit_rate': '1200000',
                'tags': {'title': 'Signal Film', 'artist': 'The Diagnostics'},
            },
            'streams': [
                {
                    'index': 0,
                    'codec_type': 'video',
                    'codec_name': 'h264',
                    'profile': 'High',
                    'width': 1920,
                    'height': 1080,
                    'avg_frame_rate': '24000/1001',
                    'pix_fmt': 'yuv420p10le',
                    'disposition': {'default': 1, 'attached_pic': 0},
                    'side_data_list': [{'rotation': 0}],
                },
                {
                    'index': 1,
                    'codec_type': 'audio',
                    'codec_name': 'aac',
                    'sample_rate': '48000',
                    'channels': 2,
                    'channel_layout': 'stereo',
                    'disposition': {'default': 1},
                },
                {
                    'index': 2,
                    'codec_type': 'video',
                    'codec_name': 'png',
                    'width': 600,
                    'height': 600,
                    'disposition': {'default': 0, 'attached_pic': 1},
                },
            ],
        }
        info = parseprobe(payload, '/master/videos/signal.mp4')

        if (
            info.get('kind') != 'video'
            or info.get('video', {}).get('codec') != 'H264'
            or info.get('audio', {}).get('codec') != 'AAC'
            or info.get('video', {}).get('bit_depth') != 10
            or not info.get('artwork')
            or info.get('tags', {}).get('title') != 'Signal Film'
        ):

            raise MediaDecodeError(f'media probe parser failed: {info}')

        result['checks']['probe_parser'] = info

        if fitsize(1920, 1080) != [1920, 1080] or fitsize(1080, 1920) != [1080, 1920]:

            raise MediaDecodeError('video fit calculation failed')

        result['checks']['fit'] = True
        expectedbackends = {
            'i915': ['iHD'],
            'xe': ['iHD'],
            'amdgpu': ['radeonsi'],
            'radeon': ['radeonsi', 'r600'],
            'nvidia': ['nvidia'],
            'nvidia-drm': ['nvidia'],
            'nouveau': ['nouveau'],
            'vmwgfx': ['vmwgfx'],
            'virtio_gpu': ['virtio_gpu'],
        }

        for backend, expected in expectedbackends.items():

            actual = [
                entry.get('driver')
                for entry in vaapicandidates(
                    backend,
                    contractpath='/nonexistent/t1os-video-contract.json',
                )
            ]

            if actual != expected:

                raise MediaDecodeError(
                    f'video backend mapping failed for {backend}: {actual}'
                )

        if (
            not vaapiprofilematches(
                {
                    'codec': 'HEVC',
                    'name': 'HEVCMain10',
                    'bit_depths': [10],
                    'max_width': 4096,
                    'max_height': 2304,
                },
                {
                    'codec': 'HEVC',
                    'profile': 'Main 10',
                    'bit_depth': 10,
                    'width': 3840,
                    'height': 2160,
                },
            )
            or vaapiprofilematches(
                {
                    'codec': 'HEVC',
                    'name': 'HEVCMain',
                    'bit_depths': [8],
                    'max_width': 4096,
                    'max_height': 2304,
                },
                {
                    'codec': 'HEVC',
                    'profile': 'Main 10',
                    'bit_depth': 10,
                    'width': 3840,
                    'height': 2160,
                },
            )
        ):

            raise MediaDecodeError('VAAPI stream capability matching failed')

        result['checks']['hardware_backend_contract'] = expectedbackends
        result['checks']['hardware_profile_matching'] = True
        command, width, height, framerate = videocommand('/master/videos/signal.mp4', info['video'])

        if (
            width != 1920
            or height != 1080
            or abs(framerate - info['video']['frame_rate']) > 0.001
            or 'rawvideo' not in command
            or not any('fps=fps=' in value for value in command)
            or any('showinfo' in value for value in command)
        ):

            raise MediaDecodeError('video decoder command is incomplete')

        result['checks']['decoder_command'] = command
        hardwarecommand, hardwarewidth, hardwareheight, _ = videocommand(
            '/master/videos/signal.mp4',
            info['video'],
            acceleration={
                'backend': 'virtualbox-vmsvga-vaapi',
                'driver': 'vmwgfx',
                'device': '/the one/drivers/nodes/dri/renderD128',
            },
        )

        if (
            hardwarewidth != 1920
            or hardwareheight != 1080
            or '-hwaccel' not in hardwarecommand
            or 'vaapi' not in hardwarecommand
            or not any(
                'scale_vaapi=w=1920:h=1080:format=bgra' in value
                and 'hwdownload,format=bgra' in value
                for value in hardwarecommand
            )
        ):

            raise MediaDecodeError('hardware video decoder command is incomplete')

        result['checks']['hardware_decoder_command'] = hardwarecommand

        decoderparent, decoderpeer = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        videoparent, videopeer = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        receivedfds = []
        testfd = None

        try:

            videoparent.setblocking(False)
            protocolcontext = {
                'decoder_socket': decoderparent,
                'video_socket': videoparent,
                'video_transport': {'stream': 'diagnostic'},
                'outstanding': set(),
            }
            # The protocol check only needs a transferable descriptor.  Use
            # this measured source file so the diagnostic remains valid before
            # Driver Server has populated the runtime device-node tree.
            testfd = os.open(os.path.realpath(__file__), os.O_RDONLY)
            protocolframe = {
                'op': 'frame',
                'frame': 41,
                'pts_ns': 125000000,
                'duration_ns': 41666667,
                'width': 1920,
                'height': 1080,
                'format': 'drm_prime',
                'objects': [{'size': 4096, 'modifier': 0}],
                'layers': [{'fourcc': 842094158, 'planes': [{'object': 0, 'offset': 0, 'pitch': 1920}]}],
                'fds': [testfd],
            }
            testfd = None
            sendnativeframe(protocolcontext, protocolframe)
            packet, ancillary, _, _ = videopeer.recvmsg(
                65536,
                socket.CMSG_SPACE(array.array('i').itemsize * VIDEOMAXFDS),
            )

            for level, kind, payload in ancillary:

                if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:

                    values = array.array('i')
                    values.frombytes(payload[:len(payload) - (len(payload) % values.itemsize)])
                    receivedfds.extend(int(value) for value in values)

            descriptor = json.loads(packet.decode('utf-8'))

            if (
                descriptor.get('frame') != 41
                or descriptor.get('stream') != 'diagnostic'
                or len(receivedfds) != 1
                or protocolcontext.get('outstanding') != {41}
            ):

                raise MediaDecodeError('native GPU frame descriptor transport failed')

            videopeer.send(b'{"op":"presented","frame":41,"pts_ns":125000000}')
            pollvideosurface(protocolcontext)

            if protocolcontext.get('presented_frames') != {41}:

                raise MediaDecodeError('native GPU presentation acknowledgement failed')

            videopeer.send(b'{"op":"release","frame":41}')
            pollvideosurface(protocolcontext)
            control = decoderpeer.recv(64)
            magic, kind, frameid = struct.unpack('<IIQ', control)

            if (
                magic != VIDEOCONTROLMAGIC
                or kind != VIDEOCONTROLRELEASE
                or frameid != 41
                or protocolcontext.get('outstanding')
            ):

                raise MediaDecodeError('native GPU frame release transport failed')

            if not nativeresize(protocolcontext, 800, 450):

                raise MediaDecodeError('native GPU presentation resize could not be sent')

            resizecontrol = decoderpeer.recv(64)
            resizemagic, resizekind, resizevalue = struct.unpack(
                '<IIQ',
                resizecontrol,
            )

            if (
                resizemagic != VIDEOCONTROLMAGIC
                or resizekind != VIDEOCONTROLRESIZE
                or resizevalue != ((800 << 32) | 450)
            ):

                raise MediaDecodeError('native GPU presentation resize transport failed')

            result['checks']['native_surface_protocol'] = True
            result['checks']['native_presentation_acknowledgement'] = True
            result['checks']['native_adaptive_resize'] = [800, 450]

        finally:

            if testfd is not None:

                os.close(testfd)

            for descriptor in receivedfds:

                os.close(descriptor)

            decoderparent.close()
            decoderpeer.close()
            videoparent.close()
            videopeer.close()

        os.makedirs(root, mode=0o700, exist_ok=False)
        session = newsession(
            '/master/videos/signal.mp4',
            info,
            None,
            None,
            FFMPEGPATH,
            16,
            16,
            False,
        )
        frame = bytes((0x11, 0x22, 0x33, 0xff)) * 4
        publishframe(session, frame, 2, 2, 0.0)

        if not os.path.isfile(session.get('framepath', '')) or os.path.getsize(session['framepath']) != 16:

            raise MediaDecodeError('atomic video frame publication failed')

        result['checks']['frame_publication'] = True
        cleanupframe(session['root'])

        decoded = {}
        sharedrings = {}
        decoderpriorities = {}
        videoonly = ''
        audiovideo = ''

        for path in list(paths or []):

            target = os.path.abspath(os.path.normpath(str(path)))
            fixture = mediainfo(target)

            if fixture.get('kind') != 'video':

                raise MediaDecodeError(f'video fixture was not identified: {target}')

            if not fixture.get('audio'):

                videoonly = target

            else:

                audiovideo = target

            fixturesession = newsession(target, fixture, None, None, FFMPEGPATH, 320, 180, False)
            context = startvideo(fixturesession, 0.0)

            try:

                index, framepath = context['frames'].get(timeout=10.0)
                nextindex, nextpath = context['frames'].get(timeout=10.0)

                if (
                    index != 0
                    or nextindex != 1
                    or framepath == nextpath
                    or len(context.get('slots', [])) != FRAMESLOTS
                    or not all(
                        isinstance(slot.get('buffer'), bytearray)
                        and isinstance(slot.get('descriptor'), int)
                        for slot in context['slots']
                    )
                    or (
                        hasattr(os, 'setpriority')
                        and context.get('decoder_nice') != VIDEODECODERNICE
                    )
                    or not os.path.isfile(framepath)
                    or os.path.getsize(framepath) != context['framesize']
                    or not os.path.isfile(nextpath)
                    or os.path.getsize(nextpath) != context['framesize']
                ):

                    raise MediaDecodeError(f'video fixture returned an invalid frame: {target}')

                decoded[target] = [context['width'], context['height'], os.path.getsize(framepath)]
                sharedrings[target] = len(context['slots'])
                decoderpriorities[target] = context.get('decoder_nice')

            finally:

                stopvideo(context)
                cleanupframe(fixturesession['root'])

        result['checks']['decoded'] = decoded
        result['checks']['shared_frame_ring'] = sharedrings
        result['checks']['video_decoder_priority'] = decoderpriorities

        if videoonly:

            statuses = []
            frames = []
            playback = play(
                videoonly,
                statuscallback=statuses.append,
                framecallback=frames.append,
                maximumwidth=64,
                maximumheight=36,
                retainframe=True,
            )

            invalidplayback = (
                playback.get('kind') != 'video'
                or playback.get('frames', 0) < FRAMESLOTS
                or not frames
                or any(not os.path.basename(str(frame.get('path', ''))).startswith('frame-') for frame in frames)
                or any(os.path.getsize(str(frame.get('path', ''))) != integer(frame.get('width')) * integer(frame.get('height')) * 4 for frame in frames)
                or not statuses
                or statuses[-1].get('state') != 'complete'
            )
            playbackroot = os.path.dirname(str(frames[-1].get('path', ''))) if frames else ''
            cleanupframe(playbackroot)

            if invalidplayback:

                raise MediaDecodeError('video-only playback lifecycle failed')

            result['checks']['video_only_playback'] = {
                'frames': playback.get('frames', 0),
                'statuses': len(statuses),
                'dropped': playback.get('dropped_frames', 0),
                'atomic_snapshots': True,
            }

            controlstate = {
                'statuses': [],
                'frames': [],
                'result': {},
                'cancelled': False,
                'error': '',
                'done': threading.Event(),
            }
            controlthread = threading.Thread(
                target=diagnosticcontrolworker,
                args=(controlstate, videoonly),
                daemon=True,
                name='media-control-diagnostic',
            )
            controlthread.start()
            deadline = time.monotonic() + 5.0
            controlpath = ''

            while time.monotonic() < deadline and not controlpath:

                for status in list(controlstate['statuses']):

                    controlpath = str(status.get('control', '') or controlpath)

                if not controlpath:

                    time.sleep(0.01)

            while time.monotonic() < deadline and not controlstate['frames']:

                time.sleep(0.01)

            if not controlstate['frames']:

                raise MediaDecodeError('video playback did not publish a frame before control testing')

            if not controlpath or not audioapi.sendcontrol(controlpath, 'pause'):

                raise MediaDecodeError('video pause control could not be sent')

            while time.monotonic() < deadline and not any(status.get('state') == 'paused' for status in controlstate['statuses']):

                time.sleep(0.01)

            if not any(status.get('state') == 'paused' for status in controlstate['statuses']):

                raise MediaDecodeError('video playback did not pause')

            initialgeneration = max(integer(status.get('generation'), 0) for status in controlstate['statuses'])

            if not audioapi.sendcontrol(controlpath, 'resize', width=32, height=18):

                raise MediaDecodeError('video resize control could not be sent')

            deadline = time.monotonic() + 5.0

            while time.monotonic() < deadline and not any(
                integer(status.get('generation'), 0) > initialgeneration
                for status in controlstate['statuses']
            ):

                time.sleep(0.01)

            resizegeneration = max(integer(status.get('generation'), 0) for status in controlstate['statuses'])

            if resizegeneration <= initialgeneration:

                raise MediaDecodeError('video decoder did not accept the requested size')

            if not audioapi.sendcontrol(controlpath, 'seek', position=0.8):

                raise MediaDecodeError('video seek control could not be sent')

            deadline = time.monotonic() + 5.0

            while time.monotonic() < deadline and not any(integer(status.get('generation'), 0) > resizegeneration for status in controlstate['statuses']):

                time.sleep(0.01)

            if not any(integer(status.get('generation'), 0) > resizegeneration for status in controlstate['statuses']):

                raise MediaDecodeError('video playback did not seek')

            seekgeneration = max(integer(status.get('generation'), 0) for status in controlstate['statuses'])

            if not audioapi.sendcontrol(controlpath, 'resume'):

                raise MediaDecodeError('video resume control could not be sent')

            deadline = time.monotonic() + 5.0

            while time.monotonic() < deadline and not any(
                integer(frame.get('width'), 0) == 32
                and integer(frame.get('height'), 0) == 18
                and integer(frame.get('generation'), 0) >= seekgeneration
                for frame in controlstate['frames']
            ):

                time.sleep(0.01)

            if not any(
                integer(frame.get('width'), 0) == 32
                and integer(frame.get('height'), 0) == 18
                and integer(frame.get('generation'), 0) >= seekgeneration
                for frame in controlstate['frames']
            ):

                raise MediaDecodeError('video decoder did not restart at the requested size')

            if not audioapi.sendcontrol(controlpath, 'stop'):

                raise MediaDecodeError('video stop control could not be sent')

            controlthread.join(timeout=3.0)

            if controlthread.is_alive() or not controlstate.get('cancelled') or controlstate.get('error'):

                raise MediaDecodeError(f"video control lifecycle failed: {controlstate.get('error', '')}")

            if not any(status.get('state') == 'stopped' for status in controlstate['statuses']):

                raise MediaDecodeError('video playback did not report its stopped state')

            result['checks']['video_controls'] = {
                'statuses': len(controlstate['statuses']),
                'frames': len(controlstate['frames']),
                'resize_generation': resizegeneration,
            }

        if audiovideo:

            originalplay = audioapi.play
            avstatuses = []
            avframes = []

            def delayedframe(frame):

                avframes.append(frame)
                time.sleep(0.16)

            try:

                audioapi.play = diagnosticaudio
                started = time.monotonic()
                avplayback = play(
                    audiovideo,
                    statuscallback=avstatuses.append,
                    framecallback=delayedframe,
                    maximumwidth=64,
                    maximumheight=36,
                )
                elapsed = time.monotonic() - started

            finally:

                audioapi.play = originalplay

            if (
                avplayback.get('kind') != 'video'
                or not avframes
                or not avstatuses
                or avstatuses[-1].get('state') != 'complete'
                or avplayback.get('dropped_frames', 0) < 1
                or elapsed > number(avplayback.get('duration'), 0.0) + 0.5
            ):

                raise MediaDecodeError(
                    'audio-master video playback did not discard a slow presentation backlog'
                )

            drift = abs(number(avframes[-1].get('pts'), 0.0) - number(avstatuses[-1].get('position'), 0.0))
            presenteddrift = max(
                (
                    number(status.get('maximum_av_drift_ms'), 0.0)
                    for status in avstatuses
                ),
                default=0.0,
            )
            sourcefps = max(
                1.0,
                number(
                    mediainfo(audiovideo).get('video', {}).get('frame_rate'),
                    25.0,
                ),
            )
            completionlimit = LATELIMIT + (1.0 / sourcefps) + 0.02

            if presenteddrift > (LATELIMIT * 1000.0) + 1.0:

                raise MediaDecodeError(
                    f'presented audio and video drift exceeded the diagnostic limit: '
                    f'{presenteddrift:.3f}ms'
                )

            if drift > completionlimit:

                raise MediaDecodeError(f'audio and video drift exceeded the diagnostic limit: {drift:.3f}s')

            result['checks']['audio_video_sync'] = {
                'drift': round(drift, 4),
                'frames': len(avframes),
                'statuses': len(avstatuses),
                'dropped': avplayback.get('dropped_frames', 0),
                'elapsed': round(elapsed, 4),
                'maximum_presented_drift_ms': round(presenteddrift, 3),
                'completion_tolerance': round(completionlimit, 4),
            }

        result['passed'] = True

    except Exception as error:

        result['errors'].append(str(error))

    finally:

        try:

            if os.path.isdir(root) and not os.path.islink(root):

                shutil.rmtree(root, ignore_errors=True)

        except Exception:

            pass

    return result



## command line
def reportstatus(status):

    print(
        MEDIASTATUSPREFIX + json.dumps(status, sort_keys=True, separators=(',', ':')),
        flush=True,
    )


def reportframe(frame):

    print(
        MEDIAFRAMEPREFIX + json.dumps(frame, sort_keys=True, separators=(',', ':')),
        flush=True,
    )


def usage():

    print('usage: media.py play <media file>')
    print('       media.py probe <media file>')
    print('       media.py video-probe [codec]')
    print('       media.py diagnostic [video files...]')


def playarguments(arguments):

    maximumwidth = MAXWIDTH
    maximumheight = MAXHEIGHT
    pathparts = []
    index = 0

    while index < len(arguments):

        value = str(arguments[index])

        if value == '--maximum-width' and index + 1 < len(arguments):

            maximumwidth = max(2, min(MAXWIDTH, integer(arguments[index + 1], MAXWIDTH)))
            index += 2
            continue

        if value == '--maximum-height' and index + 1 < len(arguments):

            maximumheight = max(2, min(MAXHEIGHT, integer(arguments[index + 1], MAXHEIGHT)))
            index += 2
            continue

        pathparts.append(value)
        index += 1

    return ' '.join(pathparts).strip(), maximumwidth, maximumheight


def main():

    global STOPREQUESTED

    arguments = list(sys.argv[1:])

    if not arguments:

        usage()
        return 2

    command = str(arguments[0]).strip().lower()

    if command == 'diagnostic':

        result = diagnostic(arguments[1:])
        print(json.dumps(result, sort_keys=True, separators=(',', ':')))
        return 0 if result.get('passed') else 1

    if command == 'probe':

        if len(arguments) < 2:

            print('> enter a media file to inspect')
            return 2

        try:

            print(json.dumps(mediainfo(' '.join(arguments[1:])), sort_keys=True, separators=(',', ':')))
            return 0

        except MediaError as error:

            print(f'> {error}')
            return 1

    if command == 'video-probe':

        codec = cleanvalue(arguments[1] if len(arguments) > 1 else 'H264').upper()
        attempts = []
        acceleration = videoacceleration(
            {'codec': codec},
            refresh=True,
            diagnostics=attempts,
        )
        print(json.dumps({
            'format': 1,
            'codec': codec,
            'acceleration': acceleration,
            'attempts': attempts,
            'render_nodes': sorted(glob.glob(os.path.join(DRMNODEROOT, 'renderD*'))),
            'driver_path': LIBVADRIVERPATH,
            'decoder': VIDEODECODERPATH,
        }, sort_keys=True, separators=(',', ':')))
        return 0 if acceleration else 1

    if command != 'play':

        usage()
        return 2

    if len(arguments) < 2:

        print('> enter a media file to play')
        return 2

    path, maximumwidth, maximumheight = playarguments(arguments[1:])

    if not path:

        print('> enter a media file to play')
        return 2

    STOPREQUESTED = False
    signal.signal(signal.SIGTERM, requeststop)
    signal.signal(signal.SIGINT, requeststop)

    try:

        play(
            path,
            statuscallback=reportstatus,
            framecallback=reportframe,
            controls=True,
            maximumwidth=maximumwidth,
            maximumheight=maximumheight,
        )
        return 0

    except MediaCancelled:

        print('> playback stopped')
        return 130

    except MediaError as error:

        print(f'> {error}')
        return 1

    except Exception as error:

        print(f'> media playback failed: {error}')
        return 1


if __name__ == '__main__':

    raise SystemExit(main())
