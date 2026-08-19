#!"/the one/software/python/bin/python" -B

"""T1OS system Python service, package manager, client, and command dispatcher.

Importable package payloads are installed into the interpreter's real
``site-packages`` directory.  ELF dependencies bundled by wheels are moved to
the T1OS Python catalogue and every native consumer is relocated before a
journalled commit.  Upstream pip is used only as a locked resolver and wheel
unpacker; it never writes the live interpreter.
"""

from __future__ import annotations

import base64
import array
import csv
import hashlib
import importlib.metadata
import importlib.machinery
import io
import json
import os
import re
import shutil
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

BUILDROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BUILDROOT not in sys.path:
    sys.path.insert(0, BUILDROOT)

PROTOCOL = 1
PROTOCOL_READY = b'R'
STATE_FORMAT = 2
SERVICE = 'T1OS system Python'
DEFAULT_SOCKET = '/.ephemeral/python/manager.sock'
DEFAULT_SYSTEM_ROOT = '/the one'
PROCESS_ROOT = '/the one/drivers/processes'
INDEX_URL = 'https://pypi.org/simple/'
PROJECT_JSON_URL = 'https://pypi.org/pypi/{name}/json'
MAXIMUM_REQUEST = 256 * 1024
MAXIMUM_RESPONSE = 8 * 1024 * 1024
MAXIMUM_FILES = 100000
MAXIMUM_BYTES = 2 * 1024 * 1024 * 1024
MAXIMUM_FILE_BYTES = 512 * 1024 * 1024
PIP_TIMEOUT = 900
COMPILE_TIMEOUT = 300
IMPORT_TIMEOUT = 300
GLIBC_MAXIMUM = (2, 41)
PROJECT_NAME = re.compile(
    r'^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,126}[A-Za-z0-9])?$'
)
EXACT_VERSION = re.compile(
    r'^[A-Za-z0-9](?:[A-Za-z0-9.!+_-]{0,126}[A-Za-z0-9])?$'
)
HASH = re.compile(r'^[0-9a-f]{64}$')
SAFE_RELATIVE = re.compile(r'^[^\\\x00]+$')
DISALLOWED_TOP_LEVEL = frozenset({
    'sitecustomize', 'usercustomize', 'pip', 'ensurepip', 'setuptools',
    'pkg_resources', 'wheel',
})
DISALLOWED_SUFFIXES = ('.egg-link', '.egg', '.pyi-link')
MERGED_GLIBC = {
    'libpthread.so.0': 'libc.so.6',
    'libdl.so.2': 'libc.so.6',
    'librt.so.1': 'libc.so.6',
    'libutil.so.1': 'libc.so.6',
    'libanl.so.1': 'libc.so.6',
}
EXTENSION_SUFFIXES = tuple(
    sorted(importlib.machinery.EXTENSION_SUFFIXES, key=len, reverse=True)
)


class ManagerError(RuntimeError):
    """A package request is invalid or cannot be completed safely."""

    def __init__(self, message, code='failed', data=None):
        super().__init__(str(message))
        self.code = str(code or 'failed')
        self.data = dict(data or {})


class PythonManagerError(RuntimeError):
    """A client request was rejected or the manager was unavailable."""

    def __init__(self, message, code='failed', response=None):
        super().__init__(str(message))
        self.code = str(code or 'failed')
        self.response = dict(response or {})


def log(message, file=None):
    """Write one service log record in the standard T1OS format."""

    from GODDESS.GODDESS import formatlog

    print(formatlog('python', message), file=file or sys.stderr, flush=True)


def architect_capability_check(*arguments, **options):
    """Load the operations client only when a mutation needs authorization."""

    from operations.operations import architect_capability_check as check

    return check(*arguments, **options)


def request(operation, arguments=None, timeout=5.0, socket_path=None,
            descriptor=None):
    """Send one request and return the manager's structured response."""

    path = str(
        socket_path
        or os.environ.get('T1OS_PYTHON_MANAGER_SOCKET')
        or DEFAULT_SOCKET
    )
    payload = {
        'format': PROTOCOL,
        'operation': str(operation or '').strip(),
        'arguments': dict(arguments or {}),
    }
    encoded = (
        json.dumps(payload, sort_keys=True, separators=(',', ':')) + '\n'
    ).encode('utf-8')

    if len(encoded) > MAXIMUM_REQUEST:
        raise PythonManagerError(
            'The Python manager request is too large.', 'request_too_large')

    channel = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    channel.settimeout(float(timeout))

    try:
        channel.connect(path)
        ready = channel.recv(1)
        if ready != PROTOCOL_READY:
            raise PythonManagerError(
                'The Python manager did not complete its request handshake.',
                'handshake_failed',
            )
        if descriptor is None:
            channel.sendall(encoded)
        elif str(operation or '').strip() == 'apply_lock':
            try:
                expected = int(payload['arguments']['size'])
            except (KeyError, TypeError, ValueError) as error:
                raise PythonManagerError(
                    'The Python lock stream size is invalid.',
                    'invalid_arguments',
                ) from error
            if expected <= 0 or expected > 1024 * 1024:
                raise PythonManagerError(
                    'The Python lock stream size is invalid.',
                    'invalid_arguments',
                )
            channel.sendall(encoded)
            remaining = expected
            while remaining:
                block = os.read(int(descriptor), min(65536, remaining))
                if not block:
                    raise PythonManagerError(
                        'The Python lock stream ended early.',
                        'short_request',
                    )
                channel.sendall(block)
                remaining -= len(block)
        else:
            rights = array.array('i', [int(descriptor)])
            sent = channel.sendmsg(
                [encoded],
                [(socket.SOL_SOCKET, socket.SCM_RIGHTS, rights)],
            )
            if sent != len(encoded):
                raise PythonManagerError(
                    'The Python manager descriptor request was incomplete.',
                    'short_request',
                )
        received = bytearray()

        while b'\n' not in received:
            block = channel.recv(min(65536, MAXIMUM_RESPONSE - len(received)))
            if not block:
                break
            received.extend(block)
            if len(received) >= MAXIMUM_RESPONSE:
                raise PythonManagerError(
                    'The Python manager response is too large.',
                    'response_too_large',
                )
    except PythonManagerError:
        raise
    except (OSError, TimeoutError) as error:
        raise PythonManagerError(
            'The Python manager is unavailable. ' + str(error),
            'manager_unavailable',
        ) from error
    finally:
        channel.close()

    line = bytes(received).split(b'\n', 1)[0]
    if not line:
        raise PythonManagerError(
            'The Python manager closed the request without a response.',
            'empty_response',
        )

    try:
        response = json.loads(line.decode('utf-8'))
    except (UnicodeError, ValueError, TypeError) as error:
        raise PythonManagerError(
            'The Python manager returned an invalid response.',
            'invalid_response',
        ) from error

    if not isinstance(response, dict) or int(response.get('format', 0)) != PROTOCOL:
        raise PythonManagerError(
            'The Python manager returned an unsupported response.',
            'unsupported_response',
            response if isinstance(response, dict) else None,
        )

    if not bool(response.get('ok')):
        raise PythonManagerError(
            response.get('message') or 'The Python manager rejected the request.',
            response.get('code') or 'failed',
            response,
        )

    return response


def data(operation, arguments=None, timeout=5.0, socket_path=None):
    """Return only a successful response's data mapping."""

    return request(
        operation,
        arguments=arguments,
        timeout=timeout,
        socket_path=socket_path,
    ).get('data', {})


def system_root():
    return os.path.abspath(
        os.environ.get('T1OS_SYSTEM_ROOT', DEFAULT_SYSTEM_ROOT)
    )


def python_root():
    return os.path.abspath(os.environ.get(
        'T1OS_PYTHON_ROOT',
        os.path.join(system_root(), 'software', 'python'),
    ))


def python_library():
    return f'python{sys.version_info.major}.{sys.version_info.minor}'


def site_packages():
    return os.path.abspath(os.environ.get(
        'T1OS_PYTHON_SITE_PACKAGES',
        os.path.join(python_root(), 'lib', python_library(), 'site-packages'),
    ))


def python_bin():
    return os.path.abspath(os.environ.get(
        'T1OS_PYTHON_BIN',
        os.path.join(python_root(), 'bin'),
    ))


def catalogue_path():
    return os.path.abspath(os.environ.get(
        'T1OS_PYTHON_CATALOGUE',
        os.path.join(system_root(), 'catalogue', 'python'),
    ))


def provider_catalogues():
    """Return managed and immutable native-library provider catalogues."""

    paths = [
        catalogue_path(),
        os.path.join(system_root(), 'catalogue', 'python'),
    ]
    result = []
    for path in paths:
        path = os.path.abspath(path)
        if path not in result:
            result.append(path)
    return result


def image_catalogue():
    return os.path.abspath(os.environ.get(
        'T1OS_PYTHON_IMAGE_CATALOGUE',
        os.path.join(system_root(), 'catalogue', 'image'),
    ))


def management_root():
    return os.path.abspath(os.environ.get(
        'T1OS_PYTHON_MANAGEMENT_ROOT',
        os.path.join(python_root(), '.t1pip'),
    ))


def state_path():
    return os.path.join(management_root(), 'state.json')


def previous_path():
    return os.path.join(management_root(), 'previous.json')


def history_path():
    return os.path.join(management_root(), 'history.jsonl')


def cache_path():
    return os.path.join(management_root(), 'artifacts')


def transactions_path():
    return os.path.join(management_root(), 'transactions')


def core_manifest_path():
    return os.path.join(python_root(), 'manifest.json')


def tool_directory():
    return os.path.dirname(os.path.abspath(__file__))


def tools_configuration():
    return os.path.join(tool_directory(), 'tools.json')


def socket_path():
    return os.environ.get('T1OS_PYTHON_MANAGER_SOCKET', DEFAULT_SOCKET)


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def normalise_name(value):
    name = str(value or '').strip()
    if not PROJECT_NAME.fullmatch(name):
        raise ManagerError('Use a valid Python distribution name.', 'invalid_name')
    return re.sub(r'[-_.]+', '-', name).lower()


def exact_version(value):
    version = str(value or '').strip()
    if not EXACT_VERSION.fullmatch(version):
        raise ManagerError('Use one exact Python module version.', 'invalid_version')
    return version


def process_start_time(pid):
    try:
        with open(os.path.join(PROCESS_ROOT, str(int(pid)), 'stat'),
                  'r', encoding='ascii') as stream:
            value = stream.read(4096)
        end = value.rfind(')')
        fields = value[end + 2:].split()
        return int(fields[19]) if end > 0 and len(fields) > 19 else 0
    except (OSError, TypeError, ValueError):
        return 0


def process_uid_gid(pid):
    try:
        with open(os.path.join(PROCESS_ROOT, str(int(pid)), 'status'),
                  'r', encoding='ascii') as stream:
            values = {}
            for line in stream:
                if line.startswith(('Uid:', 'Gid:')):
                    key, value = line.split(':', 1)
                    values[key] = int(value.split()[0])
        return values.get('Uid', -1), values.get('Gid', -1)
    except (OSError, TypeError, ValueError):
        return -1, -1


def process_domain(pid):
    try:
        with open(os.path.join(PROCESS_ROOT, str(int(pid)), 'attr', 'current'),
                  'r', encoding='ascii') as stream:
            value = stream.read(128).strip()
    except OSError:
        return ''
    return value[5:] if value.startswith('t1os:') else ''


def peer_identity(channel):
    try:
        raw = channel.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
        pid, uid, gid = struct.unpack('3i', raw)
    except (AttributeError, OSError, struct.error):
        return None
    started = process_start_time(pid)
    domain = process_domain(pid)
    proc_uid, proc_gid = process_uid_gid(pid)
    allowed = {'brick', 'settings'}
    if (
        pid < 2 or uid != 1000 or gid != 1000 or
        proc_uid != uid or proc_gid != gid or
        not started or domain not in allowed
    ):
        return None
    return {
        'pid': pid, 'uid': uid, 'gid': gid, 'started': started,
        'domain': domain,
    }


def require_architect(peer, operation, arguments):
    if not isinstance(peer, dict):
        raise ManagerError(
            'Authenticate this Python change in the requesting application.',
            'architect_required')
    try:
        result = architect_capability_check(
            operation, arguments,
            client_pid=peer['pid'], client_started=peer['started'],
            client_uid=peer['uid'], timeout=3.0)
    except Exception as error:
        raise ManagerError(
            'Python change authorization is unavailable.',
            'architect_required') from error
    if not result.get('authorized'):
        raise ManagerError(
            'Authenticate this Python change in the requesting application.',
            'architect_required')


def contained(path, parent):
    resolved = os.path.realpath(path)
    base = os.path.realpath(parent)
    return resolved == base or resolved.startswith(base + os.sep)


def safe_relative(value):
    value = str(value or '').replace('\\', '/')
    if (
        not value or value.startswith('/') or not SAFE_RELATIVE.fullmatch(value)
        or any(part in ('', '.', '..') for part in value.split('/'))
    ):
        raise ManagerError('A package contains an unsafe path.', 'unsafe_path')
    return value


def safe_remove_tree(path, parent):
    if not contained(path, parent) or os.path.realpath(path) == os.path.realpath(parent):
        raise ManagerError('Refusing an unsafe cleanup path.', 'unsafe_path')
    if not os.path.lexists(path):
        return
    status = os.lstat(path)
    if stat.S_ISLNK(status.st_mode) or not stat.S_ISDIR(status.st_mode):
        os.unlink(path)
    else:
        shutil.rmtree(path)


def read_json(path, default=None):
    try:
        with open(path, 'r', encoding='utf-8') as stream:
            return json.load(stream)
    except FileNotFoundError:
        return default
    except (OSError, ValueError, TypeError) as error:
        raise ManagerError(
            'T1OS Python package state is unreadable: ' + str(error),
            'state_invalid',
        ) from error


def fsync_directory(path):
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
    except (OSError, PermissionError):
        if os.name == 'nt':
            return
        raise
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_bytes(path, payload, mode=0o644):
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    temporary = os.path.join(
        directory, '.' + os.path.basename(path) + '.' + uuid.uuid4().hex + '.new'
    )
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0),
        mode,
    )
    try:
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise OSError('short write')
            offset += written
        os.fsync(descriptor)
    except BaseException:
        os.close(descriptor)
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    else:
        os.close(descriptor)
    os.replace(temporary, path)
    fsync_directory(directory)


def atomic_json(path, value, mode=0o644):
    payload = (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + '\n'
    ).encode('utf-8')
    atomic_bytes(path, payload, mode)


def append_history(record):
    os.makedirs(management_root(), exist_ok=True)
    payload = (
        json.dumps(record, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
        + '\n'
    ).encode('utf-8')
    descriptor = os.open(
        history_path(),
        os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, 'O_NOFOLLOW', 0),
        0o644,
    )
    try:
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def default_state():
    return {
        'format': STATE_FORMAT,
        'python_version': '.'.join(str(value) for value in sys.version_info[:3]),
        'transaction': '',
        'requested': [],
        'artifacts': [],
        'packages': [],
        'files': [],
        'catalogue_files': [],
        'updated_at': None,
    }


def validate_state(value):
    if value is None:
        return default_state()
    if not isinstance(value, dict) or int(value.get('format', 0)) != STATE_FORMAT:
        raise ManagerError('T1OS Python package state has an unsupported format.', 'state_invalid')
    for field in ('requested', 'artifacts', 'packages', 'files', 'catalogue_files'):
        if not isinstance(value.get(field), list):
            raise ManagerError('T1OS Python package state is malformed.', 'state_invalid')
    for record in value.get('files', []) + value.get('catalogue_files', []):
        if not isinstance(record, dict):
            raise ManagerError('T1OS Python ownership state is malformed.', 'state_invalid')
        safe_relative(record.get('path'))
        if not HASH.fullmatch(str(record.get('sha256') or '')):
            raise ManagerError('T1OS Python ownership state has an invalid hash.', 'state_invalid')
    return value


def load_state(path=None):
    return validate_state(read_json(path or state_path(), None))


def ensure_store():
    root = management_root()
    if os.path.lexists(root) and stat.S_ISLNK(os.lstat(root).st_mode):
        raise ManagerError('The Python module state cannot be a link.', 'unsafe_store')
    for path in (root, cache_path(), transactions_path()):
        os.makedirs(path, exist_ok=True)
        status = os.lstat(path)
        if not stat.S_ISDIR(status.st_mode) or stat.S_ISLNK(status.st_mode):
            raise ManagerError('The Python module state is unsafe.', 'unsafe_store')


def requested_mapping(state):
    mapping = {}
    for source in state.get('requested', []):
        if not isinstance(source, dict):
            raise ManagerError('Requested package state is invalid.', 'state_invalid')
        item = dict(source)
        item['name'] = normalise_name(item.get('name'))
        mapping[item['name']] = item
    return mapping


def distribution_imports(distribution):
    try:
        files = distribution.files or []
    except Exception:
        files = []
    roots = {
        str(item).replace('\\', '/').split('/', 1)[0]
        for item in files
    }

    def import_exists(value):
        return any(
            root == value or root == value + '.py' or root.startswith(value + '.')
            for root in roots
        )

    values = []
    try:
        text = distribution.read_text('top_level.txt') or ''
    except Exception:
        text = ''
    for value in text.splitlines():
        value = value.strip()
        if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', value):
            values.append(value)
    # Some wheels publish stale top_level.txt entries for extension modules
    # which only exist inside a package (PyNaCl, for example, declares
    # ``_sodium`` while shipping ``nacl/_sodium.abi3.so``).  Import only names
    # that the wheel actually installs at its root.  Otherwise a valid native
    # package is rejected by testing a module that cannot exist.
    available = [value for value in values if import_exists(value)]
    if available:
        return sorted(set(available), key=str.casefold)
    values = []
    for item in files:
        first = str(item).replace('\\', '/').split('/', 1)[0]
        if first.endswith('.py'):
            first = first[:-3]
        if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', first):
            values.append(first)
    return sorted(set(values), key=str.casefold)


def distributions_at(paths):
    existing = [path for path in paths if os.path.isdir(path)]
    if not existing:
        return []
    try:
        return list(importlib.metadata.distributions(path=existing))
    except Exception:
        return []


def package_records(state):
    return {
        normalise_name(item.get('name')): item
        for item in state.get('packages', []) if isinstance(item, dict)
    }


def installed_modules():
    state = load_state()
    managed = package_records(state)
    requested = requested_mapping(state)
    results = []
    seen = set()
    for origin, paths in (
        ('site', [site_packages()]),
        ('image', [image_catalogue()]),
    ):
        for distribution in distributions_at(paths):
            try:
                display_name = str(distribution.metadata.get('Name') or '').strip()
                version = str(distribution.version or '').strip()
                if not display_name or not version:
                    continue
                name = normalise_name(display_name)
                key = (name, origin)
                if key in seen:
                    continue
                seen.add(key)
                package = managed.get(name) if origin == 'site' else None
                request = requested.get(name, {}) if package else {}
                results.append({
                    'name': name,
                    'display_name': display_name,
                    'version': version,
                    'imports': distribution_imports(distribution),
                    'origin': 'managed' if package else 'system',
                    'system': not bool(package),
                    'requested': bool(request),
                    'pinned': bool(request.get('pinned')),
                    'requirement': str(request.get('requirement') or ''),
                    'requires': [str(item) for item in (distribution.requires or [])],
                    'summary': str(distribution.metadata.get('Summary') or '').strip(),
                    'license': str(
                        distribution.metadata.get('License-Expression')
                        or distribution.metadata.get('License') or ''
                    ).strip(),
                    'native': bool((package or {}).get('native')),
                    'native_libraries': len((package or {}).get('catalogue_files', [])),
                    'installer': str((package or {}).get('installer') or 't1os-build'),
                })
            except Exception:
                continue
    results.sort(key=lambda item: (item['name'], item['origin']))
    return state, results


def core_identity():
    version = '.'.join(str(value) for value in sys.version_info[:3])
    release = ''
    manifest_hash = ''
    try:
        manifest = read_json(core_manifest_path(), {}) or {}
        release = str(manifest.get('release') or '')
        manifest_hash = sha256(core_manifest_path())
    except (ManagerError, OSError):
        pass
    return {
        'version': version,
        'implementation': sys.implementation.name,
        'abi': f'cp{sys.version_info.major}{sys.version_info.minor}',
        'architecture': os.uname().machine if hasattr(os, 'uname') else 'unknown',
        'release': release,
        'manifest_sha256': manifest_hash,
        'entrypoint': sys.executable,
        'site_packages': site_packages(),
        'catalogue': catalogue_path(),
    }


def read_history(limit=50):
    try:
        with open(history_path(), 'r', encoding='utf-8') as stream:
            lines = stream.readlines()[-max(1, min(int(limit), 500)):]
    except OSError:
        return []
    records = []
    for line in lines:
        try:
            value = json.loads(line)
            if isinstance(value, dict):
                records.append(value)
        except (ValueError, TypeError):
            pass
    return records


CURRENT = {
    'running': False,
    'operation': '',
    'phase': '',
    'started_at': None,
    'transaction': '',
}
CURRENT_LOCK = threading.Lock()
TRANSACTION_LOCK = threading.Lock()


def set_progress(operation='', phase='', transaction='', running=True):
    with CURRENT_LOCK:
        started = CURRENT.get('started_at')
        if running and not CURRENT.get('running'):
            started = time.time()
        CURRENT.update({
            'running': bool(running),
            'operation': str(operation),
            'phase': str(phase),
            'transaction': str(transaction),
            'started_at': started if running else None,
        })


def progress():
    with CURRENT_LOCK:
        return dict(CURRENT)


def verified_tool(record_name, suffix=''):
    configuration = read_json(tools_configuration(), {}) or {}
    record = configuration.get(record_name, {})
    filename = str(record.get('filename') or '')
    if os.path.basename(filename) != filename or (suffix and not filename.endswith(suffix)):
        raise ManagerError('The private Python tool lock is invalid.', 'tool_invalid')
    configured_path = str(record.get('path') or '')
    if configured_path:
        if (
            not os.path.isabs(configured_path)
            or os.path.normpath(configured_path) != configured_path
            or os.path.basename(configured_path) != filename
        ):
            raise ManagerError('The private Python tool path is invalid.', 'tool_invalid')
        path = configured_path
    else:
        path = os.path.join(tool_directory(), filename)
    try:
        status = os.stat(path, follow_symlinks=False)
    except OSError as error:
        raise ManagerError('A private Python tool is missing.', 'tool_missing') from error
    if not stat.S_ISREG(status.st_mode) or status.st_size != int(record.get('size', -1)):
        raise ManagerError('A private Python tool has an invalid size.', 'tool_invalid')
    expected = str(record.get('sha256') or '').lower()
    if not HASH.fullmatch(expected) or sha256(path) != expected:
        raise ManagerError('A private Python tool has an invalid hash.', 'tool_invalid')
    return path, configuration


def verified_pip():
    return verified_tool('pip', '.whl')


def patchelf_path():
    override = os.environ.get('T1OS_PATCHELF')
    if override:
        return os.path.abspath(override)
    path, _ = verified_tool('patchelf')
    return path


def packaging_api():
    path, _ = verified_pip()
    if path not in sys.path:
        sys.path.insert(0, path)
    try:
        from pip._vendor.packaging.markers import default_environment
        from pip._vendor.packaging.requirements import Requirement
        from pip._vendor.packaging.tags import sys_tags
        from pip._vendor.packaging.version import Version, InvalidVersion
    except Exception as error:
        raise ManagerError('The private packaging library is unusable.', 'tool_invalid') from error
    return Requirement, Version, InvalidVersion, default_environment, sys_tags


def target_environment():
    _, _, _, default_environment, _ = packaging_api()
    environment = default_environment()
    environment.update({
        'os_name': 'posix',
        'sys_platform': 'linux',
        'platform_system': 'Linux',
        'platform_machine': 'x86_64',
        'implementation_name': 'cpython',
        'platform_python_implementation': 'CPython',
        'python_version': f'{sys.version_info.major}.{sys.version_info.minor}',
        'python_full_version': '.'.join(str(value) for value in sys.version_info[:3]),
    })
    return environment


def dependency_problems(modules):
    Requirement, Version, InvalidVersion, _, _ = packaging_api()
    versions = {}
    for item in modules:
        try:
            versions[item['name']] = Version(item['version'])
        except InvalidVersion:
            continue
    environment = target_environment()
    problems = []
    for item in modules:
        for text in item.get('requires', []):
            try:
                requirement = Requirement(text)
                if requirement.marker and not requirement.marker.evaluate(environment):
                    continue
                name = normalise_name(requirement.name)
                actual = versions.get(name)
                if actual is None:
                    problems.append(f"{item['display_name']} requires {requirement}")
                elif requirement.specifier and actual not in requirement.specifier:
                    problems.append(
                        f"{item['display_name']} requires {requirement}; {actual} is installed"
                    )
            except Exception as error:
                problems.append(f"{item['display_name']} has invalid dependency {text}: {error}")
    return sorted(set(problems), key=str.casefold)


def run_command(command, timeout, environment=None, code='tool_failed'):
    try:
        result = subprocess.run(
            command,
            # T1OS publishes device nodes below /the one/drivers/nodes, while
            # Python's DEVNULL sentinel always opens the standard null device.
            # A closed pipe supplies the package tool with deterministic EOF and
            # keeps package operations fully non-interactive.
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            env=environment,
            close_fds=True,
        )
    except subprocess.TimeoutExpired as error:
        raise ManagerError('The Python package operation timed out.', 'timeout') from error
    except OSError as error:
        raise ManagerError('A Python package tool could not start: ' + str(error), code) from error
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or '').strip()
        lines = [line.strip() for line in detail.splitlines() if line.strip()]
        message = lines[-1] if lines else 'The Python package tool failed.'
        raise ManagerError(message[:2000], code, {'output': detail[-16000:]})
    return result


def pip_environment():
    environment = {
        'PATH': os.environ.get('PATH', ''),
        'LANG': 'C.UTF-8',
        'LC_ALL': 'C.UTF-8',
        'PYTHONNOUSERSITE': '1',
        'PYTHONDONTWRITEBYTECODE': '1',
        'PIP_DISABLE_PIP_VERSION_CHECK': '1',
        'PIP_NO_INPUT': '1',
    }
    for name in ('TMP', 'TEMP', 'TMPDIR', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATHEXT'):
        if os.environ.get(name):
            environment[name] = os.environ[name]
    certificate = os.path.join(system_root(), 'settings', 'network', 'cacerts.pem')
    if os.path.isfile(certificate):
        environment['SSL_CERT_FILE'] = certificate
        environment['PIP_CERT'] = certificate
    return environment


def manager_python_command(extra_library_paths=None):
    encoded = os.environ.get('T1OS_PYTHON_TEST_LAUNCHER')
    if not encoded:
        # Bind package-tool children to the immutable canonical interpreter
        # object used by the running Python service.
        return [os.path.realpath(sys.executable)]
    try:
        values = json.loads(encoded)
    except (ValueError, TypeError) as error:
        raise ManagerError('The Python test launcher is malformed.', 'tool_invalid') from error
    if (
        not isinstance(values, list) or not values
        or any(not isinstance(value, str) or not value for value in values)
        or not os.path.isabs(values[0]) or not os.path.isfile(values[0])
    ):
        raise ManagerError('The Python test launcher is unsafe.', 'tool_invalid')
    values = list(values)
    extra_library_paths = [
        os.path.abspath(path) for path in (extra_library_paths or []) if path
    ]
    if extra_library_paths and '--library-path' in values:
        index = values.index('--library-path')
        if index + 1 >= len(values):
            raise ManagerError('The Python test launcher is malformed.', 'tool_invalid')
        values[index + 1] = os.pathsep.join(extra_library_paths + [values[index + 1]])
    return values


def private_pip_command(pip_path, *arguments):
    launcher = (
        'import runpy,sys;'
        'sys.path.insert(0,sys.argv.pop(1));'
        'runpy.run_module("pip",run_name="__main__")'
    )
    return [*manager_python_command(), '-I', '-B', '-c', launcher, pip_path, *arguments]


def copy_local_wheel(path):
    source = os.path.abspath(str(path or ''))
    if not source.lower().endswith('.whl'):
        raise ManagerError('Choose a Python wheel file.', 'wheel_required')
    try:
        status = os.stat(source, follow_symlinks=False)
    except OSError as error:
        raise ManagerError('The Python wheel is unavailable.', 'wheel_missing') from error
    if not stat.S_ISREG(status.st_mode) or status.st_nlink != 1:
        raise ManagerError('The Python wheel file is unsafe.', 'unsafe_wheel')
    if status.st_size <= 0 or status.st_size > MAXIMUM_FILE_BYTES:
        raise ManagerError('The Python wheel file has an unsafe size.', 'size_limit')
    ensure_store()
    digest = sha256(source)
    directory = os.path.join(cache_path(), digest)
    os.makedirs(directory, exist_ok=True)
    destination = os.path.join(directory, os.path.basename(source))
    if not os.path.exists(destination):
        temporary = destination + '.' + uuid.uuid4().hex + '.new'
        shutil.copyfile(source, temporary, follow_symlinks=False)
        if sha256(temporary) != digest:
            os.unlink(temporary)
            raise ManagerError('The Python wheel changed while being copied.', 'wheel_changed')
        os.replace(temporary, destination)
        fsync_directory(directory)
    return destination, digest


def descriptor_identity(descriptor, maximum, arguments, label,
                        allow_anonymous=False):
    if descriptor is None:
        raise ManagerError(label + ' requires a file descriptor.',
                           'descriptor_required')
    try:
        status = os.fstat(descriptor)
    except OSError as error:
        raise ManagerError(label + ' descriptor is unavailable.',
                           'descriptor_invalid') from error
    valid_links = (0, 1) if allow_anonymous else (1,)
    if not stat.S_ISREG(status.st_mode) or status.st_nlink not in valid_links:
        raise ManagerError(label + ' descriptor is unsafe.', 'descriptor_invalid')
    try:
        expected_size = int(arguments.get('size', -1))
    except (TypeError, ValueError) as error:
        raise ManagerError(label + ' size is invalid.',
                           'invalid_arguments') from error
    if status.st_size <= 0 or status.st_size > int(maximum):
        raise ManagerError(label + ' has an unsafe size.', 'size_limit')
    if status.st_size != expected_size:
        raise ManagerError(label + ' changed before it was received.', 'file_changed')
    expected_hash = str(arguments.get('sha256') or '').lower()
    if not HASH.fullmatch(expected_hash):
        raise ManagerError(label + ' hash is invalid.', 'invalid_arguments')
    return status, expected_size, expected_hash


def descriptor_bytes(descriptor, maximum, arguments, label,
                     allow_anonymous=False):
    """Read and authenticate one regular-file descriptor from a client."""

    _, expected_size, expected_hash = descriptor_identity(
        descriptor, maximum, arguments, label,
        allow_anonymous=allow_anonymous)
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
        content = bytearray()
        digest = hashlib.sha256()
        while len(content) <= maximum:
            block = os.read(
                descriptor, min(1024 * 1024, maximum + 1 - len(content)))
            if not block:
                break
            content.extend(block)
            digest.update(block)
    except OSError as error:
        raise ManagerError(label + ' could not be read.',
                           'descriptor_invalid') from error
    if len(content) != expected_size or digest.hexdigest() != expected_hash:
        raise ManagerError(label + ' changed before it was received.', 'file_changed')
    return bytes(content), expected_hash


def copy_descriptor_wheel(descriptor, arguments):
    filename = os.path.basename(str(arguments.get('filename') or ''))
    if (not filename or filename != str(arguments.get('filename') or '')
            or not filename.lower().endswith('.whl')):
        raise ManagerError('Choose a Python wheel file.', 'wheel_required')
    _, expected_size, digest = descriptor_identity(
        descriptor, MAXIMUM_FILE_BYTES, arguments, 'Python wheel')
    ensure_store()
    directory = os.path.join(cache_path(), digest)
    os.makedirs(directory, exist_ok=True)
    destination = os.path.join(directory, filename)
    temporary = os.path.join(directory, '.' + filename + '.' + uuid.uuid4().hex + '.new')
    output = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0),
        0o600,
    )
    copied = 0
    actual = hashlib.sha256()
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
        while copied <= MAXIMUM_FILE_BYTES:
            block = os.read(
                descriptor,
                min(1024 * 1024, MAXIMUM_FILE_BYTES + 1 - copied),
            )
            if not block:
                break
            actual.update(block)
            offset = 0
            while offset < len(block):
                written = os.write(output, block[offset:])
                if written <= 0:
                    raise OSError('short write')
                offset += written
            copied += len(block)
        os.fsync(output)
    except BaseException:
        os.close(output)
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    else:
        os.close(output)
    if copied != expected_size or actual.hexdigest() != digest:
        os.unlink(temporary)
        raise ManagerError('Python wheel changed before it was received.',
                           'file_changed')
    if not os.path.exists(destination):
        os.replace(temporary, destination)
        fsync_directory(directory)
    else:
        os.unlink(temporary)
    if sha256(destination) != digest:
        raise ManagerError('The cached Python wheel has changed.', 'wheel_changed')
    return destination, digest


def requirement_argument(item):
    kind = str(item.get('kind') or 'index')
    if kind == 'wheel':
        path = str(item.get('path') or '')
        if not contained(path, cache_path()) or not os.path.isfile(path):
            raise ManagerError('A cached Python wheel is missing.', 'wheel_missing')
        return path
    name = normalise_name(item.get('name'))
    requirement = str(item.get('requirement') or name).strip()
    Requirement, _, _, _, _ = packaging_api()
    try:
        parsed = Requirement(requirement)
    except Exception as error:
        raise ManagerError('Use a valid Python package requirement.', 'invalid_requirement') from error
    if normalise_name(parsed.name) != name or parsed.url or parsed.marker:
        raise ManagerError('Use a package name with an optional version constraint.', 'invalid_requirement')
    return requirement


def report_artifacts(report):
    artifacts = []
    for item in report.get('install', []):
        metadata = item.get('metadata', {})
        name = normalise_name(metadata.get('name'))
        version = str(metadata.get('version') or '')
        download = item.get('download_info', {})
        url = str(download.get('url') or '')
        archive = download.get('archive_info', {})
        hashes = dict(archive.get('hashes') or {})
        digest = str(hashes.get('sha256') or '').lower()
        if not digest and str(archive.get('hash') or '').startswith('sha256='):
            digest = str(archive['hash']).split('=', 1)[1].lower()
        if not version or not url or not HASH.fullmatch(digest):
            raise ManagerError('The resolver omitted an artifact identity.', 'report_invalid')
        artifacts.append({
            'name': name,
            'version': version,
            'url': url,
            'sha256': digest,
            'requested': bool(item.get('requested')),
        })
    artifacts.sort(key=lambda item: item['name'])
    return artifacts


def file_manifest(base):
    base = os.path.abspath(base)
    records = []
    count = 0
    total = 0
    if not os.path.isdir(base):
        return records
    for root, directories, files in os.walk(base, topdown=True, followlinks=False):
        directories.sort(key=str.casefold)
        files.sort(key=str.casefold)
        for name in directories:
            status = os.lstat(os.path.join(root, name))
            if not stat.S_ISDIR(status.st_mode) or stat.S_ISLNK(status.st_mode):
                raise ManagerError('A package contains an unsafe directory.', 'unsafe_wheel')
        for name in files:
            path = os.path.join(root, name)
            status = os.lstat(path)
            if not stat.S_ISREG(status.st_mode) or status.st_nlink != 1:
                raise ManagerError('A package contains a link or special file.', 'unsafe_wheel')
            if status.st_size > MAXIMUM_FILE_BYTES:
                raise ManagerError('A Python package file is too large.', 'size_limit')
            count += 1
            total += status.st_size
            if count > MAXIMUM_FILES or total > MAXIMUM_BYTES:
                raise ManagerError('The Python package installation is too large.', 'size_limit')
            records.append({
                'path': os.path.relpath(path, base).replace(os.sep, '/'),
                'size': status.st_size,
                'sha256': sha256(path),
            })
    records.sort(key=lambda item: item['path'].encode('utf-8'))
    return records


def is_elf(path):
    try:
        with open(path, 'rb') as stream:
            return stream.read(4) == b'\x7fELF'
    except OSError:
        return False


def validate_elf_header(path):
    with open(path, 'rb') as stream:
        header = stream.read(64)
    if len(header) < 64 or header[:4] != b'\x7fELF':
        raise ManagerError('A native package file has an invalid ELF header.', 'native_invalid')
    if header[4] != 2 or header[5] != 1 or struct.unpack_from('<H', header, 18)[0] != 62:
        raise ManagerError(
            'A native package is not ELF64 little-endian x86-64.',
            'native_architecture',
        )
    versions = []
    with open(path, 'rb') as stream:
        data = stream.read()
    for major, minor in re.findall(rb'GLIBC_([0-9]+)\.([0-9]+)', data):
        versions.append((int(major), int(minor)))
    if versions and max(versions) > GLIBC_MAXIMUM:
        maximum = '.'.join(map(str, max(versions)))
        raise ManagerError(
            f'A native package requires GLIBC {maximum}; T1OS provides 2.41.',
            'native_glibc',
        )


def elf_dynamic_layout(path, data=None):
    """Return the file-backed dynamic-string layout for one ELF64 object."""
    if data is None:
        data = Path(path).read_bytes()
    if len(data) < 64 or data[:6] != b'\x7fELF\x02\x01':
        raise ManagerError('A native package has an invalid ELF layout.', 'native_invalid')
    try:
        program_offset = struct.unpack_from('<Q', data, 32)[0]
        program_size = struct.unpack_from('<H', data, 54)[0]
        program_count = struct.unpack_from('<H', data, 56)[0]
    except struct.error as error:
        raise ManagerError('A native package has a truncated ELF header.', 'native_invalid') from error
    if program_size < 56 or program_count > 4096:
        raise ManagerError('A native package has an unsafe ELF program table.', 'native_invalid')
    loads = []
    dynamic = None
    interpreter = None
    for index in range(program_count):
        offset = program_offset + index * program_size
        if offset < 0 or offset + 56 > len(data):
            raise ManagerError('A native package has a truncated ELF program table.', 'native_invalid')
        kind, _, file_offset, virtual, _, file_size, memory_size, _ = struct.unpack_from(
            '<IIQQQQQQ', data, offset
        )
        if file_offset + file_size > len(data):
            raise ManagerError('A native package maps data beyond the file.', 'native_invalid')
        if kind == 1:
            loads.append((virtual, file_offset, file_size, memory_size))
        elif kind == 2:
            dynamic = (file_offset, file_size)
        elif kind == 3:
            interpreter = (file_offset, file_size)
    if dynamic is None:
        raise ManagerError('A native package has no dynamic table.', 'native_invalid')

    entries = []
    dynamic_offset, dynamic_size = dynamic
    for offset in range(dynamic_offset, dynamic_offset + dynamic_size, 16):
        if offset + 16 > len(data):
            raise ManagerError('A native package has a truncated dynamic table.', 'native_invalid')
        tag, value = struct.unpack_from('<QQ', data, offset)
        entries.append((tag, value))
        if tag == 0:
            break
    else:
        raise ManagerError('A native package dynamic table is not terminated.', 'native_invalid')
    values = {}
    for tag, value in entries:
        values.setdefault(tag, []).append(value)
    if 5 not in values or 10 not in values:
        raise ManagerError('A native package has no dynamic string table.', 'native_invalid')
    string_virtual = values[5][0]
    string_size = values[10][0]
    string_offset = None
    for virtual, file_offset, file_size, _ in loads:
        if virtual <= string_virtual and string_virtual + string_size <= virtual + file_size:
            string_offset = file_offset + (string_virtual - virtual)
            break
    if string_offset is None or string_offset + string_size > len(data):
        raise ManagerError(
            'A native package has a dynamic string table outside a loadable segment.',
            'native_invalid',
        )
    for tag in (1, 14, 15, 29):
        for value in values.get(tag, []):
            if value >= string_size:
                raise ManagerError('A native package has an invalid dynamic string.', 'native_invalid')
            start = string_offset + value
            if data.find(b'\0', start, string_offset + string_size) < 0:
                raise ManagerError('A native package has an unterminated dynamic string.', 'native_invalid')
    return {
        'data': data,
        'entries': entries,
        'values': values,
        'string_offset': string_offset,
        'string_size': string_size,
        'interpreter': interpreter,
    }


def replace_needed_in_place(path, old_name, new_name):
    """Replace a NEEDED name without growing or relocating the ELF tables."""
    old = old_name.encode('ascii')
    new = new_name.encode('ascii')
    if len(new) > len(old):
        raise ManagerError('A native dependency replacement is too long.', 'native_patch_failed')
    data = bytearray(Path(path).read_bytes())
    layout = elf_dynamic_layout(path, data)
    changed = False
    for value in layout['values'].get(1, []):
        start = layout['string_offset'] + value
        end = data.find(0, start, layout['string_offset'] + layout['string_size'])
        if bytes(data[start:end]) != old:
            continue
        data[start:end + 1] = new + b'\0' * (len(old) - len(new) + 1)
        changed = True
    if changed:
        with open(path, 'r+b') as stream:
            stream.seek(0)
            stream.write(data)
            stream.truncate()
            stream.flush()
            os.fsync(stream.fileno())
    return changed


def patchelf(arguments, path, allow_empty=False):
    result = run_command(
        [patchelf_path(), *arguments, path],
        60,
        pip_environment(),
        code='native_patch_failed',
    )
    output = result.stdout.strip()
    if not output and not allow_empty and arguments and arguments[0].startswith('--print'):
        return ''
    return output


def elf_needed(path):
    output = patchelf(['--print-needed'], path, allow_empty=True)
    return [line.strip() for line in output.splitlines() if line.strip()]


def elf_soname(path):
    return patchelf(['--print-soname'], path, allow_empty=True)


def elf_interpreter(path):
    try:
        return patchelf(['--print-interpreter'], path, allow_empty=True)
    except ManagerError:
        return ''


def native_library_candidate(relative, path):
    parts = relative.replace('\\', '/').split('/')
    lowered = os.path.basename(relative).lower()
    if any(part.lower().endswith(('.libs', '.lib')) for part in parts[:-1]):
        return True
    if '.cpython-' in lowered or lowered.endswith('.abi3.so'):
        return False
    if re.search(r'\.so(?:\.[0-9][0-9.]*)$', lowered):
        return bool(elf_soname(path))
    return False


def protected_paths():
    manifest = read_json(core_manifest_path(), {}) or {}
    software = {
        safe_relative(item.get('path'))
        for item in (manifest.get('software', {}) or {}).get('files', [])
        if isinstance(item, dict)
    }
    catalogue = {
        safe_relative(item.get('path'))
        for item in (manifest.get('catalogue', {}) or {}).get('files', [])
        if isinstance(item, dict)
    }
    return software, catalogue


def update_record(record_path, rows):
    entries = []
    for path, absolute in sorted(rows, key=lambda item: item[0].encode('utf-8')):
        if os.path.normcase(os.path.abspath(absolute)) == os.path.normcase(os.path.abspath(record_path)):
            entries.append((path, '', ''))
            continue
        digest = hashlib.sha256()
        with open(absolute, 'rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
        encoded = base64.urlsafe_b64encode(digest.digest()).rstrip(b'=').decode('ascii')
        entries.append((path, 'sha256=' + encoded, str(os.path.getsize(absolute))))
    output = io.StringIO(newline='')
    writer = csv.writer(output, lineterminator='\n')
    writer.writerows(entries)
    atomic_bytes(record_path, output.getvalue().encode('utf-8'))


def verify_distribution_record(site, distribution):
    try:
        record_text = distribution.read_text('RECORD')
        metadata_path = os.path.abspath(str(distribution._path))
    except Exception as error:
        raise ManagerError('A wheel has no readable installation record.', 'record_missing') from error
    if not record_text or not contained(metadata_path, site):
        raise ManagerError('A wheel has an unsafe installation record.', 'record_invalid')
    owners = set()
    seen = set()
    record_file = os.path.join(metadata_path, 'RECORD')
    for row in csv.reader(io.StringIO(record_text)):
        if len(row) != 3 or not row[0]:
            raise ManagerError('A wheel RECORD is malformed.', 'record_invalid')
        relative, encoded_hash, encoded_size = row
        owner_relative = relative.replace('\\', '/')
        # pip represents scripts with scheme-relative ../../bin paths even
        # when --target places them in TARGET/bin.  Translate only this exact
        # case; every other traversal remains forbidden.
        script_match = re.fullmatch(r'(?:\.\./)+bin/([A-Za-z0-9][A-Za-z0-9._+-]{0,126})', owner_relative)
        if script_match:
            owner_relative = 'bin/' + script_match.group(1)
        elif owner_relative.startswith('../'):
            raise ManagerError('A wheel RECORD escapes site-packages.', 'record_invalid')
        candidate = os.path.realpath(os.path.join(site, owner_relative.replace('/', os.sep)))
        if not contained(candidate, site):
            raise ManagerError('A wheel RECORD escapes site-packages.', 'record_invalid')
        key = os.path.normcase(candidate)
        if key in seen:
            raise ManagerError('A wheel RECORD repeats a path.', 'record_invalid')
        seen.add(key)
        if os.path.normcase(candidate) == os.path.normcase(record_file):
            owners.add(os.path.relpath(candidate, site).replace(os.sep, '/'))
            continue
        if not encoded_hash or not encoded_size:
            raise ManagerError('A wheel RECORD omits a file hash.', 'record_invalid')
        try:
            size = int(encoded_size)
            algorithm, value = encoded_hash.split('=', 1)
        except (ValueError, TypeError) as error:
            raise ManagerError('A wheel RECORD hash is malformed.', 'record_invalid') from error
        if algorithm.lower() not in ('sha256', 'sha384', 'sha512'):
            raise ManagerError('A wheel RECORD uses a weak hash.', 'record_invalid')
        if not os.path.isfile(candidate) or os.path.islink(candidate):
            raise ManagerError('A wheel RECORD file is missing.', 'record_invalid')
        if os.path.getsize(candidate) != size:
            raise ManagerError('A wheel RECORD size does not match.', 'record_invalid')
        digest = hashlib.new(algorithm)
        with open(candidate, 'rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
        actual = base64.urlsafe_b64encode(digest.digest()).rstrip(b'=').decode('ascii')
        if actual != value:
            raise ManagerError('A wheel RECORD hash does not match.', 'record_invalid')
        owners.add(os.path.relpath(candidate, site).replace(os.sep, '/'))
    return metadata_path, owners


def validate_pth(path):
    try:
        lines = Path(path).read_text(encoding='utf-8').splitlines()
    except (OSError, UnicodeError) as error:
        raise ManagerError('A package path file is unreadable.', 'startup_code_forbidden') from error
    for line in lines:
        value = line.strip()
        if not value or value.startswith('#'):
            continue
        if value.startswith(('import ', 'import\t')):
            raise ManagerError(
                os.path.basename(path) + ' executes during Python startup and is not allowed.',
                'startup_code_forbidden',
            )
        if os.path.isabs(value) or '..' in value.replace('\\', '/').split('/'):
            raise ManagerError(
                os.path.basename(path) + ' points outside system site-packages.',
                'startup_code_forbidden',
            )


def collect_staged_distributions(site, previous_state):
    distributions = distributions_at([site])
    if not distributions and any(Path(site).iterdir()):
        raise ManagerError('Installed wheels contain no distribution metadata.', 'metadata_missing')
    packages = []
    owners = {}
    seen = set()
    managed_before = set(package_records(previous_state))
    protected = {
        normalise_name(distribution.metadata.get('Name'))
        for distribution in distributions_at([site_packages(), image_catalogue()])
        if normalise_name(distribution.metadata.get('Name')) not in managed_before
    }
    for distribution in distributions:
        name = normalise_name(distribution.metadata.get('Name'))
        if name in seen:
            raise ManagerError('The resolver produced a duplicate package.', 'duplicate_module')
        if name in protected:
            raise ManagerError(
                name + ' would replace an essential T1OS package.',
                'protected_collision',
            )
        seen.add(name)
        metadata_path, paths = verify_distribution_record(site, distribution)
        for relative in paths:
            owners.setdefault(relative, set()).add(name)
        packages.append({
            'name': name,
            'display_name': str(distribution.metadata.get('Name') or name),
            'version': str(distribution.version),
            'imports': distribution_imports(distribution),
            'requires': [str(item) for item in (distribution.requires or [])],
            'dist_info': os.path.relpath(metadata_path, site).replace(os.sep, '/'),
            'native': False,
            'catalogue_files': [],
            'installer': 't1os-python',
        })
    packages.sort(key=lambda item: item['name'])
    return distributions, packages, owners


def validate_staged_paths(site, owners, previous_state):
    base_software, _ = protected_paths()
    prefix = 'lib/' + python_library() + '/site-packages/'
    managed_before = {
        (item.get('area'), item.get('path'))
        for item in previous_state.get('files', [])
    }
    for record in file_manifest(site):
        relative = record['path']
        lowered = relative.casefold()
        if lowered.endswith(DISALLOWED_SUFFIXES):
            raise ManagerError(
                os.path.basename(relative) + ' is not supported by T1OS Python.',
                'startup_code_forbidden',
            )
        if lowered.endswith('.pth'):
            validate_pth(os.path.join(site, relative.replace('/', os.sep)))
        if prefix + relative in base_software and ('site', relative) not in managed_before:
            raise ManagerError(
                relative + ' would replace protected system Python code.',
                'protected_collision',
            )
        first = relative.split('/', 1)[0]
        stem = first[:-3] if first.endswith('.py') else first
        if stem in sys.stdlib_module_names or stem in DISALLOWED_TOP_LEVEL:
            raise ManagerError(
                stem + ' would replace protected system Python code.',
                'protected_collision',
            )
        if relative not in owners:
            raise ManagerError(
                relative + ' is not owned by a wheel RECORD.',
                'unowned_file',
            )


def patch_native_payload(site, catalogue_stage, owners, packages):
    os.makedirs(catalogue_stage, exist_ok=True)
    package_by_name = {item['name']: item for item in packages}
    native_site = []
    relocation_by_name = {}
    initial_manifest = file_manifest(site)
    python_sources = [
        os.path.join(site, record['path'].replace('/', os.sep))
        for record in initial_manifest if record['path'].endswith('.py')
    ]
    for record in initial_manifest:
        relative = record['path']
        path = os.path.join(site, relative.replace('/', os.sep))
        if not is_elf(path):
            continue
        validate_elf_header(path)
        file_owners = set(owners.get(relative, ()))
        if not file_owners:
            raise ManagerError('A native file has no package owner.', 'unowned_file')
        if native_library_candidate(relative, path):
            old_names = {os.path.basename(relative)}
            soname = elf_soname(path)
            if soname:
                old_names.add(soname)
            for source in python_sources:
                try:
                    data = Path(source).read_bytes()
                except OSError:
                    continue
                if any(name.encode('utf-8') in data for name in old_names):
                    raise ManagerError(
                        os.path.basename(relative)
                        + ' is loaded by path and requires a T1OS compatibility recipe.',
                        'native_recipe_required',
                    )
            digest = sha256(path)
            new_name = soname or os.path.basename(relative)
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._+-]{0,254}', new_name):
                raise ManagerError(
                    os.path.basename(relative) + ' has an unsafe native library name.',
                    'native_invalid',
                )
            destination = os.path.join(catalogue_stage, new_name)
            if os.path.exists(destination):
                if sha256(destination) != digest:
                    raise ManagerError(
                        new_name + ' is supplied with different native contents.',
                        'native_collision',
                    )
                os.unlink(path)
                relocation = relocation_by_name[new_name]
                relocation['owners'].update(file_owners)
                relocation['old_names'].update(old_names)
            else:
                os.replace(path, destination)
                relocation = {
                    'path': destination,
                    'name': new_name,
                    'old_names': set(old_names),
                    'owners': set(file_owners),
                }
                relocation_by_name[new_name] = relocation
            owners.pop(relative, None)
            for owner in file_owners:
                if new_name not in package_by_name[owner]['catalogue_files']:
                    package_by_name[owner]['catalogue_files'].append(new_name)
                package_by_name[owner]['native'] = True
        else:
            native_site.append((relative, path, file_owners))
            for owner in file_owners:
                package_by_name[owner]['native'] = True

    relocations = sorted(relocation_by_name.values(), key=lambda item: item['name'])
    all_native = list(native_site) + [
        ('catalogue:' + item['name'], item['path'], set(item['owners']))
        for item in relocations
    ]
    for _, path, _ in all_native:
        if elf_dynamic_layout(path)['interpreter'] is not None:
            raise ManagerError(
                os.path.basename(path)
                + ' is a native executable and requires a T1OS compatibility recipe.',
                'native_recipe_required',
            )
        needed = elf_needed(path)
        for old_name, new_name in MERGED_GLIBC.items():
            if old_name in needed:
                if not replace_needed_in_place(path, old_name, new_name):
                    raise ManagerError(
                        old_name + ' could not be merged safely into T1OS libc.',
                        'native_patch_failed',
                    )
                needed = [new_name if value == old_name else value for value in needed]
        patchelf(['--set-rpath', catalogue_path()], path, allow_empty=True)
        elf_dynamic_layout(path)
        if patchelf(['--print-rpath'], path, allow_empty=True) != catalogue_path():
            raise ManagerError('A native package RUNPATH was not patched.', 'native_patch_failed')

    providers = set()
    for provider_catalogue in provider_catalogues():
        if not os.path.isdir(provider_catalogue):
            continue
        providers.update(os.listdir(provider_catalogue))
        for entry in os.listdir(provider_catalogue):
            provider = os.path.join(provider_catalogue, entry)
            if is_elf(provider):
                try:
                    soname = elf_soname(provider)
                    if soname:
                        providers.add(soname)
                except ManagerError:
                    pass
    for item in relocations:
        providers.add(item['name'])
        soname = elf_soname(item['path'])
        if soname:
            providers.add(soname)
    unresolved = {}
    for relative, path, _ in all_native:
        missing = sorted({name for name in elf_needed(path) if name not in providers})
        if missing:
            unresolved[relative] = missing
    if unresolved:
        raise ManagerError(
            'A native package has unresolved T1OS libraries.',
            'native_closure',
            {'unresolved': unresolved},
        )
    return [{
        'path': item['path'],
        'name': item['name'],
        'old_names': sorted(item['old_names']),
        'owners': sorted(item['owners']),
    } for item in relocations]


def compile_staged(site, owners):
    command = [
        *manager_python_command(), '-I', '-B', '-m', 'compileall', '-q', '-f',
        '--invalidation-mode', 'checked-hash', '-d', site_packages(), site,
    ]
    run_command(command, COMPILE_TIMEOUT, pip_environment(), code='compile_failed')
    import importlib.util
    for record in file_manifest(site):
        relative = record['path']
        if not relative.endswith('.py'):
            continue
        source = os.path.join(site, relative.replace('/', os.sep))
        cached = importlib.util.cache_from_source(source)
        if os.path.isfile(cached):
            cached_relative = os.path.relpath(cached, site).replace(os.sep, '/')
            owners.setdefault(cached_relative, set()).update(owners.get(relative, ()))


def validate_staged_native_imports(site, catalogue_stage, packages):
    imports = sorted({
        name
        for package in packages if package.get('native')
        for name in package.get('imports', [])
        if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', str(name))
    }, key=str.casefold)
    if not imports:
        return
    libraries = [
        catalogue_stage,
        *provider_catalogues(),
        image_catalogue(),
        os.path.join(image_catalogue(), 'pillow.libs'),
    ]
    environment = pip_environment()
    environment['LD_LIBRARY_PATH'] = os.pathsep.join(
        [path for path in libraries if os.path.isdir(path)]
    )
    script = (
        'import importlib,json,sys;'
        'sys.dont_write_bytecode=True;'
        'sys.path.insert(0,sys.argv[1]);'
        'names=json.loads(sys.argv[2]);'
        '[(print("T1OS Python import",name),importlib.import_module(name)) for name in names]'
    )
    command = [
        *manager_python_command([catalogue_stage]),
        '-I', '-B', '-P', '-c', script, site, json.dumps(imports),
    ]
    run_command(
        command, IMPORT_TIMEOUT, environment,
        code='native_import_failed',
    )


def install_entry_points(site, bin_stage, distributions, owners):
    os.makedirs(bin_stage, exist_ok=True)
    bin_owners = {}
    command_launcher, _ = verified_tool('command_launcher')
    for distribution in distributions:
        name = normalise_name(distribution.metadata.get('Name'))
        for entry in distribution.entry_points:
            if entry.group not in ('console_scripts', 'gui_scripts'):
                continue
            command = str(entry.name or '').strip()
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._+-]{0,126}', command):
                raise ManagerError('A package defines an unsafe command name.', 'unsafe_script')
            module, separator, attribute = str(entry.value).partition(':')
            if not separator or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.]*', module):
                raise ManagerError('A package defines an unsupported console command.', 'unsafe_script')
            attributes = [part for part in attribute.split('.') if part]
            if not attributes or any(not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', part) for part in attributes):
                raise ManagerError('A package defines an unsupported console command.', 'unsafe_script')
            destination = os.path.join(bin_stage, command)
            if os.path.exists(destination):
                raise ManagerError(command + ' is provided by more than one package.', 'script_collision')
            shutil.copyfile(command_launcher, destination)
            os.chmod(destination, 0o755)
            bin_owners[command] = {name}

    embedded = os.path.join(site, 'bin')
    if os.path.isdir(embedded):
        for record in file_manifest(embedded):
            relative = record['path']
            source_relative = 'bin/' + relative
            file_owners = owners.pop(source_relative, set())
            if not file_owners:
                raise ManagerError(source_relative + ' has no package owner.', 'unowned_file')
            destination = os.path.join(bin_stage, relative.replace('/', os.sep))
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            if os.path.exists(destination):
                os.unlink(os.path.join(embedded, relative.replace('/', os.sep)))
                continue
            # pip's generated text wrapper cannot express `/the one` in a
            # Linux shebang. Replace it with the locked native dispatcher.
            os.unlink(os.path.join(embedded, relative.replace('/', os.sep)))
            shutil.copyfile(command_launcher, destination)
            os.chmod(destination, 0o755)
            bin_owners[relative] = set(file_owners)
        shutil.rmtree(embedded)
    return bin_owners


def finalise_metadata(
    site, catalogue_stage, bin_stage, distributions, packages, owners,
    catalogue_owners, bin_owners, requested,
):
    requested_names = {normalise_name(item['name']) for item in requested}
    package_paths = {item['name']: {'site': set(), 'bin': set(), 'catalogue': set()} for item in packages}
    for relative, file_owners in owners.items():
        for owner in file_owners:
            package_paths[owner]['site'].add(relative)
    for relative, file_owners in bin_owners.items():
        for owner in file_owners:
            package_paths[owner]['bin'].add(relative)
    for relative, file_owners in catalogue_owners.items():
        for owner in file_owners:
            package_paths[owner]['catalogue'].add(relative)

    for distribution in distributions:
        name = normalise_name(distribution.metadata.get('Name'))
        dist_info = os.path.abspath(str(distribution._path))
        installer = os.path.join(dist_info, 'INSTALLER')
        atomic_bytes(installer, b't1os-python\n')
        owners.setdefault(os.path.relpath(installer, site).replace(os.sep, '/'), set()).add(name)
        package_paths[name]['site'].add(os.path.relpath(installer, site).replace(os.sep, '/'))
        requested_file = os.path.join(dist_info, 'REQUESTED')
        requested_relative = os.path.relpath(requested_file, site).replace(os.sep, '/')
        if name in requested_names:
            atomic_bytes(requested_file, b'')
            owners.setdefault(requested_relative, set()).add(name)
            package_paths[name]['site'].add(requested_relative)
        elif os.path.exists(requested_file):
            os.unlink(requested_file)
            owners.pop(requested_relative, None)
            package_paths[name]['site'].discard(requested_relative)
        transformation = os.path.join(dist_info, 'T1OS.json')
        record = next(item for item in packages if item['name'] == name)
        atomic_json(transformation, {
            'format': 1,
            'installer': 't1os-python',
            'site_packages': site_packages(),
            'catalogue': catalogue_path(),
            'native': bool(record.get('native')),
            'catalogue_files': sorted(record.get('catalogue_files', [])),
        })
        transformation_relative = os.path.relpath(transformation, site).replace(os.sep, '/')
        owners.setdefault(transformation_relative, set()).add(name)
        package_paths[name]['site'].add(transformation_relative)

    # Recreate installed RECORDs after T1OS has moved and patched native files.
    for distribution in distributions:
        name = normalise_name(distribution.metadata.get('Name'))
        dist_info = os.path.abspath(str(distribution._path))
        record_path = os.path.join(dist_info, 'RECORD')
        record_relative = os.path.relpath(record_path, site).replace(os.sep, '/')
        owners.setdefault(record_relative, set()).add(name)
        package_paths[name]['site'].add(record_relative)
        rows = []
        for relative in package_paths[name]['site']:
            rows.append((relative, os.path.join(site, relative.replace('/', os.sep))))
        for relative in package_paths[name]['bin']:
            rows.append((
                os.path.join(python_bin(), relative.replace('/', os.sep)).replace(os.sep, '/'),
                os.path.join(bin_stage, relative.replace('/', os.sep)),
            ))
        for relative in package_paths[name]['catalogue']:
            rows.append((
                os.path.join(catalogue_path(), relative).replace(os.sep, '/'),
                os.path.join(catalogue_stage, relative),
            ))
        update_record(record_path, rows)

    file_records = []
    for area, root, mapping in (
        ('site', site, owners),
        ('bin', bin_stage, bin_owners),
    ):
        actual = {item['path']: item for item in file_manifest(root)}
        if set(actual) != set(mapping):
            missing = sorted(set(actual) ^ set(mapping))
            raise ManagerError('Package ownership is incomplete.', 'unowned_file', {'paths': missing[:50]})
        for relative, record in actual.items():
            file_records.append({
                'area': area,
                'path': relative,
                'size': record['size'],
                'sha256': record['sha256'],
                'owners': sorted(mapping[relative]),
            })
    catalogue_records = []
    actual_catalogue = {item['path']: item for item in file_manifest(catalogue_stage)}
    if set(actual_catalogue) != set(catalogue_owners):
        raise ManagerError('Native catalogue ownership is incomplete.', 'unowned_file')
    for relative, record in actual_catalogue.items():
        catalogue_records.append({
            'path': relative,
            'size': record['size'],
            'sha256': record['sha256'],
            'owners': sorted(catalogue_owners[relative]),
        })
    file_records.sort(key=lambda item: (item['area'], item['path']))
    catalogue_records.sort(key=lambda item: item['path'])
    return file_records, catalogue_records


def toml_string(value):
    return json.dumps(str(value), ensure_ascii=False)


def write_pylock(path, requested, artifacts):
    lines = [
        'format = 1',
        'python = ' + toml_string('.'.join(map(str, sys.version_info[:3]))),
        'abi = ' + toml_string(f'cp{sys.version_info.major}{sys.version_info.minor}'),
        '',
    ]
    for item in sorted(requested, key=lambda value: normalise_name(value['name'])):
        lines.extend([
            '[[requested]]',
            'name = ' + toml_string(normalise_name(item['name'])),
            'requirement = ' + toml_string(item.get('requirement') or item['name']),
            'pinned = ' + ('true' if item.get('pinned') else 'false'),
            'kind = ' + toml_string(item.get('kind') or 'index'),
            '',
        ])
    for item in sorted(artifacts, key=lambda value: normalise_name(value['name'])):
        lines.extend([
            '[[artifact]]',
            'name = ' + toml_string(normalise_name(item['name'])),
            'version = ' + toml_string(item['version']),
            'url = ' + toml_string(item['url']),
            'sha256 = ' + toml_string(item['sha256']),
            '',
        ])
    atomic_bytes(path, ('\n'.join(lines).rstrip() + '\n').encode('utf-8'))


def read_pylock(path):
    try:
        import tomllib
        with open(path, 'rb') as stream:
            value = tomllib.load(stream)
    except (OSError, ValueError, TypeError) as error:
        raise ManagerError('The Python lock file is unreadable: ' + str(error), 'lock_invalid') from error
    if not isinstance(value, dict) or int(value.get('format', 0)) != 1:
        raise ManagerError('The Python lock file has an unsupported format.', 'lock_invalid')
    abi = f'cp{sys.version_info.major}{sys.version_info.minor}'
    if str(value.get('abi') or '') != abi:
        raise ManagerError('The Python lock file is for another Python ABI.', 'lock_invalid')
    requested = []
    for raw in value.get('requested', []):
        if not isinstance(raw, dict):
            raise ManagerError('The Python lock file is malformed.', 'lock_invalid')
        name = normalise_name(raw.get('name'))
        requested.append({
            'name': name,
            'requirement': str(raw.get('requirement') or name),
            'pinned': bool(raw.get('pinned')),
            'kind': str(raw.get('kind') or 'index'),
        })
    artifacts = []
    for raw in value.get('artifact', []):
        if not isinstance(raw, dict):
            raise ManagerError('The Python lock file is malformed.', 'lock_invalid')
        digest = str(raw.get('sha256') or '').lower()
        if not HASH.fullmatch(digest):
            raise ManagerError('The Python lock file has an invalid hash.', 'lock_invalid')
        artifacts.append({
            'name': normalise_name(raw.get('name')),
            'version': exact_version(raw.get('version')),
            'url': str(raw.get('url') or ''),
            'sha256': digest,
        })
    artifact_versions = {
        item['name']: item['version'] for item in artifacts
    }
    for item in requested:
        if item.get('kind') == 'wheel':
            version = artifact_versions.get(item['name'])
            if not version:
                raise ManagerError(
                    'A local-wheel lock is missing its artifact.',
                    'lock_invalid')
            # Imported locks deliberately contain no privileged cache path.
            # Preserve the exact distribution version as an index request;
            # this transaction still consumes the lock's hashed artifact URL.
            item.update({
                'kind': 'index',
                'pinned': True,
                'requirement': item['name'] + '==' + version,
            })
    return requested, artifacts


def locked_artifact_argument(item):
    url = str(item.get('url') or '')
    digest = str(item.get('sha256') or '').lower()
    if not HASH.fullmatch(digest):
        raise ManagerError('A locked artifact hash is invalid.', 'lock_invalid')
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ('https', 'file'):
        raise ManagerError('A locked artifact uses an unsafe URL.', 'lock_invalid')
    return url.split('#', 1)[0] + '#sha256=' + digest


def staged_modules(packages):
    return [{
        'name': item['name'],
        'display_name': item['display_name'],
        'version': item['version'],
        'requires': list(item.get('requires', [])),
    } for item in packages]


def resolve_environment(requested, previous_state, locked_artifacts=None, operation='install'):
    ensure_store()
    transaction = uuid.uuid4().hex
    root = os.path.join(transactions_path(), transaction)
    site = os.path.join(root, 'site')
    catalogue_stage = os.path.join(root, 'catalogue')
    bin_stage = os.path.join(root, 'bin')
    os.makedirs(site, exist_ok=False)
    os.makedirs(catalogue_stage)
    os.makedirs(bin_stage)
    set_progress(operation, 'resolving wheels', transaction)
    report_path = os.path.join(root, 'pip-report.json')
    pip_path, configuration = verified_pip()
    requested = sorted((dict(item) for item in requested), key=lambda item: normalise_name(item['name']))
    artifacts = []
    try:
        arguments = []
        if locked_artifacts:
            arguments = [locked_artifact_argument(item) for item in locked_artifacts]
        else:
            arguments = [requirement_argument(item) for item in requested]
        if arguments:
            command = private_pip_command(
                pip_path,
                'install', '--isolated', '--disable-pip-version-check', '--no-input',
                '--only-binary=:all:', '--no-compile', '--target', site,
                '--report', report_path, '--cache-dir', cache_path(),
                '--index-url', str(configuration.get('index_url') or INDEX_URL),
                *(('--no-deps',) if locked_artifacts else ()),
                *arguments,
            )
            run_command(command, PIP_TIMEOUT, pip_environment(), code='resolution_failed')
            report = read_json(report_path, {}) or {}
            artifacts = report_artifacts(report)
        distributions, packages, owners = collect_staged_distributions(site, previous_state)
        validate_staged_paths(site, owners, previous_state)
        actual = {(item['name'], item['version'], item['sha256']) for item in artifacts}
        if locked_artifacts:
            expected = {
                (normalise_name(item['name']), str(item['version']), str(item['sha256']).lower())
                for item in locked_artifacts
            }
            if actual != expected:
                raise ManagerError('The locked wheel set did not reproduce exactly.', 'lock_mismatch')
        artifact_by_name = {item['name']: item for item in artifacts}
        requested_names = {normalise_name(item['name']) for item in requested}
        for package in packages:
            package['artifact'] = dict(artifact_by_name.get(package['name'], {}))
            package['requested'] = package['name'] in requested_names
            request = next((item for item in requested if normalise_name(item['name']) == package['name']), {})
            package['pinned'] = bool(request.get('pinned'))
        set_progress(operation, 'patching native libraries', transaction)
        relocations = patch_native_payload(site, catalogue_stage, owners, packages)
        catalogue_owners = {
            item['name']: set(item['owners']) for item in relocations
        }
        set_progress(operation, 'compiling checked bytecode', transaction)
        compile_staged(site, owners)
        set_progress(operation, 'testing native imports', transaction)
        validate_staged_native_imports(site, catalogue_stage, packages)
        bin_owners = install_entry_points(site, bin_stage, distributions, owners)
        files, catalogue_files = finalise_metadata(
            site, catalogue_stage, bin_stage, distributions, packages, owners,
            catalogue_owners, bin_owners, requested,
        )
        system_modules = [
            item for item in installed_modules()[1]
            if item.get('system')
        ]
        problems = dependency_problems(system_modules + staged_modules(packages))
        if problems:
            raise ManagerError(
                'The resolved packages have unsatisfied dependencies.',
                'dependency_conflict', {'problems': problems},
            )
        lock_path = os.path.join(root, 'pylock.toml')
        write_pylock(lock_path, requested, artifacts)
        new_state = {
            'format': STATE_FORMAT,
            'python_version': '.'.join(map(str, sys.version_info[:3])),
            'transaction': transaction,
            'requested': requested,
            'artifacts': artifacts,
            'packages': packages,
            'files': files,
            'catalogue_files': catalogue_files,
            'updated_at': time.time(),
        }
        validate_state(new_state)
        return {
            'transaction': transaction,
            'root': root,
            'site': site,
            'bin': bin_stage,
            'catalogue': catalogue_stage,
            'lock': lock_path,
            'state': new_state,
        }
    except Exception:
        set_progress(operation, 'failed', transaction)
        safe_remove_tree(root, transactions_path())
        raise


def area_root(area):
    roots = {
        'site': site_packages(),
        'bin': python_bin(),
        'catalogue': catalogue_path(),
    }
    try:
        return roots[area]
    except KeyError as error:
        raise ManagerError('Package state names an unknown installation area.', 'state_invalid') from error


def state_file_map(state):
    records = {}
    for item in state.get('files', []):
        area = str(item.get('area') or '')
        relative = safe_relative(item.get('path'))
        records[(area, relative)] = item
    for item in state.get('catalogue_files', []):
        relative = safe_relative(item.get('path'))
        records[('catalogue', relative)] = item
    return records


def prune_empty_parents(path, root):
    parent = os.path.dirname(path)
    root = os.path.realpath(root)
    while contained(parent, root) and os.path.realpath(parent) != root:
        try:
            os.rmdir(parent)
        except OSError:
            return
        parent = os.path.dirname(parent)


def journal_write(path, value):
    atomic_json(path, value, 0o600)


def recover_transactions(_service=False):
    if not _service:
        raise ManagerError(
            'Python transaction recovery is restricted to service startup.',
            'operation_denied')
    ensure_store()
    live = load_state()
    for name in sorted(os.listdir(transactions_path())):
        root = os.path.join(transactions_path(), name)
        if not os.path.isdir(root) or os.path.islink(root):
            continue
        journal_path = os.path.join(root, 'journal.json')
        journal = read_json(journal_path, None)
        if not isinstance(journal, dict):
            safe_remove_tree(root, transactions_path())
            continue
        if str(live.get('transaction') or '') == str(journal.get('transaction') or ''):
            safe_remove_tree(root, transactions_path())
            continue
        # Planned actions are persisted before the first rename.  Recovery
        # therefore covers a crash between an individual rename and the next
        # journal fsync, not merely actions whose completion was recorded.
        for action in reversed(journal.get('planned_new', journal.get('installed', []))):
            area = action['area']
            relative = safe_relative(action['path'])
            target = os.path.join(area_root(area), relative.replace('/', os.sep))
            staged = os.path.join(root, area, relative.replace('/', os.sep))
            # A still-present staged file proves its corresponding live rename
            # had not happened.  This distinction matters when old and new
            # bytes happen to have the same digest.
            if os.path.isfile(staged):
                continue
            expected = str(action.get('sha256') or '')
            if not os.path.isfile(target) or (expected and sha256(target) != expected):
                raise ManagerError(
                    'Interrupted Python transaction contains an unexpected live file: '
                    + relative, 'recovery_required',
                )
            os.unlink(target)
            prune_empty_parents(target, area_root(area))
        for action in reversed(journal.get('planned_old', journal.get('backed_up', []))):
            area = action['area']
            relative = safe_relative(action['path'])
            backup = os.path.join(root, 'backup', area, relative.replace('/', os.sep))
            target = os.path.join(area_root(area), relative.replace('/', os.sep))
            if os.path.isfile(backup):
                expected = str(action.get('sha256') or '')
                if expected and sha256(backup) != expected:
                    raise ManagerError(
                        'Interrupted Python transaction backup is damaged: ' + relative,
                        'recovery_required',
                    )
                if os.path.lexists(target):
                    raise ManagerError(
                        'Interrupted Python transaction cannot restore: ' + relative,
                        'recovery_required',
                    )
                os.makedirs(os.path.dirname(target), exist_ok=True)
                os.replace(backup, target)
        safe_remove_tree(root, transactions_path())


def commit_environment(stage, operation):
    old_state = load_state()
    new_state = validate_state(stage['state'])
    old_files = state_file_map(old_state)
    new_files = state_file_map(new_state)
    root = stage['root']
    journal_path = os.path.join(root, 'journal.json')
    journal = {
        'format': 1,
        'transaction': stage['transaction'],
        'operation': operation,
        'state': 'prepared',
        'planned_old': [
            {
                'area': area, 'path': relative,
                'sha256': old_files[(area, relative)]['sha256'],
            }
            for area, relative in sorted(old_files)
        ],
        'planned_new': [
            {
                'area': area, 'path': relative,
                'sha256': new_files[(area, relative)]['sha256'],
            }
            for area, relative in sorted(new_files)
        ],
        'backed_up': [],
        'installed': [],
    }
    # Refuse to build on top of files changed outside the Python module manager.
    for (area, relative), record in old_files.items():
        target = os.path.join(area_root(area), relative.replace('/', os.sep))
        if not os.path.isfile(target) or os.path.islink(target) or sha256(target) != record['sha256']:
            raise ManagerError(
                relative + ' changed outside the Python module manager. Run repair or restore it first.',
                'managed_file_changed',
            )
    for area, relative in new_files:
        target = os.path.join(area_root(area), relative.replace('/', os.sep))
        if os.path.lexists(target) and (area, relative) not in old_files:
            raise ManagerError(relative + ' collides with an existing system file.', 'protected_collision')
    journal_write(journal_path, journal)
    switched = False
    try:
        set_progress(operation, 'committing files', stage['transaction'])
        for area, relative in sorted(old_files):
            target = os.path.join(area_root(area), relative.replace('/', os.sep))
            backup = os.path.join(root, 'backup', area, relative.replace('/', os.sep))
            os.makedirs(os.path.dirname(backup), exist_ok=True)
            os.replace(target, backup)
            journal['backed_up'].append({'area': area, 'path': relative})
            journal_write(journal_path, journal)
            prune_empty_parents(target, area_root(area))
        for (area, relative), record in sorted(new_files.items()):
            source = os.path.join(stage[area], relative.replace('/', os.sep))
            target = os.path.join(area_root(area), relative.replace('/', os.sep))
            if not os.path.isfile(source) or sha256(source) != record['sha256']:
                raise ManagerError('A staged package file changed before commit.', 'staging_changed')
            os.makedirs(os.path.dirname(target), exist_ok=True)
            os.replace(source, target)
            journal['installed'].append({'area': area, 'path': relative})
            journal_write(journal_path, journal)
        atomic_json(previous_path(), old_state)
        shutil.copyfile(stage['lock'], os.path.join(management_root(), 'pylock.toml'))
        atomic_json(state_path(), new_state)
        switched = True
        journal['state'] = 'committed'
        journal_write(journal_path, journal)
        append_history({
            'time': time.time(),
            'operation': operation,
            'result': 'committed',
            'transaction': stage['transaction'],
            'packages': len(new_state['packages']),
        })
    except Exception:
        if not switched:
            for action in reversed(journal['installed']):
                target = os.path.join(area_root(action['area']), action['path'].replace('/', os.sep))
                try:
                    os.unlink(target)
                    prune_empty_parents(target, area_root(action['area']))
                except OSError:
                    pass
            for action in reversed(journal['backed_up']):
                area = action['area']
                relative = action['path']
                backup = os.path.join(root, 'backup', area, relative.replace('/', os.sep))
                target = os.path.join(area_root(area), relative.replace('/', os.sep))
                if os.path.isfile(backup):
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    os.replace(backup, target)
        append_history({
            'time': time.time(), 'operation': operation, 'result': 'failed',
            'transaction': stage['transaction'],
        })
        raise
    finally:
        if switched or os.path.isdir(root):
            try:
                safe_remove_tree(root, transactions_path())
            except OSError:
                if not switched:
                    raise
    return new_state


def replace_environment(requested, operation, locked_artifacts=None):
    with TRANSACTION_LOCK:
        old_state = load_state()
        stage = resolve_environment(requested, old_state, locked_artifacts, operation)
        state = commit_environment(stage, operation)
        try:
            prune_unused_cache()
        except Exception as error:
            # Cache housekeeping is deliberately automatic and must not turn
            # an already committed package transaction into a reported
            # failure. Preserve the package result and leave diagnostic detail
            # in the service log for recovery tooling.
            print(
                f'> Python automatic cache cleanup failed: {error}',
                file=sys.stderr,
            )
        return state


def state_health(state):
    problems = []
    for (area, relative), record in state_file_map(state).items():
        target = os.path.join(area_root(area), relative.replace('/', os.sep))
        if not os.path.isfile(target) or os.path.islink(target):
            problems.append(relative + ' is missing')
        elif sha256(target) != record['sha256']:
            problems.append(relative + ' has changed')
    try:
        problems.extend(dependency_problems(installed_modules()[1]))
    except ManagerError as error:
        problems.append(str(error))
    return sorted(set(problems), key=str.casefold)


def operation_result(state, message):
    return {
        'message': message,
        'transaction': state.get('transaction') or '',
        'packages': len(state.get('packages', [])),
        'requested': len(state.get('requested', [])),
        'restart': 'Restart programs which already imported the changed modules.',
    }


def request_item(name, version='', pinned=False, kind='index', path=''):
    name = normalise_name(name)
    requirement = name
    if version:
        requirement += '==' + exact_version(version)
    item = {
        'name': name,
        'requirement': requirement,
        'pinned': bool(pinned or version),
        'kind': str(kind),
    }
    if path:
        item['path'] = path
    return item


def wheel_request(path):
    cached, digest = copy_local_wheel(path)
    _, _, _, _, _ = packaging_api()
    try:
        from pip._vendor.packaging.utils import parse_wheel_filename
        name, version, _, _ = parse_wheel_filename(os.path.basename(cached))
    except Exception as error:
        raise ManagerError('The wheel filename is invalid.', 'wheel_invalid') from error
    return {
        'name': normalise_name(str(name)),
        'requirement': normalise_name(str(name)),
        'pinned': True,
        'kind': 'wheel',
        'path': cached,
        'wheel_sha256': digest,
        'version': str(version),
    }


def wheel_request_descriptor(descriptor, arguments):
    cached, digest = copy_descriptor_wheel(descriptor, arguments)
    _, _, _, _, _ = packaging_api()
    try:
        from pip._vendor.packaging.utils import parse_wheel_filename
        name, version, _, _ = parse_wheel_filename(os.path.basename(cached))
    except Exception as error:
        raise ManagerError('The wheel filename is invalid.', 'wheel_invalid') from error
    return {
        'name': normalise_name(str(name)),
        'requirement': normalise_name(str(name)),
        'pinned': True,
        'kind': 'wheel',
        'path': cached,
        'wheel_sha256': digest,
        'version': str(version),
    }


def requested_for_install(arguments):
    state = load_state()
    mapping = requested_mapping(state)
    # Index installation accepts only a normalized project identity. Local
    # wheels use the separate SCM_RIGHTS descriptor operation.
    item = request_item(
        arguments.get('name'), arguments.get('version') or '', False, 'index',
    )
    mapping[item['name']] = item
    return list(mapping.values())


def op_status(arguments):
    state, modules = installed_modules()
    problems = state_health(state)
    managed = [item for item in modules if not item['system']]
    system = [item for item in modules if item['system']]
    return {
        'core': core_identity(),
        # Authority is request-scoped and process-bound; it is intentionally
        # not represented as a global system role.
        'authorization': 'request-scoped',
        'health': 'healthy' if not problems else 'needs attention',
        'problems': problems,
        'generation': state.get('transaction') or 'base',
        'transaction': progress(),
        'system_modules': len(system),
        'managed_modules': len(managed),
        'managed_files': len(state.get('files', [])),
        'native_libraries': len(state.get('catalogue_files', [])),
        'install_location': site_packages(),
    }


def op_list_modules(arguments):
    return {'modules': installed_modules()[1]}


def op_show_module(arguments):
    name = normalise_name(arguments.get('name'))
    modules = [item for item in installed_modules()[1] if item['name'] == name]
    if not modules:
        raise ManagerError(name + ' is not installed.', 'module_missing')
    return {'modules': modules}


def pypi_project(name):
    name = normalise_name(name)
    configuration = read_json(tools_configuration(), {}) or {}
    template = str(configuration.get('project_json_url') or PROJECT_JSON_URL)
    if template.count('{name}') != 1:
        raise ManagerError('The Python project catalogue URL is invalid.', 'tool_invalid')
    url = template.replace('{name}', urllib.parse.quote(name))
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ('https', 'file') or parsed.username or parsed.password:
        raise ManagerError('The Python project catalogue URL is unsafe.', 'tool_invalid')
    request = urllib.request.Request(url, headers={'User-Agent': 'T1OS-Python/1'})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise ManagerError(name + ' was not found on PyPI.', 'module_missing') from error
        raise ManagerError('PyPI could not be reached.', 'network_failed') from error
    except (OSError, ValueError, urllib.error.URLError) as error:
        raise ManagerError('PyPI could not be reached: ' + str(error), 'network_failed') from error


def compatible_wheel(filename):
    value = str(filename or '').lower()
    if not value.endswith('.whl'):
        return False
    python_tag = f'cp{sys.version_info.major}{sys.version_info.minor}'
    return (
        (python_tag in value or 'abi3' in value or 'py3-none-any' in value)
        and ('manylinux' in value or 'linux_x86_64' in value or 'none-any' in value)
        and ('x86_64' in value or 'none-any' in value)
    )


def project_versions(project):
    values = []
    compatible = 0
    for version, files in (project.get('releases') or {}).items():
        matched = [item for item in files if compatible_wheel(item.get('filename')) and not item.get('yanked')]
        if matched:
            values.append(str(version))
            compatible += len(matched)
    _, Version, InvalidVersion, _, _ = packaging_api()
    parsed = []
    for value in values:
        try:
            parsed.append((Version(value), value))
        except InvalidVersion:
            pass
    parsed.sort(reverse=True)
    return [value for _, value in parsed], compatible


def op_find_module(arguments):
    project = pypi_project(arguments.get('name'))
    versions, compatible = project_versions(project)
    info = project.get('info') or {}
    return {
        'name': str(info.get('name') or arguments.get('name')),
        'summary': str(info.get('summary') or ''),
        'latest': versions[0] if versions else '',
        'versions': versions,
        'compatible_wheels': compatible,
    }


def op_list_updates(arguments):
    state, modules = installed_modules()
    requests = requested_mapping(state)
    updates = []
    for item in modules:
        if item['name'] not in requests:
            continue
        try:
            found = op_find_module({'name': item['name']})
            latest = found.get('latest') or ''
        except ManagerError:
            latest = ''
        updates.append({
            'name': item['name'], 'installed': item['version'], 'latest': latest,
            'pinned': bool(requests[item['name']].get('pinned')),
            'available': bool(latest and latest != item['version']),
        })
    return {'updates': updates}


def op_install_module(arguments):
    state = replace_environment(requested_for_install(arguments), 'install')
    return operation_result(state, 'Python module installed.')


def op_install_wheel(arguments, descriptor):
    state = load_state()
    mapping = requested_mapping(state)
    item = wheel_request_descriptor(descriptor, arguments)
    mapping[item['name']] = item
    result = replace_environment(list(mapping.values()), 'install wheel')
    return operation_result(result, 'Python wheel installed.')


def change_requested(name, action):
    state = load_state()
    mapping = requested_mapping(state)
    name = normalise_name(name)
    packages = package_records(state)
    if action == 'remove':
        if name not in mapping:
            raise ManagerError(name + ' was installed as a dependency; remove its requesting module.', 'not_requested')
        del mapping[name]
    elif action in ('pin', 'unpin', 'update'):
        if name not in mapping or name not in packages:
            raise ManagerError(name + ' is not a requested module.', 'not_requested')
        item = mapping[name]
        if action == 'pin':
            item.update({
                'requirement': name + '==' + exact_version(packages[name]['version']),
                'pinned': True, 'kind': 'index',
            })
            item.pop('path', None)
        elif action == 'unpin':
            item.update({'requirement': name, 'pinned': False, 'kind': 'index'})
            item.pop('path', None)
        elif action == 'update' and not item.get('pinned'):
            item.update({'requirement': name, 'kind': 'index'})
            item.pop('path', None)
    return list(mapping.values())


def op_remove_module(arguments):
    state = replace_environment(change_requested(arguments.get('name'), 'remove'), 'remove')
    return operation_result(state, 'Python module removed.')


def op_pin_module(arguments):
    state = replace_environment(change_requested(arguments.get('name'), 'pin'), 'pin')
    return operation_result(state, 'Python module pinned.')


def op_unpin_module(arguments):
    state = replace_environment(change_requested(arguments.get('name'), 'unpin'), 'unpin')
    return operation_result(state, 'Python module unpinned.')


def op_update_module(arguments):
    state = replace_environment(change_requested(arguments.get('name'), 'update'), 'update')
    return operation_result(state, 'Python module updated.')


def op_update_modules(arguments):
    state = load_state()
    requested = []
    packages = package_records(state)
    for item in requested_mapping(state).values():
        if item.get('pinned') and item['name'] in packages:
            item['requirement'] = item['name'] + '==' + packages[item['name']]['version']
        elif item.get('kind') != 'wheel':
            item['requirement'] = item['name']
        requested.append(item)
    result = replace_environment(requested, 'update all')
    return operation_result(result, 'Python modules updated.')


def op_repair_modules(arguments):
    state = load_state()
    result = replace_environment(
        state.get('requested', []), 'repair', state.get('artifacts', []),
    )
    return operation_result(result, 'Python modules repaired from their exact lock.')


def op_restore_modules(arguments):
    previous = load_state(previous_path())
    result = replace_environment(
        previous.get('requested', []), 'restore', previous.get('artifacts', []),
    )
    return operation_result(result, 'The previous Python module set was restored.')


def op_check_modules(arguments):
    state = load_state()
    problems = state_health(state)
    if problems:
        raise ManagerError('Python module verification failed.', 'check_failed', {'problems': problems})
    return {
        'files': len(state.get('files', [])) + len(state.get('catalogue_files', [])),
        'packages': len(state.get('packages', [])),
        'problems': [],
    }


def op_history(arguments):
    return {'history': read_history(arguments.get('limit', 50))}


def op_export_lock(arguments):
    if arguments:
        raise ManagerError('Python lock export takes no path.', 'invalid_arguments')
    state = load_state()
    with tempfile.TemporaryDirectory(
            prefix='t1os-pylock-export-', dir=management_root()) as directory:
        path = os.path.join(directory, 'pylock.toml')
        write_pylock(path, state.get('requested', []), state.get('artifacts', []))
        with open(path, 'rb') as stream:
            content = stream.read(1024 * 1024 + 1)
    if len(content) > 1024 * 1024:
        raise ManagerError('Python lock export is too large.', 'response_too_large')
    return {
        'content': base64.b64encode(content).decode('ascii'),
        'sha256': hashlib.sha256(content).hexdigest(),
        'encoding': 'base64',
        'message': 'Python lock prepared for the requesting application.',
    }


def op_apply_lock(arguments, descriptor):
    content, _ = descriptor_bytes(
        descriptor, 1024 * 1024, arguments, 'Python lock',
        allow_anonymous=True)
    with tempfile.TemporaryDirectory(
            prefix='t1os-pylock-import-', dir=management_root()) as directory:
        path = os.path.join(directory, 'pylock.toml')
        atomic_bytes(path, content, mode=0o600)
        requested, artifacts = read_pylock(path)
    result = replace_environment(requested, 'apply lock', artifacts)
    return operation_result(result, 'Python lock applied.')


def prune_unused_cache():
    keep = set()
    for state in (load_state(), load_state(previous_path())):
        for item in state.get('artifacts', []):
            digest = str(item.get('sha256') or '').lower()
            if HASH.fullmatch(digest):
                keep.add(digest)
    removed = 0
    ensure_store()
    for name in os.listdir(cache_path()):
        path = os.path.join(cache_path(), name)
        if name not in keep:
            safe_remove_tree(path, cache_path())
            removed += 1
    return removed


def op_clear_cache(arguments):
    removed = prune_unused_cache()
    return {'removed': removed, 'message': 'Unused Python downloads cleared.'}


OPERATIONS = {
    'status': op_status,
    'list_modules': op_list_modules,
    'show_module': op_show_module,
    'find_module': op_find_module,
    'list_updates': op_list_updates,
    'install_module': op_install_module,
    'install_wheel': op_install_wheel,
    'remove_module': op_remove_module,
    'pin_module': op_pin_module,
    'unpin_module': op_unpin_module,
    'update_module': op_update_module,
    'update_modules': op_update_modules,
    'repair_modules': op_repair_modules,
    'restore_modules': op_restore_modules,
    'check_modules': op_check_modules,
    'history': op_history,
    'export_lock': op_export_lock,
    'apply_lock': op_apply_lock,
    'clear_cache': op_clear_cache,
}

READ_OPERATIONS = frozenset({
    'status', 'list_modules', 'show_module', 'find_module', 'list_updates',
    'check_modules', 'history', 'export_lock',
})
MUTATION_OPERATIONS = frozenset({
    'install_module', 'remove_module', 'pin_module', 'unpin_module',
    'update_module', 'update_modules', 'repair_modules', 'restore_modules',
    'clear_cache', 'install_wheel', 'apply_lock',
})
DESCRIPTOR_OPERATIONS = frozenset({'install_wheel', 'apply_lock'})

OPERATION_ARGUMENT_KEYS = {
    'status': (frozenset(),),
    'list_modules': (frozenset(),),
    'show_module': (frozenset(('name',)),),
    'find_module': (frozenset(('name',)),),
    'list_updates': (frozenset(),),
    'install_module': (frozenset(('name',)), frozenset(('name', 'version'))),
    'install_wheel': (frozenset(('filename', 'size', 'sha256')),),
    'remove_module': (frozenset(('name',)),),
    'pin_module': (frozenset(('name',)),),
    'unpin_module': (frozenset(('name',)),),
    'update_module': (frozenset(('name',)),),
    'update_modules': (frozenset(),),
    'repair_modules': (frozenset(),),
    'restore_modules': (frozenset(),),
    'check_modules': (frozenset(),),
    'history': (frozenset(), frozenset(('limit',))),
    'export_lock': (frozenset(),),
    'apply_lock': (frozenset(('size', 'sha256')),),
    'clear_cache': (frozenset(),),
}


def dispatch(request, peer, descriptors=None):
    if not isinstance(request, dict) or int(request.get('format', 0)) != PROTOCOL:
        raise ManagerError('The Python manager request is unsupported.', 'unsupported_request')
    operation = str(request.get('operation') or '').strip()
    arguments = request.get('arguments', {})
    if operation not in OPERATIONS or not isinstance(arguments, dict):
        raise ManagerError('The Python manager operation is unknown.', 'unknown_operation')
    if frozenset(arguments) not in OPERATION_ARGUMENT_KEYS.get(operation, ()):
        raise ManagerError('The Python manager arguments are invalid.', 'invalid_arguments')
    descriptors = list(descriptors or [])
    if operation in DESCRIPTOR_OPERATIONS:
        if len(descriptors) != 1:
            raise ManagerError(
                'This operation requires exactly one file descriptor.',
                'descriptor_required')
    elif descriptors:
        raise ManagerError('This operation does not accept file descriptors.',
                           'unexpected_descriptor')
    if operation in MUTATION_OPERATIONS:
        require_architect(peer, operation, arguments)
    elif operation not in READ_OPERATIONS:
        raise ManagerError('The Python manager operation is denied.', 'operation_denied')
    try:
        if operation in DESCRIPTOR_OPERATIONS:
            data = OPERATIONS[operation](arguments, descriptors[0])
        else:
            data = OPERATIONS[operation](arguments)
    finally:
        # Resolution and commit phases update CURRENT for live status, but the
        # completed request is the sole lifecycle boundary.  Always return the
        # manager to idle after either a successful mutation or an exception.
        if operation in MUTATION_OPERATIONS:
            set_progress(running=False)
    message = str(data.get('message') or '') if isinstance(data, dict) else ''
    return {
        'format': PROTOCOL,
        'ok': True,
        'operation': operation,
        'message': message,
        'data': data if isinstance(data, dict) else {},
    }


def error_response(error, operation=''):
    if isinstance(error, ManagerError):
        code = error.code
        data = error.data
        message = str(error)
    else:
        code = 'internal_error'
        data = {}
        message = 'The Python manager encountered an internal error.'
        log(traceback.format_exc().rstrip())
    return {
        'format': PROTOCOL, 'ok': False, 'operation': str(operation),
        'code': code, 'message': message, 'data': data,
    }


def receive_request(channel):
    # Peer PID/UID/GID are captured with SO_PEERCRED immediately after accept.
    # Do not also request unsolicited credentials or security labels here:
    # those records can crowd a caller's explicit SCM_RIGHTS descriptor out of
    # the ancillary buffer without adding any authority to the request.
    for option_name in ('SO_PASSCRED', 'SO_PASSSEC'):
        option = getattr(socket, option_name, None)
        if option is None:
            continue
        try:
            channel.setsockopt(socket.SOL_SOCKET, option, 0)
        except OSError:
            pass
    payload = bytearray()
    descriptors = []
    truncation = None
    # Linux may attach SCM_CREDENTIALS or an LSM security label alongside
    # SCM_RIGHTS.  Reserve enough space for those records without exceeding
    # the comparatively small per-socket ancillary-memory limit used by the
    # VM kernel.  Asking recvmsg for a 64 KiB control buffer can itself be
    # clipped there and reported as MSG_CTRUNC before the descriptor record is
    # copied.  Four KiB comfortably covers one descriptor, credentials, and a
    # normal security label while staying below that limit.
    ancillary_space = socket.CMSG_SPACE(4 * 1024)
    try:
        while b'\n' not in payload:
            block, ancillary, flags, _ = channel.recvmsg(
                min(65536, MAXIMUM_REQUEST + 1 - len(payload)),
                ancillary_space,
            )
            for level, kind, data in ancillary:
                if level != socket.SOL_SOCKET or kind != socket.SCM_RIGHTS:
                    continue
                received = array.array('i')
                usable = len(data) - (len(data) % received.itemsize)
                received.frombytes(data[:usable])
                descriptors.extend(received.tolist())
            # VM security metadata can be larger than the bounded ancillary
            # buffer.  Linux closes any rights discarded by truncation; an
            # intact received descriptor remains safe because dispatch still
            # requires exactly one and descriptor_identity verifies it fully.
            if (flags & getattr(socket, 'MSG_CTRUNC', 0)) and not descriptors:
                detail = {
                    'flags': int(flags),
                    'control_buffer': ancillary_space,
                    'control_records': [
                        {'level': int(level), 'type': int(kind),
                         'bytes': len(data)}
                        for level, kind, data in ancillary
                    ],
                    'passcred': None,
                    'passsec': None,
                }
                for option_name, field in (
                        ('SO_PASSCRED', 'passcred'),
                        ('SO_PASSSEC', 'passsec')):
                    option = getattr(socket, option_name, None)
                    if option is not None:
                        try:
                            detail[field] = int(channel.getsockopt(
                                socket.SOL_SOCKET, option))
                        except OSError:
                            pass
                log('descriptor ancillary truncation ' + json.dumps(
                    detail, sort_keys=True, separators=(',', ':')))
                truncation = detail
            if len(descriptors) > 4:
                raise ManagerError('Too many file descriptors were supplied.',
                                   'unexpected_descriptor')
            if not block:
                break
            payload.extend(block)
            if len(payload) > MAXIMUM_REQUEST:
                raise ManagerError('The Python manager request is too large.',
                                   'request_too_large')
        line, separator, remainder = bytes(payload).partition(b'\n')
        if not line:
            raise ManagerError('The Python manager request is empty.',
                               'empty_request')
        if not separator:
            raise ManagerError('The Python manager request is incomplete.',
                               'short_request')
        try:
            request = json.loads(line.decode('utf-8'))
        except (UnicodeError, ValueError, TypeError) as error:
            raise ManagerError('The Python manager request is invalid.',
                               'invalid_request') from error
        operation = str(request.get('operation') or '') if isinstance(request, dict) else ''
        if operation == 'apply_lock' and not descriptors:
            arguments = request.get('arguments', {})
            try:
                expected = int(arguments.get('size', -1))
            except (AttributeError, TypeError, ValueError) as error:
                raise ManagerError('The Python lock stream size is invalid.',
                                   'invalid_arguments') from error
            if expected <= 0 or expected > 1024 * 1024:
                raise ManagerError('The Python lock stream size is invalid.',
                                   'invalid_arguments')
            content = bytearray(remainder)
            if len(content) > expected:
                raise ManagerError('The Python lock stream is too large.',
                                   'request_too_large')
            while len(content) < expected:
                block = channel.recv(min(65536, expected - len(content)))
                if not block:
                    raise ManagerError('The Python lock stream ended early.',
                                       'short_request')
                content.extend(block)
            with tempfile.TemporaryFile(
                    prefix='t1os-pylock-stream-',
                    dir=management_root()) as stream:
                stream.write(content)
                stream.flush()
                stream.seek(0)
                descriptors.append(os.dup(stream.fileno()))
        elif truncation is not None and not descriptors:
            raise ManagerError(
                'The Python manager descriptor was truncated.',
                'ancillary_truncated', truncation)
        return request, descriptors
    except BaseException:
        for descriptor in descriptors:
            try:
                os.close(descriptor)
            except OSError:
                pass
        raise


def handle_client(channel, peer):
    operation = ''
    descriptors = []
    try:
        request, descriptors = receive_request(channel)
        operation = str(request.get('operation') or '') if isinstance(request, dict) else ''
        response = dispatch(request, peer, descriptors)
    except Exception as error:
        response = error_response(error, operation)
    finally:
        for descriptor in descriptors:
            try:
                os.close(descriptor)
            except OSError:
                pass
    encoded = (json.dumps(response, sort_keys=True, separators=(',', ':')) + '\n').encode('utf-8')
    if len(encoded) > MAXIMUM_RESPONSE:
        encoded = (json.dumps(error_response(
            ManagerError('The Python manager response is too large.', 'response_too_large'),
            operation,
        ), separators=(',', ':')) + '\n').encode('utf-8')
    try:
        channel.sendall(encoded)
    except OSError:
        pass
    finally:
        channel.close()


def recover_transactions_for_service():
    """Boot-time recovery is an internal service action, never a client op."""

    recover_transactions(_service=True)


def prepare_socket_directory(directory):
    """Create the manager directory below a trusted, root-owned parent."""

    directory = os.path.abspath(directory)
    parent = os.path.dirname(directory)
    name = os.path.basename(directory)
    if not name or name in ('.', '..'):
        raise ManagerError('The Python manager socket directory is unsafe.',
                           'unsafe_socket')

    flags = os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0)
    nofollow = getattr(os, 'O_NOFOLLOW', 0)
    parent_descriptor = os.open(parent, flags | nofollow)
    try:
        parent_status = os.fstat(parent_descriptor)
        parent_mode = stat.S_IMODE(parent_status.st_mode)
        trusted_ephemeral = (
            parent == '/.ephemeral' and
            parent_status.st_uid == 0 and
            parent_mode == 0o1777
        )
        if (not stat.S_ISDIR(parent_status.st_mode) or
                (not trusted_ephemeral and
                 (parent_status.st_uid != 0 or parent_mode & 0o022))):
            raise ManagerError('The Python manager socket parent is unsafe.',
                               'unsafe_socket')
        try:
            os.mkdir(name, mode=0o710, dir_fd=parent_descriptor)
        except FileExistsError:
            pass
        child_status = os.stat(
            name, dir_fd=parent_descriptor, follow_symlinks=False)
        if (not stat.S_ISDIR(child_status.st_mode) or
                child_status.st_uid != 0):
            raise ManagerError('The Python manager socket directory is unsafe.',
                               'unsafe_socket')
        child_descriptor = os.open(
            name, flags | nofollow, dir_fd=parent_descriptor)
        try:
            os.fchown(child_descriptor, 0, 1000)
            os.fchmod(child_descriptor, 0o710)
        finally:
            os.close(child_descriptor)
    finally:
        os.close(parent_descriptor)


def serve():
    ensure_store()
    recover_transactions_for_service()
    path = socket_path()
    directory = os.path.dirname(path)
    prepare_socket_directory(directory)
    if os.path.lexists(path):
        status = os.lstat(path)
        if not stat.S_ISSOCK(status.st_mode):
            raise ManagerError('The Python manager socket path is unsafe.', 'unsafe_socket')
        os.unlink(path)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        listener.bind(path)
        os.chown(path, 0, 1000)
        os.chmod(path, 0o660)
        listener.listen(16)
        log('The T1OS system Python package service is ready.')
        while True:
            channel, _ = listener.accept()
            peer = peer_identity(channel)
            if peer is None:
                channel.close()
                continue
            # The ready byte is a transport barrier.  Clients do not send
            # request data or SCM_RIGHTS until the accepted socket has had all
            # unsolicited ancillary delivery disabled.  This prevents a
            # descriptor-bearing message from being queued with VM security
            # metadata before receive_request can normalize the socket.
            for option_name in ('SO_PASSCRED', 'SO_PASSSEC'):
                option = getattr(socket, option_name, None)
                if option is not None:
                    try:
                        channel.setsockopt(socket.SOL_SOCKET, option, 0)
                    except OSError:
                        pass
            try:
                channel.sendall(PROTOCOL_READY)
            except OSError:
                channel.close()
                continue
            thread = threading.Thread(
                target=handle_client, args=(channel, peer), daemon=True)
            thread.start()
    finally:
        listener.close()
        try:
            os.unlink(path)
        except OSError:
            pass


def diagnostic():
    state, modules = installed_modules()
    result = {
        'passed': not state_health(state),
        'core': core_identity(),
        'state': state,
        'modules': modules,
        'problems': state_health(state),
        'resolver': verified_pip()[0],
        'patchelf': patchelf_path(),
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result['passed'] else 1


def selected_entry_point(command):
    """Return the one installed console or GUI entry point for command."""

    matches = []
    for group in ('console_scripts', 'gui_scripts'):
        matches.extend(importlib.metadata.entry_points(group=group, name=command))
    if len(matches) != 1:
        if not matches:
            raise RuntimeError(command + ' is not an installed Python command.')
        raise RuntimeError(
            command + ' is provided by more than one Python package.')
    return matches[0]


def entry_point_main(argv=None):
    """Dispatch a native launcher invocation to an installed entry point."""

    values = list(sys.argv[1:] if argv is None else argv)
    if not values:
        print('T1OS Python command: missing command name', file=sys.stderr)
        return 126
    command = os.path.basename(values.pop(0))
    sys.argv = [command, *values]
    try:
        entry = selected_entry_point(command).load()
        result = entry()
        return int(result) if isinstance(result, int) else 0
    except Exception as error:
        print('T1OS Python command: ' + str(error), file=sys.stderr)
        return 1


def main(argv=None):
    values = list(sys.argv[1:] if argv is None else argv)
    if values[:1] == ['--entry-point']:
        return entry_point_main(values[1:])
    if values == ['diagnostic']:
        return diagnostic()
    if values:
        print(
            'Use python.py with no arguments, python.py diagnostic, or the '
            'locked entry-point launcher.',
            file=sys.stderr,
        )
        return 2
    try:
        serve()
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as error:
        response = error_response(error)
        log(response['message'])
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
