#!/usr/bin/env bash
# shellcheck disable=SC2016 # Literal NTFS system names intentionally contain '$'.
set -euo pipefail

fixtures=$1
wal_fixtures=$2
journal_validator=$3
ntfscp_tool=$4

export LC_ALL=C
export PYTHONDONTWRITEBYTECODE=1
umask 077
work=$(mktemp -d /var/tmp/roothealth-repair-fixtures.XXXXXX)
case "$work" in /var/tmp/roothealth-repair-fixtures.*) ;; *) exit 1 ;; esac
active_loop=
mounted=0
mount_root="$work/mount"
mkdir "$mount_root"
cleanup() {
    set +e
    [ "$mounted" = 0 ] || umount "$mount_root"
    [ -z "$active_loop" ] || losetup --detach "$active_loop"
    case "$work" in /var/tmp/roothealth-repair-fixtures.*) rm -rf -- "$work" ;; esac
}
trap cleanup EXIT

base="$work/base.ntfs"
seed="$work/roothealth.seed"
layout="$work/roothealth-layout.json"
truncate -s 512M "$base"
active_loop=$(losetup --find --show "$base")
mkfs.ntfs -F -Q -L 'T1OS REPAIR FIXTURES' "$active_loop" >/dev/null
mount.ntfs-3g -o rw,permissions,windows_names,big_writes \
    "$active_loop" "$mount_root"
mounted=1
mkdir -p \
    "$mount_root/the one/repair-index" \
    "$mount_root/the one/repair-payloads" \
    "$mount_root/the one/orphan-source" \
    "$mount_root/the one/identity-parent" \
    "$mount_root/the one/software/python/bin" \
    "$mount_root/the one/deep/collation-parent-a" \
    "$mount_root/the one/deep/collation-parent-b" \
    "$mount_root/the one/deep/compressed"
printf 'identity target\n' >"$mount_root/the one/identity-parent/required.bin"
printf '#!/bin/sh\nexit 0\n' >"$mount_root/the one/software/python/bin/python"
printf '#!/bin/sh\nexit 0\n' >"$mount_root/the one/software/python/bin/python4.13"
printf 'attribute-list base stream\n' >"$mount_root/the one/deep/attrlist.bin"
ln "$mount_root/the one/deep/attrlist.bin" \
    "$mount_root/the one/deep/collation-parent-b/attrlist-shared.bin"
ln "$mount_root/the one/deep/attrlist.bin" \
    "$mount_root/the one/deep/collation-parent-a/attrlist-shared.bin"
printf 'user-defined attribute holder\n' >"$mount_root/the one/deep/user-defined.bin"
printf 'raw MFT layout candidate base value\n' \
    >"$mount_root/the one/deep/layout-candidate.bin"
python3 - "$mount_root/the one/deep/runlist-size.bin" <<'PY'
from pathlib import Path
import sys

Path(sys.argv[1]).write_bytes((b'RUNLIST-SIZE-ORACLE-' * 700)[:12345])
PY
python3 - "$mount_root/the one/deep" <<'PY'
import os
from pathlib import Path
import sys

directory = Path(sys.argv[1])
sparse = directory / 'unflagged-sparse.bin'
filler = directory / 'unflagged-sparse-filler.tmp'
sparse.write_bytes((b'SPARSE-RUN-FIRST-' * 16384)[:192 * 1024])
filler.write_bytes((b'SPARSE-RUN-FILLER-' * 16384)[:192 * 1024])
with sparse.open('ab') as handle:
    handle.write((b'SPARSE-RUN-LAST-' * 16384)[:192 * 1024])
filler.unlink()
(directory / 'mapping-pair-tail.bin').write_bytes(
    (b'MAPPING-PAIR-TAIL-' * 16384)[:192 * 1024]
)
(directory / 'attribute-end-tail.bin').write_bytes(b'AT-END-TAIL-ORACLE\n')
sparse_unit = directory / 'sparse-unit.bin'
with sparse_unit.open('wb', buffering=0) as handle:
    os.ftruncate(handle.fileno(), 64 * 4096)
    if os.pwrite(handle.fileno(), b'H' * 4096, 0) != 4096:
        raise SystemExit('short sparse-unit head write')
    if os.pwrite(handle.fileno(), b'T' * 4096, 63 * 4096) != 4096:
        raise SystemExit('short sparse-unit tail write')
    os.fsync(handle.fileno())
PY
printf 'hard-link reciprocity oracle\n' >"$mount_root/the one/deep/link-source.bin"
ln "$mount_root/the one/deep/link-source.bin" \
    "$mount_root/the one/deep/link-second.bin"
printf 'resident FILE_NAME value collation oracle\n' \
    >"$mount_root/the one/deep/collation-parent-b/shared.bin"
ln "$mount_root/the one/deep/collation-parent-b/shared.bin" \
    "$mount_root/the one/deep/collation-parent-a/shared.bin"
printf 'POSIX collision member A\n' \
    >"$mount_root/the one/deep/collation-parent-a/PosixName.bin"
printf 'POSIX collision member B\n' \
    >"$mount_root/the one/deep/collation-parent-a/posixname.bin"
python3 - "$mount_root/the one/deep/duplicate-a.bin" \
    "$mount_root/the one/deep/duplicate-b.bin" <<'PY'
from pathlib import Path
import sys

payload = (b'DUPLICATE-CLUSTER-CONTENT-PROOF-' * 8192)[:256 * 1024]
for name in sys.argv[1:]:
    Path(name).write_bytes(payload)
PY
python3 - "$mount_root/the one/deep/compressed" <<'PY'
import os
from pathlib import Path
import struct
import sys

directory = Path(sys.argv[1])
current = struct.unpack('<I', os.getxattr(directory, 'system.ntfs_attrib'))[0]
os.setxattr(directory, 'system.ntfs_attrib', struct.pack('<I', current | 0x800))
(directory / 'metadata.bin').write_bytes(
    (b'ROOTHEALTH-COMPRESSED-METADATA-' * 32768)[:768 * 1024]
)
PY
dd if=/dev/zero of="$mount_root/the one/repair-payloads/bitmap.bin" \
    bs=4096 count=128 status=none
printf 'allocated fixture payload\n' | dd \
    of="$mount_root/the one/repair-payloads/bitmap.bin" conv=notrunc status=none
printf 'live MFT bitmap fixture\n' \
    >"$mount_root/the one/repair-payloads/live-record.txt"
python3 - "$mount_root/the one/repair-payloads/journal-overlap.bin" <<'PY'
from pathlib import Path
import sys

Path(sys.argv[1]).write_bytes((b'ROOTHEALTH-JOURNAL-OWNER-ORACLE-' * 128)[:4096])
PY
dd if=/dev/zero of="$mount_root/the one/orphan-source/reconnect.bin" \
    bs=4096 count=32 status=none
dd if=/dev/zero of="$mount_root/the one/orphan-source/recovery.bin" \
    bs=4096 count=32 status=none
for number in $(seq -w 1 160); do
    printf 'index fixture %s\n' "$number" \
        >"$mount_root/the one/repair-index/entry-$number-abcdefghijklmnopqrstuvwxyz0123456789.data"
done
sync
umount "$mount_root"
mounted=0
printf 'named stream content\n' >"$work/named-stream.bin"
for stream_number in $(seq -w 1 24); do
    "$ntfscp_tool" -f -N "stream$stream_number" "$active_loop" \
        "$work/named-stream.bin" '/the one/deep/attrlist.bin' >/dev/null
done
python3 - "$work/user-defined-stream.bin" <<'PY'
from pathlib import Path
import sys

Path(sys.argv[1]).write_bytes(
    (b'USER-DEFINED-NONRESIDENT-RUNLIST-' * 8192)[:192 * 1024]
)
PY
"$ntfscp_tool" -f -N userDefinedStream "$active_loop" \
    "$work/user-defined-stream.bin" '/the one/deep/user-defined.bin' >/dev/null
printf 'resident layout stream value\n' >"$work/layout-resident-stream.bin"
"$ntfscp_tool" -f -N layoutResident "$active_loop" \
    "$work/layout-resident-stream.bin" '/the one/deep/layout-candidate.bin' >/dev/null
losetup --detach "$active_loop"
active_loop=
building="$base.building"
mv "$base" "$building"
active_loop=$(losetup --find --show "$building")
python3 "$journal_validator" seed "$active_loop" "$seed" >/dev/null
"$ntfscp_tool" -f -m "$active_loop" "$seed" '$Extend/$RootHealth'
sync
mount.ntfs-3g -o rw,permissions,show_sys_files "$active_loop" "$mount_root"
mounted=1
python3 - "$mount_root/\$Extend/\$RootHealth" <<'PY'
import os
from pathlib import Path
import struct
import sys

path = Path(sys.argv[1])
required = 0x00002007
os.setxattr(path, "system.ntfs_attrib", struct.pack("<I", required))
observed = struct.unpack("<I", os.getxattr(path, "system.ntfs_attrib"))[0]
if observed != required:
    raise SystemExit(
        f"journal protected attributes did not persist: 0x{observed:08x}"
    )
PY
sync
umount "$mount_root"
mounted=0
losetup --detach "$active_loop"
active_loop=
python3 "$journal_validator" provision-flags "$building" >/dev/null
active_loop=$(losetup --find --show "$building")
python3 "$journal_validator" validate "$active_loop" \
    --require-one-run --require-zero-entry-area --report "$layout"
losetup --detach "$active_loop"
active_loop=
mv "$building" "$base"

# Build the exact 0x40000 ATTRIBUTE_LIST before the final bitmap-pair pool,
# then reserve the next allocator extent until every later allocation is done.
# Releasing that reservation at the final cleanup leaves a deterministic free
# peer immediately after the list run for the isolated >0x40000 negative.
printf 'x' >"$work/large-attrlist-stream.bin"
"$ntfscp_tool" -f "$base" "$work/large-attrlist-stream.bin" \
    '/the one/deep/large-attrlist.bin' >/dev/null
python3 -B - >"$work/large-attrlist-names.txt" <<'PY'
for ordinal in range(488):
    prefix = f's{ordinal:04d}'
    print(prefix + 'x' * (255 - len(prefix)))
prefix = 'z0489'
print(prefix + 'y' * (208 - len(prefix)))
PY
while IFS= read -r stream_name; do
    "$ntfscp_tool" -f -N "$stream_name" "$base" \
        "$work/large-attrlist-stream.bin" \
        '/the one/deep/large-attrlist.bin' >/dev/null
done <"$work/large-attrlist-names.txt"
dd if=/dev/zero of="$work/large-attrlist-adjacent.bin" \
    bs=4096 count=1 status=none
"$ntfscp_tool" -f "$base" "$work/large-attrlist-adjacent.bin" \
    '/the one/deep/large-attrlist-adjacent.reserve' >/dev/null

active_loop=$(losetup --find --show "$base")
mount.ntfs-3g -o rw,permissions,windows_names,big_writes \
    "$active_loop" "$mount_root"
mounted=1
python3 - "$mount_root/the one/repair-payloads" <<'PY'
import os
from pathlib import Path
import sys

directory = Path(sys.argv[1])
for ordinal in range(64):
    path = directory / f'bitmap-pair-candidate-{ordinal:02d}.bin'
    block = bytes((0x41 + ordinal % 23,)) * 4096
    with path.open('wb', buffering=0) as handle:
        if handle.write(block) != len(block):
            raise SystemExit('short bitmap candidate write')
        os.fsync(handle.fileno())
directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
try:
    os.fsync(directory_fd)
finally:
    os.close(directory_fd)
PY
sync
umount "$mount_root"
mounted=0
losetup --detach "$active_loop"
active_loop=
declare -A bitmap_candidate_by_byte=()
bitmap_selected=
bitmap_victim=
for ordinal in $(seq -w 0 63); do
    candidate_path="/the one/repair-payloads/bitmap-pair-candidate-$ordinal.bin"
    candidate_lcn=$(ntfscluster -F "$candidate_path" "$base" |
        awk '$1 == 0 && $3 == 1 {print $2}')
    case "$candidate_lcn" in
        ''|*[!0-9]*)
            echo "Bitmap candidate $ordinal lacks one exact cluster: $candidate_lcn" >&2
            exit 1
            ;;
    esac
    candidate_byte=$((candidate_lcn / 8))
    if [ -n "${bitmap_candidate_by_byte[$candidate_byte]:-}" ]; then
        bitmap_selected=${bitmap_candidate_by_byte[$candidate_byte]}
        bitmap_victim=$ordinal
        break
    fi
    bitmap_candidate_by_byte[$candidate_byte]=$ordinal
done
if [ -z "$bitmap_selected" ] || [ -z "$bitmap_victim" ]; then
    echo 'Could not construct a same-byte live/free cluster pair.' >&2
    exit 1
fi
active_loop=$(losetup --find --show "$base")
mount.ntfs-3g -o rw,permissions,windows_names,big_writes \
    "$active_loop" "$mount_root"
mounted=1
rm -- "$mount_root/the one/repair-payloads/bitmap.bin"
mv -- \
    "$mount_root/the one/repair-payloads/bitmap-pair-candidate-$bitmap_selected.bin" \
    "$mount_root/the one/repair-payloads/bitmap.bin"
for ordinal in $(seq -w 0 63); do
    [ "$ordinal" = "$bitmap_selected" ] || \
        rm -- "$mount_root/the one/repair-payloads/bitmap-pair-candidate-$ordinal.bin"
done
rm -- "$mount_root/the one/deep/large-attrlist-adjacent.reserve"
sync
umount "$mount_root"
mounted=0
losetup --detach "$active_loop"
active_loop=
unset bitmap_candidate_by_byte

resolve_inode() {
    ntfsinfo -F "$2" "$1" |
        awk 'NR == 1 && $1 == "Dumping" && $2 == "Inode" {print $3}'
}
resolve_index_inode() {
    ntfsinfo -F "$2" "$1" |
        awk -v wanted="$3" \
            '$1 == "Dumping" && $2 == "attribute" && $3 == wanted {print $8}'
}
bitmap_inode=$(resolve_inode "$base" '/the one/repair-payloads/bitmap.bin')
live_inode=$(resolve_inode "$base" '/the one/repair-payloads/live-record.txt')
journal_overlap_inode=$(resolve_inode \
    "$base" '/the one/repair-payloads/journal-overlap.bin')
index_inode=$(resolve_index_inode "$base" '/the one/repair-index' '$INDEX_ROOT')
index_allocation_inode=$(resolve_index_inode \
    "$base" '/the one/repair-index' '$INDEX_ALLOCATION')
reconnect_inode=$(resolve_inode "$base" '/the one/orphan-source/reconnect.bin')
recovery_inode=$(resolve_inode "$base" '/the one/orphan-source/recovery.bin')
root_index_inode=$(resolve_index_inode "$base" '/' '$INDEX_ROOT')
root_index_allocation_inode=$(resolve_index_inode "$base" '/' '$INDEX_ALLOCATION')
the_one_inode=$(resolve_inode "$base" '/the one')
identity_parent_inode=$(resolve_index_inode \
    "$base" '/the one/identity-parent' '$INDEX_ROOT')
identity_target_inode=$(resolve_inode "$base" '/the one/identity-parent/required.bin')
attribute_list_inode=$(resolve_inode "$base" '/the one/deep/attrlist.bin')
large_attribute_list_inode=$(resolve_inode \
    "$base" '/the one/deep/large-attrlist.bin')
runlist_size_inode=$(resolve_inode "$base" '/the one/deep/runlist-size.bin')
deep_parent_inode=$(resolve_inode "$base" '/the one/deep')
link_inode=$(resolve_inode "$base" '/the one/deep/link-source.bin')
hardlink_inode=$(resolve_inode \
    "$base" '/the one/deep/collation-parent-a/shared.bin')
hardlink_parent_a_inode=$(resolve_inode \
    "$base" '/the one/deep/collation-parent-a')
hardlink_parent_b_inode=$(resolve_inode \
    "$base" '/the one/deep/collation-parent-b')
posix_collision_first_inode=$(resolve_inode \
    "$base" '/the one/deep/collation-parent-a/PosixName.bin')
posix_collision_second_inode=$(resolve_inode \
    "$base" '/the one/deep/collation-parent-a/posixname.bin')
python_parent_inode=$(resolve_inode "$base" '/the one/software/python/bin')
python_required_inode=$(resolve_inode \
    "$base" '/the one/software/python/bin/python')
python_donor_inode=$(resolve_inode \
    "$base" '/the one/software/python/bin/python4.13')
sparse_unit_inode=$(resolve_inode "$base" '/the one/deep/sparse-unit.bin')
duplicate_first_inode=$(resolve_inode "$base" '/the one/deep/duplicate-a.bin')
duplicate_second_inode=$(resolve_inode "$base" '/the one/deep/duplicate-b.bin')
compressed_inode=$(resolve_inode "$base" '/the one/deep/compressed/metadata.bin')
user_defined_inode=$(resolve_inode "$base" '/the one/deep/user-defined.bin')
unflagged_sparse_inode=$(resolve_inode "$base" '/the one/deep/unflagged-sparse.bin')
mapping_pair_tail_inode=$(resolve_inode "$base" '/the one/deep/mapping-pair-tail.bin')
attribute_end_tail_inode=$(resolve_inode "$base" '/the one/deep/attribute-end-tail.bin')
layout_candidate_inode=$(resolve_inode "$base" '/the one/deep/layout-candidate.bin')
for inode in "$bitmap_inode" "$live_inode" "$index_inode" "$index_allocation_inode" \
        "$reconnect_inode" "$recovery_inode" "$root_index_inode" \
        "$root_index_allocation_inode" "$the_one_inode" \
        "$identity_parent_inode" "$identity_target_inode" \
        "$attribute_list_inode" "$large_attribute_list_inode" \
        "$runlist_size_inode" "$deep_parent_inode" \
        "$link_inode" "$hardlink_inode" "$hardlink_parent_a_inode" \
        "$hardlink_parent_b_inode" "$posix_collision_first_inode" \
        "$posix_collision_second_inode" "$python_parent_inode" \
        "$python_required_inode" "$python_donor_inode" "$sparse_unit_inode" \
        "$duplicate_first_inode" "$duplicate_second_inode" \
        "$compressed_inode" "$user_defined_inode" "$unflagged_sparse_inode" \
        "$mapping_pair_tail_inode" "$attribute_end_tail_inode" \
        "$layout_candidate_inode" "$journal_overlap_inode"; do
    case "$inode" in ''|*[!0-9]*) echo "Invalid fixture inode: $inode" >&2; exit 1 ;; esac
done
python3 -B - "$work/posix-collision-clean.json" \
    "$hardlink_parent_a_inode" "$posix_collision_first_inode" \
    "$posix_collision_second_inode" <<'PY'
import json
import sys

state = {
    'kind': 'posix-collision-clean',
    'parent_inode': int(sys.argv[2]),
    'inodes': [int(sys.argv[3]), int(sys.argv[4])],
    'final_names': ['PosixName.bin', 'posixname.bin'],
    'required_anchor': False,
}
with open(sys.argv[1], 'w', encoding='utf-8') as handle:
    json.dump(state, handle, sort_keys=True)
    handle.write('\n')
PY
python3 -B - "$work/hardlink-collation.json" "$hardlink_inode" \
    "$hardlink_parent_a_inode" "$hardlink_parent_b_inode" <<'PY'
import json
import sys

state = {
    'kind': 'hardlink-collation',
    'inode': int(sys.argv[2]),
    'parent_inodes': [int(sys.argv[3]), int(sys.argv[4])],
    'target_name': 'shared.bin',
}
with open(sys.argv[1], 'w', encoding='utf-8') as handle:
    json.dump(state, handle, sort_keys=True)
    handle.write('\n')
PY
python3 -B - "$work/attribute-list-hardlink.json" "$attribute_list_inode" \
    "$hardlink_parent_a_inode" "$hardlink_parent_b_inode" <<'PY'
import json
import sys

state = {
    'kind': 'attribute-list-hardlink',
    'inode': int(sys.argv[2]),
    'parent_inodes': [int(sys.argv[3]), int(sys.argv[4])],
    'target_name': 'attrlist-shared.bin',
}
with open(sys.argv[1], 'w', encoding='utf-8') as handle:
    json.dump(state, handle, sort_keys=True)
    handle.write('\n')
PY
python3 -B - "$work/large-attribute-list.json" \
    "$large_attribute_list_inode" <<'PY'
import json
import sys

state = {'kind': 'large-attribute-list', 'inode': int(sys.argv[2])}
with open(sys.argv[1], 'w', encoding='utf-8') as handle:
    json.dump(state, handle, sort_keys=True)
    handle.write('\n')
PY
python3 -B - "$work/sparse-stream.json" "$sparse_unit_inode" <<'PY'
import json
import sys

state = {'kind': 'sparse-stream', 'inode': int(sys.argv[2])}
with open(sys.argv[1], 'w', encoding='utf-8') as handle:
    json.dump(state, handle, sort_keys=True)
    handle.write('\n')
PY
python3 "$fixtures" mutate fragment-data "$base" \
    --inode "$unflagged_sparse_inode" \
    --state "$work/fragment-data-preparation.json" >/dev/null
python3 - "$work/fragment-data-preparation.json" <<'PY'
import json
import re
import sys

state = json.load(open(sys.argv[1], encoding='utf-8'))
runs = state.get('runs')
if (
    state.get('kind') != 'fragment-data'
    or not isinstance(runs, list)
    or len(runs) < 2
    or any(not isinstance(run, list) or len(run) != 3 or run[1] is None for run in runs)
    or not re.fullmatch(r'[0-9a-f]{64}', str(state.get('content_sha256', '')))
):
    raise SystemExit(f'fragmented ordinary DATA preparation failed: {state!r}')
PY

clone() { cp --reflink=auto --sparse=always "$base" "$work/$1.ntfs"; }
layout_candidate_cases=(
    layout-attrs-offset-candidate
    layout-attrs-offset-ambiguous
    layout-bytes-in-use-candidate
    layout-bytes-in-use-ambiguous
    layout-bytes-in-use-dual-chain
    layout-next-instance-candidate
    layout-next-instance-wrap-candidate
    layout-resident-value-candidate
    layout-resident-name-candidate
    layout-resident-length-candidate
    layout-resident-ambiguous
)
file_name_cached_cases=(
    file-name-cached-timestamps
    file-name-cached-allocated-size
    file-name-cached-data-size
    file-name-cached-file-attributes
    file-name-cached-ea-reparse
)
file_name_stable_cases=(
    file-name-stable-parent
    file-name-stable-sequence
    file-name-stable-flags
)
posix_collision_negative_cases=(
    posix-collision-exact-duplicate
    posix-collision-mixed-namespace
    posix-collision-duplicate-reference
    posix-collision-required-anchor
)
for name in dirty-log boot-primary boot-backup mft-primary mft-mirror \
        bitmaps index-i30 orphan-parent orphan-recovery wal-one-torn \
        wal-both-torn wal-ambiguous identity-parent-index identity-root-index \
        attribute-list attribute-list-equal-triple-order large-attribute-list-boundary \
        large-attribute-list-boundary-overrun large-attribute-list-truncated \
        large-attribute-list-over-limit \
        runlist-size reparse-index secure-derived upcase-attrdef \
        secure-sii-stale upcase-nonascii user-defined-runlist \
        unflagged-sparse-run mapping-pair-tail attribute-end-tail \
        link-reciprocity hardlink-value-order sparse-unit-header \
        duplicate-cluster compressed-metadata \
        compressed-payload dirty-only-wiped-log \
        "${file_name_cached_cases[@]}" "${file_name_stable_cases[@]}" \
        "${posix_collision_negative_cases[@]}" \
        "${layout_candidate_cases[@]}"; do
    clone "$name"
done
for name in journal-mft-false-free journal-cluster-false-free \
        journal-duplicate-owner journal-mft-false-free-duplicate \
        journal-cluster-false-free-duplicate journal-duplicate-owner-one-torn \
        journal-duplicate-owner-preparing; do
    clone "$name"
done
python3 "$fixtures" mutate dirty-log "$work/dirty-log.ntfs" \
    --state "$work/dirty-log.json" >/dev/null
python3 "$fixtures" mutate boot-primary "$work/boot-primary.ntfs" >/dev/null
python3 "$fixtures" mutate boot-backup "$work/boot-backup.ntfs" >/dev/null
python3 "$fixtures" mutate mft-primary "$work/mft-primary.ntfs" >/dev/null
python3 "$fixtures" mutate mft-mirror "$work/mft-mirror.ntfs" >/dev/null
python3 "$fixtures" mutate bitmaps "$work/bitmaps.ntfs" \
    --allocated-inode "$bitmap_inode" --live-inode "$live_inode" \
    --state "$work/bitmaps.json" >/dev/null
python3 "$fixtures" mutate journal-mft-false-free \
    "$work/journal-mft-false-free.ntfs" --layout "$layout" \
    --state "$work/journal-mft-false-free.json" >/dev/null
python3 "$fixtures" mutate journal-cluster-false-free \
    "$work/journal-cluster-false-free.ntfs" --layout "$layout" \
    --state "$work/journal-cluster-false-free.json" >/dev/null
python3 "$fixtures" mutate journal-duplicate-owner \
    "$work/journal-duplicate-owner.ntfs" --layout "$layout" \
    --overlap-inode "$journal_overlap_inode" \
    --state "$work/journal-duplicate-owner.json" >/dev/null
python3 "$fixtures" mutate journal-mft-false-free-duplicate \
    "$work/journal-mft-false-free-duplicate.ntfs" --layout "$layout" \
    --overlap-inode "$journal_overlap_inode" \
    --state "$work/journal-mft-false-free-duplicate.json" >/dev/null
python3 "$fixtures" mutate journal-cluster-false-free-duplicate \
    "$work/journal-cluster-false-free-duplicate.ntfs" --layout "$layout" \
    --overlap-inode "$journal_overlap_inode" \
    --state "$work/journal-cluster-false-free-duplicate.json" >/dev/null
python3 "$fixtures" mutate journal-duplicate-owner \
    "$work/journal-duplicate-owner-one-torn.ntfs" --layout "$layout" \
    --overlap-inode "$journal_overlap_inode" \
    --state "$work/journal-duplicate-owner-one-torn.json" >/dev/null
python3 "$wal_fixtures" mutate one-torn \
    "$work/journal-duplicate-owner-one-torn.ntfs" "$layout" >/dev/null
python3 "$fixtures" mutate journal-duplicate-owner \
    "$work/journal-duplicate-owner-preparing.ntfs" --layout "$layout" \
    --overlap-inode "$journal_overlap_inode" \
    --state "$work/journal-duplicate-owner-preparing.json" >/dev/null
python3 "$wal_fixtures" mutate preparing-zero \
    "$work/journal-duplicate-owner-preparing.ntfs" "$layout" >/dev/null
python3 "$fixtures" mutate index-i30 "$work/index-i30.ntfs" \
    --index-inode "$index_inode" \
    --index-allocation-inode "$index_allocation_inode" >/dev/null
python3 "$fixtures" mutate index-reference "$work/identity-parent-index.ntfs" \
    --index-inode "$identity_parent_inode" --target-name required.bin \
    --target-inode "$identity_target_inode" \
    --state "$work/identity-parent.json" >/dev/null
python3 "$fixtures" mutate index-reference "$work/identity-root-index.ntfs" \
    --index-inode "$root_index_inode" --target-name 'the one' \
    --target-inode "$the_one_inode" \
    --index-allocation-inode "$root_index_allocation_inode" \
    --state "$work/identity-root.json" >/dev/null
python3 "$fixtures" mutate attribute-list "$work/attribute-list.ntfs" \
    --inode "$attribute_list_inode" --state "$work/attribute-list.json" >/dev/null
python3 "$fixtures" mutate attribute-list-equal-triple-order \
    "$work/attribute-list-equal-triple-order.ntfs" --inode "$attribute_list_inode" \
    --parent-inode "$hardlink_parent_a_inode" \
    --second-parent-inode "$hardlink_parent_b_inode" \
    --target-name attrlist-shared.bin \
    --state "$work/attribute-list-equal-triple-order.json" >/dev/null
python3 "$fixtures" mutate large-attribute-list-boundary \
    "$work/large-attribute-list-boundary.ntfs" \
    --inode "$large_attribute_list_inode" \
    --state "$work/large-attribute-list-boundary.json" >/dev/null
python3 "$fixtures" mutate large-attribute-list-boundary-overrun \
    "$work/large-attribute-list-boundary-overrun.ntfs" \
    --inode "$large_attribute_list_inode" \
    --state "$work/large-attribute-list-boundary-overrun.json" >/dev/null
python3 "$fixtures" mutate large-attribute-list-truncated \
    "$work/large-attribute-list-truncated.ntfs" \
    --inode "$large_attribute_list_inode" \
    --state "$work/large-attribute-list-truncated.json" >/dev/null
python3 "$fixtures" mutate large-attribute-list-over-limit \
    "$work/large-attribute-list-over-limit.ntfs" \
    --inode "$large_attribute_list_inode" \
    --state "$work/large-attribute-list-over-limit.json" >/dev/null
python3 "$fixtures" mutate runlist-size "$work/runlist-size.ntfs" \
    --inode "$runlist_size_inode" --state "$work/runlist-size.json" >/dev/null
python3 "$fixtures" mutate reparse-index "$work/reparse-index.ntfs" \
    --state "$work/reparse-index.json" >/dev/null
python3 "$fixtures" mutate secure-derived "$work/secure-derived.ntfs" \
    --state "$work/secure-derived.json" >/dev/null
python3 "$fixtures" mutate upcase-attrdef "$work/upcase-attrdef.ntfs" \
    --state "$work/upcase-attrdef.json" >/dev/null
python3 "$fixtures" mutate secure-sii-stale "$work/secure-sii-stale.ntfs" \
    --state "$work/secure-sii-stale.json" >/dev/null
python3 "$fixtures" mutate upcase-nonascii "$work/upcase-nonascii.ntfs" \
    --state "$work/upcase-nonascii.json" >/dev/null
python3 "$fixtures" mutate user-defined-runlist "$work/user-defined-runlist.ntfs" \
    --inode "$user_defined_inode" --stream-name userDefinedStream \
    --state "$work/user-defined-runlist.json" >/dev/null
python3 "$fixtures" mutate unflagged-sparse-run "$work/unflagged-sparse-run.ntfs" \
    --inode "$unflagged_sparse_inode" \
    --state "$work/unflagged-sparse-run.json" >/dev/null
python3 "$fixtures" mutate mapping-pair-tail "$work/mapping-pair-tail.ntfs" \
    --inode "$mapping_pair_tail_inode" \
    --state "$work/mapping-pair-tail.json" >/dev/null
python3 "$fixtures" mutate attribute-end-tail "$work/attribute-end-tail.ntfs" \
    --inode "$attribute_end_tail_inode" \
    --state "$work/attribute-end-tail.json" >/dev/null
python3 "$fixtures" mutate link-reciprocity "$work/link-reciprocity.ntfs" \
    --inode "$link_inode" --parent-inode "$deep_parent_inode" \
    --target-name link-second.bin --state "$work/link-reciprocity.json" >/dev/null
python3 "$fixtures" mutate hardlink-value-order \
    "$work/hardlink-value-order.ntfs" --inode "$hardlink_inode" \
    --parent-inode "$hardlink_parent_a_inode" \
    --second-parent-inode "$hardlink_parent_b_inode" \
    --target-name shared.bin --state "$work/hardlink-value-order.json" >/dev/null
for name in "${file_name_cached_cases[@]}" "${file_name_stable_cases[@]}"; do
    python3 "$fixtures" mutate "$name" "$work/$name.ntfs" \
        --inode "$hardlink_inode" --parent-inode "$hardlink_parent_a_inode" \
        --second-parent-inode "$hardlink_parent_b_inode" \
        --target-name shared.bin --state "$work/$name.json" >/dev/null
done
for name in posix-collision-exact-duplicate posix-collision-mixed-namespace \
        posix-collision-duplicate-reference; do
    python3 "$fixtures" mutate "$name" "$work/$name.ntfs" \
        --parent-inode "$hardlink_parent_a_inode" \
        --inode "$posix_collision_first_inode" \
        --second-inode "$posix_collision_second_inode" \
        --target-name PosixName.bin --second-target-name posixname.bin \
        --state "$work/$name.json" >/dev/null
done
python3 "$fixtures" mutate posix-collision-required-anchor \
    "$work/posix-collision-required-anchor.ntfs" \
    --parent-inode "$python_parent_inode" --inode "$python_required_inode" \
    --second-inode "$python_donor_inode" --target-name python \
    --second-target-name python4.13 \
    --state "$work/posix-collision-required-anchor.json" >/dev/null
python3 "$fixtures" mutate sparse-unit-header "$work/sparse-unit-header.ntfs" \
    --inode "$sparse_unit_inode" --state "$work/sparse-unit-header.json" >/dev/null
python3 "$fixtures" mutate duplicate-cluster "$work/duplicate-cluster.ntfs" \
    --first-inode "$duplicate_first_inode" --second-inode "$duplicate_second_inode" \
    --state "$work/duplicate-cluster.json" >/dev/null
python3 "$fixtures" mutate compressed-metadata "$work/compressed-metadata.ntfs" \
    --inode "$compressed_inode" --state "$work/compressed-metadata.json" >/dev/null
python3 "$fixtures" mutate compressed-payload "$work/compressed-payload.ntfs" \
    --inode "$compressed_inode" --state "$work/compressed-payload.json" >/dev/null
python3 "$fixtures" mutate volume-dirty-wiped-log "$work/dirty-only-wiped-log.ntfs" \
    --state "$work/dirty-only-wiped-log.json" >/dev/null
for layout_case in "${layout_candidate_cases[@]}"; do
    python3 "$fixtures" mutate "$layout_case" "$work/$layout_case.ntfs" \
        --inode "$layout_candidate_inode" --state "$work/$layout_case.json" \
        >/dev/null
done

make_orphan() {
    image=$1
    inode=$2
    relative_path=$3
    bad_parent=$4
    snapshot="$image.snapshot.json"
    python3 "$fixtures" snapshot-orphan "$image" "$inode" "$snapshot"
    active_loop=$(losetup --find --show "$image")
    mount.ntfs-3g -o rw,permissions,windows_names,big_writes \
        "$active_loop" "$mount_root"
    mounted=1
    rm -- "$mount_root/$relative_path"
    sync
    umount "$mount_root"
    mounted=0
    losetup --detach "$active_loop"
    active_loop=
    restore_args=()
    [ "$bad_parent" = false ] || restore_args+=(--bad-parent)
    python3 "$fixtures" restore-orphan "$image" "$snapshot" \
        "${restore_args[@]}" >/dev/null
}
make_orphan "$work/orphan-parent.ntfs" "$reconnect_inode" \
    'the one/orphan-source/reconnect.bin' false
make_orphan "$work/orphan-recovery.ntfs" "$recovery_inode" \
    'the one/orphan-source/recovery.bin' true

python3 "$wal_fixtures" mutate one-torn "$work/wal-one-torn.ntfs" "$layout" >/dev/null
python3 "$wal_fixtures" mutate both-torn "$work/wal-both-torn.ntfs" "$layout" >/dev/null
python3 "$wal_fixtures" mutate equal-generation-divergent \
    "$work/wal-ambiguous.ntfs" "$layout" >/dev/null
python3 "$wal_fixtures" inspect "$base" "$layout" --expect healthy >/dev/null
python3 "$wal_fixtures" inspect "$work/wal-one-torn.ntfs" "$layout" \
    --expect degraded >/dev/null
python3 "$wal_fixtures" inspect "$work/wal-both-torn.ntfs" "$layout" \
    --expect invalid >/dev/null
python3 "$wal_fixtures" inspect "$work/wal-ambiguous.ntfs" "$layout" \
    --expect ambiguous >/dev/null
python3 "$fixtures" inspect "$base" >"$work/clean.json"
python3 "$fixtures" inspect "$base" --state "$work/hardlink-collation.json" \
    >"$work/hardlink-collation-inspect.json"
python3 "$fixtures" inspect "$base" --state "$work/posix-collision-clean.json" \
    >"$work/posix-collision-clean-inspect.json"
python3 "$fixtures" inspect "$base" --state "$work/attribute-list-hardlink.json" \
    >"$work/attribute-list-hardlink-inspect.json"
python3 "$fixtures" inspect "$base" --state "$work/large-attribute-list.json" \
    >"$work/large-attribute-list-inspect.json"
python3 "$fixtures" inspect "$base" --state "$work/sparse-stream.json" \
    >"$work/sparse-stream-inspect.json"
python3 "$fixtures" inspect "$work/bitmaps.ntfs" --state "$work/bitmaps.json" \
    >"$work/bitmaps-inspect.json"
python3 "$fixtures" inspect "$work/identity-parent-index.ntfs" \
    --state "$work/identity-parent.json" >"$work/identity-parent-inspect.json"
python3 "$fixtures" inspect "$work/identity-root-index.ntfs" \
    --state "$work/identity-root.json" >"$work/identity-root-inspect.json"
for deep_name in dirty-log attribute-list attribute-list-equal-triple-order \
        large-attribute-list-boundary large-attribute-list-boundary-overrun \
        large-attribute-list-truncated \
        large-attribute-list-over-limit \
        runlist-size reparse-index secure-derived \
        upcase-attrdef secure-sii-stale upcase-nonascii user-defined-runlist \
        unflagged-sparse-run mapping-pair-tail attribute-end-tail \
        link-reciprocity hardlink-value-order sparse-unit-header \
        duplicate-cluster compressed-metadata \
        compressed-payload dirty-only-wiped-log \
        "${file_name_cached_cases[@]}" "${file_name_stable_cases[@]}" \
        "${posix_collision_negative_cases[@]}" \
        "${layout_candidate_cases[@]}"; do
    python3 "$fixtures" inspect "$work/$deep_name.ntfs" \
        --state "$work/$deep_name.json" >"$work/$deep_name-inspect.json"
done
for journal_name in journal-mft-false-free journal-cluster-false-free \
        journal-duplicate-owner journal-mft-false-free-duplicate \
        journal-cluster-false-free-duplicate journal-duplicate-owner-one-torn \
        journal-duplicate-owner-preparing; do
    python3 "$fixtures" inspect "$work/$journal_name.ntfs" \
        --state "$work/$journal_name.json" \
        >"$work/$journal_name-inspect.json"
done
python3 - "$work/clean.json" "$work/bitmaps-inspect.json" \
    "$work/identity-parent-inspect.json" "$work/identity-root-inspect.json" <<'PY'
import json
import sys

clean = json.load(open(sys.argv[1], encoding="utf-8"))
corrupt = json.load(open(sys.argv[2], encoding="utf-8"))
for field in ("boot_equal", "primary_boot_ntfs", "backup_boot_ntfs", "mft_mirror_equal"):
    if clean.get(field) is not True:
        raise SystemExit(f"clean raw fixture invariant failed: {field}")
expected = {
    "allocated_cluster": False,
    "free_cluster": True,
    "live_inode": False,
    "unused_inode": True,
}
bitmap = corrupt.get("bitmap_state")
if not isinstance(bitmap, dict) or any(
    bitmap.get(field) is not value for field, value in expected.items()
):
    raise SystemExit(f"bitmap fixture differs: {bitmap!r}")
for prefix in ("cluster", "mft"):
    set_mask = bitmap.get(f"{prefix}_set_mask")
    clear_mask = bitmap.get(f"{prefix}_clear_mask")
    if (
        bitmap.get(f"{prefix}_byte") != bitmap.get(f"{prefix}_corrupt_byte")
        or not isinstance(set_mask, int)
        or not isinstance(clear_mask, int)
        or not set_mask
        or not clear_mask
        or set_mask & clear_mask
        or bitmap[f"{prefix}_byte"] & set_mask
        or not bitmap[f"{prefix}_byte"] & clear_mask
    ):
        raise SystemExit(f"{prefix} bitmap byte lacks mixed false-free/false-used bits: {bitmap!r}")
for path in sys.argv[3:]:
    identity = json.load(open(path, encoding="utf-8")).get("index_reference")
    if not isinstance(identity, dict) or identity.get("valid") is not False:
        raise SystemExit(f"identity-index fixture did not break only its reference: {identity!r}")
PY

python3 - "$work" <<'PY'
import json
import hashlib
from pathlib import Path
import sys

root = Path(sys.argv[1])
def pair(name):
    state = json.loads((root / f'{name}.json').read_text())
    seen = json.loads((root / f'{name}-inspect.json').read_text())
    return state, seen

hardlink_state = json.loads((root / 'hardlink-collation.json').read_text())
hardlink = json.loads(
    (root / 'hardlink-collation-inspect.json').read_text()
).get('hardlink_collation')
if (
    not isinstance(hardlink, dict)
    or hardlink_state['parent_inodes'] != sorted(hardlink_state['parent_inodes'])
    or hardlink.get('link_count') != 2
    or hardlink.get('file_name_count') != 2
    or hardlink.get('resident_parent_order') != hardlink_state['parent_inodes']
    or hardlink.get('attribute_instances') == sorted(hardlink.get('attribute_instances', []))
    or hardlink.get('values_distinct') is not True
    or hardlink.get('values_collated') is not True
    or hardlink.get('all_reciprocal') is not True
    or len(hardlink.get('index_copies', [])) != 2
    or any(
        item.get('reciprocal') is not True
        or item.get('semantic_key_match') is not True
        for item in hardlink.get('index_copies', [])
    )
):
    raise SystemExit(f'clean hardlink resident-value collation failed: {hardlink!r}')

state, seen = pair('posix-collision-clean')
value = seen.get('posix_collision')
if not (
    isinstance(value, dict)
    and value.get('canonical_collision') is True
    and value.get('exact_utf16_duplicate') is False
    and value.get('all_posix') is True
    and value.get('unique_entry_references') is True
    and value.get('all_reciprocal') is True
    and len(value.get('members', [])) == 2
    and [member.get('entry_name') for member in value.get('members', [])]
    == state.get('final_names')
    and all(
        member.get('entry_flags_valid') is True
        and member.get('stable_key_match') is True
        and member.get('reciprocal') is True
        for member in value.get('members', [])
    )
):
    raise SystemExit(f'clean POSIX case-collision oracle failed: {value!r}')

collision_expectations = {
    'posix-collision-exact-duplicate': (True, True, True, True, True, False),
    'posix-collision-mixed-namespace': (True, False, False, True, True, False),
    'posix-collision-duplicate-reference': (True, False, True, False, False, False),
    'posix-collision-required-anchor': (True, False, True, True, True, True),
}
for name, expected in collision_expectations.items():
    state, seen = pair(name)
    value = seen.get('posix_collision')
    observed = (
        value.get('canonical_collision'),
        value.get('exact_utf16_duplicate'),
        value.get('all_posix'),
        value.get('all_reciprocal'),
        value.get('unique_entry_references'),
        value.get('required_anchor'),
    ) if isinstance(value, dict) else None
    if observed != expected or len(value.get('members', [])) != 2:
        raise SystemExit(
            f'POSIX collision negative oracle failed for {name}: {value!r}'
        )

cached_fields = {
    'file-name-cached-timestamps': 'timestamps',
    'file-name-cached-allocated-size': 'allocated-size',
    'file-name-cached-data-size': 'data-size',
    'file-name-cached-file-attributes': 'file-attributes',
    'file-name-cached-ea-reparse': 'ea-reparse',
}
for name, field in cached_fields.items():
    state, seen = pair(name)
    value = seen.get('file_name_index_field')
    copy = value.get('mutated_copy') if isinstance(value, dict) else None
    if not (
        isinstance(value, dict)
        and isinstance(copy, dict)
        and state.get('mutation_class') == 'cached'
        and state.get('field') == field
        and value.get('field') == field
        and value.get('link_count') == 2
        and value.get('file_name_count') == 2
        and value.get('all_reciprocal') is True
        and copy.get('semantic_key_match') is True
        and copy.get('entry_flags_valid') is True
        and copy.get('reciprocal') is True
        and field in copy.get('cached_differences', [])
        and copy.get('cached_difference_count', 0) >= 1
        and copy.get('key_sha256') == state.get('key_after_sha256')
        and copy.get('key_sha256') != state.get('key_before_sha256')
        and copy.get('file_name_value_sha256')
        == state.get('file_name_value_sha256')
    ):
        raise SystemExit(f'cached FILE_NAME normalization oracle failed for {name}: {value!r}')

for name in (
    'file-name-stable-parent',
    'file-name-stable-sequence',
    'file-name-stable-flags',
):
    state, seen = pair(name)
    value = seen.get('file_name_index_field')
    copy = value.get('mutated_copy') if isinstance(value, dict) else None
    if not (
        isinstance(value, dict)
        and isinstance(copy, dict)
        and state.get('mutation_class') == 'stable'
        and value.get('link_count') == 2
        and value.get('file_name_count') == 2
        and value.get('all_reciprocal') is False
        and copy.get('reciprocal') is False
        and copy.get('semantic_key_match')
        is state.get('expected_semantic_key_match')
        and copy.get('entry_flags_valid')
        is state.get('expected_entry_flags_valid')
        and copy.get('file_name_value_sha256')
        == state.get('file_name_value_sha256')
    ):
        raise SystemExit(f'stable FILE_NAME mismatch oracle failed for {name}: {value!r}')

attribute_list_hardlink_state = json.loads(
    (root / 'attribute-list-hardlink.json').read_text()
)
attribute_list_hardlink = json.loads(
    (root / 'attribute-list-hardlink-inspect.json').read_text()
).get('attribute_list_hardlink')
if (
    not isinstance(attribute_list_hardlink, dict)
    or attribute_list_hardlink.get('link_count') != 3
    or attribute_list_hardlink.get('selected_file_name_count') != 2
    or attribute_list_hardlink.get('file_name_entry_count', 0) < 3
    or attribute_list_hardlink.get('attribute_list_entry_count', 0) <= 3
    or attribute_list_hardlink.get('ale_parent_order')
    != attribute_list_hardlink_state['parent_inodes']
    or attribute_list_hardlink.get('resolved_values_distinct') is not True
    or attribute_list_hardlink.get('resolved_values_collated') is not True
    or attribute_list_hardlink.get('instances_nonmonotonic') is not True
    or attribute_list_hardlink.get('all_entries_resolved') is not True
    or attribute_list_hardlink.get('all_reciprocal') is not True
    or len(attribute_list_hardlink.get('index_copies', [])) != 2
    or any(
        item.get('semantic_key_match') is not True
        or item.get('reciprocal') is not True
        for item in attribute_list_hardlink.get('index_copies', [])
    )
):
    raise SystemExit(
        'clean ATTRIBUTE_LIST/resident FILE_NAME collation failed: '
        f'{attribute_list_hardlink!r}'
    )

large_attribute_list = json.loads(
    (root / 'large-attribute-list-inspect.json').read_text()
).get('large_attribute_list')
large_runs = large_attribute_list.get('runs', []) if isinstance(large_attribute_list, dict) else []
if (
    not isinstance(large_attribute_list, dict)
    or large_attribute_list.get('nonresident') is not True
    or large_attribute_list.get('logical_size') != 0x40000
    or large_attribute_list.get('initialized_size') != large_attribute_list.get('logical_size')
    or large_attribute_list.get('allocated_size', 0) < large_attribute_list.get('logical_size', 0)
    or large_attribute_list.get('run_count') != len(large_runs)
    or not large_runs
    or any(run[1] is None or run[2] <= 0 for run in large_runs)
    or large_attribute_list.get('entry_count') != 493
    or large_attribute_list.get('bound_entry_count') != large_attribute_list.get('entry_count')
    or large_attribute_list.get('unique_binding_count') != large_attribute_list.get('entry_count')
    or large_attribute_list.get('storage_record_count') != 489
    or large_attribute_list.get('extension_record_count') != 488
    or large_attribute_list.get('full_length_named_data_count') != 488
    or large_attribute_list.get('cap_tail_named_data_count') != 1
    or large_attribute_list.get('max_name_length') != 255
    or large_attribute_list.get('all_entries_bound') is not True
    or large_attribute_list.get('boundary_limit') != 256 * 1024
    or large_attribute_list.get('boundary_entry_relation') != 'ENDS_AT_LIMIT'
    or large_attribute_list.get('boundary_entry_offset', 0) < 0
    or large_attribute_list.get('boundary_entry_end') != 0x40000
    or large_attribute_list.get('read_fault_logical_offset') != 0x3ffff
    or large_attribute_list.get('read_fault_physical_offset', 0) <= 0
    or len(str(large_attribute_list.get('stream_sha256', ''))) != 64
):
    raise SystemExit(
        f'clean streaming exact-256-KiB ATTRIBUTE_LIST census failed: {large_attribute_list!r}'
    )

sparse = json.loads(
    (root / 'sparse-stream-inspect.json').read_text()
).get('sparse_stream')
expected_sparse = b'H' * 4096 + bytes(62 * 4096) + b'T' * 4096
runs = sparse.get('runs', []) if isinstance(sparse, dict) else []
if (
    not isinstance(sparse, dict)
    or sparse.get('attribute_flags') != 0x8000
    or sparse.get('record_attrs_offset') != 56
    or sparse.get('record_bytes_in_use') != 368
    or sparse.get('record_next_attr_instance') != 3
    or sparse.get('attribute_record_offset') != 272
    or sparse.get('attribute_record_length') != 88
    or sparse.get('compression_unit') != 4
    or sparse.get('data_size') != 64 * 4096
    or sparse.get('initialized_size') != 64 * 4096
    or sparse.get('allocated_size') != 64 * 4096
    or sparse.get('compressed_size') != 2 * 4096
    or sparse.get('physical_bytes') != 2 * 4096
    or sparse.get('logical_clusters') != 64
    or sparse.get('mapped_clusters') != 2
    or sparse.get('sparse_clusters') != 62
    or len(runs) != 3
    or runs[0][0] != 0 or not isinstance(runs[0][1], int) or runs[0][2] != 1
    or runs[1] != [1, None, 62]
    or runs[2][0] != 63 or not isinstance(runs[2][1], int) or runs[2][2] != 1
    or sparse.get('runlist_complete') is not True
    or sparse.get('tail_run_mapped') is not True
    or sparse.get('mapped_lcns_distinct') is not True
    or sparse.get('mapped_cluster_bits') != [True, True]
    or sparse.get('mft_bitmap_bit') is not True
    or sparse.get('hole_all_zero') is not True
    or sparse.get('mapping_pairs_offset') != 72
    or sparse.get('mapping_pairs_record_offset') != 344
    or sparse.get('terminator_attribute_offset') != 82
    or sparse.get('terminator_record_offset') != 354
    or sparse.get('mapping_tail_record_offset') != 355
    or sparse.get('mapping_tail_length') != 5
    or sparse.get('mapping_tail_hex') != 'ff00000000'
    or sparse.get('mapping_tail_all_zero') is not False
    or sparse.get('mapping_tail_pinned_producer_slack') is not True
    or sparse.get('mapping_tail_opaque_slack') is not True
    or sparse.get('mapping_tail_accepted_slack') is not True
    or sparse.get('head_sha256') != hashlib.sha256(b'H' * 4096).hexdigest()
    or sparse.get('tail_sha256') != hashlib.sha256(b'T' * 4096).hexdigest()
    or sparse.get('logical_sha256') != hashlib.sha256(expected_sparse).hexdigest()
):
    raise SystemExit(f'clean genuine sparse-stream census failed: {sparse!r}')

state, seen = pair('attribute-list')
value = seen.get('attribute_list')
if not isinstance(value, dict) or value.get('valid') is not False or value.get('extent_valid') is not True:
    raise SystemExit(f'attribute-list raw oracle failed: {value!r}')

state, seen = pair('attribute-list-equal-triple-order')
value = seen.get('attribute_list_hardlink')
if (
    not isinstance(value, dict)
    or value.get('link_count') != 3
    or value.get('resolved_values_collated') is not False
    or value.get('all_entries_resolved') is not True
    or value.get('all_reciprocal') is not True
    or value.get('ale_instance_order') != state['ale_instance_order']
    or value.get('ale_record_order') != state['ale_record_order']
    or sorted(value.get('value_sha256_in_ale_order', [])) != state['value_sha256']
    or state.get('permitted_equal_triple_order') is not True
    or value.get('ale_parent_order') != state['permuted_ale_parent_order']
    or value.get('ale_parent_order') == state['original_ale_parent_order']
):
    raise SystemExit(f'ATTRIBUTE_LIST equal-triple order acceptance oracle failed: {value!r}')

state, seen = pair('large-attribute-list-boundary')
value = seen.get('large_attribute_list_boundary')
if (
    not isinstance(value, dict)
    or value.get('nonresident') is not True
    or value.get('logical_size') != state['logical_size']
    or value.get('logical_size') != 0x40000
    or value.get('entry_count') != state['entry_count']
    or value.get('entry_offset') != state['entry_offset']
    or value.get('entry_length') != state['entry_length']
    or value.get('extent_inode') != state['extent_inode']
    or value.get('extent_sequence') != state['expected_sequence']
    or value.get('reference_sequence') != state['wrong_sequence']
    or value.get('reference_sequence') == value.get('extent_sequence')
    or value.get('stream_sha256') != state['stream_after_sha256']
    or value.get('stream_sha256') == state['stream_before_sha256']
):
    raise SystemExit(f'large ATTRIBUTE_LIST boundary raw oracle failed: {value!r}')

state, seen = pair('large-attribute-list-boundary-overrun')
value = seen.get('large_attribute_list_boundary_overrun')
if (
    not isinstance(value, dict)
    or value.get('nonresident') is not True
    or value.get('logical_size') != 0x40000
    or value.get('initialized_size') != 0x40000
    or value.get('entry_offset') != state['entry_offset']
    or value.get('entry_length') != state['wrong_entry_length']
    or value.get('claimed_entry_end') != state['claimed_entry_end']
    or value.get('claimed_entry_end') != 0x40008
    or value.get('stream_sha256') != state['stream_after_sha256']
    or value.get('stream_sha256') == state['stream_before_sha256']
    or value.get('tail_hex') != state['tail_hex']
    or value.get('parse_rejected') is not True
    or value.get('parsed_entries') != 0
):
    raise SystemExit(
        f'large ATTRIBUTE_LIST boundary-overrun raw oracle failed: {value!r}'
    )

state, seen = pair('large-attribute-list-truncated')
value = seen.get('large_attribute_list_truncated')
if (
    not isinstance(value, dict)
    or value.get('nonresident') is not True
    or state['original_logical_size'] != 0x40000
    or state['truncated_size'] != 0x3ffff
    or value.get('logical_size') != state['truncated_size']
    or value.get('initialized_size') != state['truncated_size']
    or value.get('allocated_size') != state['allocated_size']
    or value.get('prefix_sha256') != state['prefix_sha256']
    or value.get('tail_hex') != state['truncated_tail_hex']
    or value.get('parse_rejected') is not True
    or value.get('parsed_entries') != 0
):
    raise SystemExit(f'large ATTRIBUTE_LIST truncation raw oracle failed: {value!r}')

state, seen = pair('large-attribute-list-over-limit')
value = seen.get('large_attribute_list_over_limit')
if (
    not isinstance(value, dict)
    or value.get('nonresident') is not True
    or value.get('maximum_valid_size') != 0x40000
    or value.get('logical_size') != 0x40008
    or value.get('initialized_size') != 0x40008
    or value.get('logical_size') != state['over_limit_size']
    or value.get('allocated_size') != state['allocated_size']
    or value.get('highest_vcn') != state['highest_vcn']
    or value.get('runs') != state['expanded_runs']
    or value.get('entry_count') != state['entry_count']
    or value.get('bound_entry_count') != state['bound_entry_count']
    or value.get('last_entry_offset') != state['last_entry_offset']
    or value.get('last_entry_length') != state['last_entry_length']
    or value.get('last_entry_end') != state['over_limit_size']
    or value.get('appended_lcn') != state['appended_lcn']
    or value.get('appended_cluster_bitmap_set') is not True
    or value.get('mapping_hex') != state['mapping_after_hex']
    or value.get('mapping_hex') == state['mapping_before_hex']
    or value.get('opaque_mapping_slack_hex') != state['opaque_mapping_slack_hex']
    or value.get('valid_prefix_sha256') != state['valid_prefix_sha256']
    or value.get('stream_sha256') != state['stream_sha256']
):
    raise SystemExit(f'over-limit ATTRIBUTE_LIST raw oracle failed: {value!r}')

state, seen = pair('dirty-log')
value = seen.get('dirty_log')
if (
    not isinstance(value, dict)
    or not value.get('primary_flags', 0) & 1
    or not value.get('mirror_flags', 0) & 1
    or value.get('logfile_size') != state['logfile_size']
    or value.get('restart_magic') != ['RSTR', 'RSTR']
    or value.get('restart_usa') != [0xA101, 0xA102]
    or len(value.get('restart_page_sha256', [])) != 2
):
    raise SystemExit(f'zero-LSN dirty-log raw oracle failed: {value!r}')

state, seen = pair('runlist-size')
value = seen.get('runlist_size')
if (
    not isinstance(value, dict)
    or value.get('initialized_size') != state['wrong_initialized_size']
    or value.get('data_size') != state['data_size']
    or value.get('content_sha256') != state['content_sha256']
):
    raise SystemExit(f'runlist-size raw oracle failed: {value!r}')

_, seen = pair('reparse-index')
if seen.get('reparse_index', {}).get('reserved') != '5a0000':
    raise SystemExit(f'reparse-index raw oracle failed: {seen!r}')

state, seen = pair('secure-derived')
value = seen.get('secure_derived')
if (
    not isinstance(value, dict)
    or value.get('sds_equal') is not False
    or value.get('sds_primary_sha256') != state['sds_primary_sha256']
    or value.get('index_reserved') != {'$SDH': '5a0000', '$SII': '5a0000'}
):
    raise SystemExit(f'$Secure raw oracle failed: {value!r}')

state, seen = pair('upcase-attrdef')
value = seen.get('upcase_attrdef')
if (
    not isinstance(value, dict)
    or value.get('upcase_value') != state['upcase_wrong']
    or value.get('attrdef_type') != state['attrdef_wrong_type']
):
    raise SystemExit(f'UpCase/AttrDef raw oracle failed: {value!r}')

state, seen = pair('secure-sii-stale')
value = seen.get('secure_sii_stale')
if (
    not isinstance(value, dict)
    or value.get('security_id') != state['security_id']
    or value.get('sds_offset') != state['stale_sds_offset']
    or value.get('sds_length') != state['sds_length']
):
    raise SystemExit(f'$Secure/$SII stale-entry raw oracle failed: {value!r}')

state, seen = pair('upcase-nonascii')
value = seen.get('upcase_nonascii')
if (
    not isinstance(value, dict)
    or value.get('stream_size') != state['stream_size']
    or value.get('codepoint') != state['codepoint']
    or value.get('mapping') != state['wrong_mapping']
):
    raise SystemExit(f'non-ASCII $UpCase raw oracle failed: {value!r}')

state, seen = pair('user-defined-runlist')
value = seen.get('user_defined_runlist')
if (
    not isinstance(value, dict)
    or value.get('type') != state['user_defined_type']
    or value.get('mapping_hex') != state['after_mapping_hex']
    or value.get('mapping_hex') == state['before_mapping_hex']
):
    raise SystemExit(f'user-defined runlist raw oracle failed: {value!r}')

state, seen = pair('unflagged-sparse-run')
value = seen.get('unflagged_sparse_run')
original_runs = state['original_runs']
mutated_runs = state['mutated_runs']
if (
    not isinstance(value, dict)
    or state['attribute_flags'] != 0
    or value.get('attribute_flags') != 0
    or value.get('attribute_instance') != state['attribute_instance']
    or any(run[1] is None for run in original_runs)
    or value.get('runs') != mutated_runs
    or value.get('sparse_run_count') != 1
    or mutated_runs[:-1] != original_runs[:-1]
    or mutated_runs[-1][0] != original_runs[-1][0]
    or mutated_runs[-1][1] is not None
    or mutated_runs[-1][2] != original_runs[-1][2]
    or value.get('terminator_record_offset') != state['mutated_terminator_record_offset']
    or value.get('mapping_hex') != state['after_mapping_hex']
    or value.get('mapping_hex') == state['before_mapping_hex']
    or value.get('tail_hex') != state['mutated_tail_hex']
    or state.get('opaque_post_terminator_slack') is not True
):
    raise SystemExit(f'unflagged sparse-run raw oracle failed: {value!r}')

state, seen = pair('mapping-pair-tail')
value = seen.get('mapping_pair_tail')
expected_tail = bytes((state['tail_value'],)) + bytes(state['tail_length'] - 1)
if (
    not isinstance(value, dict)
    or state['before_tail_hex'] != bytes(state['tail_length']).hex()
    or value.get('attribute_flags') != state['attribute_flags']
    or value.get('attribute_instance') != state['attribute_instance']
    or value.get('runs') != state['runs']
    or value.get('encoded_mapping_hex') != state['encoded_mapping_hex']
    or value.get('encoded_mapping_sha256') != state['encoded_mapping_sha256']
    or value.get('terminator_record_offset') != state['terminator_record_offset']
    or value.get('tail_record_offset') != state['tail_record_offset']
    or value.get('tail_hex') != expected_tail.hex()
    or value.get('tail_nonzero_record_offsets') != [state['tail_record_offset']]
    or value.get('opaque_ignored_slack') is not True
):
    raise SystemExit(f'mapping-pair trailing-byte raw oracle failed: {value!r}')

layout_cases = (
    'layout-attrs-offset-candidate',
    'layout-attrs-offset-ambiguous',
    'layout-bytes-in-use-candidate',
    'layout-bytes-in-use-ambiguous',
    'layout-bytes-in-use-dual-chain',
    'layout-next-instance-candidate',
    'layout-next-instance-wrap-candidate',
    'layout-resident-value-candidate',
    'layout-resident-name-candidate',
    'layout-resident-length-candidate',
    'layout-resident-ambiguous',
)
for name in layout_cases:
    state, seen = pair(name)
    value = seen.get('layout_candidate')
    canonical = state.get('canonical', {})
    ranges = state.get('changed_ranges', [])
    observed_ranges = value.get('changed_ranges', []) if isinstance(value, dict) else []
    if (
        not isinstance(value, dict)
        or state.get('kind') != name
        or state.get('typed_action_id') != 7
        or state.get('typed_apply_required') is not True
        or state.get('expected_check_result') != 'unsafe'
        or state.get('expected_repair_result') not in (
            'refused-no-write-until-ID7', 'success-after-fresh-rescan'
        )
        or value.get('kind') != name
        or value.get('inode') != state.get('inode')
        or value.get('record_device_offset') != state.get('record_device_offset')
        or value.get('record_size') != state.get('record_size')
        or value.get('typed_action_id') != 7
        or value.get('typed_apply_required') is not True
        or value.get('evidence_class') != state.get('evidence_class')
        or value.get('record_sha256') != state.get('after_record_sha256')
        or value.get('raw_record_sha256') != state.get('after_raw_record_sha256')
        or value.get('reconstructed_before_sha256') != state.get('before_record_sha256')
        or value.get('unchanged_bytes_sha256') != state.get('unchanged_bytes_sha256')
        or value.get('resident_name_sha256') != state.get('resident_name_after_sha256')
        or value.get('resident_value_sha256') != state.get('resident_value_after_sha256')
        or value.get('changed_ranges_match') is not True
        or len(ranges) == 0
        or len(observed_ranges) != len(ranges)
        or any(
            observed.get('record_offset') != expected.get('record_offset')
            or observed.get('device_offset') != expected.get('device_offset')
            or observed.get('length') != expected.get('length')
            or observed.get('current_hex') != expected.get('after_hex')
            or observed.get('matches_after') is not True
            for observed, expected in zip(observed_ranges, ranges)
        )
    ):
        raise SystemExit(f'{name} raw byte-range oracle failed: {value!r}')
    if name.startswith('layout-attrs-offset'):
        expected = canonical['attrs_offset'] + 8
        if value.get('attrs_offset') != expected:
            raise SystemExit(f'{name} attrs_offset candidate drifted: {value!r}')
    elif name.startswith('layout-bytes-in-use'):
        expected = canonical['bytes_in_use'] - 8
        if value.get('bytes_in_use') != expected:
            raise SystemExit(f'{name} bytes_in_use candidate drifted: {value!r}')
        if name == 'layout-bytes-in-use-dual-chain' and (
            value.get('plausible_bytes_in_use_candidates')
            != [canonical['bytes_in_use'], canonical['bytes_in_use'] + 8]
            or value.get('second_at_end_hex') != 'ffffffff00000000'
            or state.get('evidence_class') != 'AMBIGUOUS_MULTIPLE_PACKED_ENDS'
        ):
            raise SystemExit(f'{name} dual packed-end oracle drifted: {value!r}')
    elif name in ('layout-next-instance-candidate', 'layout-next-instance-wrap-candidate'):
        expected_max = 0xffff if name.endswith('-wrap-candidate') else canonical['max_attribute_instance']
        if (
            value.get('candidate_max_attribute_instance') != expected_max
            or value.get('expected_repaired_next_attr_instance') != ((expected_max + 1) & 0xffff)
            or value.get('next_attr_instance') != (1 if name.endswith('-wrap-candidate') else expected_max)
            or value.get('prepared_instance_value') != (0xffff if name.endswith('-wrap-candidate') else None)
            or state.get('evidence_class') != 'DERIVABLE_ALLOCATOR_CURSOR'
            or state.get('repair_required') is not True
            or state.get('expected_repair_result') != 'success-after-fresh-rescan'
        ):
            raise SystemExit(f'{name} allocator-cursor oracle drifted: {value!r}')
    elif name in ('layout-resident-value-candidate', 'layout-resident-ambiguous'):
        if value.get('resident_value_offset') != canonical['resident_value_offset'] + 1:
            raise SystemExit(f'{name} resident value-offset oracle drifted: {value!r}')
    if name in ('layout-resident-name-candidate', 'layout-resident-ambiguous'):
        if value.get('resident_name_offset') != canonical['resident_name_offset'] + 1:
            raise SystemExit(f'{name} resident name-offset oracle drifted: {value!r}')
    if name in ('layout-resident-length-candidate', 'layout-resident-ambiguous'):
        if value.get('resident_record_length') != canonical['resident_record_length'] + 1:
            raise SystemExit(f'{name} resident length oracle drifted: {value!r}')
    if name.startswith('layout-next-instance-'):
        pass
    elif name.endswith('-candidate'):
        if (
            state.get('evidence_class') != 'DERIVABLE_LAYOUT_CANDIDATE'
            or value.get('resident_name_sha256') != canonical['resident_name_sha256']
            or value.get('resident_value_sha256') != canonical['resident_value_sha256']
        ):
            raise SystemExit(f'{name} did not preserve candidate authority: {value!r}')
    elif not str(
        state.get('evidence_class', '')
    ).startswith('AMBIGUOUS_'):
        raise SystemExit(f'{name} is not marked ambiguous: {state!r}')

state, seen = pair('attribute-end-tail')
value = seen.get('attribute_end_tail')
expected_tail = bytes((state['tail_value'],)) + bytes(state['tail_length'] - 1)
if (
    not isinstance(value, dict)
    or state['before_tail_hex'] != bytes(state['tail_length']).hex()
    or value.get('at_end_record_offset') != state['at_end_record_offset']
    or value.get('at_end_value') != 0xffffffff
    or value.get('tail_record_offset') != state['tail_record_offset']
    or value.get('tail_hex') != expected_tail.hex()
    or value.get('tail_nonzero_record_offsets') != [state['tail_record_offset']]
    or value.get('bytes_in_use') != state['bytes_in_use']
    or state['tail_record_offset'] + state['tail_length'] != state['bytes_in_use']
):
    raise SystemExit(f'AT_END trailing-byte raw oracle failed: {value!r}')

state, seen = pair('link-reciprocity')
value = seen.get('link_reciprocity')
if (
    not isinstance(value, dict)
    or value.get('link_count') != state['wrong_link_count']
    or value.get('file_name_count', 0) < state['expected_link_count']
    or value.get('target_parent_sequence') != 0
):
    raise SystemExit(f'link reciprocity raw oracle failed: {value!r}')

state, seen = pair('hardlink-value-order')
value = seen.get('hardlink_collation')
if (
    not isinstance(value, dict)
    or value.get('link_count') != 2
    or value.get('file_name_count') != 2
    or value.get('resident_parent_order') != state['wrong_parent_order']
    or value.get('resident_parent_order') != list(reversed(state['expected_parent_order']))
    or value.get('attribute_instances') != state['wrong_attribute_instances']
    or sorted(value.get('value_sha256', [])) != state['value_sha256']
    or value.get('values_distinct') is not True
    or value.get('values_collated') is not False
    or value.get('all_reciprocal') is not True
    or any(
        item.get('reciprocal') is not True
        or item.get('semantic_key_match') is not True
        for item in value.get('index_copies', [])
    )
):
    raise SystemExit(f'hardlink resident-value order raw oracle failed: {value!r}')

state, seen = pair('sparse-unit-header')
value = seen.get('sparse_stream')
if (
    not isinstance(value, dict)
    or value.get('attribute_flags') != state['attribute_flags']
    or value.get('attribute_instance') != state['attribute_instance']
    or value.get('compression_unit') != state['wrong_compression_unit']
    or value.get('data_size') != state['data_size']
    or value.get('initialized_size') != state['initialized_size']
    or value.get('allocated_size') != state['allocated_size']
    or value.get('compressed_size') != state['compressed_size']
    or value.get('runs') != state['runs']
    or value.get('mapped_lcns') != state['mapped_lcns']
    or value.get('logical_sha256') != state['logical_sha256']
    or value.get('mapping_hex') != state['mapping_hex']
    or value.get('attribute_record_offset') != state['attribute_record_offset']
    or value.get('attribute_record_length') != state['attribute_record_length']
    or value.get('mapping_pairs_offset') != state['mapping_pairs_offset']
    or value.get('terminator_attribute_offset') != state['terminator_attribute_offset']
    or value.get('mapping_tail_length') != state['mapping_tail_length']
    or value.get('mapping_tail_hex') != state['mapping_tail_hex']
    or value.get('mapping_tail_opaque_slack') is not True
    or value.get('mapping_tail_accepted_slack') is not True
    or value.get('runlist_complete') is not True
    or value.get('tail_run_mapped') is not True
    or value.get('mapped_cluster_bits') != [True, True]
    or value.get('mft_bitmap_bit') is not True
    or value.get('hole_all_zero') is not True
):
    raise SystemExit(f'sparse unit/header raw oracle failed: {value!r}')

state, seen = pair('duplicate-cluster')
value = seen.get('duplicate_cluster')
if (
    not isinstance(value, dict)
    or value.get('same_runs') is not True
    or value.get('first_sha256') != state['content_sha256']
    or value.get('second_sha256') != state['content_sha256']
    or value.get('original_second_all_allocated') is not True
):
    raise SystemExit(f'duplicate-cluster raw oracle failed: {value!r}')

state, seen = pair('compressed-metadata')
value = seen.get('compressed_metadata')
if (
    not isinstance(value, dict)
    or value.get('flags') != state['flags']
    or value.get('compression_unit') != state['wrong_compression_unit']
    or value.get('compressed_size') != state['wrong_compressed_size']
):
    raise SystemExit(f'compressed-metadata raw oracle failed: {value!r}')

state, seen = pair('compressed-payload')
value = seen.get('compressed_payload')
if (
    not isinstance(value, dict)
    or value.get('physical_offset') != state['physical_offset']
    or value.get('header_hex') != state['after_header_hex']
    or value.get('header_hex') == state['before_header_hex']
):
    raise SystemExit(f'compressed-payload raw oracle failed: {value!r}')

state, seen = pair('dirty-only-wiped-log')
value = seen.get('volume_dirty_wiped_log')
if (
    not isinstance(value, dict)
    or not value.get('primary_flags', 0) & 1
    or not value.get('mirror_flags', 0) & 1
    or value.get('logfile_size') != state['logfile_size']
    or value.get('logfile_all_ff') is not True
):
    raise SystemExit(f'dirty-only wiped-log raw oracle failed: {value!r}')

for name in (
    'journal-mft-false-free',
    'journal-cluster-false-free',
    'journal-duplicate-owner',
    'journal-mft-false-free-duplicate',
    'journal-cluster-false-free-duplicate',
    'journal-duplicate-owner-one-torn',
    'journal-duplicate-owner-preparing',
):
    state, seen = pair(name)
    value = seen.get('journal_allocation')
    duplicate = 'duplicate' in name
    false_mft = 'mft-false-free' in name
    false_cluster = 'cluster-false-free' in name
    if not (
        isinstance(value, dict)
        and value.get('mft_bit') is (not false_mft)
        and value.get('cluster_bit') is (not false_cluster)
        and value.get('journal_cluster_owner_count') == (2 if duplicate else 1)
        and value.get('ownership_records_examined', 0) > 0
        and (
            (duplicate and value.get('overlap_lcn') == state['journal_cluster'])
            or (not duplicate and value.get('overlap_lcn') is None)
        )
    ):
        raise SystemExit(f'{name} raw oracle failed: {value!r}')
PY

python3 "$wal_fixtures" inspect "$work/journal-duplicate-owner-one-torn.ntfs" \
    "$layout" --expect degraded >/dev/null
python3 "$wal_fixtures" inspect "$work/journal-duplicate-owner-preparing.ntfs" \
    "$layout" >"$work/journal-preparing-wal.json"
python3 - "$work/journal-preparing-wal.json" <<'PY'
import json
import sys

selected = json.load(open(sys.argv[1], encoding='utf-8')).get('selected')
if not isinstance(selected, dict) or selected.get('state') != 'PREPARING':
    raise SystemExit(f'preparing-zero runtime WAL mutation failed: {selected!r}')
oracle = selected.get('entry_oracle')
if not isinstance(oracle, dict) or oracle.get('entry_count') != 0:
    raise SystemExit(f'preparing-zero durable-prefix oracle failed: {oracle!r}')
PY

echo 'roothealth fixture construction passed: 5 base census + 64 filesystem variants + 5 WAL mutations.'
