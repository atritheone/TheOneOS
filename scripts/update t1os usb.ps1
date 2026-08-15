[CmdletBinding()]
param(
    [switch]$Prepare,
    [switch]$IncludeBoot,
    [switch]$ValidateOnly,
    [switch]$Full
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Path $PSScriptRoot -Parent
$updaterPath = $MyInvocation.MyCommand.Path
$targetValidator = Join-Path $PSScriptRoot 'push to disk.ps1'
$aclPreparer = Join-Path $PSScriptRoot 'migrate managed python usb acl.ps1'
$bootUpdater = Join-Path $PSScriptRoot 'push hardware kernel to usb.ps1'
$updateStatePath = 'D:\the one\settings\usb update state.json'

function Get-T1OSUsbSourceStamp {
    $sourceRoots = @(
        'source\build software',
        'source\boot',
        'source\drivers',
        'source\catalogue\graphics',
        'source\catalogue\virtualbox',
        'source\catalogue\audio',
        'source\catalogue\network',
        'source\catalogue\image',
        'source\catalogue\python',
        'source\software\virtualbox',
        'source\software\audio',
        'source\software\network',
        'source\software\chromium',
        'source\software\python',
        'source\settings\virtualbox',
        'source\settings\network',
        'source\settings\media',
        'source\settings\runtime paths.json',
        'source\native\video',
        'resource\chromium-source\150.0.7871.181\manifest.json',
        'resource\chromium-source\150.0.7871.181\overlay\media\gpu\t1os',
        'resource\fonts',
        'resource\logos',
        'resource\cursors\extra simple white original',
        'flash\red_screen_of_death.png'
    )
    $records = [Collections.Generic.List[string]]::new()
    foreach ($relativeRoot in $sourceRoots) {
        $path = Join-Path $projectRoot $relativeRoot
        if (-not (Test-Path -LiteralPath $path)) {
            throw "T1OS USB update source is missing: $path"
        }
        $items = if (Test-Path -LiteralPath $path -PathType Leaf) {
            @(Get-Item -LiteralPath $path -Force)
        }
        else {
            @(Get-ChildItem -LiteralPath $path -File -Recurse -Force)
        }
        foreach ($item in $items) {
            if (
                $item.Extension -in @('.pyc', '.pyo') -or
                $item.DirectoryName -match '(^|[\\/])__pycache__($|[\\/])'
            ) {
                continue
            }
            $relative = [IO.Path]::GetRelativePath($projectRoot, $item.FullName).
                Replace('\', '/')
            $records.Add(
                "$relative`0$($item.Length)`0$($item.LastWriteTimeUtc.Ticks)"
            )
        }
    }
    foreach ($definition in @(
        $targetValidator,
        $aclPreparer,
        $bootUpdater,
        $updaterPath
    )) {
        $item = Get-Item -LiteralPath $definition -Force
        $relative = [IO.Path]::GetRelativePath($projectRoot, $item.FullName).
            Replace('\', '/')
        $records.Add("$relative`0$($item.Length)`0$($item.LastWriteTimeUtc.Ticks)")
    }
    $records.Sort([StringComparer]::Ordinal)
    $payload = [Text.Encoding]::UTF8.GetBytes(($records -join "`n"))
    [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($payload)).
        ToLowerInvariant()
}

foreach ($required in @($targetValidator, $aclPreparer, $bootUpdater)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Required T1OS USB update component is missing: $required"
    }
}

& $targetValidator -UsbDrive -ValidateTargetOnly
if ($LASTEXITCODE -ne 0) {
    throw "T1OS USB target validation failed (exit code $LASTEXITCODE)."
}

if ($ValidateOnly) {
    Write-Host 'The T1OS USB target is valid; no files were changed.'
    exit 0
}

if ($Prepare) {
    Write-Host 'Preparing the one-time Windows maintenance ACL...'
    & $aclPreparer
    if ($LASTEXITCODE -ne 0) {
        throw "T1OS USB maintenance preparation failed (exit code $LASTEXITCODE)."
    }
}

if ($IncludeBoot) {
    Write-Host 'Updating the kernel, initramfs, EFI boot files, and modules...'
    & $bootUpdater -Confirm:$false
    if ($LASTEXITCODE -ne 0) {
        throw "T1OS USB boot update failed (exit code $LASTEXITCODE)."
    }
}

$sourceStamp = Get-T1OSUsbSourceStamp
$currentRelease = (
    Get-Content -Raw -LiteralPath (Join-Path $projectRoot 'source\python\locks\release.json') |
        ConvertFrom-Json -ErrorAction Stop
).release
if (-not $Full -and (Test-Path -LiteralPath $updateStatePath -PathType Leaf)) {
    try {
        $state = Get-Content -Raw -LiteralPath $updateStatePath |
            ConvertFrom-Json -ErrorAction Stop
        if (
            [string]$state.source_stamp -ceq $sourceStamp -and
            [string]$state.python_release -ceq [string]$currentRelease
        ) {
            Write-Host 'The USB already contains the last verified managed source state.'
            Write-Host 'No files needed updating. Use -Full for an exhaustive target re-scan.'
            exit 0
        }
    }
    catch {
        Write-Host 'The previous USB update stamp is unreadable; performing a full verified sync.'
    }
}

Write-Host 'Updating all managed T1OS userspace files incrementally...'
& $targetValidator -UsbDrive -Fast
if ($LASTEXITCODE -ne 0) {
    throw "T1OS USB userspace update failed (exit code $LASTEXITCODE)."
}

$state = [ordered]@{
    format = 1
    source_stamp = $sourceStamp
    python_release = [string]$currentRelease
    verified_utc = [DateTime]::UtcNow.ToString('o')
}
$stateTemporaryPath = "$updateStatePath.$PID.new"
try {
    [IO.File]::WriteAllText(
        $stateTemporaryPath,
        (($state | ConvertTo-Json -Depth 3) + "`n"),
        [Text.UTF8Encoding]::new($false)
    )
    Move-Item -LiteralPath $stateTemporaryPath `
        -Destination $updateStatePath -Force
}
finally {
    Remove-Item -LiteralPath $stateTemporaryPath `
        -Force -ErrorAction SilentlyContinue
}
Write-Host 'T1OS USB update completed and verified.'
