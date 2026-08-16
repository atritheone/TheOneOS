# RootHealth v0.5.2 qualification record

Release qualification requires:

- `--boot-repair` evaluates the selected clean LFS restart page and the
  `$Volume` dirty flag before the release-specific four-record `$MFTMirr`
  repair schema;
- a matching primary and backup boot sector, supported selected clean restart
  page, clear dirty flag, and absent hibernation file exits status 0 with zero
  target writes and without walking historical log pages;
- a clean Windows volume is not refused merely because both usable mirrored
  FILE records have a valid Windows-evolved layout outside RootHealth's
  qualified repair schema;
- an unclean restart page, set dirty flag, hibernation image, boot-sector
  disagreement, or incomplete probe still enters the existing bounded repair
  path and cannot use the fast admission path;
- the v0.5.1 clean-restart historical-noise test remains below two seconds in
  qualification and preserves an identical target hash;
- malformed, ambiguous, or unsupported unclean logs remain no-write refusals;
- the v0.5.1 bounded WAL, identity, mirror-repair, dirty-clear,
  power-interruption, diagnostic, and timeout qualifications continue to pass;
- the offline comprehensive checker remains unavailable from normal boot.
