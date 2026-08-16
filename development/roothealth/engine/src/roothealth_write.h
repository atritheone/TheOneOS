/*
 * RootHealth typed write planner.
 *
 * This interface is deliberately independent of ntfsck globals.  A later
 * internal-WAL backend can replace the direct backend without changing repair
 * passes.  The direct backend accepts only operations which are independently
 * restartable through NTFS redundancy or the native $LogFile protocol.
 */
#ifndef ROOTHEALTH_WRITE_H
#define ROOTHEALTH_WRITE_H

#include <stddef.h>
#include <stdint.h>
#include <sys/types.h>

/*
 * Stable typed-action ABI.  The on-disk WAL action id is the enum value plus
 * one; zero is reserved as invalid.  Keep the explicit values stable once a
 * release journal can contain them.  Coarse "repair" labels are deliberately
 * not accepted: every physical write must retain its semantic family.
 */
enum rh_write_kind {
	RH_WRITE_BOOT_PRIMARY = 0,
	RH_WRITE_BOOT_BACKUP = 1,
	RH_WRITE_MFT_PRIMARY = 2,
	RH_WRITE_MFT_MIRROR = 3,
	RH_WRITE_LOGFILE_REDO = 4,
	RH_WRITE_LOGFILE_RESTART = 5,
	RH_WRITE_MFT_RECORD = 6,
	RH_WRITE_ATTRIBUTE_LIST = 7,
	RH_WRITE_RUNLIST_MAPPING_PAIRS = 8,
	RH_WRITE_ATTRIBUTE_DATA = 9,
	RH_WRITE_INDEX_ROOT = 10,
	RH_WRITE_INDEX_ALLOCATION = 11,
	RH_WRITE_INDEX_BITMAP = 12,
	RH_WRITE_CLUSTER_DATA = 13,
	RH_WRITE_RECOVERY_NAMESPACE = 14,
	RH_WRITE_REPARSE_INDEX = 15,
	RH_WRITE_SECURE_SDS = 16,
	RH_WRITE_SECURE_SDH = 17,
	RH_WRITE_SECURE_SII = 18,
	RH_WRITE_UPCASE_DATA = 19,
	RH_WRITE_ATTRDEF_DATA = 20,
	RH_WRITE_BITMAP_MFT = 21,
	RH_WRITE_BITMAP_CLUSTER = 22,
	RH_WRITE_VOLUME_DIRTY_SET = 23,
	RH_WRITE_VOLUME_DIRTY_CLEAR = 24,
	RH_WRITE_KIND_COUNT = 25
};

#define RH_WRITE_ACTION_ID(kind) ((uint32_t)(kind) + 1U)

enum rh_write_target_object {
	RH_WRITE_TARGET_INVALID = 0,
	RH_WRITE_TARGET_BOOT_PRIMARY = 1,
	RH_WRITE_TARGET_BOOT_BACKUP = 2,
	RH_WRITE_TARGET_MFT_RECORD_PRIMARY = 3,
	RH_WRITE_TARGET_MFT_RECORD_MIRROR = 4,
	RH_WRITE_TARGET_NONRESIDENT_ATTRIBUTE = 5,
	RH_WRITE_TARGET_PROVEN_FREE_ALLOCATION = 6
};

#define RH_WRITE_TARGET_PRIMARY UINT16_C(0x0001)
#define RH_WRITE_TARGET_MIRROR UINT16_C(0x0002)
#define RH_WRITE_TARGET_RESIDENT UINT16_C(0x0004)
#define RH_WRITE_TARGET_NONRESIDENT UINT16_C(0x0008)
/* External exhaustive evidence proves the target object was free before this
 * transaction.  The flag is never inferred from zero or stale payload bytes. */
#define RH_WRITE_TARGET_PRETRANSACTION_FREE UINT16_C(0x0010)
#define RH_WRITE_TARGET_SET_ONLY UINT16_C(0x0020)
#define RH_WRITE_TARGET_CLEAR_ONLY UINT16_C(0x0040)
#define RH_WRITE_TARGET_NATIVE_LOG_DERIVED UINT16_C(0x0080)
#define RH_WRITE_TARGET_FLAGS_MASK UINT16_C(0x00ff)

struct rh_write_semantic_target {
	uint32_t seal_version;
	enum rh_write_target_object object;
	uint64_t owner_mft_record;
	uint16_t owner_sequence;
	uint16_t attribute_instance;
	uint32_t attribute_type;
	uint16_t attribute_name_length;
	uint16_t flags;
	uint32_t evidence_version;
	unsigned char attribute_name_hash[32];
	int64_t lowest_vcn;
	int64_t logical_vcn;
	uint64_t logical_offset;
	uint64_t logical_length;
	uint64_t semantic_target_offset;
	uint64_t semantic_target_length;
	int64_t lcn;
	uint64_t evidence_generation;
	unsigned char evidence_hash[32];
	unsigned char staged_view_hash[32];
	unsigned char semantic_before_hash[32];
	unsigned char semantic_after_hash[32];
	int finalized;
};

struct rh_write_operation {
	enum rh_write_kind kind;
	uint64_t offset;
	size_t length;
	unsigned char *before;
	unsigned char *after;
	char before_sha256[65];
	char after_sha256[65];
	struct rh_write_semantic_target target;
	size_t write_boundaries;
	size_t sync_ordinal;
	int sync_completed;
	int readback_verified;
	int verified;
};

struct rh_write_backend_ops {
	/* A persistent backend must durably record undo before raw mutation. */
	int persistent_undo;
	int (*begin)(void *opaque, const struct rh_write_operation *ops,
			size_t count);
	int (*before_write)(void *opaque, size_t ordinal,
			const struct rh_write_operation *op);
	int (*after_write)(void *opaque, size_t ordinal,
			const struct rh_write_operation *op);
	int (*barrier)(void *opaque, size_t completed);
	int (*finish)(void *opaque, size_t completed);
	void (*abort)(void *opaque, size_t completed);
};

struct rh_write_range {
	uint64_t offset;
	uint64_t length;
};

struct rh_writer {
	char *path;
	int read_fd;
	int write_fd;
	uint64_t device_size;
	dev_t device_id;
	ino_t inode_id;
	struct rh_write_operation *operations;
	size_t operation_count;
	size_t operation_capacity;
	uint64_t planned_bytes;
	size_t last_verified_ordinal;
	size_t sync_count;
	size_t write_boundaries;
	int commit_started;
	int commit_completed;
	int lock_held;
	const struct rh_write_backend_ops *backend;
	void *backend_opaque;
	struct rh_write_range *excluded;
	size_t excluded_count;
	size_t excluded_capacity;
	struct rh_write_range *raw_wal_allowed;
	size_t raw_wal_allowed_count;
	size_t raw_wal_allowed_capacity;
};

const char *rh_write_kind_name(enum rh_write_kind kind);
int rh_writer_open(struct rh_writer *writer, const char *path);
void rh_writer_close(struct rh_writer *writer);
void rh_writer_reset_plan(struct rh_writer *writer);
int rh_writer_set_backend(struct rh_writer *writer,
		const struct rh_write_backend_ops *ops, void *opaque);
int rh_writer_exclude(struct rh_writer *writer, uint64_t offset,
		uint64_t length);
int rh_writer_allow_raw_wal(struct rh_writer *writer, uint64_t offset,
		uint64_t length);
int rh_writer_restore_restrictions(struct rh_writer *writer,
		size_t excluded_count, size_t raw_wal_allowed_count);
int rh_writer_range_excluded(const struct rh_writer *writer, uint64_t offset,
		uint64_t length);
int rh_writer_read(struct rh_writer *writer, uint64_t offset, size_t length,
		void *buffer);
int rh_writer_staged_read(struct rh_writer *writer, size_t operation_count,
		uint64_t offset, size_t length, void *buffer);
int rh_writer_current_read(struct rh_writer *writer, uint64_t offset,
		size_t length, void *buffer);
int rh_writer_plan(struct rh_writer *writer, enum rh_write_kind kind,
		uint64_t offset, size_t length, const void *after);
int rh_writer_plan_typed(struct rh_writer *writer, enum rh_write_kind kind,
		uint64_t offset, size_t length, const void *after,
		const struct rh_write_semantic_target *target);
int rh_write_semantic_target_valid(enum rh_write_kind kind,
		const struct rh_write_semantic_target *target, uint64_t offset,
		size_t length, int require_finalized);
int rh_write_semantic_payload_hash(enum rh_write_kind kind,
		const struct rh_write_semantic_target *target, uint64_t offset,
		size_t length, const unsigned char *payload, unsigned char output[32]);
int rh_write_operation_semantics_valid(const struct rh_write_operation *op,
		int require_finalized);
int rh_writer_finalize_target(struct rh_writer *writer, size_t operation_ordinal,
		uint32_t evidence_version, uint64_t evidence_generation,
		const unsigned char evidence_hash[32],
		const unsigned char staged_view_hash[32]);
size_t rh_writer_plan_checkpoint(const struct rh_writer *writer);
int rh_writer_discard_after(struct rh_writer *writer, size_t checkpoint);
int rh_writer_plan_hash(const struct rh_writer *writer, size_t operation_count,
		unsigned char output[32]);
int rh_writer_commit(struct rh_writer *writer);
int rh_writer_sync(struct rh_writer *writer);
int rh_writer_pause_for_rescan(struct rh_writer *writer);
int rh_writer_resume_after_rescan(struct rh_writer *writer);

/* Raw backend access is confined to validated WAL DATA extents. */
ssize_t rh_writer_raw_pread(struct rh_writer *writer, void *buffer,
		size_t length, uint64_t offset);
ssize_t rh_writer_raw_pwrite(struct rh_writer *writer, const void *buffer,
		size_t length, uint64_t offset);
int rh_writer_raw_begin(struct rh_writer *writer);
int rh_writer_raw_sync(struct rh_writer *writer);
int rh_writer_raw_end(struct rh_writer *writer);
int rh_writer_recovery_write(struct rh_writer *writer, uint64_t offset,
		size_t length, const void *data);

void rh_sha256(const void *data, size_t length, unsigned char output[32]);
void rh_sha256_hex(const void *data, size_t length, char output[65]);

#endif
