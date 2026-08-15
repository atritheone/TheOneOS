[CmdletBinding()]
param(
    [string]$ImagePath
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Path $PSScriptRoot -Parent
$environmentRoot = Join-Path $projectRoot 'environment'
. (Join-Path $PSScriptRoot 'common.ps1')

if ([string]::IsNullOrWhiteSpace($ImagePath)) {
    $ImagePath = Join-Path $environmentRoot 'storage.img'
}

if (-not (Test-Path -LiteralPath $ImagePath -PathType Leaf)) {
    throw "Disk image not found: $ImagePath"
}

Write-Host 'Checking the disk mount status...'
if (Test-T1OSDiskMounted) {
    throw 'The disk is mounted. Unmount it before cleaning.'
}

$wslImageOutput = & wsl.exe --exec wslpath -a $ImagePath
if ($LASTEXITCODE -ne 0 -or -not $wslImageOutput) {
    throw "Could not translate the disk image path for WSL: $ImagePath"
}
$wslImagePath = ([string]($wslImageOutput | Select-Object -First 1)).Trim()
if ([string]::IsNullOrWhiteSpace($wslImagePath)) {
    throw 'WSL returned an empty disk image path.'
}

$repairCommand = @'
set -eu
image=$1
work_dir=$(mktemp -d /tmp/t1os-clean-disk.XXXXXX)
config="$work_dir/e2fsck.conf"
undo_file="$work_dir/e2fsck.undo"
transcript="$work_dir/e2fsck.log"

cleanup() {
    rm -rf -- "$work_dir"
}
trap cleanup EXIT HUP INT TERM

cat > "$config" <<'EOF'
[problems]
0x030004 = {
    force_no = true
    no_ok = true
    no_nomsg = false
}
EOF

has_lost_found() {
    /usr/sbin/debugfs -R 'stat /lost+found' "$image" 2>/dev/null | grep -q '^Inode:'
}

had_lost_found=0
if has_lost_found; then
    had_lost_found=1
fi

echo 'Repairing the ext4 filesystem...'
set +e
LC_ALL=C E2FSCK_CONFIG="$config" /usr/sbin/e2fsck -f -y -z "$undo_file" "$image" >"$transcript" 2>&1
repair_exit=$?
set -e

if [ "$had_lost_found" -eq 0 ] && has_lost_found; then
    cat "$transcript" >&2
    echo 'The repair attempted to create /lost+found. Rolling back all repairs.' >&2
    if [ -f "$undo_file" ]; then
        /usr/sbin/e2undo "$undo_file" "$image" >&2
    fi
    if has_lost_found; then
        echo 'Rollback failed to remove the unexpected /lost+found directory.' >&2
        exit 8
    fi
    echo 'The repair was rolled back to preserve the no-lost+found requirement.' >&2
    exit 8
fi

case "$repair_exit" in
    0|1|2|3)
        cat "$transcript"
        echo 'Disk errors were repaired successfully.'
        ;;
    *)
        cat "$transcript" >&2
        echo "Disk repair left errors unresolved (e2fsck exit code $repair_exit)." >&2
        exit "$repair_exit"
        ;;
esac
'@

& wsl.exe -u root --exec sh -c $repairCommand sh $wslImagePath
$repairExitCode = $LASTEXITCODE
if ($repairExitCode -ne 0) {
    throw "Disk cleaning failed with exit code $repairExitCode."
}

Write-Host 'Disk cleaning completed without creating lost+found.'
exit 0
