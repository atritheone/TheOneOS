/* ROOTHEALTH_REPAIR_ROLE(DIAGNOSTIC) ROOTHEALTH_IO_ROLE(PLANNER) */
#include "config.h"

#include <errno.h>
#include <limits.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include "roothealth_policy_internal.h"

#define RH_ACTION_MASK(kind) (UINT32_C(1) << (unsigned int)(kind))
#define RH_FACT_MASK(fact) (UINT64_C(1) << (unsigned int)(fact))
#define RH_PROBLEM_ARRAY_SIZE ((size_t)PR_NAMESPACE_LINK_COUNT_MISMATCH + 1U)
#define RH_EVIDENCE_MAGIC UINT64_C(0x5248504f4c494359)
#define RH_EVIDENCE_VERSION UINT32_C(2)
#define RH_EVIDENCE_SEAL_HEADER_SIZE \
	(104U + 4U * (size_t)RH_POLICY_FACT_COUNT)
#define RH_EVIDENCE_SEAL_TARGET_SIZE 323U

#define DENY RH_POLICY_CONFIG_DENY
#define CONDITIONAL RH_POLICY_CONFIG_CONDITIONAL
#define ROOTHEALTH_PROBLEM_POLICY(code, decision) \
	{ RH_POLICY_SCOPE_PROBLEM, #code, code, RH_POLICY_AGGREGATE_COUNT, decision },
#define ROOTHEALTH_AGGREGATE_POLICY(name, decision)
static const struct rh_policy_definition rh_problem_definitions[] = {
#include "roothealth_problem_policy.def"
};
#undef ROOTHEALTH_PROBLEM_POLICY
#undef ROOTHEALTH_AGGREGATE_POLICY
#define ROOTHEALTH_PROBLEM_POLICY(code, decision)
#define ROOTHEALTH_AGGREGATE_POLICY(name, decision) \
	{ RH_POLICY_SCOPE_AGGREGATE, #name, -1, RH_POLICY_AGGREGATE_##name, decision },
static const struct rh_policy_definition rh_aggregate_definitions[] = {
#include "roothealth_problem_policy.def"
};
#undef ROOTHEALTH_PROBLEM_POLICY
#undef ROOTHEALTH_AGGREGATE_POLICY
#undef CONDITIONAL
#undef DENY

static const char *const rh_fact_names[RH_POLICY_FACT_COUNT] = {
	"identity-bound",
	"complete-mft-census",
	"complete-attribute-census",
	"complete-runlist-census",
	"complete-namespace-census",
	"complete-index-census",
	"complete-cluster-census",
	"no-io-uncertainty",
	"no-duplicate-clusters",
	"targets-outside-wal",
	"ownership-exact",
	"sets-proven-live",
	"clears-proven-unreferenced",
	"index-tree-complete",
	"child-vcns-valid",
	"indx-blocks-valid",
	"reachable-set-exact",
	"no-unresolved-blocks",
	"data-preserving",
	"final-overlay-valid",
};

#define RH_CLUSTER_BITMAP_FACTS ( \
	RH_FACT_MASK(RH_FACT_IDENTITY_BOUND) | \
	RH_FACT_MASK(RH_FACT_COMPLETE_MFT_CENSUS) | \
	RH_FACT_MASK(RH_FACT_COMPLETE_ATTRIBUTE_CENSUS) | \
	RH_FACT_MASK(RH_FACT_COMPLETE_RUNLIST_CENSUS) | \
	RH_FACT_MASK(RH_FACT_COMPLETE_CLUSTER_CENSUS) | \
	RH_FACT_MASK(RH_FACT_NO_IO_UNCERTAINTY) | \
	RH_FACT_MASK(RH_FACT_NO_DUPLICATE_CLUSTERS) | \
	RH_FACT_MASK(RH_FACT_TARGETS_OUTSIDE_WAL) | \
	RH_FACT_MASK(RH_FACT_OWNERSHIP_EXACT) | \
	RH_FACT_MASK(RH_FACT_SETS_PROVEN_LIVE) | \
	RH_FACT_MASK(RH_FACT_CLEARS_PROVEN_UNREFERENCED) | \
	RH_FACT_MASK(RH_FACT_DATA_PRESERVING) | \
	RH_FACT_MASK(RH_FACT_FINAL_OVERLAY_VALID))

#define RH_MFT_BITMAP_FACTS ( \
	RH_FACT_MASK(RH_FACT_IDENTITY_BOUND) | \
	RH_FACT_MASK(RH_FACT_COMPLETE_MFT_CENSUS) | \
	RH_FACT_MASK(RH_FACT_COMPLETE_NAMESPACE_CENSUS) | \
	RH_FACT_MASK(RH_FACT_NO_IO_UNCERTAINTY) | \
	RH_FACT_MASK(RH_FACT_TARGETS_OUTSIDE_WAL) | \
	RH_FACT_MASK(RH_FACT_SETS_PROVEN_LIVE) | \
	RH_FACT_MASK(RH_FACT_CLEARS_PROVEN_UNREFERENCED) | \
	RH_FACT_MASK(RH_FACT_DATA_PRESERVING) | \
	RH_FACT_MASK(RH_FACT_FINAL_OVERLAY_VALID))

#define RH_INDEX_BITMAP_FACTS ( \
	RH_FACT_MASK(RH_FACT_IDENTITY_BOUND) | \
	RH_FACT_MASK(RH_FACT_COMPLETE_MFT_CENSUS) | \
	RH_FACT_MASK(RH_FACT_COMPLETE_NAMESPACE_CENSUS) | \
	RH_FACT_MASK(RH_FACT_COMPLETE_INDEX_CENSUS) | \
	RH_FACT_MASK(RH_FACT_NO_IO_UNCERTAINTY) | \
	RH_FACT_MASK(RH_FACT_TARGETS_OUTSIDE_WAL) | \
	RH_FACT_MASK(RH_FACT_INDEX_TREE_COMPLETE) | \
	RH_FACT_MASK(RH_FACT_CHILD_VCNS_VALID) | \
	RH_FACT_MASK(RH_FACT_INDX_BLOCKS_VALID) | \
	RH_FACT_MASK(RH_FACT_REACHABLE_SET_EXACT) | \
	RH_FACT_MASK(RH_FACT_NO_UNRESOLVED_BLOCKS) | \
	RH_FACT_MASK(RH_FACT_DATA_PRESERVING) | \
	RH_FACT_MASK(RH_FACT_FINAL_OVERLAY_VALID))

#define RH_IMPLEMENTATION(profile_value, evidence, pass, action, facts_value) \
	{ profile_value, evidence, pass, RH_ACTION_MASK(action), facts_value }

/* Enum-indexed: a problem.h rename or typo is a compile failure, not a downgrade. */
static const struct rh_policy_implementation
rh_problem_implementations[RH_PROBLEM_ARRAY_SIZE] = {
	[PR_MFT_BITMAP_MISMATCH] = RH_IMPLEMENTATION(
		RH_POLICY_PROFILE_MFT_BITMAP, "mft-bitmap-full-ledger-v1",
		"mft-bitmap-census", RH_WRITE_BITMAP_MFT, RH_MFT_BITMAP_FACTS),
	[PR_IDX_BITMAP_MISMATCH] = RH_IMPLEMENTATION(
		RH_POLICY_PROFILE_INDEX_BITMAP, "index-bitmap-set-only-v1",
		"index-tree-census", RH_WRITE_INDEX_BITMAP, RH_INDEX_BITMAP_FACTS),
	[PR_CLUSTER_BITMAP_MISMATCH] = RH_IMPLEMENTATION(
		RH_POLICY_PROFILE_CLUSTER_BITMAP, "cluster-bitmap-exhaustive-v1",
		"bitmap-census", RH_WRITE_BITMAP_CLUSTER, RH_CLUSTER_BITMAP_FACTS),
};

static const struct rh_policy_implementation
rh_aggregate_implementations[RH_POLICY_AGGREGATE_COUNT] = {
	[RH_POLICY_AGGREGATE_MFT_BITMAP] = RH_IMPLEMENTATION(
		RH_POLICY_PROFILE_MFT_BITMAP, "mft-bitmap-full-ledger-v1",
		"mft-bitmap-census", RH_WRITE_BITMAP_MFT, RH_MFT_BITMAP_FACTS),
	[RH_POLICY_AGGREGATE_INDEX_BITMAP] = RH_IMPLEMENTATION(
		RH_POLICY_PROFILE_INDEX_BITMAP, "index-bitmap-set-only-v1",
		"index-tree-census", RH_WRITE_INDEX_BITMAP, RH_INDEX_BITMAP_FACTS),
	[RH_POLICY_AGGREGATE_CLUSTER_BITMAP] = RH_IMPLEMENTATION(
		RH_POLICY_PROFILE_CLUSTER_BITMAP, "cluster-bitmap-exhaustive-v1",
		"bitmap-census", RH_WRITE_BITMAP_CLUSTER, RH_CLUSTER_BITMAP_FACTS),
};

struct rh_policy_evidence {
	uint64_t magic;
	uint32_t version;
	enum rh_policy_target_object object;
	uint64_t generation;
	unsigned char census_hash[32];
	uint64_t final_overlay_generation;
	unsigned char final_overlay_hash[32];
	enum rh_evidence_state facts[RH_POLICY_FACT_COUNT];
	struct rh_policy_target_identity *targets;
	size_t target_count;
	unsigned char seal[32];
};

_Static_assert(sizeof(rh_problem_definitions) /
		sizeof(rh_problem_definitions[0]) ==
		(size_t)(PR_NAMESPACE_LINK_COUNT_MISMATCH - PR_PRE_SCAN_MFT + 1),
	"roothealth problem policy must cover every problem_code_t");
_Static_assert(sizeof(rh_aggregate_definitions) /
		sizeof(rh_aggregate_definitions[0]) == RH_POLICY_AGGREGATE_COUNT,
	"roothealth aggregate policy must cover every aggregate");
_Static_assert(RH_WRITE_KIND_COUNT <= 32,
	"roothealth policy action mask is too narrow");

static int rh_all_zero(const unsigned char *bytes, size_t length)
{
	size_t i;

	for (i = 0; i < length; i++)
		if (bytes[i])
			return 0;
	return 1;
}

static enum rh_evidence_state rh_known_state(int completed, int value)
{
	if (!completed)
		return RH_EVIDENCE_UNKNOWN;
	return value ? RH_EVIDENCE_TRUE : RH_EVIDENCE_FALSE;
}

static void rh_evidence_fill_facts(struct rh_policy_evidence *evidence,
		const struct rh_bitmap_census_result *result)
{
#define RH_SET_FACT(fact, member) \
	evidence->facts[fact] = rh_known_state(result->completed, result->member)
	RH_SET_FACT(RH_FACT_IDENTITY_BOUND, identity_bound);
	RH_SET_FACT(RH_FACT_COMPLETE_MFT_CENSUS, complete_mft_census);
	RH_SET_FACT(RH_FACT_COMPLETE_ATTRIBUTE_CENSUS, complete_attribute_census);
	RH_SET_FACT(RH_FACT_COMPLETE_RUNLIST_CENSUS, complete_runlist_census);
	RH_SET_FACT(RH_FACT_COMPLETE_NAMESPACE_CENSUS, complete_namespace_census);
	RH_SET_FACT(RH_FACT_COMPLETE_INDEX_CENSUS, complete_index_census);
	RH_SET_FACT(RH_FACT_COMPLETE_CLUSTER_CENSUS, complete_cluster_census);
	RH_SET_FACT(RH_FACT_NO_IO_UNCERTAINTY, no_io_uncertainty);
	RH_SET_FACT(RH_FACT_NO_DUPLICATE_CLUSTERS, no_duplicate_clusters);
	RH_SET_FACT(RH_FACT_TARGETS_OUTSIDE_WAL, targets_outside_wal);
	RH_SET_FACT(RH_FACT_OWNERSHIP_EXACT, ownership_exact);
	RH_SET_FACT(RH_FACT_SETS_PROVEN_LIVE, sets_proven_live);
	RH_SET_FACT(RH_FACT_CLEARS_PROVEN_UNREFERENCED, clears_proven_unreferenced);
	RH_SET_FACT(RH_FACT_INDEX_TREE_COMPLETE, index_tree_complete);
	RH_SET_FACT(RH_FACT_CHILD_VCNS_VALID, child_vcns_valid);
	RH_SET_FACT(RH_FACT_INDX_BLOCKS_VALID, indx_blocks_valid);
	RH_SET_FACT(RH_FACT_REACHABLE_SET_EXACT, reachable_set_exact);
	RH_SET_FACT(RH_FACT_NO_UNRESOLVED_BLOCKS, no_unresolved_blocks);
	RH_SET_FACT(RH_FACT_DATA_PRESERVING, data_preserving);
	RH_SET_FACT(RH_FACT_FINAL_OVERLAY_VALID, final_overlay_valid);
#undef RH_SET_FACT
}

static int rh_target_basic_valid(const struct rh_policy_target_identity *target)
{
	unsigned char empty_hash[32];
	unsigned char name_bytes[RH_POLICY_ATTRIBUTE_NAME_PREFIX_MAX * 2U];
	unsigned char prefix_hash[32];
	size_t i;

	rh_sha256("", 0, empty_hash);
	if (!target || target->object <= RH_POLICY_TARGET_NONE ||
			target->object > RH_POLICY_TARGET_INDEX_BITMAP ||
			target->action_kind < 0 ||
			target->action_kind >= RH_WRITE_KIND_COUNT ||
			target->write_object <= RH_WRITE_TARGET_INVALID ||
			target->write_object > RH_WRITE_TARGET_PROVEN_FREE_ALLOCATION ||
			(target->semantic_flags &
			 (uint16_t)~RH_WRITE_TARGET_FLAGS_MASK) ||
			target->attribute_name_length > 255U ||
			target->attribute_name_prefix_length >
				RH_POLICY_ATTRIBUTE_NAME_PREFIX_MAX ||
			target->attribute_name_prefix_length >
				target->attribute_name_length ||
			(!target->attribute_name_length &&
			 (target->attribute_name_prefix_length ||
			  memcmp(target->attribute_name_hash, empty_hash,
				sizeof(empty_hash)))) ||
			(target->attribute_name_length &&
			 rh_all_zero(target->attribute_name_hash,
				sizeof(target->attribute_name_hash))) ||
			!target->mft_sequence || !target->logical_length ||
			!target->physical_length || !target->semantic_length ||
			!target->operation_ordinal || !target->writer_checkpoint ||
			target->operation_ordinal > target->writer_checkpoint ||
			rh_all_zero(target->staged_plan_hash,
				sizeof(target->staged_plan_hash)) ||
			rh_all_zero(target->before_hash, sizeof(target->before_hash)) ||
			rh_all_zero(target->after_hash, sizeof(target->after_hash)) ||
			!memcmp(target->before_hash, target->after_hash,
				sizeof(target->before_hash)) ||
			target->logical_offset > UINT64_MAX - target->logical_length ||
			target->physical_offset > UINT64_MAX - target->physical_length ||
			target->semantic_offset > UINT64_MAX - target->semantic_length ||
			target->changes_set_bits > 1 || target->changes_clear_bits > 1 ||
			(!target->changes_set_bits && !target->changes_clear_bits))
		return 0;
	if (target->attribute_name_length <=
			RH_POLICY_ATTRIBUTE_NAME_PREFIX_MAX) {
		if (target->attribute_name_prefix_length !=
				target->attribute_name_length)
			return 0;
		for (i = 0; i < target->attribute_name_length; i++) {
			name_bytes[2U * i] =
				(unsigned char)target->attribute_name_prefix[i];
			name_bytes[2U * i + 1U] =
				(unsigned char)(target->attribute_name_prefix[i] >> 8);
		}
		rh_sha256(name_bytes, target->attribute_name_length * 2U,
			prefix_hash);
		if (memcmp(prefix_hash, target->attribute_name_hash,
				sizeof(prefix_hash)))
			return 0;
	}
	return 1;
}

static void rh_target_normalize(struct rh_policy_target_identity *output,
		const struct rh_policy_target_identity *input,
		const struct rh_bitmap_census_result *result)
{
	memset(output, 0, sizeof(*output));
	output->object = input->object;
	output->action_kind = input->action_kind;
	output->write_object = input->write_object;
	output->semantic_flags = input->semantic_flags;
	output->mft_record = input->mft_record;
	output->mft_sequence = input->mft_sequence;
	output->attribute_instance = input->attribute_instance;
	output->attribute_type = input->attribute_type;
	output->attribute_name_length = input->attribute_name_length;
	output->attribute_name_prefix_length =
		input->attribute_name_prefix_length;
	memcpy(output->attribute_name_prefix, input->attribute_name_prefix,
		input->attribute_name_prefix_length *
			sizeof(*input->attribute_name_prefix));
	memcpy(output->attribute_name_hash, input->attribute_name_hash,
		sizeof(output->attribute_name_hash));
	output->lowest_vcn = input->lowest_vcn;
	output->logical_vcn = input->logical_vcn;
	output->lcn = input->lcn;
	output->logical_offset = input->logical_offset;
	output->logical_length = input->logical_length;
	output->physical_offset = input->physical_offset;
	output->physical_length = input->physical_length;
	output->semantic_offset = input->semantic_offset;
	output->semantic_length = input->semantic_length;
	output->operation_ordinal = input->operation_ordinal;
	output->writer_checkpoint = input->writer_checkpoint;
	memcpy(output->staged_plan_hash, input->staged_plan_hash,
		sizeof(output->staged_plan_hash));
	memcpy(output->before_hash, input->before_hash,
		sizeof(output->before_hash));
	memcpy(output->after_hash, input->after_hash,
		sizeof(output->after_hash));
	output->census_generation = result->generation;
	memcpy(output->census_hash, result->census_hash,
		sizeof(output->census_hash));
	output->changes_set_bits = input->changes_set_bits;
	output->changes_clear_bits = input->changes_clear_bits;
}

static unsigned char *rh_evidence_put_u8(unsigned char *output,
		uint8_t value)
{
	*output = value;
	return output + 1U;
}

static unsigned char *rh_evidence_put_u16(unsigned char *output,
		uint16_t value)
{
	output[0] = (unsigned char)value;
	output[1] = (unsigned char)(value >> 8);
	return output + 2U;
}

static unsigned char *rh_evidence_put_u32(unsigned char *output,
		uint32_t value)
{
	size_t i;

	for (i = 0; i < 4U; i++)
		output[i] = (unsigned char)(value >> (8U * i));
	return output + 4U;
}

static unsigned char *rh_evidence_put_u64(unsigned char *output,
		uint64_t value)
{
	size_t i;

	for (i = 0; i < 8U; i++)
		output[i] = (unsigned char)(value >> (8U * i));
	return output + 8U;
}

static unsigned char *rh_evidence_put_bytes(unsigned char *output,
		const void *bytes, size_t length)
{
	memcpy(output, bytes, length);
	return output + length;
}

/*
 * The target representation is a wire format, not a C object image.  Keep its
 * field order explicit so padding, enum width, size_t width and host byte order
 * can never alter a persisted/recovered evidence seal.
 */
static unsigned char *rh_evidence_put_target(unsigned char *output,
		const struct rh_policy_target_identity *target)
{
	size_t i;

	output = rh_evidence_put_u32(output, (uint32_t)target->object);
	output = rh_evidence_put_u32(output, (uint32_t)target->action_kind);
	output = rh_evidence_put_u32(output, (uint32_t)target->write_object);
	output = rh_evidence_put_u16(output, target->semantic_flags);
	output = rh_evidence_put_u64(output, target->mft_record);
	output = rh_evidence_put_u16(output, target->mft_sequence);
	output = rh_evidence_put_u16(output, target->attribute_instance);
	output = rh_evidence_put_u32(output, target->attribute_type);
	output = rh_evidence_put_u16(output, target->attribute_name_length);
	output = rh_evidence_put_u8(output,
		target->attribute_name_prefix_length);
	for (i = 0; i < RH_POLICY_ATTRIBUTE_NAME_PREFIX_MAX; i++)
		output = rh_evidence_put_u16(output,
			target->attribute_name_prefix[i]);
	output = rh_evidence_put_bytes(output, target->attribute_name_hash,
		sizeof(target->attribute_name_hash));
	output = rh_evidence_put_u64(output, target->lowest_vcn);
	output = rh_evidence_put_u64(output, target->logical_vcn);
	output = rh_evidence_put_u64(output, target->lcn);
	output = rh_evidence_put_u64(output, target->logical_offset);
	output = rh_evidence_put_u64(output, target->logical_length);
	output = rh_evidence_put_u64(output, target->physical_offset);
	output = rh_evidence_put_u64(output, target->physical_length);
	output = rh_evidence_put_u64(output, target->semantic_offset);
	output = rh_evidence_put_u64(output, target->semantic_length);
	output = rh_evidence_put_u64(output, target->operation_ordinal);
	output = rh_evidence_put_u64(output, target->writer_checkpoint);
	output = rh_evidence_put_bytes(output, target->staged_plan_hash,
		sizeof(target->staged_plan_hash));
	output = rh_evidence_put_bytes(output, target->before_hash,
		sizeof(target->before_hash));
	output = rh_evidence_put_bytes(output, target->after_hash,
		sizeof(target->after_hash));
	output = rh_evidence_put_u64(output, target->census_generation);
	output = rh_evidence_put_bytes(output, target->census_hash,
		sizeof(target->census_hash));
	output = rh_evidence_put_u8(output, target->changes_set_bits);
	return rh_evidence_put_u8(output, target->changes_clear_bits);
}

static int rh_evidence_compute_seal(const struct rh_policy_evidence *evidence,
		unsigned char output[32])
{
	unsigned char *serialized, *cursor;
	size_t total, i;

	if (!evidence || !output ||
			(evidence->target_count && !evidence->targets)) {
		errno = EINVAL;
		return -1;
	}
	if (evidence->target_count >
			(SIZE_MAX - RH_EVIDENCE_SEAL_HEADER_SIZE) /
				RH_EVIDENCE_SEAL_TARGET_SIZE) {
		errno = EOVERFLOW;
		return -1;
	}
	total = RH_EVIDENCE_SEAL_HEADER_SIZE + evidence->target_count *
		RH_EVIDENCE_SEAL_TARGET_SIZE;
	serialized = malloc(total);
	if (!serialized)
		return -1;
	cursor = serialized;
	cursor = rh_evidence_put_u64(cursor, evidence->magic);
	cursor = rh_evidence_put_u32(cursor, evidence->version);
	cursor = rh_evidence_put_u32(cursor, (uint32_t)evidence->object);
	cursor = rh_evidence_put_u64(cursor, evidence->generation);
	cursor = rh_evidence_put_u64(cursor, (uint64_t)evidence->target_count);
	cursor = rh_evidence_put_bytes(cursor, evidence->census_hash,
		sizeof(evidence->census_hash));
	cursor = rh_evidence_put_u64(cursor,
		evidence->final_overlay_generation);
	cursor = rh_evidence_put_bytes(cursor, evidence->final_overlay_hash,
		sizeof(evidence->final_overlay_hash));
	for (i = 0; i < RH_POLICY_FACT_COUNT; i++)
		cursor = rh_evidence_put_u32(cursor,
			(uint32_t)(int32_t)evidence->facts[i]);
	for (i = 0; i < evidence->target_count; i++)
		cursor = rh_evidence_put_target(cursor, &evidence->targets[i]);
	if ((size_t)(cursor - serialized) != total) {
		free(serialized);
		errno = EIO;
		return -1;
	}
	rh_sha256(serialized, total, output);
	free(serialized);
	return 0;
}

static int rh_evidence_valid(const struct rh_policy_evidence *evidence)
{
	unsigned char seal[32];
	size_t i;

	if (!evidence || evidence->magic != RH_EVIDENCE_MAGIC ||
			evidence->version != RH_EVIDENCE_VERSION ||
			evidence->object <= RH_POLICY_TARGET_NONE ||
			evidence->object > RH_POLICY_TARGET_INDEX_BITMAP ||
			!evidence->generation || !evidence->target_count ||
			!evidence->targets ||
			rh_all_zero(evidence->census_hash,
				sizeof(evidence->census_hash)) ||
			(evidence->facts[RH_FACT_FINAL_OVERLAY_VALID] ==
				RH_EVIDENCE_TRUE && (!evidence->final_overlay_generation ||
				rh_all_zero(evidence->final_overlay_hash,
					sizeof(evidence->final_overlay_hash)))))
		return 0;
	for (i = 0; i < evidence->target_count; i++)
		if (!rh_target_basic_valid(&evidence->targets[i]) ||
				evidence->targets[i].object != evidence->object ||
				evidence->targets[i].census_generation !=
					evidence->generation ||
				memcmp(evidence->targets[i].census_hash,
					evidence->census_hash, 32))
			return 0;
	if (rh_evidence_compute_seal(evidence, seal))
		return 0;
	return !memcmp(seal, evidence->seal, sizeof(seal));
}

#ifdef ROOTHEALTH_REPAIR_TESTING
int rh_policy_evidence_test_copy_seal(
		const struct rh_policy_evidence *evidence,
		unsigned char output[32])
{
	if (!output || !rh_evidence_valid(evidence)) {
		errno = EINVAL;
		return -1;
	}
	memcpy(output, evidence->seal, 32U);
	return 0;
}
#endif

int rh_policy_seal_bitmap_census(
		const struct rh_bitmap_census_result *result,
		const struct rh_policy_target_identity *targets,
		size_t target_count, struct rh_policy_evidence **output)
{
	struct rh_policy_evidence *evidence;
	size_t i;

	if (output)
		*output = NULL;
	if (!result || !targets || !target_count || !output ||
			result->object <= RH_POLICY_TARGET_NONE ||
			result->object > RH_POLICY_TARGET_INDEX_BITMAP ||
			!result->generation ||
			rh_all_zero(result->census_hash,
				sizeof(result->census_hash)) ||
			target_count > SIZE_MAX / sizeof(*targets)) {
		errno = EINVAL;
		return -1;
	}
	evidence = calloc(1, sizeof(*evidence));
	if (!evidence)
		return -1;
	evidence->targets = calloc(target_count, sizeof(*evidence->targets));
	if (!evidence->targets)
		goto error;
	evidence->magic = RH_EVIDENCE_MAGIC;
	evidence->version = RH_EVIDENCE_VERSION;
	evidence->object = result->object;
	evidence->generation = result->generation;
	evidence->final_overlay_generation = result->final_overlay_generation;
	evidence->target_count = target_count;
	memcpy(evidence->census_hash, result->census_hash,
		sizeof(evidence->census_hash));
	memcpy(evidence->final_overlay_hash, result->final_overlay_hash,
		sizeof(evidence->final_overlay_hash));
	rh_evidence_fill_facts(evidence, result);
	for (i = 0; i < target_count; i++) {
		if (!rh_target_basic_valid(&targets[i]) ||
				targets[i].object != result->object) {
			errno = EINVAL;
			goto error;
		}
		rh_target_normalize(&evidence->targets[i], &targets[i], result);
	}
	if (rh_evidence_compute_seal(evidence, evidence->seal))
		goto error;
	*output = evidence;
	return 0;
error:
	rh_policy_evidence_destroy(evidence);
	return -1;
}

size_t rh_policy_definition_count(void)
{
	return sizeof(rh_problem_definitions) / sizeof(rh_problem_definitions[0]) +
		sizeof(rh_aggregate_definitions) /
			sizeof(rh_aggregate_definitions[0]);
}

const struct rh_policy_definition *rh_policy_definition_at(size_t index)
{
	if (index < sizeof(rh_problem_definitions) /
			sizeof(rh_problem_definitions[0]))
		return &rh_problem_definitions[index];
	index -= sizeof(rh_problem_definitions) /
		sizeof(rh_problem_definitions[0]);
	if (index < sizeof(rh_aggregate_definitions) /
			sizeof(rh_aggregate_definitions[0]))
		return &rh_aggregate_definitions[index];
	return NULL;
}

const struct rh_policy_definition *rh_policy_problem(problem_code_t code)
{
	if (code < PR_PRE_SCAN_MFT || code > PR_NAMESPACE_LINK_COUNT_MISMATCH)
		return NULL;
	return &rh_problem_definitions[(size_t)(code - PR_PRE_SCAN_MFT)];
}

const struct rh_policy_definition *rh_policy_aggregate(const char *name)
{
	size_t i;

	if (!name)
		return NULL;
	for (i = 0; i < sizeof(rh_aggregate_definitions) /
			sizeof(rh_aggregate_definitions[0]); i++)
		if (!strcmp(rh_aggregate_definitions[i].name, name))
			return &rh_aggregate_definitions[i];
	return NULL;
}

const struct rh_policy_implementation *rh_policy_implementation(
		const struct rh_policy_definition *definition)
{
	const struct rh_policy_implementation *implementation;

	if (!definition || definition->configured != RH_POLICY_CONFIG_CONDITIONAL)
		return NULL;
	if (definition->scope == RH_POLICY_SCOPE_PROBLEM) {
		if (definition->problem_code < PR_PRE_SCAN_MFT ||
				definition->problem_code >
					PR_NAMESPACE_LINK_COUNT_MISMATCH)
			return NULL;
		implementation = &rh_problem_implementations[
			(size_t)definition->problem_code];
	} else if (definition->scope == RH_POLICY_SCOPE_AGGREGATE &&
			definition->aggregate_id >= 0 &&
			definition->aggregate_id < RH_POLICY_AGGREGATE_COUNT) {
		implementation = &rh_aggregate_implementations[
			(size_t)definition->aggregate_id];
	} else {
		return NULL;
	}
	if (implementation->profile == RH_POLICY_PROFILE_NONE)
		return NULL;
	return implementation;
}

const char *rh_policy_fact_name(enum rh_policy_fact fact)
{
	if (fact < 0 || fact >= RH_POLICY_FACT_COUNT)
		return "invalid";
	return rh_fact_names[fact];
}

size_t rh_policy_evidence_target_count(const struct rh_policy_evidence *evidence)
{
	if (!rh_evidence_valid(evidence))
		return 0;
	return evidence->target_count;
}

const struct rh_policy_target_identity *rh_policy_evidence_target(
		const struct rh_policy_evidence *evidence, size_t target_ordinal)
{
	if (!rh_evidence_valid(evidence) ||
			target_ordinal >= evidence->target_count)
		return NULL;
	return &evidence->targets[target_ordinal];
}

static int rh_name_is_i30(const struct rh_policy_target_identity *target)
{
	static const unsigned char i30[] = {
		'$', 0, 'I', 0, '3', 0, '0', 0
	};
	unsigned char hash[32];

	rh_sha256(i30, sizeof(i30), hash);
	return target->attribute_name_length == sizeof(i30) / 2U &&
		!memcmp(target->attribute_name_hash, hash, sizeof(hash));
}

static int rh_profile_target_valid(enum rh_policy_profile profile,
		const struct rh_policy_target_identity *target)
{
	switch (profile) {
	case RH_POLICY_PROFILE_CLUSTER_BITMAP:
		return target->object == RH_POLICY_TARGET_VOLUME_BITMAP &&
			target->action_kind == RH_WRITE_BITMAP_CLUSTER &&
			target->write_object ==
				RH_WRITE_TARGET_NONRESIDENT_ATTRIBUTE &&
			target->mft_record == 6 && target->attribute_type == 0x80 &&
			!target->attribute_name_length;
	case RH_POLICY_PROFILE_MFT_BITMAP:
		return target->object == RH_POLICY_TARGET_MFT_BITMAP &&
			target->action_kind == RH_WRITE_BITMAP_MFT &&
			target->write_object ==
				RH_WRITE_TARGET_NONRESIDENT_ATTRIBUTE &&
			!target->mft_record && target->attribute_type == 0xb0 &&
			!target->attribute_name_length;
	case RH_POLICY_PROFILE_INDEX_BITMAP:
		return target->object == RH_POLICY_TARGET_INDEX_BITMAP &&
			target->action_kind == RH_WRITE_INDEX_BITMAP &&
			(target->write_object == RH_WRITE_TARGET_MFT_RECORD_PRIMARY ||
			 target->write_object ==
				RH_WRITE_TARGET_NONRESIDENT_ATTRIBUTE) &&
			target->attribute_type == 0xb0 && rh_name_is_i30(target);
	default:
		return 0;
	}
}

static int rh_operation_target_matches(
		const struct rh_policy_target_identity *target,
		const struct rh_write_operation *operation)
{
	const struct rh_write_semantic_target *semantic = &operation->target;
	enum rh_write_target_object expected_object = target->write_object;
	uint16_t expected_flags = target->semantic_flags;

	if (!!target->changes_set_bits == !!target->changes_clear_bits)
		return 0;
	if (!!(expected_flags & RH_WRITE_TARGET_SET_ONLY) !=
			!!target->changes_set_bits ||
			!!(expected_flags & RH_WRITE_TARGET_CLEAR_ONLY) !=
			!!target->changes_clear_bits)
		return 0;
	if (expected_object == RH_WRITE_TARGET_MFT_RECORD_PRIMARY ||
			expected_object == RH_WRITE_TARGET_MFT_RECORD_MIRROR) {
		if (semantic->lowest_vcn != -1 || semantic->logical_vcn != -1 ||
				semantic->lcn != -1 || target->lowest_vcn != UINT64_MAX ||
				target->logical_vcn != UINT64_MAX || target->lcn != UINT64_MAX)
			return 0;
	} else if (semantic->lowest_vcn < 0 || semantic->logical_vcn < 0 ||
			semantic->lcn < 0 ||
			(uint64_t)semantic->lowest_vcn != target->lowest_vcn ||
			(uint64_t)semantic->logical_vcn != target->logical_vcn ||
			(uint64_t)semantic->lcn != target->lcn)
		return 0;
	return semantic->seal_version == 1 && !semantic->finalized &&
		semantic->object == expected_object &&
		semantic->owner_mft_record == target->mft_record &&
		semantic->owner_sequence == target->mft_sequence &&
		semantic->attribute_instance == target->attribute_instance &&
		semantic->attribute_type == target->attribute_type &&
		semantic->attribute_name_length == target->attribute_name_length &&
		semantic->flags == expected_flags &&
		!memcmp(semantic->attribute_name_hash,
			target->attribute_name_hash, 32) &&
		semantic->logical_offset == target->logical_offset &&
		semantic->logical_length == target->logical_length &&
		semantic->semantic_target_offset == target->semantic_offset &&
		semantic->semantic_target_length == target->semantic_length &&
		rh_write_semantic_target_valid(operation->kind, semantic,
			operation->offset, operation->length, 0);
}

enum rh_policy_final_decision rh_policy_authorize_operation(
		const struct rh_policy_definition *definition,
		const struct rh_policy_evidence *evidence, size_t target_ordinal,
		const struct rh_writer *writer, size_t operation_ordinal,
		struct rh_policy_authorization *record)
{
	const struct rh_policy_implementation *implementation;
	const struct rh_policy_target_identity *target;
	const struct rh_write_operation *operation;
	unsigned char plan_hash[32], before_hash[32], after_hash[32];
	size_t i;
	enum rh_policy_final_decision decision = RH_POLICY_FINAL_DENIED;

	if (record)
		memset(record, 0, sizeof(*record));
	implementation = rh_policy_implementation(definition);
	if (!implementation || !rh_evidence_valid(evidence) || !writer ||
			target_ordinal >= evidence->target_count || !operation_ordinal ||
			operation_ordinal > writer->operation_count)
		return decision;
	target = &evidence->targets[target_ordinal];
	operation = &writer->operations[operation_ordinal - 1];
	if (record) {
		record->definition = definition;
		record->implementation = implementation;
		record->target_ordinal = target_ordinal;
		record->target = *target;
		record->evidence_generation = evidence->generation;
		memcpy(record->evidence_hash, evidence->census_hash,
			sizeof(record->evidence_hash));
		record->final_overlay_generation =
			evidence->final_overlay_generation;
		memcpy(record->final_overlay_hash, evidence->final_overlay_hash,
			sizeof(record->final_overlay_hash));
		record->writer_checkpoint = target->writer_checkpoint;
		memcpy(record->staged_plan_hash, target->staged_plan_hash,
			sizeof(record->staged_plan_hash));
		record->required_fact_mask = implementation->required_fact_mask;
		memcpy(record->facts, evidence->facts, sizeof(record->facts));
	}
	if (!(implementation->allowed_action_mask &
			RH_ACTION_MASK(target->action_kind)) ||
			!rh_profile_target_valid(implementation->profile, target) ||
			target->operation_ordinal != operation_ordinal ||
			target->writer_checkpoint != writer->operation_count ||
			operation->kind != target->action_kind ||
			operation->offset != target->physical_offset ||
			operation->length != target->physical_length ||
			!rh_operation_target_matches(target, operation) ||
			rh_writer_plan_hash(writer, writer->operation_count, plan_hash) ||
			memcmp(plan_hash, target->staged_plan_hash,
				sizeof(plan_hash)))
		goto out;
	rh_sha256(operation->before, operation->length, before_hash);
	rh_sha256(operation->after, operation->length, after_hash);
	if (memcmp(before_hash, target->before_hash, sizeof(before_hash)) ||
			memcmp(after_hash, target->after_hash, sizeof(after_hash)))
		goto out;
	for (i = 0; i < RH_POLICY_FACT_COUNT; i++)
		if ((implementation->required_fact_mask & RH_FACT_MASK(i)) &&
				evidence->facts[i] != RH_EVIDENCE_TRUE)
			goto out;
	decision = RH_POLICY_FINAL_AUTHORIZED;
out:
	if (record)
		record->decision = decision;
	return decision;
}

void rh_policy_evidence_destroy(struct rh_policy_evidence *evidence)
{
	if (!evidence)
		return;
	free(evidence->targets);
	memset(evidence, 0, sizeof(*evidence));
	free(evidence);
}
