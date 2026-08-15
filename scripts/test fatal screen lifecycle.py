from __future__ import annotations

import ast
import re
import struct
import sys
from pathlib import Path


ROOT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
GODDESS = ROOT / "source/build software/GODDESS/GODDESS.py"
ANIMATION = ROOT / "source/boot/boot animation/boot animation.py"
PUSH = ROOT / "scripts/push to disk.ps1"
ARTWORK = ROOT / "flash/red_screen_of_death.png"


def function(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"missing function {name}")


def selected_namespace(source: str, names: tuple[str, ...], initial: dict) -> dict:
    tree = ast.parse(source)
    nodes = [function(tree, name) for name in names]
    namespace = dict(initial)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "<fatal-screen-test>", "exec"), namespace)
    return namespace


def require(source: str, value: str, label: str) -> None:
    if value not in source:
        raise AssertionError(f"{label} is missing {value!r}")


def main() -> None:
    goddess = GODDESS.read_text(encoding="utf-8")
    animation = ANIMATION.read_text(encoding="utf-8")
    push = PUSH.read_text(encoding="utf-8")
    goddess_tree = ast.parse(goddess, filename=str(GODDESS))
    animation_tree = ast.parse(animation, filename=str(ANIMATION))

    namespace = selected_namespace(
        goddess,
        ("_fatalwords", "operationalfailureline"),
        {"re": re},
    )
    failure = namespace["operationalfailureline"](
        "Window Server",
        "GPU presentation watchdog timed out: page flip stalled",
    )
    if failure != "window server failure - gpu presentation watchdog timed out - page flip stalled":
        raise AssertionError(f"unexpected fatal failure line {failure!r}")
    if failure != failure.lower() or ":" in failure:
        raise AssertionError("fatal failure line is not lowercase and colon-free")

    animation_namespace = selected_namespace(
        animation,
        ("normalisefatalfailure",),
        {},
    )
    animation_failure = animation_namespace["normalisefatalfailure"](
        "Driver Server Failure: DEVICE POLICY LOST"
    )
    if animation_failure != "driver server failure - device policy lost":
        raise AssertionError(f"renderer changed the failure grammar {animation_failure!r}")

    require(animation, 'title = "FATAL SYSTEM ERROR"', "fatal screen title")
    require(animation, 'status = "restarting..."', "fatal restart status")
    require(animation, 'mode == "fatal"', "fatal animation mode")
    require(animation, '"role": "system animation" if systemtransition', "topmost system role")
    require(animation, 'FATALIMAGE = "/the one/resources/system/red_screen_of_death.png"', "runtime artwork path")
    require(goddess, "environment['T1OS_BOOT_GRAPHICS'] = 'cpu'", "independent CPU fatal scene")

    supervise = ast.get_source_segment(goddess, function(goddess_tree, "supervise")) or ""
    operational = ast.get_source_segment(goddess, function(goddess_tree, "operationalfatal")) or ""
    shutdown = ast.get_source_segment(goddess, function(goddess_tree, "shutdownsequence")) or ""
    goddess_main = ast.get_source_segment(goddess, function(goddess_tree, "main")) or ""

    require(supervise, "OPERATIONALCRITICALTASKS", "critical runtime supervision")
    require(supervise, "OPERATIONALRESTARTLIMIT", "bounded runtime recovery")
    require(supervise, "operationalfatal(", "runtime fatal escalation")
    require(operational, "startfatalanimation(component, reason)", "fatal presentation launch")
    require(operational, "shutdownsequence('restart', presentation=presentation)", "fatal restart handoff")
    require(shutdown, "presentation if presentation is not None", "presentation-preserving shutdown")
    require(goddess_main, "SYSTEMPHASE = 'operational'", "operational phase transition")

    if goddess_main.index("birth(POSTSTARTOPS)") >= goddess_main.index("SYSTEMPHASE = 'operational'"):
        raise AssertionError("t1os becomes operational before the desktop starts")
    if "'network'" in goddess[goddess.index("OPERATIONALCRITICALTASKS"):goddess.index("OPERATIONALRESTARTLIMIT")]:
        raise AssertionError("a network failure was made system-fatal")

    data = ARTWORK.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise AssertionError("fatal screen artwork is not PNG")
    width, height = struct.unpack(">II", data[16:24])
    if (width, height) != (1672, 941):
        raise AssertionError(f"unexpected fatal screen artwork size {(width, height)}")

    require(push, "$fatalScreenSource", "fatal artwork build input")
    require(push, 'system_resource_destination="$mount_point/the one/resources/system"', "fatal artwork destination")
    require(push, "red_screen_of_death.png", "fatal artwork synchronization")

    print("Fatal screen lifecycle validation passed.")


if __name__ == "__main__":
    main()
