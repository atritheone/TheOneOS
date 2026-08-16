[CmdletBinding()]
param(
    [switch]$IncludeUsbImage
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Path $PSScriptRoot -Parent

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

$syntaxErrors = @()
Get-ChildItem -LiteralPath (Join-Path $projectRoot 'scripts') -Filter '*.ps1' | Where-Object {
    $_.Name -like '*hardware*' -or
    $_.Name -like '*roothealth*' -or
    $_.Name -eq 'build driver runtime.ps1' -or
    $_.Name -eq 'prepare prod build.ps1'
} | ForEach-Object {
    $tokens = $null
    $errors = $null
    [void][System.Management.Automation.Language.Parser]::ParseFile($_.FullName, [ref]$tokens, [ref]$errors)
    foreach ($error in $errors) {
        $syntaxErrors += "$($_.Name): $error"
    }
}
if ($syntaxErrors.Count) {
    throw ($syntaxErrors -join [Environment]::NewLine)
}

if (-not (Test-Path -LiteralPath $bootPolicyBuilder -PathType Leaf)) {
    throw "Required hardware build artifact not found: $bootPolicyBuilder"
}

foreach ($requiredFile in @($initScript, $angelContract, $initramfsBuilder, $ntfsCheckerBuilder, $ntfsCheckerTest, $ntfsChecker, $ntfsCheckerMetadata, $ntfsCheckerLicense, $ntfsCheckerSourceArchive, $ntfsCheckerProductPatch, $ntfsCheckerSecurityPatch, $ntfsCheckerVerdictPatch, $imageBuilder, $bundleBuilder, $bundleValidator, $imageValidator, $productionPreparer, $hardwareUsbWorkflow, $kernelBuilder, $graphicsKernelBuilder, $grubScript, $encryptedGrubScript, $grubTheme, $grubBackground, $kernelConfig, $kernelPolicy, $goddessScript, $inputServer, $kernel, $initramfs, $firmwareArchive, $firmwareManifest, $moduleArchive, $driverServer, $operationsScript, $moduleLoader, $driverPolicy, $desktopCompatibility, $compatibilityValidator, $driverRuntime, $networkServer, $wirelessEngine, $networkLoader, $networkCertificates, $graphicsCatalogue, $intelVaapi, $r600Vaapi, $nouveauVaapi, $virtioVaapi, $vmwgfxVaapi, $nouveauDrm, $nouveauVulkan, $vulkanLoader, $nvidiaEgl, $nvidiaGles, $nvidiaEglVendor, $nvidiaGbmBackend, $nvidiaPathProvider, $nvidiaPathProviderSource, $nvidiaRuntime, $nvidiaVaapi, $nvidiaCuda, $nvidiaNvcuvid, $nvidiaPtxjit, $gstreamerCore, $gstreamerBase, $gstreamerCodecParsers, $mediaDecodeService, $mediaDecodeWorker, $audioRuntimeManifest, $mediaDecodeServiceSource, $mediaDecodeWorkerSource, $mediaDecodeProtocolSource, $chromiumServer, $chromiumEngine, $chromiumSandbox, $chromiumLibc, $chromiumLibasound, $chromiumProvider, $chromiumProviderSource, $chromiumInputBridge, $chromiumInputBridgeSource, $chromiumWindowManager, $chromiumWindowManagerSource, $windowServer, $brickScript, $chromiumSubprocess, $chromiumSubprocessSource, $runtimePathContract)) {
    if (-not (Test-Path -LiteralPath $requiredFile -PathType Leaf)) {
        throw "Required hardware build artifact not found: $requiredFile"
    }
}
if (-not (Test-Path -LiteralPath $expanseScript -PathType Leaf)) {
    throw "Required hardware build artifact not found: $expanseScript"
}
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
    "strings `"`$source/vmlinux`" | grep -Fx '/the one/drivers/nodes/nvidia-uvm'",
    "strings `"`$source/vmlinux`" | grep -Fx '/the one/build/windows/windowserver.py'",
    "strings `"`$source/vmlinux`" | grep -Fx '/the one/build/drivers/driverserver.py'",
    "strings `"`$source/vmlinux`" | grep -Fx '/the one/build/brick/brick.py'",
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
    "strings `"`$source/vmlinux`" | grep -Fx '/the one/build/brick/brick.py'",
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
    'angel-failure.log',
    'roothealth.stderr',
    'roothealth.json',
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
    "python_management='/mnt/the one/software/python/.t1pip'",
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
    "grep -qx 'angel-recovery'",
    "grep -qx 'sbin/roothealth'",
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

$kernelPolicyText = Get-Content -LiteralPath $kernelPolicy -Raw
$rootPushText = Get-Content -LiteralPath $rootPushScript -Raw
$hardwareKernelPushText = Get-Content -LiteralPath $hardwareKernelPushScript -Raw
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
    'static bool t1os_external_volume_options(const void *data)',
    '"uid=1000,gid=1000,dmask=0077,fmask=0177"',
    't1os_external_volume_options(data)'
)) {
    if (-not $kernelPolicyText.Contains($externalMountPolicy)) {
        throw "T1OS LSM is missing the private uid-1000 removable-volume mount contract: $externalMountPolicy"
    }
}
foreach ($requiredText in @(
    '#define T1OS_WINDOWSERVER_SCRIPT     "/the one/build/windows/windowserver.py"',
    '#define T1OS_BRICK_SCRIPT            "/the one/build/brick/brick.py"',
    '#define T1OS_DRIVERSERVER_SCRIPT     "/the one/build/drivers/driverserver.py"',
    'static bool t1os_is_drm_render_node_path(const struct path *p)',
    'static bool t1os_is_chromium_device_node_path(const struct path *p)',
    'static bool t1os_is_nvidia_device_node_name(const char *path)',
    'static bool t1os_is_nvidia_decode_device_node_name(const char *path)',
    'static bool t1os_is_nvidia_uvm_device_node_name(const char *path)',
    'static bool t1os_is_console_device_node_name(const char *path)',
    'static bool t1os_is_console_multiplexer_name(const char *path)',
    'static bool t1os_is_brick_process(void)',
    'static bool t1os_is_nvidia_device_node_path(const struct path *p)',
    'static bool t1os_is_chromium_uvm_process(void)',
    'static bool t1os_kernel_devtmpfs_worker(void)',
    'static bool t1os_kernel_devtmpfs_dentry(const struct dentry *dentry)',
    'static bool t1os_kernel_devtmpfs_parent(const struct path *dir)',
    'strcmp(dentry->d_sb->s_type->name, "devtmpfs")',
    'if (t1os_kernel_devtmpfs_parent(dir))',
    'if ((S_ISCHR(mode) || S_ISBLK(mode)) &&',
    '!strcmp(relative, "modules")',
    '!strcmp(relative, "devices")',
    '!strcmp(relative, "driver/nvidia/gpus")',
    '!strncmp(relative, "driver/nvidia/gpus/", 19)',
    'static bool t1os_process_component_is_current(const char *value, size_t length)',
    'pid_t current_pid = task_pid_nr(current);',
    'return parsed == (unsigned long)current_pid;',
    't1os_process_component_is_current(relative, component_length)',
    'static const char prefix[] = "/the one/drivers/nodes/"',
    '!strcmp(name, "nvidiactl")',
    '!strcmp(name, "nvidia-modeset")',
    '!strcmp(name, "nvidia-uvm")',
    '"/the one/drivers/nodes/nvidia-uvm"',
    'if (strncmp(name, "nvidia", 6))',
    "return *digit == '\0';",
    'if (t1os_is_nvidia_device_node_name(path))',
    'if (t1os_is_console_device_node_name(path))',
    'return current->signal && READ_ONCE(current->signal->tty);',
    'S_ISCHR(mode) &&',
    't1os_is_nvidia_device_node_path(&p)',
    'static void t1os_log_denial(const char *operation, const char *path)',
    '"T1OS LSM: denied %s path=%s pid=%d comm=%s\n"',
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
    'static bool t1os_reign_time_output_create_allowed(const struct path *dir,',
    'static const char parent[] = "/the one/settings/time";',
    'static const char common[] = "common.txt";',
    'static const char atreyan[] = "atreyan.txt";',
    'if (t1os_reign_time_output_create_allowed(dir, dentry, mode))',
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
    'return -EACCES;',
    '#define T1OS_CHROMIUM_BINARY         "/the one/software/chromium/program/chrome"',
    '#define T1OS_CHROMIUM_SANDBOX        "/the one/software/chromium/program/chrome-sandbox"',
    '#define T1OS_MEDIA_DECODER_DAEMON    "/the one/software/audio/t1-media-decoderd"',
    '#define T1OS_FFMPEG_BINARY           "/the one/software/audio/ffmpeg"',
    '#define T1OS_FFPROBE_BINARY          "/the one/software/audio/ffprobe"',
    '!strcmp(path, T1OS_FFMPEG_BINARY)',
    '!strcmp(path, T1OS_FFPROBE_BINARY)',
    '"/the one/software",',
    '"/the one/catalogue",',
    'Script and interpreter exceptions apply only to execution.',
    'static bool t1os_is_media_decoder_daemon_process(void)',
    'static bool t1os_is_expanse_runtime_path(const char *path)',
    'static bool t1os_is_python_management_path(const char *path)',
    'return t1os_domain_is(T1OS_DOMAIN_EXPANSE);',
    'return t1os_domain_is(T1OS_DOMAIN_PYTHON_SERVICE);',
    '!strcmp(path, "/.ephemeral/media")',
    '!strncmp(path, "/.ephemeral/media/", 18)',
    't1os_is_video_client_process() ||',
    't1os_is_audioserver_process() ||',
    'static bool t1os_executable_path_matches(const char *path, const char *target)',
    'static const char unreachable[] = "(unreachable)"',
    'matched = t1os_executable_path_matches(name, target)',
    't1os_is_executable_process(T1OS_CHROMIUM_BINARY)',
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
        '(?ms)!strcmp\(relative, "driver/nvidia/gpus"\) \|\|\s*!strncmp\(relative, "driver/nvidia/gpus/", 19\)\)\s*return t1os_is_driverserver_process\(\);'
    )
) {
    throw 'The NVIDIA reconciliation procfs ACL is not limited to DriverServer and bounded graphics diagnostics.'
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
        '/* Render nodes expose command submission and decode',
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
    -not $nvidiaAclBody.Contains(
        't1os_is_nvidia_decode_device_node_name(path)'
    ) -or
    -not $nvidiaAclBody.Contains('t1os_is_video_client_process()') -or
    -not $nvidiaAclBody.Contains(
        't1os_is_executable_process(T1OS_CHROMIUM_BINARY)'
    ) -or
    -not $nvidiaAclBody.Contains(
        't1os_is_nvidia_uvm_device_node_name(path)'
    ) -or
    -not $nvidiaAclBody.Contains('t1os_is_chromium_uvm_process()') -or
    $nvidiaAclBody.Contains('t1os_is_driverserver_process()') -or
    $nvidiaAclBody.Contains('T1OS_CHROMIUM_SANDBOX')
) {
    throw 'The NVIDIA decode-node ACL is not narrowly scoped to measured video clients.'
}
if (-not [regex]::IsMatch(
    $nvidiaAclBody,
    '(?ms)t1os_is_nvidia_uvm_device_node_name\(path\)\s*&&\s*\(t1os_is_video_client_process\(\)\s*\|\|\s*t1os_is_chromium_uvm_process\(\)\)'
)) {
    throw 'The NVIDIA UVM node ACL is not limited to native video and measured Chromium GPU/zygote processes.'
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
    '(?ms)if \(!strcmp\(path, "/the one/drivers/nodes/null"\).*?if \(t1os_is_chromium_engine_process\(\) \|\|\s*t1os_is_media_decoder_daemon_process\(\)\)\s*return true;\s*return false;\s*\}'
)) {
    throw 'The harmless standard-device ACL does not include the measured native video service.'
}
if (
    -not [regex]::IsMatch(
        $kernelPolicyText,
        '(?ms)if \(!strcmp\(path, "/the one/drivers/nodes/zero"\).*?if \(t1os_is_chromium_engine_process\(\)\)\s*return true;\s*return false;\s*\}'
    ) -or
    [regex]::IsMatch(
        $kernelPolicyText,
        '(?ms)if \(!strcmp\(path, "/the one/drivers/nodes/zero"\).*?t1os_is_media_decoder_daemon_process\(\).*?return false;\s*\}'
    )
) {
    throw 'The native video service standard-device ACL is broader than the null node.'
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
    -not $execHookBody.Contains('T1OS_MODPROBE_BINARY')
) {
    throw 'T1OS LSM conflates protected-tree immutability with execution policy.'
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

$pythonCheck = @'
import ast
from pathlib import Path
import sys

project_root = Path(sys.argv[1])
for relative_path in (
    "source/build software/graphics/graphics.py",
    "source/build software/windows/windowserver.py",
    "source/build software/expanse/expanse.py",
    "source/build software/GODDESS/GODDESS.py",
    "source/build software/operations/operations.py",
    "source/build software/startup/startup.py",
    "source/build software/lock screen/lock screen.py",
    "source/boot/boot animation/boot animation.py",
    "source/build software/input/inputserver.py",
    "source/build software/audio/audioserver.py",
    "source/build software/drivers/driverserver.py",
    "source/build software/network/network.py",
    "source/build software/chromium/chromium.py",
):
    path = project_root / relative_path
    compile(path.read_text(encoding="utf-8"), str(path), "exec")

chromium_path = project_root / "source/build software/chromium/chromium.py"
chromium_tree = ast.parse(
    chromium_path.read_text(encoding="utf-8"),
    filename=str(chromium_path),
)
chromium_functions = {
    node.name: node
    for node in chromium_tree.body
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
}
for function_name in ("sendws", "enginecommand"):
    function = chromium_functions.get(function_name)
    if function is None:
        raise SystemExit(
            f"Chromium transport function is missing: {function_name}"
        )
    direct_sends = [
        node
        for node in ast.walk(function)
        if (
            isinstance(node, ast.Attribute)
            and node.attr in {"send", "sendall"}
        )
        or (
            isinstance(node, ast.Name)
            and node.id in {"send", "sendall"}
        )
    ]
    if direct_sends:
        lines = sorted(
            {
                int(getattr(node, "lineno", function.lineno))
                for node in direct_sends
            }
        )
        raise SystemExit(
            f"Chromium {function_name} bypasses JsonLineQueue with a direct "
            f"socket send at lines {lines}"
        )
'@
$pythonCheck | wsl.exe -d Ubuntu --exec python3 -B - $wslProjectRoot
if ($LASTEXITCODE -ne 0) {
    throw 'Hardware Python syntax validation failed.'
}

$wslPythonTest = ConvertTo-T1OSWslPath -Path (Join-Path $projectRoot 'scripts\test boot animation lifecycle.py')
& wsl.exe -d Ubuntu --exec python3 -B $wslPythonTest $wslProjectRoot
if ($LASTEXITCODE -ne 0) {
    throw 'Boot animation lifecycle validation failed.'
}

$wslPythonTest = ConvertTo-T1OSWslPath -Path (Join-Path $projectRoot 'scripts\test fatal screen lifecycle.py')
& wsl.exe -d Ubuntu --exec python3 -B $wslPythonTest $wslProjectRoot
if ($LASTEXITCODE -ne 0) {
    throw 'Fatal screen lifecycle validation failed.'
}

$wslPythonTest = ConvertTo-T1OSWslPath -Path (Join-Path $projectRoot 'scripts\test power lifecycle.py')
& wsl.exe -d Ubuntu --exec python3 -B $wslPythonTest $wslProjectRoot
if ($LASTEXITCODE -ne 0) {
    throw 'Power lifecycle validation failed.'
}

$wslPythonTest = ConvertTo-T1OSWslPath -Path (Join-Path $projectRoot 'scripts\test chromium media decode service.py')
& wsl.exe -d Ubuntu --exec python3 -B $wslPythonTest
if ($LASTEXITCODE -ne 0) {
    throw 'Chromium T1MD media decode service validation failed.'
}

$wslPythonTest = ConvertTo-T1OSWslPath -Path (Join-Path $projectRoot 'scripts\test video compatibility.py')
& wsl.exe -d Ubuntu --exec python3 -B $wslPythonTest
if ($LASTEXITCODE -ne 0) {
    throw 'Video compatibility validation failed.'
}

& pwsh -NoLogo -NoProfile -NonInteractive -File (Join-Path $PSScriptRoot 'test chromium xwm.ps1')
if ($LASTEXITCODE -ne 0) {
    throw 'Chromium X11 protocol bridge validation failed.'
}

& pwsh -NoLogo -NoProfile -NonInteractive -File (Join-Path $PSScriptRoot 'test chromium fonts.ps1')
if ($LASTEXITCODE -ne 0) {
    throw 'Chromium font configuration validation failed.'
}

$wslPythonTest = ConvertTo-T1OSWslPath -Path (Join-Path $projectRoot 'scripts\test kms presentation.py')
& wsl.exe -d Ubuntu --exec python3 -B $wslPythonTest $wslProjectRoot
if ($LASTEXITCODE -ne 0) {
    throw 'Event-driven KMS presentation validation failed.'
}

$networkInitializationCheck = @'
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import types

project_root = Path(sys.argv[1])
network_path = project_root / "source/build software/network/network.py"

pyroute2 = types.ModuleType("pyroute2")
pyroute2.IPRoute = object
sys.modules["pyroute2"] = pyroute2

reign_package = types.ModuleType("reign")
reign_module = types.ModuleType("reign.reign")
reign_module.timestamp = lambda: "test"
reign_module.formatlog = lambda software, message, epoch=None: f"[{software}] {message}"
sys.modules["reign"] = reign_package
sys.modules["reign.reign"] = reign_module

goddess_package = types.ModuleType("GODDESS")
goddess_module = types.ModuleType("GODDESS.GODDESS")
goddess_module.formatlog = reign_module.formatlog
goddess_module.popenisolated = lambda *args, **kwargs: None
sys.modules["GODDESS"] = goddess_package
sys.modules["GODDESS.GODDESS"] = goddess_module

operations_package = types.ModuleType("operations")
operations_module = types.ModuleType("operations.operations")
operations_module.service_secret_get = lambda *_args, **_kwargs: None
sys.modules["operations"] = operations_package
sys.modules["operations.operations"] = operations_module

spec = importlib.util.spec_from_file_location("t1os_network_test", network_path)
network = importlib.util.module_from_spec(spec)
spec.loader.exec_module(network)
network.ensurehostfirewall = lambda: True

with tempfile.TemporaryDirectory() as temporary:
    network.NETDIR = temporary
    network.DNSCONF = os.path.join(temporary, "dns.txt")
    network.LOGFILE = os.path.join(temporary, "network.log")
    if not network.configuredns(["10.0.2.3", "invalid", "10.0.2.3", "1.1.1.1"]):
        raise SystemExit("DHCP DNS persistence rejected valid nameservers")
    expected_dns = (
        "nameserver 10.0.2.3\n"
        "nameserver 1.1.1.1\n"
        "options timeout:2 attempts:3\n"
    )
    actual_dns = Path(network.DNSCONF).read_text(encoding="utf-8")
    if actual_dns != expected_dns:
        raise SystemExit(f"DHCP DNS persistence regression: {actual_dns!r}")

    original_control = network.wirelesscontrolcommand
    network.wirelesscontrolcommand = lambda _iface, _command, timeout=2: (
        "wpa_state=COMPLETED\nssid=MyHomeWiFi-AX\n"
    )
    try:
        if network.connectedwirelessname("wlan0") != "MyHomeWiFi-AX":
            raise SystemExit("associated Wi-Fi name capitalization was not preserved")
    finally:
        network.wirelesscontrolcommand = original_control

    ethernet_id = network.ethernetconnectionid(
        "eth0", "192.168.1.1", "192.168.1.1", "d8:43:ae:53:56:ca"
    )
    if ethernet_id != network.ethernetconnectionid(
        "eth0", "192.168.1.1", "192.168.1.1", "d8:43:ae:53:56:ca"
    ):
        raise SystemExit("Ethernet connection identity was not stable")
    if ethernet_id == network.ethernetconnectionid(
        "eth0", "10.0.2.2", "10.0.2.2", "d8:43:ae:53:56:ca"
    ):
        raise SystemExit("distinct Ethernet connections received the same identity")

    virtualbox_dns = network.dnsserversforlease(
        "10.0.2.2", ["103.86.96.100"], isvirtualbox=True
    )
    if virtualbox_dns != ["10.0.2.3", "103.86.96.100"]:
        raise SystemExit(f"VirtualBox NAT DNS proxy regression: {virtualbox_dns!r}")

request = network.dhcprequestpacket(
    "d8:43:ae:53:56:ca", 0x12345678, "192.168.1.102", "192.168.1.1"
)
request_options = network.parsedhcpoptions(request)
if len(request) < 300:
    raise SystemExit(f"DHCPREQUEST is below the BOOTP minimum: {len(request)}")
if request[4:8] != bytes.fromhex("12345678"):
    raise SystemExit("DHCPREQUEST transaction identifier regression")
if request_options.get(53) != b"\x03":
    raise SystemExit("DHCPREQUEST message type regression")
if request_options.get(50) != bytes((192, 168, 1, 102)):
    raise SystemExit("DHCPREQUEST requested-address regression")
if request_options.get(54) != bytes((192, 168, 1, 1)):
    raise SystemExit("DHCPREQUEST server-identifier regression")
if request_options.get(61) != b"\x01" + bytes.fromhex("d843ae5356ca"):
    raise SystemExit("DHCPREQUEST did not preserve the DHCP client identifier")
if request_options.get(57) != bytes((2, 64)):
    raise SystemExit("DHCPREQUEST maximum-message-size regression")
if request_options.get(55) != bytes((1, 3, 6, 15, 28, 51, 58, 59)):
    raise SystemExit("DHCPREQUEST parameter request list regression")

ack = bytearray(network.dhcpbasepacket("d8:43:ae:53:56:ca", 0x12345678))
ack[0] = 2
ack.extend(b"\x35\x01\x05\xff")
ack = network.padbootp(bytes(ack))
socket_events = []

class FakeRoute:
    def link_lookup(self, ifname):
        socket_events.append(("lookup", ifname))
        return [2]

    def route(self, operation, **values):
        socket_events.append(("route", operation, values))

    def close(self):
        socket_events.append(("route-close",))

class FakeSocket:
    def setsockopt(self, *values):
        socket_events.append(("setsockopt",) + values)

    def bind(self, address):
        socket_events.append(("bind", address))

    def settimeout(self, value):
        socket_events.append(("timeout", value))

    def sendto(self, packet, address):
        socket_events.append(("send", packet, address))
        return len(packet)

    def recvfrom(self, _size):
        return ack, ("192.168.1.1", 67)

    def close(self):
        socket_events.append(("socket-close",))

original_socket = network.socket.socket
original_route = network.IPRoute
original_log = network.log
original_bind_to_device = getattr(network.socket, "SO_BINDTODEVICE", None)
try:
    network.socket.socket = lambda *_args, **_values: FakeSocket()
    network.socket.SO_BINDTODEVICE = 25
    network.IPRoute = FakeRoute
    network.dhcppacketlistener = lambda _iface: None
    network.log = lambda message: socket_events.append(("log", message))
    if not network.dhcprequest(
        "eth0", "d8:43:ae:53:56:ca", 0x12345678,
        "192.168.1.102", "192.168.1.1"
    ):
        raise SystemExit(f"DHCPREQUEST rejected a matching DHCPACK: {socket_events!r}")
finally:
    network.socket.socket = original_socket
    if original_bind_to_device is None:
        del network.socket.SO_BINDTODEVICE
    else:
        network.socket.SO_BINDTODEVICE = original_bind_to_device
    network.IPRoute = original_route
    network.log = original_log

sent = [event for event in socket_events if event[0] == "send"]
if len(sent) != 1 or len(sent[0][1]) < 300:
    raise SystemExit("DHCPREQUEST transaction did not send one padded packet")
if not any(event[:2] == ("route", "replace") for event in socket_events):
    raise SystemExit("DHCPREQUEST transaction did not install a link broadcast route")

ethernet = bytes.fromhex("ffffffffffffd843ae5356ca0800")
ipv4 = bytearray(20)
ipv4[0] = 0x45
ipv4[9] = 17
ipv4[12:16] = bytes((192, 168, 1, 1))
ipv4[16:20] = bytes((192, 168, 1, 102))
udp = bytearray(8)
udp[0:2] = (67).to_bytes(2, "big")
udp[2:4] = (68).to_bytes(2, "big")
udp[4:6] = (8 + len(ack)).to_bytes(2, "big")
payload, peer = network.dhcpframepayload(ethernet + ipv4 + udp + ack)
if payload != ack or peer != ("192.168.1.1", 67):
    raise SystemExit("DHCP link-layer unicast ACK extraction regression")

network.NETDIR = "/the one/settings/network"
network.DNSCONF = "/the one/settings/network/dns.txt"
network.LOGFILE = os.devnull

events = []
link_up = False

def inventory():
    return [{
        "name": "eth0",
        "index": 2,
        "carrier": link_up,
        "operstate": "UP" if link_up else "DOWN",
        "up": link_up,
        "wireless": False,
        "mac": "08:00:27:81:ba:ca",
    }]

def bring_up(iface):
    global link_up
    events.append(("up", iface))
    link_up = True
    return "08:00:27:81:ba:ca"

network.linkinventory = inventory
network.upinterface = bring_up
network.configdhcp = lambda iface: events.append(("dhcp", iface))
network.time.sleep = lambda _seconds: None
network.os.path.exists = lambda _path: False
network.main()

expected = [("up", "eth0"), ("dhcp", "eth0")]
if events != expected:
    raise SystemExit(
        f"wired initialization regression: expected {expected!r}, got {events!r}"
    )

# The wired selector must never mistake an associated Wi-Fi interface for
# Ethernet, even if the Wi-Fi driver reports carrier and operstate UP.
network.linkinventory = lambda: [{
    "name": "wlan0",
    "index": 3,
    "carrier": True,
    "operstate": "UP",
    "up": True,
    "wireless": True,
    "mac": "e4:c7:67:9a:2e:9b",
}]
if network.detectinterface() is not None:
    raise SystemExit("wireless interface was accepted by the wired-only selector")

# With no carrier-ready Ethernet, configured Wi-Fi association starts
# immediately instead of waiting through the Ethernet settling interval.
events.clear()
wireless = {
    "name": "wlan0",
    "index": 3,
    "carrier": False,
    "operstate": "DOWN",
    "up": True,
    "wireless": True,
    "mac": "e4:c7:67:9a:2e:9b",
}
network.linkinventory = lambda: [wireless]
network.activatewirelessinterfaces = lambda _links: []
network.configuredwirelesslinks = lambda _links: [wireless]

def associate(iface):
    events.append(("associate", iface))
    wireless["carrier"] = True
    wireless["operstate"] = "UP"
    return True

network.ensurewireless = associate
network.waitforwirelessready = lambda iface: events.append(("late-wait", iface)) or True
network.detectinterface = lambda allowwireless=False: None
network.main()
expected = [
    ("associate", "wlan0"),
    ("dhcp", "wlan0"),
]
if events != expected:
    raise SystemExit(
        f"Wi-Fi fallback regression: expected {expected!r}, got {events!r}"
    )

# A Settings reconfiguration request must reapply an already-connected Wi-Fi
# interface instead of publishing a false disconnected state.
events.clear()
network.loadjson = lambda _path, _default=None: {
    "connected": True,
    "interface": "wlan0",
}
network.main(force=True)
expected = [
    ("associate", "wlan0"),
    ("dhcp", "wlan0"),
]
if events != expected:
    raise SystemExit(
        f"Wi-Fi reconfiguration regression: expected {expected!r}, got {events!r}"
    )
network.loadjson = lambda _path, default=None: {} if default is None else default

# If both links are ready, Ethernet must pre-empt Wi-Fi.
events.clear()
ethernet_ready = {
    "name": "eth0",
    "index": 2,
    "carrier": True,
    "operstate": "UP",
    "up": True,
    "wireless": False,
    "mac": "d8:43:ae:53:56:ca",
}
wireless_ready = dict(wireless, carrier=True, operstate="UP")
network.linkinventory = lambda: [wireless_ready, ethernet_ready]
network.main()
if events != [("dhcp", "eth0")]:
    raise SystemExit(
        f"Ethernet priority regression: expected DHCP on eth0, got {events!r}"
    )

# Ethernet carrier may disappear briefly when the interface is brought up.
# Verify that main keeps retrying the wired NIC and eventually runs DHCP on it.
events.clear()
inventory_calls = 0

def settling_inventory():
    global inventory_calls
    inventory_calls += 1
    carrier = inventory_calls >= 5
    return [{
        "name": "eth0",
        "index": 2,
        "carrier": carrier,
        "operstate": "UP" if carrier else "DOWN",
        "up": inventory_calls > 1,
        "wireless": False,
        "mac": "d8:43:ae:53:56:ca",
    }]

network.linkinventory = settling_inventory
network.upinterface = lambda iface: events.append(("up", iface)) or "d8:43:ae:53:56:ca"
network.configdhcp = lambda iface: events.append(("dhcp", iface))
network.configuredwirelesslinks = lambda _links: []
network.detectinterface = lambda allowwireless=False: next(
    (
        link["name"] for link in settling_inventory()
        if not link["wireless"] and network.linkready(link)
    ),
    None,
)
network.main()

expected = [("up", "eth0"), ("dhcp", "eth0")]
if events != expected or inventory_calls < 5:
    raise SystemExit(
        f"wired carrier settle regression: expected {expected!r}, "
        f"got {events!r} after {inventory_calls} inventories"
    )
'@
$networkInitializationCheck | wsl.exe -d Ubuntu --exec python3 -B - $wslProjectRoot
if ($LASTEXITCODE -ne 0) {
    throw 'T1OS wired network initialization validation failed.'
}

$buildSoftwareRoot = Join-Path $projectRoot 'source\build software'
$wslDriverServer = (
    & wsl.exe -d Ubuntu --exec wslpath -a $driverServer |
        Select-Object -First 1
).Trim()
$wslBuildSoftwareRoot = (
    & wsl.exe -d Ubuntu --exec wslpath -a $buildSoftwareRoot |
        Select-Object -First 1
).Trim()
$driverDiagnosticOutput = & wsl.exe -d Ubuntu --exec env "PYTHONPATH=$wslBuildSoftwareRoot" python3 $wslDriverServer --diagnostic
$driverDiagnosticExitCode = $LASTEXITCODE
if ($driverDiagnosticExitCode -ne 0) {
    throw "T1OS Driver Server diagnostic failed (exit code $driverDiagnosticExitCode)."
}
$driverDiagnosticJson = $driverDiagnosticOutput |
    Where-Object { $_ -match '^\s*\{.*\}\s*$' } |
    Select-Object -Last 1
if (-not $driverDiagnosticJson) {
    throw 'T1OS Driver Server diagnostic did not emit its JSON result.'
}
try {
    $driverDiagnosticResult = $driverDiagnosticJson | ConvertFrom-Json
}
catch {
    throw "T1OS Driver Server diagnostic emitted invalid JSON: $driverDiagnosticJson"
}
if ($driverDiagnosticResult.passed -ne $true) {
    throw 'T1OS Driver Server diagnostic did not report passed=true.'
}
foreach ($check in @(
    'nvidia_uvm_device_registration',
    'nvidia_uvm_module_load_order',
    'nvidia_uvm_primary_node'
)) {
    if ($driverDiagnosticResult.checks.$check -ne $true) {
        throw "T1OS Driver Server diagnostic did not pass its UVM check: $check"
    }
}

$wslInit = (& wsl.exe -d Ubuntu --exec wslpath -a $initScript | Select-Object -First 1).Trim()
$wslInitramfs = (& wsl.exe -d Ubuntu --exec wslpath -a $initramfs | Select-Object -First 1).Trim()
$wslModules = (& wsl.exe -d Ubuntu --exec wslpath -a $moduleArchive | Select-Object -First 1).Trim()
$wslFirmware = (& wsl.exe -d Ubuntu --exec wslpath -a $firmwareArchive | Select-Object -First 1).Trim()
$wslModuleLoader = (& wsl.exe -d Ubuntu --exec wslpath -a $moduleLoader | Select-Object -First 1).Trim()
$wslWirelessEngine = (& wsl.exe -d Ubuntu --exec wslpath -a $wirelessEngine | Select-Object -First 1).Trim()
$wslNetworkLoader = (& wsl.exe -d Ubuntu --exec wslpath -a $networkLoader | Select-Object -First 1).Trim()
$wslNetworkCatalogue = (& wsl.exe -d Ubuntu --exec wslpath -a (Split-Path -Path $networkLoader -Parent) | Select-Object -First 1).Trim()
$wslChromiumEngine = (& wsl.exe -d Ubuntu --exec wslpath -a $chromiumEngine | Select-Object -First 1).Trim()
$wslChromiumSandbox = (& wsl.exe -d Ubuntu --exec wslpath -a $chromiumSandbox | Select-Object -First 1).Trim()
$wslChromiumLibc = (& wsl.exe -d Ubuntu --exec wslpath -a $chromiumLibc | Select-Object -First 1).Trim()
$wslChromiumLibasound = (& wsl.exe -d Ubuntu --exec wslpath -a $chromiumLibasound | Select-Object -First 1).Trim()
$wslChromiumProvider = (& wsl.exe -d Ubuntu --exec wslpath -a $chromiumProvider | Select-Object -First 1).Trim()
$wslChromiumInputBridge = (& wsl.exe -d Ubuntu --exec wslpath -a $chromiumInputBridge | Select-Object -First 1).Trim()
$wslChromiumSubprocess = (& wsl.exe -d Ubuntu --exec wslpath -a $chromiumSubprocess | Select-Object -First 1).Trim()
$wslNvidiaPathProvider = (& wsl.exe -d Ubuntu --exec wslpath -a $nvidiaPathProvider | Select-Object -First 1).Trim()
$wslNvidiaVaapi = (& wsl.exe -d Ubuntu --exec wslpath -a $nvidiaVaapi | Select-Object -First 1).Trim()
$wslMediaDecodeService = (& wsl.exe -d Ubuntu --exec wslpath -a $mediaDecodeService | Select-Object -First 1).Trim()
$wslMediaDecodeWorker = (& wsl.exe -d Ubuntu --exec wslpath -a $mediaDecodeWorker | Select-Object -First 1).Trim()

$linuxCheck = @'
set -euo pipefail
trap 'status=$?; printf "Linux artifact check failed at line %s (exit %s): %s\n" "$LINENO" "$status" "$BASH_COMMAND" >&2' ERR
init=$1
initramfs=$2
modules=$3
module_loader=$4
wireless_engine=$5
network_loader=$6
network_catalogue=$7
chromium_engine=$8
chromium_provider=$9
chromium_sandbox=${10}
chromium_libc=${11}
chromium_input_bridge=${12}
chromium_libasound=${13}
chromium_subprocess=${14}
nvidia_path_provider=${15}
nvidia_vaapi=${16}
firmware=${17}
media_decode_service=${18}
media_decode_worker=${19}
expected_python_release=${20}
module_work=/var/tmp/t1os-module-validate
shellcheck -s sh "$init"

offset=$(python3 - "$initramfs" <<'PY'
from pathlib import Path
import sys
data = Path(sys.argv[1]).read_bytes()
magic = b'\x1f\x8b\x08'
offset = next(
    (
        position
        for position in range(0, len(data) - len(magic) + 1, 512)
        if data[position:position + len(magic)] == magic
    ),
    -1,
)
if offset < 0:
    raise SystemExit('512-byte-aligned gzip member not found in initramfs')
print(offset)
PY
)
early_listing=$(cpio --numeric-uid-gid -tv < "$initramfs" 2>/dev/null)
main_listing=$(
    dd if="$initramfs" skip="$offset" iflag=skip_bytes status=none |
        gzip -cd |
        cpio --numeric-uid-gid -tv 2>/dev/null
)
validate_archive_modes() {
    archive_kind=$1
    awk -v archive_kind="$archive_kind" '
        {
            mode=$1
            uid=$3
            gid=$4
            path=$NF
            expected=""
            if (uid != "0" || gid != "0") bad=1
            if (substr(mode, 1, 1) == "d") {
                expected="drwxr-xr-x"
            } else if (substr(mode, 1, 1) == "-") {
                expected="-rw-r--r--"
                if (archive_kind == "main" && (path == "protected-roots.tsv" || path == "profiled-python-entrypoints.tsv")) {
                    expected="-r--r--r--"
                } else if (archive_kind == "main" && (path == "init" || path == "angel-recovery" || path ~ /^(bin|sbin)\// || path ~ /(^|\/)ld-linux[^\/]*$/)) {
                    expected="-rwxr-xr-x"
                }
            } else {
                bad=1
            }
            if (expected != "" && mode != expected) bad=1
        }
        END { exit bad ? 1 : 0 }
    '
}
printf '%s\n' "$early_listing" | validate_archive_modes early
printf '%s\n' "$main_listing" | validate_archive_modes main
test "$(
    dd if="$initramfs" skip="$offset" iflag=skip_bytes status=none |
        gzip -cd |
        cpio -i --to-stdout init 2>/dev/null |
        sha256sum | awk '{print $1}'
)" = "$(sha256sum "$init" | awk '{print $1}')"
dd if="$initramfs" skip="$offset" iflag=skip_bytes status=none | gzip -cd | cpio -it 2>/dev/null | grep -qx 'sbin/cryptsetup'
dd if="$initramfs" skip="$offset" iflag=skip_bytes status=none | gzip -cd | cpio -it 2>/dev/null | grep -qx 'sbin/roothealth'
dd if="$initramfs" skip="$offset" iflag=skip_bytes status=none | gzip -cd | cpio -it 2>/dev/null | grep -qx 'lib64/ld-linux-x86-64.so.2'
dd if="$initramfs" skip="$offset" iflag=skip_bytes status=none | gzip -cd | cpio -it 2>/dev/null | grep -qx 'bin/sh'
dd if="$initramfs" skip="$offset" iflag=skip_bytes status=none | gzip -cd | cpio -it 2>/dev/null | grep -qx 'bin/mdev'
dd if="$initramfs" skip="$offset" iflag=skip_bytes status=none | gzip -cd | cpio -it 2>/dev/null | grep -qx 'protected-roots.tsv'
dd if="$initramfs" skip="$offset" iflag=skip_bytes status=none | gzip -cd | cpio -it 2>/dev/null | grep -qx 'profiled-python-entrypoints.tsv'
(
    initramfs_work=$(mktemp -d /var/tmp/t1os-initramfs-policy-validate.XXXXXX)
    trap 'rm -rf -- "$initramfs_work"' EXIT
    dd if="$initramfs" skip="$offset" iflag=skip_bytes status=none |
        gzip -cd |
        (cd "$initramfs_work" && cpio -id --quiet)

    "$initramfs_work/bin/busybox" sh -eu -s -- \
        "$initramfs_work" "$expected_python_release" <<'BOOT_POLICY_TEST'
root=$1
expected_python_release=$2
definitions=$("$root/bin/busybox" sed '/^\. \/angel-recovery$/d;/^mount_pseudo_filesystems$/,$d' "$root/init")
eval "$definitions"
busybox="$root/bin/busybox"
protected_inventory="$root/protected-roots.tsv"
profiled_inventory="$root/profiled-python-entrypoints.tsv"

secure_protected_directory "$root"
secure_protected_file "$root/init" 0555
secure_protected_file "$protected_inventory" 0444
secure_protected_file "$profiled_inventory" 0444
[ "$("$busybox" sed -n '$=' "$profiled_inventory")" -gt 0 ]
validate_protected_inventory_file

"$busybox" awk -F '\t' '
    $1 == "H" && $2 == "1" && $3 == expected && $5 == "6" { release = 1 }
    $1 == "F" && $2 == "python_software" && $3 == "bin/python" { stable = 1 }
    $1 == "F" && $2 == "python_software" && $3 == "bin/python3.14" { versioned = 1 }
    $1 == "F" && $2 == "python_software" && $3 == "bin/python3.13" { compatibility = 1 }
    $1 == "D" && $2 == "python_software" && $3 == "lib/python3.14" { stdlib = 1 }
    $2 == "python_software" && $3 ~ /^lib\/python3\.13(\/|$)/ { obsolete = 1 }
    END { exit !(release && stable && versioned && compatibility && stdlib && !obsolete) }
' expected="$expected_python_release" "$protected_inventory"

malformed_inventory="$root/protected-roots-malformed.tsv"
"$busybox" cp "$protected_inventory" "$malformed_inventory"
"$busybox" chmod 0644 "$malformed_inventory"
"$busybox" printf 'X\tunexpected\n' >>"$malformed_inventory"
"$busybox" chmod 0444 "$malformed_inventory"
protected_inventory=$malformed_inventory
if validate_protected_inventory_file; then
    echo 'The boot inventory validator accepted a malformed record.' >&2
    exit 1
fi
BOOT_POLICY_TEST

    unshare --mount "$initramfs_work/bin/busybox" sh -eu -s -- "$initramfs_work" <<'BOOT_MOUNT_POLICY_TEST'
root=$1
busybox="$root/bin/busybox"
probe_root="$root/mount-probe"
cleanup() {
    "$busybox" umount "$probe_root" 2>/dev/null || true
}
trap cleanup EXIT

"$busybox" mount --make-rprivate /
"$busybox" mkdir -p "$probe_root"
"$busybox" mount -t tmpfs -o rw,nodev,nosuid tmpfs "$probe_root"
definitions=$("$busybox" sed '/^\. \/angel-recovery$/d;/^mount_pseudo_filesystems$/,$d' "$root/init")
eval "$definitions"
busybox="$root/bin/busybox"

"$busybox" chmod 0777 "$probe_root"
secure_protected_mount_root "$probe_root"
"$busybox" ln -s "$probe_root" "$root/mount-probe-link"
if secure_protected_mount_root "$root/mount-probe-link"; then
    echo 'The protected mount-root validator accepted a symbolic link.' >&2
    exit 1
fi
"$busybox" rm "$root/mount-probe-link"
BOOT_MOUNT_POLICY_TEST
)
if dd if="$initramfs" skip="$offset" iflag=skip_bytes status=none | gzip -cd | \
        cpio -itv 2>/dev/null | awk '$1 ~ /^l/ { found=1 } END { exit found ? 0 : 1 }'; then
    echo 'The hardware initramfs contains forbidden symbolic links.' >&2
    exit 1
fi
cpio -it < "$initramfs" 2>/dev/null | grep -qx 'kernel/x86/microcode/AuthenticAMD.bin'
cpio -it < "$initramfs" 2>/dev/null | grep -qx 'kernel/x86/microcode/GenuineIntel.bin'
rm -rf -- "$module_work"
mkdir -p "$module_work"
tar --zstd -xf "$modules" -C "$module_work"
if tar --zstd -tf "$modules" | grep -Eq '^\.?/?(lib|usr|sbin|bin)/'; then
    echo 'The module archive contains a forbidden Linux hierarchy.' >&2
    exit 1
fi
test -s "$module_work/the one/drivers/modules/module-manifest.sha256"
(cd "$module_work/the one/drivers/modules" && sha256sum -c --quiet module-manifest.sha256)
test -s "$module_work/the one/drivers/modules"/*/modules.dep
file "$module_loader" | grep -F 'statically linked' >/dev/null
strings "$module_loader" | grep -F '/the one/drivers/modules' >/dev/null
strings "$module_loader" | grep -F '/the one/drivers/processes/modules' >/dev/null
strings "$module_loader" | grep -F '/the one/drivers/processes/cmdline' >/dev/null
strings "$module_loader" | grep -F '/the one/drivers/state/module/%s' >/dev/null
if strings "$module_loader" | grep -Fx '/proc/modules' >/dev/null; then exit 1; fi
if strings "$module_loader" | grep -Fx '/proc/cmdline' >/dev/null; then exit 1; fi
"$module_loader" --version | grep -F 'kmod version 34.2' >/dev/null
kernel_release=$(find "$module_work/the one/drivers/modules" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | head -n 1)
[ -n "$kernel_release" ]
"$module_loader" --dirname "$module_work" --set-version "$kernel_release" --show-depends snd_usb_audio | grep -F 'snd-usb-audio.ko' >/dev/null
nvidia_core_module=$(find "$module_work/the one/drivers/modules/$kernel_release" -type f -name 'nvidia.ko*' -print -quit)
nvidia_uvm_module=$(find "$module_work/the one/drivers/modules/$kernel_release" -type f -name 'nvidia-uvm.ko*' -print -quit)
test -n "$nvidia_core_module"
test -n "$nvidia_uvm_module"
[ "$(modinfo -F version "$nvidia_core_module")" = '610.43.03' ]
[ "$(modinfo -F version "$nvidia_uvm_module")" = '610.43.03' ]
[ "$(modinfo -F version "$nvidia_core_module")" = "$(modinfo -F version "$nvidia_uvm_module")" ]
nvidia_uvm_dependencies=$("$module_loader" --dirname "$module_work" --set-version "$kernel_release" --show-depends nvidia_uvm)
printf '%s\n' "$nvidia_uvm_dependencies" | awk '
    /^insmod .*\/nvidia\.ko(\.[^ ]+)?[[:space:]]*$/ { core = NR }
    /^insmod .*\/nvidia-uvm\.ko(\.[^ ]+)?[[:space:]]*$/ { uvm = NR }
    END { exit !(core && uvm && core < uvm) }
'
rm -rf -- "$module_work"

if tar --zstd -tvf "$firmware" | awk '$1 ~ /^l/ { found=1 } END { exit found ? 0 : 1 }'; then
    echo 'The firmware archive contains forbidden symbolic links.' >&2
    exit 1
fi

readelf -lW "$wireless_engine" | grep -F '/the one/catalogue/network/ld-linux-x86-64.so.2' >/dev/null
readelf -dW "$wireless_engine" | grep -F '/the one/catalogue/network' >/dev/null
"$network_loader" --library-path "$network_catalogue" "$wireless_engine" -v | grep -F 'wpa_supplicant v2.11' >/dev/null
readelf -h "$nvidia_path_provider" >/dev/null
readelf -dW "$nvidia_path_provider" |
    grep -F '/the one/catalogue/graphics/nvidia:/the one/catalogue/graphics:/the one/catalogue/python' \
        >/dev/null
strings "$nvidia_path_provider" | grep -F '/the one/drivers/nodes' >/dev/null
strings "$nvidia_path_provider" | grep -F '/the one/drivers/processes' >/dev/null
strings "$nvidia_path_provider" | grep -F '/the one/drivers/state' >/dev/null
strings "$nvidia_path_provider" | grep -F 't1os-cuda-thread-name' >/dev/null
if strings "$nvidia_path_provider" | grep -F '/the one/drivers/nodes/null' >/dev/null; then exit 1; fi
strings "$nvidia_path_provider" | grep -Fx 'nvidia-uvm' >/dev/null
if strings "$nvidia_path_provider" | grep -Fx 'nvidia-uvm-tools' >/dev/null; then exit 1; fi
(
    # The dynamic loader treats spaces in LD_PRELOAD as entry separators.
    # Exercise the exact provider from a private, space-free pathname.
    nvidia_path_provider_selftest="/var/tmp/t1os-nvidia-path-provider-selftest-$$.so"
    trap 'rm -f -- "$nvidia_path_provider_selftest"' EXIT
    cp -- "$nvidia_path_provider" "$nvidia_path_provider_selftest"
    LD_PRELOAD="$nvidia_path_provider_selftest" python3 - <<'PY'
import ctypes
import os

path = f'/proc/self/task/{os.getpid()}/comm'
flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_CLOEXEC
descriptor = os.open(path, flags)
try:
    target = os.readlink(f'/dev/fd/{descriptor}')
    assert target.startswith('/memfd:t1os-cuda-thread-name'), target
    payload = b't1os-cuda-worker'
    assert os.write(descriptor, payload) == len(payload)
finally:
    os.close(descriptor)

libc = ctypes.CDLL(None, use_errno=True)
libc.fopen.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
libc.fopen.restype = ctypes.c_void_p
libc.fileno.argtypes = [ctypes.c_void_p]
libc.fileno.restype = ctypes.c_int
libc.fclose.argtypes = [ctypes.c_void_p]
libc.fclose.restype = ctypes.c_int
stream = libc.fopen(path.encode(), b'wb')
assert stream, ctypes.get_errno()
stream_descriptor = libc.fileno(stream)
target = os.readlink(f'/dev/fd/{stream_descriptor}')
assert target.startswith('/memfd:t1os-cuda-thread-name'), target
assert libc.fclose(stream) == 0
PY
)
readelf -h "$chromium_provider" >/dev/null
for media_decode_binary in "$media_decode_service" "$media_decode_worker"; do
    readelf -h "$media_decode_binary" >/dev/null
    readelf -lW "$media_decode_binary" |
        grep -F '/the one/catalogue/python/ld-linux-x86-64.so.2' >/dev/null
    readelf -dW "$media_decode_binary" |
        grep -F '/the one/catalogue/audio:/the one/catalogue/graphics:/the one/catalogue/python' \
            >/dev/null
done
readelf -dW "$nvidia_vaapi" | grep -F '(NEEDED)' | grep -F 'libgstcodecparsers-1.0.so.0' >/dev/null
readelf -Ws "$nvidia_vaapi" | grep -F 'gst_vp9_parser_new' >/dev/null
readelf -Ws "$nvidia_vaapi" | grep -F 'gst_vp9_parser_parse_frame_header' >/dev/null
strings "$chromium_provider" | grep -F '/the one/drivers/nodes' >/dev/null
strings "$chromium_provider" | grep -F '/.ephemeral/chromium' >/dev/null
strings "$chromium_provider" | grep -Fx '/.ephemeral/chromium/extensions' >/dev/null
strings "$chromium_provider" | grep -Fx '/.ephemeral/volumes' >/dev/null
strings "$chromium_provider" | grep -Fx '/the one/drivers/nodes/urandom' >/dev/null
strings "$chromium_provider" | grep -Fx '/dev/nvidiactl' >/dev/null
strings "$chromium_provider" | grep -F '/the one/drivers/nodes/nvidia' >/dev/null
readelf -Ws "$chromium_provider" | awk '$8 == "__xstat64" { found=1 } END { exit !found }'
if strings "$chromium_provider" | grep -Fx '/dev/nvidia-uvm' >/dev/null; then exit 1; fi
if strings "$chromium_provider" | grep -Fx '/the one/drivers/nodes/nvidia-uvm' >/dev/null; then exit 1; fi
if strings "$chromium_provider" | grep -F 'NVIDIA sandbox bridge' >/dev/null; then exit 1; fi
if strings "$chromium_provider" | grep -Fx 't1os-nv-broker' >/dev/null; then exit 1; fi
if strings "$chromium_provider" | grep -Fx 't1os-cuda-thread-name' >/dev/null; then exit 1; fi
if strings "$chromium_provider" | grep -Fx '/dev/nvidia-uvm-tools' >/dev/null; then exit 1; fi
if strings "$chromium_provider" | grep -Fx '/dev/nvidia-caps' >/dev/null; then exit 1; fi
strings "$chromium_provider" | grep -Fx 'SingletonLock' >/dev/null
if strings "$chromium_provider" | grep -F 'T1OS path provider trace:' >/dev/null; then exit 1; fi
if strings "$chromium_provider" | grep -Fx '/drives' >/dev/null; then exit 1; fi
readelf -lW "$chromium_engine" | grep -F '/the one/software/chromium/libraries/ld-linux-x86-64.so.2' >/dev/null
readelf -dW "$chromium_engine" | grep -F '/the one/software/chromium/libraries' >/dev/null
chromium_video_features=$(strings "$chromium_engine" | grep -E '^(AcceleratedVideoDecodeLinuxGL|VaapiOnNvidiaGPUs|FallbackAfterDecodeError|Dav1dVideoDecoder)$')
for feature in AcceleratedVideoDecodeLinuxGL VaapiOnNvidiaGPUs FallbackAfterDecodeError Dav1dVideoDecoder; do
    printf '%s\n' "$chromium_video_features" | grep -Fx "$feature" >/dev/null
done
readelf -lW "$chromium_input_bridge" | grep -F '/the one/software/chromium/libraries/ld-linux-x86-64.so.2' >/dev/null
readelf -dW "$chromium_input_bridge" | grep -F '/the one/software/chromium/libraries' >/dev/null
strings "$chromium_input_bridge" | grep -F '/the one/software/chromium/libraries/libxdo.so.3' >/dev/null
file "$chromium_subprocess" | grep -Eq '(^|, )(statically linked|static-pie linked)(,|$)'
if readelf -lW "$chromium_subprocess" | grep -Eq '[[:space:]]INTERP[[:space:]]'; then exit 1; fi
strings "$chromium_subprocess" | grep -Fx '/the one/software/chromium/program/chrome' >/dev/null
strings "$chromium_subprocess" | grep -Fx '/.ephemeral/chromium/path-provider.so' >/dev/null
strings "$chromium_subprocess" | grep -Fx 'SANDBOX_LD_LIBRARY_PATH=/the one/software/chromium/libraries:/the one/catalogue/graphics' >/dev/null
strings "$chromium_subprocess" | grep -Fx 'SANDBOX_GPU_LD_LIBRARY_PATH=/the one/catalogue/graphics/nvidia:/the one/catalogue/graphics:/the one/software/chromium/libraries' >/dev/null
strings "$chromium_subprocess" | grep -Fx 'SANDBOX_GPU_EGL_VENDOR_LIBRARY_FILENAMES=/the one/catalogue/graphics/nvidia/egl_vendor.d/10_nvidia.json' >/dev/null
strings "$chromium_subprocess" | grep -Fx 'SANDBOX_GPU_EGL_EXTERNAL_PLATFORM_CONFIG_DIRS=/the one/catalogue/graphics/nvidia/gbm' >/dev/null
strings "$chromium_subprocess" | grep -Fx 'SANDBOX_GPU_GBM_BACKENDS_PATH=/the one/catalogue/graphics/nvidia/gbm' >/dev/null
strings "$chromium_subprocess" | grep -Fx 'SANDBOX_GPU_GBM_BACKEND=nvidia-drm' >/dev/null
strings "$chromium_subprocess" | grep -Fx 'SANDBOX_LD_PRELOAD' >/dev/null
strings "$chromium_subprocess" | grep -Fx 'SANDBOX_LD_LIBRARY_PATH' >/dev/null
strings "$chromium_subprocess" | grep -Fx 'T1OS_CHROMIUM_LAUNCH_ID' >/dev/null
strings "$chromium_subprocess" | grep -Fx '/the one/drivers/processes' >/dev/null
strings "$chromium_subprocess" | grep -Fx 't1os-chrome-subprocess: invalid child process type' >/dev/null
strings "$chromium_subprocess" | grep -Fx 't1os-chrome-subprocess: invalid child identity' >/dev/null
strings "$chromium_subprocess" | grep -Fx 't1os-chrome-subprocess: invalid Chromium parent' >/dev/null
strings "$chromium_subprocess" | grep -Fx 't1os-chrome-subprocess: unsafe loader environment' >/dev/null
strings "$chromium_subprocess" | grep -Fx 'GLIBC_TUNABLES=' >/dev/null
readelf -h "$chromium_sandbox" >/dev/null
strings "$chromium_sandbox" | grep -Fx '/.ephemeral/chromium/sandbox-root' >/dev/null
if strings "$chromium_sandbox" | grep -F '/.t1p' >/dev/null; then exit 1; fi
if strings "$chromium_sandbox" | grep -F '/proc/self/fd' >/dev/null; then exit 1; fi
if strings "$chromium_sandbox" | grep -F '/.ephemeral/chromium/processes' >/dev/null; then exit 1; fi
strings "$chromium_engine" | grep -F '/the one/settings/network/dns.txt' >/dev/null
strings "$chromium_libc" | grep -F '/the one/settings/network/dns.txt' >/dev/null
if strings "$chromium_engine" | grep -F '/etc/resolv.conf' >/dev/null; then exit 1; fi
if strings "$chromium_libc" | grep -F '/etc/resolv.conf' >/dev/null; then exit 1; fi
if strings "$chromium_engine" | grep -F '/.t1dns/resolver' >/dev/null; then exit 1; fi
if strings "$chromium_libc" | grep -F '/.t1dns/resolver' >/dev/null; then exit 1; fi
if strings "$chromium_engine" | grep -F '/the one/dns.txt' >/dev/null; then exit 1; fi
if strings "$chromium_libc" | grep -F '/the one/dns.txt' >/dev/null; then exit 1; fi
strings "$chromium_libasound" | grep -F '/the one/drivers/nodes/null' >/dev/null
if strings "$chromium_libasound" | grep -Fx '/dev/null' >/dev/null; then exit 1; fi
'@

$normalizedLinuxCheck = $linuxCheck.Replace("`r", '') + "`n# end"
$normalizedLinuxCheck | wsl.exe -d Ubuntu -u root --exec bash -s -- $wslInit $wslInitramfs $wslModules $wslModuleLoader $wslWirelessEngine $wslNetworkLoader $wslNetworkCatalogue $wslChromiumEngine $wslChromiumProvider $wslChromiumSandbox $wslChromiumLibc $wslChromiumInputBridge $wslChromiumLibasound $wslChromiumSubprocess $wslNvidiaPathProvider $wslNvidiaVaapi $wslFirmware $wslMediaDecodeService $wslMediaDecodeWorker $pythonRelease
$linuxCheckExitCode = $LASTEXITCODE
if ($linuxCheckExitCode -ne 0) {
    throw 'Hardware Linux artifact validation failed.'
}

if ($IncludeUsbImage) {
    & pwsh -NoLogo -NoProfile -NonInteractive -File (Join-Path $PSScriptRoot 'validate hardware usb image.ps1')
    if ($LASTEXITCODE -ne 0) {
        throw 'Hardware USB image validation failed.'
    }
}

Write-Host 'T1OS hardware build validation passed.'
