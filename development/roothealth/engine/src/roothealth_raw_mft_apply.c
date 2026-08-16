/* ROOTHEALTH_REPAIR_ROLE(TYPED_WAL_ADAPTER) ROOTHEALTH_IO_ROLE(PLANNER) */
#include "config.h"

#include <errno.h>
#include <limits.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include "attrib.h"
#include "device.h"
#include "layout.h"
#include "mst.h"
#include "roothealth_raw_mft_apply.h"

struct rh_raw_layout_group {
	size_t first;
	size_t count;
	uint64_t record;
	uint16_t sequence;
	uint64_t physical_offset;
};

struct rh_raw_layout_stage_context {
	const struct rh_raw_mft_census *census;
	const struct rh_raw_layout_group *groups;
	size_t group_count;
};

static int rh_hash_exact(const void *bytes, size_t length,
		const unsigned char expected[32])
{
	unsigned char digest[32];

	rh_sha256(bytes, length, digest);
	return !memcmp(digest, expected, sizeof(digest));
}

static int rh_raw_layout_stage_action(ntfs_volume *volume, void *opaque)
{
	const struct rh_raw_layout_stage_context *context = opaque;
	size_t group_index;

	if (!volume || !volume->dev || !volume->mft_na || !context ||
			volume->mft_record_size != 1024U) {
		errno = EINVAL;
		return -1;
	}
	for (group_index = 0; group_index < context->group_count; group_index++) {
		const struct rh_raw_layout_group *group = &context->groups[group_index];
		unsigned char record[1024];
		size_t candidate_index;

		if (group->record > INT64_MAX / sizeof(record) ||
				group->physical_offset > INT64_MAX ||
				ntfs_attr_mst_pread(volume->mft_na,
					(int64_t)(group->record * sizeof(record)), 1,
					sizeof(record), record) != 1)
			return -1;
		for (candidate_index = 0; candidate_index < group->count;
				candidate_index++) {
			const struct rh_raw_layout_candidate *candidate =
				&context->census->layout_candidates[group->first +
				 candidate_index];

			if (candidate->storage.record != group->record ||
					candidate->storage.sequence != group->sequence ||
					(candidate->replacement_length &&
					 candidate->replacement_length != candidate->length) ||
					candidate->logical_offset > sizeof(record) ||
					candidate->length > sizeof(record) -
						candidate->logical_offset ||
					!rh_hash_exact(record, sizeof(record),
						candidate->logical_record_before_hash) ||
					!rh_hash_exact(record + candidate->logical_offset,
						candidate->length, candidate->before_hash)) {
				errno = EIO;
				return -1;
			}
			if (candidate->replacement_length)
				memcpy(record + candidate->logical_offset,
					candidate->replacement, candidate->replacement_length);
			else
				memset(record + candidate->logical_offset, 0,
					candidate->length);
			if (!rh_hash_exact(record, sizeof(record),
					candidate->logical_record_after_hash) ||
					!rh_hash_exact(record + candidate->logical_offset,
						candidate->length, candidate->after_hash)) {
				errno = EIO;
				return -1;
			}
		}
		if (ntfs_mst_pre_write_fixup((NTFS_RECORD *)record, sizeof(record)) ||
				ntfs_pwrite(volume->dev, (int64_t)group->physical_offset,
					sizeof(record), record) != (s64)sizeof(record))
			return -1;
	}
	return 0;
}

int rh_raw_layout_stage(struct rh_ntfs_overlay *overlay,
		const struct rh_raw_mft_census *census,
		size_t *first_operation_ordinal)
{
	struct rh_overlay_expected_write *writes = NULL;
	struct rh_raw_layout_group *groups = NULL;
	struct rh_overlay_action_expectation expectation;
	struct rh_raw_layout_stage_context context;
	struct rh_raw_mft_ref mft_owner;
	size_t checkpoint, candidate_index, group_count = 0;
	int result = -1;

	if (first_operation_ordinal)
		*first_operation_ordinal = 0;
	if (!overlay || !overlay->volume || !overlay->writer || !census ||
			!first_operation_ordinal || !census->records_bounded ||
			!census->attribute_lists_complete || !census->extents_complete ||
			census->records_complete || census->layout_complete ||
			!census->layout_candidate_count || !census->layout_candidates ||
			!census->slots || !census->slot_count ||
			census->slots[0].state != RH_RAW_SLOT_LIVE_BASE ||
			!census->slots[0].sequence ||
			overlay->volume->mft_record_size != 1024U) {
		errno = EINVAL;
		return -1;
	}
	groups = calloc(census->layout_candidate_count, sizeof(*groups));
	if (!groups)
		return -1;
	for (candidate_index = 0;
			candidate_index < census->layout_candidate_count;
			candidate_index++) {
		const struct rh_raw_layout_candidate *candidate =
			&census->layout_candidates[candidate_index];
		struct rh_raw_layout_group *group;

		if (candidate->storage.record <= 3U ||
				candidate->storage.record >= census->slot_count ||
				!candidate->storage.sequence ||
				(candidate->replacement_length &&
				 candidate->replacement_length != candidate->length) ||
				candidate->logical_offset > 1024U ||
				candidate->length > 1024U - candidate->logical_offset ||
				census->slots[candidate->storage.record].sequence !=
					candidate->storage.sequence ||
				(census->slots[candidate->storage.record].state !=
				 RH_RAW_SLOT_LIVE_BASE &&
				 census->slots[candidate->storage.record].state !=
				 RH_RAW_SLOT_LIVE_EXTENT)) {
			errno = EINVAL;
			goto out;
		}
		if (!group_count || groups[group_count - 1U].record !=
				candidate->storage.record) {
			group = &groups[group_count++];
			group->first = candidate_index;
			group->record = candidate->storage.record;
			group->sequence = candidate->storage.sequence;
		} else {
			group = &groups[group_count - 1U];
			if (group->sequence != candidate->storage.sequence ||
					memcmp(census->layout_candidates[candidate_index - 1U].
						logical_record_after_hash,
						candidate->logical_record_before_hash, 32)) {
				errno = EINVAL;
				goto out;
			}
		}
		group->count++;
	}
	writes = calloc(group_count, sizeof(*writes));
	if (!writes)
		goto out;
	mft_owner.record = 0;
	mft_owner.sequence = census->slots[0].sequence;
	for (candidate_index = 0; candidate_index < group_count;
			candidate_index++) {
		struct rh_raw_layout_group *group = &groups[candidate_index];
		struct rh_write_semantic_target *target =
			&writes[candidate_index].target;
		uint64_t logical;

		if (group->record > UINT64_MAX / 1024U) {
			errno = EOVERFLOW;
			goto out;
		}
		logical = group->record * 1024U;
		if (rh_raw_mft_map_stream_range(census, mft_owner, AT_DATA, NULL, 0,
				logical, 1024U, &group->physical_offset) ||
				rh_writer_range_excluded(overlay->writer,
					group->physical_offset, 1024U)) {
			errno = EINVAL;
			goto out;
		}
		writes[candidate_index].offset = group->physical_offset;
		writes[candidate_index].length = 1024U;
		target->seal_version = 1;
		target->object = RH_WRITE_TARGET_MFT_RECORD_PRIMARY;
		target->owner_mft_record = group->record;
		target->owner_sequence = group->sequence;
		target->flags = RH_WRITE_TARGET_PRIMARY | RH_WRITE_TARGET_RESIDENT;
		target->lowest_vcn = -1;
		target->logical_vcn = -1;
		target->lcn = -1;
		target->logical_offset = 0;
		target->logical_length = 1024U;
		target->semantic_target_offset = group->physical_offset;
		target->semantic_target_length = 1024U;
		if (!rh_write_semantic_target_valid(RH_WRITE_MFT_RECORD, target,
				group->physical_offset, 1024U, 0)) {
			errno = EINVAL;
			goto out;
		}
	}
	checkpoint = rh_writer_plan_checkpoint(overlay->writer);
	expectation.kind = RH_WRITE_MFT_RECORD;
	expectation.writes = writes;
	expectation.write_count = group_count;
	context.census = census;
	context.groups = groups;
	context.group_count = group_count;
	if (rh_ntfs_overlay_run_action(overlay, &expectation,
			rh_raw_layout_stage_action, &context))
		goto out;
	if (overlay->writer->operation_count != checkpoint + group_count) {
		errno = EIO;
		goto out;
	}
	*first_operation_ordinal = checkpoint + 1U;
	result = 0;
out:
	free(writes);
	free(groups);
	return result;
}
