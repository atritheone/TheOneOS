# The One OS

**The One OS** (T1OS) is an experimental operating system built almost entirely in Python on top of a 64-bit Linux kernel.

The One OS is designed as a self-contained operating system rather than a conventional Linux distribution. It provides its own filesystem, shell, graphics stack, windowing system, system services, applications, and APIs.

## Design

The One OS follows several core principles:

- **Python-first** — the operating system is implemented primarily in Python.
- **Custom filesystem** — The One OS does not expose or depend on the standard Linux filesystem hierarchy.
- **No Linux userspace assumptions** — software must operate entirely within The One OS filesystem and environment.
- **No symlinks** — the filesystem is designed without symbolic links.
- **Self-contained software** — external software must be adapted or patched where necessary to work within The One OS.
- **Custom interfaces** — system components communicate through The One OS services and APIs rather than conventional Linux userspace infrastructure.

## Components

Some of the core The One OS components include:

- **brick** — the command shell.
- **graphics** — the operating system's graphics and rendering API.
- **windowserver** — manages graphical windows, input, focus, and display composition.
- **operations** — manages running processes and system operations.
- **expanse** — graphical file management and system navigation.
- **exchange** — inter-component data exchange.
- **architect** — filesystem and system structure services.

## Filesystem

The One OS uses its own filesystem layout and does not provide applications with access to conventional Linux directories such as `/usr`, `/lib`, `/proc`, `/sys`, or `/dev`.

The Linux kernel provides the low-level foundation, while The One OS defines the environment presented to the operating system and its software.

## Status

The One OS is under active development. Interfaces, APIs, filesystem structures, and internal components may change as the operating system develops.

## Testing

Test, validation, and audit scripts use content-addressed incremental execution.
Existing commands run only cases whose implementation, inputs, parameters,
artifacts, or relevant environment have changed. See
[scripts/INCREMENTAL TESTING.md](scripts/INCREMENTAL%20TESTING.md).

## Goal

The goal of The One OS is to build a complete, coherent and independent operating environment in Python while retaining the hardware support and low-level capabilities of the Linux kernel.
