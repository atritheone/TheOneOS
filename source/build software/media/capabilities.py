


"""
capabilities.py

capabilities exposes the canonical local-media playback contract.
"""



## imports
import json
import os



## paths
CAPABILITYPATH = '/the one/settings/media/playback capabilities.json'



## fallback contract
# The installed JSON file is authoritative.  The fallback keeps diagnostics
# and recovery media usable while the settings tier is being restored.
FALLBACK = {
    'format': 1,
    'policy': 't1os-modern-local-media-v1',
    'video_extensions': [
        '.3g2', '.3gp', '.264', '.265', '.266', '.asf', '.avc', '.avi',
        '.divx', '.dv', '.f4v', '.flv', '.gxf', '.h264', '.h265', '.h266',
        '.hevc', '.ivf', '.m1v', '.m2t', '.m2ts', '.m2v', '.m4v',
        '.mjpeg', '.mjpg', '.mkv', '.mov', '.mp4', '.mpeg', '.mpg', '.mpv',
        '.mts', '.mxf', '.nut', '.ogm', '.ogv', '.rm', '.rmvb', '.ts',
        '.vob', '.vvc', '.webm', '.wmv', '.y4m',
    ],
    'audio_extensions': [
        '.aac', '.ac3', '.aiff', '.alac', '.ape', '.dts', '.eac3', '.flac',
        '.m4a', '.mka', '.mp2', '.mp3', '.oga', '.ogg', '.opus', '.tak',
        '.tta', '.wav', '.wma', '.wv',
    ],
}



def _normaliseextensions(values):

    result = set()

    for value in values if isinstance(values, (list, tuple, set)) else ():

        extension = str(value or '').strip().lower()

        if extension and not extension.startswith('.'):

            extension = f'.{extension}'

        if extension and extension != '.' and '/' not in extension and '\\' not in extension:

            result.add(extension)

    return tuple(sorted(result))


def load(path=CAPABILITYPATH):

    contract = dict(FALLBACK)

    try:

        with open(path, 'r', encoding='utf-8') as stream:

            loaded = json.load(stream)

        if not isinstance(loaded, dict) or int(loaded.get('format', 0)) != 1:

            raise ValueError('media playback capability format is not supported')

        contract.update(loaded)

    except Exception:

        pass

    contract['video_extensions'] = _normaliseextensions(contract.get('video_extensions'))
    contract['audio_extensions'] = _normaliseextensions(contract.get('audio_extensions'))
    return contract


CONTRACT = load()
VIDEO_EXTENSIONS = tuple(CONTRACT.get('video_extensions', ()))
AUDIO_EXTENSIONS = tuple(CONTRACT.get('audio_extensions', ()))


def extensionkind(path):

    extension = os.path.splitext(str(path or ''))[1].lower()

    if extension in VIDEO_EXTENSIONS:

        return 'video'

    if extension in AUDIO_EXTENSIONS:

        return 'audio'

    return 'unknown'


def ismediacandidate(path):

    return extensionkind(path) != 'unknown'


def required(name):

    values = CONTRACT.get(str(name), ())
    return tuple(sorted({str(value).strip() for value in values if str(value).strip()}))

