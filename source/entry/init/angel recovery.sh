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
angel_root_identity=0
angel_reinstall_allowed=0
angel_selected_action=
angel_selection_source=
angel_recommended_action=
angel_recommendation_reason=
angel_recommendation_confidence=
angel_recovery_generation=
angel_failure_reason=
angel_roothealth_recurrence=
angel_request_authorization_digest=
angel_request_origin_boot_id=
angel_journal_authorization_digest=
angel_continuation_relative='.angel-recovery-authorization'
angel_authentication_failures=0
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
    printf '%s' "$answer"
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
    # Device discovery writes the shared root-discovery transcript.  Once the
    # ESP has been resolved in this boot, reuse that exact block device instead
    # of replacing the root-drive evidence or waiting through another scan.
    if [ -z "${esp_device:-}" ] || [ ! -b "$esp_device" ]; then
        esp_device=$(angel_resolve_device "$esp_spec") || return 1
    fi
    "$busybox" mkdir -p "$angel_esp_mount" || return 1
    if ! "$busybox" mount -t vfat \
            -o rw,nodev,nosuid,noexec,umask=0077 \
            "$esp_device" "$angel_esp_mount"; then
        return 1
    fi
    "$busybox" mkdir -p "$angel_esp_mount/T1OS" || return 1
    return 0
}

angel_unmount_esp() {
    if ! "$busybox" mountpoint -q "$angel_esp_mount"; then
        return 0
    fi
    "$busybox" sync
    "$busybox" umount "$angel_esp_mount"
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
        python|build|reset|reinstall)
            angel_selected_action=$requested
            angel_selection_source=settings
            ;;
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
        printf 'authorization_digest=%s\n' "${angel_request_authorization_digest:-${angel_journal_authorization_digest:-none}}"
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
        python|build|reset|reinstall)
            angel_selected_action=$journal_action
            angel_selection_source=journal
            ;;
        *) return 1 ;;
    esac
    angel_journal_authorization_digest=$(angel_read_key authorization_digest "$journal" 2>/dev/null || true)
    case "$angel_journal_authorization_digest" in
        *[!0-9a-f]*|'') angel_journal_authorization_digest= ;;
    esac
    [ "${#angel_journal_authorization_digest}" = 64 ] || angel_journal_authorization_digest=
    [ -z "$angel_journal_authorization_digest" ] || \
        angel_request_authorization_digest=$angel_journal_authorization_digest
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
    angel_recovery_generation=$(
        "$busybox" awk -F '\t' 'NR == 1 { print $4; exit }' "$recovery_manifest"
    ) || angel_recovery_generation=
    case "$angel_recovery_generation" in
        *[!0-9a-f]*|'') angel_recovery_generation=unknown ;;
    esac
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
            [ "$($busybox stat -c '%u:%g:%04a' "$target" 2>/dev/null)" = "0:0:$mode" ] || return 1
        else
            [ -f "$target" ] && [ ! -L "$target" ] || return 1
            [ "$($busybox stat -c '%u:%g:%04a:%h' "$target" 2>/dev/null)" = "0:0:$mode:1" ] || return 1
            [ "$($busybox stat -c '%s' "$target" 2>/dev/null)" = "$size" ] || return 1
            actual=$($busybox sha256sum "$target" 2>/dev/null) || return 1
            [ "${actual%% *}" = "$digest" ] || return 1
        fi
        records=$((records + 1))
    done <"$manifest"

    [ "$records" -gt 0 ] || return 1
    # Every baseline entry was verified above.  Equal entry counts also prove
    # that the installed scope contains no unexpected file, directory, link,
    # device, or socket which the immutable manifest did not authorize.
    actual_records=$(
        "$busybox" find "$base/$prefix" -xdev -print 2>/dev/null | \
            "$busybox" awk 'END { print NR }'
    ) || return 1
    expected_records=$records
    if angel_manifest_matches_prefix "$angel_manifest_relative" "$prefix"; then
        installed_manifest="$base/$angel_manifest_relative"
        [ -f "$installed_manifest" ] && [ ! -L "$installed_manifest" ] || return 1
        [ "$($busybox stat -c '%u:%g:%04a:%h' "$installed_manifest" 2>/dev/null)" = '0:0:0444:1' ] || return 1
        "$busybox" cmp -s "$installed_manifest" "$manifest" || return 1
        expected_records=$((expected_records + 1))
    fi
    [ "$actual_records" = "$expected_records" ]
}

angel_valid_root_layout() {
    [ -d "$angel_root_mount/the one" ] || return 1
    for forbidden in bin dev etc home lib lib64 mnt opt proc root run sbin srv sys tmp usr var; do
        [ ! -e "$angel_root_mount/$forbidden" ] || return 1
    done
}

angel_master_credential_available() {
    master_file="$angel_root_mount/the one/master/master.txt"
    [ -f "$master_file" ] && [ ! -L "$master_file" ] || return 1
    [ "$($busybox stat -c '%u:%g:%a:%h' "$master_file" 2>/dev/null)" = '0:0:600:1' ] || return 1
    master_size=$($busybox stat -c '%s' "$master_file" 2>/dev/null) || return 1
    case "$master_size" in ''|*[!0-9]*) return 1 ;; esac
    [ "$master_size" -gt 0 ] && [ "$master_size" -le 4096 ]
}

angel_classify_failure_kind() {
    case "${angel_failure_reason:-}" in
        *'could not find the root filesystem'*|*'could not find the encrypted root container'*)
            printf 'root-not-found\n'
            ;;
        *'could not mount'*root*) printf 'root-mount-failed\n' ;;
        *'not a valid root filesystem'*) printf 'root-layout-invalid\n' ;;
        *'operating-system files that must be recovered'*) printf 'managed-integrity\n' ;;
    esac
}

angel_roothealth_history_summary() {
    history="$angel_esp_mount/T1OS/diagnostics/roothealth-history"
    [ -d "$history" ] || return 0
    current_failure_kind=$(angel_classify_failure_kind)
    current_fingerprint=
    if [ -n "${roothealth_refusal_code:-}" ]; then
        current_fingerprint=$(printf '%s\n%s\n' "$roothealth_refusal_code" \
            "${roothealth_refusal_predicates:-}" | "$busybox" sha256sum) || \
            current_fingerprint=
        current_fingerprint=${current_fingerprint%% *}
    elif [ -z "$current_failure_kind" ]; then
        return 0
    fi
    same=0
    different=0
    for slot in 1 2 3 4 5; do
        history_manifest="$history/boot-$slot/manifest.env"
        [ -s "$history_manifest" ] || continue
        if [ -n "${roothealth_refusal_code:-}" ]; then
            code=$(angel_read_key refusal_code "$history_manifest" 2>/dev/null || true)
            [ -n "$code" ] || continue
            fingerprint=$(angel_read_key refusal_fingerprint "$history_manifest" 2>/dev/null || true)
            case "$fingerprint" in *[!0-9a-f]*|'') fingerprint= ;; esac
            [ "${#fingerprint}" = 64 ] || fingerprint=
            if { [ -n "$fingerprint" ] && [ "$fingerprint" = "$current_fingerprint" ]; } || \
                    { [ -z "$fingerprint" ] && [ "$code" = "$roothealth_refusal_code" ]; }; then
                same=$((same + 1))
            else
                different=$((different + 1))
            fi
        else
            failure_kind=$(angel_read_key failure_kind "$history_manifest" 2>/dev/null || true)
            [ -n "$failure_kind" ] && [ "$failure_kind" != none ] || continue
            if [ "$failure_kind" = "$current_failure_kind" ]; then
                same=$((same + 1))
            else
                different=$((different + 1))
            fi
        fi
    done
    if [ "$same" -ge 2 ] && [ "$different" -eq 0 ]; then
        angel_roothealth_recurrence=exact
        angel_say "The same boot failure evidence appears in $same of the last five captured boots."
    elif [ "$different" -gt 0 ]; then
        angel_roothealth_recurrence=varying
        angel_say 'Recent boot failures vary, which points to storage, connection, power, or nondeterministic evidence rather than one damaged operating-system component.'
    else
        angel_roothealth_recurrence=single
    fi
}

angel_set_recommendation() {
    angel_recommended_action=$1
    angel_recommendation_confidence=$2
    angel_recommendation_reason=$3
}

angel_diagnose_recovery() {
    angel_recommended_action=
    angel_recommendation_confidence=
    angel_recommendation_reason=

    if [ -n "${roothealth_refusal_code:-}" ]; then
        case "${roothealth_refusal_class:-unknown}" in
            io)
                if [ "$angel_roothealth_recurrence" = varying ]; then
                    reason='RootHealth found changing storage I/O evidence across recent boots. Power off and check the drive, connection, and power before changing files.'
                else
                    reason='RootHealth found uncertain storage I/O. Power off and check the drive, connection, and power before changing files.'
                fi
                ;;
            wrong-root)
                reason='The selected root does not match this USB identity. Check the selected drive or boot media; do not copy recovery files to it.'
                ;;
            repairable|recovery-required)
                reason='Filesystem recovery must complete before any operating-system file repair is safe. Resetting Python or The One OS cannot repair NTFS metadata.'
                ;;
            ambiguous-corruption)
                reason='The filesystem evidence is ambiguous. Preserve the drive and diagnostics; no operating-system file recovery is safe.'
                ;;
            timeout|internal)
                reason='RootHealth did not complete its bounded check. Restart once; if this repeats, preserve the diagnostics instead of replacing operating-system files.'
                ;;
            *)
                reason='RootHealth cannot validate this filesystem condition. No operating-system file recovery is safe until the filesystem is admitted.'
                ;;
        esac
        angel_set_recommendation '' unavailable "$reason"
        return 0
    fi

    if [ "$angel_root_safe" != 1 ]; then
        case "$angel_failure_reason" in
            *'could not find the root filesystem'*|*'could not find the encrypted root container'*)
                reason='The root drive was not found. Check the drive, USB identity, connection, and firmware selection; recovery must not write to an unidentified device.'
                ;;
            *) reason='The root filesystem is not safe to change, so I cannot recommend an operating-system file recovery.' ;;
        esac
        angel_set_recommendation '' unavailable "$reason"
        return 0
    fi
    if [ "$angel_root_mounted" != 1 ]; then
        angel_set_recommendation '' unavailable \
            'The root filesystem could not be mounted read-only, so I cannot inspect or change its operating-system files safely.'
        return 0
    fi
    if [ "$angel_root_identity" != 1 ]; then
        angel_set_recommendation '' unavailable \
            'The mounted filesystem has not been proven to be this USB’s T1OS root. I will not recommend writing to it.'
        return 0
    fi
    if [ "$angel_recovery_ready" != 1 ]; then
        angel_set_recommendation '' unavailable \
            'The independent recovery baseline is unavailable, so I cannot compare or restore operating-system components.'
        return 0
    fi

    case "$angel_selection_source" in
        journal)
            angel_set_recommendation "$angel_selected_action" required \
                "An interrupted $angel_selected_action recovery must continue from its recorded transaction."
            return 0
            ;;
        settings)
            angel_set_recommendation "$angel_selected_action" requested \
                "Settings authenticated and requested $angel_selected_action recovery."
            return 0
            ;;
        command-line)
            angel_set_recommendation "$angel_selected_action" requested \
                "The signed recovery boot entry requested $angel_selected_action recovery."
            return 0
            ;;
    esac

    if ! angel_valid_root_layout; then
        if angel_master_credential_available; then
            angel_set_recommendation reinstall high \
                'The identity-bound root is healthy, but it no longer contains a valid The One OS installation. A clean reinstall is the applicable recovery.'
        else
            angel_set_recommendation '' unavailable \
                'The identity-bound root needs a clean reinstall, but its private master credential is unavailable or unsafe. I cannot authenticate destructive recovery; use the trusted deployment workflow to recreate this root.'
        fi
        return 0
    fi

    python_health=healthy
    for prefix in \
        'the one/software/python' \
        'the one/catalogue/python' \
        'the one/catalogue/image'; do
        angel_verify_prefix_at "$angel_root_mount" "$prefix" || python_health=damaged
    done
    build_health=healthy
    boot_health=healthy
    drivers_health=healthy
    resources_health=healthy
    system_health=healthy
    angel_verify_prefix_at "$angel_root_mount" 'the one/build' || build_health=damaged
    angel_verify_prefix_at "$angel_root_mount" boot || boot_health=damaged
    angel_verify_prefix_at "$angel_root_mount" 'the one/drivers' || drivers_health=damaged
    angel_verify_prefix_at "$angel_root_mount" 'the one/resources' || resources_health=damaged
    for prefix in \
        'the one/catalogue/audio' \
        'the one/catalogue/graphics' \
        'the one/catalogue/network' \
        'the one/catalogue/virtualbox' \
        'the one/software/audio' \
        'the one/software/chromium' \
        'the one/software/graphics' \
        'the one/software/network' \
        'the one/software/system' \
        'the one/software/virtualbox'; do
        angel_verify_prefix_at "$angel_root_mount" "$prefix" || system_health=damaged
    done

    if [ "$python_health" = damaged ] && [ "$build_health" = healthy ] && \
            [ "$boot_health" = healthy ] && [ "$drivers_health" = healthy ] && \
            [ "$resources_health" = healthy ] && [ "$system_health" = healthy ]; then
        angel_set_recommendation python high \
            'Only Python or its managed libraries differ from the verified recovery generation. Repair Python is the smallest safe recovery and keeps user files and settings.'
    elif [ "$build_health" = damaged ] && [ "$python_health" = healthy ] && \
            [ "$boot_health" = healthy ] && [ "$drivers_health" = healthy ] && \
            [ "$resources_health" = healthy ] && [ "$system_health" = healthy ]; then
        angel_set_recommendation build high \
            'Only the build software differs from the verified recovery generation. Resetting the build software is the smallest safe recovery.'
    elif [ "$python_health" = damaged ] || [ "$build_health" = damaged ] || \
            [ "$boot_health" = damaged ] || [ "$drivers_health" = damaged ] || \
            [ "$resources_health" = damaged ] || [ "$system_health" = damaged ]; then
        angel_set_recommendation reset high \
            'Several operating-system components, or a component outside the Python and build repair scopes, differ from the verified recovery generation. Reset is the smallest complete recovery and keeps user files.'
    else
        angel_set_recommendation '' none \
            'The verified recovery baseline matches the inspected boot, Python, build, driver, resource, Chromium, graphics, network, audio, system, and virtual-machine components. I cannot justify replacing operating-system files from the available evidence.'
    fi
}

angel_present_recommendation() {
    if [ -n "$angel_recovery_generation" ]; then
        generation_short=$(printf '%.12s' "$angel_recovery_generation")
        angel_say "The verified recovery generation is $generation_short."
    fi
    angel_say "$angel_recommendation_reason"
    if [ -n "$angel_recommended_action" ]; then
        case "$angel_recommended_action" in
            python) effect='It replaces Python and managed libraries while keeping user files and settings.' ;;
            build) effect='It replaces only the build software.' ;;
            reset) effect='It replaces operating-system files, settings, and logs while preserving /master, /software, and /the one/master.' ;;
            reinstall) effect='It removes every user file from the root drive and installs a clean baseline.' ;;
        esac
        angel_say "I recommend $angel_recommended_action recovery. $effect"
    fi
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
    [ "$angel_root_identity" = 1 ] || return 1
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
    [ "$angel_root_identity" = 1 ] || return 1
    angel_journal_write reinstall erase || return 1
    angel_prepare_writable_root || return 1
    angel_say 'I am removing the installed files from The One OS root drive.'
    for item in "$angel_root_mount"/* "$angel_root_mount"/.[!.]*; do
        [ -e "$item" ] || continue
        case "${item##*/}" in
            .|..|.angel-recovery-authorization|.angel-recovery-authorization.new) continue ;;
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
    [ "$($busybox stat -c '%u:%g:%a:%h' "$record" 2>/dev/null)" = '0:0:600:1' ] || return 1
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

angel_continuation_path() {
    printf '%s/%s\n' "$angel_root_mount" "$angel_continuation_relative"
}

angel_validate_continuation() {
    action=$1
    digest=$2
    continuation=$(angel_continuation_path)
    case "$digest" in *[!0-9a-f]*|'') return 1 ;; esac
    [ "${#digest}" = 64 ] || return 1
    [ -f "$continuation" ] && [ ! -L "$continuation" ] || return 1
    [ "$($busybox stat -c '%u:%g:%a:%h' "$continuation" 2>/dev/null)" = '0:0:600:1' ] || return 1
    [ "$($busybox stat -c '%s' "$continuation" 2>/dev/null)" -le 512 ] || return 1
    [ "$(angel_read_key format "$continuation")" = 1 ] || return 1
    [ "$(angel_read_key state "$continuation")" = in-progress ] || return 1
    [ "$(angel_read_key action "$continuation")" = "$action" ] || return 1
    [ "$(angel_read_key digest "$continuation")" = "$digest" ] || return 1
    [ "$(angel_read_key recovery_sha256 "$continuation")" = "${recovery_sha256:-unknown}" ] || return 1
}

angel_write_continuation() {
    action=$1
    digest=$2
    origin_boot_id=$3
    continuation=$(angel_continuation_path)
    temporary="$continuation.new"
    "$busybox" rm -f "$temporary" || return 1
    {
        printf 'format=1\n'
        printf 'state=in-progress\n'
        printf 'action=%s\n' "$action"
        printf 'digest=%s\n' "$digest"
        printf 'origin_boot_id=%s\n' "${origin_boot_id:-manual}"
        printf 'recovery_sha256=%s\n' "${recovery_sha256:-unknown}"
    } >"$temporary" || return 1
    "$busybox" chmod 0600 "$temporary" || return 1
    [ "$($busybox stat -c '%u:%g:%a:%h' "$temporary" 2>/dev/null)" = '0:0:600:1' ] || return 1
    "$busybox" mv -f "$temporary" "$continuation" || return 1
    "$busybox" sync
    angel_validate_continuation "$action" "$digest"
}

angel_manual_recovery_authorization() {
    action=$1
    verifier=/sbin/recoveryauth
    master_file="$angel_root_mount/the one/master/master.txt"
    if [ ! -x "$verifier" ] || [ ! -f "$master_file" ] || [ -L "$master_file" ]; then
        angel_say 'I cannot authenticate this destructive action because the independent recovery authenticator or master credential is unavailable.'
        return 1
    fi
    angel_ask "Enter the current master password to authorize $action recovery."
    password=$(angel_secret_answer)
    if printf '%s\n' "$password" | "$verifier" "$master_file"; then
        password=
        unset password
        angel_authentication_failures=0
        angel_say 'I authenticated the destructive recovery action.'
        return 0
    fi
    password=
    unset password
    angel_authentication_failures=$((angel_authentication_failures + 1))
    delay=$((1 << angel_authentication_failures))
    [ "$delay" -le 30 ] || delay=30
    angel_say "Authentication failed. I will wait $delay seconds before another attempt."
    "$busybox" sleep "$delay"
    return 1
}

angel_new_manual_digest() {
    boot_id=$($busybox cat /proc/sys/kernel/random/boot_id 2>/dev/null || printf unknown)
    created=$($busybox date +%s 2>/dev/null || printf 0)
    digest=$(printf '%s\n%s\n%s\n%s\n' "$boot_id" "$created" "$1" "${recovery_sha256:-unknown}" | \
        "$busybox" sha256sum) || return 1
    printf '%s\n' "${digest%% *}"
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

    [ "$angel_root_mounted" = 1 ] && [ "$angel_root_safe" = 1 ] && \
            [ "$angel_root_identity" = 1 ] || {
        angel_say 'I cannot authenticate a destructive action without a verified installed root.'
        return 1
    }

    digest=$angel_request_authorization_digest
    if [ -z "$digest" ] && [ "$angel_selection_source" = journal ]; then
        continuation=$(angel_continuation_path)
        digest=$(angel_read_key digest "$continuation" 2>/dev/null || true)
    fi
    if angel_validate_continuation "$action" "$digest"; then
        angel_request_authorization_digest=$digest
        angel_journal_authorization_digest=$digest
        angel_say 'I verified the interrupted recovery authorization.'
        return 0
    fi

    origin_boot_id=$angel_request_origin_boot_id
    current_boot_id=$($busybox cat /proc/sys/kernel/random/boot_id 2>/dev/null) || current_boot_id=
    case "$origin_boot_id" in
        ????????-????-????-????-????????????) ;;
        *) origin_boot_id= ;;
    esac
    case "$origin_boot_id" in *[!0-9a-f-]*) origin_boot_id= ;; esac
    authorized_from_settings=0
    if [ -n "$origin_boot_id" ] && [ "$origin_boot_id" != "$current_boot_id" ] && \
            angel_validate_recovery_record "$action" "$digest" "$origin_boot_id"; then
        authorized_from_settings=1
    else
        [ -z "$digest" ] || \
            angel_say 'The Settings authorization is invalid or expired. I can authenticate at the recovery console instead.'
        angel_manual_recovery_authorization "$action" || return 1
        digest=$(angel_new_manual_digest "$action") || return 1
        origin_boot_id=manual
    fi

    "$busybox" mount -o remount,rw "$angel_root_mount" || return 1
    root_mode=rw
    angel_write_continuation "$action" "$digest" "$origin_boot_id" || {
        angel_say 'I could not record resumable destructive recovery authorization safely.'
        return 1
    }
    if [ "$authorized_from_settings" = 1 ]; then
        record="$angel_root_mount/the one/master/recovery authorizations/$digest"
        if ! "$busybox" rm -f "$record" || ! "$busybox" sync; then
            "$busybox" rm -f "$(angel_continuation_path)" 2>/dev/null || true
            angel_say 'I could not consume the Settings recovery authorization safely.'
            return 1
        fi
    fi
    angel_request_authorization_digest=$digest
    angel_journal_authorization_digest=$digest
    angel_request_origin_boot_id=
    angel_journal_write "$action" authorized || {
        angel_say 'I could not record the authorized recovery transaction safely.'
        return 1
    }
    return 0
}

angel_finish_action() {
    action=$1
    case "$action" in
        reset|reinstall)
            [ "$angel_root_mounted" = 1 ] || return 1
            if [ "${root_mode:-ro}" != rw ]; then
                "$busybox" mount -o remount,rw "$angel_root_mount" || return 1
                root_mode=rw
            fi
            "$busybox" rm -f "$(angel_continuation_path)" || return 1
            "$busybox" sync
            ;;
    esac
    angel_append_log "completed=$action"
    angel_journal_clear
    "$busybox" sync
    [ "$angel_root_mounted" = 0 ] || "$busybox" mount -o remount,ro "$angel_root_mount" || true
    angel_say 'I will restart The One OS now.'
    "$busybox" reboot -f
}

angel_action_available() {
    action=$1
    if [ "$angel_recovery_ready" != 1 ]; then
        angel_say 'I cannot make changes because the independent recovery files are unavailable.'
        return 1
    fi
    if [ "$angel_root_mounted" != 1 ]; then
        angel_say 'I cannot use that action because the existing root filesystem is unavailable.'
        return 1
    fi
    if [ "$angel_root_safe" != 1 ]; then
        angel_say 'I cannot use that action because RootHealth has not admitted the root filesystem for writing.'
        return 1
    fi
    if [ "$angel_root_identity" != 1 ]; then
        angel_say 'I cannot use that action because this filesystem has not been proven to be The One OS root.'
        return 1
    fi
    if [ "$action" = reinstall ] && [ "$angel_reinstall_allowed" != 1 ]; then
        angel_say 'I cannot reinstall because I could not identify the root filesystem safely.'
        return 1
    fi
    return 0
}

angel_run_action() {
    action=$1
    angel_action_available "$action" || return 0
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
        if angel_finish_action "$action"; then
            return 0
        fi
        angel_say 'I completed the file operation but could not finalize its recovery journal safely.'
        angel_append_log "finalize-failed=$action"
        return 1
    fi
    angel_say 'I could not complete that recovery action. I did not report it as successful.'
    angel_append_log "failed=$action"
    return 1
}

angel_recovery_menu() {
    while :; do
        if [ -n "$angel_recommended_action" ]; then
            angel_ask 'Choose recommended, python, build, reset, reinstall, restart, or power off.'
        else
            angel_ask 'Choose python, build, reset, reinstall, restart, or power off.'
        fi
        choice=$(angel_answer)
        if [ "$choice" = recommended ] && [ -n "$angel_recommended_action" ]; then
            choice=$angel_recommended_action
        fi
        case "$choice" in
            python|build|reset|reinstall)
                angel_run_action "$choice" || true
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
    angel_root_identity=${3:-0}
    quiet=0
    angel_say 'I have entered recovery.'

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
    if command -v roothealth_recovery_explanation >/dev/null 2>&1; then
        roothealth_recovery_explanation
    fi
    angel_roothealth_history_summary
    angel_diagnose_recovery
    angel_present_recommendation
    if [ -n "$angel_selected_action" ]; then
        angel_run_action "$angel_selected_action" || true
    fi
    angel_recovery_menu
}
