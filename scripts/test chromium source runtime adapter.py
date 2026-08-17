"""Offline tests for the source-built Chromium runtime installer."""

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

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "development/build chromium runtime.py"
SOURCE_BUILDER = ROOT / "development/build chromium source.py"
OVERLAY_APPLIER = (
    ROOT / "resource/chromium-source/150.0.7871.181/apply.py"
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def load_adapter():
    spec = importlib.util.spec_from_file_location(
        "t1os_chromium_runtime_adapter", ADAPTER
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {ADAPTER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_source_builder():
    spec = importlib.util.spec_from_file_location(
        "t1os_chromium_source_builder", SOURCE_BUILDER
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {SOURCE_BUILDER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_overlay_applier():
    spec = importlib.util.spec_from_file_location(
        "t1os_chromium_overlay_applier", OVERLAY_APPLIER
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {OVERLAY_APPLIER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_stage(adapter, stage: Path) -> None:
    stage.mkdir(parents=True)
    chrome = b"\x7fELF fixture\0" + adapter.BUILD_MARKER + b"\0compiled"
    (stage / "chrome").write_bytes(chrome)
    (stage / "chrome_crashpad_handler").write_bytes(
        b"\x7fELF crashpad fixture"
    )
    (stage / "icudtl.dat").write_bytes(b"icu")
    (stage / "resources.pak").write_bytes(b"pak")
    (stage / "locales").mkdir()
    (stage / "locales/en-US.pak").write_bytes(b"locale")
    artifact_hashes = {
        path.relative_to(stage).as_posix():
            hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(stage.rglob("*"))
        if path.is_file()
    }
    runtime = {
        "format": 1,
        "development": True,
        "chromium_version": adapter.VERSION,
        "chromium_revision": adapter.REVISION,
        "chrome_sha256": hashlib.sha256(chrome).hexdigest(),
        "artifacts": artifact_hashes,
        "source_build": {
            "profile": "development",
            "gn_args": list(adapter.DEVELOPMENT_GN_ARGS),
            "strip_policy": "none",
            "required_debug_sections": list(
                adapter.DEVELOPMENT_REQUIRED_DEBUG_SECTIONS
            ),
            "debug_sections": {
                name: list(adapter.DEVELOPMENT_REQUIRED_DEBUG_SECTIONS)
                for name in adapter.SOURCE_DEBUG_RUNTIME_FILES
            },
        },
        "t1os_media_decoder": {
            "available": True,
            "protocol": "T1MD",
            "protocol_version": 1,
            "feature": "T1OSVideoDecoder",
            "brokered_socket": True,
            "descriptor_pool_size": adapter.DESCRIPTOR_POOL_SIZE,
            "chromium_revision": adapter.REVISION,
            "build_marker": adapter.BUILD_MARKER.decode("ascii"),
            "protocol_header_sha256": adapter.PROTOCOL_HEADER_SHA256,
            "source_overlay_sha256": adapter.SOURCE_OVERLAY_SHA256,
        },
    }
    (stage / "t1os-chromium-runtime.json").write_text(
        json.dumps(runtime), encoding="utf-8"
    )


def expect_rejected(call, expected: str) -> None:
    try:
        call()
    except RuntimeError as error:
        require(
            expected in str(error),
            f"wrong rejection for {expected!r}: {error}",
        )
    else:
        raise RuntimeError(f"invalid runtime was accepted: {expected}")


def main() -> int:
    adapter = load_adapter()
    adapter.elf_section_names = lambda path: list(
        adapter.DEVELOPMENT_REQUIRED_DEBUG_SECTIONS
    )
    with tempfile.TemporaryDirectory() as temporary:
        tree = Path(temporary)
        (tree / "_platform_specific/linux_x64").mkdir(parents=True)
        (tree / "LICENSE").write_bytes(b"L")
        (tree / "_platform_specific/linux_x64/lib.so").write_bytes(b"X")
        (tree / "manifest.json").write_bytes(b"M")
        require(
            adapter.tree_sha256(tree)
            == "0590426d699b5cb2f3ef5f08cbc8a370"
               "959822d82e21c3b2f9c4f62470eb3688",
            "external-runtime tree hashing is platform-order dependent",
        )
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        stage = root / "stage"
        destination = root / "chromium"
        program = destination / "program"
        program.mkdir(parents=True)
        libraries = destination / "libraries"
        libraries.mkdir()
        (libraries / "ld-linux-x86-64.so.2").write_bytes(
            b"\x7fELF loader fixture"
        )
        sandbox = program / "chrome-sandbox"
        sandbox.write_bytes(b"T1OS audited sandbox")
        helper = program / "t1os-helper"
        helper.write_bytes(b"T1OS helper")
        tools = destination / "tools"
        tools.mkdir()
        for name in (
            "t1os-chrome-subprocess",
            "t1os-xinput",
            "t1os-xwm",
        ):
            (tools / name).write_bytes(b"\x7fELF T1OS helper " + name.encode())
        (destination / "t1os-path-provider.so").write_bytes(
            b"\x7fELF T1OS path provider"
        )
        stale_library = program / "liboptimization_guide_internal.so"
        stale_library.write_bytes(b"old Google-package ABI")
        version_extra = program / "CHROME_VERSION_EXTRA"
        version_extra.write_text("stable\n", encoding="utf-8")
        (destination / "manifest.json").write_text(
            json.dumps({
                "format": 1,
                "packages": {"preserved": "yes"},
                "t1os_path_provider": "t1os-path-provider.so",
                "t1os_helper_artifacts": {"stale/helper": "0" * 64},
                "t1os_direct_tool_artifacts": {"tools/stale": "0" * 64},
                "t1os_helper_build": {
                    "mode": "stale",
                    "debug_sections": {"stale/helper": []},
                },
            }),
            encoding="utf-8",
        )
        write_stage(adapter, stage)

        adapter.STAGE = stage
        adapter.DESTINATION = destination
        adapter.PROGRAM = program
        commands: list[list[str]] = []

        def fake_output(command: list[str]) -> str:
            commands.append(command)
            return (
                adapter.T1OS_INTERPRETER
                if "--print-interpreter" in command
                else adapter.T1OS_RUNPATH
            )

        adapter.checked_output = fake_output
        safe_program = adapter.PROGRAM
        adapter.PROGRAM = destination.parent / "escaped-program"
        expect_rejected(
            adapter.install,
            "not the exact dedicated destination",
        )
        adapter.PROGRAM = safe_program
        adapter.install()

        require(
            (program / "chrome").read_bytes().startswith(b"\x7fELF fixture"),
            "compiled chrome was not installed",
        )
        require(
            sandbox.read_bytes() == b"T1OS audited sandbox",
            "program/chrome-sandbox was replaced",
        )
        require(
            helper.read_bytes() == b"T1OS helper",
            "a preserved T1OS helper was replaced",
        )
        require(
            (program / "chrome_crashpad_handler").read_bytes()
            == b"\x7fELF crashpad fixture",
            "source-built crashpad handler was not installed",
        )
        require(
            not stale_library.exists(),
            "a stale Google-package private-ABI library survived install",
        )
        require(
            not version_extra.exists(),
            "stale Google CHROME_VERSION_EXTRA survived source install",
        )
        set_commands = [
            command for command in commands
            if "--set-interpreter" in command or "--set-rpath" in command
        ]
        installed_interpreter_checks = [
            command for command in commands
            if "--print-interpreter" in command
            and Path(command[-1]).parent == program
        ]
        require(
            not set_commands
            and {Path(command[-1]).name
                 for command in installed_interpreter_checks}
            == {"chrome", "chrome_crashpad_handler"}
            and (program / "chrome").read_bytes()
            == (stage / "chrome").read_bytes()
            and (program / "chrome_crashpad_handler").read_bytes()
            == (stage / "chrome_crashpad_handler").read_bytes(),
            "installed executables were repatched or did not retain the "
            "exact staged T1OS ELF bytes",
        )
        manifest = json.loads(
            (destination / "manifest.json").read_text(encoding="utf-8")
        )
        require(
            manifest["packages"] == {"preserved": "yes"}
            and manifest["t1os_path_provider"] == "t1os-path-provider.so",
            "existing runtime manifest metadata was not merged",
        )
        require(
            manifest["development"] is True
            and manifest["source_build"]["profile"] == "development"
            and manifest["source_build"]["gn_args"]
            == list(adapter.DEVELOPMENT_GN_ARGS)
            and manifest["source_build"]["strip_policy"] == "none"
            and manifest["source_build"]["required_debug_sections"]
            == list(adapter.DEVELOPMENT_REQUIRED_DEBUG_SECTIONS),
            "installed manifest lost Chromium source-build debug provenance",
        )
        require(
            "t1os_helper_artifacts" not in manifest
            and "t1os_helper_build" not in manifest
            and "t1os_direct_tool_artifacts" not in manifest,
            "adapter retained stale pre-rebuild T1OS helper metadata",
        )
        decoder = manifest["t1os_media_decoder"]
        require(
            decoder["available"] is True
            and decoder["brokered_socket"] is True
            and decoder["protocol"] == "T1MD"
            and decoder["protocol_version"] == 1
            and decoder["descriptor_pool_size"]
            == adapter.DESCRIPTOR_POOL_SIZE
            and decoder["chromium_revision"] == adapter.REVISION
            and decoder["build_marker"]
            == adapter.BUILD_MARKER.decode("ascii")
            and decoder["protocol_header_sha256"]
            == adapter.PROTOCOL_HEADER_SHA256
            and decoder["source_overlay_sha256"]
            == adapter.SOURCE_OVERLAY_SHA256,
            "installed manifest decoder contract is incomplete",
        )

        (stage / "forbidden.cc").write_text("source", encoding="utf-8")
        expect_rejected(
            adapter.load_validated_runtime,
            "loose-language files are forbidden",
        )
        (stage / "forbidden.cc").unlink()

        (stage / "chrome_sandbox").write_bytes(b"upstream sandbox")
        expect_rejected(
            adapter.load_validated_runtime,
            "upstream Chromium sandbox must not be staged",
        )
        (stage / "chrome_sandbox").unlink()

        runtime_path = stage / "t1os-chromium-runtime.json"
        runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
        runtime["source_build"]["gn_args"][-1] = (
            "enable_iterator_debugging=true"
        )
        runtime_path.write_text(json.dumps(runtime), encoding="utf-8")
        expect_rejected(
            adapter.load_validated_runtime,
            "exact development brokered T1MD runtime",
        )

        write_stage_runtime = json.loads(
            runtime_path.read_text(encoding="utf-8")
        )
        write_stage_runtime["source_build"]["gn_args"] = list(
            adapter.DEVELOPMENT_GN_ARGS
        )
        runtime_path.write_text(
            json.dumps(write_stage_runtime), encoding="utf-8"
        )
        runtime = write_stage_runtime
        runtime["t1os_media_decoder"]["protocol_version"] = True
        runtime_path.write_text(json.dumps(runtime), encoding="utf-8")
        expect_rejected(
            adapter.load_validated_runtime,
            "exact development brokered T1MD runtime",
        )

    source_builder = load_source_builder()
    with tempfile.TemporaryDirectory() as temporary:
        checkout = Path(temporary)
        source = checkout / "src"
        source.mkdir()
        arguments = SimpleNamespace(
            source=source,
            depot_tools=checkout / "depot_tools",
        )
        gclient_file = checkout / ".gclient"
        required_solutions = source_builder.required_gclient_solutions(arguments)
        gclient_file.write_text(
            "solutions = " + repr(required_solutions) + "\n",
            encoding="utf-8",
        )
        require(
            source_builder.read_gclient_solutions(gclient_file)
            == required_solutions,
            "canonical PGO-enabled .gclient was rejected",
        )
        wrong_solutions = [dict(required_solutions[0])]
        wrong_solutions[0]["custom_vars"] = {}
        gclient_file.write_text(
            "solutions = " + repr(wrong_solutions) + "\n",
            encoding="utf-8",
        )
        expect_rejected(
            lambda: source_builder.verify_gclient_configuration(arguments),
            "pinned Chromium solution",
        )
        gclient_file.write_text(
            "solutions = " + repr(required_solutions)
            + "\nraise RuntimeError('must never execute')\n",
            encoding="utf-8",
        )
        expect_rejected(
            lambda: source_builder.read_gclient_solutions(gclient_file),
            "only the solutions assignment",
        )
        gclient_file.unlink()
        target = checkout / "gclient-target"
        target.write_text(
            "solutions = " + repr(required_solutions) + "\n",
            encoding="utf-8",
        )
        gclient_file.symlink_to(target)
        expect_rejected(
            lambda: source_builder.read_gclient_solutions(gclient_file),
            "cannot securely open",
        )
        gclient_file.unlink()

        class SyncRunner:
            dry_run = True

            def __init__(self):
                self.commands = []

            def output(self, command, *, cwd=None):
                return ""

            def run(self, command, *, cwd=None, env=None):
                self.commands.append((list(command), cwd))

        sync_runner = SyncRunner()
        source_builder.sync(arguments, sync_runner)
        require(
            sync_runner.commands[0][0][:2] == ["gclient", "config"]
            and "checkout_pgo_profiles=True" in sync_runner.commands[0][0],
            "sync did not establish the pinned PGO-enabled .gclient first",
        )
        sync_index = next(
            index for index, (command, _) in enumerate(sync_runner.commands)
            if command[:2] == ["gclient", "sync"]
        )
        remote_index = next(
            index for index, (command, _) in enumerate(sync_runner.commands)
            if command[:4] == ["git", "remote", "set-url", "origin"]
        )
        require(
            0 < remote_index < sync_index
            and sync_runner.commands[remote_index][0][-1]
            == source_builder.CHROMIUM_SOURCE_URL,
            "sync did not pin the Chromium root origin before gclient sync",
        )

    require(
        "resources" not in source_builder.RUNTIME_DIRECTORIES
        and "resources" not in adapter.DIRECTORIES_TO_PROGRAM,
        "unpacked Chromium development resources entered the runtime set",
    )
    require(
        all(
            name not in source_builder.RUNTIME_FILES
            and name in adapter.FILES_TO_PROGRAM
            for name in ("libqt5_shim.so", "libqt6_shim.so")
        ),
        "optional Chromium Qt shims are staged or unmanaged",
    )
    with tempfile.TemporaryDirectory() as temporary:
        source = Path(temporary) / "src"
        output = source / "out/t1os-development"
        output.mkdir(parents=True)
        expected = (
            source_builder.COMMON_GN_ARGS
            + source_builder.PROFILES["development"]["args"]
        )
        args_file = output / "args.gn"
        args_file.write_text(
            "\n".join(expected) + "\nuse_thin_lto=false\n",
            encoding="utf-8",
        )

        class FakeRunner:
            dry_run = False

            def output(self, command, *, cwd=None):
                return source_builder.CHROMIUM_REVISION

            def run(self, command, *, cwd=None, env=None):
                return None

        provenance_args = SimpleNamespace(
            source=source,
            profile="development",
            depot_tools=Path(temporary) / "depot_tools",
        )
        original_gclient_verifier = (
            source_builder.verify_gclient_dependencies
        )
        source_builder.verify_gclient_dependencies = lambda args: None
        expect_rejected(
            lambda: source_builder.verify_package_provenance(
                provenance_args, FakeRunner()
            ),
            "unexpected",
        )
        args_file.write_text("\n".join(expected) + "\n", encoding="utf-8")
        source_builder.verify_package_provenance(
            provenance_args, FakeRunner()
        )
        source_builder.verify_gclient_dependencies = (
            original_gclient_verifier
        )

        original_run = source_builder.subprocess.run
        source_builder.subprocess.run = lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout="[1/1] would rebuild chrome\n",
            stderr="",
        )
        try:
            expect_rejected(
                lambda: source_builder.require_no_pending_ninja_work(
                    provenance_args
                ),
                "pending Ninja work",
            )
        finally:
            source_builder.subprocess.run = original_run

        expect_rejected(
            lambda: source_builder.validate_stage_destination(
                output,
                source.parent,
                source.parent / "t1os-runtime-development",
            ),
            "non-dedicated Chromium stage",
        )
        runtime_output = source.parent / "runtime-output"
        runtime_output.mkdir()
        for name in source_builder.REQUIRED_RUNTIME_FILES:
            (runtime_output / name).write_bytes(
                b"\x7fELF fixture" if name.startswith("chrome") else b"data"
            )
        runtime_locales = runtime_output / "locales"
        runtime_locales.mkdir()
        (runtime_locales / "en-US.pak").write_bytes(b"compiled locale")
        (runtime_locales / "en-US.pak.info").write_text(
            "GRIT build metadata", encoding="utf-8"
        )
        filtered_stage = source.parent / "t1os-runtime-development"
        source_builder.copy_runtime(
            runtime_output, filtered_stage, filtered_stage
        )
        require(
            (filtered_stage / "locales/en-US.pak").is_file()
            and not (filtered_stage / "locales/en-US.pak.info").exists(),
            "Chromium locale build metadata entered the runtime stage",
        )
        shutil.rmtree(filtered_stage)
        expected_stage = source.parent / "t1os-runtime-development"
        redirected_stage = source.parent / "redirected-stage"
        redirected_stage.mkdir()
        try:
            expected_stage.symlink_to(
                redirected_stage, target_is_directory=True
            )
        except OSError:
            # Some Windows hosts do not grant symlink creation to test users.
            pass
        else:
            expect_rejected(
                lambda: source_builder.validate_stage_destination(
                    output, expected_stage, expected_stage
                ),
                "plain dedicated directory",
            )

    overlay_applier = load_overlay_applier()
    required_import_transforms = {
        "gpu/command_buffer/service/shared_image/"
        "ozone_image_backing_factory.cc":
            "An imported NATIVE_PIXMAP already owns its allocation",
        "ui/ozone/common/native_pixmap_egl_binding.cc":
            "modifier policy=implicit-linear",
        "ui/ozone/platform/x11/x11_surface_factory.cc":
            "direct NativePixmapDmaBuf fallback used by Ozone Wayland",
        "ui/ozone/platform/x11/ozone_platform_x11.cc":
            "Imported DMA-BUFs do not require X11/DRI3 allocation",
        "content/renderer/render_thread_impl.cc":
            "T1OS_MEDIA_DECODER renderer_gate",
        "media/mojo/services/gpu_mojo_media_client.cc":
            "T1OS_MEDIA_DECODER gpu_service_gate",
        "media/gpu/chromeos/mailbox_video_frame_converter.h":
            "output_mappable_",
        "media/gpu/chromeos/mailbox_video_frame_converter.cc":
            "output_mappable_",
        "media/renderers/video_resource_updater.h":
            "mappable_hardware_bridge_reported_",
        "media/renderers/video_resource_updater.cc":
            "T1OS_MEDIA_DECODER presentation_bridge",
    }
    transform_contract = overlay_applier.transformations()
    require(
        all(
            path in transform_contract
            and transform_contract[path][0] == sentinel
            for path, sentinel in required_import_transforms.items()
        ),
        "a required T1OS decode eligibility or direct-EGL DMA-BUF "
        "transformation is absent from the pinned Chromium overlay",
    )
    overlay_source = OVERLAY_APPLIER.read_text(encoding="utf-8")
    for required in (
        "const bool explicit_decode_kill_switch =",
        "base::CommandLine::ForCurrentProcess()->HasSwitch(",
        "const bool preference_disables_selected_decoder =",
        "(!t1os_decoder_enabled || explicit_decode_kill_switch)",
        "return preference_disables_selected_decoder ||",
    ):
        require(
            required in overlay_source,
            "the T1OS decoder still inherits Chromium's derived conventional "
            f"decode preference: {required}",
        )
    for required in (
        "const bool t1os_decoder_requested =",
        "is_gpu_compositing_disabled_ && !t1os_decoder_requested",
        "T1OS_MEDIA_DECODER renderer_factory gpu_channel=1",
        "software_compositing=",
        "T1OS_MEDIA_DECODER presentation_bridge",
    ):
        require(
            required in overlay_source,
            "the T1OS renderer returns before constructing its offscreen "
            f"media GPU factory: {required}",
        )
    for required in (
        "usage == gfx::BufferUsage::SCANOUT ||",
        "usage == gfx::BufferUsage::GPU_READ",
        "modifier policy=egl-preflighted ",
        "render_target=1",
        "root import preflight accepted modifier=",
        "flags &= ~GBM_BO_USE_SCANOUT",
        "flags |= GBM_BO_USE_RENDERING",
        "format, size, usage, modifiers",
        "gbm_bo_create_with_modifiers2",
        "filtered_modifiers.size(), flags",
        "GBM modifier allocator=",
        "EGL_PLATFORM_GBM_KHR",
        "EGL platform=gbm shared_device=1",
        "GetNativeDevice() const",
        "modifier policy=implicit-linear",
        "has_dma_buf_import_modifier && !t1os_implicit_linear",
        "Multiplanar SharedImages import each selected NV12/P010 plane",
        "EGL_DMA_BUF_PLANE0_MODIFIER_LO_EXT",
        "EGL_DMA_BUF_PLANE0_MODIFIER_HI_EXT",
        "selected = SinglePlaneFormat::kBGRX_8888",
        "uses T1OS NVIDIA-native BGRX/XRGB8888",
    ):
        require(
            required in overlay_source,
            "the T1OS root presentation retry can escape the explicit-linear "
            f"modifier policy: {required}",
        )
    marker_header = (
        overlay_applier.OVERLAY
        / overlay_applier.BUILD_MARKER_OVERLAY_PATH
    ).read_bytes()
    protocol_source = (
        overlay_applier.OVERLAY
        / "media/gpu/t1os/t1_media_decode_protocol.h"
    ).read_text(encoding="utf-8")
    decoder_source = (
        overlay_applier.OVERLAY
        / "media/gpu/t1os/t1os_video_decoder.cc"
    ).read_text(encoding="utf-8")
    connection_source = (
        overlay_applier.OVERLAY
        / "media/gpu/t1os/t1os_decoder_connection.cc"
    ).read_text(encoding="utf-8")
    presentation_source = (
        overlay_applier.OVERLAY
        / "ui/ozone/platform/x11/t1os_surfaceless.cc"
    ).read_text(encoding="utf-8")
    require(
        "ConnectionDeletionTaskRunner()" in connection_source
        and "base::MayBlock()" in connection_source
        and "base::WithBaseSyncPrimitives()" in connection_source
        and "base::TaskShutdownBehavior::BLOCK_SHUTDOWN" in connection_source
        and "ConnectionDeletionTaskRunner())," in connection_source,
        "T1MD connection deletion can still join its reader on Chromium's "
        "non-blocking media sequence",
    )
    require(
        "ScopedAllowBlockingForGbmSurface allow_thread_join;"
        in presentation_source
        and "scoped_refptr<T1OSGbmSurface> keep_alive(this);"
        in presentation_source
        and "base::ScopedBlockingCall allow_thread_join"
        not in presentation_source,
        "Chromium presentation teardown or callbacks retain an unsafe GPU "
        "sequence lifetime",
    )
    require(
        "T1_MEDIA_FEATURE_DMABUF" in protocol_source
        and "kCommonRequiredFeatures | T1_MEDIA_FEATURE_DMABUF"
        in connection_source
        and "kCommonRequiredFeatures | T1_MEDIA_FEATURE_LINEAR_MEMORY_OUTPUT"
        in connection_source
        and "kT1OSMediaDecodeOutputLinearMemory" in connection_source
        and "IsValidT1OSDmaBufObject" in decoder_source
        and "IsValidT1OSLinearMemoryObject" in decoder_source
        and "VideoFrame::WrapExternalDataWithLayout" in decoder_source
        and "NativePixmapFrameResource::CreateForT1OS" in decoder_source
        and "frame_converter_->ConvertFrame(std::move(resource))"
        in decoder_source,
        "the NVDEC DMA-BUF/linear output and external-resource ownership "
        "contract is incomplete",
    )
    for required in (
        "constexpr size_t kMaximumInFlightFrames = 3",
        "GBM_BO_USE_SCANOUT | GBM_BO_USE_RENDERING",
        "gbm_surface_create(device",
        "DRM_FORMAT_XRGB8888, kGbmUsage",
        "gbm_surface_lock_front_buffer(gbm_surface_)",
        "gbm_bo_get_fd(buffer)",
        "modifier == DRM_FORMAT_MOD_INVALID",
        "stride < static_cast<uint32_t>(size_.width()) * 4u",
        "rgb-gbm-dmabuf-v1",
        "glfinish-producer-consumer",
        "FrameKey{generation_, frame}",
        "RetireCurrentGeneration()",
        "retired_generations_.emplace(",
        "ProcessControlPacket, weak_this_",
        "std::string(packet.data(), static_cast<size_t>(length))",
        "constexpr base::TimeDelta kDestroyDrainTimeout = base::Milliseconds(50)",
        "producer_sync=glFinish consumer_sync=glFinish",
        "T1OSAuxiliarySurface::Create",
        "T1OS_PRESENTATION_BRIDGE auxiliary top-level contained",
    ):
        require(
            required in presentation_source,
            "the Chromium RGB GBM DMA-BUF ownership contract is incomplete: "
            f"{required}",
        )
    require(
        "gbm_surface_destroy(gbm_surface_);" not in presentation_source
        and "ReleaseBuffer(pending.owner_surface, pending.buffer);"
        not in presentation_source
        and presentation_source.count("pending.owner_surface = nullptr;") >= 3
        and presentation_source.count("pending.buffer = nullptr;") >= 3,
        "Chromium can free an externally allocated GBM object before clearing "
        "its BackupRefPtr-tracked slot",
    )
    for pointer_name, destroy_call in (
        ("failed_surface", "gbm_surface_destroy(failed_surface);"),
        ("unconfigured_surface", "gbm_surface_destroy(unconfigured_surface);"),
        ("retired_gbm", "gbm_surface_destroy(retired_gbm);"),
        ("destroyed_surface", "gbm_surface_destroy(destroyed_surface);"),
    ):
        pointer = presentation_source.index(
            f"gbm_surface* {pointer_name}",
        )
        clear = presentation_source.index(
            " = nullptr;",
            pointer,
        )
        destroy = presentation_source.index(destroy_call, clear)
        require(
            pointer < clear < destroy,
            f"Chromium does not clear {pointer_name} before external GBM destruction",
        )
    for forbidden in (
        "EGLStream",
        "eglCreateStream",
        "eglStreamConsumer",
        "base::NoDestructor",
        "DisconnectConsumer",
        "base::Seconds(5)",
    ):
        require(
            forbidden not in presentation_source,
            f"the Chromium presentation producer still contains {forbidden}",
        )
    resize_start = presentation_source.index("bool T1OSGbmSurface::Resize(")
    resize_end = presentation_source.index(
        "gfx::SwapResult T1OSGbmSurface::SwapBuffers", resize_start
    )
    resize_source = presentation_source[resize_start:resize_end]
    require(
        resize_source.index("RetireCurrentGeneration()")
        < resize_source.index("CreateGbmSurface(size)"),
        "Chromium does not retire the old GBM generation before replacement",
    )
    require(
        "poll(" not in resize_source and "TimedWait" not in resize_source,
        "Chromium resize blocks the GPU sequence waiting for WindowServer",
    )
    require(
        "t1os_presentation_owner_claimed_" in overlay_source
        and "T1OSAuxiliarySurface::Create(egl_display, window)"
        in overlay_source
        and "second view therefore fails explicitly" not in overlay_source,
        "a second top-level can still force a persistent GPU restart loop",
    )
    normalized_marker = overlay_applier.normalized_build_marker_header(
        marker_header
    )
    require(
        overlay_applier.digest_named_files({"marker": normalized_marker})
        != overlay_applier.digest_named_files({
            "marker": normalized_marker.replace(
                b"pool=8", b"pool=9", 1
            )
        }),
        "functional build-marker header bytes are absent from the "
        "source-overlay fingerprint",
    )
    with tempfile.TemporaryDirectory() as temporary:
        source = Path(temporary)
        transformed = source / "patched.txt"
        transformed.write_bytes(b"prefix T1OS sentinel arbitrary edit\n")
        expected_edits = {"patched.txt": b"prefix T1OS sentinel exact\n"}
        upstream_edits = {"patched.txt": b"prefix upstream\n"}
        errors = overlay_applier.reconcile_transformed_files(
            source, expected_edits, upstream_edits, check=True
        )
        require(
            errors and "patched bytes mismatch" in errors[0],
            "sentinel-bearing dirty transformed bytes passed exact check",
        )
        expect_rejected(
            lambda: overlay_applier.reconcile_transformed_files(
                source, expected_edits, upstream_edits, check=False
            ),
            "unrecognized dirty bytes",
        )
        allowlist_errors = overlay_applier.validate_dirty_path_allowlist(
            [(" M", "unrelated/source.cc")],
            {"patched.txt"},
        )
        require(
            allowlist_errors
            and "unexpected dirty Chromium source" in allowlist_errors[0],
            "unrelated dirty root source bypassed the exact allowlist",
        )

    expect_rejected(
        lambda: source_builder.validate_gclient_dependency_state(
            "src/third_party/ffmpeg",
            "a" * 40,
            "a" * 40,
            " M libavcodec/decode.c",
        ),
        "is dirty",
    )

    original_loader = adapter.load_validated_runtime
    original_run_builder = adapter.run_builder
    original_source = adapter.CHROMIUM_SOURCE
    with tempfile.TemporaryDirectory() as temporary:
        source = Path(temporary) / "src"
        source.mkdir()
        adapter.CHROMIUM_SOURCE = source
        commands: list[str] = []

        def missing_stage():
            raise RuntimeError("stage absent")

        adapter.load_validated_runtime = missing_stage
        adapter.run_builder = commands.append
        adapter.prepare()
        require(
            commands
            == ["sync", "apply", "configure", "build", "test", "package"],
            "prepare did not select the complete source build for an absent "
            "validated stage",
        )
    adapter.load_validated_runtime = original_loader
    adapter.run_builder = original_run_builder
    adapter.CHROMIUM_SOURCE = original_source

    require(
        list(adapter.RELEASE_GN_ARGS)
        == source_builder.COMMON_GN_ARGS
        + source_builder.PROFILES["release"]["args"],
        "runtime adapter release contract differs from the source builder",
    )
    adapter.configure_profile("release")
    require(
        adapter.ACTIVE_PROFILE == "release"
        and adapter.STAGE.name == "t1os-runtime-release"
        and adapter.PROFILE_CONTRACTS["release"]["development"] is False,
        "runtime adapter did not select the production release stage",
    )
    adapter.configure_profile("development")

    print("Chromium source-runtime adapter tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
