#!/bin/python3.13


"""
audioservertest.py

audioservertest is a client test tool for the T1OS audioserver IPC protocol.
"""



## imports
import os
import sys
import time
import json
import math
import struct
import socket



## globals

# protocol (must match audioserver.py)
MAGIC = b'T1AU'
PROTO = 1

MSGHELLO = 1
MSGPING = 2
MSGCONFIG = 3
MSGDEVLIST = 10
MSGDEVSET = 11
MSGSTREAMOPEN = 20
MSGSTREAMCLOSE = 21
MSGSTREAMWRITE = 22
MSGSTREAMSTATUS = 24
MSGSTREAMCONTROL = 25
MSGSUBSCRIBE = 40
MSGNOTIFY = 41
MSGERROR = 250

# path (must match audioserver.py)
AUDIOSOCK = '/.ephemeral/audio/accept.sock'

# defaults
DEFAULTSR = 48000
DEFAULTCH = 2
DEFAULTFRAMES = 480



## functions

# protocol functions
def pack(msgtype, payload, raw):

    body = b""

    if int(msgtype) == MSGSTREAMWRITE:

        if payload is None:

            payload = {}

        try:

            jblob = json.dumps(payload).encode('utf-8')

        except Exception:

            jblob = b"{}"

        if raw is None:

            raw = b""

        body = struct.pack('>I', len(jblob)) + jblob + raw

    else:

        if payload is not None:

            try:

                body = json.dumps(payload).encode('utf-8')

            except Exception:

                body = b""

        if raw:

            body += raw

    flags = 0

    header = struct.pack(
        '>4sBBHI',
        MAGIC,
        PROTO,
        int(msgtype),
        flags,
        len(body)
    )

    return header + body


def unpack(buf):

    if len(buf) < 12:

        return None, None, None, buf

    try:

        magic, proto, mtype, flags, length = struct.unpack('>4sBBHI', buf[:12])

    except Exception:

        return None, None, None, buf

    if magic != MAGIC or proto != PROTO:

        return None, None, None, buf

    if len(buf) < 12 + length:

        return None, None, None, buf

    payload = buf[12:12 + length]

    rest = buf[12 + length:]

    try:

        data = json.loads(payload.decode('utf-8'))

        raw = None

    except Exception:

        data = None

        raw = payload

    return mtype, data, raw, rest


def sendmsg(sock, msgtype, payload=None, raw=None):

    blob = pack(msgtype, payload, raw)

    sock.sendall(blob)


def recvmsgs(sock, timeout, wanttypes=None):

    end = time.time() + float(timeout)

    buf = b""
    out = []

    while time.time() < end:

        remain = end - time.time()

        if remain <= 0:

            break

        sock.settimeout(remain)

        try:

            chunk = sock.recv(65536)

        except Exception:

            chunk = b""

        if not chunk:

            break

        buf += chunk

        while True:

            mtype, payload, raw, buf = unpack(buf)

            if mtype is None:

                break

            out.append((mtype, payload, raw))

            if wanttypes and mtype in wanttypes:

                return out

    return out


def req(sock, msgtype, payload=None, raw=None, timeout=1.0):

    sendmsg(sock, msgtype, payload, raw)

    msgs = recvmsgs(sock, timeout, wanttypes={msgtype, MSGERROR})

    last = None

    for m in msgs:

        last = m

        if m[0] == MSGERROR:

            return m

        if m[0] == msgtype:

            return m

    return last


# audio generation functions
def makepcm(sr, ch, frames, freq, amp, phase):

    out = bytearray(frames * ch * 2)

    twopi = 2.0 * math.pi

    step = twopi * float(freq) / float(sr)

    idx = 0

    for i in range(frames):

        s = math.sin(phase)

        phase += step

        v = int(s * amp)

        if v > 32767:
            v = 32767

        if v < -32768:
            v = -32768

        for _ in range(ch):

            struct.pack_into('<h', out, idx, v)

            idx += 2

    return bytes(out), phase


def pickdevice(devresp, preferid):

    if not devresp:
        return None

    payload = devresp[1]

    if not payload:
        return None

    devices = payload.get('devices', [])

    if not devices:
        return None

    if preferid:

        for d in devices:

            if d.get('id') == preferid:
                return preferid

    active = payload.get('active')

    if active:
        return active

    return devices[0].get('id')


# printing functions
def show(title, obj):

    print()
    print(title)

    if obj is None:

        print("  (none)")

        return

    if isinstance(obj, (bytes, bytearray)):

        print(f"  bytes: {len(obj)}")

        return

    try:

        text = json.dumps(obj, indent=2)

        for line in text.splitlines():

            print("  " + line)

    except Exception:

        print("  " + str(obj))


def main():

    # args
    duration = 1.0
    freq = 440.0
    amp = 0.20
    deviceid = None
    subscribenotify = True

    for a in sys.argv[1:]:

        if a.startswith('duration='):
            duration = float(a.split('=', 1)[1])

        if a.startswith('freq='):
            freq = float(a.split('=', 1)[1])

        if a.startswith('amp='):
            amp = float(a.split('=', 1)[1])

        if a.startswith('device='):
            deviceid = a.split('=', 1)[1].strip() or None

        if a == 'nonotify':
            subscribenotify = False

    print("audioservertest")
    print(f"sock: {AUDIOSOCK}")
    print(f"duration: {duration}s  freq: {freq}hz  amp: {amp}")
    if deviceid:
        print(f"device: {deviceid}")
    else:
        print("device: (auto)")

    # connect
    if not os.path.exists(AUDIOSOCK):

        print()
        print("result: FAIL")
        print("reason: audioserver socket not found (is audioserver running?)")
        return 2

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(2.0)

    try:

        sock.connect(AUDIOSOCK)

    except Exception as e:

        print()
        print("result: FAIL")
        print(f"reason: connect failed: {e}")
        return 2

    print()
    print("connected: OK")

    # hello
    t0 = time.time()
    hello = req(sock, MSGHELLO, {}, None, timeout=1.0)
    t1 = time.time()

    if not hello or hello[0] == MSGERROR:

        show("hello: ERROR", hello[1] if hello else None)

        return 2

    show("hello: OK", hello[1])
    print(f"hello rtt: {(t1 - t0) * 1000.0:.2f} ms")

    # ping
    t0 = time.time()
    ping = req(sock, MSGPING, {}, None, timeout=1.0)
    t1 = time.time()

    if not ping or ping[0] == MSGERROR:

        show("ping: ERROR", ping[1] if ping else None)

        return 2

    show("ping: OK", ping[1])
    print(f"ping rtt: {(t1 - t0) * 1000.0:.2f} ms")

    # config get
    cfg = req(sock, MSGCONFIG, None, None, timeout=1.0)

    if not cfg or cfg[0] == MSGERROR:

        show("config: ERROR", cfg[1] if cfg else None)

        return 2

    show("config: OK", cfg[1])

    sr = int(cfg[1].get('samplerate', DEFAULTSR)) if cfg[1] else DEFAULTSR
    ch = int(cfg[1].get('channels', DEFAULTCH)) if cfg[1] else DEFAULTCH
    frames = int(cfg[1].get('frames', DEFAULTFRAMES)) if cfg[1] else DEFAULTFRAMES

    # dev list
    devs = req(sock, MSGDEVLIST, {}, None, timeout=1.0)

    if not devs or devs[0] == MSGERROR:

        show("devlist: ERROR", devs[1] if devs else None)

    else:

        show("devlist: OK", devs[1])

        chosen = pickdevice(devs, deviceid)

        if chosen:

            if devs[1] and devs[1].get('active') != chosen:

                setresp = req(sock, MSGDEVSET, {'id': chosen}, None, timeout=1.0)

                if not setresp or setresp[0] == MSGERROR:

                    show("devset: ERROR", setresp[1] if setresp else None)

                else:

                    show("devset: OK", setresp[1])

            else:

                print()
                print("devset: (already active)")

        else:

            print()
            print("devset: SKIP (no devices found)")

    # subscribe notify
    if subscribenotify:

        sub = req(sock, MSGSUBSCRIBE, {'topic': 'device'}, None, timeout=1.0)

        if sub and sub[0] != MSGERROR:
            show("subscribe: OK", sub[1])
        else:
            show("subscribe: ERROR", sub[1] if sub else None)

    # open stream
    spec = {
        'samplerate': sr,
        'channels': ch,
        'format': 's16le',
        'write_ack': True,
    }

    sopen = req(sock, MSGSTREAMOPEN, spec, None, timeout=1.0)

    if not sopen or sopen[0] == MSGERROR:

        show("streamopen: ERROR", sopen[1] if sopen else None)

        return 2

    streamid = None

    if sopen[1]:
        streamid = sopen[1].get('stream')

    if not streamid:

        print()
        print("streamopen: FAIL (no stream id)")

        return 2

    show("streamopen: OK", sopen[1])

    # write tone in realtime blocks
    blocksec = float(frames) / float(sr)
    blocks = int(max(1, round(float(duration) / blocksec)))

    amp16 = int(32767 * float(amp))

    print()
    print("streamwrite: START")
    print(f"sr: {sr}  ch: {ch}  frames: {frames}  block: {blocksec:.6f}s  blocks: {blocks}")

    phase = 0.0
    wrote = 0
    failed = 0
    notifies = 0

    tstart = time.time()

    for _ in range(blocks):

        pcm, phase = makepcm(sr, ch, frames, freq, amp16, phase)

        accepted = False

        for _attempt in range(100):

            response = req(sock, MSGSTREAMWRITE, {'stream': streamid}, pcm, timeout=1.0)

            if not response or response[0] == MSGERROR:

                failed += 1

                show("streamwrite: ERROR", response[1] if response else None)

                break

            payload = response[1] or {}

            if payload.get('ok'):

                if int(payload.get('accepted', 0)) != len(pcm):

                    failed += 1

                    show("streamwrite: ERROR", payload)

                else:

                    wrote += len(pcm)

                    accepted = True

                break

            if int(payload.get('accepted', 0)) != 0:

                failed += 1

                show("streamwrite: ERROR", payload)

                break

            time.sleep(0.01)

        if not accepted and failed == 0:

            failed += 1

            print("streamwrite: ERROR (stream remained full)")

        time.sleep(blocksec)

    tend = time.time()

    print("streamwrite: END")
    print(f"bytes sent: {wrote}")
    print(f"errors: {failed}")
    print(f"notifies seen: {notifies}")
    print(f"elapsed: {(tend - tstart):.3f}s")

    pause = req(sock, MSGSTREAMCONTROL, {'stream': streamid, 'paused': True}, None, timeout=1.0)

    if not pause or pause[0] == MSGERROR or not (pause[1] or {}).get('paused'):

        failed += 1
        show("streampause: ERROR", pause[1] if pause else None)

    else:

        show("streampause: OK", pause[1])
        pausedbytes = int((pause[1] or {}).get('output_bytes', 0))
        time.sleep(max(0.05, blocksec * 3.0))
        pausedstatus = req(sock, MSGSTREAMSTATUS, {'stream': streamid}, None, timeout=1.0)

        if not pausedstatus or pausedstatus[0] == MSGERROR:

            failed += 1
            show("pausehold: ERROR", pausedstatus[1] if pausedstatus else None)

        elif int((pausedstatus[1] or {}).get('output_bytes', -1)) != pausedbytes:

            failed += 1
            show("pausehold: ERROR (output advanced)", pausedstatus[1])

        else:

            show("pausehold: OK", pausedstatus[1])

    resume = req(sock, MSGSTREAMCONTROL, {'stream': streamid, 'paused': False}, None, timeout=1.0)

    if not resume or resume[0] == MSGERROR or (resume[1] or {}).get('paused'):

        failed += 1
        show("streamresume: ERROR", resume[1] if resume else None)

    else:

        show("streamresume: OK", resume[1])

    status = req(sock, MSGSTREAMSTATUS, {'stream': streamid}, None, timeout=1.0)

    if not status or status[0] == MSGERROR:

        failed += 1

        show("streamstatus: ERROR", status[1] if status else None)

    else:

        show("streamstatus: OK", status[1])

    # close stream and wait for the server to drain queued PCM
    sclose = req(sock, MSGSTREAMCLOSE, {'stream': streamid, 'drain': True}, None, timeout=1.0)

    if not sclose or sclose[0] == MSGERROR:

        show("streamclose: ERROR", sclose[1] if sclose else None)

    else:

        show("streamclose: OK", sclose[1])

        drainend = time.time() + 5.0

        while time.time() < drainend:

            status = req(sock, MSGSTREAMSTATUS, {'stream': streamid}, None, timeout=1.0)

            if not status or status[0] == MSGERROR:

                failed += 1

                show("streamdrain: ERROR", status[1] if status else None)

                break

            if status[1] and status[1].get('state') == 'closed':

                show("streamdrain: OK", status[1])

                break

            time.sleep(0.01)

        else:

            failed += 1

            print("streamdrain: ERROR (timed out)")

    # drain any late notify
    tail = recvmsgs(sock, 0.2, wanttypes=None)

    for mtype, payload, raw in tail:

        if mtype == MSGNOTIFY:

            notifies += 1

    print()
    print("result: PASS" if failed == 0 else "result: WARN")
    print("note: audioserver mixes into the active backend; if no audio device node is present, playback may be silent even if IPC passes.")

    try:

        sock.close()

    except Exception:

        pass

    return 0 if failed == 0 else 1



## execute main
if __name__ == '__main__':

    raise SystemExit(main())
