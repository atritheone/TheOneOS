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
$angelVoiceTest = Join-Path $projectRoot 'scripts\test angel voice.py'
$angelRecoveryTest = Join-Path $projectRoot 'scripts\test angel recovery.ps1'
$initramfsBuilder = Join-Path $projectRoot 'scripts\build hardware initramfs.ps1'
$bootPolicyBuilder = Join-Path $projectRoot 'scripts\build boot protected roots.py'
$ntfsCheckerBuilder = Join-Path $projectRoot 'scripts\build roothealth.ps1'
$ntfsCheckerTest = Join-Path $projectRoot 'scripts\test roothealth.ps1'
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
$productionPreparer = Join-Path $projectRoot 'scripts\prepare prod build.ps1'
$hardwareUsbWorkflow = Join-Path $projectRoot 'scripts\build hardware usb.ps1'
$kernelBuilder = Join-Path $projectRoot 'scripts\build hardware kernel.ps1'
$graphicsKernelBuilder = Join-Path $projectRoot 'scripts\build graphics kernel.ps1'
$rootPushScript = Join-Path $projectRoot 'scripts\push to disk.ps1'
$hardwareKernelPushScript = Join-Path $projectRoot 'scripts\push hardware kernel to usb.ps1'
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
$compatibilityValidator = Join-Path $projectRoot 'scripts\validate hardware compatibility.ps1'
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
$authenticationBrokerText = Get-Content -LiteralPath $authenticationBroker -Raw
$goddessText = Get-Content -LiteralPath $goddessScript -Raw
$driverServerText = Get-Content -LiteralPath $driverServer -Raw
foreach ($requiredText in @("TERMINFOBASE = '/.ephemeral/terminfo'", 'os.path.ismount(EPHEMERALTIER)', 'unmountpath(TERMINFOBASE)')) {
    if (-not $goddessText.Contains($requiredText)) {
        throw "GODDESS is missing runtime terminfo cleanup: $requiredText"
    }
}
foreach ($requiredText in @('QUIETSYSTEM = os.environ.get(', 'if QUIETSYSTEM and not force:', 'mirrordisplayconsole(force=True)', 'def attachserialconsole():', "node = '/the one/drivers/nodes/ttyS0'", 'os.dup2(descriptor, standard, inheritable=True)', 'self.primary.flush()', 'os.O_WRONLY | os.O_NONBLOCK', "raise OSError('display mirror is not a character device')", 'os.close(displayfd)', 'termios.tcgetattr(DISPLAYCONSOLEFD)', 'attributes[3] &= ~echoflags', "NULLDEVICE = '/the one/drivers/nodes/null'", "DISPLAYCONSOLENODE = '/the one/drivers/nodes/tty0'", 'DISPLAYCONSOLEMODETIMEOUT = 2.0', 'DISPLAYCONSOLEHELPERRETIRETIMEOUT = 5.0', 'fcntl.ioctl(int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]))', 'pass_fds=(DISPLAYCONSOLEFD,)', 'def waitdisplayconsolemodehelper(', 'graphicsconsole = graphicsbackend != ''framebuffer''', 'if not setdisplayconsolemode(graphicsconsole):', 'setdisplayconsolemode(True)', 'setdisplayconsolemode(False)')) {
    if (-not $goddessText.Contains($requiredText)) {
        throw "GODDESS is missing the display-console ownership behavior: $requiredText"
    }
}
foreach ($requiredText in @('final_created = False', 'if final_created or repair_existing:', 'status.st_uid != os.geteuid()', 'status.st_gid != os.getegid()', 'stat.S_IMODE(status.st_mode) != final_mode', 'repair_existing=True')) {
    if (-not $authenticationBrokerText.Contains($requiredText)) {
        throw "The authentication broker is missing descriptor-secure directory metadata enforcement: $requiredText"
    }
}
if ($goddessText.Contains('subprocess.DEVNULL')) {
    throw 'GODDESS recovery helpers still depend on the forbidden /dev/null hierarchy.'
}
foreach ($requiredText in @(
    'DRIVERSERVERENABLED = (',
    'os.path.isfile(DRIVERSERVERSCRIPT)',
    'and os.path.isfile(DRIVERPOLICY)',
    "def kernelcommandlineoption(option):",
    "kernelcommandlineoption('t1os.chromium-diagnostic=1')",
    "'engine-diagnostic'",
    "GRAPHICSSOFTWARELOG = '/the one/logs/graphics.py.log'",
    "WINDOWSERVERSOFTWARELOG = '/the one/logs/windowserver.py.log'",
    'def _kernelringbuffer():',
    'operation(3, buffer, size)',
    'def _gpufailurestate():',
    'def capturegpufailureevidence(payload):',
    'GRAPHICSDIAGNOSTICTIMEOUT = 3.0',
    'def capturewindowserverhangpid(pid, phase):',
    'def capturewindowserverhangbounded(process, phase):',
    'def capturegpufailureevidencebounded(payload):',
    "'--graphics-hang-capture'",
    "'--graphics-kernel-capture'",
    'capturegpufailureevidence(payload)',
    "GRAPHICSRECOVERYBOOT = '/the one/settings/graphics recovery boot.json'",
    "NVIDIAPATHPROVIDER = '/.ephemeral/graphics/nvidia-path-provider.so'",
    "NVIDIACACHEPATH = '/.ephemeral/cache/nvidia'",
    "'/the one/catalogue/graphics/nvidia/t1os-nvidia-path-provider.so'",
    'def preparenvidiapathprovider():',
    'os.makedirs(NVIDIACACHEPATH, mode=0o1777, exist_ok=True)',
    'os.fchmod(cachedescriptor, 0o1777)',
    'os.makedirs(parent, mode=0o711, exist_ok=True)',
    'os.fchown(parentdescriptor, 0, 0)',
    'os.fchmod(parentdescriptor, 0o711)',
    'os.fchown(descriptor, 0, 0)',
    'os.fchmod(descriptor, 0o555)',
    "environment['LD_PRELOAD'] = pathprovider",
    "environment['T1OS_NVIDIA_PATH_PROVIDER'] = pathprovider",
    "environment['T1OS_NVIDIA_PATH_PROVIDER_SOURCE'] = (",
    'NVIDIAPATHPROVIDERSOURCE',
    'def requestfirmwaregraphicsrecovery(reason, attempt):',
    'def pinfirmwarerecoveryboot(root=EFIVARFSROOT):',
    'def graphicsaccelerationrequired():',
    'def discardlegacyfirmwaregraphicsrecovery():',
    "'gpu-required-retry'",
    'persistent next-boot framebuffer recovery is disabled',
    'FS_IOC_GETFLAGS = 0x80086601',
    'FS_IOC_SETFLAGS = 0x40086602',
    'FS_IMMUTABLE_FL = 0x00000010',
    "f'BootCurrent-{EFIVARGLOBALGUID}'",
    "f'BootNext-{EFIVARGLOBALGUID}'",
    "payload = struct.pack('<IH', 7, current)",
    'if verified != payload:',
    "kernelcommandlineoption('t1os.graphics=framebuffer')",
    'WINDOWSERVERREADYMAXTIME = 90.0',
    'WINDOWSERVERGPUFAILUREEXIT = 70',
    'WINDOWSERVERBACKENDINITFAILUREEXIT = 71',
    'WINDOWSERVERCOMPOSITORFAILUREEXIT = 72',
    'KMSRECOVERYATTEMPTSPERCYCLE = 3',
    'def drmscanoutnodeavailable():',
    'def accelerateddrmcandidates():',
    'def nextaccelerateddrmdevice():',
    'def nextkmsdrmdevice():',
    "environment['T1OS_DRM_DEVICE'] = drmdevice",
    "environment['__NV_GBM_TRACE_ENABLED'] = '1'",
    "environment['T1OS_FRAMEBUFFER_CONSOLE_OWNED'] = '1'",
    'def normalisebootid(value):',
    'def currentbootid(paths=BOOTIDPATHS):',
    "'early-framebuffer-owner-retirement'",
    "'display-console-ownership'",
    "'display-console-recovery'",
    'while not stopbootanimation(earlybootanimation):',
    "'CPU-KMS WindowServer readiness device loss'",
    "'CPU-KMS lock-screen presentation device loss'",
    "backend='kms-framebuffer'",
    "'accelerated-device-candidate-retry'",
    'def acceleratedfailureaction(windowserverproc, acceptresponsive=False):',
    "'accelerated-userspace-failure'",
    'preserving HDMI/KMS',
    'currentprogress != progress',
    'def _driverservergraphicsreset(bdf, driver):',
    "'request': 'RESET_GRAPHICS'",
    'connection.connect(DRIVERSERVERACCEPT)',
    'recovered = True',
    'recovered = recovered and ready',
    'if not recovered:',
    'authorized GPU reset failed after accelerated'
)) {
    if (-not $goddessText.Contains($requiredText)) {
        throw "GODDESS is missing module-independent Driver Server startup: $requiredText"
    }
}
foreach ($retiredGraphicsLog in @('gpu-hang-python.log', 'gpu-hang-process.log', 'gpu-failure-kernel.log')) {
    if ($goddessText.Contains($retiredGraphicsLog)) {
        throw "GODDESS still creates retired standalone graphics log: $retiredGraphicsLog"
    }
}
foreach ($forbiddenText in @(
    'and os.path.isfile(DRIVERMODULELOADER)',
    'and os.path.isdir(DRIVERKERNELROOT)'
)) {
    if ($goddessText.Contains($forbiddenText)) {
        throw "GODDESS still makes device policy conditional on a module runtime: $forbiddenText"
    }
}
if ($goddessText.Contains('recovered = recovered or ready')) {
    throw 'GODDESS still allows one recovered adapter to mask another poisoned adapter.'
}
$failedResetBranches = [regex]::Matches(
    $goddessText,
    '(?ms)^\s+if not recovered:\r?\n(?<body>.*?)^\s+elif acceleratedattempts < ACCELERATEDLOGINATTEMPTS:'
)
if ($failedResetBranches.Count -ne 3) {
    throw "GODDESS must have exactly three authoritative failed-reset barriers; found $($failedResetBranches.Count)."
}
foreach ($failedResetBranch in $failedResetBranches) {
    $failedResetBody = $failedResetBranch.Groups['body'].Value
    $recoveryRequestOffset = $failedResetBody.IndexOf(
        'requestfirmwaregraphicsrecovery('
    )
    $kmsOffset = $failedResetBody.IndexOf(
        "graphicsbackend = 'kms-framebuffer'"
    )
    if (
        $recoveryRequestOffset -lt 0 -or
        $kmsOffset -lt 0 -or
        $recoveryRequestOffset -gt $kmsOffset -or
        $failedResetBody.Contains('acceleratedattempts +=') -or
        $failedResetBody.Contains("graphicsbackend = 'opengl'") -or
        $failedResetBody.Contains("graphicsbackend = 'framebuffer'")
    ) {
        throw (
            'An authoritative GPU-reset failure does not arm firmware recovery ' +
            'before attempting the last same-boot CPU-KMS owner.'
        )
    }
}
if (
    ([regex]::Matches(
        $goddessText,
        [regex]::Escape("backend='kms-framebuffer'")
    )).Count -ne 2
) {
    throw 'GODDESS must reset the exact selected DRM driver at both CPU-KMS device-loss barriers.'
}
$earlyAnimationOffset = $goddessText.IndexOf(
    "earlybootanimation = startbootanimation('early-dots')"
)
$earlyDriverBirthOffset = $goddessText.IndexOf(
    'birth(EARLYSYSTEMOPS)',
    $earlyAnimationOffset
)
$earlyRetirementOffset = $goddessText.IndexOf(
    'while not stopbootanimation(earlybootanimation):',
    $earlyDriverBirthOffset
)
if (
    $earlyAnimationOffset -lt 0 -or
    $earlyDriverBirthOffset -le $earlyAnimationOffset -or
    $earlyRetirementOffset -le $earlyDriverBirthOffset
) {
    throw 'The early framebuffer writer does not remain active through DriverServer discovery.'
}
if (
    -not $driverServerText.Contains(
        'self.early_boot_animation_retired = retireearlybootanimation()'
    ) -or
    -not $driverServerText.Contains(
        "statpath = PROCESSROOT / str(int(pid)) / 'stat'"
    )
) {
    throw 'DriverServer does not retire the framebuffer writer at native display binding.'
}

$preStartOffset = $goddessText.IndexOf('PRESTARTOPS = [')
$postStartOffset = $goddessText.IndexOf('POSTSTARTOPS = [')
$networkWaitOffset = $goddessText.IndexOf('waitnetworkstartup(networkproc)')
$startupLaunchOffset = $goddessText.IndexOf('runstartup(startupenvironment, wsproc)')
if (
    $preStartOffset -lt 0 -or
    $postStartOffset -le $preStartOffset -or
    -not $goddessText.Substring(
        $preStartOffset,
        $postStartOffset - $preStartOffset
    ).Contains("('network', NETWORKSCRIPT, 'behind')") -or
    $networkWaitOffset -lt 0 -or
    $startupLaunchOffset -lt 0 -or
    $networkWaitOffset -gt $startupLaunchOffset
) {
    throw 'GODDESS does not start and await the initial network attempt before login.'
}

$inputServerText = Get-Content -LiteralPath $inputServer -Raw
if ($inputServerText.Contains('EVENT_CANDIDATES')) {
    throw 'Input Server still restricts hardware discovery to a fixed event-node list.'
}

$chromiumServerText = Get-Content -LiteralPath $chromiumServer -Raw
foreach ($requiredText in @(
    'SINGLETONNAMES = ("SingletonLock", "SingletonSocket", "SingletonCookie")',
    'def chromiumprocessalive(process):',
    'def zygoteproviderstatus(',
    'def zygoteprovideractive(',
    'expected_launch_id=""',
    'def gpucandidateruntimeready(',
    'with open(entry.path + "/environ", "rb") as stream:',
    'b"LD_LIBRARY_PATH=" + expected_library_path.encode()',
    'commandpath = f"{PROCESSROOT}/{process}/cmdline"',
    'def clearstaleprofilelock():',
    'clearstaleprofilelock()',
    'DNSFILE = "/the one/settings/network/dns.txt"',
    'SESSIONIDENTITYFILE = "/the one/settings/session/identity.json"',
    'with open(SESSIONIDENTITYFILE, "rb") as stream:',
    'return f"/master/{mastername()}/flash"',
    'downloads = downloaddir()',
    'if not os.path.isdir(downloads) or os.path.islink(downloads):',
    'def ensurednsconfiguration():',
    '=== chromium session started pid=',
    'window lifecycle operation=',
    'chromium engine stopping reason=',
    '"--enable-gpu"',
    '"--use-angle=swiftshader"',
    '"--enable-unsafe-swiftshader"',
    '"--disable-features=Vulkan,DefaultANGLEVulkan,VulkanFromANGLE"',
    '"--force-color-profile=srgb"',
    '"LD_LIBRARY_PATH": LIBRARIES + ":" + GRAPHICSCATALOGUE',
    '"--ignore-gpu-blocklist"',
    '"--disable-gpu-driver-bug-workarounds"',
    '"--use-gl=angle"',
    '"--use-angle=swiftshader"',
    '"--enable-unsafe-swiftshader"',
    'NVIDIADIRECTVAAPIQUARANTINED = True',
    '"--disable-accelerated-video-decode"',
    '"--disable-features=AcceleratedVideoDecodeLinuxGL,"',
    '",VaapiOnNvidiaGPUs"',
    'MEDIADECODEFEATURE = "T1OSVideoDecoder"',
    'PRESENTATIONFEATURE = "T1OSNvidiaPresentation"',
    'NVIDIAPRESENTATIONVARIABLE = "T1OS_CHROMIUM_NVIDIA_PRESENTATION"',
    'def nvidiapresentationenabled():',
    '"t1os.chromium.nvidia-presentation=0"',
    'and nvidiapresentationenabled()',
    'MEDIADECODESOCKETSWITCH = "--t1os-video-decode-socket="',
    'MEDIADECODEOUTPUTVARIABLE = "T1OS_MEDIA_DECODE_OUTPUT"',
    'MEDIADECODEOUTPUTSWITCH = "--t1os-video-decode-output="',
    'def t1osmediadecoderconfiguration(graphicsdriver):',
    'capability.get("brokered_socket") is not True',
    'def t1osmediadecoderarguments(configuration):',
    'def t1osmediadecoderoutputmode(presentationbridge):',
    'def mergechromiumfeaturearguments(arguments):',
    'chrome_arguments = mergechromiumfeaturearguments(chrome_arguments)',
    'def servicechromiumenvironment(environment):',
    'or name.startswith("CUDA_")',
    'def chromiumgraphicsenvironment(',
    'presentationbridge=True,',
    'if presentationbridge:',
    'result[NVIDIAGPULIBRARYPATHVARIABLE] = NVIDIAGRAPHICSLIBRARYPATH',
    'result[NVIDIAGPUEGLVENDORVARIABLE] = NVIDIAEGLVENDORFILE',
    'result[NVIDIAGPUGBMBACKENDSPATHVARIABLE] = NVIDIAGBMPATH',
    'def activegraphicsrendernode(',
    'def validatedwindowgraphicscontract(contract):',
    'def capturewindowgraphicscontract(graphics):',
    'surfaces.get("render_identity")',
    'stat.S_ISCHR(status.st_mode)',
    'DRMNODEROOT = "/the one/drivers/nodes/dri"',
    'def measurevideoacceleration(acceleration, rendernode):',
    'CHROMIUMVIDEOCODECS = frozenset(("H264", "VP8", "VP9", "AV1"))',
    'browsercodecs = measuredcodecs & CHROMIUMVIDEOCODECS',
    'or not browsercodecs',
    '"--hardware-video-device-path="',
    'NVIDIARUNTIMEPATH = GRAPHICSCATALOGUE + "/nvidia"',
    'NOUVEAURENDERER = "angle-swiftshader"',
    'def rendererconfiguration(graphicsdriver, presentationbridge=True):',
    'chromium audio output unavailable; continuing muted:',
    'chromium audio stream interrupted; continuing muted:',
    'max(width, int(screenwidth if screenwidth is not None else width))',
    'CHROMEEXECUTABLE = PROGRAM + "/chrome"',
    'SANDBOXEXECUTABLE = "./chrome-sandbox"',
    'SANDBOXROOT = RUNTIME + "/sandbox-root"',
    'CHROMEEXECUTABLE, "--ozone-platform=x11"',
    '"zygote_provider": False',
    '"zygote_library_path": False',
    '"zygote_verified": False',
    '"library_path": environment.get("LD_LIBRARY_PATH", "")',
    'chrome_environment["T1OS_CHROMIUM_SANDBOX_DISCOVERY"] = "1"',
    'chrome_environment[CHROMIUMLAUNCHVARIABLE] = launch_id',
    '"launch_id": launch_id',
    'processidentity=dropengineidentity',
    'probetimeout=CHROMEPROBETIMEOUT',
    'env=chrome_environment, cwd=PROGRAM, preexec_fn=dropengineidentity',
    'def claiminstance():',
    'def serviceinstanceactivations():',
    'forwarded launch to active chromium instance',
    'if not claiminstance():',
    'f"chromium-sandbox+architect-policy gl_provider="',
    'chromium window ready id=',
    'class JsonLineQueue:',
    'TRANSPORTQUEUELIMIT',
    'TRANSPORTFLUSHBUDGET',
    'WSOUTPUT = JsonLineQueue(damage=True)',
    'ENGINEOUTPUT = JsonLineQueue(limit=ENGINEQUEUELIMIT, motion=True)',
    'controloutput = JsonLineQueue(limit=ENGINEQUEUELIMIT, damage=True)',
    'class PersistentInputBridge:',
    'class ChromiumInputBridgeError(RuntimeError):',
    'A bounded nonblocking connection to the persistent X11 input helper.',
    'os.set_blocking(self.process.stdin.fileno(), False)',
    'self.output = bytearray()',
    'self.pendingmotion = None',
    'def flush(self, budget=INPUTBRIDGEFLUSHBUDGET):',
    'writabletargets.append(inputbridge.process.stdin)',
    'inputbridge.flush()',
    'except (BufferError, ChromiumInputBridgeError):',
    'def processwindowmanageroutput():',
    'parts[0] == b"FULLSCREEN"',
    'xwmincoming = startupxwmincoming',
    'def drainjsonoutput(queue, target, timeout=0.5):',
    'predrained = drainjsonoutput(WSOUTPUT, WSOCK, timeout=0.5)',
    'drained = drainjsonoutput(WSOUTPUT, WSOCK, timeout=0.5)',
    'os.kill(process, signal.SIGKILL)',
    'Chromium engine did not reap after SIGKILL pid=',
    'def startinputbridge(environment, windowid):',
    'persistent Chromium input bridge connected',
    'return [path, *map(str, arguments)]',
    'elf(TOOLS + "/t1os-xwm")',
    'LIBRARIES + "/libXdamage.so.1"',
    'LIBRARIES + "/libXfixes.so.3"',
    'pcm.t1os_null {',
    'CACHE = RUNTIME + "/cache"',
    'DISKCACHEBYTES = 256 * 1024 * 1024',
    'MEDIACACHEBYTES = 128 * 1024 * 1024',
    'def cachearguments():',
    'f"--disk-cache-size={DISKCACHEBYTES}"',
    'f"--media-cache-size={MEDIACACHEBYTES}"',
    'checks["cache_policy"] = (',
    'FONTCACHE = SETTINGROOT + "/font-cache"',
    'def repairchromiumownedtree(path, uid=ENGINEUID, gid=ENGINEGID):',
    'os.stat(name, dir_fd=descriptor, follow_symlinks=False)',
    'os.fchown(descriptor, uid, gid)',
    'os.fchmod(descriptor, 0o700)',
    'os.fchmod(child, 0o600)',
    'unexpected symbolic link in Chromium owned state:',
    'def probechromiumownedroots(paths, uid=ENGINEUID, gid=ENGINEGID):',
    'Chromium owned state write probes passed roots=',
    '"GSETTINGS_BACKEND": "memory"',
    'scrollclicks == [4, 5]',
    'def audiodiagnostic():',
    'ALSA null PCM still contains a conventional device path',
    '"DBUS_SESSION_BUS_ADDRESS": "unix:path=" + RUNTIMEROOT + "/no-session-bus"'
)) {
    if (-not $chromiumServerText.Contains($requiredText)) {
        throw "Chromium runtime integration is missing: $requiredText"
    }
}
if (
    $chromiumServerText.Contains('MASTERFILE =') -or
    $chromiumServerText.Contains('/the one/master/master.txt')
) {
    throw 'Chromium still reads the protected master credential record directly.'
}
if ($chromiumServerText.Contains('elf(LOADER')) {
    throw 'Chromium runtime must direct-exec measured helpers, not a generic dynamic loader.'
}
$cleanupStartIndex = $chromiumServerText.IndexOf('def cleanup():')
$preStopDrainIndex = $chromiumServerText.IndexOf(
    'predrained = drainjsonoutput(WSOUTPUT, WSOCK, timeout=0.5)',
    [Math]::Max(0, $cleanupStartIndex)
)
$cleanupStopEngineIndex = $chromiumServerText.IndexOf(
    '    stopengine()',
    [Math]::Max(0, $cleanupStartIndex)
)
if (
    $cleanupStartIndex -lt 0 -or
    $preStopDrainIndex -lt $cleanupStartIndex -or
    $cleanupStopEngineIndex -le $preStopDrainIndex
) {
    throw 'Chromium cleanup does not drain WindowServer controls before engine teardown.'
}
foreach ($forbiddenChromiumStateImplementation in @(
    'CACHE = SETTINGROOT + "/cache"',
    'def repairwritabletree(path, uid=ENGINEUID, gid=ENGINEGID):',
    'nextfullscreenprobe'
)) {
    if ($chromiumServerText.Contains($forbiddenChromiumStateImplementation)) {
        throw "Chromium retains an unsafe or persistent state implementation: $forbiddenChromiumStateImplementation"
    }
}
if ($chromiumServerText.Contains('os.listdir("/master")')) {
    throw 'Chromium still guesses its download owner by scanning /master.'
}
if ($chromiumServerText.Contains('(downloaddir(), 0o755)')) {
    throw 'Chromium still creates the T1OS downloads directory.'
}
foreach ($forbiddenVulkanForce in @(
    '"--use-angle=vulkan"',
    '"--enable-features=Vulkan,DefaultANGLEVulkan,VulkanFromANGLE"',
    'environment["VK_DRIVER_FILES"]',
    'environment["VK_ICD_FILENAMES"]'
)) {
    if ($chromiumServerText.Contains($forbiddenVulkanForce)) {
        throw "Chromium still forces the unsupported Nouveau Vulkan presentation path: $forbiddenVulkanForce"
    }
}
foreach ($forbiddenProcessAlias in @(
    'SANDBOXPROCESSROOT',
    'mountprocessruntime',
    'unmountprocessruntime'
)) {
    if ($chromiumServerText.Contains($forbiddenProcessAlias)) {
        throw "Chromium still creates the obsolete process-interface alias: $forbiddenProcessAlias"
    }
}
$chromiumProviderSourceText = Get-Content -LiteralPath $chromiumProviderSource -Raw
foreach ($requiredText in @(
    '{ "/the one/software/chromium/program/extensions", "/.ephemeral/chromium/extensions", true }',
    '{ "/opt/google/chrome/extensions", "/.ephemeral/chromium/extensions", true }',
    '{ "/opt/google/chrome", "/the one/software/chromium/program", true }',
    '{ "/media", "/.ephemeral/volumes", true }',
    '{ "/mnt", "/.ephemeral/volumes", true }',
    '#define T1OS_CHROMIUM_PERSISTENT_SANDBOX',
    '#define T1OS_CHROMIUM_EXECUTABLE',
    'static bool chromium_sandbox_candidate_probe(const char *path, int mode)',
    'static bool chromium_executable_owner_probe(const char *path)',
    'static bool chromium_executable_readlink(const char *path, char *buffer,',
    'getauxval(AT_EXECFN)',
    '#define T1OS_CHROMIUM_PROCESS_EXECUTABLE',
    '#define T1OS_CHROMIUM_NVIDIA_MAXIMUM_GPUS 16',
    'static int chromium_singleton_create(const char *target_path,',
    'static bool chromium_singleton_readlink(int directory, const char *path,',
    'static bool chromium_nvidia_graphics_node(const char *path)',
    'strcmp(path, "/dev/nvidiactl") == 0',
    'decimal_suffix(path + 11)',
    'T1OS_CHROMIUM_NVIDIA_CONTROL',
    'T1OS_CHROMIUM_NVIDIA_ROOT',
    'SYS_openat, AT_FDCWD, target,',
    '{ "/usr/lib/x86_64-linux-gnu/dri", "/the one/catalogue/graphics/drivers", true }',
    '{ "/usr/lib64/dri", "/the one/catalogue/graphics/drivers", true }',
    '{ "/usr/lib/dri", "/the one/catalogue/graphics/drivers", true }',
    'O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC',
    '!S_ISREG(status.st_mode)',
    'int __xstat(int version, const char *path, struct stat *status)',
    'int __xstat64(int version, const char *path, struct stat64 *status)',
    'int __fxstatat64(int version, int directory, const char *path,',
    'strcmp(path, "/proc/self/exe") == 0',
    'status->st_uid = getuid()',
    'errno = EPERM;'
)) {
    if (-not $chromiumProviderSourceText.Contains($requiredText)) {
        throw "Chromium path provider is missing persistent-program path virtualization: $requiredText"
    }
}
foreach ($forbiddenText in @(
    '/dev/nvidia-uvm',
    '/the one/drivers/nodes/nvidia-uvm',
    'T1OS_CHROMIUM_NVIDIA_BROKER',
    'chromium_start_nvidia_broker',
    'chromium_preserved_nvidia_open',
    't1os-nv-broker',
    't1os-cuda-thread-name',
    'SCM_RIGHTS',
    'strcmp(path, "/dev/nvidia-uvm-tools")',
    'strcmp(path, "/dev/nvidia-caps")'
)) {
    if ($chromiumProviderSourceText.Contains($forbiddenText)) {
        throw "Chromium path provider grants an over-broad NVIDIA mapping: $forbiddenText"
    }
}
$chromiumSubprocessSourceText = Get-Content -LiteralPath $chromiumSubprocessSource -Raw
foreach ($requiredText in @(
    '#define T1OS_CHROMIUM_BINARY',
    '#define T1OS_CHROMIUM_PATH_PROVIDER',
    '#define T1OS_CHROMIUM_LIBRARY_PATH_BASE',
    '#define T1OS_CHROMIUM_LIBRARY_PATH_NVIDIA',
    '#define T1OS_CHROMIUM_GPU_LIBRARY_VARIABLE',
    '#define T1OS_CHROMIUM_GPU_EGL_VENDOR_VARIABLE',
    '#define T1OS_CHROMIUM_GPU_EGL_EXTERNAL_VARIABLE',
    '#define T1OS_CHROMIUM_GPU_GBM_PATH_VARIABLE',
    '#define T1OS_CHROMIUM_GPU_GBM_BACKEND_VARIABLE',
    '#define T1OS_CHROMIUM_PROCESS_ROOT',
    '#define T1OS_CHROMIUM_ENGINE_ID 1000',
    '"/the one/catalogue/graphics/nvidia:"',
    '"/the one/catalogue/graphics"',
    'child_process_type(argc, argv)',
    'loader_environment_valid()',
    'unprivileged_identity_valid()',
    'parent_is_chromium(&parent_kind, &parent_rejection)',
    'getgroups(0, NULL) == 0',
    '"%s/%ld/cmdline"',
    'strcmp(type, "zygote") == 0',
    'strncmp(argument, "--type=", 7) == 0',
    '"--no-sandbox"',
    '"--disable-setuid-sandbox"',
    '"--disable-namespace-sandbox"',
    '"--disable-seccomp-filter-sandbox"',
    '"GLIBC_TUNABLES="',
    'getenv("SANDBOX_LD_PRELOAD")',
    'getenv("SANDBOX_LD_LIBRARY_PATH")',
    'getenv(T1OS_CHROMIUM_GPU_LIBRARY_VARIABLE)',
    'setenv("__EGL_VENDOR_LIBRARY_FILENAMES"',
    'setenv("GBM_BACKENDS_PATH"',
    'unsetenv(T1OS_CHROMIUM_GPU_EGL_VENDOR_VARIABLE)',
    'launch_id_valid(launch_id)',
    'setenv("LD_PRELOAD", path_provider, 1)',
    'setenv("LD_LIBRARY_PATH", library_path, 1)',
    'execve(T1OS_CHROMIUM_BINARY, argv, environ)'
)) {
    if (-not $chromiumSubprocessSourceText.Contains($requiredText)) {
        throw "Chromium subprocess bootstrap is missing its confinement behavior: $requiredText"
    }
}
foreach ($publicDriveRoot in @(
    '{ "/media", "/drives", true }',
    '{ "/mnt", "/drives", true }'
)) {
    if ($chromiumProviderSourceText.Contains($publicDriveRoot)) {
        throw "Chromium still exposes the old public drive backing root: $publicDriveRoot"
    }
}
foreach ($forbiddenAlias in @('RUNTIMEPROGRAM', 'RUNTIMECHROME', 'RUNTIMESANDBOX', '/.ephemeral/chromium-program')) {
    if ($chromiumServerText.Contains($forbiddenAlias)) {
        throw "Chromium still depends on the removed temporary program alias: $forbiddenAlias"
    }
}
foreach ($persistentLaunchNeedle in @(
    'CHROMEEXECUTABLE = PROGRAM + "/chrome"',
    'SANDBOXEXECUTABLE = "./chrome-sandbox"',
    'chrome_environment["T1OS_CHROMIUM_SANDBOX_DISCOVERY"] = "1"',
    'env=chrome_environment, cwd=PROGRAM'
)) {
    if (-not $chromiumServerText.Contains($persistentLaunchNeedle)) {
        throw "Chromium persistent launch is missing: $persistentLaunchNeedle"
    }
}
foreach ($forbiddenIdentityOverride in @('T1OS_CHROMIUM_EXECUTABLE', 'T1OS_CHROMIUM_LOGICAL_PROGRAM')) {
    if ($chromiumServerText.Contains($forbiddenIdentityOverride) -or
        ($forbiddenIdentityOverride -eq 'T1OS_CHROMIUM_LOGICAL_PROGRAM' -and
         $chromiumProviderSourceText.Contains($forbiddenIdentityOverride))) {
        throw "Chromium still uses the rejected executable identity override: $forbiddenIdentityOverride"
    }
}
if ($chromiumServerText.Contains('"--disable-gpu"')) {
    throw 'Chromium is still forced into software rendering.'
}
if ($chromiumServerText.Contains('"--disable-gpu-sandbox"')) {
    throw 'Chromium still carries the ineffective GPU sandbox switch.'
}
if ($chromiumServerText.Contains('"--start-maximized"')) {
    throw 'Chromium still lets its private X window override the T1OS client geometry.'
}
foreach ($forbiddenLogOwnershipNeedle in @(
    'os.makedirs(os.path.dirname(LOGFILE), exist_ok=True)',
    'mkdir(os.path.dirname(LOGFILE), 0o755)'
)) {
    if ($chromiumServerText.Contains($forbiddenLogOwnershipNeedle)) {
        throw "Chromium still attempts to own the GODDESS-managed log directory: $forbiddenLogOwnershipNeedle"
    }
}
foreach ($mediaIntegrationNeedle in @(
    'def chromedevicescale(',
    'WINDOW_FULLSCREEN_SET',
    'FULLSCREENCURSORDELAY = 2.0',
    'BACKINGMAXWIDTH = 3840',
    'BACKINGMAXHEIGHT = 2160',
    'def chromiumbackingsize(',
    'def outputtosourcepoint(',
    'WINDOW_BUFFER_ATTACH',
    'AcceleratedVideoDecodeLinuxGL',
    'LIBVA_DRIVERS_PATH',
    'latencyclass="interactive"',
    'AUDIOCHUNKBYTES = 480 * 2 * 2',
    'AUDIOSTREAMBUFFERSECONDS = 0.04',
    'AUDIOSTREAMPREBUFFERMS = 20',
    'def audiolatencymilliseconds(',
    'frames_per_second": 60'
)) {
    if (-not $chromiumServerText.Contains($mediaIntegrationNeedle)) {
        throw "Chromium media/window integration is missing: $mediaIntegrationNeedle"
    }
}
$chromiumInputBridgeSourceText = Get-Content -LiteralPath $chromiumInputBridgeSource -Raw
foreach ($fullscreenNeedle in @(
    '_NET_WM_STATE_FULLSCREEN',
    'window_is_fullscreen(',
    'printf("FULLSCREEN %d',
    '#define MAX_INPUT_BYTES (1024U * 1024U)',
    '#define MAX_COMMAND_BYTES (MAX_INPUT_BYTES * 2U + 2U)',
    'line = malloc(COMMAND_BUFFER_BYTES);',
    'while (fgets(line, (int)COMMAND_BUFFER_BYTES, stdin))'
)) {
    if (-not $chromiumInputBridgeSourceText.Contains($fullscreenNeedle)) {
        throw "Chromium X11 fullscreen bridge is missing: $fullscreenNeedle"
    }
}
foreach ($unboundedInputNeedle in @(
    'getline(&line',
    '#define MAX_INPUT_LINE'
)) {
    if ($chromiumInputBridgeSourceText.Contains($unboundedInputNeedle)) {
        throw "Chromium input bridge retains an inconsistent or unbounded command reader: $unboundedInputNeedle"
    }
}
$chromiumWindowManagerSourceText = Get-Content -LiteralPath $chromiumWindowManagerSource -Raw
foreach ($windowManagerNeedle in @(
    'SUBSTRUCTURE_REDIRECT_MASK',
    '_NET_WM_STATE_FULLSCREEN',
    'handle_configure(',
    'enter_fullscreen(',
    'leave_fullscreen(',
    'announce_fullscreen(',
    '"FULLSCREEN %d\n"',
    'XDamageCreate(',
    'queue_damage(',
    'flush_damage(',
    'XPending(display)',
    '"WINDOW %lu',
    'printf(',
    '"DAMAGE %d %d %u %u'
)) {
    if (-not $chromiumWindowManagerSourceText.Contains($windowManagerNeedle)) {
        throw "Chromium private X11 protocol bridge is missing: $windowManagerNeedle"
    }
}
$windowServerText = Get-Content -LiteralPath $windowServer -Raw
foreach ($cursorHandoffNeedle in @(
    'def cursorstartupsceneactive():',
    '"startup", "lockscreen", "desktop", "taskbar"',
    'if cursorstartupsceneactive():'
)) {
    if (-not $windowServerText.Contains($cursorHandoffNeedle)) {
        throw "WindowServer cannot release the cursor after a recovery-owner desktop handoff: $cursorHandoffNeedle"
    }
}
$expanseText = Get-Content -LiteralPath $expanseScript -Raw
foreach ($expanseCpuNeedle in @(
    'SURFACESTAGINGROOT = f"/.ephemeral/expanse/surfaces-{os.getpid()}"',
    'def commitcpusurface(staged, live, expected):',
    'tmpbuf = surfacestagingpath("taskbar")',
    'tmpbuf = surfacestagingpath("startmenu")',
    'tmpbuf = surfacestagingpath("volumebar")',
    'open(live, "r+b", buffering=0)',
    'os.chmod(output, 0o644)'
)) {
    if (-not $expanseText.Contains($expanseCpuNeedle)) {
        throw "Expanse cannot stage icons and CPU shell surfaces in its private runtime: $expanseCpuNeedle"
    }
}
if ($expanseText.Contains('tmpbuf = f"{realbuf}.tmp"')) {
    throw 'Expanse still tries to create staging files in the protected WindowServer buffer directory.'
}
foreach ($consoleGridNeedle in @(
    'GPUCOMMANDGRIDITEMLIMIT = 32768',
    'if kind == "console_grid":',
    "for phase in ('backgrounds', 'texts', 'overlays'):",
    '"console_grid_item_limit": GPUCOMMANDGRIDITEMLIMIT'
)) {
    if (-not $windowServerText.Contains($consoleGridNeedle)) {
        throw "WindowServer is missing packed Brick console drawing: $consoleGridNeedle"
    }
}
if (-not $windowServerText.Contains('from graphics.graphics import backendinfo, framebufferpresentationproof')) {
    throw 'WindowServer must import and use the framebuffer presentation proof for fallback login.'
}
foreach ($failureClassNeedle in @(
    'GPUDEVICEFAILUREEXIT = 70',
    'BACKENDINITFAILUREEXIT = 71',
    'sys.exit(BACKENDINITFAILUREEXIT)',
    'sys.exit(GPUDEVICEFAILUREEXIT)'
)) {
    if (-not $windowServerText.Contains($failureClassNeedle)) {
        throw "WindowServer does not distinguish backend initialization from GPU device loss: $failureClassNeedle"
    }
}
foreach ($directPresentationNeedle in @(
    'def setwindowexternalbuffer(',
    'def windowbufferrecttooutput(',
    '"buffer_source_width"',
    'CHROMIUMXWDBUFFER',
    'source_offset=int(win.get("buffer_offset", 0))',
    'elif op == "WINDOW_BUFFER_ATTACH"'
)) {
    if (-not $windowServerText.Contains($directPresentationNeedle)) {
        throw "WindowServer direct Chromium presentation is missing: $directPresentationNeedle"
    }
}
foreach ($gpuPresentationNeedle in @(
    'PRESENTATIONMAXINFLIGHT = 3',
    'def handlepresentationconfigure(state, descriptor):',
    'def handlepresentationframe(state, descriptor, fds):',
    'gpupresentationbuffercreate(descriptor, fds)',
    '"sync_mode": "glfinish-producer-consumer"',
    '"generation": generation',
    'def capturechromiumpresentation(win, stream, surface):',
    'def finishchromiumpresentations():',
    'consumer_release=drm-page-flip',
    'feedback_clock=drm-page-flip'
)) {
    if (-not $windowServerText.Contains($gpuPresentationNeedle)) {
        throw "WindowServer RGB GBM DMA-BUF presentation is missing: $gpuPresentationNeedle"
    }
}
foreach ($retiredPresentationNeedle in @(
    'gpupresentationstream',
    'eglStreamConsumer',
    'EGLStream'
)) {
    if ($windowServerText.Contains($retiredPresentationNeedle)) {
        throw "WindowServer retains the retired presentation transport: $retiredPresentationNeedle"
    }
}
if ($chromiumServerText.Contains('runtool("xrandr"')) {
    throw 'Chromium still attempts to shrink the fixed maximum-size Xvfb screen with xrandr.'
}
foreach ($forbiddenPerEventProcess in @(
    'xdotool(["mousemove"',
    'xdotool([verb, str(button)])',
    'xdotool(["click", str(button)])',
    'xdotool(["type"',
    'xdotool(["key"'
)) {
    if ($chromiumServerText.Contains($forbiddenPerEventProcess)) {
        throw "Chromium still starts a synchronous xdotool process per input event: $forbiddenPerEventProcess"
    }
}
foreach ($forbiddenSwitch in @(
    '"--no-sandbox"',
    '"--no-zygote"',
    '"--disable-gpu-sandbox"'
)) {
    if ($chromiumServerText.Contains($forbiddenSwitch)) {
        throw "Chromium security regression: forbidden launch switch $forbiddenSwitch"
    }
}
foreach ($subprocessNeedle in @(
    'SUBPROCESSEXECUTABLE = TOOLS + "/t1os-chrome-subprocess"',
    '"--browser-subprocess-path=" + SUBPROCESSEXECUTABLE',
    'NVIDIADIRECTVAAPIQUARANTINED = True',
    '"--disable-accelerated-video-decode"',
    'chrome_environment["SANDBOX_LD_PRELOAD"]',
    'chrome_environment["SANDBOX_LD_LIBRARY_PATH"]',
    'runtime_status.get("utility_runtime_ready")',
    'status["utility_provider"] or provider'
)) {
    if (-not $chromiumServerText.Contains($subprocessNeedle)) {
        throw "Chromium does not preserve its measured child environment: $subprocessNeedle"
    }
}
foreach ($requiredText in @(
    'def applydeviceaccess(self):',
    "stat.S_ISCHR(status.st_mode)",
    "self.applydeviceaccess()",
    'def reconcilevolumes(self, force=False):',
    'def partitionosreasons(path, sectorsize=512):',
    "WINDOWS_ROOT_NAMES = {'windows', 'winnt'}",
    "SUPPORTED_EXTERNAL_FILESYSTEMS = {'ntfs3', 'exfat', 'vfat'}",
    "Path(target).parent == VOLUMEBASE",
    'module_runtime_ready = (',
    'device policy mode kernel=',
    'driver policy {self.state}',
    'def parsemoduleparameters(commandline):',
    'def pcidisplayalias(alias):',
    'def firmwaregraphicsrecoveryrequested(',
    'BOOTIDPATH = Path(os.environ.get(',
    'A previous boot is never',
    'explicit command-line framebuffer graphics recovery',
    "mountoptions = b'uid=1000,gid=1000,dmask=0077,fmask=0177'",
    'module parameter verified {module}.{name}={actual}',
    'modprobe timed out after',
    "'RESET_GRAPHICS'",
    'SO_PEERCRED',
    'def parsegraphicsresetrequest(request, peer):',
    'RESET_GRAPHICS is restricted to PID 1 running as UID 0',
    'def boundedgraphicswrite(self, path, value, bdf, phase, timeout=None):',
    'pid = os.fork()',
    'Do not exec: the inherited DriverServer argv',
    'def validategraphicsownership(',
    "('state', Path(stateroot)),",
    "('control', Path(controlroot)),",
    'def resetgraphicsrequest(',
    'self.graphics_reset_lock.acquire(blocking=False)',
    "'unbind',",
    "'function-reset',",
    "'bind',",
    "'drivers_probe'",
    "'wait-drm',",
    'def orderedaliasmodules(alias, modules):',
    "['nvidia']",
    "['nouveau'] if 'nouveau' in ordered else []",
    "return 'nvidia_drm'",
    'def pcialiasbindings(',
    'def nvidiaaliasclaimed(bindings):',
    "if module == 'nouveau' and nvidiaclaimed:",
    "NVIDIADRMREQUIREDPARAMETERS = {",
    "'fbdev': '1',",
    "'modeset': '1',",
    'def nvidiafrontendmajor(path=NVIDIADEVICESPATH):',
    "'nvidia-frontend': []",
    "'nvidiactl': []",
    'current NVIDIA character-device registrations must contain',
    'NVIDIAUVMMINOR = 0',
    'def nvidiauvmmajor(path=NVIDIADEVICESPATH):',
    "match.group(2) == 'nvidia-uvm'",
    'NVIDIA UVM character-device registration must contain exactly ',
    "f'one nvidia-uvm entry: nvidia-uvm={registrations}'",
    'def nvidiagpuminors(root=NVIDIAGPUROOT, maximum=NVIDIAMAXIMUMGPUS):',
    'def ensurenvidiacharnode(',
    'def reconcilenvidianodes(',
    'def reconcilenvidiauvmnode(',
    "name = 'nvidia-uvm'",
    'def loadnvidiauvm(self, source=',
    "module = 'nvidia_uvm'",
    "['--use-blacklist', module]",
    'if nvidiaclaimed and nodesready:',
    'self.loadnvidiauvm(source=source)',
    'def nvidiaresetreadiness(self, bdf, wait=0.0):',
    'transient_unclaimed=True',
    "self.nvidia_node_state = 'reclaiming'",
    "'wait-nvidia-proc'",
    "'wait-nvidia-nodes'",
    "('nvidiactl', NVIDIACONTROLMINOR)",
    "('nvidia-modeset', NVIDIAMODESETMINOR)",
    'self.reconcilenvidianodes(wait=2.0)',
    "self.nvidia_node_state = 'failed'",
    "self.setstate('degraded')"
)) {
    if (-not $driverServerText.Contains($requiredText)) {
        throw "Driver Server is missing its authenticated graphics/NVIDIA contract: $requiredText"
    }
}
foreach ($forbiddenText in @(
    "return ['nouveau', 'nvidia']",
    'subprocess.run(["nvidia-modprobe"',
    "Path('/dev')",
    'Path("/dev")'
)) {
    if ($driverServerText.Contains($forbiddenText)) {
        throw "Driver Server regressed its NVIDIA preference or bounded node policy: $forbiddenText"
    }
}
if ($driverServerText.Contains('subprocess.DEVNULL')) {
    throw 'Driver Server module loading still depends on the forbidden /dev/null hierarchy.'
}
if (-not $goddessText.Contains('driverstatus.get("device_grants", [])) or "no devices"')) {
    throw 'GODDESS does not report applied Driver Server device grants.'
}

Write-Host 'Hardware desktop runtime contracts validation passed.'
