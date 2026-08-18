#!/usr/bin/env python3
"""Exercise cache reuse and invalidation without running a T1OS product test."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time


HERE = Path(__file__).resolve().parent.parent


def invoke(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(root / "scripts/incremental_test.py"),
            "run",
            "--script",
            str(root / "scripts/fixture.py"),
            "--",
            *arguments,
        ],
        cwd=root,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def count(root: Path) -> int:
    path = root / "counter.txt"
    return int(path.read_text(encoding="ascii")) if path.exists() else 0


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="t1os-incremental-selftest-") as temporary:
        root = Path(temporary)
        scripts = root / "scripts"
        scripts.mkdir()
        for name in ("incremental_test.py", "_incremental_test.py", "incremental test.ps1"):
            shutil.copy2(HERE / name, scripts / name)
        (root / "environment").mkdir()
        (root / "input.txt").write_text("one\n", encoding="utf-8")
        (scripts / "incremental tests.json").write_text(
            json.dumps(
                {
                    "format": 1,
                    "tasks": [
                        {
                            "id": "selftest.fixture",
                            "script": "scripts/fixture.py",
                            "profile": "pure",
                            "discover": False,
                            "inputs": ["input.txt"],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        (scripts / "fixture.py").write_text(
            """from pathlib import Path
import os
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _incremental_test import guard
if guard(__file__, sys.argv[1:]):
    raise SystemExit(0)
root = Path(__file__).resolve().parent.parent
counter = root / 'counter.txt'
counter.write_text(str(int(counter.read_text() if counter.exists() else '0') + 1))
if 'slow' in sys.argv:
    time.sleep(0.75)
if 'fail' in sys.argv:
    raise SystemExit(9)
""",
            encoding="utf-8",
        )

        first = invoke(root)
        require(first.returncode == 0 and "EXECUTE" in first.stdout, first.stdout)
        second = invoke(root)
        require(second.returncode == 0 and "REUSED" in second.stdout, second.stdout)
        require(count(root) == 1, "identical invocation executed twice")

        input_path = root / "input.txt"
        os.utime(input_path, None)
        touched = invoke(root)
        require("REUSED" in touched.stdout and count(root) == 1, "mtime-only touch reran test")

        input_path.write_text("two\n", encoding="utf-8")
        changed = invoke(root)
        require("EXECUTE" in changed.stdout and count(root) == 2, "content change did not rerun")
        input_path.write_text("one\n", encoding="utf-8")
        restored = invoke(root)
        require("REUSED" in restored.stdout and count(root) == 2, "restored content was retested")

        failed = invoke(root, "fail")
        require(failed.returncode == 9 and count(root) == 3, "failure fixture did not fail")
        failed_again = invoke(root, "fail")
        require(failed_again.returncode == 9 and count(root) == 4, "failed result was cached")

        input_path.write_text("concurrent\n", encoding="utf-8")
        command = [
            sys.executable,
            str(scripts / "incremental_test.py"),
            "run",
            "--script",
            str(scripts / "fixture.py"),
            "--",
            "slow",
        ]
        before = count(root)
        first_process = subprocess.Popen(command, cwd=root, text=True, stdout=subprocess.PIPE)
        second_process = subprocess.Popen(command, cwd=root, text=True, stdout=subprocess.PIPE)
        first_output = first_process.communicate(timeout=20)[0]
        second_output = second_process.communicate(timeout=20)[0]
        require(first_process.returncode == second_process.returncode == 0, "concurrent task failed")
        require(count(root) == before + 1, "concurrent callers executed the body more than once")
        require(
            sorted(("EXECUTE" in first_output, "EXECUTE" in second_output)) == [False, True],
            "concurrent callers did not single-flight",
        )

    print("Incremental runner self-test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
