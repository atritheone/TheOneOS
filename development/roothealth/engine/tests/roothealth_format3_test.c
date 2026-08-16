
#include "config.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#include "roothealth_format3.h"

bool rh_coverage_is_clean(const struct rh_coverage_ledger *ledger)
{
	return ledger && ledger->complete;
}

static int hex_value(unsigned char value)
{
	if (value >= '0' && value <= '9')
		return value - '0';
	if (value >= 'a' && value <= 'f')
		return value - 'a' + 10;
	if (value >= 'A' && value <= 'F')
		return value - 'A' + 10;
	return -1;
}

int rh_uuid_parse(const char *text, unsigned char output[16])
{
	static const unsigned int hyphens[] = { 8, 13, 18, 23 };
	unsigned int source = 0, target = 0, hyphen = 0;

	if (!text || !output || strlen(text) != 36)
		return -1;
	while (source < 36) {
		int high, low;
		if (hyphen < sizeof(hyphens) / sizeof(hyphens[0]) &&
				source == hyphens[hyphen]) {
			if (text[source++] != '-')
				return -1;
			hyphen++;
			continue;
		}
		high = hex_value((unsigned char)text[source++]);
		low = hex_value((unsigned char)text[source++]);
		if (high < 0 || low < 0 || target >= 16)
			return -1;
		output[target++] = (unsigned char)((high << 4) | low);
	}
	return target == 16 ? 0 : -1;
}

const char *rh_public_result(int result)
{
	switch (result) {
	case RH_RESULT_UNSAFE: return "unsafe";
	case RH_RESULT_IO: return "io-error";
	case RH_RESULT_WRONG_ROOT: return "wrong-root";
	default: return "internal-error";
	}
}

static void wal_unknown(struct rh_scan_evidence *scan)
{
	memset(&scan->wal, 0, sizeof(scan->wal));
	scan->wal.present = -1;
	scan->wal.valid = -1;
	scan->wal.recovery_required = -1;
	scan->wal.state = -1;
	scan->wal.transaction_kind = -1;
	scan->wal.max_entry_count = -1;
}

const char *rh_native_state(const struct rh_scan_evidence *scan)
{
	if (!scan->native_log.checked)
		return NULL;
	if (scan->native_refused)
		return "UNSAFE";
	switch (scan->native_log.state) {
	case RH_NATIVE_LOG_EMPTY_T1OS: return "EMPTY_T1OS";
	case RH_NATIVE_LOG_CLEAN_RESTART: return "CLEAN_RESTART";
	case RH_NATIVE_LOG_REPLAY_PLANNED: return "REPLAY_PLANNED";
	default: return "UNSAFE";
	}
}

const char *rh_write_kind_name(enum rh_write_kind kind)
{
	static const char *const names[] = {
		"boot-primary", "boot-backup", "mft-primary", "mft-mirror"
	};
	return kind >= 0 && kind < 4 ? names[kind] : "unsupported";
}

static void base_scan(struct rh_scan_evidence *scan)
{
	memset(scan, 0, sizeof(*scan));
	scan->completed = 1;
	scan->result = RH_RESULT_UNSAFE;
	scan->identity_valid = 1;
	strcpy(scan->scan_id, "11111111-2222-4333-8444-555555555555");
	strcpy(scan->execution.role, "INITIAL");
	strcpy(scan->execution.transport, "DIRECT");
	strcpy(scan->execution.exec_id, "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee");
	memset(scan->execution.binary_sha256, 'a', 64);
	scan->execution.binary_sha256[64] = 0;
	scan->execution.pid = (uint64_t)getpid();
	scan->execution.parent_pid = (uint64_t)getppid();
	scan->identity.prewrite_checked = 1;
	scan->identity.observed_primary_serial = UINT64_C(0x1122334455667788);
	scan->identity.observed_backup_serial = UINT64_C(0x1122334455667788);
	strcpy(scan->identity.observed_label, "T1OS-test");
	strcpy(scan->identity.anchor, "the one");
	scan->wal.checked = 1;
	scan->wal.present = 1;
	scan->wal.valid = 1;
	scan->wal.recovery_required = 0;
	scan->wal.fast_path_trusted = 1;
	scan->wal.ownership_census_complete = 1;
	scan->wal.write_safe = 1;
	scan->wal.state = RH_WAL_EMPTY;
	scan->wal.transaction_kind = RH_WAL_TX_NONE;
	scan->wal.max_entry_count = RH_WAL_MAX_ENTRIES;
	scan->wal.generation = 7;
	strcpy(scan->wal.journal_uuid,
		"01234567-89ab-4cde-8fab-0123456789ab");
	scan->wal.volume_serial = UINT64_C(0x1122334455667788);
}

static void native_case(struct rh_scan_evidence *scan, const char *name)
{
	struct rh_log_result *log = &scan->native_log;
	log->checked = 1;
	log->logfile_bytes = 8192;
	log->pages_expected = 2;
	log->pages_examined = 2;
	if (!strcmp(name, "empty")) {
		log->state = RH_NATIVE_LOG_EMPTY_T1OS;
		log->wiped_pages_scanned = 2;
		scan->logfile_clean_known = 1;
		scan->logfile_clean = 1;
		return;
	}
	log->major_version = 1;
	log->minor_version = 1;
	log->restart_lsn = 100;
	log->synced_lsn = 100;
	log->committed_lsn = 100;
	log->latest_lsn = 100;
	if (!strcmp(name, "clean")) {
		log->state = RH_NATIVE_LOG_CLEAN_RESTART;
		scan->logfile_clean_known = 1;
		scan->logfile_clean = 1;
		return;
	}
	log->state = RH_NATIVE_LOG_REPLAY_PLANNED;
	log->checkpoint_records_examined = 1;
	log->control_records_examined = 1;
	log->mutation_records_examined = 1;
	log->transaction_tables = 1;
	log->actions_seen = 2;
	log->redo_actions = 1;
	log->restart_pages_planned = 2;
	log->planned_io_operations = 4;
	log->planned_io_bytes = 10240;
	scan->logfile_clean_known = 1;
	if (!strcmp(name, "refused")) {
		scan->native_refused = 1;
		log->unsupported_actions = 1;
	}
}

int main(int argc, char **argv)
{
	struct rh_report report;
	struct rh_cli cli;
	struct rh_device_evidence device;
	struct rh_scan_evidence initial;
	struct rh_foundation_evidence foundation;
	struct rh_repair_evidence repair;
	const struct rh_scan_evidence *final;
	int result = RH_RESULT_UNSAFE;

	if (argc != 4)
		return 1;
	memset(&cli, 0, sizeof(cli));
	cli.mode = RH_CLI_CHECK;
	cli.expected_serial = UINT64_C(0x1122334455667788);
	strcpy(cli.expected_uuid_text, "01234567-89ab-4cde-8fab-0123456789ab");
	memset(&device, 0, sizeof(device));
	if (lstat(argv[2], &device.requested_stat) ||
			stat(argv[2], &device.resolved_stat))
		return 2;
	strcpy(device.requested, argv[2]);
	strcpy(device.resolved, argv[2]);
	device.selection_proven = 1;
	base_scan(&initial);
	final = &initial;
	if (!strcmp(argv[3], "io")) {
		cli.mode = RH_CLI_REPAIR;
		initial.completed = 0;
		initial.result = RH_RESULT_IO;
		memset(&initial.identity, 0, sizeof(initial.identity));
		initial.identity_valid = 0;
		memset(&initial.native_log, 0, sizeof(initial.native_log));
		initial.logfile_clean_known = 0;
		wal_unknown(&initial);
		result = RH_RESULT_IO;
		final = NULL;
	} else if (!strcmp(argv[3], "wrong")) {
		cli.mode = RH_CLI_REPAIR;
		initial.result = RH_RESULT_WRONG_ROOT;
		initial.identity_valid = 0;
		memset(&initial.native_log, 0, sizeof(initial.native_log));
		initial.logfile_clean_known = 0;
		wal_unknown(&initial);
		result = RH_RESULT_WRONG_ROOT;
		final = NULL;
	} else if (!strcmp(argv[3], "mirror-divergence") ||
			!strcmp(argv[3], "mirror-unsupported")) {
		cli.mode = RH_CLI_REPAIR;
		memset(&initial.native_log, 0, sizeof(initial.native_log));
		initial.logfile_clean_known = 0;
		initial.mirror.checked = 1;
		initial.mirror.records_checked = 1;
		initial.mirror.failure_record_known = 1;
		initial.mirror.failure_record = 0;
		strcpy(initial.refusal_stage, "mft-mirror");
		if (!strcmp(argv[3], "mirror-divergence")) {
			initial.mirror.ambiguous_records = 1;
			initial.mirror.failure_kind =
				RH_MIRROR_FAILURE_VALID_DIVERGENCE;
			initial.mirror.records[0].checked = 1;
			initial.mirror.records[0].primary_valid = 1;
			initial.mirror.records[0].mirror_valid = 1;
			initial.mirror.records[0].equal_known = 1;
		} else {
			initial.mirror.unsupported_records = 1;
			initial.mirror.failure_kind =
				RH_MIRROR_FAILURE_BOTH_UNSUPPORTED;
			initial.mirror.records[0].checked = 1;
		}
		result = RH_RESULT_UNSAFE;
		final = NULL;
	} else {
		native_case(&initial, argv[3]);
	}
	memset(&foundation, 0, sizeof(foundation));
	memset(&repair, 0, sizeof(repair));
	if (rh_report_prepare(&report, argv[1]))
		return 3;
	if (!strcmp(argv[3], "overflow")) {
		struct stat st;
		if (setenv("ROOTHEALTH_FORMAT3_TEST_FORCE_BUILD_FAILURE", "1", 1) ||
				!rh_format3_publish(&report, &cli, &device, &initial,
					&initial, &foundation, &repair, RH_RESULT_UNSAFE) ||
				!lstat(argv[1], &st))
			return 4;
		return 0;
	}
	if (
			rh_format3_publish(&report, &cli, &device, &initial, final,
				&foundation, &repair, result))
		return 3;
	return 0;
}
