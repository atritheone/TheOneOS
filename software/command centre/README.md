# The One OS Command Centre

A Windows desktop control surface for the current T1OS build, release,
validation, virtual-machine, hardware-USB, managed-Python, and runtime
development workflows.

The privileged Electron process and the renderer use one typed command
catalogue. Every visible workflow is an allowlisted script plus fixed,
reviewable arguments; the renderer cannot execute arbitrary PowerShell. Use
the search field to find a workflow and enable `advanced workflows` for
focused stage builds, selective USB updates, diagnostics, and specialist
tests. A running command can be stopped together with its child-process tree
from the output panel.

The catalogue currently covers:

- storage image mounting, inspection, repair, users, debug policy, backup, and
  production preparation;
- full and fast managed-tree synchronisation plus installed-USB maintenance;
- image, graphics, audio/media, network, driver, VirtualBox, Chromium, and
  RootHealth runtime builds;
- canonical Python 3.14 verification, source rebuild, candidate staging,
  promotion, provenance, and deployment tests;
- current combined VM build/run flows, disposable Brick/GUI/feature suites,
  release smoke boots, graphics/video diagnostics, resize tests, and log
  extraction;
- planned, complete, no-QEMU, and artifacts-only hardware-USB builds, selective
  updates, compatibility audits, image/bundle validation, QEMU boot, and
  guarded physical flashing; and
- content-addressed QEMU, OpenGL, audio/media, image, KMS, Brick, compositor,
  lifecycle, clipboard, Chromium, RootHealth, and hardware contract tests.

The editable current-version field is persisted in the project-root `current_version.txt` file. Source and disk backup names include that version automatically.

`push to disk` mounts `environment/software/storage.img` when needed and uses checksums
to synchronise the managed build, boot, driver, catalogue, runtime-software,
provisioned-setting, font, Expanse-artwork, and mouse-cursor sources. It
transfers only new or changed files, removes obsolete files from fully managed
runtime trees, verifies the result, syncs the filesystem, and unmounts it when
finished. Runtime-owned network, DNS, and interface settings are preserved;
the certificate bundle and an explicitly configured, open-network-only source
`wireless.txt` are updated, while protected Wi-Fi credentials are created only
on the target device through T1OS Settings. The source `network.txt` is used only to seed a missing runtime
file. The command centre stores
the last successful push in the project-root `last_push.txt` file and displays
it below the button as `HH:MM:DD:MM:YYY` (for example, a 2026 timestamp ends
in `6AE`), where the Atreyan year is the Gregorian year minus 2020.
The graphics push includes `source/catalogue/graphics`; the obsolete
`source/software/graphics` and `/the one/software/graphics` tier is not read,
created, synchronised, verified, or removed by this command.
The development-only `resource/tests/opengl 3d test.py` is outside every
synchronised source tree. It is not pushed, removed, or otherwise changed by
this command.

`create disk user` is available whenever `storage.img` is mounted, including
when an active user already exists. It creates the same master credential
format and home-directory tree as T1OS startup, then atomically makes the new
account the active master. Existing home directories and their files are
preserved. The password is sent to the PowerShell process over standard input,
hashed by the current T1OS authentication broker using versioned Argon2id (or
the broker's bounded scrypt fallback), and is never written or printed as
plaintext. `change disk user` authenticates the current password and can rename
the home, replace the password, or do both atomically. `remove disk user`
requires the exact active username and current password before deleting the
credential and private home.

The matching `create usb user`, `change usb user`, `remove usb user`, and
`toggle usb debug mode` workflows apply those operations to one unambiguous,
healthy, writable physical T1OS USB. The target must be a non-system USB NTFS
volume with the expected T1OS identity and filesystem inventory. Command
Centre mounts it into WSL only for the scoped broker operation and always
attempts to sync and detach it afterward.

The command layout is fluid: groups and command cards expand across all
available window width when Command Centre is maximised, while retaining a
single-column-safe minimum at narrow widths. Displayed command names are
normalised to lowercase by the shared catalogue.

`create new disk` creates a blank ext4 raw image matching the size and filesystem geometry of `environment/software/storage.img`. When `storage.img` exists, the new file is named `storage_new.img`; it never overwrites an existing image.

`clean disk` repairs an unmounted ext4 image with `e2fsck`. A temporary
per-problem policy forces the request to create `/lost+found` to `no`, even
while other repairs are approved, and an undo-file guard rolls the repair back
if that directory appears unexpectedly.

`prepare prod disk` mounts the disk if needed, disables enabled production
debug constants in the on-disk Python build, removes users, caches, logs,
rubbish, `lost+found`, ephemeral state, and mounted-driver placeholders, then
atomically replaces `/the one/settings` with a strict production-default
inventory. System-owned network, media, runtime-path, VirtualBox, and terminfo
data is retained or refreshed from source; audio, Expanse, Brick, Chromium, and
all other user/runtime settings are reset. The command writes the current
version to `/the one/settings/t1osversion.txt`, verifies the complete settings
inventory, and proves with a before/after tree digest that the end-user tests in
`/software` were not changed before it syncs and unmounts the filesystem.

## Run

From PowerShell:

```powershell
& '.\scripts\tools\run command centre.ps1'
```

For UI development with Vite hot reload:

```powershell
npm run dev
```

## Portable executable

Build the single-file Windows executable with:

```powershell
npm run portable
```

The result is written to `release/T1OS Command Centre Portable.exe`. Keep it
anywhere inside the t1os project tree so it can locate `scripts`, `source`, and
`environment`. If it must be launched from elsewhere, set `T1OS_PROJECT_ROOT`
to the full t1os project directory first.

## Safety behaviour

- Only command identifiers defined in the Electron main process can be executed.
- The renderer and main process consume the same catalogue, preventing hidden
  backend actions or stale UI-only buttons.
- Only one command can run at a time.
- Stopping a command terminates its PowerShell process tree, including helpers
  launched beneath it. Because a forced stop can interrupt script cleanup, the
  UI requires confirmation and it should be used only for a stuck workflow.
- Disk conversion, disk backup, VM builds and testing are disabled while `/mnt/t1fs` is mounted.
- The renderer has no direct Node.js or PowerShell access.
- WSL mount status is refreshed every three seconds from WSL's persistent PID
  1 mount namespace. A mount is accepted as `mounted` only when `/mnt/t1fs` is
  backed by this project's `environment/software/storage.img`; a different source is
  reported as unavailable and is never unmounted by the command centre.
- While the disk is mounted, the disk-user line reads the username before the
  first colon in `/the one/master/master.txt`, or shows `no user` when that
  file is absent.
- Creating a disk user requires the mounted image to be verified as this
  project's `storage.img`; it remains available when the disk-user line already
  shows an account.
- The `open disk` pill beneath `current version` opens `/mnt/t1fs` in Windows
  Explorer while the disk is mounted and remains visible but muted while it is
  unmounted.
- While the disk is mounted, `debug mode` scans recognised uppercase Python
  debug flags under `/the one/build`, `/boot`, and `/software`. It is `on` when
  any flag is enabled and `off` when all flags are disabled. The disk command
  toggles and normalises every recognised flag together; user files and the
  third-party catalogue are not changed.
- Disk health is checked with `e2fsck -f -n` only while `storage.img` is
  unmounted. The `-n` option keeps the image read-only, so the check cannot
  repair the filesystem or create `lost+found`.
- The last confirmed `ok` or `corrupted` health result remains visible while
  the disk is mounted; unmounting invalidates its image signature and triggers
  a fresh check.
- Disk-sensitive commands recheck the authoritative mount state in the main
  process immediately before launch. Their PowerShell guards use the same PID
  1 namespace, and mounted-disk test operations enter that namespace for bind
  mounts, file access, chroots, and cleanup.
- Command startup blocks the periodic disk-user and disk-health probes, so a
  background probe cannot acquire `storage.img` between a command's preflight
  check and its PowerShell process starting.
- VirtualBox conversion preserves the existing VDI until a replacement has
  converted successfully. If Windows shell or OneDrive metadata processing is
  holding `storage.img` with sharing rules VirtualBox cannot use, conversion
  reads an unmounted, consistency-checked temporary snapshot outside OneDrive
  and removes it afterward.
- VirtualBox VM creation retries the bounded transient states reported while
  VirtualBox is releasing a session or preparing a newly registered object.
  Configuration still stops immediately for non-transient errors, and every
  system, display, audio, network, serial, controller, and media-attachment
  operation is checked before the build is reported as successful.
- Output colours are semantic: confirmed failures and error diagnostics are
  red, system and status messages are light blue, and raw script diagnostics
  are neutral even when a tool writes progress or warnings to stderr.

The t1os PowerShell scripts remain the operational backend. All development scripts live in the repository's project-root `scripts` directory and resolve assets through the neighbouring `environment` directory, independently of the caller's current working directory.

## Virtual machine workflow

`build for vbox` and `build for vmware` regenerate the boot ISO, derive its
`root=UUID` from the current `environment/software/storage.img`, convert a fresh virtual
disk, and create the VM configuration. The run commands refuse to start stale,
mis-sized, misconfigured, or incorrectly attached VM artifacts and report the
build command needed to repair them.

From PowerShell, the corresponding entry points are:

```powershell
& '.\scripts\vm\build vbox.ps1'
& '.\scripts\vm\run vbox.ps1'

& '.\scripts\vm\build vmware.ps1'
& '.\scripts\vm\run vmware.ps1'
```

To check both installed hypervisors and all generated VM media without starting
a guest:

```powershell
& '.\scripts\tests\test vm setup.ps1'
```

Release smoke boots use disposable full clones and leave the ready VM disks
untouched:

```powershell
& '.\scripts\tests\test release vbox.ps1'
& '.\scripts\tests\test release vmware.ps1'
```

For development, use the VirtualBox disposable test harness instead of
rebuilding or driving the release VM for every Brick change. One headless boot
accepts a batch of structured Brick directives through a private writable
request/response share, while a second read-only share exposes the current
`source/build software` tree. The guest agent has no network listener or shell
action and selects only Brick's fixed headless or graphical entry point:

```powershell
& '.\scripts\tests\test t1os vm.ps1' -Suite Smoke
& '.\scripts\tests\test t1os vm.ps1' -Suite Brick
& '.\scripts\tests\test t1os vm.ps1' -Suite Gui
& '.\scripts\tests\test t1os vm.ps1' -Suite Full
```

`Brick` is the normal fast development gate. The harness prepares one test-only
template from the last validated release VDI, injects only the restricted test
agent into that derivative, and then uses linked disposable clones, so it does
not rebuild or alter the release VM or synchronise unrelated large runtimes.
`Gui` detects whether the baseline needs first-run account creation or an
existing-user login, completes that flow inside the disposable clone, launches
the workspace copy of Brick, injects real VirtualBox keyboard input, and records
nonblank, resolution-checked, distinct screenshots for each account/session
transition, the desktop, Brick, directive output, and the maximized window.
`Full` combines the
complete structured diagnostics with those GUI transitions. Reports, serial
evidence, and GUI screenshots are written under `environment/hardware` and the
temporary VM is always removed. Rebuild the base VM only when boot, native
runtime, or intended release disk content changes. Guest-agent changes refresh
only the test template; ordinary Brick Python iterations run from the read-only
workspace share.

The cheaper host-side Brick directive diagnostic remains useful before a VM
boot:

```powershell
& '.\scripts\test.ps1' -BrickDirectives
```

## Hardware USB workflow

The `hardware usb` and `validation` groups expose both the normal release
endpoints and the focused stages needed for current development. `install
hardware tools` is the one-time environment setup; `plan complete USB build`
prints the complete dependency order without changing artifacts.

`build complete usb` runs the complete dependency-ordered workflow: firmware,
kernel and modules, the driver loader, graphics, audio, network, Chromium,
runtime-path audits, initramfs, root synchronisation, artifact checks, image
assembly and validation, followed by the QEMU/OVMF boot test. After the
development/runtime tests and before assembly, `storage.img` is reset with the
same verified production-preparation pass used by `prepare prod disk`. Before assembly,
`validate desktop compatibility` proves that the module allowlist and
compatibility contract agree, every module dependency is packaged, declared
firmware is present and hashed, both CPU-vendor microcode families exist, and
the Intel/AMD/NVIDIA graphics runtime has a closed library dependency set. The individual
stage scripts, including wireless configuration and desktop-compatibility
validation, remain available from PowerShell for focused iteration and
diagnosis, but are not duplicated as normal dashboard buttons.

`rebuild USB image and bundle` is retained as a faster endpoint when the
underlying artifacts are already current. It creates the current 16 GiB
production image, keeps the previous validated image and manifest until their
replacements succeed, and validates the capacity-independent bundle. `boot-test
USB in QEMU` reruns only the boot test, which validates the image first.

`flash usb` now discovers eligible targets inside its own dialog, displays the
exact case-sensitive erase confirmation for the selected disk, and reports the
protected Biwin NV7400 and WD My Passport disks as excluded. Flashing still
requires that exact phrase, an elevated Command Centre process, the image's
validated manifest and hash, and complete write/read-back verification. It
does not expose the large-disk override.

Secure Boot private-key generation and encrypted production-image creation
remain deliberate command-line procedures in `docs/hardware-usb-boot.md`, so
secret paths and passphrase-file choices are not normal dashboard actions.
