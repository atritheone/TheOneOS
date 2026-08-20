#!"/the one/software/python/bin/python" -B

"""
operationsserver.py

operations server is the T1OS operations socket server. It accepts
requests from userland over a unix socket and launches processes,
registers existing processes, lists operations, and sends kill
signals. GODDESS remains responsible for supervising system services
and publishes their identities through the authenticated socket.
"""



# imports
import os
import sys
import json
import time
import socket
import signal
import struct
import threading
import subprocess
import shutil
import re
import stat as statmodule
import ctypes
import resource
import datetime
import zoneinfo
import fcntl
import errno

sys.path.insert(0, '/the one/build')
from GODDESS.GODDESS import (
    dropchromiumidentity,
    dropdesktopidentity,
    formatlog,
    popenisolated,
    popensecured,
    publishsessionidentity,
    softwarelogpath,
)
from broker import broker as authbroker

_builtin_print = print


def print(*values, sep=' ', end='\n', file=None, flush=False):

    target = sys.stdout if file is None else file
    if target is sys.stderr:
        message = sep.join(str(value) for value in values)
        prefix = '> operations server '
        if message.lower().startswith(prefix):
            message = message[len(prefix):]
        return _builtin_print(formatlog('operations server', message), end=end,
                              file=target, flush=flush)
    return _builtin_print(*values, sep=sep, end=end, file=target, flush=flush)



# globals
OPERATIONSROOT = '/.ephemeral/operations'
OPERATIONSSTATE = os.path.join(OPERATIONSROOT, 'state.json')
OPERATIONSSOCKET = os.path.join(OPERATIONSROOT, 'control.sock')
PROCESSROOT = '/the one/drivers/processes'
GRAPHICSSTATEPATH = '/.ephemeral/windowserver/state/graphics.json'
DESKTOPUID = 1000
DESKTOPGID = 1000
MAXIMUMREQUEST = 65536
VALIDRECOVERYACTIONS = frozenset(('python', 'build', 'reset', 'reinstall'))
VMTESTMAXOUTPUT = 4 * 1024 * 1024
VMTESTMAXDIRECTIVE = 32 * 1024
VMTESTMEDIA = '/software/without_a_blush.mp4'
VMTESTAUDIO = '/software/hey_now.flac'
VMTESTIMAGE = '/software/if_you_wait.jpg'
VMTESTTEXT = '/software/opengltest1.py'
VMTESTOPENGL = '/software/opengltest2.py'
VMTESTCREEP = '/software/creep.py'
VMTESTTERMINALRESULT = '/master/development/terminal_test.result'
VMTESTPLAYERSTATUS = '/.ephemeral/media/vm-player-status-{}.json'
SESSIONIDENTITYFILE = '/the one/settings/session/identity.json'
LOCKSCREENREADYPATH = '/.ephemeral/windowserver/state/lockscreen-ready.json'
LOCKSCREENLIFECYCLEPATH = '/.ephemeral/lock screen/state.json'
LOCKSCREENPOSTHANDOFFPATH = '/.ephemeral/lock screen/post-handoff-ready.json'
LOGINREADYPATH = '/.ephemeral/startup/login-ready.json'
SERVICESECRETDIRECTORY = '/the one/master/service credentials'
SERVICESECRETNAME = re.compile(r'network\.wireless\.[0-9a-f]{24}\Z')
MAXIMUMSERVICESECRET = 4096
STARTUPSCRIPT = '/the one/build/startup/startup.py'
STARTUPLOG = '/the one/logs/startup.py.log'
STARTUPFILE = '/the one/settings/procedures/startup/startup.txt'
MASTERFILE = '/the one/master/master.txt'
MASTERSETTINGSFILE = '/the one/settings/master/settings.json'
MASTERSETTINGSDIRECTORYMODE = 0o711
MASTERSETTINGSFILEMODE = 0o644
RTCSETTIME = 0x4024700A
RTCREADTIME = 0x80247009
TIMEZONEFILE = '/the one/settings/time/timezone.txt'
INTERNETTIMEFILE = '/the one/settings/time/internet.txt'
VIRTUALBOXTIMEFILE = '/the one/settings/time/virtualbox.txt'
ZONEINFODIR = '/the one/software/chromium/resources/zoneinfo'
DEFAULTTIMEZONE = 'Australia/Sydney'
VIRTUALBOXGUESTNODE = '/the one/drivers/nodes/vboxguest'
MINIMUMCLOCKEPOCH = 1609459200.0
MAXIMUMCLOCKEPOCH = 4102444800.0

# This catalogue is broker-owned.  Callers may select an entry, but may not
# supply a profile, executable, log destination, uid, gid, or arbitrary
# environment.  The descriptor-bound profile is revalidated by the kernel.
APPLICATIONCATALOGUE = {
    '/the one/build/array/array.py': {
        'name': 'array', 'profile': 'desktop', 'arguments': 'array',
    },
    '/the one/build/brick/brick.py': {
        'name': 'brick', 'profile': 'brick', 'arguments': 'brick',
        'environment': {'BRICK_WINDOW': frozenset(('0', '1'))},
    },
    '/the one/build/calculator/calculator.py': {
        'name': 'calculator', 'profile': 'desktop', 'arguments': 'none',
    },
    '/the one/build/operations/operationscentre.py': {
        'name': 'operations centre', 'profile': 'desktop', 'arguments': 'none',
    },
    '/the one/build/chromium/chromium.py': {
        'name': 'chromium', 'profile': 'chromium', 'arguments': 'none',
    },
    '/the one/build/player/player.py': {
        'name': 'player', 'profile': 'video', 'arguments': 'file',
    },
    '/the one/build/settings/settings.py': {
        'name': 'settings', 'profile': 'settings', 'arguments': 'none',
        'environment': {
            'T1OS_SETTINGS_SECTION': frozenset((
                'about', 'appearance', 'audio', 'display', 'master', 'mouse',
                'network', 'python', 'recovery', 'time', 'virtualbox')),
            'T1OS_SETTINGS_TARGET': None,
        },
    },
    '/the one/build/snap/snap.py': {
        'name': 'snap', 'profile': 'snap', 'arguments': 'none',
    },
    '/the one/build/viewer/viewer.py': {
        'name': 'viewer', 'profile': 'desktop', 'arguments': 'files',
    },
    '/the one/build/write/write.py': {
        'name': 'write', 'profile': 'desktop', 'arguments': 'file',
    },
}

# Procedures may select only these broker-owned identifiers.  Their policy
# files never confer authority by naming a filesystem path; Operations maps an
# ID to the same fixed catalogue object and keeps argv empty.
STARTUPAPPLICATIONS = frozenset((
    'brick',
    'calculator',
    'operations centre',
    'chromium',
    'settings',
    'snap',
))
PROCEDURECATALOGUE = {
    policy['name']: {
        'path': path,
        'name': policy['name'],
        'profile': policy['profile'],
        'arguments': 'none',
    }
    for path, policy in APPLICATIONCATALOGUE.items()
    if policy.get('name') in STARTUPAPPLICATIONS
}

PEERUIDS = {
    'goddess': frozenset((0,)),
    'startup': frozenset((0,)),
    'architect': frozenset((0,)),
    'operations': frozenset((0,)),
    'procedures': frozenset((0,)),
    'window': frozenset((0,)),
    'audio': frozenset((0,)),
    'driver': frozenset((0,)),
    'input': frozenset((0,)),
    'network': frozenset((0,)),
    'reign': frozenset((0,)),
    'python': frozenset((0,)),
    'exchange': frozenset((0,)),
    'virtualbox': frozenset((0,)),
    'expanse': frozenset((DESKTOPUID,)),
    'brick': frozenset((DESKTOPUID,)),
    'desktop': frozenset((DESKTOPUID,)),
    'video': frozenset((DESKTOPUID,)),
    'settings': frozenset((DESKTOPUID,)),
    'snap': frozenset((DESKTOPUID,)),
    'chromium': frozenset((DESKTOPUID,)),
    'lockscreen': frozenset((DESKTOPUID,)),
}
SERVERSTOP = False
ACCEPTTIMEOUT = 1.0
REAPINTERVAL = 0.5
TELEMETRYINTERVAL = 0.5
LASTREAP = 0.0
STATELOCK = threading.Lock()
STATEWRITELOCK = threading.Lock()
PROCESSES = {}
OPMETA = {}
COMPLETED = {}
READYPENDING = {}
READYPENDINGTTL = 30.0
COMPLETEDKEEP = 50
TELEMETRYLOCK = threading.Lock()
TELEMETRY = {'sampled': 0.0, 'sample_ms': 0, 'system': {}, 'processes': {}}
TELEMETRYPREVIOUS = {}
SYSTEMPREVIOUS = None
TELEMETRYPREVIOUSTIME = 0.0
GRAPHICSLOCK = threading.Lock()
GRAPHICSPREVIOUS = {'sampled': 0.0, 'render_total_ms': 0.0, 'frames': 0, 'windows': {}}
GRAPHICSCURRENT = {'system': {}, 'processes': {}}

try:
    CLOCKTICKS = int(os.sysconf('SC_CLK_TCK'))
except Exception:
    CLOCKTICKS = 100

try:
    PAGESIZE = int(os.sysconf('SC_PAGE_SIZE'))
except Exception:
    PAGESIZE = 4096



# telemetry functions
def processtext(path, limit=262144):

    try:

        with open(path, 'r', encoding='utf-8', errors='replace') as stream:
            return stream.read(max(1, int(limit)))

    except Exception:
        return ''


def processdomain(pid):

    """Return the immutable T1OS LSM domain for a live process."""

    root = os.path.join(PROCESSROOT, str(int(pid)), 'attr')
    for relative in (os.path.join('t1os', 'current'), 'current'):
        value = processtext(os.path.join(root, relative), 128).strip()
        if value.startswith('t1os:'):
            domain = value[5:].strip()
            if re.fullmatch(r'[a-z][a-z0-9-]{0,31}', domain):
                return domain
    return None


def capturepeer(peer):

    if not isinstance(peer, dict):
        return None
    try:
        pid = int(peer.get('pid'))
        uid = int(peer.get('uid'))
        gid = int(peer.get('gid'))
    except (TypeError, ValueError):
        return None
    # GODDESS is PID 1 and is the only peer allowed to bootstrap the early
    # service snapshot. All other peer checks retain their domain allowlists.
    if pid < 1 or uid < 0 or gid < 0:
        return None
    record = processstat(pid)
    domain = processdomain(pid)
    if record is None or domain not in PEERUIDS or uid not in PEERUIDS[domain]:
        return None
    return {
        'pid': pid,
        'uid': uid,
        'gid': gid,
        'started': int(record.get('started', 0)),
        'domain': domain,
    }


def peerstillvalid(peer):

    if not isinstance(peer, dict):
        return False
    try:
        record = processstat(int(peer['pid']))
        if record is None or int(record.get('started', -1)) != int(peer['started']):
            return False
        domain = processdomain(int(peer['pid']))
        return (
            domain == peer.get('domain') and
            int(peer['uid']) in PEERUIDS.get(domain, ())
        )
    except (KeyError, TypeError, ValueError):
        return False


def requestaction(request):

    action = request.get('action', request.get('op', ''))
    return str(action or '').strip().upper()


ACTIONDOMAINS = {
    'BOOTSTRAP': frozenset(('goddess',)),
    'VM_TEST_BRICK_EXECUTE': frozenset(('virtualbox',)),
    'VM_TEST_LAUNCH': frozenset(('virtualbox',)),
    'VM_TEST_CLOSE': frozenset(('virtualbox',)),
    'VM_TEST_STATUS': frozenset(('virtualbox',)),
    'LAUNCH_CATALOGUE': frozenset(('expanse', 'desktop', 'brick')),
    'CATALOGUE_LIST': frozenset(('brick',)),
    'SESSION_LOGOUT': frozenset(('expanse', 'brick')),
    'DESKTOP_CREATE': frozenset(('expanse',)),
    'DESKTOP_RENAME': frozenset(('expanse',)),
    'SESSION_LOCK_START': frozenset(('window',)),
    'SESSION_AUTH_VERIFY': frozenset(('lockscreen',)),
    'PROCEDURE_LAUNCH': frozenset(('procedures',)),
    'STARTUP_LIST': frozenset(('brick',)),
    'STARTUP_ADD': frozenset(('brick',)),
    'STARTUP_REMOVE': frozenset(('brick',)),
    'STARTUP_CHANGE': frozenset(('brick',)),
    'SERVICE_SECRET_PUT': frozenset(('settings',)),
    'SERVICE_SECRET_DELETE': frozenset(('settings',)),
    'SERVICE_SECRET_EXISTS': frozenset(('settings',)),
    'SERVICE_SECRET_GET': frozenset(('network',)),
    'SETTINGS_AUTH_VERIFY': frozenset(('settings',)),
    'SETTINGS_ACCOUNT_GET': frozenset(('settings', 'brick')),
    'SETTINGS_MASTER_UPDATE': frozenset(('settings', 'brick')),
    'SETTINGS_RECOVERY_AUTHORIZE': frozenset(('settings',)),
    'SETTINGS_HOSTNAME_SET': frozenset(('settings', 'brick')),
    'SETTINGS_TIME_SET': frozenset(('settings', 'brick')),
    'TIME_SAMPLE_SET': frozenset(('reign',)),
    'REGISTER_PID': frozenset(('window', 'brick', 'desktop', 'video', 'settings', 'snap', 'chromium', 'picker')),
    'COMPLETE_PID': frozenset(('brick', 'desktop', 'video', 'settings', 'snap', 'chromium')),
    'READY_PID': frozenset(('window', 'brick', 'desktop', 'video', 'settings', 'snap', 'chromium', 'picker')),
    'KILL': frozenset(('window', 'brick', 'desktop')),
    'LIST': frozenset(PEERUIDS),
    'WAIT': frozenset(('window', 'brick', 'desktop', 'procedures')),
}


def authorizerequest(request):

    peer = request.get('_peer')
    action = requestaction(request)
    allowed = ACTIONDOMAINS.get(action)
    if allowed is None or not peerstillvalid(peer):
        return False
    return str(peer.get('domain')) in allowed


def vmtestenabled():

    """Require the signed, test-template-only developer boot boundary."""

    return (
        os.environ.get('T1OS_DEVELOPER') == '1' and
        os.environ.get('T1OS_ENABLE_VM_TEST_AGENT') == '1'
    )


def graphicstelemetry():

    global GRAPHICSPREVIOUS, GRAPHICSCURRENT

    with GRAPHICSLOCK:

        try:

            text = processtext(GRAPHICSSTATEPATH, 4 * 1024 * 1024)

            if not text:
                return {'system': {}, 'processes': {}}

            state = json.loads(text)
            sampled = float(state.get('sampled') or os.path.getmtime(GRAPHICSSTATEPATH))

            if sampled <= float(GRAPHICSPREVIOUS.get('sampled', 0.0)):

                system = dict(GRAPHICSCURRENT.get('system', {}))
                processes = dict(GRAPHICSCURRENT.get('processes', {}))

                if time.time() - sampled > 3.0:
                    system['gpu_percent'] = None
                    processes = {}

                return {
                    'system': system,
                    'processes': processes,
                }

            telemetry = state.get('telemetry', {})
            frames = max(0, int(telemetry.get('frames', 0)))
            averagerender = max(0.0, float(telemetry.get('average_render_ms', 0.0)))
            rendertotal = averagerender * float(frames)
            previoussampled = float(GRAPHICSPREVIOUS.get('sampled', 0.0))
            previousframes = int(GRAPHICSPREVIOUS.get('frames', 0))
            previousrender = float(GRAPHICSPREVIOUS.get('render_total_ms', 0.0))
            accelerated = (
                str(state.get('window_compositor', '')).lower() == 'gpu'
                and not bool(state.get('gpu_failed', False))
            )
            percent = None

            if previoussampled > 0.0:

                elapsed = max(0.001, sampled - previoussampled)
                framedelta = max(0, frames - previousframes)

                if not accelerated or framedelta == 0:
                    percent = 0.0

                else:
                    renderdelta = max(0.0, rendertotal - previousrender)
                    percent = max(0.0, min(100.0, (renderdelta / (elapsed * 1000.0)) * 100.0))

            windows = {}

            for window in state.get('window_telemetry', {}).get('windows', []):

                try:

                    identifier = str(int(window.get('id')))
                    windows[identifier] = {
                        'pid': max(0, int(window.get('pid', 0))),
                        'pixels': max(0, int(window.get('composited_pixels', 0))),
                        'draws': max(0, int(window.get('gpu_draw_calls', 0))),
                    }

                except Exception:
                    continue

            previouswindows = GRAPHICSPREVIOUS.get('windows', {})
            deltas = []

            for identifier, window in windows.items():

                previous = previouswindows.get(identifier, {})

                if int(previous.get('pid', 0)) != int(window.get('pid', 0)):
                    previous = {}

                deltas.append({
                    'pid': int(window.get('pid', 0)),
                    'pixels': max(0, int(window.get('pixels', 0)) - int(previous.get('pixels', 0))),
                    'draws': max(0, int(window.get('draws', 0)) - int(previous.get('draws', 0))),
                })

            totalpixels = sum(value['pixels'] for value in deltas)
            totaldraws = sum(value['draws'] for value in deltas)
            processpercent = {}

            if percent is not None and percent > 0.0:

                for value in deltas:

                    pid = int(value.get('pid', 0))

                    if pid <= 0:
                        continue

                    if totalpixels > 0:
                        share = float(value.get('pixels', 0)) / float(totalpixels)

                    elif totaldraws > 0:
                        share = float(value.get('draws', 0)) / float(totaldraws)

                    else:
                        share = 0.0

                    processpercent[str(pid)] = processpercent.get(str(pid), 0.0) + (percent * share)

            system = {
                'gpu_percent': percent,
                'gpu_name': str(
                    state.get('renderer')
                    or state.get('drm_driver')
                    or state.get('backend')
                    or 'graphics processor'
                )[:128],
                'gpu_backend': str(state.get('backend', ''))[:64],
                'gpu_accelerated': bool(accelerated),
            }
            GRAPHICSPREVIOUS = {
                'sampled': sampled,
                'render_total_ms': rendertotal,
                'frames': frames,
                'windows': windows,
            }
            GRAPHICSCURRENT = {'system': system, 'processes': processpercent}
            return {'system': dict(system), 'processes': dict(processpercent)}

        except Exception:
            return {'system': {}, 'processes': {}}


def processstat(pid):

    try:

        path = os.path.join(PROCESSROOT, str(int(pid)), 'stat')
        text = processtext(path, 16384).strip()

        if not text or ')' not in text:
            return None

        left, right = text.rsplit(')', 1)
        fields = right.strip().split()

        if len(fields) < 22:
            return None

        return {
            'pid': int(pid),
            'name': left.split('(', 1)[-1],
            'state': fields[0],
            'parent': int(fields[1]),
            'ticks': int(fields[11]) + int(fields[12]),
            'threads': int(fields[17]),
            'started': int(fields[19]),
            'rss': max(0, int(fields[21])) * PAGESIZE,
        }

    except Exception:
        return None


def processrunning(pid):

    ipid = int(pid)
    stat = processstat(ipid)

    if stat is not None and str(stat.get('state', '')).upper() == 'Z':
        return False

    try:
        os.kill(ipid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return True


def processstatus(pid):

    values = {}
    path = os.path.join(PROCESSROOT, str(int(pid)), 'status')

    try:

        for line in processtext(path).splitlines():

            if ':' not in line:
                continue

            key, value = line.split(':', 1)
            values[key.strip()] = value.strip()

    except Exception:
        return {}

    result = {}

    for source, target in (('VmRSS', 'memory'), ('VmHWM', 'peak_memory')):

        try:

            match = values.get(source, '').split()

            if match:
                result[target] = int(match[0]) * 1024

        except Exception:
            pass

    try:
        result['threads'] = int(values.get('Threads', ''))
    except Exception:
        pass

    for source, target in (('Uid', 'uid'), ('Gid', 'gid')):
        try:
            fields = values.get(source, '').split()
            if fields:
                result[target] = int(fields[0])
        except Exception:
            pass

    return result


def processio(pid):

    result = {}
    path = os.path.join(PROCESSROOT, str(int(pid)), 'io')

    try:

        for line in processtext(path, 65536).splitlines():

            if ':' not in line:
                continue

            key, value = line.split(':', 1)

            if key.strip() == 'read_bytes':
                result['read_bytes'] = max(0, int(value.strip()))

            elif key.strip() == 'write_bytes':
                result['write_bytes'] = max(0, int(value.strip()))

    except Exception:
        return {}

    return result


def processrecord(pid):

    stat = processstat(pid)

    if stat is None:
        return None

    status = processstatus(pid)
    usage = processio(pid)
    record = dict(stat)
    record.update(status)
    record.update(usage)
    record['memory'] = int(record.get('memory', record.get('rss', 0)))
    record['peak_memory'] = max(
        int(record.get('memory', 0)),
        int(record.get('peak_memory', record.get('memory', 0))),
    )
    record['read_bytes'] = int(record.get('read_bytes', 0))
    record['write_bytes'] = int(record.get('write_bytes', 0))
    record['identity'] = f"{int(pid)}:{int(record.get('started', 0))}"
    return record


def processrecords():

    records = {}

    try:
        entries = os.listdir(PROCESSROOT)
    except Exception:
        return records

    for entry in entries:

        if not str(entry).isdigit():
            continue

        record = processrecord(int(entry))

        if record is not None:
            records[str(int(entry))] = record

    return records


def systemcounters():

    total = None
    idle = None
    memorytotal = None
    memoryavailable = None

    try:

        first = processtext(os.path.join(PROCESSROOT, 'stat'), 65536).splitlines()[0]
        fields = first.split()

        if fields and fields[0] == 'cpu':

            values = [int(value) for value in fields[1:11]]
            total = sum(values)
            idle = values[3] + (values[4] if len(values) > 4 else 0)

    except Exception:
        pass

    try:

        values = {}

        for line in processtext(os.path.join(PROCESSROOT, 'meminfo'), 65536).splitlines():

            if ':' not in line:
                continue

            key, value = line.split(':', 1)
            parts = value.strip().split()

            if parts:
                values[key.strip()] = int(parts[0]) * 1024

        memorytotal = values.get('MemTotal')
        memoryavailable = values.get('MemAvailable')

        if memoryavailable is None:
            memoryavailable = (
                int(values.get('MemFree', 0))
                + int(values.get('Buffers', 0))
                + int(values.get('Cached', 0))
            )

    except Exception:
        pass

    return {
        'total': total,
        'idle': idle,
        'memory_total_bytes': memorytotal,
        'memory_available_bytes': memoryavailable,
    }


def sampletelemetry(force=False):

    global TELEMETRY, TELEMETRYPREVIOUS, SYSTEMPREVIOUS, TELEMETRYPREVIOUSTIME

    now = time.time()

    with TELEMETRYLOCK:

        if not force and now - float(TELEMETRY.get('sampled', 0.0)) < TELEMETRYINTERVAL:
            return dict(TELEMETRY)

    records = processrecords()
    system = systemcounters()
    graphics = graphicstelemetry()
    elapsed = max(0.0, now - float(TELEMETRYPREVIOUSTIME))
    previoussystem = SYSTEMPREVIOUS
    systemcpu = None
    totaltickdelta = None

    try:

        if previoussystem and system.get('total') is not None:

            totaltickdelta = max(0, int(system['total']) - int(previoussystem['total']))
            idledelta = max(0, int(system['idle']) - int(previoussystem['idle']))

            if totaltickdelta > 0:
                systemcpu = max(0.0, min(100.0, ((totaltickdelta - idledelta) / totaltickdelta) * 100.0))

    except Exception:
        systemcpu = None
        totaltickdelta = None

    current = {}

    for pid, record in records.items():

        entry = dict(record)
        previous = TELEMETRYPREVIOUS.get(entry.get('identity'))
        cpu = None

        try:

            if previous and totaltickdelta and totaltickdelta > 0:
                delta = max(0, int(entry.get('ticks', 0)) - int(previous.get('ticks', 0)))
                cpu = max(0.0, (delta / totaltickdelta) * 100.0)

        except Exception:
            cpu = None

        entry['cpu_percent'] = cpu
        systemgpu = graphics.get('system', {}).get('gpu_percent')
        entry['gpu_percent'] = (
            graphics.get('processes', {}).get(str(pid), 0.0)
            if systemgpu is not None
            else None
        )
        current[pid] = entry

    memorytotal = system.get('memory_total_bytes')
    memoryavailable = system.get('memory_available_bytes')
    memoryused = None

    try:

        if memorytotal is not None and memoryavailable is not None:
            memoryused = max(0, int(memorytotal) - int(memoryavailable))

    except Exception:
        memoryused = None

    snapshot = {
        'sampled': now,
        'sample_ms': int(round(elapsed * 1000.0)) if TELEMETRYPREVIOUSTIME else 0,
        'system': {
            'cpu_percent': systemcpu,
            'memory_total_bytes': memorytotal,
            'memory_available_bytes': memoryavailable,
            'memory_used_bytes': memoryused,
            **graphics.get('system', {}),
        },
        'processes': current,
    }

    TELEMETRYPREVIOUS = {
        str(record.get('identity')): {
            'ticks': int(record.get('ticks', 0)),
            'read_bytes': int(record.get('read_bytes', 0)),
            'write_bytes': int(record.get('write_bytes', 0)),
        }
        for record in current.values()
        if record.get('identity')
    }
    SYSTEMPREVIOUS = system
    TELEMETRYPREVIOUSTIME = now

    with TELEMETRYLOCK:
        TELEMETRY = snapshot

    return dict(snapshot)


def processtree(pid, records=None, registered=None):

    root = str(int(pid))
    records = records if isinstance(records, dict) else processrecords()
    registered = {str(int(value)) for value in (registered or [])}
    children = {}

    for key, info in records.items():

        try:
            parent = str(int(info.get('parent', 0)))
        except Exception:
            continue

        children.setdefault(parent, []).append(str(key))

    found = []
    pending = [root]

    while pending:

        current = pending.pop(0)

        if current in found:
            continue

        found.append(current)

        for child in children.get(current, []):

            if child in registered and child != root:
                continue

            pending.append(child)

    return found


def operationresources(pid, registered, telemetry):

    records = telemetry.get('processes', {}) if isinstance(telemetry, dict) else {}
    keys = processtree(pid, records=records, registered=registered)
    selected = [records[key] for key in keys if key in records]

    if not selected:
        return None, None

    cpuvalues = [value.get('cpu_percent') for value in selected if value.get('cpu_percent') is not None]
    gpuvalues = [value.get('gpu_percent') for value in selected if value.get('gpu_percent') is not None]
    identity = records.get(str(int(pid)), {}).get('identity')
    resources = {
        'cpu_percent': sum(float(value) for value in cpuvalues) if cpuvalues else None,
        'gpu_percent': sum(float(value) for value in gpuvalues) if gpuvalues else None,
        'memory_bytes': sum(int(value.get('memory', 0)) for value in selected),
        'peak_memory_bytes': sum(int(value.get('peak_memory', value.get('memory', 0))) for value in selected),
        'threads': sum(int(value.get('threads', 0)) for value in selected),
        'children': max(0, len(selected) - 1),
        'read_bytes': sum(int(value.get('read_bytes', 0)) for value in selected),
        'write_bytes': sum(int(value.get('write_bytes', 0)) for value in selected),
    }
    return identity, resources


def processdescendant(parent, child):

    try:

        parent = int(parent)
        current = int(child)

        if parent <= 0 or current <= 0:
            return False

        if parent == current:
            return True

        visited = set()

        while current > 1 and current not in visited:

            visited.add(current)
            record = processstat(current)

            if record is None:
                return False

            current = int(record.get('parent', 0))

            if current == parent:
                return True

    except Exception:
        return False

    return False


def operationpermission(info):

    try:

        return bool((info or {}).get('_broker_owned'))

    except Exception:
        return False


def dropsandboxidentity():

    """Drop catalogue/untrusted children before their first Python opcode."""

    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NOFILE, (1024, 1024))
    dropdesktopidentity()


def applicationenvironment(requested, policy):

    if not isinstance(requested, dict) or len(requested) > 8:
        raise ValueError('invalid environment')
    environment = {
        key: value for key, value in os.environ.items()
        if key in ('LANG', 'LC_ALL', 'LC_CTYPE', 'TZ', 'TERM', 'COLORTERM')
    }
    allowed = policy.get('environment', {})
    for rawkey, rawvalue in requested.items():
        key, value = str(rawkey), str(rawvalue)
        choices = allowed.get(key)
        if key not in allowed or len(value.encode('utf-8')) > 256:
            raise ValueError('environment key denied')
        if choices is not None and value not in choices:
            raise ValueError('environment value denied')
        if any(character in value for character in ('\x00', '\n', '\r')):
            raise ValueError('environment value denied')
        environment[key] = value
    username, _credentialhash = authbroker.read_credentials(MASTERFILE)
    username = authbroker.canonicalize_username(username)
    home = os.path.join('/master', username)
    homestatus = os.stat(home, follow_symlinks=False)
    if (not statmodule.S_ISDIR(homestatus.st_mode) or
            homestatus.st_uid != DESKTOPUID or homestatus.st_gid != DESKTOPGID):
        raise PermissionError('desktop home ownership is unsafe')
    environment['HOME'] = home
    environment['PATH'] = '/the one/software/python/bin:/the one/drivers/tools'
    return environment


def userpath(value):

    value = str(value)
    if not value.startswith('/') or len(value.encode('utf-8')) > 4096:
        raise ValueError('invalid path argument')
    if any(character in value for character in ('\x00', '\n', '\r')):
        raise ValueError('invalid path argument')
    return os.path.normpath(value)


def cataloguearguments(kind, arguments):

    if not isinstance(arguments, list) or len(arguments) > 8:
        raise ValueError('invalid arguments')
    values = [str(value) for value in arguments]
    if any(len(value.encode('utf-8')) > 4096 or '\x00' in value for value in values):
        raise ValueError('invalid arguments')
    if kind == 'none':
        if values:
            raise ValueError('arguments denied')
        return []
    if kind == 'file':
        if len(values) > 1:
            raise ValueError('arguments denied')
        return [userpath(value) for value in values]
    if kind == 'brick':
        if not values:
            return []
        if len(values) < 2 or values[0] != '--run-file':
            raise ValueError('arguments denied')
        target = userpath(values[1])
        if not target.lower().endswith('.py') or not (
            target == '/master' or target.startswith('/master/') or
            target == '/.ephemeral/volumes' or
            target.startswith('/.ephemeral/volumes/') or
            target == '/software' or target.startswith('/software/')
        ):
            raise ValueError('Python file denied')
        trailing = values[2:]
        if any(
            len(value.encode('utf-8')) > 256 or
            any(character in value for character in ('\x00', '\n', '\r'))
            for value in trailing
        ):
            raise ValueError('Python arguments denied')
        return ['--run-file', target, *trailing]
    if kind == 'files':
        return [userpath(value) for value in values]
    if kind == 'array':
        if not values:
            return []
        if values[0] in ('--open-item', '--search') and len(values) == 2:
            return [values[0], userpath(values[1]) if values[0] == '--open-item' else values[1][:1024]]
        if values[0] == '--search-session' and len(values) == 3:
            session = userpath(values[1])
            if not session.startswith('/.ephemeral/expanse/'):
                raise ValueError('search session denied')
            return [values[0], session, values[2][:1024]]
        if values[0] == '--context-action' and len(values) == 3:
            if values[1] not in (
                'copy', 'copypath', 'rename', 'delete', 'opennew', 'openwith',
            ):
                raise ValueError('context action denied')
            return [values[0], values[1], userpath(values[2])]
        if len(values) == 1:
            return [userpath(values[0])]
        raise ValueError('arguments denied')
    raise ValueError('unknown argument policy')


def sessionidentityfor(peerpid):

    peerpid = int(peerpid)
    record = processrecord(peerpid)
    if record is not None and processdomain(peerpid) == 'expanse':
        return str(record.get('identity', ''))
    with STATELOCK:
        entry = dict(OPMETA.get(str(peerpid), {}))
    if entry.get('_session_identity'):
        return str(entry['_session_identity'])
    # Walk to the session's measured Expanse ancestor; catalogue apps may in
    # turn launch further typed catalogue apps.
    current = peerpid
    visited = set()
    while current > 1 and current not in visited:
        visited.add(current)
        currentrecord = processrecord(current)
        if currentrecord is None:
            break
        if processdomain(current) == 'expanse':
            return str(currentrecord.get('identity', ''))
        current = int(currentrecord.get('parent', 0))
    return ''


def desktopitemname(value):

    name = str(value or '').strip()
    if (
        not name or name in ('.', '..') or '/' in name or
        any(character in name for character in ('\x00', '\n', '\r')) or
        len(name.encode('utf-8')) > 255
    ):
        raise ValueError('invalid name')
    return name


def createdesktopentry(root, kind, name, owner):

    kind = str(kind or '').strip().lower()
    if kind not in ('file', 'tier'):
        raise ValueError('invalid item type')
    name = desktopitemname(name)
    root = os.path.abspath(str(root or ''))
    if not root.startswith('/'):
        raise ValueError('invalid desktop tier')

    rootfd = None
    createdfd = None
    created = False
    try:
        rootstate = os.stat(root, follow_symlinks=False)
        if not statmodule.S_ISDIR(rootstate.st_mode):
            raise PermissionError('desktop tier is unavailable')
        owneruid, ownergid = int(owner[0]), int(owner[1])
        if rootstate.st_uid != owneruid or rootstate.st_gid != ownergid:
            raise PermissionError('desktop tier ownership is unsafe')

        directoryflags = (
            os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0) |
            getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_CLOEXEC', 0)
        )
        rootfd = os.open(root, directoryflags)
        openedstate = os.fstat(rootfd)
        if (
            openedstate.st_dev != rootstate.st_dev or
            openedstate.st_ino != rootstate.st_ino or
            not statmodule.S_ISDIR(openedstate.st_mode)
        ):
            raise PermissionError('desktop tier changed during creation')

        if kind == 'file':
            fileflags = (
                os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_CLOEXEC', 0)
            )
            createdfd = os.open(name, fileflags, 0o600, dir_fd=rootfd)
            created = True
            os.fchown(createdfd, owneruid, ownergid)
            os.fchmod(createdfd, 0o600)
            os.fsync(createdfd)
        else:
            os.mkdir(name, 0o700, dir_fd=rootfd)
            created = True
            createdfd = os.open(name, directoryflags, dir_fd=rootfd)
            os.fchown(createdfd, owneruid, ownergid)
            os.fchmod(createdfd, 0o700)
            os.fsync(createdfd)

        os.fsync(rootfd)
        return os.path.join(root, name)
    except FileExistsError:
        raise FileExistsError('name already exists')
    except Exception:
        if created and rootfd is not None:
            try:
                if kind == 'tier':
                    os.rmdir(name, dir_fd=rootfd)
                else:
                    os.unlink(name, dir_fd=rootfd)
            except OSError:
                pass
        raise
    finally:
        if createdfd is not None:
            os.close(createdfd)
        if rootfd is not None:
            os.close(rootfd)


def handledesktopcreate(request):

    permittedfields = {
        'action', 'op', 'kind', 'name', '_peer_checked', '_peer',
        '_peer_pid', '_peer_uid', '_peer_gid',
    }
    if set(request) - permittedfields:
        return {'status': 'error', 'message': 'unexpected desktop field'}
    peer = request.get('_peer', {})
    try:
        if peer.get('domain') != 'expanse' or not sessionidentityfor(peer.get('pid', 0)):
            raise PermissionError('desktop session ownership unavailable')
        username, _credentialhash = authbroker.read_credentials(MASTERFILE)
        username = authbroker.canonicalize_username(username)
        root = os.path.join('/master', username, 'expanse')
        path = createdesktopentry(
            root, request.get('kind'), request.get('name'),
            (DESKTOPUID, DESKTOPGID),
        )
        return {
            'status': 'ok',
            'kind': str(request.get('kind')).strip().lower(),
            'path': path,
        }
    except (FileExistsError, OSError, TypeError, ValueError, PermissionError) as error:
        return {'status': 'error', 'message': str(error).lower() or 'creation failed'}
    except Exception as error:
        print(f'> operations server desktop create error {error}', file=sys.stderr)
        return {'status': 'error', 'message': 'creation failed'}


def desktoprelativeparts(value):

    relative = str(value or '')
    if (
        not relative or relative.startswith('/') or
        len(relative.encode('utf-8')) > 4096 or
        any(character in relative for character in ('\x00', '\n', '\r'))
    ):
        raise ValueError('invalid desktop item')
    parts = relative.split('/')
    if any(not part or part in ('.', '..') for part in parts):
        raise ValueError('invalid desktop item')
    if any(len(part.encode('utf-8')) > 255 for part in parts):
        raise ValueError('invalid desktop item')
    return parts


def renamedesktopentry(root, relative, name, owner):

    parts = desktoprelativeparts(relative)
    name = desktopitemname(name)
    root = os.path.abspath(str(root or ''))
    if not root.startswith('/'):
        raise ValueError('invalid desktop tier')

    owneruid, ownergid = int(owner[0]), int(owner[1])
    directoryflags = (
        os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0) |
        getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_CLOEXEC', 0)
    )
    descriptors = []
    try:
        rootstate = os.stat(root, follow_symlinks=False)
        if (
            not statmodule.S_ISDIR(rootstate.st_mode) or
            rootstate.st_uid != owneruid or rootstate.st_gid != ownergid
        ):
            raise PermissionError('desktop tier ownership is unsafe')
        rootfd = os.open(root, directoryflags)
        descriptors.append(rootfd)
        openedstate = os.fstat(rootfd)
        if (
            openedstate.st_dev != rootstate.st_dev or
            openedstate.st_ino != rootstate.st_ino
        ):
            raise PermissionError('desktop tier changed during rename')

        parentfd = rootfd
        for component in parts[:-1]:
            parentfd = os.open(component, directoryflags, dir_fd=parentfd)
            descriptors.append(parentfd)
            parentstate = os.fstat(parentfd)
            if (
                not statmodule.S_ISDIR(parentstate.st_mode) or
                parentstate.st_uid != owneruid or parentstate.st_gid != ownergid
            ):
                raise PermissionError('desktop item ownership is unsafe')

        source = parts[-1]
        sourcestate = os.stat(source, dir_fd=parentfd, follow_symlinks=False)
        if (
            statmodule.S_ISLNK(sourcestate.st_mode) or
            not (
                statmodule.S_ISREG(sourcestate.st_mode) or
                statmodule.S_ISDIR(sourcestate.st_mode)
            ) or
            sourcestate.st_uid != owneruid or sourcestate.st_gid != ownergid
        ):
            raise PermissionError('desktop item ownership is unsafe')

        if source != name:
            library = ctypes.CDLL(None, use_errno=True)
            operation = getattr(library, 'renameat2', None)
            if operation is None:
                raise OSError(errno.ENOSYS, 'safe rename is unavailable')
            operation.argtypes = (
                ctypes.c_int, ctypes.c_char_p,
                ctypes.c_int, ctypes.c_char_p, ctypes.c_uint,
            )
            operation.restype = ctypes.c_int
            if operation(
                parentfd, os.fsencode(source),
                parentfd, os.fsencode(name), 1,
            ) != 0:
                number = ctypes.get_errno()
                if number in (errno.EEXIST, errno.ENOTEMPTY):
                    raise FileExistsError('name already exists')
                raise OSError(number, os.strerror(number))
            os.fsync(parentfd)

        renamedparts = [*parts[:-1], name]
        return os.path.join(root, *renamedparts)
    except FileNotFoundError:
        raise FileNotFoundError('desktop item no longer exists')
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def handledesktoprename(request):

    permittedfields = {
        'action', 'op', 'relative', 'name', '_peer_checked', '_peer',
        '_peer_pid', '_peer_uid', '_peer_gid',
    }
    if set(request) - permittedfields:
        return {'status': 'error', 'message': 'unexpected desktop field'}
    peer = request.get('_peer', {})
    try:
        if peer.get('domain') != 'expanse' or not sessionidentityfor(peer.get('pid', 0)):
            raise PermissionError('desktop session ownership unavailable')
        username, _credentialhash = authbroker.read_credentials(MASTERFILE)
        username = authbroker.canonicalize_username(username)
        root = os.path.join('/master', username, 'expanse')
        path = renamedesktopentry(
            root, request.get('relative'), request.get('name'),
            (DESKTOPUID, DESKTOPGID),
        )
        return {'status': 'ok', 'path': path}
    except (FileExistsError, FileNotFoundError, OSError, TypeError, ValueError, PermissionError) as error:
        return {'status': 'error', 'message': str(error).lower() or 'rename failed'}
    except Exception as error:
        print(f'> operations server desktop rename error {error}', file=sys.stderr)
        return {'status': 'error', 'message': 'rename failed'}


def spawnsandboxed(path, arguments, profile, environment, *, name, state='starting'):

    command = [path, *arguments]
    process = popenisolated(
        command,
        softwarepath=path,
        logpath=softwarelogpath(path),
        security_profile=profile,
        preexec_fn=(
            dropchromiumidentity if profile == 'chromium'
            else dropsandboxidentity),
        start_new_session=True,
        env=environment,
    )
    record = processrecord(process.pid)
    if record is None:
        try:
            process.kill()
        except OSError:
            pass
        raise RuntimeError('could not bind process identity')
    info = {
        'name': name,
        'script': path,
        'log': softwarelogpath(path),
        'user': 'desktop',
        'mode': 'front',
        'state': state,
        '_broker_owned': True,
        '_process_identity': str(record['identity']),
    }
    return process, info


def handlelaunchcatalogue(request):

    permittedfields = {
        'action', 'op', 'path', 'args', 'name', 'log', 'environment',
        '_peer_checked', '_peer', '_peer_pid', '_peer_uid', '_peer_gid',
    }
    if set(request) - permittedfields:
        return {'status': 'error', 'message': 'unexpected launch field'}
    path = str(request.get('path') or '')
    policy = APPLICATIONCATALOGUE.get(path)
    if policy is None:
        return {'status': 'error', 'message': 'catalogue entry denied'}
    try:
        requestedname = str(request.get('name') or policy['name'])
        requestedlog = str(request.get('log') or softwarelogpath(path))
        if requestedname != policy['name'] or requestedlog != softwarelogpath(path):
            raise ValueError('catalogue metadata denied')
        arguments = cataloguearguments(policy['arguments'], request.get('args', []))
        environment = applicationenvironment(request.get('environment', {}), policy)
        process, info = spawnsandboxed(
            path, arguments, policy['profile'], environment,
            name=policy['name'])
        session = sessionidentityfor(request['_peer']['pid'])
        if not session:
            raise PermissionError('session ownership unavailable')
        info['_owner_pid'] = int(request['_peer']['pid'])
        info['_owner_started'] = int(request['_peer']['started'])
        info['_session_identity'] = session
        if not recordstart(process.pid, process, info, arguments):
            raise RuntimeError('operation registration failed')
        return {'status': 'ok', 'pid': process.pid, 'profile': policy['profile']}
    except (OSError, ValueError, TypeError, PermissionError) as error:
        return {'status': 'error', 'message': str(error) or 'catalogue launch denied'}
    except Exception as error:
        print(f'> operations server catalogue launch error {error}', file=sys.stderr)
        return {'status': 'error', 'message': 'catalogue launch failed'}


def handlecataloguelist(request):

    """Return public application metadata without exposing launch authority."""

    try:
        if set(request) - {
            'action', 'op', '_peer_checked', '_peer', '_peer_pid',
            '_peer_uid', '_peer_gid',
        }:
            raise ValueError('unexpected catalogue list field')
        running = {}
        for info in activeoperations().values():
            path = os.path.normpath(str(info.get('script') or ''))
            running[path] = running.get(path, 0) + 1
        applications = []
        for path, policy in sorted(
                APPLICATIONCATALOGUE.items(),
                key=lambda item: str(item[1].get('name') or '').casefold()):
            name = str(policy.get('name') or '').strip().lower()
            applications.append({
                'name': name,
                'path': path,
                'profile': str(policy.get('profile') or '').strip().lower(),
                'handler': str(policy.get('arguments') or 'none').strip().lower(),
                'startup': name in PROCEDURECATALOGUE,
                'running': int(running.get(os.path.normpath(path), 0)),
            })
        return {'status': 'ok', 'applications': applications}
    except (OSError, ValueError, TypeError) as error:
        return {'status': 'error', 'message': str(error).lower()}
    except Exception as error:
        print(f'> operations server catalogue list error {error}', file=sys.stderr)
        return {'status': 'error', 'message': 'catalogue list failed'}


def readstartupoperations(path=None):

    path = STARTUPFILE if path is None else str(path)

    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, 'O_CLOEXEC', 0) |
            getattr(os, 'O_NOFOLLOW', 0),
        )
    except FileNotFoundError:
        return []

    try:
        metadata = os.fstat(descriptor)
        if (
            not statmodule.S_ISREG(metadata.st_mode) or
            metadata.st_nlink != 1 or metadata.st_size > 65536 or
            metadata.st_mode & (statmodule.S_IWGRP | statmodule.S_IWOTH)
        ):
            raise PermissionError('unsafe startup configuration')
        content = os.read(descriptor, 65537)
    finally:
        os.close(descriptor)

    if len(content) > 65536:
        raise ValueError('startup configuration is too large')
    lines = [
        line.strip()
        for line in content.decode('utf-8', errors='strict').splitlines()
        if line.strip() and not line.lstrip().startswith('#')
    ]
    if len(lines) % 2:
        raise ValueError('startup configuration is incomplete')
    bypath = {
        os.path.normpath(policy['path']): name
        for name, policy in PROCEDURECATALOGUE.items()
    }
    entries = []
    seen = set()
    for index in range(0, len(lines), 2):
        storedpath = os.path.normpath(lines[index])
        name = bypath.get(storedpath)
        mode = lines[index + 1].strip().lower()
        if name is None or mode not in ('front', 'behind') or name in seen:
            raise ValueError('startup configuration contains a denied operation')
        seen.add(name)
        entries.append({
            'software': name,
            'path': PROCEDURECATALOGUE[name]['path'],
            'mode': mode,
        })
    return entries


def writestartupoperations(entries, path=None):

    path = STARTUPFILE if path is None else str(path)

    directory = os.path.dirname(path)
    os.makedirs(directory, mode=0o755, exist_ok=True)
    lines = []
    for entry in entries:
        name = str(entry.get('software') or '').strip().lower()
        policy = PROCEDURECATALOGUE.get(name)
        mode = str(entry.get('mode') or '').strip().lower()
        if policy is None or mode not in ('front', 'behind'):
            raise ValueError('startup operation denied')
        lines.extend((policy['path'], mode))
    content = (''.join(line + '\n' for line in lines)).encode('utf-8')
    temporary = '{}.new.{}.{}'.format(path, os.getpid(), threading.get_ident())
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL |
            getattr(os, 'O_CLOEXEC', 0) | getattr(os, 'O_NOFOLLOW', 0),
            0o644,
        )
        try:
            offset = 0
            while offset < len(content):
                written = os.write(descriptor, content[offset:])
                if written <= 0:
                    raise OSError('short startup configuration write')
                offset += written
            os.fchmod(descriptor, 0o644)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(temporary, path)
        directorydescriptor = os.open(
            directory,
            os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0) |
            getattr(os, 'O_CLOEXEC', 0),
        )
        try:
            os.fsync(directorydescriptor)
        finally:
            os.close(directorydescriptor)
    finally:
        try:
            os.unlink(temporary)
        except OSError:
            pass


def handlestartupconfiguration(request, action):

    try:
        allowedfields = {
            'action', 'op', '_peer_checked', '_peer', '_peer_pid',
            '_peer_uid', '_peer_gid',
        }
        if action != 'STARTUP_LIST':
            allowedfields.add('software')
        if action in ('STARTUP_ADD', 'STARTUP_CHANGE'):
            allowedfields.add('mode')
        if set(request) - allowedfields:
            raise ValueError('unexpected startup field')

        entries = readstartupoperations()
        if action == 'STARTUP_LIST':
            return {'status': 'ok', 'operations': entries}

        software = str(request.get('software') or '').strip().lower()
        if software not in PROCEDURECATALOGUE:
            raise ValueError('startup software denied')
        position = next((
            index for index, entry in enumerate(entries)
            if entry.get('software') == software
        ), None)

        if action == 'STARTUP_ADD':
            if position is not None:
                raise ValueError('startup operation already exists')
            mode = str(request.get('mode') or '').strip().lower()
            if mode not in ('front', 'behind'):
                raise ValueError('startup mode denied')
            entries.append({'software': software, 'mode': mode})
        elif action == 'STARTUP_REMOVE':
            if position is None:
                raise ValueError('startup operation not found')
            del entries[position]
        elif action == 'STARTUP_CHANGE':
            if position is None:
                raise ValueError('startup operation not found')
            mode = str(request.get('mode') or '').strip().lower()
            if mode not in ('front', 'behind'):
                raise ValueError('startup mode denied')
            entries[position]['mode'] = mode
        else:
            raise ValueError('startup action denied')

        writestartupoperations(entries)
        return {'status': 'ok', 'operations': readstartupoperations()}
    except (OSError, ValueError, TypeError, UnicodeError, PermissionError) as error:
        return {'status': 'error', 'message': str(error).lower()}
    except Exception as error:
        print(f'> operations server startup configuration error {error}', file=sys.stderr)
        return {'status': 'error', 'message': 'startup configuration failed'}


def vmtestfields(request, allowed):

    internal = {
        '_peer_checked', '_peer', '_peer_pid', '_peer_uid', '_peer_gid',
    }
    if not vmtestenabled():
        raise PermissionError('VM test broker is disabled')
    if set(request) - set(allowed) - internal:
        raise ValueError('unexpected VM test field')


def vmtestenvironment():

    environment = {
        key: value for key, value in os.environ.items()
        if key in ('LANG', 'LC_ALL', 'LC_CTYPE', 'TZ', 'TERM', 'COLORTERM')
    }
    environment.update({
        'HOME': '/',
        'PATH': '/the one/software/python/bin:/the one/drivers/tools',
        'T1OS_VM_TEST': '1',
    })
    return environment


def vmtesttext(value):

    raw = bytes(value or b'')
    truncated = len(raw) > VMTESTMAXOUTPUT
    if truncated:
        raw = raw[:VMTESTMAXOUTPUT]
    return raw.decode('utf-8', errors='replace'), truncated


def vmtestbrickresult(stdout):

    for line in reversed(str(stdout).splitlines()):
        try:
            result = json.loads(line.strip())
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(result, dict) and result.get('format') == 1:
            return result
    return None


def handlevmtestbrickexecute(request):

    process = None
    started = time.monotonic()
    try:
        vmtestfields(request, {'action', 'op', 'directive', 'timeout_seconds'})
        directive = request.get('directive')
        if not isinstance(directive, str):
            raise ValueError('directive must be text')
        directive = directive.strip()
        if (
            not directive or len(directive) > VMTESTMAXDIRECTIVE or
            '\x00' in directive
        ):
            raise ValueError('directive exceeds the VM test limit')
        timeout = request.get('timeout_seconds', 180)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise ValueError('timeout must be numeric')
        timeout = max(1, min(600, int(timeout)))
        path = '/the one/build/brick/brick.py'
        process = popensecured(
            [path, 'execute', directive],
            softwarepath=path,
            security_profile='brick',
            preexec_fn=dropsandboxidentity,
            start_new_session=True,
            cwd='/',
            env=vmtestenvironment(),
            # T1OS deliberately exposes its device tree at
            # /the one/drivers/nodes instead of the conventional device root.
            # subprocess.DEVNULL resolves through Python's standard null-device
            # path and therefore cannot be used here. A closed pipe gives the
            # Brick worker deterministic EOF without opening any device node.
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            out, err = process.communicate(timeout=timeout)
            timedout = False
        except subprocess.TimeoutExpired:
            process.kill()
            out, err = process.communicate()
            timedout = True
        stdout, stdouttruncated = vmtesttext(out)
        stderr, stderrtruncated = vmtesttext(err)
        result = vmtestbrickresult(stdout)
        passed = bool(
            not timedout and process.returncode == 0 and
            isinstance(result, dict) and result.get('passed') and
            not stdouttruncated and not stderrtruncated
        )
        return {
            'status': 'ok',
            'passed': passed,
            'exit_code': int(process.returncode),
            'timed_out': timedout,
            'duration_seconds': round(time.monotonic() - started, 6),
            'brick_path': path,
            'source': 'deployed',
            'result': result,
            'stdout': stdout,
            'stderr': stderr,
            'stdout_truncated': stdouttruncated,
            'stderr_truncated': stderrtruncated,
        }
    except (OSError, ValueError, TypeError, PermissionError) as error:
        return {'status': 'error', 'message': str(error) or 'VM test Brick execution denied'}
    except Exception as error:
        print(f'> operations server VM test Brick error {error}', file=sys.stderr)
        return {'status': 'error', 'message': 'VM test Brick execution failed'}


def handlevmtestlaunch(request):

    try:
        vmtestfields(request, {'action', 'op', 'application'})
        application = str(request.get('application') or '')
        applications = {
            'brick': (
                '/the one/build/brick/brick.py', [], {'BRICK_WINDOW': '1'}),
            'settings': (
                '/the one/build/settings/settings.py', [],
                {'T1OS_SETTINGS_SECTION': 'python'}),
            'settings-display': (
                '/the one/build/settings/settings.py', [],
                {'T1OS_SETTINGS_SECTION': 'display'}),
            'player': (
                '/the one/build/player/player.py', [VMTESTMEDIA], {}),
            'player-audio': (
                '/the one/build/player/player.py', [VMTESTAUDIO], {}),
            'viewer': (
                '/the one/build/viewer/viewer.py', [VMTESTIMAGE], {}),
            'write': (
                '/the one/build/write/write.py', [VMTESTTEXT], {}),
            'chromium': (
                '/the one/build/chromium/chromium.py', [], {}),
            'array-opengl': (
                '/the one/build/array/array.py',
                ['--open-item', VMTESTOPENGL], {}),
            'creep-self-test': (
                '/the one/build/brick/brick.py',
                ['--run-file', VMTESTCREEP, '--self-test'],
                {'BRICK_WINDOW': '0'}),
        }
        if application not in applications:
            raise ValueError('VM test application denied')
        path, requestedarguments, requestedenvironment = applications[application]
        fixtures = {
            'player': VMTESTMEDIA,
            'player-audio': VMTESTAUDIO,
            'viewer': VMTESTIMAGE,
            'write': VMTESTTEXT,
            'array-opengl': VMTESTOPENGL,
            'creep-self-test': VMTESTCREEP,
        }
        fixture = fixtures.get(application)
        if fixture and not os.path.isfile(fixture):
            raise FileNotFoundError(fixture)
        policy = APPLICATIONCATALOGUE[path]
        arguments = cataloguearguments(policy['arguments'], requestedarguments)
        environment = applicationenvironment(requestedenvironment, policy)
        environment['T1OS_VM_TEST'] = '1'
        process, info = spawnsandboxed(
            path, arguments, policy['profile'], environment,
            name=policy['name'])
        peer = request['_peer']
        info['_owner_pid'] = int(peer['pid'])
        info['_owner_started'] = int(peer['started'])
        info['_session_identity'] = 'vm-test'
        info['_vm_test_application'] = application
        if not recordstart(process.pid, process, info, arguments):
            raise RuntimeError('VM test operation registration failed')
        return {
            'status': 'ok',
            'passed': True,
            'pid': int(process.pid),
            'profile': policy['profile'],
            'application_path': path,
            'media_path': fixture if application in ('player', 'player-audio') else None,
            'source': 'deployed',
        }
    except (OSError, ValueError, TypeError, PermissionError) as error:
        return {'status': 'error', 'message': str(error) or 'VM test launch denied'}
    except Exception as error:
        print(f'> operations server VM test launch error {error}', file=sys.stderr)
        return {'status': 'error', 'message': 'VM test launch failed'}


def handlevmtestclose(request):

    try:
        vmtestfields(request, {'action', 'op'})
        peer = request['_peer']
        if not peerstillvalid(peer):
            raise PermissionError('VM test owner is no longer valid')
        reaptracked()
        with STATELOCK:
            entries = [
                dict(entry) for entry in OPMETA.values()
                if (
                    str(entry.get('_session_identity', '')) == 'vm-test' and
                    int(entry.get('_owner_pid', -1)) == int(peer['pid']) and
                    int(entry.get('_owner_started', -1)) == int(peer['started'])
                )
            ]
        records = processrecords()
        targets = []
        for entry in entries:
            pid = int(entry.get('pid', 0) or 0)
            record = records.get(str(pid))
            if (
                pid <= 1 or record is None or
                str(record.get('identity', '')) !=
                    str(entry.get('_process_identity', ''))
            ):
                continue
            targets.extend(processtree(pid, records=records, registered=()))
        signalled = []
        for target in reversed(list(dict.fromkeys(targets))):
            expected = records.get(str(target))
            fresh = processrecord(int(target))
            if (
                expected is None or fresh is None or
                str(expected.get('identity', '')) !=
                    str(fresh.get('identity', '')) or
                processdomain(int(target)) not in (
                    'desktop', 'brick', 'video', 'settings', 'chromium',
                    'picker', 'untrusted', 'snap')
            ):
                continue
            try:
                os.kill(int(target), signal.SIGTERM)
                signalled.append(int(target))
            except ProcessLookupError:
                pass
        return {
            'status': 'ok',
            'passed': True,
            'signalled': signalled,
            'source': 'deployed',
        }
    except (OSError, ValueError, TypeError, PermissionError) as error:
        return {'status': 'error', 'message': str(error) or 'VM test close denied'}
    except Exception as error:
        print(f'> operations server VM test close error {error}', file=sys.stderr)
        return {'status': 'error', 'message': 'VM test close failed'}


def vmtestsessionidentity():

    descriptor = os.open(
        SESSIONIDENTITYFILE,
        os.O_RDONLY | getattr(os, 'O_CLOEXEC', 0) |
        getattr(os, 'O_NOFOLLOW', 0),
    )
    try:
        metadata = os.fstat(descriptor)
        if (
            not statmodule.S_ISREG(metadata.st_mode) or
            metadata.st_uid != 0 or metadata.st_gid != DESKTOPGID or
            statmodule.S_IMODE(metadata.st_mode) != 0o640 or
            metadata.st_nlink != 1 or
            not 0 < metadata.st_size <= 1024
        ):
            raise PermissionError('unsafe session identity')
        payload = os.read(descriptor, 1025)
        if len(payload) != metadata.st_size:
            raise ValueError('session identity changed while reading')
        identity = json.loads(payload.decode('utf-8'))
        if (
            not isinstance(identity, dict) or
            set(identity) != {'format', 'username'} or
            isinstance(identity.get('format'), bool) or
            identity.get('format') != 1
        ):
            raise ValueError('invalid session identity')
        username = str(identity.get('username') or '')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,31}', username):
            raise ValueError('invalid session username')
        return username
    finally:
        os.close(descriptor)


def vmtestliveprocess(domain, uid, records=None):

    expected_domain = str(domain)
    expected_uid = int(uid)
    snapshot = processrecords() if records is None else dict(records)

    for pidtext, record in snapshot.items():
        try:
            pid = int(pidtext)
            if (
                str(record.get('state', '')).upper() == 'Z' or
                int(record.get('uid', -1)) != expected_uid or
                int(record.get('gid', -1)) != expected_uid or
                processdomain(pid) != expected_domain
            ):
                continue
            fresh = processrecord(pid)
            if (
                fresh is not None and
                str(fresh.get('state', '')).upper() != 'Z' and
                int(fresh.get('uid', -1)) == expected_uid and
                int(fresh.get('gid', -1)) == expected_uid and
                str(fresh.get('identity', '')) ==
                    str(record.get('identity', '')) and
                processdomain(pid) == expected_domain
            ):
                return True
        except (OSError, ValueError, TypeError):
            continue

    return False


def vmtestsecurejson(path, maximum, owners):

    allowedowners = {
        (int(owner[0]), int(owner[1])) for owner in tuple(owners)
    }

    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, 'O_CLOEXEC', 0) |
        getattr(os, 'O_NOFOLLOW', 0),
    )
    try:
        metadata = os.fstat(descriptor)
        if (
            not statmodule.S_ISREG(metadata.st_mode) or
            (metadata.st_uid, metadata.st_gid) not in allowedowners or
            metadata.st_nlink != 1 or
            statmodule.S_IMODE(metadata.st_mode) & 0o022 or
            not 0 < metadata.st_size <= int(maximum)
        ):
            raise PermissionError('unsafe broker status file')
        payload = os.read(descriptor, int(maximum) + 1)
        if len(payload) != metadata.st_size:
            raise ValueError('broker status file changed while reading')
        value = json.loads(payload.decode('utf-8'))
        if not isinstance(value, dict):
            raise ValueError('invalid broker status document')
        return value
    finally:
        os.close(descriptor)


def vmtestlockscreenready():

    receipt = vmtestsecurejson(LOCKSCREENREADYPATH, 65536, ((0, 0),))
    lifecycle = vmtestsecurejson(
        LOCKSCREENLIFECYCLEPATH, 4096, ((DESKTOPUID, DESKTOPGID),))
    marker = vmtestsecurejson(
        LOCKSCREENPOSTHANDOFFPATH, 4096,
        ((0, 0), (0, DESKTOPGID), (DESKTOPUID, DESKTOPGID)))

    try:
        windowserver_pid = int(receipt.get('windowserver_pid', 0))
        frame_sequence = int(receipt.get('frame_sequence', 0))
        topmost_window = int(receipt.get('topmost_window', 0))
        windows = [int(value) for value in receipt.get('windows', [])]
        lockscreen_pid = int(marker.get('pid', 0))
        marker_windowserver_pid = int(marker.get('windowserver_pid', 0))
        marker_sequence = int(marker.get('frame_sequence', 0))
        lifecycle_pid = int(lifecycle.get('pid', 0))
        windowserver_started = int(receipt.get('windowserver_starttime', 0))
        presenter_pid = int(receipt.get('presenter_pid', 0))
        presenter_started = int(receipt.get('presenter_starttime', 0))
    except (ValueError, TypeError):
        raise ValueError('invalid lock-screen receipt identity')

    if (
        isinstance(receipt.get('format'), bool) or
        receipt.get('format') != 1 or
        windowserver_pid <= 1 or
        windowserver_started <= 0 or
        frame_sequence <= 0 or
        topmost_window <= 0 or
        not windows or len(windows) > 256 or
        topmost_window not in windows or
        not str(receipt.get('server', '')).strip() or
        str(receipt.get('role', '')) != 'lockscreen' or
        str(receipt.get('topmost_role', '')) != 'lockscreen' or
        str(receipt.get('backend', '')).strip().lower() not in
            ('opengl', 'framebuffer', 'kms-framebuffer') or
        receipt.get('full_coverage') is not True or
        receipt.get('gpu_failed') is not False or
        receipt.get('boot_active') is not False or
        marker.get('format') != 1 or marker.get('state') != 'ready' or
        marker.get('physically_verified') is not True or
        marker.get('boot_active') is not False or
        lockscreen_pid <= 1 or lifecycle_pid != lockscreen_pid or
        lifecycle.get('format') != 1 or lifecycle.get('state') != 'ready' or
        marker_windowserver_pid != windowserver_pid or
        str(marker.get('server', '')).strip() !=
            str(receipt.get('server', '')).strip() or
        str(marker.get('backend', '')).strip().lower() !=
            str(receipt.get('backend', '')).strip().lower() or
        marker_sequence <= 0 or frame_sequence < marker_sequence or
        presenter_pid != lockscreen_pid or presenter_started <= 0 or
        receipt.get('presenter_domain') != 'lockscreen'
    ):
        raise ValueError('lock-screen receipt is not current presentation proof')

    lockscreen = processrecord(lockscreen_pid)
    if (
        lockscreen is None or
        str(lockscreen.get('state', '')).upper() == 'Z' or
        int(lockscreen.get('uid', -1)) != DESKTOPUID or
        int(lockscreen.get('gid', -1)) != DESKTOPGID or
        processdomain(lockscreen_pid) != 'lockscreen' or
        int(lockscreen.get('started', 0)) != presenter_started
    ):
        return False
    freshlockscreen = processrecord(lockscreen_pid)
    if (
        freshlockscreen is None or
        str(freshlockscreen.get('state', '')).upper() == 'Z' or
        str(freshlockscreen.get('identity', '')) !=
            str(lockscreen.get('identity', '')) or
        int(freshlockscreen.get('uid', -1)) != DESKTOPUID or
        int(freshlockscreen.get('gid', -1)) != DESKTOPGID or
        processdomain(lockscreen_pid) != 'lockscreen' or
        int(freshlockscreen.get('started', 0)) != presenter_started
    ):
        return False

    first = processrecord(windowserver_pid)
    if (
        first is None or
        str(first.get('state', '')).upper() == 'Z' or
        int(first.get('uid', -1)) != 0 or
        processdomain(windowserver_pid) != 'window' or
        int(first.get('started', 0)) != windowserver_started
    ):
        return False
    fresh = processrecord(windowserver_pid)
    return bool(
        fresh is not None and
        str(fresh.get('state', '')).upper() != 'Z' and
        int(fresh.get('uid', -1)) == 0 and
        str(fresh.get('identity', '')) == str(first.get('identity', '')) and
        processdomain(windowserver_pid) == 'window' and
        int(fresh.get('started', 0)) == windowserver_started
    )


def vmtestloginready():

    marker = vmtestsecurejson(LOGINREADYPATH, 4096, ((0, 0),))

    try:
        pid = int(marker.get('pid', 0))
        winid = int(marker.get('winid', 0))
        username = authbroker.canonicalize_username(marker.get('username', ''))
    except (ValueError, TypeError, authbroker.AuthenticationError):
        return False

    record = processrecord(pid)
    return bool(
        marker.get('format') == 1 and marker.get('state') == 'ready' and
        pid > 1 and winid > 0 and username and record is not None and
        str(record.get('state', '')).upper() != 'Z' and
        int(record.get('uid', -1)) == 0 and processdomain(pid) == 'startup'
    )


def handlevmteststatus(request):

    try:
        vmtestfields(request, {'action', 'op'})
        peer = request['_peer']
        reaptracked()
        with STATELOCK:
            entries = [
                dict(entry) for entry in OPMETA.values()
                if (
                    str(entry.get('_session_identity', '')) == 'vm-test' and
                    int(entry.get('_owner_pid', -1)) == int(peer['pid']) and
                    int(entry.get('_owner_started', -1)) == int(peer['started'])
                )
            ]
        expected = {
            'brick': 'brick',
            'settings': 'settings',
            'settings-display': 'settings',
            'player': 'video',
            'player-audio': 'video',
            'viewer': 'desktop',
            'write': 'desktop',
            'chromium': 'chromium',
            'array-opengl': 'desktop',
        }
        applications = {name: False for name in expected}
        playerpid = 0
        for entry in entries:
            application = str(entry.get('_vm_test_application') or '')
            if application not in expected:
                continue
            pid = int(entry.get('pid', 0) or 0)
            record = processrecord(pid)
            if (
                record is not None and
                str(record.get('identity', '')) ==
                    str(entry.get('_process_identity', '')) and
                int(record.get('uid', -1)) == DESKTOPUID and
                processdomain(pid) == expected[application]
            ):
                applications[application] = True
                if application == 'player':
                    playerpid = pid
        # The session identity is intentionally published only after login.
        # The GUI harness also needs to distinguish an existing account from
        # first-run setup while the login screen is still active.  Operations
        # already owns credential-file access, so expose only the canonical
        # username here; never return the credential hash.
        records = processrecords()
        try:
            sessionusername = vmtestsessionidentity()
        except (OSError, UnicodeError, ValueError, TypeError):
            sessionusername = ''
        sessionactive = bool(
            sessionusername and
            vmtestliveprocess('expanse', DESKTOPUID, records=records)
        )
        try:
            lockscreenready = vmtestlockscreenready()
        except (OSError, UnicodeError, ValueError, TypeError, PermissionError):
            lockscreenready = False
        try:
            loginready = vmtestloginready()
        except (OSError, UnicodeError, ValueError, TypeError, PermissionError):
            loginready = False
        username = sessionusername
        if not username:
            try:
                configuredusername, _credentialhash = \
                    authbroker.read_credentials(MASTERFILE)
                username = authbroker.canonicalize_username(
                    configuredusername)
            except (
                OSError, UnicodeError, ValueError, TypeError,
                authbroker.AuthenticationError,
            ):
                username = ''
        terminalresult = ''
        try:
            resultstat = os.stat(VMTESTTERMINALRESULT, follow_symlinks=False)
            if (
                statmodule.S_ISREG(resultstat.st_mode) and
                int(resultstat.st_uid) == DESKTOPUID and
                0 < int(resultstat.st_size) <= 1024
            ):
                with open(
                    VMTESTTERMINALRESULT, 'r', encoding='utf-8',
                    errors='replace') as stream:
                    terminalresult = stream.read(1024)
        except OSError:
            pass
        playerstatus = {}
        mediaruntime = {}
        try:
            runtimestat = os.stat('/.ephemeral/media', follow_symlinks=False)
            mediaruntime = {
                'directory': statmodule.S_ISDIR(runtimestat.st_mode),
                'uid': int(runtimestat.st_uid),
                'gid': int(runtimestat.st_gid),
                'mode': format(statmodule.S_IMODE(runtimestat.st_mode), '04o'),
            }
        except OSError:
            pass
        try:
            playerstatuspath = VMTESTPLAYERSTATUS.format(playerpid)
            playerstat = os.stat(playerstatuspath, follow_symlinks=False)
            if (
                statmodule.S_ISREG(playerstat.st_mode) and
                int(playerstat.st_uid) == DESKTOPUID and
                int(playerstat.st_size) > 0 and
                int(playerstat.st_size) <= 4096 and
                not (int(playerstat.st_mode) & 0o022)
            ):
                with open(
                    playerstatuspath, 'r', encoding='utf-8',
                    errors='strict') as stream:
                    candidate = json.load(stream)
                if (
                    isinstance(candidate, dict) and
                    candidate.get('format') == 1 and
                    int(candidate.get('pid', 0)) == playerpid and
                    str(candidate.get('media_path', '')) == VMTESTMEDIA
                ):
                    playerstatus = {
                        'pid': playerpid,
                        'media_path': VMTESTMEDIA,
                        'media_kind': str(candidate.get('media_kind', ''))[:16],
                        'state': str(candidate.get('state', ''))[:16],
                        'position': max(0.0, float(candidate.get('position', 0.0))),
                        'duration': max(0.0, float(candidate.get('duration', 0.0))),
                        'error': str(candidate.get('error', ''))[:512],
                        'frame_ready': candidate.get('frame_ready') is True,
                        'frame_width': max(0, int(candidate.get('frame_width', 0))),
                        'frame_height': max(0, int(candidate.get('frame_height', 0))),
                        'frame_number': max(0, int(candidate.get('frame_number', 0))),
                    }
        except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError):
            pass
        return {
            'status': 'ok',
            'source': 'broker-owned-guest-state',
            'has_user': bool(username),
            'username': username,
            'session_active': sessionactive,
            'exchange_ready': os.path.exists('/.ephemeral/exchange.sock'),
            'windowserver_ready': os.path.exists(
                '/.ephemeral/windowserver/accept.sock'),
            'lock_screen_ready': lockscreenready,
            'login_ready': loginready,
            'applications': applications,
            'terminal_fixture_result': terminalresult,
            'player_status': playerstatus,
            'media_runtime': mediaruntime,
        }
    except (OSError, ValueError, TypeError, PermissionError) as error:
        return {'status': 'error', 'message': str(error) or 'VM test status denied'}
    except Exception as error:
        print(f'> operations server VM test status error {error}', file=sys.stderr)
        return {'status': 'error', 'message': 'VM test status failed'}


def handleprocedurelaunch(request):

    """Launch one root-policy-selected procedure as an untrusted desktop task."""

    try:
        if set(request) - {
            'action', 'op', 'id', 'mode', '_peer_checked', '_peer',
            '_peer_pid', '_peer_uid', '_peer_gid',
        }:
            raise ValueError('unexpected procedure launch field')
        procedureid = str(request.get('id') or '').strip().lower()
        policy = PROCEDURECATALOGUE.get(procedureid)
        if policy is None:
            raise ValueError('procedure identifier denied')
        path = policy['path']
        mode = str(request.get('mode') or 'behind').strip().lower()
        if mode not in ('front', 'behind'):
            raise ValueError('procedure mode denied')
        # Re-open and bind the exact broker-owned catalogue object.  No path,
        # profile, argv, environment, log destination, or identity is accepted
        # from Procedures.
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, 'O_CLOEXEC', 0) |
            getattr(os, 'O_NOFOLLOW', 0),
        )
        try:
            metadata = os.fstat(descriptor)
            pathname = os.stat(path, follow_symlinks=False)
            if (
                not statmodule.S_ISREG(metadata.st_mode) or
                (metadata.st_dev, metadata.st_ino) !=
                    (pathname.st_dev, pathname.st_ino) or
                metadata.st_uid != 0 or metadata.st_nlink != 1 or
                metadata.st_mode & (statmodule.S_IWGRP | statmodule.S_IWOTH)
            ):
                raise PermissionError('unsafe procedure executable')
        finally:
            os.close(descriptor)

        process, info = spawnsandboxed(
            path, [], policy['profile'], applicationenvironment({}, policy),
            name=policy['name'],
        )
        info['mode'] = mode
        info['_owner_pid'] = int(request['_peer']['pid'])
        info['_owner_started'] = int(request['_peer']['started'])
        info['_session_identity'] = 'system-procedures'
        if not recordstart(process.pid, process, info, ()):
            process.kill()
            raise RuntimeError('operation registration failed')
        return {'status': 'ok', 'pid': process.pid, 'profile': policy['profile']}
    except (OSError, ValueError, TypeError, PermissionError) as error:
        return {'status': 'error', 'message': str(error) or 'procedure launch denied'}
    except Exception as error:
        print(f'> operations server procedure launch error {error}', file=sys.stderr)
        return {'status': 'error', 'message': 'procedure launch failed'}


def secretname(request):

    name = str(request.get('name') or request.get('service') or '')
    if not SERVICESECRETNAME.fullmatch(name):
        raise ValueError('service credential name denied')
    return name


def handleservicesecret(request, action):

    try:
        name = secretname(request)
        if action == 'SERVICE_SECRET_PUT':
            value = request.get('value', request.get('secret'))
            if not isinstance(value, str):
                raise ValueError('service credential value denied')
            encoded = value.encode('utf-8', errors='strict')
            if not 1 <= len(encoded) <= MAXIMUMSERVICESECRET or '\x00' in value:
                raise ValueError('service credential value denied')
            authbroker.store_service_secret(
                name, encoded, directory=SERVICESECRETDIRECTORY)
            return {'status': 'ok', 'stored': True}
        if action == 'SERVICE_SECRET_DELETE':
            try:
                authbroker.delete_service_secret(
                    name, directory=SERVICESECRETDIRECTORY)
                deleted = True
            except FileNotFoundError:
                deleted = False
            return {'status': 'ok', 'deleted': deleted}
        if action == 'SERVICE_SECRET_EXISTS':
            try:
                authbroker.load_service_secret(
                    name, directory=SERVICESECRETDIRECTORY)
                exists = True
            except FileNotFoundError:
                exists = False
            return {'status': 'ok', 'exists': exists}
        if action == 'SERVICE_SECRET_GET':
            secret = authbroker.load_service_secret(
                name, directory=SERVICESECRETDIRECTORY)
            return {'status': 'ok', 'value': secret.decode('utf-8', errors='strict')}
    except (OSError, ValueError, UnicodeError, authbroker.AuthenticationError) as error:
        return {'status': 'error', 'message': str(error) or 'service credential request failed'}
    return {'status': 'error', 'message': 'service credential action denied'}


def boundedpassword(request, key):

    value = request.get(key)
    if not isinstance(value, str):
        raise ValueError('password is required')
    if not (
        authbroker.MIN_NEW_PASSWORD_CHARS <= len(value)
        <= authbroker.MAX_PASSWORD_CHARS
    ):
        raise ValueError('password length denied')
    if any(character in value for character in ('\x00', '\n', '\r')):
        raise ValueError('password value denied')
    return value


def handlesettingsauth(request):

    try:
        password = boundedpassword(request, 'password')
        result = authbroker.authenticate_master(
            MASTERFILE, password, scope='settings:verify', migrate=True)
        if not result.ok:
            return {
                'status': 'error', 'message': 'authentication failed',
                'retry_after': float(result.retry_after or 0.0),
            }
        return {
            'status': 'ok', 'verified': True,
            'username': result.username, 'migrated': bool(result.migrated),
        }
    except (OSError, ValueError, authbroker.AuthenticationError):
        return {'status': 'error', 'message': 'authentication failed'}


def handlesessionauth(request):

    """Verify a lock-screen password without exposing credential storage."""

    try:
        password = boundedpassword(request, 'password')
        result = authbroker.authenticate_master(
            MASTERFILE, password, scope='session:unlock', migrate=True)
        if not result.ok:
            return {
                'status': 'ok', 'verified': False,
                'retry_after': float(result.retry_after or 0.0),
            }
        return {
            'status': 'ok', 'verified': True,
            'username': result.username, 'migrated': bool(result.migrated),
        }
    except (OSError, ValueError, authbroker.AuthenticationError):
        return {'status': 'error', 'message': 'authentication failed'}


def settingsimagepath(value, oldhome, newhome):

    value = str(value or '').strip()
    if not value:
        return ''
    absolute = os.path.normpath(value)
    if not absolute.startswith('/') or len(absolute.encode('utf-8')) > 4096:
        raise ValueError('master image path denied')
    extension = os.path.splitext(absolute)[1].lower()
    if extension not in ('.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif'):
        raise ValueError('master image type denied')
    if oldhome and absolute.startswith(oldhome + '/'):
        return os.path.join(newhome, os.path.relpath(absolute, oldhome))
    if not absolute.startswith('/master/'):
        raise ValueError('master image path denied')
    return absolute


def atomicjsonfile(path, value, mode=0o600, directorymode=0o700):

    directory = os.path.dirname(path)
    os.makedirs(directory, mode=directorymode, exist_ok=True)
    os.chmod(directory, directorymode)
    temporary = f'{path}.new.{os.getpid()}.{threading.get_ident()}'
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0),
        mode)
    try:
        data = (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode('utf-8')
        offset = 0
        while offset < len(data):
            written = os.write(descriptor, data[offset:])
            if written <= 0:
                raise OSError('short settings write')
            offset += written
        os.fchmod(descriptor, mode)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)


def writemastersettings(value, path=MASTERSETTINGSFILE):

    # This file contains only the enabled flag and the selected profile-image
    # path. Expanse and Settings run as uid 1000 and must be able to traverse
    # the broker-owned directory and read the broker-published snapshot.
    atomicjsonfile(
        path,
        value,
        mode=MASTERSETTINGSFILEMODE,
        directorymode=MASTERSETTINGSDIRECTORYMODE,
    )


def repairmastersettingspermissions(path=MASTERSETTINGSFILE):

    directory = os.path.dirname(path)

    if not os.path.lexists(path):
        return False

    directorystate = os.stat(directory, follow_symlinks=False)
    filestate = os.stat(path, follow_symlinks=False)

    if (
        not statmodule.S_ISDIR(directorystate.st_mode) or
        statmodule.S_ISLNK(directorystate.st_mode) or
        directorystate.st_uid != 0
    ):
        raise PermissionError('master settings directory is unsafe')

    if (
        not statmodule.S_ISREG(filestate.st_mode) or
        statmodule.S_ISLNK(filestate.st_mode) or
        filestate.st_uid != 0 or
        filestate.st_nlink != 1
    ):
        raise PermissionError('master settings file is unsafe')

    os.chmod(directory, MASTERSETTINGSDIRECTORYMODE)
    os.chmod(path, MASTERSETTINGSFILEMODE)
    return True


def handlesettingsaccountget(request):

    try:
        username, _ = authbroker.read_credentials(MASTERFILE)
        return {'status': 'ok', 'username': username}
    except Exception:
        return {'status': 'error', 'message': 'master account unavailable'}


def handlesettingsmasterupdate(request):

    """Authenticated account/profile transaction; no password hash escapes."""

    try:
        requested = authbroker.canonicalize_username(request.get('username'))
        newpassword = request.get('new_password', '')
        if not isinstance(newpassword, str):
            raise ValueError('new password denied')
        if newpassword:
            authbroker.validate_new_password(newpassword)
        useimage = request.get('use_master_image') is True
        oldname, oldhash = authbroker.read_credentials(MASTERFILE)
        accountchanged = requested != oldname or bool(newpassword)
        if accountchanged:
            current = boundedpassword(request, 'current_password')
            result = authbroker.authenticate_master(
                MASTERFILE, current,
                scope='settings:master-update', migrate=False)
            if not result.ok:
                return {
                    'status': 'error', 'message': 'authentication failed',
                    'retry_after': float(result.retry_after or 0.0),
                }
        replacement = authbroker.hash_password(newpassword) if newpassword else oldhash
        homebase = '/master'
        oldhome = os.path.join(homebase, oldname)
        newhome = os.path.join(homebase, requested)
        imagepath = settingsimagepath(
            request.get('image_path', ''), oldhome, newhome) if useimage else ''
        moved = False
        if requested != oldname:
            oldstat = os.stat(oldhome, follow_symlinks=False)
            if not statmodule.S_ISDIR(oldstat.st_mode) or os.path.lexists(newhome):
                raise ValueError('master home rename denied')
            os.rename(oldhome, newhome)
            moved = True
        try:
            authbroker.atomic_write_credentials(MASTERFILE, requested, replacement)
            writemastersettings({
                'use_master_image': useimage,
                'image_path': imagepath,
            })
            publishsessionidentity(MASTERFILE)
        except Exception:
            authbroker.atomic_write_credentials(MASTERFILE, oldname, oldhash)
            if moved and os.path.isdir(newhome) and not os.path.lexists(oldhome):
                os.rename(newhome, oldhome)
            try:
                publishsessionidentity(MASTERFILE)
            except Exception:
                pass
            raise
        return {
            'status': 'ok',
            'username': requested,
            'password_changed': bool(newpassword),
            'use_master_image': useimage,
            'image_path': imagepath,
        }
    except (OSError, ValueError, TypeError, authbroker.AuthenticationError) as error:
        return {'status': 'error', 'message': str(error) or 'master update failed'}


def handlesettingshostname(request):

    try:
        name = str(request.get('hostname') or '').strip().lower()
        if not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', name):
            raise ValueError('hostname denied')
        library = ctypes.CDLL(None, use_errno=True)
        encoded = name.encode('ascii')
        if library.sethostname(encoded, len(encoded)) != 0:
            number = ctypes.get_errno()
            raise OSError(number, os.strerror(number))
        path = '/the one/settings/terminal/name.txt'
        directory = os.path.dirname(path)
        os.makedirs(directory, mode=0o700, exist_ok=True)
        temporary = f'{path}.new.{os.getpid()}.{threading.get_ident()}'
        descriptor = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
            getattr(os, 'O_NOFOLLOW', 0), 0o644)
        try:
            os.write(descriptor, encoded + b'\n')
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(temporary, path)
        return {'status': 'ok', 'hostname': name}
    except (OSError, ValueError) as error:
        return {'status': 'error', 'message': str(error) or 'hostname update failed'}


def timezonepath(name):

    name = str(name or '').strip().replace('\\', '/')
    if (
        not name or name.startswith('/') or
        any(part in ('', '.', '..') for part in name.split('/'))
    ):
        raise ValueError('timezone denied')
    root = os.path.realpath(ZONEINFODIR)
    path = os.path.realpath(os.path.join(root, *name.split('/')))
    if os.path.commonpath((root, path)) != root or not os.path.isfile(path):
        raise ValueError('Unknown timezone: ' + name)
    return path


def timezoneinfo(name):

    name = str(name or '').strip()
    with open(timezonepath(name), 'rb') as stream:
        return zoneinfo.ZoneInfo.from_file(stream, key=name)


def configuredtimezone():

    try:
        with open(TIMEZONEFILE, 'r', encoding='utf-8') as stream:
            name = stream.read(256).strip()
    except OSError:
        name = DEFAULTTIMEZONE
    if name in ('10', '+10'):
        name = DEFAULTTIMEZONE
    timezoneinfo(name)
    return name


def settingenabled(path):

    try:
        with open(path, 'r', encoding='utf-8') as stream:
            return stream.read(32).strip().lower() in ('1', 'true', 'yes', 'on')
    except OSError:
        return False


def virtualboxrtc():

    # VirtualBox presents the emulated CMOS clock as UTC.  Physical T1OS
    # installations retain the project's local-wall-clock motherboard policy.
    return os.path.exists(VIRTUALBOXGUESTNODE)


def rtcclockzone(name, virtualbox=None):

    if virtualbox is None:
        virtualbox = virtualboxrtc()
    return datetime.timezone.utc if virtualbox else timezoneinfo(name)


def rtcfieldsepoch(fields, name, virtualbox=None):

    second, minute, hour, day, month, year = (int(value) for value in fields[:6])
    wallclock = datetime.datetime(year + 1900, month + 1, day, hour, minute, second)
    zone = rtcclockzone(name, virtualbox)
    candidates = []
    for fold in (0, 1):
        candidate = wallclock.replace(tzinfo=zone, fold=fold)
        epoch = candidate.timestamp()
        if datetime.datetime.fromtimestamp(epoch, zone).replace(tzinfo=None) == wallclock:
            candidates.append(epoch)
    if not candidates:
        raise ValueError('motherboard time does not exist in ' + str(name))
    return max(candidates)


def rtcclockfields(epoch, name, virtualbox=None):

    local = datetime.datetime.fromtimestamp(
        float(epoch), rtcclockzone(name, virtualbox))
    timetable = local.timetuple()
    return (
        local.second, local.minute, local.hour, local.day,
        local.month - 1, local.year - 1900,
        (local.weekday() + 1) % 7, timetable.tm_yday - 1,
        1 if local.dst() and local.dst() != datetime.timedelta(0) else 0,
    )


def rtcwallclockepoch(name):

    last_error = None
    for node in ('/the one/drivers/nodes/rtc0', '/the one/drivers/nodes/rtc'):
        try:
            descriptor = os.open(
                node,
                os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) |
                getattr(os, 'O_CLOEXEC', 0))
            try:
                status = os.fstat(descriptor)
                if not statmodule.S_ISCHR(status.st_mode):
                    raise OSError('RTC node is not a character device')
                value = bytearray(struct.calcsize('9i'))
                fcntl.ioctl(descriptor, RTCREADTIME, value, True)
            finally:
                os.close(descriptor)
            return rtcfieldsepoch(struct.unpack('9i', value), name)
        except (OSError, ValueError) as error:
            last_error = error
    if last_error is not None:
        raise last_error
    raise FileNotFoundError('motherboard RTC is unavailable')


def writemotherboardclock(epoch, name):

    value = struct.pack('9i', *rtcclockfields(epoch, name))
    for node in ('/the one/drivers/nodes/rtc0', '/the one/drivers/nodes/rtc'):
        try:
            descriptor = os.open(
                node,
                os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) |
                getattr(os, 'O_CLOEXEC', 0))
            try:
                status = os.fstat(descriptor)
                if not statmodule.S_ISCHR(status.st_mode):
                    raise OSError('RTC node is not a character device')
                fcntl.ioctl(descriptor, RTCSETTIME, value)
                return True
            finally:
                os.close(descriptor)
        except OSError:
            continue
    return False


def setclockepoch(epoch, name, *, update_motherboard):

    epoch = float(epoch)
    if not MINIMUMCLOCKEPOCH <= epoch <= MAXIMUMCLOCKEPOCH:
        raise ValueError('clock value denied')
    timezoneinfo(name)
    time.clock_settime(time.CLOCK_REALTIME, epoch)
    return writemotherboardclock(epoch, name) if update_motherboard else False


def initialiseclockfrommotherboard():

    try:
        name = configuredtimezone()
        epoch = rtcwallclockepoch(name)
        setclockepoch(epoch, name, update_motherboard=False)
        clockkind = 'UTC VirtualBox RTC' if virtualboxrtc() else 'local motherboard time'
        print(
            f'> operations server initialized system clock from {clockkind} ({name})',
            file=sys.stderr, flush=True)
        return True
    except Exception as error:
        print(
            f'> operations server motherboard clock initialization unavailable {error}',
            file=sys.stderr, flush=True)
        return False


def handletimesample(request):

    try:
        if str(request.get('source') or '').strip().lower() != 'internet':
            raise ValueError('time source denied')
        if not settingenabled(INTERNETTIMEFILE):
            raise PermissionError('internet time is disabled')
        name = configuredtimezone()
        epoch = float(request.get('epoch'))
        motherboardupdated = setclockepoch(
            epoch, name, update_motherboard=True)
        return {
            'status': 'ok', 'source': 'internet', 'timezone': name,
            'clock_set': True, 'motherboard_updated': motherboardupdated,
        }
    except (OSError, TypeError, ValueError) as error:
        return {'status': 'error', 'message': str(error) or 'time sample denied'}


def handlesettingstime(request):

    try:
        timezone = str(request.get('timezone') or '').strip()
        if len(timezone) > 128 or not re.fullmatch(r'[A-Za-z0-9_+.-]+(?:/[A-Za-z0-9_+.-]+)*', timezone):
            raise ValueError('timezone denied')
        timezoneinfo(timezone)
        internet = request.get('internet') is True
        virtualbox = request.get('virtualbox') is True
        epoch = request.get('epoch')
        if epoch is not None:
            epoch = float(epoch)
            if not MINIMUMCLOCKEPOCH <= epoch <= MAXIMUMCLOCKEPOCH:
                raise ValueError('clock value denied')
            internet = False
            virtualbox = False
        values = {
            '/the one/settings/time/timezone.txt': timezone + '\n',
            '/the one/settings/time/internet.txt': ('true' if internet else 'false') + '\n',
            '/the one/settings/time/virtualbox.txt': ('true' if virtualbox else 'false') + '\n',
        }
        for path, value in values.items():
            directory = os.path.dirname(path)
            os.makedirs(directory, mode=0o700, exist_ok=True)
            temporary = f'{path}.new.{os.getpid()}.{threading.get_ident()}'
            descriptor = os.open(
                temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                getattr(os, 'O_NOFOLLOW', 0), 0o644)
            try:
                os.write(descriptor, value.encode('utf-8'))
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            os.replace(temporary, path)
        motherboardupdated = False
        if epoch is not None:
            motherboardupdated = setclockepoch(
                epoch, timezone, update_motherboard=True)
        return {
            'status': 'ok', 'timezone': timezone,
            'clock_set': epoch is not None,
            'motherboard_updated': motherboardupdated,
        }
    except (OSError, ValueError, zoneinfo.ZoneInfoNotFoundError) as error:
        return {'status': 'error', 'message': str(error) or 'time update failed'}


def handlesettingsrecovery(request):

    """Authenticate recovery and hand destructive authority only to PID 1."""

    try:
        action = str(request.get('recovery_action') or request.get('recovery') or '').strip().lower()
        if action not in VALIDRECOVERYACTIONS:
            raise ValueError('recovery action denied')
        password = boundedpassword(request, 'password')
        token = None
        if action in authbroker.RECOVERY_ACTIONS:
            # The lifetime includes firmware startup, device discovery and the
            # bounded RootHealth gate.  Five minutes remains well inside the
            # broker's maximum while avoiding expiry during an ordinary boot.
            issued = authbroker.issue_recovery_authorization(
                MASTERFILE, password, action, ttl=300)
            authentication = issued.authentication
            token = issued.token or None
        else:
            # Python and build recovery do not receive a destructive token, but
            # Settings still authenticates the person requesting the restart.
            authentication = authbroker.authenticate_master(
                MASTERFILE, password, scope=f'recovery:{action}', migrate=False)
        if not authentication.ok or (
                action in authbroker.RECOVERY_ACTIONS and not token):
            return {
                'status': 'error', 'message': 'authentication failed',
                'retry_after': float(authentication.retry_after or 0.0),
            }
        # A destructive token is sent over the credential-bound local power
        # transport and never returned to Settings or placed in argv/environment.
        from operations.operations import requestpower
        requestpower(
            'restart', timeout=5.0, recovery_action=action,
            recovery_token=token)
        return {'status': 'ok', 'accepted': True, 'recovery_action': action}
    except (OSError, ValueError, authbroker.AuthenticationError) as error:
        return {'status': 'error', 'message': str(error) or 'recovery authorization failed'}


def handlesessionlogout(request):

    peer = request.get('_peer', {})
    session = sessionidentityfor(peer.get('pid', 0))
    if not session:
        return {'status': 'error', 'message': 'session identity unavailable'}
    if peer.get('domain') == 'brick':
        with STATELOCK:
            ownerentry = dict(OPMETA.get(str(peer.get('pid')), {}))
        if (
            str(ownerentry.get('_session_identity', '')) != session or
            int(ownerentry.get('_owner_started', -1)) <= 0 or
            str(ownerentry.get('_process_identity', '')) !=
                str((processrecord(peer.get('pid')) or {}).get('identity', ''))
        ):
            return {'status': 'error', 'message': 'session ownership denied'}
    records = processrecords()
    targets = []
    with STATELOCK:
        entries = [(key, dict(value)) for key, value in OPMETA.items()]
    for key, entry in entries:
        if str(entry.get('_session_identity', '')) != session:
            continue
        record = records.get(str(key))
        if record is None or str(record.get('identity', '')) != str(entry.get('_process_identity', '')):
            continue
        targets.extend(processtree(int(key), records=records, registered=()))
    # Include Expanse last; its SO_PEERCRED PID/start-time anchors this session.
    requester = processrecord(peer['pid'])
    if requester is not None and str(requester.get('identity', '')) == session:
        targets.append(str(peer['pid']))
    signalled = []
    for target in reversed(list(dict.fromkeys(targets))):
        try:
            expected = records.get(str(target))
            fresh = processrecord(int(target))
            if (expected is None or fresh is None or
                    str(expected.get('identity', '')) != str(fresh.get('identity', '')) or
                    processdomain(int(target)) not in (
                        'untrusted', 'expanse', 'desktop', 'brick', 'video',
                        'settings', 'snap', 'chromium', 'picker', 'lockscreen')):
                continue
            os.kill(int(target), signal.SIGTERM)
            signalled.append(int(target))
        except ProcessLookupError:
            pass
        except OSError as error:
            print(f'> operations server logout signal error {error}', file=sys.stderr)
    try:
        startup = popenisolated(
            [STARTUPSCRIPT],
            softwarepath=STARTUPSCRIPT, logpath=STARTUPLOG,
            security_profile='startup', start_new_session=True)
    except Exception as error:
        return {
            'status': 'error', 'message': 'session ended but startup failed',
            'signalled': signalled,
        }
    return {'status': 'ok', 'signalled': signalled, 'startup_pid': startup.pid}


def handlesessionlockstart(request):

    """Start the fixed authentication UI without granting Window Startup."""

    try:
        lifecycle = '/.ephemeral/lock screen'
        os.makedirs(lifecycle, mode=0o700, exist_ok=True)
        lifecyclestat = os.stat(lifecycle, follow_symlinks=False)
        if not statmodule.S_ISDIR(lifecyclestat.st_mode):
            raise PermissionError('unsafe session-lock runtime directory')
        os.chown(lifecycle, DESKTOPUID, DESKTOPGID, follow_symlinks=False)
        os.chmod(lifecycle, 0o700, follow_symlinks=False)
        process = popenisolated(
            [STARTUPSCRIPT, 'session-lock'],
            softwarepath=STARTUPSCRIPT,
            logpath=STARTUPLOG,
            security_profile='lockscreen',
            preexec_fn=dropsandboxidentity,
            start_new_session=True,
        )
        record = processrecord(process.pid)
        if record is None or processdomain(process.pid) != 'lockscreen':
            try:
                process.kill()
            except OSError:
                pass
            raise RuntimeError('could not bind session lock identity')
        info = {
            'name': 'session lock', 'script': STARTUPSCRIPT,
            'log': STARTUPLOG, 'user': 'session', 'mode': 'front',
            'state': 'starting', '_broker_owned': True,
            '_owner_pid': int(request['_peer']['pid']),
            '_owner_started': int(request['_peer']['started']),
            '_session_identity': sessionidentityfor(request['_peer']['pid']),
            '_process_identity': str(record['identity']),
        }
        if not recordstart(process.pid, process, info, ('session-lock',)):
            process.kill()
            raise RuntimeError('could not register session lock')
        return {
            'status': 'ok', 'pid': int(process.pid),
            'identity': str(record['identity']),
        }
    except Exception as error:
        print(f'> operations server session lock error {error}', file=sys.stderr)
        return {'status': 'error', 'message': 'session lock unavailable'}


# Boot-scoped state helpers. Operations Server is the sole writer. The
# checkpoint is not the live registry; it only lets a restarted server recover
# descriptive metadata for processes that still have the same /proc identity.
def savestate():

    temporary = f'{OPERATIONSSTATE}.tmp.{os.getpid()}.{threading.get_ident()}'

    try:

        with STATEWRITELOCK:

            with STATELOCK:
                active = {key: dict(value) for key, value in OPMETA.items()}
                completed = {key: dict(value) for key, value in COMPLETED.items()}

            os.makedirs(OPERATIONSROOT, mode=0o750, exist_ok=True)

            with open(temporary, 'x', encoding='utf-8') as stream:
                os.chmod(temporary, 0o600)
                payload = {
                    'format': 1,
                    'active': active,
                    'completed': completed,
                }
                json.dump(payload, stream, sort_keys=True, separators=(',', ':'))
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())

            os.replace(temporary, OPERATIONSSTATE)
            directoryfd = os.open(OPERATIONSROOT, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directoryfd)
            finally:
                os.close(directoryfd)

        return True

    except PermissionError:
        print('> operations server state checkpoint permission denied', file=sys.stderr)

    except Exception as e:
        print(f'> operations server state checkpoint error {e}', file=sys.stderr)

    try:
        if os.path.exists(temporary):
            os.unlink(temporary)
    except Exception:
        pass

    return False


def loadstate():

    global OPMETA, COMPLETED

    try:

        with open(OPERATIONSSTATE, encoding='utf-8') as stream:
            loaded = json.load(stream)

        if not isinstance(loaded, dict) or loaded.get('format') != 1:
            raise ValueError('operations state has an unsupported format')

        loadedactive = loaded.get('active', {})
        loadedcompleted = loaded.get('completed', {})
        if not isinstance(loadedactive, dict) or not isinstance(loadedcompleted, dict):
            raise ValueError('operations state collections are invalid')

        active = {}
        for pid, info in loadedactive.items():
            if not isinstance(info, dict):
                continue
            key = str(int(pid))
            record = processrecord(int(key))
            identity = str(info.get('_process_identity', ''))
            if (
                record is None or
                str(record.get('state', '')).upper() == 'Z' or
                not identity or
                str(record.get('identity', '')) != identity
            ):
                continue
            entry = dict(info)
            entry['pid'] = int(key)
            entry.setdefault('args', [])
            entry.setdefault('state', 'running')
            entry.setdefault('exitcode', None)
            active[key] = entry

        completed = {}
        for pid, info in loadedcompleted.items():
            if not isinstance(info, dict):
                continue
            key = str(int(pid))
            entry = dict(info)
            entry['pid'] = int(key)
            entry.setdefault('state', 'completed')
            entry.setdefault('exitcode', None)
            entry.setdefault('ended', 0.0)
            completed[key] = entry

        ordered = sorted(
            completed.items(), key=lambda item: float(item[1].get('ended', 0.0)))
        completed = dict(ordered[-COMPLETEDKEEP:])

        with STATELOCK:
            OPMETA = active
            COMPLETED = completed

        return True

    except FileNotFoundError:
        with STATELOCK:
            OPMETA = {}
            COMPLETED = {}
        return True

    except PermissionError:
        print('> operations server state checkpoint permission denied', file=sys.stderr)

    except Exception as e:
        print(f'> operations server state load error {e}', file=sys.stderr)

    with STATELOCK:
        OPMETA = {}
        COMPLETED = {}

    return False


def recordstart(pid, proc, info, args=None):

    try:

        key = str(int(pid))
        entry = dict(info or {})
        entry['pid'] = int(pid)
        entry['args'] = list(args or [])
        entry['started'] = float(time.time())
        requestedstate = str(entry.get('state', 'running')).strip().lower()
        entry['state'] = 'starting' if requestedstate == 'starting' else 'running'
        entry['exitcode'] = None

        with STATELOCK:
            COMPLETED.pop(key, None)
            readyat = READYPENDING.pop(key, None)

            if readyat is not None and entry['state'] == 'starting':
                entry['state'] = 'running'
                entry['ready'] = float(time.time())

            OPMETA[key] = entry

            if proc is not None:
                PROCESSES[key] = proc

        savestate()
        return True

    except Exception as e:
        print(f'> operations server start record error {e}', file=sys.stderr)
        return False


def recorddone(pid, code=None, state='completed'):

    try:

        key = str(int(pid))

        with STATELOCK:

            entry = dict(OPMETA.get(key, {}))
            entry['pid'] = int(pid)
            entry['state'] = str(state)
            entry['ended'] = float(time.time())
            entry['exitcode'] = code
            COMPLETED[key] = entry
            PROCESSES.pop(key, None)
            OPMETA.pop(key, None)
            READYPENDING.pop(key, None)

            ordered = sorted(COMPLETED.items(), key=lambda item: float(item[1].get('ended', 0.0)))

            while len(ordered) > COMPLETEDKEEP:

                victim, _ = ordered.pop(0)
                COMPLETED.pop(victim, None)

        savestate()

    except Exception as e:
        print(f'> operations server completion record error {e}', file=sys.stderr)


def reaptracked():

    try:

        with STATELOCK:
            tracked = list(PROCESSES.items())

    except Exception:
        tracked = []

    for pid, proc in tracked:

        try:
            code = proc.poll()
        except Exception:
            code = None

        if code is not None:

            try:

                with STATELOCK:
                    previous = str(OPMETA.get(str(pid), {}).get('state', ''))

            except Exception:
                previous = ''

            state = 'killed' if previous in ('stopping', 'killing') else ('completed' if int(code) == 0 else 'failed')
            recorddone(pid, int(code), state)

    try:

        with STATELOCK:
            external = [key for key in OPMETA if key not in PROCESSES]

    except Exception:
        external = []

    for pid in external:

        try:
            record = processrecord(pid)
            with STATELOCK:
                expected = str(OPMETA.get(str(pid), {}).get('_process_identity', ''))
            if (
                record is None or
                str(record.get('state', '')).upper() == 'Z' or
                not expected or
                str(record.get('identity', '')) != expected
            ):
                raise ProcessLookupError
            continue
        except ProcessLookupError:
            pass
        except PermissionError:
            continue
        except Exception:
            continue

        try:

            with STATELOCK:
                previous = str(OPMETA.get(str(pid), {}).get('state', ''))

        except Exception:
            previous = ''

        code = -9 if previous == 'killing' else (-15 if previous == 'stopping' else None)
        state = 'killed' if previous in ('stopping', 'killing') else 'completed'
        recorddone(pid, code, state)

    try:

        cutoff = time.monotonic() - READYPENDINGTTL

        with STATELOCK:

            for key, marked in list(READYPENDING.items()):

                if float(marked) < cutoff:
                    READYPENDING.pop(key, None)

    except Exception:
        pass


def activeoperations():

    """Return a registry snapshot after pruning dead or reused PIDs."""

    reaptracked()
    with STATELOCK:
        return {key: dict(value) for key, value in OPMETA.items()}


def publicoperation(info):

    return {
        key: value for key, value in dict(info or {}).items()
        if not str(key).startswith('_')
    }


def handlebootstrap(request):

    """Idempotently replace the GODDESS-owned part of the live registry."""

    peer = request.get('_peer', {})
    supplied = request.get('operations')
    if peer.get('domain') != 'goddess' or not isinstance(supplied, list):
        return {'status': 'error', 'message': 'invalid bootstrap'}
    if len(supplied) > 256:
        return {'status': 'error', 'message': 'bootstrap too large'}

    accepted = {}
    try:
        for item in supplied:
            if not isinstance(item, dict):
                raise ValueError('invalid operation')
            pid = int(item.get('pid'))
            if pid < 1 or not processdescendant(int(peer['pid']), pid):
                raise PermissionError('process is outside GODDESS')
            record = processrecord(pid)
            if record is None or str(record.get('state', '')).upper() == 'Z':
                continue
            mode = str(item.get('mode', 'behind')).strip().lower()
            entry = {
                'pid': pid,
                'name': str(item.get('name') or 'operation')[:128],
                'script': str(item.get('script') or '-')[:4096],
                'log': str(item.get('log') or '-')[:4096],
                'user': str(item.get('user') or 'GODDESS')[:64],
                'mode': 'behind' if mode in ('back', 'behind', 'background') else 'front',
                'args': [],
                'state': 'running',
                'exitcode': None,
                '_broker_owned': False,
                '_owner_pid': int(peer['pid']),
                '_owner_started': int(peer['started']),
                '_process_identity': str(record['identity']),
                '_registry_source': 'goddess',
            }
            accepted[str(pid)] = entry
    except PermissionError:
        return {'status': 'error', 'message': 'bootstrap denied'}
    except Exception as error:
        print(f'> operations server bootstrap parse error {error}', file=sys.stderr)
        return {'status': 'error', 'message': 'invalid bootstrap'}

    now = float(time.time())
    with STATELOCK:
        existinggoddess = {
            key for key, value in OPMETA.items()
            if value.get('_registry_source') == 'goddess'
        }
        for key, entry in accepted.items():
            previous = OPMETA.get(key, {})
            if previous.get('_process_identity') == entry['_process_identity']:
                entry['started'] = float(previous.get('started', now))
                entry['state'] = str(previous.get('state', 'running'))
                if 'ready' in previous:
                    entry['ready'] = previous['ready']
            else:
                entry['started'] = now
            COMPLETED.pop(key, None)
            OPMETA[key] = entry

        for key in existinggoddess - set(accepted):
            previous = dict(OPMETA.pop(key, {}))
            PROCESSES.pop(key, None)
            READYPENDING.pop(key, None)
            previous.update({
                'pid': int(key), 'state': 'completed', 'exitcode': None,
                'ended': now,
            })
            COMPLETED[key] = previous

        ordered = sorted(
            COMPLETED.items(), key=lambda item: float(item[1].get('ended', 0.0)))
        while len(ordered) > COMPLETEDKEEP:
            victim, _ = ordered.pop(0)
            COMPLETED.pop(victim, None)

    savestate()
    return {'status': 'ok', 'registered': len(accepted)}


# request handler functions
def _disabled_handlerun(request):

    pid = None

    try:

        # read script path
        path = request.get('path', None)

        # read arguments
        args = request.get('args', [])

        # read operation name
        name = request.get('name', None)

        # read log path
        logpath = request.get('log', None)

        # read user
        user = request.get('user', 'master')

        # read mode
        mode = request.get('mode', 'behind')

        mode = 'behind' if str(mode).strip().lower() in ('back', 'behind', 'background') else 'front'

        # ensure script path present
        if not path:
            return {'status': 'error', 'message': 'missing path'}

    except Exception as e:

        # run request parse error
        print(f'> operations server run request parse error {e}', file=sys.stderr)
        return {'status': 'error', 'message': 'invalid request'}

    try:

        # normalise args list
        arglist = list(args) if args else []

    except Exception as e:

        # run args error
        print(f'> operations server run args error {e}', file=sys.stderr)
        return {'status': 'error', 'message': 'invalid args'}

    try:

        # derive name if missing
        if not name:

            basename = os.path.basename(path)
            name = os.path.splitext(basename)[0]

    except Exception as e:

        # run name derive error
        print(f'> operations server run name derive error {e}', file=sys.stderr)
        return {'status': 'error', 'message': 'invalid name'}

    loghandle = None

    try:

        # prepare log handle
        if logpath:

            try:

                logdir = os.path.dirname(logpath) or '.'
                os.makedirs(logdir, exist_ok=True)

            except PermissionError:

                # log directory permission error
                print('> operations server log directory permission denied', file=sys.stderr)

            except Exception as e:

                # log directory create error
                print(f'> operations server log directory error {e}', file=sys.stderr)

            try:

                loghandle = open(logpath, 'a')

            except FileNotFoundError:

                # log file path not found
                print('> operations server log file path not found', file=sys.stderr)

            except PermissionError:

                # log file permission error
                print('> operations server log file permission denied', file=sys.stderr)

            except Exception as e:

                # log file open error
                print(f'> operations server log file error {e}', file=sys.stderr)

    except Exception as e:

        # run log prepare error
        print(f'> operations server run log prepare error {e}', file=sys.stderr)
        loghandle = None

    try:

        # build command list
        if str(path).endswith('.py'):
            cmd = [sys.executable, "-u", path] + arglist
        else:
            cmd = [path] + arglist

    except Exception as e:

        # run command build error
        print(f'> operations server run command build error {e}', file=sys.stderr)

        if loghandle is not None:

            loghandle.close()
        return {'status': 'error', 'message': 'invalid command'}

    try:

        # prepare popen options
        popenopts = {}

        if loghandle is not None:

            popenopts['stdout'] = loghandle
            popenopts['stderr'] = loghandle

        else:

            popenopts['stdout'] = subprocess.DEVNULL
            popenopts['stderr'] = subprocess.DEVNULL

        # spawn process
        proc = subprocess.Popen(cmd, **popenopts)

        pid = proc.pid

    except FileNotFoundError:

        # script not found
        print(f'> operations server script not found {path}', file=sys.stderr)

        if loghandle is not None:

            loghandle.close()
        return {'status': 'error', 'message': 'script not found'}

    except PermissionError:

        # script permission error
        print(f'> operations server script permission denied {path}', file=sys.stderr)

        if loghandle is not None:

            loghandle.close()
        return {'status': 'error', 'message': 'permission denied'}

    except Exception as e:

        # run spawn error
        print(f'> operations server run spawn error {e}', file=sys.stderr)

        if loghandle is not None:

            loghandle.close()
        return {'status': 'error', 'message': 'spawn error'}


    if loghandle is not None:

        try:
            loghandle.flush()
        except Exception:
            pass

        try:
            loghandle.close()
        except Exception:
            pass

    try:

        # build info entry
        info = {}

        info['name'] = name
        info['script'] = path
        info['log'] = logpath if logpath else '-'
        info['user'] = user
        info['mode'] = mode
        info['state'] = 'starting' if str(request.get('state', '')).strip().lower() == 'starting' else 'running'
        info['_owner_pid'] = int(request.get('_peer_pid', 0) or 0)

        if not recordstart(pid, proc, info, arglist):
            print(f'> operations server failed to register operation for pid {pid}', file=sys.stderr)

    except Exception as e:

        # run operations append error
        print(f'> operations server run operations append error {e}', file=sys.stderr)

    return {'status': 'ok', 'pid': pid}


def _disabled_handlestream(request, conn):

    pid = None
    loghandle = None

    try:

        # read script path
        path = request.get('path', None)

        # read arguments
        args = request.get('args', [])

        # read operation name
        name = request.get('name', None)

        # read log path
        logpath = request.get('log', None)

        # read user
        user = request.get('user', 'master')

        # ensure script path present
        if not path:


            resptext = json.dumps({'status': 'error', 'message': 'missing path'}) + '\n'
            conn.sendall(resptext.encode('utf-8'))


            conn.close()

            return

    except Exception as e:

        print(f'> operations server runstream request parse error {e}', file=sys.stderr)


        resptext = json.dumps({'status': 'error', 'message': 'invalid request'}) + '\n'
        conn.sendall(resptext.encode('utf-8'))


        conn.close()

        return

    try:

        # normalise args list
        arglist = list(args) if args else []

    except Exception as e:

        print(f'> operations server runstream args error {e}', file=sys.stderr)


        resptext = json.dumps({'status': 'error', 'message': 'invalid args'}) + '\n'
        conn.sendall(resptext.encode('utf-8'))


        conn.close()

        return

    try:

        # derive name if missing
        if not name:

            basename = os.path.basename(path)
            name = os.path.splitext(basename)[0]

    except Exception as e:

        print(f'> operations server runstream name derive error {e}', file=sys.stderr)


        resptext = json.dumps({'status': 'error', 'message': 'invalid name'}) + '\n'
        conn.sendall(resptext.encode('utf-8'))


        conn.close()

        return

    try:

        # prepare log handle (optional)
        if logpath:

            try:

                logdir = os.path.dirname(logpath) or '.'
                os.makedirs(logdir, exist_ok=True)

            except PermissionError:

                print('> operations server log directory permission denied', file=sys.stderr)

            except Exception as e:

                print(f'> operations server log directory error {e}', file=sys.stderr)

            try:

                loghandle = open(logpath, 'a')

            except Exception as e:

                print(f'> operations server log file error {e}', file=sys.stderr)
                loghandle = None

    except Exception as e:

        print(f'> operations server runstream log prepare error {e}', file=sys.stderr)
        loghandle = None

    try:

        # build command list
        if str(path).endswith('.py'):
            cmd = [sys.executable, "-u", path] + arglist
        else:
            cmd = [path] + arglist

    except Exception as e:

        print(f'> operations server runstream command build error {e}', file=sys.stderr)


        resptext = json.dumps({'status': 'error', 'message': 'invalid command'}) + '\n'
        conn.sendall(resptext.encode('utf-8'))


        if loghandle is not None:
            loghandle.close()


        conn.close()

        return

    try:

        # spawn process with stream pipe
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            errors='replace',
            bufsize=1
        )

        pid = proc.pid

    except FileNotFoundError:

        print(f'> operations server script not found {path}', file=sys.stderr)


        resptext = json.dumps({'status': 'error', 'message': 'script not found'}) + '\n'
        conn.sendall(resptext.encode('utf-8'))


        if loghandle is not None:
            loghandle.close()


        conn.close()

        return

    except PermissionError:

        print(f'> operations server script permission denied {path}', file=sys.stderr)


        resptext = json.dumps({'status': 'error', 'message': 'permission denied'}) + '\n'
        conn.sendall(resptext.encode('utf-8'))


        if loghandle is not None:
            loghandle.close()


        conn.close()

        return

    except Exception as e:

        print(f'> operations server runstream spawn error {e}', file=sys.stderr)


        resptext = json.dumps({'status': 'error', 'message': 'spawn error'}) + '\n'
        conn.sendall(resptext.encode('utf-8'))


        if loghandle is not None:
            loghandle.close()


        conn.close()

        return

    try:

        # register operation (best effort)
        info = {}

        info['name'] = name
        info['script'] = path
        info['log'] = logpath if logpath else '-'
        info['user'] = user
        info['mode'] = 'front'

        recordstart(pid, proc, info, arglist)

    except Exception as e:

        print(f'> operations server runstream operations append error {e}', file=sys.stderr)

    try:

        # send started frame
        started = {'status': 'ok', 'pid': pid, 'stream': True}

        conn.sendall((json.dumps(started) + '\n').encode('utf-8'))

    except Exception as e:

        print(f'> operations server runstream started send error {e}', file=sys.stderr)


        proc.terminate()


        if loghandle is not None:
            loghandle.close()


        conn.close()

        return

    try:

        # stream output as json lines
        while True:

            try:

                line = proc.stdout.readline()

            except Exception as e:

                print(f'> operations server runstream read error {e}', file=sys.stderr)
                break

            if not line:
                break


            if loghandle is not None:
                loghandle.write(line)

            try:

                frame = {'type': 'out', 'data': line}

                conn.sendall((json.dumps(frame) + '\n').encode('utf-8'))

            except Exception:

                # client went away
                break

    except Exception as e:

        print(f'> operations server runstream loop error {e}', file=sys.stderr)

    try:

        code = proc.wait()

    except Exception:

        code = None

    recorddone(pid, code, 'completed' if code == 0 else 'failed')


    # exit frame
    frame = {'type': 'exit', 'code': code}

    try:
        conn.sendall((json.dumps(frame) + '\n').encode('utf-8'))
    except Exception:
        pass


    if loghandle is not None:
        loghandle.close()


    conn.close()

def safelegacyrequest(request):

    path = str(request.get('path') or '')
    if not path.startswith('/') or len(path.encode('utf-8')) > 4096:
        raise ValueError('invalid path')
    arguments = request.get('args', [])
    if not isinstance(arguments, list) or len(arguments) > 64:
        raise ValueError('invalid arguments')
    arguments = [str(value) for value in arguments]
    if any(len(value.encode('utf-8')) > 4096 or '\x00' in value for value in arguments):
        raise ValueError('invalid arguments')
    name = os.path.splitext(os.path.basename(path))[0][:64] or 'operation'
    environment = applicationenvironment({}, {})
    return path, arguments, name, environment


def handlelegacyrun(request):

    del request
    return {
        'status': 'error',
        'message': 'RUN is retired; use a typed catalogue launch',
    }


def handlesafestream(request, connection):

    # The legacy streaming RUN protocol was an arbitrary-path confused deputy.
    # Keep the old function symbol for wire-version compatibility, but make it
    # unconditionally fail closed; typed launches resolve server-owned entries.
    del request
    try:
        connection.sendall((json.dumps({
            'status': 'error',
            'message': 'RUN is retired; use a typed catalogue launch',
        }) + '\n').encode('utf-8'))
    except OSError:
        pass
    finally:
        connection.close()
    return

    # Unreachable until old clients have completed their protocol migration.
    process = None
    try:
        path, arguments, name, environment = safelegacyrequest(request)
        command = [sys.executable, '-B', '-u', path, *arguments] if path.endswith('.py') else [path, *arguments]
        process = popensecured(
            command, path, 'untrusted',
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, bufsize=0, close_fds=True,
            preexec_fn=dropsandboxidentity, start_new_session=True,
            env=environment)
        record = processrecord(process.pid)
        if record is None:
            raise RuntimeError('could not bind process identity')
        info = {
            'name': name, 'script': path, 'log': '-', 'user': 'desktop',
            'mode': 'front', 'state': 'running', '_broker_owned': True,
            '_owner_pid': int(request['_peer']['pid']),
            '_owner_started': int(request['_peer']['started']),
            '_session_identity': sessionidentityfor(request['_peer']['pid']),
            '_process_identity': str(record['identity']),
        }
        if not recordstart(process.pid, process, info, arguments):
            raise RuntimeError('operation registration failed')
        connection.sendall((json.dumps({'status': 'ok', 'pid': process.pid}) + '\n').encode('utf-8'))
        while True:
            block = process.stdout.read(4096)
            if not block:
                break
            connection.sendall((json.dumps({
                'type': 'output', 'data': block.decode('utf-8', errors='replace')
            }) + '\n').encode('utf-8'))
        code = process.wait()
        recorddone(process.pid, code, 'completed' if code == 0 else 'failed')
        connection.sendall((json.dumps({'type': 'exit', 'code': code}) + '\n').encode('utf-8'))
    except Exception as error:
        try:
            connection.sendall((json.dumps({'status': 'error', 'message': str(error) or 'launch failed'}) + '\n').encode('utf-8'))
        except OSError:
            pass
        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass
    finally:
        connection.close()


def sendresponse(conn, response):

    try:

        conn.sendall((json.dumps(response) + '\n').encode('utf-8'))

        return True

    except (BrokenPipeError, ConnectionResetError):

        # A request client may time out or close after dispatch.  The broker
        # operation has already completed, so a vanished reply destination is
        # not a server failure and must not escape the worker thread.
        return False


def handleclient(conn, peer=None):

    fileobj = None

    try:

        fileobj = conn.makefile('rb')

    except Exception:

        conn.close()
        return

    request = None

    try:

        line = fileobj.readline(MAXIMUMREQUEST + 1)

        if not line or len(line) > MAXIMUMREQUEST or not line.endswith(b'\n'):
            return

        text = line.decode('utf-8', errors='replace').strip()

        request = json.loads(text)

        if not isinstance(request, dict):
            raise ValueError('request is not an object')

        identity = capturepeer(peer)
        if identity is None:
            raise PermissionError('peer identity denied')
        request['_peer_checked'] = True
        request['_peer'] = identity
        request['_peer_pid'] = identity['pid']
        request['_peer_uid'] = identity['uid']
        request['_peer_gid'] = identity['gid']

    except Exception as e:

        resp = {'status': 'error', 'message': 'invalid request'}
        sendresponse(conn, resp)
        return

    op = None
    mode = 'behind'

    try:

        op = requestaction(request)

        mode = request.get('mode', 'behind')

        mode = 'behind' if str(mode).strip().lower() in ('back', 'behind', 'background') else 'front'

    except Exception:

        resp = {'status': 'error', 'message': 'invalid request'}
        sendresponse(conn, resp)
        return

    if not authorizerequest(request):
        response = {'status': 'error', 'message': 'request denied'}
        sendresponse(conn, response)
        conn.close()
        return

    if op == 'RUN' and mode == 'front' and request.get('stream') is True:

        handlesafestream(request, conn)

        return

    response = handlerequest(request)


    sendresponse(conn, response)


    conn.close()

def handleregisterpid(request):

    try:

        pid = request.get('pid', None)

        if pid is None:
            return {'status': 'error', 'message': 'missing pid'}

        ipid = int(pid)

    except Exception as e:

        # register pid parse error
        print(f'> operations server register pid error {e}', file=sys.stderr)
        return {'status': 'error', 'message': 'invalid pid'}

    try:

        name = request.get('name', None)
        script = request.get('script', None)
        logpath = '-'
        user = 'desktop'
        mode = request.get('mode', 'behind')
        mode = 'behind' if str(mode).strip().lower() in ('back', 'behind', 'background') else 'front'

        if not name:
            name = 'operation'

        if not script:
            script = '-'

    except Exception as e:

        # register request parse error
        print(f'> operations server register request parse error {e}', file=sys.stderr)
        return {'status': 'error', 'message': 'invalid request'}

    try:

        if request.get('_peer_checked'):

            peerpid = request.get('_peer_pid')

            peer = request.get('_peer')
            if (peerpid is None or not peerstillvalid(peer) or
                    not processdescendant(int(peerpid), ipid)):
                return {'status': 'error', 'message': 'registration denied'}

    except Exception:
        return {'status': 'error', 'message': 'registration denied'}

    try:

        # verify process exists and is not an unreaped zombie
        if not processrunning(ipid):
            raise ProcessLookupError

    except ProcessLookupError:

        # process not running
        return {'status': 'error', 'message': 'pid not running'}

    except PermissionError:

        # permission denied checking pid
        print(f'> operations server permission denied checking pid {ipid}', file=sys.stderr)

    except Exception as e:

        # register check error
        print(f'> operations server register check error {e}', file=sys.stderr)

    try:

        record = processrecord(ipid)
        domain = processdomain(ipid)
        peerdomain = str(request.get('_peer', {}).get('domain', ''))
        permitted = {
            'window': frozenset(('desktop', 'brick', 'video', 'settings', 'snap', 'chromium', 'picker', 'startup')),
            'brick': frozenset(('untrusted', 'desktop', 'video')),
            'desktop': frozenset(('untrusted', 'desktop', 'video')),
            'video': frozenset(('video',)),
            'settings': frozenset(('settings',)),
            'snap': frozenset(('snap',)),
            'chromium': frozenset(('chromium',)),
        }
        if record is None or domain not in permitted.get(peerdomain, ()):
            return {'status': 'error', 'message': 'registration domain denied'}

        info = {}

        info['name'] = name
        info['script'] = script
        info['log'] = logpath if logpath else '-'
        info['user'] = user
        info['mode'] = mode
        info['state'] = 'starting' if str(request.get('state', '')).strip().lower() == 'starting' else 'running'
        info['_broker_owned'] = False
        info['_owner_pid'] = int(request['_peer']['pid'])
        info['_owner_started'] = int(request['_peer']['started'])
        info['_process_identity'] = str(record['identity'])
        info['_session_identity'] = sessionidentityfor(request['_peer']['pid'])

        if not recordstart(ipid, None, info, []):
            return {'status': 'error', 'message': 'registration failed'}

    except Exception as e:

        # register operations append error
        print(f'> operations server register operations append error {e}', file=sys.stderr)
        return {'status': 'error', 'message': 'append error'}

    return {'status': 'ok', 'pid': ipid}


def handlecompletepid(request):

    try:
        pid = int(request.get('pid'))
        code = int(request.get('exitcode'))
        if pid <= 0 or code < 0 or code > 255:
            raise ValueError
    except Exception:
        return {'status': 'error', 'message': 'invalid completion'}

    if not request.get('_peer_checked'):
        return {'status': 'error', 'message': 'completion denied'}

    peerpid = int(request.get('_peer_pid', 0) or 0)
    key = str(pid)

    try:
        with STATELOCK:
            active = dict(OPMETA.get(key, {}))
            completed = dict(COMPLETED.get(key, {}))
            entry = active or completed

        if not entry or int(entry.get('_owner_pid', 0) or 0) != peerpid:
            return {'status': 'error', 'message': 'completion denied'}

        state = 'completed' if code == 0 else 'failed'

        if active:
            recorddone(pid, code, state)
        else:
            with STATELOCK:
                COMPLETED[key]['state'] = state
                COMPLETED[key]['exitcode'] = code
            savestate()

        return {'status': 'ok', 'pid': pid, 'exitcode': code}

    except Exception as error:
        print(f'> operations server completion error {error}', file=sys.stderr)
        return {'status': 'error', 'message': 'completion failed'}


def handleready(request):

    try:
        ipid = int(request.get('pid'))
    except Exception:
        return {'status': 'error', 'message': 'invalid pid'}

    try:
        if not processrunning(ipid):
            raise ProcessLookupError
    except ProcessLookupError:
        return {'status': 'error', 'message': 'pid not running'}
    except PermissionError:
        pass
    except Exception:
        return {'status': 'error', 'message': 'pid check failed'}

    key = str(ipid)

    try:

        with STATELOCK:

            entry = OPMETA.get(key)

            if entry is None:
                # A fast GUI can map before its launcher finishes REGISTER_PID.
                # Retain a short-lived readiness edge so registration cannot
                # overwrite the already-observed visible state with starting.
                READYPENDING[key] = time.monotonic()
                return {'status': 'ok', 'pid': ipid, 'pending': True}

            changed = str(entry.get('state', 'running')) == 'starting'
            entry['state'] = 'running'

            if changed:
                entry['ready'] = float(time.time())

            READYPENDING.pop(key, None)

        if changed:
            savestate()
        return {'status': 'ok', 'pid': ipid, 'changed': changed}

    except Exception as e:
        print(f'> operations server ready update error {e}', file=sys.stderr)
        return {'status': 'error', 'message': 'ready update failed'}


def handlekill(request):

    try:

        pid = request.get('pid', None)

        if pid is None:
            return {'status': 'error', 'message': 'missing pid'}

        ipid = int(pid)

    except Exception as e:

        # kill pid parse error
        print(f'> operations server kill pid error {e}', file=sys.stderr)
        return {'status': 'error', 'message': 'invalid pid'}

    try:

        operations = activeoperations()
        info = operations.get(str(ipid))

        if info is None:
            return {'status': 'error', 'message': 'operation not registered'}

        current = processrecord(ipid)

        if current is None:
            return {'status': 'error', 'message': 'pid not running'}

        with STATELOCK:
            metadata = dict(OPMETA.get(str(ipid), {}))
        peer = request.get('_peer', {})
        if not peerstillvalid(peer):
            return {'status': 'error', 'message': 'permission denied'}
        if str(current.get('identity', '')) != str(metadata.get('_process_identity', '')):
            return {'status': 'error', 'message': 'operation changed'}
        peerdomain = str(peer.get('domain', ''))
        owner = (
            int(metadata.get('_owner_pid', 0) or 0) == int(peer.get('pid', -1)) and
            int(metadata.get('_owner_started', -1)) == int(peer.get('started', -2))
        )
        same_session = (
            metadata.get('_session_identity') and
            metadata.get('_session_identity') == sessionidentityfor(peer.get('pid', 0))
        )
        if not owner and not (peerdomain in ('window', 'brick') and same_session):
            return {'status': 'error', 'message': 'permission denied'}

        expected = str(request.get('identity', '')).strip()

        if expected and expected != str(current.get('identity', '')):
            return {'status': 'error', 'message': 'operation changed'}

        force = bool(request.get('force', False))
        tree = bool(request.get('tree', False))
        chosen = signal.SIGKILL if force else signal.SIGTERM
        registered = list(operations.keys())
        records = processrecords()
        targets = processtree(ipid, records=records, registered=()) if tree else [str(ipid)]
        signalled = []

        for target in reversed(targets):

            try:
                expected_record = records.get(str(target))
                fresh_record = processrecord(int(target))
                if (expected_record is None or fresh_record is None or
                        str(expected_record.get('identity', '')) !=
                        str(fresh_record.get('identity', '')) or
                        processdomain(int(target)) not in (
                            'untrusted', 'expanse', 'desktop', 'brick', 'video',
                            'settings', 'snap', 'chromium', 'picker', 'lockscreen')):
                    continue
                os.kill(int(target), chosen)
                signalled.append(int(target))
            except ProcessLookupError:
                continue
            except PermissionError:
                return {'status': 'error', 'message': 'permission denied', 'signalled': signalled}
            except Exception as e:
                print(f'> operations server kill error {e}', file=sys.stderr)
                return {'status': 'error', 'message': 'kill error', 'signalled': signalled}

        if not signalled:
            return {'status': 'error', 'message': 'pid not running'}

    except ProcessLookupError:

        # process not running
        return {'status': 'error', 'message': 'pid not running'}

    except PermissionError:

        # permission denied killing pid
        print(f'> operations server permission denied killing pid {ipid}', file=sys.stderr)
        return {'status': 'error', 'message': 'permission denied'}

    except Exception as e:

        # kill error
        print(f'> operations server kill error {e}', file=sys.stderr)
        return {'status': 'error', 'message': 'kill error'}

    try:

        key = str(ipid)

        with STATELOCK:

            if key in OPMETA:
                OPMETA[key]['state'] = 'killing' if force else 'stopping'

        savestate()

    except Exception:
        pass

    return {
        'status': 'ok',
        'killed': True,
        'force': force,
        'tree': tree,
        'signalled': signalled,
    }


def handlelist(request):

    try:
        cleaned = activeoperations()
        resourcesrequested = bool(request.get('resources', False))
        telemetry = (
            sampletelemetry()
            if resourcesrequested
            else {
                'sampled': time.time(),
                'sample_ms': 0,
                'system': {},
                'processes': processrecords(),
            }
        )
        registered = list(cleaned.keys())

        snapshot = {}

        for pid, info in cleaned.items():


            entry = publicoperation(info)
            entry['pid'] = int(pid)

            entry.setdefault('args', [])
            entry.setdefault('started', None)
            entry.setdefault('state', 'running')
            entry.setdefault('exitcode', None)

            identity, resources = operationresources(pid, registered, telemetry)

            if identity:
                entry['identity'] = identity

            if resourcesrequested and resources is not None:

                entry['resources'] = resources

                try:

                    with STATELOCK:

                        if str(pid) in OPMETA:
                            previouspeak = int(OPMETA[str(pid)].get('peak_memory_bytes', 0))
                            OPMETA[str(pid)]['peak_memory_bytes'] = max(
                                previouspeak,
                                int(resources.get('peak_memory_bytes', 0)),
                            )
                            OPMETA[str(pid)]['identity'] = identity
                            OPMETA[str(pid)]['resources'] = dict(resources)

                except Exception:
                    pass

            snapshot[pid] = entry

    except Exception as e:

        # list snapshot error
        print(f'> operations server list snapshot error {e}', file=sys.stderr)
        return {'status': 'error', 'message': 'snapshot error'}

    try:

        with STATELOCK:
            completed = {key: publicoperation(value) for key, value in COMPLETED.items()}

    except Exception:
        completed = {}

    response = {
        'status': 'ok',
        'version': 2,
        'sampled': float(telemetry.get('sampled', time.time())),
        'sample_ms': int(telemetry.get('sample_ms', 0)),
        'operations': snapshot,
        'completed': completed,
    }

    if resourcesrequested:
        response['system'] = dict(telemetry.get('system', {}))

    return response


def handlewait(request):

    try:

        pid = str(int(request.get('pid')))
        timeout = float(request.get('timeout', 60.0))
        timeout = max(0.0, min(timeout, 3600.0))

    except Exception:
        return {'status': 'error', 'message': 'invalid wait request'}

    peer = request.get('_peer', {})
    with STATELOCK:
        entry = dict(OPMETA.get(pid, COMPLETED.get(pid, {})))
    owner = (
        int(entry.get('_owner_pid', 0) or 0) == int(peer.get('pid', -1)) and
        int(entry.get('_owner_started', -1)) == int(peer.get('started', -2))
    )
    if entry and not owner and peer.get('domain') not in ('window', 'procedures'):
        return {'status': 'error', 'message': 'wait denied'}

    started = time.time()

    while True:

        reaptracked()

        try:

            with STATELOCK:

                if pid in COMPLETED:

                    entry = publicoperation(COMPLETED[pid])
                    return {'status': 'ok', 'operation': entry}

                known = pid in OPMETA
                tracked = pid in PROCESSES

        except Exception:
            known = False
            tracked = False

        if known and not tracked:

            try:
                if not processrunning(pid):
                    raise ProcessLookupError
            except ProcessLookupError:

                recorddone(pid, None, 'completed')
                continue
            except PermissionError:
                pass
            except Exception:
                pass

        if not known:

            try:
                if not processrunning(pid):
                    raise ProcessLookupError
            except ProcessLookupError:
                return {'status': 'ok', 'operation': {'pid': int(pid), 'state': 'completed', 'exitcode': None}}
            except PermissionError:
                pass
            except Exception:
                return {'status': 'error', 'message': 'operation not found'}

        if time.time() - started >= timeout:
            return {'status': 'waiting', 'pid': int(pid)}

        time.sleep(0.05)


def handleunknown(request):

    op = None

    try:

        op = request.get('op', None)

    except Exception:

        op = None

    return {'status': 'error', 'message': f'unknown op {op}'}


def handlerequest(request):

    try:

        op = requestaction(request)

    except Exception as e:

        # handlerequest parse error
        print(f'> operations server handlerequest parse error {e}', file=sys.stderr)
        return {'status': 'error', 'message': 'invalid request'}

    if op == 'BOOTSTRAP':
        return handlebootstrap(request)

    if op == 'VM_TEST_BRICK_EXECUTE':
        return handlevmtestbrickexecute(request)

    if op == 'VM_TEST_LAUNCH':
        return handlevmtestlaunch(request)

    if op == 'VM_TEST_CLOSE':
        return handlevmtestclose(request)

    if op == 'VM_TEST_STATUS':
        return handlevmteststatus(request)

    if op == 'LAUNCH_CATALOGUE':
        return handlelaunchcatalogue(request)

    if op == 'CATALOGUE_LIST':
        return handlecataloguelist(request)

    if op == 'PROCEDURE_LAUNCH':
        return handleprocedurelaunch(request)

    if op.startswith('STARTUP_'):
        return handlestartupconfiguration(request, op)

    if op == 'SESSION_LOGOUT':
        return handlesessionlogout(request)

    if op == 'DESKTOP_CREATE':
        return handledesktopcreate(request)

    if op == 'DESKTOP_RENAME':
        return handledesktoprename(request)

    if op == 'SESSION_LOCK_START':
        return handlesessionlockstart(request)

    if op == 'SESSION_AUTH_VERIFY':
        return handlesessionauth(request)

    if op.startswith('SERVICE_SECRET_'):
        return handleservicesecret(request, op)

    if op == 'SETTINGS_ACCOUNT_GET':
        return handlesettingsaccountget(request)

    if op == 'SETTINGS_AUTH_VERIFY':
        return handlesettingsauth(request)

    if op == 'SETTINGS_MASTER_UPDATE':
        return handlesettingsmasterupdate(request)

    if op == 'SETTINGS_RECOVERY_AUTHORIZE':
        return handlesettingsrecovery(request)

    if op == 'SETTINGS_HOSTNAME_SET':
        return handlesettingshostname(request)

    if op == 'SETTINGS_TIME_SET':
        return handlesettingstime(request)

    if op == 'TIME_SAMPLE_SET':
        return handletimesample(request)

    if op == 'RUN':
        return handlelegacyrun(request)

    if op == 'REGISTER_PID':
        return handleregisterpid(request)

    if op == 'COMPLETE_PID':
        return handlecompletepid(request)

    if op == 'READY_PID':
        return handleready(request)

    if op == 'KILL':
        return handlekill(request)

    if op == 'LIST':
        return handlelist(request)

    if op == 'WAIT':
        return handlewait(request)

    return handleunknown(request)


# signal functions
def handlesigterm(signum, frame):

    global SERVERSTOP

    try:

        SERVERSTOP = True

    except Exception as e:

        # sigterm handler error
        print(f'> operations server sigterm handler error {e}', file=sys.stderr)


def handlesigint(signum, frame):

    global SERVERSTOP

    try:

        SERVERSTOP = True

    except Exception as e:

        # sigint handler error
        print(f'> operations server sigint handler error {e}', file=sys.stderr)


# socket functions
def setupsocket():

    serversock = None

    try:

        sockdir = os.path.dirname(OPERATIONSSOCKET) or '/'

        try:

            os.makedirs(sockdir, mode=0o750, exist_ok=True)
            os.chown(sockdir, 0, DESKTOPGID)
            os.chmod(sockdir, 0o750)

        except PermissionError:

            print('> operations server socket directory permission denied', file=sys.stderr)

        except Exception as e:

            print(f'> operations server socket directory error {e}', file=sys.stderr)

    except Exception as e:

        print(f'> operations server pre socket directory error {e}', file=sys.stderr)

    try:

        if os.path.exists(OPERATIONSSOCKET):

            try:

                os.unlink(OPERATIONSSOCKET)

            except PermissionError:

                print('> operations server permission denied removing existing socket', file=sys.stderr)

            except Exception as e:

                print(f'> operations server unlink socket error {e}', file=sys.stderr)

    except Exception as e:

        print(f'> operations server pre socket cleanup error {e}', file=sys.stderr)

    try:

        serversock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

    except Exception as e:

        print(f'> operations server socket create error {e}', file=sys.stderr)
        return None

    try:

        serversock.bind(OPERATIONSSOCKET)
        # The operations directory is boot-scoped tmpfs. Operations Server is
        # its sole writer; desktop clients only need group traversal and socket
        # access.
        directoryinfo = os.stat(sockdir, follow_symlinks=False)
        if (
            not statmodule.S_ISDIR(directoryinfo.st_mode) or
            directoryinfo.st_uid != 0 or directoryinfo.st_gid != DESKTOPGID or
            directoryinfo.st_mode & (statmodule.S_IWGRP | statmodule.S_IWOTH)
        ):
            raise PermissionError('unsafe operations socket directory')
        os.chown(OPERATIONSSOCKET, 0, DESKTOPGID)
        os.chmod(OPERATIONSSOCKET, 0o660)
        serversock.listen(32)

    except PermissionError:

        print('> operations server bind permission denied', file=sys.stderr)

        serversock.close()
        return None

    except Exception as e:

        print(f'> operations server bind error {e}', file=sys.stderr)

        serversock.close()
        return None


    if hasattr(serversock, 'set_inheritable'):
        serversock.set_inheritable(False)

    return serversock


def acceptloop(serversock):

    global SERVERSTOP
    global LASTREAP

    while True:

        if SERVERSTOP:
            break

        try:

            now = time.time()

            if now - LASTREAP >= REAPINTERVAL:

                reaptracked()
                sampletelemetry()
                LASTREAP = now

        except Exception as e:

            print(f'> operations server periodic update error {e}', file=sys.stderr)


        serversock.settimeout(ACCEPTTIMEOUT)

        conn = None

        try:

            conn, _ = serversock.accept()

        except socket.timeout:

            conn = None

        except InterruptedError:

            conn = None

        except Exception as e:

            print(f'> operations server accept error {e}', file=sys.stderr)
            conn = None

        if conn is None:
            continue

        try:

            peer = {'pid': None, 'uid': None, 'gid': None}

            if hasattr(socket, 'SO_PEERCRED'):

                raw = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize('3i'))
                peer['pid'], peer['uid'], peer['gid'] = struct.unpack('3i', raw)

            t = threading.Thread(target=handleclient, args=(conn, peer), daemon=True)

            t.start()

            continue

        except Exception as e:

            print(f'> operations server thread start error {e}', file=sys.stderr)


        conn.close()

def diagnostic():

    global OPERATIONSROOT, OPERATIONSSTATE, PROCESSES, OPMETA, COMPLETED, READYPENDING
    global GRAPHICSSTATEPATH, GRAPHICSPREVIOUS, GRAPHICSCURRENT, TELEMETRY
    global STARTUPFILE, processstat, processrecords, processdomain

    result = {'passed': False, 'checks': {}, 'errors': []}
    # The CLI diagnostic is launched by Brick and deliberately retains the
    # caller's unprivileged domain. Keep its scratch data in Brick's private
    # runtime rather than granting that subprocess Operations-server authority.
    root = f'/.ephemeral/brick/operations-diagnostic-{os.getpid()}'
    originalroot = OPERATIONSROOT
    originalstate = OPERATIONSSTATE
    originalstartupfile = STARTUPFILE
    originalgraphicspath = GRAPHICSSTATEPATH
    originalgraphicsprevious = dict(GRAPHICSPREVIOUS)
    originalgraphicscurrent = {
        'system': dict(GRAPHICSCURRENT.get('system', {})),
        'processes': dict(GRAPHICSCURRENT.get('processes', {})),
    }
    originalprocessstat = processstat
    originalprocessrecords = processrecords
    originalprocessdomain = processdomain

    def diagnosticprocessstat(target):
        ipid = int(target)
        if ipid == os.getpid():
            state = 'R'
            parent = os.getppid()
        else:
            process = PROCESSES.get(str(ipid))
            if process is None:
                return originalprocessstat(ipid)
            state = 'Z' if process.poll() is not None else 'R'
            parent = os.getpid()
        return {
            'pid': ipid,
            'name': 'operations-diagnostic',
            'state': state,
            'parent': int(parent),
            'ticks': 10,
            'threads': 1,
            'started': ipid * 1000 + 7,
            'rss': 4096,
        }

    def diagnosticprocessrecords():
        pids = [os.getpid(), *(int(value) for value in PROCESSES)]
        records = {}
        for ipid in pids:
            record = processrecord(ipid)
            if record is not None:
                records[str(ipid)] = record
        return records

    def diagnosticprocessdomain(target):
        ipid = int(target)
        tracked = str(ipid) in PROCESSES
        if ipid == os.getpid() or tracked:
            return 'brick'
        return originalprocessdomain(ipid)

    def binddiagnosticmetadata(target, peer):
        record = processrecord(target)
        if record is None:
            raise RuntimeError('diagnostic process identity unavailable')
        with STATELOCK:
            metadata = OPMETA.get(str(int(target)))
            if metadata is None:
                raise RuntimeError('diagnostic process metadata unavailable')
            metadata['_process_identity'] = str(record['identity'])
            metadata['_owner_pid'] = int(peer['pid'])
            metadata['_owner_started'] = int(peer['started'])
            metadata['_session_identity'] = 'operations-diagnostic'

    try:

        shutil.rmtree(root, ignore_errors=True)
        os.makedirs(root, exist_ok=False)
        OPERATIONSROOT = root
        OPERATIONSSTATE = os.path.join(root, 'state.json')
        GRAPHICSSTATEPATH = os.path.join(root, 'graphics.json')
        STARTUPFILE = os.path.join(root, 'startup', 'startup.txt')

        catalogue = handlecataloguelist({'action': 'CATALOGUE_LIST'})
        applications = catalogue.get('applications', [])
        startupnames = {
            str(item.get('name') or '')
            for item in applications
            if isinstance(item, dict) and item.get('startup') is True
        }
        if (
            catalogue.get('status') != 'ok' or not applications or
            not all(isinstance(item, dict) for item in applications) or
            not all(str(item.get('name', '')).lower() == item.get('name', '')
                    for item in applications) or
            startupnames != set(STARTUPAPPLICATIONS)
        ):
            raise RuntimeError('public application catalogue is incomplete')
        result['checks']['application_catalogue'] = True

        startupsoftware = sorted(PROCEDURECATALOGUE)[0]
        addedstartup = handlestartupconfiguration({
            'action': 'STARTUP_ADD', 'software': startupsoftware,
            'mode': 'behind',
        }, 'STARTUP_ADD')
        changedstartup = handlestartupconfiguration({
            'action': 'STARTUP_CHANGE', 'software': startupsoftware,
            'mode': 'front',
        }, 'STARTUP_CHANGE')
        listedstartup = handlestartupconfiguration(
            {'action': 'STARTUP_LIST'}, 'STARTUP_LIST')
        duplicate = handlestartupconfiguration({
            'action': 'STARTUP_ADD', 'software': startupsoftware,
            'mode': 'behind',
        }, 'STARTUP_ADD')
        removedstartup = handlestartupconfiguration({
            'action': 'STARTUP_REMOVE', 'software': startupsoftware,
        }, 'STARTUP_REMOVE')
        if (
            addedstartup.get('status') != 'ok' or
            changedstartup.get('status') != 'ok' or
            listedstartup.get('operations') != [{
                'software': startupsoftware,
                'path': PROCEDURECATALOGUE[startupsoftware]['path'],
                'mode': 'front',
            }] or
            duplicate.get('status') != 'error' or
            removedstartup.get('operations') != []
        ):
            raise RuntimeError('startup operation management failed')
        result['checks']['startup_management'] = True

        diagnosticsettings = os.path.join(root, 'master-settings', 'settings.json')
        writemastersettings({
            'use_master_image': True,
            'image_path': '/master/diagnostic/profile.png',
        }, path=diagnosticsettings)
        diagnosticdirectorystate = os.stat(
            os.path.dirname(diagnosticsettings), follow_symlinks=False)
        diagnosticfilestate = os.stat(
            diagnosticsettings, follow_symlinks=False)
        if (
            statmodule.S_IMODE(diagnosticdirectorystate.st_mode) !=
            MASTERSETTINGSDIRECTORYMODE or
            statmodule.S_IMODE(diagnosticfilestate.st_mode) !=
            MASTERSETTINGSFILEMODE
        ):
            raise RuntimeError('master settings snapshot is not session-readable')
        result['checks']['master_settings_permissions'] = True

        # 2026-07-23 00:00:00 UTC is 10:00 in Sydney.  A VirtualBox RTC stores
        # the first value; physical local-RTC policy stores the second.
        clockepoch = 1784764800
        virtualfields = rtcclockfields(
            clockepoch, DEFAULTTIMEZONE, virtualbox=True)
        hardwarefields = rtcclockfields(
            clockepoch, DEFAULTTIMEZONE, virtualbox=False)
        if (
            virtualfields[:6] != (0, 0, 0, 23, 6, 126) or
            hardwarefields[:6] != (0, 0, 10, 23, 6, 126) or
            rtcfieldsepoch(
                virtualfields, DEFAULTTIMEZONE, virtualbox=True) != clockepoch or
            rtcfieldsepoch(
                hardwarefields, DEFAULTTIMEZONE, virtualbox=False) != clockepoch
        ):
            raise RuntimeError('VirtualBox UTC RTC conversion is incorrect')
        result['checks']['virtualbox_utc_rtc'] = True

        softwarepython = '/software/opengltest2.py'
        if cataloguearguments(
            'brick', ['--run-file', softwarepython]
        ) != ['--run-file', softwarepython]:
            raise RuntimeError('/software Python launch was not preserved')
        try:
            cataloguearguments(
                'brick', ['--run-file', '/software/not-python.txt']
            )
        except ValueError:
            pass
        else:
            raise RuntimeError('non-Python /software launch was accepted')
        result['checks']['software_python_through_brick'] = True

        desktopcreateroot = os.path.join(root, 'desktop-create')
        os.makedirs(desktopcreateroot, exist_ok=False)
        diagnosticowner = (os.getuid(), os.getgid())
        createdfile = createdesktopentry(
            desktopcreateroot, 'file', 'notes.txt', diagnosticowner)
        createdtier = createdesktopentry(
            desktopcreateroot, 'tier', 'work', diagnosticowner)
        try:
            createdesktopentry(
                desktopcreateroot, 'file', 'notes.txt', diagnosticowner)
        except FileExistsError:
            duplicateblocked = True
        else:
            duplicateblocked = False
        renamedfile = renamedesktopentry(
            desktopcreateroot, 'notes.txt', 'journal.txt', diagnosticowner)
        try:
            renamedesktopentry(
                desktopcreateroot, 'journal.txt', 'work', diagnosticowner)
        except FileExistsError:
            overwriteblocked = True
        else:
            overwriteblocked = False
        if (
            os.path.exists(createdfile) or
            not os.path.isfile(renamedfile) or
            not os.path.isdir(createdtier) or
            not duplicateblocked or
            not overwriteblocked
        ):
            raise RuntimeError('scoped desktop creation or rename failed')
        result['checks']['scoped_desktop_creation'] = True
        result['checks']['scoped_desktop_rename'] = True

        with GRAPHICSLOCK:
            GRAPHICSPREVIOUS = {'sampled': 0.0, 'render_total_ms': 0.0, 'frames': 0, 'windows': {}}
            GRAPHICSCURRENT = {'system': {}, 'processes': {}}

        with STATELOCK:
            PROCESSES = {}
            OPMETA = {}
            COMPLETED = {}
            READYPENDING = {}

        processstat = diagnosticprocessstat
        processrecords = diagnosticprocessrecords
        processdomain = diagnosticprocessdomain
        peerrecord = processstat(os.getpid())
        diagnosticpeer = {
            'pid': os.getpid(),
            # The read-only chroot harness enters as root, while this fixture
            # deliberately models the Brick peer that invokes the diagnostic
            # on a live system.
            'uid': DESKTOPUID,
            'gid': DESKTOPGID,
            'started': int(peerrecord['started']),
            'domain': 'brick',
        }
        bootstrappeer = dict(diagnosticpeer)
        bootstrappeer['domain'] = 'goddess'
        bootstraprequest = {
            'op': 'BOOTSTRAP',
            '_peer': bootstrappeer,
            'operations': [{
                'pid': os.getpid(), 'name': 'GODDESS diagnostic',
                'script': os.path.abspath(__file__), 'log': '-',
                'user': 'GODDESS', 'mode': 'behind',
            }],
        }
        firstbootstrap = handlebootstrap(bootstraprequest)
        with STATELOCK:
            firststarted = OPMETA.get(str(os.getpid()), {}).get('started')
        secondbootstrap = handlebootstrap(bootstraprequest)
        with STATELOCK:
            secondstarted = OPMETA.get(str(os.getpid()), {}).get('started')
        if (
            firstbootstrap.get('registered') != 1 or
            secondbootstrap.get('registered') != 1 or
            firststarted != secondstarted
        ):
            raise RuntimeError('GODDESS bootstrap was not idempotent')
        retiredbootstrap = handlebootstrap({
            'op': 'BOOTSTRAP', '_peer': bootstrappeer, 'operations': [],
        })
        with STATELOCK:
            bootstrapretired = str(os.getpid()) not in OPMETA
            COMPLETED.pop(str(os.getpid()), None)
        if retiredbootstrap.get('status') != 'ok' or not bootstrapretired:
            raise RuntimeError('GODDESS bootstrap did not reconcile removals')
        savestate()
        result['checks']['idempotent_goddess_bootstrap'] = True

        completepath = os.path.join(root, 'complete.py')

        with open(completepath, 'w', encoding='utf-8') as stream:
            stream.write("import time\ntime.sleep(0.6)\nprint('operation diagnostic')\n")

        # Exercise the internal lifecycle machinery directly. The public RUN
        # request remains retired and fail-closed in handlerequest().
        started = _disabled_handlerun({
            'op': 'RUN',
            'path': completepath,
            'args': [],
            'name': 'complete diagnostic',
            'log': os.path.join(root, 'complete.log'),
            'user': 'architect',
            'mode': 'behind',
            'state': 'starting',
        })

        pid = int(started.get('pid'))
        binddiagnosticmetadata(pid, diagnosticpeer)

        startinglisting = handlelist({'op': 'LIST'})

        if startinglisting.get('operations', {}).get(str(pid), {}).get('state') != 'starting':
            raise RuntimeError('window-waiting operation was not recorded as starting')

        ready = handleready({'op': 'READY_PID', 'pid': pid})

        if ready.get('status') != 'ok' or not ready.get('changed'):
            raise RuntimeError('starting operation was not promoted by readiness')

        result['checks']['starting_ready_lifecycle'] = True
        graphicstime = time.time()

        with open(GRAPHICSSTATEPATH, 'w', encoding='utf-8') as stream:
            json.dump({
                'sampled': graphicstime,
                'backend': 'opengl',
                'renderer': 'diagnostic GPU',
                'window_compositor': 'gpu',
                'gpu_failed': False,
                'telemetry': {'frames': 100, 'average_render_ms': 1.0},
                'window_telemetry': {
                    'windows': [
                        {'id': 1, 'pid': pid, 'composited_pixels': 1000, 'gpu_draw_calls': 10},
                        {'id': 2, 'pid': 0, 'composited_pixels': 1000, 'gpu_draw_calls': 10},
                    ],
                },
            }, stream, sort_keys=True, separators=(',', ':'))

        graphicstelemetry()

        with open(GRAPHICSSTATEPATH, 'w', encoding='utf-8') as stream:
            json.dump({
                'sampled': graphicstime + 1.0,
                'backend': 'opengl',
                'renderer': 'diagnostic GPU',
                'window_compositor': 'gpu',
                'gpu_failed': False,
                'telemetry': {'frames': 110, 'average_render_ms': 2.0},
                'window_telemetry': {
                    'windows': [
                        {'id': 1, 'pid': pid, 'composited_pixels': 1600, 'gpu_draw_calls': 16},
                        {'id': 2, 'pid': 0, 'composited_pixels': 1400, 'gpu_draw_calls': 14},
                    ],
                },
            }, stream, sort_keys=True, separators=(',', ':'))

        # This diagnostic runs in Brick's unprivileged domain, so it must not
        # widen procfs authority merely to exercise the Operations list schema.
        # Seed a private, deterministic sample after separately validating the
        # graphics telemetry calculation above.
        with TELEMETRYLOCK:
            TELEMETRY = {
                'sampled': time.time(),
                'sample_ms': 1000,
                'system': {
                    'cpu_percent': 4.0,
                    'memory_total_bytes': 1024 * 1024 * 1024,
                    'memory_available_bytes': 768 * 1024 * 1024,
                    'memory_used_bytes': 256 * 1024 * 1024,
                    'gpu_percent': 12.0,
                    'gpu_name': 'diagnostic GPU',
                },
                'processes': {
                    str(pid): {
                        'identity': f'{pid}:diagnostic',
                        'parent': os.getpid(),
                        'cpu_percent': 3.0,
                        'gpu_percent': 7.2,
                        'memory': 16 * 1024 * 1024,
                        'peak_memory': 20 * 1024 * 1024,
                        'threads': 1,
                        'read_bytes': 4096,
                        'write_bytes': 2048,
                    },
                },
            }
        listing = handlelist({'op': 'LIST', 'resources': True})

        if str(pid) not in listing.get('operations', {}):
            raise RuntimeError('started operation was missing from the live list')

        result['checks']['list_running'] = True

        liveentry = listing.get('operations', {}).get(str(pid), {})

        if (
            listing.get('version') != 2
            or not liveentry.get('identity')
            or not isinstance(liveentry.get('resources'), dict)
            or not isinstance(listing.get('system'), dict)
        ):
            raise RuntimeError('versioned resource snapshot is incomplete')

        result['checks']['resource_snapshot'] = True
        systemgpu = listing.get('system', {}).get('gpu_percent')
        processgpu = liveentry.get('resources', {}).get('gpu_percent')

        if (
            abs(float(systemgpu) - 12.0) > 0.01
            or abs(float(processgpu) - 7.2) > 0.01
            or listing.get('system', {}).get('gpu_name') != 'diagnostic GPU'
        ):
            raise RuntimeError('GPU telemetry was not attributed to the operation')

        result['checks']['gpu_telemetry'] = {
            'system_percent': round(float(systemgpu), 2),
            'process_percent': round(float(processgpu), 2),
        }

        denied = handlekill({'op': 'KILL', 'pid': os.getpid(), 'force': True})

        if denied.get('status') != 'error' or denied.get('message') != 'operation not registered':
            raise RuntimeError('unregistered process kill was not denied')

        result['checks']['unregistered_kill_denied'] = True
        waited = handlewait({
            'op': 'WAIT', 'pid': pid, 'timeout': 5.0,
            '_peer': diagnosticpeer,
        })
        operation = waited.get('operation', {})

        if waited.get('status') != 'ok' or operation.get('exitcode') != 0:
            raise RuntimeError('completed operation result was not preserved')

        result['checks']['wait_result'] = True
        listing = handlelist({'op': 'LIST'})

        if str(pid) not in listing.get('completed', {}):
            raise RuntimeError('completed operation was missing from history')

        result['checks']['list_completed'] = True

        with STATELOCK:
            COMPLETED = {}

        if not loadstate() or str(pid) not in COMPLETED:
            raise RuntimeError('completed operation did not survive a service restart')

        result['checks']['boot_scoped_checkpoint'] = True
        killpath = os.path.join(root, 'kill.py')

        with open(killpath, 'w', encoding='utf-8') as stream:
            stream.write('import time\ntime.sleep(30)\n')

        started = _disabled_handlerun({
            'op': 'RUN',
            'path': killpath,
            'args': [],
            'name': 'kill diagnostic',
            'log': os.path.join(root, 'kill.log'),
            'user': 'architect',
            'mode': 'behind',
        })

        killpid = int(started.get('pid'))
        binddiagnosticmetadata(killpid, diagnosticpeer)

        stale = handlekill({
            'op': 'KILL',
            'pid': killpid,
            'identity': f'{killpid}:stale',
            'force': True,
            '_peer': diagnosticpeer,
        })

        if stale.get('status') != 'error' or stale.get('message') != 'operation changed':
            raise RuntimeError(
                f'stale process identity was not denied: {stale!r}')

        result['checks']['stale_identity_denied'] = True
        killed = handlekill({
            'op': 'KILL', 'pid': killpid, 'force': True,
            '_peer': diagnosticpeer,
        })

        if killed.get('status') != 'ok' or not killed.get('killed'):
            raise RuntimeError('force kill request failed')

        waited = handlewait({
            'op': 'WAIT', 'pid': killpid, 'timeout': 5.0,
            '_peer': diagnosticpeer,
        })
        operation = waited.get('operation', {})

        if waited.get('status') != 'ok' or operation.get('state') != 'killed':
            raise RuntimeError('killed operation state was not preserved')

        result['checks']['kill_wait'] = True
        result['passed'] = all(bool(value) for value in result['checks'].values())

    except Exception as e:
        result['errors'].append(str(e))

    finally:

        try:
            reaptracked()
        except Exception:
            pass

        with STATELOCK:

            for proc in list(PROCESSES.values()):

                try:
                    proc.kill()
                except Exception:
                    pass

            PROCESSES = {}
            OPMETA = {}
            COMPLETED = {}
            READYPENDING = {}

        OPERATIONSROOT = originalroot
        OPERATIONSSTATE = originalstate
        STARTUPFILE = originalstartupfile
        GRAPHICSSTATEPATH = originalgraphicspath

        with GRAPHICSLOCK:
            GRAPHICSPREVIOUS = originalgraphicsprevious
            GRAPHICSCURRENT = originalgraphicscurrent

        processstat = originalprocessstat
        processrecords = originalprocessrecords
        processdomain = originalprocessdomain

        shutil.rmtree(root, ignore_errors=True)

    print(json.dumps(result, sort_keys=True, separators=(',', ':')))
    return 0 if result.get('passed') else 1


def main():

    global SERVERSTOP

    initialiseclockfrommotherboard()

    try:
        repairmastersettingspermissions()
    except Exception as error:
        print(
            f'> operations server master settings permission repair error {error}',
            file=sys.stderr,
        )

    loadstate()

    try:

        signal.signal(signal.SIGTERM, handlesigterm)
        signal.signal(signal.SIGINT, handlesigint)

    except Exception as e:

        print(f'> operations server signal handler install error {e}', file=sys.stderr)

    serversock = setupsocket()

    if serversock is None:
        return

    try:

        acceptloop(serversock)

    except Exception as e:

        print(f'> operations server main loop error {e}', file=sys.stderr)


    serversock.close()

    try:

        if os.path.exists(OPERATIONSSOCKET):
            os.unlink(OPERATIONSSOCKET)

    except Exception as e:

        print(f'> operations server socket cleanup error {e}', file=sys.stderr)


if __name__ == '__main__':

    if len(sys.argv) > 1 and sys.argv[1] == 'diagnostic':
        sys.exit(diagnostic())

    main()
