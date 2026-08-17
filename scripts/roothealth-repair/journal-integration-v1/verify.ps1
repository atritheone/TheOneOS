[CmdletBinding()]
param(
    [string]$ProjectRoot,

    [string]$NtfscpPath,

    [switch]$RunSyntheticBundleTest,

    [switch]$RunFixtureSuite
)

$incrementalTestBootstrap = Join-Path $PSScriptRoot '..\..\incremental test.ps1'
if (Test-Path -LiteralPath $incrementalTestBootstrap -PathType Leaf) {
    . $incrementalTestBootstrap
    if (Invoke-T1OSIncrementalTestGuard -ScriptPath $PSCommandPath -BoundParameters $PSBoundParameters -UnboundArguments $args) { return }
}
$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Join-Path $PSScriptRoot '..\..\..'
}
$ProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot)
$patchPath = Join-Path $PSScriptRoot 'roothealth-journal-integration-v1.patch'
$baselineManifestPath = Join-Path $PSScriptRoot 'baseline-source-sha256.tsv'
$proposedManifestPath = Join-Path $PSScriptRoot 'proposed-source-sha256.tsv'
$qualificationPath = Join-Path $PSScriptRoot 'qualification.json'
$packageManifestPath = Join-Path $PSScriptRoot 'package-sha256.tsv'
$provenancePath = Join-Path $PSScriptRoot 'ntfscp-provenance.proposed-test-only.json'
$syntheticTestPath = Join-Path $PSScriptRoot 'test-synthetic-bundle-manifest.ps1'

foreach ($required in @(
    $patchPath,
    $baselineManifestPath,
    $proposedManifestPath,
    $qualificationPath,
    $packageManifestPath,
    $provenancePath,
    $syntheticTestPath
)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Journal integration package input not found: $required"
    }
}
if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    throw 'Ubuntu WSL is required to verify the journal integration package.'
}

function Get-LowerSha256 {
    param([Parameter(Mandatory)][string]$Path)
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
}

function Read-SourceManifest {
    param([Parameter(Mandatory)][string]$Path)
    $lines = @(Get-Content -LiteralPath $Path)
    if ($lines.Count -lt 2 -or $lines[0] -cne "sha256`tbytes`tpath") {
        throw "Invalid source manifest header: $Path"
    }
    $seen = [Collections.Generic.HashSet[string]]::new(
        [StringComparer]::Ordinal
    )
    $entries = @()
    foreach ($line in $lines[1..($lines.Count - 1)]) {
        $parts = $line -split "`t", 3
        if (
            $parts.Count -ne 3 -or
            $parts[0] -notmatch '^[0-9a-f]{64}$' -or
            $parts[1] -notmatch '^[1-9][0-9]*$' -or
            -not $parts[2].StartsWith('scripts/', [StringComparison]::Ordinal) -or
            $parts[2].Contains('..', [StringComparison]::Ordinal) -or
            [System.IO.Path]::IsPathRooted($parts[2]) -or
            -not $seen.Add($parts[2])
        ) {
            throw "Invalid source manifest record: $line"
        }
        $entries += [pscustomobject]@{
            Sha256 = $parts[0]
            Bytes = [int64]$parts[1]
            Path = $parts[2]
        }
    }
    return @($entries)
}

function Assert-ManifestTree {
    param(
        [Parameter(Mandatory)][string]$Root,
        [Parameter(Mandatory)]$Entries
    )
    foreach ($entry in $Entries) {
        $path = Join-Path $Root ($entry.Path -replace '/', '\')
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Source-bound file is missing: $path"
        }
        $item = Get-Item -LiteralPath $path
        if (
            [int64]$item.Length -ne [int64]$entry.Bytes -or
            (Get-LowerSha256 -Path $path) -cne $entry.Sha256
        ) {
            throw "Source-bound file changed: $path"
        }
    }
}

function ConvertTo-WslPath {
    param([Parameter(Mandatory)][string]$Path)
    $converted = & wsl.exe -d Ubuntu --exec wslpath -a $Path
    if ($LASTEXITCODE -ne 0 -or -not $converted) {
        throw "Could not translate path for WSL: $Path"
    }
    return ([string]($converted | Select-Object -First 1)).Trim()
}

$qualification = Get-Content -LiteralPath $qualificationPath -Raw | ConvertFrom-Json
if (
    [string]$qualification.state -cne 'PROPOSED_FAIL_CLOSED' -or
    [bool]$qualification.scope.production_usb_build_executed -or
    [bool]$qualification.scope.production_scripts_modified_in_place -or
    [bool]$qualification.scope.init_or_boot_modified -or
    [bool]$qualification.scope.repairs_enabled
) {
    throw 'Qualification status is not the required non-production fail-closed state.'
}
if (
    (Get-LowerSha256 -Path $baselineManifestPath) -cne
        [string]$qualification.source_binding.baseline_manifest_sha256 -or
    (Get-LowerSha256 -Path $proposedManifestPath) -cne
        [string]$qualification.source_binding.proposed_manifest_sha256 -or
    (Get-LowerSha256 -Path $patchPath) -cne
        [string]$qualification.source_binding.patch_sha256
) {
    throw 'Qualification source or patch hash binding changed.'
}

$packageEntries = Read-SourceManifest -Path $packageManifestPath
$listedPackagePaths = @($packageEntries | ForEach-Object { $_.Path })
$actualPackagePaths = @(
    Get-ChildItem -LiteralPath $PSScriptRoot -File |
        Where-Object Name -cne 'package-sha256.tsv' |
        Sort-Object Name |
        ForEach-Object { 'scripts/roothealth-repair/journal-integration-v1/' + $_.Name }
)
if (@(Compare-Object $listedPackagePaths $actualPackagePaths -CaseSensitive).Count -ne 0) {
    throw 'Journal integration package file inventory changed.'
}
Assert-ManifestTree -Root $ProjectRoot -Entries $packageEntries

$baselineEntries = Read-SourceManifest -Path $baselineManifestPath
$proposedEntries = Read-SourceManifest -Path $proposedManifestPath
Assert-ManifestTree -Root $ProjectRoot -Entries $baselineEntries

$work = Join-Path ([System.IO.Path]::GetTempPath()) (
    '.roothealth-journal-package-' + [guid]::NewGuid().ToString('N')
)
New-Item -ItemType Directory -Path (Join-Path $work 'scripts') -Force | Out-Null
try {
    foreach ($entry in $baselineEntries) {
        $source = Join-Path $ProjectRoot ($entry.Path -replace '/', '\')
        $destination = Join-Path $work ($entry.Path -replace '/', '\')
        Copy-Item -LiteralPath $source -Destination $destination
    }
    $wslWork = ConvertTo-WslPath -Path $work
    $wslPatch = ConvertTo-WslPath -Path $patchPath
    & wsl.exe -d Ubuntu --exec git -C $wslWork apply `
        --check --whitespace=error-all $wslPatch
    if ($LASTEXITCODE -ne 0) {
        throw 'The proposal patch does not cleanly apply to its source-bound baseline.'
    }
    & wsl.exe -d Ubuntu --exec git -C $wslWork apply `
        --whitespace=error-all $wslPatch
    if ($LASTEXITCODE -ne 0) {
        throw 'The proposal patch failed to apply after its dry run.'
    }
    Assert-ManifestTree -Root $work -Entries $proposedEntries

    $powerShellFiles = @(Get-ChildItem -LiteralPath (Join-Path $work 'scripts') -Filter '*.ps1')
    foreach ($file in $powerShellFiles) {
        $tokens = $null
        $errors = $null
        [void][System.Management.Automation.Language.Parser]::ParseFile(
            $file.FullName,
            [ref]$tokens,
            [ref]$errors
        )
        if ($errors.Count -ne 0) {
            throw "PowerShell parse failed for applied source: $($file.Name)"
        }
    }

    $bashAssignments = [ordered]@{
        'create hardware usb image.ps1' = 'buildCommand'
        'validate hardware usb image.ps1' = 'validateCommand'
        'create hardware usb bundle.ps1' = 'shell'
        'test hardware usb bundle.ps1' = 'shell'
        'test roothealth journal.ps1' = 'testScript'
    }
    foreach ($pair in $bashAssignments.GetEnumerator()) {
        $path = Join-Path (Join-Path $work 'scripts') $pair.Key
        $tokens = $null
        $errors = $null
        $ast = [System.Management.Automation.Language.Parser]::ParseFile(
            $path,
            [ref]$tokens,
            [ref]$errors
        )
        $name = $pair.Value
        $assignment = $ast.Find({
            param($node)
            $node -is [System.Management.Automation.Language.AssignmentStatementAst] -and
            $node.Left -is [System.Management.Automation.Language.VariableExpressionAst] -and
            $node.Left.VariablePath.UserPath -ceq $name
        }, $true)
        if (-not $assignment) {
            throw "Could not locate Bash here-string $name in $($pair.Key)."
        }
        $assignment.Right.Value | & wsl.exe -d Ubuntu --exec bash -n
        if ($LASTEXITCODE -ne 0) {
            throw "Bash parse failed for $($pair.Key)::$name."
        }
    }

    $pythonCompile = 'import pathlib,sys; p=pathlib.Path(sys.argv[1]); compile(p.read_text(encoding="utf-8-sig"),str(p),"exec")'
    $standalonePython = @(Get-ChildItem -LiteralPath (Join-Path $work 'scripts') -Filter '*.py')
    foreach ($file in $standalonePython) {
        $wslFile = ConvertTo-WslPath -Path $file.FullName
        & wsl.exe -d Ubuntu --exec env PYTHONDONTWRITEBYTECODE=1 `
            python3 -B -c $pythonCompile $wslFile
        if ($LASTEXITCODE -ne 0) {
            throw "Python compile failed for applied source: $($file.Name)"
        }
    }
    $inlineCount = 0
    foreach ($file in $powerShellFiles) {
        $text = Get-Content -LiteralPath $file.FullName -Raw
        foreach ($match in [regex]::Matches(
            $text,
            "(?ms)<<'PY'\r?\n(.*?)\r?\nPY"
        )) {
            $inlineCount += 1
            $match.Groups[1].Value | & wsl.exe -d Ubuntu --exec env `
                PYTHONDONTWRITEBYTECODE=1 python3 -B -c `
                'import sys; compile(sys.stdin.read(),"inline","exec")'
            if ($LASTEXITCODE -ne 0) {
                throw "Inline Python compile failed for applied source: $($file.Name)"
            }
        }
    }
    if (
        $powerShellFiles.Count -ne 6 -or
        $bashAssignments.Count -ne 5 -or
        $standalonePython.Count -ne 2 -or
        $inlineCount -ne 30
    ) {
        throw 'Applied static-unit counts differ from the qualified matrix.'
    }
    $imageBuilderText = Get-Content -LiteralPath (
        Join-Path (Join-Path $work 'scripts') 'create hardware usb image.ps1'
    ) -Raw
    if (
        $imageBuilderText.Contains(
            '--allow-proposed-test-tool',
            [StringComparison]::Ordinal
        ) -or
        -not $imageBuilderText.Contains(
            'provision-flags-device "$root_device"',
            [StringComparison]::Ordinal
        ) -or
        -not $imageBuilderText.Contains(
            '--builder-image "$output"',
            [StringComparison]::Ordinal
        )
    ) {
        throw 'Applied builder entrypoint or release provenance closure changed.'
    }

    if (-not [string]::IsNullOrWhiteSpace($NtfscpPath)) {
        $NtfscpPath = [System.IO.Path]::GetFullPath($NtfscpPath)
        if (-not (Test-Path -LiteralPath $NtfscpPath -PathType Leaf)) {
            throw "Selected ntfscp not found: $NtfscpPath"
        }
        $validator = Join-Path (Join-Path $work 'scripts') 'validate roothealth journal.py'
        $wslValidator = ConvertTo-WslPath -Path $validator
        $wslTool = ConvertTo-WslPath -Path $NtfscpPath
        $wslProvenance = ConvertTo-WslPath -Path $provenancePath
        & wsl.exe -u root -e env PYTHONDONTWRITEBYTECODE=1 `
            python3 -B $wslValidator verify-ntfscp $wslTool $wslProvenance `
            --allow-proposed-test-tool
        if ($LASTEXITCODE -ne 0) {
            throw 'Proposed selected ntfscp failed its test-only source binding.'
        }
        & wsl.exe -u root -e env PYTHONDONTWRITEBYTECODE=1 `
            python3 -B $wslValidator verify-ntfscp $wslTool $wslProvenance `
            *> $null
        if ($LASTEXITCODE -eq 0) {
            throw 'Proposed-test-only ntfscp passed the production release gate.'
        }
    }
    elseif ($RunFixtureSuite) {
        throw '-RunFixtureSuite requires -NtfscpPath.'
    }

    if ($RunSyntheticBundleTest) {
        & pwsh -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass `
            -File $syntheticTestPath -ScriptsRoot (Join-Path $work 'scripts')
        if ($LASTEXITCODE -ne 0) {
            throw 'Synthetic bundle manifest qualification failed.'
        }
    }
    if ($RunFixtureSuite) {
        & pwsh -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass `
            -File (Join-Path (Join-Path $work 'scripts') 'test roothealth journal.ps1') `
            -NtfscpPath $NtfscpPath -NtfscpProvenancePath $provenancePath
        if ($LASTEXITCODE -ne 0) {
            throw 'Disposable RootHealth journal qualification failed.'
        }
    }

    $cacheEntries = @(
        Get-ChildItem -LiteralPath $work -Recurse -Force -ErrorAction Stop |
            Where-Object {
                $_.Name -eq '__pycache__' -or $_.Extension -in @('.pyc', '.pyo')
            }
    )
    if ($cacheEntries.Count -ne 0) {
        throw 'Package verification generated forbidden Python bytecode.'
    }
    Write-Host (
        "ROOTHEALTH_JOURNAL_PACKAGE_PASS files=8 ps=6 bash=5 python=32 " +
        "synthetic=$([int][bool]$RunSyntheticBundleTest) " +
        "fixture=$([int][bool]$RunFixtureSuite)"
    )
}
finally {
    if (Test-Path -LiteralPath $work) {
        $resolved = [System.IO.Path]::GetFullPath($work)
        $tempPrefix = [System.IO.Path]::GetFullPath(
            [System.IO.Path]::GetTempPath()
        ).TrimEnd([System.IO.Path]::DirectorySeparatorChar) +
            [System.IO.Path]::DirectorySeparatorChar
        if (
            -not $resolved.StartsWith($tempPrefix, [StringComparison]::OrdinalIgnoreCase) -or
            [System.IO.Path]::GetFileName($resolved) -notlike
                '.roothealth-journal-package-*'
        ) {
            throw "Refusing to remove unexpected verifier path: $resolved"
        }
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}
