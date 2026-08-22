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
$ntfsNoAccessRulesPatch = Join-Path $projectRoot 'source\entry\kernel\t1os ntfs3 noacsrules.patch'
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
$kernelPolicyText = Get-Content -LiteralPath $kernelPolicy -Raw
$ntfsNoAccessRulesPatchText = Get-Content -LiteralPath $ntfsNoAccessRulesPatch -Raw
$rootPushText = Get-Content -LiteralPath $rootPushScript -Raw
$hardwareKernelPushText = Get-Content -LiteralPath $hardwareKernelPushScript -Raw
$globalDevicesCheck = $kernelPolicyText.IndexOf('if (!strcmp(relative, "devices"))')
$flatProcessCheck = $kernelPolicyText.IndexOf("slash = strchr(relative, '/');")
if ($globalDevicesCheck -lt 0 -or $flatProcessCheck -lt 0 -or
        $globalDevicesCheck -gt $flatProcessCheck) {
    throw 'T1OS LSM checks DriverServer global proc inventories after the flat PID parser.'
}
if ($hardwareKernelPushText -match '(?m)^\$updateName\s*=\s*''\d{8}-') {
    throw 'The USB update script still requires a manually unique transaction identifier.'
}
foreach ($transactionNeedle in @(
    '[DateTime]::UtcNow',
    '[Guid]::NewGuid()',
    ".Substring(0, 12)"
)) {
    if (-not $hardwareKernelPushText.Contains($transactionNeedle)) {
        throw "The USB update script does not generate its transaction identifier: $transactionNeedle"
    }
}
foreach ($externalMountPolicy in @(
    'static bool t1os_external_volume_options(const char *type, const void *data)',
    '"uid=1000,gid=1000,dmask=0077,fmask=0177,noacsrules"',
    '"uid=1000,gid=1000,dmask=0077,fmask=0177"',
    't1os_external_volume_options(type, data)'
)) {
    if (-not $kernelPolicyText.Contains($externalMountPolicy)) {
        throw "T1OS LSM is missing the private uid-1000 removable-volume mount contract: $externalMountPolicy"
    }
}
foreach ($ntfsSyntheticAccessRule in @(
    'if (!sbi->options->noacsrules)',
    '(!S_ISDIR(mode) || !sbi->options->noacsrules)',
    'Windows uses READONLY on directories for folder customisation'
)) {
    if (-not $ntfsNoAccessRulesPatchText.Contains($ntfsSyntheticAccessRule)) {
        throw "The NTFS3 synthetic access patch does not preserve writable read-only-attributed directories: $ntfsSyntheticAccessRule"
    }
}
foreach ($requiredText in @(
    '#define T1OS_WINDOWSERVER_SCRIPT     "/the one/build/windows/windowserver.py"',
    '#define T1OS_BRICK_SCRIPT            "/the one/build/brick/brick.py"',
    '#define T1OS_DRIVERSERVER_SCRIPT     "/the one/build/drivers/driverserver.py"',
    'static bool t1os_is_drm_render_node_path(const struct path *p)',
    'static bool t1os_is_chromium_device_node_path(const struct path *p)',
    'static bool t1os_is_nvidia_device_node_name(const char *path)',
    'static bool t1os_is_console_device_node_name(const char *path)',
    'static bool t1os_is_console_multiplexer_name(const char *path)',
    'static bool t1os_is_brick_process(void)',
    'static bool t1os_is_nvidia_device_node_path(const struct path *p)',
    'static bool t1os_kernel_devtmpfs_worker(void)',
    'static bool t1os_kernel_devtmpfs_dentry(const struct dentry *dentry)',
    'static bool t1os_kernel_devtmpfs_parent(const struct path *dir)',
    'strcmp(dentry->d_sb->s_type->name, "devtmpfs")',
    'if (t1os_kernel_devtmpfs_parent(dir))',
    'if ((S_ISCHR(mode) || S_ISBLK(mode)) &&',
    '!strcmp(relative, "modules")',
    '!strcmp(relative, "devices")',
    '!strcmp(path, "/the one/drivers/processes/driver/nvidia")',
    '!strncmp(path, "/the one/drivers/processes/driver/nvidia/",',
    'static bool t1os_process_component_is_current(const char *value, size_t length)',
    'pid_t current_pid = task_pid_nr(current);',
    'return parsed == (unsigned long)current_pid;',
    't1os_process_component_is_current(relative, component_length)',
    'static const char prefix[] = "/the one/drivers/nodes/"',
    '!strcmp(name, "nvidiactl")',
    '!strcmp(name, "nvidia-modeset")',
    '!strcmp(name, "nvidia-uvm")',
    'if (strncmp(name, "nvidia", 6))',
    "return *digit == '\0';",
    'if (t1os_is_nvidia_device_node_name(path))',
    'if (t1os_is_console_device_node_name(path))',
    'return current->signal && READ_ONCE(current->signal->tty);',
    'S_ISCHR(mode) &&',
    't1os_is_nvidia_device_node_path(&p)',
    'static void t1os_log_denial(const char *operation, const char *path)',
    '"T1OS LSM: denied %s path=%s domain=%s pid=%d comm=%s uid=%u euid=%u gid=%u\n"',
    't1os_is_driverserver_process() &&',
    't1os_is_drm_render_node_path(path)',
    't1os_is_chromium_device_node_path(path)',
    't1os_is_nvidia_device_node_path(path)',
    'static bool t1os_is_graphics_recovery_marker(const char *path);',
    'static bool t1os_is_graphics_recovery_marker(const char *path)',
    'static bool t1os_is_efi_bootnext(const char *path);',
    'static bool t1os_is_efi_bootnext_name(const char *name)',
    'static bool t1os_is_efi_bootnext(const char *path)',
    '"BootNext-8be4df61-93ca-11d2-aa0d-00e098032b8c"',
    'static const char negative_suffix[] = " (deleted)";',
    '"/the one/drivers/control/firmware/efi/efivars/"',
    '"/sys/firmware/efi/efivars/"',
    '"/firmware/efi/efivars/"',
    '!t1os_is_efi_bootnext(name)',
    '"/the one/settings/graphics recovery boot.json"',
    '"/the one/drivers/nodes/tty0"',
    'return path && !strcmp(path, marker);',
    'return t1os_is_goddess_process();',
    'if (!strcmp(path, "/the one/master") ||',
    '!strcmp(path, T1OS_MODPROBE_BINARY) && !current->mm',
    'static bool t1os_is_reign_time_output_path(const char *path)',
    'return t1os_domain_is(T1OS_DOMAIN_REIGN);',
    'static bool t1os_time_output_bootstrap_create_allowed(const struct path *dir,',
    'static const char parent[] = "/the one/settings/time";',
    'static const char common[] = "common.txt";',
    'static const char atreyan[] = "atreyan.txt";',
    'if (t1os_time_output_bootstrap_create_allowed(dir, dentry, mode))',
    'static int t1os_path_symlink(const struct path *dir,',
    '(void)old_name;',
    'static bool t1os_struct_path_is_ephemeral(const struct path *path)',
    'return t1os_struct_path_is_ephemeral(&destination) ? 0 : -EACCES;',
    't1os_struct_path_is_ephemeral(&source) &&',
    't1os_struct_path_is_ephemeral(&destination)',
    '"#!\"/the one/software/python/bin/python\" -B";',
    'static int t1os_path_unlink(const struct path *dir, struct dentry *dentry)',
    'static int t1os_path_rename(const struct path *old_dir,',
    'static int t1os_check_dentry_metadata(struct dentry *dentry)',
    'The verified initramfs establishes NTFS3''s persistent $LX ownership and',
    'if (!t1os_runtime_root_active())',
    '!strcmp(dentry->d_sb->s_type->name, "tmpfs")',
    'Do not use TMPFS_MAGIC because devtmpfs is shmem-backed too',
    'return -EACCES;',
    '#define T1OS_CHROMIUM_BINARY         "/the one/software/chromium/program/chrome"',
    '#define T1OS_CHROMIUM_SANDBOX        "/the one/software/chromium/program/chrome-sandbox"',
    '#define T1OS_MEDIA_DECODER_DAEMON    "/the one/software/audio/t1-media-decoderd"',
    'T1OS_CRED_VIDEO_WORKER',
    'static bool t1os_video_worker_creds(const struct cred *cred)',
    'kuid_t uid = make_kuid(&init_user_ns, 65534);',
    'kgid_t gid = make_kgid(&init_user_ns, 1000);',
    '!strcmp(path, T1OS_VIDEO_DECODER_BINARY) &&',
    'execsecurity->cred_class = T1OS_CRED_VIDEO_WORKER;',
    'static bool t1os_immutable_exec_path(const char *path)',
    'static bool t1os_general_exec_allowed(enum t1os_domain domain,',
    'static bool t1os_interpreted_script(const struct linux_binprm *bprm)',
    't1os_general_exec_allowed(execsecurity->domain,',
    'static bool t1os_packaged_application_path(const char *path)',
    't1os_unprivileged_domain(target) &&',
    't1os_packaged_application_path(path)',
    '"/the one/software",',
    '"/the one/catalogue",',
    'Script and interpreter exceptions apply only to execution.',
    'static bool t1os_is_media_decoder_daemon_process(void)',
    'static bool t1os_is_expanse_runtime_path(const char *path)',
    'static bool t1os_is_python_management_path(const char *path)',
    '"/the one/software/python/pip"',
    'static bool t1os_is_python_site_packages_path(const char *path)',
    '"/the one/software/python/lib/python3.14/site-packages"',
    'static bool t1os_is_python_package_command_path(const char *path)',
    'strcmp(relative, "python3.14")',
    'static bool t1os_is_python_package_catalogue_path(const char *path)',
    '"/the one/catalogue/python"',
    'static bool t1os_is_python_package_path(const char *path)',
    'if (t1os_is_python_package_path(path))',
    'return t1os_domain_is(T1OS_DOMAIN_EXPANSE);',
    'return t1os_domain_is(T1OS_DOMAIN_PYTHON_SERVICE);',
    '!strcmp(path, "/.ephemeral/media")',
    '!strncmp(path, "/.ephemeral/media/", 18)',
    't1os_is_video_client_process() ||',
    't1os_is_audioserver_process() ||',
    'static bool t1os_executable_path_matches(const char *path, const char *target)',
    'static const char unreachable[] = "(unreachable)"',
    'matched = t1os_executable_path_matches(name, target)',
    't1os_is_executable_process(T1OS_CHROMIUM_SANDBOX)',
    'return t1os_is_executable_process(T1OS_MEDIA_DECODER_DAEMON);'
)) {
    if (-not $kernelPolicyText.Contains($requiredText)) {
        throw "T1OS kernel policy is missing scoped Driver Server device-node metadata access: $requiredText"
    }
}

$devtmpfsHelperStart = $kernelPolicyText.IndexOf(
    'static bool t1os_kernel_devtmpfs_worker(void)',
    [System.StringComparison]::Ordinal
)
$devtmpfsHelperEnd = $kernelPolicyText.IndexOf(
    'static bool t1os_is_drm_render_node_path(const struct path *p)',
    [Math]::Max(0, $devtmpfsHelperStart),
    [System.StringComparison]::Ordinal
)
$devtmpfsHelperBody = if (
    $devtmpfsHelperStart -ge 0 -and $devtmpfsHelperEnd -gt $devtmpfsHelperStart
) {
    $kernelPolicyText.Substring(
        $devtmpfsHelperStart,
        $devtmpfsHelperEnd - $devtmpfsHelperStart
    )
}
else {
    ''
}
if (
    -not $devtmpfsHelperBody.Contains('return !current->mm &&') -or
    -not $devtmpfsHelperBody.Contains('(current->flags & PF_KTHREAD)') -or
    -not $devtmpfsHelperBody.Contains('!strcmp(current->comm, "kdevtmpfs")') -or
    -not $devtmpfsHelperBody.Contains(
        'strcmp(dentry->d_sb->s_type->name, "devtmpfs")'
    ) -or
    -not $devtmpfsHelperBody.Contains(
        'dentry->d_sb->s_flags & SB_KERNMOUNT'
    ) -or
    $devtmpfsHelperBody.Contains('d_path(dir,') -or
    $devtmpfsHelperBody.Contains(
        'static const char root[] = "/the one/drivers/nodes";'
    )
) {
    throw 'The late-loaded device-node exemption is not confined to the kernel-owned kdevtmpfs mount.'
}
$devtmpfsCapabilityStart = $kernelPolicyText.IndexOf(
    'static int t1os_capable(const struct cred *cred, struct user_namespace *ns,',
    [System.StringComparison]::Ordinal
)
$devtmpfsCapabilityEnd = $kernelPolicyText.IndexOf(
    'static int t1os_settime(const struct timespec64 *ts,',
    [Math]::Max(0, $devtmpfsCapabilityStart),
    [System.StringComparison]::Ordinal
)
$devtmpfsCapabilityBody = if (
    $devtmpfsCapabilityStart -ge 0 -and
    $devtmpfsCapabilityEnd -gt $devtmpfsCapabilityStart
) {
    $kernelPolicyText.Substring(
        $devtmpfsCapabilityStart,
        $devtmpfsCapabilityEnd - $devtmpfsCapabilityStart
    )
}
else {
    ''
}
if (-not [regex]::IsMatch(
    $devtmpfsCapabilityBody,
    '(?ms)case CAP_MKNOD:\s*if \(t1os_kernel_devtmpfs_worker\(\)\)\s*return 0;\s*return domain == T1OS_DOMAIN_GODDESS \|\|\s*domain == T1OS_DOMAIN_DRIVER \? 0 : -EACCES;'
)) {
    throw 'The CAP_MKNOD policy does not authorize only kdevtmpfs plus the established userspace domains.'
}
$devtmpfsSetattrStart = $kernelPolicyText.IndexOf(
    'static int t1os_inode_setattr(struct mnt_idmap *idmap,',
    [System.StringComparison]::Ordinal
)
$devtmpfsSetattrEnd = $kernelPolicyText.IndexOf(
    'static int t1os_inode_setxattr(struct mnt_idmap *idmap,',
    [Math]::Max(0, $devtmpfsSetattrStart),
    [System.StringComparison]::Ordinal
)
$devtmpfsSetattrBody = if (
    $devtmpfsSetattrStart -ge 0 -and $devtmpfsSetattrEnd -gt $devtmpfsSetattrStart
) {
    $kernelPolicyText.Substring(
        $devtmpfsSetattrStart,
        $devtmpfsSetattrEnd - $devtmpfsSetattrStart
    )
}
else {
    ''
}
if (-not $devtmpfsSetattrBody.Contains(
    'if (t1os_kernel_devtmpfs_dentry(dentry))'
)) {
    throw 'The kdevtmpfs metadata exception is missing from inode_setattr.'
}
$devtmpfsMkdirStart = $kernelPolicyText.IndexOf(
    'static int t1os_path_mkdir(const struct path *dir,',
    [System.StringComparison]::Ordinal
)
$devtmpfsMkdirEnd = $kernelPolicyText.IndexOf(
    '/* Make node: mknod */',
    [Math]::Max(0, $devtmpfsMkdirStart),
    [System.StringComparison]::Ordinal
)
$devtmpfsMkdirBody = if (
    $devtmpfsMkdirStart -ge 0 -and $devtmpfsMkdirEnd -gt $devtmpfsMkdirStart
) {
    $kernelPolicyText.Substring(
        $devtmpfsMkdirStart,
        $devtmpfsMkdirEnd - $devtmpfsMkdirStart
    )
}
else {
    ''
}
$devtmpfsUnlinkStart = $kernelPolicyText.IndexOf(
    'static int t1os_path_unlink(const struct path *dir, struct dentry *dentry)',
    [System.StringComparison]::Ordinal
)
$devtmpfsUnlinkEnd = $kernelPolicyText.IndexOf(
    '/* Delete: rmdir */',
    [Math]::Max(0, $devtmpfsUnlinkStart),
    [System.StringComparison]::Ordinal
)
$devtmpfsUnlinkBody = if (
    $devtmpfsUnlinkStart -ge 0 -and $devtmpfsUnlinkEnd -gt $devtmpfsUnlinkStart
) {
    $kernelPolicyText.Substring(
        $devtmpfsUnlinkStart,
        $devtmpfsUnlinkEnd - $devtmpfsUnlinkStart
    )
}
else {
    ''
}
$devtmpfsMknodStart = $kernelPolicyText.IndexOf(
    'static int t1os_path_mknod(const struct path *dir,',
    [System.StringComparison]::Ordinal
)
$devtmpfsMknodEnd = $kernelPolicyText.IndexOf(
    'static int t1os_path_truncate(const struct path *path)',
    [Math]::Max(0, $devtmpfsMknodStart),
    [System.StringComparison]::Ordinal
)
$devtmpfsMknodBody = if (
    $devtmpfsMknodStart -ge 0 -and $devtmpfsMknodEnd -gt $devtmpfsMknodStart
) {
    $kernelPolicyText.Substring(
        $devtmpfsMknodStart,
        $devtmpfsMknodEnd - $devtmpfsMknodStart
    )
}
else {
    ''
}
if (
    -not $devtmpfsMkdirBody.Contains(
        'if (t1os_kernel_devtmpfs_parent(dir))'
    ) -or
    $devtmpfsUnlinkBody.Contains(
        't1os_kernel_devtmpfs_parent(dir)'
    ) -or
    -not $devtmpfsMknodBody.Contains(
        'if ((S_ISCHR(mode) || S_ISBLK(mode)) &&'
    ) -or
    -not $devtmpfsMknodBody.Contains(
        't1os_kernel_devtmpfs_parent(dir)'
    )
) {
    throw 'The kdevtmpfs exception must authorize directory and device-node creation only.'
}
$processReadStart = $kernelPolicyText.IndexOf(
    'static bool t1os_process_read_allowed(const char *path)',
    [System.StringComparison]::Ordinal
)
$processReadEnd = $kernelPolicyText.IndexOf(
    'static bool t1os_special_read_allowed(const char *path)',
    [Math]::Max(0, $processReadStart),
    [System.StringComparison]::Ordinal
)
$processReadBody = if (
    $processReadStart -ge 0 -and $processReadEnd -gt $processReadStart
) {
    $kernelPolicyText.Substring(
        $processReadStart,
        $processReadEnd - $processReadStart
    )
}
else {
    ''
}
if (
    -not [regex]::IsMatch(
        $processReadBody,
        '(?ms)!strcmp\(relative, "modules"\)\)\s*return t1os_is_goddess_process\(\) \|\|\s*t1os_is_driverserver_process\(\);'
    ) -or
    -not [regex]::IsMatch(
        $processReadBody,
        '(?ms)!strcmp\(relative, "devices"\)\)\s*return t1os_is_driverserver_process\(\);'
    ) -or
    -not [regex]::IsMatch(
        $processReadBody,
        '(?ms)!strcmp\(path, "/the one/drivers/processes/driver/nvidia"\) \|\|\s*!strncmp\(path, "/the one/drivers/processes/driver/nvidia/".*?\)\s*return true;'
    ) -or
    -not $processReadBody.Contains('own_process &&') -or
    -not $processReadBody.Contains('!strcmp(leaf, "/maps")') -or
    -not $processReadBody.Contains('if (!t1os_process_reader_domain())')
    ) {
    throw 'The process discovery ACL does not expose public GPU/system data and self inspection while retaining cross-process isolation.'
}

$committedCredsStart = $kernelPolicyText.IndexOf(
    'static void t1os_bprm_committed_creds(',
    [System.StringComparison]::Ordinal
)
$committedCredsEnd = $kernelPolicyText.IndexOf(
    '/* Guard the actual module and firmware read paths',
    [Math]::Max(0, $committedCredsStart),
    [System.StringComparison]::Ordinal
)
$committedCredsBody = if (
    $committedCredsStart -ge 0 -and $committedCredsEnd -gt $committedCredsStart
) {
    $kernelPolicyText.Substring(
        $committedCredsStart,
        $committedCredsEnd - $committedCredsStart
    )
}
else {
    ''
}
if (
    -not $committedCredsBody.Contains(
        'domain == T1OS_DOMAIN_CHROMIUM'
    ) -or
    -not $committedCredsBody.Contains(
        't1os_chromium_child_creds(cred)'
    ) -or
    -not $committedCredsBody.Contains(
        'set_dumpable(current->mm, SUID_DUMP_USER);'
    ) -or
    -not $committedCredsBody.Contains(
        'set_dumpable(current->mm, SUID_DUMP_DISABLE);'
    )
) {
    throw 'Chromium same-domain runtime attestation is not narrowly reconciled with Linux procfs dumpability checks.'
}
$ptraceStart = $kernelPolicyText.IndexOf(
    'static int t1os_ptrace_access_check(',
    [System.StringComparison]::Ordinal
)
$ptraceEnd = $kernelPolicyText.IndexOf(
    'static int t1os_ptrace_traceme(',
    [Math]::Max(0, $ptraceStart),
    [System.StringComparison]::Ordinal
)
$ptraceBody = if ($ptraceStart -ge 0 -and $ptraceEnd -gt $ptraceStart) {
    $kernelPolicyText.Substring($ptraceStart, $ptraceEnd - $ptraceStart)
}
else {
    ''
}
if (
    -not $ptraceBody.Contains(
        'access != PTRACE_MODE_READ_FSCREDS'
    ) -or
    -not $ptraceBody.Contains(
        'access != PTRACE_MODE_READ_REALCREDS'
    ) -or
    -not [regex]::IsMatch(
        $ptraceBody,
        'case T1OS_DOMAIN_CHROMIUM:\s*return target == T1OS_DOMAIN_CHROMIUM \? 0 : -EACCES;'
    )
) {
    throw 'Chromium process inspection is not restricted to read-only same-domain access.'
}

foreach ($forbiddenText in @(
    't1os_bootstrap_python_symlink_allowed',
    'static const char name[] = "t1python";',
    'if (t1os_bootstrap_python_symlink_allowed(dir, dentry, old_name))'
)) {
    if ($kernelPolicyText.Contains($forbiddenText)) {
        throw "T1OS kernel policy still contains the obsolete Python symlink exception: $forbiddenText"
    }
}
if (
    $kernelPolicyText.Contains('t1os_current_has_argument') -or
    $kernelPolicyText.Contains('--type=gpu-process') -or
    $kernelPolicyText.Contains('--type=zygote')
) {
    throw 'T1OS kernel policy still derives Chromium device authority from userspace argv.'
}
$nvidiaAclStart = $kernelPolicyText.IndexOf(
    'if (t1os_is_nvidia_device_node_name(path)) {',
    [System.StringComparison]::Ordinal
)
$nvidiaAclEnd = if ($nvidiaAclStart -ge 0) {
    $kernelPolicyText.IndexOf(
        '/* Render nodes expose command submission',
        $nvidiaAclStart,
        [System.StringComparison]::Ordinal
    )
}
else {
    -1
}
$nvidiaAclBody = if ($nvidiaAclStart -ge 0 -and $nvidiaAclEnd -gt $nvidiaAclStart) {
    $kernelPolicyText.Substring(
        $nvidiaAclStart,
        $nvidiaAclEnd - $nvidiaAclStart
    )
}
else {
    ''
}
if (
    -not $nvidiaAclBody.Contains('t1os_is_windowserver_process()') -or
    -not $nvidiaAclBody.Contains('/the one/drivers/nodes/nvidia-modeset') -or
    -not $nvidiaAclBody.Contains('return true;') -or
    $nvidiaAclBody.Contains('t1os_is_video_client_process()') -or
    $nvidiaAclBody.Contains('T1OS_CHROMIUM_BINARY') -or
    $nvidiaAclBody.Contains('t1os_is_driverserver_process()') -or
    $nvidiaAclBody.Contains('T1OS_CHROMIUM_SANDBOX')
) {
    throw 'The NVIDIA application-node ACL is not general by device class with modeset reserved for WindowServer.'
}
if (-not [regex]::IsMatch(
    $kernelPolicyText,
    '(?ms)if \(!strncmp\(path, "/the one/drivers/nodes/dri/renderD", 34\)\)\s*return true;'
)) {
    throw 'DRM render nodes are not exposed as a general DAC-controlled application facility.'
}
if (-not [regex]::IsMatch(
    $kernelPolicyText,
    '(?ms)if \(t1os_is_graphics_recovery_marker\(path\)\)\s*return t1os_is_goddess_process\(\);'
)) {
    throw 'The obsolete recovery marker cleanup is not exclusive to GODDESS.'
}
if (-not [regex]::IsMatch(
    $kernelPolicyText,
    '(?ms)if \(t1os_is_efi_bootnext\(path\)\)\s*return t1os_is_goddess_process\(\);'
)) {
    throw 'The EFI recovery boot pin is not exclusive to GODDESS.'
}
if (-not [regex]::IsMatch(
    $kernelPolicyText,
    '(?ms)if \(!strcmp\(path, "/the one/drivers/nodes/tty0"\)\) \{\s*if \(t1os_is_goddess_process\(\)\)\s*return true;\s*return false;\s*\}'
)) {
    throw 'The visible graphics-recovery console is not exclusive to GODDESS.'
}
if (-not [regex]::IsMatch(
    $kernelPolicyText,
    '(?ms)if \(!strcmp\(path, "/the one/drivers/nodes/null"\)\)\s*return true;'
)) {
    throw 'The null device is not a general DAC-controlled operating-system facility.'
}
if (-not [regex]::IsMatch(
    $kernelPolicyText,
    '(?ms)if \(!strcmp\(path, "/the one/drivers/nodes/zero"\) \|\|.*?!strcmp\(path, "/the one/drivers/nodes/tty"\)\)\s*return true;'
)) {
    throw 'Standard character devices are not exposed through one general DAC-controlled rule.'
}
foreach ($forbiddenText in @(
    '!strncmp(path, "/the one/drivers/nodes/nvidia"',
    '!strncmp(name, "nvidia", 6) ||',
    't1os_is_driverserver_process() || t1os_is_windowserver_process()',
    '!strcmp(name, "nvidia-uvm-tools")',
    '!strcmp(name, "nvidia-caps")'
)) {
    if ($kernelPolicyText.Contains($forbiddenText)) {
        throw "T1OS kernel policy grants over-broad NVIDIA device authority: $forbiddenText"
    }
}
if ($kernelPolicyText.Contains('T1OS_CHROMIUM_RUNTIME_BINARY') -or
    $kernelPolicyText.Contains('/.ephemeral/chromium-program/chrome')) {
    throw 'T1OS kernel policy still authorizes the removed temporary Chromium program alias.'
}
$writeHookStart = $kernelPolicyText.IndexOf(
    'static int t1os_file_open(struct file *file)',
    [System.StringComparison]::Ordinal
)
$writeHookEnd = $kernelPolicyText.IndexOf(
    'static int t1os_bprm_check(struct linux_binprm *bprm)',
    [System.StringComparison]::Ordinal
)
$writeHookBody = if ($writeHookStart -ge 0 -and $writeHookEnd -gt $writeHookStart) {
    $kernelPolicyText.Substring($writeHookStart, $writeHookEnd - $writeHookStart)
}
else {
    ''
}
if (
    -not $writeHookBody.Contains('Script and interpreter exceptions apply only to execution.') -or
    [regex]::IsMatch(
        $writeHookBody,
        '(?ms)!t1os_check_path\(name\)\s*&&\s*!is_script\(name\)'
    )
) {
    throw 'T1OS LSM still lets protected scripts bypass its write policy.'
}
$specialPathStart = $kernelPolicyText.IndexOf(
    'static bool t1os_is_special_path(const char *path)',
    [System.StringComparison]::Ordinal
)
$specialPathEnd = $kernelPolicyText.IndexOf(
    'static bool t1os_is_nvidia_device_node_name(const char *path)',
    [Math]::Max(0, $specialPathStart),
    [System.StringComparison]::Ordinal
)
$specialPathBody = if (
    $specialPathStart -ge 0 -and $specialPathEnd -gt $specialPathStart
) {
    $kernelPolicyText.Substring(
        $specialPathStart,
        $specialPathEnd - $specialPathStart
    )
}
else {
    ''
}
if (
    -not [regex]::IsMatch(
        $specialPathBody,
        '(?ms)!strcmp\(path, "/the one/settings"\).*?return true;.*?!strcmp\(path, "/the one/settings/session/identity.json"\).*?return true;.*?!strncmp\(path, "/the one/settings/".*?\)\s*return false;'
    ) -or
    $specialPathBody.Contains('/the one/settings/operations') -or
    $specialPathBody.Contains('/the one/settings/windowserver') -or
    $specialPathBody.Contains('/the one/settings/audio') -or
    $specialPathBody.Contains('/the one/settings/display')
) {
    throw 'The settings policy must protect the namespace root and authoritative leaves while leaving every application subtree to DAC.'
}
$execHookStart = $kernelPolicyText.IndexOf(
    'static int t1os_bprm_check(struct linux_binprm *bprm)',
    [System.StringComparison]::Ordinal
)
$execHookEnd = $kernelPolicyText.IndexOf(
    'static int t1os_kernel_read_file(struct file *file,',
    [Math]::Max(0, $execHookStart),
    [System.StringComparison]::Ordinal
)
$execHookBody = if ($execHookStart -ge 0 -and $execHookEnd -gt $execHookStart) {
    $kernelPolicyText.Substring($execHookStart, $execHookEnd - $execHookStart)
}
else {
    ''
}
if (
    -not $kernelPolicyText.Contains(
        'Protected runtime paths are a write-integrity boundary.'
    ) -or
    $execHookBody.Contains('t1os_check_path(') -or
    $execHookBody.Contains('denied protected executable') -or
    -not $execHookBody.Contains('t1os_is_forbidden_runtime_path(path)') -or
    -not $execHookBody.Contains('T1OS_MODPROBE_BINARY') -or
    -not $execHookBody.Contains('t1os_general_exec_allowed(domain, bprm, path)') -or
    -not $execHookBody.Contains('t1os_interpreted_script(bprm)') -or
    -not $execHookBody.Contains('t1os_general_exec_allowed(execsecurity->domain,') -or
    $kernelPolicyText.Contains('t1os_native_exec_allowed') -or
    $kernelPolicyText.Contains('t1os_catalogue_launch') -or
    $kernelPolicyText.Contains('t1os_window_launch') -or
    $kernelPolicyText.Contains('T1OS_CALCULATOR_SCRIPT') -or
    $kernelPolicyText.Contains('T1OS_WRITE_SCRIPT')
) {
    throw 'T1OS LSM does not cleanly separate general same-domain execution from protected-tree integrity and privileged transitions.'
}
if (-not $kernelPolicyText.Contains(
    'id == READING_MODULE || id == READING_MODULE_COMPRESSED'
)) {
    throw 'T1OS LSM does not authorize signed compressed modules through the measured module-loader.'
}
$kernelReadFileStart = $kernelPolicyText.IndexOf(
    'static int t1os_kernel_read_file(struct file *file,',
    [System.StringComparison]::Ordinal
)
$kernelReadFileEnd = $kernelPolicyText.IndexOf(
    'static int t1os_kernel_load_data(',
    [Math]::Max(0, $kernelReadFileStart),
    [System.StringComparison]::Ordinal
)
$kernelReadFileBody = if (
    $kernelReadFileStart -ge 0 -and $kernelReadFileEnd -gt $kernelReadFileStart
) {
    $kernelPolicyText.Substring(
        $kernelReadFileStart,
        $kernelReadFileEnd - $kernelReadFileStart
    )
}
else {
    ''
}
if (
    -not $kernelReadFileBody.Contains('id != READING_FIRMWARE') -or
    -not $kernelReadFileBody.Contains('t1os_is_driverserver_process()') -or
    -not $kernelReadFileBody.Contains('t1os_domain_is(T1OS_DOMAIN_MODULE_LOADER)') -or
    -not $kernelReadFileBody.Contains('t1os_kernel_firmware_worker()') -or
    -not $kernelReadFileBody.Contains('strncmp(path, "/the one/drivers/firmware/", 26)')
) {
    throw 'T1OS LSM does not authorize validated firmware reads through the measured loader and its kernel worker.'
}
$recursivePolicyStart = $kernelPolicyText.IndexOf(
    'static const char *prot_rec[] = {',
    [System.StringComparison]::Ordinal
)
$recursivePolicyEnd = $kernelPolicyText.IndexOf('};', $recursivePolicyStart)
$recursivePolicyBody = if ($recursivePolicyStart -ge 0 -and $recursivePolicyEnd -gt $recursivePolicyStart) {
    $kernelPolicyText.Substring(
        $recursivePolicyStart,
        $recursivePolicyEnd - $recursivePolicyStart
    )
}
else {
    ''
}
foreach ($protectedSystemRoot in @(
    '"/boot"',
    '"/the one/build"',
    '"/the one/software"',
    '"/the one/catalogue"'
)) {
    if (-not $recursivePolicyBody.Contains($protectedSystemRoot)) {
        throw "T1OS LSM does not recursively protect $protectedSystemRoot in Master role."
    }
}
foreach ($requiredText in @(
    '# Linux mode bits on an offline T1OS target are not an authorization boundary.',
    '"$python_software_destination"',
    '"$python_catalogue_destination"',
    '"$image_catalogue_destination"',
    '"$build_destination"',
    '"$boot_destination"',
    '"$virtualbox_software_destination"',
    "normalize_metadata = target_mode == 'image'",
    'updates deliberately do not chmod/chown DrvFS paths'
)) {
    if (-not $rootPushText.Contains($requiredText)) {
        throw "The offline deployer cannot replace an arbitrary legacy mode layout: $requiredText"
    }
}
foreach ($forbiddenText in @(
    'managed update requires the 0755 directory policy',
    'migrate or reimage this legacy USB before retrying',
    'for writable_ancestor in'
)) {
    if ($rootPushText.Contains($forbiddenText)) {
        throw "The offline deployer still rejects a legacy Linux mode layout: $forbiddenText"
    }
}

Write-Host 'Hardware kernel policy contracts validation passed.'
