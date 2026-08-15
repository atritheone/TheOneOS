#!/bin/python3.13



"""
build.py

build creates deterministic media diagnostic fixtures for The One OS.
"""



## imports
import os
import sys
import math
import struct



## fixture values
WIDTH = 64
HEIGHT = 36
FRAMES = 20
FPS = 10
SAMPLERATE = 48000
CHANNELS = 2
BITS = 16



## RIFF functions
def chunk(name, payload):

    payload = bytes(payload)
    padding = b'\x00' if len(payload) % 2 else b''
    return bytes(name) + struct.pack('<I', len(payload)) + payload + padding


def listchunk(name, payload):

    return chunk(b'LIST', bytes(name) + bytes(payload))


def streamheader(kind, handler, scale, rate, length, suggested, samplesize, width=0, height=0):

    return struct.pack(
        '<4s4sIHHIIIIIIIIhhhh',
        bytes(kind),
        bytes(handler),
        0,
        0,
        0,
        0,
        int(scale),
        int(rate),
        0,
        int(length),
        int(suggested),
        0xffffffff,
        int(samplesize),
        0,
        0,
        int(width),
        int(height),
    )



## media functions
def videoframe(index):

    rowbytes = WIDTH * 3
    padding = b'\x00' * ((4 - (rowbytes % 4)) % 4)
    output = bytearray()

    for row in reversed(range(HEIGHT)):

        for column in range(WIDTH):

            red = (index * 23 + column * 4) & 0xff
            green = (row * 7 + index * 11) & 0xff
            blue = (column * 2 + row * 3 + index * 17) & 0xff
            output.extend((blue, green, red))

        output.extend(padding)

    return bytes(output)


def audioframe(index):

    samples = SAMPLERATE // FPS
    output = bytearray()
    start = index * samples

    for offset in range(samples):

        sample = int(math.sin(((start + offset) * 2.0 * math.pi * 440.0) / SAMPLERATE) * 9000.0)
        packed = struct.pack('<h', sample)
        output.extend(packed * CHANNELS)

    return bytes(output)


def avifile(audio=True):

    firstvideo = videoframe(0)
    videoformat = struct.pack(
        '<IiiHHIIiiII',
        40,
        WIDTH,
        HEIGHT,
        1,
        24,
        0,
        len(firstvideo),
        0,
        0,
        0,
        0,
    )
    videolist = chunk(
        b'strh',
        streamheader(b'vids', b'DIB ', 1, FPS, FRAMES, len(firstvideo), 0, WIDTH, HEIGHT),
    )
    videolist += chunk(b'strf', videoformat)
    headers = listchunk(b'strl', videolist)
    streamcount = 1
    maximumbytes = len(firstvideo) * FPS

    if audio:

        blockalign = CHANNELS * (BITS // 8)
        audiosamples = SAMPLERATE * FRAMES // FPS
        audioformat = struct.pack(
            '<HHIIHH',
            1,
            CHANNELS,
            SAMPLERATE,
            SAMPLERATE * blockalign,
            blockalign,
            BITS,
        )
        audiolist = chunk(
            b'strh',
            streamheader(
                b'auds',
                b'\x00\x00\x00\x00',
                blockalign,
                SAMPLERATE * blockalign,
                audiosamples,
                len(audioframe(0)),
                blockalign,
            ),
        )
        audiolist += chunk(b'strf', audioformat)
        headers += listchunk(b'strl', audiolist)
        streamcount = 2
        maximumbytes += SAMPLERATE * blockalign

    mainheader = struct.pack(
        '<IIIIIIIIII4I',
        1000000 // FPS,
        maximumbytes,
        0,
        0,
        FRAMES,
        0,
        streamcount,
        max(len(firstvideo), len(audioframe(0)) if audio else 0),
        WIDTH,
        HEIGHT,
        0,
        0,
        0,
        0,
    )
    headerlist = listchunk(b'hdrl', chunk(b'avih', mainheader) + headers)
    movie = bytearray()

    for index in range(FRAMES):

        movie.extend(chunk(b'00db', videoframe(index)))

        if audio:

            movie.extend(chunk(b'01wb', audioframe(index)))

    payload = b'AVI ' + headerlist + listchunk(b'movi', movie)
    return b'RIFF' + struct.pack('<I', len(payload)) + payload


def writefixture(path, data):

    temporary = f'{path}.tmp-{os.getpid()}'

    try:

        with open(temporary, 'wb') as stream:

            stream.write(data)

        os.replace(temporary, path)

    finally:

        try:

            if os.path.exists(temporary):

                os.unlink(temporary)

        except Exception:

            pass


def main():

    root = str(sys.argv[1]) if len(sys.argv) > 1 else '/.ephemeral/media-tests'
    root = os.path.abspath(os.path.normpath(root))
    os.makedirs(root, mode=0o700, exist_ok=True)
    writefixture(os.path.join(root, 'sample audio video.avi'), avifile(audio=True))
    writefixture(os.path.join(root, 'sample video only.avi'), avifile(audio=False))
    return 0


if __name__ == '__main__':

    raise SystemExit(main())
