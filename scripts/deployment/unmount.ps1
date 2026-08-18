[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$environmentRoot = Join-Path $projectRoot 'environment\software'
$imagePath = Join-Path $environmentRoot 'storage.img'
$mountPoint = '/mnt/t1fs'

if (-not (Test-Path -LiteralPath $imagePath -PathType Leaf)) {
    throw "Disk image not found: $imagePath"
}

$wslImageOutput = & wsl.exe --exec wslpath -a $imagePath
$wslPathExitCode = $LASTEXITCODE
if ($wslPathExitCode -ne 0 -or -not $wslImageOutput) {
    throw 'Could not translate the storage.img path for WSL.'
}
$wslImagePath = ([string]($wslImageOutput | Select-Object -First 1)).Trim()

Write-Host "Checking $mountPoint..."
$unmountCommand = @'
set -eu

image_path=$1
mount_point=$2

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
    [ "$(readlink -f "$backing_file")" = "$(readlink -f "$image_path")" ]
}

if nsenter -t 1 -m -- mountpoint -q "$mount_point"; then
    if ! verify_image_mount; then
        echo "$mount_point is mounted from a different source; refusing to unmount it." >&2
        exit 1
    fi
    echo "Unmounting the disk..."
    sync
    attempt=1
    while nsenter -t 1 -m -- mountpoint -q "$mount_point"; do
        if nsenter -t 1 -m -- umount -R "$mount_point"; then
            break
        fi
        if [ "$attempt" -ge 5 ]; then
            echo "$mount_point remained busy after $attempt unmount attempts." >&2
            exit 1
        fi
        attempt=$((attempt + 1))
        sleep 0.2
    done
else
    echo "Disk is already unmounted."
fi

losetup -j "$image_path" 2>/dev/null |
    while IFS=: read -r loop_device _; do
        [ -n "$loop_device" ] || continue
        if ! nsenter -t 1 -m -- findmnt -rn -S "$loop_device" >/dev/null 2>&1; then
            losetup -d "$loop_device"
        fi
    done

if nsenter -t 1 -m -- mountpoint -q "$mount_point"; then
    echo "$mount_point is still mounted." >&2
    exit 1
fi
'@

& wsl.exe -u root --exec sh -c $unmountCommand sh $wslImagePath $mountPoint
if ($LASTEXITCODE -ne 0) {
    throw "WSL could not unmount the disk (exit code $LASTEXITCODE)."
}

Write-Host 'Disk unmounted safely.'
exit 0
