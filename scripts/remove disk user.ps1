[CmdletBinding()]
param([switch]$UsbDrive)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Path $PSScriptRoot -Parent
$commonScript = Join-Path $PSScriptRoot 'common.ps1'
$mountScript = Join-Path $PSScriptRoot 'mount.ps1'
$mountPoint = '/mnt/t1fs'

foreach ($requiredScript in @($commonScript, $mountScript)) {
    if (-not (Test-Path -LiteralPath $requiredScript -PathType Leaf)) {
        throw "Required script not found: $requiredScript"
    }
}
. $commonScript

$requestText = [Console]::In.ReadToEnd()
if ([string]::IsNullOrWhiteSpace($requestText)) {
    throw 'User removal details were not supplied by the command centre.'
}
try {
    $request = $requestText | ConvertFrom-Json -ErrorAction Stop
} catch {
    throw 'The supplied user removal details were not valid.'
} finally {
    $requestText = $null
}

$username = ([string]$request.username).Trim()
$password = [string]$request.password
if ($username -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$') {
    throw 'The active username confirmation is invalid.'
}
if (-not $password -or $password.Length -gt 32 -or
    [Text.Encoding]::UTF8.GetByteCount($password) -gt 128 -or
    $password.Contains([char]0) -or $password.Contains("`n") -or $password.Contains("`r")) {
    throw 'The current password is invalid.'
}

if ($UsbDrive) {
    $usbTarget = Get-T1OSUsbDriveTarget
    Write-Host "T1OS USB target: $($usbTarget.DriveSource) '$($usbTarget.Label)' on USB disk $($usbTarget.DiskNumber)."
} else {
    Write-Host 'Checking the mounted disk...'
    if (-not (Test-T1OSDiskMounted -MountPoint $mountPoint)) {
        throw "The disk must be mounted at $mountPoint before removing a user."
    }
    & pwsh -NoLogo -NoProfile -NonInteractive -File $mountScript
    if ($LASTEXITCODE -ne 0) {
        throw "The mounted disk could not be verified as storage.img (exit code $LASTEXITCODE)."
    }
}

$brokerPath = Join-Path $projectRoot 'source/build software/broker/broker.py'
if (-not (Test-Path -LiteralPath $brokerPath -PathType Leaf)) {
    throw "Authentication broker not found: $brokerPath"
}
$wslBrokerOutput = & wsl.exe --exec wslpath -a $brokerPath
if ($LASTEXITCODE -ne 0 -or -not $wslBrokerOutput) {
    throw 'Could not translate the authentication broker path for WSL.'
}
$wslBrokerPath = ([string]($wslBrokerOutput | Select-Object -First 1)).Trim()

$removeCommand = @'
set -eu
mount_point=$1
broker=$2
username=$3
mountpoint -q "$mount_point"
python3 -I -B "$broker" remove-user \
    --root "$mount_point" \
    --username "$username"
test ! -e "$mount_point/the one/master/master.txt"
test ! -e "$mount_point/master/$username"
profile="$mount_point/the one/settings/master/settings.json"
if [ -e "$profile" ]; then
    [ -f "$profile" ] && [ ! -L "$profile" ] || {
        echo 'master profile settings are unsafe' >&2
        exit 1
    }
    rm -f -- "$profile"
fi
sync
'@

$credentialInput = $password
$password = $null
$request = $null
$wslArguments = if ($UsbDrive) {
    $usbMountPoint = "/mnt/t1usb-command-centre-$([guid]::NewGuid().ToString('N'))"
    $usbRemoveCommand = @'
set -eu
drive_source=$1
mount_point=$2
broker=$3
username=$4
mkdir -m 700 "$mount_point"
cleanup() { sync; umount "$mount_point" 2>/dev/null || true; rmdir "$mount_point" 2>/dev/null || true; }
trap cleanup EXIT HUP INT TERM
mount -t drvfs "$drive_source" "$mount_point" -o metadata,uid=0,gid=0,umask=022
test -d "$mount_point/the one/master"
chmod 700 "$mount_point/the one/master"
python3 -I -B "$broker" remove-user --root "$mount_point" --username "$username"
test ! -e "$mount_point/the one/master/master.txt"
test ! -e "$mount_point/master/$username"
'@
    @('-u', 'root', '--exec', 'sh', '-c', $usbRemoveCommand, 'sh',
        $usbTarget.DriveSource, $usbMountPoint, $wslBrokerPath, $username)
} else {
    @('-u', 'root', '--exec', 'nsenter', '-t', '1', '-m', '--',
        'sh', '-c', $removeCommand, 'sh', $mountPoint, $wslBrokerPath, $username)
}
$removeOutput = $credentialInput | & wsl.exe @wslArguments
$removeExitCode = $LASTEXITCODE
$credentialInput = $null
$wslArguments = $null
if ($removeExitCode -ne 0) {
    throw "The disk user could not be removed (exit code $removeExitCode)."
}

if ($UsbDrive) {
    $profilePath = Join-Path $usbTarget.Root 'the one\settings\master\settings.json'
    if (Test-Path -LiteralPath $profilePath -PathType Leaf) {
        Remove-Item -LiteralPath $profilePath -Force
    }
}
$targetName = if ($UsbDrive) { 'USB' } else { 'disk image' }
Write-Host "$targetName user '$username' and its private home were removed."
exit 0
