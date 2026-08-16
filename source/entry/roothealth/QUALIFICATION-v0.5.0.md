# RootHealth v0.5.0 qualification record

Release qualification requires:

- a clean supported T1OS root exits `--boot-repair` with status 0, zero target
  writes, and no complete-census provider invocation;
- bounded journal location reads the provisioned record directly and does not
  enumerate MFT records or allocation ownership;
- sole-valid boot and MFT peers converge through direct redundant repair;
- an exact native-log replay converges before dirty clearing;
- an exact T1OS-empty native log plus dirty flag converges through the mirrored
  dirty-clear protocol;
- power interruption between the two dirty-peer writes is recovered
  conservatively by restoring dirty before retrying;
- ambiguous valid peers, hibernation, unexpected journal state, wrong identity,
  physical I/O, and unsupported native-log actions remain no-write refusals;
- Angel contains one `--boot-repair` call, no normal `--repair` call, no force
  mount fallback, no progress heartbeat, and an eight-second hard timeout;
- the offline comprehensive checker and legacy operations-file migration tests
  remain available but are not reachable from normal boot.
