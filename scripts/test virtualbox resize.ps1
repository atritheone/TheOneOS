[CmdletBinding()]
param(
    [string]$VmName = 'The One OS',
    [string[]]$Modes = @('1280x720', '1920x1080', '1376x843', '1024x768', '2560x1440'),
    [int]$TimeoutSeconds = 20,
    [switch]$StartHeadless,
    [int]$BootWaitSeconds = 22,
    [switch]$PowerOffAfter
)

$incrementalTestBootstrap = Join-Path $PSScriptRoot 'incremental test.ps1'
if (Test-Path -LiteralPath $incrementalTestBootstrap -PathType Leaf) {
    . $incrementalTestBootstrap
    if (Invoke-T1OSIncrementalTestGuard -ScriptPath $PSCommandPath -BoundParameters $PSBoundParameters -UnboundArguments $args) { return }
}
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Path $PSScriptRoot -Parent
$developmentRoot = Join-Path $projectRoot 'development\virtualbox runtime'
$captureRoot = Join-Path $developmentRoot 'resize captures'
$reportPath = Join-Path $developmentRoot 'resize test.json'
$versionPath = Join-Path $projectRoot 'source\settings\virtualbox\version.txt'

function Get-VBoxManage {
    $command = Get-Command 'VBoxManage' -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    $default = 'C:\Program Files\Oracle\VirtualBox\VBoxManage.exe'
    if (Test-Path -LiteralPath $default -PathType Leaf) {
        return $default
    }

    throw 'VBoxManage was not found.'
}

function Get-PngSize {
    param(
        [Parameter(Mandatory)]
        [string]$Path
    )

    $bytes = [System.IO.File]::ReadAllBytes($Path)
    if ($bytes.Length -lt 24) {
        throw "Screenshot is not a valid PNG: $Path"
    }

    $width = [System.Net.IPAddress]::NetworkToHostOrder([System.BitConverter]::ToInt32($bytes, 16))
    $height = [System.Net.IPAddress]::NetworkToHostOrder([System.BitConverter]::ToInt32($bytes, 20))
    return @([int]$width, [int]$height)
}

function Get-ScreenshotSize {
    param(
        [Parameter(Mandatory)]
        [string]$Path
    )

    if (Test-Path -LiteralPath $Path -PathType Leaf) {
        Remove-Item -LiteralPath $Path -Force
    }

    & $script:VBoxManage controlvm $VmName screenshotpng $Path *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "VirtualBox could not capture the running VM (exit code $LASTEXITCODE)."
    }

    return Get-PngSize -Path $Path
}

function Wait-GuestMode {
    param(
        [Parameter(Mandatory)]
        [int]$Width,
        [Parameter(Mandatory)]
        [int]$Height,
        [Parameter(Mandatory)]
        [string]$CapturePath
    )

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    $stable = 0
    $observedWidth = 0
    $observedHeight = 0

    while ([DateTime]::UtcNow -lt $deadline) {
        Start-Sleep -Milliseconds 300
        $size = Get-ScreenshotSize -Path $CapturePath
        $observedWidth = $size[0]
        $observedHeight = $size[1]

        if ($observedWidth -eq $Width -and $observedHeight -eq $Height) {
            $stable++
            if ($stable -ge 2) {
                return [ordered]@{
                    passed = $true
                    requested_width = $Width
                    requested_height = $Height
                    observed_width = $observedWidth
                    observed_height = $observedHeight
                }
            }
        }
        else {
            $stable = 0
        }
    }

    return [ordered]@{
        passed = $false
        requested_width = $Width
        requested_height = $Height
        observed_width = $observedWidth
        observed_height = $observedHeight
    }
}

$script:VBoxManage = Get-VBoxManage
$startedByTest = $false
$running = & $VBoxManage list runningvms
if (-not ($running | Select-String -SimpleMatch "`"$VmName`"" -Quiet)) {
    if (-not $StartHeadless) {
        throw "The VM '$VmName' is not running."
    }

    & $VBoxManage startvm $VmName --type headless | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "VirtualBox could not start '$VmName' headlessly."
    }

    $startedByTest = $true
    Start-Sleep -Seconds $BootWaitSeconds

    $running = & $VBoxManage list runningvms
    if (-not ($running | Select-String -SimpleMatch "`"$VmName`"" -Quiet)) {
        throw "The VM '$VmName' stopped during its $BootWaitSeconds-second boot wait."
    }
}

if (-not (Test-Path -LiteralPath $versionPath -PathType Leaf)) {
    throw "T1OS VirtualBox runtime version file not found: $versionPath"
}

$hostVersion = [string](& $VBoxManage --version)
$guestVersion = (Get-Content -LiteralPath $versionPath -Raw).Trim()
$hostMatch = [regex]::Match($hostVersion.Trim(), '^(?<version>\d+\.\d+\.\d+)r(?<revision>\d+)')
$guestMatch = [regex]::Match($guestVersion, 'VirtualBox Guest Additions (?<version>\d+\.\d+\.\d+) r(?<revision>\d+)')

if (-not $hostMatch.Success -or -not $guestMatch.Success) {
    throw 'The host or guest VirtualBox version could not be parsed.'
}

$versionMatched = $hostMatch.Groups['version'].Value -eq $guestMatch.Groups['version'].Value -and $hostMatch.Groups['revision'].Value -eq $guestMatch.Groups['revision'].Value

if (-not $versionMatched) {
    throw "VirtualBox version mismatch: host=$hostVersion guest=$guestVersion"
}

New-Item -ItemType Directory -Path $captureRoot -Force | Out-Null
$results = @()

foreach ($mode in $Modes) {
    $match = [regex]::Match($mode, '^(?<width>\d+)x(?<height>\d+)$')
    if (-not $match.Success) {
        throw "Invalid mode '$mode'. Use WIDTHxHEIGHT."
    }

    $width = [int]$match.Groups['width'].Value
    $height = [int]$match.Groups['height'].Value
    $capturePath = Join-Path $captureRoot "$width`x$height.png"
    Write-Host "Requesting $width x $height..."
    & $VBoxManage controlvm $VmName setvideomodehint $width $height 32 *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "VirtualBox rejected the $width x $height display hint."
    }

    $result = Wait-GuestMode -Width $width -Height $height -CapturePath $capturePath
    $results += $result

    if (-not $result.passed) {
        Write-Host "Mode failed: requested $width x $height, observed $($result.observed_width) x $($result.observed_height)."
    }
}

$report = [ordered]@{
    format = 1
    vm = $VmName
    tested_at = [DateTime]::UtcNow.ToString('o')
    host_version = $hostVersion.Trim()
    guest_version = $guestVersion
    version_matched = $versionMatched
    started_headless = $startedByTest
    passed = -not ($results | Where-Object { -not $_.passed })
    transitions = $results
}

$report | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $reportPath -Encoding utf8
Write-Host "Resize report: $reportPath"

if ($startedByTest -or $PowerOffAfter) {
    & $VBoxManage controlvm $VmName poweroff *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "VirtualBox could not power off '$VmName' after the resize test."
    }
}

if (-not $report.passed) {
    exit 1
}

Write-Host 'All VirtualBox resize transitions passed.'
