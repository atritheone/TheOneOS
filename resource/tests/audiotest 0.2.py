#!/bin/python3.13


"""
audiotest_song.py

audiotest_song plays a short procedural song to fully exercise
The One OS audioserver: timing, mixing, buffering, and backend stability.
"""



## imports
import os
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
MSGDEVLIST = 10
MSGSTREAMOPEN = 20
MSGSTREAMCLOSE = 21
MSGSTREAMWRITE = 22
MSGERROR = 250

# audio format (must match audioserver)
SAMPLERATE = 48000
CHANNELS = 2
FORMAT = 's16le'

# math
TWOPI = 6.283185307179586



## functions

# protocol helpers
def u32be(n):

    return struct.pack('>I', int(n) & 0xFFFFFFFF)


def pack(msgtype, payload=None, raw=None):

    body = b''

    if payload is not None:
        body = json.dumps(payload).encode('utf-8')

    if raw:
        body += raw

    header = struct.pack(
        '>4sBBHI',
        MAGIC,
        PROTO,
        int(msgtype),
        0,
        len(body)
    )

    return header + body


def recvn(sock, n):

    buf = b''

    while len(buf) < n:

        chunk = sock.recv(n - len(buf))

        if not chunk:
            return None

        buf += chunk

    return buf


def recvmsg(sock):

    head = recvn(sock, 12)

    if not head:
        return None, None

    magic, proto, mtype, flags, length = struct.unpack('>4sBBHI', head)

    if magic != MAGIC or proto != PROTO:
        return None, None

    body = b''

    if length:
        body = recvn(sock, length)

    payload = None

    if body:
        try:
            payload = json.loads(body.decode('utf-8'))
        except Exception:
            payload = None

    return mtype, payload


def sendmsg(sock, msgtype, payload=None, raw=None):

    sock.sendall(pack(msgtype, payload, raw))


# audio synthesis
def clamp(v, lo, hi):

    if v < lo:
        return lo

    if v > hi:
        return hi

    return v


def env(t, attack, release, length):

    if t < attack:
        return t / attack

    if t > length - release:
        return clamp((length - t) / release, 0.0, 1.0)

    return 1.0


def sample(freq, t):

    return math.sin(TWOPI * freq * t)


def makesong():

    # song layout (seconds)
    bpm = 120.0
    beat = 60.0 / bpm
    bars = 8
    length = bars * 4 * beat

    frames = int(SAMPLERATE * length)

    out = bytearray(frames * CHANNELS * 2)

    # melody notes (Hz)
    melody = [
        440.0, 493.9, 523.3, 587.3,
        659.3, 587.3, 523.3, 493.9,
    ]

    bass = [
        110.0, 110.0, 98.0, 98.0,
        82.4, 82.4, 98.0, 110.0,
    ]

    i = 0

    while i < frames:

        t = i / SAMPLERATE

        step = int((t / beat)) % len(melody)

        mfreq = melody[step]
        bfreq = bass[step]

        e = env(t % beat, 0.01, 0.05, beat)

        # voices
        s_bass = sample(bfreq, t) * 0.4
        s_mid  = sample(mfreq * 0.5, t) * 0.2
        s_mel  = sample(mfreq, t) * 0.5

        s = (s_bass + s_mid + s_mel) * e

        # stereo pan (slow L/R motion)
        pan = math.sin(t * 0.5)
        l = s * (0.6 + pan * 0.4)
        r = s * (0.6 - pan * 0.4)

        l = clamp(int(l * 32767), -32768, 32767)
        r = clamp(int(r * 32767), -32768, 32767)

        off = i * CHANNELS * 2

        struct.pack_into('<h', out, off + 0, l)
        struct.pack_into('<h', out, off + 2, r)

        i += 1

    return bytes(out)


def chunkpcm(pcm, chunkbytes):

    i = 0

    while i < len(pcm):

        yield pcm[i:i + chunkbytes]

        i += chunkbytes



## main

def main():

    if not os.path.exists(AUDIOSOCK):

        print('audioserver socket not found')

        return

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(AUDIOSOCK)

    # hello
    sendmsg(sock, MSGHELLO, {})
    recvmsg(sock)

    # open stream
    spec = {
        'samplerate': SAMPLERATE,
        'channels': CHANNELS,
        'format': FORMAT,
    }

    sendmsg(sock, MSGSTREAMOPEN, spec)

    mtype, payload = recvmsg(sock)

    if mtype != MSGSTREAMOPEN:

        print('stream open failed')

        return

    streamid = int(payload.get('stream'))

    print(f'playing song on stream {streamid}')

    pcm = makesong()

    meta = {'stream': streamid}
    j = json.dumps(meta).encode('utf-8')
    prefix = u32be(len(j))

    # chunk size aligned to mixer expectations
    chunkbytes = 1920 * 8
    bytespersec = SAMPLERATE * CHANNELS * 2
    blocksec = chunkbytes / bytespersec

    for block in chunkpcm(pcm, chunkbytes):

        sendmsg(sock, MSGSTREAMWRITE, None, prefix + j + block)
        time.sleep(blocksec)

    # let tail play out
    time.sleep(0.5)

    sendmsg(sock, MSGSTREAMCLOSE, {'stream': streamid})
    recvmsg(sock)

    sock.close()

    print('song complete')



# execute
if __name__ == '__main__':

    main()
