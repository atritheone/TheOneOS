#!/usr/bin/env python3
"""Unit tests for the read-only RootHealth refusal report classifier."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
CLASSIFIER = ROOT / "scripts" / "roothealth-repair" / "classify-report.py"


def report(code: str, ledger_hash: str = "ledger-a") -> dict[str, object]:
    return {
        "format": 3,
        "checker": "roothealth",
        "exit_code": 2,
        "result": "unsafe",
        "issues": [{
            "code": code,
            "pass": "complete-census",
            "message": "test refusal",
            "failed_predicates": ["coverage_complete=false"],
        }],
        "initial": {
            "dirty": True,
            "coverage": {"complete": False, "ledger_hash": ledger_hash},
        },
        "issue_ledger": {"ledger_hash": "issues-a"},
        "native_log": {
            "state": "clean",
            "parse_errors": 0,
            "unsupported_actions": 0,
        },
        "wal": {"state": "clean", "recovery_required": False},
    }


def run(*paths: Path) -> dict[str, object]:
    completed = subprocess.run(
        [sys.executable, str(CLASSIFIER), *(str(path) for path in paths)],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="roothealth-classifier-") as temporary:
        directory = Path(temporary)
        first = directory / "first.json"
        second = directory / "second.json"
        third = directory / "third.json"
        first.write_text(json.dumps(report("CENSUS_INCOMPLETE")), encoding="utf-8")
        second.write_text(json.dumps(report("CENSUS_INCOMPLETE")), encoding="utf-8")
        third.write_text(
            json.dumps(report("MFT_BITMAP_MISMATCH", "ledger-b")),
            encoding="utf-8",
        )

        single = run(first)
        assert single["recurrence"] == "single"
        assert single["reports"][0]["class"] == "unsupported"
        assert single["reports"][0]["pass"] == "complete-census"
        assert single["reports"][0]["failed_predicates"] == [
            "coverage_complete=false"
        ]

        exact = run(first, second)
        assert exact["recurrence"] == "exact"

        varying = run(first, third)
        assert varying["recurrence"] == "varying"
        assert varying["reports"][1]["class"] == "ambiguous-corruption"

        third.write_text(json.dumps(report("WAL_UNSAFE")), encoding="utf-8")
        assert run(third)["reports"][0]["class"] == "ambiguous-corruption"

    print("RootHealth report classifier tests passed.")


if __name__ == "__main__":
    main()
