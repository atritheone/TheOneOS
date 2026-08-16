# RootHealth v0.5.1 clean-restart rollout

Version 0.5.1 preserves the bounded v0.5 boot path and fixes false refusal of
clean Windows NTFS volumes. After the selected LFS restart page passes the
release structural profile, a set `RESTART_VOLUME_IS_CLEAN` flag is accepted as
the authoritative shutdown verdict. Historical record pages are not replay
work and are not parsed on that clean path.

Angel still invokes `roothealth --boot-repair` once, silently, with an
eight-second hard limit before the first NTFS mount. Genuinely unclean native
logs still require an exact bounded replay plan; this release does not reset a
log, clear a dirty flag, or force-mount an unsupported volume.

Boot refusal output preserves the original scan stage and errno separately
from the repair-dispatch result, and includes bounded WAL, identity, native-log,
and dirty-state evidence. Angel removes a prior ESP diagnostic when the current
boot did not create a replacement, so stale reports cannot masquerade as the
current failure.

Roll back v0.5.1 if a structurally valid clean restart page is not admitted
without writes, an unclean log bypasses bounded replay, a clean supported root
exceeds the eight-second budget, or a refusal loses its original scan stage.
