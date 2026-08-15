# `$Reparse`, `$ObjId`, and `$Quota` reader-only authority slice

## Status and containment

This is a source-bound diagnostic/reference-manifest proposal.  It adds no
write, overlay, WAL, action, recovery, or policy interface.  The production
translation unit is labelled `DIAGNOSTIC`/`READER`; its mutation-primitive
audit is empty.  All current repair policies remain closed.

The checker consumes the common immutable `rh_census_reader`, the complete raw
MFT census, and the complete namespace/I30 census.  It does not introduce a
device or mapping-pairs ABI.  Record-extent and `ATTRIBUTE_LIST` assembly,
including opaque bytes after the first mapping-pairs terminator, is delegated
to `rh_raw_mft_stream_pread_reader`.

The result is opaque and hash-revalidated.  The only reference-manifest export
is a source-owned typed seal for each free-slot component already present in
main: `REPARSE` and `OBJID`.  Callers cannot choose a component kind or assert a
completion boolean.

## Evidence and authority rules

The common raw census must be bounded and complete for records, attributes,
attribute lists, extents and runs.  Records 24, 25 and 26 must be live base
records.  The namespace census must be complete, I30-backed, reciprocal, and
cover every raw `FILE_NAME` link.  All inputs must share one nonzero generation
and nonzero evidence hashes.  An incomplete or stale input produces a
hash-bound incomplete diagnostic result and no typed seal.

For `$Reparse:$R`, every live unnamed `$REPARSE_POINT` is parsed and reconciled
with `$STANDARD_INFORMATION` reparse flags and the complete I30 namespace tag
and flag evidence.  The canonical `(tag, file-reference)` manifest is compared
with a structurally validated index.  The free-slot manifest is the sorted,
deduplicated union of canonical source references and structurally valid
observed references.

For `$ObjId:$O`, every live unnamed 16- or 64-byte `$OBJECT_ID` is parsed,
duplicate object IDs are refused, and the exact object-ID/file-reference/index
payload manifest is derived.  A 16-byte attribute obtains its optional 48
bytes only from a structurally valid matching current index entry; otherwise
authority is absent.  A 64-byte attribute carries that evidence itself.  The
typed free-slot manifest again preserves the union of canonical and valid
observed references.

For `$Quota:$O/$Q`, `$Q` is the sole accounting authority.  Entries validate
owner IDs, versions, flags, thresholds/limits, SID structure and padding.  The
derived SID-to-owner `$O` manifest must match the observed `$O`, every v3
`$STANDARD_INFORMATION.owner_id` must resolve to a live `$Q` user, and the
default owner is unique.  An `$O` mismatch is diagnosable while `$Q` authority
remains complete.  A malformed `$Q` closes Quota authority; `$O` and SI owner
IDs cannot reconstruct usage, limits, thresholds, times or flags.

Resident SMALL_INDEX and 4096-byte INDEX_ALLOCATION plus BITMAP structures are
parsed with MST fixup, checked tree traversal, unique reachability, key
ordering, END accounting and an exact allocation bitmap.  The implementation
is deliberately limited to the T1OS 4096-byte cluster/index-block profile.

## Source boundary

At freeze time the isolated tree's common files exactly matched main:

```
roothealth_raw_mft.c                 43577aa87668d92fa9662ea0c5ff4bab9be5de82a95ef0250eda9ffc48b6d15a
roothealth_raw_mft.h                 35860e170172853059ab37f632ccf7d842b3d62dad5a6f23df340ece3a5f1acb
roothealth_namespace.c               511e15752200c15b69441883d7cb62681c6ad5c9c2c3eebed867cbf20b57fab6
roothealth_namespace.h               d6a356e930433c91b7209e4c7c609f550a11511d0b51bee792199304b420c977
roothealth_census_device.c           517fb77e08418457d16320139ee9a6aa266d00523b035fa5ced7ff7bebbf1dde
roothealth_census_device.h           d56d684f57b8431de3c48c73fa293a243119442a5473071e828301ff61a14bd7
roothealth_free_slot_authority.c      aa3e7dd03006749fe4be9fea144d1032129ea363bb05be3d699cf57e1a71cdcc
roothealth_free_slot_authority.h      c320cf76e0067e8d03a7610ee018187b7454a07e334e27621ce45fd6f8cc266e
roothealth_free_slot_authority_internal.h
                                      50aaeb531e2c43c4c29440fa7410ebbd9afa8e155e475157c2ed55c1a23bb909
roothealth_write.c                    af7c6c3781015e1a552f7ae8a4a09823092e2f6d5c4580920a9a399ac835dc85
roothealth_write.h                    7cc30774d850e4c6cd2060c4809b1a33e9b019ac9aa64eff3b7cbccb29ba31f7
libntfs.a                             f3a3eeaff6ab32ac2dd9434903d8e8d159fa2fe2abd2e7aaaf23c3f24e34517c
```

No common file and no libntfs file is changed by this patch.

## Exact release and fixture matrix

The exact read-only T1OS image SHA-256 is
`0596099c95d7d177e95f71852ea1eb644c90f51ca5cee2f52bb9115dc724e2fa`.
Its checker result is:

```
raw_system_indexes=green mode=release reparse_live=0 reparse_end=1 objid_live=0 objid_end=1 quota_o_live=1 quota_o_end=1 quota_q_live=2 quota_q_end=1 quota_users=1 si=22739 file_names=22980 attrlists=317 extents=323 refs=0/0 quota_si_refs=0 operations=0 hash=a8ab34c6d112ab54423018615af46e912eb9bdeca76aecfc37480eaed1004d7d reparse=e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855 objid=e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855 quota=d22a226bbabc81ecec96e1785cc05655ab3793b92da5b88638dbf00310088d5a
```

The frozen `$Secure` release regression was rerun on the same image and still
reports seven legacy descriptors, 29 live central entries plus one structural
END, 20 referenced central IDs, 21 distinct MFT SI IDs, and zero operations.
Exact `$SDH` and `$SII` lookup remains green for all 29 live IDs.

The nonempty fixture SHA-256 is
`ba27141c7fac317013fdb8ec3de5692a3e467a20b5875f8aa5e1d4de68790de6`.
It contains one reparse point and one object ID and produces typed seals with
one exact reference each:

```
raw_system_indexes=green mode=fixture reparse_live=1 reparse_end=1 objid_live=1 objid_end=1 quota_o_live=1 quota_o_end=1 quota_q_live=2 quota_q_end=1 quota_users=1 si=21 file_names=17 attrlists=0 extents=0 refs=1/1 quota_si_refs=0 operations=0 hash=471b41665ae09e958132d99a04960ddf874804928f710d049ab24ca3bec37eb5 reparse=f99a5dd4e8910270ce0fb811c5e97bc89945b7cf4272c1b7e54e667e22b3d26d objid=50f43558efc16f41060b003061a488e76ea480f8315b0b68fec4c7afe6113f1f quota=c0887d17ed3262cc4fb919fe80cc6d3bdbe7cc74e1eae2a4e02f45f5e4dbc19f
```

Negative/refusal results are:

```
raw_system_indexes=green mode=source-refuse generation=mismatch authority=absent seal=refused operations=0
raw_system_indexes=green mode=refuse-reparse authority=complete observed_index=invalid seal=refused objid_seal=green operations=0
raw_system_indexes=green mode=refuse-objid authority=absent observed_index=invalid seal=refused reparse_seal=green operations=0
raw_system_indexes=green mode=quota-o-mismatch q_authority=complete o_manifest=mismatch operations=0
raw_system_indexes=green mode=quota-q-refuse q_authority=absent quota_policy=closed operations=0
```

SHA-256 verification before and after all strict scans was unchanged for the
release, clean fixture and every negative fixture.  Every result also checks
`writer.operation_count == 0`.

The common opaque mapping-tail regression remains green:

```
raw-sparse flags=0x8000 unit=4 physical_clusters=2 hole_clusters=30 opaque_tail=clean-and-bound wrong_unit=refused unflagged_hole=refused writes=0
```

## Qualification

The production module, release harness, fixture builder and fixture-only
mutator compile with `-std=gnu11 -Wall -Wextra -Werror`.  A GCC `-fanalyzer`
build of the production module and release harness is green.  ASan+UBSan with
leak detection and halt-on-error is green for the release, nonempty fixture,
stale-source refusal and all four corrupt/mismatch fixtures.  Sanitizer
qualification found and fixed zero-count `qsort(NULL, 0, ...)` calls.

Checked dynamic growth is used for manifests, walk frames, facts, references
and SID storage.  Integer multiplication/doubling is guarded.  Allocation
failure is propagated as an I/O/resource error and cannot produce a seal or a
write plan.

## Deliberately closed boundaries

1. The common reader ABI has no immutable device-identity token.  The
   integration ledger must bind the raw census, namespace census and this
   checker to one mounted reader instance; this slice does not invent a
   competing ABI.
2. Main has no Quota free-slot component kind/friend constructor.  Quota source
   references are evidence-bound internally, but no new public seal or action
   ABI is introduced here.
3. No rebuild target, action ID, WAL adapter, recovery-time rederivation or
   policy predicate is implemented.  No repair policy is authorized.
4. Nonresident 4096-byte index parsing is implemented but is not qualified by
   a large Reparse/ObjId/Quota fixture in this slice.  It must remain outside
   production authorization until large-tree, malformed-bitmap and recovery
   matrices exist.
5. The new source and tests are intentionally not added to the production
   Makefile in this source-bound proposal.  Integration must occur only after
   the immutable-reader identity and reviewed recovery registry boundaries are
   frozen.
