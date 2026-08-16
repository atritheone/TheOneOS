#include "config.h"

#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "roothealth_policy_internal.h"

static void fill_result(struct rh_bitmap_census_result *result)
{
	size_t i;

	memset(result, 0, sizeof(*result));
	result->object = RH_POLICY_TARGET_INDEX_BITMAP;
	result->generation = UINT64_C(0x0102030405060708);
	for (i = 0; i < sizeof(result->census_hash); i++)
		result->census_hash[i] = (unsigned char)(0xa0U + i);
	result->final_overlay_generation = UINT64_C(0x1112131415161718);
	for (i = 0; i < sizeof(result->final_overlay_hash); i++)
		result->final_overlay_hash[i] = (unsigned char)(0xc0U + i);
	result->completed = 1;
	result->identity_bound = 1;
	result->complete_mft_census = 0;
	result->complete_attribute_census = 1;
	result->complete_runlist_census = 0;
	result->complete_namespace_census = 1;
	result->complete_index_census = 0;
	result->complete_cluster_census = 1;
	result->no_io_uncertainty = 0;
	result->no_duplicate_clusters = 1;
	result->targets_outside_wal = 0;
	result->ownership_exact = 1;
	result->sets_proven_live = 0;
	result->clears_proven_unreferenced = 1;
	result->index_tree_complete = 0;
	result->child_vcns_valid = 1;
	result->indx_blocks_valid = 0;
	result->reachable_set_exact = 1;
	result->no_unresolved_blocks = 0;
	result->data_preserving = 1;
	result->final_overlay_valid = 0;
}

static void fill_target(struct rh_policy_target_identity *target)
{
	static const unsigned char i30[] = {
		'$', 0, 'I', 0, '3', 0, '0', 0
	};
	size_t i;

	memset(target, 0, sizeof(*target));
	target->object = RH_POLICY_TARGET_INDEX_BITMAP;
	target->action_kind = RH_WRITE_INDEX_BITMAP;
	target->write_object = RH_WRITE_TARGET_NONRESIDENT_ATTRIBUTE;
	target->semantic_flags = RH_WRITE_TARGET_NONRESIDENT |
		RH_WRITE_TARGET_SET_ONLY;
	target->mft_record = UINT64_C(0x2122232425262728);
	target->mft_sequence = UINT16_C(0x3132);
	target->attribute_instance = UINT16_C(0x4142);
	target->attribute_type = UINT32_C(0x51525354);
	target->attribute_name_length = 4U;
	target->attribute_name_prefix_length = 4U;
	target->attribute_name_prefix[0] = '$';
	target->attribute_name_prefix[1] = 'I';
	target->attribute_name_prefix[2] = '3';
	target->attribute_name_prefix[3] = '0';
	rh_sha256(i30, sizeof(i30), target->attribute_name_hash);
	target->lowest_vcn = UINT64_C(0x0101010101010101);
	target->logical_vcn = UINT64_C(0x0202020202020202);
	target->lcn = UINT64_C(0x0303030303030303);
	target->logical_offset = UINT64_C(0x1011121314151617);
	target->logical_length = UINT64_C(0x0011223344556677);
	target->physical_offset = UINT64_C(0x2021222324252627);
	target->physical_length = UINT64_C(0x0001020304050607);
	target->semantic_offset = UINT64_C(0x3031323334353637);
	target->semantic_length = UINT64_C(0x0002030405060708);
	target->operation_ordinal = UINT64_C(0x5152535455565758);
	target->writer_checkpoint = UINT64_C(0x6162636465666768);
	for (i = 0; i < sizeof(target->staged_plan_hash); i++) {
		target->staged_plan_hash[i] = (unsigned char)(0x10U + i);
		target->before_hash[i] = (unsigned char)(0x40U + i);
		target->after_hash[i] = (unsigned char)(0x80U + i);
	}
	target->changes_set_bits = 1U;
}

int main(void)
{
	static const unsigned char expected[32] = {
		0x6b, 0x70, 0x0e, 0xff, 0x4a, 0x16, 0x65, 0x8e,
		0x50, 0x64, 0xc9, 0xc2, 0x5f, 0xe0, 0xe4, 0xa8,
		0xff, 0x29, 0x2d, 0x29, 0x2a, 0xa2, 0x76, 0x26,
		0x23, 0xdc, 0xbc, 0x6c, 0x53, 0x7f, 0x91, 0xae
	};
	struct rh_bitmap_census_result result;
	struct rh_policy_target_identity target;
	struct rh_policy_evidence *evidence = NULL;
	unsigned char seal[32];
	size_t i;
	int status = 1;

	fill_result(&result);
	fill_target(&target);
	if (rh_policy_seal_bitmap_census(&result, &target, 1U, &evidence) ||
			rh_policy_evidence_test_copy_seal(evidence, seal))
		goto out;
	if (memcmp(seal, expected, sizeof(seal))) {
		fputs("policy-seal-v2 actual=", stderr);
		for (i = 0; i < sizeof(seal); i++)
			fprintf(stderr, "%02x", seal[i]);
		fputc('\n', stderr);
		goto out;
	}
	puts("policy-seal-v2 canonical-le=1 known-vector=1 bytes=507");
	status = 0;
out:
	rh_policy_evidence_destroy(evidence);
	return status;
}
