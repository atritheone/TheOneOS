"""Interactive fixture for the graphical Brick terminal emulator."""

import os
import shutil
import sys

import humanize


RESULT_PATH = "/master/development/terminal_test.result"


def write_result(value):
    with open(RESULT_PATH, "w", encoding="utf-8") as stream:
        stream.write(value + "\n")


def main():
    size = shutil.get_terminal_size(fallback=(0, 0))
    checks = {
        "stdin_tty": sys.stdin.isatty(),
        "stdout_tty": sys.stdout.isatty(),
        "term": bool(os.environ.get("TERM")),
        "columns": size.columns > 0,
        "lines": size.lines > 0,
        "arguments": sys.argv[1:] == ["alpha", "two words"],
        "managed_module": humanize.naturalsize(1_234_567, binary=True) == "1.2 MiB",
    }

    print("\x1b[1;36mT1OS Brick terminal emulator fixture\x1b[0m")
    print(
        "tty stdin={} stdout={} TERM={} size={}x{}".format(
            checks["stdin_tty"],
            checks["stdout_tty"],
            os.environ.get("TERM", ""),
            size.columns,
            size.lines,
        )
    )
    print("arguments={!r}".format(sys.argv[1:]))
    print("humanize={}".format(humanize.naturalsize(1_234_567, binary=True)))
    response = input("terminal input> ")
    checks["interactive_input"] = response == "interactive answer"
    print("\x1b[32mreceived={!r}\x1b[0m".format(response))

    if all(checks.values()):
        write_result("TERMINAL_EMULATOR_PASS")
        print("\x1b[1;32mTERMINAL_EMULATOR_PASS\x1b[0m")
        return 0

    failed = ", ".join(name for name, passed in checks.items() if not passed)
    write_result("TERMINAL_EMULATOR_FAIL {}".format(failed))
    print("\x1b[1;31mTERMINAL_EMULATOR_FAIL {}\x1b[0m".format(failed))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
