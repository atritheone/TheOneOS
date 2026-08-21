#!/bin/sh

mount -t devtmpfs devtmpfs /dev
mount -t proc     proc     /proc
mount -t sysfs    sysfs    /sys

# Linux ping sockets permit ICMP echo without granting the desktop shell raw
# packet authority.  Limit that ordinary-user facility to the T1OS user group.
/bin/busybox printf '1000 1000\n' > /proc/sys/net/ipv4/ping_group_range || {
    /bin/busybox echo 'software init could not enable ordinary-user icmp echo' >/dev/console
    exec /bin/busybox sh
}
ping_group_values=$(/bin/busybox cat /proc/sys/net/ipv4/ping_group_range) || {
    /bin/busybox echo 'software init could not read the ordinary-user icmp echo boundary' >/dev/console
    exec /bin/busybox sh
}
set -- $ping_group_values
[ "$#" = 2 ] && [ "$1" = 1000 ] && [ "$2" = 1000 ] || {
    /bin/busybox echo 'software init found the wrong ordinary-user icmp echo boundary' >/dev/console
    exec /bin/busybox sh
}
unset ping_group_values

root=/dev/sda

if [ -b /dev/vda ]; then
    root=/dev/vda
fi

mount "$root" /mnt

/bin/busybox mkdir -p \
    "/mnt/.ephemeral" \
    "/mnt/the one/drivers/nodes" \
    "/mnt/the one/drivers/state" \
    "/mnt/the one/drivers/control" \
    "/mnt/the one/drivers/processes" \
    "/mnt/the one/logs"

# The release image keeps persistent system directories sealed between boots.
# Open only the LSM-governed log tier for the root and desktop service group;
# individual software domains remain confined to their assigned log paths.
/bin/busybox chown 0:1000 "/mnt/the one/logs" || exec /bin/busybox sh
/bin/busybox chmod 0770 "/mnt/the one/logs" || exec /bin/busybox sh
[ "$(/bin/busybox stat -c '%u:%g:%a' "/mnt/the one/logs")" = "0:1000:770" ] || exec /bin/busybox sh

mount -t devtmpfs devtmpfs "/mnt/the one/drivers/nodes" || exec /bin/busybox sh
/bin/busybox mkdir -p "/mnt/the one/drivers/nodes/pts" || exec /bin/busybox sh
mount -t devpts -o newinstance,gid=1000,ptmxmode=0660,mode=0600 devpts "/mnt/the one/drivers/nodes/pts" || exec /bin/busybox sh
/bin/busybox chown 0:1000 "/mnt/the one/drivers/nodes/pts/ptmx" || exec /bin/busybox sh
/bin/busybox chmod 0660 "/mnt/the one/drivers/nodes/pts/ptmx" || exec /bin/busybox sh
mount -t sysfs -o rw sysfs "/mnt/the one/drivers/control" || exec /bin/busybox sh
mount -t sysfs -o ro sysfs "/mnt/the one/drivers/state" || exec /bin/busybox sh
mount -t proc -o ro proc "/mnt/the one/drivers/processes" || exec /bin/busybox sh
mount -t tmpfs -o mode=1777,nosuid,nodev tmpfs "/mnt/.ephemeral" || exec /bin/busybox sh
/bin/busybox mkdir -m 0700 "/mnt/.ephemeral/media" || exec /bin/busybox sh
/bin/busybox chown 1000:1000 "/mnt/.ephemeral/media" || exec /bin/busybox sh
/bin/busybox chmod 0700 "/mnt/.ephemeral/media" || exec /bin/busybox sh
/bin/busybox mkdir -m 0700 "/mnt/.ephemeral/brick" || exec /bin/busybox sh
/bin/busybox chown 1000:1000 "/mnt/.ephemeral/brick" || exec /bin/busybox sh
/bin/busybox chmod 0700 "/mnt/.ephemeral/brick" || exec /bin/busybox sh
/bin/busybox mkdir -m 0711 "/mnt/.ephemeral/expanse" || exec /bin/busybox sh
/bin/busybox chown 1000:1000 "/mnt/.ephemeral/expanse" || exec /bin/busybox sh
/bin/busybox chmod 0711 "/mnt/.ephemeral/expanse" || exec /bin/busybox sh
/bin/busybox mkdir -m 01733 "/mnt/.ephemeral/network" || exec /bin/busybox sh
/bin/busybox chown 0:0 "/mnt/.ephemeral/network" || exec /bin/busybox sh
/bin/busybox chmod 01733 "/mnt/.ephemeral/network" || exec /bin/busybox sh
/bin/busybox mkdir -m 0700 "/mnt/.ephemeral/operations" || exec /bin/busybox sh
/bin/busybox chown 1000:1000 "/mnt/.ephemeral/operations" || exec /bin/busybox sh
/bin/busybox chmod 0700 "/mnt/.ephemeral/operations" || exec /bin/busybox sh
/bin/busybox mkdir -m 02710 "/mnt/.ephemeral/audio" || exec /bin/busybox sh
/bin/busybox chown 0:1000 "/mnt/.ephemeral/audio" || exec /bin/busybox sh
/bin/busybox chmod 02710 "/mnt/.ephemeral/audio" || exec /bin/busybox sh

# Provision mutable state which services cannot create after entering their
# measured domains. This is the software-runtime subset of the hardware init's
# permission preparation; no device, firmware, recovery, or storage logic is
# needed by the VM.
legacy_python_management="/mnt/the one/software/python/.t1pip"
python_management="/mnt/the one/software/python/pip"
[ ! -L "$legacy_python_management" ] || exec /bin/busybox sh
[ ! -L "$python_management" ] || exec /bin/busybox sh
if [ -e "$legacy_python_management" ]; then
    [ -d "$legacy_python_management" ] || exec /bin/busybox sh
    [ ! -e "$python_management" ] || exec /bin/busybox sh
    /bin/busybox mv -- "$legacy_python_management" "$python_management" || exec /bin/busybox sh
fi
[ ! -L "$python_management" ] || exec /bin/busybox sh
/bin/busybox mkdir -p \
    "$python_management/artifacts" \
    "$python_management/transactions" || exec /bin/busybox sh
for python_state_directory in \
    "$python_management" \
    "$python_management/artifacts" \
    "$python_management/transactions"; do
    [ -d "$python_state_directory" ] && [ ! -L "$python_state_directory" ] || exec /bin/busybox sh
    /bin/busybox chown 0:0 "$python_state_directory" || exec /bin/busybox sh
    /bin/busybox chmod 0700 "$python_state_directory" || exec /bin/busybox sh
done

chromium_sandbox="/mnt/the one/software/chromium/program/chrome-sandbox"
if [ -f "$chromium_sandbox" ] && [ ! -L "$chromium_sandbox" ]; then
    /bin/busybox chown 0:0 "$chromium_sandbox" || exec /bin/busybox sh
    /bin/busybox chmod 4755 "$chromium_sandbox" || exec /bin/busybox sh
    [ "$(/bin/busybox stat -c '%u:%g:%a:%h' "$chromium_sandbox")" = "0:0:4755:1" ] || exec /bin/busybox sh
fi

# Remove the exact interpreter alias left by older T1OS images. Current kernels
# execute the quoted canonical interpreter path directly.
if [ -L /mnt/t1python ]; then
    [ "$(/bin/busybox readlink /mnt/t1python 2>/dev/null)" = "/the one/software/python/bin/python" ] || exec /bin/busybox sh
	/bin/busybox rm -- /mnt/t1python || exec /bin/busybox sh
elif [ -e /mnt/t1python ]; then
    exec /bin/busybox sh
fi
[ ! -e /mnt/t1python ] && [ ! -L /mnt/t1python ] || exec /bin/busybox sh

export TERM=linux
export TERMINFO="/the one/settings/terminfo"
export PYTHONHASHSEED=0
export PYTHONNOUSERSITE=1
export PYTHONDONTWRITEBYTECODE=1
# The VM root does not use the hardware initramfs RootHealth shutdown gate.
# After GODDESS quiesces and protects storage, hand the selected action directly
# to the virtual firmware so poweroff stops the VM and restart reboots it.
export T1OS_POWER_HANDOFF=direct
# Normal VM boots keep GODDESS dialogue on the serial and persistent log
# streams.  She can still force the local console mirror for fatal recovery.
export T1OS_QUIET=1
unset PYTHONHOME PYTHONPATH

case " $(/bin/busybox cat /proc/cmdline) " in
    *" t1os.graphics=framebuffer "*) export T1OS_GRAPHICS=framebuffer ;;
    *" t1os.graphics=cpu "*) export T1OS_GRAPHICS=cpu ;;
esac

# A command-line request alone cannot enable the test agent. The immutable
# test template must also carry the deliberately injected root-owned marker.
case " $(/bin/busybox cat /proc/cmdline) " in
    *" t1os.developer=1 "*)
        if [ -f /mnt/t1os-developer-policy ] &&
                [ "$(/bin/busybox cat /mnt/t1os-developer-policy 2>/dev/null)" = enabled ]; then
            export T1OS_DEVELOPER=1
            export T1OS_ENABLE_VM_TEST_AGENT=1
        fi
        ;;
esac

# Preserve an already-open display descriptor across switch_root.  GODDESS
# uses this descriptor for the KD_TEXT/KD_GRAPHICS ownership hand-off without
# reopening tty0 through the restricted persistent device tree.
if [ -c "/mnt/the one/drivers/nodes/tty0" ]; then
    # Open tty0 through the canonical T1OS devtmpfs mount.  After switch_root
    # the descriptor's path remains /the one/drivers/nodes/tty0, which the LSM
    # grants only to GODDESS.  An fd opened through initramfs /dev/tty0 retains
    # that obsolete path and is correctly rejected after the handoff.
    exec 3<>"/mnt/the one/drivers/nodes/tty0"
    export T1OS_DISPLAY_CONSOLE_FD=3
fi

exec switch_root /mnt \
     "/the one/software/python/bin/python" \
     "/the one/build/GODDESS/GODDESS.py"
