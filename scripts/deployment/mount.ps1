[CmdletBinding()]
param(
    [switch]$ReadOnly
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$environmentRoot = Join-Path $projectRoot 'environment\software'
. (Join-Path $PSScriptRoot '..\common.ps1')
Set-Location -LiteralPath $environmentRoot

$imagePath = Join-Path $environmentRoot 'storage.img'
$mountPoint = '/mnt/t1fs'
$mountMode = if ($ReadOnly) { 'ro' } else { 'rw' }

if (-not (Test-Path -LiteralPath $imagePath -PathType Leaf)) {
    throw "Disk image not found: $imagePath"
}

Write-Host 'Locating the disk image in WSL...'
$wslImageOutput = & wsl.exe --exec wslpath -a $imagePath
$wslPathExitCode = $LASTEXITCODE
if ($wslPathExitCode -ne 0 -or -not $wslImageOutput) {
    throw 'Could not translate the storage.img path for WSL.'
}
$wslImagePath = ([string]($wslImageOutput | Select-Object -First 1)).Trim()
if ([string]::IsNullOrWhiteSpace($wslImagePath)) {
    throw 'WSL returned an empty path for storage.img.'
}

if (-not (Test-T1OSDiskMounted -MountPoint $mountPoint)) {
    Assert-T1OSFilesystemHealthy -ImagePath $imagePath -Operation "mounting it $mountMode"
}

Write-Host "Mounting storage.img at $mountPoint ($mountMode)..."
$mountCommand = @'
set -eu

image_path=$1
mount_point=$2
mount_mode=$3

case "$mount_mode" in
    ro|rw) ;;
    *) echo "Invalid storage image mount mode: $mount_mode" >&2; exit 1 ;;
esac

cleanup_unmounted_image_loops() {
    losetup -j "$image_path" 2>/dev/null |
        while IFS=: read -r loop_device _; do
            [ -n "$loop_device" ] || continue
            if ! nsenter -t 1 -m -- findmnt -rn -S "$loop_device" >/dev/null 2>&1; then
                losetup -d "$loop_device"
            fi
        done
}

verify_image_mount() {
    nsenter -t 1 -m -- mountpoint -q "$mount_point" || return 1
    source_device=$(nsenter -t 1 -m -- findmnt -rn -o SOURCE -T "$mount_point" | head -n 1)
    source_device=${source_device%%\[*}
    case "$source_device" in
        /dev/loop*) ;;
        *) return 1 ;;
    esac
    backing_file=$(losetup -n -O BACK-FILE "$source_device" 2>/dev/null | head -n 1)
    [ -n "$backing_file" ] || return 1
    [ "$(readlink -f "$backing_file")" = "$(readlink -f "$image_path")" ] || return 1
    mount_options=$(nsenter -t 1 -m -- findmnt -rn -o OPTIONS -T "$mount_point" | head -n 1)
    options=",${mount_options},"
    case "$mount_mode:$options" in
        ro:*,ro,*) ;;
        rw:*,rw,*) ;;
        *) return 1 ;;
    esac
}

mkdir -p "$mount_point"

if nsenter -t 1 -m -- mountpoint -q "$mount_point"; then
    if ! verify_image_mount; then
        echo "$mount_point is mounted from a different source." >&2
        exit 1
    fi
    echo "Disk is already mounted from storage.img."
    exit 0
fi

cleanup_unmounted_image_loops

if nsenter -t 1 -m -- find "$mount_point" -mindepth 1 -maxdepth 1 -print -quit | grep -q .; then
    echo "$mount_point contains stale files while it is unmounted. Clean the mountpoint before mounting storage.img." >&2
    exit 1
fi

if ! nsenter -t 1 -m -- mount -o "loop,$mount_mode" "$image_path" "$mount_point"; then
    cleanup_unmounted_image_loops
    exit 1
fi

if ! verify_image_mount; then
    nsenter -t 1 -m -- umount "$mount_point" 2>/dev/null || true
    cleanup_unmounted_image_loops
    echo "storage.img did not remain mounted at $mount_point." >&2
    exit 1
fi

echo "Mounted $(nsenter -t 1 -m -- findmnt -rn -o SOURCE -T "$mount_point") from $image_path."
'@

& wsl.exe -u root --exec sh -c $mountCommand sh $wslImagePath $mountPoint $mountMode
if ($LASTEXITCODE -ne 0) {
    throw "WSL could not mount storage.img (exit code $LASTEXITCODE)."
}

& wsl.exe -u root --exec nsenter -t 1 -m -- sh -c 'mountpoint -q "$2" && source=$(findmnt -rn -o SOURCE -T "$2" | head -n 1) && source=${source%%\[*} && case "$source" in /dev/loop*) backing=$(losetup -n -O BACK-FILE "$source" | head -n 1); [ "$(readlink -f "$backing")" = "$(readlink -f "$1")" ] || exit 1;; *) exit 1;; esac && options=",$(findmnt -rn -o OPTIONS -T "$2" | head -n 1)," && case "$3:$options" in ro:*,ro,*|rw:*,rw,*) exit 0;; *) exit 1;; esac' sh $wslImagePath $mountPoint $mountMode
if ($LASTEXITCODE -ne 0) {
    throw "The mount command completed, but $mountPoint is not backed by storage.img in $mountMode mode."
}

Write-Host "Disk mounted at $mountPoint ($mountMode)."
exit 0
