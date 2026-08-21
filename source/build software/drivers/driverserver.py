#!"/the one/software/python/bin/python" -B

"""T1OS Driver Server.

Discovers cold-plug and hot-plug hardware from the T1OS driver-state tree,
applies T1OS module policy, and delegates dependency-aware insertion to the
T1OS-native modprobe runtime. No Linux distribution service or persistent
Linux filesystem hierarchy is required.
"""

import hashlib
import ctypes
import errno
import json
import os
import re
import select
import signal
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

sys.path.insert(0, '/the one/build')
from GODDESS.GODDESS import formatlog


DRIVERROOT = Path(os.environ.get('T1OS_DRIVER_ROOT', '/the one/drivers'))
STATEROOT = Path(os.environ.get('T1OS_DRIVER_STATE', str(DRIVERROOT / 'state')))
CONTROLROOT = Path(os.environ.get('T1OS_DRIVER_CONTROL', str(DRIVERROOT / 'control')))
MODULEROOT = Path(os.environ.get('T1OS_DRIVER_MODULES', str(DRIVERROOT / 'modules')))
FIRMWAREROOT = Path(os.environ.get('T1OS_DRIVER_FIRMWARE', str(DRIVERROOT / 'firmware')))
MODPROBE = Path(os.environ.get('T1OS_DRIVER_MODPROBE', str(DRIVERROOT / 'tools/modprobe')))
NULLDEVICE = Path(os.environ.get('T1OS_DRIVER_NULL', str(DRIVERROOT / 'nodes/null')))
POLICYPATH = Path(os.environ.get('T1OS_DRIVER_POLICY', str(DRIVERROOT / 'settings/policy.json')))
RUNTIMEROOT = Path(os.environ.get('T1OS_DRIVER_RUNTIME', '/.ephemeral/drivers'))
SOCKETPATH = RUNTIMEROOT / 'accept.sock'
STATUSPATH = RUNTIMEROOT / 'status.json'
PROCESSROOT = Path(os.environ.get(
    'T1OS_DRIVER_PROCESSES',
    str(DRIVERROOT / 'processes'),
))
try:
    EARLYBOOTANIMATIONPID = int(os.environ.get(
        'T1OS_EARLY_BOOT_ANIMATION_PID',
        '0',
    ) or 0)
except (TypeError, ValueError):
    EARLYBOOTANIMATIONPID = 0
EARLYBOOTANIMATIONBASE = Path('/.ephemeral/boot animation')
VOLUMESTATUSPATH = RUNTIMEROOT / 'volumes.json'
CMDLINEPATH = Path(os.environ.get('T1OS_DRIVER_CMDLINE', str(DRIVERROOT / 'processes/cmdline')))
GRAPHICSRECOVERYBOOTPATH = Path(os.environ.get(
    'T1OS_GRAPHICS_RECOVERY_BOOT',
    '/the one/settings/graphics recovery boot.json',
))
BOOTIDPATH = Path(os.environ.get(
    'T1OS_BOOT_ID',
    str(PROCESSROOT / 'sys/kernel/random/boot_id'),
))
UEVENT_PROTOCOL = 15  # NETLINK_KOBJECT_UEVENT
VOLUMEBASE = Path(os.environ.get('T1OS_VOLUME_ROOT', '/.ephemeral/volumes'))
MOUNTSFILE = Path(os.environ.get(
    'T1OS_DRIVER_MOUNTS',
    str(DRIVERROOT / 'processes/self/mounts'),
))
GRAPHICSRESETREQUESTLIMIT = 4096
GRAPHICSRESETWRITETIMEOUT = float(os.environ.get(
    'T1OS_GRAPHICS_RESET_WRITE_TIMEOUT',
    '3.0',
))
GRAPHICSRESETREADYTIMEOUT = float(os.environ.get(
    'T1OS_GRAPHICS_RESET_READY_TIMEOUT',
    '8.0',
))
PCIBDFPATTERN = re.compile(
    r'^[0-9A-Fa-f]{4}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}\.[0-7]$'
)
PCIDRIVERPATTERN = re.compile(r'^[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}$')
NVIDIADEVICESPATH = Path(os.environ.get(
    'T1OS_NVIDIA_DEVICES',
    str(DRIVERROOT / 'processes/devices'),
))
NVIDIAGPUROOT = Path(os.environ.get(
    'T1OS_NVIDIA_GPU_ROOT',
    str(DRIVERROOT / 'processes/driver/nvidia/gpus'),
))
NVIDIANODEROOT = Path(os.environ.get(
    'T1OS_NVIDIA_NODE_ROOT',
    str(DRIVERROOT / 'nodes'),
))
NVIDIANODEGROUP = 1000
NVIDIANODEMODE = 0o660
NVIDIACONTROLMINOR = 255
NVIDIAMODESETMINOR = 254
NVIDIAUVMMINOR = 0
NVIDIAMAXIMUMGPUS = 32
NVIDIAPROCREADLIMIT = 64 * 1024
NVIDIADRMREQUIREDPARAMETERS = {
    'fbdev': '1',
    'modeset': '1',
}

MS_RDONLY = 1
MS_NOSUID = 2
MS_NODEV = 4
MS_NOEXEC = 8
MNT_DETACH = 2

SUPPORTED_EXTERNAL_FILESYSTEMS = {'ntfs3', 'exfat', 'vfat'}
WINDOWS_ROOT_NAMES = {'windows', 'winnt'}
OS_GPT_TYPES = {
    '21686148-6449-6e6f-744e-656564454649': 'BIOS boot partition',
    'c12a7328-f81f-11d2-ba4b-00a0c93ec93b': 'EFI system partition',
    'e3c9e316-0b5c-4db8-817d-f92df00215ae': 'Microsoft reserved partition',
    'de94bba4-06d1-4d40-a16a-bfd50179d6ac': 'Windows recovery partition',
    '7c3457ef-0000-11aa-aa11-00306543ecac': 'Apple APFS container',
    '48465300-0000-11aa-aa11-00306543ecac': 'Apple HFS partition',
    '426f6f74-0000-11aa-aa11-00306543ecac': 'Apple boot partition',
    '0657fd6d-a4ab-43c4-84e5-0933c84b4f4f': 'Linux swap partition',
    '0fc63daf-8483-4772-8e79-3d69d8477de4': 'Linux filesystem partition',
    '4f68bce3-e8cd-4db1-96e7-fbcaf984b709': 'Linux x86-64 root partition',
    '44479540-f297-41b2-9af7-d131d5f0458a': 'Linux x86 root partition',
    '69dad710-2ce4-4e3c-b16c-21a1d49abed3': 'Linux ARM64 root partition',
    '933ac7e1-2eb4-4f13-b844-0e14e2aef915': 'Linux home partition',
}
OS_MBR_TYPES = {
    0x27: 'Windows recovery partition',
    0x82: 'Linux swap partition',
    0x83: 'Linux filesystem partition',
    0x8E: 'Linux LVM partition',
    0xAB: 'Apple boot partition',
    0xAF: 'Apple filesystem partition',
    0xEF: 'EFI system partition',
}


class GraphicsResetError(Exception):
    def __init__(self, phase, errornumber, message):
        super().__init__(str(message))
        self.phase = str(phase)
        self.errornumber = int(errornumber or errno.EIO)
        self.message = str(message)


def graphicsresetresponse(
    success,
    phase,
    errornumber=0,
    message='',
    bdf='',
    driver='',
    **details,
):
    errornumber = int(errornumber or 0)
    response = {
        'format': 1,
        'request': 'RESET_GRAPHICS',
        'state': 'ok' if success else 'error',
        'ok': bool(success),
        'phase': str(phase),
        'errno': errornumber,
        'errno_name': errno.errorcode.get(errornumber, '') if errornumber else '',
        'message': str(message),
    }
    if bdf:
        response['bdf'] = str(bdf)
    if driver:
        response['driver'] = str(driver)
    response.update(details)
    return response


def parsegraphicsresetrequest(request, peer):
    if not isinstance(request, dict):
        raise GraphicsResetError(
            'request',
            errno.EINVAL,
            'request must be a JSON object',
        )

    if request.get('request') != 'RESET_GRAPHICS':
        raise GraphicsResetError(
            'request',
            errno.EINVAL,
            'request must be RESET_GRAPHICS',
        )

    allowed = {'request', 'bdf', 'driver'}
    unknown = sorted(set(request) - allowed)
    if unknown:
        raise GraphicsResetError(
            'request',
            errno.EINVAL,
            f'unknown request fields: {", ".join(unknown)}',
        )

    try:
        pid, uid, _ = (int(value) for value in peer)
    except (TypeError, ValueError):
        raise GraphicsResetError(
            'authorize',
            errno.EPERM,
            'RESET_GRAPHICS requires Unix peer credentials',
        )

    if pid != 1 or uid != 0:
        raise GraphicsResetError(
            'authorize',
            errno.EPERM,
            'RESET_GRAPHICS is restricted to PID 1 running as UID 0',
        )

    if not isinstance(request.get('bdf'), str):
        raise GraphicsResetError(
            'validate-bdf',
            errno.EINVAL,
            'PCI BDF must be a string',
        )
    if not isinstance(request.get('driver'), str):
        raise GraphicsResetError(
            'validate-driver',
            errno.EINVAL,
            'PCI driver name must be a string',
        )
    bdf = request['bdf']
    driver = request['driver']
    if PCIBDFPATTERN.fullmatch(bdf) is None:
        raise GraphicsResetError(
            'validate-bdf',
            errno.EINVAL,
            'invalid PCI BDF',
        )
    if PCIDRIVERPATTERN.fullmatch(driver) is None:
        raise GraphicsResetError(
            'validate-driver',
            errno.EINVAL,
            'invalid PCI driver name',
        )
    return bdf.lower(), driver


def peercredentials(connection):
    option = getattr(socket, 'SO_PEERCRED', None)
    if option is None:
        raise GraphicsResetError(
            'authorize',
            errno.ENOTSUP,
            'Unix peer credentials are unavailable',
        )
    try:
        credentials = connection.getsockopt(
            socket.SOL_SOCKET,
            option,
            struct.calcsize('3i'),
        )
        return struct.unpack('3i', credentials)
    except (OSError, struct.error) as error:
        raise GraphicsResetError(
            'authorize',
            getattr(error, 'errno', None) or errno.EPERM,
            f'could not read Unix peer credentials: {error}',
        ) from error


def currentpcidriver(root, bdf):
    link = Path(root) / 'bus/pci/devices' / bdf / 'driver'
    if not link.is_symlink():
        return ''
    try:
        return os.path.basename(os.path.realpath(link))
    except OSError:
        return ''


def pciclass(root, bdf):
    path = Path(root) / 'bus/pci/devices' / bdf / 'class'
    try:
        value = path.read_text(
            encoding='ascii',
            errors='strict',
        ).strip()
        return int(value, 0)
    except (OSError, ValueError) as error:
        raise GraphicsResetError(
            'validate-class',
            getattr(error, 'errno', None) or errno.ENODEV,
            f'could not read PCI class from {path}: {error}',
        ) from error


def validategraphicsownership(
    bdf,
    driver,
    controlroot=CONTROLROOT,
    stateroot=STATEROOT,
):
    for label, root in (
        ('state', Path(stateroot)),
        ('control', Path(controlroot)),
    ):
        device = root / 'bus/pci/devices' / bdf
        if not device.exists():
            raise GraphicsResetError(
                'validate-device',
                errno.ENODEV,
                f'PCI function {bdf} is absent from the {label} tree',
            )
        deviceclass = pciclass(root, bdf)
        if (deviceclass & 0xFF0000) != 0x030000:
            raise GraphicsResetError(
                'validate-class',
                errno.EPERM,
                f'PCI function {bdf} is class 0x{deviceclass:06x}, not display class 0x03',
            )
        actual = currentpcidriver(root, bdf)
        if actual != driver:
            raise GraphicsResetError(
                'validate-owner',
                errno.ENODEV,
                f'{label} tree owner is {actual or "unbound"}, expected {driver}',
            )

        expected = root / 'bus/pci/drivers' / driver
        link = device / 'driver'
        try:
            owned = (
                expected.exists()
                and os.path.normcase(os.path.realpath(link))
                == os.path.normcase(os.path.realpath(expected))
            )
        except OSError:
            owned = False
        if not owned:
            raise GraphicsResetError(
                'validate-owner',
                errno.ENODEV,
                f'{label} tree does not link {bdf} to {driver}',
            )

    unbind = Path(controlroot) / 'bus/pci/drivers' / driver / 'unbind'
    if not unbind.exists():
        raise GraphicsResetError(
            'validate-owner',
            errno.ENOENT,
            f'PCI driver unbind control is absent: {unbind}',
        )
    return True


def pcidrmnodes(bdf, stateroot=STATEROOT):
    stateroot = Path(stateroot)
    device = stateroot / 'bus/pci/devices' / bdf
    expected = os.path.normcase(os.path.realpath(device))
    drmroot = stateroot / 'class/drm'
    try:
        entries = list(drmroot.iterdir())
    except OSError:
        return []

    nodes = []
    for entry in entries:
        if re.fullmatch(r'(?:card|renderD)[0-9]+', entry.name) is None:
            continue
        try:
            actual = os.path.normcase(os.path.realpath(entry / 'device'))
        except OSError:
            continue
        if actual == expected:
            nodes.append(entry.name)
    return sorted(nodes)


def log(message):
    print(formatlog('driver server', message), flush=True)


def processalive(pid):
    try:
        # A non-child zombie has already released every fd and mmap, but
        # kill(pid, 0) continues to report it until PID 1 reaps it.
        # T1OS does not retain the conventional process-filesystem mount after
        # switch_root; the read-only view exposed to DriverServer lives below
        # DRIVERROOT.
        statpath = PROCESSROOT / str(int(pid)) / 'stat'
        try:
            processstat = statpath.read_text(
                encoding='ascii',
                errors='replace',
            )
            # The comm field is parenthesized and may itself contain spaces;
            # the process state is the first field after its closing ')'.
            stattail = processstat.rsplit(')', 1)[1].split()
            if stattail and stattail[0] == 'Z':
                return False
        except (OSError, IndexError):
            pass
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except (OSError, ValueError, TypeError):
        return False


def retireearlybootanimation(pid=EARLYBOOTANIMATIONPID):
    """Release firmware framebuffer memory before native display binding."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return True

    if pid <= 1 or not processalive(pid):
        return True

    request = EARLYBOOTANIMATIONBASE / 'request.json'
    temporary = request.with_name(f'{request.name}.{os.getpid()}.new')

    try:
        EARLYBOOTANIMATIONBASE.mkdir(mode=0o700, parents=True, exist_ok=True)
        with temporary.open('w', encoding='utf-8') as stream:
            json.dump({
                'format': 1,
                'pid': pid,
                'action': 'stop',
            }, stream, sort_keys=True, separators=(',', ':'))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, request)
    except OSError as error:
        log(f'early boot animation stop request failed pid={pid}: {error}')
        try:
            temporary.unlink()
        except OSError:
            pass

    deadline = time.monotonic() + 1.5
    while processalive(pid) and time.monotonic() < deadline:
        time.sleep(0.02)

    if processalive(pid):
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        deadline = time.monotonic() + 1.0
        while processalive(pid) and time.monotonic() < deadline:
            time.sleep(0.02)

    if processalive(pid):
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        deadline = time.monotonic() + 1.0
        while processalive(pid) and time.monotonic() < deadline:
            time.sleep(0.02)

    retired = not processalive(pid)
    log(
        f'early boot animation framebuffer owner pid={pid} '
        f'retired={retired} before native display binding'
    )
    return retired


def normalizemodule(value):
    return str(value or '').strip().replace('-', '_')


def parseblacklist(commandline):
    blocked = set()
    for argument in str(commandline or '').split():
        if argument.startswith('module_blacklist=') or argument.startswith('modprobe.blacklist='):
            for module in argument.split('=', 1)[1].split(','):
                module = normalizemodule(module)
                if module:
                    blocked.add(module)
    return blocked


def parsemoduleparameters(commandline):
    parameters = {}

    for argument in str(commandline or '').split():
        if '.' not in argument or '=' not in argument:
            continue

        module, option = argument.split('.', 1)

        if '=' not in option:
            continue

        name, value = option.split('=', 1)
        module = normalizemodule(module)

        if (
            module
            and re.fullmatch(r'[A-Za-z0-9_]+', module)
            and re.fullmatch(r'[A-Za-z0-9_]+', name)
        ):
            parameters.setdefault(module, {})[name] = value

    return parameters


def pcidisplayalias(alias):
    return bool(re.fullmatch(
        r'pci:.*bc03sc[0-9a-f]{2}i[0-9a-f]{2}',
        str(alias or '').strip().lower(),
    ))


def orderedaliasmodules(alias, modules):
    """Prefer NVIDIA's official stack without removing Nouveau fallback."""
    ordered = sorted({
        normalizemodule(module)
        for module in modules
        if normalizemodule(module)
    })
    if not pcidisplayalias(alias) or 'nvidia' not in ordered:
        return ordered
    return (
        ['nvidia']
        + [module for module in ordered if module not in {'nvidia', 'nouveau'}]
        + (['nouveau'] if 'nouveau' in ordered else [])
    )


def aliasloadmodule(alias, module):
    module = normalizemodule(module)
    if pcidisplayalias(alias) and module == 'nvidia':
        # The DRM leaf pulls in nvidia and nvidia_modeset in dependency order
        # and makes KMS available before WindowServer starts.
        return 'nvidia_drm'
    return module


def pcialiasbindings(
    alias,
    stateroot=STATEROOT,
    *,
    driverlookup=None,
):
    """Return authoritative PCI-driver ownership for one display alias."""
    alias = str(alias or '').strip()
    if not pcidisplayalias(alias):
        return []

    stateroot = Path(stateroot)
    devices = stateroot / 'bus/pci/devices'
    driverlookup = driverlookup or (
        lambda bdf: currentpcidriver(stateroot, bdf)
    )

    try:
        entries = sorted(
            devices.iterdir(),
            key=lambda entry: entry.name.lower(),
        )
    except OSError:
        return []

    bindings = []
    for entry in entries:
        bdf = entry.name.lower()
        if PCIBDFPATTERN.fullmatch(bdf) is None:
            continue

        try:
            modalias = (entry / 'modalias').read_text(
                encoding='ascii',
                errors='strict',
            ).strip()
            deviceclass = int(
                (entry / 'class').read_text(
                    encoding='ascii',
                    errors='strict',
                ).strip(),
                0,
            )
        except (OSError, ValueError):
            continue

        if (
            modalias.casefold() != alias.casefold()
            or (deviceclass & 0xFF0000) != 0x030000
        ):
            continue

        bindings.append({
            'bdf': bdf,
            'driver': str(driverlookup(bdf) or '').strip(),
        })

    return bindings


def nvidiaaliasclaimed(bindings):
    """True only when NVIDIA owns every PCI display function for an alias."""
    bindings = list(bindings or [])
    return bool(bindings) and all(
        normalizemodule(binding.get('driver')) == 'nvidia'
        for binding in bindings
    )


def moduleparametermatches(module, name, expected, actual):
    if (
        normalizemodule(module) == 'nvidia_drm'
        and name in NVIDIADRMREQUIREDPARAMETERS
        and str(expected).strip().lower() in {'1', 'y', 'yes', 'on', 'true'}
    ):
        return str(actual).strip().lower() in {
            '1',
            'y',
            'yes',
            'on',
            'true',
        }
    return str(actual) == str(expected)


def boundedtext(path, limit=NVIDIAPROCREADLIMIT):
    limit = max(1, min(int(limit), NVIDIAPROCREADLIMIT))
    with Path(path).open('rb') as handle:
        encoded = handle.read(limit + 1)
    if len(encoded) > limit:
        raise ValueError(f'kernel information exceeded {limit} bytes: {path}')
    return encoded.decode('ascii', errors='strict')


def nvidiafrontendmajor(path=NVIDIADEVICESPATH):
    """Resolve the NVIDIA frontend major from legacy or current drivers."""
    registrations = {
        'nvidia-frontend': [],
        'nvidia': [],
        'nvidiactl': [],
    }
    section = ''
    for line in boundedtext(path).splitlines():
        heading = line.strip().casefold()
        if heading == 'character devices:':
            section = 'character'
            continue
        if heading == 'block devices:':
            section = 'block'
            continue
        if section != 'character':
            continue
        match = re.fullmatch(r'\s*([0-9]+)\s+(\S+)\s*', line)
        if match is None or match.group(2) not in registrations:
            continue
        registrations[match.group(2)].append(int(match.group(1), 10))

    legacy = registrations['nvidia-frontend']
    nvidia = registrations['nvidia']
    control = registrations['nvidiactl']
    if len(legacy) > 1 or len(nvidia) > 1 or len(control) > 1:
        raise ValueError(
            'duplicate NVIDIA character-device registration: '
            f'nvidia-frontend={legacy}, nvidia={nvidia}, nvidiactl={control}'
        )

    modernpresent = bool(nvidia or control)
    modernvalid = (
        len(nvidia) == 1
        and len(control) == 1
        and nvidia[0] == control[0]
    )
    if modernpresent and not modernvalid:
        raise ValueError(
            'current NVIDIA character-device registrations must contain '
            'exactly one nvidia and one nvidiactl entry with the same major: '
            f'nvidia={nvidia}, nvidiactl={control}'
        )
    if legacy and modernvalid and legacy[0] != nvidia[0]:
        raise ValueError(
            'conflicting legacy and current NVIDIA character-device majors: '
            f'nvidia-frontend={legacy[0]}, nvidia/nvidiactl={nvidia[0]}'
        )
    if len(legacy) == 1:
        major = legacy[0]
    elif modernvalid:
        major = nvidia[0]
    else:
        raise ValueError(
            'no complete NVIDIA character-device registration was found '
            '(expected nvidia-frontend or matching nvidia and nvidiactl)'
        )

    if major < 1 or major > 0xFFF:
        raise ValueError(f'NVIDIA frontend major is out of range: {major}')
    return major


def nvidiauvmmajor(path=NVIDIADEVICESPATH):
    """Resolve the dynamically allocated major for the primary NVIDIA UVM node."""
    registrations = []
    section = ''
    for line in boundedtext(path).splitlines():
        heading = line.strip().casefold()
        if heading == 'character devices:':
            section = 'character'
            continue
        if heading == 'block devices:':
            section = 'block'
            continue
        if section != 'character':
            continue
        match = re.fullmatch(r'\s*([0-9]+)\s+(\S+)\s*', line)
        if match is not None and match.group(2) == 'nvidia-uvm':
            registrations.append(int(match.group(1), 10))

    if len(registrations) != 1:
        raise ValueError(
            'NVIDIA UVM character-device registration must contain exactly '
            f'one nvidia-uvm entry: nvidia-uvm={registrations}'
        )
    major = registrations[0]
    if major < 1 or major > 0xFFF:
        raise ValueError(f'NVIDIA UVM major is out of range: {major}')
    return major


def nvidiagpuminors(root=NVIDIAGPUROOT, maximum=NVIDIAMAXIMUMGPUS):
    """Read GPU minors, allocating only a small range if a field is absent."""
    root = Path(root)
    maximum = max(1, min(int(maximum), NVIDIAMAXIMUMGPUS))
    try:
        entries = sorted(
            (
                entry
                for entry in root.iterdir()
                if entry.is_dir()
                and PCIBDFPATTERN.fullmatch(entry.name) is not None
            ),
            key=lambda entry: entry.name.lower(),
        )
    except FileNotFoundError:
        return []
    if len(entries) > maximum:
        raise ValueError(
            f'NVIDIA reported {len(entries)} GPUs; policy permits {maximum}'
        )

    reported = {}
    missing = []
    for entry in entries:
        information = entry / 'information'
        try:
            content = boundedtext(information, 16 * 1024)
        except FileNotFoundError:
            content = ''
        match = re.search(
            r'(?mi)^Device[ \t]+Minor:[ \t]*([0-9]+)[ \t]*$',
            content,
        )
        if match is None:
            missing.append(entry.name.lower())
            continue

        minor = int(match.group(1), 10)
        if minor < 0 or minor >= NVIDIAMODESETMINOR:
            raise ValueError(
                f'NVIDIA GPU minor is out of range for {entry.name}: {minor}'
            )
        if minor in reported:
            raise ValueError(
                f'duplicate NVIDIA GPU minor {minor} for '
                f'{reported[minor]} and {entry.name}'
            )
        reported[minor] = entry.name.lower()

    # Some driver builds omit Device Minor. Never guess outside a bounded
    # low-minor range, and never collide with a minor the driver reported.
    fallback = iter(
        minor
        for minor in range(maximum)
        if minor not in reported
    )
    for bdf in missing:
        try:
            minor = next(fallback)
        except StopIteration as error:
            raise ValueError(
                'no bounded NVIDIA GPU minor remains for fallback allocation'
            ) from error
        reported[minor] = bdf

    return [
        {
            'bdf': bdf,
            'minor': minor,
            'minor_source': (
                'fallback'
                if bdf in missing
                else 'information'
            ),
        }
        for minor, bdf in sorted(reported.items())
    ]


def ensurenvidiacharnode(
    path,
    major,
    minor,
    *,
    nodemaker=None,
    owner=None,
    moder=None,
):
    """Create or validate one NVIDIA character node without replacing it."""
    nodemaker = nodemaker or getattr(os, 'mknod', None)
    owner = owner or getattr(os, 'chown', None)
    moder = moder or os.chmod
    if nodemaker is None or owner is None:
        raise OSError(errno.ENOSYS, 'character-node operations are unavailable')
    if not hasattr(os, 'makedev'):
        raise OSError(errno.ENOSYS, 'device-number operations are unavailable')
    path = Path(path)
    major = int(major)
    minor = int(minor)
    wanteddevice = os.makedev(major, minor)
    try:
        status = path.lstat()
        created = False
    except FileNotFoundError:
        nodemaker(
            path,
            stat.S_IFCHR | NVIDIANODEMODE,
            wanteddevice,
        )
        status = path.lstat()
        created = True

    if not stat.S_ISCHR(status.st_mode):
        raise ValueError(f'NVIDIA device path is not a character node: {path}')
    if status.st_rdev != wanteddevice:
        raise ValueError(
            f'NVIDIA device number mismatch for {path}: '
            f'expected {major}:{minor}, '
            f'found {os.major(status.st_rdev)}:{os.minor(status.st_rdev)}'
        )

    if status.st_uid != 0 or status.st_gid != NVIDIANODEGROUP:
        owner(path, 0, NVIDIANODEGROUP, follow_symlinks=False)
    if stat.S_IMODE(status.st_mode) != NVIDIANODEMODE:
        moder(path, NVIDIANODEMODE, follow_symlinks=False)

    verified = path.lstat()
    if (
        not stat.S_ISCHR(verified.st_mode)
        or verified.st_rdev != wanteddevice
        or verified.st_uid != 0
        or verified.st_gid != NVIDIANODEGROUP
        or stat.S_IMODE(verified.st_mode) != NVIDIANODEMODE
    ):
        raise ValueError(f'NVIDIA device-node verification failed: {path}')
    return created


def firmwaregraphicsrecoveryrequested(
    path=GRAPHICSRECOVERYBOOTPATH,
    bootidpath=BOOTIDPATH,
):
    # Compatibility query for older diagnostics. A previous boot is never
    # allowed to suppress native GPU module discovery on this boot.
    del path, bootidpath
    return False


def parseuevent(payload):
    fields = {}
    for raw in bytes(payload).split(b'\0'):
        if not raw:
            continue
        text = raw.decode('utf-8', 'replace')
        if '=' in text:
            key, value = text.split('=', 1)
            fields[key] = value
        elif '@' in text and 'ACTION' not in fields:
            action, devpath = text.split('@', 1)
            fields['ACTION'] = action
            fields.setdefault('DEVPATH', devpath)
    return fields


def atomicjson(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('w', encoding='utf-8') as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write('\n')
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def normalizevolumeidentity(value):
    return str(value or '').strip().casefold()


def safevolumename(value):
    name = re.sub(r'[^A-Za-z0-9._-]+', '_', str(value or '')).strip('._-')
    return name[:80] or 'external'


def mountunescape(value):
    return (
        str(value or '')
        .replace('\\040', ' ')
        .replace('\\011', '\t')
        .replace('\\012', '\n')
        .replace('\\134', '\\')
    )


def mountedfilesystems(path=MOUNTSFILE):
    mounted = {}
    try:
        with Path(path).open('r', encoding='utf-8', errors='replace') as handle:
            for line in handle:
                fields = line.split()
                if len(fields) < 4:
                    continue
                source = mountunescape(fields[0])
                target = mountunescape(fields[1])
                mounted[target] = {
                    'source': source,
                    'filesystem': fields[2],
                    'options': set(fields[3].split(',')),
                }
    except OSError:
        pass
    return mounted


def readat(handle, offset, size):
    handle.seek(max(0, int(offset)))
    return handle.read(max(0, int(size)))


def ntfsrecord(handle, mftoffset, recordsize, recordnumber, sectorsize):
    data = bytearray(readat(handle, mftoffset + (recordsize * recordnumber), recordsize))
    if len(data) != recordsize or data[:4] != b'FILE':
        return None
    try:
        usaoffset, usacount = struct.unpack_from('<HH', data, 4)
    except struct.error:
        return None
    if usaoffset < 8 or usacount < 1 or usaoffset + (usacount * 2) > len(data):
        return None
    sequence = bytes(data[usaoffset:usaoffset + 2])
    for index in range(1, usacount):
        end = (index * sectorsize) - 2
        replacement = usaoffset + (index * 2)
        if end < 0 or end + 2 > len(data) or replacement + 2 > len(data):
            return None
        if bytes(data[end:end + 2]) != sequence:
            return None
        data[end:end + 2] = data[replacement:replacement + 2]
    return bytes(data)


def ntfsattributes(record):
    if not record or len(record) < 24:
        return
    try:
        offset = struct.unpack_from('<H', record, 20)[0]
    except struct.error:
        return
    while offset + 24 <= len(record):
        try:
            attributetype, length = struct.unpack_from('<II', record, offset)
        except struct.error:
            return
        if attributetype == 0xFFFFFFFF:
            return
        if length < 24 or offset + length > len(record):
            return
        nonresident = record[offset + 8]
        if nonresident == 0:
            try:
                contentsize = struct.unpack_from('<I', record, offset + 16)[0]
                contentoffset = struct.unpack_from('<H', record, offset + 20)[0]
            except struct.error:
                return
            start = offset + contentoffset
            end = start + contentsize
            if start >= offset and end <= offset + length:
                yield attributetype, record[start:end]
        offset += length


def ntfsrawattributes(record):
    if not record or len(record) < 24:
        return
    try:
        offset = struct.unpack_from('<H', record, 20)[0]
    except struct.error:
        return
    while offset + 24 <= len(record):
        try:
            attributetype, length = struct.unpack_from('<II', record, offset)
        except struct.error:
            return
        if attributetype == 0xFFFFFFFF:
            return
        if length < 24 or offset + length > len(record):
            return
        yield attributetype, bool(record[offset + 8]), record[offset:offset + length]
        offset += length


def ntfsindexentries(data, headeroffset):
    names = set()
    if len(data) < headeroffset + 16:
        return names, False
    try:
        entryoffset, totalsize = struct.unpack_from('<II', data, headeroffset)
    except struct.error:
        return names, False
    offset = headeroffset + entryoffset
    end = headeroffset + totalsize
    if offset < headeroffset + 16 or end > len(data) or offset > end:
        return names, False
    while offset + 16 <= end:
        try:
            entrysize, keysize, flags = struct.unpack_from('<HHH', data, offset + 8)
        except struct.error:
            return names, False
        if entrysize < 16 or offset + entrysize > end:
            return names, False
        if flags & 0x02:
            return names, True
        key = data[offset + 16:offset + 16 + keysize]
        if len(key) >= 66:
            namelength = key[64]
            nameend = 66 + (namelength * 2)
            if nameend <= len(key):
                name = key[66:nameend].decode('utf-16-le', 'replace').strip().casefold()
                if name:
                    names.add(name)
        offset += entrysize
    return names, False


def ntfsfixup(data, sectorsize, magic):
    fixed = bytearray(data)
    if len(fixed) < 8 or fixed[:4] != magic:
        return None
    try:
        usaoffset, usacount = struct.unpack_from('<HH', fixed, 4)
    except struct.error:
        return None
    if usaoffset < 8 or usacount < 1 or usaoffset + (usacount * 2) > len(fixed):
        return None
    sequence = bytes(fixed[usaoffset:usaoffset + 2])
    for index in range(1, usacount):
        end = (index * sectorsize) - 2
        replacement = usaoffset + (index * 2)
        if end < 0 or end + 2 > len(fixed) or replacement + 2 > len(fixed):
            return None
        if bytes(fixed[end:end + 2]) != sequence:
            return None
        fixed[end:end + 2] = fixed[replacement:replacement + 2]
    return bytes(fixed)


def ntfsdataruns(attribute):
    try:
        runoffset = struct.unpack_from('<H', attribute, 32)[0]
        realsize = struct.unpack_from('<Q', attribute, 48)[0]
    except struct.error:
        return [], 0, False
    if runoffset < 64 or runoffset >= len(attribute):
        return [], 0, False
    runs = []
    offset = runoffset
    lcn = 0
    while offset < len(attribute):
        header = attribute[offset]
        offset += 1
        if header == 0:
            return runs, realsize, True
        lengthsize = header & 0x0F
        offsetsz = header >> 4
        if lengthsize < 1 or lengthsize > 8 or offsetsz > 8 or offset + lengthsize + offsetsz > len(attribute):
            return runs, realsize, False
        length = int.from_bytes(attribute[offset:offset + lengthsize], 'little')
        offset += lengthsize
        if offsetsz:
            delta = int.from_bytes(
                attribute[offset:offset + offsetsz],
                'little',
                signed=True,
            )
            lcn += delta
            runlcn = lcn
        else:
            runlcn = None
        offset += offsetsz
        if length < 1:
            return runs, realsize, False
        runs.append((runlcn, length))
    return runs, realsize, False


def ntfsrootnames(handle, mftoffset, recordsize, sectorsize, clustersize):
    root = ntfsrecord(handle, mftoffset, recordsize, 5, sectorsize)
    if root is None:
        return set(), False
    names = set()
    complete = True
    indexblocksize = 0
    needsallocation = False
    allocations = []
    for attributetype, nonresident, attribute in ntfsrawattributes(root):
        if attributetype == 0x90 and not nonresident:
            try:
                contentsize = struct.unpack_from('<I', attribute, 16)[0]
                contentoffset = struct.unpack_from('<H', attribute, 20)[0]
            except struct.error:
                return names, False
            content = attribute[contentoffset:contentoffset + contentsize]
            if len(content) != contentsize or len(content) < 32:
                return names, False
            indexblocksize = struct.unpack_from('<I', content, 8)[0]
            needsallocation = bool(content[28] & 0x01)
            found, parsed = ntfsindexentries(content, 16)
            names.update(found)
            complete = complete and parsed
        elif attributetype == 0xA0 and nonresident:
            allocations.append(attribute)
    if indexblocksize == 0 or indexblocksize > 1024 * 1024:
        return names, False
    if needsallocation and not allocations:
        return names, False
    for attribute in allocations:
        runs, realsize, parsedruns = ntfsdataruns(attribute)
        if not parsedruns or realsize > 64 * 1024 * 1024:
            return names, False
        remaining = realsize
        for lcn, clusters in runs:
            runsize = min(remaining, clusters * clustersize)
            remaining -= runsize
            if lcn is None:
                continue
            data = readat(handle, lcn * clustersize, runsize)
            if len(data) != runsize:
                return names, False
            for offset in range(0, len(data) - indexblocksize + 1, indexblocksize):
                block = ntfsfixup(data[offset:offset + indexblocksize], sectorsize, b'INDX')
                if block is None:
                    return names, False
                found, parsed = ntfsindexentries(block, 24)
                names.update(found)
                complete = complete and parsed
        if remaining > 0:
            return names, False
    return names, complete


def probentfs(handle, boots):
    try:
        sectorsize = struct.unpack_from('<H', boots, 11)[0]
        sectorspercluster = boots[13]
        mftcluster = struct.unpack_from('<Q', boots, 48)[0]
        recordcode = struct.unpack_from('<b', boots, 64)[0]
        serial = struct.unpack_from('<Q', boots, 72)[0]
    except (IndexError, struct.error):
        raise ValueError('invalid NTFS boot sector')
    if sectorsize not in (512, 1024, 2048, 4096) or sectorspercluster < 1:
        raise ValueError('invalid NTFS geometry')
    clustersize = sectorsize * sectorspercluster
    recordsize = (1 << -recordcode) if recordcode < 0 else recordcode * clustersize
    if recordsize < 512 or recordsize > 65536:
        raise ValueError('invalid NTFS record size')
    mftoffset = mftcluster * clustersize
    label = ''
    volumeflags = 0
    volume = ntfsrecord(handle, mftoffset, recordsize, 3, sectorsize)
    for attributetype, content in ntfsattributes(volume):
        if attributetype == 0x60:
            label = content.decode('utf-16-le', 'replace').rstrip('\0').strip()
        elif attributetype == 0x70 and len(content) >= 12:
            volumeflags = struct.unpack_from('<H', content, 10)[0]

    rootnames, rootcomplete = ntfsrootnames(
        handle,
        mftoffset,
        recordsize,
        sectorsize,
        clustersize,
    )
    for recordnumber in range(16, 4096):
        record = ntfsrecord(handle, mftoffset, recordsize, recordnumber, sectorsize)
        if record is None:
            continue
        try:
            if not (struct.unpack_from('<H', record, 22)[0] & 0x01):
                continue
        except struct.error:
            continue
        for attributetype, content in ntfsattributes(record):
            if attributetype != 0x30 or len(content) < 66:
                continue
            parent = int.from_bytes(content[:6], 'little')
            namelength = content[64]
            end = 66 + (namelength * 2)
            if parent != 5 or end > len(content):
                continue
            name = content[66:end].decode('utf-16-le', 'replace').strip().casefold()
            if name:
                rootnames.add(name)
            break
        if rootnames.intersection(WINDOWS_ROOT_NAMES):
            break

    osinstall = bool(rootnames.intersection(WINDOWS_ROOT_NAMES)) or not rootcomplete
    osreason = (
        'Windows system directory in NTFS root'
        if rootnames.intersection(WINDOWS_ROOT_NAMES)
        else 'NTFS root index could not be completely verified as data-only'
    )
    return {
        'filesystem': 'ntfs3',
        'label': label,
        'uuid': f'{serial:016X}',
        'os_install': osinstall,
        'os_reason': osreason,
        'safe_write': not osinstall and volumeflags == 0 and 'hiberfil.sys' not in rootnames,
        'volume_flags': volumeflags,
    }


def probeexfat(handle, boots):
    try:
        sectorsize = 1 << boots[108]
        clustersize = sectorsize * (1 << boots[109])
        heapoffset = struct.unpack_from('<I', boots, 88)[0]
        rootcluster = struct.unpack_from('<I', boots, 96)[0]
        serial = struct.unpack_from('<I', boots, 100)[0]
        volumeflags = struct.unpack_from('<H', boots, 106)[0]
    except (IndexError, struct.error):
        raise ValueError('invalid exFAT boot sector')
    if sectorsize < 512 or sectorsize > 4096 or clustersize < sectorsize or clustersize > 32 * 1024 * 1024:
        raise ValueError('invalid exFAT geometry')
    if rootcluster < 2:
        raise ValueError('invalid exFAT root cluster')
    rootoffset = (heapoffset * sectorsize) + ((rootcluster - 2) * clustersize)
    root = readat(handle, rootoffset, min(clustersize, 1024 * 1024))
    label = ''
    for offset in range(0, len(root) - 31, 32):
        entry = root[offset:offset + 32]
        if entry[0] == 0x00:
            break
        if entry[0] == 0x83:
            length = min(int(entry[1]), 15)
            label = entry[2:2 + (length * 2)].decode('utf-16-le', 'replace').strip()
            break
    return {
        'filesystem': 'exfat',
        'label': label,
        'uuid': f'{serial:08X}',
        'os_install': False,
        'os_reason': '',
        'safe_write': not bool(volumeflags & 0x0006),
        'volume_flags': volumeflags,
    }


def probefat(handle, boots):
    try:
        sectorsize = struct.unpack_from('<H', boots, 11)[0]
        sectorspercluster = boots[13]
        reservedsectors = struct.unpack_from('<H', boots, 14)[0]
        fatcount = boots[16]
        rootentries = struct.unpack_from('<H', boots, 17)[0]
        totalsectors16 = struct.unpack_from('<H', boots, 19)[0]
        fatsize16 = struct.unpack_from('<H', boots, 22)[0]
        totalsectors32 = struct.unpack_from('<I', boots, 32)[0]
        fatsize32 = struct.unpack_from('<I', boots, 36)[0]
    except (IndexError, struct.error):
        raise ValueError('invalid FAT boot sector')
    if sectorsize not in (512, 1024, 2048, 4096) or sectorspercluster < 1 or fatcount < 1:
        raise ValueError('invalid FAT geometry')
    totalsectors = totalsectors16 or totalsectors32
    fatsize = fatsize16 or fatsize32
    rootsectors = ((rootentries * 32) + (sectorsize - 1)) // sectorsize
    datasectors = totalsectors - (reservedsectors + (fatcount * fatsize) + rootsectors)
    if totalsectors < 1 or fatsize < 1 or datasectors < 1:
        raise ValueError('invalid FAT layout')
    clusters = datasectors // sectorspercluster
    fattype = 12 if clusters < 4085 else (16 if clusters < 65525 else 32)
    clustersize = sectorsize * sectorspercluster
    fatoffset = reservedsectors * sectorsize
    datastart = (reservedsectors + (fatcount * fatsize) + rootsectors) * sectorsize

    if fattype == 32:
        serial = struct.unpack_from('<I', boots, 67)[0]
        label = boots[71:82].decode('ascii', 'replace').strip()
        rootcluster = struct.unpack_from('<I', boots, 44)[0]
        rootdata = bytearray()
        seen = set()
        cluster = rootcluster
        while 2 <= cluster < 0x0FFFFFF8 and cluster not in seen and len(seen) < 4096:
            seen.add(cluster)
            rootdata.extend(readat(handle, datastart + ((cluster - 2) * clustersize), clustersize))
            nextentry = readat(handle, fatoffset + (cluster * 4), 4)
            if len(nextentry) != 4:
                break
            cluster = struct.unpack_from('<I', nextentry)[0] & 0x0FFFFFFF
        fatstate = readat(handle, fatoffset + 4, 4)
        state = struct.unpack_from('<I', fatstate)[0] if len(fatstate) == 4 else 0
        safewrite = bool(state & (1 << 27)) and bool(state & (1 << 26))
    else:
        serial = struct.unpack_from('<I', boots, 39)[0]
        label = boots[43:54].decode('ascii', 'replace').strip()
        rootoffset = (reservedsectors + (fatcount * fatsize)) * sectorsize
        rootdata = bytearray(readat(handle, rootoffset, rootentries * 32))
        if fattype == 16:
            fatstate = readat(handle, fatoffset + 2, 2)
            state = struct.unpack_from('<H', fatstate)[0] if len(fatstate) == 2 else 0
            safewrite = bool(state & (1 << 15)) and bool(state & (1 << 14))
        else:
            safewrite = False

    rootnames = set()
    rootlabel = ''
    for offset in range(0, len(rootdata) - 31, 32):
        entry = rootdata[offset:offset + 32]
        if entry[0] == 0x00:
            break
        if entry[0] == 0xE5 or entry[11] == 0x0F:
            continue
        rawname = bytes(entry[:8]).decode('ascii', 'replace').rstrip()
        rawextension = bytes(entry[8:11]).decode('ascii', 'replace').rstrip()
        if entry[11] & 0x08:
            rootlabel = (rawname + rawextension).strip()
            continue
        name = rawname if not rawextension else f'{rawname}.{rawextension}'
        if name:
            rootnames.add(name.casefold())
    if not label or label.casefold() == 'no name':
        label = rootlabel
    osmarkers = {
        'windows', 'winnt', 'efi', 'boot', 'bootmgr',
        'io.sys', 'msdos.sys', 'command.com',
    }
    osinstall = bool(rootnames.intersection(osmarkers))
    return {
        'filesystem': 'vfat',
        'label': label.strip(),
        'uuid': f'{serial:08X}',
        'os_install': osinstall,
        'os_reason': 'boot or operating-system content in FAT root',
        'safe_write': not osinstall and safewrite,
        'fat_type': fattype,
    }


def probevolume(path):
    with Path(path).open('rb', buffering=0) as handle:
        boots = readat(handle, 0, 4096)
        if len(boots) < 512:
            raise ValueError('volume is too small to identify')
        if boots[3:11] == b'NTFS    ':
            return probentfs(handle, boots)
        if boots[3:11] == b'EXFAT   ':
            return probeexfat(handle, boots)
        if boots[:6] == b'LUKS\xba\xbe':
            return {
                'filesystem': 'luks',
                'label': '',
                'uuid': '',
                'os_install': True,
                'os_reason': 'encrypted Linux-compatible volume',
                'safe_write': False,
            }
        if boots[32:36] == b'NXSB':
            return {
                'filesystem': 'apfs',
                'label': '',
                'uuid': '',
                'os_install': True,
                'os_reason': 'Apple APFS container',
                'safe_write': False,
            }
        hfs = readat(handle, 1024, 2)
        if hfs in (b'BD', b'H+', b'HX'):
            return {
                'filesystem': 'hfs',
                'label': '',
                'uuid': '',
                'os_install': True,
                'os_reason': 'Apple filesystem',
                'safe_write': False,
            }
        superblock = readat(handle, 1024, 1024)
        if len(superblock) >= 136 and superblock[56:58] == b'\x53\xef':
            label = superblock[120:136].split(b'\0', 1)[0].decode('utf-8', 'replace').strip()
            filesystemuuid = str(uuid.UUID(bytes=superblock[104:120]))
            return {
                'filesystem': 'ext',
                'label': label,
                'uuid': filesystemuuid,
                'os_install': True,
                'os_reason': 'Linux filesystem',
                'safe_write': False,
            }
        if boots[54:62] in (b'FAT12   ', b'FAT16   ') or boots[82:90] == b'FAT32   ':
            return probefat(handle, boots)
        for pagesize in (4096, 8192, 16384, 32768, 65536):
            signature = readat(handle, pagesize - 10, 10)
            if signature in (b'SWAP-SPACE', b'SWAPSPACE2'):
                return {
                    'filesystem': 'swap',
                    'label': '',
                    'uuid': '',
                    'os_install': True,
                    'os_reason': 'Linux swap volume',
                    'safe_write': False,
                }
    return {
        'filesystem': 'unknown',
        'label': '',
        'uuid': '',
        'os_install': False,
        'os_reason': '',
        'safe_write': False,
    }


def partitionosreasons(path, sectorsize=512):
    reasons = set()
    types = set()
    with Path(path).open('rb', buffering=0) as handle:
        mbr = readat(handle, 0, 512)
        if len(mbr) < 512:
            return ['unreadable partition table'], types
        if mbr[510:512] == b'\x55\xaa':
            for index in range(4):
                entry = mbr[446 + (index * 16):462 + (index * 16)]
                if len(entry) != 16 or entry[4] == 0:
                    continue
                if entry[0] == 0x80:
                    reasons.add('legacy bootable partition')
                partitiontype = int(entry[4])
                types.add(f'mbr:{partitiontype:02x}')
                if partitiontype in OS_MBR_TYPES:
                    reasons.add(OS_MBR_TYPES[partitiontype])
        gpt = readat(handle, int(sectorsize), max(512, int(sectorsize)))
        if gpt[:8] != b'EFI PART':
            return sorted(reasons), types
        try:
            entrieslba = struct.unpack_from('<Q', gpt, 72)[0]
            entrycount = min(struct.unpack_from('<I', gpt, 80)[0], 4096)
            entrysize = struct.unpack_from('<I', gpt, 84)[0]
        except struct.error:
            return ['invalid GPT header'], types
        if entrysize < 128 or entrysize > 4096:
            return ['invalid GPT entry size'], types
        entries = readat(handle, entrieslba * int(sectorsize), entrycount * entrysize)
        if len(entries) != entrycount * entrysize:
            return ['incomplete GPT partition array'], types
        for index in range(entrycount):
            rawtype = entries[index * entrysize:index * entrysize + 16]
            if rawtype == b'\0' * 16:
                continue
            partitiontype = str(uuid.UUID(bytes_le=rawtype))
            types.add(f'gpt:{partitiontype}')
            if partitiontype in OS_GPT_TYPES:
                reasons.add(OS_GPT_TYPES[partitiontype])
    return sorted(reasons), types


def loadpolicy(path=POLICYPATH):
    with Path(path).open('r', encoding='utf-8') as handle:
        loaded = json.load(handle)
    if not isinstance(loaded, dict) or loaded.get('format') != 1:
        raise ValueError('driver policy format is not supported')
    allowed = {normalizemodule(item) for item in loaded.get('allowed_modules', [])}
    allowed.discard('')
    if not allowed:
        raise ValueError('driver policy contains no allowed modules')
    loaded['allowed_modules'] = sorted(allowed)
    loaded['maximum_module_loads'] = max(1, min(int(loaded.get('maximum_module_loads', 64)), 256))
    device_access = []
    for rule in loaded.get('device_access', []):
        if not isinstance(rule, dict):
            raise ValueError('driver device-access rule is not an object')
        pattern = str(rule.get('pattern', '')).strip().replace('\\', '/')
        if not pattern or pattern.startswith('/') or '..' in pattern.split('/'):
            raise ValueError(f'unsafe driver device-access pattern: {pattern}')
        mode_text = str(rule.get('mode', '0000')).strip()
        try:
            mode = int(mode_text, 8)
            group = int(rule.get('group', 0))
        except (TypeError, ValueError) as error:
            raise ValueError(f'invalid driver device-access rule: {pattern}') from error
        if mode < 0 or mode > 0o777 or group < 0 or group > 65535:
            raise ValueError(f'out-of-range driver device-access rule: {pattern}')
        device_access.append({'pattern': pattern, 'mode': mode, 'group': group})
    loaded['device_access'] = device_access

    external = loaded.get('external_volumes', {})
    if not isinstance(external, dict):
        raise ValueError('external volume policy is not an object')
    enabled = bool(external.get('enabled', False))
    allow_all_data = bool(external.get('allow_all_data', False))
    labels = {
        normalizevolumeidentity(item)
        for item in external.get('allowed_labels', [])
        if normalizevolumeidentity(item)
    }
    identities = {
        normalizevolumeidentity(item).replace('-', '')
        for item in external.get('allowed_uuids', [])
        if normalizevolumeidentity(item)
    }
    filesystems = {
        str(item or '').strip().lower()
        for item in external.get('filesystems', [])
        if str(item or '').strip()
    }
    if not filesystems:
        filesystems = set(SUPPORTED_EXTERNAL_FILESYSTEMS)
    unsupported = filesystems.difference(SUPPORTED_EXTERNAL_FILESYSTEMS)
    if unsupported:
        raise ValueError(f'unsafe external volume filesystem policy: {sorted(unsupported)}')
    if enabled and not allow_all_data and not labels and not identities:
        raise ValueError(
            'external volume mounting requires allow_all_data or an explicit label/UUID allowlist'
        )
    loaded['external_volumes'] = {
        'enabled': enabled,
        'allow_all_data': allow_all_data,
        'allowed_labels': sorted(labels),
        'allowed_uuids': sorted(identities),
        'filesystems': sorted(filesystems),
        'read_only': bool(external.get('read_only', False)),
    }
    return loaded


def validatemanifest(moduleroot=MODULEROOT):
    root = Path(moduleroot).resolve()
    manifest = root / 'module-manifest.sha256'
    if not manifest.is_file():
        raise FileNotFoundError(f'module manifest not found: {manifest}')

    checked = 0
    with manifest.open('r', encoding='utf-8') as handle:
        for number, line in enumerate(handle, 1):
            line = line.rstrip('\n')
            if not line:
                continue
            digest = line[:64].lower()
            relative = line[64:].lstrip(' *')
            if len(digest) != 64 or any(character not in '0123456789abcdef' for character in digest):
                raise ValueError(f'invalid module manifest digest on line {number}')
            if not relative:
                raise ValueError(f'missing module manifest path on line {number}')
            candidate = (root / relative).resolve()
            try:
                candidate.relative_to(root)
            except ValueError as error:
                raise ValueError(f'module manifest path escapes its root: {relative}') from error
            if not candidate.is_file():
                raise FileNotFoundError(f'module manifest file not found: {candidate}')
            hasher = hashlib.sha256()
            with candidate.open('rb') as module_file:
                for chunk in iter(lambda: module_file.read(1024 * 1024), b''):
                    hasher.update(chunk)
            actual = hasher.hexdigest()
            if actual != digest:
                raise ValueError(f'module hash mismatch: {relative}')
            checked += 1
    if checked < 1:
        raise ValueError('module manifest is empty')
    return checked


class DriverServer:
    def __init__(self):
        self.policy = loadpolicy()
        try:
            commandline = CMDLINEPATH.read_text(encoding='utf-8', errors='replace')
        except OSError:
            commandline = ''
        self.commandline = commandline
        self.blacklist = parseblacklist(commandline)
        self.module_parameters = parsemoduleparameters(commandline)
        commandrecovery = (
            't1os.graphics=framebuffer' in commandline.split()
        )
        # State from an earlier boot must never suppress GPU discovery on this
        # boot. Firmware-framebuffer mode must be selected explicitly in this
        # boot's kernel command line.
        self.firmware_graphics_recovery = bool(commandrecovery)
        self.firmware_graphics_recovery_source = (
            'kernel-command-line' if commandrecovery else ''
        )
        self.display_recovery_modules = set()
        self.early_boot_animation_retired = False
        self.allowed = set(self.policy['allowed_modules'])
        nvidiadrmparameters = self.module_parameters.setdefault(
            'nvidia_drm',
            {},
        )
        for name, value in NVIDIADRMREQUIREDPARAMETERS.items():
            nvidiadrmparameters[name] = value
        self.maximum = self.policy['maximum_module_loads']
        self.device_access = list(self.policy.get('device_access', []))
        self.volume_policy = dict(self.policy.get('external_volumes', {}))
        self.device_grants = set()
        self.processed_aliases = set()
        self.loaded = set()
        self.failed = {}
        self.skipped = {}
        self.manifest_files = 0
        self.integrity_ready = False
        self.running = True
        self.lock = threading.Lock()
        self.state = 'starting'
        self.started = time.time()
        self.volumes = []
        self.volume_blocks = {}
        self.volume_probe_cache = {}
        self.volume_signature = None
        self.volume_retry = False
        self.abandoned_modprobes = []
        self.graphics_reset_lock = threading.Lock()
        self.graphics_helpers_lock = threading.Lock()
        self.abandoned_graphics_helpers = {}
        self.pending_graphics_helpers = {}
        self.nvidia_device_nodes = []
        self.nvidia_devices = []
        self.nvidia_node_state = 'not-required'
        self.nvidia_uvm_major = None
        self.nvidia_uvm_node_state = 'not-required'
        self.graphics_control_root = CONTROLROOT
        self.graphics_state_root = STATEROOT
        self.graphics_write_timeout = max(
            0.05,
            min(30.0, GRAPHICSRESETWRITETIMEOUT),
        )
        self.graphics_ready_timeout = max(
            0.05,
            min(60.0, GRAPHICSRESETREADYTIMEOUT),
        )

    def snapshot(self):
        with self.lock:
            return {
                'format': 1,
                'state': self.state,
                'kernel_release': os.uname().release,
                'module_root': str(MODULEROOT),
                'firmware_root': str(FIRMWAREROOT),
                'manifest_files': self.manifest_files,
                'integrity_ready': self.integrity_ready,
                'blacklist': sorted(self.blacklist),
                'module_parameters': {
                    module: dict(sorted(options.items()))
                    for module, options in sorted(self.module_parameters.items())
                },
                'firmware_graphics_recovery': self.firmware_graphics_recovery,
                'firmware_graphics_recovery_source': (
                    self.firmware_graphics_recovery_source
                ),
                'display_recovery_modules': sorted(self.display_recovery_modules),
                'loaded': sorted(self.loaded),
                'failed': dict(sorted(self.failed.items())),
                'skipped': dict(sorted(self.skipped.items())),
                'device_grants': sorted(self.device_grants),
                'nvidia_device_nodes': list(self.nvidia_device_nodes),
                'nvidia_devices': [
                    dict(item)
                    for item in self.nvidia_devices
                ],
                'nvidia_node_state': self.nvidia_node_state,
                'nvidia_uvm_major': self.nvidia_uvm_major,
                'nvidia_uvm_node_state': self.nvidia_uvm_node_state,
                'volumes': [dict(item) for item in self.volumes],
                'volume_blocks': dict(sorted(self.volume_blocks.items())),
                'uptime_seconds': round(time.time() - self.started, 3),
            }

    def publish(self):
        try:
            atomicjson(STATUSPATH, self.snapshot())
        except OSError as error:
            log(f'status write failed: {error}')
        try:
            atomicjson(VOLUMESTATUSPATH, {
                'format': 1,
                'volumes': [dict(item) for item in self.volumes],
            })
        except OSError as error:
            log(f'volume status write failed: {error}')

    def setstate(self, state):
        with self.lock:
            self.state = state
        self.publish()

    def reapgraphicshelpers(self):
        if not hasattr(os, 'waitpid'):
            return

        with self.graphics_helpers_lock:
            for pid, helper in list(self.abandoned_graphics_helpers.items()):
                try:
                    reaped, _ = os.waitpid(pid, os.WNOHANG)
                except ChildProcessError:
                    reaped = pid
                except OSError:
                    continue
                if reaped != pid:
                    continue

                descriptor = helper.get('result_descriptor', -1)
                if descriptor >= 0:
                    try:
                        os.close(descriptor)
                    except OSError:
                        pass
                bdf = helper.get('bdf', '')
                if self.pending_graphics_helpers.get(bdf) == pid:
                    self.pending_graphics_helpers.pop(bdf, None)
                self.abandoned_graphics_helpers.pop(pid, None)
                log(
                    f'graphics reset helper reaped pid={pid} '
                    f'bdf={bdf} phase={helper.get("phase", "")}'
                )

    def boundedgraphicswrite(self, path, value, bdf, phase, timeout=None):
        self.reapgraphicshelpers()
        timeout = (
            self.graphics_write_timeout
            if timeout is None
            else max(0.05, min(30.0, float(timeout)))
        )

        with self.graphics_helpers_lock:
            pending = self.pending_graphics_helpers.get(bdf)
            if pending is not None:
                return {
                    'ok': False,
                    'errno': errno.EBUSY,
                    'phase': phase,
                    'message': (
                        f'previous graphics reset helper {pending} remains '
                        f'blocked for {bdf}'
                    ),
                    'timed_out': False,
                }

        if not hasattr(os, 'fork'):
            return {
                'ok': False,
                'errno': errno.ENOSYS,
                'phase': phase,
                'message': 'forked sysfs writes are unavailable',
                'timed_out': False,
            }

        pathbytes = os.fsencode(str(path))
        valuebytes = str(value).encode('ascii')
        try:
            resultread, resultwrite = os.pipe()
        except OSError as error:
            return {
                'ok': False,
                'errno': error.errno or errno.EIO,
                'phase': phase,
                'message': f'could not create helper status pipe: {error}',
                'timed_out': False,
            }

        try:
            pid = os.fork()
        except OSError as error:
            os.close(resultread)
            os.close(resultwrite)
            return {
                'ok': False,
                'errno': error.errno or errno.EIO,
                'phase': phase,
                'message': f'could not fork graphics reset helper: {error}',
                'timed_out': False,
            }

        if pid == 0:
            # Do not exec: the inherited DriverServer argv is part of the T1OS
            # LSM identity used to authorize writes to the private sysfs mount.
            try:
                os.close(resultread)
                descriptor = -1
                errornumber = 0
                try:
                    descriptor = os.open(
                        pathbytes,
                        os.O_WRONLY | getattr(os, 'O_CLOEXEC', 0),
                    )
                    written = os.write(descriptor, valuebytes)
                    if written != len(valuebytes):
                        errornumber = errno.EIO
                except OSError as error:
                    errornumber = error.errno or errno.EIO
                except BaseException:
                    errornumber = errno.EIO
                finally:
                    if descriptor >= 0:
                        try:
                            os.close(descriptor)
                        except OSError:
                            if not errornumber:
                                errornumber = errno.EIO

                if errornumber:
                    try:
                        os.write(
                            resultwrite,
                            int(errornumber).to_bytes(4, 'little', signed=False),
                        )
                    except OSError:
                        pass
                    os._exit(1)
                os._exit(0)
            except BaseException:
                os._exit(1)

        os.close(resultwrite)
        deadline = time.monotonic() + timeout
        status = None
        while time.monotonic() < deadline:
            try:
                reaped, status = os.waitpid(pid, os.WNOHANG)
            except InterruptedError:
                continue
            except ChildProcessError:
                os.close(resultread)
                return {
                    'ok': False,
                    'errno': errno.ECHILD,
                    'phase': phase,
                    'message': f'graphics reset helper {pid} was lost',
                    'timed_out': False,
                }
            if reaped == pid:
                break
            time.sleep(0.01)
        else:
            try:
                os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, OSError):
                pass

            try:
                reaped, status = os.waitpid(pid, os.WNOHANG)
            except (ChildProcessError, OSError):
                reaped = 0
            if reaped == pid:
                os.close(resultread)
            else:
                with self.graphics_helpers_lock:
                    self.abandoned_graphics_helpers[pid] = {
                        'bdf': bdf,
                        'phase': phase,
                        'started': time.monotonic(),
                        'result_descriptor': resultread,
                    }
                    self.pending_graphics_helpers[bdf] = pid
            return {
                'ok': False,
                'errno': errno.ETIMEDOUT,
                'phase': phase,
                'message': (
                    f'helper {pid} timed out after {timeout:.2f}s '
                    f'writing {path}'
                ),
                'timed_out': True,
                'helper_pid': pid,
            }

        errorbytes = b''
        try:
            errorbytes = os.read(resultread, 4)
        except OSError:
            pass
        finally:
            os.close(resultread)

        if os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0:
            return {
                'ok': True,
                'errno': 0,
                'phase': phase,
                'message': 'ok',
                'timed_out': False,
                'helper_pid': pid,
            }

        errornumber = (
            int.from_bytes(errorbytes, 'little', signed=False)
            if len(errorbytes) == 4
            else errno.EIO
        )
        if os.WIFSIGNALED(status):
            message = (
                f'helper {pid} was terminated by signal '
                f'{os.WTERMSIG(status)} writing {path}'
            )
        else:
            message = (
                f'helper {pid} failed writing {path}: '
                f'{os.strerror(errornumber)}'
            )
        return {
            'ok': False,
            'errno': errornumber,
            'phase': phase,
            'message': message,
            'timed_out': False,
            'helper_pid': pid,
        }

    def nvidiaresetreadiness(self, bdf, wait=0.0):
        """Require NVIDIA procfs ownership and every userspace device node."""
        bdf = str(bdf or '').strip().lower()
        deadline = time.monotonic() + max(
            0.0,
            min(float(wait), 5.0),
        )
        devices = []
        while True:
            if not self.reconcilenvidianodes(
                wait=0.0,
                transient_unclaimed=True,
            ):
                detail = getattr(self, 'failed', {}).get(
                    'nvidia-device-nodes',
                    'NVIDIA device-node reconciliation failed',
                )
                return {
                    'ok': False,
                    'phase': 'wait-nvidia-nodes',
                    'errno': errno.EIO,
                    'message': detail,
                }

            devices = [
                dict(device)
                for device in getattr(self, 'nvidia_devices', [])
            ]
            target = next(
                (
                    device
                    for device in devices
                    if str(device.get('bdf', '')).strip().lower() == bdf
                ),
                None,
            )
            if target is not None:
                break
            if time.monotonic() >= deadline:
                return {
                    'ok': False,
                    'phase': 'wait-nvidia-proc',
                    'errno': errno.ETIMEDOUT,
                    'message': (
                        f'NVIDIA reclaimed {bdf}, but '
                        'the NVIDIA kernel GPU inventory did not report it'
                    ),
                    'nvidia_devices': devices,
                }
            time.sleep(0.05)

        uvmrequired = 'nvidia_uvm' in getattr(self, 'loaded', set())
        if uvmrequired and not self.reconcilenvidiauvmnode(
            wait=max(0.0, deadline - time.monotonic()),
        ):
            detail = getattr(self, 'failed', {}).get(
                'nvidia-uvm-device-node',
                'NVIDIA UVM device-node reconciliation failed',
            )
            return {
                'ok': False,
                'phase': 'wait-nvidia-uvm',
                'errno': errno.EIO,
                'message': detail,
                'nvidia_devices': devices,
                'nvidia_device_nodes': sorted(
                    getattr(self, 'nvidia_device_nodes', [])
                ),
            }

        expectednodes = {
            'nvidiactl',
            'nvidia-modeset',
            *[
                f'nvidia{int(device["minor"])}'
                for device in devices
            ],
        }
        if uvmrequired:
            expectednodes.add('nvidia-uvm')
        reportednodes = set(
            getattr(self, 'nvidia_device_nodes', [])
        )
        missingnodes = sorted(expectednodes - reportednodes)
        nodestate = str(
            getattr(self, 'nvidia_node_state', '')
        ).strip()
        if nodestate != 'ready' or missingnodes:
            detail = (
                f'NVIDIA node state is {nodestate or "unknown"}'
                if nodestate != 'ready'
                else f'NVIDIA nodes missing after reconciliation: {missingnodes}'
            )
            return {
                'ok': False,
                'phase': 'wait-nvidia-nodes',
                'errno': errno.EIO,
                'message': detail,
                'nvidia_devices': devices,
                'nvidia_device_nodes': sorted(reportednodes),
            }

        return {
            'ok': True,
            'phase': 'ready',
            'errno': 0,
            'message': 'NVIDIA procfs and userspace device nodes are ready',
            'nvidia_devices': devices,
            'nvidia_device_nodes': sorted(reportednodes),
        }

    def resetgraphicsrequest(
        self,
        request,
        peer,
        *,
        ownershipvalidator=None,
        writefunction=None,
        driverlookup=None,
        drmfinder=None,
        pathexists=None,
        monotonic=None,
        sleep=None,
    ):
        started = time.monotonic()
        bdf = ''
        driver = ''
        try:
            bdf, driver = parsegraphicsresetrequest(request, peer)
        except GraphicsResetError as error:
            return graphicsresetresponse(
                False,
                error.phase,
                error.errornumber,
                error.message,
            )

        if not self.graphics_reset_lock.acquire(blocking=False):
            return graphicsresetresponse(
                False,
                'serialize',
                errno.EBUSY,
                'another graphics reset request is active',
                bdf,
                driver,
            )

        ownershipvalidator = ownershipvalidator or (
            lambda candidate, owner: validategraphicsownership(
                candidate,
                owner,
                self.graphics_control_root,
                self.graphics_state_root,
            )
        )
        writefunction = writefunction or self.boundedgraphicswrite
        driverlookup = driverlookup or (
            lambda candidate: currentpcidriver(
                self.graphics_state_root,
                candidate,
            )
        )
        drmfinder = drmfinder or (
            lambda candidate: pcidrmnodes(
                candidate,
                self.graphics_state_root,
            )
        )
        pathexists = pathexists or os.path.exists
        monotonic = monotonic or time.monotonic
        sleep = sleep or time.sleep
        operations = []
        warnings = []

        def finish(success, phase, errornumber, message, **details):
            details['elapsed_seconds'] = round(
                time.monotonic() - started,
                3,
            )
            details['operations'] = operations
            if warnings:
                details['warnings'] = warnings
            return graphicsresetresponse(
                success,
                phase,
                errornumber,
                message,
                bdf,
                driver,
                **details,
            )

        try:
            self.reapgraphicshelpers()
            with self.graphics_helpers_lock:
                pending = self.pending_graphics_helpers.get(bdf)
            if pending is not None:
                return finish(
                    False,
                    'serialize',
                    errno.EBUSY,
                    f'blocked helper {pending} still owns reset state for {bdf}',
                    helper_pid=pending,
                )

            try:
                ownershipvalidator(bdf, driver)
            except GraphicsResetError as error:
                return finish(
                    False,
                    error.phase,
                    error.errornumber,
                    error.message,
                )
            except OSError as error:
                return finish(
                    False,
                    'validate-owner',
                    error.errno or errno.EIO,
                    str(error),
                )

            driverroot = (
                Path(self.graphics_control_root)
                / 'bus/pci/drivers'
                / driver
            )
            unbindpath = driverroot / 'unbind'
            unbind = writefunction(
                unbindpath,
                bdf,
                bdf,
                'unbind',
            )
            operations.append(dict(unbind))
            if not unbind.get('ok'):
                if unbind.get('timed_out') or driverlookup(bdf) == driver:
                    return finish(
                        False,
                        'unbind',
                        unbind.get('errno') or errno.EIO,
                        unbind.get('message') or 'PCI driver unbind failed',
                        helper_pid=unbind.get('helper_pid', 0),
                    )
                warnings.append(
                    'unbind helper reported an error after ownership disappeared'
                )

            unbinddeadline = monotonic() + min(
                1.0,
                self.graphics_ready_timeout,
            )
            while (
                driverlookup(bdf) == driver
                and monotonic() < unbinddeadline
            ):
                sleep(0.02)
            if driverlookup(bdf) == driver:
                return finish(
                    False,
                    'unbind-state',
                    errno.ETIMEDOUT,
                    f'{driver} still owns {bdf} after unbind',
                )

            resetpath = (
                Path(self.graphics_control_root)
                / 'bus/pci/devices'
                / bdf
                / 'reset'
            )
            resetattempted = bool(pathexists(resetpath))
            resetcomplete = False
            if resetattempted:
                reset = writefunction(
                    resetpath,
                    '1',
                    bdf,
                    'function-reset',
                )
                operations.append(dict(reset))
                resetcomplete = bool(reset.get('ok'))
                if not resetcomplete:
                    if reset.get('timed_out'):
                        return finish(
                            False,
                            'function-reset',
                            reset.get('errno') or errno.ETIMEDOUT,
                            reset.get('message') or 'PCI function reset timed out',
                            helper_pid=reset.get('helper_pid', 0),
                            pci_reset_attempted=True,
                            pci_reset_complete=False,
                        )
                    warnings.append(
                        'optional PCI function reset failed: '
                        + str(reset.get('message') or 'unknown error')
                    )

            bindpath = driverroot / 'bind'
            probepath = (
                Path(self.graphics_control_root)
                / 'bus/pci/drivers_probe'
            )
            bindmethod = ''
            binderror = None
            if pathexists(bindpath):
                bind = writefunction(
                    bindpath,
                    bdf,
                    bdf,
                    'bind',
                )
                operations.append(dict(bind))
                if bind.get('ok'):
                    bindmethod = 'bind'
                else:
                    binderror = bind
                    if bind.get('timed_out'):
                        return finish(
                            False,
                            'bind',
                            bind.get('errno') or errno.ETIMEDOUT,
                            bind.get('message') or 'PCI driver bind timed out',
                            helper_pid=bind.get('helper_pid', 0),
                            pci_reset_attempted=resetattempted,
                            pci_reset_complete=resetcomplete,
                        )

            if not bindmethod and driverlookup(bdf) != driver:
                if not pathexists(probepath):
                    return finish(
                        False,
                        'probe',
                        (
                            binderror.get('errno')
                            if binderror is not None
                            else errno.ENOENT
                        ),
                        (
                            (
                                binderror.get('message', '')
                                + '; PCI drivers_probe is absent'
                            ).strip('; ')
                            if binderror is not None
                            else f'PCI drivers_probe is absent: {probepath}'
                        ),
                        pci_reset_attempted=resetattempted,
                        pci_reset_complete=resetcomplete,
                    )
                probe = writefunction(
                    probepath,
                    bdf,
                    bdf,
                    'probe',
                )
                operations.append(dict(probe))
                if not probe.get('ok'):
                    return finish(
                        False,
                        'probe',
                        probe.get('errno') or errno.EIO,
                        probe.get('message') or 'PCI driver reprobe failed',
                        helper_pid=probe.get('helper_pid', 0),
                        pci_reset_attempted=resetattempted,
                        pci_reset_complete=resetcomplete,
                    )
                bindmethod = 'drivers_probe'
            elif not bindmethod:
                bindmethod = 'already-bound'

            readydeadline = monotonic() + self.graphics_ready_timeout
            nodes = []
            while monotonic() < readydeadline:
                if driverlookup(bdf) == driver:
                    nodes = drmfinder(bdf)
                    if nodes:
                        break
                sleep(0.05)
            if driverlookup(bdf) != driver:
                return finish(
                    False,
                    'wait-driver',
                    errno.ETIMEDOUT,
                    f'{driver} did not reclaim {bdf}',
                    bind_method=bindmethod,
                    pci_reset_attempted=resetattempted,
                    pci_reset_complete=resetcomplete,
                )
            if not nodes:
                return finish(
                    False,
                    'wait-drm',
                    errno.ETIMEDOUT,
                    f'{driver} reclaimed {bdf}, but no DRM node appeared',
                    bind_method=bindmethod,
                    pci_reset_attempted=resetattempted,
                    pci_reset_complete=resetcomplete,
                )

            nvidiareadiness = None
            if normalizemodule(driver) == 'nvidia':
                nvidiareadiness = self.nvidiaresetreadiness(
                    bdf,
                    wait=max(0.0, readydeadline - monotonic()),
                )
                if not nvidiareadiness.get('ok'):
                    return finish(
                        False,
                        nvidiareadiness.get(
                            'phase',
                            'wait-nvidia-nodes',
                        ),
                        nvidiareadiness.get('errno') or errno.EIO,
                        nvidiareadiness.get('message')
                        or 'NVIDIA userspace devices did not become ready',
                        bind_method=bindmethod,
                        pci_reset_attempted=resetattempted,
                        pci_reset_complete=resetcomplete,
                        drm_nodes=nodes,
                        nvidia_devices=nvidiareadiness.get(
                            'nvidia_devices',
                            [],
                        ),
                        nvidia_device_nodes=nvidiareadiness.get(
                            'nvidia_device_nodes',
                            [],
                        ),
                    )

            completedetails = {
                'bind_method': bindmethod,
                'pci_reset_attempted': resetattempted,
                'pci_reset_complete': resetcomplete,
                'drm_nodes': nodes,
            }
            if nvidiareadiness is not None:
                completedetails.update({
                    'nvidia_devices': nvidiareadiness.get(
                        'nvidia_devices',
                        [],
                    ),
                    'nvidia_device_nodes': nvidiareadiness.get(
                        'nvidia_device_nodes',
                        [],
                    ),
                })
            return finish(
                True,
                'complete',
                0,
                'graphics PCI function reinitialized',
                **completedetails,
            )
        finally:
            self.graphics_reset_lock.release()

    def receivestatusrequest(self, connection):
        request = connection.recv(GRAPHICSRESETREQUESTLIMIT + 1)
        if request.strip().upper() == b'STATUS':
            return request

        while b'\n' not in request:
            if len(request) > GRAPHICSRESETREQUESTLIMIT:
                raise GraphicsResetError(
                    'request',
                    errno.E2BIG,
                    'request exceeds the maximum length',
                )
            chunk = connection.recv(
                GRAPHICSRESETREQUESTLIMIT + 1 - len(request)
            )
            if not chunk:
                raise GraphicsResetError(
                    'request',
                    errno.EINVAL,
                    'JSON request must end with a newline',
                )
            request += chunk

        line, remainder = request.split(b'\n', 1)
        if remainder.strip():
            raise GraphicsResetError(
                'request',
                errno.EINVAL,
                'only one request is allowed per connection',
            )
        if len(line) > GRAPHICSRESETREQUESTLIMIT:
            raise GraphicsResetError(
                'request',
                errno.E2BIG,
                'request exceeds the maximum length',
            )
        return line

    def statusserver(self):
        RUNTIMEROOT.mkdir(parents=True, exist_ok=True)
        try:
            SOCKETPATH.unlink()
        except FileNotFoundError:
            pass
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(str(SOCKETPATH))
        os.chmod(SOCKETPATH, 0o600)
        listener.listen(8)
        listener.settimeout(1.0)
        while self.running:
            try:
                connection, _ = listener.accept()
            except socket.timeout:
                self.reapgraphicshelpers()
                continue
            except OSError:
                break
            with connection:
                try:
                    connection.settimeout(1.0)
                    encoded = self.receivestatusrequest(connection)
                    if encoded.strip().upper() == b'STATUS':
                        response = self.snapshot()
                    else:
                        try:
                            request = json.loads(encoded.decode('utf-8'))
                        except (UnicodeDecodeError, json.JSONDecodeError) as error:
                            response = graphicsresetresponse(
                                False,
                                'request',
                                errno.EINVAL,
                                f'invalid JSON request: {error}',
                            )
                        else:
                            if (
                                not isinstance(request, dict)
                                or request.get('request') != 'RESET_GRAPHICS'
                            ):
                                response = {
                                    'state': 'error',
                                    'message': 'unknown request',
                                }
                            else:
                                try:
                                    peer = peercredentials(connection)
                                except GraphicsResetError as error:
                                    response = graphicsresetresponse(
                                        False,
                                        error.phase,
                                        error.errornumber,
                                        error.message,
                                    )
                                else:
                                    response = self.resetgraphicsrequest(
                                        request,
                                        peer,
                                    )
                                    log(
                                        'graphics reset request '
                                        f'bdf={response.get("bdf", "")} '
                                        f'driver={response.get("driver", "")} '
                                        f'state={response.get("state")} '
                                        f'phase={response.get("phase")} '
                                        f'errno={response.get("errno")}'
                                    )
                    connection.sendall(
                        json.dumps(response, sort_keys=True).encode('utf-8')
                        + b'\n'
                    )
                except GraphicsResetError as error:
                    try:
                        connection.sendall(
                            json.dumps(graphicsresetresponse(
                                False,
                                error.phase,
                                error.errornumber,
                                error.message,
                            ), sort_keys=True).encode('utf-8')
                            + b'\n'
                        )
                    except OSError:
                        pass
                except OSError:
                    pass
        listener.close()

    def configurefirmware(self):
        parameter = CONTROLROOT / 'module/firmware_class/parameters/path'
        if not FIRMWAREROOT.is_dir():
            raise FileNotFoundError(f'firmware root not found: {FIRMWAREROOT}')
        with parameter.open('w', encoding='ascii') as handle:
            handle.write(str(FIRMWAREROOT))
        log(f'firmware search path {FIRMWAREROOT}')

    def runmodprobe(self, arguments, timeout=30):
        remaining = []

        for process in self.abandoned_modprobes:
            if process.poll() is None:
                remaining.append(process)

        self.abandoned_modprobes = remaining

        with (
            tempfile.TemporaryFile(mode='w+t', encoding='utf-8') as output,
            tempfile.TemporaryFile(mode='w+t', encoding='utf-8') as errors,
        ):
            nullinput = None

            try:
                nullinput = NULLDEVICE.open('rb', buffering=0)
                process = subprocess.Popen(
                    [str(MODPROBE), *arguments],
                    stdin=nullinput,
                    stdout=output,
                    stderr=errors,
                    text=True,
                    start_new_session=True,
                )
            except OSError as error:
                return 127, '', f'{type(error).__name__}: {error}'
            finally:
                if nullinput is not None:
                    nullinput.close()

            deadline = time.monotonic() + max(0.1, float(timeout))

            while time.monotonic() < deadline:
                status = process.poll()

                if status is not None:
                    output.flush()
                    errors.flush()
                    output.seek(0)
                    errors.seek(0)
                    return status, output.read().strip(), errors.read().strip()

                time.sleep(0.02)

            # Module init and removal can remain in uninterruptible kernel
            # sleep. Never let DriverServer's recovery policy inherit
            # subprocess.run()'s unbounded post-timeout wait.
            try:
                process.kill()
            except (ProcessLookupError, OSError):
                pass

            self.abandoned_modprobes.append(process)
            return 124, '', f'modprobe timed out after {float(timeout):.1f}s'

    def resolvemodules(self, alias):
        status, output, _ = self.runmodprobe(['--resolve-alias', alias], timeout=10)
        if status != 0:
            return []
        return sorted({normalizemodule(line) for line in output.splitlines() if normalizemodule(line)})

    def verifymoduleparameters(self, module):
        failures = []

        for name, expected in sorted(
            self.module_parameters.get(module, {}).items()
        ):
            parameter = CONTROLROOT / 'module' / module / 'parameters' / name

            try:
                actual = parameter.read_text(
                    encoding='utf-8',
                    errors='replace',
                ).strip()
            except OSError as error:
                failures.append(f'{name}=unreadable ({error})')
                continue

            if not moduleparametermatches(
                module,
                name,
                expected,
                actual,
            ):
                failures.append(
                    f'{name}=expected {expected!r}, live {actual!r}'
                )
            else:
                log(f'module parameter verified {module}.{name}={actual}')

        return failures

    def reconcilenvidianodes(
        self,
        *,
        devicespath=NVIDIADEVICESPATH,
        gpuroot=NVIDIAGPUROOT,
        noderoot=NVIDIANODEROOT,
        wait=0.0,
        transient_unclaimed=False,
    ):
        """Materialize the NVIDIA nodes normally created by udev."""
        failurekey = 'nvidia-device-nodes'
        deadline = time.monotonic() + max(0.0, min(float(wait), 5.0))
        previousstate = self.nvidia_node_state
        previousdevices = [dict(device) for device in self.nvidia_devices]
        previousnodes = list(self.nvidia_device_nodes)
        previousfrontendnodes = [
            name for name in previousnodes if name != 'nvidia-uvm'
        ]
        retainedservicenodes = [
            name for name in previousnodes if name == 'nvidia-uvm'
        ]
        devices = []
        while True:
            try:
                devices = nvidiagpuminors(gpuroot)
            except (OSError, ValueError) as error:
                previous = self.failed.get(failurekey)
                detail = f'GPU minor discovery failed: {error}'[:512]
                self.failed[failurekey] = detail
                self.nvidia_node_state = 'failed'
                if previous != detail:
                    log(f'NVIDIA device-node setup failed: {detail}')
                if getattr(self, 'state', 'starting') == 'ready':
                    self.setstate('degraded')
                return False
            if devices or time.monotonic() >= deadline:
                break
            time.sleep(0.05)

        if not devices:
            # During an authorized reset, the module can be bound before its
            # procfs GPU inventory is repopulated. Do not publish that brief
            # interval as an unclaimed device or imply that Nouveau should
            # probe while the reset transaction still owns the NVIDIA GPU.
            if transient_unclaimed:
                # Never leave the pre-reset inventory visible. Readiness must
                # be proved by a fresh NVIDIA procfs GPU discovery,
                # otherwise a fast poll can mistake stale nodes for a
                # successfully reclaimed adapter.
                self.nvidia_devices = []
                self.nvidia_device_nodes = []
                self.nvidia_node_state = 'reclaiming'
                return True

            # A successfully inserted module with no NVIDIA procfs GPU
            # entries did not claim a device. Leave Nouveau available for
            # unsupported/older hardware rather than fabricating GPU nodes.
            self.nvidia_devices = []
            self.nvidia_device_nodes = []
            self.nvidia_node_state = 'unclaimed'
            self.skipped[failurekey] = (
                'official NVIDIA module did not claim a GPU; Nouveau remains '
                'available'
            )
            if previousstate != 'unclaimed':
                log(
                    'official NVIDIA module reported no claimed GPUs; '
                    'continuing to Nouveau'
                )
            return True

        try:
            rootstatus = Path(noderoot).lstat()
            if not stat.S_ISDIR(rootstatus.st_mode):
                raise ValueError(
                    f'NVIDIA node root is not a directory: {noderoot}'
                )
            major = nvidiafrontendmajor(devicespath)
            specifications = [
                ('nvidiactl', NVIDIACONTROLMINOR),
                ('nvidia-modeset', NVIDIAMODESETMINOR),
                *[
                    (f'nvidia{device["minor"]}', device['minor'])
                    for device in devices
                ],
            ]
            created = []
            for name, minor in specifications:
                path = Path(noderoot) / name
                if ensurenvidiacharnode(path, major, minor):
                    created.append(name)
                self.device_grants.add(name)
            self.nvidia_devices = [dict(device) for device in devices]
            frontendnodes = [
                name
                for name, _ in specifications
            ]
            # UVM is reconciled independently after the frontend nodes. Keep
            # its already-proven node in the published inventory so the
            # once-per-second access pass does not remove/re-add it and report
            # an unchanged frontend as a state transition on every pass.
            self.nvidia_device_nodes = frontendnodes + retainedservicenodes
            self.nvidia_node_state = 'ready'
            self.failed.pop(failurekey, None)
            self.skipped.pop(failurekey, None)
            if (
                previousstate != 'ready'
                or previousdevices != self.nvidia_devices
                or previousfrontendnodes != frontendnodes
                or created
            ):
                log(
                    f'NVIDIA device nodes ready major={major} '
                    f'nodes={self.nvidia_device_nodes} '
                    f'created={created or "none"} '
                    f'group={NVIDIANODEGROUP} mode={NVIDIANODEMODE:04o}'
                )
            if (
                getattr(self, 'state', 'starting') == 'degraded'
                and not self.failed
            ):
                self.setstate('ready')
            return True
        except (OSError, ValueError) as error:
            previous = self.failed.get(failurekey)
            detail = str(error)[:512]
            self.failed[failurekey] = detail
            self.nvidia_devices = [dict(device) for device in devices]
            self.nvidia_node_state = 'failed'
            if previous != detail:
                log(f'NVIDIA device-node setup failed: {detail}')
            if getattr(self, 'state', 'starting') == 'ready':
                self.setstate('degraded')
            return False

    def reconcilenvidiauvmnode(
        self,
        *,
        devicespath=NVIDIADEVICESPATH,
        noderoot=NVIDIANODEROOT,
        wait=0.0,
    ):
        """Materialize only UVM's primary minor after nvidia_uvm is loaded."""
        failurekey = 'nvidia-uvm-device-node'
        deadline = time.monotonic() + max(0.0, min(float(wait), 5.0))
        previousstate = getattr(
            self,
            'nvidia_uvm_node_state',
            'not-required',
        )
        previousmajor = getattr(self, 'nvidia_uvm_major', None)
        major = None
        registrationerror = None

        while True:
            try:
                major = nvidiauvmmajor(devicespath)
                break
            except (OSError, ValueError) as error:
                registrationerror = error
                if time.monotonic() >= deadline:
                    break
                time.sleep(0.05)

        try:
            if major is None:
                raise ValueError(
                    'UVM registration did not become ready: '
                    f'{registrationerror}'
                )
            rootstatus = Path(noderoot).lstat()
            if not stat.S_ISDIR(rootstatus.st_mode):
                raise ValueError(
                    f'NVIDIA node root is not a directory: {noderoot}'
                )

            name = 'nvidia-uvm'
            path = Path(noderoot) / name
            created = ensurenvidiacharnode(
                path,
                major,
                NVIDIAUVMMINOR,
            )
            self.device_grants.add(name)
            self.nvidia_device_nodes = [
                node
                for node in self.nvidia_device_nodes
                if node != name
            ] + [name]
            self.nvidia_uvm_major = major
            self.nvidia_uvm_node_state = 'ready'
            self.failed.pop(failurekey, None)
            self.skipped.pop(failurekey, None)
            if (
                previousstate != 'ready'
                or previousmajor != major
                or created
            ):
                log(
                    f'NVIDIA UVM node ready major={major} '
                    f'minor={NVIDIAUVMMINOR} created={created} '
                    f'group={NVIDIANODEGROUP} mode={NVIDIANODEMODE:04o}'
                )
            if (
                getattr(self, 'state', 'starting') == 'degraded'
                and not self.failed
            ):
                self.setstate('ready')
            return True
        except (OSError, ValueError) as error:
            detail = str(error)[:512]
            previous = self.failed.get(failurekey)
            self.failed[failurekey] = detail
            self.nvidia_device_nodes = [
                node
                for node in self.nvidia_device_nodes
                if node != 'nvidia-uvm'
            ]
            self.nvidia_uvm_major = None
            self.nvidia_uvm_node_state = 'failed'
            if previous != detail:
                log(f'NVIDIA UVM device-node setup failed: {detail}')
            if getattr(self, 'state', 'starting') == 'ready':
                self.setstate('degraded')
            return False

    def loadnvidiauvm(self, source='nvidia'):
        """Load UVM only after NVIDIA's display stack has claimed a GPU."""
        module = 'nvidia_uvm'
        if module in self.loaded:
            return self.reconcilenvidiauvmnode(wait=2.0)
        if len(self.loaded) >= self.maximum:
            self.failed[module] = 'module-load policy limit reached'
            self.nvidia_uvm_node_state = 'module-failed'
            return False
        if module in self.blacklist:
            self.skipped[module] = 'kernel command-line blacklist'
            self.nvidia_uvm_node_state = 'blocked'
            log(f'skipped blacklisted module {module} source={source}')
            return False
        if module not in self.allowed:
            self.skipped[module] = 'not allowed by T1OS driver policy'
            self.nvidia_uvm_node_state = 'blocked'
            log(f'skipped disallowed module {module} source={source}')
            return False

        log(
            f'loading module {module} source={source} '
            'dependency=nvidia'
        )
        status, _, error = self.runmodprobe(
            ['--use-blacklist', module]
        )
        if status != 0:
            detail = (
                error.splitlines()[-1]
                if error
                else f'modprobe exit {status}'
            )
            self.failed[module] = detail[:512]
            self.nvidia_uvm_node_state = 'module-failed'
            log(f'module {module} failed source={source}: {detail}')
            return False

        self.loaded.add(module)
        self.failed.pop(module, None)
        self.skipped.pop(module, None)
        self.nvidia_uvm_node_state = 'loading'
        log(f'loaded module {module} source={source}')
        return self.reconcilenvidiauvmnode(wait=2.0)

    def handlealias(self, alias, source='coldplug'):
        alias = str(alias or '').strip()
        if not self.integrity_ready or not alias or alias in self.processed_aliases:
            return
        self.processed_aliases.add(alias)
        modules = orderedaliasmodules(alias, self.resolvemodules(alias))
        nvidiaclaimed = False

        if pcidisplayalias(alias) and not self.early_boot_animation_retired:
            self.early_boot_animation_retired = retireearlybootanimation()
            if not self.early_boot_animation_retired:
                for module in modules:
                    self.skipped[aliasloadmodule(alias, module)] = (
                        'early framebuffer owner could not be retired safely'
                    )
                self.failed['display-owner-handoff'] = (
                    'native display binding blocked while the early firmware '
                    'framebuffer writer remained alive'
                )
                self.publish()
                return

        if self.firmware_graphics_recovery and pcidisplayalias(alias):
            self.display_recovery_modules.update(modules)

        for module in modules:
            if module == 'nouveau' and nvidiaclaimed:
                bindings = pcialiasbindings(
                    alias,
                    self.graphics_state_root,
                )
                nvidiaclaimed = nvidiaaliasclaimed(bindings)
                ownership = ','.join(
                    f'{binding["bdf"]}={binding["driver"] or "unbound"}'
                    for binding in bindings
                )
                if nvidiaclaimed:
                    self.skipped[module] = (
                        'official NVIDIA driver owns every matching PCI '
                        'display function'
                    )
                    log(
                        f'skipped fallback module {module} source={source} '
                        f'ownership={ownership or "unavailable"}'
                    )
                    continue

            loadmodule = aliasloadmodule(alias, module)
            if len(self.loaded) >= self.maximum:
                self.failed[loadmodule] = 'module-load policy limit reached'
                continue
            if module in self.blacklist or loadmodule in self.blacklist:
                self.skipped[loadmodule] = 'kernel command-line blacklist'
                log(
                    f'skipped blacklisted module {loadmodule} '
                    f'alias_module={module} source={source}'
                )
                continue
            if (
                self.firmware_graphics_recovery
                and module in self.display_recovery_modules
            ):
                self.skipped[module] = (
                    'explicit command-line framebuffer graphics recovery'
                )
                log(
                    f'skipped native display module {module} '
                    f'source={source} recovery=firmware-framebuffer'
                )
                continue
            if module not in self.allowed or loadmodule not in self.allowed:
                self.skipped[loadmodule] = (
                    'not allowed by T1OS driver policy'
                )
                continue
            options = [
                f'{name}={value}'
                for name, value in sorted(
                    self.module_parameters.get(loadmodule, {}).items()
                )
            ]
            log(
                f'loading module {loadmodule} alias_module={module} '
                f'source={source} '
                f'parameters={options or "none"}'
            )
            status, _, error = self.runmodprobe(
                ['--use-blacklist', loadmodule, *options]
            )
            if status == 0:
                self.loaded.add(loadmodule)
                self.failed.pop(loadmodule, None)
                log(f'loaded module {loadmodule} source={source}')
                parameterfailures = self.verifymoduleparameters(loadmodule)

                if parameterfailures:
                    detail = '; '.join(parameterfailures)[:512]
                    self.failed[loadmodule] = (
                        f'live module parameter mismatch: {detail}'
                    )
                    log(
                        f'module {loadmodule} parameter verification failed: '
                        f'{detail}'
                    )
                if loadmodule == 'nvidia_drm':
                    nodesready = self.reconcilenvidianodes(wait=2.0)
                    bindings = pcialiasbindings(
                        alias,
                        self.graphics_state_root,
                    )
                    nvidiaclaimed = nvidiaaliasclaimed(bindings)
                    ownership = ','.join(
                        f'{binding["bdf"]}={binding["driver"] or "unbound"}'
                        for binding in bindings
                    )
                    log(
                        'official NVIDIA PCI ownership '
                        f'claimed={nvidiaclaimed} '
                        f'bindings={ownership or "none"}'
                    )
                    if nvidiaclaimed and nodesready:
                        self.loadnvidiauvm(source=source)
            else:
                detail = error.splitlines()[-1] if error else f'modprobe exit {status}'
                self.failed[loadmodule] = detail[:512]
                log(
                    f'module {loadmodule} failed source={source}: {detail}'
                )
        self.publish()

    def coldplug(self):
        aliases = set()
        devices = STATEROOT / 'devices'
        for root, directories, files in os.walk(devices, followlinks=False):
            directories.sort()
            if 'modalias' not in files:
                continue
            try:
                alias = (Path(root) / 'modalias').read_text(encoding='ascii', errors='replace').strip()
            except OSError:
                continue
            if alias:
                aliases.add(alias)
        log(f'coldplug discovered aliases={len(aliases)}')

        if self.firmware_graphics_recovery:
            for alias in sorted(aliases):
                if pcidisplayalias(alias):
                    self.display_recovery_modules.update(
                        self.resolvemodules(alias)
                    )

            log(
                'firmware-framebuffer recovery active; native display '
                f'modules blocked={sorted(self.display_recovery_modules)}'
            )

        for alias in sorted(aliases):
            self.handlealias(alias, source='coldplug')

    def applydeviceaccess(self):
        noderoot = DRIVERROOT / 'nodes'

        if 'nvidia_drm' in self.loaded:
            self.reconcilenvidianodes()
        if 'nvidia_uvm' in self.loaded:
            self.reconcilenvidiauvmnode()

        for rule in self.device_access:
            for path in noderoot.glob(rule['pattern']):
                try:
                    relative = path.relative_to(noderoot).as_posix()
                    failurekey = f'device-access:{path.name}'
                    status = path.stat(follow_symlinks=False)
                    if not stat.S_ISCHR(status.st_mode):
                        continue
                    wantedmode = int(rule['mode'])
                    wantedgroup = int(rule['group'])
                    if status.st_uid != 0 or status.st_gid != wantedgroup:
                        os.chown(path, 0, wantedgroup, follow_symlinks=False)
                    if stat.S_IMODE(status.st_mode) != wantedmode:
                        os.chmod(path, wantedmode, follow_symlinks=False)
                    if relative not in self.device_grants:
                        self.device_grants.add(relative)
                        log(
                            f'device access granted node={relative} '
                            f'group={wantedgroup} mode={wantedmode:04o}'
                        )
                    self.failed.pop(failurekey, None)
                except (OSError, ValueError) as error:
                    self.failed[f'device-access:{path.name}'] = str(error)[:512]

    def blockinventory(self):
        inventory = {}
        classroot = STATEROOT / 'class/block'
        try:
            entries = sorted(classroot.iterdir(), key=lambda item: item.name)
        except OSError:
            return inventory
        for entry in entries:
            try:
                resolved = entry.resolve(strict=True)
                device = (entry / 'dev').read_text(encoding='ascii').strip()
                size = int((entry / 'size').read_text(encoding='ascii').strip())
                partition = (entry / 'partition').is_file()
            except (OSError, ValueError):
                continue
            inventory[entry.name] = {
                'name': entry.name,
                'entry': entry,
                'resolved': resolved,
                'device': device,
                'size': size,
                'partition': partition,
                'parent': resolved.parent.name if partition else None,
                'node': DRIVERROOT / 'nodes' / entry.name,
            }
        return inventory

    def blockisusb(self, block):
        resolved = Path(block['resolved'])
        for ancestor in (resolved, *resolved.parents):
            try:
                if (ancestor / 'subsystem').resolve(strict=True).name == 'usb':
                    return True
            except OSError:
                pass
        parts = [part.casefold() for part in resolved.parts]
        return any(
            re.fullmatch(r'usb[0-9]+', part) or re.fullmatch(r'[0-9]+-[0-9]+(?:\.[0-9]+)*', part)
            for part in parts
        )

    def rootblockdisks(self, inventory):
        roots = set()
        bydevice = {item['device']: name for name, item in inventory.items()}
        try:
            rootdevice = f'{os.major(os.stat("/").st_dev)}:{os.minor(os.stat("/").st_dev)}'
            rootname = bydevice.get(rootdevice)
            if rootname:
                roots.add(rootname)
        except (OSError, ValueError):
            pass
        mounts = mountedfilesystems()
        rootmount = mounts.get('/', {})
        source = str(rootmount.get('source', ''))
        if source:
            name = Path(source).name
            if name in inventory:
                roots.add(name)

        pending = list(roots)
        while pending:
            name = pending.pop()
            item = inventory.get(name)
            if item is None:
                continue
            if item.get('partition') and item.get('parent') in inventory:
                parent = item['parent']
                if parent not in roots:
                    roots.add(parent)
                    pending.append(parent)
            slaves = item['entry'] / 'slaves'
            try:
                for slave in slaves.iterdir():
                    if slave.name in inventory and slave.name not in roots:
                        roots.add(slave.name)
                        pending.append(slave.name)
            except OSError:
                pass
        return {
            item['parent'] if item.get('partition') and item.get('parent') else name
            for name, item in inventory.items()
            if name in roots
        }

    def cachedvolumeprobe(self, block):
        key = (block['device'], block['size'])
        cached = self.volume_probe_cache.get(key)
        if cached is not None:
            return dict(cached)
        node = Path(block['node'])
        status = node.stat()
        if not stat.S_ISBLK(status.st_mode):
            raise ValueError(f'not a block device: {node}')
        probed = probevolume(node)
        self.volume_probe_cache[key] = dict(probed)
        return probed

    def volumeauthorized(self, probe):
        label = normalizevolumeidentity(probe.get('label'))
        identity = normalizevolumeidentity(probe.get('uuid')).replace('-', '')
        return (
            bool(self.volume_policy.get('allow_all_data', False))
            or label in set(self.volume_policy.get('allowed_labels', []))
            or identity in set(self.volume_policy.get('allowed_uuids', []))
        )

    def unmountvolume(self, target):
        target = Path(target)
        try:
            target.relative_to(VOLUMEBASE)
        except ValueError:
            return False
        try:
            os.sync()
        except OSError:
            pass
        libc = ctypes.CDLL(None, use_errno=True)
        if not hasattr(libc, 'umount2'):
            return False
        libc.umount2.argtypes = [ctypes.c_char_p, ctypes.c_int]
        result = libc.umount2(os.fsencode(target), 0)
        if result != 0:
            result = libc.umount2(os.fsencode(target), MNT_DETACH)
        if result != 0:
            error = ctypes.get_errno()
            log(f'volume unmount failed target={target} errno={error}')
            return False
        try:
            target.rmdir()
        except OSError:
            pass
        log(f'external volume unmounted target={target}')
        return True

    def mountvolume(self, block, probe, target):
        target = Path(target)
        try:
            if target.parent.resolve() != VOLUMEBASE.resolve():
                raise ValueError('external volume target escaped its private root')
        except OSError as error:
            raise ValueError('external volume target could not be resolved') from error
        target.mkdir(mode=0o700, parents=True, exist_ok=True)
        source = Path(block['node'])
        filesystem = str(probe['filesystem'])
        readonly = bool(self.volume_policy.get('read_only', False) or not probe.get('safe_write', False))
        baseflags = MS_NOSUID | MS_NODEV | MS_NOEXEC
        # These removable filesystems do not carry the desktop's Unix identity
        # reliably. Publish a private uid-1000 view so a volume admitted as
        # writable is actually writable from Array and its file picker.
        mountoptions = b'uid=1000,gid=1000,dmask=0077,fmask=0177'
        libc = ctypes.CDLL(None, use_errno=True)
        if not hasattr(libc, 'mount'):
            raise OSError(errno.ENOSYS, 'mount system call is unavailable')
        libc.mount.argtypes = [
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_ulong,
            ctypes.c_void_p,
        ]

        flags = baseflags | (MS_RDONLY if readonly else 0)
        result = libc.mount(
            os.fsencode(source),
            os.fsencode(target),
            filesystem.encode('ascii'),
            flags,
            mountoptions,
        )
        if result != 0:
            lasterror = ctypes.get_errno()
            try:
                target.rmdir()
            except OSError:
                pass
            raise OSError(lasterror, os.strerror(lasterror), str(source))

        # A clean, policy-writable volume must never be silently published as
        # read-only. Verify the exact uid-1000 view consumed by Array and its
        # file picker before advertising the mount.
        try:
            self.probevolumeaccess(target, writable=not readonly)
        except OSError:
            self.unmountvolume(target)
            raise

        log(
            f'external volume mounted label={probe.get("label")!r} '
            f'filesystem={filesystem} source={source} target={target} '
            f'read_only={readonly} access_probe=passed '
            f'policy_read_only={bool(self.volume_policy.get("read_only", False))} '
            f'safe_write={bool(probe.get("safe_write", False))} '
            f'os_install={bool(probe.get("os_install", False))} '
            f'volume_flags={int(probe.get("volume_flags", 0))} '
            f'write_guard_reason={probe.get("os_reason") or ("filesystem is dirty or not safely closed" if not probe.get("safe_write", False) else "none")!r}'
        )
        return readonly

    @staticmethod
    def desktopmodepermits(metadata, writable=False):
        """Model uid/gid 1000 DAC access to a mounted directory inode."""

        mode = stat.S_IMODE(metadata.st_mode)
        required = 0o7 if writable else 0o5
        if metadata.st_uid == 1000:
            granted = (mode >> 6) & 0o7
        elif metadata.st_gid == 1000:
            granted = (mode >> 3) & 0o7
        else:
            granted = mode & 0o7
        return granted & required == required

    @staticmethod
    def probevolumeaccess(target, writable):
        directorydescriptor = -1
        probedescriptor = -1
        probename = f'.t1os-write-probe-{os.getpid()}-{time.monotonic_ns()}'
        try:
            rootstate = os.stat(target, follow_symlinks=False)
            if (
                not stat.S_ISDIR(rootstate.st_mode) or
                not DriverServer.desktopmodepermits(rootstate, writable=writable)
            ):
                raise OSError(
                    errno.EACCES,
                    (
                        'mounted volume root is not accessible to the desktop '
                        f'identity (uid={rootstate.st_uid} gid={rootstate.st_gid} '
                        f'mode={stat.S_IMODE(rootstate.st_mode):04o} '
                        f'writable={bool(writable)})'
                    ),
                    str(target),
                )
            directorydescriptor = os.open(
                target,
                os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0) |
                getattr(os, 'O_CLOEXEC', 0) |
                getattr(os, 'O_NOFOLLOW', 0),
            )
            openedstate = os.fstat(directorydescriptor)
            if (
                openedstate.st_dev != rootstate.st_dev or
                openedstate.st_ino != rootstate.st_ino or
                not stat.S_ISDIR(openedstate.st_mode)
            ):
                raise OSError(
                    errno.EACCES, 'mounted volume changed during access probe',
                    str(target),
                )
            os.listdir(directorydescriptor)

            if writable:
                probedescriptor = os.open(
                    probename,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                    getattr(os, 'O_CLOEXEC', 0) |
                    getattr(os, 'O_NOFOLLOW', 0),
                    0o600,
                    dir_fd=directorydescriptor,
                )
                probestate = os.fstat(probedescriptor)
                if (
                    not stat.S_ISREG(probestate.st_mode) or
                    probestate.st_uid != 1000 or probestate.st_gid != 1000 or
                    stat.S_IMODE(probestate.st_mode) & 0o077 or
                    probestate.st_nlink != 1
                ):
                    raise OSError(
                        errno.EACCES,
                        'mounted volume did not apply the desktop file identity',
                        str(target),
                    )
                if os.write(probedescriptor, b'1') != 1:
                    raise OSError(errno.EIO, 'short mounted volume probe write')
                os.fsync(probedescriptor)
                os.close(probedescriptor)
                probedescriptor = -1
                os.unlink(probename, dir_fd=directorydescriptor)
        finally:
            if probedescriptor >= 0:
                os.close(probedescriptor)
            if directorydescriptor >= 0:
                try:
                    os.unlink(probename, dir_fd=directorydescriptor)
                except FileNotFoundError:
                    pass
                os.close(directorydescriptor)

    def targetforvolume(self, probe, mounted):
        label = str(probe.get('label') or '').strip()
        identity = str(probe.get('uuid') or '').replace('-', '')
        base = safevolumename(label or identity or 'external')
        target = VOLUMEBASE / base
        if str(target) not in mounted and (not target.exists() or not any(target.iterdir())):
            return target
        suffix = safevolumename(identity[-8:] if identity else hashlib.sha256(base.encode()).hexdigest()[:8])
        return VOLUMEBASE / f'{base}-{suffix}'

    def reconcilevolumes(self, force=False):
        enabled = bool(self.volume_policy.get('enabled', False))
        inventory = self.blockinventory()
        signature = tuple(sorted(
            (name, item['device'], item['size'], bool(item['partition']), str(item.get('parent') or ''))
            for name, item in inventory.items()
        ))
        if not force and not self.volume_retry and signature == self.volume_signature:
            return

        retry = False
        blocks = {}
        desired = []
        rootdisks = self.rootblockdisks(inventory)
        disks = [item for item in inventory.values() if not item['partition']]
        children = {}
        for item in inventory.values():
            if item['partition'] and item.get('parent'):
                children.setdefault(item['parent'], []).append(item)

        if enabled:
            allowedfilesystems = set(self.volume_policy.get('filesystems', []))
            for disk in sorted(disks, key=lambda item: item['name']):
                if not self.blockisusb(disk):
                    continue
                if disk['name'] in rootdisks:
                    blocks[disk['name']] = 'contains the active T1OS root'
                    continue
                node = Path(disk['node'])
                try:
                    status = node.stat()
                    if not stat.S_ISBLK(status.st_mode):
                        continue
                    sectorsizepath = disk['entry'] / 'queue/logical_block_size'
                    sectorsize = int(sectorsizepath.read_text(encoding='ascii').strip())
                    if sectorsize not in (512, 1024, 2048, 4096):
                        raise ValueError(f'unsupported logical sector size {sectorsize}')
                    tablereasons, _ = partitionosreasons(node, sectorsize)
                except (OSError, ValueError) as error:
                    blocks[disk['name']] = f'could not safely inspect partition table: {error}'
                    retry = True
                    continue

                devices = sorted(children.get(disk['name'], []), key=lambda item: item['name'])
                if not devices:
                    devices = [disk]
                probes = []
                diskreasons = list(tablereasons)
                for device in devices:
                    try:
                        probe = self.cachedvolumeprobe(device)
                    except (OSError, ValueError) as error:
                        diskreasons.append(f'{device["name"]} could not be identified: {error}')
                        retry = True
                        continue
                    probe['device'] = device['name']
                    probe['source'] = str(device['node'])
                    probes.append((device, probe))
                    if probe.get('os_install'):
                        diskreasons.append(f'{device["name"]}: {probe.get("os_reason") or "OS volume"}')
                    elif probe.get('filesystem') not in allowedfilesystems:
                        diskreasons.append(
                            f'{device["name"]}: filesystem {probe.get("filesystem") or "unknown"} '
                            'is not permitted for external mounting'
                        )

                if diskreasons:
                    blocks[disk['name']] = '; '.join(sorted(set(diskreasons)))
                    continue

                authorized = [
                    (device, probe)
                    for device, probe in probes
                    if self.volumeauthorized(probe)
                ]
                if not authorized:
                    identities = ','.join(
                        str(probe.get('label') or probe.get('uuid') or device['name'])
                        for device, probe in probes
                    )
                    blocks[disk['name']] = f'not explicitly authorized ({identities or "unlabelled"})'
                    continue
                desired.extend(authorized)

        VOLUMEBASE.mkdir(parents=True, exist_ok=True)
        mounted = mountedfilesystems()
        physical = {
            target: details
            for target, details in mounted.items()
            if (
                Path(target).parent == VOLUMEBASE
                and str(details.get('source', '')).startswith(str(DRIVERROOT / 'nodes') + '/')
            )
        }
        desiredsources = {str(device['node']) for device, _ in desired}
        for target, details in list(physical.items()):
            if details.get('source') not in desiredsources:
                if self.unmountvolume(target):
                    mounted.pop(target, None)
                    physical.pop(target, None)

        volumes = []
        for device, probe in desired:
            source = str(device['node'])
            existingtarget = next((
                target for target, details in physical.items()
                if details.get('source') == source
            ), None)
            if existingtarget is not None:
                target = Path(existingtarget)
                readonly = 'ro' in physical[existingtarget].get('options', set())
            else:
                try:
                    target = self.targetforvolume(probe, mounted)
                    readonly = self.mountvolume(device, probe, target)
                    mounted[str(target)] = {
                        'source': source,
                        'filesystem': probe['filesystem'],
                        'options': {'ro'} if readonly else {'rw'},
                    }
                    physical[str(target)] = mounted[str(target)]
                except (OSError, ValueError) as error:
                    blocks[device['name']] = f'mount failed: {error}'
                    retry = True
                    continue
            volumes.append({
                'root': str(target),
                'label': str(probe.get('label') or target.name),
                'uuid': str(probe.get('uuid') or ''),
                'filesystem': str(probe.get('filesystem') or ''),
                'source': source,
                'device': device['name'],
                'read_only': bool(readonly),
                'removable': True,
            })

        previousblocks = dict(self.volume_blocks)
        with self.lock:
            self.volumes = sorted(volumes, key=lambda item: item['root'].casefold())
            self.volume_blocks = dict(sorted(blocks.items()))
        self.volume_signature = None if retry else signature
        self.volume_retry = retry
        if previousblocks != blocks:
            for name, reason in sorted(blocks.items()):
                log(f'external volume skipped disk={name}: {reason}')
        self.publish()

    def shutdownvolumes(self):
        mounted = mountedfilesystems()
        for target, details in sorted(mounted.items(), reverse=True):
            if (
                Path(target).parent == VOLUMEBASE
                and str(details.get('source', '')).startswith(str(DRIVERROOT / 'nodes') + '/')
            ):
                self.unmountvolume(target)
        with self.lock:
            self.volumes = []
        self.publish()

    def hotplug(self):
        netlink = socket.socket(socket.AF_NETLINK, socket.SOCK_DGRAM, UEVENT_PROTOCOL)
        netlink.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024 * 1024)
        netlink.bind((os.getpid(), 1))
        netlink.setblocking(False)
        log('hotplug listener ready')
        while self.running:
            readable, _, _ = select.select([netlink], [], [], 1.0)
            if not readable:
                self.applydeviceaccess()
                self.reconcilevolumes(force=False)
                continue
            try:
                event = parseuevent(netlink.recv(256 * 1024))
            except OSError as error:
                if self.running:
                    log(f'hotplug receive failed: {error}')
                continue
            action = event.get('ACTION')
            if action not in ('add', 'bind', 'change', 'remove', 'unbind'):
                continue
            alias = event.get('MODALIAS', '')
            if alias and action in ('add', 'bind', 'change'):
                self.handlealias(alias, source=f'hotplug:{action}')
            self.applydeviceaccess()
            if event.get('SUBSYSTEM') == 'block' or event.get('DEVNAME', '').startswith(('sd', 'nvme', 'vd', 'mmcblk', 'dm-')):
                self.reconcilevolumes(force=True)
        netlink.close()

    def stop(self, *_):
        self.running = False

    def run(self):
        release_root = MODULEROOT / os.uname().release
        module_runtime_ready = (
            MODPROBE.is_file()
            and os.access(MODPROBE, os.X_OK)
            and release_root.is_dir()
        )

        RUNTIMEROOT.mkdir(parents=True, exist_ok=True)
        status_thread = threading.Thread(target=self.statusserver, name='driver-status', daemon=True)
        status_thread.start()
        self.publish()

        degraded = False
        if module_runtime_ready:
            try:
                self.configurefirmware()
                self.manifest_files = validatemanifest()
                self.integrity_ready = True
                log(f'module manifest verified files={self.manifest_files}')
            except Exception as error:
                degraded = True
                self.failed['driver-integrity'] = str(error)[:512]
                log(f'driver integrity degraded: {error}')

            self.coldplug()
        else:
            log(
                f'device policy mode kernel={os.uname().release} '
                'matching module runtime=unavailable'
            )

        self.applydeviceaccess()
        try:
            self.reconcilevolumes(force=True)
        except Exception as error:
            degraded = True
            self.failed['external-volumes'] = str(error)[:512]
            log(f'external volume policy degraded: {error}')
        degraded = degraded or bool(self.failed)
        self.setstate('degraded' if degraded else 'ready')
        log(
            f'driver policy {self.state} loaded={len(self.loaded)} '
            f'device_grants={len(self.device_grants)} failed={len(self.failed)}'
        )

        try:
            try:
                self.hotplug()
            except Exception as error:
                self.failed['hotplug-listener'] = str(error)[:512]
                self.setstate('degraded')
                log(f'hotplug listener failed: {error}')
                while self.running:
                    time.sleep(1)
        finally:
            self.shutdownvolumes()


def diagnostic():
    assert normalizemodule('snd-usb-audio') == 'snd_usb_audio'
    assert parseblacklist('quiet module_blacklist=amdgpu,nouveau modprobe.blacklist=snd-usb-audio') == {
        'amdgpu', 'nouveau', 'snd_usb_audio'
    }
    assert parsemoduleparameters(
        'quiet nouveau.config=NvGspFw=0 nouveau.debug=debug '
        'snd-usb-audio.index=2'
    ) == {
        'nouveau': {'config': 'NvGspFw=0', 'debug': 'debug'},
        'snd_usb_audio': {'index': '2'},
    }
    assert parsemoduleparameters(
        'nvidia_drm.modeset=1 nvidia_drm.fbdev=1'
    ) == {
        'nvidia_drm': {'modeset': '1', 'fbdev': '1'},
    }
    assert moduleparametermatches('nvidia_drm', 'modeset', '1', 'Y')
    assert not moduleparametermatches('nvidia_drm', 'modeset', '1', 'N')
    assert pcidisplayalias(
        'pci:v000010DEd00002783sv00001462sd00005137bc03sc00i00'
    )
    nvidiaalias = (
        'pci:v000010DEd00002783sv00001462sd00005137bc03sc00i00'
    )
    assert orderedaliasmodules(
        nvidiaalias,
        ['nouveau', 'nvidia'],
    ) == ['nvidia', 'nouveau']
    assert aliasloadmodule(nvidiaalias, 'nvidia') == 'nvidia_drm'
    assert aliasloadmodule(nvidiaalias, 'nouveau') == 'nouveau'
    assert not pcidisplayalias(
        'pci:v000010DEd000022B1sv00001462sd00005137bc04sc03i00'
    )
    assert parsegraphicsresetrequest({
        'request': 'RESET_GRAPHICS',
        'bdf': '0000:01:00.0',
        'driver': 'nouveau',
    }, (1, 0, 0)) == ('0000:01:00.0', 'nouveau')
    try:
        parsegraphicsresetrequest({
            'request': 'RESET_GRAPHICS',
            'bdf': '0000:01:00.0',
            'driver': 'nouveau',
        }, (2, 0, 0))
    except GraphicsResetError as error:
        assert error.phase == 'authorize' and error.errornumber == errno.EPERM
    else:
        raise AssertionError('non-PID-1 graphics reset peer was authorized')
    try:
        parsegraphicsresetrequest({
            'request': 'RESET_GRAPHICS',
            'bdf': '../../devices',
            'driver': 'nouveau',
        }, (1, 0, 0))
    except GraphicsResetError as error:
        assert error.phase == 'validate-bdf'
    else:
        raise AssertionError('unsafe graphics reset BDF was accepted')
    event = parseuevent(b'add@/devices/test\0ACTION=add\0MODALIAS=usb:v1234p5678\0')
    assert event['ACTION'] == 'add' and event['MODALIAS'] == 'usb:v1234p5678'
    with tempfile.TemporaryDirectory(prefix='t1os-driver-diagnostic-') as temporary:
        root = Path(temporary)
        resetserver = DriverServer.__new__(DriverServer)
        resetserver.graphics_reset_lock = threading.Lock()
        resetserver.graphics_helpers_lock = threading.Lock()
        resetserver.abandoned_graphics_helpers = {}
        resetserver.pending_graphics_helpers = {}
        resetserver.graphics_control_root = root / 'control'
        resetserver.graphics_state_root = root / 'state'
        resetserver.graphics_write_timeout = 0.2
        resetserver.graphics_ready_timeout = 0.2
        resetstate = {'driver': 'nouveau'}
        resetcalls = []

        def diagnosticgraphicswrite(path, value, bdf, phase):
            resetcalls.append((Path(path).name, str(value), bdf, phase))
            if phase == 'unbind':
                resetstate['driver'] = ''
            elif phase == 'bind':
                resetstate['driver'] = 'nouveau'
            return {
                'ok': True,
                'errno': 0,
                'phase': phase,
                'message': 'ok',
                'timed_out': False,
            }

        resetresponse = resetserver.resetgraphicsrequest(
            {
                'request': 'RESET_GRAPHICS',
                'bdf': '0000:01:00.0',
                'driver': 'nouveau',
            },
            (1, 0, 0),
            ownershipvalidator=lambda bdf, driver: True,
            writefunction=diagnosticgraphicswrite,
            driverlookup=lambda bdf: resetstate['driver'],
            drmfinder=lambda bdf: (
                ['card1', 'renderD128']
                if resetstate['driver'] == 'nouveau'
                else []
            ),
            pathexists=lambda path: True,
        )
        assert resetresponse['ok'] and resetresponse['phase'] == 'complete'
        assert resetresponse['drm_nodes'] == ['card1', 'renderD128']
        assert [call[3] for call in resetcalls] == [
            'unbind',
            'function-reset',
            'bind',
        ]

        resetstate['driver'] = 'nouveau'

        def diagnosticunbindfailure(path, value, bdf, phase):
            return {
                'ok': False,
                'errno': errno.EIO,
                'phase': phase,
                'message': 'injected unbind failure',
                'timed_out': False,
            }

        resetfailure = resetserver.resetgraphicsrequest(
            {
                'request': 'RESET_GRAPHICS',
                'bdf': '0000:01:00.0',
                'driver': 'nouveau',
            },
            (1, 0, 0),
            ownershipvalidator=lambda bdf, driver: True,
            writefunction=diagnosticunbindfailure,
            driverlookup=lambda bdf: resetstate['driver'],
            drmfinder=lambda bdf: [],
            pathexists=lambda path: True,
        )
        assert (
            not resetfailure['ok']
            and resetfailure['phase'] == 'unbind'
            and resetfailure['errno'] == errno.EIO
        )

        resetserver.graphics_reset_lock.acquire()
        try:
            resetbusy = resetserver.resetgraphicsrequest(
                {
                    'request': 'RESET_GRAPHICS',
                    'bdf': '0000:01:00.0',
                    'driver': 'nouveau',
                },
                (1, 0, 0),
            )
        finally:
            resetserver.graphics_reset_lock.release()
        assert (
            not resetbusy['ok']
            and resetbusy['phase'] == 'serialize'
            and resetbusy['errno'] == errno.EBUSY
        )

        previousnvidiagpuminors = globals()['nvidiagpuminors']
        try:
            globals()['nvidiagpuminors'] = lambda root: []
            resetserver.failed = {}
            resetserver.skipped = {}
            resetserver.nvidia_devices = [{
                'bdf': '0000:01:00.0',
                'minor': 0,
            }]
            resetserver.nvidia_device_nodes = [
                'nvidiactl',
                'nvidia-modeset',
                'nvidia0',
            ]
            resetserver.nvidia_node_state = 'ready'
            assert resetserver.reconcilenvidianodes(
                wait=0.0,
                transient_unclaimed=True,
            )
            assert resetserver.nvidia_devices == []
            assert resetserver.nvidia_device_nodes == []
            assert resetserver.nvidia_node_state == 'reclaiming'
        finally:
            globals()['nvidiagpuminors'] = previousnvidiagpuminors

        nvidiaresetstate = {
            'driver': 'nvidia',
            'readiness': 'ready',
        }

        def diagnosticnvidiawrite(path, value, bdf, phase):
            if phase == 'unbind':
                nvidiaresetstate['driver'] = ''
            elif phase == 'bind':
                nvidiaresetstate['driver'] = 'nvidia'
            return {
                'ok': True,
                'errno': 0,
                'phase': phase,
                'message': 'ok',
                'timed_out': False,
            }

        def diagnosticnvidiareconcile(
            wait=0.0,
            transient_unclaimed=False,
        ):
            resetserver.failed = {}
            if nvidiaresetstate['readiness'] == 'missing-proc':
                resetserver.nvidia_devices = []
                resetserver.nvidia_device_nodes = []
                resetserver.nvidia_node_state = 'unclaimed'
                return True
            resetserver.nvidia_devices = [{
                'bdf': '0000:01:00.0',
                'minor': 0,
                'minor_source': 'information',
            }]
            resetserver.nvidia_device_nodes = (
                ['nvidiactl', 'nvidia0']
                if nvidiaresetstate['readiness'] == 'missing-modeset'
                else ['nvidiactl', 'nvidia-modeset', 'nvidia0']
            )
            resetserver.nvidia_node_state = 'ready'
            return True

        resetserver.reconcilenvidianodes = diagnosticnvidiareconcile
        nvidiareset = resetserver.resetgraphicsrequest(
            {
                'request': 'RESET_GRAPHICS',
                'bdf': '0000:01:00.0',
                'driver': 'nvidia',
            },
            (1, 0, 0),
            ownershipvalidator=lambda bdf, driver: True,
            writefunction=diagnosticnvidiawrite,
            driverlookup=lambda bdf: nvidiaresetstate['driver'],
            drmfinder=lambda bdf: (
                ['card1', 'renderD128']
                if nvidiaresetstate['driver'] == 'nvidia'
                else []
            ),
            pathexists=lambda path: True,
        )
        assert (
            nvidiareset['ok']
            and nvidiareset['nvidia_devices'][0]['bdf']
            == '0000:01:00.0'
            and nvidiareset['nvidia_device_nodes']
            == ['nvidia-modeset', 'nvidia0', 'nvidiactl']
        )

        nvidiaresetstate.update({
            'driver': 'nvidia',
            'readiness': 'missing-proc',
        })
        nvidiaprocfailure = resetserver.resetgraphicsrequest(
            {
                'request': 'RESET_GRAPHICS',
                'bdf': '0000:01:00.0',
                'driver': 'nvidia',
            },
            (1, 0, 0),
            ownershipvalidator=lambda bdf, driver: True,
            writefunction=diagnosticnvidiawrite,
            driverlookup=lambda bdf: nvidiaresetstate['driver'],
            drmfinder=lambda bdf: (
                ['card1']
                if nvidiaresetstate['driver'] == 'nvidia'
                else []
            ),
            pathexists=lambda path: True,
        )
        assert (
            not nvidiaprocfailure['ok']
            and nvidiaprocfailure['phase'] == 'wait-nvidia-proc'
        )

        nvidiaresetstate.update({
            'driver': 'nvidia',
            'readiness': 'missing-modeset',
        })
        nvidianodefailure = resetserver.resetgraphicsrequest(
            {
                'request': 'RESET_GRAPHICS',
                'bdf': '0000:01:00.0',
                'driver': 'nvidia',
            },
            (1, 0, 0),
            ownershipvalidator=lambda bdf, driver: True,
            writefunction=diagnosticnvidiawrite,
            driverlookup=lambda bdf: nvidiaresetstate['driver'],
            drmfinder=lambda bdf: (
                ['card1']
                if nvidiaresetstate['driver'] == 'nvidia'
                else []
            ),
            pathexists=lambda path: True,
        )
        assert (
            not nvidianodefailure['ok']
            and nvidianodefailure['phase'] == 'wait-nvidia-nodes'
            and 'nvidia-modeset' in nvidianodefailure['message']
        )

        if hasattr(os, 'fork'):
            forkoutput = root / 'forked-write'
            forkoutput.write_bytes(b'0')
            forkresult = resetserver.boundedgraphicswrite(
                forkoutput,
                '1',
                '0000:01:00.0',
                'diagnostic-write',
                timeout=0.5,
            )
            assert forkresult['ok'] and forkoutput.read_bytes() == b'1'

        recovery = root / 'graphics recovery boot.json'
        bootid = root / 'boot_id'
        currentboot = '806e7a15-5099-4fda-b909-cb85cb364f8d'
        priorboot = 'd174f975-9b45-41ea-8714-4dc1f25e5f2a'
        bootid.write_text(currentboot, encoding='ascii')
        recovery.write_text(json.dumps({
            'format': 1,
            'mode': 'firmware-framebuffer',
            'state': 'requested',
            'boot_id': priorboot,
        }), encoding='utf-8')
        # Persistent state from an earlier boot must never suppress native GPU
        # discovery on the current boot.
        assert not firmwaregraphicsrecoveryrequested(recovery, bootid)
        recovery.write_text(json.dumps({
            'format': 1,
            'mode': 'firmware-framebuffer',
            'state': 'requested',
            'boot_id': currentboot,
        }), encoding='utf-8')
        assert not firmwaregraphicsrecoveryrequested(recovery, bootid)
        recovery.write_text('{}', encoding='utf-8')
        assert not firmwaregraphicsrecoveryrequested(recovery, bootid)
        policy = root / 'policy.json'
        policy.write_text(json.dumps({
            'format': 1,
            'allowed_modules': ['nouveau'],
            'maximum_module_loads': 4,
            'external_volumes': {
                'enabled': True,
                'allow_all_data': True,
                'allowed_labels': [],
                'allowed_uuids': [],
                'filesystems': ['ntfs3', 'exfat', 'vfat'],
                'read_only': False,
            },
            'device_access': [{
                'pattern': 'dri/renderD*',
                'mode': '0660',
                'group': 1000,
            }],
        }), encoding='utf-8')
        parsed_policy = loadpolicy(policy)
        assert parsed_policy['device_access'] == [{
            'pattern': 'dri/renderD*',
            'mode': 0o660,
            'group': 1000,
        }]
        assert parsed_policy['external_volumes'] == {
            'enabled': True,
            'allow_all_data': True,
            'allowed_labels': [],
            'allowed_uuids': [],
            'filesystems': ['exfat', 'ntfs3', 'vfat'],
            'read_only': False,
        }
        assert safevolumename('../../CACHE volume') == 'CACHE_volume'

        devices = root / 'devices'
        devices.write_text(
            'Character devices:\n'
            '  1 mem\n'
            '195 nvidia-frontend\n'
            '226 drm\n'
            '\n'
            'Block devices:\n'
            '195 nvidia\n',
            encoding='ascii',
        )
        assert nvidiafrontendmajor(devices) == 195
        devices.write_text(
            'Character devices:\n'
            '195 nvidia\n'
            '195 nvidiactl\n'
            '511 nvidia-uvm\n'
            '\n'
            'Block devices:\n'
            '195 nvidia-frontend\n',
            encoding='ascii',
        )
        assert nvidiafrontendmajor(devices) == 195
        assert nvidiauvmmajor(devices) == 511
        devices.write_text(
            'Character devices:\n'
            '195 nvidia-frontend\n'
            '195 nvidia\n'
            '195 nvidiactl\n',
            encoding='ascii',
        )
        assert nvidiafrontendmajor(devices) == 195
        invalidregistrations = [
            (
                'Character devices:\n'
                '195 nvidia\n'
                '196 nvidiactl\n'
            ),
            (
                'Character devices:\n'
                '195 nvidia\n'
                '195 nvidia\n'
                '195 nvidiactl\n'
            ),
            (
                'Character devices:\n'
                '195 nvidia-frontend\n'
                '196 nvidia\n'
                '196 nvidiactl\n'
            ),
            (
                'Block devices:\n'
                '195 nvidia\n'
                '195 nvidiactl\n'
            ),
        ]
        for invalidregistration in invalidregistrations:
            devices.write_text(invalidregistration, encoding='ascii')
            try:
                nvidiafrontendmajor(devices)
            except ValueError:
                pass
            else:
                raise AssertionError(
                    'invalid NVIDIA major registration was accepted'
                )
        invaliduvmregistrations = [
            'Character devices:\n195 nvidia\n195 nvidiactl\n',
            (
                'Character devices:\n'
                '511 nvidia-uvm\n'
                '512 nvidia-uvm\n'
            ),
            'Block devices:\n511 nvidia-uvm\n',
        ]
        for invalidregistration in invaliduvmregistrations:
            devices.write_text(invalidregistration, encoding='ascii')
            try:
                nvidiauvmmajor(devices)
            except ValueError:
                pass
            else:
                raise AssertionError(
                    'invalid NVIDIA UVM major registration was accepted'
                )
        gpuroot = root / 'nvidia-gpus'
        firstgpu = gpuroot / '0000:01:00.0'
        secondgpu = gpuroot / '0000:02:00.0'
        firstgpu.mkdir(parents=True)
        secondgpu.mkdir()
        (firstgpu / 'information').write_text(
            'Model: NVIDIA diagnostic GPU\nDevice Minor: 7\n',
            encoding='ascii',
        )
        (secondgpu / 'information').write_text(
            'Model: NVIDIA diagnostic fallback GPU\n',
            encoding='ascii',
        )
        diagnosticminors = nvidiagpuminors(gpuroot)
        assert diagnosticminors == [
            {
                'bdf': '0000:02:00.0',
                'minor': 0,
                'minor_source': 'fallback',
            },
            {
                'bdf': '0000:01:00.0',
                'minor': 7,
                'minor_source': 'information',
            },
        ]

        aliasstate = root / 'pci-state'
        firstpcidevice = (
            aliasstate / 'bus/pci/devices/0000:01:00.0'
        )
        secondpcidevice = (
            aliasstate / 'bus/pci/devices/0000:02:00.0'
        )
        firstpcidevice.mkdir(parents=True)
        secondpcidevice.mkdir(parents=True)
        for device in (firstpcidevice, secondpcidevice):
            (device / 'modalias').write_text(
                nvidiaalias,
                encoding='ascii',
            )
            (device / 'class').write_text('0x030000\n', encoding='ascii')
        diagnosticbindings = pcialiasbindings(
            nvidiaalias,
            aliasstate,
            driverlookup=lambda bdf: {
                '0000:01:00.0': 'nvidia',
                '0000:02:00.0': 'nvidia',
            }.get(bdf, ''),
        )
        assert diagnosticbindings == [
            {'bdf': '0000:01:00.0', 'driver': 'nvidia'},
            {'bdf': '0000:02:00.0', 'driver': 'nvidia'},
        ]
        assert nvidiaaliasclaimed(diagnosticbindings)
        diagnosticbindings[1]['driver'] = ''
        assert not nvidiaaliasclaimed(diagnosticbindings)

        nvidiadriver = aliasstate / 'bus/pci/drivers/nvidia'
        nvidiadriver.mkdir(parents=True)
        for device in (firstpcidevice, secondpcidevice):
            (device / 'driver').symlink_to(
                nvidiadriver,
                target_is_directory=True,
            )

        def diagnosticaliasserver():
            server = DriverServer.__new__(DriverServer)
            server.integrity_ready = True
            server.processed_aliases = set()
            server.firmware_graphics_recovery = False
            server.display_recovery_modules = set()
            server.early_boot_animation_retired = True
            server.loaded = set()
            server.maximum = 8
            server.failed = {}
            server.skipped = {}
            server.blacklist = set()
            server.allowed = {
                'nvidia',
                'nvidia_drm',
                'nvidia_uvm',
                'nouveau',
            }
            server.module_parameters = {'nvidia_drm': {}}
            server.graphics_state_root = aliasstate
            server.resolvemodules = lambda alias: ['nvidia', 'nouveau']
            server.verifymoduleparameters = lambda module: []
            server.reconcilenvidianodes = lambda wait=0.0: True
            server.reconcilenvidiauvmnode = lambda wait=0.0: True
            server.nvidia_uvm_node_state = 'not-required'
            server.publish = lambda: None
            return server

        claimedserver = diagnosticaliasserver()
        claimedloads = []
        claimedserver.runmodprobe = lambda arguments, timeout=30: (
            claimedloads.append(list(arguments)) or (0, '', '')
        )
        claimedserver.handlealias(nvidiaalias, source='diagnostic')
        assert [arguments[1] for arguments in claimedloads] == [
            'nvidia_drm',
            'nvidia_uvm',
        ]
        assert claimedserver.skipped['nouveau'].startswith(
            'official NVIDIA driver owns'
        )

        (secondpcidevice / 'driver').unlink()
        mixedserver = diagnosticaliasserver()
        mixedloads = []
        mixedserver.runmodprobe = lambda arguments, timeout=30: (
            mixedloads.append(list(arguments)) or (0, '', '')
        )
        mixedserver.handlealias(nvidiaalias, source='diagnostic')
        assert [arguments[1] for arguments in mixedloads] == [
            'nvidia_drm',
            'nouveau',
        ]

        devices.write_text(
            'Character devices:\n'
            '195 nvidia\n'
            '195 nvidiactl\n'
            '511 nvidia-uvm\n',
            encoding='ascii',
        )
        uvmserver = DriverServer.__new__(DriverServer)
        uvmserver.device_grants = set()
        uvmserver.nvidia_device_nodes = [
            'nvidiactl',
            'nvidia-modeset',
            'nvidia0',
        ]
        uvmserver.nvidia_uvm_major = None
        uvmserver.nvidia_uvm_node_state = 'not-required'
        uvmserver.failed = {}
        uvmserver.skipped = {}
        uvmserver.state = 'starting'
        uvmnodes = []
        previousensurenvidiacharnode = globals()['ensurenvidiacharnode']
        try:
            globals()['ensurenvidiacharnode'] = (
                lambda path, major, minor: (
                    uvmnodes.append((Path(path), major, minor)) or True
                )
            )
            assert uvmserver.reconcilenvidiauvmnode(
                devicespath=devices,
                noderoot=root,
            )
        finally:
            globals()['ensurenvidiacharnode'] = (
                previousensurenvidiacharnode
            )
        assert uvmnodes == [
            (root / 'nvidia-uvm', 511, NVIDIAUVMMINOR),
        ]
        assert uvmserver.nvidia_device_nodes == [
            'nvidiactl',
            'nvidia-modeset',
            'nvidia0',
            'nvidia-uvm',
        ]
        assert (
            uvmserver.nvidia_uvm_major == 511
            and uvmserver.nvidia_uvm_node_state == 'ready'
            and uvmserver.device_grants == {'nvidia-uvm'}
        )

        invalidnode = root / 'nvidiactl'
        invalidnode.write_bytes(b'not a character node')
        try:
            ensurenvidiacharnode(invalidnode, 195, NVIDIACONTROLMINOR)
        except (OSError, ValueError):
            pass
        else:
            raise AssertionError('non-character NVIDIA node was accepted')

        if (
            hasattr(os, 'mknod')
            and hasattr(os, 'chown')
            and getattr(os, 'geteuid', lambda: 1)() == 0
        ):
            realnode = root / 'nvidia0'
            assert ensurenvidiacharnode(realnode, 1, 7)
            realnodestatus = realnode.lstat()
            assert (
                stat.S_ISCHR(realnodestatus.st_mode)
                and os.major(realnodestatus.st_rdev) == 1
                and os.minor(realnodestatus.st_rdev) == 7
                and realnodestatus.st_uid == 0
                and realnodestatus.st_gid == NVIDIANODEGROUP
                and stat.S_IMODE(realnodestatus.st_mode) == NVIDIANODEMODE
            )

        legacydisk = root / 'legacy-disk.img'
        legacybytes = bytearray(4096)
        legacybytes[446] = 0x80
        legacybytes[450] = 0x07
        legacybytes[510:512] = b'\x55\xaa'
        legacydisk.write_bytes(legacybytes)
        legacyreasons, _ = partitionosreasons(legacydisk)
        assert 'legacy bootable partition' in legacyreasons

        gptdisk = root / 'gpt-disk.img'
        gptbytes = bytearray(4096)
        gptbytes[512:520] = b'EFI PART'
        struct.pack_into('<Q', gptbytes, 512 + 72, 2)
        struct.pack_into('<I', gptbytes, 512 + 80, 1)
        struct.pack_into('<I', gptbytes, 512 + 84, 128)
        efitype = uuid.UUID('c12a7328-f81f-11d2-ba4b-00a0c93ec93b')
        gptbytes[1024:1040] = efitype.bytes_le
        gptdisk.write_bytes(gptbytes)
        gptreasons, _ = partitionosreasons(gptdisk)
        assert 'EFI system partition' in gptreasons

        extvolume = root / 'linux-volume.img'
        extbytes = bytearray(4096)
        extbytes[1024 + 56:1024 + 58] = b'\x53\xef'
        extbytes[1024 + 104:1024 + 120] = uuid.UUID(
            '11111111-2222-3333-4444-555555555555'
        ).bytes
        extbytes[1024 + 120:1024 + 125] = b'CACHE'
        extvolume.write_bytes(extbytes)
        extprobe = probevolume(extvolume)
        assert extprobe['filesystem'] == 'ext' and extprobe['os_install']

        fatvolume = root / 'fat-data-volume.img'
        fatbytes = bytearray(65536)
        fatbytes[0:3] = b'\xeb\x3c\x90'
        struct.pack_into('<H', fatbytes, 11, 512)
        fatbytes[13] = 1
        struct.pack_into('<H', fatbytes, 14, 1)
        fatbytes[16] = 2
        struct.pack_into('<H', fatbytes, 17, 512)
        struct.pack_into('<H', fatbytes, 19, 8192)
        struct.pack_into('<H', fatbytes, 22, 32)
        struct.pack_into('<I', fatbytes, 39, 0xA1B2C3D4)
        fatbytes[43:54] = b'USB DISK   '
        fatbytes[54:62] = b'FAT16   '
        fatbytes[510:512] = b'\x55\xaa'
        struct.pack_into('<H', fatbytes, 512 + 2, 0xC000)
        fatroot = (1 + (2 * 32)) * 512
        fatbytes[fatroot:fatroot + 8] = b'PHOTO   '
        fatbytes[fatroot + 8:fatroot + 11] = b'JPG'
        fatbytes[fatroot + 11] = 0x20
        fatbytes[fatroot + 32] = 0
        fatvolume.write_bytes(fatbytes)
        fatprobe = probevolume(fatvolume)
        assert fatprobe['filesystem'] == 'vfat'
        assert fatprobe['label'] == 'USB DISK' and fatprobe['safe_write']
        assert not fatprobe['os_install']
        fatbytes[fatroot:fatroot + 8] = b'WINDOWS '
        fatbytes[fatroot + 8:fatroot + 11] = b'   '
        fatbytes[fatroot + 11] = 0x10
        fatvolume.write_bytes(fatbytes)
        assert probevolume(fatvolume)['os_install']

        def diagnosticntfsrecord(attributes):
            record = bytearray(1024)
            record[:4] = b'FILE'
            struct.pack_into('<HH', record, 4, 0x30, 3)
            struct.pack_into('<H', record, 20, 0x38)
            struct.pack_into('<H', record, 22, 0x01)
            record[0x30:0x32] = b'\xaa\xbb'
            record[0x32:0x36] = b'\0\0\0\0'
            offset = 0x38
            for attributetype, content in attributes:
                length = (24 + len(content) + 7) & ~7
                struct.pack_into('<II', record, offset, attributetype, length)
                record[offset + 8] = 0
                struct.pack_into('<I', record, offset + 16, len(content))
                struct.pack_into('<H', record, offset + 20, 24)
                record[offset + 24:offset + 24 + len(content)] = content
                offset += length
            struct.pack_into('<I', record, offset, 0xFFFFFFFF)
            record[510:512] = b'\xaa\xbb'
            record[1022:1024] = b'\xaa\xbb'
            return record

        ntfsvolume = root / 'windows-volume.img'
        ntfsbytes = bytearray(24 * 1024)
        ntfsbytes[3:11] = b'NTFS    '
        struct.pack_into('<H', ntfsbytes, 11, 512)
        ntfsbytes[13] = 8
        struct.pack_into('<Q', ntfsbytes, 48, 1)
        struct.pack_into('<b', ntfsbytes, 64, -10)
        struct.pack_into('<Q', ntfsbytes, 72, 0x123456789ABCDEF0)
        ntfsbytes[4096 + (3 * 1024):4096 + (4 * 1024)] = diagnosticntfsrecord([
            (0x60, 'CACHE'.encode('utf-16-le')),
            (0x70, b'\0' * 8 + b'\x03\x01\0\0'),
        ])
        indexroot = bytearray(48)
        struct.pack_into('<I', indexroot, 8, 4096)
        struct.pack_into('<III', indexroot, 16, 16, 32, 32)
        struct.pack_into('<H', indexroot, 32 + 8, 16)
        struct.pack_into('<H', indexroot, 32 + 12, 0x02)
        ntfsbytes[4096 + (5 * 1024):4096 + (6 * 1024)] = diagnosticntfsrecord([
            (0x90, bytes(indexroot)),
        ])
        ntfsvolume.write_bytes(ntfsbytes)
        cleanntfsprobe = probevolume(ntfsvolume)
        assert cleanntfsprobe['label'] == 'CACHE'
        assert not cleanntfsprobe['os_install'] and cleanntfsprobe['safe_write']

        ntfsbytes[4096 + (3 * 1024):4096 + (4 * 1024)] = diagnosticntfsrecord([
            (0x60, 'CACHE'.encode('utf-16-le')),
            (0x70, b'\0' * 8 + b'\x03\x01\x01\0'),
        ])
        ntfsvolume.write_bytes(ntfsbytes)
        dirtyntfsprobe = probevolume(ntfsvolume)
        assert not dirtyntfsprobe['os_install'] and not dirtyntfsprobe['safe_write']

        filename = bytearray(66 + (len('Windows') * 2))
        filename[:6] = (5).to_bytes(6, 'little')
        filename[64] = len('Windows')
        filename[65] = 1
        filename[66:] = 'Windows'.encode('utf-16-le')
        ntfsbytes[4096 + (16 * 1024):4096 + (17 * 1024)] = diagnosticntfsrecord([
            (0x30, bytes(filename)),
        ])
        ntfsvolume.write_bytes(ntfsbytes)
        ntfsprobe = probevolume(ntfsvolume)
        assert ntfsprobe['label'] == 'CACHE'
        assert ntfsprobe['os_install'] and not ntfsprobe['safe_write']

        module = root / 'example.ko.zst'
        module.write_bytes(b't1os-driver-diagnostic')
        digest = hashlib.sha256(module.read_bytes()).hexdigest()
        (root / 'module-manifest.sha256').write_text(f'{digest}  ./example.ko.zst\n', encoding='utf-8')
        assert validatemanifest(root) == 1
        module.write_bytes(b'changed')
        try:
            validatemanifest(root)
        except ValueError:
            pass
        else:
            raise AssertionError('changed module passed manifest validation')
    print(json.dumps({'passed': True, 'checks': {
        'module_normalization': True,
        'command_line_blacklist': True,
        'uevent_parser': True,
        'graphics_reset_authentication': True,
        'graphics_reset_validation': True,
        'graphics_reset_sequence': True,
        'graphics_reset_serialization': True,
        'graphics_reset_error_detail': True,
        'nvidia_reset_readiness': True,
        'nvidia_alias_preference': True,
        'nvidia_pci_bind_ownership': True,
        'nvidia_kms_parameters': True,
        'nvidia_modern_device_registration': True,
        'nvidia_uvm_device_registration': True,
        'nvidia_device_node_discovery': True,
        'nvidia_device_node_validation': True,
        'nvidia_uvm_module_load_order': True,
        'nvidia_uvm_primary_node': True,
        'module_manifest': True,
        'device_access_policy': True,
        'external_volume_policy': True,
        'boot_partition_rejection': True,
        'linux_volume_rejection': True,
        'fat_data_volume': True,
        'fat_os_volume_rejection': True,
        'windows_volume_rejection': True,
    }}, sort_keys=True))


def main():
    if len(sys.argv) > 1 and sys.argv[1] == '--diagnostic':
        diagnostic()
        return 0
    server = DriverServer()
    signal.signal(signal.SIGTERM, server.stop)
    signal.signal(signal.SIGINT, server.stop)
    server.run()
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        log(f'fatal: {error}')
        raise
