#ifndef ROOTHEALTH_WAL_H
#define ROOTHEALTH_WAL_H

#include <stddef.h>
#include <stdint.h>

#include "roothealth_write.h"

#define RH_WAL_SIZE (128ULL * 1024ULL * 1024ULL)
#define RH_WAL_MAX_TARGET_BYTES (100ULL * 1024ULL * 1024ULL)
#define RH_WAL_MAX_ENTRIES 4096U
#define RH_WAL_SEMANTIC_SEAL_VERSION 1U
#define RH_WAL_DESCRIPTOR_PLAN_BYTES 0x1e0U
#define RH_WAL_ACTION_VERIFIER_ABI_VERSION 1U

enum rh_wal_state {
	RH_WAL_EMPTY = 0,
	RH_WAL_PREPARING = 1,
	RH_WAL_APPLYING = 2,
	RH_WAL_COMMITTED = 3,
	RH_WAL_ROLLBACK = 4
};

enum rh_wal_transaction_kind {
	RH_WAL_TX_NONE = 0,
	RH_WAL_TX_METADATA_REPAIR = 1,
	RH_WAL_TX_DIRTY_CLEAR = 2
};

enum rh_wal_trace_kind {
	RH_WAL_TRACE_UNDO_PAYLOAD = 1,
	RH_WAL_TRACE_DESCRIPTOR = 2,
	RH_WAL_TRACE_STATE = 3,
	RH_WAL_TRACE_SUPERBLOCK_RECONSTRUCT = 4,
	RH_WAL_TRACE_ROLLBACK_RESTORE = 5
};

struct rh_wal_trace_action {
	enum rh_wal_trace_kind kind;
	uint64_t extent_offset;
	uint64_t length;
	int slot;
	enum rh_wal_state from_state;
	enum rh_wal_state to_state;
	unsigned char transaction_uuid[16];
	unsigned char before_hash[32];
	unsigned char after_hash[32];
	uint64_t sync_ordinal;
	uint64_t write_boundaries;
};

struct rh_wal_observation {
	int checked;
	int present;              /* -1 unknown, 0 false, 1 true */
	int valid;                /* -1 unknown, 0 false, 1 true */
	int recovery_required;    /* -1 unknown, 0 false, 1 true */
	int recovered;
	int fast_path_trusted;
	uint64_t unreadable_record_count;
	uint64_t definite_duplicate_count;
	int ownership_census_complete;
	int write_safe;
	int journal_mft_bitmap_allocated; /* -1 unknown, 0 false-free, 1 set */
	uint64_t journal_cluster_bitmap_false_free_count;
	int state;                /* -1 unknown, otherwise enum rh_wal_state */
	int transaction_kind;     /* -1 unknown, otherwise enum value */
	int max_entry_count;      /* -1 unknown, 4096 for a valid v1 WAL */
	uint64_t generation;
	char journal_uuid[37];
	uint64_t volume_serial;
	size_t write_boundaries;
};

struct rh_wal_run {
	uint64_t stream_offset;
	uint64_t device_offset;
	uint64_t length;
};

/* Immutable, physical target entry captured from a prepared/committed WAL. */
struct rh_wal_committed_entry {
	uint32_t action_id;
	uint64_t target_offset;
	uint64_t length;
	unsigned char before_hash[32];
	unsigned char after_hash[32];
	struct rh_write_semantic_target target;
};

/*
 * Immutable recovery view supplied to a semantic action verifier.  Bounded
 * accessors below expose the exact old payload and the whole transaction's
 * virtual pre-transaction filesystem; neither underlying writer nor payload
 * pointer is exposed to callback code.
 *
 * A verifier must derive every location and semantic field again from that
 * virtual filesystem and reproduce evidence_version, evidence_generation,
 * evidence_hash, staged_view_hash, and both semantic hashes.  Comparing the
 * stored digests alone is never sufficient.
 */
struct rh_wal_recovery_entry_view {
	uint64_t ordinal;
	uint32_t action_id;
	uint32_t reserved32;
	uint64_t target_offset;
	uint64_t length;
	unsigned char old_hash[32];
	unsigned char new_hash[32];
	struct rh_write_semantic_target target;
};

struct rh_wal_preimage;
struct rh_free_slot_component_seal;

struct rh_wal_action_verifier_context {
	uint32_t version;
	uint32_t action_id;
	enum rh_wal_transaction_kind transaction_kind;
	enum rh_wal_state state;
	uint64_t generation;
	uint64_t volume_serial;
	uint64_t journal_record;
	uint16_t journal_sequence;
	uint16_t reserved16;
	uint32_t reserved32;
	unsigned char journal_uuid[16];
	unsigned char transaction_uuid[16];
	unsigned char plan_hash[32];
	const struct rh_wal_preimage *preimage;
	const struct rh_wal_recovery_entry_view *entries;
	size_t entry_count;
};

typedef int (*rh_wal_action_verifier_fn)(
		const struct rh_wal_action_verifier_context *context);

struct rh_wal_action_verifier_slot {
	rh_wal_action_verifier_fn verify;
};

struct rh_wal {
	struct rh_writer *writer;
	struct rh_wal_observation *observation;
	uint32_t sector_size;
	uint64_t volume_serial;
	uint64_t journal_record;
	uint16_t journal_sequence;
	unsigned char journal_uuid[16];
	struct rh_wal_run *runs;
	size_t run_count;
	size_t run_capacity;
	uint64_t journal_record_device_offset;
	uint64_t journal_record_device_length;
	uint64_t data_size;
	unsigned char selected_header[4096];
	int selected_slot;
	uint64_t generation;
	enum rh_wal_state state;
	enum rh_wal_transaction_kind transaction_kind;
	uint64_t data_used;
	uint64_t entry_count;
	uint64_t target_bytes;
	unsigned char transaction_uuid[16];
	unsigned char plan_hash[32];
	int degraded_slot;
	int raw_recovery_locator;
	struct rh_wal_planned_entry *planned_entries;
	size_t planned_count;
	struct rh_wal_trace_action *trace_actions;
	size_t trace_count;
	size_t trace_capacity;
	/* Indexed by stable on-disk action ID; index zero is never used. */
	struct rh_wal_action_verifier_slot
		action_verifiers[RH_WRITE_KIND_COUNT + 1U];
};

int rh_uuid_parse(const char *text, unsigned char output[16]);
void rh_uuid_format(const unsigned char input[16], char output[37]);

/* Returns the stable roothealth exit code (0, 2, 3, or 5). */
int rh_wal_locate_and_validate(struct rh_wal *wal, struct rh_writer *writer,
		uint64_t expected_serial, const unsigned char expected_uuid[16],
		uint64_t expected_record, uint16_t expected_sequence,
		struct rh_wal_observation *observation);
/* Bounded boot locator: validates the provisioned record and WAL headers
 * directly, without the whole-volume uniqueness and ownership census. */
int rh_wal_locate_and_validate_bounded(struct rh_wal *wal,
		struct rh_writer *writer, uint64_t expected_serial,
		const unsigned char expected_uuid[16], uint64_t expected_record,
		uint16_t expected_sequence, struct rh_wal_observation *observation);
/* Repair-only retry used after the ordinary complete locator cannot mount. */
int rh_wal_locate_raw_interrupted_recovery(struct rh_wal *wal,
		struct rh_writer *writer, uint64_t expected_serial,
		const unsigned char expected_uuid[16], uint64_t expected_record,
		uint16_t expected_sequence, struct rh_wal_observation *observation);
int rh_wal_reconstruct_degraded(struct rh_wal *wal);
int rh_wal_install_backend(struct rh_wal *wal,
		enum rh_wal_transaction_kind transaction_kind);
int rh_wal_finalize_empty(struct rh_wal *wal);
int rh_wal_rollback(struct rh_wal *wal);
int rh_wal_committed_accept(struct rh_wal *wal,
		enum rh_wal_transaction_kind verified_kind);
int rh_wal_committed_entry_at(const struct rh_wal *wal, size_t ordinal,
		struct rh_wal_committed_entry *entry);
/* Validated immutable entry view for an interrupted transaction. */
int rh_wal_recovery_entry_at(struct rh_wal *wal, size_t ordinal,
		struct rh_wal_committed_entry *entry);
int rh_wal_recovery_entries(struct rh_wal *wal,
		struct rh_wal_committed_entry **entries, size_t *count);
size_t rh_wal_trace_action_count(const struct rh_wal *wal);
int rh_wal_trace_action_at(const struct rh_wal *wal, size_t ordinal,
		struct rh_wal_trace_action *action);
void rh_wal_uninstall_backend(struct rh_wal *wal);
int rh_wal_validate_action_order(enum rh_wal_transaction_kind transaction_kind,
		const enum rh_write_kind *kinds, size_t count);
int rh_wal_validate_mft_operation_pairs(const struct rh_wal *wal,
		const struct rh_write_operation *operations, size_t count);
/*
 * Produce the opaque WAL-exclusion component only from a fully validated,
 * write-safe locator result.  The canonical source hash is independent of
 * the mutable WAL header generation/state so recovery can reproduce it from
 * the same journal identity, run map, and writer restriction set.
 */
int rh_wal_create_free_slot_exclusion_seal(const struct rh_wal *wal,
		uint64_t correlation_generation,
		struct rh_free_slot_component_seal **output);
/* Recovery derives the same source-owned seal from the immutable old view. */
int rh_wal_preimage_create_free_slot_exclusion_seal(
		const struct rh_wal_preimage *preimage,
		uint64_t correlation_generation,
		struct rh_free_slot_component_seal **output);

/*
 * Register one exact stable action ID after rh_wal_locate_and_validate().
 * Duplicate registration is rejected. Native IDs 5/6 are owned by the built-in
 * indivisible replay verifier; callers cannot replace or opt around it through
 * this generic API.
 */
int rh_wal_register_action_verifier(struct rh_wal *wal, uint32_t action_id,
		rh_wal_action_verifier_fn verify);
uint64_t rh_wal_preimage_size(const struct rh_wal_preimage *preimage);
int rh_wal_preimage_read(const struct rh_wal_preimage *preimage,
		uint64_t offset, size_t length, void *buffer);
int rh_wal_preimage_range_excluded(const struct rh_wal_preimage *preimage,
		uint64_t offset, uint64_t length, int *excluded);
int rh_wal_entry_old_read(const struct rh_wal_action_verifier_context *context,
		uint64_t ordinal, uint64_t relative_offset, size_t length,
		void *buffer);

#ifdef ROOTHEALTH_WAL_TEST_HOOKS
void rh_wal_test_install_builtin_action_verifiers(struct rh_wal *wal);
int rh_wal_test_append_run(struct rh_wal *wal, uint64_t stream_offset,
		uint64_t device_offset, uint64_t length);
int rh_wal_test_dispatch_action_verifiers(struct rh_wal *wal,
		struct rh_writer *preimage,
		const struct rh_wal_recovery_entry_view *entries,
		const unsigned char *const *old_payloads, size_t count);
#endif

#endif
