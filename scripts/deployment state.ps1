function Get-T1OSDeploymentRootDefinitions {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$ProjectRoot,

        [Parameter(Mandatory)]
        [string]$ScriptRoot
    )

    $chromiumOverlay = Join-Path $ProjectRoot 'resource\chromium-source\150.0.7871.181'
    [ordered]@{
        build = @(
            (Join-Path $ProjectRoot 'source\build software')
        )
        boot = @(
            (Join-Path $ProjectRoot 'source\boot')
        )
        drivers = @(
            (Join-Path $ProjectRoot 'source\drivers')
        )
        graphics = @(
            (Join-Path $ProjectRoot 'source\catalogue\graphics')
            (Join-Path $ProjectRoot 'source\catalogue\graphics\catalogue.json')
        )
        virtualbox_catalogue = @(
            (Join-Path $ProjectRoot 'source\catalogue\virtualbox')
        )
        virtualbox_software = @(
            (Join-Path $ProjectRoot 'source\software\virtualbox')
        )
        virtualbox_settings = @(
            (Join-Path $ProjectRoot 'source\settings\virtualbox')
        )
        audio_catalogue = @(
            (Join-Path $ProjectRoot 'source\catalogue\audio')
        )
        audio_software = @(
            (Join-Path $ProjectRoot 'source\software\audio')
            (Join-Path $ProjectRoot 'source\software\audio\manifest.json')
        )
        network_catalogue = @(
            (Join-Path $ProjectRoot 'source\catalogue\network')
        )
        network_software = @(
            (Join-Path $ProjectRoot 'source\software\network')
        )
        network_settings = @(
            (Join-Path $ProjectRoot 'source\settings\network')
        )
        media_settings = @(
            (Join-Path $ProjectRoot 'source\settings\media')
            (Join-Path $ProjectRoot 'source\native\video')
            (Join-Path $chromiumOverlay 'manifest.json')
            (Join-Path $chromiumOverlay 'overlay\media\gpu\t1os')
        )
        chromium = @(
            (Join-Path $ProjectRoot 'source\software\chromium')
            (Join-Path $ProjectRoot 'source\software\chromium\manifest.json')
        )
        runtime_contract = @(
            (Join-Path $ProjectRoot 'source\settings\runtime paths.json')
        )
        image_catalogue = @(
            (Join-Path $ProjectRoot 'source\catalogue\image')
        )
        python = @(
            (Join-Path $ProjectRoot 'source\software\python')
            (Join-Path $ProjectRoot 'source\software\python\manifest.json')
            (Join-Path $ProjectRoot 'source\catalogue\python')
            (Join-Path $ProjectRoot 'source\python\locks\release.json')
            (Join-Path $ProjectRoot 'source\python\build\runtime.json')
        )
        resources = @(
            (Join-Path $ProjectRoot 'source\software\system')
            (Join-Path $ProjectRoot 'resource\fonts\atkinsonhyperlegiblenext.ttf')
            (Join-Path $ProjectRoot 'resource\fonts\cambria.ttf')
            (Join-Path $ProjectRoot 'resource\fonts\Fira_Code_v6.2\ttf\FiraCode-Retina.ttf')
            (Join-Path $ProjectRoot 'resource\fonts\Fira_Code_v6.2\ttf\FiraCode-Bold.ttf')
            (Join-Path $ProjectRoot 'resource\fonts\Fira_Code_v6.2\ttf\FiraCode-SemiBold.ttf')
            (Join-Path $ProjectRoot 'resource\logos')
            (Join-Path $ProjectRoot 'resource\cursors\extra simple white original')
            (Join-Path $ProjectRoot 'flash\red_screen_of_death.png')
        )
    }
}

function Get-T1OSDeploymentFileRecords {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$ProjectRoot,

        [Parameter(Mandatory)]
        [string[]]$Path
    )

    $records = [Collections.Generic.List[string]]::new()
    $largeFiles = [ordered]@{}
    $seen = [Collections.Generic.HashSet[string]]::new(
        [StringComparer]::OrdinalIgnoreCase
    )
    $contentPaths = [Collections.Generic.HashSet[string]]::new(
        [StringComparer]::OrdinalIgnoreCase
    )
    foreach ($inputPath in $Path) {
        if (Test-Path -LiteralPath $inputPath -PathType Leaf) {
            $null = $contentPaths.Add([IO.Path]::GetFullPath($inputPath))
        }
    }
    $fileCount = 0L
    $byteCount = 0L
    foreach ($inputPath in $Path) {
        if (-not (Test-Path -LiteralPath $inputPath)) {
            throw "T1OS deployment input is missing: $inputPath"
        }
        $items = if (Test-Path -LiteralPath $inputPath -PathType Leaf) {
            @(Get-Item -LiteralPath $inputPath -Force)
        }
        else {
            @(Get-ChildItem -LiteralPath $inputPath -File -Recurse -Force)
        }
        foreach ($item in $items) {
            if (-not $seen.Add($item.FullName)) {
                continue
            }
            if (
                $item.Extension -in @('.pyc', '.pyo') -or
                $item.DirectoryName -match '(^|[\\/])__pycache__($|[\\/])'
            ) {
                continue
            }
            $relative = [IO.Path]::GetRelativePath($ProjectRoot, $item.FullName).
                Replace('\', '/')
            $contentIdentity = if ($contentPaths.Contains($item.FullName)) {
                (Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).
                    Hash.ToLowerInvariant()
            }
            else {
                [string]$item.LastWriteTimeUtc.Ticks
            }
            $records.Add("$relative`0$($item.Length)`0$contentIdentity")
            if ($item.Length -ge 64MB) {
                $largeFiles[$relative] = [pscustomobject]@{
                    length = $item.Length
                    modified_utc_ticks = $item.LastWriteTimeUtc.Ticks
                }
            }
            $fileCount++
            $byteCount += $item.Length
        }
    }
    $records.Sort([StringComparer]::Ordinal)
    $payload = [Text.Encoding]::UTF8.GetBytes(($records -join "`n"))
    [pscustomobject]@{
        source_stamp = [Convert]::ToHexString(
            [Security.Cryptography.SHA256]::HashData($payload)
        ).ToLowerInvariant()
        files = $fileCount
        bytes = $byteCount
        large_files = [pscustomobject]$largeFiles
    }
}

function Get-T1OSDeploymentSourceState {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$ProjectRoot,

        [Parameter(Mandatory)]
        [string]$ScriptRoot
    )

    $definitions = Get-T1OSDeploymentRootDefinitions `
        -ProjectRoot $ProjectRoot -ScriptRoot $ScriptRoot
    $roots = [ordered]@{}
    foreach ($entry in $definitions.GetEnumerator()) {
        $roots[$entry.Key] = Get-T1OSDeploymentFileRecords `
            -ProjectRoot $ProjectRoot -Path $entry.Value
    }
    $chromiumManifestPath = Join-Path $ProjectRoot `
        'source\software\chromium\manifest.json'
    $chromiumManifest = Get-Content -Raw -LiteralPath $chromiumManifestPath |
        ConvertFrom-Json -ErrorAction Stop
    $chromiumEngineRecord = $roots.chromium.large_files.psobject.Properties[
        'source/software/chromium/program/chrome'
    ]
    if (
        $null -eq $chromiumEngineRecord -or
        [string]$chromiumManifest.engine_sha256 -notmatch '^[0-9a-f]{64}$'
    ) {
        throw 'The Chromium deployment manifest has no valid large-engine digest.'
    }
    $chromiumEngineRecord.Value | Add-Member -NotePropertyName declared_sha256 `
        -NotePropertyValue ([string]$chromiumManifest.engine_sha256)

    $contractPaths = @(
        (Join-Path $ScriptRoot 'deployment\push to disk.ps1'),
        (Join-Path $ScriptRoot 'deployment\update t1os usb.ps1'),
        (Join-Path $ScriptRoot 'deployment state.ps1'),
        (Join-Path $ScriptRoot 'common.ps1'),
        (Join-Path $ScriptRoot 'tests\test python runtime.ps1'),
        (Join-Path $ScriptRoot 'build\build boot protected roots.py'),
        (Join-Path $ScriptRoot 'deployment\migrate managed python usb acl.ps1'),
        (Join-Path $ScriptRoot 'deployment\push hardware kernel to usb.ps1')
    )
    $contract = Get-T1OSDeploymentFileRecords `
        -ProjectRoot $ProjectRoot -Path $contractPaths
    [pscustomobject]@{
        format = 2
        contract_stamp = $contract.source_stamp
        roots = [pscustomobject]$roots
    }
}

function Read-T1OSDeploymentState {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$Path
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $null
    }
    try {
        $state = Get-Content -Raw -LiteralPath $Path |
            ConvertFrom-Json -ErrorAction Stop
        if (
            [int]$state.format -ne 2 -or
            [string]$state.contract_stamp -notmatch '^[0-9a-f]{64}$' -or
            [string]::IsNullOrWhiteSpace([string]$state.target_identity) -or
            $null -eq $state.roots
        ) {
            return $null
        }
        return $state
    }
    catch {
        return $null
    }
}

function Get-T1OSDeploymentPlan {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [psobject]$SourceState,

        [AllowNull()]
        [psobject]$PreviousState,

        [Parameter(Mandatory)]
        [string]$TargetIdentity,

        [switch]$Full
    )

    $allRoots = @($SourceState.roots.psobject.Properties.Name)
    $stateValid = (
        -not $Full -and
        $null -ne $PreviousState -and
        [string]$PreviousState.target_identity -ceq $TargetIdentity -and
        [string]$PreviousState.contract_stamp -ceq [string]$SourceState.contract_stamp
    )
    if (-not $stateValid) {
        return [pscustomobject]@{
            roots = $allRoots
            state_valid = $false
            full_verification = $true
            unchanged_large_files = @()
        }
    }

    $changed = [Collections.Generic.List[string]]::new()
    $unchangedLargeFiles = [Collections.Generic.List[string]]::new()
    foreach ($rootName in $allRoots) {
        $sourceRoot = $SourceState.roots.psobject.Properties[$rootName].Value
        $previousProperty = $PreviousState.roots.psobject.Properties[$rootName]
        if (
            $null -eq $previousProperty -or
            [string]$previousProperty.Value.source_stamp -cne [string]$sourceRoot.source_stamp
        ) {
            $changed.Add($rootName)
            if (
                $null -ne $previousProperty -and
                $null -ne $previousProperty.Value.large_files
            ) {
                foreach ($largeFileProperty in $sourceRoot.large_files.psobject.Properties) {
                    $previousLargeFile = $previousProperty.Value.large_files.psobject.Properties[
                        $largeFileProperty.Name
                    ]
                    if (
                        $null -ne $previousLargeFile -and
                        [long]$previousLargeFile.Value.length -eq [long]$largeFileProperty.Value.length -and
                        [long]$previousLargeFile.Value.modified_utc_ticks -eq [long]$largeFileProperty.Value.modified_utc_ticks -and
                        [string]$previousLargeFile.Value.declared_sha256 -ceq [string]$largeFileProperty.Value.declared_sha256
                    ) {
                        $unchangedLargeFiles.Add("$rootName|$($largeFileProperty.Name)")
                    }
                }
            }
        }
    }
    [pscustomobject]@{
        roots = @($changed)
        state_valid = $true
        full_verification = $false
        unchanged_large_files = @($unchangedLargeFiles)
    }
}

function Write-T1OSDeploymentState {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$Path,

        [Parameter(Mandatory)]
        [psobject]$SourceState,

        [Parameter(Mandatory)]
        [string]$TargetIdentity,

        [Parameter(Mandatory)]
        [bool]$FullVerification,

        [AllowNull()]
        [psobject]$PreviousState
    )

    $parent = Split-Path -Path $Path -Parent
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    $state = [ordered]@{
        format = 2
        contract_stamp = [string]$SourceState.contract_stamp
        target_identity = $TargetIdentity
        verified_utc = [DateTime]::UtcNow.ToString('o')
        last_full_verification_utc = if ($FullVerification) {
            [DateTime]::UtcNow.ToString('o')
        }
        elseif ($PreviousState -and $PreviousState.last_full_verification_utc) {
            [string]$PreviousState.last_full_verification_utc
        }
        else {
            $null
        }
        roots = $SourceState.roots
    }
    $temporaryPath = "$Path.$PID.new"
    try {
        $json = ($state | ConvertTo-Json -Depth 8) + "`n"
        $encoding = [Text.UTF8Encoding]::new($false)
        $stream = [IO.FileStream]::new(
            $temporaryPath,
            [IO.FileMode]::Create,
            [IO.FileAccess]::Write,
            [IO.FileShare]::None,
            4096,
            [IO.FileOptions]::WriteThrough
        )
        try {
            $bytes = $encoding.GetBytes($json)
            $stream.Write($bytes, 0, $bytes.Length)
            $stream.Flush($true)
        }
        finally {
            $stream.Dispose()
        }
        Move-Item -LiteralPath $temporaryPath -Destination $Path -Force
    }
    finally {
        Remove-Item -LiteralPath $temporaryPath `
            -Force -ErrorAction SilentlyContinue
    }
}
