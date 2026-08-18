#!/usr/bin/env python3

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

import importlib.util
import ast
import json
import os
import pathlib
import re
import sys
import tempfile
import types


ROOT = pathlib.Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "source" / "drivers" / "settings" / "desktop compatibility.json"
MEDIA = ROOT / "source" / "build software" / "media" / "media.py"
GRAPHICS = ROOT / "source" / "build software" / "graphics" / "graphics.py"
PLAYER = ROOT / "source" / "build software" / "player" / "player.py"
CHROMIUM = ROOT / "source" / "build software" / "chromium" / "chromium.py"
CATALOGUE = ROOT / "source" / "catalogue" / "graphics"


def loadmodule(name, path):
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


def require(condition, detail):
    if not condition:
        raise RuntimeError(detail)


def main():
    audio_package = types.ModuleType("audio")
    audio_module = types.ModuleType("audio.audio")
    audio_module.LOSSLESSCODECS = set()
    audio_module.AUDIOSOCK = "/nonexistent/audio.sock"
    audio_package.audio = audio_module
    sys.modules["audio"] = audio_package
    sys.modules["audio.audio"] = audio_module
    if "fcntl" not in sys.modules:
        fcntl_module = types.ModuleType("fcntl")
        fcntl_module.LOCK_EX = 2
        fcntl_module.LOCK_SH = 1
        fcntl_module.LOCK_UN = 8
        fcntl_module.ioctl = lambda *args, **kwargs: 0
        fcntl_module.flock = lambda *args, **kwargs: 0
        sys.modules["fcntl"] = fcntl_module

    media = loadmodule("t1os_media_compatibility_test", MEDIA)
    graphicstree = ast.parse(GRAPHICS.read_text(encoding="utf-8"), str(GRAPHICS))
    colourfunction = next(
        node
        for node in graphicstree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_gpuvideocolourtransform"
    )
    graphicsnamespace = {}
    exec(
        compile(
            ast.Module(body=[colourfunction], type_ignores=[]),
            str(GRAPHICS),
            "exec",
        ),
        graphicsnamespace,
    )
    graphics = types.SimpleNamespace(
        _gpuvideocolourtransform=graphicsnamespace["_gpuvideocolourtransform"]
    )
    playertree = ast.parse(PLAYER.read_text(encoding="utf-8"), str(PLAYER))
    changefunction = next(
        node
        for node in playertree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "substantialvideochange"
    )
    playernamespace = {}
    exec(
        compile(
            ast.Module(body=[changefunction], type_ignores=[]),
            str(PLAYER),
            "exec",
        ),
        playernamespace,
    )
    chromiumtext = CHROMIUM.read_text(encoding="utf-8")
    chromiumtree = ast.parse(chromiumtext, str(CHROMIUM))
    chromiumfunctions = [
        node
        for node in chromiumtree.body
        if isinstance(node, ast.FunctionDef)
        and node.name in (
            "gpucandidateruntimeready",
            "chromiumdiagnosticswitches",
            "chromiumdiagnosticenvironment",
            "browsergpuarguments",
            "servicechromiumenvironment",
            "chromiumgraphicsenvironment",
            "rendererconfiguration",
            "requirevideoacceleration",
            "zygoteproviderstatus",
            "mergechromiumfeaturearguments",
        )
    ]
    chromiumnamespace = {
        "os": os,
        "PROCESSROOT": "",
        "RUNTIMEPROVIDER": "/.ephemeral/chromium/path-provider.so",
        "CHROMEEXECUTABLE": "/the one/software/chromium/program/chrome",
        "LIBVADRIVERPATH": "/the one/catalogue/graphics/drivers",
        "LIBRARIES": "/the one/software/chromium/libraries",
        "BASEGRAPHICSLIBRARYPATH":
            "/the one/software/chromium/libraries:/the one/catalogue/graphics",
        "MESAGRAPHICSLIBRARYPATH":
            "/the one/catalogue/graphics:"
            "/the one/software/chromium/libraries",
        "NVIDIAGRAPHICSLIBRARYPATH":
            "/the one/catalogue/graphics/nvidia:"
            "/the one/catalogue/graphics:"
            "/the one/software/chromium/libraries",
        "NVIDIAGPULIBRARYPATHVARIABLE":
            "SANDBOX_GPU_LD_LIBRARY_PATH",
        "NVIDIAGPUEGLVENDORVARIABLE":
            "SANDBOX_GPU_EGL_VENDOR_LIBRARY_FILENAMES",
        "NVIDIAGPUEGLEXTERNALVARIABLE":
            "SANDBOX_GPU_EGL_EXTERNAL_PLATFORM_CONFIG_DIRS",
        "NVIDIAGPUGBMBACKENDSPATHVARIABLE":
            "SANDBOX_GPU_GBM_BACKENDS_PATH",
        "NVIDIAGPUGBMBACKENDVARIABLE": "SANDBOX_GPU_GBM_BACKEND",
        "NVIDIAEGLVENDORFILE":
            "/the one/catalogue/graphics/nvidia/"
            "egl_vendor.d/10_nvidia.json",
        "NVIDIAGBMPATH": "/the one/catalogue/graphics/nvidia/gbm",
        "CHROMIUMLAUNCHVARIABLE": "T1OS_CHROMIUM_LAUNCH_ID",
        "NVIDIADIRECTVAAPIQUARANTINED": True,
        "NOUVEAURENDERER": "angle-swiftshader",
    }
    exec(
        compile(
            ast.Module(body=chromiumfunctions, type_ignores=[]),
            str(CHROMIUM),
            "exec",
        ),
        chromiumnamespace,
    )
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    decode = contract.get("video_decode", {})
    checks = {}

    require(
        media.MAXWIDTH == 3840
        and media.MAXHEIGHT == 2160
        and media.MAXFPS == 60.0
        and media.outputframerate(
            {"frame_rate": 60.0},
            3840,
            2160,
        ) == 60.0,
        "default playback policy must preserve 4K 60 fps video",
    )
    checks["default_playback_limit"] = [media.MAXWIDTH, media.MAXHEIGHT, media.MAXFPS]

    require(decode.get("api") == "vaapi", "video decode API must be VA-API")
    require(
        decode.get("surface_transport") == "drm-prime-2",
        "video surfaces must use DRM PRIME 2",
    )
    require(
        int(decode.get("maximum_in_flight", 0)) == media.VIDEOMAXFDS * 4,
        "the decoder and contract in-flight limits diverged",
    )

    expected = {
        "i915": ["iHD"],
        "xe": ["iHD"],
        "amdgpu": ["radeonsi"],
        "radeon": ["radeonsi", "r600"],
        "nvidia": ["nvidia"],
        "nvidia-drm": ["nvidia"],
        "nvidia_drm": ["nvidia"],
        "nouveau": ["nouveau"],
        "vmwgfx": ["vmwgfx"],
        "virtio_gpu": ["virtio_gpu"],
    }
    actual = {}
    for driver, candidates in expected.items():
        actual[driver] = [
            item["driver"]
            for item in media.vaapicandidates(driver, contractpath=str(CONTRACT))
        ]
        require(
            actual[driver] == candidates,
            f"{driver} routes to {actual[driver]}, expected {candidates}",
        )
    checks["backend_routing"] = actual

    # The built-in policy is the last line of defence if the installed JSON is
    # unreadable. Its NVIDIA aliases must remain fail closed too.
    missing_contract = ROOT / "source" / "drivers" / "settings" / (
        "missing desktop compatibility.json"
    )
    fallback_routing = {}
    for driver in ("nvidia", "nvidia-drm", "nvidia_drm"):
        fallback_routing[driver] = [
            item["driver"]
            for item in media.vaapicandidates(
                driver,
                contractpath=str(missing_contract),
            )
        ]
        require(
            fallback_routing[driver] == ["nvidia"],
            f"built-in {driver} route must select NVIDIA NVDEC",
        )
        require(
            media.hardwaredecoderequired(
                backend=driver,
                contractpath=str(missing_contract),
            ),
            f"built-in {driver} route must forbid software decode",
        )
    checks["fallback_backend_routing"] = fallback_routing

    normalize_driver = lambda value: str(value).strip().replace("-", "_")
    dependency_only = {
        normalize_driver(module)
        for module in contract.get("dependency_only_modules", [])
    }
    physical = {
        normalize_driver(module)
        for module in contract.get("module_groups", {}).get("graphics", [])
        if normalize_driver(module) not in dependency_only
    }
    routed = {
        normalize_driver(driver)
        for backend in decode.get("backends", [])
        for driver in backend.get("drm_drivers", [])
    }
    hardware_covered = {
        normalize_driver(driver)
        for backend in decode.get("backends", [])
        if backend.get("hardware_decode") != "unavailable"
        for driver in backend.get("drm_drivers", [])
    }
    require(
        physical <= routed,
        f"physical graphics drivers without video routing: {sorted(physical - routed)}",
    )
    require(
        {"vmwgfx", "virtio_gpu"} <= hardware_covered,
        "virtual GPU video routes are incomplete",
    )
    nvidia_backend = next(
        (
            backend
            for backend in decode.get("backends", [])
            if "nvidia" in {
                normalize_driver(driver)
                for driver in backend.get("drm_drivers", [])
            }
        ),
        None,
    )
    require(
        isinstance(nvidia_backend, dict)
        and nvidia_backend.get("hardware_decode") == "capability-probed"
        and nvidia_backend.get("decode_backend") == "nvdec-direct"
        and nvidia_backend.get("vaapi_drivers") == ["nvidia"]
        and nvidia_backend.get("software_fallback") is False
        and {
            "drivers/nvidia_drv_video.so",
            "nvidia/libcuda.so.1",
            "nvidia/libnvcuvid.so.1",
        } <= set(nvidia_backend.get("required_files", []))
        and "fail playback" in str(nvidia_backend.get("fallback", "")).lower(),
        "NVIDIA must require capability-probed NVDEC without CPU fallback",
    )
    require(
        media.defaultvideobackends()[3].get("software_fallback") is False,
        "the fallback video contract must also fail closed for NVIDIA",
    )
    require(
        media.hardwaredecoderequired(
            backend="nvidia_drm",
            contractpath=str(CONTRACT),
        )
        and media.hardwaredecoderequired(
            backend="nvidia-drm",
            contractpath=str(CONTRACT),
        )
        and not media.hardwaredecoderequired(
            backend="amdgpu",
            contractpath=str(CONTRACT),
        ),
        "NVIDIA fail-closed policy must survive DRM module-name normalization "
        "without depending on a video-surface socket",
    )
    nvidia_runtime = media.vaapiruntimeconfiguration(
        "nvidia",
        "nvidia",
        {"decode_backend": "nvdec-direct", "software_fallback": False},
    )
    nvidia_environment = media.videoaccelerationenvironment(
        nvidia_runtime,
        environment={
            "LD_LIBRARY_PATH": "/browser/libraries",
            "NVD_SINGLE_BUFFER": "1",
        },
        preload_path_provider=True,
    )
    require(
        nvidia_runtime.get("hardware_required") is True
        and nvidia_runtime.get("decode_backend") == "nvdec-direct"
        and nvidia_environment.get("LIBVA_DRIVER_NAME") == "nvidia"
        and nvidia_environment.get("NVD_BACKEND") == "direct"
        and nvidia_runtime.get("unset_environment") == ["NVD_SINGLE_BUFFER"]
        and "NVD_SINGLE_BUFFER" not in nvidia_environment
        and nvidia_environment.get("CUDA_DISABLE_PERF_BOOST") == "1"
        and nvidia_environment.get("CUDA_CACHE_PATH")
        == "/.ephemeral/cache/nvidia"
        and "NVD_LOG" not in nvidia_environment
        and nvidia_environment.get("LD_LIBRARY_PATH", "").startswith(
            media.NVIDIARUNTIMEPATH + ":" + media.GRAPHICSCATALOGUE
        )
        and nvidia_environment.get("LD_PRELOAD") == media.NVIDIAPATHPROVIDER
        and media.NVIDIAPATHPROVIDER
        == "/.ephemeral/graphics/nvidia-path-provider.so"
        and not any(
            character.isspace()
            for character in nvidia_environment.get("LD_PRELOAD", "")
        ),
        "NVIDIA VA-API process environment is incomplete",
    )
    probe_capability, probe_adapter_log, probe_stdout = (
        media.parsevideoaccelerationprobeoutput(
            b"10.125 adapter CUDA ready\n"
            b"10.250 adapter direct exporter ready\n"
            b'{"format":1,"vendor":"NVDEC direct","profiles":[]}\n'
        )
    )
    require(
        probe_capability == {
            "format": 1,
            "vendor": "NVDEC direct",
            "profiles": [],
        }
        and probe_adapter_log == (
            "10.125 adapter CUDA ready\n"
            "10.250 adapter direct exporter ready"
        )
        and probe_stdout.endswith('"profiles":[]}\n'),
        "NVIDIA probe logging obscures the final capability JSON",
    )
    failed_capability, failed_adapter_log, _ = (
        media.parsevideoaccelerationprobeoutput(
            b"11.000 Failed to load CUDA functions\n"
            b"11.001 Exporter failed\n"
        )
    )
    require(
        failed_capability is None
        and failed_adapter_log.endswith("Exporter failed"),
        "failed NVIDIA probe did not retain its adapter trace",
    )
    with tempfile.TemporaryDirectory(prefix="t1os-nvidia-probe-") as temporary:
        temporary = pathlib.Path(temporary)
        driverroot = temporary / "drivers"
        driverroot.mkdir()
        (driverroot / "nvidia_drv_video.so").write_bytes(b"driver")
        decoder = temporary / "t1-video-decode"
        decoder.write_bytes(b"decoder")
        rendernode = str(temporary / "renderD129")
        pathlib.Path(rendernode).write_bytes(b"render")
        previous_driverroot = media.LIBVADRIVERPATH
        previous_decoder = media.VIDEODECODERPATH
        previous_details = media.drmnodedetails
        previous_backend = media.drmbackend
        previous_candidates = media.vaapicandidates
        previous_run = media.subprocess.run
        observed_probe = {}

        def probedecoder(command, **arguments):
            observed_probe["command"] = command
            observed_probe["environment"] = dict(arguments.get("env") or {})
            return types.SimpleNamespace(
                returncode=0,
                stdout=(
                    b"12.000 Initialising NVIDIA VA-API Driver\n"
                    b'{"format":1,"vendor":"NVDEC direct",'
                    b'"profiles":[{"codec":"H264","name":"H264High"}]}\n'
                ),
                stderr=b"",
            )

        try:
            media.LIBVADRIVERPATH = str(driverroot)
            media.VIDEODECODERPATH = str(decoder)
            media.drmnodedetails = lambda node: {"node": node, "node_type": 2}
            media.drmbackend = lambda node: "nvidia"
            media.vaapicandidates = lambda backend, contractpath="": [{
                "driver": "nvidia",
                "class": "physical",
                "decode_backend": "nvdec-direct",
                "software_fallback": False,
            }]
            media.subprocess.run = probedecoder
            media.VIDEOACCELERATION.clear()
            measured_probe = media.videoacceleration(
                {},
                refresh=True,
                preferrednode=rendernode,
            )
        finally:
            media.LIBVADRIVERPATH = previous_driverroot
            media.VIDEODECODERPATH = previous_decoder
            media.drmnodedetails = previous_details
            media.drmbackend = previous_backend
            media.vaapicandidates = previous_candidates
            media.subprocess.run = previous_run
            media.VIDEOACCELERATION.clear()

        require(
            measured_probe
            and measured_probe.get("vendor") == "NVDEC direct"
            and observed_probe.get("environment", {}).get("NVD_LOG") == "1"
            and observed_probe.get("command") == [
                str(decoder),
                "--probe",
                "--device",
                rendernode,
            ],
            "NVIDIA adapter logging is not confined to the capability probe",
        )
    checks["nvidia_probe_diagnostics"] = True
    checks["routed_drm_drivers"] = sorted(routed)
    checks["hardware_decode_drm_drivers"] = sorted(hardware_covered)

    missing = []
    for backend in decode.get("backends", []):
        for relative in backend.get("required_files", []):
            if not (CATALOGUE / relative.removeprefix("drivers/")).is_file():
                candidate = ROOT / "source" / "catalogue" / "graphics" / relative
                if not candidate.is_file():
                    missing.append(relative)
    require(not missing, f"packaged video drivers are missing: {sorted(set(missing))}")
    checks["packaged_va_drivers"] = sorted({
        relative
        for backend in decode.get("backends", [])
        for relative in backend.get("required_files", [])
    })

    profiles = [
        (
            {
                "codec": "H264",
                "name": "H264High",
                "bit_depths": [8],
                "max_width": 4096,
                "max_height": 2304,
            },
            {
                "codec": "H264",
                "profile": "High",
                "bit_depth": 8,
                "width": 3840,
                "height": 2160,
            },
            True,
        ),
        (
            {
                "codec": "HEVC",
                "name": "HEVCMain10",
                "bit_depths": [10],
                "max_width": 4096,
                "max_height": 2304,
            },
            {
                "codec": "HEVC",
                "profile": "Main 10",
                "bit_depth": 10,
                "width": 3840,
                "height": 2160,
            },
            True,
        ),
        (
            {
                "codec": "VP9",
                "name": "VP9Profile2",
                "bit_depths": [10],
                "max_width": 4096,
                "max_height": 2304,
            },
            {
                "codec": "VP9",
                "profile": "Profile 2",
                "bit_depth": 10,
                "width": 3840,
                "height": 2160,
            },
            True,
        ),
        (
            {
                "codec": "AV1",
                "name": "AV1Profile0",
                "bit_depths": [8, 10],
                "max_width": 4096,
                "max_height": 2304,
            },
            {
                "codec": "AV1",
                "profile": "Main",
                "bit_depth": 10,
                "width": 3840,
                "height": 2160,
            },
            True,
        ),
        (
            {
                "codec": "HEVC",
                "name": "HEVCMain",
                "bit_depths": [8],
                "max_width": 4096,
                "max_height": 2304,
            },
            {
                "codec": "HEVC",
                "profile": "Main 10",
                "bit_depth": 10,
                "width": 3840,
                "height": 2160,
            },
            False,
        ),
        (
            {
                "codec": "H264",
                "name": "H264High",
                "bit_depths": [8],
                "max_width": 1920,
                "max_height": 1080,
            },
            {
                "codec": "H264",
                "profile": "High",
                "bit_depth": 8,
                "width": 3840,
                "height": 2160,
            },
            False,
        ),
    ]
    for capability, stream, wanted in profiles:
        require(
            media.vaapiprofilematches(capability, stream) is wanted,
            f"profile match for {capability['name']} and {stream} was not {wanted}",
        )
    checks["exact_profile_matching"] = len(profiles)

    require(
        media.fitsize(3840, 2160, 800, 600) == [800, 450],
        "4K window scaling did not preserve display aspect",
    )
    require(
        media.fitsize(3840, 2160, 3840, 2160) == [3840, 2160],
        "full-screen 4K sizing was capped below the framebuffer",
    )
    checks["adaptive_surface_sizes"] = [[800, 450], [3840, 2160]]
    substantial = playernamespace["substantialvideochange"]
    require(
        not substantial([800, 450], [900, 500])
        and substantial([800, 450], [1280, 720])
        and substantial([1280, 720], [800, 450]),
        "adaptive resize hysteresis is invalid",
    )
    checks["adaptive_resize_hysteresis"] = True

    offset, rows = graphics._gpuvideocolourtransform({
        "color": {"space": 1, "range": 1},
        "bit_depth": 10,
    })
    require(
        abs(offset[0] - (64.0 / 1023.0)) < 1e-9
        and rows[0][0] > 1.0
        and rows[0][2] > 1.5,
        "10-bit limited-range BT.709 transform is invalid",
    )
    checks["gpu_colour_transform"] = "BT.709 limited 10-bit"

    chromium_environment = chromiumnamespace[
        "servicechromiumenvironment"
    ]({
        "DISPLAY": ":99",
        "LIBVA_DRIVER_NAME": "nvidia",
        "NVD_BACKEND": "direct",
        "CUDA_DISABLE_PERF_BOOST": "1",
        "T1OS_CHROMIUM_NVIDIA_DEBUG": "1",
    })
    require(
        chromium_environment == {"DISPLAY": ":99"},
        "Chromium retained legacy NVIDIA decode authority",
    )
    chromium_graphics_environment = chromiumnamespace[
        "chromiumgraphicsenvironment"
    ]({
        "DISPLAY": ":99",
        "LD_LIBRARY_PATH": chromiumnamespace["BASEGRAPHICSLIBRARYPATH"],
        "LIBGL_DRIVERS_PATH": chromiumnamespace["LIBRARIES"],
    }, "nvidia_drm")
    require(
        chromium_graphics_environment.get("LD_LIBRARY_PATH")
        == chromiumnamespace["BASEGRAPHICSLIBRARYPATH"]
        and chromium_graphics_environment.get(
            chromiumnamespace["NVIDIAGPULIBRARYPATHVARIABLE"]
        ) == chromiumnamespace["NVIDIAGRAPHICSLIBRARYPATH"]
        and chromium_graphics_environment.get(
            chromiumnamespace["NVIDIAGPUEGLVENDORVARIABLE"]
        ) == chromiumnamespace["NVIDIAEGLVENDORFILE"]
        and chromium_graphics_environment.get(
            chromiumnamespace["NVIDIAGPUGBMBACKENDSPATHVARIABLE"]
        )
        == chromiumnamespace["NVIDIAGBMPATH"]
        and "__EGL_VENDOR_LIBRARY_FILENAMES"
        not in chromium_graphics_environment
        and "GBM_BACKENDS_PATH" not in chromium_graphics_environment
        and "LIBGL_DRIVERS_PATH" not in chromium_graphics_environment,
        "Chromium NVIDIA EGL rendering still resolves through Mesa",
    )
    acceleration = {
        "driver": "nvidia",
        "hardware_required": True,
    }
    require(
        "def t1osmediadecoderconfiguration(" in chromiumtext
        and 'MEDIADECODEPROTOCOL = "T1MD"' in chromiumtext
        and 'MEDIADECODEFEATURE = "T1OSVideoDecoder"' in chromiumtext
        and 'MEDIADECODESOCKETSWITCH = "--t1os-video-decode-socket="' in chromiumtext
        and 'MEDIADECODEOUTPUTVARIABLE = "T1OS_MEDIA_DECODE_OUTPUT"' in chromiumtext
        and 'MEDIADECODEOUTPUTSWITCH = "--t1os-video-decode-output="' in chromiumtext
        and 'PRESENTATIONFEATURE = "T1OSNvidiaPresentation"' in chromiumtext
        and 'def nvidiapresentationenabled():' in chromiumtext
        and '"t1os.chromium.nvidia-presentation=0"' in chromiumtext
        and 'capability.get("brokered_socket") is not True' in chromiumtext
        and "servicechromiumenvironment(environment)" in chromiumtext
        and re.search(
            r"expected_gpu_library_path\s*=\s*chrome_environment\software\.get\(\s*"
            r"NVIDIAGPULIBRARYPATHVARIABLE,\s*"
            r"MESAGRAPHICSLIBRARYPATH\s*"
            r"if presentationbridge and not proprietarynvidia\s*"
            r"else \"\",\s*\)",
            chromiumtext,
        ),
        "Chromium hardware decode is not bound to the brokered T1MD service",
    )
    checks["chromium_hardware_decode_route"] = {
        "service_switch": "t1os-video-decode-socket",
        "protocol": "T1MD/1",
        "browser_brokered": True,
        "nvidia_direct_vaapi_quarantined": True,
        "legacy_vaapi": False,
    }
    browser_gpu_arguments = chromiumnamespace["browsergpuarguments"]
    nvidia_gpu_arguments = browser_gpu_arguments("nvidia_drm", acceleration)
    nvidia_service_arguments = browser_gpu_arguments(
        "nvidia_drm",
        None,
        servicedecoder={"feature": "T1OSVideoDecoder"},
    )
    nvidia_stable_arguments = browser_gpu_arguments(
        "nvidia_drm",
        None,
        servicedecoder={"feature": "T1OSVideoDecoder"},
        presentationbridge=False,
    )
    stable_renderer, stable_renderer_arguments = chromiumnamespace[
        "rendererconfiguration"
    ]("nvidia_drm", presentationbridge=False)
    merged_feature_arguments = chromiumnamespace[
        "mergechromiumfeaturearguments"
    ]([
        "--enable-features=T1OSVideoDecoder",
        "--enable-features=T1OSNvidiaPresentation",
        "--disable-features=VaapiOnNvidiaGPUs",
        "--disable-features=Vulkan,VaapiOnNvidiaGPUs",
    ])
    require(
        "--disable-gpu-sandbox" not in nvidia_gpu_arguments
        and '"--disable-gpu-sandbox"' not in chromiumtext
        and "--no-zygote" not in nvidia_gpu_arguments
        and "--no-unsandboxed-zygote" not in nvidia_gpu_arguments
        and "--use-gl=egl" in nvidia_gpu_arguments
        and "--disable-accelerated-video-decode" in nvidia_gpu_arguments
        and "--disable-accelerated-video-decode"
        not in nvidia_service_arguments
        and "--disable-accelerated-video-decode"
        not in nvidia_stable_arguments
        and "--use-gl=egl" not in nvidia_stable_arguments
        and "--ignore-gpu-blocklist" not in nvidia_stable_arguments
        and stable_renderer == "angle-swiftshader-rollback"
        and "--use-gl=angle" in stable_renderer_arguments
        and "--use-angle=swiftshader" in stable_renderer_arguments
        and merged_feature_arguments == [
            "--enable-features=T1OSVideoDecoder,T1OSNvidiaPresentation",
            "--disable-features=VaapiOnNvidiaGPUs,Vulkan",
        ]
        and (
            "--disable-features=AcceleratedVideoDecodeLinuxGL,"
            "VaapiOnNvidiaGPUs"
        )
        in nvidia_service_arguments
        and chromiumnamespace["NVIDIADIRECTVAAPIQUARANTINED"]
        and "chromium-sandbox+architect-policy" in chromiumtext,
        "Chromium NVIDIA GPU launch or sandbox policy is inconsistent",
    )
    checks["chromium_nvidia_gpu_containment"] = {
        "gpu_process": "chromium-sandbox+architect-policy",
        "renderer": "chromium-sandbox+architect-policy",
        "gpu_launch": "direct measured helper; Chromium kGpu sandbox",
        "nvidia_web_decode": "t1md-dmabuf-or-linear; direct-vaapi-disabled",
        "production_renderer": "native-egl-opengl",
        "rollback_renderer": "angle-swiftshader-rollback",
        "unsupported_switches": [],
    }
    candidate_ready = chromiumnamespace["gpucandidateruntimeready"]
    require(
        not candidate_ready(True, False, False, True)
        and not candidate_ready(False, True, True, True)
        and not candidate_ready(True, True, True, False)
        and not candidate_ready(True, True, True, True, False)
        and candidate_ready(True, True, True, True)
        and 'CHROMIUMLAUNCHVARIABLE = "T1OS_CHROMIUM_LAUNCH_ID"' in chromiumtext
        and "chrome_environment[CHROMIUMLAUNCHVARIABLE] = launch_id" in chromiumtext
        and '"launch_id": launch_id' in chromiumtext
        and "candidate_runtime_ready" in chromiumtext
        and "processidentity=dropengineidentity" in chromiumtext
        and "probetimeout=CHROMEPROBETIMEOUT" in chromiumtext,
        "Chromium GPU readiness is not scoped to one measured launch/process",
    )
    expected_library_path = (
        "/the one/software/chromium/libraries:"
        "/the one/catalogue/graphics"
    )
    legacy_decoder_environment = {
        "LIBVA_DRIVER_NAME=nvidia",
        "LIBVA_DRIVERS_PATH=/the one/catalogue/graphics/drivers",
        "NVD_BACKEND=direct",
        "NVD_FORCE_INIT=1",
        "NVD_LOG=1",
        "NVD_STATS=1",
        "LIBVA_MESSAGING_LEVEL=2",
        "CUDA_DISABLE_PERF_BOOST=1",
        "T1OS_CHROMIUM_NVIDIA_DEBUG=1",
    }
    with tempfile.TemporaryDirectory(prefix="t1os-chromium-processes-") as temporary:
        processroot = pathlib.Path(temporary)
        chromiumnamespace["PROCESSROOT"] = str(processroot)

        def writegpuprocess(process, environment, provider=False):
            processpath = processroot / str(process)
            processpath.mkdir()
            (processpath / "cmdline").write_bytes(
                b"/the one/software/chromium/program/chrome\0"
                b"--type=gpu-process\0"
            )
            (processpath / "maps").write_bytes(
                (
                    b"7f000000-7f001000 r-xp "
                    + chromiumnamespace["RUNTIMEPROVIDER"].encode()
                    + b"\n"
                )
                if provider
                else b"7f000000-7f001000 r-xp /unrelated/library.so\n"
            )
            (processpath / "environ").write_bytes(
                b"\0".join(
                    str(value).encode()
                    for value in sorted(environment)
                )
                + b"\0"
            )

        launch_a = "launch-a"
        marker_a = f"T1OS_CHROMIUM_LAUNCH_ID={launch_a}"
        writegpuprocess(101, {marker_a}, provider=True)
        writegpuprocess(102, legacy_decoder_environment | {marker_a})
        writegpuprocess(
            103,
            {marker_a, f"LD_LIBRARY_PATH={expected_library_path}"},
        )
        split_status = chromiumnamespace["zygoteproviderstatus"](
            expected_library_path,
            launch_a,
        )
        require(
            split_status["gpu_provider"]
            and split_status["gpu_environment"]
            and split_status["gpu_library_path"]
            and not split_status["gpu_runtime_ready"],
            "Chromium combined runtime properties from different GPU processes",
        )

        launch_b = "launch-b"
        marker_b = f"T1OS_CHROMIUM_LAUNCH_ID={launch_b}"
        writegpuprocess(
            104,
            {
                marker_b,
                f"LD_LIBRARY_PATH={expected_library_path}",
            },
            provider=True,
        )
        mismatch_status = chromiumnamespace["zygoteproviderstatus"](
            expected_library_path,
            launch_a,
        )
        matching_status = chromiumnamespace["zygoteproviderstatus"](
            expected_library_path,
            launch_b,
        )
        require(
            not mismatch_status["gpu_runtime_ready"]
            and matching_status["gpu_runtime_ready"]
            and matching_status["gpu_runtime_pid"] == 104
            and matching_status["gpu_launch_scope"],
            "Chromium accepted a GPU process from another browser launch",
        )

        gpu_library_path = chromiumnamespace["NVIDIAGRAPHICSLIBRARYPATH"]
        launch_c = "launch-c"
        marker_c = f"T1OS_CHROMIUM_LAUNCH_ID={launch_c}"
        writegpuprocess(
            105,
            {marker_c, f"LD_LIBRARY_PATH={gpu_library_path}"},
            provider=True,
        )
        incomplete_gpu_status = chromiumnamespace["zygoteproviderstatus"](
            expected_library_path,
            launch_c,
            0,
            gpu_library_path,
        )
        launch_d = "launch-d"
        marker_d = f"T1OS_CHROMIUM_LAUNCH_ID={launch_d}"
        writegpuprocess(
            106,
            {
                marker_d,
                f"LD_LIBRARY_PATH={gpu_library_path}",
                "__EGL_VENDOR_LIBRARY_FILENAMES="
                + chromiumnamespace["NVIDIAEGLVENDORFILE"],
                "__EGL_EXTERNAL_PLATFORM_CONFIG_DIRS="
                + chromiumnamespace["NVIDIAGBMPATH"],
                "GBM_BACKENDS_PATH=" + chromiumnamespace["NVIDIAGBMPATH"],
                "GBM_BACKEND=nvidia-drm",
            },
            provider=True,
        )
        complete_gpu_status = chromiumnamespace["zygoteproviderstatus"](
            expected_library_path,
            launch_d,
            0,
            gpu_library_path,
        )
        require(
            not incomplete_gpu_status["gpu_runtime_ready"]
            and complete_gpu_status["gpu_runtime_ready"]
            and complete_gpu_status["gpu_graphics_environment"],
            "Chromium accepted an NVIDIA GPU without its exact EGL/GBM contract",
        )
        incomplete_candidate = next(
            candidate
            for candidate in incomplete_gpu_status["candidates"]
            if candidate["pid"] == 105
        )
        complete_candidate = next(
            candidate
            for candidate in complete_gpu_status["candidates"]
            if candidate["pid"] == 106
        )
        require(
            incomplete_candidate["graphics_environment_source"] == "missing"
            and complete_candidate["graphics_environment_source"]
            == "live-environment"
            and all(complete_candidate["live_gpu_graphics"].values())
            and complete_candidate["switches"] == ["--type=gpu-process"]
            and not any(
                value.startswith("T1OS_CHROMIUM_LAUNCH_ID=")
                for value in complete_candidate["library_environment"]
            ),
            "Chromium GPU diagnostics omit exact fields or persist launch credentials",
        )
    require(
        "def capturewindowgraphicscontract(" in chromiumtext
        and "def validatedwindowgraphicscontract(" in chromiumtext
        and 'surfaces.get("render_identity")' in chromiumtext
        and "stat.S_ISCHR(status.st_mode)" in chromiumtext
        and "int(os.major(status.st_rdev)) != expectedmajor" in chromiumtext
        and "int(os.minor(status.st_rdev)) != expectedminor" in chromiumtext,
        "Chromium does not validate WindowServer's selected render-node identity",
    )
    require(
        'CHROMIUMVIDEOCODECS = frozenset(("H264", "VP8", "VP9", "AV1"))'
        in chromiumtext
        and "browsercodecs = measuredcodecs & CHROMIUMVIDEOCODECS"
        in chromiumtext
        and "or not browsercodecs" in chromiumtext,
        "Chromium accepts a VA-API probe without any supported web-video codec",
    )
    checks["chromium_launch_scoped_gpu_runtime"] = {
        "marker": "T1OS_CHROMIUM_LAUNCH_ID",
        "minimum_probe_seconds": 15,
        "minimum_runtime_seconds": 15,
        "windowserver_render_identity": True,
    }

    result = {
        "format": 1,
        "passed": True,
        "checks": checks,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(json.dumps({
            "format": 1,
            "passed": False,
            "error": str(error),
        }, indent=2, sort_keys=True))
        raise SystemExit(1)
