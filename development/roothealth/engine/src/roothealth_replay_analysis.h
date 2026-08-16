#ifndef ROOTHEALTH_REPLAY_ANALYSIS_H
#define ROOTHEALTH_REPLAY_ANALYSIS_H

#include "roothealth_replay_guard.h"

#include <stddef.h>
#include <stdint.h>

#define RH_REPLAY_PLAN_REDO 1U
#define RH_REPLAY_PLAN_UNDO 2U

struct rh_replay_analysis_record {
	const unsigned char *bytes;
	size_t size;
	unsigned int plan_flags;
	uint64_t effective_lcn;
	int has_effective_lcn;
};

struct rh_replay_analysis_result {
	unsigned int checkpoint_records;
	unsigned int transaction_tables;
	unsigned int open_attribute_tables;
	unsigned int attribute_name_tables;
	unsigned int dirty_page_tables;
	unsigned int dynamic_open_attributes;
	unsigned int delete_dirty_controls;
	unsigned int hotfix_controls;
	unsigned int mutation_records;
	unsigned int winner_redos;
	unsigned int loser_redos;
	unsigned int loser_undos;
};

struct rh_native_authority_census;

int rh_replay_analysis_plan(struct rh_replay_analysis_record *records,
		size_t record_count, const struct rh_replay_geometry *geometry,
		uint64_t synced_lsn, uint64_t committed_lsn,
		struct rh_replay_analysis_result *result);
int rh_replay_analysis_plan_native(
		struct rh_replay_analysis_record *records, size_t record_count,
		const struct rh_replay_geometry *geometry, uint64_t synced_lsn,
		uint64_t committed_lsn, uint64_t correlation_generation,
		struct rh_replay_analysis_result *result,
		struct rh_native_authority_census **census);

#endif
