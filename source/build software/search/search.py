

"""
search.py

search finds files and tiers by name and searches text inside files or tiers.
"""



# imports
import os
import re
import sys



# globals
DELIMIN = 'in'
MAXTEXTSIZE = 16 * 1024 * 1024
MAXRESULTS = 2000
SHOWHIDDEN = str(os.environ.get('T1OS_SEARCH_HIDDEN', '')).strip().lower() in ('1', 'true', 'yes', 'on')
WALKERRORS = []



# path functions
def isfile(path):

    try:
        return os.path.isfile(path)
    except Exception:
        return False


def isdir(path):

    try:
        return os.path.isdir(path)
    except Exception:
        return False


def joinfrom(tokens):

    try:
        return ' '.join(tokens).strip()
    except Exception:
        return ''


def visible(name):

    try:
        return SHOWHIDDEN or not str(name).startswith('.')
    except Exception:
        return False


def walkerror(error):

    try:
        WALKERRORS.append(str(error))
    except Exception:
        pass


def walkpaths(root):

    if not isdir(root):
        return

    try:

        for dirpath, dirnames, filenames in os.walk(root, topdown=True, onerror=walkerror):

            dirnames[:] = sorted([name for name in dirnames if visible(name)], key=str.casefold)
            filenames = sorted([name for name in filenames if visible(name)], key=str.casefold)

            for name in dirnames:
                yield os.path.join(dirpath, name), True

            for name in filenames:
                yield os.path.join(dirpath, name), False

    except Exception as e:
        WALKERRORS.append(str(e))


def wildcardregex(pattern):

    try:

        escaped = re.escape(pattern)
        escaped = escaped.replace(r'\*', '.*')
        escaped = escaped.replace(r'\?', '.')
        return f'^{escaped}$'

    except Exception:
        return None



# match functions
def termmatch(value, term, exact=False, wildcard=False):

    try:

        lowvalue = str(value).lower()
        lowterm = str(term).lower()

        if exact:
            return lowvalue == lowterm

        if wildcard and ('*' in lowterm or '?' in lowterm):

            regex = wildcardregex(lowterm)
            return bool(regex and re.match(regex, lowvalue))

        return lowterm in lowvalue

    except Exception:
        return False


def matchname(name, terms, mode='any'):

    if not terms:
        return False

    if mode == 'exact':
        return termmatch(name, joinfrom(terms), exact=True)

    checks = [termmatch(name, term, wildcard=True) for term in terms]

    if mode == 'all':
        return all(checks)

    return any(checks)


def matchline(line, terms, mode='any'):

    if not terms:
        return False

    if mode == 'exact':

        try:
            return joinfrom(terms).lower() in str(line).lower()
        except Exception:
            return False

    checks = [termmatch(line, term) for term in terms]

    if mode == 'all':
        return all(checks)

    return any(checks)



# parse functions
def splitin(args):

    positions = [index for index, token in enumerate(args) if str(token).lower() == DELIMIN]

    for index in reversed(positions):

        if index <= 0 or index >= len(args) - 1:
            continue

        target = joinfrom(args[index + 1:])

        if isfile(target) or isdir(target):
            return list(args[:index]), target

    if positions:

        index = positions[-1]
        return list(args[:index]), joinfrom(args[index + 1:])

    return None, None


def parsenamescope(args):

    remaining = list(args)
    found = []

    while remaining:

        matched = False

        for count in range(1, len(remaining) + 1):

            candidate = joinfrom(remaining[-count:])

            if isdir(candidate):

                found.append(candidate)
                remaining = remaining[:-count]
                matched = True
                break

        if not matched:
            break

    found.reverse()
    return remaining, found


def parse(args):

    tokens = [str(arg) for arg in (args or [])]

    if not tokens:
        return None

    purpose = None
    kind = 'both'
    mode = 'any'

    first = tokens[0].lower()

    if first in ('names', 'files', 'tiers'):

        purpose = 'names'
        kind = {'names': 'both', 'files': 'file', 'tiers': 'tier'}[first]
        tokens = tokens[1:]

    elif first in ('exact', 'all'):

        mode = first
        tokens = tokens[1:]

    terms, target = splitin(tokens)

    if purpose == 'names':

        if terms is None:
            return None

        return purpose, terms, [target], kind, mode

    if terms is not None:
        return 'content', terms, [target], kind, mode

    terms, scopes = parsenamescope(tokens)
    return 'names', terms, scopes or ['.'], kind, mode



# content functions
def binary(path):

    try:

        with open(path, 'rb') as stream:
            sample = stream.read(4096)

        return b'\x00' in sample

    except Exception:
        return False


def searchfile(terms, filepath, mode, counts):

    try:

        size = os.path.getsize(filepath)

        if size > MAXTEXTSIZE:
            counts['large'] += 1
            return

        if binary(filepath):
            counts['binary'] += 1
            return

        counts['files'] += 1

        with open(filepath, 'r', encoding='utf-8', errors='replace') as stream:

            for lineno, line in enumerate(stream, 1):

                if counts['matches'] >= MAXRESULTS:
                    counts['limited'] = True
                    return

                if matchline(line, terms, mode):

                    print(f'{filepath}:{lineno} {line.rstrip()}', flush=True)
                    counts['matches'] += 1

    except PermissionError:

        print(f'permission denied {filepath}', file=sys.stderr)
        counts['errors'] += 1

    except OSError as e:

        print(f'error opening file {filepath} {e}', file=sys.stderr)
        counts['errors'] += 1

    except Exception as e:

        print(f'error searching file {filepath} {e}', file=sys.stderr)
        counts['errors'] += 1


def searchcontent(terms, target, mode='any'):

    counts = {'files': 0, 'matches': 0, 'binary': 0, 'large': 0, 'errors': 0, 'limited': False}

    if not terms:

        print('no search terms given', file=sys.stderr)
        return 1

    if isfile(target):
        searchfile(terms, target, mode, counts)

    elif isdir(target):

        for path, istier in walkpaths(target):

            if not istier:
                searchfile(terms, path, mode, counts)

            if counts['limited']:
                break

    else:

        print(f'target not found {target}', file=sys.stderr)
        return 1

    if counts['matches'] == 0:
        print('> no matches found')

    print(f"> {counts['matches']} matches in {counts['files']} files")

    if counts['limited']:
        print(f'> stopped after {MAXRESULTS} matches')

    if counts['binary'] or counts['large'] or counts['errors']:
        print(f"> skipped {counts['binary']} binary, {counts['large']} large, {counts['errors']} unreadable")

    return 0



# name functions
def kindmatch(istier, kind):

    if kind == 'file':
        return not istier

    if kind == 'tier':
        return istier

    return True


def iterfindnames(
    terms,
    scopes,
    kind='both',
    mode='any',
    cancelled=None,
):

    """Yield matching file/tier records without writing to stdout.

    Keeping this as an iterator lets a graphical client pause a live filesystem
    walk and hand that exact walk to a richer search surface without rescanning
    entries it has already visited.  ``cancelled`` may be a callable so a client
    can abandon an obsolete walk when the query changes.
    """

    terms = [str(term) for term in (terms or []) if str(term)]
    scopes = [str(scope) for scope in (scopes or [])]
    printed = set()
    WALKERRORS.clear()

    if not terms:
        return

    for scope in scopes:

        if cancelled is not None and cancelled():
            break

        if not isdir(scope):
            continue

        name = os.path.basename(scope.rstrip('/'))

        if name and kind in ('both', 'tier') and matchname(name, terms, mode):
            absolute = os.path.abspath(scope)
            printed.add(absolute)
            yield {'path': scope, 'is_tier': True}

        for entry, istier in walkpaths(scope):

            if cancelled is not None and cancelled():
                return

            if not kindmatch(istier, kind):
                continue

            if not matchname(os.path.basename(entry), terms, mode):
                continue

            absolute = os.path.abspath(entry)

            if absolute in printed:
                continue

            printed.add(absolute)
            yield {'path': entry, 'is_tier': bool(istier)}


def findnames(
    terms,
    scopes,
    kind='both',
    mode='any',
    limit=MAXRESULTS,
    cancelled=None,
    on_result=None,
):

    """Return matching file/tier records without writing to stdout.

    This is the programmatic API used by graphical search clients.  ``cancelled``
    may be a callable so a client can abandon an obsolete filesystem walk when
    the query changes.
    """

    maximum = MAXRESULTS if limit is None else max(0, int(limit))
    results = []

    if maximum == 0:
        return results

    for record in iterfindnames(
        terms,
        scopes,
        kind=kind,
        mode=mode,
        cancelled=cancelled,
    ):
        results.append(record)

        if on_result is not None:
            on_result(dict(record))

        if len(results) >= maximum:
            break

    return results


def searchname(terms, scopes, kind='both', mode='any'):

    if not terms:

        print('no search terms given', file=sys.stderr)
        return 1

    for scope in scopes:

        if not isdir(scope):

            print(f'target not found {scope}', file=sys.stderr)
            return 1

    results = findnames(
        terms,
        scopes,
        kind=kind,
        mode=mode,
        limit=MAXRESULTS,
        on_result=lambda result: print(result['path'], flush=True),
    )
    found = len(results)
    limited = found >= MAXRESULTS

    if found == 0:
        print('> no matches found')

    print(f'> {found} names found')

    if limited:
        print(f'> stopped after {MAXRESULTS} names')

    if WALKERRORS:
        print(f'> skipped {len(WALKERRORS)} unreadable tiers')

    return 0



# search functions
def search(args=None):

    parsed = parse(args)

    if not parsed:

        print('usage search <name> [scope tiers]')
        print('usage search <term> in <file or tier>')
        print('usage search <names|files|tiers> <name> in <tier>')
        return 1

    purpose, terms, targets, kind, mode = parsed

    if not terms:

        print('no search terms given', file=sys.stderr)
        return 1

    if purpose == 'content':
        return searchcontent(terms, targets[0], mode)

    return searchname(terms, targets, kind, mode)



# execute search
if __name__ == '__main__':
    sys.exit(search(sys.argv[1:]))
