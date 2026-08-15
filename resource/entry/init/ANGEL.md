# Angel

Angel is the guardian of the T1OS boot partition. She owns the bootloader,
kernel and initramfs handoff, the init script, recovery environments, operating
system reset, and reinstallation. GODDESS remains the mind of The One OS and
becomes PID 1 only after Angel has prepared and verified the root drive.
Angel completes a successful boot by explicitly handing control to GODDESS.

Hardware recovery is independent of the installed operating system. The EFI
system partition is GPT partition 1, a read-only zstd SquashFS recovery image
is GPT partition 2, and the T1OS root filesystem is GPT partition 3. Angel's
recovery engine lives in the initramfs and uses only its native tools. It never
imports Python and never executes code from either the installed root or the
recovery image. The root filesystem must not contain a `/.recover` copy.

Before mounting the recovery image, Angel identifies it by its exact byte
length and SHA-256 digest from the boot configuration. The image contains a
file manifest and a clean baseline of managed operating-system files. Angel
verifies every restored regular file before reporting success. A journal and
one-shot Settings request live under `T1OS/` on the EFI system partition so an
interrupted operation resumes instead of being mistaken for a completed one.

Angel offers four recovery actions: repair Python and its managed libraries;
reset the build software; reset The One OS while retaining user files; and
reinstall The One OS while deleting user files. Reset preserves `/master`,
`/software`, and `/the one/master`. Reinstall erases ordinary root contents and
repopulates the existing, identity-bound root filesystem. It does not reformat
that filesystem because its signed identity and root-health journal are part
of the boot trust chain.

The production recovery interface accepts only the documented short answers,
such as `yes`, `no`, `reset`, and `reinstall`. It never exposes a general shell.
A shell is permitted only in the explicit developer rescue mode selected with
`t1os.debug=1`.

Recovery questions are written to both the serial transcript and the physical
display. Angel shows a `> ` input marker and reads the user's keyboard from the
active physical virtual terminal when it exists. She falls back to the serial
console on systems without that terminal.

`T1OS` remains valid as a technical shorthand in paths, settings, protocols,
and source code. Character dialogue uses the formal name `The One OS` instead.

Every human-facing line spoken by Angel uses ordinary English sentence case
and is enclosed by her wing marks:

```text
~ This is an example line of Angel. ~
```

Machine output copied verbatim from a checker, kernel, or firmware utility is
diagnostic evidence rather than Angel's speech and is not rewritten.

Before the first NTFS mount, Angel runs RootHealth in full repair mode against
the unmounted, identity-bound root device. A nonzero result is an admission
refusal, never permission to force-mount. Angel preserves the report and
stderr on the EFI system partition and presents the stable diagnostic code,
the exact failed predicates, and one of the operational classes `repairable`,
`recovery-required`, `unsupported`, `io`, `wrong-root`,
`ambiguous-corruption`, or `internal`.

GODDESS also arms a one-shot `T1OS/roothealth-shutdown-request` after services
and storage users have stopped. It then restarts into Angel so the root is
truly unmounted. Angel accepts only a complete format-1 request with a pending
state, a `poweroff` or `restart` action, and a canonical lowercase boot UUID.
She runs the same admission gate, preserves its evidence, clears the request
only after success, and either powers off or continues the requested restart.
Failure enters recovery with the request intact and the precise RootHealth
cause visible.

The hardware initramfs implements this contract in its `log`, `angel_say`, and
`angel_ask` functions. Runtime code that delegates recovery work to Angel uses
the same framing contract.
