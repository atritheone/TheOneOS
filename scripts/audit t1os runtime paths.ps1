[CmdletBinding()]
param(
    [switch]$SkipStorageImage
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Path $PSScriptRoot -Parent
$contractPath = Join-Path $projectRoot 'source\settings\runtime paths.json'
$storagePath = Join-Path $projectRoot 'environment\storage.img'
$reportPath = Join-Path $projectRoot 'environment\hardware\t1os-runtime-path-audit.json'

if (-not (Test-Path -LiteralPath $contractPath -PathType Leaf)) {
    throw "T1OS runtime path contract not found: $contractPath"
}

$contract = Get-Content -LiteralPath $contractPath -Raw | ConvertFrom-Json
$forbidden = @($contract.forbidden_runtime_roots | ForEach-Object { [string]$_ })
if ($forbidden.Count -eq 0) {
    throw 'The T1OS runtime path contract has no forbidden roots.'
}

$escapedRoots = $forbidden | ForEach-Object { [regex]::Escape($_) }
$pattern = '(?<![A-Za-z0-9_.-])(?:' + ($escapedRoots -join '|') + ')(?:/|$|[\s"''])'
$sourceRoots = @(
    (Join-Path $projectRoot 'source\build software'),
    (Join-Path $projectRoot 'source\software\virtualbox'),
    (Join-Path $projectRoot 'source\software\chromium')
)
$extensions = @('.py', '.sh', '.json', '.conf', '.service', '.desktop')
$violations = [System.Collections.Generic.List[object]]::new()

foreach ($root in $sourceRoots) {
    if (-not (Test-Path -LiteralPath $root -PathType Container)) {
        continue
    }
    Get-ChildItem -LiteralPath $root -Recurse -File | Where-Object {
        $_.FullName -notmatch '[\\/]__pycache__[\\/]' -and
        $extensions -contains $_.Extension.ToLowerInvariant()
    } | ForEach-Object {
        $file = $_
        $lineNumber = 0
        Get-Content -LiteralPath $file.FullName | ForEach-Object {
            $lineNumber++
            if ($_ -match $pattern) {
                $violations.Add([pscustomobject]@{
                    kind = 'source'
                    path = [IO.Path]::GetRelativePath($projectRoot, $file.FullName)
                    line = $lineNumber
                    text = $_.Trim()
                })
            }
        }
    }
}

$storageChecked = $false
if (-not $SkipStorageImage -and (Test-Path -LiteralPath $storagePath -PathType Leaf)) {
    $storageChecked = $true
    $wslStorage = (& wsl.exe -d Ubuntu --exec wslpath -a $storagePath | Select-Object -First 1).Trim()
    if (-not $wslStorage) {
        throw 'Could not translate storage.img into a WSL path.'
    }

    $forbiddenNames = ($forbidden | ForEach-Object { $_.TrimStart('/') }) -join ','
    $probe = @'
set -euo pipefail
image=$1
names=$2
work=$(mktemp -d)
loop=
cleanup() {
    if mountpoint -q "$work"; then umount "$work"; fi
    if [ -n "$loop" ]; then losetup -d "$loop"; fi
    rmdir "$work"
}
trap cleanup EXIT
loop=$(losetup --find --show --read-only "$image")
mount -o ro "$loop" "$work"
IFS=,
for name in $names; do
    if [ -e "$work/$name" ] || [ -L "$work/$name" ]; then
        printf '{"kind":"storage-root","path":"/%s","line":0,"text":"forbidden runtime root exists in storage.img"}\n' "$name"
    fi
done
python3 - "$work" "$names" <<'PY'
from pathlib import Path
import json
import re
import sys

mount = Path(sys.argv[1])
roots = ["/" + item for item in sys.argv[2].split(",") if item]
pattern = re.compile(r"(?<![A-Za-z0-9_.-])(?:" + "|".join(map(re.escape, roots)) + r")(?:/|$|[\s\"'])")
scan_roots = (
    mount / "the one" / "build",
    mount / "the one" / "software" / "virtualbox",
    mount / "the one" / "software" / "chromium",
)
extensions = {".py", ".sh", ".json", ".conf", ".service", ".desktop"}
for root in scan_roots:
    if not root.is_dir():
        continue
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in extensions or "__pycache__" in path.parts:
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for number, line in enumerate(lines, 1):
            if pattern.search(line):
                print(json.dumps({
                    "kind": "storage-source",
                    "path": "/" + path.relative_to(mount).as_posix(),
                    "line": number,
                    "text": line.strip(),
                }, ensure_ascii=True))
PY
'@
    $found = @(& wsl.exe -d Ubuntu -u root --exec bash -c $probe bash $wslStorage $forbiddenNames)
    if ($LASTEXITCODE -ne 0) {
        throw "Could not inspect storage.img (exit code $LASTEXITCODE)."
    }
    foreach ($entry in $found) {
        if ($entry) {
            $violations.Add(($entry | ConvertFrom-Json))
        }
    }
}

$report = [ordered]@{
    schema = 1
    generated_utc = [DateTime]::UtcNow.ToString('o')
    contract = [IO.Path]::GetRelativePath($projectRoot, $contractPath)
    initramfs_excluded = $true
    storage_checked = $storageChecked
    passed = ($violations.Count -eq 0)
    violations = @($violations)
}

$reportDirectory = Split-Path -Path $reportPath -Parent
New-Item -ItemType Directory -Path $reportDirectory -Force | Out-Null
$report | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $reportPath -Encoding utf8

if ($violations.Count -ne 0) {
    $violations | Format-Table kind, path, line, text -AutoSize | Out-Host
    throw "T1OS runtime path audit failed with $($violations.Count) violation(s)."
}

Write-Host 'T1OS runtime path audit completed successfully.'
Write-Host "Report: $reportPath"
