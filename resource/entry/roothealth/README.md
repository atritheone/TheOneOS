# roothealth

`roothealth` is the offline NTFS checker and repair engine for the T1OS
hardware root drive.  It replaces `ntfsfix` before the first root mount.  It
has no Windows runtime dependency, adds no boot mode or partition, and treats
the persistent T1OS namespace as T1OS data rather than a Linux hierarchy.

The normative safety, repair, report, and boot rules are in
`REPAIR-CONTRACT.md`; the internal crash journal is specified by
`JOURNAL-FORMAT.md`.

## Interfaces

Angel uses only the bounded boot mode:

```text
roothealth --boot-repair --require-t1os-root --expected-serial SERIAL \
  --expected-journal-uuid UUID --expected-journal-record RECORD:SEQUENCE \
  DEVICE
```

Engineering and offline recovery retain the comprehensive modes:

```text
roothealth --check --require-t1os-root --expected-serial SERIAL \
  --expected-journal-uuid UUID --expected-journal-record RECORD:SEQUENCE \
  --report NEW DEVICE

roothealth --repair --require-t1os-root --expected-serial SERIAL \
  --expected-journal-uuid UUID --expected-journal-record RECORD:SEQUENCE \
  --report NEW DEVICE
```

The comprehensive modes run the same complete checker.  `--repair` is non-interactive and
may perform only a closed, evidence-backed transformation selected by the
RootHealth policy.  Generic upstream `-a`, `-p`, `-r`, `-y`, salvage,
hibernation-discard, log-reset, and delete-to-make-consistent behavior is not
exposed.

The stable exits are:

| Exit | Meaning |
| ---: | --- |
| `0` | Fresh read-only rescan proved clean, log-clean, not dirty, and T1OS |
| `2` | Unsupported, ambiguous, destructive, or unresolved corruption |
| `3` | Device or physical I/O failure |
| `4` | Wrong root or unexpected NTFS serial |
| `5` | Usage, report, timeout, or internal failure |

Only exit `0` permits boot.

## Bounded boot check and repair

`--boot-repair` does not enumerate the filesystem. It reads the two NTFS boot
records, the four mirrored bootstrap FILE records, the provisioned RootHealth
journal record and headers, the native NTFS restart state, the dirty flag, and
the minimum T1OS identity paths. A clean root performs no write and does not
scan the MFT, allocation maps, directory graph, security metadata, user files,
or the retired operations registry.

The bounded repair surface is limited to a uniquely valid redundant boot or
MFT peer, exact native-log replay, and the mirrored dirty flag. Each repair is
followed immediately by another bounded pass. The command has no full-census
fallback; an unrecognized condition is refused for offline recovery.

## What the comprehensive modes check

A clean verdict accounts for the boot copies, `$MFT`/`$MFTMirr`, every FILE
record and attribute extent, mapping pairs and cluster ownership, native
`$LogFile`, directory and metadata indexes, reciprocal namespace links, both
allocation bitmaps, `$Secure`, `$Reparse`, `$UpCase`, `$AttrDef`, sparse and
compressed attributes, fixed system records, `$Extend/$ObjId`, `$Quota`, and
an optional `$UsnJrnl`, the raw T1OS identity graph, and the internal
RootHealth journal.  An explicit coverage ledger must reconcile
every expected and examined object; a skipped pass or unknown denominator can
never become clean.

The release repair profile is deliberately bounded to 512-byte NTFS sectors,
4096-byte clusters, 1024-byte MFT records, 4096-byte index blocks, and volumes
up to 256 GiB.  It supports the pinned NTFS `$ATTRIBUTE_LIST` maximum of
`0x40000` bytes exactly; smaller implementation-only metadata/count ceilings
are forbidden.  Release roots also carry the pinned formatter's cluster-aligned
`$LogFile` of at most 64 MiB, attested by image and resize validation.  Other
layouts fail closed without repair.

## Repair and crash safety

Discovery and planning use a read overlay and perform no target mutation.
Before the persistent journal is reachable, RootHealth can restore only one
readable, structurally invalid boot or mirrored bootstrap record from its
sole strictly valid peer.  Read failures and conflicting valid peers are
never overwrite authority.

All nonredundant metadata changes use the preallocated 128 MiB unnamed data
stream at `$Extend/$RootHealth`.  This is internal NTFS metadata, not a T1OS
directory or extra partition.  Each full-sector before image, typed semantic
target, evidence seal, transaction plan, durability barrier, target readback,
and state transition is validated.  Interrupted transactions roll back or
finish on the next invocation.  A derived repair larger than one journal
transaction is committed in deterministic, freshly revalidated batches; the
transaction limit is not a filesystem-size limit.  Native-log redo/undo is
never prefix-committed and remains one indivisible WAL transaction.  The NTFS
dirty flag remains set until a fresh process has completed the full post-repair
check; dirty clearing is a separate journal transaction followed by another
fresh-process rescan.

The T1OS ntfs3 runtime does not create a Windows redo stream.  A recognized
wiped/empty native log left dirty by a T1OS power loss is therefore checked as
a zero-log-write state: RootHealth proves the complete volume, then uses only
the normal journalled dirty-clear transaction.  It never invents or resets log
records.  A merely syntactic pair of restart pages with zero/contradictory
LSNs is not treated as an empty log and remains a zero-write unsafe refusal.

Safe transformations include uniquely derivable bitmap, index, namespace,
security-index, fixed-table, attribute-list, runlist, link-count, and
compressed-metadata repairs.  RootHealth reconnects an intact orphan to its
proved original parent, or to the existing
`the one/recovered files/roothealth` directory when no parent can be proven.
It never creates `lost+found` or a top-level recovery directory.  Missing
source data, corrupt compressed payload, unreadable records, ambiguous
ownership, and conflicting valid authorities remain exit `2` rather than
being discarded or guessed.

## Boot behavior

The initramfs selects the root partition independently of its potentially
damaged NTFS boot sector, then invokes exactly one `--boot-repair` command with
an eight-second hard budget before the first mount. The command is silent on
success. The expected NTFS serial and provisioned journal identity come from
the boot artifact. On success, the existing first mount is read-only and
independently verifies the T1OS release tree before the normal read-write
reopen. Full format-3 reports remain an offline `--check`/`--repair` facility.

## Qualification and licensing

The production gate includes a clean zero-write test, one fixture per repair
family, wrong-root and I/O no-write tests, parser sanitizers, exact repair
policy and linked-I/O audits, native-log opcode preflight, report-path safety,
raw namespace/content comparisons, and materialized power-cut states before
and after every target write and real sync barrier.  Every action the binary
can emit must recover and converge; qualification cannot hide it behind an
unsupported-WAL result.

The build consumes a hash-pinned `ntfsprogs-plus` source revision, carries the
semantic NTFS-3G 2026.7.7 corrupt-input hardening, builds a stripped hardened
x86-64 PIE with libc as its only runtime dependency, and emits build metadata,
GPL-2.0 `COPYING`, and a deterministic corresponding-source archive containing
the pristine upstream archive, exact patch series, build recipe, and hashes.
Windows `chkdsk` may be used only as an optional engineering comparison on
disposable fixtures; neither the build, boot path, repair policy, nor end user
depends on Windows.
