# Incremental testing

Every T1OS test, validation, and audit entrypoint is content-addressed. Existing
commands remain valid; the entrypoint enters `incremental_test.py`, computes its
input identity, and executes its body only when that exact identity has not
already passed.

A normal cache hit is reported as:

```text
REUSED hardware.case.kernel-policy - input key 0123456789ab
```

The identity includes the task definition, normalized arguments, test
implementation, discovered and declared input content, and the relevant host,
WSL, QEMU, VirtualBox, or VMware identity. File digests are memoized using file
identity metadata, but test keys use content hashes: touching an unchanged file
does not rerun a test, and restoring previously tested content reuses its old
passing result.

Only successful completed executions are stored. Failed or interrupted tests
never create a reusable result. Concurrent callers for the same key share one
execution through an operating-system file lock. Declared evidence is copied
into the content-addressed result directory so a later suite cannot overwrite
the evidence belonging to an earlier result.

## Commands

Run the existing entrypoint as usual:

```powershell
& 'scripts/test hardware build.ps1'
& 'scripts/test t1os vm.ps1' -Suite Full
```

Inspect a task key and every input that formed it without running the task:

```powershell
python -B scripts/incremental_test.py explain `
    --script 'scripts/test video compatibility.py'
```

List registered tasks, show cached passing-key counts, or audit coverage:

```powershell
python -B scripts/incremental_test.py list
python -B scripts/incremental_test.py status
python -B scripts/incremental_test.py audit
```

Invalidate one task after diagnosing a cache or test-definition defect:

```powershell
python -B scripts/incremental_test.py invalidate --task hardware.case.kernel-policy
```

This is a maintenance operation, not part of normal testing. Changes to the
runner, task definition, test implementation, inputs, parameters, artifacts,
or relevant tools invalidate results automatically.

## State

Ignored local state is stored in `environment/.test-state/`:

- `digests.sqlite3` memoizes file content digests.
- `results/<task>/<key>.json` records an atomic passing result.
- `results/<task>/<key>.evidence/` contains immutable copied evidence.
- `locks/` contains persistent lock files; the operating system owns lock
  lifetime, so a killed process cannot leave a stale logical lock.

Deleting this directory is safe but discards reusable knowledge and causes
otherwise unnecessary work. Prefer task-specific invalidation.

## Adding or changing a test

1. Add the script to `incremental tests.json` with a stable task ID and the
   narrowest correct environment profile.
2. Declare generated, ignored, parameter-default, or dynamically constructed
   inputs explicitly. Authored paths referenced by PowerShell `Join-Path`,
   Python `Path / ...`, and literal script paths are discovered directly.
   Aggregate entrypoints declare the wider inputs of their child cases in the
   registry so scripts inspected merely as contract text do not pull unrelated
   subsystems into a task key.
3. Declare evidence that must remain attached to a passing result.
4. Add the language guard used by neighbouring scripts.
5. Run the registry audit and the runner self-test.

The audit fails for unregistered scripts, stale registry entries, duplicate task
IDs, and scripts that bypass their language guard.

## Orchestration

`test hardware build.ps1` is now a dispatcher over eleven independently cached
hardware cases. A kernel-policy change therefore runs the kernel-policy case
and relevant downstream artifact tests without repeating USB writer, Chromium,
network, font, or provenance cases.

`test.ps1` similarly dispatches separate graphics, audio, image, KMS, and QEMU
tasks. Nested calls—such as QEMU requesting static image validation—enter the
same task registry, so a prerequisite already proven for the same key is reused.
