[CmdletBinding()]
param(
    [ValidateRange(60, 600)]
    [int]$BootTimeoutSeconds = 300
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Path $PSScriptRoot -Parent
$environmentRoot = Join-Path $projectRoot 'environment'
$hardwareRoot = Join-Path $environmentRoot 'hardware'
$sourceVmx = Join-Path $environmentRoot 'vmware\The One OS.vmx'
$serialPath = Join-Path $environmentRoot 'vmware-serial.log'
$evidencePath = Join-Path $hardwareRoot 'vmware-release-smoke-serial.log'
$token = [guid]::NewGuid().ToString('N').Substring(0, 10)
$cloneName = "The One OS 0.31 Release Smoke $token"
$cloneRoot = Join-Path $hardwareRoot "vmware-smoke-$token"
$cloneVmx = Join-Path $cloneRoot "$cloneName.vmx"
$cloned = $false
$started = $false

$vmrun = Get-Command vmrun -ErrorAction SilentlyContinue
if (-not $vmrun) {
    throw 'vmrun was not found. Install VMware Workstation or add vmrun to PATH.'
}
if (-not (Test-Path -LiteralPath $sourceVmx -PathType Leaf)) {
    throw "VMware VM not found: $sourceVmx. Run scripts/build vmware.ps1."
}

function Get-T1OSRunningVmwareVms {
    return @(& $vmrun.Source -T ws list) | ForEach-Object { ([string]$_).Trim() }
}

function Read-T1OSSharedText {
    param([Parameter(Mandatory)][string]$Path)

    try {
        $stream = [System.IO.FileStream]::new(
            $Path,
            [System.IO.FileMode]::Open,
            [System.IO.FileAccess]::Read,
            [System.IO.FileShare]::ReadWrite -bor [System.IO.FileShare]::Delete
        )
        try {
            $reader = [System.IO.StreamReader]::new($stream)
            try {
                return $reader.ReadToEnd()
            }
            finally {
                $reader.Dispose()
            }
        }
        finally {
            $stream.Dispose()
        }
    }
    catch [System.IO.IOException] {
        return ''
    }
}

try {
    New-Item -ItemType Directory -Path $cloneRoot -Force | Out-Null
    & $vmrun.Source -T ws clone $sourceVmx $cloneVmx full -cloneName $cloneName
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $cloneVmx -PathType Leaf)) {
        throw "VMware full clone failed with exit code $LASTEXITCODE."
    }
    $cloned = $true

    if (Test-Path -LiteralPath $serialPath -PathType Leaf) {
        Remove-Item -LiteralPath $serialPath -Force
    }

    & $vmrun.Source -T ws start $cloneVmx nogui
    if ($LASTEXITCODE -ne 0) {
        throw "VMware clone start failed with exit code $LASTEXITCODE."
    }
    $started = $true

    $deadline = (Get-Date).AddSeconds($BootTimeoutSeconds)
    $accepted = $false
    $fatalPattern = 'I CANNOT CONTINUE|Kernel panic|blocked for more than 120 seconds|GPU OWNER FAILED|ABORTING SYSTEM'

    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 2
        $running = Get-T1OSRunningVmwareVms
        if (-not ($running | Where-Object {
            [string]::Equals($_, $cloneVmx, [System.StringComparison]::OrdinalIgnoreCase)
        })) {
            throw 'VMware smoke VM stopped before acceptance.'
        }

        if (Test-Path -LiteralPath $serialPath -PathType Leaf) {
            $serial = Read-T1OSSharedText -Path $serialPath
            if ($serial -match $fatalPattern) {
                throw 'VMware smoke boot emitted a fatal marker.'
            }
            if (
                $serial.Contains('THE DRIVER SERVER IS READY.') -and
                $serial.Contains('REPORTED 0 FAILURES.') -and
                $serial.Contains('THE WINDOW SERVER IS READY ON PROCESS ') -and
                $serial.Contains('I HAVE STARTED THE FIRST-RUN OR LOGIN EXPERIENCE')
            ) {
                $accepted = $true
                break
            }
        }
    }

    if (-not $accepted) {
        throw 'VMware smoke boot timed out before the first-run acceptance markers.'
    }

    Copy-Item -LiteralPath $serialPath -Destination $evidencePath -Force
    Write-Host "VMware release smoke boot passed: $cloneName"
    Write-Host "Serial evidence: $evidencePath"
}
finally {
    if ($started) {
        & $vmrun.Source -T ws stop $cloneVmx hard | Out-Null
    }
    if ($cloned -and (Test-Path -LiteralPath $cloneVmx -PathType Leaf)) {
        & $vmrun.Source -T ws deleteVM $cloneVmx | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "Could not delete disposable VMware clone '$cloneName' through vmrun."
        }
    }
    if (Test-Path -LiteralPath $cloneRoot) {
        $resolvedCloneRoot = [System.IO.Path]::GetFullPath($cloneRoot)
        $resolvedHardwareRoot = [System.IO.Path]::GetFullPath($hardwareRoot).TrimEnd('\') + '\'
        if (-not $resolvedCloneRoot.StartsWith($resolvedHardwareRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to remove unexpected VMware smoke path: $resolvedCloneRoot"
        }
        Get-ChildItem -LiteralPath $resolvedCloneRoot -Force -Recurse -ErrorAction SilentlyContinue |
            ForEach-Object { $_.Attributes = [System.IO.FileAttributes]::Normal }
        (Get-Item -LiteralPath $resolvedCloneRoot -Force).Attributes = [System.IO.FileAttributes]::Normal
        Remove-Item -LiteralPath $resolvedCloneRoot -Recurse -Force -ErrorAction SilentlyContinue
        if (Test-Path -LiteralPath $resolvedCloneRoot) {
            Write-Warning "Could not remove disposable VMware clone directory '$resolvedCloneRoot'."
        }
    }
}
