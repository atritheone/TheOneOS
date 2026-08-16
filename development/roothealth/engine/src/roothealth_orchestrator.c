
/* ROOTHEALTH_REPAIR_ROLE(ORCHESTRATOR) ROOTHEALTH_IO_ROLE(REPORT) */
#include "config.h"

#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <getopt.h>
#include <inttypes.h>
#include <limits.h>
#include <poll.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/random.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#include "roothealth_hash_stream.h"
#include "roothealth_orchestrator.h"
#include "roothealth_census_device.h"
#include "roothealth_complete_census.h"
#include "roothealth_dirty.h"
#include "roothealth_namespace_repair.h"
#include "roothealth_overlay.h"
#include "roothealth_policy.h"
#include "roothealth_replay_guard.h"

#define RH_RESCAN_PACKET_VERSION 1U

static const unsigned char rh_rescan_magic[8] = {
	'R', 'H', 'S', 'C', 'A', 'N', 3, 0
};

struct rh_rescan_packet {
	unsigned char magic[8];
	uint32_t version;
	uint32_t size;
	int32_t result;
	int32_t completed;
	int32_t identity_valid;
	int32_t logfile_clean_known;
	int32_t logfile_clean;
	int32_t native_state;
	int32_t dirty_known;
	int32_t dirty;
	int32_t census_available;
	int32_t providers_complete;
	int32_t device_fd_inherited;
	int32_t report_fd_inherited;
	uint64_t pid;
	uint64_t parent_pid;
	uint64_t device_dev;
	uint64_t device_ino;
	uint64_t device_rdev;
	uint64_t device_size;
	struct rh_coverage_ledger coverage;
	uint32_t fixed_results[RH_COMPLETE_CENSUS_FIXED_CHECK_COUNT];
	unsigned char coverage_hash[32];
	char scan_id[37];
	char exec_id[37];
	char binary_sha256[65];
};

static int rh_rescan_semantics_valid(int result, int completed,
		int identity_valid, int logfile_clean_known, int logfile_clean,
		int native_state)
{
	int native_clean = native_state == RH_NATIVE_LOG_CLEAN_RESTART ||
		native_state == RH_NATIVE_LOG_EMPTY_T1OS;

	if ((completed != 0 && completed != 1) ||
			(identity_valid != 0 && identity_valid != 1) ||
			(logfile_clean_known != 0 && logfile_clean_known != 1) ||
			(logfile_clean != 0 && logfile_clean != 1) ||
			(!logfile_clean_known && logfile_clean) ||
			(result != RH_RESULT_OK && result != RH_RESULT_UNSAFE &&
			 result != RH_RESULT_IO && result != RH_RESULT_WRONG_ROOT &&
			 result != RH_RESULT_INTERNAL) ||
			(completed != (result != RH_RESULT_IO &&
			 result != RH_RESULT_INTERNAL)) ||
			(native_state == 0 &&
			 (logfile_clean_known || logfile_clean)) ||
			(native_clean &&
			 (!logfile_clean_known || !logfile_clean)) ||
			((native_state == RH_NATIVE_LOG_REPLAY_PLANNED ||
			  native_state == -1) &&
			 (!logfile_clean_known || logfile_clean)) ||
			native_state < -1 || native_state > RH_NATIVE_LOG_EMPTY_T1OS)
		return 0;

	/* OK is a complete clean attestation, never a partial hint. */
	if (result == RH_RESULT_OK)
		return completed && identity_valid && logfile_clean_known &&
			logfile_clean && native_clean;
	return 1;
}

#ifdef ROOTHEALTH_RESCAN_TEST_HOOKS
int rh_orchestrator_test_rescan_semantics(int result, int completed,
		int identity_valid, int logfile_clean_known, int logfile_clean,
		int native_state)
{
	return rh_rescan_semantics_valid(result, completed, identity_valid,
		logfile_clean_known, logfile_clean, native_state);
}
#endif

const char *rh_public_result(int result)
{
	switch (result) {
	case RH_RESULT_OK: return "clean";
	case RH_RESULT_UNSAFE: return "unsafe";
	case RH_RESULT_IO: return "io-error";
	case RH_RESULT_WRONG_ROOT: return "wrong-root";
	default: return "internal-error";
	}
}

static int rh_result_rank(int result)
{
	switch (result) {
	case RH_RESULT_INTERNAL: return 5;
	case RH_RESULT_IO: return 4;
	case RH_RESULT_UNSAFE: return 3;
	case RH_RESULT_WRONG_ROOT: return 2;
	case RH_RESULT_OK: return 1;
	default: return 5;
	}
}

int rh_result_precedence(int first, int second)
{
	return rh_result_rank(second) > rh_result_rank(first) ? second : first;
}

static void rh_record_refusal(char destination[RH_REFUSAL_STAGE_MAX + 1U],
		int *saved_errno, const char *stage, int error_number)
{
	if (!destination || !saved_errno)
		return;
	if (!stage)
		stage = "unknown";
	strncpy(destination, stage, RH_REFUSAL_STAGE_MAX);
	destination[RH_REFUSAL_STAGE_MAX] = 0;
	*saved_errno = error_number > 0 ? error_number : 0;
}

void rh_cli_usage(FILE *stream)
{
	fprintf(stream,
		"roothealth v%s\n\n"
		"Usage: roothealth (--preflight|--boot-repair) --require-t1os-root "
		"--expected-serial SERIAL --expected-journal-uuid UUID "
		"--expected-journal-record RECORD:SEQUENCE DEVICE\n"
		"       roothealth (--check|--repair) --require-t1os-root "
		"--expected-serial SERIAL --expected-journal-uuid UUID "
		"--expected-journal-record RECORD:SEQUENCE --report NEW DEVICE\n\n"
		"Modes:\n"
		"  --preflight  bounded read-only boot-critical metadata preflight\n"
		"  --boot-repair  bounded boot-critical check and repair\n"
		"  --check   read-only root-health diagnosis\n"
		"  --repair  commit qualified repairs and verify with a fresh rescan\n",
		ROOTHEALTH_REPAIR_VERSION);
}

static int rh_parse_u64(const char *text, uint64_t *value, int base)
{
	char *end = NULL;
	unsigned long long parsed;

	if (!text || !*text || text[0] == '-')
		return -1;
	errno = 0;
	parsed = strtoull(text, &end, base);
	if (errno || !end || *end)
		return -1;
	*value = (uint64_t)parsed;
	return 0;
}

static int rh_parse_serial(const char *text, uint64_t *serial)
{
	const unsigned char *p = (const unsigned char *)text;
	uint64_t value = 0;
	size_t digits = 0;
	unsigned int nibble;

	if (!p || !*p)
		return -1;
	if (p[0] == '0' && (p[1] == 'x' || p[1] == 'X'))
		p += 2;
	for (; *p; p++) {
		if (*p == '-')
			continue;
		if (*p >= '0' && *p <= '9')
			nibble = *p - '0';
		else if (*p >= 'a' && *p <= 'f')
			nibble = *p - 'a' + 10U;
		else if (*p >= 'A' && *p <= 'F')
			nibble = *p - 'A' + 10U;
		else
			return -1;
		if (digits++ >= 16)
			return -1;
		value = (value << 4) | nibble;
	}
	if (digits != 16 || !value)
		return -1;
	*serial = value;
	return 0;
}

static int rh_parse_record(const char *text, uint64_t *record,
		uint16_t *sequence)
{
	char first[32];
	const char *colon;
	uint64_t record_value, sequence_value;
	size_t length;

	if (!text || !(colon = strchr(text, ':')) || strchr(colon + 1, ':'))
		return -1;
	length = (size_t)(colon - text);
	if (!length || length >= sizeof(first))
		return -1;
	memcpy(first, text, length);
	first[length] = 0;
	if (rh_parse_u64(first, &record_value, 0) ||
			rh_parse_u64(colon + 1, &sequence_value, 0) ||
			record_value < 24U || !sequence_value ||
			sequence_value > UINT16_MAX)
		return -1;
	*record = record_value;
	*sequence = (uint16_t)sequence_value;
	return 0;
}

int rh_cli_parse(int argc, char **argv, struct rh_cli *cli)
{
	static const struct option options[] = {
		{ "preflight", no_argument, NULL, 'p' },
		{ "boot-repair", no_argument, NULL, 'b' },
		{ "check", no_argument, NULL, 'c' },
		{ "repair", no_argument, NULL, 'r' },
		{ "require-t1os-root", no_argument, NULL, 'T' },
		{ "expected-serial", required_argument, NULL, 's' },
		{ "expected-journal-uuid", required_argument, NULL, 'u' },
		{ "expected-journal-record", required_argument, NULL, 'R' },
		{ "report", required_argument, NULL, 'J' },
		{ "quiet", no_argument, NULL, 'q' },
		{ "help", no_argument, NULL, 'h' },
		{ "version", no_argument, NULL, 'V' },
		{ "internal-rescan-fd", required_argument, NULL, 1000 },
		{ "internal-parent-report-fd", required_argument, NULL, 1001 },
		{ "internal-expected-st-dev", required_argument, NULL, 1002 },
		{ "internal-expected-st-ino", required_argument, NULL, 1003 },
		{ "internal-expected-st-rdev", required_argument, NULL, 1004 },
		{ "internal-report-st-dev", required_argument, NULL, 1005 },
		{ "internal-report-st-ino", required_argument, NULL, 1006 },
		{ NULL, 0, NULL, 0 }
	};
	uint64_t fd;
	int option, modes = 0, uuid_set = 0;

	memset(cli, 0, sizeof(*cli));
	cli->internal_fd = -1;
	cli->internal_report_fd = -1;
	opterr = 0;
	while ((option = getopt_long(argc, argv, "pbcrTs:u:R:J:qhV",
			options, NULL)) != -1) {
		switch (option) {
		case 'p': cli->mode = RH_CLI_PREFLIGHT; modes++; break;
		case 'b': cli->mode = RH_CLI_BOOT_REPAIR; modes++; break;
		case 'c': cli->mode = RH_CLI_CHECK; modes++; break;
		case 'r': cli->mode = RH_CLI_REPAIR; modes++; break;
		case 'T': cli->require_root = 1; break;
		case 's':
			if (rh_parse_serial(optarg, &cli->expected_serial))
				return -1;
			break;
		case 'u':
			if (rh_uuid_parse(optarg, cli->expected_uuid))
				return -1;
			rh_uuid_format(cli->expected_uuid, cli->expected_uuid_text);
			uuid_set = 1;
			break;
		case 'R':
			if (rh_parse_record(optarg, &cli->expected_record,
					&cli->expected_sequence))
				return -1;
			break;
		case 'J': cli->report_path = optarg; break;
		case 'q': cli->quiet = 1; break;
		case 'h': rh_cli_usage(stdout); exit(0);
		case 'V':
			printf("roothealth v%s (ntfs-next d4f481d)\n",
				ROOTHEALTH_REPAIR_VERSION);
			exit(0);
		case 1000:
			if (rh_parse_u64(optarg, &fd, 10) || fd > INT_MAX)
				return -1;
			cli->internal_fd = (int)fd;
			break;
		case 1001:
			if (rh_parse_u64(optarg, &fd, 10) || fd > INT_MAX)
				return -1;
			cli->internal_report_fd = (int)fd;
			break;
		case 1002:
			if (rh_parse_u64(optarg, &cli->internal_expected_dev, 10))
				return -1;
			break;
		case 1003:
			if (rh_parse_u64(optarg, &cli->internal_expected_ino, 10))
				return -1;
			break;
		case 1004:
			if (rh_parse_u64(optarg, &cli->internal_expected_rdev, 10))
				return -1;
			break;
		case 1005:
			if (rh_parse_u64(optarg, &cli->internal_report_dev, 10))
				return -1;
			break;
		case 1006:
			if (rh_parse_u64(optarg, &cli->internal_report_ino, 10))
				return -1;
			break;
		default: return -1;
		}
	}
	if (modes != 1 || !cli->require_root || !cli->expected_serial ||
			!uuid_set || !cli->expected_record || !cli->expected_sequence ||
			optind + 1 != argc)
		return -1;
	cli->device_path = argv[optind];
	if (cli->internal_fd < 0 && cli->mode != RH_CLI_PREFLIGHT &&
			cli->mode != RH_CLI_BOOT_REPAIR &&
			(!cli->report_path ||
			cli->internal_report_fd >= 0))
		return -1;
	if ((cli->mode == RH_CLI_PREFLIGHT ||
			cli->mode == RH_CLI_BOOT_REPAIR) && (cli->report_path ||
			cli->internal_fd >= 0 || cli->internal_report_fd >= 0))
		return -1;
	if (cli->internal_fd >= 0 &&
			(cli->mode != RH_CLI_CHECK || cli->report_path ||
			 cli->internal_report_fd < 0 || !cli->internal_expected_dev ||
			 !cli->internal_expected_ino || !cli->internal_expected_rdev ||
			 !cli->internal_report_dev || !cli->internal_report_ino))
		return -1;
	return 0;
}

int rh_uuid_text(char output[37])
{
	unsigned char uuid[16];
	ssize_t result;

	do {
		result = getrandom(uuid, sizeof(uuid), 0);
	} while (result < 0 && errno == EINTR);
	if (result != (ssize_t)sizeof(uuid))
		return -1;
	uuid[6] = (unsigned char)((uuid[6] & 0x0fU) | 0x40U);
	uuid[8] = (unsigned char)((uuid[8] & 0x3fU) | 0x80U);
	rh_uuid_format(uuid, output);
	return 0;
}

static void rh_hex(const unsigned char *bytes, size_t length, char *output)
{
	static const char digits[] = "0123456789abcdef";
	size_t i;

	for (i = 0; i < length; i++) {
		output[i * 2] = digits[bytes[i] >> 4];
		output[i * 2 + 1] = digits[bytes[i] & 15U];
	}
	output[length * 2] = 0;
}

static int rh_hash_text_valid(const char *text)
{
	size_t i;
	if (!text || strlen(text) != 64)
		return 0;
	for (i = 0; i < 64; i++)
		if (!((text[i] >= '0' && text[i] <= '9') ||
				(text[i] >= 'a' && text[i] <= 'f')))
			return 0;
	return 1;
}

static int rh_uuid_canonical_v4(const char text[37])
{
	unsigned char parsed[16];
	char canonical[37];

	if (text[36] || text[14] != '4' ||
			!(text[19] == '8' || text[19] == '9' ||
			  text[19] == 'a' || text[19] == 'b') ||
			rh_uuid_parse(text, parsed))
		return 0;
	rh_uuid_format(parsed, canonical);
	return !strcmp(text, canonical);
}

int rh_binary_hash(char output[65])
{
	struct rh_hash_stream stream;
	unsigned char buffer[32768], digest[32];
	int fd;

	fd = open("/proc/self/exe", O_RDONLY | O_CLOEXEC);
	if (fd < 0)
		return -1;
	rh_hash_stream_init(&stream);
	for (;;) {
		ssize_t got = read(fd, buffer, sizeof(buffer));
		if (got < 0) {
			if (errno == EINTR)
				continue;
			close(fd);
			return -1;
		}
		if (!got)
			break;
		if (rh_hash_stream_update(&stream, buffer, (size_t)got)) {
			close(fd);
			return -1;
		}
	}
	if (close(fd) || rh_hash_stream_final(&stream, digest))
		return -1;
	rh_hex(digest, sizeof(digest), output);
	return 0;
}

int rh_device_resolve(const char *path, struct rh_device_evidence *device)
{
	if (!path || path[0] != '/' || strlen(path) >= sizeof(device->requested)) {
		errno = EINVAL;
		return -1;
	}
	memset(device, 0, sizeof(*device));
	strcpy(device->requested, path);
	if (lstat(path, &device->requested_stat))
		return -1;
	device->requested_was_symlink =
		S_ISLNK(device->requested_stat.st_mode);
	if (!realpath(path, device->resolved) ||
			stat(device->resolved, &device->resolved_stat))
		return -1;
#ifndef ROOTHEALTH_REPAIR_TESTING
	if (!S_ISBLK(device->resolved_stat.st_mode)) {
		errno = ENOTBLK;
		return -1;
	}
#else
	if (!S_ISBLK(device->resolved_stat.st_mode) &&
			!S_ISREG(device->resolved_stat.st_mode)) {
		errno = ENOTBLK;
		return -1;
	}
#endif
	return 0;
}

const char *rh_native_state(const struct rh_scan_evidence *scan)
{
	if (!scan->native_log.checked)
		return NULL;
	if (scan->native_refused)
		return "UNSAFE";
	switch (scan->native_log.state) {
	case RH_NATIVE_LOG_CLEAN_RESTART: return "CLEAN_RESTART";
	case RH_NATIVE_LOG_REPLAY_PLANNED: return "REPLAY_PLANNED";
	case RH_NATIVE_LOG_EMPTY_T1OS: return "EMPTY_T1OS";
	default:
		return scan->result == RH_RESULT_IO ? "IO_ERROR" : "UNSAFE";
	}
}

static int rh_native_plan_valid(
		const struct rh_scan_evidence *scan, const struct rh_writer *writer,
		size_t first)
{
	const struct rh_write_operation *a, *b;
	size_t i, native_count;

	if (!scan || !writer || scan->native_log.state !=
			RH_NATIVE_LOG_REPLAY_PLANNED || scan->native_refused ||
		scan->native_log.parse_errors || scan->native_log.unsupported_actions ||
		scan->native_log.restart_pages_planned != 2U ||
		writer->operation_count < first + 2U)
		return 0;
	native_count = writer->operation_count - first;
	if (scan->native_log.planned_io_operations != native_count)
		return 0;
	for (i = 0; i + 2U < native_count; ++i)
		if (writer->operations[first + i].kind != RH_WRITE_LOGFILE_REDO ||
				!rh_write_operation_semantics_valid(
					&writer->operations[first + i], 0))
			return 0;
	if ((native_count == 2U) !=
			(!scan->native_log.mutation_records_examined &&
			 !scan->native_log.redo_actions && !scan->native_log.undo_actions))
		return 0;
	if (native_count == 2U &&
			scan->native_log.checkpoint_records_examined < 1U)
		return 0;
	a = &writer->operations[writer->operation_count - 2U];
	b = &writer->operations[writer->operation_count - 1U];
	if (a->kind != RH_WRITE_LOGFILE_RESTART ||
		b->kind != RH_WRITE_LOGFILE_RESTART ||
		a->length != RH_REPLAY_PAGE_SIZE ||
		b->length != RH_REPLAY_PAGE_SIZE || a->offset == b->offset ||
		a->offset > UINT64_MAX - a->length ||
		b->offset > UINT64_MAX - b->length ||
		!(a->offset + a->length <= b->offset ||
		  b->offset + b->length <= a->offset) ||
		!rh_write_operation_semantics_valid(a, 0) ||
		!rh_write_operation_semantics_valid(b, 0))
		return 0;
	return 1;
}

int rh_orchestrator_scan(const struct rh_cli *cli,
		struct rh_device_evidence *device, struct rh_scan_evidence *scan,
		struct rh_writer *writer, int keep_writer)
{
	struct rh_wal *wal = &scan->wal_handle;
	struct rh_ntfs_overlay dirty_overlay;
	struct rh_volume_dirty_pair dirty_pair;
	struct rh_census_reader census_reader;
	struct rh_complete_census_profile census_profile;
	size_t foundation_count, checkpoint;
	int mounted, result, fast_dirty;
	const char *stage = "initialization";

	memset(scan, 0, sizeof(*scan));
	scan->result = RH_RESULT_INTERNAL;
	scan->wal.present = -1;
	scan->wal.valid = -1;
	scan->wal.recovery_required = -1;
	scan->wal.state = -1;
	scan->wal.transaction_kind = -1;
	scan->wal.max_entry_count = -1;
	scan->wal.journal_mft_bitmap_allocated = -1;
	errno = 0;
	stage = "scan-id";
	if (rh_uuid_text(scan->scan_id)) {
		rh_record_refusal(scan->refusal_stage, &scan->refusal_errno,
			stage, errno);
		return scan->result;
	}
	stage = "writer-open";
	errno = 0;
	if (rh_writer_open(writer, device->resolved)) {
		scan->result = RH_RESULT_IO;
		rh_record_refusal(scan->refusal_stage, &scan->refusal_errno,
			stage, errno);
		return scan->result;
	}
	stage = "device-binding";
	if (writer->device_id != device->resolved_stat.st_dev ||
			writer->inode_id != device->resolved_stat.st_ino) {
		scan->result = RH_RESULT_IO;
		errno = ESTALE;
		goto close;
	}
	/* Preserve the successfully attested selection across every early exit. */
	device->selection_proven = 1;
	device->size = writer->device_size;
	stage = "mounted-state";
	errno = 0;
	mounted = roothealth_refuse_mounted(device->resolved);
	if (mounted > 0) {
		scan->completed = 1;
		scan->result = RH_RESULT_UNSAFE;
		goto close;
	}
	if (mounted < 0) {
		scan->result = RH_RESULT_IO;
		goto close;
	}
	stage = "bootstrap-boot";
	errno = 0;
	result = roothealth_bootstrap_boot_plan(writer, cli->expected_serial,
		ROOTHEALTH_EXPECTED_LABEL_PREFIX, &scan->identity, &scan->boot);
	if (result != RH_RESULT_OK) {
		scan->result = result;
		goto close;
	}
	if (cli->mode == RH_CLI_BOOT_REPAIR && writer->operation_count) {
		scan->foundation_operation_count = writer->operation_count;
		stage = scan->boot.repaired_primary ? "foundation-primary-boot" :
			"foundation-backup-boot";
		scan->completed = 1;
		scan->result = RH_RESULT_UNSAFE;
		goto close;
	}
	/*
	 * A bad primary cannot locate the attested journal before its first
	 * foundation write.  Fail closed rather than repair ahead of identity.
	 */
	if (scan->boot.repaired_primary) {
		stage = "foundation-primary-boot";
		scan->result = RH_RESULT_UNSAFE;
		goto close;
	}
	/*
	 * Normal boot must not be gated by RootHealth's release-specific schema
	 * for all four redundant bootstrap FILE records.  Windows legitimately
	 * evolves those record layouts.  Once both boot sectors bind the selected
	 * device to the expected serial, a valid selected clean LFS restart page,
	 * a clear $Volume dirty flag, and no hibernation image are the complete
	 * boot-critical clean proof.  This path reads only the mount bootstrap,
	 * $Volume and the selected restart pages; it never walks historical log
	 * records and never plans or performs a write.
	 *
	 * If any predicate is absent, retain the existing bounded repair path,
	 * including mirror/WAL/identity validation and qualified recovery.
	 */
	if (cli->mode == RH_CLI_BOOT_REPAIR) {
		stage = "boot-clean-probe";
		errno = 0;
		fast_dirty = -1;
		result = roothealth_boot_clean_probe(device->resolved, writer,
			&scan->native_log, &fast_dirty);
		if (result > 0) {
			scan->identity.prewrite_checked = 1;
			scan->identity.prewrite_valid = 1;
			strcpy(scan->identity.anchor, "boot-serial+clean-ntfs");
			scan->identity_valid = 1;
			scan->dirty_known = 1;
			scan->dirty = 0;
			scan->logfile_clean_known = 1;
			scan->logfile_clean = 1;
			scan->completed = 1;
			scan->result = RH_RESULT_OK;
			goto close;
		}
		if (result < 0) {
			scan->result = RH_RESULT_INTERNAL;
			goto close;
		}
	}
	/* The boot path repairs the four redundant bootstrap FILE records before
	 * asking libntfs to traverse the namespace or locate the private journal. */
	if (cli->mode == RH_CLI_BOOT_REPAIR) {
		stage = "mft-mirror";
		errno = 0;
		result = roothealth_mftmirr_plan(writer, &scan->boot.geometry,
			&scan->mirror);
		if (result != RH_RESULT_OK) {
			scan->result = result;
			goto close;
		}
		scan->foundation_operation_count = writer->operation_count;
		if (scan->foundation_operation_count) {
			scan->completed = 1;
			scan->result = RH_RESULT_UNSAFE;
			goto close;
		}
	}
	stage = "wal-locate";
	errno = 0;
	result = (cli->mode == RH_CLI_PREFLIGHT ||
		cli->mode == RH_CLI_BOOT_REPAIR) ?
		rh_wal_locate_and_validate_bounded(wal, writer,
			cli->expected_serial, cli->expected_uuid, cli->expected_record,
			cli->expected_sequence, &scan->wal) :
		rh_wal_locate_and_validate(wal, writer,
			cli->expected_serial, cli->expected_uuid, cli->expected_record,
			cli->expected_sequence, &scan->wal);
	/*
	 * An APPLYING transaction may have torn one of its own MFT targets, so
	 * the mounted uniqueness census can report an unreadable record before it
	 * can authenticate the WAL.  Permit the raw interrupted locator only for
	 * that no-duplicate shape; semantic recovery still has to rederive every
	 * journaled action from its immutable preimage.
	 */
	if (result != RH_RESULT_OK && keep_writer &&
			cli->mode == RH_CLI_REPAIR &&
			(scan->wal.checked != 1 ||
			 (scan->wal.unreadable_record_count != 0 &&
			  scan->wal.definite_duplicate_count == 0))) {
		int locate_result = result;
		struct rh_wal_observation locate_observation = scan->wal;
		int recovery_result = rh_wal_locate_raw_interrupted_recovery(wal,
			writer, cli->expected_serial, cli->expected_uuid,
			cli->expected_record, cli->expected_sequence, &scan->wal);

		if (recovery_result == RH_RESULT_OK) {
			result = RH_RESULT_OK;
		} else {
			/*
			 * The raw locator is only an interrupted-replay escape hatch.
			 * If it does not authenticate a non-empty transaction, retain the
			 * ordinary locator's diagnosis and observation verbatim.
			 */
			scan->wal = locate_observation;
			result = locate_result;
		}
	}
	if (result != RH_RESULT_OK) {
		scan->result = result;
		goto close;
	}
	scan->wal_handle_valid = 1;
	scan->wal_degraded = wal->degraded_slot != 0;
	if (scan->wal_degraded)
		scan->wal.recovery_required = 1;
	if (scan->wal.valid != 1 || !scan->wal.write_safe) {
		stage = "wal-write-safe";
		scan->result = RH_RESULT_UNSAFE;
		goto close;
	}
	/*
	 * A qualified interrupted transaction may have torn the namespace record
	 * that carries the volume label.  The WAL is bound independently by the
	 * boot serial, journal UUID/record/sequence, complete ownership census and
	 * its authenticated transaction descriptors.  Let repair mode recover that
	 * transaction before requiring namespace identity; the mandatory rescan
	 * after recovery revalidates the label before any new repair can proceed.
	 * Check mode remains fail-closed and performs no recovery writes.
	 */
	if (scan->wal.state != RH_WAL_EMPTY ||
			(!scan->wal_degraded && scan->wal.recovery_required != 0)) {
		stage = "wal-recovery-required";
		scan->completed = 1;
		scan->result = RH_RESULT_UNSAFE;
		if (cli->mode == RH_CLI_REPAIR && keep_writer) {
			rh_record_refusal(scan->refusal_stage, &scan->refusal_errno,
				stage, errno);
			return scan->result;
		}
		goto close;
	}
	stage = "identity";
	errno = 0;
	result = (cli->mode == RH_CLI_PREFLIGHT ||
		cli->mode == RH_CLI_BOOT_REPAIR) ?
		roothealth_verify_namespace_identity_bounded(writer, device->resolved,
			&scan->boot.geometry, cli->expected_serial,
			ROOTHEALTH_EXPECTED_LABEL_PREFIX, &scan->identity) :
		roothealth_verify_namespace_identity(writer, device->resolved,
			&scan->boot.geometry, cli->expected_serial,
			ROOTHEALTH_EXPECTED_LABEL_PREFIX, &scan->identity);
	if (result != RH_RESULT_OK) {
		scan->result = result;
		goto close;
	}
	scan->identity_valid = 1;
	if (scan->wal_degraded) {
		stage = "wal-degraded";
		scan->result = RH_RESULT_UNSAFE;
		if (cli->mode == RH_CLI_REPAIR && keep_writer) {
			rh_record_refusal(scan->refusal_stage, &scan->refusal_errno,
				stage, errno);
			return scan->result;
		}
		goto close;
	}
	if (scan->wal.state != RH_WAL_EMPTY || scan->wal.recovery_required != 0) {
		scan->completed = 1;
		scan->result = RH_RESULT_UNSAFE;
		goto close;
	}
	stage = "mft-mirror";
	errno = 0;
	if (cli->mode != RH_CLI_BOOT_REPAIR) {
		result = roothealth_mftmirr_plan(writer, &scan->boot.geometry,
			&scan->mirror);
		if (result != RH_RESULT_OK) {
			scan->result = result;
			goto close;
		}
	}
	foundation_count = writer->operation_count;
	scan->foundation_operation_count = foundation_count;
	if (foundation_count > RH_FOUNDATION_MAX) {
		scan->result = RH_RESULT_UNSAFE;
		goto close;
	}
	checkpoint = writer->operation_count;
	stage = "native-log";
	errno = 0;
	if (roothealth_log_replay_plan(device->resolved, writer,
			&scan->native_log)) {
		int error = errno;
		scan->result = error == EIO ? RH_RESULT_IO :
			error == ENOMEM || error == EMFILE || error == ENFILE ?
			RH_RESULT_INTERNAL : RH_RESULT_UNSAFE;
		goto close;
	}
	if (writer->operation_count != checkpoint) {
		/* Read-only modes never retain a write plan. */
		if ((!rh_native_plan_valid(scan, writer, checkpoint) ||
			 (cli->mode != RH_CLI_REPAIR &&
			  cli->mode != RH_CLI_BOOT_REPAIR)) &&
				rh_writer_discard_after(writer, checkpoint)) {
			scan->result = RH_RESULT_INTERNAL;
			goto close;
		}
		if (writer->operation_count == checkpoint) {
			scan->native_refused = 1;
			scan->native_log.unsupported_actions++;
			scan->native_log.planned_io_operations = 0;
			scan->native_log.planned_io_bytes = 0;
		}
	}
	scan->completed = 1;
	scan->logfile_clean_known = 1;
	scan->logfile_clean = !scan->native_refused &&
		(scan->native_log.state == RH_NATIVE_LOG_CLEAN_RESTART ||
		 scan->native_log.state == RH_NATIVE_LOG_EMPTY_T1OS);
	/* Foundation direct writes remain closed; qualified metadata uses the WAL. */
	scan->safe_foundation_commit = 0;
	if (cli->mode == RH_CLI_PREFLIGHT ||
			cli->mode == RH_CLI_BOOT_REPAIR) {
		stage = "preflight-dirty";
		if (rh_ntfs_overlay_mount(&dirty_overlay, writer, 0)) {
			scan->result = errno == EIO ? RH_RESULT_IO : RH_RESULT_UNSAFE;
			goto close;
		}
		if (rh_volume_dirty_inspect(dirty_overlay.volume, writer, 0,
				&dirty_pair)) {
			rh_ntfs_overlay_unmount(&dirty_overlay);
			scan->result = errno == EIO ? RH_RESULT_IO : RH_RESULT_UNSAFE;
			goto close;
		}
		scan->dirty_known = 1;
		scan->dirty = dirty_pair.initially_dirty;
		rh_ntfs_overlay_unmount(&dirty_overlay);
		scan->result = !foundation_count && scan->logfile_clean &&
			!scan->dirty ? RH_RESULT_OK : RH_RESULT_UNSAFE;
		goto close;
	}
	memset(&census_profile, 0, sizeof(census_profile));
	census_profile.expected_volume_serial = cli->expected_serial;
	census_profile.roothealth_record = cli->expected_record;
	census_profile.roothealth_sequence = cli->expected_sequence;
	census_profile.require_t1os_identity = 1;
	stage = "complete-census";
	errno = 0;
	if (rh_census_reader_from_writer_prefix(writer, writer->operation_count,
			&census_reader) || rh_complete_census_run(&census_reader,
			&census_profile, 1, &scan->census)) {
		scan->result = errno == EIO ? RH_RESULT_IO : RH_RESULT_UNSAFE;
		goto close;
	}
	scan->census_available = 1;
	stage = "dirty-state";
	errno = 0;
	if (rh_ntfs_overlay_mount(&dirty_overlay, writer, 0)) {
		scan->result = errno == EIO ? RH_RESULT_IO : RH_RESULT_UNSAFE;
		goto close;
	}
	if (rh_volume_dirty_inspect(dirty_overlay.volume, writer, 0,
			&dirty_pair)) {
		rh_ntfs_overlay_unmount(&dirty_overlay);
		scan->result = errno == EIO ? RH_RESULT_IO : RH_RESULT_UNSAFE;
		goto close;
	}
	scan->dirty_known = 1;
	scan->dirty = dirty_pair.initially_dirty;
	rh_ntfs_overlay_unmount(&dirty_overlay);
	scan->result = scan->logfile_clean && !scan->dirty &&
		scan->census.providers_complete &&
		scan->census.coverage.complete &&
		rh_coverage_is_clean(&scan->census.coverage) ? RH_RESULT_OK :
		RH_RESULT_UNSAFE;
	if (scan->result != RH_RESULT_OK)
		stage = scan->dirty ? "volume-dirty" : "coverage-verdict";
	if (keep_writer) {
		if (scan->result != RH_RESULT_OK)
			rh_record_refusal(scan->refusal_stage, &scan->refusal_errno,
				stage, errno);
		return scan->result;
	}
close:
	scan->completed = scan->result != RH_RESULT_IO &&
		scan->result != RH_RESULT_INTERNAL;
	if (scan->result != RH_RESULT_OK)
		rh_record_refusal(scan->refusal_stage, &scan->refusal_errno,
			stage, errno);
	if (keep_writer && cli->mode == RH_CLI_BOOT_REPAIR)
		return scan->result;
	if (scan->wal_handle_valid)
		rh_wal_uninstall_backend(&scan->wal_handle);
	rh_writer_close(writer);
	return scan->result;
}

static void rh_foundation_names(enum rh_write_kind kind,
		const char **source, const char **target, const char **name)
{
	switch (kind) {
	case RH_WRITE_BOOT_PRIMARY:
		*source = "BACKUP"; *target = "PRIMARY"; *name = "$Boot.primary";
		break;
	case RH_WRITE_BOOT_BACKUP:
		*source = "PRIMARY"; *target = "BACKUP"; *name = "$Boot.backup";
		break;
	case RH_WRITE_MFT_PRIMARY:
		*source = "MFT_MIRROR"; *target = "MFT_PRIMARY";
		*name = "$MFT.primary-record";
		break;
	case RH_WRITE_MFT_MIRROR:
		*source = "MFT_PRIMARY"; *target = "MFT_MIRROR";
		*name = "$MFT.mirror-record";
		break;
	default:
		*source = ""; *target = ""; *name = "invalid";
		break;
	}
}

static void rh_put_be32(unsigned char output[4], uint32_t value)
{
	output[0] = (unsigned char)(value >> 24);
	output[1] = (unsigned char)(value >> 16);
	output[2] = (unsigned char)(value >> 8);
	output[3] = (unsigned char)value;
}

static void rh_put_be64(unsigned char output[8], uint64_t value)
{
	size_t i;
	for (i = 0; i < 8; i++)
		output[i] = (unsigned char)(value >> (56U - 8U * i));
}

static void rh_put_le32(unsigned char output[4], uint32_t value)
{
	output[0] = (unsigned char)value;
	output[1] = (unsigned char)(value >> 8);
	output[2] = (unsigned char)(value >> 16);
	output[3] = (unsigned char)(value >> 24);
}

static void rh_put_le64(unsigned char output[8], uint64_t value)
{
	size_t i;
	for (i = 0; i < 8; i++)
		output[i] = (unsigned char)(value >> (8U * i));
}

static int rh_decode_hash(const char text[65], unsigned char output[32])
{
	size_t i;
	for (i = 0; i < 32; i++) {
		unsigned int a, b;
		char high = text[i * 2], low = text[i * 2 + 1];
		a = high >= '0' && high <= '9' ? (unsigned int)(high - '0') :
			high >= 'a' && high <= 'f' ?
				(unsigned int)(high - 'a' + 10) : 16U;
		b = low >= '0' && low <= '9' ? (unsigned int)(low - '0') :
			low >= 'a' && low <= 'f' ?
				(unsigned int)(low - 'a' + 10) : 16U;
		if (a > 15U || b > 15U)
			return -1;
		output[i] = (unsigned char)((a << 4) | b);
	}
	return text[64] ? -1 : 0;
}

static int rh_foundation_hashes(struct rh_foundation_evidence *foundation)
{
	struct rh_hash_stream plan, ledger;
	unsigned char encoded[20], digest[32], hash[32], integer[8];
	size_t i;

	rh_hash_stream_init(&plan);
	rh_hash_stream_init(&ledger);
	if (rh_hash_stream_update(&ledger, "RHREPL3\0", 8))
		return -1;
	rh_put_le32(encoded, 3);
	rh_put_le64(encoded + 4, foundation->count);
	if (rh_hash_stream_update(&ledger, encoded, 12))
		return -1;
	for (i = 0; i < foundation->count; i++) {
		struct rh_foundation_action *action = &foundation->actions[i];
		rh_put_be32(encoded, action->action_id);
		rh_put_be64(encoded + 4, action->offset);
		rh_put_be64(encoded + 12, action->length);
		if (rh_hash_stream_update(&plan, encoded, sizeof(encoded)) ||
				rh_decode_hash(action->before_hash, hash) ||
				rh_hash_stream_update(&plan, hash, sizeof(hash)) ||
				rh_decode_hash(action->after_hash, hash) ||
				rh_hash_stream_update(&plan, hash, sizeof(hash)))
			return -1;
		rh_put_le64(integer, i);
		if (rh_hash_stream_update(&ledger, integer, 8))
			return -1;
		rh_put_le32(encoded, action->action_id);
		rh_put_le64(encoded + 4, action->offset);
		rh_put_le64(encoded + 12, action->length);
		if (rh_hash_stream_update(&ledger, encoded, 20) ||
				rh_decode_hash(action->before_hash, hash) ||
				rh_hash_stream_update(&ledger, hash, 32) ||
				rh_decode_hash(action->after_hash, hash) ||
				rh_hash_stream_update(&ledger, hash, 32))
			return -1;
	}
	if (rh_hash_stream_final(&plan, digest))
		return -1;
	rh_hex(digest, 32, foundation->plan_hash);
	if (rh_hash_stream_final(&ledger, digest))
		return -1;
	rh_hex(digest, 32, foundation->repair_ledger_hash);
	return 0;
}

int rh_orchestrator_capture_foundation(const struct rh_writer *writer,
		struct rh_foundation_evidence *foundation)
{
	size_t i;

	memset(foundation, 0, sizeof(*foundation));
	if (writer->operation_count > RH_FOUNDATION_MAX)
		return -1;
	foundation->count = writer->operation_count;
	foundation->syncs = writer->sync_count;
	foundation->write_boundaries = writer->write_boundaries;
	for (i = 0; i < writer->operation_count; i++) {
		const struct rh_write_operation *source = &writer->operations[i];
		struct rh_foundation_action *target = &foundation->actions[i];
		if (!source->verified || !source->sync_completed ||
				!source->readback_verified || !source->write_boundaries)
			return -1;
		target->ordinal = i;
		target->action_id = RH_WRITE_ACTION_ID(source->kind);
		target->kind = source->kind;
		target->offset = source->offset;
		target->length = source->length;
		strcpy(target->before_hash, source->before_sha256);
		strcpy(target->after_hash, source->after_sha256);
		target->write_boundaries = source->write_boundaries;
		target->sync_ordinal = source->sync_ordinal;
		rh_foundation_names(source->kind, &target->source_peer,
			&target->target_peer, &target->target);
		foundation->bytes += source->length;
	}
	return foundation->count ? rh_foundation_hashes(foundation) : 0;
}

static int rh_repair_ledger_hash(struct rh_repair_transaction_evidence *batch)
{
	struct rh_hash_stream stream;
	unsigned char encoded[28], digest[32], hash[32];
	size_t i;

	rh_hash_stream_init(&stream);
	if (rh_hash_stream_update(&stream, "RHREPL3\0", 8))
		return -1;
	rh_put_le32(encoded, 3);
	rh_put_le64(encoded + 4, batch->action_count);
	if (rh_hash_stream_update(&stream, encoded, 12))
		return -1;
	for (i = 0; i < batch->action_count; i++) {
		const struct rh_repair_action_evidence *action = &batch->actions[i];
		rh_put_le64(encoded, i);
		rh_put_le32(encoded + 8, action->action_id);
		rh_put_le64(encoded + 12, action->offset);
		rh_put_le64(encoded + 20, action->length);
		if (rh_hash_stream_update(&stream, encoded, sizeof(encoded)) ||
				rh_decode_hash(action->before_hash, hash) ||
				rh_hash_stream_update(&stream, hash, sizeof(hash)) ||
				rh_decode_hash(action->after_hash, hash) ||
				rh_hash_stream_update(&stream, hash, sizeof(hash)))
			return -1;
	}
	if (rh_hash_stream_final(&stream, digest))
		return -1;
	rh_hex(digest, sizeof(digest), batch->repair_ledger_hash);
	return 0;
}

static int rh_capture_wal_transaction(struct rh_repair_evidence *repair,
		const struct rh_wal *wal, const struct rh_writer *writer,
		enum rh_wal_transaction_kind kind)
{
	struct rh_repair_transaction_evidence *batch;
	size_t i;

	if (!repair || !wal || !writer || wal->state != RH_WAL_COMMITTED ||
			repair->transaction_count >= RH_REPAIR_TRANSACTION_MAX ||
			wal->planned_count != writer->operation_count || !wal->planned_count) {
		errno = EINVAL;
		return -1;
	}
	batch = &repair->transactions[repair->transaction_count];
	memset(batch, 0, sizeof(*batch));
	batch->actions = calloc(wal->planned_count, sizeof(*batch->actions));
	if (!batch->actions)
		return -1;
	batch->origin = RH_REPAIR_ORIGIN_NEW;
	batch->kind = kind;
	batch->initial_state = RH_WAL_PREPARING;
	batch->action_count = wal->planned_count;
	rh_uuid_format(wal->transaction_uuid, batch->transaction_uuid);
	rh_hex(wal->plan_hash, sizeof(wal->plan_hash), batch->plan_hash);
	for (i = 0; i < batch->action_count; i++) {
		struct rh_wal_committed_entry entry;
		struct rh_repair_action_evidence *action = &batch->actions[i];
		const struct rh_write_operation *operation = &writer->operations[i];

		if (rh_wal_committed_entry_at(wal, i, &entry) ||
				entry.action_id != RH_WRITE_ACTION_ID(operation->kind) ||
				!operation->verified || !operation->sync_completed ||
				!operation->readback_verified || !operation->write_boundaries)
			return -1;
		action->ordinal = repair->action_count + i;
		action->action_id = entry.action_id;
		action->kind = operation->kind;
		action->offset = entry.target_offset;
		action->length = entry.length;
		rh_hex(entry.before_hash, sizeof(entry.before_hash),
			action->before_hash);
		rh_hex(entry.after_hash, sizeof(entry.after_hash), action->after_hash);
		action->write_boundaries = operation->write_boundaries;
		action->verified = 1;
		batch->target_bytes += entry.length;
		batch->write_boundaries += operation->write_boundaries;
	}
	batch->syncs = batch->action_count;
	batch->last_verified_ordinal = writer->last_verified_ordinal;
	batch->commit_started = writer->commit_started;
	batch->commit_completed = writer->commit_completed;
	if (!batch->commit_started || !batch->commit_completed ||
			batch->last_verified_ordinal != batch->action_count ||
			rh_repair_ledger_hash(batch))
		return -1;
	repair->transaction_count++;
	repair->action_count += batch->action_count;
	repair->target_bytes += batch->target_bytes;
	repair->syncs += batch->syncs;
	repair->write_boundaries += batch->write_boundaries;
	return 0;
}

static int rh_capture_wal_trace(struct rh_repair_evidence *repair,
		const struct rh_wal *wal, size_t transaction_ordinal, size_t first)
{
	size_t total = rh_wal_trace_action_count(wal), count, i, required;
	struct rh_wal_action_evidence *grown;

	if (!repair || first > total ||
			(transaction_ordinal != SIZE_MAX &&
			 transaction_ordinal >= repair->transaction_count) ||
			total - first > SIZE_MAX - repair->wal_action_count) {
		errno = EINVAL;
		return -1;
	}
	count = total - first;
	required = repair->wal_action_count + count;
	if (required > repair->wal_action_capacity) {
		if (required > SIZE_MAX / sizeof(*grown)) {
			errno = EOVERFLOW;
			return -1;
		}
		grown = realloc(repair->wal_actions, required * sizeof(*grown));
		if (!grown)
			return -1;
		repair->wal_actions = grown;
		repair->wal_action_capacity = required;
	}
	for (i = 0; i < count; i++) {
		struct rh_wal_trace_action source;
		struct rh_wal_action_evidence *target =
			&repair->wal_actions[repair->wal_action_count + i];

		if (rh_wal_trace_action_at(wal, first + i, &source) ||
				(transaction_ordinal == SIZE_MAX && source.kind !=
				 RH_WAL_TRACE_SUPERBLOCK_RECONSTRUCT))
			return -1;
		memset(target, 0, sizeof(*target));
		target->ordinal = repair->wal_action_count + i;
		target->kind = source.kind;
		target->extent_offset = source.extent_offset;
		target->length = source.length;
		target->slot = source.slot;
		target->transaction_ordinal = transaction_ordinal;
		rh_uuid_format(source.transaction_uuid, target->transaction_uuid);
		target->from_state = source.from_state;
		target->to_state = source.to_state;
		rh_hex(source.before_hash, sizeof(source.before_hash),
			target->before_hash);
		rh_hex(source.after_hash, sizeof(source.after_hash),
			target->after_hash);
		target->sync_ordinal = source.sync_ordinal;
		target->write_boundaries = source.write_boundaries;
		repair->wal_bytes += source.length;
		repair->wal_syncs++;
		repair->wal_write_boundaries += source.write_boundaries;
	}
	repair->wal_action_count = required;
	return 0;
}

int rh_orchestrator_reconstruct_degraded(struct rh_scan_evidence *initial,
		struct rh_writer *writer, struct rh_repair_evidence *repair)
{
	struct rh_wal *wal;

	if (!initial || !writer || !repair || !initial->wal_handle_valid ||
			initial->wal.valid != 1 || !initial->wal.write_safe ||
			!initial->wal_degraded) {
		errno = EINVAL;
		return RH_RESULT_UNSAFE;
	}
	wal = &initial->wal_handle;
	if (rh_wal_reconstruct_degraded(wal))
		return errno == EIO ? RH_RESULT_IO : RH_RESULT_UNSAFE;
	if (rh_capture_wal_trace(repair, wal, SIZE_MAX, 0))
		return errno == EIO ? RH_RESULT_IO : RH_RESULT_UNSAFE;
	initial->wal_degraded = 0;
	return RH_RESULT_OK;
}

static int rh_recovery_bitmap_chain_state(
		const struct rh_wal_committed_entry *entries, size_t count,
		size_t ordinal, const unsigned char current_hash[32],
		int *is_old, int *is_new)
{
	const struct rh_wal_committed_entry *entry;
	unsigned char previous_hash[32];
	size_t i, chain_count = 0, position = 0, applied_count = 0;
	size_t matched_applied_count = 0;
	unsigned int matches = 0;

	if (!entries || ordinal >= count || !current_hash || !is_old || !is_new)
		return -1;
	entry = &entries[ordinal];
	if (entry->target.semantic_target_length != 1U ||
			entry->target.semantic_target_offset < entry->target_offset ||
			entry->target.semantic_target_offset >=
				entry->target_offset + entry->length ||
			(entry->action_id != RH_WRITE_ACTION_ID(RH_WRITE_BITMAP_MFT) &&
			 entry->action_id !=
				RH_WRITE_ACTION_ID(RH_WRITE_BITMAP_CLUSTER)))
		return 0;
	for (i = 0; i < count; i++) {
		if (entries[i].target_offset != entry->target_offset ||
				entries[i].length != entry->length)
			continue;
		if (entries[i].action_id != entry->action_id) {
			errno = EIO;
			return -1;
		}
		if (i == ordinal)
			position = chain_count;
		chain_count++;
	}
	if (chain_count < 2U)
		return 0;
	/*
	 * Multiple one-bit corrections can target the same bitmap byte.  The WAL
	 * seals them as an exact before/after chain.  Classify the durable byte at
	 * a chain boundary so a later correction proves every predecessor was
	 * applied; this preserves the global leading-prefix recovery rule.
	 */
	for (i = 0; i < count; i++) {
		if (entries[i].target_offset != entry->target_offset ||
				entries[i].length != entry->length)
			continue;
		if (!applied_count) {
			memcpy(previous_hash, entries[i].before_hash, 32U);
			if (!memcmp(current_hash, previous_hash, 32U)) {
				matches++;
				matched_applied_count = 0;
			}
		} else if (memcmp(previous_hash, entries[i].before_hash, 32U)) {
			errno = EIO;
			return -1;
		}
		memcpy(previous_hash, entries[i].after_hash, 32U);
		applied_count++;
		if (!memcmp(current_hash, previous_hash, 32U)) {
			matches++;
			matched_applied_count = applied_count;
		}
	}
	if (matches != 1U) {
		errno = EIO;
		return -1;
	}
	*is_new = position < matched_applied_count;
	*is_old = !*is_new;
	return 1;
}

static int rh_capture_recovered_begin(struct rh_repair_evidence *repair,
		struct rh_wal *wal, struct rh_writer *writer,
		struct rh_repair_transaction_evidence **output)
{
	struct rh_wal_committed_entry *entries = NULL;
	struct rh_repair_transaction_evidence *batch;
	size_t count = 0, i;
	int saw_old = 0;

	if (!repair || !wal || !writer || !output || wal->state == RH_WAL_EMPTY ||
			repair->transaction_count >= RH_REPAIR_TRANSACTION_MAX ||
			(wal->transaction_kind != RH_WAL_TX_METADATA_REPAIR &&
			 wal->transaction_kind != RH_WAL_TX_DIRTY_CLEAR) ||
			rh_wal_recovery_entries(wal, &entries, &count))
		return -1;
	if (wal->state == RH_WAL_PREPARING && count != 0) {
		free(entries);
		errno = EIO;
		return -1;
	}
	batch = &repair->transactions[repair->transaction_count];
	memset(batch, 0, sizeof(*batch));
	if (count) {
		batch->actions = calloc(count, sizeof(*batch->actions));
		if (!batch->actions) {
			free(entries);
			return -1;
		}
	}
	batch->origin = wal->state == RH_WAL_COMMITTED ?
		RH_REPAIR_ORIGIN_RECOVERED_COMMITTED :
		RH_REPAIR_ORIGIN_RECOVERED_ROLLED_BACK;
	batch->kind = wal->transaction_kind;
	batch->initial_state = wal->state;
	batch->action_count = count;
	rh_uuid_format(wal->transaction_uuid, batch->transaction_uuid);
	rh_hex(wal->plan_hash, sizeof(wal->plan_hash), batch->plan_hash);
	for (i = 0; i < count; i++) {
		struct rh_repair_action_evidence *action = &batch->actions[i];
		unsigned char *current = malloc((size_t)entries[i].length);
		unsigned char digest[32];
		int chain_state, is_old, is_new;

		if (!current || entries[i].action_id == 0 ||
				entries[i].action_id > RH_WRITE_KIND_COUNT ||
				rh_writer_staged_read(writer, 0, entries[i].target_offset,
					(size_t)entries[i].length, current)) {
			free(current);
			free(entries);
			return -1;
		}
		rh_sha256(current, (size_t)entries[i].length, digest);
		free(current);
		is_old = !memcmp(digest, entries[i].before_hash, 32U);
		is_new = !memcmp(digest, entries[i].after_hash, 32U);
		chain_state = rh_recovery_bitmap_chain_state(entries, count, i,
			digest, &is_old, &is_new);
		if (chain_state < 0) {
			free(entries);
			return -1;
		}
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
		fprintf(stderr, "recovery capture i=%zu action=%u off=%"PRIu64
			" len=%"PRIu64" chain=%d old=%d new=%d saw_old=%d\n", i,
			entries[i].action_id, entries[i].target_offset,
			entries[i].length, chain_state, is_old, is_new, saw_old);
#endif
		/*
		 * COMMITTED targets must match the sealed after-image exactly.  An
		 * APPLYING target may instead contain a torn physical write; its durable
		 * undo payload is authoritative and rollback will restore it.  The only
		 * permitted interrupted shape is a leading touched prefix (complete or
		 * torn) followed by untouched old images.  A new image after an old or
		 * torn entry would contradict the writer's per-operation fsync order.
		 */
		if ((wal->state == RH_WAL_COMMITTED && !is_new) ||
				(is_new && saw_old)) {
			free(entries);
			errno = EIO;
			return -1;
		}
		if (is_old)
			saw_old = 1;
		else {
			batch->last_verified_ordinal++;
			if (!is_new)
				saw_old = 1;
		}
		action->action_id = entries[i].action_id;
		action->kind = (enum rh_write_kind)(entries[i].action_id - 1U);
		action->offset = entries[i].target_offset;
		action->length = entries[i].length;
		rh_hex(entries[i].before_hash, 32U, action->before_hash);
		rh_hex(entries[i].after_hash, 32U, action->after_hash);
		action->verified = 1;
		batch->target_bytes += entries[i].length;
	}
	free(entries);
	if (batch->origin == RH_REPAIR_ORIGIN_RECOVERED_COMMITTED) {
		if (batch->last_verified_ordinal != count) {
			errno = EIO;
			return -1;
		}
		batch->commit_started = 1;
		batch->commit_completed = 1;
		batch->syncs = count;
		batch->write_boundaries = count;
	} else {
		batch->commit_started = batch->last_verified_ordinal != 0;
	}
	if (rh_repair_ledger_hash(batch))
		return -1;
	repair->transaction_count++;
	*output = batch;
	return 0;
}

int rh_orchestrator_recover(const struct rh_cli *cli,
		const struct rh_device_evidence *device, const char binary_hash[65],
		int report_fd, struct rh_scan_evidence *initial,
		struct rh_writer *writer, struct rh_repair_evidence *repair)
{
	struct rh_repair_transaction_evidence *batch;
	struct rh_wal *wal;
	size_t trace_first, i;
	int result;

	if (!cli || !device || !binary_hash || report_fd < 0 || !initial ||
			!writer || !repair || !initial->wal_handle_valid ||
			initial->wal.valid != 1 || !initial->wal.write_safe ||
			initial->wal_degraded || initial->wal.state == RH_WAL_EMPTY) {
		errno = EINVAL;
		return RH_RESULT_UNSAFE;
	}
	wal = &initial->wal_handle;
	if (rh_capture_recovered_begin(repair, wal, writer, &batch)) {
		if (!cli->quiet)
			fprintf(stderr, "roothealth recovery refused at capture: %s\n",
				strerror(errno));
		return errno == EIO ? RH_RESULT_IO : RH_RESULT_UNSAFE;
	}
	trace_first = rh_wal_trace_action_count(wal);
	if (batch->origin == RH_REPAIR_ORIGIN_RECOVERED_COMMITTED)
		result = rh_wal_committed_accept(wal, batch->kind);
	else
		result = rh_wal_rollback(wal);
	if (result || rh_capture_wal_trace(repair, wal,
			repair->transaction_count - 1U, trace_first)) {
		if (!cli->quiet)
			fprintf(stderr, "roothealth recovery refused at apply: %s\n",
				strerror(errno));
		return errno == EIO ? RH_RESULT_IO : RH_RESULT_UNSAFE;
	}
	if (batch->origin == RH_REPAIR_ORIGIN_RECOVERED_COMMITTED)
		batch->accepted = 1;
	else {
		batch->rolled_back = 1;
		for (i = trace_first; i < rh_wal_trace_action_count(wal); i++) {
			struct rh_wal_trace_action action;
			if (rh_wal_trace_action_at(wal, i, &action))
				return RH_RESULT_INTERNAL;
			if (action.kind != RH_WAL_TRACE_ROLLBACK_RESTORE)
				continue;
			batch->rollback_restored_entries++;
			batch->rollback_restored_bytes += action.length;
			batch->rollback_syncs++;
			batch->rollback_write_boundaries += action.write_boundaries;
		}
		if (batch->rollback_restored_entries != batch->last_verified_ordinal) {
			if (!cli->quiet)
				fprintf(stderr, "roothealth recovery rollback mismatch restored=%"PRIu64
					" verified=%"PRIu64" trace-first=%zu trace-count=%zu\n",
					batch->rollback_restored_entries,
					batch->last_verified_ordinal, trace_first,
					rh_wal_trace_action_count(wal));
			errno = EIO;
			return RH_RESULT_IO;
		}
	}
	if (rh_writer_pause_for_rescan(writer)) {
		if (!cli->quiet)
			fprintf(stderr, "roothealth recovery rescan pause failed: %s\n",
				strerror(errno));
		return RH_RESULT_IO;
	}
	result = rh_orchestrator_self_rescan(cli, device, &batch->post_scan,
		binary_hash, report_fd);
	if (rh_writer_resume_after_rescan(writer)) {
		if (!cli->quiet)
			fprintf(stderr, "roothealth recovery rescan resume failed: %s\n",
				strerror(errno));
		return RH_RESULT_IO;
	}
	if ((result != RH_RESULT_OK && result != RH_RESULT_UNSAFE) ||
			!batch->post_scan.completed || !batch->post_scan.census_available) {
		if (!cli->quiet)
			fprintf(stderr, "roothealth recovery rescan invalid result=%d complete=%d census=%d\n",
				result, batch->post_scan.completed,
				batch->post_scan.census_available);
		errno = EIO;
		return RH_RESULT_IO;
	}
	batch->post_scan_available = 1;
	return RH_RESULT_OK;
}

static void rh_census_profile_from_cli(const struct rh_cli *cli,
		struct rh_complete_census_profile *profile)
{
	memset(profile, 0, sizeof(*profile));
	profile->expected_volume_serial = cli->expected_serial;
	profile->roothealth_record = cli->expected_record;
	profile->roothealth_sequence = cli->expected_sequence;
	profile->require_t1os_identity = 1;
}

static int rh_run_complete_prefix(const struct rh_cli *cli,
		struct rh_writer *writer, uint64_t generation,
		struct rh_complete_census *census)
{
	struct rh_census_reader reader;
	struct rh_complete_census_profile profile;

	rh_census_profile_from_cli(cli, &profile);
	if (rh_census_reader_from_writer_prefix(writer, writer->operation_count,
			&reader) || rh_complete_census_run(&reader, &profile, generation,
			census))
		return -1;
	return 0;
}

static int rh_observe_or_stage_dirty(struct rh_writer *writer,
		int requested_dirty, int stage, struct rh_volume_dirty_pair *pair)
{
	struct rh_ntfs_overlay overlay;
	int result = -1;

	if (rh_ntfs_overlay_mount(&overlay, writer, 0))
		return -1;
	if (!rh_volume_dirty_inspect(overlay.volume, writer, requested_dirty,
			pair) && (!stage || !rh_volume_dirty_stage_pair(writer, pair)))
		result = 0;
	rh_ntfs_overlay_unmount(&overlay);
	return result;
}

int rh_orchestrator_boot_repair(struct rh_scan_evidence *initial,
		struct rh_writer *writer)
{
	struct rh_volume_dirty_pair dirty_clear;
	size_t i;

	if (!initial || !writer || !writer->path) {
		errno = EINVAL;
		return RH_RESULT_INTERNAL;
	}
	if (initial->foundation_operation_count) {
		if (initial->foundation_operation_count > RH_FOUNDATION_MAX ||
			initial->foundation_operation_count > writer->operation_count ||
			rh_writer_discard_after(writer,
				initial->foundation_operation_count))
			return RH_RESULT_UNSAFE;
		for (i = 0; i < writer->operation_count; i++)
			if (writer->operations[i].kind < RH_WRITE_BOOT_PRIMARY ||
					writer->operations[i].kind > RH_WRITE_MFT_MIRROR) {
				errno = EPERM;
				return RH_RESULT_UNSAFE;
			}
		return rh_writer_commit(writer) ?
			(errno == EIO ? RH_RESULT_IO : RH_RESULT_UNSAFE) : RH_RESULT_OK;
	}
	if (initial->native_log.state == RH_NATIVE_LOG_REPLAY_PLANNED) {
		if (!initial->identity_valid || initial->wal.state != RH_WAL_EMPTY ||
				initial->wal_degraded || !rh_native_plan_valid(initial, writer, 0)) {
			errno = EPERM;
			return RH_RESULT_UNSAFE;
		}
		return rh_writer_commit(writer) ?
			(errno == EIO ? RH_RESULT_IO : RH_RESULT_UNSAFE) : RH_RESULT_OK;
	}
	if (initial->dirty_known && initial->dirty && initial->identity_valid &&
			initial->logfile_clean && initial->wal.state == RH_WAL_EMPTY &&
			!initial->wal_degraded) {
		rh_writer_reset_plan(writer);
		if (rh_observe_or_stage_dirty(writer, 0, 1, &dirty_clear) ||
				!dirty_clear.initially_dirty || !dirty_clear.planned ||
				writer->operation_count != 2U)
			return errno == EIO ? RH_RESULT_IO : RH_RESULT_UNSAFE;
		for (i = 0; i < writer->operation_count; i++)
			if (writer->operations[i].kind != RH_WRITE_VOLUME_DIRTY_CLEAR) {
				errno = EPERM;
				return RH_RESULT_UNSAFE;
			}
		return rh_writer_commit(writer) ?
			(errno == EIO ? RH_RESULT_IO : RH_RESULT_UNSAFE) : RH_RESULT_OK;
	}
	errno = EOPNOTSUPP;
	return RH_RESULT_UNSAFE;
}

static int rh_finalize_operations_version(struct rh_writer *writer,
		size_t first, size_t count, uint32_t evidence_version,
		uint64_t generation, const unsigned char evidence[32],
		const unsigned char staged[32])
{
	size_t i;

	for (i = 0; i < count; i++)
		if (rh_writer_finalize_target(writer, first + i, evidence_version,
				generation,
				evidence, staged))
			return -1;
	return 0;
}

static int rh_finalize_operations(struct rh_writer *writer, size_t first,
		size_t count, uint64_t generation, const unsigned char evidence[32],
		const unsigned char staged[32])
{
	return rh_finalize_operations_version(writer, first, count, 1U,
		generation, evidence, staged);
}

static int rh_authorize_bitmap(const struct rh_writer *writer,
		const struct rh_policy_evidence *evidence, size_t first, size_t count,
		problem_code_t problem, const char *aggregate)
{
	const struct rh_policy_definition *definitions[2];
	struct rh_policy_authorization authorization;
	size_t d, i;

	definitions[0] = rh_policy_problem(problem);
	definitions[1] = rh_policy_aggregate(aggregate);
	if (!definitions[0] || !definitions[1] ||
			rh_policy_evidence_target_count(evidence) != count)
		return -1;
	for (d = 0; d < 2; d++)
		for (i = 0; i < count; i++)
			if (rh_policy_authorize_operation(definitions[d], evidence, i,
					writer, first + i, &authorization) !=
					RH_POLICY_FINAL_AUTHORIZED) {
				errno = EPERM;
				return -1;
			}
	return 0;
}

static int rh_index_bitmap_bootstrap_candidate(
		const struct rh_complete_census *census)
{
	const struct rh_index_bitmap_census *index;
	size_t i;

	if (!census || !census->identity_matches ||
			!census->raw.records_complete || !census->raw.records_bounded ||
			!census->raw.layout_complete ||
			!census->raw.attribute_lists_complete ||
			!census->raw.extents_complete || census->raw.unreadable_records ||
			census->raw.invalid_records ||
			!census->namespace_census.graph_complete ||
			!census->namespace_census.i30_complete ||
			!census->namespace_census.reciprocity_complete ||
			!census->mft_bitmap.complete ||
			!census->mft_bitmap.structurally_valid ||
			!census->mft_bitmap.clean || census->mft_bitmap.change_count ||
			!census->cluster_bitmap.complete ||
			!census->cluster_bitmap.structurally_valid ||
			!census->cluster_bitmap.ownership_exact ||
			!census->cluster_bitmap.clean ||
			census->cluster_bitmap.change_count)
		return 0;
	index = &census->index_bitmap;
	if (!index->complete || !index->index_tree_complete ||
			!index->child_vcns_valid || !index->indx_blocks_valid ||
			!index->reachable_set_exact || !index->sets_proven_reachable ||
			!index->targets_outside_wal || !index->set_only_safe ||
			index->clear_bits_required || !index->change_count ||
			index->unreadable_records || index->ambiguous_attributes ||
			index->unresolved_blocks)
		return 0;
	for (i = 0; i < index->change_count; i++)
		if (!index->changes[i].set_mask || index->changes[i].clear_mask ||
				(index->changes[i].set_mask &
				 (unsigned char)(index->changes[i].set_mask - 1U)))
			return 0;
	return 1;
}

void rh_orchestrator_repair_release(struct rh_repair_evidence *repair)
{
	size_t i;

	if (!repair)
		return;
	for (i = 0; i < repair->transaction_count; i++) {
		free(repair->transactions[i].actions);
		if (repair->transactions[i].post_scan_available &&
				repair->transactions[i].post_scan.census_available)
			rh_complete_census_release(
				&repair->transactions[i].post_scan.census);
	}
	free(repair->wal_actions);
	memset(repair, 0, sizeof(*repair));
}

int rh_orchestrator_repair(const struct rh_cli *cli,
		const struct rh_device_evidence *device,
		const char binary_hash[65], int report_fd,
		struct rh_scan_evidence *initial, struct rh_writer *writer,
		struct rh_repair_evidence *repair)
{
	struct rh_wal *wal;
	struct rh_ntfs_overlay overlay;
	struct rh_complete_census namespace_view = {0};
	struct rh_complete_census staged = {0}, post = {0}, clear_staged = {0};
	struct rh_complete_census final = {0};
	const struct rh_complete_census *repair_source;
	struct rh_namespace_repair_candidate namespace_candidate;
	struct rh_volume_dirty_pair dirty_set, dirty_clear, observed;
	struct rh_policy_evidence *cluster_policy = NULL;
	struct rh_policy_evidence *mft_policy = NULL;
	struct rh_policy_evidence *index_policy = NULL;
	struct rh_mft_bitmap_full_ledger_seal *mft_ledger = NULL;
	size_t cluster_first = 0, cluster_count = 0;
	size_t mft_first = 0, mft_count = 0;
	size_t index_first = 0, index_count = 0, dirty_count = 0;
	size_t namespace_first = 0;
	uint64_t generation;
	int overlay_mounted = 0, rescan_result, result = RH_RESULT_UNSAFE;
	int native_only, namespace_qualified = 0;
	const char *stage = "preconditions";

	errno = 0;
	if (!repair)
		return RH_RESULT_UNSAFE;
	if (!cli || !device || !binary_hash || report_fd < 0 || !initial ||
			!writer || !initial->wal_handle_valid ||
			!initial->identity_valid ||
			!initial->census_available ||
			initial->wal.state != RH_WAL_EMPTY || initial->wal.valid != 1 ||
			!initial->wal.write_safe) {
		rh_record_refusal(repair->refusal_stage, &repair->refusal_errno,
			stage, EINVAL);
		return RH_RESULT_UNSAFE;
	}
	wal = &initial->wal_handle;
	generation = initial->census.generation + 1U;
	native_only = rh_native_plan_valid(initial, writer, 0);
	if (native_only) {
		size_t native_count = writer->operation_count;
		struct rh_scan_evidence *native_post;

		stage = "native-preconditions";
		if (!initial->census.providers_complete ||
				!initial->census.coverage.complete ||
				initial->census.cluster_bitmap.change_count ||
				!rh_coverage_is_clean(&initial->census.coverage))
			goto out;
		stage = "native-finalize";
		if (rh_finalize_operations(writer, 1, native_count, generation,
				initial->census.cluster_bitmap.census_hash,
				initial->census.cluster_bitmap.census_hash))
			goto out;
		stage = "native-commit";
		if (rh_wal_install_backend(wal, RH_WAL_TX_METADATA_REPAIR) ||
				rh_writer_commit(writer) ||
				rh_capture_wal_transaction(repair, wal, writer,
					RH_WAL_TX_METADATA_REPAIR))
			goto out;
		rh_wal_uninstall_backend(wal);
		rh_writer_reset_plan(writer);
		stage = "native-accept";
		if (rh_wal_committed_accept(wal, RH_WAL_TX_METADATA_REPAIR) ||
				rh_capture_wal_trace(repair, wal,
					repair->transaction_count - 1U, 0))
			goto out;
		repair->transactions[repair->transaction_count - 1U].accepted = 1;
		stage = "native-self-rescan";
		if (rh_writer_pause_for_rescan(writer))
			goto out;
		rescan_result = rh_orchestrator_self_rescan(cli, device,
			&repair->transactions[repair->transaction_count - 1U].post_scan,
			binary_hash, report_fd);
		native_post = &repair->transactions[repair->transaction_count - 1U]
			.post_scan;
		if (rh_writer_resume_after_rescan(writer) ||
				(rescan_result != RH_RESULT_OK &&
				 rescan_result != RH_RESULT_UNSAFE) ||
				!native_post->completed || !native_post->identity_valid ||
				!native_post->census_available ||
				!native_post->census.providers_complete ||
				!native_post->census.coverage.complete ||
				!rh_coverage_is_clean(&native_post->census.coverage) ||
				!native_post->logfile_clean_known ||
				!native_post->logfile_clean ||
				(native_post->native_log.state != RH_NATIVE_LOG_CLEAN_RESTART &&
				 native_post->native_log.state != RH_NATIVE_LOG_EMPTY_T1OS))
			goto out;
		repair->transactions[repair->transaction_count - 1U]
			.post_scan_available = 1;
		if (!native_post->dirty) {
			if (rescan_result != RH_RESULT_OK)
				goto out;
			result = RH_RESULT_OK;
			goto out;
		}
		if (rescan_result != RH_RESULT_UNSAFE)
			goto out;
		stage = "native-dirty-preflight";
		if (rh_run_complete_prefix(cli, writer, generation + 1U, &post) ||
				!post.providers_complete || !post.coverage.complete ||
				!rh_coverage_is_clean(&post.coverage))
			goto out;
		goto dirty_clear_stage;
	}
	if (!initial->logfile_clean || writer->operation_count) {
		stage = "native-log-not-clean";
		rh_record_refusal(repair->refusal_stage, &repair->refusal_errno,
			stage, EINVAL);
		return RH_RESULT_UNSAFE;
	}
	if (!rh_namespace_operations_registry_qualify(&initial->census,
			&namespace_candidate))
		namespace_qualified = 1;
	else
		errno = 0;
	if (!namespace_qualified && (!initial->census.providers_complete ||
			!initial->census.coverage.complete) &&
			!rh_index_bitmap_bootstrap_candidate(&initial->census)) {
		stage = "census-incomplete";
		rh_record_refusal(repair->refusal_stage, &repair->refusal_errno,
			stage, EINVAL);
		return RH_RESULT_UNSAFE;
	}
	repair_source = &initial->census;

	/* A completely clean volume needs no transaction. */
	if (!initial->census.cluster_bitmap.change_count &&
			!initial->census.mft_bitmap.change_count &&
			!initial->census.index_bitmap.change_count &&
			!namespace_qualified && !initial->dirty) {
		if (rh_coverage_is_clean(&initial->census.coverage))
			return RH_RESULT_OK;
		stage = "coverage-unqualified";
		rh_record_refusal(repair->refusal_stage, &repair->refusal_errno,
			stage, EINVAL);
		return RH_RESULT_UNSAFE;
	}

	if (namespace_qualified || initial->census.cluster_bitmap.change_count ||
			initial->census.mft_bitmap.change_count ||
			initial->census.index_bitmap.change_count) {
		stage = "metadata-capacity";
		if (initial->census.cluster_bitmap.change_count > SIZE_MAX -
				initial->census.mft_bitmap.change_count ||
			initial->census.cluster_bitmap.change_count +
				initial->census.mft_bitmap.change_count > SIZE_MAX -
				initial->census.index_bitmap.change_count ||
			initial->census.cluster_bitmap.change_count +
				initial->census.mft_bitmap.change_count +
				initial->census.index_bitmap.change_count >
				RH_WAL_MAX_ENTRIES - 2U - (namespace_qualified ? 1U : 0U)) {
			errno = EOPNOTSUPP;
			goto out;
		}
		stage = "metadata-stage";
		if (rh_ntfs_overlay_mount(&overlay, writer, 0))
			goto out;
		overlay_mounted = 1;
		if (rh_volume_dirty_inspect(overlay.volume, writer, 1, &dirty_set))
			goto out;
		if (!dirty_set.initially_dirty) {
			if (rh_volume_dirty_stage_pair(writer, &dirty_set) ||
					!dirty_set.planned)
				goto out;
			dirty_count = 2;
		}
		if (namespace_qualified) {
			struct rh_census_reader namespace_reader;

			if (rh_census_reader_from_writer_prefix(writer,
					writer->operation_count, &namespace_reader) ||
					rh_namespace_operations_registry_stage(&namespace_reader,
						&initial->census, writer, &namespace_first,
						&namespace_candidate))
				goto out;
			rh_ntfs_overlay_unmount(&overlay);
			overlay_mounted = 0;
			stage = "namespace-staged-census";
			if (rh_run_complete_prefix(cli, writer,
					initial->census.generation, &namespace_view) ||
					!namespace_view.identity_matches ||
					!namespace_view.namespace_census.graph_complete ||
					!namespace_view.namespace_census.i30_complete ||
					!namespace_view.namespace_census.reciprocity_complete ||
					namespace_view.namespace_census.i30_edge_count !=
						namespace_view.namespace_census.link_count ||
					memcmp(initial->census.raw.file_name_manifest_hash,
						namespace_view.raw.file_name_manifest_hash, 32U))
				goto out;
			repair_source = &namespace_view;
			/* The namespace edit changes the index-tree evidence source. Keep
			 * index-bitmap repair in a separately qualified boot rather than
			 * binding it to a pre-edit WAL census. */
			if (repair_source->index_bitmap.change_count) {
				errno = EOPNOTSUPP;
				goto out;
			}
			if (repair_source->mft_bitmap.change_count ||
					repair_source->index_bitmap.change_count ||
					repair_source->cluster_bitmap.change_count) {
				if (rh_ntfs_overlay_mount(&overlay, writer, 0))
					goto out;
				overlay_mounted = 1;
			}
		}
		if (repair_source->mft_bitmap.change_count &&
				(rh_mft_bitmap_stage_prefix(&overlay,
					&repair_source->mft_bitmap,
					RH_WAL_MAX_ENTRIES - dirty_count, &mft_count,
					&mft_first) || mft_count !=
					repair_source->mft_bitmap.change_count))
			goto out;
		if (repair_source->index_bitmap.change_count &&
				(rh_index_bitmap_stage_prefix(&overlay,
					&repair_source->index_bitmap,
					RH_WAL_MAX_ENTRIES - dirty_count - mft_count -
						(namespace_qualified ? 1U : 0U),
					&index_count, &index_first) || index_count !=
					repair_source->index_bitmap.change_count))
			goto out;
		if (repair_source->cluster_bitmap.change_count &&
				(rh_cluster_bitmap_stage_prefix(&overlay,
					&repair_source->cluster_bitmap,
					RH_WAL_MAX_ENTRIES - dirty_count - mft_count - index_count -
						(namespace_qualified ? 1U : 0U),
					&cluster_count, &cluster_first) || cluster_count !=
					repair_source->cluster_bitmap.change_count))
			goto out;
		if (overlay_mounted) {
			rh_ntfs_overlay_unmount(&overlay);
			overlay_mounted = 0;
		}
		stage = "metadata-preflight";
		if (rh_run_complete_prefix(cli, writer, generation, &staged)) {
			stage = "metadata-staged-census";
			goto out;
		}
		if (!staged.providers_complete || !staged.coverage.complete ||
				!rh_coverage_is_clean(&staged.coverage)) {
			stage = "metadata-staged-not-clean";
			errno = EINVAL;
			goto out;
		}
		if (rh_observe_or_stage_dirty(writer, 1, 0, &observed) ||
				!observed.initially_dirty) {
			stage = "metadata-staged-dirty";
			goto out;
		}
		if (mft_count) {
			if (rh_mft_bitmap_full_ledger_seal_create(repair_source,
					&staged, &mft_ledger) ||
					rh_mft_bitmap_seal_policy(&repair_source->mft_bitmap,
						&staged.mft_bitmap, writer, mft_first, 1, 1,
						mft_ledger, &mft_policy)) {
				stage = "mft-bitmap-policy-seal";
				goto out;
			}
			if (rh_authorize_bitmap(writer, mft_policy, mft_first, mft_count,
					PR_MFT_BITMAP_MISMATCH, "MFT_BITMAP")) {
				stage = "mft-bitmap-policy-authorize";
				goto out;
			}
		}
		if (index_count) {
			if (rh_index_bitmap_seal_policy(&repair_source->index_bitmap,
					&staged.index_bitmap, writer, index_first, 1,
					repair_source->namespace_census.reciprocity_complete,
					&index_policy)) {
				stage = "index-bitmap-policy-seal";
				goto out;
			}
			if (rh_authorize_bitmap(writer, index_policy, index_first,
					index_count, PR_IDX_BITMAP_MISMATCH, "INDEX_BITMAP")) {
				stage = "index-bitmap-policy-authorize";
				goto out;
			}
		}
		if (cluster_count) {
			if (rh_cluster_bitmap_seal_policy(
					&repair_source->cluster_bitmap,
					&staged.cluster_bitmap, writer, cluster_first, 1,
					&cluster_policy)) {
				stage = "cluster-bitmap-policy-seal";
				goto out;
			}
			if (rh_authorize_bitmap(writer, cluster_policy, cluster_first,
					cluster_count, PR_CLUSTER_BITMAP_MISMATCH,
					"CLUSTER_BITMAP")) {
				stage = "cluster-bitmap-policy-authorize";
				goto out;
			}
		}
		if (dirty_count && rh_finalize_operations(writer, 1, dirty_count,
				initial->census.cluster_bitmap.generation,
				initial->census.cluster_bitmap.census_hash,
				staged.cluster_bitmap.census_hash)) {
			stage = "metadata-finalize-dirty";
			goto out;
		}
		if (namespace_qualified && rh_finalize_operations(writer,
				namespace_first, 1U, initial->census.generation,
				initial->census.namespace_census.census_hash,
				staged.namespace_census.census_hash)) {
			stage = "metadata-finalize-namespace";
			goto out;
		}
		if (mft_count && rh_finalize_operations(writer, mft_first, mft_count,
				repair_source->mft_bitmap.generation,
				repair_source->mft_bitmap.census_hash,
				staged.mft_bitmap.census_hash)) {
			stage = "metadata-finalize-mft-bitmap";
			goto out;
		}
		if (index_count && rh_finalize_operations_version(writer, index_first,
				index_count, RH_INDEX_BITMAP_EVIDENCE_VERSION,
				repair_source->index_bitmap.generation,
				repair_source->index_bitmap.census_hash,
				staged.index_bitmap.census_hash)) {
			stage = "metadata-finalize-index-bitmap";
			goto out;
		}
		if (cluster_count && rh_finalize_operations(writer, cluster_first,
				cluster_count, repair_source->cluster_bitmap.generation,
				repair_source->cluster_bitmap.census_hash,
				staged.cluster_bitmap.census_hash)) {
			stage = "metadata-finalize-cluster-bitmap";
			goto out;
		}
		stage = "metadata-commit";
		if (rh_wal_install_backend(wal, RH_WAL_TX_METADATA_REPAIR) ||
				rh_writer_commit(writer) ||
				rh_capture_wal_transaction(repair, wal, writer,
					RH_WAL_TX_METADATA_REPAIR))
			goto out;
		rh_wal_uninstall_backend(wal);
		rh_writer_reset_plan(writer);
		stage = "metadata-accept";
		if (rh_run_complete_prefix(cli, writer, generation + 1U, &post) ||
				!post.providers_complete || !post.coverage.complete ||
				!rh_coverage_is_clean(&post.coverage) ||
				rh_observe_or_stage_dirty(writer, 1, 0, &observed) ||
				!observed.initially_dirty ||
				rh_wal_committed_accept(wal, RH_WAL_TX_METADATA_REPAIR) ||
				rh_capture_wal_trace(repair, wal,
					repair->transaction_count - 1U, 0))
			goto out;
		repair->transactions[repair->transaction_count - 1U].accepted = 1;
		stage = "metadata-self-rescan";
		if (rh_writer_pause_for_rescan(writer))
			goto out;
		rescan_result = rh_orchestrator_self_rescan(cli, device,
				&repair->transactions[repair->transaction_count - 1U].post_scan,
				binary_hash, report_fd);
		if (rh_writer_resume_after_rescan(writer) ||
				rescan_result != RH_RESULT_UNSAFE ||
				!repair->transactions[repair->transaction_count - 1U]
					.post_scan.census_available ||
				!repair->transactions[repair->transaction_count - 1U]
					.post_scan.census.coverage.complete ||
				!rh_coverage_is_clean(&repair->transactions[
					repair->transaction_count - 1U].post_scan.census.coverage) ||
				!repair->transactions[repair->transaction_count - 1U]
					.post_scan.dirty) {
			errno = EIO;
			goto out;
		}
		repair->transactions[repair->transaction_count - 1U]
			.post_scan_available = 1;
	} else {
		stage = "dirty-only-preflight";
		/* Recreate an independently owned post view for the dirty-clear seal. */
		if (rh_run_complete_prefix(cli, writer, generation + 1U, &post) ||
				!post.providers_complete || !post.coverage.complete ||
				!rh_coverage_is_clean(&post.coverage))
			goto out;
	}

dirty_clear_stage:
	/* Dirty-clear is a separate, final mirrored transaction. */
	stage = "dirty-clear-stage";
	if (rh_observe_or_stage_dirty(writer, 0, 1, &dirty_clear) ||
			!dirty_clear.initially_dirty || !dirty_clear.planned ||
			writer->operation_count != 2)
		goto out;
	stage = "dirty-clear-staged-census";
	if (rh_run_complete_prefix(cli, writer, generation + 2U,
			&clear_staged) || !clear_staged.providers_complete ||
			!clear_staged.coverage.complete ||
			!rh_coverage_is_clean(&clear_staged.coverage))
		goto out;
	stage = "dirty-clear-staged-observe";
	if (rh_observe_or_stage_dirty(writer, 0, 0, &observed) ||
			observed.initially_dirty)
		goto out;
	stage = "dirty-clear-finalize";
	if (rh_finalize_operations(writer, 1, 2,
			post.cluster_bitmap.generation,
			post.cluster_bitmap.census_hash,
			clear_staged.cluster_bitmap.census_hash))
		goto out;
	stage = "dirty-clear-install";
	if (rh_wal_install_backend(wal, RH_WAL_TX_DIRTY_CLEAR))
		goto out;
	stage = "dirty-clear-commit";
	if (rh_writer_commit(writer))
		goto out;
	stage = "dirty-clear-capture";
	if (rh_capture_wal_transaction(repair, wal, writer,
			RH_WAL_TX_DIRTY_CLEAR))
		goto out;
	stage = "dirty-clear-accept";
	rh_wal_uninstall_backend(wal);
	rh_writer_reset_plan(writer);
	if (rh_run_complete_prefix(cli, writer, generation + 3U, &final) ||
			!final.providers_complete || !final.coverage.complete ||
			!rh_coverage_is_clean(&final.coverage) ||
			rh_observe_or_stage_dirty(writer, 0, 0, &observed) ||
			observed.initially_dirty ||
			rh_wal_committed_accept(wal, RH_WAL_TX_DIRTY_CLEAR) ||
			rh_capture_wal_trace(repair, wal,
				repair->transaction_count - 1U, 0))
		goto out;
	repair->transactions[repair->transaction_count - 1U].accepted = 1;
	stage = "dirty-clear-self-rescan";
	if (rh_writer_pause_for_rescan(writer))
		goto out;
	rescan_result = rh_orchestrator_self_rescan(cli, device,
			&repair->transactions[repair->transaction_count - 1U].post_scan,
			binary_hash, report_fd);
	if (rh_writer_resume_after_rescan(writer) ||
			rescan_result != RH_RESULT_OK ||
			!repair->transactions[repair->transaction_count - 1U]
				.post_scan.census_available ||
			!repair->transactions[repair->transaction_count - 1U]
				.post_scan.census.coverage.complete ||
			!rh_coverage_is_clean(&repair->transactions[
				repair->transaction_count - 1U].post_scan.census.coverage) ||
			repair->transactions[repair->transaction_count - 1U]
				.post_scan.dirty) {
		errno = EIO;
		goto out;
	}
	repair->transactions[repair->transaction_count - 1U]
		.post_scan_available = 1;
	repair->dirty_cleared = 1;
	result = RH_RESULT_OK;
out:
	if (overlay_mounted)
		rh_ntfs_overlay_unmount(&overlay);
	rh_mft_bitmap_full_ledger_seal_destroy(mft_ledger);
	rh_policy_evidence_destroy(index_policy);
	rh_policy_evidence_destroy(mft_policy);
	rh_policy_evidence_destroy(cluster_policy);
	rh_complete_census_release(&final);
	rh_complete_census_release(&clear_staged);
	rh_complete_census_release(&post);
	rh_complete_census_release(&staged);
	rh_complete_census_release(&namespace_view);
	if (result != RH_RESULT_OK) {
		rh_record_refusal(repair->refusal_stage, &repair->refusal_errno,
			stage, errno);
		rh_wal_uninstall_backend(wal);
		rh_writer_reset_plan(writer);
	}
	return result;
}

static int rh_write_all(int fd, const void *buffer, size_t length)
{
	const unsigned char *p = buffer;
	while (length) {
		ssize_t result = write(fd, p, length);
		if (result < 0) {
			if (errno == EINTR)
				continue;
			return -1;
		}
		if (!result) {
			errno = EIO;
			return -1;
		}
		p += result;
		length -= (size_t)result;
	}
	return 0;
}

static int rh_protected_fd_inherited(const struct rh_device_evidence *device,
		uint64_t report_dev, uint64_t report_ino, int transport_fd)
{
	struct dirent *entry;
	DIR *directory;
	int own_fd, inherited = 0;

	directory = opendir("/proc/self/fd");
	if (!directory)
		return -1;
	own_fd = dirfd(directory);
	for (;;) {
		struct stat st;
		char *end = NULL;
		long parsed;

		errno = 0;
		entry = readdir(directory);
		if (!entry) {
			if (errno)
				inherited = -1;
			break;
		}
		errno = 0;
		parsed = strtol(entry->d_name, &end, 10);
		if (errno || !end || *end || parsed < 0 || parsed > INT_MAX)
			continue;
		if ((int)parsed == transport_fd || (int)parsed == own_fd)
			continue;
		if (fstat((int)parsed, &st)) {
			inherited = -1;
			break;
		}
		if ((S_ISBLK(device->resolved_stat.st_mode) && S_ISBLK(st.st_mode) &&
			 st.st_rdev == device->resolved_stat.st_rdev) ||
			(!S_ISBLK(device->resolved_stat.st_mode) &&
			 st.st_dev == device->resolved_stat.st_dev &&
			 st.st_ino == device->resolved_stat.st_ino) ||
			((uint64_t)st.st_dev == report_dev &&
			 (uint64_t)st.st_ino == report_ino)) {
			inherited = 1;
			break;
		}
	}
	if (closedir(directory))
		return -1;
	return inherited;
}

static int rh_anonymous_pipe_fd(int fd)
{
	char path[64], target[128];
	ssize_t length;

	if (snprintf(path, sizeof(path), "/proc/self/fd/%d", fd) < 0)
		return 0;
	length = readlink(path, target, sizeof(target) - 1);
	if (length < 7 || (size_t)length >= sizeof(target))
		return 0;
	target[length] = 0;
	return !strncmp(target, "pipe:[", 6) && target[length - 1] == ']';
}

int rh_orchestrator_internal_rescan(const struct rh_cli *cli)
{
	struct rh_device_evidence device;
	struct rh_scan_evidence scan;
	struct rh_rescan_packet packet;
	struct rh_writer writer;
	struct stat transport;
	int access;
	int fd = cli->internal_fd;

	access = fcntl(fd, F_GETFL);
	if (access < 0 || (access & O_ACCMODE) != O_WRONLY ||
			fstat(fd, &transport) || !S_ISFIFO(transport.st_mode) ||
			!rh_anonymous_pipe_fd(fd) ||
			fcntl(fd, F_SETFD, FD_CLOEXEC) ||
			rh_device_resolve(cli->device_path, &device))
		return RH_RESULT_INTERNAL;
	if ((uint64_t)device.resolved_stat.st_dev != cli->internal_expected_dev ||
			(uint64_t)device.resolved_stat.st_ino != cli->internal_expected_ino ||
			(uint64_t)device.resolved_stat.st_rdev != cli->internal_expected_rdev)
		return RH_RESULT_INTERNAL;
	errno = 0;
	if (fcntl(cli->internal_report_fd, F_GETFD) >= 0 || errno != EBADF)
		return RH_RESULT_INTERNAL;
	if (rh_protected_fd_inherited(&device, cli->internal_report_dev,
			cli->internal_report_ino, fd) != 0)
		return RH_RESULT_INTERNAL;
	memset(&packet, 0, sizeof(packet));
	memcpy(packet.magic, rh_rescan_magic, sizeof(packet.magic));
	packet.version = RH_RESCAN_PACKET_VERSION;
	packet.size = sizeof(packet);
	packet.pid = (uint64_t)getpid();
	packet.parent_pid = (uint64_t)getppid();
	rh_orchestrator_scan(cli, &device, &scan, &writer, 0);
	packet.device_dev = (uint64_t)device.resolved_stat.st_dev;
	packet.device_ino = (uint64_t)device.resolved_stat.st_ino;
	packet.device_rdev = (uint64_t)device.resolved_stat.st_rdev;
	packet.device_size = device.size;
	if (rh_uuid_text(packet.exec_id) ||
			rh_binary_hash(packet.binary_sha256))
		return RH_RESULT_INTERNAL;
	packet.result = scan.result;
	packet.completed = scan.completed;
	packet.identity_valid = scan.identity_valid;
	packet.logfile_clean_known = scan.logfile_clean_known;
	packet.logfile_clean = scan.logfile_clean;
	packet.native_state = scan.native_refused ? -1 :
		(int)scan.native_log.state;
	packet.dirty_known = scan.dirty_known;
	packet.dirty = scan.dirty;
	packet.census_available = scan.census_available;
	packet.providers_complete = scan.census_available ?
		scan.census.providers_complete : 0;
	if (scan.census_available) {
		size_t i;
		packet.coverage = scan.census.coverage;
		packet.coverage.fixed_system.checks = NULL;
		for (i = 0; i < RH_COMPLETE_CENSUS_FIXED_CHECK_COUNT; i++)
			packet.fixed_results[i] = scan.census.fixed_checks[i].result;
		memcpy(packet.coverage_hash, scan.census.coverage_hash,
			sizeof(packet.coverage_hash));
	}
	packet.device_fd_inherited = 0;
	packet.report_fd_inherited = 0;
	strcpy(packet.scan_id, scan.scan_id);
	if (rh_write_all(fd, &packet, sizeof(packet))) {
		if (scan.census_available)
			rh_complete_census_release(&scan.census);
		return RH_RESULT_INTERNAL;
	}
	if (scan.census_available)
		rh_complete_census_release(&scan.census);
	return RH_RESULT_OK;
}

static int64_t rh_now_milliseconds(void)
{
	struct timespec now;
	if (clock_gettime(CLOCK_MONOTONIC, &now))
		return -1;
	return (int64_t)now.tv_sec * 1000 + now.tv_nsec / 1000000;
}

static int rh_read_all_before(int fd, void *buffer, size_t length,
		int64_t deadline)
{
	unsigned char *p = buffer;
	int flags;

	flags = fcntl(fd, F_GETFL);
	if (flags < 0 || fcntl(fd, F_SETFL, flags | O_NONBLOCK))
		return -1;
	while (length) {
		ssize_t result = read(fd, p, length);
		if (result < 0) {
			if (errno == EINTR)
				continue;
			if (errno == EAGAIN || errno == EWOULDBLOCK) {
				struct pollfd event;
				int64_t now = rh_now_milliseconds();
				int remaining, ready;
				if (now < 0 || now >= deadline) {
					errno = ETIMEDOUT;
					return -1;
				}
				remaining = (int)(deadline - now);
				event.fd = fd;
				event.events = POLLIN | POLLHUP;
				event.revents = 0;
				ready = poll(&event, 1, remaining);
				if (ready < 0 && errno == EINTR)
					continue;
				if (ready > 0)
					continue;
				if (!ready)
					errno = ETIMEDOUT;
			}
			return -1;
		}
		if (!result) {
			errno = EPIPE;
			return -1;
		}
		p += result;
		length -= (size_t)result;
	}
	return 0;
}

static int rh_expect_eof_before(int fd, int64_t deadline)
{
	for (;;) {
		unsigned char extra;
		ssize_t result = read(fd, &extra, 1);
		if (!result)
			return 0;
		if (result > 0) {
			errno = EMSGSIZE;
			return -1;
		}
		if (errno == EINTR)
			continue;
		if (errno == EAGAIN || errno == EWOULDBLOCK) {
			struct pollfd event;
			int64_t now = rh_now_milliseconds();
			int remaining, ready;
			if (now < 0 || now >= deadline) {
				errno = ETIMEDOUT;
				return -1;
			}
			remaining = (int)(deadline - now);
			event.fd = fd;
			event.events = POLLIN | POLLHUP;
			event.revents = 0;
			ready = poll(&event, 1, remaining);
			if (ready > 0 || (ready < 0 && errno == EINTR))
				continue;
			if (!ready)
				errno = ETIMEDOUT;
		}
		return -1;
	}
}

static int rh_wait_before(pid_t child, int *status, int64_t deadline)
{
	for (;;) {
		pid_t result = waitpid(child, status, WNOHANG);
		int64_t now;
		if (result == child)
			return 0;
		if (result < 0) {
			if (errno == EINTR)
				continue;
			return -1;
		}
		now = rh_now_milliseconds();
		if (now < 0 || now >= deadline) {
			errno = ETIMEDOUT;
			return -1;
		}
		(void)poll(NULL, 0, deadline - now > 10 ? 10 :
			(int)(deadline - now));
	}
}

static void rh_kill_and_reap_bounded(pid_t child, int *status)
{
	int64_t deadline = rh_now_milliseconds();

	(void)kill(child, SIGKILL);
	if (deadline < 0 || deadline > INT64_MAX - 1000)
		return;
	deadline += 1000;
	(void)rh_wait_before(child, status, deadline);
}

int rh_orchestrator_self_rescan(const struct rh_cli *cli,
		const struct rh_device_evidence *device,
		struct rh_scan_evidence *scan, const char binary_hash[65], int report_fd)
{
	struct rh_rescan_packet packet;
	char fd_text[32], report_fd_text[32], serial[19], record[64];
	char dev_text[32], ino_text[32], rdev_text[32];
	char report_dev_text[32], report_ino_text[32];
	struct stat report_stat;
	unsigned char coverage_hash[32];
	size_t i;
	int pipefd[2], flags, status = 0;
	int64_t deadline;
	pid_t child;

	memset(scan, 0, sizeof(*scan));
	scan->result = RH_RESULT_INTERNAL;
	strcpy(scan->execution.role, "SELF_EXEC_RESCAN");
	strcpy(scan->execution.transport, "SELF_EXEC_PIPE_V1");
	strcpy(scan->execution.binary_sha256, binary_hash);
	scan->execution.parent_pid = (uint64_t)getpid();
	scan->execution.timeout_known = 1;
	scan->execution.timeout_ms = RH_RESCAN_TIMEOUT_MS;
	scan->execution.timed_out_known = 1;
	deadline = rh_now_milliseconds();
	if (deadline < 0 || deadline > INT64_MAX - RH_RESCAN_TIMEOUT_MS)
		return RH_RESULT_INTERNAL;
	deadline += RH_RESCAN_TIMEOUT_MS;
	flags = fcntl(report_fd, F_GETFD);
	if (flags < 0 || !(flags & FD_CLOEXEC) || fstat(report_fd, &report_stat) ||
			!S_ISREG(report_stat.st_mode))
		return RH_RESULT_INTERNAL;
	if (pipe(pipefd))
		return RH_RESULT_INTERNAL;
	flags = fcntl(pipefd[0], F_GETFD);
	if (flags < 0 || fcntl(pipefd[0], F_SETFD, flags | FD_CLOEXEC)) {
		close(pipefd[0]);
		close(pipefd[1]);
		return RH_RESULT_INTERNAL;
	}
	flags = fcntl(pipefd[1], F_GETFD);
	if (flags < 0 || fcntl(pipefd[1], F_SETFD, flags & ~FD_CLOEXEC)) {
		close(pipefd[0]);
		close(pipefd[1]);
		return RH_RESULT_INTERNAL;
	}
	child = fork();
	if (child < 0) {
		close(pipefd[0]);
		close(pipefd[1]);
		return RH_RESULT_INTERNAL;
	}
	if (!child) {
		snprintf(fd_text, sizeof(fd_text), "%d", pipefd[1]);
		snprintf(report_fd_text, sizeof(report_fd_text), "%d", report_fd);
		snprintf(serial, sizeof(serial), "0x%016"PRIx64,
			cli->expected_serial);
		snprintf(record, sizeof(record), "%"PRIu64":%u",
			cli->expected_record, cli->expected_sequence);
		snprintf(dev_text, sizeof(dev_text), "%"PRIu64,
			(uint64_t)device->resolved_stat.st_dev);
		snprintf(ino_text, sizeof(ino_text), "%"PRIu64,
			(uint64_t)device->resolved_stat.st_ino);
		snprintf(rdev_text, sizeof(rdev_text), "%"PRIu64,
			(uint64_t)device->resolved_stat.st_rdev);
		snprintf(report_dev_text, sizeof(report_dev_text), "%"PRIu64,
			(uint64_t)report_stat.st_dev);
		snprintf(report_ino_text, sizeof(report_ino_text), "%"PRIu64,
			(uint64_t)report_stat.st_ino);
		close(pipefd[0]);
		execl("/proc/self/exe", "roothealth", "--check",
			"--require-t1os-root", "--expected-serial", serial,
			"--expected-journal-uuid", cli->expected_uuid_text,
			"--expected-journal-record", record, "--internal-rescan-fd",
			fd_text, "--internal-parent-report-fd", report_fd_text,
			"--internal-expected-st-dev", dev_text,
			"--internal-expected-st-ino", ino_text,
			"--internal-expected-st-rdev", rdev_text,
			"--internal-report-st-dev", report_dev_text,
			"--internal-report-st-ino", report_ino_text,
			device->resolved, (char *)NULL);
		_exit(127);
	}
	close(pipefd[1]);
	scan->execution.pid = (uint64_t)child;
	if (rh_read_all_before(pipefd[0], &packet, sizeof(packet), deadline) ||
			rh_expect_eof_before(pipefd[0], deadline)) {
		if (errno == ETIMEDOUT)
			scan->execution.timed_out = 1;
		rh_kill_and_reap_bounded(child, &status);
		close(pipefd[0]);
		return RH_RESULT_INTERNAL;
	}
	close(pipefd[0]);
	if (rh_wait_before(child, &status, deadline)) {
		if (errno == ETIMEDOUT)
			scan->execution.timed_out = 1;
		rh_kill_and_reap_bounded(child, &status);
		return RH_RESULT_INTERNAL;
	}
	scan->execution.transport_status_known = 1;
	scan->execution.transport_status = WIFEXITED(status) ?
		WEXITSTATUS(status) : 128 + WTERMSIG(status);
	scan->execution.pipe_payload_bytes = sizeof(packet);
	if (!WIFEXITED(status) || WEXITSTATUS(status) ||
			memcmp(packet.magic, rh_rescan_magic, sizeof(packet.magic)) ||
			packet.version != RH_RESCAN_PACKET_VERSION ||
			packet.size != sizeof(packet) ||
			packet.pid != (uint64_t)child ||
			packet.parent_pid != (uint64_t)getpid() ||
			packet.device_dev != (uint64_t)device->resolved_stat.st_dev ||
			packet.device_ino != (uint64_t)device->resolved_stat.st_ino ||
			packet.device_rdev != (uint64_t)device->resolved_stat.st_rdev ||
			(packet.device_size != device->size &&
			 !(packet.result == RH_RESULT_IO && !packet.completed &&
			   packet.device_size == 0)) ||
			packet.device_fd_inherited != 0 ||
			packet.report_fd_inherited != 0 ||
			(packet.dirty_known != 0 && packet.dirty_known != 1) ||
			(packet.dirty != 0 && packet.dirty != 1) ||
			(!packet.dirty_known && packet.dirty) ||
			(packet.census_available != 0 && packet.census_available != 1) ||
			(packet.providers_complete != 0 && packet.providers_complete != 1) ||
			(packet.providers_complete && !packet.census_available) ||
			packet.scan_id[sizeof(packet.scan_id) - 1] != 0 ||
			packet.exec_id[sizeof(packet.exec_id) - 1] != 0 ||
			packet.binary_sha256[sizeof(packet.binary_sha256) - 1] != 0 ||
			!rh_uuid_canonical_v4(packet.scan_id) ||
			!rh_uuid_canonical_v4(packet.exec_id) ||
			!strcmp(packet.scan_id, packet.exec_id) ||
			!rh_hash_text_valid(packet.binary_sha256) ||
			strcmp(packet.binary_sha256, binary_hash) ||
			(packet.census_available &&
			 (packet.coverage.fixed_system.check_count !=
				RH_COMPLETE_CENSUS_FIXED_CHECK_COUNT ||
			  (packet.result == RH_RESULT_OK &&
			   (!packet.providers_complete || !packet.coverage.complete)))) ||
			!rh_rescan_semantics_valid(packet.result, packet.completed,
				packet.identity_valid, packet.logfile_clean_known,
				packet.logfile_clean, packet.native_state))
		return RH_RESULT_INTERNAL;
	scan->completed = packet.completed;
	scan->result = packet.result;
	scan->identity_valid = packet.identity_valid;
	scan->identity.prewrite_checked = packet.identity_valid;
	scan->dirty_known = packet.dirty_known;
	scan->dirty = packet.dirty;
	scan->logfile_clean_known = packet.logfile_clean_known;
	scan->logfile_clean = packet.logfile_clean;
	scan->native_log.checked = packet.native_state != 0;
	scan->native_log.state = packet.native_state > 0 ?
		(enum rh_native_log_state)packet.native_state :
		RH_NATIVE_LOG_UNKNOWN;
	scan->native_refused = packet.native_state < 0;
	if (packet.census_available) {
		scan->census_available = 1;
		scan->census.providers_complete = packet.providers_complete;
		scan->census.coverage = packet.coverage;
		for (i = 0; i < RH_COMPLETE_CENSUS_FIXED_CHECK_COUNT; i++) {
			scan->census.fixed_checks[i].id =
				rh_coverage_required_fixed_check_id(i);
			scan->census.fixed_checks[i].result = packet.fixed_results[i];
		}
		scan->census.coverage.fixed_system.checks =
			scan->census.fixed_checks;
		scan->census.coverage.fixed_system.check_count =
			RH_COMPLETE_CENSUS_FIXED_CHECK_COUNT;
		if (rh_coverage_hash(&scan->census.coverage, coverage_hash) ||
				memcmp(coverage_hash, packet.coverage_hash,
					sizeof(coverage_hash)) ||
				(scan->result == RH_RESULT_OK &&
				 !rh_coverage_is_clean(&scan->census.coverage)))
			return RH_RESULT_INTERNAL;
		memcpy(scan->census.coverage_hash, packet.coverage_hash,
			sizeof(packet.coverage_hash));
	}
	strcpy(scan->scan_id, packet.scan_id);
	strcpy(scan->execution.exec_id, packet.exec_id);
	scan->execution.device_fd_inherited = packet.device_fd_inherited;
	scan->execution.report_fd_inherited = packet.report_fd_inherited;
	return scan->result;
}
