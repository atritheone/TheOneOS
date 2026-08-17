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
    throw 'User changes were not supplied by the command centre.'
}
try {
    $request = $requestText | ConvertFrom-Json -ErrorAction Stop
} catch {
    throw 'The supplied user changes were not valid.'
} finally {
    $requestText = $null
}

$username = ([string]$request.username).Trim()
$currentPassword = [string]$request.currentPassword
$newPassword = [string]$request.newPassword
$changePassword = $request.changePassword -eq $true

if ($username -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$') {
    throw 'The username must contain 1-32 ASCII letters, numbers, dots, underscores, or hyphens and start with a letter or number.'
}
if (-not $currentPassword -or $currentPassword.Length -gt 32 -or
    [Text.Encoding]::UTF8.GetByteCount($currentPassword) -gt 128 -or
    $currentPassword.Contains([char]0) -or $currentPassword.Contains("`n") -or $currentPassword.Contains("`r")) {
    throw 'The current password is invalid.'
}
if ($changePassword -and ($newPassword.Length -lt 4 -or $newPassword.Length -gt 32 -or
    [Text.Encoding]::UTF8.GetByteCount($newPassword) -gt 128 -or
    $newPassword.Contains([char]0) -or $newPassword.Contains("`n") -or $newPassword.Contains("`r"))) {
    throw 'The new password must contain between 4 and 32 characters and cannot contain a null character or line break.'
}
if (-not $changePassword -and $newPassword) {
    throw 'A new password was supplied without requesting a password change.'
}

if ($UsbDrive) {
    $usbTarget = Get-T1OSUsbDriveTarget
    Write-Host "T1OS USB target: $($usbTarget.DriveSource) '$($usbTarget.Label)' on USB disk $($usbTarget.DiskNumber)."
} else {
    Write-Host 'Checking the mounted disk...'
    if (-not (Test-T1OSDiskMounted -MountPoint $mountPoint)) {
        throw "The disk must be mounted at $mountPoint before changing a user."
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

$changeCommand = @'
set -eu
mount_point=$1
broker=$2
username=$3
change_password=$4

mountpoint -q "$mount_point"
arguments=""
if [ "$change_password" = 1 ]; then
    arguments=--change-password
fi
python3 -I -B "$broker" change-user \
    --root "$mount_point" \
    --username "$username" \
    $arguments
test "$(stat -c '%a' "$mount_point/the one/master/master.txt")" = 600
test "$(stat -c '%u:%g:%a' "$mount_point/master/$username")" = 1000:1000:700
sync
'@

$credentialInput = if ($changePassword) {
    "$currentPassword`n$newPassword"
} else {
    $currentPassword
}
$currentPassword = $null
$newPassword = $null
$request = $null
$wslArguments = if ($UsbDrive) {
    $usbMountPoint = "/mnt/t1usb-command-centre-$([guid]::NewGuid().ToString('N'))"
    $usbChangeCommand = @'
set -eu
drive_source=$1
mount_point=$2
broker=$3
username=$4
change_password=$5
mkdir -m 700 "$mount_point"
cleanup() { sync; umount "$mount_point" 2>/dev/null || true; rmdir "$mount_point" 2>/dev/null || true; }
trap cleanup EXIT HUP INT TERM
mount -t drvfs "$drive_source" "$mount_point" -o metadata,uid=0,gid=0,umask=022
test -d "$mount_point/the one/master"
chmod 700 "$mount_point/the one/master"
arguments=""
[ "$change_password" = 0 ] || arguments=--change-password
python3 -I -B "$broker" change-user --root "$mount_point" --username "$username" $arguments
test "$(stat -c '%a' "$mount_point/the one/master/master.txt")" = 600
'@
    @('-u', 'root', '--exec', 'sh', '-c', $usbChangeCommand, 'sh',
        $usbTarget.DriveSource, $usbMountPoint, $wslBrokerPath, $username,
        $(if ($changePassword) { '1' } else { '0' }))
} else {
    @('-u', 'root', '--exec', 'nsenter', '-t', '1', '-m', '--',
        'sh', '-c', $changeCommand, 'sh', $mountPoint, $wslBrokerPath, $username,
        $(if ($changePassword) { '1' } else { '0' }))
}
$changeOutput = $credentialInput | & wsl.exe @wslArguments
$changeExitCode = $LASTEXITCODE
$credentialInput = $null
$wslArguments = $null
if ($changeExitCode -ne 0) {
    throw "The disk user could not be changed (exit code $changeExitCode)."
}

$resultText = ([string]($changeOutput | Select-Object -Last 1)).Trim()
try {
    $result = $resultText | ConvertFrom-Json -ErrorAction Stop
} catch {
    throw 'The authentication broker returned an invalid change result.'
}

$profileCommand = @'
set -eu
root=$1
old_name=$2
new_name=$3
profile="$root/the one/settings/master/settings.json"
[ -e "$profile" ] || exit 0
python3 -I -B - "$profile" "$old_name" "$new_name" <<'PY'
import json, os, stat, sys, tempfile
path, old_name, new_name = sys.argv[1:]
metadata = os.lstat(path)
if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode) or metadata.st_size > 4096:
    raise SystemExit('master profile settings are unsafe')
with open(path, 'r', encoding='utf-8') as stream:
    value = json.load(stream)
if not isinstance(value, dict):
    raise SystemExit('master profile settings are invalid')
image = str(value.get('image_path') or '')
old_home = f'/master/{old_name}/'
if image.startswith(old_home):
    value['image_path'] = f'/master/{new_name}/' + image[len(old_home):]
directory = os.path.dirname(path)
descriptor, temporary = tempfile.mkstemp(prefix='.settings.', suffix='.new', dir=directory)
try:
    with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
        json.dump(value, stream, sort_keys=True, separators=(',', ':'))
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(temporary, 0o644)
    os.replace(temporary, path)
finally:
    if os.path.exists(temporary):
        os.unlink(temporary)
PY
'@

if (-not $UsbDrive -and [string]$result.old_username -cne [string]$result.username) {
    $profileArguments = @(
        '-u', 'root', '--exec', 'nsenter', '-t', '1', '-m', '--',
        'sh', '-c', $profileCommand, 'sh', $mountPoint,
        ([string]$result.old_username), ([string]$result.username)
    )
    & wsl.exe @profileArguments
    if ($LASTEXITCODE -ne 0) {
        throw 'The user changed, but the master profile path could not be relocated.'
    }
}

if ($UsbDrive -and [string]$result.old_username -cne [string]$result.username) {
    $profilePath = Join-Path $usbTarget.Root 'the one\settings\master\settings.json'
    if (Test-Path -LiteralPath $profilePath -PathType Leaf) {
        $profile = Get-Content -LiteralPath $profilePath -Raw | ConvertFrom-Json -ErrorAction Stop
        $oldPrefix = "/master/$($result.old_username)/"
        if ([string]$profile.image_path -like "$oldPrefix*") {
            $profile.image_path = "/master/$($result.username)/" + ([string]$profile.image_path).Substring($oldPrefix.Length)
            $temporaryProfile = "$profilePath.$([guid]::NewGuid().ToString('N')).new"
            try {
                $profile | ConvertTo-Json -Depth 16 -Compress | Set-Content -LiteralPath $temporaryProfile -Encoding utf8NoBOM
                Move-Item -LiteralPath $temporaryProfile -Destination $profilePath -Force
            } finally {
                if (Test-Path -LiteralPath $temporaryProfile) { Remove-Item -LiteralPath $temporaryProfile -Force }
            }
        }
    }
}

if (-not $UsbDrive) {
    & wsl.exe -u root --exec nsenter -t 1 -m -- sync
    if ($LASTEXITCODE -ne 0) {
        throw 'The changed disk user could not be flushed to storage.'
    }
}
$targetName = if ($UsbDrive) { 'USB' } else { 'disk image' }
Write-Host "$targetName user '$($result.old_username)' changed to '$($result.username)'. Password changed: $([bool]$result.password_changed)."
exit 0
