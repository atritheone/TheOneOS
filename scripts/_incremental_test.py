"""Bootstrap used by Python test entrypoints to enter the incremental runner."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


def guard(script_path: str, arguments: list[str]) -> bool:
    script = Path(script_path).resolve()
    project = Path(__file__).resolve().parent.parent
    try:
        relative = script.relative_to(project).as_posix()
    except ValueError:
        relative = script.as_posix()
    if os.environ.get("T1OS_INCREMENTAL_ACTIVE_SCRIPT") == relative:
        return False
    runner = Path(__file__).resolve().parent / "incremental_test.py"
    completed = subprocess.run(
        [sys.executable, str(runner), "run", "--script", str(script), "--", *arguments],
        cwd=project,
        check=False,
    )
    if completed.returncode:
        raise SystemExit(completed.returncode)
    return True
