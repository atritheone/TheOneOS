#!/usr/bin/env python3
"""Exercise persistent desktop-tier ownership repair on a POSIX host."""

import ast
import os
from pathlib import Path
import stat as statmodule
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[2]
GODDESS = ROOT / 'source/build software/GODDESS/GODDESS.py'
DESKTOP_UID = 1000
DESKTOP_GID = 1000


def load_repair_functions():
    source = GODDESS.read_text(encoding='utf-8')
    tree = ast.parse(source, filename=str(GODDESS))
    wanted = {'_normaliseownedtree', 'normalisepersistentdesktoptiers'}
    selected = [
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in wanted
    ]
    assert {node.name for node in selected} == wanted
    module = ast.Module(body=selected, type_ignores=[])
    namespace = {
        'os': os,
        'statmodule': statmodule,
        'T1OS_DESKTOP_UID': DESKTOP_UID,
        'T1OS_DESKTOP_GID': DESKTOP_GID,
    }
    exec(compile(module, str(GODDESS), 'exec'), namespace)
    return namespace['normalisepersistentdesktoptiers']


def assert_owner(path, uid, gid, mode):
    status = os.lstat(path)
    assert status.st_uid == uid, (path, status.st_uid, uid)
    assert status.st_gid == gid, (path, status.st_gid, gid)
    assert statmodule.S_IMODE(status.st_mode) == mode, (
        path, oct(statmodule.S_IMODE(status.st_mode)), oct(mode))


def child_result(callback):
    pid = os.fork()
    if pid == 0:
        try:
            os.setgroups([])
            os.setgid(DESKTOP_GID)
            os.setuid(DESKTOP_UID)
            callback()
        except BaseException:
            os._exit(1)
        os._exit(0)
    _pid, status = os.waitpid(pid, 0)
    return os.waitstatus_to_exitcode(status)


def main():
    if os.name == 'nt':
        subprocess.run(
            [
                'wsl.exe', '--distribution', 'Ubuntu', '--user', 'root',
                '--cd', str(ROOT), 'python3',
                Path(__file__).relative_to(ROOT).as_posix(),
            ],
            check=True,
        )
        return
    if os.name != 'posix' or not hasattr(os, 'chown') or os.geteuid() != 0:
        print('persistent desktop tier permissions: skipped (requires POSIX root)')
        return

    repair = load_repair_functions()
    old_developer = os.environ.pop('T1OS_DEVELOPER', None)
    old_agent = os.environ.pop('T1OS_ENABLE_VM_TEST_AGENT', None)
    try:
        with tempfile.TemporaryDirectory(prefix='t1os-tier-contract-') as root:
            os.chmod(root, 0o755)
            software = os.path.join(root, 'software')
            rubbish = os.path.join(root, '.rubbish')
            os.mkdir(software, 0o755)
            existing = os.path.join(software, 'opengl test.py')
            Path(existing).write_text('print("gpu")\n', encoding='utf-8')

            repair(software, rubbish)
            assert_owner(software, DESKTOP_UID, DESKTOP_GID, 0o755)
            assert_owner(existing, DESKTOP_UID, DESKTOP_GID, 0o644)
            assert_owner(rubbish, DESKTOP_UID, DESKTOP_GID, 0o700)

            def desktop_mutation():
                os.unlink(existing)
                child = os.path.join(software, 'created.py')
                Path(child).write_text('pass\n', encoding='utf-8')
                os.unlink(child)
                item = os.path.join(rubbish, 'item')
                os.mkdir(item)
                os.rmdir(item)

            assert child_result(desktop_mutation) == 0

            index = os.path.join(rubbish, 'index.txt')
            Path(index).write_text('header\n', encoding='utf-8')
            repair(software, rubbish)
            assert_owner(index, DESKTOP_UID, DESKTOP_GID, 0o600)

            developer_software = os.path.join(root, 'developer-software')
            developer_rubbish = os.path.join(root, 'developer-rubbish')
            os.mkdir(developer_software, 0o755)
            reserved = os.path.join(developer_software, 't1os-python')
            os.mkdir(reserved, 0o755)
            reserved_file = os.path.join(reserved, 'fixture')
            Path(reserved_file).write_text('root fixture\n', encoding='utf-8')
            ordinary = os.path.join(developer_software, 'ordinary.py')
            Path(ordinary).write_text('pass\n', encoding='utf-8')
            os.environ['T1OS_DEVELOPER'] = '1'
            os.environ['T1OS_ENABLE_VM_TEST_AGENT'] = '1'

            repair(developer_software, developer_rubbish)
            assert_owner(developer_software, 0, 0, 0o1777)
            assert_owner(reserved, 0, 0, 0o755)
            assert_owner(reserved_file, 0, 0, 0o644)
            assert_owner(ordinary, DESKTOP_UID, DESKTOP_GID, 0o644)

            def developer_mutation():
                try:
                    os.rename(reserved, reserved + '-renamed')
                except PermissionError:
                    pass
                else:
                    raise AssertionError('desktop renamed a reserved VM fixture')
                child = os.path.join(developer_software, 'desktop-owned')
                Path(child).write_text('ok\n', encoding='utf-8')
                os.unlink(child)

            assert child_result(developer_mutation) == 0
    finally:
        if old_developer is None:
            os.environ.pop('T1OS_DEVELOPER', None)
        else:
            os.environ['T1OS_DEVELOPER'] = old_developer
        if old_agent is None:
            os.environ.pop('T1OS_ENABLE_VM_TEST_AGENT', None)
        else:
            os.environ['T1OS_ENABLE_VM_TEST_AGENT'] = old_agent

    print('persistent desktop tier permissions: passed')


if __name__ == '__main__':
    main()
