[CmdletBinding()]
param(
    [switch]$Elevated,

    [int]$ExpectedDiskNumber = -1,

    [string]$ExpectedDiskSerial = '',

    [string]$WindowsUserSid = '',

    [string]$DiagnosticPath = ''
)

$ErrorActionPreference = 'Stop'
$scriptPath = $MyInvocation.MyCommand.Path
trap {
    if ($Elevated -and -not [string]::IsNullOrWhiteSpace($DiagnosticPath)) {
        try {
        [IO.File]::WriteAllText(
            $DiagnosticPath,
            ($_ | Out-String),
            [Text.UTF8Encoding]::new($false)
        )
        }
        catch {
            # The original failure remains authoritative if diagnostics cannot
            # be persisted.
        }
        exit 1
    }
    break
}

function Get-T1OSManagedPythonUsbTarget {
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
        -not (Test-Path -LiteralPath 'D:\autorun.inf' -PathType Leaf) -or
        -not (Test-Path -LiteralPath 'D:\the one\software\python' -PathType Container) -or
        -not (Test-Path -LiteralPath 'D:\the one\catalogue\python' -PathType Container)
    ) {
        throw 'D: is not the exact healthy T1OS GPT USB target.'
    }

    [pscustomobject]@{
        DiskNumber = [int]$disk.Number
        DiskSerial = ([string]$disk.SerialNumber).Trim()
        Label = ([string]$volume.FileSystemLabel).Trim()
        Model = ([string]$disk.FriendlyName).Trim()
    }
}

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

$target = Get-T1OSManagedPythonUsbTarget
if (-not $Elevated) {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $sid = $identity.User.Value
    Write-Host (
        "One-time managed-system ACL migration target: D: '$($target.Label)' " +
        "on USB disk $($target.DiskNumber) $($target.Model), serial $($target.DiskSerial)"
    )
    Write-Host "Windows maintenance identity: $($identity.Name) ($sid)"
    $diagnosticPath = Join-Path (
        [IO.Path]::GetTempPath()
    ) "t1os-python-acl-$([guid]::NewGuid().ToString('N')).log"

    $quote = {
        param([string]$Value)
        "'" + $Value.Replace("'", "''") + "'"
    }
    $elevatedCommand = (
        "& $(& $quote $scriptPath) -Elevated " +
        "-ExpectedDiskNumber $($target.DiskNumber) " +
        "-ExpectedDiskSerial $(& $quote $target.DiskSerial) " +
        "-WindowsUserSid $(& $quote $sid) " +
        "-DiagnosticPath $(& $quote $diagnosticPath)"
    )
    $encodedCommand = [Convert]::ToBase64String(
        [Text.Encoding]::Unicode.GetBytes($elevatedCommand)
    )
    $arguments = @(
        '-NoLogo',
        '-NoProfile',
        '-NonInteractive',
        '-ExecutionPolicy',
        'Bypass',
        '-EncodedCommand',
        $encodedCommand
    )
    try {
        $process = Start-Process -FilePath 'pwsh.exe' -Verb RunAs -Wait -PassThru `
            -WindowStyle Hidden -ArgumentList $arguments
    }
    catch {
        throw "The one-time ACL migration was not elevated: $($_.Exception.Message)"
    }
    if ($process.ExitCode -ne 0) {
        $detail = if (Test-Path -LiteralPath $diagnosticPath -PathType Leaf) {
            (Get-Content -LiteralPath $diagnosticPath -Raw).Trim()
        }
        else {
            'The elevated child did not produce a diagnostic record.'
        }
        if (Test-Path -LiteralPath $diagnosticPath) {
            Remove-Item -LiteralPath $diagnosticPath -Force
        }
        throw (
            "The elevated ACL migration failed (exit code $($process.ExitCode)): " +
            $detail
        )
    }
    if (Test-Path -LiteralPath $diagnosticPath) {
        Remove-Item -LiteralPath $diagnosticPath -Force
    }
    Write-Host 'One-time managed-system USB ACL migration completed.'
    exit 0
}

if (-not (Test-IsAdministrator)) {
    throw 'The ACL migration process does not have an elevated Administrator token.'
}
if ($WindowsUserSid -notmatch '^S-1-5-21-(?:[0-9]+-){3}[0-9]+$') {
    throw 'The requested Windows maintenance SID is malformed.'
}
$elevatedTarget = Get-T1OSManagedPythonUsbTarget
if (
    $elevatedTarget.DiskNumber -ne $ExpectedDiskNumber -or
    $elevatedTarget.DiskSerial -cne $ExpectedDiskSerial
) {
    throw 'The T1OS USB target identity changed before ACL migration.'
}

$bootPath = 'D:\boot'
if (-not (Test-Path -LiteralPath $bootPath)) {
    $bootBackups = @(
        Get-ChildItem -LiteralPath 'D:\the one' -Directory -Force |
            Where-Object { $_.Name -cmatch '^\.boot\.t1os-[0-9a-f]{32}\.backup$' }
    )
    if ($bootBackups.Count -ne 1) {
        throw 'The interrupted boot-tree transaction cannot be recovered unambiguously.'
    }
    $bootBackup = $bootBackups[0]
    Move-Item -LiteralPath $bootBackup.FullName -Destination $bootPath
    $interruptedStage = Join-Path 'D:\the one' (
        $bootBackup.Name.Substring(0, $bootBackup.Name.Length - '.backup'.Length) + '.stage'
    )
    if (Test-Path -LiteralPath $interruptedStage) {
        & attrib.exe -R -S -H $interruptedStage /S /D 2>$null
        & attrib.exe -R -S -H (Join-Path $interruptedStage '*') /S /D 2>$null
        Remove-Item -LiteralPath $interruptedStage -Recurse -Force
    }
    Write-Host 'Recovered the boot tree from the interrupted managed update.'
}

$ancestorPaths = @(
    'D:\the one',
    'D:\the one\software',
    'D:\the one\catalogue',
    'D:\the one\settings',
    'D:\the one\resources'
)
$managedRoots = @(
    'D:\the one\software\python',
    'D:\the one\software\virtualbox',
    'D:\the one\software\audio',
    'D:\the one\software\network',
    'D:\the one\software\chromium',
    'D:\the one\catalogue\python',
    'D:\the one\catalogue\image',
    'D:\the one\catalogue\graphics',
    'D:\the one\catalogue\audio',
    'D:\the one\catalogue\network',
    'D:\the one\build',
    'D:\the one\drivers',
    'D:\the one\settings\virtualbox',
    'D:\the one\settings\network',
    'D:\the one\settings\media',
    'D:\the one\resources\fonts',
    'D:\the one\resources\logos',
    'D:\the one\resources\cursors',
    'D:\the one\resources\system',
    $bootPath
)
foreach ($path in @($ancestorPaths + $managedRoots)) {
    $item = Get-Item -LiteralPath $path -Force -ErrorAction Stop
    if (
        -not $item.PSIsContainer -or
        $item.Attributes.HasFlag([System.IO.FileAttributes]::ReparsePoint)
    ) {
        throw "Managed ACL target is not a real directory: $path"
    }
}

foreach ($path in $ancestorPaths) {
    & icacls.exe $path /grant:r "*$WindowsUserSid`:(M)" /Q | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "Could not grant staging-container access on $path."
    }
}
foreach ($path in $managedRoots) {
    & takeown.exe /F $path /R /D Y | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "Could not take ownership of the legacy managed tree at $path."
    }
    # Existing files need an object ACE of their own: Windows ignores the
    # inheritance-only flags when they are applied to a regular file.
    & icacls.exe $path /grant:r "*$WindowsUserSid`:(M)" /T /Q | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "Could not grant existing managed-object access on $path."
    }
    # Also apply an inheritable maintenance ACE at every level. Legacy
    # protected directories can have inheritance disabled, so a root-only
    # (OI)(CI) ACE is insufficient: rsync staging files created below such a
    # directory would inherit only the old read-only ACL.
    & icacls.exe $path /grant:r "*$WindowsUserSid`:(OI)(CI)(M)" /T /Q | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "Could not grant managed-tree access on $path."
    }
    & icacls.exe $path /grant "*$WindowsUserSid`:(OI)(CI)(M)" /Q | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "Could not grant future-child access on $path."
    }
    & attrib.exe -R -S -H $path /S /D 2>$null
    & attrib.exe -R -S -H (Join-Path $path '*') /S /D 2>$null
}
$verificationPaths = [System.Collections.Generic.List[string]]::new()
foreach ($path in $ancestorPaths) {
    $verificationPaths.Add($path)
}
foreach ($root in $managedRoots) {
    $verificationPaths.Add($root)
    foreach ($item in Get-ChildItem -LiteralPath $root -Force -Recurse -ErrorAction Stop) {
        $verificationPaths.Add($item.FullName)
    }
}
foreach ($path in $verificationPaths) {
    $acl = Get-Acl -LiteralPath $path
    $matching = @(
        $acl.Access | Where-Object {
            try {
                $aceSid = $_.IdentityReference.Translate(
                    [Security.Principal.SecurityIdentifier]
                ).Value
            }
            catch {
                $aceSid = $_.IdentityReference.Value
            }
            $aceSid -ceq $WindowsUserSid -and
            $_.AccessControlType -eq [Security.AccessControl.AccessControlType]::Allow -and
            ($_.FileSystemRights -band [Security.AccessControl.FileSystemRights]::Modify)
        }
    )
    if ($matching.Count -eq 0) {
        throw "The migrated ACL was not retained on $path."
    }
}

Write-Host (
    "Migrated managed-system USB ACLs for $WindowsUserSid on disk " +
    "$($elevatedTarget.DiskNumber), serial $($elevatedTarget.DiskSerial)."
)
exit 0
