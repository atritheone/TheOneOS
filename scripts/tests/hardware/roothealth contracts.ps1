[CmdletBinding()]
param()

$incrementalTestBootstrap = Join-Path $PSScriptRoot '..\..\incremental test.ps1'
if (Test-Path -LiteralPath $incrementalTestBootstrap -PathType Leaf) {
    . $incrementalTestBootstrap
    if (Invoke-T1OSIncrementalTestGuard -ScriptPath $PSCommandPath -BoundParameters $PSBoundParameters -UnboundArguments $args) { return }
}
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..\..')).Path

function ConvertTo-T1OSWslPath {
    param([Parameter(Mandatory)][string]$Path)

    $converted = & wsl.exe -d Ubuntu --exec wslpath -a $Path
    if ($LASTEXITCODE -ne 0 -or -not $converted) {
        throw "Could not translate test path for WSL: $Path"
    }
    return ([string]($converted | Select-Object -First 1)).Trim()
}

$wslProjectRoot = ConvertTo-T1OSWslPath -Path $projectRoot
$initScript = Join-Path $projectRoot 'source\entry\init\init hardware.sh'
$angelContract = Join-Path $projectRoot 'source\entry\init\ANGEL.md'
$angelVoiceTest = Join-Path $projectRoot 'scripts\tests\test angel voice.py'
$angelRecoveryTest = Join-Path $projectRoot 'scripts\tests\test angel recovery.ps1'
$initramfsBuilder = Join-Path $projectRoot 'scripts\build\build hardware initramfs.ps1'
$bootPolicyBuilder = Join-Path $projectRoot 'scripts\build\build boot protected roots.py'
$ntfsCheckerBuilder = Join-Path $projectRoot 'scripts\build\build roothealth.ps1'
$ntfsCheckerTest = Join-Path $projectRoot 'scripts\tests\test roothealth.ps1'
$ntfsChecker = Join-Path $projectRoot 'environment\hardware\tools\roothealth'
$ntfsCheckerMetadata = Join-Path $projectRoot 'environment\hardware\tools\roothealth.json'
$ntfsCheckerLicense = Join-Path $projectRoot 'environment\hardware\tools\roothealth.COPYING'
$ntfsCheckerSourceArchive = Join-Path $projectRoot 'environment\hardware\tools\roothealth-source.tar.gz'
$ntfsCheckerProductPatch = Join-Path $projectRoot 'source\entry\roothealth\0001-roothealth-read-only-checker.patch'
$ntfsCheckerSecurityPatch = Join-Path $projectRoot 'source\entry\roothealth\0002-ntfs-3g-2026.7.7-index-hardening.patch'
$ntfsCheckerVerdictPatch = Join-Path $projectRoot 'source\entry\roothealth\0003-roothealth-verdict-hardening.patch'
$imageBuilder = Join-Path $projectRoot 'scripts\create hardware usb image.ps1'
$bundleBuilder = Join-Path $projectRoot 'scripts\create hardware usb bundle.ps1'
$bundleValidator = Join-Path $projectRoot 'scripts\test hardware usb bundle.ps1'
$flashScript = Join-Path $projectRoot 'scripts\flash hardware usb.ps1'
$imageValidator = Join-Path $projectRoot 'scripts\validate hardware usb image.ps1'
$productionPreparer = Join-Path $projectRoot 'scripts\build\prepare prod build.ps1'
$hardwareUsbWorkflow = Join-Path $projectRoot 'scripts\build\build hardware usb.ps1'
$kernelBuilder = Join-Path $projectRoot 'scripts\build\build hardware kernel.ps1'
$graphicsKernelBuilder = Join-Path $projectRoot 'scripts\build\build graphics kernel.ps1'
$rootPushScript = Join-Path $projectRoot 'scripts\deployment\push to disk.ps1'
$hardwareKernelPushScript = Join-Path $projectRoot 'scripts\deployment\push hardware kernel to usb.ps1'
$grubScript = Join-Path $projectRoot 'source\entry\grub\grub hardware 0.2.cfg'
$encryptedGrubScript = Join-Path $projectRoot 'source\entry\grub\grub hardware encrypted 0.2.cfg'
$grubTheme = Join-Path $projectRoot 'source\entry\grub\t1os hardware theme.txt'
$grubBackground = Join-Path $projectRoot 'source\entry\grub\t1os black background.png.base64'
$kernelConfig = Join-Path $projectRoot 'source\entry\kernel\T10Skernel hardware 0.19 settings.txt'
$kernelPolicy = Join-Path $projectRoot 'source\entry\kernel\t1os_lsm.c'
$goddessScript = Join-Path $projectRoot 'source\build software\GODDESS\GODDESS.py'
$expanseScript = Join-Path $projectRoot 'source\build software\expanse\expanse.py'
$authenticationBroker = Join-Path $projectRoot 'source\build software\broker\broker.py'
$inputServer = Join-Path $projectRoot 'source\build software\input\inputserver.py'
$hardwareRoot = Join-Path $projectRoot 'environment\hardware'
$kernel = Join-Path $hardwareRoot 'boot\vmlinuz-hardware'
$initramfs = Join-Path $hardwareRoot 'boot\initramfs-hardware'
$pythonManifest = Join-Path $projectRoot 'source\software\python\manifest.json'
$pythonRelease = [string](
    Get-Content -LiteralPath $pythonManifest -Raw | ConvertFrom-Json
).release
if ($pythonRelease -notmatch '^[0-9A-Za-z][0-9A-Za-z._+-]{0,127}$') {
    throw 'The canonical Python manifest has an invalid release identifier.'
}
$firmwareArchive = Join-Path $hardwareRoot 'firmware.tar.zst'
$firmwareManifest = Join-Path $hardwareRoot 't1os-firmware-manifest.json'
$moduleArchive = Join-Path $hardwareRoot 'modules.tar.zst'
$driverServer = Join-Path $projectRoot 'source\build software\drivers\driverserver.py'
$operationsScript = Join-Path $projectRoot 'source\build software\operations\operations.py'
$moduleLoader = Join-Path $projectRoot 'source\drivers\tools\modprobe'
$driverPolicy = Join-Path $projectRoot 'source\drivers\settings\policy.json'
$desktopCompatibility = Join-Path $projectRoot 'source\drivers\settings\desktop compatibility.json'
$compatibilityValidator = Join-Path $projectRoot 'scripts\audits\validate hardware compatibility.ps1'
$driverRuntime = Join-Path $projectRoot 'source\drivers\settings\runtime.json'
$networkServer = Join-Path $projectRoot 'source\build software\network\network.py'
$wirelessEngine = Join-Path $projectRoot 'source\software\network\wireless-engine'
$networkLoader = Join-Path $projectRoot 'source\catalogue\network\ld-linux-x86-64.so.2'
$networkCertificates = Join-Path $projectRoot 'source\settings\network\cacerts.pem'
$graphicsCatalogueRoot = Join-Path $projectRoot 'source\catalogue\graphics'
$graphicsCatalogue = Join-Path $graphicsCatalogueRoot 'catalogue.json'
$intelVaapi = Join-Path $graphicsCatalogueRoot 'drivers\iHD_drv_video.so'
$r600Vaapi = Join-Path $graphicsCatalogueRoot 'drivers\r600_drv_video.so'
$radeonsiVaapi = Join-Path $graphicsCatalogueRoot 'drivers\radeonsi_drv_video.so'
$nouveauVaapi = Join-Path $graphicsCatalogueRoot 'drivers\nouveau_drv_video.so'
$virtioVaapi = Join-Path $graphicsCatalogueRoot 'drivers\virtio_gpu_drv_video.so'
$vmwgfxVaapi = Join-Path $graphicsCatalogueRoot 'drivers\vmwgfx_drv_video.so'
$nouveauDrm = Join-Path $graphicsCatalogueRoot 'libdrm_nouveau.so.2'
$nouveauVulkan = Join-Path $graphicsCatalogueRoot 'libvulkan_nouveau.so'
$vulkanLoader = Join-Path $projectRoot 'source\catalogue\graphics\libvulkan.so.1'
$nvidiaEgl = Join-Path $graphicsCatalogueRoot 'nvidia\libEGL.so.1'
$nvidiaGles = Join-Path $graphicsCatalogueRoot 'nvidia\libGLESv2.so.2'
$nvidiaEglVendor = Join-Path $graphicsCatalogueRoot 'nvidia\egl_vendor.d\10_nvidia.json'
$nvidiaGbmBackend = Join-Path $graphicsCatalogueRoot 'nvidia\gbm\nvidia-drm_gbm.so'
$nvidiaPathProvider = Join-Path $graphicsCatalogueRoot 'nvidia\t1os-nvidia-path-provider.so'
$nvidiaPathProviderSource = Join-Path $projectRoot 'source\entry\graphics\t1os_nvidia_path_provider.c'
$nvidiaRuntime = Join-Path $graphicsCatalogueRoot 'nvidia\runtime.json'
$nvidiaVaapi = Join-Path $graphicsCatalogueRoot 'drivers\nvidia_drv_video.so'
$nvidiaCuda = Join-Path $graphicsCatalogueRoot 'nvidia\libcuda.so.1'
$nvidiaNvcuvid = Join-Path $graphicsCatalogueRoot 'nvidia\libnvcuvid.so.1'
$nvidiaPtxjit = Join-Path $graphicsCatalogueRoot 'nvidia\libnvidia-ptxjitcompiler.so.1'
$gstreamerCore = Join-Path $graphicsCatalogueRoot 'libgstreamer-1.0.so.0'
$gstreamerBase = Join-Path $graphicsCatalogueRoot 'libgstbase-1.0.so.0'
$gstreamerCodecParsers = Join-Path $graphicsCatalogueRoot 'libgstcodecparsers-1.0.so.0'
$mediaDecodeService = Join-Path $projectRoot 'source\software\audio\t1-media-decoderd'
$mediaDecodeWorker = Join-Path $projectRoot 'source\software\audio\t1-video-decode'
$audioRuntimeManifest = Join-Path $projectRoot 'source\software\audio\manifest.json'
$mediaDecodeServiceSource = Join-Path $projectRoot 'source\native\video\t1_media_decoded.c'
$mediaDecodeWorkerSource = Join-Path $projectRoot 'source\native\video\t1_media_decode_worker.c'
$mediaDecodeProtocolSource = Join-Path $projectRoot 'source\native\video\t1_media_decode_protocol.h'
$chromiumServer = Join-Path $projectRoot 'source\build software\chromium\chromium.py'
$chromiumEngine = Join-Path $projectRoot 'source\software\chromium\program\chrome'
$chromiumSandbox = Join-Path $projectRoot 'source\software\chromium\program\chrome-sandbox'
$chromiumLibc = Join-Path $projectRoot 'source\software\chromium\libraries\libc.so.6'
$chromiumLibasound = Join-Path $projectRoot 'source\software\chromium\libraries\libasound.so.2'
$chromiumProvider = Join-Path $projectRoot 'source\software\chromium\t1os-path-provider.so'
$chromiumProviderSource = Join-Path $projectRoot 'source\entry\chromium\t1os_path_provider.c'
$chromiumInputBridge = Join-Path $projectRoot 'source\software\chromium\tools\t1os-xinput'
$chromiumInputBridgeSource = Join-Path $projectRoot 'source\entry\chromium\t1os_xinput.c'
$chromiumWindowManager = Join-Path $projectRoot 'source\software\chromium\tools\t1os-xwm'
$chromiumWindowManagerSource = Join-Path $projectRoot 'source\entry\chromium\t1os_xwm.c'
$windowServer = Join-Path $projectRoot 'source\build software\windows\windowserver.py'
$brickScript = Join-Path $projectRoot 'source\build software\brick\brick.py'
$chromiumSubprocess = Join-Path $projectRoot 'source\software\chromium\tools\t1os-chrome-subprocess'
$chromiumSubprocessSource = Join-Path $projectRoot 'source\entry\chromium\t1os_chrome_subprocess.c'
$runtimePathContract = Join-Path $projectRoot 'source\settings\runtime paths.json'
$ntfsCheckerBuilderText = Get-Content -LiteralPath $ntfsCheckerBuilder -Raw
foreach ($requiredText in @(
    'd4f481df6926557f7b18b471a43313652dec6f7e',
        "`$checkerVersion = '0.5.2'",
    'development\roothealth\engine',
    '-fstack-protector-strong -fPIE',
    '-D_FORTIFY_SOURCE=3',
    '-Wl,-z,relro,-z,now,-pie',
    '[ "$needed" = libc.so.6 ]',
    'roothealth-source.tar.gz',
    'corresponding_source'
)) {
    if (-not $ntfsCheckerBuilderText.Contains($requiredText)) {
        throw "The roothealth builder is missing a pinned or hardened build control: $requiredText"
    }
}

try {
    $ntfsCheckerMetadataObject = Get-Content -Raw -LiteralPath $ntfsCheckerMetadata |
        ConvertFrom-Json
}
catch {
    throw "The roothealth build metadata is malformed: $($_.Exception.Message)"
}
if (
    [int]$ntfsCheckerMetadataObject.format -ne 2 -or
    [string]$ntfsCheckerMetadataObject.product -cne 'roothealth' -or
    [string]$ntfsCheckerMetadataObject.version -cne '0.5.2' -or
    [string]$ntfsCheckerMetadataObject.mode -cne 'qualified-repair' -or
    [string]$ntfsCheckerMetadataObject.upstream.commit -cne 'd4f481df6926557f7b18b471a43313652dec6f7e' -or
    @($ntfsCheckerMetadataObject.enabled_policies) -notcontains 'cluster-bitmap-exhaustive-v1' -or
    @($ntfsCheckerMetadataObject.enabled_policies) -notcontains 'operations-registry-resident-i30-v1' -or
    @($ntfsCheckerMetadataObject.enabled_policies) -notcontains 'mft-bitmap-full-ledger-v1' -or
    @($ntfsCheckerMetadataObject.enabled_policies) -notcontains 'index-bitmap-set-only-v1' -or
    @($ntfsCheckerMetadataObject.recovery_verified_actions) -notcontains 11 -or
    @($ntfsCheckerMetadataObject.recovery_verified_actions) -notcontains 13 -or
    @($ntfsCheckerMetadataObject.recovery_verified_actions) -notcontains 22 -or
    @($ntfsCheckerMetadataObject.recovery_verified_actions).Count -lt 8 -or
    @($ntfsCheckerMetadataObject.build.runtime_dependencies).Count -ne 1 -or
    [string]$ntfsCheckerMetadataObject.build.runtime_dependencies[0] -cne 'libc.so.6' -or
    [string]$ntfsCheckerMetadataObject.outputs.binary.sha256 -cne (
        Get-FileHash -Algorithm SHA256 -LiteralPath $ntfsChecker
    ).Hash.ToLowerInvariant() -or
    [string]$ntfsCheckerMetadataObject.outputs.license.sha256 -cne (
        Get-FileHash -Algorithm SHA256 -LiteralPath $ntfsCheckerLicense
    ).Hash.ToLowerInvariant() -or
    [string]$ntfsCheckerMetadataObject.outputs.corresponding_source.sha256 -cne (
        Get-FileHash -Algorithm SHA256 -LiteralPath $ntfsCheckerSourceArchive
    ).Hash.ToLowerInvariant()
) {
    throw 'The roothealth build metadata does not attest its pinned source and outputs.'
}

$ntfsCheckerProductPatchText = Get-Content -LiteralPath $ntfsCheckerProductPatch -Raw
foreach ($requiredText in @(
    'NTFS_MNT_FS_NO_REPAIR | NTFS_MNT_RDONLY',
    't1os_check_root_identity',
    't1os_write_report',
    'writes_attempted',
    'The NTFS volume is dirty'
)) {
    if (-not $ntfsCheckerProductPatchText.Contains($requiredText)) {
        throw "The T1OS NTFS product patch is missing read-only health behavior: $requiredText"
    }
}

$ntfsCheckerSecurityPatchText = Get-Content -LiteralPath $ntfsCheckerSecurityPatch -Raw
foreach ($requiredText in @(
    'ntfs_ie_stream_inconsistent',
    'index_block_size',
    'Last entry in index root overflows',
    'Invalid tail_size',
    'MAX_PARENT_VCN',
    'ntfs_mapping_pair_sign_extend',
    '__builtin_add_overflow(vcn',
    '__builtin_add_overflow(lcn',
    'finish_compressed_sb',
    'cb = cb_sb_end',
    'A phrase token needs two input bytes'
)) {
    if (-not $ntfsCheckerSecurityPatchText.Contains($requiredText)) {
        throw "The T1OS NTFS security patch is missing a 2026.7.7 corrupt-input hardening: $requiredText"
    }
}

$ntfsCheckerVerdictPatchText = Get-Content -LiteralPath $ntfsCheckerVerdictPatch -Raw
foreach ($requiredText in @(
    '#define T1OS_EXIT_CLEAN',
    '#define T1OS_EXIT_UNSAFE',
    '#define T1OS_EXIT_IO',
    '#define T1OS_EXIT_WRONG_ROOT',
    '#define T1OS_EXIT_INTERNAL',
    '"check",',
    'NTFS_MNT_FORENSIC',
    't1os_check_logfile_state',
    'status = ntfsck_check_backup_boot(vol)',
    'status = ntfsck_scan_mft_records(vol)',
    'status = ntfsck_scan_index_entries(vol)',
    'status = ntfsck_check_mft_records(vol)',
    'if (fsck_fixes)',
    'ret = T1OS_EXIT_INTERNAL'
)) {
    if (-not $ntfsCheckerVerdictPatchText.Contains($requiredText)) {
        throw "The T1OS NTFS verdict patch is missing a fail-closed check-only behavior: $requiredText"
    }
}

$initramfsBuilderText = Get-Content -LiteralPath $initramfsBuilder -Raw
foreach ($requiredText in @(
    'outputs.manifest_sha256',
    'Get-FileHash -Algorithm SHA256',
    '$pythonVerifier',
    '& $pythonVerifier',
    '$previousIncrementalScript = $env:T1OS_INCREMENTAL_ACTIVE_SCRIPT',
    '$env:T1OS_INCREMENTAL_ACTIVE_SCRIPT = ''scripts/tests/test python runtime.ps1''',
    '$env:T1OS_INCREMENTAL_ACTIVE_SCRIPT = $previousIncrementalScript',
    '$verificationJson | ConvertFrom-Json',
    '[string]$verificationObject.release -cne [string]$manifestObject.release',
    '$bootPolicyBuilder',
    't1os-boot-protected-roots',
    "boot_policy.get('roots')",
    'did not confirm the locked initramfs payload',
    '$ntfsCheckerBuilder',
    '& $ntfsCheckerBuilder',
    'cp -L -- "$ntfs_checker" "$rootfs/sbin/roothealth"',
    'cp -- "$recovery_script" "$rootfs/angel-recovery"',
    'source\entry\recoveryauth\recoveryauth.c',
    '"$rootfs/sbin/recoveryauth"',
    '-Wl,-l:libargon2.so.1 -lcrypto',
    "grep -qx 'angel-recovery'",
    "grep -qx 'sbin/roothealth'",
    "grep -qx 'sbin/recoveryauth'",
    'protected-roots.tsv',
    'profiled-python-entrypoints.tsv',
    'profiled_python_entrypoints',
    'validate_python_mode',
    't1os-install-tree-sha256-v2',
    'Independent boot protected-root inventories are missing',
    'exclude_generated_bytecode',
    'mktemp -d /var/tmp/t1os-hardware-initramfs.XXXXXX',
    'find "$early" "$rootfs" -type d -exec chmod 0755',
    "touch -h -d '@0'",
    '--reproducible',
    'cpio --numeric-uid-gid -tv',
    'validate_archive_modes early',
    'validate_archive_modes main',
    'mv -f -- "$output_tmp" "$output"',
    "('image_catalogue', 'source/catalogue/image', '/the one/catalogue/image', False)",
    "('build_software', 'source/build software', '/the one/build', True)",
    "('boot', 'source/boot', '/boot', True)",
    "('virtualbox_software', 'source/software/virtualbox', '/the one/software/virtualbox', True)",
    "('manifest.json', len(manifest_bytes), manifest_digest, '0444')",
    'chmod 0444 "$rootfs/protected-roots.tsv"',
    "grep -qx 'protected-roots.tsv'"
)) {
    if (-not $initramfsBuilderText.Contains($requiredText)) {
        throw "The hardware initramfs builder is missing protected-root attestation behavior: $requiredText"
    }
}
foreach ($forbiddenText in @(
    'python-release.sha256',
    'rootfs="$stage/rootfs"',
    'early="$stage/early"',
    'sbin/ntfsfix',
    'libntfs-3g'
)) {
    if ($initramfsBuilderText.Contains($forbiddenText)) {
        throw "The hardware initramfs builder still uses the obsolete Python-only attestation: $forbiddenText"
    }
}

$imageBuilderText = Get-Content -LiteralPath $imageBuilder -Raw
foreach ($requiredText in @(
    "Join-Path `$projectRoot 'current_version.txt'",
    '$rootVolumeLabel = "T1OS $currentVersion"',
    'mkfs.ntfs -F -Q -L "$root_label"',
    'root_type=0700',
    'root_partition_name=$root_label',
    '--new=2:0:+3G --typecode=2:8300 --change-name=2:T1OS_RECOVERY',
    '--new=3:0:0 --typecode=3:"$root_type"',
    'mksquashfs "$root_mount" "$recovery_image"',
    '-b 1M -Xcompression-level 22 -tailends -no-exports',
    'recovery_manifest="$recovery_settings/files.tsv"',
    'rm -rf -- "$root_mount/.recover"',
    "'recovery_filesystem': 'squashfs-zstd'",
    "--exclude='/the one/settings/terminfo/*'",
    'graphics_recovery_marker="$graphics_recovery_settings/graphics recovery boot.json"',
    "graphics_recovery_temporary_regex='.*/graphics recovery boot[.]json[.][0-9]+[.]new'",
    'rm -f -- "$graphics_recovery_marker"',
    '[ -L "$graphics_recovery_marker" ]',
    'The hardware root retained one-shot graphics-recovery state.',
    'bucket_hex=$(printf',
    'terminfo_target/index.tsv',
    'T1OS Logo - Black Transparent.ico',
    'Icon="the one\\resources\\t1os-drive.ico"',
    '$root_mount/autorun.inf',
    "'root_filesystem': 'ntfs'",
    "'root_label': os.environ['T1OS_ROOT_LABEL']",
    "'windows_native_root': os.environ['T1OS_ENCRYPTED'] != '1'"
)) {
    if (-not $imageBuilderText.Contains($requiredText)) {
        throw "The hardware image builder is missing the NTFS/Windows contract: $requiredText"
    }
}
$bundleBuilderText = Get-Content -LiteralPath $bundleBuilder -Raw
foreach ($requiredText in @(
    "format = 't1os-usb-bundle'",
    "drive_version = `$version",
    "windows_autorun = 'autorun.inf'",
    "windows_drive_icon = 'the one\resources\t1os-drive.ico'",
    "entry = 'esp.img'",
    "entry = 'recovery.squashfs'",
    "entry = 'root.ntfs.img'",
    'minimum_target_bytes = $minimumTargetBytes',
    'ntfsresize --force --no-progress-bar --size "$root_bytes"',
    'ntfsfix --clear-dirty "$root_loop"',
    '[System.IO.Compression.ZipArchiveMode]::Create'
)) {
    if (-not $bundleBuilderText.Contains($requiredText)) {
        throw "The hardware USB bundle builder is missing the capacity-independent contract: $requiredText"
    }
}
$rootCopyOffset = $imageBuilderText.IndexOf('rsync -aHAX --numeric-ids --delete')
$recoveryScrubOffset = $imageBuilderText.IndexOf(
    'graphics_recovery_marker="$graphics_recovery_settings/graphics recovery boot.json"'
)
$terminfoCopyOffset = $imageBuilderText.IndexOf(
    'terminfo_source="$source_mount/the one/settings/terminfo"'
)
if (
    $rootCopyOffset -lt 0 -or
    $recoveryScrubOffset -le $rootCopyOffset -or
    $terminfoCopyOffset -le $recoveryScrubOffset
) {
    throw 'The hardware image builder does not scrub recovery state immediately after the root copy.'
}


Write-Host 'Hardware roothealth contracts validation passed.'
