#!/usr/bin/env python3
"""Compatibility installer for scripts/build chromium runtime.ps1.

The source build itself lives in `development/build chromium source.py`.
This adapter stages only compiled Chromium outputs into the established T1OS
runtime layout.  It deliberately preserves the T1OS-built SUID sandbox, path
provider, X/input helpers, library bundle, and other existing runtime assets.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SOURCE_BUILDER = REPO / "development/build chromium source.py"
SOURCE_MANIFEST_PATH = (
    REPO / "resource/chromium-source/150.0.7871.181/manifest.json"
)
SOURCE_MANIFEST = json.loads(
    SOURCE_MANIFEST_PATH.read_text(encoding="utf-8")
)
CHROMIUM_SOURCE = Path("/home/edward/t1os-chromium/src")
STAGE = Path("/home/edward/t1os-chromium/t1os-runtime-development")
ACTIVE_PROFILE = "development"
DESTINATION = REPO / "source/software/chromium"
PROGRAM = DESTINATION / "program"
REVISION = SOURCE_MANIFEST["chromium_revision"]
VERSION = SOURCE_MANIFEST["chromium_version"]
BUILD_MARKER = SOURCE_MANIFEST["build_marker"].encode("ascii")
DESCRIPTOR_POOL_SIZE = SOURCE_MANIFEST["descriptor_pool_size"]
PROTOCOL_HEADER_SHA256 = SOURCE_MANIFEST["protocol_header_sha256"]
SOURCE_OVERLAY_SHA256 = SOURCE_MANIFEST["source_overlay_sha256"]
T1OS_INTERPRETER = (
    "/the one/software/chromium/libraries/ld-linux-x86-64.so.2"
)
T1OS_RUNPATH = "/the one/software/chromium/libraries"
PINNED_WIDEVINE_VERSION = "4.10.3050.0"
PINNED_WIDEVINE_SHA256 = (
    "b8d8b79440326ceffba9230ab0a89cacd42058fc3dd3cf6c1f6a87336ed7e06f"
)

FILES_TO_PROGRAM = {
    "chrome": "chrome",
    "chrome_crashpad_handler": "chrome_crashpad_handler",
    "chrome_100_percent.pak": "chrome_100_percent.pak",
    "chrome_200_percent.pak": "chrome_200_percent.pak",
    "resources.pak": "resources.pak",
    "icudtl.dat": "icudtl.dat",
    "snapshot_blob.bin": "snapshot_blob.bin",
    "v8_context_snapshot.bin": "v8_context_snapshot.bin",
    "libEGL.so": "libEGL.so",
    "libGLESv2.so": "libGLESv2.so",
    "liboptimization_guide_internal.so": "liboptimization_guide_internal.so",
    # Managed for removal when absent from the validated stage. T1OS does not
    # ship Qt; retaining either shim from an older build would leave unresolved
    # DT_NEEDED dependencies in the runtime.
    "libqt5_shim.so": "libqt5_shim.so",
    "libqt6_shim.so": "libqt6_shim.so",
    "libvk_swiftshader.so": "libvk_swiftshader.so",
    "libvulkan.so.1": "libvulkan.so.1",
    "vk_swiftshader_icd.json": "vk_swiftshader_icd.json",
}
DIRECTORIES_TO_PROGRAM = (
    "locales",
    "MEIPreload",
    "IwaKeyDistribution",
    "PrivacySandboxAttestationsPreloaded",
)
REQUIRED_STAGE_FILES = (
    "chrome", "chrome_crashpad_handler", "icudtl.dat", "resources.pak",
)
REQUIRED_STAGE_DIRECTORIES = ("locales",)
FORBIDDEN_SOURCE_SUFFIXES = {
    ".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".java", ".js",
    ".m", ".mm", ".py", ".rs", ".ts", ".sh", ".bash", ".zsh", ".fish",
    ".pl", ".pm", ".rb", ".lua", ".go", ".swift", ".kt", ".kts", ".mjs",
    ".cjs", ".jsx", ".tsx", ".asm", ".s", ".inc",
}
ELF_PROGRAM_FILES = {
    "chrome",
    "chrome_crashpad_handler",
    "libEGL.so",
    "libGLESv2.so",
    "liboptimization_guide_internal.so",
    "libqt5_shim.so",
    "libqt6_shim.so",
    "libvk_swiftshader.so",
    "libvulkan.so.1",
}
EXECUTABLE_PROGRAM_FILES = {"chrome", "chrome_crashpad_handler"}
T1OS_HELPER_ARTIFACT_PATHS = (
    "program/chrome-sandbox",
    "t1os-path-provider.so",
    "tools/t1os-chrome-subprocess",
    "tools/t1os-xinput",
    "tools/t1os-xwm",
)
SOURCE_DEBUG_RUNTIME_FILES = ("chrome", "chrome_crashpad_handler")
DEVELOPMENT_REQUIRED_DEBUG_SECTIONS = (
    ".debug_info",
    ".debug_line",
    ".symtab",
)
DEVELOPMENT_GN_ARGS = (
    'target_os="linux"',
    'target_cpu="x64"',
    "is_component_build=false",
    "enable_t1os_video_decoder=true",
    "proprietary_codecs=true",
    'ffmpeg_branding="Chrome"',
    "enable_hevc_parser_and_hw_decoder=true",
    "enable_platform_hevc=true",
    "use_sysroot=true",
    "use_remoteexec=false",
    "use_siso=false",
    "is_debug=false",
    "is_official_build=false",
    "dcheck_always_on=true",
    "symbol_level=2",
    "blink_symbol_level=1",
    "enable_iterator_debugging=false",
)
RELEASE_GN_ARGS = (
    'target_os="linux"',
    'target_cpu="x64"',
    "is_component_build=false",
    "enable_t1os_video_decoder=true",
    "proprietary_codecs=true",
    'ffmpeg_branding="Chrome"',
    "enable_hevc_parser_and_hw_decoder=true",
    "enable_platform_hevc=true",
    "use_sysroot=true",
    "use_remoteexec=false",
    "use_siso=false",
    "is_debug=false",
    "is_official_build=true",
    "dcheck_always_on=false",
    "symbol_level=1",
    "blink_symbol_level=0",
)
PROFILE_CONTRACTS = {
    "development": {
        "development": True,
        "gn_args": DEVELOPMENT_GN_ARGS,
        "required_debug_sections": DEVELOPMENT_REQUIRED_DEBUG_SECTIONS,
        "strip_policy": "none",
    },
    "release": {
        "development": False,
        "gn_args": RELEASE_GN_ARGS,
        "required_debug_sections": (),
        "strip_policy": "none",
    },
}


def configure_profile(profile: str) -> None:
    """Select an exact source-build profile and its immutable stage root."""

    global ACTIVE_PROFILE, STAGE
    if profile not in PROFILE_CONTRACTS:
        raise ValueError(f"unsupported Chromium runtime profile: {profile}")
    ACTIVE_PROFILE = profile
    STAGE = Path(f"/home/edward/t1os-chromium/t1os-runtime-{profile}")


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


def tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    files = sorted(
        (
            path.relative_to(root).as_posix(),
            path,
        )
        for path in root.rglob("*")
        if path.is_file()
    )
    for relative_text, path in files:
        relative = relative_text.encode("utf-8")
        data = path.read_bytes()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def require_contained_path(path: Path, root: Path) -> None:
    try:
        path.relative_to(root)
    except ValueError as error:
        raise RuntimeError(
            f"runtime path escapes its dedicated root: {path} not in {root}"
        ) from error


def validate_install_destinations() -> None:
    if PROGRAM.parent != DESTINATION or PROGRAM.name != "program":
        raise RuntimeError(
            f"Chromium PROGRAM is not the exact dedicated destination: "
            f"{PROGRAM}"
        )
    runtime_directories = (
        PROGRAM,
        DESTINATION / "tools",
        DESTINATION / "resources",
    )
    if DESTINATION.is_symlink() or any(
        path.is_symlink() for path in runtime_directories
    ):
        raise RuntimeError(
            "Chromium destination runtime directories must not be symlinks"
        )
    if not DESTINATION.is_dir():
        raise RuntimeError(
            f"Chromium destination root is absent: {DESTINATION}"
        )
    for path in runtime_directories:
        if path.parent != DESTINATION:
            raise RuntimeError(
                f"Chromium runtime directory escapes destination: {path}"
            )
        if path.exists() and not path.is_dir():
            raise RuntimeError(
                f"Chromium runtime directory is not a directory: {path}"
            )
    managed = [
        *(PROGRAM / name for name in FILES_TO_PROGRAM.values()),
        *(PROGRAM / name for name in DIRECTORIES_TO_PROGRAM),
        PROGRAM / "chrome-sandbox",
        PROGRAM / "CHROME_VERSION_EXTRA",
        PROGRAM / "WidevineCdm",
        DESTINATION / "manifest.json",
        *(DESTINATION / relative for relative in T1OS_HELPER_ARTIFACT_PATHS),
    ]
    for path in managed:
        require_contained_path(path, DESTINATION)
        if path.is_symlink():
            raise RuntimeError(
                f"managed Chromium destination must not be a symlink: {path}"
            )


def checked_output(command: list[str]) -> str:
    return subprocess.check_output(command, text=True).strip()


def validate_t1os_elf(path: Path, executable: bool) -> None:
    with path.open("rb") as stream:
        magic = stream.read(4)
    if magic != b"\x7fELF":
        raise RuntimeError(f"compiled runtime artifact is not ELF: {path}")
    interpreter = (
        checked_output(["patchelf", "--print-interpreter", str(path)])
        if executable
        else T1OS_INTERPRETER
    )
    runpath = checked_output(["patchelf", "--print-rpath", str(path)])
    if interpreter != T1OS_INTERPRETER or runpath != T1OS_RUNPATH:
        raise RuntimeError(
            f"T1OS ELF contract failed for {path}: "
            f"interpreter={interpreter!r}, runpath={runpath!r}"
        )


def validate_dynamic_dependencies(root: Path) -> None:
    libraries = DESTINATION / "libraries"
    loader = libraries / "ld-linux-x86-64.so.2"
    if not loader.is_file():
        raise RuntimeError(f"T1OS runtime loader is absent: {loader}")
    # Mirror chromium.py and the exact ELF RUNPATH contract. The program
    # directory is not a deployed loader search path.
    library_path = str(libraries)
    for name in sorted(ELF_PROGRAM_FILES):
        path = root / name
        if not path.is_file():
            continue
        output = checked_output([
            str(loader),
            "--library-path",
            library_path,
            "--list",
            str(path),
        ])
        if "not found" in output:
            raise RuntimeError(
                f"unresolved T1OS DT_NEEDED dependency for {name}: {output}"
            )


def audit_no_loose_language_files(root: Path) -> None:
    leaked = sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in FORBIDDEN_SOURCE_SUFFIXES
    )
    if leaked:
        rendered = ", ".join(str(path) for path in leaked[:5])
        raise RuntimeError(
            f"loose-language files are forbidden in Chromium runtime: {rendered}"
        )
    scripted = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        with path.open("rb") as stream:
            prefix = stream.read(128)
        if prefix.startswith(b"#!"):
            scripted.append(path)
    if scripted:
        rendered = ", ".join(str(path) for path in scripted[:5])
        raise RuntimeError(
            f"scripted runtime artifacts are forbidden: {rendered}"
        )


def is_plain_int(value: object, expected: int) -> bool:
    return type(value) is int and value == expected


def load_validated_runtime() -> dict[str, object]:
    profile = PROFILE_CONTRACTS[ACTIVE_PROFILE]
    runtime_manifest_path = STAGE / "t1os-chromium-runtime.json"
    if not runtime_manifest_path.is_file():
        raise RuntimeError(
            f"validated source-build manifest missing: {runtime_manifest_path}"
        )
    runtime = json.loads(runtime_manifest_path.read_text(encoding="utf-8"))
    decoder = runtime.get("t1os_media_decoder", {})
    source_build = runtime.get("source_build")
    if (
        not is_plain_int(runtime.get("format"), 1)
        or runtime.get("development") is not profile["development"]
        or runtime.get("chromium_version") != VERSION
        or runtime.get("chromium_revision") != REVISION
        or not isinstance(decoder, dict)
        or decoder.get("available") is not True
        or decoder.get("protocol") != "T1MD"
        or not is_plain_int(decoder.get("protocol_version"), 1)
        or decoder.get("feature") != "T1OSVideoDecoder"
        or decoder.get("brokered_socket") is not True
        or not is_plain_int(
            decoder.get("descriptor_pool_size"), DESCRIPTOR_POOL_SIZE
        )
        or decoder.get("chromium_revision") != REVISION
        or decoder.get("build_marker") != BUILD_MARKER.decode("ascii")
        or decoder.get("protocol_header_sha256") != PROTOCOL_HEADER_SHA256
        or decoder.get("source_overlay_sha256") != SOURCE_OVERLAY_SHA256
        or not isinstance(source_build, dict)
        or set(source_build) != {
            "profile",
            "gn_args",
            "strip_policy",
            "required_debug_sections",
            "debug_sections",
        }
        or source_build.get("profile") != ACTIVE_PROFILE
        or source_build.get("gn_args") != list(profile["gn_args"])
        or source_build.get("strip_policy") != profile["strip_policy"]
        or source_build.get("required_debug_sections")
        != list(profile["required_debug_sections"])
    ):
        raise RuntimeError(
            f"stage does not contain the exact {ACTIVE_PROFILE} brokered "
            "T1MD runtime"
        )

    missing_files = [
        name for name in REQUIRED_STAGE_FILES
        if not (STAGE / name).is_file()
    ]
    missing_directories = [
        name for name in REQUIRED_STAGE_DIRECTORIES
        if not (STAGE / name).is_dir()
    ]
    if missing_files or missing_directories:
        raise RuntimeError(
            "staged compiled Chromium runtime is incomplete: "
            f"files={missing_files}, directories={missing_directories}"
        )
    if (STAGE / "chrome-sandbox").exists() or (STAGE / "chrome_sandbox").exists():
        raise RuntimeError(
            "the upstream Chromium sandbox must not be staged; "
            "T1OS builds program/chrome-sandbox separately"
        )
    audit_no_loose_language_files(STAGE)

    chrome = STAGE / "chrome"
    actual_hash = file_sha256(chrome)
    if runtime.get("chrome_sha256") != actual_hash:
        raise RuntimeError("staged chrome hash does not match its manifest")
    if not file_contains(chrome, BUILD_MARKER):
        raise RuntimeError(
            "staged chrome does not contain the exact T1OS media build marker"
        )
    artifacts = runtime.get("artifacts")
    if not isinstance(artifacts, dict):
        raise RuntimeError("staged runtime artifact hash inventory is missing")
    actual_artifacts = {
        path.relative_to(STAGE).as_posix(): file_sha256(path)
        for path in sorted(STAGE.rglob("*"))
        if path.is_file() and path.name != "t1os-chromium-runtime.json"
    }
    if artifacts != actual_artifacts:
        raise RuntimeError("staged runtime artifact hash inventory mismatches")
    debug_sections = source_build.get("debug_sections")
    if (
        not isinstance(debug_sections, dict)
        or set(debug_sections) != set(SOURCE_DEBUG_RUNTIME_FILES)
    ):
        raise RuntimeError(
            "staged Chromium source-build debug inventory has the wrong keys"
        )
    for name in SOURCE_DEBUG_RUNTIME_FILES:
        recorded_sections = debug_sections.get(name)
        actual_sections = elf_section_names(STAGE / name)
        if (
            not isinstance(recorded_sections, list)
            or not recorded_sections
            or not all(
                isinstance(section, str) for section in recorded_sections
            )
            or recorded_sections != sorted(set(recorded_sections))
            or recorded_sections != actual_sections
            or not all(
                section in actual_sections
                for section in profile["required_debug_sections"]
            )
        ):
            raise RuntimeError(
                "staged Chromium source-build debug attestation differs: "
                f"{name}"
            )
    for name in sorted(ELF_PROGRAM_FILES):
        path = STAGE / name
        if path.is_file():
            validate_t1os_elf(path, name in EXECUTABLE_PROGRAM_FILES)
    return runtime


def run_builder(command: str) -> None:
    subprocess.run(
        [
            sys.executable,
            str(SOURCE_BUILDER),
            command,
            "--profile",
            ACTIVE_PROFILE,
            "--source",
            str(CHROMIUM_SOURCE),
            "--stage",
            str(STAGE),
        ],
        check=True,
    )


def build() -> None:
    for command in ("sync", "apply", "configure", "build", "test", "package"):
        run_builder(command)


def prepare() -> None:
    # A validated stage is immutable-by-hash and may be reinstalled without a
    # source rebuild. If it is absent or stale, perform the complete pinned
    # configure/build/test/package path; never package an old output merely
    # because a previously installed program/chrome happens to exist.
    try:
        load_validated_runtime()
    except (OSError, RuntimeError, subprocess.CalledProcessError):
        if not CHROMIUM_SOURCE.is_dir():
            raise RuntimeError(
                "validated Chromium stage is absent and the pinned source "
                f"checkout is unavailable: {CHROMIUM_SOURCE}"
            )
        build()
    else:
        print(f"reusing validated source-built Chromium stage: {STAGE}")


def install() -> None:
    runtime = load_validated_runtime()
    # Resolve every target and reject links before the first overwrite/delete.
    validate_install_destinations()
    sandbox = PROGRAM / "chrome-sandbox"
    sandbox_hash = file_sha256(sandbox) if sandbox.is_file() else None

    PROGRAM.mkdir(parents=True, exist_ok=True)
    for source_name, destination_name in FILES_TO_PROGRAM.items():
        source = STAGE / source_name
        destination = PROGRAM / destination_name
        if source.is_file():
            shutil.copy2(source, destination)
        elif destination.is_file() or destination.is_symlink():
            # FILES_TO_PROGRAM is the complete managed set. Remove an optional
            # artifact omitted by this pinned build rather than retaining an
            # ABI-incompatible file from a previous Google/package build.
            destination.unlink()
    for name in DIRECTORIES_TO_PROGRAM:
        source = STAGE / name
        destination = PROGRAM / name
        if destination.exists():
            shutil.rmtree(destination)
        if source.is_dir():
            shutil.copytree(source, destination)

    chrome = PROGRAM / "chrome"
    if not chrome.is_file():
        raise RuntimeError("installed source-built Chrome binary is missing")
    crashpad = PROGRAM / "chrome_crashpad_handler"
    if not crashpad.is_file():
        raise RuntimeError(
            "installed source-built chrome_crashpad_handler is missing"
        )
    # The stage already contains the exact T1OS interpreter and RUNPATH.
    # Re-running patchelf is not byte-idempotent for large Chromium ELFs: it
    # can append and relocate an equivalent INTERP segment. Preserve the
    # attested bytes, then independently re-read the installed ELF contract.
    for name in sorted(ELF_PROGRAM_FILES):
        path = PROGRAM / name
        if path.is_file():
            expected = runtime["artifacts"].get(name)
            if expected != file_sha256(path):
                raise RuntimeError(
                    f"installed T1OS ELF differs from validated stage: {name}"
                )
            validate_t1os_elf(path, name in EXECUTABLE_PROGRAM_FILES)
    validate_dynamic_dependencies(PROGRAM)
    audit_no_loose_language_files(PROGRAM)
    if sandbox_hash is not None and (
        not sandbox.is_file() or file_sha256(sandbox) != sandbox_hash
    ):
        raise RuntimeError(
            "install replaced T1OS program/chrome-sandbox unexpectedly"
        )

    # Do not copy stage/chrome_sandbox. The PowerShell wrapper immediately
    # rebuilds T1OS's audited program/chrome-sandbox and retains setuid policy.
    manifest_path = DESTINATION / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["engine"] = "T1OS Chromium"
    manifest["engine_version"] = runtime["chromium_version"]
    manifest["engine_sha256"] = file_sha256(chrome)
    manifest["development"] = runtime["development"]
    manifest["built_utc"] = datetime.now(timezone.utc).isoformat()
    manifest["source_build"] = runtime["source_build"]
    manifest["t1os_media_decoder"] = {
        "available": True,
        "brokered_socket": True,
        "chromium_revision": REVISION,
        "descriptor_pool_size": DESCRIPTOR_POOL_SIZE,
        "feature": "T1OSVideoDecoder",
        "protocol": "T1MD",
        "protocol_version": 1,
        "build_marker": BUILD_MARKER.decode("ascii"),
        "protocol_header_sha256": PROTOCOL_HEADER_SHA256,
        "source_overlay_sha256": SOURCE_OVERLAY_SHA256,
    }
    manifest["source_build_artifacts"] = {
        f"program/{relative}": digest
        for relative, digest in runtime["artifacts"].items()
    }
    # The PowerShell wrapper rebuilds the five T1OS helpers after this adapter
    # returns, then writes and verifies their exact hashes and build/debug
    # attestation. Never preserve stale pre-build helper metadata here.
    manifest.pop("t1os_helper_artifacts", None)
    manifest.pop("t1os_helper_build", None)
    manifest.pop("t1os_direct_tool_artifacts", None)
    version_extra = PROGRAM / "CHROME_VERSION_EXTRA"
    if version_extra.exists():
        version_extra.unlink()
    widevine = PROGRAM / "WidevineCdm"
    manifest.pop("preserved_external_runtime", None)
    if widevine.is_dir():
        widevine_manifest = json.loads(
            (widevine / "manifest.json").read_text(encoding="utf-8")
        )
        widevine_hash = tree_sha256(widevine)
        if (
            widevine_manifest.get("version") != PINNED_WIDEVINE_VERSION
            or widevine_hash != PINNED_WIDEVINE_SHA256
        ):
            raise RuntimeError(
                "preserved external Widevine CDM does not match its pin"
            )
        manifest["preserved_external_runtime"] = {
            "program/WidevineCdm": {
                "classification": "external compiled CDM and signed data",
                "version": PINNED_WIDEVINE_VERSION,
                "sha256": widevine_hash,
            }
        }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"installed validated source-built Chromium into {PROGRAM}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("build", "prepare"))
    parser.add_argument(
        "--profile", choices=sorted(PROFILE_CONTRACTS), default="release"
    )
    args = parser.parse_args()
    try:
        configure_profile(args.profile)
        build() if args.command == "build" else prepare()
        install()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
