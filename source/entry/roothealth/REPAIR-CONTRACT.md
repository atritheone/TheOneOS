# roothealth repair contract

This document is normative for the repair-capable T1OS hardware root health
tool.  It defines the product boundary independently of any upstream `ntfsck`
command-line behaviour.

## Supported volume profile

`roothealth` repairs an unmounted NTFS volume used as the T1OS hardware root.
It has no Windows runtime dependency and does not assume a Linux directory
hierarchy on that volume.  The persistent namespace must satisfy the T1OS raw
identity checks.  The volume may be the inner NTFS device of the supported
LUKS layout.

The release profile is deliberately exact: 512-byte NTFS sectors, 4096-byte
clusters, 1024-byte MFT records, 4096-byte index blocks, and a root volume no
larger than 256 GiB.  Image creation and bundle resize validation enforce the
same geometry.  A different geometry is checked
only far enough to return an unsafe/unsupported result and is never repaired.
This bounds all allocation maps and the crash journal without depending on the
end user's USB-drive firmware or access to Windows.

The supported geometry and pinned on-disk format rules are the resource bounds.
Roothealth must not add smaller implementation-only validity limits for
legitimate variable-sized metadata (for example `$Secure:$SDS`, security-ID,
hard-link, extent, or index-entry counts).  The pinned NTFS implementation's
explicit `$ATTRIBUTE_LIST` compatibility maximum is `0x40000` bytes: that exact
boundary is supported and a larger list is structurally outside the profile.
Other streams are consumed with checked arithmetic and bounded-memory
iterators, external sorting, or streaming passes whose limits derive from the
validated volume and stream sizes.  Allocation failure is an internal exit `5`
with zero writes; it is not evidence that an otherwise valid on-disk structure
is corrupt or unsupported.

Release roots are formatted by the pinned NTFS implementation, whose
volume-size rule creates a cluster-aligned `$LogFile` no larger than exactly
64 MiB; subsequent supported bundle resizing preserves that stream.  Image and
bundle manifests attest its size and the validators enforce the same bound.
A larger native log is outside the T1OS repair profile and is refused before
any write.  The 64 MiB ceiling is therefore a release-format invariant, not a
parser allocation shortcut.

The qualified native-replay subprofile permits at most 4096 typed physical
operations in its one indivisible transaction.  Every accepted mutation names
one proved 4 KiB cluster or one aligned 1 KiB MFT record (including a required
mirror operation), and each restart copy is one 4 KiB page; control records do
not write.  The resulting old-byte payload is therefore at most 16 MiB, plus
2 MiB of v1 descriptors, within the 128 MiB journal and its 100 MiB target-byte
limit.  A syntactically valid log which would exceed that exact operation
profile is reported unsupported with a zero writer plan and no WAL mutation;
the limit is checked only after whole-log preflight, never during a partial
commit.

The same profile pins the canonical system tables produced by the selected
source revision: unnamed `$UpCase/$DATA` is 131072 bytes with SHA-256
`41c26bc7a12bdaeb26025c93118697c7e3ef81ee048b00fe5cce2a472e0e0742`, and
unnamed `$AttrDef/$DATA` is 2560 bytes with SHA-256
`d7de5b1b2f79f45f235ceb1adbc46908ed64eae174eb90ed66aefe5f25165da3`.
Roothealth embeds those exact bytes rather than relying on a host installation.
It may replace `$AttrDef` only after a complete attribute census proves that
the volume uses no custom type or incompatible bound.  It may replace
`$UpCase` only after every affected index is proved correctly ordered under
the canonical table or the same fully journalled plan rebuilds those indexes
from a complete reciprocal namespace manifest.

The repair path never mounts the target.  It refuses a hibernated volume,
physical read failure, ambiguous authoritative metadata, unsupported or
destructive transformation, and a volume whose expected serial or T1OS
identity cannot be proven.  The expected serial and unique redundant authority
are mandatory before a bootstrap-copy write; full T1OS identity is mandatory
before the first unique-metadata write.

## Public command line

The production health modes are mutually exclusive:

```text
roothealth --preflight --require-t1os-root --expected-serial SERIAL \
  --expected-journal-uuid UUID --expected-journal-record RECORD:SEQUENCE \
  DEVICE
roothealth --boot-repair --require-t1os-root --expected-serial SERIAL \
  --expected-journal-uuid UUID --expected-journal-record RECORD:SEQUENCE \
  DEVICE
roothealth --check --require-t1os-root --expected-serial SERIAL \
  --expected-journal-uuid UUID --expected-journal-record RECORD:SEQUENCE \
  --report NEW DEVICE
roothealth --repair --require-t1os-root --expected-serial SERIAL \
  --expected-journal-uuid UUID --expected-journal-record RECORD:SEQUENCE \
  --report NEW DEVICE
```

`--preflight` is a read-only diagnostic only. `--boot-repair` is Angel's sole
normal admission mode. Both are bounded and omit the complete allocation,
namespace, security, fixed-system, compression, and user-data censuses.
`--boot-repair` may change only a uniquely authoritative redundant boot/MFT
copy, an exactly recognized native-log replay plan, or the mirrored dirty
flag. It repeats the bounded check after each change and has no comprehensive
fallback. Angel stops it after eight seconds and continues only on exit `0`;
every other result enters recovery before any root mount. Kernel `force`
mounting is not an admission fallback.

Every nonzero invocation emits one concise diagnostic line even under
`--quiet`: public result, exit code, stable orchestration/refusal stage,
captured errno, and errno text. Quiet mode suppresses progress, never the sole
failure explanation. Exit `2` also carries a stable primary issue code and the
complete sorted failed-predicate set in the format-3 issue ledger. The code
taxonomy and evidence requirements for adding repair classes are normative in
`FAILURE-TAXONOMY-v1.md`.

`--repair` remains the offline comprehensive, non-interactive,
policy-controlled repair followed by
an independent read-only rescan.  Generic upstream repair, preen, yes-to-all,
salvage, journal-reset, and hibernation-discard options are not exposed.

Stable exits are: `0` verified clean T1OS root; `2` unsafe, unsupported, or
unresolved corruption; `3` device or I/O failure; `4` wrong root or serial;
and `5` usage, report, or internal failure.  Only exit `0` permits boot.

An orderly power transition uses a deferred unmounted shutdown gate. After
GODDESS stops sessions, services, storage, and display work and synchronizes
the root, it atomically records the requested restart or power-off on the ESP
and restarts into Angel. Angel applies the same bounded boot admission before mounting
the root. Restart continues only on exit `0`; power-off occurs from initramfs
only on exit `0`. A refusal preserves the request and evidence and enters
cause-aware recovery. This gate never raw-writes beneath the live root mount.

## Complete check and repair surface

The comprehensive `--check` and `--repair` modes run the same in-process
checker.  A clean verdict requires all of
the following, with no skipped pass or parser warning: primary/backup boot and
geometry; `$MFT`/`$MFTMirr`; native `$LogFile`; every allocated FILE record,
attribute header/list/extent and mapping-pairs run; directory and metadata
indexes including MST fixups, ordering, child topology and index bitmaps;
reciprocal FILE_NAME/parent links, sequence numbers, link counts and namespace
reachability; `$MFT` and volume allocation bitmaps against an exhaustive run
ownership census; duplicate and out-of-range clusters; `$Secure` SDS mirrors,
SII and SDH; `$Extend/$ObjId:$O`, `$Quota:$O/$Q`, and `$Reparse:$R` against
their complete source censuses; an optional `$UsnJrnl:$Max/$J` when present;
`$UpCase`; `$AttrDef`; volume flags; sparse,
compressed and encrypted attribute invariants; every fixed NTFS system record;
the T1OS identity; and the internal `$Extend/$RootHealth` binding.  A feature
which the checker cannot validate is unsafe rather than implicitly clean.
Unknown/user-defined attribute types still receive complete header, extent,
mapping-pairs, bounds, overlap, and allocation validation; only their
application-specific payload semantics are opaque.  A failed read, allocation,
parser step, or deliberately skipped pass is an I/O/internal/unsafe verdict as
appropriate and can never be converted into a clean result.

The checker maintains an explicit coverage ledger: initialized MFT record
slots examined, live/free/unreadable records, attributes and extent records,
decoded run segments, namespace links, indexes, reachable/allocated index
blocks, allocation-map bits, security descriptors, reparse entries, and each
fixed-system-file check.  Expected and completed counts must reconcile before
`clean`; a void helper returning early or a partially walked structure cannot
be mistaken for a completed pass.

The format-3 `coverage` object is stable and contains `complete`,
`ledger_hash`, the two top-level counters `io_errors` and `skipped`, and these
fixed counter groups:

- `mft_slots`: `expected`, `completed`, `live`, `free`, `unreadable`,
  `invalid`;
- `attributes`: `expected`, `completed`, `resident`, `nonresident`,
  `user_defined`, `extents_expected`, `extents_completed`, `runs_expected`,
  `runs_completed`, `unreadable`, `skipped`;
- `namespace_links`: `expected`, `completed`, `reciprocal`, `unresolved`,
  `unreadable`;
- `indexes`: `expected`, `completed`, `blocks_allocated`,
  `blocks_reachable`, `blocks_examined`, `blocks_unreadable`,
  `bitmap_bits_expected`, `bitmap_bits_examined`;
- `bitmaps`: `mft_bits_expected`, `mft_bits_examined`,
  `cluster_bits_expected`, `cluster_bits_examined`, `differences`;
- `security`: `ids_expected`, `ids_examined`, `descriptors_expected`,
  `descriptors_examined`, `sds_entries_expected`, `sds_entries_examined`,
  `sdh_entries_expected`, `sdh_entries_examined`, `sii_entries_expected`,
  `sii_entries_examined`, `unreadable`;
- `reparse`: `attributes_expected`, `attributes_examined`,
  `index_entries_expected`, `index_entries_examined`, `unresolved`,
  `unreadable`;
- `compressed`: `units_expected`, `units_examined`, `unreadable`;
- `fixed_system`: `expected`, `completed`, `failed`, and ordered `checks`
  records containing a stable `id` and stable `result`.

Every counter is a nonnegative JSON integer.  It is `null` only when an early
failure makes that denominator genuinely unknowable; unknown is never encoded
as zero.  A complete T1OS root necessarily has nonzero MFT-slot, attribute,
nonresident-run, namespace-link, index, MFT-bitmap-bit,
cluster-bitmap-bit, security-ID, descriptor, SDS, SDH, and SII denominators;
zero in any of those fields is incomplete rather than an empty success.
Exit `0` requires `complete=true`; MFT
`completed=expected=live+free` with zero unreadable/invalid; every expected
attribute, extent, run, index, security, reparse, compressed-unit, bitmap-bit,
and fixed-system count equal to its completed/examined counterpart; namespace
`expected=completed=reciprocal`; index
`blocks_allocated=blocks_reachable=blocks_examined`; all unresolved,
unreadable, invalid, failed, difference, I/O, and skipped counters zero; and
every fixed-system check `PASS`.  `ledger_hash` is 64 lowercase hexadecimal
characters and binds the canonical fixed-order integer/null encoding plus
fixed-system checks sorted by ID.

For a mutating repair, the initial ledger may be structurally complete while
reporting a positive bitmap `differences` count and the corresponding
`system.bitmap` check as `FAIL`; those are the diagnosed inputs to the sealed
bitmap action plan, not missing census work.  Every committed batch rescan and
the final exit-`0` ledger still require zero differences and every fixed check
`PASS`.  No other initial failed fixed check is admitted by this exception.

The format-3 ledger hash input is frozen as follows.  It starts with the eight
bytes `52 48 43 4f 56 33 00 00` (`RHCOV3` and two NULs), little-endian `u32`
value `3`, and one byte `0` or `1` for `complete`.  It then encodes exactly 60
counters in this order: top-level `io_errors`, `skipped`; every counter from
`mft_slots`, `attributes`, `namespace_links`, `indexes`, `bitmaps`, `security`,
`reparse`, `compressed`, and the three `fixed_system` counters, in the field
order listed above.  Each counter occupies nine bytes: tag `0` followed by
eight zero bytes for JSON `null`, or tag `1` followed by its unsigned
little-endian `u64` value.  No other tag is valid.

Next is a little-endian `u32` fixed-check count.  Checks are sorted by the raw
UTF-8 bytes of their unique ID.  Each is encoded as a little-endian `u16`
nonzero ID-byte length, those ASCII ID bytes (restricted to
`[a-z0-9_.-]`), and one result byte: `1=PASS`, `2=FAIL`, `3=UNREADABLE`, or
`4=SKIPPED`.  Duplicate IDs, unknown results, more than 65535 checks, or an ID
longer than 255 bytes invalidate the ledger.  SHA-256 of exactly this stream is
the lowercase `ledger_hash`; JSON serialization, object order, C layout,
padding, pointers, and host endianness never enter it.  Any schema change
requires a report/ledger format bump.

The fixed-system check set always includes stable IDs for records 0 through
11 (`system.mft`, `system.mftmirr`, `system.logfile`, `system.volume`,
`system.attrdef`, `system.root`, `system.bitmap`, `system.boot`,
`system.badclus`, `system.secure`, `system.upcase`, and `system.extend`) and
for the T1OS extended metadata (`extend.quota`, `extend.objid`,
`extend.reparse`, `extend.usnjrnl`, and `extend.roothealth`).  The
`extend.usnjrnl` check is `PASS` only when the file is absent, as in the
canonical freshly built T1OS root, or when every present `$Max` and `$J`
stream and every referenced per-record USN has been completely validated.
Presence never counts as validation and absence is never fabricated after a
failed `$Extend` enumeration.  Unknown live system children or system streams
which have not been completely interpreted make the ledger incomplete.

Repair is the policy-controlled subset of that check surface.  Each detected
problem is either reconstructed from unique independent evidence, or remains
an explicit unresolved exit `2`; detection is never suppressed merely because
the repair policy denies a destructive or ambiguous transformation.

RootHealth v0.4.0 adds exactly these production-qualified derived surfaces:

- one stale resident `$I30` entry for the exact path
  `the one/settings/operations/operations.txt`, only when it is the sole
  reciprocity difference, its referenced FILE slot is definitively free, the
  parent chain is unique, the small index is structurally complete, and no
  `$INDEX_ALLOCATION` or `$BITMAP` participates;
- `$MFT/$BITMAP` byte corrections after a complete raw-MFT, attribute-list,
  extent, and reciprocal namespace ledger proves every set target live and
  every clear target unreferenced;
- per-directory `$I30/$BITMAP` corrections which set a missing bit for a
  completely traversed reachable INDX block; index-bitmap clears are denied;
- the existing exhaustive volume allocation-bitmap correction.

The resident stale-entry operation and all bitmap changes share one bounded
metadata WAL transaction when their evidence remains source-compatible.  The
volume dirty pair precedes them when necessary.  WAL recovery re-derives the
same exact stale entry and all bitmap target bytes from the immutable old view,
then a complete staged census must reconcile before commit and a fresh-process
rescan must reconcile before the journal is accepted.  A large/nonresident
directory index, more than one unmatched entry, a live or unreadable child,
an ambiguous path or name, an index-bitmap clear, a mixed stale-entry plus
index-bitmap plan, incomplete providers, or any change outside the sealed
targets remains an exit-`2` refusal with no target write.

Pre-write T1OS identity does not depend on a directory index which may itself
need repair.  The exhaustive raw-MFT census keys every live object by record
and sequence, validates each complete `$FILE_NAME` value, reconstructs parent
chains to fixed root record 5, rejects cycles and ambiguous same-parent/name
aliases, and compares names with the embedded canonical `$UpCase` table.
An `$UpCase` collision is not by itself an alias when every colliding
`$FILE_NAME` uses the POSIX namespace (`0`): canonical NTFS permits distinct,
case-sensitive POSIX names in one parent.  Roothealth accepts such a set only
when the exact UTF-16 names are pairwise distinct, every child record and
sequence is unambiguous, raw-MFT/`$I30` reciprocity is complete, and the pinned
NTFS filename collation produces one strict deterministic order.  It still
rejects an exact-name duplicate, a mixed-namespace or non-POSIX `$UpCase`
collision, duplicate ownership, and any collision which makes a required
T1OS identity anchor ambiguous.
Multiple independently reciprocal `$FILE_NAME` links to one record remain
valid hard links and are counted separately; they are not collapsed or
rejected merely because they share an inode.  Reciprocity requires the exact
parent reference, filename namespace and length, UTF-16 name, and indexed
child record/sequence.  Timestamps, allocated/data sizes, file attributes,
and the EA/reparse union inside a `$FILE_NAME` value are cached observations:
valid NTFS producers may leave them different in the MFT attribute and its
`$I30` key.  Roothealth validates, preserves, and independently hashes both
complete values and reports cached-field differences, but a cached-only
difference is neither corruption nor repair authority.  This does not relax
the explicit three-copy `0x00002007` `$RootHealth` provisioning invariant.
It requires the
directory `the one` plus the regular-file anchors
`the one/software/python/bin/python3.13`,
`the one/build/GODDESS/GODDESS.py`,
`the one/build/drivers/driverserver.py`,
`the one/drivers/tools/modprobe`,
`the one/drivers/settings/policy.json`, and
`the one/drivers/modules/module-manifest.sha256`; it also proves the forbidden Linux-style
top-level names absent by enumerating root-child `$FILE_NAME` values.  When
those raw anchors exist but a required `$I30` entry is missing or corrupt, the
volume is T1OS with repairable corruption.  When a raw required anchor itself
is absent, it is wrong root (exit `4`) and no unique write is permitted.
Ordinary pathname lookup is repeated only as part of the fresh post-repair
rescan.  The canonical raw graph hash is part of the namespace evidence seal.

## One boot repair invocation

The block device is selected without trusting the NTFS boot sector that may
need repair.  A normal GRUB boot identifies GPT partition 3 on the disk that
contains the active T1OS ESP and passes the root filesystem UUID.  A UKI
supplies the preserved ESP filesystem UUID and the initramfs resolves that
ESP's sibling root partition.  GPT partition 2 is the independent SquashFS
recovery image and is never a roothealth target.  An encrypted build resolves
and unlocks the expected outer LUKS container in partition 3, then uses its
fixed mapper device.  In every case the
independently embedded expected NTFS serial, provisioned journal UUID, and MFT
record/sequence locator are passed to roothealth.  The locator makes crash
recovery bounded even with damaged indexes; the UUID binds it to the journal
attested on the booted ESP.  Roothealth still validates the record contents and
uses a bounded unique raw-MFT scan only as a recovery fallback.  The trusted
fast path requires the exact attested record and sequence, parent/name, stream
shape, serial, UUID, runlist, and header bindings.  It rejects any definite
second live journal record found while scanning readable allocated records,
but unrelated unreadable records do not disable that exact locator; they are
reported and handled by the later checker.  Fallback discovery has no such
authority and is permitted only when the bounded scan has no unreadable
allocated record and proves exactly one matching journal.  This is device
binding within the existing boot paths, not a new partition or mode.

1. Open the target read-only and take an exclusive device lock.
2. Validate usable boot geometry and `$MFT` bootstrap metadata.  Before the
   full namespace is readable, the only permitted writes are restoration of a
   readable but structurally invalid boot or mirrored bootstrap record from
   its unique, strictly valid redundant peer, and only when that peer contains
   the expected NTFS serial.  A target-sector read error is an I/O failure,
   never evidence that the target is absent or safe to overwrite.
   A structurally valid boot peer with different geometry, serial, or defined
   sector bytes is conflicting authority and is never overwritten.  Two
   structurally valid mirrored MFT records which differ are also never copied
   over one another at this stage; they remain a read-only deferred conflict
   which only a fully preflighted native-log transaction may resolve.
3. Locate and validate `$Extend/$RootHealth` from those trusted bootstrap
   structures, then recover any interrupted internal transaction before the
   general diagnosis.  No unique metadata write is permitted during bootstrap.
4. Parse the complete supported native `$LogFile` transaction, reconstruct its
   control tables and semantic intents, and preflight every intrinsic log,
   payload, target-stream, and physical-mapping bound without writing the
   target.  A native action which also needs outer filesystem authority (for
   example `InitializeFileRecordSegment` against an allegedly free slot) stays
   deferred rather than receiving a fabricated local proof.  Reject an action
   that targets the internal journal's data, base record, allocation, or run
   binding.
5. Complete diagnosis, bind every deferred native intent to its required
   immutable pre-transaction census seal, and stage the complete native and
   uniquely derivable repair plan in the read overlay.  This may require
   bounded in-memory rounds: native-log intent, protected-record and attribute
   structure, a raw-MFT namespace/allocation census, native overlay, then
   derived indexes/allocation/security metadata.  Planning is not authority to
   write and must remain side-effect-free on the target.
6. Select every candidate through the explicit roothealth problem policy and
   prove the expected NTFS serial, raw T1OS identity, and complete namespace
   against the final staged view.  Newly introduced upstream problem codes
   fail the build until assigned an allow, conditional, or deny decision.  A
   damaged structure needed for identity is corruption, not a wrong-root
   verdict; it may be staged only when independent evidence yields one exact,
   content-preserving reconstruction.  A policy authorization is sealed to
   the exact staged-view generation, semantic object, physical range, and
   before/after byte hashes; it cannot authorize different bytes at the same
   address or be reused after another candidate changes that view.
7. Require a fresh overlay-only full check to prove the complete cumulative
   plan before the first WAL mutation.  The plan may repair derived metadata,
   allocation maps, attributes, indexes, security indexes, and namespace
   links, but never silently discard file data.  If it exceeds one v1 WAL
   transaction, partition it into deterministic dependency-ordered batches;
   transaction capacity is never a derived-filesystem-validity limit.  A
   nonempty native-log replay is the exception: its complete winner-redo and
   loser-undo plan is one indivisible initial WAL transaction, with the two
   clean restart-page writes last.  It is never prefix-committed or split
   across batches; a native plan outside the explicitly qualified replay/WAL
   profile is refused before any write.  Derived actions which fit may be
   included after the ID 5 group and before the final ID 6 pair in that same
   atomic transaction; any remaining derived-only batches follow after it has
   been freshly verified.  If corruption
   exists while the NTFS volume flag is clean, one semantic dirty-set operation
   (the ordered primary/MFTMirr physical pair defined below) precedes the first
   metadata transaction.  Each transaction requires a final-validation seal
   over its canonical plan hash and staged overlay, while the cumulative final
   overlay must still reconcile with the initially proved complete plan;
   preliminary per-candidate authorization alone is never write authority.
8. Keep the NTFS dirty flag set while any repair is incomplete.  Persist every
   unique-metadata target write through the internal write-ahead log, sync it,
   perform and sync the target write, and verify the bytes by readback.  After
   each committed metadata batch, close the writable handle, reopen from fresh
   process state, rederive that batch's semantic targets and coverage, return
   its WAL to `EMPTY`, and recompute the still-required suffix before beginning
   another batch.  A crash therefore resumes by ordinary diagnosis; no
   external state file or second recovery mode is needed.
9. After all metadata batches, close the writable handle, reopen the device
   read-only, and run the complete checker and T1OS identity proof from fresh
   process state.  Roothealth
   self-executes the same production binary in a hidden read-only rescan role,
   with a bounded inherited result pipe and the exact already-resolved device
   identity.  No external checker or second packaged repair binary is used.
   The child opens the target only read-only/forensic/no-repair and cannot
   create the report or perform a target mutation.
10. Clear dirty state only after that rescan has proved structural, allocation,
   journal, and namespace health.  Reopen and rescan once more.  Report success
   only when the final result is clean, log-clean, not dirty, and T1OS.

A clean volume is a true no-op: it opens no writable target handle, performs no
device write, does not advance the internal journal, and does not create a
recovery directory.

## Internal write-ahead log

Every release image contains one preallocated unnamed `$DATA` stream at
`$Extend/$RootHealth`.  It is NTFS metadata, not a new partition, boot mode, or
visible T1OS directory.  It has one base FILE record, no attribute list,
compression, sparseness, encryption, or reparse data.  Its runlist is validated
and rediscovered on every boot and after resize; cached LCNs are never trusted.
The journal has exactly NTFS file attributes `0x00002007` (read-only, hidden,
system, and not-content-indexed).  Those bits must agree in
`$STANDARD_INFORMATION`, the base record's sole `$FILE_NAME`, and the exact
cached `$Extend::$I30` key for the same record and sequence.  A mismatch makes
the locator non-write-safe.  Provisioning may make the three-copy update only
against a fresh unmounted `.building` image and revalidates its MST fixups;
the boot-time product never provisions or changes the journal's identity.

The journal contains two independently checksummed 4096-byte superblocks.
Generation selects the newest valid copy.  Superblocks bind the journal UUID,
NTFS serial, capacity, transaction identifier, plan hash, entry count, and
state (`EMPTY`, `PREPARING`, `APPLYING`, `COMMITTED`, or `ROLLBACK`).  Each
sector-aligned entry records its target offset, length, action kind, old and new
hashes, and one durable copy of the old bytes.

Before a target write, roothealth appends and syncs the old bytes and entry,
then advances and syncs a superblock.  It next performs the target write,
syncs, and verifies the new hash by readback.  Recovery of `PREPARING` or
`APPLYING` transactions restores entries in reverse order and verifies the old
hashes.  `COMMITTED` transactions are finalized only after a fresh rescan.
Raw journal I/O bypasses the intercepted target writer and is restricted to
the validated journal extents.  Target writes can never overlap those extents
or the journal's own base FILE record.  Its `$Extend` index entry may be
re-derived, but the raw MFT locator must remain intact throughout a transaction.

Structural repair uses one or more metadata journal transactions; dirty-flag
clearing is always a distinct final transaction.  Every metadata batch is
committed and independently rescanned while NTFS remains dirty; only then is
that batch's journal state returned to `EMPTY`.  After the last metadata batch,
the dirty-clear transaction is followed by the final fresh clean/not-dirty
rescan.  The transaction kind is recorded in each non-empty superblock, so
interrupted `COMMITTED` recovery cannot confuse the phases.

A metadata-repair transaction never contains a dirty-clear action.  When the
initial diagnosis found the volume flag clean, the first metadata batch
contains exactly one semantic dirty-set action represented by an ordered
primary-MFT and `$MFTMirr` physical pair as its first two target operations;
later metadata batches contain none.  If the flag was already dirty, no batch
contains a dirty-set action.
The dirty-clear transaction contains exactly the corresponding two-entry
typed dirty-clear pair and no other target operation.  The two entries must
name the attested physical copies of `$Volume` record 3 and encode the same
flag transition.  Recovery validates these action-kind, ordering, location,
and pair-consistency constraints before accepting or rolling back a descriptor
set.  Every other change to an MFT record covered by `$MFTMirr` is likewise
invalid unless the plan contains the adjacent matching mirror write with the
same semantic action kind.

Planning and recovery use the same complete-census publisher over one
immutable, read-only NTFS device interface.  In planning, that interface reads
an explicit writer-operation prefix (`0` for the initial view, or the exact
staged prefix being validated); in recovery, it reads the reconstructed WAL
pre-transaction view.  The device exposes only exact-length reads, seek, and
stat, installs no planning callback, and rejects every write.  Both paths must
produce the same action-specific evidence and canonical RHCOV3 ledger for the
same byte view.  A read, stat, close, sync, or unmount error invalidates the
census; teardown failure cannot be discarded after a nominally clean scan.

Missing, duplicated, malformed, undersized, or misbound journal metadata is an
unsafe roothealth result and blocks boot as well as every unique-metadata
repair without modifying it.  A valid non-`EMPTY` state mandates recovery or
finalization before diagnosis and can never be ignored to permit a mount.
An unreadable unrelated MFT record is not by itself evidence that the exact,
attested fast-path journal record is misbound; it does make untrusted fallback
discovery ambiguous and therefore unavailable.
Fast-path identity alone is not write authority.  Before reconstructing a
superblock, appending an entry, or recovering a transaction, a complete raw
run census over every record slot in the initialized `$MFT` must prove that
every journal cluster has exactly one owner and is not
claimed by `$BadClus`, another system stream, or ordinary data.  The census
parses every readable in-use FILE record even when its `$MFT` bitmap bit is
incorrectly clear; any unreadable or ownership-ambiguous slot blocks write
authority.  Such a record/runlist therefore leaves the
exact locator reportable but makes the journal non-write-safe and blocks all
raw journal mutation.

The sole exception to an allocation-map mismatch is the journal's own exact
attested record and runlist.  When the complete raw census proves unique
ownership and no duplicate, a falsely clear journal-record or journal-cluster
bitmap bit does not prevent raw WAL recovery.  The missing allocation bits are
mandatory typed set-only repairs in the next metadata transaction, and the
recovery locator continues to recognize that same bound false-free state after
a crash.  A duplicate owner, false-used unrelated record, unreadable census,
or any run/header ambiguity still blocks every raw journal write.
Bytes beyond an `EMPTY` header's zero `data_used` are stale capacity and need
not be erased after a completed transaction; release seeds alone are required
to have a fully zero entry area.
Redundant-copy recovery is permitted before the internal WAL is reachable only
under its independent sole-valid-peer durability rule.  Native log replay
occurs after WAL recovery and is itself WAL-backed; its native restart-page
ordering is an additional recovery authority rather than a substitute for the
full-sector undo images.

Native replay is qualified per exact redo/undo opcode pair, not by a generic
"known opcode" test.  Roothealth validates every MST-protected record page,
client and transaction chain, LSN ordering, action and payload bounds, target
attribute/runlist, LCN slice, and protected-system exclusion for the complete
transaction before it stages the first action.  All actions in the selected
transaction must be supported; a partially understood transaction is refused
without a target or WAL write.  Release qualification includes real resident,
nonresident, FILE-record, index, and bitmap redo transactions plus malformed
variants of every opcode.  Dump/control records may guide parsing but never
silently count as completed semantic redo, and no resize, truncate,
deallocation, or content-discard helper is reachable unless that exact native
operation, target, before-image, and complete-transaction outcome have passed
the same semantic qualification and WAL gates.

`InitializeFileRecordSegment` targets an MFT-record object, not a generic free
cluster.  Its pre-transaction FILE-record bytes may contain arbitrary stale
content: roothealth preserves them as the exact WAL before-image and may stage
the logged complete after-record only when the exhaustive raw-MFT, MFT-bitmap,
extent, and namespace censuses prove the slot free and wholly unreferenced.
The completely preflighted native log must identify the exact target set before
the raw census is run.  The census may treat only those sorted, unique,
predeclared slots as opaque 1024-byte candidates, so a zeroed, `BAAD`, bad-USA,
or otherwise unparseable stale preimage does not become a false global census
failure.  Every target's record number, exact raw bytes, and physical mapping
are hashed; every other MFT slot is still fully bounded.  Each target needs its
own clear MFT-bitmap bit and the complete extent, namespace/index,
fixed-system, native-control, and exclusion reference union must prove the
whole set unreferenced.  Duplicate or partially authorized target sets are
refused, and a multi-record native transaction remains one atomic WAL
transaction.  No general tolerance for unreadable or invalid MFT slots is
introduced.
The after-record number, nonzero sequence, MST structure, LSN provenance, and
the transaction's final bitmap/namespace overlay must all reconcile.  A zero
preimage is therefore neither required nor treated as additional authority.

Replay analysis reconstructs the restart checkpoint's transaction,
open-attribute, and dirty-page tables before choosing any target operation.
Committed winners are replayed forward and active losers are undone in reverse
LSN order; compensation-log records are interpreted rather than counted as
ordinary redo.  A missing, contradictory, truncated, cyclic, or unsupported
control table makes the entire native-log plan unsafe.  Qualification reports
control-record coverage separately from mutation-opcode coverage so a checker
cannot claim complete replay merely because a small set of data operations is
implemented.

The T1OS runtime ntfs3 driver does not emit a Windows-style redo action stream.
After a T1OS-origin power loss, the native log may therefore be in its exact
recognized wiped/empty representation while the volume dirty flag remains
set.  That state plans zero native-log action and restart-page writes; it does
not reset, synthesize, or reinterpret a log.  Roothealth retains dirty state,
runs the complete structural/allocation/namespace check and any independently
derived repairs, and may clear dirty only through the ordinary final
dirty-clear transaction after both fresh rescans succeed.  A partly wiped,
malformed, contradictory, or otherwise unrecognized log remains unsafe.

## Data preservation and recovery namespace

Derived metadata may be rebuilt from independently validated source records.
The supported repair set includes these uniquely evidenced transformations:

- reconstruct a readable FILE record's canonical header and attribute layout
  when its record number, sequence, base reference, complete attributes, and
  payload bytes are independently bounded: this includes `bytes_in_use`,
  `next_attr_instance`, derivable directory/view flags, reserved bytes,
  resident indexed flags, canonical attribute order, and aligned name/value or
  mapping-pairs offsets; the rewrite preserves every semantic value and is a
  complete MST-protected ID 7 record action, never an in-place header poke;
- canonicalize a structurally bounded resident or nonresident attribute header
  only when the complete name, value or mapping-pairs stream, VCN span, sizes,
  and owning record make the packed representation unique; overlapping,
  truncated, multiply interpretable, or non-fitting layouts remain unsafe;
- treat the first valid zero byte in a bounded mapping-pairs array as its
  semantic terminator.  Bytes from that terminator to the end of the enclosing
  attribute record are opaque producer slack: roothealth preserves and hashes
  them exactly, but they are neither decoded, required to be zero, repaired,
  nor used as authority.  Only malformed bytes before the terminator or a
  missing in-bounds terminator make the runlist unsafe;
- distinguish protocol-required canonical fields from receive-side opaque
  fields.  A field is eligible for zeroing only when the applicable NTFS or
  embedded structure contract requires zero on read.  Fields specified as
  reserved-but-ignored when received (including such fields inside serialized
  security claims) are preserved and evidence-bound exactly; a producer's
  preferred zero value alone is not repair authority;
- replace a stale `$ATTRIBUTE_LIST` record sequence from the one matching live
  extent record and its reciprocal base reference;
- reduce an impossible `initialized_size > data_size` to `data_size`, without
  changing the runlist or payload;
- restore fixed zero/reserved index fields and rebuild `$I30`, `$Reparse:$R`,
  `$ObjId:$O`, `$Secure:$SDH`, and `$Secure:$SII` from a complete validated
  source census;
- restore the canonical empty/default T1OS `$Quota:$O/$Q` indexes only when a
  complete MFT, security-ID, owner-ID, and quota-charge census proves that no
  nondefault quota state exists; otherwise preserve and validate the existing
  quota indexes or refuse repair;
- restore the redundant `$Secure:$SDS` half from its sole valid peer and bind
  every rebuilt security-index entry to the parsed descriptor stream;
- restore the pinned `$UpCase` or `$AttrDef` stream only under the complete
  namespace/index or attribute-type predicates defined by the supported
  profile;
- reconstruct mapping-pair coverage, including an opaque user-defined
  attribute, only when its VCN span, sizes, allocation, and unique physical
  ownership determine one exact runlist without interpreting its payload;
- restore a FILE record's in-use, directory/view, record-sequence, or base
  reference fields only when the MFT bitmap, complete bounded attribute set,
  extent graph, and every reciprocal namespace/index reference unanimously
  derive the same value; the record and every dependent reference are changed
  in one WAL-backed plan, while any conflicting authority is refused;
- restore FILE_NAME parent sequences and link counts from the complete
  reciprocal namespace graph;
- restore a duplicate stream's mapping to its one uniquely allocated,
  otherwise-unowned original run, or relocate intact bytes to a deterministic
  proved-free run in the same fully journalled transaction; and
- repair compressed-attribute header metadata only when the complete run and
  compression-unit census uniquely derives it and the compressed payload
  itself validates.

`$UsnJrnl` is not created, deleted, reset, truncated, or treated as an empty
T1OS default at boot.  When present, roothealth may correct a stale cached USN
in another record only when the completely validated journal bounds prove the
value impossible; damaged or ambiguous journal content remains unsafe rather
than being discarded.

These are closed predicates, not examples which authorize analogous writes.
Each transformation still needs its exact policy entry, semantic action seal,
complete overlay check, persistent WAL transaction, and fresh-process rescan.
An opaque user-defined payload is preserved byte-for-byte.

An MFT-contained metadata change is never emitted as an arbitrary raw byte
range inside a record.  Roothealth reads and validates the complete record,
applies post-read MST fixups, changes the derived logical value or attribute
header, regenerates the update-sequence array and sector trailers, and
journals the complete raw 1024-byte record image.  This rule also applies when
the requested logical byte happens not to occupy a sector trailer;
qualification includes forced trailer-boundary cases.  The sole narrow
exception is the paired ID 24/25 volume-flags transition: the supported
record-3 layout proves its exact two-byte range is outside the USA and sector
trailers, and recovery rederives that same layout before touching it.  A
record in the mirrored geometry additionally has the adjacent matching
`$MFTMirr` action required by the WAL contract.

An orphan with a unique valid original parent and name is reconnected there.
If its parent cannot be proven, intact content may be reconnected under the
existing T1OS directory `the one/recovered files/roothealth` with a stable,
collision-resistant name.  `lost+found`, `FSCK_*`, and new top-level
directories are forbidden.

Repairs that would discard an unreadable MFT record, remove the only filename,
sparse a corrupt compressed unit, release ambiguous extents, reset `$LogFile`,
or choose between conflicting valid authorities are refused.  Such a refusal
is exit `2`, leaves the target unmounted, and is described in the report.
A corrupt compressed payload without an independently validated redundant
source is likewise refused; a structurally plausible decompression result is
not repair authority.

## Report format 3

The report is part of the boot decision, not best-effort logging.  Roothealth
opens the final component with `O_CREAT|O_EXCL|O_NOFOLLOW`, mode `0600`, before
the first device mutation.  It accepts only a newly created regular file,
limits the complete JSON document to 4 MiB, preserves the first write, flush,
or close error, and on a detected failure removes only a partial file created
by that invocation.  Report ownership has three states: before successful
`openat(O_EXCL)` no file is owned; `CREATED_ID_UNKNOWN` means the invocation
created an inode but has not yet bound its handle identity; and
`CREATED_ID_KNOWN` binds the open handle's device/inode to the retained trusted
parent directory and basename.  Synchronous cleanup keeps the handle open,
promotes `CREATED_ID_UNKNOWN` to `CREATED_ID_KNOWN` with `fstat`, then performs
`fstatat` identity matching before `unlinkat`.  If identity cannot be proven,
the name was replaced, or unlink itself fails, roothealth exits `5`, reports
cleanup failure to its caller, and leaves only invalid zero/partial JSON rather
than risk deleting another inode.  An abrupt power loss or `SIGKILL` may leave
an empty or incomplete file, but never a valid success document; `/run` is
recreated on the next boot and target recovery never consumes that file as
authority.
The initramfs supplies a trusted, root-owned `/run` parent.  An existing file,
symlink, directory, special file, target-device alias, or report failure is
exit `5`; none is permission to start or continue a repair.

Every report has `format=3`, checker name/version, mode, requested and resolved
device identities, stable result/exit, an `initial` diagnostic snapshot, the
bound `wal` observation, the exact `native_log` observation, ordered
`foundation_repairs`, bounded physical-action samples, an `RHTXN3` batch
ledger with bounded transaction/rescan samples, a final snapshot, and an
`RHISS3` issue ledger with bounded samples.  Unknown booleans are JSON `null`,
never fabricated as false.  Device identity includes type, major/minor (or
regular-fixture inode), size, and the independently expected NTFS serial.

The packaged checker identity is exactly `roothealth`; development component
names are not accepted by release validation.  The top-level field set is
exactly `format`, `checker`, `checker_version`, `mode`, `result`, `exit_code`,
`device`, `identity`, `initial`, `native_log`, `foundation_repairs`, `plan`,
`commit`, `batch_ledger`, `batch_samples`, `repairs`, `wal`, `issue_ledger`,
`issues`, `report_budget`, `final`, and `dirty_cleared`.  No unknown member is
permitted at the top level or inside any fixed object, ledger record, or
bounded sample.  This closed field grammar is also used to materialize the
pre-mutation maximum-size proof; an unmodelled member cannot consume the
remaining reservation after a repair starts.

`device` has exactly `requested_path`, `resolved_path`,
`requested_was_symlink`, `resolved_type`, `requested_dev`, `requested_ino`,
`resolved_dev`, `resolved_ino`, `resolved_major`, `resolved_minor`,
`mapper_name`, and `selection_proven`.  Device/inode strings encode unsigned
64-bit decimal values; major/minor and PID fields are unsigned 32-bit values.
`identity` has exactly `prewrite_checked`, `prewrite_valid`,
`expected_serial`, `observed_primary_serial`, `observed_backup_serial`,
`expected_label`, `observed_label`, and `anchor`.  `plan` has exactly
`operations`, `bytes`, `priority_operations`, `foundation_operations`,
`foundation_bytes`, `wal_operations`, `wal_bytes`, `by_action_id`, `by_kind`,
`bytes_by_action_id`, and `bytes_by_kind`; `commit` has exactly `started`,
`completed`, `last_verified_ordinal`, `syncs`, and `write_boundaries`.
Counts, ordinals, offsets, lengths, and byte/boundary totals are unsigned
64-bit JSON integers unless a narrower field is explicitly stated; numeric
overflow is a report error, never a serializer exception.

Identity validity is tri-state and follows the observation boundary exactly.
When `prewrite_checked=false`, `prewrite_valid` and every observed identity
field (`observed_primary_serial`, `observed_backup_serial`, `observed_label`,
and `anchor`) are `null`; expected serial/label remain present because they are
invocation inputs.  When `prewrite_checked=true`, `prewrite_valid` is a JSON
boolean.  A `true` validity result requires all four observed fields to be
present and bound to the successful pre-write identity proof.  No unchecked or
partially read identity state is serialized as `false`.

The exact `native_log` fields are `checked`, `state`, `logfile_bytes`,
`pages_expected`, `pages_examined`, `wiped_pages_scanned`, `version_major`,
`version_minor`, `restart_lsn`, `synced_lsn`, `committed_lsn`, `latest_lsn`,
`checkpoint_records_examined`, `control_records_examined`,
`mutation_records_examined`, `open_attribute_tables`,
`attribute_name_tables`, `dirty_page_tables`, `transaction_tables`,
`actions_seen`, `redo_actions`, `undo_actions`, `restart_pages_planned`,
`unsupported_actions`, `io_errors`, `parse_errors`,
`planned_io_operations`, and `planned_io_bytes`; no additional field is
permitted.  Counts through `parse_errors` are unsigned 32-bit JSON integers,
and the byte, LSN, and planned-I/O fields are unsigned 64-bit JSON integers.
`version_major` and `version_minor` are unsigned 16-bit integers when known.
The nullable fields are `state`, `logfile_bytes`, `pages_expected`, the two
version fields, and the four LSN fields.  An unchecked observation uses null
for all of those fields and zero for every non-null count; it does not
fabricate negative evidence.

A checked observation binds a positive 4 KiB-aligned `logfile_bytes`, with
`pages_expected=logfile_bytes/4096` and examined/wiped pages within that
bound.  `actions_seen` equals control plus mutation records; checkpoint and
per-table counts cannot exceed the control count; redo and undo are each
bounded by the mutation count, rather than incorrectly sum-bounded because a
loser action can require both decisions.  Public `state` is exactly one of
`CLEAN_RESTART`, `REPLAY_PLANNED`, `EMPTY_T1OS`, `UNSAFE`, or `IO_ERROR`.
`EMPTY_T1OS` has every page examined and wiped, null version/LSNs, and zero
action, control, table, restart, planned-I/O, and error counts.
`REPLAY_PLANNED` has a supported restart version, at least one selected redo
or undo, exactly two restart pages, and zero parser/I/O/unsupported counts;
its planned operation and byte totals reconcile exactly with the ordered ID 5
and ID 6 physical entries.  `CLEAN_RESTART` has no selected or planned writes.
`UNSAFE` has a parser or unsupported-action count and zero planned I/O;
`IO_ERROR` has a positive I/O-error count and zero planned I/O.  A refusal
caused by the native parser itself never leaves a partial native writer plan.
Check mode is strictly read-only and therefore never reports
`REPLAY_PLANNED`; any nonzero native planned-I/O total in check mode is an
invalid document.  In repair mode, `REPLAY_PLANNED` reconciles exactly to its
ordered ID 5/6 physical entries, top-level plan counts/bytes/maps, the
canonical `RHREPL3` repair-ledger hash, and one matching `RHTXN3` transaction
sample and aggregate record.  Empty or mismatched plan, repair, transaction,
or ledger evidence invalidates the whole report.
If native replay is completely preflighted and simulated but a later
overlay-dependent filesystem check finds an unrelated ambiguity, the overall
run is exit `2` and retains the complete ID 5/6 plan as an uncommitted,
`result=refused` metadata transaction.  Every such physical entry has
`verified=false` and zero write boundaries, the transaction and top-level
commit both have `commit_started=false`, and the internal WAL remains
`EMPTY`; this preserves truthful replay evidence without writing the target or
mislabeling a valid log as malformed.  A partial native plan is never exposed.
The initial snapshot's
`native_log_state` equals this detailed state.  Every diagnostic/rescan
snapshot contains its own nullable `native_log_state`; exit `0` permits only
`CLEAN_RESTART` or `EMPTY_T1OS` in the final fresh-process snapshot.

Every diagnostic/rescan snapshot contains an `execution` object.  Its exact
fields are `role`, `exec_id`, `pid`, `parent_pid`, `binary_sha256`, `transport`,
`pipe_payload_bytes`, `transport_exit_status`, `timeout_ms`, `timed_out`,
`device_fd_inherited`, and `report_fd_inherited`.  The initial process uses
`role=INITIAL`, `transport=DIRECT`, zero payload bytes,
`transport_exit_status=null`, `timeout_ms=null`, and `timed_out=null`.  Its
`parent_pid` is the positive result of `getppid()`.  A child uses
`role=SELF_EXEC_RESCAN`, a distinct RFC 4122 lowercase UUID `exec_id`,
`transport=SELF_EXEC_PIPE_V1`, positive bounded payload bytes, transport exit
`0`, the configured positive timeout in milliseconds, and `timed_out=false`.
The initial `exec_id` is also a distinct RFC 4122 lowercase UUID.  PIDs are
positive JSON integers; the child's `parent_pid` equals the initial process
PID.  `pipe_payload_bytes`, the two PID fields, timeout when non-null, and
transport exit when non-null are JSON integers rather than strings.  No
additional field is permitted in `execution`.  Both roles report the same
64-lowercase-hex executable hash.
The two inherited-FD booleans are always false: the child receives only its
result pipe and independently opens the resolved target read-only.  Any field
mismatch, duplicate exec ID, oversized/truncated payload, nonzero transport
exit, timeout, signal, or unexpected inherited device/report descriptor is an
internal failure and cannot produce exit `0`.

The exact initial-snapshot fields are `completed`, `scan_id`, `execution`,
`fresh_process`, `read_only`, `exit_code`, `result`, `dirty`,
`logfile_clean`, `native_log_state`, `identity_valid`, and `coverage`.
Every rescan/final snapshot adds exactly `ordinal`, `stage`, `binding`,
`transaction_uuid`, and `plan_hash`; no other snapshot field is permitted.

Each foundation repair records its typed action, target byte range, old/new
SHA-256, sync/readback result, and sole-valid-peer evidence.  Its exact
`target_status` is `READABLE_STRUCTURALLY_INVALID`; an unreadable target does
not produce a foundation-repair record because the invocation stops with I/O
exit `3` before planning.  Foundation repairs are bounded by the four redundant
boot/MFT peers and remain complete in the report.
The base physical-action fields are exactly `ordinal`, `action_id`, `kind`,
`target`, `offset`, `length`, `before_hash`, `after_hash`, `verified`, and
`write_boundaries`.  A diagnostic repair sample adds only `sample_reasons`.
A foundation action instead adds exactly `sync_ordinal`, `sync_completed`,
`readback_verified`, and `authority`; authority has exactly `source_peer`,
`target_peer`, `source_strict_valid`, `source_expected_bound`,
`target_status`, `sole_valid_peer`, and `conflicting_valid_peer`.

Every transaction records `METADATA_REPAIR` or `DIRTY_CLEAR`, transaction UUID,
complete ordered WAL plan hash, exact operation and byte totals, count and byte
maps by the fixed action IDs/names, commit/finalization state, sync count, last
verified ordinal, and a canonical physical-repair ledger commitment.  The
commitment's format name is `RHREPL3`.  Its SHA-256 input is the eight bytes
`RHREPL3\0`, little-endian `u32` format `3`, little-endian `u64` entry count,
then for each local ordinal: `u64` local ordinal, `u32` action ID, `u64`
physical offset, `u64` physical length, 32-byte before hash, and 32-byte after
hash.  The plan hash separately binds the complete semantic WAL descriptors.
Count maps, byte maps, target-byte total, entry count, plan hash, and repair
ledger hash are exact even when no corresponding action is sampled.

Top-level `repairs` is diagnostic sampling, not the complete ledger.  It is
capped at 128 unique, increasing physical ordinals and deterministically keeps
the first 32 actions, last 32 actions, and up to 64 earliest actions associated
with unresolved/error evidence (deduplicating overlaps).  Every sample records
`sample_reasons` from `FIRST`, `LAST`, and `ERROR` plus the complete action
ID/name, semantic target, byte range, old/new SHA-256, verification, and write
boundary evidence.  The diagnostic target string is at most 256 UTF-8 bytes;
semantic seals, not that text, authorize the write.  `report_budget` records
emitted/omitted sample counts.
Qualification retains the complete typed-writer trace and independently
recomputes every `RHREPL3` hash, count map, byte map, and sample selection.

The canonical `RHTXN3` streaming ledger covers every physical phase in order:
a foundation phase when present, recovered work, every new metadata
transaction, and the final dirty-clear transaction.  Its hash input starts
with the eight bytes `RHTXN3\0\0`, little-endian `u32` format `3`, and
little-endian `u64` record count.  Every fixed-size record then contains, in
this exact order:

1. `u64` phase ordinal; `u8` phase (`FOUNDATION=1`,
   `METADATA_REPAIR=2`, `DIRTY_CLEAR=3`); `u8` origin
   (`FOUNDATION=1`, `NEW=2`, `RECOVERED_COMMITTED=3`,
   `RECOVERED_ROLLED_BACK=4`); `u8` result (`accepted=1`, `refused=2`,
   `rolled-back=3`); `u8` flags; and a zero `u32`;
2. the RFC 4122 UUID as 16 network-order bytes, or 16 zero bytes only for
   foundation; the 32-byte plan/foundation hash; and the 32-byte `RHREPL3`
   hash;
3. little-endian `u64` entry count, target-byte count, last verified ordinal,
   target sync count, target-write boundary count, rollback-restored entry
   count, rollback-restored byte count, rollback sync count, and rollback
   write-boundary count;
4. 25 little-endian `u64` action counts in action-ID order 1 through 25,
   followed by 25 corresponding byte counts; and
5. the 32-byte rescan, cumulative coverage-ledger, and cumulative diagnosis
   hashes, each all-zero only when the rescan is absent.

Flag bits are `0x01 commit_started`, `0x02 commit_completed`,
`0x04 rescan_present`, `0x08 rollback_completed`, and
`0x10 rollback_readback_verified`; all other bits are zero.  An accepted
phase has both commit bits, no rollback bits, every entry verified, positive
sync/boundary counts, and a rescan.  A refused `NEW` phase has no commit,
rollback, write, or rescan evidence.  A recovered partial phase uses origin
`RECOVERED_ROLLED_BACK`, result `rolled-back`, both rollback bits, a
rollback-restored count equal to the original verified prefix, zero current
target sync/boundary counts (the raw restore is in `RHWAL3`), and a fresh
rescan.  A zero-prefix `PREPARING` recovery has `commit_started=false` and
zero restored entries; an `APPLYING` prefix has `commit_started=true` and a
positive matching restored prefix.  Neither is mislabeled
`RECOVERED_COMMITTED`.  Both recovered origins precede every `NEW` phase.

The rescan hash input is `RHSCAN3\0`, little-endian `u32` format `3`,
little-endian `u64` byte length, then the UTF-8 bytes of the exact snapshot
JSON serialized with lexicographically sorted keys, no insignificant
whitespace, ASCII escaping, and JSON separators `,` and `:`.  The cumulative
diagnosis hash uses the same envelope with magic `RHDIAG3\0` over an object
whose exact sorted fields are `completed`, `exit_code`, `result`, `dirty`,
`logfile_clean`, `native_log_state`, and `identity_valid`.  The cumulative
coverage hash is the snapshot's canonical `RHCOV3` hash.

Top-level `batch_ledger` has the exact fields `format`, `record_count`,
`ledger_hash`, `foundation_count`, `new_count`,
`recovered_committed_count`, `recovered_rolled_back_count`, `metadata_count`,
`dirty_clear_count`, `accepted_count`, `refused_count`,
`rolled_back_count`, `priority_count`, `rescan_count`,
`commit_started_count`, `commit_completed_count`, `verified_entries`,
`rollback_restored_entries`, `rollback_restored_bytes`, `rollback_syncs`,
`rollback_write_boundaries`,
`entry_count`, `target_bytes`, `syncs`, `write_boundaries`,
`by_action_id`, `by_kind`, `bytes_by_action_id`, `bytes_by_kind`,
`dirty_set_action_count`, `dirty_set_phase_ordinal`,
`dirty_clear_action_count`, `dirty_clear_phase_ordinal`,
`native_redo_count`, `native_restart_count`, `native_phase_ordinal`,
`first_metadata_ordinal`, `first_phase`, `last_phase`,
`final_rescan_digest`, `final_coverage_ledger_hash`, and
`final_diagnosis_hash`; no other field is permitted.  Count and byte maps use
nonzero entries only and their action-ID/name forms are exact mirrors.

Top-level `batch_samples`, not unbounded `transactions[]` or `rescans[]`,
contains at most 64 paired phase/rescan samples: the first 16, last 16, and
up to 32 earliest priority phases after deduplication.  A priority phase is
refused/rolled back or has failed rescan transport, I/O, identity, or coverage
evidence.  Samples use increasing global phase ordinals, record all canonical
record fields plus `sample_reasons`, and contain the full bounded `rescan`
object when present.  `sample_reasons` is the sorted subset of `ERROR`,
`FIRST`, and `LAST` implied by that phase.  Full `initial` and `final`
snapshots are never sampled away.  Qualification recomputes `RHTXN3` and the
deterministic sample choice from the complete orchestration trace.  A plan
whose fixed envelope cannot represent its bounded samples and aggregates is
refused before mutation; it is never allowed to discover report overflow
after a committed batch.

A metadata transaction never contains dirty-clear.  Only the first metadata
transaction may contain the dirty-set physical pair, and then only at ordinals
zero and one; all later metadata transactions contain no ID 24.  A dirty-clear
transaction is exactly the two matching dirty-clear entries and is the final
ledger record.  Native-log replay occurs in exactly one first metadata
transaction: all ID 5 entries are contiguous, any included derived entries
follow them, and the exact two ID 6 restart pages are that transaction's final
entries.  One distinct fresh self-exec rescan digest follows and binds every
committed batch before another batch may begin.

Raw internal-journal housekeeping is reported separately under the `wal`
object.  The `RHWAL3` hash input starts with `RHWAL3\0\0`, little-endian
`u32` format `3`, and little-endian `u64` record count.  Each record is,
in order: `u64` ordinal; `u8` kind
(`undo-payload-append=1`, `descriptor-append=2`,
`state-transition=3`, `superblock-reconstruct=4`,
`rollback-restore=5`); `u8` from-state; `u8` to-state; `u8` slot code;
`u32` evidence flags; nullable transaction ordinal as `u64`; 16-byte
transaction UUID; `u64` physical offset, length, sync ordinal, and write
boundaries; then 32-byte before and after hashes.  State codes are
`null=0`, `EMPTY=1`, `PREPARING=2`, `APPLYING=3`,
`COMMITTED=4`, and `ROLLBACK=5`.  Slot codes are `0` null, `1` slot 0,
and `2` slot 1.  The nullable ordinal is `UINT64_MAX` only when absent and
then the UUID is all zero; otherwise the UUID is the corresponding `RHTXN3`
UUID.  Evidence flag bit 0 means sync completed and bit 1 means readback
verified; both are mandatory and every other bit is zero.

An `undo-payload-append` or `descriptor-append` may have equal before and
after hashes when a newly bound transaction reuses a slot containing the same
stale bytes.  It remains a mandatory physical write and must carry nonzero
boundary, sync, and successful readback evidence.  Every other `RHWAL3`
action must change bytes.

`rollback-restore` is bound to the exact
`RECOVERED_ROLLED_BACK` phase ordinal and UUID, never left unassociated or
described as a new transaction.  Its complete count, bytes, syncs, and
boundaries equal that phase's rollback aggregates.  A zero-prefix
`PREPARING` rollback is represented by one zero-entry
`RECOVERED_ROLLED_BACK` RHTXN3 phase with its fresh rescan and has no restore
record.  No other zero-entry phase is valid.  Superblock reconstruction has no
transaction association.  State-transition records alone carry from/to
states, and a transition never maps a state to itself.

The `wal` object has exactly `checked`, `present`, `valid`, `state`,
`generation`, `recovery_required`, `recovered`, `journal_uuid`,
`volume_serial`, `transaction_kind`, `max_entry_count`,
`fast_path_trusted`, `fallback_attempted`, `fallback_ambiguous`,
`unreadable_record_count`, `definite_duplicate_count`, `write_boundaries`,
`action_ledger`, and `actions`.  Generation, locator counts, and boundaries
are nullable/required unsigned 64-bit fields as applicable;
`max_entry_count` is nullable unsigned 32-bit and is exactly 4096 for a valid
bound journal.

`wal.action_ledger` has exactly `format`, `entry_count`, `ledger_hash`,
`total_bytes`, `syncs`, `write_boundaries`, `by_kind`,
`bytes_by_kind`, `syncs_by_kind`, `boundaries_by_kind`, `first_kind`,
`last_kind`, and `error_count`.  `wal.actions` contains at most 128
increasing global-ordinal samples: first 32, last 32, and up to 64 earliest
actions tied to unresolved/I/O/unsafe evidence, after deduplication.
Those writes are not filesystem repair entries and do not appear in a newly
planned transaction.  Qualification recomputes `RHWAL3`, every aggregate,
the rollback cross-binding, and deterministic samples from the complete raw
WAL trace.

One fresh rescan follows every committed metadata batch and is made from a
closed/reopened read-only device; its binding names that transaction UUID and
plan hash.  Intermediate rescans verify the committed semantic targets and
the exact remaining diagnosis even though later repair candidates still make
the volume unhealthy.  The final fresh rescan follows the separate dirty-clear
transaction when one was needed.  Every rescan records structural, allocation,
`$LogFile`, dirty-state, serial, complete T1OS identity, coverage ledger, and
fresh-process evidence.  Exit `0` requires a full final snapshot which is
clean, log-clean, not dirty, identity-valid, and equal to the last `RHTXN3`
rescan digest.  Clean `--repair` has an empty batch/action ledger, one full
clean final rescan bound to `INITIAL`, zero device/WAL writes, and no writable
target open.

An initially clean invocation which performs only a redundant-copy foundation
repair also needs exactly one fresh rescan.  That rescan has `stage=FINAL` and
`binding=FOUNDATION`; it is not mislabeled `POST_METADATA`, and no synthetic
dirty-set/dirty-clear transaction is created merely to add another phase.  If
a later transaction does follow foundation work, its intermediate foundation
rescan uses `stage=POST_METADATA` instead.  A clean no-op final rescan uses
`binding=INITIAL`.

Issue records contain a stable problem code, pass, severity, resolved state,
object reference or safely bounded path, policy decision, supporting/failed
predicates, message, and associated action ordinals.  The canonical `RHISS3`
hash input starts with `RHISS3\0\0`, little-endian `u32` format `3`, and
little-endian `u64` issue count.  Each variable-size record contains, in
order: `u64` ordinal; `u8` severity (`INFO=1`, `WARNING=2`,
`CORRUPTION=3`, `IO=4`, `UNSAFE=5`); `u8` resolved; `u8` policy
(`ALLOW=1`, `CONDITIONAL=2`, `DENY=3`); zero `u8`; nullable record and
offset as little-endian `u64`; length-prefixed problem code, pass, path, and
message; a length-prefixed required-predicate array; the failed-predicate
array; and a little-endian `u32` action-ordinal count followed by
little-endian `u64` ordinals.  Nullable integers use `UINT64_MAX`.  UTF-8
strings use a little-endian `u16` byte length; only path may be null, encoded
as `0xffff`.  Code and pass are at most 128 bytes, path 512, message 1024,
each predicate 64; both predicate arrays are sorted/unique subsets capped at
8, failed is a subset of required, and the sorted/unique action set is capped
at 16.  The message is diagnostic but still hash-bound so its alteration is
detectable.

Top-level `issue_ledger` has exactly `format`, `entry_count`,
`ledger_hash`, `resolved_count`, `unresolved_count`, `error_count`,
`by_severity`, `unresolved_by_severity`, `first_severity`, and
`last_severity`.  `error_count` includes every unresolved issue and every
`IO`/`UNSAFE` issue.  Top-level `issues` contains at most 128 increasing
global-ordinal samples: first 32, last 32, and up to 64 earliest error issues
after deduplication.  Omitted resolved diagnostics do not block exit `0` when
the full ledger has both unresolved and error count zero and the final complete
rescan is clean.  Qualification retains the complete issue trace and
recomputes `RHISS3`, aggregates, and samples; sampling never hides a decision.
A report never includes target data, filenames outside the affected metadata
object, or unbounded parser strings.

### Bounded publication proof

The report is created before diagnosis with `O_CREAT|O_EXCL|O_NOFOLLOW`, mode
`0600`.  Before the first WAL or target write, roothealth uses
`posix_fallocate` (or a build-qualified equivalent with the same allocation
guarantee) to reserve the complete 4 MiB file while it still contains only
invalid zero bytes and allocates every fixed report/sample arena.  It freezes
the report envelope and the complete current-batch plan, computes the
max-escaped serialized bound, and permits a later batch only when that batch
fits the already frozen envelope and is completely preflighted immediately
before its own commit.  It does not pretend to preflight a future batch before
the required intervening fresh rescan/replan.

`report_budget` has exactly `limit_bytes`, `reservation_method`,
`reserved_bytes`, `reserved_before_mutation`,
`fixed_buffers_allocated_before_mutation`,
`envelope_frozen_before_mutation`,
`every_committed_batch_preflighted_before_its_commit`,
`future_batches_envelope_constrained`, `worst_case_bytes`,
`written_bytes`, `size_proof_format`, and `size_proof_hash`, followed for
each prefix `repair`, `batch`, `wal_action`, and `issue` by exactly
`_samples_limit`, `_samples_emitted`, `_samples_omitted`,
`_priority_emitted`, and `_priority_omitted`.  Reservation method is
`POSIX_FALLOCATE`, format is `RHSIZE3`, limit/reservation are both
4,194,304, and every ordering boolean is true.  Emitted plus omitted equals
the corresponding streaming-ledger total, and the priority pair equals its
exact priority/error aggregate.

The `RHSIZE3` hash input is the eight bytes `RHSIZE3\0`, little-endian
`u32` format `3`, then these 28 little-endian `u64` constants in order:
report limit, worst-case bytes; repair limit/edge; batch limit/edge; WAL
limit/edge; issue limit/edge; maximum action-target, issue-code, issue-pass,
issue-path, issue-message, predicate-count, predicate-bytes,
issue-action-ordinal-count, rescan-JSON, fixed-envelope, JSON-escape,
device-path, mapper-name, version-text, identity-text, serial-text, fixed-system
check-ID bytes, and measured fixed-field bytes.  At most 17 fixed-system check
records are present and each check ID is at most 255 canonical ASCII bytes.
The 32-byte maximum-envelope hash and 32-byte fixed-field hash follow.  The
frozen maximum vector is 3,466,470 bytes with SHA-256
`d0f04d213d43dca8fe85d7ec2adbb9efb7cfbe56015f0899f42a82f208ec7ad6`.
The independently materialized exact non-sample schema (including full
`initial`/`final`, `wal` and its ledger, `batch_ledger`,
`issue_ledger`, four foundation actions, plan/commit, identity/device,
native-log, result, and budget fields) is 98,927 bytes with
SHA-256
`54f41614828eac7d21067812657883c7b299ef0d9021921b904834cfef58fb85`,
within their 128 KiB slot.  The resulting size-proof hash is
`03e7d405abfb81027dddd44ec44c970b7f35221deddaabb55e78ededcf70f8a4`.
The maximum envelope leaves 727,834 bytes of the reservation unused; a
4,194,305-byte document is a mandatory rejection.
Adding one otherwise omitted fixed field to make the non-sample object
131,073 bytes is also a mandatory pre-mutation rejection.

Publication uses a bounded full-`pwrite` loop for the complete JSON into that
invalid reservation, then `ftruncate` to the exact JSON length and
`fdatasync`.  A kill before truncation leaves zero padding or partial JSON and
therefore never a valid success document.  Any reservation, allocation,
size-proof, write, truncate, sync, or close failure is exit `5`, performs no
later target write, and synchronously removes only the file created by that
invocation when its retained handle/name identity is still provable.  Failure
to prove that identity or to unlink is itself a propagated exit `5` cleanup
failure; it may leave the invalid reservation but may never delete a
replacement.  Static closure tests prove report reservation/arenas/envelope and
per-batch preflight dominate every typed writer call.  Power-cut qualification
retains every physical write even though production JSON reports only bounded
samples.

## Qualification gate

Release tests retain the read-only checker corpus and add a real fixture for
each repair family.  Every fixture is repaired, independently checked, and
compared with raw metadata plus content/namespace manifests.  A target-specific
write interceptor enumerates every device-write boundary.  Fresh clones are
killed immediately before and after each boundary; none may be falsely
approved, and one subsequent repair invocation must converge to an independent
clean result.  A release build may not classify an interrupted state from any
action it can emit as an unsupported-WAL refusal; every such action needs its
action-specific recovery rederivation and convergence proof.  The suite also
proves wrong-root zero-write refusal, clean
zero-write behaviour on a writable device, report-path safety, I/O failure
mapping, absence of hidden direct writes, and absence of `lost+found`.
