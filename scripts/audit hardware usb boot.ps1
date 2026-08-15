[CmdletBinding()]
param(
    [ValidatePattern('^[A-Za-z]$')]
    [string]$RootDrive = 'D',

    [string]$ReportPath,

    [switch]$Elevated
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Path $PSScriptRoot -Parent
if ([string]::IsNullOrWhiteSpace($ReportPath)) {
    $ReportPath = Join-Path $projectRoot 'environment\hardware\physical-usb-boot-audit.json'
}
$ReportPath = [System.IO.Path]::GetFullPath($ReportPath)

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator
    )
}

if (-not (Test-IsAdministrator)) {
    if ($Elevated) {
        throw 'The elevated USB boot audit does not have administrator rights.'
    }
    $hostExecutable = (Get-Process -Id $PID).Path
    $arguments = @(
        '-NoLogo',
        '-NoProfile',
        '-NonInteractive',
        '-ExecutionPolicy',
        'Bypass',
        '-File',
        ('"' + $PSCommandPath.Replace('"', '""') + '"'),
        '-RootDrive',
        $RootDrive,
        '-ReportPath',
        ('"' + $ReportPath.Replace('"', '""') + '"'),
        '-Elevated'
    ) -join ' '
    $process = Start-Process -FilePath $hostExecutable -Verb RunAs `
        -WindowStyle Hidden -ArgumentList $arguments -Wait -PassThru
    if ($process.ExitCode -ne 0) {
        throw "Elevated USB boot audit failed with exit code $($process.ExitCode)."
    }
    Get-Content -LiteralPath $ReportPath -Raw
    exit 0
}

$rootLetter = $RootDrive.ToUpperInvariant()
$rootVolume = Get-Volume -DriveLetter $rootLetter -ErrorAction Stop
$rootPartition = Get-Partition -DriveLetter $rootLetter -ErrorAction Stop
$disk = Get-Disk -Number $rootPartition.DiskNumber -ErrorAction Stop
$efiPartitions = @(
    Get-Partition -DiskNumber $disk.Number -ErrorAction Stop |
        Where-Object {
            $_.GptType -ceq '{c12a7328-f81f-11d2-ba4b-00a0c93ec93b}'
        }
)
if (
    [string]$disk.BusType -cne 'USB' -or
    $disk.IsBoot -or
    $disk.IsSystem -or
    [string]$rootVolume.FileSystemType -cne 'NTFS' -or
    -not ([string]$rootVolume.FileSystemLabel).StartsWith(
        'T1OS',
        [StringComparison]::OrdinalIgnoreCase
    ) -or
    $efiPartitions.Count -ne 1
) {
    throw "$rootLetter`: is not an unambiguous T1OS GPT USB target."
}

$efi = $efiPartitions[0]
$efiRoot = [string]($efi.AccessPaths | Where-Object {
    $_ -like '\\?\Volume{*}\'
} | Select-Object -First 1)
$temporaryAccessPath = $null
if ([string]::IsNullOrWhiteSpace($efiRoot)) {
    $usedLetters = @(
        Get-Volume -ErrorAction Stop |
            Where-Object DriveLetter |
            ForEach-Object { ([string]$_.DriveLetter).ToUpperInvariant() }
    )
    $efiLetter = @('Z', 'Y', 'X', 'W', 'V') |
        Where-Object { $_ -notin $usedLetters } |
        Select-Object -First 1
    if (-not $efiLetter) {
        throw 'No temporary drive letter is available for the EFI audit.'
    }
    $temporaryAccessPath = "$efiLetter`: \".Replace(' ', '')
    Add-PartitionAccessPath -DiskNumber $disk.Number `
        -PartitionNumber $efi.PartitionNumber `
        -AccessPath $temporaryAccessPath
    $efiRoot = $temporaryAccessPath
}

function Get-FileAudit {
    param(
        [Parameter(Mandatory)]
        [string]$RelativePath
    )

    $path = Join-Path $efiRoot $RelativePath
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        return [ordered]@{
            path = $RelativePath.Replace('\', '/')
            present = $false
            bytes = $null
            sha256 = $null
            last_write_utc = $null
        }
    }
    $item = Get-Item -LiteralPath $path -Force
    return [ordered]@{
        path = $RelativePath.Replace('\', '/')
        present = $true
        bytes = [long]$item.Length
        sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash.ToLowerInvariant()
        last_write_utc = $item.LastWriteTimeUtc.ToString('o')
    }
}

try {
    $files = @(
        'EFI\BOOT\BOOTX64.EFI',
        'EFI\BOOT\grub.cfg',
        'boot\grub\grub.cfg',
        'boot\grub\x86_64-efi\normal.mod',
        'boot\grub\fonts\unicode.pf2',
        'boot\vmlinuz-hardware',
        'boot\initramfs-hardware',
        'T1OS\image-manifest.json'
    ) | ForEach-Object { Get-FileAudit -RelativePath $_ }

    $efiVolume = $efi | Get-Volume -ErrorAction SilentlyContinue
    $efiFsInfo = @(& fsutil.exe fsinfo volumeinfo $efiRoot 2>&1) -join "`n"
    $efiSerial = $null
    if ($efiFsInfo -match '(?im)^Volume Serial Number\s*:\s*(\S+)\s*$') {
        $efiSerial = $Matches[1]
    }
    $efiBootConfigPath = Join-Path $efiRoot 'EFI\BOOT\grub.cfg'
    $grubConfigPath = Join-Path $efiRoot 'boot\grub\grub.cfg'
    $efiBootConfig = if (Test-Path -LiteralPath $efiBootConfigPath -PathType Leaf) {
        Get-Content -LiteralPath $efiBootConfigPath -Raw
    }
    $grubConfig = if (Test-Path -LiteralPath $grubConfigPath -PathType Leaf) {
        Get-Content -LiteralPath $grubConfigPath -Raw
    }

    $report = [ordered]@{
        format = 1
        audited_at_utc = [DateTime]::UtcNow.ToString('o')
        disk = [ordered]@{
            number = [int]$disk.Number
            friendly_name = [string]$disk.FriendlyName
            serial_number = ([string]$disk.SerialNumber).Trim()
            bytes = [long]$disk.Size
            partition_style = [string]$disk.PartitionStyle
        }
        root = [ordered]@{
            drive = "$rootLetter`:"
            label = [string]$rootVolume.FileSystemLabel
            bytes = [long]$rootVolume.Size
            partition_guid = ([string]$rootPartition.Guid).Trim('{}').ToLowerInvariant()
        }
        efi = [ordered]@{
            bytes = [long]$efi.Size
            partition_guid = ([string]$efi.Guid).Trim('{}').ToLowerInvariant()
            filesystem = [string]$efiVolume.FileSystemType
            label = [string]$efiVolume.FileSystemLabel
            unique_id = [string]$efiVolume.UniqueId
            volume_serial = $efiSerial
            fallback_config = $efiBootConfig
            grub_config = $grubConfig
            files = $files
        }
    }
    $directory = Split-Path -Path $ReportPath -Parent
    if (-not (Test-Path -LiteralPath $directory -PathType Container)) {
        New-Item -ItemType Directory -Path $directory | Out-Null
    }
    $report | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $ReportPath `
        -Encoding utf8NoBOM
}
finally {
    if ($temporaryAccessPath) {
        Remove-PartitionAccessPath -DiskNumber $disk.Number `
            -PartitionNumber $efi.PartitionNumber `
            -AccessPath $temporaryAccessPath -ErrorAction SilentlyContinue
    }
}

$report | ConvertTo-Json -Depth 6
