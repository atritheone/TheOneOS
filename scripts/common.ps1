function Get-T1OSCurrentVersion {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$ProjectRoot,

        [string]$Version
    )

    if ([string]::IsNullOrWhiteSpace($Version)) {
        $versionFile = Join-Path $ProjectRoot 'current_version.txt'
        $legacyVersionFile = Join-Path $ProjectRoot 'current-version.txt'
        if (-not (Test-Path -LiteralPath $versionFile -PathType Leaf) -and
            (Test-Path -LiteralPath $legacyVersionFile -PathType Leaf)) {
            Move-Item -LiteralPath $legacyVersionFile -Destination $versionFile
        }

        if (-not (Test-Path -LiteralPath $versionFile -PathType Leaf)) {
            throw "Current version file not found: $versionFile"
        }

        $Version = Get-Content -LiteralPath $versionFile -Raw
    }

    $Version = $Version.Trim()
    if ($Version -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$') {
        throw "Invalid current version '$Version'. Use letters, numbers, dots, underscores, or hyphens."
    }

    return $Version
}

function Test-T1OSDiskMounted {
    [CmdletBinding()]
    param(
        [string]$MountPoint = '/mnt/t1fs'
    )

    $null = & wsl.exe -u root --exec nsenter -t 1 -m -- mountpoint -q $MountPoint
    $mountExitCode = $LASTEXITCODE

    if ($mountExitCode -eq 0) {
        return $true
    }
    if ($mountExitCode -in @(1, 32)) {
        return $false
    }

    throw "Could not verify the WSL host mount status for $MountPoint (exit code $mountExitCode)."
}

function Get-T1OSUsbDriveTarget {
    [CmdletBinding()]
    param()

    $requiredRelativePaths = @(
        'boot',
        'the one',
        'the one\build',
        'the one\master',
        'the one\settings\runtime paths.json',
        'the one\resources\t1os-drive.ico',
        'autorun.inf'
    )
    $candidates = @(
        Get-Volume -ErrorAction Stop |
            Where-Object {
                $_.DriveLetter -and (
                    [string]$_.DriveLetter -ceq 'D' -or
                    ([string]$_.FileSystemLabel).StartsWith('T1OS', [StringComparison]::OrdinalIgnoreCase)
                )
            } |
            ForEach-Object {
                $volume = $_
                $letter = ([string]$volume.DriveLetter).ToUpperInvariant()
                $root = "$letter`:\"
                $partition = Get-Partition -DriveLetter $letter -ErrorAction Stop
                $disk = $partition | Get-Disk -ErrorAction Stop
                if (
                    [string]$disk.BusType -cne 'USB' -or $disk.IsBoot -or $disk.IsSystem -or
                    $disk.IsReadOnly -or [string]$volume.FileSystemType -cne 'NTFS' -or
                    [string]$volume.HealthStatus -cne 'Healthy'
                ) { return }
                foreach ($relativePath in $requiredRelativePaths) {
                    if (-not (Test-Path -LiteralPath (Join-Path $root $relativePath))) { return }
                }
                $autorun = Get-Content -LiteralPath (Join-Path $root 'autorun.inf') -Raw
                if (
                    $autorun -notmatch '(?im)^\s*Label=T1OS(?:\s|$)' -or
                    $autorun -notmatch '(?im)^\s*Icon="the one\\resources\\t1os-drive\.ico"\s*$'
                ) { return }
                [pscustomobject]@{
                    DriveLetter = $letter
                    Root = $root
                    DriveSource = "$letter`:"
                    Label = ([string]$volume.FileSystemLabel).Trim()
                    DiskNumber = [int]$disk.Number
                    SerialNumber = ([string]$disk.SerialNumber).Trim()
                    Model = ([string]$disk.FriendlyName).Trim()
                }
            }
    )
    $preferred = @($candidates | Where-Object DriveLetter -CEQ 'D')
    if ($preferred.Count -eq 1) { return $preferred[0] }
    if ($candidates.Count -eq 1) { return $candidates[0] }
    if ($candidates.Count -eq 0) {
        throw 'No unambiguous healthy NTFS T1OS USB drive was found.'
    }
    throw 'More than one T1OS USB drive was found. Keep only the intended target connected.'
}

function Assert-T1OSFilesystemHealthy {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$ImagePath,

        [string]$Operation = 'using storage.img'
    )

    if (-not (Test-Path -LiteralPath $ImagePath -PathType Leaf)) {
        throw "Disk image not found: $ImagePath"
    }

    if (Test-T1OSDiskMounted) {
        throw "The disk is mounted. Unmount it before $Operation."
    }

    $wslImageOutput = & wsl.exe --exec wslpath -a $ImagePath
    if ($LASTEXITCODE -ne 0 -or -not $wslImageOutput) {
        throw "Could not translate the disk image path for WSL: $ImagePath"
    }

    $wslImagePath = ([string]($wslImageOutput | Select-Object -First 1)).Trim()
    if ([string]::IsNullOrWhiteSpace($wslImagePath)) {
        throw 'WSL returned an empty disk image path.'
    }

    Write-Host "Validating the ext4 filesystem before $Operation..."
    # Windows PowerShell wraps native stderr records as PowerShell errors.
    # e2fsck writes its normal banner and progress there, so a caller using
    # ErrorActionPreference=Stop must not fail merely because output arrived
    # on fd 2. Capture both streams and judge the documented process status.
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $checkOutput = @(
            & wsl.exe -u root --exec /usr/sbin/e2fsck -f -n $wslImagePath 2>&1
        )
        $checkExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }

    foreach ($line in $checkOutput) {
        Write-Host $line.ToString()
    }

    if ($checkExitCode -ne 0) {
        throw "storage.img failed its read-only filesystem check (e2fsck exit code $checkExitCode). Run scripts/deployment/clean disk.ps1 before $Operation."
    }
}

function Get-T1OSFilesystemUuid {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$ImagePath
    )

    if (-not (Test-Path -LiteralPath $ImagePath -PathType Leaf)) {
        throw "Disk image not found: $ImagePath"
    }

    $wslImageOutput = & wsl.exe --exec wslpath -a $ImagePath
    if ($LASTEXITCODE -ne 0 -or -not $wslImageOutput) {
        throw "Could not translate the disk image path for WSL: $ImagePath"
    }

    $wslImagePath = ([string]($wslImageOutput | Select-Object -First 1)).Trim()
    if ([string]::IsNullOrWhiteSpace($wslImagePath)) {
        throw 'WSL returned an empty disk image path.'
    }

    $previousErrorActionPreference = $ErrorActionPreference
    try {
        # dumpe2fs writes its banner to stderr even when the operation succeeds.
        $ErrorActionPreference = 'Continue'
        $headerOutput = @(
            & wsl.exe -u root --exec /usr/sbin/dumpe2fs -h $wslImagePath 2>&1
        )
        $headerExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }

    if ($headerExitCode -ne 0) {
        throw "Could not read the filesystem UUID from storage.img (dumpe2fs exit code $headerExitCode)."
    }

    $headerText = ($headerOutput | ForEach-Object { $_.ToString() }) -join "`n"
    $uuidMatch = [regex]::Match(
        $headerText,
        '(?im)^Filesystem UUID:\s*(?<uuid>[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})\s*$'
    )
    if (-not $uuidMatch.Success) {
        throw 'dumpe2fs did not report a valid filesystem UUID for storage.img.'
    }

    return $uuidMatch.Groups['uuid'].Value.ToLowerInvariant()
}

function Set-T1OSBootRootIdentity {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$ImagePath,

        [Parameter(Mandatory)]
        [string]$GrubConfigPath
    )

    if (-not (Test-Path -LiteralPath $GrubConfigPath -PathType Leaf)) {
        throw "GRUB configuration not found: $GrubConfigPath"
    }

    $filesystemUuid = Get-T1OSFilesystemUuid -ImagePath $ImagePath
    $configText = [System.IO.File]::ReadAllText($GrubConfigPath)
    $rootPattern = 'root=UUID=(?:[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}|@T1OS_ROOT_UUID@)'
    if (-not [regex]::IsMatch($configText, $rootPattern)) {
        throw "GRUB configuration does not contain a replaceable root=UUID entry: $GrubConfigPath"
    }

    $updatedText = [regex]::Replace($configText, $rootPattern, "root=UUID=$filesystemUuid")
    if ($updatedText -ne $configText) {
        [System.IO.File]::WriteAllText($GrubConfigPath, $updatedText)
        Write-Host "updated the VM boot root UUID to $filesystemUuid."
    }
    else {
        Write-Host "verified the VM boot root UUID: $filesystemUuid."
    }

    return $filesystemUuid
}

function Assert-T1OSBootRootIdentity {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$ImagePath,

        [Parameter(Mandatory)]
        [string]$GrubConfigPath
    )

    if (-not (Test-Path -LiteralPath $GrubConfigPath -PathType Leaf)) {
        throw "GRUB configuration not found: $GrubConfigPath"
    }

    $filesystemUuid = Get-T1OSFilesystemUuid -ImagePath $ImagePath
    $configText = [System.IO.File]::ReadAllText($GrubConfigPath)
    $configuredUuids = @(
        [regex]::Matches(
            $configText,
            'root=UUID=(?<uuid>[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})'
        ) | ForEach-Object { $_.Groups['uuid'].Value.ToLowerInvariant() } | Select-Object -Unique
    )

    if ($configuredUuids.Count -eq 0) {
        throw "GRUB configuration does not contain a concrete root=UUID entry: $GrubConfigPath"
    }
    if ($configuredUuids.Count -ne 1 -or $configuredUuids[0] -ne $filesystemUuid) {
        throw "GRUB root UUID does not match storage.img. configured=$($configuredUuids -join ',') filesystem=$filesystemUuid. Rebuild the VM boot ISO."
    }

    return $filesystemUuid
}

function Assert-T1OSArtifactCurrent {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$ArtifactPath,

        [Parameter(Mandatory)]
        [string[]]$InputPath,

        [string]$RebuildCommand = 'rebuild the VM'
    )

    if (-not (Test-Path -LiteralPath $ArtifactPath -PathType Leaf)) {
        throw "VM artifact not found: $ArtifactPath. Run $RebuildCommand."
    }

    $artifact = Get-Item -LiteralPath $ArtifactPath
    foreach ($path in $InputPath) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "VM build input not found: $path"
        }

        $input = Get-Item -LiteralPath $path
        if ($input.LastWriteTimeUtc -gt $artifact.LastWriteTimeUtc) {
            throw "VM artifact is stale: $ArtifactPath is older than $path. Run $RebuildCommand."
        }
    }
}

function Install-T1OSReplacementFile {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$SourcePath,

        [Parameter(Mandatory)]
        [string]$DestinationPath
    )

    if (-not (Test-Path -LiteralPath $SourcePath -PathType Leaf)) {
        throw "Replacement file not found: $SourcePath"
    }

    $destinationDirectory = Split-Path -Path $DestinationPath -Parent
    $sourceFullPath = [System.IO.Path]::GetFullPath($SourcePath)
    $destinationFullPath = [System.IO.Path]::GetFullPath($DestinationPath)
    $replacementPath = $sourceFullPath
    $stagedForVolume = $false

    if (-not [string]::Equals(
        [System.IO.Path]::GetPathRoot($sourceFullPath),
        [System.IO.Path]::GetPathRoot($destinationFullPath),
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        $replacementPath = Join-Path $destinationDirectory (
            '.{0}.{1}.replacement' -f [System.IO.Path]::GetFileName($DestinationPath), [guid]::NewGuid().ToString('N')
        )
        Copy-Item -LiteralPath $sourceFullPath -Destination $replacementPath
        $stagedForVolume = $true
    }

    if (-not (Test-Path -LiteralPath $destinationFullPath -PathType Leaf)) {
        Move-Item -LiteralPath $replacementPath -Destination $destinationFullPath
        if ($stagedForVolume) {
            Remove-Item -LiteralPath $sourceFullPath -Force
        }
        return
    }

    $backupPath = Join-Path $destinationDirectory (
        '.{0}.{1}.backup' -f [System.IO.Path]::GetFileName($DestinationPath), [guid]::NewGuid().ToString('N')
    )

    try {
        # File.Replace keeps the previous artifact at BackupPath until the new
        # file is installed successfully. A cross-volume source is staged next
        # to the destination first so the replacement remains atomic.
        [System.IO.File]::Replace($replacementPath, $destinationFullPath, $backupPath, $true)
    }
    catch {
        if (-not (Test-Path -LiteralPath $destinationFullPath -PathType Leaf) -and
            (Test-Path -LiteralPath $backupPath -PathType Leaf)) {
            Move-Item -LiteralPath $backupPath -Destination $destinationFullPath
        }
        if ($stagedForVolume -and (Test-Path -LiteralPath $replacementPath -PathType Leaf)) {
            Remove-Item -LiteralPath $replacementPath -Force -ErrorAction SilentlyContinue
        }
        throw
    }

    if ($stagedForVolume -and (Test-Path -LiteralPath $sourceFullPath -PathType Leaf)) {
        Remove-Item -LiteralPath $sourceFullPath -Force
    }
    if (Test-Path -LiteralPath $backupPath -PathType Leaf) {
        try {
            Remove-Item -LiteralPath $backupPath -Force -ErrorAction Stop
        }
        catch {
            Write-Warning "The replacement succeeded, but its old backup could not be removed: $backupPath"
        }
    }
}
