# RootHealth v0.5.0 bounded-boot rollout

Version 0.5.0 removes the comprehensive filesystem census from Angel's normal
boot path. Angel invokes `roothealth --boot-repair` once, silently, with an
eight-second hard limit before the first NTFS mount.

The bounded command reads only the redundant NTFS boot records, the four
mirrored bootstrap FILE records, the provisioned RootHealth journal record and
headers, native-log restart state, the mirrored dirty flag, and the minimum
T1OS identity paths. It may repair only a uniquely valid redundant peer, an
exact native-log replay plan, or the mirrored dirty flag. Every mutation is
followed by a new bounded pass and the command has no full-census fallback.

The old persistent `the one/settings/operations/operations.txt` policy remains
available only through offline comprehensive repair for migration of already
damaged media. Operations recording itself is boot-scoped socket state under
`/.ephemeral/operations` and is not a RootHealth boot concern.

Roll back v0.5.0 if a clean supported root exceeds the eight-second budget, if
the first read-only mount is admitted after a nonzero RootHealth exit, or if a
bounded repair cannot converge on its immediate rescan.
