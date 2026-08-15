#!/usr/bin/env python3
import os
import re
import argparse


def isblank(line):

    return line.strip() == ""


def iscommentonly(line):

    s = line.lstrip()

    if s.startswith("#"):
        return True

    return False


def indent(line):

    i = 0
    while i < len(line) and line[i] in (" ", "\t"):
        i += 1

    return line[:i]


def stripcomment(line):

    out = []
    i = 0
    in_s = False
    in_d = False
    esc = False

    while i < len(line):

        ch = line[i]

        if esc:
            out.append(ch)
            esc = False
            i += 1
            continue

        if ch == "\\":
            out.append(ch)
            esc = True
            i += 1
            continue

        if not in_d and ch == "'" and not esc:
            in_s = not in_s
            out.append(ch)
            i += 1
            continue

        if not in_s and ch == '"' and not esc:
            in_d = not in_d
            out.append(ch)
            i += 1
            continue

        if not in_s and not in_d and ch == "#":
            break

        out.append(ch)
        i += 1

    return "".join(out).rstrip()


def istryheader(line):

    core = stripcomment(line).strip()

    if core == "try:":
        return True

    return False


def isexceptheader(line):

    core = stripcomment(line).strip()

    if core == "except:":
        return True

    m = re.fullmatch(r"except\s+Exception(\s+as\s+[A-Za-z_][A-Za-z0-9_]*)?\s*:", core)
    if m:
        return True

    return False


def isemptyhandlerstmt(line):

    core = stripcomment(line).strip()

    if core == "pass":
        return True

    if core == "continue":
        return True

    if core == "return":
        return True

    return False


def find_suite_indent(lines, start, end):

    i = start
    while i <= end:

        if isblank(lines[i]) or iscommentonly(lines[i]):
            i += 1
            continue

        return indent(lines[i])

    return None


def count_nonblank_noncomment(lines, start, end):

    c = 0
    last = None

    i = start
    while i <= end:

        if isblank(lines[i]) or iscommentonly(lines[i]):
            i += 1
            continue

        c += 1
        last = i
        i += 1

    return c, last


def try_unwrap(lines, i):

    n = len(lines)

    if not istryheader(lines[i]):
        return None

    tryindent = indent(lines[i])

    # find the next header at same indent: except / else / finally
    j = i + 1
    while j < n:

        if isblank(lines[j]) or iscommentonly(lines[j]):
            j += 1
            continue

        curindent = indent(lines[j])

        if len(curindent) < len(tryindent):
            return None

        if curindent == tryindent:

            core = stripcomment(lines[j]).strip()

            if core.startswith("except") or core == "else:" or core == "finally:":
                break

        j += 1

    if j >= n:
        return None

    # must be except header and allowed
    if not isexceptheader(lines[j]):
        return None

    suite_start = i + 1
    suite_end = j - 1

    # try suite must exist (at least one nonblank/noncomment line)
    suiteindent = find_suite_indent(lines, suite_start, suite_end)
    if suiteindent is None:
        return None

    if not suiteindent.startswith(tryindent) or len(suiteindent) == len(tryindent):
        return None

    # now parse except handler suite
    ex_head = j

    k = ex_head + 1
    while k < n and (isblank(lines[k]) or iscommentonly(lines[k])):
        k += 1

    if k >= n:
        return None

    exsuiteindent = indent(lines[k])

    if exsuiteindent == tryindent:
        return None

    if len(exsuiteindent) <= len(tryindent):
        return None

    # handler body runs until indent returns to tryindent or less
    ex_start = ex_head + 1
    ex_end = ex_head

    t = ex_head + 1
    while t < n:

        if isblank(lines[t]) or iscommentonly(lines[t]):
            ex_end = t
            t += 1
            continue

        curindent = indent(lines[t])

        if len(curindent) <= len(tryindent):
            break

        ex_end = t
        t += 1

    # must be exactly one nonblank/noncomment statement in except body
    c, laststmt = count_nonblank_noncomment(lines, ex_start, ex_end)
    if c != 1:
        return None

    if not isemptyhandlerstmt(lines[laststmt]):
        return None

    # must NOT have additional except/else/finally at tryindent immediately after handler
    u = ex_end + 1
    while u < n and (isblank(lines[u]) or iscommentonly(lines[u])):
        u += 1

    if u < n and indent(lines[u]) == tryindent:

        core = stripcomment(lines[u]).strip()

        if core.startswith("except") or core == "else:" or core == "finally:":
            return None

    # compute deindent prefix for try suite
    prefix = suiteindent

    return {
        "try_line": i,
        "suite_start": suite_start,
        "suite_end": suite_end,
        "suite_prefix": prefix,
        "try_indent": tryindent,
        "except_head": ex_head,
        "except_end": ex_end,
    }


def deindent_suite(lines, info):

    out = []
    prefix = info["suite_prefix"]
    base = info["try_indent"]

    i = info["suite_start"]
    while i <= info["suite_end"]:

        line = lines[i]

        if line.startswith(prefix):
            out.append(base + line[len(prefix):])
        else:
            out.append(line)

        i += 1

    return out


def transform_text(text):

    lines = text.splitlines(keepends=True)
    n = len(lines)

    out = []
    i = 0
    blocks = 0

    while i < n:

        info = try_unwrap(lines, i)

        if info is None:
            out.append(lines[i])
            i += 1
            continue

        # emit unwrapped try suite
        out.extend(deindent_suite(lines, info))

        # skip try header + suite + except block
        i = info["except_end"] + 1
        blocks += 1

    return "".join(out), blocks


def iter_py_files(root):

    for dirpath, dirnames, filenames in os.walk(root):

        dirnames[:] = [d for d in dirnames if d not in ("__pycache__", ".git", ".venv", "venv")]

        for name in filenames:

            if name.lower().endswith(".py"):
                yield os.path.join(dirpath, name)


def read_file(path):

    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    except UnicodeDecodeError:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()


def write_file(path, text):

    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def process_file(path, dry_run, backup):

    src = read_file(path)

    new, blocks = transform_text(src)

    if blocks == 0:
        return 0

    if new == src:
        return 0

    if dry_run:
        return blocks

    if backup:
        bak = path + ".bak"
        if not os.path.exists(bak):
            write_file(bak, src)

    write_file(path, new)
    return blocks


def main():

    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".", help="Root folder (default: current directory)")
    ap.add_argument("--dry-run", action="store_true", help="Do not write files; just report")
    ap.add_argument("--no-backup", action="store_true", help="Do not create .bak files")
    args = ap.parse_args()

    root = os.path.abspath(args.root)
    dry_run = args.dry_run
    backup = not args.no_backup

    total_blocks = 0
    changed_files = 0

    for path in iter_py_files(root):

        blocks = process_file(path, dry_run=dry_run, backup=backup)

        if blocks:
            changed_files += 1
            total_blocks += blocks

            rel = os.path.relpath(path, root)
            print(f"{rel}: {blocks} block(s)")

    mode = "DRY RUN" if dry_run else "APPLIED"
    print(f"\n{mode}: {changed_files} file(s), {total_blocks} block(s)")


if __name__ == "__main__":
    main()
