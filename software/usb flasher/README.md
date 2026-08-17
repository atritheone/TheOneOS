# The One OS USB Flasher

A minimal Windows flasher for compact The One OS `.t1os` installers. The
portable executable requests administrator access because USB partitioning and
raw partition writes require elevation.

## End-user files

Distribute these two files together:

1. `The One OS USB Flasher Portable.exe`
2. `The One OS <version>.t1os`

When exactly one `.t1os` bundle is beside the executable it is selected automatically.
Otherwise the user can browse to it.

## Safety

- The writer validates the bundle structure and embedded EFI/NTFS SHA-256 values
  before raw disk access, then verifies both payloads from the USB after writing.
- Only non-system USB disks up to 256 GiB are offered.
- The target is resolved again immediately before flashing and its exact identity
  is confirmed again inside the writer.
- The application requires an erase acknowledgement and a separate native
  confirmation dialog.
- The EFI and root partitions are created for the target USB, and the NTFS root
  is expanded to fill its remaining capacity.
- The NTFS root keeps the release label `T1OS <version>` and includes the T1OS
  drive icon used by Windows Explorer.
- After expansion and verification, the writer flushes and dismounts every USB
  volume, then remounts the verified NTFS root with a Windows drive letter so
  the completed T1OS USB is immediately accessible in Windows Explorer.
- Closing the application is blocked while a flash is running, and Windows sleep
  is inhibited until verification finishes.

## Development

```powershell
npm install
npm run typecheck
npm run dev
npm run portable
```
