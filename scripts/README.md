# T1OS scripts

Scripts are grouped by responsibility:

- `build/` builds kernels, runtime payloads, images, and release inputs.
- `vm/` creates, converts, runs, and inspects VirtualBox and VMware environments.
- `deployment/` manages storage images, USB targets, backups, and mounted filesystems.
- `audits/` contains compatibility, provenance, and runtime validation commands.
- `tests/` contains test entry points and the existing hardware/runtime contract suites.
- `tools/` contains developer-facing utility launchers and notes.
- `roothealth-repair/` contains the versioned roothealth qualification assets.
- `fixtures/` contains shared test fixtures.

The files kept directly in this directory are shared infrastructure or stable release
entry points. Some are referenced by signed or hashed roothealth qualification
packages, so their paths are intentionally preserved.

Workspace cleanup is dry-run-first and includes the disposable Ubuntu WSL T1OS
development state from the same PowerShell program:

```powershell
pwsh -File 'scripts/tools/clean workspace.ps1'
pwsh -File 'scripts/tools/clean workspace.ps1' -Execute
```

Use `-SkipUbuntu` to restrict either mode to the Windows project. Current build
products, tracked sources, and reusable Python candidate data are protected by
the script's retention and verification gates.
