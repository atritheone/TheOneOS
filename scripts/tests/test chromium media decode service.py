"""Focused policy and lifecycle tests for T1OS's Chromium media service."""

from __future__ import annotations

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
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import types


ROOT = Path(__file__).resolve().parents[2]
CHROMIUM = ROOT / "source/build software/chromium/chromium.py"
AUDIO_SERVER = ROOT / "source/build software/audio/audioserver.py"
DRIVER_SERVER = ROOT / "source/build software/drivers/driverserver.py"
CHROMIUM_OVERLAY_APPLIER = (
    ROOT / "resource/chromium-source/150.0.7871.181/apply.py"
)
GODDESS = ROOT / "source/build software/GODDESS/GODDESS.py"
MEDIA_WORKER = ROOT / "source/native/video/t1_media_decode_worker.c"
MEDIA_DAEMON = ROOT / "source/native/video/t1_media_decoded.c"
GRAPHICS_BUILD = ROOT / "scripts/build/build graphics runtime.ps1"
NVIDIA_PLANAR_PATCH = (
    ROOT
    / "resource/patches/nvidia vaapi planar export"
    / "apply_t1os_planar_export.py"
)


def loadfunctions(
    name: str,
    path: Path,
    functions: set[str],
    constants: dict[str, object],
):
    """Load isolated functions without executing either boot-time module."""

    source = path.read_text(encoding="utf-8")
    parsed = ast.parse(source, filename=str(path))
    selected = [
        node
        for node in parsed.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in functions
    ]
    missing = functions.difference(
        node.name for node in selected
    )
    if missing:
        raise RuntimeError(
            f"{path} is missing tested functions: {sorted(missing)}"
        )

    module = types.ModuleType(name)
    module.__dict__.update({
        "__file__": str(path),
        "json": json,
        "re": re,
        "os": types.SimpleNamespace(
            environ=os.environ,
            fdopen=os.fdopen,
            fsync=os.fsync,
            getpid=os.getpid,
            kill=os.kill,
            lstat=os.lstat,
            makedirs=os.makedirs,
            chmod=os.chmod,
            open=os.open,
            O_CREAT=os.O_CREAT,
            O_EXCL=os.O_EXCL,
            O_WRONLY=os.O_WRONLY,
            path=os.path,
            replace=os.replace,
            stat=os.stat,
            unlink=os.unlink,
        ),
        "stat": stat,
        "statmodule": stat,
        **constants,
    })
    extracted = ast.Module(body=selected, type_ignores=[])
    ast.fix_missing_locations(extracted)
    exec(compile(extracted, str(path), "exec"), module.__dict__)
    return module


def require(condition: bool, message: str):
    if not condition:
        raise RuntimeError(message)


def chromiumtests(chromium):
    overlay_applier = CHROMIUM_OVERLAY_APPLIER.read_text(encoding="utf-8")
    launcher_source = CHROMIUM.read_text(encoding="utf-8")
    audio_server_source = AUDIO_SERVER.read_text(encoding="utf-8")
    driver_server_source = DRIVER_SERVER.read_text(encoding="utf-8")
    require(
        chromium.audiolatencymilliseconds(1920, 48000) == 10.0
        and "AUDIOCHUNKBYTES = 480 * 2 * 2" in launcher_source
        and "AUDIOSTREAMBUFFERSECONDS = 0.04" in launcher_source
        and "AUDIOSTREAMPREBUFFERMS = 20" in launcher_source
        and "stopcheck=AUDIOSTOP.is_set" in launcher_source
        and "chromium audio relay healthy" in launcher_source,
        "Chromium audio relay no longer has the bounded low-latency policy",
    )
    require(
        "INTERACTIVESTREAMMINBUFFERSECONDS = 0.04" in audio_server_source
        and "max(INTERACTIVESTREAMMINBUFFERSECONDS, requestedbufsec)"
        in audio_server_source
        and "if latencyclass == 'interactive'\n        else 0.25"
        in audio_server_source,
        "AudioServer restored the hidden 250 ms minimum browser queue",
    )
    require(
        "def configureprofilesession(" in launcher_source
        and 'session["restore_on_startup"] = value' in launcher_source
        and "single_root=presentationbridge" in launcher_source
        and "--disable-restore-session-state" not in launcher_source,
        "single-root presentation still relies on an unknown Chromium switch",
    )
    require(
        'std::getenv(\\"T1OS_PRESENTATION_BRIDGE\\")' in overlay_applier,
        "the T1OS mailbox converter no longer detects the presentation bridge",
    )
    require(
        "si_format->SetPrefersExternalSampler()" in overlay_applier
        and "import=external-yuv" in overlay_applier,
        "the T1OS NVDEC path no longer selects a composed external YUV image",
    )
    require(
        "import=external-yuv" in overlay_applier
        and "import=chromium-planar" not in overlay_applier,
        "the T1OS NVDEC path is not selecting external-sampler composition",
    )
    require(
        "native pixmap import=direct-dmabuf" in overlay_applier,
        "the external-YUV import no longer bypasses the invalid GBM re-import",
    )
    frame_hot_messages = (
        "T1OS_MEDIA_DECODER SharedImage",
        "T1OS_MEDIA_DECODER EGL external plane=",
        "T1OS_MEDIA_DECODER EGL plane=",
        "T1OS_MEDIA_DECODER native pixmap import=direct-dmabuf",
    )
    require(
        all(
            f'VLOG(2) << \\"{message}' in overlay_applier
            for message in frame_hot_messages
        )
        and all(
            f'LOG(INFO) << \\"{message}' not in overlay_applier
            for message in frame_hot_messages
        ),
        "frame-hot Chromium decoder diagnostics are enabled at INFO level",
    )
    require(
        "AUDIOTELEMETRYINTERVAL = 30.0" in audio_server_source
        and "AUDIORELAYLOGINTERVAL = 30.0" in launcher_source,
        "Chromium/audio periodic telemetry is not production-throttled",
    )
    require(
        "previousfrontendnodes" in driver_server_source
        and "retainedservicenodes" in driver_server_source,
        "NVIDIA UVM reconciliation can still emit readiness every tick",
    )
    require(
        "bool t1os_chroma_is_drm_rg = false;" in overlay_applier
        and "handle.t1os_chroma_is_drm_rg = chroma_is_drm_rg;"
        in overlay_applier
        and "clone.t1os_chroma_is_drm_rg = handle.t1os_chroma_is_drm_rg;"
        in overlay_applier
        and "bool t1os_chroma_is_drm_rg@3;" in overlay_applier
        and "data.t1os_chroma_is_drm_rg()" in overlay_applier
        and "producer_handle.t1os_chroma_is_drm_rg" in overlay_applier
        and "supports_zero_copy_webgpu_import = chroma_is_drm_rg"
        not in overlay_applier,
        "the producer's exact DRM chroma ordering is not preserved for EGL import",
    )
    require(
        "the late path must not notify twice" in overlay_applier
        and "decoder_support_notifier_.is_notified()" in overlay_applier,
        "the seek/GPU-loss decoder readiness race guard is missing",
    )
    service = {
        "feature": chromium.MEDIADECODEFEATURE,
        "socket": chromium.MEDIADECODESOCKET,
        "protocol": chromium.MEDIADECODEPROTOCOL,
        "protocol_version": chromium.MEDIADECODEPROTOCOLVERSION,
        "service_pid": 712,
        "brokered_socket": True,
    }
    defaultarguments = chromium.browsergpuarguments("nvidia", None)
    servicearguments = chromium.browsergpuarguments(
        "nvidia",
        None,
        servicedecoder=service,
    )
    stablearguments = chromium.browsergpuarguments(
        "nvidia",
        None,
        servicedecoder=service,
        presentationbridge=False,
    )
    stablefallbackarguments = chromium.browsergpuarguments(
        "nvidia",
        None,
        presentationbridge=False,
    )
    require(
        "--disable-accelerated-video-decode" in defaultarguments,
        "software decode is not retained when no safe NVIDIA decoder is ready",
    )
    require(
        "--disable-accelerated-video-decode" not in servicearguments,
        "the global decode kill flag remains active for the T1OS service",
    )
    require(
        (
            "--disable-features=AcceleratedVideoDecodeLinuxGL,"
            "VaapiOnNvidiaGPUs"
        )
        in servicearguments,
        "the unsafe Chromium NVIDIA VA-API route was re-enabled",
    )
    require(
        "--no-unsandboxed-zygote" not in defaultarguments
        and "--no-unsandboxed-zygote" not in servicearguments
        and "--no-unsandboxed-zygote" not in stablearguments,
        "native NVIDIA presentation does not use the measured direct GPU helper",
    )
    require(
        "--disable-accelerated-video-decode" not in stablearguments
        and "--use-gl=egl" not in stablearguments
        and "--ignore-gpu-blocklist" not in stablearguments,
        "the linear T1MD route is still coupled to NVIDIA EGL presentation",
    )
    require(
        "--disable-accelerated-video-decode" in stablefallbackarguments,
        "software decode is not the fallback when neither T1MD nor native import is ready",
    )
    require(
        chromium.t1osmediadecoderarguments(service)
        == [
            "--enable-features=T1OSVideoDecoder",
            "--t1os-video-decode-socket=/.ephemeral/media/decode.sock",
            "--t1os-video-decode-output=linear-memory",
        ],
        "an omitted T1MD output mode does not fail safe to linear memory",
    )
    dma_service = {**service, "output_mode": "dma-buf"}
    require(
        chromium.t1osmediadecoderarguments(dma_service)[-1]
        == "--t1os-video-decode-output=dma-buf",
        "an explicitly proven DMA-BUF output mode is not preserved",
    )
    debugvariable = chromium.CHROMIUMDEBUGVARIABLE
    previousdebug = os.environ.get(debugvariable)
    previousdiagnosticpolicy = chromium.HARDWAREDIAGNOSTICPOLICY
    previousdiagnosticfallback = chromium.HARDWAREDIAGNOSTICFALLBACK
    previousdebugkernel = chromium.kernelcommandlineoption
    with tempfile.TemporaryDirectory() as temporary:
        diagnosticpolicy = Path(temporary) / "hardware diagnostics.json"
        missingdiagnosticpolicy = Path(temporary) / "missing diagnostics.json"
        missingdiagnosticfallback = Path(temporary) / "missing fallback.json"
        chromium.kernelcommandlineoption = lambda option: False
        try:
            os.environ.pop(debugvariable, None)
            chromium.HARDWAREDIAGNOSTICPOLICY = str(missingdiagnosticpolicy)
            chromium.HARDWAREDIAGNOSTICFALLBACK = str(
                missingdiagnosticfallback
            )
            defaultdiagnostics = chromium.hardwarediagnosticpolicy()
            require(
                defaultdiagnostics["enabled"] is False
                and defaultdiagnostics["chromium_engine"] is False
                and defaultdiagnostics["source"] == "default-off"
                and chromium.chromiumdebugenabled() is False
                and chromium.chromiumdebugarguments() == [],
                "Chromium hardware diagnostics did not default off",
            )

            validpolicy = {
                "format": 1,
                "enabled": True,
                "chromium_engine": True,
                "media_service": False,
                "engine_log_limit_bytes": chromium.ENGINEDEBUGLOGMINIMUM,
            }
            diagnosticpolicy.write_text(
                json.dumps(validpolicy),
                encoding="utf-8",
            )
            chromium.HARDWAREDIAGNOSTICFALLBACK = str(diagnosticpolicy)
            fallbackdiagnostics = chromium.hardwarediagnosticpolicy()
            require(
                fallbackdiagnostics["source"] == "launcher-fallback"
                and fallbackdiagnostics["enabled"] is True
                and fallbackdiagnostics["chromium_engine"] is True
                and fallbackdiagnostics["media_service"] is False
                and chromium.chromiumdebugenabled() is True,
                "the strictly validated launcher-side diagnostic fallback was not selected",
            )
            chromium.HARDWAREDIAGNOSTICFALLBACK = str(
                missingdiagnosticfallback
            )
            configureddiagnostics = chromium.hardwarediagnosticpolicy(
                str(diagnosticpolicy)
            )
            chromium.HARDWAREDIAGNOSTICPOLICY = str(diagnosticpolicy)
            debugconfiguration = chromium.chromiumdebugconfiguration()
            debugarguments = chromium.chromiumdebugarguments()
            servicedecoderarguments = chromium.t1osmediadecoderarguments(service)
            require(
                configureddiagnostics["source"] == "settings"
                and configureddiagnostics["enabled"] is True
                and configureddiagnostics["chromium_engine"] is True
                and configureddiagnostics["media_service"] is False
                and configureddiagnostics["engine_log_limit_bytes"]
                    == chromium.ENGINEDEBUGLOGMINIMUM
                and debugconfiguration["enabled"] is True
                and "--enable-logging=stderr" in debugarguments
                and any(
                    argument.startswith("--vmodule=")
                    for argument in debugarguments
                ),
                "the strict settings opt-in did not enable Chromium diagnostics",
            )
            require(
                servicedecoderarguments == [
                    "--enable-features=T1OSVideoDecoder",
                    "--t1os-video-decode-socket=/.ephemeral/media/decode.sock",
                    "--t1os-video-decode-output=linear-memory",
                ]
                and chromium.t1osmediadecoderarguments(None) == []
                and "--enable-logging=stderr" not in servicedecoderarguments
                and not any(
                    argument.startswith("--vmodule=")
                    for argument in servicedecoderarguments
                )
                and chromium.chromiumdebugarguments() == debugarguments,
                "Chromium diagnostics remain coupled to T1MD service availability",
            )

            componentoff = {**validpolicy, "chromium_engine": False}
            diagnosticpolicy.write_text(
                json.dumps(componentoff),
                encoding="utf-8",
            )
            require(
                chromium.chromiumdebugconfiguration()["enabled"] is False,
                "the Chromium component gate did not require both settings opt-ins",
            )

            invalidpolicies = (
                [],
                {**validpolicy, "format": True},
                {**validpolicy, "enabled": "true"},
                {**validpolicy, "chromium_engine": 1},
                {**validpolicy, "media_service": None},
                {**validpolicy, "engine_log_limit_bytes": True},
                {
                    **validpolicy,
                    "engine_log_limit_bytes":
                        chromium.ENGINEDEBUGLOGMINIMUM - 1,
                },
                {
                    **validpolicy,
                    "engine_log_limit_bytes":
                        chromium.ENGINEDEBUGLOGMAXIMUM + 1,
                },
            )
            for index, invalidpolicy in enumerate(invalidpolicies):
                diagnosticpolicy.write_text(
                    json.dumps(invalidpolicy),
                    encoding="utf-8",
                )
                rejected = chromium.hardwarediagnosticpolicy(
                    str(diagnosticpolicy)
                )
                require(
                    rejected["enabled"] is False
                    and rejected["chromium_engine"] is False
                    and rejected["source"] == "invalid-settings"
                    and chromium.chromiumdebugconfiguration()["enabled"] is False,
                    f"invalid Chromium hardware diagnostic policy {index} did not fail closed",
                )

            oversizedpolicy = {
                **validpolicy,
                "padding": "x" * 17000,
            }
            diagnosticpolicy.write_text(
                json.dumps(oversizedpolicy),
                encoding="utf-8",
            )
            rejected = chromium.hardwarediagnosticpolicy(str(diagnosticpolicy))
            require(
                rejected["enabled"] is False
                and rejected["chromium_engine"] is False
                and rejected["source"] == "invalid-settings"
                and chromium.chromiumdebugconfiguration()["enabled"] is False,
                "an oversized Chromium hardware diagnostic policy did not fail closed",
            )

            diagnosticpolicy.write_text(
                json.dumps(validpolicy),
                encoding="utf-8",
            )
            os.environ[debugvariable] = "0"
            disabledconfiguration = chromium.chromiumdebugconfiguration()
            require(
                disabledconfiguration["enabled"] is False
                and disabledconfiguration["chromium_engine"] is False
                and disabledconfiguration["source"] == "environment-off"
                and chromium.chromiumdebugarguments() == [],
                "the explicit Chromium debug-off environment did not override settings",
            )
        finally:
            chromium.HARDWAREDIAGNOSTICPOLICY = previousdiagnosticpolicy
            chromium.HARDWAREDIAGNOSTICFALLBACK = previousdiagnosticfallback
            chromium.kernelcommandlineoption = previousdebugkernel
            if previousdebug is None:
                os.environ.pop(debugvariable, None)
            else:
                os.environ[debugvariable] = previousdebug
    require(
        chromium.productionengineoutput(
            "t1os-chrome-subprocess: entered child-type=gpu-process"
        )
        and chromium.productionengineoutput(
            "T1OS_PRESENTATION_BRIDGE import failed"
        )
        and chromium.productionengineoutput(
            "GPU command buffer context lost during initialization"
        )
        and chromium.productionengineoutput(
            "GPU process exited unexpectedly: exit_code=8704"
        )
        and not chromium.productionengineoutput(
            "VERBOSE2: routine decoder selection detail"
        ),
        "the production engine-log filter lost helper, presentation, or context evidence",
    )
    sanitized = chromium.sanitizeengineoutput(
        "gpu --t1os-presentation-token=secret-value "
        "https://example.invalid/watch?q=private "
        "file:///the%20one/settings/private"
    )
    sanitizedauthorization = chromium.sanitizeengineoutput(
        "Authorization: Bearer secret-value with-more-data"
    )
    require(
        "--t1os-presentation-token=<redacted>" in sanitized
        and sanitized.count("<url-redacted>") == 2
        and "secret-value" not in sanitized
        and "example.invalid" not in sanitized
        and "file:///" not in sanitized,
        "Chromium engine-log sanitization retained a presentation token or URL",
    )
    require(
        sanitizedauthorization == "Authorization: <redacted>"
        and "Bearer" not in sanitizedauthorization
        and "secret-value" not in sanitizedauthorization,
        "Chromium engine-log sanitization retained an authorization value",
    )
    isolated = chromium.servicechromiumenvironment({
        "DISPLAY": ":99",
        "LIBVA_DRIVER_NAME": "nvidia",
        "LIBVA_DRIVERS_PATH": "/driver",
        "NVD_BACKEND": "direct",
        "CUDA_DISABLE_PERF_BOOST": "1",
        "T1OS_CHROMIUM_NVIDIA_DEBUG": "1",
        "T1OS_MEDIA_DECODE_OUTPUT": "dma-buf",
    })
    require(
        isolated == {"DISPLAY": ":99"},
        "legacy NVIDIA decode authority leaked into Chromium",
    )
    graphics = chromium.chromiumgraphicsenvironment({
        "DISPLAY": ":99",
        "LD_LIBRARY_PATH": chromium.BASEGRAPHICSLIBRARYPATH,
        "LIBGL_DRIVERS_PATH": chromium.LIBRARIES,
    }, "nvidia_drm")
    require(
        graphics == {
            "DISPLAY": ":99",
            "LD_LIBRARY_PATH": chromium.BASEGRAPHICSLIBRARYPATH,
            chromium.NVIDIAGPULIBRARYPATHVARIABLE:
                chromium.NVIDIAGRAPHICSLIBRARYPATH,
            chromium.NVIDIAGPUEGLVENDORVARIABLE:
                chromium.NVIDIAEGLVENDORFILE,
            chromium.NVIDIAGPUEGLEXTERNALVARIABLE:
                chromium.NVIDIAGBMPATH,
            chromium.NVIDIAGPUGBMBACKENDSPATHVARIABLE:
                chromium.NVIDIAGBMPATH,
            chromium.NVIDIAGPUGBMBACKENDVARIABLE: "nvidia-drm",
        },
        "NVIDIA EGL rendering did not select the contained vendor runtime",
    )
    stablegraphics = chromium.chromiumgraphicsenvironment({
        "DISPLAY": ":99",
        "LD_LIBRARY_PATH": chromium.BASEGRAPHICSLIBRARYPATH,
        "LIBGL_DRIVERS_PATH": chromium.LIBRARIES,
    }, "nvidia_drm", presentationbridge=False)
    require(
        stablegraphics == {
            "DISPLAY": ":99",
            "LD_LIBRARY_PATH": chromium.BASEGRAPHICSLIBRARYPATH,
            "LIBGL_DRIVERS_PATH": chromium.LIBRARIES,
        },
        "the production stability route still injects the NVIDIA EGL runtime",
    )
    stablemode, stablemodearguments = chromium.rendererconfiguration(
        "nvidia_drm",
        presentationbridge=False,
    )
    require(
        stablemode == "angle-swiftshader-rollback"
        and "--use-gl=angle" in stablemodearguments
        and "--use-angle=swiftshader" in stablemodearguments,
        "the explicit NVIDIA rollback no longer selects SwiftShader",
    )
    variable = chromium.NVIDIAPRESENTATIONVARIABLE
    previous = os.environ.get(variable)
    try:
        os.environ.pop(variable, None)
        require(
            chromium.nvidiapresentationenabled() is True,
            "NVIDIA hardware presentation is not enabled by default",
        )
        os.environ[variable] = "0"
        require(
            chromium.nvidiapresentationenabled() is False,
            "the explicit NVIDIA presentation rollback is ignored",
        )
    finally:
        if previous is None:
            os.environ.pop(variable, None)
        else:
            os.environ[variable] = previous
    require(
        chromium.servicechromiumenvironment(graphics) == graphics,
        "decode isolation removed the independent NVIDIA graphics runtime",
    )
    require(
        chromium.t1osmediadecoderoutputmode(False) == "linear-memory"
        and chromium.t1osmediadecoderoutputmode(True) == "dma-buf",
        "T1MD output selection is still coupled to decoder readiness",
    )
    require(
        chromium.mergechromiumfeaturearguments([
            "--enable-features=T1OSVideoDecoder",
            "--enable-features=T1OSNvidiaPresentation",
            "--disable-features=VaapiOnNvidiaGPUs",
            "--disable-features=Vulkan,VaapiOnNvidiaGPUs",
        ]) == [
            "--enable-features=T1OSVideoDecoder,T1OSNvidiaPresentation",
            "--disable-features=VaapiOnNvidiaGPUs,Vulkan",
        ],
        "Chromium feature switches are not consolidated deterministically",
    )

    with tempfile.TemporaryDirectory() as temporary:
        chromium.PROFILE = str(Path(temporary) / "profile")
        chowned = []
        chromium.safechown = lambda path: chowned.append(str(path))
        require(
            chromium.configureprofilesession(
                restore_session=True,
                single_root=True,
            ) == 5,
            "NVIDIA presentation did not suppress multi-window restore",
        )
        preferences = json.loads(
            (Path(chromium.PROFILE) / "Default" / "Preferences").read_text(
                encoding="utf-8"
            )
        )
        default_profile = Path(chromium.PROFILE) / "Default"
        require(
            preferences.get("session", {}).get("restore_on_startup") == 5,
            "single-root startup preference directory is not Chromium-owned",
        )
        require(
            str(default_profile) in chowned,
            "fresh Chromium Default profile directory was not handed to the engine UID",
        )
        require(
            chromium.configureprofilesession(
                restore_session=True,
                single_root=False,
            ) == 1,
            "normal session restore preference is no longer available",
        )

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        policy = root / "policy.json"
        manifest = root / "manifest.json"
        state = root / "state.json"
        socketpath = str(root / "decode.sock")
        policy.write_text(
            json.dumps({
                "enabled": True,
                "kill_switch": False,
                "protocol_version": 1,
            }),
            encoding="utf-8",
        )
        manifest.write_text(
            json.dumps({
                "t1os_media_decoder": {
                    "available": True,
                    "protocol": "T1MD",
                    "protocol_version": 1,
                    "feature": "T1OSVideoDecoder",
                    "brokered_socket": True,
                    "descriptor_pool_size": 8,
                    "chromium_revision":
                        "24b04c927b23c39cf9c5227cc8dc6f64a744c8e9",
                    "protocol_header_sha256":
                        "efcd311d2d9e83177ca867b09cd9a4f9"
                        "17da8dd0673a9e26461a66d591c4b003",
                    "source_overlay_sha256":
                        "703475ade7e720a9972002b0d1c97b07"
                        "87358d751bc0d294d0b956dd60ef7398",
                    "build_marker":
                        "T1OS_MEDIA_DECODER=T1MD/1;brokered_socket=1;"
                        "pool=8;chromium="
                        "24b04c927b23c39cf9c5227cc8dc6f64a744c8e9;"
                        "protocol_sha256="
                        "efcd311d2d9e83177ca867b09cd9a4f9"
                        "17da8dd0673a9e26461a66d591c4b003;"
                        "source_sha256="
                        "703475ade7e720a9972002b0d1c97b07"
                        "87358d751bc0d294d0b956dd60ef7398",
                },
            }),
            encoding="utf-8",
        )
        state.write_text(
            json.dumps({
                "state": "ready",
                "protocol": "T1MD",
                "protocol_version": 1,
                "pid": 712,
                "socket": socketpath,
                "worker_uid": 65534,
                "worker_gid": 1000,
                "maximum_sessions": 8,
                "maximum_connections": 8,
                "sandbox": {
                    "format": 1,
                    "landlock_abi": 7,
                    "landlock_minimum_abi": 5,
                    "landlock_filesystem":
                        "deny-by-default-all-through-ioctl-dev",
                    "landlock_network": "deny-tcp-bind-connect",
                    "seccomp": "filter",
                    "seccomp_tsync": True,
                    "runtime_filesystem": "read-only",
                    "device_filesystem": "read-write-ioctl",
                    "network_creation": "denied",
                    "process_creation": "threads-only",
                    "session_stdin": "null",
                    "session_stdout": "null",
                    "session_stderr": "bounded-nonblocking-relay",
                    "session_diagnostic_limit": 1048576,
                    "session_exec_visible_fds": 6,
                    "session_required_ipc_fds": 3,
                    "session_unexpected_inherited_fds": 0,
                    "policy_flags": 255,
                },
                "watchdog": {
                    "format": 1,
                    "policy_id": "t1md-watchdog-v1",
                    "authority": "supervisor",
                    "clock": "CLOCK_MONOTONIC",
                    "timeout_action": "SIGKILL",
                    "idle_timeout_ms": 0,
                    "starting_timeout_ms": 15000,
                    "hello_timeout_ms": 30000,
                    "create_timeout_ms": 15000,
                    "decode_timeout_ms": 15000,
                    "flush_timeout_ms": 15000,
                    "reset_timeout_ms": 10000,
                    "release_timeout_ms": 6000,
                    "destroy_timeout_ms": 10000,
                    "cleanup_timeout_ms": 10000,
                    "exiting_timeout_ms": 1000,
                },
            }),
            encoding="utf-8",
        )
        previous = {
            "policy": chromium.MEDIADECODEPOLICY,
            "packaged_policy": chromium.MEDIADECODEPACKAGEDPOLICY,
            "manifest": chromium.CHROMIUMMANIFEST,
            "state": chromium.MEDIADECODESTATE,
            "socket": chromium.MEDIADECODESOCKET,
            "stat": chromium.os.stat,
            "kill": chromium.os.kill,
            "kernel": chromium.kernelcommandlineoption,
        }
        chromium.MEDIADECODEPOLICY = str(policy)
        chromium.CHROMIUMMANIFEST = str(manifest)
        chromium.MEDIADECODESTATE = str(state)
        chromium.MEDIADECODESOCKET = socketpath
        chromium.kernelcommandlineoption = lambda option: False
        chromium.os.kill = lambda process, chosen: None

        def measuredstat(path, *arguments, **options):
            if os.path.normpath(str(path)) == os.path.normpath(socketpath):
                return types.SimpleNamespace(
                    st_mode=stat.S_IFSOCK | 0o660,
                    st_uid=1000,
                    st_gid=1000,
                )
            return previous["stat"](path, *arguments, **options)

        chromium.os.stat = measuredstat
        try:
            configured, reason = chromium.t1osmediadecoderconfiguration(
                "nvidia"
            )
            require(
                reason == "ready"
                and configured
                and configured["brokered_socket"] is True,
                "a valid brokered T1MD service was rejected",
            )
            chromium.MEDIADECODEPOLICY = str(root / "missing-settings.json")
            chromium.MEDIADECODEPACKAGEDPOLICY = str(policy)
            configured, reason = chromium.t1osmediadecoderconfiguration(
                "nvidia"
            )
            require(
                reason == "ready"
                and configured
                and configured["brokered_socket"] is True,
                "the packaged media policy fallback was not selected",
            )
            chromium.MEDIADECODEPOLICY = str(policy)
            policy.write_text(
                json.dumps({
                    "enabled": True,
                    "kill_switch": False,
                    "max_sessions": 16,
                    "protocol_version": 1,
                }),
                encoding="utf-8",
            )
            configured, reason = chromium.t1osmediadecoderconfiguration(
                "nvidia"
            )
            require(
                configured is None and reason == "session-ceiling-mismatch",
                "Chromium accepted a service ceiling other than eight",
            )
            policy.write_text(
                json.dumps({
                    "enabled": True,
                    "kill_switch": False,
                    "max_sessions": 8,
                    "protocol_version": 1,
                }),
                encoding="utf-8",
            )
            service_state = json.loads(state.read_text(encoding="utf-8"))
            service_state["sandbox"]["seccomp_tsync"] = "true"
            state.write_text(json.dumps(service_state), encoding="utf-8")
            configured, reason = chromium.t1osmediadecoderconfiguration(
                "nvidia"
            )
            require(
                configured is None
                and reason.startswith("service-not-ready:"),
                "a non-Boolean worker sandbox attestation was accepted",
            )
            service_state["sandbox"]["seccomp_tsync"] = True
            service_state["sandbox"]["session_stderr"] = "null"
            state.write_text(json.dumps(service_state), encoding="utf-8")
            configured, reason = chromium.t1osmediadecoderconfiguration(
                "nvidia"
            )
            require(
                configured is None
                and reason.startswith("service-not-ready:"),
                "a development worker without its bounded debug relay "
                "was accepted",
            )
            service_state["sandbox"]["session_stderr"] = (
                "bounded-nonblocking-relay"
            )
            service_state["watchdog"]["decode_timeout_ms"] = 14000
            state.write_text(json.dumps(service_state), encoding="utf-8")
            configured, reason = chromium.t1osmediadecoderconfiguration(
                "nvidia"
            )
            require(
                configured is None
                and reason.startswith("service-not-ready:"),
                "a service with a different supervisor watchdog policy "
                "was accepted",
            )
            service_state["watchdog"]["decode_timeout_ms"] = 15000
            state.write_text(json.dumps(service_state), encoding="utf-8")
            policy.write_text(
                json.dumps({
                    "enabled": True,
                    "kill_switch": True,
                    "protocol_version": 1,
                }),
                encoding="utf-8",
            )
            configured, reason = chromium.t1osmediadecoderconfiguration(
                "nvidia"
            )
            require(
                configured is None and reason == "kill-switch",
                "the Chromium media decoder kill switch did not win",
            )
            policy.write_text(
                json.dumps({
                    "enabled": True,
                    "kill_switch": False,
                    "protocol_version": 1,
                }),
                encoding="utf-8",
            )
            runtime = json.loads(manifest.read_text(encoding="utf-8"))
            protocol_hash = runtime["t1os_media_decoder"][
                "protocol_header_sha256"
            ]
            runtime["t1os_media_decoder"]["protocol_header_sha256"] = (
                "0" * 64
            )
            manifest.write_text(json.dumps(runtime), encoding="utf-8")
            configured, reason = chromium.t1osmediadecoderconfiguration(
                "nvidia"
            )
            require(
                configured is None
                and reason.startswith("chromium-runtime-unpatched:"),
                "a mismatched native/Chromium protocol ABI was accepted",
            )
            runtime["t1os_media_decoder"]["protocol_header_sha256"] = (
                protocol_hash
            )
            source_hash = runtime["t1os_media_decoder"][
                "source_overlay_sha256"
            ]
            runtime["t1os_media_decoder"]["source_overlay_sha256"] = (
                "0" * 64
            )
            manifest.write_text(json.dumps(runtime), encoding="utf-8")
            configured, reason = chromium.t1osmediadecoderconfiguration(
                "nvidia"
            )
            require(
                configured is None
                and reason.startswith("chromium-runtime-unpatched:"),
                "a Chromium runtime from different source bytes was accepted",
            )
            runtime["t1os_media_decoder"]["source_overlay_sha256"] = (
                source_hash
            )
            build_marker = runtime["t1os_media_decoder"]["build_marker"]
            runtime["t1os_media_decoder"]["build_marker"] = (
                build_marker + "-tampered"
            )
            manifest.write_text(json.dumps(runtime), encoding="utf-8")
            configured, reason = chromium.t1osmediadecoderconfiguration(
                "nvidia"
            )
            require(
                configured is None
                and reason.startswith("chromium-runtime-unpatched:"),
                "a Chromium binary with a different build marker was "
                "accepted",
            )
            runtime["t1os_media_decoder"]["build_marker"] = build_marker
            runtime["t1os_media_decoder"]["brokered_socket"] = False
            manifest.write_text(json.dumps(runtime), encoding="utf-8")
            configured, reason = chromium.t1osmediadecoderconfiguration(
                "nvidia"
            )
            require(
                configured is None
                and reason.startswith("chromium-runtime-unpatched:"),
                "an unpatched Chromium runtime did not fail closed",
            )
            runtime["t1os_media_decoder"]["brokered_socket"] = True
            runtime["t1os_media_decoder"]["available"] = False
            manifest.write_text(json.dumps(runtime), encoding="utf-8")
            configured, reason = chromium.t1osmediadecoderconfiguration(
                "nvidia"
            )
            require(
                configured is None
                and reason.startswith("chromium-runtime-unpatched:"),
                "a runtime marked unavailable did not fail closed",
            )
            runtime["t1os_media_decoder"]["available"] = 1
            manifest.write_text(json.dumps(runtime), encoding="utf-8")
            configured, reason = chromium.t1osmediadecoderconfiguration(
                "nvidia"
            )
            require(
                configured is None
                and reason.startswith("chromium-runtime-unpatched:"),
                "a non-Boolean runtime availability marker was accepted",
            )
            runtime["t1os_media_decoder"]["available"] = True
            runtime["t1os_media_decoder"]["protocol_version"] = True
            manifest.write_text(json.dumps(runtime), encoding="utf-8")
            configured, reason = chromium.t1osmediadecoderconfiguration(
                "nvidia"
            )
            require(
                configured is None
                and reason.startswith("chromium-runtime-unpatched:"),
                "a Boolean runtime protocol version was accepted",
            )
            policy.write_text(
                json.dumps({
                    "enabled": True,
                    "kill_switch": "corrupt",
                    "protocol_version": 1,
                }),
                encoding="utf-8",
            )
            configured, reason = chromium.t1osmediadecoderconfiguration(
                "nvidia"
            )
            require(
                configured is None and reason.startswith("policy-invalid:"),
                "a malformed Chromium media policy did not fail closed",
            )
            policy.write_text(
                json.dumps({
                    "enabled": True,
                    "kill_switch": False,
                    "protocol_version": True,
                }),
                encoding="utf-8",
            )
            configured, reason = chromium.t1osmediadecoderconfiguration(
                "nvidia"
            )
            require(
                configured is None and reason == "policy-protocol-invalid",
                "a Boolean Chromium policy protocol version was accepted",
            )
        finally:
            chromium.MEDIADECODEPOLICY = previous["policy"]
            chromium.MEDIADECODEPACKAGEDPOLICY = previous[
                "packaged_policy"
            ]
            chromium.CHROMIUMMANIFEST = previous["manifest"]
            chromium.MEDIADECODESTATE = previous["state"]
            chromium.MEDIADECODESOCKET = previous["socket"]
            chromium.os.stat = previous["stat"]
            chromium.os.kill = previous["kill"]
            chromium.kernelcommandlineoption = previous["kernel"]


def goddesstests(goddess):
    with tempfile.TemporaryDirectory() as temporary:
        policy = Path(temporary) / "policy.json"
        diagnosticpolicy = Path(temporary) / "hardware diagnostics.json"
        missingdiagnosticpolicy = Path(temporary) / "missing diagnostics.json"
        kernel = goddess.kernelcommandlineoption
        primary_policy = goddess.MEDIADECODEPOLICY
        packaged_policy = goddess.MEDIADECODEPACKAGEDPOLICY
        hardware_policy = goddess.HARDWAREDIAGNOSTICPOLICY
        hardware_fallback = goddess.HARDWAREDIAGNOSTICFALLBACK
        goddess.kernelcommandlineoption = lambda option: False
        goddess.HARDWAREDIAGNOSTICPOLICY = str(missingdiagnosticpolicy)
        goddess.HARDWAREDIAGNOSTICFALLBACK = str(missingdiagnosticpolicy)
        try:
            default = goddess.mediadecodeservicepolicy(
                path=str(Path(temporary) / "missing.json"),
                environment={},
            )
            require(
                default["enabled"] is False
                and default["source"] == "default-off",
                "GODDESS native decode did not default off",
            )
            policy.write_text(
                json.dumps({
                    "enabled": True,
                    "kill_switch": False,
                    "max_sessions": 16,
                    "protocol_version": 1,
                }),
                encoding="utf-8",
            )
            enabled = goddess.mediadecodeservicepolicy(
                path=str(policy),
                environment={},
            )
            require(
                enabled["enabled"] is False
                and enabled["source"] == "invalid-settings",
                "GODDESS accepted a service ceiling other than eight",
            )
            policy.write_text(
                json.dumps({
                    "enabled": True,
                    "kill_switch": False,
                    "max_sessions": 40,
                    "protocol_version": 1,
                }),
                encoding="utf-8",
            )
            bounded = goddess.mediadecodeservicepolicy(
                path=str(policy),
                environment={},
            )
            require(
                bounded["enabled"] is False
                and bounded["source"] == "invalid-settings",
                "GODDESS accepted an out-of-range session bound",
            )
            policy.write_text(
                json.dumps({
                    "enabled": True,
                    "kill_switch": False,
                    "max_sessions": 8,
                    "protocol_version": 1,
                }),
                encoding="utf-8",
            )
            enabled = goddess.mediadecodeservicepolicy(
                path=str(policy),
                environment={},
            )
            require(
                enabled["enabled"] is True
                and enabled["max_sessions"] == 8
                and enabled["development_debug"] is False,
                "GODDESS rejected the exact eight-connection contract",
            )
            policy.write_text(
                json.dumps({
                    "enabled": True,
                    "kill_switch": False,
                    "development_debug": True,
                    "max_sessions": 8,
                    "protocol_version": 1,
                }),
                encoding="utf-8",
            )
            production = goddess.mediadecodeservicepolicy(
                path=str(policy),
                environment={},
            )
            debug = goddess.mediadecodeservicepolicy(
                path=str(policy),
                environment={"T1OS_MEDIA_DECODE_DEBUG": "1"},
            )
            require(
                production["development_debug"] is False
                and debug["development_debug"] is True,
                "GODDESS does not require an explicit per-boot debug opt-in",
            )
            diagnosticpolicy.write_text(
                json.dumps({
                    "format": 1,
                    "enabled": True,
                    "chromium_engine": False,
                    "media_service": True,
                    "engine_log_limit_bytes":
                        goddess.HARDWAREDIAGNOSTICLOGMINIMUM,
                }),
                encoding="utf-8",
            )
            configureddiagnostics = goddess.hardwarediagnosticpolicy(
                str(diagnosticpolicy)
            )
            goddess.HARDWAREDIAGNOSTICFALLBACK = str(diagnosticpolicy)
            fallbackdiagnostics = goddess.hardwarediagnosticpolicy()
            goddess.HARDWAREDIAGNOSTICPOLICY = str(diagnosticpolicy)
            diagnosticsdebug = goddess.mediadecodeservicepolicy(
                path=str(policy),
                environment={},
            )
            diagnosticsdisabled = goddess.mediadecodeservicepolicy(
                path=str(policy),
                environment={"T1OS_MEDIA_DECODE_DEBUG": "0"},
            )
            require(
                configureddiagnostics["source"] == "settings"
                and fallbackdiagnostics["source"] == "launcher-fallback"
                and fallbackdiagnostics["enabled"] is True
                and fallbackdiagnostics["media_service"] is True
                and configureddiagnostics["enabled"] is True
                and configureddiagnostics["chromium_engine"] is False
                and configureddiagnostics["media_service"] is True
                and diagnosticsdebug["development_debug"] is True
                and diagnosticsdebug["debug_source"] == "settings"
                and diagnosticsdisabled["development_debug"] is False,
                "GODDESS did not honor bounded media diagnostics or its explicit environment override",
            )
            goddess.HARDWAREDIAGNOSTICPOLICY = str(missingdiagnosticpolicy)
            goddess.MEDIADECODEPOLICY = str(
                Path(temporary) / "missing-settings.json"
            )
            goddess.MEDIADECODEPACKAGEDPOLICY = str(policy)
            packaged = goddess.mediadecodeservicepolicy(environment={})
            require(
                packaged["enabled"] is True
                and packaged["max_sessions"] == 8,
                "GODDESS did not select the packaged media policy fallback",
            )
            policy.write_text(
                json.dumps({
                    "enabled": True,
                    "kill_switch": False,
                    "max_sessions": 8,
                    "protocol_version": 1,
                }),
                encoding="utf-8",
            )
            killed = goddess.mediadecodeservicepolicy(
                path=str(policy),
                environment={"T1OS_MEDIA_DECODE_SERVICE": "0"},
            )
            require(
                killed["enabled"] is False
                and killed["source"] == "environment-off",
                "the emergency environment kill switch did not win",
            )
            policy.write_text(
                json.dumps({
                    "enabled": True,
                    "kill_switch": True,
                    "protocol_version": 1,
                }),
                encoding="utf-8",
            )
            killed = goddess.mediadecodeservicepolicy(
                path=str(policy),
                environment={"T1OS_MEDIA_DECODE_SERVICE": "1"},
            )
            require(
                killed["enabled"] is False
                and killed["source"] == "kill-switch",
                "the persistent kill switch did not win",
            )
            policy.write_text(
                json.dumps({
                    "enabled": True,
                    "kill_switch": "corrupt",
                    "development_debug": True,
                    "protocol_version": 1,
                }),
                encoding="utf-8",
            )
            invalid = goddess.mediadecodeservicepolicy(
                path=str(policy),
                environment={},
            )
            require(
                invalid["enabled"] is False
                and invalid["source"] == "invalid-settings",
                "a malformed GODDESS media policy did not fail closed",
            )
            invalid_override = goddess.mediadecodeservicepolicy(
                path=str(policy),
                environment={"T1OS_MEDIA_DECODE_SERVICE": "1"},
            )
            require(
                invalid_override["enabled"] is False
                and invalid_override["source"] == "invalid-settings",
                "an enable override bypassed malformed GODDESS policy",
            )
            policy.write_text(
                json.dumps({
                    "enabled": True,
                    "kill_switch": False,
                    "development_debug": True,
                    "max_sessions": 8,
                    "protocol_version": True,
                }),
                encoding="utf-8",
            )
            invalid = goddess.mediadecodeservicepolicy(
                path=str(policy),
                environment={},
            )
            require(
                invalid["enabled"] is False
                and invalid["source"] == "invalid-settings",
                "a Boolean protocol version was accepted by GODDESS",
            )
        finally:
            goddess.kernelcommandlineoption = kernel
            goddess.MEDIADECODEPOLICY = primary_policy
            goddess.MEDIADECODEPACKAGEDPOLICY = packaged_policy
            goddess.HARDWAREDIAGNOSTICPOLICY = hardware_policy
            goddess.HARDWAREDIAGNOSTICFALLBACK = hardware_fallback

    inherited_single_buffer = os.environ.get("NVD_SINGLE_BUFFER")
    os.environ["NVD_SINGLE_BUFFER"] = "1"
    try:
        environment = goddess.mediadecodeserviceenvironment(
            {
                "environment": {
                    "T1OS_DRM_DEVICE":
                        "/the one/drivers/nodes/dri/card0",
                },
            },
            "/.ephemeral/graphics/nvidia-path-provider.so",
        )
    finally:
        if inherited_single_buffer is None:
            os.environ.pop("NVD_SINGLE_BUFFER", None)
        else:
            os.environ["NVD_SINGLE_BUFFER"] = inherited_single_buffer
    require(
        environment["LIBVA_DRIVER_NAME"] == "nvidia"
        and environment["NVD_BACKEND"] == "direct"
        and "NVD_SINGLE_BUFFER" not in environment
        and environment["CUDA_DISABLE_PERF_BOOST"] == "1"
        and environment["CUDA_CACHE_PATH"] == "/.ephemeral/cache/nvidia"
        and "CUDA_CACHE_DISABLE" not in environment
        and environment["__GL_SHADER_DISK_CACHE"] == "0"
        and environment["MESA_SHADER_CACHE_DISABLE"] == "true"
        and environment["LD_PRELOAD"]
        == "/.ephemeral/graphics/nvidia-path-provider.so",
        "the isolated native NVDEC environment is incomplete",
    )
    require(
        "T1OS_CHROMIUM_NVIDIA_DEBUG" not in environment,
        "Chromium's quarantined NVIDIA broker controls leaked into the service",
    )

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        statepath = root / "state.json"
        socketpath = str(root / "decode.sock")
        device = os.path.normpath(
            "/the one/drivers/nodes/dri/renderD128"
        )
        state = {
            "state": "ready",
            "protocol": "T1MD",
            "protocol_version": 1,
            "pid": 913,
            "socket": socketpath,
            "device": device,
            "worker_uid": 65534,
            "worker_gid": 1000,
            "maximum_sessions": 8,
            "maximum_connections": 8,
            "surface_export": dict(goddess.MEDIADECODEEXPORTCONTRACT),
            "capabilities": {
                "vendor": "T1OS NVIDIA VA-API state test",
                "profile_count": 7,
                "chroma_subsampling": "4:2:0",
                "bit_depths": [8, 10],
                "output_formats": ["NV12", "P010"],
            },
            "sandbox": {
                "format": 1,
                "landlock_abi": 7,
                "landlock_minimum_abi": 5,
                "landlock_filesystem":
                    "deny-by-default-all-through-ioctl-dev",
                "landlock_network": "deny-tcp-bind-connect",
                "seccomp": "filter",
                "seccomp_tsync": True,
                "runtime_filesystem": "read-only",
                "device_filesystem": "read-write-ioctl",
                "network_creation": "denied",
                "process_creation": "threads-only",
                "session_stdin": "null",
                "session_stdout": "null",
                "session_stderr": "bounded-nonblocking-relay",
                "session_diagnostic_limit": 1048576,
                "session_exec_visible_fds": 6,
                "session_required_ipc_fds": 3,
                "session_unexpected_inherited_fds": 0,
                "policy_flags": 255,
            },
            "watchdog": dict(goddess.MEDIADECODEWATCHDOGCONTRACT),
        }
        statepath.write_text(json.dumps(state), encoding="utf-8")
        previous_state = goddess.MEDIADECODESTATE
        previous_socket = goddess.MEDIADECODESOCKET
        previous_stat = goddess.os.stat
        goddess.MEDIADECODESTATE = str(statepath)
        goddess.MEDIADECODESOCKET = socketpath

        def measuredstat(path, *arguments, **options):
            if os.path.normpath(str(path)) == os.path.normpath(socketpath):
                return types.SimpleNamespace(
                    st_mode=stat.S_IFSOCK | 0o660,
                    st_uid=1000,
                    st_gid=1000,
                )
            return previous_stat(path, *arguments, **options)

        goddess.os.stat = measuredstat
        process = types.SimpleNamespace(pid=913, poll=lambda: None)
        try:
            require(
                goddess.mediadecodeready(process, device),
                "GODDESS rejected the exact supervised watchdog contract",
            )
            state["surface_export"]["modifier_scope"] = "common"
            statepath.write_text(json.dumps(state), encoding="utf-8")
            require(
                not goddess.mediadecodeready(process, device),
                "GODDESS accepted a shared-modifier surface contract",
            )
            state["surface_export"]["modifier_scope"] = "per-object"
            state["capabilities"]["output_formats"].append("P012")
            statepath.write_text(json.dumps(state), encoding="utf-8")
            require(
                not goddess.mediadecodeready(process, device),
                "GODDESS accepted a browser-unusable decoder output format",
            )
            state["capabilities"]["output_formats"].pop()
            state["watchdog"]["authority"] = "worker"
            statepath.write_text(json.dumps(state), encoding="utf-8")
            require(
                not goddess.mediadecodeready(process, device),
                "GODDESS accepted a worker-owned watchdog deadline",
            )
            state["watchdog"]["authority"] = "supervisor"
            state["sandbox"]["session_exec_visible_fds"] = 5
            statepath.write_text(json.dumps(state), encoding="utf-8")
            require(
                not goddess.mediadecodeready(process, device),
                "GODDESS accepted the obsolete five-FD worker contract",
            )
        finally:
            goddess.MEDIADECODESTATE = previous_state
            goddess.MEDIADECODESOCKET = previous_socket
            goddess.os.stat = previous_stat

    source = GODDESS.read_text(encoding="utf-8")
    require(
        "MEDIADECODEWORKER = '/the one/software/audio/t1-video-decode'"
        in source,
        "GODDESS does not use the LSM-authorized compiled multicall worker",
    )
    require(
        "t1-media-decode-worker" not in source,
        "GODDESS still references the LSM-ineligible standalone worker",
    )
    require(
        "environment['NVD_SINGLE_BUFFER']" not in source
        and "NVD_SINGLE_BUFFER is intentionally absent" in source,
        "GODDESS re-enabled NVIDIA's superseded common-modifier export",
    )
    ready = source.index("if not waitwindowserver(wsproc):")
    service = source.index(
        "configuremediadecodeservice(wsproc, graphicsbackend)",
        ready,
    )
    startup = source.index("runstartup(startupenvironment, wsproc)", service)
    require(
        ready < service < startup,
        "media service lifecycle is not ordered after graphics and before login",
    )
    require(
        "'media',\n            'exchange'" in source,
        "media service is not stopped before driver/display teardown",
    )
    require(
        "info.get('command')\n                        or [script]"
        in source,
        "GODDESS supervision cannot restart a native service command",
    )
    require(
        "[sys.executable, script]" not in source,
        "GODDESS supervision reintroduced an interpreter-first service fallback",
    )
    for required in (
        "'--socket-uid',\n            '1000'",
        "'--socket-gid',\n            '1000'",
        "'--allow-uid',\n            '1000'",
        "'--worker-uid',\n            str(MEDIADECODEWORKERUID)",
        "'--worker-gid',\n            str(MEDIADECODEWORKERGID)",
        "'--max-connections',\n            str(policy['max_sessions'])",
        "if policy['development_debug']:\n            command.append('--debug')",
    ):
        require(
            required in source,
            f"GODDESS native decoder launch contract is missing {required}",
        )


def nativeworkerlifecycletests():
    source = MEDIA_WORKER.read_text(encoding="utf-8")
    main = source.index("t1_media_worker_main(int socket_fd,")
    ready = source.index("T1_MEDIA_WATCHDOG_READY", main)
    handshake = source.index("t1_media_handshake(&worker, true)", ready)
    hardware = source.index("av_hwdevice_ctx_create(", handshake)
    seccomp = source.index("t1_media_install_worker_seccomp()", hardware)
    capabilities = source.index("t1_media_finish_hello(&worker)", seccomp)
    loop = source.index("t1_media_worker_loop(&worker)", capabilities)
    require(
        ready < handshake < hardware < seccomp < capabilities < loop,
        "worker must authenticate a live broker socket before opening "
        "VA-API/NVDEC, then install the sandbox before advertising "
        "CAPABILITIES",
    )
    require(
        "T1_MEDIA_WORKER preauthentication-discard" in source,
        "abandoned broker sockets are not diagnosable",
    )
    require(
        "VA_EXPORT_SURFACE_SEPARATE_LAYERS" in source
        and "VA_EXPORT_SURFACE_COMPOSED_LAYERS" not in source
        and "drm->num_objects != 2" in source
        and "drm->num_layers != 2" in source
        and "T1_MEDIA_FRAME_SEPARATE_LAYERS" in source,
        "the worker does not fail closed on the natural two-object export topology",
    )
    require(
        "return T1_MEDIA_PIXEL_FORMAT_UNKNOWN;" in source
        and "software_format == AV_PIX_FMT_NV12" in source
        and "software_format == AV_PIX_FMT_P010LE" in source
        and "description->log2_chroma_w == 1" in source
        and "description->log2_chroma_h == 1" in source,
        "the worker does not hard-fail unknown depth/chroma output formats",
    )
    require(
        "--capability-contract-self-test" in source
        and "T1_MEDIA_PROFILE_VP9_1) != 0" in source
        and "T1_MEDIA_PROFILE_VP9_2) !=" in source
        and "T1_MEDIA_PROFILE_AV1_MAIN) !=" in source
        and "T1_MEDIA_PROFILE_MPEG2_MAIN) != 0" in source,
        "the browser-usable profile/depth capability contract is untested",
    )
    daemon = MEDIA_DAEMON.read_text(encoding="utf-8")
    require(
        "T1_MEDIA_SERVICE worker-reject reason=capacity" in daemon,
        "decoder connection capacity rejection is not diagnosable",
    )
    require(
        '\\"surface_export\\"' in daemon
        and "T1_MEDIA_SURFACE_OBJECT_LAYOUT" in daemon
        and "T1_MEDIA_SURFACE_MODIFIER_SCOPE" in daemon
        and "T1_MEDIA_SURFACE_MODIFIER_LAYOUT" in daemon
        and "composed_fallback=0" in daemon,
        "daemon readiness/log evidence omits the surface-export contract",
    )


def nvidiaplanarexporttests():
    build = GRAPHICS_BUILD.read_text(encoding="utf-8")
    patch = NVIDIA_PLANAR_PATCH.read_text(encoding="utf-8")
    require(
        "python3 \"$nvidia_vaapi_planar_patch\"" in build
        and "multi-object-natural-per-plane-modifier-v2" in build,
        "the graphics build does not apply or attest the NVIDIA planar patch",
    )
    require(
        "fmtInfo->bppc, fmtInfo->numPlanes, fmtInfo->plane, false);" in patch
        and '".Height = driverImages[i].height,"' in patch
        and "natural per-plane DMA-BUF export" in patch,
        "the NVIDIA build does not enforce natural per-plane modifier tiling",
    )


def main():
    chromium = loadfunctions(
        "t1os_test_chromium",
        CHROMIUM,
        {
            "booleanoption",
            "kernelcommandlineoption",
            "nvidiapresentationenabled",
            "hardwarediagnosticpolicy",
            "chromiumdebugconfiguration",
            "chromiumdebugenabled",
            "chromiumdebugarguments",
            "sanitizeengineoutput",
            "productionengineoutput",
            "t1osmediadecoderconfiguration",
            "t1osmediadecoderarguments",
            "t1osmediadecoderoutputmode",
            "mergechromiumfeaturearguments",
            "mkdir",
            "atomictext",
            "configureprofilesession",
            "servicechromiumenvironment",
            "chromiumgraphicsenvironment",
            "rendererconfiguration",
            "browsergpuarguments",
            "audiolatencymilliseconds",
        },
        {
            "CHROMIUMMANIFEST": "/the one/software/chromium/manifest.json",
            "PROFILE": "/the one/settings/chromium/profile",
            "safechown": lambda path: None,
            "logline": lambda message: None,
            "ENGINEGID": 1000,
            "ENGINEUID": 1000,
            "LIBRARIES": "/the one/software/chromium/libraries",
            "BASEGRAPHICSLIBRARYPATH":
                "/the one/software/chromium/libraries:"
                "/the one/catalogue/graphics",
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
            "NVIDIAGPUGBMBACKENDVARIABLE":
                "SANDBOX_GPU_GBM_BACKEND",
            "NVIDIAEGLVENDORFILE":
                "/the one/catalogue/graphics/nvidia/"
                "egl_vendor.d/10_nvidia.json",
            "NVIDIAGBMPATH":
                "/the one/catalogue/graphics/nvidia/gbm",
            "NOUVEAURENDERER": "angle-swiftshader",
            "NVIDIAPRESENTATIONVARIABLE":
                "T1OS_CHROMIUM_NVIDIA_PRESENTATION",
            "CHROMIUMDEBUGVARIABLE": "T1OS_CHROMIUM_DEBUG",
            "HARDWAREDIAGNOSTICPOLICY":
                "/the one/settings/media/hardware diagnostics.json",
            "HARDWAREDIAGNOSTICFALLBACK":
                "/the one/build/chromium/hardware diagnostics.json",
            "ENGINEDEBUGLOGLIMIT": 8 * 1024 * 1024,
            "ENGINEDEBUGLOGMINIMUM": 64 * 1024,
            "ENGINEDEBUGLOGMAXIMUM": 16 * 1024 * 1024,
            "ENGINEDEBUGLINELIMIT": 16 * 1024,
            "AUDIORATE": 48000,
            "MEDIADECODECHROMIUMREVISION":
                "24b04c927b23c39cf9c5227cc8dc6f64a744c8e9",
            "MEDIADECODEFEATURE": "T1OSVideoDecoder",
            "PRESENTATIONFEATURE": "T1OSNvidiaPresentation",
            "MEDIADECODEOUTPUTVARIABLE": "T1OS_MEDIA_DECODE_OUTPUT",
            "MEDIADECODEOUTPUTSWITCH":
                "--t1os-video-decode-output=",
            "MEDIADECODEOUTPUTDMABUF": "dma-buf",
            "MEDIADECODEOUTPUTLINEAR": "linear-memory",
            "MEDIADECODEPOLICY":
                "/the one/settings/media/video decode service.json",
            "MEDIADECODEPACKAGEDPOLICY":
                "/the one/software/audio/video decode service.json",
            "MEDIADECODEPROTOCOL": "T1MD",
            "MEDIADECODEPROTOCOLVERSION": 1,
            "MEDIADECODEPROTOCOLHEADERSHA256":
                "efcd311d2d9e83177ca867b09cd9a4f9"
                "17da8dd0673a9e26461a66d591c4b003",
            "MEDIADECODESOURCEOVERLAYSHA256":
                "703475ade7e720a9972002b0d1c97b07"
                "87358d751bc0d294d0b956dd60ef7398",
            "MEDIADECODEBUILDMARKER":
                "T1OS_MEDIA_DECODER=T1MD/1;brokered_socket=1;pool=8;"
                "chromium="
                "24b04c927b23c39cf9c5227cc8dc6f64a744c8e9;"
                "protocol_sha256="
                "efcd311d2d9e83177ca867b09cd9a4f9"
                "17da8dd0673a9e26461a66d591c4b003;"
                "source_sha256="
                "703475ade7e720a9972002b0d1c97b07"
                "87358d751bc0d294d0b956dd60ef7398",
            "MEDIADECODEWORKERUID": 65534,
            "MEDIADECODEWORKERGID": 1000,
            "MEDIADECODESANDBOXFORMAT": 1,
            "MEDIADECODESANDBOXMINIMUMABI": 5,
            "MEDIADECODESANDBOXFLAGS": 255,
            "MEDIADECODESESSIONEXECVISIBLEFDS": 6,
            "MEDIADECODESESSIONREQUIREDIPCFDS": 3,
            "MEDIADECODESESSIONSTDIN": "null",
            "MEDIADECODESESSIONSTDOUT": "null",
            "MEDIADECODESESSIONSTDERR": "bounded-nonblocking-relay",
            "MEDIADECODESESSIONDIAGNOSTICLIMIT": 1048576,
            "MEDIADECODEWATCHDOGCONTRACT": {
                "format": 1,
                "policy_id": "t1md-watchdog-v1",
                "authority": "supervisor",
                "clock": "CLOCK_MONOTONIC",
                "timeout_action": "SIGKILL",
                "idle_timeout_ms": 0,
                "starting_timeout_ms": 15000,
                "hello_timeout_ms": 30000,
                "create_timeout_ms": 15000,
                "decode_timeout_ms": 15000,
                "flush_timeout_ms": 15000,
                "reset_timeout_ms": 10000,
                "release_timeout_ms": 6000,
                "destroy_timeout_ms": 10000,
                "cleanup_timeout_ms": 10000,
                "exiting_timeout_ms": 1000,
            },
            "MEDIADECODEMAXSESSIONS": 8,
            "MEDIADECODESOCKET": "/.ephemeral/media/decode.sock",
            "MEDIADECODESOCKETSWITCH": "--t1os-video-decode-socket=",
            "MEDIADECODESTATE": "/.ephemeral/media/decode-service.json",
            "PROCESSROOT": "/the one/drivers/processes",
        },
    )
    goddess = loadfunctions(
        "t1os_test_goddess",
        GODDESS,
        {
            "booleanoption",
            "hardwarediagnosticpolicy",
            "kernelcommandlineoption",
            "mediadecodeready",
            "mediadecodeservicepolicy",
            "mediadecodeserviceenvironment",
        },
        {
            "GRAPHICSCATALOGUE": "/the one/catalogue/graphics",
            "LIBVADRIVERPATH": "/the one/catalogue/graphics/dri",
            "NVIDIACACHEPATH": "/.ephemeral/cache/nvidia",
            "MEDIADECODEMAXSESSIONS": 8,
            "MEDIADECODEMAXPROFILES": 48,
            "HARDWAREDIAGNOSTICPOLICY":
                "/the one/settings/media/hardware diagnostics.json",
            "HARDWAREDIAGNOSTICFALLBACK":
                "/the one/build/chromium/hardware diagnostics.json",
            "HARDWAREDIAGNOSTICLOGMINIMUM": 64 * 1024,
            "HARDWAREDIAGNOSTICLOGMAXIMUM": 16 * 1024 * 1024,
            "MEDIADECODEEXPORTCONTRACT": {
                "mode": "separate-layers",
                "object_layout": "one-object-per-plane",
                "modifier_scope": "per-object",
                "modifier_layout": "natural-per-plane",
                "composed_fallback": False,
            },
            "MEDIADECODEPOLICY":
                "/the one/settings/media/video decode service.json",
            "MEDIADECODEPACKAGEDPOLICY":
                "/the one/software/audio/video decode service.json",
            "MEDIADECODEPROTOCOL": "T1MD",
            "MEDIADECODEPROTOCOLVERSION": 1,
            "MEDIADECODESTATE": "/.ephemeral/media/decode-service.json",
            "MEDIADECODESOCKET": "/.ephemeral/media/decode.sock",
            "MEDIADECODESANDBOXFORMAT": 1,
            "MEDIADECODESANDBOXMINIMUMABI": 5,
            "MEDIADECODESANDBOXFLAGS": 255,
            "MEDIADECODESESSIONEXECVISIBLEFDS": 6,
            "MEDIADECODESESSIONREQUIREDIPCFDS": 3,
            "MEDIADECODESESSIONSTDIN": "null",
            "MEDIADECODESESSIONSTDOUT": "null",
            "MEDIADECODESESSIONSTDERR": "bounded-nonblocking-relay",
            "MEDIADECODESESSIONDIAGNOSTICLIMIT": 1048576,
            "MEDIADECODEWATCHDOGCONTRACT": {
                "format": 1,
                "policy_id": "t1md-watchdog-v1",
                "authority": "supervisor",
                "clock": "CLOCK_MONOTONIC",
                "timeout_action": "SIGKILL",
                "idle_timeout_ms": 0,
                "starting_timeout_ms": 15000,
                "hello_timeout_ms": 30000,
                "create_timeout_ms": 15000,
                "decode_timeout_ms": 15000,
                "flush_timeout_ms": 15000,
                "reset_timeout_ms": 10000,
                "release_timeout_ms": 6000,
                "destroy_timeout_ms": 10000,
                "cleanup_timeout_ms": 10000,
                "exiting_timeout_ms": 1000,
            },
            "MEDIADECODEWORKERUID": 65534,
            "MEDIADECODEWORKERGID": 1000,
            "NVIDIAGRAPHICSRUNTIME":
                "/the one/catalogue/graphics/nvidia",
        },
    )
    chromiumtests(chromium)
    goddesstests(goddess)
    nativeworkerlifecycletests()
    nvidiaplanarexporttests()
    print("Chromium media decode service policy and lifecycle tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
