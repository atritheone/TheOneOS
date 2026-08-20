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
$initText = Get-Content -LiteralPath $initScript -Raw
$angelContractText = Get-Content -LiteralPath $angelContract -Raw
$goddessText = Get-Content -LiteralPath $goddessScript -Raw
$authenticationBrokerText = Get-Content -LiteralPath $authenticationBroker -Raw
foreach ($requiredText in @(
    'Angel is the guardian of the T1OS boot partition',
    "angel_prefix='~ '",
    "angel_suffix=' ~'",
    'printf ''%s%s%s\n'' "$angel_prefix" "$message" "$angel_suffix"',
    'I have prepared the root drive and will now hand control to GODDESS.'
)) {
    if (-not $initText.Contains($requiredText)) {
        throw "Angel's initramfs voice contract is missing: $requiredText"
    }
}
if ($initText.Contains("tr '[:lower:]' '[:upper:]'")) {
    throw "Angel's initramfs voice still converts her speech to GODDESS-style uppercase."
}
foreach ($requiredText in @(
    'bootloader,',
    'kernel and initramfs handoff',
    'operating',
    'system reset, and reinstallation',
    '~ This is an example line of Angel. ~'
)) {
    if (-not $angelContractText.Contains($requiredText)) {
        throw "Angel's ownership contract is incomplete: $requiredText"
    }
}
foreach ($requiredText in @(
    "ANGELPREFIX = '~ '",
    "ANGELSUFFIX = ' ~'",
    'def formalsystemname(message):',
    'def formatangel(message):',
    'def angelprint(*values,',
    "recordoutputfailure('angel-print', output, error)",
    'angelprint(',
    'I am recovering the {backend} graphics backend'
)) {
    if (-not $goddessText.Contains($requiredText)) {
        throw "GODDESS does not delegate recovery speech to Angel: $requiredText"
    }
}
if ($initText -match '(?m)^root=/dev/(sda|vda)') {
    throw 'The hardware init script still contains a guessed root disk.'
}
foreach ($requiredText in @(
    'root=*) root_spec=${argument#root=}',
    'UUID=?*|PARTUUID=?*|LABEL=?*|/dev/?*)',
    'UUID=*) expected=${device_spec#UUID=}; token="UUID=\"$expected\""',
    'PARTUUID=*) expected=${device_spec#PARTUUID=}; token="PARTUUID=\"$expected\""',
    'root_fstype=ntfs3',
    'ntfs_mount_options=uid=0,gid=0,fmask=0022,dmask=0022,windows_names,acl',
    'mount_t1os_root ro',
    '"$busybox" umount /mnt',
    'admit_t1os_ntfs_root',
    '"$busybox" timeout -k 1 8 /sbin/roothealth',
    '/sbin/roothealth',
    '--boot-repair',
    '--require-t1os-root',
    'RootHealth admitted the root.',
    'RootHealth did not admit the unmounted NTFS root',
    'roothealth_admission_status',
    'persist_ntfs_health_report',
    'persist_angel_log_to_root',
    'persist_angel_failure_log',
    'persist_roothealth_boot_history',
    'roothealth_history_limit=5',
    'diagnostics/roothealth-history',
    '"$history_root/boot-1/manifest.env"',
    'refusal_fingerprint=%s',
    'failure_kind=%s',
    'admission_status=%s',
    'angel-failure.log',
    'roothealth.stderr',
    'roothealth.json',
    'roothealth_report_primary_code',
    'roothealth_report_failed_predicates',
    'MFT_BITMAP_MISMATCH',
    ': >"$roothealth_report"',
    'diagnostic_target="$diagnostics/$diagnostic_name"',
    'Never present evidence from an older boot as the current result.',
    'boot.env',
    'mountinfo',
    'dmesg.log',
    '"$logs/angel.log"',
    '"$busybox" cp /run/roothealth.json "$report_tmp"',
    'write_roothealth_log >"$log_tmp"',
    '"$busybox" mv "$log_tmp" "$logs/roothealth.log"',
    '[roothealth] root drive check completed',
    '[roothealth] fresh read-only rescan proved the root drive clean',
    '[roothealth] advisory verdict did not gate boot; the kernel mount and mounted T1OS identity were authoritative',
    'previous_kernel_log="$logs/kernel.log"',
    '''/mnt/the one/logs/kernel.log''',
    'mount_t1os_root rw',
    'ensure_runtime_permissions',
    'ensure_persistent_runtime_permissions',
    "software='/mnt/software'",
    "rubbish='/mnt/.rubbish'",
    "logs='/mnt/the one/logs'",
    'expected_software_metadata',
    'system log tier is not writable',
    'The unmounted restart health gate passed. I will continue this clean boot now.',
    'angel_unmount_esp',
    'protected_inventory=/protected-roots.tsv',
    'profiled_python_inventory=/profiled-python-entrypoints.tsv',
    'done < "$profiled_python_inventory"',
    'stat -c ''%a'' "$protected_inventory"',
    '"$busybox" mount --make-rprivate /mnt',
    'mount_tree_is_private',
    '/^(shared|master):/',
    'verify_managed_release_integrity',
    'recheck_managed_release_integrity',
    'secure_protected_mount_root',
    'stat -c ''%h''',
    '! -type d ! -type f -print -quit',
    'sort -z',
    'python_software python_catalogue image_catalogue',
    'build_software boot virtualbox_software',
    '/the one/software/python',
    '/the one/software/python/bin/python',
    '/the one/catalogue/python',
    '/the one/catalogue/image',
    '/the one/build',
    '/the one/software/virtualbox',
    'T1OS LSM denies Master-role mutation',
    'export PYTHONNOUSERSITE=1',
    'export PYTHONDONTWRITEBYTECODE=1',
    'export PYTHONSAFEPATH=1',
    'unset PYTHONHOME PYTHONPATH',
    '-B -I',
    '"$busybox" chmod 4755 "$sandbox"',
    '"$busybox" chmod 0755 "$root_directory"',
    'root filesystem did not retain its secure root-directory permission',
    'prepare_terminfo_runtime',
    "target=`"`$ephemeral/terminfo`"",
    "export TERMINFO='/.ephemeral/terminfo'",
    'verify_t1os_root',
    'validate_protected_file python_software bin/python',
    'cryptsetup open',
    '/the one/drivers/control',
    '/the one/drivers/processes',
    'mount -t devpts',
    'newinstance,gid=1000,ptmxmode=0660,mode=0600',
    '/the one/drivers/nodes/pts/ptmx',
    'chown 0:1000',
    'chmod 0660',
    '$ephemeral/media',
    'chown 1000:1000',
    'chmod 0700',
    '$ephemeral/expanse',
    'chmod 0711',
    "python_management='/mnt/the one/software/python/pip'",
    "legacy_python_management='/mnt/the one/software/python/.t1pip'",
    '"$busybox" mv -- "$legacy_python_management" "$python_management"',
    'if [ -L "$python_management" ]; then',
    '"$python_management/artifacts"',
    '"$python_management/transactions"',
    '$ephemeral/audio',
    'chmod 02710',
    'mount -t efivarfs',
    'recovery restart will remain disabled',
    '/the one/drivers/tools/modprobe',
    't1os.quiet=1',
    'export T1OS_QUIET=1',
    'framebuffer) export T1OS_GRAPHICS=framebuffer',
    'T1OS_DISPLAY_CONSOLE_FD=3',
    "exec 3<>'/mnt/the one/drivers/nodes/tty0'",
    'archive_previous_boot_logs',
    'atreyan_boot_timestamp',
    'previous_boot_timestamp=',
    'archive_directory="$logs/$previous_boot_timestamp"',
    '"$archive_directory/$evidence_name"',
    'printf "%s-%s-%dAE %s.%s.%s\n"',
    'atreyan_boot_timestamp || printf ''unknown-time-%s\n'' "$boot_id"',
    'failed_gpu_boot=1',
    'previous-gpu-boot.txt',
    'write_hardware_inventory',
    'hardware_inventory.log',
    'boot_id=%s',
    'kernel ring at init handoff'
)) {
    if (-not $initText.Contains($requiredText)) {
        throw "The hardware init script is missing the safety behavior: $requiredText"
    }
}
if ($initText.Contains('if ! verify_managed_release_integrity; then')) {
    throw 'The hardware init script still treats recovery-version drift as a normal-boot failure.'
}
foreach ($forbiddenBootGate in @(
    'preflight_t1os_ntfs_root',
    'check_t1os_ntfs_root',
    'mount_t1os_root ro force',
    'mount_t1os_root rw force',
    'advisory status',
    'I will decide from the next NTFS mount attempt',
    'touch "$operations_file"'
)) {
    if ($initText.Contains($forbiddenBootGate)) {
        throw "The hardware init script retains the obsolete advisory/force path: $forbiddenBootGate"
    }
}
if ($initText -match '(?m)^recheck_managed_release_integrity\s*$') {
    throw 'The hardware init script still repeats the managed-tree hash scan before handoff.'
}
$bootStatusMatch = [regex]::Match(
    $initText,
    '(?ms)^boot_status\(\) \{(?<body>.*?)^\}'
)
if (-not $bootStatusMatch.Success -or $bootStatusMatch.Groups['body'].Value.Contains('/dev/tty0')) {
    throw 'Angel still writes successful normal-boot milestones to the physical display.'
}
if (-not $initText.Contains('if [ "$angel_visible" = 1 ] && [ -c /dev/tty0 ]; then')) {
    throw 'Angel physical output is not restricted to an explicit failure path.'
}
if ($initText.Contains('initramfs.log')) {
    throw 'Angel still uses the obsolete initramfs.log filename.'
}
if ($initText.Contains('/the one/software/python/bin/python3.13')) {
    throw 'The current hardware init script bypasses the stable Python entrypoint.'
}

$brickText = Get-Content -LiteralPath $brickScript -Raw
foreach ($requiredText in @(
    'class ConsoleDisplay:',
    'def consoleopenpair():',
    'def startconsole(',
    'def consolekeyevent(',
    'def graphicsbuildconsole(',
    'def drawconsole(',
    'def consolefit():',
    'def consolediagnosticcommand():',
    "'T1OS_CONSOLE': '1'",
    "b'\x1b[200~'",
    'signal.SIGWINCH',
    "'kind': 'console_grid'"
)) {
    if (-not $brickText.Contains($requiredText)) {
        throw "Brick is missing interactive console support: $requiredText"
    }
}
if ($brickText.Contains('opsrunstream(prog, prog_args, name, logpath, user)')) {
    throw 'Brick still uses the line-framed operation stream for foreground software.'
}
foreach ($forbiddenText in @(
    'archive_prefix=',
    'filename_prefix=',
    '"$logs/$archive_prefix$evidence_name"'
)) {
    if ($initText.Contains($forbiddenText)) {
        throw "The hardware init script still archives prior-boot logs with filename prefixes: $forbiddenText"
    }
}
foreach ($forbiddenText in @(
    'verify_python_release',
    'python-release.sha256',
    'protect_root_bind_mount',
    'protected_mount_state',
    'remount,bind,ro,nodev,nosuid',
    'remount,bind,ro,nodev,nosuid,noexec',
    '/sbin/ntfsfix',
    '--clear-dirty',
    'repair_ntfs_root',
    'verify_repaired_ntfs_root',
    'ntfs_repair_attempted'
)) {
    if ($initText.Contains($forbiddenText)) {
        throw "The hardware init script retains obsolete or unsafe protected-root behavior: $forbiddenText"
    }
}

$admissionCallOffset = $initText.LastIndexOf("`nadmit_t1os_ntfs_root || \`n")
$mainReadOnlyMountOffset = $initText.LastIndexOf('if ! mount_t1os_root ro; then')
if (
    $admissionCallOffset -lt 0 -or
    $mainReadOnlyMountOffset -lt 0 -or
    $admissionCallOffset -ge $mainReadOnlyMountOffset
) {
    throw 'The hardware init script does not require bounded RootHealth admission before its first normal NTFS mount.'
}
$admissionFunction = [regex]::Match(
    $initText,
    '(?ms)^admit_t1os_ntfs_root\(\) \{(?<body>.*?)^\}'
)
if (
    -not $admissionFunction.Success -or
    -not $admissionFunction.Groups['body'].Value.Contains('run_roothealth_boot_repair') -or
    -not $admissionFunction.Groups['body'].Value.Contains('return "$roothealth_admission_status"')
) {
    throw 'RootHealth admission does not propagate the bounded boot-repair verdict.'
}

Write-Host 'Hardware init and desktop contracts validation passed.'
