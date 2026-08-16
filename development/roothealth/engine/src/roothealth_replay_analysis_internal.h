#ifndef ROOTHEALTH_REPLAY_ANALYSIS_INTERNAL_H
#define ROOTHEALTH_REPLAY_ANALYSIS_INTERNAL_H

#include "roothealth_replay_analysis.h"

#define RH_REPLAY_NATIVE_NAME_MAX 510U

struct rh_open_attribute {
	uint32_t key;
	uint32_t type;
	uint64_t file_reference;
	uint32_t bytes_per_index;
	uint64_t open_lsn;
	uint64_t source_lsn;
	uint16_t name_bytes;
	uint8_t source_kind;
	uint8_t expects_name;
	uint8_t name_present;
	uint8_t present;
	unsigned char name_utf16le[RH_REPLAY_NATIVE_NAME_MAX];
};

struct rh_replay_analysis_export {
	const struct rh_replay_analysis_record *records;
	const struct rh_replay_action_view *views;
	size_t record_count;
	const struct rh_replay_geometry *geometry;
	uint64_t synced_lsn;
	uint64_t committed_lsn;
	uint64_t analysis_start_lsn;
	const struct rh_open_attribute *open_attributes;
	size_t open_attribute_capacity;
	uint16_t open_entry_size;
	const struct rh_replay_analysis_result *result;
};

typedef int (*rh_replay_analysis_complete_consumer)(
	const struct rh_replay_analysis_export *completed, void *opaque);

/*
 * Private completed-pass export.  The consumer runs only after all analysis
 * invariants have succeeded and before temporary tables are released.  It
 * must copy any evidence it retains.
 */
int rh_replay_analysis_plan_export(struct rh_replay_analysis_record *records,
		size_t record_count, const struct rh_replay_geometry *geometry,
		uint64_t synced_lsn, uint64_t committed_lsn,
		rh_replay_analysis_complete_consumer consumer, void *consumer_opaque,
		struct rh_replay_analysis_result *result);

#endif
