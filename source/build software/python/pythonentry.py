"""Dispatch native T1OS Python commands to their installed entry points."""

from __future__ import annotations

import importlib.metadata
import os
import sys


def selected_entry_point(command):
    matches = []
    for group in ("console_scripts", "gui_scripts"):
        matches.extend(importlib.metadata.entry_points(group=group, name=command))
    if len(matches) != 1:
        if not matches:
            raise RuntimeError(command + " is not an installed Python command.")
        raise RuntimeError(command + " is provided by more than one Python package.")
    return matches[0]


def main(argv=None):
    values = list(sys.argv[1:] if argv is None else argv)
    if not values:
        print("T1OS Python command: missing command name", file=sys.stderr)
        return 126
    command = os.path.basename(values.pop(0))
    sys.argv = [command, *values]
    try:
        entry = selected_entry_point(command).load()
        result = entry()
        return int(result) if isinstance(result, int) else 0
    except Exception as error:
        print("T1OS Python command: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
