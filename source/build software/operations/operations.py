

"""
operations.py

operations manages processes for The One OS. It can run operations, records running operations, and can terminate operations.
"""



# imports
import os
import sys
import json
import socket
import signal
import subprocess
import re

sys.path.insert(0, '/the one/build')

from GODDESS.GODDESS import popenisolated



# globals
LOGSTIER='/the one/logs'
SOCKETPATH = "/.ephemeral/power/control.sock"
OPERATIONSSOCKET = "/.ephemeral/operations/control.sock"
VALIDACTIONS = frozenset(("poweroff", "restart"))
VALIDRECOVERYACTIONS = frozenset(("python", "build", "reset", "reinstall"))
MAXIMUMRESPONSE = 4096



# power transition functions
class PowerRequestError(RuntimeError):
    pass


class OperationsRequestError(RuntimeError):
    pass


def requestoperations(request, timeout=3.0):

    if not isinstance(request, dict):
        raise ValueError('operations request must be an object')

    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        connection.settimeout(max(0.1, float(timeout)))
        connection.connect(OPERATIONSSOCKET)
        encoded = json.dumps(
            request, sort_keys=True, separators=(',', ':'))
        if len(encoded.encode('utf-8')) > 65535:
            raise ValueError('operations request is too large')
        connection.sendall(encoded.encode('utf-8') + b'\n')

        response = bytearray()
        while len(response) < 65536:
            chunk = connection.recv(min(4096, 65536 - len(response)))
            if not chunk:
                break
            response.extend(chunk)
            if b'\n' in chunk:
                break

        line = bytes(response).split(b'\n', 1)[0]
        if not line:
            raise OperationsRequestError('OperationsServer closed without a response')
        try:
            result = json.loads(line.decode('utf-8', errors='strict'))
        except (UnicodeError, ValueError, TypeError) as error:
            raise OperationsRequestError('OperationsServer returned invalid JSON') from error
        if not isinstance(result, dict):
            raise OperationsRequestError('OperationsServer returned an invalid response')
        if str(result.get('status', '')).lower() not in ('ok', 'accepted'):
            raise OperationsRequestError(str(result.get('message') or 'request denied'))
        return result
    except OperationsRequestError:
        raise
    except (FileNotFoundError, ConnectionRefusedError) as error:
        raise OperationsRequestError('OperationsServer is unavailable') from error
    except OSError as error:
        raise OperationsRequestError(f'OperationsServer request failed: {error}') from error
    finally:
        connection.close()


def launchcatalogueapplication(path, args=None, name=None, logpath=None,
                               environment=None, timeout=3.0):

    request = {
        'action': 'LAUNCH_CATALOGUE',
        'path': str(path),
        'args': [str(value) for value in (args or ())],
        'environment': {
            str(key): str(value)
            for key, value in (environment or {}).items()
        },
    }
    if name:
        request['name'] = str(name)
    if logpath:
        request['log'] = str(logpath)
    return requestoperations(request, timeout=timeout)


def requestsessionlogout(timeout=10.0):

    return requestoperations({'action': 'SESSION_LOGOUT'}, timeout=timeout)


def normaliseaction(action):

    action = str(action or "").strip().lower()

    if action not in VALIDACTIONS:
        raise ValueError(f"unsupported power action: {action or 'empty'}")

    return action


def requestpower(action, timeout=2.0, recovery_action=None, recovery_token=None):

    action = normaliseaction(action)
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

    try:

        connection.settimeout(max(0.1, float(timeout)))
        connection.connect(SOCKETPATH)
        request = {
            "format": 1,
            "action": action,
        }
        if recovery_action is not None:
            recovery_action = str(recovery_action).strip().lower()
            if action != "restart" or recovery_action not in VALIDRECOVERYACTIONS:
                raise ValueError(f"unsupported recovery action: {recovery_action or 'empty'}")
            request["recovery_action"] = recovery_action
            if recovery_token is not None:
                token = str(recovery_token)
                if len(token) != 43 or not all(
                    value.isalnum() or value in '_-' for value in token):
                    raise ValueError('invalid recovery authorization token')
                request['recovery_token'] = token
        connection.sendall(
            json.dumps(request, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
        )

        response = bytearray()

        while len(response) < MAXIMUMRESPONSE:

            chunk = connection.recv(min(1024, MAXIMUMRESPONSE - len(response)))

            if not chunk:
                break

            response.extend(chunk)

            if b"\n" in chunk:
                break

        line = bytes(response).split(b"\n", 1)[0]

        if not line:
            raise PowerRequestError("GODDESS closed the power request without a response")

        try:
            result = json.loads(line.decode("utf-8"))
        except (UnicodeError, ValueError, TypeError) as error:
            raise PowerRequestError(f"GODDESS returned an invalid power response: {error}") from error

        if not isinstance(result, dict) or int(result.get("format", 0)) != 1:
            raise PowerRequestError("GODDESS returned an unsupported power response")

        if not result.get("ok"):
            raise PowerRequestError(str(result.get("error") or "power request was rejected"))

        if str(result.get("action", "")) != action:
            raise PowerRequestError("GODDESS acknowledged a different power action")
        if recovery_action is not None and str(result.get("recovery_action", "")) != recovery_action:
            raise PowerRequestError("GODDESS acknowledged a different recovery action")

        return result

    except PowerRequestError:
        raise

    except (FileNotFoundError, ConnectionRefusedError):
        raise PowerRequestError("GODDESS power control is unavailable")

    except OSError as error:
        raise PowerRequestError(f"power request failed: {error}") from error

    finally:

        try:
            connection.close()
        except Exception:
            pass


def requestrecovery(action, timeout=2.0):

    return requestpower("restart", timeout=timeout, recovery_action=action)


def service_secret_put(name, value, timeout=3.0):

    return requestoperations({
        'action': 'SERVICE_SECRET_PUT', 'name': str(name), 'value': str(value),
    }, timeout=timeout)


def service_secret_delete(name, timeout=3.0):

    return requestoperations({
        'action': 'SERVICE_SECRET_DELETE', 'name': str(name),
    }, timeout=timeout)


def service_secret_exists(name, timeout=3.0):

    return bool(requestoperations({
        'action': 'SERVICE_SECRET_EXISTS', 'name': str(name),
    }, timeout=timeout).get('exists'))


def service_secret_get(name, timeout=3.0):

    result = requestoperations({
        'action': 'SERVICE_SECRET_GET', 'name': str(name),
    }, timeout=timeout)
    return str(result.get('value') or '')


def settings_account_get(timeout=3.0):

    return requestoperations({'action': 'SETTINGS_ACCOUNT_GET'}, timeout=timeout)


def settings_auth_verify(password, timeout=5.0):

    return requestoperations({
        'action': 'SETTINGS_AUTH_VERIFY', 'password': str(password),
    }, timeout=timeout)


def session_auth_verify(password, timeout=5.0):

    return requestoperations({
        'action': 'SESSION_AUTH_VERIFY', 'password': str(password),
    }, timeout=timeout)


def settings_master_update(current_password, username, new_password='',
                           use_master_image=False, image_path='', timeout=15.0):

    return requestoperations({
        'action': 'SETTINGS_MASTER_UPDATE',
        'current_password': str(current_password),
        'username': str(username),
        'new_password': str(new_password),
        'use_master_image': bool(use_master_image),
        'image_path': str(image_path),
    }, timeout=timeout)


def settings_recovery_authorize(password, action, timeout=10.0):

    return requestoperations({
        'action': 'SETTINGS_RECOVERY_AUTHORIZE',
        'password': str(password), 'recovery_action': str(action),
    }, timeout=timeout)


def settings_hostname_set(hostname, timeout=3.0):

    return requestoperations({
        'action': 'SETTINGS_HOSTNAME_SET', 'hostname': str(hostname),
    }, timeout=timeout)


def settings_time_set(timezone, internet=False, virtualbox=False, epoch=None,
                      timeout=5.0):

    request = {
        'action': 'SETTINGS_TIME_SET', 'timezone': str(timezone),
        'internet': bool(internet), 'virtualbox': bool(virtualbox),
    }
    if epoch is not None:
        request['epoch'] = float(epoch)
    return requestoperations(request, timeout=timeout)


def time_sample_set(epoch, source='internet', timeout=5.0):

    return requestoperations({
        'action': 'TIME_SAMPLE_SET',
        'source': str(source),
        'epoch': float(epoch),
    }, timeout=timeout)


def python_authorization_policy(operation, arguments=None):

    operation = str(operation or '').strip()
    arguments = dict(arguments or {})
    allowed = {
        'install_module': (frozenset(('name',)), frozenset(('name', 'version'))),
        'remove_module': (frozenset(('name',)),),
        'pin_module': (frozenset(('name',)),),
        'unpin_module': (frozenset(('name',)),),
        'update_module': (frozenset(('name',)),),
        'update_modules': (frozenset(),),
        'repair_modules': (frozenset(),),
        'restore_modules': (frozenset(),),
        'clear_cache': (frozenset(),),
    }.get(operation)
    if allowed is None or frozenset(arguments) not in allowed:
        raise ValueError('Python mutation arguments are not authorizable')
    name = re.sub(r'[-_.]+', '-', str(arguments.get('name') or '').strip()).lower()
    if name and not re.fullmatch(
            r'[a-z0-9](?:[a-z0-9-]{0,126}[a-z0-9])?', name):
        raise ValueError('invalid Python package name')
    if operation == 'install_module':
        if not name:
            raise ValueError('Python package name is required')
        version = str(arguments.get('version') or 'latest').strip()
        if not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.!+_-]{0,126}[A-Za-z0-9])?', version):
            raise ValueError('invalid Python package version')
        return 'python:install', f'{name}@{version}'
    if operation in ('remove_module', 'pin_module', 'unpin_module', 'update_module'):
        if not name:
            raise ValueError('Python package name is required')
        scope = {
            'remove_module': 'python:remove',
            'pin_module': 'python:pin',
            'unpin_module': 'python:unpin',
            'update_module': 'python:update',
        }[operation]
        return scope, name
    fixed = {
        'update_modules': ('python:update', '*'),
        'repair_modules': ('python:repair', 'current-lock'),
        'restore_modules': ('python:restore', 'previous-generation'),
        'clear_cache': ('python:clear-cache', 'unused'),
    }
    if operation in fixed:
        return fixed[operation]
    raise ValueError('Python mutation operation is not authorizable')


def architect_authorize(password, operation, arguments=None, timeout=10.0):

    scope, resource = python_authorization_policy(operation, arguments)
    return requestoperations({
        'action': 'ARCHITECT_AUTHORIZE',
        'password': str(password),
        'python_operation': str(operation),
        'scope': scope,
        'resource': resource,
    }, timeout=timeout)


def architect_revoke(timeout=3.0):

    return requestoperations({'action': 'ARCHITECT_REVOKE'}, timeout=timeout)


def architect_capability_check(operation, arguments=None,
                                 *, client_pid=None, client_started=None,
                                 client_uid=None, timeout=3.0):

    scope, resource = python_authorization_policy(operation, arguments)
    request = {
        'action': 'ARCHITECT_CAPABILITY_CHECK',
        'python_operation': str(operation),
        'scope': scope, 'resource': resource,
    }
    if client_pid is not None:
        request['client_pid'] = int(client_pid)
        request['client_started'] = int(client_started)
        request['client_uid'] = int(client_uid)
    return requestoperations(request, timeout=timeout)



# operation state functions
def runoperation(path, args):
    raise OperationsRequestError(
        'arbitrary local process launch is retired; use LAUNCH_CATALOGUE')


def killoperation(target):
    raise OperationsRequestError(
        'arbitrary PID termination is retired; use a broker-owned lifecycle action')


# current operations functions
def listoperations():

    try:

        # read and current running operations
        ops = readoperations()

    except Exception as e:

        # error preparing operations
        print(f'> error preparing operations {e}')
        return

    # if no operations remain
    if not ops:
        print('> no running operations')
        return

    # define operation entries
    records = []

    try:

        # build rows from pruned operations
        for pid, info in ops.items():

            # fetch fields with defaults
            name = info.get('name', '')
            path = str(info.get('script', ''))
            log = info.get('log') or ''
            user = info.get('user', 'master')
            mode = info.get('mode', 'behind')

            # append row
            records.append([str(pid), name, path, log, user, mode])

    except Exception as e:

        # generic parse error
        print(f'> error parsing operations {e}')
        return

    # if no entries are produced
    if not records:
        print('> no running operations')
        return

    # define column headings
    headings = ['pid', 'software', 'path', 'log', 'user', 'mode']

    # calculate widths
    widths = [len(h) for h in headings]
    for row in records:
        for i, cell in enumerate(row):
            if len(cell) > widths[i]:
                widths[i] = len(cell)

    # define table format
    fmt = '  '.join('{' + str(i) + ':<' + str(w) + '}' for i, w in enumerate(widths))

    # print table headings
    print(fmt.format(*headings))

    # spacer
    print()

    # print operations table
    for row in records:
        print(fmt.format(*row))


def readoperations():
    """Compatibility wrapper backed by the authoritative socket registry."""

    try:
        response = requestoperations({'op': 'LIST'})
        operations = response.get('operations', {})
        if not isinstance(operations, dict):
            return {}
        return {int(pid): dict(info) for pid, info in operations.items()}
    except Exception:
        return {}
