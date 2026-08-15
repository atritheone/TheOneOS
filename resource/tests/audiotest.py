#!/bin/python3.13



"""
audiotest.py

audiotest is a simple sound test client for The One OS audioserver.
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

# audioserver ipc
AUDIOSOCK = '/.ephemeral/audio/accept.sock'

# protocol
MAGIC = b'T1AU'
PROTO = 1
MAXMSG = 1024 * 1024

MSGHELLO = 1
MSGPING = 2
MSGCONFIG = 3
MSGDEVLIST = 10
MSGDEVSET = 11
MSGSTREAMOPEN = 20
MSGSTREAMCLOSE = 21
MSGSTREAMWRITE = 22
MSGERROR = 250

# defaults (must match audioserver)
DEFAULTSR = 48000
DEFAULTCH = 2
DEFAULTFMT = 's16le'

# audio generation
TWOPI = 6.283185307179586




## functions

# protocol functions
def u32be(n):

    return struct.pack('>I', int(n) & 0xFFFFFFFF)


def pack(msgtype, payload=None, raw=None):

    body = b""

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
        int(msgtype) & 0xFF,
        int(flags) & 0xFFFF,
        len(body)
    )

    return header + body


def recvn(sock, n):

    buf = b""

    while len(buf) < n:

        chunk = sock.recv(n - len(buf))

        if not chunk:

            return None

        buf += chunk

    return buf


def recvmsg(sock):

    head = recvn(sock, 12)

    if not head:

        return None, None, None

    try:

        magic, proto, mtype, flags, length = struct.unpack('>4sBBHI', head)

    except Exception:

        return None, None, None

    if magic != MAGIC or proto != PROTO:

        return None, None, None

    if length < 0 or length > MAXMSG:

        return None, None, None

    body = b""

    if length:

        body = recvn(sock, length)

        if body is None:

            return None, None, None

    # server responses are json-only in this implementation
    payload = None

    if body:

        try:

            payload = json.loads(body.decode('utf-8'))

        except Exception:

            payload = None

    return int(mtype), payload, body


def sendmsg(sock, msgtype, payload=None, raw=None):

    blob = pack(msgtype, payload, raw)

    sock.sendall(blob)


# audio functions
def makesine(freq, seconds, gain):

    sr = DEFAULTSR

    ch = DEFAULTCH

    frames = int(sr * float(seconds))

    amp = float(gain)

    if amp < 0.0:
        amp = 0.0

    if amp > 1.0:
        amp = 1.0

    peak = int(32767.0 * amp)

    out = bytearray(frames * ch * 2)

    phase = 0.0

    step = TWOPI * float(freq) / float(sr)

    i = 0

    while i < frames:

        s = int(math.sin(phase) * peak)

        if s > 32767:
            s = 32767

        if s < -32768:
            s = -32768

        off = i * ch * 2

        struct.pack_into('<h', out, off + 0, s)
        struct.pack_into('<h', out, off + 2, s)

        phase += step

        if phase >= TWOPI:
            phase -= TWOPI

        i += 1

    return bytes(out)


def chunkpcm(pcm, chunkbytes):

    i = 0

    n = len(pcm)

    while i < n:

        yield pcm[i:i + chunkbytes]

        i += chunkbytes


# utility functions
def usage():

    print('usage: audiotest.py [seconds] [freq] [gain] [deviceid]')
    print('  seconds: duration in seconds (default 2.0)')
    print('  freq:    tone frequency hz (default 440)')
    print('  gain:    0.0..1.0 (default 0.20)')
    print('  deviceid: optional; if set, audioserver will switch to it')
    print('')
    print('example:')
    print('  audiotest.py 3 440 0.25 virtio-snd')
    print('  audiotest.py 2 880 0.15')
    print('')


def pickarg(i, default):

    if len(sys.argv) > i:

        return sys.argv[i]

    return default


def main():

    if len(sys.argv) > 1 and sys.argv[1] in ('-h', '--help'):

        usage()

        return

    seconds = float(pickarg(1, '2.0'))

    freq = float(pickarg(2, '440'))

    gain = float(pickarg(3, '0.20'))

    deviceid = pickarg(4, '')

    if not os.path.exists(AUDIOSOCK):

        print(f'error: audioserver socket not found: {AUDIOSOCK}')

        return

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

    try:

        sock.connect(AUDIOSOCK)

    except Exception as e:

        print(f'error: cannot connect to audioserver: {e}')

        return

    # hello
    sendmsg(sock, MSGHELLO, {})

    mtype, payload, _ = recvmsg(sock)

    if mtype != MSGHELLO:

        print('error: no hello response')

        return

    # device list
    sendmsg(sock, MSGDEVLIST, {})

    mtype, payload, _ = recvmsg(sock)

    if mtype == MSGERROR:

        print(f'error: {payload}')

        return

    if mtype != MSGDEVLIST or not payload:

        print('error: invalid devlist response')

        return

    devices = payload.get('devices', [])
    active = payload.get('active', None)

    print('devices:')

    for d in devices:

        did = d.get('id')
        ready = d.get('ready')
        caps = d.get('caps', {})
        name = caps.get('name', d.get('name', did))

        mark = ' '

        if active and did == active:
            mark = '*'

        print(f'  {mark} {did}  ready={ready}  name={name}')

    # optional set device
    if deviceid:

        sendmsg(sock, MSGDEVSET, {'id': deviceid})

        mtype, payload, _ = recvmsg(sock)

        if mtype == MSGERROR:

            print(f'error: devset failed: {payload}')

            return

        if mtype != MSGDEVSET:

            print('error: invalid devset response')

            return

        print(f'active device: {payload.get("active")}')

    # open stream
    spec = {}
    spec['samplerate'] = DEFAULTSR
    spec['channels'] = DEFAULTCH
    spec['format'] = DEFAULTFMT

    sendmsg(sock, MSGSTREAMOPEN, spec)

    mtype, payload, _ = recvmsg(sock)

    if mtype == MSGERROR:

        print(f'error: streamopen failed: {payload}')

        return

    if mtype != MSGSTREAMOPEN or not payload or 'stream' not in payload:

        print('error: invalid streamopen response')

        return

    streamid = int(payload['stream'])

    print(f'stream: {streamid}')

    # generate tone
    pcm = makesine(freq=freq, seconds=seconds, gain=gain)

    # send in server-friendly blocks (multiple of a typical mix block)
    # MIXFRAMES(480) * CH(2) * 2bytes = 1920 bytes
    chunkbytes = 1920 * 8

    # streamwrite format: 4-byte jlen + json + raw
    meta = {'stream': streamid}
    j = json.dumps(meta).encode('utf-8')
    prefix = u32be(len(j))

    t0 = time.time()

    sent = 0

    bytespersec = int(DEFAULTSR * DEFAULTCH * 2)

    blocksec = float(chunkbytes) / float(bytespersec)

    for block in chunkpcm(pcm, chunkbytes):

        sendmsg(sock, MSGSTREAMWRITE, None, prefix + j + block)

        sent += len(block)

        time.sleep(blocksec)

    dt = time.time() - t0

    print(f'sent bytes: {sent} in {dt:.3f}s (rt target {seconds:.3f}s)')

    time.sleep(0.25)

    sendmsg(sock, MSGSTREAMCLOSE, {'stream': streamid})

    recvmsg(sock)

    try:

        sock.close()

    except Exception:

        pass

    print('done')



# execute main
if __name__ == '__main__':

    main()
