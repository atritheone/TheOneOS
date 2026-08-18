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
$graphicsObject = Get-Content -LiteralPath $graphicsCatalogue -Raw | ConvertFrom-Json
$graphicsDrivers = @($graphicsObject.drivers | ForEach-Object { [string]$_ })
$graphicsPaths = @($graphicsObject.files | ForEach-Object { [string]$_.path })

if (
    [int]$graphicsObject.format -ne 1 -or
    [string]$graphicsObject.state -ne 'ready' -or
    [string]$graphicsObject.profile -ne 'hardware' -or
    [string]$graphicsObject.sources.nvidia_vaapi_driver.commit -ne
        '03bb5a0c082493f95f2cd54ffd31dbfa8c7cbe7d' -or
    [string]$graphicsObject.sources.nv_codec_headers.commit -ne
        '0a6fba9a2820628b8103464f4c8753ee05838baa' -or
    [string]$graphicsObject.sources.gstreamer_codecparsers.version -ne
        '1.26.11'
) {
    throw 'The graphics catalogue is not a ready hardware-profile release.'
}

foreach ($driver in @('i915', 'xe', 'radeon', 'r600', 'r600-vaapi', 'amdgpu', 'radeonsi', 'nvidia-open', 'nvidia-nvdec-vaapi', 'nouveau', 'nouveau-vaapi', 'nvk', 'virtio_gpu', 'vmwgfx')) {
    if ($driver -notin $graphicsDrivers) {
        throw "The hardware graphics catalogue is missing driver support: $driver"
    }
}

foreach ($relative in @(
    'drivers/iHD_drv_video.so',
    'drivers/r600_drv_video.so',
    'drivers/radeonsi_drv_video.so',
    'drivers/nvidia_drv_video.so',
    'drivers/nouveau_drv_video.so',
    'drivers/virtio_gpu_drv_video.so',
    'drivers/vmwgfx_drv_video.so',
    'libdrm_nouveau.so.2',
    'libvulkan_nouveau.so',
    'nvidia/libEGL.so.1',
    'nvidia/libGLESv2.so.2',
    'nvidia/libEGL_nvidia.so.0',
    'nvidia/libnvidia-egl-gbm.so.1',
    'nvidia/libcuda.so.1',
    'nvidia/libnvcuvid.so.1',
    'nvidia/libnvidia-ptxjitcompiler.so.1',
    'libgstreamer-1.0.so.0',
    'libgstbase-1.0.so.0',
    'libgstcodecparsers-1.0.so.0',
    'nvidia/egl_vendor.d/10_nvidia.json',
    'nvidia/gbm/15_nvidia_gbm.json',
    'nvidia/gbm/nvidia-drm_gbm.so',
    'nvidia/t1os-nvidia-path-provider.so',
    'nvidia/runtime.json'
)) {
    if ($relative -notin $graphicsPaths) {
        throw "The hardware graphics manifest is missing: $relative"
    }
}

$nvidiaPathProviderText = Get-Content -LiteralPath $nvidiaPathProviderSource -Raw
foreach ($requiredText in @(
    '#define T1OS_DEVICE_ROOT "/the one/drivers/nodes"',
    '#define T1OS_PROCESS_ROOT "/the one/drivers/processes"',
    '#define T1OS_STATE_ROOT "/the one/drivers/state"',
    '#define T1OS_CUDA_THREAD_NAME "t1os-cuda-thread-name"',
    '!strcmp(name, "nvidiactl")',
    '!strcmp(name, "nvidia-modeset")',
    '!strcmp(name, "nvidia-uvm")',
    'decimal_suffix(name + 6)',
    '!strcmp(path, "/dev/dri")',
    'drm_node_name(path + 9)',
    'static bool bounded_tree_suffix(',
    'static bool cuda_thread_name_path(',
    'static const char prefix[] = "/proc/self/task/"',
    'return !strcmp(thread, "/comm")',
    'static bool cuda_thread_name_open(',
    '(flags & O_ACCMODE) == O_WRONLY',
    '(flags & (O_CREAT | O_TRUNC)) == (O_CREAT | O_TRUNC)',
    'static int cuda_thread_name_descriptor(',
    'return memfd_create(T1OS_CUDA_THREAD_NAME, options)',
    'static FILE *cuda_thread_name_stream(',
    'descriptor = memfd_create(T1OS_CUDA_THREAD_NAME, MFD_CLOEXEC)',
    'mode && mode[0] == ''w''',
    '!strcmp(path, "/proc")',
    '!strncmp(path, "/proc/", 6)',
    'bounded_tree_suffix(path + 5)',
    '!strcmp(path, "/sys")',
    '!strncmp(path, "/sys/", 5)',
    'bounded_tree_suffix(path + 4)',
    'errno = EINVAL',
    'errno = EFAULT',
    'errno = ENAMETOOLONG',
    'int __xstat64(',
    'DIR *opendir(',
    'char *realpath('
)) {
    if (-not $nvidiaPathProviderText.Contains($requiredText)) {
        throw "The NVIDIA userspace path provider is incomplete: $requiredText"
    }
}
foreach ($forbiddenText in @(
    '"/dev", "/the one/drivers/nodes"',
    'strncmp(path, "/dev/nvidia", 11)',
    'strncmp(path, "/proc", 5)',
    'strncmp(path, "/sys", 4)',
    '#define T1OS_NULL_DEVICE',
    'T1OS_DEVICE_ROOT "/null"',
    '!strcmp(name, "nvidia-uvm-tools")',
    '!strcmp(name, "nvidia-caps")'
)) {
    if ($nvidiaPathProviderText.Contains($forbiddenText)) {
        throw "The NVIDIA userspace path provider is over-broad: $forbiddenText"
    }
}

$wslAngelVoiceTest = ConvertTo-T1OSWslPath -Path $angelVoiceTest
& wsl.exe -d Ubuntu --exec python3 -B $wslAngelVoiceTest $wslProjectRoot
if ($LASTEXITCODE -ne 0) {
    throw "Angel's boot and recovery voice validation failed."
}
& $angelRecoveryTest
if ($LASTEXITCODE -ne 0) {
    throw "Angel's recovery engine validation failed."
}

Write-Host 'Hardware graphics and angel validation passed.'
