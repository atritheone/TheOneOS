#!"/the one/software/python/bin/python" -B

"""
settings.py

The first control-panel application for The One OS.
"""

import datetime
import ctypes
import importlib.metadata as importlib_metadata
import ipaddress
import json
import os
import re
import selectors
import secrets
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import zoneinfo


BUILDROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def _prefer_build_root():
    while BUILDROOT in sys.path:
        sys.path.remove(BUILDROOT)
    sys.path.insert(0, BUILDROOT)


_prefer_build_root()

try:
    from python.python import (
        PythonManagerError,
        request as pythonrequest,
    )
except Exception:
    PythonManagerError = RuntimeError
    pythonrequest = None

from operations.operations import (
    architect_authorize,
    architect_revoke,
    service_secret_delete,
    service_secret_exists,
    service_secret_put,
    settings_account_get,
    settings_hostname_set,
    settings_master_update,
    settings_recovery_authorize,
    settings_time_set,
)

_prefer_build_root()


APPNAME = 'settings'
APPPATH = '/the one/build/settings/settings.py'
WINDOWSOCK = '/.ephemeral/windowserver/accept.sock'
AUDIOSOCK = '/.ephemeral/audio/accept.sock'
FONT = '/the one/resources/fonts/atkinsonhyperlegiblenext.ttf'
# Keep Settings on the same visual palette as Array.  In particular, normal
# application and control surfaces are black; grey is reserved for outlines,
# secondary text, and transient/status surfaces.
COLOURBG = 0x000000
COLOURTEXT = 0xEFEFEF
COLOURSTATUS = 0x242424
COLOURDIVIDER = 0x3A3A3A
COLOURMUTED = 0x8A8A8A
COLOURERROR = 0xFF0000
SYSTEMROOT = os.environ.get('T1OS_SYSTEM_ROOT', '/the one')
DISPLAYFILE = os.path.join(SYSTEMROOT, 'settings', 'display', 'settings.json')
AUDIOFILE = os.path.join(SYSTEMROOT, 'settings', 'audio', 'audioserver.json')
MOUSEFILE = os.path.join(SYSTEMROOT, 'settings', 'mouse', 'settings.json')
NETWORKDIR = os.path.join(SYSTEMROOT, 'settings', 'network')
NETWORKFILE = os.path.join(NETWORKDIR, 'network.txt')
DNSFILE = os.path.join(NETWORKDIR, 'dns.txt')
ETHERNETNAMESFILE = os.path.join(NETWORKDIR, 'ethernet-names.json')
NETWORKSTATE = os.environ.get('T1OS_NETWORK_STATE', '/.ephemeral/network/connection.json')
WIRELESSFILE = os.path.join(NETWORKDIR, 'wireless.txt')
WIRELESSCREDENTIALPREFIX = 'network.wireless.'
WIRELESSSCANSTATE = os.environ.get('T1OS_WIRELESS_SCAN_STATE', '/.ephemeral/network/wireless.json')
WIRELESSSCANREQUEST = os.environ.get('T1OS_WIRELESS_SCAN_REQUEST', '/.ephemeral/network/scan.request')
NETWORKRECONFIGURE = os.environ.get('T1OS_NETWORK_RECONFIGURE', '/.ephemeral/network/reconfigure.request')
INTERNETTIMEFILE = os.path.join(SYSTEMROOT, 'settings', 'time', 'internet.txt')
VIRTUALBOXTIMEFILE = os.path.join(SYSTEMROOT, 'settings', 'time', 'virtualbox.txt')
TIMEZONEFILE = os.path.join(SYSTEMROOT, 'settings', 'time', 'timezone.txt')
TERMINALNAMEFILE = os.path.join(SYSTEMROOT, 'settings', 'terminal', 'name.txt')
MASTERSETTINGSFILE = os.path.join(
    SYSTEMROOT, 'settings', 'master', 'settings.json')
MASTERHOMEBASE = os.environ.get('T1OS_MASTER_HOME', '/master')
RECOVERYBOOTMOUNT = os.environ.get(
    'T1OS_RECOVERY_BOOT_MOUNT', '/.ephemeral/angel-boot')
RECOVERYMANIFEST = os.path.join(
    SYSTEMROOT, 'settings', 'recovery', 'files.tsv')
ZONEINFODIR = os.path.join(SYSTEMROOT, 'software', 'chromium', 'resources', 'zoneinfo')
DEFAULTTIMEZONE = 'Australia/Sydney'
DEFAULTTERMINALNAME = 'terminal'
MASTERPASSWORDMINCHARS = 4
MASTERPASSWORDMAXCHARS = 32
UISCALEOPTIONS = (
    0.5, 0.6, 0.7, 0.8, 0.9,
    1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 3.0)
CURSORSIZEDEFAULTS = (
    (1080, 23), (1440, 26), (1800, 29), (2160, 31), (2880, 34))
CURSORSIZEMIN = 16
CURSORSIZEMAX = 48
AE_START_YEAR = 2021
DRMSTATE = os.path.join(SYSTEMROOT, 'drivers', 'state', 'class', 'drm')
NETSTATE = os.path.join(SYSTEMROOT, 'drivers', 'state', 'class', 'net')
RTC_SET_TIME = 0x4024700A

MAGIC = b'T1AU'
PROTO = 1
HEADER_SIZE = 12
MSGHELLO = 1
MSGCONFIG = 3
MSGDEVLIST = 10
MSGDEVSET = 11
MSGVOLUME = 30
MSGMUTE = 31
MSGNOTIFY = 41
MSGERROR = 250

DEFAULTDISPLAY = {
    'width': 2560,
    'height': 1440,
    'ui_scale': 1.0,
    'brightness': 100,
    'contrast': 100,
    'saturation': 100,
    'night_light_enabled': False,
    'night_light_mode': 'automatic',
    'night_light_manual_temperature': 3400,
    'night_light_day_temperature': 6500,
    'night_light_sunset_temperature': 4500,
    'night_light_bedtime_temperature': 3400,
    'night_light_day_time': '06:00',
    'night_light_evening_time': '18:00',
    'night_light_bedtime_time': '22:00',
    'night_light_transition_minutes': 10,
    'night_light_preview': False,
}
DEFAULTAUDIO = {
    'mastergain': 0.20,
    'mastermute': False,
    'autodevice': True,
    'device': None,
}
DEFAULTMOUSE = {
    # 100% is the unmodified pointer movement used before this setting existed.
    'cursor_speed': 1.0,
    # None follows the resolution bucket selected by graphics.py.
    'cursor_size': None,
}
DEFAULTNETWORK = {
    'interface': '',
    'dhcp': True,
    'address': '',
    'netmask': '24',
    'gateway': '',
    'dns1': '',
    'dns2': '',
}
DEFAULTWIRELESS = {
    'ssid': '',
    'security': 'wpa2',
    'passphrase': '',
}

SECTIONS = (
    'display', 'audio', 'mouse', 'network', 'time & date', 'master',
    'recovery', 'python', 'about')
ABOUTFOOTER = 'slayer'
VMTESTSTATUSPATH = '/.ephemeral/settings-vm-test.json'
EDITABLE = {
    'network': ('address', 'netmask', 'gateway', 'dns1', 'dns2'),
    'time & date': ('date', 'time'),
}

gfx = None
SELECTOR = selectors.DefaultSelector()
SOCK = None
INBUF = b''
OUTBUF = bytearray()
RUNNING = True
WINID = None
POINTERCURSORMODE = 'arrow'
BUFFER = None
BASEWINW = 920
BASEWINH = 720
BASESCREENW = 1920
BASESCREENH = 1080
WINW = BASEWINW
WINH = BASEWINH
PIXELW = BASEWINW
PIXELH = BASEWINH
UISCALE = 1.0
SCREENW = 1920
SCREENH = 1080
GRAPHICSBACKEND = 'none'
GRAPHICSCONNECTOR = 0
GRAPHICSSTATE = None
GRAPHICSSTRICT = False
GRAPHICSCOMMANDS = None
NEEDWINDOW = True
HASFOCUS = True
NEEDREDRAW = True
LASTWINDOWNAME = ''
SECTION = str(os.environ.get('T1OS_SETTINGS_SECTION', 'display')).strip().lower()
if SECTION not in SECTIONS:
    SECTION = 'display'
SETTINGSTARGET = str(os.environ.get('T1OS_SETTINGS_TARGET', '')).strip().lower()
DISPLAYPAGE = 'main'
STATUS = ''
STATUSERROR = False
STATUSSECTION = ''
EDITFIELD = None
EDITBUFFER = ''
DRAGGING = None
RESOLUTIONEDITED = False
DROPDOWN = None
DROPDOWNHOVER = None
DROPDOWNSEARCH = ''
DROPDOWNSEARCHAT = 0.0
CONTROLS = {}
ABOUTSCROLL = 0
PYTHONSCROLL = 0
PYTHONSTATE = {}
PYTHONMODULES = []
PYTHONSELECTED = ''
PYTHONQUERY = ''
PYTHONPENDING = None
PYTHONWORK = None
PYTHONWORKRESULT = None
PYTHONWORKLOCK = threading.Lock()
PYTHONLASTREFRESH = 0.0
RECOVERY = {'action': ''}
PASSWORDPROMPT = None
PASSWORDPROMPTSEQUENCE = 0

DISPLAY = dict(DEFAULTDISPLAY)
# Brightness, contrast, and saturation are edited as a draft so their sliders
# can repaint immediately without changing the applied display configuration.
# Entries are committed to DISPLAY only by savedisplay(), via the Apply button.
DISPLAYDRAFT = {}
AUDIO = dict(DEFAULTAUDIO)
MOUSE = dict(DEFAULTMOUSE)
NETWORK = dict(DEFAULTNETWORK)
WIRELESS = dict(DEFAULTWIRELESS)
ETHERNETNAMES = {}
TIME = {}
TERMINALNAME = DEFAULTTERMINALNAME
MASTER = {
    'name': '',
    'original_name': '',
    'current_password': '',
    'new_password': '',
    'confirm_password': '',
    'use_master_image': False,
    'original_use_master_image': False,
    'image_path': '',
    'original_image_path': '',
}
MASTERNAMEEDITING = False
PICKER_VERSION = 0
PICKER_PENDING = None
TIMEZONES = []
CLOCKEDITED = False
AUDIODEVICES = []
INTERFACES = []
WIRELESSNETWORKS = []
WIRELESSSTATEMTIME = 0.0
NETWORKSTATEMTIME = 0.0
LASTNETWORKPOLL = 0.0
RESOLUTIONS = []
RESIZETARGET = None


def clamp(value, minimum, maximum):
    return minimum if value < minimum else maximum if value > maximum else value


def uiscalefor(width, height, requested=1.0):
    try:
        requested = clamp(float(requested), 0.5, 3.0)
        width = float(width)
        height = float(height)
        if width <= 0.0 or height <= 0.0:
            return requested
        automatic = min(width / float(BASESCREENW), height / float(BASESCREENH))
        return clamp(automatic * requested, 0.5, 3.0)
    except Exception:
        return 1.0


def automaticcursorsize(screenheight=None):
    height = int(SCREENH if screenheight is None else screenheight)
    return min(CURSORSIZEDEFAULTS, key=lambda item: abs(height - item[0]))[1]


def mousecursorsize():
    value = MOUSE.get('cursor_size')
    if value is None:
        return automaticcursorsize()
    return clamp(int(round(float(value))), CURSORSIZEMIN, CURSORSIZEMAX)


def applyuiscale():
    global UISCALE
    previous = float(UISCALE)
    UISCALE = uiscalefor(SCREENW, SCREENH, DISPLAY.get('ui_scale', 1.0))
    return abs(previous - UISCALE) > 0.001


def scalepixel(value, minimum=0):
    scaled = int(round(float(value) * float(UISCALE)))
    return max(int(minimum), scaled)


def scalerect(rect):
    x, y, width, height = [float(value) for value in rect]
    left = int(round(x * UISCALE))
    top = int(round(y * UISCALE))
    right = int(round((x + width) * UISCALE))
    bottom = int(round((y + height) * UISCALE))
    return [left, top, max(0, right - left), max(0, bottom - top)]


def windowpixelsize():
    return scalepixel(BASEWINW, 1), scalepixel(BASEWINH, 1)


def managedtexttop(y, pixelsize, ascender=None):
    """Translate the CPU text top coordinate to the managed GPU line box."""
    try:
        if ascender is None:
            face = gfx.getttfface(FONT)
            if face is None:
                return scalepixel(y)
            face.set_pixel_sizes(0, int(pixelsize))
            ascender = int(face.size.ascender >> 6)
        return scalepixel(y) + int(pixelsize) - int(ascender)
    except Exception:
        return scalepixel(y)


def logicalcoordinate(value):
    return int(round(float(value) / max(0.01, float(UISCALE))))


def atomictext(path, text, mode=0o600):
    directory = os.path.dirname(path)
    os.makedirs(directory, mode=0o700, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.settings-', dir=directory)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            stream.write(str(text))
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except Exception:
            pass
        raise


def atomicjson(path, payload, mode=0o600):
    atomictext(
        path, json.dumps(payload, indent=2, sort_keys=True) + '\n', mode=mode)


def loadjson(path, defaults):
    result = dict(defaults)
    try:
        with open(path, 'r', encoding='utf-8') as stream:
            loaded = json.load(stream)
        if isinstance(loaded, dict):
            result.update(loaded)
    except Exception:
        pass
    return result


def loadkeyvalues(path):
    values = {}
    try:
        with open(path, 'r', encoding='utf-8') as stream:
            for line in stream:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, value = line.split('=', 1)
                values[key.strip()] = value.strip()
    except Exception:
        pass
    return values


def boolvalue(value, default=False):
    if isinstance(value, bool):
        return value
    value = str(value).strip().lower()
    if value in ('true', 'yes', '1', 'on'):
        return True
    if value in ('false', 'no', '0', 'off'):
        return False
    return bool(default)


def validateterminalname(value):
    name = str(value or '').strip()
    if not name:
        raise ValueError('Terminal name cannot be empty.')
    if len(name) > 63:
        raise ValueError('Terminal name must be 63 characters or fewer.')
    if not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', name):
        raise ValueError(
            'Terminal name may contain letters, numbers, and internal hyphens.')
    return name


def readterminalname():
    try:
        with open(TERMINALNAMEFILE, 'r', encoding='utf-8') as stream:
            return validateterminalname(stream.read(256))
    except Exception:
        try:
            hostname = str(socket.gethostname() or '').strip()
            if hostname.lower() not in ('', '(none)', 'localhost'):
                return validateterminalname(hostname)
        except Exception:
            pass
    return DEFAULTTERMINALNAME


def setterminalhostname(name):
    encoded = validateterminalname(name).encode('ascii')
    library = ctypes.CDLL(None, use_errno=True)
    operation = library.sethostname
    operation.argtypes = (ctypes.c_char_p, ctypes.c_size_t)
    operation.restype = ctypes.c_int
    if operation(encoded, len(encoded)) != 0:
        errornumber = ctypes.get_errno()
        raise OSError(errornumber, os.strerror(errornumber))


def validatemastername(value):
    name = str(value or '').strip()
    if not name:
        raise ValueError('Master name cannot be empty.')
    if len(name) > 64:
        raise ValueError('Master name must be 64 characters or fewer.')
    if name in ('.', '..'):
        raise ValueError('Master name is not valid.')
    if any(
        character in '/\\:' or not character.isprintable()
        for character in name
    ):
        raise ValueError(
            'Master name cannot contain slashes, colons, or control characters.')
    return name


def readmasteraccount():
    """Return only the non-secret account identity exposed by Operations."""

    try:
        result = settings_account_get(timeout=3.0)
        return validatemastername(result.get('username')), '', []
    except Exception:
        return '', '', []


def masterhomepath(name):
    base = os.path.abspath(MASTERHOMEBASE)
    path = os.path.abspath(os.path.join(base, validatemastername(name)))
    if os.path.commonpath((base, path)) != base:
        raise ValueError('Master home path is not valid.')
    return path


def clearmasterpasswords():
    for field in ('current_password', 'new_password', 'confirm_password'):
        MASTER[field] = ''


def validatemasterimagepath(value, required=False):
    path = str(value or '').strip()
    if not path:
        if required:
            raise ValueError('Choose a master image before applying.')
        return ''
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        raise ValueError('The selected master image could not be found.')
    if os.path.splitext(path)[1].lower() not in (
        '.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif',
    ):
        raise ValueError(
            'Choose a PNG, JPEG, WebP, BMP, or GIF image.')
    return path


def relocatedmasterimagepath(path, oldhome, newhome):
    path = str(path or '').strip()
    if not path:
        return ''
    absolute = os.path.abspath(path)
    try:
        if os.path.commonpath((os.path.abspath(oldhome), absolute)) != os.path.abspath(oldhome):
            return absolute
    except ValueError:
        return absolute
    return os.path.join(
        os.path.abspath(newhome),
        os.path.relpath(absolute, os.path.abspath(oldhome)))


def clockvalue(value, default='00:00'):
    match = re.fullmatch(r'\s*([01]?\d|2[0-3]):([0-5]\d)\s*', str(value))
    if not match:
        return str(default)
    return '{:02d}:{:02d}'.format(int(match.group(1)), int(match.group(2)))


def nightlightactive():
    return bool(DISPLAY.get('night_light_enabled'))


def nightlightsummary():
    if not DISPLAY.get('night_light_enabled'):
        return 'off'
    mode = str(DISPLAY.get('night_light_mode', 'automatic'))
    if mode == 'manual':
        return 'manual · {} K'.format(
            int(DISPLAY.get('night_light_manual_temperature', 3400)))
    return 'automatic · {} / {} / {}'.format(
        DISPLAY.get('night_light_day_time', '06:00'),
        DISPLAY.get('night_light_evening_time', '18:00'),
        DISPLAY.get('night_light_bedtime_time', '22:00'))


def systemtext(path, limit=65536):
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as stream:
            return stream.read(max(1, int(limit)))
    except Exception:
        return ''


def cleanhardwarelabel(value):
    cleaned = ''.join(
        character if character.isprintable() else ' '
        for character in str(value or '')
    )
    return ' '.join(cleaned.split()).strip()


def processorname(processroot=None):
    processroot = processroot or os.path.join(SYSTEMROOT, 'drivers', 'processes')
    values = {}
    for line in systemtext(os.path.join(processroot, 'cpuinfo')).splitlines():
        if ':' not in line:
            continue
        key, value = line.split(':', 1)
        key = key.strip().casefold()
        value = cleanhardwarelabel(value)
        if value and key not in values:
            values[key] = value
    for key in ('model name', 'hardware', 'processor', 'cpu model'):
        value = values.get(key, '')
        if value and not value.isdigit():
            return value
    return 'Unknown processor'


def installedmemory(processroot=None, dmientries=None):
    processroot = processroot or os.path.join(SYSTEMROOT, 'drivers', 'processes')
    dmientries = dmientries or os.path.join(
        SYSTEMROOT, 'drivers', 'state', 'firmware', 'dmi', 'entries')
    installedbytes = 0
    try:
        entries = sorted(
            name for name in os.listdir(dmientries)
            if name == '17' or name.startswith('17-'))
    except Exception:
        entries = []
    for entry in entries:
        try:
            with open(os.path.join(dmientries, entry, 'raw'), 'rb') as stream:
                raw = stream.read(4096)
        except Exception:
            continue
        if len(raw) < 14 or raw[0] != 17:
            continue
        size = int.from_bytes(raw[12:14], 'little')
        if size in (0, 0xFFFF):
            continue
        if size == 0x7FFF:
            if len(raw) < 32:
                continue
            megabytes = int.from_bytes(raw[28:32], 'little') & 0x7FFFFFFF
            installedbytes += megabytes * 1024 * 1024
        elif size & 0x8000:
            installedbytes += (size & 0x7FFF) * 1024
        else:
            installedbytes += size * 1024 * 1024
    if installedbytes:
        gibibytes = installedbytes / (1024.0 ** 3)
        if gibibytes < 1.0:
            return str(max(1, int(round(gibibytes * 1024.0)))) + ' MB'
        return str(max(1, int(round(gibibytes)))) + ' GB'

    match = re.search(
        r'^MemTotal:\s*([0-9]+)\s*kB\b',
        systemtext(os.path.join(processroot, 'meminfo')),
        flags=re.IGNORECASE | re.MULTILINE)
    if not match:
        return 'Unknown RAM'
    gibibytes = (int(match.group(1)) * 1024.0) / (1024.0 ** 3)
    if gibibytes < 1.0:
        return str(max(1, int(round(gibibytes * 1024.0)))) + ' MB'
    # MemTotal is usable memory and excludes firmware and PCI reservations.
    # When SMBIOS is unavailable, round to the nearest four-GB installed
    # boundary rather than presenting values such as 46 GB for a 48 GB kit.
    if gibibytes >= 8.0:
        return str(max(4, int((gibibytes + 3.999) // 4) * 4)) + ' GB'
    return str(max(1, int(gibibytes + 0.999))) + ' GB'


def formatcapacity(bytecount):
    try:
        value = max(0.0, float(bytecount))
    except (TypeError, ValueError):
        return ''
    units = ('bytes', 'KB', 'MB', 'GB', 'TB', 'PB')
    unit = units[0]
    for candidate in units:
        unit = candidate
        if value < 1024.0 or candidate == units[-1]:
            break
        value /= 1024.0
    if unit == 'bytes':
        return str(int(value)) + ' ' + unit
    if value < 10.0:
        shown = '{:.1f}'.format(value).rstrip('0').rstrip('.')
    else:
        shown = '{:.0f}'.format(value)
    return shown + ' ' + unit


def storagecomponent(name, blockroot):
    name = str(name or '').strip()
    path = os.path.join(blockroot, name)
    try:
        sectors = int(systemtext(os.path.join(path, 'size'), 64).strip())
    except (TypeError, ValueError):
        sectors = 0
    if sectors <= 0:
        return ''
    model = cleanhardwarelabel(systemtext(os.path.join(path, 'device', 'model'), 256))
    vendor = cleanhardwarelabel(systemtext(os.path.join(path, 'device', 'vendor'), 128))
    if model and vendor and vendor.casefold() not in model.casefold():
        model = vendor + ' ' + model
    return (model or name) + ' — ' + formatcapacity(sectors * 512)


def storagecomponents(blockroot=None):
    blockroot = blockroot or os.path.join(SYSTEMROOT, 'drivers', 'state', 'block')
    components = []
    try:
        entries = sorted(os.listdir(blockroot))
    except Exception:
        entries = []
    for name in entries:
        lowered = name.casefold()
        path = os.path.join(blockroot, name)
        if (
            lowered.startswith(('loop', 'ram', 'zram', 'dm-')) or
            os.path.exists(os.path.join(path, 'partition'))
        ):
            continue
        component = storagecomponent(name, blockroot)
        if component:
            components.append(component)
    return components


def rootmountsource(processroot):
    mounts = systemtext(os.path.join(processroot, 'mounts'))
    for line in mounts.splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[1] == '/':
            return fields[0].replace('\\040', ' ').replace('\\134', '\\')
    mountinfo = systemtext(os.path.join(processroot, 'self', 'mountinfo'))
    for line in mountinfo.splitlines():
        fields = line.split()
        if len(fields) < 7 or fields[4] != '/' or '-' not in fields:
            continue
        separator = fields.index('-')
        if len(fields) > separator + 2:
            return fields[separator + 2]
    commandline = systemtext(os.path.join(processroot, 'cmdline'), 65536)
    match = re.search(r'(?:^|\s)root=([^\s]+)', commandline)
    return match.group(1) if match else ''


def rootmountdevice(processroot):
    """Return the kernel major:minor identity of the mounted root."""
    mountinfo = systemtext(os.path.join(processroot, 'self', 'mountinfo'))
    for line in mountinfo.splitlines():
        fields = line.split()
        if len(fields) >= 6 and fields[4] == '/':
            return fields[2]
    return ''


def parentblockname(token, entries, blockroot):
    """Map a partition name to its whole-disk kernel block entry."""
    token = os.path.basename(str(token or '')).strip()
    if token in entries:
        return token
    for entry in entries:
        if os.path.exists(os.path.join(blockroot, entry, token)):
            return entry
    match = re.match(r'^(nvme\d+n\d+|mmcblk\d+)p\d+$', token)
    if not match:
        match = re.match(r'^((?:sd|vd|xvd|hd)[a-z]+)\d+$', token)
    parent = match.group(1) if match else ''
    return parent if parent in entries else token


def rootblockname(blockroot=None, processroot=None):
    blockroot = blockroot or os.path.join(SYSTEMROOT, 'drivers', 'state', 'block')
    processroot = processroot or os.path.join(SYSTEMROOT, 'drivers', 'processes')
    try:
        entries = sorted(os.listdir(blockroot))
    except Exception:
        entries = []
    source = rootmountsource(processroot)
    token = os.path.basename(source).strip()
    if source.startswith('/'):
        node = os.path.join(SYSTEMROOT, 'drivers', 'nodes', os.path.basename(source))
        resolved = os.path.basename(os.path.realpath(node))
        if resolved in entries:
            token = resolved
    if source.startswith(('UUID=', 'PARTUUID=', 'LABEL=', 'PARTLABEL=')):
        key, expected = source.split('=', 1)
        for entry in entries:
            values = loadkeyvalues(os.path.join(blockroot, entry, 'uevent'))
            if values.get(key) == expected:
                token = entry
                break
    if token not in entries:
        rootdevice = rootmountdevice(processroot)
        for entry in entries:
            candidates = [os.path.join(blockroot, entry)]
            try:
                candidates.extend(
                    os.path.join(blockroot, entry, child)
                    for child in os.listdir(os.path.join(blockroot, entry))
                )
            except Exception:
                pass
            matched = next((
                candidate for candidate in candidates
                if systemtext(os.path.join(candidate, 'dev'), 64).strip() == rootdevice
            ), '')
            if matched:
                token = os.path.basename(matched)
                break
    token = parentblockname(token, entries, blockroot)
    if token not in entries:
        commandline = systemtext(os.path.join(processroot, 'cmdline'), 65536)
        match = re.search(r'(?:^|\s)root=([^\s]+)', commandline)
        if match:
            candidate = os.path.basename(match.group(1)).strip()
            token = parentblockname(candidate, entries, blockroot)
    if token not in entries:
        bootstate = loadkeyvalues(os.path.join(SYSTEMROOT, 'logs', 'kernel.log'))
        if not bootstate:
            bootstate = loadkeyvalues(
                os.path.join(SYSTEMROOT, 'logs', 'hardware-boot.log')
            )
        token = parentblockname(
            os.path.basename(bootstate.get('root_device', '')),
            entries,
            blockroot)
    for entry in entries:
        dmname = systemtext(os.path.join(blockroot, entry, 'dm', 'name'), 256).strip()
        if token and dmname == token:
            token = entry
            break
    visited = set()
    while token and token not in visited:
        visited.add(token)
        path = os.path.join(blockroot, token)
        try:
            slaves = sorted(os.listdir(os.path.join(path, 'slaves')))
        except Exception:
            slaves = []
        if slaves:
            token = slaves[0]
            continue
        normalized = parentblockname(token, entries, blockroot)
        if normalized != token:
            token = normalized
            continue
        if os.path.exists(os.path.join(path, 'partition')):
            realparent = os.path.basename(os.path.dirname(os.path.realpath(path)))
            if realparent in entries and realparent != token:
                token = realparent
                continue
            match = re.match(r'^(nvme\d+n\d+|mmcblk\d+)p\d+$', token)
            parent = match.group(1) if match else re.sub(r'\d+$', '', token)
            if parent in entries:
                token = parent
                continue
        break
    if token in entries and not os.path.exists(os.path.join(blockroot, token, 'partition')):
        return token
    physical = [
        name for name in entries
        if not name.casefold().startswith(('loop', 'ram', 'zram', 'dm-'))
        and not os.path.exists(os.path.join(blockroot, name, 'partition'))
        and storagecomponent(name, blockroot)
    ]
    return physical[0] if len(physical) == 1 else ''


def installedstorage(blockroot=None, processroot=None):
    blockroot = blockroot or os.path.join(SYSTEMROOT, 'drivers', 'state', 'block')
    rootdrive = rootblockname(blockroot, processroot)
    return storagecomponent(rootdrive, blockroot) if rootdrive else 'Unknown storage'


def graphicsproductname(renderer):
    renderer = cleanhardwarelabel(renderer)
    original = renderer
    lowered = renderer.casefold()
    if lowered.startswith('zink '):
        opening = renderer.find('(')
        if opening >= 0:
            product = renderer[opening + 1:].strip()
            if product.endswith(')'):
                product = product[:-1].rstrip()
            if product:
                renderer = product
    renderer = re.sub(r'^mesa(?:\s+dri)?\s+', '', renderer, flags=re.IGNORECASE)
    renderer = re.sub(
        r'^gallium\s+[^ ]+\s+on\s+', '', renderer, flags=re.IGNORECASE)

    # Renderer APIs append implementation data after semicolons. A retail GPU
    # product name does not use these clauses.
    if ';' in renderer:
        renderer = renderer.split(';', 1)[0].strip()

    # NVIDIA's OpenGL renderer historically appends transport/API capabilities
    # in slash form, for example "/PCIe/SSE2".
    renderer = re.sub(
        r'/(?:pcie|agp|sse\d*|opengl|vulkan|drm)(?:/.*)?$',
        '', renderer, flags=re.IGNORECASE).strip()

    # Mesa, Zink, NVK, RADV and other drivers place codenames, compiler
    # versions and backend names in one or more trailing parenthetical groups.
    # Keep only parenthetical phrases that are genuinely marketed as part of a
    # product name.
    marketedqualifiers = (
        'laptop gpu', 'mobile', 'max-q', 'max-q design',
    )
    while True:
        match = re.search(r'\s+\(([^()]*)\)\s*$', renderer)
        if not match:
            break
        details = cleanhardwarelabel(match.group(1)).casefold()
        if details in marketedqualifiers:
            break
        renderer = renderer[:match.start()].rstrip()

    return renderer or original


def graphicscardname(statepath=None):
    statepath = statepath or os.environ.get(
        'T1OS_GRAPHICS_STATE', '/.ephemeral/windowserver/state/graphics.json')
    state = loadjson(statepath, {})
    renderer = cleanhardwarelabel(state.get('renderer'))
    lowered = renderer.casefold()
    software = any(token in lowered for token in (
        'llvmpipe', 'softpipe', 'swrast', 'software rasterizer'))
    if renderer and not software:
        return graphicsproductname(renderer)
    description = cleanhardwarelabel(state.get('drm_description'))
    if description and description.casefold() not in ('none', 'unknown'):
        return description
    driver = cleanhardwarelabel(state.get('drm_driver')).casefold().replace('-', '_')
    drivernames = {
        'amdgpu': 'AMD Radeon Graphics',
        'radeon': 'AMD Radeon Graphics',
        'i915': 'Intel Graphics',
        'xe': 'Intel Graphics',
        'nouveau': 'NVIDIA Graphics',
        'nvidia': 'NVIDIA Graphics',
        'vmwgfx': 'VMware SVGA 3D',
        'vboxvideo': 'VirtualBox Graphics Adapter',
        'virtio_gpu': 'Virtio Graphics',
    }
    if driver in drivernames:
        return drivernames[driver]
    if str(state.get('backend') or '').casefold() == 'framebuffer':
        return 'Framebuffer graphics'
    return renderer or 'Unknown graphics card'


def operatingsystemversion(path=None):
    path = path or os.path.join(SYSTEMROOT, 'settings', 't1osversion.txt')
    version = cleanhardwarelabel(systemtext(path, 256))
    return version or 'Unknown version'


def pythonversion():
    return '.'.join(str(part) for part in sys.version_info[:3])


def installedpythonmodules(systemroot=None):
    """Return managed third-party Python distributions and their versions."""
    systemroot = systemroot or SYSTEMROOT
    pythonlibrary = f'python{sys.version_info.major}.{sys.version_info.minor}'
    locations = (
        os.path.join(
            systemroot, 'software', 'python', 'lib', pythonlibrary,
            'site-packages'),
        os.path.join(systemroot, 'catalogue', 'image'),
    )
    modules = {}
    for location in locations:
        if not os.path.isdir(location):
            continue
        try:
            distributions = importlib_metadata.distributions(path=[location])
            for distribution in distributions:
                package = cleanhardwarelabel(distribution.metadata.get('Name', ''))
                version = cleanhardwarelabel(distribution.version)
                if not package or not version:
                    continue
                names = tuple(
                    cleanhardwarelabel(line)
                    for line in str(
                        distribution.read_text('top_level.txt') or '').splitlines()
                    if re.fullmatch(
                        r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*', line.strip()))
                if not names:
                    names = (package,)
                for name in names:
                    identity = re.sub(r'[-_.]+', '-', name).casefold()
                    modules.setdefault(identity, (name, version))
        except Exception:
            continue
    return tuple(sorted(
        modules.values(),
        key=lambda item: re.sub(r'[^a-z0-9]', '', item[0].casefold())))


def pythonmoduleview():
    """Return the service inventory, with the core scan as a safe fallback."""

    if PYTHONMODULES:
        return list(PYTHONMODULES)
    return [
        {
            'name': re.sub(r'[-_.]+', '-', name).casefold(),
            'display_name': name,
            'version': version,
            'imports': [name],
            'origin': 'system',
            'system': True,
            'requested': False,
            'pinned': False,
        }
        for name, version in installedpythonmodules()
    ]


def selectedpythonmodule():
    return next((
        item for item in pythonmoduleview()
        if str(item.get('name') or '') == str(PYTHONSELECTED or '')
    ), None)


def _pythonworker(operation, arguments, timeout):
    global PYTHONWORKRESULT
    outcome = {'operation': operation, 'response': None, 'error': None}
    try:
        if pythonrequest is None:
            raise RuntimeError('The Python manager client is unavailable.')
        if operation == 'refresh':
            response = None
        else:
            response = pythonrequest(
                operation, arguments=arguments, timeout=timeout)
        statusresponse = pythonrequest('status', timeout=5.0)
        modulesresponse = pythonrequest('list_modules', timeout=5.0)
        outcome.update({
            'response': response,
            'status': statusresponse.get('data', {}),
            'modules': modulesresponse.get('data', {}).get('modules', []),
        })
    except Exception as error:
        outcome['error'] = error
        try:
            statusresponse = pythonrequest('status', timeout=5.0)
            modulesresponse = pythonrequest('list_modules', timeout=5.0)
            outcome.update({
                'status': statusresponse.get('data', {}),
                'modules': modulesresponse.get('data', {}).get('modules', []),
            })
        except Exception:
            pass
    with PYTHONWORKLOCK:
        PYTHONWORKRESULT = outcome


def startpythonrequest(operation='refresh', arguments=None, timeout=10.0):
    global PYTHONWORK
    if PYTHONWORK is not None and PYTHONWORK.is_alive():
        setstatus('A Python request is already running.', True, section='python')
        return False
    thread = threading.Thread(
        target=_pythonworker,
        args=(str(operation), dict(arguments or {}), float(timeout)),
        name='settings Python request',
        daemon=True,
    )
    PYTHONWORK = thread
    thread.start()
    if operation != 'refresh':
        setstatus('Preparing a protected system Python change…', section='python')
    redraw()
    return True


def pollpythonrequest():
    global PYTHONWORK, PYTHONWORKRESULT, PYTHONSTATE, PYTHONMODULES
    global PYTHONSELECTED, PYTHONLASTREFRESH
    with PYTHONWORKLOCK:
        outcome = PYTHONWORKRESULT
        PYTHONWORKRESULT = None
    if outcome is None:
        return False
    try:
        architect_revoke(timeout=3.0)
    except Exception:
        # A consumed one-shot capability may already be absent. A broker
        # transport failure is surfaced by the worker result and cannot grant
        # new authority by itself.
        pass
    PYTHONWORK = None
    PYTHONLASTREFRESH = time.monotonic()
    if isinstance(outcome.get('status'), dict):
        PYTHONSTATE = dict(outcome['status'])
    if isinstance(outcome.get('modules'), list):
        PYTHONMODULES = list(outcome['modules'])
    if PYTHONSELECTED and not selectedpythonmodule():
        PYTHONSELECTED = ''
    error = outcome.get('error')
    if error is not None:
        setstatus(str(error), True, section='python')
    elif outcome.get('operation') == 'refresh':
        # A background inventory refresh is not evidence that the operation
        # which produced a visible error has recovered.  Keep authentication,
        # transport and manager errors on screen until an explicit user action
        # replaces them; otherwise the ten-second refresh loop erases the only
        # useful diagnosis while the page still appears healthy.
        pass
    else:
        response = outcome.get('response') or {}
        setstatus(
            str(response.get('message') or 'Python module change completed.'),
            section='python',
        )
    redraw()
    return True


def queuepythonchange(operation, arguments, message):
    global PYTHONPENDING
    if PYTHONWORK is not None and PYTHONWORK.is_alive():
        setstatus('Wait for the current Python request.', True, section='python')
        return False
    PYTHONPENDING = {
        'operation': str(operation),
        'arguments': dict(arguments or {}),
        'message': str(message),
    }
    setstatus('Review the Python module change.', section='python')
    redraw()
    return True


def cancelpythonchange():
    global PYTHONPENDING
    PYTHONPENDING = None
    setstatus('Python module change cancelled.', section='python')
    redraw()


def confirmpythonchange():
    if not PYTHONPENDING:
        return False
    return openpasswordprompt(
        'python_change',
        'authorise Python change',
        'Enter the current master password to authorise this protected Python change.',
        'python',
        submitlabel='authorise',
    )


def authorisedpythonchange(password):
    global PYTHONPENDING
    pending = dict(PYTHONPENDING or {})
    if not pending:
        raise RuntimeError('The Python change is no longer pending.')
    architect_authorize(
        password,
        pending.get('operation'),
        pending.get('arguments'),
        timeout=10.0)
    PYTHONPENDING = None
    if not startpythonrequest(
            pending.get('operation'), pending.get('arguments'), timeout=900.0):
        architect_revoke(timeout=3.0)
        raise RuntimeError('The Python change could not be started.')
    return True


def kernelrelease(processroot=None):
    processroot = processroot or os.path.join(SYSTEMROOT, 'drivers', 'processes')
    release = cleanhardwarelabel(
        systemtext(os.path.join(processroot, 'sys', 'kernel', 'osrelease'), 256))
    if release:
        return release
    version = cleanhardwarelabel(
        systemtext(os.path.join(processroot, 'version'), 1024))
    match = re.search(r'\bLinux version\s+([^\s]+)', version, re.IGNORECASE)
    if match:
        return cleanhardwarelabel(match.group(1))
    try:
        return cleanhardwarelabel(os.uname().release) or 'unknown'
    except Exception:
        return 'unknown'


def moduleversion(module, stateroot=None):
    module = str(module or '').strip().replace('-', '_')
    stateroot = stateroot or os.path.join(SYSTEMROOT, 'drivers', 'state')
    return cleanhardwarelabel(
        systemtext(os.path.join(stateroot, 'module', module, 'version'), 256))


def devicedriver(devicepath):
    driverlink = os.path.join(devicepath, 'driver')
    try:
        if os.path.exists(driverlink):
            driver = os.path.basename(os.path.realpath(driverlink))
            if driver and driver != 'driver':
                return cleanhardwarelabel(driver).replace('-', '_')
    except Exception:
        pass
    values = loadkeyvalues(os.path.join(devicepath, 'uevent'))
    return cleanhardwarelabel(values.get('DRIVER', '')).replace('-', '_')


def drivermodules(classroot, entryprefix='', excluded=()):
    modules = []
    excluded = {str(value).casefold() for value in excluded}
    try:
        entries = sorted(os.listdir(classroot))
    except Exception:
        entries = []
    for entry in entries:
        if entry.casefold() in excluded or (
            entryprefix and not entry.casefold().startswith(entryprefix.casefold())
        ):
            continue
        base = os.path.join(classroot, entry)
        module = devicedriver(os.path.join(base, 'device'))
        if not module:
            module = devicedriver(base)
        if module and module not in modules:
            modules.append(module)
    return modules


def driverlisttext(modules, names, stateroot=None, processroot=None):
    entries = []
    useskernel = False
    for module in modules:
        module = str(module or '').strip().replace('-', '_')
        if not module:
            continue
        friendly = names.get(module)
        if not friendly:
            friendly = module.replace('_', ' ').strip()
        version = moduleversion(module, stateroot)
        if version:
            entries.append(friendly + ' ' + version)
        else:
            entries.append(friendly)
            useskernel = True
    if not entries:
        return 'No active driver'
    result = ' · '.join(entries)
    if useskernel:
        result += ' — kernel ' + kernelrelease(processroot)
    return result


def platformdrivertext(processroot=None, runtimefile=None):
    runtimefile = runtimefile or os.path.join(
        SYSTEMROOT, 'drivers', 'settings', 'runtime.json')
    runtime = loadjson(runtimefile, {})
    result = 'Linux platform drivers — kernel ' + kernelrelease(processroot)
    kmod = cleanhardwarelabel(runtime.get('kmod_version'))
    if kmod:
        result += ' · module loader ' + kmod
    return result


def graphicsdrivertext(
    statepath=None,
    stateroot=None,
    processroot=None,
):
    statepath = statepath or os.environ.get(
        'T1OS_GRAPHICS_STATE', '/.ephemeral/windowserver/state/graphics.json')
    state = loadjson(statepath, {})
    module = cleanhardwarelabel(
        state.get('drm_binding') or state.get('drm_driver')
    ).casefold().replace('-', '_')
    names = {
        'amdgpu': 'AMDGPU',
        'radeon': 'Radeon',
        'i915': 'Intel i915',
        'xe': 'Intel Xe',
        'nouveau': 'Nouveau',
        'nvidia': 'NVIDIA driver',
        'nvidia_drm': 'NVIDIA driver',
        'vmwgfx': 'VMware graphics',
        'vboxvideo': 'VirtualBox graphics',
        'virtio_gpu': 'Virtio graphics',
    }
    if not module:
        backend = cleanhardwarelabel(state.get('backend')).casefold()
        if backend == 'framebuffer':
            return 'Linux framebuffer — kernel ' + kernelrelease(processroot)
        return 'No active driver'

    label = names.get(module, module.replace('_', ' '))
    version = moduleversion(module, stateroot)
    if not version and module.startswith('nvidia'):
        version = moduleversion('nvidia', stateroot)
    if not version:
        version = cleanhardwarelabel(state.get('drm_version'))
    result = label + ((' ' + version) if version else '')

    provider = cleanhardwarelabel(state.get('provider')).casefold()
    apiversion = cleanhardwarelabel(state.get('version'))
    if provider == 'mesa' or 'mesa' in apiversion.casefold():
        match = re.search(r'\bMesa\s+([0-9][A-Za-z0-9_.+-]*)', apiversion)
        if match:
            result += ' · Mesa ' + match.group(1)
    if not version:
        result += ' — kernel ' + kernelrelease(processroot)
    return result


def audiodrivertext(stateroot=None, processroot=None):
    stateroot = stateroot or os.path.join(SYSTEMROOT, 'drivers', 'state')
    modules = drivermodules(os.path.join(stateroot, 'class', 'sound'), 'card')
    names = {
        'snd_hda_intel': 'Linux HDA audio',
        'snd_usb_audio': 'Linux USB audio',
        'snd_sof': 'Sound Open Firmware',
        'snd_aloop': 'Linux loopback audio',
        'virtio_snd': 'Virtio audio',
    }
    return driverlisttext(modules, names, stateroot, processroot)


def networkdrivertext(stateroot=None, processroot=None):
    stateroot = stateroot or os.path.join(SYSTEMROOT, 'drivers', 'state')
    modules = drivermodules(
        os.path.join(stateroot, 'class', 'net'), excluded=('lo',))
    names = {
        'iwlwifi': 'Intel Wi-Fi',
        'iwlmvm': 'Intel Wi-Fi',
        'brcmfmac': 'Broadcom Wi-Fi',
        'mt7921e': 'MediaTek Wi-Fi',
        'mt7925e': 'MediaTek Wi-Fi',
        'r8169': 'Realtek Ethernet',
        'e1000': 'Intel Ethernet',
        'e1000e': 'Intel Ethernet',
        'igb': 'Intel Ethernet',
        'igc': 'Intel Ethernet',
        'virtio_net': 'Virtio network',
        'vmxnet3': 'VMware network',
    }
    for module in modules:
        if module.startswith(('ath10k', 'ath11k', 'ath12k')):
            names[module] = 'Qualcomm Wi-Fi'
        elif module.startswith(('rtw88', 'rtw89')):
            names[module] = 'Realtek Wi-Fi'
    return driverlisttext(modules, names, stateroot, processroot)


def virtualboxcontrolsresolution():
    client = os.path.join(SYSTEMROOT, 'software', 'virtualbox', 'VBoxDRMClient')
    guestnode = os.path.join(SYSTEMROOT, 'drivers', 'nodes', 'vboxguest')
    try:
        return os.path.isfile(client) and os.access(client, os.X_OK) and os.path.exists(guestnode)
    except Exception:
        return False


def virtualboxtimeavailable():
    service = os.path.join(SYSTEMROOT, 'software', 'virtualbox', 'VBoxT1Service')
    guestnode = os.path.join(SYSTEMROOT, 'drivers', 'nodes', 'vboxguest')
    try:
        return os.path.isfile(service) and os.access(service, os.X_OK) and os.path.exists(guestnode)
    except Exception:
        return False


def displaymodes():
    modes = {(1280, 720), (1366, 768), (1920, 1080), (2560, 1440), (3840, 2160)}
    try:
        for root, directories, files in os.walk(DRMSTATE):
            if 'modes' not in files:
                continue
            with open(os.path.join(root, 'modes'), 'r', encoding='utf-8') as stream:
                for line in stream:
                    parts = line.strip().lower().split('x', 1)
                    if len(parts) == 2:
                        modes.add((int(parts[0]), int(parts[1])))
    except Exception:
        pass
    modes.add((int(DISPLAY['width']), int(DISPLAY['height'])))
    return sorted((mode for mode in modes if mode[0] >= 320 and mode[1] >= 200), key=lambda mode: mode[0] * mode[1])


def syncliveresolution(width, height):
    global RESOLUTIONS
    if RESOLUTIONEDITED:
        return False
    width = clamp(int(width), 320, 8192)
    height = clamp(int(height), 200, 8192)
    changed = int(DISPLAY.get('width', 0)) != width or int(DISPLAY.get('height', 0)) != height
    DISPLAY['width'] = width
    DISPLAY['height'] = height
    if (width, height) not in RESOLUTIONS:
        RESOLUTIONS = sorted(RESOLUTIONS + [(width, height)], key=lambda mode: mode[0] * mode[1])
    return changed


def edidproductname(data):
    if not isinstance(data, (bytes, bytearray)) or len(data) < 128:
        return ''
    if bytes(data[:8]) != b'\x00\xff\xff\xff\xff\xff\xff\x00':
        return ''
    for offset in (54, 72, 90, 108):
        descriptor = bytes(data[offset:offset + 18])
        if len(descriptor) != 18 or descriptor[:3] != b'\x00\x00\x00':
            continue
        if descriptor[3] not in (0xFC, 0xFE):
            continue
        name = descriptor[5:18].decode('ascii', errors='ignore')
        name = ' '.join(name.replace('\x00', '').replace('\n', ' ').replace('\r', ' ').split()).strip()
        if name:
            return name
    return ''


def displayconnectors():
    connectors = []
    try:
        entries = sorted(os.listdir(DRMSTATE))
    except Exception:
        return connectors
    for entry in entries:
        path = os.path.join(DRMSTATE, entry)
        if not os.path.isdir(path) or '-' not in entry:
            continue
        try:
            with open(os.path.join(path, 'status'), 'r', encoding='utf-8', errors='replace') as stream:
                if stream.read().strip().lower() != 'connected':
                    continue
        except Exception:
            continue
        connectorid = 0
        try:
            with open(os.path.join(path, 'connector_id'), 'r', encoding='ascii', errors='replace') as stream:
                connectorid = int(stream.read().strip())
        except Exception:
            pass
        connectors.append((0 if connectorid and connectorid == GRAPHICSCONNECTOR else 1, entry, path))
    connectors.sort(key=lambda item: (item[0], item[1]))
    return connectors


def systemproductname():
    dmi = os.path.join(SYSTEMROOT, 'drivers', 'state', 'class', 'dmi', 'id')
    invalid = {'', 'unknown', 'none', 'not specified', 'system product name',
               'default string', 'to be filled by o.e.m.'}
    for filename in ('product_name', 'board_name'):
        try:
            with open(os.path.join(dmi, filename), 'r', encoding='utf-8', errors='replace') as stream:
                value = ' '.join(stream.read(256).split()).strip()
        except Exception:
            continue
        if value.casefold() not in invalid:
            return value
    return ''


def displayproductname():
    connectors = displayconnectors()
    for priority, entry, path in connectors:
        try:
            with open(os.path.join(path, 'edid'), 'rb') as stream:
                name = edidproductname(stream.read(4096))
        except Exception:
            name = ''
        if name:
            return name
    if virtualboxcontrolsresolution():
        return 'VirtualBox Display'
    if not connectors or any(token in connectors[0][1].casefold() for token in ('edp-', 'lvds-', 'dsi-')):
        product = systemproductname()
        if product:
            return product
    return 'Unknown display'


def networkinterfaces():
    names = set()
    try:
        for name in os.listdir(NETSTATE):
            if name != 'lo' and os.path.isdir(os.path.join(NETSTATE, name)):
                names.add(name)
    except Exception:
        pass
    try:
        for name in os.listdir(NETWORKDIR):
            if name.endswith('.wireless.txt'):
                names.add(name[:-len('.wireless.txt')])
            elif name.endswith('.txt') and name not in ('network.txt', 'dns.txt', 'wireless.txt'):
                names.add(name[:-4])
    except Exception:
        pass
    if NETWORK.get('interface'):
        names.add(str(NETWORK['interface']))
    return sorted(names)


def networktype(interface):
    interface = str(interface or '').strip()
    lowered = interface.lower()
    state = os.path.join(NETSTATE, interface)
    if os.path.isdir(os.path.join(state, 'wireless')) or lowered.startswith(('wl', 'wifi')):
        return 'wi-fi'
    if lowered.startswith(('ww', 'ppp', 'rmnet', 'cdc-wdm')):
        return 'mobile'
    if lowered.startswith(('bnep', 'bt')):
        return 'bluetooth'
    if lowered.startswith(('tun', 'tap', 'wg')):
        return 'vpn'
    if lowered.startswith(('usb', 'rndis')):
        return 'usb'
    return 'ethernet'


def wirelessinterfaces():
    return [interface for interface in INTERFACES if networktype(interface) == 'wi-fi']


def refreshnetworkinterfaces():
    global INTERFACES
    current = networkinterfaces()
    if current == INTERFACES:
        return False
    INTERFACES = current
    return True


def networkwirelessselected():
    configured = str(NETWORK.get('interface') or '').strip()
    if configured:
        return networktype(configured) == 'wi-fi'
    runtime = connectionstate()
    current = str(runtime.get('interface') or '').strip()
    if current and networktype(current) == 'wi-fi':
        return True
    wiredonline = any(
        networktype(interface) == 'ethernet' and interfaceconnected(interface)
        for interface in INTERFACES
    )
    return bool(wirelessinterfaces()) and not wiredonline


def networkdisplayname(value):
    # Network names are user-visible identifiers.  Sanitize control characters
    # without case-folding or otherwise rewriting the router-provided spelling.
    return ''.join(
        character for character in str(value or '')
        if character.isprintable() and character not in ('\r', '\n')
    ).strip()


def ethernetruntime(interface=''):
    runtime = connectionstate()
    current = str(runtime.get('interface') or '').strip()
    if (
        not bool(runtime.get('connected')) or
        not current or
        networktype(current) != 'ethernet' or
        (interface and current != str(interface).strip())
    ):
        return {}
    return runtime


def ethernetconnectionkey(interface=''):
    runtime = ethernetruntime(interface)
    key = str(runtime.get('connection_id') or '').strip()
    return key if key.startswith('ethernet-') and len(key) <= 96 else ''


def ethernetcustomname(interface=''):
    key = ethernetconnectionkey(interface)
    return networkdisplayname(ETHERNETNAMES.get(key, '')) if key else ''


def ethernetdhcpname(interface=''):
    return networkdisplayname(ethernetruntime(interface).get('name', ''))


def refreshwirelessnetworks(force=False):
    global WIRELESSNETWORKS, WIRELESSSTATEMTIME
    try:
        modified = os.path.getmtime(WIRELESSSCANSTATE)
    except OSError:
        modified = 0.0
    if not force and modified == WIRELESSSTATEMTIME:
        return False
    state = loadjson(WIRELESSSCANSTATE, {'networks': []})
    networks = []
    seen = set()
    for item in state.get('networks', []):
        if not isinstance(item, dict):
            continue
        ssid = ''.join(character for character in str(item.get('ssid') or '') if character.isprintable()).strip()
        security = str(item.get('security') or 'wpa2').strip().lower()
        if not ssid or ssid in seen or security not in ('open', 'wpa2', 'wpa3'):
            continue
        seen.add(ssid)
        try:
            signal = int(item.get('signal', -999) or -999)
        except (TypeError, ValueError):
            signal = -999
        networks.append({
            'ssid': ssid,
            'security': security,
            'signal': signal,
        })
    changed = networks != WIRELESSNETWORKS
    WIRELESSNETWORKS = networks
    WIRELESSSTATEMTIME = modified
    if changed and not force and SECTION == 'network':
        setstatus(
            str(len(networks)) + ' Wi-Fi network' + ('' if len(networks) == 1 else 's') + ' found.'
            if networks else 'No Wi-Fi networks were found.',
            error=not networks)
    return changed


def refreshnetworkruntime(force=False):
    global NETWORKSTATEMTIME
    try:
        modified = os.path.getmtime(NETWORKSTATE)
    except OSError:
        modified = 0.0
    if not force and modified == NETWORKSTATEMTIME:
        return False
    NETWORKSTATEMTIME = modified
    if not force and SECTION == 'network':
        state = connectionstate()
        if bool(state.get('connected')):
            name = networkdisplayname(state.get('name'))
            if not name and str(state.get('type') or '').lower() == 'ethernet':
                name = ethernetcustomname(str(state.get('interface') or ''))
            name = name or networkdisplayname(state.get('type') or 'network')
            setstatus(name + ' connected.')
        else:
            setstatus('No network connection.', True)
    return True


def requestwirelessscan():
    if not wirelessinterfaces():
        setstatus('No Wi-Fi interface is available.', True)
        return False
    try:
        atomictext(WIRELESSSCANREQUEST, str(int(time.time())) + '\n')
    except Exception as error:
        setstatus('Could not request a Wi-Fi scan: ' + str(error), True)
        return False
    setstatus('Scanning for Wi-Fi networks…')
    return True


def wirelesssecuritylabel(value):
    return {
        'open': 'open',
        'wpa2': 'WPA2 Personal',
        'wpa3': 'WPA3 Personal',
    }.get(str(value or '').lower(), str(value or ''))


def interfaceconnected(interface):
    state = os.path.join(NETSTATE, str(interface or ''))
    try:
        with open(os.path.join(state, 'carrier'), 'r', encoding='ascii', errors='replace') as stream:
            carrier = stream.read().strip() == '1'
    except Exception:
        carrier = None
    try:
        with open(os.path.join(state, 'operstate'), 'r', encoding='ascii', errors='replace') as stream:
            operating = stream.read().strip().lower()
    except Exception:
        operating = ''
    if networktype(interface) == 'wi-fi':
        return bool(carrier) and operating == 'up'
    if carrier is not None:
        return bool(carrier)
    return operating == 'up'


def connectionstate():
    return loadjson(NETWORKSTATE, {})


def preferrednetworkinterface():
    runtime = connectionstate()
    current = str(runtime.get('interface') or '').strip()
    if current and interfaceconnected(current):
        return current
    configured = str(NETWORK.get('interface') or '').strip()
    if configured:
        return configured
    for interface in INTERFACES:
        if interfaceconnected(interface):
            return interface
    return INTERFACES[0] if INTERFACES else ''


def networkconnectionlabel(interface):
    interface = str(interface or '').strip()
    if not interface:
        return 'no connection'
    kind = networktype(interface)
    if not interfaceconnected(interface):
        return kind
    runtime = connectionstate()
    name = ''
    if str(runtime.get('interface') or '').strip() == interface and bool(runtime.get('connected')):
        name = networkdisplayname(runtime.get('name'))
    if not name and kind == 'ethernet':
        name = ethernetcustomname(interface)
    if not name and kind == 'wi-fi':
        specific = os.path.join(NETWORKDIR, interface + '.wireless.txt')
        wireless = specific if os.path.exists(specific) else os.path.join(NETWORKDIR, 'wireless.txt')
        name = networkdisplayname(loadkeyvalues(wireless).get('ssid'))
    return kind + (' — ' + name if name else '')


def networkdetails(interface):
    interface = str(interface or '').strip()
    if not interface or not interfaceconnected(interface):
        return {}
    runtime = connectionstate()
    if (
        str(runtime.get('interface') or '').strip() != interface or
        not bool(runtime.get('connected'))
    ):
        return {}
    address = str(runtime.get('address') or '').strip()
    gateway = str(runtime.get('gateway') or '').strip()
    if not address or not gateway:
        return {}
    mac = str(runtime.get('mac') or '').strip()
    if not mac:
        try:
            with open(os.path.join(NETSTATE, interface, 'address'), 'r', encoding='ascii', errors='replace') as stream:
                mac = stream.read().strip()
        except Exception:
            mac = ''
    return {
        'interface': interface,
        'mac': mac,
        'address': address,
        'gateway': gateway,
    }


def readinternettime():
    try:
        with open(INTERNETTIMEFILE, 'r', encoding='utf-8') as stream:
            return boolvalue(stream.read(), False)
    except Exception:
        return False


def readvirtualboxtime():
    try:
        with open(VIRTUALBOXTIMEFILE, 'r', encoding='utf-8') as stream:
            return boolvalue(stream.read(), True)
    except Exception:
        return True


def readtimezone():
    try:
        with open(TIMEZONEFILE, 'r', encoding='utf-8') as stream:
            name = stream.read().strip()
    except Exception:
        return DEFAULTTIMEZONE
    if name in ('10', '+10'):
        return DEFAULTTIMEZONE
    return name or DEFAULTTIMEZONE


def zoneinforoots():
    roots = [ZONEINFODIR]
    sourcezoneinfo = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                                  'software', 'chromium', 'resources', 'zoneinfo')
    if sourcezoneinfo not in roots:
        roots.append(sourcezoneinfo)
    return roots


def availabletimezones(refresh=False):
    global TIMEZONES
    if TIMEZONES and not refresh:
        return list(TIMEZONES)
    names = set()
    for root in zoneinforoots():
        for filename in ('zone1970.tab', 'zone.tab'):
            try:
                with open(os.path.join(root, filename), 'r', encoding='utf-8') as stream:
                    for line in stream:
                        if line.startswith('#'):
                            continue
                        columns = line.rstrip('\n').split('\t')
                        if len(columns) >= 3 and '/' in columns[2]:
                            names.add(columns[2])
            except OSError:
                continue
        if names:
            break
    names.add(str(TIME.get('timezone') or readtimezone()))
    names.add(DEFAULTTIMEZONE)
    names.add('UTC')
    TIMEZONES = sorted(name for name in names if name)
    return list(TIMEZONES)


def timezonepath(name):
    name = str(name or '').strip().replace('\\', '/')
    if not name or name.startswith('/') or any(part in ('', '.', '..') for part in name.split('/')):
        raise ValueError('Timezone must be an area and city, such as Australia/Sydney.')
    roots = zoneinforoots()
    for root in roots:
        root = os.path.realpath(root)
        path = os.path.realpath(os.path.join(root, *name.split('/')))
        try:
            inside = os.path.commonpath((root, path)) == root
        except ValueError:
            inside = False
        if inside and os.path.isfile(path):
            return path
    raise ValueError('Unknown timezone: ' + name)


def timezoneinfo(name):
    name = str(name or '').strip()
    with open(timezonepath(name), 'rb') as stream:
        return zoneinfo.ZoneInfo.from_file(stream, key=name)


def motherboarddatetime(name=None, epoch=None):
    name = str(name or TIME.get('timezone') or readtimezone()).strip()
    return datetime.datetime.fromtimestamp(time.time() if epoch is None else float(epoch), timezoneinfo(name))


def formatatreyandate(value):
    ae_year = int(value.year) - (AE_START_YEAR - 1)
    if ae_year < 1:
        raise ValueError('Atreyan dates begin in 1AE.')
    return f'{value.day:02d}:{value.month:02d}:{ae_year}AE'


def parseatreyandate(value):
    match = re.fullmatch(r'\s*(\d{1,2}):(\d{1,2}):(\d+)AE\s*', str(value), re.IGNORECASE)
    if not match:
        raise ValueError('Date must use DD:MM:YAE, such as 23:07:6AE.')
    day, month, ae_year = (int(part) for part in match.groups())
    if ae_year < 1:
        raise ValueError('Atreyan dates begin in 1AE.')
    return datetime.date(ae_year + (AE_START_YEAR - 1), month, day)


def refreshclock():
    if CLOCKEDITED or EDITFIELD in ('date', 'time'):
        return False
    current = motherboarddatetime()
    changed = TIME.get('date') != formatatreyandate(current) or TIME.get('time') != current.strftime('%H:%M')
    TIME['date'] = formatatreyandate(current)
    TIME['time'] = current.strftime('%H:%M')
    return changed


def loadstate():
    global DISPLAY, AUDIO, MOUSE, NETWORK, WIRELESS, ETHERNETNAMES, TIME
    global TERMINALNAME, MASTER, MASTERNAMEEDITING, CLOCKEDITED
    global RESOLUTIONS, INTERFACES, RESOLUTIONEDITED, DISPLAYPAGE
    DISPLAY = loadjson(DISPLAYFILE, DEFAULTDISPLAY)
    DISPLAY['width'] = clamp(int(DISPLAY.get('width', 2560)), 320, 8192)
    DISPLAY['height'] = clamp(int(DISPLAY.get('height', 1440)), 200, 8192)
    DISPLAY['ui_scale'] = clamp(
        float(DISPLAY.get('ui_scale', 1.0)), 0.5, 3.0)
    for field in ('brightness', 'contrast', 'saturation'):
        DISPLAY[field] = clamp(int(DISPLAY.get(field, 100)), 0, 200)
    DISPLAY['night_light_enabled'] = boolvalue(DISPLAY.get('night_light_enabled'))
    # Migrate the previous automatic/custom/always schedule model.  "Always"
    # maps to manual and uses its old bedtime temperature; the scheduled modes
    # map to the new three-transition automatic mode.
    legacyschedule = str(DISPLAY.get('night_light_schedule', '')).strip().lower()
    mode = str(DISPLAY.get('night_light_mode', 'automatic')).strip().lower()
    if legacyschedule == 'always':
        mode = 'manual'
        DISPLAY['night_light_manual_temperature'] = DISPLAY.get(
            'night_light_bedtime_temperature', 3400)
    DISPLAY['night_light_mode'] = mode if mode in ('manual', 'automatic') else 'automatic'
    for field, default in (
        ('night_light_manual_temperature', 3400),
        ('night_light_day_temperature', 6500),
        ('night_light_sunset_temperature', 4500),
        ('night_light_bedtime_temperature', 3400),
    ):
        DISPLAY[field] = clamp(int(DISPLAY.get(field, default)), 1000, 6500)
    DISPLAY['night_light_transition_minutes'] = clamp(
        int(DISPLAY.get('night_light_transition_minutes', 10)), 1, 30)
    for field, default in (
        ('night_light_day_time', '06:00'),
        ('night_light_evening_time', '18:00'),
        ('night_light_bedtime_time', '22:00'),
    ):
        DISPLAY[field] = clockvalue(DISPLAY.get(field, default), default)
    if legacyschedule == 'custom':
        DISPLAY['night_light_day_time'] = clockvalue(
            DISPLAY.get('night_light_custom_end'), '06:00')
        DISPLAY['night_light_evening_time'] = clockvalue(
            DISPLAY.get('night_light_custom_start'), '18:00')
    for obsolete in (
        'night_light_schedule', 'night_light_custom_start',
        'night_light_custom_end', 'night_light_wake_time',
        'night_light_disabled_until', 'night_light_latitude',
        'night_light_longitude',
    ):
        DISPLAY.pop(obsolete, None)
    DISPLAY['night_light_preview'] = boolvalue(
        DISPLAY.get('night_light_preview'))
    DISPLAYDRAFT.clear()
    DISPLAYPAGE = 'night_light' if SECTION == 'display' and SETTINGSTARGET == 'night light' else 'main'

    AUDIO = loadjson(AUDIOFILE, DEFAULTAUDIO)
    AUDIO['mastergain'] = clamp(float(AUDIO.get('mastergain', 0.20)), 0.0, 1.0)
    AUDIO['mastermute'] = boolvalue(AUDIO.get('mastermute'))
    AUDIO['autodevice'] = boolvalue(AUDIO.get('autodevice'), True)

    MOUSE = loadjson(MOUSEFILE, DEFAULTMOUSE)
    MOUSE['cursor_speed'] = clamp(float(MOUSE.get('cursor_speed', 1.0)), 0.25, 2.0)
    cursorsize = MOUSE.get('cursor_size')
    MOUSE['cursor_size'] = (
        None if cursorsize is None else
        clamp(int(round(float(cursorsize))), CURSORSIZEMIN, CURSORSIZEMAX)
    )

    config = loadkeyvalues(NETWORKFILE)
    NETWORK = dict(DEFAULTNETWORK)
    NETWORK.update(config)
    NETWORK['dhcp'] = boolvalue(config.get('dhcp', True), True)
    try:
        with open(DNSFILE, 'r', encoding='utf-8') as stream:
            servers = [line.split(None, 1)[1].strip() for line in stream if line.strip().lower().startswith('nameserver ') and len(line.split(None, 1)) == 2]
        if servers:
            NETWORK['dns1'] = servers[0]
        if len(servers) > 1:
            NETWORK['dns2'] = servers[1]
    except Exception:
        pass
    WIRELESS = dict(DEFAULTWIRELESS)
    WIRELESS.update(loadkeyvalues(WIRELESSFILE))
    # A GUI never receives a saved wireless secret. An empty password means
    # "retain the brokered credential" for the currently configured network;
    # entering a value explicitly rotates it through the privileged broker.
    WIRELESS.pop('passphrase', None)
    credential = str(WIRELESS.get('credential') or '').strip()
    if not validwirelesscredential(credential):
        credential = ''
    try:
        WIRELESS['credential_present'] = bool(
            credential and service_secret_exists(credential, timeout=3.0))
    except Exception:
        WIRELESS['credential_present'] = False
    WIRELESS['passphrase'] = ''
    WIRELESS['security'] = str(WIRELESS.get('security') or 'wpa2').strip().lower()
    if WIRELESS['security'] not in ('open', 'wpa2', 'wpa3'):
        WIRELESS['security'] = 'wpa2'
    ETHERNETNAMES = {
        str(key): networkdisplayname(value)
        for key, value in loadjson(ETHERNETNAMESFILE, {}).items()
        if str(key).startswith('ethernet-') and networkdisplayname(value)
    }

    timezone = readtimezone()
    try:
        current = motherboarddatetime(timezone)
    except Exception:
        timezone = DEFAULTTIMEZONE
        current = motherboarddatetime(timezone)
    TIME = {
        'date': formatatreyandate(current),
        'time': current.strftime('%H:%M'),
        'internet': readinternettime(),
        'virtualbox': readvirtualboxtime(),
        'timezone': timezone,
    }
    TERMINALNAME = readterminalname()
    mastername, _, _ = readmasteraccount()
    mastersettings = loadjson(MASTERSETTINGSFILE, {
        'use_master_image': False,
        'image_path': '',
    })
    usemasterimage = boolvalue(mastersettings.get('use_master_image'))
    masterimagepath = str(mastersettings.get('image_path') or '').strip()
    MASTER = {
        'name': mastername,
        'original_name': mastername,
        'current_password': '',
        'new_password': '',
        'confirm_password': '',
        'use_master_image': usemasterimage,
        'original_use_master_image': usemasterimage,
        'image_path': masterimagepath,
        'original_image_path': masterimagepath,
    }
    MASTERNAMEEDITING = False
    CLOCKEDITED = False
    RESOLUTIONEDITED = False
    RESOLUTIONS = displaymodes()
    INTERFACES = networkinterfaces()
    refreshwirelessnetworks(force=True)
    refreshnetworkruntime(force=True)


def setstatus(message, error=False, section=None):
    global STATUS, STATUSERROR, STATUSSECTION
    STATUS = str(message)
    STATUSERROR = bool(error)
    STATUSSECTION = str(section or SECTION)
    redraw()


def statusvisible(section=None):
    return bool(STATUS and STATUSSECTION == str(section or SECTION))


def saveterminalname(live=True):
    global TERMINALNAME
    name = validateterminalname(TERMINALNAME)
    settings_hostname_set(name, timeout=3.0)
    TERMINALNAME = name
    setstatus('Terminal name applied.', section='about')


def savemaster():
    global MASTER
    requestedname = validatemastername(MASTER.get('name'))
    currentname, _, _ = readmasteraccount()
    if not currentname:
        raise RuntimeError('Master account is unavailable.')

    newpassword = str(MASTER.get('new_password') or '')
    confirmation = str(MASTER.get('confirm_password') or '')
    namechanged = requestedname != currentname
    passwordchanged = bool(newpassword or confirmation)
    usemasterimage = bool(MASTER.get('use_master_image'))
    imagepath = (
        validatemasterimagepath(MASTER.get('image_path'), required=True)
        if usemasterimage else
        os.path.abspath(str(MASTER.get('image_path') or '').strip())
        if str(MASTER.get('image_path') or '').strip() else '')
    profilechanged = (
        usemasterimage != bool(MASTER.get('original_use_master_image')) or
        imagepath != str(MASTER.get('original_image_path') or ''))

    if not namechanged and not passwordchanged and not profilechanged:
        MASTER['current_password'] = ''
        setstatus('No master changes to apply.', section='master')
        return

    currentpassword = str(MASTER.get('current_password') or '')
    try:
        if not currentpassword:
            raise ValueError(
                'Enter the current password to apply master changes.')
        if passwordchanged:
            if not newpassword:
                raise ValueError('New password cannot be empty.')
            if not MASTERPASSWORDMINCHARS <= len(newpassword) <= MASTERPASSWORDMAXCHARS:
                raise ValueError(
                    'New password must contain {}-{} characters.'.format(
                        MASTERPASSWORDMINCHARS, MASTERPASSWORDMAXCHARS))
            if newpassword != confirmation:
                raise ValueError('New passwords do not match.')
        result = settings_master_update(
            currentpassword,
            requestedname,
            new_password=newpassword if passwordchanged else '',
            use_master_image=usemasterimage,
            image_path=imagepath,
            timeout=15.0,
        )
        requestedname = validatemastername(
            result.get('username') or requestedname)
        imagepath = str(result.get('image_path') or imagepath)

        MASTER['name'] = requestedname
        MASTER['original_name'] = requestedname
        MASTER['use_master_image'] = usemasterimage
        MASTER['original_use_master_image'] = usemasterimage
        MASTER['image_path'] = imagepath
        MASTER['original_image_path'] = imagepath
        if profilechanged and (namechanged or passwordchanged):
            message = 'Master account and image settings applied.'
        elif profilechanged:
            message = 'Master image settings applied.'
        else:
            message = (
                'Master name and password changed.'
                if namechanged and passwordchanged else
                'Master name changed. Reopen apps to refresh user paths.'
                if namechanged else
                'Master password changed.')
        setstatus(message, section='master')
    finally:
        clearmasterpasswords()
        redraw()


def savedisplay():
    uiscale = max(0.5, min(3.0, float(DISPLAY.get('ui_scale', 1.0))))
    applied = dict(DISPLAY)
    applied['ui_scale'] = uiscale
    for field in ('brightness', 'contrast', 'saturation'):
        applied[field] = clamp(
            int(DISPLAYDRAFT.get(field, DISPLAY.get(field, 100))), 0, 200)
    nightlight = {
        'night_light_enabled': bool(applied.get('night_light_enabled')),
        'night_light_mode': str(applied.get('night_light_mode', 'automatic')),
        'night_light_manual_temperature': int(applied.get('night_light_manual_temperature', 3400)),
        'night_light_day_temperature': int(applied.get('night_light_day_temperature', 6500)),
        'night_light_sunset_temperature': int(applied.get('night_light_sunset_temperature', 4500)),
        'night_light_bedtime_temperature': int(applied.get('night_light_bedtime_temperature', 3400)),
        'night_light_day_time': clockvalue(applied.get('night_light_day_time'), '06:00'),
        'night_light_evening_time': clockvalue(applied.get('night_light_evening_time'), '18:00'),
        'night_light_bedtime_time': clockvalue(applied.get('night_light_bedtime_time'), '22:00'),
        'night_light_transition_minutes': int(applied.get('night_light_transition_minutes', 10)),
        # Preview is deliberately transient; a reboot must never leave the
        # desktop racing through an accelerated day.
        'night_light_preview': False,
    }
    stored = {
        'width': int(applied['width']),
        'height': int(applied['height']),
        'ui_scale': uiscale,
        'brightness': int(applied['brightness']),
        'contrast': int(applied['contrast']),
        'saturation': int(applied['saturation']),
        **nightlight,
    }
    atomicjson(DISPLAYFILE, stored, mode=0o644)
    DISPLAY.update(applied)
    DISPLAYDRAFT.clear()
    if WINID is not None:
        sendws({
            'op': 'DISPLAY_SETTINGS_SET',
            'winid': WINID,
            'ui_scale': uiscale,
            'brightness': int(applied['brightness']),
            'contrast': int(applied['contrast']),
            'saturation': int(applied['saturation']),
            **{key: applied.get(key, value) for key, value in nightlight.items()},
        })
    if virtualboxcontrolsresolution():
        setstatus('Display settings applied. Resolution remains controlled by VirtualBox Guest Additions.')
    elif GRAPHICSBACKEND == 'framebuffer':
        setstatus('Display settings applied. Resolution is set by the framebuffer.')
    else:
        setstatus('Image settings applied. Resolution takes effect after restarting the graphics service.')


def validateaddress(value, optional=False):
    value = str(value).strip()
    if optional and not value:
        return ''
    return str(ipaddress.ip_address(value))


def validwirelesscredential(value):

    return bool(re.fullmatch(r'network\.wireless\.[0-9a-f]{24}', str(value or '')))


def newwirelesscredential():

    return WIRELESSCREDENTIALPREFIX + secrets.token_hex(12)


def savenetwork():
    interface = str(NETWORK.get('interface', '')).strip()
    wirelesslines = None
    previouswireless = loadkeyvalues(WIRELESSFILE)
    previouscredential = str(previouswireless.get('credential') or '').strip()
    if not validwirelesscredential(previouscredential):
        previouscredential = ''
    newcredential = ''
    activecredential = ''
    pendingpassphrase = ''
    if networkwirelessselected():
        ssid = str(WIRELESS.get('ssid') or '').strip()
        security = str(WIRELESS.get('security') or 'wpa2').strip().lower()
        passphrase = str(WIRELESS.get('passphrase') or '')
        if not ssid or len(ssid.encode('utf-8')) > 32:
            raise ValueError('The Wi-Fi network name must contain 1 to 32 UTF-8 bytes.')
        if '=' in ssid or any(character in ssid for character in ('\x00', '\n', '\r')):
            raise ValueError('The Wi-Fi network name contains an unsupported character.')
        if security not in ('open', 'wpa2', 'wpa3'):
            raise ValueError('Wi-Fi security must be open, WPA2 Personal, or WPA3 Personal.')
        if security != 'open':
            length = len(passphrase.encode('utf-8'))
            if passphrase:
                if length < 8 or length > 63:
                    raise ValueError('The Wi-Fi password must contain 8 to 63 UTF-8 bytes.')
                if any(character in passphrase for character in ('\x00', '\n', '\r')):
                    raise ValueError('The Wi-Fi password contains an unsupported character.')
            else:
                sameprofile = (
                    str(previouswireless.get('ssid') or '') == ssid and
                    str(previouswireless.get('security') or '').strip().lower() == security
                )
                if not (
                    sameprofile and previouscredential and
                    service_secret_exists(previouscredential, timeout=3.0)
                ):
                    raise ValueError(
                        'Enter the Wi-Fi password for this protected network.')
                activecredential = previouscredential
        else:
            passphrase = ''
            WIRELESS['passphrase'] = ''
        wirelesslines = ['ssid=' + ssid, 'security=' + security]
        if passphrase:
            newcredential = newwirelesscredential()
            activecredential = newcredential
            pendingpassphrase = passphrase
        if activecredential:
            wirelesslines.append('credential=' + activecredential)
    if not NETWORK.get('dhcp'):
        address = validateaddress(NETWORK.get('address'))
        gateway = validateaddress(NETWORK.get('gateway'))
        prefix = int(str(NETWORK.get('netmask', '24')).strip())
        if prefix < 0 or prefix > 32:
            raise ValueError('Network prefix must be from 0 to 32.')
        NETWORK['address'], NETWORK['gateway'], NETWORK['netmask'] = address, gateway, str(prefix)
    dns = []
    for field in ('dns1', 'dns2'):
        value = validateaddress(NETWORK.get(field, ''), optional=True)
        NETWORK[field] = value
        if value and value not in dns:
            dns.append(value)
    lines = ['dhcp=' + ('true' if NETWORK.get('dhcp') else 'false')]
    if not NETWORK.get('dhcp'):
        lines.extend(('address=' + NETWORK['address'], 'netmask=' + NETWORK['netmask'], 'gateway=' + NETWORK['gateway']))
    target = os.path.join(NETWORKDIR, interface + '.txt') if interface else NETWORKFILE
    atomictext(target, '\n'.join(lines) + '\n', mode=0o644)
    atomictext(
        DNSFILE, ''.join('nameserver ' + server + '\n' for server in dns),
        mode=0o644)
    if newcredential:
        service_secret_put(newcredential, pendingpassphrase, timeout=3.0)

    try:
        if wirelesslines is not None:
            wirelesscontent = '\n'.join(wirelesslines) + '\n'
            atomictext(WIRELESSFILE, wirelesscontent, mode=0o644)
            for name in wirelessinterfaces():
                atomictext(
                    os.path.join(NETWORKDIR, name + '.wireless.txt'),
                    wirelesscontent,
                    mode=0o644)
    except Exception:
        if newcredential:
            try:
                service_secret_delete(newcredential, timeout=3.0)
            except Exception:
                pass
        raise

    if (
        wirelesslines is not None and
        previouscredential and
        previouscredential != activecredential
    ):
        try:
            service_secret_delete(previouscredential, timeout=3.0)
        except Exception:
            pass
    atomicjson(ETHERNETNAMESFILE, {
        str(key): networkdisplayname(value)
        for key, value in ETHERNETNAMES.items()
        if str(key).startswith('ethernet-') and networkdisplayname(value)
    }, mode=0o644)
    atomictext(NETWORKRECONFIGURE, str(int(time.time())) + '\n')
    if wirelesslines is not None:
        wiredonline = any(
            networktype(name) == 'ethernet' and interfaceconnected(name)
            for name in INTERFACES)
        if wiredonline:
            setstatus('Wi-Fi saved. Ethernet remains preferred while connected.')
        else:
            setstatus('Connecting to ' + str(WIRELESS.get('ssid') or 'Wi-Fi') + '…')
    else:
        setstatus('Network settings applied. Ethernet remains the preferred connection.')


def motherboardclockfields(epoch, name=None):
    zone = timezoneinfo(str(name or TIME.get('timezone') or readtimezone()).strip())
    local = datetime.datetime.fromtimestamp(float(epoch), zone)
    timetable = local.timetuple()
    return (
        local.second,
        local.minute,
        local.hour,
        local.day,
        local.month - 1,
        local.year - 1900,
        (local.weekday() + 1) % 7,
        timetable.tm_yday - 1,
        1 if local.dst() and local.dst() != datetime.timedelta(0) else 0,
    )


def writemotherboardclock(epoch, name=None):
    try:
        import fcntl
    except ImportError:
        return False
    value = struct.pack('9i', *motherboardclockfields(epoch, name))
    nodes = (
        os.path.join(SYSTEMROOT, 'drivers', 'nodes', 'rtc0'),
        os.path.join(SYSTEMROOT, 'drivers', 'nodes', 'rtc'),
    )
    for node in nodes:
        try:
            descriptor = os.open(node, os.O_RDONLY)
            try:
                fcntl.ioctl(descriptor, RTC_SET_TIME, value)
                return True
            finally:
                os.close(descriptor)
        except OSError:
            continue
    return False


def manualepoch(datevalue, timevalue, name):
    zone = timezoneinfo(name)
    datepart = parseatreyandate(datevalue)
    timepart = datetime.datetime.strptime(str(timevalue).strip(), '%H:%M').time()
    requested = datetime.datetime.combine(datepart, timepart)
    requested = requested.replace(tzinfo=zone)
    epoch = requested.timestamp()
    # Reject local times which do not exist during a daylight-saving jump.
    roundtrip = datetime.datetime.fromtimestamp(epoch, zone)
    if formatatreyandate(roundtrip) != formatatreyandate(requested) or roundtrip.strftime('%H:%M') != requested.strftime('%H:%M'):
        raise ValueError('That local time does not exist in ' + name + '.')
    return epoch


def setclock():
    global CLOCKEDITED
    name = str(TIME.get('timezone', DEFAULTTIMEZONE)).strip()
    zone = timezoneinfo(name)
    enabled = bool(TIME.get('internet'))
    virtualbox_enabled = bool(TIME.get('virtualbox'))
    manual = bool(CLOCKEDITED)
    motherboard_updated = False
    epoch = None

    if manual:
        epoch = manualepoch(TIME['date'], TIME['time'], name)
        if not hasattr(time, 'clock_settime'):
            raise PermissionError('This platform does not provide system clock control.')
        enabled = False
        virtualbox_enabled = False
        TIME['internet'] = False
        TIME['virtualbox'] = False

    # Disable automatic sources before a manual step so neither the NTP worker
    # nor the ten-second VirtualBox poll can immediately race the requested time.
    result = settings_time_set(
        name,
        internet=enabled,
        virtualbox=virtualbox_enabled,
        epoch=epoch if manual else None,
        timeout=5.0,
    )
    if manual:
        motherboard_updated = bool(result.get('motherboard_updated'))
    CLOCKEDITED = False
    refreshclock()
    virtualbox_active = virtualbox_enabled and virtualboxtimeavailable()
    if manual and motherboard_updated:
        setstatus('Manual time saved to the system and motherboard clocks; automatic sources are off.')
    elif manual:
        setstatus('Manual system time saved; the motherboard clock was unavailable. Automatic sources are off.')
    elif enabled and virtualbox_active:
        setstatus('Internet and VirtualBox host time enabled.')
    elif enabled:
        setstatus('Internet time enabled. The time service will synchronise shortly.')
    elif virtualbox_active:
        setstatus('VirtualBox host time enabled.')
    else:
        setstatus('Time settings saved. Using the motherboard clock.')


def audiopacket(message, payload=None):
    body = json.dumps(payload or {}, separators=(',', ':')).encode('utf-8')
    return struct.pack('>4sBBHI', MAGIC, PROTO, int(message), 0, len(body)) + body


def audioreceive(channel, expected):
    while True:
        header = b''
        while len(header) < HEADER_SIZE:
            part = channel.recv(HEADER_SIZE - len(header))
            if not part:
                raise ConnectionError('audio server disconnected')
            header += part
        magic, protocol, message, flags, length = struct.unpack('>4sBBHI', header)
        if magic != MAGIC or protocol != PROTO or length > 1024 * 1024:
            raise ValueError('invalid audio response')
        body = b''
        while len(body) < length:
            part = channel.recv(length - len(body))
            if not part:
                raise ConnectionError('audio server disconnected')
            body += part
        payload = json.loads(body.decode('utf-8')) if body else {}
        if message == MSGERROR:
            raise RuntimeError(payload.get('error', 'audio server error'))
        if message == MSGNOTIFY:
            continue
        if message == expected:
            return payload


def audiorequest(channel, message, payload=None):
    channel.sendall(audiopacket(message, payload))
    return audioreceive(channel, message)


def withaudio(callback):
    channel = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    channel.settimeout(2.0)
    try:
        channel.connect(AUDIOSOCK)
        audiorequest(channel, MSGHELLO, {'client': 'settings', 'protocol': PROTO})
        return callback(channel)
    finally:
        channel.close()


def refreshaudio(quiet=False):
    global AUDIODEVICES, AUDIO
    try:
        def fetch(channel):
            return (audiorequest(channel, MSGCONFIG, {}), audiorequest(channel, MSGDEVLIST, {}))
        config, devices = withaudio(fetch)
        AUDIO.update(config)
        AUDIO['mastergain'] = clamp(float(AUDIO.get('mastergain', 0.20)), 0.0, 1.0)
        AUDIO['mastermute'] = boolvalue(AUDIO.get('mastermute'))
        AUDIODEVICES = list(devices.get('devices', []))
        AUDIO['active'] = devices.get('active')
        if not quiet:
            setstatus('Audio devices refreshed.')
        redraw()
        return True
    except Exception as error:
        AUDIODEVICES = []
        if not quiet:
            setstatus('Audio service unavailable: ' + str(error), True)
        return False


def audiodevicename(device):
    if not isinstance(device, dict):
        return 'Audio output'
    identifier = str(device.get('id') or '').strip()
    caps = device.get('caps') if isinstance(device.get('caps'), dict) else {}
    metadata = caps.get('uevent') if isinstance(caps.get('uevent'), dict) else {}
    product = device.get('product') or caps.get('product') or caps.get('model')
    manufacturer = device.get('manufacturer') or caps.get('manufacturer')
    product = ' '.join(str(product or '').replace('_', ' ').split()).strip()
    manufacturer = ' '.join(str(manufacturer or '').replace('_', ' ').split()).strip()
    if product:
        if manufacturer and manufacturer.casefold() not in product.casefold():
            return manufacturer + ' ' + product
        return product
    candidates = (
        device.get('displayname'),
        caps.get('displayname'),
        caps.get('friendlyname'),
        metadata.get('ID_MODEL_FROM_DATABASE'),
        metadata.get('ID_MODEL'),
        metadata.get('PRODUCT'),
        caps.get('name'),
        device.get('name'),
    )
    for candidate in candidates:
        label = ' '.join(str(candidate or '').replace('_', ' ').split()).strip()
        lowered = label.lower()
        if not label or lowered == identifier.lower():
            continue
        if lowered in ('snd', 'sound', 'audio', 'audioout', 'output'):
            continue
        if (lowered.startswith('snd/') or
                lowered.startswith('pcm') and 'd' in lowered):
            continue
        return label
    return 'Audio output'


def saveaudio():
    def apply(channel):
        selected = AUDIO.get('device')
        audiorequest(channel, MSGCONFIG, {
            'autodevice': bool(AUDIO.get('autodevice')),
            'device': selected,
        })
        audiorequest(channel, MSGVOLUME, {'gain': float(AUDIO['mastergain'])})
        audiorequest(channel, MSGMUTE, {'mute': bool(AUDIO['mastermute'])})
        if selected:
            audiorequest(channel, MSGDEVSET, {'id': selected})
    withaudio(apply)
    setstatus('Audio settings applied.')


def savemouse(live=True):
    speed = clamp(float(MOUSE.get('cursor_speed', 1.0)), 0.25, 2.0)
    cursorsize = MOUSE.get('cursor_size')
    cursorsize = (
        None if cursorsize is None else
        clamp(int(round(float(cursorsize))), CURSORSIZEMIN, CURSORSIZEMAX)
    )
    MOUSE['cursor_speed'] = speed
    MOUSE['cursor_size'] = cursorsize
    atomicjson(MOUSEFILE, {
        'cursor_size': cursorsize,
        'cursor_speed': speed,
    }, mode=0o644)
    if live:
        if WINID is not None:
            sendws({
                'op': 'MOUSE_SETTINGS_SET',
                'winid': WINID,
                'cursor_size': cursorsize,
                'cursor_speed': speed,
            })
    setstatus('Mouse settings applied.')


def applysection():
    editsave()
    try:
        if SECTION == 'display':
            savedisplay()
        elif SECTION == 'audio':
            saveaudio()
        elif SECTION == 'mouse':
            savemouse()
        elif SECTION == 'network':
            savenetwork()
        elif SECTION == 'time & date':
            setclock()
        elif SECTION == 'master':
            requestmastersave()
        elif SECTION == 'recovery':
            requestrecoverypassword()
        elif SECTION == 'about':
            saveterminalname()
    except Exception as error:
        setstatus(str(error), True)


def recoveryready():

    if not os.path.ismount(RECOVERYBOOTMOUNT):
        return False, 'The Angel boot-partition request store is unavailable.'

    try:
        with open(RECOVERYMANIFEST, 'r', encoding='utf-8') as stream:
            header = stream.readline().rstrip('\n').split('\t')
    except OSError:
        return False, 'The independent recovery baseline is unavailable.'

    if len(header) < 2 or header[:2] != ['H', '1']:
        return False, 'The recovery baseline identity is invalid.'

    return True, 'Angel recovery is ready.'


def selectrecovery(action):

    action = str(action or '').strip().lower()

    if action not in ('python', 'build', 'reset', 'reinstall'):
        raise ValueError('Choose a supported recovery action.')

    ready, detail = recoveryready()

    if not ready:
        setstatus(detail, True, section='recovery')
        return

    RECOVERY['action'] = action
    setstatus(
        'Review this recovery action, then choose restart to authenticate.',
        section='recovery',
    )
    redraw()


def cancelrecovery():

    global EDITFIELD, EDITBUFFER
    EDITFIELD = None
    EDITBUFFER = ''
    RECOVERY['action'] = ''
    setstatus('Recovery request cancelled.', section='recovery')
    redraw()


def openpasswordprompt(kind, title, message, section, submitlabel='continue'):

    global PASSWORDPROMPT, PASSWORDPROMPTSEQUENCE
    if PASSWORDPROMPT is not None:
        return False
    if WINID is None:
        setstatus(
            'The password prompt is unavailable.', True, section=section)
        return False
    PASSWORDPROMPTSEQUENCE += 1
    dialogid = 'settings-password-{}-{}'.format(
        os.getpid(), PASSWORDPROMPTSEQUENCE)
    PASSWORDPROMPT = {
        'dialog_id': dialogid,
        'kind': str(kind),
        'title': str(title),
        'message': str(message),
        'section': str(section),
        'submit_label': str(submitlabel),
        'winid': None,
    }
    sendws({
        'op': 'CREATE_PASSWORD_PROMPT',
        'parent': int(WINID),
        'dialog_id': dialogid,
        'title': str(title),
        'message': str(message),
        'submit_label': str(submitlabel),
        'cancel_label': 'cancel',
        'max_length': 256,
    })
    setstatus('Enter the current master password.', section=section)
    redraw()
    return True


def retrypasswordprompt(pending):

    prefix = 'The password was incorrect. '
    message = str(pending.get('message', ''))
    while message.startswith(prefix):
        message = message[len(prefix):]
    message = prefix + message
    return openpasswordprompt(
        pending.get('kind', ''),
        pending.get('title', 'authentication required'),
        message,
        pending.get('section', SECTION),
        pending.get('submit_label', 'continue'),
    )


def requestrecoverypassword():

    action = str(RECOVERY.get('action') or '').strip().lower()
    if action not in ('python', 'build', 'reset', 'reinstall'):
        setstatus('Choose a recovery action first.', True, section='recovery')
        return False
    return openpasswordprompt(
        'recovery',
        'confirm recovery',
        'Enter the current master password to authorise {} recovery.'.format(
            action),
        'recovery',
        submitlabel='restart',
    )


def confirmrecovery(password):

    action = str(RECOVERY.get('action') or '').strip().lower()

    if action not in ('python', 'build', 'reset', 'reinstall'):
        raise ValueError('Choose a recovery action first.')

    settings_recovery_authorize(password, action, timeout=10.0)
    RECOVERY['action'] = ''
    setstatus(
        'Angel will ' + action + ' after the computer restarts.',
        section='recovery',
    )
    redraw()


def startmasternamechange():
    global MASTERNAMEEDITING
    editsave()
    MASTER['name'] = str(MASTER.get('original_name') or '')
    clearmasterpasswords()
    MASTERNAMEEDITING = True
    setstatus('Enter a new master name, then confirm it with your password.',
              section='master')
    redraw()


def cancelmasternamechange():
    global MASTERNAMEEDITING, EDITFIELD, EDITBUFFER
    EDITFIELD = None
    EDITBUFFER = ''
    MASTER['name'] = str(MASTER.get('original_name') or '')
    clearmasterpasswords()
    MASTERNAMEEDITING = False
    setstatus('Master name change cancelled.', section='master')
    redraw()


def confirmmasternamechange():
    global MASTERNAMEEDITING
    editsave()
    if str(MASTER.get('name') or '') == str(
        MASTER.get('original_name') or ''
    ):
        clearmasterpasswords()
        MASTERNAMEEDITING = False
        setstatus('Master name is unchanged.', section='master')
        redraw()
        return
    try:
        validatemastername(MASTER.get('name'))
    except Exception as error:
        setstatus(str(error), True, section='master')
        return
    openpasswordprompt(
        'master_name',
        'change master name',
        'Enter the current master password to change the master name.',
        'master',
        submitlabel='change name',
    )


def requestmastersave():

    editsave()
    try:
        requestedname = validatemastername(MASTER.get('name'))
        currentname = str(MASTER.get('original_name') or '')
        newpassword = str(MASTER.get('new_password') or '')
        confirmation = str(MASTER.get('confirm_password') or '')
        accountchanged = requestedname != currentname or bool(
            newpassword or confirmation)
        profilechanged = (
            bool(MASTER.get('use_master_image')) !=
            bool(MASTER.get('original_use_master_image')) or
            str(MASTER.get('image_path') or '') !=
            str(MASTER.get('original_image_path') or '')
        )
        if bool(newpassword or confirmation):
            if not newpassword:
                raise ValueError('New password cannot be empty.')
            if not MASTERPASSWORDMINCHARS <= len(newpassword) <= MASTERPASSWORDMAXCHARS:
                raise ValueError(
                    'New password must contain {}-{} characters.'.format(
                        MASTERPASSWORDMINCHARS, MASTERPASSWORDMAXCHARS))
            if newpassword != confirmation:
                raise ValueError('New passwords do not match.')
        if accountchanged or profilechanged:
            return openpasswordprompt(
                'master_changes',
                'apply master changes',
                'Enter the current master password to apply these changes.',
                'master',
                submitlabel='apply',
            )
        savemaster()
        return True
    except Exception as error:
        setstatus(str(error), True, section='master')
        return False


def handlepasswordpromptresult(message):

    global PASSWORDPROMPT, MASTERNAMEEDITING
    pending = PASSWORDPROMPT
    if pending is None:
        return False
    if str(message.get('dialog_id', '')) != str(pending.get('dialog_id', '')):
        return False
    PASSWORDPROMPT = None
    section = str(pending.get('section', SECTION))
    if str(message.get('result', 'cancel')) != 'submit':
        setstatus('Password entry cancelled.', section=section)
        redraw()
        return True

    password = str(message.get('value', ''))
    try:
        kind = str(pending.get('kind', ''))
        if kind == 'recovery':
            confirmrecovery(password)
        elif kind in ('master_name', 'master_changes'):
            MASTER['current_password'] = password
            savemaster()
            if kind == 'master_name':
                MASTERNAMEEDITING = False
        elif kind == 'python_change':
            authorisedpythonchange(password)
        else:
            raise RuntimeError('The password prompt request is no longer valid.')
    except Exception as error:
        setstatus(str(error), True, section=section)
    finally:
        password = ''
        MASTER['current_password'] = ''
        redraw()
    return True


def pointin(pointx, pointy, rect):
    return bool(rect and rect[0] <= pointx < rect[0] + rect[2] and rect[1] <= pointy < rect[1] + rect[3])


def writevmteststatus(stage, **detail):
    if os.environ.get('T1OS_VM_TEST') != '1':
        return
    try:
        payload = {
            'format': 1,
            'pid': os.getpid(),
            'stage': str(stage),
            'section': str(SECTION),
            'window': int(WINID) if WINID is not None else None,
            'graphics_active': bool(
                GRAPHICSSTATE and GRAPHICSSTATE.get('active')),
            'graphics_pending': bool(
                GRAPHICSSTATE and GRAPHICSSTATE.get('pending')),
            'graphics_failure': str(
                GRAPHICSSTATE.get('failure', '') if GRAPHICSSTATE else ''),
        }
        payload.update(detail)
        with open(VMTESTSTATUSPATH, 'w', encoding='utf-8') as stream:
            json.dump(payload, stream, sort_keys=True, separators=(',', ':'))
            stream.write('\n')
        os.chmod(VMTESTSTATUSPATH, 0o604)
    except Exception:
        pass


def layout():
    contentx = 205
    right = max(contentx + 360, WINW - 28)
    rowwidth = right - contentx
    controls = {'nav': {}, 'dropdowns': {}}
    y = 92
    for section in SECTIONS:
        controls['nav'][section] = [0, y, 190, 42]
        y += 48
    controls['save'] = [right - 112, WINH - 56, 112, 34]
    controls['rows'] = {}
    rowy = 130
    if SECTION == 'display':
        if DISPLAYPAGE == 'main':
            controls['rows']['display'] = [contentx, rowy, rowwidth, 44]
            rowy += 58
            controls['rows']['resolution'] = [contentx, rowy, rowwidth, 44]
            rowy += 58
            controls['rows']['ui_scale'] = [contentx, rowy, rowwidth, 44]
            for field in ('brightness', 'contrast', 'saturation'):
                rowy += 60
                controls['rows'][field] = [contentx, rowy, rowwidth, 46]
            rowy += 58
            controls['rows']['night_light'] = [contentx, rowy, rowwidth, 42]
        elif DISPLAYPAGE == 'night_light':
            controls['rows']['back'] = [contentx, 88, 120, 30]
            controls['rows']['night_light_enabled'] = [contentx, 128, rowwidth, 40]
            controls['rows']['night_light_mode'] = [contentx, 182, rowwidth, 40]
            if str(DISPLAY.get('night_light_mode', 'automatic')) == 'manual':
                controls['rows']['night_light_manual_temperature'] = [contentx, 246, rowwidth, 44]
            else:
                automaticrows = (
                    ('night_light_day_temperature', 232, 44),
                    ('night_light_day_time', 280, 38),
                    ('night_light_sunset_temperature', 326, 44),
                    ('night_light_evening_time', 374, 38),
                    ('night_light_bedtime_temperature', 420, 44),
                    ('night_light_bedtime_time', 468, 38),
                    ('night_light_transition_minutes', 520, 44),
                )
                for field, top, height in automaticrows:
                    controls['rows'][field] = [contentx, top, rowwidth, height]
                controls['rows']['night_light_preview'] = [contentx, 578, 160, 32]
    elif SECTION == 'audio':
        controls['rows']['volume'] = [contentx, rowy, rowwidth, 50]
        rowy += 72
        controls['rows']['mute'] = [contentx, rowy, rowwidth, 44]
        rowy += 58
        controls['rows']['autodevice'] = [contentx, rowy, rowwidth, 44]
        rowy += 58
        controls['rows']['device'] = [contentx, rowy, rowwidth, 44]
        rowy += 58
        controls['rows']['refresh'] = [contentx, rowy, 112, 34]
    elif SECTION == 'mouse':
        controls['rows']['cursor_speed'] = [contentx, rowy, rowwidth, 50]
        rowy += 72
        controls['rows']['cursor_size'] = [contentx, rowy, rowwidth, 70]
    elif SECTION == 'network':
        controls['rows']['connection'] = [contentx, rowy, rowwidth, 40]
        rowy += 50
        controls['rows']['interface'] = [contentx, rowy, rowwidth, 40]
        if networkwirelessselected():
            rowy += 44
            controls['rows']['wifi_network'] = [contentx, rowy, rowwidth, 38]
            rowy += 44
            controls['rows']['security'] = [contentx, rowy, rowwidth, 38]
            rowy += 44
            controls['rows']['passphrase'] = [contentx, rowy, rowwidth, 38]
            rowy += 44
            controls['rows']['scan'] = [contentx, rowy, 160, 32]
            rowy += 44
            controls['rows']['dhcp'] = [contentx, rowy, rowwidth, 38]
            detailfields = (
                ('mac', 'address', 'gateway', 'dns1', 'dns2')
                if NETWORK.get('dhcp') else
                ('address', 'netmask', 'gateway', 'dns1', 'dns2')
            )
            for field in detailfields:
                rowy += 42
                controls['rows'][field] = [contentx, rowy, rowwidth, 36]
        else:
            rowy += 50
            controls['rows']['network_name'] = [contentx, rowy, rowwidth, 40]
            rowy += 50
            controls['rows']['mac'] = [contentx, rowy, rowwidth, 40]
            rowy += 50
            controls['rows']['dhcp'] = [contentx, rowy, rowwidth, 40]
            for field in ('address', 'netmask', 'gateway', 'dns1', 'dns2'):
                rowy += 48
                controls['rows'][field] = [contentx, rowy, rowwidth, 38]
    elif SECTION == 'time & date':
        for field in ('date', 'time', 'timezone'):
            controls['rows'][field] = [contentx, rowy, rowwidth, 44]
            rowy += 58
        controls['rows']['internet'] = [contentx, rowy, rowwidth, 44]
        if virtualboxtimeavailable():
            rowy += 50
            controls['rows']['virtualbox'] = [contentx, rowy, rowwidth, 44]
    elif SECTION == 'master':
        controls['rows']['master_name'] = [contentx, 130, rowwidth, 44]
        if MASTERNAMEEDITING:
            controls['save'] = None
            controls['rows']['master_name_cancel'] = [
                right - 300, 196, 140, 34]
            controls['rows']['master_name_confirm'] = [
                right - 150, 196, 150, 34]
        else:
            controls['rows']['master_name_change'] = [
                right - 150, 184, 150, 34]
            controls['rows']['new_password'] = [
                contentx, 286, rowwidth, 44]
            controls['rows']['confirm_password'] = [
                contentx, 342, rowwidth, 44]
            controls['rows']['use_master_image'] = [
                contentx, 398, rowwidth, 40]
            if MASTER.get('use_master_image'):
                controls['rows']['master_image_path'] = [
                    contentx, 444, rowwidth, 44]
                controls['rows']['master_image_choose'] = [
                    right - 150, 496, 150, 34]
    elif SECTION == 'recovery':
        controls['save'] = None
        if RECOVERY.get('action'):
            controls['rows']['recovery_cancel'] = [
                right - 300, 310, 140, 34]
            controls['rows']['recovery_confirm'] = [
                right - 150, 310, 150, 34]
        else:
            for index, action in enumerate(('python', 'build', 'reset', 'reinstall')):
                controls['rows']['recovery_' + action] = [
                    contentx, 118 + index * 112, rowwidth, 86]
    elif SECTION == 'python':
        controls['save'] = None
        controls['rows']['python_refresh'] = [right - 106, 88, 106, 32]
        controls['rows']['python_check'] = [right - 222, 88, 106, 32]
        controls['rows']['python_query'] = [contentx, 142, max(240, rowwidth - 126), 40]
        controls['rows']['python_add'] = [right - 106, 146, 106, 32]
        if PYTHONPENDING:
            controls['rows']['python_cancel'] = [right - 222, 232, 106, 32]
            controls['rows']['python_confirm'] = [right - 106, 232, 106, 32]
        else:
            selected = selectedpythonmodule()
            if selected and not selected.get('system') and selected.get('requested'):
                controls['rows']['python_remove'] = [right - 338, 232, 106, 32]
                controls['rows']['python_update'] = [right - 222, 232, 106, 32]
                controls['rows']['python_pin'] = [right - 106, 232, 106, 32]
        offset = int(PYTHONSCROLL)
        for index, _item in enumerate(pythonmoduleview()):
            controls['rows']['python_module_' + str(index)] = [
                contentx, 306 + index * 42 - offset, rowwidth, 38]
    elif SECTION == 'about':
        controls['rows']['terminal_name'] = [contentx, 126, rowwidth, 44]
    return controls


def loadgraphics():
    global gfx, GRAPHICSSTATE
    buildroot = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    while buildroot in sys.path:
        sys.path.remove(buildroot)
    sys.path.insert(0, buildroot)
    import graphics.graphics as graphics
    gfx = graphics
    GRAPHICSSTATE = gfx.managedstate()


def configuregraphics(capabilities):
    global GRAPHICSSTRICT
    capabilities = capabilities if isinstance(capabilities, dict) else {}
    GRAPHICSSTRICT = bool(
        capabilities.get('accelerated') and
        capabilities.get('managed_resources'))
    if GRAPHICSSTATE is not None:
        gfx.managedconfigure(
            GRAPHICSSTATE, capabilities,
            required=('rectangle', 'text'))


def managedclip(clip=None):
    if clip is None:
        return [0, 0, int(PIXELW), int(PIXELH)]
    return scalerect(clip)


def drawtext(x, y, text, colour=COLOURTEXT, size=15, clip=None):
    try:
        text = str(text)
        # Empty editable fields have no glyphs to draw.  Omitting their text
        # node keeps the whole retained scene valid while the field border and
        # caret continue to describe the empty value.
        if not text:
            return
        physicalclip = scalerect(clip) if clip is not None else None
        if GRAPHICSCOMMANDS is not None:
            pixelsize = scalepixel(size, 1)
            GRAPHICSCOMMANDS.append({
                'kind': 'text',
                'x': scalepixel(x),
                'y': managedtexttop(y, pixelsize),
                'text': text,
                'size': pixelsize,
                'font': FONT,
                'color': int(colour),
                'clip': physicalclip or managedclip(),
            })
            return
        gfx.drawtextttf(
            scalepixel(x), scalepixel(y), text, int(colour),
            scalepixel(size, 1), fontpath=FONT, clip=physicalclip)
    except Exception:
        pass


def fill(rect, colour):
    physical = scalerect(rect)
    if (
        len(rect) >= 4 and
        int(rect[0]) == 0 and int(rect[1]) == 0 and
        int(rect[2]) == int(WINW) and int(rect[3]) == int(WINH)
    ):
        # Fractional UI scales can round the logical inverse one pixel away
        # from the actual surface.  A canvas background always owns the exact
        # physical surface, independent of logical-coordinate rounding.
        physical = [0, 0, int(PIXELW), int(PIXELH)]
    if GRAPHICSCOMMANDS is not None:
        if physical[2] > 0 and physical[3] > 0:
            GRAPHICSCOMMANDS.append({
                'kind': 'rectangle',
                'rect': physical,
                'color': int(colour),
                'clip': managedclip(),
            })
        return
    gfx.fillrectfast(physical[0], physical[1], physical[2], physical[3], int(colour))


def fillclipped(rect, colour, clip):
    left = max(rect[0], clip[0])
    top = max(rect[1], clip[1])
    right = min(rect[0] + rect[2], clip[0] + clip[2])
    bottom = min(rect[1] + rect[3], clip[1] + clip[3])
    if right > left and bottom > top:
        fill([left, top, right - left, bottom - top], colour)


def fieldrow(name, label, value, rect, disabled=False, secret=False):
    colour = COLOURMUTED if disabled else COLOURTEXT
    drawtext(rect[0], rect[1] + 11, label, colour)
    valuebox = [rect[0] + max(150, rect[2] // 3), rect[1], max(180, rect[2] - max(150, rect[2] // 3)), rect[3]]
    fill(valuebox, COLOURBG)
    border(valuebox, COLOURTEXT if EDITFIELD == name else COLOURDIVIDER)
    shown = EDITBUFFER if EDITFIELD == name else value
    if secret:
        visible = '•' * len(str(shown))
        visible = elidetext(visible, valuebox[2] - 24)
    else:
        visible = shown if EDITFIELD == name else elidetext(shown, valuebox[2] - 24)
    drawtext(valuebox[0] + 12, valuebox[1] + 10, visible, colour)
    if EDITFIELD == name and HASFOCUS:
        caret = valuebox[0] + 12 + min(
            valuebox[2] - 16, max(0, textwidth(visible, 15)))
        fill([caret, valuebox[1] + 8, 2, valuebox[3] - 16], COLOURTEXT)


def fieldvaluebox(rect):
    if not rect:
        return None
    labelwidth = max(150, rect[2] // 3)
    return [
        rect[0] + labelwidth,
        rect[1],
        max(180, rect[2] - labelwidth),
        rect[3],
    ]


def textcursorfields():
    if (
        SECTION == 'display' and DISPLAYPAGE == 'night_light' and
        str(DISPLAY.get('night_light_mode', 'automatic')) == 'automatic'
    ):
        return {
            'night_light_day_time',
            'night_light_evening_time',
            'night_light_bedtime_time',
        }
    if SECTION == 'network':
        fields = {'dns1', 'dns2'}
        if not NETWORK.get('dhcp'):
            fields.update(('address', 'netmask', 'gateway'))
        if networkwirelessselected():
            if str(WIRELESS.get('security') or '').lower() != 'open':
                fields.add('passphrase')
        elif (
            ethernetconnectionkey(preferrednetworkinterface())
            and not ethernetdhcpname(preferrednetworkinterface())
        ):
            fields.add('network_name')
        return fields
    if SECTION == 'time & date':
        return {'date', 'time'}
    if SECTION == 'master':
        if MASTERNAMEEDITING:
            return {'master_name'}
        return {'new_password', 'confirm_password'}
    if SECTION == 'about':
        return {'terminal_name'}
    if SECTION == 'python':
        return {'python_query'}
    return set()


def textcursorhit(x, y):
    if DROPDOWN:
        return False
    rows = CONTROLS.get('rows', {})
    return any(
        pointin(x, y, fieldvaluebox(rows.get(name)))
        for name in textcursorfields()
    )


def dropdownvaluebox(rect):
    labelwidth = max(150, rect[2] // 3)
    return [rect[0] + labelwidth, rect[1], max(180, rect[2] - labelwidth), rect[3]]


def dropdownoptions(options):
    result = []
    for option in options or []:
        if isinstance(option, dict):
            value = option.get('value')
            label = option.get('label', value)
        elif isinstance(option, (tuple, list)) and len(option) >= 2:
            value, label = option[0], option[1]
        else:
            value, label = option, option
        result.append({'value': value, 'label': str(label)})
    return result


def dropdownrow(name, label, value, rect, options, disabled=False):
    drawtext(rect[0], rect[1] + 11, label, COLOURTEXT)
    valuebox = dropdownvaluebox(rect)
    choices = dropdownoptions(options)
    shown = next((choice['label'] for choice in choices if choice['value'] == value), str(value))
    shown = elidetext(shown, valuebox[2] - 48)
    opened = bool(DROPDOWN and DROPDOWN.get('name') == name)
    if GRAPHICSCOMMANDS is not None:
        fill(valuebox, COLOURBG)
        border(valuebox, COLOURTEXT if opened else COLOURDIVIDER)
        drawtext(valuebox[0] + 12, valuebox[1] + 10, shown,
                 COLOURMUTED if disabled else COLOURTEXT, 15)
        chevrondown(valuebox, COLOURMUTED)
    else:
        physical = scalerect(valuebox)
        gfx.drawdropdowncontrol(
            physical[0], physical[1], physical[2], physical[3], shown,
            FONT, scalepixel(15, 1), opened=opened)
    CONTROLS['dropdowns'][name] = {
        'rect': valuebox,
        'options': choices,
        'value': value,
        'disabled': bool(disabled),
    }


def dropdownpopup(name=None):
    name = name or (DROPDOWN or {}).get('name')
    control = CONTROLS.get('dropdowns', {}).get(name)
    if not control:
        return None
    popup, visible = gfx.dropdownpopuprect(
        control['rect'], len(control['options']), WINH, rowheight=34, maximumvisible=8)
    return control, popup, visible


def opendropdown(name):
    global DROPDOWN, DROPDOWNHOVER, DROPDOWNSEARCH, DROPDOWNSEARCHAT
    if EDITFIELD:
        editsave()
    opened = dropdownpopup(name)
    if not opened or opened[0].get('disabled') or not opened[0].get('options'):
        return False
    control, popup, visible = opened
    selected = next((index for index, option in enumerate(control['options']) if option['value'] == control['value']), 0)
    offset = max(0, min(selected - visible // 2, len(control['options']) - visible))
    DROPDOWN = {'name': name, 'offset': offset}
    DROPDOWNHOVER = selected
    DROPDOWNSEARCH = ''
    DROPDOWNSEARCHAT = 0.0
    redraw()
    return True


def closedropdown():
    global DROPDOWN, DROPDOWNHOVER, DROPDOWNSEARCH, DROPDOWNSEARCHAT
    changed = DROPDOWN is not None
    DROPDOWN = None
    DROPDOWNHOVER = None
    DROPDOWNSEARCH = ''
    DROPDOWNSEARCHAT = 0.0
    if changed:
        redraw()
    return changed


def paintdropdown():
    opened = dropdownpopup()
    if not opened:
        return
    control, popup, visible = opened
    offset = max(0, min(int(DROPDOWN.get('offset', 0)), max(0, len(control['options']) - visible)))
    DROPDOWN['offset'] = offset
    choices = control['options'][offset:offset + visible]
    labels = [elidetext(choice['label'], popup[2] - 38) for choice in choices]
    selected = next((index for index, choice in enumerate(choices) if choice['value'] == control['value']), None)
    hovered = None if DROPDOWNHOVER is None else int(DROPDOWNHOVER) - offset
    if hovered is not None and not (0 <= hovered < len(choices)):
        hovered = None
    if GRAPHICSCOMMANDS is not None:
        fill(popup, COLOURBG)
        border(popup, COLOURDIVIDER)
        for index, label in enumerate(labels):
            row = [popup[0] + 1, popup[1] + index * 34 + 1,
                   max(0, popup[2] - 2), 34]
            if index == hovered:
                fill(row, COLOURSTATUS)
            drawtext(row[0] + 10, row[1] + 8, label,
                     COLOURTEXT if index == selected else COLOURMUTED, 15)
    else:
        physical = scalerect(popup)
        gfx.drawdropdownmenu(
            physical, labels, FONT, fontsize=scalepixel(15, 1),
            rowheight=scalepixel(34, 1), selected=selected, hovered=hovered)


def dropdownoptionat(x, y):
    opened = dropdownpopup()
    if not opened:
        return None
    control, popup, visible = opened
    offset = int(DROPDOWN.get('offset', 0))
    return gfx.dropdownindexat(x, y, popup, len(control['options']), offset=offset, rowheight=34)


def dropdownselect(name, value):
    global RESOLUTIONEDITED
    if name == 'resolution':
        DISPLAY['width'], DISPLAY['height'] = int(value[0]), int(value[1])
        RESOLUTIONEDITED = (int(value[0]), int(value[1])) != (int(SCREENW), int(SCREENH))
    elif name == 'ui_scale':
        DISPLAY['ui_scale'] = float(value)
    elif name == 'night_light_mode':
        DISPLAY['night_light_mode'] = str(value)
    elif name == 'device':
        AUDIO['device'] = value
    elif name == 'interface':
        NETWORK['interface'] = str(value or '')
    elif name == 'wifi_network':
        previous = str(WIRELESS.get('ssid') or '')
        WIRELESS['ssid'] = str(value or '')
        if WIRELESS['ssid'] != previous:
            WIRELESS['passphrase'] = ''
        match = next((
            network for network in WIRELESSNETWORKS
            if network.get('ssid') == WIRELESS['ssid']), None)
        if match:
            WIRELESS['security'] = str(match.get('security') or 'wpa2')
    elif name == 'security':
        WIRELESS['security'] = str(value or 'wpa2')
        if WIRELESS['security'] == 'open':
            WIRELESS['passphrase'] = ''
    elif name == 'timezone':
        TIME['timezone'] = str(value)
        try:
            current = motherboarddatetime(str(value))
            TIME['date'] = formatatreyandate(current)
            TIME['time'] = current.strftime('%H:%M')
        except Exception:
            pass
    else:
        return False
    closedropdown()
    redraw()
    return True


def checkbox(rect, checked, label):
    box = [rect[0], rect[1] + 8, 24, 24]
    fill(box, COLOURTEXT if checked else COLOURBG)
    border(box, COLOURDIVIDER)
    if checked:
        fill([box[0] + 6, box[1] + 6, 12, 12], COLOURBG)
    drawtext(rect[0] + 38, rect[1] + 10, label)


def chevrondown(rect, colour=COLOURMUTED):
    # Draw this control glyph from managed rectangles.  The UI font does not
    # contain U+2304, which otherwise appears as a missing-glyph box.
    left = int(rect[0] + rect[2] - 24)
    top = int(rect[1] + rect[3] // 2 - 3)
    for offset in range(4):
        fill([left + offset, top + offset, 2, 2], colour)
        fill([left + 8 - offset, top + offset, 2, 2], colour)


def sectionrow(rect, label, value=''):
    border(rect, COLOURDIVIDER)
    drawtext(rect[0] + 12, rect[1] + 10, label)
    if value:
        available = max(40, rect[2] - textwidth(label, 15) - 68)
        shown = elidetext(value, available, 14)
        drawtext(rect[0] + rect[2] - textwidth(shown, 14) - 30,
                 rect[1] + 11, shown, COLOURMUTED, 14)
    drawtext(rect[0] + rect[2] - 18, rect[1] + 10, '›', COLOURMUTED, 16)


def slider(name, label, value, rect, maximum, suffix='%', minimum=0, marks=()):
    drawtext(rect[0], rect[1], label)
    drawtext(rect[0] + rect[2] - 65, rect[1], str(int(round(value))) + suffix, COLOURMUTED)
    track = [rect[0], rect[1] + 29, rect[2], 8]
    fill(track, COLOURBG)
    border(track, COLOURDIVIDER)
    amount = clamp(
        (float(value) - float(minimum)) /
        float(max(0.001, float(maximum) - float(minimum))),
        0.0, 1.0)
    fill([track[0] + 1, track[1] + 1, int(max(0, track[2] - 2) * amount), track[3] - 2], COLOURTEXT)
    for mark in marks:
        markamount = clamp(
            (float(mark) - float(minimum)) /
            float(max(0.001, float(maximum) - float(minimum))),
            0.0, 1.0)
        markx = track[0] + int(round((track[2] - 1) * markamount))
        fill([markx, track[1] - 3, 1, track[3] + 6], COLOURMUTED)
        labeltext = str(int(round(mark)))
        drawtext(
            markx - textwidth(labeltext, 10) // 2,
            track[1] + 14, labeltext, COLOURMUTED, 10)
    thumbx = track[0] + int((track[2] - 14) * amount)
    fill([thumbx, track[1] - 4, 14, 16], COLOURTEXT)


def border(rect, colour=COLOURDIVIDER):
    x, y, width, height = [int(value) for value in rect]
    fill([x, y, width, 1], colour)
    fill([x, y + height - 1, width, 1], colour)
    fill([x, y, 1, height], colour)
    fill([x + width - 1, y, 1, height], colour)


def textwidth(textvalue, size=16):
    try:
        measured = gfx.measuretext(str(textvalue), scalepixel(size, 1), FONT)
        return max(1, int(round(float(measured) / max(0.01, UISCALE))))
    except Exception:
        return max(1, int(len(str(textvalue)) * int(size) * 0.56))


def elidetext(textvalue, maximumwidth, size=15):
    textvalue = str(textvalue)
    if textwidth(textvalue, size) <= maximumwidth:
        return textvalue
    ellipsis = '…'
    while textvalue and textwidth(textvalue + ellipsis, size) > maximumwidth:
        textvalue = textvalue[:-1]
    return textvalue + ellipsis


def button(rect, label, focused=False):
    # Match windowserver's standard-dialog buttons: transparent dark body,
    # one-pixel dialog outline, centred light text, and a focused underline.
    border(rect, COLOURDIVIDER)
    size = 16
    labelwidth = min(max(1, rect[2] - 8), textwidth(label, size))
    labelx = rect[0] + max(4, (rect[2] - labelwidth) // 2)
    labely = rect[1] + max(2, (rect[3] - size) // 2)
    drawtext(labelx, labely, label, COLOURTEXT, size)
    if focused:
        underliney = min(rect[1] + rect[3] - 5, labely + size + 2)
        fill([labelx, underliney, min(rect[2] - 4, labelwidth), 1], COLOURTEXT)


def informationrow(label, value, y, clip=None):
    drawtext(205, y, label, COLOURMUTED, 15, clip)
    drawtext(
        365, y, elidetext(value, max(180, WINW - 393), 15),
        COLOURTEXT, 15, clip)


def aboutscrollmaximum():
    viewportbottom = WINH - 72
    contentbottom = 766
    return max(0, contentbottom - viewportbottom)


def pythonscrollmaximum(modules=None):
    modules = pythonmoduleview() if modules is None else tuple(modules)
    viewportbottom = WINH - 72
    contentbottom = 312 + max(1, len(modules)) * 42
    return max(0, contentbottom - viewportbottom)


def paint():
    global NEEDREDRAW, CONTROLS, GRAPHICSCOMMANDS
    if (
        not NEEDREDRAW or BUFFER is None or WINID is None or
        RESIZETARGET is not None
    ):
        return
    managed = bool(
        GRAPHICSSTRICT and GRAPHICSSTATE is not None and
        GRAPHICSSTATE.get('available'))
    if managed and GRAPHICSSTATE.get('pending'):
        # Keep the latest application state queued until the preceding retained
        # scene is physically presented.  Consuming NEEDREDRAW here made rapid
        # navigation (or a click during a display-scale resize) update SECTION
        # without ever submitting the corresponding visible scene.
        return
    NEEDREDRAW = False
    if GRAPHICSSTRICT and not managed:
        # Never hide a managed-rendering failure with shared-buffer pixels.
        return
    GRAPHICSCOMMANDS = [] if managed else None
    CONTROLS = layout()
    fill([0, 0, WINW, WINH], COLOURBG)
    # Array keeps its header and sidebar on the same black canvas and separates
    # the panes with a single crisp divider below the header.
    fill([190, 78, 1, max(0, WINH - 78)], COLOURDIVIDER)
    drawtext(22, 28, 'settings', COLOURTEXT, 26)
    for section, rect in CONTROLS['nav'].items():
        textx = 22
        drawtext(textx, rect[1] + 11, section, COLOURTEXT if section == SECTION else COLOURMUTED)
        if section == SECTION:
            labelwidth = min(160, textwidth(section, 15))
            fill([textx, rect[1] + 31, labelwidth, 1], COLOURTEXT)
    title = SECTION
    if SECTION == 'display' and DISPLAYPAGE != 'main':
        title = 'night light'
    drawtext(205, 30, title, COLOURTEXT, 26)
    rows = CONTROLS['rows']

    if SECTION == 'display':
        if DISPLAYPAGE == 'main':
            fieldrow('display', 'display', displayproductname(), rows['display'])
            resolutionoptions = [((width, height), str(width) + ' x ' + str(height)) for width, height in RESOLUTIONS]
            if virtualboxcontrolsresolution():
                resolution = (int(SCREENW), int(SCREENH))
                dropdownrow('resolution', 'resolution', resolution, rows['resolution'],
                            [(resolution, str(SCREENW) + ' x ' + str(SCREENH) + '  (controlled by VirtualBox)')], True)
            elif GRAPHICSBACKEND == 'framebuffer':
                resolution = (int(SCREENW), int(SCREENH))
                dropdownrow('resolution', 'resolution', resolution, rows['resolution'],
                            [(resolution, str(SCREENW) + ' x ' + str(SCREENH) + '  (current framebuffer)')], True)
            else:
                resolution = (int(DISPLAY['width']), int(DISPLAY['height']))
                dropdownrow('resolution', 'resolution', resolution, rows['resolution'], resolutionoptions)
            scaleoptions = [
                (scale, str(int(round(scale * 100.0))) + '%')
                for scale in UISCALEOPTIONS
            ]
            dropdownrow('ui_scale', 'UI scale', float(DISPLAY.get('ui_scale', 1.0)), rows['ui_scale'], scaleoptions)
            slider(
                'brightness', 'brightness',
                DISPLAYDRAFT.get('brightness', DISPLAY['brightness']),
                rows['brightness'], 200)
            slider(
                'contrast', 'contrast',
                DISPLAYDRAFT.get('contrast', DISPLAY['contrast']),
                rows['contrast'], 200)
            slider(
                'saturation', 'saturation',
                DISPLAYDRAFT.get('saturation', DISPLAY['saturation']),
                rows['saturation'], 200)
            sectionrow(rows['night_light'], 'night light', nightlightsummary())
        elif DISPLAYPAGE == 'night_light':
            button(rows['back'], '‹ display')
            checkbox(
                rows['night_light_enabled'],
                DISPLAY.get('night_light_enabled'),
                'turn on')
            dropdownrow(
                'night_light_mode', 'mode',
                str(DISPLAY.get('night_light_mode', 'automatic')),
                rows['night_light_mode'],
                [
                    ('manual', 'manual'),
                    ('automatic', 'automatic'),
                ])
            if str(DISPLAY.get('night_light_mode', 'automatic')) == 'manual':
                slider(
                    'night_light_manual_temperature', 'temperature',
                    DISPLAY.get('night_light_manual_temperature', 3400),
                    rows['night_light_manual_temperature'], 6500, ' K', 1000)
            else:
                slider(
                    'night_light_day_temperature', 'day temperature',
                    DISPLAY.get('night_light_day_temperature', 6500),
                    rows['night_light_day_temperature'], 6500, ' K', 1000)
                fieldrow(
                    'night_light_day_time', 'day starts',
                    DISPLAY.get('night_light_day_time', '06:00'),
                    rows['night_light_day_time'])
                slider(
                    'night_light_sunset_temperature', 'evening temperature',
                    DISPLAY.get('night_light_sunset_temperature', 4500),
                    rows['night_light_sunset_temperature'], 6500, ' K', 1000)
                fieldrow(
                    'night_light_evening_time', 'evening starts',
                    DISPLAY.get('night_light_evening_time', '18:00'),
                    rows['night_light_evening_time'])
                slider(
                    'night_light_bedtime_temperature', 'bedtime temperature',
                    DISPLAY.get('night_light_bedtime_temperature', 3400),
                    rows['night_light_bedtime_temperature'], 6500, ' K', 1000)
                fieldrow(
                    'night_light_bedtime_time', 'bedtime starts',
                    DISPLAY.get('night_light_bedtime_time', '22:00'),
                    rows['night_light_bedtime_time'])
                slider(
                    'night_light_transition_minutes', 'smooth transition',
                    DISPLAY.get('night_light_transition_minutes', 10),
                    rows['night_light_transition_minutes'], 30, ' min', 1)
                button(
                    rows['night_light_preview'],
                    'previewing…' if DISPLAY.get('night_light_preview') else 'preview 24 hours')
    elif SECTION == 'audio':
        slider('volume', 'output volume', float(AUDIO['mastergain']) * 100.0, rows['volume'], 100)
        checkbox(rows['mute'], AUDIO.get('mastermute'), 'mute all output')
        checkbox(rows['autodevice'], AUDIO.get('autodevice'), 'automatically choose an output device')
        active = AUDIO.get('device') or AUDIO.get('active') or ''
        deviceoptions = [(device.get('id'), audiodevicename(device)) for device in AUDIODEVICES if device.get('id')]
        if not deviceoptions:
            deviceoptions = [(active, str(active or 'no device'))]
        dropdownrow('device', 'output device', active,
                    rows['device'], deviceoptions, not AUDIODEVICES)
        button(rows['refresh'], 'refresh')
    elif SECTION == 'mouse':
        slider(
            'cursor_speed', 'cursor speed',
            float(MOUSE.get('cursor_speed', 1.0)) * 100.0,
            rows['cursor_speed'], 200, minimum=25)
        slider(
            'cursor_size', 'cursor size', mousecursorsize(),
            rows['cursor_size'], CURSORSIZEMAX, suffix=' px',
            minimum=CURSORSIZEMIN,
            marks=tuple(size for _, size in CURSORSIZEDEFAULTS))
    elif SECTION == 'network':
        drawtext(
            205, 94,
            'Ethernet is always preferred; Wi-Fi is used when no cable is connected.',
            COLOURMUTED, 13)
        selectedinterface = preferrednetworkinterface()
        details = networkdetails(selectedinterface)
        fieldrow('connection', 'connection', networkconnectionlabel(selectedinterface), rows['connection'])
        interfaceoptions = [('', 'automatic')]
        interfaceoptions.extend((name, networktype(name) + ' — ' + name) for name in INTERFACES)
        dropdownrow('interface', 'interface', str(NETWORK.get('interface') or ''),
                    rows['interface'], interfaceoptions, not INTERFACES)
        if networkwirelessselected():
            networkoptions = []
            savedssid = str(WIRELESS.get('ssid') or '').strip()
            if savedssid:
                networkoptions.append((savedssid, savedssid))
            for network in WIRELESSNETWORKS:
                ssid = network['ssid']
                if ssid == savedssid:
                    continue
                label = ssid + ' — ' + wirelesssecuritylabel(network['security'])
                networkoptions.append((ssid, label))
            dropdownrow(
                'wifi_network', 'Wi-Fi SSID', savedssid, rows['wifi_network'],
                networkoptions, not networkoptions)
            dropdownrow(
                'security', 'security', str(WIRELESS.get('security') or 'wpa2'),
                rows['security'],
                [('open', 'open'), ('wpa2', 'WPA2 Personal'), ('wpa3', 'WPA3 Personal')])
            passworddisabled = str(WIRELESS.get('security') or '').lower() == 'open'
            fieldrow(
                'passphrase', 'password', WIRELESS.get('passphrase', ''),
                rows['passphrase'], disabled=passworddisabled, secret=True)
            button(rows['scan'], 'scan networks')
            checkbox(rows['dhcp'], NETWORK.get('dhcp'), 'automatic address (DHCP)')
            disabled = bool(NETWORK.get('dhcp'))
            if disabled:
                fieldrow('mac', 'MAC address', details.get('mac', ''), rows['mac'], True)
                fieldrow('address', 'IP address', details.get('address', ''), rows['address'], True)
                fieldrow('gateway', 'gateway', details.get('gateway', ''), rows['gateway'], True)
            else:
                fieldrow('address', 'IP address', NETWORK.get('address', ''), rows['address'])
                fieldrow('netmask', 'network prefix', NETWORK.get('netmask', '24'), rows['netmask'])
                fieldrow('gateway', 'gateway', NETWORK.get('gateway', ''), rows['gateway'])
            fieldrow('dns1', 'primary DNS', NETWORK.get('dns1', ''), rows['dns1'])
            fieldrow('dns2', 'secondary DNS', NETWORK.get('dns2', ''), rows['dns2'])
        else:
            routername = ethernetdhcpname(selectedinterface)
            customname = ethernetcustomname(selectedinterface)
            editableethernetname = bool(
                ethernetconnectionkey(selectedinterface) and not routername)
            fieldrow(
                'network_name', 'network name', routername or customname,
                rows['network_name'], disabled=not editableethernetname)
            if details:
                fieldrow('mac', 'MAC address', details.get('mac', ''), rows['mac'], True)
            checkbox(rows['dhcp'], NETWORK.get('dhcp'), 'automatic address (DHCP)')
            disabled = bool(NETWORK.get('dhcp'))
            liveaddress = details.get('address', '') if disabled else ''
            if '/' in liveaddress:
                liveaddress, liveprefix = liveaddress.rsplit('/', 1)
            else:
                liveprefix = ''
            fieldrow('address', 'IP address', liveaddress or NETWORK.get('address', ''), rows['address'], disabled)
            fieldrow('netmask', 'network prefix', liveprefix or NETWORK.get('netmask', '24'), rows['netmask'], disabled)
            fieldrow('gateway', 'gateway', details.get('gateway', '') if disabled and details else NETWORK.get('gateway', ''), rows['gateway'], disabled)
            fieldrow('dns1', 'primary DNS', NETWORK.get('dns1', ''), rows['dns1'])
            fieldrow('dns2', 'secondary DNS', NETWORK.get('dns2', ''), rows['dns2'])
    elif SECTION == 'time & date':
        fieldrow('date', 'date', TIME.get('date', ''), rows['date'])
        fieldrow('time', 'time', TIME.get('time', ''), rows['time'])
        timezone = str(TIME.get('timezone', DEFAULTTIMEZONE))
        dropdownrow('timezone', 'timezone', timezone, rows['timezone'],
                    [(name, name) for name in availabletimezones()])
        checkbox(rows['internet'], TIME.get('internet'), 'set time automatically from the internet')
        if rows.get('virtualbox'):
            checkbox(rows['virtualbox'], TIME.get('virtualbox'), 'synchronise time with the VirtualBox host')
            helpy = 443
        else:
            helpy = 385
        drawtext(205, helpy, 'Date format: DD:MM:YAE. A manual time turns automatic sources off.', COLOURMUTED, 13)
    elif SECTION == 'master':
        fieldrow(
            'master_name', 'master name', MASTER.get('name', ''),
            rows['master_name'], disabled=not MASTERNAMEEDITING)
        if MASTERNAMEEDITING:
            button(rows['master_name_cancel'], 'cancel')
            button(
                rows['master_name_confirm'], 'confirm',
                focused=EDITFIELD is None)
            drawtext(
                205, 252,
                'A password prompt will confirm the master name change.',
                COLOURMUTED, 13)
        else:
            button(rows['master_name_change'], 'change name')
            drawtext(205, 250, 'change password', COLOURTEXT, 19)
            fieldrow(
                'new_password', 'new password',
                MASTER.get('new_password', ''),
                rows['new_password'], secret=True)
            fieldrow(
                'confirm_password', 'confirm password',
                MASTER.get('confirm_password', ''),
                rows['confirm_password'], secret=True)
            checkbox(
                rows['use_master_image'],
                MASTER.get('use_master_image'),
                'use master image')
            if MASTER.get('use_master_image'):
                fieldrow(
                    'master_image_path', 'image file',
                    MASTER.get('image_path', ''),
                    rows['master_image_path'])
                button(
                    rows['master_image_choose'],
                    'change image' if MASTER.get('image_path')
                    else 'choose image')
            drawtext(
                205, 546,
                'Passwords use 4-32 characters; applying asks for the current password.',
                COLOURMUTED, 13)
    elif SECTION == 'recovery':
        ready, recoverydetail = recoveryready()
        drawtext(
            205, 88, recoverydetail,
            COLOURTEXT if ready else COLOURERROR, 14)
        action = str(RECOVERY.get('action') or '')
        recoverydescriptions = {
            'python': (
                'repair Python',
                'Restore Python, its managed libraries, and the image catalogue.'),
            'build': (
                'reset build software',
                'Replace the complete build software tree with the recovery baseline.'),
            'reset': (
                'reset The One OS',
                'Replace operating-system files and settings while keeping user files.'),
            'reinstall': (
                'reinstall The One OS',
                'Erase every user file, then install a clean operating-system baseline.'),
        }
        if not action:
            for name in ('python', 'build', 'reset', 'reinstall'):
                rect = rows['recovery_' + name]
                heading, detail = recoverydescriptions[name]
                drawtext(rect[0], rect[1] + 8, heading, COLOURTEXT, 18)
                drawtext(rect[0], rect[1] + 40, detail, COLOURMUTED, 13)
                button(
                    [rect[0] + rect[2] - 112, rect[1] + 18, 112, 34],
                    'select')
                fill(
                    [rect[0], rect[1] + rect[3], rect[2], 1],
                    COLOURDIVIDER)
        else:
            heading, detail = recoverydescriptions.get(
                action, ('recovery', 'Choose a recovery action.'))
            drawtext(205, 142, heading, COLOURTEXT, 22)
            drawtext(205, 184, detail, COLOURMUTED, 14)
            if action == 'reinstall':
                drawtext(
                    205, 226,
                    'Reinstall permanently removes every user file from the root drive.',
                    COLOURERROR, 14)
            else:
                drawtext(
                    205, 226,
                    'The computer will restart into Angel recovery.',
                    COLOURMUTED, 14)
            button(rows['recovery_cancel'], 'cancel')
            button(
                rows['recovery_confirm'], 'restart',
                focused=EDITFIELD is None)
    elif SECTION == 'python':
        state = PYTHONSTATE
        core = state.get('core', {})
        busy = bool(PYTHONWORK is not None and PYTHONWORK.is_alive())
        drawtext(205, 92, 'runtime', COLOURTEXT, 19)
        drawtext(
            205, 120,
            '{} — {} — {}'.format(
                str(core.get('version') or pythonversion()),
                str(state.get('health') or 'manager not connected'),
                'protected changes',
            ),
            COLOURTEXT if state.get('health') == 'healthy' else COLOURMUTED,
            14,
        )
        button(rows['python_check'], 'check')
        button(rows['python_refresh'], 'refresh')
        fieldrow(
            'python_query', 'add module',
            EDITBUFFER if EDITFIELD == 'python_query' else PYTHONQUERY,
            rows['python_query'], disabled=busy)
        button(rows['python_add'], 'add')
        drawtext(
            205, 202,
            'Each module change requires master-password authorisation.',
            COLOURMUTED, 13)

        selected = selectedpythonmodule()
        if PYTHONPENDING:
            drawtext(
                205, 242, elidetext(PYTHONPENDING.get('message', ''), max(180, WINW - 460)),
                COLOURTEXT, 13)
            button(rows['python_cancel'], 'cancel')
            button(rows['python_confirm'], 'confirm')
        elif selected:
            detail = '{} {} — {}'.format(
                selected.get('display_name') or selected.get('name') or '',
                selected.get('version') or '',
                'system' if selected.get('system') else 'requested' if selected.get('requested') else 'dependency',
            )
            drawtext(205, 242, elidetext(detail, max(180, WINW - 600)), COLOURTEXT, 13)
            if not selected.get('system') and selected.get('requested'):
                button(rows['python_remove'], 'remove')
                button(rows['python_update'], 'update')
                button(rows['python_pin'], 'unpin' if selected.get('pinned') else 'pin')
        elif busy:
            phase = str((state.get('transaction') or {}).get('phase') or 'working')
            drawtext(205, 242, phase + '…', COLOURTEXT, 13)

        fill([205, 272, max(0, WINW - 233), 1], COLOURDIVIDER)
        modules = pythonmoduleview()
        moduleclip = [191, 274, max(0, WINW - 191), max(0, WINH - 346)]
        offset = int(PYTHONSCROLL)
        drawtext(205, 282, 'installed modules', COLOURTEXT, 17, moduleclip)
        if modules:
            for index, item in enumerate(modules):
                top = 312 + index * 42 - offset
                name = str(item.get('display_name') or item.get('name') or '')
                version = str(item.get('version') or '')
                kind = 'system' if item.get('system') else 'requested' if item.get('requested') else 'dependency'
                if item.get('pinned'):
                    kind += ', pinned'
                if str(item.get('name') or '') == PYTHONSELECTED:
                    fillclipped([195, top - 4, max(0, WINW - 223), 36], COLOURSTATUS, moduleclip)
                drawtext(205, top, name, COLOURTEXT, 15, moduleclip)
                value = version + ' — ' + kind
                drawtext(
                    max(470, WINW - 330), top,
                    elidetext(value, 280), COLOURMUTED, 13, moduleclip)
        else:
            drawtext(
                205, 312, 'No Python modules are installed.',
                COLOURMUTED, 15, moduleclip)
    elif SECTION == 'about':
        drawtext(205, 94, 'terminal', COLOURTEXT, 19)
        fieldrow(
            'terminal_name', 'terminal name', TERMINALNAME,
            rows['terminal_name'])
        aboutclip = [191, 180, max(0, WINW - 191), max(0, WINH - 252)]
        offset = int(ABOUTSCROLL)
        drawtext(205, 190 - offset, 'components', COLOURTEXT, 19, aboutclip)
        informationrow('processor', processorname(), 230 - offset, aboutclip)
        informationrow(
            'graphics card', graphicscardname(), 272 - offset, aboutclip)
        informationrow('RAM', installedmemory(), 314 - offset, aboutclip)
        informationrow('storage', installedstorage(), 356 - offset, aboutclip)
        fillclipped(
            [205, 394 - offset, max(0, WINW - 233), 1],
            COLOURDIVIDER, aboutclip)
        drawtext(205, 418 - offset, 'drivers', COLOURTEXT, 19, aboutclip)
        informationrow(
            'platform', platformdrivertext(), 458 - offset, aboutclip)
        informationrow(
            'graphics', graphicsdrivertext(), 500 - offset, aboutclip)
        informationrow('audio', audiodrivertext(), 542 - offset, aboutclip)
        informationrow(
            'network', networkdrivertext(), 584 - offset, aboutclip)
        fillclipped(
            [205, 622 - offset, max(0, WINW - 233), 1],
            COLOURDIVIDER, aboutclip)
        drawtext(
            205, 646 - offset, 'operating system',
            COLOURTEXT, 19, aboutclip)
        drawtext(205, 694 - offset, 'The One OS', COLOURTEXT, 26, aboutclip)
        informationrow(
            'version', operatingsystemversion(), 746 - offset, aboutclip)
        drawtext(
            WINW - 28 - textwidth(ABOUTFOOTER, 11), 746 - offset,
            ABOUTFOOTER, COLOURMUTED, 11, aboutclip)

    if CONTROLS.get('save'):
        button(CONTROLS['save'], 'apply', focused=EDITFIELD is None)
    if statusvisible():
        drawtext(205, WINH - 50, STATUS, COLOURERROR if STATUSERROR else COLOURTEXT, 13)
    paintdropdown()
    if managed:
        commands = GRAPHICSCOMMANDS
        GRAPHICSCOMMANDS = None
        if (
            not commands or commands[0].get('kind') != 'rectangle' or
            commands[0].get('rect') != [0, 0, int(PIXELW), int(PIXELH)]
        ):
            raise RuntimeError('Settings managed scene has no complete background')
        gfx.managedmarkdamage(
            GRAPHICSSTATE, [0, 0, int(PIXELW), int(PIXELH)],
            bounds=(int(PIXELW), int(PIXELH)))
        gfx.managedsubmit(
            GRAPHICSSTATE, lambda request: sendws(request) or True,
            WINID, commands)
        return
    gfx.present()
    sendws({'op': 'DAMAGE', 'winid': WINID, 'rect': [0, 0, PIXELW, PIXELH]})


def windowname():
    if SECTION == 'display' and DISPLAYPAGE != 'main':
        return 'night light'
    return SECTION


def windowcurrent():
    global LASTWINDOWNAME
    current = windowname()
    if WINID is None or current == LASTWINDOWNAME:
        return
    LASTWINDOWNAME = current
    sendws({
        'op': 'WINDOW_CURRENT_SET',
        'winid': WINID,
        'current': current,
    })


def redraw():
    global NEEDREDRAW
    NEEDREDRAW = True
    windowcurrent()


def editsave():
    global EDITFIELD, EDITBUFFER, CLOCKEDITED, TERMINALNAME, PYTHONQUERY
    if not EDITFIELD:
        return
    if SECTION == 'display' and EDITFIELD in (
        'night_light_day_time', 'night_light_evening_time',
        'night_light_bedtime_time',
    ):
        defaults = {
            'night_light_day_time': '06:00',
            'night_light_evening_time': '18:00',
            'night_light_bedtime_time': '22:00',
        }
        DISPLAY[EDITFIELD] = clockvalue(EDITBUFFER, defaults[EDITFIELD])
    elif SECTION == 'network' and EDITFIELD == 'network_name':
        key = ethernetconnectionkey(preferrednetworkinterface())
        value = networkdisplayname(EDITBUFFER)[:64]
        if key:
            if value:
                ETHERNETNAMES[key] = value
            else:
                ETHERNETNAMES.pop(key, None)
    elif SECTION == 'network' and EDITFIELD in NETWORK:
        NETWORK[EDITFIELD] = EDITBUFFER.strip()
    elif SECTION == 'network' and EDITFIELD == 'passphrase':
        WIRELESS['passphrase'] = EDITBUFFER
    elif SECTION == 'time & date' and EDITFIELD in TIME:
        if EDITFIELD in ('date', 'time') and str(TIME.get(EDITFIELD, '')) != EDITBUFFER.strip():
            CLOCKEDITED = True
        TIME[EDITFIELD] = EDITBUFFER.strip()
    elif SECTION == 'master' and EDITFIELD == 'master_name':
        MASTER['name'] = EDITBUFFER.strip()
    elif SECTION == 'master' and EDITFIELD in (
        'current_password', 'new_password', 'confirm_password',
    ):
        MASTER[EDITFIELD] = EDITBUFFER
    elif SECTION == 'about' and EDITFIELD == 'terminal_name':
        TERMINALNAME = EDITBUFFER.strip()
    elif SECTION == 'python' and EDITFIELD == 'python_query':
        PYTHONQUERY = EDITBUFFER.strip()
    EDITFIELD = None
    EDITBUFFER = ''
    redraw()


def startedit(name, value):
    global EDITFIELD, EDITBUFFER
    editsave()
    EDITFIELD = name
    EDITBUFFER = str(value)
    redraw()


def sliderchange(name, x, rect):
    amount = clamp((float(x) - rect[0]) / float(max(1, rect[2])), 0.0, 1.0)
    if name == 'volume':
        AUDIO['mastergain'] = amount
    elif name == 'cursor_speed':
        MOUSE['cursor_speed'] = (25.0 + amount * 175.0) / 100.0
    elif name == 'cursor_size':
        MOUSE['cursor_size'] = int(round(
            CURSORSIZEMIN + amount * (CURSORSIZEMAX - CURSORSIZEMIN)))
    elif name in ('brightness', 'contrast', 'saturation'):
        DISPLAYDRAFT[name] = int(round(amount * 200.0))
    elif name in (
        'night_light_manual_temperature',
        'night_light_day_temperature',
        'night_light_sunset_temperature',
        'night_light_bedtime_temperature',
    ):
        DISPLAY[name] = int(round((1000.0 + amount * 5500.0) / 100.0) * 100)
    elif name == 'night_light_transition_minutes':
        DISPLAY[name] = int(round(1.0 + amount * 29.0))
    else:
        DISPLAY[name] = int(round(amount * 200.0))
    redraw()


def handlebutton(message):
    global SECTION, DRAGGING, RESOLUTIONEDITED, DISPLAYPAGE
    global MASTERNAMEEDITING, ABOUTSCROLL, PYTHONSCROLL
    global PYTHONSELECTED
    if message.get('button', 1) not in (1, '1', 'left', 'LEFT'):
        return
    x = logicalcoordinate(message.get('x', 0))
    y = logicalcoordinate(message.get('y', 0))
    down = str(message.get('state', 'down')).lower() == 'down'
    if not down:
        DRAGGING = None
        return
    if DROPDOWN:
        opened = dropdownpopup()
        index = dropdownoptionat(x, y)
        if opened and index is not None:
            control = opened[0]
            if 0 <= index < len(control['options']):
                dropdownselect(DROPDOWN.get('name'), control['options'][index]['value'])
                return
        closedropdown()
        return
    for section, rect in CONTROLS.get('nav', {}).items():
        if pointin(x, y, rect):
            editsave()
            if SECTION == 'master' and section != 'master':
                clearmasterpasswords()
                MASTER['name'] = str(MASTER.get('original_name') or '')
                MASTERNAMEEDITING = False
            if SECTION == 'recovery' and section != 'recovery':
                RECOVERY['action'] = ''
            SECTION = section
            DISPLAYPAGE = 'main'
            if section == 'about':
                ABOUTSCROLL = 0
            if section == 'python':
                PYTHONSCROLL = 0
                startpythonrequest('refresh')
            if section == 'network' and wirelessinterfaces() and not WIRELESSNETWORKS:
                requestwirelessscan()
            redraw()
            writevmteststatus(
                'navigation', pointer_x=x, pointer_y=y,
                target=section)
            return
    rows = CONTROLS.get('rows', {})
    if pointin(x, y, CONTROLS.get('save')):
        applysection()
        return
    if SECTION == 'display':
        if DISPLAYPAGE == 'main':
            if pointin(x, y, CONTROLS.get('dropdowns', {}).get('resolution', {}).get('rect')):
                opendropdown('resolution')
                return
            if pointin(x, y, CONTROLS.get('dropdowns', {}).get('ui_scale', {}).get('rect')):
                opendropdown('ui_scale')
                return
            if pointin(x, y, rows.get('night_light')):
                DISPLAYPAGE = 'night_light'
                redraw()
                return
            for name in ('brightness', 'contrast', 'saturation'):
                if pointin(x, y, rows.get(name)):
                    DRAGGING = name
                    sliderchange(name, x, rows[name])
                    return
        elif DISPLAYPAGE == 'night_light':
            if pointin(x, y, rows.get('back')):
                DISPLAYPAGE = 'main'
                redraw()
                return
            if pointin(x, y, rows.get('night_light_enabled')):
                DISPLAY['night_light_enabled'] = not DISPLAY.get('night_light_enabled')
                redraw()
                return
            if pointin(
                x, y,
                CONTROLS.get('dropdowns', {}).get(
                    'night_light_mode', {}).get('rect')
            ):
                opendropdown('night_light_mode')
                return
            if pointin(x, y, rows.get('night_light_preview')):
                DISPLAY['night_light_preview'] = True
                savedisplay()
                DISPLAY['night_light_preview'] = False
                setstatus('Previewing a full day for 15 seconds.', section='display')
                return
            for name in (
                'night_light_manual_temperature',
                'night_light_day_temperature',
                'night_light_sunset_temperature',
                'night_light_bedtime_temperature',
            ):
                if pointin(x, y, rows.get(name)):
                    DRAGGING = name
                    sliderchange(name, x, rows[name])
                    return
            if pointin(x, y, rows.get('night_light_transition_minutes')):
                DRAGGING = 'night_light_transition_minutes'
                sliderchange(DRAGGING, x, rows[DRAGGING])
                return
            for name in (
                'night_light_day_time', 'night_light_evening_time',
                'night_light_bedtime_time',
            ):
                if pointin(x, y, rows.get(name)):
                    startedit(name, DISPLAY.get(name, ''))
                    return
    elif SECTION == 'audio':
        if pointin(x, y, rows.get('volume')):
            DRAGGING = 'volume'
            sliderchange('volume', x, rows['volume'])
        elif pointin(x, y, rows.get('mute')):
            AUDIO['mastermute'] = not AUDIO.get('mastermute')
            redraw()
        elif pointin(x, y, rows.get('autodevice')):
            AUDIO['autodevice'] = not AUDIO.get('autodevice')
            redraw()
        elif pointin(x, y, CONTROLS.get('dropdowns', {}).get('device', {}).get('rect')):
            opendropdown('device')
        elif pointin(x, y, rows.get('refresh')):
            refreshaudio()
    elif SECTION == 'mouse':
        if pointin(x, y, rows.get('cursor_speed')):
            DRAGGING = 'cursor_speed'
            sliderchange('cursor_speed', x, rows['cursor_speed'])
        elif pointin(x, y, rows.get('cursor_size')):
            DRAGGING = 'cursor_size'
            sliderchange('cursor_size', x, rows['cursor_size'])
    elif SECTION == 'network':
        if pointin(x, y, CONTROLS.get('dropdowns', {}).get('interface', {}).get('rect')):
            opendropdown('interface')
        elif pointin(x, y, CONTROLS.get('dropdowns', {}).get('wifi_network', {}).get('rect')):
            opendropdown('wifi_network')
        elif pointin(x, y, CONTROLS.get('dropdowns', {}).get('security', {}).get('rect')):
            opendropdown('security')
        elif pointin(x, y, rows.get('scan')):
            requestwirelessscan()
        elif (
            pointin(x, y, rows.get('passphrase')) and
            str(WIRELESS.get('security') or '').lower() != 'open'
        ):
            startedit('passphrase', WIRELESS.get('passphrase', ''))
        elif (
            pointin(x, y, rows.get('network_name')) and
            ethernetconnectionkey(preferrednetworkinterface()) and
            not ethernetdhcpname(preferrednetworkinterface())
        ):
            startedit('network_name', ethernetcustomname(preferrednetworkinterface()))
        elif pointin(x, y, rows.get('dhcp')):
            NETWORK['dhcp'] = not NETWORK.get('dhcp')
            redraw()
        else:
            for name in EDITABLE['network']:
                if pointin(x, y, rows.get(name)) and (name in ('dns1', 'dns2') or not NETWORK.get('dhcp')):
                    startedit(name, NETWORK.get(name, ''))
                    return
    elif SECTION == 'time & date':
        if pointin(x, y, CONTROLS.get('dropdowns', {}).get('timezone', {}).get('rect')):
            opendropdown('timezone')
            return
        for name in EDITABLE['time & date']:
            if pointin(x, y, rows.get(name)):
                startedit(name, TIME.get(name, ''))
                return
        if pointin(x, y, rows.get('internet')):
            TIME['internet'] = not TIME.get('internet')
            redraw()
        elif pointin(x, y, rows.get('virtualbox')):
            TIME['virtualbox'] = not TIME.get('virtualbox')
            redraw()
    elif SECTION == 'master':
        if MASTERNAMEEDITING:
            if pointin(x, y, rows.get('master_name_cancel')):
                cancelmasternamechange()
                return
            if pointin(x, y, rows.get('master_name_confirm')):
                confirmmasternamechange()
                return
            for name in ('master_name',):
                if pointin(x, y, rows.get(name)):
                    startedit(name, MASTER.get(name, ''))
                    return
            return
        if pointin(x, y, rows.get('master_name_change')):
            startmasternamechange()
            return
        if pointin(x, y, rows.get('use_master_image')):
            MASTER['use_master_image'] = not MASTER.get('use_master_image')
            redraw()
            return
        if (
            MASTER.get('use_master_image') and
            (
                pointin(x, y, rows.get('master_image_path')) or
                pointin(x, y, rows.get('master_image_choose'))
            )
        ):
            startmasterimagepicker()
            return
        for name in ('new_password', 'confirm_password'):
            if pointin(x, y, rows.get(name)):
                startedit(name, MASTER.get(name, ''))
                return
    elif SECTION == 'recovery':
        if RECOVERY.get('action'):
            if pointin(x, y, rows.get('recovery_cancel')):
                cancelrecovery()
                return
            if pointin(x, y, rows.get('recovery_confirm')):
                applysection()
                return
        else:
            for action in ('python', 'build', 'reset', 'reinstall'):
                if pointin(x, y, rows.get('recovery_' + action)):
                    selectrecovery(action)
                    return
    elif SECTION == 'python':
        busy = bool(PYTHONWORK is not None and PYTHONWORK.is_alive())
        if pointin(x, y, rows.get('python_refresh')):
            startpythonrequest('refresh')
            return
        if pointin(x, y, rows.get('python_check')):
            startpythonrequest('check_modules', timeout=120.0)
            return
        if pointin(x, y, rows.get('python_query')) and not busy:
            startedit('python_query', PYTHONQUERY)
            return
        if pointin(x, y, rows.get('python_add')) and not busy:
            editsave()
            query = PYTHONQUERY.strip()
            if not query:
                setstatus('Enter a Python module name.', True, section='python')
                return
            queuepythonchange(
                'install_module', {'name': query},
                'Install {} and its required dependencies?'.format(query))
            return
        if pointin(x, y, rows.get('python_cancel')):
            cancelpythonchange()
            return
        if pointin(x, y, rows.get('python_confirm')):
            confirmpythonchange()
            return
        selected = selectedpythonmodule()
        if selected and not selected.get('system') and selected.get('requested'):
            name = str(selected.get('name') or '')
            label = str(selected.get('display_name') or name)
            if pointin(x, y, rows.get('python_remove')):
                queuepythonchange(
                    'remove_module', {'name': name},
                    'Remove {} and dependencies no longer needed?'.format(label))
                return
            if pointin(x, y, rows.get('python_update')):
                queuepythonchange(
                    'update_module', {'name': name},
                    'Update {} to the latest compatible version?'.format(label))
                return
            if pointin(x, y, rows.get('python_pin')):
                operation = 'unpin_module' if selected.get('pinned') else 'pin_module'
                queuepythonchange(
                    operation, {'name': name},
                    '{} {} at version {}?'.format(
                        'Unpin' if selected.get('pinned') else 'Pin',
                        label, selected.get('version') or 'current'))
                return
        for index, item in enumerate(pythonmoduleview()):
            if pointin(x, y, rows.get('python_module_' + str(index))):
                PYTHONSELECTED = str(item.get('name') or '')
                redraw()
                return
    elif SECTION == 'about':
        if pointin(x, y, rows.get('terminal_name')):
            startedit('terminal_name', TERMINALNAME)


def handlemotion(message):
    global DROPDOWNHOVER
    x = logicalcoordinate(message.get('x', 0))
    y = logicalcoordinate(message.get('y', 0))
    setpointercursor('text' if textcursorhit(x, y) else 'arrow')
    if DROPDOWN:
        hovered = dropdownoptionat(x, y)
        if hovered != DROPDOWNHOVER:
            DROPDOWNHOVER = hovered
            redraw()
        return
    if not DRAGGING:
        return
    rect = CONTROLS.get('rows', {}).get(DRAGGING)
    if rect:
        sliderchange(DRAGGING, x, rect)


def handlescroll(message):
    global ABOUTSCROLL, PYTHONSCROLL
    if not DROPDOWN:
        if SECTION == 'about':
            delta = int(message.get('dy', 0))
            if delta:
                previous = ABOUTSCROLL
                ABOUTSCROLL = int(clamp(
                    ABOUTSCROLL + (-44 if delta > 0 else 44),
                    0,
                    aboutscrollmaximum()))
                if ABOUTSCROLL != previous:
                    redraw()
        elif SECTION == 'python':
            delta = int(message.get('dy', 0))
            if delta:
                previous = PYTHONSCROLL
                PYTHONSCROLL = int(clamp(
                    PYTHONSCROLL + (-44 if delta > 0 else 44),
                    0,
                    pythonscrollmaximum()))
                if PYTHONSCROLL != previous:
                    redraw()
        return
    opened = dropdownpopup()
    if not opened:
        return
    control, popup, visible = opened
    maximum = max(0, len(control['options']) - visible)
    delta = int(message.get('dy', 0))
    if delta:
        DROPDOWN['offset'] = max(
            0, min(maximum, int(DROPDOWN.get('offset', 0)) + (-1 if delta > 0 else 1)))
        redraw()


def handlekey(message):
    global EDITFIELD, EDITBUFFER, RUNNING, DROPDOWNHOVER, DISPLAYPAGE
    if str(message.get('state', 'down')).lower() not in ('down', 'repeat'):
        return
    key = str(message.get('key', '')).upper()
    if key in ('ESC', 'ESCAPE'):
        if closedropdown():
            return
        if SECTION == 'master' and MASTERNAMEEDITING:
            cancelmasternamechange()
            return
        if SECTION == 'recovery' and RECOVERY.get('action'):
            cancelrecovery()
            return
        if SECTION == 'display' and DISPLAYPAGE != 'main' and not EDITFIELD:
            DISPLAYPAGE = 'main'
            redraw()
            return
        EDITFIELD = None
        EDITBUFFER = ''
        redraw()
    elif DROPDOWN:
        opened = dropdownpopup()
        if not opened:
            closedropdown()
            return
        control, popup, visible = opened
        count = len(control['options'])
        current = DROPDOWNHOVER
        if current is None:
            current = next((
                index for index, option in enumerate(control['options'])
                if option['value'] == control['value']), 0)
        if key in ('UP', 'ARROWUP'):
            DROPDOWNHOVER = max(0, int(current) - 1)
        elif key in ('DOWN', 'ARROWDOWN'):
            DROPDOWNHOVER = min(count - 1, int(current) + 1)
        elif key == 'HOME':
            DROPDOWNHOVER = 0
        elif key == 'END':
            DROPDOWNHOVER = count - 1
        elif key in ('ENTER', 'RETURN', 'SPACE'):
            dropdownselect(
                DROPDOWN.get('name'),
                control['options'][max(0, min(count - 1, int(current)))]['value'])
            return
        else:
            return
        offset = int(DROPDOWN.get('offset', 0))
        if DROPDOWNHOVER < offset:
            DROPDOWN['offset'] = DROPDOWNHOVER
        elif DROPDOWNHOVER >= offset + visible:
            DROPDOWN['offset'] = DROPDOWNHOVER - visible + 1
        redraw()
    elif EDITFIELD and key in ('ENTER', 'RETURN', 'TAB'):
        editsave()
    elif EDITFIELD and key == 'BACKSPACE':
        EDITBUFFER = EDITBUFFER[:-1]
        redraw()
    elif not EDITFIELD and key in ('ENTER', 'RETURN'):
        if SECTION == 'master' and MASTERNAMEEDITING:
            confirmmasternamechange()
        else:
            applysection()


def handletext(message):
    global EDITBUFFER, DROPDOWNHOVER, DROPDOWNSEARCH, DROPDOWNSEARCHAT
    if not HASFOCUS:
        return
    textvalue = ''.join(character for character in str(message.get('text', '')) if character.isprintable())
    if DROPDOWN and textvalue:
        opened = dropdownpopup()
        if not opened:
            return
        control, popup, visible = opened
        now = time.monotonic()
        if now - DROPDOWNSEARCHAT > 0.9:
            DROPDOWNSEARCH = ''
        DROPDOWNSEARCH = (DROPDOWNSEARCH + textvalue).casefold()
        DROPDOWNSEARCHAT = now
        match = next((
            index for index, option in enumerate(control['options'])
            if option['label'].casefold().startswith(DROPDOWNSEARCH)), None)
        if match is None:
            match = next((
                index for index, option in enumerate(control['options'])
                if DROPDOWNSEARCH in option['label'].casefold()), None)
        if match is not None:
            DROPDOWNHOVER = match
            maximum = max(0, len(control['options']) - visible)
            DROPDOWN['offset'] = max(0, min(maximum, match - visible // 2))
            redraw()
        return
    if not EDITFIELD:
        return
    if textvalue and len(EDITBUFFER) < 64:
        EDITBUFFER += textvalue[:64 - len(EDITBUFFER)]
        redraw()


def sendws(message):
    OUTBUF.extend(json.dumps(message, separators=(',', ':')).encode('utf-8') + b'\n')


def setpointercursor(mode):
    global POINTERCURSORMODE
    mode = str(mode or 'arrow')
    if mode == POINTERCURSORMODE or WINID is None:
        return
    POINTERCURSORMODE = mode
    sendws({
        'op': 'CURSOR_MODE_SET',
        'winid': int(WINID),
        'mode': mode,
    })


def startmasterimagepicker():
    global PICKER_PENDING
    if PICKER_PENDING is not None:
        return True
    if PICKER_VERSION < 1 or WINID is None:
        setstatus(
            'The Array image picker is unavailable.',
            True, section='master')
        return False

    selected = str(MASTER.get('image_path') or '').strip()
    initial = os.path.dirname(os.path.abspath(selected)) if selected else ''
    if not os.path.isdir(initial):
        try:
            initial = masterhomepath(MASTER.get('original_name') or MASTER.get('name'))
        except Exception:
            initial = MASTERHOMEBASE
    if not os.path.isdir(initial):
        initial = '/'

    PICKER_PENDING = {'kind': 'master_image', 'request_id': None}
    sendws({
        'op': 'CREATE_PICKER',
        'parent': int(WINID),
        'mode': 'open_file',
        'title': 'choose master image',
        'initial_path': initial,
        'allow_multiple': False,
        'filters': [{
            'id': 'images',
            'label': 'images',
            'extensions': [
                '.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif',
            ],
        }],
    })
    setstatus('Opening Array…', section='master')
    redraw()
    return True


def handlepickerresult(message):
    global PICKER_PENDING
    if PICKER_PENDING is None:
        return False
    requestid = str(message.get('request_id', ''))
    expected = PICKER_PENDING.get('request_id')
    if expected and requestid != str(expected):
        return False
    PICKER_PENDING = None
    paths = message.get('paths', [])
    if (
        str(message.get('status', 'cancelled')) != 'accepted' or
        not isinstance(paths, list) or not paths
    ):
        setstatus('Image selection cancelled.', section='master')
        redraw()
        return True
    try:
        MASTER['image_path'] = validatemasterimagepath(paths[0], required=True)
        setstatus(
            'Master image selected. Apply to update the taskbar and lock screen.',
            section='master')
    except Exception as error:
        setstatus(str(error), True, section='master')
    redraw()
    return True


def flushws():
    if not SOCK or not OUTBUF:
        return
    try:
        sent = SOCK.send(OUTBUF)
        del OUTBUF[:sent]
    except (BlockingIOError, InterruptedError):
        pass


def recvws():
    global INBUF, RUNNING
    try:
        data = SOCK.recv(65536)
    except (BlockingIOError, InterruptedError):
        return []
    if not data:
        RUNNING = False
        return []
    INBUF += data
    messages = []
    while b'\n' in INBUF:
        line, INBUF = INBUF.split(b'\n', 1)
        if line.strip():
            messages.append(json.loads(line.decode('utf-8')))
    return messages


def closebuffer():
    if not gfx:
        return
    for name in ('_FILE_MAP', '_map'):
        target = getattr(gfx, name, None)
        if target:
            try:
                target.close()
            except Exception:
                pass
            setattr(gfx, name, None)
    for name in ('_FILE_FD', '_fd'):
        descriptor = getattr(gfx, name, None)
        if descriptor:
            try:
                os.close(descriptor)
            except Exception:
                pass
            setattr(gfx, name, None)


def bindbuffer(path, width, height):
    global BUFFER, WINW, WINH, PIXELW, PIXELH
    closebuffer()
    BUFFER = path
    PIXELW, PIXELH = max(1, int(width)), max(1, int(height))
    WINW = max(1, int(round(PIXELW / max(0.01, UISCALE))))
    WINH = max(1, int(round(PIXELH / max(0.01, UISCALE))))
    if not GRAPHICSSTRICT:
        gfx.initbuffer(BUFFER, PIXELW, PIXELH)
    gfx.initttffont(FONT, scalepixel(15, 1))
    redraw()


def handlews(message):
    global WINID, SCREENW, SCREENH, GRAPHICSBACKEND, GRAPHICSCONNECTOR
    global NEEDWINDOW, RUNNING, HASFOCUS, PICKER_VERSION, PICKER_PENDING
    global PASSWORDPROMPT, RESIZETARGET
    operation = str(message.get('op', ''))
    if operation in ('WELCOME', 'FB_SIZE'):
        framebuffer = message if operation == 'FB_SIZE' else message.get('fb', {})
        SCREENW = int(framebuffer.get('w', SCREENW))
        SCREENH = int(framebuffer.get('h', SCREENH))
        syncliveresolution(SCREENW, SCREENH)
        scalechanged = applyuiscale()
        if operation == 'WELCOME':
            graphicsstate = message.get('graphics', {})
            configuregraphics(graphicsstate)
            GRAPHICSBACKEND = str(graphicsstate.get('backend', GRAPHICSBACKEND)).lower()
            try:
                GRAPHICSCONNECTOR = int(graphicsstate.get('connector') or 0)
            except (TypeError, ValueError):
                GRAPHICSCONNECTOR = 0
            try:
                PICKER_VERSION = int(
                    message.get('pickers', {}).get('version', 0))
            except (TypeError, ValueError):
                PICKER_VERSION = 0
        if NEEDWINDOW:
            NEEDWINDOW = False
            targetwidth, targetheight = windowpixelsize()
            sendws({'op': 'CREATE_WINDOW', 'role': 'window', 'title': APPNAME,
                    'current': windowname(), 'path': APPPATH,
                    'w': targetwidth, 'h': targetheight,
                    'x': scalepixel(140), 'y': scalepixel(90), 'pid': os.getpid()})
        elif scalechanged and WINID is not None:
            targetwidth, targetheight = windowpixelsize()
            RESIZETARGET = (targetwidth, targetheight)
            sendws({'op': 'RESIZE', 'winid': WINID,
                    'w': targetwidth, 'h': targetheight})
        redraw()
    elif operation == 'WINDOW_CREATED':
        WINID = int(message.get('winid'))
        RESIZETARGET = None
        bindbuffer(message.get('buffer'), message.get('w', PIXELW), message.get('h', PIXELH))
        paint()
        sendws({'op': 'MAP', 'winid': WINID})
        sendws({'op': 'RAISE', 'winid': WINID})
        sendws({'op': 'FOCUS_SET', 'winid': WINID})
    elif operation == 'RESIZED':
        resizedwidth = max(1, int(message.get('w', PIXELW)))
        resizedheight = max(1, int(message.get('h', PIXELH)))
        bindbuffer(message.get('buffer', BUFFER), resizedwidth, resizedheight)
        if RESIZETARGET is not None:
            if (resizedwidth, resizedheight) == tuple(RESIZETARGET):
                RESIZETARGET = None
            else:
                targetwidth, targetheight = RESIZETARGET
                sendws({
                    'op': 'RESIZE', 'winid': WINID,
                    'w': int(targetwidth), 'h': int(targetheight),
                })
        redraw()
    elif operation in ('GRAPHICS_COMMITTED', 'GRAPHICS_CLEARED') or (
            operation == 'ERROR' and
            str(message.get('code', '')).startswith('graphics_')):
        if GRAPHICSSTATE is not None:
            gfx.managedresponse(GRAPHICSSTATE, message)
            writevmteststatus(
                'graphics-response', operation=operation,
                generation=int(message.get('generation', 0) or 0),
                presented=message.get('presented'))
            if GRAPHICSSTATE.get('need_submit'):
                redraw()
    elif operation == 'FOCUS':
        HASFOCUS = str(message.get('state', 'in')).lower() in ('in', 'focused', 'focus', '1', 'true')
        redraw()
    elif operation == 'POINTER_BUTTON':
        handlebutton(message)
    elif operation == 'POINTER_MOTION':
        handlemotion(message)
    elif operation == 'SCROLL':
        handlescroll(message)
    elif operation == 'KEY':
        handlekey(message)
    elif operation == 'TEXT':
        handletext(message)
    elif operation == 'DAMAGE':
        redraw()
    elif operation == 'DIALOG_CREATED':
        if (
            PASSWORDPROMPT is not None and
            str(message.get('dialog_id', '')) ==
            str(PASSWORDPROMPT.get('dialog_id', ''))
        ):
            PASSWORDPROMPT['winid'] = message.get('winid')
    elif operation == 'DIALOG_RESULT':
        handlepasswordpromptresult(message)
    elif operation == 'PICKER_CREATED':
        if PICKER_PENDING is not None:
            PICKER_PENDING['request_id'] = str(
                message.get('request_id', ''))
            setstatus('Select an image in Array.', section='master')
            redraw()
    elif operation == 'PICKER_RESULT':
        handlepickerresult(message)
    elif operation == 'DISPLAY_SETTINGS_SET':
        if virtualboxcontrolsresolution():
            setstatus(
                'Display settings applied. Resolution remains controlled by VirtualBox Guest Additions.',
                section='display')
        elif GRAPHICSBACKEND == 'framebuffer':
            setstatus(
                'Display settings applied. Resolution is set by the framebuffer.',
                section='display')
        else:
            setstatus(
                'Image settings applied. Resolution takes effect after restarting the graphics service.',
                section='display')
    elif operation == 'MOUSE_SETTINGS_SET':
        setstatus('Mouse settings applied.', section='mouse')
    elif operation == 'ERROR' and str(message.get('code', '')).startswith('display_settings'):
        setstatus(
            str(message.get('detail', 'Display settings could not be applied.')),
            True, section='display')
    elif operation == 'ERROR' and str(message.get('code', '')).startswith('mouse_settings'):
        setstatus(
            str(message.get('detail', 'Mouse settings could not be applied.')),
            True, section='mouse')
    elif operation == 'ERROR' and str(message.get('code', '')).startswith('picker_'):
        PICKER_PENDING = None
        setstatus(
            str(message.get('detail', 'The Array image picker is unavailable.')),
            True, section='master')
        redraw()
    elif operation == 'ERROR' and PASSWORDPROMPT is not None and (
        str(message.get('dialog_id', '')) ==
        str(PASSWORDPROMPT.get('dialog_id', '')) or
        str(message.get('code', '')).startswith('dialog_') or
        (
            str(message.get('code', '')) == 'unknown_op' and
            str(message.get('detail', '')) == 'CREATE_PASSWORD_PROMPT'
        )
    ):
        section = str(PASSWORDPROMPT.get('section', SECTION))
        PASSWORDPROMPT = None
        setstatus(
            'The window server password prompt is unavailable.',
            True, section=section)
        redraw()
    elif operation == 'CLOSE':
        RUNNING = False
        sendws({'op': 'CLOSE_ACK', 'pid': os.getpid()})
    elif operation == 'WINDOW_DESTROYED':
        try:
            destroyed = int(message.get('winid'))
        except (TypeError, ValueError):
            destroyed = None
        if destroyed == WINID:
            RUNNING = False
        elif (
            PASSWORDPROMPT is not None and
            destroyed == PASSWORDPROMPT.get('winid')
        ):
            section = str(PASSWORDPROMPT.get('section', SECTION))
            PASSWORDPROMPT = None
            setstatus('Password entry cancelled.', section=section)


def connectwindowserver():
    global SOCK
    SOCK = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    SOCK.connect(WINDOWSOCK)
    SOCK.setblocking(False)
    SELECTOR.register(SOCK, selectors.EVENT_READ | selectors.EVENT_WRITE)
    sendws({'op': 'HELLO'})
    sendws({'op': 'SUBSCRIBE', 'types': ['fbsize']})


def terminate(signum=None, frame=None):
    global RUNNING
    RUNNING = False


def cleanup():
    closebuffer()
    if SOCK:
        try:
            SELECTOR.unregister(SOCK)
        except Exception:
            pass
        try:
            SOCK.close()
        except Exception:
            pass


def main():
    global LASTNETWORKPOLL
    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)
    loadstate()
    loadgraphics()
    refreshaudio(quiet=True)
    connectwindowserver()
    try:
        while RUNNING:
            pollpythonrequest()
            if SECTION == 'time & date' and refreshclock():
                redraw()
            elif SECTION == 'network':
                now = time.monotonic()
                interfaceschanged = False
                if now - LASTNETWORKPOLL >= 0.5:
                    LASTNETWORKPOLL = now
                    interfaceschanged = refreshnetworkinterfaces()
                if interfaceschanged or refreshwirelessnetworks() or refreshnetworkruntime():
                    redraw()
            elif (
                SECTION == 'python' and
                not (PYTHONWORK is not None and PYTHONWORK.is_alive()) and
                time.monotonic() - PYTHONLASTREFRESH >= 10.0
            ):
                startpythonrequest('refresh')
            for key, mask in SELECTOR.select(timeout=0.03):
                if key.fileobj is SOCK and mask & selectors.EVENT_READ:
                    for message in recvws():
                        handlews(message)
                if key.fileobj is SOCK and mask & selectors.EVENT_WRITE:
                    flushws()
            paint()
            flushws()
    finally:
        cleanup()
    return 0


def diagnostic():
    global SYSTEMROOT, DISPLAYFILE, AUDIOFILE, MOUSEFILE, NETWORKDIR, NETWORKFILE, DNSFILE, ETHERNETNAMESFILE, NETWORKSTATE, WIRELESSFILE, WIRELESSSCANSTATE, WIRELESSSCANREQUEST, NETWORKRECONFIGURE, INTERNETTIMEFILE, VIRTUALBOXTIMEFILE, TIMEZONEFILE, TERMINALNAMEFILE, MASTERSETTINGSFILE, MASTERHOMEBASE, ZONEINFODIR, DRMSTATE, NETSTATE, TERMINALNAME, MASTER
    global architect_authorize, architect_revoke, service_secret_delete, service_secret_exists, service_secret_put, settings_account_get, settings_hostname_set, settings_master_update, settings_recovery_authorize, settings_time_set
    global UISCALE, WINW, WINH, SECTION, DISPLAYPAGE, CONTROLS
    if os.name == 'nt':
        result = {
            'passed': False,
            'checks': {},
            'errors': [
                'The Settings diagnostic is POSIX-only and will not create '
                'T1OS test state on Windows.'
            ],
        }
        print(json.dumps(result, sort_keys=True, separators=(',', ':')))
        return 1
    original = (SYSTEMROOT, DISPLAYFILE, AUDIOFILE, MOUSEFILE, NETWORKDIR, NETWORKFILE, DNSFILE, ETHERNETNAMESFILE, NETWORKSTATE, WIRELESSFILE, WIRELESSSCANSTATE, WIRELESSSCANREQUEST, NETWORKRECONFIGURE, INTERNETTIMEFILE, VIRTUALBOXTIMEFILE, TIMEZONEFILE, TERMINALNAMEFILE, MASTERSETTINGSFILE, MASTERHOMEBASE, ZONEINFODIR, DRMSTATE, NETSTATE)
    diagnosticoperationsoriginal = (
        architect_authorize,
        architect_revoke,
        service_secret_delete,
        service_secret_exists,
        service_secret_put,
        settings_account_get,
        settings_hostname_set,
        settings_master_update,
        settings_recovery_authorize,
        settings_time_set,
    )
    diagnosticaccount = {
        'username': 'old-master',
        'password': 'current secret',
    }
    diagnosticsecrets = {}
    diagnosticcalls = {
        'hostname': [],
        'master': [],
        'time': [],
    }

    def diagnosticprivilegedcall(*_arguments, **_keywords):
        raise AssertionError(
            'The Settings diagnostic cannot invoke this privileged operation.')

    def diagnosticaccountget(timeout=3.0):
        del timeout
        return {'username': diagnosticaccount['username']}

    def diagnostichostnameset(name, timeout=3.0):
        del timeout
        name = validateterminalname(name)
        diagnosticcalls['hostname'].append(name)
        atomictext(TERMINALNAMEFILE, name + '\n')
        return {'name': name}

    def diagnosticmasterupdate(
        current_password,
        username,
        new_password='',
        use_master_image=False,
        image_path='',
        timeout=15.0,
    ):
        del timeout
        requestedname = validatemastername(username)
        if str(current_password) != diagnosticaccount['password']:
            raise ValueError('The current password is incorrect.')
        oldname = diagnosticaccount['username']
        returnedimage = str(image_path or '')
        if oldname != requestedname and returnedimage:
            oldhome = os.path.abspath(os.path.join(MASTERHOMEBASE, oldname))
            image = os.path.abspath(returnedimage)
            try:
                if os.path.commonpath((oldhome, image)) == oldhome:
                    returnedimage = os.path.join(
                        MASTERHOMEBASE,
                        requestedname,
                        os.path.relpath(image, oldhome),
                    )
            except ValueError:
                pass
        diagnosticcalls['master'].append({
            'username': requestedname,
            'password_changed': bool(new_password),
            'use_master_image': bool(use_master_image),
            'image_path': str(image_path or ''),
        })
        diagnosticaccount['username'] = requestedname
        if new_password:
            diagnosticaccount['password'] = str(new_password)
        return {
            'username': requestedname,
            'use_master_image': bool(use_master_image),
            'image_path': returnedimage,
        }

    def diagnosticsecretput(reference, value, timeout=3.0):
        del timeout
        diagnosticsecrets[str(reference)] = str(value)
        return {'stored': True}

    def diagnosticsecretdelete(reference, timeout=3.0):
        del timeout
        diagnosticsecrets.pop(str(reference), None)
        return {'deleted': True}

    def diagnosticsecretexists(reference, timeout=3.0):
        del timeout
        return str(reference) in diagnosticsecrets

    def diagnostictimeset(
        timezone,
        internet=False,
        virtualbox=False,
        epoch=None,
        timeout=5.0,
    ):
        del timeout
        diagnosticcalls['time'].append({
            'timezone': str(timezone),
            'internet': bool(internet),
            'virtualbox': bool(virtualbox),
            'manual': epoch is not None,
        })
        atomictext(TIMEZONEFILE, str(timezone).strip() + '\n')
        atomictext(INTERNETTIMEFILE, 'true\n' if internet else 'false\n')
        atomictext(VIRTUALBOXTIMEFILE, 'true\n' if virtualbox else 'false\n')
        return {'motherboard_updated': False}

    (
        architect_authorize,
        architect_revoke,
        service_secret_delete,
        service_secret_exists,
        service_secret_put,
        settings_account_get,
        settings_hostname_set,
        settings_master_update,
        settings_recovery_authorize,
        settings_time_set,
    ) = (
        diagnosticprivilegedcall,
        diagnosticprivilegedcall,
        diagnosticsecretdelete,
        diagnosticsecretexists,
        diagnosticsecretput,
        diagnosticaccountget,
        diagnostichostnameset,
        diagnosticmasterupdate,
        diagnosticprivilegedcall,
        diagnostictimeset,
    )
    result = {'passed': False, 'checks': {}, 'errors': []}
    try:
        with tempfile.TemporaryDirectory(prefix='t1os-settings-') as root:
            SYSTEMROOT = root
            DISPLAYFILE = os.path.join(root, 'settings', 'display', 'settings.json')
            AUDIOFILE = os.path.join(root, 'settings', 'audio', 'audioserver.json')
            MOUSEFILE = os.path.join(root, 'settings', 'mouse', 'settings.json')
            NETWORKDIR = os.path.join(root, 'settings', 'network')
            NETWORKFILE = os.path.join(NETWORKDIR, 'network.txt')
            DNSFILE = os.path.join(NETWORKDIR, 'dns.txt')
            ETHERNETNAMESFILE = os.path.join(NETWORKDIR, 'ethernet-names.json')
            NETWORKSTATE = os.path.join(root, '.ephemeral', 'network', 'connection.json')
            WIRELESSFILE = os.path.join(NETWORKDIR, 'wireless.txt')
            WIRELESSSCANSTATE = os.path.join(root, '.ephemeral', 'network', 'wireless.json')
            WIRELESSSCANREQUEST = os.path.join(root, '.ephemeral', 'network', 'scan.request')
            NETWORKRECONFIGURE = os.path.join(root, '.ephemeral', 'network', 'reconfigure.request')
            INTERNETTIMEFILE = os.path.join(root, 'settings', 'time', 'internet.txt')
            VIRTUALBOXTIMEFILE = os.path.join(root, 'settings', 'time', 'virtualbox.txt')
            TIMEZONEFILE = os.path.join(root, 'settings', 'time', 'timezone.txt')
            TERMINALNAMEFILE = os.path.join(root, 'settings', 'terminal', 'name.txt')
            MASTERSETTINGSFILE = os.path.join(
                root, 'settings', 'master', 'settings.json')
            MASTERHOMEBASE = os.path.join(root, 'master')
            ZONEINFODIR = os.path.join(root, 'software', 'chromium', 'resources', 'zoneinfo')
            DRMSTATE = os.path.join(root, 'drivers', 'state', 'class', 'drm')
            NETSTATE = os.path.join(root, 'drivers', 'state', 'class', 'net')
            processroot = os.path.join(root, 'drivers', 'processes')
            stateroot = os.path.join(root, 'drivers', 'state')
            driverinfostate = os.path.join(root, 'driver-information-state')
            blockroot = os.path.join(stateroot, 'block')
            graphicsstate = os.path.join(root, '.ephemeral', 'windowserver', 'state', 'graphics.json')
            driverruntime = os.path.join(
                root, 'drivers', 'settings', 'runtime.json')
            versionfile = os.path.join(root, 'settings', 't1osversion.txt')
            os.makedirs(os.path.join(MASTERHOMEBASE, 'old-master', 'reference'))
            atomictext(
                os.path.join(processroot, 'cpuinfo'),
                'processor : 0\nmodel name : AMD Ryzen 7 7800X3D 8-Core Processor\n')
            atomictext(os.path.join(processroot, 'meminfo'), 'MemTotal:       47710208 kB\n')
            atomictext(
                os.path.join(processroot, 'sys', 'kernel', 'osrelease'),
                '6.15.4-t1os\n')
            atomicjson(driverruntime, {'kmod_version': '34.2'})
            atomictext(
                os.path.join(driverinfostate, 'module', 'nvidia', 'version'),
                '580.65.06\n')
            atomictext(
                os.path.join(
                    driverinfostate, 'class', 'sound',
                    'card0', 'device', 'uevent'),
                'DRIVER=snd_hda_intel\n')
            atomictext(
                os.path.join(
                    driverinfostate, 'class', 'net',
                    'wlan0', 'device', 'uevent'),
                'DRIVER=iwlwifi\n')
            dmientries = os.path.join(root, 'drivers', 'state', 'firmware', 'dmi', 'entries')
            for index in range(2):
                raw = bytearray(32)
                raw[0] = 17
                raw[1] = 32
                raw[12:14] = (24 * 1024).to_bytes(2, 'little')
                path = os.path.join(dmientries, '17-' + str(index), 'raw')
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, 'wb') as stream:
                    stream.write(raw)
            drive = os.path.join(blockroot, 'nvme0n1')
            atomictext(os.path.join(drive, 'size'), '2147483648\n')
            atomictext(os.path.join(drive, 'device', 'model'), 'Samsung SSD 990 PRO\n')
            partition = os.path.join(blockroot, 'nvme0n1p1')
            atomictext(os.path.join(partition, 'partition'), '1\n')
            atomictext(os.path.join(partition, 'size'), '2147480000\n')
            otherdrive = os.path.join(blockroot, 'sdb')
            atomictext(os.path.join(otherdrive, 'size'), '3907029168\n')
            atomictext(os.path.join(otherdrive, 'device', 'model'), 'WD My Passport\n')
            atomictext(
                os.path.join(processroot, 'mounts'),
                'nvme0n1p1 / ext4 rw,relatime 0 0\n'
                'sdb /the one/storage/backup ext4 rw 0 0\n')
            atomicjson(graphicsstate, {
                'backend': 'opengl',
                'renderer': (
                    'zink Vulkan 1.4(NVIDIA GeForce RTX 4070 SUPER '
                    '(NVIDIA_PROPRIETARY))'),
                'drm_driver': 'nvidia',
                'drm_version': '580.65.06',
                'provider': 'nvidia',
            })
            atomictext(versionfile, '0.29\n')
            result['checks']['about_hardware_information'] = (
                processorname(processroot) == 'AMD Ryzen 7 7800X3D 8-Core Processor'
                and graphicscardname(graphicsstate) == 'NVIDIA GeForce RTX 4070 SUPER'
                and installedmemory(processroot, dmientries) == '48 GB'
                and installedstorage(blockroot, processroot) == 'Samsung SSD 990 PRO — 1 TB')
            result['checks']['about_driver_information'] = (
                platformdrivertext(processroot, driverruntime)
                == (
                    'Linux platform drivers — kernel 6.15.4-t1os '
                    '· module loader 34.2')
                and graphicsdrivertext(
                    graphicsstate, driverinfostate, processroot)
                == 'NVIDIA driver 580.65.06'
                and audiodrivertext(driverinfostate, processroot)
                == 'Linux HDA audio — kernel 6.15.4-t1os'
                and networkdrivertext(driverinfostate, processroot)
                == 'Intel Wi-Fi — kernel 6.15.4-t1os')
            result['checks']['about_driver_scroll_without_scrollbar'] = (
                aboutscrollmaximum() > 0)
            result['checks']['ram_usable_memory_fallback'] = (
                installedmemory(processroot, os.path.join(root, 'no-dmi')) == '48 GB')
            result['checks']['storage_reports_only_system_drive'] = (
                rootblockname(blockroot, processroot) == 'nvme0n1'
                and 'WD My Passport' not in installedstorage(blockroot, processroot))
            result['checks']['graphics_reports_product_only'] = (
                graphicsproductname(
                    'AMD Radeon RX 7800 XT (radeonsi, navi32, LLVM 18.1.8)')
                == 'AMD Radeon RX 7800 XT'
                and graphicsproductname(
                    'NVIDIA GeForce RTX 4070 SUPER (NVK AD104)')
                == 'NVIDIA GeForce RTX 4070 SUPER'
                and graphicsproductname(
                    'zink Vulkan 1.4(NVIDIA GeForce RTX 4070 SUPER (NVK AD104))')
                == 'NVIDIA GeForce RTX 4070 SUPER'
                and graphicsproductname(
                    'SVGA3D; build: RELEASE; LLVM;')
                == 'SVGA3D'
                and graphicsproductname(
                    'GeForce RTX 3080/PCIe/SSE2')
                == 'GeForce RTX 3080'
                and graphicsproductname(
                    'Mesa DRI Intel(R) Arc A770 Graphics (DG2)')
                == 'Intel(R) Arc A770 Graphics'
                and graphicsproductname(
                    'NVIDIA GeForce RTX 4090 (Laptop GPU)')
                == 'NVIDIA GeForce RTX 4090 (Laptop GPU)')
            usbdrive = os.path.join(blockroot, 'sdc')
            usbpartition = os.path.join(usbdrive, 'sdc2')
            atomictext(os.path.join(usbdrive, 'size'), '125045424\n')
            atomictext(os.path.join(usbdrive, 'device', 'vendor'), 'SanDisk\n')
            atomictext(os.path.join(usbdrive, 'device', 'model'), 'Ultra USB 3.0\n')
            atomictext(os.path.join(usbpartition, 'partition'), '2\n')
            atomictext(os.path.join(usbpartition, 'dev'), '8:34\n')
            rootdevice = '/' + 'dev/root'
            atomictext(
                os.path.join(processroot, 'mounts'),
                f'{rootdevice} / ext4 rw,relatime 0 0\n')
            atomictext(
                os.path.join(processroot, 'self', 'mountinfo'),
                f'24 1 8:34 / / rw,relatime - ext4 {rootdevice} rw\n')
            result['checks']['usb_root_storage_from_mount_identity'] = (
                rootblockname(blockroot, processroot) == 'sdc'
                and installedstorage(blockroot, processroot)
                == 'SanDisk Ultra USB 3.0 — 60 GB')
            result['checks']['about_uses_brick_version_source'] = (
                operatingsystemversion(versionfile) == '0.29')
            result['checks']['python_runtime_version'] = (
                pythonversion() ==
                '.'.join(str(part) for part in sys.version_info[:3]))
            modulepath = os.path.join(
                root, 'software', 'python', 'lib',
                f'python{sys.version_info.major}.{sys.version_info.minor}',
                'site-packages', 'example_module-1.2.3.dist-info')
            os.makedirs(modulepath, exist_ok=True)
            atomictext(
                os.path.join(modulepath, 'METADATA'),
                'Metadata-Version: 2.1\nName: example-module\nVersion: 1.2.3\n')
            atomictext(os.path.join(modulepath, 'top_level.txt'), 'example_module\n')
            imagepackage = os.path.join(
                root, 'catalogue', 'image', 'example_image-4.5.dist-info')
            os.makedirs(imagepackage, exist_ok=True)
            atomictext(
                os.path.join(imagepackage, 'METADATA'),
                'Metadata-Version: 2.1\nName: Example-Image\nVersion: 4.5\n')
            atomictext(os.path.join(imagepackage, 'top_level.txt'), 'ExampleImage\n')
            result['checks']['python_installed_modules'] = (
                installedpythonmodules(root) == (
                    ('ExampleImage', '4.5'),
                    ('example_module', '1.2.3')))
            result['checks']['python_module_view_fallback'] = (
                [item['display_name'] for item in pythonmoduleview()]
                == ['ExampleImage', 'example_module']
                and pythonscrollmaximum([{}] * 24) > 0)
            result['checks']['about_footer'] = ABOUTFOOTER == 'slayer'
            loadstate()
            result['checks']['mouse_speed_default_preserves_current'] = (
                DEFAULTMOUSE.get('cursor_speed') == 1.0
                and MOUSE.get('cursor_speed') == 1.0
                and MOUSE.get('cursor_size') is None
                and automaticcursorsize(1080) == 23
                and automaticcursorsize(2160) == 31)
            MOUSE['cursor_speed'] = 1.5
            MOUSE['cursor_size'] = 32
            savemouse(live=False)
            result['checks']['mouse_speed_persistence'] = (
                loadjson(MOUSEFILE, {}).get('cursor_speed') == 1.5
                and loadjson(MOUSEFILE, {}).get('cursor_size') == 32)
            TERMINALNAME = 'studio-terminal'
            saveterminalname(live=False)
            result['checks']['terminal_name_persistence'] = (
                readterminalname() == 'studio-terminal'
                and open(TERMINALNAMEFILE, encoding='utf-8').read().strip()
                == 'studio-terminal'
                and diagnosticcalls['hostname'] == ['studio-terminal'])
            result['checks']['terminal_name_validation'] = False
            try:
                validateterminalname('not a valid terminal name')
            except ValueError:
                result['checks']['terminal_name_validation'] = True
            masterimage = os.path.join(
                MASTERHOMEBASE, 'old-master', 'reference', 'portrait.png')
            atomictext(masterimage, 'diagnostic image\n')
            MASTER.update({
                'use_master_image': True,
                'image_path': masterimage,
            })
            result['checks']['master_profile_requires_password'] = False
            try:
                savemaster()
            except ValueError:
                result['checks']['master_profile_requires_password'] = (
                    not diagnosticcalls['master']
                    and not MASTER.get('current_password'))
            MASTER['current_password'] = 'current secret'
            savemaster()
            result['checks']['master_profile_broker_request'] = (
                len(diagnosticcalls['master']) == 1
                and diagnosticcalls['master'][0] == {
                    'username': 'old-master',
                    'password_changed': False,
                    'use_master_image': True,
                    'image_path': masterimage,
                }
                and MASTER.get('use_master_image') is True
                and MASTER.get('image_path') == masterimage
                and not MASTER.get('current_password'))
            MASTER.update({
                'name': 'new master',
                'current_password': 'wrong secret',
                'new_password': '',
                'confirm_password': '',
            })
            result['checks']['master_wrong_password_rejected'] = False
            try:
                savemaster()
            except ValueError:
                storedname, _, _ = readmasteraccount()
                result['checks']['master_wrong_password_rejected'] = (
                    storedname == 'old-master'
                    and len(diagnosticcalls['master']) == 1
                    and not MASTER.get('current_password'))
            MASTER.update({
                'name': 'old-master',
                'current_password': 'current secret',
                'new_password': 'first new secret',
                'confirm_password': 'different secret',
            })
            result['checks']['master_password_confirmation'] = False
            try:
                savemaster()
            except ValueError:
                storedname, _, _ = readmasteraccount()
                result['checks']['master_password_confirmation'] = (
                    storedname == 'old-master'
                    and diagnosticaccount['password'] == 'current secret'
                    and len(diagnosticcalls['master']) == 1
                    and not MASTER.get('new_password')
                    and not MASTER.get('confirm_password'))
            MASTER.update({
                'name': 'new master',
                'current_password': 'current secret',
                'new_password': 'new secret',
                'confirm_password': 'new secret',
            })
            savemaster()
            storedname, _, _ = readmasteraccount()
            migratedimage = os.path.join(
                MASTERHOMEBASE, 'new master', 'reference', 'portrait.png')
            result['checks']['master_name_and_password_change'] = (
                storedname == 'new master'
                and diagnosticaccount['password'] == 'new secret'
                and len(diagnosticcalls['master']) == 2
                and diagnosticcalls['master'][-1]['username'] == 'new master'
                and diagnosticcalls['master'][-1]['password_changed'] is True
                and MASTER.get('image_path') == migratedimage
                and not any(MASTER.get(field) for field in (
                    'current_password', 'new_password', 'confirm_password')))
            result['checks']['master_name_validation'] = False
            try:
                validatemastername('../escape')
            except ValueError:
                result['checks']['master_name_validation'] = True
            DISPLAY.update({
                'width': 1920,
                'height': 1080,
                'ui_scale': 1.5,
                'brightness': 85,
                'contrast': 105,
                'saturation': 90,
                'night_light_enabled': True,
                'night_light_mode': 'automatic',
                'night_light_manual_temperature': 3600,
                'night_light_day_time': '05:45',
                'night_light_evening_time': '20:30',
                'night_light_bedtime_time': '23:15',
                'night_light_bedtime_temperature': 3200,
                'night_light_transition_minutes': 12,
            })
            savedisplay()
            stored = loadjson(DISPLAYFILE, {})
            result['checks']['display_persistence'] = (
                stored.get('brightness') == 85 and stored.get('width') == 1920 and stored.get('ui_scale') == 1.5)
            result['checks']['ui_scale_below_100_options'] = (
                UISCALEOPTIONS[:6] == (
                    0.5, 0.6, 0.7, 0.8, 0.9, 1.0))
            DISPLAY['ui_scale'] = 0.5
            savedisplay()
            result['checks']['ui_scale_50_persistence'] = (
                loadjson(DISPLAYFILE, {}).get('ui_scale') == 0.5
                and abs(uiscalefor(1920, 1080, 0.5) - 0.5) < 0.001)
            result['checks']['night_light_persistence'] = (
                stored.get('night_light_enabled') is True
                and stored.get('night_light_mode') == 'automatic'
                and stored.get('night_light_manual_temperature') == 3600
                and stored.get('night_light_day_time') == '05:45'
                and stored.get('night_light_evening_time') == '20:30'
                and stored.get('night_light_bedtime_time') == '23:15'
                and stored.get('night_light_bedtime_temperature') == 3200
                and stored.get('night_light_transition_minutes') == 12
                and stored.get('night_light_preview') is False)
            result['checks']['night_light_two_modes'] = (
                DEFAULTDISPLAY.get('night_light_mode') == 'automatic'
                and set(('manual', 'automatic')) == {'manual', 'automatic'}
                and stored.get('night_light_transition_minutes') <= 30
                and 'night_light_latitude' not in stored
                and 'night_light_longitude' not in stored)
            result['checks']['ui_scale_default'] = DEFAULTDISPLAY.get('ui_scale') == 1.0
            result['checks']['settings_uniform_display_scale'] = (
                abs(uiscalefor(2560, 1440, 1.0) - (4.0 / 3.0)) < 0.001
                and abs(uiscalefor(2560, 1600, 1.0) - (4.0 / 3.0)) < 0.001
                and abs(uiscalefor(3840, 2160, 1.0) - 2.0) < 0.001)
            screenshotscale = uiscalefor(3839, 1974, 0.8)
            previousscale = UISCALE
            try:
                UISCALE = screenshotscale
                screenshotwindow = windowpixelsize()
                result['checks']['settings_3839x1974_80_scale'] = (
                    abs(screenshotscale - (1974.0 / 1080.0 * 0.8)) < 0.001
                    and screenshotwindow == (
                        int(round(BASEWINW * screenshotscale)),
                        int(round(BASEWINH * screenshotscale)))
                    and managedtexttop(100, 22, ascender=18) ==
                    scalepixel(100) + 4)
            finally:
                UISCALE = previousscale
            previouslayoutstate = (UISCALE, WINW, WINH, SECTION, DISPLAYPAGE)
            try:
                UISCALE = uiscalefor(2560, 1440, 1.0)
                WINW, WINH = BASEWINW, BASEWINH
                SECTION, DISPLAYPAGE = 'display', 'main'
                displayrows = layout()['rows']
                valueboxes = (
                    fieldvaluebox(displayrows['display']),
                    dropdownvaluebox(displayrows['resolution']),
                    dropdownvaluebox(displayrows['ui_scale']),
                )
                physicalboxes = tuple(scalerect(rect) for rect in valueboxes)
                result['checks']['settings_field_alignment'] = (
                    len({rect[0] for rect in valueboxes}) == 1
                    and len({rect[2] for rect in valueboxes}) == 1
                    and len({rect[0] for rect in physicalboxes}) == 1
                    and len({rect[2] for rect in physicalboxes}) == 1
                    and scalerect([0, 0, BASEWINW, BASEWINH])
                    == [0, 0, 1227, 960])
            finally:
                UISCALE, WINW, WINH, SECTION, DISPLAYPAGE = previouslayoutstate
            result['checks']['muted_text_contrast'] = COLOURMUTED == 0x8A8A8A
            DISPLAY['width'], DISPLAY['height'] = 2560, 1440
            result['checks']['live_opengl_resolution'] = (
                syncliveresolution(3840, 2160) and
                (DISPLAY['width'], DISPLAY['height']) == (3840, 2160) and
                (3840, 2160) in RESOLUTIONS)
            NETWORK.update({'dhcp': False, 'address': '192.168.1.20', 'netmask': '24', 'gateway': '192.168.1.1', 'dns1': '1.1.1.1', 'dns2': '8.8.8.8'})
            savenetwork()
            result['checks']['network_persistence'] = loadkeyvalues(NETWORKFILE).get('address') == '192.168.1.20'
            result['checks']['dns_persistence'] = 'nameserver 1.1.1.1' in open(DNSFILE, encoding='utf-8').read()
            result['checks']['invalid_static_rejected'] = False
            NETWORK['address'] = 'not-an-address'
            try:
                savenetwork()
            except ValueError:
                result['checks']['invalid_static_rejected'] = True
            packet = audiopacket(MSGVOLUME, {'gain': 0.5})
            magic, protocol, message, flags, length = struct.unpack('>4sBBHI', packet[:HEADER_SIZE])
            result['checks']['audio_protocol'] = magic == MAGIC and protocol == PROTO and message == MSGVOLUME and length > 0
            result['checks']['recognisable_audio_name'] = (
                audiodevicename({
                    'id': 'snd',
                    'name': 'snd',
                    'caps': {'name': 'Realtek ALC897 Analog'},
                }) == 'Realtek ALC897 Analog')
            result['checks']['audio_product_name_priority'] = (
                audiodevicename({
                    'id': 'snd',
                    'name': 'ALC897 Analog',
                    'caps': {'manufacturer': 'Logitech', 'product': 'G Pro X Wireless'},
                }) == 'Logitech G Pro X Wireless')
            result['checks']['audio_codec_over_system_vendor'] = (
                audiodevicename({
                    'id': 'snd',
                    'name': 'Micro-Star International Co., Ltd.',
                    'caps': {'name': 'Realtek ALC897'},
                }) == 'Realtek ALC897')
            result['checks']['audio_default_20'] = DEFAULTAUDIO.get('mastergain') == 0.20
            TIME['internet'] = True
            setclock()
            result['checks']['internet_time_persistence'] = readinternettime()
            result['checks']['virtualbox_time_default'] = readvirtualboxtime()
            result['checks']['timezone_persistence'] = readtimezone() == DEFAULTTIMEZONE
            result['checks']['timezone_daylight_saving'] = (
                motherboarddatetime(DEFAULTTIMEZONE, 1767225600).utcoffset() !=
                motherboarddatetime(DEFAULTTIMEZONE, 1782864000).utcoffset())
            result['checks']['manual_time_uses_timezone'] = (
                manualepoch('23:07:6AE', '10:00', DEFAULTTIMEZONE) == 1784764800)
            winterrtc = motherboardclockfields(1784764800, DEFAULTTIMEZONE)
            summerrtc = motherboardclockfields(1767225600, DEFAULTTIMEZONE)
            result['checks']['rtc_writes_local_wall_time'] = (
                winterrtc[:6] == (0, 0, 10, 23, 6, 126)
                and summerrtc[:6] == (0, 0, 11, 1, 0, 126))
            result['checks']['rtc_writes_daylight_flag'] = winterrtc[8] == 0 and summerrtc[8] == 1
            result['checks']['atreyan_date_format'] = (
                formatatreyandate(motherboarddatetime(DEFAULTTIMEZONE, 1784764800)) == '23:07:6AE')
            connector = os.path.join(DRMSTATE, 'card0-HDMI-A-1')
            os.makedirs(connector, exist_ok=True)
            atomictext(os.path.join(connector, 'status'), 'connected\n')
            atomictext(os.path.join(connector, 'connector_id'), '42\n')
            edid = bytearray(128)
            edid[:8] = b'\x00\xff\xff\xff\xff\xff\xff\x00'
            edid[54:72] = b'\x00\x00\x00\xfc\x00LG ULTRAGEAR\n'
            with open(os.path.join(connector, 'edid'), 'wb') as stream:
                stream.write(edid)
            result['checks']['display_product_name'] = displayproductname() == 'LG ULTRAGEAR'
            wirelessstate = os.path.join(NETSTATE, 'wlan0')
            os.makedirs(os.path.join(wirelessstate, 'wireless'), exist_ok=True)
            atomictext(os.path.join(wirelessstate, 'carrier'), '1\n')
            atomictext(os.path.join(wirelessstate, 'operstate'), 'up\n')
            atomictext(os.path.join(wirelessstate, 'address'), '00:11:22:33:44:55\n')
            NETWORK.update({'interface': 'wlan0', 'dhcp': True, 'dns1': '', 'dns2': ''})
            WIRELESS.update({
                'ssid': 'Home Network',
                'security': 'wpa2',
                'passphrase': 'correct horse battery staple',
            })
            savenetwork()
            storedwireless = loadkeyvalues(WIRELESSFILE)
            storedcredential = storedwireless.get('credential', '')
            result['checks']['wireless_credentials_persistence'] = (
                storedwireless.get('ssid') == 'Home Network'
                and storedwireless.get('security') == 'wpa2'
                and validwirelesscredential(storedcredential)
                and 'passphrase' not in storedwireless
                and diagnosticsecrets.get(storedcredential)
                == 'correct horse battery staple')
            result['checks']['network_reconfigure_request'] = os.path.isfile(NETWORKRECONFIGURE)
            atomicjson(WIRELESSSCANSTATE, {
                'networks': [
                    {'ssid': 'Home Network', 'security': 'wpa2', 'signal': -41},
                    {'ssid': 'Guest', 'security': 'open', 'signal': -60},
                ],
            })
            refreshwirelessnetworks(force=True)
            result['checks']['wireless_scan_results'] = (
                [item['ssid'] for item in WIRELESSNETWORKS] == ['Home Network', 'Guest'])
            setstatus('2 Wi-Fi networks available.', section='network')
            result['checks']['wireless_status_scoped_to_network'] = (
                statusvisible('network')
                and not statusvisible('display')
                and not statusvisible('audio')
                and not statusvisible('time & date'))
            atomicjson(NETWORKSTATE, {
                'interface': 'wlan0',
                'type': 'wi-fi',
                'connected': True,
                'name': 'MyHomeWiFi-AX',
                'address': '192.168.1.20/24',
                'gateway': '192.168.1.1',
                'mac': '00:11:22:33:44:55',
            })
            result['checks']['network_connection_identity'] = (
                networkconnectionlabel('wlan0') == 'wi-fi — MyHomeWiFi-AX')
            result['checks']['network_name_case_preserved'] = (
                networkdisplayname('MyHomeWiFi-AX') == 'MyHomeWiFi-AX')
            result['checks']['network_technical_details'] = networkdetails('wlan0') == {
                'interface': 'wlan0',
                'mac': '00:11:22:33:44:55',
                'address': '192.168.1.20/24',
                'gateway': '192.168.1.1',
            }
            disconnected = loadjson(NETWORKSTATE, {})
            disconnected['connected'] = False
            atomicjson(NETWORKSTATE, disconnected)
            result['checks']['network_details_hidden_when_disconnected'] = not networkdetails('wlan0')
            ethernetstate = os.path.join(NETSTATE, 'eth0')
            os.makedirs(ethernetstate, exist_ok=True)
            atomictext(os.path.join(ethernetstate, 'carrier'), '1\n')
            atomictext(os.path.join(ethernetstate, 'operstate'), 'up\n')
            atomictext(os.path.join(ethernetstate, 'address'), '00:11:22:33:44:66\n')
            connectionkey = 'ethernet-0123456789abcdef01234567'
            atomicjson(NETWORKSTATE, {
                'interface': 'eth0',
                'type': 'ethernet',
                'connected': True,
                'name': '',
                'connection_id': connectionkey,
                'address': '192.168.1.21/24',
                'gateway': '192.168.1.1',
                'mac': '00:11:22:33:44:66',
            })
            refreshnetworkinterfaces()
            NETWORK['interface'] = ''
            ETHERNETNAMES[connectionkey] = 'Studio LAN'
            savenetwork()
            result['checks']['custom_ethernet_name_persistence'] = (
                loadjson(ETHERNETNAMESFILE, {}).get(connectionkey) == 'Studio LAN')
            result['checks']['custom_ethernet_name_identity'] = (
                networkconnectionlabel('eth0') == 'ethernet — Studio LAN')
            namedethernet = loadjson(NETWORKSTATE, {})
            namedethernet['name'] = 'RouterDomain'
            atomicjson(NETWORKSTATE, namedethernet)
            result['checks']['dhcp_ethernet_name_priority'] = (
                networkconnectionlabel('eth0') == 'ethernet — RouterDomain')
            virtualboxclient = os.path.join(root, 'software', 'virtualbox', 'VBoxDRMClient')
            virtualboxguest = os.path.join(root, 'drivers', 'nodes', 'vboxguest')
            atomictext(virtualboxclient, '', mode=0o700)
            atomictext(virtualboxguest, '', mode=0o600)
            result['checks']['virtualbox_resolution_authority'] = virtualboxcontrolsresolution()
            result['checks']['sections'] = tuple(SECTIONS) == (
                'display', 'audio', 'mouse', 'network', 'time & date',
                'master', 'recovery', 'python', 'about')
            SECTION = 'display'
            CONTROLS = layout()
            masterrect = CONTROLS['nav']['master']
            handlebutton({
                'button': 1, 'state': 'down',
                'x': scalepixel(masterrect[0] + masterrect[2] // 2),
                'y': scalepixel(masterrect[1] + masterrect[3] // 2),
            })
            masterclicked = SECTION == 'master'
            CONTROLS = layout()
            aboutrect = CONTROLS['nav']['about']
            handlebutton({
                'button': 1, 'state': 'down',
                'x': scalepixel(aboutrect[0] + aboutrect[2] // 2),
                'y': scalepixel(aboutrect[1] + aboutrect[3] // 2),
            })
            result['checks']['physical_navigation_clicks'] = (
                masterclicked and SECTION == 'about')
            result['passed'] = all(result['checks'].values())
    except Exception as error:
        result['errors'].append(str(error))
    finally:
        (SYSTEMROOT, DISPLAYFILE, AUDIOFILE, MOUSEFILE, NETWORKDIR, NETWORKFILE, DNSFILE, ETHERNETNAMESFILE, NETWORKSTATE, WIRELESSFILE, WIRELESSSCANSTATE, WIRELESSSCANREQUEST, NETWORKRECONFIGURE, INTERNETTIMEFILE, VIRTUALBOXTIMEFILE, TIMEZONEFILE, TERMINALNAMEFILE, MASTERSETTINGSFILE, MASTERHOMEBASE, ZONEINFODIR, DRMSTATE, NETSTATE) = original
        (
            architect_authorize,
            architect_revoke,
            service_secret_delete,
            service_secret_exists,
            service_secret_put,
            settings_account_get,
            settings_hostname_set,
            settings_master_update,
            settings_recovery_authorize,
            settings_time_set,
        ) = diagnosticoperationsoriginal
    print(json.dumps(result, sort_keys=True, separators=(',', ':')))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1].strip().lower() == '--diagnostic':
        raise SystemExit(diagnostic())
    raise SystemExit(main())
