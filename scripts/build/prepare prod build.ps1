[CmdletBinding()]
param(
    [string]$Version
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$commonScript = Join-Path $PSScriptRoot '..\common.ps1'
$mountScript = Join-Path $PSScriptRoot '..\deployment\mount.ps1'
$unmountScript = Join-Path $PSScriptRoot '..\deployment\unmount.ps1'
$mountPoint = '/mnt/t1fs'
$sourceSettings = Join-Path $projectRoot 'source\settings'

foreach ($requiredScript in @($commonScript, $mountScript, $unmountScript)) {
    if (-not (Test-Path -LiteralPath $requiredScript -PathType Leaf)) {
        throw "Required script not found: $requiredScript"
    }
}

if (-not (Test-Path -LiteralPath $sourceSettings -PathType Container)) {
    throw "Source settings directory not found: $sourceSettings"
}

$sourceSettingsWslOutput = & wsl.exe -d Ubuntu --exec wslpath -a $sourceSettings
if ($LASTEXITCODE -ne 0 -or -not $sourceSettingsWslOutput) {
    throw "Could not translate the source settings path for WSL: $sourceSettings"
}
$sourceSettingsWsl = ([string](
    $sourceSettingsWslOutput | Select-Object -First 1
)).Trim()
if ([string]::IsNullOrWhiteSpace($sourceSettingsWsl)) {
    throw 'WSL returned an empty source settings path.'
}

. $commonScript
$Version = Get-T1OSCurrentVersion -ProjectRoot $projectRoot -Version $Version

$shouldUnmount = $false
$operationError = $null
$unmountError = $null

try {
    Write-Host 'Checking the disk mount status...'
    if (-not (Test-T1OSDiskMounted -MountPoint $mountPoint)) {
        Write-Host 'The disk is unmounted. Mounting it now...'
        & pwsh -NoLogo -NoProfile -NonInteractive -File $mountScript
        if ($LASTEXITCODE -ne 0) {
            throw "The disk could not be mounted (exit code $LASTEXITCODE)."
        }
    }
    else {
        Write-Host "The disk is already mounted at $mountPoint."
        & pwsh -NoLogo -NoProfile -NonInteractive -File $mountScript
        if ($LASTEXITCODE -ne 0) {
            throw "The existing mount could not be verified as storage.img (exit code $LASTEXITCODE)."
        }
    }

    $shouldUnmount = $true
    Write-Host "Preparing the disk as production version $Version..."

    $prepareCommand = @'
set -eu
mount_point=$1
version=$2
source_settings=$3
one_root="$mount_point/the one"
build_root="$one_root/build"
settings_root="$one_root/settings"
logs_root="$one_root/logs"
brick_settings="$settings_root/brick"
expanse_settings="$settings_root/expanse"
audio_settings="$settings_root/audio/audioserver.json"
chromium_settings="$settings_root/chromium"
chromium_profile="$chromium_settings/profile"
chromium_config="$chromium_settings/config"
chromium_font_cache="$chromium_settings/font-cache"
chromium_legacy_settings="$settings_root/browser"
rubbish_root="$mount_point/.rubbish"
ephemeral_root="$mount_point/.ephemeral"
software_root="$mount_point/software"
version_file="$settings_root/t1osversion.txt"
settings_stage="$one_root/.settings.production-new-$$"
settings_previous="$one_root/.settings.production-previous-$$"
settings_swap_active=0

cleanup_settings_swap() {
    status=$?
    trap - EXIT HUP INT TERM
    if [ "$settings_swap_active" = 1 ]; then
        rm -rf -- "$settings_root"
        mv -- "$settings_previous" "$settings_root"
        settings_swap_active=0
    fi
    [ ! -e "$settings_stage" ] || rm -rf -- "$settings_stage"
    exit "$status"
}
trap cleanup_settings_swap EXIT HUP INT TERM

tree_digest() {
    python3 - "$1" <<'PY'
import hashlib
import os
import stat
import sys

root = os.path.abspath(sys.argv[1])
if not os.path.isdir(root) or os.path.islink(root):
    raise SystemExit(f'protected tree is missing or unsafe: {root}')

digest = hashlib.sha256()

def add(value):
    payload = value if isinstance(value, bytes) else str(value).encode('utf-8')
    digest.update(len(payload).to_bytes(8, 'big'))
    digest.update(payload)

root_status = os.lstat(root)
add('.')
add('directory')
add(stat.S_IMODE(root_status.st_mode))
add(root_status.st_uid)
add(root_status.st_gid)

for directory, directories, filenames in os.walk(root, topdown=True, followlinks=False):
    directories.sort()
    filenames.sort()
    entries = list(directories) + list(filenames)
    for name in entries:
        path = os.path.join(directory, name)
        relative = os.path.relpath(path, root).replace(os.sep, '/')
        status = os.lstat(path)
        if stat.S_ISDIR(status.st_mode):
            kind = 'directory'
        elif stat.S_ISREG(status.st_mode):
            kind = 'file'
        elif stat.S_ISLNK(status.st_mode):
            kind = 'symlink'
        else:
            raise SystemExit(f'protected tree contains a special file: {relative}')
        add(relative)
        add(kind)
        add(stat.S_IMODE(status.st_mode))
        add(status.st_uid)
        add(status.st_gid)
        if kind == 'file':
            add(status.st_size)
            with open(path, 'rb') as handle:
                while True:
                    block = handle.read(1024 * 1024)
                    if not block:
                        break
                    digest.update(block)
        elif kind == 'symlink':
            add(os.readlink(path))

print(digest.hexdigest())
PY
}

mountpoint -q "$mount_point"
[ -d "$build_root" ] || { echo "Build directory not found: $build_root" >&2; exit 1; }
[ -d "$settings_root" ] || { echo "Settings directory not found: $settings_root" >&2; exit 1; }
[ -d "$source_settings" ] || { echo "Source settings directory not found: $source_settings" >&2; exit 1; }
[ -d "$software_root" ] || { echo "End-user test software directory not found: $software_root" >&2; exit 1; }
[ ! -e "$settings_stage" ] && [ ! -L "$settings_stage" ]
[ ! -e "$settings_previous" ] && [ ! -L "$settings_previous" ]
software_digest_before=$(tree_digest "$software_root")

echo 'Checking and disabling production debugging flags...'
python3 - "$build_root" <<'PY'
import os
import re
import sys

build_root = sys.argv[1]
pattern = re.compile(
    r'^([ \t]*(?:DEBUG[A-Z0-9_]*|_DEBUG_[A-Z0-9_]*)[ \t]*=[ \t]*)True([ \t]*(?:#.*)?)$',
    re.MULTILINE,
)
changed = []

for directory, subdirectories, filenames in os.walk(build_root):
    subdirectories.sort()
    for filename in sorted(filenames):
        if not filename.endswith('.py'):
            continue
        file_path = os.path.join(directory, filename)
        with open(file_path, 'r+', encoding='utf-8') as handle:
            original = handle.read()
            updated = pattern.sub(r'\1False\2', original)
            if updated == original:
                continue
            handle.seek(0)
            handle.write(updated)
            handle.truncate()
            handle.flush()
            os.fsync(handle.fileno())
        changed.append(os.path.relpath(file_path, build_root))

if changed:
    for file_path in changed:
        print(f'disabled debugging in {file_path}')
else:
    print('debugging was already disabled.')
PY

if grep -R -n -E --include='*.py' '^[[:space:]]*(DEBUG[A-Z0-9_]*|_DEBUG_[A-Z0-9_]*)[[:space:]]*=[[:space:]]*True([[:space:]]*(#.*)?)?$' "$build_root"; then
    echo 'One or more debugging flags remain enabled.' >&2
    exit 1
fi

echo 'Removing Python caches...'
find "$build_root" -type d -name '__pycache__' -prune -exec rm -rf -- {} +

echo 'Removing existing users and filesystem leftovers...'
rm -rf -- "$mount_point/master" "$one_root/master" "$mount_point/lost+found"

echo 'Clearing logs, Brick settings, rubbish, and ephemeral runtime state...'
for directory in "$logs_root" "$brick_settings" "$rubbish_root" "$ephemeral_root"; do
    mkdir -p "$directory"
    find "$directory" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
done

echo 'Clearing persistent placeholders for mounted driver runtime state...'
for runtime_name in control nodes processes state; do
    runtime_root="$one_root/drivers/$runtime_name"
    mkdir -p "$runtime_root"
    find "$runtime_root" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
done

echo 'Resetting Chromium settings for a fresh end-user install...'
rm -rf -- \
    "$chromium_settings" \
    "$chromium_legacy_settings"
mkdir -p "$chromium_settings"
for directory in "$chromium_profile" "$chromium_config" "$chromium_font_cache"; do
    mkdir -p "$directory"
    chown 1000:1000 "$directory"
    chmod 0700 "$directory"
done
chown 1000:1000 "$chromium_settings"
chmod 0700 "$chromium_settings"

echo 'Removing taskbar pins and saved taskbar ordering...'
mkdir -p "$expanse_settings"
printf '[]\n' > "$expanse_settings/taskbarpins.json"
printf '[]\n' > "$expanse_settings/taskbarorder.json"

echo 'Resetting the audio volume to 20%...'
python3 - "$audio_settings" <<'PY'
import json
import os
import sys

path = sys.argv[1]
directory = os.path.dirname(path)
os.makedirs(directory, exist_ok=True)

try:
    with open(path, 'r', encoding='utf-8') as handle:
        loaded = json.load(handle)
except (FileNotFoundError, json.JSONDecodeError):
    loaded = {}

config = {
    'autodevice': True,
    'mastergain': 0.2,
}

temporary = path + '.tmp'
try:
    with open(temporary, 'w', encoding='utf-8') as handle:
        json.dump(config, handle, indent=4, sort_keys=True)
        handle.write('\n')
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    directory_fd = os.open(directory, os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
finally:
    if os.path.exists(temporary):
        os.unlink(temporary)
PY

echo "Updating the on-disk version to $version..."
printf '%s\n' "$version" > "$version_file"

echo 'Replacing the complete settings namespace with production defaults...'
mkdir -p \
    "$settings_stage/audio" \
    "$settings_stage/brick" \
    "$settings_stage/chromium/profile" \
    "$settings_stage/chromium/config" \
    "$settings_stage/chromium/font-cache" \
    "$settings_stage/expanse" \
    "$settings_stage/media" \
    "$settings_stage/network" \
    "$settings_stage/virtualbox"

for required_source_setting in \
    "$source_settings/runtime paths.json" \
    "$source_settings/media/hardware diagnostics.json" \
    "$source_settings/media/video decode service.json" \
    "$source_settings/network/cacerts.pem" \
    "$source_settings/network/network.txt" \
    "$source_settings/virtualbox/version.txt"; do
    [ -f "$required_source_setting" ] && [ ! -L "$required_source_setting" ] || {
        echo "Required production source setting is missing or unsafe: $required_source_setting" >&2
        exit 1
    }
done

cp -- "$source_settings/runtime paths.json" "$settings_stage/runtime paths.json"
cp -- "$source_settings/media/hardware diagnostics.json" "$settings_stage/media/hardware diagnostics.json"
cp -- "$source_settings/media/video decode service.json" "$settings_stage/media/video decode service.json"
cp -- "$source_settings/network/cacerts.pem" "$settings_stage/network/cacerts.pem"
cp -- "$source_settings/network/network.txt" "$settings_stage/network/network.txt"
cp -- "$source_settings/virtualbox/version.txt" "$settings_stage/virtualbox/version.txt"
if [ -e "$source_settings/network/tnc.conf" ] || [ -L "$source_settings/network/tnc.conf" ]; then
    [ -f "$source_settings/network/tnc.conf" ] && [ ! -L "$source_settings/network/tnc.conf" ] || {
        echo 'The source network tnc.conf is unsafe.' >&2
        exit 1
    }
    cp -- "$source_settings/network/tnc.conf" "$settings_stage/network/tnc.conf"
fi

[ -d "$settings_root/terminfo" ] && [ ! -L "$settings_root/terminfo" ] || {
    echo 'The system terminfo settings tree is missing or unsafe.' >&2
    exit 1
}
cp -a -- "$settings_root/terminfo" "$settings_stage/terminfo"

printf '{\n    "autodevice": true,\n    "mastergain": 0.2\n}\n' \
    > "$settings_stage/audio/audioserver.json"
printf '[]\n' > "$settings_stage/expanse/taskbarpins.json"
printf '[]\n' > "$settings_stage/expanse/taskbarorder.json"
printf '%s\n' "$version" > "$settings_stage/t1osversion.txt"

chown -R 0:0 "$settings_stage"
find "$settings_stage" -type d -exec chmod 0755 {} +
find "$settings_stage" -type f -exec chmod 0644 {} +
for directory in \
    "$settings_stage/chromium" \
    "$settings_stage/chromium/profile" \
    "$settings_stage/chromium/config" \
    "$settings_stage/chromium/font-cache"; do
    chown 1000:1000 "$directory"
    chmod 0700 "$directory"
done

mv -- "$settings_root" "$settings_previous"
mv -- "$settings_stage" "$settings_root"
settings_swap_active=1

# Rebind paths after the atomic settings-tree replacement.
brick_settings="$settings_root/brick"
expanse_settings="$settings_root/expanse"
audio_settings="$settings_root/audio/audioserver.json"
chromium_settings="$settings_root/chromium"
chromium_profile="$chromium_settings/profile"
chromium_config="$chromium_settings/config"
chromium_font_cache="$chromium_settings/font-cache"
chromium_legacy_settings="$settings_root/browser"
version_file="$settings_root/t1osversion.txt"

echo 'Verifying the production cleanup...'
[ ! -e "$mount_point/master" ]
[ ! -e "$one_root/master" ]
[ ! -e "$mount_point/lost+found" ]
[ -z "$(find "$build_root" -type d -name '__pycache__' -print -quit)" ]
for directory in "$logs_root" "$brick_settings" "$rubbish_root" "$ephemeral_root"; do
    [ -z "$(find "$directory" -mindepth 1 -print -quit)" ]
done
for runtime_name in control nodes processes state; do
    runtime_root="$one_root/drivers/$runtime_name"
    [ -z "$(find "$runtime_root" -mindepth 1 -print -quit)" ]
done
for directory in "$chromium_profile" "$chromium_config" "$chromium_font_cache"; do
    [ -z "$(find "$directory" -mindepth 1 -print -quit)" ]
    [ "$(stat -c '%u:%g:%a' "$directory")" = '1000:1000:700' ]
done
[ "$(find "$chromium_settings" -mindepth 1 -maxdepth 1 -printf '%f\n' | sort | tr '\n' ' ')" = 'config font-cache profile ' ]
[ "$(stat -c '%u:%g:%a' "$chromium_settings")" = '1000:1000:700' ]
[ ! -e "$chromium_legacy_settings" ] && [ ! -L "$chromium_legacy_settings" ]
[ "$(tr -d '[:space:]' < "$expanse_settings/taskbarpins.json")" = '[]' ]
[ "$(tr -d '[:space:]' < "$expanse_settings/taskbarorder.json")" = '[]' ]
python3 - "$audio_settings" <<'PY'
import json
import sys

with open(sys.argv[1], 'r', encoding='utf-8') as handle:
    config = json.load(handle)
if config != {'autodevice': True, 'mastergain': 0.2}:
    raise SystemExit('audio settings were not reset to production defaults')
PY
[ "$(cat "$version_file")" = "$version" ]

python3 - "$settings_root" <<'PY'
import json
from pathlib import Path
import sys

root = Path(sys.argv[1])
expected_top_level = {
    'audio',
    'brick',
    'chromium',
    'expanse',
    'media',
    'network',
    'runtime paths.json',
    't1osversion.txt',
    'terminfo',
    'virtualbox',
}
actual_top_level = {entry.name for entry in root.iterdir()}
if actual_top_level != expected_top_level:
    raise SystemExit(
        'production settings inventory mismatch: ' +
        repr(sorted(actual_top_level))
    )

for path in root.rglob('*'):
    if path.is_symlink():
        raise SystemExit(f'production settings contain a symbolic link: {path}')

if any((root / 'brick').iterdir()):
    raise SystemExit('Brick settings were not emptied')
for name in ('profile', 'config', 'font-cache'):
    if any((root / 'chromium' / name).iterdir()):
        raise SystemExit(f'Chromium {name} settings were not emptied')
if {entry.name for entry in (root / 'chromium').iterdir()} != {
    'profile', 'config', 'font-cache'
}:
    raise SystemExit('Chromium settings contain an unexpected entry')
if {entry.name for entry in (root / 'expanse').iterdir()} != {
    'taskbarpins.json', 'taskbarorder.json'
}:
    raise SystemExit('Expanse settings contain an unexpected entry')
if {entry.name for entry in (root / 'audio').iterdir()} != {
    'audioserver.json'
}:
    raise SystemExit('Audio settings contain an unexpected entry')
PY

cmp -s -- "$source_settings/runtime paths.json" "$settings_root/runtime paths.json"
cmp -s -- "$source_settings/media/hardware diagnostics.json" "$settings_root/media/hardware diagnostics.json"
cmp -s -- "$source_settings/media/video decode service.json" "$settings_root/media/video decode service.json"
cmp -s -- "$source_settings/network/cacerts.pem" "$settings_root/network/cacerts.pem"
cmp -s -- "$source_settings/network/network.txt" "$settings_root/network/network.txt"
cmp -s -- "$source_settings/virtualbox/version.txt" "$settings_root/virtualbox/version.txt"
[ "$(tr -d '\r\n' < "$settings_root/network/network.txt")" = 'dhcp=true' ]
expected_network_entries='cacerts.pem network.txt '
if [ -f "$source_settings/network/tnc.conf" ]; then
    cmp -s -- "$source_settings/network/tnc.conf" "$settings_root/network/tnc.conf"
    expected_network_entries='cacerts.pem network.txt tnc.conf '
fi
[ "$(find "$settings_root/network" -mindepth 1 -maxdepth 1 -printf '%f\n' | sort | tr '\n' ' ')" = "$expected_network_entries" ]
[ "$(find "$settings_root/media" -mindepth 1 -maxdepth 1 -printf '%f\n' | sort | tr '\n' ' ')" = 'hardware diagnostics.json video decode service.json ' ]
[ "$(find "$settings_root/virtualbox" -mindepth 1 -maxdepth 1 -printf '%f\n' | sort | tr '\n' ' ')" = 'version.txt ' ]
[ -n "$(find "$settings_root/terminfo" -type f -print -quit)" ]

software_digest_after=$(tree_digest "$software_root")
[ "$software_digest_after" = "$software_digest_before" ] || {
    echo '/software changed during production preparation; rolling back settings and failing.' >&2
    exit 1
}
printf 'Preserved /software tree SHA-256: %s\n' "$software_digest_after"

rm -rf -- "$settings_previous"
settings_swap_active=0

sync
echo 'Production cleanup verification passed.'
'@

    & wsl.exe -u root --exec nsenter -t 1 -m -- sh -c $prepareCommand sh $mountPoint $Version $sourceSettingsWsl
    if ($LASTEXITCODE -ne 0) {
        throw "Production preparation failed (exit code $LASTEXITCODE)."
    }
}
catch {
    $operationError = $_
}
finally {
    if ($shouldUnmount) {
        Write-Host 'Unmounting the prepared production disk...'
        & pwsh -NoLogo -NoProfile -NonInteractive -File $unmountScript
        if ($LASTEXITCODE -ne 0) {
            $unmountError = "The disk could not be unmounted (exit code $LASTEXITCODE)."
        }
    }
}

if ($operationError -and $unmountError) {
    throw "$($operationError.Exception.Message) $unmountError"
}
if ($operationError) {
    throw $operationError
}
if ($unmountError) {
    throw $unmountError
}

Write-Host "Production disk preparation completed for version $Version."
exit 0
