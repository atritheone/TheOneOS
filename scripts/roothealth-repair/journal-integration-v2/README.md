# RootHealth journal image-integration proposal v1

Status: `PROPOSED_FAIL_CLOSED` — non-production, zero repair enablement.

This package is a source-bound, mechanically applicable proposal for creating and
attesting the fixed 128 MiB `$Extend/$RootHealth` journal while a fresh,
unmounted `*.building` NTFS image is being assembled. It does not alter the
workspace production scripts in place, does not touch init/boot code, does not
enable a repair path, and was qualified without running the production USB
image build.

The patch changes seven existing scripts and adds one fixture helper. It:

- accepts only a pinned, release-qualified d4 `ntfscp` provenance manifest in
  the production image builder;
- seeds the journal, copies it to `$Extend/$RootHealth`, provisions exact
  `0x00002007` STANDARD_INFORMATION/base-FILE_NAME/`$Extend::$I30` flags, and
  invokes only the builder-only block provisioner while the whole-disk output
  still ends in `.building`;
- retains O_NOFOLLOW-opened and exclusively locked whole-disk and block fds,
  proves plain-loop or exactly one dm-crypt layer, validates both GPT copies,
  binds exact p2 geometry, and repeats the full binding before open, after open,
  and after the journal fsync;
- completes an allocated-MFT ownership census and rejects journal run
  self-overlap or any second owner;
- carries serial, UUID, RECORD:SEQUENCE, exact flags, EMPTY header generations,
  ownership, write-exclusion, and tool/validator provenance through image, ESP,
  sidecar, bundle, inspection, shrink, and expansion manifests;
- independently revalidates the raw journal after population and every resize,
  while proving validation itself does not change the source or target image.

The public `provision-flags` command remains regular-file-only and is explicitly
tested to reject a block device. `provision-flags-device` is builder-only and
requires a retained `.building` backing-file identity plus the exact block/GPT
ancestry.

## Intentional release blocker

`ntfscp-provenance.proposed-test-only.json` binds the selected development
binary and pinned d4 source, but its build/link/qualification hashes are null.
The production builder rejects it. A distinct source-built tool package must
replace it with state `release-qualified` and non-null source-manifest,
link-manifest, and qualification hashes before this proposal can be considered
for integration.

## Verification

From the project root:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File `
  scripts/roothealth-repair/journal-integration-v1/verify.ps1
```

Add `-RunSyntheticBundleTest` for the bounded bundle-manifest positive/negative
test. Add both `-RunFixtureSuite` and `-NtfscpPath <selected-d4-ntfscp>` to rerun
the root-required disposable NTFS/GPT/plain/dm-crypt/resize matrix. The fixture
suite uses `wsl.exe -u root`; it never uses `sudo`.

The package intentionally contains no production binary and no generated USB
image.
