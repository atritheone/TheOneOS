# T1OS Chromium 150 NVIDIA graphics and media overlay

This directory is the reviewable source overlay for Chromium
`150.0.7871.181`, revision
`24b04c927b23c39cf9c5227cc8dc6f64a744c8e9`. The apply tool refuses every
other revision.

The patched browser process opens four fresh `AF_UNIX/SOCK_SEQPACKET`
connections to the T1OS media service whenever it launches a sandboxed GPU
process. Chromium transfers those connected sockets through
`ChildProcessLauncherFileData::files_to_preload` under
`t1os-media-decode-0` through `t1os-media-decode-3`. The GPU process never sees
the service pathname and never opens CUDA, UVM, NVDEC, or NVIDIA device files.

Each `T1OSVideoDecoder` exclusively owns one connection. The fifth concurrent
decoder returns no platform decoder and Chromium may select a software decoder.
Four connections leave half of the daemon's default eight-session budget free
while an old GPU process exits during a GPU restart. Closing a GPU process
closes every descriptor in its pool; a replacement GPU process receives newly
connected descriptors.

Compressed access units are immutable sealed memfds. The negotiated output is
one of two exact contracts:

* `dma-buf`: NV12/P010 is exported as exactly two objects and two one-plane
  layers. Each object keeps its own natural NVIDIA modifier, and the explicit
  R/G versus G/R chroma order survives native-pixmap Mojo transport. Chromium
  converts the frame to a SharedImage and sends `RELEASE` only after the
  compositor releases it.
* `linear-memory`: the worker copies the decoded frame into one sealed composed
  NV12/P010 memfd. Chromium maps it as a software-readable `VideoFrame`; this
  mode validates NVDEC independently from NVIDIA EGL presentation.

Composed DMA-BUF output, a one-object descriptor disguised as separate layers,
unknown pixel formats, non-4:2:0 output, and implicit/invalid modifiers are all
rejected. Direct Chromium NVIDIA VA-API/CUDA decode remains quarantined; T1MD is
the only NVIDIA hardware-decoder route.

Decode and presentation are independent features:

* GN: `enable_t1os_video_decoder=true`
* decode runtime: `--enable-features=T1OSVideoDecoder`
* NVIDIA presentation runtime: `--enable-features=T1OSNvidiaPresentation`
* browser-only discovery:
  `--t1os-video-decode-socket=/.ephemeral/media/decode.sock`

The socket switch is deliberately not copied to the GPU command line. The
launcher supplies the decode output in both a browser switch and
`T1OS_MEDIA_DECODE_OUTPUT`; the browser broker requires an exact match before
opening its descriptor pool, and the GPU process independently derives the
T1MD HELLO feature set from the environment. Absence defaults to linear memory,
never DMA-BUF.

## End-to-end NVIDIA contract

The browser, renderer, and utility processes keep the canonical private T1OS
loader closure. Only the sandboxed GPU process receives the version-matched
NVIDIA EGL/GBM closure, vendor JSON, external-platform directory, and
`GBM_BACKEND=nvidia-drm`. No Chromium process receives `LIBVA_*`, `NVD_*`,
CUDA/UVM, or direct NVDEC authority.

For native presentation, the browser opens the selected T1OS render node and a
token-authorized WindowServer socket before GPU sandbox entry. Ozone creates an
XRGB8888 GBM window surface on that brokered device. Every frame carries an
explicit valid modifier, zero offset, pitch of at least `width * 4`, and a
bounded object size. Producer `glFinish` precedes descriptor transfer;
WindowServer copies the imported frame to its own retained GPU target, performs
the matching consumer `glFinish`, destroys the EGLImage, and only then sends the
generation-tagged release that permits GBM reuse.

The producer queue is bounded to three frames. Resize retires the old generation
asynchronously, and stale releases cannot touch a replacement GBM surface.
Destruction has only a 50 ms best-effort receipt drain; it cannot block the GPU
sequence for the former five-second teardown window. The cross-process
EGLStream singleton and its priority-inheritance futex sandbox exception are
removed.

The GPU broker mirrors Chromium's standard NVIDIA presentation authority at
T1OS's translated `/the one/drivers/nodes/nvidiactl`, `nvidia-modeset`, and
numbered GPU-node paths. This is required because the preload provider rewrites
NVIDIA's conventional device paths before a post-sandbox lazy open reaches the
broker. The render node remains descriptor-brokered, and UVM/CUDA/NVDEC nodes
remain unavailable to Chromium; decoding stays isolated in the T1MD service.

Presentation protocol v1 authorizes one visible Chromium root. The launcher
sets Chromium's real `session.restore_on_startup` preference to the single-root
default while native presentation is active. If Chromium nevertheless creates
a second top-level host, it receives a valid pbuffer-derived surface on the same
EGL display whose swaps complete without presentation; this contains the host
without a null-surface/context-loss restart loop. Visible multi-window native
presentation requires a future multiplexed protocol carrying per-widget
geometry and stacking.

The supported operating matrix is:

| NVIDIA presentation | T1MD | Renderer | Decode output |
|---|---|---|---|
| ready | ready | native NVIDIA EGL | two-object DMA-BUF |
| ready | unavailable | native NVIDIA EGL | Chromium software decode |
| rollback/unavailable | ready | SwiftShader | sealed linear memory |
| rollback/unavailable | unavailable | SwiftShader | Chromium software decode |

Runtime rollback is `T1OS_CHROMIUM_NVIDIA_PRESENTATION=0` or kernel option
`t1os.chromium.nvidia-presentation=0`. T1MD has its independent settings,
environment, and kernel kill switches. A failure in either stage therefore
does not silently enable direct NVIDIA VA-API or grant the wrong process a
vendor loader.

## Failure mapping and acceptance gates

The implementation treats the observed failures as contract violations, not
generic GPU instability:

| Symptom | Contract failure | Guard |
|---|---|---|
| Pink/green frames | synthetic common object/modifier or wrong UV order | exact two-object topology, per-plane modifiers, explicit chroma order |
| `Aw, Snap!` error 11 | child-process crash after invalid import/lifetime | strict descriptor and linear-plane pointer/stride/dimension bounds, sealed inputs, fail-closed output negotiation |
| GPU context loss | mixed loader closure, null second root, unproven-context GL dispatch, or blocking teardown | GPU-only NVIDIA environment, auxiliary surface containment, async generations, blocking-aware reader join, no failure-path `glFinish` |
| Chromium crash | stale release or singleton surface aliasing | generation/frame ownership keys and per-widget surface instances |

Before a hardware image is promoted, the pinned overlay must apply twice
idempotently, the targeted T1OS objects must compile with bounded parallelism,
the focused media and sandbox unit tests must pass, and Ninja dry-run output
must be inspected before any wider build. Target hardware acceptance then
requires 8-bit NV12 and 10-bit P010 playback, seek/reset, repeated resize and
fullscreen transitions, GPU-process restart, software-presentation plus T1MD
linear mode, native-presentation plus software decode, and a sustained playback
soak with no pink frames, SIGSEGV, context loss, or NVIDIA Xid/reset evidence.

The Linux DNS watcher and network-service sandbox use
`/the one/settings/network/dns.txt`, matching the T1OS libc resolver patch.
The compiled browser does not fall back to `/etc/resolv.conf`.

The development profile is an optimized, symbolized DCHECK build
(`is_official_build=false`, `dcheck_always_on=true`, `symbol_level=2`).
Chromium 150's libc++ no longer implements its retired iterator-debugging
mode, so `enable_iterator_debugging=false`; libc++ hardening and Chromium
runtime checks remain enabled.

`apply.py` copies new files and performs fingerprinted anchored edits to the
pinned source tree. It reconstructs every transformed file from the pinned Git
blob, permits only the exact transformed/overlay dirty-path set, and hashes
all expected patched bytes. The compiled marker header is also hashed after
normalizing only its self-referential source digest. The frozen fingerprints
are:

* protocol header:
  `11a319c26e499415cf39a3b6b5c59c3801b2e91859500472b92c6be1fcaceba0`
* complete source overlay:
  `597ed8a32051a65e12a3582801369c8caa9dabcf8ef7e36720cfaf1be3919f4e`

Run the tool twice to verify idempotence:

```text
python3 apply.py --source /path/to/chromium/src
python3 apply.py --source /path/to/chromium/src --check
```

The packaged manifest must advertise the decoder only after the patched binary
has been built and contains the exact build marker from `manifest.json`.
Unmodified Google Chrome must never receive a truthful brokered-decoder marker.
Packaging also proves the specified-versus-actual gclient/DEPS revisions,
clean nested Git repositories, exact GN arguments, and passing focused tests.
A full build additionally requires no pending Ninja work. The bounded recovery
path instead attests the explicit T1OS objects, affected archives, three links,
and focused test binaries; it intentionally does not execute unrelated stale
WebUI/resource edges. The stage is restricted to the dedicated sibling
`t1os-runtime-<profile>` directory.

The Chromium checkout and compiled output are intentionally not stored here.
No C/C++ source from this overlay is deployed to T1OS; only compiled Chromium
artifacts and approved data resources are packaged. No uncompiled language
file is deployed by this Chromium runtime path; T1OS's existing Python
orchestration remains separate.
