#!/usr/bin/env python3
"""Focused host-safe regression checks for the August userspace boot fixes."""

import sys as _t1os_incremental_sys
from pathlib import Path as _T1OSIncrementalPath

if __name__ == "__main__":
    _t1os_incremental_scripts = next(
        (parent for parent in _T1OSIncrementalPath(__file__).resolve().parents
         if (parent / "incremental_test.py").is_file()),
        None,
    )
    if _t1os_incremental_scripts is not None:
        _t1os_incremental_sys.path.insert(0, str(_t1os_incremental_scripts))
        from _incremental_test import guard as _t1os_incremental_guard
        if _t1os_incremental_guard(__file__, _t1os_incremental_sys.argv[1:]):
            raise SystemExit(0)

import ast
import datetime
from pathlib import Path
import re
import zoneinfo


ROOT = Path(__file__).resolve().parents[1]


def source(relative):
    return (ROOT / relative).read_text(encoding='utf-8')


def function(text, name):
    tree = ast.parse(text)
    lines = text.splitlines()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return '\n'.join(lines[node.lineno - 1:node.end_lineno])
    raise AssertionError(f'missing function {name}')


def require(text, *needles):
    for needle in needles:
        assert needle in text, f'missing recovery contract: {needle}'


def main():
    lsm = source('source/entry/kernel/t1os_lsm.c')
    protected = re.search(
        r'static const char \*prot_nonrec\[\]\s*=\s*\{(.*?)\};',
        lsm, re.DOTALL)
    assert protected and '"/.ephemeral"' not in protected.group(1)
    require(
        lsm,
        'static bool t1os_is_ephemeral_path',
        'if (t1os_is_ephemeral_path(name)) {',
        't1os_struct_path_is_ephemeral(&destination)',
        'static bool t1os_is_reign_time_output_path',
        '!strcmp(target, "/.ephemeral")',
    )

    hardware_init = source('source/entry/init/init hardware.sh')
    software_init = source('source/entry/init/init software.sh')
    require(hardware_init, 'nodev,nosuid,mode=1777', 'mkdir -m 01733 "$ephemeral/network"')
    require(software_init, 'mode=1777,nosuid,nodev', 'mkdir -m 01733 "/mnt/.ephemeral/network"')

    goddess = source('source/build software/GODDESS/GODDESS.py')
    early = function(goddess, 'main')
    require(
        function(goddess, 'createephemeral'),
        'os.chmod(EPHEMERALTIER, 0o1777)',
    )

    inputserver = source('source/build software/input/inputserver.py')
    windowserver = source('source/build software/windows/windowserver.py')
    pythonmanager = source('source/build software/python/python.py')
    network = source('source/build software/network/network.py')
    for implementation, name in (
        (function(inputserver, 'makepaths'), 'InputServer'),
        (function(windowserver, 'securedirectory'), 'WindowServer'),
        (function(pythonmanager, 'prepare_socket_directory'), 'Python manager'),
    ):
        require(
            implementation,
            "parent == '/.ephemeral'" if name == 'Python manager'
            else 'parent == "/.ephemeral"',
            '0o1777',
        )
    require(
        function(network, 'writeinitialstate'),
        'statmodule.S_IMODE(status.st_mode) != 0o1733',
    )
    assert (
        early.index('normaliseservicesettings()') <
        early.index('normalisedesktopsettings()') <
        early.index('birth(PRESTARTOPS)')
    )
    require(
        function(goddess, 'normaliseservicesettings'),
        'directorymode=0o755, filemode=0o644',
        "('virtualbox.txt', b'true\\n')",
        "('timezone.txt', b'Australia/Sydney\\n')",
        'os.mknod(',
        'statmodule.S_IFREG | 0o644',
        "('common.txt', 'atreyan.txt')",
        'rootownedfiles=rootownedfiles',
        "if relative == 'network':",
        'os.fchmod(descriptor, 0o777)',
    )
    require(
        function(goddess, 'normalisedesktopsettings'),
        "'array'",
        "'chromium'",
        "'expanse'",
        "'operations centre'",
        'directorymode=0o700, filemode=0o600',
    )
    require(goddess, "('python', PYTHONSCRIPT, 'behind')")
    assert "('Python', PYTHONSCRIPT" not in goddess

    network = source('source/build software/network/network.py')
    require(
        network,
        'def ensurenetworkruntime():',
        'os.chmod(NETWORKRUNTIME, 0o1733)',
        'os.chmod(temporary, 0o644)',
        'except OSError:',
    )

    operations = source('source/build software/operations/operationsserver.py')
    operations_main = function(operations, 'main')
    assert operations_main.index('initialiseclockfrommotherboard()') < operations_main.index('loadstate()')
    require(
        operations,
        "'TIME_SAMPLE_SET': frozenset(('reign',))",
        'zoneinfo.ZoneInfo.from_file(stream, key=name)',
        "if kind == 'brick':",
        "return ['--run-file', target]",
    )

    zonepath = ROOT / 'source/software/chromium/resources/zoneinfo/Australia/Sydney'
    with zonepath.open('rb') as stream:
        sydney = zoneinfo.ZoneInfo.from_file(stream, key='Australia/Sydney')
    wallclock = datetime.datetime(2026, 8, 16, 21, 48, tzinfo=sydney)
    assert wallclock.utcoffset() == datetime.timedelta(hours=10)
    assert datetime.datetime.fromtimestamp(wallclock.timestamp(), sydney) == wallclock

    reign = source('source/build software/reign/reign.py')
    require(
        function(reign, 'syncinternettime'),
        "'action': 'TIME_SAMPLE_SET'",
        "result.get('status') != 'ok'",
    )
    assert reign.index("if __name__ == '__main__':") < reign.index('    initialise()')

    array = source('source/build software/array/array.py')
    typedlaunch = function(array, 'opsrun')
    require(typedlaunch, '"op": "LAUNCH_CATALOGUE"', '"args": list(args)')
    assert '"op": "RUN"' not in typedlaunch
    require(
        function(array, 'runitem'),
        'prog = BRICKPROG if ispython else target',
        "arguments = ['--run-file', target] if ispython else []",
    )
    brick = source('source/build software/brick/brick.py')
    require(function(brick, 'main'), 'if startupfile is not None:', 'run([str(startupfile)])')

    operationscentre = source(
        'source/build software/operations/operationscentre.py')
    require(
        operationscentre,
        'VERSION = 2',
        'SORTREVERSE = False',
        "< 2 and SORTCOLUMN == 'name'",
    )

    expanse = source('source/build software/expanse/expanse.py')
    require(
        function(expanse, 'masterimagesettingstick'),
        'loadmasterimagesettings()',
        'painttaskbar(sock)',
    )

    window = source('source/build software/windows/windowserver.py')
    picker = function(window, 'pickerfinish')
    require(picker, 'The authenticated Picker process has already performed filesystem')
    for forbidden in ('os.path.isfile', 'os.path.isdir', 'os.access', 'pickerpathwritable'):
        assert forbidden not in picker, f'WindowServer repeated Picker probe: {forbidden}'

    print('userspace boot recovery contracts: passed')


if __name__ == '__main__':
    main()
