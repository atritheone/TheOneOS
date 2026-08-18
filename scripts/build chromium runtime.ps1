[CmdletBinding()]
param(
    [switch]$RefreshUpstream,

    [ValidateSet('release', 'development')]
    [string]$Profile = 'release',

    [switch]$Development,

    [switch]$HelpersOnly,

    [switch]$OptimizedHelpers
)

$ErrorActionPreference = 'Stop'
if ($Development) {
    if (
        $PSBoundParameters.ContainsKey('Profile') -and
        $Profile -cne 'development'
    ) {
        throw '-Development cannot be combined with a non-development -Profile.'
    }
    $Profile = 'development'
}
$developmentSourceProfile = $Profile -ceq 'development'
$developmentHelperBuild = $developmentSourceProfile -and -not $OptimizedHelpers
$projectRoot = Split-Path -Path $PSScriptRoot -Parent
$builder = Join-Path $projectRoot 'development\build chromium runtime.py'
$destination = Join-Path $projectRoot 'source\software\chromium'
$mediaPolicyPath = Join-Path $projectRoot 'source\settings\media\video decode service.json'
$mediaBuildMarker = (
    'T1OS_MEDIA_DECODER=T1MD/1;brokered_socket=1;pool=8;' +
    'chromium=24b04c927b23c39cf9c5227cc8dc6f64a744c8e9;' +
    'protocol_sha256=' +
    '11a319c26e499415cf39a3b6b5c59c3801b2e91859500472b92c6be1fcaceba0;' +
    'source_sha256=' +
    '102cea1fe8eb1358493eb2889579ece701ead0edf917d5edcc276a2d23fc0705'
)
$protocolHeaderSha256 = '11a319c26e499415cf39a3b6b5c59c3801b2e91859500472b92c6be1fcaceba0'
$sourceOverlaySha256 = '102cea1fe8eb1358493eb2889579ece701ead0edf917d5edcc276a2d23fc0705'
$subprocessSource = Join-Path $projectRoot 'source\entry\chromium\t1os_chrome_subprocess.c'
$subprocessLauncher = Join-Path $destination 'tools\t1os-chrome-subprocess'
$inputSource = Join-Path $projectRoot 'source\entry\chromium\t1os_xinput.c'
$inputBridge = Join-Path $destination 'tools\t1os-xinput'
$windowManagerSource = Join-Path $projectRoot 'source\entry\chromium\t1os_xwm.c'
$windowManager = Join-Path $destination 'tools\t1os-xwm'
$upstreamDirectTools = @(
    (Join-Path $destination 'tools\Xvfb'),
    (Join-Path $destination 'tools\dash'),
    (Join-Path $destination 'tools\xclip'),
    (Join-Path $destination 'tools\xdotool'),
    (Join-Path $destination 'tools\xkbcomp'),
    (Join-Path $destination 'tools\xrandr')
)
$fontConfigurationSource = Join-Path $projectRoot 'source\entry\chromium\fonts.conf'
$fontConfiguration = Join-Path $destination 'resources\fontconfig-configuration\fonts.conf'
$gsettingsSchemaSource = Join-Path $projectRoot 'source\entry\chromium\org.t1os.chromium.runtime.gschema.xml'
$gsettingsSchemaDirectory = Join-Path $destination 'resources\gsettings-schemas'
$gsettingsSchema = Join-Path $gsettingsSchemaDirectory 'org.t1os.chromium.runtime.gschema.xml'
$gsettingsCompiled = Join-Path $gsettingsSchemaDirectory 'gschemas.compiled'
$providerSource = Join-Path $projectRoot 'source\entry\chromium\t1os_path_provider.c'
$providerLibrary = Join-Path $destination 't1os-path-provider.so'
$sandboxSourceRoot = Join-Path $projectRoot 'source\entry\chromium'
$sandboxSource = Join-Path $sandboxSourceRoot 'sandbox\linux\suid\sandbox.c'
$sandboxProcessSource = Join-Path $sandboxSourceRoot 'sandbox\linux\suid\process_util_linux.c'
$sandboxExecutable = Join-Path $destination 'program\chrome-sandbox'
$upstreamSandboxExecutable = Join-Path $destination 'program\chrome_sandbox'
$developmentHelperCompilerFlags = @(
    '-O0',
    '-g3',
    '-fno-omit-frame-pointer'
)
$commonHelperSecurityCompilerFlags = @(
    '-fstack-protector-strong',
    '-fstack-clash-protection',
    '-fcf-protection=full',
    '-fno-plt',
    '-fno-common',
    '-Wformat=2',
    '-Werror=format-security'
)
$productionHelperCompilerFlags = @(
    '-O2',
    '-DNDEBUG',
    '-D_FORTIFY_SOURCE=3',
    '-fno-omit-frame-pointer'
)
$helperCompilerFlags = if ($developmentHelperBuild) {
    @($developmentHelperCompilerFlags) + @($commonHelperSecurityCompilerFlags)
}
else {
    @($productionHelperCompilerFlags) + @($commonHelperSecurityCompilerFlags)
}
$helperExecutableCompilerFlags = @('-fPIE')
$helperExecutableLinkerFlags = @(
    '-pie',
    '-Wl,-z,relro,-z,now,-z,noexecstack,--as-needed',
    '-Wl,--build-id=none'
)
$helperSharedLinkerFlags = @(
    '-Wl,-z,relro,-z,now,-z,noexecstack,--as-needed',
    '-Wl,--build-id=none'
)
$helperStaticLinkerFlags = @(
    '-static-pie',
    '-Wl,-z,relro,-z,noexecstack',
    '-Wl,--build-id=none'
)
$helperBuildMode = if ($developmentHelperBuild) { 'development' } else { 'production' }
$helperStripPolicy = if ($developmentHelperBuild) { 'none' } else { 'production-selective' }
$requiredDevelopmentDebugSections = @(
    '.debug_info',
    '.debug_line',
    '.symtab'
)
$requiredHelperDebugSections = [System.Collections.Generic.List[string]]::new()
if ($developmentHelperBuild) {
    foreach ($section in $requiredDevelopmentDebugSections) {
        $requiredHelperDebugSections.Add($section)
    }
}

$builderAvailable = Test-Path -LiteralPath $builder -PathType Leaf
if (-not $HelpersOnly -and -not $builderAvailable) {
    throw "Chromium upstream runtime builder not found: $builder"
}
if (
    $HelpersOnly -and
    -not (Test-Path -LiteralPath (Join-Path $destination 'program\chrome') -PathType Leaf)
) {
    throw 'Helpers-only mode requires an already packaged Chromium engine.'
}
foreach ($sourcePath in @($subprocessSource, $inputSource, $windowManagerSource, $fontConfigurationSource, $gsettingsSchemaSource)) {
    if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
        throw "Chromium helper source not found: $sourcePath"
    }
}
foreach ($sourcePath in @($providerSource, $sandboxSource, $sandboxProcessSource)) {
    if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
        throw "Chromium T1OS source not found: $sourcePath"
    }
}

$destinationItem = Get-Item -LiteralPath $destination
if ($destinationItem.LinkType) {
    throw "Chromium destination root must not be a link: $destination"
}
$destinationFullPath = [System.IO.Path]::GetFullPath($destination)
foreach ($directory in @(
    (Join-Path $destination 'program'),
    (Join-Path $destination 'tools'),
    (Join-Path $destination 'resources')
)) {
    $directoryFullPath = [System.IO.Path]::GetFullPath($directory)
    if (
        [System.IO.Path]::GetDirectoryName($directoryFullPath) -cne
            $destinationFullPath
    ) {
        throw "Chromium runtime directory escapes its exact root: $directory"
    }
    if (Test-Path -LiteralPath $directory) {
        $item = Get-Item -LiteralPath $directory
        if (-not $item.PSIsContainer -or $item.LinkType) {
            throw "Chromium runtime directory must be a plain directory: $directory"
        }
    }
    else {
        New-Item -ItemType Directory -Path $directory | Out-Null
    }
}

function ConvertTo-WslPath {
    param([Parameter(Mandatory)][string]$WindowsPath)

    $output = & wsl.exe -d Ubuntu --exec wslpath -a $WindowsPath
    if ($LASTEXITCODE -ne 0 -or -not $output) {
        throw "Could not translate path for WSL: $WindowsPath"
    }
    return ([string]($output | Select-Object -First 1)).Trim()
}

function Get-WslElfSectionNames {
    param([Parameter(Mandatory)][string]$WindowsPath)

    $wslPath = ConvertTo-WslPath -WindowsPath $WindowsPath
    $sectionOutput = @(
        & wsl.exe -d Ubuntu --exec readelf --wide --sections $wslPath
    )
    if ($LASTEXITCODE -ne 0) {
        throw "Could not inspect ELF sections: $WindowsPath"
    }
    $sectionNames = @(
        foreach ($line in $sectionOutput) {
            if (
                [string]$line -match '^\s*\[\s*(\d+)\]\s+(\S+)' -and
                [int]$Matches[1] -ne 0
            ) {
                # ELF section zero has no name. readelf prints its type
                # ("NULL") in the first non-whitespace column, so exclude the
                # reserved entry instead of recording the type as a name.
                $Matches[2]
            }
        }
    )
    if ($sectionNames.Count -eq 0) {
        throw "ELF section inventory is empty: $WindowsPath"
    }
    return @($sectionNames | Sort-Object -Unique)
}

function Get-WslElfHardening {
    param([Parameter(Mandatory)][string]$WindowsPath)

    $wslPath = ConvertTo-WslPath -WindowsPath $WindowsPath
    $header = @(& wsl.exe -d Ubuntu --exec readelf -hW $wslPath)
    if ($LASTEXITCODE -ne 0) {
        throw "Could not inspect ELF header: $WindowsPath"
    }
    $program = @(& wsl.exe -d Ubuntu --exec readelf -lW $wslPath)
    if ($LASTEXITCODE -ne 0) {
        throw "Could not inspect ELF program headers: $WindowsPath"
    }
    $dynamic = @(& wsl.exe -d Ubuntu --exec readelf -dW $wslPath 2>$null)
    $headerText = $header -join "`n"
    $programText = $program -join "`n"
    $dynamicText = $dynamic -join "`n"
    $stackLine = @($program | Where-Object { [string]$_ -match '\bGNU_STACK\b' })
    return [pscustomobject][ordered]@{
        position_independent = $headerText -match '(?m)^\s*Type:\s+DYN\b'
        relro = $programText -match '(?m)^\s*GNU_RELRO\b'
        bind_now = $dynamicText -match '(?m)(BIND_NOW|FLAGS(?:_1)?.*\bNOW\b)'
        non_executable_stack = (
            $stackLine.Count -eq 1 -and
            ([string]$stackLine[0] -notmatch '\bRWE\b')
        )
    }
}

function Assert-WslElfHardening {
    param(
        [Parameter(Mandatory)][string]$WindowsPath,
        [switch]$RequireBindNow
    )

    $hardening = Get-WslElfHardening -WindowsPath $WindowsPath
    if (
        -not $hardening.position_independent -or
        -not $hardening.relro -or
        -not $hardening.non_executable_stack -or
        ($RequireBindNow -and -not $hardening.bind_now)
    ) {
        throw (
            "ELF hardening gate failed: $WindowsPath " +
            "(PIE=$($hardening.position_independent), " +
            "RELRO=$($hardening.relro), BIND_NOW=$($hardening.bind_now), " +
            "NX_STACK=$($hardening.non_executable_stack))"
        )
    }
    return $hardening
}

if (-not $HelpersOnly) {
    $wslBuilder = ConvertTo-WslPath -WindowsPath $builder
    $command = if ($RefreshUpstream -or -not (Test-Path -LiteralPath (Join-Path $destination 'program\chrome') -PathType Leaf)) {
        'build'
    } else {
        'prepare'
    }

    & wsl.exe -d Ubuntu --exec python3 $wslBuilder $command --profile $Profile
    if ($LASTEXITCODE -ne 0) {
        throw "Chromium runtime build failed (exit code $LASTEXITCODE)."
    }
}
else {
    Write-Host "Rebuilding T1OS helpers only for the existing $Profile Chromium runtime."
}

New-Item -ItemType Directory -Path (Split-Path -Path $fontConfiguration -Parent) -Force | Out-Null
Copy-Item -LiteralPath $fontConfigurationSource -Destination $fontConfiguration -Force
New-Item -ItemType Directory -Path $gsettingsSchemaDirectory -Force | Out-Null
Copy-Item -LiteralPath $gsettingsSchemaSource -Destination $gsettingsSchema -Force
$wslGsettingsSchemaDirectory = ConvertTo-WslPath -WindowsPath $gsettingsSchemaDirectory
& wsl.exe -d Ubuntu --exec glib-compile-schemas --strict $wslGsettingsSchemaDirectory
if ($LASTEXITCODE -ne 0) {
    throw "Chromium private GSettings schema compilation failed (exit code $LASTEXITCODE)."
}

$wslSubprocessSource = ConvertTo-WslPath -WindowsPath $subprocessSource
$wslSubprocessLauncher = ConvertTo-WslPath -WindowsPath $subprocessLauncher
$subprocessBuildArguments = @(
    '-d', 'Ubuntu', '--exec', 'gcc', '-std=c11'
) + $helperCompilerFlags + $helperExecutableCompilerFlags + @(
    '-Wall', '-Wextra', '-Werror'
) + $helperStaticLinkerFlags + @(
    '-o', $wslSubprocessLauncher, $wslSubprocessSource
)
if (-not $developmentHelperBuild) {
    $subprocessBuildArguments += '-s'
}

# These upstream executables are direct children of the Chromium domain (Xvfb
# also invokes xkbcomp and, on compatibility paths, dash). Pin every one to the
# private loader and library tree so the LSM never has to authorize a generic
# dynamic-loader command line or a host-style /bin path.
foreach ($directTool in $upstreamDirectTools) {
    if (-not (Test-Path -LiteralPath $directTool -PathType Leaf)) {
        throw "Chromium direct-exec tool is missing: $directTool"
    }
    $wslDirectTool = ConvertTo-WslPath -WindowsPath $directTool
    & wsl.exe -d Ubuntu --exec patchelf `
        --set-interpreter '/the one/software/chromium/libraries/ld-linux-x86-64.so.2' `
        --set-rpath '/the one/software/chromium/libraries' `
        $wslDirectTool
    if ($LASTEXITCODE -ne 0) {
        throw "Chromium direct-exec tool patch failed: $directTool (exit code $LASTEXITCODE)."
    }
}
& wsl.exe @subprocessBuildArguments
if ($LASTEXITCODE -ne 0) {
    throw "Chromium subprocess bootstrap build failed (exit code $LASTEXITCODE)."
}

$wslInputSource = ConvertTo-WslPath -WindowsPath $inputSource
$wslInputBridge = ConvertTo-WslPath -WindowsPath $inputBridge
$inputBuildArguments = @(
    '-d', 'Ubuntu', '--exec', 'gcc', '-std=c11'
) + $helperCompilerFlags + $helperExecutableCompilerFlags + @(
    '-Wall', '-Wextra', '-Werror'
) + $helperExecutableLinkerFlags + @(
    '-o', $wslInputBridge, $wslInputSource, '-ldl'
)
& wsl.exe @inputBuildArguments
if ($LASTEXITCODE -ne 0) {
    throw "Chromium persistent input/fullscreen bridge build failed (exit code $LASTEXITCODE)."
}
& wsl.exe -d Ubuntu --exec patchelf `
    --set-interpreter '/the one/software/chromium/libraries/ld-linux-x86-64.so.2' `
    --set-rpath '/the one/software/chromium/libraries' `
    $wslInputBridge
if ($LASTEXITCODE -ne 0) {
    throw "Chromium input/fullscreen bridge patch failed (exit code $LASTEXITCODE)."
}
if (-not $developmentHelperBuild) {
    & wsl.exe -d Ubuntu --exec strip --strip-unneeded $wslInputBridge
    if ($LASTEXITCODE -ne 0) {
        throw "Chromium input/fullscreen bridge strip failed (exit code $LASTEXITCODE)."
    }
}

$wslWindowManagerSource = ConvertTo-WslPath -WindowsPath $windowManagerSource
$wslWindowManager = ConvertTo-WslPath -WindowsPath $windowManager
$wslChromiumLibraries = ConvertTo-WslPath -WindowsPath (Join-Path $destination 'libraries')
$windowManagerBuildArguments = @(
    '-d', 'Ubuntu', '--exec', 'gcc', '-std=c11'
) + $helperCompilerFlags + $helperExecutableCompilerFlags + @(
    '-Wall', '-Wextra', '-Werror'
) + $helperExecutableLinkerFlags + @(
    "-L$wslChromiumLibraries", "-Wl,-rpath-link,$wslChromiumLibraries",
    '-o', $wslWindowManager, $wslWindowManagerSource,
    '-l:libXdamage.so.1', '-l:libXfixes.so.3', '-l:libX11.so.6'
)
& wsl.exe @windowManagerBuildArguments
if ($LASTEXITCODE -ne 0) {
    throw "Chromium private X11 protocol bridge build failed (exit code $LASTEXITCODE)."
}
& wsl.exe -d Ubuntu --exec patchelf `
    --set-interpreter '/the one/software/chromium/libraries/ld-linux-x86-64.so.2' `
    --set-rpath '/the one/software/chromium/libraries' `
    $wslWindowManager
if ($LASTEXITCODE -ne 0) {
    throw "Chromium private X11 protocol bridge patch failed (exit code $LASTEXITCODE)."
}
if (-not $developmentHelperBuild) {
    & wsl.exe -d Ubuntu --exec strip --strip-unneeded $wslWindowManager
    if ($LASTEXITCODE -ne 0) {
        throw "Chromium private X11 protocol bridge strip failed (exit code $LASTEXITCODE)."
    }
}

$wslProviderSource = ConvertTo-WslPath -WindowsPath $providerSource
$wslProviderLibrary = ConvertTo-WslPath -WindowsPath $providerLibrary
$providerBuildArguments = @(
    '-d', 'Ubuntu', '--exec', 'gcc', '-std=gnu11'
) + $helperCompilerFlags + @(
    '-Wall', '-Wextra', '-Werror', '-fPIC', '-shared'
) + $helperSharedLinkerFlags + @(
    '-o', $wslProviderLibrary, $wslProviderSource, '-ldl'
)
& wsl.exe @providerBuildArguments
if ($LASTEXITCODE -ne 0) {
    throw "Chromium path provider build failed (exit code $LASTEXITCODE)."
}
$providerStrings = & wsl.exe -d Ubuntu --exec strings $wslProviderLibrary
$providerSymbols = & wsl.exe -d Ubuntu --exec readelf -Ws $wslProviderLibrary
if (
    $LASTEXITCODE -ne 0 -or
    $providerStrings -notcontains '/dev/nvidiactl' -or
    $providerStrings -notcontains '/the one/drivers/nodes/nvidiactl' -or
    $providerStrings -contains '/dev/nvidia-uvm' -or
    $providerStrings -contains '/the one/drivers/nodes/nvidia-uvm' -or
    $providerStrings -contains 't1os-cuda-thread-name' -or
    (($providerStrings -join "`n") -match 'NVIDIA sandbox bridge') -or
    (($providerStrings -join "`n") -match 't1os-nv-broker') -or
    (($providerStrings -join "`n") -match 'fresh-open') -or
    (($providerSymbols -join "`n") -match 'chromium_nvidia_broker') -or
    (($providerSymbols -join "`n") -match 'cuda_thread_name') -or
    (($providerSymbols -join "`n") -notmatch '(?m)\s__xstat64$')
) {
    throw (
        'Chromium path provider contains the retired CUDA/UVM broker or is ' +
        'missing its ordinary graphics/runtime path contract.'
    )
}

$wslSandboxSourceRoot = ConvertTo-WslPath -WindowsPath $sandboxSourceRoot
$wslSandboxSource = ConvertTo-WslPath -WindowsPath $sandboxSource
$wslSandboxProcessSource = ConvertTo-WslPath -WindowsPath $sandboxProcessSource
$wslSandboxExecutable = ConvertTo-WslPath -WindowsPath $sandboxExecutable
$sandboxBuildArguments = @(
    '-d', 'Ubuntu', '--exec', 'gcc', '-std=gnu11'
) + $helperCompilerFlags + $helperExecutableCompilerFlags + @(
    '-Wall', '-Wextra', '-Wno-unused-parameter'
) + $helperStaticLinkerFlags + @(
    '-I', $wslSandboxSourceRoot,
    '-o', $wslSandboxExecutable, $wslSandboxSource, $wslSandboxProcessSource
)
if (-not $developmentHelperBuild) {
    $sandboxBuildArguments += '-s'
}
& wsl.exe @sandboxBuildArguments
if ($LASTEXITCODE -ne 0) {
    throw "Chromium SUID sandbox build failed (exit code $LASTEXITCODE)."
}

$required = @(
    (Join-Path $destination 'program\chrome'),
    (Join-Path $destination 'program\chrome_crashpad_handler'),
    $sandboxExecutable
) + @($upstreamDirectTools) + @(
    (Join-Path $destination 'tools\t1os-xinput'),
    $windowManager,
    $subprocessLauncher,
    (Join-Path $destination 'libraries\ld-linux-x86-64.so.2'),
    $providerLibrary,
    $fontConfiguration,
    $gsettingsSchema,
    $gsettingsCompiled
)
foreach ($path in $required) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Chromium T1OS runtime output is missing: $path"
    }
}

foreach ($path in @(
    (Join-Path $destination 'program\chrome'),
    (Join-Path $destination 'program\chrome_crashpad_handler')
) + @($upstreamDirectTools) + @(
    $inputBridge,
    $windowManager,
    $providerLibrary
)) {
    Assert-WslElfHardening -WindowsPath $path -RequireBindNow | Out-Null
}

foreach ($path in @($upstreamDirectTools) + @(
    $inputBridge,
    $windowManager
)) {
    $wslPath = ConvertTo-WslPath -WindowsPath $path
    $actualInterpreter = & wsl.exe -d Ubuntu --exec patchelf --print-interpreter $wslPath
    if (
        $LASTEXITCODE -ne 0 -or
        ([string]$actualInterpreter).Trim() -cne
            '/the one/software/chromium/libraries/ld-linux-x86-64.so.2'
    ) {
        throw "Chromium tool has the wrong interpreter: $path"
    }
    $actualRunpath = & wsl.exe -d Ubuntu --exec patchelf --print-rpath $wslPath
    if (
        $LASTEXITCODE -ne 0 -or
        ([string]$actualRunpath).Trim() -cne
            '/the one/software/chromium/libraries'
    ) {
        throw "Chromium tool has the wrong RUNPATH: $path"
    }
}
foreach ($path in @($subprocessLauncher, $sandboxExecutable)) {
    # These two executables are fully static PIEs and therefore have no lazy
    # dynamic bindings to gate. PIE, RELRO, and a non-executable stack remain
    # mandatory.
    Assert-WslElfHardening -WindowsPath $path | Out-Null
}

$t1osInterpreter = '/the one/software/chromium/libraries/ld-linux-x86-64.so.2'
$t1osRunpath = '/the one/software/chromium/libraries'
$programDirectory = Join-Path $destination 'program'
$libraryDirectory = Join-Path $destination 'libraries'
$runtimeElfNames = @(
    'chrome',
    'chrome_crashpad_handler',
    'libEGL.so',
    'libGLESv2.so',
    'liboptimization_guide_internal.so',
    'libqt5_shim.so',
    'libqt6_shim.so',
    'libvk_swiftshader.so',
    'libvulkan.so.1'
)
foreach ($name in $runtimeElfNames) {
    $path = Join-Path $programDirectory $name
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        continue
    }
    $wslPath = ConvertTo-WslPath -WindowsPath $path
    $actualRunpath = & wsl.exe -d Ubuntu --exec patchelf --print-rpath $wslPath
    if ($LASTEXITCODE -ne 0 -or ([string]$actualRunpath).Trim() -cne $t1osRunpath) {
        throw "Chromium runtime ELF has the wrong RUNPATH: $path"
    }
    if ($name -in @('chrome', 'chrome_crashpad_handler')) {
        $actualInterpreter = & wsl.exe -d Ubuntu --exec patchelf --print-interpreter $wslPath
        if (
            $LASTEXITCODE -ne 0 -or
            ([string]$actualInterpreter).Trim() -cne $t1osInterpreter
        ) {
            throw "Chromium runtime ELF has the wrong interpreter: $path"
        }
    }
    $neededLibraries = @(
        & wsl.exe -d Ubuntu --exec patchelf --print-needed $wslPath
    )
    if ($LASTEXITCODE -ne 0) {
        throw "Could not inspect DT_NEEDED for Chromium runtime ELF: $path"
    }
    foreach ($needed in $neededLibraries) {
        $neededName = ([string]$needed).Trim()
        if (-not $neededName) {
            continue
        }
        if (
            -not (Test-Path -LiteralPath (Join-Path $libraryDirectory $neededName) -PathType Leaf)
        ) {
            throw "Chromium runtime dependency is unresolved: $name -> $neededName"
        }
    }
}

if (Test-Path -LiteralPath (Join-Path $destination 'manifest.json') -PathType Leaf) {
    $manifestPath = Join-Path $destination 'manifest.json'
    $manifest = Get-Content -LiteralPath $manifestPath -Raw |
        ConvertFrom-Json
    if (
        $manifest.development -isnot [bool] -or
        $manifest.development -ne $developmentSourceProfile -or
        -not $manifest.source_build -or
        [string]$manifest.source_build.profile -cne $Profile
    ) {
        throw (
            "The packaged Chromium engine is not the requested $Profile " +
            'source-build profile.'
        )
    }
    $helperPaths = [ordered]@{
        'program/chrome-sandbox' = $sandboxExecutable
        't1os-path-provider.so' = $providerLibrary
        'tools/t1os-chrome-subprocess' = $subprocessLauncher
        'tools/t1os-xinput' = $inputBridge
        'tools/t1os-xwm' = $windowManager
    }
    $helperHashes = [ordered]@{}
    $helperDebugSections = [ordered]@{}
    foreach ($entry in $helperPaths.GetEnumerator()) {
        $item = Get-Item -LiteralPath $entry.Value
        if ($item.LinkType) {
            throw "Compiled T1OS Chromium helper must not be a link: $($entry.Value)"
        }
        $helperHashes[$entry.Key] = (
            Get-FileHash -Algorithm SHA256 -LiteralPath $entry.Value
        ).Hash.ToLowerInvariant()
        $sections = @(Get-WslElfSectionNames -WindowsPath $entry.Value)
        if ($developmentHelperBuild) {
            foreach ($requiredSection in $requiredDevelopmentDebugSections) {
                if ($sections -cnotcontains $requiredSection) {
                    throw (
                        'Development T1OS Chromium helper is missing ' +
                        "$requiredSection`: $($entry.Key)"
                    )
                }
            }
        }
        $helperDebugSections[$entry.Key] = @($sections)
    }
    $directToolPaths = [ordered]@{}
    foreach ($path in $upstreamDirectTools) {
        $directToolPaths["tools/$([System.IO.Path]::GetFileName($path))"] = $path
    }
    $directToolHashes = [ordered]@{}
    foreach ($entry in $directToolPaths.GetEnumerator()) {
        $item = Get-Item -LiteralPath $entry.Value
        if ($item.LinkType) {
            throw "Chromium direct-exec tool must not be a link: $($entry.Value)"
        }
        $directToolHashes[$entry.Key] = (
            Get-FileHash -Algorithm SHA256 -LiteralPath $entry.Value
        ).Hash.ToLowerInvariant()
    }
    $manifest | Add-Member -NotePropertyName 't1os_helper_artifacts' `
        -NotePropertyValue ([pscustomobject]$helperHashes) -Force
    $manifest | Add-Member -NotePropertyName 't1os_helper_build' `
        -NotePropertyValue ([pscustomobject][ordered]@{
        mode = $helperBuildMode
        compiler_flags = @($helperCompilerFlags)
        strip_policy = $helperStripPolicy
        required_debug_sections = $requiredHelperDebugSections
        debug_sections = [pscustomobject]$helperDebugSections
    }) -Force
    $manifest | Add-Member -NotePropertyName 't1os_direct_tool_artifacts' `
        -NotePropertyValue ([pscustomobject]$directToolHashes) -Force
    [System.IO.File]::WriteAllText(
        $manifestPath,
        ($manifest | ConvertTo-Json -Depth 100) + "`n",
        [System.Text.UTF8Encoding]::new($false)
    )
    # Re-read the serialized inventory and prove its exact topology and bytes
    # before the media policy can be enabled or the sandbox can become SUID.
    $manifest = Get-Content -LiteralPath $manifestPath -Raw |
        ConvertFrom-Json
    $recordedHelperNames = @(
        $manifest.t1os_helper_artifacts.PSObject.Properties.Name |
            Sort-Object
    )
    $requiredHelperNames = @($helperPaths.Keys | Sort-Object)
    if (
        $recordedHelperNames.Count -ne $requiredHelperNames.Count -or
        (Compare-Object -CaseSensitive `
            -ReferenceObject $requiredHelperNames `
            -DifferenceObject $recordedHelperNames)
    ) {
        throw 'The T1OS Chromium helper hash inventory has the wrong keys.'
    }
    $recordedDirectToolNames = @(
        $manifest.t1os_direct_tool_artifacts.PSObject.Properties.Name |
            Sort-Object
    )
    $requiredDirectToolNames = @($directToolPaths.Keys | Sort-Object)
    if (
        $recordedDirectToolNames.Count -ne $requiredDirectToolNames.Count -or
        (Compare-Object -CaseSensitive `
            -ReferenceObject $requiredDirectToolNames `
            -DifferenceObject $recordedDirectToolNames)
    ) {
        throw 'The Chromium direct-exec tool hash inventory has the wrong keys.'
    }
    $helperBuild = $manifest.t1os_helper_build
    if (
        -not $helperBuild -or
        [string]$helperBuild.mode -cne $helperBuildMode -or
        [string]$helperBuild.strip_policy -cne $helperStripPolicy -or
        [string]::Join("`n", @($helperBuild.compiler_flags)) -cne
            [string]::Join("`n", @($helperCompilerFlags)) -or
        [string]::Join("`n", @($helperBuild.required_debug_sections)) -cne
            [string]::Join("`n", $requiredHelperDebugSections)
    ) {
        throw 'The T1OS Chromium helper build attestation is invalid.'
    }
    $recordedDebugNames = @(
        $helperBuild.debug_sections.PSObject.Properties.Name |
            Sort-Object
    )
    if (
        $recordedDebugNames.Count -ne $requiredHelperNames.Count -or
        (Compare-Object -CaseSensitive `
            -ReferenceObject $requiredHelperNames `
            -DifferenceObject $recordedDebugNames)
    ) {
        throw 'The T1OS Chromium helper debug-section inventory has the wrong keys.'
    }
    foreach ($entry in $helperPaths.GetEnumerator()) {
        $recordedHash = [string](
            $manifest.t1os_helper_artifacts.PSObject.Properties[
                $entry.Key
            ].Value
        )
        $actualHash = (
            Get-FileHash -Algorithm SHA256 -LiteralPath $entry.Value
        ).Hash.ToLowerInvariant()
        if ($recordedHash -cne $actualHash) {
            throw "Compiled T1OS Chromium helper hash mismatch: $($entry.Key)"
        }
        $recordedSections = @(
            $helperBuild.debug_sections.PSObject.Properties[
                $entry.Key
            ].Value
        )
        if ($recordedSections -ccontains 'NULL') {
            throw (
                'Compiled T1OS Chromium helper debug-section inventory ' +
                "contains reserved ELF section zero: $($entry.Key)"
            )
        }
        $actualSections = @(Get-WslElfSectionNames -WindowsPath $entry.Value)
        if (
            [string]::Join("`n", $recordedSections) -cne
                [string]::Join("`n", $actualSections)
        ) {
            throw (
                'Compiled T1OS Chromium helper debug-section inventory ' +
                "mismatch: $($entry.Key)"
            )
        }
    }
    foreach ($entry in $directToolPaths.GetEnumerator()) {
        $recordedHash = [string](
            $manifest.t1os_direct_tool_artifacts.PSObject.Properties[
                $entry.Key
            ].Value
        )
        $actualHash = (
            Get-FileHash -Algorithm SHA256 -LiteralPath $entry.Value
        ).Hash.ToLowerInvariant()
        if ($recordedHash -cne $actualHash) {
            throw "Chromium direct-exec tool hash mismatch: $($entry.Key)"
        }
    }
    $actualEngineHash = (
        Get-FileHash -Algorithm SHA256 -LiteralPath (
            Join-Path $destination 'program\chrome'
        )
    ).Hash.ToLowerInvariant()
    if ([string]$manifest.engine_sha256 -cne $actualEngineHash) {
        throw 'The installed Chromium manifest hash does not match program/chrome.'
    }
    $decoder = $manifest.t1os_media_decoder
    if (
        -not $decoder -or
        $decoder.available -isnot [bool] -or
        $decoder.available -ne $true -or
        [string]$decoder.protocol -cne 'T1MD' -or
        $decoder.protocol_version -isnot [long] -or
        $decoder.protocol_version -ne 1 -or
        [string]$decoder.feature -cne 'T1OSVideoDecoder' -or
        $decoder.brokered_socket -isnot [bool] -or
        $decoder.brokered_socket -ne $true -or
        $decoder.descriptor_pool_size -isnot [long] -or
        $decoder.descriptor_pool_size -ne 8 -or
        [string]$decoder.chromium_revision -cne
            '24b04c927b23c39cf9c5227cc8dc6f64a744c8e9' -or
        [string]$decoder.protocol_header_sha256 -cne
            $protocolHeaderSha256 -or
        [string]$decoder.source_overlay_sha256 -cne
            $sourceOverlaySha256 -or
        [string]$decoder.build_marker -cne $mediaBuildMarker
    ) {
        throw (
            'The source-built Chromium runtime does not advertise the exact ' +
            'brokered T1MD v1 decoder contract.'
        )
    }

    if (Test-Path -LiteralPath $upstreamSandboxExecutable) {
        throw (
            'The source-build install deployed upstream program/chrome_sandbox; ' +
            'only T1OS program/chrome-sandbox is permitted.'
        )
    }
    $forbiddenRuntimeExtensions = @(
        '.c', '.cc', '.cpp', '.cxx', '.h', '.hh', '.hpp', '.java', '.js',
        '.m', '.mm', '.py', '.rs', '.ts'
    )
    $looseLanguageArtifacts = @(
        Get-ChildItem -LiteralPath (Join-Path $destination 'program') `
            -Recurse -File |
            Where-Object {
                $forbiddenRuntimeExtensions -contains $_.Extension.ToLowerInvariant()
            }
    )
    if ($looseLanguageArtifacts.Count -ne 0) {
        throw (
            'The source-build install deployed loose-language artifacts: ' +
            (($looseLanguageArtifacts | Select-Object -First 5 -ExpandProperty FullName) -join ', ')
        )
    }

    $wslChromiumEngine = ConvertTo-WslPath -WindowsPath (
        Join-Path $destination 'program\chrome'
    )
    & wsl.exe -d Ubuntu --exec grep -a -F -q -- `
        $mediaBuildMarker $wslChromiumEngine
    if ($LASTEXITCODE -ne 0) {
        throw (
            'The source-built Chromium binary does not contain the exact ' +
            'brokered T1MD build marker.'
        )
    }

    $mediaPolicy = Get-Content -LiteralPath $mediaPolicyPath -Raw |
        ConvertFrom-Json
    $mediaPolicy.enabled = $true
    $mediaPolicy.kill_switch = $false
    $mediaPolicy.development_debug = $false
    $mediaPolicy.max_sessions = 8
    $mediaPolicy.protocol_version = 1
    [System.IO.File]::WriteAllText(
        $mediaPolicyPath,
        ($mediaPolicy | ConvertTo-Json -Depth 4) + "`n",
        [System.Text.UTF8Encoding]::new($false)
    )
    Write-Host (
        'Enabled the T1MD v1 media service policy for this validated ' +
        "$Profile Chromium build."
    )
}
else {
    throw 'The packaged source-built Chromium manifest is absent.'
}

Write-Host 'T1OS Chromium runtime completed successfully.'
Write-Host "Runtime: $destination"
