#!/usr/bin/env python3
"""Static security contract checks for T1OS input/compositor IPC.

This test deliberately parses source without importing T1OS modules.  Pass an
isolated source copy with --source-root when running it outside the target OS.
"""

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

import argparse
import ast
from pathlib import Path


FILES = {
    "input": Path("source/build software/input/inputserver.py"),
    "window": Path("source/build software/windows/windowserver.py"),
    "expanse": Path("source/build software/expanse/expanse.py"),
    "operations": Path("source/build software/operations/operationsserver.py"),
    "driver": Path("source/build software/drivers/driverserver.py"),
    "write": Path("source/build software/write/write.py"),
    "settings": Path("source/build software/settings/settings.py"),
    "chromium": Path("source/build software/chromium/chromium.py"),
}


def function_source(tree, text, name):
    lines = text.splitlines()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return "\n".join(lines[node.lineno - 1:node.end_lineno])
    raise AssertionError(f"missing function {name}")


def require(text, *values):
    for value in values:
        assert value in text, f"missing security contract: {value}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    args = parser.parse_args()
    root = args.source_root.resolve(strict=True)

    sources = {}
    trees = {}
    for name, relative in FILES.items():
        path = (root / relative).resolve(strict=True)
        assert path.is_relative_to(root), f"source escaped root: {path}"
        text = path.read_text(encoding="utf-8")
        sources[name] = text
        trees[name] = ast.parse(text, filename=str(path))

    input_source = sources["input"]
    require(
        input_source,
        "SO_PEERCRED",
        "candidate.get(\"domain\") == \"window\"",
        "RAWINPUTSUBSCRIPTIONS",
        "srv.listen(1)",
        "os.chmod(SOCKPATH, 0o600)",
        "raw input consumer already connected",
        "pidfd_open",
    )
    assert "WINDOWSERVERPATH" not in input_source

    window_source = sources["window"]
    require(
        window_source,
        "SO_PEERCRED",
        "os.chmod(SOCKPATH, 0o660)",
        "os.chmod(sockdir, 0o750)",
        "processsecuritydomain",
        "processidentitycurrent",
        "pidfd_open",
        "authorizedwindowrole",
        "input_injection_denied",
        "protected_auth_surface",
        "screen_capture",
        "guest_integration",
        "desktop_controller",
        "clienthasclipboardaccess",
        "CLIPBOARD_CLEAR",
        "O_NOFOLLOW",
        "videoauthorizationvalid",
        "CLIENTWINDOWLIMIT",
        "windowbufferallocationpermitted",
        "security_profile=\"picker\"",
        "waitforprocessidentity",
    )
    assert "def trustedscript(" not in window_source

    openarray = function_source(trees["window"], window_source, "openarray")
    require(openarray, 'broadcasttaskbarevent({"op": "SESSION_OPEN_ARRAY"})')
    for forbidden_launch in ("popenisolated(", "operationsregisterpid("):
        assert forbidden_launch not in openarray, (
            f"Win+E still bypasses session-owned catalogue launch: {forbidden_launch}")

    input_dispatch = function_source(
        trees["window"], window_source, "handleinputevent")
    require(
        input_dispatch,
        'WINSTATE.get("held") and st == "down" and key == "E"',
        "openarray()",
    )

    expanse_main = function_source(
        trees["expanse"], sources["expanse"], "main")
    require(
        expanse_main,
        'elif op == "SESSION_OPEN_ARRAY":',
        'launchstartsoftware("array")',
    )

    desktop_context = function_source(
        trees["expanse"], sources["expanse"], "rundesktopcontextaction")
    require(
        desktop_context,
        'desktopconfirm(sock, action, target)',
        'desktopclipboard(action, target)',
        'desktoppaste(sock, target)',
        'desktopstartfileaction(sock, "extract", target)',
        'desktopstartfileaction(sock, "compress", target)',
        'desktopproperties(sock, target)',
        'desktoparraysidebarpin(target)',
        'desktoptextdialog(',
    )
    assert "launcharraycontext" not in desktop_context
    assert "--context-action" not in desktop_context
    desktop_dialog = function_source(
        trees["expanse"], sources["expanse"], "desktopdialog")
    require(desktop_dialog, '"parent": DESKTOPID', '"op": "CREATE_DIALOG"')
    desktop_worker = function_source(
        trees["expanse"], sources["expanse"], "desktopworkerperform")
    for action in (
        '"create"', '"paste"', '"delete"', '"destroy"', '"link"',
        '"compress"', '"extract"',
    ):
        assert action in desktop_worker, f"Expanse desktop worker lacks {action}"
    require(
        sources["expanse"],
        'str(sys.argv[1]).strip().lower() == "desktop-action-worker"',
        "raise SystemExit(desktopworkermain())",
        'str(sys.argv[1]).strip().lower() == "desktop-executable-worker"',
        "raise SystemExit(desktopexecutablemain(sys.argv[2]))",
        'result["checks"]["desktop_native_context_dispatch"] = True',
    )
    assert not (
        root / "source/build software/expanse/desktopactions.py"
    ).exists(), "desktop actions were split out of expanse.py"

    catalogue_launch = function_source(
        trees["operations"], sources["operations"], "handlelaunchcatalogue")
    session_check = catalogue_launch.index(
        "session = sessionidentityfor(request['_peer']['pid'])")
    spawn = catalogue_launch.index("process, info = spawnsandboxed(")
    assert session_check < spawn, (
        "Operations spawns catalogue software before session ownership is proven")

    desktop_action = function_source(
        trees["operations"], sources["operations"], "handledesktopaction")
    require(
        sources["operations"],
        "DESKTOPACTIONWORKER = '/the one/build/expanse/expanse.py'",
        "'DESKTOP_ACTION': frozenset(('expanse',))",
    )
    require(
        desktop_action,
        "security_profile='desktop'",
        "preexec_fn=dropsandboxidentity",
        "[DESKTOPACTIONWORKER, 'desktop-action-worker']",
        "target = desktopactiontarget(",
        "root, request.get('target')",
        "[DESKTOPACTIONWORKER, 'desktop-executable-worker', target]",
        "desktop executable ownership or mode is unsafe",
    )

    volume_probe = function_source(
        trees["driver"], sources["driver"], "probevolumeaccess")
    require(
        volume_probe,
        "desktopmodepermits(rootstate, writable=writable)",
        "probestate.st_uid != 1000",
        "os.write(probedescriptor, b'1')",
    )
    volume_dac = function_source(
        trees["driver"], sources["driver"], "desktopmodepermits")
    require(volume_dac, "required = 0o7 if writable else 0o5")
    for forbidden_transition in (
        "os.fork(", "os.setuid(", "os.setgid(", "os.setgroups(",
    ):
        assert forbidden_transition not in volume_probe, (
            "DriverServer volume publication still performs an LSM-blocked "
            f"credential transition: {forbidden_transition}")

    user_read_path = function_source(
        trees["write"], sources["write"], "userreadpath")
    user_save_path = function_source(
        trees["write"], sources["write"], "usersavepath")
    require(user_read_path, "kernel policy and DAC decide readability")
    for forbidden_read_root in (
        "'/the one/logs'", "'/.ephemeral/volumes'", "'/software'",
        "os.path.commonpath",
    ):
        assert forbidden_read_root not in user_read_path, (
            f"Write still pre-denies an OS-readable path: {forbidden_read_root}")
    assert "'/the one/logs'" not in user_save_path, (
        "Write made the system log tier writable while admitting it for reading")
    read_payload = function_source(
        trees["write"], sources["write"], "readfilepayload")
    for forbidden_metadata_gate in (
        "metadata.st_uid", "stat.S_IWGRP", "metadata.st_nlink", "O_NOFOLLOW",
    ):
        assert forbidden_metadata_gate not in read_payload, (
            f"Write still rejects readable regular files by metadata: "
            f"{forbidden_metadata_gate}")
    picker_result = function_source(
        trees["write"], sources["write"], "handlepickerresult")
    assert "check(path)" not in picker_result
    require(
        sources["write"],
        "WRITESETTINGSFILE = '/the one/settings/write/settings.json'",
        "def legacywritesettingspath():",
        "def writeapplicationsettingssnapshot(payload):",
    )

    calls = [
        node for node in ast.walk(trees["window"])
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "popenisolated"
    ]
    assert calls, "expected fixed WindowServer launches"
    for call in calls:
        keywords = {keyword.arg for keyword in call.keywords}
        assert "security_profile" in keywords, (
            f"popenisolated call at line {call.lineno} has no security profile")

    createwindow = function_source(
        trees["window"], window_source, "createwindow")
    require(
        createwindow,
        "standard_dialog = bool(internal and",
        "identity = clients.get(cid, {}).get(\"identity\")",
    )

    pickerfinish = function_source(
        trees["window"], window_source, "pickerfinish")
    require(
        pickerfinish,
        "The authenticated Picker process has already performed filesystem",
        "pickerfilematches(path, config[\"filters\"])",
    )
    for forbidden_probe in (
        "os.path.isfile", "os.path.isdir", "os.path.islink",
        "os.access", "pickerpathwritable",
    ):
        assert forbidden_probe not in pickerfinish, (
            f"WindowServer repeated a Picker filesystem probe: {forbidden_probe}")

    clipset = function_source(trees["window"], window_source, "clipset")
    require(clipset, 'req.get("text")', "clienthasclipboardaccess")
    assert 'req.get("paths"' not in clipset

    settings_source = sources["settings"]
    assert "inputserver/accept.sock" not in settings_source
    require(settings_source, "'op': 'MOUSE_SETTINGS_SET'", "'winid': WINID")

    paste = function_source(
        trees["chromium"], sources["chromium"], "pasteclipboard")
    require(paste, 'message.get("text", "")')
    assert 'message.get("path"' not in paste

    print("window IPC static security contracts: passed")


if __name__ == "__main__":
    main()
