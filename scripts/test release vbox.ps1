[CmdletBinding()]
param(
    [string]$VmName = 'The One OS',

    [ValidateRange(60, 600)]
    [int]$BootTimeoutSeconds = 300
)

$incrementalTestBootstrap = Join-Path $PSScriptRoot 'incremental test.ps1'
if (Test-Path -LiteralPath $incrementalTestBootstrap -PathType Leaf) {
    . $incrementalTestBootstrap
    if (Invoke-T1OSIncrementalTestGuard -ScriptPath $PSCommandPath -BoundParameters $PSBoundParameters -UnboundArguments $args) { return }
}
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Path $PSScriptRoot -Parent
$environmentRoot = Join-Path $projectRoot 'environment'
$hardwareRoot = Join-Path $environmentRoot 'hardware'
$serialPath = Join-Path $environmentRoot 'vbox-serial.log'
$evidencePath = Join-Path $hardwareRoot 'vbox-release-smoke-serial.log'
$token = [guid]::NewGuid().ToString('N').Substring(0, 10)
$cloneName = "$VmName 0.31 Release Smoke $token"
$cloneBase = Join-Path $hardwareRoot "vbox-smoke-$token"
$registered = $false
$bootAccepted = $false

function Get-VmState {
    param([Parameter(Mandatory)][string]$Name)

    $stateLine = & VBoxManage showvminfo $Name --machinereadable 2>$null |
        Where-Object { $_ -match '^VMState=' } |
        Select-Object -First 1
    if (-not $stateLine) {
        return 'missing'
    }
    return ([string]$stateLine).Split('=', 2)[1].Trim('"')
}

function Read-SharedText {
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
    & VBoxManage clonevm $VmName `
        --name $cloneName `
        --basefolder $cloneBase `
        --mode all `
        --register
    if ($LASTEXITCODE -ne 0) {
        throw "VirtualBox clone failed with exit code $LASTEXITCODE."
    }
    $registered = $true

    if (Test-Path -LiteralPath $serialPath -PathType Leaf) {
        Remove-Item -LiteralPath $serialPath -Force
    }

    & VBoxManage startvm $cloneName --type headless
    if ($LASTEXITCODE -ne 0) {
        throw "VirtualBox clone start failed with exit code $LASTEXITCODE."
    }

    $deadline = (Get-Date).AddSeconds($BootTimeoutSeconds)
    $fatalPattern = (
        'I CANNOT CONTINUE|Kernel panic|blocked for more than 120 seconds|' +
        'GPU OWNER FAILED|ABORTING SYSTEM'
    )

    while ((Get-Date) -lt $deadline) {
        $state = Get-VmState -Name $cloneName

        if (Test-Path -LiteralPath $serialPath -PathType Leaf) {
            $serial = Read-SharedText -Path $serialPath
            if ($serial -match $fatalPattern) {
                throw 'VirtualBox smoke boot emitted a fatal marker.'
            }
            if (
                $serial.Contains('THE DRIVER SERVER IS READY.') -and
                $serial.Contains('REPORTED 0 FAILURES.') -and
                $serial.Contains('THE WINDOW SERVER IS READY ON PROCESS ') -and
                $serial.Contains('I HAVE STARTED THE FIRST-RUN OR LOGIN EXPERIENCE')
            ) {
                $bootAccepted = $true
                Start-Sleep -Seconds 15
                break
            }
        }

        if ($state -in @('poweroff', 'aborted', 'saved')) {
            throw "VirtualBox smoke VM stopped before acceptance; state=$state."
        }
        Start-Sleep -Seconds 2
    }

    if (-not $bootAccepted) {
        throw 'VirtualBox smoke boot timed out before the first-run acceptance markers.'
    }

    Copy-Item -LiteralPath $serialPath -Destination $evidencePath -Force
    Write-Host "VirtualBox release smoke boot passed: $cloneName"
    Write-Host "Serial evidence: $evidencePath"
}
finally {
    if ($registered) {
        if ((Get-VmState -Name $cloneName) -eq 'running') {
            & VBoxManage controlvm $cloneName poweroff | Out-Null
            foreach ($attempt in 1..30) {
                Start-Sleep -Milliseconds 500
                if ((Get-VmState -Name $cloneName) -ne 'running') {
                    break
                }
            }
        }
        & VBoxManage unregistervm $cloneName --delete | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "Could not remove disposable VirtualBox clone '$cloneName'."
        }
    }
    if (Test-Path -LiteralPath $cloneBase) {
        $resolvedCloneBase = [System.IO.Path]::GetFullPath($cloneBase)
        $resolvedHardwareRoot = [System.IO.Path]::GetFullPath($hardwareRoot).TrimEnd('\') + '\'
        if (-not $resolvedCloneBase.StartsWith($resolvedHardwareRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to remove unexpected VirtualBox smoke path: $resolvedCloneBase"
        }
        Get-ChildItem -LiteralPath $resolvedCloneBase -Force -Recurse -ErrorAction SilentlyContinue |
            ForEach-Object { $_.Attributes = [System.IO.FileAttributes]::Normal }
        (Get-Item -LiteralPath $resolvedCloneBase -Force).Attributes = [System.IO.FileAttributes]::Normal
        Remove-Item -LiteralPath $resolvedCloneBase -Recurse -Force -ErrorAction SilentlyContinue
        if (Test-Path -LiteralPath $resolvedCloneBase) {
            Write-Warning "Could not remove disposable VirtualBox clone directory '$resolvedCloneBase'."
        }
    }
}
