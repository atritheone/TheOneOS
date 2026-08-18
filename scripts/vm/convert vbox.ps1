# convert vbox.ps1

$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$environmentRoot = Join-Path $projectRoot 'environment\software'
. (Join-Path $PSScriptRoot '..\common.ps1')
Set-Location -LiteralPath $environmentRoot

function Test-T1OSDirectReadAvailable {
    param([Parameter(Mandatory = $true)][string]$Path)

    $stream = $null
    try {
        # VBoxManage requires a normal shared-read handle. Windows shell/OneDrive
        # processes can occasionally hold the image with stricter sharing rules.
        $stream = [System.IO.File]::Open(
            $Path,
            [System.IO.FileMode]::Open,
            [System.IO.FileAccess]::Read,
            [System.IO.FileShare]::Read
        )
        return $true
    } catch [System.IO.IOException] {
        return $false
    } finally {
        if ($null -ne $stream) {
            $stream.Dispose()
        }
    }
}

function Copy-T1OSRawImageSnapshot {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination
    )

    $sourceInfoBefore = Get-Item -LiteralPath $Source
    $sourceStream = $null
    $destinationStream = $null

    try {
        $sourceShare = [System.IO.FileShare]::ReadWrite -bor [System.IO.FileShare]::Delete
        $sourceStream = [System.IO.File]::Open(
            $Source,
            [System.IO.FileMode]::Open,
            [System.IO.FileAccess]::Read,
            $sourceShare
        )
        $destinationStream = [System.IO.File]::Open(
            $Destination,
            [System.IO.FileMode]::CreateNew,
            [System.IO.FileAccess]::Write,
            [System.IO.FileShare]::None
        )

        $buffer = New-Object byte[] (8MB)
        while (($bytesRead = $sourceStream.Read($buffer, 0, $buffer.Length)) -gt 0) {
            $destinationStream.Write($buffer, 0, $bytesRead)
        }
        $destinationStream.Flush($true)
    } finally {
        if ($null -ne $destinationStream) {
            $destinationStream.Dispose()
        }
        if ($null -ne $sourceStream) {
            $sourceStream.Dispose()
        }
    }

    $sourceInfoAfter = Get-Item -LiteralPath $Source
    $snapshotInfo = Get-Item -LiteralPath $Destination
    if (
        $sourceInfoBefore.Length -ne $sourceInfoAfter.Length -or
        $sourceInfoBefore.LastWriteTimeUtc.Ticks -ne $sourceInfoAfter.LastWriteTimeUtc.Ticks -or
        $snapshotInfo.Length -ne $sourceInfoAfter.Length
    ) {
        throw 'storage.img changed while its temporary snapshot was being created. conversion has been stopped.'
    }
}

Write-Host 'checking if t1fs is mounted in wsl...'

if (Test-T1OSDiskMounted) {
    Write-Host 't1fs appears to be mounted. unmount from wsl before converting it.'
    exit 1
}

Write-Host 't1fs is not mounted.'

$imgPath = Join-Path $environmentRoot 'storage.img'
$vdiPath = Join-Path $environmentRoot 't1os-root.vdi'
$vboxDefault = 'C:\Program Files\Oracle\VirtualBox\VBoxManage.exe'
$vboxCommand = Get-Command 'VBoxManage.exe' -ErrorAction SilentlyContinue

if ($null -ne $vboxCommand) {
    $vboxManagePath = $vboxCommand.Source
} elseif (Test-Path -LiteralPath $vboxDefault -PathType Leaf) {
    $vboxManagePath = $vboxDefault
} else {
    Write-Host 'vboxmanage.exe was not found in PATH or at the default VirtualBox installation path.'
    exit 1
}

Write-Host "checking for storage.img at $imgPath"

if (-not (Test-Path -LiteralPath $imgPath -PathType Leaf)) {
    Write-Host 'storage.img was not found in the environment folder.'
    exit 1
}

if (Test-Path -LiteralPath $vdiPath -PathType Leaf) {
    $mediumInfo = @(& $vboxManagePath showmediuminfo disk $vdiPath 2>&1)
    $mediumInfoExitCode = $LASTEXITCODE
    if ($mediumInfoExitCode -eq 0) {
        $mediumInfoText = ($mediumInfo | ForEach-Object { $_.ToString() }) -join "`n"
        if ($mediumInfoText -match '(?im)^In use by VMs:\s*\S') {
            Write-Host 't1os-root.vdi is attached to a registered VM. Run scripts/vm/build vbox.ps1 so VirtualBox can unregister the old disk before conversion.'
            exit 1
        }
    }
}

try {
    Assert-T1OSFilesystemHealthy -ImagePath $imgPath -Operation 'converting it for VirtualBox'
}
catch {
    Write-Host $_.Exception.Message
    exit 1
}

$temporaryRoot = Join-Path ([System.IO.Path]::GetTempPath()) 'T1OS Command Centre'
New-Item -ItemType Directory -Path $temporaryRoot -Force | Out-Null
$temporarySource = $null
$temporaryVdi = Join-Path $temporaryRoot ("t1os-root-{0}.vdi" -f [guid]::NewGuid().ToString('N'))
$conversionSource = $imgPath
$exitCode = 1

try {
    if (-not (Test-T1OSDirectReadAvailable -Path $imgPath)) {
        $temporarySource = Join-Path $temporaryRoot ("storage-{0}.img" -f [guid]::NewGuid().ToString('N'))
        Write-Host 'storage.img is held by a Windows background process. creating an unlocked temporary snapshot...'
        Copy-T1OSRawImageSnapshot -Source $imgPath -Destination $temporarySource
        $conversionSource = $temporarySource
        Write-Host 'temporary snapshot created.'
    }

    Write-Host 'converting storage.img to t1os-root.vdi with vboxmanage...'
    & $vboxManagePath convertfromraw $conversionSource $temporaryVdi --format VDI
    $conversionExitCode = $LASTEXITCODE

    if ($conversionExitCode -ne 0) {
        throw "conversion failed with exit code $conversionExitCode."
    }

    if (Test-Path -LiteralPath $vdiPath -PathType Leaf) {
        Write-Host 'conversion succeeded. replacing the existing t1os-root.vdi...'
        Install-T1OSReplacementFile -SourcePath $temporaryVdi -DestinationPath $vdiPath
    }
    else {
        Move-Item -LiteralPath $temporaryVdi -Destination $vdiPath
    }
    $temporaryVdi = $null
    Write-Host 'conversion complete. created:'
    Write-Host "  $vdiPath"
    $exitCode = 0
} catch {
    Write-Host $_.Exception.Message
    $exitCode = 1
} finally {
    if ($null -ne $temporarySource -and (Test-Path -LiteralPath $temporarySource)) {
        Remove-Item -LiteralPath $temporarySource -Force -ErrorAction SilentlyContinue
    }
    if ($null -ne $temporaryVdi -and (Test-Path -LiteralPath $temporaryVdi)) {
        Remove-Item -LiteralPath $temporaryVdi -Force -ErrorAction SilentlyContinue
    }
}

exit $exitCode
