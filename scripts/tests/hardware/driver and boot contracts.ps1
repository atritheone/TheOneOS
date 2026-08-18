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
$inputServerText = Get-Content -LiteralPath $inputServer -Raw
$driverPolicyText = Get-Content -LiteralPath $driverPolicy -Raw
foreach ($requiredText in @(
    '"pattern": "null"',
    '"pattern": "random"',
    '"pattern": "urandom"',
    '"pattern": "dri/renderD*"',
    '"mode": "0440"',
    '"mode": "0660"',
    '"group": 1000'
)) {
    if (-not $driverPolicyText.Contains($requiredText)) {
        throw "Driver policy is missing scoped Chromium device-node access: $requiredText"
    }
}
$policyObject = Get-Content -LiteralPath $driverPolicy -Raw | ConvertFrom-Json
$compatibilityObject = Get-Content -LiteralPath $desktopCompatibility -Raw | ConvertFrom-Json
foreach ($module in @('nvidia', 'nvidia_modeset', 'nvidia_drm', 'nvidia_uvm', 'nouveau')) {
    if ($policyObject.allowed_modules -notcontains $module) {
        throw "Driver policy is missing the NVIDIA preference/fallback module: $module"
    }
}
if ($compatibilityObject.dependency_only_modules -notcontains 'nvidia_uvm') {
    throw 'Desktop compatibility does not classify nvidia_uvm as dependency-only.'
}
if (-not $policyObject.external_volumes.enabled -or
    -not $policyObject.external_volumes.allow_all_data -or
    ($policyObject.external_volumes.filesystems -contains 'ext4') -or
    ($policyObject.external_volumes.filesystems -notcontains 'ntfs3') -or
    ($policyObject.external_volumes.filesystems -notcontains 'exfat') -or
    ($policyObject.external_volumes.filesystems -notcontains 'vfat')) {
    throw 'External volume policy does not admit all supported Windows-compatible data drives.'
}
$contractModules = @(
    $compatibilityObject.module_groups.PSObject.Properties.Value |
        ForEach-Object { $_ } |
        ForEach-Object { ([string]$_).Replace('-', '_') } |
        Sort-Object -Unique
)
$policyModules = @(
    $policyObject.allowed_modules |
        ForEach-Object { ([string]$_).Replace('-', '_') } |
        Sort-Object -Unique
)
if (($contractModules -join "`n") -ne ($policyModules -join "`n")) {
    throw 'Driver policy and desktop compatibility module groups are not identical.'
}
$firmwareObject = Get-Content -LiteralPath $firmwareManifest -Raw | ConvertFrom-Json
if ($firmwareObject.format -ne 2 -or $firmwareObject.coverage -notlike 'complete*') {
    throw 'Hardware firmware is not a complete pinned WHENCE installation.'
}
if ([string]$firmwareObject.nvidia_open_driver_version -ne '610.43.03') {
    throw 'Hardware firmware does not match the NVIDIA open kernel driver.'
}
foreach ($requiredText in @('def listeventnodes():', 'suffix.isascii()', 'suffix.isdigit()', 'events.sort(key=lambda item: item[0])', 'getattr(os, "O_NOFOLLOW", 0)', 'stat.S_ISCHR(os.fstat(fd).st_mode)', 'fd = openeventdevice(path)')) {
    if (-not $inputServerText.Contains($requiredText)) {
        throw "Input Server is missing secure dynamic event-node discovery: $requiredText"
    }
}

$themeText = Get-Content -LiteralPath $grubTheme -Raw
foreach ($requiredText in @('title-text: "The One OS"', 'title-font: "GNU Unifont Regular 16"', 'desktop-image: "t1os-black.png"', 'desktop-color: "#000000"', 'terminal-border: "0"', '+ boot_menu {', 'id = "__timeout__"', 'text = "booting in %d..."')) {
    if (-not $themeText.Contains($requiredText)) {
        throw "The hardware GRUB theme is missing: $requiredText"
    }
}
$backgroundBytes = [Convert]::FromBase64String((Get-Content -LiteralPath $grubBackground -Raw).Trim())
if ($backgroundBytes.Length -lt 8 -or
    -not [System.Linq.Enumerable]::SequenceEqual(
        [byte[]]$backgroundBytes[0..7],
        [byte[]](0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a)
    )) {
    throw 'The hardware GRUB background source is not a valid PNG payload.'
}

foreach ($template in @(
    [pscustomobject]@{ Path = $grubScript; Default = 't1os-boot'; RootToken = '@T1OS_ROOT_UUID@' },
    [pscustomobject]@{ Path = $encryptedGrubScript; Default = 't1os-encrypted-boot'; RootToken = '@T1OS_LUKS_UUID@' }
)) {
    $grubText = Get-Content -LiteralPath $template.Path -Raw
    $menuTitles = @(
        [regex]::Matches($grubText, '(?m)^menuentry\s+"([^"]+)"') |
            ForEach-Object { $_.Groups[1].Value }
    )
    if (($menuTitles -join '|') -ne 'boot|safe mode|recovery') {
        throw "The hardware GRUB menu must contain exactly boot, safe mode, and recovery: $($template.Path)"
    }
    foreach ($requiredText in @(
        'set timeout_style=menu',
        'set timeout=5',
        "set default=$($template.Default)",
        'set gfxmode=auto',
        'set gfxpayload=keep',
        'insmod png',
        'insmod ntfs',
        'set theme=$prefix/t1os-theme.txt',
        'rootfstype=ntfs3',
        't1os.recoverypart=SCAN',
        '@T1OS_RECOVERY_SHA256@',
        $template.RootToken
    )) {
        if (-not $grubText.Contains($requiredText)) {
            throw "The hardware GRUB template is missing: $requiredText"
        }
    }
    $bootMatch = [regex]::Match($grubText, '(?ms)^menuentry "boot".*?^}')
    if (-not $bootMatch.Success) {
        throw "The hardware GRUB template has no boot entry: $($template.Path)"
    }
    $bootText = $bootMatch.Value
    foreach ($requiredText in @(
        't1os.graphics=auto',
        't1os.quiet=1',
        'nvidia_drm.modeset=1',
        'nvidia_drm.fbdev=1',
        'nouveau.config=NvGspFw=0',
        'console=ttyS0,115200n8',
        'quiet',
        'loglevel=0',
        'logo.nologo'
    )) {
        if (-not $bootText.Contains($requiredText)) {
            throw "The normal boot entry is missing its consumer boot setting: $requiredText"
        }
    }
    foreach ($forbiddenText in @(
        'console=tty0',
        'loglevel=7',
        't1os.graphics=cpu',
        't1os.graphics=framebuffer',
        'drm.debug=',
        'nouveau.debug=',
        'log_buf_len='
    )) {
        if ($bootText.Contains($forbiddenText)) {
            throw "The normal boot entry exposes a diagnostic setting: $forbiddenText"
        }
    }
    $safeMatch = [regex]::Match($grubText, '(?ms)^menuentry "safe mode".*?^}')
    if (-not $safeMatch.Success -or
        -not $safeMatch.Value.Contains('t1os.graphics=framebuffer') -or
        -not $safeMatch.Value.Contains('module_blacklist=amdgpu,radeon,nouveau')) {
        throw "Safe mode does not preserve an independent firmware framebuffer: $($template.Path)"
    }
    if ($grubText -match '(?im)^\s*set\s+gfxmode\s*=\s*(?!auto\s*$)\S+') {
        throw "The hardware GRUB template contains a fixed firmware graphics mode: $($template.Path)"
    }
    if ($grubText -match '(?i)(?:^|\s)video=[^\s\\]+') {
        throw "The hardware GRUB template contains a fixed kernel video mode: $($template.Path)"
    }
    if ($grubText -match '(?m)^menuentry\s+"[^"]*T1OS') {
        throw "A hardware GRUB menu label still contains T1OS: $($template.Path)"
    }
}

$configText = Get-Content -LiteralPath $kernelConfig -Raw
if ($configText.Contains('CONFIG_NTFS3_64BIT_CLUSTER=y')) {
    throw 'Hardware kernel must not enable NTFS3 64-bit clusters because Windows does not support that large-volume mode.'
}
foreach ($option in @(
    'CONFIG_SECURITY_T1OS=y',
    'CONFIG_EFI=y',
    'CONFIG_EFI_STUB=y',
    'CONFIG_EFIVAR_FS=y',
    'CONFIG_BLK_DEV_NVME=y',
    'CONFIG_USB_XHCI_HCD=y',
    'CONFIG_USB_STORAGE=y',
    'CONFIG_USB_UAS=y',
    'CONFIG_HID=y',
    'CONFIG_HID_GENERIC=y',
    'CONFIG_USB_HID=y',
    'CONFIG_EXT4_FS=y',
    'CONFIG_EXFAT_FS=y',
    'CONFIG_FAT_FS=y',
    'CONFIG_VFAT_FS=y',
    'CONFIG_NLS_CODEPAGE_437=y',
    'CONFIG_NLS_ASCII=y',
    'CONFIG_NLS_UTF8=y',
    'CONFIG_NTFS3_FS=y',
    'CONFIG_NTFS3_FS_POSIX_ACL=y',
    'CONFIG_DRM_SIMPLEDRM=y',
    'CONFIG_R8169=y',
    'CONFIG_SND=y',
    'CONFIG_SND_PCM=y',
    'CONFIG_SND_PROC_FS=y',
    'CONFIG_SND_HDA_INTEL=y',
    'CONFIG_SND_HDA_CODEC_REALTEK=y',
    'CONFIG_BLK_DEV_DM=y',
    'CONFIG_DM_CRYPT=y',
    'CONFIG_MODPROBE_PATH="/the one/drivers/tools/modprobe"',
    # The generated hardware kernel is also the validated upgrade source for
    # the VirtualBox VM. Keep every VM boot and integration dependency built in
    # because the VM initramfs intentionally has no hardware module archive.
    'CONFIG_SATA_AHCI=y',
    'CONFIG_ATA_PIIX=y',
    'CONFIG_BLK_DEV_SD=y',
    'CONFIG_VIRTIO=y',
    'CONFIG_VIRTIO_PCI=y',
    'CONFIG_VIRTIO_NET=y',
    'CONFIG_DRM_VBOXVIDEO=y',
    'CONFIG_VBOXGUEST=y',
    'CONFIG_VBOXSF_FS=y',
    'CONFIG_SND_INTEL8X0=y',
    'CONFIG_SERIAL_8250_CONSOLE=y',
    'CONFIG_UNIX98_PTYS=y'
)) {
    if (-not $configText.Contains($option)) {
        throw "Hardware kernel configuration gate failed: $option"
    }
}


Write-Host 'Hardware driver and boot contracts validation passed.'
