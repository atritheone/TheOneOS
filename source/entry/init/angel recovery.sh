#!/bin/sh

# Angel's recovery environment. This program is copied into the initramfs and
# deliberately uses only initramfs tools. It must never import Python or execute
# a program from either the installed root or the recovery payload.

angel_recovery_mount=${ANGEL_RECOVERY_MOUNT:-/run/angel-recovery}
angel_esp_mount=${ANGEL_ESP_MOUNT:-/run/angel-esp}
angel_root_mount=${ANGEL_ROOT_MOUNT:-/mnt}
angel_manifest_relative='the one/settings/recovery/files.tsv'
angel_request_relative='T1OS/recovery-request'
angel_journal_relative='T1OS/recovery-state'
angel_log_relative='T1OS/recovery.log'
angel_shutdown_health_relative='T1OS/roothealth-shutdown-request'
angel_recovery_ready=0
angel_root_mounted=0
angel_root_safe=0
angel_reinstall_allowed=0
angel_selected_action=
angel_request_authorization_digest=
angel_request_origin_boot_id=
angel_shutdown_health_action=
angel_shutdown_health_origin_boot_id=
angel_input_console=${ANGEL_INPUT_CONSOLE:-}

angel_select_input_console() {
    [ -z "$angel_input_console" ] || return 0
    if [ -c /dev/tty0 ]; then
        # The boot command line keeps /dev/console on the serial port so boot
        # validation retains its transcript. Recovery is a user-facing CLI,
        # however, so its default input must be the active physical VT.
        angel_input_console=/dev/tty0
        printf '\033[?25h' >/dev/tty0 2>/dev/null || true
    else
        angel_input_console=/dev/console
    fi
}

angel_say() {
    message=$*
    printf '%s%s%s\n' "$angel_prefix" "$message" "$angel_suffix" >/dev/console
    if [ -c /dev/tty0 ]; then
        printf '%s%s%s\n' "$angel_prefix" "$message" "$angel_suffix" \
            >/dev/tty0 2>/dev/null || true
    fi
}

angel_ask() {
    message=$*
    angel_select_input_console
    printf '%s%s%s\n> ' "$angel_prefix" "$message" "$angel_suffix" >/dev/console
    if [ -c /dev/tty0 ]; then
        printf '%s%s%s\n> ' "$angel_prefix" "$message" "$angel_suffix" \
            >/dev/tty0 2>/dev/null || true
    fi
}

angel_answer() {
    angel_select_input_console
    answer=
    IFS= read -r answer <"$angel_input_console" || answer=
    printf '%s' "$answer" | "$busybox" tr '[:upper:]' '[:lower:]' | \
        "$busybox" sed 's/^[[:space:]]*//;s/[[:space:]]*$//'
}

angel_secret_answer() {
    angel_select_input_console
    answer=
    terminal_state=$("$busybox" stty -g <"$angel_input_console" 2>/dev/null || true)
    [ -z "$terminal_state" ] || \
        "$busybox" stty -echo <"$angel_input_console" 2>/dev/null || true
    IFS= read -r answer <"$angel_input_console" || answer=
    [ -z "$terminal_state" ] || \
        "$busybox" stty "$terminal_state" <"$angel_input_console" 2>/dev/null || true
    printf '\n' >/dev/console
    if [ -c /dev/tty0 ]; then printf '\n' >/dev/tty0 2>/dev/null || true; fi
    printf '%s' "$answer" | \
        "$busybox" sed 's/^[[:space:]]*//;s/[[:space:]]*$//'
}

angel_append_log() {
    [ -d "$angel_esp_mount/T1OS" ] || return 0
    printf '%s\n' "$*" >>"$angel_esp_mount/$angel_log_relative" 2>/dev/null || true
}

angel_canonical_relative_path() {
    candidate=$1
    case "$candidate" in
        ''|/*|./*|../*|*/./*|*/../*|*/.|*/..|*//*|*"	"*) return 1 ;;
    esac
    return 0
}

angel_resolve_device() {
    specification=$1
    saved_root_device=${root_device:-}
    root_device=
    if find_device "$specification"; then
        resolved_device=$root_device
        root_device=$saved_root_device
        printf '%s\n' "$resolved_device"
        return 0
    fi
    root_device=$saved_root_device
    return 1
}

angel_mount_esp() {
    if "$busybox" mountpoint -q "$angel_esp_mount"; then
        return 0
    fi
    [ -n "${esp_spec:-}" ] || return 1
    esp_device=$(angel_resolve_device "$esp_spec") || return 1
    "$busybox" mkdir -p "$angel_esp_mount" || return 1
    if ! "$busybox" mount -t vfat \
            -o rw,nodev,nosuid,noexec,umask=0077 \
            "$esp_device" "$angel_esp_mount"; then
        return 1
    fi
    "$busybox" mkdir -p "$angel_esp_mount/T1OS" || return 1
    return 0
}

angel_read_key() {
    key=$1
    file=$2
    [ -f "$file" ] || return 1
    "$busybox" awk -F= -v wanted="$key" \
        '$1 == wanted { value=substr($0, length($1) + 2) } END { if (value != "") print value }' \
        "$file"
}

angel_read_request() {
    request="$angel_esp_mount/$angel_request_relative"
    [ -s "$request" ] || return 1
    [ "$(angel_read_key format "$request")" = 1 ] || return 1
    requested=$(angel_read_key action "$request") || return 1
    case "$requested" in
        python|build|reset|reinstall) angel_selected_action=$requested ;;
        *) return 1 ;;
    esac
    angel_request_origin_boot_id=$(angel_read_key origin_boot_id "$request" 2>/dev/null || true)
    case "$angel_request_origin_boot_id" in
        ????????-????-????-????-????????????) ;;
        *) angel_request_origin_boot_id= ;;
    esac
    case "$angel_request_origin_boot_id" in
        *[!0-9a-f-]*) angel_request_origin_boot_id= ;;
    esac
    angel_request_authorization_digest=$(angel_read_key authorization_digest "$request" 2>/dev/null || true)
    case "$angel_request_authorization_digest" in
        ''|*[!0-9a-f]*) angel_request_authorization_digest= ;;
    esac
    [ "${#angel_request_authorization_digest}" = 64 ] || angel_request_authorization_digest=
    return 0
}

angel_read_shutdown_health_request() {
    request="$angel_esp_mount/$angel_shutdown_health_relative"
    angel_shutdown_health_action=
    angel_shutdown_health_origin_boot_id=
    [ -s "$request" ] || return 1
    [ "$(angel_read_key format "$request")" = 1 ] || return 1
    [ "$(angel_read_key state "$request")" = pending ] || return 1
    requested=$(angel_read_key action "$request") || return 1
    case "$requested" in
        poweroff|restart) ;;
        *) return 1 ;;
    esac
    origin_boot_id=$(angel_read_key origin_boot_id "$request") || return 1
    case "$origin_boot_id" in
        ????????-????-????-????-????????????) ;;
        *) return 1 ;;
    esac
    case "$origin_boot_id" in
        *[!0-9a-f-]*) return 1 ;;
    esac
    angel_shutdown_health_action=$requested
    angel_shutdown_health_origin_boot_id=$origin_boot_id
    return 0
}

angel_clear_shutdown_health_request() {
    "$busybox" rm -f \
        "$angel_esp_mount/$angel_shutdown_health_relative" \
        "$angel_esp_mount/$angel_shutdown_health_relative.new"
    "$busybox" sync
}

angel_journal_write() {
    action=$1
    phase=$2
    journal="$angel_esp_mount/$angel_journal_relative"
    temporary="$journal.new"
    {
        printf 'format=1\n'
        printf 'state=in-progress\n'
        printf 'action=%s\n' "$action"
        printf 'phase=%s\n' "$phase"
        printf 'root=%s\n' "${root_spec:-unknown}"
        printf 'recovery=%s\n' "${recovery_spec:-unknown}"
    } >"$temporary" || return 1
    "$busybox" mv -f "$temporary" "$journal" || return 1
    "$busybox" sync
}

angel_journal_clear() {
    "$busybox" rm -f \
        "$angel_esp_mount/$angel_request_relative" \
        "$angel_esp_mount/$angel_journal_relative" \
        "$angel_esp_mount/$angel_journal_relative.new"
    "$busybox" sync
}

angel_request_clear() {
    "$busybox" rm -f "$angel_esp_mount/$angel_request_relative"
    "$busybox" sync
}

angel_read_journal() {
    journal="$angel_esp_mount/$angel_journal_relative"
    [ -s "$journal" ] || return 1
    [ "$(angel_read_key format "$journal")" = 1 ] || return 1
    [ "$(angel_read_key state "$journal")" = in-progress ] || return 1
    journal_action=$(angel_read_key action "$journal") || return 1
    case "$journal_action" in
        python|build|reset|reinstall) angel_selected_action=$journal_action ;;
        *) return 1 ;;
    esac
    return 0
}

angel_verify_recovery_device() {
    case "${recovery_bytes:-}" in
        ''|*[!0-9]*) return 1 ;;
    esac
    [ "$recovery_bytes" -gt 4096 ] || return 1
    case "${recovery_sha256:-}" in
        *[!0-9a-f]*|'') return 1 ;;
    esac
    [ "${#recovery_sha256}" = 64 ] || return 1

    actual=$(
        "$busybox" head -c "$recovery_bytes" "$recovery_device" 2>/dev/null | \
            "$busybox" sha256sum
    ) || return 1
    actual=${actual%% *}
    [ "$actual" = "$recovery_sha256" ]
}

angel_mount_recovery() {
    [ -n "${recovery_spec:-}" ] || return 1
    angel_say 'I am verifying the independent recovery files.'
    recovery_device=
    if [ "$recovery_spec" = SCAN ]; then
        for candidate in \
            /dev/nvme*n*p* /dev/sd[a-z][0-9]* /dev/vd[a-z][0-9]* \
            /dev/mmcblk*p*; do
            [ -b "$candidate" ] || continue
            recovery_device=$candidate
            if angel_verify_recovery_device; then
                break
            fi
            recovery_device=
        done
    else
        recovery_device=$(angel_resolve_device "$recovery_spec") || return 1
        angel_verify_recovery_device || recovery_device=
    fi
    if [ -z "$recovery_device" ]; then
        angel_say 'I cannot use the recovery files because their identity or contents are not valid.'
        return 1
    fi

    "$busybox" mkdir -p "$angel_recovery_mount" || return 1
    "$busybox" mount -t squashfs -o ro,nodev,nosuid,noexec \
        "$recovery_device" "$angel_recovery_mount" || return 1
    recovery_manifest="$angel_recovery_mount/$angel_manifest_relative"
    [ -s "$recovery_manifest" ] || return 1
    header=$(
        "$busybox" awk -F '\t' 'NR == 1 && $1 == "H" && $2 == "1" { print $1 }' \
            "$recovery_manifest"
    ) || return 1
    [ "$header" = H ] || return 1
    angel_recovery_ready=1
    angel_say 'I verified the independent recovery files.'
    return 0
}

angel_manifest_matches_prefix() {
    path=$1
    prefix=$2
    [ "$path" = "$prefix" ] || [ "${path#"$prefix"/}" != "$path" ]
}

angel_verify_prefix_at() {
    base=$1
    prefix=$2
    manifest="$angel_recovery_mount/$angel_manifest_relative"
    tab=$(printf '\t')
    records=0

    while IFS="$tab" read -r kind relative size digest mode; do
        case "$kind" in
            H) continue ;;
            D|F) ;;
            *) return 1 ;;
        esac
        angel_canonical_relative_path "$relative" || return 1
        angel_manifest_matches_prefix "$relative" "$prefix" || continue
        target="$base/$relative"
        if [ "$kind" = D ]; then
            [ -d "$target" ] && [ ! -L "$target" ] || return 1
        else
            [ -f "$target" ] && [ ! -L "$target" ] || return 1
            [ "$($busybox stat -c '%s' "$target" 2>/dev/null)" = "$size" ] || return 1
            actual=$($busybox sha256sum "$target" 2>/dev/null) || return 1
            [ "${actual%% *}" = "$digest" ] || return 1
        fi
        records=$((records + 1))
    done <"$manifest"

    [ "$records" -gt 0 ]
}

angel_restore_tree() {
    relative=$1
    label=$2
    source_path="$angel_recovery_mount/$relative"
    target_path="$angel_root_mount/$relative"
    parent=${target_path%/*}
    name=${target_path##*/}
    stage="$parent/.$name.angel-new"
    previous="$parent/.$name.angel-previous"

    [ -d "$source_path" ] && [ ! -L "$source_path" ] || return 1
    "$busybox" mkdir -p "$parent" || return 1
    "$busybox" rm -rf "$stage" || return 1
    "$busybox" cp -a "$source_path" "$stage" || return 1
    "$busybox" rm -rf "$previous" || return 1
    if [ -e "$target_path" ]; then
        "$busybox" mv "$target_path" "$previous" || return 1
    fi
    if ! "$busybox" mv "$stage" "$target_path"; then
        [ ! -e "$previous" ] || "$busybox" mv "$previous" "$target_path" || true
        return 1
    fi
    if ! angel_verify_prefix_at "$angel_root_mount" "$relative"; then
        "$busybox" rm -rf "$target_path"
        [ ! -e "$previous" ] || "$busybox" mv "$previous" "$target_path" || true
        return 1
    fi
    "$busybox" rm -rf "$previous"
    angel_append_log "restored=$relative label=$label"
    return 0
}

angel_prepare_writable_root() {
    [ "$angel_root_mounted" = 1 ] || return 1
    [ "$angel_root_safe" = 1 ] || return 1
    if "$busybox" mount -o remount,rw "$angel_root_mount"; then
        root_mode=rw
        return 0
    fi
    return 1
}

angel_repair_python() {
    angel_journal_write python prepare || return 1
    angel_prepare_writable_root || return 1
    angel_say 'I am restoring Python and its managed libraries.'
    for item in \
        'the one/software/python' \
        'the one/catalogue/python' \
        'the one/catalogue/image'; do
        angel_journal_write python "$item" || return 1
        angel_restore_tree "$item" Python || return 1
    done
    angel_say 'I repaired Python and verified every restored file.'
}

angel_repair_build() {
    angel_journal_write build prepare || return 1
    angel_prepare_writable_root || return 1
    angel_say 'I am restoring the build software.'
    angel_restore_tree 'the one/build' 'build software' || return 1
    angel_say 'I reset the build software and verified every restored file.'
}

angel_reset_system() {
    angel_journal_write reset prepare || return 1
    angel_prepare_writable_root || return 1
    angel_say 'I am resetting The One OS while keeping the user files.'
    for item in \
        boot \
        'the one/build' \
        'the one/catalogue' \
        'the one/drivers' \
        'the one/logs' \
        'the one/resources' \
        'the one/settings' \
        'the one/software'; do
        angel_journal_write reset "$item" || return 1
        angel_restore_tree "$item" 'The One OS' || return 1
    done
    "$busybox" rm -rf "$angel_root_mount/.recover"
    "$busybox" mkdir -p \
        "$angel_root_mount/.ephemeral" \
        "$angel_root_mount/.rubbish" \
        "$angel_root_mount/.remainder"
    angel_say 'I reset The One OS and kept the user files.'
}

angel_install_fresh_root() {
    [ "$angel_root_mounted" = 1 ] || return 1
    [ "$angel_root_safe" = 1 ] || return 1
    angel_journal_write reinstall erase || return 1
    angel_prepare_writable_root || return 1
    angel_say 'I am removing the installed files from The One OS root drive.'
    for item in "$angel_root_mount"/* "$angel_root_mount"/.[!.]*; do
        [ -e "$item" ] || continue
        case "${item##*/}" in
            .|..) continue ;;
        esac
        "$busybox" rm -rf "$item" || return 1
    done
    angel_journal_write reinstall install || return 1

    for item in "$angel_recovery_mount"/* "$angel_recovery_mount"/.[!.]*; do
        [ -e "$item" ] || continue
        name=${item##*/}
        case "$name" in .|..|master|.recover|.ephemeral|.rubbish) continue ;; esac
        "$busybox" cp -a "$item" "$angel_root_mount/$name" || return 1
    done
    "$busybox" mkdir -p \
        "$angel_root_mount/.ephemeral" \
        "$angel_root_mount/.rubbish" \
        "$angel_root_mount/.remainder"
    "$busybox" rm -rf \
        "$angel_root_mount/master" \
        "$angel_root_mount/the one/master" \
        "$angel_root_mount/.recover"
    angel_verify_prefix_at "$angel_root_mount" 'the one' || return 1
    angel_say 'I reinstalled The One OS and verified the clean installation.'
}

angel_confirm_action() {
    action=$1
    case "$action" in
        python)
            angel_ask 'Should I repair Python? Answer yes or no.'
            [ "$(angel_answer)" = yes ]
            ;;
        build)
            angel_ask 'Should I reset the build software? Answer yes or no.'
            [ "$(angel_answer)" = yes ]
            ;;
        reset)
            angel_say 'Reset keeps the user files and replaces the operating-system files and settings.'
            angel_ask 'Type reset to continue or no to go back.'
            [ "$(angel_answer)" = reset ]
            ;;
        reinstall)
            angel_say 'Reinstall removes every user file from the root drive.'
            angel_ask 'Type reinstall to continue or no to go back.'
            [ "$(angel_answer)" = reinstall ] || return 1
            angel_ask 'Are you sure? Answer yes or no.'
            [ "$(angel_answer)" = yes ]
            ;;
        *) return 1 ;;
    esac
}

angel_validate_recovery_record() {
    action=$1
    digest=$2
    origin_boot_id=$3
    case "$digest" in
        *[!0-9a-f]*|'') return 1 ;;
    esac
    [ "${#digest}" = 64 ] || return 1

    record="$angel_root_mount/the one/master/recovery authorizations/$digest"
    [ -f "$record" ] && [ ! -L "$record" ] || return 1
    [ "$($busybox stat -c '%a' "$record" 2>/dev/null)" = 600 ] || return 1
    [ "$($busybox stat -c '%s' "$record" 2>/dev/null)" -le 512 ] || return 1
    [ "$(angel_read_key format "$record")" = 2 ] || return 1
    [ "$(angel_read_key action "$record")" = "$action" ] || return 1
    [ "$(angel_read_key origin_boot_id "$record")" = "$origin_boot_id" ] || return 1
    expires=$(angel_read_key expires "$record") || return 1
    case "$expires" in ''|*[!0-9]*) return 1 ;; esac
    now=$($busybox date +%s 2>/dev/null) || return 1
    [ "$expires" -gt "$now" ] || return 1
    [ "$expires" -le $((now + 900)) ] || return 1
    return 0
}

angel_require_recovery_authorization() {
    action=$1
    case "$action" in reset|reinstall) ;; *) return 0 ;; esac

    # Developer images retain an explicit, two-key boot policy. Production
    # images never receive this bypass from t1os.debug alone.
    if [ "${developer:-0}" = 1 ] && [ "${debug:-0}" = 1 ]; then
        angel_say 'Explicit developer policy bypassed destructive-action authorization.'
        return 0
    fi

    [ "$angel_root_mounted" = 1 ] && [ "$angel_root_safe" = 1 ] || {
        angel_say 'I cannot authenticate a destructive action without a verified installed root.'
        return 1
    }

    digest=$angel_request_authorization_digest
    origin_boot_id=$angel_request_origin_boot_id
    current_boot_id=$($busybox cat /proc/sys/kernel/random/boot_id 2>/dev/null) || current_boot_id=
    case "$origin_boot_id" in
        ????????-????-????-????-????????????) ;;
        *) origin_boot_id= ;;
    esac
    case "$origin_boot_id" in *[!0-9a-f-]*) origin_boot_id= ;; esac
    [ -n "$origin_boot_id" ] && [ "$origin_boot_id" != "$current_boot_id" ] || {
        angel_say 'The recovery request is not bound to the preceding boot.'
        return 1
    }
    angel_request_authorization_digest=
    angel_request_origin_boot_id=
    angel_validate_recovery_record "$action" "$digest" "$origin_boot_id" || {
        angel_say 'The recovery authorization is invalid, expired, or for a different action.'
        return 1
    }

    # Consume the digest-named authorization record before any destructive
    # journal or writable operation so a request cannot be replayed.
    record="$angel_root_mount/the one/master/recovery authorizations/$digest"
    if ! "$busybox" mount -o remount,rw "$angel_root_mount" ||
            ! "$busybox" rm -f "$record" ||
            ! "$busybox" sync; then
        angel_say 'I could not consume the recovery authorization safely.'
        return 1
    fi
    root_mode=rw
    return 0
}

angel_finish_action() {
    action=$1
    angel_append_log "completed=$action"
    angel_journal_clear
    "$busybox" sync
    [ "$angel_root_mounted" = 0 ] || "$busybox" mount -o remount,ro "$angel_root_mount" || true
    angel_say 'I will restart The One OS now.'
    "$busybox" reboot -f
}

angel_run_action() {
    action=$1
    angel_confirm_action "$action" || return 0
    angel_require_recovery_authorization "$action" || return 0
    case "$action" in
        python) angel_repair_python ;;
        build) angel_repair_build ;;
        reset) angel_reset_system ;;
        reinstall) angel_install_fresh_root ;;
        *) return 1 ;;
    esac
    if [ "$?" -eq 0 ]; then
        angel_finish_action "$action"
        return 0
    fi
    angel_say 'I could not complete that recovery action. I did not report it as successful.'
    angel_append_log "failed=$action"
    return 1
}

angel_recovery_menu() {
    while :; do
        angel_ask 'Choose python, build, reset, reinstall, restart, or power off.'
        choice=$(angel_answer)
        case "$choice" in
            python|build|reset|reinstall)
                if [ "$angel_recovery_ready" != 1 ]; then
                    angel_say 'I cannot make changes because the independent recovery files are unavailable.'
                elif [ "$choice" != reinstall ] && [ "$angel_root_mounted" != 1 ]; then
                    angel_say 'I cannot use that action because the existing root filesystem is unavailable.'
                elif [ "$choice" = reinstall ] && [ "$angel_reinstall_allowed" != 1 ]; then
                    angel_say 'I cannot reinstall because I could not identify the root filesystem safely.'
                elif [ "$choice" = reinstall ] && { [ "$angel_root_mounted" != 1 ] || [ "$angel_root_safe" != 1 ]; }; then
                    angel_say 'I cannot reinstall because the root filesystem is not safe to change.'
                else
                    angel_run_action "$choice" || true
                fi
                ;;
            restart)
                if [ -s "$angel_esp_mount/$angel_journal_relative" ]; then
                    angel_say 'An interrupted recovery action must finish before I restart.'
                else
                    angel_request_clear
                    angel_say 'I will restart the Terminal.'
                    "$busybox" reboot -f
                fi
                ;;
            'power off'|poweroff|off)
                angel_say 'I will power off the Terminal.'
                "$busybox" poweroff -f
                ;;
            no|'') ;;
            *) angel_say 'I did not recognize that answer.' ;;
        esac
    done
}

angel_recovery_main() {
    angel_root_mounted=${1:-0}
    angel_root_safe=${2:-0}
    quiet=0
    angel_say 'I have entered recovery.'
    if command -v roothealth_recovery_explanation >/dev/null 2>&1; then
        roothealth_recovery_explanation
    fi

    if ! angel_mount_esp; then
        angel_say 'I cannot reach the boot partition, so recovery progress cannot be recorded safely.'
    else
        if angel_read_journal; then
            angel_say 'I found an interrupted recovery action.'
        elif angel_read_request; then
            angel_say 'I found the recovery action selected in Settings.'
        fi
    fi

    angel_mount_recovery || true
    if [ -n "$angel_selected_action" ]; then
        angel_run_action "$angel_selected_action" || true
    fi
    angel_recovery_menu
}
