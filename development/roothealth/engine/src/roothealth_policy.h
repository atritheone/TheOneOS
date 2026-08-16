#ifndef ROOTHEALTH_POLICY_H
#define ROOTHEALTH_POLICY_H

#include <stddef.h>
#include <stdint.h>

#include "problem.h"
#include "roothealth_write.h"

#define RH_POLICY_ATTRIBUTE_NAME_PREFIX_MAX 16

enum rh_policy_scope {
	RH_POLICY_SCOPE_PROBLEM = 1,
	RH_POLICY_SCOPE_AGGREGATE = 2
};

enum rh_policy_configured_decision {
	RH_POLICY_CONFIG_DENY = 0,
	RH_POLICY_CONFIG_CONDITIONAL = 1
};

enum rh_policy_final_decision {
	RH_POLICY_FINAL_DENIED = 0,
	RH_POLICY_FINAL_AUTHORIZED = 1
};

enum rh_evidence_state {
	RH_EVIDENCE_UNKNOWN = -1,
	RH_EVIDENCE_FALSE = 0,
	RH_EVIDENCE_TRUE = 1
};

enum rh_policy_fact {
	RH_FACT_IDENTITY_BOUND = 0,
	RH_FACT_COMPLETE_MFT_CENSUS,
	RH_FACT_COMPLETE_ATTRIBUTE_CENSUS,
	RH_FACT_COMPLETE_RUNLIST_CENSUS,
	RH_FACT_COMPLETE_NAMESPACE_CENSUS,
	RH_FACT_COMPLETE_INDEX_CENSUS,
	RH_FACT_COMPLETE_CLUSTER_CENSUS,
	RH_FACT_NO_IO_UNCERTAINTY,
	RH_FACT_NO_DUPLICATE_CLUSTERS,
	RH_FACT_TARGETS_OUTSIDE_WAL,
	RH_FACT_OWNERSHIP_EXACT,
	RH_FACT_SETS_PROVEN_LIVE,
	RH_FACT_CLEARS_PROVEN_UNREFERENCED,
	RH_FACT_INDEX_TREE_COMPLETE,
	RH_FACT_CHILD_VCNS_VALID,
	RH_FACT_INDX_BLOCKS_VALID,
	RH_FACT_REACHABLE_SET_EXACT,
	RH_FACT_NO_UNRESOLVED_BLOCKS,
	RH_FACT_DATA_PRESERVING,
	RH_FACT_FINAL_OVERLAY_VALID,
	RH_POLICY_FACT_COUNT
};

enum rh_policy_profile {
	RH_POLICY_PROFILE_NONE = 0,
	RH_POLICY_PROFILE_CLUSTER_BITMAP,
	RH_POLICY_PROFILE_MFT_BITMAP,
	RH_POLICY_PROFILE_INDEX_BITMAP
};

enum rh_policy_target_object {
	RH_POLICY_TARGET_NONE = 0,
	RH_POLICY_TARGET_VOLUME_BITMAP,
	RH_POLICY_TARGET_MFT_BITMAP,
	RH_POLICY_TARGET_INDEX_BITMAP
};

#define ROOTHEALTH_PROBLEM_POLICY(code, decision)
#define ROOTHEALTH_AGGREGATE_POLICY(name, decision) RH_POLICY_AGGREGATE_##name,
enum rh_policy_aggregate_id {
#include "roothealth_problem_policy.def"
	RH_POLICY_AGGREGATE_COUNT
};
#undef ROOTHEALTH_PROBLEM_POLICY
#undef ROOTHEALTH_AGGREGATE_POLICY

struct rh_policy_definition {
	enum rh_policy_scope scope;
	const char *name;
	int problem_code;
	enum rh_policy_aggregate_id aggregate_id;
	enum rh_policy_configured_decision configured;
};

struct rh_policy_implementation {
	enum rh_policy_profile profile;
	const char *evidence_id;
	const char *source_pass;
	uint32_t allowed_action_mask;
	uint64_t required_fact_mask;
};

/*
 * This is an exact physical target identity, not a caller-selected byte range.
 * Instances are copied into sealed pass evidence and returned read-only.
 */
struct rh_policy_target_identity {
	enum rh_policy_target_object object;
	enum rh_write_kind action_kind;
	enum rh_write_target_object write_object;
	uint16_t semantic_flags;
	uint64_t mft_record;
	uint16_t mft_sequence;
	uint16_t attribute_instance;
	uint32_t attribute_type;
	uint16_t attribute_name_length;
	uint8_t attribute_name_prefix_length;
	uint16_t attribute_name_prefix[RH_POLICY_ATTRIBUTE_NAME_PREFIX_MAX];
	unsigned char attribute_name_hash[32];
	uint64_t lowest_vcn;
	uint64_t logical_vcn;
	uint64_t lcn;
	uint64_t logical_offset;
	uint64_t logical_length;
	uint64_t physical_offset;
	uint64_t physical_length;
	uint64_t semantic_offset;
	uint64_t semantic_length;
	uint64_t operation_ordinal;
	uint64_t writer_checkpoint;
	unsigned char staged_plan_hash[32];
	unsigned char before_hash[32];
	unsigned char after_hash[32];
	uint64_t census_generation;
	unsigned char census_hash[32];
	uint8_t changes_set_bits;
	uint8_t changes_clear_bits;
};

struct rh_policy_evidence;

struct rh_policy_authorization {
	const struct rh_policy_definition *definition;
	const struct rh_policy_implementation *implementation;
	enum rh_policy_final_decision decision;
	size_t target_ordinal;
	struct rh_policy_target_identity target;
	uint64_t evidence_generation;
	unsigned char evidence_hash[32];
	uint64_t final_overlay_generation;
	unsigned char final_overlay_hash[32];
	uint64_t writer_checkpoint;
	unsigned char staged_plan_hash[32];
	uint64_t required_fact_mask;
	enum rh_evidence_state facts[RH_POLICY_FACT_COUNT];
};

size_t rh_policy_definition_count(void);
const struct rh_policy_definition *rh_policy_definition_at(size_t index);
const struct rh_policy_definition *rh_policy_problem(problem_code_t code);
const struct rh_policy_definition *rh_policy_aggregate(const char *name);
const struct rh_policy_implementation *rh_policy_implementation(
		const struct rh_policy_definition *definition);
const char *rh_policy_fact_name(enum rh_policy_fact fact);
size_t rh_policy_evidence_target_count(const struct rh_policy_evidence *evidence);
const struct rh_policy_target_identity *rh_policy_evidence_target(
		const struct rh_policy_evidence *evidence, size_t target_ordinal);
enum rh_policy_final_decision rh_policy_authorize_operation(
		const struct rh_policy_definition *definition,
		const struct rh_policy_evidence *evidence, size_t target_ordinal,
		const struct rh_writer *writer, size_t operation_ordinal,
		struct rh_policy_authorization *record);
void rh_policy_evidence_destroy(struct rh_policy_evidence *evidence);

#endif
