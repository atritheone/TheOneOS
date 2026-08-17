export type CommandGroup =
  | 'workspace'
  | 'production'
  | 'runtimes'
  | 'python'
  | 'virtual machines'
  | 'hardware usb'
  | 'validation'
  | 'tests'

export type DiskRequirement = 'mounted' | 'unmounted' | 'known' | 'none'
export type CommandInput =
  | 'create-user'
  | 'change-user'
  | 'remove-user'
  | 'flash-usb'
  | 'wireless'

export interface CommandSpec {
  label: string
  detail: string
  group: CommandGroup
  script: string
  arguments?: readonly string[]
  disk?: DiskRequirement
  input?: CommandInput
  confirm?: string
  advanced?: boolean
  recordsPush?: boolean
}

const command = <T extends CommandSpec>(spec: T): T => ({
  ...spec,
  // Keep command names consistent even when a catalogue entry contains an
  // acronym or product name with capitals.
  label: spec.label.toLowerCase(),
})

// This catalogue is intentionally shared by Electron's privileged process and
// the renderer. Adding a backend action automatically makes it available to
// the UI, so the two sides cannot silently drift apart again. Fixed arguments
// expose safe, repeatable workflows without permitting arbitrary command or
// PowerShell execution from the renderer.
export const commandCatalogue = {
  'mount-disk': command({
    label: 'mount disk', detail: 'mount storage.img read/write at /mnt/t1fs', group: 'workspace',
    script: 'mount.ps1', disk: 'unmounted',
  }),
  'mount-disk-read-only': command({
    label: 'mount disk read-only', detail: 'inspect storage.img without allowing writes', group: 'workspace',
    script: 'mount.ps1', arguments: ['-ReadOnly'], disk: 'unmounted', advanced: true,
  }),
  'unmount-disk': command({
    label: 'unmount disk', detail: 'sync and safely detach the T1OS filesystem', group: 'workspace',
    script: 'unmount.ps1', disk: 'mounted',
  }),
  'create-user': command({
    label: 'create disk user', detail: 'create or replace the active master user', group: 'workspace',
    script: 'create disk user.ps1', disk: 'mounted', input: 'create-user',
  }),
  'change-user': command({
    label: 'change disk user', detail: 'change the active username, password, or both', group: 'workspace',
    script: 'change disk user.ps1', disk: 'mounted', input: 'change-user',
  }),
  'remove-user': command({
    label: 'remove disk user', detail: 'remove the active credentials and permanently delete its private home', group: 'workspace',
    script: 'remove disk user.ps1', disk: 'mounted', input: 'remove-user',
  }),
  'create-usb-user': command({
    label: 'create usb user', detail: 'create or replace the active master user on the validated T1OS USB', group: 'workspace',
    script: 'create disk user.ps1', arguments: ['-UsbDrive'], input: 'create-user',
  }),
  'change-usb-user': command({
    label: 'change usb user', detail: 'change the active username, password, or both on the validated T1OS USB', group: 'workspace',
    script: 'change disk user.ps1', arguments: ['-UsbDrive'], input: 'change-user',
  }),
  'remove-usb-user': command({
    label: 'remove usb user', detail: 'remove active credentials and permanently delete the private home on the validated T1OS USB', group: 'workspace',
    script: 'remove disk user.ps1', arguments: ['-UsbDrive'], input: 'remove-user',
  }),
  'toggle-debug': command({
    label: 'toggle debug mode', detail: 'switch all recognised T1OS debug flags together', group: 'workspace',
    script: 'toggle debug mode.ps1', disk: 'mounted',
  }),
  'toggle-usb-debug': command({
    label: 'toggle usb debug mode', detail: 'switch all recognised T1OS debug flags on the validated T1OS USB', group: 'workspace',
    script: 'toggle debug mode.ps1', arguments: ['-UsbDrive'],
  }),
  'create-disk': command({
    label: 'create new disk', detail: 'create a blank ext4 image matching storage.img', group: 'workspace',
    script: 'create new disk.ps1', disk: 'unmounted',
  }),
  'clean-disk': command({
    label: 'repair disk', detail: 'run guarded e2fsck repair without creating lost+found', group: 'workspace',
    script: 'clean disk.ps1', disk: 'unmounted',
    confirm: 'repair storage.img with the guarded e2fsck workflow?',
  }),
  'backup-disk': command({
    label: 'backup disk', detail: 'copy storage.img using the current version', group: 'workspace',
    script: 'backup_disk.ps1', disk: 'unmounted',
  }),
  'backup-source': command({
    label: 'backup source', detail: 'archive the source tree using the current version', group: 'workspace',
    script: 'backup_source_code.ps1',
  }),

  'push-to-disk': command({
    label: 'sync storage image', detail: 'checksum-sync every managed release tree to storage.img', group: 'production',
    script: 'push to disk.ps1', disk: 'unmounted', recordsPush: true,
  }),
  'push-to-disk-fast': command({
    label: 'fast sync storage image', detail: 'sync only source roots changed since the last verified image update', group: 'production',
    script: 'push to disk.ps1', arguments: ['-Fast'], disk: 'unmounted', recordsPush: true, advanced: true,
  }),
  'push-to-drive': command({
    label: 'sync t1os usb drive', detail: 'checksum-sync managed release trees to the validated USB filesystem', group: 'production',
    script: 'push to disk.ps1', arguments: ['-UsbDrive'], recordsPush: true,
  }),
  'validate-drive-target': command({
    label: 'validate t1os usb target', detail: 'identify and verify the connected update target without writing', group: 'production',
    script: 'push to disk.ps1', arguments: ['-UsbDrive', '-ValidateTargetOnly'], advanced: true,
  }),
  'prepare-prod': command({
    label: 'prepare production disk', detail: 'remove development/user state and verify production defaults', group: 'production',
    script: 'prepare prod build.ps1', disk: 'known',
    confirm: 'prepare storage.img for production? user data, logs, caches, and development state will be removed.',
  }),
  'create-iso': command({
    label: 'create boot iso', detail: 'build the current GRUB boot ISO from release artifacts', group: 'production',
    script: 'create iso.ps1',
  }),
  'update-usb': command({
    label: 'update installed t1os usb', detail: 'apply the normal validated incremental runtime update', group: 'production',
    script: 'update t1os usb.ps1',
  }),
  'update-usb-with-boot': command({
    label: 'update usb including boot', detail: 'update runtimes plus kernel, initramfs, EFI files, and modules', group: 'production',
    script: 'update t1os usb.ps1', arguments: ['-IncludeBoot'],
    confirm: 'update the connected T1OS USB including its boot payload?', advanced: true,
  }),
  'update-usb-full': command({
    label: 'full usb update', detail: 'force the complete managed and boot update workflow', group: 'production',
    script: 'update t1os usb.ps1', arguments: ['-Full', '-IncludeBoot'],
    confirm: 'run the full update against the validated connected T1OS USB?', advanced: true,
  }),
  'prepare-usb-maintenance': command({
    label: 'prepare usb maintenance access', detail: 'perform the one-time managed-Python Windows ACL migration', group: 'production',
    script: 'update t1os usb.ps1', arguments: ['-Prepare'],
    confirm: 'prepare maintenance access on the validated T1OS USB?', advanced: true,
  }),

  'build-image-catalogue': command({
    label: 'build image catalogue', detail: 'rebuild the managed image runtime catalogue', group: 'runtimes',
    script: 'build image catalogue.ps1',
  }),
  'build-graphics-vm': command({
    label: 'build vm graphics runtime', detail: 'build the VirtualBox/VMware graphics userspace', group: 'runtimes',
    script: 'build graphics runtime.ps1', arguments: ['-Profile', 'vm'],
  }),
  'build-graphics-hardware': command({
    label: 'build hardware graphics runtime', detail: 'build Intel, AMD, NVIDIA, and VM graphics userspace', group: 'runtimes',
    script: 'build graphics runtime.ps1', arguments: ['-Profile', 'hardware', '-EnableNvidia'],
  }),
  'build-audio-release': command({
    label: 'build audio runtime', detail: 'build the release audio and media service payload', group: 'runtimes',
    script: 'build audio runtime.ps1',
  }),
  'build-audio-development': command({
    label: 'build development audio', detail: 'build audio/media with development diagnostics', group: 'runtimes',
    script: 'build audio runtime.ps1', arguments: ['-Development'], advanced: true,
  }),
  'build-network-runtime': command({
    label: 'build network runtime', detail: 'build the hardware networking payload', group: 'runtimes',
    script: 'build network runtime.ps1',
  }),
  'build-driver-runtime': command({
    label: 'build driver runtime', detail: 'build the T1OS driver module loader', group: 'runtimes',
    script: 'build driver runtime.ps1',
  }),
  'build-virtualbox-runtime': command({
    label: 'build virtualbox runtime', detail: 'build guest service, clipboard, and test-agent payloads', group: 'runtimes',
    script: 'build virtualbox runtime.ps1',
  }),
  'build-chromium-release': command({
    label: 'build chromium runtime', detail: 'prepare the release Chromium source/runtime adapter', group: 'runtimes',
    script: 'build chromium runtime.ps1', arguments: ['-Profile', 'release'],
  }),
  'build-chromium-development': command({
    label: 'build development chromium', detail: 'prepare Chromium with development diagnostics', group: 'runtimes',
    script: 'build chromium runtime.ps1', arguments: ['-Development'], advanced: true,
  }),
  'build-roothealth': command({
    label: 'build roothealth', detail: 'build the read-only checker and qualified repair engine', group: 'runtimes',
    script: 'build roothealth.ps1',
  }),
  'build-vm-kernel': command({
    label: 'build vm graphics kernel', detail: 'build the current VMSVGA-capable VirtualBox kernel', group: 'runtimes',
    script: 'build graphics kernel.ps1', advanced: true,
  }),

  'verify-python-runtime': command({
    label: 'verify production python', detail: 'verify the canonical Python 3.14 production release without mutation', group: 'python',
    script: 'build python runtime.ps1',
  }),
  'rebuild-python-runtime': command({
    label: 'rebuild and promote python', detail: 'source-build, package, verify, and promote Python 3.14.7', group: 'python',
    script: 'build python runtime.ps1', arguments: ['-Rebuild'],
    confirm: 'rebuild Python 3.14.7 from source and promote it as the production runtime?',
  }),
  'stage-python-candidate': command({
    label: 'package python candidate', detail: 'verify/package the existing candidate without promotion', group: 'python',
    script: 'build python runtime.ps1', arguments: ['-StageOnly'], advanced: true,
  }),
  'promote-python-candidate': command({
    label: 'promote python candidate', detail: 'promote an already-built and verified candidate', group: 'python',
    script: 'build python runtime.ps1', arguments: ['-Promote'],
    confirm: 'promote the existing verified Python candidate into the production source trees?', advanced: true,
  }),
  'test-python-runtime': command({
    label: 'test python runtime', detail: 'validate production Python, packages, entry points, and deployment', group: 'python',
    script: 'test python runtime.ps1',
  }),
  'audit-python-provenance': command({
    label: 'audit python provenance', detail: 'verify locked sources, hashes, manifests, and release evidence', group: 'python',
    script: 'audit python provenance.ps1',
  }),
  'diagnose-python-source': command({
    label: 'diagnose python source build', detail: 'run the isolated source-build diagnostic pipeline', group: 'python',
    script: 'build python source diagnostic.ps1', advanced: true,
  }),
  'build-python-candidate': command({
    label: 'build python candidate only', detail: 'construct the pinned Python 3.14.7 candidate', group: 'python',
    script: 'build python 3.14 candidate.ps1', advanced: true,
  }),
  'push-python-candidate': command({
    label: 'push python candidate to storage', detail: 'deploy the candidate to storage.img for isolated evaluation', group: 'python',
    script: 'push python 3.14 candidate to storage.ps1', disk: 'unmounted', advanced: true,
  }),

  'build-run-vbox': command({
    label: 'build and run virtualbox', detail: 'refresh media, configure the VM, validate it, and launch', group: 'virtual machines',
    script: 'build and run vbox.ps1', disk: 'unmounted',
  }),
  'build-vbox': command({
    label: 'build virtualbox vm', detail: 'refresh and validate the VM without launching it', group: 'virtual machines',
    script: 'build and run vbox.ps1', arguments: ['-BuildOnly'], disk: 'unmounted',
  }),
  'run-vbox': command({
    label: 'run virtualbox vm', detail: 'validate and launch the existing VirtualBox VM', group: 'virtual machines',
    script: 'run vbox.ps1',
  }),
  'validate-vbox': command({
    label: 'validate virtualbox vm', detail: 'check the existing VM and media without launching', group: 'virtual machines',
    script: 'run vbox.ps1', arguments: ['-ValidateOnly'], advanced: true,
  }),
  'convert-vbox': command({
    label: 'convert virtualbox disk', detail: 'regenerate the VDI from a checked storage image', group: 'virtual machines',
    script: 'convert vbox.ps1', disk: 'unmounted', advanced: true,
  }),
  'build-run-vmware': command({
    label: 'build and run vmware', detail: 'refresh media, configure the VM, validate it, and launch', group: 'virtual machines',
    script: 'build and run vmware.ps1', disk: 'unmounted',
  }),
  'build-vmware': command({
    label: 'build vmware vm', detail: 'refresh and validate the VM without launching it', group: 'virtual machines',
    script: 'build and run vmware.ps1', arguments: ['-BuildOnly'], disk: 'unmounted',
  }),
  'run-vmware': command({
    label: 'run vmware vm', detail: 'validate and launch the existing VMware VM', group: 'virtual machines',
    script: 'run vmware.ps1',
  }),
  'validate-vmware': command({
    label: 'validate vmware vm', detail: 'check the existing VM and media without launching', group: 'virtual machines',
    script: 'run vmware.ps1', arguments: ['-ValidateOnly'], advanced: true,
  }),
  'convert-vmware': command({
    label: 'convert vmware disk', detail: 'regenerate the VMDK from a checked storage image', group: 'virtual machines',
    script: 'convert vmware.ps1', disk: 'unmounted', advanced: true,
  }),
  'test-vm-setup': command({
    label: 'validate vm setup', detail: 'check installed hypervisors, VM configuration, and generated media', group: 'virtual machines',
    script: 'test vm setup.ps1',
  }),
  'prepare-vm-test': command({
    label: 'prepare disposable vm tests', detail: 'refresh the restricted VirtualBox test template', group: 'virtual machines',
    script: 'prepare vm test vbox.ps1', advanced: true,
  }),
  'test-vm-smoke': command({
    label: 'vm smoke suite', detail: 'boot one disposable clone and run core structured checks', group: 'virtual machines',
    script: 'test t1os vm.ps1', arguments: ['-Suite', 'Smoke'],
  }),
  'test-vm-brick': command({
    label: 'vm brick suite', detail: 'run the normal fast Brick development gate', group: 'virtual machines',
    script: 'test t1os vm.ps1', arguments: ['-Suite', 'Brick'],
  }),
  'test-vm-gui': command({
    label: 'vm gui suite', detail: 'exercise account, desktop, Brick, input, and screenshot transitions', group: 'virtual machines',
    script: 'test t1os vm.ps1', arguments: ['-Suite', 'Gui'],
  }),
  'test-vm-features': command({
    label: 'vm feature suite', detail: 'exercise the structured runtime feature diagnostics', group: 'virtual machines',
    script: 'test t1os vm.ps1', arguments: ['-Suite', 'Features'], advanced: true,
  }),
  'test-vm-full': command({
    label: 'full vm suite', detail: 'combine structured diagnostics with the complete GUI workflow', group: 'virtual machines',
    script: 'test t1os vm.ps1', arguments: ['-Suite', 'Full'],
    confirm: 'run the complete disposable VirtualBox VM test suite?',
  }),
  'monitor-vm-full': command({
    label: 'monitored full vm suite', detail: 'run the full suite with progress/evidence monitoring', group: 'virtual machines',
    script: 'run monitored vm test.ps1', arguments: ['-Suite', 'Full'], advanced: true,
  }),
  'test-release-vbox': command({
    label: 'virtualbox release smoke boot', detail: 'boot a disposable full clone without changing the release VDI', group: 'virtual machines',
    script: 'test release vbox.ps1',
  }),
  'test-release-vmware': command({
    label: 'vmware release smoke boot', detail: 'boot a disposable full clone without changing the release VMDK', group: 'virtual machines',
    script: 'test release vmware.ps1',
  }),
  'extract-vbox-logs': command({
    label: 'extract virtualbox logs', detail: 'collect guest logs and evidence from the current VM disk', group: 'virtual machines',
    script: 'extract vbox logs.ps1',
  }),
  'test-graphics-vbox': command({
    label: 'test virtualbox graphics', detail: 'exercise the default accelerated presentation path', group: 'virtual machines',
    script: 'test graphics vbox.ps1', advanced: true,
  }),
  'test-graphics-matrix': command({
    label: 'test graphics mode matrix', detail: 'compare hardware, no-3D, and CPU presentation evidence', group: 'virtual machines',
    script: 'test graphics vbox.ps1', arguments: ['-Matrix'], advanced: true,
  }),
  'test-video-vbox': command({
    label: 'test virtualbox video', detail: 'measure the end-to-end decode and presentation pipeline', group: 'virtual machines',
    script: 'test video vbox.ps1', advanced: true,
  }),
  'test-vbox-resize': command({
    label: 'test virtualbox resize', detail: 'exercise the standard dynamic display modes', group: 'virtual machines',
    script: 'test virtualbox resize.ps1', advanced: true,
  }),

  'install-hardware-deps': command({
    label: 'install hardware tools', detail: 'install pinned WSL build, UEFI, QEMU, signing, and image tools', group: 'hardware usb',
    script: 'install hardware build dependencies.ps1',
    confirm: 'install or update the pinned hardware build dependencies in WSL?',
  }),
  'plan-hardware-usb': command({
    label: 'plan complete usb build', detail: 'print the dependency-ordered hardware workflow without running it', group: 'hardware usb',
    script: 'build hardware usb.ps1', arguments: ['-PlanOnly'],
  }),
  'build-hardware-usb': command({
    label: 'build complete usb', detail: 'build, audit, assemble, validate, bundle, and QEMU-boot the release', group: 'hardware usb',
    script: 'build hardware usb.ps1', disk: 'unmounted', recordsPush: true,
    confirm: 'run the complete hardware USB release build? this is a long, multi-stage operation.',
  }),
  'build-hardware-no-qemu': command({
    label: 'build usb without qemu', detail: 'run the complete workflow but skip the final boot test', group: 'hardware usb',
    script: 'build hardware usb.ps1', arguments: ['-SkipQemu'], disk: 'unmounted', recordsPush: true, advanced: true,
    confirm: 'build the complete hardware USB release and skip only the final QEMU boot?',
  }),
  'create-hardware-image': command({
    label: 'rebuild usb image and bundle', detail: 'prepare production storage, assemble 16 GiB image, validate, and bundle', group: 'hardware usb',
    script: 'build hardware usb.ps1', arguments: ['-ArtifactsOnly'], disk: 'unmounted',
    confirm: 'rebuild the production USB image and capacity-independent bundle?',
  }),
  'stage-hardware-firmware': command({
    label: 'stage hardware firmware', detail: 'stage the complete pinned firmware inventory', group: 'hardware usb',
    script: 'stage hardware firmware.ps1', advanced: true,
  }),
  'build-hardware-kernel': command({
    label: 'build hardware kernel', detail: 'build the physical-hardware kernel and modules', group: 'hardware usb',
    script: 'build hardware kernel.ps1', advanced: true,
  }),
  'build-hardware-initramfs': command({
    label: 'build hardware initramfs', detail: 'assemble the hardware boot and recovery initramfs', group: 'hardware usb',
    script: 'build hardware initramfs.ps1', advanced: true,
  }),
  'configure-hardware-wireless': command({
    label: 'configure image wi-fi', detail: 'set a distributable open-network SSID for hardware images', group: 'hardware usb',
    script: 'configure hardware wireless.ps1', input: 'wireless', advanced: true,
  }),
  'push-hardware-kernel-usb': command({
    label: 'update usb boot payload', detail: 'push kernel, initramfs, EFI files, and modules to a validated USB', group: 'hardware usb',
    script: 'push hardware kernel to usb.ps1', confirm: 'update the boot payload on the validated T1OS USB?', advanced: true,
  }),
  'push-python-usb': command({
    label: 'update usb managed python', detail: 'push only the verified managed-Python payload', group: 'hardware usb',
    script: 'push managed python to usb.ps1', advanced: true,
  }),
  'push-media-usb': command({
    label: 'update usb media runtime', detail: 'push only audio, video, Chromium, and media policy payloads', group: 'hardware usb',
    script: 'push media runtime to usb.ps1', advanced: true,
  }),
  'push-chromium-usb': command({
    label: 'update usb chromium presentation', detail: 'push the focused Chromium/graphics presentation payload', group: 'hardware usb',
    script: 'push chromium presentation to usb.ps1', advanced: true,
  }),
  'flash-hardware-usb': command({
    label: 'flash usb', detail: 'select an eligible disk, erase it, write the image, and verify every byte', group: 'hardware usb',
    script: 'flash hardware usb.ps1', input: 'flash-usb',
  }),
  'list-usb-targets': command({
    label: 'list safe usb targets', detail: 'internal JSON target discovery used by the flash dialog', group: 'hardware usb',
    script: 'flash hardware usb.ps1', arguments: ['-ListTargets'], advanced: true,
  }),

  'audit-runtime-paths': command({
    label: 'audit deployed runtime paths', detail: 'audit source and storage.img path contracts', group: 'validation',
    script: 'audit t1os runtime paths.ps1', disk: 'unmounted',
  }),
  'audit-source-runtime-paths': command({
    label: 'audit source runtime paths', detail: 'audit source contracts without inspecting storage.img', group: 'validation',
    script: 'audit t1os runtime paths.ps1', arguments: ['-SkipStorageImage'], advanced: true,
  }),
  'audit-hardware-usb': command({
    label: 'audit installed hardware usb', detail: 'inspect the installed boot/runtime contract on the USB filesystem', group: 'validation',
    script: 'audit hardware usb boot.ps1', advanced: true,
  }),
  'validate-hardware-compatibility': command({
    label: 'validate desktop compatibility', detail: 'prove module, firmware, GPU, microcode, and library closure', group: 'validation',
    script: 'validate hardware compatibility.ps1',
  }),
  'test-hardware-build': command({
    label: 'validate hardware artifacts', detail: 'run the complete hardware build contract suite', group: 'validation',
    script: 'test hardware build.ps1',
  }),
  'test-hardware-build-image': command({
    label: 'validate hardware artifacts + image', detail: 'include the generated USB image in hardware contract checks', group: 'validation',
    script: 'test hardware build.ps1', arguments: ['-IncludeUsbImage'], advanced: true,
  }),
  'validate-hardware-image': command({
    label: 'validate usb image', detail: 'verify partitioning, filesystems, manifests, boot, and production policy', group: 'validation',
    script: 'validate hardware usb image.ps1',
  }),
  'test-hardware-bundle': command({
    label: 'validate usb bundle', detail: 'materialise and verify the bundle at multiple target capacities', group: 'validation',
    script: 'test hardware usb bundle.ps1',
  }),
  'test-hardware-qemu': command({
    label: 'boot-test usb in qemu', detail: 'validate then UEFI/xHCI boot the physical-hardware image', group: 'validation',
    script: 'test hardware usb qemu.ps1',
  }),
  'test-video-compatibility': command({
    label: 'validate video compatibility', detail: 'verify hardware-wide decode routing and capabilities', group: 'validation',
    script: 'test video compatibility.ps1',
  }),
  'test-roothealth': command({
    label: 'test roothealth', detail: 'exercise the checker against corruption and recovery fixtures', group: 'validation',
    script: 'test roothealth.ps1',
  }),
  'test-roothealth-repair': command({
    label: 'test roothealth repair', detail: 'qualify repair, refusal, replay, and power-cut behaviour', group: 'validation',
    script: 'test roothealth repair.ps1', advanced: true,
  }),
  'test-chromium-runtime': command({
    label: 'test chromium runtime', detail: 'validate the Chromium adapter, sandbox, media, fonts, and XWM', group: 'validation',
    script: 'test chromium runtime.ps1', disk: 'unmounted',
  }),
  'test-chromium-fonts': command({
    label: 'test chromium fonts', detail: 'validate font discovery and rendering contracts', group: 'validation',
    script: 'test chromium fonts.ps1', advanced: true,
  }),
  'test-chromium-xwm': command({
    label: 'test chromium xwm', detail: 'validate X11 window-management adapter behaviour', group: 'validation',
    script: 'test chromium xwm.ps1', advanced: true,
  }),
  'test-angel-recovery': command({
    label: 'test angel recovery', detail: 'exercise boot recovery and fatal-screen contracts', group: 'validation',
    script: 'test angel recovery.ps1', advanced: true,
  }),
  'validate-profiled-python': command({
    label: 'validate python entry points', detail: 'verify every profiled Python launcher contract', group: 'validation',
    script: 'validate profiled python entrypoints.ps1', advanced: true,
  }),

  'test': command({
    label: 'qemu runtime test', detail: 'run the default content-addressed QEMU runtime gate', group: 'tests',
    script: 'test.ps1', disk: 'unmounted',
  }),
  'test-opengl': command({
    label: 'qemu opengl test', detail: 'run the default runtime gate with OpenGL enabled', group: 'tests',
    script: 'test.ps1', arguments: ['-OpenGL'], disk: 'unmounted',
  }),
  'test-audio': command({
    label: 'audio and media tests', detail: 'run the content-addressed audio/media runtime cases', group: 'tests',
    script: 'test.ps1', arguments: ['-Audio'],
  }),
  'test-image': command({
    label: 'image runtime tests', detail: 'run the managed image catalogue/runtime cases', group: 'tests',
    script: 'test.ps1', arguments: ['-Image'],
  }),
  'test-kms': command({
    label: 'kms presentation tests', detail: 'exercise direct scanout and KMS presentation contracts', group: 'tests',
    script: 'test.ps1', arguments: ['-GraphicsKms'], advanced: true,
  }),
  'test-brick-directives': command({
    label: 'brick directive tests', detail: 'run the fast host-side structured Brick diagnostic', group: 'tests',
    script: 'test.ps1', arguments: ['-BrickDirectives'],
  }),
  'test-graphics-compositor': command({
    label: 'graphics compositor tests', detail: 'exercise compositor rendering and lifecycle behaviour', group: 'tests',
    script: 'test.ps1', arguments: ['-GraphicsCompositor'], advanced: true,
  }),
  'test-graphics-player': command({
    label: 'player graphics tests', detail: 'exercise Player rendering through the graphics stack', group: 'tests',
    script: 'test.ps1', arguments: ['-GraphicsPlayer'], advanced: true,
  }),
  'test-graphics-startup': command({
    label: 'startup graphics tests', detail: 'exercise startup and desktop presentation lifecycle', group: 'tests',
    script: 'test.ps1', arguments: ['-GraphicsStartup'], advanced: true,
  }),
  'test-graphics-lockscreen': command({
    label: 'lock-screen graphics tests', detail: 'exercise lock-screen rendering and transitions', group: 'tests',
    script: 'test.ps1', arguments: ['-GraphicsLockscreen'], advanced: true,
  }),
  'test-graphics-boot': command({
    label: 'boot graphics tests', detail: 'exercise boot-animation presentation and handoff', group: 'tests',
    script: 'test.ps1', arguments: ['-GraphicsBoot'], advanced: true,
  }),
  'test-vbox-clipboard': command({
    label: 'virtualbox clipboard tests', detail: 'exercise the guest clipboard service contract', group: 'tests',
    script: 'test.ps1', arguments: ['-VirtualBoxClipboard'], advanced: true,
  }),
} as const

export type CommandId = keyof typeof commandCatalogue

export const commandGroups: readonly CommandGroup[] = [
  'workspace',
  'production',
  'runtimes',
  'python',
  'virtual machines',
  'hardware usb',
  'validation',
  'tests',
]
