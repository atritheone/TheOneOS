[CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
param(
    [Parameter(ParameterSetName = 'Flash', Mandatory)]
    [ValidateRange(1, 1024)]
    [int]$DiskNumber,

    [Parameter(ParameterSetName = 'Flash')]
    [Parameter(ParameterSetName = 'Inspect', Mandatory)]
    [string]$ImagePath,

    [Parameter(ParameterSetName = 'Flash', Mandatory)]
    [string]$Confirmation,

    [Parameter(ParameterSetName = 'Flash')]
    [switch]$AllowLargeUsb,

    [Parameter(ParameterSetName = 'Flash')]
    [switch]$RequireProduction,

    [Parameter(ParameterSetName = 'Flash')]
    [switch]$EndUserImage,

    [Parameter(ParameterSetName = 'List', Mandatory)]
    [switch]$ListTargets,

    [Parameter(ParameterSetName = 'List')]
    [switch]$Json,

    [Parameter(ParameterSetName = 'Inspect', Mandatory)]
    [switch]$InspectImage
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Path $PSScriptRoot -Parent

Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;

public static class T1OSVolumeControl
{
    public const uint GENERIC_READ = 0x80000000;
    public const uint GENERIC_WRITE = 0x40000000;
    public const uint FILE_SHARE_READ = 0x00000001;
    public const uint FILE_SHARE_WRITE = 0x00000002;
    public const uint OPEN_EXISTING = 3;
    public const uint FSCTL_LOCK_VOLUME = 0x00090018;
    public const uint FSCTL_UNLOCK_VOLUME = 0x0009001c;
    public const uint FSCTL_DISMOUNT_VOLUME = 0x00090020;
    public const uint FSCTL_ALLOW_EXTENDED_DASD_IO = 0x00090083;

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern SafeFileHandle CreateFile(
        string fileName,
        uint desiredAccess,
        uint shareMode,
        IntPtr securityAttributes,
        uint creationDisposition,
        uint flagsAndAttributes,
        IntPtr templateFile);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool DeviceIoControl(
        SafeFileHandle device,
        uint controlCode,
        IntPtr inputBuffer,
        uint inputBufferSize,
        IntPtr outputBuffer,
        uint outputBufferSize,
        out uint bytesReturned,
        IntPtr overlapped);
}
'@

function Get-T1OSUsbDisks {
    @(
        Get-Disk |
            Where-Object {
                $_.BusType -eq 'USB' -and
                -not $_.IsBoot -and
                -not $_.IsSystem -and
                $_.Number -ne 0 -and
                [long]$_.Size -gt 0 -and
                ([string]$_.FriendlyName).Trim() -notmatch '(?i)BIWIN\s+NV7400|WD\s+My\s+Passport|My\s+Passport'
            } |
            Sort-Object Number
    )
}

function Get-T1OSProtectedUsbDisks {
    @(
        Get-Disk |
            Where-Object {
                $_.BusType -eq 'USB' -and
                ([string]$_.FriendlyName).Trim() -match '(?i)BIWIN\s+NV7400|WD\s+My\s+Passport|My\s+Passport'
            } |
            Sort-Object Number
    )
}

function Get-T1OSUsbConfirmation {
    param(
        [Parameter(Mandatory)]
        $Disk
    )

    $targetName = ([string]$Disk.FriendlyName).Trim()
    $targetSerial = ([string]$Disk.SerialNumber).Trim()
    if ([string]::IsNullOrWhiteSpace($targetSerial)) {
        $targetSerial = 'NO-SERIAL'
    }
    $targetSizeGiB = [math]::Round($Disk.Size / 1GB, 2)
    return "ERASE DISK $($Disk.Number) $targetName $targetSizeGiB GiB SERIAL $targetSerial"
}

function Read-T1OSImageBytes {
    param(
        [Parameter(Mandatory)]
        [System.IO.Stream]$Stream,

        [Parameter(Mandatory)]
        [long]$Offset,

        [Parameter(Mandatory)]
        [ValidateRange(1, 1048576)]
        [int]$Count
    )

    if ($Offset -lt 0 -or $Offset + $Count -gt $Stream.Length) {
        throw 'The image ends before its partition metadata is complete.'
    }

    $buffer = [byte[]]::new($Count)
    $Stream.Position = $Offset
    $read = 0
    while ($read -lt $Count) {
        $countRead = $Stream.Read($buffer, $read, $Count - $read)
        if ($countRead -le 0) {
            throw 'The image ended unexpectedly while its partition metadata was being read.'
        }
        $read += $countRead
    }
    return ,$buffer
}

function Get-T1OSImageVersion {
    param(
        [Parameter(Mandatory)]
        [string]$Path
    )

    $baseName = [System.IO.Path]::GetFileNameWithoutExtension($Path)
    $versionMatches = [regex]::Matches($baseName, '(?<![\d.])\d+\.\d+(?![\d.])')
    if ($versionMatches.Count -ne 1) {
        throw 'The installation filename must contain exactly one decimal version, for example "The One OS 0.305.t1os".'
    }
    return $versionMatches[0].Value
}

function Get-T1OSImageLayout {
    param(
        [Parameter(Mandatory)]
        [string]$Path,

        [switch]$RequireFilenameVersion
    )

    $resolvedPath = [System.IO.Path]::GetFullPath($Path)
    if (-not (Test-Path -LiteralPath $resolvedPath -PathType Leaf)) {
        throw "The One OS image not found: $resolvedPath"
    }

    $image = Get-Item -LiteralPath $resolvedPath
    if ($image.Length -lt 1MB) {
        throw 'The selected image is too small to be a The One OS disk image.'
    }

    $stream = [System.IO.FileStream]::new(
        $resolvedPath,
        [System.IO.FileMode]::Open,
        [System.IO.FileAccess]::Read,
        [System.IO.FileShare]::ReadWrite
    )
    try {
        $gptHeader = Read-T1OSImageBytes -Stream $stream -Offset 512 -Count 512
        if ([Text.Encoding]::ASCII.GetString($gptHeader, 0, 8) -cne 'EFI PART') {
            throw 'The selected image does not contain the expected GPT partition table.'
        }

        $partitionEntriesLba = [BitConverter]::ToUInt64($gptHeader, 72)
        $partitionEntryCount = [BitConverter]::ToUInt32($gptHeader, 80)
        $partitionEntrySize = [BitConverter]::ToUInt32($gptHeader, 84)
        if ($partitionEntryCount -lt 3 -or $partitionEntrySize -lt 128 -or $partitionEntrySize -gt 4096) {
            throw 'The selected image has an invalid GPT partition layout.'
        }

        $entryTableOffset = [long]$partitionEntriesLba * 512
        $espEntry = Read-T1OSImageBytes -Stream $stream -Offset $entryTableOffset -Count $partitionEntrySize
        $recoveryEntry = Read-T1OSImageBytes -Stream $stream -Offset ($entryTableOffset + $partitionEntrySize) -Count $partitionEntrySize
        $rootEntry = Read-T1OSImageBytes -Stream $stream -Offset ($entryTableOffset + 2 * $partitionEntrySize) -Count $partitionEntrySize

        $espType = [Guid]::new([byte[]]$espEntry[0..15])
        $rootType = [Guid]::new([byte[]]$rootEntry[0..15])
        $recoveryType = [Guid]::new([byte[]]$recoveryEntry[0..15])
        $expectedEspType = [Guid]'c12a7328-f81f-11d2-ba4b-00a0c93ec93b'
        $expectedRootType = [Guid]'ebd0a0a2-b9e5-4433-87c0-68b6b72699c7'
        $expectedRecoveryType = [Guid]'0fc63daf-8483-4772-8e79-3d69d8477de4'
        if ($espType -ne $expectedEspType) {
            throw 'The selected image does not contain the expected EFI system partition.'
        }
        if ($rootType -ne $expectedRootType) {
            throw 'The selected image does not contain the expected NTFS root partition.'
        }
        if ($recoveryType -ne $expectedRecoveryType) {
            throw 'The selected image does not contain the expected independent recovery partition.'
        }

        $espStartLba = [BitConverter]::ToUInt64($espEntry, 32)
        $recoveryStartLba = [BitConverter]::ToUInt64($recoveryEntry, 32)
        $rootStartLba = [BitConverter]::ToUInt64($rootEntry, 32)
        $rootEndLba = [BitConverter]::ToUInt64($rootEntry, 40)
        if ($espStartLba -lt 2 -or $recoveryStartLba -le $espStartLba -or $rootStartLba -le $recoveryStartLba -or $rootEndLba -lt $rootStartLba) {
            throw 'The selected image has invalid partition boundaries.'
        }
        if (([decimal]($rootEndLba + 1) * 512) -gt $image.Length) {
            throw 'The selected image is truncated before the end of its NTFS root partition.'
        }

        $espBootSector = Read-T1OSImageBytes -Stream $stream -Offset ([long]$espStartLba * 512) -Count 512
        if (
            [Text.Encoding]::ASCII.GetString($espBootSector, 82, 8) -cne 'FAT32   ' -or
            $espBootSector[510] -ne 0x55 -or
            $espBootSector[511] -ne 0xAA
        ) {
            throw 'The selected image EFI partition is not a valid FAT32 boot partition.'
        }

        $rootBootSector = Read-T1OSImageBytes -Stream $stream -Offset ([long]$rootStartLba * 512) -Count 512
        if (
            [Text.Encoding]::ASCII.GetString($rootBootSector, 3, 8) -cne 'NTFS    ' -or
            $rootBootSector[510] -ne 0x55 -or
            $rootBootSector[511] -ne 0xAA
        ) {
            throw 'The selected image root partition is not a valid NTFS filesystem.'
        }
        $recoveryHeader = Read-T1OSImageBytes -Stream $stream -Offset ([long]$recoveryStartLba * 512) -Count 4
        if ([Text.Encoding]::ASCII.GetString($recoveryHeader) -cne 'hsqs') {
            throw 'The selected image recovery partition is not a valid SquashFS baseline.'
        }

        $version = $null
        $volumeLabel = $null
        try {
            $version = Get-T1OSImageVersion -Path $resolvedPath
            $volumeLabel = "T1OS $version"
        }
        catch {
            if ($RequireFilenameVersion) {
                throw
            }
        }
        [pscustomobject]@{
            valid = $true
            bytes = [long]$image.Length
            partitionTable = 'gpt'
            bootFilesystem = 'fat32'
            rootFilesystem = 'ntfs'
            version = $version
            volumeLabel = $volumeLabel
        }
    }
    finally {
        $stream.Dispose()
    }
}

function Get-T1OSStreamSha256 {
    param(
        [Parameter(Mandatory)]
        [System.IO.Stream]$Stream
    )

    $hash = [Security.Cryptography.IncrementalHash]::CreateHash(
        [Security.Cryptography.HashAlgorithmName]::SHA256
    )
    $buffer = [byte[]]::new(4MB)
    try {
        while (($count = $Stream.Read($buffer, 0, $buffer.Length)) -gt 0) {
            $hash.AppendData($buffer, 0, $count)
        }
        return [Convert]::ToHexString($hash.GetHashAndReset()).ToLowerInvariant()
    }
    finally {
        $hash.Dispose()
    }
}

function Open-T1OSBundle {
    param(
        [Parameter(Mandatory)]
        [string]$Path,

        [switch]$VerifyPayloads
    )

    $resolvedPath = [System.IO.Path]::GetFullPath($Path)
    if ([System.IO.Path]::GetExtension($resolvedPath).ToLowerInvariant() -ne '.t1os') {
        throw 'The selected installation bundle must end in .t1os.'
    }
    if (-not (Test-Path -LiteralPath $resolvedPath -PathType Leaf)) {
        throw "The One OS installation bundle not found: $resolvedPath"
    }

    Add-Type -AssemblyName System.IO.Compression
    $bundleFile = Get-Item -LiteralPath $resolvedPath
    $fileStream = [System.IO.FileStream]::new(
        $resolvedPath,
        [System.IO.FileMode]::Open,
        [System.IO.FileAccess]::Read,
        [System.IO.FileShare]::Read
    )
    $archive = $null
    try {
        $archive = [System.IO.Compression.ZipArchive]::new(
            $fileStream,
            [System.IO.Compression.ZipArchiveMode]::Read,
            $true
        )
        $entries = @($archive.Entries)
        $entryNames = @($entries | ForEach-Object { $_.FullName })
        $expectedEntryNames = @('manifest.json', 'esp.img', 'recovery.squashfs', 'root.ntfs.img')
        if (
            $entries.Count -ne $expectedEntryNames.Count -or
            @(Compare-Object $expectedEntryNames $entryNames -CaseSensitive).Count -ne 0
        ) {
            throw 'The T1OS bundle must contain only its manifest and three partition payloads.'
        }

        $manifestEntry = $archive.GetEntry('manifest.json')
        if (-not $manifestEntry -or $manifestEntry.Length -le 0 -or $manifestEntry.Length -gt 1MB) {
            throw 'The T1OS bundle manifest is missing or invalid.'
        }
        $manifestStream = $manifestEntry.Open()
        $reader = [System.IO.StreamReader]::new(
            $manifestStream,
            [System.Text.UTF8Encoding]::new($false, $true),
            $true,
            4096,
            $false
        )
        try {
            $manifest = $reader.ReadToEnd() | ConvertFrom-Json
        }
        finally {
            $reader.Dispose()
        }

        $filenameVersion = Get-T1OSImageVersion -Path $resolvedPath
        $version = [string]$manifest.version
        $volumeLabel = [string]$manifest.volume_label
        $rootUuid = [string]$manifest.root_uuid
        if (
            [string]$manifest.format -cne 't1os-usb-bundle' -or
            [int]$manifest.format_version -ne 2 -or
            [string]$manifest.state -cne 'validated'
        ) {
            throw 'The selected file is not a validated T1OS USB bundle.'
        }
        if (
            $version -notmatch '^\d+(?:\.\d+)?$' -or
            $filenameVersion -cne $version -or
            [string]$manifest.drive_version -cne $version -or
            $volumeLabel -cne "T1OS $version"
        ) {
            throw 'The bundle filename, drive version, and NTFS label are inconsistent.'
        }
        if (
            [string]$manifest.partition_table -cne 'gpt' -or
            [string]$manifest.root_filesystem -cne 'ntfs' -or
            [bool]$manifest.windows_native_root -ne $true -or
            [string]$manifest.windows_autorun -cne 'autorun.inf' -or
            [string]$manifest.windows_drive_icon -cne 'the one\resources\system\drive logo.ico'
        ) {
            throw 'The bundle does not describe a Windows-native GPT/NTFS T1OS drive.'
        }
        if ($rootUuid -notmatch '^[0-9A-Fa-f]{16}$') {
            throw 'The bundle contains an invalid NTFS root UUID.'
        }
        $rootHealthJournal = $manifest.roothealth_journal
        $journalValidatorPath = Join-Path $PSScriptRoot 'validate roothealth journal.py'
        if (-not (Test-Path -LiteralPath $journalValidatorPath -PathType Leaf)) {
            throw "RootHealth journal validator not found: $journalValidatorPath"
        }
        $journalValidatorHash = (
            Get-FileHash -Algorithm SHA256 -LiteralPath $journalValidatorPath
        ).Hash.ToLowerInvariant()
        $slotGenerations = @($rootHealthJournal.resize_validation.headers.slot_generations)
        if (
            $null -eq $rootHealthJournal -or
            [int]$rootHealthJournal.format -ne 1 -or
            [string]$rootHealthJournal.state -cne 'resize-preserved-and-validated' -or
            [string]$rootHealthJournal.path -cne '$Extend/$RootHealth' -or
            [int64]$rootHealthJournal.logical_bytes -ne 134217728 -or
            [string]$rootHealthJournal.required_flags -cne '0x00002007' -or
            [string]$rootHealthJournal.volume_serial -notmatch '^[0-9A-F]{16}$' -or
            [string]$rootHealthJournal.journal_uuid -notmatch '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' -or
            [int64]$rootHealthJournal.mft_record -le 0 -or
            [int64]$rootHealthJournal.mft_sequence -le 0 -or
            [string]$rootHealthJournal.record_locator -cne "$($rootHealthJournal.mft_record):$($rootHealthJournal.mft_sequence)" -or
            [string]$rootHealthJournal.identity_sha256 -notmatch '^[0-9a-f]{64}$' -or
            [string]$rootHealthJournal.run_policy -cne 'VALIDATED_AFTER_RESIZE' -or
            [int64]$rootHealthJournal.resize_validation.run_count -lt 1 -or
            [string]$rootHealthJournal.resize_validation.report_sha256 -notmatch '^[0-9a-f]{64}$' -or
            [string]$rootHealthJournal.resize_validation.write_exclusion.sha256 -notmatch '^[0-9a-f]{64}$' -or
            [int64]$rootHealthJournal.resize_validation.write_exclusion.range_count -lt 1 -or
            [string]$rootHealthJournal.resize_validation.headers.state -cne 'EMPTY' -or
            [int64]$rootHealthJournal.resize_validation.headers.selected_generation -ne 2 -or
            $slotGenerations.Count -ne 2 -or
            [int64]$slotGenerations[0] -ne 1 -or
            [int64]$slotGenerations[1] -ne 2 -or
            [int64]$rootHealthJournal.resize_validation.headers.max_entry_count -ne 4096 -or
            [string]$rootHealthJournal.resize_validation.headers.entry_area_zero_sha256 -notmatch '^[0-9a-f]{64}$' -or
            -not [bool]$rootHealthJournal.resize_validation.ownership.complete -or
            -not [bool]$rootHealthJournal.resize_validation.ownership.unique_owner -or
            -not [bool]$rootHealthJournal.resize_validation.ownership.self_nonoverlap -or
            [int64]$rootHealthJournal.resize_validation.ownership.journal_clusters -ne 32768 -or
            [string]$rootHealthJournal.provenance.validator_sha256 -cne $journalValidatorHash -or
            [string]$rootHealthJournal.provenance.ntfscp_binary_sha256 -notmatch '^[0-9a-f]{64}$' -or
            [string]$rootHealthJournal.provenance.ntfscp_manifest_sha256 -notmatch '^[0-9a-f]{64}$' -or
            [string]$rootHealthJournal.provenance.ntfs_next_commit -cne 'd4f481df6926557f7b18b471a43313652dec6f7e' -or
            [string]$rootHealthJournal.provenance.ntfs_next_archive_sha256 -cne '13dc944f477997ae4ecd89e3d0fdaa34b74ebbc1f7beb675657624ed6289eff5'
        ) {
            throw 'The bundle lacks a complete source-bound resize-preserved RootHealth journal attestation.'
        }

        $espEntry = $archive.GetEntry([string]$manifest.esp.entry)
        $recoveryEntry = $archive.GetEntry([string]$manifest.recovery.entry)
        $rootEntry = $archive.GetEntry([string]$manifest.root.entry)
        $espBytes = [long]$manifest.esp.bytes
        $recoveryBytes = [long]$manifest.recovery.bytes
        $recoveryPartitionBytes = [long]$manifest.recovery.partition_bytes
        $rootBytes = [long]$manifest.root.bytes
        $minimumTargetBytes = [long]$manifest.minimum_target_bytes
        $espHash = ([string]$manifest.esp.sha256).ToLowerInvariant()
        $recoveryHash = ([string]$manifest.recovery.sha256).ToLowerInvariant()
        $rootHash = ([string]$manifest.root.sha256).ToLowerInvariant()
        if (
            -not $espEntry -or -not $recoveryEntry -or -not $rootEntry -or
            $espEntry.FullName -cne 'esp.img' -or
            $recoveryEntry.FullName -cne 'recovery.squashfs' -or
            $rootEntry.FullName -cne 'root.ntfs.img' -or
            $espBytes -ne 512MB -or $espEntry.Length -ne $espBytes -or
            $recoveryBytes -le 4096 -or $recoveryEntry.Length -ne $recoveryBytes -or
            $recoveryPartitionBytes -ne 3GB -or $recoveryBytes -gt $recoveryPartitionBytes -or
            $rootBytes -lt 1GB -or $rootEntry.Length -ne $rootBytes -or
            ($rootBytes % 512) -ne 0 -or
            $minimumTargetBytes -ne (1MB + $espBytes + $recoveryPartitionBytes + $rootBytes + 1MB) -or
            $espHash -notmatch '^[0-9a-f]{64}$' -or
            $recoveryHash -notmatch '^[0-9a-f]{64}$' -or
            $rootHash -notmatch '^[0-9a-f]{64}$'
        ) {
            throw 'The bundle payload lengths, hashes, or minimum target size are invalid.'
        }
        if (
            [string]$manifest.esp.filesystem -cne 'fat32' -or
            [string]$manifest.esp.label -cne 'T1OS_EFI' -or
            [string]$manifest.recovery.filesystem -cne 'squashfs-zstd' -or
            [string]$manifest.recovery.label -cne 'T1OS_RECOVERY' -or
            [string]$manifest.root.filesystem -cne 'ntfs' -or
            [string]$manifest.root.label -cne $volumeLabel -or
            [string]$manifest.root.uuid -cne $rootUuid
        ) {
            throw 'The bundle payload filesystem metadata is inconsistent.'
        }

        if ($VerifyPayloads) {
            Write-Host 'Validating compact T1OS bundle payloads...'
            $espStream = $espEntry.Open()
            try {
                $actualEspHash = Get-T1OSStreamSha256 -Stream $espStream
            }
            finally {
                $espStream.Dispose()
            }
            if ($actualEspHash -cne $espHash) {
                throw 'The EFI payload hash does not match the bundle manifest.'
            }

            $recoveryStream = $recoveryEntry.Open()
            try {
                $actualRecoveryHash = Get-T1OSStreamSha256 -Stream $recoveryStream
            }
            finally {
                $recoveryStream.Dispose()
            }
            if ($actualRecoveryHash -cne $recoveryHash) {
                throw 'The recovery payload hash does not match the bundle manifest.'
            }

            $rootStream = $rootEntry.Open()
            try {
                $actualRootHash = Get-T1OSStreamSha256 -Stream $rootStream
            }
            finally {
                $rootStream.Dispose()
            }
            if ($actualRootHash -cne $rootHash) {
                throw 'The NTFS payload hash does not match the bundle manifest.'
            }
            Write-Host 'Compact T1OS bundle payload validation passed.'
        }

        $layout = [pscustomobject]@{
            valid = $true
            bundle = $true
            bytes = [long]$bundleFile.Length
            payloadBytes = $espBytes + $recoveryBytes + $rootBytes
            minimumTargetBytes = $minimumTargetBytes
            partitionTable = 'gpt'
            bootFilesystem = 'fat32'
            rootFilesystem = 'ntfs'
            version = $version
            driveVersion = $version
            volumeLabel = $volumeLabel
            rootUuid = $rootUuid.ToUpperInvariant()
            production = [bool]$manifest.production
            secureBoot = [bool]$manifest.secure_boot
            espBytes = $espBytes
            recoveryBytes = $recoveryBytes
            recoveryPartitionBytes = $recoveryPartitionBytes
            rootBytes = $rootBytes
            espHash = $espHash
            recoveryHash = $recoveryHash
            rootHash = $rootHash
            roothealthJournal = $rootHealthJournal
        }
        return [pscustomobject]@{
            FileStream = $fileStream
            Archive = $archive
            Manifest = $manifest
            EspEntry = $espEntry
            RecoveryEntry = $recoveryEntry
            RootEntry = $rootEntry
            Layout = $layout
        }
    }
    catch {
        if ($archive) {
            $archive.Dispose()
        }
        $fileStream.Dispose()
        throw
    }
}

function Get-T1OSBundleLayout {
    param(
        [Parameter(Mandatory)]
        [string]$Path
    )

    $context = Open-T1OSBundle -Path $Path
    try {
        return $context.Layout
    }
    finally {
        $context.Archive.Dispose()
        $context.FileStream.Dispose()
    }
}

function Invoke-T1OSMountvol {
    param(
        [Parameter(Mandatory)]
        [string]$MountvolPath,

        [Parameter(Mandatory)]
        [string]$MountPoint,

        [Parameter(Mandatory)]
        [ValidateSet('/d')]
        [string]$Action
    )

    $startInfo = [Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $MountvolPath
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.ArgumentList.Add($MountPoint)
    $startInfo.ArgumentList.Add($Action)
    $process = [Diagnostics.Process]::Start($startInfo)
    try {
        $process.WaitForExit()
        if ($process.ExitCode -ne 0) {
            throw "mountvol $Action failed for $MountPoint (exit code $($process.ExitCode))."
        }
    }
    finally {
        $process.Dispose()
    }
}

function Dismount-T1OSMountedVolumes {
    param(
        [Parameter(Mandatory)]
        [int]$TargetDiskNumber
    )

    $mountvolPath = Join-Path (
        [Environment]::GetFolderPath([Environment+SpecialFolder]::Windows)
    ) 'System32\mountvol.exe'
    if (-not (Test-Path -LiteralPath $mountvolPath -PathType Leaf)) {
        throw "Windows mountvol was not found: $mountvolPath"
    }

    $mountedPartitions = @(
        Get-Partition -DiskNumber $TargetDiskNumber -ErrorAction Stop |
            Sort-Object PartitionNumber |
            ForEach-Object {
                $partition = $_
                $mountPoints = @(
                    $partition.AccessPaths |
                        Where-Object {
                            -not [string]::IsNullOrWhiteSpace($_) -and
                            $_ -match '^[A-Za-z]:\\'
                        }
                )
                if ($mountPoints.Count -gt 0) {
                    [pscustomobject]@{
                        PartitionNumber = [int]$partition.PartitionNumber
                        MountPoints = [string[]]$mountPoints
                    }
                }
            }
    )

    foreach ($mountedPartition in $mountedPartitions) {
        $mountPoints = @($mountedPartition.MountPoints)
        $primaryMountPoint = @(
            $mountPoints |
                Where-Object { $_ -match '^[A-Za-z]:\\$' } |
                Select-Object -First 1
        )
        if ($primaryMountPoint.Count -eq 0) {
            $primaryMountPoint = @($mountPoints | Select-Object -First 1)
        }
        $primaryMountPoint = [string]$primaryMountPoint[0]

        foreach ($mountPoint in @($mountPoints | Where-Object {
            $_ -cne $primaryMountPoint
        })) {
            Write-Host "Removing extra USB mount point $mountPoint..."
            Invoke-T1OSMountvol `
                -MountvolPath $mountvolPath `
                -MountPoint $mountPoint `
                -Action '/d'
        }

        Write-Host "Removing mounted USB volume access path $primaryMountPoint before flashing..."
        Invoke-T1OSMountvol `
            -MountvolPath $mountvolPath `
            -MountPoint $primaryMountPoint `
            -Action '/d'
    }
}

function Lock-T1OSRemovableVolumes {
    param(
        [Parameter(Mandatory)]
        [int]$TargetDiskNumber,

        [switch]$AllowExtendedDASDIO
    )

    $volumeTargets = @(
        Get-Partition -DiskNumber $TargetDiskNumber -ErrorAction Stop |
            Sort-Object PartitionNumber |
            ForEach-Object {
                $partition = $_
                $volumePath = @(
                    $partition.AccessPaths |
                        Where-Object {
                            $_ -match '^\\\\\?\\Volume\{[0-9a-f-]+\}\\$'
                        }
                ) | Select-Object -First 1
                if ($volumePath) {
                    [pscustomobject]@{
                        PartitionNumber = [int]$partition.PartitionNumber
                        VolumePath = [string]$volumePath
                    }
                }
            }
    )

    $handles = [Collections.Generic.List[Microsoft.Win32.SafeHandles.SafeFileHandle]]::new()
    try {
        foreach ($volumeTarget in $volumeTargets) {
            $volumePath = [string]$volumeTarget.VolumePath
            $devicePath = $volumePath.TrimEnd('\')
            Write-Host "Locking and dismounting removable USB volume $volumePath..."
            $handle = [T1OSVolumeControl]::CreateFile(
                $devicePath,
                [T1OSVolumeControl]::GENERIC_READ -bor [T1OSVolumeControl]::GENERIC_WRITE,
                [T1OSVolumeControl]::FILE_SHARE_READ -bor [T1OSVolumeControl]::FILE_SHARE_WRITE,
                [IntPtr]::Zero,
                [T1OSVolumeControl]::OPEN_EXISTING,
                0,
                [IntPtr]::Zero
            )
            if ($handle.IsInvalid) {
                $errorCode = [Runtime.InteropServices.Marshal]::GetLastWin32Error()
                $handle.Dispose()
                throw [ComponentModel.Win32Exception]::new($errorCode, "Could not open USB volume $volumePath")
            }

            $bytesReturned = [uint32]0
            if (-not [T1OSVolumeControl]::DeviceIoControl(
                $handle, [T1OSVolumeControl]::FSCTL_LOCK_VOLUME,
                [IntPtr]::Zero, 0, [IntPtr]::Zero, 0,
                [ref]$bytesReturned, [IntPtr]::Zero
            )) {
                $errorCode = [Runtime.InteropServices.Marshal]::GetLastWin32Error()
                $handle.Dispose()
                throw [ComponentModel.Win32Exception]::new($errorCode, "Could not lock USB volume $volumePath. Close Explorer and every application using the USB")
            }

            if (-not [T1OSVolumeControl]::DeviceIoControl(
                $handle, [T1OSVolumeControl]::FSCTL_DISMOUNT_VOLUME,
                [IntPtr]::Zero, 0, [IntPtr]::Zero, 0,
                [ref]$bytesReturned, [IntPtr]::Zero
            )) {
                $errorCode = [Runtime.InteropServices.Marshal]::GetLastWin32Error()
                [void][T1OSVolumeControl]::DeviceIoControl(
                    $handle, [T1OSVolumeControl]::FSCTL_UNLOCK_VOLUME,
                    [IntPtr]::Zero, 0, [IntPtr]::Zero, 0,
                    [ref]$bytesReturned, [IntPtr]::Zero
                )
                $handle.Dispose()
                throw [ComponentModel.Win32Exception]::new($errorCode, "Could not dismount locked USB volume $volumePath")
            }

            if (
                $AllowExtendedDASDIO -and
                -not [T1OSVolumeControl]::DeviceIoControl(
                    $handle,
                    [T1OSVolumeControl]::FSCTL_ALLOW_EXTENDED_DASD_IO,
                    [IntPtr]::Zero,
                    0,
                    [IntPtr]::Zero,
                    0,
                    [ref]$bytesReturned,
                    [IntPtr]::Zero
                )
            ) {
                $errorCode = [Runtime.InteropServices.Marshal]::GetLastWin32Error()
                # RAW partitions have no mounted filesystem boundary and
                # commonly reject this filesystem control with INVALID_
                # FUNCTION, NOT_SUPPORTED, or INVALID_PARAMETER. The locked
                # volume device already exposes the complete partition.
                if ($errorCode -in @(1, 50, 87)) {
                    Write-Host "Complete-partition DASD control is unnecessary for raw USB volume $volumePath (status $errorCode)."
                }
                else {
                    [void][T1OSVolumeControl]::DeviceIoControl(
                        $handle, [T1OSVolumeControl]::FSCTL_UNLOCK_VOLUME,
                        [IntPtr]::Zero, 0, [IntPtr]::Zero, 0,
                        [ref]$bytesReturned, [IntPtr]::Zero
                    )
                    $handle.Dispose()
                    throw [ComponentModel.Win32Exception]::new(
                        $errorCode,
                        "Could not enable complete partition access for USB volume $volumePath"
                    )
                }
            }

            $handles.Add($handle)
        }

        return $handles.ToArray()
    }
    catch {
        foreach ($handle in $handles) {
            $bytesReturned = [uint32]0
            [void][T1OSVolumeControl]::DeviceIoControl(
                $handle, [T1OSVolumeControl]::FSCTL_UNLOCK_VOLUME,
                [IntPtr]::Zero, 0, [IntPtr]::Zero, 0,
                [ref]$bytesReturned, [IntPtr]::Zero
            )
            $handle.Dispose()
        }
        throw
    }
}

function Unlock-T1OSRemovableVolumes {
    param(
        [Microsoft.Win32.SafeHandles.SafeFileHandle[]]$Handles
    )

    foreach ($handle in @($Handles)) {
        if (-not $handle -or $handle.IsClosed) {
            continue
        }
        $bytesReturned = [uint32]0
        [void][T1OSVolumeControl]::DeviceIoControl(
            $handle,
            [T1OSVolumeControl]::FSCTL_UNLOCK_VOLUME,
            [IntPtr]::Zero,
            0,
            [IntPtr]::Zero,
            0,
            [ref]$bytesReturned,
            [IntPtr]::Zero
        )
        $handle.Dispose()
    }
}

function Mount-T1OSRootForWindows {
    param(
        [Parameter(Mandatory)]
        [int]$TargetDiskNumber,

        [Parameter(Mandatory)]
        [string]$ExpectedLabel
    )

    $partition = Get-Partition `
        -DiskNumber $TargetDiskNumber `
        -PartitionNumber 3 `
        -ErrorAction Stop
    if ([int][char]$partition.DriveLetter -eq 0) {
        Add-PartitionAccessPath `
            -DiskNumber $TargetDiskNumber `
            -PartitionNumber 3 `
            -AssignDriveLetter `
            -ErrorAction Stop
    }

    foreach ($attempt in 1..30) {
        Update-HostStorageCache
        $partition = Get-Partition `
            -DiskNumber $TargetDiskNumber `
            -PartitionNumber 3 `
            -ErrorAction Stop
        if ([int][char]$partition.DriveLetter -ne 0) {
            break
        }
        Start-Sleep -Milliseconds 250
    }
    if ([int][char]$partition.DriveLetter -eq 0) {
        throw 'Windows did not assign a drive letter to the verified T1OS root volume.'
    }

    $volume = $partition | Get-Volume -ErrorAction Stop
    if (
        [string]$volume.FileSystemType -cne 'NTFS' -or
        [string]$volume.FileSystemLabel -cne $ExpectedLabel
    ) {
        throw 'The drive letter was not attached to the expected verified T1OS NTFS root volume.'
    }

    return [char]$partition.DriveLetter
}

function Write-T1OSBundleEntry {
    param(
        [Parameter(Mandatory)]
        [System.IO.Compression.ZipArchiveEntry]$Entry,

        [Parameter(Mandatory)]
        [System.IO.Stream]$Target,

        [Parameter(Mandatory)]
        [long]$Offset,

        [Parameter(Mandatory)]
        [long]$ExpectedBytes,

        [Parameter(Mandatory)]
        [string]$ExpectedHash,

        [Parameter(Mandatory)]
        [double]$ProgressStart,

        [Parameter(Mandatory)]
        [double]$ProgressSpan,

        [ValidateRange(0, 1048576)]
        [int]$CommitPrefixBytes = 0
    )

    $source = $Entry.Open()
    $hash = [Security.Cryptography.IncrementalHash]::CreateHash(
        [Security.Cryptography.HashAlgorithmName]::SHA256
    )
    $buffer = [byte[]]::new(4MB)
    [byte[]]$commitPrefix = $null
    if ($CommitPrefixBytes -gt 0) {
        $commitPrefix = [byte[]]::new($CommitPrefixBytes)
    }
    $written = [long]0
    $nextReport = ([math]::Floor($ProgressStart / 5) * 5) + 5
    try {
        if ($CommitPrefixBytes -gt $ExpectedBytes) {
            throw "Bundle entry $($Entry.FullName) is shorter than its delayed commit prefix."
        }
        if ($CommitPrefixBytes -gt 0) {
            # Remove any stale filesystem signature before streaming the body.
            # The verified prefix is committed only after the full entry hashes.
            $Target.Position = $Offset
            $Target.Write($commitPrefix, 0, $commitPrefix.Length)
            $Target.Flush()
        }
        $Target.Position = $Offset + $CommitPrefixBytes
        while (($count = $source.Read($buffer, 0, $buffer.Length)) -gt 0) {
            if ($written + $count -gt $ExpectedBytes) {
                throw "Bundle entry $($Entry.FullName) exceeds its declared length."
            }
            $hash.AppendData($buffer, 0, $count)
            $bufferOffset = 0
            if ($written -lt $CommitPrefixBytes) {
                $prefixCount = [int][math]::Min(
                    [long]$count,
                    [long]$CommitPrefixBytes - $written
                )
                [Buffer]::BlockCopy(
                    $buffer,
                    0,
                    $commitPrefix,
                    [int]$written,
                    $prefixCount
                )
                $bufferOffset = $prefixCount
            }
            if ($bufferOffset -lt $count) {
                $Target.Write($buffer, $bufferOffset, $count - $bufferOffset)
            }
            $written += $count
            $entryPercent = [math]::Floor(($written / $ExpectedBytes) * 100)
            $overallPercent = [math]::Floor(
                $ProgressStart + (($entryPercent / 100.0) * $ProgressSpan)
            )
            while ($overallPercent -ge $nextReport -and $nextReport -le 100) {
                Write-Host "Writing T1OS USB: $nextReport%"
                $nextReport += 5
            }
        }
        if ($written -ne $ExpectedBytes) {
            throw "Bundle entry $($Entry.FullName) ended before its declared length."
        }
        $actualHash = [Convert]::ToHexString($hash.GetHashAndReset()).ToLowerInvariant()
        if ($actualHash -cne $ExpectedHash) {
            throw "Bundle entry $($Entry.FullName) changed while it was being written."
        }
        if ($CommitPrefixBytes -gt 0) {
            $Target.Position = $Offset
            $Target.Write($commitPrefix, 0, $commitPrefix.Length)
        }
    }
    finally {
        $hash.Dispose()
        $source.Dispose()
    }
}

function Get-T1OSDiskRegionHash {
    param(
        [Parameter(Mandatory)]
        [System.IO.Stream]$Stream,

        [Parameter(Mandatory)]
        [long]$Offset,

        [Parameter(Mandatory)]
        [long]$Bytes,

        [Parameter(Mandatory)]
        [double]$ProgressStart,

        [Parameter(Mandatory)]
        [double]$ProgressSpan
    )

    $hash = [Security.Cryptography.IncrementalHash]::CreateHash(
        [Security.Cryptography.HashAlgorithmName]::SHA256
    )
    $buffer = [byte[]]::new(4MB)
    $read = [long]0
    $nextReport = ([math]::Floor($ProgressStart / 5) * 5) + 5
    try {
        $Stream.Position = $Offset
        while ($read -lt $Bytes) {
            $requested = [int][math]::Min([long]$buffer.Length, $Bytes - $read)
            $count = $Stream.Read($buffer, 0, $requested)
            if ($count -le 0) {
                throw 'The USB drive ended during bundle read-back verification.'
            }
            $hash.AppendData($buffer, 0, $count)
            $read += $count
            $entryPercent = [math]::Floor(($read / $Bytes) * 100)
            $overallPercent = [math]::Floor(
                $ProgressStart + (($entryPercent / 100.0) * $ProgressSpan)
            )
            while ($overallPercent -ge $nextReport -and $nextReport -le 100) {
                Write-Host "Verifying T1OS USB: $nextReport%"
                $nextReport += 5
            }
        }
        return [Convert]::ToHexString($hash.GetHashAndReset()).ToLowerInvariant()
    }
    finally {
        $hash.Dispose()
    }
}

function Clear-T1OSDiskRegion {
    param(
        [Parameter(Mandatory)][System.IO.Stream]$Stream,
        [Parameter(Mandatory)][long]$Offset,
        [Parameter(Mandatory)][long]$Bytes
    )

    $zeroes = [byte[]]::new(4MB)
    $Stream.Position = $Offset
    $remaining = $Bytes
    while ($remaining -gt 0) {
        $count = [int][math]::Min([long]$zeroes.Length, $remaining)
        $Stream.Write($zeroes, 0, $count)
        $remaining -= $count
    }
}

function Install-T1OSBundle {
    param(
        [Parameter(Mandatory)]
        $BundleContext,

        [Parameter(Mandatory)]
        $Disk,

        [Parameter(Mandatory)]
        [string]$SerialNumber
    )

    $targetDiskNumber = [int]$Disk.Number
    $physicalPath = "\\.\PhysicalDrive$targetDiskNumber"
    $layout = $BundleContext.Layout
    $volumeLocks = @()
    $targetStream = $null
    $readbackStream = $null
    $espVolumeStream = $null
    $recoveryVolumeStream = $null
    $rootVolumeStream = $null
    $payloadDiskOffline = $false

    try {
        $rawWriteDisk = Get-Disk -Number $targetDiskNumber -ErrorAction Stop
        if ([long]$rawWriteDisk.Size -le 0) {
            throw 'Windows reports that the confirmed USB has no media. Physically unplug and reconnect it, refresh the target list, and try again.'
        }
        elseif ($rawWriteDisk.IsOffline) {
            Set-Disk -Number $targetDiskNumber -IsOffline $false -ErrorAction Stop
            $rawWriteDisk = Get-Disk -Number $targetDiskNumber -ErrorAction Stop
        }

        $existingPartitions = @(Get-Partition -DiskNumber $targetDiskNumber -ErrorAction SilentlyContinue)
        if ($existingPartitions.Count -gt 0) {
            Dismount-T1OSMountedVolumes -TargetDiskNumber $targetDiskNumber
            $volumeLocks = @(Lock-T1OSRemovableVolumes -TargetDiskNumber $targetDiskNumber)
        }

        $writeDisk = Get-Disk -Number $targetDiskNumber -ErrorAction Stop
        if (
            $writeDisk.BusType -ne 'USB' -or
            $writeDisk.IsBoot -or
            $writeDisk.IsSystem -or
            ([string]$writeDisk.SerialNumber).Trim() -cne $SerialNumber -or
            ([long]$writeDisk.Size) -ne ([long]$Disk.Size)
        ) {
            throw 'The USB disk identity changed before partitioning; refusing to continue.'
        }

        Write-Host 'Preparing capacity-independent GPT partitions...'
        Unlock-T1OSRemovableVolumes -Handles $volumeLocks
        $volumeLocks = @()
        if ($writeDisk.PartitionStyle -ne 'RAW') {
            Clear-Disk -Number $targetDiskNumber -RemoveData -RemoveOEM -Confirm:$false
        }

        # Clear-Disk removes every partition, but some removable-media
        # drivers retain an empty GPT or MBR label instead of reporting RAW.
        # Wait for the storage cache to converge and accept either retained
        # label only when the exact USB identity is unchanged and there are
        # zero partitions. An empty MBR is explicitly converted below.
        # The predecessor accepted only: PartitionStyle -in @('RAW', 'GPT')
        $clearedPartitions = @()
        foreach ($attempt in 1..40) {
            Update-HostStorageCache
            $writeDisk = Get-Disk -Number $targetDiskNumber -ErrorAction Stop
            $clearedPartitions = @(
                Get-Partition `
                    -DiskNumber $targetDiskNumber `
                    -ErrorAction SilentlyContinue
            )
            if (
                $writeDisk.BusType -ne 'USB' -or
                $writeDisk.IsBoot -or
                $writeDisk.IsSystem -or
                ([string]$writeDisk.SerialNumber).Trim() -cne $SerialNumber -or
                ([long]$writeDisk.Size) -ne ([long]$Disk.Size)
            ) {
                throw 'The USB disk identity changed while clearing its partition table; refusing to continue.'
            }
            if (
                $clearedPartitions.Count -eq 0 -and
                $writeDisk.PartitionStyle -in @('RAW', 'GPT', 'MBR')
            ) {
                break
            }
            Start-Sleep -Milliseconds 250
        }

        if ($clearedPartitions.Count -ne 0) {
            throw 'The USB disk still contains partitions after Clear-Disk; refusing to initialize a new layout.'
        }

        if ($writeDisk.PartitionStyle -eq 'RAW') {
            Initialize-Disk -Number $targetDiskNumber -PartitionStyle GPT | Out-Null
        }
        elseif ($writeDisk.PartitionStyle -eq 'GPT') {
            Write-Host 'Windows retained an empty GPT label after Clear-Disk; safely reusing the partition-free GPT.'
        }
        elseif ($writeDisk.PartitionStyle -eq 'MBR') {
            Write-Host 'Windows retained an empty MBR label after Clear-Disk; converting the partition-free disk to GPT.'
            Set-Disk -Number $targetDiskNumber -PartitionStyle GPT
        }
        else {
            throw "The cleared USB disk reported unsupported partition style '$($writeDisk.PartitionStyle)'; expected RAW, empty GPT, or empty MBR."
        }

        foreach ($attempt in 1..40) {
            Update-HostStorageCache
            $writeDisk = Get-Disk -Number $targetDiskNumber -ErrorAction Stop
            $clearedPartitions = @(
                Get-Partition `
                    -DiskNumber $targetDiskNumber `
                    -ErrorAction SilentlyContinue
            )
            if (
                $writeDisk.PartitionStyle -eq 'GPT' -and
                $clearedPartitions.Count -eq 0
            ) {
                break
            }
            Start-Sleep -Milliseconds 250
        }
        if (
            $writeDisk.PartitionStyle -ne 'GPT' -or
            $clearedPartitions.Count -ne 0
        ) {
            throw 'The USB disk did not reach an empty GPT state before T1OS partition creation.'
        }

        $espPartition = New-Partition `
            -DiskNumber $targetDiskNumber `
            -Offset 1MB `
            -Size ([long]$layout.espBytes) `
            -GptType '{C12A7328-F81F-11D2-BA4B-00A0C93EC93B}' `
            -AssignDriveLetter:$false
        $recoveryPartition = New-Partition `
            -DiskNumber $targetDiskNumber `
            -Size ([long]$layout.recoveryPartitionBytes) `
            -GptType '{0FC63DAF-8483-4772-8E79-3D69D8477DE4}' `
            -AssignDriveLetter:$false
        $rootPartition = New-Partition `
            -DiskNumber $targetDiskNumber `
            -Size ([long]$layout.rootBytes) `
            -GptType '{EBD0A0A2-B9E5-4433-87C0-68B6B72699C7}' `
            -AssignDriveLetter:$false
        if (
            $espPartition.PartitionNumber -ne 1 -or
            $recoveryPartition.PartitionNumber -ne 2 -or
            $rootPartition.PartitionNumber -ne 3 -or
            [long]$espPartition.Size -ne [long]$layout.espBytes -or
            [long]$recoveryPartition.Size -ne [long]$layout.recoveryPartitionBytes -or
            [long]$rootPartition.Size -ne [long]$layout.rootBytes
        ) {
            throw 'Windows created an unexpected initial T1OS partition layout.'
        }

        # Creating the blank partitions causes Windows to publish new volume
        # devices. Prevent automount/filesystem probes from taking ownership
        # while the verified FAT and NTFS payloads are written directly.
        Write-Host 'Locking the newly created USB volumes for the complete payload write.'
        $volumeLocks = @(
            Lock-T1OSRemovableVolumes `
                -TargetDiskNumber $targetDiskNumber `
                -AllowExtendedDASDIO
        )
        if ($volumeLocks.Count -ne 3) {
            throw 'The flasher could not obtain exclusive handles for all three newly created T1OS volumes.'
        }

        $writeDisk = Get-Disk -Number $targetDiskNumber -ErrorAction Stop
        if (
            $writeDisk.BusType -ne 'USB' -or
            $writeDisk.IsBoot -or
            $writeDisk.IsSystem -or
            ([string]$writeDisk.SerialNumber).Trim() -cne $SerialNumber -or
            ([long]$writeDisk.Size) -ne ([long]$Disk.Size) -or
            (
                -not $payloadDiskOffline -and
                $volumeLocks.Count -ne 3
            )
        ) {
            throw 'Exclusive payload-write ownership of the intended USB disk could not be verified.'
        }

        Write-Host 'Writing T1OS USB: 0%'
        if ($payloadDiskOffline) {
            $targetStream = [System.IO.FileStream]::new(
                $physicalPath,
                [System.IO.FileMode]::Open,
                [System.IO.FileAccess]::Write,
                [System.IO.FileShare]::ReadWrite,
                4MB,
                [System.IO.FileOptions]::WriteThrough
            )
            Write-T1OSBundleEntry `
                -Entry $BundleContext.EspEntry `
                -Target $targetStream `
                -Offset ([long]$espPartition.Offset) `
                -ExpectedBytes ([long]$layout.espBytes) `
                -ExpectedHash ([string]$layout.espHash) `
                -ProgressStart 0 `
                -ProgressSpan 10
            Clear-T1OSDiskRegion `
                -Stream $targetStream `
                -Offset ([long]$recoveryPartition.Offset) `
                -Bytes ([long]$layout.recoveryPartitionBytes)
            Write-T1OSBundleEntry `
                -Entry $BundleContext.RecoveryEntry `
                -Target $targetStream `
                -Offset ([long]$recoveryPartition.Offset) `
                -ExpectedBytes ([long]$layout.recoveryBytes) `
                -ExpectedHash ([string]$layout.recoveryHash) `
                -ProgressStart 10 `
                -ProgressSpan 20
            Write-T1OSBundleEntry `
                -Entry $BundleContext.RootEntry `
                -Target $targetStream `
                -Offset ([long]$rootPartition.Offset) `
                -ExpectedBytes ([long]$layout.rootBytes) `
                -ExpectedHash ([string]$layout.rootHash) `
                -ProgressStart 30 `
                -ProgressSpan 70 `
                -CommitPrefixBytes 1MB
            $targetStream.Flush($true)
            $targetStream.Dispose()
            $targetStream = $null

            $readbackStream = [System.IO.FileStream]::new(
                $physicalPath,
                [System.IO.FileMode]::Open,
                [System.IO.FileAccess]::Read,
                [System.IO.FileShare]::ReadWrite,
                4MB,
                [System.IO.FileOptions]::SequentialScan
            )
            Write-Host 'Verifying T1OS USB: 0%'
            $actualEspHash = Get-T1OSDiskRegionHash `
                -Stream $readbackStream `
                -Offset ([long]$espPartition.Offset) `
                -Bytes ([long]$layout.espBytes) `
                -ProgressStart 0 `
                -ProgressSpan 10
            $actualRecoveryHash = Get-T1OSDiskRegionHash `
                -Stream $readbackStream `
                -Offset ([long]$recoveryPartition.Offset) `
                -Bytes ([long]$layout.recoveryBytes) `
                -ProgressStart 10 `
                -ProgressSpan 20
            $actualRootHash = Get-T1OSDiskRegionHash `
                -Stream $readbackStream `
                -Offset ([long]$rootPartition.Offset) `
                -Bytes ([long]$layout.rootBytes) `
                -ProgressStart 30 `
                -ProgressSpan 70
            $readbackStream.Dispose()
            $readbackStream = $null
        }
        else {
            # FileStream owns these locked handles. Closing the streams
            # releases the volume locks after verified read-back.
            $espVolumeStream = [System.IO.FileStream]::new(
                $volumeLocks[0],
                [System.IO.FileAccess]::ReadWrite,
                4MB,
                $false
            )
            $recoveryVolumeStream = [System.IO.FileStream]::new(
                $volumeLocks[1],
                [System.IO.FileAccess]::ReadWrite,
                4MB,
                $false
            )
            $rootVolumeStream = [System.IO.FileStream]::new(
                $volumeLocks[2],
                [System.IO.FileAccess]::ReadWrite,
                4MB,
                $false
            )
            $volumeLocks = @()

            Write-T1OSBundleEntry `
                -Entry $BundleContext.EspEntry `
                -Target $espVolumeStream `
                -Offset 0 `
                -ExpectedBytes ([long]$layout.espBytes) `
                -ExpectedHash ([string]$layout.espHash) `
                -ProgressStart 0 `
                -ProgressSpan 10
            Clear-T1OSDiskRegion `
                -Stream $recoveryVolumeStream `
                -Offset 0 `
                -Bytes ([long]$layout.recoveryPartitionBytes)
            Write-T1OSBundleEntry `
                -Entry $BundleContext.RecoveryEntry `
                -Target $recoveryVolumeStream `
                -Offset 0 `
                -ExpectedBytes ([long]$layout.recoveryBytes) `
                -ExpectedHash ([string]$layout.recoveryHash) `
                -ProgressStart 10 `
                -ProgressSpan 20
            Write-T1OSBundleEntry `
                -Entry $BundleContext.RootEntry `
                -Target $rootVolumeStream `
                -Offset 0 `
                -ExpectedBytes ([long]$layout.rootBytes) `
                -ExpectedHash ([string]$layout.rootHash) `
                -ProgressStart 30 `
                -ProgressSpan 70 `
                -CommitPrefixBytes 1MB
            $espVolumeStream.Flush($true)
            $recoveryVolumeStream.Flush($true)
            $rootVolumeStream.Flush($true)

            Write-Host 'Verifying T1OS USB: 0%'
            $actualEspHash = Get-T1OSDiskRegionHash `
                -Stream $espVolumeStream `
                -Offset 0 `
                -Bytes ([long]$layout.espBytes) `
                -ProgressStart 0 `
                -ProgressSpan 10
            $actualRecoveryHash = Get-T1OSDiskRegionHash `
                -Stream $recoveryVolumeStream `
                -Offset 0 `
                -Bytes ([long]$layout.recoveryBytes) `
                -ProgressStart 10 `
                -ProgressSpan 20
            $actualRootHash = Get-T1OSDiskRegionHash `
                -Stream $rootVolumeStream `
                -Offset 0 `
                -Bytes ([long]$layout.rootBytes) `
                -ProgressStart 30 `
                -ProgressSpan 70
            $espVolumeStream.Dispose()
            $espVolumeStream = $null
            $recoveryVolumeStream.Dispose()
            $recoveryVolumeStream = $null
            $rootVolumeStream.Dispose()
            $rootVolumeStream = $null
        }

        if ($actualEspHash -cne [string]$layout.espHash) {
            throw 'The flashed EFI partition failed read-back verification.'
        }
        if ($actualRecoveryHash -cne [string]$layout.recoveryHash) {
            throw 'The flashed recovery partition failed read-back verification.'
        }
        if ($actualRootHash -cne [string]$layout.rootHash) {
            throw 'The flashed NTFS root failed read-back verification.'
        }
        Write-Host 'Compact payload write and full read-back verification succeeded.'

        if ($payloadDiskOffline) {
            Set-Disk `
                -Number $targetDiskNumber `
                -IsOffline $false `
                -ErrorAction Stop
            $payloadDiskOffline = $false
        }
        else {
            Unlock-T1OSRemovableVolumes -Handles $volumeLocks
            $volumeLocks = @()
        }
        Update-HostStorageCache
        $rootPartition = Get-Partition `
            -DiskNumber $targetDiskNumber `
            -PartitionNumber 3 `
            -ErrorAction Stop
        $supportedSize = Get-PartitionSupportedSize `
            -DiskNumber $targetDiskNumber `
            -PartitionNumber 3 `
            -ErrorAction Stop
        if ([long]$supportedSize.SizeMax -gt ([long]$rootPartition.Size + 1MB)) {
            Write-Host "Expanding the T1OS root to $([math]::Round($supportedSize.SizeMax / 1GB, 2)) GiB..."
            Resize-Partition `
                -DiskNumber $targetDiskNumber `
                -PartitionNumber 3 `
                -Size ([long]$supportedSize.SizeMax) `
                -ErrorAction Stop
            Update-HostStorageCache
        }
        else {
            Write-Host 'The T1OS root already occupies all available USB capacity.'
        }

        $rootPartition = Get-Partition `
            -DiskNumber $targetDiskNumber `
            -PartitionNumber 3 `
            -ErrorAction Stop
        if ([long]$rootPartition.Size -lt ([long]$supportedSize.SizeMax - 1MB)) {
            throw 'The T1OS root partition did not expand to the available USB capacity.'
        }

        $rootVolume = $null
        foreach ($attempt in 1..30) {
            try {
                $rootVolume = $rootPartition | Get-Volume -ErrorAction Stop
                if ($rootVolume -and $rootVolume.FileSystemType -eq 'NTFS') {
                    break
                }
            }
            catch {
                $rootVolume = $null
            }
            Start-Sleep -Milliseconds 250
            Update-HostStorageCache
        }
        if (-not $rootVolume -or [string]$rootVolume.FileSystemType -cne 'NTFS') {
            throw 'The expanded T1OS NTFS root did not become available.'
        }
        if ([string]$rootVolume.FileSystemLabel -cne [string]$layout.volumeLabel) {
            $rootVolume | Set-Volume -NewFileSystemLabel $layout.volumeLabel -ErrorAction Stop
            $rootVolume = $rootPartition | Get-Volume -ErrorAction Stop
        }
        if ([string]$rootVolume.FileSystemLabel -cne [string]$layout.volumeLabel) {
            throw "The expanded T1OS root label is not '$($layout.volumeLabel)'."
        }

        $bootSectorStream = [System.IO.FileStream]::new(
            $physicalPath,
            [System.IO.FileMode]::Open,
            [System.IO.FileAccess]::Read,
            [System.IO.FileShare]::ReadWrite
        )
        try {
            $bootSector = Read-T1OSImageBytes `
                -Stream $bootSectorStream `
                -Offset ([long]$rootPartition.Offset) `
                -Count 512
        }
        finally {
            $bootSectorStream.Dispose()
        }
        if ([Text.Encoding]::ASCII.GetString($bootSector, 3, 8) -cne 'NTFS    ') {
            throw 'The expanded T1OS root no longer has an NTFS boot sector.'
        }
        $rootUuid = [BitConverter]::ToUInt64($bootSector, 72).ToString('X16')
        if ($rootUuid -cne [string]$layout.rootUuid) {
            throw 'The expanded T1OS root UUID changed unexpectedly.'
        }

        $rootDriveLetter = Mount-T1OSRootForWindows `
            -TargetDiskNumber $targetDiskNumber `
            -ExpectedLabel ([string]$layout.volumeLabel)
        Write-Host "T1OS root expanded and verified: $([math]::Round($rootPartition.Size / 1GB, 2)) GiB"
        Write-Host "USB drive name verified: $($layout.volumeLabel)"
        Write-Host "Finalizing and cleanly dismounting T1OS from $($rootDriveLetter):\ for its final flush..."
        Dismount-T1OSMountedVolumes -TargetDiskNumber $targetDiskNumber
        $volumeLocks = @(
            Lock-T1OSRemovableVolumes -TargetDiskNumber $targetDiskNumber
        )
        Unlock-T1OSRemovableVolumes -Handles $volumeLocks
        $volumeLocks = @()
        Update-HostStorageCache
        $rootDriveLetter = Mount-T1OSRootForWindows `
            -TargetDiskNumber $targetDiskNumber `
            -ExpectedLabel ([string]$layout.volumeLabel)
        Write-Host "The verified T1OS USB is available in Windows as $($rootDriveLetter):\."
    }
    finally {
        if ($targetStream) {
            try {
                $targetStream.Dispose()
            }
            catch {
                Write-Warning "Could not close the failed USB write stream cleanly: $($_.Exception.Message)"
            }
        }
        if ($readbackStream) {
            try {
                $readbackStream.Dispose()
            }
            catch {
                Write-Warning "Could not close the failed USB read-back stream cleanly: $($_.Exception.Message)"
            }
        }
        if ($espVolumeStream) {
            try {
                $espVolumeStream.Dispose()
            }
            catch {
                Write-Warning "Could not close the failed EFI volume stream cleanly: $($_.Exception.Message)"
            }
        }
        if ($recoveryVolumeStream) {
            try {
                $recoveryVolumeStream.Dispose()
            }
            catch {
                Write-Warning "Could not close the failed recovery volume stream cleanly: $($_.Exception.Message)"
            }
        }
        if ($rootVolumeStream) {
            try {
                $rootVolumeStream.Dispose()
            }
            catch {
                Write-Warning "Could not close the failed root volume stream cleanly: $($_.Exception.Message)"
            }
        }
        Unlock-T1OSRemovableVolumes -Handles $volumeLocks
    }
}

if ($InspectImage) {
    if ([System.IO.Path]::GetExtension($ImagePath).ToLowerInvariant() -eq '.t1os') {
        Get-T1OSBundleLayout -Path $ImagePath | ConvertTo-Json -Depth 12 -Compress
    }
    else {
        Get-T1OSImageLayout -Path $ImagePath -RequireFilenameVersion | ConvertTo-Json -Compress
    }
    return
}

if ($ListTargets) {
    $targets = Get-T1OSUsbDisks
    $protectedTargets = Get-T1OSProtectedUsbDisks

    if ($Json) {
        $targetDetails = @($targets | ForEach-Object {
            [pscustomobject]@{
                diskNumber = [int]$_.Number
                friendlyName = ([string]$_.FriendlyName).Trim()
                serialNumber = ([string]$_.SerialNumber).Trim()
                sizeBytes = [long]$_.Size
                sizeGiB = [double][math]::Round($_.Size / 1GB, 2)
                confirmation = Get-T1OSUsbConfirmation -Disk $_
            }
        })
        $protectedDetails = @($protectedTargets | ForEach-Object {
            [pscustomobject]@{
                diskNumber = [int]$_.Number
                friendlyName = ([string]$_.FriendlyName).Trim()
                serialNumber = ([string]$_.SerialNumber).Trim()
                sizeBytes = [long]$_.Size
                sizeGiB = [double][math]::Round($_.Size / 1GB, 2)
            }
        })
        [pscustomobject]@{
            targets = $targetDetails
            protectedTargets = $protectedDetails
        } | ConvertTo-Json -Depth 4 -Compress
        return
    }

    if (-not $targets) {
        Write-Host 'No eligible non-system USB disks are attached.'
    }
    else {
        $targets | Select-Object Number,FriendlyName,SerialNumber,@{
            Name = 'SizeGiB'
            Expression = { [math]::Round($_.Size / 1GB, 2) }
        },OperationalStatus,IsOffline,IsReadOnly | Format-Table -AutoSize
        foreach ($target in $targets) {
            Write-Host "Confirmation for disk $($target.Number): $(Get-T1OSUsbConfirmation -Disk $target)"
        }
    }

    foreach ($protectedTarget in $protectedTargets) {
        Write-Host "Rejected protected disk $($protectedTarget.Number): $(([string]$protectedTarget.FriendlyName).Trim())"
    }
    Write-Host 'BIWIN NV7400 and WD My Passport devices are always rejected by the flasher.'
    return
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Managing a T1OS USB requires an elevated PowerShell session.'
}

if ([string]::IsNullOrWhiteSpace($ImagePath)) {
    $currentVersion = (Get-Content -LiteralPath (Join-Path $projectRoot 'current_version.txt') -Raw).Trim()
    $ImagePath = Join-Path $projectRoot "environment\hardware\The One OS $currentVersion.t1os"
}
$ImagePath = [System.IO.Path]::GetFullPath($ImagePath)
$isBundle = [System.IO.Path]::GetExtension($ImagePath).ToLowerInvariant() -eq '.t1os'

if (-not (Test-Path -LiteralPath $ImagePath -PathType Leaf)) {
    throw "The One OS installation file was not found: $ImagePath"
}
$image = Get-Item -LiteralPath $ImagePath
if ($image.Length -le 0) {
    throw 'The One OS installation file is empty.'
}

if ($isBundle) {
    $bundleContext = Open-T1OSBundle -Path $ImagePath -VerifyPayloads
    try {
        $imageLayout = $bundleContext.Layout
    }
    finally {
        $bundleContext.Archive.Dispose()
        $bundleContext.FileStream.Dispose()
    }
    if ($RequireProduction -and -not $imageLayout.production) {
        throw 'The installation bundle is not approved for end-user flashing.'
    }
}
else {
    $manifestPath = "$ImagePath.json"
    $imageLayout = Get-T1OSImageLayout -Path $ImagePath -RequireFilenameVersion:$EndUserImage

    if (-not $EndUserImage) {
        if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
            throw "Validated image manifest not found: $manifestPath"
        }

        $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
        if ($manifest.state -ne 'validated') {
            throw 'The image manifest is not in the validated state.'
        }
        if ($RequireProduction -and $manifest.production -ne $true) {
            throw 'The image is not approved for end-user flashing.'
        }
        if ([long]$manifest.bytes -ne $image.Length) {
            throw 'The image length no longer matches its validated manifest.'
        }
        if ([string]$manifest.root_filesystem -cne 'ntfs') {
            throw 'The validated image manifest does not identify an NTFS root filesystem.'
        }
        $imageJournal = $manifest.roothealth_journal
        $journalValidatorPath = Join-Path $PSScriptRoot 'validate roothealth journal.py'
        if (-not (Test-Path -LiteralPath $journalValidatorPath -PathType Leaf)) {
            throw "RootHealth journal validator not found: $journalValidatorPath"
        }
        $journalValidatorHash = (
            Get-FileHash -Algorithm SHA256 -LiteralPath $journalValidatorPath
        ).Hash.ToLowerInvariant()
        if (
            $null -eq $imageJournal -or
            [int]$imageJournal.format -ne 1 -or
            [string]$imageJournal.state -cne 'provisioned-and-validated' -or
            [string]$imageJournal.path -cne '$Extend/$RootHealth' -or
            [int64]$imageJournal.logical_bytes -ne 134217728 -or
            [string]$imageJournal.required_flags -cne '0x00002007' -or
            [string]$imageJournal.headers.state -cne 'EMPTY' -or
            -not [bool]$imageJournal.ownership.complete -or
            -not [bool]$imageJournal.ownership.unique_owner -or
            -not [bool]$imageJournal.ownership.self_nonoverlap -or
            [string]$imageJournal.provenance.validator_sha256 -cne $journalValidatorHash
        ) {
            throw 'The validated image manifest lacks its source-bound RootHealth journal attestation.'
        }
    }

    $imageHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $ImagePath).Hash.ToLowerInvariant()
    if (-not $EndUserImage -and $imageHash -ne ([string]$manifest.sha256).ToLowerInvariant()) {
        throw 'The image hash no longer matches its validated manifest.'
    }
}

$requiredBytes = if ($isBundle) {
    [long]$imageLayout.minimumTargetBytes
}
else {
    [long]$image.Length
}

$disk = Get-Disk -Number $DiskNumber -ErrorAction Stop
if ([long]$disk.Size -le 0) {
    throw 'Windows reports that this USB has no media. Physically unplug and reconnect it, refresh the target list, and try again.'
}
$friendlyName = ([string]$disk.FriendlyName).Trim()
$serialNumber = ([string]$disk.SerialNumber).Trim()
$sizeGiB = [math]::Round($disk.Size / 1GB, 2)

if ($DiskNumber -eq 0 -or $disk.IsBoot -or $disk.IsSystem) {
    throw "Disk $DiskNumber is a boot or system disk and can never be flashed."
}
if ($disk.BusType -ne 'USB') {
    throw "Disk $DiskNumber is not reported as USB; it can never be flashed by this tool."
}
if ($friendlyName -match '(?i)BIWIN\s+NV7400|WD\s+My\s+Passport|My\s+Passport') {
    throw "Protected disk model rejected: $friendlyName"
}
if ($disk.IsReadOnly) {
    throw "Disk $DiskNumber is read-only."
}
if ($disk.Size -lt $requiredBytes) {
    throw "Disk $DiskNumber is smaller than the required $([math]::Round($requiredBytes / 1GB, 2)) GiB."
}
if ($disk.Size -gt 256GB -and -not $AllowLargeUsb) {
    throw "Disk $DiskNumber is larger than 256 GB. Use -AllowLargeUsb only after independently verifying it is disposable."
}

$expectedConfirmation = Get-T1OSUsbConfirmation -Disk $disk
Write-Host "Target disk: $DiskNumber"
Write-Host "Model: $friendlyName"
Write-Host "Serial: $serialNumber"
Write-Host "Capacity: $sizeGiB GiB"
Write-Host "Image: $ImagePath"
Write-Host "Root filesystem: $($imageLayout.rootFilesystem.ToUpperInvariant())"
if ($imageLayout.volumeLabel) {
    Write-Host "USB volume label: $($imageLayout.volumeLabel)"
}
if ($isBundle) {
    Write-Host "Bundle payload: $([math]::Round($imageLayout.payloadBytes / 1GB, 2)) GiB"
    Write-Host "Minimum target: $([math]::Round($imageLayout.minimumTargetBytes / 1GB, 2)) GiB"
    Write-Host "EFI SHA-256: $($imageLayout.espHash)"
    Write-Host "Root SHA-256: $($imageLayout.rootHash)"
}
else {
    Write-Host "Image SHA-256: $imageHash"
}

Write-Host "Required confirmation: $expectedConfirmation"

if ($Confirmation -cne $expectedConfirmation) {
    throw 'The typed confirmation does not exactly match the resolved target identity.'
}

$targetDescription = "USB Disk $DiskNumber '$friendlyName' serial '$serialNumber' ($sizeGiB GiB)"
if (-not $PSCmdlet.ShouldProcess($targetDescription, "Overwrite with validated T1OS image $($image.Name)")) {
    return
}

if ($isBundle) {
    $bundleContext = Open-T1OSBundle -Path $ImagePath
    try {
        Install-T1OSBundle `
            -BundleContext $bundleContext `
            -Disk $disk `
            -SerialNumber $serialNumber
    }
    finally {
        $bundleContext.Archive.Dispose()
        $bundleContext.FileStream.Dispose()
    }
    return
}

$physicalPath = "\\.\PhysicalDrive$DiskNumber"
$bufferSize = 4MB
$buffer = [byte[]]::new($bufferSize)
$sourceStream = $null
$targetStream = $null
$readbackStream = $null
$volumeLocks = @()

try {
    if ($disk.IsOffline) {
        Set-Disk -Number $DiskNumber -IsOffline $false -ErrorAction Stop
    }
    Dismount-T1OSMountedVolumes -TargetDiskNumber $DiskNumber
    $volumeLocks = @(Lock-T1OSRemovableVolumes -TargetDiskNumber $DiskNumber)

    $writeDisk = Get-Disk -Number $DiskNumber -ErrorAction Stop
    if (
        $writeDisk.BusType -ne 'USB' -or
        $writeDisk.IsBoot -or
        $writeDisk.IsSystem -or
        ([string]$writeDisk.SerialNumber).Trim() -cne $serialNumber -or
        ([long]$writeDisk.Size) -ne ([long]$disk.Size)
    ) {
        throw 'The USB disk identity changed after volume locking; refusing to open the physical drive.'
    }

    $sourceStream = [System.IO.FileStream]::new(
        $ImagePath,
        [System.IO.FileMode]::Open,
        [System.IO.FileAccess]::Read,
        [System.IO.FileShare]::Read,
        $bufferSize,
        [System.IO.FileOptions]::SequentialScan
    )
    $targetStream = [System.IO.FileStream]::new(
        $physicalPath,
        [System.IO.FileMode]::Open,
        [System.IO.FileAccess]::Write,
        [System.IO.FileShare]::ReadWrite,
        $bufferSize,
        [System.IO.FileOptions]::WriteThrough
    )

    $written = [long]0
    $nextWriteReport = 5
    Write-Host 'Writing T1OS USB image: 0%'
    while (($count = $sourceStream.Read($buffer, 0, $buffer.Length)) -gt 0) {
        $targetStream.Write($buffer, 0, $count)
        $written += $count
        $percent = [math]::Floor(($written / $sourceStream.Length) * 100)
        Write-Progress -Activity 'Writing T1OS USB image' -Status "$written of $($sourceStream.Length) bytes" -PercentComplete $percent
        while ($percent -ge $nextWriteReport -and $nextWriteReport -le 100) {
            Write-Host "Writing T1OS USB image: $nextWriteReport%"
            $nextWriteReport += 5
        }
    }
    $targetStream.Flush($true)
    Write-Progress -Activity 'Writing T1OS USB image' -Completed
    $sourceStream.Dispose(); $sourceStream = $null
    $targetStream.Dispose(); $targetStream = $null

    $readbackStream = [System.IO.FileStream]::new(
        $physicalPath,
        [System.IO.FileMode]::Open,
        [System.IO.FileAccess]::Read,
        [System.IO.FileShare]::ReadWrite,
        $bufferSize,
        [System.IO.FileOptions]::SequentialScan
    )
    $incrementalHash = [Security.Cryptography.IncrementalHash]::CreateHash(
        [Security.Cryptography.HashAlgorithmName]::SHA256
    )
    $remaining = [long]$image.Length
    $read = [long]0
    $nextReadReport = 5
    Write-Host 'Verifying T1OS USB image: 0%'
    while ($remaining -gt 0) {
        $requested = [int][math]::Min([long]$buffer.Length, $remaining)
        $count = $readbackStream.Read($buffer, 0, $requested)
        if ($count -le 0) {
            throw 'The target disk ended before the complete image could be read back.'
        }
        $incrementalHash.AppendData($buffer, 0, $count)
        $remaining -= $count
        $read += $count
        $percent = [math]::Floor(($read / $image.Length) * 100)
        Write-Progress -Activity 'Verifying T1OS USB image' -Status "$read of $($image.Length) bytes" -PercentComplete $percent
        while ($percent -ge $nextReadReport -and $nextReadReport -le 100) {
            Write-Host "Verifying T1OS USB image: $nextReadReport%"
            $nextReadReport += 5
        }
    }
    $readbackHash = [Convert]::ToHexString($incrementalHash.GetHashAndReset()).ToLowerInvariant()
    $incrementalHash.Dispose()
    Write-Progress -Activity 'Verifying T1OS USB image' -Completed

    if ($readbackHash -ne $imageHash) {
        throw "Read-back verification failed. Expected $imageHash, received $readbackHash."
    }

    Write-Host 'Flash and full read-back verification succeeded.'
    $readbackStream.Dispose(); $readbackStream = $null
    Unlock-T1OSRemovableVolumes -Handles $volumeLocks
    $volumeLocks = @()

    $currentDisk = Get-Disk -Number $DiskNumber -ErrorAction Stop
    if ($currentDisk.IsOffline) {
        Set-Disk -Number $DiskNumber -IsOffline $false -ErrorAction Stop
    }
    Update-HostStorageCache

    $rootVolume = $null
    foreach ($attempt in 1..20) {
        try {
            $rootVolume = Get-Partition -DiskNumber $DiskNumber -PartitionNumber 3 -ErrorAction Stop |
                Get-Volume -ErrorAction Stop
            if ($rootVolume) {
                break
            }
        }
        catch {
            $rootVolume = $null
        }
        Start-Sleep -Milliseconds 250
        Update-HostStorageCache
    }
    if (-not $rootVolume) {
        throw 'The flashed NTFS root volume did not become available in Windows.'
    }
    if ([string]$rootVolume.FileSystemType -cne 'NTFS') {
        throw "The flashed root volume was expected to be NTFS, but Windows reported '$($rootVolume.FileSystemType)'."
    }

    if ($EndUserImage) {
        if ([string]$rootVolume.FileSystemLabel -cne [string]$imageLayout.volumeLabel) {
            Write-Host "Setting USB drive name to '$($imageLayout.volumeLabel)'..."
            $rootVolume | Set-Volume -NewFileSystemLabel $imageLayout.volumeLabel -ErrorAction Stop
        }
        $verifiedVolume = Get-Partition -DiskNumber $DiskNumber -PartitionNumber 3 -ErrorAction Stop |
            Get-Volume -ErrorAction Stop
        if ([string]$verifiedVolume.FileSystemLabel -cne [string]$imageLayout.volumeLabel) {
            throw "The USB drive name could not be verified as '$($imageLayout.volumeLabel)'."
        }
        $rootVolume = $verifiedVolume
        Write-Host "USB drive name verified: $($imageLayout.volumeLabel)"
    }

    $rootDriveLetter = Mount-T1OSRootForWindows `
        -TargetDiskNumber $DiskNumber `
        -ExpectedLabel ([string]$rootVolume.FileSystemLabel)
    Write-Host "Finalizing and cleanly dismounting T1OS from $($rootDriveLetter):\ for its final flush..."
    Dismount-T1OSMountedVolumes -TargetDiskNumber $DiskNumber
    $finalLocks = @(Lock-T1OSRemovableVolumes -TargetDiskNumber $DiskNumber)
    Unlock-T1OSRemovableVolumes -Handles $finalLocks
    Update-HostStorageCache
    $rootDriveLetter = Mount-T1OSRootForWindows `
        -TargetDiskNumber $DiskNumber `
        -ExpectedLabel ([string]$rootVolume.FileSystemLabel)
    Write-Host "The verified T1OS USB is available in Windows as $($rootDriveLetter):\."
}
finally {
    if ($sourceStream) { $sourceStream.Dispose() }
    if ($targetStream) { $targetStream.Dispose() }
    if ($readbackStream) { $readbackStream.Dispose() }
    foreach ($handle in $volumeLocks) {
        $bytesReturned = [uint32]0
        [void][T1OSVolumeControl]::DeviceIoControl(
            $handle, [T1OSVolumeControl]::FSCTL_UNLOCK_VOLUME,
            [IntPtr]::Zero, 0, [IntPtr]::Zero, 0,
            [ref]$bytesReturned, [IntPtr]::Zero
        )
        $handle.Dispose()
    }
}
