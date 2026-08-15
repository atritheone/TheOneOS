


"""
audio.py

audio is the non-daemon audio API of The One OS.
"""



## imports
import os
import sys
import time
import json
import re
import base64
import signal
import socket
import struct
import stat
import threading
import subprocess



## protocol
MAGIC = b'T1AU'
PROTO = 1
HEADER_SIZE = 12
MAXMSG = 1024 * 1024

MSGHELLO = 1
MSGPING = 2
MSGCONFIG = 3
MSGDEVLIST = 10
MSGDEVSET = 11
MSGSTREAMOPEN = 20
MSGSTREAMCLOSE = 21
MSGSTREAMWRITE = 22
MSGSTREAMREAD = 23
MSGSTREAMSTATUS = 24
MSGSTREAMCONTROL = 25
MSGVOLUME = 30
MSGMUTE = 31
MSGSUBSCRIBE = 40
MSGNOTIFY = 41
MSGERROR = 250



## audio format
DEFAULTSR = 48000
DEFAULTCH = 2
DEFAULTFMT = 's16le'
DEFAULTFRAMES = 480
FRAMEBYTES = DEFAULTCH * 2
CHUNKFRAMES = 4800
CHUNKBYTES = CHUNKFRAMES * FRAMEBYTES



## paths
AUDIOSOCK = '/.ephemeral/audio/accept.sock'
FFMPEGPATH = '/the one/software/audio/ffmpeg'
MEDIASANDBOXSOURCE = '/the one/catalogue/audio/libt1-media-file-sandbox.so.1'
MEDIASANDBOXPATH = '/.ephemeral/media/t1-media-file-sandbox.so'
PLAYBACKCONTROLDIR = '/.ephemeral/audio'
PLAYBACKSTATUSPREFIX = 'T1OS_AUDIO_STATUS '



## limits
DEFAULTTIMEOUT = 5.0
WRITETIMEOUT = 10.0
DRAINTIMEOUT = 10.0
STDERRLIMIT = 64 * 1024
ARTWORKLIMIT = 16 * 1024 * 1024
ARTSCANLIMIT = 64 * 1024 * 1024
TAGLIMIT = 512



## metadata
TAGALIASES = {
    'album': 'album',
    'album_artist': 'albumartist',
    'albumartist': 'albumartist',
    'artist': 'artist',
    'comment': 'comment',
    'composer': 'composer',
    'copyright': 'copyright',
    'date': 'date',
    'disc': 'disc',
    'disc_number': 'disc',
    'discnumber': 'disc',
    'genre': 'genre',
    'label': 'label',
    'performer': 'artist',
    'publisher': 'label',
    'title': 'title',
    'track': 'track',
    'track_number': 'track',
    'tracknumber': 'track',
    'year': 'date',
}
LOSSLESSCODECS = {
    'alac',
    'ape',
    'flac',
    'mlp',
    'pcm',
    'shorten',
    'tak',
    'truehd',
    'tta',
    'wavpack',
}



## playback state
STOPREQUESTED = False
ACTIVEPROCESS = None
MEDIASANDBOXLOCK = threading.Lock()



## errors
class AudioError(Exception):

    pass


def preparemediasandbox():

    with MEDIASANDBOXLOCK:

        stage = 'read packaged sandbox'
        try:

            with open(MEDIASANDBOXSOURCE, 'rb') as stream:

                payload = stream.read(2 * 1024 * 1024 + 1)

            if (
                not payload.startswith(b'\x7fELF')
                or len(payload) > 2 * 1024 * 1024
            ):

                raise OSError('media sandbox library is not a bounded ELF')

            parent = os.path.dirname(MEDIASANDBOXPATH)
            stage = 'prepare sandbox directory'
            os.makedirs(parent, mode=0o700, exist_ok=True)

            if os.path.islink(parent):

                raise OSError('media sandbox directory is not safe')
            parentstat = os.stat(parent, follow_symlinks=False)
            if (
                not stat.S_ISDIR(parentstat.st_mode)
                or int(parentstat.st_uid) != os.geteuid()
                or int(parentstat.st_gid) != os.getegid()
                or stat.S_IMODE(parentstat.st_mode) != 0o700
            ):
                raise OSError(
                    'media sandbox directory has unsafe ownership or mode '
                    f'{int(parentstat.st_uid)}:{int(parentstat.st_gid)}:'
                    f'{stat.S_IMODE(parentstat.st_mode):04o}'
                )

            try:

                stage = 'validate existing sandbox'
                existingdescriptor = os.open(
                    MEDIASANDBOXPATH,
                    os.O_RDONLY
                    | getattr(os, 'O_NOFOLLOW', 0)
                    | getattr(os, 'O_CLOEXEC', 0),
                )

                with os.fdopen(existingdescriptor, 'rb') as stream:

                    existingstat = os.fstat(stream.fileno())
                    if (
                        stream.read(2 * 1024 * 1024 + 1) == payload
                        and stat.S_ISREG(existingstat.st_mode)
                        and int(existingstat.st_uid) == os.geteuid()
                        and int(existingstat.st_gid) == os.getegid()
                        and stat.S_IMODE(existingstat.st_mode) == 0o500
                    ):
                        return MEDIASANDBOXPATH

            except OSError:

                pass

            temporary = f'{MEDIASANDBOXPATH}.{os.getpid()}.{threading.get_ident()}.new'
            stage = 'create sandbox copy'
            descriptor = os.open(
                temporary,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, 'O_NOFOLLOW', 0)
                | getattr(os, 'O_CLOEXEC', 0),
                0o500,
            )

            try:

                offset = 0

                while offset < len(payload):

                    written = os.write(descriptor, payload[offset:])

                    if written <= 0:

                        raise OSError('short media sandbox library write')

                    offset += written

                stage = 'synchronise sandbox copy'
                os.fsync(descriptor)

            finally:

                os.close(descriptor)

            stage = 'publish sandbox copy'
            os.replace(temporary, MEDIASANDBOXPATH)
            return MEDIASANDBOXPATH

        except Exception as error:

            try:

                if 'temporary' in locals() and os.path.exists(temporary):

                    os.unlink(temporary)

            except Exception:

                pass

            raise AudioUnavailable(
                f'media decoder sandbox is unavailable during {stage}: {error}'
            )


def mediasandboxenvironment(path, environment=None):

    target = os.path.realpath(os.path.abspath(os.path.normpath(str(path))))

    if not os.path.isfile(target) or not os.access(target, os.R_OK):

        raise AudioDecodeError('media file is not readable')

    sandbox = preparemediasandbox()
    result = dict(os.environ if environment is None else environment)
    preload = str(result.get('LD_PRELOAD', '') or '').strip()
    result['LD_PRELOAD'] = sandbox if not preload else f'{sandbox}:{preload}'
    result['T1OS_MEDIA_SANDBOX_INPUT'] = target
    result['T1OS_MEDIA_SANDBOX_REQUIRED'] = '1'
    return result


class AudioUnavailable(AudioError):

    pass


class AudioProtocolError(AudioError):

    pass


class AudioDecodeError(AudioError):

    pass


class AudioCancelled(AudioError):

    pass


class AudioSeek(AudioError):

    def __init__(self, position):

        super().__init__('audio seek requested')
        self.position = float(position)


class AudioPaused(AudioError):

    pass



## packet functions
def packetheader(msgtype, length):

    return struct.pack(
        '>4sBBHI',
        MAGIC,
        PROTO,
        int(msgtype),
        0,
        int(length),
    )


def jsonbytes(payload):

    if payload is None:

        return b''

    try:

        return json.dumps(payload, separators=(',', ':')).encode('utf-8')

    except Exception as e:

        raise AudioProtocolError(f'cannot encode audio message: {e}')


def packrequest(msgtype, payload=None, raw=None):

    if int(msgtype) == MSGSTREAMWRITE:

        jblob = jsonbytes(payload if payload is not None else {})

        body = struct.pack('>I', len(jblob)) + jblob

        if raw:

            body += bytes(raw)

    else:

        body = jsonbytes(payload)

        if raw:

            body += bytes(raw)

    if len(body) > MAXMSG:

        raise AudioProtocolError('audio message is too large')

    return packetheader(msgtype, len(body)) + body


def packresponse(msgtype, payload=None, raw=None):

    body = jsonbytes(payload)

    if raw:

        body += bytes(raw)

    if len(body) > MAXMSG:

        raise AudioProtocolError('audio response is too large')

    return packetheader(msgtype, len(body)) + body


def unpackresponse(buf):

    if len(buf) < HEADER_SIZE:

        return None, None, None, buf

    try:

        magic, proto, msgtype, flags, length = struct.unpack(
            '>4sBBHI',
            buf[:HEADER_SIZE],
        )

    except Exception as e:

        raise AudioProtocolError(f'invalid audio header: {e}')

    if magic != MAGIC:

        raise AudioProtocolError('invalid audio message magic')

    if int(proto) != PROTO:

        raise AudioProtocolError(f'unsupported audio protocol {proto}')

    if int(length) > MAXMSG:

        raise AudioProtocolError('audio response is too large')

    need = HEADER_SIZE + int(length)

    if len(buf) < need:

        return None, None, None, buf

    body = buf[HEADER_SIZE:need]

    rest = buf[need:]

    payload = None

    raw = None

    if body:

        try:

            payload = json.loads(body.decode('utf-8'))

        except Exception:

            raw = body

    return int(msgtype), payload, raw, rest



## client
class AudioClient:

    def __init__(self, path=AUDIOSOCK, timeout=DEFAULTTIMEOUT):

        self.path = str(path)

        self.timeout = float(timeout)

        self.sock = None

        self.inbuf = b''

        self.notifies = []


    def connect(self):

        if self.sock is not None:

            return self

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

        sock.settimeout(self.timeout)

        try:

            sock.connect(self.path)

        except FileNotFoundError:

            sock.close()

            raise AudioUnavailable('audio server is not running')

        except ConnectionRefusedError:

            sock.close()

            raise AudioUnavailable('audio server is unavailable')

        except Exception as e:

            sock.close()

            raise AudioUnavailable(f'cannot connect to audio server: {e}')

        self.sock = sock

        hello = self.request(MSGHELLO, {'client': 'audio', 'protocol': PROTO})

        if not isinstance(hello, dict) or hello.get('server') != 'audioserver':

            self.disconnect()

            raise AudioProtocolError('audio server hello failed')

        return self


    def disconnect(self):

        sock = self.sock

        self.sock = None

        self.inbuf = b''

        if sock is not None:

            try:

                sock.close()

            except Exception:

                pass


    def send(self, msgtype, payload=None, raw=None):

        if self.sock is None:

            raise AudioUnavailable('audio server is not connected')

        packet = packrequest(msgtype, payload, raw)

        try:

            self.sock.sendall(packet)

        except Exception as e:

            self.disconnect()

            raise AudioUnavailable(f'audio server write failed: {e}')


    def receive(self, timeout=None):

        if self.sock is None:

            raise AudioUnavailable('audio server is not connected')

        if timeout is None:

            timeout = self.timeout

        end = time.monotonic() + float(timeout)

        while True:

            msgtype, payload, raw, rest = unpackresponse(self.inbuf)

            if msgtype is not None:

                self.inbuf = rest

                return msgtype, payload, raw

            remain = end - time.monotonic()

            if remain <= 0:

                raise TimeoutError('audio server response timed out')

            try:

                self.sock.settimeout(remain)

                chunk = self.sock.recv(65536)

            except socket.timeout:

                raise TimeoutError('audio server response timed out')

            except Exception as e:

                self.disconnect()

                raise AudioUnavailable(f'audio server read failed: {e}')

            if not chunk:

                self.disconnect()

                raise AudioUnavailable('audio server disconnected')

            self.inbuf += chunk

            if len(self.inbuf) > MAXMSG + HEADER_SIZE:

                self.disconnect()

                raise AudioProtocolError('audio server response buffer is too large')


    def request(self, msgtype, payload=None, raw=None, timeout=None):

        self.send(msgtype, payload, raw)

        if timeout is None:

            timeout = self.timeout

        end = time.monotonic() + float(timeout)

        while True:

            remain = end - time.monotonic()

            if remain <= 0:

                raise TimeoutError('audio server request timed out')

            rtype, response, response_raw = self.receive(remain)

            if rtype == MSGNOTIFY:

                self.notifies.append(response)

                if len(self.notifies) > 100:

                    self.notifies = self.notifies[-100:]

                continue

            if rtype == MSGERROR:

                if isinstance(response, dict):

                    message = response.get('error', response.get('text', 'audio server error'))

                else:

                    message = 'audio server error'

                raise AudioProtocolError(str(message))

            if rtype != int(msgtype):

                continue

            if response is None and response_raw:

                raise AudioProtocolError('invalid audio server response')

            return response


    def devices(self):

        response = self.request(MSGDEVLIST, {})

        if not isinstance(response, dict):

            raise AudioProtocolError('invalid audio device response')

        return response


    def requireoutput(self):

        response = self.devices()

        active = response.get('active')

        devices = response.get('devices', [])

        if not active:

            raise AudioUnavailable('no audio output device is active')

        for device in devices:

            if device.get('id') == active and device.get('ready'):

                return device

        raise AudioUnavailable('the active audio output device is not ready')


    def openstream(
        self,
        samplerate=DEFAULTSR,
        bufferseconds=None,
        prebufferms=None,
        latencyclass=None,
    ):

        request = {
            'samplerate': int(samplerate),
            'channels': DEFAULTCH,
            'format': DEFAULTFMT,
            'write_ack': True,
        }

        if bufferseconds is not None:

            request['buffer_seconds'] = float(bufferseconds)

        if prebufferms is not None:

            request['prebuffer_ms'] = int(prebufferms)

        if latencyclass is not None:

            request['latency_class'] = str(latencyclass)

        response = self.request(MSGSTREAMOPEN, request)

        if not isinstance(response, dict) or not response.get('stream'):

            raise AudioProtocolError('audio stream open failed')

        return int(response['stream']), response


    def writestream(self, streamid, pcmbytes, stopcheck=None):

        data = bytes(pcmbytes)

        if not data or len(data) % FRAMEBYTES:

            raise AudioProtocolError('PCM block is not frame aligned')

        end = time.monotonic() + WRITETIMEOUT

        while True:

            if stopcheck is not None and stopcheck():

                raise AudioCancelled('playback stopped')

            remain = end - time.monotonic()

            if remain <= 0:

                raise AudioUnavailable('audio stream remained full')

            response = self.request(
                MSGSTREAMWRITE,
                {'stream': int(streamid)},
                data,
                timeout=min(self.timeout, remain),
            )

            if not isinstance(response, dict):

                raise AudioProtocolError('invalid audio write response')

            if response.get('ok'):

                accepted = int(response.get('accepted', 0))

                if accepted != len(data):

                    raise AudioProtocolError('audio server accepted a partial PCM block')

                return response

            if int(response.get('accepted', 0)) != 0:

                raise AudioProtocolError('audio server reported an invalid partial write')

            time.sleep(0.01)


    def streamstatus(self, streamid):

        response = self.request(MSGSTREAMSTATUS, {'stream': int(streamid)})

        if not isinstance(response, dict):

            raise AudioProtocolError('invalid audio stream status')

        return response


    def controlstream(self, streamid, paused=None, muted=None):

        payload = {'stream': int(streamid)}

        if paused is not None:
            payload['paused'] = bool(paused)

        if muted is not None:
            payload['muted'] = bool(muted)

        if 'paused' not in payload and 'muted' not in payload:
            raise AudioProtocolError('stream control requires paused or muted state')

        response = self.request(MSGSTREAMCONTROL, payload)

        if not isinstance(response, dict):

            raise AudioProtocolError('invalid audio stream control response')

        return response


    def closestream(self, streamid, drain=True, stopcheck=None):

        response = self.request(MSGSTREAMCLOSE, {
            'stream': int(streamid),
            'drain': bool(drain),
        })

        if not drain:

            return response

        end = time.monotonic() + DRAINTIMEOUT

        while True:

            if stopcheck is not None and stopcheck():

                self.abortstream(streamid)

                raise AudioCancelled('playback stopped')

            status = self.streamstatus(streamid)

            if status.get('state') == 'closed':

                return status

            if time.monotonic() >= end:

                self.abortstream(streamid)

                raise AudioUnavailable('audio stream drain timed out')

            time.sleep(0.01)


    def abortstream(self, streamid):

        try:

            return self.request(MSGSTREAMCLOSE, {
                'stream': int(streamid),
                'drain': False,
            }, timeout=0.5)

        except Exception:

            return None


    def __enter__(self):

        return self.connect()


    def __exit__(self, exc_type, exc, traceback):

        self.disconnect()



## decoder functions
def decodercommand(
    path,
    ffmpegpath=FFMPEGPATH,
    startseconds=0.0,
    samplerate=DEFAULTSR,
    streamindex=None,
):

    command = [
        str(ffmpegpath),
        '-hide_banner',
        '-loglevel', 'error',
        '-nostdin',
    ]

    try:

        startseconds = max(0.0, float(startseconds))

    except Exception:

        startseconds = 0.0

    if startseconds > 0.0:

        command.extend(['-ss', f'{startseconds:.6f}'])

    streammap = '0:a:0'

    try:

        if streamindex is not None and int(streamindex) >= 0:

            streammap = f'0:{int(streamindex)}'

    except Exception:

        streammap = '0:a:0'

    command.extend([
        '-i', str(path),
        '-map', streammap,
        '-vn',
        '-sn',
        '-dn',
        '-ac', str(DEFAULTCH),
        '-ar', str(int(samplerate)),
        '-c:a', 'pcm_s16le',
        '-f', 's16le',
        'pipe:1',
    ])

    return command


def parseduration(text):

    match = re.search(
        r'Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)',
        str(text),
        flags=re.IGNORECASE,
    )

    if not match:

        return 0.0

    hours = int(match.group(1))
    minutes = int(match.group(2))
    seconds = float(match.group(3))

    return max(0.0, (hours * 3600.0) + (minutes * 60.0) + seconds)


def cleanvalue(value):

    try:

        value = str(value).replace('\x00', '').strip()
        value = ' '.join(value.split())
        return value[:TAGLIMIT]

    except Exception:

        return ''


def tagname(name):

    try:

        name = re.sub(r'[^a-z0-9]+', '_', str(name).strip().lower()).strip('_')
        return TAGALIASES.get(name, '')

    except Exception:

        return ''


def codecname(value):

    value = cleanvalue(value)
    base = re.split(r'\s*\(', value, maxsplit=1)[0].strip().lower()
    names = {
        'aac': 'AAC',
        'alac': 'ALAC',
        'flac': 'FLAC',
        'mp3': 'MP3',
        'mp3float': 'MP3',
        'opus': 'Opus',
        'pcm': 'PCM',
        'vorbis': 'Vorbis',
        'wavpack': 'WavPack',
        'wmav1': 'WMA',
        'wmav2': 'WMA',
    }
    name = names.get(base, base.replace('_', ' ').upper())

    if base == 'aac':

        profiles = re.findall(r'\(([^)]+)\)', value)

        for profile in profiles:

            profile = cleanvalue(profile)

            if profile and '/' not in profile and len(profile) <= 16:

                return f'{name} {profile}'

    return name


def parsestream(value, info):

    value = cleanvalue(value)
    parts = [cleanvalue(part) for part in value.split(',') if cleanvalue(part)]

    if not parts:

        return

    info['codec_detail'] = parts[0]
    info['codec'] = codecname(parts[0])
    lowercodec = re.split(r'\s*\(', parts[0], maxsplit=1)[0].strip().lower()
    info['lossless'] = lowercodec in LOSSLESSCODECS or lowercodec.startswith('pcm_')

    ratematch = re.search(r'\b(\d+)\s*Hz\b', value, flags=re.IGNORECASE)

    if ratematch:

        info['sample_rate'] = max(0, int(ratematch.group(1)))

    bitmatch = re.search(r'\((\d+)\s*bit\)', value, flags=re.IGNORECASE)

    if not bitmatch:

        bitmatch = re.search(r'\b[su](8|16|24|32|64)(?:p|le|be)?\b', value, flags=re.IGNORECASE)

    if bitmatch:

        info['bit_depth'] = max(0, int(bitmatch.group(1)))

    ratematch = re.search(r'\b(\d+(?:\.\d+)?)\s*kb/s\b', value, flags=re.IGNORECASE)

    if ratematch:

        info['bit_rate'] = max(0, int(round(float(ratematch.group(1)))))

    for part in parts[1:]:

        lowered = part.lower()

        if re.search(r'\b(?:mono|stereo|\d+(?:\.\d+)(?:\([^)]*\))?|\d+\s+channels?)\b', lowered):

            info['channels'] = part[:64]
            break


def parseinfo(text, path=''):

    text = str(text)
    extension = os.path.splitext(str(path))[1].lower().lstrip('.')
    info = {
        'version': 1,
        'path': str(path),
        'format': extension.upper(),
        'container': '',
        'codec': '',
        'codec_detail': '',
        'duration': parseduration(text),
        'sample_rate': 0,
        'bit_depth': 0,
        'bit_rate': 0,
        'channels': '',
        'lossless': False,
        'file_size': 0,
        'artwork': False,
        'tags': {},
    }
    metadata = False
    streamseen = False

    for line in text.splitlines():

        stripped = line.strip()

        if stripped.startswith('Input #'):

            match = re.match(r'Input #\d+,\s*([^,]+)', stripped, flags=re.IGNORECASE)

            if match:

                info['container'] = cleanvalue(match.group(1)).upper()

            continue

        if stripped.startswith('Duration:'):

            metadata = False
            ratematch = re.search(r'bitrate:\s*(\d+(?:\.\d+)?)\s*kb/s', stripped, flags=re.IGNORECASE)

            if ratematch:

                info['bit_rate'] = max(0, int(round(float(ratematch.group(1)))))

            continue

        if stripped.startswith('Stream #'):

            metadata = False
            streamseen = True

            if 'Audio:' in stripped and not info.get('codec'):

                parsestream(stripped.split('Audio:', 1)[1], info)

            if 'Video:' in stripped and 'attached pic' in stripped.lower():

                info['artwork'] = True

            continue

        if stripped == 'Metadata:' and not streamseen:

            metadata = True
            continue

        if metadata:

            match = re.match(r'\s*([^:]{1,64})\s*:\s*(.*)$', stripped)

            if not match:

                continue

            name = tagname(match.group(1))
            value = cleanvalue(match.group(2))

            if name and value and name not in info['tags']:

                info['tags'][name] = value

    if not info['format']:

        info['format'] = info.get('codec') or info.get('container') or 'AUDIO'

    try:

        if path and os.path.isfile(path):

            info['file_size'] = max(0, int(os.path.getsize(path)))

    except Exception:

        info['file_size'] = 0

    return info


def audioinfo(path, ffmpegpath=FFMPEGPATH):

    target = os.path.realpath(os.path.abspath(os.path.normpath(str(path))))

    if not os.path.isfile(target) or not os.access(target, os.R_OK):

        raise AudioDecodeError('audio file is not readable')

    try:

        completed = subprocess.run(
            [str(ffmpegpath), '-hide_banner', '-nostdin', '-i', target],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10.0,
            check=False,
            env=mediasandboxenvironment(target),
        )

    except FileNotFoundError:

        raise AudioUnavailable('audio decoder is not installed')

    except PermissionError:

        raise AudioUnavailable('audio decoder is not executable')

    except subprocess.TimeoutExpired:

        raise AudioDecodeError('audio metadata inspection timed out')

    except Exception as e:

        raise AudioDecodeError(f'cannot inspect audio metadata: {e}')

    detail = completed.stderr.decode('utf-8', errors='replace')
    info = parseinfo(detail, target)

    if not info.get('codec'):

        raise AudioDecodeError('audio stream information is unavailable')

    return info


def synchsafe(data):

    try:

        if len(data) != 4:

            return 0

        return ((data[0] & 0x7f) << 21) | ((data[1] & 0x7f) << 14) | ((data[2] & 0x7f) << 7) | (data[3] & 0x7f)

    except Exception:

        return 0


def deunsync(data):

    try:

        return bytes(data).replace(b'\xff\x00', b'\xff')

    except Exception:

        return b''


def imageoffset(data):

    signatures = (
        b'\x89PNG\r\n\x1a\n',
        b'\xff\xd8\xff',
        b'GIF87a',
        b'GIF89a',
    )
    offsets = [data.find(signature) for signature in signatures]

    search = 0

    while True:

        offset = data.find(b'RIFF', search)

        if offset < 0:

            break

        if offset + 12 <= len(data) and data[offset + 8:offset + 12] == b'WEBP':

            offsets.append(offset)
            break

        search = offset + 4

    search = 0

    while True:

        offset = data.find(b'BM', search)

        if offset < 0:

            break

        if offset + 14 <= len(data):

            size = int.from_bytes(data[offset + 2:offset + 6], 'little')

            if size >= 14 and offset + size <= len(data):

                offsets.append(offset)
                break

        search = offset + 2

    offsets = [offset for offset in offsets if offset >= 0]
    return min(offsets) if offsets else -1


def trimimage(data):

    if data.startswith(b'\x89PNG\r\n\x1a\n'):

        marker = data.find(b'IEND', 8)

        if marker >= 4 and marker + 8 <= len(data):

            return data[:marker + 8]

    if data.startswith(b'\xff\xd8\xff'):

        marker = data.find(b'\xff\xd9', 3)

        if marker >= 0:

            return data[:marker + 2]

    if data.startswith((b'GIF87a', b'GIF89a')):

        marker = data.rfind(b'\x3b')

        if marker >= 0:

            return data[:marker + 1]

    if data.startswith(b'RIFF') and len(data) >= 12 and data[8:12] == b'WEBP':

        size = 8 + int.from_bytes(data[4:8], 'little')

        if 12 <= size <= len(data):

            return data[:size]

    if data.startswith(b'BM') and len(data) >= 14:

        size = int.from_bytes(data[2:6], 'little')

        if 14 <= size <= len(data):

            return data[:size]

    return data


def validimage(data):

    if not isinstance(data, (bytes, bytearray)) or len(data) < 8 or len(data) > ARTWORKLIMIT:

        return b''

    data = bytes(data)
    offset = imageoffset(data)

    if offset < 0:

        return b''

    return trimimage(data[offset:])


def id3blob(data):

    start = data.find(b'ID3')

    if start < 0 or start + 10 > len(data):

        return b''

    header = data[start:start + 10]
    version = int(header[3])
    size = synchsafe(header[6:10])

    if version not in (2, 3, 4) or size <= 0 or size > ARTSCANLIMIT or start + 10 + size > len(data):

        return b''

    body = data[start + 10:start + 10 + size]

    if header[5] & 0x80:

        body = deunsync(body)

    offset = 0

    if header[5] & 0x40 and version in (3, 4) and len(body) >= 4:

        extended = synchsafe(body[:4]) if version == 4 else int.from_bytes(body[:4], 'big') + 4
        offset = max(0, min(len(body), extended))

    while offset < len(body):

        if version == 2:

            if offset + 6 > len(body):

                break

            name = body[offset:offset + 3]
            length = int.from_bytes(body[offset + 3:offset + 6], 'big')
            headerlength = 6

        else:

            if offset + 10 > len(body):

                break

            name = body[offset:offset + 4]
            lengthdata = body[offset + 4:offset + 8]
            length = synchsafe(lengthdata) if version == 4 else int.from_bytes(lengthdata, 'big')
            headerlength = 10

        if not name.strip(b'\x00') or length <= 0 or length > ARTWORKLIMIT + 4096:

            break

        framestart = offset + headerlength
        frameend = framestart + length

        if frameend > len(body):

            break

        if name in (b'APIC', b'PIC'):

            artwork = validimage(body[framestart:frameend])

            if artwork:

                return artwork

        offset = frameend

    return b''


def id3art(path):

    try:

        with open(path, 'rb') as stream:

            data = stream.read(ARTSCANLIMIT)

        return id3blob(data)

    except Exception:

        return b''


def picturedata(data):

    try:

        offset = 0

        if len(data) < 32:

            return b''

        offset += 4
        mimelength = int.from_bytes(data[offset:offset + 4], 'big')
        offset += 4

        if mimelength < 0 or mimelength > 256 or offset + mimelength + 4 > len(data):

            return b''

        mime = data[offset:offset + mimelength]
        offset += mimelength
        descriptionlength = int.from_bytes(data[offset:offset + 4], 'big')
        offset += 4

        if descriptionlength < 0 or descriptionlength > 65536 or offset + descriptionlength + 20 > len(data):

            return b''

        offset += descriptionlength + 16
        imagelength = int.from_bytes(data[offset:offset + 4], 'big')
        offset += 4

        if mime == b'-->' or imagelength <= 0 or imagelength > ARTWORKLIMIT or offset + imagelength > len(data):

            return b''

        return validimage(data[offset:offset + imagelength])

    except Exception:

        return b''


def flacart(path):

    try:

        with open(path, 'rb') as stream:

            prefix = stream.read(1024 * 1024)
            marker = prefix.find(b'fLaC')

            if marker < 0:

                return b''

            stream.seek(marker + 4)
            scanned = marker + 4

            while scanned < ARTSCANLIMIT:

                header = stream.read(4)

                if len(header) != 4:

                    break

                last = bool(header[0] & 0x80)
                kind = header[0] & 0x7f
                length = int.from_bytes(header[1:4], 'big')
                scanned += 4 + length

                if length < 0 or length > ARTSCANLIMIT or scanned > ARTSCANLIMIT:

                    break

                if kind == 6:

                    artwork = picturedata(stream.read(length))

                    if artwork:

                        return artwork

                else:

                    stream.seek(length, 1)

                if last:

                    break

    except Exception:

        return b''

    return b''


def oggart(path):

    try:

        with open(path, 'rb') as stream:

            data = stream.read(ARTSCANLIMIT)

    except Exception:

        return b''

    alphabet = b'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/='

    for key in (b'METADATA_BLOCK_PICTURE=', b'metadata_block_picture=', b'COVERART=', b'coverart='):

        start = data.find(key)

        if start < 0:

            continue

        start += len(key)
        end = start

        while end < len(data) and data[end] in alphabet and end - start <= ARTWORKLIMIT * 2:

            end += 1

        try:

            decoded = base64.b64decode(data[start:end], validate=True)

        except Exception:

            continue

        artwork = picturedata(decoded) if b'PICTURE' in key.upper() else validimage(decoded)

        if artwork:

            return artwork

    return b''


def covrblob(data):

    search = 0

    while True:

        position = data.find(b'covr', search)

        if position < 0:

            return b''

        if position < 4:

            search = position + 4
            continue

        start = position - 4
        size = int.from_bytes(data[start:position], 'big')

        if size == 1 and start + 16 <= len(data):

            size = int.from_bytes(data[start + 8:start + 16], 'big')

        end = start + size

        if size >= 16 and end <= len(data):

            datamarker = data.find(b'data', position + 4, end)

            while datamarker >= position + 8 and datamarker + 12 <= end:

                datastart = datamarker - 4
                datasize = int.from_bytes(data[datastart:datamarker], 'big')
                dataend = datastart + datasize

                if datasize >= 16 and dataend <= end:

                    artwork = validimage(data[datastart + 16:dataend])

                    if artwork:

                        return artwork

                datamarker = data.find(b'data', datamarker + 4, end)

        search = position + 4


def mp4art(path):

    try:

        size = os.path.getsize(path)
        portion = ARTSCANLIMIT // 2

        with open(path, 'rb') as stream:

            first = stream.read(min(size, portion))
            artwork = covrblob(first)

            if artwork or size <= portion:

                return artwork

            stream.seek(max(0, size - portion))
            return covrblob(stream.read(portion))

    except Exception:

        return b''


def wmaart(path):

    try:

        with open(path, 'rb') as stream:

            data = stream.read(ARTSCANLIMIT)

    except Exception:

        return b''

    key = 'WM/Picture'.encode('utf-16-le')
    search = 0

    while True:

        position = data.find(key, search)

        if position < 0:

            return b''

        start = position + len(key)
        artwork = validimage(data[start:min(len(data), start + ARTWORKLIMIT)])

        if artwork:

            return artwork

        search = start


def embeddedart(path):

    extension = os.path.splitext(str(path))[1].lower()
    readers = []

    if extension == '.flac':

        readers = [flacart, id3art]

    elif extension in ('.ogg', '.opus'):

        readers = [oggart]

    elif extension in ('.m4a', '.mp4'):

        readers = [mp4art]

    elif extension == '.wma':

        readers = [wmaart]

    else:

        readers = [id3art]

    for reader in readers:

        artwork = reader(path)

        if artwork:

            return artwork

    return b''


def extractart(path, output, ffmpegpath=FFMPEGPATH):

    target = os.path.abspath(os.path.normpath(str(path)))
    output = os.path.abspath(os.path.normpath(str(output)))
    ephemeral = os.path.abspath('/.ephemeral')

    if not os.path.isfile(target) or not os.access(target, os.R_OK):

        return False

    try:

        if os.path.commonpath((output, ephemeral)) != ephemeral or output == ephemeral:

            return False

    except Exception:

        return False

    parent = os.path.dirname(output)

    try:

        os.makedirs(parent, mode=0o700, exist_ok=True)

        if os.path.islink(parent) or os.path.commonpath((os.path.realpath(parent), ephemeral)) != ephemeral:

            return False

        if os.path.lexists(output) and os.path.islink(output):

            return False

    except Exception:

        return False

    artwork = embeddedart(target)

    if not artwork:

        return False

    temporary = f'{output}.tmp-{os.getpid()}-{threading.get_ident()}'

    try:

        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)

        with os.fdopen(descriptor, 'wb') as stream:

            stream.write(artwork)
            stream.flush()
            os.fsync(stream.fileno())

        os.replace(temporary, output)
        os.chmod(output, 0o600)
        return True

    except Exception:

        return False

    finally:

        try:

            if os.path.exists(temporary):

                os.unlink(temporary)

        except Exception:

            pass


def audioduration(path, ffmpegpath=FFMPEGPATH):

    target = os.path.realpath(os.path.abspath(os.path.normpath(str(path))))

    try:

        completed = subprocess.run(
            [str(ffmpegpath), '-hide_banner', '-nostdin', '-i', target],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10.0,
            check=False,
            env=mediasandboxenvironment(target),
        )

    except FileNotFoundError:

        raise AudioUnavailable('audio decoder is not installed')

    except PermissionError:

        raise AudioUnavailable('audio decoder is not executable')

    except subprocess.TimeoutExpired:

        raise AudioDecodeError('audio file inspection timed out')

    except Exception as e:

        raise AudioDecodeError(f'cannot inspect audio file: {e}')

    detail = completed.stderr.decode('utf-8', errors='replace')
    duration = parseduration(detail)

    if duration <= 0.0:

        raise AudioDecodeError('audio track duration is unavailable')

    return float(duration)


def pcmblocks(pipe, blockbytes=CHUNKBYTES):

    pending = bytearray()

    while True:

        chunk = pipe.read(65536)

        if not chunk:

            break

        pending.extend(chunk)

        while len(pending) >= int(blockbytes):

            block = bytes(pending[:blockbytes])

            del pending[:blockbytes]

            yield block

    if len(pending) % FRAMEBYTES:

        raise AudioDecodeError('decoder returned an unaligned PCM stream')

    if pending:

        yield bytes(pending)


def stderrreader(pipe, storage, limit=STDERRLIMIT):

    try:

        while True:

            data = pipe.read(4096)

            if not data:

                break

            storage.extend(data)

            if len(storage) > int(limit):

                del storage[:len(storage) - int(limit)]

    except Exception:

        pass


def decodererror(storage):

    if not storage:

        return 'audio file could not be decoded'

    text = bytes(storage).decode('utf-8', errors='replace')

    lines = [line.strip() for line in text.replace('\r', '\n').split('\n') if line.strip()]

    if not lines:

        return 'audio file could not be decoded'

    message = lines[-1]

    if len(message) > 500:

        message = message[:497] + '...'

    return message


def terminateprocess(proc):

    if proc is None or proc.poll() is not None:

        return

    try:

        os.killpg(int(proc.pid), signal.SIGTERM)

    except Exception:

        try:

            proc.terminate()

        except Exception:

            pass

    try:

        proc.wait(timeout=0.5)

    except Exception:

        try:

            os.killpg(int(proc.pid), signal.SIGKILL)

        except Exception:

            try:

                proc.kill()

            except Exception:

                pass


class PlaybackController:

    def __init__(self, pid=None, root=PLAYBACKCONTROLDIR):

        if pid is None:

            pid = os.getpid()

        self.path = os.path.join(str(root), f'playback-{int(pid)}.sock')
        self.sock = None
        self.paused = False
        self.muted = False
        self.stopped = False
        self.seekposition = None
        self.resizesize = None

        os.makedirs(str(root), mode=0o700, exist_ok=True)

        try:

            if os.path.exists(self.path):

                os.unlink(self.path)

        except Exception:

            pass

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)

        try:

            previousmask = os.umask(0o177)
            try:
                sock.bind(self.path)
            finally:
                os.umask(previousmask)
            sock.setblocking(False)

        except Exception:

            sock.close()
            raise

        self.sock = sock


    def poll(self):

        if self.sock is None:

            return

        while True:

            try:

                blob = self.sock.recv(4096)

            except BlockingIOError:

                break

            except InterruptedError:

                continue

            except Exception:

                break

            if not blob or len(blob) > 4096:

                continue

            try:

                message = json.loads(blob.decode('utf-8'))
                command = str(message.get('command', '')).strip().lower()

            except Exception:

                continue

            if command == 'stop':

                self.stopped = True
                continue

            if command == 'pause':

                self.paused = True
                continue

            if command == 'resume':

                self.paused = False
                continue

            if command == 'mute':

                self.muted = bool(message.get('muted', True))
                continue

            if command == 'seek':

                try:

                    position = float(message.get('position'))

                except Exception:

                    continue

                if not (position >= 0.0) or position == float('inf'):

                    continue

                self.seekposition = position

                continue

            if command == 'resize':

                try:

                    width = max(2, int(message.get('width')))
                    height = max(2, int(message.get('height')))

                except Exception:

                    continue

                self.resizesize = [width, height]


    def takeseek(self):

        position = self.seekposition
        self.seekposition = None

        return position


    def takeresize(self):

        size = self.resizesize
        self.resizesize = None

        return size


    def close(self):

        sock = self.sock
        self.sock = None

        if sock is not None:

            try:

                sock.close()

            except Exception:

                pass

        try:

            if os.path.exists(self.path):

                os.unlink(self.path)

        except Exception:

            pass


def sendcontrol(controlpath, command, position=None, width=None, height=None, muted=None):

    try:

        controlpath = str(controlpath or '').strip()
        command = str(command or '').strip().lower()

    except Exception:

        return False

    if not controlpath or command not in ('stop', 'pause', 'resume', 'seek', 'resize', 'mute'):

        return False

    payload = {'command': command}

    if command == 'seek':

        try:

            position = float(position)

        except Exception:

            return False

        if position < 0.0 or position != position or position in (float('inf'), float('-inf')):

            return False

        payload['position'] = position

    if command == 'resize':

        try:

            width = max(2, int(width))
            height = max(2, int(height))

        except Exception:

            return False

        payload['width'] = width
        payload['height'] = height

    if command == 'mute':

        payload['muted'] = bool(muted)

    try:

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)

    except Exception:

        return False

    try:

        sock.sendto(
            json.dumps(payload, separators=(',', ':')).encode('utf-8'),
            controlpath,
        )

        return True

    except Exception:

        return False

    finally:

        try:

            sock.close()

        except Exception:

            pass


def playbackstatus(
    callback,
    state,
    position,
    duration,
    controlpath,
    path,
    streamstatus=None,
):

    if callback is None:

        return

    try:

        payload = {
            'type': 'audio_status',
            'state': str(state),
            'position': max(0.0, float(position)),
            'duration': max(0.0, float(duration)),
            'control': str(controlpath or ''),
            'path': str(path),
        }

        if isinstance(streamstatus, dict):

            payload.update({
                'audio_underruns': max(0, int(streamstatus.get('underruns', 0))),
                'audio_queued_bytes': max(0, int(streamstatus.get('queued', 0))),
                'audio_capacity_bytes': max(0, int(streamstatus.get('capacity', 0))),
            })

        callback(payload)

    except Exception:

        pass


def startdecoder(
    path,
    ffmpegpath,
    startseconds=0.0,
    samplerate=DEFAULTSR,
    streamindex=None,
):

    command = decodercommand(
        path,
        ffmpegpath,
        startseconds=startseconds,
        samplerate=samplerate,
        streamindex=streamindex,
    )

    try:

        return subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
            start_new_session=True,
            env=mediasandboxenvironment(path),
        )

    except FileNotFoundError:

        if not os.path.isfile(ffmpegpath):

            raise AudioUnavailable('audio decoder is not installed')

        raise AudioUnavailable('audio decoder runtime loader is not installed')

    except PermissionError:

        raise AudioUnavailable('audio decoder is not executable')

    except Exception as e:

        raise AudioUnavailable(f'cannot start audio decoder: {e}')



## playback
def stoprequested():

    return bool(STOPREQUESTED)


def requeststop(signum=None, frame=None):

    global STOPREQUESTED

    STOPREQUESTED = True

    proc = ACTIVEPROCESS

    if proc is not None and proc.poll() is None:

        try:

            os.killpg(int(proc.pid), signal.SIGTERM)

        except Exception:

            try:

                proc.terminate()

            except Exception:

                pass


def play(
    path,
    ffmpegpath=FFMPEGPATH,
    socketpath=AUDIOSOCK,
    stopcheck=None,
    statuscallback=None,
    controls=False,
    bufferseconds=None,
    prebufferms=None,
    durationseconds=None,
    streamindex=None,
    startseconds=0.0,
    controlroot=PLAYBACKCONTROLDIR,
):

    global ACTIVEPROCESS

    target = os.path.realpath(os.path.abspath(os.path.normpath(str(path))))

    if not os.path.exists(target):

        raise AudioDecodeError(f'audio file not found: {target}')

    if not os.path.isfile(target):

        raise AudioDecodeError(f'not an audio file: {target}')

    if not os.access(target, os.R_OK):

        raise AudioDecodeError(f'audio file is not readable: {target}')

    if not os.path.isfile(ffmpegpath):

        raise AudioUnavailable('audio decoder is not installed')

    if stopcheck is None:

        stopcheck = stoprequested

    controller = None
    controlpath = ''
    try:

        duration = max(0.0, float(durationseconds or 0.0))

    except Exception:

        duration = 0.0
    client = None
    decodedbytes = 0
    try:

        baseposition = max(0.0, float(startseconds))

    except Exception:

        baseposition = 0.0

    if duration > 0.0:

        baseposition = min(baseposition, max(0.0, duration - 0.05))

    reportedposition = baseposition
    samplerate = DEFAULTSR

    if controls:

        try:

            controller = PlaybackController(root=controlroot)
            controlpath = controller.path

        except Exception as e:

            raise AudioUnavailable(f'cannot create audio playback controls: {e}')

    try:

        if duration <= 0.0:

            duration = audioduration(target, ffmpegpath)

    except AudioError:

        duration = 0.0

    playbackstatus(
        statuscallback,
        'loading',
        baseposition,
        duration,
        controlpath,
        target,
    )

    try:

        client = AudioClient(socketpath).connect()
        device = client.requireoutput()
        outputformat = device.get('format', {}) if isinstance(device, dict) else {}

        try:

            samplerate = int(outputformat.get('samplerate', DEFAULTSR))

        except Exception:

            samplerate = DEFAULTSR

        if samplerate <= 0:

            samplerate = DEFAULTSR

        while True:

            streamid = None
            proc = None
            errbuf = bytearray()
            errthread = None
            generationbytes = 0
            serverpaused = False
            servermuted = False
            lastreport = 0.0
            lastposition = float(baseposition)

            def emit(state, status=None, force=False):

                nonlocal lastreport, lastposition, reportedposition

                now = time.monotonic()

                if not force and (now - lastreport) < 0.20:

                    return

                if status is None and streamid is not None:

                    try:

                        status = client.streamstatus(streamid)

                    except Exception:

                        status = None

                if isinstance(status, dict):

                    playedbytes = int(status.get('presented_bytes', status.get('output_bytes', 0)))
                    statusrate = int(status.get('samplerate', samplerate) or samplerate)
                    lastposition = float(baseposition) + (
                        float(playedbytes) / float(statusrate * FRAMEBYTES)
                    )

                if duration > 0.0 and lastposition > duration:

                    lastposition = duration

                reportedposition = lastposition

                playbackstatus(
                    statuscallback,
                    state,
                    lastposition,
                    duration,
                    controlpath,
                    target,
                    streamstatus=status,
                )
                lastreport = now

            def servicecontrol(fromwrite=False):

                nonlocal serverpaused, servermuted

                if controller is not None:

                    controller.poll()

                    if controller.stopped:

                        raise AudioCancelled('playback stopped')

                    seekposition = controller.takeseek()

                    if seekposition is not None:

                        raise AudioSeek(seekposition)

                    if bool(controller.paused) != bool(serverpaused):

                        status = client.controlstream(streamid, controller.paused)
                        serverpaused = bool(controller.paused)
                        emit('paused' if serverpaused else 'playing', status=status, force=True)

                    if bool(controller.muted) != bool(servermuted):

                        status = client.controlstream(streamid, muted=controller.muted)
                        servermuted = bool(controller.muted)
                        emit('paused' if serverpaused else 'playing', status=status, force=True)

                    if serverpaused and fromwrite:

                        raise AudioPaused('playback paused')

                if stopcheck():

                    raise AudioCancelled('playback stopped')

                return False

            try:

                streamid, streaminfo = client.openstream(
                    samplerate=samplerate,
                    bufferseconds=bufferseconds,
                    prebufferms=prebufferms,
                )
                proc = startdecoder(
                    target,
                    ffmpegpath,
                    startseconds=baseposition,
                    samplerate=samplerate,
                    streamindex=streamindex,
                )
                ACTIVEPROCESS = proc
                errthread = threading.Thread(
                    target=stderrreader,
                    args=(proc.stderr, errbuf),
                    daemon=True,
                )
                errthread.start()
                blocks = iter(pcmblocks(proc.stdout))
                emit('playing', force=True)

                while True:

                    try:

                        servicecontrol(fromwrite=False)

                        if serverpaused:

                            emit('paused')
                            time.sleep(0.02)
                            continue

                        block = next(blocks)
                        client.writestream(
                            streamid,
                            block,
                            stopcheck=lambda: servicecontrol(fromwrite=True),
                        )
                        generationbytes += len(block)
                        decodedbytes += len(block)
                        emit('playing')

                    except StopIteration:

                        break

                    except AudioPaused:

                        continue

                try:

                    code = proc.wait(timeout=2.0)

                except subprocess.TimeoutExpired:

                    terminateprocess(proc)
                    raise AudioDecodeError('audio decoder did not exit')

                if errthread is not None:

                    errthread.join(timeout=0.5)

                servicecontrol(fromwrite=False)

                if int(code) != 0:

                    raise AudioDecodeError(decodererror(errbuf))

                if generationbytes <= 0:

                    raise AudioDecodeError('file contains no decodable audio stream')

                status = client.request(MSGSTREAMCLOSE, {
                    'stream': int(streamid),
                    'drain': True,
                })
                emit('draining', status=status, force=True)
                drainremaining = float(DRAINTIMEOUT)
                drainlast = time.monotonic()

                while not isinstance(status, dict) or status.get('state') != 'closed':

                    servicecontrol(fromwrite=False)
                    now = time.monotonic()

                    if not serverpaused:

                        drainremaining -= max(0.0, now - drainlast)

                    drainlast = now

                    if drainremaining <= 0.0:

                        client.abortstream(streamid)
                        raise AudioUnavailable('audio stream drain timed out')

                    time.sleep(0.01)
                    status = client.streamstatus(streamid)
                    emit('paused' if serverpaused else 'draining', status=status)

                emit('complete', status=status, force=True)
                streamid = None

                return {
                    'path': target,
                    'decoded_bytes': int(decodedbytes),
                    'duration': float(duration),
                    'samplerate': samplerate,
                    'channels': DEFAULTCH,
                    'format': DEFAULTFMT,
                }

            except AudioSeek as seek:

                requested = max(0.0, float(seek.position))

                if duration > 0.0:

                    requested = min(requested, max(0.0, duration - 0.05))

                baseposition = requested
                playbackstatus(
                    statuscallback,
                    'seeking',
                    baseposition,
                    duration,
                    controlpath,
                    target,
                )

            finally:

                terminateprocess(proc)
                ACTIVEPROCESS = None

                if errthread is not None and errthread.is_alive():

                    errthread.join(timeout=0.2)

                if streamid is not None:

                    client.abortstream(streamid)

    except AudioCancelled:

        playbackstatus(
            statuscallback,
            'stopped',
            reportedposition,
            duration,
            controlpath,
            target,
        )
        raise

    except AudioError:

        if stopcheck():

            raise AudioCancelled('playback stopped')

        raise

    finally:

        ACTIVEPROCESS = None

        if client is not None:

            client.disconnect()

        if controller is not None:

            controller.close()



## diagnostics
def diagnostic(ffmpegpath=FFMPEGPATH, audiopaths=None):

    result = {
        'format': 1,
        'passed': False,
        'ffmpeg': str(ffmpegpath),
        'checks': {},
        'errors': [],
    }
    artoutputs = []
    artinputs = []
    artroot = f'/.ephemeral/audio-diagnostic-{os.getpid()}'

    try:

        blob = packrequest(MSGSTREAMWRITE, {'stream': 7}, b'\x00\x00\x00\x00')

        if blob[:4] != MAGIC or len(blob) <= HEADER_SIZE:

            raise AudioProtocolError('request framing failed')

        result['checks']['request_framing'] = True

        response = packresponse(MSGSTREAMSTATUS, {'stream': 7, 'state': 'closed'})

        msgtype, payload, raw, rest = unpackresponse(response)

        if msgtype != MSGSTREAMSTATUS or payload.get('state') != 'closed' or raw is not None or rest:

            raise AudioProtocolError('response framing failed')

        result['checks']['response_framing'] = True

        response = packresponse(MSGSTREAMCONTROL, {
            'stream': 7,
            'state': 'paused',
            'paused': True,
            'muted': True,
        })
        msgtype, payload, raw, rest = unpackresponse(response)

        if (
            msgtype != MSGSTREAMCONTROL
            or not payload.get('paused')
            or not payload.get('muted')
            or raw is not None
            or rest
        ):

            raise AudioProtocolError('stream control framing failed')

        result['checks']['stream_control_framing'] = True

        duration = parseduration('Duration: 01:02:03.50, start: 0.000000')

        if abs(duration - 3723.5) > 0.0001:

            raise AudioDecodeError('audio duration parser failed')

        result['checks']['duration_parser'] = True

        detail = '''Input #0, flac, from '/master/music/diagnostic.flac':
  Metadata:
    title           : Signal Fires
    artist          : The Diagnostics
    album           : Native Audio
    album_artist    : T1OS Ensemble
    composer        : Ada Signal
    genre           : Electronic
    date            : 2026
    track           : 3/12
    disc            : 1/2
  Duration: 00:04:05.25, start: 0.000000, bitrate: 2304 kb/s
  Stream #0:0: Audio: flac, 96000 Hz, stereo, s32 (24 bit), 2304 kb/s
  Stream #0:1: Video: png, rgba, 800x800 (attached pic)'''
        info = parseinfo(detail, '/master/music/diagnostic.flac')

        if (
            info.get('codec') != 'FLAC'
            or info.get('sample_rate') != 96000
            or info.get('bit_depth') != 24
            or info.get('channels') != 'stereo'
            or info.get('bit_rate') != 2304
            or not info.get('lossless')
            or not info.get('artwork')
            or info.get('tags', {}).get('title') != 'Signal Fires'
            or info.get('tags', {}).get('albumartist') != 'T1OS Ensemble'
            or info.get('tags', {}).get('track') != '3/12'
        ):

            raise AudioDecodeError(f'audio metadata parser failed: {info}')

        result['checks']['metadata_parser'] = True
        sampleimage = b'\x89PNG\r\n\x1a\nT1OSART'
        mime = b'image/png'
        picture = struct.pack('>I', 3)
        picture += struct.pack('>I', len(mime)) + mime
        picture += struct.pack('>I', 0)
        picture += struct.pack('>IIII', 2, 2, 8, 0)
        picture += struct.pack('>I', len(sampleimage)) + sampleimage
        pictureframe = b'\x00image/png\x00\x03\x00' + sampleimage
        frame = b'APIC' + struct.pack('>I', len(pictureframe)) + b'\x00\x00' + pictureframe
        framesize = len(frame)
        sizebytes = bytes(((framesize >> 21) & 0x7f, (framesize >> 14) & 0x7f, (framesize >> 7) & 0x7f, framesize & 0x7f))
        id3 = b'ID3\x03\x00\x00' + sizebytes + frame
        dataatom = struct.pack('>I', 16 + len(sampleimage)) + b'data' + struct.pack('>II', 14, 0) + sampleimage
        covratom = struct.pack('>I', 8 + len(dataatom)) + b'covr' + dataatom
        os.makedirs(artroot, mode=0o700, exist_ok=True)
        flacpath = os.path.join(artroot, 'picture.flac')
        oggpath = os.path.join(artroot, 'picture.ogg')
        wmapath = os.path.join(artroot, 'picture.wma')

        with open(flacpath, 'wb') as stream:

            stream.write(b'fLaC' + bytes((0x86,)) + len(picture).to_bytes(3, 'big') + picture)

        with open(oggpath, 'wb') as stream:

            stream.write(b'OggS\x00METADATA_BLOCK_PICTURE=' + base64.b64encode(picture) + b'\x00')

        with open(wmapath, 'wb') as stream:

            stream.write(b'T1OSASF' + 'WM/Picture'.encode('utf-16-le') + b'\x00' * 12 + sampleimage)

        artinputs.extend((flacpath, oggpath, wmapath))

        if (
            id3blob(id3) != sampleimage
            or flacart(flacpath) != sampleimage
            or oggart(oggpath) != sampleimage
            or covrblob(covratom) != sampleimage
            or wmaart(wmapath) != sampleimage
        ):

            raise AudioDecodeError('embedded artwork container parser failed')

        result['checks']['artwork_parsers'] = ['ID3', 'FLAC', 'Vorbis', 'MP4', 'ASF']

        if not os.path.isfile(ffmpegpath):

            raise AudioUnavailable('audio decoder is not installed')

        completed = subprocess.run(
            [str(ffmpegpath), '-hide_banner', '-version'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5.0,
            check=False,
        )

        if completed.returncode != 0:

            raise AudioUnavailable('audio decoder version check failed')

        versionline = completed.stdout.decode('utf-8', errors='replace').splitlines()[0]

        result['checks']['decoder'] = versionline

        decoded = {}
        durations = {}
        seekdecoded = {}
        metadata = {}
        artworks = {}

        for audiopath in list(audiopaths or []):

            target = os.path.abspath(os.path.normpath(str(audiopath)))

            if not os.path.isfile(target):

                raise AudioDecodeError(f'audio fixture not found: {target}')

            duration = audioduration(target, ffmpegpath)
            durations[target] = duration
            info = audioinfo(target, ffmpegpath)
            metadata[target] = info

            os.makedirs(artroot, mode=0o700, exist_ok=True)
            artpath = os.path.join(artroot, f'art-{len(artoutputs) + 1}.image')
            extracted = extractart(target, artpath, ffmpegpath)

            if info.get('artwork') and not extracted:

                raise AudioDecodeError(f'embedded artwork extraction failed: {target}')

            if extracted:

                if not os.path.isfile(artpath) or os.path.getsize(artpath) < 8:

                    raise AudioDecodeError(f'embedded artwork output is invalid: {target}')

                artoutputs.append(artpath)
                artworks[target] = os.path.getsize(artpath)
                info['artwork'] = True

            completed = subprocess.run(
                decodercommand(target, ffmpegpath),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=10.0,
                check=False,
                env=mediasandboxenvironment(target),
            )

            if completed.returncode != 0:

                detail = completed.stderr.decode('utf-8', errors='replace').strip()

                raise AudioDecodeError(detail or f'audio fixture did not decode: {target}')

            if not completed.stdout or len(completed.stdout) % FRAMEBYTES:

                raise AudioDecodeError(f'audio fixture produced invalid PCM: {target}')

            decoded[target] = len(completed.stdout)

            completed = subprocess.run(
                decodercommand(
                    target,
                    ffmpegpath,
                    startseconds=max(0.0, duration / 2.0),
                ),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=10.0,
                check=False,
                env=mediasandboxenvironment(target),
            )

            if completed.returncode != 0 or not completed.stdout:

                detail = completed.stderr.decode('utf-8', errors='replace').strip()
                raise AudioDecodeError(detail or f'audio fixture seek failed: {target}')

            if len(completed.stdout) >= decoded[target] or len(completed.stdout) % FRAMEBYTES:

                raise AudioDecodeError(f'audio fixture seek produced invalid PCM: {target}')

            seekdecoded[target] = len(completed.stdout)

        result['checks']['decoded'] = decoded
        result['checks']['durations'] = durations
        result['checks']['seek_decoded'] = seekdecoded
        result['checks']['metadata'] = metadata
        result['checks']['artworks'] = artworks

        result['passed'] = True

    except Exception as e:

        result['errors'].append(str(e))

    finally:

        for artpath in artoutputs + artinputs:

            try:

                if os.path.isfile(artpath):

                    os.unlink(artpath)

            except Exception:

                pass

        try:

            if os.path.isdir(artroot) and not os.path.islink(artroot):

                os.rmdir(artroot)

        except Exception:

            pass

    return result



## command line
def usage():

    print('usage: audio.py play <audio file>')

    print('       audio.py diagnostic [audio files...]')


def main():

    global STOPREQUESTED

    args = list(sys.argv[1:])

    if not args:

        usage()

        return 2

    command = str(args[0]).strip().lower()

    if command == 'diagnostic':

        result = diagnostic(audiopaths=args[1:])

        print(json.dumps(result, sort_keys=True, separators=(',', ':')))

        return 0 if result.get('passed') else 1

    if command != 'play':

        usage()

        return 2

    if len(args) < 2:

        print('> enter an audio file to play')

        return 2

    path = ' '.join(args[1:])

    STOPREQUESTED = False

    signal.signal(signal.SIGTERM, requeststop)

    signal.signal(signal.SIGINT, requeststop)

    try:

        def report(status):

            print(
                PLAYBACKSTATUSPREFIX + json.dumps(
                    status,
                    sort_keys=True,
                    separators=(',', ':'),
                ),
                flush=True,
            )

        play(path, statuscallback=report, controls=True)

        return 0

    except AudioCancelled:

        print('> playback stopped')

        return 130

    except AudioError as e:

        print(f'> {e}')

        return 1

    except Exception as e:

        print(f'> audio playback failed: {e}')

        return 1



if __name__ == '__main__':

    raise SystemExit(main())
