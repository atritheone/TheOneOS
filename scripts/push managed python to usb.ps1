[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param(
    [switch]$ValidateTargetOnly,
    [switch]$Candidate314
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Path $PSScriptRoot -Parent
if ($Candidate314) {
    throw (
        'Python candidate roots are non-deployable because they contain a generated ' +
        'snapshot of /the one/build. Package and promote the candidate, then deploy ' +
        'the canonical verified Python release instead.'
    )
}
$pythonManifestPath = Join-Path $projectRoot 'source\software\python\manifest.json'
$pythonReleaseLockPath = Join-Path $projectRoot 'source\python\locks\release.json'
$pythonVerifierPath = Join-Path $PSScriptRoot 'test python runtime.ps1'
$rootPushPath = Join-Path $PSScriptRoot 'push to disk.ps1'
$candidateRoot = Join-Path $projectRoot 'development\python 3.14 candidate\t1os'
$candidateManifestPath = Join-Path $candidateRoot 'manifest.json'

function Invoke-T1OSPowerShellScript {
    param(
        [Parameter(Mandatory)]
        [string]$Path,

        [string[]]$Arguments = @()
    )

    & pwsh -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass `
        -File $Path @Arguments
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "T1OS workflow script failed with exit code $exitCode`: $Path"
    }
}

function Get-T1OSPythonUsbTarget {
    $volume = Get-Volume -DriveLetter D -ErrorAction Stop
    $partition = Get-Partition -DriveLetter D -ErrorAction Stop
    $disk = $partition | Get-Disk -ErrorAction Stop
    $efi = @(
        Get-Partition -DiskNumber $disk.Number -ErrorAction Stop |
            Where-Object {
                $_.GptType -ceq '{c12a7328-f81f-11d2-ba4b-00a0c93ec93b}' -and
                $_.Size -eq 536870912
            }
    )

    $requiredPaths = @(
        'D:\autorun.inf',
        'D:\boot',
        'D:\the one\build',
        'D:\the one\resources\t1os-drive.ico',
        'D:\the one\settings\runtime paths.json'
    )
    $missingPaths = @(
        $requiredPaths | Where-Object { -not (Test-Path -LiteralPath $_) }
    )
    $autorun = if (Test-Path -LiteralPath 'D:\autorun.inf' -PathType Leaf) {
        Get-Content -LiteralPath 'D:\autorun.inf' -Raw
    }
    else {
        ''
    }

    if (
        [string]$disk.BusType -cne 'USB' -or
        $disk.IsBoot -or
        $disk.IsSystem -or
        $disk.IsReadOnly -or
        [string]$volume.FileSystemType -cne 'NTFS' -or
        [string]$volume.HealthStatus -cne 'Healthy' -or
        -not ([string]$volume.FileSystemLabel).StartsWith(
            'T1OS',
            [StringComparison]::OrdinalIgnoreCase
        ) -or
        $efi.Count -ne 1 -or
        $missingPaths.Count -ne 0 -or
        $autorun -notmatch '(?im)^\s*Label=T1OS(?:\s|$)' -or
        $autorun -notmatch '(?im)^\s*Icon="the one\\resources\\t1os-drive\.ico"\s*$'
    ) {
        throw 'D: is not the exact healthy T1OS GPT USB target.'
    }

    [pscustomobject]@{
        DriveLetter = 'D'
        Label = ([string]$volume.FileSystemLabel).Trim()
        DiskNumber = [int]$disk.Number
        DiskUniqueId = ([string]$disk.UniqueId).Trim()
        DiskSerial = ([string]$disk.SerialNumber).Trim()
        DiskModel = ([string]$disk.FriendlyName).Trim()
        PartitionNumber = [int]$partition.PartitionNumber
        PartitionGuid = ([string]$partition.Guid).Trim()
        EfiPartitionNumber = [int]$efi[0].PartitionNumber
    }
}

function Assert-SameT1OSPythonUsbTarget {
    param(
        [Parameter(Mandatory)]$Expected,
        [Parameter(Mandatory)]$Actual
    )

    foreach ($property in @(
        'DriveLetter',
        'DiskNumber',
        'DiskUniqueId',
        'DiskSerial',
        'PartitionNumber',
        'PartitionGuid',
        'EfiPartitionNumber'
    )) {
        if ([string]$Expected.$property -cne [string]$Actual.$property) {
            throw "The T1OS USB target identity changed at property $property."
        }
    }
}

function Remove-T1OSWindowsTransactionTree {
    param([Parameter(Mandatory)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }
    & attrib.exe -R -S -H $Path /S /D 2>$null
    & attrib.exe -R -S -H (Join-Path $Path '*') /S /D 2>$null
    Remove-Item -LiteralPath $Path -Recurse -Force
}

function Undo-T1OSWindowsManagedMirror {
    param([Parameter(Mandatory)][object[]]$Transactions)

    $reverseTransactions = @($Transactions)
    [array]::Reverse($reverseTransactions)
    foreach ($transaction in $reverseTransactions) {
        try {
            if ($transaction.Swapped) {
                $failed = "$($transaction.Stage).failed"
                if (Test-Path -LiteralPath $failed) {
                    Remove-T1OSWindowsTransactionTree -Path $failed
                }
                if (Test-Path -LiteralPath $transaction.Destination) {
                    Move-Item -LiteralPath $transaction.Destination -Destination $failed
                }
                if ($transaction.HadDestination -and (Test-Path -LiteralPath $transaction.Backup)) {
                    Move-Item -LiteralPath $transaction.Backup -Destination $transaction.Destination
                }
                if (Test-Path -LiteralPath $failed) {
                    Remove-T1OSWindowsTransactionTree -Path $failed
                }
            }
            elseif ($transaction.LiveMovedToBackup) {
                $failed = "$($transaction.Stage).failed"
                if (Test-Path -LiteralPath $failed) {
                    Remove-T1OSWindowsTransactionTree -Path $failed
                }
                if (Test-Path -LiteralPath $transaction.Destination) {
                    Move-Item -LiteralPath $transaction.Destination -Destination $failed
                }
                if (-not (Test-Path -LiteralPath $transaction.Backup -PathType Container)) {
                    throw "The rollback backup disappeared: $($transaction.Backup)"
                }
                Move-Item -LiteralPath $transaction.Backup -Destination $transaction.Destination
                if (Test-Path -LiteralPath $failed) {
                    Remove-T1OSWindowsTransactionTree -Path $failed
                }
            }
            elseif (Test-Path -LiteralPath $transaction.Stage) {
                Remove-T1OSWindowsTransactionTree -Path $transaction.Stage
            }
        }
        catch {
            Write-Warning "Could not fully roll back $($transaction.Label): $($_.Exception.Message)"
        }
    }
}

function Complete-T1OSWindowsManagedMirror {
    param([Parameter(Mandatory)][object[]]$Transactions)

    foreach ($transaction in $Transactions) {
        if (Test-Path -LiteralPath $transaction.Backup) {
            Remove-T1OSWindowsTransactionTree -Path $transaction.Backup
        }
        if (Test-Path -LiteralPath $transaction.Stage) {
            Remove-T1OSWindowsTransactionTree -Path $transaction.Stage
        }
    }
}

function Merge-T1OSInstalledPythonPackages {
    param(
        [Parameter(Mandatory)][string]$UsbRoot,
        [Parameter(Mandatory)][object[]]$Transactions
    )

    $liveSoftware = Join-Path $UsbRoot 'the one\software\python'
    $stateRoot = Join-Path $liveSoftware '.t1pip'
    $statePath = Join-Path $stateRoot 'state.json'
    if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) {
        return
    }
    try {
        $state = Get-Content -LiteralPath $statePath -Raw |
            ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        throw "The installed Python module state is unreadable: $($_.Exception.Message)"
    }
    if (
        [int]$state.format -ne 2 -or
        $null -eq $state.files -or
        $null -eq $state.catalogue_files
    ) {
        throw 'The installed Python module state has an unsupported format.'
    }
    $softwareTransaction = @($Transactions | Where-Object Label -ceq 'Python software')
    $catalogueTransaction = @($Transactions | Where-Object Label -ceq 'Python catalogue')
    if ($softwareTransaction.Count -ne 1 -or $catalogueTransaction.Count -ne 1) {
        throw 'The managed Python mirror has no unique software/catalogue transaction.'
    }

    function Copy-OwnedT1OSPythonFile {
        param(
            [Parameter(Mandatory)][string]$SourceRoot,
            [Parameter(Mandatory)][string]$StageRoot,
            [Parameter(Mandatory)][string]$Relative,
            [Parameter(Mandatory)][long]$Size,
            [Parameter(Mandatory)][string]$Sha256
        )
        $relativeParts = $Relative.Replace('/', '\').Split('\')
        if (
            [string]::IsNullOrWhiteSpace($Relative) -or
            [IO.Path]::IsPathRooted($Relative) -or
            $relativeParts -contains '..' -or
            $relativeParts -contains '.' -or
            $Sha256 -cnotmatch '^[0-9a-f]{64}$'
        ) {
            throw "Unsafe path in installed Python module state: $Relative"
        }
        $source = Join-Path $SourceRoot ($relativeParts -join '\')
        $destination = Join-Path $StageRoot ($relativeParts -join '\')
        $sourceItem = Get-Item -LiteralPath $source -Force -ErrorAction Stop
        if (
            $sourceItem.PSIsContainer -or
            $sourceItem.Attributes.HasFlag([IO.FileAttributes]::ReparsePoint) -or
            $sourceItem.Length -ne $Size -or
            (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant() -cne $Sha256
        ) {
            throw "An installed Python module file differs from its state: $Relative"
        }
        if (Test-Path -LiteralPath $destination) {
            throw "An installed package collides with the new system Python: $Relative"
        }
        New-Item -ItemType Directory -Path (Split-Path $destination -Parent) -Force | Out-Null
        Copy-Item -LiteralPath $source -Destination $destination
    }

    foreach ($record in @($state.files)) {
        $area = [string]$record.area
        $relative = [string]$record.path
        if ($area -ceq 'site') {
            $prefix = 'lib\python3.14\site-packages'
        }
        elseif ($area -ceq 'bin') {
            $prefix = 'bin'
        }
        else {
            throw "Unknown installed Python module area: $area"
        }
        Copy-OwnedT1OSPythonFile `
            -SourceRoot (Join-Path $liveSoftware $prefix) `
            -StageRoot (Join-Path $softwareTransaction[0].Stage $prefix) `
            -Relative $relative -Size ([long]$record.size) `
            -Sha256 ([string]$record.sha256)
    }
    $liveCatalogue = Join-Path $UsbRoot 'the one\catalogue\python'
    foreach ($record in @($state.catalogue_files)) {
        Copy-OwnedT1OSPythonFile `
            -SourceRoot $liveCatalogue `
            -StageRoot $catalogueTransaction[0].Stage `
            -Relative ([string]$record.path) -Size ([long]$record.size) `
            -Sha256 ([string]$record.sha256)
    }

    $unsafeState = @(
        Get-ChildItem -LiteralPath $stateRoot -Force -Recurse |
            Where-Object { $_.Attributes.HasFlag([IO.FileAttributes]::ReparsePoint) }
    )
    if ($unsafeState.Count) {
        throw "The Python module state contains a reparse point: $($unsafeState[0].FullName)"
    }
    $stateStage = Join-Path $softwareTransaction[0].Stage '.t1pip'
    New-Item -ItemType Directory -Path $stateStage -Force | Out-Null
    $output = & robocopy.exe $stateRoot $stateStage /E /COPY:DAT /DCOPY:DAT `
        /XD transactions /R:2 /W:1 /XJ /NFL /NDL /NJH /NJS /NP
    $exit = $LASTEXITCODE
    $output | Out-Host
    if ($exit -ge 8) {
        throw "Could not preserve the installed Python module state (robocopy exit $exit)."
    }
    Write-Host (
        "Preserved $(@($state.files).Count) installed Python file(s) and " +
        "$(@($state.catalogue_files).Count) patched catalogue file(s)."
    )
}

function Start-T1OSWindowsManagedMirror {
    param(
        [Parameter(Mandatory)]
        [string]$UsbRoot,

        [Parameter(Mandatory)]
        [hashtable]$SourceRoots
    )

    if (-not (Get-Command robocopy.exe -ErrorAction SilentlyContinue)) {
        throw 'Required Windows copy command not found: robocopy.exe'
    }
    $maintenanceSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value

    foreach ($parent in @(
        (Join-Path $UsbRoot 'the one'),
        (Join-Path $UsbRoot 'the one\software'),
        (Join-Path $UsbRoot 'the one\catalogue'),
        (Join-Path $UsbRoot 'boot')
    )) {
        foreach ($orphan in @(
            Get-ChildItem -LiteralPath $parent -Directory -Force -ErrorAction Stop |
                Where-Object {
                    $_.Name -cmatch '^\.(?:python|image|build|virtualbox|boot animation)\.t1os-[0-9a-f]{32}\.stage\.failed$'
                }
        )) {
            Write-Host "Removing verified failed-transaction payload $($orphan.FullName)..."
            Remove-T1OSWindowsTransactionTree -Path $orphan.FullName
        }
    }

    $mappings = @(
        [pscustomobject]@{
            Label = 'Python software'
            Source = $SourceRoots.Software
            Destination = Join-Path $UsbRoot 'the one\software\python'
            ExcludeGenerated = $false
        },
        [pscustomobject]@{
            Label = 'Python catalogue'
            Source = $SourceRoots.Catalogue
            Destination = Join-Path $UsbRoot 'the one\catalogue\python'
            ExcludeGenerated = $false
        },
        [pscustomobject]@{
            Label = 'image catalogue'
            Source = $SourceRoots.Image
            Destination = Join-Path $UsbRoot 'the one\catalogue\image'
            ExcludeGenerated = $false
        }
    )
    if ($SourceRoots.ContainsKey('BuildSoftware')) {
        $mappings += [pscustomobject]@{
            Label = 'Python userspace callers'
            Source = $SourceRoots.BuildSoftware
            Destination = Join-Path $UsbRoot 'the one\build'
            ExcludeGenerated = $true
        }
    }
    if ($SourceRoots.ContainsKey('Boot')) {
        $mappings += [pscustomobject]@{
            Label = 'Python boot callers'
            Source = Join-Path $SourceRoots.Boot 'boot animation'
            Destination = Join-Path $UsbRoot 'boot\boot animation'
            ExcludeGenerated = $true
            TransactionParent = Join-Path $UsbRoot 'the one'
        }
    }
    if ($SourceRoots.ContainsKey('VirtualBoxSoftware')) {
        $mappings += [pscustomobject]@{
            Label = 'VirtualBox Python callers'
            Source = $SourceRoots.VirtualBoxSoftware
            Destination = Join-Path $UsbRoot 'the one\software\virtualbox'
            ExcludeGenerated = $true
        }
    }

    $transactionId = [guid]::NewGuid().ToString('N')
    $transactions = [System.Collections.Generic.List[object]]::new()
    try {
      foreach ($mapping in $mappings) {
        if (-not (Test-Path -LiteralPath $mapping.Source -PathType Container)) {
            throw "Managed source root is missing: $($mapping.Source)"
        }
        $hadDestination = Test-Path -LiteralPath $mapping.Destination
        if ($hadDestination) {
            $destinationItem = Get-Item -LiteralPath $mapping.Destination -Force
            if (
                -not $destinationItem.PSIsContainer -or
                $destinationItem.Attributes.HasFlag(
                    [System.IO.FileAttributes]::ReparsePoint
                )
            ) {
                throw "Managed USB destination is not a real directory: $($mapping.Destination)"
            }
        }

        $parent = if ($mapping.PSObject.Properties.Name -contains 'TransactionParent') {
            $mapping.TransactionParent
        }
        else {
            Split-Path -Path $mapping.Destination -Parent
        }
        $leaf = Split-Path -Path $mapping.Destination -Leaf
        $stage = Join-Path $parent ".$leaf.t1os-$transactionId.stage"
        $backup = Join-Path $parent ".$leaf.t1os-$transactionId.backup"
        if ((Test-Path -LiteralPath $stage) -or (Test-Path -LiteralPath $backup)) {
            throw "Reserved managed-update path already exists beside $($mapping.Destination)."
        }
        New-Item -ItemType Directory -Path $stage | Out-Null
        $transactions.Add([pscustomobject]@{
            Label = $mapping.Label
            Destination = $mapping.Destination
            Stage = $stage
            Backup = $backup
            HadDestination = $hadDestination
            LiveMovedToBackup = $false
            Swapped = $false
        })
        # The one-time migration grants permission to create a sibling stage.
        # Some legacy T1OS parent ACLs do not pass that ACE to new children, but
        # the creating Windows identity owns the new directory and can safely
        # grant itself inheritable access without elevation.
        & icacls.exe $stage /grant:r "*$maintenanceSid`:(OI)(CI)(M)" /Q | Out-Host
        if ($LASTEXITCODE -ne 0) {
            throw "Could not initialize the owned staging ACL for $($mapping.Label)."
        }

        $arguments = @(
            $mapping.Source,
            $stage,
            '/MIR',
            '/COPY:DAT',
            '/DCOPY:DAT',
            '/R:2',
            '/W:1',
            '/XJ',
            '/NFL',
            '/NDL',
            '/NJH',
            '/NJS',
            '/NP'
        )
        if ($mapping.ExcludeGenerated) {
            $arguments += @('/XD', '__pycache__', '/XF', '*.pyc', '*.pyo')
        }
        Write-Host "Staging $($mapping.Label) through the Windows NTFS path..."
        $robocopyOutput = & robocopy.exe @arguments
        $robocopyExit = $LASTEXITCODE
        $robocopyOutput | Out-Host
        if (
            $robocopyExit -ge 8 -or
            ($robocopyOutput -join "`n") -match '(?im)^\s*ERROR\s+[0-9]+'
        ) {
            Remove-T1OSWindowsTransactionTree -Path $stage
            throw (
                "Windows staging failed for $($mapping.Label) " +
                "(robocopy exit $robocopyExit)."
            )
        }
      }
      Merge-T1OSInstalledPythonPackages `
          -UsbRoot $UsbRoot -Transactions $transactions.ToArray()
    }
    catch {
        Undo-T1OSWindowsManagedMirror -Transactions $transactions.ToArray()
        throw
    }

    try {
        foreach ($transaction in $transactions) {
            if ($transaction.HadDestination) {
                Move-Item -LiteralPath $transaction.Destination -Destination $transaction.Backup
                $transaction.LiveMovedToBackup = $true
            }
            Move-Item -LiteralPath $transaction.Stage -Destination $transaction.Destination
            $transaction.Swapped = $true
            Write-Host "Activated staged $($transaction.Label)."
        }
    }
    catch {
        Undo-T1OSWindowsManagedMirror -Transactions $transactions.ToArray()
        throw
    }

    return ,$transactions.ToArray()
}

function Assert-T1OSCandidate314Payload {
    param(
        [Parameter(Mandatory)][string]$Root,
        [Parameter(Mandatory)][string]$ManifestPath,
        [switch]$AllowOneDrivePlaceholders,
        [switch]$UsbLayout
    )

    try {
        $candidate = Get-Content -LiteralPath $ManifestPath -Raw |
            ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        throw "The Python 3.14 candidate manifest is malformed: $($_.Exception.Message)"
    }
    if (
        [string]$candidate.component -cne 't1os-python-candidate' -or
        [string]$candidate.candidate_release -cne '3.14.7-t1os-candidate.5' -or
        [string]$candidate.python_version -cne '3.14.7' -or
        [string]$candidate.python_abi -cne 'cp314' -or
        [bool]$candidate.promotable
    ) {
        throw 'The staged payload is not the verified Python 3.14.7 candidate.'
    }

    $areas = @(
        [pscustomobject]@{ Name = 'software'; Relative = 'software\python'; EmbeddedManifest = $true },
        [pscustomobject]@{ Name = 'catalogue'; Relative = 'catalogue\python'; EmbeddedManifest = $false },
        [pscustomobject]@{ Name = 'image'; Relative = 'catalogue\image'; EmbeddedManifest = $false },
        [pscustomobject]@{ Name = 'build_software'; Relative = 'build'; EmbeddedManifest = $false },
        [pscustomobject]@{ Name = 'boot'; Relative = 'boot'; EmbeddedManifest = $false },
        [pscustomobject]@{ Name = 'virtualbox_software'; Relative = 'software\virtualbox'; EmbeddedManifest = $false }
    )
    $externalManifestHash = (
        Get-FileHash -LiteralPath $ManifestPath -Algorithm SHA256
    ).Hash.ToLowerInvariant()

    foreach ($area in $areas) {
        $areaRoot = if ($UsbLayout -and $area.Name -ceq 'boot') {
            Join-Path (Split-Path -Path $Root -Parent) 'boot'
        }
        else {
            Join-Path $Root $area.Relative
        }
        if (-not (Test-Path -LiteralPath $areaRoot -PathType Container)) {
            throw "Candidate payload root is missing: $areaRoot"
        }
        $rootItem = Get-Item -LiteralPath $areaRoot -Force
        if (
            $rootItem.Attributes.HasFlag([System.IO.FileAttributes]::ReparsePoint) -and
            (
                -not $AllowOneDrivePlaceholders -or
                -not [string]::IsNullOrEmpty([string]$rootItem.LinkType) -or
                $null -ne $rootItem.Target
            )
        ) {
            throw "Candidate payload root is a reparse point: $areaRoot"
        }
        $records = @($candidate.payloads.($area.Name))
        $expected = [Collections.Generic.Dictionary[string, object]]::new(
            [StringComparer]::Ordinal
        )
        foreach ($record in $records) {
            $relative = ([string]$record.path).Replace('\', '/')
            if (
                [string]::IsNullOrWhiteSpace($relative) -or
                $relative.StartsWith('/') -or
                $relative.Split('/') -contains '..' -or
                $expected.ContainsKey($relative)
            ) {
                throw "Unsafe or duplicate candidate manifest path: $relative"
            }
            $expected.Add($relative, $record)
        }
        if ($area.EmbeddedManifest) {
            $expected.Add('manifest.json', [pscustomobject]@{
                path = 'manifest.json'
                size = (Get-Item -LiteralPath $ManifestPath).Length
                sha256 = $externalManifestHash
            })
        }

        $actual = @(
            Get-ChildItem -LiteralPath $areaRoot -File -Force -Recurse |
                Sort-Object FullName
        )
        $unsafe = @(
            Get-ChildItem -LiteralPath $areaRoot -Force -Recurse |
                Where-Object {
                    $_.Attributes.HasFlag([System.IO.FileAttributes]::ReparsePoint) -and
                    (
                        -not $AllowOneDrivePlaceholders -or
                        -not [string]::IsNullOrEmpty([string]$_.LinkType) -or
                        $null -ne $_.Target
                    )
                }
        )
        if ($unsafe.Count -ne 0) {
            throw "Candidate payload contains a reparse point: $($unsafe[0].FullName)"
        }
        if ($actual.Count -ne $expected.Count) {
            throw (
                "Candidate $($area.Name) inventory count differs: " +
                "expected $($expected.Count), found $($actual.Count)."
            )
        }
        foreach ($file in $actual) {
            $relative = [IO.Path]::GetRelativePath($areaRoot, $file.FullName).Replace('\', '/')
            if (-not $expected.ContainsKey($relative)) {
                throw "Unexpected candidate payload file: $($area.Name)/$relative"
            }
            $record = $expected[$relative]
            if ($file.Length -ne [long]$record.size) {
                throw "Candidate payload size differs: $($area.Name)/$relative"
            }
            $digest = (
                Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256
            ).Hash.ToLowerInvariant()
            if ($digest -cne [string]$record.sha256) {
                throw "Candidate payload hash differs: $($area.Name)/$relative"
            }
        }
    }

    return $candidate
}

function Invoke-T1OSCandidate314UsbSmoke {
    param([Parameter(Mandatory)][string]$ExpectedManifestHash)

    $script = @'
set -euo pipefail
expected_manifest=$1
mount_point="/tmp/t1os-python314-usb-$$"
mkdir "$mount_point"
cleanup() {
    status=$?
    mountpoint -q "$mount_point" && umount "$mount_point" || true
    rmdir "$mount_point" 2>/dev/null || true
    exit "$status"
}
trap cleanup EXIT HUP INT TERM
mount -t drvfs D: "$mount_point"
root="$mount_point/the one"
loader="$root/catalogue/python/ld-linux-x86-64.so.2"
python="$root/software/python/bin/python"
compatibility_python="$root/software/python/bin/python3.13"
image="$root/catalogue/image"
libraries="$image/pillow.libs:$image:$root/catalogue/python"

test "$(sha256sum "$root/software/python/manifest.json" | awk '{print $1}')" = "$expected_manifest"
PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PYTHONPATH= \
    "$loader" --library-path "$libraries" "$python" -B -P - "$image" <<'PY'
import json, ssl, sqlite3, sys
sys.path.insert(0, sys.argv[1])
import PIL, freetype, pyroute2
result = {
    "python": sys.version.split()[0],
    "pillow": PIL.__version__,
    "freetype": ".".join(map(str, freetype.version())),
    "pyroute2": pyroute2.__version__,
    "openssl": ssl.OPENSSL_VERSION,
    "sqlite": sqlite3.sqlite_version,
    "safe_path": bool(sys.flags.safe_path),
    "dont_write_bytecode": bool(sys.dont_write_bytecode),
}
print(json.dumps(result, sort_keys=True))
assert result["python"] == "3.14.7", result
assert result["pillow"] == "12.3.0", result
assert result["pyroute2"] == "0.9.4", result
assert result["safe_path"] and result["dont_write_bytecode"], result
PY
test "$(PYTHONDONTWRITEBYTECODE=1 "$loader" --library-path "$libraries" \
    "$compatibility_python" -B -P -c 'import sys; print(sys.version.split()[0])')" = '3.14.7'
umount "$mount_point"
rmdir "$mount_point"
trap - EXIT HUP INT TERM
'@
    & wsl.exe -d Ubuntu -u root --exec bash -c $script bash $ExpectedManifestHash
    if ($LASTEXITCODE -ne 0) {
        throw "The Python 3.14 candidate failed its live USB smoke test (exit $LASTEXITCODE)."
    }
}

$requiredFiles = if ($Candidate314) {
    @($candidateManifestPath, $rootPushPath)
}
else {
    @($pythonManifestPath, $pythonReleaseLockPath, $pythonVerifierPath, $rootPushPath)
}
foreach ($requiredFile in $requiredFiles) {
    if (-not (Test-Path -LiteralPath $requiredFile -PathType Leaf)) {
        throw "Required managed-Python USB input not found: $requiredFile"
    }
}

if ($Candidate314) {
    $manifest = Assert-T1OSCandidate314Payload -Root $candidateRoot `
        -ManifestPath $candidateManifestPath -AllowOneDrivePlaceholders
    $manifestHash = (
        Get-FileHash -LiteralPath $candidateManifestPath -Algorithm SHA256
    ).Hash.ToLowerInvariant()
    $release = [string]$manifest.candidate_release
    $sourceRoots = @{
        Software = Join-Path $candidateRoot 'software\python'
        Catalogue = Join-Path $candidateRoot 'catalogue\python'
        Image = Join-Path $candidateRoot 'catalogue\image'
        BuildSoftware = Join-Path $candidateRoot 'build'
        Boot = Join-Path $candidateRoot 'boot'
        VirtualBoxSoftware = Join-Path $candidateRoot 'software\virtualbox'
    }
}
else {
    try {
        $manifest = Get-Content -LiteralPath $pythonManifestPath -Raw |
            ConvertFrom-Json -ErrorAction Stop
        $releaseLock = Get-Content -LiteralPath $pythonReleaseLockPath -Raw |
            ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        throw "The managed Python manifest or release lock is malformed: $($_.Exception.Message)"
    }
    $manifestHash = (
        Get-FileHash -LiteralPath $pythonManifestPath -Algorithm SHA256
    ).Hash.ToLowerInvariant()
    $release = [string]$releaseLock.release
    if (
        [string]$manifest.state -cne 'verified' -or
        [string]$manifest.release -cne $release -or
        $release -notmatch '^[0-9A-Za-z][0-9A-Za-z._+-]{0,127}$' -or
        [string]$releaseLock.outputs.manifest_sha256 -cne $manifestHash
    ) {
        throw 'The managed Python source is not the immutable verified release.'
    }
    $sourceRoots = @{
        Software = Join-Path $projectRoot 'source\software\python'
        Catalogue = Join-Path $projectRoot 'source\catalogue\python'
        Image = Join-Path $projectRoot 'source\catalogue\image'
        BuildSoftware = Join-Path $projectRoot 'source\build software'
        Boot = Join-Path $projectRoot 'source\boot'
        VirtualBoxSoftware = Join-Path $projectRoot 'source\software\virtualbox'
    }
}

$target = Get-T1OSPythonUsbTarget
Write-Host "Managed Python release: $release"
Write-Host "Manifest SHA-256: $manifestHash"
Write-Host (
    "T1OS USB target: D: '$($target.Label)' on USB disk " +
    "$($target.DiskNumber) $($target.DiskModel), serial $($target.DiskSerial)"
)

# Reuse the root deployer's independent target validator before it is allowed
# to write to the physical device. This workflow deliberately never touches the
# hidden EFI partition and therefore never requests elevation.
Invoke-T1OSPowerShellScript -Path $rootPushPath -Arguments @(
    '-UsbDrive',
    '-ValidateTargetOnly'
)

if ($ValidateTargetOnly) {
    Write-Host 'Managed-Python USB target validation passed; no files were changed.'
    exit 0
}

if (-not $PSCmdlet.ShouldProcess(
    "USB disk $($target.DiskNumber), D:",
    "Synchronise managed Python $release and its package catalogue to the NTFS root"
)) {
    Write-Host 'Managed-Python USB deployment was not executed.'
    exit 0
}

if ($Candidate314) {
    Write-Host 'The exact Python 3.14 candidate payload passed its local inventory gate.'
}
else {
    Write-Host 'Running the frozen Python verifier before opening the target filesystem...'
    Invoke-T1OSPowerShellScript -Path $pythonVerifierPath -Arguments @(
        '-DeploymentPayloadOnly'
    )
}

$targetAfterVerification = Get-T1OSPythonUsbTarget
Assert-SameT1OSPythonUsbTarget -Expected $target -Actual $targetAfterVerification

Write-Host 'Running the no-follow managed-tree preflight before Windows replacement...'
Invoke-T1OSPowerShellScript -Path $rootPushPath -Arguments @(
    '-UsbDrive',
    '-ValidateManagedTreeOnly'
)
$targetAfterPreflight = Get-T1OSPythonUsbTarget
Assert-SameT1OSPythonUsbTarget -Expected $target -Actual $targetAfterPreflight

$mirrorTransactions = Start-T1OSWindowsManagedMirror -UsbRoot 'D:\' -SourceRoots $sourceRoots
try {
    $targetAfterMirror = Get-T1OSPythonUsbTarget
    Assert-SameT1OSPythonUsbTarget -Expected $target -Actual $targetAfterMirror

    Write-Host 'Verifying the mirrored managed release through the T1OS runtime path...'
    if ($Candidate314) {
        Assert-T1OSCandidate314Payload -Root 'D:\the one' `
            -ManifestPath 'D:\the one\software\python\manifest.json' -UsbLayout | Out-Null
        Invoke-T1OSCandidate314UsbSmoke -ExpectedManifestHash $manifestHash
    }
    else {
        Invoke-T1OSPowerShellScript -Path $rootPushPath -Arguments @(
            '-UsbDrive',
            '-VerifyManagedReleaseOnly'
        )
    }
    Complete-T1OSWindowsManagedMirror -Transactions $mirrorTransactions
}
catch {
    Undo-T1OSWindowsManagedMirror -Transactions $mirrorTransactions
    throw
}

$targetAfterRootPush = Get-T1OSPythonUsbTarget
Assert-SameT1OSPythonUsbTarget -Expected $target -Actual $targetAfterRootPush
Invoke-T1OSPowerShellScript -Path $rootPushPath -Arguments @(
    '-UsbDrive',
    '-ValidateTargetOnly'
)

$volume = Get-Volume -DriveLetter D -ErrorAction Stop
if (
    [string]$volume.FileSystemType -cne 'NTFS' -or
    [string]$volume.HealthStatus -cne 'Healthy'
) {
    throw 'The T1OS USB root did not remain a healthy NTFS volume after deployment.'
}

Write-Host ''
Write-Host "Managed Python $release was deployed and verified on the T1OS USB."
Write-Host 'No UAC prompt was used and the hidden EFI partition was not changed.'
if (-not $Candidate314) {
    Write-Host (
        'Before hardware boot, install the separately verified matching initramfs with ' +
        'scripts\push hardware kernel to usb.ps1 -BootFilesOnly.'
    )
}
exit 0
