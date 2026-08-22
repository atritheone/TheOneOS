[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param(
    [switch]$ValidateTargetOnly,
    [switch]$BootFilesOnly,
    [switch]$Elevated,
    [string]$DiagnosticPath = ''
)

$ErrorActionPreference = 'Stop'
trap {
    if ($Elevated -and -not [string]::IsNullOrWhiteSpace($DiagnosticPath)) {
        try {
            [IO.File]::WriteAllText(
                $DiagnosticPath,
                ($_ | Out-String),
                [Text.UTF8Encoding]::new($false)
            )
        }
        catch {
            # Preserve the original update failure if diagnostics cannot be written.
        }
        exit 1
    }
    break
}
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$kernelSource = Join-Path $projectRoot 'environment\hardware\boot\vmlinuz-hardware'
$initramfsSource = Join-Path $projectRoot 'environment\hardware\boot\initramfs-hardware'
$modulesSource = Join-Path $projectRoot 'environment\hardware\modules.tar.zst'
$releaseSource = Join-Path $projectRoot 'environment\hardware\kernel-release.txt'
$kernelProvenanceSource = Join-Path $projectRoot 'environment\hardware\boot\kernel-build-inputs.json'
$initramfsProvenanceSource = Join-Path $projectRoot 'environment\hardware\boot\initramfs-build-inputs.json'
$compatibilitySource = Join-Path $projectRoot 'source\drivers\settings\desktop compatibility.json'
# Transaction paths are internal implementation details. Generate the suffix
# for every elevated run so deployment never depends on a developer manually
# changing a release label left in this script.
$updateName = '{0:yyyyMMdd-HHmmss}-{1}' -f @(
    [DateTime]::UtcNow,
    [Guid]::NewGuid().ToString('N').Substring(0, 12)
)

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator
    )
}

function Assert-T1OSArtifactProvenance {
    param(
        [Parameter(Mandatory)][string]$ManifestPath,
        [Parameter(Mandatory)][string]$ExpectedComponent
    )

    try {
        $manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
    }
    catch {
        throw "Hardware artifact provenance is unreadable: $ManifestPath"
    }
    if (
        [int]$manifest.format -ne 1 -or
        [string]$manifest.component -cne $ExpectedComponent
    ) {
        throw "Hardware artifact provenance has the wrong identity: $ManifestPath"
    }
    $records = @($manifest.inputs) + @($manifest.outputs)
    if ($records.Count -eq 0) {
        throw "Hardware artifact provenance is empty: $ManifestPath"
    }
    $rootPrefix = $projectRoot.TrimEnd('\') + '\'
    foreach ($record in $records) {
        $relative = [string]$record.path
        $expectedHash = [string]$record.sha256
        if (
            [string]::IsNullOrWhiteSpace($relative) -or
            $relative.StartsWith('/', [StringComparison]::Ordinal) -or
            $relative.Contains('..') -or
            $expectedHash -cnotmatch '^[0-9a-f]{64}$'
        ) {
            throw "Hardware artifact provenance contains an unsafe record: $ManifestPath"
        }
        $candidate = [IO.Path]::GetFullPath(
            (Join-Path $projectRoot $relative.Replace('/', '\'))
        )
        if (-not $candidate.StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Hardware artifact provenance escaped the project: $relative"
        }
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            throw "Hardware artifact provenance input is missing: $relative"
        }
        $actualHash = (
            Get-FileHash -Algorithm SHA256 -LiteralPath $candidate
        ).Hash.ToLowerInvariant()
        if ($actualHash -cne $expectedHash) {
            throw (
                "Hardware artifact is stale; rebuild before USB deployment: " +
                "$relative expected=$expectedHash actual=$actualHash"
            )
        }
    }
}

function Get-T1OSUsbTarget {
    $volume = Get-Volume -DriveLetter D -ErrorAction Stop
    $partition = Get-Partition -DriveLetter D -ErrorAction Stop
    $disk = $partition | Get-Disk -ErrorAction Stop
    $efi = @(
        Get-Partition -DiskNumber $disk.Number -ErrorAction Stop |
            Where-Object {
                $_.GptType -ceq '{c12a7328-f81f-11d2-ba4b-00a0c93ec93b}' -and
                $_.Size -eq 536870912
            }
    )

    $rootHealthAccepted = if ($BootFilesOnly) {
        [string]$volume.HealthStatus -in @('Healthy', 'Warning')
    }
    else {
        [string]$volume.HealthStatus -ceq 'Healthy'
    }

    if (
        [string]$disk.BusType -cne 'USB' -or
        $disk.IsBoot -or
        $disk.IsSystem -or
        $disk.IsReadOnly -or
        [string]$volume.FileSystemType -cne 'NTFS' -or
        -not $rootHealthAccepted -or
        -not ([string]$volume.FileSystemLabel).StartsWith(
            'T1OS',
            [StringComparison]::OrdinalIgnoreCase
        ) -or
        $efi.Count -ne 1 -or
        -not (Test-Path -LiteralPath 'D:\the one\drivers\modules') -or
        -not (Test-Path -LiteralPath 'D:\autorun.inf')
    ) {
        throw 'D: is not the exact healthy T1OS GPT USB target.'
    }

    return [pscustomobject]@{
        Disk = $disk
        Volume = $volume
        Efi = $efi[0]
    }
}

foreach ($path in @(
    $kernelSource,
    $initramfsSource,
    $modulesSource,
    $releaseSource,
    $kernelProvenanceSource,
    $initramfsProvenanceSource,
    $compatibilitySource
)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Required hardware update input is absent: $path"
    }
}

Assert-T1OSArtifactProvenance `
    -ManifestPath $kernelProvenanceSource `
    -ExpectedComponent 't1os-hardware-kernel'
Assert-T1OSArtifactProvenance `
    -ManifestPath $initramfsProvenanceSource `
    -ExpectedComponent 't1os-hardware-initramfs'

$compatibility = Get-Content -LiteralPath $compatibilitySource -Raw |
    ConvertFrom-Json
if ($compatibility.boot.secure_boot -ne $false) {
    throw (
        'This scoped standalone-kernel updater is only valid for the ' +
        'non-Secure-Boot T1OS USB layout.'
    )
}

$release = (Get-Content -LiteralPath $releaseSource -Raw).Trim()
if ($release -cne '7.1.5-t1os-hardware') {
    throw "Unexpected hardware kernel release: $release"
}

$target = Get-T1OSUsbTarget
Write-Host (
    "T1OS hardware target: D: '$($target.Volume.FileSystemLabel)' on USB " +
    "disk $($target.Disk.Number) $($target.Disk.FriendlyName)"
)

if ($ValidateTargetOnly) {
    Write-Host 'Scoped hardware boot-file USB target validation passed.'
    exit 0
}

if (-not (Test-IsAdministrator)) {
    if ($Elevated) {
        throw 'The elevated hardware update process does not have administrator rights.'
    }
    $hostExecutable = (Get-Process -Id $PID).Path
    $bootFilesOnlyArgument = if ($BootFilesOnly) { ' -BootFilesOnly' } else { '' }
    $diagnosticPath = Join-Path (
        [IO.Path]::GetTempPath()
    ) "t1os-hardware-update-$([guid]::NewGuid().ToString('N')).log"
    $arguments = (
        '-NoProfile -ExecutionPolicy Bypass -File "' +
        $PSCommandPath.Replace('"', '""') +
        '" -Elevated' + $bootFilesOnlyArgument +
        ' -DiagnosticPath "' + $diagnosticPath.Replace('"', '""') +
        '" -Confirm:$false'
    )
    Write-Host (
        'Administrator rights are required only to mount and update the ' +
        'hidden T1OS EFI partition. Accept the Windows UAC prompt.'
    )
    $process = Start-Process -FilePath $hostExecutable -Verb RunAs `
        -ArgumentList $arguments -Wait -PassThru
    if ($process.ExitCode -ne 0) {
        $detail = if (Test-Path -LiteralPath $diagnosticPath -PathType Leaf) {
            (Get-Content -LiteralPath $diagnosticPath -Raw).Trim()
        }
        else {
            'The elevated child did not produce a diagnostic record.'
        }
        if (Test-Path -LiteralPath $diagnosticPath) {
            Remove-Item -LiteralPath $diagnosticPath -Force
        }
        throw (
            "Elevated T1OS hardware update failed with exit code " +
            "$($process.ExitCode): $detail"
        )
    }
    if (Test-Path -LiteralPath $diagnosticPath) {
        Remove-Item -LiteralPath $diagnosticPath -Force
    }
    exit 0
}

$installAction = if ($BootFilesOnly) {
    'Install the rebuilt hardware kernel and repair-capable initramfs only'
}
else {
    'Install the rebuilt hardware kernel, initramfs, and matching module tree'
}
if (-not $PSCmdlet.ShouldProcess(
    "USB disk $($target.Disk.Number), D: and its EFI partition",
    $installAction
)) {
    Write-Host 'Scoped hardware boot-file USB update was not executed.'
    exit 0
}

$completedModuleStage = (
    'D:\the one\drivers\.t1os-modules-update-20260812-brick-console-pty'
)
if (Test-Path -LiteralPath $completedModuleStage) {
    $stageItem = Get-Item -LiteralPath $completedModuleStage -Force
    $expectedStage = [IO.Path]::GetFullPath($completedModuleStage)
    $stageFiles = @(
        Get-ChildItem -LiteralPath $completedModuleStage -Recurse -Force -File
    )
    if (
        $stageItem.FullName -cne $expectedStage -or
        -not $stageItem.PSIsContainer -or
        $stageItem.Attributes.HasFlag([IO.FileAttributes]::ReparsePoint) -or
        $stageFiles.Count -ne 0
    ) {
        throw "Refusing unexpected completed module stage: $completedModuleStage"
    }
    Remove-Item -LiteralPath $completedModuleStage -Recurse -Force
    Write-Host "Removed empty completed module stage: $completedModuleStage"
}

function ConvertTo-WslPath {
    param([Parameter(Mandatory)][string]$WindowsPath)

    $output = & wsl.exe -d Ubuntu --exec wslpath -a $WindowsPath
    if ($LASTEXITCODE -ne 0 -or -not $output) {
        throw "Could not translate path for WSL: $WindowsPath"
    }
    return ([string]($output | Select-Object -First 1)).Trim()
}

$moduleSwap = @'
set -euo pipefail
archive=$1
update_name=$2
mount_point=/mnt/t1-hardware-update-usb
mkdir -p -- "$mount_point"
if mountpoint -q "$mount_point"; then
    echo 'Hardware update mount point is already in use.' >&2
    exit 1
fi
mount -t drvfs D: "$mount_point" -o metadata,uid=0,gid=0,umask=022
cleanup() {
    sync
    umount "$mount_point"
}
trap cleanup EXIT
drivers="$mount_point/the one/drivers"
[ "$(realpath -e -- "$drivers")" = "$drivers" ]
stage="$drivers/.t1os-modules-update-$update_name"
backup="$drivers/modules.previous-$update_name"
[ -d "$stage" ] && [ ! -L "$stage" ]
[ ! -e "$backup" ] && [ ! -L "$backup" ]
[ -d "$drivers/modules" ] && [ ! -L "$drivers/modules" ]
[ -z "$(find "$stage" -mindepth 1 -print -quit)" ]
tar --zstd -xf "$archive" -C "$stage"
new="$stage/the one/drivers/modules"
[ -d "$new" ] && [ ! -L "$new" ]
(cd "$new" && sha256sum -c module-manifest.sha256 >/dev/null)
mv -- "$drivers/modules" "$backup"
if ! mv -- "$new" "$drivers/modules"; then
    mv -- "$backup" "$drivers/modules"
    exit 1
fi
if ! (cd "$drivers/modules" && sha256sum -c module-manifest.sha256 >/dev/null); then
    mv -- "$drivers/modules" "$new.failed"
    mv -- "$backup" "$drivers/modules"
    exit 1
fi
sync
sha256sum "$drivers/modules/module-manifest.sha256"
'@

$moduleRollback = @'
set -euo pipefail
update_name=$1
mount_point=/mnt/t1-hardware-update-usb
mkdir -p -- "$mount_point"
mount -t drvfs D: "$mount_point" -o metadata,uid=0,gid=0,umask=022
cleanup() {
    sync
    umount "$mount_point"
}
trap cleanup EXIT
drivers="$mount_point/the one/drivers"
backup="$drivers/modules.previous-$update_name"
failed="$drivers/modules.failed-$update_name"
[ -d "$backup" ] && [ ! -L "$backup" ]
[ -d "$drivers/modules" ] && [ ! -L "$drivers/modules" ]
mv -- "$drivers/modules" "$failed"
mv -- "$backup" "$drivers/modules"
sync
'@

$modulesSwapped = $false
$wslModules = $null
if (-not $BootFilesOnly) {
    $wslModules = ConvertTo-WslPath -WindowsPath $modulesSource
    $moduleStageWindows = (
        "D:\the one\drivers\.t1os-modules-update-$updateName"
    )
    $moduleFailedWindows = (
        "D:\the one\drivers\modules.failed-$updateName"
    )
    $legacyFailedUpdatePaths = @(
        'D:\the one\drivers\.t1os-modules-update-20260812-roothealth-readable-logs',
        'D:\the one\drivers\modules.failed-20260812-roothealth-readable-logs',
        'D:\the one\drivers\.t1os-modules-update-20260813-roothealth-advisory-mount-policy',
        'D:\the one\drivers\modules.failed-20260813-roothealth-advisory-mount-policy'
    )
    foreach ($retryPath in @(
        $moduleStageWindows,
        $moduleFailedWindows
    ) + $legacyFailedUpdatePaths) {
        $expectedRetryPath = [System.IO.Path]::GetFullPath($retryPath)
        if (-not (Test-Path -LiteralPath $retryPath)) {
            continue
        }
        $actualRetryPath = (
            Get-Item -LiteralPath $retryPath -Force
        ).FullName
        if (
            $actualRetryPath -cne $expectedRetryPath -or
            -not (Get-Item -LiteralPath $retryPath -Force).PSIsContainer
        ) {
            throw "Refusing unexpected failed module update path: $actualRetryPath"
        }
        Remove-Item -LiteralPath $retryPath -Recurse -Force
    }
    New-Item -ItemType Directory -Path $moduleStageWindows | Out-Null
    & fsutil.exe file setCaseSensitiveInfo $moduleStageWindows enable | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw 'Could not enable case-sensitive names on the module staging directory.'
    }
    $caseState = & fsutil.exe file queryCaseSensitiveInfo $moduleStageWindows
    if (
        $LASTEXITCODE -ne 0 -or
        ([string]$caseState) -notmatch '(?i)\bis enabled\b'
    ) {
        throw 'The module staging directory is not case-sensitive.'
    }
}

$efiAccessPath = $null
$kernelSwapped = $false
$initramfsSwapped = $false
$kernelBackupCreated = $false
$initramfsBackupCreated = $false
$kernelDestination = $null
$initramfsDestination = $null
$kernelTemporary = $null
$initramfsTemporary = $null
$kernelBackup = $null
$initramfsBackup = $null
$kernelFailed = $null
$initramfsFailed = $null

try {
    if (-not $BootFilesOnly) {
        & wsl.exe -d Ubuntu -u root --exec bash -c $moduleSwap -- `
            $wslModules $updateName
        if ($LASTEXITCODE -ne 0) {
            throw "The matching USB module-tree switch failed (exit code $LASTEXITCODE)."
        }
        $modulesSwapped = $true
    }

    $usedLetters = @(
        Get-Volume -ErrorAction Stop |
            Where-Object DriveLetter |
            ForEach-Object { ([string]$_.DriveLetter).ToUpperInvariant() }
    )
    $efiLetter = @('Z', 'Y', 'X', 'W', 'V') |
        Where-Object { $_ -notin $usedLetters } |
        Select-Object -First 1
    if (-not $efiLetter) {
        throw 'No temporary drive letter is available for the T1OS EFI partition.'
    }
    $efiAccessPath = "$efiLetter`:\"
    Add-PartitionAccessPath -DiskNumber $target.Disk.Number `
        -PartitionNumber $target.Efi.PartitionNumber `
        -AccessPath $efiAccessPath

    $efiRoot = [System.IO.Path]::GetFullPath($efiAccessPath)
    $bootDirectory = Join-Path $efiRoot 'boot'
    $kernelDestination = Join-Path $bootDirectory 'vmlinuz-hardware'
    $initramfsDestination = Join-Path $bootDirectory 'initramfs-hardware'
    $kernelTemporary = Join-Path (
        $bootDirectory
    ) ".vmlinuz-hardware.t1os-$updateName"
    $initramfsTemporary = Join-Path (
        $bootDirectory
    ) ".initramfs-hardware.t1os-$updateName"
    $kernelBackup = Join-Path (
        $bootDirectory
    ) "vmlinuz-hardware.previous-$updateName"
    $initramfsBackup = Join-Path (
        $bootDirectory
    ) "initramfs-hardware.previous-$updateName"
    $kernelFailed = Join-Path (
        $bootDirectory
    ) "vmlinuz-hardware.failed-$updateName"
    $initramfsFailed = Join-Path (
        $bootDirectory
    ) "initramfs-hardware.failed-$updateName"
    foreach ($requiredPath in @(
        $bootDirectory,
        $initramfsDestination,
        (Join-Path $efiRoot 'EFI\BOOT\BOOTX64.EFI'),
        $kernelDestination
    )) {
        if (-not (Test-Path -LiteralPath $requiredPath)) {
            throw "The mounted T1OS EFI layout is incomplete: $requiredPath"
        }
    }
    $stagingBytes = (Get-Item -LiteralPath $kernelSource).Length +
        (Get-Item -LiteralPath $initramfsSource).Length + 4MB
    $efiFreeBytes = (Get-Volume -DriveLetter $efiLetter -ErrorAction Stop).SizeRemaining
    if ($efiFreeBytes -lt $stagingBytes) {
        # Transactional updates retain one rollback pair. Older complete pairs
        # only consume the small EFI filesystem and eventually prevent the
        # next atomic staging copy. Refuse unpaired or unexpectedly named files
        # and prune only complete T1OS-generated rollback generations.
        $kernelRollbacks = @{}
        $initramfsRollbacks = @{}
        foreach ($entry in Get-ChildItem -LiteralPath $bootDirectory -File -Force) {
            if ($entry.Name -match '^vmlinuz-hardware\.previous-(\d{8}-[A-Za-z0-9-]+)$') {
                $kernelRollbacks[$Matches[1]] = $entry.FullName
            }
            elseif ($entry.Name -match '^initramfs-hardware\.previous-(\d{8}-[A-Za-z0-9-]+)$') {
                $initramfsRollbacks[$Matches[1]] = $entry.FullName
            }
        }
        $rollbackSuffixes = @(
            @($kernelRollbacks.Keys) + @($initramfsRollbacks.Keys) |
                Sort-Object -Unique
        )
        foreach ($suffix in $rollbackSuffixes) {
            if (-not $kernelRollbacks.ContainsKey($suffix) -or
                -not $initramfsRollbacks.ContainsKey($suffix)) {
                throw "The EFI rollback generation $suffix is incomplete."
            }
        }
        $retainedRollback = $rollbackSuffixes |
            Sort-Object -Descending -Property {
                [Math]::Max(
                    (Get-Item -LiteralPath $kernelRollbacks[$_]).LastWriteTimeUtc.Ticks,
                    (Get-Item -LiteralPath $initramfsRollbacks[$_]).LastWriteTimeUtc.Ticks
                )
            } |
            Select-Object -First 1
        foreach ($suffix in $rollbackSuffixes) {
            if ($suffix -ceq $retainedRollback) {
                continue
            }
            Remove-Item -LiteralPath $kernelRollbacks[$suffix] -Force
            Remove-Item -LiteralPath $initramfsRollbacks[$suffix] -Force
            Write-Host "Pruned stale EFI rollback pair: $suffix"
        }
        $efiFreeBytes = (Get-Volume -DriveLetter $efiLetter -ErrorAction Stop).SizeRemaining
        if ($efiFreeBytes -lt $stagingBytes) {
            throw (
                "The EFI partition still lacks staging space after safe rollback pruning: " +
                "free=$efiFreeBytes required=$stagingBytes"
            )
        }
    }
    $kernelSourceHash = (
        Get-FileHash -Algorithm SHA256 -LiteralPath $kernelSource
    ).Hash.ToLowerInvariant()
    $initramfsSourceHash = (
        Get-FileHash -Algorithm SHA256 -LiteralPath $initramfsSource
    ).Hash.ToLowerInvariant()
    $currentKernelHash = (
        Get-FileHash -Algorithm SHA256 -LiteralPath $kernelDestination
    ).Hash.ToLowerInvariant()
    $currentInitramfsHash = (
        Get-FileHash -Algorithm SHA256 -LiteralPath $initramfsDestination
    ).Hash.ToLowerInvariant()
    $bootFilesAlreadyCurrent = (
        $currentKernelHash -ceq $kernelSourceHash -and
        $currentInitramfsHash -ceq $initramfsSourceHash
    )
    $kernelBackupExists = Test-Path -LiteralPath $kernelBackup
    $initramfsBackupExists = Test-Path -LiteralPath $initramfsBackup
    if (
        $bootFilesAlreadyCurrent -and
        $kernelBackupExists -ne $initramfsBackupExists
    ) {
        throw 'The retained EFI kernel and initramfs rollback pair is incomplete.'
    }
    $reservedPaths = @(
        $kernelTemporary,
        $initramfsTemporary,
        $kernelFailed,
        $initramfsFailed
    )
    if (-not $bootFilesAlreadyCurrent) {
        $reservedPaths += @($kernelBackup, $initramfsBackup)
    }
    foreach ($reservedPath in $reservedPaths) {
        if (Test-Path -LiteralPath $reservedPath) {
            throw (
                "A reserved kernel update path already exists: $reservedPath; " +
                "current-kernel=$currentKernelHash source-kernel=$kernelSourceHash " +
                "current-initramfs=$currentInitramfsHash " +
                "source-initramfs=$initramfsSourceHash"
            )
        }
    }

    if ($bootFilesAlreadyCurrent) {
        Write-Host 'EFI kernel and initramfs already match the rebuilt artifacts.'
    }
    else {
        Copy-Item -LiteralPath $kernelSource -Destination $kernelTemporary
        Copy-Item -LiteralPath $initramfsSource -Destination $initramfsTemporary
        $kernelTemporaryHash = (
            Get-FileHash -Algorithm SHA256 -LiteralPath $kernelTemporary
        ).Hash.ToLowerInvariant()
        $initramfsTemporaryHash = (
            Get-FileHash -Algorithm SHA256 -LiteralPath $initramfsTemporary
        ).Hash.ToLowerInvariant()
        if ($kernelSourceHash -cne $kernelTemporaryHash) {
            throw 'The staged EFI kernel hash differs from the rebuilt kernel.'
        }
        if ($initramfsSourceHash -cne $initramfsTemporaryHash) {
            throw 'The staged EFI initramfs hash differs from the rebuilt initramfs.'
        }

        Move-Item -LiteralPath $kernelDestination -Destination $kernelBackup
        $kernelBackupCreated = $true
        try {
            Move-Item -LiteralPath $initramfsDestination -Destination $initramfsBackup
            $initramfsBackupCreated = $true
            Move-Item -LiteralPath $kernelTemporary -Destination $kernelDestination
            $kernelSwapped = $true
            Move-Item -LiteralPath $initramfsTemporary -Destination $initramfsDestination
            $initramfsSwapped = $true
        }
        catch {
            throw
        }
    }

    $installedKernelHash = (
        Get-FileHash -Algorithm SHA256 -LiteralPath $kernelDestination
    ).Hash.ToLowerInvariant()
    $installedInitramfsHash = (
        Get-FileHash -Algorithm SHA256 -LiteralPath $initramfsDestination
    ).Hash.ToLowerInvariant()
    if ($installedKernelHash -cne $kernelSourceHash) {
        throw 'The installed EFI kernel failed SHA-256 verification.'
    }
    if ($installedInitramfsHash -cne $initramfsSourceHash) {
        throw 'The installed EFI initramfs failed SHA-256 verification.'
    }

    Write-Host "Installed kernel SHA-256: $installedKernelHash"
    Write-Host "Installed initramfs SHA-256: $installedInitramfsHash"
    Write-Host "Kernel release: $release"
    if (Test-Path -LiteralPath $kernelBackup) {
        Write-Host "Previous kernel retained: $kernelBackup"
        Write-Host "Previous initramfs retained: $initramfsBackup"
    }
    if (-not $BootFilesOnly) {
        Write-Host (
            "Previous module tree retained: D:\the one\drivers\" +
            "modules.previous-$updateName"
        )
    }
    Write-VolumeCache -DriveLetter $efiLetter -ErrorAction Stop
    $efiVolume = Get-Volume -DriveLetter $efiLetter -ErrorAction Stop
    if (
        [string]$efiVolume.HealthStatus -cne 'Healthy' -or
        [string]$efiVolume.OperationalStatus -cne 'OK'
    ) {
        Repair-Volume -DriveLetter $efiLetter -OfflineScanAndFix `
            -ErrorAction Stop | Out-Null
        Write-VolumeCache -DriveLetter $efiLetter -ErrorAction Stop
        $efiVolume = Get-Volume -DriveLetter $efiLetter -ErrorAction Stop
    }
    if (
        [string]$efiVolume.HealthStatus -cne 'Healthy' -or
        [string]$efiVolume.OperationalStatus -cne 'OK'
    ) {
        throw 'The T1OS EFI filesystem did not remain healthy after the transactional update.'
    }
}
catch {
    $updateError = $_
    foreach ($bootFile in @(
        @{
            Name = 'initramfs'
            BackupCreated = $initramfsBackupCreated
            Destination = $initramfsDestination
            Backup = $initramfsBackup
            Failed = $initramfsFailed
        },
        @{
            Name = 'kernel'
            BackupCreated = $kernelBackupCreated
            Destination = $kernelDestination
            Backup = $kernelBackup
            Failed = $kernelFailed
        }
    )) {
        if (-not $bootFile.BackupCreated) {
            continue
        }
        try {
            if (Test-Path -LiteralPath $bootFile.Destination) {
                Move-Item -LiteralPath $bootFile.Destination `
                    -Destination $bootFile.Failed
            }
            Move-Item -LiteralPath $bootFile.Backup `
                -Destination $bootFile.Destination
        }
        catch {
            Write-Warning (
                "Could not roll back the EFI $($bootFile.Name): " +
                $_.Exception.Message
            )
        }
    }
    foreach ($temporaryPath in @($kernelTemporary, $initramfsTemporary)) {
        if ($temporaryPath -and (Test-Path -LiteralPath $temporaryPath)) {
            Remove-Item -LiteralPath $temporaryPath -Force -ErrorAction SilentlyContinue
        }
    }
    if ($modulesSwapped) {
        try {
            & wsl.exe -d Ubuntu -u root --exec bash -c $moduleRollback -- `
                $updateName
        }
        catch {
            Write-Warning "Could not roll back the USB module tree: $($_.Exception.Message)"
        }
    }
    throw $updateError
}
finally {
    if ($efiAccessPath) {
        Remove-PartitionAccessPath -DiskNumber $target.Disk.Number `
            -PartitionNumber $target.Efi.PartitionNumber `
            -AccessPath $efiAccessPath -ErrorAction SilentlyContinue
    }
}

$updatedVolume = Get-Volume -DriveLetter D -ErrorAction Stop
if (
    [string]$updatedVolume.FileSystemType -cne 'NTFS' -or
    (
        -not $BootFilesOnly -and
        [string]$updatedVolume.HealthStatus -cne 'Healthy'
    )
) {
    throw 'The T1OS USB root did not remain a healthy NTFS volume.'
}

if ($BootFilesOnly) {
    Write-Host (
        'Scoped EFI kernel/initramfs bootstrap update passed. The NTFS root ' +
        'was not modified; boot T1OS to run its initramfs health pass.'
    )
}
else {
    $recoveryMarker = 'D:\the one\settings\graphics recovery boot.json'
    if (Test-Path -LiteralPath $recoveryMarker -PathType Leaf) {
        $recoveryArchive = (
            "D:\the one\settings\graphics recovery boot.previous-$updateName.json"
        )
        if (-not (Test-Path -LiteralPath $recoveryArchive)) {
            Move-Item -LiteralPath $recoveryMarker -Destination $recoveryArchive
            Write-Host "Archived obsolete graphics recovery marker: $recoveryArchive"
        }
        else {
            Remove-Item -LiteralPath $recoveryMarker -Force
            Write-Host 'Removed obsolete graphics recovery marker.'
        }
    }
    Write-Host (
        'Scoped hardware kernel/initramfs/module update passed. No image or ' +
        '.t1os bundle was rebuilt or replaced.'
    )
}
