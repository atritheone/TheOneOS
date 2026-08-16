
#ifndef ROOTHEALTH_ORCHESTRATOR_H
#define ROOTHEALTH_ORCHESTRATOR_H

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <sys/stat.h>

#include "roothealth_repair.h"
#include "roothealth_complete_census.h"
#include "roothealth_wal.h"

#define RH_FOUNDATION_MAX 4U
#define RH_REPAIR_TRANSACTION_MAX 64U
#define RH_RESCAN_TIMEOUT_MS 180000U
#define RH_REFUSAL_STAGE_MAX 63U

enum rh_cli_mode {
	RH_CLI_NONE = 0,
	RH_CLI_CHECK,
	RH_CLI_REPAIR,
	RH_CLI_PREFLIGHT,
	RH_CLI_BOOT_REPAIR
};

struct rh_cli {
	enum rh_cli_mode mode;
	int require_root;
	int quiet;
	uint64_t expected_serial;
	unsigned char expected_uuid[16];
	char expected_uuid_text[37];
	uint64_t expected_record;
	uint16_t expected_sequence;
	const char *report_path;
	const char *device_path;
	int internal_fd;
	int internal_report_fd;
	uint64_t internal_expected_dev;
	uint64_t internal_expected_ino;
	uint64_t internal_expected_rdev;
	uint64_t internal_report_dev;
	uint64_t internal_report_ino;
};

struct rh_device_evidence {
	char requested[4096];
	char resolved[4096];
	int requested_was_symlink;
	struct stat requested_stat;
	struct stat resolved_stat;
	uint64_t size;
	int selection_proven;
};

struct rh_execution_evidence {
	char role[24];
	char transport[24];
	char exec_id[37];
	char binary_sha256[65];
	uint64_t pid;
	uint64_t parent_pid;
	uint64_t pipe_payload_bytes;
	int transport_status_known;
	int transport_status;
	int timeout_known;
	uint32_t timeout_ms;
	int timed_out_known;
	int timed_out;
	int device_fd_inherited;
	int report_fd_inherited;
};

struct rh_scan_evidence {
	int completed;
	int result;
	int safe_foundation_commit;
	int identity_valid;
	int dirty_known;
	int dirty;
	int logfile_clean_known;
	int logfile_clean;
	int native_refused;
	size_t foundation_operation_count;
	char scan_id[37];
	struct rh_execution_evidence execution;
	struct rh_identity_result identity;
	struct rh_boot_result boot;
	struct rh_mirror_result mirror;
	struct rh_log_result native_log;
	struct rh_wal_observation wal;
	struct rh_wal wal_handle;
	int wal_handle_valid;
	struct rh_complete_census census;
	int census_available;
	int wal_degraded;
	char refusal_stage[RH_REFUSAL_STAGE_MAX + 1U];
	int refusal_errno;
};

struct rh_repair_action_evidence {
	uint64_t ordinal;
	uint32_t action_id;
	enum rh_write_kind kind;
	uint64_t offset;
	uint64_t length;
	char before_hash[65];
	char after_hash[65];
	uint64_t write_boundaries;
	int verified;
};

struct rh_repair_transaction_evidence {
	enum {
		RH_REPAIR_ORIGIN_NEW = 0,
		RH_REPAIR_ORIGIN_RECOVERED_COMMITTED = 1,
		RH_REPAIR_ORIGIN_RECOVERED_ROLLED_BACK = 2
	} origin;
	enum rh_wal_transaction_kind kind;
	enum rh_wal_state initial_state;
	char transaction_uuid[37];
	char plan_hash[65];
	char repair_ledger_hash[65];
	struct rh_repair_action_evidence *actions;
	size_t action_count;
	uint64_t target_bytes;
	uint64_t syncs;
	uint64_t write_boundaries;
	uint64_t last_verified_ordinal;
	int commit_started;
	int commit_completed;
	int accepted;
	int rolled_back;
	uint64_t rollback_restored_entries;
	uint64_t rollback_restored_bytes;
	uint64_t rollback_syncs;
	uint64_t rollback_write_boundaries;
	struct rh_scan_evidence post_scan;
	int post_scan_available;
};

struct rh_wal_action_evidence {
	uint64_t ordinal;
	enum rh_wal_trace_kind kind;
	uint64_t extent_offset;
	uint64_t length;
	int slot;
	uint64_t transaction_ordinal;
	char transaction_uuid[37];
	enum rh_wal_state from_state;
	enum rh_wal_state to_state;
	char before_hash[65];
	char after_hash[65];
	uint64_t sync_ordinal;
	uint64_t write_boundaries;
};

struct rh_repair_evidence {
	struct rh_repair_transaction_evidence
		transactions[RH_REPAIR_TRANSACTION_MAX];
	size_t transaction_count;
	size_t action_count;
	uint64_t target_bytes;
	uint64_t syncs;
	uint64_t write_boundaries;
	struct rh_wal_action_evidence *wal_actions;
	size_t wal_action_count;
	size_t wal_action_capacity;
	uint64_t wal_bytes;
	uint64_t wal_syncs;
	uint64_t wal_write_boundaries;
	int dirty_cleared;
	char refusal_stage[RH_REFUSAL_STAGE_MAX + 1U];
	int refusal_errno;
};

struct rh_foundation_action {
	uint64_t ordinal;
	uint32_t action_id;
	enum rh_write_kind kind;
	uint64_t offset;
	uint64_t length;
	char before_hash[65];
	char after_hash[65];
	uint64_t write_boundaries;
	uint64_t sync_ordinal;
	const char *source_peer;
	const char *target_peer;
	const char *target;
};

struct rh_foundation_evidence {
	struct rh_foundation_action actions[RH_FOUNDATION_MAX];
	size_t count;
	uint64_t bytes;
	uint64_t syncs;
	uint64_t write_boundaries;
	char plan_hash[65];
	char repair_ledger_hash[65];
};

void rh_cli_usage(FILE *stream);
int rh_cli_parse(int argc, char **argv, struct rh_cli *cli);
int rh_device_resolve(const char *path, struct rh_device_evidence *device);
int rh_binary_hash(char output[65]);
int rh_uuid_text(char output[37]);
const char *rh_public_result(int result);
const char *rh_native_state(const struct rh_scan_evidence *scan);
int rh_result_precedence(int first, int second);

int rh_orchestrator_scan(const struct rh_cli *cli,
		struct rh_device_evidence *device, struct rh_scan_evidence *scan,
		struct rh_writer *writer, int keep_writer);
int rh_orchestrator_recover(const struct rh_cli *cli,
		const struct rh_device_evidence *device, const char binary_hash[65],
		int report_fd, struct rh_scan_evidence *initial,
		struct rh_writer *writer, struct rh_repair_evidence *repair);
int rh_orchestrator_reconstruct_degraded(struct rh_scan_evidence *initial,
		struct rh_writer *writer, struct rh_repair_evidence *repair);
int rh_orchestrator_capture_foundation(const struct rh_writer *writer,
		struct rh_foundation_evidence *foundation);
int rh_orchestrator_repair(const struct rh_cli *cli,
		const struct rh_device_evidence *device,
		const char binary_hash[65], int report_fd,
		struct rh_scan_evidence *initial, struct rh_writer *writer,
		struct rh_repair_evidence *repair);
int rh_orchestrator_boot_repair(struct rh_scan_evidence *initial,
		struct rh_writer *writer);
void rh_orchestrator_repair_release(struct rh_repair_evidence *repair);
int rh_orchestrator_internal_rescan(const struct rh_cli *cli);
int rh_orchestrator_self_rescan(const struct rh_cli *cli,
		const struct rh_device_evidence *device,
		struct rh_scan_evidence *scan, const char binary_hash[65], int report_fd);

#ifdef ROOTHEALTH_RESCAN_TEST_HOOKS
int rh_orchestrator_test_rescan_semantics(int result, int completed,
	int identity_valid, int logfile_clean_known, int logfile_clean,
	int native_state);
#endif

#endif
