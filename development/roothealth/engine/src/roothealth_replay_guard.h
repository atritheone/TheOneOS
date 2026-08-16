#ifndef ROOTHEALTH_REPLAY_GUARD_H
#define ROOTHEALTH_REPLAY_GUARD_H

#include <stddef.h>
#include <stdint.h>

#define RH_REPLAY_PAGE_SIZE 4096U
#define RH_REPLAY_SECTOR_SIZE 512U
#define RH_REPLAY_MIN_LOGFILE_SIZE (50U * RH_REPLAY_PAGE_SIZE)
/*
 * T1OS's pinned d4 formatter caps $LogFile at exactly 64 MiB and every
 * supported image/resize path preserves that stream.  This is a release-
 * profile invariant checked by the builder, not a claim about arbitrary NTFS.
 */
#define RH_REPLAY_MAX_LOGFILE_SIZE (64U * 1024U * 1024U)
#define RH_REPLAY_MAX_ACTION_SIZE (64U * 1024U)
#define RH_REPLAY_MAX_IO_PAGES 16U
#define RH_REPLAY_MAX_RECORD_PAGES 18U
#define RH_REPLAY_MAX_ACTIONS 4096U
#define RH_REPLAY_ACTION_COUNT 38U
#define RH_REPLAY_SOURCE_UNKNOWN UINT64_MAX

enum rh_replay_action_class {
	RH_REPLAY_ACTION_DENY = 0,
	RH_REPLAY_ACTION_CHECKPOINT,
	RH_REPLAY_ACTION_CONTROL,
	RH_REPLAY_ACTION_MFT_WRITE,
	RH_REPLAY_ACTION_INDX_WRITE,
	RH_REPLAY_ACTION_RAW_WRITE,
	RH_REPLAY_ACTION_BITMAP_WRITE,
	RH_REPLAY_ACTION_TRANSACTION_END
};

struct rh_replay_action_policy {
	const char *name;
	uint64_t undo_mask;
	enum rh_replay_action_class action_class;
	const char *deny_reason;
};

struct rh_replay_geometry {
	uint32_t page_size;
	uint32_t cluster_size;
	uint32_t mft_record_size;
	uint32_t index_record_size;
	uint64_t logfile_size;
	uint64_t volume_clusters;
	uint32_t sequence_bits;
	uint16_t client_sequence;
	uint16_t client_index;
};

struct rh_replay_page_view {
	uint16_t next_record_offset;
	uint16_t page_count;
	uint16_t page_position;
	uint32_t flags;
	uint32_t file_offset;
	uint64_t copy_value;
	uint64_t last_end_lsn;
};

struct rh_replay_action_view {
	uint32_t record_type;
	uint16_t redo_operation;
	uint16_t undo_operation;
	uint16_t lcn_count;
	uint16_t cluster_index;
	uint16_t record_offset;
	uint16_t attribute_offset;
	uint16_t redo_length;
	uint16_t undo_length;
	uint16_t record_flags;
	uint32_t transaction_id;
	uint64_t this_lsn;
	uint64_t previous_lsn;
	uint64_t undo_next_lsn;
	uint64_t target_vcn;
	uint64_t first_lcn;
	size_t record_size;
	size_t redo_data_offset;
	size_t undo_data_offset;
	size_t extra_data_offset;
	size_t extra_data_length;
	size_t target_slice_offset;
	size_t target_object_size;
	enum rh_replay_action_class action_class;
};

const struct rh_replay_action_policy *rh_replay_action_policy(unsigned int op);
int rh_replay_guard_profile(const struct rh_replay_geometry *geometry);
int rh_replay_guard_unprotect_rcrd(unsigned char *page, size_t length,
		struct rh_replay_page_view *view);
int rh_replay_guard_action(const unsigned char *record, size_t record_size,
		const struct rh_replay_geometry *geometry,
		uint64_t source_byte_offset, struct rh_replay_action_view *view);

#endif
