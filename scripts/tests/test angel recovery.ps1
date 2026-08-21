[CmdletBinding()]
param()

$incrementalTestBootstrap = Join-Path $PSScriptRoot '..\incremental test.ps1'
if (Test-Path -LiteralPath $incrementalTestBootstrap -PathType Leaf) {
    . $incrementalTestBootstrap
    if (Invoke-T1OSIncrementalTestGuard -ScriptPath $PSCommandPath -BoundParameters $PSBoundParameters -UnboundArguments $args) { return }
}
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$engine = Join-Path $projectRoot 'source\entry\init\angel recovery.sh'
$busyboxBinary = Join-Path $projectRoot 'environment\software\initramfs\bin\busybox'

foreach ($required in @($engine, $busyboxBinary)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Angel recovery test input is missing: $required"
    }
}
if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    throw 'Ubuntu WSL is required to test Angel recovery.'
}

$wslEngineOutput = & wsl.exe -d Ubuntu -u root --exec wslpath -a $engine
$wslEngineExitCode = $LASTEXITCODE
$wslEngine = ([string]($wslEngineOutput | Select-Object -First 1)).Trim()
if ($wslEngineExitCode -ne 0 -or -not $wslEngine) {
    throw 'Could not translate the Angel recovery engine path for WSL.'
}
$wslBusyboxOutput = & wsl.exe -d Ubuntu -u root --exec wslpath -a $busyboxBinary
$wslBusyboxExitCode = $LASTEXITCODE
$wslBusybox = ([string]($wslBusyboxOutput | Select-Object -First 1)).Trim()
if ($wslBusyboxExitCode -ne 0 -or -not $wslBusybox) {
    throw 'Could not translate the initramfs BusyBox path for WSL.'
}

$test = @'
set -euo pipefail
trap 'status=$?; printf "Angel recovery test failed at line %s (exit %s): %s\n" "$LINENO" "$status" "$BASH_COMMAND" >&2' ERR
engine=$1
busybox=$2
test -x "$busybox"
work=$(mktemp -d /var/tmp/t1os-angel-recovery.XXXXXX)
cleanup() {
    rm -rf -- "$work"
}
trap cleanup EXIT

recovery="$work/recovery"
root="$work/root"
esp="$work/esp"
mkdir -p "$recovery" "$root" "$esp/T1OS"

for tree in \
    boot \
    'the one/build' \
    'the one/catalogue/audio' \
    'the one/catalogue/graphics' \
    'the one/catalogue/python' \
    'the one/catalogue/image' \
    'the one/catalogue/network' \
    'the one/catalogue/virtualbox' \
    'the one/drivers' \
    'the one/logs' \
    'the one/resources' \
    'the one/settings' \
    'the one/software/audio' \
    'the one/software/chromium' \
    'the one/software/graphics' \
    'the one/software/network' \
    'the one/software/system' \
    'the one/software/virtualbox' \
    'the one/software/python'; do
    mkdir -p "$recovery/$tree"
    printf 'baseline:%s\n' "$tree" >"$recovery/$tree/baseline.txt"
done
mkdir -p "$recovery/the one/settings/recovery"
manifest="$recovery/the one/settings/recovery/files.tsv"
printf 'H\t1\tThe One OS test\ttest-generation\t-\n' >"$manifest"
find "$recovery" -mindepth 1 ! -path "$manifest" -print0 |
    sort -z |
    while IFS= read -r -d '' path; do
        relative=${path#"$recovery"/}
        mode=$(stat -c '%04a' "$path")
        if [ -d "$path" ]; then
            printf 'D\t%s\t0\t-\t%s\n' "$relative" "$mode"
        else
            size=$(stat -c '%s' "$path")
            digest=$(sha256sum "$path")
            digest=${digest%% *}
            printf 'F\t%s\t%s\t%s\t%s\n' "$relative" "$size" "$digest" "$mode"
        fi
    done >>"$manifest"
chmod 0444 "$manifest"

angel_prefix='~ '
angel_suffix=' ~'
find_device() { return 1; }
. "$engine"
angel_recovery_mount=$recovery
angel_root_mount=$root
angel_esp_mount=$esp
angel_root_mounted=1
angel_root_safe=1
angel_root_identity=1
angel_reinstall_allowed=1
angel_recovery_ready=1
angel_say() { :; }
angel_ask() { :; }
angel_append_log() { :; }
angel_journal_write() { :; }
angel_prepare_writable_root() { return 0; }

# The shutdown gate accepts only a complete, canonical one-shot request and
# must clear stale in-memory state after any later invalid read.
shutdown_request="$esp/T1OS/roothealth-shutdown-request"
printf '%s\n' \
    'format=1' \
    'state=pending' \
    'action=poweroff' \
    'origin_boot_id=01234567-89ab-cdef-0123-456789abcdef' \
    >"$shutdown_request"
angel_read_shutdown_health_request
test "$angel_shutdown_health_action" = poweroff
test "$angel_shutdown_health_origin_boot_id" = \
    01234567-89ab-cdef-0123-456789abcdef

sed -i 's/01234567/0123456G/' "$shutdown_request"
if angel_read_shutdown_health_request; then
    echo 'Angel accepted a shutdown request with a malformed boot ID.' >&2
    exit 1
fi
test -z "$angel_shutdown_health_action"
test -z "$angel_shutdown_health_origin_boot_id"

sed -i 's/action=poweroff/action=halt/' "$shutdown_request"
if angel_read_shutdown_health_request; then
    echo 'Angel accepted an unknown shutdown action.' >&2
    exit 1
fi

printf '%s\n' \
    'format=1' \
    'state=pending' \
    'action=restart' \
    'origin_boot_id=01234567-89ab-cdef-0123-456789abcdef' \
    >"$shutdown_request"
angel_read_shutdown_health_request
test "$angel_shutdown_health_action" = restart
angel_clear_shutdown_health_request
test ! -e "$shutdown_request"

# Recovery completion leaves a one-shot GRUB marker. Normal init consumes it
# after GRUB has selected the ordinary OS entry without showing a menu.
angel_arm_normal_boot reset
normal_boot_request="$esp/T1OS/recovery-complete"
grep -Fxq 'format=1' "$normal_boot_request"
grep -Fxq 'state=complete' "$normal_boot_request"
grep -Fxq 'action=reset' "$normal_boot_request"
test "$(stat -c '%a' "$normal_boot_request")" = 600
angel_clear_normal_boot_request
test ! -e "$normal_boot_request"

# The recovery reader must honor its chosen interactive console and normalize
# the short answer without requiring Python or a general shell.
answer_file="$work/answer"
printf '  YeS  \n' >"$answer_file"
angel_input_console="$answer_file"
test "$(angel_answer)" = yes

preserve_users() {
    mkdir -p "$root/master" "$root/software" "$root/the one/master"
    printf 'master-user\n' >"$root/master/user.txt"
    printf 'software-user\n' >"$root/software/user.txt"
    printf 'profile-user\n' >"$root/the one/master/user.txt"
}

preserve_users
for tree in \
    'the one/software/python' \
    'the one/catalogue/python' \
    'the one/catalogue/image' \
    'the one/build'; do
    mkdir -p "$root/$tree"
    printf 'damaged\n' >"$root/$tree/baseline.txt"
done

angel_repair_python
for tree in \
    'the one/software/python' \
    'the one/catalogue/python' \
    'the one/catalogue/image'; do
    diff -r -- "$recovery/$tree" "$root/$tree"
done
grep -Fxq damaged "$root/the one/build/baseline.txt"

angel_repair_build
diff -r -- "$recovery/the one/build" "$root/the one/build"

for tree in \
    boot \
    'the one/build' \
    'the one/catalogue' \
    'the one/drivers' \
    'the one/logs' \
    'the one/resources' \
    'the one/settings' \
    'the one/software'; do
    rm -rf -- "$root/$tree"
    mkdir -p "$root/$tree"
    printf 'damaged\n' >"$root/$tree/damaged.txt"
done
mkdir "$root/.recover"
angel_reset_system
for tree in \
    boot \
    'the one/build' \
    'the one/catalogue' \
    'the one/drivers' \
    'the one/logs' \
    'the one/resources' \
    'the one/settings' \
    'the one/software'; do
    diff -r -- "$recovery/$tree" "$root/$tree"
done
grep -Fxq master-user "$root/master/user.txt"
grep -Fxq software-user "$root/software/user.txt"
grep -Fxq profile-user "$root/the one/master/user.txt"
test ! -e "$root/.recover"

printf 'erase-me\n' >"$root/user-file.txt"
recovery_sha256=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
continuation_digest=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
angel_write_continuation reinstall "$continuation_digest" manual
angel_validate_continuation reinstall "$continuation_digest"
angel_install_fresh_root
test ! -e "$root/user-file.txt"
test ! -e "$root/master"
test ! -e "$root/software"
test ! -e "$root/the one/master"
test ! -e "$root/.recover"
test -d "$root/.ephemeral"
test -d "$root/.rubbish"
test -d "$root/.remainder"
angel_validate_continuation reinstall "$continuation_digest"
rm -f -- "$root/.angel-recovery-authorization"
grep -Fxq 'baseline:boot' "$root/boot/baseline.txt"
angel_verify_prefix_at "$root" 'the one'

# Recovery advice is scoped to the smallest baseline tree which differs.
angel_selection_source=
roothealth_refusal_code=
roothealth_refusal_class=
angel_recovery_generation=test-generation
angel_diagnose_recovery
test -z "$angel_recommended_action"

mkdir "$root/etc"
angel_diagnose_recovery
test -z "$angel_recommended_action"
test "$angel_recommendation_confidence" = unavailable
mkdir -p "$root/the one/master"
printf 'Architect:placeholder\n' >"$root/the one/master/master.txt"
chmod 0600 "$root/the one/master/master.txt"
angel_diagnose_recovery
test "$angel_recommended_action" = reinstall
rm -rf -- "$root/etc" "$root/the one/master"

printf 'unexpected\n' >"$root/the one/software/chromium/unexpected.txt"
angel_diagnose_recovery
test "$angel_recommended_action" = reset
rm -f -- "$root/the one/software/chromium/unexpected.txt"

chmod 0600 "$root/the one/software/python/baseline.txt"
angel_diagnose_recovery
test "$angel_recommended_action" = python
chmod 0644 "$root/the one/software/python/baseline.txt"

printf 'damaged\n' >"$root/the one/software/python/baseline.txt"
angel_diagnose_recovery
test "$angel_recommended_action" = python
angel_restore_tree 'the one/software/python' Python

printf 'damaged\n' >"$root/the one/build/baseline.txt"
angel_diagnose_recovery
test "$angel_recommended_action" = build
angel_restore_tree 'the one/build' 'build software'

printf 'damaged\n' >"$root/the one/drivers/baseline.txt"
angel_diagnose_recovery
test "$angel_recommended_action" = reset
angel_restore_tree 'the one/drivers' 'The One OS'

printf 'damaged\n' >"$root/the one/software/chromium/baseline.txt"
angel_diagnose_recovery
test "$angel_recommended_action" = reset
angel_restore_tree 'the one/software/chromium' Chromium

roothealth_refusal_code=MFT_BITMAP_MISMATCH
roothealth_refusal_class=ambiguous-corruption
angel_selection_source=settings
angel_selected_action=reset
mkdir -p \
    "$esp/T1OS/diagnostics/roothealth-history/boot-1" \
    "$esp/T1OS/diagnostics/roothealth-history/boot-2"
printf 'refusal_code=MFT_BITMAP_MISMATCH\n' \
    >"$esp/T1OS/diagnostics/roothealth-history/boot-1/manifest.env"
printf 'refusal_code=MFT_BITMAP_MISMATCH\n' \
    >"$esp/T1OS/diagnostics/roothealth-history/boot-2/manifest.env"
angel_roothealth_history_summary
test "$angel_roothealth_recurrence" = exact
printf '%s\n' \
    'refusal_code=MFT_BITMAP_MISMATCH' \
    'refusal_fingerprint=cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc' \
    >"$esp/T1OS/diagnostics/roothealth-history/boot-2/manifest.env"
angel_roothealth_history_summary
test "$angel_roothealth_recurrence" = varying
angel_diagnose_recovery
test -z "$angel_recommended_action"
test "$angel_recommendation_confidence" = unavailable
angel_root_safe=0
if angel_action_available reset; then
    echo 'Angel allowed a selected action while RootHealth refused the filesystem.' >&2
    exit 1
fi
angel_root_safe=1
roothealth_refusal_code=
roothealth_refusal_class=
angel_selection_source=
angel_selected_action=

angel_failure_reason='I could not find the root filesystem UUID=test.'
printf 'failure_kind=root-not-found\n' \
    >"$esp/T1OS/diagnostics/roothealth-history/boot-1/manifest.env"
printf 'failure_kind=root-not-found\n' \
    >"$esp/T1OS/diagnostics/roothealth-history/boot-2/manifest.env"
angel_roothealth_history_summary
test "$angel_roothealth_recurrence" = exact
angel_root_safe=0
angel_diagnose_recovery
test -z "$angel_recommended_action"
test "$angel_recommendation_confidence" = unavailable
angel_root_safe=1
angel_failure_reason=

# A failed post-copy verification must put the previous tree back.
rm -rf -- "$root/the one/build"
mkdir -p "$root/the one/build"
printf 'previous-tree\n' >"$root/the one/build/previous.txt"
sed -i '/^F\tthe one\/build\/baseline.txt\t/s/\t[0-9a-f]\{64\}\t/\tffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff\t/' "$manifest"
if angel_restore_tree 'the one/build' 'rollback test'; then
    echo 'Angel accepted a recovery tree with a false manifest digest.' >&2
    exit 1
fi
grep -Fxq previous-tree "$root/the one/build/previous.txt"
test ! -e "$root/the one/build/baseline.txt"

echo 'Angel recovery engine tests passed.'
'@

$test | wsl.exe -d Ubuntu -u root --exec bash -s -- $wslEngine $wslBusybox
if ($LASTEXITCODE -ne 0) {
    throw "Angel recovery engine validation failed with exit code $LASTEXITCODE."
}
