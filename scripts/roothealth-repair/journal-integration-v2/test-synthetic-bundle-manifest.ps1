[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$ScriptsRoot
)

$incrementalTestBootstrap = Join-Path $PSScriptRoot '..\..\incremental test.ps1'
if (Test-Path -LiteralPath $incrementalTestBootstrap -PathType Leaf) {
    . $incrementalTestBootstrap
    if (Invoke-T1OSIncrementalTestGuard -ScriptPath $PSCommandPath -BoundParameters $PSBoundParameters -UnboundArguments $args) { return }
}
$ErrorActionPreference = 'Stop'
$ScriptsRoot = [System.IO.Path]::GetFullPath($ScriptsRoot)
$flash = Join-Path $ScriptsRoot 'flash hardware usb.ps1'
$validator = Join-Path $ScriptsRoot 'validate roothealth journal.py'
foreach ($required in @($flash, $validator)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Synthetic bundle test input not found: $required"
    }
}
$work = Join-Path ([System.IO.Path]::GetTempPath()) (
    '.rh-journal-manifest-' + [guid]::NewGuid().ToString('N')
)
$bundle = Join-Path $work 'The One OS 0.3.t1os'
$esp = Join-Path $work 'esp.img'
$root = Join-Path $work 'root.ntfs.img'
$manifestPath = Join-Path $work 'manifest.json'

function Write-Manifest {
    param([Parameter(Mandatory)]$Manifest)
    [System.IO.File]::WriteAllText(
        $manifestPath,
        ($Manifest | ConvertTo-Json -Depth 12) + [Environment]::NewLine,
        [System.Text.UTF8Encoding]::new($false)
    )
}

function Replace-BundleManifest {
    param([Parameter(Mandatory)]$Manifest)
    Write-Manifest -Manifest $Manifest
    $stream = [System.IO.FileStream]::new(
        $bundle,
        [System.IO.FileMode]::Open,
        [System.IO.FileAccess]::ReadWrite,
        [System.IO.FileShare]::None
    )
    $archive = [System.IO.Compression.ZipArchive]::new(
        $stream,
        [System.IO.Compression.ZipArchiveMode]::Update,
        $false
    )
    try {
        $archive.GetEntry('manifest.json').Delete()
        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
            $archive,
            $manifestPath,
            'manifest.json',
            [System.IO.Compression.CompressionLevel]::Optimal
        ) | Out-Null
    }
    finally {
        $archive.Dispose()
        $stream.Dispose()
    }
}

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
New-Item -ItemType Directory -Path $work | Out-Null
try {
    $espStream = [System.IO.File]::OpenWrite($esp)
    $espStream.SetLength(512MB)
    $espStream.Dispose()
    $rootStream = [System.IO.File]::OpenWrite($root)
    $rootStream.SetLength(1GB)
    $rootStream.Dispose()
    $espHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $esp).Hash.ToLowerInvariant()
    $rootHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $root).Hash.ToLowerInvariant()
    $validatorHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $validator).Hash.ToLowerInvariant()
    $journal = [ordered]@{
        format = 1
        state = 'resize-preserved-and-validated'
        path = '$Extend/$RootHealth'
        volume_serial = '0123456789ABCDEF'
        journal_uuid = '01234567-89ab-4cde-8f01-23456789abcd'
        mft_record = 64
        mft_sequence = 1
        logical_bytes = 134217728
        required_flags = '0x00002007'
        record_locator = '64:1'
        identity_sha256 = ('1' * 64)
        run_policy = 'VALIDATED_AFTER_RESIZE'
        provisioning_run_count = 1
        headers = [ordered]@{
            state = 'EMPTY'; selected_generation = 2; slot_generations = @(1, 2)
            max_entry_count = 4096; entry_area_zero_sha256 = ('2' * 64)
        }
        ownership = [ordered]@{
            complete = $true; unique_owner = $true; self_nonoverlap = $true
            journal_clusters = 32768
        }
        provisioning_write_exclusion = [ordered]@{ range_count = 6; sha256 = ('3' * 64) }
        final_validation = [ordered]@{
            report_sha256 = ('4' * 64); run_count = 1
            write_exclusion = [ordered]@{ range_count = 6; sha256 = ('3' * 64) }
            ownership = [ordered]@{
                complete = $true; unique_owner = $true; self_nonoverlap = $true
                journal_clusters = 32768
            }
            headers = [ordered]@{
                state = 'EMPTY'; selected_generation = 2; slot_generations = @(1, 2)
                max_entry_count = 4096; entry_area_zero_sha256 = ('2' * 64)
            }
        }
        resize_validation = [ordered]@{
            report_sha256 = ('5' * 64); run_count = 1
            write_exclusion = [ordered]@{ range_count = 6; sha256 = ('6' * 64) }
            ownership = [ordered]@{
                complete = $true; unique_owner = $true; self_nonoverlap = $true
                journal_clusters = 32768
            }
            headers = [ordered]@{
                state = 'EMPTY'; selected_generation = 2; slot_generations = @(1, 2)
                max_entry_count = 4096; entry_area_zero_sha256 = ('2' * 64)
            }
        }
        provenance = [ordered]@{
            validator_sha256 = $validatorHash
            ntfscp_binary_sha256 = ('7' * 64)
            ntfscp_manifest_sha256 = ('8' * 64)
            ntfs_next_commit = 'd4f481df6926557f7b18b471a43313652dec6f7e'
            ntfs_next_archive_sha256 = '13dc944f477997ae4ecd89e3d0fdaa34b74ebbc1f7beb675657624ed6289eff5'
            seed_report_sha256 = ('9' * 64)
            provision_report_sha256 = ('a' * 64)
            validation_report_sha256 = ('b' * 64)
        }
    }
    $manifest = [ordered]@{
        format = 't1os-usb-bundle'; format_version = 1; state = 'validated'
        version = '0.3'; drive_version = '0.3'; volume_label = 'T1OS 0.3'
        root_uuid = '0123456789ABCDEF'; root_filesystem = 'ntfs'
        partition_table = 'gpt'; windows_native_root = $true
        windows_autorun = 'autorun.inf'; windows_drive_icon = 'the one\resources\t1os-drive.ico'
        minimum_target_bytes = 1612709888
        source_image = 'synthetic.img'; source_image_bytes = 2147483648
        source_image_sha256 = ('c' * 64); production = $false; secure_boot = $false
        kernel_release = 'synthetic'; roothealth_journal = $journal
        esp = [ordered]@{
            entry = 'esp.img'; bytes = 536870912; sha256 = $espHash
            filesystem = 'fat32'; label = 'T1OS_EFI'
        }
        root = [ordered]@{
            entry = 'root.ntfs.img'; bytes = 1073741824; sha256 = $rootHash
            filesystem = 'ntfs'; label = 'T1OS 0.3'; uuid = '0123456789ABCDEF'
            growth_reserve_mib = 256
        }
    }
    Write-Manifest -Manifest $manifest
    $archiveStream = [System.IO.FileStream]::new(
        $bundle,
        [System.IO.FileMode]::CreateNew
    )
    $archive = [System.IO.Compression.ZipArchive]::new(
        $archiveStream,
        [System.IO.Compression.ZipArchiveMode]::Create,
        $false
    )
    try {
        foreach ($payload in @(
            @($manifestPath, 'manifest.json'),
            @($esp, 'esp.img'),
            @($root, 'root.ntfs.img')
        )) {
            [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
                $archive,
                $payload[0],
                $payload[1],
                [System.IO.Compression.CompressionLevel]::Optimal
            ) | Out-Null
        }
    }
    finally {
        $archive.Dispose()
        $archiveStream.Dispose()
    }
    $layout = (& pwsh -NoProfile -ExecutionPolicy Bypass -File $flash `
        -InspectImage -ImagePath $bundle) | ConvertFrom-Json
    if (
        -not $layout.valid -or
        $layout.roothealthJournal.state -cne 'resize-preserved-and-validated'
    ) {
        throw 'valid synthetic bundle did not retain its RootHealth journal attestation'
    }
    $manifest.roothealth_journal.state = 'provisioned-and-validated'
    Replace-BundleManifest -Manifest $manifest
    & pwsh -NoProfile -ExecutionPolicy Bypass -File $flash `
        -InspectImage -ImagePath $bundle *> $null
    if ($LASTEXITCODE -eq 0) {
        throw 'bundle parser accepted the pre-resize RootHealth journal state'
    }
    $manifest.roothealth_journal.state = 'resize-preserved-and-validated'
    $manifest.roothealth_journal.resize_validation.ownership.unique_owner = $false
    Replace-BundleManifest -Manifest $manifest
    & pwsh -NoProfile -ExecutionPolicy Bypass -File $flash `
        -InspectImage -ImagePath $bundle *> $null
    if ($LASTEXITCODE -eq 0) {
        throw 'bundle parser accepted ambiguous RootHealth journal ownership'
    }
    'SYNTHETIC_BUNDLE_MANIFEST_PASS positive=1 negative=2'
}
finally {
    Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
}
