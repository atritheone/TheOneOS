"""Central credential, throttling, and authorization broker for T1OS.

The installed system uses the bundled libargon2 directly.  ``hashlib.scrypt``
is a versioned, bounded fallback for recovery images that do not contain that
library.  The old PBKDF2 representation is accepted only so a successful login
can migrate an existing installation.
"""

import argparse
import base64
import contextlib
import ctypes
import ctypes.util
import dataclasses
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import stat
import sys
import time
import unicodedata


FORMAT_VERSION = 1
MIN_NEW_PASSWORD_CHARS = 4
MAX_PASSWORD_CHARS = 32
MAX_PASSWORD_BYTES = 128
MAX_CREDENTIAL_BYTES = 4096

ARGON2_TIME_COST = 3
ARGON2_MEMORY_KIB = 65536
ARGON2_PARALLELISM = 1
ARGON2_HASH_BYTES = 32
ARGON2_SALT_BYTES = 16
ARGON2_TIME_BOUNDS = (2, 6)
ARGON2_MEMORY_BOUNDS = (32768, 262144)
ARGON2_PARALLELISM_BOUNDS = (1, 4)

SCRYPT_N = 32768
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_N_BOUNDS = (16384, 65536)
SCRYPT_P_BOUNDS = (1, 2)
SCRYPT_MAX_MEMORY = 128 * 1024 * 1024

LEGACY_PBKDF2_ALGORITHM = "sha256"
LEGACY_PBKDF2_ITERATIONS = 100000

AUTH_STATE_DIRECTORY = "/.ephemeral/authentication"
ATTEMPT_STATE_FILE = os.path.join(AUTH_STATE_DIRECTORY, "attempts.json")
MAX_AUTHORIZATION_TTL_SECONDS = 900
RECOVERY_ACTIONS = frozenset(("reset", "reinstall"))
SERVICE_SECRET_DIRECTORY = "/the one/master/service credentials"
MAX_SERVICE_SECRET_BYTES = 4096

_USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")
_B64_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_HEX_32_RE = re.compile(r"^[0-9a-fA-F]{32}$")
_HEX_64_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_SERVICE_RE = re.compile(r"^[a-z][a-z0-9.-]{0,63}$")

_ARGON2_LIBRARY = None
_ARGON2_LOAD_ATTEMPTED = False


class AuthenticationError(Exception):
    """Raised when authentication storage or policy cannot be used safely."""


@dataclasses.dataclass(frozen=True)
class AuthenticationResult:
    ok: bool
    username: str = ""
    retry_after: float = 0.0
    migrated: bool = False
    error: str = ""


@dataclasses.dataclass(frozen=True)
class IssuedAuthorization:
    authentication: AuthenticationResult
    token: str = ""


def canonicalize_username(value):
    """Return the only filesystem-safe account spelling accepted by T1OS."""
    if not isinstance(value, str):
        raise ValueError("username must be text")
    value = unicodedata.normalize("NFKC", value).strip()
    if not _USERNAME_RE.fullmatch(value):
        raise ValueError(
            "username must be 1-32 ASCII letters, numbers, dots, underscores, "
            "or hyphens and must start with a letter or number"
        )
    return value


def validate_new_password(password):
    data = _password_bytes(password, allow_short=False)
    return len(data)


def _password_bytes(password, *, allow_short=True):
    if not isinstance(password, str):
        raise ValueError("password must be text")
    if "\x00" in password:
        raise ValueError("password cannot contain a null character")
    if len(password) > MAX_PASSWORD_CHARS:
        raise ValueError(
            f"passwords must contain {MIN_NEW_PASSWORD_CHARS}-"
            f"{MAX_PASSWORD_CHARS} characters"
        )
    if not allow_short and len(password) < MIN_NEW_PASSWORD_CHARS:
        raise ValueError(
            f"passwords must contain {MIN_NEW_PASSWORD_CHARS}-"
            f"{MAX_PASSWORD_CHARS} characters"
        )
    encoded = password.encode("utf-8")
    if len(encoded) > MAX_PASSWORD_BYTES:
        raise ValueError("encoded password is too long")
    return encoded


def _encode_b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _decode_b64(value, *, minimum, maximum):
    if not isinstance(value, str) or not _B64_RE.fullmatch(value):
        raise ValueError("invalid base64 value")
    if len(value) > ((maximum + 2) // 3) * 4:
        raise ValueError("base64 value is too large")
    decoded = base64.b64decode(
        value + ("=" * (-len(value) % 4)), altchars=b"-_", validate=True
    )
    if not minimum <= len(decoded) <= maximum:
        raise ValueError("decoded value has an invalid length")
    if _encode_b64(decoded) != value:
        raise ValueError("base64 value is not canonical")
    return decoded


def _bounded_integer(value, minimum, maximum):
    if not isinstance(value, str) or not value.isascii() or not value.isdigit():
        raise ValueError("invalid integer")
    if len(value) > len(str(maximum)):
        raise ValueError("integer is too large")
    number = int(value, 10)
    if not minimum <= number <= maximum:
        raise ValueError("integer is outside policy bounds")
    return number


def _load_argon2():
    global _ARGON2_LIBRARY, _ARGON2_LOAD_ATTEMPTED
    if _ARGON2_LOAD_ATTEMPTED:
        return _ARGON2_LIBRARY
    _ARGON2_LOAD_ATTEMPTED = True

    candidates = [
        "/the one/software/chromium/libraries/libargon2.so.1",
        "/the one/software/chromium/lib/libargon2.so.1",
    ]
    system_candidate = ctypes.util.find_library("argon2")
    if system_candidate:
        candidates.append(system_candidate)

    for candidate in candidates:
        try:
            library = ctypes.CDLL(candidate, use_errno=True)
            function = library.argon2id_hash_raw
            function.argtypes = [
                ctypes.c_uint32,
                ctypes.c_uint32,
                ctypes.c_uint32,
                ctypes.c_void_p,
                ctypes.c_size_t,
                ctypes.c_void_p,
                ctypes.c_size_t,
                ctypes.c_void_p,
                ctypes.c_size_t,
            ]
            function.restype = ctypes.c_int
            _ARGON2_LIBRARY = library
            break
        except (AttributeError, OSError):
            continue
    return _ARGON2_LIBRARY


def argon2id_available():
    return _load_argon2() is not None


def _argon2id(password, salt, *, time_cost, memory_kib, parallelism):
    library = _load_argon2()
    if library is None:
        raise AuthenticationError("Argon2id is unavailable")
    output = (ctypes.c_ubyte * ARGON2_HASH_BYTES)()
    password_buffer = ctypes.create_string_buffer(password, len(password) + 1)
    salt_buffer = ctypes.create_string_buffer(salt, len(salt))
    result = library.argon2id_hash_raw(
        time_cost,
        memory_kib,
        parallelism,
        password_buffer,
        len(password),
        salt_buffer,
        len(salt),
        output,
        ARGON2_HASH_BYTES,
    )
    if result != 0:
        raise AuthenticationError(f"Argon2id failed with status {result}")
    return bytes(output)


def _parse_current_hash(stored):
    if not isinstance(stored, str) or len(stored) > 512 or not stored.isascii():
        raise ValueError("invalid credential representation")
    parts = stored.split("$")
    if len(parts) != 8 or parts[0] != "t1auth" or parts[1] != "v=1":
        raise ValueError("unsupported credential representation")
    if parts[2] == "kdf=argon2id":
        expected = ("m", "t", "p", "salt", "hash")
        values = parts[3:]
        if tuple(item.partition("=")[0] for item in values) != expected:
            raise ValueError("malformed Argon2id representation")
        memory = _bounded_integer(values[0].partition("=")[2], *ARGON2_MEMORY_BOUNDS)
        time_cost = _bounded_integer(values[1].partition("=")[2], *ARGON2_TIME_BOUNDS)
        parallelism = _bounded_integer(
            values[2].partition("=")[2], *ARGON2_PARALLELISM_BOUNDS
        )
        salt = _decode_b64(values[3].partition("=")[2], minimum=16, maximum=32)
        digest = _decode_b64(
            values[4].partition("=")[2],
            minimum=ARGON2_HASH_BYTES,
            maximum=ARGON2_HASH_BYTES,
        )
        return {
            "kdf": "argon2id",
            "memory": memory,
            "time": time_cost,
            "parallelism": parallelism,
            "salt": salt,
            "digest": digest,
        }
    if parts[2] == "kdf=scrypt":
        expected = ("n", "r", "p", "salt", "hash")
        values = parts[3:]
        if tuple(item.partition("=")[0] for item in values) != expected:
            raise ValueError("malformed scrypt representation")
        n = _bounded_integer(values[0].partition("=")[2], *SCRYPT_N_BOUNDS)
        if n & (n - 1):
            raise ValueError("scrypt N must be a power of two")
        r = _bounded_integer(values[1].partition("=")[2], SCRYPT_R, SCRYPT_R)
        parallelism = _bounded_integer(
            values[2].partition("=")[2], *SCRYPT_P_BOUNDS
        )
        salt = _decode_b64(values[3].partition("=")[2], minimum=16, maximum=32)
        digest = _decode_b64(values[4].partition("=")[2], minimum=32, maximum=32)
        return {
            "kdf": "scrypt",
            "n": n,
            "r": r,
            "parallelism": parallelism,
            "salt": salt,
            "digest": digest,
        }
    raise ValueError("unsupported KDF")


def _parse_legacy_hash(stored):
    if not isinstance(stored, str) or len(stored) != 111 or not stored.isascii():
        raise ValueError("invalid legacy credential representation")
    algorithm, iterations, salt_hex, digest_hex = stored.split("$")
    if algorithm != LEGACY_PBKDF2_ALGORITHM:
        raise ValueError("unsupported legacy algorithm")
    if iterations != str(LEGACY_PBKDF2_ITERATIONS):
        raise ValueError("unsupported legacy work factor")
    if not _HEX_32_RE.fullmatch(salt_hex) or not _HEX_64_RE.fullmatch(digest_hex):
        raise ValueError("malformed legacy credential")
    return bytes.fromhex(salt_hex), bytes.fromhex(digest_hex)


def validate_stored_hash(stored):
    try:
        if stored.startswith("t1auth$"):
            _parse_current_hash(stored)
        else:
            _parse_legacy_hash(stored)
        return True
    except (AttributeError, TypeError, ValueError):
        return False


def hash_password(password):
    encoded = _password_bytes(password, allow_short=False)
    salt = os.urandom(ARGON2_SALT_BYTES)
    if argon2id_available():
        digest = _argon2id(
            encoded,
            salt,
            time_cost=ARGON2_TIME_COST,
            memory_kib=ARGON2_MEMORY_KIB,
            parallelism=ARGON2_PARALLELISM,
        )
        return (
            f"t1auth$v=1$kdf=argon2id$m={ARGON2_MEMORY_KIB}"
            f"$t={ARGON2_TIME_COST}$p={ARGON2_PARALLELISM}"
            f"$salt={_encode_b64(salt)}$hash={_encode_b64(digest)}"
        )

    digest = hashlib.scrypt(
        encoded,
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=32,
        maxmem=SCRYPT_MAX_MEMORY,
    )
    return (
        f"t1auth$v=1$kdf=scrypt$n={SCRYPT_N}$r={SCRYPT_R}$p={SCRYPT_P}"
        f"$salt={_encode_b64(salt)}$hash={_encode_b64(digest)}"
    )


def verify_password(password, stored):
    try:
        encoded = _password_bytes(password, allow_short=True)
        if stored.startswith("t1auth$"):
            parsed = _parse_current_hash(stored)
            if parsed["kdf"] == "argon2id":
                actual = _argon2id(
                    encoded,
                    parsed["salt"],
                    time_cost=parsed["time"],
                    memory_kib=parsed["memory"],
                    parallelism=parsed["parallelism"],
                )
            else:
                actual = hashlib.scrypt(
                    encoded,
                    salt=parsed["salt"],
                    n=parsed["n"],
                    r=parsed["r"],
                    p=parsed["parallelism"],
                    dklen=32,
                    maxmem=SCRYPT_MAX_MEMORY,
                )
            return hmac.compare_digest(actual, parsed["digest"])

        salt, expected = _parse_legacy_hash(stored)
        actual = hashlib.pbkdf2_hmac(
            LEGACY_PBKDF2_ALGORITHM,
            encoded,
            salt,
            LEGACY_PBKDF2_ITERATIONS,
            dklen=32,
        )
        return hmac.compare_digest(actual, expected)
    except (AuthenticationError, AttributeError, TypeError, ValueError):
        return False


def password_needs_upgrade(stored):
    try:
        parsed = _parse_current_hash(stored)
    except (TypeError, ValueError):
        return validate_stored_hash(stored)
    if parsed["kdf"] == "argon2id":
        return (
            parsed["memory"] != ARGON2_MEMORY_KIB
            or parsed["time"] != ARGON2_TIME_COST
            or parsed["parallelism"] != ARGON2_PARALLELISM
        )
    return argon2id_available() or (
        parsed["n"] != SCRYPT_N
        or parsed["r"] != SCRYPT_R
        or parsed["parallelism"] != SCRYPT_P
    )


def _directory_flags():
    flags = os.O_RDONLY
    flags |= getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    return flags


def _file_flags(flags):
    return flags | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)


def _safe_component(component):
    return (
        isinstance(component, str)
        and component not in ("", ".", "..")
        and "/" not in component
        and "\\" not in component
        and "\x00" not in component
    )


def _open_secure_directory(
    path, *, create=False, final_mode=None, repair_existing=False
):
    path = os.path.abspath(path)
    if os.name != "posix":
        if create:
            os.makedirs(path, mode=final_mode or 0o700, exist_ok=True)
        if os.path.islink(path) or not os.path.isdir(path):
            raise AuthenticationError("unsafe directory")
        return os.open(path, _directory_flags())

    components = [item for item in path.split(os.sep) if item]
    descriptor = os.open(os.sep, _directory_flags())
    final_created = False
    try:
        for index, component in enumerate(components):
            if not _safe_component(component):
                raise AuthenticationError("unsafe directory component")
            is_final = index == len(components) - 1
            if create:
                try:
                    os.mkdir(
                        component,
                        (final_mode if is_final and final_mode is not None else 0o755),
                        dir_fd=descriptor,
                    )
                    if is_final:
                        final_created = True
                except FileExistsError:
                    pass
            child = os.open(component, _directory_flags(), dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        if final_mode is not None and create and components:
            if final_created or repair_existing:
                os.fchmod(descriptor, final_mode)
            status = os.fstat(descriptor)
            if (
                not stat.S_ISDIR(status.st_mode)
                or status.st_uid != os.geteuid()
                or status.st_gid != os.getegid()
                or stat.S_IMODE(status.st_mode) != final_mode
            ):
                raise AuthenticationError("unsafe directory metadata")
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _open_child_directory(parent, component, *, create=False, mode=0o700):
    if not _safe_component(component):
        raise AuthenticationError("unsafe child directory")
    if create:
        try:
            os.mkdir(component, mode, dir_fd=parent)
        except FileExistsError:
            pass
    child = os.open(component, _directory_flags(), dir_fd=parent)
    if create:
        os.fchmod(child, mode)
    return child


def _atomic_write_at(directory, name, data, *, mode=0o600):
    if not _safe_component(name) or not isinstance(data, (bytes, bytearray)):
        raise AuthenticationError("unsafe atomic write")
    temporary = f".{name}.{os.getpid()}.{secrets.token_hex(8)}.new"
    descriptor = None
    try:
        descriptor = os.open(
            temporary,
            _file_flags(os.O_WRONLY | os.O_CREAT | os.O_EXCL),
            mode,
            dir_fd=directory,
        )
        os.fchmod(descriptor, mode)
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise AuthenticationError("short atomic write")
            view = view[written:]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        os.replace(
            temporary,
            name,
            src_dir_fd=directory,
            dst_dir_fd=directory,
        )
        os.fsync(directory)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            os.unlink(temporary, dir_fd=directory)
        except FileNotFoundError:
            pass


def _read_regular_at(directory, name, *, maximum):
    if not _safe_component(name):
        raise AuthenticationError("unsafe filename")
    descriptor = os.open(name, _file_flags(os.O_RDONLY), dir_fd=directory)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > maximum:
            raise AuthenticationError("unsafe authentication file")
        chunks = []
        remaining = maximum + 1
        while remaining:
            chunk = os.read(descriptor, min(remaining, 4096))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        if len(data) > maximum:
            raise AuthenticationError("authentication file is too large")
        return data, metadata
    finally:
        os.close(descriptor)


def ensure_private_file(path):
    parent, name = os.path.split(os.path.abspath(path))
    directory = _open_secure_directory(
        parent, create=True, final_mode=0o700, repair_existing=True
    )
    try:
        try:
            descriptor = os.open(
                name,
                _file_flags(os.O_WRONLY | os.O_CREAT | os.O_EXCL),
                0o600,
                dir_fd=directory,
            )
        except FileExistsError:
            descriptor = os.open(name, _file_flags(os.O_RDONLY), dir_fd=directory)
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise AuthenticationError("credential path is not a regular file")
            os.fchmod(descriptor, 0o600)
        finally:
            os.close(descriptor)
    finally:
        os.close(directory)


def _service_secret_name(service):
    if not isinstance(service, str) or not _SERVICE_RE.fullmatch(service):
        raise ValueError("invalid service credential name")
    return service + ".secret"


def store_service_secret(service, secret, *, directory=SERVICE_SECRET_DIRECTORY):
    """Store a service credential behind root-only descriptor-relative access.

    This is intentionally a least-privilege store, not cryptographic sealing:
    T1OS does not yet have a TPM- or login-unlocked key with which unattended
    services could honestly encrypt secrets at rest.
    """
    name = _service_secret_name(service)
    if isinstance(secret, str):
        secret = secret.encode("utf-8")
    if (
        not isinstance(secret, (bytes, bytearray))
        or not 1 <= len(secret) <= MAX_SERVICE_SECRET_BYTES
        or b"\x00" in secret
    ):
        raise ValueError("invalid service credential")
    if os.name != "posix":
        directory = os.path.abspath(directory)
        os.makedirs(directory, mode=0o700, exist_ok=True)
        if os.path.islink(directory) or not os.path.isdir(directory):
            raise AuthenticationError("unsafe service credential directory")
        destination = os.path.abspath(os.path.join(directory, name))
        if os.path.commonpath((directory, destination)) != directory:
            raise AuthenticationError("unsafe service credential path")
        temporary = os.path.join(
            directory, f".{name}.{os.getpid()}.{secrets.token_hex(8)}.new"
        )
        descriptor = None
        try:
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
                0o600,
            )
            os.chmod(temporary, 0o600)
            view = memoryview(bytes(secret))
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise AuthenticationError("short service credential write")
                view = view[written:]
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = None
            if os.path.lexists(destination) and os.path.islink(destination):
                raise AuthenticationError("service credential path is a link")
            os.replace(temporary, destination)
            os.chmod(destination, 0o600)
            return
        finally:
            if descriptor is not None:
                os.close(descriptor)
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

    descriptor = _open_secure_directory(directory, create=True, final_mode=0o700)
    try:
        _atomic_write_at(descriptor, name, bytes(secret), mode=0o600)
    finally:
        os.close(descriptor)


def load_service_secret(service, *, directory=SERVICE_SECRET_DIRECTORY):
    name = _service_secret_name(service)
    if os.name != "posix":
        directory = os.path.abspath(directory)
        path = os.path.abspath(os.path.join(directory, name))
        if (
            os.path.commonpath((directory, path)) != directory
            or os.path.islink(directory)
            or os.path.islink(path)
        ):
            raise AuthenticationError("unsafe service credential path")
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0))
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_SERVICE_SECRET_BYTES:
                raise AuthenticationError("unsafe service credential")
            secret = os.read(descriptor, MAX_SERVICE_SECRET_BYTES + 1)
        finally:
            os.close(descriptor)
        if not secret or len(secret) > MAX_SERVICE_SECRET_BYTES or b"\x00" in secret:
            raise AuthenticationError("unsafe service credential")
        return secret

    descriptor = _open_secure_directory(directory)
    try:
        secret, metadata = _read_regular_at(
            descriptor, name, maximum=MAX_SERVICE_SECRET_BYTES
        )
    finally:
        os.close(descriptor)
    if metadata.st_mode & 0o077 or not secret or b"\x00" in secret:
        raise AuthenticationError("unsafe service credential")
    return secret


def delete_service_secret(service, *, directory=SERVICE_SECRET_DIRECTORY):
    name = _service_secret_name(service)
    if os.name != "posix":
        directory = os.path.abspath(directory)
        path = os.path.abspath(os.path.join(directory, name))
        if (
            os.path.commonpath((directory, path)) != directory
            or os.path.islink(directory)
            or os.path.islink(path)
        ):
            raise AuthenticationError("unsafe service credential path")
        os.unlink(path)
        return

    descriptor = _open_secure_directory(directory)
    try:
        os.unlink(name, dir_fd=descriptor)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write_credentials(path, username, stored_hash):
    username = canonicalize_username(username)
    if not validate_stored_hash(stored_hash):
        raise ValueError("invalid credential representation")
    parent, name = os.path.split(os.path.abspath(path))
    directory = _open_secure_directory(parent, create=True, final_mode=0o700)
    try:
        payload = f"{username}:{stored_hash}\n".encode("utf-8")
        _atomic_write_at(directory, name, payload, mode=0o600)
    finally:
        os.close(directory)


def read_credentials(path):
    parent, name = os.path.split(os.path.abspath(path))
    directory = _open_secure_directory(parent)
    try:
        data, _ = _read_regular_at(directory, name, maximum=MAX_CREDENTIAL_BYTES)
    finally:
        os.close(directory)
    try:
        text = data.decode("utf-8", errors="strict")
        first = text.splitlines()[0]
        username, stored = first.split(":", 1)
        username = canonicalize_username(username)
    except (IndexError, UnicodeError, ValueError) as error:
        raise AuthenticationError("malformed credential file") from error
    if not validate_stored_hash(stored):
        raise AuthenticationError("unsupported credential representation")
    return username, stored


def _ensure_tree_at(base, parts, *, mode=0o700, owner_uid=None, owner_gid=None):
    descriptor = os.dup(base)
    try:
        for component in parts:
            child = _open_child_directory(descriptor, component, create=True, mode=mode)
            os.close(descriptor)
            descriptor = child
            if owner_uid is not None and owner_gid is not None and os.name == "posix":
                os.fchown(descriptor, int(owner_uid), int(owner_gid))
                os.fchmod(descriptor, mode)
    finally:
        os.close(descriptor)


def ensure_user_tree(home_base, username, *, owner_uid=None, owner_gid=None):
    """Create a private user home without following filesystem links.

    Installed desktop sessions pass their fixed unprivileged uid/gid.  Tests and
    image tooling may omit ownership when they intentionally operate as the
    current user.  Requiring both values prevents a half-applied identity.
    """
    if (owner_uid is None) != (owner_gid is None):
        raise ValueError("user-home ownership requires both uid and gid")
    if owner_uid is not None:
        owner_uid = int(owner_uid)
        owner_gid = int(owner_gid)
        if owner_uid < 1 or owner_gid < 1:
            raise ValueError("user-home owner must be unprivileged")
    username = canonicalize_username(username)
    base = _open_secure_directory(home_base, create=True, final_mode=0o755)
    try:
        user = _open_child_directory(base, username, create=True, mode=0o700)
        try:
            if owner_uid is not None and os.name == "posix":
                os.fchown(user, owner_uid, owner_gid)
                os.fchmod(user, 0o700)
            for relative in (
                ("flash", "books"),
                ("flash", "music"),
                ("flash", "images"),
                ("flash", "downloads"),
                ("flash", "videos"),
                ("expanse",),
                ("reference", "identity"),
            ):
                _ensure_tree_at(
                    user,
                    relative,
                    mode=0o700,
                    owner_uid=owner_uid,
                    owner_gid=owner_gid,
                )
        finally:
            os.close(user)
    finally:
        os.close(base)
    return username


def provision_user(root, username, password, *, owner_uid=1000, owner_gid=1000):
    root = os.path.abspath(root)
    root_descriptor = _open_secure_directory(root)
    os.close(root_descriptor)
    username = canonicalize_username(username)
    stored = hash_password(password)
    ensure_user_tree(
        os.path.join(root, "master"),
        username,
        owner_uid=owner_uid,
        owner_gid=owner_gid,
    )
    atomic_write_credentials(
        os.path.join(root, "the one", "master", "master.txt"),
        username,
        stored,
    )
    return username


def change_user(root, current_password, username, new_password=""):
    """Authenticate and atomically change the active account identity.

    An empty ``new_password`` keeps the current versioned credential hash.  A
    supplied password is always passed through ``hash_password`` so account
    management cannot drift from login/provisioning KDF policy.
    """
    root = os.path.abspath(root)
    root_descriptor = _open_secure_directory(root)
    os.close(root_descriptor)
    master_file = os.path.join(root, "the one", "master", "master.txt")
    old_username, old_hash = read_credentials(master_file)
    if not verify_password(current_password, old_hash):
        raise AuthenticationError("authentication failed")

    username = canonicalize_username(username)
    replacement = hash_password(new_password) if new_password else old_hash
    home_base = os.path.join(root, "master")
    moved = False
    if username != old_username:
        base = _open_secure_directory(home_base)
        try:
            old_home = _open_child_directory(base, old_username)
            try:
                if not stat.S_ISDIR(os.fstat(old_home).st_mode):
                    raise AuthenticationError("active user home is unsafe")
            finally:
                os.close(old_home)
            try:
                os.stat(username, dir_fd=base, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise AuthenticationError("requested user home already exists")
            os.rename(
                old_username,
                username,
                src_dir_fd=base,
                dst_dir_fd=base,
            )
            os.fsync(base)
            moved = True
        finally:
            os.close(base)

    try:
        atomic_write_credentials(master_file, username, replacement)
    except Exception:
        if moved:
            base = _open_secure_directory(home_base)
            try:
                os.rename(
                    username,
                    old_username,
                    src_dir_fd=base,
                    dst_dir_fd=base,
                )
                os.fsync(base)
            finally:
                os.close(base)
        raise
    return {
        "old_username": old_username,
        "username": username,
        "password_changed": bool(new_password),
    }


def remove_user(root, current_password, username):
    """Authenticate and remove the active credential and private home tree."""
    root = os.path.abspath(root)
    root_descriptor = _open_secure_directory(root)
    os.close(root_descriptor)
    master_file = os.path.join(root, "the one", "master", "master.txt")
    active_username, stored = read_credentials(master_file)
    username = canonicalize_username(username)
    if username != active_username:
        raise AuthenticationError("active username confirmation does not match")
    if not verify_password(current_password, stored):
        raise AuthenticationError("authentication failed")

    home_base = os.path.join(root, "master")
    quarantine = f".removed-{secrets.token_hex(12)}"
    base = _open_secure_directory(home_base)
    moved = False
    try:
        home = _open_child_directory(base, active_username)
        try:
            if not stat.S_ISDIR(os.fstat(home).st_mode):
                raise AuthenticationError("active user home is unsafe")
        finally:
            os.close(home)
        os.rename(
            active_username,
            quarantine,
            src_dir_fd=base,
            dst_dir_fd=base,
        )
        os.fsync(base)
        moved = True

        credential_parent, credential_name = os.path.split(master_file)
        credentials = _open_secure_directory(credential_parent)
        try:
            os.unlink(credential_name, dir_fd=credentials)
            os.fsync(credentials)
        except Exception:
            os.rename(
                quarantine,
                active_username,
                src_dir_fd=base,
                dst_dir_fd=base,
            )
            os.fsync(base)
            moved = False
            raise
        finally:
            os.close(credentials)
    finally:
        os.close(base)

    if moved:
        quarantine_path = os.path.join(home_base, quarantine)
        try:
            shutil.rmtree(quarantine_path)
        except Exception as error:
            raise AuthenticationError(
                "account removed but quarantined home cleanup failed"
            ) from error
    return active_username


class AttemptLimiter:
    """A process-safe, persistent exponential backoff state machine."""

    def __init__(self, path=ATTEMPT_STATE_FILE):
        self.path = os.path.abspath(path)

    @contextlib.contextmanager
    def _locked(self):
        parent, name = os.path.split(self.path)
        directory = _open_secure_directory(parent, create=True, final_mode=0o700)
        lock_name = f".{name}.lock"
        lock_descriptor = os.open(
            lock_name,
            _file_flags(os.O_RDWR | os.O_CREAT),
            0o600,
            dir_fd=directory,
        )
        os.fchmod(lock_descriptor, 0o600)
        try:
            try:
                import fcntl

                fcntl.flock(lock_descriptor, fcntl.LOCK_EX)
            except ImportError:
                pass
            yield directory, name
        finally:
            try:
                import fcntl

                fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
            except ImportError:
                pass
            os.close(lock_descriptor)
            os.close(directory)

    @staticmethod
    def _key(principal, scope):
        if not isinstance(principal, str) or not isinstance(scope, str):
            raise AuthenticationError("invalid rate-limit identity")
        return hashlib.sha256(
            (scope + "\x00" + principal).encode("utf-8", errors="strict")
        ).hexdigest()

    @staticmethod
    def _load(directory, name):
        try:
            raw, metadata = _read_regular_at(directory, name, maximum=32768)
        except FileNotFoundError:
            return {"version": 1, "entries": {}}
        if metadata.st_mode & 0o077:
            raise AuthenticationError("rate-limit state permissions are too broad")
        try:
            state = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as error:
            raise AuthenticationError("rate-limit state is corrupt") from error
        if (
            not isinstance(state, dict)
            or state.get("version") != 1
            or not isinstance(state.get("entries"), dict)
            or len(state["entries"]) > 64
        ):
            raise AuthenticationError("rate-limit state is invalid")
        return state

    @staticmethod
    def _write(directory, name, state):
        raw = json.dumps(
            state, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("ascii")
        _atomic_write_at(directory, name, raw + b"\n", mode=0o600)

    def reserve(self, principal, scope, *, now=None):
        now = float(time.time() if now is None else now)
        key = self._key(principal, scope)
        with self._locked() as (directory, name):
            state = self._load(directory, name)
            entries = state["entries"]
            entry = entries.get(key, {})
            try:
                blocked_until = float(entry.get("blocked_until", 0.0))
                failures = int(entry.get("failures", 0))
            except (TypeError, ValueError) as error:
                raise AuthenticationError("invalid rate-limit entry") from error
            if blocked_until > now:
                return False, min(blocked_until - now, 30.0)

            failures = min(max(failures, 0) + 1, 10)
            delay = min(float(2 ** (failures - 1)), 30.0)
            entries[key] = {
                "failures": failures,
                "blocked_until": now + delay,
                "last": now,
            }
            for old_key, old_entry in list(entries.items()):
                try:
                    if now - float(old_entry.get("last", now)) > 86400:
                        entries.pop(old_key, None)
                except (AttributeError, TypeError, ValueError):
                    raise AuthenticationError("invalid rate-limit entry")
            self._write(directory, name, state)
            return True, delay

    def success(self, principal, scope):
        key = self._key(principal, scope)
        with self._locked() as (directory, name):
            state = self._load(directory, name)
            if key in state["entries"]:
                state["entries"].pop(key, None)
                self._write(directory, name, state)


def authenticate_master(
    master_file,
    password,
    *,
    scope="login",
    rate_path=ATTEMPT_STATE_FILE,
    now=None,
    migrate=True,
):
    try:
        username, stored = read_credentials(master_file)
        limiter = AttemptLimiter(rate_path)
        allowed, delay = limiter.reserve(username, scope, now=now)
        if not allowed:
            return AuthenticationResult(
                False, username=username, retry_after=delay, error="rate-limited"
            )
        if not verify_password(password, stored):
            return AuthenticationResult(
                False, username=username, retry_after=delay, error="invalid-credential"
            )
        limiter.success(username, scope)
        migrated = False
        if migrate and password_needs_upgrade(stored):
            try:
                replacement = hash_password(password)
                atomic_write_credentials(master_file, username, replacement)
                migrated = True
            except Exception:
                # Authentication remains valid, but callers can surface the failed
                # migration without ever logging or retaining the password.
                return AuthenticationResult(
                    True, username=username, migrated=False, error="migration-failed"
                )
        return AuthenticationResult(True, username=username, migrated=migrated)
    except Exception as error:
        return AuthenticationResult(False, error=type(error).__name__)


def _validate_token(token):
    if not isinstance(token, str) or not _TOKEN_RE.fullmatch(token):
        raise ValueError("invalid authorization token")
    return token


def _token_name(token):
    _validate_token(token)
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def _recovery_directory(master_file):
    return os.path.join(os.path.dirname(os.path.abspath(master_file)), "recovery authorizations")


def issue_recovery_authorization(
    master_file,
    password,
    action,
    *,
    ttl=300,
    rate_path=ATTEMPT_STATE_FILE,
    now=None,
):
    if action not in RECOVERY_ACTIONS:
        raise ValueError("unsupported destructive recovery action")
    result = authenticate_master(
        master_file,
        password,
        scope=f"recovery:{action}",
        rate_path=rate_path,
    )
    if not result.ok:
        return IssuedAuthorization(result)
    ttl = int(ttl)
    if not 30 <= ttl <= MAX_AUTHORIZATION_TTL_SECONDS:
        raise ValueError("recovery authorization lifetime is outside policy bounds")
    now = int(time.time() if now is None else now)
    token = secrets.token_urlsafe(32)
    name = _token_name(token)
    body = (
        "format=1\n"
        f"action={action}\n"
        f"expires={now + ttl}\n"
        f"subject={result.username}\n"
    ).encode("ascii")
    directory = _open_secure_directory(
        _recovery_directory(master_file), create=True, final_mode=0o700
    )
    try:
        _atomic_write_at(directory, name, body, mode=0o600)
    finally:
        os.close(directory)
    return IssuedAuthorization(result, token)


def validate_recovery_authorization(master_file, token, action, *, now=None):
    try:
        if action not in RECOVERY_ACTIONS:
            return False
        name = _token_name(token)
        directory = _open_secure_directory(_recovery_directory(master_file))
        try:
            raw, metadata = _read_regular_at(directory, name, maximum=512)
        finally:
            os.close(directory)
        if metadata.st_mode & 0o077:
            return False
        values = {}
        for line in raw.decode("ascii").splitlines():
            key, value = line.split("=", 1)
            if key in values:
                return False
            values[key] = value
        if set(values) != {"format", "action", "expires", "subject"}:
            return False
        if values["format"] != "1" or values["action"] != action:
            return False
        canonicalize_username(values["subject"])
        expires = _bounded_integer(values["expires"], 1, 4102444800)
        now = int(time.time() if now is None else now)
        return now < expires <= now + MAX_AUTHORIZATION_TTL_SECONDS
    except (AuthenticationError, FileNotFoundError, OSError, TypeError, ValueError,
            UnicodeError):
        return False


def recovery_authorization_digest(
    master_file, token, action, *, now=None, origin_boot_id=None
):
    """Return the token-record digest Angel can verify with initramfs tools.

    The opaque token never becomes a command-line argument.  Angel hashes it,
    finds the root-only authorization record by that digest, and checks the same
    small, bounded record format before allowing a destructive action.
    """
    if not validate_recovery_authorization(master_file, token, action, now=now):
        raise AuthenticationError("invalid recovery authorization")
    digest = _token_name(token)
    if origin_boot_id is None:
        return digest
    origin_boot_id = str(origin_boot_id).strip().lower()
    if not re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
        origin_boot_id,
    ):
        raise ValueError("invalid recovery authorization boot identity")
    directory = _open_secure_directory(_recovery_directory(master_file))
    try:
        raw, metadata = _read_regular_at(directory, digest, maximum=512)
        if metadata.st_mode & 0o077:
            raise AuthenticationError("unsafe recovery authorization")
        values = {}
        for line in raw.decode("ascii").splitlines():
            key, value = line.split("=", 1)
            if key in values:
                raise AuthenticationError("invalid recovery authorization")
            values[key] = value
        if set(values) != {"format", "action", "expires", "subject"}:
            raise AuthenticationError("invalid recovery authorization")
        if values["format"] != "1" or values["action"] != action:
            raise AuthenticationError("invalid recovery authorization")
        canonicalize_username(values["subject"])
        expires = _bounded_integer(values["expires"], 1, 4102444800)
        current = int(time.time() if now is None else now)
        if not current < expires <= current + MAX_AUTHORIZATION_TTL_SECONDS:
            raise AuthenticationError("expired recovery authorization")
        upgraded = (
            "format=2\n"
            f"action={action}\n"
            f"expires={expires}\n"
            f"subject={values['subject']}\n"
            f"origin_boot_id={origin_boot_id}\n"
        ).encode("ascii")
        _atomic_write_at(directory, digest, upgraded, mode=0o600)
    finally:
        os.close(directory)
    return digest


def _read_password_stdin():
    value = sys.stdin.read(MAX_PASSWORD_CHARS + 3)
    if value.endswith("\r\n"):
        value = value[:-2]
    elif value.endswith("\n"):
        value = value[:-1]
    if "\n" in value or "\r" in value:
        raise ValueError("password input contained extra lines")
    return value


def _read_password_lines(count):
    if not isinstance(count, int) or count < 1 or count > 2:
        raise ValueError("invalid password input count")
    value = sys.stdin.read((MAX_PASSWORD_CHARS + 3) * count)
    value = value.replace("\r\n", "\n")
    if value.endswith("\n"):
        value = value[:-1]
    lines = value.split("\n")
    if len(lines) != count or any("\r" in line for line in lines):
        raise ValueError("password input did not contain the expected lines")
    return lines


def _cli(argv=None):
    parser = argparse.ArgumentParser(description="T1OS authentication broker")
    commands = parser.add_subparsers(dest="command", required=True)

    canonical = commands.add_parser("canonicalize-username")
    canonical.add_argument("username")

    commands.add_parser("hash-password")

    provision = commands.add_parser("provision-user")
    provision.add_argument("--root", required=True)
    provision.add_argument("--username", required=True)

    change = commands.add_parser("change-user")
    change.add_argument("--root", required=True)
    change.add_argument("--username", required=True)
    change.add_argument("--change-password", action="store_true")

    remove = commands.add_parser("remove-user")
    remove.add_argument("--root", required=True)
    remove.add_argument("--username", required=True)

    recovery = commands.add_parser("issue-recovery")
    recovery.add_argument("--master-file", default="/the one/master/master.txt")
    recovery.add_argument("--action", choices=sorted(RECOVERY_ACTIONS), required=True)
    recovery.add_argument("--ttl", type=int, default=300)

    verify_recovery = commands.add_parser("verify-recovery")
    verify_recovery.add_argument(
        "--master-file", default="/the one/master/master.txt"
    )
    verify_recovery.add_argument(
        "--action", choices=sorted(RECOVERY_ACTIONS), required=True
    )

    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "canonicalize-username":
            print(canonicalize_username(arguments.username))
        elif arguments.command == "hash-password":
            print(hash_password(_read_password_stdin()))
        elif arguments.command == "provision-user":
            print(provision_user(
                arguments.root, arguments.username, _read_password_stdin()
            ))
        elif arguments.command == "change-user":
            passwords = _read_password_lines(
                2 if arguments.change_password else 1
            )
            print(json.dumps(change_user(
                arguments.root,
                passwords[0],
                arguments.username,
                passwords[1] if arguments.change_password else "",
            ), sort_keys=True, separators=(",", ":")))
        elif arguments.command == "remove-user":
            print(remove_user(
                arguments.root,
                _read_password_lines(1)[0],
                arguments.username,
            ))
        elif arguments.command == "issue-recovery":
            issued = issue_recovery_authorization(
                arguments.master_file,
                _read_password_stdin(),
                arguments.action,
                ttl=arguments.ttl,
            )
            if not issued.authentication.ok:
                if issued.authentication.retry_after:
                    print(
                        f"authorization denied; retry after "
                        f"{int(issued.authentication.retry_after + 0.999)} seconds",
                        file=sys.stderr,
                    )
                else:
                    print("authorization denied", file=sys.stderr)
                return 1
            print(issued.token)
        elif arguments.command == "verify-recovery":
            token = sys.stdin.read(128).strip()
            print(recovery_authorization_digest(
                arguments.master_file, token, arguments.action
            ))
        return 0
    except Exception as error:
        print(f"authentication broker failed: {type(error).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(_cli())
