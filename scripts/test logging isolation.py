"""Regression checks for per-software log isolation."""

import ast
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import types


ROOT = Path(__file__).resolve().parents[1]
GODDESS = ROOT / "source" / "build software" / "GODDESS" / "GODDESS.py"
REIGN = ROOT / "source" / "build software" / "reign" / "reign.py"
HARDWARE_INIT = ROOT / "resource" / "entry" / "init" / "init hardware.sh"


def loadlogging(systemroot):

    source = GODDESS.read_text(encoding="utf-8")
    tree = ast.parse(source)
    names = {
        "softwarelogpath",
        "_LazyLogPopen",
        "_securedlaunchoptions",
        "_validateprofilecommand",
        "popenisolated",
    }
    selected = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names
    ]
    module = types.SimpleNamespace()
    namespace = {
        "SYSTEMROOT": str(systemroot),
        "os": os,
        "subprocess": subprocess,
        "threading": threading,
        "time": time,
    }
    exec(compile(ast.Module(body=selected, type_ignores=[]), GODDESS, "exec"), namespace)
    module.softwarelogpath = namespace["softwarelogpath"]
    module.popenisolated = namespace["popenisolated"]
    return module


def checkruntime():

    with tempfile.TemporaryDirectory() as temporary:
        systemroot = Path(temporary)
        logging = loadlogging(systemroot)
        firstline = "first software stdout"
        firsterror = "first software stderr"
        secondline = "second software stdout"

        first = logging.popenisolated(
            [
                sys.executable,
                "-c",
                (
                    "import sys; "
                    f"print({firstline!r}); "
                    f"print({firsterror!r}, file=sys.stderr)"
                ),
            ],
            softwarepath="/the one/build/first/first.py",
        )
        assert first.wait(timeout=10) == 0

        secondlog = systemroot / "logs" / "custom-second.log"
        second = logging.popenisolated(
            [sys.executable, "-c", f"print({secondline!r})"],
            softwarepath="/the one/build/second/second.py",
            logpath=str(secondlog),
        )
        assert second.wait(timeout=10) == 0

        firstlog = systemroot / "logs" / "first.py.log"
        firsttext = firstlog.read_text(encoding="utf-8")
        secondtext = secondlog.read_text(encoding="utf-8")

        assert firstline in firsttext
        assert firsterror in firsttext
        assert secondline not in firsttext
        assert secondline in secondtext
        assert firstline not in secondtext
        assert firsterror not in secondtext

        silentlog = systemroot / "logs" / "silent.py.log"
        silent = logging.popenisolated(
            [sys.executable, "-c", "pass"],
            softwarepath="/the one/build/silent/silent.py",
        )
        assert silent.wait(timeout=10) == 0
        assert not silentlog.exists(), "silent software created an empty log"

        delayedlog = systemroot / "logs" / "delayed.py.log"
        delayed = logging.popenisolated(
            [
                sys.executable,
                "-c",
                "import time; time.sleep(0.1); print('delayed output')",
            ],
            softwarepath="/the one/build/delayed/delayed.py",
        )
        assert not delayedlog.exists(), "log was created before software output"
        assert delayed.wait(timeout=10) == 0
        assert "delayed output" in delayedlog.read_text(encoding="utf-8")


def checklaunchers():

    files = {
        "window server": ROOT / "source" / "build software" / "windows" / "windowserver.py",
        "expanse": ROOT / "source" / "build software" / "expanse" / "expanse.py",
        "startup": ROOT / "source" / "build software" / "startup" / "startup.py",
        "operations centre": (
            ROOT / "source" / "build software" / "operations" / "operationscentre.py"
        ),
    }

    for name, path in files.items():
        source = path.read_text(encoding="utf-8")
        if name != "expanse":
            assert "popenisolated(" in source, (
                f"{name} does not use isolated launching"
            )
        assert "subprocess.Popen(" not in source, f"{name} has an inherited-output launch"
        assert "subprocess.run(" not in source, f"{name} has an inherited-output run"

    graphics = (
        ROOT / "source" / "build software" / "graphics" / "graphics.py"
    ).read_text(encoding="utf-8")
    graphicslog = graphics.split("def log(msg, flush=False):", 1)[1].split(
        "def normalisecolor", 1
    )[0]
    assert "sys.stderr" not in graphicslog

    goddess = (
        ROOT / "source" / "build software" / "GODDESS" / "GODDESS.py"
    ).read_text(encoding="utf-8")
    for eagerlog in (
        "with open(LOGPATHS['boot animation']",
        "with open(LOGPATHS['power animation']",
        "with open(STARTUPLOG",
        "with open(logpath, 'ab')",
        "with open(GRAPHICSSOFTWARELOG, 'ab')",
        "for path in (STARTUPLOG, LOCKSCREENLOG)",
    ):
        assert eagerlog not in goddess, f"GODDESS still eagerly opens {eagerlog}"

    diagnosticlaunch = goddess.split(
        "if kernelcommandlineoption('t1os.chromium-diagnostic=1'):", 1
    )[1].split("time.sleep(1)", 1)[0]
    assert "popenisolated(" in diagnosticlaunch
    assert "'w'," not in diagnosticlaunch, (
        "Chromium boot diagnostics still create their log before output"
    )

    network = (
        ROOT / "source" / "build software" / "network" / "network.py"
    ).read_text(encoding="utf-8")
    assert "loghandle = open(LOGFILE" not in network

    operations = (
        ROOT / "source" / "build software" / "operations" / "operations.py"
    ).read_text(encoding="utf-8")
    assert "logfile = open(logpath" not in operations

    reign = REIGN.read_text(encoding="utf-8")
    for loggingname in (
        "def formatlog(",
        "def emitlog(",
        "def softwarelogpath(",
        "class _LazyLogPopen(",
        "def popenisolated(",
    ):
        assert loggingname not in reign, f"reign still owns {loggingname}"

    for loggingname in (
        "def formatlog(",
        "def emitlog(",
        "def softwarelogpath(",
        "class _LazyLogPopen(",
        "def popenisolated(",
    ):
        assert loggingname in goddess, f"GODDESS does not own {loggingname}"

    hardwareinit = HARDWARE_INIT.read_text(encoding="utf-8")
    archive = hardwareinit.split("archive_previous_boot_logs() {", 1)[1].split(
        "persist_ntfs_health_report() {", 1
    )[0]
    for cleanup in (
        'for evidence in "$logs"/*.log; do',
        '[ -s "$evidence" ] && continue',
        '"$busybox" rm -f "$evidence"',
    ):
        assert cleanup in archive, (
            "the boot archive does not discard zero-line service logs"
        )


def main():

    checkruntime()
    checklaunchers()
    print("logging isolation checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
