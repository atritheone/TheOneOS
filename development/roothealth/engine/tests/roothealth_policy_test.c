#include "config.h"

#include <stdio.h>
#include <string.h>

#include "roothealth_policy_internal.h"

static void complete_result(struct rh_bitmap_census_result *result,
		enum rh_policy_target_object object, uint64_t generation)
{
	memset(result, 0, sizeof(*result));
	result->object = object;
	result->generation = generation;
	memset(result->census_hash, (int)(generation & 0xff),
		sizeof(result->census_hash));
	result->final_overlay_generation = generation + 1;
	memset(result->final_overlay_hash, (int)((generation + 1) & 0xff),
		sizeof(result->final_overlay_hash));
	result->completed = 1;
	result->identity_bound = 1;
	result->complete_mft_census = 1;
	result->complete_attribute_census = 1;
	result->complete_runlist_census = 1;
	result->complete_namespace_census = 1;
	result->complete_index_census = 1;
	result->complete_cluster_census = 1;
	result->no_io_uncertainty = 1;
	result->no_duplicate_clusters = 1;
	result->targets_outside_wal = 1;
	result->ownership_exact = 1;
	result->sets_proven_live = 1;
	result->clears_proven_unreferenced = 1;
	result->index_tree_complete = 1;
	result->child_vcns_valid = 1;
	result->indx_blocks_valid = 1;
	result->reachable_set_exact = 1;
	result->no_unresolved_blocks = 1;
	result->data_preserving = 1;
	result->final_overlay_valid = 1;
}

static void target_for_profile(struct rh_policy_target_identity *target,
		enum rh_policy_profile profile)
{
	memset(target, 0, sizeof(*target));
	rh_sha256("", 0, target->attribute_name_hash);
	target->mft_sequence = 1;
	target->attribute_instance = 4;
	target->lowest_vcn = 0;
	target->logical_vcn = 2;
	target->lcn = 100;
	target->logical_offset = 8192;
	target->logical_length = 4096;
	target->physical_offset = 409600;
	target->physical_length = 4096;
	target->semantic_offset = target->physical_offset;
	target->semantic_length = target->physical_length;
	target->changes_set_bits = 1;
	target->changes_clear_bits = 1;
	switch (profile) {
	case RH_POLICY_PROFILE_CLUSTER_BITMAP:
		target->object = RH_POLICY_TARGET_VOLUME_BITMAP;
		target->action_kind = RH_WRITE_BITMAP_CLUSTER;
		target->mft_record = 6;
		target->attribute_type = 0x80;
		break;
	case RH_POLICY_PROFILE_MFT_BITMAP:
		target->object = RH_POLICY_TARGET_MFT_BITMAP;
		target->action_kind = RH_WRITE_BITMAP_MFT;
		target->mft_record = 0;
		target->attribute_type = 0xb0;
		break;
	case RH_POLICY_PROFILE_INDEX_BITMAP:
		target->object = RH_POLICY_TARGET_INDEX_BITMAP;
		target->action_kind = RH_WRITE_INDEX_BITMAP;
		target->mft_record = 5;
		target->attribute_type = 0xb0;
		target->attribute_name_length = 4;
		target->attribute_name_prefix_length = 4;
		target->attribute_name_prefix[0] = '$';
		target->attribute_name_prefix[1] = 'I';
		target->attribute_name_prefix[2] = '3';
		target->attribute_name_prefix[3] = '0';
		{
			static const unsigned char i30[] = {
				'$', 0, 'I', 0, '3', 0, '0', 0
			};
			rh_sha256(i30, sizeof(i30), target->attribute_name_hash);
		}
		break;
	default:
		break;
	}
}

static void clear_fact(struct rh_bitmap_census_result *result,
		enum rh_policy_fact fact)
{
	switch (fact) {
	case RH_FACT_IDENTITY_BOUND: result->identity_bound = 0; break;
	case RH_FACT_COMPLETE_MFT_CENSUS: result->complete_mft_census = 0; break;
	case RH_FACT_COMPLETE_ATTRIBUTE_CENSUS:
		result->complete_attribute_census = 0; break;
	case RH_FACT_COMPLETE_RUNLIST_CENSUS:
		result->complete_runlist_census = 0; break;
	case RH_FACT_COMPLETE_NAMESPACE_CENSUS:
		result->complete_namespace_census = 0; break;
	case RH_FACT_COMPLETE_INDEX_CENSUS:
		result->complete_index_census = 0; break;
	case RH_FACT_COMPLETE_CLUSTER_CENSUS:
		result->complete_cluster_census = 0; break;
	case RH_FACT_NO_IO_UNCERTAINTY: result->no_io_uncertainty = 0; break;
	case RH_FACT_NO_DUPLICATE_CLUSTERS:
		result->no_duplicate_clusters = 0; break;
	case RH_FACT_TARGETS_OUTSIDE_WAL: result->targets_outside_wal = 0; break;
	case RH_FACT_OWNERSHIP_EXACT: result->ownership_exact = 0; break;
	case RH_FACT_SETS_PROVEN_LIVE: result->sets_proven_live = 0; break;
	case RH_FACT_CLEARS_PROVEN_UNREFERENCED:
		result->clears_proven_unreferenced = 0; break;
	case RH_FACT_INDEX_TREE_COMPLETE: result->index_tree_complete = 0; break;
	case RH_FACT_CHILD_VCNS_VALID: result->child_vcns_valid = 0; break;
	case RH_FACT_INDX_BLOCKS_VALID: result->indx_blocks_valid = 0; break;
	case RH_FACT_REACHABLE_SET_EXACT: result->reachable_set_exact = 0; break;
	case RH_FACT_NO_UNRESOLVED_BLOCKS:
		result->no_unresolved_blocks = 0; break;
	case RH_FACT_DATA_PRESERVING: result->data_preserving = 0; break;
	case RH_FACT_FINAL_OVERLAY_VALID: result->final_overlay_valid = 0; break;
	default: break;
	}
}

static int authorize_with_result(const struct rh_policy_definition *definition,
		const struct rh_bitmap_census_result *result,
		struct rh_policy_target_identity *target,
		struct rh_policy_authorization *authorization)
{
	struct rh_policy_evidence *evidence = NULL;
	struct rh_write_operation operation;
	struct rh_writer writer;
	unsigned char before[4096], after[4096];
	int decision;

	memset(before, 0x5a, sizeof(before));
	memset(after, 0xa5, sizeof(after));
	memset(&operation, 0, sizeof(operation));
	operation.kind = target->action_kind;
	operation.offset = target->physical_offset;
	operation.length = target->physical_length;
	operation.before = before;
	operation.after = after;
	memset(&writer, 0, sizeof(writer));
	writer.operations = &operation;
	writer.operation_count = 1;
	target->operation_ordinal = 1;
	target->writer_checkpoint = 1;
	rh_sha256(before, operation.length, target->before_hash);
	rh_sha256(after, operation.length, target->after_hash);
	if (rh_writer_plan_hash(&writer, 1, target->staged_plan_hash))
		return -1;
	if (rh_policy_seal_bitmap_census(result, target, 1, &evidence))
		return -1;
	decision = rh_policy_authorize_operation(definition, evidence, 0,
		&writer, 1, authorization);
	rh_policy_evidence_destroy(evidence);
	return decision;
}

static int exact_implemented_problem(problem_code_t code)
{
	return code == PR_CLUSTER_BITMAP_MISMATCH ||
		code == PR_MFT_BITMAP_MISMATCH ||
		code == PR_IDX_BITMAP_MISMATCH;
}

static int exact_implemented_aggregate(enum rh_policy_aggregate_id id)
{
	return id == RH_POLICY_AGGREGATE_CLUSTER_BITMAP ||
		id == RH_POLICY_AGGREGATE_MFT_BITMAP ||
		id == RH_POLICY_AGGREGATE_INDEX_BITMAP;
}

static int exact_operation_binding_test(void)
{
	const struct rh_policy_definition *definition =
		rh_policy_problem(PR_CLUSTER_BITMAP_MISMATCH);
	struct rh_bitmap_census_result result;
	struct rh_policy_target_identity target;
	struct rh_policy_evidence *evidence = NULL;
	struct rh_policy_authorization authorization;
	struct rh_write_operation operation;
	struct rh_writer writer;
	unsigned char before[4096], after[4096];
	int ok = 0;

	target_for_profile(&target, RH_POLICY_PROFILE_CLUSTER_BITMAP);
	complete_result(&result, target.object, 900);
	memset(before, 0x33, sizeof(before));
	memset(after, 0xcc, sizeof(after));
	memset(&operation, 0, sizeof(operation));
	operation.kind = target.action_kind;
	operation.offset = target.physical_offset;
	operation.length = target.physical_length;
	operation.before = before;
	operation.after = after;
	memset(&writer, 0, sizeof(writer));
	writer.operations = &operation;
	writer.operation_count = 1;
	target.operation_ordinal = 1;
	target.writer_checkpoint = 1;
	rh_sha256(before, sizeof(before), target.before_hash);
	rh_sha256(after, sizeof(after), target.after_hash);
	if (rh_writer_plan_hash(&writer, 1, target.staged_plan_hash) ||
			rh_policy_seal_bitmap_census(&result, &target, 1, &evidence) ||
			rh_policy_authorize_operation(definition, evidence, 0, &writer, 1,
				&authorization) != RH_POLICY_FINAL_AUTHORIZED)
		goto out;
	after[0] ^= 1;
	if (rh_policy_authorize_operation(definition, evidence, 0, &writer, 1,
			&authorization) != RH_POLICY_FINAL_DENIED)
		goto out;
	after[0] ^= 1;
	operation.offset++;
	if (rh_policy_authorize_operation(definition, evidence, 0, &writer, 1,
			&authorization) != RH_POLICY_FINAL_DENIED)
		goto out;
	operation.offset--;
	writer.operation_count = 0;
	if (rh_policy_authorize_operation(definition, evidence, 0, &writer, 1,
			&authorization) != RH_POLICY_FINAL_DENIED)
		goto out;
	ok = 1;
out:
	rh_policy_evidence_destroy(evidence);
	return ok ? 0 : -1;
}

int main(void)
{
	size_t i, fact;
	size_t problems = 0, aggregates = 0, implemented = 0;

	if (rh_policy_definition_count() != 112)
		return 1;
	for (i = 0; i < rh_policy_definition_count(); i++) {
		const struct rh_policy_definition *definition =
			rh_policy_definition_at(i);
		const struct rh_policy_implementation *implementation;
		struct rh_bitmap_census_result result;
		struct rh_policy_target_identity target;
		struct rh_policy_authorization authorization;
		int expected;

		if (!definition)
			return 1;
		implementation = rh_policy_implementation(definition);
		if (definition->scope == RH_POLICY_SCOPE_PROBLEM) {
			problems++;
			expected = exact_implemented_problem(
				(problem_code_t)definition->problem_code);
		} else if (definition->scope == RH_POLICY_SCOPE_AGGREGATE) {
			aggregates++;
			expected = exact_implemented_aggregate(definition->aggregate_id);
		} else {
			return 1;
		}
		if (!!implementation != expected)
			return 1;
		if (!implementation)
			continue;
		implemented++;
		if (!implementation->evidence_id || !implementation->source_pass)
			return 1;
		target_for_profile(&target, implementation->profile);
		complete_result(&result, target.object, i + 1);
		if (authorize_with_result(definition, &result, &target,
				&authorization) != RH_POLICY_FINAL_AUTHORIZED ||
				authorization.target.mft_record != target.mft_record ||
				authorization.evidence_generation != result.generation)
			return 1;
		for (fact = 0; fact < RH_POLICY_FACT_COUNT; fact++) {
			if (!(implementation->required_fact_mask &
					(UINT64_C(1) << fact)))
				continue;
			complete_result(&result, target.object, i + fact + 100);
			clear_fact(&result, (enum rh_policy_fact)fact);
			if (authorize_with_result(definition, &result, &target,
					&authorization) != RH_POLICY_FINAL_DENIED ||
					authorization.facts[fact] != RH_EVIDENCE_FALSE)
				return 1;
		}
		complete_result(&result, target.object, i + 500);
		result.completed = 0;
		if (authorize_with_result(definition, &result, &target,
				&authorization) != RH_POLICY_FINAL_DENIED)
			return 1;
	}
	if (problems != 98 || aggregates != 14 || implemented != 6 ||
		rh_policy_implementation(rh_policy_problem(
			PR_IDX_BITMAP_SIZE_MISMATCH)) ||
		rh_policy_implementation(rh_policy_problem(
			PR_BITMAP_MFT_SIZE_MISMATCH)) ||
		rh_policy_implementation(rh_policy_problem(
			PR_MFT_BITMAP_SIZE_MISMATCH)) || exact_operation_binding_test())
		return 1;
	printf("policy problems=%zu aggregates=%zu implemented=%zu "
		"exact_set=1 sealed_evidence=1 typed_targets=1 exact_bytes=1 "
		"staged_plan_bound=1 final_overlay_required=1\n",
		problems, aggregates, implemented);
	return 0;
}
