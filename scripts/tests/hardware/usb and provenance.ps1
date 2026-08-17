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
$audioRuntime = Get-Content -LiteralPath $audioRuntimeManifest -Raw |
    ConvertFrom-Json
$audioProtocol = $audioRuntime.runtime.media_decode_protocol
if (
    -not $audioProtocol -or
    [string]$audioProtocol.name -cne 'T1MD' -or
    [int]$audioProtocol.version -ne 1 -or
    [string]$audioProtocol.transport -cne 'AF_UNIX/SOCK_SEQPACKET'
) {
    throw 'The native audio runtime does not advertise the T1MD v1 transport.'
}
$bundleValidatorText = Get-Content -LiteralPath $bundleValidator -Raw
foreach ($requiredText in @(
    'TargetSizesGiB',
    'ntfsresize --force --no-progress-bar "$root_device"',
    'Its --expand option is a distinct',
    't1os-drive.ico',
    'autorun.inf',
    'at least two distinct target capacities'
)) {
    if (-not $bundleValidatorText.Contains($requiredText)) {
        throw "The hardware USB bundle validator is missing the multi-capacity contract: $requiredText"
    }
}
$flashScriptText = Get-Content -LiteralPath $flashScript -Raw
foreach ($requiredText in @(
    '-CommitPrefixBytes 1MB',
    'Resize-Partition',
    'Get-PartitionSupportedSize',
    'minimumTargetBytes',
    'Windows reports that this USB has no media',
    '[long]$_.Size -gt 0',
    "PartitionStyle -in @('RAW', 'GPT')",
    'Windows retained an empty GPT label after Clear-Disk',
    'The USB disk still contains partitions after Clear-Disk',
    'The USB disk did not reach an empty GPT state before T1OS partition creation',
    'function Invoke-T1OSMountvol',
    'function Dismount-T1OSMountedVolumes',
    'Removing mounted USB volume access path',
    "Invoke-T1OSMountvol ``",
    "-Action '/d'",
    'Locking the newly created USB volumes for the complete payload write',
    'The verified T1OS USB is available in Windows',
    'Exclusive payload-write ownership of the intended USB disk could not be verified',
    'FSCTL_ALLOW_EXTENDED_DASD_IO',
    '$errorCode -in @(1, 50, 87)',
    'Complete-partition DASD control is unnecessary for raw USB volume',
    '-AllowExtendedDASDIO',
    '$volumeLocks.Count -ne 3',
    '$volumeLocks[0]',
    '$volumeLocks[1]',
    '$volumeLocks[2]',
    '$recoveryVolumeStream',
    'FileStream owns these locked handles',
    '[byte[]]$commitPrefix = $null',
    'function Mount-T1OSRootForWindows',
    'Add-PartitionAccessPath',
    '-AssignDriveLetter',
    'Windows did not assign a drive letter to the verified T1OS root volume',
    'Finalizing and cleanly dismounting T1OS from',
    "windows_drive_icon -cne 'the one\resources\t1os-drive.ico'"
)) {
    if (-not $flashScriptText.Contains($requiredText)) {
        throw "The hardware USB flasher is missing the bundle-install contract: $requiredText"
    }
}
foreach ($forbiddenText in @(
    'function Restore-T1OSUsbDiskMedia',
    'function Invoke-T1OSPnpUtil',
    '-IsOffline $true',
    "-Action '/p'"
)) {
    if ($flashScriptText.Contains($forbiddenText)) {
        throw "The hardware USB flasher contains a forbidden whole-device ejection path: $forbiddenText"
    }
}

$windowsAccessibleMarker = 'The verified T1OS USB is available in Windows as'
if (([regex]::Matches($flashScriptText, [regex]::Escape($windowsAccessibleMarker))).Count -ne 2) {
    throw 'The hardware USB flasher must finish both write paths with the verified root available in Windows.'
}
$finalDismountMarker = 'Finalizing and cleanly dismounting T1OS from'
$searchOffset = 0
foreach ($pathName in @('bundle', 'raw-image')) {
    $dismountOffset = $flashScriptText.IndexOf($finalDismountMarker, $searchOffset)
    if ($dismountOffset -lt 0) {
        throw "The $pathName USB write path lacks its final clean dismount."
    }
    $availableOffset = $flashScriptText.IndexOf($windowsAccessibleMarker, $dismountOffset)
    if ($availableOffset -lt 0) {
        throw "The $pathName USB write path does not restore Windows access after its verified dismount."
    }
    $finalSection = $flashScriptText.Substring(
        $dismountOffset,
        $availableOffset - $dismountOffset
    )
    if (
        ([regex]::Matches($finalSection, 'Mount-T1OSRootForWindows')).Count -ne 1 -or
        ([regex]::Matches($finalSection, 'Update-HostStorageCache')).Count -ne 1
    ) {
        throw "The $pathName USB write path must refresh storage and remount the verified NTFS root after its clean flush."
    }
    $searchOffset = $availableOffset + $windowsAccessibleMarker.Length
}

$flashTokens = $null
$flashParseErrors = $null
$flashAst = [Management.Automation.Language.Parser]::ParseFile(
    $flashScript,
    [ref]$flashTokens,
    [ref]$flashParseErrors
)
if ($flashParseErrors.Count -gt 0) {
    throw "The hardware USB flasher does not parse: $($flashParseErrors[0].Message)"
}
$bundleWriterAst = $flashAst.Find(
    {
        param($node)
        $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq 'Write-T1OSBundleEntry'
    },
    $true
)
if (-not $bundleWriterAst) {
    throw 'The hardware USB flasher bundle writer function could not be isolated for testing.'
}
Invoke-Expression $bundleWriterAst.Extent.Text
$bundleVerifierAst = $flashAst.Find(
    {
        param($node)
        $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq 'Get-T1OSDiskRegionHash'
    },
    $true
)
if (-not $bundleVerifierAst) {
    throw 'The hardware USB flasher bundle verifier function could not be isolated for testing.'
}
Invoke-Expression $bundleVerifierAst.Extent.Text

$writerPayload = [byte[]]::new(5MB)
[Random]::new(305).NextBytes($writerPayload)
$writerExpectedHash = [Convert]::ToHexString(
    [Security.Cryptography.SHA256]::HashData($writerPayload)
).ToLowerInvariant()
$writerZip = [IO.MemoryStream]::new()
$writerCreateArchive = [IO.Compression.ZipArchive]::new(
    $writerZip,
    [IO.Compression.ZipArchiveMode]::Create,
    $true
)
$writerCreateEntry = $writerCreateArchive.CreateEntry(
    'root.ntfs.img',
    [IO.Compression.CompressionLevel]::NoCompression
)
$writerCreateStream = $writerCreateEntry.Open()
$writerCreateStream.Write($writerPayload, 0, $writerPayload.Length)
$writerCreateStream.Dispose()
$writerCreateArchive.Dispose()
$writerZip.Position = 0
$writerReadArchive = [IO.Compression.ZipArchive]::new(
    $writerZip,
    [IO.Compression.ZipArchiveMode]::Read,
    $true
)
$writerEntry = $writerReadArchive.GetEntry('root.ntfs.img')
$writerOffset = 4096
$writerTargetBytes = [byte[]]::new($writerPayload.Length + 8192)
$writerTarget = [IO.MemoryStream]::new($writerTargetBytes, $true)
try {
    $writerProgress = @(
        & {
            Write-T1OSBundleEntry `
                -Entry $writerEntry `
                -Target $writerTarget `
                -Offset $writerOffset `
                -ExpectedBytes $writerPayload.Length `
                -ExpectedHash $writerExpectedHash `
                -ProgressStart 0 `
                -ProgressSpan 10 `
                -CommitPrefixBytes 1MB
            Write-T1OSBundleEntry `
                -Entry $writerEntry `
                -Target $writerTarget `
                -Offset $writerOffset `
                -ExpectedBytes $writerPayload.Length `
                -ExpectedHash $writerExpectedHash `
                -ProgressStart 10 `
                -ProgressSpan 90 `
                -CommitPrefixBytes 1MB
        } 6>&1 | ForEach-Object { $_.ToString() }
    )
    $expectedWriterProgress = @(5..100 | Where-Object { $_ % 5 -eq 0 } | ForEach-Object {
        "Writing T1OS USB: $_%"
    })
    if (($writerProgress -join "`n") -cne ($expectedWriterProgress -join "`n")) {
        throw "Compact bundle write progress was not emitted once in exact 5% intervals: $($writerProgress -join ', ')"
    }

    $writerActual = [byte[]]::new($writerPayload.Length)
    $writerTarget.Position = $writerOffset
    $writerRead = 0
    while ($writerRead -lt $writerActual.Length) {
        $writerCount = $writerTarget.Read(
            $writerActual,
            $writerRead,
            $writerActual.Length - $writerRead
        )
        if ($writerCount -le 0) {
            throw 'The delayed-prefix bundle writer test target ended early.'
        }
        $writerRead += $writerCount
    }
    $writerActualHash = [Convert]::ToHexString(
        [Security.Cryptography.SHA256]::HashData($writerActual)
    ).ToLowerInvariant()
    if ($writerActualHash -cne $writerExpectedHash) {
        throw 'The delayed-prefix bundle writer did not reproduce the source payload exactly.'
    }

    $verifyFirst = @(
        & {
            Get-T1OSDiskRegionHash `
                -Stream $writerTarget `
                -Offset $writerOffset `
                -Bytes $writerPayload.Length `
                -ProgressStart 0 `
                -ProgressSpan 10
        } 6>&1
    )
    $verifySecond = @(
        & {
            Get-T1OSDiskRegionHash `
                -Stream $writerTarget `
                -Offset $writerOffset `
                -Bytes $writerPayload.Length `
                -ProgressStart 10 `
                -ProgressSpan 90
        } 6>&1
    )
    $verifyProgress = @(
        $verifyFirst[0..($verifyFirst.Count - 2)]
        $verifySecond[0..($verifySecond.Count - 2)]
    ) | ForEach-Object { $_.ToString() }
    $expectedVerifyProgress = @(5..100 | Where-Object { $_ % 5 -eq 0 } | ForEach-Object {
        "Verifying T1OS USB: $_%"
    })
    if (($verifyProgress -join "`n") -cne ($expectedVerifyProgress -join "`n")) {
        throw "Compact bundle verification progress was not emitted once in exact 5% intervals: $($verifyProgress -join ', ')"
    }
    if (
        [string]$verifyFirst[-1] -cne $writerExpectedHash -or
        [string]$verifySecond[-1] -cne $writerExpectedHash
    ) {
        throw 'The compact bundle progress regression test failed read-back hashing.'
    }
}
finally {
    $writerTarget.Dispose()
    $writerReadArchive.Dispose()
    $writerZip.Dispose()
}
Write-Host 'Delayed-prefix compact bundle writer and 5% progress validation passed.'

$kernelBuilderText = Get-Content -LiteralPath $kernelBuilder -Raw
foreach ($gspContract in @(
    '{ 0, tu102_gsp_load, &ad102_gsp, &r535_rm_ga102, "535.113.01" }',
    '{ 0, gh100_gsp_load, &gb202_gsp, &r570_rm_gb20x, "570.144" }',
    '"Nv%sFw"'
)) {
    if (-not $kernelBuilderText.Contains($gspContract)) {
        throw "The hardware kernel build does not enforce its Nouveau GSP selector contract: $gspContract"
    }
}
foreach ($nvidiaContract in @(
    "nvidiaVersion = '610.43.03'",
    "nvidia_module_set='nvidia nvidia-modeset nvidia-drm nvidia-uvm'",
    'nvidia_module_set_stamp="$nvidia_source/.t1os-kernel-module-set"',
    '[ "$(cat "$nvidia_module_set_stamp" 2>/dev/null || true)" != "$nvidia_module_set" ]',
    "NV_KERNEL_MODULES='nvidia nvidia-modeset nvidia-drm nvidia-uvm'",
    'modules_install',
    "find `"`$modules_work/lib/modules/`$kernel_release`" -type f -name 'nvidia-drm.ko*'",
    "find `"`$modules_work/lib/modules/`$kernel_release`" -type f -name 'nvidia-uvm.ko*'",
    "strings `"`$source/vmlinux`" | grep -Fx '/the one/drivers/nodes/nvidia-modeset'",
    "strings `"`$source/vmlinux`" | grep -Fx '/the one/drivers/nodes/dri/renderD'",
    "strings `"`$source/vmlinux`" | grep -Fx '/the one/drivers/processes/driver/nvidia'",
    "strings `"`$source/vmlinux`" | grep -Fx '/the one/build/windows/windowserver.py'",
    "strings `"`$source/vmlinux`" | grep -Fx '/the one/build/drivers/driverserver.py'",
    "strings `"`$source/vmlinux`" | grep -Fx '/the one/build'",
    "strings `"`$source/vmlinux`" | grep -Fx '/the one/software'",
    "strings `"`$source/vmlinux`" | grep -Fx '/the one/drivers/nodes/pts/ptmx'",
    'gv100_head_state',
    'gv100_head_rgpos',
    '.state = gv100_head_state,',
    '.rgpos = gv100_head_rgpos,'
)) {
    if (-not $kernelBuilderText.Contains($nvidiaContract)) {
        throw "The hardware kernel build is missing its NVIDIA display contract: $nvidiaContract"
    }
}

$graphicsKernelBuilderText = Get-Content -LiteralPath $graphicsKernelBuilder -Raw
foreach ($serviceIdentity in @(
    "strings `"`$source/vmlinux`" | grep -Fx '/the one/build/windows/windowserver.py'",
    "strings `"`$source/vmlinux`" | grep -Fx '/the one/build/drivers/driverserver.py'",
    "strings `"`$source/vmlinux`" | grep -Fx '/the one/build'",
    "strings `"`$source/vmlinux`" | grep -Fx '/the one/software'",
    "strings `"`$source/vmlinux`" | grep -Fx '/the one/drivers/nodes/pts/ptmx'"
)) {
    if (-not $graphicsKernelBuilderText.Contains($serviceIdentity)) {
        throw "The VM kernel build does not verify its embedded service identity: $serviceIdentity"
    }
}

$imageBuilderText = Get-Content -LiteralPath $imageBuilder -Raw
if (-not $imageBuilderText.Contains(
    't1os.quiet=1 nvidia_drm.modeset=1 nvidia_drm.fbdev=1 nouveau.config=NvGspFw=0'
)) {
    throw 'The signed hardware image command line does not enable the NVIDIA open KMS stack.'
}
$imageValidatorText = Get-Content -LiteralPath $imageValidator -Raw
$hardwareUsbWorkflowText = Get-Content -LiteralPath $hardwareUsbWorkflow -Raw
foreach ($requiredText in @(
    'losetup --find --show --read-only --partscan',
    'blockdev --getro "$loop"',
    '"$ntfs_checker" --check --quiet --require-t1os-root',
    '--expected-serial "${expected_roothealth_identity[0]}"',
    '--expected-journal-uuid "${expected_roothealth_identity[1]}"',
    '--expected-journal-record "${expected_roothealth_identity[2]}"',
    'image_hash_before_ntfs_check=',
    'image_hash_after_ntfs_check=',
    'python3 -B "$roothealth_report_validator" "$work/roothealth.json"',
    '--check-state EMPTY --expected-exit 0',
    '--expected-volume-serial "${expected_roothealth_identity[0]}"'
)) {
    if (-not $imageValidatorText.Contains($requiredText)) {
        throw "The hardware image validator does not prove the read-only T1OS NTFS health gate: $requiredText"
    }
}
if ([regex]::Matches($hardwareUsbWorkflowText, "'-Production'").Count -lt 2) {
    throw 'Normal and ArtifactsOnly hardware USB builds do not both request a production-clean image.'
}
foreach ($runtimeDriverRoot in @('nodes', 'state', 'control', 'processes')) {
    $runtimeExclude = "--exclude='/$runtimeDriverRoot/'"
    if (
        -not $imageBuilderText.Contains($runtimeExclude) -or
        -not $imageValidatorText.Contains($runtimeExclude)
    ) {
        throw "Hardware image provenance validation does not exclude the mounted DriverServer runtime root: $runtimeDriverRoot"
    }
}
$productionPreparerText = Get-Content -LiteralPath $productionPreparer -Raw
foreach ($requiredText in @(
    'chromium_profile="$chromium_settings/profile"',
    'chromium_config="$chromium_settings/config"',
    'chromium_font_cache="$chromium_settings/font-cache"',
    'chromium_legacy_settings="$settings_root/browser"',
    'rm -rf -- \
    "$chromium_settings" \
    "$chromium_legacy_settings"',
    'chown 1000:1000 "$directory"',
    '[ ! -e "$chromium_legacy_settings" ] && [ ! -L "$chromium_legacy_settings" ]',
    "[ `"`$(stat -c '%u:%g:%a' `"`$directory`")`" = '1000:1000:700' ]"
)) {
    if (-not $productionPreparerText.Contains($requiredText)) {
        throw "Production preparation does not scrub Chromium-owned state: $requiredText"
    }
}
foreach ($requiredText in @(
    'settings_stage="$one_root/.settings.production-new-$$"',
    'software_digest_before=$(tree_digest "$software_root")',
    'software_digest_after=$(tree_digest "$software_root")',
    'Replacing the complete settings namespace with production defaults',
    "'audio',",
    "'brick',",
    "'network',",
    "'terminfo',",
    'runtime_name in control nodes processes state',
    'expected_network_entries=''cacerts.pem network.txt '''
)) {
    if (-not $productionPreparerText.Contains($requiredText)) {
        throw "Production preparation does not reset or prove the complete settings/runtime inventory: $requiredText"
    }
}
foreach ($requiredText in @(
    "Name = 'reset storage.img to verified production defaults'",
    "Script = 'prepare prod build.ps1'",
    "'prepare prod build.ps1',",
    "Name = 'build the read-only roothealth'",
    "Script = 'build roothealth.ps1'",
    "Name = 'exercise the roothealth against corruption fixtures'",
    "Script = 'test roothealth.ps1'"
)) {
    if (-not $hardwareUsbWorkflowText.Contains($requiredText)) {
        throw "The hardware USB workflow does not production-clean storage.img before artifact creation: $requiredText"
    }
}
foreach ($requiredText in @(
    'production image settings inventory mismatch',
    'production image retained user/runtime network settings',
    'production image audio settings are not release defaults',
    'find "$work/root/.ephemeral"',
    'runtime_name in control nodes processes state'
)) {
    if (-not $imageValidatorText.Contains($requiredText)) {
        throw "Hardware image validation does not prove complete production settings hygiene: $requiredText"
    }
}
foreach ($requiredText in @(
    'chromium_profile="$chromium_settings/profile"',
    'chromium_legacy_cache="$chromium_settings/cache"',
    'test ! -e "$chromium_settings/instance.sock"',
    'expected_production=${23}',
    '[ "$expected_production" = True ]',
    'ntfs-3g "${loop}p3" "$work/root" -o ro,permissions,windows_names'
)) {
    if (
        -not $imageBuilderText.Contains($requiredText) -and
        -not $imageValidatorText.Contains($requiredText)
    ) {
        throw "Hardware image release validation is missing Chromium state hygiene: $requiredText"
    }
}
foreach ($requiredText in @(
    'chromium_source=${31}',
    'expected_chromium_source_sha256=$(source_tree_sha256 "$chromium_source")',
    'chromium_source_sha256 = $chromiumSourceHash',
    "'chromium_source_sha256': os.environ['T1OS_CHROMIUM_SOURCE_SHA256']"
)) {
    if (-not $imageBuilderText.Contains($requiredText)) {
        throw "Hardware image creation is missing Chromium runtime provenance: $requiredText"
    }
}
foreach ($requiredText in @(
    'expected_chromium_source_hash=${25}',
    'actual_chromium_source_hash=$(source_tree_sha256 "$chromium_source")',
    'manifest.chromium_source_sha256',
    'Final USB Chromium runtime provenance differs from current source'
)) {
    if (-not $imageValidatorText.Contains($requiredText)) {
        throw "Hardware image validation is missing Chromium runtime provenance: $requiredText"
    }
}

function Get-T1OSBashFunctionText {
    param(
        [Parameter(Mandatory)]
        [string]$ScriptText,

        [Parameter(Mandatory)]
        [string]$FunctionName
    )

    $pattern = (
        '(?ms)^' +
        [regex]::Escape($FunctionName) +
        '\(\) \{\r?\n.*?^\}\r?$'
    )
    $match = [regex]::Match($ScriptText, $pattern)
    if (-not $match.Success) {
        throw "Could not isolate Bash function for regression testing: $FunctionName"
    }
    return $match.Value.Replace("`r`n", "`n").TrimEnd("`r")
}

function Get-T1OSPythonHereDocumentText {
    param(
        [Parameter(Mandatory)]
        [string]$ScriptText,

        [Parameter(Mandatory)]
        [string]$Invocation
    )

    $pattern = (
        '(?ms)^[ \t]*' +
        [regex]::Escape($Invocation) +
        '\r?\n(?<body>.*?)^PY\r?$'
    )
    $matches = [regex]::Matches($ScriptText, $pattern)
    if ($matches.Count -ne 1) {
        throw "Could not isolate one Python here-document for regression testing: $Invocation"
    }
    return $matches[0].Groups['body'].Value.Replace("`r`n", "`n").Trim()
}

function Remove-T1OSExactTextOnce {
    param(
        [Parameter(Mandatory)]
        [string]$Text,

        [Parameter(Mandatory)]
        [string]$Fragment,

        [string]$Replacement = ''
    )

    $index = $Text.IndexOf($Fragment, [StringComparison]::Ordinal)
    if ($index -lt 0) {
        throw 'Production preparation debug rewrite reporting contract is missing.'
    }
    if (
        $Text.IndexOf(
            $Fragment,
            $index + $Fragment.Length,
            [StringComparison]::Ordinal
        ) -ge 0
    ) {
        throw 'Production preparation debug rewrite reporting contract is duplicated.'
    }
    return (
        $Text.Substring(0, $index) +
        $Replacement +
        $Text.Substring($index + $Fragment.Length)
    )
}

$builderProductionNormalizer = Get-T1OSBashFunctionText `
    -ScriptText $imageBuilderText `
    -FunctionName 'normalize_production_build_tree'
$validatorProductionNormalizer = Get-T1OSBashFunctionText `
    -ScriptText $imageValidatorText `
    -FunctionName 'normalize_production_build_tree'
if ($builderProductionNormalizer -cne $validatorProductionNormalizer) {
    throw 'Image creation and validation use different production provenance normalization.'
}
$builderProductionRewrite = Get-T1OSPythonHereDocumentText `
    -ScriptText $builderProductionNormalizer `
    -Invocation 'python3 - "$build_tree" <<''PY'''
$preparerProductionRewrite = Get-T1OSPythonHereDocumentText `
    -ScriptText $productionPreparerText `
    -Invocation 'python3 - "$build_root" <<''PY'''
$preparerProductionRewrite = Remove-T1OSExactTextOnce `
    -Text $preparerProductionRewrite `
    -Fragment "changed = []`n`n" `
    -Replacement "`n"
$preparerProductionRewrite = Remove-T1OSExactTextOnce `
    -Text $preparerProductionRewrite `
    -Fragment "        changed.append(os.path.relpath(file_path, build_root))`n"
$productionRewriteReporting = @'
if changed:
    for file_path in changed:
        print(f'disabled debugging in {file_path}')
else:
    print('debugging was already disabled.')
'@
$preparerProductionRewrite = (
    Remove-T1OSExactTextOnce `
        -Text $preparerProductionRewrite `
        -Fragment $productionRewriteReporting.Trim()
).Trim()
if ($builderProductionRewrite -cne $preparerProductionRewrite) {
    throw 'Production preparation and image provenance use different Python debug rewrite programs.'
}
foreach ($normalizationContract in @(
    'DEBUG[A-Z0-9_]*|_DEBUG_[A-Z0-9_]*',
    "pattern.sub(r'\1False\2', original)",
    "with open(file_path, 'r+', encoding='utf-8') as handle:",
    'handle.truncate()',
    'os.fsync(handle.fileno())'
)) {
    if (
        -not $builderProductionNormalizer.Contains($normalizationContract) -or
        -not $productionPreparerText.Contains($normalizationContract)
    ) {
        throw "Production preparation and provenance do not share their exact debug rewrite contract: $normalizationContract"
    }
}
foreach ($normalizationCall in @(
    @{
        Text = $imageBuilderText
        Required = 'normalize_production_build_tree "$expected_build" "$production"'
    },
    @{
        Text = $imageValidatorText
        Required = 'normalize_production_build_tree "$expected_build" "$expected_production"'
    }
)) {
    if (-not $normalizationCall.Text.Contains($normalizationCall.Required)) {
        throw "Production provenance normalization is not applied to the disposable expected build tree: $($normalizationCall.Required)"
    }
}

# Exercise the exact embedded normalizer. All generated fixtures live inside a
# guarded WSL-native /var/tmp directory: no T1OS test path or file is created on
# the Windows host. A changed CRLF file must acquire the same LF bytes as
# prepare-prod's Python text rewrite, an untouched CRLF file must retain its
# bytes, development mode must remain byte-exact, and the same rsync comparison
# used for image provenance must still reject unrelated drift.
$productionProvenanceCheck = @'
set -euo pipefail
umask 077

work=$(mktemp -d /var/tmp/t1os-production-provenance.XXXXXX)
case "$work" in
    /var/tmp/t1os-production-provenance.*) ;;
    *)
        echo "Unexpected production provenance fixture path: $work" >&2
        exit 1
        ;;
esac

cleanup() {
    case "${work:-}" in
        /var/tmp/t1os-production-provenance.*)
            if [ -d "$work" ] && [ ! -L "$work" ]; then
                rm -rf -- "$work"
            fi
            ;;
    esac
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

[ -d "$work" ]
[ ! -L "$work" ]
chmod 0700 -- "$work"

source_tree="$work/source"
production_numeric="$work/production-numeric"
production_boolean="$work/production-boolean"
development="$work/development"
clean_deployment="$work/clean-deployment"
changed_deployment="$work/changed-deployment"
mkdir -p -- "$source_tree"

python3 -B - "$source_tree" <<'PY'
from pathlib import Path
import sys

root = Path(sys.argv[1])
(root / 'flags.py').write_bytes(
    b'DEBUG = True\r\n'
    b'DEBUG_AUDIO = True # audio\r\n'
    b'_DEBUG_GPU_2 = True    # gpu\r\n'
    b' DEBUG2=True\r\n'
    b'debug = True\r\n'
    b'XDEBUG = True\r\n'
    b'DEBUG = True or False\r\n'
    b'DEBUG_MIXED = true\r\n'
    b'VALUE = 7\r\n'
)
(root / 'unchanged.py').write_bytes(
    b"VALUE = 'keeps CRLF'\r\nOTHER = 9\r\n"
)
PY

for destination in "$production_numeric" "$production_boolean" "$development"; do
    mkdir -p -- "$destination"
    cp -a -- "$source_tree"/. "$destination"/
done
'@
$productionProvenanceCheck += "`n$builderProductionNormalizer`n"
$productionProvenanceCheck += @'
normalize_production_build_tree "$production_numeric" 1
normalize_production_build_tree "$production_boolean" True
normalize_production_build_tree "$development" 0

python3 -B - \
    "$source_tree" \
    "$production_numeric" \
    "$production_boolean" \
    "$development" <<'PY'
from pathlib import Path
import sys

source, numeric, boolean, development = map(Path, sys.argv[1:])
debug_source = (
    b'DEBUG = True\r\n'
    b'DEBUG_AUDIO = True # audio\r\n'
    b'_DEBUG_GPU_2 = True    # gpu\r\n'
    b' DEBUG2=True\r\n'
    b'debug = True\r\n'
    b'XDEBUG = True\r\n'
    b'DEBUG = True or False\r\n'
    b'DEBUG_MIXED = true\r\n'
    b'VALUE = 7\r\n'
)
debug_expected = (
    b'DEBUG = False\n'
    b'DEBUG_AUDIO = False # audio\n'
    b'_DEBUG_GPU_2 = False    # gpu\n'
    b' DEBUG2=False\n'
    b'debug = True\n'
    b'XDEBUG = True\n'
    b'DEBUG = True or False\n'
    b'DEBUG_MIXED = true\n'
    b'VALUE = 7\n'
)
unchanged = b"VALUE = 'keeps CRLF'\r\nOTHER = 9\r\n"

for production in (numeric, boolean):
    if (production / 'flags.py').read_bytes() != debug_expected:
        raise SystemExit(
            'Production provenance did not mirror the anchored debug and newline rewrite.'
        )
    if (production / 'unchanged.py').read_bytes() != unchanged:
        raise SystemExit(
            'Production provenance rewrote an unchanged CRLF source file.'
        )

if (
    (source / 'flags.py').read_bytes() != debug_source
    or (source / 'unchanged.py').read_bytes() != unchanged
    or (development / 'flags.py').read_bytes() != debug_source
    or (development / 'unchanged.py').read_bytes() != unchanged
):
    raise SystemExit(
        'Production provenance mutated its source fixture or changed development-mode bytes.'
    )
PY

for deployment in "$clean_deployment" "$changed_deployment"; do
    mkdir -p -- "$deployment"
    cp -a -- "$production_numeric"/. "$deployment"/
done
python3 -B - "$changed_deployment/flags.py" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
payload = path.read_bytes()
changed = payload.replace(b'VALUE = 7', b'VALUE = 8')
if changed == payload:
    raise SystemExit('Production provenance change fixture was not modified.')
path.write_bytes(changed)
PY

clean_differences=$(
    rsync -r --checksum --delete --itemize-changes --dry-run -- \
        "$production_numeric"/ "$clean_deployment"/
)
if [ -n "$clean_differences" ]; then
    echo 'Production debug normalization did not produce an exact clean provenance comparison.' >&2
    exit 1
fi
changed_differences=$(
    rsync -r --checksum --delete --itemize-changes --dry-run -- \
        "$production_numeric"/ "$changed_deployment"/
)
if [ -z "$changed_differences" ] || \
        ! printf '%s\n' "$changed_differences" | grep -F 'flags.py' >/dev/null; then
    echo 'Production provenance failed to detect an unrelated code change.' >&2
    exit 1
fi
'@

$normalizedProductionProvenanceCheck = (
    $productionProvenanceCheck.Replace("`r", '') + "`n# end"
)
$normalizedProductionProvenanceCheck | wsl.exe -d Ubuntu --exec bash -s --
$productionProvenanceExitCode = $LASTEXITCODE
if ($productionProvenanceExitCode -ne 0) {
    throw "Production provenance normalizer regression validation failed (exit code $productionProvenanceExitCode)."
}
Write-Host 'Production-aware source provenance regression validation passed.'

Write-Host 'Hardware usb and provenance validation passed.'
