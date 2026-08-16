# RootHealth v0.4.1 diagnostic rollout

Version 0.4.1 does not expand the automatic repair surface. It preserves the
v0.4.0 fail-closed policy while correcting the diagnosis of an early
`mft-mirror` refusal observed on the first physical canary.

The canary reached the expected NTFS root, proved its identity and empty
RootHealth WAL, then stopped before native-log inspection and before the
complete census. Version 0.4.0 incorrectly reported that early refusal as
`CENSUS_INCOMPLETE`.

Version 0.4.1 distinguishes a valid-but-divergent mirrored record from a pair
of records outside the qualified bootstrap layouts. Its single refusal line
records the MFT record number, both structural verdicts, first differing byte,
differing-byte count, and SHA-256 fingerprints of both raw records. It never
includes record contents and does not authorize a write from this evidence.

Angel also preserves root-device probe evidence and displays a periodic
RootHealth heartbeat on the physical console. The next physical boot remains
a diagnostic canary and must not be promoted as a production release.

Deploy the RootHealth binary, source bundle, metadata, Angel initramfs and
tests as one generation. Roll back the complete generation if the canary does
not produce one of the new precise mirror codes or if any zero-write or report
contract test fails.
