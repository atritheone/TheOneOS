#!"/the one/software/python/bin/python" -B

"""
reign.py

reign provides timekeeping services for The One OS.  The system clock is
initialised from the motherboard RTC; optional internet time keeps it accurate.
"""



# imports
import datetime
import os
import socket
import stat as statmodule
import struct
import threading
import time
import zoneinfo



# globals
SYSTEMROOT = os.environ.get('T1OS_SYSTEM_ROOT', '/the one')
COMMONTIMEFILE = os.path.join(SYSTEMROOT, 'settings', 'time', 'common.txt')
ATREYANTIMEFILE = os.path.join(SYSTEMROOT, 'settings', 'time', 'atreyan.txt')
INTERNETTIMEFILE = os.path.join(SYSTEMROOT, 'settings', 'time', 'internet.txt')
TIMEZONEFILE = os.path.join(SYSTEMROOT, 'settings', 'time', 'timezone.txt')
ZONEINFODIR = os.path.join(SYSTEMROOT, 'software', 'chromium', 'resources', 'zoneinfo')
DEFAULTTIMEZONE = 'Australia/Sydney'
AE_START_YEAR = 2021
TIMETIER = os.path.dirname(COMMONTIMEFILE)
NTP_SERVER = 'pool.ntp.org'
NTP_PORT = 123
NTP_TIMEOUT = 3.0
NTP_EPOCH = 2208988800
NTP_SYNC_INTERVAL = 6 * 60 * 60
NTP_RETRY_INTERVAL = 60
RTC_SET_TIME = 0x4024700A
RTC_RD_TIME = 0x80247009
TIMEOUTPUTS = frozenset((COMMONTIMEFILE, ATREYANTIMEFILE))
TIMEOUTPUTMAXIMUM = 128
CLOCKMUTATIONUNAVAILABLE = (
    'clock mutation is owned by Operations and is not available from reign'
)
_TIMEZONENAME = None
_TIMEZONE = None


# time functions
def readtimezone():

    try:

        with open(TIMEZONEFILE, 'r', encoding='utf-8') as f:

            name = f.read().strip()

    except Exception:

        return DEFAULTTIMEZONE

    # Migrate the old numeric Sydney offset without preserving its DST bug.
    if name in ('10', '+10'):
        return DEFAULTTIMEZONE

    return name or DEFAULTTIMEZONE


def timezonepath(name):

    name = str(name or '').strip().replace('\\', '/')

    if not name or name.startswith('/') or any(part in ('', '.', '..') for part in name.split('/')):
        raise ValueError('invalid timezone name')

    roots = [ZONEINFODIR]
    sourcezoneinfo = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                                  'software', 'chromium', 'resources', 'zoneinfo')
    if sourcezoneinfo not in roots:
        roots.append(sourcezoneinfo)

    for root in roots:

        root = os.path.realpath(root)
        path = os.path.realpath(os.path.join(root, *name.split('/')))

        try:

            inside = os.path.commonpath((root, path)) == root

        except ValueError:

            inside = False

        if inside and os.path.isfile(path):
            return path

    raise ValueError(f'unknown timezone {name}')


def timezoneinfo(name=None):

    global _TIMEZONENAME, _TIMEZONE
    name = str(name or readtimezone()).strip()

    if name == _TIMEZONENAME and _TIMEZONE is not None:
        return _TIMEZONE

    try:

        with open(timezonepath(name), 'rb') as f:

            value = zoneinfo.ZoneInfo.from_file(f, key=name)

    except Exception:

        name = DEFAULTTIMEZONE

        try:

            with open(timezonepath(name), 'rb') as f:

                value = zoneinfo.ZoneInfo.from_file(f, key=name)

        except Exception:

            value = datetime.timezone.utc

    _TIMEZONENAME, _TIMEZONE = name, value
    return value


def internettimeenabled():

    try:

        with open(INTERNETTIMEFILE, 'r') as f:

            return f.read().strip().lower() in ('1', 'true', 'yes', 'on')

    except Exception:

        return False


def queryinternettime(server=NTP_SERVER, timeout=NTP_TIMEOUT):

    # A minimal SNTP request.  The transmit timestamp in the reply is seconds
    # since 1900; convert it to the Unix epoch used by CLOCK_REALTIME.
    request = b'\x1b' + (47 * b'\0')
    addresses = socket.getaddrinfo(server, NTP_PORT, type=socket.SOCK_DGRAM)
    last_error = None

    for family, socktype, protocol, canonical, address in addresses:

        channel = socket.socket(family, socktype, protocol)

        try:

            channel.settimeout(float(timeout))
            channel.sendto(request, address)
            response = channel.recv(512)

            if len(response) < 48:
                raise ValueError('short internet time response')

            leap = response[0] >> 6
            mode = response[0] & 0x07
            stratum = response[1]

            if leap == 3 or mode not in (4, 5) or not 1 <= stratum <= 15:
                raise ValueError('invalid internet time response')

            seconds, fraction = struct.unpack('!II', response[40:48])
            epoch = seconds - NTP_EPOCH + (fraction / float(1 << 32))

            if epoch <= 0:
                raise ValueError('invalid internet time timestamp')

            return epoch

        except Exception as e:

            last_error = e

        finally:

            channel.close()

    if last_error:
        raise last_error

    raise OSError('internet time server has no usable address')


def syncinternettime():

    # Reign deliberately has no clock-mutation authority.  Do not turn an
    # unauthenticated network sample into a generic clock-setting capability.
    raise PermissionError(CLOCKMUTATIONUNAVAILABLE)


def rtcnodes():

    return (
        os.path.join(SYSTEMROOT, 'drivers', 'nodes', 'rtc0'),
        os.path.join(SYSTEMROOT, 'drivers', 'nodes', 'rtc'),
    )


def localrtcepoch(year, month, day, hour, minute, second, name=None):

    wallclock = datetime.datetime(int(year), int(month), int(day), int(hour),
                                  int(minute), int(second))
    zone = timezoneinfo(name)
    candidates = []

    for fold in (0, 1):

        candidate = wallclock.replace(tzinfo=zone, fold=fold)
        epoch = candidate.timestamp()

        if datetime.datetime.fromtimestamp(epoch, zone).replace(tzinfo=None) == wallclock:
            candidates.append(epoch)

    if not candidates:
        raise ValueError(f'motherboard time does not exist in {getattr(zone, "key", name)}')

    # A local RTC cannot distinguish the repeated hour at the end of daylight
    # saving. Prefer the later (standard-time) occurrence so boot does not move
    # the system clock backwards after that transition.
    return max(candidates)


def readmotherboardclock(name=None):

    try:

        import fcntl

    except ImportError:

        raise OSError('this platform does not provide RTC control')

    last_error = None

    for node in rtcnodes():

        try:

            descriptor = os.open(node, os.O_RDONLY)

            try:

                value = bytearray(struct.calcsize('9i'))
                fcntl.ioctl(descriptor, RTC_RD_TIME, value, True)
                second, minute, hour, day, month, year, _, _, _ = struct.unpack('9i', value)
                return localrtcepoch(year + 1900, month + 1, day, hour, minute,
                                     second, name)

            finally:

                os.close(descriptor)

        except OSError as error:

            last_error = error

    if last_error is not None:
        raise last_error

    raise FileNotFoundError('motherboard RTC is unavailable')


def initialisemotherboardtime(name=None):

    del name
    raise PermissionError(CLOCKMUTATIONUNAVAILABLE)


def motherboardclockfields(epoch, name=None):

    local = datetime.datetime.fromtimestamp(float(epoch), timezoneinfo(name))
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

    del epoch, name
    raise PermissionError(CLOCKMUTATIONUNAVAILABLE)


def currentdatetime(epoch=None):

    # The hardware, VirtualBox and SNTP all provide an absolute system timestamp.
    # The named zone is applied only when producing a local wall-clock value.
    return datetime.datetime.fromtimestamp(time.time() if epoch is None else epoch, timezoneinfo())


def currenttime(epoch=None):

    return currentdatetime(epoch).timetuple()


def formatatreyandate(value):

    ae_year = value.tm_year - (AE_START_YEAR - 1)
    return f'{value.tm_mday:02}:{value.tm_mon:02}:{ae_year}AE'


def writetimeoutput(path, value):

    if path not in TIMEOUTPUTS:
        raise PermissionError('reign time output path denied')
    if not isinstance(value, str) or not value or '\n' in value or '\x00' in value:
        raise ValueError('invalid reign time output')
    payload = value.encode('ascii', errors='strict')
    if len(payload) > TIMEOUTPUTMAXIMUM:
        raise ValueError('reign time output is too large')

    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0) |
        getattr(os, 'O_CLOEXEC', 0),
        0o644,
    )
    try:
        status = os.fstat(descriptor)
        if (
            not statmodule.S_ISREG(status.st_mode)
            or status.st_uid != 0
            or status.st_gid != 0
            or status.st_nlink != 1
        ):
            raise PermissionError('reign time output metadata is unsafe')
        os.fchmod(descriptor, 0o644)
        if statmodule.S_IMODE(os.fstat(descriptor).st_mode) != 0o644:
            raise PermissionError('reign time output mode is unsafe')
        os.ftruncate(descriptor, 0)
        os.lseek(descriptor, 0, os.SEEK_SET)
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise OSError('short write publishing reign time output')
            offset += written
        os.ftruncate(descriptor, len(payload))
    finally:
        os.close(descriptor)


def writecommon():

    t = currenttime()

    # format the time
    s = f"{formatatreyandate(t)} {time.strftime('%H:%M:%S', t)}"

    try:

        writetimeoutput(COMMONTIMEFILE, s)

    except FileNotFoundError as e:

        # commom time file not found error
        print('common time file not found', flush=True)

    except PermissionError:

        # permission denied error
        print('permission denied to write common time file', flush=True)

    except OSError as e:

        # other errors
        print(f'error writing common time {e}', flush=True)


def writeatreyan():

    t = currenttime()

    # convert 24-hour clock to 12-hour clock
    hour = t.tm_hour % 12
    if hour == 0:
        hour = 12

    # format minutes
    minute = f"{t.tm_min:02}"

    # determine am or pm
    ampm = 'am' if t.tm_hour < 12 else 'pm'

    # build the atreyan time
    s = f"{hour}:{minute} {ampm} {formatatreyandate(t)}"

    try:

        writetimeoutput(ATREYANTIMEFILE, s)

    except FileNotFoundError as e:

        # atreyan time file not found error
        print('atreyan time file not found', flush=True)

    except PermissionError:

        # permission denied error
        print('permission denied to write atreyan time file', flush=True)

    except OSError as e:

        # other errors
        print(f'error writing atreyan time {e}', flush=True)


def internettimeservice():

    unavailableannounced = False

    while True:

        internet_enabled = internettimeenabled()

        if internet_enabled and not unavailableannounced:
            print(f'internet time unavailable {CLOCKMUTATIONUNAVAILABLE}', flush=True)
            unavailableannounced = True
        elif not internet_enabled:
            unavailableannounced = False

        time.sleep(1)


def timekeeper():

    # Keep network waits off this loop so the on-disk clocks still advance every
    # second while an internet server or DNS is unavailable.
    threading.Thread(target=internettimeservice, name='internet-time', daemon=True).start()

    while True:

        # write the common era time
        writecommon()

        # write the atreyan era time
        writeatreyan()

        # repeat every second
        time.sleep(1)


def timestamp(epoch=None):

    t = currenttime(epoch)

    # convert to 12-hr clock
    hour = t.tm_hour % 12
    if hour == 0:
        hour = 12

    # zero-pad minutes and seconds
    minute = f"{t.tm_min:02}"
    second = f"{t.tm_sec:02}"

    # am/pm tag
    ampm = 'AM' if t.tm_hour < 12 else 'PM'

    # build bracketed stamp with seconds
    return f'[{formatatreyandate(t)} {hour}:{minute}:{second} {ampm}]'


def initialise():

    try:

        os.makedirs(TIMETIER, exist_ok=True)

    except PermissionError:

        print('permission denied creating time tier', flush=True)

    except OSError as e:

        print(f'error creating time tier {e}', flush=True)

    # Internet time is deliberately opt-in so an offline machine always starts
    # from the motherboard clock without waiting for a network connection.
    if not os.path.exists(INTERNETTIMEFILE):
        try:

            with open(INTERNETTIMEFILE, 'w') as f:

                f.write('false\n')

        except FileNotFoundError:

            print('time settings tier not found', flush=True)

        except PermissionError:

            print('permission denied writing internet time setting', flush=True)

        except OSError as e:

            print(f'error writing internet time setting {e}', flush=True)


initialise()


if __name__ == '__main__':

    # write common on launch
    writecommon()

    # write atreyan on launch
    writeatreyan()

    # run timekeeper
    timekeeper()
