[CmdletBinding()]
param(
    [switch]$Clean
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Path $PSScriptRoot -Parent
$driverSourceRoot = Join-Path $projectRoot 'source\drivers'
$toolsTarget = Join-Path $driverSourceRoot 'tools'
$settingsTarget = Join-Path $driverSourceRoot 'settings'
$developmentRoot = Join-Path $projectRoot 'development\driver runtime'
$stageRoot = Join-Path $developmentRoot 'stage'
$cacheRoot = Join-Path ([System.IO.Path]::GetTempPath()) 't1os-driver-cache'
$archive = Join-Path $cacheRoot 'kmod-34.2.tar.xz'
$kmodVersion = '34.2'
$kmodSha256 = '5a5d5073070cc7e0c7a7a3c6ec2a0e1780850c8b47b3e3892226b93ffcb9cb54'
$kmodUrl = 'https://www.kernel.org/pub/linux/utils/kernel/kmod/kmod-34.2.tar.xz'
$mesonVersion = '1.7.2'

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
if ($Clean -and (Test-Path -LiteralPath $archive)) {
    Remove-Item -LiteralPath $archive -Force
}
if (-not (Test-Path -LiteralPath $archive -PathType Leaf)) {
    Write-Host "Downloading kmod $kmodVersion from kernel.org..."
    & curl.exe --fail --location --retry 5 --output $archive $kmodUrl
    if ($LASTEXITCODE -ne 0) {
        throw "kmod download failed (exit code $LASTEXITCODE)."
    }
}

$archiveHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $archive).Hash.ToLowerInvariant()
if ($archiveHash -ne $kmodSha256) {
    throw "kmod source hash mismatch. Expected $kmodSha256, received $archiveHash."
}

if (Test-Path -LiteralPath $stageRoot) {
    Remove-Item -LiteralPath $stageRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $stageRoot -Force | Out-Null
New-Item -ItemType Directory -Path $toolsTarget -Force | Out-Null
New-Item -ItemType Directory -Path $settingsTarget -Force | Out-Null

$wslArchive = ConvertTo-WslPath -WindowsPath $archive
$wslStage = ConvertTo-WslPath -WindowsPath $stageRoot

$buildCommand = @'
set -euo pipefail
archive=$1
stage=$2
kmod_version=$3
meson_version=$4
work=/var/tmp/t1os-driver-runtime
tools=/var/tmp/t1os-driver-build-tools
source="$work/kmod-$kmod_version"
build="$work/build"

for command_name in gcc ninja pkg-config python3 strip sha256sum tar xz file strings; do
    command -v "$command_name" >/dev/null 2>&1 || {
        echo "Required driver-runtime build command not found: $command_name" >&2
        exit 127
    }
done
test -f /usr/lib/x86_64-linux-gnu/libzstd.a || {
    echo 'Static libzstd development library not found. Install libzstd-dev.' >&2
    exit 127
}

case "$work" in
    /var/tmp/t1os-driver-runtime) rm -rf -- "$work" ;;
    *) echo "Refusing unexpected driver-runtime work path: $work" >&2; exit 1 ;;
esac
mkdir -p "$work" "$stage"
tar -xf "$archive" -C "$work"

# kmod normally consults Linux-distribution paths. T1OS exposes the same
# kernel interfaces exclusively through its driver namespace, so compile the
# loader against those paths and a single T1OS policy directory.
python3 - \
    "$source/libkmod/libkmod.c" \
    "$source/libkmod/libkmod-module.c" \
    "$source/libkmod/libkmod-config.c" <<'PY'
from pathlib import Path
import sys

context_path = Path(sys.argv[1])
module_path = Path(sys.argv[2])
config_path = Path(sys.argv[3])
context = context_path.read_text(encoding='utf-8')
old_config = '''static const char *const default_config_paths[] = {
\t// clang-format off
\tSYSCONFDIR "/modprobe.d",
\t"/run/modprobe.d",
\t"/usr/local/lib/modprobe.d",
\tDISTCONFDIR "/modprobe.d",
\t"/lib/modprobe.d",
\tNULL,
\t// clang-format on
};'''
new_config = '''static const char *const default_config_paths[] = {
\t"/the one/drivers/settings/modprobe.d",
\tNULL,
};'''
if context.count(old_config) != 1:
    raise SystemExit('unexpected kmod default configuration source')
context = context.replace(old_config, new_config)
context = context.replace('"/sys/module/compression"', '"/the one/drivers/state/module/compression"')
context_path.write_text(context, encoding='utf-8')

module = module_path.read_text(encoding='utf-8')
if '"/proc/modules"' not in module or '"/sys/module/' not in module:
    raise SystemExit('unexpected kmod module-state source')
module = module.replace('"/proc/modules"', '"/the one/drivers/processes/modules"')
module = module.replace('"/sys/module/', '"/the one/drivers/state/module/')
module_path.write_text(module, encoding='utf-8')

# Module parameters on the kernel command line are parsed by libkmod rather
# than passed to finit_module() by the kernel.  T1OS exposes the command line
# in its driver namespace, so leaving this one Linux path unchanged silently
# discards every <module>.<parameter>=... boot policy.
config = config_path.read_text(encoding='utf-8')
if config.count('"/proc/cmdline"') != 1:
    raise SystemExit('unexpected kmod command-line configuration source')
config = config.replace(
    '"/proc/cmdline"',
    '"/the one/drivers/processes/cmdline"',
)
config_path.write_text(config, encoding='utf-8')
PY

if [ ! -x "$tools/bin/meson" ] || [ "$("$tools/bin/meson" --version)" != "$meson_version" ]; then
    rm -rf -- "$tools"
    python3 -m venv "$tools"
    "$tools/bin/pip" install --disable-pip-version-check --no-cache-dir "meson==$meson_version"
fi

PKG_CONFIG_ALL_STATIC=1 "$tools/bin/meson" setup "$build" "$source" \
    --prefix='/the one/drivers' \
    --bindir=. \
    --libdir=. \
    -Dmoduledir='/the one/drivers/modules' \
    -Ddistconfdir='/the one/drivers/settings' \
    -Dzstd=enabled \
    -Dxz=disabled \
    -Dzlib=disabled \
    -Dopenssl=disabled \
    -Dmanpages=false \
    -Ddocs=false \
    -Dbuild-tests=false \
    -Dbashcompletiondir=no \
    -Dfishcompletiondir=no \
    -Dzshcompletiondir=no \
    -Dlogging=false \
    -Ddefault_library=static \
    -Dprefer_static=true \
    -Dc_link_args=-static

PKG_CONFIG_ALL_STATIC=1 "$tools/bin/meson" compile -C "$build" kmod:executable
cp -- "$build/kmod" "$stage/modprobe"
strip --strip-unneeded "$stage/modprobe"
chmod 0755 "$stage/modprobe"

file_output=$(file "$stage/modprobe")
case "$file_output" in *'statically linked'*) ;; *) echo "$file_output" >&2; exit 1;; esac
case "$file_output" in *'dynamically linked'*) echo "$file_output" >&2; exit 1;; esac
strings "$stage/modprobe" | grep -F '/the one/drivers/modules' >/dev/null
strings "$stage/modprobe" | grep -F '/the one/drivers/processes/modules' >/dev/null
strings "$stage/modprobe" | grep -F '/the one/drivers/processes/cmdline' >/dev/null
strings "$stage/modprobe" | grep -F '/the one/drivers/state/module/%s' >/dev/null
if strings "$stage/modprobe" | grep -Fx '/proc/modules' >/dev/null; then
    echo 'The T1OS module loader still uses /proc/modules.' >&2
    exit 1
fi
if strings "$stage/modprobe" | grep -Fx '/proc/cmdline' >/dev/null; then
    echo 'The T1OS module loader still uses /proc/cmdline.' >&2
    exit 1
fi
version_output=$("$stage/modprobe" --version)
case "$version_output" in *"kmod version $kmod_version"*) ;; *) echo "$version_output" >&2; exit 1;; esac
sha256sum "$stage/modprobe"
'@

& wsl.exe -d Ubuntu -u root --exec bash -c $buildCommand bash $wslArchive $wslStage $kmodVersion $mesonVersion
if ($LASTEXITCODE -ne 0) {
    throw "T1OS driver runtime build failed (exit code $LASTEXITCODE)."
}

$stageLoader = Join-Path $stageRoot 'modprobe'
if (-not (Test-Path -LiteralPath $stageLoader -PathType Leaf)) {
    throw "Driver runtime did not produce its module loader: $stageLoader"
}

Copy-Item -LiteralPath $stageLoader -Destination (Join-Path $toolsTarget 'modprobe') -Force
$loaderHash = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $toolsTarget 'modprobe')).Hash.ToLowerInvariant()
$metadata = [ordered]@{
    format = 1
    runtime = 'T1OS driver module loader'
    kmod_version = $kmodVersion
    kmod_source_sha256 = $kmodSha256
    module_directory = '/the one/drivers/modules'
    module_state = '/the one/drivers/state/module'
    loaded_module_list = '/the one/drivers/processes/modules'
    kernel_command_line = '/the one/drivers/processes/cmdline'
    static = $true
    zstd = $true
    sha256 = $loaderHash
}
$metadata | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $settingsTarget 'runtime.json') -Encoding utf8

Write-Host "T1OS driver runtime completed: $loaderHash"
Write-Host "Loader: $(Join-Path $toolsTarget 'modprobe')"
