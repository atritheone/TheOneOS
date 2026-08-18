#!/usr/bin/env python3
"""Pinned Chromium source build for the T1OS brokered media decoder.

This entrypoint never mutates the OS image or a .t1os bundle.  `package`
creates a compiled-runtime staging directory which the normal T1OS build may
consume after review.
"""

from __future__ import annotations

import argparse
import ast
import concurrent.futures
import hashlib
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
OVERLAY_ROOT = REPO / "resource/chromium-source/150.0.7871.181"
MANIFEST = json.loads((OVERLAY_ROOT / "manifest.json").read_text(encoding="utf-8"))
CHROMIUM_REVISION = MANIFEST["chromium_revision"]
DEPOT_TOOLS_REVISION = MANIFEST["depot_tools_revision"]
CHROMIUM_SOURCE_URL = "https://github.com/chromium/chromium.git"
BUILD_MARKER = MANIFEST["build_marker"].encode("ascii")
PROTOCOL_HEADER_SHA256 = MANIFEST["protocol_header_sha256"]
SOURCE_OVERLAY_SHA256 = MANIFEST["source_overlay_sha256"]
SKIA_OVERLAY_DIRTY_STATUS = "M src/gpu/ganesh/gl/GrGLCaps.cpp"

PROFILES = {
    "development": {
        "out": "t1os-development",
        "args": [
            "is_debug=false",
            "is_official_build=false",
            "dcheck_always_on=true",
            "symbol_level=2",
            "blink_symbol_level=1",
            # M150 libc++ removed _LIBCPP_ENABLE_DEBUG_MODE. Its extensive
            # hardening mode remains active in this optimized DCHECK build.
            "enable_iterator_debugging=false",
        ],
    },
    "release": {
        "out": "t1os-release",
        "args": [
            "is_debug=false",
            "is_official_build=true",
            "dcheck_always_on=false",
            "symbol_level=1",
            "blink_symbol_level=0",
        ],
    },
}

COMMON_GN_ARGS = [
    "target_os=\"linux\"",
    "target_cpu=\"x64\"",
    "is_component_build=false",
    "enable_t1os_video_decoder=true",
    "proprietary_codecs=true",
    "ffmpeg_branding=\"Chrome\"",
    "enable_hevc_parser_and_hw_decoder=true",
    "enable_platform_hevc=true",
    "use_sysroot=true",
    "use_remoteexec=false",
    # Keep the persistent incremental output directory on Ninja. Chromium's
    # default can change to Siso as depot_tools evolves; mixing generators
    # makes the wrapper stop before compilation and would otherwise require a
    # needless full clean rebuild.
    "use_siso=false",
]

RUNTIME_FILES = [
    "chrome",
    "chrome_crashpad_handler",
    "chrome_100_percent.pak",
    "chrome_200_percent.pak",
    "resources.pak",
    "icudtl.dat",
    "snapshot_blob.bin",
    "v8_context_snapshot.bin",
    "libEGL.so",
    "libGLESv2.so",
    "liboptimization_guide_internal.so",
    "libvk_swiftshader.so",
    "libvulkan.so.1",
    "vk_swiftshader_icd.json",
]
RUNTIME_DIRECTORIES = [
    "locales",
    "MEIPreload",
    "IwaKeyDistribution",
    "PrivacySandboxAttestationsPreloaded",
]
REQUIRED_RUNTIME_FILES = {
    "chrome", "chrome_crashpad_handler", "icudtl.dat", "resources.pak",
}
REQUIRED_RUNTIME_DIRECTORIES = {"locales"}
ELF_RUNTIME_FILES = {
    "chrome",
    "chrome_crashpad_handler",
    "libEGL.so",
    "libGLESv2.so",
    "liboptimization_guide_internal.so",
    "libvk_swiftshader.so",
    "libvulkan.so.1",
}
EXECUTABLE_RUNTIME_FILES = {"chrome", "chrome_crashpad_handler"}
BUILD_TARGETS = ("chrome", "media_unittests", "sandbox_linux_unittests")
T1OS_TARGETED_RELINK_OBJECTS = (
    "obj/skia/skia/GrGLCaps.o",
    "obj/components/viz/service/service/direct_renderer.o",
    "obj/components/viz/service/service/skia_output_surface_impl_on_gpu.o",
    "obj/components/viz/service/service/root_compositor_frame_sink_impl.o",
    "obj/components/viz/host/host/gpu_host_impl.o",
    "obj/content/browser/browser/gpu_process_host.o",
    "obj/content/browser/browser/viz_process_transport_factory.o",
    "obj/content/browser/browser/child_process_launcher_helper.o",
    "obj/content/child/child/child_thread_impl.o",
    "obj/content/gpu/gpu_sources/gpu_child_thread.o",
    "obj/content/gpu/gpu_sources/gpu_main.o",
    "obj/mojo/core/impl_for_embedder/channel_posix.o",
    "obj/content/browser/browser/t1os_media_decode_broker.o",
    "obj/content/common/common/gpu_pre_sandbox_hook_linux.o",
    "obj/content/common/sandbox_support_linux/zygote_communication_linux.o",
    "obj/content/renderer/renderer/render_thread_impl.o",
    "obj/media/base/base/t1os_media_switches.o",
    "obj/media/gpu/chromeos/common/mailbox_video_frame_converter.o",
    "obj/media/gpu/chromeos/common/native_pixmap_frame_resource.o",
    "obj/media/gpu/t1os_video_decoder/t1os_decoder_connection.o",
    "obj/media/gpu/t1os_video_decoder/t1os_video_decoder.o",
    "obj/media/mojo/mojom/stable/native_pixmap_handle/"
    "native_pixmap_handle.mojom.o",
    "obj/media/mojo/mojom/stable/native_pixmap_handle/"
    "native_pixmap_handle_mojom_traits.o",
    "obj/media/mojo/mojom/stable/native_pixmap_handle_shared_cpp_sources/"
    "native_pixmap_handle.mojom-shared.o",
    "obj/media/mojo/clients/clients/mojo_codec_factory.o",
    "obj/media/mojo/services/services/gpu_mojo_media_client.o",
    "obj/media/mojo/services/services/gpu_mojo_media_client_linux.o",
    "obj/media/mojo/services/services/oop_video_decoder_factory_service.o",
    "obj/media/renderers/renderers/video_resource_updater.o",
    "obj/gpu/command_buffer/service/gles2_sources/ozone_image_gl_textures_holder.o",
    "obj/gpu/ipc/service/service/gpu_init.o",
    "obj/sandbox/policy/policy/bpf_gpu_policy_linux.o",
    "obj/ui/gl/gl/gl_utils.o",
    "obj/ui/gfx/linux/gbm/gbm_wrapper.o",
    "obj/ui/gfx/linux/gbm_support_x11/gbm_support_x11.o",
    "obj/ui/gfx/memory_buffer_sources/native_pixmap_handle.o",
    "obj/ui/gfx/mojom/native_handle_types/native_handle_types.mojom.o",
    "obj/ui/gfx/mojom/native_handle_types_mojom_traits/"
    "native_handle_types_mojom_traits.o",
    "obj/ui/gfx/mojom/native_handle_types_shared_cpp_sources/"
    "native_handle_types.mojom-shared.o",
    "obj/ui/ozone/common/common/native_pixmap_egl_binding.o",
    "obj/ui/ozone/platform/x11/x11/t1os_gbm_pixmap.o",
    "obj/ui/ozone/platform/x11/x11/t1os_surfaceless.o",
    "obj/ui/ozone/platform/x11/x11/x11_surface_factory.o",
)
T1OS_TARGETED_TEST_OBJECTS = (
    "obj/media/gpu/unit_tests/t1os_video_decoder_unittest.o",
    "obj/sandbox/policy/tests/t1os_gpu_seal_policy_unittest.o",
)
T1OS_PIPELINE_RELINK_OBJECTS = (
    "obj/media/base/base/t1os_media_switches.o",
    "obj/media/audio/audio/alsa_output.o",
    "obj/media/audio/audio/audio_manager_alsa.o",
    "obj/content/browser/browser/t1os_media_decode_broker.o",
    "obj/media/gpu/t1os_video_decoder/t1os_decoder_connection.o",
    "obj/ui/ozone/platform/x11/x11/t1os_surfaceless.o",
)
T1OS_TARGETED_RELINK_ARCHIVES = (
    "obj/skia/libskia.a",
    "obj/components/viz/service/libservice.a",
    "obj/content/renderer/librenderer.a",
    "obj/content/child/libchild.a",
    "obj/content/gpu/libgpu_sources.a",
    "obj/media/mojo/services/libmedia_mojo_services.a",
    "obj/gpu/ipc/service/libgpu_ipc_service.a",
    "obj/gpu/command_buffer/service/libgles2_sources.a",
    "obj/sandbox/policy/libpolicy.a",
    "obj/ui/gl/libgl_wrapper.a",
)
T1OS_TARGETED_ARCHIVE_GRAPHS = {
    "obj/skia/libskia.a":
        "obj/skia/skia.ninja",
    "obj/components/viz/service/libservice.a":
        "obj/components/viz/service/service.ninja",
    "obj/content/renderer/librenderer.a":
        "obj/content/renderer/renderer.ninja",
    "obj/content/child/libchild.a":
        "obj/content/child/child.ninja",
    "obj/content/gpu/libgpu_sources.a":
        "obj/content/gpu/gpu_sources.ninja",
    "obj/gpu/ipc/service/libgpu_ipc_service.a":
        "obj/gpu/ipc/service/service.ninja",
    "obj/gpu/command_buffer/service/libgles2_sources.a":
        "obj/gpu/command_buffer/service/gles2_sources.ninja",
    "obj/sandbox/policy/libpolicy.a":
        "obj/sandbox/policy/policy.ninja",
    "obj/ui/gl/libgl_wrapper.a":
        "obj/ui/gl/gl.ninja",
    # Recovery-only entry: an interrupted broad Ninja run can leave this thin
    # archive referring to generated Blink objects removed by a later GN gen.
    "obj/third_party/blink/renderer/bindings/core/v8/libv8.a":
        "obj/third_party/blink/renderer/bindings/core/v8/v8.ninja",
    "obj/media/mojo/services/libmedia_mojo_services.a":
        "obj/media/mojo/services/services.ninja",
}
T1OS_TARGETED_LINK_GRAPHS = {
    "chrome": (
        "obj/chrome/chrome_initial.ninja",
        "build ./chrome: link ",
        "chrome.rsp",
    ),
    "media_unittests": (
        "obj/media/media_unittests.ninja",
        "build ./media_unittests: link ",
        "media_unittests.rsp",
    ),
    "sandbox_linux_unittests": (
        "obj/sandbox/linux/sandbox_linux_unittests.ninja",
        "build ./sandbox_linux_unittests: link ",
        "sandbox_linux_unittests.rsp",
    ),
}
ALLOWED_DATA_SUFFIXES = {
    ".bin", ".dat", ".json", ".pak", ".pb", ".png", ".svg", ".xml",
}
T1OS_INTERPRETER = (
    "/the one/software/chromium/libraries/ld-linux-x86-64.so.2"
)
T1OS_RUNPATH = "/the one/software/chromium/libraries"
SOURCE_DEBUG_RUNTIME_FILES = ("chrome", "chrome_crashpad_handler")
DEVELOPMENT_REQUIRED_DEBUG_SECTIONS = (
    ".debug_info",
    ".debug_line",
    ".symtab",
)


class Runner:
    def __init__(self, dry_run: bool) -> None:
        self.dry_run = dry_run

    def run(
        self,
        command: list[str],
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        rendered = " ".join(command)
        print(f"+ {rendered}" + (f"  (cwd={cwd})" if cwd else ""))
        if not self.dry_run:
            subprocess.run(command, cwd=cwd, env=env, check=True)

    def output(self, command: list[str], *, cwd: Path | None = None) -> str:
        print(f"+ {' '.join(command)}" + (f"  (cwd={cwd})" if cwd else ""))
        if self.dry_run:
            return ""
        return subprocess.check_output(command, cwd=cwd, text=True).strip()


def depot_env(depot_tools: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["PATH"] = str(depot_tools) + os.pathsep + env.get("PATH", "")
    # This checkout is part of the reproducible Chromium build contract.
    # depot_tools otherwise updates itself while gclient is running, after
    # ensure_pin() has validated it, and leaves the next build unbuildable.
    env["DEPOT_TOOLS_UPDATE"] = "0"
    return env


def ensure_pin(path: Path, revision: str, label: str, runner: Runner) -> None:
    actual = runner.output(["git", "rev-parse", "HEAD"], cwd=path)
    if not runner.dry_run and actual != revision:
        raise RuntimeError(f"{label} is {actual}; required {revision}")


def fetch(args: argparse.Namespace, runner: Runner) -> None:
    if not args.depot_tools.exists():
        runner.run(
            [
                "git",
                "clone",
                "https://chromium.googlesource.com/chromium/tools/depot_tools.git",
                str(args.depot_tools),
            ]
        )
    runner.run(["git", "checkout", DEPOT_TOOLS_REVISION], cwd=args.depot_tools)
    args.source.parent.mkdir(parents=True, exist_ok=True)
    if not args.source.exists():
        runner.run(
            ["fetch", "--nohooks", "chromium"],
            cwd=args.source.parent,
            env=depot_env(args.depot_tools),
        )
    sync(args, runner)


def sync(args: argparse.Namespace, runner: Runner) -> None:
    ensure_pin(args.depot_tools, DEPOT_TOOLS_REVISION, "depot_tools", runner)
    if not args.source.exists():
        raise RuntimeError(f"Chromium source is absent: {args.source}")
    checkout = args.source.parent
    gclient_file = checkout / ".gclient"
    if gclient_file.is_symlink() or (
        gclient_file.exists() and not gclient_file.is_file()
    ):
        raise RuntimeError(f"{gclient_file}: must be a regular non-symlink file")
    runner.run(
        [
            "gclient",
            "config",
            "--unmanaged",
            "--name",
            args.source.name,
            "--custom-var",
            "checkout_pgo_profiles=True",
            CHROMIUM_SOURCE_URL,
        ],
        cwd=checkout,
        env=depot_env(args.depot_tools),
    )
    if not runner.dry_run:
        verify_gclient_configuration(args)
    runner.run(
        ["git", "remote", "set-url", "origin", CHROMIUM_SOURCE_URL],
        cwd=args.source,
    )
    if not runner.dry_run:
        verify_chromium_root_remote(args)
    runner.run(["git", "fetch", "origin", "refs/tags/150.0.7871.181"], cwd=args.source)
    runner.run(["git", "checkout", "--detach", CHROMIUM_REVISION], cwd=args.source)
    runner.run(
        [
            "gclient",
            "sync",
            "-D",
            "--force",
            "--revision",
            f"{args.source.name}@{CHROMIUM_REVISION}",
        ],
        cwd=checkout,
        env=depot_env(args.depot_tools),
    )
    ensure_pin(args.source, CHROMIUM_REVISION, "Chromium", runner)


def apply_overlay(args: argparse.Namespace, runner: Runner) -> None:
    apply_script = OVERLAY_ROOT / "apply.py"
    runner.run([sys.executable, str(apply_script), "--source", str(args.source)])
    runner.run(
        [sys.executable, str(apply_script), "--source", str(args.source), "--check"]
    )


def output_directory(args: argparse.Namespace) -> Path:
    return args.source / "out" / PROFILES[args.profile]["out"]


def configure(args: argparse.Namespace, runner: Runner) -> None:
    ensure_pin(args.source, CHROMIUM_REVISION, "Chromium", runner)
    gn_args = COMMON_GN_ARGS + PROFILES[args.profile]["args"]
    runner.run(
        ["gn", "gen", str(output_directory(args)), f"--args={' '.join(gn_args)}"],
        cwd=args.source,
        env=depot_env(args.depot_tools),
    )
    runner.run(
        ["gn", "args", str(output_directory(args)), "--list", "--short"],
        cwd=args.source,
        env=depot_env(args.depot_tools),
    )


def build(args: argparse.Namespace, runner: Runner) -> None:
    runner.run(
        [
            str(args.source / "third_party/ninja/ninja"),
            "-j16",
            "-C",
            str(output_directory(args)),
            *BUILD_TARGETS,
        ],
        cwd=args.source,
        env=depot_env(args.depot_tools),
    )


def ninja_target_commands(
    args: argparse.Namespace, targets: tuple[str, ...]
) -> dict[str, str]:
    """Return GN's final command for each explicit target in one graph scan."""

    ninja = args.source / "third_party/ninja/ninja"
    output_bytes = subprocess.check_output(
        [
            str(ninja),
            "-C",
            str(output_directory(args)),
            "-t",
            "commands",
            "-s",
            *targets,
        ],
        cwd=args.source,
        env=depot_env(args.depot_tools),
    )
    # The full dependency command stream can contain a byte from an upstream
    # generated path which is not valid UTF-8. The selected compiler/archive/
    # linker command and every T1OS-owned target are ASCII; replacement is safe
    # for unselected dependency lines and the exact-output check below fails
    # closed if the selected command itself were affected.
    output = output_bytes.decode("utf-8", errors="replace")
    commands = [line for line in output.splitlines() if line.strip()]
    if len(commands) != len(targets):
        raise RuntimeError(
            "GN targeted command count differs from requested outputs: "
            f"commands={len(commands)} targets={len(targets)}"
        )
    result = dict(zip(targets, commands, strict=True))
    for target, command in result.items():
        if target not in command:
            raise RuntimeError(
                f"final generated command does not produce {target}: "
                f"{command[:240]}"
            )
    return result


def run_target_command(
    args: argparse.Namespace, target: str, command: str
) -> None:
    out = output_directory(args)
    print(f"+ targeted Chromium output {target}", flush=True)
    if target in T1OS_TARGETED_ARCHIVE_GRAPHS:
        graph = out / T1OS_TARGETED_ARCHIVE_GRAPHS[target]
        prefix = f"build {target}: alink "
        edge = next(
            (
                line
                for line in graph.read_text(
                    encoding="utf-8", errors="strict"
                ).splitlines()
                if line.startswith(prefix)
            ),
            None,
        )
        if edge is None:
            raise RuntimeError(f"GN archive edge is absent for {target}")
        explicit_inputs = edge[len(prefix):].split(" | ", 1)[0].split()
        if not explicit_inputs or any(not name.endswith(".o") for name in explicit_inputs):
            raise RuntimeError(f"GN archive inputs are invalid for {target}")
        archive_part = command.split("&&", 1)
        if len(archive_part) != 2:
            raise RuntimeError(f"GN archive command is malformed for {target}")
        archive_argv = shlex.split(archive_part[1].strip())
        response_indexes = [
            index
            for index, value in enumerate(archive_argv)
            if value.startswith("@")
        ]
        if len(response_indexes) != 1:
            raise RuntimeError(
                f"GN archive command has an invalid response file for {target}"
            )
        index = response_indexes[0]
        archive_argv[index:index + 1] = explicit_inputs
        archive_path = out / target
        archive_path.unlink(missing_ok=True)
        subprocess.run(archive_argv, cwd=out, check=True)
        return
    response_path = None
    if target in T1OS_TARGETED_LINK_GRAPHS:
        graph_name, prefix, response_name = T1OS_TARGETED_LINK_GRAPHS[target]
        graph = out / graph_name
        edge = next(
            (
                line
                for line in graph.read_text(
                    encoding="utf-8", errors="strict"
                ).splitlines()
                if line.startswith(prefix)
            ),
            None,
        )
        if edge is None:
            raise RuntimeError(f"GN link edge is absent for {target}")
        explicit_inputs = edge[len(prefix):].split(" | ", 1)[0].split()
        if not explicit_inputs or any(name.startswith(("$", "|")) for name in explicit_inputs):
            raise RuntimeError(f"GN link inputs are invalid for {target}")
        response_path = out / response_name
        response_switches = (
            "@./" + response_name,
            '@"./' + response_name + '"',
        )
        if sum(command.count(value) for value in response_switches) != 1:
            raise RuntimeError(
                f"GN link command has an invalid response file for {target}"
            )
        response_path.write_text(
            "\n".join(explicit_inputs) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    try:
        subprocess.run(
            ["bash", "-lc", command],
            cwd=out,
            env=depot_env(args.depot_tools),
            check=True,
        )
    finally:
        if response_path is not None:
            response_path.unlink(missing_ok=True)


def targeted_relink(args: argparse.Namespace, runner: Runner) -> None:
    """Recover a T1OS-only relink when global Ninja history is unavailable.

    This intentionally compiles the complete set of production translation
    units that implement the T1OS decoder and its presentation bridge, plus
    the pinned Skia NVIDIA MSAA capability correction. It rebuilds the static
    archives containing those units and executes GN's exact chrome link
    command. It does not manufacture Ninja freshness for unrelated outputs.
    """

    if runner.dry_run:
        print("+ targeted T1OS Chromium compile, archive, link, test, package")
        return
    verify_package_provenance(args, runner)
    all_targets = (
        *T1OS_TARGETED_RELINK_OBJECTS,
        *T1OS_TARGETED_RELINK_ARCHIVES,
        "chrome",
        *T1OS_TARGETED_TEST_OBJECTS,
        "media_unittests",
        "sandbox_linux_unittests",
    )
    commands = ninja_target_commands(args, all_targets)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(
                run_target_command, args, target, commands[target]
            ): target
            for target in T1OS_TARGETED_RELINK_OBJECTS
        }
        for future in concurrent.futures.as_completed(futures):
            target = futures[future]
            try:
                future.result()
            except Exception as error:
                raise RuntimeError(
                    f"targeted Chromium compile failed for {target}: {error}"
                ) from error
    for target in T1OS_TARGETED_RELINK_ARCHIVES:
        run_target_command(args, target, commands[target])
    run_target_command(args, "chrome", commands["chrome"])
    for target in T1OS_TARGETED_TEST_OBJECTS:
        run_target_command(args, target, commands[target])
    run_target_command(
        args, "media_unittests", commands["media_unittests"]
    )
    run_target_command(
        args, "sandbox_linux_unittests", commands["sandbox_linux_unittests"]
    )
    chrome = output_directory(args) / "chrome"
    if not file_contains(chrome, BUILD_MARKER):
        raise RuntimeError(
            "targeted Chromium relink lacks the exact T1OS media build marker"
        )
    test(args, runner)
    package(args, runner, require_full_ninja_freshness=False)


def pipeline_relink(args: argparse.Namespace, runner: Runner) -> None:
    """Compile and relink only the measured decode/presentation correction.

    The persistent output has unrelated stale generated edges. Invoking Ninja
    for even one object currently schedules those edges, so this path obtains
    GN's final commands read-only and executes only the three named objects,
    the Chrome link, the media-test link, and the focused T1OS tests.
    """

    if args.profile != "development":
        raise RuntimeError("pipeline relink is development-profile only")
    if runner.dry_run:
        print("+ bounded T1OS pipeline compile, link, test, package")
        return
    verify_package_provenance(args, runner)
    all_targets = (
        *T1OS_PIPELINE_RELINK_OBJECTS,
        "chrome",
        "media_unittests",
    )
    commands = ninja_target_commands(args, all_targets)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            executor.submit(
                run_target_command, args, target, commands[target]
            ): target
            for target in T1OS_PIPELINE_RELINK_OBJECTS
        }
        for future in concurrent.futures.as_completed(futures):
            target = futures[future]
            try:
                future.result()
            except Exception as error:
                raise RuntimeError(
                    f"bounded pipeline compile failed for {target}: {error}"
                ) from error
    run_target_command(
        args, "media_unittests", commands["media_unittests"]
    )
    runner.run(
        [
            str(output_directory(args) / "media_unittests"),
            "--gtest_filter=T1OS*",
            "--test-launcher-jobs=1",
        ],
        cwd=output_directory(args),
    )
    run_target_command(args, "chrome", commands["chrome"])
    chrome = output_directory(args) / "chrome"
    if not file_contains(chrome, BUILD_MARKER):
        raise RuntimeError(
            "pipeline Chromium relink lacks the exact T1OS media build marker"
        )
    package(args, runner, require_full_ninja_freshness=False)


def test(args: argparse.Namespace, runner: Runner) -> None:
    out = output_directory(args)
    runner.run(
        [
            str(out / "media_unittests"),
            "--gtest_filter=T1OS*",
            "--test-launcher-jobs=1",
        ],
        cwd=out,
    )
    runner.run(
        [
            str(out / "sandbox_linux_unittests"),
            "--gtest_filter=T1OSGpuSealPolicy.*",
            "--test-launcher-jobs=1",
        ],
        cwd=out,
    )


def validate_stage_destination(
    out: Path, stage: Path, expected_stage: Path
) -> None:
    if stage != expected_stage:
        raise RuntimeError(
            f"refusing non-dedicated Chromium stage {stage}; "
            f"required {expected_stage}"
        )
    if stage == out or stage in out.parents or out in stage.parents:
        raise RuntimeError(
            f"Chromium output and stage roots overlap: out={out}, stage={stage}"
        )
    if stage.exists() and (stage.is_symlink() or not stage.is_dir()):
        raise RuntimeError(
            f"Chromium stage must be a plain dedicated directory: {stage}"
        )
    if stage.parent.is_symlink():
        raise RuntimeError(
            f"Chromium stage parent must not be a symlink: {stage.parent}"
        )


def copy_runtime(out: Path, stage: Path, expected_stage: Path) -> None:
    validate_stage_destination(out, stage, expected_stage)
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    for name in RUNTIME_FILES:
        source = out / name
        if source.exists():
            shutil.copy2(source, stage / name)
    for name in RUNTIME_DIRECTORIES:
        source = out / name
        if source.is_dir():
            destination = stage / name
            if name != "locales":
                shutil.copytree(source, destination)
                continue
            destination.mkdir()
            for locale in sorted(source.iterdir()):
                if locale.is_symlink() or not locale.is_file():
                    raise RuntimeError(
                        f"unexpected Chromium locale artifact: {locale}"
                    )
                # GRIT emits human-readable resource-map sidecars alongside
                # the compiled packs. They are build metadata, not runtime
                # input, and must never enter the T1OS payload.
                if locale.name.endswith(".pak.info"):
                    continue
                if locale.suffix.lower() != ".pak":
                    raise RuntimeError(
                        f"unexpected Chromium locale artifact: {locale}"
                    )
                shutil.copy2(locale, destination / locale.name)
    missing_files = sorted(
        name for name in REQUIRED_RUNTIME_FILES
        if not (stage / name).is_file()
    )
    missing_directories = sorted(
        name for name in REQUIRED_RUNTIME_DIRECTORIES
        if not (stage / name).is_dir()
    )
    if missing_files or missing_directories:
        raise RuntimeError(
            "compiled Chromium runtime is incomplete: "
            f"files={missing_files}, directories={missing_directories}"
        )


def file_contains(path: Path, needle: bytes) -> bool:
    overlap = max(0, len(needle) - 1)
    previous = b""
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            combined = previous + chunk
            if needle in combined:
                return True
            previous = combined[-overlap:] if overlap else b""
    return False


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def elf_section_names(path: Path) -> list[str]:
    output = subprocess.check_output(
        ["readelf", "--wide", "--sections", str(path)],
        text=True,
    )
    names: set[str] = set()
    for line in output.splitlines():
        match = re.match(r"^\s*\[\s*(\d+)\]\s+(\S+)", line)
        if match and int(match.group(1)) != 0:
            names.add(match.group(2))
    if not names:
        raise RuntimeError(f"ELF section inventory is empty: {path}")
    return sorted(names)


def patch_t1os_elf(path: Path, executable: bool) -> None:
    command = ["patchelf"]
    if executable:
        command += ["--set-interpreter", T1OS_INTERPRETER]
    command += ["--set-rpath", T1OS_RUNPATH, str(path)]
    subprocess.run(command, check=True)
    if executable:
        interpreter = subprocess.check_output(
            ["patchelf", "--print-interpreter", str(path)], text=True
        ).strip()
        if interpreter != T1OS_INTERPRETER:
            raise RuntimeError(
                f"wrong T1OS interpreter for {path}: {interpreter}"
            )
    runpath = subprocess.check_output(
        ["patchelf", "--print-rpath", str(path)], text=True
    ).strip()
    if runpath != T1OS_RUNPATH:
        raise RuntimeError(f"wrong T1OS RUNPATH for {path}: {runpath}")


def audit_runtime_artifacts(stage: Path) -> None:
    for path in sorted(stage.rglob("*")):
        if path.is_symlink():
            raise RuntimeError(f"runtime symlinks are forbidden: {path}")
        if not path.is_file():
            continue
        relative = path.relative_to(stage).as_posix()
        if "/" not in relative and relative in ELF_RUNTIME_FILES:
            with path.open("rb") as stream:
                magic = stream.read(4)
            if magic != b"\x7fELF":
                raise RuntimeError(f"runtime ELF is malformed: {relative}")
            continue
        if path.suffix.lower() not in ALLOWED_DATA_SUFFIXES:
            raise RuntimeError(
                f"runtime artifact is not compiled code or approved data: "
                f"{relative}"
            )


def verify_dynamic_dependencies(stage: Path) -> None:
    libraries = REPO / "source/software/chromium/libraries"
    loader = libraries / "ld-linux-x86-64.so.2"
    if not loader.is_file():
        raise RuntimeError(f"T1OS runtime loader is absent: {loader}")
    # Match the deployed contract exactly. Chromium's program directory is
    # deliberately not a loader search path; private dependencies must resolve
    # from the immutable T1OS library bundle.
    library_path = str(libraries)
    for name in sorted(ELF_RUNTIME_FILES):
        path = stage / name
        if not path.is_file():
            continue
        result = subprocess.run(
            [
                str(loader),
                "--library-path",
                library_path,
                "--list",
                str(path),
            ],
            text=True,
            capture_output=True,
        )
        output = result.stdout + result.stderr
        if result.returncode != 0 or "not found" in output:
            raise RuntimeError(
                f"unresolved T1OS DT_NEEDED dependency for {name}:\n{output}"
            )


def verify_compiled_runtime(stage: Path) -> None:
    chrome = stage / "chrome"
    if not file_contains(chrome, BUILD_MARKER):
        raise RuntimeError(
            "compiled chrome does not contain the exact T1OS media build marker"
        )
    audit_runtime_artifacts(stage)
    verify_dynamic_dependencies(stage)


def verify_package_provenance(
    args: argparse.Namespace, runner: Runner
) -> None:
    ensure_pin(args.source, CHROMIUM_REVISION, "Chromium", runner)
    apply_script = OVERLAY_ROOT / "apply.py"
    runner.run(
        [
            sys.executable,
            str(apply_script),
            "--source",
            str(args.source),
            "--check",
        ]
    )
    verify_gclient_dependencies(args)

    args_file = output_directory(args) / "args.gn"
    if not args_file.is_file():
        raise RuntimeError(
            f"configured GN arguments are absent: {args_file}"
        )
    actual: dict[str, str] = {}
    for line_number, raw_line in enumerate(
        args_file.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise RuntimeError(
                f"malformed GN argument at {args_file}:{line_number}"
            )
        key, value = (part.strip() for part in line.split("=", 1))
        if not key or key in actual:
            raise RuntimeError(
                f"duplicate or empty GN argument at "
                f"{args_file}:{line_number}: {key!r}"
            )
        actual[key] = value

    expected: dict[str, str] = {}
    for assignment in COMMON_GN_ARGS + PROFILES[args.profile]["args"]:
        key, value = (part.strip() for part in assignment.split("=", 1))
        expected[key] = value
    mismatches = {
        key: {"required": value, "actual": actual.get(key)}
        for key, value in expected.items()
        if actual.get(key) != value
    }
    unexpected = {
        key: value for key, value in actual.items() if key not in expected
    }
    if mismatches or unexpected:
        raise RuntimeError(
            "GN output does not match the requested pinned T1OS profile: "
            f"mismatched={mismatches}, unexpected={unexpected}"
        )


def required_gclient_solutions(args: argparse.Namespace) -> list[dict[str, object]]:
    return [{
        "name": args.source.name,
        "url": CHROMIUM_SOURCE_URL,
        "deps_file": "DEPS",
        "managed": False,
        "custom_deps": {},
        # Official Linux builds default to chrome_pgo_phase=2. Chromium's
        # update_pgo_profiles.py requires this exact custom variable so the
        # DEPS-selected Linux profile is present before GN generation.
        "custom_vars": {"checkout_pgo_profiles": True},
    }]


def read_gclient_solutions(path: Path) -> object:
    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise RuntimeError(f"{path}: cannot securely open .gclient: {error}") from error
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_uid != os.geteuid()
            or before.st_mode & 0o022
            or not 0 < before.st_size <= 65536
        ):
            raise RuntimeError(
                f"{path}: must be an owner-controlled regular file with one link"
            )
        chunks: list[bytes] = []
        remaining = before.st_size + 1
        while remaining:
            chunk = os.read(descriptor, min(remaining, 65536))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
        if (
            (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        ):
            raise RuntimeError(f"{path}: changed while it was being verified")
        payload = b"".join(chunks)
        if len(payload) != before.st_size:
            raise RuntimeError(f"{path}: size changed while it was being verified")
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as error:
            raise RuntimeError(f"{path}: is not UTF-8") from error
    finally:
        os.close(descriptor)

    tree = ast.parse(text, filename=str(path))
    if len(tree.body) != 1:
        raise RuntimeError(f"{path}: must contain only the solutions assignment")
    statement = tree.body[0]
    if not (
        isinstance(statement, ast.Assign)
        and len(statement.targets) == 1
        and isinstance(statement.targets[0], ast.Name)
        and statement.targets[0].id == "solutions"
    ):
        raise RuntimeError(f"{path}: solutions assignment is missing")
    return ast.literal_eval(statement.value)


def verify_gclient_configuration(args: argparse.Namespace) -> None:
    gclient_file = args.source.parent / ".gclient"
    if read_gclient_solutions(gclient_file) != required_gclient_solutions(args):
        raise RuntimeError(
            f"{gclient_file}: configuration does not match the pinned "
            "Chromium solution"
        )


def verify_chromium_root_remote(args: argparse.Namespace) -> None:
    try:
        remote = subprocess.check_output(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=args.source,
            text=True,
            timeout=30,
        ).strip()
    except (OSError, subprocess.CalledProcessError) as error:
        raise RuntimeError("could not read Chromium origin URL") from error
    if remote != CHROMIUM_SOURCE_URL:
        raise RuntimeError(
            f"Chromium origin is {remote!r}; required {CHROMIUM_SOURCE_URL!r}"
        )


def parse_gclient_revinfo(output: str) -> dict[str, str]:
    revisions: dict[str, str] = {}
    for line in output.splitlines():
        path, separator, value = line.partition(": ")
        if separator and value.startswith(("http://", "https://")):
            revisions[path] = value
    return revisions


def parse_git_revision_url(value: str) -> tuple[str, str] | None:
    match = re.fullmatch(r"(.+\.git)@([0-9a-f]{40})", value)
    if not match:
        return None
    return match.group(1), match.group(2)


def validate_gclient_dependency_state(
    path: str, expected: str, actual: str, dirty_status: str
) -> None:
    if actual != expected:
        raise RuntimeError(
            f"gclient dependency {path} is {actual}; required {expected}"
        )
    if dirty_status:
        raise RuntimeError(
            f"gclient dependency {path} is dirty: {dirty_status!r}"
        )


def verify_gclient_dependencies(args: argparse.Namespace) -> None:
    checkout = args.source.parent
    verify_gclient_configuration(args)
    verify_chromium_root_remote(args)

    print("Auditing DEPS-selected gclient revisions...", flush=True)
    expected_output = subprocess.check_output(
        ["gclient", "revinfo"],
        cwd=checkout,
        env=depot_env(args.depot_tools),
        text=True,
        timeout=300,
    )
    print("Auditing actual gclient checkout revisions...", flush=True)
    actual_output = subprocess.check_output(
        ["gclient", "revinfo", "-a"],
        cwd=checkout,
        env=depot_env(args.depot_tools),
        text=True,
        timeout=300,
    )
    expected_revisions = parse_gclient_revinfo(expected_output)
    actual_revisions = parse_gclient_revinfo(actual_output)
    root_record = actual_revisions.get(args.source.name, "")
    if not root_record.endswith("@" + CHROMIUM_REVISION):
        raise RuntimeError("gclient root revision does not match Chromium pin")

    expected_git_paths = {
        relative
        for relative, value in expected_revisions.items()
        if relative != args.source.name
        and ":" not in relative
        and parse_git_revision_url(value)
    }
    actual_git_paths = {
        relative
        for relative, value in actual_revisions.items()
        if relative != args.source.name
        and ":" not in relative
        and parse_git_revision_url(value)
    }
    missing = sorted(expected_git_paths - actual_git_paths)
    unexpected = sorted(actual_git_paths - expected_git_paths)
    if missing or unexpected:
        raise RuntimeError(
            "gclient Git dependency topology differs from DEPS: "
            f"missing={missing}, unexpected={unexpected}"
        )

    verified = 0
    for relative in sorted(expected_git_paths):
        expected_url, expected_revision = parse_git_revision_url(
            expected_revisions[relative]
        )
        actual_url, actual_revision = parse_git_revision_url(
            actual_revisions[relative]
        )
        if actual_url != expected_url:
            raise RuntimeError(
                f"gclient dependency {relative} URL is {actual_url}; "
                f"required {expected_url}"
            )
        repository = checkout / relative
        if not (repository / ".git").exists():
            raise RuntimeError(
                f"gclient Git dependency is absent: {repository}"
            )
        actual = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=repository,
            text=True,
        ).strip()
        dirty = subprocess.check_output(
            [
                "git",
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
            ],
            cwd=repository,
            text=True,
        ).strip()
        if relative == f"{args.source.name}/third_party/skia":
            if dirty != SKIA_OVERLAY_DIRTY_STATUS:
                raise RuntimeError(
                    f"gclient dependency {relative} has unexpected overlay "
                    f"state: {dirty!r}; required "
                    f"{SKIA_OVERLAY_DIRTY_STATUS!r}"
                )
            # This one nested edit was authenticated by apply.py against the
            # pinned Skia revision and clean-file digest before this audit.
            dirty = ""
        validate_gclient_dependency_state(
            relative, expected_revision, actual_revision, dirty
        )
        validate_gclient_dependency_state(
            relative, expected_revision, actual, dirty
        )
        verified += 1
    if verified == 0:
        raise RuntimeError("gclient dependency audit found no nested Git repos")


def require_no_pending_ninja_work(
    args: argparse.Namespace,
) -> None:
    result = subprocess.run(
        [
            str(args.source / "third_party/ninja/ninja"),
            "-j16",
            "-C",
            str(output_directory(args)),
            "-n",
            *BUILD_TARGETS,
        ],
        cwd=args.source,
        env=depot_env(args.depot_tools),
        text=True,
        capture_output=True,
    )
    output = result.stdout + result.stderr
    if result.returncode != 0:
        raise RuntimeError(
            "could not prove Chromium build freshness:\n" + output
        )
    if "ninja: no work to do." not in output:
        raise RuntimeError(
            "Chromium outputs have pending Ninja work; run the pinned build "
            "and tests before packaging:\n" + output
        )


def package(
    args: argparse.Namespace,
    runner: Runner,
    *,
    require_full_ninja_freshness: bool = True,
) -> None:
    if runner.dry_run:
        print(f"+ package compiled runtime to {args.stage}")
        return
    verify_package_provenance(args, runner)
    if require_full_ninja_freshness:
        require_no_pending_ninja_work(args)
    out = output_directory(args)
    expected_stage = (
        args.source.parent / f"t1os-runtime-{args.profile}"
    )
    copy_runtime(out, args.stage, expected_stage)
    for name in sorted(ELF_RUNTIME_FILES):
        path = args.stage / name
        if path.is_file():
            patch_t1os_elf(path, name in EXECUTABLE_RUNTIME_FILES)
    verify_compiled_runtime(args.stage)
    chrome_hash = file_sha256(args.stage / "chrome")
    required_debug_sections = (
        list(DEVELOPMENT_REQUIRED_DEBUG_SECTIONS)
        if args.profile == "development"
        else []
    )
    source_debug_sections: dict[str, list[str]] = {}
    for name in SOURCE_DEBUG_RUNTIME_FILES:
        sections = elf_section_names(args.stage / name)
        missing = [
            section for section in required_debug_sections
            if section not in sections
        ]
        if missing:
            raise RuntimeError(
                f"{name} lacks development debug sections: {missing}"
            )
        source_debug_sections[name] = sections
    artifact_hashes = {
        path.relative_to(args.stage).as_posix(): file_sha256(path)
        for path in sorted(args.stage.rglob("*"))
        if path.is_file()
    }
    runtime_manifest = {
        "format": 1,
        "development": args.profile == "development",
        "chromium_version": MANIFEST["chromium_version"],
        "chromium_revision": CHROMIUM_REVISION,
        "chrome_sha256": chrome_hash,
        "artifacts": artifact_hashes,
        "source_build": {
            "profile": args.profile,
            "gn_args": COMMON_GN_ARGS + PROFILES[args.profile]["args"],
            "strip_policy": "none",
            "required_debug_sections": required_debug_sections,
            "debug_sections": source_debug_sections,
        },
        "t1os_media_decoder": {
            "available": True,
            "protocol": "T1MD",
            "protocol_version": 1,
            "feature": MANIFEST["runtime_feature"],
            "brokered_socket": True,
            "descriptor_pool_size": MANIFEST["descriptor_pool_size"],
            "chromium_revision": CHROMIUM_REVISION,
            "build_marker": MANIFEST["build_marker"],
            "protocol_header_sha256": PROTOCOL_HEADER_SHA256,
            "source_overlay_sha256": SOURCE_OVERLAY_SHA256,
        },
    }
    (args.stage / "t1os-chromium-runtime.json").write_text(
        json.dumps(runtime_manifest, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"verified compiled runtime: {args.stage}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=[
            "fetch",
            "sync",
            "apply",
            "configure",
            "build",
            "targeted-relink",
            "pipeline-relink",
            "test",
            "package",
            "all",
        ],
    )
    parser.add_argument("--profile", choices=sorted(PROFILES), default="development")
    parser.add_argument(
        "--source", type=Path, default=Path("/home/edward/t1os-chromium/src")
    )
    parser.add_argument(
        "--depot-tools", type=Path, default=Path("/home/edward/depot_tools")
    )
    parser.add_argument(
        "--stage",
        type=Path,
        default=Path("/home/edward/t1os-chromium/t1os-runtime-development"),
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    args.source = args.source.resolve()
    args.depot_tools = args.depot_tools.resolve()
    # Keep the lexical path so validate_stage_destination() can detect an
    # expected-name symlink before any recursive deletion.
    args.stage = args.stage.absolute()
    runner = Runner(args.dry_run)
    actions = {
        "fetch": fetch,
        "sync": sync,
        "apply": apply_overlay,
        "configure": configure,
        "build": build,
        "targeted-relink": targeted_relink,
        "pipeline-relink": pipeline_relink,
        "test": test,
        "package": package,
    }
    try:
        if args.command == "all":
            for action in (sync, apply_overlay, configure, build, test, package):
                action(args, runner)
        else:
            actions[args.command](args, runner)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
