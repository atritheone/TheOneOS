
#!/bin/sh
set -eu

input_tree=${1:?source tree required}
build=${2:?build directory required}
validator_input=${3:?validate-report.py required}

export PYTHONDONTWRITEBYTECODE=1
cc=${CC:-gcc}
validator="$build/validate-report.py"
cp "$validator_input" "$validator"
sha256sum "$validator" > "$build/validate-report.py.sha256"

# Never qualify objects from the mutable/incremental source tree.  Copy the
# complete source, prove distclean removed every prior object/archive, rerun
# Autoconf, configure, and link in that fresh tree.
tree="$build/source-tree"
test ! -e "$tree"
mkdir -m 0755 "$tree"
cp -a "$input_tree/." "$tree/"
(
	cd "$tree"
	make distclean >/dev/null
	if find . -type f \( -name '*.o' -o -name '*.lo' -o -name '*.la' -o \
		-name '*.a' -o -name '*.so' -o -name roothealth \) \
		-print -quit | grep -q .; then
		echo "distclean left a prebuilt link input" >&2
		exit 1
	fi
	autoreconf -fi >/dev/null
	./configure --disable-static --enable-shared \
		CFLAGS="-O2 -g -ffile-prefix-map=$tree=. -fdebug-prefix-map=$tree=." \
		LDFLAGS="-Wl,-Map,$build/roothealth.link.map" >/dev/null
)
common="-DHAVE_CONFIG_H -I$tree -I$tree/src -I$tree/include"
binary="$tree/src/roothealth"

python3 -B "$tree/tests/check_roothealth_format3_literals.py" \
	"$tree/src/roothealth_format3.c"
if grep -Eq 'rh_writer_commit[[:space:]]*\(' \
	"$tree/src/roothealth_repair_main.c"; then
	echo "public orchestration main retains a target commit primitive" >&2
	exit 1
fi
grep -Fq 'int rh_orchestrator_boot_repair(' \
	"$tree/src/roothealth_orchestrator.c"
make -C "$tree/libntfs" libntfs.la >/dev/null
make -C "$tree/src" roothealth >/dev/null

test -x "$binary"

# Bind the tested executable to this clean build and to the release libc ABI.
file "$binary" | grep -q 'ELF 64-bit LSB pie executable, x86-64'
test "$(readelf -W -l "$binary" | awk '$1 == "GNU_STACK" { print $7 }')" = RW
readelf -W -l "$binary" | grep -q 'GNU_RELRO'
readelf -d "$binary" | grep -Eq 'BIND_NOW|Flags:.*NOW'
test "$(readelf -d "$binary" | \
	sed -n 's/.*Shared library: \[\([^]]*\)\].*/\1/p')" = libc.so.6
sha256sum "$binary" > "$build/roothealth.unstripped.sha256"
cp "$binary" "$build/roothealth.stripped"
strip --strip-all "$build/roothealth.stripped"
sha256sum "$build/roothealth.stripped" > "$build/roothealth.stripped.sha256"
objdump -T "$binary" | sed -n 's/.*(\(GLIBC_[0-9.]*\)).*/\1/p' | \
	sort -Vu > "$build/roothealth.glibc-versions"
cat > "$build/roothealth.glibc-versions.expected" <<'EOF'
GLIBC_2.2.5
GLIBC_2.3
GLIBC_2.3.4
GLIBC_2.4
GLIBC_2.7
GLIBC_2.14
GLIBC_2.17
GLIBC_2.25
GLIBC_2.33
GLIBC_2.34
EOF
cmp "$build/roothealth.glibc-versions.expected" \
	"$build/roothealth.glibc-versions"
if objdump -T "$binary" | grep -q '__isoc23_'; then
	echo "roothealth imports an unapproved C23 libc symbol" >&2
	exit 1
fi
python3 -B "$tree/tests/roothealth_link_manifest.py" \
	--tree "$tree" --map "$build/roothealth.link.map" \
	--sources "$build/roothealth-linked-inputs.manifest" \
	--objects "$build/roothealth-linked-objects.tsv"
test "$("$binary" --help | sed -n '1p')" = "roothealth v0.5.2"
test "$("$binary" --version | sed -n '1p')" = \
	"roothealth v0.5.2 (ntfs-next d4f481d)"
if "$binary" --help | grep -Eq -- '--preen|--force|--yes|--auto|--clear-dirty'; then
	echo "roothealth exposed an unqualified repair option" >&2
	exit 1
fi
"$binary" --help | grep -Eq -- '(^|[[:space:]])--preflight([=[:space:]]|$)'
"$binary" --help | grep -Eq -- '(^|[[:space:]])--boot-repair([=[:space:]]|$)'

expect_cli_5()
{
	set +e
	"$@" >"$build/cli.stdout" 2>"$build/cli.stderr"
	status=$?
	set -e
	test "$status" -eq 5
}

expect_cli_5 "$binary" --check --repair --require-t1os-root \
	--expected-serial 0x1122334455667788 \
	--expected-journal-uuid 01234567-89ab-4cde-8fab-0123456789ab \
	--expected-journal-record 64:1 --report "$build/mutual.json" /dev/null
test ! -e "$build/mutual.json"
expect_cli_5 "$binary" --preflight --check --require-t1os-root \
	--expected-serial 0x1122334455667788 \
	--expected-journal-uuid 01234567-89ab-4cde-8fab-0123456789ab \
	--expected-journal-record 64:1 /dev/null
expect_cli_5 "$binary" --boot-repair --repair --require-t1os-root \
	--expected-serial 0x1122334455667788 \
	--expected-journal-uuid 01234567-89ab-4cde-8fab-0123456789ab \
	--expected-journal-record 64:1 /dev/null
expect_cli_5 "$binary" --boot-repair --require-t1os-root \
	--expected-serial 0x1122334455667788 \
	--expected-journal-uuid 01234567-89ab-4cde-8fab-0123456789ab \
	--expected-journal-record 64:1 --report "$build/boot-repair.json" /dev/null
test ! -e "$build/boot-repair.json"
expect_cli_5 "$binary" --preflight --require-t1os-root \
	--expected-serial 0x1122334455667788 \
	--expected-journal-uuid 01234567-89ab-4cde-8fab-0123456789ab \
	--expected-journal-record 64:1 --report "$build/preflight.json" /dev/null
test ! -e "$build/preflight.json"
set +e
"$binary" --preflight --quiet --require-t1os-root \
	--expected-serial 0x1122334455667788 \
	--expected-journal-uuid 01234567-89ab-4cde-8fab-0123456789ab \
	--expected-journal-record 64:1 /dev/null
preflight_io_status=$?
set -e
test "$preflight_io_status" -eq 3
expect_cli_5 "$binary" --check --require-t1os-root \
	--expected-serial 0x1122334455667788 --expected-journal-record 64:1 \
	--report "$build/missing-uuid.json" /dev/null
test ! -e "$build/missing-uuid.json"
expect_cli_5 "$binary" --check --require-t1os-root \
	--expected-serial 0x1122334455667788 \
	--expected-journal-uuid 01234567-89ab-4cde-8fab-0123456789ab \
	--expected-journal-record 23:1 --report "$build/bad-record.json" /dev/null
test ! -e "$build/bad-record.json"
printf sentinel > "$build/existing-report.json"
expect_cli_5 "$binary" --check --require-t1os-root \
	--expected-serial 0x1122334455667788 \
	--expected-journal-uuid 01234567-89ab-4cde-8fab-0123456789ab \
	--expected-journal-record 64:1 --report "$build/existing-report.json" /dev/null
test "$(cat "$build/existing-report.json")" = sentinel

printf '%s\n' "roothealth-cli cases=9 passed=1"

$cc $common -DROOTHEALTH_REPORT_TEST_HOOKS -O1 -g -Wall -Wextra -Werror -fanalyzer \
	"$tree/tests/roothealth_report_test.c" "$tree/src/roothealth_report.c" \
	-o "$build/roothealth-report-test"
"$build/roothealth-report-test"

$cc $common -DROOTHEALTH_REPORT_TEST_HOOKS -O1 -g -Wall -Wextra -Werror \
	-fsanitize=address,undefined -fno-omit-frame-pointer \
	"$tree/tests/roothealth_report_test.c" "$tree/src/roothealth_report.c" \
	-o "$build/roothealth-report-asan"
ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 \
	UBSAN_OPTIONS=halt_on_error=1 "$build/roothealth-report-asan"

for source in roothealth_repair_main roothealth_orchestrator \
	roothealth_format3 roothealth_report; do
	$cc $common -O1 -g -Wall -Wextra -Werror -fanalyzer \
		-Wno-address-of-packed-member -c "$tree/src/$source.c" \
		-o "$build/$source.strict.o"
done

$cc $common -DROOTHEALTH_RESCAN_TEST_HOOKS -O1 -g -Wall -Wextra -Werror \
	-ffunction-sections -fdata-sections -c "$tree/src/roothealth_orchestrator.c" \
	-o "$build/roothealth-orchestrator-protocol.o"
$cc $common -DROOTHEALTH_RESCAN_TEST_HOOKS -O1 -g -Wall -Wextra -Werror \
	-Wl,--gc-sections \
	"$tree/tests/roothealth_rescan_packet_test.c" \
	"$build/roothealth-orchestrator-protocol.o" \
	-o "$build/roothealth-rescan-packet-test"
"$build/roothealth-rescan-packet-test"

$cc $common -DROOTHEALTH_FORMAT3_TEST_HOOKS -O1 -g -Wall -Wextra -Werror -fanalyzer \
	"$tree/tests/roothealth_format3_test.c" \
	"$tree/src/roothealth_format3.c" "$tree/src/roothealth_report.c" \
	"$tree/src/roothealth_hash_stream.c" \
	-o "$build/roothealth-format3-test"

$cc $common -DROOTHEALTH_FORMAT3_TEST_HOOKS -O1 -g -Wall -Wextra -Werror \
	-fsanitize=address,undefined -fno-omit-frame-pointer \
	"$tree/tests/roothealth_format3_test.c" \
	"$tree/src/roothealth_format3.c" "$tree/src/roothealth_report.c" \
	"$tree/src/roothealth_hash_stream.c" \
	-o "$build/roothealth-format3-asan"

: > "$build/device.img"
for state in empty clean replay refused; do
	report="$build/$state.json"
	rm -f "$report"
	"$build/roothealth-format3-test" "$report" "$build/device.img" "$state"
	asan_report="$build/$state.asan.json"
	rm -f "$asan_report"
	ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 \
		UBSAN_OPTIONS=halt_on_error=1 \
		"$build/roothealth-format3-asan" "$asan_report" \
		"$build/device.img" "$state"
	python3 -B - "$report" "$validator" "$state" <<'PY'
import importlib.util
import json
import pathlib
import sys

report_path, validator_path, state = sys.argv[1:]
payload = pathlib.Path(report_path).read_bytes()
report = json.loads(payload)
if report["report_budget"]["written_bytes"] != len(payload):
    raise SystemExit("written_bytes mismatch")
spec = importlib.util.spec_from_file_location("validate_report", validator_path)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)
module.validate_native_log(report["native_log"], f"generated.{state}")
if state == "refused":
    assert report["native_log"]["state"] == "UNSAFE"
    assert report["native_log"]["planned_io_operations"] == 0
elif state == "replay":
    assert report["native_log"]["state"] == "REPLAY_PLANNED"
    assert report["native_log"]["planned_io_operations"] == 4
PY
done

for state in mirror-divergence mirror-unsupported; do
	report="$build/$state.json"
	rm -f "$report"
	"$build/roothealth-format3-test" "$report" "$build/device.img" "$state"
	python3 -B - "$report" "$state" <<'PY'
import json
import sys

report = json.load(open(sys.argv[1], encoding="utf-8"))
state = sys.argv[2]
expected = (
    "MFT_MIRROR_DIVERGENCE"
    if state == "mirror-divergence"
    else "MFT_MIRROR_UNSUPPORTED_LAYOUT"
)
issue = report["issues"][0]
assert issue["code"] == expected
assert issue["pass"] == "mft-mirror"
assert "MFT_MIRROR_QUALIFIED" in issue["failed_predicates"]
assert report["plan"]["operations"] == 0
assert report["commit"]["started"] is False
PY
done

overflow_report="$build/overflow.json"
rm -f "$overflow_report"
"$build/roothealth-format3-test" "$overflow_report" "$build/device.img" overflow
test ! -e "$overflow_report"

test "$(id -u)" -eq 0
command -v losetup >/dev/null
truncate -s 1M "$build/block.img"
before_hash=$(sha256sum "$build/block.img" | cut -d ' ' -f 1)
loop=$(losetup --find --show --read-only "$build/block.img")
cleanup_loop()
{
	losetup -d "$loop" 2>/dev/null || true
}
trap cleanup_loop EXIT HUP INT TERM

for state in empty clean refused; do
	validated_report="$build/validated-$state.json"
	rm -f "$validated_report"
	"$build/roothealth-format3-test" "$validated_report" "$loop" "$state"
	python3 -B "$validator" "$validated_report" --check-state EMPTY \
		--expected-exit 2 \
		--expected-journal-uuid 01234567-89ab-4cde-8fab-0123456789ab \
		--expected-volume-serial 0x1122334455667788 \
		--expected-requested-path "$loop" --expected-resolved-path "$loop" \
		--expected-requested-symlink false
done

# A diagnostic native plan with no bound ID5/ID6 repair/RHTXN evidence is not
# a valid full document, and check mode can never carry REPLAY_PLANNED.
unbound_replay="$build/validated-replay-unbound.json"
rm -f "$unbound_replay"
"$build/roothealth-format3-test" "$unbound_replay" "$loop" replay
set +e
python3 -B "$validator" "$unbound_replay" --check-state EMPTY \
	--expected-exit 2 \
	--expected-journal-uuid 01234567-89ab-4cde-8fab-0123456789ab \
	--expected-volume-serial 0x1122334455667788 \
	--expected-requested-path "$loop" --expected-resolved-path "$loop" \
	--expected-requested-symlink false
unbound_replay_status=$?
set -e
test "$unbound_replay_status" -ne 0

io_report="$build/validated-io.json"
rm -f "$io_report"
"$build/roothealth-format3-test" "$io_report" "$loop" io
python3 -B "$validator" "$io_report" --early-io

wrong_report="$build/validated-wrong.json"
rm -f "$wrong_report"
"$build/roothealth-format3-test" "$wrong_report" "$loop" wrong
python3 -B "$validator" "$wrong_report" --rejection-exit 4 \
	--rejection-wal unchecked \
	--expected-journal-uuid 01234567-89ab-4cde-8fab-0123456789ab \
	--expected-volume-serial 0x1122334455667788 \
	--expected-requested-path "$loop" --expected-resolved-path "$loop" \
	--expected-requested-symlink false

real_check="$build/real-check.json"
rm -f "$real_check"
set +e
"$binary" --check --require-t1os-root \
	--expected-serial 0x1122334455667788 \
	--expected-journal-uuid 01234567-89ab-4cde-8fab-0123456789ab \
	--expected-journal-record 64:1 --report "$real_check" "$loop"
check_status=$?
set -e
test "$check_status" -eq 2
python3 -B - "$real_check" "$validator" <<'PY'
import importlib.util
import json
import pathlib
import sys

report_path, validator_path = sys.argv[1:]
payload = pathlib.Path(report_path).read_bytes()
report = json.loads(payload)
spec = importlib.util.spec_from_file_location("validate_report", validator_path)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)
module.require_exact_fields(report, module.TOP_LEVEL_FIELDS, "report")
module.validate_device(report)
module.validate_identity(report)
module.validate_issues(report)
initial = module.validate_snapshot(report["initial"], "initial")
final = module.validate_snapshot(report["final"], "final")
module.validate_native_log(report["native_log"], "native_log")
module.validate_batch_ledger(report)
module.validate_report_budget(report)
module.wal_object(report)
execution = initial["execution"]
assert report["mode"] == "check" and report["exit_code"] == 2
assert execution["role"] == "INITIAL" and execution["transport"] == "DIRECT"
assert execution["pid"] > 0 and execution["parent_pid"] > 0
assert len(execution["binary_sha256"]) == 64
assert final["execution"] == execution and final["scan_id"] == initial["scan_id"]
assert report["foundation_repairs"] == [] and report["repairs"] == []
assert report["batch_ledger"]["record_count"] == 0
assert report["report_budget"]["written_bytes"] == len(payload)
PY

real_repair="$build/real-repair.json"
rm -f "$real_repair"
set +e
"$binary" --repair --require-t1os-root \
	--expected-serial 0x1122334455667788 \
	--expected-journal-uuid 01234567-89ab-4cde-8fab-0123456789ab \
	--expected-journal-record 64:1 --report "$real_repair" "$loop"
repair_status=$?
set -e
test "$repair_status" -eq 2
python3 -B "$validator" "$real_repair" --rejection-exit 2 \
	--rejection-wal unchecked \
	--expected-journal-uuid 01234567-89ab-4cde-8fab-0123456789ab \
	--expected-volume-serial 0x1122334455667788 \
	--expected-requested-path "$loop" --expected-resolved-path "$loop" \
	--expected-requested-symlink false
after_hash=$(sha256sum "$build/block.img" | cut -d ' ' -f 1)
test "$before_hash" = "$after_hash"

cleanup_loop
trap - EXIT HUP INT TERM

printf '%s\n' \
	"roothealth-format3 native-cases=4 failure-cases=1 full-reports=7 passed=1"
