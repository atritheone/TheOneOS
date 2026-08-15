# T1OS VMSVGA video implementation

This directory contains the Mesa SVGA video implementation used by T1OS
VirtualBox VMSVGA. The complete hardware-wide Player architecture, support
matrix, telemetry, build gates, and physical certification procedure are in
`docs/video-hardware-playback.md`.

## Data path

1. `t1-video-decode` uses FFmpeg and VAAPI to decode into GPU-owned NV12
   surfaces.
2. The native decoder exports each surface as a DMA-BUF descriptor with PTS,
   duration, colour, and interlace metadata.
3. VA-API video processing produces a presentation surface near the visible
   video area.
4. `media.py` applies bounded decoder backpressure and schedules surfaces
   against the audio clock.
5. WindowServer authenticates the stream, validates the advertised fourcc and
   modifier, and imports one composed layer or separate Y/UV layers.
6. The OpenGL compositor acknowledges the first successful draw, then releases
   retired surfaces back to the decoder.

The native surface pool is bounded at 16 frames. This prevents an unbounded
decode backlog while preserving smooth playback when decode runs faster than
real time.

## VirtualBox implementation

The kernel patch generator extends `vmwgfx` for the VirtualBox PCI identity and
validates the VirtualBox D3D11 video command range. The Mesa patch generator
adds the SVGA Gallium video codec, packed NV12 allocation/export/import, and
the command bridge used by VirtualBox.

Retained command generations and video-content generations are separate.
Incoming frames invalidate the cached window texture without making an
otherwise valid retained-scene patch stale.

## Adaptive presentation sizing

Player starts with a GPU presentation surface near the current video area,
capped by framebuffer dimensions. After a substantial stable window-size
change, the native helper resizes through VA-API video processing without a
decoder restart. A 4K compressed stream is still decoded at coded resolution,
but a small window no longer exports and composites a full-size 4K surface.

## Build and acceptance

Build the combined hardware release:

```powershell
& "scripts/build graphics runtime.ps1" -Clean -Profile hardware -EnableNvidia
```

Validate packaged drivers and runtime dependencies:

```powershell
& "scripts/test hardware build.ps1"
```

Run the end-to-end VirtualBox gate:

```powershell
& "scripts/test video vbox.ps1" -InitialSetup
```

The gate requires VMSVGA/OpenGL hardware operation, a VA-API hardware decoder,
DMA-BUF imports and releases, changing captured frames, actual presentation
acknowledgements, clean completion, zero-copy telemetry, no audio underruns,
and bounded drop rate and A/V drift. Historical results from the older
submission-counting pipeline are not accepted by the current gate.
