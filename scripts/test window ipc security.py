#!/usr/bin/env python3
"""Static security contract checks for T1OS input/compositor IPC.

This test deliberately parses source without importing T1OS modules.  Pass an
isolated source copy with --source-root when running it outside the target OS.
"""

import argparse
import ast
from pathlib import Path


FILES = {
    "input": Path("source/build software/input/inputserver.py"),
    "window": Path("source/build software/windows/windowserver.py"),
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
        "identity.get(\"domain\") == \"window\"",
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
