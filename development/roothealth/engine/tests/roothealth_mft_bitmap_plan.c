#include "config.h"

#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "roothealth_mft_bitmap.h"

static int parse_u64(const char *text, uint64_t *value)
{
	char *end = NULL;
	unsigned long long parsed;

	errno = 0;
	parsed = strtoull(text, &end, 0);
	if (errno || !end || *end)
		return -1;
	*value = (uint64_t)parsed;
	return 0;
}

static int authorization_closed(const struct rh_writer *writer, size_t first)
{
	const struct rh_policy_definition *problem;
	const struct rh_policy_definition *aggregate;
	struct rh_policy_authorization authorization;

	problem = rh_policy_problem(PR_MFT_BITMAP_MISMATCH);
	aggregate = rh_policy_aggregate("MFT_BITMAP");
	if (!problem || !aggregate)
		return -1;
	return rh_policy_authorize_operation(problem, NULL, 0, writer, first,
			&authorization) == RH_POLICY_FINAL_DENIED &&
		rh_policy_authorize_operation(aggregate, NULL, 0, writer, first,
			&authorization) == RH_POLICY_FINAL_DENIED ? 0 : -1;
}

static int semantic_target_exact(const struct rh_write_operation *operation,
		const struct rh_mft_bitmap_census *census,
		const struct rh_mft_bitmap_change *change)
{
	const struct rh_write_semantic_target *target = &operation->target;
	unsigned char empty_name_hash[32];
	unsigned char before_hash[32];
	unsigned char after_hash[32];
	uint16_t flags;

	if (!operation || !census || !change ||
			change->logical_vcn > INT64_MAX || change->lcn > INT64_MAX ||
			!!change->set_mask == !!change->clear_mask)
		return 0;
	flags = RH_WRITE_TARGET_NONRESIDENT |
		(change->set_mask ? RH_WRITE_TARGET_SET_ONLY :
		 RH_WRITE_TARGET_CLEAR_ONLY);
	rh_sha256("", 0, empty_name_hash);
	rh_sha256(operation->before, operation->length, before_hash);
	rh_sha256(operation->after, operation->length, after_hash);
	return target->seal_version == 1 &&
		target->object == RH_WRITE_TARGET_NONRESIDENT_ATTRIBUTE &&
		target->owner_mft_record == FILE_MFT &&
		target->owner_sequence == census->mft_sequence &&
		target->attribute_instance == census->bitmap_attribute_instance &&
		target->attribute_type == AT_BITMAP &&
		!target->attribute_name_length && target->flags == flags &&
		!memcmp(target->attribute_name_hash, empty_name_hash, 32) &&
		!target->lowest_vcn &&
		target->logical_vcn == (int64_t)change->logical_vcn &&
		target->logical_offset == change->logical_offset &&
		target->logical_length == 1 &&
		target->semantic_target_offset == change->physical_offset &&
		target->semantic_target_length == 1 &&
		target->lcn == (int64_t)change->lcn &&
		!target->evidence_version && !target->evidence_generation &&
		!target->finalized &&
		!memcmp(target->semantic_before_hash, before_hash, 32) &&
		!memcmp(target->semantic_after_hash, after_hash, 32);
}

int main(int argc, char **argv)
{
	struct rh_writer writer;
	struct rh_ntfs_overlay overlay;
	struct rh_mft_bitmap_census initial;
	struct rh_mft_bitmap_census repeat;
	struct rh_mft_bitmap_census final;
	struct rh_policy_evidence *evidence = NULL;
	uint64_t roothealth_record, roothealth_sequence, expected_logical;
	uint64_t expected_physical, expected_before, expected_after;
	uint64_t expected_set, expected_clear, expected_obligation;
	size_t first = 0;
	int result = 1;

	memset(&initial, 0, sizeof(initial));
	memset(&repeat, 0, sizeof(repeat));
	memset(&final, 0, sizeof(final));
	if (argc != 11 || parse_u64(argv[2], &roothealth_record) ||
			parse_u64(argv[3], &roothealth_sequence) ||
			parse_u64(argv[4], &expected_logical) ||
			parse_u64(argv[5], &expected_physical) ||
			parse_u64(argv[6], &expected_before) ||
			parse_u64(argv[7], &expected_after) ||
			parse_u64(argv[8], &expected_set) ||
			parse_u64(argv[9], &expected_clear) ||
			parse_u64(argv[10], &expected_obligation) ||
			roothealth_sequence > UINT16_MAX || expected_before > UINT8_MAX ||
			expected_after > UINT8_MAX || expected_set > UINT8_MAX ||
			expected_clear > UINT8_MAX || expected_obligation > 1U)
		return 5;
	if (rh_writer_open(&writer, argv[1]))
		return 3;
	if (rh_ntfs_overlay_mount(&overlay, &writer, 0))
		goto out_writer;
	if (rh_mft_bitmap_census_run(overlay.volume, &writer, 1,
			roothealth_record, (uint16_t)roothealth_sequence, &initial)) {
		fprintf(stderr, "initial census failed: %s slots=%llu/%llu live=%llu "
			"free=%llu unreadable=%llu ambiguous=%llu\n", strerror(errno),
			(unsigned long long)initial.mft_slots_completed,
			(unsigned long long)initial.mft_slots_expected,
			(unsigned long long)initial.mft_slots_in_use,
			(unsigned long long)initial.mft_slots_free,
			(unsigned long long)initial.unreadable_slots,
			(unsigned long long)initial.ambiguous_slots);
		goto out_overlay;
	}
	if (!initial.complete || !initial.structurally_valid || initial.clean ||
			initial.change_count != 1U || initial.mft_slots_expected != 82U ||
			initial.mft_slots_completed != initial.mft_slots_expected ||
			initial.mft_slots_in_use != 37U || initial.mft_slots_free != 45U ||
			initial.bitmap_bytes != 16U || initial.padding_bits_examined != 46U ||
			initial.unreadable_slots || initial.ambiguous_slots ||
			!initial.roothealth_record_bound ||
			(uint64_t)initial.roothealth_false_free_obligation !=
				expected_obligation ||
			initial.changes[0].logical_offset != expected_logical ||
			initial.changes[0].physical_offset != expected_physical ||
			initial.changes[0].before != (unsigned char)expected_before ||
			initial.changes[0].after != (unsigned char)expected_after ||
			initial.changes[0].set_mask != (unsigned char)expected_set ||
			initial.changes[0].clear_mask != (unsigned char)expected_clear ||
			!initial.sets_proven_live || !initial.clears_structurally_free ||
			initial.clears_proven_unreferenced ||
			!initial.targets_outside_wal) {
		fprintf(stderr, "unexpected initial census: clean=%d changes=%zu "
			"logical=%llu physical=%llu before=%02x after=%02x set=%02x "
			"clear=%02x obligation=%d\n", initial.clean,
			initial.change_count,
			(unsigned long long)(initial.change_count ?
				initial.changes[0].logical_offset : 0),
			(unsigned long long)(initial.change_count ?
				initial.changes[0].physical_offset : 0),
			initial.change_count ? initial.changes[0].before : 0,
			initial.change_count ? initial.changes[0].after : 0,
			initial.change_count ? initial.changes[0].set_mask : 0,
			initial.change_count ? initial.changes[0].clear_mask : 0,
			initial.roothealth_false_free_obligation);
		goto out_initial;
	}
	if (rh_mft_bitmap_census_run(overlay.volume, &writer, 99,
			roothealth_record, (uint16_t)roothealth_sequence, &repeat) ||
			memcmp(initial.census_hash, repeat.census_hash,
				sizeof(initial.census_hash)) ||
			memcmp(initial.expected_hash, repeat.expected_hash,
				sizeof(initial.expected_hash))) {
		fprintf(stderr, "canonical census hash changed with runtime generation\n");
		rh_mft_bitmap_census_destroy(&repeat);
		goto out_initial;
	}
	rh_mft_bitmap_census_destroy(&repeat);
	if (rh_mft_bitmap_stage(&overlay, &initial, &first) || first != 1U ||
			writer.operation_count != 1U || writer.write_boundaries ||
			writer.operations[0].kind != RH_WRITE_BITMAP_MFT ||
			writer.operations[0].offset != expected_physical ||
			writer.operations[0].length != 1U ||
			writer.operations[0].before[0] != (unsigned char)expected_before ||
			writer.operations[0].after[0] != (unsigned char)expected_after ||
			!semantic_target_exact(&writer.operations[0], &initial,
				&initial.changes[0])) {
		fprintf(stderr, "stage failed: %s first=%zu operations=%zu "
			"source_writes=%zu\n", strerror(errno), first,
			writer.operation_count, writer.write_boundaries);
		goto out_initial;
	}
	if (rh_mft_bitmap_census_run(overlay.volume, &writer, 2,
			roothealth_record, (uint16_t)roothealth_sequence, &final) ||
			!final.complete || !final.structurally_valid || !final.clean ||
			final.change_count || !final.roothealth_record_bound ||
			!final.roothealth_bitmap_bit_set ||
			final.roothealth_false_free_obligation ||
			memcmp(initial.expected_hash, final.expected_hash,
				sizeof(initial.expected_hash))) {
		fprintf(stderr, "final census failed: %s complete=%d structural=%d "
			"clean=%d changes=%zu roothealth_set=%d obligation=%d\n",
			strerror(errno), final.complete, final.structurally_valid,
			final.clean, final.change_count, final.roothealth_bitmap_bit_set,
			final.roothealth_false_free_obligation);
		goto out_final;
	}
	if (!rh_mft_bitmap_seal_policy(&initial, &final, &writer, first, 0, 1,
			NULL, &evidence) || evidence) {
		fprintf(stderr, "identity-unbound evidence was not refused\n");
		goto out_final;
	}
	if (!rh_mft_bitmap_seal_policy(&initial, &final, &writer, first, 1, 0,
			NULL, &evidence) || evidence) {
		fprintf(stderr, "namespace-incomplete evidence was not refused\n");
		goto out_final;
	}
	errno = 0;
	if (!rh_mft_bitmap_seal_policy(&initial, &final, &writer, first, 1, 1,
			NULL, &evidence) || evidence || errno != EPERM ||
			authorization_closed(&writer, first)) {
		fprintf(stderr, "closed ledger gate was bypassed: %s evidence=%p\n",
			strerror(errno), (void *)evidence);
		goto out_final;
	}
	printf("mft-bitmap-plan slots=%llu live=%llu free=%llu bitmap_bytes=%zu "
		"padding=%llu operations=%zu action=%u logical=%llu physical=%llu "
		"before=%02x after=%02x set=%02x clear=%02x "
		"roothealth_false_free=%d source_writes=%zu final_clean=%d "
		"clears_proven_unreferenced=0 ledger_gate=closed "
		"canonical_hash=1 seal_refusals=3 authorized=0\n",
		(unsigned long long)initial.mft_slots_expected,
		(unsigned long long)initial.mft_slots_in_use,
		(unsigned long long)initial.mft_slots_free, initial.bitmap_bytes,
		(unsigned long long)initial.padding_bits_examined,
		writer.operation_count,
		RH_WRITE_ACTION_ID(writer.operations[0].kind),
		(unsigned long long)initial.changes[0].logical_offset,
		(unsigned long long)initial.changes[0].physical_offset,
		initial.changes[0].before, initial.changes[0].after,
		initial.changes[0].set_mask, initial.changes[0].clear_mask,
		initial.roothealth_false_free_obligation, writer.write_boundaries,
		final.clean);
	result = 0;
out_final:
	rh_policy_evidence_destroy(evidence);
	rh_mft_bitmap_census_destroy(&final);
out_initial:
	rh_mft_bitmap_census_destroy(&initial);
out_overlay:
	rh_ntfs_overlay_unmount(&overlay);
out_writer:
	rh_writer_close(&writer);
	return result;
}
