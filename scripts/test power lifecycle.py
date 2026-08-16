from pathlib import Path
import ast
import errno
import io
import importlib.util
import sys
import threading
import types

sys.dont_write_bytecode = True


def require(source, text, label):
    if text not in source:
        raise RuntimeError(f"{label} is missing: {text}")


def forbid(source, text, label):
    if text in source:
        raise RuntimeError(f"{label} still contains forbidden text: {text}")


def function(tree, name):
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise RuntimeError(f"function is missing: {name}")


def ordered(source, labels):
    positions = []
    for label in labels:
        position = source.find(label)
        if position < 0:
            raise RuntimeError(f"shutdown ordering marker is missing: {label}")
        positions.append(position)
    if positions != sorted(positions):
        raise RuntimeError(f"shutdown ordering is incorrect: {' -> '.join(labels)}")


def testconsoleoutputrecovery(source, tree):
    selected = [
        node
        for node in tree.body
        if (
            isinstance(node, ast.ClassDef)
            and node.name == "ConsoleMirror"
        )
        or (
            isinstance(node, ast.FunctionDef)
            and node.name in {
                "recordoutputfailure",
                "displayconsolefallback",
                "formalsystemname",
                "print",
            }
        )
    ]
    module = ast.Module(body=selected, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {
        "os": __import__("os"),
        "re": __import__("re"),
        "sys": sys,
        "_builtin_print": print,
        "formatlog": lambda software, message: (
            f"[01:08:5AE 1:02:03 PM] [{software}] {message}"
        ),
        "GODDESSPRINTPREFIX": __import__("re").compile(r"a^"),
        "OUTPUTFAILURELOG": "/path/that/does/not/exist/GODDESS.py.log",
        "OUTPUTFAILURELIMIT": 64,
        "_OUTPUTFAILURECOUNT": 0,
        "_GODDESSDISPLAYPHRASES": set(),
        "_GODDESSDISPLAYLOCK": threading.Lock(),
        "_GODDESSDISPLAYONCEPHRASES": ("I CANNOT CONTINUE",),
    }
    exec(compile(module, "<goddess-output-recovery-test>", "exec"), namespace)

    class FailedConsole:
        def write(self, value):
            raise OSError(errno.EIO, "synthetic console write failure")

        def flush(self):
            raise OSError(errno.EIO, "synthetic console flush failure")

    display = io.StringIO()
    mirror = namespace["ConsoleMirror"](FailedConsole(), display)
    if mirror.write("recovery survives\n") != len("recovery survives\n"):
        raise RuntimeError("console mirror did not acknowledge fallback output")
    mirror.flush()
    if display.getvalue() != "recovery survives\n":
        raise RuntimeError("console mirror lost the surviving display stream")

    both_failed = namespace["ConsoleMirror"](FailedConsole(), FailedConsole())
    if both_failed.write("diagnostic only") != len("diagnostic only"):
        raise RuntimeError("dual console failure escaped the diagnostic boundary")
    both_failed.flush()

    fallbacks = []

    def failed_print(*args, **kwargs):
        raise OSError(errno.EIO, "synthetic PID 1 stdout failure")

    namespace["_builtin_print"] = failed_print
    namespace["recordoutputfailure"] = lambda *args: None
    namespace["displayconsolefallback"] = (
        lambda value: fallbacks.append(value) or True
    )
    namespace["print"]("graphics recovery continues", flush=True)
    if not fallbacks or "GRAPHICS RECOVERY CONTINUES" not in fallbacks[0]:
        raise RuntimeError("PID 1 print did not use its display fallback")
    if "[01:08:5AE 1:02:03 PM]" in fallbacks[0]:
        raise RuntimeError("PID 1 display fallback retained a log timestamp")

    namespace["_builtin_print"] = print
    screen = io.StringIO()
    previous_stdout = sys.stdout
    try:
        sys.stdout = screen
        namespace["print"]("screen message")
        namespace["print"]("screen message")
        namespace["print"](
            "[01:08:5AE 1:02:03 PM] [driver server] child message"
        )
        namespace["print"]("first phrase\nsecond phrase\nfirst phrase")
        namespace["print"]("second phrase\nthird phrase")
        namespace["print"]("I cannot continue. The first reason remains.")
        namespace["print"](
            "I cannot continue because the second reason is different."
        )
        namespace["print"](
            "I cannot continue, so I will keep diagnostics available."
        )
        namespace["print"]("First context. Shared status phrase.")
        namespace["print"]("Second context. Shared status phrase.")
        namespace["print"](
            "[01:08:5AE 1:02:03 PM] [driver server] child message"
        )
    finally:
        sys.stdout = previous_stdout
    if screen.getvalue() != (
        "SCREEN MESSAGE\n"
        "[DRIVER SERVER] CHILD MESSAGE\n"
        "FIRST PHRASE\nSECOND PHRASE\n"
        "THIRD PHRASE\n"
        "I CANNOT CONTINUE. THE FIRST REASON REMAINS.\n"
        "THE SECOND REASON IS DIFFERENT.\n"
        "I WILL KEEP DIAGNOSTICS AVAILABLE.\n"
        "FIRST CONTEXT. SHARED STATUS PHRASE.\n"
        "SECOND CONTEXT.\n"
        "[DRIVER SERVER] CHILD MESSAGE\n"
    ):
        raise RuntimeError(
            f"screen output timestamp policy regressed: {screen.getvalue()!r}"
        )

    logfile = io.StringIO()
    namespace["print"]("file message", file=logfile)
    namespace["print"]("file message", file=logfile)
    if logfile.getvalue() != (
        "[01:08:5AE 1:02:03 PM] FILE MESSAGE\n"
        "[01:08:5AE 1:02:03 PM] FILE MESSAGE\n"
    ):
        raise RuntimeError(
            f"file output lost its timestamp: {logfile.getvalue()!r}"
        )


def main():
    root = Path(sys.argv[1]).resolve()
    animation_path = root / "source/boot/boot animation/boot animation.py"
    goddess_path = root / "source/build software/GODDESS/GODDESS.py"
    power_path = root / "source/build software/operations/operations.py"
    expanse_path = root / "source/build software/expanse/expanse.py"
    brick_path = root / "source/build software/brick/brick.py"
    windowserver_path = root / "source/build software/windows/windowserver.py"
    init_hardware_path = root / "source/entry/init/init hardware.sh"

    sources = {
        "animation": animation_path.read_text(encoding="utf-8"),
        "goddess": goddess_path.read_text(encoding="utf-8"),
        "power": power_path.read_text(encoding="utf-8"),
        "expanse": expanse_path.read_text(encoding="utf-8"),
        "brick": brick_path.read_text(encoding="utf-8"),
        "windowserver": windowserver_path.read_text(encoding="utf-8"),
        "init_hardware": init_hardware_path.read_text(encoding="utf-8"),
    }
    trees = {
        name: ast.parse(source, filename=str({
            "animation": animation_path,
            "goddess": goddess_path,
            "power": power_path,
            "expanse": expanse_path,
            "brick": brick_path,
            "windowserver": windowserver_path,
        }[name]))
        for name, source in sources.items()
        if name != "init_hardware"
    }

    testconsoleoutputrecovery(sources["goddess"], trees["goddess"])

    for tree_name, names in (
        ("power", ("normaliseaction", "requestpower")),
        (
            "goddess",
            (
                "setuppowerserver",
                "receivepowerrequest",
                "startpoweranimation",
                "stopphase",
                "stopstragglers",
                "armshutdownhealthgate",
                "shutdownsequence",
                "kernelpower",
                "main",
            ),
        ),
        ("animation", ("configurecontrol", "powerlayout", "drawpowerframe", "powerloop")),
    ):
        for name in names:
            function(trees[tree_name], name)

    for text in (
        'VALIDACTIONS = frozenset(("poweroff", "restart"))',
        '"format": 1',
        'connection.connect(SOCKETPATH)',
        'raise PowerRequestError("GODDESS power control is unavailable")',
    ):
        require(sources["power"], text, "power request protocol")

    for text in (
        'POWERCONTROLBASE = "/.ephemeral/power animation"',
        'mode in ("poweroff", "restart")',
        'systemtransition = powertransition or mode == "fatal"',
        '"role": "system animation" if systemtransition else "boot animation"',
        'powerlabel = "shutting down" if mode == "poweroff" else "restarting"',
        'drawpowerframe(powerlabel, dotframes()[0])',
        'powerloop(powerlabel)',
        'controlstate("visible", mode=mode)',
        'DOTFRAMETIME = 0.24',
        'DOTMINIMUMTIME = 0.72',
        'POWERFONT = "/the one/resources/fonts/atkinsonhyperlegiblenext.ttf"',
        'fullwidth = int(measuretext(label + "...", int(BOOTFONT), fontpath=POWERFONT))',
        'measuretext(label + ".", int(BOOTFONT), fontpath=POWERFONT)',
        'measuretext(label + "..", int(BOOTFONT), fontpath=POWERFONT)',
        '"font": POWERFONT',
        "fontpath=POWERFONT",
    ):
        require(sources["animation"], text, "power animation")

    forbid(sources["animation"], "restrart", "power animation copy")

    for text in (
        '"system animation"',
        'if role == "system animation":',
        'setfocus(wid)',
    ):
        require(sources["windowserver"], text, "system animation compositor role")

    for source_name in ("expanse", "brick"):
        source = sources[source_name]
        require(source, "requestpower(", f"{source_name} power integration")
        forbid(source, "libc.syscall(", f"{source_name} power integration")
        forbid(source, "0x4321fedc", f"{source_name} power integration")
        forbid(source, "0x1234567", f"{source_name} power integration")

    require(sources["expanse"], 'requestpower("poweroff")', "Expanse shutdown")
    require(sources["expanse"], 'requestpower("restart")', "Expanse restart")
    require(sources["expanse"], "while RUN:", "Expanse accepted-request hold")
    require(sources["brick"], "requestpower('poweroff')", "Brick shutdown")
    require(sources["brick"], "requestpower('restart')", "Brick restart")
    require(sources["brick"], "while RUNNING:", "Brick accepted-request hold")

    goddess_main = function(trees["goddess"], "main")
    early_returns = [
        node.lineno
        for node in ast.walk(goddess_main)
        if isinstance(node, ast.Return)
    ]
    if early_returns:
        raise RuntimeError(
            "PID 1 main still has boot-aborting return paths at lines "
            + ", ".join(str(line) for line in sorted(early_returns))
        )
    for text in (
        "'op': 'BOOTSTRAP'",
        "'operations': operationssnapshot()",
        "OPERATIONSSYNCREQUIRED = True",
        "syncoperations()",
    ):
        require(
            sources["goddess"],
            text,
            "non-blocking OperationsServer bootstrap",
        )
    for retired in ("OPERATIONFILEPATH", "operations.txt", "operations-registry"):
        if retired in sources["goddess"]:
            raise RuntimeError(
                f"PID 1 still contains retired operations recording path {retired}"
            )

    shutdown_node = function(trees["goddess"], "shutdownsequence")
    shutdown_source = ast.get_source_segment(sources["goddess"], shutdown_node) or ""
    ordered(
        shutdown_source,
        (
            "startpoweranimation(action)",
            "stopphase('session'",
            "stopphase(\n        'services'",
            "stopphase('driver storage'",
            "stopstragglers(",
            "stopphase('display'",
            "stopanimationprocess(animation)",
            "armshutdownhealthgate(action)",
            "unmountpath(EPHEMERALTIER)",
            "remountrootreadonly()",
            "kernelpower('restart')",
        ),
    )

    for text in (
        "SYSTEMSTATE = 'request accepted'",
        "if SYSTEMSTATE != 'running':",
        "socket.SO_PEERCRED",
        "signal.SIGTERM",
        "signal.SIGKILL",
        "proc.terminate()",
        "RB_POWER_OFF = 0x4321FEDC",
        "RB_AUTOBOOT = 0x01234567",
        "operation = libc.reboot",
        "SHUTDOWNHEALTHREQUEST = os.path.join(",
        "'state=pending\\n'",
        "os.replace(temporary, SHUTDOWNHEALTHREQUEST)",
        "I armed the unmounted RootHealth shutdown gate",
    ):
        require(sources["goddess"], text, "GODDESS shutdown coordinator")

    restart_gate = sources["init_hardware"][
        sources["init_hardware"].index(
            'if [ -n "$angel_shutdown_health_action" ]; then'
        ):
        sources["init_hardware"].index(
            'if [ "$recovery" = 1 ]; then'
        )
    ]
    for text in (
        "angel_clear_shutdown_health_request",
        "I will restart through firmware boot order now.",
        '"$busybox" sync',
        '"$busybox" reboot -f',
    ):
        require(restart_gate, text, "initramfs restart completion")
    forbid(
        restart_gate,
        "continue requested restart",
        "initramfs restart completion",
    )

    goddesspackage = types.ModuleType("GODDESS")
    goddessmodule = types.ModuleType("GODDESS.GODDESS")
    goddessmodule.popenisolated = lambda *args, **kwargs: None
    sys.modules["GODDESS"] = goddesspackage
    sys.modules["GODDESS.GODDESS"] = goddessmodule

    spec = importlib.util.spec_from_file_location("t1os_power_test", power_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.normaliseaction(" POWEROff ") == "poweroff"
    assert module.normaliseaction("restart") == "restart"
    try:
        module.normaliseaction("hibernate")
    except ValueError:
        pass
    else:
        raise RuntimeError("power protocol accepted an unsupported action")

    print("Power lifecycle validation passed.")


if __name__ == "__main__":
    main()
