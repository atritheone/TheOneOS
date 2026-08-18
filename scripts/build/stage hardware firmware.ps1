[CmdletBinding()]
param(
    [switch]$Clean
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$cacheRoot = Join-Path ([System.IO.Path]::GetTempPath()) 't1os-firmware-cache'
$archive = Join-Path $cacheRoot 'linux-firmware-20260622.tar.xz'
$regdbArchive = Join-Path $cacheRoot 'wireless-regdb-2026.05.30.tar.xz'
$intelMicrocodeArchive = Join-Path $cacheRoot 'intel-microcode-20260512.tar.gz'
$sofArchive = Join-Path $cacheRoot 'sof-bin-2025.12.2.tar.gz'
$stageRoot = Join-Path $projectRoot 'environment\hardware\firmware'
$archiveTarget = Join-Path $projectRoot 'environment\hardware\firmware.tar.zst'
$manifestTarget = Join-Path $projectRoot 'environment\hardware\t1os-firmware-manifest.json'
$temporaryStage = Join-Path $projectRoot 'development\hardware firmware stage'
$temporaryArchive = Join-Path $temporaryStage 'firmware.tar.zst'
$temporaryManifest = Join-Path $temporaryStage 't1os-firmware-manifest.json'
$firmwareVersion = '20260622'
$firmwareSha256 = '2b9d8a358e76eb766588609135e53fa548b902c551daae33ee32f26f25e60dbb'
$firmwareUrl = "https://cdn.kernel.org/pub/linux/kernel/firmware/linux-firmware-$firmwareVersion.tar.xz"
$regdbVersion = '2026.05.30'
$regdbSha256 = '8a27bfc081bafed8c24dd70fab0d96f098e5a0bfcd08d3da672595f225ab8993'
$regdbUrl = "https://www.kernel.org/pub/software/network/wireless-regdb/wireless-regdb-$regdbVersion.tar.xz"
$intelMicrocodeVersion = 'microcode-20260512'
$intelMicrocodeCommit = '98f8d817ca3d560c48ae988bd805d1b53b48a631'
$intelMicrocodeSha256 = 'c72a142e69d5961ca7d15bc87d51b5ebb930a546bf3e8ac23755e64a44d4e746'
$intelMicrocodeUrl = "https://github.com/intel/Intel-Linux-Processor-Microcode-Data-Files/archive/$intelMicrocodeCommit.tar.gz"
$sofVersion = '2025.12.2'
$sofSha256 = '533f63e3a6d94c09ce05a782657b675fa683ff20787c0979226cf563ec79f517'
$sofUrl = "https://github.com/thesofproject/sof-bin/releases/download/v$sofVersion/sof-bin-$sofVersion.tar.gz"
$nvidiaVersion = '610.43.03'
$nvidiaSha256 = '45e2d4c134a23c35e50f253a4aa63e7e5e8d17e3d185d4a07c8a58e9612ed392'
$nvidiaCacheRoot = Join-Path ([System.IO.Path]::GetTempPath()) 't1os-kernel-cache'
$nvidiaRunfile = Join-Path $nvidiaCacheRoot "NVIDIA-Linux-x86_64-$nvidiaVersion.run"
$nvidiaUrl = "https://us.download.nvidia.com/XFree86/Linux-x86_64/$nvidiaVersion/NVIDIA-Linux-x86_64-$nvidiaVersion.run"

function ConvertTo-WslPath {
    param([Parameter(Mandatory)][string]$WindowsPath)

    $output = & wsl.exe -d Ubuntu --exec wslpath -a $WindowsPath
    if ($LASTEXITCODE -ne 0 -or -not $output) {
        throw "Could not translate path for WSL: $WindowsPath"
    }
    return ([string]($output | Select-Object -First 1)).Trim()
}

foreach ($command in @('wsl.exe', 'curl.exe')) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        throw "Required command not found: $command"
    }
}

New-Item -ItemType Directory -Path $cacheRoot -Force | Out-Null
New-Item -ItemType Directory -Path $nvidiaCacheRoot -Force | Out-Null

if ($Clean -and (Test-Path -LiteralPath $archive)) {
    Remove-Item -LiteralPath $archive -Force
}
if ($Clean -and (Test-Path -LiteralPath $regdbArchive)) {
    Remove-Item -LiteralPath $regdbArchive -Force
}
if ($Clean -and (Test-Path -LiteralPath $intelMicrocodeArchive)) {
    Remove-Item -LiteralPath $intelMicrocodeArchive -Force
}
if ($Clean -and (Test-Path -LiteralPath $sofArchive)) {
    Remove-Item -LiteralPath $sofArchive -Force
}
if ($Clean -and (Test-Path -LiteralPath $nvidiaRunfile)) {
    Remove-Item -LiteralPath $nvidiaRunfile -Force
}

if (-not (Test-Path -LiteralPath $archive -PathType Leaf)) {
    Write-Host "Downloading linux-firmware $firmwareVersion from kernel.org..."
    & curl.exe --fail --location --retry 5 --continue-at - --output $archive $firmwareUrl
    if ($LASTEXITCODE -ne 0) {
        throw "linux-firmware download failed (exit code $LASTEXITCODE)."
    }
}

if (-not (Test-Path -LiteralPath $regdbArchive -PathType Leaf)) {
    Write-Host "Downloading wireless-regdb $regdbVersion from kernel.org..."
    & curl.exe --fail --location --retry 5 --continue-at - --output $regdbArchive $regdbUrl
    if ($LASTEXITCODE -ne 0) {
        throw "wireless-regdb download failed (exit code $LASTEXITCODE)."
    }
}

if (-not (Test-Path -LiteralPath $intelMicrocodeArchive -PathType Leaf)) {
    Write-Host "Downloading Intel processor microcode $intelMicrocodeVersion from Intel..."
    & curl.exe --fail --location --retry 5 --continue-at - --output $intelMicrocodeArchive $intelMicrocodeUrl
    if ($LASTEXITCODE -ne 0) {
        throw "Intel processor microcode download failed (exit code $LASTEXITCODE)."
    }
}

if (-not (Test-Path -LiteralPath $sofArchive -PathType Leaf)) {
    Write-Host "Downloading Sound Open Firmware $sofVersion from the SOF project..."
    & curl.exe --fail --location --retry 5 --continue-at - --output $sofArchive $sofUrl
    if ($LASTEXITCODE -ne 0) {
        throw "Sound Open Firmware download failed (exit code $LASTEXITCODE)."
    }
}

if (-not (Test-Path -LiteralPath $nvidiaRunfile -PathType Leaf)) {
    Write-Host "Downloading NVIDIA open GPU firmware $nvidiaVersion..."
    & curl.exe --fail --location --retry 5 --continue-at - --output $nvidiaRunfile $nvidiaUrl
    if ($LASTEXITCODE -ne 0) {
        throw "NVIDIA driver download failed (exit code $LASTEXITCODE)."
    }
}

$actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $archive).Hash.ToLowerInvariant()
if ($actualHash -ne $firmwareSha256) {
    throw "linux-firmware hash mismatch. Expected $firmwareSha256, received $actualHash."
}
$actualRegdbHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $regdbArchive).Hash.ToLowerInvariant()
if ($actualRegdbHash -ne $regdbSha256) {
    throw "wireless-regdb hash mismatch. Expected $regdbSha256, received $actualRegdbHash."
}
$actualIntelMicrocodeHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $intelMicrocodeArchive).Hash.ToLowerInvariant()
if ($actualIntelMicrocodeHash -ne $intelMicrocodeSha256) {
    throw "Intel processor microcode hash mismatch. Expected $intelMicrocodeSha256, received $actualIntelMicrocodeHash."
}
$actualSofHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $sofArchive).Hash.ToLowerInvariant()
if ($actualSofHash -ne $sofSha256) {
    throw "Sound Open Firmware hash mismatch. Expected $sofSha256, received $actualSofHash."
}
$actualNvidiaHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $nvidiaRunfile).Hash.ToLowerInvariant()
if ($actualNvidiaHash -ne $nvidiaSha256) {
    throw "NVIDIA driver hash mismatch. Expected $nvidiaSha256, received $actualNvidiaHash."
}

if (Test-Path -LiteralPath $temporaryStage) {
    Remove-Item -LiteralPath $temporaryStage -Recurse -Force
}
New-Item -ItemType Directory -Path $temporaryStage -Force | Out-Null

$wslArchive = ConvertTo-WslPath -WindowsPath $archive
$wslRegdbArchive = ConvertTo-WslPath -WindowsPath $regdbArchive
$wslIntelMicrocodeArchive = ConvertTo-WslPath -WindowsPath $intelMicrocodeArchive
$wslSofArchive = ConvertTo-WslPath -WindowsPath $sofArchive
$wslNvidiaRunfile = ConvertTo-WslPath -WindowsPath $nvidiaRunfile
$wslTemporaryArchive = ConvertTo-WslPath -WindowsPath $temporaryArchive

$stageCommand = @'
set -euo pipefail

archive=$1
stage_archive=$2
version=$3
archive_sha=$4
regdb_archive=$5
regdb_version=$6
regdb_sha=$7
intel_archive=$8
intel_version=$9
intel_commit=${10}
intel_sha=${11}
sof_archive=${12}
sof_version=${13}
sof_sha=${14}
nvidia_runfile=${15}
nvidia_version=${16}
nvidia_sha=${17}
source_root="/var/tmp/t1os-linux-firmware-$version"
regdb_source_root="/var/tmp/t1os-wireless-regdb-$regdb_version"
intel_source_root="/var/tmp/t1os-intel-microcode-$intel_version"
sof_source_root="/var/tmp/t1os-sof-bin-$sof_version"
nvidia_source_root="/var/tmp/t1os-nvidia-firmware-$nvidia_version"
installed_root="/var/tmp/t1os-linux-firmware-installed-$version"
stage="/var/tmp/t1os-linux-firmware-stage-$version"

case "$source_root" in
    /var/tmp/t1os-linux-firmware-*) rm -rf -- "$source_root" ;;
    *) echo "Refusing to replace unexpected firmware work path: $source_root" >&2; exit 1 ;;
esac
case "$regdb_source_root" in
    /var/tmp/t1os-wireless-regdb-*) rm -rf -- "$regdb_source_root" ;;
    *) echo "Refusing to replace unexpected regulatory database work path: $regdb_source_root" >&2; exit 1 ;;
esac
case "$intel_source_root" in
    /var/tmp/t1os-intel-microcode-*) rm -rf -- "$intel_source_root" ;;
    *) echo "Refusing to replace unexpected Intel microcode work path: $intel_source_root" >&2; exit 1 ;;
esac
case "$sof_source_root" in
    /var/tmp/t1os-sof-bin-*) rm -rf -- "$sof_source_root" ;;
    *) echo "Refusing to replace unexpected Sound Open Firmware work path: $sof_source_root" >&2; exit 1 ;;
esac
case "$nvidia_source_root" in
    /var/tmp/t1os-nvidia-firmware-*) rm -rf -- "$nvidia_source_root" ;;
    *) echo "Refusing to replace unexpected NVIDIA firmware work path: $nvidia_source_root" >&2; exit 1 ;;
esac
case "$installed_root" in
    /var/tmp/t1os-linux-firmware-installed-*) rm -rf -- "$installed_root" ;;
    *) echo "Refusing to replace unexpected firmware install path: $installed_root" >&2; exit 1 ;;
esac
case "$stage" in
    /var/tmp/t1os-linux-firmware-stage-*) rm -rf -- "$stage" ;;
    *) echo "Refusing to replace unexpected firmware stage path: $stage" >&2; exit 1 ;;
esac

mkdir -p "$source_root" "$regdb_source_root" "$intel_source_root" "$sof_source_root" "$installed_root" "$stage"
printf '%s  %s\n' "$nvidia_sha" "$nvidia_runfile" | sha256sum -c -
tar -xf "$archive" -C "$source_root"
tar -xf "$regdb_archive" -C "$regdb_source_root"
tar -xzf "$intel_archive" -C "$intel_source_root"
tar -xzf "$sof_archive" -C "$sof_source_root"
sh "$nvidia_runfile" --extract-only --target "$nvidia_source_root"
firmware_root="$source_root/linux-firmware-$version"
regdb_root="$regdb_source_root/wireless-regdb-$regdb_version"
intel_root="$intel_source_root/Intel-Linux-Processor-Microcode-Data-Files-$intel_commit"
sof_root="$sof_source_root/sof-bin-$sof_version"
test -f "$firmware_root/WHENCE"
test -s "$regdb_root/regulatory.db"
test -d "$intel_root/intel-ucode"
test -s "$intel_root/license"
test -d "$sof_root/sof"
test -d "$sof_root/sof-tplg"
test -d "$sof_root/sof-ipc4"
test -d "$sof_root/sof-ipc4-tplg"
test -s "$nvidia_source_root/LICENSE"
test -s "$nvidia_source_root/firmware/gsp_ga10x.bin"
test -s "$nvidia_source_root/firmware/gsp_tu10x.bin"
test -s "$nvidia_source_root/firmware/ucodes_ga10x.bin"
test -s "$nvidia_source_root/firmware/ucodes_tu10x.bin"

# Install every firmware entry declared by the pinned WHENCE catalogue.  The
# installer creates the release's Link entries. The exact case-sensitive tree
# remains on the WSL filesystem and is archived before crossing into Windows,
# where case-distinct Radeon firmware names cannot coexist as loose files.
# This is deliberately a complete desktop payload: selecting a new supported
# module must not silently leave its firmware behind.
(cd "$firmware_root" && ./copy-firmware.sh "$installed_root")
cp -a -- "$installed_root"/. "$stage"/

cp -- "$regdb_root/regulatory.db" "$stage/regulatory.db"
if [ -s "$regdb_root/regulatory.db.p7s" ]; then
    cp -- "$regdb_root/regulatory.db.p7s" "$stage/regulatory.db.p7s"
fi

cp -- "$firmware_root/WHENCE" "$stage/WHENCE"
find "$firmware_root" -maxdepth 1 -type f \( -name 'LICENCE*' -o -name 'LICENSE*' \) -exec cp -a -- {} "$stage/" \;
mkdir -p "$stage/intel-ucode"
cp -a -- "$intel_root/intel-ucode"/. "$stage/intel-ucode"/
cp -- "$intel_root/license" "$stage/LICENCE.intel-microcode"
cp -- "$intel_root/README.md" "$stage/README.intel-microcode.md"
cp -- "$intel_root/releasenote.md" "$stage/RELEASENOTE.intel-microcode.md"
mkdir -p "$stage/intel"
cp -a -- "$sof_root"/sof* "$stage/intel"/
cp -- "$sof_root/LICENCE.Intel" "$stage/LICENCE.sound-open-firmware.Intel"
cp -- "$sof_root/LICENCE.NXP" "$stage/LICENCE.sound-open-firmware.NXP"
cp -- "$sof_root/Notice.NXP" "$stage/NOTICE.sound-open-firmware.NXP"
cp -- "$sof_root/README.md" "$stage/README.sound-open-firmware.md"
cp -- "$sof_root/manifest.txt" "$stage/MANIFEST.sound-open-firmware.txt"
mkdir -p "$stage/nvidia/$nvidia_version"
cp -- "$nvidia_source_root/firmware/gsp_ga10x.bin" \
    "$stage/nvidia/$nvidia_version/gsp_ga10x.bin"
cp -- "$nvidia_source_root/firmware/gsp_tu10x.bin" \
    "$stage/nvidia/$nvidia_version/gsp_tu10x.bin"
cp -- "$nvidia_source_root/firmware/ucodes_ga10x.bin" \
    "$stage/nvidia/$nvidia_version/ucodes_ga10x.bin"
cp -- "$nvidia_source_root/firmware/ucodes_tu10x.bin" \
    "$stage/nvidia/$nvidia_version/ucodes_tu10x.bin"
cp -- "$nvidia_source_root/LICENSE" \
    "$stage/LICENCE.nvidia-open-gpu-driver-$nvidia_version"

# linux-firmware expresses WHENCE aliases as symbolic links. T1OS does not
# permit symbolic links, so replace every in-tree alias with a regular copy of
# its resolved payload before creating the integrity manifest or archive.
python3 - "$stage" <<'PY'
from pathlib import Path
import os
import shutil
import stat
import sys

root = Path(sys.argv[1]).resolve()
directory_links = []
file_links = []
for current, directories, names in os.walk(root, followlinks=False):
    current_path = Path(current)
    for name in directories:
        path = current_path / name
        if path.is_symlink():
            directory_links.append(path)
    for name in names:
        path = current_path / name
        if path.is_symlink():
            file_links.append(path)

for path in sorted((*directory_links, *file_links)):
    target = path.resolve(strict=True)
    try:
        target.relative_to(root)
    except ValueError as error:
        raise SystemExit(f'firmware link escapes its root: {path}') from error

for path in sorted(directory_links, key=lambda item: len(item.parts)):
    target = path.resolve(strict=True)
    if not target.is_dir():
        raise SystemExit(f'firmware directory alias has an invalid target: {path}')
    path.unlink()
    shutil.copytree(target, path, symlinks=False, copy_function=shutil.copy2)

for path in sorted(file_links):
    target = path.resolve(strict=True)
    if not target.is_file():
        raise SystemExit(f'firmware file alias has an invalid target: {path}')
    payload = target.read_bytes()
    mode = stat.S_IMODE(target.stat().st_mode)
    path.unlink()
    path.write_bytes(payload)
    path.chmod(mode)

remaining = [
    str(Path(current) / name)
    for current, directories, names in os.walk(root, followlinks=False)
    for name in (*directories, *names)
    if (Path(current) / name).is_symlink()
]
if remaining:
    raise SystemExit('firmware staging retained symbolic links: ' + ', '.join(remaining[:20]))
print(
    f'Materialized {len(file_links)} firmware file aliases and '
    f'{len(directory_links)} directory aliases.'
)
PY

test -n "$(find "$stage/amd-ucode" -type f -name '*.bin' -print -quit)"
test -n "$(find "$stage/intel-ucode" -type f -print -quit)"
test -n "$(find "$stage/amdgpu" -type f -print -quit)"
test -n "$(find "$stage/radeon" -type f -print -quit)"
test -n "$(find "$stage/i915" -type f -print -quit)"
test -n "$(find "$stage/nvidia" -type f -print -quit)"
test -n "$(find "$stage/mediatek" -type f -print -quit)"
test -n "$(find "$stage/rtl_nic" -type f -print -quit)"
test -s "$stage/iwlwifi-cc-a0-77.ucode"
test -s "$stage/regulatory.db"
test -s "$stage/nvidia/ad104/gsp/booter_load-535.113.01.bin"
test -s "$stage/nvidia/ad104/gsp/booter_unload-535.113.01.bin"
test -s "$stage/nvidia/ad104/gsp/bootloader-535.113.01.bin"
test -s "$stage/nvidia/ad104/gsp/gsp-535.113.01.bin"
test -s "$stage/nvidia/ad104/gsp/gsp-570.144.bin"
test -s "$stage/nvidia/$nvidia_version/gsp_ga10x.bin"
test -s "$stage/nvidia/$nvidia_version/gsp_tu10x.bin"
test -s "$stage/nvidia/$nvidia_version/ucodes_ga10x.bin"
test -s "$stage/nvidia/$nvidia_version/ucodes_tu10x.bin"

python3 - "$stage" "$version" "$archive_sha" "$regdb_version" "$regdb_sha" "$intel_version" "$intel_commit" "$intel_sha" "$sof_version" "$sof_sha" "$nvidia_version" "$nvidia_sha" <<'PY'
from pathlib import Path
import hashlib
import json
import os
import sys

root = Path(sys.argv[1])
files = []
for current, directories, names in os.walk(root, followlinks=True):
    directories.sort()
    names.sort()
    for name in names:
        path = Path(current) / name
        if not path.is_file() or path.name == 't1os-firmware-manifest.json':
            continue
        resolved = path.resolve()
        try:
            resolved.relative_to(root.resolve())
        except ValueError as error:
            raise SystemExit(f'firmware link escapes its root: {path}') from error
        data = path.read_bytes()
        entry = {
            'path': path.relative_to(root).as_posix(),
            'size': len(data),
            'sha256': hashlib.sha256(data).hexdigest(),
        }
        files.append(entry)

manifest = {
    'format': 2,
    'source': 'kernel.org linux-firmware',
    'version': sys.argv[2],
    'archive_sha256': sys.argv[3],
    'wireless_regdb_version': sys.argv[4],
    'wireless_regdb_archive_sha256': sys.argv[5],
    'intel_microcode_version': sys.argv[6],
    'intel_microcode_commit': sys.argv[7],
    'intel_microcode_archive_sha256': sys.argv[8],
    'sound_open_firmware_version': sys.argv[9],
    'sound_open_firmware_archive_sha256': sys.argv[10],
    'nvidia_open_driver_version': sys.argv[11],
    'nvidia_open_driver_archive_sha256': sys.argv[12],
    'coverage': 'complete pinned WHENCE installation with materialized Link entries plus matching NVIDIA open-driver firmware',
    'target_profile': 'common x86_64 Windows desktop hardware, approximately 2017-2026',
    'files': files,
}
(root / 't1os-firmware-manifest.json').write_text(
    json.dumps(manifest, indent=2) + '\n',
    encoding='utf-8',
)
PY

rm -f -- "$stage_archive"
(cd "$stage" && tar --sort=name --mtime='UTC 2026-07-24' --owner=0 --group=0 --numeric-owner -cf - . | zstd -19 -T0 -o "$stage_archive")
cp -- "$stage/t1os-firmware-manifest.json" "$stage_archive.manifest"
rm -rf -- "$source_root" "$regdb_source_root" "$intel_source_root" "$sof_source_root" "$nvidia_source_root" "$installed_root" "$stage"
'@

$stageScript = Join-Path $temporaryStage 'stage-hardware-firmware.sh'
[System.IO.File]::WriteAllText(
    $stageScript,
    $stageCommand,
    [System.Text.UTF8Encoding]::new($false)
)
$wslStageScript = ConvertTo-WslPath -WindowsPath $stageScript
$stageExitCode = 1
try {
    & wsl.exe -d Ubuntu -u root --exec bash $wslStageScript $wslArchive $wslTemporaryArchive $firmwareVersion $firmwareSha256 $wslRegdbArchive $regdbVersion $regdbSha256 $wslIntelMicrocodeArchive $intelMicrocodeVersion $intelMicrocodeCommit $intelMicrocodeSha256 $wslSofArchive $sofVersion $sofSha256 $wslNvidiaRunfile $nvidiaVersion $nvidiaSha256
    $stageExitCode = $LASTEXITCODE
}
finally {
    if (Test-Path -LiteralPath $stageScript) {
        Remove-Item -LiteralPath $stageScript -Force
    }
}
if ($stageExitCode -ne 0) {
    throw "Firmware staging failed (exit code $stageExitCode)."
}

if (-not (Test-Path -LiteralPath $temporaryArchive -PathType Leaf)) {
    throw 'Firmware staging did not produce an archive.'
}
if (-not (Test-Path -LiteralPath "$temporaryArchive.manifest" -PathType Leaf)) {
    throw 'Firmware staging did not produce a manifest.'
}
Move-Item -LiteralPath "$temporaryArchive.manifest" -Destination $temporaryManifest
if (Test-Path -LiteralPath $archiveTarget) {
    Remove-Item -LiteralPath $archiveTarget -Force
}
Move-Item -LiteralPath $temporaryArchive -Destination $archiveTarget
if (Test-Path -LiteralPath $manifestTarget) {
    Remove-Item -LiteralPath $manifestTarget -Force
}
Move-Item -LiteralPath $temporaryManifest -Destination $manifestTarget
if (Test-Path -LiteralPath $stageRoot) {
    Remove-Item -LiteralPath $stageRoot -Recurse -Force
}

$manifest = Get-Content -LiteralPath $manifestTarget -Raw | ConvertFrom-Json
$bytes = ($manifest.files | Measure-Object -Property size -Sum).Sum
Write-Host "Hardware firmware staged: $($manifest.files.Count) manifest entries, $bytes payload bytes"
Write-Host "Archive: $archiveTarget"
Write-Host "Manifest: $manifestTarget"
