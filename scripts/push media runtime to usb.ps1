[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param(
    [switch]$ValidateTargetOnly
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Path $PSScriptRoot -Parent
$mountPoint = '/mnt/t1-media-runtime-usb'

$goddessSource = Join-Path $projectRoot 'source\build software\GODDESS\GODDESS.py'
$chromiumBuildSource = Join-Path $projectRoot 'source\build software\chromium\chromium.py'
$audioSoftwareSource = Join-Path $projectRoot 'source\software\audio'
$audioCatalogueSource = Join-Path $projectRoot 'source\catalogue\audio'
$chromiumRuntimeSource = Join-Path $projectRoot 'source\software\chromium'
$mediaPolicySource = Join-Path $projectRoot 'source\settings\media\video decode service.json'
$nativeProtocolHeader = Join-Path $projectRoot 'source\native\video\t1_media_decode_protocol.h'
$nativeWatchdogHeader = Join-Path $projectRoot 'source\native\video\t1_media_decode_watchdog.h'
$chromiumOverlayRoot = Join-Path $projectRoot 'resource\chromium-source\150.0.7871.181'
$chromiumProtocolHeader = Join-Path $chromiumOverlayRoot 'overlay\media\gpu\t1os\t1_media_decode_protocol.h'
$chromiumSourceManifest = Join-Path $chromiumOverlayRoot 'manifest.json'

function Get-T1OSUsbDriveTarget {
    $requiredRelativePaths = @(
        'the one',
        'the one\build\GODDESS',
        'the one\build\chromium',
        'the one\software\audio',
        'the one\catalogue\audio',
        'the one\software\chromium',
        'the one\settings',
        'the one\settings\runtime paths.json',
        'autorun.inf'
    )

    $candidates = @(
        Get-Volume -ErrorAction Stop |
            Where-Object {
                $_.DriveLetter -and (
                    [string]$_.DriveLetter -ceq 'D' -or
                    ([string]$_.FileSystemLabel).StartsWith(
                        'T1OS',
                        [StringComparison]::OrdinalIgnoreCase
                    )
                )
            } |
            ForEach-Object {
                $volume = $_
                $driveLetter = ([string]$volume.DriveLetter).ToUpperInvariant()
                $root = "$driveLetter`:\"
                $partition = Get-Partition -DriveLetter $driveLetter -ErrorAction Stop
                $disk = $partition | Get-Disk -ErrorAction Stop

                if (
                    [string]$disk.BusType -cne 'USB' -or
                    $disk.IsBoot -or
                    $disk.IsSystem -or
                    $disk.IsReadOnly -or
                    [string]$volume.FileSystemType -cne 'NTFS' -or
                    [string]$volume.HealthStatus -cne 'Healthy'
                ) {
                    return
                }

                foreach ($relativePath in $requiredRelativePaths) {
                    if (-not (Test-Path -LiteralPath (Join-Path $root $relativePath))) {
                        return
                    }
                }

                $autorun = Get-Content -LiteralPath (
                    Join-Path $root 'autorun.inf'
                ) -Raw
                if (
                    $autorun -notmatch '(?im)^\s*Label=T1OS(?:\s|$)' -or
                    $autorun -notmatch (
                        '(?im)^\s*Icon="the one\\resources\\' +
                        't1os-drive\.ico"\s*$'
                    )
                ) {
                    return
                }

                [pscustomobject]@{
                    DriveLetter = $driveLetter
                    DriveSource = "$driveLetter`:"
                    Root = $root
                    Label = ([string]$volume.FileSystemLabel).Trim()
                    DiskNumber = [int]$disk.Number
                    Model = ([string]$disk.FriendlyName).Trim()
                }
            }
    )

    $driveD = @($candidates | Where-Object { $_.DriveLetter -ceq 'D' })
    if ($driveD.Count -eq 1) {
        return $driveD[0]
    }
    if ($candidates.Count -eq 1) {
        return $candidates[0]
    }
    if ($candidates.Count -eq 0) {
        throw (
            'No healthy NTFS T1OS USB drive was found at D: or on a ' +
            'USB volume whose label starts with T1OS.'
        )
    }

    $identities = $candidates | ForEach-Object {
        "$($_.DriveLetter): '$($_.Label)' on USB disk $($_.DiskNumber)"
    }
    throw (
        'More than one eligible T1OS USB drive was found and none was the ' +
        "preferred D: target: $($identities -join '; ')"
    )
}

function ConvertTo-WslPath {
    param(
        [Parameter(Mandatory)]
        [string]$WindowsPath
    )

    $output = & wsl.exe -d Ubuntu --exec wslpath -a $WindowsPath
    if ($LASTEXITCODE -ne 0 -or -not $output) {
        throw "Could not translate path for WSL: $WindowsPath"
    }
    $translated = ([string]($output | Select-Object -First 1)).Trim()
    if ([string]::IsNullOrWhiteSpace($translated)) {
        throw "WSL returned an empty path for: $WindowsPath"
    }
    return $translated
}

$usbTarget = Get-T1OSUsbDriveTarget
Write-Host (
    "T1OS USB target: $($usbTarget.DriveLetter): '$($usbTarget.Label)' " +
    "on USB disk $($usbTarget.DiskNumber) $($usbTarget.Model)"
)

if ($ValidateTargetOnly) {
    Write-Host 'Scoped media-runtime USB target validation passed.'
    exit 0
}

$requiredFiles = @(
    $goddessSource,
    $chromiumBuildSource,
    $mediaPolicySource,
    $nativeProtocolHeader,
    $nativeWatchdogHeader,
    $chromiumProtocolHeader,
    $chromiumSourceManifest,
    (Join-Path $audioSoftwareSource 'manifest.json'),
    (Join-Path $audioSoftwareSource 't1-media-decoderd'),
    (Join-Path $audioSoftwareSource 't1-video-decode'),
    (Join-Path $chromiumRuntimeSource 'manifest.json'),
    (Join-Path $chromiumRuntimeSource 'program\chrome'),
    (Join-Path $chromiumRuntimeSource 'program\chrome-sandbox'),
    (Join-Path $chromiumRuntimeSource 'program\chrome_crashpad_handler'),
    (Join-Path $chromiumRuntimeSource 'libraries\ld-linux-x86-64.so.2'),
    (Join-Path $chromiumRuntimeSource 't1os-path-provider.so')
)
$requiredDirectories = @(
    $audioSoftwareSource,
    $audioCatalogueSource,
    $chromiumRuntimeSource,
    (Join-Path $chromiumRuntimeSource 'tools')
)
foreach ($path in $requiredFiles) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Required scoped media-runtime source file is absent: $path"
    }
}
foreach ($path in $requiredDirectories) {
    if (-not (Test-Path -LiteralPath $path -PathType Container)) {
        throw "Required scoped media-runtime source directory is absent: $path"
    }
}

$validatorCode = @'
#!/usr/bin/env python3
from __future__ import annotations

import ast
import hashlib
import json
import re
import struct
import sys
from pathlib import Path


def fail(message: str) -> None:
    raise SystemExit(message)


def require(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as error:
        fail(f"could not read exact JSON contract {path}: {type(error).__name__}")
    require(isinstance(value, dict), f"JSON contract is not an object: {path}")
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_contains(path: Path, needle: bytes) -> bool:
    overlap = max(0, len(needle) - 1)
    tail = b""
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            candidate = tail + block
            if needle in candidate:
                return True
            tail = candidate[-overlap:] if overlap else b""
    return False


def is_elf(path: Path) -> bool:
    try:
        with path.open("rb") as stream:
            return stream.read(4) == b"\x7fELF"
    except OSError:
        return False


def elf_section_names(path: Path) -> list[str]:
    file_size = path.stat().st_size
    with path.open("rb") as stream:
        header = stream.read(64)
        require(
            len(header) == 64
            and header[:4] == b"\x7fELF"
            and header[4] == 2
            and header[5] == 1,
            f"ELF helper is not little-endian ELF64: {path}",
        )
        fields = struct.unpack_from("<HHIQQQIHHHHHH", header, 16)
        section_offset = fields[5]
        section_entry_size = fields[10]
        section_count = fields[11]
        string_table_index = fields[12]
        native_section_size = struct.calcsize("<IIQQQQIIQQ")
        require(
            section_offset > 0 and section_entry_size >= native_section_size,
            f"ELF helper has no valid section table: {path}",
        )

        def read_section(index: int) -> tuple[int, ...]:
            offset = section_offset + index * section_entry_size
            require(
                0 <= offset <= file_size - native_section_size,
                f"ELF helper section table escapes the file: {path}",
            )
            stream.seek(offset)
            data = stream.read(native_section_size)
            require(
                len(data) == native_section_size,
                f"ELF helper section table is truncated: {path}",
            )
            return struct.unpack("<IIQQQQIIQQ", data)

        first_section = read_section(0)
        if section_count == 0:
            section_count = first_section[5]
        if string_table_index == 0xFFFF:
            string_table_index = first_section[6]
        require(
            type(section_count) is int
            and 0 < section_count <= 65536
            and type(string_table_index) is int
            and 0 < string_table_index < section_count,
            f"ELF helper section metadata is invalid: {path}",
        )

        string_section = read_section(string_table_index)
        string_offset = string_section[4]
        string_size = string_section[5]
        require(
            0 < string_size <= file_size
            and 0 <= string_offset <= file_size - string_size,
            f"ELF helper section-name table escapes the file: {path}",
        )
        stream.seek(string_offset)
        strings = stream.read(string_size)
        require(
            len(strings) == string_size,
            f"ELF helper section-name table is truncated: {path}",
        )

        names: set[str] = set()
        for index in range(section_count):
            name_offset = read_section(index)[0]
            require(
                0 <= name_offset < len(strings),
                f"ELF helper section name escapes its table: {path}",
            )
            name_end = strings.find(b"\0", name_offset)
            require(
                name_end >= name_offset,
                f"ELF helper section name is unterminated: {path}",
            )
            if name_end == name_offset:
                continue
            try:
                name = strings[name_offset:name_end].decode("ascii")
            except UnicodeDecodeError:
                fail(f"ELF helper section name is not ASCII: {path}")
            names.add(name)
    require(names, f"ELF helper section inventory is empty: {path}")
    return sorted(names)


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


def is_plain_int(value: object, expected: int) -> bool:
    return type(value) is int and value == expected


def safe_relative(value: object, label: str) -> Path:
    require(isinstance(value, str) and value, f"{label} is not a path string")
    path = Path(value)
    require(
        not path.is_absolute()
        and "\\" not in value
        and all(part not in ("", ".", "..") for part in path.parts),
        f"{label} is unsafe: {value!r}",
    )
    return path


def literal_assignments(path: Path) -> dict[str, object]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError) as error:
        fail(f"Python build file is invalid: {path}: {error}")
    assignments: dict[str, object] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        try:
            assignments[target.id] = ast.literal_eval(node.value)
        except (ValueError, TypeError):
            pass
    return assignments


def reject_runtime_sources(*roots: Path) -> None:
    forbidden_suffixes = {
        ".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".java",
        ".js", ".m", ".mm", ".py", ".rs", ".ts", ".sh", ".bash",
        ".zsh", ".fish", ".pl", ".pm", ".rb", ".lua", ".go", ".swift",
        ".kt", ".kts", ".mjs", ".cjs", ".jsx", ".tsx", ".asm", ".s",
        ".inc", ".mojom", ".gn", ".gni", ".proto", ".idl", ".webidl",
        ".cmake", ".mk", ".gradle", ".scala", ".cs", ".fs", ".vb",
        ".r", ".dart", ".php", ".t1os", ".img",
    }
    for root in roots:
        require(root.is_dir() and not root.is_symlink(), f"runtime root is unsafe: {root}")
        for path in root.rglob("*"):
            require(not path.is_symlink(), f"runtime symlink is forbidden: {path}")
            if not path.is_file():
                continue
            require(
                path.suffix.lower() not in forbidden_suffixes,
                f"loose-language or image artifact is forbidden: {path}",
            )
            with path.open("rb") as stream:
                require(
                    stream.read(2) != b"#!",
                    f"scripted runtime artifact is forbidden: {path}",
                )


if len(sys.argv) != 12:
    fail("media runtime validator received the wrong argument count")

(
    goddess_path,
    chromium_build_path,
    native_header_path,
    native_watchdog_header_path,
    chromium_header_path,
    source_manifest_path,
    audio_software_path,
    audio_catalogue_path,
    chromium_runtime_path,
    policy_path,
) = map(Path, sys.argv[1:11])
expected_kill_text = sys.argv[11]

expected_kill = {"true": True, "false": False}.get(expected_kill_text)
require(expected_kill is not None, "expected kill-switch state is invalid")

for build_file in (goddess_path, chromium_build_path):
    require(
        build_file.is_file()
        and not build_file.is_symlink()
        and build_file.suffix == ".py",
        f"allowed Python build file is absent or unsafe: {build_file}",
    )

goddess_constants = literal_assignments(goddess_path)
chromium_constants = literal_assignments(chromium_build_path)
for constants, label in (
    (goddess_constants, "GODDESS"),
    (chromium_constants, "Chromium launcher"),
):
    require(constants.get("MEDIADECODEPROTOCOL") == "T1MD", f"{label} protocol changed")
    require(
        constants.get("MEDIADECODEPOLICY")
        == "/the one/settings/media/video decode service.json"
        and constants.get("MEDIADECODEPACKAGEDPOLICY")
        == "/the one/software/audio/video decode service.json",
        f"{label} media policy paths changed",
    )
    require(
        is_plain_int(constants.get("MEDIADECODEPROTOCOLVERSION"), 1),
        f"{label} protocol version changed",
    )
    require(
        is_plain_int(constants.get("MEDIADECODEWORKERUID"), 65534),
        f"{label} worker UID changed",
    )
    require(
        is_plain_int(constants.get("MEDIADECODEWORKERGID"), 1000),
        f"{label} worker GID changed",
    )
    require(
        constants.get("MEDIADECODESESSIONSTDERR")
        == "bounded-nonblocking-relay",
        f"{label} diagnostic relay changed",
    )
    require(
        is_plain_int(
            constants.get("MEDIADECODESESSIONDIAGNOSTICLIMIT"),
            1048576,
        ),
        f"{label} diagnostic relay limit changed",
    )
    require(
        is_plain_int(
            constants.get("MEDIADECODESESSIONEXECVISIBLEFDS"),
            6,
        )
        and is_plain_int(
            constants.get("MEDIADECODESESSIONREQUIREDIPCFDS"),
            3,
        ),
        f"{label} worker descriptor contract changed",
    )
require(
    is_plain_int(goddess_constants.get("MEDIADECODEMAXSESSIONS"), 8),
    "GODDESS does not enforce an exact eight-session ceiling",
)
require(
    is_plain_int(chromium_constants.get("MEDIADECODEMAXSESSIONS"), 8),
    "Chromium launcher does not enforce an exact eight-session ceiling",
)
expected_surface_export = {
    "mode": "separate-layers",
    "object_layout": "one-object-per-plane",
    "modifier_scope": "per-object",
    "modifier_layout": "natural-per-plane",
    "composed_fallback": False,
}
require(
    goddess_constants.get("MEDIADECODEEXPORTCONTRACT")
    == expected_surface_export,
    "GODDESS surface-export readiness contract changed",
)

goddess_text = goddess_path.read_text(encoding="utf-8")
require(
    re.search(r"['\"]--max-sessions['\"].{0,160}policy\[['\"]max_sessions['\"]\]",
              goddess_text, re.DOTALL)
    and re.search(r"['\"]--max-connections['\"].{0,160}policy\[['\"]max_sessions['\"]\]",
                  goddess_text, re.DOTALL),
    "GODDESS does not bind both native daemon ceilings to the exact policy",
)
require(
    "environment['NVD_SINGLE_BUFFER']" not in goddess_text
    and "NVD_SINGLE_BUFFER is intentionally absent" in goddess_text,
    "GODDESS re-enabled NVIDIA's superseded common-modifier allocation",
)
require(
    "os.path.isfile(MEDIADECODEPACKAGEDPOLICY)" in goddess_text
    and "os.path.isfile(MEDIADECODEPACKAGEDPOLICY)" in
        chromium_build_path.read_text(encoding="utf-8"),
    "the protected-settings media policy lacks its packaged USB fallback",
)

native_header = native_header_path.read_bytes()
native_watchdog_header = native_watchdog_header_path.read_bytes()
chromium_header = chromium_header_path.read_bytes()
require(native_header == chromium_header, "native and Chromium T1MD headers differ")
protocol_hash = hashlib.sha256(native_header).hexdigest()
watchdog_header_hash = hashlib.sha256(native_watchdog_header).hexdigest()
expected_watchdog_contract = {
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
}
for constants, label in (
    (goddess_constants, "GODDESS"),
    (chromium_constants, "Chromium launcher"),
):
    require(
        constants.get("MEDIADECODEWATCHDOGCONTRACT")
        == expected_watchdog_contract,
        f"{label} supervisor watchdog contract changed",
    )
require(
    chromium_constants.get("MEDIADECODECHROMIUMREVISION")
    == "24b04c927b23c39cf9c5227cc8dc6f64a744c8e9"
    and chromium_constants.get("MEDIADECODEPROTOCOLHEADERSHA256")
    == protocol_hash,
    "Chromium launcher provenance constants differ from authoritative T1MD",
)

source_contract = load_json(source_manifest_path)
require(is_plain_int(source_contract.get("format"), 1), "source contract format changed")
require(source_contract.get("protocol_magic") == "T1MD", "source protocol magic changed")
require(
    is_plain_int(source_contract.get("protocol_version"), 1),
    "source protocol version changed",
)
require(
    is_plain_int(source_contract.get("descriptor_pool_size"), 8),
    "Chromium descriptor pool is not exactly eight",
)
require(
    source_contract.get("protocol_header_sha256") == protocol_hash,
    "source contract protocol-header hash differs from authoritative bytes",
)
revision = source_contract.get("chromium_revision")
overlay_hash = source_contract.get("source_overlay_sha256")
require(
    source_contract.get("chromium_version") == "150.0.7871.181"
    and revision == "24b04c927b23c39cf9c5227cc8dc6f64a744c8e9"
    and source_contract.get("chromium_tag") == "refs/tags/150.0.7871.181"
    and source_contract.get("depot_tools_revision")
    == "93919990d65a94fd62a5b1bae4e2909df6996e4a",
    "Chromium/depot_tools source pins changed",
)
require(
    isinstance(overlay_hash, str) and re.fullmatch(r"[0-9a-f]{64}", overlay_hash),
    "Chromium source-overlay hash is invalid",
)
full_marker = (
    "T1OS_MEDIA_DECODER=T1MD/1;brokered_socket=1;pool=8;"
    f"chromium={revision};protocol_sha256={protocol_hash};"
    f"source_sha256={overlay_hash}"
)
require(
    source_contract.get("build_marker") == full_marker,
    "source build marker is not the exact full provenance marker",
)
require(
    chromium_constants.get("MEDIADECODESOURCEOVERLAYSHA256") == overlay_hash
    and chromium_constants.get("MEDIADECODEBUILDMARKER") == full_marker,
    "Chromium launcher source/build provenance constants differ",
)

policy = load_json(policy_path)
require(policy.get("enabled") is True, "deployment policy is not enabled")
require(
    policy.get("development_debug") is False,
    "deployment policy enables development diagnostics in production",
)
require(
    policy.get("kill_switch") is expected_kill,
    "deployment policy kill-switch state was not preserved exactly",
)
require(
    is_plain_int(policy.get("max_sessions"), 8),
    "deployment policy does not enforce exactly eight sessions/connections",
)
require(
    is_plain_int(policy.get("protocol_version"), 1),
    "deployment policy protocol version changed",
)

reject_runtime_sources(
    audio_software_path,
    audio_catalogue_path,
    chromium_runtime_path,
)

audio_manifest = load_json(audio_software_path / "manifest.json")
require(is_plain_int(audio_manifest.get("format"), 1), "audio manifest format changed")
require(audio_manifest.get("state") == "ready", "audio runtime is not ready")
require(
    audio_manifest.get("build_mode") == "development",
    "audio runtime is not a development build",
)
audio_runtime = audio_manifest.get("runtime")
require(isinstance(audio_runtime, dict), "audio runtime contract is absent")
require(
    audio_runtime.get("media_decode_service")
    == "/the one/software/audio/t1-media-decoderd"
    and audio_runtime.get("media_decode_worker")
    == "/the one/software/audio/t1-video-decode"
    and audio_runtime.get("media_decode_worker_mode") == "--t1md-worker",
    "audio multicall service/worker contract changed",
)
audio_protocol = audio_runtime.get("media_decode_protocol")
require(isinstance(audio_protocol, dict), "audio protocol contract is absent")
expected_audio_protocol = {
    "name": "T1MD",
    "version": 1,
    "transport": "AF_UNIX/SOCK_SEQPACKET",
    "header_sha256": protocol_hash,
    "maximum_decode_requests": 1,
    "maximum_in_flight_frames": 16,
    "backpressure_feature_bit": 64,
    "linear_memory_output_feature_bit": 128,
    "backpressure_message_type": 15,
    "backpressure_timeout_ms": 0,
    "backpressure_reset_terminal": "RESET_DONE-without-EXIT",
}
require(
    set(audio_protocol) == set(expected_audio_protocol),
    "audio T1MD protocol topology changed",
)
for name, value in expected_audio_protocol.items():
    require(
        type(audio_protocol.get(name)) is type(value)
        and audio_protocol.get(name) == value,
        f"audio T1MD protocol contract changed: {name}",
    )
surface_export = audio_runtime.get("media_decode_surface_export")
expected_surface_export_manifest = {
    **expected_surface_export,
    "chroma_subsampling": "4:2:0",
    "bit_depths": [8, 10],
    "output_formats": ["NV12", "P010"],
}
require(
    isinstance(surface_export, dict)
    and set(surface_export) == set(expected_surface_export_manifest),
    "audio surface-export contract topology changed",
)
for name, value in expected_surface_export_manifest.items():
    require(
        type(surface_export.get(name)) is type(value)
        and surface_export.get(name) == value,
        f"audio surface-export contract changed: {name}",
    )
watchdog = audio_runtime.get("media_decode_watchdog")
expected_watchdog_manifest = {
    **expected_watchdog_contract,
    "header_sha256": watchdog_header_hash,
}
require(
    isinstance(watchdog, dict)
    and set(watchdog) == set(expected_watchdog_manifest),
    "audio watchdog contract topology changed",
)
for name, value in expected_watchdog_manifest.items():
    require(
        type(watchdog.get(name)) is type(value)
        and watchdog.get(name) == value,
        f"audio watchdog contract changed: {name}",
    )
sandbox = audio_runtime.get("media_decode_sandbox")
expected_sandbox = {
    "required": True,
    "worker_uid": 65534,
    "worker_gid": 1000,
    "landlock_minimum_abi": 5,
    "landlock_filesystem": "deny-by-default-all-through-ioctl-dev",
    "landlock_network": "deny-tcp-bind-connect",
    "runtime_filesystem": "read-only",
    "device_filesystem": "read-write-ioctl",
    "seccomp": "filter",
    "seccomp_tsync": True,
    "network_creation": "denied",
    "process_creation": "threads-only",
    "session_stdin": "null",
    "session_stdout": "null",
    "session_stderr": "bounded-nonblocking-relay",
    "session_diagnostic_limit": 1048576,
    "session_exec_visible_fds": 6,
    "session_required_ipc_fds": 3,
    "session_unexpected_inherited_fds": 0,
    "probe_diagnostic_limit": 65536,
    "rlimit_core": 0,
    "rlimit_fsize": 67108864,
    "rlimit_nofile": 256,
    "rlimit_nproc": 256,
}
require(isinstance(sandbox, dict), "audio sandbox contract is absent")
for name, value in expected_sandbox.items():
    require(sandbox.get(name) == value, f"audio sandbox contract changed: {name}")
for name in (
    "worker_uid", "worker_gid", "landlock_minimum_abi",
    "session_diagnostic_limit", "session_exec_visible_fds",
    "session_required_ipc_fds", "session_unexpected_inherited_fds",
    "probe_diagnostic_limit", "rlimit_core", "rlimit_fsize",
    "rlimit_nofile", "rlimit_nproc",
):
    require(type(sandbox.get(name)) is int, f"audio sandbox integer is not exact: {name}")

standalone_worker = audio_software_path / "t1-media-decode-worker"
require(
    not standalone_worker.exists() and not standalone_worker.is_symlink(),
    "LSM-ineligible standalone media worker must not be deployed",
)
for name in ("ffmpeg", "ffprobe", "t1-media-decoderd", "t1-video-decode"):
    path = audio_software_path / name
    require(path.is_file() and is_elf(path),
            f"compiled audio executable is absent or malformed: {path}")
daemon = audio_software_path / "t1-media-decoderd"
for marker in (
    b"T1_MEDIA_WORKER_DIAGNOSTIC",
    b"bounded-nonblocking-relay",
    b"worker-diagnostics-truncated",
):
    require(
        file_contains(daemon, marker),
        f"development diagnostic relay marker is absent: {marker!r}",
    )

inventory = audio_manifest.get("files")
require(isinstance(inventory, list) and inventory, "audio hash inventory is absent")
expected_audio_files: set[tuple[str, str]] = set()
area_roots = {
    "software": audio_software_path,
    "catalogue": audio_catalogue_path,
}
for item in inventory:
    require(isinstance(item, dict), "audio hash inventory entry is invalid")
    area = item.get("area")
    require(area in area_roots, f"audio inventory area is invalid: {area!r}")
    relative = safe_relative(item.get("path"), "audio inventory path")
    key = (area, relative.as_posix())
    require(key not in expected_audio_files, f"duplicate audio inventory path: {key}")
    expected_audio_files.add(key)
    path = area_roots[area] / relative
    require(path.is_file() and not path.is_symlink(), f"audio artifact is absent: {path}")
    require(
        is_plain_int(item.get("size"), path.stat().st_size),
        f"audio artifact size differs from manifest: {path}",
    )
    require(item.get("sha256") == sha256(path), f"audio artifact hash differs: {path}")
actual_audio_files = {
    ("software", path.relative_to(audio_software_path).as_posix())
    for path in audio_software_path.rglob("*")
    if (
        path.is_file()
        and path.name != "manifest.json"
        and path.relative_to(audio_software_path).as_posix()
        != "video decode service.json"
    )
} | {
    ("catalogue", path.relative_to(audio_catalogue_path).as_posix())
    for path in audio_catalogue_path.rglob("*")
    if path.is_file()
}
require(
    actual_audio_files == expected_audio_files,
    "audio manifest inventory is not the exact compiled runtime tree",
)

chromium_manifest = load_json(chromium_runtime_path / "manifest.json")
require(is_plain_int(chromium_manifest.get("format"), 1), "Chromium manifest format changed")
require(
    chromium_manifest.get("development") is True,
    "Chromium runtime is not an attested development build",
)
decoder = chromium_manifest.get("t1os_media_decoder")
require(isinstance(decoder, dict), "Chromium T1MD capability is absent")
require(
    decoder.get("available") is True
    and decoder.get("brokered_socket") is True
    and decoder.get("protocol") == "T1MD"
    and is_plain_int(decoder.get("protocol_version"), 1)
    and decoder.get("feature") == "T1OSVideoDecoder"
    and is_plain_int(decoder.get("descriptor_pool_size"), 8)
    and decoder.get("chromium_revision") == revision
    and decoder.get("protocol_header_sha256") == protocol_hash
    and decoder.get("source_overlay_sha256") == overlay_hash
    and decoder.get("build_marker") == full_marker,
    "Chromium does not advertise the exact brokered T1MD build",
)
chrome = chromium_runtime_path / "program" / "chrome"
require(chrome.is_file() and is_elf(chrome),
        "compiled Chromium engine is absent or malformed")
require(
    chromium_manifest.get("engine_sha256") == sha256(chrome),
    "Chromium engine hash differs from its manifest",
)
require(
    file_contains(chrome, full_marker.encode("ascii")),
    "Chromium binary lacks the exact full T1MD provenance marker",
)

development_gn_args = [
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
]
required_source_debug_sections = [
    ".debug_info",
    ".debug_line",
    ".symtab",
]
source_build = chromium_manifest.get("source_build")
require(
    isinstance(source_build, dict)
    and set(source_build) == {
        "profile",
        "gn_args",
        "strip_policy",
        "required_debug_sections",
        "debug_sections",
    }
    and source_build.get("profile") == "development"
    and source_build.get("gn_args") == development_gn_args
    and source_build.get("strip_policy") == "none"
    and source_build.get("required_debug_sections")
    == required_source_debug_sections,
    "Chromium source binary lacks the exact development-build attestation",
)
source_debug_sections = source_build.get("debug_sections")
required_source_debug_paths = {
    "chrome",
    "chrome_crashpad_handler",
}
require(
    isinstance(source_debug_sections, dict)
    and set(source_debug_sections) == required_source_debug_paths,
    "Chromium source-build debug-section inventory has the wrong keys",
)
for relative_text in sorted(required_source_debug_paths):
    recorded_sections = source_debug_sections[relative_text]
    require(
        isinstance(recorded_sections, list)
        and recorded_sections
        and all(isinstance(section, str) for section in recorded_sections)
        and recorded_sections == sorted(set(recorded_sections)),
        f"Chromium source-build debug attestation is invalid: {relative_text}",
    )
    path = chromium_runtime_path / "program" / relative_text
    actual_sections = elf_section_names(path)
    require(
        recorded_sections == actual_sections,
        f"Chromium source-build debug-section inventory differs: {path}",
    )
    require(
        all(section in actual_sections for section in required_source_debug_sections),
        f"Chromium source-built development binary lacks debug sections: {path}",
    )

helper_artifacts = chromium_manifest.get("t1os_helper_artifacts")
required_helper_paths = {
    "program/chrome-sandbox",
    "t1os-path-provider.so",
    "tools/t1os-chrome-subprocess",
    "tools/t1os-xinput",
    "tools/t1os-xwm",
}
require(
    isinstance(helper_artifacts, dict)
    and set(helper_artifacts) == required_helper_paths,
    "Chromium T1OS helper hash inventory is not the exact required set",
)
for relative_text in sorted(required_helper_paths):
    expected_hash = helper_artifacts[relative_text]
    relative = safe_relative(relative_text, "Chromium T1OS helper artifact")
    require(
        isinstance(expected_hash, str)
        and re.fullmatch(r"[0-9a-f]{64}", expected_hash),
        f"Chromium T1OS helper hash is invalid: {relative}",
    )
    path = chromium_runtime_path / relative
    require(
        path.is_file() and not path.is_symlink() and is_elf(path),
        f"compiled Chromium T1OS helper is absent or malformed: {path}",
    )
    require(
        sha256(path) == expected_hash,
        f"Chromium T1OS helper hash differs from manifest: {path}",
    )

helper_build = chromium_manifest.get("t1os_helper_build")
production_helper_flags = [
    "-O2",
    "-DNDEBUG",
    "-D_FORTIFY_SOURCE=2",
    "-fstack-protector-strong",
    "-fno-omit-frame-pointer",
]
required_helper_debug_sections = []
require(
    isinstance(helper_build, dict)
    and set(helper_build) == {
        "mode",
        "compiler_flags",
        "strip_policy",
        "required_debug_sections",
        "debug_sections",
    }
    and helper_build.get("mode") == "production"
    and helper_build.get("compiler_flags") == production_helper_flags
    and helper_build.get("strip_policy") == "production-selective"
    and helper_build.get("required_debug_sections")
    == required_helper_debug_sections,
    "Chromium T1OS helpers are not an exact hardened production build",
)
helper_debug_sections = helper_build.get("debug_sections")
require(
    isinstance(helper_debug_sections, dict)
    and set(helper_debug_sections) == required_helper_paths,
    "Chromium T1OS helper debug-section inventory is not the exact required set",
)
for relative_text in sorted(required_helper_paths):
    recorded_sections = helper_debug_sections[relative_text]
    require(
        isinstance(recorded_sections, list)
        and recorded_sections
        and all(isinstance(section, str) for section in recorded_sections)
        and recorded_sections == sorted(set(recorded_sections)),
        f"Chromium T1OS helper debug-section attestation is invalid: {relative_text}",
    )
    path = chromium_runtime_path / safe_relative(
        relative_text,
        "Chromium T1OS helper debug artifact",
    )
    actual_sections = elf_section_names(path)
    require(
        recorded_sections == actual_sections,
        f"Chromium T1OS helper debug-section inventory differs: {path}",
    )

require(
    not (chromium_runtime_path / "program" / "chrome_sandbox").exists(),
    "upstream chrome_sandbox is forbidden",
)
require(
    (chromium_runtime_path / "program" / "chrome-sandbox").is_file(),
    "T1OS chrome-sandbox is absent",
)

artifacts = chromium_manifest.get("source_build_artifacts")
require(
    isinstance(artifacts, dict) and artifacts,
    "Chromium source-build hash inventory is absent",
)
for relative_text, expected_hash in artifacts.items():
    relative = safe_relative(relative_text, "Chromium source-build artifact")
    require(
        relative.parts and relative.parts[0] == "program",
        f"Chromium source-build artifact escaped program/: {relative}",
    )
    require(
        isinstance(expected_hash, str)
        and re.fullmatch(r"[0-9a-f]{64}", expected_hash),
        f"Chromium source-build artifact hash is invalid: {relative}",
    )
    path = chromium_runtime_path / relative
    require(path.is_file() and not path.is_symlink(),
            f"Chromium source-build artifact is absent: {path}")
    require(sha256(path) == expected_hash,
            f"Chromium source-build artifact hash differs: {path}")

external = chromium_manifest.get("preserved_external_runtime", {})
require(isinstance(external, dict), "Chromium external-runtime inventory is invalid")
widevine = chromium_runtime_path / "program" / "WidevineCdm"
require(
    not widevine.exists() or "program/WidevineCdm" in external,
    "preserved Widevine runtime lacks an exact external hash contract",
)
for relative_text, contract in external.items():
    relative = safe_relative(relative_text, "Chromium external-runtime artifact")
    require(isinstance(contract, dict), f"external runtime contract is invalid: {relative}")
    path = chromium_runtime_path / relative
    require(path.is_dir() and not path.is_symlink(),
            f"external runtime directory is absent: {path}")
    require(
        contract.get("sha256") == tree_sha256(path),
        f"external runtime tree hash differs: {path}",
    )

print(json.dumps({
    "state": "validated",
    "protocol_header_sha256": protocol_hash,
    "watchdog_header_sha256": watchdog_header_hash,
    "source_overlay_sha256": overlay_hash,
    "descriptor_pool_size": 8,
    "maximum_sessions": 8,
    "maximum_connections": 8,
    "development_debug": False,
    "chromium_helper_build_mode": "production-logging",
    "kill_switch": expected_kill,
}, sort_keys=True))
'@

$copyCommand = @'
set -eu

validator=$1
goddess_source=$2
chromium_build_source=$3
native_protocol_header=$4
native_watchdog_header=$5
chromium_protocol_header=$6
chromium_source_manifest=$7
audio_software_source=$8
audio_catalogue_source=$9
chromium_runtime_source=${10}
media_policy_source=${11}
mount_point=${12}
drive_source=${13}

case "$mount_point" in
    /mnt/t1-media-runtime-usb) ;;
    *)
        echo "Refusing unexpected scoped mount point: $mount_point" >&2
        exit 64
        ;;
esac
case "$drive_source" in
    [A-Z]:) ;;
    *)
        echo "Refusing unexpected Windows drive identity: $drive_source" >&2
        exit 64
        ;;
esac

for command_name in \
    python3 rsync mount umount mountpoint findmnt readlink find grep \
    head dirname cmp sha256sum readelf stat chmod chown mkdir rmdir rm cp \
    sync df du awk mktemp
do
    command -v "$command_name" >/dev/null 2>&1 || {
        echo "Required WSL command is unavailable: $command_name" >&2
        exit 127
    }
done

stage=$(mktemp -d -- /tmp/t1os-media-runtime-push.XXXXXXXXXX)
case "$stage" in
    /tmp/t1os-media-runtime-push.[A-Za-z0-9]*) ;;
    *)
        echo "Refusing unsafe temporary stage: $stage" >&2
        exit 64
        ;;
esac
if [ -L "$stage" ] || [ "$(readlink -f -- "$stage")" != "$stage" ]; then
    echo "Refusing unsafe resolved temporary stage: $stage" >&2
    exit 64
fi
mounted_here=0
guard_recovery_required=0

cleanup() {
    status=$1
    trap - EXIT HUP INT TERM
    set +e
    # Once runtime mutation begins, every failing exit must leave the USB
    # fail-closed. This also covers a copied-byte, policy, or final-sync
    # failure discovered after the enabled policy was atomically installed.
    if [ "$status" -ne 0 ] &&
        [ "$guard_recovery_required" = 1 ] &&
        [ "$mounted_here" = 1 ] &&
        mountpoint -q "$mount_point" &&
        [ -f "$stage/video-decode-service.json" ]; then
        if install_policy_atomically \
            "$stage/video-decode-service.json" \
            "$media_policy_destination" \
            guard; then
            if ! sync; then
                echo "Could not flush the recovered fail-closed media policy." >&2
                status=1
            else
                echo "Recovered the USB to a disabled, kill-switched media policy." >&2
            fi
        else
            echo "Could not recover the fail-closed media policy after failure." >&2
            status=1
        fi
    fi
    if [ -d "$stage" ] && [ ! -L "$stage" ] &&
        [ "$(readlink -f -- "$stage")" = "$stage" ]; then
        if ! rm -rf -- "$stage"; then
            echo "Could not remove the scoped temporary stage." >&2
            status=1
        fi
    fi
    if [ "$mounted_here" = 1 ]; then
        if ! sync; then
            echo "Could not flush the scoped T1OS USB mount." >&2
            status=1
        fi
        if ! umount "$mount_point"; then
            echo "Could not release the scoped T1OS USB mount." >&2
            status=1
        fi
    fi
    exit "$status"
}
trap 'cleanup $?' EXIT
trap 'cleanup 129' HUP
trap 'cleanup 130' INT
trap 'cleanup 143' TERM

# Repeat the source proof as root before the USB is mounted or changed.
python3 "$validator" \
    "$goddess_source" \
    "$chromium_build_source" \
    "$native_protocol_header" \
    "$native_watchdog_header" \
    "$chromium_protocol_header" \
    "$chromium_source_manifest" \
    "$audio_software_source" \
    "$audio_catalogue_source" \
    "$chromium_runtime_source" \
    "$media_policy_source" \
    false

if [ -L "$mount_point" ]; then
    echo "Scoped USB mount point is a symlink; refusing to continue." >&2
    exit 1
fi
if [ ! -e "$mount_point" ]; then
    mkdir -m 0755 -- "$mount_point"
fi
if [ ! -d "$mount_point" ] ||
    [ "$(readlink -f -- "$mount_point")" != "$mount_point" ]; then
    echo "Scoped USB mount point is absent or resolves unexpectedly." >&2
    exit 1
fi
if mountpoint -q "$mount_point"; then
    echo "Scoped USB mount point was already mounted; refusing to continue." >&2
    exit 1
fi
if find "$mount_point" -mindepth 1 -maxdepth 1 -print -quit | grep -q .; then
    echo "Scoped USB mount point contains stale files while unmounted." >&2
    exit 1
fi

mount -t drvfs "$drive_source" "$mount_point" \
    -o metadata,uid=0,gid=0,umask=022
mounted_here=1
mount_options=$(findmnt -rn -o OPTIONS -T "$mount_point" | head -n 1)
case ",$mount_options," in
    *,ro,*)
        echo "T1OS USB mounted read-only; refusing to copy." >&2
        exit 1
        ;;
esac
mounted_source=$(findmnt -rn -o SOURCE -T "$mount_point" | head -n 1)
if [ "$mounted_source" != "$drive_source" ]; then
    echo "Scoped mount is not backed by the selected Windows USB drive." >&2
    exit 1
fi

mount_root=$(readlink -f -- "$mount_point")
if [ "$mount_root" != "$mount_point" ]; then
    echo "Scoped mount point resolved to an unexpected path: $mount_root" >&2
    exit 1
fi

goddess_destination="$mount_point/the one/build/GODDESS/GODDESS.py"
chromium_build_destination="$mount_point/the one/build/chromium/chromium.py"
audio_software_destination="$mount_point/the one/software/audio"
audio_catalogue_destination="$mount_point/the one/catalogue/audio"
chromium_runtime_destination="$mount_point/the one/software/chromium"
settings_destination="$mount_point/the one/settings"
media_policy_destination="$audio_software_destination/video decode service.json"

require_exact_directory() {
    candidate=$1
    expected=$2
    if [ "$candidate" != "$expected" ] || [ ! -d "$candidate" ] || [ -L "$candidate" ]; then
        echo "Scoped destination directory is absent or unsafe: $candidate" >&2
        exit 1
    fi
    resolved=$(readlink -f -- "$candidate")
    if [ "$resolved" != "$expected" ]; then
        echo "Scoped destination resolves unexpectedly: $candidate" >&2
        exit 1
    fi
}

require_exact_file_parent() {
    candidate=$1
    expected=$2
    if [ "$candidate" != "$expected" ] || [ -L "$candidate" ]; then
        echo "Scoped destination file is unsafe: $candidate" >&2
        exit 1
    fi
    parent=$(dirname -- "$candidate")
    if [ ! -d "$parent" ] || [ -L "$parent" ]; then
        echo "Scoped destination parent is absent or unsafe: $parent" >&2
        exit 1
    fi
    resolved=$(readlink -f -- "$parent")
    expected_parent=$(dirname -- "$expected")
    if [ "$resolved" != "$expected_parent" ]; then
        echo "Scoped destination parent resolves unexpectedly: $parent" >&2
        exit 1
    fi
}

require_exact_directory \
    "$audio_software_destination" \
    "$mount_point/the one/software/audio"
require_exact_directory \
    "$audio_catalogue_destination" \
    "$mount_point/the one/catalogue/audio"
require_exact_directory \
    "$chromium_runtime_destination" \
    "$mount_point/the one/software/chromium"
require_exact_directory \
    "$settings_destination" \
    "$mount_point/the one/settings"
require_exact_file_parent \
    "$goddess_destination" \
    "$mount_point/the one/build/GODDESS/GODDESS.py"
require_exact_file_parent \
    "$chromium_build_destination" \
    "$mount_point/the one/build/chromium/chromium.py"
if [ -L "$media_policy_destination" ]; then
    echo "Scoped packaged media policy destination is a symlink." >&2
    exit 1
fi
require_exact_file_parent \
    "$media_policy_destination" \
    "$mount_point/the one/software/audio/video decode service.json"

for destination in \
    "$audio_software_destination" \
    "$audio_catalogue_destination" \
    "$chromium_runtime_destination"
do
    if find "$destination" -type l -print -quit | grep -q .; then
        echo "Existing scoped runtime contains a symlink: $destination" >&2
        exit 1
    fi
done

for identity_path in \
    "$mount_point/the one/settings/runtime paths.json" \
    "$mount_point/autorun.inf"
do
    if [ ! -e "$identity_path" ] || [ -L "$identity_path" ]; then
        echo "Mounted drive is not a complete T1OS USB root." >&2
        exit 1
    fi
done
grep -Eiq '^[[:space:]]*Label=T1OS([[:space:]]|$)' \
    "$mount_point/autorun.inf" || {
    echo "Mounted drive lacks the exact T1OS identity marker." >&2
    exit 1
}

cp -- "$media_policy_source" "$stage/video-decode-service.json"
preserve_kill_switch=0
if python3 - "$media_policy_destination" <<'PY'
import json
import sys
try:
    with open(sys.argv[1], encoding="utf-8") as stream:
        value = json.load(stream)
except Exception:
    raise SystemExit(1)
raise SystemExit(
    0
    if (
        isinstance(value, dict)
        and value.get("kill_switch") is True
        and value.get("deployment_guard") is not True
    )
    else 1
)
PY
then
    preserve_kill_switch=1
    python3 - "$stage/video-decode-service.json" <<'PY'
import json
import sys
path = sys.argv[1]
with open(path, encoding="utf-8") as stream:
    value = json.load(stream)
if not isinstance(value, dict):
    raise SystemExit("source media policy is not an object")
value["kill_switch"] = True
with open(path, "w", encoding="utf-8", newline="\n") as stream:
    json.dump(value, stream, indent=2)
    stream.write("\n")
PY
    expected_kill=true
    echo "Preserving the existing emergency media-decode kill switch."
else
    expected_kill=false
fi

install_policy_atomically() {
    policy_source=$1
    policy_destination=$2
    policy_state=$3
    python3 - "$policy_source" "$policy_destination" "$policy_state" <<'PY'
import json
import os
import stat
import sys
from pathlib import Path

source = Path(sys.argv[1])
destination = Path(sys.argv[2])
state = sys.argv[3]
if state not in ("guard", "final"):
    raise SystemExit(f"invalid atomic policy state: {state!r}")

source_bytes = source.read_bytes()
if state == "guard":
    value = json.loads(source_bytes.decode("utf-8"))
    if not isinstance(value, dict):
        raise SystemExit("media guard policy source is not an object")
    value["enabled"] = False
    value["kill_switch"] = True
    value["deployment_guard"] = True
    payload = (json.dumps(value, indent=2) + "\n").encode("utf-8")
else:
    payload = source_bytes

parent = destination.parent
parent_flags = os.O_RDONLY | os.O_DIRECTORY
if hasattr(os, "O_NOFOLLOW"):
    parent_flags |= os.O_NOFOLLOW
directory_fd = os.open(parent, parent_flags)
temporary_name = (
    f".{destination.name}.t1os-policy-{state}-{os.getpid()}"
)
temporary_fd = -1
temporary_created = False
try:
    try:
        existing = os.stat(
            destination.name,
            dir_fd=directory_fd,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        existing = None
    if existing is not None and not stat.S_ISREG(existing.st_mode):
        raise SystemExit(
            f"refusing non-regular media policy destination: {destination}"
        )

    open_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        open_flags |= os.O_NOFOLLOW
    temporary_fd = os.open(
        temporary_name,
        open_flags,
        0o600,
        dir_fd=directory_fd,
    )
    temporary_created = True
    written = 0
    while written < len(payload):
        count = os.write(temporary_fd, payload[written:])
        if count <= 0:
            raise OSError("short atomic media policy write")
        written += count
    os.fchown(temporary_fd, 0, 0)
    os.fchmod(temporary_fd, 0o644)
    os.fsync(temporary_fd)
    os.close(temporary_fd)
    temporary_fd = -1

    os.replace(
        temporary_name,
        destination.name,
        src_dir_fd=directory_fd,
        dst_dir_fd=directory_fd,
    )
    os.fsync(directory_fd)

    verify_flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        verify_flags |= os.O_NOFOLLOW
    verify_fd = os.open(
        destination.name,
        verify_flags,
        dir_fd=directory_fd,
    )
    try:
        chunks = []
        while True:
            chunk = os.read(verify_fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        if b"".join(chunks) != payload:
            raise SystemExit(
                f"atomic media policy verification failed: {destination}"
            )
    finally:
        os.close(verify_fd)
finally:
    if temporary_fd >= 0:
        os.close(temporary_fd)
    if temporary_created:
        try:
            os.unlink(temporary_name, dir_fd=directory_fd)
        except FileNotFoundError:
            pass
    os.close(directory_fd)
PY
}

python3 "$validator" \
    "$goddess_source" \
    "$chromium_build_source" \
    "$native_protocol_header" \
    "$native_watchdog_header" \
    "$chromium_protocol_header" \
    "$chromium_source_manifest" \
    "$audio_software_source" \
    "$audio_catalogue_source" \
    "$chromium_runtime_source" \
    "$stage/video-decode-service.json" \
    "$expected_kill"

required_kib=$(
    du -sk \
        "$audio_software_source" \
        "$audio_catalogue_source" \
        "$chromium_runtime_source" |
        awk '{total += $1} END {print total + 262144}'
)
available_kib=$(df -Pk "$mount_point" | awk 'NR == 2 {print $4}')
if [ -z "$available_kib" ] || [ "$available_kib" -lt "$required_kib" ]; then
    echo "T1OS USB lacks the conservative free-space reserve for this runtime." >&2
    exit 1
fi

require_exact_file_parent \
    "$media_policy_destination" \
    "$mount_point/the one/software/audio/video decode service.json"

# Fail closed before replacing any executable/runtime byte. If rsync,
# validation, power, or unmount fails after this point, the USB retains an
# atomically installed disabled + kill-switched policy on its next boot.
guard_recovery_required=1
install_policy_atomically \
    "$stage/video-decode-service.json" \
    "$media_policy_destination" \
    guard
sync
echo "Installed fail-closed media policy guard before runtime mutation."

# These are the only destination trees and files this script may mutate.
rsync -a --no-whole-file --checksum --delete \
    --no-owner --no-group --no-perms \
    --no-times --omit-dir-times -- \
    "$audio_catalogue_source"/ "$audio_catalogue_destination"/
rsync -a --no-whole-file --checksum --delete \
    --exclude='/video decode service.json' \
    --no-owner --no-group --no-perms \
    --no-times --omit-dir-times -- \
    "$audio_software_source"/ "$audio_software_destination"/
rsync -a --no-whole-file --checksum --delete \
    --exclude='/program/chrome-sandbox' \
    --exclude='/tools/t1os-chrome-subprocess' \
    --no-owner --no-group --no-perms \
    --no-times --omit-dir-times -- \
    "$chromium_runtime_source"/ "$chromium_runtime_destination"/
rsync -a --no-whole-file --checksum \
    --no-owner --no-group --no-perms \
    --no-times --omit-dir-times -- \
    "$goddess_source" "$goddess_destination"
rsync -a --no-whole-file --checksum \
    --no-owner --no-group --no-perms \
    --no-times --omit-dir-times -- \
    "$chromium_build_source" "$chromium_build_destination"

# DrvFS must preserve the pre-existing T1OS NTFS ACLs. Reasserting ownership
# recursively is both unnecessary (the mount maps new files to uid/gid zero)
# and can be rejected by intentionally read-only executable ACLs. Validate
# effective ownership/access instead. Replace the SUID sandbox and measured
# subprocess helper separately under fresh names, fsync them, and use a bounded
# remove-and-rename fallback when a protected legacy ACL rejects replace.
python3 - \
    "$chromium_runtime_source/program/chrome-sandbox" \
    "$chromium_runtime_destination/program/chrome-sandbox" \
    4755 \
    "$chromium_runtime_source/tools/t1os-chrome-subprocess" \
    "$chromium_runtime_destination/tools/t1os-chrome-subprocess" \
    755 <<'PY'
import os
import shutil
import stat
import sys
from pathlib import Path

if len(sys.argv) != 7:
    raise SystemExit("protected Chromium helper replacement arguments changed")

for offset in (1, 4):
    source = Path(sys.argv[offset])
    destination = Path(sys.argv[offset + 1])
    expected_mode = int(sys.argv[offset + 2], 8)
    parent = destination.parent
    temporary = parent / f".{destination.name}.t1os-{os.getpid()}"
    if temporary.exists() or temporary.is_symlink():
        raise SystemExit(f"refusing stale helper temporary: {temporary}")
    try:
        with source.open("rb") as source_stream, temporary.open("xb") as target:
            shutil.copyfileobj(source_stream, target, 1024 * 1024)
            target.flush()
            os.fchown(target.fileno(), 0, 0)
            os.fchmod(target.fileno(), expected_mode)
            os.fsync(target.fileno())
        try:
            os.replace(temporary, destination)
        except PermissionError:
            # A legacy NTFS ACL can permit parent delete/create while denying
            # the ReplaceFile-style operation used by DrvFS. The service is
            # already kill-switched, so remove only this attested helper and
            # immediately rename the fully fsynced replacement into place.
            destination.unlink()
            try:
                os.rename(temporary, destination)
            except BaseException:
                if not destination.exists():
                    with source.open("rb") as source_stream, destination.open(
                        "xb"
                    ) as target:
                        shutil.copyfileobj(
                            source_stream, target, 1024 * 1024
                        )
                        target.flush()
                        os.fchown(target.fileno(), 0, 0)
                        os.fchmod(target.fileno(), expected_mode)
                        os.fsync(target.fileno())
                raise
        directory_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass

    details = destination.stat()
    if (
        details.st_uid != 0
        or details.st_gid != 0
        or stat.S_IMODE(details.st_mode) != expected_mode
    ):
        raise SystemExit(
            f"T1OS protected helper permission contract failed: {destination}"
        )
PY

for owned_path in \
    "$audio_catalogue_destination" \
    "$audio_software_destination" \
    "$chromium_runtime_destination" \
    "$goddess_destination" \
    "$chromium_build_destination"
do
    if [ "$(stat -c '%u:%g' "$owned_path")" != "0:0" ]; then
        echo "Scoped runtime is not effectively root-owned: $owned_path" >&2
        exit 1
    fi
done
for executable in \
    "$audio_software_destination/ffmpeg" \
    "$audio_software_destination/ffprobe" \
    "$audio_software_destination/t1-media-decoderd" \
    "$audio_software_destination/t1-video-decode" \
    "$chromium_runtime_destination/program/chrome" \
    "$chromium_runtime_destination/program/chrome_crashpad_handler" \
    "$chromium_runtime_destination/libraries/ld-linux-x86-64.so.2"
do
    if [ ! -f "$executable" ] || [ ! -x "$executable" ]; then
        echo "Scoped runtime executable is not executable: $executable" >&2
        exit 1
    fi
done
if find "$chromium_runtime_destination/tools" -type f \
    ! -perm /111 -print -quit | grep -q .; then
    echo "A Chromium runtime tool is not executable." >&2
    exit 1
fi
if [ ! -r "$goddess_destination" ] || [ ! -r "$chromium_build_destination" ]; then
    echo "A scoped Python launcher is not readable." >&2
    exit 1
fi

verify_tree() {
    label=$1
    source=$2
    destination=$3
    preserve_policy=${4:-false}
    if [ "$preserve_policy" = true ]; then
        differences=$(
            rsync -a --no-whole-file --checksum --delete \
                --exclude='/video decode service.json' \
                --no-owner --no-group --no-perms \
                --no-times --omit-dir-times \
                --itemize-changes --dry-run -- \
                "$source"/ "$destination"/
        )
    else
        differences=$(
            rsync -a --no-whole-file --checksum --delete \
                --no-owner --no-group --no-perms \
                --no-times --omit-dir-times \
                --itemize-changes --dry-run -- \
                "$source"/ "$destination"/
        )
    fi
    if [ -n "$differences" ]; then
        echo "$label post-copy checksum verification failed:" >&2
        printf '%s\n' "$differences" >&2
        exit 1
    fi
}

verify_tree \
    "audio catalogue" \
    "$audio_catalogue_source" \
    "$audio_catalogue_destination"
verify_tree \
    "audio software" \
    "$audio_software_source" \
    "$audio_software_destination" \
    true
verify_tree \
    "Chromium runtime" \
    "$chromium_runtime_source" \
    "$chromium_runtime_destination"
cmp -s -- "$goddess_source" "$goddess_destination"
cmp -s -- "$chromium_build_source" "$chromium_build_destination"

readelf -h "$audio_software_destination/t1-media-decoderd" >/dev/null
readelf -h "$audio_software_destination/t1-video-decode" >/dev/null
readelf -h "$chromium_runtime_destination/program/chrome" >/dev/null
readelf -h "$chromium_runtime_destination/program/chrome-sandbox" >/dev/null

# Prove the copied runtime before enabling its policy on the USB.
python3 "$validator" \
    "$goddess_destination" \
    "$chromium_build_destination" \
    "$native_protocol_header" \
    "$native_watchdog_header" \
    "$chromium_protocol_header" \
    "$chromium_source_manifest" \
    "$audio_software_destination" \
    "$audio_catalogue_destination" \
    "$chromium_runtime_destination" \
    "$stage/video-decode-service.json" \
    "$expected_kill"

# The exact helper inventory and copied hash have now passed validation.
if [ "$(stat -c '%u:%g:%a' \
        "$chromium_runtime_destination/program/chrome-sandbox")" != \
        "0:0:4755" ]; then
    echo "T1OS chrome-sandbox permission contract failed." >&2
    exit 1
fi

require_exact_file_parent \
    "$media_policy_destination" \
    "$mount_point/the one/software/audio/video decode service.json"

# The final enabled policy is the last functional runtime mutation. Its
# same-directory fsync + atomic rename prevents a torn policy on power loss.
# Flush every previously validated runtime and privileged-mode write first, so
# the enabled policy can never become durable ahead of the bytes it activates.
sync
install_policy_atomically \
    "$stage/video-decode-service.json" \
    "$media_policy_destination" \
    final
cmp -s -- "$stage/video-decode-service.json" "$media_policy_destination"

python3 "$validator" \
    "$goddess_destination" \
    "$chromium_build_destination" \
    "$native_protocol_header" \
    "$native_watchdog_header" \
    "$chromium_protocol_header" \
    "$chromium_source_manifest" \
    "$audio_software_destination" \
    "$audio_catalogue_destination" \
    "$chromium_runtime_destination" \
    "$media_policy_destination" \
    "$expected_kill"

printf 'GODDESS SHA-256: '
sha256sum "$goddess_destination" | awk '{print $1}'
printf 'Chromium launcher SHA-256: '
sha256sum "$chromium_build_destination" | awk '{print $1}'
printf 'Native decoder daemon SHA-256: '
sha256sum "$audio_software_destination/t1-media-decoderd" | awk '{print $1}'
printf 'Chromium engine SHA-256: '
sha256sum "$chromium_runtime_destination/program/chrome" | awk '{print $1}'

sync
guard_recovery_required=0
echo "Scoped T1OS media runtime synchronization and verification passed."
'@

$validatorPath = Join-Path (
    [System.IO.Path]::GetTempPath()
) "t1os-media-runtime-validator-$([guid]::NewGuid().ToString('N')).py"
$copyScriptPath = Join-Path (
    [System.IO.Path]::GetTempPath()
) "t1os-media-runtime-copy-$([guid]::NewGuid().ToString('N')).sh"
$readOnlyReplacementTargets = @()

try {
    [System.IO.File]::WriteAllText(
        $validatorPath,
        $validatorCode,
        [System.Text.UTF8Encoding]::new($false)
    )

    $wslValidator = ConvertTo-WslPath -WindowsPath $validatorPath
    $wslGoddessSource = ConvertTo-WslPath -WindowsPath $goddessSource
    $wslChromiumBuildSource = ConvertTo-WslPath -WindowsPath $chromiumBuildSource
    $wslNativeProtocolHeader = ConvertTo-WslPath -WindowsPath $nativeProtocolHeader
    $wslNativeWatchdogHeader = ConvertTo-WslPath -WindowsPath $nativeWatchdogHeader
    $wslChromiumProtocolHeader = ConvertTo-WslPath -WindowsPath $chromiumProtocolHeader
    $wslChromiumSourceManifest = ConvertTo-WslPath -WindowsPath $chromiumSourceManifest
    $wslAudioSoftwareSource = ConvertTo-WslPath -WindowsPath $audioSoftwareSource
    $wslAudioCatalogueSource = ConvertTo-WslPath -WindowsPath $audioCatalogueSource
    $wslChromiumRuntimeSource = ConvertTo-WslPath -WindowsPath $chromiumRuntimeSource
    $wslMediaPolicySource = ConvertTo-WslPath -WindowsPath $mediaPolicySource

    & wsl.exe -d Ubuntu --exec python3 $wslValidator `
        $wslGoddessSource `
        $wslChromiumBuildSource `
        $wslNativeProtocolHeader `
        $wslNativeWatchdogHeader `
        $wslChromiumProtocolHeader `
        $wslChromiumSourceManifest `
        $wslAudioSoftwareSource `
        $wslAudioCatalogueSource `
        $wslChromiumRuntimeSource `
        $wslMediaPolicySource `
        false
    if ($LASTEXITCODE -ne 0) {
        throw 'Scoped media-runtime source validation failed.'
    }

    $sourceBytes = (
        Get-ChildItem -LiteralPath $audioSoftwareSource -Recurse -File |
            Measure-Object -Property Length -Sum
    ).Sum + (
        Get-ChildItem -LiteralPath $audioCatalogueSource -Recurse -File |
            Measure-Object -Property Length -Sum
    ).Sum + (
        Get-ChildItem -LiteralPath $chromiumRuntimeSource -Recurse -File |
            Measure-Object -Property Length -Sum
    ).Sum
    Write-Host (
        (
            'Validated scoped payload: {0:N2} GiB. No boot, driver, network, ' +
            'resource, image, bundle, or log path is in the copy set.'
        ) -f
        ([double]$sourceBytes / 1GB)
    )

    if (-not $PSCmdlet.ShouldProcess(
        $usbTarget.Root,
        'Synchronize only the compiled T1MD/Chromium runtime, its two Python launchers, and media policy'
    )) {
        Write-Host 'Scoped media-runtime USB synchronization was not executed.'
        exit 0
    }

    # DrvFS cannot atomically rename a new rsync file over an NTFS target that
    # has the Windows read-only attribute.  Snapshot and temporarily clear that
    # attribute only inside the scoped runtime trees, then restore it in the
    # outer finally block even if validation or synchronization fails.
    $replacementRoots = @(
        (Join-Path $usbTarget.Root 'the one\software\audio'),
        (Join-Path $usbTarget.Root 'the one\catalogue\audio'),
        (Join-Path $usbTarget.Root 'the one\software\chromium')
    )
    $readOnlyReplacementTargets = @(
        foreach ($replacementRoot in $replacementRoots) {
            Get-ChildItem -LiteralPath $replacementRoot -Recurse -File -Force |
                Where-Object { $_.IsReadOnly } |
                ForEach-Object { $_.FullName }
        }
    )
    foreach ($readOnlyTarget in $readOnlyReplacementTargets) {
        (Get-Item -LiteralPath $readOnlyTarget -Force).IsReadOnly = $false
    }

    [System.IO.File]::WriteAllText(
        $copyScriptPath,
        $copyCommand,
        [System.Text.UTF8Encoding]::new($false)
    )
    $wslCopyScript = ConvertTo-WslPath -WindowsPath $copyScriptPath

    & wsl.exe -d Ubuntu -u root --exec sh $wslCopyScript `
        $wslValidator `
        $wslGoddessSource `
        $wslChromiumBuildSource `
        $wslNativeProtocolHeader `
        $wslNativeWatchdogHeader `
        $wslChromiumProtocolHeader `
        $wslChromiumSourceManifest `
        $wslAudioSoftwareSource `
        $wslAudioCatalogueSource `
        $wslChromiumRuntimeSource `
        $wslMediaPolicySource `
        $mountPoint `
        $usbTarget.DriveSource
    if ($LASTEXITCODE -ne 0) {
        throw (
            'Scoped media-runtime synchronization failed with exit code ' +
            "$LASTEXITCODE."
        )
    }
}
finally {
    foreach ($readOnlyTarget in $readOnlyReplacementTargets) {
        if (Test-Path -LiteralPath $readOnlyTarget -PathType Leaf) {
            (Get-Item -LiteralPath $readOnlyTarget -Force).IsReadOnly = $true
        }
    }
    foreach ($temporaryPath in @($copyScriptPath, $validatorPath)) {
        if (Test-Path -LiteralPath $temporaryPath) {
            Remove-Item -LiteralPath $temporaryPath -Force `
                -WhatIf:$false -Confirm:$false
        }
    }
}

$updatedVolume = Get-Volume -DriveLetter $usbTarget.DriveLetter -ErrorAction Stop
if (
    [string]$updatedVolume.FileSystemType -cne 'NTFS' -or
    [string]$updatedVolume.HealthStatus -cne 'Healthy' -or
    -not ([string]$updatedVolume.FileSystemLabel).StartsWith(
        'T1OS',
        [StringComparison]::OrdinalIgnoreCase
    )
) {
    throw (
        'The scoped T1OS USB target did not remain a healthy, labelled NTFS ' +
        'volume after synchronization.'
    )
}

Write-Host (
    "Scoped media runtime push completed. $($usbTarget.DriveLetter): remains " +
    'available in Windows; no image or bundle was rebuilt.'
)
