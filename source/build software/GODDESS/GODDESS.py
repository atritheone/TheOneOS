#!"/the one/software/python/bin/python" -B
"""
GODDESS.py

GODDESS is the mind of The One OS.
"""

## imports
import os
import re
import sys
import time
import json
import signal
import ctypes
import socket
import select
import struct
import threading
import subprocess
import fcntl
import termios
import uuid
import stat as statmodule
import shutil
import errno

sys.path.insert(0, '/the one/build')
from reign.reign import (
    timestamp,
)


def attachserialconsole():

    """Attach PID 1 standard streams to the exact optional serial console."""

    if __name__ != '__main__':
        return False
    node = '/the one/drivers/nodes/ttyS0'
    descriptor = None
    try:
        descriptor = os.open(
            node,
            os.O_RDWR | getattr(os, 'O_NOCTTY', 0) |
            getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_CLOEXEC', 0),
        )
        metadata = os.fstat(descriptor)
        if not statmodule.S_ISCHR(metadata.st_mode):
            raise OSError('serial console is not a character device')
        for standard in (0, 1, 2):
            os.dup2(descriptor, standard, inheritable=True)
        return True
    except OSError:
        return False
    finally:
        if descriptor is not None and descriptor > 2:
            os.close(descriptor)


# Establish the durable diagnostic stream before any speech or tty0 mirror is
# constructed. Graphics ownership may later make tty0 block or return EIO, but
# it must never take the release/readiness UART down with it.
attachserialconsole()

SYSTEMROOT = os.environ.get('T1OS_SYSTEM_ROOT', '/the one')
POWERCONTROLSOCKET = '/.ephemeral/power/control.sock'
VALIDPOWERACTIONS = frozenset(('poweroff', 'restart'))
VALIDRECOVERYACTIONS = frozenset(('python', 'build', 'reset', 'reinstall'))
DESTRUCTIVERECOVERYACTIONS = frozenset(('reset', 'reinstall'))
RECOVERYBOOTMOUNT = '/.ephemeral/angel-boot'
RECOVERYREQUEST = os.path.join(RECOVERYBOOTMOUNT, 'T1OS', 'recovery-request')
SHUTDOWNHEALTHREQUEST = os.path.join(
    RECOVERYBOOTMOUNT, 'T1OS', 'roothealth-shutdown-request')
SESSIONIDENTITY = '/the one/settings/session/identity.json'


def _normaliseownedtree(
        descriptor, *, directorymode=0o700, filemode=None,
        rootownedfiles=()):

    """Normalize an existing tree without following links or flattening modes."""

    os.fchown(descriptor, T1OS_DESKTOP_UID, T1OS_DESKTOP_GID)
    os.fchmod(descriptor, directorymode)
    for name in os.listdir(descriptor):
        if name in ('.', '..') or '/' in name or '\x00' in name:
            raise OSError('unsafe owned-tree entry')
        status = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
        if statmodule.S_ISDIR(status.st_mode):
            child = os.open(
                name,
                os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0) |
                getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_CLOEXEC', 0),
                dir_fd=descriptor,
            )
            try:
                _normaliseownedtree(
                    child, directorymode=directorymode, filemode=filemode)
            finally:
                os.close(child)
        elif statmodule.S_ISREG(status.st_mode):
            if name in rootownedfiles:
                if (
                    status.st_uid != 0 or status.st_gid != 0 or
                    status.st_nlink != 1 or
                    statmodule.S_IMODE(status.st_mode) != 0o644
                ):
                    raise PermissionError(
                        f'protected root-owned output is unsafe: {name}')
                # Goddess verifies these endpoints but never changes or writes
                # them. Reign owns all content publication through the exact
                # LSM path allowance.
                continue
            owner = (
                (T1OS_DESKTOP_UID, T1OS_DESKTOP_GID)
            )
            os.chown(
                name, owner[0], owner[1],
                dir_fd=descriptor, follow_symlinks=False)
            # Preserve owner read/write/execute and all read/execute semantics;
            # remove only set-id and group/other write authority.
            if filemode is None:
                mode = statmodule.S_IMODE(status.st_mode)
                mode &= ~(statmodule.S_ISUID | statmodule.S_ISGID | 0o022)
            else:
                mode = int(filemode)
            os.chmod(name, mode, dir_fd=descriptor, follow_symlinks=False)
        elif statmodule.S_ISLNK(status.st_mode):
            os.chown(
                name, T1OS_DESKTOP_UID, T1OS_DESKTOP_GID,
                dir_fd=descriptor, follow_symlinks=False)


def normaliseservicesettings():

    """Publish non-secret settings to their root boot-time consumers."""

    settingsroot = '/the one/settings'
    os.chown(settingsroot, 0, 0, follow_symlinks=False)
    os.chmod(settingsroot, 0o755, follow_symlinks=False)
    for relative in ('audio', 'display', 'mouse', 'network', 'time'):
        path = os.path.join(settingsroot, relative)
        if not os.path.exists(path):
            os.mkdir(path, mode=0o755)
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0) |
            getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_CLOEXEC', 0),
        )
        try:
            if relative == 'time':
                defaults = (
                    ('internet.txt', b'false\n'),
                    ('virtualbox.txt', b'true\n'),
                    ('timezone.txt', b'Australia/Sydney\n'),
                )
                for name, value in defaults:
                    try:
                        setting = os.open(
                            name,
                            os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                            getattr(os, 'O_NOFOLLOW', 0) |
                            getattr(os, 'O_CLOEXEC', 0),
                            0o644,
                            dir_fd=descriptor,
                        )
                    except FileExistsError:
                        continue
                    try:
                        if os.write(setting, value) != len(value):
                            raise OSError('short write publishing time default')
                        os.fsync(setting)
                    finally:
                        os.close(setting)
                # Establish the protected publication endpoints without ever
                # opening them for write. The kernel permits PID 1 to create
                # only these two empty regular inodes; Reign is their writer.
                for name in ('common.txt', 'atreyan.txt'):
                    try:
                        os.mknod(
                            name, statmodule.S_IFREG | 0o644,
                            dir_fd=descriptor)
                    except FileExistsError:
                        pass
            # These are service-consumed, non-secret settings.  The desktop
            # Settings process owns mutation, while boot services must be able
            # to traverse and read them without broad DAC-bypass capability.
            # The desktop owns the three user-selectable policy inputs. Reign
            # exclusively publishes these two derived clock outputs and
            # validates that they remain root-owned before every update.
            rootownedfiles = (
                ('common.txt', 'atreyan.txt') if relative == 'time' else ()
            )
            _normaliseownedtree(
                descriptor, directorymode=0o755, filemode=0o644,
                rootownedfiles=rootownedfiles)
            if relative == 'network':
                # Network atomically replaces only its exact LSM-authorized DNS
                # output; the directory DAC must permit its root-owned temp.
                os.fchmod(descriptor, 0o777)
        finally:
            os.close(descriptor)


def normalisedesktopsettings():

    """Repair persistent application state before uid 1000 launches."""

    settingsroot = '/the one/settings'
    for relative in (
        'array',
        'brick',
        'chromium',
        'expanse',
        'operations centre',
    ):
        path = os.path.join(settingsroot, relative)
        os.makedirs(path, mode=0o700, exist_ok=True)
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0) |
            getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_CLOEXEC', 0),
        )
        try:
            _normaliseownedtree(
                descriptor, directorymode=0o700, filemode=0o600)
        finally:
            os.close(descriptor)


def normaliseexistingdesktopownership(masterfile='/the one/master/master.txt'):

    """Repair safe ownership boundaries on upgraded installations."""

    from broker import broker as authbroker

    username, _credentialhash = authbroker.read_credentials(masterfile)
    username = authbroker.canonicalize_username(username)
    masterbase = os.open(
        '/master',
        os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0) |
        getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_CLOEXEC', 0),
    )
    try:
        os.fchown(masterbase, 0, 0)
        os.fchmod(masterbase, 0o755)
        userhome = os.open(
            username,
            os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0) |
            getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_CLOEXEC', 0),
            dir_fd=masterbase,
        )
        try:
            _normaliseownedtree(userhome)
        finally:
            os.close(userhome)
    finally:
        os.close(masterbase)

    normaliseservicesettings()
    return username


def publishsessionidentity(masterfile='/the one/master/master.txt'):

    """Publish the username only; credential hashes remain root-confined."""

    from broker import broker as authbroker

    username, _credentialhash = authbroker.read_credentials(masterfile)
    username = authbroker.canonicalize_username(username)
    payload = json.dumps(
        {'format': 1, 'username': username},
        sort_keys=True,
        separators=(',', ':'),
    ).encode('utf-8') + b'\n'
    directory = os.path.dirname(SESSIONIDENTITY)
    os.makedirs(directory, mode=0o750, exist_ok=True)
    os.chown(directory, 0, T1OS_DESKTOP_GID)
    os.chmod(directory, 0o750)
    temporary = f'{SESSIONIDENTITY}.new.{os.getpid()}.{uuid.uuid4().hex}'
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL |
        getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_CLOEXEC', 0),
        0o640,
    )
    try:
        os.fchown(descriptor, 0, T1OS_DESKTOP_GID)
        os.fchmod(descriptor, 0o640)
        offset = 0
        while offset < len(payload):
            offset += os.write(descriptor, payload[offset:])
        os.fsync(descriptor)
    except Exception:
        os.close(descriptor)
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    else:
        os.close(descriptor)
    os.replace(temporary, SESSIONIDENTITY)
    directorydescriptor = os.open(
        directory,
        os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0) |
        getattr(os, 'O_CLOEXEC', 0),
    )
    try:
        os.fsync(directorydescriptor)
    finally:
        os.close(directorydescriptor)
    return {'format': 1, 'username': username}


def formatlog(software, message, epoch=None):

    name = ' '.join(str(software).strip().strip('[]').split()) or 'unknown'
    stamp = timestamp(epoch)
    marker = f'] [{name}] '
    legacy = f'T1OS {name}:'
    lines = []

    for text in str(message).splitlines() or ['']:
        if text.startswith('[') and marker in text:
            text = text.split(marker, 1)[1]
        if text.lower().startswith(legacy.lower()):
            text = text[len(legacy):].lstrip()
        if text.startswith('> '):
            text = text[2:]
            if text.lower().startswith(name.lower() + ' '):
                text = text[len(name):].lstrip()
        lines.append(text)

    return '\n'.join(f'{stamp} [{name}] {line}' for line in lines)


def emitlog(software, message, file=None):

    print(formatlog(software, message), file=file, flush=True)


def softwarelogpath(softwarepath, logpath=None):

    """Return the exclusive stdout/stderr log for a software process."""

    requested = str(logpath or '').strip()

    if requested and requested != '-':
        return requested

    name = os.path.basename(str(softwarepath or '').rstrip('/\\'))

    if not name:
        name = 'unknown'

    return os.path.join(SYSTEMROOT, 'logs', f'{name}.log')


class _LazyLogPopen(subprocess.Popen):

    """A process whose combined output creates its log on first write."""

    def __init__(self, command, logpath, **options):

        self.logpath = logpath
        self.logerror = None
        self._logthread = None
        self._outputlock = threading.Lock()
        self._outputtail = bytearray()
        readdescriptor, writedescriptor = os.pipe()

        try:
            super().__init__(
                command,
                stdout=writedescriptor,
                stderr=subprocess.STDOUT,
                **options,
            )
        except BaseException:
            os.close(readdescriptor)
            os.close(writedescriptor)
            raise

        os.close(writedescriptor)
        self._logthread = threading.Thread(
            target=self._copyoutput,
            args=(readdescriptor,),
            name=f't1os log {self.pid}',
            daemon=True,
        )
        self._logthread.start()

    def _copyoutput(self, descriptor):

        stream = None
        outputavailable = True

        try:
            while True:
                try:
                    block = os.read(descriptor, 65536)
                except OSError as error:
                    self.logerror = error
                    break

                if not block:
                    break

                with self._outputlock:
                    self._outputtail.extend(block)
                    if len(self._outputtail) > 65536:
                        del self._outputtail[:-65536]

                if stream is None and outputavailable:
                    try:
                        directory = os.path.dirname(self.logpath)
                        if directory:
                            os.makedirs(directory, exist_ok=True)
                        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT
                        logdescriptor = os.open(self.logpath, flags, 0o600)
                        try:
                            os.fchmod(logdescriptor, 0o600)
                            stream = os.fdopen(
                                logdescriptor,
                                'ab',
                                buffering=0,
                            )
                        except BaseException:
                            os.close(logdescriptor)
                            raise
                    except OSError as error:
                        # Continue draining the pipe so a log-path failure can
                        # never block or terminate the software process.
                        self.logerror = error
                        outputavailable = False

                if stream is not None:
                    try:
                        stream.write(block)
                    except OSError as error:
                        self.logerror = error
                        stream.close()
                        stream = None
                        outputavailable = False
        finally:
            if stream is not None:
                stream.close()
            os.close(descriptor)

    def outputtail(self):

        with self._outputlock:
            return bytes(self._outputtail)

    def wait(self, timeout=None):

        started = time.monotonic()
        returncode = super().wait(timeout=timeout)
        thread = self._logthread

        if thread is not None:
            remaining = None
            if timeout is not None:
                remaining = max(0.0, timeout - (time.monotonic() - started))
            thread.join(remaining)

        return returncode


T1OS_PR_SET_DOMAIN = 0x54510001
T1OS_PR_SET_NO_NEW_PRIVS = 38
T1OS_PR_SET_DUMPABLE = 4
T1OS_PR_CAPBSET_DROP = 24
T1OS_PR_CAP_AMBIENT = 47
T1OS_PR_CAP_AMBIENT_CLEAR_ALL = 4
T1OS_LINUX_CAPABILITY_VERSION_3 = 0x20080522
T1OS_DESKTOP_UID = 1000
T1OS_DESKTOP_GID = 1000
T1OS_PYTHON_EXECUTABLE = '/the one/software/python/bin/python'
T1OS_SECURITY_PROFILES = {
    'untrusted': 0,
    'goddess': 1,
    'startup': 2,
    'architect': 3,
    'operations': 4,
    'procedures': 5,
    'window': 6,
    'brick': 7,
    'audio': 8,
    'driver': 9,
    'input': 10,
    'network': 11,
    'reign': 12,
    'python': 13,
    'exchange': 14,
    'expanse': 15,
    'virtualbox': 16,
    'boot-animation': 17,
    'desktop': 18,
    'video': 19,
    'settings': 20,
    'maintenance': 21,
    'module-loader': 22,
    'snap': 23,
    'chromium': 24,
    'picker': 25,
    'lockscreen': 26,
}


def securityprofileid(profile):

    name = str(profile or '').strip().lower()
    if name not in T1OS_SECURITY_PROFILES:
        raise ValueError(f'unknown T1OS security profile {profile!r}')
    return int(T1OS_SECURITY_PROFILES[name])


def securitytransition(profile, descriptor, interpreterdescriptor=0):

    """Request a kernel-verified, non-argv security-domain transition."""

    profileid = securityprofileid(profile)
    operation = libc.prctl
    operation.argtypes = (
        ctypes.c_int,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_ulong,
    )
    operation.restype = ctypes.c_int
    ctypes.set_errno(0)
    result = operation(
        T1OS_PR_SET_DOMAIN,
        profileid,
        int(descriptor),
        int(interpreterdescriptor),
        0,
    )
    if result != 0:
        errornumber = ctypes.get_errno() or errno.EPERM
        raise PermissionError(
            errornumber,
            f'The One OS kernel rejected the {profile} security profile',
        )


class _T1OSCapabilityHeader(ctypes.Structure):

    _fields_ = (
        ('version', ctypes.c_uint32),
        ('pid', ctypes.c_int),
    )


class _T1OSCapabilityData(ctypes.Structure):

    _fields_ = (
        ('effective', ctypes.c_uint32),
        ('permitted', ctypes.c_uint32),
        ('inheritable', ctypes.c_uint32),
    )


def _clearprocesscapabilities():

    header = _T1OSCapabilityHeader(T1OS_LINUX_CAPABILITY_VERSION_3, 0)
    data = (_T1OSCapabilityData * 2)()
    operation = libc.capset
    operation.argtypes = (
        ctypes.POINTER(_T1OSCapabilityHeader),
        ctypes.POINTER(_T1OSCapabilityData),
    )
    operation.restype = ctypes.c_int
    ctypes.set_errno(0)
    if operation(ctypes.byref(header), data) != 0:
        errornumber = ctypes.get_errno() or errno.EPERM
        raise PermissionError(errornumber, 'could not clear process capabilities')

    ctypes.set_errno(0)
    if libc.prctl(
            T1OS_PR_CAP_AMBIENT, T1OS_PR_CAP_AMBIENT_CLEAR_ALL,
            0, 0, 0) != 0:
        errornumber = ctypes.get_errno() or errno.EPERM
        raise PermissionError(errornumber, 'could not clear ambient capabilities')


def _dropcapabilityboundingset():

    # Linux currently defines fewer than 64 capabilities.  EINVAL is the
    # documented response for numbers beyond CAP_LAST_CAP; every real drop
    # must succeed while the launcher still has CAP_SETPCAP.
    for capability in range(64):
        ctypes.set_errno(0)
        if libc.prctl(T1OS_PR_CAPBSET_DROP, capability, 0, 0, 0) == 0:
            continue
        errornumber = ctypes.get_errno() or errno.EPERM
        if errornumber != errno.EINVAL:
            raise PermissionError(
                errornumber, 'could not clear capability bounding set')


def _dropbaseidentity(*, drop_bounding, no_new_privileges):

    if os.geteuid() == 0:
        os.setgroups([])
        if drop_bounding:
            _dropcapabilityboundingset()
        os.setresgid(T1OS_DESKTOP_GID, T1OS_DESKTOP_GID, T1OS_DESKTOP_GID)
        os.setresuid(T1OS_DESKTOP_UID, T1OS_DESKTOP_UID, T1OS_DESKTOP_UID)
    else:
        if (tuple(os.getresuid()) != (T1OS_DESKTOP_UID,) * 3 or
                tuple(os.getresgid()) != (T1OS_DESKTOP_GID,) * 3 or
                os.getgroups()):
            raise PermissionError('desktop identity is not already confined')
    _clearprocesscapabilities()
    os.umask(0o077)
    ctypes.set_errno(0)
    if libc.prctl(T1OS_PR_SET_DUMPABLE, 0, 0, 0, 0) != 0:
        errornumber = ctypes.get_errno() or errno.EPERM
        raise PermissionError(errornumber, 'could not disable process dumps')
    if not no_new_privileges:
        return
    ctypes.set_errno(0)
    if libc.prctl(T1OS_PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
        errornumber = ctypes.get_errno() or errno.EPERM
        raise PermissionError(errornumber, 'could not enable no_new_privs')


def dropdesktopidentity():

    """Irreversibly enter the ordinary desktop uid/gid before exec."""

    _dropbaseidentity(drop_bounding=True, no_new_privileges=True)


def dropchromiumidentity():

    """Enter Chromium's uid without disabling its fixed setuid sandbox.

    The kernel transition policy accepts this exception only for the measured
    Chromium script/domain.  The setuid sandbox needs the bounding set and must
    be able to raise privilege once, so no_new_privs is intentionally deferred
    to that sandbox.  Effective, permitted, inheritable, and ambient sets are
    still cleared before the first Python opcode.
    """

    _dropbaseidentity(drop_bounding=False, no_new_privileges=False)


def _securedpreexec(profile, descriptor, interpreterdescriptor=0, previous=None):

    def applyprofile():

        if previous is not None:
            previous()
        # Identity/capability reduction must happen while the child still has
        # its inherited, immutable launcher domain.  The kernel consumes the
        # descriptor authorization last; there is no target-domain authority
        # until exec commits, and a failed transition aborts the child launch.
        securitytransition(profile, descriptor, interpreterdescriptor)

    return applyprofile


def _securedlaunchoptions(softwarepath, security_profile, options):

    """Bind a launch profile to an already-open immutable software object."""

    options = dict(options)
    options.setdefault('close_fds', True)
    if security_profile is None:
        return options, ()

    flags = os.O_RDONLY | getattr(os, 'O_CLOEXEC', 0) | getattr(os, 'O_NOFOLLOW', 0)
    descriptor = os.open(str(softwarepath), flags)
    opened = os.fstat(descriptor)
    pathname = os.stat(str(softwarepath), follow_symlinks=False)
    if not statmodule.S_ISREG(opened.st_mode):
        os.close(descriptor)
        raise PermissionError('security-profile software is not a regular file')
    if (opened.st_dev, opened.st_ino) != (pathname.st_dev, pathname.st_ino):
        os.close(descriptor)
        raise PermissionError('security-profile software changed while opening')
    if (opened.st_uid != 0 or opened.st_nlink != 1 or
            opened.st_mode & (statmodule.S_IWGRP | statmodule.S_IWOTH)):
        os.close(descriptor)
        raise PermissionError('security-profile software ownership is unsafe')

    descriptors = [descriptor]
    interpreterdescriptor = 0
    if str(softwarepath).endswith('.py'):
        interpreterdescriptor = os.open(T1OS_PYTHON_EXECUTABLE, flags)
        interpreter = os.fstat(interpreterdescriptor)
        interpreterpath = os.stat(
            T1OS_PYTHON_EXECUTABLE, follow_symlinks=False)
        if (not statmodule.S_ISREG(interpreter.st_mode) or
                (interpreter.st_dev, interpreter.st_ino) !=
                (interpreterpath.st_dev, interpreterpath.st_ino) or
                interpreter.st_uid != 0 or interpreter.st_nlink != 1 or
                interpreter.st_mode &
                (statmodule.S_IWGRP | statmodule.S_IWOTH)):
            os.close(interpreterdescriptor)
            os.close(descriptor)
            raise PermissionError('profile interpreter ownership is unsafe')
        descriptors.append(interpreterdescriptor)

    inherited = tuple(int(value) for value in options.get('pass_fds', ()))
    options['pass_fds'] = inherited + tuple(descriptors)
    options['preexec_fn'] = _securedpreexec(
        security_profile, descriptor, interpreterdescriptor,
        options.get('preexec_fn'))
    return options, tuple(descriptors)


def _validateprofilecommand(command, softwarepath, security_profile):

    if security_profile is None:
        return
    try:
        executable = str(command[0])
    except (IndexError, TypeError):
        raise ValueError('profiled launch command is empty')
    if executable != str(softwarepath):
        raise ValueError(
            'profiled software must be executed directly from its bound path')


def popensecured(command, softwarepath, security_profile, **options):

    """Start a process with descriptor-bound LSM identity and caller I/O."""

    _validateprofilecommand(command, softwarepath, security_profile)
    secured, descriptors = _securedlaunchoptions(
        softwarepath, security_profile, options)
    try:
        return subprocess.Popen(command, **secured)
    finally:
        for descriptor in descriptors:
            os.close(descriptor)


def popenisolated(command, softwarepath=None, logpath=None,
                  security_profile=None, **options):

    """Start software with output confined to a lazily created log."""

    if 'stdout' in options or 'stderr' in options:
        raise ValueError('popenisolated owns stdout and stderr')

    if softwarepath is None:
        try:
            arguments = list(command)
            softwarepath = arguments[1] if len(arguments) > 1 else arguments[0]
        except Exception:
            softwarepath = 'unknown'

    _validateprofilecommand(command, softwarepath, security_profile)
    resolvedlog = softwarelogpath(softwarepath, logpath)
    options, securitydescriptors = _securedlaunchoptions(
        softwarepath, security_profile, options)

    try:
        return _LazyLogPopen(command, resolvedlog, **options)
    finally:
        for descriptor in securitydescriptors:
            os.close(descriptor)


_EARLYCLOCKNOTICE = (
    'I am retaining the kernel-provided system clock because the '
    'Operations-owned motherboard clock bootstrap is unavailable.'
    if os.getpid() == 1 else None
)

_builtin_print = print
QUIETSYSTEM = os.environ.get('T1OS_QUIET', '').strip().lower() in ('1', 'true', 'yes', 'on')
ANGELPREFIX = '~ '
ANGELSUFFIX = ' ~'
GODDESSPRINTPREFIX = re.compile(
    r'^(?:T1OS\s+)?GODDESS(?:\s+GRAPHICS\s+RECOVERY|\s+DIAGNOSTIC\s+LOG|'
    r'\s+DIAGNOSTIC\s+UNAVAILABLE|\s+FATAL|\s+BIRTH)?\s*:\s*',
    re.IGNORECASE,
)
OUTPUTFAILURELOG = '/the one/logs/GODDESS.py.log'
OUTPUTFAILURELIMIT = 64
_OUTPUTFAILURECOUNT = 0
_GODDESSDISPLAYPHRASES = set()
_GODDESSDISPLAYLOCK = threading.Lock()
_GODDESSDISPLAYONCEPHRASES = (
    'I CANNOT CONTINUE',
)


def recordoutputfailure(destination, value, error):

    # PID 1 output is diagnostic, never a boot dependency. A DRM/VT ownership
    # transition can make an inherited console return EIO even though the
    # root filesystem and the replacement display owner are healthy. Record a
    # bounded breadcrumb without calling print (which would recurse), then let
    # graphics recovery continue.
    global _OUTPUTFAILURECOUNT

    if _OUTPUTFAILURECOUNT >= OUTPUTFAILURELIMIT:
        return

    _OUTPUTFAILURECOUNT += 1

    try:
        payload = (
            formatlog(
                'GODDESS',
                f'output failure destination={destination} '
                f'error={type(error).__name__}: {error} '
                f'value={str(value)[:2048]!r}',
            ) + '\n'
        ).encode('utf-8', errors='replace')
        descriptor = os.open(
            OUTPUTFAILURELOG,
            os.O_WRONLY | os.O_CREAT | os.O_APPEND
            | getattr(os, 'O_CLOEXEC', 0),
            0o600,
        )
        try:
            os.write(descriptor, payload)
        finally:
            os.close(descriptor)
    except BaseException:
        pass


def displayconsolefallback(value):

    rawfd = os.environ.get('T1OS_DISPLAY_CONSOLE_FD', '').strip()

    if not rawfd.isdigit():
        return False

    try:
        payload = str(value).encode('utf-8', errors='replace')
        offset = 0
        descriptor = int(rawfd)

        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                return False
            offset += written

        return True
    except (BrokenPipeError, OSError, ValueError):
        return False


def formalsystemname(message):

    """Use the operating system's formal name in character dialogue."""

    return re.sub(
        r'(?<![\w.-])T1OS(?![\w.-])',
        'The One OS',
        str(message),
        flags=re.IGNORECASE,
    )


def formatangel(message):

    """Frame recovery speech in Angel's ordinary sentence-case voice."""

    lines = []

    for line in formalsystemname(message).splitlines() or ['']:
        if line.startswith(ANGELPREFIX) and line.endswith(ANGELSUFFIX):
            line = line[len(ANGELPREFIX):-len(ANGELSUFFIX)]
        lines.append(f'{ANGELPREFIX}{line}{ANGELSUFFIX}')

    return '\n'.join(lines)


def angelprint(*values, sep=' ', end='\n', file=None, flush=False):

    """Let Angel speak when PID 1 delegates recovery work to her."""

    target = sys.stdout if file is None else file
    output = formatangel(sep.join(str(value) for value in values))

    try:
        return _builtin_print(output, end=end, file=target, flush=flush)
    except (BrokenPipeError, OSError, ValueError) as error:
        recordoutputfailure('angel-print', output, error)
        if file is None:
            displayconsolefallback(output + end)
        return None


def print(*values, sep=' ', end='\n', file=None, flush=False):

    target = sys.stdout if file is None else file
    message = formalsystemname(
        GODDESSPRINTPREFIX.sub(
            '',
            sep.join(str(value) for value in values),
        )
    ).upper()
    # Child services already emit canonical records. Preserve their identity
    # while applying GODDESS's uppercase speaking style to the complete line.
    servicerecord = re.match(
        r'^\[\d{2}:\d{2}:-?\d+AE \d{1,2}:\d{2}:\d{2} '
        r'(?:AM|PM)\] \[[^]]+\] ',
        message,
    ) is not None
    if servicerecord:
        formatted = message
    else:
        formatted = formatlog('GODDESS', message)
        formatted = formatted.replace(' [GODDESS] ', ' ', 1)

    # Log files retain canonical timestamps. Human-facing boot consoles show
    # the same records without the leading clock value; this also covers child
    # service records replayed by logstreamworker().
    output = formatted if file is not None else re.sub(
        r'(?m)^\[\d{2}[:/]\d{2}[:/]-?\d+AE '
        r'\d{1,2}:\d{2}:\d{2} (?:AM|PM)\]\s*',
        '',
        formatted,
    )

    # Repeated GODDESS status phrases remain valid events, but repeating a
    # conversational clause across differently worded lines sounds unnatural.
    # Speak designated clause stems once, then retain only the unique reason or
    # consequence in later lines. Exact repeated sentences and clauses are also
    # removed when they occur inside otherwise different lines. Service records
    # and timestamped file output stay complete.
    if file is None and not servicerecord:
        lines = output.split('\n')
        kept = []
        hasphrase = False
        hasnewphrase = False
        with _GODDESSDISPLAYLOCK:
            for line in lines:
                if line.strip():
                    hasphrase = True
                for oncephrase in _GODDESSDISPLAYONCEPHRASES:
                    if not line.startswith(oncephrase):
                        continue
                    oncekey = f'ONCE:{oncephrase}'
                    if oncekey in _GODDESSDISPLAYPHRASES:
                        line = re.sub(
                            rf'^{re.escape(oncephrase)}'
                            r'(?:(?:,\s*SO)|(?:\s+BECAUSE))?\s*',
                            '',
                            line,
                            count=1,
                        ).lstrip(' ,.;:-')
                    else:
                        _GODDESSDISPLAYPHRASES.add(oncekey)
                    break
                uniqueclauses = []
                for clause in re.findall(r'[^.!?]+(?:[.!?]+|$)', line):
                    phrase = ' '.join(
                        clause.strip().rstrip('.!?').split()
                    )
                    if not phrase:
                        continue
                    clausekey = f'CLAUSE:{phrase}'
                    if clausekey in _GODDESSDISPLAYPHRASES:
                        continue
                    _GODDESSDISPLAYPHRASES.add(clausekey)
                    uniqueclauses.append(clause.strip())
                line = ' '.join(uniqueclauses)
                phrase = ' '.join(line.split())
                if not phrase:
                    continue
                hasnewphrase = True
                kept.append(line)
        if hasphrase and not hasnewphrase:
            return None
        output = '\n'.join(kept)

    try:
        return _builtin_print(output, end=end, file=target, flush=flush)
    except (BrokenPipeError, OSError, ValueError) as error:
        recordoutputfailure('primary-print', formatted, error)
        if file is None:
            displayconsolefallback(output + end)
        return None


if __name__ == '__main__':
    print('I am awake, and my Python runtime is ready.', flush=True)

    if _EARLYCLOCKNOTICE is not None:
        print(_EARLYCLOCKNOTICE, flush=True)



## globals

DISPLAYCONSOLEFD = None
NULLDEVICE = '/the one/drivers/nodes/null'
DISPLAYCONSOLENODE = '/the one/drivers/nodes/tty0'
KDSETMODE = 0x4B3A
KD_TEXT = 0x00
KD_GRAPHICS = 0x01
DISPLAYCONSOLEMODETIMEOUT = 2.0
DISPLAYCONSOLEHELPERRETIRETIMEOUT = 5.0
_ABANDONEDKERNELHELPERS = []
_PENDINGDISPLAYMODEHELPER = None
_PENDINGDISPLAYMODE = None
NONRESETTABLEPCITRANSPORTDRIVERS = {
    'pci-stub',
    'pcieport',
    'vfio-pci',
    'virtio-pci',
    'xen-platform-pci',
}

class ConsoleMirror:

    def __init__(self, primary, display):

        self.primary = primary
        self.display = display

    def write(self, value):

        written = None

        try:

            written = self.primary.write(value)
            self.primary.flush()

        except (BrokenPipeError, OSError, ValueError) as error:

            recordoutputfailure('primary-write', value, error)

        try:

            self.display.write(value)

        except (BrokenPipeError, OSError, ValueError) as error:

            recordoutputfailure('display-write', value, error)

        return written if isinstance(written, int) else len(value)

    def flush(self):

        try:

            self.primary.flush()

        except (BrokenPipeError, OSError, ValueError) as error:

            recordoutputfailure('primary-flush', '', error)

        try:

            self.display.flush()

        except (BrokenPipeError, OSError, ValueError) as error:

            recordoutputfailure('display-flush', '', error)

    def __getattr__(self, name):

        return getattr(self.primary, name)


def acquiredisplayconsole():

    """Return the measured tty0 descriptor through T1OS's canonical path."""

    global DISPLAYCONSOLEFD

    rawfd = os.environ.get('T1OS_DISPLAY_CONSOLE_FD', '').strip()
    candidate = int(rawfd) if rawfd.isdigit() else None

    if candidate is not None:
        try:
            metadata = os.fstat(candidate)
            if not statmodule.S_ISCHR(metadata.st_mode):
                raise OSError('inherited display descriptor is not a character device')
            DISPLAYCONSOLEFD = candidate
            return candidate
        except (OSError, ValueError):
            pass

    # BusyBox switch_root may retire non-standard initramfs descriptors.  The
    # runtime LSM grants GODDESS access to this exact canonical tty0 node and
    # denies every broader device-tree path, so reacquiring it here preserves
    # the same narrow display-ownership boundary.
    descriptor = os.open(
        DISPLAYCONSOLENODE,
        os.O_RDWR | getattr(os, 'O_NOCTTY', 0) |
        getattr(os, 'O_CLOEXEC', 0),
    )
    metadata = os.fstat(descriptor)
    if not statmodule.S_ISCHR(metadata.st_mode):
        os.close(descriptor)
        raise OSError('display console is not a character device')
    DISPLAYCONSOLEFD = descriptor
    os.environ['T1OS_DISPLAY_CONSOLE_FD'] = str(descriptor)
    return descriptor


def mirrordisplayconsole(force=False):

    global DISPLAYCONSOLEFD

    try:

        DISPLAYCONSOLEFD = acquiredisplayconsole()

        if QUIETSYSTEM and not force:

            return

        if isinstance(sys.stdout, ConsoleMirror):

            return

        displayfd = os.open(
            DISPLAYCONSOLENODE,
            os.O_WRONLY | os.O_NONBLOCK | getattr(os, 'O_NOCTTY', 0) |
            getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_CLOEXEC', 0),
        )
        displaymetadata = os.fstat(displayfd)
        if not statmodule.S_ISCHR(displaymetadata.st_mode):
            os.close(displayfd)
            raise OSError('display mirror is not a character device')
        try:
            display = os.fdopen(displayfd, 'w', buffering=1, closefd=True)
        except Exception:
            os.close(displayfd)
            raise
        sys.stdout = ConsoleMirror(sys.stdout, display)
        sys.stderr = ConsoleMirror(sys.stderr, display)

    except Exception as error:

        print(f'I could not mirror my messages to the display console. {error}', flush=True)


def disabledisplayconsoleecho():

    if DISPLAYCONSOLEFD is None:

        return

    try:

        attributes = termios.tcgetattr(DISPLAYCONSOLEFD)
        echoflags = termios.ECHO | termios.ECHONL | termios.ECHOE | termios.ECHOK
        attributes[3] &= ~echoflags
        termios.tcsetattr(DISPLAYCONSOLEFD, termios.TCSANOW, attributes)
        termios.tcflush(DISPLAYCONSOLEFD, termios.TCIFLUSH)

    except Exception as error:

        print(f'I could not disable display console echo. {error}', flush=True)


def setdisplayconsolemode(graphics):

    global _PENDINGDISPLAYMODEHELPER, _PENDINGDISPLAYMODE

    mode = KD_GRAPHICS if graphics else KD_TEXT
    name = 'graphics' if graphics else 'text'

    if _PENDINGDISPLAYMODEHELPER is not None:
        if _PENDINGDISPLAYMODEHELPER.poll() is None:
            print(
                'I cannot change the display console mode because the previous '
                f'{_PENDINGDISPLAYMODE or "unknown"} mode helper is still blocked.',
                flush=True,
            )
            return False

        _PENDINGDISPLAYMODEHELPER = None
        _PENDINGDISPLAYMODE = None

    # The initramfs opened tty0 before the runtime LSM boundary and handed
    # that descriptor to PID 1.  Pass the measured descriptor to the bounded
    # helper instead of reopening /the one/drivers/nodes/tty0 from a generic
    # ``python -c`` process, which the T1OS device ACL correctly rejects.
    if DISPLAYCONSOLEFD is None:
        print(
            f'I could not place the display console in {name} mode because its '
            'inherited terminal connection is unavailable.',
            flush=True,
        )
        return False

    # The signed developer VM uses a deterministic software-KMS path and
    # starts logging threads before the GUI readiness barrier.  Forking a
    # profiled helper from that multithreaded PID 1 can block inside Popen's
    # pre-exec handshake.  Apply the identical ioctl directly to the exact
    # canonical tty descriptor in this test-only boundary; production boots
    # retain the bounded helper and its kernel-stall watchdog below.
    if (
        os.environ.get('T1OS_DEVELOPER') == '1'
        and os.environ.get('T1OS_ENABLE_VM_TEST_AGENT') == '1'
    ):
        try:
            fcntl.ioctl(DISPLAYCONSOLEFD, KDSETMODE, mode)
            return True
        except (OSError, ValueError) as error:
            print(
                f'I could not place the developer VM display console in '
                f'{name} mode. {type(error).__name__}: {error}',
                flush=True,
            )
            return False

    script = os.path.abspath(__file__)
    arguments = [
        script,
        '--display-console-mode-helper',
        str(DISPLAYCONSOLEFD),
        str(KDSETMODE),
        str(mode),
    ]

    nulldescriptor = None
    process = None

    try:
        nulldescriptor = os.open(
            NULLDEVICE,
            os.O_RDONLY | getattr(os, 'O_CLOEXEC', 0),
        )
        process = popensecured(
            arguments,
            script,
            'goddess',
            stdin=nulldescriptor,
            stdout=nulldescriptor,
            stderr=nulldescriptor,
            close_fds=True,
            pass_fds=(DISPLAYCONSOLEFD,),
            start_new_session=True,
        )
    except (OSError, ValueError, TypeError) as error:
        detail = f'{type(error).__name__}: {error}'
    finally:
        if nulldescriptor is not None:
            try:
                os.close(nulldescriptor)
            except OSError:
                pass

    if process is not None:
        deadline = time.monotonic() + DISPLAYCONSOLEMODETIMEOUT

        while time.monotonic() < deadline:
            status = process.poll()

            if status is not None:
                if status == 0:
                    return True
                detail = f'helper exit {status}'
                break

            time.sleep(0.01)
        else:
            # KDSETMODE(KD_TEXT) enters fbcon and can sleep forever when the
            # native DRM display engine is wedged. Never wait for that kernel
            # task from PID 1. SIGKILL remains pending until the syscall
            # returns; the normal non-blocking child reaper collects it later.
            try:
                process.kill()
            except (ProcessLookupError, OSError):
                pass

            _ABANDONEDKERNELHELPERS.append(process)
            _PENDINGDISPLAYMODEHELPER = process
            _PENDINGDISPLAYMODE = name
            detail = f'timeout after {DISPLAYCONSOLEMODETIMEOUT:.1f}s'

    print(
        f'I could not place the display console in {name} mode. {detail}',
        flush=True,
    )
    return False


def waitdisplayconsolemodehelper(
    timeout=DISPLAYCONSOLEHELPERRETIRETIMEOUT,
):

    global _PENDINGDISPLAYMODEHELPER, _PENDINGDISPLAYMODE

    process = _PENDINGDISPLAYMODEHELPER

    if process is None:
        return True

    deadline = time.monotonic() + max(0.0, float(timeout))

    while True:

        try:
            status = process.poll()
        except Exception:
            status = -1

        if status is not None:
            _PENDINGDISPLAYMODEHELPER = None
            _PENDINGDISPLAYMODE = None
            return True

        if time.monotonic() >= deadline:
            print(
                'The blocked display console helper did not stop within '
                f'{float(timeout):.1f} seconds while using '
                f'{_PENDINGDISPLAYMODE or "unknown"} mode.',
                flush=True,
            )
            return False

        time.sleep(0.02)


if __name__ == '__main__':
    mirrordisplayconsole()
    disabledisplayconsoleecho()

# misc
IDLERATE = 5
DEBUGSYSTEM = os.environ.get('T1OS_DEBUG', '').strip().lower() in ('1', 'true', 'yes', 'on')
AE_START_YEAR = 2021
LOGSTREAMPOLL = 0.10
PREVIOUSBOOTLOGLIMIT = 7

# paths
LOGDIR = '/the one/logs'
EPHEMERALTIER = '/.ephemeral'
TERMINFOBASE = '/.ephemeral/terminfo'
OPERATIONSSOCKET = '/.ephemeral/operations/control.sock'
TERMINALNAMEFILE = '/the one/settings/terminal/name.txt'
BOOTANIMATIONSCRIPT = '/boot/boot animation/boot animation.py'
BOOTANIMATIONBASE = '/.ephemeral/boot animation'
BOOTANIMATIONREQUEST = os.path.join(BOOTANIMATIONBASE, 'request.json')
BOOTANIMATIONSTATE = os.path.join(BOOTANIMATIONBASE, 'state.json')
POWERANIMATIONBASE = '/.ephemeral/power animation'
POWERANIMATIONREQUEST = os.path.join(POWERANIMATIONBASE, 'request.json')
POWERANIMATIONSTATE = os.path.join(POWERANIMATIONBASE, 'state.json')
FATALANIMATIONBASE = '/.ephemeral/fatal screen'
FATALANIMATIONCONTENT = os.path.join(FATALANIMATIONBASE, 'content.json')
FATALANIMATIONREQUEST = os.path.join(FATALANIMATIONBASE, 'request.json')
FATALANIMATIONSTATE = os.path.join(FATALANIMATIONBASE, 'state.json')
FATALERRORLOG = '/the one/logs/fatal errors.jsonl'
FATALPRESENTTIMEOUT = 3.0
FATALDISPLAYTIME = 5.0
STARTUPSCRIPT = '/the one/build/startup/startup.py'
STARTUPLOG = '/the one/logs/startup.py.log'
LOCKSCREENLOG = '/the one/logs/lock screen.py.log'
LOCKSCREENSTATE = '/.ephemeral/lock screen/state.json'
LOCKSCREENPOSTHANDOFFSTATE = '/.ephemeral/lock screen/post-handoff-ready.json'
LOCKSCREENPOSTHANDOFFTIMEOUT = 15.0
ACCELERATEDBOOTREADYPATH = '/.ephemeral/windowserver/state/accelerated-boot-ready.json'
ACCELERATEDLOCKSCREENREADYPATH = '/.ephemeral/windowserver/state/accelerated-lockscreen-ready.json'
ACCELERATIONUNAVAILABLEPATH = '/.ephemeral/windowserver/state/acceleration-unavailable.json'
GRAPHICSCAPABILITYPATH = '/.ephemeral/windowserver/state/graphics-capability.json'
LOCKSCREENREADYPATH = '/.ephemeral/windowserver/state/lockscreen-ready.json'
GRAPHICSRECOVERYLOG = '/the one/logs/graphics recovery.jsonl'
GRAPHICSSOFTWARELOG = '/the one/logs/graphics.py.log'
WINDOWSERVERSOFTWARELOG = '/the one/logs/windowserver.py.log'
GRAPHICSRECOVERYBOOT = '/the one/settings/graphics recovery boot.json'
BOOTIDPATHS = (
    '/the one/drivers/processes/sys/kernel/random/boot_id',
)
EFIVARFSROOT = '/the one/drivers/control/firmware/efi/efivars'
EFIVARGLOBALGUID = '8be4df61-93ca-11d2-aa0d-00e098032b8c'
FS_IOC_GETFLAGS = 0x80086601
FS_IOC_SETFLAGS = 0x40086602
FS_IMMUTABLE_FL = 0x00000010
_LASTGPUKERNELRING = None
CHROMIUMSCRIPT = '/the one/build/chromium/chromium.py'
PROCEDURESCRIPT = '/the one/build/procedures/procedures.py'
NETWORKSCRIPT = '/the one/build/network/network.py'
NETWORKINITIALSTATE = '/.ephemeral/network/initial.json'
NETWORKINITIALSTATEFIELDS = frozenset((
    'format', 'connected', 'interface', 'completed',
))
NETWORKINITIALSTATEMAXIMUM = 512
NETWORKINITIALSTATEINTERFACE = re.compile(r'[A-Za-z0-9_.:-]{0,15}')
REIGNSCRIPT = '/the one/build/reign/reign.py'
EXCHANGESCRIPT = '/the one/build/exchange/exchange.py'
INPUTSERVERSCRIPT = '/the one/build/input/inputserver.py'
WINDOWSERVERSCRIPT = '/the one/build/windows/windowserver.py'
AUDIOSERVERSCRIPT = '/the one/build/audio/audioserver.py'
EXPANSESCRIPT = '/the one/build/expanse/expanse.py'
OPERATIONSSERVERSCRIPT = '/the one/build/operations/operationsserver.py'
PYTHONSCRIPT = '/the one/build/python/python.py'
DRIVERSERVERSCRIPT = '/the one/build/drivers/driverserver.py'
DRIVERMODULEROOT = '/the one/drivers/modules'
DRIVERMODULELOADER = '/the one/drivers/tools/modprobe'
DRIVERPOLICY = '/the one/drivers/settings/policy.json'
DRIVERKERNELROOT = os.path.join(DRIVERMODULEROOT, os.uname().release)
DRIVERSERVERENABLED = (
    os.path.isfile(DRIVERSERVERSCRIPT)
    and os.path.isfile(DRIVERPOLICY)
)
MEDIADECODESERVICE = '/the one/software/audio/t1-media-decoderd'
MEDIADECODEWORKER = '/the one/software/audio/t1-video-decode'
MEDIADECODEPOLICY = '/the one/settings/media/video decode service.json'
MEDIADECODEPACKAGEDPOLICY = (
    '/the one/software/audio/video decode service.json'
)
HARDWAREDIAGNOSTICPOLICY = (
    '/the one/settings/media/hardware diagnostics.json'
)
HARDWAREDIAGNOSTICFALLBACK = (
    '/the one/build/chromium/hardware diagnostics.json'
)
HARDWAREDIAGNOSTICLOGMINIMUM = 64 * 1024
HARDWAREDIAGNOSTICLOGMAXIMUM = 16 * 1024 * 1024
MEDIADECODERUNTIME = '/.ephemeral/media'
MEDIADECODESOCKET = MEDIADECODERUNTIME + '/decode.sock'
MEDIADECODESTATE = MEDIADECODERUNTIME + '/decode-service.json'
MEDIADECODEPROTOCOL = 'T1MD'
MEDIADECODEPROTOCOLVERSION = 1
MEDIADECODESANDBOXFORMAT = 1
MEDIADECODESANDBOXMINIMUMABI = 5
MEDIADECODESANDBOXFLAGS = 255
MEDIADECODESESSIONEXECVISIBLEFDS = 6
MEDIADECODESESSIONREQUIREDIPCFDS = 3
MEDIADECODESESSIONSTDIN = 'null'
MEDIADECODESESSIONSTDOUT = 'null'
MEDIADECODESESSIONSTDERR = 'bounded-nonblocking-relay'
MEDIADECODESESSIONDIAGNOSTICLIMIT = 1048576
MEDIADECODEWATCHDOGCONTRACT = {
    'format': 1,
    'policy_id': 't1md-watchdog-v1',
    'authority': 'supervisor',
    'clock': 'CLOCK_MONOTONIC',
    'timeout_action': 'SIGKILL',
    'idle_timeout_ms': 0,
    'starting_timeout_ms': 15000,
    'hello_timeout_ms': 30000,
    'create_timeout_ms': 15000,
    'decode_timeout_ms': 15000,
    'flush_timeout_ms': 15000,
    'reset_timeout_ms': 10000,
    'release_timeout_ms': 6000,
    'destroy_timeout_ms': 10000,
    'cleanup_timeout_ms': 10000,
    'exiting_timeout_ms': 1000,
}
MEDIADECODEMAXSESSIONS = 8
MEDIADECODEMAXPROFILES = 48
MEDIADECODEWORKERUID = 65534
MEDIADECODEWORKERGID = 1000
MEDIADECODEEXPORTCONTRACT = {
    'mode': 'separate-layers',
    'object_layout': 'one-object-per-plane',
    'modifier_scope': 'per-object',
    'modifier_layout': 'natural-per-plane',
    'composed_fallback': False,
}
MEDIADECODEREADYTIMEOUT = 15.0
MEDIADECODEREADYPOLL = 0.05
MEDIADECODELOG = '/the one/logs/media.py.log'
GRAPHICSCLASSROOT = '/the one/drivers/state/class/drm'
GRAPHICSDEVICEROOT = '/the one/drivers/nodes/dri'
GRAPHICSCATALOGUE = '/the one/catalogue/graphics'
NVIDIAGRAPHICSRUNTIME = GRAPHICSCATALOGUE + '/nvidia'
NVIDIACACHEPATH = '/.ephemeral/cache/nvidia'
LIBVADRIVERPATH = GRAPHICSCATALOGUE + '/drivers'
GUESTADDITIONSSCRIPT = '/the one/software/virtualbox/guestadditions.py'
LOGPATHS = {
    'procedures': '/the one/logs/procedures.py.log',
    'reign': '/the one/logs/reign.py.log',
    'exchange': '/the one/logs/exchange.py.log',
    'input server': '/the one/logs/inputserver.py.log',
    'window server': WINDOWSERVERSOFTWARELOG,
    'audio server': '/the one/logs/audioserver.py.log',
    'network': '/the one/logs/network.py.log',
    'expanse': '/the one/logs/expanse.py.log',
    'operations server': '/the one/logs/operationsserver.py.log',
    'driver server': '/the one/logs/driverserver.py.log',
    'media': MEDIADECODELOG,
    'boot animation': '/the one/logs/boot animation.py.log',
    'power animation': '/the one/logs/power animation.py.log',
    'fatal screen': '/the one/logs/fatal screen.py.log',
    'virtualbox': '/the one/logs/guestadditions.py.log',
}
TASKS = {}
OPERATIONSSYNCREQUIRED = True
LASTOPERATIONSSYNC = 0.0
OPERATIONSSYNCINTERVAL = 1.0
POWERSERVER = None
SYSTEMSTATE = 'running'
SYSTEMPHASE = 'starting'
FATALACTIVE = False


def prunepreviousbootlogs():

    """Keep only the newest bounded set of completed-boot log archives."""

    try:
        names = os.listdir(LOGDIR)
    except FileNotFoundError:
        return
    except OSError as error:
        print(
            f'I could not inspect previous boot logs. {error}',
            flush=True,
        )
        return

    archives = []

    for name in names:
        path = os.path.join(LOGDIR, name)
        manifest = os.path.join(path, 'archive-manifest.txt')

        try:
            pathstatus = os.stat(path, follow_symlinks=False)
            manifeststatus = os.stat(manifest, follow_symlinks=False)
        except OSError:
            continue

        if not (
            statmodule.S_ISDIR(pathstatus.st_mode)
            and statmodule.S_ISREG(manifeststatus.st_mode)
        ):
            continue

        archives.append((pathstatus.st_mtime_ns, name, path))

    archives.sort(reverse=True)

    for _modified, _name, path in archives[PREVIOUSBOOTLOGLIMIT:]:
        try:
            shutil.rmtree(path)
        except OSError as error:
            print(
                f'I could not remove the expired previous boot logs at '
                f'{path}. {error}',
                flush=True,
            )
PROCESSROOT = '/the one/drivers/processes'
SUPERVISERATE = 0.20
SESSIONSTOPTIMEOUT = 2.0
SERVICESTOPTIMEOUT = 3.0
DRIVERSTOPTIMEOUT = 5.0
FORCESTOPTIMEOUT = 1.0
OPERATIONALCRITICALTASKS = frozenset((
    'driver server',
    'input server',
    'window server',
    'expanse',
))
OPERATIONALRESTARTLIMIT = 3
OPERATIONALRESTARTWINDOW = 60.0
OPERATIONALHEALTHYRESET = 300.0


def kernelcommandlineoption(option):

    try:

        with open('/the one/drivers/processes/cmdline', 'rb') as stream:

            return option.encode('ascii') in stream.read(65536).split()

    except (OSError, UnicodeError):

        return False


def graphicsaccelerationrequired():

    """Return true for every ordinary boot; CPU graphics must be explicit."""

    requested = str(os.environ.get('T1OS_GRAPHICS', '')).strip().lower()
    return not (
        kernelcommandlineoption('t1os.graphics=framebuffer')
        or kernelcommandlineoption('t1os.graphics=cpu')
        or requested in ('framebuffer', 'cpu')
    )


def booleanoption(value):

    if isinstance(value, bool):
        return value

    text = str(value or '').strip().lower()

    if text in ('1', 'true', 'yes', 'on', 'enabled'):
        return True

    if text in ('0', 'false', 'no', 'off', 'disabled'):
        return False

    return None


def hardwarediagnosticpolicy(path=None):

    """Read the strict shared policy for bounded GPU/media diagnostics."""

    result = {
        'enabled': False,
        'chromium_engine': False,
        'media_service': False,
        'engine_log_limit_bytes': 8 * 1024 * 1024,
        'source': 'default-off',
    }
    explicitpath = path is not None
    paths = (
        (str(path),)
        if explicitpath
        else (HARDWAREDIAGNOSTICPOLICY, HARDWAREDIAGNOSTICFALLBACK)
    )
    for index, candidate in enumerate(paths):
        try:
            if (
                os.path.islink(candidate)
                or not statmodule.S_ISREG(os.stat(candidate).st_mode)
            ):
                raise ValueError(
                    'hardware diagnostic policy is not a regular file'
                )
            with open(candidate, 'r', encoding='utf-8') as stream:
                encoded = stream.read(16385)
            if len(encoded.encode('utf-8')) > 16384:
                raise ValueError('hardware diagnostic policy is too large')
            configured = json.loads(encoded)
            if not isinstance(configured, dict):
                raise ValueError('hardware diagnostic policy is not an object')
            if type(configured.get('format')) is not int:
                raise ValueError(
                    'hardware diagnostic policy format is not an integer'
                )
            if configured.get('format') != 1:
                raise ValueError('unsupported hardware diagnostic policy format')
            for option in ('enabled', 'chromium_engine', 'media_service'):
                if type(configured.get(option)) is not bool:
                    raise ValueError(
                        f'hardware diagnostic policy {option} is not a JSON Boolean'
                    )
            limit = configured.get('engine_log_limit_bytes', 8 * 1024 * 1024)
            if (
                type(limit) is not int
                or limit < HARDWAREDIAGNOSTICLOGMINIMUM
                or limit > HARDWAREDIAGNOSTICLOGMAXIMUM
            ):
                raise ValueError(
                    'hardware diagnostic engine log limit is unsafe'
                )
            result.update({
                'enabled': configured['enabled'],
                'chromium_engine': configured['chromium_engine'],
                'media_service': configured['media_service'],
                'engine_log_limit_bytes': limit,
                'source': (
                    'launcher-fallback'
                    if not explicitpath and index == 1
                    else 'settings'
                ),
            })
            return result
        except FileNotFoundError:
            continue
        except Exception as error:
            result['source'] = (
                'invalid-launcher-fallback'
                if not explicitpath and index == 1
                else 'invalid-settings'
            )
            result['error'] = f'{type(error).__name__}: {error}'[:1024]
            return result
    return result


def mediadecodeservicepolicy(
    path=None,
    environment=None,
):

    """Return the explicit fail-closed native web-decoder boot policy."""

    if path is None:
        path = MEDIADECODEPOLICY
        if (
            not os.path.isfile(path)
            and os.path.isfile(MEDIADECODEPACKAGEDPOLICY)
        ):
            path = MEDIADECODEPACKAGEDPOLICY

    policy = {
        'enabled': False,
        'kill_switch': False,
        'development_debug': False,
        'max_sessions': MEDIADECODEMAXSESSIONS,
        'source': 'default-off',
    }

    try:
        with open(path, 'r', encoding='utf-8') as stream:
            configured = json.load(stream)

        if not isinstance(configured, dict):
            raise ValueError('media decode policy is not an object')

        for option in (
            'enabled',
            'kill_switch',
            'development_debug',
        ):
            if option in configured and type(configured[option]) is not bool:
                raise ValueError(
                    f'media decode policy {option} is not a JSON Boolean'
                )

        configuredprotocol = configured.get(
            'protocol_version',
            MEDIADECODEPROTOCOLVERSION,
        )

        if (
            type(configuredprotocol) is not int
            or configuredprotocol != MEDIADECODEPROTOCOLVERSION
        ):
            raise ValueError(
                f'unsupported media decode protocol {configuredprotocol}'
            )

        configuredmax = configured.get(
            'max_sessions',
            MEDIADECODEMAXSESSIONS,
        )
        if (
            type(configuredmax) is not int
            or configuredmax != MEDIADECODEMAXSESSIONS
        ):
            raise ValueError(
                f'media decode max_sessions must be exactly '
                f'{MEDIADECODEMAXSESSIONS}, got {configuredmax}'
            )
        policy.update({
            'enabled': configured.get('enabled', False) is True,
            'kill_switch': configured.get('kill_switch', False) is True,
            # A persistent development-era setting must not make every user
            # boot run the decoder daemon and workers with high-volume trace
            # output. Debugging is authorized explicitly below for one boot.
            'development_debug': False,
            # Chromium pre-opens four channels for each GPU generation. Keep
            # room for both the retiring and replacement GPU processes so a
            # GPU restart cannot strand every decoder connection.
            'max_sessions': configuredmax,
            'source': 'settings',
        })
    except FileNotFoundError:
        pass
    except Exception as error:
        policy['error'] = str(error)
        policy['source'] = 'invalid-settings'

    environment = os.environ if environment is None else environment
    environmentvalue = booleanoption(
        environment.get('T1OS_MEDIA_DECODE_SERVICE')
    )
    debugvalue = booleanoption(
        environment.get('T1OS_MEDIA_DECODE_DEBUG')
    )
    kernelon = kernelcommandlineoption('t1os.media-decode-service=1')
    kerneloff = kernelcommandlineoption('t1os.media-decode-service=0')
    kerneldebug = kernelcommandlineoption('t1os.media-decode-debug=1')
    diagnosticpolicy = hardwarediagnosticpolicy()
    diagnosticdebug = bool(
        diagnosticpolicy['enabled']
        and diagnosticpolicy['media_service']
    )
    policy['development_debug'] = bool(
        debugvalue is not False
        and (debugvalue is True or kerneldebug or diagnosticdebug)
    )
    policy['debug_source'] = 'off'
    if policy['development_debug']:
        policy['debug_source'] = (
            'environment-on'
            if debugvalue is True
            else 'kernel-on'
            if kerneldebug
            else diagnosticpolicy['source']
        )
    if diagnosticpolicy.get('source') == 'invalid-settings':
        policy['diagnostic_error'] = diagnosticpolicy.get('error', 'unknown')

    # The kill paths always win. This gives a damaged test build a boot-time
    # rollback which does not depend on reaching the desktop or rewriting the
    # persistent settings tier.
    if policy['kill_switch'] or environmentvalue is False or kerneloff:
        policy['enabled'] = False
        policy['source'] = (
            'kill-switch'
            if policy['kill_switch']
            else (
                'environment-off'
                if environmentvalue is False
                else 'kernel-off'
            )
        )
    elif (
        policy['source'] != 'invalid-settings'
        and (environmentvalue is True or kernelon)
    ):
        policy['enabled'] = True
        policy['source'] = (
            'environment-on'
            if environmentvalue is True
            else 'kernel-on'
        )

    return policy


def mediadecoderendernode(drmdevice):

    """Resolve the render node belonging to WindowServer's selected card."""

    card = os.path.basename(str(drmdevice or '').strip())

    if not (
        card.startswith('card')
        and card[4:].isdigit()
    ):
        return ''

    renderroot = os.path.join(
        GRAPHICSCLASSROOT,
        card,
        'device',
        'drm',
    )

    try:
        candidates = sorted(os.listdir(renderroot))
    except OSError:
        return ''

    for name in candidates:
        if not (
            name.startswith('renderD')
            and name[7:].isdigit()
        ):
            continue

        node = os.path.join(GRAPHICSDEVICEROOT, name)

        try:
            status = os.stat(node, follow_symlinks=False)
        except OSError:
            continue

        if statmodule.S_ISCHR(status.st_mode):
            return node

    return ''


def clearmediadecodestate():

    for path in (MEDIADECODESTATE, MEDIADECODESOCKET):
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        except OSError as error:
            print(
                f'I could not remove the outdated media decoder path {path}. '
                f'{error}',
                flush=True,
            )


def mediadecodeserviceenvironment(
    windowtask,
    pathprovider,
    developmentdebug=False,
):

    """Build a private NVDEC environment which Chromium never inherits."""

    environment = os.environ.copy()

    for name in tuple(environment):
        if (
            name.startswith('NVD_')
            or name.startswith('CUDA_')
            or name.startswith('LIBVA_')
            or name.startswith('T1OS_CHROMIUM_NVIDIA_')
        ):
            environment.pop(name, None)

    environment.pop('LD_PRELOAD', None)
    environment['LD_LIBRARY_PATH'] = (
        '/the one/software/audio:'
        + NVIDIAGRAPHICSRUNTIME
        + ':'
        + GRAPHICSCATALOGUE
    )
    environment['LIBVA_DRIVERS_PATH'] = LIBVADRIVERPATH
    environment['LIBVA_DRIVER_NAME'] = 'nvidia'
    environment['NVD_BACKEND'] = 'direct'
    environment['NVD_FORCE_INIT'] = '1'
    # NVD_SINGLE_BUFFER is intentionally absent.  Its mere presence selects the
    # superseded common-modifier allocation in the NVIDIA VA driver.  Chromium's
    # T1MD bridge transports the patched driver's natural luma/chroma objects,
    # with one independently validated modifier per DMA-BUF object.
    environment['CUDA_DISABLE_PERF_BOOST'] = '1'
    environment['CUDA_CACHE_PATH'] = NVIDIACACHEPATH
    environment['__GL_SHADER_DISK_CACHE'] = '0'
    environment['MESA_SHADER_CACHE_DISABLE'] = 'true'
    environment['T1OS_MEDIA_DECODE_PROTOCOL'] = (
        f'{MEDIADECODEPROTOCOL}/{MEDIADECODEPROTOCOLVERSION}'
    )

    if developmentdebug:
        environment['T1OS_MEDIA_DECODE_DEBUG'] = '1'

    if pathprovider:
        environment['LD_PRELOAD'] = pathprovider
        environment['T1OS_NVIDIA_PATH_PROVIDER'] = pathprovider

    selectedenvironment = (
        windowtask.get('environment')
        if isinstance(windowtask, dict)
        else None
    )

    if isinstance(selectedenvironment, dict):
        drmdevice = str(
            selectedenvironment.get('T1OS_DRM_DEVICE', '')
        ).strip()

        if drmdevice:
            environment['T1OS_DRM_DEVICE'] = drmdevice

    return environment


def mediadecodeready(proc, device):

    if proc is None or proc.poll() is not None:
        return False

    try:
        socketstatus = os.stat(MEDIADECODESOCKET, follow_symlinks=False)

        if not statmodule.S_ISSOCK(socketstatus.st_mode):
            return False

        # Chromium runs as 1000:1000. The daemon owns the socket metadata and
        # must grant that measured identity connect permission; a world-writable
        # service socket is deliberately rejected.
        socketmode = statmodule.S_IMODE(socketstatus.st_mode)
        connectable = (
            (
                int(socketstatus.st_uid) == 1000
                and bool(socketmode & statmodule.S_IWUSR)
            )
            or (
                int(socketstatus.st_gid) == 1000
                and bool(socketmode & statmodule.S_IWGRP)
            )
        )

        if not connectable or bool(socketmode & statmodule.S_IWOTH):
            return False

        with open(MEDIADECODESTATE, 'r', encoding='utf-8') as stream:
            state = json.load(stream)

        if not isinstance(state, dict):
            return False

        sandbox = state.get('sandbox')
        watchdog = state.get('watchdog')
        surfaceexport = state.get('surface_export')
        capabilities = state.get('capabilities')
        outputformats = (
            capabilities.get('output_formats')
            if isinstance(capabilities, dict)
            else None
        )
        bitdepths = (
            capabilities.get('bit_depths')
            if isinstance(capabilities, dict)
            else None
        )

        return (
            state.get('state') == 'ready'
            and state.get('protocol') == MEDIADECODEPROTOCOL
            and type(state.get('protocol_version')) is int
            and state.get('protocol_version')
            == MEDIADECODEPROTOCOLVERSION
            and type(state.get('pid')) is int
            and state.get('pid') == int(proc.pid)
            and type(state.get('worker_uid')) is int
            and state.get('worker_uid') == MEDIADECODEWORKERUID
            and type(state.get('worker_gid')) is int
            and state.get('worker_gid') == MEDIADECODEWORKERGID
            and type(state.get('maximum_sessions')) is int
            and state.get('maximum_sessions') == MEDIADECODEMAXSESSIONS
            and type(state.get('maximum_connections')) is int
            and state.get('maximum_connections') == MEDIADECODEMAXSESSIONS
            and os.path.normpath(str(state.get('socket', '')))
            == MEDIADECODESOCKET
            and os.path.normpath(str(state.get('device', ''))) == device
            and isinstance(surfaceexport, dict)
            and set(surfaceexport) == set(MEDIADECODEEXPORTCONTRACT)
            and all(
                type(surfaceexport.get(name)) is type(value)
                and surfaceexport.get(name) == value
                for name, value in MEDIADECODEEXPORTCONTRACT.items()
            )
            and isinstance(capabilities, dict)
            and set(capabilities) == {
                'vendor',
                'profile_count',
                'chroma_subsampling',
                'bit_depths',
                'output_formats',
            }
            and isinstance(capabilities.get('vendor'), str)
            and bool(capabilities.get('vendor').strip())
            and type(capabilities.get('profile_count')) is int
            and 0 < capabilities.get('profile_count') <= MEDIADECODEMAXPROFILES
            and capabilities.get('chroma_subsampling') == '4:2:0'
            and isinstance(outputformats, list)
            and bool(outputformats)
            and len(outputformats) == len(set(outputformats))
            and set(outputformats).issubset({'NV12', 'P010'})
            and isinstance(bitdepths, list)
            and bool(bitdepths)
            and len(bitdepths) == len(set(bitdepths))
            and set(bitdepths).issubset({8, 10})
            and ('NV12' in outputformats) == (8 in bitdepths)
            and ('P010' in outputformats) == (10 in bitdepths)
            and isinstance(sandbox, dict)
            and type(sandbox.get('format')) is int
            and sandbox.get('format') == MEDIADECODESANDBOXFORMAT
            and type(sandbox.get('landlock_abi')) is int
            and sandbox.get('landlock_abi')
            >= MEDIADECODESANDBOXMINIMUMABI
            and type(sandbox.get('landlock_minimum_abi')) is int
            and sandbox.get('landlock_minimum_abi')
            == MEDIADECODESANDBOXMINIMUMABI
            and sandbox.get('landlock_filesystem')
            == 'deny-by-default-all-through-ioctl-dev'
            and sandbox.get('landlock_network')
            == 'deny-tcp-bind-connect'
            and sandbox.get('seccomp') == 'filter'
            and sandbox.get('seccomp_tsync') is True
            and sandbox.get('runtime_filesystem') == 'read-only'
            and sandbox.get('device_filesystem') == 'read-write-ioctl'
            and sandbox.get('network_creation') == 'denied'
            and sandbox.get('process_creation') == 'threads-only'
            and sandbox.get('session_stdin') == MEDIADECODESESSIONSTDIN
            and sandbox.get('session_stdout') == MEDIADECODESESSIONSTDOUT
            and sandbox.get('session_stderr') == MEDIADECODESESSIONSTDERR
            and type(sandbox.get('session_diagnostic_limit')) is int
            and sandbox.get('session_diagnostic_limit')
            == MEDIADECODESESSIONDIAGNOSTICLIMIT
            and type(sandbox.get('session_exec_visible_fds')) is int
            and sandbox.get('session_exec_visible_fds')
            == MEDIADECODESESSIONEXECVISIBLEFDS
            and type(sandbox.get('session_required_ipc_fds')) is int
            and sandbox.get('session_required_ipc_fds')
            == MEDIADECODESESSIONREQUIREDIPCFDS
            and type(
                sandbox.get('session_unexpected_inherited_fds')
            ) is int
            and sandbox.get('session_unexpected_inherited_fds') == 0
            and type(sandbox.get('policy_flags')) is int
            and sandbox.get('policy_flags') == MEDIADECODESANDBOXFLAGS
            and isinstance(watchdog, dict)
            and set(watchdog) == set(MEDIADECODEWATCHDOGCONTRACT)
            and all(
                type(watchdog.get(name)) is type(value)
                and watchdog.get(name) == value
                for name, value in MEDIADECODEWATCHDOGCONTRACT.items()
            )
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return False


def stopmediadecodeservice():

    info = TASKS.pop('media', None)
    proc = info.get('proc') if isinstance(info, dict) else None
    terminateprocess(proc, timeout=SERVICESTOPTIMEOUT)
    clearmediadecodestate()


def configuremediadecodeservice(windowserverproc, graphicsbackend):

    """Bind one supervised decoder daemon to the proven graphics generation."""

    existing = TASKS.get('media')

    if isinstance(existing, dict):
        existingproc = existing.get('proc')

        if (
            existingproc is not None
            and existingproc.poll() is None
            and int(existing.get('windowserver_pid', 0))
            == int(getattr(windowserverproc, 'pid', 0))
        ):
            return True

        stopmediadecodeservice()

    policy = mediadecodeservicepolicy()

    if policy.get('diagnostic_error'):
        print(
            'I rejected the hardware diagnostic policy: '
            f'{policy["diagnostic_error"]}',
            flush=True,
        )
    elif policy['development_debug']:
        print(
            'I enabled bounded native media lifecycle diagnostics from '
            f'{policy.get("debug_source", "unknown")}.',
            flush=True,
        )

    if not policy['enabled']:
        clearmediadecodestate()
        print(
            'I have left native media decoding disabled because of the '
            f'{policy["source"]} policy. Chromium will decode media in software.',
            flush=True,
        )
        return False

    capability = (
        graphicscapabilityreceipt(windowserverproc)
        if graphicsbackend == 'opengl'
        else None
    )
    driver = str(
        capability.get('drm_driver', '')
        if isinstance(capability, dict)
        else ''
    ).strip().lower().replace('-', '_')

    if (
        not isinstance(capability, dict)
        or capability.get('state') != 'accelerated-candidate'
        or driver not in ('nvidia', 'nvidia_drm')
    ):
        clearmediadecodestate()
        print(
            'I did not start native media decoding because the display is not '
            'using NVIDIA acceleration. Chromium will decode media in software. '
            f'The display backend is {graphicsbackend}, and its driver is '
            f'{driver or "unknown"}.',
            flush=True,
        )
        return False

    windowtask = TASKS.get('window server', {})
    selectedenvironment = (
        windowtask.get('environment')
        if isinstance(windowtask, dict)
        else {}
    ) or {}
    drmdevice = str(selectedenvironment.get('T1OS_DRM_DEVICE', '')).strip()
    rendernode = mediadecoderendernode(drmdevice)

    if not rendernode:
        clearmediadecodestate()
        print(
            'I did not start native media decoding because the selected render '
            f'device {drmdevice or "missing"} is unavailable. Chromium will '
            'decode media in software.',
            flush=True,
        )
        return False

    missing = [
        path
        for path in (MEDIADECODESERVICE, MEDIADECODEWORKER)
        if not os.path.isfile(path) or not os.access(path, os.X_OK)
    ]

    if missing:
        clearmediadecodestate()
        print(
            'I did not start native media decoding because these runtime files '
            f'are missing: {", ".join(missing)}. Chromium will decode media in '
            'software.',
            flush=True,
        )
        return False

    try:
        pathprovider = preparenvidiapathprovider()

        if not pathprovider:
            raise RuntimeError('NVIDIA path provider is unavailable')

        os.makedirs(MEDIADECODERUNTIME, mode=0o755, exist_ok=True)
        # The native daemon retains root authority for its fixed socket/state,
        # while Player owns the private per-session frame and preload files.
        # Root can create the daemon entries inside this directory without
        # taking ordinary playback's runtime away from the desktop identity.
        os.chown(MEDIADECODERUNTIME, 1000, 1000)
        os.chmod(MEDIADECODERUNTIME, 0o700)
        clearmediadecodestate()
        command = [
            MEDIADECODESERVICE,
            '--socket',
            MEDIADECODESOCKET,
            '--device',
            rendernode,
            '--worker',
            MEDIADECODEWORKER,
            '--socket-uid',
            '1000',
            '--socket-gid',
            '1000',
            '--allow-uid',
            '1000',
            '--worker-uid',
            str(MEDIADECODEWORKERUID),
            '--worker-gid',
            str(MEDIADECODEWORKERGID),
            '--max-sessions',
            str(policy['max_sessions']),
            '--max-connections',
            str(policy['max_sessions']),
            '--state',
            MEDIADECODESTATE,
        ]

        if policy['development_debug']:
            command.append('--debug')

        environment = mediadecodeserviceenvironment(
            windowtask,
            pathprovider,
            developmentdebug=policy['development_debug'],
        )
        proc = popenisolated(
            command,
            softwarepath=MEDIADECODESERVICE,
            logpath=MEDIADECODELOG,
            security_profile='video',
            start_new_session=True,
            env=environment,
        )
        TASKS['media'] = {
            'script': MEDIADECODESERVICE,
            'command': tuple(command),
            'proc': proc,
            'role': 'behind',
            'environment': environment,
            'windowserver_pid': int(windowserverproc.pid),
            'restart_delay': 1.0,
            'restart_limit': 3,
            'restart_failures': 0,
        }
        register('media', proc, 'behind')
    except Exception as error:
        TASKS.pop('media', None)
        clearmediadecodestate()
        print(
            'I could not start native media decoding. Chromium will decode media '
            f'in software. {type(error).__name__} {error}',
            flush=True,
        )
        return False

    deadline = time.monotonic() + MEDIADECODEREADYTIMEOUT

    while time.monotonic() < deadline:
        if mediadecodeready(proc, rendernode):
            print(
                f'My native media decoder is ready on process {proc.pid}, using '
                f'{rendernode}. It supports {policy["max_sessions"]} sessions '
                f'with protocol {MEDIADECODEPROTOCOL} '
                f'{MEDIADECODEPROTOCOLVERSION}.',
                flush=True,
            )
            return True

        if proc.poll() is not None:
            break

        time.sleep(MEDIADECODEREADYPOLL)

    status = proc.poll()
    stopmediadecodeservice()
    print(
        'My native media decoder did not become ready within '
        f'{MEDIADECODEREADYTIMEOUT:g} seconds and returned status {status}. '
        'Chromium will decode media in software.',
        flush=True,
    )
    return False


def initialiseterminalname():

    name = 'terminal'

    try:

        with open(TERMINALNAMEFILE, 'r', encoding='utf-8') as stream:

            candidate = stream.read(256).strip()

        if re.fullmatch(
            r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?',
            candidate
        ):

            name = candidate

    except OSError:

        pass

    encoded = name.encode('ascii')
    operation = libc.sethostname
    operation.argtypes = (ctypes.c_char_p, ctypes.c_size_t)
    operation.restype = ctypes.c_int

    if operation(encoded, len(encoded)) != 0:

        errornumber = ctypes.get_errno()
        print(
            'I could not name this terminal. ' + os.strerror(errornumber),
            flush=True
        )
        return False

    os.environ['HOSTNAME'] = name
    print(f'I have named this terminal {name}.', flush=True)
    return True

# operations
EARLYSYSTEMOPS = (
    [('driver server', DRIVERSERVERSCRIPT, 'behind')]
    if DRIVERSERVERENABLED else []
)
PRESTARTOPS = [
    ('network', NETWORKSCRIPT, 'behind'),
    ('python', PYTHONSCRIPT, 'behind'),
    ('input server', INPUTSERVERSCRIPT, 'behind'),
    ('reign', REIGNSCRIPT, 'behind'),
    ('audio server', AUDIOSERVERSCRIPT, 'behind'),
    ('window server', WINDOWSERVERSCRIPT, 'behind'),
    ('operations server', OPERATIONSSERVERSCRIPT, 'behind'),
    ('procedures', PROCEDURESCRIPT, 'behind'),
]
POSTSTARTOPS = [
    ('exchange', EXCHANGESCRIPT, 'behind'),
    ('expanse', EXPANSESCRIPT, 'front'),
]
if os.path.isfile(GUESTADDITIONSSCRIPT) and os.path.exists('/the one/drivers/nodes/vboxguest'):
    PRESTARTOPS.insert(0, ('virtualbox', GUESTADDITIONSSCRIPT, 'behind'))

SERVICESECURITYPROFILES = {
    'media': 'video',
    'driver server': 'driver',
    'network': 'network',
    'python': 'python',
    'input server': 'input',
    'reign': 'reign',
    'audio server': 'audio',
    'window server': 'window',
    'operations server': 'operations',
    'procedures': 'procedures',
    'exchange': 'exchange',
    'expanse': 'expanse',
    'virtualbox': 'virtualbox',
}

# window server
WINDOWSERVERACCEPT = '/.ephemeral/windowserver/accept.sock'
WINDOWSERVERREADYTIMEOUT = 30.0
WINDOWSERVERREADYMAXTIME = 90.0
WINDOWSERVERREADYPOLL = 0.05
# WELCOME carries the complete graphics capability record, including every
# cached DMA-BUF format. NVIDIA currently advertises enough formats for that
# single newline-delimited record to exceed 4 KiB.
WINDOWSERVERWELCOMELIMIT = 256 * 1024
BOOTPRESENTATIONTIMEOUT = 15.0
WINDOWSERVERGPUFAILUREEXIT = 70
WINDOWSERVERBACKENDINITFAILUREEXIT = 71
WINDOWSERVERCOMPOSITORFAILUREEXIT = 72
ACCELERATEDLOGINATTEMPTS = 3
_ACCELERATEDDRMCANDIDATES = ()
_ACCELERATEDDRMATTEMPT = 0
_KMSDRMCANDIDATES = ()
_KMSDRMATTEMPT = 0
GRAPHICSRECOVERYDELAY = 0.75
FRAMEBUFFERRECOVERYATTEMPTSPERCYCLE = 3
KMSRECOVERYATTEMPTSPERCYCLE = 3
FRAMEBUFFERRECOVERYVISIBLEDELAY = 15.0
GRAPHICSDRIVERRPCTIMEOUT = 30.0
GRAPHICSDRIVERRESPONSELIMIT = 65536
GRAPHICSDIAGNOSTICTIMEOUT = 3.0
NVIDIAPATHPROVIDERSOURCE = (
    '/the one/catalogue/graphics/nvidia/t1os-nvidia-path-provider.so'
)
NVIDIAPATHPROVIDER = '/.ephemeral/graphics/nvidia-path-provider.so'
# A complete DHCP failure can legitimately consume roughly 45 seconds across
# its bounded retries. Healthy links return much earlier; this ceiling only
# prevents a broken service from holding the login handoff indefinitely.
NETWORKREADYTIMEOUT = 60.0
NETWORKREADYPOLL = 0.10
DRIVERSERVERACCEPT = '/.ephemeral/drivers/accept.sock'
DRIVERSERVERREADYTIMEOUT = 90.0 if DEBUGSYSTEM else 45.0
DRIVERSERVERREADYPOLL = 0.10


class LoginPresentationFailure(RuntimeError):
    pass


class LoginClientBufferFailure(RuntimeError):
    pass


def acceleratedfailureaction(windowserverproc, acceptresponsive=False):

    # WindowServer reserves 70 for a verified GPU/DRM health failure, 71 for
    # provider/backend initialization failure, and 72 for a compositor/OpenGL
    # API failure with a healthy device. Initialization failure selects another
    # GPU in a fresh process because NVIDIA and Mesa cannot safely replace one
    # another after their process-wide EGL libraries have been loaded. A deadline,
    # absent process, or unresponsive process is not evidence of device loss:
    # terminate the display owner and let CPU-rendered KMS test the still-bound
    # device first. Every other failure likewise preserves HDMI/KMS. In
    # particular, never turn a missing DSO, provider setup exception, client
    # crash, or Python deadlock into an HDMI-disconnecting PCI reset.
    if windowserverproc is None:
        return 'cpu-kms'

    try:
        status = windowserverproc.poll()
    except Exception:
        return 'cpu-kms'

    if status is None:
        responsive = bool(
            acceptresponsive
            and windowserverhello()
        )

        if not responsive and len(_ACCELERATEDDRMCANDIDATES) > 1:
            return 'next-device'
        return 'cpu-kms'

    if int(status) == WINDOWSERVERGPUFAILUREEXIT:
        return 'gpu-reset'

    if int(status) == WINDOWSERVERBACKENDINITFAILUREEXIT:
        return 'next-device'

    if int(status) == WINDOWSERVERCOMPOSITORFAILUREEXIT:
        return 'cpu-kms'

    return 'cpu-kms'


def drmscanoutnodeavailable():

    try:
        return any(
            re.fullmatch(r'card[0-9]+', name)
            for name in os.listdir('/the one/drivers/nodes/dri')
        )
    except OSError:
        return False


def accelerateddrmcandidates():

    override = str(os.environ.get('T1OS_DRM_DEVICE', '')).strip()

    if override:
        return [override]

    noderoot = '/the one/drivers/nodes/dri'
    stateroot = '/the one/drivers/state/class/drm'

    try:
        cards = sorted(
            (
                os.path.join(noderoot, name)
                for name in os.listdir(noderoot)
                if re.fullmatch(r'card[0-9]+', name)
            ),
            key=lambda path: int(os.path.basename(path)[4:]),
        )
    except OSError:
        return []

    connected = []
    disconnected = []

    try:
        stateentries = os.listdir(stateroot)
    except OSError:
        stateentries = []

    for card in cards:
        cardname = os.path.basename(card)
        isconnected = False

        for entry in stateentries:

            if not entry.startswith(cardname + '-'):
                continue

            try:
                with open(
                    os.path.join(stateroot, entry, 'status'),
                    'r',
                    encoding='ascii',
                    errors='replace',
                ) as stream:
                    isconnected = stream.read(64).strip().lower() == 'connected'
            except OSError:
                continue

            if isconnected:
                break

        (connected if isconnected else disconnected).append(card)

    return connected + disconnected


def nextaccelerateddrmdevice():

    global _ACCELERATEDDRMCANDIDATES, _ACCELERATEDDRMATTEMPT
    global ACCELERATEDLOGINATTEMPTS

    candidates = tuple(accelerateddrmcandidates())

    if candidates != _ACCELERATEDDRMCANDIDATES:
        _ACCELERATEDDRMCANDIDATES = candidates
        _ACCELERATEDDRMATTEMPT = 0

    # Every discovered GPU gets at least one isolated provider process. Keep
    # the historical three-attempt floor for single-GPU driver recovery.
    ACCELERATEDLOGINATTEMPTS = max(3, len(candidates))

    if not candidates:
        return None

    device = candidates[_ACCELERATEDDRMATTEMPT % len(candidates)]
    _ACCELERATEDDRMATTEMPT += 1
    return device


def nextkmsdrmdevice():

    global _KMSDRMCANDIDATES, _KMSDRMATTEMPT
    global KMSRECOVERYATTEMPTSPERCYCLE

    candidates = tuple(accelerateddrmcandidates())

    if candidates != _KMSDRMCANDIDATES:
        _KMSDRMCANDIDATES = candidates
        _KMSDRMATTEMPT = 0

    KMSRECOVERYATTEMPTSPERCYCLE = max(3, len(candidates))

    if not candidates:
        return None

    device = candidates[_KMSDRMATTEMPT % len(candidates)]
    _KMSDRMATTEMPT += 1
    return device



## set environment

# import c library
libc = ctypes.CDLL('libc.so.6', use_errno=True)

for stream in (sys.stdin, sys.stdout, sys.stderr) if __name__ == '__main__' else ():

    try:
        os.set_inheritable(stream.fileno(), True)

    except OSError:
        pass



## functions

# misc functions
def sigchldhandler():

    # loop over children
    while True:

        try:

            # reap zombie children
            pid, _ = os.waitpid(-1, os.WNOHANG)

            # break when there are no zombies left
            if pid <= 0:
                break

        # reaping error
        except ChildProcessError:

            break

        except OSError as e:

            # os error during waitpid
            print(
                'I encountered an operating system error while collecting a '
                f'child process. {e}'
            )

            break

        except Exception as e:

            # unexpected error
            print(f'I encountered an error while collecting a child process. {e}')

            break


def _fatalwords(value, fallback):

    text = ' '.join(str(value or '').split()).lower()
    text = text.replace(':', ' -')
    text = re.sub(r'\s*-\s*-\s*', ' - ', text)
    text = ' '.join(text.split()).strip(' -')
    return text or str(fallback)


def operationalfailureline(component, reason):

    name = _fatalwords(component, 'system')
    detail = _fatalwords(reason, 'unknown fatal failure')

    if name.endswith(' failure'):
        name = name[:-8].rstrip()

    return f'{name} failure - {detail}'[:512]


def recordfatalerror(component, reason, logpaths=(), recovery=()):

    payload = {
        'format': 1,
        'time': time.time(),
        'boot_id': currentbootid(),
        'phase': str(SYSTEMPHASE),
        'component': _fatalwords(component, 'system'),
        'reason': _fatalwords(reason, 'unknown fatal failure'),
        'failure': operationalfailureline(component, reason),
        'logs': [str(path) for path in logpaths],
        'recovery': [str(value) for value in recovery],
    }

    try:
        os.makedirs(LOGDIR, exist_ok=True)
        with open(FATALERRORLOG, 'a', encoding='utf-8') as stream:
            stream.write(json.dumps(payload, sort_keys=True, separators=(',', ':')) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
    except Exception as error:
        print(f'I could not record the fatal operational error. {error}', flush=True)

    return payload


def fatalhold(reason, logpaths=()):

    setdisplayconsolemode(False)
    mirrordisplayconsole(force=True)
    print(f'I cannot continue. {reason}', flush=True)

    for path in logpaths:

        try:

            with open(path, 'r', encoding='utf-8', errors='replace') as handle:

                lines = handle.readlines()[-120:]

            print(f'I saved my diagnostic log at {path}.', flush=True)

            for line in lines:

                print(line.rstrip(), flush=True)

        except Exception as error:

            print(
                f'I could not read the diagnostic information at {path}. {error}',
                flush=True,
            )

    if os.getpid() != 1:

        raise SystemExit(1)

    print(
        'I cannot continue, so I will remain here and keep the diagnostics '
        'available.',
        flush=True,
    )

    while True:

        sigchldhandler()
        time.sleep(IDLERATE)


# streaming functions
def parselogstamp(line):

    try:

        # Accept legacy slash dates while Reign emits English-order colon dates.
        m = re.match(r'^\[(\d{2})[:/](\d{2})[:/](\d+)AE (\d{1,2}):(\d{2}):(\d{2}) (AM|PM)\]', line)

        if not m:
            return None

        day = int(m.group(1))

        mon = int(m.group(2))

        ae_year = int(m.group(3))

        hour12 = int(m.group(4))

        minute = int(m.group(5))

        second = int(m.group(6))

        ampm = m.group(7)

        hour24 = hour12 % 12

        if ampm == 'PM':
            hour24 += 12

        greg_year = ae_year + (AE_START_YEAR - 1)

        return (greg_year, mon, day, hour24, minute, second)

    except Exception:

        return None


def scanlogfiles():

    try:

        if not os.path.isdir(LOGDIR):
            return []

    except Exception:

        return []

    try:

        out = []

        for name in os.listdir(LOGDIR):


            if not name.endswith('.log'):
                continue

            out.append(os.path.join(LOGDIR, name))

        out.sort()
        return out

    except Exception:

        return []


def logstreamworker():

    state = {}

    seq = 0

    print()

    print('I am starting the system log stream.')

    print()

    while True:

        if not DEBUGSYSTEM:

            try:
                time.sleep(0.25)
            except Exception:
                pass

            continue

        try:

            paths = scanlogfiles()

        except Exception:

            paths = []

        for path in paths:

            if path in state:
                continue

            f = open(path, 'r', encoding='utf-8', errors='replace')

            try:

                f.seek(0, os.SEEK_END)

            except Exception:

                f.close()
                continue

            state[path] = {'f': f}

        dead = []

        for path, info in state.items():

            try:

                if not os.path.exists(path):
                    dead.append(path)

            except Exception:

                dead.append(path)

        for path in dead:

            f = state[path]['f']
            f.close()

            del state[path]
        buffer = []

        for path, info in state.items():

            f = info['f']

            while True:

                line = f.readline()

                if not line:
                    break

                seq += 1

                key = parselogstamp(line)

                if key is None:

                    try:

                        now = time.gmtime(time.time())

                        key = (now.tm_year, now.tm_mon, now.tm_mday, now.tm_hour, now.tm_min, now.tm_sec)

                    except Exception:

                        key = (9999, 12, 31, 23, 59, 59)

                try:

                    src = os.path.basename(path)

                except Exception:

                    src = 'unknown.log'

                buffer.append((key, seq, src, line.rstrip('\n')))

        buffer.sort(key=lambda x: (x[0], x[1]))

        for _, __, src, line in buffer:

            print(f'{line}')

        time.sleep(LOGSTREAMPOLL)


def startlogstream():

    try:

        t = threading.Thread(target=logstreamworker, daemon=True)

    except Exception as e:

        print(f'I could not start the system log stream. {e}')

        return

    try:

        t.start()

    except Exception as e:

        print(f'I could not launch the system log stream. {e}')

        return


def createephemeral():

    # check if ephemeral exists
    if not os.path.exists(EPHEMERALTIER):

        try:

            # if not then create
            os.makedirs(EPHEMERALTIER)

        except PermissionError:

            # permission denied error
            print('I do not have permission to create the temporary runtime tier.')

            return

    # The hardware initramfs creates this tmpfs before PID 1 so it can
    # materialize the Windows-safe packaged terminfo tree inside the normal
    # T1OS ephemeral hierarchy. Reuse that filesystem instead of hiding it
    # beneath a second tmpfs mount.
    if os.path.ismount(EPHEMERALTIER):
        # Applications create private, boot-scoped top-level work areas here.
        # Sticky tmp semantics let uid 1000 create them without allowing one
        # application to remove another application's directory.
        os.chmod(EPHEMERALTIER, 0o1777)
        return

    # use mount sys call
    res = libc.mount(
        b'tmpfs',
        EPHEMERALTIER.encode(),
        b'tmpfs',
        0,
        None
    )

    # if mount fails
    if res != 0:

        err = ctypes.get_errno()

        raise OSError(err, f"CREATION OF EPHEMERAL FAILED {os.strerror(err)}")

    os.chmod(EPHEMERALTIER, 0o1777)


# window server functions
def windowserverwelcome():

    try:

        # create socket
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(1.0)

    except Exception:

        return False

    try:

        # connect to window server accept socket
        s.connect(WINDOWSERVERACCEPT)

    except Exception:

        s.close()
        return False

    try:

        # send hello
        s.sendall((json.dumps({"op": "HELLO"}) + "\n").encode("utf-8"))

    except Exception:

        s.close()
        return False

    try:

        # Read one bounded newline-delimited response. A socket file wrapper can
        # wait indefinitely on some early-boot runtimes even when the socket has
        # a timeout, so keep the deadline explicit here.
        deadline = time.monotonic() + 1.0
        response = bytearray()

        while (
            b'\n' not in response
            and len(response) < WINDOWSERVERWELCOMELIMIT
        ):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('window server welcome timed out')
            s.settimeout(remaining)
            chunk = s.recv(min(
                4096,
                WINDOWSERVERWELCOMELIMIT - len(response),
            ))
            if not chunk:
                break
            response.extend(chunk)

        if b'\n' not in response:
            raise ValueError('window server welcome is incomplete or oversized')

        line = bytes(response).split(b'\n', 1)[0]

    except Exception:

        s.close()
        return False

    # close socket
    s.close()

    try:

        # validate welcome
        if not line:
            return False

        msg = json.loads(line.decode("utf-8", errors="replace").strip())

        if msg.get("op", "") != "WELCOME":

            return False

    except Exception:

        return False

    return msg


def windowserverhello():

    return bool(windowserverwelcome())


def waitwindowserver(proc=None):

    started = time.monotonic()
    inactivityend = started + float(WINDOWSERVERREADYTIMEOUT)
    absoluteend = started + float(WINDOWSERVERREADYMAXTIME)
    progresspaths = (
        LOGPATHS['window server'],
        GRAPHICSSOFTWARELOG,
    )

    def progresssignature():
        signature = []

        for path in progresspaths:
            try:
                status = os.stat(path)
                signature.append((
                    path,
                    int(status.st_size),
                    int(status.st_mtime_ns),
                ))
            except OSError:
                pass

        return tuple(signature)

    progress = progresssignature()

    lastnote = 0

    while (
        time.monotonic() < inactivityend
        and time.monotonic() < absoluteend
    ):

        # if we were given the proc, abort early if it died
        if proc is not None and proc.poll() is not None:

            print(
                'The window server stopped unexpectedly while I was preparing '
                'the display.'
            )

            return False

        # socket must exist first (fast path)
        if os.path.exists(WINDOWSERVERACCEPT):

            # Confirm protocol readiness and bind every later presentation
            # receipt to this exact WindowServer instance, not just a PID that
            # could eventually be reused.
            welcome = windowserverwelcome()

            if welcome:
                try:
                    welcomepid = int(welcome.get('windowserver_pid', 0))
                    welcomeserver = str(welcome.get('server', '')).strip()
                except (AttributeError, TypeError, ValueError):
                    welcomepid = 0
                    welcomeserver = ''

                if (
                    welcomeserver
                    and (
                        proc is None
                        or welcomepid == int(proc.pid)
                    )
                ):
                    if proc is not None:
                        setattr(proc, '_t1os_windowserver_server', welcomeserver)
                    return True

                # A stale socket or response from a replaced owner is not
                # readiness for the process PID 1 is currently supervising.

        # The representative startup workload deliberately exercises real
        # rendering and scanout before exposing the protocol. A working slow
        # renderer (notably TCG/softpipe) may need more than 15 seconds, while
        # a wedged Nouveau submit produces no further userspace progress.
        # Extend only the inactivity deadline when this exact process log
        # advances, and retain a hard total ceiling.
        currentprogress = progresssignature()

        if currentprogress and currentprogress != progress:
            progress = currentprogress
            inactivityend = min(
                absoluteend,
                time.monotonic() + float(WINDOWSERVERREADYTIMEOUT),
            )

        # periodic status line (1Hz)
        now = int(time.time())

        if now != lastnote:
            lastnote = now

        time.sleep(WINDOWSERVERREADYPOLL)

    print(
        'The window server did not become ready within '
        f'{time.monotonic() - started:.1f} seconds.',
        flush=True,
    )
    return False


def terminateprocess(proc, timeout=1.5):

    if proc is None:
        return True

    try:

        if proc.poll() is not None:
            return True

        proc.terminate()
        proc.wait(timeout=max(0.1, float(timeout)))
        return True

    except subprocess.TimeoutExpired:

        try:
            proc.kill()
            proc.wait(timeout=1.0)
            return True
        except subprocess.TimeoutExpired:
            return False
        except Exception:
            try:
                return proc.poll() is not None
            except Exception:
                return False

    except Exception:
        try:
            return proc.poll() is not None
        except Exception:
            return False


def terminatepid(pid, timeout=1.0):

    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return

    if pid <= 1 or pid == os.getpid():
        return

    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        return

    deadline = time.monotonic() + max(0.1, float(timeout))

    while time.monotonic() < deadline:

        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        except (PermissionError, OSError):
            break

        time.sleep(0.02)

    try:
        os.kill(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass


def preparenvidiapathprovider():

    if not os.path.isfile(NVIDIAPATHPROVIDERSOURCE):
        return None

    # CUDA otherwise derives /.nv/ComputeCache from the system launcher HOME.
    # This shared, sticky tmpfs directory is writable by both desktop clients
    # (uid 1000) and the isolated decoder worker (uid 65534).
    os.makedirs(NVIDIACACHEPATH, mode=0o1777, exist_ok=True)
    cachedescriptor = os.open(
        NVIDIACACHEPATH,
        os.O_RDONLY
        | getattr(os, 'O_DIRECTORY', 0)
        | getattr(os, 'O_NOFOLLOW', 0)
        | getattr(os, 'O_CLOEXEC', 0),
    )

    try:
        os.fchown(cachedescriptor, 0, 0)
        os.fchmod(cachedescriptor, 0o1777)
    finally:
        os.close(cachedescriptor)

    with open(NVIDIAPATHPROVIDERSOURCE, 'rb') as stream:
        payload = stream.read(1024 * 1024 + 1)

    if (
        not payload
        or len(payload) > 1024 * 1024
        or not payload.startswith(b'\x7fELF')
    ):
        raise OSError('NVIDIA path provider is missing or not a bounded ELF')

    parent = os.path.dirname(NVIDIAPATHPROVIDER)
    # The provider contains no secret and is preloaded by the measured
    # unprivileged Chromium GPU process as well as native video clients.
    # Keep the directory non-listable while granting pathname traversal.
    # Repair its metadata on every call because the tmpfs path can survive a
    # WindowServer restart and an identical provider used to return early.
    os.makedirs(parent, mode=0o711, exist_ok=True)
    parentdescriptor = os.open(
        parent,
        os.O_RDONLY
        | getattr(os, 'O_DIRECTORY', 0)
        | getattr(os, 'O_NOFOLLOW', 0)
        | getattr(os, 'O_CLOEXEC', 0),
    )

    try:
        os.fchown(parentdescriptor, 0, 0)
        os.fchmod(parentdescriptor, 0o711)
    finally:
        os.close(parentdescriptor)

    try:
        descriptor = os.open(
            NVIDIAPATHPROVIDER,
            os.O_RDONLY
            | getattr(os, 'O_NOFOLLOW', 0)
            | getattr(os, 'O_CLOEXEC', 0),
        )

        try:
            existing = bytearray()

            while len(existing) <= 1024 * 1024:
                chunk = os.read(
                    descriptor,
                    min(65536, 1024 * 1024 + 1 - len(existing)),
                )

                if not chunk:
                    break

                existing.extend(chunk)

            if bytes(existing) == payload:
                os.fchown(descriptor, 0, 0)
                os.fchmod(descriptor, 0o555)
                return NVIDIAPATHPROVIDER
        finally:
            os.close(descriptor)
    except OSError:
        pass

    temporary = f'{NVIDIAPATHPROVIDER}.{os.getpid()}.new'

    try:
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
                    raise OSError('short NVIDIA path-provider write')
                offset += written
            os.fsync(descriptor)
            os.fchmod(descriptor, 0o555)
        finally:
            os.close(descriptor)

        os.replace(temporary, NVIDIAPATHPROVIDER)
        directory = os.open(
            parent,
            os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0),
        )

        try:
            os.fsync(directory)
        finally:
            os.close(directory)

        return NVIDIAPATHPROVIDER
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def windowserverenvironment(backend):

    backend = str(backend).strip().lower()

    if backend not in ('opengl', 'kms-framebuffer', 'framebuffer'):
        raise ValueError(f'unsupported WindowServer recovery backend {backend}')

    environment = os.environ.copy()
    environment['T1OS_WINDOWSERVER_GRAPHICS_BACKEND'] = backend
    environment.pop('LD_PRELOAD', None)
    environment.pop('T1OS_DRM_DEVICE', None)
    environment.pop('T1OS_FIRMWARE_FRAMEBUFFER_BOOT', None)
    environment.pop('T1OS_FRAMEBUFFER_CONSOLE_OWNED', None)
    environment.pop('__NV_GBM_TRACE_ENABLED', None)

    if backend == 'opengl':
        environment.pop('T1OS_GRAPHICS', None)
        drmdevice = nextaccelerateddrmdevice()

        if drmdevice:
            environment['T1OS_DRM_DEVICE'] = drmdevice
            print(
                f'I selected the isolated accelerated display device {drmdevice} '
                f'for attempt {_ACCELERATEDDRMATTEMPT} of '
                f'{ACCELERATEDLOGINATTEMPTS}.',
                flush=True,
            )

        identity = (
            _drmpcigraphicsidentity(os.path.basename(drmdevice))
            if drmdevice
            else None
        )
        binding = str(identity[1] if identity else '').strip().lower()

        # NVIDIA's official userspace opens conventional NVIDIA device paths.
        # Inject its measured path translator only into a WindowServer selected
        # for the NVIDIA PCI driver. A missing/corrupt optional NVIDIA shim must
        # never prevent an AMD, Intel, Nouveau, or virtual Mesa candidate from
        # starting.
        if binding in ('nvidia', 'nvidia_drm', 'nvidia-drm'):
            # NVIDIA documents this provider-local switch as the supported way
            # to expose GBM backend diagnostics. stderr is already captured in
            # the WindowServer log, and the variable is never inherited by
            # Mesa candidates.
            environment['__NV_GBM_TRACE_ENABLED'] = '1'

            try:
                pathprovider = preparenvidiapathprovider()
            except Exception as error:
                pathprovider = None
                print(
                    f'I could not prepare the NVIDIA path provider for '
                    f'{drmdevice}. {error}',
                    flush=True,
                )

            if pathprovider is not None:
                environment['LD_PRELOAD'] = pathprovider
                environment['T1OS_NVIDIA_PATH_PROVIDER'] = pathprovider
                environment['T1OS_NVIDIA_PATH_PROVIDER_SOURCE'] = (
                    NVIDIAPATHPROVIDERSOURCE
                )
    else:
        environment['T1OS_GRAPHICS'] = 'cpu'
        environment.pop('T1OS_NVIDIA_PATH_PROVIDER', None)
        environment.pop('T1OS_NVIDIA_PATH_PROVIDER_SOURCE', None)

        if backend == 'kms-framebuffer':
            drmdevice = nextkmsdrmdevice()

            if drmdevice:
                environment['T1OS_DRM_DEVICE'] = drmdevice
                print(
                    f'I selected the isolated CPU display device {drmdevice} '
                    f'for attempt {_KMSDRMATTEMPT} of '
                    f'{KMSRECOVERYATTEMPTSPERCYCLE}.',
                    flush=True,
                )

        if (
            backend == 'framebuffer'
            and kernelcommandlineoption('t1os.graphics=framebuffer')
        ):
            environment['T1OS_FIRMWARE_FRAMEBUFFER_BOOT'] = '1'

        if backend == 'framebuffer':
            consoleowned = bool(setdisplayconsolemode(False))

            if consoleowned:
                environment['T1OS_FRAMEBUFFER_CONSOLE_OWNED'] = '1'
            else:
                print(
                    'I could not confirm text console ownership before starting '
                    'the framebuffer, so the native framebuffer will not map it.',
                    flush=True,
                )

    return environment


def launchwindowserver(backend):

    environment = windowserverenvironment(backend)
    os.makedirs(LOGDIR, exist_ok=True)

    for path in (
        WINDOWSERVERACCEPT,
        '/.ephemeral/windowserver/video.sock',
        ACCELERATEDBOOTREADYPATH,
        ACCELERATEDLOCKSCREENREADYPATH,
        ACCELERATIONUNAVAILABLEPATH,
        GRAPHICSCAPABILITYPATH,
        LOCKSCREENREADYPATH,
    ):

        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        except OSError:
            pass

    proc = popenisolated(
        [WINDOWSERVERSCRIPT],
        softwarepath=WINDOWSERVERSCRIPT,
        logpath=LOGPATHS['window server'],
        security_profile='window',
        start_new_session=True,
        env=environment,
    )

    TASKS['window server'] = {
        'script': WINDOWSERVERSCRIPT,
        'proc': proc,
        'role': 'behind',
        'environment': environment,
        'graphics_backend': str(backend),
        'started_at': time.monotonic(),
        'operational_failures': 0,
        'operational_failure_window': 0.0,
    }
    register('window server', proc, 'behind')
    print(
        f'I have started a window server attempt using the {backend} backend '
        f'on process {proc.pid}.',
        flush=True,
    )
    return proc


def replacewindowserver(backend):

    try:
        current = TASKS.get('window server', {}).get('proc')
    except Exception:
        current = None

    retirementattempt = 0

    while not terminateprocess(current):
        retirementattempt += 1

        if retirementattempt == 1:
            try:
                capturewindowserverhangbounded(
                    current,
                    'windowserver-owner-retirement',
                )
            except Exception as error:
                print(
                    f'I could not capture evidence from the unresponsive window '
                    f'server. {error}',
                    flush=True,
                )

        recordgraphicsrecovery(
            str(backend),
            retirementattempt,
            'windowserver-owner-retirement',
            f'previous WindowServer pid={getattr(current, "pid", 0)} '
            f'remains alive after TERM/KILL; refusing to stack a new DRM '
            f'owner',
            capturegpu=False,
        )

        if retirementattempt == 1 or retirementattempt % 3 == 0:
            requestfirmwaregraphicsrecovery(
                'previous WindowServer remained alive with possible DRM '
                'ownership after SIGKILL',
                retirementattempt,
            )

        time.sleep(GRAPHICSRECOVERYDELAY)

    return launchwindowserver(backend)


def _kernelringbuffer():

    # klogctl(3, ...) is a non-destructive snapshot of the kernel ring. Reading
    # The kernel message character stream would expose only records newer than
    # the open and could miss
    # the nouveau/GSP fault that caused an already-observed device loss.
    try:
        operation = libc.klogctl
    except AttributeError as error:
        raise OSError(38, os.strerror(38)) from error
    operation.argtypes = (ctypes.c_int, ctypes.c_void_p, ctypes.c_int)
    operation.restype = ctypes.c_int
    size = int(operation(10, None, 0))

    if size <= 0:
        errornumber = ctypes.get_errno()
        raise OSError(errornumber, os.strerror(errornumber))

    # The hardware boot command line reserves an 8 MiB kernel log. Keep a
    # defensive upper bound in case a future kernel reports a corrupt size.
    size = min(size, 16 * 1024 * 1024)
    buffer = ctypes.create_string_buffer(size + 1)
    count = int(operation(3, buffer, size))

    if count < 0:
        errornumber = ctypes.get_errno()
        raise OSError(errornumber, os.strerror(errornumber))

    return bytes(buffer.raw[:count]).decode('utf-8', errors='replace')


def _diagnostictext(path, limit=1024 * 1024):

    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as stream:
            return stream.read(limit).rstrip()
    except OSError as error:
        return f'<unavailable: {type(error).__name__}: {error}>'


def _gpufailurestate():

    lines = []
    processroot = '/the one/drivers/processes'
    stateroot = '/the one/drivers/state'

    for label, path in (
        ('kernel command line', os.path.join(processroot, 'cmdline')),
        ('loaded modules', os.path.join(processroot, 'modules')),
        ('graphics runtime', '/the one/software/graphics/version.txt'),
        ('graphics catalogue', '/the one/catalogue/graphics/catalogue.json'),
        ('driver runtime', '/the one/drivers/settings/runtime.json'),
        (
            'firmware manifest',
            '/the one/drivers/firmware/t1os-firmware-manifest.json',
        ),
        (
            'kernel module manifest',
            '/the one/drivers/modules/module-manifest.sha256',
        ),
    ):
        lines.extend((
            f'===== {label} =====',
            _diagnostictext(path),
        ))

    pcibase = os.path.join(stateroot, 'bus', 'pci', 'devices')
    lines.append('===== display PCI devices at failure =====')

    try:
        pcidevices = sorted(os.listdir(pcibase))
    except OSError as error:
        lines.append(f'<unavailable: {type(error).__name__}: {error}>')
        pcidevices = ()

    for device in pcidevices:
        base = os.path.join(pcibase, device)
        deviceclass = _diagnostictext(os.path.join(base, 'class'), 64).strip()

        if not (
            deviceclass.startswith('0x0300')
            or deviceclass.startswith('0x0302')
        ):
            continue

        lines.append(f'[pci {device}]')

        for attribute in (
            'class',
            'vendor',
            'device',
            'subsystem_vendor',
            'subsystem_device',
            'revision',
            'irq',
            'numa_node',
            'current_link_speed',
            'current_link_width',
            'max_link_speed',
            'max_link_width',
            'power/control',
            'power/runtime_status',
            'power/runtime_active_time',
            'power/runtime_suspended_time',
            'uevent',
        ):
            value = _diagnostictext(os.path.join(base, attribute), 65536)
            lines.append(f'{attribute}={value}')

        try:
            with open(os.path.join(base, 'config'), 'rb') as stream:
                pciconfig = stream.read(4096)
            lines.append(f'config_hex={pciconfig.hex()}')
        except OSError as error:
            lines.append(
                f'config_hex=<unavailable: {type(error).__name__}: {error}>'
            )

        for linkname in ('driver', 'iommu_group'):
            try:
                value = os.readlink(os.path.join(base, linkname))
            except OSError as error:
                value = f'<unavailable: {type(error).__name__}: {error}>'
            lines.append(f'{linkname}={value}')

    drmbase = os.path.join(stateroot, 'class', 'drm')
    lines.append('===== DRM nodes and connectors at failure =====')

    try:
        drmnodes = sorted(os.listdir(drmbase))
    except OSError as error:
        lines.append(f'<unavailable: {type(error).__name__}: {error}>')
        drmnodes = ()

    for node in drmnodes:
        base = os.path.join(drmbase, node)
        lines.append(f'[drm {node}]')

        try:
            lines.append(f'target={os.readlink(base)}')
        except OSError as error:
            lines.append(f'target=<unavailable: {type(error).__name__}: {error}>')

        for attribute in ('status', 'enabled', 'dpms', 'modes'):
            path = os.path.join(base, attribute)
            if os.path.exists(path):
                lines.append(f'{attribute}={_diagnostictext(path, 65536)}')

        edidpath = os.path.join(base, 'edid')
        try:
            with open(edidpath, 'rb') as stream:
                edid = stream.read(65536)
            if edid:
                lines.append(f'edid_hex={edid.hex()}')
        except OSError:
            pass

    lines.append('===== nouveau module at failure =====')
    nouveaubase = os.path.join(stateroot, 'module', 'nouveau')

    for attribute in ('version', 'srcversion', 'taint'):
        path = os.path.join(nouveaubase, attribute)
        if os.path.exists(path):
            lines.append(f'{attribute}={_diagnostictext(path, 65536)}')

    parameters = os.path.join(nouveaubase, 'parameters')
    try:
        parameternames = sorted(os.listdir(parameters))
    except OSError as error:
        lines.append(f'<parameters unavailable: {type(error).__name__}: {error}>')
        parameternames = ()

    for parameter in parameternames:
        lines.append(
            f'{parameter}={_diagnostictext(os.path.join(parameters, parameter), 65536)}'
        )

    return '\n'.join(lines)


def capturegpufailureevidence(payload):

    global _LASTGPUKERNELRING

    os.makedirs(LOGDIR, exist_ok=True)

    with open(GRAPHICSSOFTWARELOG, 'a', encoding='utf-8') as stream:
        stream.write('\n===== accelerated GPU failure =====\n')
        json.dump(payload, stream, sort_keys=True, separators=(',', ':'))
        stream.write('\n')
        stream.write(_gpufailurestate())
        stream.write('\n===== kernel ring at failure =====\n')

        try:
            kernelring = _kernelringbuffer()

            if (
                _LASTGPUKERNELRING is not None
                and kernelring.startswith(_LASTGPUKERNELRING)
            ):
                stream.write('<records since preceding GPU snapshot>\n')
                stream.write(kernelring[len(_LASTGPUKERNELRING):])
            else:
                stream.write('<complete non-destructive kernel-ring snapshot>\n')
                stream.write(kernelring)

            _LASTGPUKERNELRING = kernelring
        except OSError as error:
            stream.write(
                f'<kernel ring unavailable: {type(error).__name__}: {error}>\n'
            )

        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def capturewindowserverhangpid(pid, phase):

    pid = int(pid)

    if pid <= 1 or not processalive(pid):
        return False

    # Ask Python to identify the precise ctypes call before collecting kernel
    # task state. The handler is installed before graphics initialization.
    try:
        os.kill(pid, signal.SIGUSR2)
        time.sleep(0.05)
    except OSError:
        pass

    processbase = os.path.join(
        '/the one/drivers/processes',
        str(pid),
    )
    lines = [
        '',
        '===== accelerated WindowServer no-progress snapshot =====',
        f'timestamp={time.time():.6f}',
        f'phase={phase}',
        f'pid={pid}',
    ]

    for name in (
        'status',
        'wchan',
        'stack',
        'syscall',
        'limits',
        'maps',
        'smaps_rollup',
        'cmdline',
    ):
        lines.append(f'===== process {name} =====')
        lines.append(
            _diagnostictext(
                os.path.join(processbase, name),
                4 * 1024 * 1024 if name == 'maps' else 256 * 1024,
            )
        )

    taskbase = os.path.join(processbase, 'task')

    try:
        taskids = sorted(
            (
                name
                for name in os.listdir(taskbase)
                if name.isdigit()
            ),
            key=int,
        )[:256]
    except OSError as error:
        lines.append(
            f'<task list unavailable: {type(error).__name__}: {error}>'
        )
        taskids = ()

    for taskid in taskids:
        lines.append(f'===== thread {taskid} =====')

        for name in ('comm', 'status', 'wchan', 'stack', 'syscall'):
            lines.append(f'[{name}]')
            lines.append(
                _diagnostictext(
                    os.path.join(taskbase, taskid, name),
                    256 * 1024,
                )
            )

    fdinfobase = os.path.join(processbase, 'fdinfo')
    fdbase = os.path.join(processbase, 'fd')

    try:
        descriptors = sorted(
            (
                name
                for name in os.listdir(fdinfobase)
                if name.isdigit()
            ),
            key=int,
        )[:512]
    except OSError as error:
        lines.append(
            f'<fdinfo unavailable: {type(error).__name__}: {error}>'
        )
        descriptors = ()

    for descriptor in descriptors:
        lines.append(f'===== fd {descriptor} =====')

        try:
            lines.append(
                f'target={os.readlink(os.path.join(fdbase, descriptor))}'
            )
        except OSError as error:
            lines.append(
                f'target=<unavailable: {type(error).__name__}: {error}>'
            )

        lines.append(
            _diagnostictext(
                os.path.join(fdinfobase, descriptor),
                256 * 1024,
            )
        )

    os.makedirs(LOGDIR, exist_ok=True)

    with open(WINDOWSERVERSOFTWARELOG, 'a', encoding='utf-8') as stream:
        stream.write('\n'.join(lines))
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())

    # Persist the faulthandler append before replacing this owner.
    try:
        descriptor = os.open(
            WINDOWSERVERSOFTWARELOG,
            os.O_RDONLY | getattr(os, 'O_CLOEXEC', 0),
        )

        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError:
        pass

    return True


def _boundedgraphicsdiagnostic(
    arguments,
    timeout=GRAPHICSDIAGNOSTICTIMEOUT,
):

    command = [
        os.path.abspath(__file__),
        *[str(value) for value in arguments],
    ]
    helper = None

    try:
        helper = popensecured(
            command,
            os.path.abspath(__file__),
            'goddess',
            close_fds=True,
            start_new_session=True,
        )
        return helper.wait(
            timeout=max(0.1, float(timeout))
        ) == 0
    except subprocess.TimeoutExpired:
        print(
            'The graphics diagnostic on process '
            f'{getattr(helper, "pid", 0)} did not finish in time while running '
            f'{arguments[0] if arguments else "an unknown operation"}.',
            flush=True,
        )

        try:
            helper.kill()
        except Exception:
            pass

        return False
    except Exception as error:
        print(
            'I could not complete the graphics diagnostic operation '
            f'{arguments[0] if arguments else "unknown"}. {error}',
            flush=True,
        )
        return False


def capturewindowserverhangbounded(process, phase):

    if process is None:
        return False

    try:
        if process.poll() is not None:
            return False
        pid = int(process.pid)
    except Exception:
        return False

    return _boundedgraphicsdiagnostic(
        ('--graphics-hang-capture', pid, str(phase)),
    )


def capturegpufailureevidencebounded(payload):

    return _boundedgraphicsdiagnostic(
        (
            '--graphics-kernel-capture',
            json.dumps(payload, sort_keys=True, separators=(',', ':')),
        ),
    )


def recordgraphicsrecovery(
    backend,
    attempt,
    phase,
    reason,
    capturegpu=True,
):

    payload = {
        'format': 1,
        'timestamp': time.time(),
        'backend': str(backend),
        'attempt': int(attempt),
        'phase': str(phase),
        'reason': str(reason),
    }

    angelprint(
        f'I am recovering the {backend} graphics backend on attempt {attempt} '
        f'during the {phase} phase because {reason}.',
        flush=True,
    )

    try:
        os.makedirs(LOGDIR, exist_ok=True)

        with open(GRAPHICSRECOVERYLOG, 'a', encoding='utf-8') as stream:
            json.dump(payload, stream, sort_keys=True, separators=(',', ':'))
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())

    except OSError as error:
        angelprint(f'I could not update the graphics recovery log. {error}', flush=True)

    if capturegpu and str(backend).strip().lower() == 'opengl':
        try:
            capturegpufailureevidencebounded(payload)
        except Exception as error:
            angelprint(
                f'I could not capture evidence from the graphics processor '
                f'failure. {error}',
                flush=True,
            )


def visibleframebufferrecoveryretry(
    windowserverproc,
    attempt,
    cycle,
    trigger,
    reason,
    animationproc=None,
):

    # A permanently absent or unusable fbdev is the final display tier. Keep
    # trying to construct a local lock screen, but do not leave quiet boot in a
    # silent black retry loop. Drop every display owner, restore the inherited
    # tty0 to fbcon, and retain a durable, visible diagnostic between bounded
    # groups of framebuffer attempts.
    if animationproc is not None:
        stopbootanimation(animationproc)

    terminateprocess(windowserverproc)
    textmode = setdisplayconsolemode(False)
    mirrordisplayconsole(force=True)
    detail = (
        f'cycle={cycle} trigger={trigger} '
        f'last_failure={type(reason).__name__}: {reason}'
    )
    recordgraphicsrecovery(
        'framebuffer',
        attempt,
        'visible-framebuffer-retry',
        detail,
        capturegpu=False,
    )
    angelprint(
        'I could not show the lock screen through the firmware framebuffer '
        f'after {FRAMEBUFFERRECOVERYATTEMPTSPERCYCLE} attempts. This was '
        f'recovery cycle {cycle}, attempt {attempt}, triggered by {trigger}.',
        flush=True,
    )

    if not textmode:
            angelprint(
                'I could not place the inherited terminal in text mode, so the '
                'diagnostic may remain hidden until the framebuffer console recovers.',
                flush=True,
            )

    angelprint(
        f'I will keep the text diagnostics visible for '
        f'{FRAMEBUFFERRECOVERYVISIBLEDELAY:.0f} seconds before I try the '
        'firmware framebuffer lock screen again.',
        flush=True,
    )
    time.sleep(FRAMEBUFFERRECOVERYVISIBLEDELAY)


def normalisebootid(value):

    try:
        return str(uuid.UUID(str(value).strip()))
    except (ValueError, TypeError, AttributeError):
        return ''


def currentbootid(paths=BOOTIDPATHS):

    for path in paths:

        try:
            with open(path, 'r', encoding='ascii') as stream:
                bootid = normalisebootid(stream.read(128))
        except OSError:
            continue

        if bootid:
            return bootid

    return ''


def firmwaregraphicsrecoveryrequested():

    # Compatibility query for older diagnostics. Persistent graphics state is
    # deliberately non-authoritative: every ordinary boot probes the GPU first.
    return False


def discardlegacyfirmwaregraphicsrecovery():

    """Remove obsolete next-boot framebuffer state left by an older build."""

    try:
        os.unlink(GRAPHICSRECOVERYBOOT)
    except FileNotFoundError:
        return False
    except OSError as error:
        angelprint(
            f'I could not discard obsolete graphics recovery state. {error}',
            flush=True,
        )
        return False

    try:
        directory = os.open(
            os.path.dirname(GRAPHICSRECOVERYBOOT),
            os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0),
        )
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError:
        pass

    angelprint(
        'I discarded obsolete next-boot framebuffer state; this boot will '
        'start with native GPU graphics.',
        flush=True,
    )
    return True


def clearfirmwaregraphicsrecovery():

    if not firmwaregraphicsrecoveryrequested():
        return False

    try:
        os.unlink(GRAPHICSRECOVERYBOOT)
        directory = os.open(
            os.path.dirname(GRAPHICSRECOVERYBOOT),
            os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0),
        )

        try:
            os.fsync(directory)
        finally:
            os.close(directory)

        angelprint(
            'I verified the firmware framebuffer lock screen and cleared the '
            'graphics recovery boot request.',
            flush=True,
        )
        return True
    except OSError as error:
        angelprint(
            f'I could not clear the graphics recovery boot request. {error}',
            flush=True,
        )
        return False


def pinfirmwarerecoveryboot(root=EFIVARFSROOT):

    # efivarfs files start with a native little-endian u32 attributes field.
    # BootCurrent and BootNext then carry one little-endian u16 boot-option
    # number. Require the corresponding Boot#### record to exist before
    # writing; this prevents an unavailable or synthetic BootCurrent value
    # from turning a recovery reboot into an arbitrary firmware boot.
    root = os.path.abspath(str(root))
    currentpath = os.path.join(
        root,
        f'BootCurrent-{EFIVARGLOBALGUID}',
    )

    try:
        with open(currentpath, 'rb') as stream:
            currentdata = stream.read(7)

        if len(currentdata) != 6:
            raise ValueError(
                f'BootCurrent has invalid efivarfs size {len(currentdata)}'
            )

        current = int(struct.unpack_from('<H', currentdata, 4)[0])
        entrypath = os.path.join(
            root,
            f'Boot{current:04X}-{EFIVARGLOBALGUID}',
        )

        with open(entrypath, 'rb') as stream:
            entryheader = stream.read(6)

        if len(entryheader) < 6:
            raise ValueError(
                f'current firmware boot option Boot{current:04X} is invalid'
            )

        nextpath = os.path.join(
            root,
            f'BootNext-{EFIVARGLOBALGUID}',
        )
        payload = struct.pack('<IH', 7, current)
        originalflags = None

        # efivarfs deliberately marks some variables immutable. BootNext is a
        # standard variable, but firmware/kernel combinations can leave an
        # existing inode with that bit set. Clear only that bit on this exact
        # variable and restore it after the verified write.
        if os.path.exists(nextpath):
            flagdescriptor = os.open(
                nextpath,
                os.O_RDONLY
                | getattr(os, 'O_CLOEXEC', 0)
                | getattr(os, 'O_NOFOLLOW', 0),
            )

            try:
                flagbuffer = bytearray(4)
                fcntl.ioctl(
                    flagdescriptor,
                    FS_IOC_GETFLAGS,
                    flagbuffer,
                    True,
                )
                originalflags = int(
                    struct.unpack_from('<I', flagbuffer, 0)[0]
                )

                if originalflags & FS_IMMUTABLE_FL:
                    struct.pack_into(
                        '<I',
                        flagbuffer,
                        0,
                        originalflags & ~FS_IMMUTABLE_FL,
                    )
                    fcntl.ioctl(
                        flagdescriptor,
                        FS_IOC_SETFLAGS,
                        flagbuffer,
                        True,
                    )
            finally:
                os.close(flagdescriptor)

        try:
            descriptor = os.open(
                nextpath,
                os.O_WRONLY
                | os.O_CREAT
                | getattr(os, 'O_CLOEXEC', 0)
                | getattr(os, 'O_NOFOLLOW', 0),
                0o600,
            )

            try:
                offset = 0

                while offset < len(payload):
                    written = os.write(descriptor, payload[offset:])

                    if written <= 0:
                        raise OSError(
                            'short write while setting EFI BootNext'
                        )

                    offset += written
            finally:
                os.close(descriptor)

            # efivarfs commits each write through EFI SetVariable and
            # deliberately has no fsync operation. Read the variable back
            # instead of treating the expected fsync(EINVAL) as failure.
            with open(nextpath, 'rb') as stream:
                verified = stream.read(7)

            if verified != payload:
                raise OSError(
                    f'EFI BootNext verification failed for Boot{current:04X}'
                )

        finally:
            if (
                originalflags is not None
                and originalflags & FS_IMMUTABLE_FL
                and os.path.exists(nextpath)
            ):
                flagdescriptor = os.open(
                    nextpath,
                    os.O_RDONLY
                    | getattr(os, 'O_CLOEXEC', 0)
                    | getattr(os, 'O_NOFOLLOW', 0),
                )

                try:
                    flagbuffer = bytearray(
                        struct.pack('<I', originalflags)
                    )
                    fcntl.ioctl(
                        flagdescriptor,
                        FS_IOC_SETFLAGS,
                        flagbuffer,
                        True,
                    )
                finally:
                    os.close(flagdescriptor)

        angelprint(
            f'I have directed the next firmware recovery boot to the current '
            f'boot entry, BOOT{current:04X}.',
            flush=True,
        )
        return True, f'Boot{current:04X}'

    except (OSError, ValueError, struct.error) as error:
        return False, f'{type(error).__name__}: {error}'


def requestfirmwaregraphicsrecovery(reason, attempt):

    # Keep recovery within this boot. Never write BootNext and never persist a
    # decision which can make a later boot skip native GPU discovery.
    recordgraphicsrecovery(
        'opengl',
        attempt,
        'gpu-recovery-contained',
        f'{reason}; persistent next-boot framebuffer recovery is disabled',
        capturegpu=False,
    )
    return False


def _drmpcigraphicsidentity(node):

    node = os.path.basename(str(node))

    if not re.fullmatch(r'(?:card|renderD)[0-9]+', node):
        return None

    devicepath = os.path.realpath(
        os.path.join('/the one/drivers/state/class/drm', node, 'device')
    )
    bdf = ''

    for component in reversed(devicepath.split(os.sep)):
        if re.fullmatch(
            r'[0-9A-Fa-f]{4}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}\.[0-7]',
            component,
        ):
            bdf = component.lower()
            break

    if not bdf:
        return None

    # Only unbind a DRM driver that owns the PCI function itself. A virtio
    # DRM device, for example, is nested below a PCI transport; unbinding its
    # parent "virtio-pci" function would reset unrelated transport state and
    # is not a graphics-driver recovery operation.
    pcidevicepath = os.path.realpath(os.path.join(
        '/the one/drivers/state/bus/pci/devices',
        bdf,
    ))

    if os.path.normpath(devicepath) != os.path.normpath(pcidevicepath):
        return None

    driverpath = os.path.join(
        '/the one/drivers/state/bus/pci/devices',
        bdf,
        'driver',
    )

    if not os.path.islink(driverpath):
        return None

    try:
        driver = os.path.basename(os.path.realpath(driverpath))
    except OSError:
        return None

    if not re.fullmatch(r'[A-Za-z0-9_.-]+', driver):
        return None

    if driver.lower() in NONRESETTABLEPCITRANSPORTDRIVERS:
        return None

    return bdf, driver


def _windowservergraphicsdevices(windowserverproc):

    devices = set()

    try:
        pid = int(windowserverproc.pid)
    except (AttributeError, TypeError, ValueError):
        return devices

    descriptorroot = os.path.join(
        '/the one/drivers/processes',
        str(pid),
        'fd',
    )

    try:
        descriptors = os.listdir(descriptorroot)
    except OSError:
        return devices

    for descriptor in descriptors:
        try:
            target = os.readlink(os.path.join(descriptorroot, descriptor))
        except OSError:
            continue

        identity = _drmpcigraphicsidentity(os.path.basename(target))

        if identity is not None:
            devices.add(identity)

    return devices


def _connectedgraphicsdevices():

    devices = set()
    drmroot = '/the one/drivers/state/class/drm'

    try:
        nodes = os.listdir(drmroot)
    except OSError:
        return devices

    for node in nodes:
        match = re.match(r'^(card[0-9]+)-', node)

        if match is None:
            continue

        try:
            with open(
                os.path.join(drmroot, node, 'status'),
                'r',
                encoding='ascii',
                errors='replace',
            ) as stream:
                status = stream.read(32).strip().lower()
        except OSError:
            continue

        if status != 'connected':
            continue

        identity = _drmpcigraphicsidentity(match.group(1))

        if identity is not None:
            devices.add(identity)

    return devices


def _driverservergraphicsreset(bdf, driver):

    # Only DriverServer is authorized by the T1OS LSM to mutate the private
    # sysfs control mount. Keep PID 1 as the authenticated Unix peer, and let
    # DriverServer use bounded no-exec fork helpers which retain its authorized
    # process identity.
    request = json.dumps(
        {
            'request': 'RESET_GRAPHICS',
            'bdf': bdf,
            'driver': driver,
        },
        sort_keys=True,
        separators=(',', ':'),
    ).encode('utf-8') + b'\n'
    response = bytearray()

    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(GRAPHICSDRIVERRPCTIMEOUT)
            connection.connect(DRIVERSERVERACCEPT)
            connection.sendall(request)

            while b'\n' not in response:
                chunk = connection.recv(4096)

                if not chunk:
                    raise RuntimeError(
                        'DriverServer closed the reset response before newline'
                    )

                response.extend(chunk)

                if len(response) > GRAPHICSDRIVERRESPONSELIMIT:
                    raise RuntimeError(
                        'DriverServer reset response exceeded '
                        f'{GRAPHICSDRIVERRESPONSELIMIT} bytes'
                    )

        line, remainder = bytes(response).split(b'\n', 1)

        if remainder.strip():
            raise RuntimeError('DriverServer returned multiple reset responses')

        state = json.loads(line.decode('utf-8'))

        if not isinstance(state, dict):
            raise RuntimeError('DriverServer reset response was not an object')

        if (
            state.get('request') != 'RESET_GRAPHICS'
            or state.get('bdf') not in (None, bdf)
            or state.get('driver') not in (None, driver)
        ):
            raise RuntimeError('DriverServer reset response identity mismatch')

        return state.get('ok') is True, state

    except (OSError, ValueError, UnicodeDecodeError, RuntimeError) as error:
        return False, {
            'format': 1,
            'request': 'RESET_GRAPHICS',
            'state': 'error',
            'ok': False,
            'phase': 'transport',
            'errno': int(getattr(error, 'errno', 0) or 0),
            'errno_name': '',
            'message': f'{type(error).__name__}: {error}',
            'bdf': bdf,
            'driver': driver,
        }


def recovergraphicsdriver(
    windowserverproc,
    attempt,
    trigger,
    backend='opengl',
):

    # A missing inherited tty descriptor is an init hand-off contract failure,
    # not evidence that the DRM device is unhealthy.  Never turn that failure
    # into a live PCI driver unbind: vmwgfx and other display drivers may still
    # own active KMS resources, and tearing them down cannot recreate tty0.
    if DISPLAYCONSOLEFD is None:
        terminateprocess(windowserverproc)
        recordgraphicsrecovery(
            backend,
            attempt,
            'driver-reset-refused',
            f'trigger={trigger}; inherited tty0 descriptor unavailable; '
            'refusing to reset a display driver for an init hand-off failure',
            capturegpu=False,
        )
        return False

    # Provider-isolated launches retain the selected card in PID 1 even after
    # the failed process and its mirrored descriptor tree have vanished.
    # Treat that identity as authoritative so one failed adapter cannot reset
    # every other connected GPU, including the healthy card driving HDMI.
    selecteddevice = ''

    try:
        selecteddevice = str(
            TASKS.get('window server', {})
            .get('environment', {})
            .get('T1OS_DRM_DEVICE', '')
        ).strip()
    except Exception:
        selecteddevice = ''

    devices = set()
    selectedauthoritative = bool(selecteddevice)

    if selecteddevice:
        identity = _drmpcigraphicsidentity(
            os.path.basename(selecteddevice)
        )

        if identity is not None:
            devices.add(identity)

    if not devices and not selectedauthoritative:
        devices = _windowservergraphicsdevices(windowserverproc)

    if not devices and not selectedauthoritative:
        devices = _connectedgraphicsdevices()

    terminateprocess(windowserverproc)

    if not devices:
        recordgraphicsrecovery(
            backend,
            attempt,
            'driver-reset',
            f'no resettable PCI DRM device could be resolved after {trigger} '
            f'selected={selecteddevice or "unknown"}',
            capturegpu=False,
        )
        return False

    results = []
    recovered = True

    for bdf, driver in sorted(devices):
        ready, response = _driverservergraphicsreset(bdf, driver)
        # A successful reset of one adapter must not mask a failed reset of
        # another adapter selected from the failed WindowServer. Reopening any
        # poisoned member of the display set can immediately hang the new
        # owner, so every selected PCI display function must be healthy.
        recovered = recovered and ready
        results.append(
            json.dumps(
                response,
                sort_keys=True,
                separators=(',', ':'),
            )
        )

    recordgraphicsrecovery(
        backend,
        attempt,
        'driver-reset',
        f'trigger={trigger}; ' + '; '.join(results),
        capturegpu=False,
    )
    return recovered


def acceleratedreceipt(path, windowserverproc, role):

    if windowserverproc is None:
        return None

    try:
        expectedserver = str(
            getattr(windowserverproc, '_t1os_windowserver_server', '')
        ).strip()

        with open(path, 'r', encoding='utf-8') as stream:
            state = json.load(stream)

        if (
            not expectedserver
            or int(state.get('windowserver_pid', 0)) != int(windowserverproc.pid)
            or str(state.get('server', '')).strip() != expectedserver
            or state.get('role') != role
            or state.get('backend') != 'opengl'
            or state.get('hardware_accelerated') is not True
            or state.get('gpu_failed') is not False
            or state.get('full_coverage') is not True
            or not str(state.get('renderer', '')).strip()
        ):
            return None

        return state

    except (OSError, ValueError, TypeError):
        return None


def graphicscapabilityreceipt(windowserverproc):

    if windowserverproc is None:
        return None

    try:
        expectedserver = str(
            getattr(windowserverproc, '_t1os_windowserver_server', '')
        ).strip()

        with open(GRAPHICSCAPABILITYPATH, 'r', encoding='utf-8') as stream:
            state = json.load(stream)

        if (
            not expectedserver
            or int(state.get('windowserver_pid', 0)) != int(windowserverproc.pid)
            or str(state.get('server', '')).strip() != expectedserver
            or state.get('backend') != 'opengl'
            or state.get('gpu_failed') is not False
            or not str(state.get('renderer', '')).strip()
        ):
            return None

        capability = str(state.get('state', '')).strip()

        if capability == 'acceleration-unavailable':
            if (
                state.get('hardware_accelerated') is not False
                or state.get('software_renderer') is not True
                or state.get('gpu_compositor') is not True
            ):
                return None
        elif capability == 'accelerated-candidate':
            if (
                state.get('hardware_accelerated') is not True
                or state.get('software_renderer') is not False
                or state.get('gpu_compositor') is not True
            ):
                return None
        else:
            return None

        return state

    except (OSError, ValueError, TypeError):
        return None


def accelerationunavailablereceipt(windowserverproc, role=None):

    if windowserverproc is None:
        return None

    try:
        expectedserver = str(
            getattr(windowserverproc, '_t1os_windowserver_server', '')
        ).strip()

        with open(ACCELERATIONUNAVAILABLEPATH, 'r', encoding='utf-8') as stream:
            state = json.load(stream)

        if (
            not expectedserver
            or int(state.get('windowserver_pid', 0)) != int(windowserverproc.pid)
            or str(state.get('server', '')).strip() != expectedserver
            or state.get('backend') != 'opengl'
            or state.get('hardware_accelerated') is not False
            or state.get('software_renderer') is not True
            or state.get('gpu_failed') is not False
            or state.get('presentation_completed') is not True
            or state.get('reason') != 'hardware-acceleration-unavailable'
            or not str(state.get('server', '')).strip()
            or not str(state.get('renderer', '')).strip()
            or (
                role is not None
                and str(state.get('role', '')) != str(role)
            )
        ):
            return None

        return state

    except (OSError, ValueError, TypeError):
        return None


def waitacceleratedbootpresentation(windowserverproc, animationproc):

    if animationproc is None:
        if windowserverproc is not None and windowserverproc.poll() is None:
            return 'animation-failed'

        return 'gpu-failed'

    deadline = time.monotonic() + BOOTPRESENTATIONTIMEOUT

    while time.monotonic() < deadline:

        receipt = acceleratedreceipt(
            ACCELERATEDBOOTREADYPATH,
            windowserverproc,
            'boot animation',
        )

        if receipt is not None:
            print(
                'I verified the accelerated boot display on process '
                f'{windowserverproc.pid} using the {receipt["renderer"]} renderer.',
                flush=True,
            )
            return 'ready'

        unavailable = accelerationunavailablereceipt(
            windowserverproc,
            'boot animation',
        )

        if unavailable is not None:
            print(
                f'Hardware acceleration is unavailable through the '
                f'{unavailable["renderer"]} renderer on process '
                f'{windowserverproc.pid}. I am switching to CPU display output.',
                flush=True,
            )
            return 'acceleration-unavailable'

        if windowserverproc is None or windowserverproc.poll() is not None:
            return 'gpu-failed'

        if animationproc.poll() is not None:
            return 'animation-failed'

        time.sleep(0.02)

    if (
        windowserverproc is None
        or windowserverproc.poll() is not None
        or not windowserverhello()
    ):
        return 'gpu-failed'

    return 'animation-failed'


def animationstate(path, pid):

    try:

        with open(path, 'r', encoding='utf-8') as stream:
            state = json.load(stream)

        if int(state.get('pid', 0)) != int(pid):
            return ''

        return str(state.get('state', '')).strip().lower()

    except (FileNotFoundError, PermissionError, OSError, ValueError, TypeError):

        return ''


def animationdetails(path, pid):

    try:
        with open(path, 'r', encoding='utf-8') as stream:
            state = json.load(stream)
        if int(state.get('pid', 0)) != int(pid):
            return {}
        return dict(state)
    except (FileNotFoundError, PermissionError, OSError, ValueError, TypeError):
        return {}


def bootanimationstate(pid):

    return animationstate(BOOTANIMATIONSTATE, pid)


def poweranimationstate(pid):

    return animationstate(POWERANIMATIONSTATE, pid)


def bootanimationrequest(pid, action):

    temporary = f'{BOOTANIMATIONREQUEST}.{os.getpid()}.new'

    try:

        os.makedirs(BOOTANIMATIONBASE, mode=0o700, exist_ok=True)

        with open(temporary, 'w', encoding='utf-8') as stream:

            json.dump({
                'format': 1,
                'pid': int(pid),
                'action': str(action),
            }, stream, sort_keys=True, separators=(',', ':'))
            stream.flush()
            os.fsync(stream.fileno())

        os.replace(temporary, BOOTANIMATIONREQUEST)
        return True

    except Exception as error:

        try:
            os.unlink(temporary)
        except Exception:
            pass

        print(f'I could not request the boot animation. {error}', flush=True)
        return False


def stopbootanimation(proc):

    if proc is None:
        return True

    try:
        running = proc.poll() is None
    except Exception:
        return False

    if not running:
        return True

    bootanimationrequest(proc.pid, 'stop')
    deadline = time.monotonic() + 1.5

    while time.monotonic() < deadline:

        # "done" is written after the graphics object closes, but only process
        # exit proves every inherited fd and mmap has been released. Never let
        # DriverServer bind a native DRM driver while this process is live.
        bootanimationstate(proc.pid)

        if proc.poll() is not None:
            return True

        time.sleep(0.02)

    try:
        proc.terminate()
        proc.wait(timeout=1.0)
    except subprocess.TimeoutExpired:

        try:
            proc.kill()
            proc.wait(timeout=1.0)
        except Exception:
            pass

    except Exception:
        pass

    try:
        return proc.poll() is not None
    except Exception:
        return False


def startbootanimation(mode='dots'):

    if not os.path.isfile(BOOTANIMATIONSCRIPT):
        print('I cannot show the boot animation because its software is missing.', flush=True)
        return None

    mode = str(mode).strip().lower()

    if mode not in ('early-dots', 'dots'):
        mode = 'dots'

    try:
        os.makedirs(BOOTANIMATIONBASE, mode=0o700, exist_ok=True)
        os.makedirs(LOGDIR, exist_ok=True)
    except OSError as error:
        print(f'I could not prepare the boot animation workspace. {error}', flush=True)
        return None

    for path in (BOOTANIMATIONREQUEST, BOOTANIMATIONSTATE):

        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        except OSError:
            pass

    try:

        environment = os.environ.copy()

        if mode == 'early-dots':
            # PID 1 has just completed the KD_GRAPHICS transition. Allow
            # this one pre-driver child to use a native DRM fbdev that was
            # built into the kernel (virtio is the common case). The flag
            # is passed only to this child and never satisfies the
            # KD_TEXT-based lock-screen recovery proof.
            environment[
                'T1OS_EARLY_FRAMEBUFFER_GRAPHICS_OWNED'
            ] = '1'
        else:
            environment.pop(
                'T1OS_EARLY_FRAMEBUFFER_GRAPHICS_OWNED',
                None,
            )

        proc = popenisolated(
            [BOOTANIMATIONSCRIPT, mode],
            softwarepath=BOOTANIMATIONSCRIPT,
            logpath=LOGPATHS['boot animation'],
            security_profile='boot-animation',
            start_new_session=True,
            env=environment,
        )

    except (OSError, PermissionError) as error:

        print(f'I could not start the boot animation. {error}', flush=True)
        return None

    deadline = time.monotonic() + 5.0

    while time.monotonic() < deadline:

        if proc.poll() is not None:
            print(
                'The boot animation stopped before showing its first frame and '
                f'returned status {proc.returncode}.',
                flush=True
            )
            return None

        if bootanimationstate(proc.pid) == 'dots':

            label = 'early boot progress' if mode == 'early-dots' else 'boot progress'
            print(
                f'I am showing the {label} on process {proc.pid}.',
                flush=True
            )
            return proc

        time.sleep(0.02)

    print(
        f'The {mode} animation did not show its first frame in time.',
        flush=True
    )
    stopbootanimation(proc)
    return None


def startpoweranimation(action):

    action = str(action or '').strip().lower()

    if action not in VALIDPOWERACTIONS:
        return None

    if not os.path.isfile(BOOTANIMATIONSCRIPT):
        print('I cannot show the power animation because its software is missing.', flush=True)
        return None

    try:
        os.makedirs(POWERANIMATIONBASE, mode=0o700, exist_ok=True)
        os.makedirs(LOGDIR, exist_ok=True)
    except OSError as error:
        print(f'I could not prepare the power animation workspace. {error}', flush=True)
        return None

    for path in (POWERANIMATIONREQUEST, POWERANIMATIONSTATE):

        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        except OSError:
            pass

    try:

        proc = popenisolated(
            [BOOTANIMATIONSCRIPT, action],
            softwarepath=BOOTANIMATIONSCRIPT,
            logpath=LOGPATHS['power animation'],
            security_profile='boot-animation',
            start_new_session=True,
        )

    except (OSError, PermissionError) as error:
        print(f'I could not start the power animation. {error}', flush=True)
        return None

    deadline = time.monotonic() + 5.0

    while time.monotonic() < deadline:

        if proc.poll() is not None:
            print(
                'The power animation stopped before showing its first frame and '
                f'returned status {proc.returncode}.',
                flush=True
            )
            return None

        if poweranimationstate(proc.pid) == 'visible':
            print(
                f'I am showing the {action} animation on process {proc.pid}.',
                flush=True
            )
            return proc

        time.sleep(0.02)

    print(f'The {action} animation did not show its first frame in time.', flush=True)

    try:
        proc.terminate()
        proc.wait(timeout=1.0)
    except Exception:
        pass

    return None


def fatalanimationstate(pid):

    return animationstate(FATALANIMATIONSTATE, pid)


def fatalanimationrequest(pid, action='stop'):

    temporary = f'{FATALANIMATIONREQUEST}.{os.getpid()}.new'

    try:
        with open(temporary, 'w', encoding='utf-8') as stream:
            json.dump({
                'format': 1,
                'pid': int(pid),
                'action': str(action),
            }, stream, sort_keys=True, separators=(',', ':'))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, FATALANIMATIONREQUEST)
        return True
    except Exception:
        try:
            os.unlink(temporary)
        except Exception:
            pass
        return False


def startfatalanimation(component, reason):

    failure = operationalfailureline(component, reason)
    temporary = f'{FATALANIMATIONCONTENT}.{os.getpid()}.new'

    if not os.path.isfile(BOOTANIMATIONSCRIPT):
        return None

    try:
        os.makedirs(FATALANIMATIONBASE, mode=0o700, exist_ok=True)
        os.makedirs(LOGDIR, exist_ok=True)

        for path in (FATALANIMATIONREQUEST, FATALANIMATIONSTATE):
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass

        with open(temporary, 'w', encoding='utf-8') as stream:
            json.dump({
                'format': 1,
                'failure': failure,
            }, stream, sort_keys=True, separators=(',', ':'))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, FATALANIMATIONCONTENT)

        environment = os.environ.copy()
        # A fatal screen is a single static frame. CPU drawing makes its
        # presentation independent of the accelerated scene that may have
        # caused the operational failure.
        environment['T1OS_BOOT_GRAPHICS'] = 'cpu'
        proc = popenisolated(
            [BOOTANIMATIONSCRIPT, 'fatal'],
            softwarepath=BOOTANIMATIONSCRIPT,
            logpath=LOGPATHS['fatal screen'],
            security_profile='boot-animation',
            start_new_session=True,
            env=environment,
        )
    except Exception as error:
        try:
            os.unlink(temporary)
        except Exception:
            pass
        print(f'I could not start the fatal system screen. {error}', flush=True)
        return None

    deadline = time.monotonic() + FATALPRESENTTIMEOUT

    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return None
        if fatalanimationstate(proc.pid) == 'visible':
            return proc
        time.sleep(0.02)

    fatalanimationrequest(proc.pid)
    terminateprocess(proc)
    return None


def driverserverstatus():

    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

    try:

        connection.settimeout(1.0)
        connection.connect(DRIVERSERVERACCEPT)
        connection.sendall(b'STATUS\n')
        response = bytearray()

        while b'\n' not in response and len(response) < 65536:
            chunk = connection.recv(65536 - len(response))
            if not chunk:
                break
            response.extend(chunk)

        if not response:
            return None

        status = json.loads(bytes(response).split(b'\n', 1)[0].decode('utf-8', errors='replace'))
        if status.get('state') not in ('ready', 'degraded'):
            return None
        return status

    except Exception:

        return None

    finally:

        connection.close()


def waitdriverserver(proc=None):

    try:
        end = time.time() + float(DRIVERSERVERREADYTIMEOUT)
    except Exception:
        end = time.time() + 45.0

    while time.time() < end:

        if proc is not None and proc.poll() is not None:
            print(
                'The driver server stopped unexpectedly while I was preparing '
                'the system.',
                flush=True,
            )
            return None

        if os.path.exists(DRIVERSERVERACCEPT):
            status = driverserverstatus()
            if status is not None:
                return status

        time.sleep(DRIVERSERVERREADYPOLL)

    print('The driver server did not become ready in time.', flush=True)
    return None


def validatenetworkinitialstate(state):

    if not isinstance(state, dict) or set(state) != NETWORKINITIALSTATEFIELDS:
        raise ValueError('invalid initial network state fields')
    if type(state.get('format')) is not int or state['format'] != 1:
        raise ValueError('invalid initial network state format')
    if type(state.get('connected')) is not bool:
        raise ValueError('invalid initial network connection status')
    interface = state.get('interface')
    if (
        not isinstance(interface, str)
        or NETWORKINITIALSTATEINTERFACE.fullmatch(interface) is None
    ):
        raise ValueError('invalid initial network interface')
    completed = state.get('completed')
    if type(completed) is not int or completed <= 0:
        raise ValueError('invalid initial network completion time')
    return state


def readnetworkinitialstate():

    descriptor = os.open(
        NETWORKINITIALSTATE,
        os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) |
        getattr(os, 'O_CLOEXEC', 0),
    )
    try:
        before = os.fstat(descriptor)
        if (
            not statmodule.S_ISREG(before.st_mode)
            or before.st_uid != 0
            or before.st_gid != 0
            or before.st_nlink != 1
            or statmodule.S_IMODE(before.st_mode) != 0o600
            or before.st_size <= 0
            or before.st_size > NETWORKINITIALSTATEMAXIMUM
        ):
            raise PermissionError('initial network state metadata is unsafe')

        payload = bytearray()
        while len(payload) <= NETWORKINITIALSTATEMAXIMUM:
            block = os.read(
                descriptor,
                NETWORKINITIALSTATEMAXIMUM + 1 - len(payload),
            )
            if not block:
                break
            payload.extend(block)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)

    if (
        len(payload) > NETWORKINITIALSTATEMAXIMUM
        or len(payload) != before.st_size
        or not payload.endswith(b'\n')
        or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) !=
           (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    ):
        raise ValueError('initial network state changed while reading')

    state = json.loads(bytes(payload).decode('utf-8', errors='strict'))
    return validatenetworkinitialstate(state)


def readnetworkinitialoutput(proc):

    if proc is None or not hasattr(proc, 'outputtail'):
        return None

    payload = proc.outputtail()
    if not isinstance(payload, bytes) or len(payload) > 65536:
        return None

    prefix = b'T1OS_NETWORK_INITIAL='
    for line in reversed(payload.splitlines()):
        if not line.startswith(prefix):
            continue
        encoded = line[len(prefix):]
        if not encoded or len(encoded) > NETWORKINITIALSTATEMAXIMUM:
            raise ValueError('initial network output is invalid')
        state = json.loads(encoded.decode('utf-8', errors='strict'))
        return validatenetworkinitialstate(state)

    return None


def waitnetworkstartup(proc=None):

    deadline = time.monotonic() + NETWORKREADYTIMEOUT

    while time.monotonic() < deadline:

        if proc is not None and proc.poll() is not None:
            print(
                'The network service stopped before its first connection attempt '
                f'and returned status {proc.returncode}.',
                flush=True
            )
            return False

        try:
            # This pipe belongs to the exact profiled child launched above, so
            # it is both cheaper and more authoritative than repeatedly
            # crossing the kernel domain boundary to poll its private file.
            state = readnetworkinitialoutput(proc)
            if state is None:
                state = readnetworkinitialstate()
        except (OSError, ValueError, TypeError, UnicodeError):
            state = None

        if state is not None:
            connected = state['connected']
            interface = state['interface'] or 'none'
            print(
                'I have completed my first network connection attempt. '
                f'The {interface} interface is '
                f'{"connected" if connected else "not connected"}.',
                flush=True
            )
            return connected

        time.sleep(NETWORKREADYPOLL)

    print(
        f'The first network connection attempt is still running after '
        f'{NETWORKREADYTIMEOUT:.0f} seconds, so I will continue starting the system.',
        flush=True
    )
    return False


def lockscreenlifecycle():

    try:

        with open(LOCKSCREENSTATE, 'r', encoding='utf-8') as stream:
            state = json.load(stream)

        return state if isinstance(state, dict) else {}

    except (OSError, ValueError, TypeError):

        return {}


def lockscreenposthandoffreceipt(windowserverproc, lockpid):

    try:

        with open(LOCKSCREENPOSTHANDOFFSTATE, 'r', encoding='utf-8') as stream:
            marker = json.load(stream)

        with open(LOCKSCREENREADYPATH, 'r', encoding='utf-8') as stream:
            current = json.load(stream)

        if not isinstance(marker, dict) or not isinstance(current, dict):
            return None

        markerpid = int(marker.get('pid', 0))
        windowserverpid = int(marker.get('windowserver_pid', 0))
        sequence = int(marker.get('frame_sequence', 0))
        server = str(marker.get('server', '')).strip()
        backend = str(marker.get('backend', '')).strip().lower()

        if (
            marker.get('format') != 1
            or marker.get('state') != 'ready'
            or markerpid != int(lockpid)
            or markerpid <= 1
            or windowserverproc is None
            or windowserverproc.poll() is not None
            or windowserverpid != int(windowserverproc.pid)
            or windowserverpid <= 1
            or not server
            or backend not in ('opengl', 'framebuffer', 'kms-framebuffer')
            or sequence <= 0
            or marker.get('boot_active') is not False
            or marker.get('physically_verified') is not True
            or current.get('role') != 'lockscreen'
            or current.get('topmost_role') != 'lockscreen'
            or int(current.get('topmost_window', 0)) not in [
                int(value) for value in current.get('windows', [])
            ]
            or int(current.get('windowserver_pid', 0)) != windowserverpid
            or str(current.get('server', '')).strip() != server
            or str(current.get('backend', '')).strip().lower() != backend
            or int(current.get('frame_sequence', 0)) < sequence
            or current.get('boot_active') is not False
            or current.get('gpu_failed') is not False
        ):
            return None

        return marker

    except (OSError, ValueError, TypeError):

        return None


def stopstartupattempt(process):

    state = lockscreenlifecycle()

    try:
        lockpid = int(state.get('pid', 0))
    except (TypeError, ValueError):
        lockpid = 0

    terminatepid(lockpid)
    terminateprocess(process)


def runstartup(environment, windowserverproc=None):

    # Startup and its lock-screen child must not depend on the boot console
    # remaining writable. In particular, a graphics-mode transition can make a
    # console-backed Python stream fail during interpreter finalisation, which
    # Python reports as exit status 120. Keep startup diagnostics in the T1OS
    # log tier and observe the explicit lock-screen lifecycle barrier instead.
    os.makedirs(LOGDIR, exist_ok=True)

    for path in (LOCKSCREENSTATE, LOCKSCREENPOSTHANDOFFSTATE):
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        except OSError:
            pass

    with popenisolated(
        [STARTUPSCRIPT],
        softwarepath=STARTUPSCRIPT,
        logpath=STARTUPLOG,
        security_profile='startup',
        env=environment,
    ) as process:
        readinessannounced = False
        posthandoffannounced = False
        posthandoffdeadline = None

        while True:

            status = process.poll()

            if status is not None:

                if status != 0:
                    state = lockscreenlifecycle()
                    lifecyclestate = str(
                        state.get('state', '')
                    ).strip().lower()
                    detail = str(state.get('detail', '')).strip()
                    stopstartupattempt(process)

                    if lifecyclestate in ('starting', 'failed'):
                        raise LoginPresentationFailure(
                            f'lock screen exited before verified presentation '
                            f'state={lifecyclestate} detail={detail or "none"} '
                            f'status={status}'
                        )

                    raise subprocess.CalledProcessError(status, process.args)

                return

            if (
                windowserverproc is None
                or windowserverproc.poll() is not None
            ):
                windowserverstatus = (
                    'missing'
                    if windowserverproc is None
                    else str(windowserverproc.returncode)
                )
                windowserverlog = _diagnostictext(
                    GRAPHICSSOFTWARELOG,
                    65536,
                ).splitlines()
                windowserverdetail = (
                    windowserverlog[-1].strip()
                    if windowserverlog
                    else 'no diagnostic log entry'
                )
                stopstartupattempt(process)
                raise LoginPresentationFailure(
                    'WindowServer exited before login completed '
                    f'status={windowserverstatus} '
                    f'last_log={windowserverdetail}'
                )

            state = lockscreenlifecycle()
            lifecyclestate = str(state.get('state', '')).strip().lower()

            if lifecyclestate == 'failed':
                detail = str(state.get('detail', '')).strip() or 'unspecified failure'
                stopstartupattempt(process)

                if 'WindowBufferAccessError:' in detail:
                    raise LoginClientBufferFailure(
                        f'lock screen window-buffer initialization failed: {detail}'
                    )

                raise LoginPresentationFailure(
                    f'lock screen reported first-frame failure: {detail}'
                )

            if not readinessannounced and lifecyclestate == 'ready':

                try:
                    lockpid = int(state.get('pid', 0))
                except (TypeError, ValueError):
                    lockpid = 0

                if (
                    str(environment.get(
                        'T1OS_WINDOWSERVER_GRAPHICS_BACKEND',
                        '',
                    )).strip().lower() == 'opengl'
                    and acceleratedreceipt(
                        ACCELERATEDLOCKSCREENREADYPATH,
                        windowserverproc,
                        'lockscreen',
                    ) is None
                ):
                    stopstartupattempt(process)
                    raise LoginPresentationFailure(
                        'lock screen claimed readiness without the current '
                        'WindowServer accelerated presentation receipt'
                    )

                    print(
                        formatlog(
                            'startup',
                            f'The lock screen showed its first frame on process '
                            f'{lockpid}.'
                        ),
                        flush=True
                    )
                readinessannounced = True
                posthandoffdeadline = (
                    time.monotonic() + LOCKSCREENPOSTHANDOFFTIMEOUT
                )

            if readinessannounced and not posthandoffannounced:

                try:
                    lockpid = int(state.get('pid', 0))
                except (TypeError, ValueError):
                    lockpid = 0

                receipt = lockscreenposthandoffreceipt(
                    windowserverproc,
                    lockpid,
                )

                if receipt is not None:
                    print(
                        formatlog(
                            'startup',
                            'I verified the lock screen after the display handoff '
                            f'on process {lockpid}, using the '
                            f'{receipt.get("backend", "")} backend at frame '
                            f'{receipt.get("frame_sequence", 0)} and the '
                            f'{receipt.get("presentation_boundary", "") or "none"} '
                            'presentation boundary.'
                        ),
                        flush=True
                    )
                    posthandoffannounced = True
                elif (
                    posthandoffdeadline is not None
                    and time.monotonic() >= posthandoffdeadline
                ):
                    stopstartupattempt(process)
                    raise LoginPresentationFailure(
                        'lock screen first frame did not advance to a '
                        'current physically verified post-handoff receipt'
                    )

            time.sleep(0.02)


# GODDESS functions
def birth(ops):

    for name, script, role in ops:

        if DEBUGSYSTEM:
            print(f'I am starting {name}.', flush=True)

        logpath = softwarelogpath(script, LOGPATHS.get(name))

        # birth operation
        try:

            environment = None
            graphicsbackend = None

            if name == 'window server':
                if (
                    kernelcommandlineoption('t1os.graphics=framebuffer')
                    or str(
                        os.environ.get('T1OS_GRAPHICS', '')
                    ).strip().lower() == 'framebuffer'
                ):
                    graphicsbackend = 'framebuffer'
                else:
                    graphicsbackend = (
                        'kms-framebuffer'
                        if (
                        kernelcommandlineoption('t1os.graphics=cpu')
                        or str(os.environ.get('T1OS_GRAPHICS', '')).strip().lower() == 'cpu'
                        )
                        else 'opengl'
                    )
                environment = windowserverenvironment(graphicsbackend)

            elif (
                name == 'python'
                and os.environ.get('T1OS_DEVELOPER') == '1'
                and os.environ.get('T1OS_ENABLE_VM_TEST_AGENT') == '1'
            ):
                # The release kernel keeps /the one/software and /the one/catalogue
                # immutable.  The signed disposable VM publishes a root-owned,
                # DAC-restricted package area below /software so the real manager
                # can exercise transactions without widening the kernel policy.
                testroot = '/software/t1os-python'
                environment = os.environ.copy()
                environment.update({
                    'T1OS_PYTHON_MANAGEMENT_ROOT': testroot + '/management',
                    'T1OS_PYTHON_SITE_PACKAGES': testroot + '/site-packages',
                    'T1OS_PYTHON_BIN': os.path.join(testroot, 'bin'),
                    'T1OS_PYTHON_CATALOGUE': testroot + '/catalogue',
                })

            proc = popenisolated(
                [script],
                softwarepath=script,
                logpath=logpath,
                security_profile=SERVICESECURITYPROFILES.get(name),
                preexec_fn=(dropdesktopidentity if name == 'expanse' else None),
                start_new_session=True,
                env=environment,
            )

        except FileNotFoundError:

            # script not found error
            print(f'I cannot start {name} because its software is missing.')

            return

        except PermissionError:

            # permission denied error
            print(f'I do not have permission to start {name}.')

            return

        except OSError as e:

            # os error birthing operation
            print(f'I could not start {name}. {e}')

            return

        # add to tasks
        TASKS[name] = {
            'script': script,
            'proc': proc,
            'role': role,
            'environment': environment,
            'started_at': time.monotonic(),
            'operational_failures': 0,
            'operational_failure_window': 0.0,
        }

        if graphicsbackend is not None:
            TASKS[name]['graphics_backend'] = graphicsbackend

        # register
        register(name, proc, role)

        if DEBUGSYSTEM:
            print(f'I have started {name} on process {proc.pid}.', flush=True)


def setuppowerserver():

    global POWERSERVER

    directory = os.path.dirname(POWERCONTROLSOCKET)
    os.makedirs(directory, mode=0o750, exist_ok=True)

    try:
        os.chown(directory, 0, 1000)
        os.chmod(directory, 0o750)
    except OSError:
        pass

    try:
        os.unlink(POWERCONTROLSOCKET)
    except FileNotFoundError:
        pass

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

    try:
        server.bind(POWERCONTROLSOCKET)
        os.chown(POWERCONTROLSOCKET, 0, 1000)
        os.chmod(POWERCONTROLSOCKET, 0o660)
        server.listen(8)
        server.setblocking(False)
    except Exception:
        server.close()
        raise

    POWERSERVER = server
    print('I am ready to receive power requests.', flush=True)


def closepowerserver():

    global POWERSERVER

    server = POWERSERVER
    POWERSERVER = None

    if server is not None:

        try:
            server.close()
        except Exception:
            pass

    try:
        os.unlink(POWERCONTROLSOCKET)
    except FileNotFoundError:
        pass
    except OSError:
        pass


def sendpowerresponse(connection, ok, action='', error='', recovery_action=''):

    response = {
        'format': 1,
        'ok': bool(ok),
    }

    if action:
        response['action'] = str(action)

    if error:
        response['error'] = str(error)

    if recovery_action:
        response['recovery_action'] = str(recovery_action)

    connection.sendall(
        json.dumps(response, sort_keys=True, separators=(',', ':')).encode('utf-8') + b'\n'
    )


def currentbootidentity():

    with open(BOOTIDPATHS[0], 'r', encoding='ascii') as stream:
        value = stream.read(128).strip().lower()
    parsed = uuid.UUID(value)
    if str(parsed) != value:
        raise ValueError('invalid kernel boot identity')
    return value


def armrecoveryrequest(action, authorization_digest='', origin_boot_id=''):

    action = str(action or '').strip().lower()

    if action not in VALIDRECOVERYACTIONS:
        raise ValueError('unsupported recovery action')
    authorization_digest = str(authorization_digest or '').strip().lower()
    if authorization_digest and not re.fullmatch(r'[0-9a-f]{64}', authorization_digest):
        raise ValueError('invalid recovery authorization digest')
    if action in DESTRUCTIVERECOVERYACTIONS and not authorization_digest:
        raise ValueError('destructive recovery authorization is required')
    origin_boot_id = str(origin_boot_id or '').strip().lower()
    if str(uuid.UUID(origin_boot_id)) != origin_boot_id:
        raise ValueError('invalid recovery origin boot identity')

    if not os.path.ismount(RECOVERYBOOTMOUNT):
        raise OSError('the Angel boot-partition request store is not mounted')

    directory = os.path.dirname(RECOVERYREQUEST)
    status = os.stat(directory, follow_symlinks=False)

    if not statmodule.S_ISDIR(status.st_mode):
        raise OSError('the Angel recovery request directory is not safe')

    temporary = f'{RECOVERYREQUEST}.{os.getpid()}.new'
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0),
            0o600,
        )

        try:
            payload = (
                'format=1\n'
                f'action={action}\n'
                f'origin_boot_id={origin_boot_id}\n'
                f'authorization_digest={authorization_digest}\n'
            ).encode('utf-8')
            offset = 0

            while offset < len(payload):
                written = os.write(descriptor, payload[offset:])

                if written <= 0:
                    raise OSError('short write while recording the recovery request')

                offset += written

            os.fsync(descriptor)
        finally:
            os.close(descriptor)

        os.replace(temporary, RECOVERYREQUEST)
        directorydescriptor = os.open(directory, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))

        try:
            os.fsync(directorydescriptor)
        finally:
            os.close(directorydescriptor)

        os.sync()
    except Exception:

        try:
            os.unlink(temporary)
        except OSError:
            pass

        raise

    pinned, detail = pinfirmwarerecoveryboot()

    if not pinned:
        angelprint(
            f'I recorded the {action} recovery request, but I could not pin the '
            f'next firmware boot to this drive. {detail}',
            flush=True,
        )
    else:
        angelprint(
            f'I recorded the {action} recovery request for the next boot.',
            flush=True,
        )


def armshutdownhealthgate(action):

    """Request an unmounted RootHealth gate in the next initramfs."""

    action = str(action or '').strip().lower()
    if action not in VALIDPOWERACTIONS:
        raise ValueError('unsupported shutdown health action')
    if not os.path.ismount(RECOVERYBOOTMOUNT):
        raise OSError('the Angel boot-partition request store is not mounted')

    directory = os.path.dirname(SHUTDOWNHEALTHREQUEST)
    status = os.stat(directory, follow_symlinks=False)
    if not statmodule.S_ISDIR(status.st_mode):
        raise OSError('the shutdown health request directory is not safe')

    temporary = f'{SHUTDOWNHEALTHREQUEST}.{os.getpid()}.new'
    descriptor = None
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL |
            getattr(os, 'O_NOFOLLOW', 0),
            0o600,
        )
        payload = (
            'format=1\n'
            'state=pending\n'
            f'action={action}\n'
            f'origin_boot_id={currentbootidentity()}\n'
        ).encode('ascii')
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise OSError('short write while recording the shutdown health gate')
            offset += written
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        os.replace(temporary, SHUTDOWNHEALTHREQUEST)
        directorydescriptor = os.open(
            directory,
            os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0),
        )
        try:
            os.fsync(directorydescriptor)
        finally:
            os.close(directorydescriptor)
        os.sync()
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    finally:
        if descriptor is not None:
            os.close(descriptor)


def processstartidentity(pid):

    path = f'/the one/drivers/processes/{int(pid)}/stat'
    with open(path, 'r', encoding='ascii', errors='strict') as stream:
        text = stream.read(16384).strip()
    fields = text.rsplit(')', 1)[1].strip().split()
    if len(fields) < 20:
        raise ValueError('process identity is incomplete')
    return int(fields[19])


def processsecuritydomain(pid):

    root = f'/the one/drivers/processes/{int(pid)}/attr'
    for relative in ('t1os/current', 'current'):
        try:
            with open(os.path.join(root, relative), 'r', encoding='ascii') as stream:
                value = stream.read(128).strip()
            if value.startswith('t1os:'):
                return value[5:]
        except OSError:
            pass
    return None


def authorisedpowerpeer(pid, uid):

    try:
        started = processstartidentity(pid)
        domain = processsecuritydomain(pid)
    except (OSError, ValueError):
        return None
    if domain == 'expanse' and int(uid) == 1000:
        return {'pid': int(pid), 'uid': int(uid), 'started': started, 'domain': domain}
    if domain == 'settings' and int(uid) == 1000:
        return {'pid': int(pid), 'uid': int(uid), 'started': started, 'domain': domain}
    if domain in ('goddess', 'operations') and int(uid) == 0:
        return {'pid': int(pid), 'uid': int(uid), 'started': started, 'domain': domain}
    return None


def powerpeerstillvalid(peer):

    try:
        return (
            processstartidentity(peer['pid']) == peer['started'] and
            processsecuritydomain(peer['pid']) == peer['domain']
        )
    except (OSError, ValueError, KeyError):
        return False


def receivepowerrequest(connection):

    global SYSTEMSTATE

    connection.settimeout(1.0)
    peerpid = None
    peeruid = None

    if hasattr(socket, 'SO_PEERCRED'):

        raw = connection.getsockopt(
            socket.SOL_SOCKET,
            socket.SO_PEERCRED,
            struct.calcsize('3i')
        )
        peerpid, peeruid, _ = struct.unpack('3i', raw)

    peer = authorisedpowerpeer(peerpid, peeruid) if peerpid is not None and peeruid is not None else None
    if peer is None:
        sendpowerresponse(connection, False, error='power request identity is not authorised')
        return None

    payload = bytearray()

    while len(payload) < 4096:

        chunk = connection.recv(min(1024, 4096 - len(payload)))

        if not chunk:
            break

        payload.extend(chunk)

        if b'\n' in chunk:
            break

    if len(payload) >= 4096 and b'\n' not in payload:
        sendpowerresponse(connection, False, error='power request is too large')
        return None
    line = bytes(payload).split(b'\n', 1)[0]

    try:
        request = json.loads(line.decode('utf-8'))
    except (UnicodeError, ValueError, TypeError):
        sendpowerresponse(connection, False, error='invalid power request')
        return None

    if not isinstance(request, dict) or int(request.get('format', 0)) != 1:
        sendpowerresponse(connection, False, error='unsupported power request format')
        return None

    action = str(request.get('action', '')).strip().lower()
    recoveryaction = str(request.get('recovery_action', '')).strip().lower()
    recoverytoken = str(request.get('recovery_token', '')).strip()
    recoverydigest = ''
    recoveryorigin = ''

    if action not in VALIDPOWERACTIONS:
        sendpowerresponse(connection, False, error='unsupported power action')
        return None

    if recoveryaction and (action != 'restart' or recoveryaction not in VALIDRECOVERYACTIONS):
        sendpowerresponse(connection, False, error='unsupported recovery action')
        return None

    if not powerpeerstillvalid(peer):
        sendpowerresponse(connection, False, error='power request identity changed')
        return None

    if recoveryaction:
        # Recovery is distinct from ordinary power control.  Only the root
        # Operations broker may present a just-issued, root-only authorization.
        if peer['domain'] != 'operations' or peer['uid'] != 0:
            sendpowerresponse(connection, False, error='recovery request identity is not authorised')
            return None
        if recoveryaction in DESTRUCTIVERECOVERYACTIONS:
            try:
                from broker import broker as authbroker
                recoveryorigin = currentbootidentity()
                if not authbroker.validate_recovery_authorization(
                        '/the one/master/master.txt', recoverytoken, recoveryaction):
                    raise ValueError
                recoverydigest = authbroker.recovery_authorization_digest(
                    '/the one/master/master.txt', recoverytoken, recoveryaction,
                    origin_boot_id=recoveryorigin)
            except Exception:
                sendpowerresponse(connection, False, error='recovery authorization is invalid')
                return None
        elif recoverytoken:
            sendpowerresponse(connection, False, error='unexpected recovery authorization')
            return None
        else:
            try:
                recoveryorigin = currentbootidentity()
            except Exception:
                sendpowerresponse(connection, False, error='recovery boot identity is unavailable')
                return None

    if SYSTEMSTATE != 'running':
        sendpowerresponse(connection, False, action=action, error='power transition already in progress')
        return None

    if recoveryaction:

        try:
            armrecoveryrequest(recoveryaction, recoverydigest, recoveryorigin)
        except (OSError, ValueError) as error:
            angelprint(f'I could not prepare recovery. {error}', flush=True)
            sendpowerresponse(connection, False, error=f'recovery request failed: {error}')
            return None

    SYSTEMSTATE = 'request accepted'
    sendpowerresponse(
        connection,
        True,
        action=action,
        recovery_action=recoveryaction,
    )

    if recoveryaction:
        angelprint(
            f'I accepted the {recoveryaction} recovery request from process '
            f'{peerpid if peerpid is not None else "unknown"}.',
            flush=True,
        )
    else:
        print(
            'I have accepted a request from process '
            f'{peerpid if peerpid is not None else "unknown"} to {action} the system.',
            flush=True
        )
    return action


def pollpowerrequest(timeout):

    server = POWERSERVER

    if server is None:
        time.sleep(max(0.0, float(timeout)))
        return None

    try:
        readable, _, _ = select.select([server], [], [], max(0.0, float(timeout)))
    except (OSError, ValueError):
        return None

    if not readable:
        return None

    try:
        connection, _ = server.accept()
    except BlockingIOError:
        return None

    try:
        return receivepowerrequest(connection)
    except Exception as error:

        try:
            sendpowerresponse(connection, False, error=f'power request failed: {error}')
        except Exception:
            pass

        print(f'I could not process the power request. {error}', flush=True)
        return None

    finally:

        try:
            connection.close()
        except Exception:
            pass


def processparent(pid):

    try:

        with open(os.path.join(PROCESSROOT, str(int(pid)), 'stat'), 'r', encoding='utf-8') as stream:
            stat = stream.read(4096)

        fields = stat.rsplit(')', 1)[1].strip().split()
        return int(fields[1])

    except (OSError, ValueError, IndexError):
        return None


def processalive(pid):

    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def processdescendants(roots):

    roots = {int(pid) for pid in roots if int(pid) > 0}
    descendants = set()
    parents = {}

    try:
        entries = os.listdir(PROCESSROOT)
    except OSError:
        return descendants

    for entry in entries:

        if not str(entry).isdigit():
            continue

        pid = int(entry)
        parent = processparent(pid)

        if parent is not None:
            parents[pid] = parent

    changed = True

    while changed:

        changed = False

        for pid, parent in parents.items():

            if pid in roots or pid in descendants:
                continue

            if parent in roots or parent in descendants:
                descendants.add(pid)
                changed = True

    return descendants


def taskpids(names):

    pids = set()

    for name in names:

        try:
            proc = TASKS.get(name, {}).get('proc')
            pid = int(proc.pid)
        except Exception:
            continue

        if pid > 1:
            pids.add(pid)

    return pids


def signalprocesses(pids, chosen):

    ownpid = os.getpid()

    for pid in sorted({int(value) for value in pids}, reverse=True):

        if pid <= 1 or pid == ownpid:
            continue

        try:
            os.kill(pid, chosen)
        except ProcessLookupError:
            pass
        except Exception as error:
            print(
                f'I could not send signal {chosen} to process {pid}. {error}',
                flush=True
            )


def waitprocesses(pids, timeout):

    remaining = {int(pid) for pid in pids if int(pid) > 1}
    deadline = time.monotonic() + max(0.0, float(timeout))

    while remaining and time.monotonic() < deadline:

        remaining = {pid for pid in remaining if processalive(pid)}
        sigchldhandler()

        if remaining:
            time.sleep(0.05)

    return {pid for pid in remaining if processalive(pid)}


def stopphase(label, names, timeout, additional=()):

    roots = taskpids(names)
    targets = roots | processdescendants(roots)
    targets.update(int(pid) for pid in additional if int(pid) > 1)

    for name in names:
        TASKS.pop(name, None)

    if not targets:
        print(f'I found no processes to stop during the {label} shutdown stage.', flush=True)
        return set()

    print(
        f'I am asking {len(targets)} processes to stop during the {label} '
        'shutdown stage.',
        flush=True
    )
    signalprocesses(targets, signal.SIGTERM)
    remaining = waitprocesses(targets, timeout)

    if remaining:
        print(
            f'I am forcing {len(remaining)} remaining processes to stop during '
            f'the {label} shutdown stage.',
            flush=True
        )
        signalprocesses(remaining, signal.SIGKILL)
        remaining = waitprocesses(remaining, FORCESTOPTIMEOUT)

    if remaining:
        print(
            f'These processes did not stop during the {label} shutdown stage. '
            f'{sorted(remaining)}',
            flush=True
        )

    return remaining


def stopstragglers(exclude=()):

    excluded = {os.getpid(), *[int(pid) for pid in exclude if pid]}
    targets = processdescendants({os.getpid()}) - excluded

    if not targets:
        return

    print(f'I am stopping {len(targets)} processes that remained after shutdown.', flush=True)
    signalprocesses(targets, signal.SIGTERM)
    remaining = waitprocesses(targets, 1.0)

    if remaining:
        signalprocesses(remaining, signal.SIGKILL)
        waitprocesses(remaining, FORCESTOPTIMEOUT)


def stopanimationprocess(proc):

    if proc is None:
        return

    try:

        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=1.0)

    except subprocess.TimeoutExpired:

        try:
            proc.kill()
            proc.wait(timeout=1.0)
        except Exception:
            pass

    except Exception:
        pass


def unmountpath(path):

    operation = libc.umount2
    operation.argtypes = (ctypes.c_char_p, ctypes.c_int)
    operation.restype = ctypes.c_int

    if operation(os.fsencode(path), 0) == 0:
        return True

    errornumber = ctypes.get_errno()
    print(
        f'I could not unmount {path}. {os.strerror(errornumber)}',
        flush=True
    )
    return False


def remountrootreadonly():

    MS_RDONLY = 1
    MS_REMOUNT = 32
    operation = libc.mount
    operation.argtypes = (
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_ulong,
        ctypes.c_void_p,
    )
    operation.restype = ctypes.c_int

    if operation(None, b'/', None, MS_RDONLY | MS_REMOUNT, None) == 0:
        return True

    errornumber = ctypes.get_errno()
    print(
        'I could not protect the root drive by remounting it read-only. '
        f'{os.strerror(errornumber)}',
        flush=True
    )
    return False


def kernelpower(action):

    RB_AUTOBOOT = 0x01234567
    RB_POWER_OFF = 0x4321FEDC
    command = RB_POWER_OFF if action == 'poweroff' else RB_AUTOBOOT
    operation = libc.reboot
    operation.argtypes = (ctypes.c_int,)
    operation.restype = ctypes.c_int

    if operation(command) != 0:
        errornumber = ctypes.get_errno()
        raise OSError(errornumber, f'kernel {action} failed: {os.strerror(errornumber)}')

    raise RuntimeError(f'kernel {action} returned unexpectedly')


def shutdownsequence(action, presentation=None):

    global SYSTEMSTATE

    action = str(action).strip().lower()
    closepowerserver()
    SYSTEMSTATE = 'animation visible'
    animation = presentation if presentation is not None else startpoweranimation(action)
    animationvisible = time.monotonic() if animation is not None else None

    if animation is None:
        print(
            f'I cannot show the {action} presentation, but I will continue the safe '
            'shutdown.',
            flush=True
        )

    try:
        os.sync()
    except Exception as error:
        print(f'I could not complete the first storage synchronization. {error}', flush=True)

    SYSTEMSTATE = 'stopping session'
    windowroots = taskpids(('window server',))
    windowchildren = processdescendants(windowroots)
    stopphase('session', ('expanse',), SESSIONSTOPTIMEOUT, additional=windowchildren)

    SYSTEMSTATE = 'stopping services'
    stopphase(
        'services',
        (
            'media',
            'exchange',
            'procedures',
            'operations server',
            'reign',
            'network',
            'virtualbox',
            'audio server',
            'input server',
        ),
        SERVICESTOPTIMEOUT
    )

    SYSTEMSTATE = 'stopping storage'
    stopphase('driver storage', ('driver server',), DRIVERSTOPTIMEOUT)

    windowpid = next(iter(taskpids(('window server',))), None)
    animationpid = animation.pid if animation is not None else None
    stopstragglers((windowpid, animationpid))

    if animationvisible is not None:

        remaining = 0.72 - (time.monotonic() - animationvisible)

        if remaining > 0:
            time.sleep(remaining)

    SYSTEMSTATE = 'stopping display'
    stopphase('display', ('window server',), SERVICESTOPTIMEOUT)
    stopanimationprocess(animation)

    SYSTEMSTATE = 'finalizing storage'
    print(f'I am finishing all storage work before I {action} the system.', flush=True)

    try:
        os.sync()
    except Exception as error:
        print(f'I could not complete the final storage synchronization. {error}', flush=True)

    try:
        armshutdownhealthgate(action)
        print(
            f'I armed the unmounted RootHealth shutdown gate for {action}.',
            flush=True,
        )
    except Exception as error:
        print(
            'I could not arm the shutdown health gate. I will restart into '
            f'normal boot admission instead of powering off unsafely. {error}',
            flush=True,
        )
        action = 'restart'

    unmountpath(TERMINFOBASE)
    unmountpath(RECOVERYBOOTMOUNT)
    unmountpath(EPHEMERALTIER)
    remountrootreadonly()
    print('I am handing control to the kernel for the unmounted RootHealth gate.', flush=True)

    SYSTEMSTATE = 'kernel handoff'

    try:
        kernelpower('restart')
    except BaseException as error:
        SYSTEMSTATE = 'kernel handoff failed'
        print(
            f'I could not hand control to the kernel to {action} the system. '
            f'{type(error).__name__} {error}',
            flush=True
        )

        while True:
            sigchldhandler()
            time.sleep(IDLERATE)


def preparefatalwindowserver():

    task = TASKS.get('window server', {})
    process = task.get('proc') if isinstance(task, dict) else None

    try:
        if process is not None and process.poll() is None and windowserverhello():
            return True
    except Exception:
        pass

    for backend in ('kms-framebuffer', 'framebuffer'):
        try:
            replacement = replacewindowserver(backend)
            deadline = time.monotonic() + 6.0

            while time.monotonic() < deadline:
                if replacement is None or replacement.poll() is not None:
                    break
                if windowserverhello():
                    return True
                time.sleep(0.05)
        except Exception as error:
            print(
                f'I could not prepare the {backend} fatal display. {error}',
                flush=True,
            )

    return False


def operationalfatal(component, reason, logpaths=(), recovery=()):

    global FATALACTIVE, SYSTEMPHASE

    failure = operationalfailureline(component, reason)

    if FATALACTIVE:
        try:
            os.sync()
        except Exception:
            pass
        try:
            kernelpower('restart')
        except BaseException:
            while True:
                sigchldhandler()
                time.sleep(IDLERATE)

    FATALACTIVE = True
    recordfatalerror(component, reason, logpaths=logpaths, recovery=recovery)
    SYSTEMPHASE = 'fatal'
    print(f'I encountered an operational fatal system error. {failure}', flush=True)

    presentation = None

    try:
        if preparefatalwindowserver():
            presentation = startfatalanimation(component, reason)

        if presentation is None:
            setdisplayconsolemode(False)
            mirrordisplayconsole(force=True)
            print('FATAL SYSTEM ERROR', flush=True)
            print(failure, flush=True)
            print('restarting...', flush=True)

        deadline = time.monotonic() + FATALDISPLAYTIME

        while time.monotonic() < deadline:
            if presentation is not None and presentation.poll() is not None:
                presentation = None
                break
            sigchldhandler()
            time.sleep(min(0.10, max(0.0, deadline - time.monotonic())))

        shutdownsequence('restart', presentation=presentation)

    except BaseException as error:
        print(
            f'I encountered an error while restarting after the fatal failure. '
            f'{type(error).__name__} {error}',
            flush=True,
        )
        try:
            os.sync()
        except Exception:
            pass
        try:
            kernelpower('restart')
        except BaseException as restart_error:
            setdisplayconsolemode(False)
            mirrordisplayconsole(force=True)
            print(f'restart failed - {type(restart_error).__name__.lower()} {restart_error}', flush=True)

            while True:
                sigchldhandler()
                time.sleep(IDLERATE)


def supervise():

    while True:

        # from birth operations
        for name, info in list(TASKS.items()):

            proc = info['proc']

            try:

                status = proc.poll()

                if (
                    status is None
                    and SYSTEMPHASE == 'operational'
                    and name in OPERATIONALCRITICALTASKS
                    and int(info.get('operational_failures', 0) or 0) > 0
                    and time.monotonic() - float(info.get('started_at', 0.0) or 0.0)
                    >= OPERATIONALHEALTHYRESET
                ):
                    TASKS[name] = dict(info)
                    TASKS[name]['operational_failures'] = 0
                    TASKS[name]['operational_failure_window'] = 0.0
                    info = TASKS[name]

                # resurrect dead operations
                if status is not None:

                    # run scripts
                    script = info['script']
                    operationalcritical = bool(
                        SYSTEMPHASE == 'operational'
                        and name in OPERATIONALCRITICALTASKS
                    )

                    if operationalcritical:
                        now = time.monotonic()
                        failurewindow = float(
                            info.get('operational_failure_window', 0.0) or 0.0
                        )
                        failures = int(
                            info.get('operational_failures', 0) or 0
                        )

                        if (
                            failurewindow <= 0.0
                            or now - failurewindow > OPERATIONALRESTARTWINDOW
                        ):
                            failurewindow = now
                            failures = 0

                        failures += 1
                        TASKS[name] = dict(info)
                        TASKS[name]['operational_failures'] = failures
                        TASKS[name]['operational_failure_window'] = failurewindow
                        info = TASKS[name]

                        if failures > OPERATIONALRESTARTLIMIT:
                            operationalfatal(
                                name,
                                f'exited with status {status} after '
                                f'{OPERATIONALRESTARTLIMIT} recovery attempts',
                                (LOGPATHS.get(name, ''),),
                                recovery=(
                                    f'attempts {OPERATIONALRESTARTLIMIT}',
                                    f'window {OPERATIONALRESTARTWINDOW:g} seconds',
                                ),
                            )

                    restartlimit = int(info.get('restart_limit', 0) or 0)
                    restartfailures = int(
                        info.get('restart_failures', 0) or 0
                    )

                    if restartlimit and restartfailures >= restartlimit:
                        continue

                    restartafter = float(info.get('restart_after', 0.0) or 0.0)

                    if time.monotonic() < restartafter:
                        continue

                    try:

                        role = info.get('role', 'behind')

                    except Exception:

                        role = 'behind'

                    logpath = softwarelogpath(script, LOGPATHS.get(name))
                    command = list(
                        info.get('command')
                        or [script]
                    )
                    environment = info.get('environment')

                    if (
                        operationalcritical
                        and name == 'window server'
                        and int(status) in (70, 71, 72)
                    ):
                        backend = str(info.get('graphics_backend', 'opengl'))

                        if backend == 'opengl':
                            backend = 'kms-framebuffer'
                        elif backend == 'kms-framebuffer':
                            backend = 'framebuffer'

                        environment = windowserverenvironment(backend)
                        TASKS[name]['graphics_backend'] = backend
                        TASKS[name]['environment'] = environment

                    if name == 'media':
                        clearmediadecodestate()

                    newproc = popenisolated(
                        command,
                        softwarepath=script,
                        logpath=logpath,
                        security_profile=SERVICESECURITYPROFILES.get(name),
                        preexec_fn=(dropdesktopidentity if name == 'expanse' else None),
                        start_new_session=True,
                        env=environment,
                    )

                    TASKS[name] = dict(info)
                    TASKS[name].update({
                        'script': script,
                        'proc': newproc,
                        'role': role,
                        'environment': environment,
                        'started_at': time.monotonic(),
                    })

                    if restartlimit:
                        TASKS[name]['restart_failures'] = restartfailures + 1
                        TASKS[name]['restart_after'] = (
                            time.monotonic()
                            + max(
                                0.1,
                                float(info.get('restart_delay', 1.0) or 1.0),
                            )
                        )

                    # register
                    register(name, newproc, role)

                    if operationalcritical and name == 'window server':
                        readydeadline = time.monotonic() + 6.0

                        while time.monotonic() < readydeadline:
                            if newproc.poll() is not None or windowserverhello():
                                break
                            time.sleep(0.05)

                        if newproc.poll() is None and windowserverhello():
                            expanse = TASKS.get('expanse', {}).get('proc')
                            terminateprocess(expanse)
                        else:
                            terminateprocess(newproc)

                    if name == 'media':
                        print(
                            f'I restarted the media decoder on process '
                            f'{newproc.pid}. This was attempt '
                            f'{TASKS[name]["restart_failures"]} of {restartlimit}.',
                            flush=True,
                        )

            except Exception as e:

                # supervise error on individual task
                print(f'I encountered an error while supervising {name}. {e}')

        # Reap any orphaned descendants synchronously, outside Popen's launch
        # path. Registered direct children are polled above.
        sigchldhandler()

        # OperationsServer may start or restart after its peers. A full
        # idempotent snapshot makes that ordering harmless and repairs any
        # missed registration without delaying supervision or boot.
        syncoperations()

        action = pollpowerrequest(SUPERVISERATE)

        if action is not None:
            shutdownsequence(action)


def operationssnapshot():

    operations = [{
        'pid': os.getpid(),
        'name': 'GODDESS',
        'script': os.path.abspath(__file__),
        'log': '-',
        'user': 'GODDESS',
        'mode': 'behind',
    }]

    for name, info in list(TASKS.items()):
        try:
            proc = info.get('proc')
            if proc is None or proc.poll() is not None:
                continue
            role = str(info.get('role', 'behind'))
            operations.append({
                'pid': int(proc.pid),
                'name': str(name),
                'script': str(info.get('script') or '-'),
                'log': str(LOGPATHS.get(name) or '-'),
                'user': 'GODDESS',
                'mode': role,
            })
        except Exception:
            continue

    return operations


def syncoperations(force=False):

    global OPERATIONSSYNCREQUIRED, LASTOPERATIONSSYNC

    now = time.monotonic()
    if (
        not force and not OPERATIONSSYNCREQUIRED and
        now - LASTOPERATIONSSYNC < OPERATIONSSYNCINTERVAL
    ):
        return True
    if not force and now - LASTOPERATIONSSYNC < OPERATIONSSYNCINTERVAL:
        return False

    LASTOPERATIONSSYNC = now
    client = None
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(0.25)
        client.connect(OPERATIONSSOCKET)
        request = {
            'op': 'BOOTSTRAP',
            'operations': operationssnapshot(),
        }
        client.sendall((json.dumps(request, separators=(',', ':')) + '\n').encode('utf-8'))
        response = b''
        while b'\n' not in response and len(response) <= 65536:
            chunk = client.recv(65536 - len(response) + 1)
            if not chunk:
                break
            response += chunk
        result = json.loads(response.split(b'\n', 1)[0].decode('utf-8'))
        if result.get('status') != 'ok':
            raise RuntimeError(result.get('message', 'bootstrap denied'))
        OPERATIONSSYNCREQUIRED = False
        return True
    except Exception:
        # Observational operations data must never become a boot barrier. The
        # supervisor retries the complete snapshot after the socket appears.
        OPERATIONSSYNCREQUIRED = True
        return False
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass


def register(name, proc, role=None):

    global OPERATIONSSYNCREQUIRED

    # Registration is a descriptive handoff. TASKS is the supervisor's source
    # of truth, so a missing Operations socket cannot impede process startup.
    OPERATIONSSYNCREQUIRED = True
    server = TASKS.get('operations server', {}).get('proc')
    if server is not None and server.poll() is None:
        syncoperations(force=True)


# core function
def main():

    global SYSTEMPHASE

    prunepreviousbootlogs()

    if os.getpid() == 1:
        print('I have completed the handoff to the first system process.', flush=True)

    initialiseterminalname()

    # create ephemeral tier
    createephemeral()
    discardlegacyfirmwaregraphicsrecovery()
    # Repair upgraded installs before graphics, input, audio and network open
    # their Settings-owned configuration.  Waiting until login is too late for
    # those boot-time consumers.
    normaliseservicesettings()
    normalisedesktopsettings()
    setuppowerserver()

    # OperationsServer starts later. The supervisor will hand it a full TASKS
    # snapshot when its socket exists; no operations recording path is a PID 1
    # boot prerequisite.

    # The boot animation has narrowly scoped access to the firmware
    # framebuffer. Start dots before driver discovery so quiet consumer boots
    # do not remain black while hardware support is being assembled.
    if setdisplayconsolemode(True):
        earlybootanimation = startbootanimation('early-dots')
    else:
        earlybootanimation = None
        recordgraphicsrecovery(
            'framebuffer',
            1,
            'early-display-console-ownership',
            'KD_GRAPHICS ownership could not be confirmed; refusing to '
            'start an unowned firmware-framebuffer writer',
            capturegpu=False,
        )
        mirrordisplayconsole(force=True)

    # Driver discovery and module insertion must settle before services that
    # open graphics, sound, or input devices are constructed.
    # DriverServer receives the early writer identity and retires it only when
    # it reaches the first native display binding. This lets the CPU dots keep
    # moving throughout policy verification and non-display discovery.
    if earlybootanimation is not None:
        os.environ['T1OS_EARLY_BOOT_ANIMATION_PID'] = str(
            earlybootanimation.pid
        )
    try:
        birth(EARLYSYSTEMOPS)
    finally:
        os.environ.pop('T1OS_EARLY_BOOT_ANIMATION_PID', None)

    try:
        driverproc = TASKS.get('driver server', {}).get('proc', None)
    except Exception:
        driverproc = None

    if DRIVERSERVERENABLED:

        driverstatus = waitdriverserver(driverproc)

        if driverstatus is None:
            print(
                'The driver server is unavailable, so I will continue with the '
                'built-in boot drivers and framebuffer fallback.',
                flush=True
            )

            try:

                with open(LOGPATHS['driver server'], 'r', encoding='utf-8', errors='replace') as handle:

                    for line in handle.readlines()[-120:]:

                        print(f'The driver server reported {line.rstrip()}', flush=True)

            except Exception as error:

                print(f'I could not read the driver server log. {error}', flush=True)

            driverstatus = {
                'state': 'unavailable',
                'loaded': [],
                'failed': {'driver-server': 'process was not ready'}
            }

        print(
            f'The driver server is {driverstatus.get("state")}. It loaded '
            f'{",".join(driverstatus.get("loaded", [])) or "no modules"}, granted '
            f'{",".join(driverstatus.get("device_grants", [])) or "no devices"}, '
            f'and reported {len(driverstatus.get("failed", {}))} failures.',
            flush=True
        )

        for failedname, faileddetail in sorted(driverstatus.get('failed', {}).items()):
            print(
                f'The {failedname} driver failed. {faileddetail}',
                flush=True
            )

    else:

        print(
            'The driver server is unavailable, so I could not start the device policy.',
            flush=True
        )

    # DriverServer normally performs this retirement immediately before the
    # first display-module bind. Also enforce it here for built-in drivers,
    # disabled DriverServer builds, and failed discovery. Process exit—not a
    # control acknowledgement—proves the framebuffer fd and mmap are gone.
    bootanimationframe = 0
    if earlybootanimation is not None:
        retirementattempt = 0
        while not stopbootanimation(earlybootanimation):
            retirementattempt += 1
            recordgraphicsrecovery(
                'framebuffer',
                retirementattempt,
                'early-framebuffer-owner-retirement',
                f'boot animation pid={earlybootanimation.pid} remains alive '
                f'after TERM/KILL; native graphics presentation is blocked',
                capturegpu=False,
            )
            time.sleep(GRAPHICSRECOVERYDELAY)

        details = animationdetails(
            BOOTANIMATIONSTATE,
            earlybootanimation.pid,
        )
        try:
            bootanimationframe = int(details.get('dot_frame', 0)) % 5
        except (TypeError, ValueError):
            bootanimationframe = 0
        earlybootanimation = None
        print(
            'I handed the moving firmware-framebuffer dots to the native '
            f'display owner at frame {bootanimationframe}.',
            flush=True,
        )

    # pre-start operations
    birth(PRESTARTOPS)

    if DEBUGSYSTEM:

        # Start the threaded log stream only after process construction. Running
        # Python callbacks or threads while Popen is in its fork/exec path can
        # deadlock PID 1 during early boot.
        startlogstream()

    try:
        windowtask = TASKS.get('window server', {})
        wsproc = windowtask.get('proc')
        graphicsbackend = str(
            windowtask.get('graphics_backend', 'opengl')
        ).strip().lower()
    except Exception:
        wsproc = None
        graphicsbackend = 'opengl'

    if graphicsbackend not in ('opengl', 'kms-framebuffer', 'framebuffer'):
        graphicsbackend = 'opengl'

    acceleratedattempts = 1 if graphicsbackend == 'opengl' else 0
    fallbackattempts = 1 if graphicsbackend in ('kms-framebuffer', 'framebuffer') else 0
    framebuffercyclefailures = 0
    framebufferrecoverycycles = 0
    diagnosticcomplete = False
    networkcomplete = False

    # Reaching a protocol socket is not the boot barrier. Keep replacing the
    # display owner until a current accelerated WindowServer proves a
    # lock-screen KMS presentation. CPU-rendered backends are diagnostics for
    # an explicitly requested recovery boot, never an automatic login path.
    while True:

        # CPU-rendered backends may be selected only by an explicit boot
        # option. Automatic recovery remains within the native GPU path and
        # cannot carry a normal boot into login on software rendering.
        if graphicsaccelerationrequired() and graphicsbackend != 'opengl':
            recordgraphicsrecovery(
                'opengl',
                max(1, acceleratedattempts),
                'gpu-required-retry',
                f'refusing automatic {graphicsbackend} userspace; restarting '
                'native accelerated graphics',
                capturegpu=False,
            )
            terminateprocess(wsproc)
            graphicsbackend = 'opengl'
            acceleratedattempts = max(1, acceleratedattempts)
            time.sleep(GRAPHICSRECOVERYDELAY)
            wsproc = replacewindowserver(graphicsbackend)
            continue

        if not waitwindowserver(wsproc):
            retrydelay = GRAPHICSRECOVERYDELAY
            readinessstatus = None if wsproc is None else wsproc.poll()
            readinessaction = (
                acceleratedfailureaction(wsproc)
                if graphicsbackend == 'opengl'
                else None
            )
            reason = (
                f'WindowServer was not ready '
                f'status={readinessstatus}'
            )
            attempt = (
                acceleratedattempts
                if graphicsbackend == 'opengl'
                else fallbackattempts
            )

            if (
                graphicsbackend == 'opengl'
                and readinessstatus is None
            ):
                try:
                    capturewindowserverhangbounded(
                        wsproc,
                        'windowserver-readiness',
                    )
                except Exception as error:
                    print(
                        f'I could not capture evidence from the unresponsive '
                        f'window server. {error}',
                        flush=True,
                    )

            recordgraphicsrecovery(
                graphicsbackend,
                attempt,
                'windowserver-readiness',
                reason,
                capturegpu=(
                    graphicsbackend == 'opengl'
                    or (
                        graphicsbackend == 'kms-framebuffer'
                        and readinessstatus == WINDOWSERVERGPUFAILUREEXIT
                    )
                ),
            )

            if graphicsbackend == 'opengl':
                if readinessaction == 'next-device':
                    terminateprocess(wsproc)
                    retrydelay = 0.0

                    if acceleratedattempts < ACCELERATEDLOGINATTEMPTS:
                        acceleratedattempts += 1
                        recordgraphicsrecovery(
                            'opengl',
                            acceleratedattempts,
                            'accelerated-device-candidate-retry',
                            f'{reason}; starting the next DRM device in a '
                            f'fresh provider-isolated WindowServer',
                            capturegpu=False,
                        )
                    else:
                        fallbackattempts = 1
                        graphicsbackend = 'kms-framebuffer'
                        recordgraphicsrecovery(
                            graphicsbackend,
                            fallbackattempts,
                            'same-boot-cpu-kms-login',
                            'all isolated accelerated DRM candidates failed '
                            'backend initialization; trying a fresh '
                            'CPU-rendered KMS owner',
                            capturegpu=False,
                        )

                elif readinessaction == 'cpu-kms':
                    fallbackattempts = 1
                    terminateprocess(wsproc)
                    graphicsbackend = 'kms-framebuffer'
                    retrydelay = 0.0
                    recordgraphicsrecovery(
                        'opengl',
                        acceleratedattempts,
                        'accelerated-userspace-failure',
                        f'{reason}; preserving the bound DRM/KMS device and '
                        f'replacing WindowServer with CPU-rendered KMS',
                        capturegpu=False,
                    )
                    print(
                        'The accelerated window server stopped without reporting '
                        f'a graphics processor failure and returned status '
                        f'{readinessstatus}. I will preserve the display connection '
                        'and switch directly to CPU display output.',
                        flush=True,
                    )
                else:
                    recovered = recovergraphicsdriver(
                        wsproc,
                        acceleratedattempts,
                        'WindowServer readiness failure',
                    )

                    if not recovered:
                        fallbackattempts = 1
                        requestfirmwaregraphicsrecovery(
                            'authorized GPU reset failed after accelerated '
                            'WindowServer readiness failure',
                            acceleratedattempts,
                        )
                        # If the reboot syscall itself returns, still test the
                        # native display engine with a fresh CPU KMS owner.
                        # A readable EFI BAR is not proof of active HDMI.
                        graphicsbackend = 'kms-framebuffer'
                        recordgraphicsrecovery(
                            graphicsbackend,
                            fallbackattempts,
                            'same-boot-cpu-kms-login',
                            'GPU reset and firmware recovery reboot both failed; '
                            'trying a fresh software KMS owner',
                            capturegpu=False,
                        )
                    elif acceleratedattempts < ACCELERATEDLOGINATTEMPTS:
                        acceleratedattempts += 1
                    else:
                        fallbackattempts = 1
                        requestfirmwaregraphicsrecovery(
                            'accelerated WindowServer readiness failed after '
                            'all driver reinitialization attempts',
                            acceleratedattempts,
                        )
                        # Reaching this line means the kernel reboot request
                        # itself failed. Keep trying native KMS with CPU
                        # rendering; stale firmware memory cannot prove scanout.
                        graphicsbackend = 'kms-framebuffer'
                        recordgraphicsrecovery(
                            graphicsbackend,
                            fallbackattempts,
                            'same-boot-cpu-kms-login',
                            'firmware recovery reboot returned unexpectedly; '
                            'trying a fresh software KMS owner',
                            capturegpu=False,
                        )

            elif graphicsbackend == 'kms-framebuffer':
                kmsdevicelost = (
                    readinessstatus == WINDOWSERVERGPUFAILUREEXIT
                )
                kmsrecovered = None

                if kmsdevicelost:
                    kmsrecovered = recovergraphicsdriver(
                        wsproc,
                        fallbackattempts,
                        'CPU-KMS WindowServer readiness device loss',
                        backend='kms-framebuffer',
                    )

                if kmsdevicelost and not kmsrecovered:
                    requestfirmwaregraphicsrecovery(
                        'authorized reset failed after CPU-KMS readiness '
                        'reported DRM device loss',
                        fallbackattempts,
                    )
                    fallbackattempts = 1
                    graphicsbackend = 'framebuffer'
                    framebuffercyclefailures = 0
                    recordgraphicsrecovery(
                        graphicsbackend,
                        fallbackattempts,
                        'legacy-framebuffer-login',
                        'CPU-KMS reported device loss and its exact selected '
                        'DRM driver could not be reset; testing an independent '
                        'display tier',
                        capturegpu=False,
                    )
                elif (
                    fallbackattempts >= KMSRECOVERYATTEMPTSPERCYCLE
                ):
                    requestfirmwaregraphicsrecovery(
                        'software KMS WindowServer did not become ready '
                        f'status={readinessstatus}',
                        fallbackattempts,
                    )
                    terminateprocess(wsproc)
                    fallbackattempts = 1
                    graphicsbackend = 'framebuffer'
                    framebuffercyclefailures = 0
                    recordgraphicsrecovery(
                        graphicsbackend,
                        fallbackattempts,
                        'legacy-framebuffer-login',
                        'software KMS could not initialize after fresh-owner '
                        'retries; testing the independent framebuffer and tty '
                        'display tier before returning to native KMS',
                        capturegpu=False,
                    )
                else:
                    if not kmsdevicelost:
                        terminateprocess(wsproc)

                    fallbackattempts += 1
                    retrydelay = 0.0
                    recordgraphicsrecovery(
                        graphicsbackend,
                        fallbackattempts,
                        (
                            'software-kms-device-reset-retry'
                            if kmsdevicelost
                            else 'software-kms-readiness-retry'
                        ),
                        f'{reason}; '
                        f'{"the selected DRM driver was reset; " if kmsdevicelost else ""}'
                        f'starting a fresh CPU-rendered display owner',
                        capturegpu=False,
                    )

            else:
                framebuffercyclefailures += 1

                if (
                    framebuffercyclefailures
                    >= FRAMEBUFFERRECOVERYATTEMPTSPERCYCLE
                ):
                    framebufferrecoverycycles += 1

                    visibleframebufferrecoveryretry(
                        wsproc,
                        fallbackattempts,
                        framebufferrecoverycycles,
                        'windowserver-readiness',
                        reason,
                        animationproc=earlybootanimation,
                    )
                    earlybootanimation = None
                    framebuffercyclefailures = 0
                    retrydelay = 0.0

                    if drmscanoutnodeavailable():
                        graphicsbackend = 'kms-framebuffer'
                        fallbackattempts = 1
                        recordgraphicsrecovery(
                            graphicsbackend,
                            fallbackattempts,
                            'software-kms-cycle-resume',
                            'the independent framebuffer tier did not prove a '
                            'visible login; returning to a fresh native KMS '
                            'owner and continuing GPU scanout recovery',
                            capturegpu=False,
                        )
                    else:
                        fallbackattempts += 1
                else:
                    fallbackattempts += 1

            if retrydelay > 0.0:
                time.sleep(retrydelay)

            wsproc = replacewindowserver(graphicsbackend)
            continue

        print(
            f'The window server is ready on process {wsproc.pid} using the '
            f'{graphicsbackend} backend.',
            flush=True,
        )

        capability = (
            graphicscapabilityreceipt(wsproc)
            if graphicsbackend == 'opengl'
            else None
        )

        if (
            capability is not None
            and capability.get('state') == 'acceleration-unavailable'
        ):
            fallbackattempts = 1
            recordgraphicsrecovery(
                graphicsbackend,
                acceleratedattempts,
                'acceleration-unavailable',
                f'renderer={capability.get("renderer", "unknown")} '
                f'driver={capability.get("drm_driver", "unknown")}; '
                f'replacing owner with CPU-rendered KMS before animation',
                capturegpu=False,
            )
            print(
                f'Hardware acceleration is unavailable through the '
                f'{capability["renderer"]} renderer on process {wsproc.pid}. '
                'I am switching to CPU display output.',
                flush=True,
            )
            graphicsbackend = 'kms-framebuffer'
            wsproc = replacewindowserver(graphicsbackend)
            continue

        # A KMS frame is not physically stable while an older KD_TEXT ioctl
        # can still finish and restore fbcon over it.  Conversely, direct
        # fbdev presentation is valid only while PID 1 owns KD_TEXT.  Treat
        # console ownership as a hard presentation barrier, not a best-effort
        # side effect: no animation or lock screen may be certified until the
        # required transition completed and no opposite-mode helper remains.
        graphicsconsole = graphicsbackend != 'framebuffer'

        if not setdisplayconsolemode(graphicsconsole):
            requiredmode = 'KD_GRAPHICS' if graphicsconsole else 'KD_TEXT'
            attempt = (
                acceleratedattempts
                if graphicsbackend == 'opengl'
                else fallbackattempts
            )
            recordgraphicsrecovery(
                graphicsbackend,
                attempt,
                'display-console-ownership',
                f'{requiredmode} could not be confirmed before managed '
                'presentation; refusing to start or certify a frame',
                capturegpu=False,
            )

            if earlybootanimation is not None:
                stopbootanimation(earlybootanimation)
                earlybootanimation = None

            if DISPLAYCONSOLEFD is None:
                terminateprocess(wsproc)
                recordgraphicsrecovery(
                    graphicsbackend,
                    attempt,
                    'display-console-contract',
                    'init did not preserve T1OS_DISPLAY_CONSOLE_FD; refusing '
                    'display-driver reset and entering diagnostic hold',
                    capturegpu=False,
                )
                fatalhold(
                    'init hand-off contract failed: inherited tty0 descriptor '
                    'is unavailable',
                    (LOGPATHS['window server'],),
                )

            if graphicsbackend in ('opengl', 'kms-framebuffer'):
                recovered = recovergraphicsdriver(
                    wsproc,
                    attempt,
                    f'{requiredmode} transition blocked before presentation',
                    backend=graphicsbackend,
                )
                helperretired = waitdisplayconsolemodehelper()
                modeconfirmed = bool(
                    helperretired
                    and setdisplayconsolemode(True)
                )
                recordgraphicsrecovery(
                    graphicsbackend,
                    attempt,
                    'display-console-recovery',
                    f'driver_reset={bool(recovered)} '
                    f'blocked_helper_retired={bool(helperretired)} '
                    f'kd_graphics_confirmed={bool(modeconfirmed)}',
                    capturegpu=False,
                )

                if not recovered or not modeconfirmed:
                    requestfirmwaregraphicsrecovery(
                        f'{requiredmode} remained unavailable after exact '
                        'display-driver reset',
                        attempt,
                    )

                if graphicsbackend == 'opengl':
                    if (
                        recovered
                        and modeconfirmed
                        and acceleratedattempts
                        < ACCELERATEDLOGINATTEMPTS
                    ):
                        acceleratedattempts += 1
                    else:
                        fallbackattempts = 1
                        graphicsbackend = 'kms-framebuffer'
                        recordgraphicsrecovery(
                            graphicsbackend,
                            fallbackattempts,
                            'same-boot-cpu-kms-login',
                            'accelerated display-console ownership could not '
                            'be made stable; trying a fresh CPU-rendered KMS '
                            'owner without certifying the failed frame',
                            capturegpu=False,
                        )
                elif (
                    recovered
                    and modeconfirmed
                    and fallbackattempts
                    < KMSRECOVERYATTEMPTSPERCYCLE
                ):
                    fallbackattempts += 1
                else:
                    fallbackattempts = 1
                    graphicsbackend = 'framebuffer'
                    framebuffercyclefailures = 0
                    recordgraphicsrecovery(
                        graphicsbackend,
                        fallbackattempts,
                        'legacy-framebuffer-login',
                        'CPU-KMS display-console ownership could not be made '
                        'stable; testing the independently owned KD_TEXT '
                        'framebuffer tier',
                        capturegpu=False,
                    )

            else:
                terminateprocess(wsproc)
                helperretired = waitdisplayconsolemodehelper()
                modeconfirmed = bool(
                    helperretired
                    and setdisplayconsolemode(False)
                )
                framebuffercyclefailures += 1
                recordgraphicsrecovery(
                    graphicsbackend,
                    fallbackattempts,
                    'display-console-recovery',
                    f'blocked_helper_retired={bool(helperretired)} '
                    f'kd_text_confirmed={bool(modeconfirmed)}',
                    capturegpu=False,
                )

                if (
                    not modeconfirmed
                    or framebuffercyclefailures
                    >= FRAMEBUFFERRECOVERYATTEMPTSPERCYCLE
                ):
                    framebufferrecoverycycles += 1
                    visibleframebufferrecoveryretry(
                        None,
                        fallbackattempts,
                        framebufferrecoverycycles,
                        'display-console-ownership',
                        RuntimeError(
                            'KD_TEXT ownership could not be confirmed'
                        ),
                    )
                    framebuffercyclefailures = 0

                    if drmscanoutnodeavailable():
                        graphicsbackend = 'kms-framebuffer'
                        fallbackattempts = 1
                    else:
                        fallbackattempts += 1
                else:
                    fallbackattempts += 1

            wsproc = replacewindowserver(graphicsbackend)
            continue

        # A failed animation is decorative failure, not GPU failure. If the
        # WindowServer is still responsive, remove the failed client and drive
        # the lock screen directly on the same GPU.
        os.environ['T1OS_BOOT_DOT_FRAME'] = str(bootanimationframe)
        try:
            bootanimation = startbootanimation('dots')
        finally:
            os.environ.pop('T1OS_BOOT_DOT_FRAME', None)

        if graphicsbackend == 'opengl':
            bootoutcome = waitacceleratedbootpresentation(
                wsproc,
                bootanimation,
            )

            if bootoutcome == 'acceleration-unavailable':
                stopbootanimation(bootanimation)
                receipt = accelerationunavailablereceipt(
                    wsproc,
                    'boot animation',
                ) or {}
                fallbackattempts = 1
                recordgraphicsrecovery(
                    graphicsbackend,
                    acceleratedattempts,
                    'acceleration-unavailable',
                    f'renderer={receipt.get("renderer", "unknown")} '
                    f'driver={receipt.get("drm_driver", "unknown")}; '
                    f'replacing owner with CPU-rendered KMS',
                    capturegpu=False,
                )
                graphicsbackend = 'kms-framebuffer'
                wsproc = replacewindowserver(graphicsbackend)
                continue

            if bootoutcome == 'gpu-failed':
                stopbootanimation(bootanimation)
                failureaction = acceleratedfailureaction(wsproc)
                failurestatus = None if wsproc is None else wsproc.poll()

                if failurestatus is None:
                    capturewindowserverhangbounded(
                        wsproc,
                        'boot-animation-presentation',
                    )

                recordgraphicsrecovery(
                    graphicsbackend,
                    acceleratedattempts,
                    'boot-animation-presentation',
                    f'WindowServer died or stopped responding '
                    f'status={failurestatus} action={failureaction}',
                    capturegpu=(failureaction == 'gpu-reset'),
                )

                if failureaction == 'next-device':
                    terminateprocess(wsproc)

                    if acceleratedattempts < ACCELERATEDLOGINATTEMPTS:
                        acceleratedattempts += 1
                        recordgraphicsrecovery(
                            'opengl',
                            acceleratedattempts,
                            'accelerated-device-candidate-retry',
                            'boot presentation owner reported backend '
                            'initialization failure; starting the next DRM '
                            'device in a fresh provider-isolated WindowServer',
                            capturegpu=False,
                        )
                    else:
                        fallbackattempts = 1
                        graphicsbackend = 'kms-framebuffer'
                        recordgraphicsrecovery(
                            graphicsbackend,
                            fallbackattempts,
                            'same-boot-cpu-kms-login',
                            'all isolated accelerated DRM candidates failed; '
                            'trying a fresh CPU-rendered KMS owner',
                            capturegpu=False,
                        )

                elif failureaction == 'cpu-kms':
                    fallbackattempts = 1
                    terminateprocess(wsproc)
                    graphicsbackend = 'kms-framebuffer'
                    recordgraphicsrecovery(
                        'opengl',
                        acceleratedattempts,
                        'accelerated-userspace-failure',
                        f'boot presentation owner exited status={failurestatus}; '
                        f'preserving HDMI/KMS for CPU-rendered lock screen',
                        capturegpu=False,
                    )
                else:
                    recovered = recovergraphicsdriver(
                        wsproc,
                        acceleratedattempts,
                        'accelerated boot presentation failure',
                    )

                    if not recovered:
                        fallbackattempts = 1
                        requestfirmwaregraphicsrecovery(
                            'authorized GPU reset failed after accelerated boot '
                            'presentation failure',
                            acceleratedattempts,
                        )
                        graphicsbackend = 'kms-framebuffer'
                        recordgraphicsrecovery(
                            graphicsbackend,
                            fallbackattempts,
                            'same-boot-cpu-kms-login',
                            'GPU reset and firmware recovery reboot both failed; '
                            'trying a fresh software KMS owner',
                            capturegpu=False,
                        )
                    elif acceleratedattempts < ACCELERATEDLOGINATTEMPTS:
                        acceleratedattempts += 1
                    else:
                        fallbackattempts = 1
                        requestfirmwaregraphicsrecovery(
                            'accelerated boot presentation failed after all '
                            'driver reinitialization attempts',
                            acceleratedattempts,
                        )
                        graphicsbackend = 'kms-framebuffer'
                        recordgraphicsrecovery(
                            graphicsbackend,
                            fallbackattempts,
                            'same-boot-cpu-kms-login',
                            'firmware recovery reboot returned unexpectedly; '
                            'trying a fresh software KMS owner',
                            capturegpu=False,
                        )

                time.sleep(GRAPHICSRECOVERYDELAY)
                wsproc = replacewindowserver(graphicsbackend)
                continue

            if bootoutcome == 'animation-failed':
                stopbootanimation(bootanimation)
                bootanimation = None
                recordgraphicsrecovery(
                    graphicsbackend,
                    acceleratedattempts,
                    'boot-animation-client',
                    'animation failed while GPU WindowServer remained healthy; '
                    'continuing directly to lock screen',
                )

        # Stop the firmware-framebuffer writer before the lock screen starts.
        # The GPU startup gate or managed dots frame is already retained on
        # screen, so this does not create a black interval.
        if earlybootanimation is not None:
            stopbootanimation(earlybootanimation)
            earlybootanimation = None

        if not diagnosticcomplete:
            diagnosticcomplete = True

            if kernelcommandlineoption('t1os.chromium-diagnostic=1'):

                print('I have started the Chromium boot diagnostic.', flush=True)
                diagnosticpath = (
                    '/the one/logs/chromium-boot-diagnostic.log'
                )
                diagnostic = popenisolated(
                    [CHROMIUMSCRIPT, 'engine-diagnostic'],
                    softwarepath=CHROMIUMSCRIPT,
                    logpath=diagnosticpath,
                    security_profile='chromium',
                    preexec_fn=dropchromiumidentity,
                )
                diagnostic.wait()
                try:
                    with open(diagnosticpath, 'rb') as diagnosticlog:
                        os.fsync(diagnosticlog.fileno())
                except FileNotFoundError:
                    pass
                print(
                    f'The Chromium boot diagnostic returned status '
                    f'{diagnostic.returncode}.',
                    flush=True
                )
                os.sync()

        if not networkcomplete:
            networkcomplete = True

            try:
                networkproc = TASKS.get('network', {}).get('proc', None)
            except Exception:
                networkproc = None

            waitnetworkstartup(networkproc)

        # Native web decoding is an optional, independently supervised consumer
        # of the exact GPU generation which has just proved accelerated
        # presentation. It must never race DriverServer or WindowServer setup.
        # Any failure leaves Chromium's NVIDIA software-decode quarantine in
        # force and therefore cannot prevent login.
        configuremediadecodeservice(wsproc, graphicsbackend)

        # Startup and Lock Screen must inherit the environment of the exact
        # WindowServer they are proving. Calling windowserverenvironment() here
        # would allocate and consume the next accelerated DRM candidate without
        # launching it, causing two-GPU retries to skip every other adapter.
        try:
            startupenvironment = dict(
                TASKS.get('window server', {}).get('environment') or {}
            )
        except Exception:
            startupenvironment = {}

        if not startupenvironment:
            startupenvironment = os.environ.copy()
            startupenvironment[
                'T1OS_WINDOWSERVER_GRAPHICS_BACKEND'
            ] = graphicsbackend

            if graphicsbackend == 'opengl':
                startupenvironment.pop('T1OS_GRAPHICS', None)
            else:
                startupenvironment['T1OS_GRAPHICS'] = 'cpu'

        startupenvironment.pop('T1OS_BOOT_ANIMATION_PID', None)

        if bootanimation is not None:
            startupenvironment['T1OS_BOOT_ANIMATION_PID'] = str(bootanimation.pid)

        try:
            print(
                f'I have started the first-run or login experience using the '
                f'{graphicsbackend} graphics backend.',
                flush=True,
            )
            runstartup(startupenvironment, wsproc)

            if (
                graphicsbackend == 'framebuffer'
                and firmwaregraphicsrecoveryrequested()
            ):
                # Keep the recovery boot armed through the lock screen. Only
                # a completed local login proves the user could see and
                # interact with the independent firmware path.
                clearfirmwaregraphicsrecovery()

            break

        except FileNotFoundError:
            stopbootanimation(bootanimation)
            fatalhold(
                'startup software was not found',
                (LOGPATHS['window server'],),
            )

        except LoginClientBufferFailure as error:
            stopbootanimation(bootanimation)
            terminateprocess(wsproc)
            recordgraphicsrecovery(
                graphicsbackend,
                1,
                'lockscreen-userspace-buffer-failure',
                f'{type(error).__name__}: {error}',
                capturegpu=False,
            )
            fatalhold(
                'lock-screen window buffer access failed',
                (LOCKSCREENLOG, STARTUPLOG, LOGPATHS['window server']),
            )

        except LoginPresentationFailure as error:
            stopbootanimation(bootanimation)
            retrydelay = GRAPHICSRECOVERYDELAY
            attempt = (
                acceleratedattempts
                if graphicsbackend == 'opengl'
                else fallbackattempts
            )

            if (
                graphicsbackend == 'opengl'
                and wsproc is not None
                and wsproc.poll() is None
            ):
                capturewindowserverhangbounded(
                    wsproc,
                    'lockscreen-presentation',
                )

            recordgraphicsrecovery(
                graphicsbackend,
                attempt,
                'lockscreen-presentation',
                f'{type(error).__name__}: {error}',
                capturegpu=(
                    graphicsbackend == 'opengl'
                    or (
                        graphicsbackend == 'kms-framebuffer'
                        and wsproc is not None
                        and wsproc.poll() == WINDOWSERVERGPUFAILUREEXIT
                    )
                ),
            )

            unavailable = (
                accelerationunavailablereceipt(wsproc, 'lockscreen')
                if graphicsbackend == 'opengl'
                else None
            )

            if unavailable is not None:
                fallbackattempts = 1
                recordgraphicsrecovery(
                    graphicsbackend,
                    acceleratedattempts,
                    'acceleration-unavailable',
                    f'renderer={unavailable.get("renderer", "unknown")} '
                    f'driver={unavailable.get("drm_driver", "unknown")}; '
                    f'lock screen will use CPU-rendered KMS',
                    capturegpu=False,
                )
                graphicsbackend = 'kms-framebuffer'

            elif graphicsbackend == 'opengl':
                failureaction = acceleratedfailureaction(
                    wsproc,
                    acceptresponsive=True,
                )
                failurestatus = None if wsproc is None else wsproc.poll()

                if failureaction == 'next-device':
                    terminateprocess(wsproc)
                    retrydelay = 0.0

                    if acceleratedattempts < ACCELERATEDLOGINATTEMPTS:
                        acceleratedattempts += 1
                        recordgraphicsrecovery(
                            'opengl',
                            acceleratedattempts,
                            'accelerated-device-candidate-retry',
                            'lock-screen presentation owner reported backend '
                            'initialization failure; starting the next DRM '
                            'device in a fresh provider-isolated WindowServer',
                            capturegpu=False,
                        )
                    else:
                        fallbackattempts = 1
                        graphicsbackend = 'kms-framebuffer'
                        recordgraphicsrecovery(
                            graphicsbackend,
                            fallbackattempts,
                            'same-boot-cpu-kms-login',
                            'all isolated accelerated DRM candidates failed; '
                            'trying a fresh CPU-rendered KMS owner',
                            capturegpu=False,
                        )

                elif failureaction == 'cpu-kms':
                    fallbackattempts = 1
                    terminateprocess(wsproc)
                    graphicsbackend = 'kms-framebuffer'
                    retrydelay = 0.0
                    recordgraphicsrecovery(
                        'opengl',
                        acceleratedattempts,
                        'accelerated-userspace-failure',
                        f'lock-screen presentation failed with responsive or '
                        f'non-GPU-failure WindowServer status={failurestatus}; '
                        f'preserving HDMI/KMS for CPU-rendered lock screen',
                        capturegpu=False,
                    )
                else:
                    recovered = recovergraphicsdriver(
                        wsproc,
                        acceleratedattempts,
                        'accelerated lock-screen presentation failure',
                    )

                    if not recovered:
                        fallbackattempts = 1
                        requestfirmwaregraphicsrecovery(
                            'authorized GPU reset failed after accelerated '
                            'lock-screen presentation failure',
                            acceleratedattempts,
                        )
                        graphicsbackend = 'kms-framebuffer'
                        recordgraphicsrecovery(
                            graphicsbackend,
                            fallbackattempts,
                            'same-boot-cpu-kms-login',
                            'GPU reset and firmware recovery reboot both failed; '
                            'trying a fresh software KMS owner',
                            capturegpu=False,
                        )
                    elif acceleratedattempts < ACCELERATEDLOGINATTEMPTS:
                        acceleratedattempts += 1
                    else:
                        fallbackattempts = 1
                        requestfirmwaregraphicsrecovery(
                            'accelerated lock-screen presentation failed after '
                            'all driver reinitialization attempts',
                            acceleratedattempts,
                        )
                        graphicsbackend = 'kms-framebuffer'
                        recordgraphicsrecovery(
                            graphicsbackend,
                            fallbackattempts,
                            'same-boot-cpu-kms-login',
                            'firmware recovery reboot returned unexpectedly; '
                            'trying a fresh software KMS owner',
                            capturegpu=False,
                        )

            elif graphicsbackend == 'kms-framebuffer':
                kmsstatus = None if wsproc is None else wsproc.poll()
                kmsdevicelost = (
                    kmsstatus == WINDOWSERVERGPUFAILUREEXIT
                )
                kmsrecovered = None

                if kmsdevicelost:
                    kmsrecovered = recovergraphicsdriver(
                        wsproc,
                        fallbackattempts,
                        'CPU-KMS lock-screen presentation device loss',
                        backend='kms-framebuffer',
                    )
                else:
                    terminateprocess(wsproc)

                if kmsdevicelost and not kmsrecovered:
                    requestfirmwaregraphicsrecovery(
                        'authorized reset failed after CPU-KMS lock-screen '
                        'presentation reported DRM device loss',
                        fallbackattempts,
                    )
                    fallbackattempts = 1
                    graphicsbackend = 'framebuffer'
                    framebuffercyclefailures = 0
                    recordgraphicsrecovery(
                        graphicsbackend,
                        fallbackattempts,
                        'legacy-framebuffer-login',
                        'CPU-KMS lock-screen presentation lost its exact DRM '
                        'device and reset failed; testing an independent '
                        'display tier',
                        capturegpu=False,
                    )
                elif (
                    fallbackattempts
                    >= KMSRECOVERYATTEMPTSPERCYCLE
                ):
                    requestfirmwaregraphicsrecovery(
                        'software KMS lock screen could not be physically '
                        'verified after fresh-owner retries',
                        fallbackattempts,
                    )
                    fallbackattempts = 1
                    graphicsbackend = 'framebuffer'
                    framebuffercyclefailures = 0
                    recordgraphicsrecovery(
                        graphicsbackend,
                        fallbackattempts,
                        'legacy-framebuffer-login',
                        'software KMS could not prove the lock screen after '
                        'fresh-owner retries; testing the independent '
                        'framebuffer and tty display tier before returning to '
                        'native KMS',
                        capturegpu=False,
                    )
                else:
                    fallbackattempts += 1
                    recordgraphicsrecovery(
                        graphicsbackend,
                        fallbackattempts,
                        (
                            'software-kms-device-reset-retry'
                            if kmsdevicelost
                            else 'software-kms-presentation-retry'
                        ),
                        (
                            'the selected DRM driver was reset after device '
                            'loss; starting a fresh CPU-KMS owner'
                            if kmsdevicelost
                            else 'starting a fresh CPU-KMS owner after '
                            'unverified lock-screen presentation'
                        ),
                        capturegpu=False,
                    )

                retrydelay = 0.0

            else:
                # Keep constructing a local lock screen and expose a durable
                # tty0 diagnostic after each bounded framebuffer group. If a
                # native DRM card still exists, return to a fresh KMS owner
                # after the visible diagnostic instead of abandoning GPU
                # scanout recovery.
                framebuffercyclefailures += 1

                if (
                    framebuffercyclefailures
                    >= FRAMEBUFFERRECOVERYATTEMPTSPERCYCLE
                ):
                    framebufferrecoverycycles += 1
                    visibleframebufferrecoveryretry(
                        wsproc,
                        fallbackattempts,
                        framebufferrecoverycycles,
                        'lockscreen-presentation',
                        error,
                    )
                    framebuffercyclefailures = 0
                    retrydelay = 0.0

                    if drmscanoutnodeavailable():
                        graphicsbackend = 'kms-framebuffer'
                        fallbackattempts = 1
                        recordgraphicsrecovery(
                            graphicsbackend,
                            fallbackattempts,
                            'software-kms-cycle-resume',
                            'the independent framebuffer tier did not prove a '
                            'visible lock screen; returning to a fresh native '
                            'KMS owner and continuing GPU scanout recovery',
                            capturegpu=False,
                        )
                    else:
                        fallbackattempts += 1
                else:
                    fallbackattempts += 1

            if retrydelay > 0.0:
                time.sleep(retrydelay)

            wsproc = replacewindowserver(graphicsbackend)
            continue

        except subprocess.CalledProcessError as error:
            stopbootanimation(bootanimation)
            fatalhold(
                f'non-graphics startup operation failed with exit code '
                f'{error.returncode}',
                (STARTUPLOG, LOCKSCREENLOG, LOGPATHS['window server']),
            )

        except Exception as error:
            stopbootanimation(bootanimation)
            fatalhold(
                f'non-graphics startup operation failed: '
                f'{type(error).__name__}: {error}',
                (STARTUPLOG, LOCKSCREENLOG, LOGPATHS['window server']),
            )

        finally:
            stopbootanimation(bootanimation)

    # master must exist or we abort
    if not os.path.isfile('/the one/master/master.txt'):

        print('I cannot continue because the master file is missing.')

        fatalhold(
            'startup finished without a master file',
            (STARTUPLOG, LOCKSCREENLOG, LOGPATHS['window server'])
        )

    # Ordinary desktop processes never read master.txt.  Publish only the
    # canonical username through a root-owned, group-readable snapshot.
    try:
        normaliseexistingdesktopownership()
        publishsessionidentity()
    except Exception as error:
        fatalhold(
            f'could not publish the desktop session identity: {error}',
            (STARTUPLOG, LOCKSCREENLOG, LOGPATHS['window server']),
        )

    # post-start operations
    birth(POSTSTARTOPS)

    expanseprocess = TASKS.get('expanse', {}).get('proc')

    if expanseprocess is None or expanseprocess.poll() is not None:
        fatalhold(
            'the desktop shell did not start',
            (LOGPATHS['expanse'], LOGPATHS['window server']),
        )

    SYSTEMPHASE = 'operational'

    print('I have finished starting the desktop.', flush=True)

    supervise()



# execute main
if __name__ == '__main__':
    diagnosticstatus = None

    if len(sys.argv) >= 2 and sys.argv[1] == '--display-console-mode-helper':
        try:
            if len(sys.argv) != 5:
                raise ValueError('invalid display helper arguments')
            fcntl.ioctl(int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]))
            diagnosticstatus = 0
        except BaseException:
            diagnosticstatus = 1

    elif len(sys.argv) >= 2 and sys.argv[1] == '--graphics-hang-capture':
        try:
            diagnosticstatus = 0 if capturewindowserverhangpid(
                int(sys.argv[2]),
                str(sys.argv[3]),
            ) else 1
        except BaseException:
            diagnosticstatus = 1

    elif (
        len(sys.argv) >= 2
        and sys.argv[1] == '--graphics-kernel-capture'
    ):
        try:
            capturegpufailureevidence(json.loads(sys.argv[2]))
            diagnosticstatus = 0
        except BaseException:
            diagnosticstatus = 1

    if diagnosticstatus is not None:
        raise SystemExit(diagnosticstatus)

    try:

        main()

    except BaseException as error:

        if SYSTEMPHASE == 'operational':
            operationalfatal(
                'goddess',
                f'unhandled {type(error).__name__} {error}',
                (
                    LOGPATHS['driver server'],
                    LOGPATHS['window server'],
                    LOCKSCREENLOG,
                    STARTUPLOG,
                ),
            )
        else:
            fatalhold(
                f'unhandled PID 1 exception: {type(error).__name__}: {error}',
                (
                    LOGPATHS['driver server'],
                    LOGPATHS['window server'],
                    LOCKSCREENLOG,
                    STARTUPLOG
                )
            )

    if os.getpid() == 1:

        fatalhold('PID 1 main loop returned unexpectedly')
