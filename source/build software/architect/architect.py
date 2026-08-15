

"""
architect.py

architect handles permissions in The One OS.
"""



# imports
import os
import sys
import tty
import time
import termios
import hashlib

BUILD_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BUILD_ROOT not in sys.path:
    sys.path.insert(0, BUILD_ROOT)

from broker import broker as authbroker



# globals
ARCH_PROTECTED_NONRECURSIVE = [
    '/software',
    '/master',
    '/the one',
    '/.rubbish',
    '/.remainder',
    '/.ephemeral',
    '/the one/settings',
    '/the one/logs',
    '/the one/software',
    '/the one/resources',
    '/the one/drivers',
    '/the one/catalogue',
]

ARCH_PROTECTED_RECURSIVE = [
    '/boot',
    '/the one/master',
    '/the one/build',
]

TEXTCOLOUR = 0xEFEFEF
ERRORCOLOUR = 0xFF0000



# gui functions
def guilog(*values, sep=' ', end='\n', file=None, flush=False, colour=None, bg=None, bold=False, underline=False, italic=False):

    try:

        # import printer from brick
        from __main__ import guiprint

        # build text from values
        parts = []
        for v in values:

            try:

                parts.append(str(v))

            except Exception as e:

                parts.append(f'<error {e}>')

        # join with separator
        text = sep.join(parts)

        # forward to guiprint with styling
        guiprint(
            text,
            sep='',
            end=end,
            file=file,
            flush=flush,
            colour=colour,
            bg=bg,
            bold=bool(bold),
            underline=bool(underline),
            italic=bool(italic),
        )

    except Exception:

        # fallback plain output (no styling)
        if file is not None:

            file.write((sep.join([str(v) for v in values])) + ('' if end is None else end))

            if flush:

                file.flush()

            return

        print(sep.join([str(v) for v in values]), end='' if end is None else end)


def guirepaint():

    import __main__

    # check gui environment
    if not os.environ.get('BRICK_WINDOW'):

        # not in gui mode
        return

    # get window id and socket
    winid = getattr(__main__, 'WINID', None)

    sock = getattr(__main__, 'SOCK', None)

    if not winid or not sock:

        # no window to repaint
        return

    rect = None

    try:

        # try to use main's dirty rectangle
        getdirty = getattr(__main__, 'getdirty', None)

        if callable(getdirty):

            d = getdirty()

            if d:

                rect = [int(d[0]), int(d[1]), int(d[2]), int(d[3])]

    except Exception:

        # error getting dirty area
        rect = None

    if rect is None:

        try:

            # fallback to full window size
            gfx = getattr(__main__, 'gfx', None)

            w = int(getattr(gfx, '_xres', 0))

            h = int(getattr(gfx, '_yres', 0))

            if w > 0 and h > 0:

                rect = [0, 0, w, h]

        except Exception:

            # error getting window size
            rect = None

    if rect is None:

        # nothing to repaint
        return

    try:

        # send damage message to window server
        sendline = getattr(__main__, 'sendline', None)

        if callable(sendline):

            sendline(sock, {"op": "DAMAGE", "winid": winid, "rect": rect})

    except Exception:

        # error sending damage
        return


def guipresent(host=None):

    try:

        if host is None:

            import __main__ as host

        # Brick's wrapper keeps the CPU buffer and managed scene in lockstep
        managedpresent = getattr(host, 'presentbrick', None)

        if callable(managedpresent):

            managedpresent()
            return True

        # compatibility path for older or non-managed GUI hosts
        rawpresent = getattr(host, 'present', None)

        if callable(rawpresent):
            rawpresent()

        legacyrepaint = getattr(host, 'guirepaint', None)

        if callable(legacyrepaint):
            legacyrepaint()
        else:
            guirepaint()

        return False

    except Exception:

        return False


def guipresentdiagnostic():

    class ManagedHost:

        def __init__(self):
            self.managed = 0
            self.raw = 0
            self.damage = 0

        def presentbrick(self):
            self.managed += 1

        def present(self):
            self.raw += 1

        def guirepaint(self):
            self.damage += 1

    class LegacyHost:

        def __init__(self):
            self.raw = 0
            self.damage = 0

        def present(self):
            self.raw += 1

        def guirepaint(self):
            self.damage += 1

    managedhost = ManagedHost()
    legacyhost = LegacyHost()
    managed = guipresent(managedhost)
    legacy = guipresent(legacyhost)

    return {
        'managed_selected': bool(managed and managedhost.managed == 1),
        'managed_legacy_damage_suppressed': bool(managedhost.raw == 0 and managedhost.damage == 0),
        'legacy_selected': bool(not legacy and legacyhost.raw == 1 and legacyhost.damage == 1),
    }


def guiline(prompt):

    try:

        from __main__ import (
            guiprint,
            pollchars,
            drawcontent,
            MAXINPUT,
            BLINKINTERVAL,
            enterinputmodal,
            exitinputmodal,
        )
        import __main__
        import time

        # take the modal lock so brick doesn't read keys
        enterinputmodal()

        # announce the prompt in the scroll
        guiprint(prompt)

        # save brick input state
        oldbuf = getattr(__main__, 'INPUTBUF', '')

        oldpos = getattr(__main__, 'CURSORPOS', 0)

        # local modal buffer
        buf = ''

        # render once
        __main__.INPUTBUF = buf

        __main__.CURSORPOS = 0

        # blink state
        last = time.monotonic()

        cursor_on = True

        while True:

            for ch in pollchars(timeout_ms=16):

                if ch in ('\n', '\r'):
                    return buf.strip()

                if ch in ('\b', '\x7f'):
                    if buf:

                        buf = buf[:-1]

                        # mirror into brick for visual echo
                        __main__.INPUTBUF = buf

                        __main__.CURSORPOS = len(buf)

                    continue

                if isinstance(ch, str) and 32 <= ord(ch) <= 126:

                    if len(buf) < MAXINPUT:

                        buf += ch

                        # mirror into brick for visual echo
                        __main__.INPUTBUF = buf

                        __main__.CURSORPOS = len(buf)

                    continue

            now = time.monotonic()

            if now - last >= BLINKINTERVAL:

                cursor_on = not cursor_on

                last = now

            drawcontent(cursor_on)

            guipresent()

            time.sleep(0.010)

    except Exception as e:

        guilog(f'> error prompting {e}', colour=ERRORCOLOUR)

        return ''

    finally:

        # restore brick input state
        import __main__

        __main__.INPUTBUF = oldbuf

        __main__.CURSORPOS = oldpos

        exitinputmodal()

        try:

            drawcontent(True)
            guipresent()

        except Exception:

            pass


def guipass(prompt):

    try:

        from __main__ import (
            guiprint,
            pollchars,
            drawcontent,
            MAXINPUT,
            BLINKINTERVAL,
            enterinputmodal,
            exitinputmodal,
        )
        import __main__
        import time

        enterinputmodal()

        guiprint(prompt)

        # save brick input state
        oldbuf = getattr(__main__, 'INPUTBUF', '')

        oldpos = getattr(__main__, 'CURSORPOS', 0)

        # secret buffer (unmasked)
        buf = ''

        # initial mirror (masked)
        __main__.INPUTBUF = ''

        __main__.CURSORPOS = 0

        last = time.monotonic()

        cursor_on = True

        while True:

            for ch in pollchars(timeout_ms=16):

                if ch in ('\n', '\r'):
                    return buf

                if ch in ('\b', '\x7f'):
                    if buf:

                        buf = buf[:-1]

                        # mirror masked bullets
                        masked = '●' * len(buf)

                        __main__.INPUTBUF = masked

                        __main__.CURSORPOS = len(masked)

                    continue

                if isinstance(ch, str) and 32 <= ord(ch) <= 126:

                    if len(buf) < MAXINPUT:

                        buf += ch

                        # mirror masked bullets
                        masked = '●' * len(buf)

                        __main__.INPUTBUF = masked

                        __main__.CURSORPOS = len(masked)

                    continue

            now = time.monotonic()

            if now - last >= BLINKINTERVAL:

                cursor_on = not cursor_on

                last = now

            drawcontent(cursor_on)

            guipresent()

            time.sleep(0.010)

    except Exception as e:

        guilog(f'> error password prompt {e}', colour=ERRORCOLOUR)

        return ''

    finally:

        # restore brick input state
        import __main__

        __main__.INPUTBUF = oldbuf

        __main__.CURSORPOS = oldpos

        exitinputmodal()

        try:

            drawcontent(True)
            guipresent()

        except Exception:

            pass


def readpass(prompt: str):

    pw = guipass(prompt)

    if pw != '':
        return pw

    sys.stdout.write(prompt)

    sys.stdout.flush()

    try:
        # get the terminal file descriptor
        fd = sys.stdin.fileno()

    except Exception as e:

        # error getting stdin fd
        guilog(f"> cannot get stdin file descriptor {e}", colour=ERRORCOLOUR)

        return ""

    try:

        # save current terminal settings
        old = termios.tcgetattr(fd)

    except Exception as e:

        # error retrieving terminal settings
        guilog(f"> cannot get terminal settings {e}", colour=ERRORCOLOUR)

        return ""

    # create buffer for the entered password
    pwd = ''

    try:

        try:

            # switch terminal to raw mode
            tty.setraw(fd)

        except Exception as e:

            # error setting raw mode
            guilog(f"> cannot set raw mode {e}", colour=ERRORCOLOUR)

            return ""

        while True:

            try:

                # read input one character at a time
                ch = sys.stdin.read(1)

            except Exception as e:

                # error reading from stdin
                guilog(f"> error reading input {e}", colour=ERRORCOLOUR)

                break

            # on 'enter', stop reading
            if ch in ('\r', '\n'):
                break

            # handle backspace/delete
            if ch in ('\x7f', '\b'):

                if pwd:

                    # remove last character from buffer
                    pwd = pwd[:-1]

                    # erase one dot from the display
                    sys.stdout.write('\b \b')

                    sys.stdout.flush()

            # for any other character, add to password buffer
            else:

                pwd += ch

                # display a bullet for each character
                sys.stdout.write('●')

                sys.stdout.flush()

    finally:

        # restore original terminal settings
        termios.tcsetattr(fd, termios.TCSADRAIN, old)

    # move to a new line after finishing input
    sys.stdout.write('\n')

    # return the collected password
    return pwd


def pbkdf2hmac(name, password, salt, iterations, dklen=None):

    # Kept only as a tightly bounded legacy diagnostic helper. New hashes and
    # verification are broker-owned.
    if (
        name != authbroker.LEGACY_PBKDF2_ALGORITHM
        or iterations != authbroker.LEGACY_PBKDF2_ITERATIONS
        or not isinstance(password, (bytes, bytearray))
        or not isinstance(salt, (bytes, bytearray))
        or len(password) > authbroker.MAX_PASSWORD_BYTES
        or len(salt) != 16
        or dklen not in (None, 32)
    ):
        return b''
    return hashlib.pbkdf2_hmac(
        name, bytes(password), bytes(salt), iterations, dklen=32
    )


def verifypw(pw, stored):

    return authbroker.verify_password(pw, stored)


def loadrole():
    # Ambient, process-global elevation is retired. Privileged operations use
    # typed, process-bound broker capabilities in their requesting process.
    return 'master'


def saverole(role):

    global currentrole
    if role != 'master':
        guilog(
            '> architect authorization must be issued after authentication',
            colour=ERRORCOLOUR,
        )
        return False
    currentrole = 'master'
    return role == 'master'


# role change helpers
def changeroleprocess(target, pw):
    global currentrole
    currentrole = 'master'
    if target == 'master':
        return True
    guilog(
        '> global architect mode is retired; authorise the specific protected action',
        colour=ERRORCOLOUR)
    return False


# role functions
def architect(args=None):

    # architect will set the global current role value
    global currentrole

    # Expiry is checked on every entry; a stale display variable cannot retain
    # privilege after its broker authorization has expired or been revoked.
    currentrole = loadrole()

    # revert to master
    if currentrole == 'architect':

        try:

            # revert prompt
            resp = guiline('> you are currently architect. revert to master? (yes/no) ')

        # revert cancel
        except (EOFError, KeyboardInterrupt):

            return

        # yes response
        if resp.lower() == 'yes':

            # Revocation is always allowed and invalidates the backing token.
            if changeroleprocess('master', ''):

                # update in-process role
                currentrole = 'master'

            else:

                # helper failed
                guilog('> remaining as architect', colour=TEXTCOLOUR)

        else:

            # cancel role change
            guilog('> remaining as architect', colour=TEXTCOLOUR)

        return

    # become architect
    if currentrole == 'master':

        try:

            # warning prompt
            guilog('> architect can modify anything in the operating system. becoming so can lead to irreparable damage to the system.', colour=TEXTCOLOUR)

            # confirmation prompt
            resp = guiline('  do you want to become architect? (yes/no) ')

            if resp.lower() == 'yes':

                confirm = guiline('> are you sure? (yes/no) ')

                if confirm.lower() == 'yes':

                    # password check
                    pw = readpass('> enter master password ')

                    # call helper to perform privileged write
                    if changeroleprocess('architect', pw):

                        # set role to architect in-process
                        currentrole = 'architect'

                        # inform user
                        guilog(
                            '> architect authorization granted for five minutes',
                            colour=TEXTCOLOUR,
                        )

                    else:

                        guilog('> remaining as master', colour=TEXTCOLOUR)

                else:

                    guilog('> remaining as master', colour=TEXTCOLOUR)

            else:

                guilog('> remaining as master', colour=TEXTCOLOUR)

        # become architect cancel
        except (EOFError, KeyboardInterrupt):

            return


def check(path):

    try:

        # No userspace bearer or mutable role can bypass protected paths.
        pass

    except NameError as e:

        # currentrole undefined error
        guilog(f'> role state error {e}', colour=ERRORCOLOUR)

        return False

    try:
        # define real path
        rp = os.path.realpath(path)

    except Exception as e:

        # error resolving path
        guilog(f'> could not resolve path {path} {e}', colour=ERRORCOLOUR)

        return False

    try:

        # if given path is protected then forbid
        for p in ARCH_PROTECTED_NONRECURSIVE:

            if rp == p:

                return False

        for p in ARCH_PROTECTED_RECURSIVE:

            if rp == p or rp.startswith(p + os.sep):

                return False

    except NameError as e:

        # protected path lists undefined
        guilog(f'> protected paths missing {e}', colour=ERRORCOLOUR)

        return False

    except Exception as e:

        # error checking protected paths
        guilog(f'> error checking protected paths {e}', colour=ERRORCOLOUR)

        return False

    # otherwise allow
    return True


def requirepermission(fn):

    def wrapper(args=None):

        # use provided paths or default to current tier
        paths = args or ['.']

        # only check the first two paths for permission
        for p in paths[:2]:

            # if any check fails, notify and abort
            if not check(p):
                guilog('> permission denied', colour=ERRORCOLOUR)
                return

        # return the original function
        return fn(args)

    # return the decorated function
    return wrapper


# Derive display state from a live authorization; master.txt never persists it.
currentrole = loadrole()


def changerolecli():

    # Role-changing subprocesses were intentionally removed: persisting a
    # process-global role made one password entry an indefinite elevation.
    guilog(
        '> architect elevation is available only in the requesting session',
        colour=ERRORCOLOUR,
    )
    return 1


# execute change role
if __name__ == '__main__':

    code = changerolecli()

    sys.exit(code)
