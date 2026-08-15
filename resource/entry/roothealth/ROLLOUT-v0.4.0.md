# RootHealth v0.4.0 rollout

Version 0.4.0 changes NTFS boot admission and expands the qualified repair
surface. It must not be mixed with an older Angel initramfs or an older
`$Extend/$RootHealth` recovery contract.

## Release gates

The release build is eligible for hardware images only after all of these pass
on disposable NTFS images:

1. The production RootHealth build and linked-input audit.
2. Unit and orchestration tests, policy/audit consistency, report validation,
   WAL recovery, write-fault, and power-cut tests.
3. A clean-image no-write run and two consecutive clean boots.
4. Exact stale resident `operations.txt` `$I30` corruption, with the MFT and
   volume bitmap differences seen in the field, repairs to exit `0`; a second
   run is clean and byte-stable.
5. Every nearby ambiguity fixture (large index, multiple stale entries, live,
   reused, unreadable or sequence-ambiguous child, index-bitmap clear, missing
   T1OS identity, altered journal binding) exits nonzero with zero target
   writes.
6. A power cut at every WAL boundary either restores the complete old view or
   completes the exact new view on the next invocation.
7. Angel invokes the complete unmounted admission before its first NTFS mount,
   contains no `force` mount path, and persists `roothealth.json`, stderr,
   boot evidence, mountinfo, dmesg, and the Angel transcript on failure.
8. OperationsServer alone owns the live in-memory registry and its Unix socket
   at `/.ephemeral/operations/control.sock`. GODDESS submits a retry-safe full
   bootstrap snapshot, the optional `state.json` checkpoint and bounded
   completion history remain boot-scoped tmpfs data, and normal supervision
   produces no operations-related NTFS writes.

## Qualification status (2026-08-15)

The disposable-image and build gates are complete. The exact combined field
case (one stale operations-registry index edge, one `$MFT/$BITMAP` difference,
and one volume-allocation-bitmap difference) repairs to a complete clean
rescan, and the next invocation is byte-stable. The native WAL sweep covers
305 interruption states; the combined metadata WAL sweep covers all 183
durable states. Exact wrong-name and multiple-stale-edge neighbours refuse
with zero target writes.

Angel admission, diagnostics persistence, legacy-repair qualification, the production
build, initramfs packaging, and hardware-build checks are automated release
gates. Their dated evidence is recorded in `QUALIFICATION-v0.4.0.md`.

The physical canary and its two consecutive clean boots are deliberately not
marked complete. They require the intended physical release clone, operator
control of rollback media, and preservation of ESP diagnostics. No physical
T1OS root was accessed during the disposable-image qualification.

## Deployment order

Publish the RootHealth binary, source bundle, metadata, contract, and Angel
initramfs as one signed boot generation. Validate that generation on a clean
clone, then on the corruption corpus, before installing it on a physical T1OS
root. Keep the previous signed ESP generation and independent recovery image
available for rollback. Do not test by mutating the user's attached T1OS drive.

## Acceptance and rollback

The first physical rollout is a canary. Preserve the ESP diagnostics from each
boot and compare RootHealth version, binary hash, exit status, scan ID, census
ledger, WAL transaction UUID, and final rescan. Expand only after repeated
clean boots show an empty repair ledger and no operations runtime state is
created in the persistent NTFS namespace. The exact old `operations.txt`
repair remains enabled for one migration period so affected installations can
reach the new boot-scoped design.

Rollback replaces the complete signed boot generation; it never downgrades
only Angel or only RootHealth. A v0.4.0 transaction left in the internal WAL
must be recovered by v0.4.0 before an older generation is booted.
