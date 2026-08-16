/* ROOTHEALTH_REPAIR_ROLE(DIAGNOSTIC) */
#include "config.h"

#include <errno.h>
#include <stdio.h>
#include <string.h>

#include "roothealth_raw_mft_apply.h"

int main(int argc, char **argv)
{
	struct rh_writer writer;
	struct rh_ntfs_overlay overlay;
	struct rh_raw_mft_census initial, final;
	struct rh_raw_mft_ref mft_owner;
	const struct rh_write_operation *operation;
	static const unsigned char zero_digest[32];
	uint64_t source_offset;
	size_t first = 0;
	int result = 1;

	memset(&initial, 0, sizeof(initial));
	memset(&final, 0, sizeof(final));
	if (argc != 2)
		return 5;
	if (rh_writer_open(&writer, argv[1]))
		return 3;
	if (rh_ntfs_overlay_mount(&overlay, &writer, 0))
		goto out_writer;
	if (rh_raw_mft_census_run(overlay.volume, &writer, 1, &initial) ||
			!initial.records_bounded || initial.records_complete ||
			initial.layout_complete || initial.layout_candidate_count != 4U ||
			initial.layout_candidates[0].storage.record != 24U ||
			initial.layout_candidates[3].storage.record != 24U ||
			memcmp(initial.layout_candidates[0].logical_record_before_hash,
				initial.layout_candidates[3].logical_record_after_hash, 32) == 0 ||
			writer.operation_count || writer.write_boundaries) {
		fprintf(stderr, "initial raw census mismatch\n");
		goto out_initial;
	}
	mft_owner.record = 0;
	mft_owner.sequence = initial.slots[0].sequence;
	if (rh_raw_mft_map_stream_range(&initial, mft_owner, AT_DATA, NULL, 0,
			24U * 1024U, 1024U, &source_offset)) {
		fprintf(stderr, "MFT map failed: errno=%d seq=%u\n", errno,
			mft_owner.sequence);
		goto out_initial;
	}
	{
		struct rh_write_semantic_target probe;
		if (rh_writer_range_excluded(&writer, source_offset, 1024U)) {
			fprintf(stderr, "mapped MFT range unexpectedly excluded\n");
			goto out_initial;
		}
		memset(&probe, 0, sizeof(probe));
		probe.seal_version = 1;
		probe.object = RH_WRITE_TARGET_MFT_RECORD_PRIMARY;
		probe.owner_mft_record = 24U;
		probe.owner_sequence = initial.slots[24].sequence;
		probe.flags = RH_WRITE_TARGET_PRIMARY | RH_WRITE_TARGET_RESIDENT;
		probe.lowest_vcn = probe.logical_vcn = probe.lcn = -1;
		probe.logical_length = probe.semantic_target_length = 1024U;
		probe.semantic_target_offset = source_offset;
		if (!rh_write_semantic_target_valid(RH_WRITE_MFT_RECORD, &probe,
				source_offset, 1024U, 0)) {
			fprintf(stderr, "probe target invalid: offset=%llu seq=%u state=%u\n",
				(unsigned long long)source_offset, probe.owner_sequence,
				initial.slots[24].state);
			goto out_initial;
		}
	}
	for (first = 0; first < initial.layout_candidate_count; first++) {
		const struct rh_raw_layout_candidate *candidate =
			&initial.layout_candidates[first];
		if (candidate->storage.record != 24U ||
				candidate->storage.sequence != initial.slots[24].sequence ||
				(candidate->replacement_length &&
				 candidate->replacement_length != candidate->length)) {
			fprintf(stderr, "candidate %zu failed stage preconditions: "
				"record=%llu seq=%u/%u length=%u replacement=%u\n", first,
				(unsigned long long)candidate->storage.record,
				candidate->storage.sequence, initial.slots[24].sequence,
				candidate->length, candidate->replacement_length);
			goto out_initial;
		}
	}
	first = 0;
	if (rh_raw_layout_stage(&overlay, &initial, &first) || first != 1U ||
			writer.operation_count != 1U || writer.write_boundaries) {
		fprintf(stderr, "layout stage failed: errno=%d first=%zu ops=%zu "
			"writes=%zu\n", errno, first, writer.operation_count,
			writer.write_boundaries);
		goto out_initial;
	}
	operation = &writer.operations[0];
	source_offset = operation->offset;
	if (operation->kind != RH_WRITE_MFT_RECORD || operation->length != 1024U ||
			operation->target.object != RH_WRITE_TARGET_MFT_RECORD_PRIMARY ||
			operation->target.owner_mft_record != 24U ||
			operation->target.owner_sequence !=
				initial.layout_candidates[0].storage.sequence ||
			operation->target.flags != (RH_WRITE_TARGET_PRIMARY |
				RH_WRITE_TARGET_RESIDENT) || operation->target.logical_offset ||
			operation->target.logical_length != 1024U ||
			operation->target.semantic_target_offset != operation->offset ||
			operation->target.semantic_target_length != 1024U ||
			memcmp(operation->target.semantic_before_hash,
				initial.layout_candidates[0].logical_record_before_hash, 32) ||
			!memcmp(operation->target.semantic_after_hash, zero_digest, 32) ||
			!memcmp(operation->target.semantic_before_hash,
				operation->target.semantic_after_hash, 32) ||
			operation->target.finalized || operation->target.evidence_version) {
		fprintf(stderr, "staged operation semantic mismatch: kind=%u off=%llu "
			"len=%zu object=%u owner=%llu seq=%u flags=%x logical=%llu/%llu "
			"semantic=%llu/%llu before=%d after=%d finalized=%u ev=%u\n",
			(unsigned)operation->kind, (unsigned long long)operation->offset,
			operation->length, operation->target.object,
			(unsigned long long)operation->target.owner_mft_record,
			operation->target.owner_sequence, operation->target.flags,
			(unsigned long long)operation->target.logical_offset,
			(unsigned long long)operation->target.logical_length,
			(unsigned long long)operation->target.semantic_target_offset,
			(unsigned long long)operation->target.semantic_target_length,
			memcmp(operation->target.semantic_before_hash,
				initial.layout_candidates[0].logical_record_before_hash, 32),
			memcmp(operation->target.semantic_after_hash, zero_digest, 32),
			operation->target.finalized, operation->target.evidence_version);
		goto out_initial;
	}
	if (rh_raw_mft_census_run(overlay.volume, &writer, 2, &final) ||
			!final.records_bounded || !final.records_complete ||
			!final.layout_complete || !final.attribute_lists_complete ||
			!final.extents_complete || final.layout_candidate_count ||
			writer.write_boundaries) {
		fprintf(stderr, "final overlay census mismatch: errno=%d records=%u "
			"layout=%u candidates=%zu\n", errno, final.records_complete,
			final.layout_complete, final.layout_candidate_count);
		goto out_final;
	}
	printf("raw-layout-plan record=24 candidates=4 operations=1 action=%u "
		"offset=%llu length=1024 mst=full-record source_writes=0 "
		"final_clean=1 policy_gate=full-ledger-pending\n",
		RH_WRITE_ACTION_ID(operation->kind),
		(unsigned long long)source_offset);
	result = 0;
out_final:
	rh_raw_mft_census_release(&final);
out_initial:
	rh_raw_mft_census_release(&initial);
	rh_ntfs_overlay_unmount(&overlay);
out_writer:
	rh_writer_close(&writer);
	return result;
}
