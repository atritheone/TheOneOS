[CmdletBinding()]
param(
    [switch]$Execute,
    [switch]$SkipUbuntu
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$mode = if ($Execute) { 'execute' } else { 'preview' }
$removedBytes = [int64]0
$plannedBytes = [int64]0
$protected = [System.Collections.Generic.List[string]]::new()
$actions = [System.Collections.Generic.List[object]]::new()

function Get-DirectoryBytes {
    param([Parameter(Mandatory)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return [int64]0
    }
    $item = Get-Item -LiteralPath $Path -Force
    if (-not $item.PSIsContainer) {
        return [int64]$item.Length
    }
    $measurement = Get-ChildItem -LiteralPath $Path -Recurse -Force -File -ErrorAction SilentlyContinue |
        Measure-Object -Property Length -Sum
    return [int64]($measurement.Sum ?? 0)
}

function Get-ProjectRelativePath {
    param([Parameter(Mandatory)][string]$Path)

    $fullRoot = [System.IO.Path]::GetFullPath($projectRoot).TrimEnd('\')
    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $prefix = $fullRoot + [System.IO.Path]::DirectorySeparatorChar
    if (-not $fullPath.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing a path outside the T1OS project: $fullPath"
    }
    if ($fullPath -eq $fullRoot) {
        throw 'Refusing to target the project root.'
    }
    return $fullPath.Substring($prefix.Length).Replace('\', '/')
}

function Test-ContainsTrackedFiles {
    param([Parameter(Mandatory)][string]$Path)

    $relative = Get-ProjectRelativePath -Path $Path
    $tracked = @(& git -C $projectRoot ls-files -- $relative)
    if ($LASTEXITCODE -ne 0) {
        throw "git ls-files failed while checking $relative"
    }
    return $tracked.Count -gt 0
}

function Add-ProtectedPath {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Reason
    )

    $display = if ([System.IO.Path]::IsPathRooted($Path)) {
        try { Get-ProjectRelativePath -Path $Path } catch { $Path }
    }
    else { $Path }
    $message = "$display - $Reason"
    $protected.Add($message)
    Write-Host "PROTECTED: $message" -ForegroundColor Yellow
}

function Remove-ProjectTarget {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Reason
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }
    $relative = Get-ProjectRelativePath -Path $Path
    $item = Get-Item -LiteralPath $Path -Force
    # OneDrive Files On-Demand marks ordinary hydrated entries as reparse
    # points. LinkType distinguishes actual junctions/symbolic links from that
    # metadata without preventing cleanup inside this OneDrive workspace.
    if (-not [string]::IsNullOrWhiteSpace([string]$item.LinkType)) {
        Add-ProtectedPath -Path $Path -Reason "target is a $($item.LinkType)"
        return
    }
    if (Test-ContainsTrackedFiles -Path $Path) {
        Add-ProtectedPath -Path $Path -Reason 'contains Git-tracked files'
        return
    }
    $bytes = Get-DirectoryBytes -Path $Path
    $script:plannedBytes += $bytes
    $actions.Add([pscustomobject]@{ path = $relative; bytes = $bytes; reason = $Reason })
    if ($Execute) {
        Remove-Item -LiteralPath $Path -Recurse -Force
        if (Test-Path -LiteralPath $Path) {
            throw "Cleanup target still exists after removal: $relative"
        }
        $script:removedBytes += $bytes
        Write-Host "REMOVED: $relative ($([math]::Round($bytes / 1MB, 1)) MiB) - $Reason"
    }
    else {
        Write-Host "WOULD REMOVE: $relative ($([math]::Round($bytes / 1MB, 1)) MiB) - $Reason"
    }
}

function Get-RelativeFileMap {
    param([Parameter(Mandatory)][string]$Path)

    $resolved = (Resolve-Path -LiteralPath $Path).Path.TrimEnd('\')
    $map = @{}
    foreach ($file in Get-ChildItem -LiteralPath $resolved -Recurse -Force -File) {
        $relative = $file.FullName.Substring($resolved.Length + 1).Replace('\', '/')
        $map[$relative] = $file.FullName
    }
    return $map
}

function Test-TreesMatch {
    param(
        [Parameter(Mandatory)][string]$Stage,
        [Parameter(Mandatory)][string]$Published
    )

    if (-not (Test-Path -LiteralPath $Stage -PathType Container) -or
        -not (Test-Path -LiteralPath $Published -PathType Container)) {
        return $false
    }
    $stageFiles = Get-RelativeFileMap -Path $Stage
    $publishedFiles = Get-RelativeFileMap -Path $Published
    if ($stageFiles.Count -ne $publishedFiles.Count) {
        return $false
    }
    foreach ($relative in $stageFiles.Keys) {
        if (-not $publishedFiles.ContainsKey($relative)) {
            return $false
        }
        $stageItem = Get-Item -LiteralPath $stageFiles[$relative]
        $publishedItem = Get-Item -LiteralPath $publishedFiles[$relative]
        if ($stageItem.Length -ne $publishedItem.Length) {
            return $false
        }
        if ((Get-FileHash -Algorithm SHA256 -LiteralPath $stageItem.FullName).Hash -ne
            (Get-FileHash -Algorithm SHA256 -LiteralPath $publishedItem.FullName).Hash) {
            return $false
        }
    }
    return $true
}

function Test-FilesMatch {
    param([Parameter(Mandatory)][array]$Pairs)

    foreach ($pair in $Pairs) {
        $left = Join-Path $projectRoot $pair[0]
        $right = Join-Path $projectRoot $pair[1]
        if (-not (Test-Path -LiteralPath $left -PathType Leaf) -or
            -not (Test-Path -LiteralPath $right -PathType Leaf)) {
            return $false
        }
        $leftItem = Get-Item -LiteralPath $left
        $rightItem = Get-Item -LiteralPath $right
        if ($leftItem.Length -ne $rightItem.Length -or
            (Get-FileHash -Algorithm SHA256 -LiteralPath $left).Hash -ne
            (Get-FileHash -Algorithm SHA256 -LiteralPath $right).Hash) {
            return $false
        }
    }
    return $true
}

function Remove-MatchingStage {
    param(
        [Parameter(Mandatory)][string]$RelativeStage,
        [Parameter(Mandatory)][scriptblock]$Verification
    )

    $stage = Join-Path $projectRoot $RelativeStage
    if (-not (Test-Path -LiteralPath $stage)) {
        return
    }
    if (& $Verification) {
        Remove-ProjectTarget -Path $stage -Reason 'published output is present and byte-identical'
    }
    else {
        Add-ProtectedPath -Path $stage -Reason 'published-output verification failed'
    }
}

function Remove-GitIgnoredBuildProducts {
    param([Parameter(Mandatory)][string]$RelativePath)

    $target = Join-Path $projectRoot $RelativePath
    if (-not (Test-Path -LiteralPath $target -PathType Container)) {
        return
    }
    $arguments = if ($Execute) { @('clean', '-fdX', '--', $RelativePath) } else { @('clean', '-ndX', '--', $RelativePath) }
    $output = @(& git -C $projectRoot @arguments)
    $cleanExitCode = $LASTEXITCODE
    if ($cleanExitCode -ne 0 -and $Execute -and $RelativePath -eq 'development/roothealth/engine') {
        Write-Host 'Repairing Windows permissions on WSL-created ignored RootHealth directories.' -ForegroundColor Yellow
        $permissionTargets = @(
            'development/roothealth/engine/autom4te.cache',
            'development/roothealth/engine/libntfs/.deps',
            'development/roothealth/engine/libntfs/.libs',
            'development/roothealth/engine/src/.deps',
            'development/roothealth/engine/src/.libs',
            'development/roothealth/engine/tests/.libs'
        )
        $account = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
        foreach ($permissionRelative in $permissionTargets) {
            $permissionPath = Join-Path $projectRoot $permissionRelative
            if (-not (Test-Path -LiteralPath $permissionPath)) {
                continue
            }
            [void](Get-ProjectRelativePath -Path $permissionPath)
            & git -C $projectRoot check-ignore -q -- $permissionRelative
            if ($LASTEXITCODE -ne 0) {
                throw "Refusing permission repair for a non-ignored path: $permissionRelative"
            }
            & takeown.exe /F $permissionPath /R /D Y | Out-Null
            if ($LASTEXITCODE -ne 0) {
                throw "takeown failed for $permissionRelative"
            }
            # WSL chmod metadata is represented by inherited deny ACEs on
            # DrvFs. Break inheritance only on these already-ignored build
            # directories, then grant the current Windows user full control.
            & icacls.exe $permissionPath /inheritance:r /grant:r "${account}:(OI)(CI)F" /T /C /Q | Out-Null
            if ($LASTEXITCODE -ne 0) {
                throw "icacls failed for $permissionRelative"
            }
        }
        $output += @(& git -C $projectRoot @arguments)
        $cleanExitCode = $LASTEXITCODE
    }
    if ($cleanExitCode -ne 0) {
        Add-ProtectedPath -Path $target -Reason 'ignored build contents were cleaned, but empty WSL-owned directories could not be removed without changing tracked parent ACLs'
        return
    }
    foreach ($line in $output) {
        Write-Host "GIT CLEAN: $line"
    }
}

function Assert-RetainedProducts {
    $required = @(
        'command_centre.exe',
        't1os_usb_flasher.exe',
        'environment/software/storage.img',
        'environment/software/t1os-root.vdi',
        'environment/software/t1os-root.vmdk',
        'environment/software/t1os-boot.iso',
        'environment/hardware/t1os-hardware-usb.img',
        'environment/hardware/The One OS 0.31.t1os',
        'environment/hardware/firmware.tar.zst',
        'environment/hardware/modules.tar.zst',
        'environment/hardware/boot/vmlinuz-hardware',
        'environment/hardware/boot/initramfs-hardware',
        'environment/hardware/tools/roothealth',
        'source/software/python/manifest.json',
        'source/python/locks/release.json',
        'development/python 3.14 candidate/t1os/manifest.json',
        'development/python 3.14 candidate/output/cpython-3.14.7-linux-x86_64.tar.gz',
        'development/roothealth/engine/configure.ac'
    )
    foreach ($relative in $required) {
        $path = Join-Path $projectRoot $relative
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Required retained product is missing: $relative"
        }
        if ((Get-Item -LiteralPath $path).Length -eq 0) {
            throw "Required retained product is empty: $relative"
        }
    }
}

function Remove-ElectronPackaging {
    param(
        [Parameter(Mandatory)][string]$ProjectRelative,
        [Parameter(Mandatory)][string]$PortableRelative,
        [Parameter(Mandatory)][string]$RetainedRelative
    )

    $portable = Join-Path $projectRoot $PortableRelative
    $retained = Join-Path $projectRoot $RetainedRelative
    if (-not (Test-Path -LiteralPath $portable -PathType Leaf)) {
        if (Test-Path -LiteralPath $retained -PathType Leaf) {
            return
        }
        Add-ProtectedPath -Path (Join-Path $projectRoot $ProjectRelative) -Reason 'neither packaged nor retained portable executable exists'
        return
    }
    $matches = Test-FilesMatch -Pairs @(,@($PortableRelative, $RetainedRelative))
    if (-not $matches) {
        if (-not (Test-Path -LiteralPath $portable -PathType Leaf) -or
            -not (Test-Path -LiteralPath $retained -PathType Leaf) -or
            (Get-Item -LiteralPath $portable).LastWriteTimeUtc -le (Get-Item -LiteralPath $retained).LastWriteTimeUtc) {
            Add-ProtectedPath -Path (Join-Path $projectRoot $ProjectRelative) -Reason 'portable executable differs and is not newer than the retained root executable'
            return
        }
        Write-Host "$(if ($Execute) { 'UPDATING' } else { 'WOULD UPDATE' }): $RetainedRelative from newer $PortableRelative"
        if ($Execute) {
            $temporary = "$retained.cleanup-new"
            Copy-Item -LiteralPath $portable -Destination $temporary -Force
            if ((Get-FileHash -Algorithm SHA256 -LiteralPath $temporary).Hash -ne
                (Get-FileHash -Algorithm SHA256 -LiteralPath $portable).Hash) {
                Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
                throw "Portable executable copy verification failed: $RetainedRelative"
            }
            Move-Item -LiteralPath $temporary -Destination $retained -Force
            if (-not (Test-FilesMatch -Pairs @(,@($PortableRelative, $RetainedRelative)))) {
                throw "Retained portable executable verification failed: $RetainedRelative"
            }
        }
    }
    foreach ($name in @('release', 'dist', 'dist-electron')) {
        Remove-ProjectTarget -Path (Join-Path $projectRoot "$ProjectRelative/$name") -Reason 'retained portable executable matches packaged output'
    }
}

function Invoke-UbuntuCleanup {
    $ubuntuProgram = @'
set -eu
mode=$1
[ "$(id -u)" -eq 0 ] || { echo 'ERROR|Ubuntu cleanup must run as root'; exit 2; }
grep -qi microsoft /proc/sys/kernel/osrelease || { echo 'ERROR|Not running under WSL'; exit 2; }

if ps -eo pid=,args= | grep -E '[t]1os|[c]hromium|[r]oothealth' | grep -v 'clean workspace.ps1' >/dev/null 2>&1; then
    echo 'ERROR|Active T1OS, Chromium, or RootHealth process detected'
    ps -eo pid=,args= | grep -E '[t]1os|[c]hromium|[r]oothealth' | grep -v 'clean workspace.ps1' || true
    exit 3
fi

is_mounted_or_contains_mount() {
    candidate=$1
    findmnt -rn -o TARGET | awk -v p="$candidate" '$0 == p || index($0, p "/") == 1 { found=1 } END { exit !found }'
}

clean_target() {
    candidate=$1
    [ -e "$candidate" ] || [ -L "$candidate" ] || return 0
    case "$candidate" in
        /mnt|/mnt/|/mnt/c|/mnt/c/*|/mnt/d|/mnt/d/*|/mnt/e|/mnt/e/*|/mnt/f|/mnt/f/*|/mnt/g|/mnt/g/*|/mnt/wsl|/mnt/wsl/*|/mnt/wslg|/mnt/wslg/*|/|/home|/root|/tmp|/var|/var/tmp)
            echo "ERROR|Forbidden Ubuntu target: $candidate"
            exit 4
            ;;
    esac
    if is_mounted_or_contains_mount "$candidate"; then
        echo "PROTECTED|Mounted path: $candidate"
        return 0
    fi
    bytes=$(du -s -B1 -- "$candidate" 2>/dev/null | awk '{print $1}')
    bytes=${bytes:-0}
    if [ "$mode" = execute ]; then
        rm -rf --one-file-system -- "$candidate"
        echo "REMOVED|$bytes|$candidate"
    else
        echo "WOULD_REMOVE|$bytes|$candidate"
    fi
}

for fixed in \
    /home/edward/t1os-chromium \
    /home/edward/depot_tools \
    /home/edward/.cache \
    /home/edward/.rustup \
    /home/edward/.cargo \
    /home/edward/.gsutil \
    /root/.cache/t1os \
    /root/.cache/pip \
    /root/.local/share/t1os \
    /root/.cargo \
    /root/.rustup \
    /root/roothealth-report \
    /autom4te.cache \
    /libntfs \
    /tests \
    /include \
    /m4 \
    /manpages \
    /fs \
    /.github \
    /.ephemeral \
    '/the one'
do
    clean_target "$fixed"
done

find /var/tmp -mindepth 1 -maxdepth 1 \
    \( -name 't1os-*' -o -name 'roothealth-*' -o -name 'pip-record-*' -o -name 'pyroute2-*.whl' \) \
    -print0 | while IFS= read -r -d '' candidate; do clean_target "$candidate"; done

find /tmp -mindepth 1 -maxdepth 1 \
    \( -name 't1os-*' -o -name 'roothealth*' -o -name 'rh-*' -o -name 'pip-*' \
       -o -name 'cpython+*' -o -name 'bootstrap+*' -o -name 'python_venv-*' \
       -o -name 'python_pep425tags-*' -o -name 'virtualenv+*' -o -name 'wheels+*' \
       -o -name 'ffconf.*' -o -name '*.resolved' \) \
    -print0 | while IFS= read -r -d '' candidate; do clean_target "$candidate"; done

find /root -mindepth 1 -maxdepth 1 \
    \( -name 'rh-*' -o -name 't1os-*' \) -print0 |
    while IFS= read -r -d '' candidate; do clean_target "$candidate"; done

if mountpoint -q /mnt/t1fs; then
    t1fs_source=$(findmnt -rn -M /mnt/t1fs -o SOURCE)
    case "$t1fs_source" in
        /dev/loop[0-9]*) ;;
        *) echo "ERROR|Unexpected /mnt/t1fs source: $t1fs_source"; exit 5 ;;
    esac
    t1fs_backing=$(losetup -n -O BACK-FILE "$t1fs_source")
    case "$t1fs_backing" in
        */reference/projects/t1os/environment/software/storage.img) ;;
        *) echo "ERROR|Unexpected /mnt/t1fs backing file: $t1fs_backing"; exit 5 ;;
    esac
    if [ "$mode" = execute ]; then
        umount /mnt/t1fs
        losetup -d "$t1fs_source"
        rmdir /mnt/t1fs
        echo 'REMOVED|4096|/mnt/t1fs (unmounted retained storage.img and detached its exact loop device)'
    else
        echo "WOULD_REMOVE|4096|/mnt/t1fs (would unmount retained storage.img and detach $t1fs_source)"
    fi
elif [ -d /mnt/t1fs ]; then
    if [ -n "$(find /mnt/t1fs -mindepth 1 -maxdepth 1 -print -quit)" ]; then
        echo 'PROTECTED|Non-empty stale mount directory: /mnt/t1fs'
    elif [ "$mode" = execute ]; then
        rmdir /mnt/t1fs
        echo 'REMOVED|4096|/mnt/t1fs'
    else
        echo 'WOULD_REMOVE|4096|/mnt/t1fs'
    fi
fi

for mountpoint in /mnt/t1-* /mnt/t1audit /mnt/t1check /mnt/t1drive /mnt/t1fontcheck \
    /mnt/t1inspect /mnt/t1verify /mnt/t1os-*; do
    [ -d "$mountpoint" ] || continue
    if is_mounted_or_contains_mount "$mountpoint"; then
        echo "PROTECTED|Mounted path: $mountpoint"
    elif [ -n "$(find "$mountpoint" -mindepth 1 -maxdepth 1 -print -quit)" ]; then
        echo "PROTECTED|Non-empty stale mount directory: $mountpoint"
    elif [ "$mode" = execute ]; then
        rmdir -- "$mountpoint"
        echo "REMOVED|4096|$mountpoint"
    else
        echo "WOULD_REMOVE|4096|$mountpoint"
    fi
done

if [ "$mode" = execute ]; then
    apt-get clean
    rm -rf --one-file-system -- /var/lib/apt/lists/*
    echo 'REMOVED|0|APT download cache and package lists'
else
    apt_bytes=$(du -s -B1 /var/cache/apt /var/lib/apt/lists 2>/dev/null | awk '{s+=$1} END {print s+0}')
    echo "WOULD_REMOVE|$apt_bytes|APT download cache and package lists"
fi
'@

    # Passing a multiline string through PowerShell's native pipeline rewrites
    # line endings to CRLF. Base64 keeps the embedded Bash program byte-exact
    # while still leaving this as a single PowerShell script.
    $normalized = $ubuntuProgram.Replace("`r", '') + "`n"
    $encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($normalized))
    $ubuntuOutput = @(& wsl.exe -d Ubuntu -u root --exec bash -c `
        'printf %s "$2" | base64 -d | bash -s -- "$1"' cleanup $mode $encoded)
    if ($LASTEXITCODE -ne 0) {
        throw "Ubuntu cleanup failed (exit code $LASTEXITCODE).`n$($ubuntuOutput -join "`n")"
    }
    foreach ($line in $ubuntuOutput) {
        Write-Host "UBUNTU: $line"
        if ($line -match '^(?:WOULD_REMOVE|REMOVED)\|([0-9]+)\|') {
            $bytes = [int64]$Matches[1]
            $script:plannedBytes += $bytes
            if ($Execute) {
                $script:removedBytes += $bytes
            }
        }
        elseif ($line -match '^PROTECTED\|(.+)$') {
            $protected.Add("Ubuntu - $($Matches[1])")
        }
    }
}

Write-Host "T1OS workspace cleanup: $mode" -ForegroundColor Cyan
Write-Host "Project: $projectRoot"
Assert-RetainedProducts

Remove-MatchingStage -RelativeStage 'development/graphics runtime/stage' -Verification {
    (Test-TreesMatch -Stage (Join-Path $projectRoot 'development/graphics runtime/stage/catalogue') -Published (Join-Path $projectRoot 'source/catalogue/graphics')) -and
    (Test-TreesMatch -Stage (Join-Path $projectRoot 'development/graphics runtime/stage/software') -Published (Join-Path $projectRoot 'source/software/graphics'))
}
Remove-MatchingStage -RelativeStage 'development/audio runtime/stage' -Verification {
    (Test-TreesMatch -Stage (Join-Path $projectRoot 'development/audio runtime/stage/catalogue') -Published (Join-Path $projectRoot 'source/catalogue/audio')) -and
    (Test-TreesMatch -Stage (Join-Path $projectRoot 'development/audio runtime/stage/software') -Published (Join-Path $projectRoot 'source/software/audio'))
}
Remove-MatchingStage -RelativeStage 'development/driver runtime/stage' -Verification {
    Test-FilesMatch -Pairs @(,@('development/driver runtime/stage/modprobe', 'source/drivers/tools/modprobe'))
}
Remove-MatchingStage -RelativeStage 'development/graphics kernel/stage' -Verification {
    Test-FilesMatch -Pairs @(
        @('development/graphics kernel/stage/t1osbzimage-virtualbox-0.19', 'environment/software/t1osbzimage-virtualbox-0.19'),
        @('development/graphics kernel/stage/T10Skernel virtualbox 0.19 settings.txt', 'source/entry/kernel/T10Skernel virtualbox 0.19 settings.txt')
    )
}
Remove-MatchingStage -RelativeStage 'development/hardware kernel/stage' -Verification {
    Test-FilesMatch -Pairs @(
        @('development/hardware kernel/stage/vmlinuz-hardware', 'environment/hardware/boot/vmlinuz-hardware'),
        @('development/hardware kernel/stage/T10Skernel hardware 0.19 settings.txt', 'source/entry/kernel/T10Skernel hardware 0.19 settings.txt'),
        @('development/hardware kernel/stage/modules.tar.zst', 'environment/hardware/modules.tar.zst'),
        @('development/hardware kernel/stage/kernel-release.txt', 'environment/hardware/kernel-release.txt')
    )
}
Remove-MatchingStage -RelativeStage 'development/virtualbox runtime/stage' -Verification {
    Test-FilesMatch -Pairs @(
        @('development/virtualbox runtime/stage/catalogue/catalogue.json', 'source/catalogue/virtualbox/catalogue.json'),
        @('development/virtualbox runtime/stage/catalogue/licence GPL-3.0.txt', 'source/catalogue/virtualbox/licence GPL-3.0.txt'),
        @('development/virtualbox runtime/stage/software/VBoxDRMClient', 'source/software/virtualbox/VBoxDRMClient'),
        @('development/virtualbox runtime/stage/software/VBoxT1Clipboard', 'source/software/virtualbox/VBoxT1Clipboard'),
        @('development/virtualbox runtime/stage/software/VBoxT1Service', 'source/software/virtualbox/VBoxT1Service')
    )
}

foreach ($relative in @(
    'development/hardware firmware stage',
    'development/hardware initramfs stage',
    'development/__pycache__',
    'scripts/tests/.test-state',
    'scripts/roothealth-repair/.journal-integration-v2-work',
    'environment/software/backups/storage_20260720_030520_0.28.img',
    'environment/software/extracted logs',
    'environment/software/build-and-run.log',
    'environment/software/qemu_debug.log',
    'environment/software/vbox-serial.log',
    'environment/software/vmware-serial.log',
    'environment/software/t1os-vm-test-serial.log',
    'environment/software/t1os-vm-test-report.json',
    'environment/software/bootiso_debug.log'
)) {
    Remove-ProjectTarget -Path (Join-Path $projectRoot $relative) -Reason 'obsolete, cached, or diagnostic workspace data'
}

Get-ChildItem -LiteralPath (Join-Path $projectRoot 'scripts') -Recurse -Force -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue |
    Sort-Object FullName -Descending |
    ForEach-Object { Remove-ProjectTarget -Path $_.FullName -Reason 'Python bytecode cache' }

Remove-GitIgnoredBuildProducts -RelativePath 'development/roothealth/engine'

$pythonVerifier = Join-Path $projectRoot 'development/promote python 3.14 runtime.py'
$pythonVerification = @(& python $pythonVerifier verify 2>&1)
if ($LASTEXITCODE -ne 0) {
    Add-ProtectedPath -Path (Join-Path $projectRoot 'development/python 3.14 candidate') -Reason "Python release verification failed: $($pythonVerification -join ' ')"
    Add-ProtectedPath -Path (Join-Path $projectRoot 'development/python 3.14 promotion') -Reason 'retained until Python release verification succeeds'
}
else {
    Add-ProtectedPath -Path (Join-Path $projectRoot 'development/python 3.14 candidate') -Reason 'latest reusable CPython build and packaged candidate'
    Add-ProtectedPath -Path (Join-Path $projectRoot 'development/python 3.14 promotion') -Reason 'historical recovery data; remove only through the promotion retention workflow'
}

Remove-ElectronPackaging -ProjectRelative 'software/command centre' `
    -PortableRelative 'software/command centre/release/T1OS Command Centre Portable.exe' `
    -RetainedRelative 'command_centre.exe'
Remove-ElectronPackaging -ProjectRelative 'software/usb flasher' `
    -PortableRelative 'software/usb flasher/release/The One OS USB Flasher Portable.exe' `
    -RetainedRelative 't1os_usb_flasher.exe'

if (-not $SkipUbuntu) {
    Invoke-UbuntuCleanup
}

Assert-RetainedProducts
$summary = [pscustomobject]@{
    mode = $mode
    project = $projectRoot
    planned_bytes = $plannedBytes
    removed_bytes = $removedBytes
    planned_gib = [math]::Round($plannedBytes / 1GB, 2)
    removed_gib = [math]::Round($removedBytes / 1GB, 2)
    windows_actions = $actions.Count
    protected = @($protected)
}
Write-Host 'CLEANUP SUMMARY' -ForegroundColor Cyan
$summary | ConvertTo-Json -Depth 4
