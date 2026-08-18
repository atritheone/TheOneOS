[CmdletBinding()]
param([switch]$UsbDrive)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$commonScript = Join-Path $PSScriptRoot '..\common.ps1'
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
    throw 'User details were not supplied by the command centre.'
}

try {
    $request = $requestText | ConvertFrom-Json -ErrorAction Stop
} catch {
    throw 'The supplied user details were not valid.'
} finally {
    $requestText = $null
}

$username = ([string]$request.username).Trim()
$password = [string]$request.password

if ($username -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$') {
    throw 'The username must contain 1-32 ASCII letters, numbers, dots, underscores, or hyphens and start with a letter or number.'
}
$passwordBytes = [Text.Encoding]::UTF8.GetByteCount($password)
if ($password.Length -lt 4 -or $password.Length -gt 32 -or $passwordBytes -gt 128 -or
    $password.Contains([char]0) -or $password.Contains("`n") -or $password.Contains("`r")) {
    throw 'The password must contain 4-32 characters, use at most 128 UTF-8 bytes, and contain no line breaks.'
}
$passwordBytes = 0

if ($UsbDrive) {
    $usbTarget = Get-T1OSUsbDriveTarget
    Write-Host "T1OS USB target: $($usbTarget.DriveSource) '$($usbTarget.Label)' on USB disk $($usbTarget.DiskNumber)."
} else {
    Write-Host 'Checking the mounted disk...'
    if (-not (Test-T1OSDiskMounted -MountPoint $mountPoint)) {
        throw "The disk must be mounted at $mountPoint before creating a user."
    }

    # mount.ps1 also proves that the existing mount is backed by this project's
    # storage.img rather than merely trusting the mount-point name.
    & pwsh -NoLogo -NoProfile -NonInteractive -File $mountScript
    if ($LASTEXITCODE -ne 0) {
        throw "The mounted disk could not be verified as storage.img (exit code $LASTEXITCODE)."
    }
}

Write-Host "Creating the active disk user '$username'..."

$brokerPath = Join-Path $projectRoot 'source/build software/broker/broker.py'
if (-not (Test-Path -LiteralPath $brokerPath -PathType Leaf)) {
    throw "Authentication broker not found: $brokerPath"
}
$wslBrokerOutput = & wsl.exe --exec wslpath -a $brokerPath
if ($LASTEXITCODE -ne 0 -or -not $wslBrokerOutput) {
    throw 'Could not translate the authentication broker path for WSL.'
}
$wslBrokerPath = ([string]($wslBrokerOutput | Select-Object -First 1)).Trim()

$createCommand = @'
set -eu
mount_point=$1
broker=$2
username=$3

mountpoint -q "$mount_point" || {
    echo "$mount_point is not mounted." >&2
    exit 1
}

umask 077
python3 -I -B "$broker" provision-user \
    --root "$mount_point" \
    --username "$username"
test "$(stat -c '%a' "$mount_point/the one/master/master.txt")" = 600
test "$(stat -c '%u:%g:%a' "$mount_point/master/$username")" = 1000:1000:700
sync
echo "Active disk user '$username' was created successfully."
'@

# The PowerShell native-command pipeline writes its own final line terminator.
# Adding one here produces a second blank password line, which the broker
# intentionally rejects as malformed secret input.
$passwordInput = $password
$password = $null
$request = $null
$wslArguments = if ($UsbDrive) {
    $usbMountPoint = "/mnt/t1usb-command-centre-$([guid]::NewGuid().ToString('N'))"
    $usbCreateCommand = @'
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
python3 -I -B "$broker" provision-user --root "$mount_point" --username "$username"
test "$(stat -c '%a' "$mount_point/the one/master/master.txt")" = 600
test "$(stat -c '%u:%g:%a' "$mount_point/master/$username")" = 1000:1000:700
echo "Active USB user '$username' was created successfully."
'@
    @('-u', 'root', '--exec', 'sh', '-c', $usbCreateCommand, 'sh',
        $usbTarget.DriveSource, $usbMountPoint, $wslBrokerPath, $username)
} else {
    @('-u', 'root', '--exec', 'nsenter', '-t', '1', '-m', '--',
        'sh', '-c', $createCommand, 'sh', $mountPoint, $wslBrokerPath, $username)
}
$passwordInput | & wsl.exe @wslArguments
$createExitCode = $LASTEXITCODE
$passwordInput = $null
$wslArguments = $null

if ($createExitCode -ne 0) {
    throw "The disk user could not be created (exit code $createExitCode)."
}

$targetName = if ($UsbDrive) { 'USB' } else { 'disk image' }
Write-Host "$targetName user '$username' is now the active master. Existing home files were kept."
exit 0
