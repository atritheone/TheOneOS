[CmdletBinding()]
param([switch]$UsbDrive)

$ErrorActionPreference = 'Stop'
$commonScript = Join-Path $PSScriptRoot 'common.ps1'
$mountScript = Join-Path $PSScriptRoot 'mount.ps1'
$mountPoint = '/mnt/t1fs'

foreach ($requiredScript in @($commonScript, $mountScript)) {
    if (-not (Test-Path -LiteralPath $requiredScript -PathType Leaf)) {
        throw "Required script not found: $requiredScript"
    }
}

. $commonScript

if ($UsbDrive) {
    $usbTarget = Get-T1OSUsbDriveTarget
    $mountPoint = "/mnt/t1usb-command-centre-$([guid]::NewGuid().ToString('N'))"
    Write-Host "T1OS USB target: $($usbTarget.DriveSource) '$($usbTarget.Label)' on USB disk $($usbTarget.DiskNumber)."
} else {
    Write-Host 'Checking the mounted disk...'
    if (-not (Test-T1OSDiskMounted -MountPoint $mountPoint)) {
        throw "The disk must be mounted at $mountPoint before changing debug mode."
    }

    & pwsh -NoLogo -NoProfile -NonInteractive -File $mountScript
    if ($LASTEXITCODE -ne 0) {
        throw "The mounted disk could not be verified as storage.img (exit code $LASTEXITCODE)."
    }
}

$toggleCommand = @'
set -eu
mount_point=$1
drive_source=${2:-}
if [ -n "$drive_source" ]; then
    mkdir -m 700 "$mount_point"
    cleanup() { sync; umount "$mount_point" 2>/dev/null || true; rmdir "$mount_point" 2>/dev/null || true; }
    trap cleanup EXIT HUP INT TERM
    mount -t drvfs "$drive_source" "$mount_point" -o metadata,uid=0,gid=0,umask=022
else
    mountpoint -q "$mount_point"
fi

python3 - "$mount_point" <<'PY'
import os
import re
import stat
import sys

mount_point = sys.argv[1]
roots = [
    os.path.join(mount_point, "the one", "build"),
    os.path.join(mount_point, "boot"),
    os.path.join(mount_point, "software"),
]
pattern = re.compile(
    r"^([ \t]*(?:DEBUG[A-Z0-9_]*|_DEBUG_[A-Z0-9_]*)[ \t]*=[ \t]*)(True|False)([ \t]*(?:#.*)?)$",
    re.MULTILINE,
)

files = []
flags = []
for root in roots:
    if not os.path.isdir(root):
        continue
    for directory, subdirectories, filenames in os.walk(root, followlinks=False):
        subdirectories.sort()
        for filename in sorted(filenames):
            if not filename.endswith(".py"):
                continue
            path = os.path.join(directory, filename)
            if os.path.islink(path):
                continue
            with open(path, "r", encoding="utf-8") as handle:
                content = handle.read()
            matches = list(pattern.finditer(content))
            if matches:
                files.append((path, content))
                flags.extend(match.group(2) == "True" for match in matches)

if not flags:
    raise RuntimeError("No recognised T1OS debug flags were found on the disk.")

target_enabled = not any(flags)
target_text = "True" if target_enabled else "False"
changed = []

for path, content in files:
    updated, replacements = pattern.subn(
        lambda match: f"{match.group(1)}{target_text}{match.group(3)}",
        content,
    )
    if updated == content:
        continue

    file_stat = os.stat(path, follow_symlinks=False)
    temporary = f"{path}.t1os-debug-mode.tmp"
    try:
        with open(temporary, "w", encoding="utf-8", newline="") as handle:
            handle.write(updated)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, stat.S_IMODE(file_stat.st_mode))
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    changed.append(os.path.relpath(path, mount_point))

verified = []
for path, _ in files:
    with open(path, "r", encoding="utf-8") as handle:
        verified.extend(match.group(2) == "True" for match in pattern.finditer(handle.read()))

if not verified or any(value != target_enabled for value in verified):
    raise RuntimeError("Debug-mode verification found inconsistent flags after the update.")

for path in changed:
    print(f"updated {path}")
print(f"debug mode is now {'on' if target_enabled else 'off'} ({len(verified)} flags across {len(files)} files).")
PY

sync
'@

Write-Host 'Updating recognised T1OS debug flags...'
$wslArguments = if ($UsbDrive) {
    @('-u', 'root', '--exec', 'sh', '-c', $toggleCommand, 'sh', $mountPoint, $usbTarget.DriveSource)
} else {
    @('-u', 'root', '--exec', 'nsenter', '-t', '1', '-m', '--', 'sh', '-c', $toggleCommand, 'sh', $mountPoint)
}
& wsl.exe @wslArguments
if ($LASTEXITCODE -ne 0) {
    throw "Debug mode could not be changed (exit code $LASTEXITCODE)."
}

$targetName = if ($UsbDrive) { 'USB' } else { 'disk image' }
Write-Host "$targetName debug mode update completed successfully."
exit 0
