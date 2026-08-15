

"""
read.py

A bounded text displayer for brick.
"""



# imports
import os
import sys
import shutil
from collections import deque



# parse functions
def parseargs(args):

    tokens = [str(arg) for arg in (args or [])]
    numbers = False
    start = None
    end = None
    last = None

    if len(tokens) >= 2 and tokens[-2].lower() == 'with' and tokens[-1].lower() == 'numbers':

        numbers = True
        tokens = tokens[:-2]

    if len(tokens) >= 4 and tokens[0].lower() == 'last' and tokens[2].lower() == 'from':

        try:
            last = max(0, int(tokens[1]))
        except Exception:
            return None

        path = ' '.join(tokens[3:]).strip()

        if not path:
            return None

        return path, start, end, last, numbers

    if len(tokens) >= 5 and tokens[-4].lower() == 'from' and tokens[-2].lower() == 'to':

        try:
            start = max(1, int(tokens[-3]))
            end = max(start, int(tokens[-1]))
        except Exception:
            return None

        path = ' '.join(tokens[:-4]).strip()

        if not path:
            return None

        return path, start, end, last, numbers

    path = ' '.join(tokens).strip()

    if not path:
        path = '-'

    return path, start, end, last, numbers



# read functions
def binary(path):

    try:

        with open(path, 'rb') as stream:
            sample = stream.read(4096)

        return b'\x00' in sample

    except Exception:
        return False


def emit(line, number, numbers):

    text = line.rstrip('\n')

    if numbers:
        sys.stdout.write(f'{number}: {text}\n')
    else:
        sys.stdout.write(text + '\n')


def readtext(path, start=None, end=None, last=None, numbers=False):

    try:

        if path == '-':

            shutil.copyfileobj(sys.stdin.buffer, sys.stdout.buffer)
            return 0

        if not os.path.isfile(path):

            if os.path.isdir(path):
                print(f'{path} is a tier', file=sys.stderr)
            else:
                print(f'file {path} not found', file=sys.stderr)

            return 1

        if binary(path):

            print(f'{path} is a binary file', file=sys.stderr)
            return 1

        with open(path, 'r', encoding='utf-8', errors='replace') as stream:

            if last is not None:

                rows = deque(maxlen=last)

                for number, line in enumerate(stream, 1):
                    rows.append((number, line))

                for number, line in rows:
                    emit(line, number, numbers)

                return 0

            for number, line in enumerate(stream, 1):

                if start is not None and number < start:
                    continue

                if end is not None and number > end:
                    break

                emit(line, number, numbers)

        return 0

    except FileNotFoundError:

        print(f'file {path} not found', file=sys.stderr)
        return 1

    except PermissionError:

        print('permission denied', file=sys.stderr)
        return 1

    except BrokenPipeError:
        return 1

    except OSError as e:

        print(f'error reading {path} {e.strerror}', file=sys.stderr)
        return 1

    except Exception as e:

        print(f'error reading {path} {e}', file=sys.stderr)
        return 1


def main():

    parsed = parseargs(sys.argv[1:])

    if not parsed:

        print('usage read <file> [from <first> to <last>] [with numbers]', file=sys.stderr)
        print('usage read last <count> from <file> [with numbers]', file=sys.stderr)
        return 1

    return readtext(*parsed)



# execute read
if __name__ == '__main__':
    sys.exit(main())
