# T1OS VirtualBox testing

The Codex test appliance uses one immutable VirtualBox template and a disposable linked clone per run. This keeps repeated tests fast, prevents test state from leaking between runs, and supports both semantic headless assertions and real 1920x1080 GUI screenshots.

## Run it

From the repository root in PowerShell:

```powershell
& 'scripts\vm\run monitored vm test.ps1' -Suite Smoke
& 'scripts\vm\run monitored vm test.ps1' -Suite Brick
& 'scripts\vm\run monitored vm test.ps1' -Suite Gui
& 'scripts\vm\run monitored vm test.ps1' -Suite Features
& 'scripts\vm\run monitored vm test.ps1' -Suite Full
```

Use the monitored wrapper for normal work. It coordinates with the Chromium release-build lock, watches Windows and WSL builders, records their resource/file behaviour, and terminates an uncoordinated pathological build by Linux process group so compiler children are not orphaned.

The lower-level preparation command is normally automatic:

```powershell
& 'scripts\vm\prepare vm test vbox.ps1'
```

It clones the last validated `environment\software\t1os-root.vdi`, overlays the current `source\build software`, provisions test-only integration, validates the ext4 filesystem, and creates `T1OS Codex Test Base` with snapshot `codex-clean`. Its signed manifest is `environment\software\t1os-vm-test-base.json`. A source, agent, fixture, package-index, ISO, or builder change invalidates the signature and rebuilds the template; otherwise preparation is a quick no-op.

## Suites

| Suite | Coverage |
| --- | --- |
| `Smoke` | Boot readiness and small Brick assertions. |
| `Brick` | Headless parser, directive, and dogfood diagnostics. |
| `Gui` | Lock screen, login, desktop, real graphical Brick, keyboard input, and window control. |
| `Features` | GUI password prompt, Settings Python manager, interactive Brick PTY/Python program, managed-module import, and Player video. |
| `Full` | Complete Brick diagnostics plus all GUI and feature coverage. |

Each run creates a linked clone under `environment\software\t1os-vm-test-<token>`, starts it headlessly, and removes the clone when finished. The test agent accepts only fixed application/status operations through the explicitly attached VirtualBox exchange share; it is not a general guest shell or network service.

## GUI and evidence

GUI input is delivered through VirtualBox's keyboard and absolute-pointer interfaces. Screenshots come from the VM framebuffer, not a mocked renderer. The latest evidence is copied to:

- `environment\software\t1os-vm-test-gui`
- `environment\software\t1os-vm-test-report.json`
- `environment\software\t1os-vm-test-serial.log`

Important feature frames are `11-password-prompt-empty.png`, `12-password-prompt-filled.png`, `15a-brick-terminal-reply.png`, `16-brick-terminal-pass.png`, `17-player-video-frame-a.png`, and `18-player-video-frame-b.png`. Screenshot stages require the expected 1920x1080 dimensions, nonblank content, sufficient colour variation, and—where an interaction must change the screen—a distinct hash.

## Test account and deterministic packages

The immutable template contains the requested test login:

```text
development
password
```

The feature suite installs the real third-party `humanize` wheel using the T1OS Settings and Python services. The signed local simple-index mirror at `environment\hardware\t1os-python-index` makes this deterministic and avoids weakening T1OS's fail-closed network policy. Managed files are isolated under `/software/t1os-python` in the disposable appliance. The interactive fixture is installed as `/master/development/terminal_test.py`, owned by the desktop identity, and exercises arguments, stdin/stdout TTY state, terminal dimensions, `TERM`, ANSI output, interactive input, and the managed import.

Player is launched through the authenticated Operations broker with the fixed media path `/software/without_a_blush.mp4`. The feature suite requires brokered test status tied to the tracked Player process and path: positive duration and playback position, a decoded frame with non-zero dimensions, and no playback error. Two distinct framebuffer captures provide the accompanying visual proof that video frames advance.

## Chromium coordination

`development\chromium release\chromium-release-build.lock` serializes a deliberate release build against VM testing. A VM run refuses to start while another process holds that lock. Once a VM test is running, a new uncoordinated T1OS Chromium runtime/source build is unrelated to the suite and is stopped immediately; generic builders are stopped only after age, CPU, or workspace-file-surge thresholds are exceeded.

Do not bypass the lock simply to gain CPU time. Inspect `.ninja_log`, compiler activity, staging-file count, and repository file count first. A busy build that is completing objects without growing the project workspace is not pathological; a stalled or repeatedly respawning build, orphaned compiler group, or multi-thousand-file repository surge is.

## Requirements

- Oracle VirtualBox with `VBoxManage` available (the default Program Files installation is detected).
- WSL distribution `Ubuntu` with `qemu-nbd`, ext4 tools, and permission to load the `nbd` module for offline template preparation.
- The base VM `The One OS` registered and powered off.
- The validated base VDI and boot ISO at `environment\software\t1os-root.vdi` and `environment\software\t1os-boot.iso`.

The harness deliberately uses the VM's PS/2 keyboard and VMSVGA 1920x1080 scanout because those are the devices T1OS opens and can capture reliably in a headless VirtualBox session.

Validate both supported VM launchers after replacing `environment\software\storage.img`:

```powershell
& 'scripts\vm\build vmware.ps1'
& 'scripts\vm\build vbox.ps1'
& 'scripts\tests\test vm setup.ps1'
```

The boot scripts create the least-privilege ephemeral media and audio runtime directories before the desktop starts. Player, the decoder, and the audio service validate their ownership and modes rather than silently widening permissions at runtime.
