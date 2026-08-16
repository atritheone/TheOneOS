
#!/usr/bin/env python3
"""Fail if the format-3 serializer reintroduces hand-counted JSON lengths."""

from __future__ import annotations

import pathlib
import re
import sys


LITERAL_EXPRESSION = re.compile(
    r'^(?:(?:"(?:\\.|[^"\\])*")|(?:name)|\s)+$', re.DOTALL
)


def call_arguments(source: str, start: int) -> list[str]:
    depth = 0
    quote = False
    escape = False
    argument_start = start
    arguments: list[str] = []
    for index in range(start, len(source)):
        character = source[index]
        if quote:
            if escape:
                escape = False
            elif character == "\\":
                escape = True
            elif character == '"':
                quote = False
            continue
        if character == '"':
            quote = True
        elif character == "(":
            depth += 1
        elif character == ")":
            if depth == 0:
                arguments.append(source[argument_start:index])
                return arguments
            depth -= 1
        elif character == "," and depth == 0:
            arguments.append(source[argument_start:index])
            argument_start = index + 1
    raise ValueError("unterminated RH_APPEND_LITERAL call")


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: check_roothealth_format3_literals.py SOURCE")
    path = pathlib.Path(sys.argv[1])
    source = path.read_text(encoding="utf-8")
    if re.search(r"rh_report_append\s*\(\s*report\s*,", source):
        raise SystemExit("direct hand-counted rh_report_append(report, ...) remains")
    count = 0
    marker = "RH_APPEND_LITERAL("
    offset = 0
    while True:
        found = source.find(marker, offset)
        if found < 0:
            break
        arguments = call_arguments(source, found + len(marker))
        # The macro declaration names its second parameter; call sites must
        # be C string-literal concatenations (plus the local `name` macro).
        if arguments[1].strip() == "literal":
            offset = found + len(marker)
            continue
        if len(arguments) != 2 or arguments[0].strip() not in {
            "report", "(report)"
        }:
            raise SystemExit(f"invalid RH_APPEND_LITERAL call at byte {found}")
        if not LITERAL_EXPRESSION.fullmatch(arguments[1]):
            raise SystemExit(f"non-literal RH_APPEND_LITERAL input at byte {found}")
        count += 1
        offset = found + len(marker)
    if count < 80:
        raise SystemExit(f"unexpectedly low checked literal count: {count}")
    print(f"roothealth-format3-literals checked={count} mismatches=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
