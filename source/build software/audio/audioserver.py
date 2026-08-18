#!"/the one/software/python/bin/python" -B

"""
audioserver.py

audioserver is the audio server daemon of The One OS.
"""



## imports
import os
import sys
import time
import json
import stat
import errno
import fcntl
import ctypes
import struct
import signal
import socket
import select
import selectors

# build path
sys.path.insert(0, '/the one/build')

# AudioServer is executed directly from this directory, so ``audio`` is the
# sibling API module rather than a package.  Pin the search path and validate
# the resolved file to prevent an unrelated namespace package or site module
# from shadowing the root-owned build object.
_AUDIODIR = os.path.dirname(os.path.realpath(__file__))
if _AUDIODIR not in sys.path:
    sys.path.insert(0, _AUDIODIR)
import audio as audioapi
if os.path.realpath(getattr(audioapi, '__file__', '')) != os.path.join(
        _AUDIODIR, 'audio.py'):
    raise ImportError('AudioServer resolved an unexpected audio API module')

MAGIC = audioapi.MAGIC
PROTO = audioapi.PROTO
HEADER_SIZE = audioapi.HEADER_SIZE
MAXMSG = audioapi.MAXMSG
MSGHELLO = audioapi.MSGHELLO
MSGPING = audioapi.MSGPING
MSGCONFIG = audioapi.MSGCONFIG
MSGDEVLIST = audioapi.MSGDEVLIST
MSGDEVSET = audioapi.MSGDEVSET
MSGSTREAMOPEN = audioapi.MSGSTREAMOPEN
MSGSTREAMCLOSE = audioapi.MSGSTREAMCLOSE
MSGSTREAMWRITE = audioapi.MSGSTREAMWRITE
MSGSTREAMREAD = audioapi.MSGSTREAMREAD
MSGSTREAMSTATUS = audioapi.MSGSTREAMSTATUS
MSGSTREAMCONTROL = audioapi.MSGSTREAMCONTROL
MSGVOLUME = audioapi.MSGVOLUME
MSGMUTE = audioapi.MSGMUTE
MSGSUBSCRIBE = audioapi.MSGSUBSCRIBE
MSGNOTIFY = audioapi.MSGNOTIFY
MSGERROR = audioapi.MSGERROR
DEFAULTSR = audioapi.DEFAULTSR
DEFAULTCH = audioapi.DEFAULTCH
DEFAULTFMT = audioapi.DEFAULTFMT
DEFAULTFRAMES = audioapi.DEFAULTFRAMES
FRAMEBYTES = audioapi.FRAMEBYTES
packresponse = audioapi.packresponse

# Live browser audio is already paced by Chromium and carries its own media
# clock.  A quarter-second minimum ring made that audio permanently trail the
# corresponding video because the private ALSA bridge cannot report this
# downstream queue to Chromium.  Two 20 ms PCM blocks retain bounded scheduler
# tolerance without turning the relay into a hidden playback buffer.
INTERACTIVESTREAMMINBUFFERSECONDS = 0.04

# t1os modules
from reign.reign import timestamp
from GODDESS.GODDESS import formatlog
from exchange.exchange import exset, exget



## globals

# misc
RUNNING = True
DEBUGAUDIOSERVER = False
AUDIOTELEMETRYINTERVAL = 30.0

# paths
NODESPATH = '/the one/drivers/nodes'
ASOUNDPROCPATH = '/the one/drivers/processes/asound'
SOUNDSTATEPATH = '/the one/drivers/state/class/sound'
DMIROOT = '/the one/drivers/state/class/dmi/id'
AUDIOROOT = '/the one/settings/audio'
AUDIOCONF = '/the one/settings/audio/audioserver.json'
AUDIOEPHEM = '/.ephemeral/audio'
AUDIOSOCK = '/.ephemeral/audio/accept.sock'
AUDIOLOG = '/the one/logs/audioserver.py.log'

# sockets
SEL = selectors.DefaultSelector()
SERVERSOCK = None
CLIENTS = {}

# audio engine
MIXFRAMES = DEFAULTFRAMES
MIXHZ = 100
# Master gain is a normalized PCM multiplier. Hardware playback gain is kept
# fixed while the software mixer remains the single live volume authority.
REFERENCEANALOGCODEC = '10ec0897'

# devices
DEVICES = []
ACTIVEDEV = None
BACKEND = None
ALSACARDINFO = {}

# streams
STREAMS = {}
STREAMNEXT = 1
CLOSEDSTREAMS = {}
CLOSEDSTREAMTTL = 5.0
CLOSEDSTREAMLIMIT = 256
MASTERGAIN = 1.0
MASTERMUTE = False
MASTERAPPLIEDGAIN = None
MASTERCONFIGDIRTY = False
MASTERCONFIGDUE = 0.0
MASTERCONFIGDELAY = 0.75
MASTERGAINRAMPMS = 10.0

# timing
LASTMIX = 0.0
XRUNS = 0
STATS = {}
MIXEDFRAMES = 0
BACKENDPRESENTEDFRAMES = 0
UNDERRUNS = 0
BACKENDWRITES = 0
BACKENDBYTES = 0
BACKENDERRS = 0
LASTSTATLOG = 0.0
LASTMIXLEVELLOG = 0.0
LASTBACKENDWRITELOG = 0.0
MAXMIXCATCHUP = 16
AUDIOPROCESSNICE = -10



## functions

# debug functions
def tickstats():

    STATS['time'] = timestamp()

    STATS['clients'] = len(CLIENTS)

    STATS['streams'] = len(STREAMS)

    STATS['xruns'] = XRUNS

    STATS['backendwrites'] = BACKENDWRITES

    STATS['backendbytes'] = BACKENDBYTES

    STATS['backenderrors'] = BACKENDERRS

    STATS['backendrecoveries'] = int(BACKEND.get('recoveries', 0)) if BACKEND else 0


def getstats():

    tickstats()

    return dict(STATS)


def log(line):

    if not DEBUGAUDIOSERVER:

        return

    msg = formatlog('audio server', line)

    try:

        with open(AUDIOLOG, 'a', buffering=1) as f:

            f.write(msg + '\n')

            f.flush()

    except Exception:

        pass


def prioritiseaudio():

    try:

        if hasattr(os, 'setpriority') and hasattr(os, 'PRIO_PROCESS'):

            os.setpriority(os.PRIO_PROCESS, 0, AUDIOPROCESSNICE)
            STATS['process_nice'] = int(os.getpriority(os.PRIO_PROCESS, 0))
            return True

    except Exception:

        pass

    try:

        current = int(os.nice(0))

        if current > AUDIOPROCESSNICE:

            os.nice(AUDIOPROCESSNICE - current)

        STATS['process_nice'] = int(os.nice(0))
        return STATS['process_nice'] <= current

    except Exception:

        STATS['process_nice'] = None
        return False


def error(code, text):

    msg = f'error {code}: {text}'

    log(msg)

    return {'error': code, 'text': text}


def warn(text):

    msg = f'warn: {text}'

    log(msg)


def pcmstats(pcmbytes, maxsamples=2048):

    if not pcmbytes:

        return 0, 0.0

    nbytes = len(pcmbytes)

    nsamp = nbytes // 2

    if nsamp <= 0:

        return 0, 0.0

    if nsamp > int(maxsamples):

        nsamp = int(maxsamples)

    maxv = 0

    acc = 0

    i = 0

    while i < nsamp:

        s = struct.unpack_from('<h', pcmbytes, i * 2)[0]

        a = s if s >= 0 else -s

        if a > maxv:

            maxv = a

        acc += int(s) * int(s)

        i += 1

    rms = (acc / float(nsamp)) ** 0.5

    return int(maxv), float(rms)


def mixleveltrace(pcmbytes):

    global LASTMIXLEVELLOG

    nowt = time.monotonic()

    if (nowt - float(LASTMIXLEVELLOG)) < AUDIOTELEMETRYINTERVAL:
        return

    LASTMIXLEVELLOG = nowt
    peak, rms = pcmstats(pcmbytes, maxsamples=2048)
    log(
        f'mix output max={peak} rms={rms:.1f} '
        f'mastergain={float(MASTERGAIN):.3f} mastermute={bool(MASTERMUTE)}'
    )


# boot functions
def setup():

    ensurepaths()

    cfg = loadconfig()

    applyconfig(cfg)

    scan()

    # A specifically configured device is a manual preference and must be
    # restored even when automatic selection is disabled.  Automatic mode is
    # only the fallback used when no preferred device is ready.
    devid = cfg.get('device')
    selected = bool(devid and devset(devid))

    if not selected and cfg.get('autodevice'):

        devid = pickautodevice()

        if devid:

            devset(devid)

    listen()

    installsignals()


def loadconfig():

    if not os.path.exists(AUDIOCONF):

        cfg = defaultconfig()

        saveconfig(cfg)

        return cfg

    try:

        with open(AUDIOCONF, 'r') as f:

            cfg = mergeconfig(defaultconfig(), json.load(f))

    except Exception:

        cfg = defaultconfig()

    return cfg


def saveconfig(cfg):

    tmp = str(AUDIOCONF) + ".tmp"

    try:

        with open(tmp, 'w') as f:

            json.dump(cfg, f, indent=4)

            f.flush()

            os.fsync(f.fileno())

        os.replace(tmp, AUDIOCONF)

        dfd = os.open(AUDIOROOT, os.O_DIRECTORY)

        os.fsync(dfd)

        os.close(dfd)

    except Exception:

        try:

            if os.path.exists(tmp):
                os.unlink(tmp)

        except Exception:

            pass


def masterconfigschedule():

    globals()['MASTERCONFIGDIRTY'] = True
    globals()['MASTERCONFIGDUE'] = time.monotonic() + float(MASTERCONFIGDELAY)


def masterconfigflush(force=False):

    if not MASTERCONFIGDIRTY:
        return False

    if not force and time.monotonic() < float(MASTERCONFIGDUE):
        return False

    cfg = getconfig()
    cfg['mastergain'] = float(MASTERGAIN)
    cfg['mastermute'] = bool(MASTERMUTE)
    saveconfig(cfg)
    globals()['MASTERCONFIGDIRTY'] = False
    globals()['MASTERCONFIGDUE'] = 0.0
    return True


def ensurepaths():

    try:

        os.makedirs(AUDIOROOT, exist_ok=True)

    except Exception:

        pass

    os.makedirs(AUDIOEPHEM, exist_ok=True)
    ephemeralstat = os.stat(AUDIOEPHEM, follow_symlinks=False)
    if (
        not stat.S_ISDIR(ephemeralstat.st_mode)
        or int(ephemeralstat.st_uid) != 0
        or int(ephemeralstat.st_gid) != 1000
        or stat.S_IMODE(ephemeralstat.st_mode) != 0o2710
    ):
        raise PermissionError('unsafe audio service runtime directory')


def installsignals():

    signal.signal(signal.SIGINT, shutdown)

    signal.signal(signal.SIGTERM, shutdown)


def shutdown(signum=None, frame=None):

    global RUNNING

    RUNNING = False

    # persist current master state on shutdown (windows-like)
    cfg = getconfig()

    cfg['mastergain'] = float(MASTERGAIN)

    cfg['mastermute'] = bool(MASTERMUTE)

    saveconfig(cfg)

    for fd in list(CLIENTS.keys()):

        drop(fd)

    try:

        backendclose()

    except Exception:

        pass

    try:

        if SERVERSOCK:
            SERVERSOCK.close()

    except Exception:

        pass

    try:

        if os.path.exists(AUDIOSOCK):

            os.unlink(AUDIOSOCK)

    except Exception:

        pass


def runloop():

    while RUNNING:

        mixloop()

        masterconfigflush()

        pollevents(mixwait(0.02))


def pollevents(timeout):

    events = SEL.select(timeout)

    for key, mask in events:

        sock = key.fileobj

        if sock == SERVERSOCK:

            accept(sock)

            continue

        if mask & selectors.EVENT_READ:

            readclient(sock)

        if mask & selectors.EVENT_WRITE:

            writeclient(sock)


# config functions
def defaultconfig():

    cfg = {}

    cfg['samplerate'] = DEFAULTSR

    cfg['channels'] = DEFAULTCH

    cfg['format'] = DEFAULTFMT

    cfg['frames'] = DEFAULTFRAMES

    cfg['mastergain'] = 0.20

    cfg['mastermute'] = False

    cfg['autodevice'] = True

    cfg['device'] = None

    cfg['preferredcodec'] = None

    cfg['maxstreams'] = 32

    cfg['maxclients'] = 32

    cfg['streambufsec'] = 2.0

    cfg['prebufferms'] = 100

    return cfg


def mergeconfig(cfg, usercfg):

    for k in usercfg:

        cfg[k] = usercfg[k]

    return cfg


def applyconfig(cfg):

    global MASTERGAIN, MASTERMUTE, MIXFRAMES

    if 'mastergain' in cfg:
        MASTERGAIN = float(cfg['mastergain'])

    if 'mastermute' in cfg:
        MASTERMUTE = bool(cfg['mastermute'])

    if 'frames' in cfg:
        MIXFRAMES = int(cfg['frames'])


def getconfig():

    cfg = defaultconfig()

    if os.path.exists(AUDIOCONF):

        try:

            with open(AUDIOCONF, 'r') as f:
                usercfg = json.load(f)

            cfg = mergeconfig(cfg, usercfg)

        except Exception:

            pass

    return cfg


# utility functions
def ioc(dirv, typev, nrv, sizev):

    IOC_NRBITS = 8

    IOC_TYPEBITS = 8

    IOC_SIZEBITS = 14

    IOC_DIRBITS = 2

    IOC_NRSHIFT = 0

    IOC_TYPESHIFT = IOC_NRSHIFT + IOC_NRBITS

    IOC_SIZESHIFT = IOC_TYPESHIFT + IOC_TYPEBITS

    IOC_DIRSHIFT = IOC_SIZESHIFT + IOC_SIZEBITS

    return (int(dirv) << IOC_DIRSHIFT) | (int(typev) << IOC_TYPESHIFT) | (int(nrv) << IOC_NRSHIFT) | (int(sizev) << IOC_SIZESHIFT)


def io(typec, nr):

    IOC_NONE = 0

    return ioc(IOC_NONE, ord(typec), int(nr), 0)


def ior(typec, nr, stype):

    IOC_READ = 2

    return ioc(IOC_READ, ord(typec), int(nr), ctypes.sizeof(stype))


def iow(typec, nr, stype):

    IOC_WRITE = 1

    return ioc(IOC_WRITE, ord(typec), int(nr), ctypes.sizeof(stype))


def iowr(typec, nr, stype):

    IOC_READ = 2

    IOC_WRITE = 1

    return ioc(IOC_READ | IOC_WRITE, ord(typec), int(nr), ctypes.sizeof(stype))


class snd_mask(ctypes.Structure):

    _fields_ = [
        ("bits", ctypes.c_uint32 * 8),
    ]


class snd_interval(ctypes.Structure):

    _fields_ = [
        ("min", ctypes.c_uint32),
        ("max", ctypes.c_uint32),
        ("openmin", ctypes.c_uint32, 1),
        ("openmax", ctypes.c_uint32, 1),
        ("integer", ctypes.c_uint32, 1),
        ("empty", ctypes.c_uint32, 1),
        ("pad", ctypes.c_uint32, 28),
    ]


class snd_pcm_hw_params(ctypes.Structure):

    _fields_ = [
        ("flags", ctypes.c_uint32),

        ("masks", snd_mask * 3),
        ("mres", snd_mask * 5),

        ("intervals", snd_interval * 12),
        ("ires", snd_interval * 9),

        ("rmask", ctypes.c_uint32),
        ("cmask", ctypes.c_uint32),

        ("info", ctypes.c_uint32),
        ("msbits", ctypes.c_uint32),
        ("rate_num", ctypes.c_uint32),
        ("rate_den", ctypes.c_uint32),

        ("fifo_size", ctypes.c_ulong),

        ("sync", ctypes.c_ubyte * 16),
        ("reserved", ctypes.c_ubyte * 48),
    ]


class snd_pcm_sw_params(ctypes.Structure):

    _fields_ = [
        ("tstamp_mode", ctypes.c_int32),
        ("period_step", ctypes.c_uint32),
        ("sleep_min", ctypes.c_uint32),

        ("avail_min", ctypes.c_ulong),
        ("xfer_align", ctypes.c_ulong),
        ("start_threshold", ctypes.c_ulong),
        ("stop_threshold", ctypes.c_ulong),
        ("silence_threshold", ctypes.c_ulong),
        ("silence_size", ctypes.c_ulong),
        ("boundary", ctypes.c_ulong),

        ("proto", ctypes.c_uint32),
        ("tstamp_type", ctypes.c_uint32),

        ("reserved", ctypes.c_ubyte * 56),
    ]


def maskset(m, bit):

    idx = int(bit) // 32

    off = int(bit) % 32

    if idx < 0 or idx >= 8:

        return

    m.bits[idx] |= (1 << off)


def intervalset(iv, v):

    iv.min = int(v)

    iv.max = int(v)

    iv.openmin = 0

    iv.openmax = 0

    iv.integer = 1

    iv.empty = 0

    iv.pad = 0


def maskclear(m):

    for i in range(0, 8):

        m.bits[i] = 0


def maskfill(m):

    for i in range(0, 8):

        m.bits[i] = 0xFFFFFFFF


def masksetlist(m, bits):

    maskclear(m)

    for b in bits:

        maskset(m, int(b))


def maskpick(m, preferbits):

    for b in preferbits:

        if maskhas(m, int(b)):

            return int(b)

    return maskfirst(m)


def intervalany(iv):

    iv.min = 0

    iv.max = 0xFFFFFFFF

    iv.openmin = 0

    iv.openmax = 0

    iv.integer = 0

    iv.empty = 0

    iv.pad = 0


def intervalrange(iv, a, b, integer=1):

    iv.min = int(a)

    iv.max = int(b)

    iv.openmin = 0

    iv.openmax = 0

    iv.integer = 1 if integer else 0

    iv.empty = 0

    iv.pad = 0


def paramsany(hw):

    for i in range(0, 3):

        maskfill(hw.masks[i])

    for i in range(0, 12):

        intervalany(hw.intervals[i])

    hw.rmask = 0

    hw.cmask = 0

    hw.info = 0

    hw.msb = 0

    hw.rate_num = 0

    hw.rate_den = 0

    hw.fifo_size = 0


def alsaprobe(fd):

    SNDRV_PCM_IOCTL_PVERSION = ior('A', 0x00, ctypes.c_int)

    ver = ctypes.c_int(0)

    buf = bytearray(ctypes.sizeof(ver))

    ctypes.memmove((ctypes.c_char * len(buf)).from_buffer(buf), ctypes.byref(ver), ctypes.sizeof(ver))

    try:

        fcntl.ioctl(fd, SNDRV_PCM_IOCTL_PVERSION, buf, True)

    except Exception:

        return False

    ctypes.memmove(ctypes.byref(ver), (ctypes.c_char * len(buf)).from_buffer(buf), ctypes.sizeof(ver))

    return int(ver.value) > 0


def alsactlpath(basepath, pcmpath=None):

    card, _ = pcmnumbers(pcmpath) if pcmpath else (None, None)

    if card is not None:

        preferred = basepath + f'/controlC{card}'

        if ischardev(preferred):
            return preferred

    try:

        for name in os.listdir(basepath):

            if not name.startswith('controlC'):

                continue

            p = basepath + '/' + name

            if ischardev(p):

                return p

    except Exception:

        return None

    return None


def alsaapplymixer(ctlfd, gain, mute):

    # Try the common HDA names used by onboard Realtek codecs as well as the
    # virtual and USB devices used by the development environments.

    names = []

    names.append('Master Playback Switch')
    names.append('Master Playback Volume')
    names.append('PCM Playback Switch')
    names.append('PCM Playback Volume')
    names.append('Speaker Playback Switch')
    names.append('Speaker Playback Volume')
    names.append('Headphone Playback Switch')
    names.append('Headphone Playback Volume')
    names.append('DAC Playback Switch')
    names.append('DAC Playback Volume')
    names.append('Front Playback Switch')
    names.append('Front Playback Volume')
    names.append('Line Out Playback Switch')
    names.append('Line Out Playback Volume')

    discovered = alsamixercontrolnames(ctlfd)

    for name in discovered:

        lowered = name.lower()

        if 'playback' not in lowered:
            continue

        if not (lowered.endswith(' switch') or lowered.endswith(' volume')):
            continue

        if name not in names:
            names.append(name)

    if discovered:

        log(f'alsa mixer controls discovered count={len(discovered)} names={discovered}')

    if mute:

        sw = 0

    else:

        sw = 1

    vol = mastergainmultiplier(gain)

    if vol < 0.0:
        vol = 0.0

    if vol > 1.0:
        vol = 1.0

    ok = False
    automutedisabled = False

    for n in names:

        if n.endswith('Switch'):

            if alsasetbyname(ctlfd, n, sw):

                ok = True

        if n.endswith('Volume'):

            if alsasetbyname(ctlfd, n, vol):

                ok = True

    # Broken or stale jack detection can leave the rear analogue line-out
    # muted even though every playback switch is on. During bring-up, keep all
    # analogue outputs active; "Disabled" is item zero on the standard HDA
    # Auto-Mute Mode enumeration.
    if not mute and 'Auto-Mute Mode' in discovered:

        automutedisabled = alsasetbyname(ctlfd, 'Auto-Mute Mode', 0)

        if automutedisabled:
            ok = True

    if not ok:

        log(f'alsa mixer apply FAILED (no matching controls) mute={mute} gain={vol:.2f} auto_mute_disabled={automutedisabled}')

    else:

        log(f'alsa mixer apply ok mute={mute} gain={vol:.2f} auto_mute_disabled={automutedisabled}')

    return ok


def alsasetbyname(ctlfd, name, value):

    # ALSA control ioctl structs
    # We only support BOOLEAN (switch) and INTEGER (volume) element types here.

    SNDRV_CTL_IOCTL_ELEM_INFO = iowr('U', 0x11, sndctleminfo)

    SNDRV_CTL_IOCTL_ELEM_READ = iowr('U', 0x12, sndctlemvalue)

    SNDRV_CTL_IOCTL_ELEM_WRITE = iowr('U', 0x13, sndctlemvalue)

    info = sndctleminfo()

    info.id.setname(name)
    info.id.iface = 2  # SNDRV_CTL_ELEM_IFACE_MIXER

    try:

        fcntl.ioctl(ctlfd, SNDRV_CTL_IOCTL_ELEM_INFO, info)

    except Exception:

        return False

    if info.type == 1:

        v = sndctlemvalue()

        v.id = info.id

        count = max(1, min(128, int(info.count)))

        for index in range(count):
            v.value.boolean[index] = int(value)

        try:

            fcntl.ioctl(ctlfd, SNDRV_CTL_IOCTL_ELEM_WRITE, v)

            return True

        except Exception:

            return False

    if info.type == 2:

        v = sndctlemvalue()

        v.id = info.id

        lo = int(info.value.integer.min)

        hi = int(info.value.integer.max)

        x = float(value)

        scaled = int(lo + (x * float(hi - lo)))

        if scaled < lo:
            scaled = lo

        if scaled > hi:
            scaled = hi

        count = max(1, min(128, int(info.count)))

        for index in range(count):
            v.value.integer[index] = int(scaled)

        try:

            fcntl.ioctl(ctlfd, SNDRV_CTL_IOCTL_ELEM_WRITE, v)

            return True

        except Exception:

            return False

    if info.type == 3:

        v = sndctlemvalue()

        v.id = info.id

        item = max(0, int(value))

        count = max(1, min(128, int(info.count)))

        for index in range(count):
            v.value.enumerated[index] = item

        try:

            fcntl.ioctl(ctlfd, SNDRV_CTL_IOCTL_ELEM_WRITE, v)

            return True

        except Exception:

            return False

    return False


class sndctlemoid(ctypes.Structure):

    _fields_ = [
        ('numid', ctypes.c_uint),
        ('iface', ctypes.c_uint),
        ('device', ctypes.c_uint),
        ('subdevice', ctypes.c_uint),
        ('name', ctypes.c_char * 44),
        ('index', ctypes.c_uint),
    ]

    def setname(self, s):

        b = s.encode('utf-8')[:43]

        self.name = b + b'\x00' * (44 - len(b))


class sndctleminfoint(ctypes.Structure):

    _fields_ = [
        ('min', ctypes.c_long),
        ('max', ctypes.c_long),
        ('step', ctypes.c_long),
    ]


class sndctleminfoval(ctypes.Union):

    _fields_ = [
        ('integer', sndctleminfoint),
        # The kernel UAPI reserves 128 bytes for this union. Its size is part
        # of the encoded ioctl request number, so shortening it makes every
        # SNDRV_CTL_IOCTL_ELEM_INFO request invalid.
        ('reserved', ctypes.c_byte * 128),
    ]


class sndctleminfo(ctypes.Structure):

    _fields_ = [
        ('id', sndctlemoid),
        ('type', ctypes.c_uint),
        ('access', ctypes.c_uint),
        ('count', ctypes.c_uint),
        ('owner', ctypes.c_uint),
        ('value', sndctleminfoval),
        ('reserved', ctypes.c_byte * 64),
    ]


class sndctlemvalueval(ctypes.Union):

    _fields_ = [
        ('integer', ctypes.c_long * 128),
        ('boolean', ctypes.c_long * 128),
        ('enumerated', ctypes.c_uint * 128),
        ('reserved', ctypes.c_byte * 512),
    ]

    def setint(self, v):

        self.integer[0] = int(v)

    def setbool(self, v):

        self.boolean[0] = int(v)


class sndctlemvalue(ctypes.Structure):

    _fields_ = [
        ('id', sndctlemoid),
        ('indirect', ctypes.c_uint),
        ('value', sndctlemvalueval),
        ('reserved', ctypes.c_byte * 128),
    ]


class sndctlemlist(ctypes.Structure):

    _fields_ = [
        ('offset', ctypes.c_uint),
        ('space', ctypes.c_uint),
        ('used', ctypes.c_uint),
        ('count', ctypes.c_uint),
        ('pids', ctypes.c_void_p),
        ('reserved', ctypes.c_byte * 50),
    ]


def alsamixercontrolnames(ctlfd):

    SNDRV_CTL_IOCTL_ELEM_LIST = iowr('U', 0x10, sndctlemlist)

    probe = sndctlemlist()

    try:

        fcntl.ioctl(ctlfd, SNDRV_CTL_IOCTL_ELEM_LIST, probe)

    except Exception as e:

        log(f'alsa mixer control enumeration FAILED stage=count err={e}')
        return []

    count = max(0, min(4096, int(probe.count)))

    if count == 0:

        return []

    identifiers = (sndctlemoid * count)()
    listing = sndctlemlist()
    listing.offset = 0
    listing.space = count
    listing.pids = ctypes.addressof(identifiers)

    try:

        fcntl.ioctl(ctlfd, SNDRV_CTL_IOCTL_ELEM_LIST, listing)

    except Exception as e:

        log(f'alsa mixer control enumeration FAILED stage=list err={e}')
        return []

    names = []

    for index in range(min(count, int(listing.used))):

        identifier = identifiers[index]

        if int(identifier.iface) != 2:  # SNDRV_CTL_ELEM_IFACE_MIXER
            continue

        raw = bytes(identifier.name).split(b'\x00', 1)[0]
        name = raw.decode('utf-8', errors='replace').strip()

        if name and name not in names:
            names.append(name)

    return names


def maskhas(m, bit):

    idx = int(bit) // 32
    off = int(bit) % 32

    return (m.bits[idx] >> off) & 1


def maskfirst(m):

    for bit in range(0, 256):

        if maskhas(m, bit):
            return bit

    return None


def intervalclamp(iv, want):

    if iv.empty:
        return None

    v = int(want)

    if v < int(iv.min):
        v = int(iv.min)

    if v > int(iv.max):
        v = int(iv.max)

    if iv.integer:
        v = int(v)

    return v


def alsadelay(fd):

    SNDRV_PCM_IOCTL_DELAY = ior('A', 0x21, ctypes.c_long)

    delay = ctypes.c_long(0)

    buf = bytearray(ctypes.sizeof(delay))

    ctypes.memmove((ctypes.c_char * len(buf)).from_buffer(buf), ctypes.byref(delay), ctypes.sizeof(delay))

    try:

        fcntl.ioctl(fd, SNDRV_PCM_IOCTL_DELAY, buf, True)

    except Exception:

        return None

    ctypes.memmove(ctypes.byref(delay), (ctypes.c_char * len(buf)).from_buffer(buf), ctypes.sizeof(delay))

    return int(delay.value)


def alsaprepare(fd):

    SNDRV_PCM_IOCTL_PREPARE = io('A', 0x40)

    try:

        fcntl.ioctl(fd, SNDRV_PCM_IOCTL_PREPARE, 0)
        return True

    except Exception:

        return False


def alsarecoverableerror(error):

    value = getattr(error, 'errno', error)

    try:
        value = int(value)
    except Exception:
        return False

    recoverable = {
        int(getattr(errno, 'EPIPE', 32)),
        int(getattr(errno, 'ESTRPIPE', 86)),
        int(getattr(errno, 'EBADFD', 77)),
    }

    return value in recoverable


def alsasetup(fd, samplerate, channels, frames, fmt):

    SNDRV_PCM_ACCESS_RW_INTERLEAVED = 3

    SNDRV_PCM_FORMAT_S16_LE = 2

    SNDRV_PCM_SUBFORMAT_STD = 0

    # mask indices
    HW_ACCESS = 0
    HW_FORMAT = 1
    HW_SUBFORMAT = 2

    # interval indices (uapi subset)
    I_CHANNELS = 2
    I_RATE = 3
    I_PERIOD_SIZE = 5
    I_PERIODS = 7
    I_BUFFER_SIZE = 9

    def clampinterval(iv, want):

        if getattr(iv, "empty", 0):
            return None

        v = int(want)

        if v < int(iv.min):
            v = int(iv.min)

        if v > int(iv.max):
            v = int(iv.max)

        if getattr(iv, "integer", 0):
            v = int(v)

        return v


    periods = 4

    buffersz = int(frames) * int(periods)

    SNDRV_PCM_IOCTL_HW_REFINE = iowr('A', 0x10, snd_pcm_hw_params)

    SNDRV_PCM_IOCTL_HW_PARAMS = iowr('A', 0x11, snd_pcm_hw_params)

    SNDRV_PCM_IOCTL_SW_PARAMS = iowr('A', 0x13, snd_pcm_sw_params)

    SNDRV_PCM_IOCTL_PREPARE = io('A', 0x40)

    hw = snd_pcm_hw_params()

    paramsany(hw)

    # request masks (start broad, then pick after refine)
    masksetlist(hw.masks[HW_ACCESS], [SNDRV_PCM_ACCESS_RW_INTERLEAVED])

    fmtprefer = [
        SNDRV_PCM_FORMAT_S16_LE,
    ]

    masksetlist(hw.masks[HW_FORMAT], fmtprefer)

    masksetlist(hw.masks[HW_SUBFORMAT], [SNDRV_PCM_SUBFORMAT_STD])

    # request intervals (start as ranges so refine can succeed on more devices)
    intervalrange(hw.intervals[I_CHANNELS], 1, 8, integer=1)

    intervalrange(hw.intervals[I_RATE], 8000, 192000, integer=1)

    intervalrange(hw.intervals[I_PERIOD_SIZE], 16, 16384, integer=1)

    intervalrange(hw.intervals[I_PERIODS], 2, 64, integer=1)

    intervalrange(hw.intervals[I_BUFFER_SIZE], 32, 262144, integer=1)

    # mark requested params (this matters)
    hw.rmask = 0

    hw.rmask |= (1 << int(HW_ACCESS))
    hw.rmask |= (1 << int(HW_FORMAT))
    hw.rmask |= (1 << int(HW_SUBFORMAT))

    hw.rmask |= (1 << int(10))  # CHANNELS param id
    hw.rmask |= (1 << int(11))  # RATE param id
    hw.rmask |= (1 << int(13))  # PERIOD_SIZE param id
    hw.rmask |= (1 << int(15))  # PERIODS param id
    hw.rmask |= (1 << int(17))  # BUFFER_SIZE param id

    try:

        fcntl.ioctl(fd, SNDRV_PCM_IOCTL_HW_REFINE, hw, True)

    except Exception as e:

        log(f'alsa ioctl hw_refine FAILED err={e}')

        return False

    # choose format after refine
    fmtchosen = maskpick(hw.masks[HW_FORMAT], fmtprefer)

    if fmtchosen is None:
        log('alsa refine: no format supported')

        return False

    masksetlist(hw.masks[HW_FORMAT], [int(fmtchosen)])

    # clamp to refined ranges
    ch = clampinterval(hw.intervals[I_CHANNELS], channels)

    rt = clampinterval(hw.intervals[I_RATE], samplerate)

    ps = clampinterval(hw.intervals[I_PERIOD_SIZE], frames)

    pr = clampinterval(hw.intervals[I_PERIODS], periods)

    bs = clampinterval(hw.intervals[I_BUFFER_SIZE], buffersz)

    if (ch is None) or (rt is None) or (ps is None) or (pr is None) or (bs is None):
        log('alsa refine: required interval empty')

        return False

    # keep buffer consistent with period_size * periods
    bs2 = int(ps) * int(pr)

    if bs2 < int(hw.intervals[I_BUFFER_SIZE].min):
        bs2 = int(hw.intervals[I_BUFFER_SIZE].min)

    if bs2 > int(hw.intervals[I_BUFFER_SIZE].max):
        bs2 = int(hw.intervals[I_BUFFER_SIZE].max)

    intervalset(hw.intervals[I_CHANNELS], int(ch))

    intervalset(hw.intervals[I_RATE], int(rt))

    intervalset(hw.intervals[I_PERIOD_SIZE], int(ps))

    intervalset(hw.intervals[I_PERIODS], int(pr))

    intervalset(hw.intervals[I_BUFFER_SIZE], int(bs2))

    try:

        fcntl.ioctl(fd, SNDRV_PCM_IOCTL_HW_PARAMS, hw, True)

    except Exception as e:

        log(f'alsa ioctl hw_params FAILED err={e}')

        return False

    sw = snd_pcm_sw_params()

    ctypes.memset(ctypes.byref(sw), 0, ctypes.sizeof(sw))

    sw.tstamp_mode = 0

    sw.period_step = 1

    sw.sleep_min = 0

    sw.avail_min = int(ps)

    sw.xfer_align = 1

    # Playback starts automatically once writes have primed most of the
    # hardware buffer. Starting an empty stream here races the first write and
    # can put a real HDA device into XRUN before the mixer has queued audio.
    sw.start_threshold = max(int(ps), int(bs2) - int(ps))

    sw.boundary = 0xFFFFFFFFFFFFFFFF

    sw.stop_threshold = sw.boundary

    sw.silence_threshold = 0

    sw.silence_size = 0

    sw.proto = 0

    sw.tstamp_type = 0

    try:

        fcntl.ioctl(fd, SNDRV_PCM_IOCTL_SW_PARAMS, sw, True)

        fcntl.ioctl(fd, SNDRV_PCM_IOCTL_PREPARE, 0)

        info = {}

        info['samplerate'] = int(hw.intervals[I_RATE].min)

        info['channels'] = int(hw.intervals[I_CHANNELS].min)

        info['period_size'] = int(hw.intervals[I_PERIOD_SIZE].min)

        info['periods'] = int(hw.intervals[I_PERIODS].min)

        info['buffer_size'] = int(hw.intervals[I_BUFFER_SIZE].min)

        info['format'] = DEFAULTFMT

        log(f'alsa prepared rate={info["samplerate"]} ch={info["channels"]} period={info["period_size"]} periods={info["periods"]} buffer={info["buffer_size"]} start_threshold={sw.start_threshold}')

        return info

    except Exception as e:

        log(f'alsa ioctl sw/prepare/start FAILED err={e}')

        return None


def now():

    return time.time()


def clamp(x, a, b):

    if x < a:
        return a

    if x > b:
        return b

    return x


def mastergainmultiplier(gain):

    return calibratedmastergain(gain)


def calibratedmastergain(gain):

    """Map the desktop volume control onto the useful hardware range."""

    value = clamp(float(gain), 0.0, 1.0)

    if value <= 0.28:
        return value * 0.90 / 0.28

    return 0.90 + ((value - 0.28) * 0.10 / 0.72)


# device functions
def scan():

    global DEVICES

    DEVICES = []

    try:

        entries = os.listdir(NODESPATH)

    except Exception:

        entries = []

    for name in entries:

        nodepath = NODESPATH + '/' + name

        dev = devfromnode(nodepath)

        if dev:
            DEVICES.append(dev)


def readuevent(path):

    data = {}

    try:

        with open(path, 'r') as f:

            lines = f.read().splitlines()

    except Exception:

        return data

    for line in lines:

        if '=' not in line:
            continue

        k, v = line.split('=', 1)

        data[k.strip()] = v.strip()

    return data


def ischardev(path):

    try:

        st = os.stat(path)

    except Exception:

        return False

    return stat.S_ISCHR(st.st_mode)


def ispcmname(name):

    # ALSA-style names: pcmC0D0p / pcmC1D0c
    if not name.startswith('pcmC'):
        return False

    if not ('D' in name):
        return False

    if not (name.endswith('p') or name.endswith('c')):
        return False

    return True


def pcmnumbers(path):

    name = os.path.basename(str(path))

    if not ispcmname(name):
        return None, None

    try:

        cardpart, devicepart = name[4:].split('D', 1)
        digits = ''

        for character in devicepart:

            if not character.isdigit():
                break

            digits += character

        return int(cardpart), int(digits)

    except Exception:

        return None, None


def normalizecodecid(value):

    value = str(value).strip().lower()

    if value.startswith('0x'):
        value = value[2:]

    return ''.join(character for character in value if character in '0123456789abcdef')


def readsmalltext(path):

    try:

        with open(path, 'r', encoding='utf-8', errors='replace') as handle:
            return ' '.join(handle.read(4096).split()).strip()

    except Exception:

        return ''


def usablehardwarestring(value):

    value = ' '.join(str(value or '').split()).strip()
    lowered = value.casefold()

    if lowered in ('', 'unknown', 'none', 'not specified', 'system product name',
                   'system manufacturer', 'default string', 'to be filled by o.e.m.'):
        return ''

    return value


def soundhardwareidentity(card):

    result = {'manufacturer': '', 'product': '', 'source': ''}

    try:
        card = int(card)
    except Exception:
        return result

    state = os.path.realpath(os.path.join(SOUNDSTATEPATH, '..', '..'))
    current = os.path.realpath(os.path.join(SOUNDSTATEPATH, f'card{card}', 'device'))

    while current and current != os.path.dirname(current):

        try:

            if os.path.commonpath((state, current)) != state:
                break

        except Exception:

            break

        if not result['product']:

            for filename in ('product', 'product_name', 'model'):

                value = usablehardwarestring(readsmalltext(os.path.join(current, filename)))

                if value:
                    result['product'] = value
                    result['source'] = 'device'
                    break

        if not result['manufacturer']:

            for filename in ('manufacturer', 'vendor_name'):

                value = usablehardwarestring(readsmalltext(os.path.join(current, filename)))

                if value:
                    result['manufacturer'] = value
                    break

        if result['product'] and result['manufacturer']:
            break

        current = os.path.dirname(current)

    # Keep the machine or motherboard identity only as a last-resort fallback.
    # It identifies the computer, not the audio product; devicename() prefers
    # ALSA endpoint and codec identities before exposing this value.
    if not result['product']:

        for filename in ('product_name', 'board_name'):

            value = usablehardwarestring(readsmalltext(os.path.join(DMIROOT, filename)))

            if value:
                result['product'] = value
                result['source'] = 'system'
                break

        for filename in ('sys_vendor', 'board_vendor'):

            value = usablehardwarestring(readsmalltext(os.path.join(DMIROOT, filename)))

            if value:
                result['manufacturer'] = value
                break

    return result


def soundmonitornames(card):

    names = []

    try:
        cardpath = os.path.join(ASOUNDPROCPATH, f'card{int(card)}')
        entries = sorted(os.listdir(cardpath))
    except Exception:
        return names

    for entry in entries:

        if not entry.startswith('eld#'):
            continue

        data = {}

        try:

            with open(os.path.join(cardpath, entry), 'r', encoding='utf-8', errors='replace') as handle:

                for rawline in handle:

                    parts = rawline.strip().split(None, 1)

                    if len(parts) == 2:
                        data[parts[0].strip().lower()] = parts[1].strip()

        except Exception:

            continue

        name = ' '.join(data.get('monitor_name', '').split()).strip()
        present = data.get('monitor_present', '1').strip() != '0'
        valid = data.get('eld_valid', '1').strip() != '0'

        if name and present and valid and name not in names:
            names.append(name)

    return names


def alsacardinfo(card):

    try:
        card = int(card)
    except Exception:
        return {'card': None, 'id': '', 'name': '', 'manufacturer': '', 'product': '', 'productsource': '', 'monitors': [], 'codecs': [], 'usb': ''}

    if card in ALSACARDINFO:
        return ALSACARDINFO[card]

    info = {'card': card, 'id': '', 'name': '', 'manufacturer': '', 'product': '', 'productsource': '', 'monitors': [], 'codecs': [], 'usb': ''}
    cardpath = os.path.join(ASOUNDPROCPATH, f'card{card}')

    hardware = soundhardwareidentity(card)
    info['manufacturer'] = hardware.get('manufacturer', '')
    info['product'] = hardware.get('product', '')
    info['productsource'] = hardware.get('source', '')
    info['monitors'] = soundmonitornames(card)

    try:

        with open(os.path.join(cardpath, 'id'), 'r', encoding='utf-8', errors='replace') as handle:
            info['id'] = handle.read().strip()

    except Exception:

        pass

    # The T1OS sound-state cards inventory carries the user-facing card
    # description while the driver node itself is normally only called "snd".
    try:

        with open(os.path.join(ASOUNDPROCPATH, 'cards'), 'r', encoding='utf-8', errors='replace') as handle:

            for rawline in handle:

                line = rawline.strip()
                before, separator, description = line.partition(':')

                if not separator or not before.split() or before.split()[0] != str(card):
                    continue

                _, dash, friendly = description.partition(' - ')
                info['name'] = (friendly if dash else description).strip()
                break

    except Exception:

        pass

    try:

        entries = sorted(os.listdir(cardpath))

    except Exception:

        entries = []

    for entry in entries:

        if not entry.startswith('codec'):
            continue

        codec = {'name': '', 'vendor_id': '', 'subsystem_id': ''}

        try:

            with open(os.path.join(cardpath, entry), 'r', encoding='utf-8', errors='replace') as handle:

                for line in handle:

                    key, separator, value = line.partition(':')

                    if not separator:
                        continue

                    key = key.strip().lower()
                    value = value.strip()

                    if key == 'codec':
                        codec['name'] = value
                    elif key == 'vendor id':
                        codec['vendor_id'] = normalizecodecid(value)
                    elif key == 'subsystem id':
                        codec['subsystem_id'] = normalizecodecid(value)

        except Exception:

            continue

        if codec['name'] or codec['vendor_id']:
            info['codecs'].append(codec)

    try:

        with open(os.path.join(cardpath, 'usbid'), 'r', encoding='ascii', errors='replace') as handle:
            info['usb'] = handle.read().strip()

    except Exception:

        pass

    ALSACARDINFO[card] = info
    return info


def alsapcmname(card, device):

    try:
        prefix = f'{int(card):02d}-{int(device):02d}'
    except Exception:
        return ''

    try:

        with open(os.path.join(ASOUNDPROCPATH, 'pcm'), 'r', encoding='utf-8', errors='replace') as handle:

            for rawline in handle:

                line = rawline.strip()

                if not line.startswith(prefix + ':'):
                    continue

                parts = line.split(':')

                if len(parts) > 1:
                    return parts[1].strip()

    except Exception:

        pass

    return ''


def usabledevicename(value, identifier=''):

    value = ' '.join(str(value or '').split()).strip()

    if not value:
        return ''

    lowered = value.lower()
    node = str(identifier or '').strip().lower()

    if lowered == node or lowered in ('snd', 'sound', 'audio', 'audioout', 'output'):
        return ''

    if (lowered.startswith(NODESPATH.lower() + '/') or
            lowered.startswith('snd/') or
            lowered.startswith('pcm') and 'd' in lowered):
        return ''

    return value


def devicename(dev):

    if not isinstance(dev, dict):
        return 'Audio output'

    identifier = dev.get('id', '')
    caps = dev.get('caps', {}) if isinstance(dev.get('caps'), dict) else {}
    meta = dev.get('meta', {}) if isinstance(dev.get('meta'), dict) else {}
    outpath = ''

    if ACTIVEDEV and ACTIVEDEV.get('id') == identifier and BACKEND:
        outpath = BACKEND.get('outpath', '')

    if not outpath:
        candidates = list(dev.get('pcmcandsout', []) or [])

        if not candidates and dev.get('pcmout'):
            candidates = [dev.get('pcmout')]

        if candidates:
            preferredcodec = getconfig().get('preferredcodec')
            outpath = sorted(candidates, key=lambda path: pcmpreferencekey(path, preferredcodec))[0]

    card, pcmdevice = pcmnumbers(outpath)
    cardinfo = alsacardinfo(card) if card is not None else {}

    if card is not None:

        product = usabledevicename(cardinfo.get('product'), identifier)
        manufacturer = usabledevicename(cardinfo.get('manufacturer'), identifier)

        if product and cardinfo.get('productsource') == 'device':

            if manufacturer and manufacturer.casefold() not in product.casefold():
                return manufacturer + ' ' + product

            return product

        for monitor in cardinfo.get('monitors', []):

            candidate = usabledevicename(monitor, identifier)

            if candidate:
                return candidate

    for key in ('displayname', 'friendlyname', 'product', 'model'):

        candidate = usabledevicename(caps.get(key), identifier)

        if candidate:
            return candidate

    if card is not None:

        for codec in cardinfo.get('codecs', []):

            candidate = usabledevicename(codec.get('name'), identifier)

            if candidate:
                return candidate

        candidate = usabledevicename(cardinfo.get('name'), identifier)

        if candidate:
            return candidate

        candidate = usabledevicename(alsapcmname(card, pcmdevice), identifier)

        if candidate:
            return candidate

    candidate = usabledevicename(caps.get('name'), identifier)

    if candidate:
        return candidate

    for key in ('ID_MODEL_FROM_DATABASE', 'ID_MODEL', 'PRODUCT', 'NAME'):

        candidate = usabledevicename(meta.get(key), identifier)

        if candidate:
            return candidate.replace('_', ' ')

    if card is not None:

        product = usabledevicename(cardinfo.get('product'), identifier)
        manufacturer = usabledevicename(cardinfo.get('manufacturer'), identifier)

        if product:

            if manufacturer and manufacturer.casefold() not in product.casefold():
                return manufacturer + ' ' + product

            return product

        candidate = usabledevicename(cardinfo.get('id'), identifier)

        if candidate:
            return candidate

    return 'Audio output'


def pcmpreferencekey(path, preference=None, cardinfo=None):

    card, device = pcmnumbers(path)

    if card is None:
        return 99, 9999, 9999, os.path.basename(str(path))

    if cardinfo is None:
        cardinfo = alsacardinfo(card)

    preferred = normalizecodecid(preference or '')
    codecs = list(cardinfo.get('codecs', []) or [])
    preferredmatch = False
    referenceanalog = False
    realtekanalog = False
    hdmi = False

    for codec in codecs:

        vendor = normalizecodecid(codec.get('vendor_id', ''))
        name = str(codec.get('name', '')).strip().lower()

        if preferred and (vendor == preferred or preferred in vendor or preferred in normalizecodecid(name)):
            preferredmatch = True

        if vendor == REFERENCEANALOGCODEC and 'hdmi' not in name:
            referenceanalog = True

        if vendor.startswith('10ec') and 'hdmi' not in name:
            realtekanalog = True

        if 'hdmi' in name or vendor.startswith('1002') or vendor.startswith('10de'):
            hdmi = True

    if preferredmatch:
        rank = 0
    elif referenceanalog:
        rank = 5
    elif realtekanalog:
        rank = 10
    elif codecs and not hdmi:
        rank = 20
    elif not codecs:
        rank = 30
    else:
        rank = 40

    return rank, card, device, os.path.basename(str(path))


def pcmcandidatediagnostic(path, preference=None):

    card, device = pcmnumbers(path)
    cardinfo = alsacardinfo(card) if card is not None else {}
    codecs = []

    for codec in cardinfo.get('codecs', []) or []:

        codecs.append({
            'vendor': normalizecodecid(codec.get('vendor_id', '')),
            'name': str(codec.get('name', '')).strip(),
        })

    return {
        'path': str(path),
        'rank': int(pcmpreferencekey(path, preference, cardinfo)[0]),
        'card': card,
        'device': device,
        'id': str(cardinfo.get('id', '')).strip(),
        'name': str(cardinfo.get('name', '')).strip(),
        'codecs': codecs,
    }


def findpcmnodes(nodepath):

    pcmout = ""

    pcmin = ""

    meta = {}

    outs = []

    ins = []

    # 1) If a uevent file exists anywhere inside the node, prefer it for “query”
    ueventpath = nodepath + '/uevent'

    if os.path.exists(ueventpath):

        meta = readuevent(ueventpath)

    # 2) Walk the node folder to find device nodes (virtio-audio/ALSA will show pcmC*D*p)
    for root, dirs, files in os.walk(nodepath):

        for name in files:

            full = root + '/' + name

            if not ispcmname(name) and not (name.startswith('pcm') and (name.endswith('p') or name.endswith('c'))):
                continue

            # we only consider actual character devices as “Linux-exposed audio”
            if not ischardev(full):
                continue

            if name.endswith('p'):

                outs.append(full)

                if not pcmout:
                    pcmout = full

            if name.endswith('c'):

                ins.append(full)

                if not pcmin:
                    pcmin = full

        # keep this shallow-ish; node folders can be big
        break

    return pcmout, pcmin, meta, outs, ins


def devfromnode(nodepath):

    if not os.path.isdir(nodepath):

        return None

    dev = {}

    dev['id'] = os.path.basename(nodepath)

    dev['path'] = nodepath

    dev['name'] = dev['id']

    dev['caps'] = {}

    dev['ready'] = False

    dev['pcmout'] = ""

    dev['pcmin'] = ""

    dev['pcmcandsout'] = []

    dev['pcmcandsin'] = []

    dev['meta'] = {}

    # optional T1OS-provided caps.json (keep, but do not require it)
    capspath = nodepath + '/caps.json'

    if os.path.exists(capspath):

        try:

            with open(capspath, 'r') as f:

                dev['caps'] = json.load(f)

        except Exception:

            dev['caps'] = {}

    pcmout, pcmin, meta, outs, ins = findpcmnodes(nodepath)

    dev['pcmout'] = pcmout

    dev['pcmin'] = pcmin

    dev['pcmcandsout'] = outs

    dev['pcmcandsin'] = ins

    dev['meta'] = meta

    # If caps.json isn't present, infer "audio" purely from Linux-exposed device nodes
    if not dev['caps']:

        if pcmout or pcmin:

            dev['caps']['class'] = 'audio'

            dev['caps']['audioout'] = True if pcmout else False

            dev['caps']['audioin'] = True if pcmin else False

            dev['caps']['samplerate'] = DEFAULTSR

            dev['caps']['channels'] = DEFAULTCH

            dev['caps']['format'] = DEFAULTFMT

            # best-effort “query” name from uevent if present
            if meta.get('DEVNAME'):

                dev['caps']['name'] = meta.get('DEVNAME')

            else:

                dev['caps']['name'] = dev['id']

    else:

        # caps.json exists; ensure it matches what the kernel actually exposed
        if pcmout and 'audioout' not in dev['caps']:
            dev['caps']['audioout'] = True

        if pcmin and 'audioin' not in dev['caps']:
            dev['caps']['audioin'] = True

        # if caps describes audio but forgot to declare class, normalize it
        if ('class' not in dev['caps']) and (dev['caps'].get('audioout') or dev['caps'].get('audioin') or dev['caps'].get('audio')):
            dev['caps']['class'] = 'audio'

        # carry Linux metadata too (useful for client UI)
        if meta:
            dev['caps']['uevent'] = meta

    caps = dev.get('caps', {})

    isaudio = True if (caps.get('class') == 'audio' or caps.get('audioout') or caps.get('audio')) else False

    if isaudio and caps.get('audioout') and dev.get('pcmout'):
        dev['ready'] = True

    # filter out non-audio nodes early
    if not dev.get('ready') and not isaudio:

        return None

    return dev


def devlist():

    lst = []

    for dev in DEVICES:

        item = {}

        item['id'] = dev.get('id')

        # The ID remains the stable driver-node key used by MSGDEVSET.  Name is
        # deliberately a human-facing ALSA/card/codec label for control panels.
        item['name'] = devicename(dev)

        item['caps'] = dev.get('caps')

        item['ready'] = dev.get('ready')

        if ACTIVEDEV and dev.get('id') == ACTIVEDEV.get('id') and BACKEND:

            item['format'] = backendformat()

        lst.append(item)

    return lst


def pickautodevice():

    ready = []

    for dev in DEVICES:

        if dev.get('ready'):

            ready.append(dev)

    if not ready:

        return None

    for dev in ready:

        if dev.get('id') == 'snd':

            return 'snd'

    for dev in ready:

        caps = dev.get('caps', {})

        if caps.get('class') == 'audio':

            return dev.get('id')

        if caps.get('audio'):

            return dev.get('id')

        if caps.get('audioout'):

            return dev.get('id')

    return ready[0].get('id')


def devset(devid):

    global ACTIVEDEV, BACKEND

    for dev in DEVICES:

        if dev.get('id') == devid:

            if BACKEND:
                backendclose()

            ACTIVEDEV = dev

            backendopen(dev)

            devnotify()

            return True

    return False


def devcaps(dev):

    if not dev:

        return {}

    return dev.get('caps', {})


def devnotify():

    payload = {}

    payload['devices'] = devlist()

    payload['active'] = ACTIVEDEV.get('id') if ACTIVEDEV else None

    broadcast(MSGNOTIFY, payload)


def devlistemit():

    payload = {}

    payload['devices'] = devlist()

    payload['active'] = ACTIVEDEV.get('id') if ACTIVEDEV else None

    broadcast(MSGDEVLIST, payload)


# backend functions
def backendformat():

    info = {}

    if BACKEND:

        if BACKEND.get('alsa'):

            info = dict(BACKEND.get('alsainfo', {}) or {})

        elif BACKEND.get('type') == 'hda':

            info = dict(BACKEND.get('hda', {}) or {})

    caps = devcaps(ACTIVEDEV)

    result = {
        'samplerate': int(info.get('samplerate', caps.get('samplerate', DEFAULTSR))),
        'channels': int(info.get('channels', caps.get('channels', DEFAULTCH))),
        'format': str(info.get('format', caps.get('format', DEFAULTFMT))),
    }

    if BACKEND and BACKEND.get('outpath'):
        result['path'] = str(BACKEND.get('outpath'))

    if BACKEND and BACKEND.get('alsactlpath'):
        result['mixer'] = str(BACKEND.get('alsactlpath'))

    if BACKEND and BACKEND.get('alsacard'):
        result['card'] = dict(BACKEND.get('alsacard'))

    return result


def backendsamplerate():

    try:

        rate = int(backendformat().get('samplerate', DEFAULTSR))

    except Exception:

        rate = DEFAULTSR

    return rate if rate > 0 else DEFAULTSR


def backendpendingframes():

    if not BACKEND:

        return 0

    if BACKEND.get('alsa'):

        framebytes = max(1, int(BACKEND.get('framebytes', FRAMEBYTES)))
        pending = len(BACKEND.get('pending', b''))
        rb = BACKEND.get('outrb')

        if rb:

            pending += int(rbavail(rb))

        delay = alsadelay(BACKEND.get('outfd')) if BACKEND.get('outfd') else None

        if delay is not None and delay > 0:

            pending += int(delay) * framebytes

        return max(0, int(pending // framebytes))

    if BACKEND.get('type') == 'hda':

        hda = BACKEND.get('hda', {})
        out = hda.get('out', {})
        framebytes = max(1, int(out.get('framesize', FRAMEBYTES)))
        pending = int(rbavail(hda.get('rb'))) if hda.get('rb') else 0
        bufsize = int(out.get('bufsize', 0))
        wp = int(out.get('wp', 0))
        base = out.get('base')
        mmio = BACKEND.get('mmio')

        if bufsize > 0 and base is not None and mmio:

            rp = mmioread32(mmio, int(base) + 0x04)

            if rp is not None:

                rp = int(rp) % bufsize
                wp %= bufsize
                pending += (wp - rp) if wp >= rp else ((bufsize - rp) + wp)

        return max(0, int(pending // framebytes))

    return 0


def backendpresentedframes(pendingframes=None):

    global BACKENDPRESENTEDFRAMES

    mixed = max(0, int(MIXEDFRAMES))
    if pendingframes is None:

        pendingframes = backendpendingframes()

    candidate = max(0, min(mixed, mixed - int(pendingframes)))

    if int(BACKENDPRESENTEDFRAMES) > mixed:

        BACKENDPRESENTEDFRAMES = candidate

    elif candidate > int(BACKENDPRESENTEDFRAMES):

        BACKENDPRESENTEDFRAMES = candidate

    return int(BACKENDPRESENTEDFRAMES)


def backendselect(dev):

    if not dev:

        return None

    caps = devcaps(dev)

    backend = caps.get('backend')

    if backend:

        return backend

    if dev.get('pcmout') or dev.get('pcmin'):

        return 'file'

    if dev.get('id') == 'hda':

        return 'hda'

    return 'file'


def backendopen(dev):

    global BACKEND

    if not dev:

        return False

    caps = devcaps(dev)

    if caps.get('class') != 'audio' or not caps.get('audioout'):

        return False

    btype = backendselect(dev)

    if btype == 'hda':

        return backendhdaopen(dev)

    return backendfileopen(dev)


def backendclose():

    global BACKEND

    if not BACKEND:

        return

    btype = BACKEND.get('type')

    if btype == 'hda':

        backendhdaclose()

        return

    backendfileclose()


def backendwrite(pcmbytes):

    if not BACKEND:

        return False

    btype = BACKEND.get('type')

    if btype == 'hda':

        return backendhdawrite(pcmbytes)

    ok = backendfilequeue(pcmbytes)

    backendfilepump()

    return ok


def backendread(nbytes):

    if not BACKEND:

        return None

    btype = BACKEND.get('type')

    if btype == 'hda':

        return backendhdaread(nbytes)

    return backendfileread(nbytes)


def backendctl(cmd, args):

    if not BACKEND:

        return False

    btype = BACKEND.get('type')

    if btype == 'hda':

        return backendhdactl(cmd, args)

    return backendfilectl(cmd, args)


def backendpoll(timeout):

    if not BACKEND:

        time.sleep(timeout)

        return False

    btype = BACKEND.get('type')

    if btype == 'hda':

        return backendhdapoll(timeout)

    return backendfilepoll(timeout)


def backendfileopen(dev):

    global BACKEND

    backend = {}

    backend['type'] = 'file'

    backend['dev'] = dev

    backend['path'] = dev.get('path')

    backend['ready'] = False

    backend['outfd'] = None

    backend['infd'] = None

    backend['alsa'] = False

    candout = dev.get('pcmcandsout', [])

    if not candout and dev.get('pcmout'):

        candout = [dev.get('pcmout')]

    if not candout:

        candout = [backend['path'] + '/out.pcm']

    inpath = dev.get('pcmin') if dev.get('pcmin') else backend['path'] + '/in.pcm'

    ctlpath = backend['path'] + '/ctl.json'

    backend['alsactlpath'] = None
    backend['alsactlfd'] = None

    backend['inpath'] = inpath

    caps = devcaps(dev)

    preferredcodec = getconfig().get('preferredcodec')
    candout = sorted(list(candout), key=lambda path: pcmpreferencekey(path, preferredcodec))
    candidateinfo = [pcmcandidatediagnostic(path, preferredcodec) for path in candout]
    log(
        f'alsa output preference codec={preferredcodec or "auto"} '
        f'candidates={json.dumps(candidateinfo, separators=(",", ":"))}'
    )

    tried = []

    for outpath in candout:

        tried.append(outpath)

        backend['outpath'] = outpath

        backend['alsa'] = False

        backend['outfd'] = None

        # open output
        try:

            flags = os.O_WRONLY

            if ischardev(outpath) and ispcmname(os.path.basename(outpath)):

                flags = os.O_RDWR | os.O_NONBLOCK

                backend['alsa'] = True

            backend['outfd'] = os.open(outpath, flags)

            log(f'backend open out path={outpath} fd={backend["outfd"]} alsa={backend["alsa"]}')

            # confirm this is actually an ALSA PCM (not just a similarly-named chardev)
            if backend.get('outfd') and backend.get('alsa'):

                if not alsaprobe(backend['outfd']):

                    log(f'alsa probe FAILED (not an ALSA PCM) path={outpath}')

                    os.close(backend['outfd'])

                    backend['outfd'] = None

                    backend['alsa'] = False

                    continue

                info = alsasetup(
                    backend['outfd'],
                    samplerate=int(caps.get('samplerate', DEFAULTSR)),
                    channels=int(caps.get('channels', DEFAULTCH)),
                    frames=int(MIXFRAMES),
                    fmt=DEFAULTFMT
                )

                if not info:

                    log(f'alsa setup FAILED path={outpath}')

                    os.close(backend['outfd'])

                    backend['outfd'] = None

                    backend['alsa'] = False

                    continue

                backend['alsainfo'] = info

                card, _ = pcmnumbers(outpath)
                backend['alsacard'] = alsacardinfo(card)
                log(
                    f'alsa output selected path={outpath} card={card} '
                    f'identity={json.dumps(pcmcandidatediagnostic(outpath, preferredcodec), separators=(",", ":"))}'
                )

                backend['periodframes'] = int(info.get('period_size', MIXFRAMES))

                backend['bufferframes'] = int(info.get('buffer_size', backend['periodframes'] * 4))

                backend['framebytes'] = int(info.get('channels', DEFAULTCH)) * 2

                backend['periodbytes'] = int(backend['periodframes'] * backend['framebytes'])

                bytespersec = int(info.get('samplerate', DEFAULTSR)) * int(info.get('channels', DEFAULTCH)) * 2

                outrbsize = int(bytespersec * 2)

                outrbsize = int(outrbsize - (outrbsize % int(backend['framebytes'])))

                backend['outrb'] = rbnew(outrbsize)

                backend['pending'] = b""
                backend['recoveries'] = 0

                backend['alsactlpath'] = alsactlpath(backend['path'], outpath)

                if backend['alsactlpath']:

                    try:
                        backend['alsactlfd'] = os.open(backend['alsactlpath'], os.O_RDWR | os.O_NONBLOCK)
                    except Exception as e:
                        backend['alsactlfd'] = None
                        log(f'alsa mixer control open FAILED path={backend["alsactlpath"]} err={e}')

                if backend.get('alsactlfd'):

                    # Master volume is applied by the software mixer. Keep the
                    # hardware path open at unity so live changes neither walk
                    # ALSA controls in the playback loop nor apply gain twice.
                    okm = alsaapplymixer(backend['alsactlfd'], gain=1.0, mute=False)

                    if not okm:

                        log('alsa mixer did not apply any controls on open')

            # success (raw output OR ALSA configured)
            break

        except Exception as e:

            backend['outfd'] = None

            backend['alsa'] = False

            log(f'backend open out FAILED path={outpath} err={e}')

            continue

    if not backend.get('outfd'):

        log(f'backend open out FAILED (no usable output) tried={tried}')

    # open input (optional)
    if caps.get('audioin'):

        try:

            backend['infd'] = os.open(inpath, os.O_RDONLY | os.O_NONBLOCK)

            log(f'backend open in path={inpath} fd={backend["infd"]}')

        except Exception as e:

            backend['infd'] = None

            log(f'backend open in FAILED path={inpath} err={e}')

    backend['ctl'] = ctlpath

    backend['ready'] = bool(backend.get('outfd'))

    if backend['ready']:

        dev['ready'] = True

    else:

        dev['ready'] = False

    BACKEND = backend

    if backend['ready']:
        devlistemit()

    return backend['ready']


def backendfileclose():

    global BACKEND

    if not BACKEND:

        return

    outfd = BACKEND.get('outfd')

    infd = BACKEND.get('infd')

    if outfd:

        try:

            os.close(outfd)

        except Exception:

            pass

    if infd:

        try:

            os.close(infd)

        except Exception:

            pass

    try:

        dev = BACKEND.get('dev') if BACKEND else None

        if dev:

            dev['ready'] = False

    except Exception:

        pass

    BACKEND = None


def backendfilewrite(pcmbytes):

    global BACKENDWRITES, BACKENDBYTES, BACKENDERRS, LASTBACKENDWRITELOG

    outfd = BACKEND.get('outfd') if BACKEND else None

    outpath = BACKEND.get('outpath') if BACKEND else None

    if not outfd:

        log('backend write skipped (no outfd)')

        return False

    try:

        want = len(pcmbytes)

        got = os.write(outfd, pcmbytes)

        BACKENDWRITES += 1

        BACKENDBYTES += int(got) if got is not None else 0

        if got != want:

            log(f'backend write SHORT path={outpath} want={want} got={got}')

            return False

        nowt = time.monotonic()
        if (nowt - float(LASTBACKENDWRITELOG)) >= AUDIOTELEMETRYINTERVAL:
            log(f'backend write ok path={outpath} bytes={got}')
            LASTBACKENDWRITELOG = nowt

        return True

    except OSError as e:

        BACKENDERRS += 1

        log(f'backend write ERROR path={outpath} want={len(pcmbytes)} errno={e.errno} err={e}')

        if int(e.errno) == 77 and BACKEND and BACKEND.get('alsa'):

            caps = devcaps(BACKEND.get('dev'))

            ok = alsasetup(
                outfd,
                samplerate=int(caps.get('samplerate', DEFAULTSR)),
                channels=int(caps.get('channels', DEFAULTCH)),
                frames=int(MIXFRAMES),
                fmt=DEFAULTFMT
            )

            if ok:

                BACKEND['alsainfo'] = dict(ok)

                BACKEND['periodframes'] = int(ok.get('period_size', BACKEND.get('periodframes', MIXFRAMES)))

                BACKEND['bufferframes'] = int(ok.get('buffer_size', BACKEND.get('bufferframes', MIXFRAMES * 4)))

                if BACKEND.get('alsactlfd'):

                    okm = alsaapplymixer(BACKEND['alsactlfd'], gain=1.0, mute=False)

                    if not okm:

                        log('alsa mixer did not apply any controls after re-setup')

                return False

            os.close(outfd)

            BACKEND['outfd'] = None

            BACKEND['ready'] = False

        return False

    except Exception as e:

        BACKENDERRS += 1

        log(f'backend write ERROR path={outpath} want={len(pcmbytes)} err={e}')

        return False


def backendfilequeue(pcmbytes):

    global BACKENDERRS

    if not BACKEND:

        return False

    if not BACKEND.get('alsa'):

        return backendfilewrite(pcmbytes)

    rb = BACKEND.get('outrb')

    if not rb:

        return False

    ok = rbpush(rb, pcmbytes)

    if not ok:

        BACKENDERRS += 1

        return False

    return True


def backendfilepump():

    global BACKENDWRITES, BACKENDBYTES, BACKENDERRS, XRUNS

    if not BACKEND:

        return False

    if not BACKEND.get('alsa'):

        return False

    outfd = BACKEND.get('outfd')

    if not outfd:

        return False

    periodframes = int(BACKEND.get('periodframes', MIXFRAMES))

    bufferframes = int(BACKEND.get('bufferframes', periodframes * 4))

    framebytes = int(BACKEND.get('framebytes', DEFAULTCH * 2))

    periodbytes = int(periodframes * framebytes)

    rb = BACKEND.get('outrb')

    if not rb:

        return False

    pending = BACKEND.get('pending', b"")

    if pending:

        data = pending

    else:

        delay = alsadelay(outfd)

        if delay is None:

            return False

        freeframes = int(bufferframes - delay)

        if freeframes < periodframes:

            return False

        maxperiods = int(freeframes // periodframes)

        maxbytes = int(maxperiods * periodbytes)

        have = int(rbavail(rb))

        if have < periodbytes:

            return False

        if have < maxbytes:

            maxbytes = int(have - (have % periodbytes))

        if maxbytes < periodbytes:

            return False

        data = rbpop(rb, maxbytes)

        if not data:

            return False

    off = 0

    total = len(data)

    while off < total:

        try:

            got = os.write(outfd, data[off:])

        except OSError as e:

            if getattr(e, "errno", None) in (11, 35):

                BACKEND['pending'] = data[off:]

                return False

            BACKENDERRS += 1

            remaining = data[off:]

            if alsarecoverableerror(e):

                BACKEND['pending'] = remaining
                recovered = alsaprepare(outfd)

                if recovered:

                    XRUNS += 1
                    BACKEND['recoveries'] = int(BACKEND.get('recoveries', 0)) + 1
                    log(
                        f'alsa playback recovered path={BACKEND.get("outpath")} '
                        f'errno={getattr(e, "errno", None)} pendingbytes={len(remaining)} '
                        f'recoveries={BACKEND["recoveries"]}'
                    )
                    return False

                log(
                    f'alsa playback recovery FAILED path={BACKEND.get("outpath")} '
                    f'errno={getattr(e, "errno", None)} pendingbytes={len(remaining)}'
                )
                BACKEND['ready'] = False
                return False

            BACKEND['pending'] = b""
            log(
                f'alsa playback write ERROR path={BACKEND.get("outpath")} '
                f'errno={getattr(e, "errno", None)} pendingbytes={len(remaining)} err={e}'
            )
            return False

        if not got or got <= 0:

            BACKEND['pending'] = data[off:]

            return False

        BACKENDWRITES += 1

        BACKENDBYTES += int(got)

        off += int(got)

    BACKEND['pending'] = b""

    return True


def backendfileread(nbytes):

    infd = BACKEND.get('infd') if BACKEND else None

    if not infd:

        return None

    try:

        return os.read(infd, int(nbytes))

    except Exception:

        return None


def backendfilepoll(timeout):

    infd = BACKEND.get('infd') if BACKEND else None

    if not infd:

        time.sleep(timeout)

        return False

    try:

        r, _, _ = select.select([infd], [], [], timeout)

        return bool(r)

    except Exception:

        return False


def backendfilectl(cmd, args):

    ctlfd = BACKEND.get('alsactlfd') if BACKEND else None

    if ctlfd and cmd in ('gain', 'mute'):

        gain = float(args.get('gain', MASTERGAIN))

        mute = bool(args.get('mute', MASTERMUTE))

        if cmd == 'gain':

            mute = bool(MASTERMUTE)

        if cmd == 'mute':

            gain = float(MASTERGAIN)

        return alsaapplymixer(ctlfd, gain=gain, mute=mute)

    ctlpath = BACKEND.get('ctl') if BACKEND else None

    if not ctlpath:

        return False

    msg = {}

    msg['cmd'] = cmd

    outputargs = dict(args or {})

    if cmd in ('gain', 'mute'):
        outputargs['gain'] = mastergainmultiplier(outputargs.get('gain', MASTERGAIN))

    msg['args'] = outputargs

    msg['time'] = timestamp()

    try:

        with open(ctlpath, 'w') as f:
            json.dump(msg, f)

        return True

    except Exception:

        return False


def backendhdaopen(dev):

    global BACKEND

    backend = {}

    backend['type'] = 'hda'

    backend['dev'] = dev

    backend['ready'] = False

    backend['pci'] = None

    backend['mmio'] = None

    backend['ctl'] = None

    backend['streams'] = {}

    backend['streamnext'] = 1

    cfg = devcaps(dev).get('hda', {})

    backend['cfg'] = cfg

    pci = pciopen(cfg)

    if not pci:

        BACKEND = backend

        return False

    backend['pci'] = pci

    mmio = mmioopen(cfg)

    if not mmio:

        pciclose(pci)

        BACKEND = backend

        return False

    backend['mmio'] = mmio

    ok = hdactlinit(backend)

    if not ok:

        mmioclose(mmio)

        pciclose(pci)

        BACKEND = backend

        return False

    ok = hdacodecinit(backend)

    if not ok:

        mmioclose(mmio)

        pciclose(pci)

        BACKEND = backend

        return False

    ok = hdastreaminit(backend)

    if not ok:

        mmioclose(mmio)

        pciclose(pci)

        BACKEND = backend

        return False

    backend['ready'] = True

    dev['ready'] = True

    BACKEND = backend

    devlistemit()

    return True


def backendhdaclose():

    global BACKEND

    if not BACKEND:

        return

    try:

        hdastreamshutdown(BACKEND)

    except Exception:

        pass

    try:

        if BACKEND.get('mmio'):
            mmioclose(BACKEND['mmio'])

    except Exception:

        pass

    try:

        if BACKEND.get('pci'):
            pciclose(BACKEND['pci'])

    except Exception:

        pass

    BACKEND = None


def backendhdawrite(pcmbytes):

    if not BACKEND:

        return False

    return hdastreamwrite(BACKEND, pcmbytes)


def backendhdaread(nbytes):

    return None


def backendhdactl(cmd, args):

    if not BACKEND:

        return False

    if cmd == 'reset':

        return hdactlreset(BACKEND)

    if cmd == 'mute':

        return hdacodecmute(BACKEND, bool(args.get('mute')))

    if cmd == 'gain':

        return hdacodecgain(BACKEND, float(args.get('gain', 1.0)))

    return False


def backendhdapoll(timeout):

    time.sleep(timeout)

    return False


# pci functions
def pciopen(cfg):

    pci = {}

    pci['bdf'] = cfg.get('bdf')

    pci['vendor'] = cfg.get('vendor')

    pci['device'] = cfg.get('device')

    pci['bars'] = cfg.get('bars', {})

    pci['ready'] = False

    if not pci['bars']:

        return None

    pci['ready'] = True

    return pci


def pciclose(pci):

    return True


def pcibar(pci, index):

    bars = pci.get('bars', {}) if pci else {}

    key = str(index)

    if key in bars:

        return bars[key]

    return None



# mmio functions
def mmioopen(cfg):

    mmio = {}

    mmio['path'] = cfg.get('mmio')

    mmio['fd'] = None

    mmio['size'] = int(cfg.get('mmiosize', 0))

    mmio['ready'] = False

    if not mmio['path']:

        return None

    if mmio['size'] <= 0:

        return None

    try:

        mmio['fd'] = os.open(mmio['path'], os.O_RDWR)

    except Exception:

        mmio['fd'] = None

    if not mmio['fd']:

        return None

    mmio['ready'] = True

    return mmio


def mmioclose(mmio):

    fd = mmio.get('fd') if mmio else None

    if not fd:

        return False

    try:

        os.close(fd)

        return True

    except Exception:

        return False


def mmioread(mmio, off, n):

    fd = mmio.get('fd') if mmio else None

    if not fd:

        return None

    try:

        os.lseek(fd, int(off), os.SEEK_SET)

        return os.read(fd, int(n))

    except Exception:

        return None


def mmiowrite(mmio, off, data):

    fd = mmio.get('fd') if mmio else None

    if not fd:

        return False

    try:

        os.lseek(fd, int(off), os.SEEK_SET)

        os.write(fd, data)

        return True

    except Exception:

        return False


def mmioread32(mmio, off):

    data = mmioread(mmio, off, 4)

    if not data or len(data) != 4:

        return None

    return struct.unpack_from('<I', data, 0)[0]


def mmiowrite32(mmio, off, val):

    data = struct.pack('<I', int(val) & 0xFFFFFFFF)

    return mmiowrite(mmio, off, data)


# hda controller functions
def hdactlinit(backend):

    mmio = backend.get('mmio')

    if not mmio:

        return False

    ok = hdactlreset(backend)

    if not ok:

        return False

    return True


def hdactlreset(backend):

    mmio = backend.get('mmio')

    if not mmio:

        return False

    # HDA global register offsets
    REG_GCAP = 0x00

    REG_GCTL = 0x08

    REG_STATESTS = 0x0E

    REG_INTCTL = 0x20

    REG_INTSTS = 0x24

    REG_CORBLBASE = 0x40

    REG_CORBUBASE = 0x44

    REG_CORBWP = 0x48

    REG_CORBRP = 0x4A

    REG_CORBCTL = 0x4C

    REG_CORBSTS = 0x4D

    REG_CORBSIZE = 0x4E

    REG_RIRBLBASE = 0x50

    REG_RIRBUBASE = 0x54

    REG_RIRBWP = 0x58

    REG_RINTCNT = 0x5A

    REG_RIRBCTL = 0x5C

    REG_RIRBSTS = 0x5D

    REG_RIRBSIZE = 0x5E

    REG_DPLBASE = 0x70

    REG_DPUBASE = 0x74

    GCTL_CRST = 0x00000001

    CORBCTL_RUN = 0x02

    RIRBCTL_RUN = 0x02

    RIRBCTL_DMARUN = 0x02

    RIRBCTL_IRQEN = 0x01

    CORBSTS_MEI = 0x01

    RIRBSTS_RINT = 0x01

    RIRBSTS_OIS = 0x04

    # read capabilities once
    gcap = mmioread32(mmio, REG_GCAP)

    if gcap is None:

        return False

    backend['hdacap'] = int(gcap)

    # stop interrupts while reinitializing
    mmiowrite32(mmio, REG_INTCTL, 0)

    mmioread32(mmio, REG_INTSTS)

    # stop CORB/RIRB if they were running
    corbctl = mmioread(mmio, REG_CORBCTL, 1)

    if corbctl and len(corbctl) == 1:

        mmiowrite(mmio, REG_CORBCTL, bytes([corbctl[0] & (~CORBCTL_RUN)]))

    rirbctl = mmioread(mmio, REG_RIRBCTL, 1)

    if rirbctl and len(rirbctl) == 1:

        mmiowrite(mmio, REG_RIRBCTL, bytes([rirbctl[0] & (~RIRBCTL_RUN)]))

    # global reset: clear CRST, then set CRST, with timeouts
    gctl = mmioread32(mmio, REG_GCTL)

    if gctl is None:

        return False

    mmiowrite32(mmio, REG_GCTL, int(gctl) & (~GCTL_CRST))


    t0 = time.time()

    while True:

        gctl = mmioread32(mmio, REG_GCTL)

        if gctl is None:

            return False

        if (int(gctl) & GCTL_CRST) == 0:

            break

        if (time.time() - t0) > 1.0:

            return False

        time.sleep(0.001)

    mmiowrite32(mmio, REG_GCTL, int(gctl) | GCTL_CRST)

    t0 = time.time()

    while True:

        gctl = mmioread32(mmio, REG_GCTL)

        if gctl is None:

            return False

        if (int(gctl) & GCTL_CRST) != 0:

            break

        if (time.time() - t0) > 1.0:

            return False

        time.sleep(0.001)

    # wait for codec presence bits to settle (STATESTS, 16-bit)
    t0 = time.time()

    while True:

        sts = mmioread(mmio, REG_STATESTS, 2)

        if sts and len(sts) == 2:

            statests = struct.unpack_from('<H', sts, 0)[0]

            backend['hdastatests'] = int(statests)

            break

        if (time.time() - t0) > 0.1:

            backend['hdastatests'] = 0

            break

        time.sleep(0.001)

    # CORB/RIRB/DMA base addresses must be provided by your device node caps
    cfg = backend.get('cfg', {})

    corb = cfg.get('corb', {})

    rirb = cfg.get('rirb', {})

    dmapos = cfg.get('dmapos', {})

    corbl = int(corb.get('base_lo', 0))

    corbu = int(corb.get('base_hi', 0))

    rirbl = int(rirb.get('base_lo', 0))

    rirbu = int(rirb.get('base_hi', 0))

    dpl = int(dmapos.get('base_lo', 0))

    dpu = int(dmapos.get('base_hi', 0))

    if corbl and rirbl:

        mmiowrite32(mmio, REG_CORBLBASE, corbl)

        mmiowrite32(mmio, REG_CORBUBASE, corbu)

        mmiowrite32(mmio, REG_RIRBLBASE, rirbl)

        mmiowrite32(mmio, REG_RIRBUBASE, rirbu)

        # choose 256 entries where possible (size enc: 0=2,1=16,2=256)
        mmiowrite(mmio, REG_CORBSIZE, bytes([0x02]))

        mmiowrite(mmio, REG_RIRBSIZE, bytes([0x02]))

        # reset CORBWP to 0 (16-bit)
        mmiowrite(mmio, REG_CORBWP, struct.pack('<H', 0))

        # reset CORBRP by setting bit15 then clearing it (16-bit)
        mmiowrite(mmio, REG_CORBRP, struct.pack('<H', 0x8000))

        mmiowrite(mmio, REG_CORBRP, struct.pack('<H', 0x0000))

        # clear CORB status
        mmiowrite(mmio, REG_CORBSTS, bytes([CORBSTS_MEI]))

        # reset RIRB write pointer (16-bit write)
        mmiowrite(mmio, REG_RIRBWP, struct.pack('<H', 0))

        # set response interrupt count (16-bit), 1 means interrupt per response
        mmiowrite(mmio, REG_RINTCNT, struct.pack('<H', 1))

        # clear RIRB status flags
        mmiowrite(mmio, REG_RIRBSTS, bytes([RIRBSTS_RINT | RIRBSTS_OIS]))

        # start CORB DMA
        corbctl = mmioread(mmio, REG_CORBCTL, 1)

        if corbctl and len(corbctl) == 1:

            mmiowrite(mmio, REG_CORBCTL, bytes([corbctl[0] | CORBCTL_RUN]))

        # start RIRB DMA + enable interrupts from RIRB
        rirbctl = mmioread(mmio, REG_RIRBCTL, 1)

        if rirbctl and len(rirbctl) == 1:

            mmiowrite(mmio, REG_RIRBCTL, bytes([(rirbctl[0] | RIRBCTL_DMARUN | RIRBCTL_IRQEN)]))

    if dpl:

        mmiowrite32(mmio, REG_DPLBASE, dpl)

        mmiowrite32(mmio, REG_DPUBASE, dpu)

    # leave controller interrupts disabled for now (enable once stream IRQ plumbing exists)
    mmiowrite32(mmio, REG_INTCTL, 0)

    mmioread32(mmio, REG_INTSTS)


    backend['hdactlready'] = True

    return True


def hdactlsetformat(backend, samplerate, channels, fmt):

    mmio = backend.get('mmio')

    hda = backend.get('hda')

    if not mmio or not hda:

        return False

    out = hda.get('out')

    if not out:

        return False

    base = out.get('base')

    if base is None:

        return False

    # stream descriptor format register is 16-bit at SD_FMT (offset 0x12)
    SD_FMT = 0x12

    # build HDA stream format word
    # channels field: (channels - 1) in bits 0..3
    ch = int(channels)

    if ch < 1:

        ch = 1

    if ch > 16:

        ch = 16

    chbits = (ch - 1) & 0x0F

    # bits per sample encoding (common)
    bps = int(fmt)

    if bps == 8:

        bpsbits = 0x0

    elif bps == 16:

        bpsbits = 0x1

    elif bps == 20:

        bpsbits = 0x2

    elif bps == 24:

        bpsbits = 0x3

    elif bps == 32:

        bpsbits = 0x4

    else:

        bpsbits = 0x1

        bps = 16

    # sample rate encoding (base 48k with mul/div) – support the common ones
    sr = int(samplerate)

    if sr == 48000:

        srbase = 0

        srmul = 0

        srdiv = 0

    elif sr == 44100:

        srbase = 1

        srmul = 0

        srdiv = 0

    elif sr == 96000:

        srbase = 0

        srmul = 1

        srdiv = 0

    elif sr == 192000:

        srbase = 0

        srmul = 3

        srdiv = 0

    else:

        srbase = 0

        srmul = 0

        srdiv = 0

        sr = 48000

    # HDA format bit packing:
    # bits 0..3: channels-1
    # bits 4..6: bits-per-sample encoding
    # bit 7: reserved
    # bits 8..10: sample rate divisor
    # bits 11..13: sample rate multiplier
    # bit 14: base rate (0=48k, 1=44.1k)
    # bit 15: reserved
    fmtword = 0

    fmtword |= chbits

    fmtword |= (bpsbits & 0x07) << 4

    fmtword |= (srdiv & 0x07) << 8

    fmtword |= (srmul & 0x07) << 11

    fmtword |= (srbase & 0x01) << 14

    # write to SD_FMT
    mmiowrite(mmio, base + SD_FMT, struct.pack('<H', fmtword))

    # store for later (codec programming will also need this)
    hda['samplerate'] = sr

    hda['channels'] = ch

    hda['format'] = bps

    hda['fmtword'] = int(fmtword)

    return True


def hdactlstart(backend):

    mmio = backend.get('mmio')

    hda = backend.get('hda')

    if not mmio or not hda:

        return False

    out = hda.get('out')

    if not out:

        return False

    base = out.get('base')

    if base is None:

        return False

    # stream descriptor offsets
    SD_CTL = 0x00

    SD_STS = 0x03

    SDCTL_RUN = 0x00000002

    SDCTL_SRST = 0x00000001

    # clear stream status byte
    mmiowrite(mmio, base + SD_STS, bytes([0x1C]))

    # ensure stream is out of reset
    ctl = mmioread32(mmio, base + SD_CTL)

    if ctl is None:

        return False

    if (int(ctl) & SDCTL_SRST) == 0:

        mmiowrite32(mmio, base + SD_CTL, int(ctl) | SDCTL_SRST)

        t0 = time.time()

        while True:

            ctl = mmioread32(mmio, base + SD_CTL)

            if ctl is None:

                return False

            if (int(ctl) & SDCTL_SRST) != 0:

                break

            if (time.time() - t0) > 0.05:

                return False

            time.sleep(0.001)

    # set RUN
    ctl = mmioread32(mmio, base + SD_CTL)

    if ctl is None:

        return False

    if (int(ctl) & SDCTL_RUN) == 0:

        mmiowrite32(mmio, base + SD_CTL, int(ctl) | SDCTL_RUN)

    hda['playing'] = True

    return True


def hdactlstop(backend):

    mmio = backend.get('mmio')

    hda = backend.get('hda')

    if not mmio or not hda:

        return False

    out = hda.get('out')

    if not out:

        return False

    base = out.get('base')

    if base is None:

        return False

    SD_CTL = 0x00

    SDCTL_RUN = 0x00000002

    ctl = mmioread32(mmio, base + SD_CTL)

    if ctl is None:

        return False

    if (int(ctl) & SDCTL_RUN) != 0:

        mmiowrite32(mmio, base + SD_CTL, int(ctl) & (~SDCTL_RUN))

    hda['playing'] = False

    return True


# hda codec functions
def hdacodecinit(backend):

    mmio = backend.get('mmio')

    if not mmio:

        return False

    cfg = backend.get('cfg', {})

    corb = cfg.get('corb', {})

    rirb = cfg.get('rirb', {})

    corbpath = corb.get('path')

    rirbpath = rirb.get('path')

    if not corbpath or not rirbpath:

        return False

    # HDA global register offsets used by verb path
    REG_STATESTS = 0x0E

    REG_CORBWP = 0x48

    REG_CORBRP = 0x4A

    REG_RIRBWP = 0x58

    # open CORB/RIRB memory nodes once (T1OS nodes)
    corbfd = backend.get('corbfd')

    if not corbfd:

        try:

            corbfd = os.open(corbpath, os.O_RDWR)

        except Exception:

            corbfd = None

        if not corbfd:

            return False

        backend['corbfd'] = corbfd


    rirbfd = backend.get('rirbfd')

    if not rirbfd:

        try:

            rirbfd = os.open(rirbpath, os.O_RDWR)

        except Exception:

            rirbfd = None

        if not rirbfd:

            return False

        backend['rirbfd'] = rirbfd

    # discover present codecs (bitmask)
    statests = backend.get('hdastatests')

    if statests is None:

        sts = mmioread(mmio, REG_STATESTS, 2)

        if sts and len(sts) == 2:

            statests = struct.unpack_from('<H', sts, 0)[0]

        else:

            statests = 0

        backend['hdastatests'] = int(statests)

    cads = []

    i = 0

    while i < 16:

        if (int(statests) >> i) & 1:

            cads.append(i)

        i += 1

    if not cads:

        return False

    # pick first codec as default output target
    cad = int(cfg.get('cad', cads[0]))

    if cad not in cads:

        cad = cads[0]

    backend['hdacad'] = cad

    # reset our software read pointers
    backend['rirbrp'] = 0

    backend['corbwp'] = 0

    # query vendor/device id from root node (nid 0)
    vid = hdacodecverb(backend, cad=cad, nid=0, verb=0xF00, payload=0x00)

    if vid is None:

        return False

    backend['hdavid'] = int(vid)

    # find the first audio function group
    sub = hdacodecverb(backend, cad=cad, nid=0, verb=0xF00, payload=0x04)

    if sub is None:

        return False

    startnid = (int(sub) >> 16) & 0xFF

    count = int(sub) & 0xFF

    if count <= 0:

        return False

    fgnid = None

    n = startnid

    end = startnid + count

    while n < end:

        fgt = hdacodecverb(backend, cad=cad, nid=n, verb=0xF00, payload=0x05)

        if fgt is not None:

            if (int(fgt) & 0xFF) == 0x01:

                fgnid = n

                break

        n += 1

    if fgnid is None:

        return False

    backend['hdafgnid'] = int(fgnid)

    # enumerate widgets under the function group
    sub = hdacodecverb(backend, cad=cad, nid=fgnid, verb=0xF00, payload=0x04)

    if sub is None:

        return False

    wstart = (int(sub) >> 16) & 0xFF

    wcount = int(sub) & 0xFF

    if wcount <= 0:

        return False


    pins = []

    outs = []

    # widget capabilities param: 0x09
    # audio widget type lives in bits 20..23 of the cap dword (per HDA spec)
    w = wstart

    wend = wstart + wcount

    while w < wend:

        cap = hdacodecverb(backend, cad=cad, nid=w, verb=0xF00, payload=0x09)

        if cap is not None:

            wtype = (int(cap) >> 20) & 0x0F

            if wtype == 0x04:

                pins.append(w)

            if wtype == 0x02:

                outs.append(w)

        w += 1

    backend['hdapins'] = pins

    backend['hdaouts'] = outs

    # pick an output amplifier target:
    # prefer an output widget if present, else a pin widget
    ampnid = None

    if outs:

        ampnid = outs[0]

    elif pins:

        ampnid = pins[0]

    backend['hdaampnid'] = ampnid

    # initialize mute off + nominal gain
    ok = hdacodecmute(backend, False)

    if not ok:

        return False

    ok = hdacodecgain(backend, 1.0)

    if not ok:

        return False

    return True


def hdacodecverb(backend, cad, nid, verb, payload):

    mmio = backend.get('mmio')

    if not mmio:

        return None

    corbfd = backend.get('corbfd')

    rirbfd = backend.get('rirbfd')

    if not corbfd or not rirbfd:

        return None

    # HDA register offsets
    REG_CORBWP = 0x48

    REG_CORBRP = 0x4A

    REG_RIRBWP = 0x58

    # build 32-bit verb: cad[31:28], nid[27:20], verb[19:8], payload[7:0]
    cmd = 0

    cmd |= (int(cad) & 0x0F) << 28

    cmd |= (int(nid) & 0xFF) << 20

    cmd |= (int(verb) & 0x0FFF) << 8

    cmd |= int(payload) & 0xFF

    # advance CORB write pointer
    wp = backend.get('corbwp')

    if wp is None:

        wp = 0

    wp = int(wp) & 0xFF

    # write command into CORB memory
    try:

        os.lseek(corbfd, wp * 4, os.SEEK_SET)

        os.write(corbfd, struct.pack('<I', cmd))

    except Exception:

        return None

    # post write pointer to hardware (8-bit in CORBWP low byte)
    mmiowrite(mmio, REG_CORBWP, bytes([wp & 0xFF, 0x00]))

    # wait for response by watching RIRBWP change
    t0 = time.time()

    lastwp = backend.get('last_rirbwp')

    if lastwp is None:

        last = mmioread(mmio, REG_RIRBWP, 2)

        if last and len(last) == 2:

            lastwp = struct.unpack_from('<H', last, 0)[0] & 0xFF

        else:

            lastwp = 0

    lastwp = int(lastwp) & 0xFF

    while True:

        cur = mmioread(mmio, REG_RIRBWP, 2)

        if cur and len(cur) == 2:

            curwp = struct.unpack_from('<H', cur, 0)[0] & 0xFF

        else:

            curwp = lastwp

        if curwp != lastwp:

            backend['last_rirbwp'] = int(curwp)

            break

        if (time.time() - t0) > 0.05:

            return None

        time.sleep(0.001)

    # RIRB entry is 8 bytes: resp (dword), resp_ex (dword)
    # the hardware write pointer indicates the last valid entry index
    idx = backend.get('last_rirbwp')

    if idx is None:

        return None

    idx = int(idx) & 0xFF

    try:

        os.lseek(rirbfd, idx * 8, os.SEEK_SET)

        entry = os.read(rirbfd, 8)

    except Exception:

        return None

    if not entry or len(entry) != 8:

        return None

    resp = struct.unpack_from('<I', entry, 0)[0]

    resp_ex = struct.unpack_from('<I', entry, 4)[0]

    # basic sanity: top nibble of resp_ex often contains the codec address in some implementations
    # keep it lenient; return resp regardless
    backend['last_resp_ex'] = int(resp_ex)

    # update software CORBWP
    backend['corbwp'] = (wp + 1) & 0xFF

    return int(resp)


def hdacodecmute(backend, mute):

    cad = backend.get('hdacad')

    nid = backend.get('hdaampnid')

    if cad is None or nid is None:

        return False

    # Set Amplifier Gain/Mute verb (0x300)
    # payload fields (common): [7] mute, [6:0] gain steps; we also need to target L/R and output amp
    # This is a minimal, widely-tolerated encoding: set output amp, left+right, index 0.
    #
    # payload bits (typical):
    # bit 15: set left
    # bit 14: set right
    # bit 13: output (1) / input (0)
    # bits 12..8: input index (0 for output amp on many widgets)
    # bit 7: mute
    # bits 6..0: gain
    #
    # We keep gain from stored state if present.
    gainstep = backend.get('hdagainstep')

    if gainstep is None:

        gainstep = 0x3F

    gainstep = int(gainstep) & 0x7F

    payload = 0

    payload |= 1 << 15

    payload |= 1 << 14

    payload |= 1 << 13

    payload |= (0 & 0x1F) << 8

    if bool(mute):

        payload |= 1 << 7

    payload |= gainstep & 0x7F

    resp = hdacodecverb(backend, cad=cad, nid=nid, verb=0x300, payload=payload & 0xFF)

    if resp is None:

        # some codecs require the full 16-bit payload via multiple verbs; keep minimal for now
        return False

    backend['hdamute'] = bool(mute)

    return True


def hdacodecgain(backend, gain):

    cad = backend.get('hdacad')

    nid = backend.get('hdaampnid')

    if cad is None or nid is None:

        return False

    g = float(gain)

    if g < 0.0:

        g = 0.0

    if g > 1.0:

        g = 1.0

    # map 0.0..1.0 to 0..0x3F (common step range)
    step = int(round(g * 63.0))

    if step < 0:

        step = 0

    if step > 0x3F:

        step = 0x3F

    backend['hdagainstep'] = int(step)

    # preserve mute state if set
    mute = bool(backend.get('hdamute', False))

    payload = 0

    payload |= 1 << 15

    payload |= 1 << 14

    payload |= 1 << 13

    payload |= (0 & 0x1F) << 8

    if mute:

        payload |= 1 << 7

    payload |= int(step) & 0x7F

    resp = hdacodecverb(backend, cad=cad, nid=nid, verb=0x300, payload=payload & 0xFF)

    if resp is None:

        return False

    return True


def hdastreaminit(backend):

    backend['hda'] = {}

    backend['hda']['samplerate'] = DEFAULTSR

    backend['hda']['channels'] = DEFAULTCH

    backend['hda']['format'] = DEFAULTFMT

    backend['hda']['playing'] = False

    backend['hda']['pos'] = 0

    bufsec = float(getconfig().get('hdabufsec', 2.0))

    if bufsec < 0.25:

        bufsec = 0.25

    rbsize = int(DEFAULTSR * DEFAULTCH * 2 * bufsec)

    framesize = int(DEFAULTCH * 2)

    rbsize = int(rbsize - (rbsize % framesize))

    backend['hda']['rb'] = rbnew(rbsize)

    return True


def hdastreamshutdown(backend):

    mmio = backend.get('mmio')

    hda = backend.get('hda')

    if not hda:

        return True

    # stop DMA stream if it is running
    if mmio and hda.get('out'):

        out = hda.get('out')

        base = out.get('base')

        if base is not None:

            SD_CTL = 0x00
            SD_STS = 0x03

            SDCTL_RUN = 0x00000002

            ctl = mmioread32(mmio, base + SD_CTL)

            if ctl is not None:

                if (int(ctl) & SDCTL_RUN) != 0:

                    mmiowrite32(mmio, base + SD_CTL, int(ctl) & (~SDCTL_RUN))


            # clear stream status bits (BCIS/FIFOE/DES typically)
            mmiowrite(mmio, base + SD_STS, bytes([0x1C]))

    # close any DMA buffer handle we opened
    out = hda.get('out')

    if out:

        bufd = out.get('bufd')

        if bufd:

            try:

                os.close(bufd)

            except Exception:

                pass

            out['bufd'] = None

        # drop stream fields
        out['wp'] = 0

    # reset software playback state
    hda['playing'] = False

    hda['pos'] = 0

    # empty ringbuffer contents if present
    rb = hda.get('rb')

    if rb:

        used = rbavail(rb)

        if used and used > 0:

            rbpop(rb, used)

    return True


def hdastreamwrite(backend, pcmbytes):

    hda = backend.get('hda')

    if not hda:

        return False

    rb = hda.get('rb')

    if not rb:

        return False

    if rbspace(rb) < len(pcmbytes):

        return False

    rbpush(rb, pcmbytes)

    return hdastreampump(backend)


def hdastreampump(backend):

    mmio = backend.get('mmio')

    hda = backend.get('hda')

    if not mmio or not hda:

        return False

    rb = hda.get('rb')

    if not rb:

        return False

    out = hda.get('out')

    if not out:

        return False

    # constants (HDA stream descriptor register offsets)
    SD_CTL = 0x00

    SD_STS = 0x03

    SD_LPIB = 0x04

    SD_CBL = 0x08

    SD_LVI = 0x0C

    SD_FMT = 0x12

    SD_BDPL = 0x18

    SD_BDPU = 0x1C

    SDCTL_RUN = 0x00000002

    # required stream fields
    base = out.get('base', None)

    bufpath = out.get('bufpath', None)

    bufsize = int(out.get('bufsize', 0))

    fragsize = int(out.get('fragsize', 0))

    framesize = int(out.get('framesize', 0))

    wp = int(out.get('wp', 0))

    if base is None or not bufpath or bufsize <= 0 or fragsize <= 0 or framesize <= 0:

        return False

    # open DMA buffer file once (T1OS node, not /dev)
    bufd = out.get('bufd')

    if not bufd:

        try:

            bufd = os.open(bufpath, os.O_RDWR)

        except Exception:

            bufd = None

        if not bufd:

            return False

        out['bufd'] = bufd

    # read hardware play position (LPIB) and clamp to buffer length
    rp = mmioread32(mmio, base + SD_LPIB)

    if rp is None:

        return False

    rp = int(rp) % bufsize

    # compute free space in cyclic DMA buffer without overwriting rp
    if wp >= rp:

        free = (bufsize - wp) + rp

    else:

        free = rp - wp

    if free > 0:

        free -= 1

    if free <= 0:

        return False

    # only write whole frames
    free -= (free % framesize)

    if free <= 0:

        return False

    # available bytes in ringbuffer
    avail = rbavail(rb)

    if avail <= 0:

        return False

    avail -= (avail % framesize)

    if avail <= 0:

        return False

    # choose how much to copy this pump
    todo = free

    if avail < todo:

        todo = avail

    if todo <= 0:

        return False

    # copy from rb into DMA buffer at wp (wrap-safe)
    first = todo

    if wp + first > bufsize:

        first = bufsize - wp

    first -= (first % framesize)

    if first < 0:

        first = 0

    second = todo - first

    second -= (second % framesize)

    if second < 0:

        second = 0

    if first:

        chunk = rbpop(rb, first)

        if not chunk or len(chunk) != first:

            return False

        ok = mmiowrite(out.get('bufmmio', None), 0, b"") if False else True

        if not ok:

            return False

        try:

            os.lseek(bufd, wp, os.SEEK_SET)

            os.write(bufd, chunk)

        except Exception:

            return False

        wp += first

        if wp >= bufsize:

            wp = 0

    if second:

        chunk = rbpop(rb, second)

        if not chunk or len(chunk) != second:

            return False

        try:

            os.lseek(bufd, wp, os.SEEK_SET)

            os.write(bufd, chunk)

        except Exception:

            return False

        wp += second

        if wp >= bufsize:

            wp %= bufsize

    out['wp'] = wp

    # keep a software position estimate (hardware consumes, we track rp)
    hda['pos'] = rp

    # auto-start stream once we have at least one fragment buffered
    if not hda.get('playing'):

        if wp >= rp:

            filled = wp - rp

        else:

            filled = (bufsize - rp) + wp

        if filled >= fragsize:

            ctl = mmioread32(mmio, base + SD_CTL)

            if ctl is None:

                return True

            if (int(ctl) & SDCTL_RUN) == 0:

                ctl = int(ctl) | SDCTL_RUN

                mmiowrite32(mmio, base + SD_CTL, ctl)

            hda['playing'] = True

    return True


def hdastreampos(backend):

    hda = backend.get('hda')

    if not hda:

        return 0

    return int(hda.get('pos', 0))


# ipc functions
def listen():

    global SERVERSOCK

    try:

        if os.path.exists(AUDIOSOCK):
            os.unlink(AUDIOSOCK)

    except Exception:

        pass

    SERVERSOCK = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

    previousmask = os.umask(0o117)
    try:
        SERVERSOCK.bind(AUDIOSOCK)
    finally:
        os.umask(previousmask)

    SERVERSOCK.listen(16)

    SERVERSOCK.setblocking(False)

    SEL.register(SERVERSOCK, selectors.EVENT_READ, accept)


def accept(sock):

    try:

        conn, _ = sock.accept()

    except Exception:

        return

    if len(CLIENTS) >= int(getconfig().get('maxclients', 32)):

        try:

            conn.close()

        except Exception:

            pass

        return

    conn.setblocking(False)

    fd = conn.fileno()

    pruneclosed(fd=fd)

    CLIENTS[fd] = {}

    CLIENTS[fd]['sock'] = conn

    CLIENTS[fd]['inbuf'] = b''

    CLIENTS[fd]['outbuf'] = b''

    CLIENTS[fd]['authed'] = False

    CLIENTS[fd]['subs'] = set()

    SEL.register(conn, selectors.EVENT_READ, readclient)


def updateclientevents(fd):

    client = CLIENTS.get(fd)

    if not client:

        return

    events = selectors.EVENT_READ

    if client.get('outbuf'):

        events |= selectors.EVENT_WRITE

    try:

        SEL.modify(client['sock'], events, readclient)

    except Exception:

        drop(fd)


def drop(fd):

    client = CLIENTS.get(fd)

    if not client:
        return

    for streamid in list(STREAMS.keys()):

        stream = STREAMS.get(streamid)

        if stream and int(stream.get('fd', -1)) == int(fd):

            streamfree(streamid, reason='disconnected', remember=False)

    pruneclosed(fd=fd)

    try:

        SEL.unregister(client['sock'])

    except BlockingIOError:

        pass

    except Exception:

        pass

    try:

        client['sock'].close()

    except Exception:

        pass

    del CLIENTS[fd]


def readclient(sock):

    fd = sock.fileno()

    client = CLIENTS.get(fd)

    if not client:
        drop(fd)
        return

    try:

        data = sock.recv(65536)

    except BlockingIOError:

        return

    except Exception:

        drop(fd)
        return

    if not data:

        drop(fd)
        return

    client['inbuf'] += data

    if len(client['inbuf']) > MAXMSG + HEADER_SIZE:

        drop(fd)

        return

    parse(fd)


def writeclient(sock):

    fd = sock.fileno()

    client = CLIENTS.get(fd)

    if not client:
        drop(fd)
        return

    outbuf = client.get('outbuf')

    if not outbuf:

        updateclientevents(fd)

        return

    try:

        sent = sock.send(outbuf)

        client['outbuf'] = outbuf[sent:]

        updateclientevents(fd)

    except BlockingIOError:

        return

    except Exception:

        drop(fd)


def send(fd, msgtype, payload, raw=None):

    client = CLIENTS.get(fd)

    if not client:
        return

    try:

        client['outbuf'] += packresponse(msgtype, payload, raw)

        updateclientevents(fd)

    except Exception:

        drop(fd)


def broadcast(msgtype, payload):

    for fd in list(CLIENTS.keys()):

        send(fd, msgtype, payload)


def parse(fd):

    client = CLIENTS.get(fd)

    if not client:
        return

    buf = client['inbuf']

    while True:

        if len(buf) < HEADER_SIZE:
            break

        try:

            magic, proto, mtype, flags, length = struct.unpack(
                '>4sBBHI',
                buf[:HEADER_SIZE]
            )

        except Exception:

            drop(fd)

            return

        if magic != MAGIC or proto != PROTO or int(length) > MAXMSG:

            drop(fd)

            return

        if len(buf) < HEADER_SIZE + length:
            break

        payload = buf[HEADER_SIZE:HEADER_SIZE + length]

        buf = buf[HEADER_SIZE + length:]

        if mtype == MSGSTREAMWRITE:

            if len(payload) < 4:

                data = None

                raw = payload

            else:

                jlen = struct.unpack('>I', payload[:4])[0]

                if jlen > len(payload) - 4:

                    data = None

                    raw = payload

                else:

                    jblob = payload[4:4 + jlen]

                    raw = payload[4 + jlen:]

                    try:

                        data = json.loads(jblob.decode('utf-8'))

                    except Exception:

                        data = None

        else:

            try:

                data = json.loads(payload.decode('utf-8'))

                raw = None

            except Exception:

                data = None

                raw = payload

        client['inbuf'] = buf

        handlemessage(fd, mtype, data, raw)

    client['inbuf'] = buf


# protocol functions
def handlemessage(fd, mtype, payload, raw):

    if mtype == MSGHELLO:

        handlehello(fd, payload)

        return

    if mtype == MSGPING:

        handleping(fd, payload)

        return

    if mtype == MSGCONFIG:

        handleconfig(fd, payload)

        return

    if mtype == MSGDEVLIST:

        handledevlist(fd, payload)

        return

    if mtype == MSGDEVSET:

        handledevset(fd, payload)

        return

    if mtype == MSGSTREAMOPEN:

        handlestreamopen(fd, payload)

        return

    if mtype == MSGSTREAMCLOSE:

        handlestreamclose(fd, payload)

        return

    if mtype == MSGSTREAMWRITE:

        handlestreamwrite(fd, payload, raw)

        return

    if mtype == MSGSTREAMREAD:

        handlestreamread(fd, payload)

        return

    if mtype == MSGSTREAMSTATUS:

        handlestreamstatus(fd, payload)

        return

    if mtype == MSGSTREAMCONTROL:

        handlestreamcontrol(fd, payload)

        return

    if mtype == MSGVOLUME:

        handlevolume(fd, payload)

        return

    if mtype == MSGMUTE:

        handlemute(fd, payload)

        return

    if mtype == MSGSUBSCRIBE:

        handlesubscribe(fd, payload)

        return

    send(fd, MSGERROR, {'error': 'unknown message'})


def handlehello(fd, payload):

    client = CLIENTS.get(fd)

    if client:

        client['authed'] = True

    resp = {}

    resp['server'] = 'audioserver'

    resp['time'] = timestamp()

    resp['protocol'] = PROTO

    resp['capabilities'] = {
        'write_ack': True,
        'stream_status': True,
        'drain_close': True,
        'negotiated_samplerate': True,
        'presented_progress': True,
    }

    send(fd, MSGHELLO, resp)


def handleping(fd, payload):

    send(fd, MSGPING, {'time': timestamp()})


def handleconfig(fd, payload):

    if not payload:

        cfg = getconfig()

        cfg['mastergain'] = float(MASTERGAIN)

        cfg['mastermute'] = bool(MASTERMUTE)

        send(fd, MSGCONFIG, cfg)

        return

    cfg = getconfig()

    cfg = mergeconfig(cfg, payload)

    applyconfig(cfg)

    saveconfig(cfg)

    send(fd, MSGCONFIG, cfg)


def handledevlist(fd, payload):

    scan()

    resp = {}

    resp['devices'] = devlist()

    resp['active'] = ACTIVEDEV.get('id') if ACTIVEDEV else None

    send(fd, MSGDEVLIST, resp)


def handledevset(fd, payload):

    if not payload or 'id' not in payload:

        send(fd, MSGERROR, {'error': 'missing device id'})
        return

    ok = devset(payload['id'])

    if not ok:

        send(fd, MSGERROR, {'error': 'device not found'})
        return

    send(fd, MSGDEVSET, {'active': payload['id']})


def handlestreamopen(fd, payload):

    if not payload:

        payload = {}

    streamid = streamnew(fd, payload)

    if not streamid:

        send(fd, MSGERROR, {'error': 'cannot open stream'})
        return

    stream = STREAMS.get(streamid)

    send(fd, MSGSTREAMOPEN, {
        'stream': streamid,
        'format': dict(stream.get('format', {})),
        'capacity': int(stream.get('rb', {}).get('size', 0)),
        'prebuffer': int(stream.get('prebuffer', 0)),
        'latency_class': str(stream.get('latency_class', 'resilient')),
        'write_ack': bool(stream.get('write_ack', False)),
    })


def handlestreamclose(fd, payload):

    if not payload or 'stream' not in payload:

        send(fd, MSGERROR, {'error': 'missing stream id'})
        return

    try:

        streamid = int(payload['stream'])

    except Exception:

        send(fd, MSGERROR, {'error': 'invalid stream id'})

        return

    stream = STREAMS.get(streamid)

    if not stream or int(stream.get('fd', -1)) != int(fd):

        closed = closedstreamget(fd, streamid)

        if closed:

            send(fd, MSGSTREAMCLOSE, closed)

        else:

            send(fd, MSGERROR, {'error': 'stream not found'})

        return

    drain = bool(payload.get('drain', True))

    if not drain:

        closed = streamfree(streamid, reason='aborted')

        send(fd, MSGSTREAMCLOSE, closed)

        return

    stream['closing'] = True

    stream['state'] = 'paused' if stream.get('paused') else 'draining'

    if rbavail(stream.get('rb')) <= 0 and streamdrained(stream):

        closed = streamfree(streamid, reason='drained')

        send(fd, MSGSTREAMCLOSE, closed)

        return

    send(fd, MSGSTREAMCLOSE, streamstatusdata(stream))


def handlestreamwrite(fd, payload, raw):

    if not payload or 'stream' not in payload or not raw:

        send(fd, MSGERROR, {'error': 'invalid stream write'})

        return

    try:

        streamid = int(payload['stream'])

    except Exception:

        send(fd, MSGERROR, {'error': 'invalid stream id'})

        return

    stream = STREAMS.get(streamid)

    if not stream or int(stream.get('fd', -1)) != int(fd):

        send(fd, MSGERROR, {'error': 'stream not found'})

        return

    if stream.get('closing'):

        send(fd, MSGERROR, {'error': 'stream is closing'})

        return

    if len(raw) % FRAMEBYTES:

        send(fd, MSGERROR, {'error': 'unaligned stream write'})

        return

    ok = streampush(streamid, raw)

    if ok:

        # prove non-zero PCM is arriving
        stream['inbytes'] += len(raw)

        m, r = pcmstats(raw, maxsamples=2048)

        stream['inmax'] = m

        stream['inrms'] = r

        t = time.time()

        if (
            t - float(stream.get('lastinlog', 0.0))
        ) > AUDIOTELEMETRYINTERVAL:

            log(f'stream {streamid} write bytes={len(raw)} inbytes={stream["inbytes"]} max={m} rms={r:.1f}')

            stream['lastinlog'] = t

        if stream.get('write_ack'):

            response = streamstatusdata(stream)
            response.update({
                'ok': True,
                'accepted': len(raw),
            })
            send(fd, MSGSTREAMWRITE, response)

        return

    if not ok:

        if stream.get('write_ack'):

            response = streamstatusdata(stream)
            response.update({
                'ok': False,
                'accepted': 0,
            })
            send(fd, MSGSTREAMWRITE, response)

            return

        send(fd, MSGERROR, {'error': 'stream write failed'})


def handlestreamread(fd, payload):

    send(fd, MSGERROR, {'error': 'capture not implemented'})


def handlestreamstatus(fd, payload):

    if not payload or 'stream' not in payload:

        send(fd, MSGERROR, {'error': 'missing stream id'})

        return

    try:

        streamid = int(payload['stream'])

    except Exception:

        send(fd, MSGERROR, {'error': 'invalid stream id'})

        return

    stream = STREAMS.get(streamid)

    if stream and int(stream.get('fd', -1)) == int(fd):

        if stream.get('closing') and rbavail(stream.get('rb')) <= 0 and streamdrained(stream):

            closed = streamfree(streamid, reason='drained')
            send(fd, MSGSTREAMSTATUS, closed)

            return

        send(fd, MSGSTREAMSTATUS, streamstatusdata(stream))

        return

    closed = closedstreamget(fd, streamid)

    if closed:

        send(fd, MSGSTREAMSTATUS, closed)

        return

    send(fd, MSGERROR, {'error': 'stream not found'})


def handlestreamcontrol(fd, payload):

    if (
        not payload
        or 'stream' not in payload
        or ('paused' not in payload and 'muted' not in payload)
    ):

        send(fd, MSGERROR, {'error': 'invalid stream control'})
        return

    try:

        streamid = int(payload['stream'])

    except Exception:

        send(fd, MSGERROR, {'error': 'invalid stream id'})
        return

    stream = STREAMS.get(streamid)

    if not stream or int(stream.get('fd', -1)) != int(fd):

        send(fd, MSGERROR, {'error': 'stream not found'})
        return

    if 'muted' in payload:
        stream['mute'] = bool(payload.get('muted'))

    if 'paused' in payload:
        paused = bool(payload.get('paused'))
        stream['paused'] = paused

        if paused:

            stream['state'] = 'paused'

        elif stream.get('closing'):

            stream['state'] = 'draining'

        elif stream.get('started'):

            stream['state'] = 'playing'

        else:

            stream['state'] = 'prebuffering'

    send(fd, MSGSTREAMCONTROL, streamstatusdata(stream))


def handlevolume(fd, payload):

    global MASTERGAIN

    if not payload:

        send(fd, MSGVOLUME, {'gain': float(MASTERGAIN), 'mute': bool(MASTERMUTE)})

        return

    if ('gain' not in payload and 'delta' not in payload):

        send(fd, MSGERROR, {'error': 'missing gain'})
        return

    if 'gain' in payload:

        gain = float(payload['gain'])

    else:

        delta = float(payload.get('delta', 0.0))

        gain = float(MASTERGAIN) + float(delta)

    if gain < 0.0:
        gain = 0.0

    if gain > 1.0:
        gain = 1.0

    # The desktop volume observer may repeat the current absolute value.
    # Avoid rewriting settings and enumerating every ALSA mixer control when
    # the effective hardware state has not changed.
    if abs(float(gain) - float(MASTERGAIN)) < 0.000001:

        send(fd, MSGVOLUME, {'gain': float(MASTERGAIN)})

        return

    MASTERGAIN = float(gain)

    # Mixing observes MASTERGAIN on the next period. Persist only after the
    # control has been quiet briefly: fsync and ALSA control walks on every
    # slider event used to starve active playback.
    masterconfigschedule()

    send(fd, MSGVOLUME, {'gain': MASTERGAIN})

    msg = {}

    msg['type'] = 'volume'

    msg['time'] = timestamp()

    msg['data'] = {'gain': float(MASTERGAIN), 'mute': bool(MASTERMUTE)}

    broadcast(MSGNOTIFY, msg)


def handlemute(fd, payload):

    global MASTERMUTE

    if not payload:

        send(fd, MSGMUTE, {'mute': bool(MASTERMUTE), 'gain': float(MASTERGAIN)})

        return

    if 'mute' not in payload:

        send(fd, MSGERROR, {'error': 'missing mute'})
        return

    mute = bool(payload['mute'])

    if mute == bool(MASTERMUTE):

        send(fd, MSGMUTE, {'mute': bool(MASTERMUTE)})

        return

    MASTERMUTE = mute

    masterconfigschedule()

    send(fd, MSGMUTE, {'mute': bool(MASTERMUTE)})

    event('mute', {'mute': bool(MASTERMUTE), 'gain': float(MASTERGAIN)})


def handlesubscribe(fd, payload):

    if not payload or 'topic' not in payload:

        send(fd, MSGERROR, {'error': 'missing topic'})
        return

    topic = payload['topic']

    client = CLIENTS.get(fd)

    if not client:

        return

    client['subs'].add(topic)

    send(fd, MSGSUBSCRIBE, {'topic': topic})

    if topic == 'volume':

        msg = {}

        msg['type'] = 'volume'

        msg['time'] = timestamp()

        msg['data'] = {'gain': float(MASTERGAIN), 'mute': bool(MASTERMUTE)}

        send(fd, MSGNOTIFY, msg)

    if topic == 'mute':

        msg = {}

        msg['type'] = 'mute'

        msg['time'] = timestamp()

        msg['data'] = {'mute': bool(MASTERMUTE), 'gain': float(MASTERGAIN)}

        send(fd, MSGNOTIFY, msg)


# stream functions
def pruneclosed(fd=None):

    nowt = time.monotonic()

    for key in list(CLOSEDSTREAMS.keys()):

        entry = CLOSEDSTREAMS.get(key, {})

        if fd is not None and int(key[0]) == int(fd):

            del CLOSEDSTREAMS[key]

            continue

        if float(entry.get('expires', 0.0)) <= nowt:

            del CLOSEDSTREAMS[key]

    if len(CLOSEDSTREAMS) <= CLOSEDSTREAMLIMIT:

        return

    ordered = sorted(
        CLOSEDSTREAMS.items(),
        key=lambda item: float(item[1].get('expires', 0.0)),
    )

    remove = len(CLOSEDSTREAMS) - CLOSEDSTREAMLIMIT

    for key, entry in ordered[:remove]:

        CLOSEDSTREAMS.pop(key, None)


def rememberclosed(stream, reason):

    if not stream:

        return None

    payload = streamstatusdata(stream)

    payload['state'] = 'closed'

    payload['queued'] = 0

    payload['reason'] = str(reason)

    key = (int(stream.get('fd', -1)), int(stream.get('id', 0)))

    CLOSEDSTREAMS[key] = {
        'expires': time.monotonic() + CLOSEDSTREAMTTL,
        'payload': payload,
    }

    pruneclosed()

    return dict(payload)


def closedstreamget(fd, streamid):

    pruneclosed()

    entry = CLOSEDSTREAMS.get((int(fd), int(streamid)))

    if not entry:

        return None

    return dict(entry.get('payload', {}))


def streamstatusdata(stream):

    rb = stream.get('rb') if stream else None
    hardwarependingframes = backendpendingframes()
    globalpresentedframes = backendpresentedframes(hardwarependingframes)
    presentedframes = streampresentedframes(stream, globalpresentedframes)
    fmt = stream.get('format', {}) if stream else {}

    return {
        'stream': int(stream.get('id', 0)),
        'state': str(stream.get('state', 'playing')),
        'queued': int(rbavail(rb)) if rb else 0,
        'capacity': int(rb.get('size', 0)) if rb else 0,
        'input_bytes': int(stream.get('inbytes', 0)),
        'output_bytes': int(stream.get('outbytes', 0)),
        'presented_bytes': int(presentedframes * FRAMEBYTES),
        'hardware_pending_frames': int(hardwarependingframes),
        'clock_monotonic_ns': int(time.monotonic_ns()),
        'samplerate': int(fmt.get('samplerate', backendsamplerate())),
        'underruns': int(stream.get('underruns', 0)),
        'paused': bool(stream.get('paused', False)),
        'muted': bool(stream.get('mute', False)),
    }


def streamsegment(stream, timelineframe, audioframes):

    frames = max(0, int(audioframes))

    if not stream or frames <= 0:

        return

    globalstart = max(0, int(timelineframe))
    streamstart = int(stream.get('outbytes', 0)) // FRAMEBYTES
    segments = stream.setdefault('segments', [])

    if segments:

        last = segments[-1]

        if int(last[1]) == globalstart and int(last[2]) + (int(last[1]) - int(last[0])) == streamstart:

            last[1] = globalstart + frames

            return

    segments.append([globalstart, globalstart + frames, streamstart])


def streampresentedframes(stream, globalpresented=None):

    if not stream:

        return 0

    presented = max(0, int(stream.get('presentedframes', 0)))
    if globalpresented is None:

        globalpresented = backendpresentedframes()

    for segment in list(stream.get('segments', [])):

        globalstart = int(segment[0])
        globalend = int(segment[1])
        streamstart = int(segment[2])

        if globalpresented <= globalstart:

            continue

        passed = min(globalend, globalpresented) - globalstart

        if passed > 0:

            presented = max(presented, streamstart + passed)

    outputframes = max(0, int(stream.get('outbytes', 0)) // FRAMEBYTES)
    presented = min(outputframes, presented)
    stream['presentedframes'] = int(presented)

    return int(presented)


def streamdrained(stream):

    outputframes = max(0, int(stream.get('outbytes', 0)) // FRAMEBYTES)

    return streampresentedframes(stream) >= outputframes


def streamnew(fd, spec):

    global STREAMNEXT

    if len(STREAMS) >= getconfig().get('maxstreams', 32):

        return None

    fmt = streamformat(spec)

    if not fmt:

        return None

    streamid = STREAMNEXT

    STREAMNEXT += 1

    latencyclass = str(spec.get('latency_class', 'resilient')).strip().lower()

    if latencyclass not in ('interactive', 'resilient'):

        latencyclass = 'resilient'

    bufsec = float(getconfig().get('streambufsec', 4.0))

    try:

        requestedbufsec = float(spec.get('buffer_seconds', bufsec))

    except Exception:

        requestedbufsec = bufsec

    if latencyclass == 'interactive':

        # Browsers and other live clients need their requested queue depth;
        # applying file-playback defaults here adds avoidable A/V latency.
        bufsec = min(
            12.0,
            max(INTERACTIVESTREAMMINBUFFERSECONDS, requestedbufsec),
        )

    else:

        # File playback can ask for more resilience than the system-wide
        # default. Keep the configured value as a floor.
        bufsec = min(12.0, max(bufsec, requestedbufsec))

    minimum_buffer_seconds = (
        INTERACTIVESTREAMMINBUFFERSECONDS
        if latencyclass == 'interactive'
        else 0.25
    )

    if bufsec < minimum_buffer_seconds:

        bufsec = minimum_buffer_seconds

    samplerate = int(fmt.get('samplerate', backendsamplerate()))

    rbsize = int(samplerate * DEFAULTCH * 2 * bufsec)

    framesize = int(DEFAULTCH * 2)

    rbsize = int(rbsize - (rbsize % framesize))

    stream = {}

    stream['id'] = streamid

    stream['fd'] = fd

    stream['format'] = fmt

    stream['rb'] = rbnew(rbsize)

    stream['gain'] = 1.0

    stream['mute'] = False

    stream['alive'] = True

    stream['closing'] = False

    stream['started'] = False

    stream['paused'] = False

    stream['state'] = 'prebuffering'

    stream['write_ack'] = bool(spec.get('write_ack', False))

    stream['latency_class'] = latencyclass

    prebufferms = int(getconfig().get('prebufferms', 100))

    try:

        requestedprebuffer = int(spec.get('prebuffer_ms', prebufferms))

    except Exception:

        requestedprebuffer = prebufferms

    if latencyclass == 'interactive':

        prebufferms = min(2000, requestedprebuffer)

    else:

        prebufferms = min(2000, max(prebufferms, requestedprebuffer))

    if prebufferms < 0:

        prebufferms = 0

    prebufferms = min(prebufferms, int(bufsec * 1000.0))

    prebuffer = int(samplerate * FRAMEBYTES * (prebufferms / 1000.0))

    prebuffer = int(prebuffer - (prebuffer % FRAMEBYTES))

    if prebuffer > rbsize:

        prebuffer = rbsize

    stream['prebuffer'] = prebuffer

    # debug counters
    stream['inbytes'] = 0

    stream['outbytes'] = 0

    stream['presentedframes'] = 0

    stream['segments'] = []

    stream['underruns'] = 0

    stream['inmax'] = 0

    stream['inrms'] = 0.0

    stream['lastinlog'] = 0.0

    STREAMS[streamid] = stream

    return streamid


def streamfree(streamid, reason='closed', remember=True):

    stream = STREAMS.get(streamid)

    if not stream:

        return False

    stream['alive'] = False

    del STREAMS[streamid]

    if remember:

        return rememberclosed(stream, reason)

    return {
        'stream': int(streamid),
        'state': 'closed',
        'queued': 0,
        'reason': str(reason),
    }


def streamget(streamid):

    return STREAMS.get(streamid)


def streampush(streamid, pcmbytes):

    stream = STREAMS.get(streamid)

    if not stream:

        return False

    rb = stream.get('rb')

    if not rb:

        return False

    framesize = FRAMEBYTES

    space = int(rbspace(rb))

    n = int(len(pcmbytes))

    if n <= 0 or n % framesize:

        return False

    if n > space:

        return False

    return bool(rbpush(rb, pcmbytes))


def streampull(streamid, nbytes):

    stream = STREAMS.get(streamid)

    if not stream:

        return None

    rb = stream.get('rb')

    if not rb:

        return None

    if rbavail(rb) < nbytes:

        return None

    return rbpop(rb, nbytes)


def streamformat(spec):

    fmt = {}

    try:

        fmt['samplerate'] = int(spec.get('samplerate', backendsamplerate()))

        fmt['channels'] = int(spec.get('channels', DEFAULTCH))

        fmt['format'] = spec.get('format', DEFAULTFMT)

    except Exception:

        return None

    if fmt['samplerate'] != backendsamplerate():

        return None

    if fmt['channels'] != DEFAULTCH:

        return None

    if fmt['format'] != DEFAULTFMT:

        return None

    return fmt


def streamgain(streamid, gain):

    stream = STREAMS.get(streamid)

    if not stream:

        return False

    try:

        stream['gain'] = clamp(float(gain), 0.0, 1.0)

    except Exception:

        return False

    return True


def streammute(streamid, mute):

    stream = STREAMS.get(streamid)

    if not stream:

        return False

    stream['mute'] = bool(mute)

    return True


# ringbuffer functions
def rbnew(maxbytes):

    rb = {}

    rb['buf'] = bytearray(maxbytes)

    rb['size'] = maxbytes

    rb['r'] = 0

    rb['w'] = 0

    rb['used'] = 0

    return rb


def rbclear(rb):

    rb['r'] = 0

    rb['w'] = 0

    rb['used'] = 0


def rbavail(rb):

    return rb.get('used', 0)


def rbspace(rb):

    return rb.get('size', 0) - rb.get('used', 0)


def rbpush(rb, data):

    size = rb['size']

    buf = rb['buf']

    w = rb['w']

    used = rb['used']

    n = len(data)

    if n > size - used:

        return False

    end = size - w

    if n <= end:

        buf[w:w + n] = data

        w = (w + n) % size

    else:

        buf[w:w + end] = data[:end]

        buf[0:n - end] = data[end:]

        w = n - end

    rb['w'] = w

    rb['used'] = used + n

    return True


def rbpop(rb, nbytes):

    size = rb['size']

    buf = rb['buf']

    r = rb['r']

    used = rb['used']

    if nbytes > used:

        return None

    out = bytearray(nbytes)

    end = size - r

    if nbytes <= end:

        out[:] = buf[r:r + nbytes]

        r = (r + nbytes) % size

    else:

        out[:end] = buf[r:r + end]

        out[end:] = buf[0:nbytes - end]

        r = nbytes - end

    rb['r'] = r

    rb['used'] = used - nbytes

    return bytes(out)


# mixing functions
def mixperiodframes():

    frames = int(MIXFRAMES)

    if BACKEND and BACKEND.get('alsa') and BACKEND.get('periodframes'):

        frames = int(BACKEND.get('periodframes'))

    return max(1, frames)


def mixwait(maximum=0.02):

    if LASTMIX <= 0.0:

        return 0.0

    wait = float(LASTMIX) - time.monotonic()

    if wait < 0.0:

        wait = 0.0

    if wait > float(maximum):

        wait = float(maximum)

    return wait


def mixloop():

    global LASTMIX, XRUNS, MIXEDFRAMES, LASTSTATLOG

    nowt = time.monotonic()

    frames = mixperiodframes()

    interval = float(frames) / float(backendsamplerate())
    epsilon = max(0.000001, interval * 0.001)

    if LASTMIX <= 0.0:

        LASTMIX = nowt

    if BACKEND and BACKEND.get('alsa'):

        backendfilepump()
        # Keep one hardware buffer queued. The former two-buffer target added
        # about 80 ms on the reference HDA device before each application's
        # own prebuffer, making recovery from load visible as A/V drift.
        targetframes = max(
            int(BACKEND.get('bufferframes', frames * 4)),
            int(frames) * 4,
        )
        framebytes = max(1, int(BACKEND.get('framebytes', FRAMEBYTES)))
        required = int(frames) * framebytes
        mixed = 0

        while backendpendingframes() < targetframes and mixed < int(MAXMIXCATCHUP):

            rb = BACKEND.get('outrb')

            if rb and rbspace(rb) < required:

                backendfilepump()

                if rbspace(rb) < required:

                    break

            pcm = mixonceframes(frames, timelineframe=MIXEDFRAMES)

            if pcm is None or not backendwrite(pcm):

                XRUNS += 1

                break

            MIXEDFRAMES += int(frames)
            mixed += 1

        LASTMIX = nowt + interval
        nowt = time.monotonic()

        if (nowt - float(LASTSTATLOG)) > AUDIOTELEMETRYINTERVAL:

            log(
                f'mix tick mixedframes={MIXEDFRAMES} presentedframes={backendpresentedframes()} '
                f'pendingframes={backendpendingframes()} xruns={XRUNS} underruns={UNDERRUNS} '
                f'backendwrites={BACKENDWRITES} backenderrors={BACKENDERRS} '
                f'recoveries={int(BACKEND.get("recoveries", 0))} streams={len(STREAMS)}'
            )

            LASTSTATLOG = nowt

        return

    if nowt + epsilon < LASTMIX:

        if BACKEND and BACKEND.get('alsa'):

            backendfilepump()

        return

    mixed = 0
    dueat = nowt

    while dueat + epsilon >= LASTMIX and mixed < int(MAXMIXCATCHUP):

        pcm = mixonceframes(frames, timelineframe=MIXEDFRAMES)

        if pcm is None:

            XRUNS += 1

        else:

            MIXEDFRAMES += int(frames)
            backendwrite(pcm)

        LASTMIX += interval
        mixed += 1

    if dueat + epsilon >= LASTMIX:

        dropped = int((dueat - LASTMIX) // interval) + 1
        LASTMIX += float(dropped) * interval
        XRUNS += int(dropped)

    nowt = time.monotonic()

    if (nowt - float(LASTSTATLOG)) > AUDIOTELEMETRYINTERVAL:

        log(f'mix tick mixedframes={MIXEDFRAMES} xruns={XRUNS} underruns={UNDERRUNS} streams={len(STREAMS)}')

        LASTSTATLOG = nowt


def mixonce():

    framebytes = MIXFRAMES * DEFAULTCH * 2

    collected = mixcollect()

    if not collected:

        return mixsilence(framebytes)

    mixed = bytearray(framebytes)

    for pcm in collected:

        mixsum(mixed, pcm)

    mixed = mixmaster(bytes(mixed))
    mixleveltrace(mixed)

    return mixed


def mixonceframes(frames, timelineframe=None):

    framebytes = int(frames) * DEFAULTCH * 2

    collected = mixcollectframes(frames, timelineframe=timelineframe)

    if not collected:

        return mixsilence(framebytes)

    mixed = bytearray(framebytes)

    for pcm in collected:

        mixsum(mixed, pcm)

    mixed = mixmaster(bytes(mixed))
    mixleveltrace(mixed)

    return mixed


def mixcollect():

    return mixcollectframes(MIXFRAMES)


def mixcollectframes(frames, timelineframe=None):

    global UNDERRUNS

    blocks = []

    need = int(frames) * DEFAULTCH * 2

    if timelineframe is None:

        timelineframe = int(MIXEDFRAMES)

    for streamid in list(STREAMS.keys()):

        stream = STREAMS.get(streamid)

        if not stream or not stream.get('alive'):

            continue

        if stream.get('paused'):

            continue

        rb = stream.get('rb')

        if not rb:

            continue

        have = int(rbavail(rb))

        if stream.get('closing') and have <= 0:

            if (not stream.get('started')) or streamdrained(stream):

                streamfree(streamid, reason='drained')

            continue

        if not stream.get('started'):

            prebuffer = int(stream.get('prebuffer', 0))

            if have >= prebuffer or (stream.get('closing') and have > 0):

                stream['started'] = True

                stream['state'] = 'draining' if stream.get('closing') else 'playing'

            elif stream.get('closing') and have <= 0:

                streamfree(streamid, reason='drained')

                continue

            else:

                continue

        if have < need:

            if stream.get('closing') and have > 0:

                pcm = rbpop(rb, have)

                pad = mixsilence(int(need - have))

                streamsegment(stream, timelineframe, len(pcm) // FRAMEBYTES)

                stream['outbytes'] += int(len(pcm))

                if not stream.get('mute'):

                    gain = stream.get('gain', 1.0)

                    if gain != 1.0:

                        pcm = mixapplygain(pcm, gain)

                    blocks.append(pcm + pad)

                continue

            stream['underruns'] = int(stream.get('underruns', 0)) + 1

            UNDERRUNS += 1

            # Resume through the stream's prebuffer instead of playing
            # isolated periods as soon as they arrive after a scheduling
            # stall. This turns a starvation event into one clean recovery.
            if not stream.get('closing'):

                stream['started'] = False

                stream['state'] = 'prebuffering'

            if stream.get('closing') and have <= 0:

                streamfree(streamid, reason='drained')

            continue

        pcm = streampull(streamid, need)

        if pcm is None:

            stream['underruns'] = int(stream.get('underruns', 0)) + 1

            UNDERRUNS += 1

            if not stream.get('closing'):

                stream['started'] = False

                stream['state'] = 'prebuffering'

            continue

        streamsegment(stream, timelineframe, len(pcm) // FRAMEBYTES)

        stream['outbytes'] += int(len(pcm))

        if not stream.get('mute'):

            gain = stream.get('gain', 1.0)

            if gain != 1.0:

                pcm = mixapplygain(pcm, gain)

            blocks.append(pcm)

    return blocks


def mixapplygain(pcms16, gain):

    if gain == 1.0:

        return pcms16

    out = bytearray(len(pcms16))

    for i in range(0, len(pcms16), 2):

        sample = struct.unpack_from('<h', pcms16, i)[0]

        val = int(sample * gain)

        if val > 32767:
            val = 32767

        if val < -32768:
            val = -32768

        struct.pack_into('<h', out, i, val)

    return bytes(out)


def mixapplygainramp(pcms16, startgain, endgain):

    if not pcms16:
        return pcms16

    channels = max(1, int(DEFAULTCH))
    framebytes = channels * 2
    frames = len(pcms16) // framebytes

    if frames <= 0:
        return pcms16

    startgain = float(startgain)
    endgain = float(endgain)

    if abs(endgain - startgain) < 0.000001:
        return mixapplygain(pcms16, endgain)

    samplerate = max(1, int(backendsamplerate()))
    rampframes = max(1, int(round(samplerate * float(MASTERGAINRAMPMS) / 1000.0)))
    rampframes = min(frames, rampframes)
    out = bytearray(len(pcms16))

    for frame in range(frames):

        if rampframes <= 1 or frame >= rampframes:
            gain = endgain
        else:
            gain = startgain + ((endgain - startgain) * (float(frame) / float(rampframes - 1)))

        offset = frame * framebytes

        for channel in range(channels):

            sampleoffset = offset + channel * 2
            sample = struct.unpack_from('<h', pcms16, sampleoffset)[0]
            value = int(sample * gain)

            if value > 32767:
                value = 32767

            if value < -32768:
                value = -32768

            struct.pack_into('<h', out, sampleoffset, value)

    remainder = frames * framebytes

    if remainder < len(pcms16):
        out[remainder:] = pcms16[remainder:]

    return bytes(out)


def mixsum(out, inp):

    for i in range(0, len(out), 2):

        a = struct.unpack_from('<h', out, i)[0]

        b = struct.unpack_from('<h', inp, i)[0]

        v = a + b

        if v > 32767:
            v = 32767

        if v < -32768:
            v = -32768

        struct.pack_into('<h', out, i, v)


def mixsilence(nbytes):

    return b'\x00' * nbytes


def mixmaster(pcmbytes):

    global MASTERAPPLIEDGAIN

    targetgain = 0.0 if MASTERMUTE else mastergainmultiplier(MASTERGAIN)

    if MASTERAPPLIEDGAIN is None:

        MASTERAPPLIEDGAIN = float(targetgain)

        if targetgain == 1.0:
            return pcmbytes

        return mixapplygain(pcmbytes, targetgain)

    startgain = float(MASTERAPPLIEDGAIN)
    MASTERAPPLIEDGAIN = float(targetgain)

    if abs(float(targetgain) - startgain) < 0.000001:

        if targetgain == 1.0:
            return pcmbytes

        return mixapplygain(pcmbytes, targetgain)

    return mixapplygainramp(pcmbytes, startgain, targetgain)


# subscription functions
def subadd(fd, topic):

    client = CLIENTS.get(fd)

    if not client:
        return False

    client['subs'].add(topic)

    return True


def subdel(fd, topic):

    client = CLIENTS.get(fd)

    if not client:
        return False

    if topic in client['subs']:
        client['subs'].remove(topic)

    return True


def subsend(topic, msgtype, payload):

    for fd, client in CLIENTS.items():

        subs = client.get('subs')

        if not subs:
            continue

        if topic not in subs:
            continue

        send(fd, msgtype, payload)


def event(evtype, payload):

    msg = {}

    msg['type'] = evtype

    msg['time'] = timestamp()

    msg['data'] = payload

    subsend(evtype, MSGNOTIFY, msg)


# core function
def main():

    prioritiseaudio()

    setup()

    runloop()



# execute main
if __name__ == '__main__':

    main()
