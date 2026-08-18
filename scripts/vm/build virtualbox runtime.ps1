[CmdletBinding()]
param(
    [switch]$Clean
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$catalogueTarget = Join-Path $projectRoot 'source\catalogue\virtualbox'
$softwareTarget = Join-Path $projectRoot 'source\software\virtualbox'
$supervisorTarget = Join-Path $softwareTarget 'guestadditions.py'
$settingsTarget = Join-Path $projectRoot 'source\settings\virtualbox'
$clipboardSource = Join-Path $PSScriptRoot 'virtualbox clipboard.cpp'
$serviceSource = Join-Path $PSScriptRoot 'virtualbox service.cpp'
$developmentRoot = Join-Path $projectRoot 'development\virtualbox runtime'
$stageRoot = Join-Path $developmentRoot 'stage'
$catalogueStage = Join-Path $stageRoot 'catalogue'
$softwareStage = Join-Path $stageRoot 'software'
$virtualBoxVersion = '7.2.12'
$virtualBoxRevision = '174389'
$virtualBoxSha256 = '64a4843677e42010e7799e951883fbbefc56bf2bc162e4970edea04f142f8b25'

function Assert-ProjectPath {
    param(
        [Parameter(Mandatory)]
        [string]$Path
    )

    $fullProjectRoot = [System.IO.Path]::GetFullPath($projectRoot).TrimEnd([System.IO.Path]::DirectorySeparatorChar)
    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $projectPrefix = $fullProjectRoot + [System.IO.Path]::DirectorySeparatorChar

    if (-not $fullPath.StartsWith($projectPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to modify a path outside the T1OS project: $fullPath"
    }
}

function ConvertTo-WslPath {
    param(
        [Parameter(Mandatory)]
        [string]$WindowsPath
    )

    $output = & wsl.exe --exec wslpath -a $WindowsPath
    if ($LASTEXITCODE -ne 0 -or -not $output) {
        throw "Could not translate path for WSL: $WindowsPath"
    }

    return ([string]($output | Select-Object -First 1)).Trim()
}

foreach ($path in @($developmentRoot, $stageRoot, $catalogueStage, $softwareStage, $catalogueTarget, $softwareTarget, $settingsTarget, $clipboardSource, $serviceSource)) {
    Assert-ProjectPath -Path $path
}

if (-not (Test-Path -LiteralPath $clipboardSource -PathType Leaf)) {
    throw "The T1OS VirtualBox clipboard source was not found: $clipboardSource"
}

if (-not (Test-Path -LiteralPath $serviceSource -PathType Leaf)) {
    throw "The T1OS VirtualBox service source was not found: $serviceSource"
}

if (-not (Test-Path -LiteralPath $supervisorTarget -PathType Leaf)) {
    throw "The T1OS VirtualBox supervisor was not found: $supervisorTarget"
}

if (-not (Get-Command 'wsl.exe' -ErrorAction SilentlyContinue)) {
    throw 'Required command not found: wsl.exe'
}

if (Test-Path -LiteralPath $stageRoot) {
    Remove-Item -LiteralPath $stageRoot -Recurse -Force
}

New-Item -ItemType Directory -Path $catalogueStage -Force | Out-Null
New-Item -ItemType Directory -Path $softwareStage -Force | Out-Null

$wslCatalogueStage = ConvertTo-WslPath -WindowsPath $catalogueStage
$wslSoftwareStage = ConvertTo-WslPath -WindowsPath $softwareStage
$wslClipboardSource = ConvertTo-WslPath -WindowsPath $clipboardSource
$wslServiceSource = ConvertTo-WslPath -WindowsPath $serviceSource
$cleanValue = if ($Clean) { '1' } else { '0' }

$buildCommand = @'
set -euo pipefail

catalogue_stage=$1
software_stage=$2
virtualbox_version=$3
virtualbox_revision=$4
virtualbox_sha256=$5
clipboard_source=$6
service_source=$7
clean_build=$8
archive_name="VirtualBox-${virtualbox_version}.tar.bz2"
archive_url="https://download.virtualbox.org/virtualbox/${virtualbox_version}/${archive_name}"
cache="/root/.cache/t1os/virtualbox"
archive="$cache/$archive_name"
runtime_runpath='/the one/catalogue/python'
runtime_interpreter='/the one/catalogue/python/ld-linux-x86-64.so.2'

for command_name in curl gcc g++ make perl python3 makeself xsltproc yasm patchelf readelf sha256sum strings strip tar; do
    if ! command -v "$command_name" >/dev/null 2>&1; then
        echo "Required WSL build command not found: $command_name" >&2
        exit 1
    fi
done

mkdir -p "$cache"

if [ "$clean_build" = '1' ]; then
    rm -f -- "$archive"
fi

if [ ! -f "$archive" ]; then
    curl -L --fail --retry 3 --output "$archive.part" "$archive_url"
    mv -- "$archive.part" "$archive"
fi

echo "$virtualbox_sha256  $archive" | sha256sum -c -

work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT
source_root="$work/source"
mkdir -p "$source_root" "$catalogue_stage" "$software_stage"
tar -xjf "$archive" --strip-components=1 -C "$source_root"
cp -- "$clipboard_source" "$source_root/src/VBox/Additions/x11/VBoxClient/vbox-t1-clipboard.cpp"
cp -- "$service_source" "$source_root/src/VBox/Additions/x11/VBoxClient/vbox-t1-service.cpp"

python3 - "$source_root" <<'PY'
import pathlib
import re
import sys

root = pathlib.Path(sys.argv[1])

def replace(relative, old, new):
    path = root / relative
    text = path.read_text(encoding='utf-8')
    if old not in text:
        raise SystemExit(f'expected VirtualBox source text was not found in {relative}: {old}')
    path.write_text(text.replace(old, new), encoding='utf-8')

replace('src/VBox/Additions/x11/VBoxClient/display-drm.cpp', '"/dev/dri/controlD%u"', '"/the one/drivers/nodes/dri/controlD%u"')
replace('src/VBox/Additions/x11/VBoxClient/display-drm.cpp', '"/dev/dri/renderD%u"', '"/the one/drivers/nodes/dri/renderD%u"')
replace('src/VBox/GuestHost/SharedClipboard/clipboard-transfers-http.cpp', '#include <VBox/GuestHost/SharedClipboard-x11.h>\n', '')
replace('src/VBox/Additions/x11/VBoxClient/display-drm.cpp', 'static const char *g_pszPidFile = VBGLR3DRMPIDFILE;', 'static const char *g_pszPidFile = "/.ephemeral/virtualbox/VBoxDRMClient.pid";')
replace('src/VBox/Additions/x11/VBoxClient/display-drm.cpp', 'vbDrmSetIpcServerAccessPermissions(hIpcServer, VbglR3DrmRestrictedIpcAccessIsNeeded());', 'vbDrmSetIpcServerAccessPermissions(hIpcServer, true);')
replace('src/VBox/Additions/x11/VBoxClient/display-drm.cpp', '''static void vbDrmSetIpcServerAccessPermissions(RTLOCALIPCSERVER hIpcServer, bool fRestrict)
{
    int rc;''', '''static void vbDrmSetIpcServerAccessPermissions(RTLOCALIPCSERVER hIpcServer, bool fRestrict)
{
    int rc;

    /* T1OS has no conventional group database.  Keep this root-owned service's
     * private IPC endpoint restricted even if a host property changes. */
    fRestrict = true;''')
replace('src/VBox/Additions/x11/VBoxClient/display-drm.cpp', '''        else
            VBClLogError("unable to grant IPC server socket access to '" VBOX_DRMIPC_USER_GROUP "', group does not exist\\n");''', '''        else
            VBClLogInfo("IPC server socket remains root-only; optional '" VBOX_DRMIPC_USER_GROUP "' group does not exist\\n");''')

display_path = root / 'src/VBox/Additions/x11/VBoxClient/display-drm.cpp'
display_text = display_path.read_text(encoding='utf-8')
rejected_device = '''            else
            {
                RTFileClose(hDevice);
                hDevice = NIL_RTFILE;
                rc = VERR_NOT_FOUND;
            }
        }
    }
    else
    {
        VBClLogError("unable to construct path to DRM device: %Rrc\\n", rc);
    }'''
diagnostic_device = '''            else
            {
                VBClLogError("rejected DRM device %s: ioctl=%Rrc driver='%s' version=%d.%d.%d\\n",
                             szPath, rc, szVmwgfxDriverName, vmwgfxVersion.cMajor,
                             vmwgfxVersion.cMinor, vmwgfxVersion.cPatchLevel);
                RTFileClose(hDevice);
                hDevice = NIL_RTFILE;
                rc = VERR_NOT_FOUND;
            }
        }
        else if (rc != VERR_FILE_NOT_FOUND)
            VBClLogVerbose(1, "unable to open DRM device %s, rc=%Rrc\\n", szPath, rc);
    }
    else
    {
        VBClLogError("unable to construct path to DRM device: %Rrc\\n", rc);
    }'''
if rejected_device not in display_text:
    raise SystemExit('could not add VirtualBox DRM probe diagnostics')
display_text = display_text.replace(rejected_device, diagnostic_device, 1)

no_device = '''    VBClLogError("unable to find DRM device\\n");

    return hDevice;'''
primary_fallback = '''    /* T1OS runs this root-owned service without a conventional device tree.
     * Fall back to primary nodes when a usable render node is unavailable. */
    for (i = 0; i < VMW_CONTROL_DEVICE_MINOR_START; i++)
    {
        hDevice = vbDrmTryDevice("/the one/drivers/nodes/dri/card%u", i);
        if (hDevice != NIL_RTFILE)
            return hDevice;
    }

    VBClLogError("unable to find DRM device\\n");

    return hDevice;'''
if no_device not in display_text:
    raise SystemExit('could not add the T1OS primary DRM node fallback')
display_text = display_text.replace(no_device, primary_fallback, 1)
display_path.write_text(display_text, encoding='utf-8')

replace('src/VBox/Runtime/r3/posix/localipc-posix.cpp', '#define RTLOCALIPC_POSIX_NAME_PREFIX    "/tmp/.iprt-localipc-"', '#define RTLOCALIPC_POSIX_NAME_PREFIX    "/.ephemeral/virtualbox/.iprt-localipc-"')

guest_header = root / 'include/VBox/VBoxGuest.h'
guest_text = guest_header.read_text(encoding='utf-8')
guest_text = guest_text.replace('"/dev/vboxguest"', '"/the one/drivers/nodes/vboxguest"')
guest_text = guest_text.replace('"/dev/vboxuser"', '"/the one/drivers/nodes/vboxuser"')
guest_text = guest_text.replace('"/dev/vboxguestu"', '"/the one/drivers/nodes/vboxuser"')
guest_header.write_text(guest_text, encoding='utf-8')

process_path = root / 'src/VBox/Runtime/r3/linux/rtProcInitExePath-linux.cpp'
process_text = process_path.read_text(encoding='utf-8')
function = re.compile(r'DECLHIDDEN\(int\) rtProcInitExePath\(char \*pszPath, size_t cchPath\)\n\{.*?\n\}', re.DOTALL)
replacement = '''DECLHIDDEN(int) rtProcInitExePath(char *pszPath, size_t cchPath)
{
    return RTStrCopy(pszPath, cchPath, "/the one/software/virtualbox/VBoxDRMClient");
}'''
process_text, count = function.subn(replacement, process_text, count=1)
if count != 1:
    raise SystemExit('could not patch the IPRT executable path function')
process_path.write_text(process_text, encoding='utf-8')

makefile_path = root / 'src/VBox/Additions/x11/VBoxClient/Makefile.kmk'
makefile_text = makefile_path.read_text(encoding='utf-8')
anchor = 'PROGRAMS.linux += VBoxDRMClient\n'
if anchor not in makefile_text:
    raise SystemExit('could not add the T1OS targets to the VirtualBox build')
makefile_text = makefile_text.replace(anchor, anchor + 'PROGRAMS.linux += VBoxT1Clipboard VBoxT1Service\n', 1)
target_anchor = '''VBoxDRMClient_SOURCES += $(VBOX_GH_SOURCES)
'''
target = '''VBoxDRMClient_SOURCES += $(VBOX_GH_SOURCES)

VBoxT1Clipboard_TEMPLATE = VBoxGuestR3Exe
VBoxT1Clipboard_DEFS += VBOX_WITH_HGCM VBOX_WITH_SHARED_CLIPBOARD VBOX_WITH_SHARED_CLIPBOARD_TRANSFERS VBOX_WITH_SHARED_CLIPBOARD_GUEST VBOX_WITH_SHARED_CLIPBOARD_TRANSFERS_HTTP
ifdef VBOX_WITH_SHARED_CLIPBOARD_TRANSFERS
 VBoxT1Clipboard_DEFS += VBOX_WITH_SHARED_CLIPBOARD_TRANSFERS VBOX_WITH_SHARED_CLIPBOARD_GUEST
endif
VBoxT1Clipboard_SOURCES = \\
	vbox-t1-clipboard.cpp \\
	$(PATH_ROOT)/src/VBox/GuestHost/SharedClipboard/clipboard-common.cpp \\
	$(PATH_ROOT)/src/VBox/GuestHost/SharedClipboard/clipboard-transfers.cpp \\
	$(PATH_ROOT)/src/VBox/GuestHost/SharedClipboard/ClipboardPath.cpp \\
	$(PATH_ROOT)/src/VBox/GuestHost/SharedClipboard/clipboard-transfers-http.cpp

VBoxT1Service_TEMPLATE = VBoxGuestR3Exe
VBoxT1Service_DEFS += VBOX_WITH_HGCM VBOX_WITH_GUEST_PROPS VBOX_WITH_SHARED_FOLDERS VBOX_WITH_DRAG_AND_DROP
ifdef VBOX_WITH_DRAG_AND_DROP_GH
 VBoxT1Service_DEFS += VBOX_WITH_DRAG_AND_DROP_GH
endif
VBoxT1Service_SOURCES = vbox-t1-service.cpp
VBoxT1Service_LIBS += \\
	$(VBOX_LIB_VBGL_R3) \\
	$(PATH_STAGE_LIB)/additions/VBoxDnDGuestR3Lib$(VBOX_SUFF_LIB)
'''
if target_anchor not in makefile_text:
    raise SystemExit('could not configure the T1OS clipboard target sources')
makefile_text = makefile_text.replace(target_anchor, target, 1)
makefile_path.write_text(makefile_text, encoding='utf-8')

for base in (root / 'src/VBox/Runtime', root / 'include'):
    for path in base.rglob('*'):
        if path.suffix not in {'.c', '.cc', '.cpp', '.h', '.hpp'}:
            continue
        try:
            text = path.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            continue
        updated = text.replace('/dev/null', '/the one/drivers/nodes/null')
        updated = updated.replace('/dev/urandom', '/the one/drivers/nodes/urandom')
        updated = updated.replace('/proc/self/cmdline', '/.ephemeral/virtualbox/process.arguments')
        updated = updated.replace('/proc/kallsyms', '/the one/drivers/processes/kallsyms')
        if updated != text:
            path.write_text(updated, encoding='utf-8')
PY

cd "$source_root"
./configure \
    --only-additions \
    --disable-kmods \
    --disable-docs \
    --disable-java \
    --disable-python \
    --disable-qt \
    --disable-alsa \
    --disable-pulse \
    --disable-hardening

source ./env.sh
prefix_flags="-O2 -mtune=generic -fstack-protector-strong -fstack-clash-protection -fcf-protection=full -fno-plt -fno-common -D_FORTIFY_SOURCE=3 -Wformat -Wformat-security -Werror=format-security -ffile-prefix-map=${source_root}=virtualbox-source -fmacro-prefix-map=${source_root}=virtualbox-source"
link_flags="-Wl,-z,relro,-z,now,-z,noexecstack,--as-needed"
kmk -j"$(nproc)" VBOX_ONLY_ADDITIONS=1 VBOX_GCC_OPT="$prefix_flags" VBOX_LD_OPT="$link_flags" VBoxDRMClient VBoxT1Clipboard VBoxT1Service

for binary_name in VBoxDRMClient VBoxT1Clipboard VBoxT1Service; do
    binary="$source_root/out/linux.amd64/release/bin/additions/$binary_name"
    if [ ! -x "$binary" ]; then
        echo "$binary_name build output was not generated." >&2
        exit 1
    fi

    cp -- "$binary" "$software_stage/$binary_name"
    chmod 0755 "$software_stage/$binary_name"
    strip --strip-unneeded "$software_stage/$binary_name"
    patchelf --set-interpreter "$runtime_interpreter" "$software_stage/$binary_name"
    patchelf --set-rpath "$runtime_runpath" "$software_stage/$binary_name"
done
cp -- "$source_root/COPYING" "$catalogue_stage/licence GPL-3.0.txt"

cat > "$software_stage/version.txt" <<EOF
VirtualBox Guest Additions $virtualbox_version r$virtualbox_revision
EOF

export T1OS_CATALOGUE_STAGE="$catalogue_stage"
export T1OS_SOFTWARE_STAGE="$software_stage"
export T1OS_VBOX_VERSION="$virtualbox_version"
export T1OS_VBOX_REVISION="$virtualbox_revision"
export T1OS_VBOX_SHA256="$virtualbox_sha256"
export T1OS_VBOX_SOURCE_URL="$archive_url"
export T1OS_RUNTIME_RUNPATH="$runtime_runpath"
export T1OS_RUNTIME_INTERPRETER="$runtime_interpreter"

python3 - <<'PY'
import hashlib
import json
import os
import pathlib
import re
import subprocess

catalogue = pathlib.Path(os.environ['T1OS_CATALOGUE_STAGE'])
software = pathlib.Path(os.environ['T1OS_SOFTWARE_STAGE'])
binaries = [software / name for name in ('VBoxDRMClient', 'VBoxT1Clipboard', 'VBoxT1Service')]
runpath = os.environ['T1OS_RUNTIME_RUNPATH']
interpreter = os.environ['T1OS_RUNTIME_INTERPRETER']

def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as file:
        for block in iter(lambda: file.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()

allowed_needed = {'libc.so.6'}
forbidden_pattern = re.compile(r'(?:^|[\s"\'])/(?:dev|proc|sys|usr|lib|etc|opt|var|tmp|bin|sbin)(?:/|$)')
metadata = {}
unresolved = []
forbidden = []
hardening_failures = []

for binary in binaries:
    elfheader = subprocess.check_output(['readelf', '-h', str(binary)], text=True, errors='replace')
    dynamic = subprocess.check_output(['readelf', '-d', str(binary)], text=True, errors='replace')
    program = subprocess.check_output(['readelf', '-lW', str(binary)], text=True, errors='replace')
    needed = re.findall(r'\(NEEDED\).*?\[([^]]+)\]', dynamic)
    actual_runpath = (re.findall(r'\(RUNPATH\).*?\[([^]]+)\]', dynamic) or [None])[0]
    actual_interpreter = (re.findall(r'Requesting program interpreter:\s*([^]]+)', program) or [None])[0]
    values = subprocess.check_output(['strings', '-a', str(binary)], text=True, errors='replace').splitlines()
    binary_forbidden = sorted(set(value for value in values if forbidden_pattern.search(value)))
    binary_unresolved = sorted(set(needed) - allowed_needed)
    stack_lines = [line for line in program.splitlines() if 'GNU_STACK' in line]
    hardening = {
        'pie': bool(re.search(r'Type:\s+DYN\b', elfheader)),
        'relro': 'GNU_RELRO' in program,
        'bind_now': 'BIND_NOW' in dynamic,
        'non_executable_stack': bool(stack_lines) and all('RWE' not in line for line in stack_lines),
    }
    metadata[binary] = {
        'needed': needed,
        'runpath': actual_runpath,
        'interpreter': actual_interpreter,
        'hardening': hardening,
    }
    unresolved.extend(f'{binary.name}: {value}' for value in binary_unresolved)
    forbidden.extend(f'{binary.name}: {value}' for value in binary_forbidden)
    hardening_failures.extend(
        f'{binary.name}: {name}' for name, enabled in hardening.items() if not enabled
    )

unresolved = sorted(set(unresolved))
forbidden = sorted(set(forbidden))
symlinks = sorted(
    str(path) for root in (catalogue, software) for path in root.rglob('*') if path.is_symlink()
)

bad_runtime = sorted(
    binary.name for binary, values in metadata.items()
    if values['runpath'] != runpath or values['interpreter'] != interpreter
)

if unresolved or forbidden or symlinks or bad_runtime or hardening_failures:
    raise SystemExit(json.dumps({
        'unresolved': unresolved,
        'forbidden_paths': forbidden,
        'symlinks': symlinks,
        'bad_runtime': bad_runtime,
        'hardening_failures': hardening_failures,
    }, indent=2))

files = []
for area, root in (('catalogue', catalogue), ('software', software)):
    for path in sorted(value for value in root.rglob('*') if value.is_file()):
        values = metadata.get(path, {})
        files.append({
            'area': area,
            'path': path.relative_to(root).as_posix(),
            'size': path.stat().st_size,
            'sha256': digest(path),
            'needed': values.get('needed', []),
            'interpreter': values.get('interpreter'),
            'runpath': values.get('runpath'),
            'hardening': values.get('hardening'),
        })

manifest = {
    'format': 1,
    'state': 'ready',
    'source': {
        'name': 'Oracle VirtualBox Guest Additions',
        'version': os.environ['T1OS_VBOX_VERSION'],
        'revision': os.environ['T1OS_VBOX_REVISION'],
        'url': os.environ['T1OS_VBOX_SOURCE_URL'],
        'sha256': os.environ['T1OS_VBOX_SHA256'],
    },
    'components': ['VBoxDRMClient', 'VBoxT1Clipboard', 'VBoxT1Service'],
    'kernel_modules': 'T1OS in-tree kernel configuration',
    'provided_dependencies': {
        'libc.so.6': '/the one/catalogue/python/libc.so.6',
        'loader': interpreter,
    },
    'path_patches': {
        'vboxguest': '/the one/drivers/nodes/vboxguest',
        'vboxuser': '/the one/drivers/nodes/vboxuser',
        'drm': '/the one/drivers/nodes/dri',
        'drm_primary_fallback': '/the one/drivers/nodes/dri/card%u',
        'pid': '/.ephemeral/virtualbox/VBoxDRMClient.pid',
        'ipc': '/.ephemeral/virtualbox/.iprt-localipc-',
        'arguments': '/.ephemeral/virtualbox/process.arguments',
        'null': '/the one/drivers/nodes/null',
        'urandom': '/the one/drivers/nodes/urandom',
    },
    'security': {
        'ipc_access': 'root-only',
        'setuid': False,
        'external_kernel_modules': False,
        'clipboard_formats': ['unicode-text', 'html', 'bitmap', 'files'],
        'clipboard_transport': 'HGCM',
        'shared_folders': 'vboxsf automount',
        'native_hardening': ['PIE', 'full RELRO', 'BIND_NOW', 'non-executable stack', 'stack protector', 'FORTIFY_SOURCE=3', 'stack clash protection', 'control-flow protection'],
        'time_synchronization': 'disabled pending an authenticated Operations time broker',
        'guest_properties': 'transient T1OS readiness and display state',
        'drag_and_drop': ['host-to-guest', 'guest-to-host'],
    },
    'files': files,
    'verification': {
        'unresolved_dependencies': unresolved,
        'forbidden_paths': forbidden,
        'symlinks': symlinks,
        'hardening_failures': hardening_failures,
    },
}

(catalogue / 'catalogue.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
PY
'@

Write-Host "Building the pinned VirtualBox $virtualBoxVersion r$virtualBoxRevision integration runtime in WSL..."
& wsl.exe -u root --exec bash -c $buildCommand bash $wslCatalogueStage $wslSoftwareStage $virtualBoxVersion $virtualBoxRevision $virtualBoxSha256 $wslClipboardSource $wslServiceSource $cleanValue
if ($LASTEXITCODE -ne 0) {
    throw "The VirtualBox runtime build failed (exit code $LASTEXITCODE)."
}

$manifestStage = Join-Path $catalogueStage 'catalogue.json'
if (-not (Test-Path -LiteralPath $manifestStage -PathType Leaf)) {
    throw "The staged VirtualBox manifest was not generated: $manifestStage"
}

$manifest = Get-Content -LiteralPath $manifestStage -Raw | ConvertFrom-Json
if ($manifest.state -ne 'ready' -or $manifest.source.version -ne $virtualBoxVersion -or $manifest.source.revision -ne $virtualBoxRevision) {
    throw 'The staged VirtualBox manifest does not match the pinned build inputs.'
}

$versionStage = Join-Path $softwareStage 'version.txt'
if (-not (Test-Path -LiteralPath $versionStage -PathType Leaf)) {
    throw "The staged VirtualBox version setting was not generated: $versionStage"
}

foreach ($target in @($catalogueTarget, $settingsTarget)) {
    if (Test-Path -LiteralPath $target) {
        Get-ChildItem -LiteralPath $target -Force | Remove-Item -Recurse -Force
    }
    else {
        New-Item -ItemType Directory -Path $target -Force | Out-Null
    }
}

if (-not (Test-Path -LiteralPath $softwareTarget -PathType Container)) {
    New-Item -ItemType Directory -Path $softwareTarget -Force | Out-Null
}

Copy-Item -LiteralPath (Join-Path $catalogueStage 'catalogue.json') -Destination $catalogueTarget -Force
Copy-Item -LiteralPath (Join-Path $catalogueStage 'licence GPL-3.0.txt') -Destination $catalogueTarget -Force
Copy-Item -LiteralPath $versionStage -Destination (Join-Path $settingsTarget 'version.txt') -Force
Copy-Item -LiteralPath (Join-Path $softwareStage 'VBoxDRMClient') -Destination $softwareTarget -Force
Copy-Item -LiteralPath (Join-Path $softwareStage 'VBoxT1Clipboard') -Destination $softwareTarget -Force
Copy-Item -LiteralPath (Join-Path $softwareStage 'VBoxT1Service') -Destination $softwareTarget -Force

$binaryTarget = Join-Path $softwareTarget 'VBoxDRMClient'
$clipboardTarget = Join-Path $softwareTarget 'VBoxT1Clipboard'
$serviceTarget = Join-Path $softwareTarget 'VBoxT1Service'
if (-not (Test-Path -LiteralPath $binaryTarget -PathType Leaf) -or -not (Test-Path -LiteralPath $clipboardTarget -PathType Leaf) -or -not (Test-Path -LiteralPath $serviceTarget -PathType Leaf) -or -not (Test-Path -LiteralPath $supervisorTarget -PathType Leaf)) {
    throw 'The VirtualBox integration runtime binaries were not installed.'
}

Write-Host "VirtualBox runtime completed: $binaryTarget, $clipboardTarget, and $serviceTarget"
