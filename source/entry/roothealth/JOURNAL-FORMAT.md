# `$Extend/$RootHealth` journal format v1

All integers are little-endian; fields explicitly named as VCN or LCN values
are signed two's-complement 64-bit integers and all others are unsigned.  UUID
fields use the 16 RFC 4122 network-order bytes emitted by standard UUID
parsers.  All unused bytes are zero and readers reject non-zero reserved
bytes.  The journal file is exactly 134,217,728 bytes in release images.

## Superblocks

Two 4096-byte superblocks occupy file offsets 0 and 4096.  A superblock is
valid only when every fixed field, bound, reserved byte, and checksum is valid.
The reader selects the valid copy with the greatest generation; a generation
tie with differing bytes is corruption.  A writer updates only the older slot,
syncs it, and leaves the previous valid slot intact.

When both copies validate, they must also form a legal adjacent pair.  Equal
generations require byte-identical headers.  Unequal generations differ by
exactly one and permit only `EMPTY` to `EMPTY` or `PREPARING`, `PREPARING` to
`APPLYING` or `ROLLBACK`, `APPLYING` to the next `APPLYING`, `COMMITTED`, or
`ROLLBACK`, `COMMITTED` to `EMPTY` or `ROLLBACK`, and `ROLLBACK` to `EMPTY`.
Two non-empty members of a pair retain the same transaction UUID, complete
plan hash, and transaction kind.  Successive `APPLYING` headers add exactly
one committed entry; `COMMITTED` and `ROLLBACK` preserve the preceding durable
prefix.  A pair with a generation gap, regressing prefix, or unrelated valid
transaction is corruption rather than authority selection.

| Offset | Size | Field |
| ---: | ---: | --- |
| `0x000` | 16 | ASCII magic `T1ROOTHEALTHWAL` followed by one NUL byte |
| `0x010` | 4 | format version, `1` |
| `0x014` | 4 | header size, `4096` |
| `0x018` | 4 | NTFS bytes per sector |
| `0x01c` | 4 | transaction state |
| `0x020` | 8 | monotonically increasing generation |
| `0x028` | 8 | raw NTFS volume serial |
| `0x030` | 16 | persistent journal UUID |
| `0x040` | 16 | current transaction UUID, or zero in `EMPTY` |
| `0x050` | 8 | journal file size, `134217728` |
| `0x058` | 8 | entry-area start, `8192` |
| `0x060` | 8 | committed bytes used in the entry area |
| `0x068` | 8 | committed entry count |
| `0x070` | 8 | sum of unpadded target lengths |
| `0x078` | 32 | complete ordered transaction-plan SHA-256, or zero in `EMPTY` |
| `0x098` | 8 | maximum target bytes, `104857600` in release seeds |
| `0x0a0` | 4 | transaction kind: `0=none`, `1=metadata repair`, `2=dirty clear` |
| `0x0a4` | 4 | maximum entry count, `4096` in v1 |
| `0x0a8` | 3896 | reserved, zero |
| `0xfe0` | 32 | SHA-256 of bytes `0x000..0xfdf` |

The state values are `0=EMPTY`, `1=PREPARING`, `2=APPLYING`,
`3=COMMITTED`, and `4=ROLLBACK`.  Transaction kind is zero only in `EMPTY`;
all other states use exactly one of the two defined kinds.  Metadata repair and
dirty-clear are deliberately separate transactions so a crash cannot publish
a clean dirty flag while structural repair is still unverified.  An `EMPTY`
header has a zero transaction UUID, transaction kind, `data_used`,
`entry_count`, `target_bytes`, and plan hash.  Release seed headers are both
valid and `EMPTY`, with generations 1 and 2.

Every non-`EMPTY` header has a nonzero transaction UUID and nonzero plan hash.
Roothealth computes that hash over the complete ordered plan before the first
journal or target mutation; v1 does not permit an unbounded streaming plan.
The canonical plan byte stream is the concatenation, in ordinal order, of each
eventual descriptor's bytes `0x000..0x1df` (magic through the complete semantic
target seal).  Payload offsets, padded lengths, semantic identities, evidence,
and intended transitions are therefore fixed during planning.  Only the
descriptor checksum is outside the plan hash.

The plan hash always describes the complete precomputed plan, not merely the
durable descriptor prefix named by a `PREPARING`, `APPLYING`, or `ROLLBACK`
header.  After an interrupted prefix write, v1 may not contain the unwritten
suffix and therefore cannot recompute the complete hash.  Recovery of those
states validates every committed descriptor, checksum, payload, ordinal,
bound, and target hash in the durable prefix before rolling that prefix back.
A `COMMITTED` header names the complete descriptor set; its descriptors must
recompute exactly to the recorded complete-plan hash before finalization or
rollback is permitted.

The writer rejects more than 4096 entries even when byte capacity remains.
It also independently enforces `data_used` against the physical entry-area
capacity and `target_bytes` against the advertised maximum.  The entry limit
keeps the worst-case descriptor and 512-byte sector-padding overhead within
the 128 MiB file when the target-byte limit is reached.
These are limits of one crash-atomic transaction, not limits on a valid NTFS
volume or on one roothealth invocation.  A larger derived repair is partitioned
into deterministic dependency-ordered metadata transactions.  Each batch is
independently recovered and freshly revalidated while the volume remains
dirty, and the next batch is replanned from that fresh view.  No batch may
split a semantic action or a required primary/mirror pair.

Action-kind validation is part of the transaction format.  `$Volume` is MFT
record 3 and is covered by `$MFTMirr` in the release geometry, so a dirty flag
change is always an exact two-entry physical pair: primary-record sector first,
matching mirror-record sector second.  A dirty-clear transaction contains
exactly that ordered pair of volume-dirty-clear entries.  A metadata-repair
transaction contains no dirty-clear entry and may contain at most one semantic
dirty-set operation; when present, its two volume-dirty-set entries occupy
ordinals zero and one.  The pair must encode the same flag transition and the
attested primary/mirror physical locations.  Unknown kinds, a singleton,
reversed or disagreeing pair, or a kind combination which does not match the
header transaction kind makes the descriptor set invalid before recovery
writes begin.

Native redo entries (ID 5) form one contiguous group after an optional leading
dirty-set pair and before every derived repair.  A metadata transaction which
contains any ID 5 entry contains exactly two ID 6 entries for the independently
validated native restart-page copies, and those are the final two target
entries after all derived repairs.  ID 6 without ID 5, an ID 5 after a derived
action, a missing or extra restart copy, or any target after the restart suffix
is invalid.  The recognized T1OS wiped/empty-log plus dirty-volume state
contains neither ID 5 nor ID 6; it leaves `$LogFile` byte-for-byte unchanged
and relies on the complete checker before the separate dirty-clear transaction.

## Entries

The entry area is a sequence of 512-byte descriptors followed immediately by
the descriptor's old-byte payload padded with zero bytes to the NTFS sector
size.  Each next descriptor begins at the following sector boundary.  A
descriptor is valid only if the referenced payload lies wholly within
`data_used`, its ordinal is contiguous from zero, and its hashes and checksum
validate.

| Offset | Size | Field |
| ---: | ---: | --- |
| `0x000` | 8 | ASCII magic `RHENTRY1` |
| `0x008` | 4 | entry version, `1` |
| `0x00c` | 4 | descriptor size, `512` |
| `0x010` | 8 | zero-based ordinal |
| `0x018` | 8 | absolute target-device byte offset |
| `0x020` | 8 | unpadded target length |
| `0x028` | 8 | absolute journal-file offset of old-byte payload |
| `0x030` | 8 | sector-padded payload length |
| `0x038` | 4 | typed roothealth action kind |
| `0x03c` | 4 | entry flags, zero for v1 |
| `0x040` | 32 | SHA-256 of bytes present before the target write |
| `0x060` | 32 | SHA-256 of intended bytes after the target write |
| `0x080` | 4 | semantic-seal version, `1` |
| `0x084` | 4 | semantic target-object identifier |
| `0x088` | 8 | owning MFT record number, or zero only for a boot sector |
| `0x090` | 2 | owning MFT record sequence number |
| `0x092` | 2 | exact attribute instance |
| `0x094` | 4 | NTFS attribute type |
| `0x098` | 2 | exact attribute-name length in UTF-16 code units |
| `0x09a` | 2 | semantic target flags |
| `0x09c` | 4 | evidence-format version |
| `0x0a0` | 32 | SHA-256 of the exact UTF-16LE attribute name; SHA-256 of empty bytes for an unnamed attribute |
| `0x0c0` | 8 | signed lowest VCN of the owning extent |
| `0x0c8` | 8 | signed logical VCN containing the semantic target |
| `0x0d0` | 8 | logical byte offset within the named attribute |
| `0x0d8` | 8 | logical attribute length covered by the evidence |
| `0x0e0` | 8 | absolute logical-device coordinate of the semantic subrange |
| `0x0e8` | 8 | semantic subrange length |
| `0x0f0` | 8 | signed physical LCN, or the target-specific sentinel defined below |
| `0x0f8` | 8 | evidence generation |
| `0x100` | 32 | SHA-256 of the canonical target-specific authority evidence |
| `0x120` | 32 | SHA-256 of the canonical staged view used to derive the target |
| `0x140` | 32 | SHA-256 of the semantic bytes before this operation |
| `0x160` | 32 | SHA-256 of the semantic bytes after this operation |
| `0x180` | 96 | reserved, zero |
| `0x1e0` | 32 | SHA-256 of descriptor bytes `0x000..0x1df` |

The old-byte payload hash must equal the descriptor's old hash; zero padding
is not hashed.  Target ranges must be in volume bounds and must not intersect
any physical extent belonging to `$Extend/$RootHealth` or the physical `$MFT`
bytes of its base FILE record.

For boot and nonresident targets, the semantic coordinate at `0x0e0` is also
the literal raw device offset.  For an MFT-contained target it is the record
base plus the offset in the post-fixup logical record.  It remains inside the
complete physical record range, but it is not a promise that the corresponding
raw byte is stored there: a logical sector-trailer byte is represented in the
record's USA.  Action-specific recovery interprets this coordinate only after
MST validation and post-read fixup.  Accordingly, the descriptor hashes at
`0x140` and `0x160` cover only those logical semantic bytes; the hashes at
`0x040` and `0x060` independently cover the complete raw record before and
after MST protection.  Hashing the complete record into both pairs is invalid.

The semantic target-object values are `1=primary boot sector`, `2=backup boot
sector`, `3=primary MFT record`, `4=mirrored MFT record`, `5=nonresident
attribute`, and `6=allocation proved free in the complete pre-transaction
census`; zero and all other values are invalid.  Target flags are
`0x0001=primary`, `0x0002=mirror`, `0x0004=resident`,
`0x0008=nonresident`, `0x0010=pre-transaction free`, `0x0020=set-only`,
`0x0040=clear-only`, and `0x0080=native-log-derived`.  No other flag bit is
valid.  The action ID, target object, flags, attribute identity, and range must
form one of roothealth's closed action-specific combinations; a structurally
valid but semantically incompatible combination is corruption.

Evidence is serialized canonically field by field and never by hashing a C
structure, native pointer, padding byte, or host-endian value.  It binds the
record sequence and complete attribute identity, the exact mapping-pairs
extent and VCN-to-LCN result, allocation and ownership census, and any
action-specific authority such as the peer-copy digest, index parent/child
reciprocity, or native `$LogFile` source LSN.  `evidence_generation` is a
nonzero transaction/report correlation value which the descriptor and plan
hash bind; it is not target authority, and recovery never seeds or weakens its
fresh evidence from that field.  The staged-view hash binds the
ordered overlay after all earlier plan entries.  Recovery reconstructs the
pre-transaction view by overlaying journalled old sectors in reverse ordinal
order, then reruns the action-specific derivation.  No recovery target write
is allowed unless that derivation reproduces the descriptor's physical range,
semantic identity, evidence hash, and before image.  `COMMITTED` recovery also
reproduces the staged/post-repair evidence and complete plan hash before it may
accept the transaction.  A descriptor with internally consistent hashes but a
retargeted record, attribute, LCN, or semantic range is therefore rejected.

The recovery implementation has an exact action-verifier registry.  Before it
calls any verifier it proves that every descriptor action ID is known and has
a registered verifier; an unknown or unregistered ID refuses the whole
transaction.  Verifiers receive the complete ordered transaction as immutable
entry views plus bounded read-only accessors for the reconstructed
pre-transaction view and journalled old payloads.  They cannot enqueue, mutate,
or retain a writer pointer.  One group verifier may own several action IDs and
is called once, allowing it to rederive primary/mirror pairing, native
ID-5/ID-6 ordering, and cumulative cross-entry evidence.  Multiple independent
groups may coexist in one transaction and each must validate its own entries
while respecting the full transaction predicates.  There is no generic
digest-only fallback: a compiled action ID remains unsupported until its
specific group verifier and evidence constructor are installed.

The v1 typed action identifiers are fixed and form part of the recovery ABI:

| ID | Action |
| ---: | --- |
| 1 | primary boot-sector copy |
| 2 | backup boot-sector copy |
| 3 | primary mirrored-bootstrap MFT record |
| 4 | `$MFTMirr` bootstrap record |
| 5 | native `$LogFile` redo |
| 6 | native `$LogFile` restart page |
| 7 | generic MFT record |
| 8 | `$ATTRIBUTE_LIST` |
| 9 | nonresident runlist mapping pairs |
| 10 | attribute data |
| 11 | index root |
| 12 | index allocation block |
| 13 | index allocation bitmap |
| 14 | relocated cluster data |
| 15 | T1OS recovery-namespace metadata |
| 16 | `$Reparse` index |
| 17 | `$Secure:$SDS` |
| 18 | `$Secure:$SDH` |
| 19 | `$Secure:$SII` |
| 20 | `$UpCase` data |
| 21 | `$AttrDef` data |
| 22 | `$MFT` allocation bitmap |
| 23 | volume cluster bitmap |
| 24 | volume dirty-set |
| 25 | volume dirty-clear |

No other nonzero ID is valid in format v1.  IDs 1--4 are reachable through
the redundant-copy foundation; IDs 5--25 require the persistent WAL.  The
native replay plan uses IDs 5 and 6 through the same persistent WAL machinery,
rather than invoking a separate direct-write path.  The complete native plan
is one indivisible initial metadata transaction; it may contain derived entries
between its ID 5 group and final ID 6 pair, and later derived-only repairs may
use additional batches.

The closed semantic tuple table below is also part of v1.  `MFT-P` and `MFT-M`
mean target objects 3 and 4; `NONRES` and `FREE` mean objects 5 and 6.  An MFT
target has the exact primary or mirror plus resident flag and identifies the
containing record/sequence.  A nonresident target has the nonresident flag and
identifies the complete attribute name, instance, lowest VCN, logical VCN and
derived LCN.  `FREE` additionally has `pre-transaction-free` and carries the
complete unique-ownership/free-allocation proof.  Attribute names in this
table refer to the attribute-header name, not a filename payload.

| ID | Permitted target and exact attribute identity |
| ---: | --- |
| 1 | primary boot object, primary flag, no MFT/attribute identity |
| 2 | backup boot object, mirror flag, no MFT/attribute identity |
| 3 | `MFT-P`, complete record 0--3, no attribute identity |
| 4 | `MFT-M`, complete record 0--3, no attribute identity |
| 5 | `MFT-P`, `MFT-M`, or `NONRES`, with native-log-derived; `InitializeFileRecordSegment` may instead use `MFT-P` for record >3 with resident, primary, pre-transaction-free, and native-log-derived flags; the qualified source LSN/open-attribute rule below additionally derives the exact tuple |
| 6 | `NONRES`, record 2, unnamed `AT_DATA` (`0x80`), native-log-derived |
| 7 | `MFT-P` or `MFT-M`, one complete MFT record, no attribute identity |
| 8 | MFT-contained or `NONRES`, unnamed `AT_ATTRIBUTE_LIST` (`0x20`) |
| 9 | MFT-contained mapping-pairs bytes of one exactly identified nonresident attribute |
| 10 | MFT-contained resident or `NONRES` `AT_DATA` (`0x80`), with its exact optional name |
| 11 | MFT-contained named `AT_INDEX_ROOT` (`0x90`) |
| 12 | `NONRES` named `AT_INDEX_ALLOCATION` (`0xa0`) |
| 13 | MFT-contained or `NONRES` named `AT_BITMAP` (`0xb0`) belonging to an index |
| 14 | `NONRES` or `FREE` `AT_DATA` (`0x80`), bound to the source stream and destination ownership plan |
| 15 | MFT-contained unnamed `AT_FILE_NAME` (`0x30`) or named `AT_INDEX_ROOT`; or `NONRES` named `AT_INDEX_ALLOCATION`/`AT_BITMAP`, only for the T1OS recovery namespace |
| 16 | record 26 and name `$R`: MFT-contained `AT_INDEX_ROOT`, or `NONRES` `AT_INDEX_ALLOCATION`/`AT_BITMAP` |
| 17 | `NONRES`, record 9, named `$SDS` `AT_DATA` |
| 18 | record 9 and name `$SDH`: MFT-contained `AT_INDEX_ROOT`, or `NONRES` `AT_INDEX_ALLOCATION`/`AT_BITMAP` |
| 19 | record 9 and name `$SII`: MFT-contained `AT_INDEX_ROOT`, or `NONRES` `AT_INDEX_ALLOCATION`/`AT_BITMAP` |
| 20 | `NONRES`, record 10, unnamed `AT_DATA`, with the canonical `$UpCase` size/hash authority |
| 21 | `NONRES`, record 4, unnamed `AT_DATA`, with the canonical `$AttrDef` size/hash and complete type-use census |
| 22 | `NONRES`, record 0, unnamed `AT_BITMAP`, set/clear constrained by the full MFT/namespace census |
| 23 | `NONRES`, record 6, unnamed `AT_DATA`, set/clear constrained by the full cluster-ownership census |
| 24 | `MFT-P` then `MFT-M`, record 3, unnamed resident `AT_VOLUME_INFORMATION` (`0x70`) flags at logical offset `0x0a`, length 2, set-only |
| 25 | `MFT-P` then `MFT-M`, the same record/attribute/range, clear-only |

For IDs 3, 4 and 7, “complete record” means a record-size semantic target and
zero type, instance and name fields.  For ID 9, “MFT-contained” describes the
physical write location only: recovery must reparse the named attribute and
prove it is nonresident, that the bytes are its mapping-pairs field, and that
the persisted extent/VCN evidence derives the same target.  IDs 16--21 reject
every cross-product of a correct record with a wrong type/name, or a correct
type/name with a wrong record.  IDs 20 and 21 also bind the release-profile
stream digests defined in the repair contract.  A format-valid ID 5 descriptor
is never sufficient by itself: recovery must independently validate the
native transaction/control tables, source LSN, exact open-attribute binding,
runlist-to-LCN mapping, semantic operation bounds and protected-range policy.
The pre-transaction-free MFT variant additionally binds the exact arbitrary
1024-byte stale before-image and a valid complete logged FILE after-image.  Its
immutable outer seal proves the old MFT-bitmap bit clear and the slot wholly
unreferenced by the complete raw-MFT, extent, allocation, and namespace
censuses; recovery rederives those facts from the virtual pre-transaction
view.  A zero old record is not required, records 0--3 are forbidden, and no
mirror action is inferred.
Until that complete replay qualification succeeds, ID 5 is unsupported and a
transaction containing it is refused without a WAL or target write.

Every MFT-contained action (including a record-targeted ID 5 and IDs 8--11,
13, 15, 16, 18 and 19) is serialized as the complete MST-protected raw MFT
record, even when its logical semantic change is one byte.  The semantic seal
still names the exact attribute/header and logical subrange.  Recovery
reconstructs the pre-transaction fixed record, rederives that subrange,
regenerates the USA and sector trailers, and requires the resulting
complete-record before/after images.  A descriptor which targets only the
apparent physical location of an MFT-contained value is invalid because
logical trailer bytes may instead reside in the USA.  The only exception is
the exact paired ID 24/25 two-byte flags field, whose pinned record-3 layout
and non-USA location are rederived independently during recovery.

## Durable update protocol

For a new target write, write and sync the old-byte payload first, then write
and sync its descriptor.  Advance the alternate valid superblock so
`data_used` and `entry_count` include the entry, and sync it before touching
the target.  Write and sync the target, read it back, and require the new hash.
Overlapping target entries are permitted and ordered; rollback processes them
in reverse ordinal order.  Any semantic mutation whose MFT record number is in
the geometry's mirrored range has an adjacent matching physical `$MFTMirr`
entry of the same action kind; a plan missing either copy is invalid.

`PREPARING` or `APPLYING` recovery writes `ROLLBACK`, restores and verifies
every entry in reverse order, and only then publishes `EMPTY`.  A target that
already has the recorded old hash needs no restore; a target matching neither
hash is still restored from the journal copy.  `COMMITTED` is never treated as
clean by itself: roothealth reopens the device read-only and acts according to
the recorded transaction kind.  For a metadata-repair transaction it completes
the structural, allocation, native-log, and identity rescan while the NTFS
dirty flag remains set.  For a dirty-clear transaction it completes the final
clean/not-dirty rescan.  Only a successful kind-appropriate rescan may publish
`EMPTY`; otherwise roothealth rolls back when every old byte is available and
verifiable, or refuses the volume.

Raw superblock, descriptor, and payload I/O uses the independently validated
journal runlist and bypasses the normal intercepted target-write path.  It can
write nowhere else.
