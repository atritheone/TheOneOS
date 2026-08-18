import sys as _t1os_incremental_sys
from pathlib import Path as _T1OSIncrementalPath

if __name__ == "__main__":
    _t1os_incremental_scripts = next(
        (parent for parent in _T1OSIncrementalPath(__file__).resolve().parents
         if (parent / "incremental_test.py").is_file()),
        None,
    )
    if _t1os_incremental_scripts is not None:
        _t1os_incremental_sys.path.insert(0, str(_t1os_incremental_scripts))
        from _incremental_test import guard as _t1os_incremental_guard
        if _t1os_incremental_guard(__file__, _t1os_incremental_sys.argv[1:]):
            raise SystemExit(0)

import ast
import builtins
import contextlib
import ctypes
import datetime
import errno
import io
import importlib.util
import json
import os
import queue
import selectors
import struct
import subprocess
import sys
import tempfile
import threading
import time
import types
from pathlib import Path


def loadgraphics(projectroot):

    fcntl = types.ModuleType("fcntl")
    fcntl.ioctl = lambda *args, **kwargs: 0
    sys.modules["fcntl"] = fcntl

    freetype = types.ModuleType("freetype")
    freetype.FT_LOAD_DEFAULT = 0
    freetype.FT_LOAD_TARGET_LIGHT = 0
    freetype.Face = object
    sys.modules["freetype"] = freetype

    reignpackage = types.ModuleType("reign")
    reign = types.ModuleType("reign.reign")
    reign.currentdatetime = lambda epoch=None: datetime.datetime.fromtimestamp(
        time.time() if epoch is None else epoch,
        datetime.timezone.utc,
    )
    reign.timestamp = lambda: "test"
    sys.modules["reign"] = reignpackage
    sys.modules["reign.reign"] = reign

    goddesspackage = types.ModuleType("GODDESS")
    goddess = types.ModuleType("GODDESS.GODDESS")
    goddess.formatlog = (
        lambda software, message, epoch=None: f"[{software}] {message}"
    )
    sys.modules["GODDESS"] = goddesspackage
    sys.modules["GODDESS.GODDESS"] = goddess

    path = projectroot / "source/build software/graphics/graphics.py"
    spec = importlib.util.spec_from_file_location("t1os_graphics_presentation_test", path)
    graphics = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(graphics)
    return graphics


def loadsourcefunctions(source, names, namespace):

    tree = ast.parse(source)
    selected = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in set(names)
    ]

    if len(selected) != len(set(names)):
        found = {node.name for node in selected}
        raise SystemExit(
            f"could not load recovery functions {sorted(set(names) - found)}"
        )

    module = ast.Module(body=selected, type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, "<graphics-recovery-state-test>", "exec"), namespace)
    return namespace


def validatenvidialockscreenreceipt(source, description):

    namespace = loadsourcefunctions(
        source,
        ("lockscreenreceiptphysicallyverified",),
        {},
    )
    verify = namespace["lockscreenreceiptphysicallyverified"]
    state = {
        "backend": "kms-framebuffer",
        "drm_driver": "nvidia-drm",
        "hardware_accelerated": False,
        "full_coverage": True,
        "frame_sequence": 4,
        "presentation_proof": {
            "verified": True,
            "scanout": True,
            "nonblack": True,
            "connector_connected": True,
            "connector_routed": True,
            "connector_link_status": "good",
            "presentation_boundary": "nvidia-continuous-scanout",
            "vblank_sequence": {
                "supported": False,
                "unsupported": True,
                "advanced": False,
                "errno": 95,
            },
            "dirty_status": "unsupported:38",
            "flush_status": "not-required:drm-ioctl-boundary",
            "present_sequence": 2,
            "modeset_sequence": 1,
            "write_committed": True,
            "mode_matches": True,
            "readback": False,
            "readback_skipped": "write-combined-device-mapping",
        },
    }

    if not verify(state):
        raise SystemExit(
            f"{description} rejected the exact NVIDIA CPU-KMS receipt"
        )

    for field, weakvalue in (
        ("dirty_status", "complete"),
        ("flush_status", "not-required"),
        ("present_sequence", 1),
        ("modeset_sequence", 0),
    ):
        weak = json.loads(json.dumps(state))
        weak["presentation_proof"][field] = weakvalue

        if verify(weak):
            raise SystemExit(
                f"{description} accepted weak NVIDIA evidence {field}={weakvalue!r}"
            )

    wrongdriver = json.loads(json.dumps(state))
    wrongdriver["drm_driver"] = "nouveau"

    if verify(wrongdriver):
        raise SystemExit(
            f"{description} allowed another driver into the NVIDIA fallback"
        )


def validateacceleratedlockscreenreceipt(source, description):

    namespace = loadsourcefunctions(
        source,
        ("lockscreenreceiptphysicallyverified",),
        {},
    )
    verify = namespace["lockscreenreceiptphysicallyverified"]
    state = {
        "backend": "opengl",
        "hardware_accelerated": True,
        "full_coverage": True,
        "renderer": "SVGA3D",
        "frame_sequence": 4,
        "presentation_proof": {
            "verified": True,
            "scanout": True,
            "nonblack": True,
            "contrast": True,
        },
    }

    if not verify(state):
        raise SystemExit(f"{description} rejected a content-verified SVGA3D receipt")

    for field in ("verified", "scanout", "nonblack", "contrast"):
        invalid = json.loads(json.dumps(state))
        invalid["presentation_proof"][field] = False

        if verify(invalid):
            raise SystemExit(
                f"{description} accepted an SVGA3D receipt without {field} proof"
            )


def validateacceleratedcontentproof(source):

    namespace = {
        "os": os,
        "stat": __import__("stat"),
        "backendinfo": lambda: {"renderer": "NVK", "drm_driver": "nouveau"},
    }
    loadsourcefunctions(
        source,
        (
            "windowbufferdimensions",
            "windowbuffercontentproof",
            "gpuwindowdynamicvideo",
            "gpuwindowretainedsceneallowed",
            "gpuwindowretainedsystem",
            "managedcontentproof",
            "acceleratedcontentproof",
        ),
        namespace,
    )

    with tempfile.TemporaryDirectory(prefix="t1os-content-proof-") as directory:
        path = os.path.join(directory, "lockscreen.raw")
        width = 32
        height = 24
        size = width * height * 4

        with open(path, "wb") as stream:
            stream.write(bytes((0, 0, 0, 255)) * (width * height))

        os.chmod(path, 0o660)
        status = os.stat(path)
        window = {
            "w": width,
            "h": height,
            "buffer": path,
            "_owned_buffer": path,
            "buffer_offset": 0,
            "buffer_stride": width * 4,
            "_buffer_peer_uid": status.st_uid,
            "_buffer_server_gid": status.st_gid,
            "_telemetry_gpu_upload_bytes": size,
            "_telemetry_gpu_draw_calls": 1,
            "_managed_only": False,
        }
        proof = namespace["acceleratedcontentproof"](window)

        if proof.get("verified") or proof.get("nonblack") or proof.get("contrast"):
            raise SystemExit("a uniform black lock-screen buffer passed content proof")

        with open(path, "r+b") as stream:
            stream.seek((width + 1) * 4)
            stream.write(bytes((239, 239, 239, 255)))

        proof = namespace["acceleratedcontentproof"](window)

        if proof.get("verified"):
            raise SystemExit("a visible CPU-authored lock screen passed GPU-only proof")

    managed = {
        "role": "lockscreen",
        "_managed_only": True,
        "_gpu_command_generation": 2,
        "_gpu_presented_generation": 0,
        "_telemetry_scene_commands_drawn": 3,
        "_telemetry_scene_texture_renders": 1,
        "_telemetry_gpu_draw_calls": 1,
        "_telemetry_cpu_damage_bytes": 0,
        "_telemetry_gpu_upload_bytes": 0,
        "gpu_commands": [{"kind": "text", "color": [239, 239, 239, 255]}],
    }

    if namespace["acceleratedcontentproof"](managed).get("verified"):
        raise SystemExit("an unpresented managed lock screen passed content proof")

    managed["_gpu_presented_generation"] = 2

    if not namespace["acceleratedcontentproof"](managed).get("verified"):
        raise SystemExit("a physically presented managed lock screen failed proof")

    managed["role"] = "window"

    if namespace["acceleratedcontentproof"](managed).get("verified"):
        raise SystemExit("a non-system managed surface passed lock-screen proof")

    managed["role"] = "lockscreen"
    managed["_telemetry_cpu_damage_bytes"] = 4

    if namespace["acceleratedcontentproof"](managed).get("verified"):
        raise SystemExit("a CPU-authored managed lock screen passed GPU-only proof")


def validatedriverserverzombiedetection(source):

    tree = ast.parse(source)
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "processalive"
    )
    killcalls = []
    namespace = {
        "os": types.SimpleNamespace(
            kill=lambda pid, signal: killcalls.append((pid, signal))
        ),
        "Path": Path,
    }
    module = ast.Module(body=[function], type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, "<driverserver-process-state-test>", "exec"), namespace)

    with tempfile.TemporaryDirectory() as temporary:
        processroot = Path(temporary)
        statdirectory = processroot / "4242"
        statdirectory.mkdir()
        namespace["PROCESSROOT"] = processroot
        statpath = statdirectory / "stat"
        statpath.write_text(
            "4242 (early boot animation) Z 1 1 1\n",
            encoding="ascii",
        )
        if namespace["processalive"](4242) is not False or killcalls:
            raise SystemExit(
                "DriverServer does not recognize a released T1OS procfs zombie"
            )

        statpath.write_text(
            "4242 (early boot animation) S 1 1 1\n",
            encoding="ascii",
        )
        if namespace["processalive"](4242) is not True:
            raise SystemExit("DriverServer rejects a live T1OS procfs process")
        if killcalls != [(4242, 0)]:
            raise SystemExit("DriverServer did not verify the live process")


def validatevideoauthorizationlogging(source):

    tree = ast.parse(source)
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "videoauthorize"
    )
    graphicscalls = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "graphicslog"
    ]
    if len(graphicscalls) != 2:
        raise SystemExit(
            "WindowServer video authorization must log exactly one issued "
            "and one rejected lifecycle record"
        )

    for call in graphicscalls:
        if "token" in ast.unparse(call).casefold():
            raise SystemExit(
                "WindowServer video authorization graphicslog references "
                "presentation credentials"
            )

    if "DEBUGWINDOWSERVER" in ast.unparse(function):
        raise SystemExit(
            "WindowServer video authorization lifecycle logging is debug-gated"
        )

    logs = []
    responses = []
    client = 73
    window = 19
    owneridentity = {
        "pid": 7301,
        "starttime": 190073,
        "domain": "chromium",
    }
    namespace = {
        "json": json,
        "time": types.SimpleNamespace(monotonic=lambda: 100.0),
        "clients": {client: {"identity": owneridentity}},
        "windows": {
            window: {
                "cid": client,
                "path": "/the one/build/chromium/chromium.py",
                "role": "window",
                "_video_streams": {},
                "_video_queues": {},
            },
        },
        "VIDEOAUTH": {},
        "VIDEOMAXSTREAMS": 32,
        "VIDEOPACKETLIMIT": 1024 * 1024,
        "VIDEOSOCKPATH": "/.ephemeral/windowserver/video.sock",
        "processidentitycurrent": lambda identity: identity is owneridentity,
        "sendjson": lambda cid, message: responses.append((cid, message)),
        "graphicslog": logs.append,
    }
    module = ast.Module(body=[function], type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, "<video-authorization-log-test>", "exec"), namespace)

    credential = "credential-that-must-never-be-logged-" + ("a" * 64)
    stream = "__t1os_chromium_presentation__"
    namespace["videoauthorize"](
        client,
        {
            "winid": window,
            "token": credential,
            "stream": stream,
            "surface_type": "presentation",
        },
    )

    if credential not in namespace["VIDEOAUTH"]:
        raise SystemExit("WindowServer rejected a valid presentation credential")
    if len(logs) != 1 or "video authorization issued" not in logs[0]:
        raise SystemExit(
            "WindowServer did not emit the issued authorization lifecycle record"
        )
    for expected in (
        f"client={client}",
        f"window={window}",
        "stream_class=chromium-presentation",
        f"stream_length={len(stream)}",
        "surface_type=presentation",
        "reusable=True",
    ):
        if expected not in logs[0]:
            raise SystemExit(
                "WindowServer issued authorization log is missing " + expected
            )
    if stream in logs[0]:
        raise SystemExit(
            "WindowServer persisted an application-supplied stream identifier"
        )
    if (
        len(responses) != 1
        or responses[0][0] != client
        or responses[0][1].get("op") != "VIDEO_AUTHORIZED"
    ):
        raise SystemExit("WindowServer did not acknowledge video authorization")
    if credential in json.dumps({"logs": logs, "responses": responses}):
        raise SystemExit(
            "WindowServer exposed a presentation credential in authorization output"
        )

    logs.clear()
    responses.clear()
    namespace["videoauthorize"](
        client,
        {
            "winid": window + 1,
            "token": credential,
            "stream": stream,
            "surface_type": "presentation",
        },
    )
    if len(logs) != 1 or "video authorization rejected" not in logs[0]:
        raise SystemExit(
            "WindowServer did not emit the rejected authorization lifecycle record"
        )
    if "detail=\"unknown_window\"" not in logs[0]:
        raise SystemExit(
            "WindowServer rejected authorization log lacks a bounded reason"
        )
    if (
        len(responses) != 1
        or responses[0][1].get("code") != "video_authorize_failed"
    ):
        raise SystemExit("WindowServer did not reject invalid video authorization")
    if credential in json.dumps({"logs": logs, "responses": responses}):
        raise SystemExit(
            "WindowServer exposed a rejected presentation credential in output"
        )

    logs.clear()
    responses.clear()
    oversizedwindow = "private-window-identifier-" + ("z" * 4096)
    namespace["videoauthorize"](
        client,
        {
            "winid": oversizedwindow,
            "token": credential,
            "stream": "private-stream-name",
            "surface_type": "video",
        },
    )
    if (
        len(logs) != 1
        or len(logs[0]) > 1024
        or "private-stream-name" in logs[0]
        or ("z" * 128) in logs[0]
    ):
        raise SystemExit(
            "WindowServer rejection logging retained an unbounded/private field"
        )


def validatewindowbufferpermissions(graphics):

    # The shared graphics module is imported by uid-1000 clients.  A protected
    # central log must therefore fall back to supervised stderr without ever
    # replacing the operational exception being diagnosed.
    originalopen = builtins.open
    originallogfile = graphics.LOGFILE
    originalgeteuid = getattr(graphics.os, "geteuid", None)
    diagnostics = io.StringIO()

    def denycentrallog(path, *args, **kwargs):

        if os.fspath(path) == graphics.LOGFILE:
            raise PermissionError(errno.EACCES, "test central log denial", path)
        return originalopen(path, *args, **kwargs)

    try:
        graphics.LOGFILE = "/tmp/t1os-test-protected-graphics.log"
        graphics.os.geteuid = lambda: 0
        builtins.open = denycentrallog

        with contextlib.redirect_stderr(diagnostics):
            result = graphics.log("test non-fatal graphics failure", flush=True)

        if result is not False or "test central log denial" not in diagnostics.getvalue():
            raise SystemExit(
                "an unavailable central graphics log can still escape or hide diagnostics"
            )
    finally:
        builtins.open = originalopen
        graphics.LOGFILE = originallogfile

        if originalgeteuid is None:
            delattr(graphics.os, "geteuid")
        else:
            graphics.os.geteuid = originalgeteuid

    originalosopen = graphics.os.open

    def denybuffer(path, flags, mode=0o777):
        raise PermissionError(errno.EACCES, "test window buffer denial", path)

    try:
        graphics.os.open = denybuffer

        try:
            graphics.initbuffer("/.ephemeral/windowserver/buffers/test.raw", 4, 3)
        except graphics.WindowBufferAccessError as error:
            if (
                error.stage != "open"
                or error.errno != errno.EACCES
                or "test window buffer denial" not in str(error)
                or "graphics.py.log" in str(error)
            ):
                raise SystemExit(
                    "window-buffer denial did not preserve its original open error"
                )
        else:
            raise SystemExit("window-buffer open denial was swallowed")
    finally:
        graphics.os.open = originalosopen

    with tempfile.TemporaryDirectory(prefix="t1os-window-buffer-") as directory:
        path = os.path.join(directory, "surface.raw")
        expected = 7 * 5 * 4

        with open(path, "wb") as stream:
            stream.truncate(expected)

        if graphics.initbuffer(path, 7, 5) is not True:
            raise SystemExit("a valid peer-owned window buffer did not initialize")

        try:
            if (
                graphics._backend != "filebuffer"
                or graphics._FILE_MAP is None
                or graphics._FILE_FD is None
                or len(graphics._buffer) != expected
            ):
                raise SystemExit("valid window-buffer state was not committed atomically")
        finally:
            graphics.baselineclose()

        # WindowServer keeps the high-water allocation after a logical shrink
        # so an older client mapping cannot fault.  The client maps only the
        # current logical prefix and must accept that retained capacity.
        with open(path, "wb") as stream:
            stream.truncate(expected * 2)

        if graphics.initbuffer(path, 7, 5) is not True:
            raise SystemExit("a retained-capacity window buffer did not initialize")

        try:
            if len(graphics._FILE_MAP) != expected or len(graphics._buffer) != expected:
                raise SystemExit("retained capacity leaked into logical buffer geometry")
        finally:
            graphics.baselineclose()


def main():

    projectroot = Path(sys.argv[1]).resolve()
    graphics = loadgraphics(projectroot)
    validatewindowbufferpermissions(graphics)
    removed = []
    released = []

    presentationdescriptor = {
        "transport": "rgb-gbm-dmabuf-v1",
        "sync_mode": "glfinish-producer-consumer",
        "origin": "bottom-left",
        "generation": 1,
        "frame": 1,
        "width": 10,
        "height": 10,
        "objects": [{"size": 400, "modifier": 0}],
        "layers": [{
            "width": 10,
            "height": 10,
            "fourcc": graphics.DRM_FORMAT_XRGB8888,
            "planes": [{"object": 0, "offset": 0, "pitch": 40}],
        }],
    }
    packedvideo = {
        "width": 380,
        "height": 214,
        "format": "drm_prime",
        "export_mode": "composed",
        "objects": [{"size": 129024, "modifier": 0}],
        "layers": [{
            "width": 380,
            "height": 214,
            "fourcc": graphics.DRM_FORMAT_NV12,
            "planes": [
                {"object": 0, "offset": 0, "pitch": 384},
                {"object": 0, "offset": 86016, "pitch": 384},
            ],
        }],
    }
    originaldriver = graphics._drmdriver

    try:
        graphics._drmdriver = "vmwgfx"
        normalizedvideo = graphics._gpuvideonormalizedescriptor(packedvideo)

        if (
            normalizedvideo.get("export_mode") != "vmwgfx-planar-views"
            or normalizedvideo.get("source_export_mode") != "composed"
            or len(normalizedvideo.get("layers", [])) != 2
            or normalizedvideo["layers"][0].get("fourcc") != graphics.DRM_FORMAT_R8
            or normalizedvideo["layers"][1].get("fourcc") != graphics.DRM_FORMAT_GR88
            or normalizedvideo["layers"][0].get("planes", [{}])[0].get("offset") != 0
            or normalizedvideo["layers"][1].get("planes", [{}])[0].get("offset") != 86016
            or normalizedvideo["layers"][1].get("width") != 190
            or normalizedvideo["layers"][1].get("height") != 107
        ):
            raise SystemExit("VMSVGA packed NV12 was not split into bounded GPU plane views")

        graphics._drmdriver = "nouveau"

        if graphics._gpuvideonormalizedescriptor(packedvideo).get("layers") != packedvideo["layers"]:
            raise SystemExit("VMSVGA video normalization escaped the vmwgfx backend")
    finally:
        graphics._drmdriver = originaldriver
    if (
        graphics._gpuvideosurfaceverticalcoordinates({}) != (0.0, 1.0)
        or graphics._gpuvideosurfaceverticalcoordinates({
            "presentation_dmabuf": True,
            "origin": "bottom-left",
            "row_order": "top-left",
        }) != (0.0, 1.0)
        or graphics._gpuvideosurfaceverticalcoordinates({
            "row_order": "bottom-left",
        }) != (1.0, 0.0)
    ):
        raise SystemExit(
            "Chromium RGB DMA-BUF row order would invert the retained frame"
        )
    malformedpresentation = []
    invalidmodifier = json.loads(json.dumps(presentationdescriptor))
    invalidmodifier["objects"][0]["modifier"] = graphics.DRM_FORMAT_MOD_INVALID
    malformedpresentation.append(("invalid modifier", invalidmodifier))
    nonzerooffset = json.loads(json.dumps(presentationdescriptor))
    nonzerooffset["layers"][0]["planes"][0]["offset"] = 1
    malformedpresentation.append(("nonzero offset", nonzerooffset))
    shortpitch = json.loads(json.dumps(presentationdescriptor))
    shortpitch["layers"][0]["planes"][0]["pitch"] = 39
    malformedpresentation.append(("short pitch", shortpitch))
    undersizedobject = json.loads(json.dumps(presentationdescriptor))
    undersizedobject["objects"][0]["size"] = 399
    malformedpresentation.append(("undersized object", undersizedobject))

    for description, descriptor in malformedpresentation:
        try:
            graphics.gpupresentationbuffercreate(descriptor, [7])
        except ValueError:
            pass
        else:
            raise SystemExit(
                f"Chromium RGB presentation accepted {description}"
            )

    mode30 = graphics.drmModeModeInfo()
    mode30.hdisplay = 3840
    mode30.vdisplay = 2160
    mode30.vrefresh = 30
    mode30.clock = 297000
    mode60 = graphics.drmModeModeInfo()
    mode60.hdisplay = 3840
    mode60.vdisplay = 2160
    mode60.vrefresh = 60
    mode60.clock = 594000

    if graphics.kmsmoderefreshrank(mode60) <= graphics.kmsmoderefreshrank(mode30):
        raise SystemExit("KMS mode ranking does not prefer the higher refresh rate")

    if graphics.kmsmoderefresh(mode60) != 60.0:
        raise SystemExit("KMS refresh-rate telemetry is incorrect")

    originaleglforrequire = graphics._egl

    class RequireEGL:

        def __init__(self, error):
            self.error = error

        def eglGetError(self):
            return self.error

    try:
        graphics._egl = RequireEGL(graphics.EGL_CONTEXT_LOST)

        try:
            graphics.openglrequire(0, "synthetic EGL init")
        except graphics.GPUDeviceLostError:
            pass
        else:
            raise SystemExit(
                "EGL_CONTEXT_LOST during provider initialization was not "
                "classified as GPU device loss"
            )

        graphics._egl = RequireEGL(0x3003)

        try:
            graphics.openglrequire(0, "synthetic EGL allocation")
        except graphics.GPUDeviceLostError:
            raise SystemExit(
                "ordinary EGL initialization failure incorrectly authorized "
                "a GPU reset"
            )
        except RuntimeError:
            pass
        else:
            raise SystemExit("ordinary EGL initialization failure was ignored")
    finally:
        graphics._egl = originaleglforrequire

    nvidiavideosaved = {
        name: getattr(graphics, name)
        for name in (
            "_backend",
            "_egl",
            "_gles",
            "_egldisplay",
            "_eglcontext",
            "_eglcreateimage",
            "_egldestroyimage",
            "_glimage_target_texture",
            "_eglvendor",
            "_eglextensions",
            "_eglextensionsqueried",
            "_eglquerydmabufmodifiers",
            "_glextensions",
            "_openglprovider",
            "_glrenderer",
        )
    }

    class NVIDIAColdStartEGL:

        def __init__(self):
            self.extensionqueries = 0

        def eglQueryString(self, display, name):
            if name == graphics.EGL_EXTENSIONS:
                self.extensionqueries += 1
                raise RuntimeError(
                    "NVIDIA cold-start EGL extension query must not run"
                )
            return b"NVIDIA"

    nvidiacoldstartegl = NVIDIAColdStartEGL()

    try:
        graphics._backend = "opengl"
        graphics._egl = nvidiacoldstartegl
        graphics._gles = object()
        graphics._egldisplay = object()
        graphics._eglcontext = object()
        graphics._eglcreateimage = object()
        graphics._egldestroyimage = object()
        graphics._glimage_target_texture = object()
        graphics._eglvendor = "NVIDIA"
        graphics._eglextensions = frozenset()
        graphics._eglextensionsqueried = False
        graphics._eglquerydmabufmodifiers = object()
        graphics._glextensions = None
        graphics._openglprovider = "nvidia"
        graphics._glrenderer = "NVIDIA synthetic renderer"

        api = graphics.gpuapi()
        info = graphics.backendinfo()

        if (
            nvidiacoldstartegl.extensionqueries != 0
            or not graphics._gpuvideomodifierimportavailable()
            or api.get("video_surfaces", {}).get("available") is not False
            or info.get("gpu_api", {})
            .get("video_surfaces", {})
            .get("available") is not False
        ):
            raise SystemExit(
                "NVIDIA capability reporting re-entered the unsafe cold-start "
                "EGL extension query"
            )
    finally:
        for name, value in nvidiavideosaved.items():
            setattr(graphics, name, value)

    class FakeDRM:

        def drmHandleEvent(self, fd, contextpointer):

            context = ctypes.cast(
                contextpointer,
                ctypes.POINTER(graphics.drmEventContext),
            ).contents
            callbacktype = ctypes.CFUNCTYPE(
                None,
                ctypes.c_int,
                ctypes.c_uint,
                ctypes.c_uint,
                ctypes.c_uint,
                ctypes.c_void_p,
            )
            callbacktype(context.page_flip_handler)(fd, 1, 0, 0, None)
            return 0

        def drmModeRmFB(self, fd, framebuffer):

            removed.append((fd, int(framebuffer)))
            return 0

        def drmModeSetCrtc(self, *args):

            return 0

        def drmModePageFlip(self, *args):

            return 0

    class FakeGBM:

        def gbm_surface_release_buffer(self, surface, bo):

            released.append((surface, bo))

        def gbm_surface_lock_front_buffer(self, surface):

            return "new-bo"

    class FakeEGL:

        def eglSwapBuffers(self, display, surface):

            return 1

    class FakeGLES:

        def glFinish(self):
            return None

        def glGetError(self):
            return graphics.GL_NO_ERROR

    graphics._backend = "opengl"
    graphics.log = lambda *args, **kwargs: None
    graphics._drmfd = 7
    graphics._drm = FakeDRM()
    graphics._gbm = FakeGBM()
    graphics._egl = FakeEGL()
    graphics._gles = FakeGLES()
    graphics._eglcontext = "context"
    graphics._egldisplay = "display"
    graphics._eglsurface = "egl-surface"
    graphics._gbmsurface = "gbm-surface"
    graphics._drmconnector = 2
    graphics._drmcrtc = 3
    graphics._drmmode = graphics.drmModeModeInfo()
    graphics._gbmbo = "old-bo"
    graphics._gbmbosurface = "old-surface"
    graphics._gbmfb = 10
    graphics._drmeventdriven = True
    graphics.kmsframebuffer = lambda bo: 11

    if not graphics.kmsscanout():
        raise SystemExit("event-driven scanout submission failed")

    if not graphics._drmflip or graphics._drmpendingbo != "new-bo":
        raise SystemExit("event-driven scanout did not retain its pending buffer")

    if not graphics.kmspresentationpending():
        raise SystemExit("public presentation state did not report the submitted flip")

    if graphics._gbmbo != "old-bo" or removed or released:
        raise SystemExit("displayed buffer was released before page-flip completion")

    if not graphics.kmshandlepresentationevent():
        raise SystemExit("DRM page-flip event did not complete the presentation")

    if graphics._drmflip or graphics._drmpendingbo is not None:
        raise SystemExit("completed DRM page flip remained pending")

    if graphics.kmspresentationpending():
        raise SystemExit("public presentation state remained pending after completion")

    if graphics._gbmbo != "new-bo" or graphics._gbmfb != 11:
        raise SystemExit("completed DRM page flip did not promote the new buffer")

    if removed != [(7, 10)] or released != [("old-surface", "old-bo")]:
        raise SystemExit("previous scanout buffer lifecycle was not completed safely")

    if graphics._gputelemetry["page_flip_submissions"] != 1:
        raise SystemExit("page-flip submission telemetry was not recorded")

    if graphics._gputelemetry["page_flips"] != 1:
        raise SystemExit("page-flip completion telemetry was not recorded")

    graphics._drmlastflipsequence = None
    graphics._drmlastfliptimestampus = None
    graphics.drmpageflip(7, 100, 10, 0, None)
    graphics.drmpageflip(7, 101, 10, 16667, None)

    if (
        graphics._gputelemetry["page_flip_sequence"] != 101
        or graphics._gputelemetry["page_flip_timestamp_us"] != 10016667
        or graphics._gputelemetry["page_flip_sequence_delta"] != 1
        or graphics._gputelemetry["page_flip_interval_ms"] != 16.667
    ):
        raise SystemExit("DRM callback cadence telemetry is incorrect")

    graphics.drmpageflip(7, 103, 10, 50001, None)

    if (
        graphics._gputelemetry["page_flip_sequence_delta"] != 2
        or graphics._gputelemetry["page_flip_interval_ms"] != 33.334
    ):
        raise SystemExit("DRM callback telemetry did not expose a two-vblank gap")

    graphics._drmlastflipsequence = None
    graphics._drmlastfliptimestampus = None
    graphics.drmpageflip(7, 0xFFFFFFFF, 20, 0, None)
    graphics.drmpageflip(7, 0, 20, 16667, None)

    if graphics._gputelemetry["page_flip_sequence_delta"] != 1:
        raise SystemExit("DRM callback cadence did not handle uint32 sequence wrap")

    graphics._kmsresetpresentationcadence()
    graphics.drmpageflip(7, 0, 30, 0, None)
    graphics.drmpageflip(7, 0, 30, 16667, None)
    nvidiacadence = graphics.gpumetrics()

    if (
        graphics._gputelemetry["page_flip_sequence_delta"] != 0
        or graphics._gputelemetry["page_flip_interval_ms"] != 16.667
        or int(nvidiacadence.get("presentation_samples", 0)) != 1
        or abs(float(nvidiacadence.get("presented_fps", 0.0)) - 59.999) > 0.01
    ):
        raise SystemExit(
            "timestamp-only NVIDIA DRM callback cadence was not measured"
        )

    graphics.drmpageflip(7, 1, 19, 0, None)

    if (
        graphics._gputelemetry["page_flip_sequence_delta"] != 0
        or graphics._gputelemetry["page_flip_interval_ms"] != 0.0
    ):
        raise SystemExit("backward DRM callback timestamp poisoned cadence telemetry")

    class LostEGL:

        def eglSwapBuffers(self, display, surface):
            return 0

        def eglGetError(self):
            return graphics.EGL_CONTEXT_LOST

    graphics._egl = LostEGL()

    try:
        graphics.kmsscanout()
    except graphics.GPUDeviceLostError:
        pass
    else:
        raise SystemExit(
            "EGL_CONTEXT_LOST was not classified as a GPU device failure"
        )
    finally:
        graphics._egl = FakeEGL()

    class EventErrorDRM:

        def __init__(self, error):
            self.error = int(error)

        def drmHandleEvent(self, fd, contextpointer):
            ctypes.set_errno(self.error)
            return -1

    graphics._drmflip = True
    graphics._drm = EventErrorDRM(errno.ENODEV)

    try:
        graphics.kmshandlepresentationevent()
    except graphics.GPUDeviceLostError:
        pass
    else:
        raise SystemExit(
            "DRM ENODEV was not classified as a GPU device failure"
        )

    graphics._drm = EventErrorDRM(errno.EINVAL)

    try:
        graphics.kmshandlepresentationevent()
    except graphics.GPUDeviceLostError:
        raise SystemExit(
            "DRM EINVAL was incorrectly classified as a lost GPU device"
        )
    except OSError:
        pass
    else:
        raise SystemExit("DRM EINVAL did not remain an API/configuration error")
    finally:
        graphics._drmflip = False
        graphics._drm = FakeDRM()

    class ErrorGLES:

        def __init__(self):
            self.errors = [
                0x0502,
                graphics.GL_NO_ERROR,
            ]

        def glFinish(self):
            return None

        def glGetError(self):
            return self.errors.pop(0)

    class CountingEGL(FakeEGL):

        def __init__(self):
            self.swapcalls = 0

        def eglSwapBuffers(self, display, surface):
            self.swapcalls += 1
            return 1

    countingegl = CountingEGL()
    graphics._egl = countingegl
    graphics._gles = ErrorGLES()
    graphics._gpuhealthlast = 0.0

    try:
        graphics.kmsscanout()
    except RuntimeError as error:
        if "eglSwapBuffers" not in str(error):
            raise SystemExit("sampled OpenGL error was mislabeled")
    else:
        raise SystemExit("sampled OpenGL error did not abort presentation")
    finally:
        graphics._egl = FakeEGL()
        graphics._gles = FakeGLES()

    if countingegl.swapcalls != 1:
        raise SystemExit("presentation did not perform exactly one EGL swap")

    class CountingHealthyGLES(FakeGLES):

        def __init__(self):
            self.errorcalls = 0

        def glGetError(self):
            self.errorcalls += 1
            return graphics.GL_NO_ERROR

    countinggles = CountingHealthyGLES()
    graphics._gles = countinggles
    graphics._gpuhealthlast = 0.0
    graphics.gpuhealthsample(operation="sample one")
    graphics.gpuhealthsample(operation="sample two")

    if countinggles.errorcalls != 1:
        raise SystemExit("GPU health polling still runs on every frame")

    graphics._gles = FakeGLES()

    graphics._drmpendingbo = "next-bo"
    graphics._drmpendingsurface = "gbm-surface"
    graphics._drmpendingfb = 12
    graphics._drmpendingstarted = time.monotonic_ns()
    graphics._drmflip = True
    originalselect = graphics.select.select
    selectcalls = {"count": 0}

    def fakeselect(*args):

        selectcalls["count"] += 1

        if selectcalls["count"] == 1:
            return ([], [], [])

        return ([7], [], [])

    graphics.select.select = fakeselect
    pulses = []

    try:

        if not graphics.kmswaitflip(waitpulse=lambda: pulses.append(True)):
            raise SystemExit("guarded page-flip wait did not complete")

    finally:
        graphics.select.select = originalselect

    if len(pulses) != 2:
        raise SystemExit("guarded page-flip wait did not service the input callback")

    if graphics._gbmbo != "next-bo" or graphics._gbmfb != 12:
        raise SystemExit("guarded page-flip wait did not promote the completed buffer")

    graphics._drmpendingbo = "recovery-bo"
    graphics._drmpendingsurface = "gbm-surface"
    graphics._drmpendingfb = 13
    graphics._drmpendingstarted = time.monotonic_ns()
    graphics._drmflip = True

    if graphics.kmswaitflip(timeout=0.0):
        raise SystemExit("lost page-flip event was incorrectly treated as a completed presentation")

    if graphics._gbmbo == "recovery-bo" or graphics._gbmfb == 13:
        raise SystemExit("timed-out page flip promoted an unconfirmed pending buffer")

    if (
        graphics._drmpendingbo != "recovery-bo"
        or graphics._drmpendingfb != 13
        or not graphics._drmflip
    ):
        raise SystemExit("timed-out page flip did not retain buffer ownership for GPU-owner teardown")

    if graphics._gputelemetry["page_flip_timeouts"] != 1:
        raise SystemExit("page-flip timeout telemetry was not recorded")

    if graphics._gputelemetry["page_flip_recoveries"] != 0:
        raise SystemExit("page-flip timeout still recorded a fabricated modeset recovery")

    blockingwait = graphics._gputelemetry["blocking_page_flip_wait_ms"]
    graphics._drmpendingstarted = time.monotonic_ns() - 2000000000

    if not graphics.kmspresentationstalled():
        raise SystemExit("event-driven page-flip watchdog did not detect a stall")

    if (
        graphics._gputelemetry["page_flip_timeouts"] != 2
        or graphics._gputelemetry["page_flip_timeout_age_ms"] < 1000.0
        or graphics._gputelemetry["blocking_page_flip_wait_ms"] != blockingwait
    ):
        raise SystemExit(
            "event-driven presentation timeout corrupted blocking-wait telemetry"
        )

    graphics._drmpendingbo = None
    graphics._drmpendingsurface = None
    graphics._drmpendingfb = 0
    graphics._drmpendingstarted = 0
    graphics._drmflip = False
    graphics._gputelemetry["page_flip_timeouts"] = 0

    graphics._backend = "framebuffer"
    graphics._xres = 2
    graphics._yres = 2
    graphics._line = 12
    graphics._size = 24
    graphics._bpp = 32
    graphics._bpp_bytes = 4
    graphics._roff, graphics._rlen = 16, 8
    graphics._goff, graphics._glen = 8, 8
    graphics._boff, graphics._blen = 0, 8
    graphics._aoff, graphics._alen = 24, 0
    graphics._packint = struct.Struct("<I").pack
    graphics._fd = 88
    black = graphics.packrgb((0, 0, 0))
    white = graphics.packrgb((255, 255, 255))
    graphics._buffer = bytearray(
        black + black + bytes(4)
        + black + white + bytes(4)
    )
    graphics._map = io.BytesIO(bytes(graphics._buffer))
    originallegacyowners = graphics._legacyframebufferowners
    originalnativevblankproof = graphics._drmdevicevblankproof
    originalfirmwareframebufferboot = graphics.FIRMWAREFRAMEBUFFERBOOT
    originalframebufferconsoleowned = graphics.FRAMEBUFFERCONSOLEOWNED
    originalframebufferwritesequence = graphics._framebufferwritesequence
    originalframebufferpansequence = graphics._framebufferpansequence

    try:
        graphics.FIRMWAREFRAMEBUFFERBOOT = True
        graphics.FRAMEBUFFERCONSOLEOWNED = True
        graphics._framebufferwritesequence = 1
        graphics._framebufferpansequence = 1
        graphics._legacyframebufferowners = lambda: {
            "identity": "EFI VGA",
            "name": "EFI VGA",
            "device": "/devices/platform/efi-framebuffer.0",
            "driver": "efi-framebuffer",
            "native": [],
            "matched": [],
            "owner_connected": False,
            "drm_probe_complete": True,
            "firmware_framebuffer": True,
        }
        graphics._drmdevicevblankproof = lambda device: {
            "device": device,
            "connector": 11,
            "crtc": 9,
            "connector_connected": True,
            "connector_routed": True,
            "connector_link_status": "good",
            "vblank": {
                "supported": True,
                "advanced": True,
                "before": 100,
                "after": 101,
                "timestamp_ns": 1,
                "error": None,
            },
        }
        proof = graphics.framebufferpresentationproof(require_nonblack=True)

        if not (
            proof.get("verified")
            and proof.get("readback")
            and proof.get("scanout")
            and proof.get("nonblack")
            and proof.get("legacy_firmware_framebuffer")
            and proof.get("firmware_framebuffer_boot")
        ):
            raise SystemExit(
                "framebuffer presentation proof rejected visible firmware "
                f"content on an explicit recovery boot {proof}"
            )

        graphics._legacyframebufferowners = lambda: {
            "identity": "EFI VGA",
            "name": "EFI VGA",
            "device": "/devices/platform/efi-framebuffer.0",
            "driver": "efi-framebuffer",
            "native": ["card1:nvidia"],
            "matched": [],
            "owner_connected": False,
            "drm_probe_complete": True,
            "firmware_framebuffer": True,
        }

        if graphics.framebufferpresentationproof(
            require_nonblack=True
        ).get("verified"):
            raise SystemExit(
                "legacy proof accepted a stale EFI aperture after native DRM "
                "took display ownership"
            )

        graphics._legacyframebufferowners = lambda: {
            "identity": "nvidiadrmfb",
            "name": "NVIDIA DRM",
            "device": "/devices/pci0000:00/0000:01:00.0",
            "driver": "nvidia",
            "native": ["card1:nvidia"],
            "matched": [{
                "card": "card1",
                "binding": "nvidia",
                "device_match": True,
                "family_match": True,
                "connector_states": ["connected"],
                "connected": True,
            }],
            "owner_connected": True,
            "drm_probe_complete": True,
            "firmware_framebuffer": False,
        }
        nativeproof = graphics.framebufferpresentationproof(
            require_nonblack=True
        )

        if not (
            nativeproof.get("verified")
            and nativeproof.get("legacy_owner_connected")
            and nativeproof.get("legacy_drm_owner")
            and nativeproof.get("readback") is False
            and nativeproof.get("readback_skipped")
            == "native-drm-fbdev-write-combined-mapping"
            and nativeproof.get("vblank_sequence", {}).get("advanced")
            and not nativeproof.get("legacy_conflicting_drm")
        ):
            raise SystemExit(
                "legacy proof rejected the connected native DRM fbdev owner "
                f"{nativeproof}"
            )

        graphics._legacyframebufferowners = lambda: {
            "identity": "virtiodrmfb",
            "name": "virtio_gpudrmfb",
            "device": "/devices/pci0000:00/virtio0",
            "driver": "virtio-pci",
            "native": ["card0:virtio-pci"],
            "matched": [{
                "card": "card0",
                "binding": "virtio-pci",
                "device_match": True,
                "family_match": True,
                "connector_states": ["connected"],
                "connected": True,
            }],
            "owner_connected": True,
            "drm_probe_complete": True,
            "firmware_framebuffer": False,
        }
        graphics._drmdevicevblankproof = lambda device: {
            "device": device,
            "connector": 11,
            "crtc": 9,
            "connector_connected": True,
            "connector_routed": True,
            "connector_link_status": None,
            "vblank": {
                "supported": False,
                "unsupported": True,
                "advanced": False,
                "before": None,
                "after": None,
                "timestamp_ns": None,
                "error": "drmCrtcGetSequence unsupported errno=95",
            },
        }
        virtionativeproof = graphics.framebufferpresentationproof(
            require_nonblack=True
        )

        if not (
            virtionativeproof.get("verified")
            and virtionativeproof.get("legacy_driver_family") == "virtio"
            and virtionativeproof.get("presentation_boundary")
            == "virtio-fbdev-pan"
            and virtionativeproof.get("vblank_sequence", {}).get(
                "unsupported"
            )
        ):
            raise SystemExit(
                "native virtio fbdev proof rejected its exact FBIOPAN "
                f"resource-flush boundary {virtionativeproof}"
            )

        graphics._legacyframebufferowners = lambda: {
            "identity": "nvidiadrmfb",
            "name": "NVIDIA DRM",
            "device": "/devices/pci0000:00/0000:01:00.0",
            "driver": "nvidia",
            "native": ["card1:nvidia"],
            "matched": [{
                "card": "card1",
                "binding": "nvidia",
                "device_match": True,
                "family_match": True,
                "connector_states": ["disconnected"],
                "connected": False,
            }],
            "owner_connected": False,
            "drm_probe_complete": True,
            "firmware_framebuffer": False,
        }

        class NativeReadTrap(io.BytesIO):

            def read(self, *args, **kwargs):
                raise RuntimeError("native write-combined mapping was read")

        graphics._map = NativeReadTrap(bytes(graphics._buffer))
        disconnectednative = graphics.framebufferpresentationproof(
            require_nonblack=True
        )

        if (
            disconnectednative.get("verified")
            or disconnectednative.get("readback")
        ):
            raise SystemExit(
                "disconnected native fbdev was certified or read back "
                f"{disconnectednative}"
            )

        graphics._legacyframebufferowners = lambda: {
            "identity": "EFI VGA",
            "name": "EFI VGA",
            "device": "/devices/platform/efi-framebuffer.0",
            "driver": "efi-framebuffer",
            "native": [],
            "matched": [],
            "owner_connected": False,
            "drm_probe_complete": True,
            "firmware_framebuffer": True,
        }
        graphics._buffer = bytearray(
            black + black + bytes(4)
            + black + black + bytes(4)
        )
        graphics._map = io.BytesIO(bytes(graphics._buffer))

        if graphics.framebufferpresentationproof(
            require_nonblack=True
        ).get("verified"):
            raise SystemExit(
                "framebuffer presentation proof treated line padding as "
                "visible content"
            )

    finally:
        graphics._legacyframebufferowners = originallegacyowners
        graphics._drmdevicevblankproof = originalnativevblankproof
        graphics.FIRMWAREFRAMEBUFFERBOOT = originalfirmwareframebufferboot
        graphics.FRAMEBUFFERCONSOLEOWNED = originalframebufferconsoleowned
        graphics._framebufferwritesequence = originalframebufferwritesequence
        graphics._framebufferpansequence = originalframebufferpansequence

    originallegacyownerstate = (
        graphics.FRAMEBUFFERSTATEPATH,
        graphics.DRMSTATEPATH,
        graphics.drmcandidates,
        graphics._graphicsdrmbinding,
        graphics._graphicsdrmroots,
    )

    try:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            framebufferstate = root / "graphics/fb0"
            framebufferdevice = framebufferstate / "device"
            drmstate = root / "drm"
            otherdevice = root / "devices/second-nvidia"
            framebufferdevice.mkdir(parents=True)
            otherdevice.mkdir(parents=True)
            drmstate.mkdir(parents=True)
            (framebufferstate / "name").write_text(
                "NVIDIA DRM\n",
                encoding="ascii",
            )
            firstconnector = drmstate / "card0-HDMI-A-1"
            secondconnector = drmstate / "card1-HDMI-A-1"
            firstconnector.mkdir()
            secondconnector.mkdir()
            (firstconnector / "status").write_text(
                "disconnected\n",
                encoding="ascii",
            )
            (secondconnector / "status").write_text(
                "connected\n",
                encoding="ascii",
            )
            cards = ["/virtual/card0", "/virtual/card1"]
            graphics.FRAMEBUFFERSTATEPATH = str(framebufferstate)
            graphics.DRMSTATEPATH = str(drmstate)
            graphics.drmcandidates = lambda: list(cards)
            graphics._graphicsdrmbinding = lambda candidate: "nvidia"
            graphics._graphicsdrmroots = lambda candidate: [
                str(
                    framebufferdevice
                    if candidate.endswith("card0")
                    else otherdevice
                )
            ]
            owners = graphics._legacyframebufferowners()

            if (
                [owner.get("card") for owner in owners.get("matched", [])]
                != ["card0"]
                or owners.get("owner_connected")
            ):
                raise SystemExit(
                    "fbdev ownership was incorrectly certified by the "
                    f"connected same-vendor sibling GPU {owners}"
                )

            (firstconnector / "status").write_text(
                "connected\n",
                encoding="ascii",
            )
            owners = graphics._legacyframebufferowners()

            if not owners.get("owner_connected"):
                raise SystemExit(
                    "fbdev ownership correlation rejected its own connected "
                    f"native DRM card {owners}"
                )

    finally:
        (
            graphics.FRAMEBUFFERSTATEPATH,
            graphics.DRMSTATEPATH,
            graphics.drmcandidates,
            graphics._graphicsdrmbinding,
            graphics._graphicsdrmroots,
        ) = originallegacyownerstate

    class PanIO:

        def __init__(self, initial=(0, 0), verified=(0, 0), panerror=None):
            self.initial = initial
            self.verified = verified
            self.panerror = panerror
            self.gets = 0
            self.pans = []

        def __call__(self, fd, request, value, mutate=False):

            if request == graphics.FBIOGET_VSCREENINFO:
                offsets = self.initial if self.gets == 0 else self.verified
                self.gets += 1
                struct.pack_into("<I", value, 16, int(offsets[0]))
                struct.pack_into("<I", value, 20, int(offsets[1]))
                return 0

            if request == graphics.FBIOPAN_DISPLAY:

                if self.panerror is not None:
                    raise self.panerror

                self.pans.append((
                    struct.unpack_from("<I", value, 16)[0],
                    struct.unpack_from("<I", value, 20)[0],
                    struct.unpack_from("<I", value, 84)[0],
                ))
                return 0

            return 0

    originalpanstate = (
        graphics.fcntl.ioctl,
        graphics._fd,
        graphics._framebuffernativedrm,
        graphics._framebufferwritesequence,
        graphics._framebufferpansequence,
        graphics._framebufferpagezero,
        graphics._backend,
        graphics._map,
        graphics._buffer,
        graphics.framebufferactivatepagezero,
    )

    try:
        graphics._fd = 99
        graphics._framebuffernativedrm = True
        graphics._framebufferwritesequence = 7
        graphics._framebufferpansequence = 0
        zerooffsetpan = PanIO()
        graphics.fcntl.ioctl = zerooffsetpan

        if (
            not graphics.framebufferactivatepagezero()
            or zerooffsetpan.pans != [(0, 0, graphics.FB_ACTIVATE_NOW)]
            or graphics._framebufferpansequence != 7
        ):
            raise SystemExit(
                "native fbdev did not force and bind a page-zero pan commit "
                "when offsets were already zero"
            )

        nonzerooffsetpan = PanIO(initial=(19, 2160))
        graphics.fcntl.ioctl = nonzerooffsetpan

        if (
            not graphics.framebufferactivatepagezero()
            or nonzerooffsetpan.pans != [(0, 0, graphics.FB_ACTIVATE_NOW)]
        ):
            raise SystemExit(
                "native fbdev pan did not clear both xoffset and yoffset"
            )

        graphics.fcntl.ioctl = PanIO(
            panerror=OSError(errno.EIO, "synthetic pan failure")
        )

        if graphics.framebufferactivatepagezero():
            raise SystemExit("failed native FBIOPAN_DISPLAY was certified")

        staleverify = PanIO(verified=(1, 0))
        graphics.fcntl.ioctl = staleverify

        if graphics.framebufferactivatepagezero():
            raise SystemExit(
                "native fbdev pan was certified after nonzero verified offsets"
            )

        class FlushTrapMap:

            def __init__(self):
                self.flushes = 0

            def seek(self, offset):
                return offset

            def write(self, payload):
                return len(payload)

            def flush(self):
                self.flushes += 1
                raise RuntimeError("write-combined mmap flush attempted")

        graphics._backend = "framebuffer"
        graphics._buffer = bytearray(b"\x01\x02\x03\x04")
        graphics.framebufferactivatepagezero = lambda: True
        nativemap = FlushTrapMap()
        graphics._map = nativemap
        graphics._framebuffernativedrm = True

        if not graphics.present() or nativemap.flushes:
            raise SystemExit(
                "native DRM fbdev presentation touched its write-combined "
                "mapping through mmap.flush"
            )

        firmwaremap = FlushTrapMap()
        graphics._map = firmwaremap
        graphics._framebuffernativedrm = False

        if graphics.present() or firmwaremap.flushes != 1:
            raise SystemExit(
                "system-memory framebuffer presentation no longer requires "
                "its flush boundary"
            )

    finally:
        (
            graphics.fcntl.ioctl,
            graphics._fd,
            graphics._framebuffernativedrm,
            graphics._framebufferwritesequence,
            graphics._framebufferpansequence,
            graphics._framebufferpagezero,
            graphics._backend,
            graphics._map,
            graphics._buffer,
            graphics.framebufferactivatepagezero,
        ) = originalpanstate

    proofmode = graphics.drmModeModeInfo()
    proofmode.clock = 25175
    proofmode.hdisplay = 640
    proofmode.hsync_start = 656
    proofmode.hsync_end = 752
    proofmode.htotal = 800
    proofmode.vdisplay = 480
    proofmode.vsync_start = 490
    proofmode.vsync_end = 492
    proofmode.vtotal = 525
    proofmode.vrefresh = 60
    proofmode.name = b"640x480"

    class FakeProofDRM:

        def __init__(self):
            self.crtc = graphics.drmModeCrtc()
            self.crtc.crtc_id = 9
            self.crtc.buffer_id = 73
            self.crtc.mode_valid = 1
            self.crtc.mode = proofmode
            self.connector = graphics.drmModeConnector()
            self.connector.connector_id = 11
            self.connector.connection = graphics.DRM_MODE_CONNECTED
            self.connector.encoder_id = 5
            self.encoder = graphics.drmModeEncoder()
            self.encoder.encoder_id = 5
            self.encoder.crtc_id = 9
            self.sequence = 100

        def drmModeGetConnector(self, fd, connector):
            return ctypes.pointer(self.connector)

        def drmModeFreeConnector(self, pointer):
            return None

        def drmModeGetEncoder(self, fd, encoder):
            return ctypes.pointer(self.encoder)

        def drmModeFreeEncoder(self, pointer):
            return None

        def drmModeGetCrtc(self, fd, crtc):
            return ctypes.pointer(self.crtc)

        def drmModeFreeCrtc(self, pointer):
            return None

        def drmCrtcGetSequence(
            self,
            fd,
            crtc,
            sequence,
            timestamp,
        ):
            self.sequence += 1
            sequence._obj.value = self.sequence
            timestamp._obj.value = self.sequence * 1000
            return 0

    graphics._backend = "kms-framebuffer"
    proofdrm = FakeProofDRM()
    graphics._drm = proofdrm
    graphics._drmfd = 91
    graphics._drmconnector = 11
    graphics._drmcrtc = 9
    graphics._drmmode = proofmode
    graphics._drmdumbfb = 73
    graphics._drmdumbpresentsequence = 1
    graphics._drmdumbmodesetsequence = 1
    graphics._drmdumblastpresenterror = None
    graphics._buffer = bytearray(
        black + black + bytes(4)
        + black + white + bytes(4)
    )
    graphics._map = io.BytesIO(bytes(len(graphics._buffer)))
    proof = graphics.framebufferpresentationproof(require_nonblack=True)

    if not (
        proof.get("verified")
        and proof.get("scanout")
        and proof.get("connector_connected")
        and proof.get("connector_routed")
        and proof.get("write_committed")
        and proof.get("nonblack")
        and not proof.get("readback")
        and proof.get("framebuffer") == 73
        and proof.get("expected_framebuffer") == 73
        and proof.get("mode_matches")
        and proof.get("vblank_sequence", {}).get("advanced")
        and proof.get("presentation_boundary") == "drm-crtc-sequence"
    ):
        raise SystemExit(
            "software KMS presentation proof confused advisory WC readback "
            f"with authoritative written-frame CRTC commit {proof}"
        )

    class FakeUnsupportedVblankDRM(FakeProofDRM):

        def drmCrtcGetSequence(
            self,
            fd,
            crtc,
            sequence,
            timestamp,
        ):
            ctypes.set_errno(getattr(errno, "EOPNOTSUPP", errno.ENOTSUP))
            return -getattr(errno, "EOPNOTSUPP", errno.ENOTSUP)

    unsupporteddrm = FakeUnsupportedVblankDRM()
    graphics._drm = unsupporteddrm
    graphics._drmdriver = "virtio_gpu"
    graphics._drmdumbpresentsequence = 2
    graphics._drmdumbdirtystatus = "complete"
    virtioproof = graphics.framebufferpresentationproof(
        require_nonblack=True
    )

    if not (
        virtioproof.get("verified")
        and virtioproof.get("vblank_sequence", {}).get("unsupported")
        and not virtioproof.get("vblank_sequence", {}).get("advanced")
        and virtioproof.get("presentation_boundary")
        == "virtio-resource-flush"
        and virtioproof.get("dirty_status") == "complete"
        and virtioproof.get("present_sequence") == 2
    ):
        raise SystemExit(
            "virtio CPU-KMS proof rejected its explicit host resource-flush "
            f"boundary {virtioproof}"
        )

    graphics._drmdriver = "nvidia-drm"
    graphics._drmdumbdirtystatus = f"unsupported:{errno.ENOSYS}"
    graphics._drmdumbflushstatus = "not-required:drm-ioctl-boundary"
    physicalunsupported = graphics.framebufferpresentationproof(
        require_nonblack=True
    )

    if not (
        physicalunsupported.get("verified")
        and physicalunsupported.get("presentation_boundary")
        == "nvidia-continuous-scanout"
        and physicalunsupported.get("vblank_sequence", {}).get("unsupported")
        and physicalunsupported.get("vblank_sequence", {}).get("errno")
        == getattr(errno, "EOPNOTSUPP", errno.ENOTSUP)
        and physicalunsupported.get("dirty_status")
        == f"unsupported:{errno.ENOSYS}"
        and physicalunsupported.get("present_sequence") == 2
        and physicalunsupported.get("modeset_sequence") == 1
    ):
        raise SystemExit(
            "NVIDIA CPU-KMS proof rejected its exact continuous-scanout "
            f"fallback {physicalunsupported}"
        )

    graphics._drmdumbdirtystatus = "complete"
    weaknvidiaproof = graphics.framebufferpresentationproof(
        require_nonblack=True
    )

    if (
        weaknvidiaproof.get("verified")
        or weaknvidiaproof.get("presentation_boundary") is not None
    ):
        raise SystemExit(
            "NVIDIA CPU-KMS proof accepted a receipt without the exact "
            f"unsupported DIRTYFB evidence {weaknvidiaproof}"
        )

    graphics._drm = proofdrm
    graphics._drmdriver = "virtio_gpu"
    graphics._drmdumbpresentsequence = 1
    graphics._drmdumbdirtystatus = ""
    try:
        json.dumps(proof)
    except TypeError as error:
        raise SystemExit(
            f"software KMS presentation receipt is not JSON serializable: {error}"
        )

    proofdrm.crtc.mode.hdisplay = 800
    mismatchedmodeproof = graphics.framebufferpresentationproof(
        require_nonblack=True
    )

    if (
        mismatchedmodeproof.get("verified")
        or mismatchedmodeproof.get("scanout")
        or mismatchedmodeproof.get("mode_matches")
    ):
        raise SystemExit(
            "software KMS presentation proof accepted the expected framebuffer "
            "on a different active CRTC timing"
        )

    graphics._backend = "opengl"

    class FakeHealthyGLES:

        def glFinish(self):
            return None

        def glGetError(self):
            return graphics.GL_NO_ERROR

    graphics._gles = FakeHealthyGLES()
    graphics._eglcontext = "context"

    if not graphics.gpuhealthcheck(
        synchronize=True,
        operation="test GPU health gate",
    ):
        raise SystemExit("healthy GPU context did not pass its health gate")

    class FakeLostGLES:

        def __init__(self):
            self.errors = [graphics.GL_CONTEXT_LOST, graphics.GL_NO_ERROR]

        def glFinish(self):
            return None

        def glGetError(self):
            return self.errors.pop(0)

    graphics._gles = FakeLostGLES()

    try:
        graphics.gpuhealthcheck(
            synchronize=True,
            operation="test GPU health gate",
        )
    except RuntimeError as error:
        if "lost GPU context" not in str(error):
            raise SystemExit("lost GPU context produced the wrong health-gate error")
    else:
        raise SystemExit("lost GPU context passed its health gate")

    graphics._gles = FakeHealthyGLES()
    graphics._glgetgraphicsresetstatus = (
        lambda: graphics.GL_GUILTY_CONTEXT_RESET
    )

    try:
        graphics.gpuhealthcheck(
            synchronize=True,
            operation="test robust reset gate",
        )
    except graphics.GPUDeviceLostError as error:
        if "guilty GPU context reset" not in str(error):
            raise SystemExit("robust GPU reset produced the wrong health-gate error")
    else:
        raise SystemExit("robust GPU reset passed its health gate")
    finally:
        graphics._glgetgraphicsresetstatus = None

    originalpresentbackend = graphics._backend
    originalkmspresent = graphics.kmspresent

    try:
        graphics._backend = "opengl"
        graphics.kmspresent = lambda: (_ for _ in ()).throw(
            graphics.GPUDeviceLostError("synthetic present device loss")
        )

        try:
            graphics.present()
        except graphics.GPUDeviceLostError:
            pass
        else:
            raise SystemExit(
                "graphics.present swallowed an authoritative GPU device loss"
            )
    finally:
        graphics._backend = originalpresentbackend
        graphics.kmspresent = originalkmspresent

    class PresentMap:

        def seek(self, position):
            return None

        def write(self, data):
            return len(data)

    originalkmspresentstate = (
        graphics._backend,
        graphics._map,
        graphics._buffer,
        graphics._size,
        graphics._kmsframebuffercommitwrittenframe,
    )

    try:
        graphics._backend = "kms-framebuffer"
        graphics._map = PresentMap()
        graphics._buffer = bytearray(b"\x01\x02\x03\x04")
        graphics._size = len(graphics._buffer)

        for operation in (
            lambda: graphics.present(),
            lambda: graphics.presentdirty(0, 0, 1, 1),
        ):
            sentinel = graphics.GPUDeviceLostError(
                "synthetic software KMS commit loss"
            )
            graphics._kmsframebuffercommitwrittenframe = (
                lambda chosen=sentinel: (_ for _ in ()).throw(chosen)
            )

            try:
                operation()
            except graphics.GPUDeviceLostError as error:
                if error is not sentinel:
                    raise SystemExit(
                        "software KMS presentation replaced the device-loss exception"
                    )
            else:
                raise SystemExit(
                    "software KMS presentation swallowed GPU device loss"
                )
    finally:
        (
            graphics._backend,
            graphics._map,
            graphics._buffer,
            graphics._size,
            graphics._kmsframebuffercommitwrittenframe,
        ) = originalkmspresentstate

    class FakeConfigEGL:

        def __init__(self, visuals=None):
            self.queries = []
            self.visuals = visuals or {
                101: 0,
                102: graphics.GBM_FORMAT_XRGB8888,
                103: graphics.GBM_FORMAT_XRGB8888,
            }

        def eglGetConfigAttrib(self, display, config, attribute, output):
            config = int(config)
            self.queries.append(config)
            output._obj.value = self.visuals[config]
            return 1

    originalconfigegl = graphics._egl
    originalconfigdisplay = graphics._egldisplay
    configegl = FakeConfigEGL()

    try:
        graphics._egl = configegl
        graphics._egldisplay = 1
        selected, selectedindex, selectedvisual = (
            graphics._eglchoosexrgbconfig([101, 102, 103], 3)
        )

        if (
            selected != 102
            or selectedindex != 1
            or selectedvisual != graphics.GBM_FORMAT_XRGB8888
        ):
            raise SystemExit("EGL did not select the first native XRGB configuration")

        if configegl.queries != [101, 102]:
            raise SystemExit(
                "EGL continued querying vendor configurations after first XRGB"
            )

        firstegl = FakeConfigEGL({
            101: graphics.GBM_FORMAT_XRGB8888,
            102: graphics.GBM_FORMAT_XRGB8888,
        })
        graphics._egl = firstegl
        selected, selectedindex, selectedvisual = (
            graphics._eglchoosexrgbconfig([101, 102], 2)
        )

        if (
            (selected, selectedindex, selectedvisual)
            != (101, 0, graphics.GBM_FORMAT_XRGB8888)
            or firstegl.queries != [101]
        ):
            raise SystemExit("EGL did not stop at a first-config XRGB match")

        defaultegl = FakeConfigEGL({101: 0, 102: 0})
        graphics._egl = defaultegl
        selected, selectedindex, selectedvisual = (
            graphics._eglchoosexrgbconfig([101, 102], 2)
        )

        if (
            (selected, selectedindex, selectedvisual) != (101, 0, None)
            or defaultegl.queries != [101, 102]
        ):
            raise SystemExit(
                "EGL provider-default policy is undefined when no native "
                "visual is advertised"
            )

        try:
            graphics._eglchoosexrgbconfig([], 0)
        except RuntimeError:
            pass
        else:
            raise SystemExit("EGL accepted an empty GBM configuration set")
    finally:
        graphics._egl = originalconfigegl
        graphics._egldisplay = originalconfigdisplay

    class FakeIntervalEGL:

        def __init__(self):
            self.swapcalls = []

        def eglGetConfigAttrib(self, display, config, attribute, output):
            values = {
                graphics.EGL_MIN_SWAP_INTERVAL: 0,
                graphics.EGL_MAX_SWAP_INTERVAL: 1,
            }
            output._obj.value = values[int(attribute)]
            return 1

        def eglSwapInterval(self, display, interval):
            self.swapcalls.append(int(interval))
            return 1

        def eglGetError(self):
            return graphics.EGL_SUCCESS

    originalintervalstate = (
        graphics._egl,
        graphics._egldisplay,
        graphics._eglconfig,
        graphics._openglprovider,
        graphics._eglswapinterval,
        graphics._eglminswapinterval,
        graphics._eglmaxswapinterval,
        graphics._egldeferredswapstate,
        graphics._egldeferredswaperror,
    )
    intervalegl = FakeIntervalEGL()

    try:
        graphics._egl = intervalegl
        graphics._egldisplay = 1
        graphics._eglconfig = 2
        graphics._openglprovider = "nvidia"

        if graphics._eglconfigurekmspresentation() != 1:
            raise SystemExit("NVIDIA EGL default presentation interval was not retained")

        if intervalegl.swapcalls:
            raise SystemExit(
                "NVIDIA EGL cold initialization still calls eglSwapInterval"
            )

        if (
            not graphics._eglapplydeferredkmspresentation()
            or intervalegl.swapcalls != [0]
            or graphics._eglswapinterval != 0
            or graphics._egldeferredswapstate
            != "applied-after-first-page-flip"
        ):
            raise SystemExit(
                "NVIDIA EGL interval was not disabled after a healthy "
                "DRM page flip"
            )

        graphics._openglprovider = "mesa"

        if graphics._eglconfigurekmspresentation() != 0:
            raise SystemExit("Mesa EGL did not retain the zero-interval page-flip policy")

        if intervalegl.swapcalls != [0, 0]:
            raise SystemExit("Mesa EGL presentation interval was not configured once")

    finally:
        (
            graphics._egl,
            graphics._egldisplay,
            graphics._eglconfig,
            graphics._openglprovider,
            graphics._eglswapinterval,
            graphics._eglminswapinterval,
            graphics._eglmaxswapinterval,
            graphics._egldeferredswapstate,
            graphics._egldeferredswaperror,
        ) = originalintervalstate

    class FakeDumbDRM:

        def __init__(self):
            self.added = []
            self.sets = []
            self.removed = []

        def drmModeGetCrtc(self, fd, crtc):
            return None

        def drmModeFreeCrtc(self, pointer):
            return None

        def drmModeAddFB(
            self,
            fd,
            width,
            height,
            depth,
            bits,
            pitch,
            handle,
            framebuffer,
        ):
            framebuffer._obj.value = 73
            self.added.append(
                (fd, width, height, depth, bits, pitch, handle)
            )
            return 0

        def drmModeSetCrtc(self, *args):
            self.sets.append(args)
            return 0

        def drmModeRmFB(self, fd, framebuffer):
            self.removed.append((fd, int(framebuffer)))
            return 0

    class FakeDumbMap:

        def __init__(self, size):
            self.data = bytearray(size)
            self.position = 0
            self.closed = False
            self.flushcalls = 0

        def seek(self, position):
            self.position = int(position)

        def write(self, data):
            end = self.position + len(data)
            self.data[self.position:end] = data
            self.position = end
            return len(data)

        def read(self, length):
            end = min(len(self.data), self.position + int(length))
            result = bytes(self.data[self.position:end])
            self.position = end
            return result

        def flush(self):
            self.flushcalls += 1
            raise OSError(22, "Invalid argument")

        def close(self):
            self.closed = True

    dumbdrm = FakeDumbDRM()
    dumbmode = graphics.drmModeModeInfo()
    dumbmode.hdisplay = 640
    dumbmode.vdisplay = 480
    dumbioctls = []
    dumbclosed = []
    dumbmap = FakeDumbMap(640 * 4 * 480)
    originaldrmload = graphics.drmload
    originalopenglload = graphics.openglload
    originalkmsdriverinfo = graphics.kmsdriverinfo
    originalkmsfindmode = graphics.kmsfindmode
    originalkmsvalidmode = graphics.kmsvalidmode
    originalopen = graphics.os.open
    originalclose = graphics.os.close
    originalioctl = graphics.fcntl.ioctl
    originalmmap = graphics.mmap.mmap
    originalmapshared = getattr(graphics.mmap, "MAP_SHARED", None)
    originalprotread = getattr(graphics.mmap, "PROT_READ", None)
    originalprotwrite = getattr(graphics.mmap, "PROT_WRITE", None)
    originalgraphlog = graphics.log
    dumblogs = []
    graphics._backend = "none"
    # The preceding legacy-framebuffer proof deliberately installs a fake
    # generic framebuffer descriptor. Keep this KMS resource test isolated so
    # close() is judged only on the resources created below.
    graphics._fd = None
    graphics._drmfd = None
    graphics._drm = dumbdrm
    graphics._map = None
    graphics._buffer = None
    graphics.drmload = lambda: True
    graphics.openglload = lambda: (_ for _ in ()).throw(
        RuntimeError("software KMS must not load EGL")
    )
    graphics.kmsdriverinfo = lambda: {
        "name": "nouveau",
        "version": "test",
        "date": "",
        "description": "",
    }
    graphics.kmsfindmode = lambda *args, **kwargs: (11, 12, dumbmode)
    graphics.kmsvalidmode = lambda mode: True
    graphics.os.open = lambda *args, **kwargs: 91
    graphics.os.close = lambda fd: dumbclosed.append(fd)

    def dumbioctl(fd, request, buffer, mutate=True):

        dumbioctls.append(request)

        if request == graphics.DRM_IOCTL_MODE_CREATE_DUMB:
            height, width, bits, flags = struct.unpack_from("<IIII", buffer, 0)

            if (width, height, bits, flags) != (640, 480, 32, 0):
                raise RuntimeError("software KMS sent an invalid dumb-buffer request")

            struct.pack_into("<I", buffer, 16, 51)
            struct.pack_into("<I", buffer, 20, 640 * 4)
            struct.pack_into("<Q", buffer, 24, 640 * 4 * 480)

        elif request == graphics.DRM_IOCTL_MODE_MAP_DUMB:
            struct.pack_into("<Q", buffer, 8, 4096)

        return 0

    graphics.fcntl.ioctl = dumbioctl
    graphics.mmap.MAP_SHARED = 1
    graphics.mmap.PROT_READ = 1
    graphics.mmap.PROT_WRITE = 2
    graphics.mmap.mmap = lambda *args, **kwargs: dumbmap
    graphics.log = lambda message, *args, **kwargs: dumblogs.append(str(message))

    try:

        if not graphics._kmsframebufferinitdevice("/dev/dri/card-test"):
            raise SystemExit(
                "software KMS dumb-buffer initialization failed: "
                + " | ".join(dumblogs)
            )

        if graphics._backend != "kms-framebuffer":
            raise SystemExit("software KMS did not expose its scanout backend")

        if dumbdrm.sets:
            raise SystemExit(
                "software KMS replaced scanout with an unwritten black buffer "
                "during initialization"
            )

        graphics._buffer[0:4] = b"\x01\x02\x03\x04"
        if not graphics.present():
            raise SystemExit("software KMS rejected its first written frame")

        if dumbmap.data[0:4] != b"\x01\x02\x03\x04":
            raise SystemExit("software KMS did not present its CPU-rendered buffer")

        if not dumbdrm.sets or dumbdrm.sets[-1][2] != 73:
            raise SystemExit(
                "software KMS did not latch the populated framebuffer after "
                "the first complete CPU write"
            )

        if dumbmap.flushcalls != 0:
            raise SystemExit(
                "software KMS called blocking msync on write-combined video "
                "memory before its first modeset"
            )

        if graphics._drmdumbflushstatus != "not-required:drm-ioctl-boundary":
            raise SystemExit(
                "software KMS did not record the DRM ioctl commit boundary"
            )

        graphics.close()

        if graphics.DRM_IOCTL_MODE_DESTROY_DUMB not in dumbioctls:
            raise SystemExit("software KMS did not destroy its dumb buffer")

        if dumbdrm.removed != [(91, 73)] or dumbclosed != [91]:
            raise SystemExit("software KMS scanout resources were not released")

    finally:
        graphics.drmload = originaldrmload
        graphics.openglload = originalopenglload
        graphics.kmsdriverinfo = originalkmsdriverinfo
        graphics.kmsfindmode = originalkmsfindmode
        graphics.kmsvalidmode = originalkmsvalidmode
        graphics.os.open = originalopen
        graphics.os.close = originalclose
        graphics.fcntl.ioctl = originalioctl
        graphics.mmap.mmap = originalmmap

        for name, value in (
            ("MAP_SHARED", originalmapshared),
            ("PROT_READ", originalprotread),
            ("PROT_WRITE", originalprotwrite),
        ):

            if value is None:
                delattr(graphics.mmap, name)
            else:
                setattr(graphics.mmap, name, value)

        graphics.log = originalgraphlog

    windowserver = (
        projectroot / "source/build software/windows/windowserver.py"
    ).read_text(encoding="utf-8")
    validatevideoauthorizationlogging(windowserver)

    for required in (
        'peeruid = int(identity.get("uid", -1))',
        'peergid = int(identity.get("gid", -1))',
        'servergid = int(os.getegid())',
        'os.fchown(descriptor, peeruid, servergid)',
        'os.fchmod(descriptor, 0o660)',
        'def windowbuffercontentproof(',
        'def acceleratedcontentproof(',
        'raise PermissionError("unsafe window-buffer ownership or mode")',
        'graphics CREATE_WINDOW denied',
        'graphics CREATE_WINDOW failed',
    ):

        if required not in windowserver:
            raise SystemExit(
                f"WindowServer peer-owned buffer contract is missing {required!r}"
            )

    chmodposition = windowserver.index('os.fchmod(descriptor, 0o660)')
    chownposition = windowserver.index('os.fchown(descriptor, peeruid, servergid)')

    if chmodposition >= chownposition:
        raise SystemExit(
            "WindowServer transfers window-buffer ownership before applying its mode"
        )
    graphicssource = (
        projectroot / "source/build software/graphics/graphics.py"
    ).read_text(encoding="utf-8")
    bricksource = (
        projectroot / "source/build software/brick/brick.py"
    ).read_text(encoding="utf-8")
    expansesource = (
        projectroot / "source/build software/expanse/expanse.py"
    ).read_text(encoding="utf-8")
    lockscreen = (
        projectroot / "source/build software/lock screen/lock screen.py"
    ).read_text(encoding="utf-8")

    if "T1OS_LOCKSCREEN_GRAPHICS', 'managed'" not in lockscreen:
        raise SystemExit("lock screen does not default to managed GPU rendering")

    for required in (
        "initlock managed GPU path active; CPU window buffer is not mapped",
        "def graphicsgpurequired(",
        "if graphicsgpurequired():",
        "graphicswaitinitial(timeout=2.0)",
        "managed GPU presentation did not complete after map",
    ):

        if required not in lockscreen:
            raise SystemExit(f"lock screen GPU-only rendering contract is missing {required!r}")

    mapposition = lockscreen.index("ok = wsmap(_winid)")
    waitposition = lockscreen.index("graphicswaitinitial(timeout=2.0)")

    if waitposition <= mapposition:
        raise SystemExit("lock screen waits for GPU presentation before mapping its window")

    for required in (
        "if op == 'ERROR':",
        "f'wscreate server error code={code} detail={detail}'",
    ):

        if required not in lockscreen:
            raise SystemExit(
                f"lock-screen CREATE_WINDOW diagnostic is missing {required!r}"
            )
    goddess = (
        projectroot / "source/build software/GODDESS/GODDESS.py"
    ).read_text(encoding="utf-8")

    for required in (
        "class LoginClientBufferFailure(RuntimeError):",
        "if 'WindowBufferAccessError:' in detail:",
        "except LoginClientBufferFailure as error:",
        "'lockscreen-userspace-buffer-failure'",
    ):

        if required not in goddess:
            raise SystemExit(
                f"PID 1 window-buffer failure classification is missing {required!r}"
            )
    driverserver = (
        projectroot / "source/build software/drivers/driverserver.py"
    ).read_text(encoding="utf-8")
    validatedriverserverzombiedetection(driverserver)
    startup = (
        projectroot / "source/build software/startup/startup.py"
    ).read_text(encoding="utf-8")
    validateacceleratedcontentproof(windowserver)
    validateacceleratedlockscreenreceipt(lockscreen, "lock screen")
    validateacceleratedlockscreenreceipt(startup, "startup")
    validatenvidialockscreenreceipt(lockscreen, "lock screen")
    validatenvidialockscreenreceipt(startup, "startup")
    graphicsbuild = (
        projectroot / "scripts/build/build graphics runtime.ps1"
    ).read_text(encoding="utf-8")

    refreshsaved = {
        name: getattr(graphics, name)
        for name in (
            "_backend",
            "_drmdriver",
            "virtualboxcontrolsresolution",
            "kmsresize",
        )
    }
    refreshcalls = []

    try:
        graphics._backend = "opengl"
        graphics._drmdriver = "nvidia"
        graphics.virtualboxcontrolsresolution = lambda: False
        graphics.kmsresize = (
            lambda waitpulse=None:
            refreshcalls.append(waitpulse) or True
        )

        if graphics.refreshfb() or refreshcalls:
            raise SystemExit(
                "steady physical connector polling still enters KMS mode discovery"
            )

        pulse = object()

        if (
            not graphics.refreshfb(
                waitpulse=pulse,
                force_physical=True,
            )
            or refreshcalls != [pulse]
        ):
            raise SystemExit(
                "the forced startup physical connector check was removed"
            )

        refreshcalls.clear()
        graphics._drmdriver = "virtio_gpu"

        if not graphics.refreshfb() or len(refreshcalls) != 1:
            raise SystemExit(
                "dynamic virtual display polling was disabled"
            )
    finally:
        for name, value in refreshsaved.items():
            setattr(graphics, name, value)

    receiptmessages = []
    receiptwindows = {
        5: {
            "id": 5,
            "cid": 1,
            "mapped": True,
            "_gpu_command_generation": 3,
            "_gpu_presented_generation": 0,
            "_gpu_commit_receipts": [],
        }
    }
    receiptnamespace = {
        "GPUCOMPOSITOR": True,
        "GRAPHICSPRESENTFD": 7,
        "GPUCOMMANDDAMAGELIMIT": 64,
        "GPUFRAMESEQUENCE": 77,
        "GPUPENDINGCOMMITRECEIPTS": [],
        "GPUCAPTUREDCOMMITRECEIPTS": [],
        "GPUDEFERREDCOMMITRECEIPTS": [],
        "windows": receiptwindows,
        "clients": {1: {}},
        "sendjson": (
            lambda cid, message:
            receiptmessages.append((cid, dict(message)))
        ),
        "kmshandlepresentationevent": lambda: True,
        "kmspresentationpending": lambda: False,
        "finishchromiumpresentations": lambda: 0,
        "iopulse": lambda: None,
    }
    loadsourcefunctions(
        windowserver,
        (
            "graphicspresentationresponse",
            "graphicsframecommitreceipts",
            "graphicsrestorecommitreceipts",
            "graphicscommitreceiptvalue",
            "graphicscommitreceiptoutstanding",
            "graphicsdelivercommitreceipt",
            "graphicsfinishdeferredcommitreceipts",
            "graphicsdefercommitreceipt",
            "graphicsstagecommitreceipts",
            "graphicsfinishcommitreceipts",
            "graphicscancelcommitreceipts",
            "graphicsdrmpresentationevent",
            "graphicspresentationpulse",
        ),
        receiptnamespace,
    )
    presentationresponse = receiptnamespace[
        "graphicspresentationresponse"
    ]
    presentationresponse(
        1,
        receiptwindows[5],
        {
            "op": "GRAPHICS_COMMITTED",
            "winid": 5,
            "generation": 3,
            "accelerated": True,
        },
    )
    receiptwindows[5]["_gpu_command_generation"] = 4
    presentationresponse(
        1,
        receiptwindows[5],
        {
            "op": "GRAPHICS_CLEARED",
            "winid": 5,
            "generation": 4,
        },
    )

    if receiptmessages:
        raise SystemExit(
            "managed scene acknowledgement escaped before presentation"
        )

    receipts = receiptnamespace[
        "graphicsframecommitreceipts"
    ]({5: 4})

    if (
        len(receipts) != 2
        or receipts[0].get("presented") is not False
        or receipts[0].get("superseded") is not True
        or receipts[1].get("presented") is not True
        or receiptwindows[5]["_gpu_commit_receipts"]
    ):
        raise SystemExit(
            "the submitted frame did not distinguish its drawn generation "
            "from a superseded managed generation"
        )

    # A request accepted while gpuend() waits belongs to the next frame. The
    # already captured receipts must no longer be present in the window queue.
    receiptwindows[5]["_gpu_command_generation"] = 5
    presentationresponse(
        1,
        receiptwindows[5],
        {
            "op": "GRAPHICS_COMMITTED",
            "winid": 5,
            "generation": 5,
            "accelerated": True,
        },
    )

    if [
        value.get("generation")
        for value in receiptwindows[5]["_gpu_commit_receipts"]
    ] != [5]:
        raise SystemExit(
            "a request arriving during scan-out was attached to the "
            "already-rendered frame"
        )

    receiptnamespace["graphicsstagecommitreceipts"](receipts)

    if (
        len(receiptwindows[5]["_gpu_commit_receipts"]) != 1
        or len(receiptnamespace["GPUPENDINGCOMMITRECEIPTS"]) != 2
    ):
        raise SystemExit(
            "managed responses were not transferred to the submitted frame"
        )

    if not receiptnamespace["graphicsdrmpresentationevent"]():
        raise SystemExit("synthetic DRM presentation did not complete")

    if (
        [message["op"] for _, message in receiptmessages]
        != ["GRAPHICS_COMMITTED", "GRAPHICS_CLEARED"]
        or receiptmessages[0][1].get("presented") is not False
        or receiptmessages[0][1].get("superseded") is not True
        or receiptmessages[1][1].get("presented") is not True
        or any(
            message.get("frame_sequence") != 77
            for _, message in receiptmessages
        )
        or receiptwindows[5]["_gpu_presented_generation"] != 4
        or receiptnamespace["GPUPENDINGCOMMITRECEIPTS"]
    ):
        raise SystemExit(
            "managed responses did not preserve superseded/presented status "
            "through the completed page flip"
        )

    # Raw kmswaitflip() consumes the DRM event before its wait callback runs.
    # The callback must still release the receipt even though the selector no
    # longer reports the graphics fd.
    nextframe = receiptnamespace["graphicsframecommitreceipts"]({5: 5})
    receiptnamespace["graphicsstagecommitreceipts"](nextframe)
    receiptmessages.clear()
    receiptnamespace["graphicspresentationpulse"]()

    if (
        len(receiptmessages) != 1
        or receiptmessages[0][1].get("generation") != 5
        or receiptmessages[0][1].get("presented") is not True
        or receiptnamespace["GPUPENDINGCOMMITRECEIPTS"]
    ):
        raise SystemExit(
            "a raw synchronous page-flip completion stranded its managed "
            "presentation receipt"
        )

    # A failed frame submission restores its captured request ahead of any
    # newer request accepted while gpuend() was servicing I/O.
    receiptwindows[5]["_gpu_command_generation"] = 6
    presentationresponse(
        1,
        receiptwindows[5],
        {
            "op": "GRAPHICS_COMMITTED",
            "winid": 5,
            "generation": 6,
            "accelerated": True,
        },
    )
    failedframe = receiptnamespace["graphicsframecommitreceipts"]({5: 6})
    receiptwindows[5]["_gpu_command_generation"] = 7
    presentationresponse(
        1,
        receiptwindows[5],
        {
            "op": "GRAPHICS_COMMITTED",
            "winid": 5,
            "generation": 7,
            "accelerated": True,
        },
    )
    receiptnamespace["graphicsrestorecommitreceipts"](failedframe)

    if [
        value.get("generation")
        for value in receiptwindows[5]["_gpu_commit_receipts"]
    ] != [6, 7]:
        raise SystemExit(
            "failed frame submission did not restore receipt ordering"
        )

    receiptmessages.clear()
    receiptwindows[5]["mapped"] = False
    receiptnamespace["graphicscancelcommitreceipts"](
        receiptwindows[5],
        "window was unmapped before presentation",
    )

    if (
        [message.get("generation") for _, message in receiptmessages]
        != [6, 7]
        or any(
            message.get("presented") is not False
            or message.get("superseded") is not True
            for _, message in receiptmessages
        )
    ):
        raise SystemExit(
            "unmapping a window did not cancel its unsubmitted receipts"
        )

    receiptmessages.clear()
    presentationresponse(
        1,
        receiptwindows[5],
        {
            "op": "GRAPHICS_COMMITTED",
            "winid": 5,
            "generation": 8,
            "accelerated": True,
        },
    )

    if (
        receiptmessages
        or [
            value.get("generation")
            for value in receiptwindows[5]["_gpu_commit_receipts"]
        ] != [8]
    ):
        raise SystemExit(
            "an unmapped initial GPU scene was not retained for its first "
            "visible frame"
        )

    if receiptnamespace["graphicsframecommitreceipts"]({}):
        raise SystemExit(
            "an unmapped initial GPU scene was captured by an unrelated frame"
        )

    receiptwindows[5]["mapped"] = True
    firstvisible = receiptnamespace["graphicsframecommitreceipts"]({5: 8})
    receiptnamespace["graphicsstagecommitreceipts"](firstvisible)
    receiptnamespace["graphicsfinishcommitreceipts"]()

    if (
        len(receiptmessages) != 1
        or receiptmessages[0][1].get("generation") != 8
        or receiptmessages[0][1].get("presented") is not True
        or receiptwindows[5]["_gpu_presented_generation"] != 8
    ):
        raise SystemExit(
            "a pre-map GPU scene did not receive the first visible frame's "
            "physical presentation receipt"
        )

    # If an unmap arrives while gpuend() is waiting, the newly cancelled
    # request must not overtake the older generation already captured in the
    # rendered frame.
    receiptmessages.clear()
    receiptwindows[5]["_gpu_command_generation"] = 9
    presentationresponse(
        1,
        receiptwindows[5],
        {
            "op": "GRAPHICS_COMMITTED",
            "winid": 5,
            "generation": 9,
            "accelerated": True,
        },
    )
    capturedbeforeunmap = receiptnamespace[
        "graphicsframecommitreceipts"
    ]({5: 9})
    receiptwindows[5]["_gpu_command_generation"] = 10
    presentationresponse(
        1,
        receiptwindows[5],
        {
            "op": "GRAPHICS_COMMITTED",
            "winid": 5,
            "generation": 10,
            "accelerated": True,
        },
    )
    receiptwindows[5]["mapped"] = False
    receiptnamespace["graphicscancelcommitreceipts"](
        receiptwindows[5],
        "window was unmapped before presentation",
    )

    if (
        receiptmessages
        or len(receiptnamespace["GPUDEFERREDCOMMITRECEIPTS"]) != 1
    ):
        raise SystemExit(
            "unmap cancellation overtook a generation captured during gpuend"
        )

    receiptnamespace["graphicsstagecommitreceipts"](
        capturedbeforeunmap
    )
    receiptnamespace["graphicsfinishcommitreceipts"]()

    if (
        [message.get("generation") for _, message in receiptmessages]
        != [9, 10]
        or receiptmessages[0][1].get("presented") is not True
        or receiptmessages[1][1].get("presented") is not False
        or receiptmessages[1][1].get("superseded") is not True
        or receiptnamespace["GPUDEFERREDCOMMITRECEIPTS"]
    ):
        raise SystemExit(
            "captured and cancelled managed generations were delivered out "
            "of request order"
        )

    # Chromium's RGB DMA-BUF is captured while composing, but both its
    # presentation feedback and ownership release must wait for the physical
    # DRM completion. This keeps Chromium's Viz clock aligned with scan-out.
    chromium_events = []
    chromium_releases = []
    chromium_promotions = []
    flip_pending = [True]
    chromium_surface = {
        "presentation_dmabuf": True,
        "ready": True,
        "presented": False,
        "connection": 19,
        "frame": 23,
        "generation": 7,
        "pts_ns": 0,
    }
    chromium_window = {
        "id": 5,
        "_video_streams": {"chromium-presentation": chromium_surface},
    }
    chromium_namespace = {
        "GPUCAPTUREDCHROMIUMPRESENTATIONS": [],
        "GPUPENDINGCHROMIUMPRESENTATIONS": [],
        "VIDEOTELEMETRY": {
            "presented_frames": 0,
            "page_flip_presented_frames": 0,
            "presentation_receipts_pending": 0,
        },
        "windows": {5: chromium_window},
        "kmspresentationpending": lambda: flip_pending[0],
        "videoevent": (
            lambda connection, message:
            chromium_events.append((connection, dict(message))) or True
        ),
        "releasepresentationframe": (
            lambda surface:
            chromium_releases.append(surface["frame"]) or True
        ),
        "videopromotepending": (
            lambda win, stream, surface:
            chromium_promotions.append((win["id"], stream, surface["frame"]))
            or True
        ),
        "time": time,
    }
    loadsourcefunctions(
        windowserver,
        (
            "capturechromiumpresentation",
            "stagechromiumpresentations",
            "finishchromiumpresentations",
        ),
        chromium_namespace,
    )

    if (
        not chromium_namespace["capturechromiumpresentation"](
            chromium_window,
            "chromium-presentation",
            chromium_surface,
        )
        or chromium_namespace["capturechromiumpresentation"](
            chromium_window,
            "chromium-presentation",
            chromium_surface,
        )
        or chromium_namespace["stagechromiumpresentations"]() != 1
        or chromium_namespace["finishchromiumpresentations"]() != 0
        or chromium_events
        or chromium_releases
    ):
        raise SystemExit(
            "Chromium RGB feedback or release escaped before page flip"
        )

    flip_pending[0] = False

    if (
        chromium_namespace["finishchromiumpresentations"]() != 1
        or len(chromium_events) != 1
        or chromium_events[0][1].get("op") != "presented"
        or int(chromium_events[0][1].get("presented_ns", 0)) <= 0
        or chromium_releases != [23]
        or chromium_promotions != [(5, "chromium-presentation", 23)]
        or chromium_namespace["VIDEOTELEMETRY"]
        ["page_flip_presented_frames"] != 1
        or chromium_namespace["GPUPENDINGCHROMIUMPRESENTATIONS"]
    ):
        raise SystemExit(
            "Chromium RGB feedback did not complete at the page-flip boundary"
        )

    managedpresentation = graphics.managedstate()
    managedpresentation.update({
        "available": True,
        "pending": True,
        "pending_at": time.monotonic(),
        "winid": 5,
        "pending_scene": [{"kind": "rectangle"}],
    })

    if not graphics.managedresponse(
        managedpresentation,
        {
            "op": "GRAPHICS_COMMITTED",
            "winid": 5,
            "generation": 8,
            "accelerated": True,
            "managed_only": True,
            "presented": False,
            "superseded": True,
            "presentation_reason": "newer managed generation was drawn",
        },
    ):
        raise SystemExit(
            "managed graphics rejected an explicit superseded receipt"
        )

    if (
        managedpresentation.get("presented") is not False
        or managedpresentation.get("presentation_reason")
        != "newer managed generation was drawn"
    ):
        raise SystemExit(
            "managed graphics lost the server's physical presentation status"
        )

    delayedmanaged = graphics.managedstate()
    replacementscene = [{"kind": "rectangle", "rect": [0, 0, 1, 1]}]
    delayedmanaged.update({
        "available": True,
        "active": False,
        "pending": True,
        "pending_at": time.monotonic(),
        "winid": 5,
        "scene": [],
        "pending_scene": list(replacementscene),
        "generation": 0,
        "submitted_generation": 3,
        "pending_generation": 3,
        "pending_clear_generation": 2,
    })

    for response in (
        {
            "op": "GRAPHICS_COMMITTED",
            "winid": 5,
            "generation": 1,
            "accelerated": True,
            "managed_only": True,
            "presented": False,
            "superseded": True,
        },
        {
            "op": "GRAPHICS_CLEARED",
            "winid": 5,
            "generation": 2,
            "presented": False,
            "superseded": True,
        },
    ):
        if not graphics.managedresponse(delayedmanaged, response):
            raise SystemExit(
                "managed graphics rejected an older delayed receipt"
            )

        if (
            delayedmanaged.get("pending") is not True
            or delayedmanaged.get("pending_generation") != 3
            or delayedmanaged.get("pending_scene") != replacementscene
        ):
            raise SystemExit(
                "an older delayed receipt released or replaced the newer "
                "managed scene"
            )

    graphics.managedresponse(
        delayedmanaged,
        {
            "op": "GRAPHICS_COMMITTED",
            "winid": 5,
            "generation": 3,
            "count": 1,
            "accelerated": True,
            "managed_only": True,
            "presented": True,
            "frame_sequence": 80,
        },
    )

    if (
        delayedmanaged.get("pending")
        or delayedmanaged.get("generation") != 3
        or delayedmanaged.get("scene") != replacementscene
        or delayedmanaged.get("presented") is not True
    ):
        raise SystemExit(
            "the replacement managed scene was not published by its own "
            "physical receipt"
        )

    class SyntheticGPUCompositorError(RuntimeError):
        pass

    presentationstate = {
        "pending": True,
        "stalled": False,
        "wakes": 0,
        "queries": 0,
    }
    presentationevents = []

    def syntheticpresentationpending():

        presentationstate["queries"] += 1
        return bool(presentationstate["pending"])

    def syntheticpresentationstalled():
        return bool(presentationstate["stalled"])

    def syntheticserveio(timeout):

        presentationstate["wakes"] += 1
        presentationevents.append(("io", round(float(timeout), 6)))

        if presentationstate["wakes"] == 2:
            presentationstate["pending"] = False
            presentationevents.append(("flip", presentationstate["wakes"]))

    presentationnamespace = {
        "time": time,
        "GPUCOMPOSITOR": True,
        "GRAPHICSPRESENTFD": 7,
        "kmspresentationpending": syntheticpresentationpending,
        "kmspresentationstalled": syntheticpresentationstalled,
        "GPUCompositorError": SyntheticGPUCompositorError,
        "serveio": syntheticserveio,
        "GPUPRESENTATIONGATEWAITS": 0,
        "GPUPRESENTATIONGATERELEASES": 0,
        "GPUPRESENTATIONGATEWAITMS": 0.0,
        "GPUPRESENTATIONGATEMAXMS": 0.0,
    }
    loadsourcefunctions(
        windowserver,
        ("gpupresentationgate",),
        presentationnamespace,
    )
    presentationgate = presentationnamespace["gpupresentationgate"]

    if presentationgate(1.0 / 60.0):
        raise SystemExit("presentation gate rendered after unrelated selector I/O")

    if not presentationstate["pending"] or presentationevents != [("io", 0.016667)]:
        raise SystemExit("presentation gate did not preserve the outstanding flip")

    if not presentationgate(1.0 / 60.0):
        raise SystemExit("presentation gate did not release after the DRM event")

    if presentationevents[-2:] != [("io", 0.016667), ("flip", 2)]:
        raise SystemExit("presentation gate did not remain selector-driven")

    if (
        presentationnamespace["GPUPRESENTATIONGATEWAITS"] != 2
        or presentationnamespace["GPUPRESENTATIONGATERELEASES"] != 1
        or presentationnamespace["GPUPRESENTATIONGATEMAXMS"] < 0.0
    ):
        raise SystemExit("presentation gate telemetry is incorrect")

    presentationstate["pending"] = False
    wakebaseline = presentationstate["wakes"]

    if not presentationgate(1.0 / 60.0) or presentationstate["wakes"] != wakebaseline:
        raise SystemExit("presentation gate waited without an outstanding flip")

    presentationnamespace["GPUCOMPOSITOR"] = False
    presentationstate["pending"] = True
    querybaseline = presentationstate["queries"]

    if not presentationgate(1.0 / 60.0):
        raise SystemExit("CPU compositor was blocked by the DRM presentation gate")

    if presentationstate["queries"] != querybaseline:
        raise SystemExit("CPU compositor queried GPU presentation ownership")

    presentationnamespace["GPUCOMPOSITOR"] = True
    presentationstate["stalled"] = True

    try:
        presentationgate(1.0 / 60.0)
    except SyntheticGPUCompositorError:
        pass
    else:
        raise SystemExit("stalled DRM presentation did not fail the GPU owner")

    composedamage = []
    composeevents = []
    composestate = {"gate_calls": 0, "paints": 0}
    composenow = time.time()
    composenamespace = {
        "time": time,
        "SERVERRUN": True,
        "LASTFBPOLL": composenow,
        "LASTGRAPHICSSTATE": composenow,
        "LASTDISPLAYADJUSTMENT": composenow,
        "SCREENW": 1920,
        "SCREENH": 1080,
        "CURSORDIRTY": False,
        "POINTERX": 10,
        "POINTERY": 10,
        "DAMAGERECTS": composedamage,
        "GPUCOMPOSITOR": True,
        "GPUANIMATIONS": {1: [{}]},
        "windows": {
            1: {
                "id": 1,
                "mapped": True,
                "_gpu_transition_start": None,
            },
        },
        "CURSORSIZES": {},
        "WORKX": 0,
        "WORKY": 0,
        "WORKW": 1920,
        "WORKH": 1080,
        "GPUDeviceLostError": RuntimeError,
        "GPUCompositorError": SyntheticGPUCompositorError,
        "GPUDEVICEFAILUREEXIT": 70,
        "GPUCOMPOSITORFAILUREEXIT": 72,
        "pickerpulse": lambda: None,
        "drainio": lambda cycles=1: None,
        "savewindowpointerpos": lambda: None,
        "writegraphicsstate": lambda: None,
        "refreshdisplayadjustment": lambda: False,
        "gpuinvalidatesurface": lambda: None,
        "refreshfb": lambda waitpulse=None: False,
        "iopulse": lambda: None,
        "backendinfo": lambda: {"refresh_hz": 60.0},
        "gpusetframebudget": lambda value: None,
        "getscreensize": lambda: (1920, 1080),
        "applyuiscale": lambda: None,
        "writefbsize": lambda width, height: None,
        "setworkarea": lambda cfg: None,
        "refreshwindows": lambda previous: None,
        "broadcastworkarea": lambda: None,
        "broadcastfbsize": lambda: None,
        "pruneoverlays": lambda: None,
        "videoreleasepulse": lambda: None,
        "flushclientmotions": lambda: None,
        "pulsefocus": lambda: None,
        "dialogpulse": lambda: None,
        "savewindowattributes": lambda: None,
        "gpuanimationsactive": lambda: True,
        "gpuwindow3danimated": lambda win: False,
        "gpuvisualrect": lambda win: [2, 3, 40, 50],
        "serveio": lambda timeout=0.0: composeevents.append(("idle", timeout)),
        "gpufallback": lambda: None,
        "graphicslog": lambda message: None,
    }

    def syntheticcomposegate(timeout):

        composestate["gate_calls"] += 1
        composeevents.append(
            (
                "gate",
                composestate["gate_calls"],
                len(composedamage),
            )
        )
        return composestate["gate_calls"] >= 2

    def syntheticpaintregions():

        composestate["paints"] += 1
        composeevents.append(("paint", list(composedamage)))
        composenamespace["SERVERRUN"] = False

    composenamespace["gpupresentationgate"] = syntheticcomposegate
    composenamespace["paintregions"] = syntheticpaintregions
    loadsourcefunctions(
        windowserver,
        ("composeloop",),
        composenamespace,
    )
    composenamespace["composeloop"]({"frame_interval_ms": 16.667})

    if composeevents[:3] != [
        ("gate", 1, 0),
        ("gate", 2, 0),
        ("paint", [[2, 3, 40, 50]]),
    ]:
        raise SystemExit(
            "compose loop rendered or accumulated animation damage before "
            f"page-flip completion: {composeevents[:6]!r}"
        )

    if composestate["paints"] != 1 or len(composedamage) != 1:
        raise SystemExit("compose loop did not present exactly one phase-locked frame")

    telemetryos = types.SimpleNamespace(
        path=os.path,
        makedirs=os.makedirs,
        replace=os.replace,
        unlink=os.unlink,
        fsync=lambda descriptor: (
            time.sleep(0.1),
            os.fsync(descriptor),
        )[-1],
    )
    telemetrynamespace = {
        "os": telemetryos,
        "json": json,
        "time": time,
        "queue": queue,
        "threading": threading,
        "TELEMETRYWRITEQUEUE": queue.Queue(maxsize=1),
        "TELEMETRYWRITER": None,
        "TELEMETRYWRITERLOCK": threading.Lock(),
        "TELEMETRYWRITESTATS": {
            "queued": 0,
            "completed": 0,
            "coalesced": 0,
            "failures": 0,
            "last_write_ms": 0.0,
            "maximum_write_ms": 0.0,
            "last_queue_delay_ms": 0.0,
            "last_error": "",
        },
    }
    loadsourcefunctions(
        windowserver,
        (
            "telemetrywriterloop",
            "queuetelemetrywrite",
            "stoptelemetrywriter",
        ),
        telemetrynamespace,
    )

    with tempfile.TemporaryDirectory() as directory:

        telemetrypath = str(Path(directory) / "graphics telemetry.json")
        started = time.monotonic()

        if not telemetrynamespace["queuetelemetrywrite"](
            telemetrypath,
            {"sequence": 7},
        ):
            raise SystemExit("asynchronous graphics telemetry was not queued")

        if time.monotonic() - started >= 0.05:
            raise SystemExit("persistent telemetry blocked the compositor caller")

        if not telemetrynamespace["stoptelemetrywriter"](timeout=2.0):
            raise SystemExit("graphics telemetry writer did not drain")

        if json.loads(Path(telemetrypath).read_text(encoding="utf-8")) != {
            "sequence": 7
        }:
            raise SystemExit("graphics telemetry writer did not persist atomically")

    class InputConnection:

        def __init__(self, payload):
            self.payload = bytearray(payload)

        def recv(self, amount):

            if not self.payload:
                raise BlockingIOError()

            length = min(int(amount), len(self.payload))
            payload = bytes(self.payload[:length])
            del self.payload[:length]
            return payload

    inputpayload = b"".join(
        json.dumps(value, separators=(",", ":")).encode("utf-8") + b"\n"
        for value in (
            {"op": "EVENT", "kind": "pointer", "x": 1, "y": 1},
            {"op": "EVENT", "kind": "pointer", "x": 2, "y": 2},
            {"op": "EVENT", "kind": "button", "button": 1, "state": 1},
            {"op": "EVENT", "kind": "pointer", "x": 3, "y": 3},
        )
    )
    inputidentity = {
        "pid": 7302,
        "starttime": 190074,
        "domain": "input",
    }
    inputnamespace = {
        "json": json,
        "INPUTCONN": InputConnection(inputpayload),
        "INPUTIDENTITY": inputidentity,
        "INPUTINBUF": b"",
        "INPUTDRAINLIMIT": 256 * 1024,
        "INPUTBYTESDRAINED": 0,
        "INPUTDRAINCAPS": 0,
        "INPUTPOINTERCOALESCED": 0,
        "processidentitycurrent": lambda identity: identity is inputidentity,
        "sel": types.SimpleNamespace(
            unregister=lambda connection: None,
        ),
        "log": lambda message: None,
    }
    loadsourcefunctions(
        windowserver,
        ("recvinputlines",),
        inputnamespace,
    )
    inputlines = [
        json.loads(value)
        for value in inputnamespace["recvinputlines"]()
    ]

    if [value["kind"] for value in inputlines] != [
        "pointer",
        "button",
        "pointer",
    ]:
        raise SystemExit("input drain did not preserve transition ordering")

    if (
        inputlines[0]["x"] != 2
        or inputnamespace["INPUTPOINTERCOALESCED"] != 1
        or inputnamespace["INPUTBYTESDRAINED"] != len(inputpayload)
    ):
        raise SystemExit("input drain did not coalesce stale pointer motion")

    # A loss-sensitive transition beyond the former 64 KiB boundary must be
    # handled in the same bounded drain cycle.  Consecutive pointer state may
    # collapse, but the key record and its ordering may not.
    adversarialinput = b"".join(
        json.dumps(
            {"op": "EVENT", "kind": "pointer", "x": value, "y": value},
            separators=(",", ":"),
        ).encode("utf-8") + b"\n"
        for value in range(3000)
    )
    adversarialinput += (
        json.dumps(
            {"op": "EVENT", "kind": "key", "code": 30, "state": "down"},
            separators=(",", ":"),
        ).encode("utf-8") + b"\n"
    )

    if not 64 * 1024 < len(adversarialinput) < 256 * 1024:
        raise SystemExit("input drain adversary has the wrong wire size")

    inputnamespace["INPUTCONN"] = InputConnection(adversarialinput)
    inputnamespace["INPUTINBUF"] = b""
    inputnamespace["INPUTBYTESDRAINED"] = 0
    inputnamespace["INPUTDRAINCAPS"] = 0
    inputnamespace["INPUTPOINTERCOALESCED"] = 0
    adversariallines = [
        json.loads(value)
        for value in inputnamespace["recvinputlines"]()
    ]

    if (
        [value.get("kind") for value in adversariallines]
        != ["pointer", "key"]
        or adversariallines[0].get("x") != 2999
        or inputnamespace["INPUTBYTESDRAINED"] != len(adversarialinput)
        or inputnamespace["INPUTDRAINCAPS"] != 0
    ):
        raise SystemExit(
            "256 KiB input drain did not reach the transition beyond 64 KiB"
        )

    inputserversource = (
        projectroot / "source/build software/input/inputserver.py"
    ).read_text(encoding="utf-8")
    inputclock = [100.0]

    class PartialInputSocket:

        def __init__(self, blocked=True, maximum=7):
            self.blocked = blocked
            self.maximum = int(maximum)
            self.output = bytearray()

        def send(self, value):

            if self.blocked:
                raise BlockingIOError()

            data = bytes(value)
            length = min(len(data), self.maximum)
            self.output.extend(data[:length])
            return length

    class InputSelector:

        def __init__(self):
            self.modifications = []

        def modify(self, *args):
            self.modifications.append(args)

        def unregister(self, sock):
            return None

    inputselector = InputSelector()
    inputsock = PartialInputSocket()
    inputdrops = []
    inputoutputnamespace = {
        "json": json,
        "time": types.SimpleNamespace(
            monotonic=lambda: inputclock[0],
        ),
        "selectors": selectors,
        "CLIENTOUTBUFLIMIT": 1024 * 1024,
        "CLIENTFLUSHBYTES": 64 * 1024,
        "CLIENTPOINTERINTERVAL": 1.0 / 240.0,
        "CLIENTPOINTERCOALESCED": 0,
        "CLIENTOUTBUFPEAK": 0,
        "clients": {
            41: {
                "sock": inputsock,
                "outbuf": bytearray(),
                "outoffset": 0,
                "pending_pointer": None,
                "pointer_next_at": 0.0,
                "events": selectors.EVENT_READ,
            },
        },
        "sel": inputselector,
        "log": lambda message: None,
    }

    def dropinputclient(cid, reason):
        inputdrops.append((cid, reason))
        inputoutputnamespace["clients"].pop(cid, None)

    inputoutputnamespace["dropclient"] = dropinputclient
    loadsourcefunctions(
        inputserversource,
        (
            "appendclientoutput",
            "materializeclientpointer",
            "flushclientpointers",
            "nextclientpointertimeout",
            "sendjson",
            "updateclientevents",
            "flushclient",
        ),
        inputoutputnamespace,
    )
    inputsendjson = inputoutputnamespace["sendjson"]
    inputsendjson(
        41,
        {"op": "EVENT", "kind": "pointer", "x": 0, "y": 0},
    )

    for coordinate in range(1, 1000):
        inputsendjson(
            41,
            {
                "op": "EVENT",
                "kind": "pointer",
                "x": coordinate,
                "y": coordinate,
            },
        )

    inputsendjson(
        41,
        {
            "op": "EVENT",
            "kind": "button",
            "button": 1,
            "state": "down",
        },
    )

    for coordinate in range(1000, 2000):
        inputsendjson(
            41,
            {
                "op": "EVENT",
                "kind": "pointer",
                "x": coordinate,
                "y": coordinate,
            },
        )

    inputsendjson(
        41,
        {"op": "EVENT", "kind": "key", "code": 30, "state": "down"},
    )
    inputqueued = bytes(
        inputoutputnamespace["clients"][41]["outbuf"]
    )
    inputmessages = [
        json.loads(line)
        for line in inputqueued.splitlines()
    ]

    if (
        [
            (value.get("kind"), value.get("x"))
            for value in inputmessages
        ]
        != [
            ("pointer", 0),
            ("pointer", 999),
            ("button", None),
            ("pointer", 1999),
            ("key", None),
        ]
        or inputoutputnamespace["CLIENTPOINTERCOALESCED"] < 1997
        or inputdrops
    ):
        raise SystemExit(
            "Input Server coalescing did not preserve transition ordering"
        )

    inputoutputnamespace["flushclient"](41)

    if (
        inputoutputnamespace["clients"][41]["outoffset"] != 0
        or bytes(inputoutputnamespace["clients"][41]["outbuf"]) != inputqueued
    ):
        raise SystemExit("blocked Input Server send mutated queued output")

    inputsock.blocked = False
    inputoutputnamespace["flushclient"](41)

    if (
        inputoutputnamespace["clients"][41]["outbuf"]
        or bytes(inputsock.output) != inputqueued
    ):
        raise SystemExit("partial Input Server sends corrupted queued output")

    # A pointer without a following transition remains one replaceable state
    # and gives the selector an exact 240 Hz wake deadline.
    inputsendjson(
        41,
        {"op": "EVENT", "kind": "pointer", "x": 2000, "y": 2000},
    )
    pointertimeout = inputoutputnamespace["nextclientpointertimeout"](
        0.01,
        now=inputclock[0],
    )

    if not 0.004 <= pointertimeout <= 0.0043:
        raise SystemExit("Input Server pointer deadline is not 240 Hz")

    inputclock[0] += 1.0 / 240.0
    inputoutputnamespace["flushclientpointers"](now=inputclock[0])

    if (
        inputoutputnamespace["clients"][41]["pending_pointer"] is not None
        or not inputoutputnamespace["clients"][41]["outbuf"]
    ):
        raise SystemExit("Input Server did not publish a due pointer state")

    # One client can consume no more than its fair 64 KiB write budget in a
    # pass, even when a synthetic socket accepts the entire offered buffer.
    fairsock = PartialInputSocket(blocked=False, maximum=2 * 1024 * 1024)
    inputoutputnamespace["clients"][42] = {
        "sock": fairsock,
        "outbuf": bytearray(),
        "outoffset": 0,
        "pending_pointer": None,
        "pointer_next_at": 0.0,
        "events": selectors.EVENT_READ,
    }
    fairpayload = b"x" * (96 * 1024)
    inputoutputnamespace["appendclientoutput"](42, fairpayload)
    inputoutputnamespace["flushclient"](42)

    if (
        len(fairsock.output) != 64 * 1024
        or len(inputoutputnamespace["clients"][42]["outbuf"])
        - int(inputoutputnamespace["clients"][42]["outoffset"])
        != 32 * 1024
    ):
        raise SystemExit("Input Server output flush exceeded its fair budget")

    inputoutputnamespace["clients"][43] = {
        "sock": PartialInputSocket(),
        "outbuf": bytearray(),
        "outoffset": 0,
        "pending_pointer": None,
        "pointer_next_at": 0.0,
        "events": selectors.EVENT_READ,
    }
    inputoutputnamespace["appendclientoutput"](
        43,
        b"x" * (inputoutputnamespace["CLIENTOUTBUFLIMIT"] + 1),
    )

    if 43 in inputoutputnamespace["clients"] or not inputdrops:
        raise SystemExit("Input Server output queue is not bounded")

    evformat = "qqHHi"
    evsize = struct.calcsize(evformat)
    evreadbytes = evsize * 256
    mouserecord = struct.pack(evformat, 1, 2, 2, 0, 1)
    mousechunks = [mouserecord * 256, mouserecord]

    def readmousechunk(fd, amount):

        if not mousechunks:
            raise BlockingIOError()

        return mousechunks.pop(0)

    mousenamespace = {
        "_MOUSE_FD": 51,
        "_MOUSEBTN_FD": None,
        "_MOUSEWHEEL_FD": None,
        "EV_SIZE": evsize,
        "EV_READ_BYTES": evreadbytes,
        "EV_FORMAT": evformat,
        "os": types.SimpleNamespace(read=readmousechunk),
        "select": types.SimpleNamespace(
            select=lambda *args: ([51], [], []),
        ),
        "struct": struct,
        "log": lambda message: None,
    }
    loadsourcefunctions(
        inputserversource,
        ("readmouse",),
        mousenamespace,
    )
    mouseevents = mousenamespace["readmouse"]()

    if len(mouseevents) != 257 or mousechunks:
        raise SystemExit("Input Server did not linearly drain the HID burst")

    class BackpressuredSocket:

        def __init__(self):
            self.blocked = True
            self.output = bytearray()

        def send(self, value):
            if self.blocked:
                raise BlockingIOError()
            data = bytes(value)
            self.output.extend(data)
            return len(data)

    outputsock = BackpressuredSocket()
    droppedclients = []
    outputnamespace = {
        "json": json,
        "time": time,
        "selectors": selectors,
        "CLIENTOUTBUFLIMIT": 4 * 1024 * 1024,
        "CLIENTPOINTERINTERVAL": 1.0 / 120.0,
        "CLIENTPOINTERCOALESCED": 0,
        "CLIENTOUTBUFPEAK": 0,
        "CLIENTOUTPUTDROPS": 0,
        "clients": {
            7: {
                "sock": outputsock,
                "outbuf": bytearray(),
                "pending_motion": None,
                "motion_next_at": 0.0,
                "events": selectors.EVENT_READ,
            },
        },
        "sel": types.SimpleNamespace(modify=lambda *args, **kwargs: None),
    }

    def dropoutputclient(cid, reason):
        droppedclients.append((cid, reason))
        outputnamespace["clients"].pop(cid, None)

    outputnamespace["dropclient"] = dropoutputclient
    loadsourcefunctions(
        windowserver,
        (
            "appendclientoutput",
            "materializeclientmotion",
            "flushclientmotions",
            "sendjson",
            "updateclientevents",
            "flushclient",
        ),
        outputnamespace,
    )
    outputnamespace["sendjson"](7, {"op": "POINTER_MOTION", "x": 0, "y": 0})

    for coordinate in range(1, 1000):
        outputnamespace["sendjson"](
            7,
            {"op": "POINTER_MOTION", "x": coordinate, "y": coordinate},
        )

    outputnamespace["sendjson"](
        7,
        {"op": "POINTER_BUTTON", "button": 1, "state": "down"},
    )
    queuedmessages = [
        json.loads(line)
        for line in bytes(outputnamespace["clients"][7]["outbuf"]).splitlines()
    ]

    if [message["op"] for message in queuedmessages] != [
        "POINTER_MOTION",
        "POINTER_MOTION",
        "POINTER_BUTTON",
    ]:
        raise SystemExit("client output coalescing did not preserve click ordering")

    if queuedmessages[1].get("x") != 999:
        raise SystemExit("client output coalescing did not retain the newest pointer")

    if outputnamespace["CLIENTPOINTERCOALESCED"] < 998 or droppedclients:
        raise SystemExit("client output backpressure accounting is incorrect")

    outputsock.blocked = False
    outputnamespace["flushclient"](7)

    if outputnamespace["clients"][7]["outbuf"] or not outputsock.output:
        raise SystemExit("client output queue did not drain after backpressure cleared")

    pointercalls = []
    brickinputnamespace = {
        "HASFOCUS": False,
        "KEYQUEUE": [],
        "SCROLLOFF": 0,
        "DIRTY_SCROLL": False,
        "DIRTY_PROMPT": False,
        "RUNNING": True,
        "SOCK": None,
        "WINID": 17,
        "handlepointerbutton": lambda message: pointercalls.append(message),
        "handlepointermotion": lambda message: None,
        "queuesmoothscroll": lambda amount: None,
        "guiprint": lambda *args, **kwargs: None,
        "ERRORCOLOUR": 0,
        "SCROLLSTEP": 3,
        "consoleactive": lambda: False,
    }
    loadsourcefunctions(
        bricksource,
        ("handleservermsg",),
        brickinputnamespace,
    )
    brickinputnamespace["handleservermsg"](
        {"op": "POINTER_BUTTON", "winid": 17, "button": 1, "state": "down"}
    )

    if not brickinputnamespace["HASFOCUS"] or len(pointercalls) != 1:
        raise SystemExit("directed Brick click did not repair stale local focus")

    brickrendernamespace = {
        "DIRTY_SCROLL": True,
        "DIRTY_PROMPT": False,
        "SOCK": object(),
        "WINID": 17,
        "PREV_CURSOR_ON": False,
        "LASTSCROLLFRAME": 0.0,
        "GRAPHICSSTATE": {"active": True, "managed_only": True},
        "SCROLLMANAGEDINTERVAL": 1.0 / 60.0,
        "SCROLLCPUINTERVAL": 1.0 / 12.0,
        "time": time,
        "jobreap": lambda: None,
        "drawcontent": lambda cursor_on: None,
        "presentbrick": lambda: None,
        "consoleactive": lambda: False,
    }

    def brickpoll():
        brickrendernamespace["DIRTY_PROMPT"] = True

    brickrendernamespace["pollserver"] = brickpoll
    loadsourcefunctions(
        bricksource,
        ("renderframe",),
        brickrendernamespace,
    )

    if not brickrendernamespace["renderframe"](False):
        raise SystemExit("Brick dirty frame was not rendered")

    if not brickrendernamespace["DIRTY_PROMPT"]:
        raise SystemExit("Brick erased a focus/resize dirty raised during frame polling")

    startremaps = []
    startpaint = []
    expansenamespace = {
        "STARTID": 93,
        "STARTMAPPED": True,
        "STARTVISIBLE": True,
        "STARTWANTED": True,
        "AWAITMAP": {93: {"role": "startmenu", "n": 1}},
        "paintstartmenu": lambda sock: startpaint.append(True),
        "log": lambda message: None,
    }

    def remapstart(sock, wid, role):
        startremaps.append((wid, role))
        expansenamespace["AWAITMAP"][wid] = {"role": role, "n": 0}

    expansenamespace["mapwin"] = remapstart
    loadsourcefunctions(
        expansesource,
        ("handleunmapped",),
        expansenamespace,
    )
    expansenamespace["handleunmapped"](object(), {"winid": 93})

    if (
        not expansenamespace["STARTWANTED"]
        or expansenamespace["STARTMAPPED"]
        or expansenamespace["STARTVISIBLE"]
        or startremaps != [(93, "startmenu")]
        or not startpaint
        or 93 not in expansenamespace["AWAITMAP"]
    ):
        raise SystemExit("late Start unmap acknowledgement cancelled a newer reopen")

    expansenamespace["STARTWANTED"] = False
    expansenamespace["AWAITMAP"][93] = {"role": "startmenu", "n": 1}
    expansenamespace["handleunmapped"](object(), {"winid": 93})

    if 93 in expansenamespace["AWAITMAP"]:
        raise SystemExit("closed Start menu retained a stale map retry")

    class LoaderFunction:

        def __init__(self, result=0):
            self.result = result
            self.argtypes = None
            self.restype = None

        def __call__(self, *args):
            return self.result

    class LoaderLibrary:

        def __init__(self):
            self.functions = {}

        def __getattr__(self, name):
            result = 0 if name == "eglGetProcAddress" else 1
            return self.functions.setdefault(name, LoaderFunction(result))

    originalconfigureprovider = graphics._graphicsconfigureprovider
    originalnvidiapreload = graphics._graphicsnvidiapreload
    originalcdll = graphics.ctypes.CDLL

    try:
        graphics._egl = object()
        graphics._gles = None
        graphics._openglprovider = "nvidia"
        graphics._opengldependencies = [object()]
        graphics._graphicsconfigureprovider = lambda provider: {
            "egl": f"/test/{provider}/libEGL.so",
            "gles": f"/test/{provider}/libGLESv2.so",
        }
        graphics._graphicsnvidiapreload = lambda runtime: (
            (_ for _ in ()).throw(
                RuntimeError("synthetic missing NVIDIA dependency")
            )
        )
        graphics.ctypes.CDLL = lambda *args, **kwargs: LoaderLibrary()

        if graphics.openglload("nvidia"):
            raise SystemExit(
                "failed NVIDIA provider preload was incorrectly committed"
            )

        if (
            graphics._egl is not None
            or graphics._gles is not None
            or graphics._openglprovider is not None
            or graphics._opengldependencies
        ):
            raise SystemExit(
                "failed NVIDIA provider preload did not roll back loader state"
            )

        if not graphics.openglload("mesa"):
            raise SystemExit(
                "Mesa provider could not load after NVIDIA rollback"
            )

        if graphics._openglprovider != "mesa":
            raise SystemExit(
                "OpenGL provider identity was committed before successful load"
            )
    finally:
        graphics._egl = None
        graphics._gles = None
        graphics._openglprovider = None
        graphics._opengldependencies = []
        graphics._graphicsconfigureprovider = originalconfigureprovider
        graphics._graphicsnvidiapreload = originalnvidiapreload
        graphics.ctypes.CDLL = originalcdll

    class TextureGLES:

        def __init__(self):
            self.allocations = []
            self.nexttexture = 40

        def glGenTextures(self, count, output):
            ctypes.cast(output, ctypes.POINTER(ctypes.c_uint))[0] = self.nexttexture
            self.nexttexture += 1

        def glActiveTexture(self, *args):
            return None

        def glBindTexture(self, *args):
            return None

        def glTexParameteri(self, *args):
            return None

        def glPixelStorei(self, *args):
            return None

        def glTexImage2D(self, *args):
            self.allocations.append(args)

        def glDeleteTextures(self, *args):
            return None

    originalgpuinitialise = graphics.gpuinitialise
    originalgputextures = graphics._gputextures
    originalgpuhandle = graphics._gpuhandle
    originalgputexturebytes = graphics._gputexturebytes
    originalgputelemetry = dict(graphics._gputelemetry)
    texturegles = TextureGLES()

    try:
        graphics._gles = texturegles
        graphics.gpuinitialise = lambda: True
        graphics._gputextures = {}
        graphics._gpuhandle = 1
        graphics._gputexturebytes = 0
        rgbhandle = graphics.gputexturecreate(
            32,
            18,
            owner="test-preservation",
            alpha=False,
            storage="RGB",
        )
        rgballocation = texturegles.allocations[-1]

        if (
            rgballocation[2] != graphics.GL_RGB
            or rgballocation[6] != graphics.GL_RGB
            or graphics.gputextureinfo(rgbhandle)["storage"] != "RGB"
        ):
            raise SystemExit(
                "default-framebuffer preservation texture was not allocated as RGB"
            )

        try:
            graphics.gputextureupdate(
                rgbhandle,
                data=bytes(32 * 18 * 4),
            )
        except ValueError:
            pass
        else:
            raise SystemExit(
                "RGB framebuffer-copy target accepted an incompatible RGBA upload"
            )

        rgbahandle = graphics.gputexturecreate(4, 4, owner="test-default")
        rgbaallocation = texturegles.allocations[-1]

        if (
            rgbaallocation[2] != graphics.GL_RGBA
            or rgbaallocation[6] != graphics.GL_RGBA
            or graphics.gputextureinfo(rgbahandle)["storage"] != "RGBA"
        ):
            raise SystemExit("managed texture default storage is no longer RGBA")
    finally:
        graphics._gles = None
        graphics.gpuinitialise = originalgpuinitialise
        graphics._gputextures = originalgputextures
        graphics._gpuhandle = originalgpuhandle
        graphics._gputexturebytes = originalgputexturebytes
        graphics._gputelemetry.clear()
        graphics._gputelemetry.update(originalgputelemetry)

    recoveryactions = loadsourcefunctions(
        goddess,
        ("acceleratedfailureaction",),
        {
            "WINDOWSERVERGPUFAILUREEXIT": 70,
            "WINDOWSERVERBACKENDINITFAILUREEXIT": 71,
            "WINDOWSERVERCOMPOSITORFAILUREEXIT": 72,
            "windowserverhello": lambda: True,
            "_ACCELERATEDDRMCANDIDATES": (),
        },
    )
    action = recoveryactions["acceleratedfailureaction"]

    if action(types.SimpleNamespace(poll=lambda: 70)) != "gpu-reset":
        raise SystemExit("verified WindowServer GPU failure does not authorize reset")

    if action(None) != "cpu-kms":
        raise SystemExit("missing WindowServer incorrectly authorizes a GPU reset")

    if action(types.SimpleNamespace(poll=lambda: 71)) != "next-device":
        raise SystemExit(
            "accelerated backend initialization failure does not select an "
            "isolated fresh-device process"
        )

    for status in (1, 72, 120):
        if action(types.SimpleNamespace(poll=lambda value=status: value)) != "cpu-kms":
            raise SystemExit(
                f"userspace WindowServer exit {status} incorrectly authorizes GPU reset"
            )

    liveprocess = types.SimpleNamespace(poll=lambda: None)

    if action(liveprocess) != "cpu-kms":
        raise SystemExit("unresponsive live GPU owner incorrectly authorizes reset")

    if action(liveprocess, acceptresponsive=True) != "cpu-kms":
        raise SystemExit(
            "responsive WindowServer/client failure does not preserve KMS for CPU login"
        )

    recoveryactions["_ACCELERATEDDRMCANDIDATES"] = (
        "/virtual/card0",
        "/virtual/card1",
    )

    if action(liveprocess) != "next-device":
        raise SystemExit(
            "hung accelerated owner does not rotate to another isolated GPU"
        )

    if action(liveprocess, acceptresponsive=True) != "cpu-kms":
        raise SystemExit(
            "responsive accelerated owner incorrectly rotates away from its GPU"
        )

    recoveryactions["windowserverhello"] = lambda: False

    if action(liveprocess, acceptresponsive=True) != "next-device":
        raise SystemExit(
            "failed WindowServer hello did not identify a hung GPU candidate"
        )

    candidateos = types.SimpleNamespace(
        environ={},
        path=os.path,
        listdir=lambda path: (
            ["card0", "card1"]
            if path == "/the one/drivers/nodes/dri"
            else ["card0-HDMI-A-1", "card1-HDMI-A-1"]
        ),
    )
    candidatestatus = {
        "/the one/drivers/state/class/drm/card0-HDMI-A-1/status":
            "disconnected\n",
        "/the one/drivers/state/class/drm/card1-HDMI-A-1/status":
            "connected\n",
    }
    candidatenamespace = {
        "os": candidateos,
        "re": __import__("re"),
        "open": lambda path, *args, **kwargs: io.StringIO(
            candidatestatus[str(path).replace("\\", "/")]
        ),
        "_ACCELERATEDDRMCANDIDATES": (),
        "_ACCELERATEDDRMATTEMPT": 0,
        "_KMSDRMCANDIDATES": (),
        "_KMSDRMATTEMPT": 0,
        "ACCELERATEDLOGINATTEMPTS": 3,
        "KMSRECOVERYATTEMPTSPERCYCLE": 3,
    }
    loadsourcefunctions(
        goddess,
        (
            "accelerateddrmcandidates",
            "nextaccelerateddrmdevice",
            "nextkmsdrmdevice",
        ),
        candidatenamespace,
    )
    nextdevice = candidatenamespace["nextaccelerateddrmdevice"]
    selecteddevices = [
        str(nextdevice()).replace("\\", "/")
        for _ in range(3)
    ]

    if selecteddevices != [
        "/the one/drivers/nodes/dri/card1",
        "/the one/drivers/nodes/dri/card0",
        "/the one/drivers/nodes/dri/card1",
    ]:
        raise SystemExit(
            "accelerated DRM candidates are not isolated and rotated with "
            f"connected scanout first: {selecteddevices}"
        )

    candidateos.environ["T1OS_DRM_DEVICE"] = "/explicit/card7"

    if nextdevice() != "/explicit/card7":
        raise SystemExit("explicit DRM selection was not isolated to one provider")

    candidateos.environ.clear()
    nextkmsdevice = candidatenamespace["nextkmsdrmdevice"]
    selectedkmsdevices = [
        str(nextkmsdevice()).replace("\\", "/")
        for _ in range(3)
    ]

    if selectedkmsdevices != [
        "/the one/drivers/nodes/dri/card1",
        "/the one/drivers/nodes/dri/card0",
        "/the one/drivers/nodes/dri/card1",
    ]:
        raise SystemExit(
            "CPU-KMS DRM candidates do not rotate independently with "
            f"connected scanout first: {selectedkmsdevices}"
        )

    environmentallocations = []
    consoleoutcomes = [False, True]
    environmentnamespace = loadsourcefunctions(
        goddess,
        ("windowserverenvironment",),
        {
            "os": types.SimpleNamespace(environ={}, path=os.path),
            "nextaccelerateddrmdevice": (
                lambda: (
                    environmentallocations.append("accelerated")
                    or "/virtual/card1"
                )
            ),
            "nextkmsdrmdevice": (
                lambda: (
                    environmentallocations.append("kms")
                    or "/virtual/card0"
                )
            ),
            "_drmpcigraphicsidentity": (
                lambda node: ("0000:01:00.0", "nvidia")
            ),
            "preparenvidiapathprovider": lambda: "/virtual/nvidia-path.so",
            "NVIDIAPATHPROVIDERSOURCE": "/virtual/source.so",
            "_ACCELERATEDDRMATTEMPT": 1,
            "_KMSDRMATTEMPT": 1,
            "ACCELERATEDLOGINATTEMPTS": 3,
            "KMSRECOVERYATTEMPTSPERCYCLE": 3,
            "firmwaregraphicsrecoveryrequested": lambda: False,
            "kernelcommandlineoption": lambda option: False,
            "setdisplayconsolemode": lambda graphics: consoleoutcomes.pop(0),
            "print": lambda *args, **kwargs: None,
        },
    )
    makeenvironment = environmentnamespace["windowserverenvironment"]
    acceleratedenvironment = makeenvironment("opengl")

    if (
        acceleratedenvironment.get("T1OS_DRM_DEVICE") != "/virtual/card1"
        or acceleratedenvironment.get("__NV_GBM_TRACE_ENABLED") != "1"
        or acceleratedenvironment.get("LD_PRELOAD")
        != "/virtual/nvidia-path.so"
        or environmentallocations != ["accelerated"]
    ):
        raise SystemExit(
            "NVIDIA WindowServer environment is not isolated to one traced "
            f"provider/device allocation: {acceleratedenvironment}"
        )

    kmsenvironment = makeenvironment("kms-framebuffer")

    if (
        kmsenvironment.get("T1OS_DRM_DEVICE") != "/virtual/card0"
        or kmsenvironment.get("T1OS_GRAPHICS") != "cpu"
        or "__NV_GBM_TRACE_ENABLED" in kmsenvironment
        or environmentallocations != ["accelerated", "kms"]
    ):
        raise SystemExit(
            "CPU-KMS WindowServer environment did not receive its independent "
            f"DRM candidate: {kmsenvironment}"
        )

    unownedframebuffer = makeenvironment("framebuffer")
    ownedframebuffer = makeenvironment("framebuffer")

    if (
        "T1OS_FRAMEBUFFER_CONSOLE_OWNED" in unownedframebuffer
        or ownedframebuffer.get("T1OS_FRAMEBUFFER_CONSOLE_OWNED") != "1"
    ):
        raise SystemExit(
            "native framebuffer environment does not bind launch permission "
            "to a successful KD_TEXT ownership transition"
        )

    class ConsoleHelperClock:

        def __init__(self):
            self.now = 0.0

        def monotonic(self):
            return self.now

        def sleep(self, delay):
            self.now += float(delay)

    class RetiringConsoleHelper:

        def __init__(self):
            self.polls = 0

        def poll(self):
            self.polls += 1
            return 0 if self.polls >= 3 else None

    helperclock = ConsoleHelperClock()
    helperprocess = RetiringConsoleHelper()
    helpernamespace = loadsourcefunctions(
        goddess,
        ("waitdisplayconsolemodehelper",),
        {
            "DISPLAYCONSOLEHELPERRETIRETIMEOUT": 5.0,
            "_PENDINGDISPLAYMODEHELPER": helperprocess,
            "_PENDINGDISPLAYMODE": "text",
            "time": helperclock,
            "print": lambda *args, **kwargs: None,
        },
    )

    if (
        not helpernamespace["waitdisplayconsolemodehelper"]()
        or helpernamespace["_PENDINGDISPLAYMODEHELPER"] is not None
        or helpernamespace["_PENDINGDISPLAYMODE"] is not None
    ):
        raise SystemExit(
            "retired KD_TEXT helper remains able to overwrite a later "
            "managed KMS presentation"
        )

    class RetirementClock:

        def __init__(self):
            self.now = 0.0

        def monotonic(self):
            return self.now

        def sleep(self, delay):
            self.now += float(delay)

    class RetirementProcess:

        def __init__(self, unkillable=False):
            self.pid = 2718
            self.status = None
            self.unkillable = unkillable
            self.terminated = 0
            self.killed = 0

        def poll(self):
            return self.status

        def terminate(self):
            self.terminated += 1

        def kill(self):
            self.killed += 1

        def wait(self, timeout=None):

            if self.unkillable:
                raise subprocess.TimeoutExpired("boot animation", timeout)

            self.status = -15
            return self.status

    retirementclock = RetirementClock()
    retirementnamespace = loadsourcefunctions(
        goddess,
        ("stopbootanimation",),
        {
            "time": retirementclock,
            "subprocess": subprocess,
            "bootanimationrequest": lambda pid, action: True,
            # "done" alone must not be accepted as fd/mmap retirement.
            "bootanimationstate": lambda pid: "done",
        },
    )
    retireanimation = retirementnamespace["stopbootanimation"]
    gracefulretirement = RetirementProcess()

    if (
        not retireanimation(gracefulretirement)
        or gracefulretirement.terminated != 1
    ):
        raise SystemExit(
            "early framebuffer writer was treated as retired from its state "
            "file without joining the still-live process"
        )

    retirementclock.now = 0.0
    stuckretirement = RetirementProcess(unkillable=True)

    if (
        retireanimation(stuckretirement)
        or stuckretirement.terminated != 1
        or stuckretirement.killed != 1
    ):
        raise SystemExit(
            "unretired early framebuffer writer did not block native driver "
            "takeover after TERM and KILL"
        )

    with tempfile.TemporaryDirectory() as temporary:
        recoveryroot = Path(temporary)
        bootidpath = recoveryroot / "boot_id"
        recoverypath = recoveryroot / "graphics recovery boot.json"
        currentboot = "806e7a15-5099-4fda-b909-cb85cb364f8d"
        priorboot = "d174f975-9b45-41ea-8714-4dc1f25e5f2a"
        bootidpath.write_text(currentboot, encoding="ascii")
        markernamespace = loadsourcefunctions(
            goddess,
            (
                "normalisebootid",
                "currentbootid",
                "firmwaregraphicsrecoveryrequested",
            ),
            {
                "uuid": __import__("uuid"),
                "json": json,
                "BOOTIDPATHS": (str(bootidpath),),
                "GRAPHICSRECOVERYBOOT": str(recoverypath),
            },
        )
        markeractive = markernamespace[
            "firmwaregraphicsrecoveryrequested"
        ]

        def writemarker(origin):
            recoverypath.write_text(
                json.dumps({
                    "format": 1,
                    "mode": "firmware-framebuffer",
                    "state": "requested",
                    "boot_id": origin,
                }),
                encoding="utf-8",
            )

        writemarker(currentboot)

        if markeractive():
            raise SystemExit(
                "same-boot recovery request incorrectly authorizes stale "
                "firmware framebuffer use"
            )

        writemarker(priorboot)

        if markeractive():
            raise SystemExit(
                "prior-boot graphics state incorrectly disabled native GPU "
                "discovery"
            )

        writemarker("")

        if markeractive():
            raise SystemExit(
                "uncorrelated firmware recovery marker did not fail closed"
            )

        bootidpath.unlink()
        writemarker(priorboot)

        if markeractive():
            raise SystemExit(
                "firmware recovery activated without a readable current boot ID"
            )

        bootidpath.write_text(currentboot, encoding="ascii")
        driverpredicate = loadsourcefunctions(
            driverserver,
            ("firmwaregraphicsrecoveryrequested",),
            {
                "Path": Path,
                "json": json,
                "uuid": __import__("uuid"),
                "GRAPHICSRECOVERYBOOTPATH": recoverypath,
                "BOOTIDPATH": bootidpath,
            },
        )["firmwaregraphicsrecoveryrequested"]
        writemarker(currentboot)

        if driverpredicate(recoverypath, bootidpath):
            raise SystemExit(
                "DriverServer restart suppresses native GPU drivers for a "
                "same-boot next-boot marker"
            )

        writemarker(priorboot)

        if driverpredicate(recoverypath, bootidpath):
            raise SystemExit(
                "DriverServer honored obsolete prior-boot framebuffer state"
            )

    firmwarepin = loadsourcefunctions(
        goddess,
        ("pinfirmwarerecoveryboot",),
        {
            "os": __import__("os"),
            "struct": struct,
            "EFIVARFSROOT": "/unused",
            "EFIVARGLOBALGUID": "8be4df61-93ca-11d2-aa0d-00e098032b8c",
            "print": lambda *args, **kwargs: None,
            "angelprint": lambda *args, **kwargs: None,
        },
    )["pinfirmwarerecoveryboot"]

    with tempfile.TemporaryDirectory() as temporary:
        efiroot = Path(temporary)
        guid = "8be4df61-93ca-11d2-aa0d-00e098032b8c"
        current = 0x27
        (efiroot / f"BootCurrent-{guid}").write_bytes(
            struct.pack("<IH", 6, current)
        )
        (efiroot / f"Boot{current:04X}-{guid}").write_bytes(
            struct.pack("<IH", 7, current) + b"validated boot option"
        )
        pinned, detail = firmwarepin(efiroot)

        if (
            not pinned
            or detail != f"Boot{current:04X}"
            or (efiroot / f"BootNext-{guid}").read_bytes()
            != struct.pack("<IH", 7, current)
        ):
            raise SystemExit(
                "firmware recovery does not verify BootNext=BootCurrent"
            )

    with tempfile.TemporaryDirectory() as temporary:
        efiroot = Path(temporary)
        (efiroot / f"BootCurrent-{guid}").write_bytes(
            struct.pack("<IH", 6, current)
        )
        pinned, _ = firmwarepin(efiroot)

        if pinned or (efiroot / f"BootNext-{guid}").exists():
            raise SystemExit(
                "firmware recovery pins an absent current boot option"
            )

    visibleevents = []
    visiblerecoverynamespace = loadsourcefunctions(
        goddess,
        ("visibleframebufferrecoveryretry",),
        {
            "FRAMEBUFFERRECOVERYATTEMPTSPERCYCLE": 3,
            "FRAMEBUFFERRECOVERYVISIBLEDELAY": 15.0,
            "stopbootanimation": lambda proc: visibleevents.append(
                ("stop-animation", proc.pid)
            ),
            "terminateprocess": lambda proc: visibleevents.append(
                ("terminate", proc.pid)
            ),
            "setdisplayconsolemode": lambda graphics: (
                visibleevents.append(("console-mode", graphics)) or True
            ),
            "mirrordisplayconsole": lambda force=False: visibleevents.append(
                ("console-mirror", force)
            ),
            "recordgraphicsrecovery": (
                lambda *args, **kwargs: visibleevents.append(
                    ("recovery-record", args, kwargs)
                )
            ),
            "print": lambda *args, **kwargs: visibleevents.append(
                ("print", " ".join(str(value) for value in args))
            ),
            "angelprint": lambda *args, **kwargs: visibleevents.append(
                ("print", " ".join(str(value) for value in args))
            ),
            "time": types.SimpleNamespace(
                sleep=lambda delay: visibleevents.append(("sleep", delay))
            ),
        },
    )
    visiblerecoverynamespace["visibleframebufferrecoveryretry"](
        types.SimpleNamespace(pid=4242),
        3,
        1,
        "lockscreen-presentation",
        RuntimeError("framebuffer proof timed out"),
        animationproc=types.SimpleNamespace(pid=4343),
    )

    visibleeventnames = [event[0] for event in visibleevents]

    if visibleeventnames[:5] != [
        "stop-animation",
        "terminate",
        "console-mode",
        "console-mirror",
        "recovery-record",
    ]:
        raise SystemExit(
            "visible framebuffer recovery does not relinquish display ownership "
            "and restore inherited tty0 before reporting"
        )

    recoveryrecord = next(
        event for event in visibleevents if event[0] == "recovery-record"
    )

    if (
        recoveryrecord[1][:3]
        != ("framebuffer", 3, "visible-framebuffer-retry")
        or "cycle=1 trigger=lockscreen-presentation" not in recoveryrecord[1][3]
        or recoveryrecord[2] != {"capturegpu": False}
    ):
        raise SystemExit(
            "visible framebuffer recovery does not persist its retry cycle"
        )

    visibletext = "\n".join(
        event[1] for event in visibleevents if event[0] == "print"
    )

    if (
        "could not show the lock screen through the firmware framebuffer "
        "after 3 attempts" not in visibletext
        or "keep the text diagnostics visible for 15 seconds" not in visibletext
        or visibleevents[-1] != ("sleep", 15.0)
    ):
        raise SystemExit(
            "visible framebuffer recovery does not expose a bounded diagnostic dwell"
        )

    with tempfile.TemporaryDirectory() as temporary:
        temporaryroot = Path(temporary)
        capabilitypath = temporaryroot / "graphics-capability.json"
        unavailablepath = temporaryroot / "acceleration-unavailable.json"
        acceleratedpath = temporaryroot / "accelerated-ready.json"
        recoverynamespace = loadsourcefunctions(
            goddess,
            (
                "acceleratedreceipt",
                "graphicscapabilityreceipt",
                "accelerationunavailablereceipt",
                "waitacceleratedbootpresentation",
            ),
            {
                "json": json,
                "time": time,
                "GRAPHICSCAPABILITYPATH": str(capabilitypath),
                "ACCELERATIONUNAVAILABLEPATH": str(unavailablepath),
                "ACCELERATEDBOOTREADYPATH": str(acceleratedpath),
                "BOOTPRESENTATIONTIMEOUT": 0.1,
                "windowserverhello": lambda: True,
            },
        )
        process = types.SimpleNamespace(
            pid=3141,
            _t1os_windowserver_server="server-current",
            poll=lambda: None,
        )
        capability = {
            "format": 1,
            "windowserver_pid": 3141,
            "server": "server-current",
            "state": "acceleration-unavailable",
            "backend": "opengl",
            "renderer": "softpipe",
            "drm_driver": "virtio_gpu",
            "software_renderer": True,
            "hardware_accelerated": False,
            "gpu_compositor": True,
            "gpu_failed": False,
        }
        capabilitypath.write_text(json.dumps(capability), encoding="utf-8")

        if recoverynamespace["graphicscapabilityreceipt"](process) != capability:
            raise SystemExit("valid software-renderer capability receipt was rejected")

        for field, value in (
            ("windowserver_pid", 2718),
            ("server", "server-stale"),
            ("software_renderer", False),
            ("hardware_accelerated", True),
            ("gpu_compositor", False),
            ("gpu_failed", True),
        ):
            invalid = dict(capability)
            invalid[field] = value
            capabilitypath.write_text(json.dumps(invalid), encoding="utf-8")

            if recoverynamespace["graphicscapabilityreceipt"](process) is not None:
                raise SystemExit(
                    f"invalid software-renderer capability accepted field={field}"
                )

        acceleratedcandidate = dict(capability)
        acceleratedcandidate.update({
            "state": "accelerated-candidate",
            "renderer": "NVK AD104",
            "software_renderer": False,
            "hardware_accelerated": True,
        })
        capabilitypath.write_text(
            json.dumps(acceleratedcandidate),
            encoding="utf-8",
        )

        if (
            recoverynamespace["graphicscapabilityreceipt"](process)
            != acceleratedcandidate
        ):
            raise SystemExit("valid hardware-renderer candidate receipt was rejected")

        unavailable = {
            "format": 1,
            "windowserver_pid": 3141,
            "server": "server-current",
            "role": "boot animation",
            "backend": "opengl",
            "renderer": "softpipe",
            "drm_driver": "virtio_gpu",
            "software_renderer": True,
            "hardware_accelerated": False,
            "gpu_failed": False,
            "presentation_completed": True,
            "reason": "hardware-acceleration-unavailable",
        }
        unavailablepath.write_text(json.dumps(unavailable), encoding="utf-8")

        if (
            recoverynamespace["accelerationunavailablereceipt"](
                process,
                "boot animation",
            )
            != unavailable
        ):
            raise SystemExit("valid presentation capability receipt was rejected")

        deadprocess = types.SimpleNamespace(
            pid=3141,
            _t1os_windowserver_server="server-current",
            poll=lambda: 70,
        )
        animation = types.SimpleNamespace(poll=lambda: None)

        if (
            recoverynamespace["waitacceleratedbootpresentation"](
                deadprocess,
                animation,
            )
            != "acceleration-unavailable"
        ):
            raise SystemExit(
                "PID-bound capability receipt did not win the WindowServer "
                "exit race"
            )

    if "data=bytes(GPUGLYPHATLASSIZE * GPUGLYPHATLASSIZE * 4)" in graphicssource:
        raise SystemExit("glyph atlases still upload a full blank texture")

    for required in (
        "uploadwidth = width + 2",
        "uploadheight = height + 2",
        "x - 1",
        "y - 1",
    ):

        if required not in graphicssource:
            raise SystemExit(f"isolated glyph-atlas uploads are missing {required!r}")

    for required in (
        'data={"kind": "graphics"}',
        'if key.data.get("kind") == "graphics":',
        "kmsseteventdriven(True)",
        "def gpupresentationgate(",
        "kmspresentationstalled()",
        "recordinputlatency(msg)",
        "def queuetelemetrywrite(",
        "def telemetrywriterloop(",
        "os.replace(temporary, path)",
        "def materializeclientmotion(",
        "def flushclientmotions(",
        "CLIENTOUTBUFLIMIT",
        "setfocus(mappedfocusfallback(exclude=wid))",
        "def releasewindowinteraction(",
        'windows[gwid].get("mapped")',
        "input_p95_within_25ms",
        "pointer_events_coalesced",
        "serveio(timeout=remaining)",
        'if "nvk" in renderer.casefold():',
        "graphics bounded glyph prewarm skipped for NVK",
        "def gpustartupworkloadgate(",
        "graphics startup representative GPU workload complete",
        "def gpuwindowretainedsceneallowed(",
        "def gpuwindowretainedsystem(",
        "def gpuprewarmretainedsystemtexts(",
        "graphics retained system glyph uploads complete",
        'not bool(win.get("_managed_only", False))',
        "graphics system scene committed",
        "graphics startup compositor waiting for first mapped scene",
        "graphics first GPU frame begin",
        "graphics first GPU frame complete",
        "graphics retained system scene ready",
        "preserve=not (retainedsystemseen and requestedfull)",
        "def graphicspresentationpulse(",
        "kmswaitflip(waitpulse=graphicspresentationpulse)",
        "accelerated-boot-ready.json",
        "acceleration-unavailable.json",
        "graphics-capability.json",
        "class GPUAccelerationUnavailableError(RuntimeError):",
        "def writegraphicscapabilityreceipt(",
        '"accelerated-candidate"',
        '"presentation_completed": True',
        '"reason": "hardware-acceleration-unavailable"',
        "graphics hardware acceleration unavailable",
        "def writeacceleratedbootready(",
        "graphics first accelerated boot-animation presentation ready",
        "accelerated-lockscreen-ready.json",
        "lockscreen-ready.json",
        '"windowserver_pid": int(os.getpid())',
        "graphics first accelerated lock-screen presentation ready",
        "def writeframebufferlockscreenready(",
        "graphics first verified framebuffer lock-screen presentation ready",
        "WindowServer startup retained GPU presentation",
        'if "nvk" not in renderer.casefold():',
        "targetscale = min(1.0, 1280.0 / width, 720.0 / height)",
        "graphics refusing in-process backend substitution",
        "class GPUCompositorError(RuntimeError):",
        "GPU compositor failed; fresh WindowServer required",
        "GPUCOMPOSITORFAILUREEXIT = 72",
        "graphics init reported GPU device loss",
        "PRESENTATIONMAXINFLIGHT = 3",
        "def handlepresentationconfigure(state, descriptor):",
        "def handlepresentationframe(state, descriptor, fds):",
        "gpupresentationbuffercreate(descriptor, fds)",
        "gpupresentationbufferrelease(handle)",
        "def capturechromiumpresentation(win, stream, surface):",
        "def stagechromiumpresentations():",
        "def finishchromiumpresentations():",
        "consumer_release=drm-page-flip",
        "feedback_clock=drm-page-flip",
        '"generation": generation',
        '"sync_mode": "glfinish-producer-consumer"',
        "presentation-queue-full",
        "graphics video protocol error connection=",
        "Chromium RGB DMA-BUF generation cleared",
    ):

        if required not in windowserver:
            raise SystemExit(f"Window Server presentation integration is missing {required!r}")

    handoffstart = windowserver.index("def handlepresentationconfigure(")
    handoffend = windowserver.index("def handlepresentationframe(", handoffstart)
    handoffsource = windowserver[handoffstart:handoffend]
    gateindex = handoffsource.index("generation <= minimumgeneration")
    clearindex = handoffsource.index("clearpresentation(")
    targetindex = handoffsource.index("target = gputargetcreate(")
    installindex = handoffsource.index('state["presentation"] = {')
    if not gateindex < clearindex < targetindex < installindex:
        raise SystemExit(
            "Chromium RGB DMA-BUF generation replacement is not ordered after "
            "validation and old-generation retirement"
        )

    presentationdrawstart = windowserver.index(
        "if presentationsurface is not None:"
    )
    presentationdrawend = windowserver.index(
        "elif scenehandle is not None:",
        presentationdrawstart,
    )
    presentationdraw = windowserver[
        presentationdrawstart:presentationdrawend
    ]
    if (
        "capturechromiumpresentation(" not in presentationdraw
        or '"op": "presented"' in presentationdraw
        or "releasepresentationframe(presentationsurface)" not in presentationdraw
    ):
        raise SystemExit(
            "Chromium presentation feedback escaped before the DRM page flip"
        )

    finishstart = windowserver.index("def finishchromiumpresentations():")
    finishend = windowserver.index(
        "def videopromotepending(",
        finishstart,
    )
    finishsource = windowserver[finishstart:finishend]
    if (
        "if kmspresentationpending()" not in finishsource
        or '"op": "presented"' not in finishsource
        or "releasepresentationframe(surface)" not in finishsource
        or "videopromotepending(win, stream, surface)" not in finishsource
    ):
        raise SystemExit(
            "Chromium page-flip presentation completion is not ownership safe"
        )

    for required in (
        "class GPUDeviceLostError(RuntimeError):",
        "GL_RGB = 0x1907",
        "EGL_CONTEXT_LOST = 0x300E",
        "EGL_MIN_SWAP_INTERVAL = 0x303B",
        "EGL_MAX_SWAP_INTERVAL = 0x303C",
        "def _eglconfigurekmspresentation(",
        "_egl.eglSwapInterval",
        "def kmsmoderefreshrank(",
        "def kmsmodeproofkey(mode):",
        "currentresolutionindex",
        '"refresh_hz":',
        '"egl_swap_interval":',
        "_gpurecordkmsstage",
        "def kmsraise(error, operation):",
        "errno.ENODEV, errno.EIO",
        'storage="RGB"',
        "RGB copy-target textures do not accept RGBA CPU upload data",
        "default-framebuffer preservation copy",
        "backdrop-blur framebuffer preservation copy",
        "def gpuhealthsample(",
        '"gpu_health_samples":',
        "EGL_EXT_create_context_robustness",
        "EGL_CONTEXT_OPENGL_ROBUST_ACCESS_EXT",
        "EGL_LOSE_CONTEXT_ON_RESET_EXT",
        "glGetGraphicsResetStatusKHR",
        "openglloadresetstatus(required=_drmdriver == \"nouveau\")",
        'os.environ.pop("MESA_VK_ABORT_ON_DEVICE_LOSS", None)',
        'shadercache = "/.ephemeral/cache/graphics"',
        'nvidiacache = "/.ephemeral/cache/nvidia"',
        '"robust_context": bool(_glrobust)',
        'if requested == "opengl":',
        'raise RuntimeError("requested OpenGL/KMS backend is unavailable")',
        "def drmload(",
        'selected = str(device or DRMDEVICE or "").strip()',
        "candidates = [selected] if selected else drmcandidates()",
        "def kmsframebufferinit(",
        "def _kmsframebufferinitdevice(device, resize=False):",
        "resize=resize,",
        "kmsfindmode(\n        resize=True,\n        preserve_current=True,\n    )",
        "_kmsframebufferinitdevice(device, resize=True)",
        "def framebufferpresentationproof(",
        "def _legacyframebufferowners():",
        '"legacy_owner_connected"',
        "FRAMEBUFFERCONSOLEOWNED",
        '"legacy_console_owned"',
        '"legacy_pan_committed"',
        "_framebuffernativedrm = len(matchedowners) == 1",
        "FB_ACTIVATE_NOW",
        "DRM ownership enumeration did not complete",
        "framebuffer is neither a known firmware aperture",
        "native DRM fbdev launch lacks confirmed KD_TEXT ownership",
        "DRM_IOCTL_MODE_CREATE_DUMB",
        "DRM_IOCTL_MODE_MAP_DUMB",
        "software KMS buffer ready",
        "scanout=pending-first-written-frame",
        "software KMS written frame committed",
        "_eglextensions = frozenset()",
        "_eglextensionsqueried = False",
        "if not extensionadvertised and not nvidiafunctionpath:",
        "def _gpuvideomodifierimportavailable():",
        '"EGL_EXT_image_dma_buf_import_modifiers" in _eglextensions',
        "EGL init stage=extension-query state=begin",
        "skipped-nvidia-cold-start",
        "EGL init stage=config-choose state=begin",
        "EGL init stage=window-surface state=begin",
        "EGL init stage=context-create state=begin",
        "EGL init stage=make-current state=begin",
        "def _eglchoosexrgbconfig(configs, count):",
        "selectedvisual = int(visual.value)\n            break",
        "_egl.eglCreateWindowSurface(_egldisplay, _eglconfig",
        "_egl.eglCreateContext(_egldisplay, _eglconfig",
        'if _openglprovider == "nvidia":',
        "OpenGL init reported device loss",
        'os.environ.pop("__NV_GBM_TRACE_ENABLED", None)',
        "DRM resize aborted by device loss",
        'requested == "kms-framebuffer"',
        'raise RuntimeError("requested software KMS framebuffer is unavailable")',
        "def gpupresentationbufferavailable():",
        "def gpupresentationbuffercreate(descriptor, fds):",
        "def gpupresentationbufferrelease(handle):",
        'resource.get("presentation_dmabuf")',
        '"row_order": "top-left"',
        '"presentation_consumer_glfinish"',
        "DRM_FORMAT_XRGB8888",
        "modifier == DRM_FORMAT_MOD_INVALID",
        "offset != 0",
        "pitch < width * 4",
        "objectsize < pitch * height",
        "def _gpuvideosurfaceverticalcoordinates(resource):",
        "texturev0, texturev1 = _gpuvideosurfaceverticalcoordinates(resource)",
        "KMSMODEEXPLICIT = False",
        'str(_drmdriver or "").lower() in ("virtio_gpu", "vmwgfx")',
        "if dynamicpreferred and preferredindex is not None:",
        "elif currentindex is not None:",
        'else "active-framebuffer"',
        "graphics DRM mode change requested",
        "def gpuend(present=True, waitpulse=None, preserve=True):",
        "_gpuframesyncpersistent and preserve",
    ):

        if required not in graphicssource:
            raise SystemExit(f"NVK ordered-presentation integration is missing {required!r}")

    releasestart = graphicssource.index("def gpupresentationbufferrelease(handle):")
    releaseend = graphicssource.index("def _gpuvideomodifierimportavailable():", releasestart)
    releasesource = graphicssource[releasestart:releaseend]
    if "_gles.glFinish()" not in releasesource or "_gles.glFlush()" in releasesource:
        raise SystemExit(
            "Chromium DMA-BUF consumer release is not protected by a "
            "completed WindowServer GPU read"
        )

    for forbidden in (
        "EGLStream",
        "eglCreateStreamFromFileDescriptorKHR",
        "eglStreamConsumerAcquireKHR",
        "eglStreamConsumerReleaseKHR",
    ):
        if forbidden in windowserver or forbidden in graphicssource:
            raise SystemExit(
                f"retired Chromium presentation transport remains: {forbidden}"
            )

    if graphicssource.count("EGL_EXTENSIONS,") != 1:
        raise SystemExit(
            "EGL extension discovery escaped the single supervised "
            "provider-initialization boundary"
        )

    composestart = windowserver.index("def composeloop(")
    composeend = windowserver.index("except KeyboardInterrupt:", composestart)
    composesource = windowserver[composestart:composeend]
    animationindex = composesource.index("animating = gpuanimationsactive()")
    presentationindex = composesource.index(
        "if not gpupresentationgate(interval):",
        animationindex,
    )
    damageindex = composesource.index(
        "DAMAGERECTS.append(gpuvisualrect(win))",
        presentationindex,
    )
    paintindex = composesource.index("paintregions()", damageindex)

    if not animationindex < presentationindex < damageindex < paintindex:
        raise SystemExit(
            "event-driven presentation gate does not precede animation damage"
        )

    if "kmswaitflip(" in composesource:
        raise SystemExit(
            "steady compositor pacing still uses a blocking DRM flip wait"
        )

    if 'if any(st.get("outbuf") for st in clients.values()):' in windowserver:
        raise SystemExit("Window Server still busy-spins while a client is backpressured")

    for forbidden in (
        'zinkdebug.add("noreorder")',
        'os.environ["MESA_VK_ABORT_ON_DEVICE_LOSS"] = "1"',
        "selectedminimum",
    ):

        if forbidden in graphicssource:
            raise SystemExit(
                f"production NVK path still enables debugging workaround {forbidden!r}"
            )

    prewarmindex = windowserver.index("gpuprewarmretainedsystemtexts()", windowserver.index("def gpupaintregions("))
    beginindex = windowserver.index("gpubeginregions(requested", windowserver.index("def gpupaintregions("))

    if prewarmindex >= beginindex:
        raise SystemExit("retained-system glyph uploads still occur after the GPU frame begins")

    directdrawstart = windowserver.index("def gpudrawwindow(")
    directdrawend = windowserver.index("def gpueffectiverects(", directdrawstart)

    if "gpuprewarmwindowtexts(win)" in windowserver[directdrawstart:directdrawend]:
        raise SystemExit("retained-system drawing still uploads glyphs inside an active frame")

    gatestart = windowserver.index("def gpustartupworkloadgate(")
    gateend = windowserver.index("def composeloop(", gatestart)
    gatesource = windowserver[gatestart:gateend]
    uploadindex = gatesource.index("gpuprewarmtext(")
    renderbeginindex = gatesource.index("gpubeginregions(")

    if not uploadindex < renderbeginindex:
        raise SystemExit("representative startup uploads do not precede rendering")

    presentationindex = gatesource.index("if not gpuend(")

    if "gpuhealthcheck(" in gatesource[:presentationindex]:
        raise SystemExit(
            "representative startup workload still blocks on an intermediate glFinish"
        )

    if '".The One"' not in gatesource:
        raise SystemExit("startup workload does not prewarm the complete boot-animation glyph set")

    for required in (
        "preserveframe = dotcount == 3",
        "preserve=preserveframe",
        "preserve_copy={preserveframe}",
    ):
        if required not in gatesource:
            raise SystemExit(
                f"startup GPU workload does not exercise preservation path {required!r}"
            )

    flipindex = gatesource.index(
        "kmswaitflip(waitpulse=graphicspresentationpulse)",
        presentationindex,
    )
    presentationgateindex = gatesource.index(
        "WindowServer startup retained GPU presentation",
        flipindex,
    )

    if not presentationindex < flipindex < presentationgateindex:
        raise SystemExit(
            "startup GPU workload does not verify presentation before readiness"
        )

    if "recoverframebufferbackend(" in windowserver:
        raise SystemExit(
            "WindowServer still substitutes framebuffer inside a lost GPU owner"
        )

    retainedpaintstart = windowserver.index("def gpupaintregions(")
    retainedpaintend = windowserver.index("def gpustartupworkloadgate(", retainedpaintstart)
    retainedpaintsource = windowserver[retainedpaintstart:retainedpaintend]
    retainedpresentindex = retainedpaintsource.index(
        "preserve=not (retainedsystemseen and requestedfull)"
    )

    if "gpuhealthcheck(" in retainedpaintsource[:retainedpresentindex]:
        raise SystemExit(
            "retained system frame still blocks before its presentation barrier"
        )

    prewarmstart = windowserver.index("def gpuprewarmretainedsystemtexts(")
    prewarmend = windowserver.index("def gpupreparewindowscenes(", prewarmstart)

    if "gpuhealthcheck(" in windowserver[prewarmstart:prewarmend]:
        raise SystemExit("retained-system glyph prewarm still blocks on glFinish")

    cpupresentindex = windowserver.index(
        "gpresent()",
        windowserver.index("def paintregions("),
    )
    framebufferreceiptindex = windowserver.index(
        "writeframebufferlockscreenready(seen)",
        cpupresentindex,
    )

    if cpupresentindex >= framebufferreceiptindex:
        raise SystemExit(
            "framebuffer lock screen is acknowledged before its present completes"
        )

    if "if resize and preferredindex is not None:" in graphicssource:
        raise SystemExit(
            "physical KMS polling still overrides the active framebuffer mode"
        )

    if "graphics startup DRM mode stability check complete" not in windowserver:
        raise SystemExit(
            "Window Server does not complete its first mode poll before readiness"
        )

    for required in (
        "def waitacceleratedpresentation(",
        "waitacceleratedpresentation()",
        "initlock accelerated presentation barrier failed",
        "LOCKSCREENREADYPATH",
        "def lockscreenreceiptphysicallyverified(",
        "'virtio-resource-flush'",
    ):

        if required not in lockscreen:
            raise SystemExit(f"lock-screen accelerated presentation barrier is missing {required!r}")

    for required in (
        "WINDOWSERVERGPUFAILUREEXIT = 70",
        "WINDOWSERVERBACKENDINITFAILUREEXIT = 71",
        "WINDOWSERVERCOMPOSITORFAILUREEXIT = 72",
        "ACCELERATEDLOGINATTEMPTS = 3",
        "FRAMEBUFFERRECOVERYATTEMPTSPERCYCLE = 3",
        "KMSRECOVERYATTEMPTSPERCYCLE = 3",
        "FRAMEBUFFERRECOVERYVISIBLEDELAY = 15.0",
        "def launchwindowserver(backend):",
        "def accelerateddrmcandidates():",
        "def nextaccelerateddrmdevice():",
        "def nextkmsdrmdevice():",
        "environment['T1OS_DRM_DEVICE'] = drmdevice",
        "environment['__NV_GBM_TRACE_ENABLED'] = '1'",
        "environment['T1OS_FRAMEBUFFER_CONSOLE_OWNED'] = '1'",
        "'accelerated-device-candidate-retry'",
        "'kms-framebuffer'",
        "def replacewindowserver(backend):",
        "def acceleratedreceipt(",
        "def graphicscapabilityreceipt(",
        "def accelerationunavailablereceipt(",
        "def waitacceleratedbootpresentation(",
        "def acceleratedfailureaction(",
        "'accelerated-userspace-failure'",
        "preserving HDMI/KMS",
        "'acceleration-unavailable'",
        "'replacing owner with CPU-rendered KMS'",
        "'replacing owner with CPU-rendered KMS before animation'",
        "'boot-animation-client'",
        "'continuing directly to lock screen'",
        "'gpu-required-retry'",
        "def graphicsaccelerationrequired():",
        "def discardlegacyfirmwaregraphicsrecovery():",
        "persistent next-boot framebuffer recovery is disabled",
        "all driver reinitialization attempts",
        "accelerated lock-screen presentation failed after ",
        "'same-boot-cpu-kms-login'",
        "'software-kms-cycle-resume'",
        "'legacy-framebuffer-login'",
        "runstartup(startupenvironment, wsproc)",
        "except LoginPresentationFailure as error:",
        "non-graphics startup operation failed",
        "WindowServer exited before login completed",
        "while True:",
        "fallbackattempts += 1",
        "GRAPHICSSOFTWARELOG",
        "def _kernelringbuffer():",
        "def _gpufailurestate():",
        "def capturegpufailureevidence(payload):",
        "capturegpufailureevidence(payload)",
        "GRAPHICSDRIVERRPCTIMEOUT = 30.0",
        "GRAPHICSDRIVERRESPONSELIMIT = 65536",
        "def _windowservergraphicsdevices(windowserverproc):",
        "def _connectedgraphicsdevices():",
        "def _driverservergraphicsreset(bdf, driver):",
        "'request': 'RESET_GRAPHICS'",
        "connection.connect(DRIVERSERVERACCEPT)",
        "DriverServer reset response identity mismatch",
        "def recovergraphicsdriver(",
        "'driver-reset'",
        "authorized GPU reset failed after accelerated ",
        "capturegpu=False",
        "DISPLAYCONSOLEMODETIMEOUT = 2.0",
        "DISPLAYCONSOLEHELPERRETIRETIMEOUT = 5.0",
        "def waitdisplayconsolemodehelper(",
        "def firmwaregraphicsrecoveryrequested():",
        "def pinfirmwarerecoveryboot(root=EFIVARFSROOT):",
        "f'BootCurrent-{EFIVARGLOBALGUID}'",
        "f'BootNext-{EFIVARGLOBALGUID}'",
        "payload = struct.pack('<IH', 7, current)",
        "if verified != payload:",
        "def requestfirmwaregraphicsrecovery(reason, attempt):",
        "def drmscanoutnodeavailable():",
        "GRAPHICSDIAGNOSTICTIMEOUT = 3.0",
        "def capturewindowserverhangpid(pid, phase):",
        "def capturewindowserverhangbounded(process, phase):",
        "def capturegpufailureevidencebounded(payload):",
        "'--graphics-hang-capture'",
        "'--graphics-kernel-capture'",
        "WINDOWSERVERSOFTWARELOG",
        "def visibleframebufferrecoveryretry(",
        "'visible-framebuffer-retry'",
        "mirrordisplayconsole(force=True)",
        "'early-framebuffer-owner-retirement'",
        "'display-console-ownership'",
        "'display-console-contract'",
        "'driver-reset-refused'",
        "graphicsconsole = graphicsbackend != 'framebuffer'",
        "if not setdisplayconsolemode(graphicsconsole):",
        "init did not preserve T1OS_DISPLAY_CONSOLE_FD",
        "refusing to reset a display driver for an init hand-off failure",
        "while not stopbootanimation(earlybootanimation):",
        "'CPU-KMS WindowServer readiness device loss'",
        "'CPU-KMS lock-screen presentation device loss'",
    ):

        if required not in goddess:
            raise SystemExit(
                f"PID 1 graphics recovery policy is missing {required!r}"
            )

    recoverystart = goddess.index("def recovergraphicsdriver(")
    recoveryend = goddess.index(
        "\ndef acceleratedreceipt(",
        recoverystart,
    )
    recoverypolicy = goddess[recoverystart:recoveryend]
    missingdescriptor = recoverypolicy.index(
        "if DISPLAYCONSOLEFD is None:"
    )
    resetrequest = recoverypolicy.index(
        "_driverservergraphicsreset(bdf, driver)"
    )

    if missingdescriptor >= resetrequest:
        raise SystemExit(
            "graphics recovery can reset a live display driver before "
            "validating the inherited tty0 contract"
        )

    ownershipstart = goddess.index(
        "if not setdisplayconsolemode(graphicsconsole):"
    )
    ownershipend = goddess.index(
        "\n        # A failed animation is decorative failure",
        ownershipstart,
    )
    ownershippolicy = goddess[ownershipstart:ownershipend]

    if (
        ownershippolicy.index("if DISPLAYCONSOLEFD is None:")
        >= ownershippolicy.index("recovered = recovergraphicsdriver(")
    ):
        raise SystemExit(
            "display-console contract failure can reach GPU reset recovery"
        )

    goddessmainpolicy = goddess[goddess.index("def main():"):]

    if (
        goddessmainpolicy.count("visibleframebufferrecoveryretry(") != 3
        or goddessmainpolicy.count("framebuffercyclefailures += 1") != 3
        or goddessmainpolicy.count(
            ">= FRAMEBUFFERRECOVERYATTEMPTSPERCYCLE"
        ) != 3
    ):
        raise SystemExit(
            "PID 1 must expose bounded visible retry cycles from framebuffer "
            "readiness, console ownership, and lock-screen failures"
        )

    if goddess.count("recovergraphicsdriver(") != 7:
        raise SystemExit(
            "PID 1 must reinitialize the selected DRM driver after each of "
            "the accelerated, CPU-KMS, and blocked-console barriers"
        )

    if goddess.count("backend='kms-framebuffer'") != 2:
        raise SystemExit(
            "CPU-KMS readiness and lock-screen device loss do not both use "
            "the authorized exact-driver reset path"
        )

    earlyanimationstart = goddess.index(
        "earlybootanimation = startbootanimation('early-dots')"
    )
    driverbirth = goddess.index("birth(EARLYSYSTEMOPS)", earlyanimationstart)
    earlyretirementgate = goddess.index(
        "while not stopbootanimation(earlybootanimation):",
        driverbirth,
    )

    if not earlyanimationstart < driverbirth < earlyretirementgate:
        raise SystemExit(
            "the early framebuffer writer does not remain active while "
            "DriverServer begins discovery"
        )

    if (
        "self.early_boot_animation_retired = retireearlybootanimation()"
        not in driverserver
        or "statpath = PROCESSROOT / str(int(pid)) / 'stat'"
        not in driverserver
    ):
        raise SystemExit(
            "DriverServer does not retire the framebuffer writer at the "
            "native display-binding boundary"
        )

    consoleownershipgate = goddessmainpolicy.index(
        "if not setdisplayconsolemode(graphicsconsole):"
    )
    managedanimationstart = goddessmainpolicy.index(
        "bootanimation = startbootanimation('dots')",
        consoleownershipgate,
    )
    ownershipblock = goddessmainpolicy[
        consoleownershipgate:managedanimationstart
    ]

    if (
        "recovergraphicsdriver(" not in ownershipblock
        or "waitdisplayconsolemodehelper()" not in ownershipblock
        or "wsproc = replacewindowserver(graphicsbackend)" not in ownershipblock
        or "continue" not in ownershipblock
    ):
        raise SystemExit(
            "managed presentation can begin without clearing and confirming "
            "a blocked display-console transition"
        )

    if (
        "def _sysfswrite(" in goddess
        or "drivers/control/bus/pci/drivers" in goddess
        or goddess.count("if not recovered:") != 3
    ):
        raise SystemExit(
            "PID 1 can still bypass DriverServer or retry a poisoned GPU "
            "after an authoritative reset failure"
        )

    accelerationbranch = goddess.index(
        "if bootoutcome == 'acceleration-unavailable':"
    )
    devicefailurebranch = goddess.index(
        "if bootoutcome == 'gpu-failed':",
        accelerationbranch,
    )
    accelerationblock = goddess[accelerationbranch:devicefailurebranch]

    if (
        "recovergraphicsdriver(" in accelerationblock
        or "requestfirmwaregraphicsrecovery(" in accelerationblock
        or "graphicsbackend = 'kms-framebuffer'" not in accelerationblock
    ):
        raise SystemExit(
            "software-renderer capability fallback is still treated as GPU "
            "device loss"
        )

    for source, expected in (
        (goddess, "WINDOWSERVERREADYTIMEOUT = 30.0"),
        (goddess, "WINDOWSERVERREADYMAXTIME = 90.0"),
        (goddess, "BOOTPRESENTATIONTIMEOUT = 15.0"),
        (lockscreen, "WINDOWCREATETIMEOUT = 60.0"),
        (lockscreen, "def waitacceleratedpresentation(timeout=12.0):"),
        (startup, "WINDOWCREATETIMEOUT = 60.0"),
        (graphicsbuild, "-Dshader-cache=enabled"),
        (graphicsbuild, "-Dzstd=enabled"),
    ):

        if expected not in source:
            raise SystemExit(
                f"accelerated cold-start policy is missing {expected!r}"
            )

    if "hellofailures >= 2" in goddess:
        raise SystemExit(
            "PID 1 still kills a live WindowServer after transient hello failures"
        )

    if goddess.index("'boot-animation-client'") >= goddess.index(
        "'continuing directly to lock screen'"
    ):
        raise SystemExit("boot-animation-only failure is not logged before direct lock screen")

    goddessmain = goddess.index("def main():")
    presentationfailure = goddess.index(
        "except LoginPresentationFailure as error:",
        goddessmain,
    )
    nongraphicsfailure = goddess.index(
        "except subprocess.CalledProcessError as error:",
        presentationfailure,
    )
    catchallfailure = goddess.index(
        "except Exception as error:",
        nongraphicsfailure,
    )

    if not presentationfailure < nongraphicsfailure < catchallfailure:
        raise SystemExit(
            "non-graphics startup errors can incorrectly authorize graphics fallback"
        )

    inputserver = (
        projectroot / "source/build software/input/inputserver.py"
    ).read_text(encoding="utf-8")

    if 'ev["source_monotonic_ns"] = time.monotonic_ns()' not in inputserver:
        raise SystemExit("Input Server event timestamp telemetry is missing")

    for required in (
        'sel.register(fd, selectors.EVENT_READ, ("device", fd))',
        'elif kind == "device":',
        '"source_monotonic_ns": time.monotonic_ns()',
        "schedulepointerpossave()",
        "savepointerpos(force=True)",
        "flushclient(cid)",
        "while True:",
        "data = os.read(_KBD_FD, EV_READ_BYTES)",
        "chunk = os.read(fd, EV_READ_BYTES)",
    ):

        if required not in inputserver:
            raise SystemExit(f"Input Server low-latency integration is missing {required!r}")

    print("event-driven KMS presentation lifecycle passed")


if __name__ == "__main__":
    main()
