# RootHealth v0.4.0 qualification record

Qualification date: 2026-08-15

This record covers the automated phases of the v0.4.0 NTFS boot-admission
change. Tests used newly created disposable NTFS loop images under WSL. No
physical T1OS root, attached removable drive, or user data volume was mounted,
repaired, or written.

## Qualified behaviour

- Angel runs one complete `roothealth --repair` admission against the
  unmounted root before its first NTFS mount and boots only on exit `0`.
- A failed admission or later mount preserves the RootHealth report, stderr,
  boot evidence, mount information, kernel log, and Angel transcript on the
  ESP. There is no `force`-mount admission fallback.
- Angel does not create an operations registry. OperationsServer owns live
  state in memory and serves it at `/.ephemeral/operations/control.sock`.
  GODDESS publishes its complete supervised-process snapshot idempotently;
  `state.json` and bounded completion history are optional boot-scoped data
  under `/.ephemeral/operations`, never persistent boot prerequisites.
- The exact qualified namespace repair removes one stale resident `$I30` edge
  named `operations.txt` only after a complete raw census proves the child
  slot free, the path and parent unique, and every provider complete.
- The same bounded WAL transaction can contain that namespace repair plus
  fully derived `$MFT/$BITMAP`, index-bitmap set-only, and volume-allocation
  bitmap corrections. Recovery re-derives and verifies every semantic action.
- Nearby ambiguous, unreadable, live-child, wrong-name, reused-slot,
  large-index, and multi-edge cases remain zero-write refusals.
- Exit-2 reports expose a stable primary failure code, the refusing pass, and
  all observed failed predicates. Quiet admission still emits one concise
  refusal line with stage and errno.
- Orderly restart and power-off are mediated by an ESP request and the same
  unmounted Angel admission. Power-off completes from initramfs only after a
  clean result; failure enters cause-aware recovery.

## Automated evidence

The repair harness completed the combined field-shaped fixture containing the
stale operations entry, an MFT-bitmap difference, and a cluster-bitmap
difference. The repaired image passed the independent final census; a second
repair run was clean and byte-stable.

The native replay power-cut sweep covered 30 target writes, 35 durability
barriers, and all 305 materialized interruption states. The combined metadata
transaction covered 42 target writes, 44 durability barriers, a first target
write at event 5, and all 181 materialized durable states. Every recovered
state converged to either the complete old view or the complete new view; no
partial view was accepted.

The positive and refusal corpus includes the exact stale operations edge, the
combined bitmap case, an actual directory-index bitmap fixture,
`completed.json` in place of `operations.txt`, and two stale references. The
last two cases returned nonzero without a target write.

Production compilation uses `-Werror`, PIE, NX stack, full RELRO, immediate
binding, and `_FORTIFY_SOURCE=3`; the release executable has only `libc.so.6`
as a runtime dependency. The deterministic source bundle contains the repair
contract, rollout record, failure taxonomy, and this qualification record.

The following release commands are the authoritative reproducible checks:

```powershell
& '.\scripts\build roothealth.ps1'
& '.\scripts\test roothealth.ps1'
& '.\scripts\test roothealth repair.ps1'
& '.\scripts\build hardware initramfs.ps1'
& '.\scripts\test hardware build.ps1'
& '.\scripts\build hardware usb.ps1' -PlanOnly -SkipQemu
```

Final artifact hashes are recorded by
`environment/hardware/tools/roothealth.json`; they are not duplicated here so
that rebuilding the deterministic source bundle cannot make this record
self-referential.

## Outstanding physical gates

Automated qualification does not authorize an in-place test on the affected
drive. Before general rollout, install the complete signed generation on a
clean physical clone, retain the previous ESP generation and independent
recovery media, then preserve and inspect the ESP diagnostics from a canary
boot and two consecutive clean boots. Those boots must report exit `0`, a
complete clean ledger, no repair actions after the canary convergence, and no
persistent operations runtime files. The exact stale persistent
`operations.txt` case remains a transitional migration repair, not a live
registry design. Roll back the whole Angel/RootHealth
generation if any condition fails.
