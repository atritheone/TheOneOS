# RootHealth v0.5.2 boot-admission rollout

Version 0.5.2 makes the normal boot decision from boot-critical NTFS state.
After the primary and backup boot sectors agree on supported geometry and the
expected serial, RootHealth reads the selected LFS restart page, the `$Volume`
dirty flag, and the hibernation state. A supported clean restart page plus a
clear dirty flag and no hibernation admits boot immediately with no writes.

The normal path no longer waits for or depends on RootHealth's exact
release-specific `$MFT`/`$MFTMirr` FILE-record repair schema. That schema is a
safe bounded repair surface, not a valid cleanliness test for every layout
Windows may produce. It remains active whenever the fast proof is incomplete,
including every genuinely dirty or unclean root.

The probe reads only the NTFS mount bootstrap, `$Volume`, the hibernation
header when present, and the two restart pages. It does not scan the MFT,
locate the private repair WAL, traverse the namespace, parse historical log
records, plan a repair, or open a writable device descriptor.

Angel continues to invoke `roothealth --boot-repair` once before the first
writable NTFS mount. Roll back v0.5.2 if an unclean or dirty root is admitted,
the clean path changes the target hash, a valid clean Windows root is refused
at `mft-mirror`, or the clean path exceeds the boot latency budget.
