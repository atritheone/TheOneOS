# RootHealth failure taxonomy v1

Exit `2` remains a boot-blocking result, but it is not a diagnosis by itself.
Every non-clean format-3 report contains one stable primary issue code, the
checking or repair pass which refused, and the complete sorted set of failed
predicates. Angel maps the code to one of these operational classes:

- `repairable`: a recognized repair or its independent rescan did not finish
  cleanly;
- `recovery-required`: qualified native-log or RootHealth WAL recovery must
  finish before mounting;
- `unsupported`: the release cannot completely validate the observed metadata;
- `ambiguous-corruption`: metadata evidence conflicts and no exact safe repair
  is qualified;
- `io`: reads or writes are uncertain and media/connection diagnosis is needed;
- `wrong-root`: device identity does not match the attested T1OS root;
- `internal`: RootHealth did not complete its own orchestration contract.

The stable v1 codes are `REPAIR_POST_RESCAN_FAILED`, `VOLUME_DIRTY`,
`WAL_RECOVERY_REQUIRED`, `WAL_UNSAFE`, `NATIVE_LOG_REPLAY_REQUIRED`,
`NATIVE_LOG_UNSUPPORTED_ACTION`, `CENSUS_INCOMPLETE`,
`UNSUPPORTED_VALID_METADATA`, `MFT_MIRROR_UNSUPPORTED_LAYOUT`,
`MFT_MIRROR_DIVERGENCE`, `MFT_BITMAP_MISMATCH`,
`INDEX_BITMAP_MISMATCH`, `CLUSTER_BITMAP_MISMATCH`,
`NAMESPACE_RECIPROCITY_MISMATCH`, `FIXED_SYSTEM_CHECK_FAILED`,
`FOUNDATION_REPAIR_DEFERRED`, `METADATA_UNRESOLVED`, `TARGET_IO_ERROR`,
`IDENTITY_MISMATCH`, and `ORCHESTRATION_INTERNAL_ERROR`.

## Evidence gate for new repairs

A new automatic repair class requires all of the following before production:

1. an untouched failed `roothealth.json`, stderr, boot evidence, and kernel log;
2. a sector-identical disposable clone or a minimal reproducible image;
3. a stable primary code and complete provider/census evidence;
4. unique independent authority for every output byte;
5. a typed WAL action and semantic recovery verifier;
6. exact positive, neighbouring ambiguity, zero-write refusal, idempotence,
   post-rescan, write-fault, and every-boundary power-cut tests.

Valid NTFS metadata which RootHealth merely does not understand expands the
validation surface; it is not rewritten to resemble a fixture. Ambiguous
metadata remains a refusal. Reports can be compared without changing them by
running `scripts/roothealth-repair/classify-report.py` against one or more
preserved JSON files. `recurrence=exact` identifies a stable missing
validation/repair class; `recurrence=varying` directs attention to media,
connection, power-loss, or nondeterministic-checker evidence.

## Shutdown gate

GODDESS cannot raw-check the filesystem from which Python PID 1 is executing.
After services and storage are quiesced it atomically writes
`T1OS/roothealth-shutdown-request` on the ESP and restarts into Angel. Angel
runs the normal full repair admission while the NTFS root is genuinely
unmounted. A requested restart continues only after exit `0`; a requested
power-off powers off from initramfs only after exit `0`. Failure preserves the
request and diagnostics and enters cause-aware recovery.
