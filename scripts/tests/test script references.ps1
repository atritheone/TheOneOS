[CmdletBinding()]
param()

$incrementalTestBootstrap = Join-Path $PSScriptRoot '..\incremental test.ps1'
if (Test-Path -LiteralPath $incrementalTestBootstrap -PathType Leaf) {
    . $incrementalTestBootstrap
    if (Invoke-T1OSIncrementalTestGuard -ScriptPath $PSCommandPath -BoundParameters $PSBoundParameters -UnboundArguments $args) { return }
}

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$scriptsRoot = Join-Path $projectRoot 'scripts'
$failures = [System.Collections.Generic.List[string]]::new()
$allowedGeneratedReferences = @('scripts/fixture.py')

function Resolve-KnownStaticRoot {
    param(
        [Parameter(Mandatory)]
        [System.Management.Automation.Language.ExpressionAst]$Expression,

        [Parameter(Mandatory)]
        [System.IO.FileInfo]$SourceFile
    )

    if ($Expression -isnot [System.Management.Automation.Language.VariableExpressionAst]) {
        return $null
    }

    switch -Regex ($Expression.VariablePath.UserPath) {
        '^(?i:PSScriptRoot)$' { return $SourceFile.DirectoryName }
        '^(?i:projectRoot|repoRoot)$' { return $projectRoot }
        '^(?i:scriptRoot|scriptsRoot)$' { return $scriptsRoot }
        default { return $null }
    }
}

foreach ($sourceFile in Get-ChildItem -LiteralPath $scriptsRoot -Recurse -File -Filter '*.ps1') {
    $tokens = $null
    $parseErrors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile(
        $sourceFile.FullName,
        [ref]$tokens,
        [ref]$parseErrors
    )
    foreach ($parseError in $parseErrors) {
        $relativeSource = [System.IO.Path]::GetRelativePath($projectRoot, $sourceFile.FullName)
        $failures.Add("${relativeSource}:$($parseError.Extent.StartLineNumber): PowerShell parse error: $($parseError.Message)")
    }

    $joinCommands = $ast.FindAll(
        {
            param($node)
            $node -is [System.Management.Automation.Language.CommandAst] -and
                $node.GetCommandName() -ieq 'Join-Path'
        },
        $true
    )
    foreach ($command in $joinCommands) {
        $arguments = @(
            $command.CommandElements | Select-Object -Skip 1 | Where-Object {
                $_ -isnot [System.Management.Automation.Language.CommandParameterAst]
            }
        )
        if ($arguments.Count -lt 2) {
            continue
        }
        $base = Resolve-KnownStaticRoot -Expression $arguments[0] -SourceFile $sourceFile
        $child = $arguments[1]
        if ($null -eq $base -or
            $child -isnot [System.Management.Automation.Language.StringConstantExpressionAst] -or
            $child.Value -notmatch '(?i)\.(?:ps1|py)$') {
            continue
        }

        $candidate = [System.IO.Path]::GetFullPath((Join-Path $base $child.Value))
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            $relativeSource = [System.IO.Path]::GetRelativePath($projectRoot, $sourceFile.FullName)
            $relativeCandidate = [System.IO.Path]::GetRelativePath($projectRoot, $candidate)
            $failures.Add("${relativeSource}:$($command.Extent.StartLineNumber): missing script reference: $relativeCandidate")
        }
    }

    $literalPaths = $ast.FindAll(
        {
            param($node)
            $node -is [System.Management.Automation.Language.StringConstantExpressionAst] -and
                $node.Value -match '^(?i:scripts)[\\/].+\.(?:ps1|py)$'
        },
        $true
    )
    foreach ($literal in $literalPaths) {
        $relativeLiteral = $literal.Value.Replace('\', '/')
        if ($relativeLiteral -in $allowedGeneratedReferences) {
            continue
        }
        $candidate = Join-Path $projectRoot $literal.Value
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            $relativeSource = [System.IO.Path]::GetRelativePath($projectRoot, $sourceFile.FullName)
            $failures.Add("${relativeSource}:$($literal.Extent.StartLineNumber): missing project script reference: $($literal.Value)")
        }
    }
}

foreach ($sourceFile in Get-ChildItem -LiteralPath $scriptsRoot -Recurse -File -Filter '*.py') {
    $sourceText = Get-Content -LiteralPath $sourceFile.FullName -Raw
    foreach ($match in [regex]::Matches(
        $sourceText,
        "(?i)(?<path>scripts[\\/][A-Za-z0-9_. /\\-]+\.(?:ps1|py))"
    )) {
        $relative = $match.Groups['path'].Value.Replace('\', '/').Trim()
        if ($relative -in $allowedGeneratedReferences) {
            continue
        }
        $candidate = Join-Path $projectRoot $relative
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            $line = 1 + ($sourceText.Substring(0, $match.Index) -split "`n").Count - 1
            $relativeSource = [System.IO.Path]::GetRelativePath($projectRoot, $sourceFile.FullName)
            $failures.Add("${relativeSource}:${line}: missing project script reference: $relative")
        }
    }
}

$commandCatalogue = Join-Path $projectRoot 'software\command centre\electron\commands.ts'
if (-not (Test-Path -LiteralPath $commandCatalogue -PathType Leaf)) {
    $failures.Add('Command Centre command catalogue is missing.')
}
else {
    $catalogueText = Get-Content -LiteralPath $commandCatalogue -Raw
    foreach ($match in [regex]::Matches($catalogueText, "(?m)\bscript:\s*'(?<path>[^']+)'")) {
        $relative = $match.Groups['path'].Value
        $candidate = Join-Path $scriptsRoot $relative
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            $line = 1 + ($catalogueText.Substring(0, $match.Index) -split "`n").Count - 1
            $failures.Add("software/command centre/electron/commands.ts:${line}: missing command script: scripts/$relative")
        }
    }
}

if ($failures.Count -gt 0) {
    throw "Script reference audit failed:`n$($failures -join "`n")"
}

Write-Host 'Script reference audit passed.'
