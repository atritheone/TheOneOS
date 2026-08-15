#!"/the one/software/python/bin/python" -B

"""
procedures.py

procedures handles startup and condition-based operations for The One OS.
"""



# imports
import os
import sys
import json
import socket
import time
import stat

sys.path.insert(0, '/the one/build')

from GODDESS.GODDESS import formatlog



# globals
STARTUPFILE = '/the one/settings/procedures/startup/startup.txt'
LOGSTIER = '/the one/logs'
LOGFILE = "/the one/logs/procedures.py.log"
EVENTTIER = '/the one/settings/procedures'
OPERATIONSSOCKET = '/.ephemeral/operations/control.sock'
SOCKETTIMEOUT = 2.0
DEBUGPROCEDURES = False
MAXPROCEDUREBYTES = 65536
PROCEDUREIDS = {
    '/the one/build/brick/brick.py': 'brick',
    '/the one/build/calculator/calculator.py': 'calculator',
    '/the one/build/operations/operationscentre.py': 'operations centre',
    '/the one/build/chromium/chromium.py': 'chromium',
    '/the one/build/settings/settings.py': 'settings',
    '/the one/build/snap/snap.py': 'snap',
}



# misc functions
def log(msg):

    if not DEBUGPROCEDURES:
        return


    try:
        os.makedirs(os.path.dirname(LOGFILE), exist_ok=True)
    except Exception:
        pass

    line = formatlog('procedures', msg) + '\n'

    with open(LOGFILE, "a") as f:

        f.write(line)

        f.flush()

        os.fsync(f.fileno())

def sendops(request):

    sock = None

    try:

        # create socket
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

        # set timeout
        sock.settimeout(SOCKETTIMEOUT)

        # connect
        sock.connect(OPERATIONSSOCKET)

        # send json line
        payload = (json.dumps(request) + '\n').encode('utf-8')
        sock.sendall(payload)

        # receive one response line
        data = b''
        while b'\n' not in data:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk

        # parse response
        text = data.decode('utf-8', errors='replace').strip()

        if not text:
            return {'status': 'error', 'message': 'no response'}

        return json.loads(text)

    except FileNotFoundError:

        # socket not found
        return {'status': 'error', 'message': 'operations socket not found'}

    except ConnectionRefusedError:

        # server not accepting
        return {'status': 'error', 'message': 'operations server refused'}

    except TimeoutError:

        # socket timeout
        return {'status': 'error', 'message': 'operations socket timeout'}

    except json.JSONDecodeError:

        # invalid json
        return {'status': 'error', 'message': 'invalid operations response'}

    except Exception as e:

        # other errors
        return {'status': 'error', 'message': f'operations socket error {e}'}

    finally:

        if sock:
            sock.close()
def opsrun(path, args, name, log, user, mode):

    procedureid = PROCEDUREIDS.get(os.path.normpath(str(path)))
    if procedureid is None:
        return {'status': 'error', 'message': 'procedure identifier denied'}
    request = {
        'action': 'PROCEDURE_LAUNCH',
        'id': procedureid,
        'mode': mode,
    }

    return sendops(request)


def opslist():

    return sendops({'op': 'LIST'})


# utility functions
def readrole():
    # Compatibility metadata only. Authority is an immutable process domain.
    return 'session'


def opname(path):

    basename = os.path.basename(path)

    name = os.path.splitext(basename)[0]

    return basename, name


def getops():

    resp = opslist()

    if resp.get('status') != 'ok':
        return {}

    ops = resp.get('operations', {})

    if not isinstance(ops, dict):
        return {}

    return ops


def isalreadyrunning(ops, path):

    try:

        # check by script
        for info in ops.values():
            script = info.get('script', None)

            if script == path:
                return True

        # fallback check
        for info in ops.values():
            cmd = info.get('cmd', None)

            if isinstance(cmd, list) and path in cmd:
                return True

    except Exception:
        return False

    return False


def hasfront(ops):

    try:
        return any(info.get('mode') == 'front' for info in ops.values())
    except Exception:
        return False


def readprocedurefile(path):

    """Read a root-owned, immutable procedure definition without links."""

    absolute = os.path.normpath(os.path.abspath(str(path)))
    root = os.path.normpath(EVENTTIER)
    if os.path.commonpath((root, absolute)) != root:
        raise PermissionError('procedure path is outside the policy tier')

    descriptor = os.open(
        absolute,
        os.O_RDONLY | getattr(os, 'O_CLOEXEC', 0) |
        getattr(os, 'O_NOFOLLOW', 0),
    )
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode) or
            metadata.st_uid != 0 or
            metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH) or
            metadata.st_nlink != 1 or
            metadata.st_size > MAXPROCEDUREBYTES
        ):
            raise PermissionError('unsafe procedure definition')
        data = os.read(descriptor, MAXPROCEDUREBYTES + 1)
        if len(data) > MAXPROCEDUREBYTES:
            raise ValueError('procedure definition is too large')
        return [
            line.strip()
            for line in data.decode('utf-8', errors='strict').splitlines()
            if line.strip() and not line.lstrip().startswith('#')
        ]
    finally:
        os.close(descriptor)


# procedure functions
def startprocedures():

    # fetch current operations snapshot
    ops = getops()

    # read startup entries
    try:
        lines = readprocedurefile(STARTUPFILE)

    except FileNotFoundError:

        # startup file missing
        log(f"no startup file found at {STARTUPFILE}")
        return []

    except PermissionError:

        # permission denied
        log(f"permission denied reading {STARTUPFILE}")
        return []

    except Exception as e:

        # other read errors
        log(f"error reading startup file {e}")
        return []

    # parse as pairs
    pairs = []
    for i in range(0, len(lines) - 1, 2):
        path = lines[i]
        mode = lines[i + 1].lower()
        pairs.append((path, mode))

    if not pairs:
        log(f"no startup entries found")
        return []

    # read user role once for startup
    role = readrole()

    # start behind operations via operations server
    for path, mode in pairs:

        if mode != 'behind':
            continue

        log(f"preparing behind operation for {path}")

        # skip if already running
        if isalreadyrunning(ops, path):
            log(f"already running {path}")
            continue

        basename, name = opname(path)

        logpath = os.path.join(LOGSTIER, f"{basename}.log")

        # run behind via operations server
        resp = opsrun(
            path=path,
            args=[],
            name=name,
            log=logpath,
            user=role,
            mode='behind'
        )

        if resp.get('status') != 'ok':
            log(f"operations run failed {path} {resp}")
            continue

        pid = resp.get('pid', None)

        log(f"behind operation started {name} pid {pid}")

        # refresh ops snapshot for duplicate prevention within same pass
        ops = getops()

    # Front and background procedures both cross the Operations boundary.
    # Operations always drops them to the untrusted desktop identity before
    # exec; Procedures never forks or executes configured paths as root.
    for path, mode in pairs:

        if mode != 'front':
            continue

        log(f"preparing front operation for {path}")

        # if any front already running, do not start another
        ops = getops()
        if hasfront(ops):
            log(f"front operation already running")
            break

        basename, name = opname(path)

        logpath = os.path.join(LOGSTIER, f"{basename}.log")
        resp = opsrun(
            path=path,
            args=[],
            name=name,
            log=logpath,
            user=role,
            mode='front',
        )
        if resp.get('status') != 'ok':
            log(f"operations run failed {path} {resp}")
        else:
            log(f"front operation started {name} pid {resp.get('pid')}")

        break

    # return list of current known pids
    ops = getops()

    return list(ops.keys())


def eventprocedures():

    found = False

    # fetch current operations snapshot
    ops = getops()

    # read user role once per event tick
    role = readrole()

    # check the procedures tier
    log(f"checking procedures tier")
    for root, dirs, files in os.walk(EVENTTIER):

        # ignore start procedures
        if 'startup' in root:
            continue

        # find procedure files
        for file in files:

            # ignore non txt files
            if not file.endswith('.txt'):
                continue

            found = True

            # determine script path
            filepath = os.path.join(root, file)
            log(f"processing file {filepath}")

            try:

                # Read only root-owned, non-link policy files.
                plines = readprocedurefile(filepath)

                # parse triplets
                for i in range(0, len(plines) - 2, 3):
                    path = plines[i]
                    action = plines[i + 1].lower()
                    mode = plines[i + 2].lower()

                    # refresh ops snapshot per rule set
                    ops = getops()

                    # resurrecting action
                    if action == 'resurrecting':
                        log(f"found resurrecting procedure {path}")

                        already = isalreadyrunning(ops, path)

                        fg = hasfront(ops)

                        if fg or already:
                            continue

                        log(f"preparing resurrecting operation {path}")

                        basename, name = opname(path)

                        logpath = os.path.join(LOGSTIER, f"{basename}.log")
                        resp = opsrun(
                            path=path,
                            args=[],
                            name=name,
                            log=logpath,
                            user=role,
                            mode='front',
                        )
                        if resp.get('status') != 'ok':
                            log(f"operations run failed {path} {resp}")
                        else:
                            log(
                                f"resurrecting procedure started {name} "
                                f"pid {resp.get('pid')}"
                            )

                        continue

                    # behind mode procedures
                    if mode == 'behind':

                        log(f"preparing behind procedure for {path}")

                        if isalreadyrunning(ops, path):
                            continue

                        basename, name = opname(path)

                        logpath = os.path.join(LOGSTIER, f"{basename}.log")

                        resp = opsrun(
                            path=path,
                            args=[],
                            name=name,
                            log=logpath,
                            user=role,
                            mode='behind'
                        )

                        if resp.get('status') != 'ok':
                            log(f"operations run failed {path} {resp}")
                            continue

                        pid = resp.get('pid', None)

                        log(f"behind procedure started {name} pid {pid}")

                        continue

                    # front mode procedures
                    if mode == 'front':

                        log(f"preparing front procedure for {path}")

                        if hasfront(ops):
                            continue

                        if isalreadyrunning(ops, path):
                            continue

                        basename, name = opname(path)

                        logpath = os.path.join(LOGSTIER, f"{basename}.log")
                        resp = opsrun(
                            path=path,
                            args=[],
                            name=name,
                            log=logpath,
                            user=role,
                            mode='front',
                        )
                        if resp.get('status') != 'ok':
                            log(f"operations run failed {path} {resp}")
                        else:
                            log(
                                f"front procedure started {name} "
                                f"pid {resp.get('pid')}"
                            )

                        continue

            except FileNotFoundError:

                # procedure file missing
                log(f"procedure file missing {filepath}")

            except PermissionError:

                # permission denied procedure file
                log(f"permission denied reading {filepath}")

            except Exception as e:

                # other errors
                log(f"failed to process {filepath} {e}")

    # if no event procedures are found
    if not found:
        log(f"no event procedures found")

    # return list of current known pids
    ops = getops()

    return list(ops.keys())



# execute main
if __name__ == '__main__':

    startprocedures()

    while True:
        eventprocedures()
        time.sleep(10)
