# RootHealth v0.4.1 qualification record

Qualification date: 2026-08-15

This diagnostic generation retains the v0.4.0 repair policy and adds evidence
for the physical `mft-mirror` refusal. It introduces no new automatic repair.

Required automated evidence:

1. Production compilation and linked-input audit pass.
2. Existing RootHealth read-only, repair, WAL, write-fault and report tests
   remain green.
3. Valid-divergence and both-unsupported mirror cases receive distinct stable
   codes, retain the `mft-mirror` pass, and produce zero planned operations.
4. Root discovery persists each candidate's `blkid` status and metadata.
5. Angel preserves the new evidence on the ESP and shows periodic progress
   while the unmounted check runs.

The physical canary remains outstanding. A physical refusal is useful only as
diagnostic evidence; it does not qualify either mirror copy as repair
authority.
