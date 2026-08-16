/* ROOTHEALTH_REPAIR_ROLE(TYPED_WAL_ADAPTER) ROOTHEALTH_IO_ROLE(PLANNER) */
#include "config.h"

#include <errno.h>
#include <limits.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>

#include "device.h"
#include "layout.h"
#include "mst.h"
#include "roothealth_index_bitmap.h"

struct rh_index_bitmap_stage_context {
	const struct rh_index_bitmap_census *census;
	size_t first;
	size_t count;
};

static void rh_i30_name_hash(unsigned char hash[32])
{
	static const unsigned char i30_utf16le[] = {
		'$', 0, 'I', 0, '3', 0, '0', 0
	};

	rh_sha256(i30_utf16le, sizeof(i30_utf16le), hash);
}

static int rh_index_bitmap_stage_action(ntfs_volume *volume, void *opaque)
{
	const struct rh_index_bitmap_stage_context *context = opaque;
	size_t i;

	if (!volume || !volume->dev || !context || !context->census) {
		errno = EINVAL;
		return -1;
	}
	for (i = 0; i < context->count; i++) {
		const struct rh_index_bitmap_change *change =
			&context->census->changes[context->first + i];
		if (change->physical_offset > INT64_MAX)
			return -1;
		if (change->storage == RH_INDEX_BITMAP_RESIDENT_MFT) {
			unsigned char *record = malloc(volume->mft_record_size);
			MFT_RECORD *mft;
			int failed = 1;

			if (!record)
				return -1;
			mft = (MFT_RECORD *)record;
			if (change->owner_mft_record > INT64_MAX /
					volume->mft_record_size ||
					change->resident_record_offset != change->physical_offset ||
					change->physical_length != volume->mft_record_size ||
					change->resident_value_offset >= volume->mft_record_size ||
					ntfs_attr_mst_pread(volume->mft_na,
						(int64_t)(change->owner_mft_record *
						 volume->mft_record_size), 1,
						volume->mft_record_size, record) != 1 ||
					mft->magic != magic_FILE ||
					le32_to_cpu(mft->mft_record_number) !=
						change->owner_mft_record ||
					le16_to_cpu(mft->sequence_number) !=
						change->owner_sequence ||
					record[change->resident_value_offset] != change->before)
					goto resident_out;
			record[change->resident_value_offset] = change->after;
			if (ntfs_mst_pre_write_fixup((NTFS_RECORD *)record,
					volume->mft_record_size) ||
					ntfs_pwrite(volume->dev,
						(int64_t)change->physical_offset,
						volume->mft_record_size, record) !=
						volume->mft_record_size)
					goto resident_out;
			failed = 0;
resident_out:
			free(record);
			if (failed)
				return -1;
		} else if (change->storage == RH_INDEX_BITMAP_NONRESIDENT) {
			if (change->physical_length != 1 ||
					ntfs_pwrite(volume->dev,
						(int64_t)change->physical_offset, 1,
						&change->after) != 1)
				return -1;
		} else {
			errno = EINVAL;
			return -1;
		}
	}
	return 0;
}

size_t rh_index_bitmap_next_batch_count(
		const struct rh_index_bitmap_census *census, size_t wal_capacity)
{
	if (!census || !census->change_count || !wal_capacity)
		return 0;
	if (wal_capacity > RH_INDEX_BITMAP_MAX_CHANGES)
		wal_capacity = RH_INDEX_BITMAP_MAX_CHANGES;
	return census->change_count < wal_capacity ? census->change_count :
		wal_capacity;
}

int rh_index_bitmap_stage_prefix(struct rh_ntfs_overlay *overlay,
		const struct rh_index_bitmap_census *census,
		size_t wal_capacity, size_t *staged_change_count,
		size_t *first_operation_ordinal)
{
	struct rh_overlay_expected_write *writes = NULL;
	struct rh_overlay_action_expectation expectation;
	struct rh_index_bitmap_stage_context context;
	size_t checkpoint, count, i;
	int result = -1;

	if (first_operation_ordinal)
		*first_operation_ordinal = 0;
	if (staged_change_count)
		*staged_change_count = 0;
	count = rh_index_bitmap_next_batch_count(census, wal_capacity);
	if (!overlay || !overlay->volume || !overlay->writer || !census ||
			!first_operation_ordinal || !staged_change_count || !count ||
			!census->complete ||
			!census->index_tree_complete || !census->child_vcns_valid ||
			!census->indx_blocks_valid || !census->reachable_set_exact ||
			!census->sets_proven_reachable || !census->targets_outside_wal ||
			!census->set_only_safe || census->clear_bits_required ||
			!census->change_count) {
		errno = EINVAL;
		return -1;
	}
	writes = calloc(count, sizeof(*writes));
	if (!writes)
		return -1;
	for (i = 0; i < count; i++) {
		const struct rh_index_bitmap_change *change = &census->changes[i];
		struct rh_write_semantic_target *target = &writes[i].target;
		uint16_t location_flags;

		if (!change->set_mask || change->clear_mask ||
				change->after != (unsigned char)(change->before |
				 change->set_mask) ||
				(change->set_mask & (unsigned char)(change->set_mask - 1U)) ||
				change->logical_offset > INT64_MAX ||
				!change->physical_length ||
				rh_writer_range_excluded(overlay->writer,
					change->physical_offset,
					(size_t)change->physical_length)) {
			errno = EINVAL;
			goto out;
		}
		writes[i].offset = change->physical_offset;
		writes[i].length = change->physical_length;
		target->seal_version = 1;
		if (change->storage == RH_INDEX_BITMAP_RESIDENT_MFT) {
			if (change->physical_length != overlay->volume->mft_record_size ||
					change->resident_record_offset != change->physical_offset ||
					change->resident_value_offset >=
						overlay->volume->mft_record_size) {
				errno = EINVAL;
				goto out;
			}
			target->object = RH_WRITE_TARGET_MFT_RECORD_PRIMARY;
			location_flags = RH_WRITE_TARGET_PRIMARY |
				RH_WRITE_TARGET_RESIDENT;
			target->lowest_vcn = -1;
			target->logical_vcn = -1;
			target->lcn = -1;
		} else if (change->storage ==
				RH_INDEX_BITMAP_NONRESIDENT) {
			if (change->physical_length != 1) {
				errno = EINVAL;
				goto out;
			}
			target->object = RH_WRITE_TARGET_NONRESIDENT_ATTRIBUTE;
			location_flags = RH_WRITE_TARGET_NONRESIDENT;
			target->lowest_vcn = change->lowest_vcn;
			target->logical_vcn = change->logical_vcn;
			target->lcn = change->lcn;
		} else {
			errno = EINVAL;
			goto out;
		}
		target->owner_mft_record = change->owner_mft_record;
		target->owner_sequence = change->owner_sequence;
		target->attribute_instance = change->bitmap_instance;
		target->attribute_type = AT_BITMAP;
		target->attribute_name_length = 4;
		target->flags = location_flags | RH_WRITE_TARGET_SET_ONLY;
		rh_i30_name_hash(target->attribute_name_hash);
		target->logical_offset = change->logical_offset;
		target->logical_length = 1;
		target->semantic_target_offset = change->storage ==
			RH_INDEX_BITMAP_RESIDENT_MFT ?
			change->resident_record_offset + change->resident_value_offset :
			change->physical_offset;
		target->semantic_target_length = 1;
		if (!rh_write_semantic_target_valid(RH_WRITE_INDEX_BITMAP, target,
				change->physical_offset, (size_t)change->physical_length, 0)) {
			errno = EINVAL;
			goto out;
		}
	}
	checkpoint = rh_writer_plan_checkpoint(overlay->writer);
	expectation.kind = RH_WRITE_INDEX_BITMAP;
	expectation.writes = writes;
	expectation.write_count = count;
	context.census = census;
	context.first = 0;
	context.count = count;
	if (rh_ntfs_overlay_run_action(overlay, &expectation,
			rh_index_bitmap_stage_action, &context))
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

int rh_index_bitmap_stage(struct rh_ntfs_overlay *overlay,
		const struct rh_index_bitmap_census *census,
		size_t *first_operation_ordinal)
{
	size_t staged = 0;

	if (!census) {
		errno = EINVAL;
		return -1;
	}
	if (census->change_count > RH_INDEX_BITMAP_MAX_CHANGES) {
		/* The caller must commit a bounded prefix and rescan, not diagnose
		 * the filesystem as corrupt merely because one WAL cannot hold it. */
		errno = E2BIG;
		return -1;
	}
	if (rh_index_bitmap_stage_prefix(overlay, census,
			RH_INDEX_BITMAP_MAX_CHANGES, &staged,
			first_operation_ordinal))
		return -1;
	if (staged != census->change_count) {
		errno = EIO;
		return -1;
	}
	return 0;
}
