"""Small, dependency-free client for the T1OS Python manager."""

import json
import os
import socket


PROTOCOL = 1
DEFAULT_SOCKET = '/.ephemeral/python/manager.sock'
MAXIMUM_RESPONSE = 8 * 1024 * 1024


class PythonManagerError(RuntimeError):
    """A request was rejected or the manager was unavailable."""

    def __init__(self, message, code='failed', response=None):
        super().__init__(str(message))
        self.code = str(code or 'failed')
        self.response = dict(response or {})


def request(operation, arguments=None, timeout=5.0, socket_path=None):
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

    if len(encoded) > 256 * 1024:
        raise PythonManagerError('The Python manager request is too large.', 'request_too_large')

    channel = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    channel.settimeout(float(timeout))

    try:
        channel.connect(path)
        channel.sendall(encoded)
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
