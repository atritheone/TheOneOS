[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$NtfscpPath,

    [Parameter(Mandatory)]
    [string]$NtfscpProvenancePath
)

$ErrorActionPreference = 'Stop'
$validator = Join-Path $PSScriptRoot 'validate roothealth journal.py'
$fixtures = Join-Path $PSScriptRoot 'roothealth journal fixtures.py'

function ConvertTo-WslPath {
    param([Parameter(Mandatory)][string]$WindowsPath)

    $output = & wsl.exe -d Ubuntu --exec wslpath -a $WindowsPath
    if ($LASTEXITCODE -ne 0 -or -not $output) {
        throw "Could not translate path for WSL: $WindowsPath"
    }
    return ([string]($output | Select-Object -First 1)).Trim()
}

if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    throw 'Ubuntu WSL is required to test the roothealth journal.'
}
if (-not (Test-Path -LiteralPath $validator -PathType Leaf)) {
    throw "The roothealth journal validator is missing: $validator"
}
if (-not (Test-Path -LiteralPath $fixtures -PathType Leaf)) {
    throw "The roothealth journal fixture helper is missing: $fixtures"
}

$integrationRequirements = [ordered]@{
    'create hardware usb image.ps1' = @(
        'verify-ntfscp',
        'provision-flags-device "$root_device"',
        '--builder-image "$output"',
        '--require-one-run --require-zero-entry-area',
        'ROOTHEALTH_JOURNAL_BASE64=',
        'roothealth_journal = $rootHealthJournal'
    )
    'validate hardware usb image.ps1' = @(
        'roothealth_journal_validator',
        '--require-one-run --require-zero-entry-area',
        'image_hash_after=$(sha256sum "$image"',
        "embedded.get('roothealth_journal')"
    )
    'create hardware usb bundle.ps1' = @(
        'source_journal_report=',
        'resize-preserved-and-validated',
        '--require-zero-entry-area',
        'ROOTHEALTH_JOURNAL_BASE64'
    )
    'test hardware usb bundle.ps1' = @(
        'validate_journal()',
        'expanded-${size_gib}-roothealth.json',
        'RootHealth ownership proof is incomplete',
        'target_hash_before_journal'
    )
    'flash hardware usb.ps1' = @(
        'resize-preserved-and-validated',
        'roothealthJournal = $rootHealthJournal',
        'ConvertTo-Json -Depth 12 -Compress'
    )
}
foreach ($entry in $integrationRequirements.GetEnumerator()) {
    $path = Join-Path $PSScriptRoot $entry.Key
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "RootHealth journal integration input is missing: $path"
    }
    $tokens = $null
    $parseErrors = $null
    [void][System.Management.Automation.Language.Parser]::ParseFile(
        $path,
        [ref]$tokens,
        [ref]$parseErrors
    )
    if ($parseErrors.Count -ne 0) {
        throw "RootHealth journal integration script has a PowerShell parse error: $path"
    }
    $text = Get-Content -LiteralPath $path -Raw
    foreach ($marker in $entry.Value) {
        if (-not $text.Contains($marker, [StringComparison]::Ordinal)) {
            throw "RootHealth journal integration marker is missing from $($entry.Key): $marker"
        }
    }
}
$imageBuilderText = Get-Content -LiteralPath (
    Join-Path $PSScriptRoot 'create hardware usb image.ps1'
) -Raw
if ($imageBuilderText.Contains('--allow-proposed-test-tool', [StringComparison]::Ordinal)) {
    throw 'The production image builder must never accept proposed-test-only ntfscp provenance.'
}

$wslValidator = ConvertTo-WslPath -WindowsPath $validator
$wslFixtures = ConvertTo-WslPath -WindowsPath $fixtures
$resolvedNtfscp = [System.IO.Path]::GetFullPath($NtfscpPath)
if (-not (Test-Path -LiteralPath $resolvedNtfscp -PathType Leaf)) {
    throw "The selected pinned ntfscp is missing: $resolvedNtfscp"
}
$resolvedNtfscpProvenance = [System.IO.Path]::GetFullPath($NtfscpProvenancePath)
if (-not (Test-Path -LiteralPath $resolvedNtfscpProvenance -PathType Leaf)) {
    throw "The selected ntfscp provenance manifest is missing: $resolvedNtfscpProvenance"
}
$wslNtfscp = ConvertTo-WslPath -WindowsPath $resolvedNtfscp
$wslNtfscpProvenance = ConvertTo-WslPath -WindowsPath $resolvedNtfscpProvenance
$testScript = @'
set -euo pipefail
export LC_ALL=C
export PYTHONDONTWRITEBYTECODE=1
umask 077

validator=$1
ntfscp_tool=$2
ntfscp_provenance=$3
mutator=$4
required_commands=(
    awk blockdev cp cryptsetup dd dmsetup grep ln losetup mkdir mkfs.ntfs
    mktemp mount.ntfs-3g mv ntfsclone ntfsresize python3 rm sed sgdisk sha256sum
    stat sync tail truncate umount
)
missing=()
for command_name in "${required_commands[@]}"; do
    command -v "$command_name" >/dev/null 2>&1 || missing+=("$command_name")
done
if [ "${#missing[@]}" -ne 0 ]; then
    printf 'Missing roothealth journal-test commands: %s\n' "${missing[*]}" >&2
    exit 127
fi
[ -f "$validator" ] || {
    echo "The journal validator is unavailable in WSL: $validator" >&2
    exit 1
}
command -v "$ntfscp_tool" >/dev/null 2>&1 || {
    echo "The selected ntfscp is unavailable in WSL: $ntfscp_tool" >&2
    exit 127
}
work=$(mktemp -d /var/tmp/roothealth-journal-test.XXXXXX)
case "$work" in
    /var/tmp/roothealth-journal-test.*) ;;
    *) echo "Unexpected roothealth journal-test path: $work" >&2; exit 1 ;;
esac
python3 -B "$validator" verify-ntfscp \
    "$ntfscp_tool" "$ntfscp_provenance" \
    --allow-proposed-test-tool \
    --report "$work/ntfscp-provenance.json"
ntfscp_state=$(python3 -B - "$work/ntfscp-provenance.json" <<'PY'
import json
import sys
with open(sys.argv[1], encoding='utf-8') as stream:
    print(json.load(stream)['state'])
PY
)
if [ "$ntfscp_state" = proposed-test-only ]; then
    if python3 -B "$validator" verify-ntfscp \
            "$ntfscp_tool" "$ntfscp_provenance" >/dev/null 2>&1; then
        echo 'Proposed test-only ntfscp provenance passed the release gate.' >&2
        exit 1
    fi
elif [ "$ntfscp_state" = release-qualified ]; then
    python3 -B "$validator" verify-ntfscp \
        "$ntfscp_tool" "$ntfscp_provenance" >/dev/null
else
    echo "Unexpected ntfscp provenance state: $ntfscp_state" >&2
    exit 1
fi

active_loop=
active_mapper=
active_holder=
mounted=0
mount_root="$work/mount"
mkdir "$mount_root"
cleanup() {
    set +e
    cleanup_failed=0
    if [ "$mounted" = 1 ]; then
        if umount "$mount_root"; then
            mounted=0
        else
            cleanup_failed=1
        fi
    fi
    if [ -n "$active_holder" ]; then
        if dmsetup remove "$active_holder"; then
            active_holder=
        else
            cleanup_failed=1
        fi
    fi
    if [ "$mounted" = 0 ] && [ -n "$active_loop" ]; then
        if losetup --detach "$active_loop"; then
            active_loop=
        else
            cleanup_failed=1
        fi
    fi
    if [ -n "$active_mapper" ]; then
        if cryptsetup close "$active_mapper"; then
            active_mapper=
        else
            cleanup_failed=1
        fi
    fi
    if [ "$cleanup_failed" = 0 ]; then
        case "$work" in
            /var/tmp/roothealth-journal-test.*) rm -rf -- "$work" ;;
        esac
    else
        echo "Could not completely clean journal-test workspace: $work" >&2
    fi
}
trap cleanup EXIT
trap 'exit 130' HUP INT TERM

image="$work/root.ntfs.building"
final_image="$work/root.ntfs"
seed="$work/roothealth.seed"
seed_report="$work/seed.json"
initial_report="$work/initial.json"
shrink_report="$work/shrink.json"
expand_report="$work/expand.json"

truncate -s 1G "$image"
active_loop=$(losetup --find --show "$image")
mkfs.ntfs -F -Q -L 'T1OS JOURNAL TEST' "$active_loop" >/dev/null
[ "$(blockdev --getss "$active_loop")" = 512 ]
public_block_before=$(sha256sum "$image" | awk '{print $1}')
if python3 -B "$validator" provision-flags "$active_loop" >/dev/null 2>&1; then
    echo 'Public regular-file journal provisioner accepted a block device.' >&2
    exit 1
fi
[ "$(sha256sum "$image" | awk '{print $1}')" = "$public_block_before" ]

python3 -B "$validator" seed "$active_loop" "$seed" --report "$seed_report"
[ "$(stat -c %s "$seed")" = 134217728 ]
"$ntfscp_tool" -f -m "$active_loop" "$seed" '$Extend/$RootHealth'
sync
mount.ntfs-3g -o rw,permissions,show_sys_files "$active_loop" "$mount_root"
mounted=1
python3 -B - "$mount_root/\$Extend/\$RootHealth" <<'PY'
import os
from pathlib import Path
import struct
import sys

path = Path(sys.argv[1])
required = 0x00002007
os.setxattr(path, 'system.ntfs_attrib', struct.pack('<I', required))
observed = struct.unpack('<I', os.getxattr(path, 'system.ntfs_attrib'))[0]
if observed != required:
    raise SystemExit(
        f'journal protected attributes did not persist: 0x{observed:08x}'
    )
PY
sync
umount "$mount_root"
mounted=0
losetup --detach "$active_loop"
active_loop=

create_builder_disk() {
    disk=$1
    root_type=$2
    root_name=$3
    truncate -s 2G "$disk"
    disk_sectors=$(($(stat -c %s "$disk") / 512))
    root_end=$((disk_sectors - 2049))
    sgdisk --zap-all "$disk" >/dev/null
    sgdisk --clear \
        --new=1:2048:+16M --typecode=1:ef00 --change-name=1:T1OS_TEST_ESP \
        --new=2:0:"$root_end" --typecode=2:"$root_type" \
        --change-name=2:"$root_name" "$disk" >/dev/null
    sgdisk --verify "$disk" >/dev/null
}

attach_builder_disk() {
    disk=$1
    active_loop=$(losetup --find --show --partscan "$disk")
    for unused in 1 2 3 4 5; do
        [ -b "${active_loop}p1" ] && [ -b "${active_loop}p2" ] && return 0
        sleep 0.2
    done
    echo "Builder partition devices did not appear for $disk" >&2
    return 1
}

plain_disk="$work/plain-gpt.img.building"
plain_name='T1OS JOURNAL TEST'
plain_report="$work/plain-block-provision.json"
create_builder_disk "$plain_disk" 0700 "$plain_name"
attach_builder_disk "$plain_disk"
ntfsclone --quiet --force --overwrite "${active_loop}p2" "$image"
sync
plain_before=$(sha256sum "$plain_disk" | awk '{print $1}')

python3 -B - "$plain_disk" "$work/backup-gpt.bin" <<'PY'
import os
from pathlib import Path
import struct
import sys
import zlib

image = Path(sys.argv[1])
saved = Path(sys.argv[2])
with image.open('r+b', buffering=0) as handle:
    handle.seek(-512, os.SEEK_END)
    original = handle.read(512)
    if len(original) != 512 or original[:8] != b'EFI PART':
        raise SystemExit('fixture backup GPT header is unavailable')
    saved.write_bytes(original)
    changed = bytearray(original)
    changed[56] ^= 1
    header_size = struct.unpack_from('<I', changed, 12)[0]
    struct.pack_into('<I', changed, 16, 0)
    struct.pack_into('<I', changed, 16, zlib.crc32(changed[:header_size]) & 0xffffffff)
    handle.seek(-512, os.SEEK_END)
    if handle.write(changed) != len(changed):
        raise SystemExit('short backup GPT mutation')
    handle.flush()
    os.fsync(handle.fileno())
PY
if python3 -B "$validator" provision-flags-device "${active_loop}p2" \
        --builder-image "$plain_disk" --root-kind plain \
        --expected-partition-name "$plain_name" >/dev/null 2>&1; then
    echo 'Block provisioner accepted valid but disagreeing GPT headers.' >&2
    exit 1
fi
python3 -B - "$plain_disk" "$work/backup-gpt.bin" <<'PY'
import os
from pathlib import Path
import sys

image = Path(sys.argv[1])
original = Path(sys.argv[2]).read_bytes()
with image.open('r+b', buffering=0) as handle:
    handle.seek(-512, os.SEEK_END)
    if handle.write(original) != len(original):
        raise SystemExit('short backup GPT restore')
    handle.flush()
    os.fsync(handle.fileno())
PY
rm -f -- "$work/backup-gpt.bin"

wrong_builder="$work/wrong-backing.img.building"
truncate -s 2G "$wrong_builder"
if python3 -B "$validator" provision-flags-device "${active_loop}p2" \
        --builder-image "$wrong_builder" --root-kind plain \
        --expected-partition-name "$plain_name" >/dev/null 2>&1; then
    echo 'Block provisioner accepted the wrong .building backing inode.' >&2
    exit 1
fi
rm -f -- "$wrong_builder"
if python3 -B "$validator" provision-flags-device "${active_loop}p1" \
        --builder-image "$plain_disk" --root-kind plain \
        --expected-partition-name "$plain_name" >/dev/null 2>&1; then
    echo 'Block provisioner accepted a non-root GPT partition.' >&2
    exit 1
fi
ln -s "$plain_disk" "$work/plain-alias.img.building"
if python3 -B "$validator" provision-flags-device "${active_loop}p2" \
        --builder-image "$work/plain-alias.img.building" --root-kind plain \
        --expected-partition-name "$plain_name" >/dev/null 2>&1; then
    echo 'Block provisioner accepted a symlinked .building image.' >&2
    exit 1
fi
rm -f -- "$work/plain-alias.img.building"
ln -s "${active_loop}p2" "$work/plain-target-link"
if python3 -B "$validator" provision-flags-device "$work/plain-target-link" \
        --builder-image "$plain_disk" --root-kind plain \
        --expected-partition-name "$plain_name" >/dev/null 2>&1; then
    echo 'Block provisioner accepted a non-mapper target symlink.' >&2
    exit 1
fi
rm -f -- "$work/plain-target-link"

mount.ntfs-3g -o ro "${active_loop}p2" "$mount_root"
mounted=1
if python3 -B "$validator" provision-flags-device "${active_loop}p2" \
        --builder-image "$plain_disk" --root-kind plain \
        --expected-partition-name "$plain_name" >/dev/null 2>&1; then
    echo 'Block provisioner accepted a mounted NTFS target.' >&2
    exit 1
fi
umount "$mount_root"
mounted=0

active_holder="rhjournal-holder-$$"
plain_sectors=$(blockdev --getsz "${active_loop}p2")
dmsetup create "$active_holder" --table \
    "0 $plain_sectors linear ${active_loop}p2 0"
if python3 -B "$validator" provision-flags-device "${active_loop}p2" \
        --builder-image "$plain_disk" --root-kind plain \
        --expected-partition-name "$plain_name" >/dev/null 2>&1; then
    echo 'Block provisioner accepted a root partition with an extra holder.' >&2
    exit 1
fi
dmsetup remove "$active_holder"
active_holder=

[ "$(sha256sum "$plain_disk" | awk '{print $1}')" = "$plain_before" ]
python3 -B "$validator" provision-flags-device "${active_loop}p2" \
    --builder-image "$plain_disk" --root-kind plain \
    --expected-partition-name "$plain_name" --report "$plain_report"
python3 -B "$validator" validate "${active_loop}p2" \
    --require-one-run --require-zero-entry-area >/dev/null
python3 -B - "$plain_report" <<'PY'
import json
import sys

with open(sys.argv[1], encoding='utf-8') as handle:
    report = json.load(handle)
binding = report.get('builder_binding', {})
raw = binding.get('binding', {})
gpt = raw.get('gpt_partition', {})
if binding.get('mode') != 'LOOP_BACKED_BUILDING_BLOCK':
    raise SystemExit('plain block report lacks builder-only mode binding')
if raw.get('root_kind') != 'plain' or gpt.get('number') != 2:
    raise SystemExit('plain block report lacks exact GPT partition-2 binding')
if gpt.get('type_guid') != 'ebd0a0a2-b9e5-4433-87c0-68b6b72699c7':
    raise SystemExit('plain block report has the wrong GPT type')
if raw.get('dm') != {'dm_name': None, 'dm_uuid': None}:
    raise SystemExit('plain block report unexpectedly contains a dm layer')
PY
losetup --detach "$active_loop"
active_loop=

retarget_disk="$work/retarget-gpt.img.building"
retarget_old="$work/retarget-gpt.img.old"
create_builder_disk "$retarget_disk" 0700 "$plain_name"
attach_builder_disk "$retarget_disk"
ntfsclone --quiet --force --overwrite "${active_loop}p2" "$image"
sync
python3 -B - "$validator" "$retarget_disk" "$retarget_old" \
        "${active_loop}p2" "$plain_name" <<'PY'
import importlib.util
import os
from pathlib import Path
import sys

validator_path = Path(sys.argv[1])
builder = Path(sys.argv[2])
old = Path(sys.argv[3])
target = Path(sys.argv[4])
partition_name = sys.argv[5]
spec = importlib.util.spec_from_file_location('journal_retarget_validator', validator_path)
if spec is None or spec.loader is None:
    raise SystemExit('could not load validator for retarget fixture')
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
original = module.provision_flags_on_handle

def retarget_after_write(*args, **kwargs):
    report = original(*args, **kwargs)
    size = builder.stat().st_size
    builder.rename(old)
    descriptor = os.open(builder, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.ftruncate(descriptor, size)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return report

module.provision_flags_on_handle = retarget_after_write
try:
    module.provision_protected_flags_device(
        target, builder, 'plain', partition_name, None
    )
except module.ValidationError:
    pass
else:
    raise SystemExit('block provisioner accepted a retargeted .building path')
if not builder.is_file() or not old.is_file():
    raise SystemExit('retarget fixture did not preserve both inode identities')
PY
losetup --detach "$active_loop"
active_loop=
rm -f -- "$retarget_disk" "$retarget_old"

luks_disk="$work/luks-gpt.img.building"
luks_name=T1OS_CRYPT
luks_report="$work/luks-block-provision.json"
luks_key="$work/luks.key"
printf 'roothealth-journal-fixture-key\n' > "$luks_key"
create_builder_disk "$luks_disk" 8309 "$luks_name"
attach_builder_disk "$luks_disk"

active_holder="rhjournal-linear-$$"
luks_sectors=$(blockdev --getsz "${active_loop}p2")
dmsetup create "$active_holder" --table \
    "0 $luks_sectors linear ${active_loop}p2 0"
if python3 -B "$validator" provision-flags-device "/dev/mapper/$active_holder" \
        --builder-image "$luks_disk" --root-kind luks \
        --expected-partition-name "$luks_name" \
        --expected-mapper-name "$active_holder" >/dev/null 2>&1; then
    echo 'Block provisioner accepted a non-crypt single-slave dm target.' >&2
    exit 1
fi
dmsetup remove "$active_holder"
active_holder=

cryptsetup luksFormat --batch-mode --type luks2 --label T1OS_CRYPT \
    --key-file "$luks_key" "${active_loop}p2"
active_mapper="rhjournal-crypt-$$"
cryptsetup open --type luks --key-file "$luks_key" \
    "${active_loop}p2" "$active_mapper"
mapper_device="/dev/mapper/$active_mapper"
ntfsclone --quiet --force --overwrite "$mapper_device" "$image"
sync
luks_before=$(sha256sum "$luks_disk" | awk '{print $1}')
if python3 -B "$validator" provision-flags-device "$mapper_device" \
        --builder-image "$luks_disk" --root-kind luks \
        --expected-partition-name "$luks_name" \
        --expected-mapper-name wrong-mapper >/dev/null 2>&1; then
    echo 'Block provisioner accepted the wrong dm-crypt mapper name.' >&2
    exit 1
fi
mount.ntfs-3g -o ro "$mapper_device" "$mount_root"
mounted=1
if python3 -B "$validator" provision-flags-device "$mapper_device" \
        --builder-image "$luks_disk" --root-kind luks \
        --expected-partition-name "$luks_name" \
        --expected-mapper-name "$active_mapper" >/dev/null 2>&1; then
    echo 'Block provisioner accepted a mounted dm-crypt target.' >&2
    exit 1
fi
umount "$mount_root"
mounted=0
[ "$(sha256sum "$luks_disk" | awk '{print $1}')" = "$luks_before" ]
python3 -B "$validator" provision-flags-device "$mapper_device" \
    --builder-image "$luks_disk" --root-kind luks \
    --expected-partition-name "$luks_name" \
    --expected-mapper-name "$active_mapper" --report "$luks_report"
python3 -B "$validator" validate "$mapper_device" \
    --require-one-run --require-zero-entry-area >/dev/null
python3 -B - "$luks_report" "$active_mapper" <<'PY'
import json
import sys

with open(sys.argv[1], encoding='utf-8') as handle:
    report = json.load(handle)
raw = report.get('builder_binding', {}).get('binding', {})
dm = raw.get('dm', {})
if raw.get('root_kind') != 'luks' or dm.get('dm_name') != sys.argv[2]:
    raise SystemExit('encrypted block report lacks exact dm-crypt binding')
if not str(dm.get('dm_uuid', '')).startswith('CRYPT-LUKS2-'):
    raise SystemExit('encrypted block report lacks a LUKS2 dm UUID')
if raw.get('gpt_partition', {}).get('type_guid') != \
        'ca7d7ccb-63ed-4c53-861c-1742536059cc':
    raise SystemExit('encrypted block report has the wrong GPT type')
PY
cryptsetup close "$active_mapper"
active_mapper=
losetup --detach "$active_loop"
active_loop=

python3 -B "$validator" provision-flags "$image" >/dev/null
active_loop=$(losetup --find --show "$image")
python3 -B "$validator" validate "$active_loop" \
    --require-one-run \
    --require-zero-entry-area \
    --report "$initial_report"

losetup --detach "$active_loop"
active_loop=
mv "$image" "$final_image"
image="$final_image"
final_sha=$(sha256sum "$image" | awk '{print $1}')
if python3 -B "$validator" provision-flags "$image" >/dev/null 2>&1; then
    echo 'Builder-only journal flag updater accepted a non-.building target.' >&2
    exit 1
fi
[ "$(sha256sum "$image" | awk '{print $1}')" = "$final_sha" ]
ln -s "$image" "$work/alias.building"
if python3 -B "$validator" provision-flags "$work/alias.building" >/dev/null 2>&1; then
    echo 'Builder-only journal flag updater accepted a symlink target.' >&2
    exit 1
fi
[ "$(sha256sum "$image" | awk '{print $1}')" = "$final_sha" ]
rm -f "$work/alias.building"
cp --reflink=auto --sparse=always -- "$image" "$work/already-final.building"
stale_sha=$(sha256sum "$work/already-final.building" | awk '{print $1}')
if python3 -B "$validator" provision-flags "$work/already-final.building" \
        >/dev/null 2>&1; then
    echo 'Builder-only journal flag updater accepted a non-fresh final image.' >&2
    exit 1
fi
[ "$(sha256sum "$work/already-final.building" | awk '{print $1}')" = "$stale_sha" ]
rm -f "$work/already-final.building"
expect_rejected() {
    mode=$1
    fixture="$work/reject-${mode}.ntfs"
    cp --reflink=auto --sparse=always -- "$image" "$fixture"
    if [ "$mode" = duplicate-name ]; then
        active_loop=$(losetup --find --show "$fixture")
        "$ntfscp_tool" -f -m "$active_loop" "$seed" '$Extend/$Duplicate0'
        sync
        losetup --detach "$active_loop"
        active_loop=
    fi
    if [ "$mode" = duplicate-owner ]; then
        ordinary_source="$work/ordinary-owner.bin"
        printf 'ordinary-owner' > "$ordinary_source"
        truncate -s 4096 "$ordinary_source"
        active_loop=$(losetup --find --show "$fixture")
        "$ntfscp_tool" -f -m "$active_loop" "$ordinary_source" \
            '$Extend/$Ordinary0'
        sync
        losetup --detach "$active_loop"
        active_loop=
    fi
    python3 -B "$mutator" "$validator" "$fixture" "$mode"
    if python3 -B "$validator" validate "$fixture" \
        --require-one-run --require-zero-entry-area >/dev/null 2>&1; then
        echo "Journal validator falsely approved negative fixture: $mode" >&2
        exit 1
    fi
    rm -f -- "$fixture"
}

for negative_case in \
    torn-one torn-both misbound-serial uuid-disagreement nonzero-entry \
    nonempty-transaction-kind invalid-entry-cap missing-protected-standard \
    missing-protected-file-name missing-protected-index missing-protected-all \
    clear-bitmap clear-mft-bitmap duplicate-name duplicate-owner \
    overlap-protected self-overlap; do
    expect_rejected "$negative_case"
done

active_loop=$(losetup --find --show "$image")

min_mb=$(
    ntfsresize --info-mb-only --force "$active_loop" |
        sed -n 's/^Minsize (in MB):[[:space:]]*//p' |
        tail -n 1
)
case "$min_mb" in
    ''|*[!0-9]*) echo 'Could not determine disposable NTFS minimum size.' >&2; exit 1 ;;
esac
alignment=$((64 * 1024 * 1024))
reserve=$((256 * 1024 * 1024))
shrink_bytes=$((min_mb * 1000000 + reserve))
shrink_bytes=$((((shrink_bytes + alignment - 1) / alignment) * alignment))
if [ "$shrink_bytes" -ge $((1024 * 1024 * 1024)) ]; then
    echo "Disposable journal fixture cannot be shrunk: $shrink_bytes" >&2
    exit 1
fi
ntfsresize --force --no-progress-bar --size "$shrink_bytes" "$active_loop" >/dev/null
sync
python3 -B "$validator" validate "$active_loop" \
    --require-zero-entry-area \
    --report "$shrink_report"

ntfsresize --force --no-progress-bar "$active_loop" >/dev/null
sync
python3 -B "$validator" validate "$active_loop" \
    --require-zero-entry-area \
    --report "$expand_report"

python3 -B - "$seed_report" "$initial_report" "$shrink_report" "$expand_report" <<'PY'
import json
import pathlib
import sys

seed, initial, shrunk, expanded = [
    json.loads(pathlib.Path(path).read_text(encoding='utf-8'))
    for path in sys.argv[1:]
]
reports = [initial, shrunk, expanded]
expected_uuid = seed['journal_uuid']
expected_serial = seed['volume_serial']
expected_record = initial['journal']['mft_record']
expected_sequence = initial['journal']['mft_sequence']
for report in reports:
    if report['state'] != 'structurally-valid':
        raise SystemExit('journal validation did not return structural success')
    device = report['device']
    journal = report['journal']
    header = journal['header']
    if device['serial'] != expected_serial:
        raise SystemExit('journal resize changed the NTFS serial')
    if header['journal_uuid'] != expected_uuid:
        raise SystemExit('journal resize changed the persistent journal UUID')
    if header['selected_generation'] != 2:
        raise SystemExit('journal did not select release seed generation 2')
    if header['max_entry_count'] != 4096:
        raise SystemExit('journal entry-count capacity policy changed')
    if journal['mft_record'] != expected_record or journal['mft_sequence'] != expected_sequence:
        raise SystemExit('journal resize changed the FILE reference')
    if journal['logical_bytes'] != 134217728:
        raise SystemExit('journal resize changed the fixed WAL capacity')
    if journal['standard_information_flags'] != '0x00002007' or \
            journal['file_name_flags'] != '0x00002007' or \
            journal['extend_i30_file_name_flags'] != '0x00002007' or \
            journal['required_protected_flags'] != '0x00002007':
        raise SystemExit('journal protected attribute profile changed')
    if journal['protected_flags_present'] is not True:
        raise SystemExit('journal protected attribute proof is absent')
    ownership = journal.get('ownership', {})
    if ownership.get('complete') is not True or ownership.get('unique_owner') is not True or \
            ownership.get('self_nonoverlap') is not True:
        raise SystemExit('journal ownership census is incomplete')
    if ownership.get('allocated_mft_records', 0) <= 0 or \
            ownership.get('nonresident_attributes_examined', 0) <= 0 or \
            ownership.get('physical_runs_examined', 0) <= 0:
        raise SystemExit('journal ownership census has implausible zero denominators')
    if ownership.get('journal_clusters') != 32768:
        raise SystemExit('journal ownership census cluster total changed')
    if not all(report['checks'].values()):
        raise SystemExit('journal raw structural proof is incomplete')
if initial['journal']['run_count'] != 1:
    raise SystemExit('freshly provisioned journal is not contiguous')
print(json.dumps({
    'journal_uuid': expected_uuid,
    'mft_record': expected_record,
    'mft_sequence': expected_sequence,
    'initial_runs': initial['journal']['runs'],
    'shrunk_runs': shrunk['journal']['runs'],
    'expanded_runs': expanded['journal']['runs'],
}, sort_keys=True))
PY

echo 'roothealth disposable journal provisioning and resize validation passed.'
'@

$scriptPath = Join-Path ([System.IO.Path]::GetTempPath()) (
    "t1os-test-roothealth-journal-$([guid]::NewGuid().ToString('N')).sh"
)
[System.IO.File]::WriteAllText(
    $scriptPath,
    $testScript.Replace("`r`n", "`n"),
    [System.Text.UTF8Encoding]::new($false)
)
try {
    & wsl.exe -d Ubuntu -u root --exec bash (
        ConvertTo-WslPath -WindowsPath $scriptPath
    ) $wslValidator $wslNtfscp $wslNtfscpProvenance $wslFixtures
    if ($LASTEXITCODE -ne 0) {
        throw "roothealth journal fixture validation failed (exit code $LASTEXITCODE)."
    }
}
finally {
    if (Test-Path -LiteralPath $scriptPath) {
        Remove-Item -LiteralPath $scriptPath -Force
    }
}

Write-Host 'roothealth journal fixture validation passed.'
