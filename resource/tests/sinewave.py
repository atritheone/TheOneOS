#!/bin/python3.13


## imports
import os
import math
import time
import ctypes
import struct


## globals

LIBASOUND = "/the one/catalogue/python/libasound.so.2"
DEVNAME = b"hw:0,0"
RATE = 48000
CHANS = 2
HERTZ = 440.0
FRAMES = 1024
SECONDS = 3.0


## functions

def die(msg):

    raise SystemExit(msg)


def loadasound():

    if not os.path.exists(LIBASOUND):
        die(f"missing {LIBASOUND}")

    lib = ctypes.CDLL(LIBASOUND)

    lib.snd_strerror.argtypes = [ctypes.c_int]
    lib.snd_strerror.restype = ctypes.c_char_p

    lib.snd_pcm_open.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_char_p, ctypes.c_int, ctypes.c_int]
    lib.snd_pcm_open.restype = ctypes.c_int

    lib.snd_pcm_close.argtypes = [ctypes.c_void_p]
    lib.snd_pcm_close.restype = ctypes.c_int

    lib.snd_pcm_format_value.argtypes = [ctypes.c_char_p]
    lib.snd_pcm_format_value.restype = ctypes.c_int

    lib.snd_pcm_set_params.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint,
        ctypes.c_uint,
        ctypes.c_int,
        ctypes.c_uint
    ]
    lib.snd_pcm_set_params.restype = ctypes.c_int

    lib.snd_pcm_writei.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
    lib.snd_pcm_writei.restype = ctypes.c_long

    lib.snd_pcm_prepare.argtypes = [ctypes.c_void_p]
    lib.snd_pcm_prepare.restype = ctypes.c_int

    return lib


def alsaerr(lib, rc):

    return lib.snd_strerror(rc).decode(errors="replace")


def openpcm(lib):

    pcm = ctypes.c_void_p()

    stream = 0

    mode = 0

    rc = lib.snd_pcm_open(ctypes.byref(pcm), DEVNAME, stream, mode)

    if rc < 0:
        die(f"snd_pcm_open failed: {alsaerr(lib, rc)}")

    return pcm



def setpcm(lib, pcm):

    fmt = lib.snd_pcm_format_value(b"S16_LE")

    if fmt < 0:
        die("snd_pcm_format_value failed for S16_LE")

    acc = 3

    softresample = 0

    latencyus = 50000

    rc = lib.snd_pcm_set_params(
        pcm,
        fmt,
        acc,
        CHANS,
        RATE,
        softresample,
        latencyus
    )

    if rc < 0:
        die(f"snd_pcm_set_params failed: {alsaerr(lib, rc)}")

    rc = lib.snd_pcm_prepare(pcm)

    if rc < 0:
        die(f"snd_pcm_prepare failed: {alsaerr(lib, rc)}")


def makeframes(phase):

    out = bytearray()

    step = (2.0 * math.pi * HERTZ) / float(RATE)

    for _ in range(FRAMES):

        s = math.sin(phase)

        phase += step

        v = int(max(-1.0, min(1.0, s)) * 30000.0)

        out += struct.pack("<hh", v, v)

    return bytes(out), phase


def play():

    lib = loadasound()

    pcm = openpcm(lib)

    setpcm(lib, pcm)

    total = int(RATE * SECONDS)

    left = total

    phase = 0.0

    try:

        while left > 0:

            buf, phase = makeframes(phase)

            frames = FRAMES

            if frames > left:
                frames = left

            rc = lib.snd_pcm_writei(pcm, ctypes.c_char_p(buf), frames)

            if rc < 0:

                rc2 = lib.snd_pcm_prepare(pcm)

                if rc2 < 0:
                    die(f"recover prepare failed: {alsaerr(lib, rc2)}")

                continue

            left -= int(rc)

    finally:

        lib.snd_pcm_close(pcm)



# main

if __name__ == "__main__":

    play()
