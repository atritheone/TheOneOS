# T1OS Python runtime

The canonical production runtime is **CPython 3.14.7**, release
`3.14.7-t1os.66`, ABI `cp314`.

The stable T1OS interpreter path is:

```text
/the one/software/python/bin/python
```

`bin/python3.14` is the versioned entrypoint. `bin/python3.13` is retained only
as a temporary compatibility entrypoint and executes the same locked CPython
3.14.7 binary. Current T1OS boot and userspace code must use `bin/python`.

## Canonical release

The installed source payload is under `source/software/python`; its native
catalogue is under `source/catalogue/python`, and its CPython-ABI image packages
are under `source/catalogue/image`.

The runtime manifest is `source/software/python/manifest.json`. The immutable
production lock is `source/python/locks/release.json`. The older
`release-zero.json` remains only as archived Python 3.13 provenance and is not a
current build input.

The 3.14 source build first produces a separately verified candidate. Promotion
then converts that exact candidate into the canonical Python manifest. The
production identity covers only `source/software/python` and
`source/catalogue/python`; kernel, initramfs, LSM, build-software, boot,
deployment, image-catalogue, and VirtualBox changes do not alter the Python
release and must never trigger a Python rebuild or promotion.

Boot-time executable modes and protected inventories are a separate mutable OS
policy. `scripts/build boot protected roots.py` derives that policy during an
initramfs build or deployment, and the hardware workflows attest it alongside
the unchanged Python release. Legacy external-root fields still present in the
3.14.7-t1os.66 manifest are retained as historical release metadata only; they
are not part of production Python verification.

Verify the existing production release without building or promoting anything:

```powershell
pwsh -File 'scripts/build python runtime.ps1'
```

Package and promote an already-built Python candidate explicitly:

```powershell
pwsh -File 'scripts/build python runtime.ps1' -Promote
```

Rebuild CPython before packaging and promotion (also explicit):

```powershell
pwsh -File 'scripts/build python runtime.ps1' -Rebuild
```

Package without promotion:

```powershell
pwsh -File 'scripts/build python runtime.ps1' -StageOnly
```

Verify the complete canonical release:

```powershell
pwsh -File 'scripts/test python runtime.ps1'
```

The default command is a read-only verification gate, so invoking it from a
larger build or deployment can never reconstruct Python. The explicit promotion
command is idempotent for an unchanged release. A new release
identifier and lock are required only when the Python software payload or its
native Python catalogue changes. OS policy and deployment changes are verified
and released independently.

## Module management

T1OS starts its system Python package service from
`/the one/build/python/python.py`. Brick and Settings share its newline-delimited
JSON protocol over `/.ephemeral/python/manager.sock`, so both always show the
same installed state.

Packages are installed where a normal system Python user expects them:

```text
/the one/software/python/lib/python3.14/site-packages
```

Package commands are installed in `/the one/software/python/bin`. There is no
separate generation directory and `sitecustomize` does not add a private module
path. A newly started program imports an added package through Python's normal
system `site-packages` processing.

Package management commands are deliberately provided only as Brick Python
directives:

```text
install python module requests
install python module numpy version 2.3.4
install python wheel /path/to/package.whl
remove python module requests
list python modules
show python module numpy
check python modules
clear python cache
```

T1OS does not install `pip`, `pip3`, or a `python -m pip` module. Commands added
by installed wheels use one small locked native launcher, because Linux
shebangs cannot represent the space in `/the one`; the launcher delegates to
the consolidated `python.py`, which selects the package's recorded entry point. A private,
hash-locked `pip-26.1.2` wheel remains inaccessible to users and is used by
`/the one/build/python/python.py` only to resolve dependencies and unpack wheels
inside a transaction workspace.

Settings lists both built-in and added packages. An Architect can type a
package name, review the change, and choose **add**. Selecting a directly added
package exposes **remove**, **update**, and **pin/unpin**. Dependencies are
shown separately and are removed automatically when no requested package needs
them.

Brick provides the same operations in plain language:

```text
python status
check python
check python modules
python history
list python modules
show python module <name>
find python module <name>
list python updates
install python module <name> [version <version>]
install python wheel <file>
remove python module <name>
update python module <name>
update python modules
pin python module <name>
unpin python module <name>
repair python modules
restore python modules
clear python cache
export python lock <file>
apply python lock <file>
```

Status, inventory, history, search, update checks, and lock export work in
Master. Installing, removing, updating, pinning,
repair, restore, cache changes, and lock application require Architect in both
the frontend and the service. The T1OS LSM is the final runtime write boundary;
Linux permission bits on an offline NTFS USB are not the authorization model.

## Package transaction and native patching

Every change resolves a complete dependency set from compatible binary wheels.
Source distributions are not built on the live operating system. Before any
live file changes, T1OS:

1. verifies each downloaded artifact identity and every wheel `RECORD` hash;
2. rejects links, unsafe paths, executable `.pth` startup hooks, stdlib/core
   collisions, unsupported architectures, and packages exceeding size limits;
3. compiles Python sources as canonical checked-hash bytecode;
4. finds every ELF extension and bundled shared library;
5. validates ELF64 little-endian x86-64 and the T1OS glibc symbol ceiling;
6. moves bundled shared libraries into `/the one/catalogue/python` under their
   wheel-provided SONAMEs, rejecting different payloads that claim the same name;
7. replaces libraries merged into modern glibc in place, then performs one
   verified RUNPATH rewrite per ELF so its dynamic table remains loadable;
8. proves the final native dependency closure against the Python catalogue and
   imports every native package with the staged catalogue before commit;
9. recreates package metadata and `RECORD`, then commits only owned files.

If a library is loaded by a hard-coded path rather than ELF dependency edges,
or a wheel contains a native executable needing its own interpreter rewrite,
the package is refused with `native_recipe_required` instead of being installed
partly. A future compatibility recipe can then describe that package explicitly.

The commit journal is fsynced before its first rename. Old owned files are moved
to transaction backup, new files are installed, and `state.json` becomes live
last. Recovery handles crashes on either side of each rename. `previous.json`
supports one-step restore, while `.t1pip/pylock.toml` records exact artifact
URLs and SHA-256 hashes for repair and export. User-modified managed files are
never silently overwritten.

Managed-Python pushes to USB and `storage.img` preserve `.t1pip` state and only
the package and catalogue files whose size and SHA-256 match that state. Base
release files remain governed by the immutable Python manifest. A collision
between an installed package and a new system release aborts the update rather
than choosing one silently.

## Recovery contract

Angel runs independently of Python from the hardware initramfs. The recovery
partition contains the canonical Python manifest plus the independently built
boot protected-root inventory used by the normal root.

- Python repair restores the Python software and native catalogue. ABI-bound
  image packages are handled by the image-catalogue deployment policy.
- Build reset restores the protected build and boot software.
- OS reset and reinstall restore the complete canonical protected-root set.

Consequently every recovery path converges on CPython 3.14.7 rather than mixing
Python or extension ABIs.
