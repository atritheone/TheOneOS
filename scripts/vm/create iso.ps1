[CmdletBinding()]
param(
    [string]$OutputPath,

    [string]$GrubConfigSource
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$environmentRoot = Join-Path $projectRoot 'environment\software'
. (Join-Path $PSScriptRoot '..\common.ps1')
Set-Location -LiteralPath $environmentRoot

$logFile = Join-Path $environmentRoot 'bootiso_debug.log'
'' | Out-File -LiteralPath $logFile -Force

if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $isoPath = Join-Path $environmentRoot 't1os-boot.iso'
}
elseif ([System.IO.Path]::IsPathRooted($OutputPath)) {
    $isoPath = [System.IO.Path]::GetFullPath($OutputPath)
}
else {
    $isoPath = [System.IO.Path]::GetFullPath((Join-Path $environmentRoot $OutputPath))
}

$isoDirectory = Split-Path -Path $isoPath -Parent
New-Item -ItemType Directory -Path $isoDirectory -Force | Out-Null
$temporaryIsoPath = Join-Path $isoDirectory ('.t1os-boot-{0}.iso' -f [guid]::NewGuid().ToString('N'))
$rawImagePath = Join-Path $environmentRoot 'storage.img'
$initSource = Join-Path $projectRoot 'source\entry\init\init software.sh'
$initTarget = Join-Path $environmentRoot 'initramfs\init'
$busyBoxPath = Join-Path $environmentRoot 'initramfs\bin\busybox'
$kernelPath = Join-Path $environmentRoot 'iso\boot\vmlinuz'
$grubConfigPath = Join-Path $environmentRoot 'iso\boot\grub\grub.cfg'
$canonicalGrubConfigPath = Join-Path $projectRoot 'source\entry\grub\grub 0.1.cfg'

if ([string]::IsNullOrWhiteSpace($GrubConfigSource)) {
    $GrubConfigSource = $canonicalGrubConfigPath
}
elseif (-not [System.IO.Path]::IsPathRooted($GrubConfigSource)) {
    $GrubConfigSource = Join-Path $projectRoot $GrubConfigSource
}
$GrubConfigSource = [System.IO.Path]::GetFullPath($GrubConfigSource)

Write-Host 'building t1os-boot.iso...'
Write-Host "logging to $logFile"

foreach ($requiredFile in @($rawImagePath, $initSource, $busyBoxPath, $kernelPath, $GrubConfigSource)) {
    if (-not (Test-Path -LiteralPath $requiredFile -PathType Leaf)) {
        throw "boot ISO input not found: $requiredFile"
    }
    if ((Get-Item -LiteralPath $requiredFile).Length -eq 0) {
        throw "boot ISO input is empty: $requiredFile"
    }
}

# The staged GRUB file is a generated ISO input and may have been changed by a
# previous graphics test. Production builds always refresh it from the tracked
# software-VM template. Tests that intentionally stage a temporary boot mode
# pass that staged file explicitly through -GrubConfigSource.
if (-not [System.IO.Path]::GetFullPath($grubConfigPath).Equals(
    $GrubConfigSource,
    [System.StringComparison]::OrdinalIgnoreCase
)) {
    Copy-Item -LiteralPath $GrubConfigSource -Destination $grubConfigPath -Force
}

$wslEnvOutput = & wsl.exe --exec wslpath -a $environmentRoot
if ($LASTEXITCODE -ne 0 -or -not $wslEnvOutput) {
    Add-Content -LiteralPath $logFile -Value 'could not translate environment path for WSL'
    throw 'could not translate the environment path for WSL.'
}
$wslEnvPath = ([string]($wslEnvOutput | Select-Object -First 1)).Trim()
if ([string]::IsNullOrWhiteSpace($wslEnvPath)) {
    Add-Content -LiteralPath $logFile -Value 'WSL returned an empty environment path'
    throw 'WSL returned an empty environment path.'
}

$wslTemporaryIsoOutput = & wsl.exe --exec wslpath -a $temporaryIsoPath
if ($LASTEXITCODE -ne 0 -or -not $wslTemporaryIsoOutput) {
    throw 'could not translate the temporary ISO path for WSL.'
}
$wslTemporaryIsoPath = ([string]($wslTemporaryIsoOutput | Select-Object -First 1)).Trim()

function Invoke-LoggedWSL {
    param(
        [Parameter(Mandatory)]
        [string]$Command
    )

    Add-Content -LiteralPath $logFile -Value "`n> $Command"
    & wsl.exe --exec bash -lc $Command 2>&1 |
        Tee-Object -Append -FilePath $logFile |
        Out-Host
    return $LASTEXITCODE
}

try {
    $dependencyExitCode = Invoke-LoggedWSL -Command (
        "command -v bash >/dev/null && command -v gzip >/dev/null && " +
        "command -v grub-mkrescue >/dev/null && test -x '$wslEnvPath/initramfs/bin/busybox'"
    )
    if ($dependencyExitCode -ne 0) {
        throw 'WSL is missing bash, gzip, grub-mkrescue, or the staged initramfs BusyBox executable.'
    }

    Copy-Item -LiteralPath $initSource -Destination $initTarget -Force
    $filesystemUuid = Set-T1OSBootRootIdentity -ImagePath $rawImagePath -GrubConfigPath $grubConfigPath

    $initramfsExitCode = Invoke-LoggedWSL -Command (
        "set -o pipefail && cd '$wslEnvPath/initramfs' && " +
        "find . -print0 | ./bin/busybox cpio -0 -H newc -o | gzip -9 > ../initramfs.cpio.gz && " +
        "test -s ../initramfs.cpio.gz && cp ../initramfs.cpio.gz ../iso/boot/initramfs"
    )
    if ($initramfsExitCode -ne 0) {
        throw 'initramfs build failed; see bootiso_debug.log for details.'
    }

    $buildExitCode = Invoke-LoggedWSL -Command (
        "cd '$wslEnvPath' && grub-mkrescue -o '$wslTemporaryIsoPath' iso && test -s '$wslTemporaryIsoPath'"
    )
    if ($buildExitCode -ne 0 -or -not (Test-Path -LiteralPath $temporaryIsoPath -PathType Leaf)) {
        throw 'ISO build failed; see bootiso_debug.log for details.'
    }

    Assert-T1OSBootRootIdentity -ImagePath $rawImagePath -GrubConfigPath $grubConfigPath | Out-Null

    if (Test-Path -LiteralPath $isoPath -PathType Leaf) {
        Install-T1OSReplacementFile -SourcePath $temporaryIsoPath -DestinationPath $isoPath
    }
    else {
        Move-Item -LiteralPath $temporaryIsoPath -Destination $isoPath
    }
    $temporaryIsoPath = $null

    Add-Content -LiteralPath $logFile -Value "`nISO created at $isoPath for root UUID $filesystemUuid"
    Write-Host "created boot ISO: $isoPath"
    exit 0
}
catch {
    Add-Content -LiteralPath $logFile -Value "`nERROR: $($_.Exception.Message)"
    Write-Host $_.Exception.Message
    exit 1
}
finally {
    if ($null -ne $temporaryIsoPath -and (Test-Path -LiteralPath $temporaryIsoPath)) {
        Remove-Item -LiteralPath $temporaryIsoPath -Force -ErrorAction SilentlyContinue
    }
}
