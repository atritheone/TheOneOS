#!/usr/bin/env python3

"""Verify Angel's boot and recovery ownership and speaking style."""

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
from pathlib import Path
import re
import sys


ROOT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parents[2]
INIT = ROOT / "source/entry/init/init hardware.sh"
RECOVERY = ROOT / "source/entry/init/angel recovery.sh"
CONTRACT = ROOT / "source/entry/init/ANGEL.md"
GODDESS = ROOT / "source/build software/GODDESS/GODDESS.py"


def require(source: str, needle: str, context: str) -> None:
    if needle not in source:
        raise RuntimeError(f"{context} is missing {needle!r}")


def test_initramfs_voice() -> None:
    source = INIT.read_text(encoding="utf-8")

    for needle in (
        "Angel is the guardian of the T1OS boot partition",
        "angel_prefix='~ '",
        "angel_suffix=' ~'",
        "printf '%s%s%s\\n' \"$angel_prefix\" \"$message\" \"$angel_suffix\"",
        "boot_status 'I have prepared the root drive and will now hand control to GODDESS.'",
    ):
        require(source, needle, "Angel's initramfs voice")

    if "tr '[:lower:]' '[:upper:]'" in source:
        raise RuntimeError("Angel's initramfs voice still uses GODDESS-style uppercase")
    if "awaken T1OS" in source:
        raise RuntimeError("Angel's successful boot does not hand control to GODDESS")

    shorthand = re.compile(r"(?<![\w.-])T1OS(?![\w.-])", re.IGNORECASE)
    for line_number, line in enumerate(source.splitlines(), start=1):
        if re.search(r"\b(?:log|boot_status|rescue)\s+[\"']", line) and shorthand.search(line):
            raise RuntimeError(
                f"Angel uses the T1OS shorthand in dialogue at line {line_number}"
            )


def test_ownership_contract() -> None:
    source = CONTRACT.read_text(encoding="utf-8")

    for needle in (
        "bootloader,",
        "kernel and initramfs handoff",
        "system reset, and reinstallation",
        "handing control to GODDESS",
        "GPT partition 2",
        "root filesystem is GPT partition 3",
        "must not contain a `/.recover` copy",
        "It never exposes a general shell",
        "reads the user's keyboard from the",
        "Character dialogue uses the formal name `The One OS`",
        "~ This is an example line of Angel. ~",
    ):
        require(source, needle, "Angel's ownership contract")


def test_recovery_cli_voice() -> None:
    source = RECOVERY.read_text(encoding="utf-8")

    for needle in (
        "deliberately uses only initramfs tools",
        "angel_say()",
        "angel_ask()",
        "angel_select_input_console()",
        "angel_input_console=/dev/tty0",
        "angel_input_console=/dev/console",
        'IFS= read -r answer <"$angel_input_console"',
        "printf '%s%s%s\\n> '",
        '"$angel_prefix" "$message" "$angel_suffix"',
        "Choose python, build, reset, reinstall, restart, or power off.",
        "Should I repair Python? Answer yes or no.",
        "Type reset to continue or no to go back.",
        "Type reinstall to continue or no to go back.",
        "I repaired Python and verified every restored file.",
        "I reset the build software and verified every restored file.",
        "I reset The One OS and kept the user files.",
        "I reinstalled The One OS and verified the clean installation.",
    ):
        require(source, needle, "Angel's recovery CLI")

    if re.search(r"\b(?:exec|switch_root)\b[^\n]*(?:/bin/)?(?:a|ba|da|k|z)?sh\b", source):
        raise RuntimeError("Angel's production recovery CLI exposes a shell")
    if re.search(r"\bpython(?:3(?:\.\d+)?)?\b", source, re.IGNORECASE):
        allowed = (
            "must never import Python",
            "angel_repair_python",
            "repair Python",
            "restoring Python",
            "repaired Python",
            "label=$label",
            "python|build|reset|reinstall",
            "python) angel_repair_python",
            "python)",
            "journal_write python",
            "software/python",
            "catalogue/python",
            "restore_tree \"$item\" Python",
            "Choose python",
        )
        for line_number, line in enumerate(source.splitlines(), start=1):
            if re.search(r"\bpython(?:3(?:\.\d+)?)?\b", line, re.IGNORECASE) and not any(
                text.lower() in line.lower() for text in allowed
            ):
                raise RuntimeError(
                    f"Angel's recovery engine invokes or imports Python at line {line_number}"
                )

    shorthand = re.compile(r"(?<![\w.-])T1OS(?![\w.-])", re.IGNORECASE)
    for line_number, line in enumerate(source.splitlines(), start=1):
        if re.search(r"\bangel_(?:say|ask)\s+[\"']", line) and shorthand.search(line):
            raise RuntimeError(
                f"Angel uses the T1OS shorthand in recovery dialogue at line {line_number}"
            )


def test_runtime_recovery_voice() -> None:
    source = GODDESS.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(GODDESS))
    selected = []

    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name)
            and target.id in {"ANGELPREFIX", "ANGELSUFFIX"}
            for target in node.targets
        ):
            selected.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in {
            "formalsystemname",
            "formatangel",
        }:
            selected.append(node)

    namespace: dict[str, object] = {"re": re}
    exec(
        compile(ast.Module(body=selected, type_ignores=[]), str(GODDESS), "exec"),
        namespace,
    )
    formatangel = namespace.get("formatangel")
    formalsystemname = namespace.get("formalsystemname")

    if not callable(formatangel) or not callable(formalsystemname):
        raise RuntimeError("GODDESS does not expose the character dialogue formatters")
    if formatangel("This is an example line of Angel.") != (
        "~ This is an example line of Angel. ~"
    ):
        raise RuntimeError("Angel's recovery formatter does not use her exact voice")
    if formatangel("T1OS is ready.\nSecond line.") != (
        "~ The One OS is ready. ~\n~ Second line. ~"
    ):
        raise RuntimeError("Angel's recovery formatter does not frame every line")
    if formalsystemname("T1OS is ready.") != "The One OS is ready.":
        raise RuntimeError("GODDESS does not use the formal operating-system name")
    for technical_name in ("T1OS_DISPLAY_CONSOLE_FD", "t1os.graphics", "t1os-root"):
        if formalsystemname(technical_name) != technical_name:
            raise RuntimeError(f"The formal-name formatter damaged {technical_name!r}")

    print_function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "print"
    )
    print_source = ast.get_source_segment(source, print_function) or ""
    require(
        print_source,
        "message = formalsystemname(",
        "GODDESS's formal operating-system name",
    )

    recovery_words = ("recovery", "recovering", "reinstall", "resetting the os", "reset the os")
    violations = []

    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "print"
        ):
            continue
        text = " ".join(
            part.value
            for argument in node.args
            for part in ast.walk(argument)
            if isinstance(part, ast.Constant) and isinstance(part.value, str)
        ).lower()
        if any(word in text for word in recovery_words):
            violations.append(node.lineno)

    if violations:
        raise RuntimeError(
            "Recovery speech is still routed through GODDESS at lines "
            + ", ".join(str(line) for line in violations)
        )


def main() -> int:
    test_initramfs_voice()
    test_ownership_contract()
    test_recovery_cli_voice()
    test_runtime_recovery_voice()
    print("Angel voice tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
