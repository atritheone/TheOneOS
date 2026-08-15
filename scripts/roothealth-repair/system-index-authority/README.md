# System-index authority publication

This package is the source-bound, reader-only `$Reparse:$R`, `$ObjId:$O`, and
`$Quota:$O/$Q` diagnostic/reference-manifest slice.  It is not a repair or
policy authorization.

- `system-index-authority.patch` replays exactly against the bound baseline.
- `qualification.json` binds source, dependency, fixture, result and log
  hashes.
- `SYSTEM-INDEX-AUTHORITY.md` describes authority rules, qualification and
  deliberately closed boundaries.
- `verify.sh [baseline-tree]` checks package hashes and, when a baseline is
  supplied, runs the non-mutating whitespace-strict patch check.

The exact release remains read-only, `$Secure` remains 29 live entries plus one
structural END, and all repair policies remain closed.
