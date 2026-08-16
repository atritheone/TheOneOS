/* ROOTHEALTH_REPAIR_ROLE(TYPED_WAL_ADAPTER) ROOTHEALTH_IO_ROLE(PLANNER) */
#include "config.h"

#include <errno.h>
#include <limits.h>
#include <stddef.h>
#include <stdlib.h>

#include "attrib.h"
#include "layout.h"
#include "roothealth_mft_bitmap.h"

struct rh_mft_bitmap_stage_context {
	const struct rh_mft_bitmap_census *census;
	size_t first;
	size_t count;
};

static int rh_mft_bitmap_stage_action(ntfs_volume *volume, void *opaque)
{
	const struct rh_mft_bitmap_stage_context *context = opaque;
	ntfs_attr *attribute = volume->mftbmp_na;
	size_t i;

	if (!attribute || !attribute->ni || attribute->ni->mft_no != FILE_MFT ||
			attribute->type != AT_BITMAP || attribute->name_len ||
			!NAttrNonResident(attribute)) {
		errno = EIO;
		return -1;
	}
	for (i = 0; i < context->count; i++) {
		const struct rh_mft_bitmap_change *change =
			&context->census->changes[context->first + i];

		if (ntfs_attr_pwrite(attribute, (int64_t)change->logical_offset, 1,
				&change->after) != 1)
			return -1;
	}
	return 0;
}

size_t rh_mft_bitmap_next_batch_count(
		const struct rh_mft_bitmap_census *census, size_t wal_capacity)
{
	if (!census || !census->change_count || !wal_capacity)
		return 0;
	if (wal_capacity > RH_MFT_BITMAP_MAX_CHANGES)
		wal_capacity = RH_MFT_BITMAP_MAX_CHANGES;
	return census->change_count < wal_capacity ? census->change_count :
		wal_capacity;
}

int rh_mft_bitmap_stage_prefix(struct rh_ntfs_overlay *overlay,
		const struct rh_mft_bitmap_census *census, size_t wal_capacity,
		size_t *staged_change_count, size_t *first_operation_ordinal)
{
	struct rh_overlay_expected_write *writes = NULL;
	struct rh_overlay_action_expectation expectation;
	struct rh_mft_bitmap_stage_context context;
	size_t checkpoint, count, i;
	int result = -1;

	if (first_operation_ordinal)
		*first_operation_ordinal = 0;
	if (staged_change_count)
		*staged_change_count = 0;
	count = rh_mft_bitmap_next_batch_count(census, wal_capacity);
	if (!overlay || !overlay->volume || !overlay->writer || !census ||
			!census->complete ||
			!census->structurally_valid || !count ||
			!census->changes || !census->bitmap_bytes ||
			!census->sets_proven_live || !census->clears_structurally_free ||
			!census->targets_outside_wal || !first_operation_ordinal ||
			!staged_change_count) {
		errno = EINVAL;
		return -1;
	}
	writes = calloc(count, sizeof(*writes));
	if (!writes)
		return -1;
	for (i = 0; i < count; i++) {
		const struct rh_mft_bitmap_change *change = &census->changes[i];
		struct rh_write_semantic_target *target = &writes[i].target;
		uint64_t within, physical;
		unsigned char set_mask, clear_mask;

		if (overlay->volume->cluster_size != 4096) {
			errno = EINVAL;
			goto out;
		}
		set_mask = (unsigned char)((unsigned char)~change->before &
			change->after);
		clear_mask = (unsigned char)(change->before &
			(unsigned char)~change->after);
		within = change->logical_offset % overlay->volume->cluster_size;
		if (!census->mft_sequence ||
				change->logical_offset >= census->bitmap_bytes ||
				change->logical_offset > INT64_MAX ||
				change->logical_vcn != change->logical_offset /
					overlay->volume->cluster_size ||
				change->logical_vcn > INT64_MAX || change->lcn > INT64_MAX ||
				change->lcn > (UINT64_MAX - within) /
					overlay->volume->cluster_size ||
				(physical = change->lcn * overlay->volume->cluster_size +
				 within) != change->physical_offset ||
				rh_writer_range_excluded(overlay->writer, physical, 1) ||
				change->set_mask != set_mask ||
				change->clear_mask != clear_mask ||
				!!change->set_mask == !!change->clear_mask) {
			errno = EINVAL;
			goto out;
		}
		writes[i].offset = change->physical_offset;
		writes[i].length = 1;
		target->seal_version = 1;
		target->object = RH_WRITE_TARGET_NONRESIDENT_ATTRIBUTE;
		target->owner_mft_record = FILE_MFT;
		target->owner_sequence = census->mft_sequence;
		target->attribute_instance = census->bitmap_attribute_instance;
		target->attribute_type = AT_BITMAP;
		target->attribute_name_length = 0;
		target->flags = RH_WRITE_TARGET_NONRESIDENT |
			(change->set_mask ? RH_WRITE_TARGET_SET_ONLY :
			 RH_WRITE_TARGET_CLEAR_ONLY);
		rh_sha256("", 0, target->attribute_name_hash);
		target->lowest_vcn = 0;
		target->logical_vcn = (int64_t)change->logical_vcn;
		target->logical_offset = change->logical_offset;
		target->logical_length = 1;
		target->semantic_target_offset = change->physical_offset;
		target->semantic_target_length = 1;
		target->lcn = (int64_t)change->lcn;
	}
	checkpoint = rh_writer_plan_checkpoint(overlay->writer);
	expectation.kind = RH_WRITE_BITMAP_MFT;
	expectation.writes = writes;
	expectation.write_count = count;
	context.census = census;
	context.first = 0;
	context.count = count;
	if (rh_ntfs_overlay_run_action(overlay, &expectation,
			rh_mft_bitmap_stage_action, &context))
		goto out;
	if (overlay->writer->operation_count != checkpoint + count) {
		errno = EIO;
		goto out;
	}
	*first_operation_ordinal = checkpoint + 1U;
	*staged_change_count = count;
	result = 0;
out:
	free(writes);
	return result;
}

int rh_mft_bitmap_stage(struct rh_ntfs_overlay *overlay,
		const struct rh_mft_bitmap_census *census,
		size_t *first_operation_ordinal)
{
	size_t staged = 0;

	if (!census) {
		errno = EINVAL;
		return -1;
	}
	if (census->change_count > RH_MFT_BITMAP_MAX_CHANGES) {
		errno = E2BIG;
		return -1;
	}
	if (rh_mft_bitmap_stage_prefix(overlay, census,
			RH_MFT_BITMAP_MAX_CHANGES, &staged, first_operation_ordinal))
		return -1;
	if (staged != census->change_count) {
		errno = EIO;
		return -1;
	}
	return 0;
}
