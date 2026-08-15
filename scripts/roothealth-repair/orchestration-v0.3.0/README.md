# Roothealth v0.3.0 orchestration proposal

Status: **PROPOSED_FAIL_CLOSED**

This package is the audited, mechanically applicable proposal for the unified
`roothealth --check|--repair` CLI and bounded format-3 reporting layer. It is
not production integration and contains no binary. The proposed executable has
no source-reachable target commit call; `--repair` therefore diagnoses and
refuses unsupported work without writing the NTFS target.

The proposal supplies the CLI, report reservation/publication lifecycle,
format-3 serialization, strict identity/journal arguments, and the bounded
self-exec rescan protocol. Enabling any repair requires a later reviewed patch
that links the complete checker, canonical non-empty `RHTXN3` evidence, WAL
recovery/action verification, and post-commit result/report orchestration.

## Contents

- `roothealth-v0.3.0-proposal.patch`: mechanical patch against the frozen
  `/var/tmp/roothealth-repair-dev.ntfstooling` copy recorded by the audit.
- `qualification.json`: status, hashes, test counts, ELF closure, and blockers.
- `complete-source.sha256`: all 524 regular files after applying the patch.
- `roothealth-linked-inputs.manifest`: exact 49 production translation units.
- `roothealth-linked-objects.tsv`: source/object SHA-256 binding for those 49
  inputs.
- `roothealth.link.map`: clean linker map used to derive the closure.
- `PACKAGE.sha256`: hashes for every other file in this directory.
- `verify.py`: read-only package and optional external-input verifier.

## Verify

Run without bytecode generation:

```sh
python3 -B verify.py
```

To bind the package to the frozen baseline and current normative inputs:

```sh
python3 -B verify.py \
  --baseline /var/tmp/roothealth-orchestration-testdesign-20260809-base \
  --baseline-manifest /var/tmp/roothealth-orchestration-testdesign-20260809.base-sha256 \
  --validator ../validate-report.py \
  --contract ../../../resource/entry/roothealth/REPAIR-CONTRACT.md
```

The final clean-room matrix passed twice with byte-identical binaries: 96 JSON
literal checks, 49 linked sources/objects, 6 CLI cases, 12 strict and 12
sanitized report cases, 6 positive and 12 negative rescan-packet cases, and 4
native-state, 1 forced-failure, and 7 full-report cases. The intentionally
unbound check-mode replay document is rejected.

Do not copy a test binary from `/var/tmp`, package this proposal as production,
or enable a target writer based on this package alone.
