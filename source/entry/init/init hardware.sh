#!/bin/sh

# Angel is the guardian of the T1OS boot partition and recovery environment.
# This initramfs entry point is her first voice before she hands control to
# GODDESS as PID 1. Angel deliberately refuses to guess a root disk by Linux
# device name.

PATH=/bin:/sbin
export PATH

busybox=/bin/busybox
root_spec=
root_fstype=ntfs3
root_mode=rw
root_wait=60
graphics_mode=auto
recovery=0
debug=0
developer=0
developer_request=0
quiet=0
angel_visible=0
root_device=
roothealth_serial=
roothealth_journal_uuid=
roothealth_journal_record=
roothealth_admission_completed=0
roothealth_admission_status=not-run
luks_spec=
luks_name=t1os-root
recovery_spec=
esp_spec=
recovery_sha256=
recovery_bytes=
root_label='The One OS'
ntfs_mount_options=uid=0,gid=0,fmask=0022,dmask=0022,windows_names,acl
protected_inventory=/protected-roots.tsv
profiled_python_inventory=/profiled-python-entrypoints.tsv
angel_log=/run/t1os-angel.log
roothealth_report=/run/roothealth.json
roothealth_stderr=/run/roothealth.stderr
roothealth_boot_evidence=/run/roothealth-boot.env
root_discovery_log=/run/root-discovery.log
roothealth_refusal_code=
roothealth_refusal_class=
roothealth_refusal_summary=
roothealth_refusal_predicates=
angel_prefix='~ '
angel_suffix=' ~'
roothealth_history_limit=5

# The recovery implementation is shipped inside the initramfs. It uses only
# BusyBox and the small native tools copied beside this init process.
# shellcheck source=/dev/null
. /angel-recovery

log() {
    # Angel speaks in ordinary sentence case, framed by her wings. Keep the
    # message untouched so names such as The One OS and NTFS retain their identity.
    message=$*
    printf '%s%s%s\n' "$angel_prefix" "$message" "$angel_suffix" >/dev/console

    # The final console= entry is the serial port so automated USB tests retain
    # the complete boot transcript. The physical display is reserved for an
    # actual failure/repair path or the explicitly selected recovery interface.
    if [ "$angel_visible" = 1 ] && [ -c /dev/tty0 ]; then
        printf '%s%s%s\n' "$angel_prefix" "$message" "$angel_suffix" \
            >/dev/tty0 2>/dev/null || true
    fi

    if [ -d /run ]; then
        boot_elapsed=unknown
        IFS=' ' read -r boot_elapsed _ </proc/uptime 2>/dev/null || \
            boot_elapsed=unknown
        printf '[%s] %s%s%s\n' \
            "$boot_elapsed" "$angel_prefix" "$message" "$angel_suffix" \
            >>"$angel_log" 2>/dev/null || true
    fi
}

boot_status() {
    # Successful normal boot remains visually silent. Milestones are retained
    # on serial and in Angel's persistent transcript for later diagnosis.
    log "$*"
}

persist_angel_log_to_root() {
    [ "${angel_root_mounted:-0}" = 1 ] || return 1
    [ "${root_mode:-ro}" = rw ] || return 1
    [ -s "$angel_log" ] || return 1

    logs='/mnt/the one/logs'
    "$busybox" mkdir -p "$logs" 2>/dev/null || return 1
    temporary="$logs/.angel.log.new"
    "$busybox" rm -f "$temporary"
    if "$busybox" cp "$angel_log" "$temporary" &&
            "$busybox" chmod 0444 "$temporary" &&
            "$busybox" mv "$temporary" "$logs/angel.log"; then
        return 0
    fi
    "$busybox" rm -f "$temporary"
    return 1
}

persist_roothealth_boot_history() {
    # RootHealth runs before the root filesystem is trusted or mounted. Keep a
    # bounded history on the EFI partition so a missing UUID, an NTFS refusal,
    # or an interrupted shutdown gate cannot erase the preceding evidence.
    history_mounted_here=0
    # Defined by the sourced Angel recovery engine.
    # shellcheck disable=SC2154
    if ! "$busybox" mountpoint -q "$angel_esp_mount"; then
        angel_mount_esp || return 0
        history_mounted_here=1
    fi

    history_root="$angel_esp_mount/T1OS/diagnostics/roothealth-history"
    history_stage="$history_root/.boot-current.new"
    "$busybox" mkdir -p "$history_root" 2>/dev/null || {
        [ "$history_mounted_here" = 0 ] || \
            angel_unmount_esp 2>/dev/null || true
        return 0
    }
    "$busybox" rm -rf "$history_stage" 2>/dev/null || true
    "$busybox" mkdir -p "$history_stage" 2>/dev/null || {
        [ "$history_mounted_here" = 0 ] || \
            angel_unmount_esp 2>/dev/null || true
        return 0
    }

    roothealth_history_copy() {
        history_source=$1
        history_name=$2
        [ -s "$history_source" ] || return 0
        if "$busybox" cp "$history_source" \
                "$history_stage/$history_name" 2>/dev/null; then
            "$busybox" chmod 0444 "$history_stage/$history_name" \
                2>/dev/null || true
        fi
    }

    roothealth_history_copy "$angel_log" angel.log
    roothealth_history_copy "$roothealth_report" roothealth.json
    roothealth_history_copy "$roothealth_stderr" roothealth.stderr
    roothealth_history_copy "$roothealth_boot_evidence" boot.env
    roothealth_history_copy "$root_discovery_log" root-discovery.log
    "$busybox" dmesg | "$busybox" tail -n 2048 \
        >"$history_stage/dmesg.log" 2>/dev/null || true
    [ -s "$history_stage/dmesg.log" ] || \
        "$busybox" rm -f "$history_stage/dmesg.log" 2>/dev/null || true

    history_boot_id=$(
        "$busybox" cat /proc/sys/kernel/random/boot_id 2>/dev/null || true
    )
    case "$history_boot_id" in
        ????????-????-????-????-????????????) ;;
        *) history_boot_id=unknown ;;
    esac
    history_captured_utc=$(
        "$busybox" date -u '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || \
            printf unknown
    )
    history_refusal_fingerprint=none
    if [ -n "$roothealth_refusal_code" ]; then
        history_refusal_fingerprint=$(printf '%s\n%s\n' \
            "$roothealth_refusal_code" "$roothealth_refusal_predicates" | \
            "$busybox" sha256sum) || history_refusal_fingerprint=none
        history_refusal_fingerprint=${history_refusal_fingerprint%% *}
    fi
    history_failure_kind=none
    case "${angel_failure_reason:-}" in
        *'could not find the root filesystem'*|*'could not find the encrypted root container'*)
            history_failure_kind=root-not-found
            ;;
        *'could not mount'*root*) history_failure_kind=root-mount-failed ;;
        *'not a valid root filesystem'*) history_failure_kind=root-layout-invalid ;;
        *'operating-system files that must be recovered'*) history_failure_kind=managed-integrity ;;
    esac
    {
        printf 'format=1\n'
        printf 'boot_id=%s\n' "$history_boot_id"
        printf 'captured_utc=%s\n' "$history_captured_utc"
        printf 'root_spec=%s\n' "$root_spec"
        printf 'root_device=%s\n' "$root_device"
        printf 'root_fstype=%s\n' "$root_fstype"
        printf 'admission_completed=%s\n' "$roothealth_admission_completed"
        printf 'admission_status=%s\n' "$roothealth_admission_status"
        printf 'refusal_code=%s\n' "$roothealth_refusal_code"
        printf 'refusal_class=%s\n' "$roothealth_refusal_class"
        printf 'refusal_fingerprint=%s\n' "$history_refusal_fingerprint"
        printf 'failure_kind=%s\n' "$history_failure_kind"
    } >"$history_stage/manifest.env" 2>/dev/null || true
    "$busybox" chmod 0444 "$history_stage/manifest.env" 2>/dev/null || true

    newest_boot_id=$(
        "$busybox" awk -F= "\$1 == \"boot_id\" { print \$2; exit }" \
            "$history_root/boot-1/manifest.env" 2>/dev/null || true
    )
    if [ "$newest_boot_id" = "$history_boot_id" ] && \
            [ "$history_boot_id" != unknown ]; then
        # A later failure message from this same boot refreshes its newest slot
        # without consuming a second position in the five-boot ring.
        "$busybox" rm -rf "$history_root/boot-1" 2>/dev/null || true
    else
        history_slot=$roothealth_history_limit
        "$busybox" rm -rf "$history_root/boot-$history_slot" \
            2>/dev/null || true
        while [ "$history_slot" -gt 1 ]; do
            history_previous=$((history_slot - 1))
            [ ! -d "$history_root/boot-$history_previous" ] || \
                "$busybox" mv "$history_root/boot-$history_previous" \
                    "$history_root/boot-$history_slot" 2>/dev/null || true
            history_slot=$history_previous
        done
    fi
    "$busybox" mv "$history_stage" "$history_root/boot-1" \
        2>/dev/null || true
    "$busybox" sync
    if [ "$history_mounted_here" = 1 ]; then
        angel_unmount_esp 2>/dev/null || true
    fi
}

persist_angel_failure_log() {
    # A failure before the normal log handoff cannot rely on the root drive.
    # Preserve the transcript on the EFI system partition when it is available.
    persist_angel_log_to_root 2>/dev/null || true
    persist_roothealth_boot_history
    angel_mount_esp || return 0
    # Defined by the sourced Angel recovery engine after angel_mount_esp.
    # shellcheck disable=SC2154
    diagnostics="$angel_esp_mount/T1OS/diagnostics"
    "$busybox" mkdir -p "$diagnostics" 2>/dev/null || return 0

    persist_diagnostic_file() {
        diagnostic_source=$1
        diagnostic_name=$2
        diagnostic_target="$diagnostics/$diagnostic_name"
        diagnostic_temporary="$diagnostics/.$diagnostic_name.new"
        if [ ! -s "$diagnostic_source" ]; then
            # Never present evidence from an older boot as the current result.
            "$busybox" rm -f "$diagnostic_temporary" \
                "$diagnostic_target" 2>/dev/null || true
            return 0
        fi
        if "$busybox" cp "$diagnostic_source" "$diagnostic_temporary" 2>/dev/null &&
                "$busybox" chmod 0444 "$diagnostic_temporary" 2>/dev/null &&
                "$busybox" mv "$diagnostic_temporary" \
                    "$diagnostic_target" 2>/dev/null; then
            return 0
        fi
        "$busybox" rm -f "$diagnostic_temporary" 2>/dev/null || true
        return 0
    }

    persist_diagnostic_file "$angel_log" angel-failure.log
    persist_diagnostic_file "$roothealth_report" roothealth.json
    persist_diagnostic_file "$roothealth_stderr" roothealth.stderr
    persist_diagnostic_file "$roothealth_boot_evidence" boot.env
    persist_diagnostic_file "$root_discovery_log" root-discovery.log
    persist_diagnostic_file /proc/self/mountinfo mountinfo
    "$busybox" dmesg | "$busybox" tail -n 2048 \
        >"/run/roothealth-dmesg.log" 2>/dev/null || true
    persist_diagnostic_file /run/roothealth-dmesg.log dmesg.log

    [ -s "$angel_log" ] || {
        "$busybox" sync
        return 0
    }
    # Defined by the sourced Angel recovery engine.
    # shellcheck disable=SC2154
    temporary="$angel_esp_mount/T1OS/.angel-failure.log.new"
    if "$busybox" cp "$angel_log" "$temporary" 2>/dev/null &&
            "$busybox" mv "$temporary" \
                "$angel_esp_mount/T1OS/angel-failure.log" 2>/dev/null; then
        "$busybox" sync
    else
        "$busybox" rm -f "$temporary" 2>/dev/null || true
    fi
}

persist_shutdown_health_evidence() {
    angel_mount_esp || return 0
    diagnostics="$angel_esp_mount/T1OS/diagnostics"
    "$busybox" mkdir -p "$diagnostics" 2>/dev/null || return 0
    for item in \
        "$roothealth_report:shutdown-roothealth.json" \
        "$roothealth_stderr:shutdown-roothealth.stderr" \
        "$roothealth_boot_evidence:shutdown-roothealth.env"
    do
        source_path=${item%%:*}
        target_name=${item#*:}
        [ -s "$source_path" ] || continue
        temporary="$diagnostics/.$target_name.new"
        if "$busybox" cp "$source_path" "$temporary" 2>/dev/null &&
                "$busybox" chmod 0444 "$temporary" 2>/dev/null; then
            "$busybox" mv -f "$temporary" "$diagnostics/$target_name" 2>/dev/null || true
        else
            "$busybox" rm -f "$temporary" 2>/dev/null || true
        fi
    done
    "$busybox" sync
}

rescue() {
    angel_visible=1
    quiet=0
    log "$*"
    # shellcheck disable=SC2034  # Consumed by the sourced Angel recovery engine.
    angel_failure_reason=$*
    printf 'failure_reason=%s\n' "$*" >>"$roothealth_boot_evidence" \
        2>/dev/null || true
    persist_angel_failure_log
    if [ -n "$recovery_spec" ]; then
        angel_recovery_main "${angel_root_mounted:-0}" "${angel_root_safe:-0}" \
            "${angel_root_identity:-0}"
    fi
    if [ "$debug" = 1 ] && [ "$developer" = 1 ]; then
        log 'Explicit developer debug policy is enabled, so I have opened the initial-system shell.'
        exec "$busybox" setsid "$busybox" cttyhack /bin/sh
    fi
    [ "$debug" = 0 ] || \
        log 'I refused the debug shell because the explicit developer policy is not enabled.'
    while :; do
        angel_ask 'Recovery is unavailable. Choose restart or power off.'
        case "$(angel_answer)" in
            restart) "$busybox" reboot -f ;;
            'power off'|poweroff|off) "$busybox" poweroff -f ;;
            *) angel_say 'I did not recognize that answer.' ;;
        esac
    done
}

mount_pseudo_filesystems() {
    "$busybox" mkdir -p /dev /proc /sys /run /mnt
    "$busybox" mountpoint -q /dev || "$busybox" mount -t devtmpfs devtmpfs /dev
    "$busybox" mountpoint -q /proc || "$busybox" mount -t proc proc /proc
    "$busybox" mountpoint -q /sys || "$busybox" mount -t sysfs sysfs /sys

    # Populate early device nodes. Persistent module discovery is owned by the
    # T1OS Driver Server after switch_root, not by an initramfs hotplug helper.
    "$busybox" mdev -s 2>/dev/null || true
}

parse_command_line() {
    for argument in $("$busybox" cat /proc/cmdline); do
        # Recovery metadata is consumed by the sourced Angel engine.
        # shellcheck disable=SC2034
        case "$argument" in
            root=*) root_spec=${argument#root=} ;;
            rootfstype=*) root_fstype=${argument#rootfstype=} ;;
            ro) root_mode=ro ;;
            rw) root_mode=rw ;;
            rootwait) root_wait=60 ;;
            t1os.rootwait=*) root_wait=${argument#t1os.rootwait=} ;;
            t1os.graphics=*) graphics_mode=${argument#t1os.graphics=} ;;
            t1os.recovery=1) recovery=1 ;;
            t1os.recovery.action=*)
                angel_selected_action=${argument#t1os.recovery.action=}
                angel_selection_source=command-line
                ;;
            t1os.recoverypart=*) recovery_spec=${argument#t1os.recoverypart=} ;;
            t1os.esppart=*) esp_spec=${argument#t1os.esppart=} ;;
            t1os.recovery.sha256=*) recovery_sha256=${argument#t1os.recovery.sha256=} ;;
            t1os.recovery.bytes=*) recovery_bytes=${argument#t1os.recovery.bytes=} ;;
            t1os.rootlabel=*) root_label=$(
                printf '%s' "${argument#t1os.rootlabel=}" | "$busybox" tr '_' ' '
            ) ;;
            t1os.debug=1) debug=1 ;;
            t1os.developer=1) developer_request=1 ;;
            t1os.quiet=1) quiet=1 ;;
            t1os.roothealth.serial=*) roothealth_serial=${argument#t1os.roothealth.serial=} ;;
            t1os.roothealth.uuid=*) roothealth_journal_uuid=${argument#t1os.roothealth.uuid=} ;;
            t1os.roothealth.record=*) roothealth_journal_record=${argument#t1os.roothealth.record=} ;;
            rd.luks.uuid=*) luks_spec=UUID=${argument#rd.luks.uuid=} ;;
            t1os.luks=*) luks_spec=${argument#t1os.luks=} ;;
            t1os.luks.name=*) luks_name=${argument#t1os.luks.name=} ;;
        esac
    done

    # Developer capability is a build-and-runtime decision. The marker must be
    # deliberately embedded in the initramfs by a developer build; command-line
    # flags alone can never turn a production recovery environment into a root
    # shell or bypass destructive-action authorization.
    if [ "$developer_request" = 1 ] &&
            [ -f /t1os-developer-policy ] &&
            [ "$("$busybox" cat /t1os-developer-policy 2>/dev/null)" = enabled ]; then
        developer=1
    fi

    case "$root_wait" in
        ''|*[!0-9]*) rescue "I cannot continue because t1os.rootwait is not a valid number. Its value is $root_wait." ;;
    esac

    [ "$root_wait" -le 300 ] || rescue 'I cannot wait more than 300 seconds for the root drive.'

    if [ "${#roothealth_serial}" -ne 16 ]; then
        rescue 'I cannot run roothealth because its expected NTFS serial is absent or malformed.'
    fi
    case "$roothealth_serial" in
        *[!0-9A-Fa-f]*) rescue 'I cannot run roothealth because its expected NTFS serial is malformed.' ;;
    esac
    if [ "${#roothealth_journal_uuid}" -ne 36 ]; then
        rescue 'I cannot run roothealth because its expected journal UUID is absent or malformed.'
    fi
    case "$roothealth_journal_uuid" in
        ????????-????-????-????-????????????) ;;
        *) rescue 'I cannot run roothealth because its expected journal UUID is malformed.' ;;
    esac
    case "$roothealth_journal_uuid" in
        *[!0-9a-f-]*) rescue 'I cannot run roothealth because its expected journal UUID is not canonical lowercase hexadecimal.' ;;
    esac
    case "$roothealth_journal_record" in
        *:*)
            roothealth_record_number=${roothealth_journal_record%%:*}
            roothealth_record_sequence=${roothealth_journal_record#*:}
            ;;
        *) rescue 'I cannot run roothealth because its expected journal record is absent or malformed.' ;;
    esac
    case "$roothealth_record_number" in
        ''|*[!0-9]*) rescue 'I cannot run roothealth because its expected journal record number is malformed.' ;;
    esac
    case "$roothealth_record_sequence" in
        ''|*[!0-9]*) rescue 'I cannot run roothealth because its expected journal record sequence is malformed.' ;;
    esac

    case "$root_spec" in
        UUID=?*|PARTUUID=?*|LABEL=?*|/dev/?*) ;;
        '') rescue 'I cannot find the root drive because no UUID, partition UUID, label, or device was supplied.' ;;
        *) rescue "I cannot use the unsupported root specification $root_spec." ;;
    esac

    case "$angel_selected_action" in
        ''|python|build|reset|reinstall) ;;
        *) angel_selected_action= ;;
    esac
}

matches_device_spec() {
    device=$1
    device_spec=$2
    metadata=$("$busybox" blkid "$device" 2>>"$root_discovery_log")
    metadata_status=$?
    printf 'elapsed=%s candidate=%s blkid_status=%s metadata=%s\n' \
        "${elapsed:-unknown}" "$device" "$metadata_status" "$metadata" \
        >>"$root_discovery_log" 2>/dev/null || true
    [ "$metadata_status" = 0 ] || return 1

    case "$device_spec" in
        UUID=*) expected=${device_spec#UUID=}; token="UUID=\"$expected\"" ;;
        PARTUUID=*) expected=${device_spec#PARTUUID=}; token="PARTUUID=\"$expected\"" ;;
        LABEL=*) expected=${device_spec#LABEL=}; token="LABEL=\"$expected\"" ;;
        /dev/*) [ "$device" = "$device_spec" ]; return ;;
        *) return 1 ;;
    esac

    case "$metadata" in
        *"$token"*) return 0 ;;
        *) return 1 ;;
    esac
}

find_device() {
    device_spec=$1
    elapsed=0
    root_device=
    {
        printf 'device_spec=%s\n' "$device_spec"
        printf 'root_wait=%s\n' "$root_wait"
    } >"$root_discovery_log" 2>/dev/null || true

    while [ "$elapsed" -le "$root_wait" ]; do
        printf 'scan_elapsed=%s\n' "$elapsed" \
            >>"$root_discovery_log" 2>/dev/null || true
        "$busybox" mdev -s 2>/dev/null || true

        if [ "${device_spec#/dev/}" != "$device_spec" ] && [ -b "$device_spec" ]; then
            root_device=$device_spec
            return 0
        fi

        for device in /dev/nvme*n*p* /dev/sd[a-z][0-9]* /dev/vd[a-z][0-9]* /dev/mmcblk*p* /dev/mapper/*; do
            [ -b "$device" ] || continue
            if matches_device_spec "$device" "$device_spec"; then
                root_device=$device
                return 0
            fi
        done

        [ "$elapsed" -lt "$root_wait" ] || break
        "$busybox" sleep 1
        elapsed=$((elapsed + 1))
    done

    return 1
}

verify_t1os_root_base() {
    [ -d '/mnt/the one' ] || return 1
    # A persistent T1OS root is not a Linux distribution hierarchy. The
    # initramfs has its own temporary Unix paths, but none may leak here.
    for forbidden in bin dev etc home lib lib64 mnt opt proc root run sbin srv sys tmp usr var; do
        [ ! -e "/mnt/$forbidden" ] || return 1
    done
}

verify_t1os_root() {
    verify_t1os_root_base || return 1
    [ -x '/mnt/the one/software/python/bin/python' ] || return 1
    validate_protected_inventory_file || return 1
    validate_protected_file python_software bin/python || return 1
    [ -f '/mnt/the one/build/GODDESS/GODDESS.py' ] || return 1
    [ -f '/mnt/the one/build/drivers/driverserver.py' ] || return 1
    [ -x '/mnt/the one/drivers/tools/modprobe' ] || return 1
    [ -f '/mnt/the one/drivers/settings/policy.json' ] || return 1
    [ -s '/mnt/the one/drivers/modules/module-manifest.sha256' ] || return 1

    module_metadata_found=0
    for module_metadata in '/mnt/the one/drivers/modules'/*/modules.dep; do
        if [ -s "$module_metadata" ]; then
            module_metadata_found=1
            break
        fi
    done
    [ "$module_metadata_found" = 1 ] || return 1
}

mount_tree_is_private() {
    # A private mount has neither a shared peer group nor a propagation master.
    # shellcheck disable=SC2016
    "$busybox" awk -v target=/mnt '
        $5 == target || index($5, target "/") == 1 {
            if ($5 == target) top++
            for (field = 7; field <= NF && $field != "-"; field++) {
                if ($field ~ /^(shared|master):/) propagated = 1
            }
        }
        END { exit (top == 1 && !propagated) ? 0 : 1 }
    ' /proc/self/mountinfo
}

mount_t1os_root() {
    requested_mode=$1

    case "$root_fstype" in
        ntfs3)
            mount_options="$requested_mode,$ntfs_mount_options"
            ;;
        ext4)
            # Retain recovery compatibility with older development images.
            mount_options=$requested_mode
            ;;
        *)
            rescue "I cannot use the unsupported The One OS root filesystem $root_fstype."
            ;;
    esac

    "$busybox" mount -t "$root_fstype" -o "$mount_options" "$root_device" /mnt || return 1
    if ! "$busybox" mount --make-rprivate /mnt || ! mount_tree_is_private; then
        "$busybox" umount /mnt 2>/dev/null || true
        return 1
    fi
}

run_roothealth_boot_repair() {
    roothealth_started=$(
        "$busybox" date -u '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || printf unknown
    )
    {
        printf 'root_device=%s\n' "$root_device"
        printf 'root_fstype=%s\n' "$root_fstype"
        printf 'expected_serial=%s\n' "$roothealth_serial"
        printf 'expected_journal_uuid=%s\n' "$roothealth_journal_uuid"
        printf 'expected_journal_record=%s\n' "$roothealth_journal_record"
        printf 'started_utc=%s\n' "$roothealth_started"
    } >"$roothealth_boot_evidence"
    : >"$roothealth_report"
    : >"$roothealth_stderr"
    "$busybox" timeout -k 1 8 /sbin/roothealth \
            --boot-repair \
            --quiet \
            --require-t1os-root \
            --expected-serial "$roothealth_serial" \
            --expected-journal-uuid "$roothealth_journal_uuid" \
            --expected-journal-record "$roothealth_journal_record" \
            "$root_device" 2>"$roothealth_stderr"
    roothealth_status=$?
    roothealth_finished=$(
        "$busybox" date -u '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || printf unknown
    )
    {
        printf 'finished_utc=%s\n' "$roothealth_finished"
        printf 'exit_status=%s\n' "$roothealth_status"
    } >>"$roothealth_boot_evidence"
    [ ! -s "$roothealth_stderr" ] || \
        "$busybox" cat "$roothealth_stderr" >>"$angel_log" 2>/dev/null || true
    return "$roothealth_status"
}

classify_roothealth_refusal() {
    roothealth_refusal_code=$(roothealth_report_primary_code)
    if [ -z "$roothealth_refusal_code" ] && [ -s "$roothealth_stderr" ]; then
        roothealth_refusal_stage=$(
            "$busybox" sed -n 's/.* stage=\([^ ]*\).*/\1/p' \
                "$roothealth_stderr" | "$busybox" tail -n 1
        )
        [ -z "$roothealth_refusal_stage" ] || roothealth_refusal_code=$(
            printf 'BOOT_%s' "$roothealth_refusal_stage" | \
                "$busybox" tr '[:lower:]-' '[:upper:]_'
        )
    fi
    [ -n "$roothealth_refusal_code" ] || roothealth_refusal_code=BOOT_UNCLASSIFIED
    if [ "$roothealth_admission_status" = 124 ] || \
            [ "$roothealth_admission_status" = 137 ]; then
        roothealth_refusal_code=BOOT_TIME_BUDGET_EXCEEDED
    fi
    case "$roothealth_refusal_code" in
        REPAIR_POST_RESCAN_FAILED|VOLUME_DIRTY)
            roothealth_refusal_class=repairable
            roothealth_refusal_summary='RootHealth found a recognized filesystem repair which did not finish with a clean independent rescan.'
            ;;
        WAL_RECOVERY_REQUIRED|NATIVE_LOG_REPLAY_REQUIRED)
            roothealth_refusal_class='recovery-required'
            roothealth_refusal_summary='RootHealth found filesystem journal recovery which must finish before the root can be mounted.'
            ;;
        CENSUS_INCOMPLETE|NATIVE_LOG_UNSUPPORTED_ACTION|UNSUPPORTED_VALID_METADATA|MFT_MIRROR_UNSUPPORTED_LAYOUT)
            roothealth_refusal_class=unsupported
            roothealth_refusal_summary='RootHealth found valid or damaged metadata which this release cannot completely validate or repair.'
            ;;
        WAL_UNSAFE|MFT_MIRROR_DIVERGENCE|MFT_BITMAP_MISMATCH|INDEX_BITMAP_MISMATCH|CLUSTER_BITMAP_MISMATCH|NAMESPACE_RECIPROCITY_MISMATCH|FIXED_SYSTEM_CHECK_FAILED|FOUNDATION_REPAIR_DEFERRED|METADATA_UNRESOLVED)
            roothealth_refusal_class=ambiguous-corruption
            roothealth_refusal_summary='RootHealth found conflicting filesystem metadata without one uniquely safe repair.'
            ;;
        TARGET_IO_ERROR)
            roothealth_refusal_class=io
            roothealth_refusal_summary='RootHealth encountered storage I/O uncertainty during the bounded boot check.'
            ;;
        IDENTITY_MISMATCH)
            roothealth_refusal_class=wrong-root
            roothealth_refusal_summary='The selected filesystem does not match the attested T1OS root identity.'
            ;;
        ORCHESTRATION_INTERNAL_ERROR)
            roothealth_refusal_class=internal
            roothealth_refusal_summary='RootHealth did not complete its own orchestration contract.'
            ;;
        BOOT_TIME_BUDGET_EXCEEDED)
            roothealth_refusal_class=timeout
            roothealth_refusal_summary='RootHealth exceeded its eight-second boot budget and was stopped.'
            ;;
        *)
            case "$roothealth_admission_status" in
                3)
                    roothealth_refusal_class=io
                    roothealth_refusal_summary='RootHealth encountered storage I/O uncertainty during the bounded boot check.'
                    ;;
                4)
                    roothealth_refusal_class=wrong-root
                    roothealth_refusal_summary='The selected filesystem does not match the attested T1OS root identity.'
                    ;;
                124|137)
                    roothealth_refusal_class=timeout
                    roothealth_refusal_summary='RootHealth exceeded its eight-second boot budget and was stopped.'
                    ;;
                5)
                    roothealth_refusal_class=internal
                    roothealth_refusal_summary='RootHealth could not complete its bounded boot check.'
                    ;;
                *)
                    roothealth_refusal_class=unsupported
                    roothealth_refusal_summary='RootHealth found a boot-critical NTFS condition outside its bounded repair surface.'
                    ;;
            esac
            ;;
    esac
    roothealth_refusal_predicates=$(roothealth_report_failed_predicates)
    printf 'roothealth_refusal_code=%s\nroothealth_refusal_class=%s\n' \
        "$roothealth_refusal_code" "$roothealth_refusal_class" \
        >>"$roothealth_boot_evidence" 2>/dev/null || true
}

roothealth_recovery_explanation() {
    [ -n "$roothealth_refusal_summary" ] || return 0
    angel_say "$roothealth_refusal_summary"
    angel_say "The diagnostic code is $roothealth_refusal_code and the policy class is $roothealth_refusal_class."
    [ -z "$roothealth_refusal_predicates" ] || \
        angel_say "The failed RootHealth predicates are $roothealth_refusal_predicates."
}

admit_t1os_ntfs_root() {
    [ "$root_fstype" = ntfs3 ] || return 0
    [ "$roothealth_admission_completed" = 0 ] || \
        [ "$roothealth_admission_status" = 0 ]
    [ -x /sbin/roothealth ] || {
        roothealth_admission_status=127
        log 'RootHealth is unavailable, so I refuse to mount the NTFS root.'
        persist_roothealth_boot_history
        return 127
    }

    roothealth_admission_completed=1
    boot_status "I am asking RootHealth to complete the unmounted NTFS admission check for $root_device."
    if run_roothealth_boot_repair; then
        roothealth_admission_status=0
        boot_status 'RootHealth admitted the root.'
        persist_roothealth_boot_history
        return 0
    else
        roothealth_admission_status=$?
    fi
    classify_roothealth_refusal
    log "$roothealth_refusal_summary"
    log "RootHealth diagnostic code=$roothealth_refusal_code class=$roothealth_refusal_class."
    log "RootHealth refused NTFS admission with status $roothealth_admission_status."
    persist_roothealth_boot_history
    return "$roothealth_admission_status"
}

check_t1os_root_for_recovery() {
    angel_root_safe=0
    angel_root_identity=0
    [ "$root_fstype" = ntfs3 ] || {
        if [ "$root_fstype" = ext4 ]; then
            # The signed root specification resolved this exact device. ext4
            # has no separate RootHealth gate, so resolution is its identity
            # proof and a read-only mount supplies the inspection boundary.
            angel_root_safe=1
            angel_root_identity=1
        fi
        return 0
    }
    if admit_t1os_ntfs_root; then
        angel_root_safe=1
        angel_root_identity=1
    fi
}

select_protected_root() {
    protected_name=$1
    case "$protected_name" in
        python_software)
            protected_destination='/the one/software/python'
            protected_exclude_generated=0
            ;;
        python_catalogue)
            protected_destination='/the one/catalogue/python'
            protected_exclude_generated=0
            ;;
        image_catalogue)
            protected_destination='/the one/catalogue/image'
            protected_exclude_generated=0
            ;;
        build_software)
            protected_destination='/the one/build'
            protected_exclude_generated=1
            ;;
        boot)
            protected_destination='/boot'
            protected_exclude_generated=1
            ;;
        virtualbox_software)
            protected_destination='/the one/software/virtualbox'
            protected_exclude_generated=1
            ;;
        *) return 1 ;;
    esac
    protected_root="/mnt$protected_destination"
}

canonical_protected_path() {
    relative_path=$1
    allow_root=$2

    if [ "$relative_path" = . ]; then
        [ "$allow_root" = 1 ]
        return
    fi
    case "$relative_path" in
        ''|/*) return 1 ;;
    esac
    case "/$relative_path/" in
        *//*|*/./*|*/../*) return 1 ;;
    esac
    return 0
}

secure_protected_directory() {
    directory=$1
    [ -d "$directory" ] && [ ! -L "$directory" ] || return 1
}

secure_protected_mount_root() {
    mount_root=$1
    secure_protected_directory "$mount_root"
}

secure_protected_file() {
    protected_file=$1
    install_mode=$2
    [ -f "$protected_file" ] && [ ! -L "$protected_file" ] || return 1
    [ "$("$busybox" stat -c '%h' "$protected_file" 2>/dev/null)" = 1 ] || return 1
    case "$install_mode" in
        0444) ;;
        0555) ;;
        *) return 1 ;;
    esac
}

validate_protected_ancestors() {
    select_protected_root "$1" || return 1
    secure_protected_mount_root /mnt || return 1
    case "$protected_name" in
        boot) ;;
        build_software)
            secure_protected_directory '/mnt/the one' || return 1
            ;;
        python_software|virtualbox_software)
            secure_protected_directory '/mnt/the one' || return 1
            secure_protected_directory '/mnt/the one/software' || return 1
            ;;
        python_catalogue|image_catalogue)
            secure_protected_directory '/mnt/the one' || return 1
            secure_protected_directory '/mnt/the one/catalogue' || return 1
            ;;
        *) return 1 ;;
    esac
}

validate_protected_inventory_file() {
    secure_protected_file "$protected_inventory" 0444 || return 1
    [ "$("$busybox" stat -c '%a' "$protected_inventory" 2>/dev/null)" = 444 ] || return 1

    # shellcheck disable=SC2016
    "$busybox" awk -F '\t' '
        function protected_name(name) {
            if (name == "python_software") return 1
            if (name == "python_catalogue") return 1
            if (name == "image_catalogue") return 1
            if (name == "build_software") return 1
            if (name == "boot") return 1
            if (name == "virtualbox_software") return 1
            return 0
        }
        NR == 1 {
            if (NF != 5) bad = 1
            if ($1 != "H" || $2 != "1" || $3 == "") bad = 1
            if (length($4) != 64 || $4 ~ /[^0-9a-f]/) bad = 1
            if ($5 != "6") bad = 1
            header_hash = $4
            headers++
            next
        }
        $1 == "R" {
            if (NF != 7 || !protected_name($2)) bad = 1
            if ($3 !~ /^\// || $4 !~ /^[01]$/) bad = 1
            if ($5 !~ /^(0|[1-9][0-9]*)$/) bad = 1
            if ($6 !~ /^(0|[1-9][0-9]*)$/) bad = 1
            if (length($7) != 64 || $7 ~ /[^0-9a-f]/) bad = 1
            roots++
            next
        }
        $1 == "D" {
            if (NF != 4 || !protected_name($2) || $3 == "" || $4 != "0755") bad = 1
            next
        }
        $1 == "F" {
            if (NF != 6 || !protected_name($2) || $3 == "") bad = 1
            if ($4 !~ /^(0|[1-9][0-9]*)$/) bad = 1
            if (length($5) != 64 || $5 ~ /[^0-9a-f]/) bad = 1
            if ($6 != "0444" && $6 != "0555") bad = 1
            if ($2 == "python_software" && $3 == "manifest.json") {
                manifest_records++
                if ($5 != header_hash || $6 != "0444") bad = 1
            }
            next
        }
        { bad = 1 }
        END {
            valid = !bad && headers == 1 && roots == 6 && manifest_records == 1
            exit valid ? 0 : 1
        }
    ' "$protected_inventory" || return 1

    for expected_name in \
        python_software python_catalogue image_catalogue \
        build_software boot virtualbox_software; do
        select_protected_root "$expected_name" || return 1
        # shellcheck disable=SC2016
        root_matches=$("$busybox" awk -F '\t' -v name="$expected_name" \
            '$1 == "R" && $2 == name { count++ } END { print count + 0 }' \
            "$protected_inventory") || return 1
        [ "$root_matches" = 1 ] || return 1
        # shellcheck disable=SC2016
        root_policy=$("$busybox" awk -F '\t' -v name="$expected_name" \
            '$1 == "R" && $2 == name { print $3 "\t" $4 }' \
            "$protected_inventory") || return 1
        [ "$root_policy" = "$protected_destination$("$busybox" printf '\t')$protected_exclude_generated" ] || return 1
    done
}

validate_protected_file() {
    root_name=$1
    relative_path=$2
    select_protected_root "$root_name" || return 1
    validate_protected_ancestors "$root_name" || return 1
    canonical_protected_path "$relative_path" 0 || return 1
    tab=$("$busybox" printf '\t')
    # shellcheck disable=SC2016
    record=$("$busybox" awk -F '\t' -v name="$root_name" -v path="$relative_path" '
        $1 == "F" && $2 == name && $3 == path {
            count++
            value=$4 "\t" $5 "\t" $6
        }
        END { if (count == 1) print value }
    ' "$protected_inventory") || return 1
    IFS="$tab" read -r expected_size expected_sha256 install_mode <<EOF
$record
EOF
    case "$expected_size" in ''|*[!0-9]*) return 1 ;; esac
    case "$expected_sha256" in *[!0-9a-f]*|'') return 1 ;; esac
    [ "${#expected_sha256}" = 64 ] || return 1
    protected_file="$protected_root/$relative_path"
    secure_protected_file "$protected_file" "$install_mode" || return 1
    [ "$("$busybox" stat -c '%s' "$protected_file" 2>/dev/null)" = "$expected_size" ] || return 1
    actual_sha256=$("$busybox" sha256sum "$protected_file" 2>/dev/null) || return 1
    [ "${actual_sha256%% *}" = "$expected_sha256" ]
}

validate_protected_root() {
    root_name=$1
    select_protected_root "$root_name" || return 1
    validate_protected_ancestors "$root_name" || return 1

    tab=$("$busybox" printf '\t')
    # shellcheck disable=SC2016
    root_record=$("$busybox" awk -F '\t' -v name="$root_name" \
        '$1 == "R" && $2 == name { print $5 "\t" $6 }' \
        "$protected_inventory") || return 1
    IFS="$tab" read -r expected_directories expected_files <<EOF
$root_record
EOF
    case "$expected_directories" in
        ''|*[!0-9]*) return 1 ;;
    esac
    case "$expected_files" in
        ''|*[!0-9]*) return 1 ;;
    esac

    work_directory="/run/protected-$root_name"
    "$busybox" rm -rf "$work_directory" || return 1
    "$busybox" mkdir -m 0700 "$work_directory" || return 1
    expected_directory_list="$work_directory/expected-directories"
    actual_directory_list="$work_directory/actual-directories"
    expected_file_list="$work_directory/expected-files"
    actual_file_list="$work_directory/actual-files"
    : >"$expected_directory_list" || return 1
    : >"$expected_file_list" || return 1

    directory_records="$work_directory/directory-records"
    file_records="$work_directory/file-records"
    # shellcheck disable=SC2016
    "$busybox" awk -F '\t' -v name="$root_name" \
        '$1 == "D" && $2 == name { print $3 "\t" $4 }' \
        "$protected_inventory" >"$directory_records" || return 1
    # shellcheck disable=SC2016
    "$busybox" awk -F '\t' -v name="$root_name" \
        '$1 == "F" && $2 == name { print $3 "\t" $4 "\t" $5 "\t" $6 }' \
        "$protected_inventory" >"$file_records" || return 1

    directory_count=0
    while IFS="$tab" read -r relative_path install_mode; do
        canonical_protected_path "$relative_path" 1 || return 1
        [ "$install_mode" = 0755 ] || return 1
        case "$relative_path" in
            .) inventory_path=$protected_root; listed_path=. ;;
            *) inventory_path="$protected_root/$relative_path"; listed_path="./$relative_path" ;;
        esac
        secure_protected_directory "$inventory_path" || return 1
        "$busybox" printf '%s\000' "$listed_path" >>"$expected_directory_list" || return 1
        directory_count=$((directory_count + 1))
    done <"$directory_records"
    [ "$directory_count" = "$expected_directories" ] || return 1

    file_count=0
    while IFS="$tab" read -r relative_path expected_size expected_sha256 install_mode; do
        canonical_protected_path "$relative_path" 0 || return 1
        inventory_path="$protected_root/$relative_path"
        secure_protected_file "$inventory_path" "$install_mode" || return 1
        [ "$("$busybox" stat -c '%s' "$inventory_path" 2>/dev/null)" = "$expected_size" ] || return 1
        actual_sha256=$("$busybox" sha256sum "$inventory_path" 2>/dev/null) || return 1
        [ "${actual_sha256%% *}" = "$expected_sha256" ] || return 1
        "$busybox" printf './%s\000' "$relative_path" >>"$expected_file_list" || return 1
        file_count=$((file_count + 1))
    done <"$file_records"
    [ "$file_count" = "$expected_files" ] || return 1

    unexpected_type=$("$busybox" find "$protected_root" ! -type d ! -type f -print -quit 2>/dev/null) || return 1
    [ -z "$unexpected_type" ] || return 1
    (
        cd "$protected_root" || exit 1
        "$busybox" find . -type d -print0
    ) >"$actual_directory_list" || return 1
    (
        cd "$protected_root" || exit 1
        "$busybox" find . -type f -print0
    ) >"$actual_file_list" || return 1

    "$busybox" sort -z "$expected_directory_list" >"$work_directory/expected-directories.sorted" || return 1
    "$busybox" sort -z "$actual_directory_list" >"$work_directory/actual-directories.sorted" || return 1
    "$busybox" cmp -s \
        "$work_directory/expected-directories.sorted" \
        "$work_directory/actual-directories.sorted" || return 1
    "$busybox" sort -z "$expected_file_list" >"$work_directory/expected-files.sorted" || return 1
    "$busybox" sort -z "$actual_file_list" >"$work_directory/actual-files.sorted" || return 1
    "$busybox" cmp -s \
        "$work_directory/expected-files.sorted" \
        "$work_directory/actual-files.sorted" || return 1
    "$busybox" rm -rf "$work_directory"
}

verify_managed_release_integrity() {
    # Diagnostic and release-qualification helper only. The active development
    # root is allowed to be newer than, or otherwise differ from, the independent
    # recovery image, so normal boot must never call this as an admission gate.
    if ! validate_protected_inventory_file; then
        return 1
    fi

    for root_name in \
        python_software python_catalogue image_catalogue \
        build_software boot virtualbox_software; do
        if ! validate_protected_root "$root_name"; then
            return 1
        fi
    done

    # These hashes establish the accepted boot generation. After switch_root,
    # the T1OS LSM denies Master-role mutation of the system trees and permits
    # deliberate maintenance only after the user changes to Architect.
    log 'I verified the managed runtime and operating-system source trees for The One OS LSM protection.'
    return 0
}

recheck_managed_release_integrity() {
    # Diagnostic and release-qualification helper only; see the policy above.
    validate_protected_inventory_file || \
        rescue 'I cannot recheck the protected-root inventory before handoff.'
    for root_name in \
        python_software python_catalogue image_catalogue \
        build_software boot virtualbox_software; do
        validate_protected_root "$root_name" || \
            rescue "I cannot hand off because protected root $root_name changed after verification."
    done
}

ensure_runtime_permissions() {
    root_directory=/mnt
    sandbox='/mnt/the one/software/chromium/program/chrome-sandbox'
    legacy_python_management='/mnt/the one/software/python/.t1pip'
    python_management='/mnt/the one/software/python/pip'
    "$busybox" chown 0:0 "$root_directory" || rescue 'I could not assign the root filesystem to the root user.'
    "$busybox" chmod 0755 "$root_directory" || rescue 'I could not set the secure root-directory permission.'
    [ "$("$busybox" stat -c '%u:%g:%a' "$root_directory")" = '0:0:755' ] || \
        rescue 'I cannot continue because the root filesystem did not retain its secure root-directory permission.'

    [ -f "$sandbox" ] || rescue 'I cannot continue because the Chromium sandbox is missing from The One OS root.'
    "$busybox" chown 0:0 "$sandbox" || rescue 'I could not assign the Chromium sandbox to the root user.'
    "$busybox" chmod 4755 "$sandbox" || rescue 'I could not set the required Chromium sandbox permission.'
    [ "$("$busybox" stat -c '%u:%g:%a' "$sandbox")" = '0:0:4755' ] || \
        rescue 'I cannot continue because the NTFS root did not retain the Chromium sandbox permission.'
    [ "$("$busybox" stat -c '%h' "$sandbox")" = 1 ] || \
        rescue 'I cannot continue because the Chromium sandbox has a filesystem alias.'

    if [ ! -f "$profiled_python_inventory" ] || [ -L "$profiled_python_inventory" ]; then
        rescue 'I cannot continue because the profiled Python inventory is missing or redirected.'
    fi
    [ "$("$busybox" stat -c '%u:%g:%a:%h' "$profiled_python_inventory")" = '0:0:444:1' ] || \
        rescue 'I cannot continue because the profiled Python inventory is not immutable.'
    profiled_count=0
    while IFS= read -r destination; do
        [ -n "$destination" ] || \
            rescue 'I cannot continue because the profiled Python inventory contains a blank path.'
        case "$destination" in
            /boot/*|'/the one/build/'*|'/the one/software/virtualbox/'*) ;;
            *) rescue "I cannot continue because the profiled Python path $destination is outside its protected roots." ;;
        esac
        script="/mnt$destination"
        if [ ! -f "$script" ] || [ -L "$script" ]; then
            rescue "I cannot continue because the profiled script $script is missing or redirected."
        fi
        [ "$("$busybox" sed -n '1p' "$script")" = '#!"/the one/software/python/bin/python" -B' ] || \
            rescue "I cannot continue because the profiled script $script has no fixed interpreter."
        "$busybox" chown 0:0 "$script" || \
            rescue "I could not assign the profiled script $script to root."
        "$busybox" chmod 0555 "$script" || \
            rescue "I could not protect the profiled script $script."
        [ "$("$busybox" stat -c '%u:%g:%a' "$script")" = '0:0:555' ] || \
            rescue "I cannot continue because the profiled script $script is mutable."
        [ "$("$busybox" stat -c '%h' "$script")" = 1 ] || \
            rescue "I cannot continue because the profiled script $script has a filesystem alias."
        profiled_count=$((profiled_count + 1))
    done < "$profiled_python_inventory"
    [ "$profiled_count" -gt 0 ] || \
        rescue 'I cannot continue because the profiled Python inventory is empty.'

    python_binary='/mnt/the one/software/python/bin/python'
    if [ ! -f "$python_binary" ] || [ -L "$python_binary" ]; then
        rescue 'I cannot continue because the profiled Python interpreter is missing or redirected.'
    fi
    "$busybox" chown 0:0 "$python_binary" || \
        rescue 'I could not assign the profiled Python interpreter to root.'
    "$busybox" chmod 0555 "$python_binary" || \
        rescue 'I could not protect the profiled Python interpreter.'
    [ "$("$busybox" stat -c '%u:%g:%a:%h' "$python_binary")" = '0:0:555:1' ] || \
        rescue 'I cannot continue because the profiled Python interpreter is mutable or aliased.'

    # Move the previous private package state before the runtime LSM boundary
    # becomes active.  Never merge two stores because that would make package
    # ownership and rollback state ambiguous.
    if [ -L "$legacy_python_management" ] || [ -L "$python_management" ]; then
        rescue 'I cannot continue because Python package state is redirected.'
    fi
    if [ -e "$legacy_python_management" ]; then
        [ -d "$legacy_python_management" ] || \
            rescue 'I cannot continue because the previous Python package state is invalid.'
        [ ! -e "$python_management" ] || \
            rescue 'I cannot continue because two Python package states exist.'
        "$busybox" mv -- "$legacy_python_management" "$python_management" || \
            rescue 'I could not migrate the Python package state.'
    fi

    # The Python service cannot create this directory beneath the immutable
    # 0555 interpreter tree after the LSM boundary becomes active. Provision
    # its exact private state roots here, reject redirected objects, and leave
    # the service as the only runtime writer through its measured LSM domain.
    if [ -L "$python_management" ]; then
        rescue 'I cannot continue because the Python management state is redirected.'
    fi
    "$busybox" mkdir -p \
        "$python_management/artifacts" \
        "$python_management/transactions" || \
        rescue 'I could not prepare the Python management state.'
    for python_state_directory in \
        "$python_management" \
        "$python_management/artifacts" \
        "$python_management/transactions"; do
        if [ ! -d "$python_state_directory" ] || [ -L "$python_state_directory" ]; then
            rescue "I cannot continue because Python state $python_state_directory is unsafe."
        fi
        "$busybox" chown 0:0 "$python_state_directory" || \
            rescue "I could not assign Python state $python_state_directory to root."
        "$busybox" chmod 0700 "$python_state_directory" || \
            rescue "I could not protect Python state $python_state_directory."
        [ "$("$busybox" stat -c '%u:%g:%a' "$python_state_directory")" = '0:0:700' ] || \
            rescue "I cannot continue because Python state $python_state_directory retained unsafe metadata."
    done
}

ensure_persistent_runtime_permissions() {
    software='/mnt/software'
    rubbish='/mnt/.rubbish'
    logs='/mnt/the one/logs'

    # These writable roots are deliberately protected as directory objects by
    # the runtime LSM.  Repair their persistent NTFS3 metadata here, while the
    # verified initramfs is still PID 1 and before executing GODDESS activates
    # the post-handoff policy.
    for persistent_directory in "$software" "$rubbish" "$logs"; do
        if [ -L "$persistent_directory" ]; then
            rescue "I cannot continue because persistent runtime tier $persistent_directory is redirected."
        fi
        "$busybox" mkdir -p "$persistent_directory" || \
            rescue "I could not prepare persistent runtime tier $persistent_directory."
        [ -d "$persistent_directory" ] || \
            rescue "I cannot continue because persistent runtime tier $persistent_directory is not a directory."
    done

    vm_test_tiers=0
    if [ "$developer" = 1 ] && \
            [ -f /mnt/t1os-vm-test-agent ] && \
            [ "$("$busybox" cat /mnt/t1os-vm-test-agent 2>/dev/null)" = enabled ]; then
        vm_test_tiers=1
    fi

    if [ "$vm_test_tiers" = 1 ]; then
        software_unsafe=$("$busybox" find "$software" -xdev \
            \( -path "$software/t1os-python" -o \
               -path "$software/t1os-python-index" \) -prune -o \
            ! -type d ! -type f -print -quit 2>/dev/null) || \
            rescue 'I could not inspect the developer software tier.'
    else
        software_unsafe=$("$busybox" find "$software" -xdev \
            ! -type d ! -type f -print -quit 2>/dev/null) || \
            rescue 'I could not inspect the software tier.'
    fi
    [ -z "$software_unsafe" ] || \
        rescue "I found an unsafe object in the software tier at $software_unsafe."

    rubbish_unsafe=$("$busybox" find "$rubbish" -xdev \
        ! -type d ! -type f -print -quit 2>/dev/null) || \
        rescue 'I could not inspect the rubbish tier.'
    [ -z "$rubbish_unsafe" ] || \
        rescue "I found an unsafe object in the rubbish tier at $rubbish_unsafe."

    if [ "$vm_test_tiers" = 1 ]; then
        "$busybox" find "$software" -xdev \
            \( -path "$software/t1os-python" -o \
               -path "$software/t1os-python-index" \) -prune -o \
            -type d -exec "$busybox" chown 1000:1000 {} + \
            -exec "$busybox" chmod 0755 {} + || \
            rescue 'I could not repair the developer software directories.'
        "$busybox" find "$software" -xdev \
            \( -path "$software/t1os-python" -o \
               -path "$software/t1os-python-index" \) -prune -o \
            -type f -exec "$busybox" chown 1000:1000 {} + \
            -exec "$busybox" chmod 'u+rw,go-w,u-s,g-s' {} + || \
            rescue 'I could not repair the developer software files.'
        "$busybox" chown 0:0 "$software" || \
            rescue 'I could not protect the developer software tier.'
        "$busybox" chmod 01777 "$software" || \
            rescue 'I could not set the developer software tier permission.'
        expected_software_metadata='0:0:1777'
    else
        "$busybox" find "$software" -xdev -type d \
            -exec "$busybox" chown 1000:1000 {} + \
            -exec "$busybox" chmod 0755 {} + || \
            rescue 'I could not repair the software directories.'
        "$busybox" find "$software" -xdev -type f \
            -exec "$busybox" chown 1000:1000 {} + \
            -exec "$busybox" chmod 'u+rw,go-w,u-s,g-s' {} + || \
            rescue 'I could not repair the software files.'
        expected_software_metadata='1000:1000:755'
    fi

    "$busybox" find "$rubbish" -xdev -type d \
        -exec "$busybox" chown 1000:1000 {} + \
        -exec "$busybox" chmod 0700 {} + || \
        rescue 'I could not repair the rubbish directories.'
    "$busybox" find "$rubbish" -xdev -type f \
        -exec "$busybox" chown 1000:1000 {} + \
        -exec "$busybox" chmod 0600 {} + || \
        rescue 'I could not repair the rubbish files.'

    "$busybox" chown 0:0 "$logs" || \
        rescue 'I could not assign the system log tier to root.'
    "$busybox" chmod 0755 "$logs" || \
        rescue 'I could not make the system log tier writable by its broker.'

    [ "$("$busybox" stat -c '%u:%g:%a' "$software")" = \
            "$expected_software_metadata" ] || \
        rescue 'I cannot continue because the software tier did not retain its required permission.'
    [ "$("$busybox" stat -c '%u:%g:%a' "$rubbish")" = '1000:1000:700' ] || \
        rescue 'I cannot continue because the rubbish tier did not retain its required permission.'
    [ "$("$busybox" stat -c '%u:%g:%a' "$logs")" = '0:0:755' ] || \
        rescue 'I cannot continue because the log tier did not retain its required permission.'

    log_probe="$logs/.init-write-probe"
    "$busybox" rm -f "$log_probe" 2>/dev/null || true
    if ! : >"$log_probe" 2>/dev/null; then
        rescue 'I cannot continue because the system log tier is not writable.'
    fi
    "$busybox" rm -f "$log_probe" || \
        rescue 'I could not remove the system log write probe.'
}

prepare_terminfo_runtime() {
    source='/mnt/the one/settings/terminfo'
    ephemeral='/mnt/.ephemeral'
    target="$ephemeral/terminfo"

    [ -d "$source" ] || rescue 'I cannot continue because the packaged terminal information database is missing.'
    "$busybox" mkdir -p "$ephemeral" || rescue 'I could not create the temporary The One OS mount point.'
    "$busybox" mount -t tmpfs \
        -o nodev,nosuid,mode=1777 \
        tmpfs "$ephemeral" || rescue 'I could not create the temporary The One OS filesystem.'
    "$busybox" mkdir -m 0700 "$ephemeral/media" || \
        rescue 'I could not prepare the private desktop media runtime.'
    "$busybox" chown 1000:1000 "$ephemeral/media" || \
        rescue 'I could not assign the private desktop media runtime.'
    "$busybox" chmod 0700 "$ephemeral/media" || \
        rescue 'I could not protect the private desktop media runtime.'
    "$busybox" mkdir -m 0700 "$ephemeral/brick" || \
        rescue 'I could not prepare the private Brick diagnostic runtime.'
    "$busybox" chown 1000:1000 "$ephemeral/brick" || \
        rescue 'I could not assign the private Brick diagnostic runtime.'
    "$busybox" chmod 0700 "$ephemeral/brick" || \
        rescue 'I could not protect the private Brick diagnostic runtime.'
    "$busybox" mkdir -m 0711 "$ephemeral/expanse" || \
        rescue 'I could not prepare the private Expanse runtime.'
    "$busybox" chown 1000:1000 "$ephemeral/expanse" || \
        rescue 'I could not assign the private Expanse runtime.'
    "$busybox" chmod 0711 "$ephemeral/expanse" || \
        rescue 'I could not protect the private Expanse runtime.'
    "$busybox" mkdir -m 01733 "$ephemeral/network" || \
        rescue 'I could not prepare the network exchange runtime.'
    "$busybox" chown 0:0 "$ephemeral/network" || \
        rescue 'I could not assign the network exchange runtime.'
    "$busybox" chmod 01733 "$ephemeral/network" || \
        rescue 'I could not protect the network exchange runtime.'
    "$busybox" mkdir -m 02710 "$ephemeral/audio" || \
        rescue 'I could not prepare the private audio service runtime.'
    "$busybox" chown 0:1000 "$ephemeral/audio" || \
        rescue 'I could not assign the private audio service runtime.'
    "$busybox" chmod 02710 "$ephemeral/audio" || \
        rescue 'I could not protect the private audio service runtime.'
    "$busybox" mkdir -p "$target" || rescue 'I could not create the terminal information mount point.'
    "$busybox" mount -t tmpfs \
        -o nodev,nosuid,noexec,size=32M,mode=0755 \
        tmpfs "$target" || rescue 'I could not create the runtime terminal information filesystem.'

    index="$source/index.tsv"
    [ -s "$index" ] || rescue 'I cannot continue because the packaged terminal information index is missing.'
    tab=$("$busybox" printf '\t')
    while IFS="$tab" read -r bucket_hex entry_hex bucket_octal entry_name; do
        case "$bucket_hex" in
            [0-9a-f][0-9a-f]) ;;
            *) rescue "I found an invalid terminal information bucket named $bucket_hex." ;;
        esac
        case "$entry_hex" in
            *[!0-9a-f]*|'') rescue "I found an invalid terminal information entry named $entry_hex." ;;
        esac
        expected_octal=$("$busybox" printf '%03o' "$((0x$bucket_hex))")
        [ "$bucket_octal" = "$expected_octal" ] || \
            rescue "I found a terminal information bucket mapping that does not match $bucket_hex and $bucket_octal."
        case "$entry_name" in
            ''|.|..|*/*) rescue "I found an invalid runtime terminal information name $entry_name." ;;
        esac
        [ -s "$source/$bucket_hex/$entry_hex" ] || \
            rescue "I cannot find the packaged terminal information entry $bucket_hex/$entry_hex."
        bucket_name=$("$busybox" printf "\\$bucket_octal")
        "$busybox" mkdir -p "$target/$bucket_name" || \
            rescue "I could not create the runtime terminal information bucket $bucket_name."
        "$busybox" cp -a "$source/$bucket_hex/$entry_hex" "$target/$bucket_name/$entry_name" || \
            rescue "I could not prepare the runtime terminal information entry $entry_name."
    done < "$index"

    [ -s "$target/l/linux" ] || rescue 'I cannot continue because the Linux terminal information entry is missing.'
    "$busybox" mount -o remount,ro,nodev,nosuid,noexec "$target" || \
        rescue 'I could not protect the runtime terminal information filesystem by making it read-only.'
}

mount_recovery_request_store() {
    target='/mnt/.ephemeral/angel-boot'
    [ -n "$esp_spec" ] || return 1
    if [ -z "${esp_device:-}" ] || [ ! -b "$esp_device" ]; then
        esp_device=$(angel_resolve_device "$esp_spec") || return 1
    fi
    "$busybox" mkdir -p "$target" || return 1
    "$busybox" mount -t vfat \
        -o rw,nodev,nosuid,noexec,umask=0077 \
        "$esp_device" "$target" || return 1
    "$busybox" mkdir -p "$target/T1OS" || return 1
    return 0
}

prepare_target_mounts() {
    "$busybox" mkdir -p \
        '/mnt/the one/drivers/nodes' \
        '/mnt/the one/drivers/state' \
        '/mnt/the one/drivers/control' \
        '/mnt/the one/drivers/processes' \
        '/mnt/the one/logs'

    "$busybox" mount -t devtmpfs devtmpfs '/mnt/the one/drivers/nodes' || \
        rescue 'I could not mount The One OS device tree.'
    "$busybox" mkdir -p '/mnt/the one/drivers/nodes/pts' || \
        rescue 'I could not prepare the interactive console device tree.'
    "$busybox" mount -t devpts \
        -o newinstance,gid=1000,ptmxmode=0660,mode=0600 \
        devpts '/mnt/the one/drivers/nodes/pts' || \
        rescue 'I could not mount the interactive console device tree.'
    [ -c '/mnt/the one/drivers/nodes/pts/ptmx' ] || \
        rescue 'I cannot find the interactive console device multiplexer.'
    "$busybox" chown 0:1000 '/mnt/the one/drivers/nodes/pts/ptmx' || \
        rescue 'I could not assign the interactive console device group.'
    "$busybox" chmod 0660 '/mnt/the one/drivers/nodes/pts/ptmx' || \
        rescue 'I could not permit the desktop group to open interactive consoles.'
    "$busybox" mount -t sysfs -o rw sysfs '/mnt/the one/drivers/control' || \
        rescue 'I could not mount The One OS driver control tree.'
    "$busybox" mount -t sysfs -o ro sysfs '/mnt/the one/drivers/state' || \
        rescue 'I could not mount The One OS driver state tree.'
    "$busybox" mount -t proc -o ro proc '/mnt/the one/drivers/processes' || \
        rescue 'I could not mount The One OS driver process state tree.'

    # Kernels predating the quoted-interpreter support created this one alias.
    # Remove only the exact legacy object; T1OS now executes canonical Python
    # directly and does not permit symbolic links.
    if [ -L /mnt/t1python ]; then
        [ "$("$busybox" readlink /mnt/t1python 2>/dev/null)" = \
            '/the one/software/python/bin/python' ] || \
            rescue 'I found a redirected Python interpreter alias in the persistent root.'
		"$busybox" rm -- /mnt/t1python || \
			rescue 'I could not remove the obsolete Python interpreter alias.'
    elif [ -e /mnt/t1python ]; then
        rescue 'I found an unexpected Python interpreter alias object in the persistent root.'
    fi
    if [ -e /mnt/t1python ] || [ -L /mnt/t1python ]; then
        rescue 'I cannot continue while the obsolete Python interpreter alias remains.'
    fi

    # A graphics-recovery reboot must return to this exact USB boot entry even
    # when the user launched it from a firmware one-time boot menu. Expose the
    # EFI variable store to PID 1 so it can set and verify
    # BootNext=BootCurrent before rebooting. Non-UEFI systems retain the
    # same-boot recovery loop and deliberately skip this optional mount.
    efivars='/mnt/the one/drivers/control/firmware/efi/efivars'
    if [ -d '/sys/firmware/efi' ] && [ -d "$efivars" ]; then
        "$busybox" mount -t efivarfs \
            -o nodev,nosuid,noexec \
            efivarfs "$efivars" || \
            log 'I cannot reach the EFI variables, so recovery restart will remain disabled.'
    fi
}

atreyan_boot_timestamp() {
    common_timestamp=$1

    if [ -z "$common_timestamp" ]; then
        common_timestamp=$("$busybox" date '+%Y-%m-%dT%H-%M-%S' 2>/dev/null) || return 1
    fi

    # The dollar-prefixed fields below belong to awk, not the shell.
    # shellcheck disable=SC2016
    "$busybox" printf '%s\n' "$common_timestamp" | "$busybox" awk -F '[-T]' '
        NF == 6 &&
        $1 ~ /^[0-9]+$/ && $2 ~ /^[0-9][0-9]$/ &&
        $3 ~ /^[0-9][0-9]$/ && $4 ~ /^[0-9][0-9]$/ &&
        $5 ~ /^[0-9][0-9]$/ && $6 ~ /^[0-9][0-9]$/ {
            year = $1 - 2020
            if (year < 1 || $2 < 1 || $2 > 12 || $3 < 1 || $3 > 31 ||
                    $4 > 23 || $5 > 59 || $6 > 59) {
                exit 1
            }
            printf "%s-%s-%dAE %s.%s.%s\n", $3, $2, year, $4, $5, $6
            formatted = 1
        }
        END { if (!formatted) exit 1 }
    '
}

atreyan_log_timestamp() {
    common_timestamp=$("$busybox" date '+%Y-%m-%dT%H-%M-%S' 2>/dev/null) || return 1

    # Match the timestamp produced by GODDESS.formatlog for normal T1OS
    # software logs: [DD:MM:YAE H:MM:SS AM].
    # shellcheck disable=SC2016
    "$busybox" printf '%s\n' "$common_timestamp" | "$busybox" awk -F '[-T]' '
        NF == 6 &&
        $1 ~ /^[0-9]+$/ && $2 ~ /^[0-9][0-9]$/ &&
        $3 ~ /^[0-9][0-9]$/ && $4 ~ /^[0-9][0-9]$/ &&
        $5 ~ /^[0-9][0-9]$/ && $6 ~ /^[0-9][0-9]$/ {
            year = $1 - 2020
            if (year < 1 || $2 < 1 || $2 > 12 || $3 < 1 || $3 > 31 ||
                    $4 > 23 || $5 > 59 || $6 > 59) {
                exit 1
            }
            hour = $4 % 12
            if (hour == 0)
                hour = 12
            ampm = $4 < 12 ? "AM" : "PM"
            printf "[%s:%s:%dAE %d:%s:%s %s]\n",
                $3, $2, year, hour, $5, $6, ampm
            formatted = 1
        }
        END { if (!formatted) exit 1 }
    '
}

roothealth_report_string() {
    report_key=$1
    "$busybox" sed -n \
        "s/.*\\\"$report_key\\\":\\\"\\([^\\\"]*\\)\\\".*/\\1/p" \
        /run/roothealth.json
}

roothealth_report_number() {
    report_key=$1
    "$busybox" sed -n \
        "s/.*\\\"$report_key\\\":\\([0-9][0-9]*\\).*/\\1/p" \
        /run/roothealth.json
}

roothealth_report_primary_code() {
    [ -s "$roothealth_report" ] || return 0
    # shellcheck disable=SC2016  # Dollar expressions below belong to awk.
    "$busybox" awk '
        { report = report $0 }
        END {
            issues = index(report, "\"issues\":[{")
            if (!issues) exit
            remainder = substr(report, issues)
            marker = "\"code\":\""
            start = index(remainder, marker)
            if (!start) exit
            remainder = substr(remainder, start + length(marker))
            finish = index(remainder, "\"")
            if (finish) print substr(remainder, 1, finish - 1)
        }
    ' "$roothealth_report"
}

roothealth_report_failed_predicates() {
    [ -s "$roothealth_report" ] || return 0
    # shellcheck disable=SC2016  # Dollar expressions below belong to awk.
    predicates=$("$busybox" awk '
        { report = report $0 }
        END {
            issues = index(report, "\"issues\":[{")
            if (!issues) exit
            remainder = substr(report, issues)
            marker = "\"failed_predicates\":["
            start = index(remainder, marker)
            if (!start) exit
            remainder = substr(remainder, start + length(marker))
            finish = index(remainder, "]")
            if (finish) print substr(remainder, 1, finish - 1)
        }
    ' "$roothealth_report")
    [ -n "$predicates" ] || return 0
    # RootHealth owns the report, but keep terminal-facing evidence to a small,
    # printable alphabet and bound it before Angel speaks it.
    printf '%s' "$predicates" | "$busybox" tr -cd \
        '[:alnum:]_.,:=/+ -' | "$busybox" sed 's/,/, /g' | \
        "$busybox" cut -c 1-512
}

roothealth_fixed_system_counts() {
    "$busybox" sed -n \
        's/.*"fixed_system":{"checks":\[[^]]*\],"completed":\([0-9][0-9]*\),"expected":\([0-9][0-9]*\),"failed":\([0-9][0-9]*\)}.*/\1 \2 \3/p' \
        /run/roothealth.json
}

write_roothealth_log() {
    roothealth_stamp=$(atreyan_log_timestamp 2>/dev/null) || \
        roothealth_stamp='[unknown time]'
    roothealth_version=$(roothealth_report_string checker_version)
    roothealth_mode=$(roothealth_report_string mode)
    roothealth_result=$(roothealth_report_string result)
    roothealth_exit=$(roothealth_report_number exit_code)
    roothealth_device=$(roothealth_report_string resolved_path)
    roothealth_label=$(roothealth_report_string observed_label)
    roothealth_serial_observed=$(roothealth_report_string observed_primary_serial)
    roothealth_fixed_counts=$(roothealth_fixed_system_counts)
    roothealth_fixed_completed=${roothealth_fixed_counts%% *}
    roothealth_fixed_remainder=${roothealth_fixed_counts#* }
    roothealth_fixed_expected=${roothealth_fixed_remainder%% *}
    roothealth_fixed_failed=${roothealth_fixed_remainder#* }
    roothealth_unresolved=$(roothealth_report_number unresolved_count)
    roothealth_operations=$(roothealth_report_number operations)

    [ -n "$roothealth_version" ] || roothealth_version=unknown
    [ -n "$roothealth_mode" ] || roothealth_mode=unknown
    [ -n "$roothealth_result" ] || roothealth_result=unknown
    [ -n "$roothealth_exit" ] || roothealth_exit=unknown
    [ -n "$roothealth_device" ] || roothealth_device=unknown
    [ -n "$roothealth_label" ] || roothealth_label=unknown
    [ -n "$roothealth_serial_observed" ] || roothealth_serial_observed=unknown
    [ -n "$roothealth_fixed_completed" ] || roothealth_fixed_completed=unknown
    [ -n "$roothealth_fixed_expected" ] || roothealth_fixed_expected=unknown
    [ -n "$roothealth_fixed_failed" ] || roothealth_fixed_failed=unknown
    [ -n "$roothealth_unresolved" ] || roothealth_unresolved=unknown
    [ -n "$roothealth_operations" ] || roothealth_operations=unknown

    printf '%s [roothealth] root drive check completed version=%s mode=%s result=%s exit_code=%s\n' \
        "$roothealth_stamp" "$roothealth_version" "$roothealth_mode" \
        "$roothealth_result" "$roothealth_exit"
    printf '%s [roothealth] volume identity verified device=%s label="%s" serial=%s\n' \
        "$roothealth_stamp" "$roothealth_device" "$roothealth_label" \
        "$roothealth_serial_observed"
    printf '%s [roothealth] fixed system metadata checks completed=%s expected=%s failed=%s unresolved_issues=%s\n' \
        "$roothealth_stamp" "$roothealth_fixed_completed" \
        "$roothealth_fixed_expected" "$roothealth_fixed_failed" \
        "$roothealth_unresolved"
    if [ "$roothealth_operations" = 0 ]; then
        printf '%s [roothealth] repair plan was empty; no filesystem metadata writes were required\n' \
            "$roothealth_stamp"
    else
        printf '%s [roothealth] qualified repairs completed operations=%s\n' \
            "$roothealth_stamp" "$roothealth_operations"
    fi
    if [ "$roothealth_result" = clean ] && [ "$roothealth_exit" = 0 ]; then
        printf '%s [roothealth] fresh read-only rescan proved the root drive clean\n' \
            "$roothealth_stamp"
    else
        printf '%s [roothealth] advisory verdict did not gate boot; the kernel mount and mounted T1OS identity were authoritative\n' \
            "$roothealth_stamp"
    fi
    printf '%s [roothealth] machine-readable evidence is available in /the one/logs/roothealth.json\n' \
        "$roothealth_stamp"
}

archive_previous_boot_logs() {
    logs='/mnt/the one/logs'
    previous_kernel_log="$logs/kernel.log"
    if [ ! -s "$previous_kernel_log" ] && [ -s "$logs/hardware-boot.log" ]; then
        # One-release compatibility for boots written before kernel.log was
        # given its canonical name.
        previous_kernel_log="$logs/hardware-boot.log"
    fi
    current_boot_id=$("$busybox" cat /proc/sys/kernel/random/boot_id 2>/dev/null)
    previous_boot_id=
    previous_boot_timestamp=
    previous_graphics_mode=

    if [ -s "$previous_kernel_log" ]; then
        # shellcheck disable=SC2016
        previous_boot_id=$("$busybox" awk -F= \
            '$1 == "boot_id" { value=$2 } END { print value }' \
            "$previous_kernel_log" 2>/dev/null)
        # shellcheck disable=SC2016
        previous_boot_timestamp=$("$busybox" awk -F= \
            '$1 == "boot_timestamp" { value=$2 } END { print value }' \
            "$previous_kernel_log" 2>/dev/null)
        # shellcheck disable=SC2016
        previous_graphics_mode=$("$busybox" awk -F= \
            '$1 == "graphics_mode" { value=$2 } END { print value }' \
            "$previous_kernel_log" 2>/dev/null)
    fi

    case "$current_boot_id" in
        ''|*[!A-Za-z0-9._-]*) current_boot_id=unknown-current-boot ;;
    esac
    case "$previous_boot_id" in
        ''|*[!A-Za-z0-9._-]*)
            previous_boot_id="legacy-before-$current_boot_id"
            ;;
    esac
    # Upgrade the timestamp written by older init builds before using it as a
    # directory name. New builds persist this Atreyan form directly.
    case "$previous_boot_timestamp" in
        ????-??-??T??-??-??)
            previous_boot_timestamp=$(atreyan_boot_timestamp \
                "$previous_boot_timestamp" 2>/dev/null) || previous_boot_timestamp=
            ;;
    esac
    timestamp_invalid_characters=$("$busybox" printf '%s' \
        "$previous_boot_timestamp" | "$busybox" tr -d '0123456789AE. -')
    [ -z "$timestamp_invalid_characters" ] || previous_boot_timestamp=
    case "$previous_boot_timestamp" in
        ??-??-[0-9]*AE\ ??.??.??) ;;
        *)
            previous_boot_timestamp=$(atreyan_boot_timestamp 2>/dev/null)
            case "$previous_boot_timestamp" in
                ??-??-[0-9]*AE\ ??.??.??) ;;
                *) previous_boot_timestamp="unknown-time-$previous_boot_id" ;;
            esac
            ;;
    esac

    # A supervised service which emitted nothing has no log evidence to keep.
    # Remove legacy placeholders before deciding whether this boot needs an
    # archive, so zero-line logs cannot survive in either the active tier or a
    # previous-boot directory.
    for evidence in "$logs"/*.log; do
        [ -f "$evidence" ] || continue
        [ -s "$evidence" ] && continue
        "$busybox" rm -f "$evidence"
    done

    previous_files=0
    for evidence in "$logs"/*; do
        [ -f "$evidence" ] || continue
        evidence_name=${evidence##*/}
        case "$evidence_name" in
            failed\ GPU\ boot\ -\ *|boot\ *\ -\ *|previous-gpu-boot.txt)
                continue
                ;;
            *)
                previous_files=1
                break
                ;;
        esac
    done
    [ "$previous_files" = 1 ] || return 0

    archive_directory="$logs/$previous_boot_timestamp"
    if [ -e "$archive_directory" ]; then
        archive_directory="$logs/$previous_boot_timestamp - $previous_boot_id"
    fi
    "$busybox" mkdir -p "$archive_directory" 2>/dev/null || return 0

    # Move the completed boot's active files together, retaining their canonical
    # names. The new boot receives clean logs while each prior boot is represented
    # by one timestamped directory.
    for evidence in "$logs"/*; do
        [ -f "$evidence" ] || continue
        evidence_name=${evidence##*/}
        case "$evidence_name" in
            failed\ GPU\ boot\ -\ *|boot\ *\ -\ *|previous-gpu-boot.txt)
                continue
                ;;
        esac
        "$busybox" mv "$evidence" \
            "$archive_directory/$evidence_name" 2>/dev/null || true
    done

    {
        printf 'format=2\n'
        printf 'boot_timestamp=%s\n' "$previous_boot_timestamp"
        printf 'previous_boot_id=%s\n' "$previous_boot_id"
        printf 'captured_before_boot_id=%s\n' "$current_boot_id"
        printf 'previous_graphics_mode=%s\n' "$previous_graphics_mode"
        if [ "$graphics_mode" = cpu ] && [ "$previous_graphics_mode" != cpu ]; then
            printf 'failed_gpu_boot=1\n'
        else
            printf 'failed_gpu_boot=0\n'
        fi
    } >"$archive_directory/archive-manifest.txt" 2>/dev/null || true

    if [ "$graphics_mode" = cpu ] && [ "$previous_graphics_mode" != cpu ]; then
        {
            printf 'directory=/the one/logs/%s\n' "${archive_directory##*/}"
            printf 'previous_boot_id=%s\n' "$previous_boot_id"
        } >"$logs/previous-gpu-boot.txt" 2>/dev/null || true
    fi
}

persist_ntfs_health_report() {
    [ "$root_fstype" = ntfs3 ] || return 0
    [ "$root_mode" = rw ] || return 0
    [ -s /run/roothealth.json ] || return 0

    logs='/mnt/the one/logs'
    [ -d "$logs" ] || return 0
    report_tmp="$logs/.roothealth.json.new"
    log_tmp="$logs/.roothealth.log.new"
    "$busybox" rm -f "$report_tmp"
    if "$busybox" cp /run/roothealth.json "$report_tmp" &&
            "$busybox" chmod 0444 "$report_tmp" &&
            "$busybox" mv "$report_tmp" "$logs/roothealth.json"; then
        :
    else
        "$busybox" rm -f "$report_tmp"
        log 'I could not preserve the NTFS health report on the root drive.'
    fi

    "$busybox" rm -f "$log_tmp"
    if write_roothealth_log >"$log_tmp" &&
            "$busybox" chmod 0444 "$log_tmp" &&
            "$busybox" mv "$log_tmp" "$logs/roothealth.log"; then
        return 0
    fi

    "$busybox" rm -f "$log_tmp"
    log 'I could not preserve the readable NTFS health log on the root drive.'
}

write_hardware_inventory() {
    output='/mnt/the one/logs/hardware_inventory.log'

    {
        printf 'format=1\n'
        printf 'boot_id=%s\n' "$boot_id"
        printf 'graphics_mode=%s\n' "$graphics_mode"
        printf 'kernel='
        "$busybox" uname -a
        printf 'command_line='
        "$busybox" cat /proc/cmdline

        for version_file in \
            '/mnt/the one/settings/t1osversion.txt' \
            '/mnt/the one/software/graphics/version.txt' \
            '/mnt/the one/catalogue/graphics/catalogue.json' \
            '/mnt/the one/drivers/settings/runtime.json' \
            '/mnt/the one/drivers/firmware/t1os-firmware-manifest.json' \
            '/mnt/the one/drivers/modules/module-manifest.sha256'; do
            if [ -s "$version_file" ]; then
                printf '\n===== file %s =====\n' "${version_file#/mnt}"
                "$busybox" cat "$version_file"
            fi
        done

        printf '\n===== loaded modules =====\n'
        "$busybox" cat /proc/modules

        printf '\n===== display PCI devices =====\n'
        for device in /sys/bus/pci/devices/*; do
            [ -s "$device/class" ] || continue
            pci_class=$("$busybox" cat "$device/class" 2>/dev/null)
            case "$pci_class" in
                0x0300*|0x0302*) ;;
                *) continue ;;
            esac

            printf '\n[pci %s]\n' "${device##*/}"
            for attribute in \
                class vendor device subsystem_vendor subsystem_device \
                revision irq numa_node current_link_speed current_link_width \
                max_link_speed max_link_width; do
                if [ -r "$device/$attribute" ]; then
                    printf '%s=' "$attribute"
                    "$busybox" cat "$device/$attribute"
                fi
            done
            if [ -L "$device/driver" ]; then
                printf 'driver='
                "$busybox" readlink "$device/driver"
            fi
            if [ -L "$device/iommu_group" ]; then
                printf 'iommu_group='
                "$busybox" readlink "$device/iommu_group"
            fi
            for attribute in power/control power/runtime_status \
                power/runtime_active_time power/runtime_suspended_time; do
                if [ -r "$device/$attribute" ]; then
                    printf '%s=' "$attribute"
                    "$busybox" cat "$device/$attribute"
                fi
            done
            if [ -r "$device/uevent" ]; then
                "$busybox" cat "$device/uevent"
            fi
            if [ -r "$device/config" ]; then
                printf 'config_hex='
                "$busybox" od -An -tx1 -v "$device/config" 2>/dev/null | \
                    "$busybox" tr -d ' \n'
                printf '\n'
            fi
        done

        printf '\n===== DRM nodes and connectors =====\n'
        for drm_node in /sys/class/drm/*; do
            [ -e "$drm_node" ] || continue
            printf '\n[drm %s]\n' "${drm_node##*/}"
            printf 'target='
            "$busybox" readlink "$drm_node" 2>/dev/null || true
            for attribute in status enabled dpms modes; do
                if [ -r "$drm_node/$attribute" ]; then
                    printf '%s=' "$attribute"
                    "$busybox" cat "$drm_node/$attribute"
                fi
            done
            if [ -s "$drm_node/edid" ]; then
                printf 'edid_hex='
                "$busybox" od -An -tx1 -v "$drm_node/edid" 2>/dev/null | \
                    "$busybox" tr -d ' \n'
                printf '\n'
            fi
        done

        printf '\n===== nouveau module parameters =====\n'
        for attribute in version srcversion taint; do
            if [ -r "/sys/module/nouveau/$attribute" ]; then
                printf '%s=' "$attribute"
                "$busybox" cat "/sys/module/nouveau/$attribute"
            fi
        done
        for parameter in /sys/module/nouveau/parameters/*; do
            [ -r "$parameter" ] || continue
            printf '%s=' "${parameter##*/}"
            "$busybox" cat "$parameter" 2>/dev/null || printf '<unreadable>\n'
        done
    } >"$output" 2>&1 || true
}

mount_pseudo_filesystems
parse_command_line
boot_status 'I have started the initial system and am preparing the root drive.'

# Settings records a one-shot request on the EFI system partition. Reading it
# here avoids any dependency on the installed Python runtime.
if angel_mount_esp; then
    if angel_read_journal || angel_read_request; then
        recovery=1
    fi
    angel_read_shutdown_health_request || true
    if [ "$recovery" != 1 ] && [ -z "$angel_shutdown_health_action" ]; then
        # Defined by the sourced Angel recovery engine.
        # shellcheck disable=SC2154
        angel_unmount_esp 2>/dev/null || true
    fi
fi

if [ -n "$luks_spec" ]; then
    log "I am waiting up to $root_wait seconds for the encrypted container $luks_spec."
    find_device "$luks_spec" || rescue "I could not find the encrypted root container $luks_spec."
    luks_device=$root_device
    log "I found the encrypted container at $luks_device."
    [ -x /sbin/cryptsetup ] || rescue 'I cannot unlock the root drive because cryptsetup is missing from the initial system.'
    /sbin/cryptsetup open --type luks "$luks_device" "$luks_name" </dev/console >/dev/console 2>&1 || \
        rescue 'I could not unlock the encrypted The One OS root.'
    "$busybox" mdev -s 2>/dev/null || true
fi

boot_status "I am waiting up to $root_wait seconds for the root drive $root_spec."
find_device "$root_spec" || rescue "I could not find the root filesystem $root_spec."
boot_status "I found the candidate root drive at $root_device."
# Consumed by the sourced Angel recovery engine.
# shellcheck disable=SC2034
angel_reinstall_allowed=1

if [ -n "$angel_shutdown_health_action" ]; then
    boot_status "I am completing the unmounted RootHealth shutdown gate for $angel_shutdown_health_action."
    if admit_t1os_ntfs_root; then
        persist_shutdown_health_evidence
        angel_clear_shutdown_health_request
        if [ "$angel_shutdown_health_action" = poweroff ]; then
            boot_status 'The unmounted shutdown health gate passed. I will power off now.'
            angel_unmount_esp || \
                rescue 'I could not safely release the boot partition after the shutdown health gate.'
            "$busybox" poweroff -f
            while :; do "$busybox" sleep 60; done
        fi
        boot_status 'The unmounted restart health gate passed. I will continue this clean boot now.'
        angel_shutdown_health_action=
        angel_unmount_esp || \
            rescue 'I could not safely release the boot partition after the restart health gate.'
    else
        rescue "The unmounted shutdown health gate failed with RootHealth code $roothealth_refusal_code."
    fi
fi

if [ "$recovery" = 1 ]; then
    check_t1os_root_for_recovery
    if [ "$angel_root_safe" = 1 ] && mount_t1os_root ro; then
        angel_root_mounted=1
        if verify_t1os_root_base; then
            angel_root_identity=1
        fi
    fi
    angel_recovery_main "$angel_root_mounted" "$angel_root_safe" "$angel_root_identity"
fi

admit_t1os_ntfs_root || \
    rescue "RootHealth did not admit the unmounted NTFS root $root_device (code $roothealth_refusal_code, class $roothealth_refusal_class)."

if ! mount_t1os_root ro; then
    rescue "I could not mount the RootHealth-admitted root $root_device read-only as $root_fstype."
fi
angel_root_safe=1
angel_root_mounted=1
if [ "$root_fstype" = ntfs3 ]; then
    angel_root_identity=1
fi

verify_t1os_root_base || rescue "I cannot continue because $root_device is not a valid root filesystem for The One OS."
angel_root_identity=1
log 'I verified The One OS root identity while it was read-only.'

if ! verify_t1os_root; then
    rescue 'I found operating-system files that must be recovered before The One OS can start.'
fi

if [ "$root_mode" = rw ]; then
    # Reopen the already-verified root read-write, then verify the mounted
    # identity again before executing anything from it.
    "$busybox" umount /mnt || rescue "I could not release the verified mount on $root_device."
    angel_root_mounted=0

    mount_t1os_root rw || \
        rescue "I could not reopen the RootHealth-admitted root $root_device for reading and writing."
    angel_root_mounted=1
    verify_t1os_root || rescue "I cannot continue because The One OS root at $root_device changed identity while I reopened it for writing."
    prepare_terminfo_runtime
    ensure_runtime_permissions
    ensure_persistent_runtime_permissions
    mount_recovery_request_store || \
        log 'I cannot mount the boot recovery request store, so Settings recovery restart will be unavailable.'
fi

# During development, active managed files are deliberately allowed to differ
# from the independent recovery image. Recovery validates its own image before
# any requested restore; its older file inventory is not a normal-boot policy.
prepare_target_mounts
archive_previous_boot_logs
persist_ntfs_health_report

export TERM=linux
export TERMINFO='/.ephemeral/terminfo'
export PYTHONHASHSEED=0
export PYTHONNOUSERSITE=1
export PYTHONDONTWRITEBYTECODE=1
export PYTHONSAFEPATH=1
unset PYTHONHOME PYTHONPATH

case "$graphics_mode" in
    cpu) export T1OS_GRAPHICS=cpu ;;
    framebuffer) export T1OS_GRAPHICS=framebuffer ;;
    auto|'') ;;
    *) log "I do not recognize the graphics mode $graphics_mode, so I will select one automatically." ;;
esac

if [ "$debug" = 1 ] && [ "$developer" = 1 ]; then
    export T1OS_DEBUG=1
    export T1OS_DEVELOPER=1
fi
[ "$quiet" = 0 ] || export T1OS_QUIET=1

if [ "$root_mode" = rw ]; then
    boot_id=$("$busybox" cat /proc/sys/kernel/random/boot_id 2>/dev/null)
    boot_status 'I am recording the hardware and kernel handoff information.'
    write_hardware_inventory

    {
        printf 'format=2\n'
        printf 'boot_id=%s\n' "$boot_id"
        printf 'boot_timestamp='
        atreyan_boot_timestamp || printf 'unknown-time-%s\n' "$boot_id"
        printf 'root_spec=%s\n' "$root_spec"
        printf 'root_device=%s\n' "$root_device"
        printf 'root_fstype=%s\n' "$root_fstype"
        printf 'graphics_mode=%s\n' "$graphics_mode"
        printf 'command_line='
        "$busybox" cat /proc/cmdline
        printf 'kernel='
        "$busybox" uname -a
        printf '\n===== kernel ring at init handoff =====\n'
        "$busybox" dmesg
    } >'/mnt/the one/logs/kernel.log' 2>/dev/null || true
fi

if [ "$quiet" = 1 ] && [ -c /dev/tty0 ]; then
    # Clear boot-loader and firmware residue before the window server takes
    # ownership of the display. Diagnostics remain on serial and in the
    # persistent kernel log.
    printf '\033[2J\033[H' >/dev/tty0 2>/dev/null || true
fi

boot_status 'I have prepared the root drive and will now hand control to GODDESS.'
persist_angel_log_to_root || \
    log 'I could not preserve the initial-system transcript on the root drive.'

# Preserve an already-open display descriptor across switch_root.  Opening it
# here avoids depending on a Linux-style /dev hierarchy in the persistent root
# and lets GODDESS mirror diagnostics without broadening the T1OS device ACL.
if [ -c '/mnt/the one/drivers/nodes/tty0' ]; then
    # GODDESS needs a read/write tty descriptor for the terminal attributes and
    # KDSETMODE handoff.  This does not expose the device hierarchy after the
    # root switch; only this already-open descriptor is inherited.
    exec 3<>'/mnt/the one/drivers/nodes/tty0'
    export T1OS_DISPLAY_CONSOLE_FD=3
fi

exec "$busybox" switch_root /mnt \
    '/the one/software/python/bin/python' \
    -B -I \
    '/the one/build/GODDESS/GODDESS.py'
