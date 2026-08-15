[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Path $PSScriptRoot -Parent
$compatibilityPath = Join-Path $projectRoot 'source\drivers\settings\desktop compatibility.json'
$policyPath = Join-Path $projectRoot 'source\drivers\settings\policy.json'
$kernelConfigPath = Join-Path $projectRoot 'resource\entry\kernel\T10Skernel hardware 0.19 settings.txt'
$modulesPath = Join-Path $projectRoot 'environment\hardware\modules.tar.zst'
$firmwarePath = Join-Path $projectRoot 'environment\hardware\firmware.tar.zst'
$firmwareManifestPath = Join-Path $projectRoot 'environment\hardware\t1os-firmware-manifest.json'
$graphicsPath = Join-Path $projectRoot 'source\catalogue\graphics'
$reportPath = Join-Path $projectRoot 'environment\hardware\desktop-compatibility-report.json'

function ConvertTo-WslPath {
    param([Parameter(Mandatory)][string]$WindowsPath)

    $output = & wsl.exe -d Ubuntu --exec wslpath -a $WindowsPath
    if ($LASTEXITCODE -ne 0 -or -not $output) {
        throw "Could not translate path for WSL: $WindowsPath"
    }
    return ([string]($output | Select-Object -First 1)).Trim()
}

foreach ($requiredFile in @($compatibilityPath, $policyPath, $kernelConfigPath, $modulesPath, $firmwarePath, $firmwareManifestPath)) {
    if (-not (Test-Path -LiteralPath $requiredFile -PathType Leaf)) {
        throw "Required desktop compatibility input not found: $requiredFile"
    }
}
foreach ($requiredDirectory in @($graphicsPath)) {
    if (-not (Test-Path -LiteralPath $requiredDirectory -PathType Container)) {
        throw "Required desktop compatibility directory not found: $requiredDirectory"
    }
}
if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    throw 'WSL is required to validate hardware compatibility.'
}

$wslCompatibility = ConvertTo-WslPath -WindowsPath $compatibilityPath
$wslPolicy = ConvertTo-WslPath -WindowsPath $policyPath
$wslKernelConfig = ConvertTo-WslPath -WindowsPath $kernelConfigPath
$wslModules = ConvertTo-WslPath -WindowsPath $modulesPath
$wslFirmware = ConvertTo-WslPath -WindowsPath $firmwarePath
$wslFirmwareManifest = ConvertTo-WslPath -WindowsPath $firmwareManifestPath
$wslGraphics = ConvertTo-WslPath -WindowsPath $graphicsPath
$wslReport = ConvertTo-WslPath -WindowsPath $reportPath

$validateCommand = @'
set -euo pipefail
umask 077

compatibility=$1
policy=$2
kernel_config=$3
modules_archive=$4
firmware_archive=$5
firmware_manifest=$6
graphics=$7
report=$8

for command_name in python3 tar zstd modinfo modprobe sha256sum mktemp; do
    command -v "$command_name" >/dev/null 2>&1 || {
        echo "Required compatibility validation command not found: $command_name" >&2
        exit 127
    }
done

work=$(mktemp -d /var/tmp/t1os-desktop-compatibility.XXXXXX)
case "$work" in
    /var/tmp/t1os-desktop-compatibility.*) ;;
    *)
        echo "Unexpected compatibility work path: $work" >&2
        exit 1
        ;;
esac
cleanup() {
    case "${work:-}" in
        /var/tmp/t1os-desktop-compatibility.*)
            if [ -d "$work" ] && [ ! -L "$work" ]; then
                rm -rf -- "$work"
            fi
            ;;
    esac
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
[ -d "$work" ]
[ ! -L "$work" ]
chmod 0700 -- "$work"
tar --zstd -xf "$modules_archive" -C "$work"

module_store="$work/the one/drivers/modules"
release=$(find "$module_store" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort | head -n 1)
[ -n "$release" ]
test -s "$module_store/$release/modules.dep"
test -s "$module_store/$release/modules.alias"
test -s "$module_store/module-manifest.sha256"
(cd "$module_store" && sha256sum -c --quiet module-manifest.sha256)

# Host kmod expects a conventional lookup root. This transient build-host link
# does not become part of T1OS; the shipped module tree remains /the one/drivers.
mkdir -p "$work/lib"
ln -s "$module_store" "$work/lib/modules"
mkdir -p "$work/firmware"
tar --zstd -xf "$firmware_archive" -C "$work/firmware"

python3 - "$compatibility" "$policy" "$kernel_config" "$work" "$release" "$modules_archive" "$work/firmware" "$firmware_manifest" "$graphics" "$report" <<'PY'
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
import hashlib
import json
import os
import re
import subprocess
import sys

(
    compatibility_path,
    policy_path,
    kernel_config_path,
    kmod_root_path,
    release,
    modules_archive_path,
    firmware_root_path,
    external_firmware_manifest_path,
    graphics_root_path,
    report_path,
) = sys.argv[1:]

compatibility_path = Path(compatibility_path)
policy_path = Path(policy_path)
kernel_config_path = Path(kernel_config_path)
kmod_root = Path(kmod_root_path)
module_root = kmod_root / 'the one/drivers/modules' / release
firmware_root = Path(firmware_root_path)
external_firmware_manifest_path = Path(external_firmware_manifest_path)
graphics_root = Path(graphics_root_path)
report_path = Path(report_path)

def load_json(path):
    with path.open('r', encoding='utf-8') as handle:
        return json.load(handle)

def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()

def normalize_module(value):
    return str(value).strip().replace('-', '_')

def run(command):
    return subprocess.run(
        command,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

compatibility = load_json(compatibility_path)
policy = load_json(policy_path)
if compatibility.get('format') != 1:
    raise SystemExit('desktop compatibility format is not supported')
if policy.get('format') != 1:
    raise SystemExit('driver policy format is not supported')

groups = compatibility.get('module_groups')
if not isinstance(groups, dict) or not groups:
    raise SystemExit('desktop compatibility module groups are missing')
contract_modules = {
    normalize_module(module)
    for modules in groups.values()
    for module in modules
}
policy_modules = {normalize_module(module) for module in policy.get('allowed_modules', [])}
if contract_modules != policy_modules:
    raise SystemExit(json.dumps({
        'message': 'driver policy and desktop compatibility contract differ',
        'missing_from_policy': sorted(contract_modules - policy_modules),
        'missing_from_contract': sorted(policy_modules - contract_modules),
    }, indent=2))

config = kernel_config_path.read_text(encoding='utf-8')
missing_builtins = [
    feature for feature in compatibility.get('built_in_kernel_features', [])
    if f'CONFIG_{feature}=y' not in config
]
if missing_builtins:
    raise SystemExit('boot-critical kernel features are not built in: ' + ', '.join(missing_builtins))

for relative in compatibility.get('firmware_roots', []):
    candidate = firmware_root / PurePosixPath(relative)
    if not candidate.is_dir() or not any(path.is_file() for path in candidate.rglob('*')):
        raise SystemExit(f'declared firmware root is missing or empty: {relative}')
for relative in compatibility.get('required_firmware_files', []):
    candidate = firmware_root / PurePosixPath(relative)
    if not candidate.is_file() or candidate.stat().st_size < 1:
        raise SystemExit(f'required firmware file is missing: {relative}')

firmware_manifest_path = firmware_root / 't1os-firmware-manifest.json'
firmware_manifest = load_json(firmware_manifest_path)
if firmware_manifest != load_json(external_firmware_manifest_path):
    raise SystemExit('external and archived firmware manifests differ')
if firmware_manifest.get('format') != 2:
    raise SystemExit('firmware manifest is not the complete format-2 payload')
firmware_manifest_entries = firmware_manifest.get('files')
if not isinstance(firmware_manifest_entries, list) or not firmware_manifest_entries:
    raise SystemExit('firmware manifest contains no files')
manifest_firmware_paths = set()
for entry in firmware_manifest_entries:
    relative = str(entry.get('path', ''))
    candidate = firmware_root / PurePosixPath(relative)
    if not relative or not candidate.is_file():
        raise SystemExit(f'firmware manifest file is missing: {relative}')
    if candidate.stat().st_size != int(entry.get('size', -1)):
        raise SystemExit(f'firmware manifest size mismatch: {relative}')
    if sha256(candidate) != str(entry.get('sha256', '')).lower():
        raise SystemExit(f'firmware manifest hash mismatch: {relative}')
    manifest_firmware_paths.add(relative)

dep_lines = (module_root / 'modules.dep').read_text(encoding='utf-8').splitlines()
module_files = set()
for line in dep_lines:
    if not line:
        continue
    owner, dependencies = line.split(':', 1)
    module_files.add(owner)
    module_files.update(dependencies.split())
missing_dependency_files = sorted(
    relative for relative in module_files
    if not (module_root / PurePosixPath(relative)).is_file()
)
if missing_dependency_files:
    raise SystemExit('module dependency metadata references missing files: ' + ', '.join(missing_dependency_files[:20]))

dependency_only = {
    normalize_module(module)
    for module in compatibility.get('dependency_only_modules', [])
}
module_closure = set()
alias_counts = {}
module_paths = {}
for module in sorted(policy_modules):
    filename = run([
        'modinfo', '-b', str(kmod_root), '-k', release, '-F', 'filename', module,
    ])
    if filename.returncode != 0 or not filename.stdout.strip():
        raise SystemExit(f'allowed module is absent from the archive: {module}: {filename.stderr.strip()}')
    resolved_path = Path(filename.stdout.strip().splitlines()[0])
    if not resolved_path.is_file():
        raise SystemExit(f'allowed module path is missing: {module}: {resolved_path}')
    module_paths[module] = resolved_path

    aliases = run([
        'modinfo', '-b', str(kmod_root), '-k', release, '-F', 'alias', module,
    ])
    alias_count = len([line for line in aliases.stdout.splitlines() if line.strip()])
    alias_counts[module] = alias_count
    if module not in dependency_only and alias_count < 1:
        raise SystemExit(f'allowed cold-plug module exposes no device alias: {module}')

    closure = run([
        'modprobe', '--dirname', str(kmod_root), '--set-version', release,
        '--show-depends', module,
    ])
    if closure.returncode != 0:
        raise SystemExit(f'module dependency resolution failed for {module}: {closure.stderr.strip()}')
    for line in closure.stdout.splitlines():
        kind, _, value = line.partition(' ')
        if kind == 'insmod':
            dependency_path = Path(value.strip())
            if not dependency_path.is_file():
                raise SystemExit(f'module dependency is missing for {module}: {dependency_path}')
            module_closure.add(dependency_path)

declared_firmware = set()
dynamic_firmware = set()
unpublished_firmware = set()
modules_without_published_firmware = []
for module_path in sorted(module_closure):
    information = run(['modinfo', '-F', 'firmware', str(module_path)])
    if information.returncode != 0:
        raise SystemExit(f'could not inspect module firmware declarations: {module_path}')
    module_declared_firmware = set()
    module_published_firmware = set()
    module_dynamic_firmware = set()
    for line in information.stdout.splitlines():
        relative = line.strip()
        if not relative:
            continue
        if (
            relative.startswith('/')
            or '..' in PurePosixPath(relative).parts
            or any(token in relative for token in ('*', '?', '%', '{', '}'))
        ):
            dynamic_firmware.add(relative)
            module_dynamic_firmware.add(relative)
            continue
        declared_firmware.add(relative)
        module_declared_firmware.add(relative)
        if (firmware_root / PurePosixPath(relative)).is_file():
            module_published_firmware.add(relative)
        else:
            unpublished_firmware.add(relative)
    # Kernel modules often retain fallback filenames for firmware revisions
    # that upstream no longer publishes. Requiring every historical name
    # would make a current official linux-firmware release impossible to use.
    # The strict gate is instead: ship the complete pinned WHENCE catalogue,
    # record every unpublished declaration, and require each firmware-using
    # module to have at least one concrete published payload (or a dynamic
    # declaration whose final device-specific name is resolved at runtime).
    if (
        module_declared_firmware
        and not module_published_firmware
        and not module_dynamic_firmware
    ):
        modules_without_published_firmware.append(module_path.name)
if modules_without_published_firmware:
    raise SystemExit(
        'supported modules have no published firmware payload: '
        + ', '.join(sorted(modules_without_published_firmware))
    )
unmanifested_firmware = sorted(
    (declared_firmware - unpublished_firmware) - manifest_firmware_paths
)
if unmanifested_firmware:
    raise SystemExit(
        'module firmware is present but not integrity-manifested: '
        + ', '.join(unmanifested_firmware[:50])
    )

graphics_manifest_path = graphics_root / 'catalogue.json'
graphics_manifest = load_json(graphics_manifest_path)
if graphics_manifest.get('state') != 'ready' or graphics_manifest.get('profile') != 'hardware':
    raise SystemExit('graphics catalogue is not a ready hardware profile')
graphics_entries = graphics_manifest.get('files')
if not isinstance(graphics_entries, list) or not graphics_entries:
    raise SystemExit('graphics catalogue contains no files')
graphics_files = {}
for entry in graphics_entries:
    relative = str(entry.get('path', ''))
    candidate = graphics_root / PurePosixPath(relative)
    if not relative or not candidate.is_file():
        raise SystemExit(f'graphics catalogue file is missing: {relative}')
    if candidate.stat().st_size != int(entry.get('size', -1)):
        raise SystemExit(f'graphics catalogue size mismatch: {relative}')
    if sha256(candidate) != str(entry.get('sha256', '')).lower():
        raise SystemExit(f'graphics catalogue hash mismatch: {relative}')
    graphics_files[relative] = entry

missing_graphics_files = sorted(
    set(compatibility['graphics_runtime'].get('required_files', []))
    - set(graphics_files)
)
if missing_graphics_files:
    raise SystemExit('required graphics runtime files are missing: ' + ', '.join(missing_graphics_files))
missing_graphics_drivers = sorted(
    set(compatibility['graphics_runtime'].get('manifest_drivers', []))
    - set(graphics_manifest.get('drivers', []))
)
if missing_graphics_drivers:
    raise SystemExit('required graphics drivers are missing: ' + ', '.join(missing_graphics_drivers))

# NVIDIA's open kernel modules, GSP firmware, and EGL/OpenGL userspace are one
# versioned driver release.  A partially updated stack is not boot-compatible,
# so reject the image unless all three independently staged artifacts identify
# the exact same release and the two runfile-derived payloads record the same
# pinned installer hash.
nvidia_sources = graphics_manifest.get('sources')
if not isinstance(nvidia_sources, dict):
    raise SystemExit('graphics catalogue sources are missing')
nvidia_graphics_source = nvidia_sources.get('nvidia_open_driver')
if not isinstance(nvidia_graphics_source, dict):
    raise SystemExit('graphics catalogue NVIDIA open-driver source is missing')

nvidia_graphics_version = str(nvidia_graphics_source.get('version', '')).strip()
nvidia_firmware_version = str(
    firmware_manifest.get('nvidia_open_driver_version', '')
).strip()
if not nvidia_graphics_version or not re.fullmatch(
    r'[0-9]+(?:\.[0-9]+)+', nvidia_graphics_version
):
    raise SystemExit(
        'graphics catalogue NVIDIA open-driver version is missing or invalid: '
        + repr(nvidia_graphics_version)
    )
if not nvidia_firmware_version:
    raise SystemExit('firmware manifest NVIDIA open-driver version is missing')

nvidia_graphics_runfile_sha256 = str(
    nvidia_graphics_source.get('runfile_sha256', '')
).strip()
nvidia_firmware_runfile_sha256 = str(
    firmware_manifest.get('nvidia_open_driver_archive_sha256', '')
).strip()
for label, value in (
    ('graphics catalogue NVIDIA runfile', nvidia_graphics_runfile_sha256),
    ('firmware manifest NVIDIA runfile', nvidia_firmware_runfile_sha256),
):
    if not re.fullmatch(r'[0-9a-f]{64}', value):
        raise SystemExit(f'{label} SHA-256 is missing or invalid: {value!r}')

nvidia_module_path = module_paths.get('nvidia')
if nvidia_module_path is None:
    raise SystemExit('NVIDIA open kernel module is absent from the validated module policy')
nvidia_module_information = run([
    'modinfo', '-F', 'version', str(nvidia_module_path),
])
nvidia_module_versions = [
    line.strip()
    for line in nvidia_module_information.stdout.splitlines()
    if line.strip()
]
if (
    nvidia_module_information.returncode != 0
    or len(nvidia_module_versions) != 1
):
    raise SystemExit(
        'could not determine one authoritative NVIDIA kernel-module version: '
        + nvidia_module_information.stderr.strip()
    )
nvidia_module_version = nvidia_module_versions[0]

nvidia_uvm_module_path = module_paths.get('nvidia_uvm')
if nvidia_uvm_module_path is None:
    raise SystemExit(
        'NVIDIA UVM kernel module is absent from the validated module policy'
    )
nvidia_uvm_module_information = run([
    'modinfo', '-F', 'version', str(nvidia_uvm_module_path),
])
nvidia_uvm_module_versions = [
    line.strip()
    for line in nvidia_uvm_module_information.stdout.splitlines()
    if line.strip()
]
if (
    nvidia_uvm_module_information.returncode != 0
    or len(nvidia_uvm_module_versions) != 1
):
    raise SystemExit(
        'could not determine one authoritative NVIDIA UVM module version: '
        + nvidia_uvm_module_information.stderr.strip()
    )
nvidia_uvm_module_version = nvidia_uvm_module_versions[0]

nvidia_versions = {
    'graphics_catalogue': nvidia_graphics_version,
    'firmware_manifest': nvidia_firmware_version,
    'kernel_module': nvidia_module_version,
    'kernel_uvm_module': nvidia_uvm_module_version,
}
if len(set(nvidia_versions.values())) != 1:
    raise SystemExit(json.dumps({
        'message': 'NVIDIA open-driver versions do not match',
        'versions': nvidia_versions,
    }, indent=2))
if nvidia_graphics_runfile_sha256 != nvidia_firmware_runfile_sha256:
    raise SystemExit(json.dumps({
        'message': 'NVIDIA runfile hashes do not match',
        'graphics_catalogue': nvidia_graphics_runfile_sha256,
        'firmware_manifest': nvidia_firmware_runfile_sha256,
    }, indent=2))

video_contract = compatibility.get('video_decode')
if not isinstance(video_contract, dict) or video_contract.get('api') != 'vaapi':
    raise SystemExit('hardware compatibility video-decode contract is missing or invalid')
video_backends = video_contract.get('backends')
if not isinstance(video_backends, list) or not video_backends:
    raise SystemExit('hardware compatibility video-decode backends are missing')
required_video_drm = {
    'i915', 'xe', 'amdgpu', 'radeon', 'nvidia', 'nvidia-drm', 'nouveau',
    'vmwgfx', 'virtio_gpu',
}
declared_video_drm = set()
required_video_files = set()
for backend in video_backends:
    if not isinstance(backend, dict):
        raise SystemExit('video-decode backend is not an object')
    drm_drivers = {
        str(value).strip().lower()
        for value in backend.get('drm_drivers', [])
        if str(value).strip()
    }
    vaapi_drivers = [
        str(value).strip()
        for value in backend.get('vaapi_drivers', [])
        if str(value).strip()
    ]
    declared_video_drm.update(drm_drivers)
    backend_required = {
        str(value).strip()
        for value in backend.get('required_files', [])
        if str(value).strip()
    }
    required_video_files.update(backend_required)
    if vaapi_drivers and not backend_required:
        raise SystemExit(
            'hardware video backend has VAAPI candidates but no required artifact: '
            + ', '.join(sorted(drm_drivers))
        )
missing_video_drm = sorted(required_video_drm - declared_video_drm)
if missing_video_drm:
    raise SystemExit(
        'hardware video contract is missing DRM backends: '
        + ', '.join(missing_video_drm)
    )
missing_video_files = sorted(required_video_files - set(graphics_files))
if missing_video_files:
    raise SystemExit(
        'hardware video contract artifacts are missing: '
        + ', '.join(missing_video_files)
    )
provided_sonames = {Path(relative).name for relative in graphics_files}
base_dependencies = set(graphics_manifest.get('runtime', {}).get('base_dependencies', []))
unresolved_graphics = sorted({
    dependency
    for entry in graphics_entries
    for dependency in entry.get('needed', [])
    if dependency not in provided_sonames and dependency not in base_dependencies
})
if unresolved_graphics:
    raise SystemExit('graphics runtime dependencies are unresolved: ' + ', '.join(unresolved_graphics))

report = {
    'format': 1,
    'state': 'ready',
    'generated_utc': datetime.now(timezone.utc).isoformat(),
    'profile': compatibility['profile'],
    'generation_window': compatibility['generation_window'],
    'architecture': compatibility['architecture'],
    'kernel_release': release,
    'contract_sha256': sha256(compatibility_path),
    'policy_sha256': sha256(policy_path),
    'kernel_config_sha256': sha256(kernel_config_path),
    'modules_archive_sha256': sha256(modules_archive_path),
    'firmware_manifest_sha256': sha256(firmware_manifest_path),
    'graphics_manifest_sha256': sha256(graphics_manifest_path),
    'nvidia_open_driver': {
        'version': nvidia_graphics_version,
        'runfile_sha256': nvidia_graphics_runfile_sha256,
        'graphics_catalogue_version': nvidia_graphics_version,
        'graphics_catalogue_runfile_sha256': nvidia_graphics_runfile_sha256,
        'firmware_manifest_version': nvidia_firmware_version,
        'firmware_manifest_runfile_sha256': nvidia_firmware_runfile_sha256,
        'kernel_module_version': nvidia_module_version,
        'kernel_uvm_module_version': nvidia_uvm_module_version,
    },
    'checks': {
        'allowed_modules': len(policy_modules),
        'module_dependency_files': len(module_files),
        'module_dependency_closure': len(module_closure),
        'device_aliases': sum(alias_counts.values()),
        'declared_firmware_files': len(declared_firmware),
        'upstream_unpublished_firmware_declarations': sorted(unpublished_firmware),
        'dynamic_firmware_declarations': sorted(dynamic_firmware),
        'integrity_manifested_firmware_files': len(firmware_manifest_entries),
        'graphics_files': len(graphics_entries),
        'graphics_drivers': graphics_manifest.get('drivers', []),
        'video_decode_backends': sorted(declared_video_drm),
        'video_decode_files': sorted(required_video_files),
        'boot_critical_builtins': len(compatibility.get('built_in_kernel_features', [])),
        'persistent_driver_root': compatibility['safety']['persistent_driver_root'],
    },
    'known_exclusions': compatibility.get('known_exclusions', []),
}
report_path.parent.mkdir(parents=True, exist_ok=True)
temporary = report_path.with_name(report_path.name + '.tmp')
temporary.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
os.replace(temporary, report_path)
print(json.dumps(report['checks'], sort_keys=True))
PY
'@

Write-Host 'Validating complete T1OS desktop hardware dependency closure...'
$normalizedValidateCommand = $validateCommand.Replace("`r", '') + "`n# end"
$output = @(
    $normalizedValidateCommand |
        wsl.exe -d Ubuntu -u root --exec bash -s -- $wslCompatibility $wslPolicy $wslKernelConfig $wslModules $wslFirmware $wslFirmwareManifest $wslGraphics $wslReport
)
$validateExitCode = $LASTEXITCODE
if ($validateExitCode -ne 0) {
    throw "Desktop hardware compatibility validation failed (exit code $validateExitCode)."
}
if (-not (Test-Path -LiteralPath $reportPath -PathType Leaf)) {
    throw 'Desktop hardware compatibility validation did not produce its report.'
}

$report = Get-Content -LiteralPath $reportPath -Raw | ConvertFrom-Json
if ($report.state -ne 'ready') {
    throw 'Desktop hardware compatibility report is not ready.'
}
Write-Host ($output | Select-Object -Last 1)
Write-Host "Desktop hardware compatibility validation passed: $reportPath"
