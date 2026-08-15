# RootHealth v0.5.1 qualification record

Release qualification requires:

- a structurally valid clean Windows LFS restart page exits `--boot-repair`
  with status 0 and zero target writes, even when historical record pages
  contain operations outside the bounded replay surface;
- an unclean restart page still enters the exact bounded native replay path;
- malformed, ambiguous, or unsupported unclean logs remain no-write refusals;
- boot refusal output retains the original scan stage and errno and reports the
  separate repair-dispatch result plus WAL, identity, native-log, and dirty
  evidence;
- absent current-boot JSON removes the previous ESP JSON instead of retaining
  stale evidence;
- the v0.5.0 bounded boot, MFT mirror, WAL, dirty-clear, power-interruption,
  identity, and eight-second timeout qualifications continue to pass;
- the offline comprehensive checker remains unavailable from normal boot.
