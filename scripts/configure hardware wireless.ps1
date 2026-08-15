[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Path $PSScriptRoot -Parent
$settingsDirectory = Join-Path $projectRoot 'source\settings\network'
$settingsPath = Join-Path $settingsDirectory 'wireless.txt'

$payload = [Console]::In.ReadToEnd()
if (-not $payload) {
    throw 'Wireless settings were not supplied.'
}

try {
    $request = $payload | ConvertFrom-Json -ErrorAction Stop
}
catch {
    throw 'Wireless settings were not valid JSON.'
}

$ssid = [string]$request.ssid
$security = ([string]$request.security).Trim().ToLowerInvariant()
$passphrase = [string]$request.passphrase

if ([string]::IsNullOrWhiteSpace($ssid) -or [Text.Encoding]::UTF8.GetByteCount($ssid) -gt 32) {
    throw 'The Wi-Fi name must contain between 1 and 32 UTF-8 bytes.'
}
if ($ssid.IndexOfAny([char[]]@([char]0, [char]10, [char]13)) -ge 0 -or $ssid.Contains('=')) {
    throw 'The Wi-Fi name contains an unsupported control character or equals sign.'
}
if ($security -notin @('open', 'wpa2', 'wpa3')) {
    throw 'Wireless security must be open, WPA2, or WPA3.'
}
if ($security -ne 'open') {
    $passphraseBytes = [Text.Encoding]::UTF8.GetByteCount($passphrase)
    if ($passphraseBytes -lt 8 -or $passphraseBytes -gt 63) {
        throw 'The Wi-Fi passphrase must contain between 8 and 63 UTF-8 bytes.'
    }
    if ($passphrase.IndexOfAny([char[]]@([char]0, [char]10, [char]13)) -ge 0) {
        throw 'The Wi-Fi passphrase contains an unsupported control character.'
    }
    throw 'Protected Wi-Fi credentials cannot be baked into a distributable T1OS image. Configure this network in T1OS Settings on the target device.'
}

$lines = @(
    "ssid=$ssid",
    "security=$security"
)
New-Item -ItemType Directory -Path $settingsDirectory -Force | Out-Null
$temporary = "$settingsPath.temporary-$PID"
try {
    [IO.File]::WriteAllText($temporary, (($lines -join "`n") + "`n"), [Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $temporary -Destination $settingsPath -Force
}
finally {
    if (Test-Path -LiteralPath $temporary) {
        Remove-Item -LiteralPath $temporary -Force
    }
}

Write-Host "Hardware Wi-Fi settings saved for '$ssid' using $security security."
Write-Host 'Run build complete hardware usb (or sync hardware root, then rebuild the USB image) to include them.'
