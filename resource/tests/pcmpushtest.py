#!/bin/python3.13


"""
pcmpushtest.py

Test whether snd/pcmC0D0p accepts raw writes.
"""



## imports
import os
import time
import errno
import select



## globals

PCM = "/the one/drivers/nodes/snd/pcmC0D0p"

CHUNK = 4096

TOTAL = 1024 * 1024

WAITMS = 200



## functions

def nowms():

    return int(time.time() * 1000)



def explain(e):

    if isinstance(e, BlockingIOError):
        return f"BlockingIOError errno={e.errno} ({os.strerror(e.errno)})"

    if isinstance(e, OSError):
        return f"OSError errno={e.errno} ({os.strerror(e.errno)})"

    return repr(e)



def openpcm():

    if not os.path.exists(PCM):
        print(f"missing {PCM}")

        return None

    flags = os.O_WRONLY | os.O_NONBLOCK

    try:

        fd = os.open(PCM, flags)

    except Exception as e:

        print(f"open failed: {explain(e)}")

        return None

    return fd



def waitwritable(fd):

    r = []

    w = [fd]

    x = []

    timeout = WAITMS / 1000.0

    rr, ww, xx = select.select(r, w, x, timeout)

    return bool(ww)



def writetest(fd):

    data = b"\x00" * CHUNK

    sent = 0

    start = nowms()

    loops = 0

    print(f"opened {PCM} (nonblocking)")

    while sent < TOTAL:

        loops += 1

        try:

            n = os.write(fd, data)

        except BlockingIOError as e:

            if e.errno in (errno.EAGAIN, errno.EWOULDBLOCK):

                if not waitwritable(fd):
                    print(f"blocked: EAGAIN after {sent} bytes, waited {WAITMS}ms, still not writable")

                    return False

                continue

            print(f"write failed: {explain(e)}")

            return False

        except Exception as e:

            print(f"write failed: {explain(e)}")

            return False

        if n == 0:
            print(f"write returned 0 after {sent} bytes")

            return False

        sent += n

        if loops % 64 == 0:

            elapsed = nowms() - start

            rate = 0.0

            if elapsed > 0:
                rate = (sent / 1024.0) / (elapsed / 1000.0)

            print(f"progress: {sent}/{TOTAL} bytes, {rate:.1f} KiB/s")

    elapsed = nowms() - start

    rate = 0.0

    if elapsed > 0:
        rate = (sent / 1024.0) / (elapsed / 1000.0)

    print(f"done: wrote {sent} bytes in {elapsed}ms ({rate:.1f} KiB/s)")

    return True



def run():

    fd = openpcm()

    if fd is None:
        return

    try:

        ok = writetest(fd)

    finally:

        os.close(fd)

    if ok:
        print("result: raw writes appear to work (device accepted data)")

    else:
        print("result: raw writes did not work (see error above)")



## main

if __name__ == "__main__":

    run()
