#ifndef ROOTHEALTH_POLICY_INTERNAL_H
#define ROOTHEALTH_POLICY_INTERNAL_H

#include <stddef.h>
#include <stdint.h>

#include "roothealth_policy.h"

/*
 * Private output of an exhaustive diagnostic pass.  Repair adapters do not
 * include this header and cannot manufacture individual policy facts.
 */
struct rh_bitmap_census_result {
	enum rh_policy_target_object object;
	uint64_t generation;
	unsigned char census_hash[32];
	uint64_t final_overlay_generation;
	unsigned char final_overlay_hash[32];
	int completed;
	int identity_bound;
	int complete_mft_census;
	int complete_attribute_census;
	int complete_runlist_census;
	int complete_namespace_census;
	int complete_index_census;
	int complete_cluster_census;
	int no_io_uncertainty;
	int no_duplicate_clusters;
	int targets_outside_wal;
	int ownership_exact;
	int sets_proven_live;
	int clears_proven_unreferenced;
	int index_tree_complete;
	int child_vcns_valid;
	int indx_blocks_valid;
	int reachable_set_exact;
	int no_unresolved_blocks;
	int data_preserving;
	int final_overlay_valid;
};

int rh_policy_seal_bitmap_census(
		const struct rh_bitmap_census_result *result,
		const struct rh_policy_target_identity *targets,
		size_t target_count, struct rh_policy_evidence **output);

#ifdef ROOTHEALTH_REPAIR_TESTING
int rh_policy_evidence_test_copy_seal(
		const struct rh_policy_evidence *evidence,
		unsigned char output[32]);
#endif

#endif
