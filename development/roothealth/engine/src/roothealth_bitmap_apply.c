/* ROOTHEALTH_REPAIR_ROLE(TYPED_WAL_ADAPTER) ROOTHEALTH_IO_ROLE(PLANNER) */
#include "config.h"

#include <errno.h>
#include <stddef.h>
#include <stdlib.h>

#include "attrib.h"
#include "inode.h"
#include "layout.h"
#include "roothealth_bitmap.h"

struct rh_bitmap_stage_context {
	const struct rh_cluster_bitmap_census *census;
	size_t first;
	size_t count;
};

static int rh_bitmap_stage_action(ntfs_volume *volume, void *opaque)
{
	const struct rh_bitmap_stage_context *context = opaque;
	ntfs_inode *inode = NULL;
	ntfs_attr *attribute = NULL;
	size_t i;
	int result = -1;

	inode = ntfs_inode_open(volume, FILE_Bitmap);
	if (!inode)
		goto out;
	attribute = ntfs_attr_open(inode, AT_DATA, AT_UNNAMED, 0);
	if (!attribute)
		goto out;
	for (i = 0; i < context->count; i++) {
		const struct rh_cluster_bitmap_change *change =
			&context->census->changes[context->first + i];

		if (ntfs_attr_pwrite(attribute, (int64_t)change->logical_offset, 1,
				&change->after) != 1)
			goto out;
	}
	result = 0;
out:
	if (attribute)
		ntfs_attr_close(attribute);
	if (inode)
		ntfs_inode_close(inode);
	return result;
}

size_t rh_cluster_bitmap_next_batch_count(
		const struct rh_cluster_bitmap_census *census, size_t wal_capacity)
{
	if (!census || !census->change_count || !wal_capacity)
		return 0;
	if (wal_capacity > RH_BITMAP_MAX_CHANGES)
		wal_capacity = RH_BITMAP_MAX_CHANGES;
	return census->change_count < wal_capacity ? census->change_count :
		wal_capacity;
}

int rh_cluster_bitmap_stage_prefix(struct rh_ntfs_overlay *overlay,
		const struct rh_cluster_bitmap_census *census, size_t wal_capacity,
		size_t *staged_change_count, size_t *first_operation_ordinal)
{
	struct rh_overlay_expected_write *writes = NULL;
	struct rh_overlay_action_expectation expectation;
	struct rh_bitmap_stage_context context;
	size_t checkpoint, count, i;
	int result = -1;

	if (first_operation_ordinal)
		*first_operation_ordinal = 0;
	if (staged_change_count)
		*staged_change_count = 0;
	count = rh_cluster_bitmap_next_batch_count(census, wal_capacity);
	if (!overlay || !census || !census->complete || !count ||
			!first_operation_ordinal || !staged_change_count) {
		errno = EINVAL;
		return -1;
	}
	writes = calloc(count, sizeof(*writes));
	if (!writes)
		return -1;
	for (i = 0; i < count; i++) {
		unsigned char set_mask = (unsigned char)~census->changes[i].before &
			census->changes[i].after;
		unsigned char clear_mask = census->changes[i].before &
			(unsigned char)~census->changes[i].after;

		writes[i].offset = census->changes[i].physical_offset;
		writes[i].length = 1;
		writes[i].target.seal_version = 1;
		writes[i].target.object = RH_WRITE_TARGET_NONRESIDENT_ATTRIBUTE;
		writes[i].target.owner_mft_record = FILE_Bitmap;
		writes[i].target.owner_sequence = census->bitmap_sequence;
		writes[i].target.attribute_instance =
			census->bitmap_attribute_instance;
		writes[i].target.attribute_type = 0x80;
		if (census->changes[i].set_mask != set_mask ||
				census->changes[i].clear_mask != clear_mask ||
				!!set_mask == !!clear_mask ||
				(set_mask && (set_mask & (unsigned char)(set_mask - 1U))) ||
				(clear_mask && (clear_mask &
				 (unsigned char)(clear_mask - 1U)))) {
			errno = EINVAL;
			goto out;
		}
		writes[i].target.flags = RH_WRITE_TARGET_NONRESIDENT |
			(set_mask ? RH_WRITE_TARGET_SET_ONLY :
			 RH_WRITE_TARGET_CLEAR_ONLY);
		rh_sha256("", 0, writes[i].target.attribute_name_hash);
		writes[i].target.lowest_vcn = 0;
		writes[i].target.logical_vcn =
			(int64_t)census->changes[i].logical_vcn;
		writes[i].target.logical_offset =
			census->changes[i].logical_offset;
		writes[i].target.logical_length = 1;
		writes[i].target.semantic_target_offset = writes[i].offset;
		writes[i].target.semantic_target_length = 1;
		writes[i].target.lcn = (int64_t)census->changes[i].lcn;
	}
	checkpoint = rh_writer_plan_checkpoint(overlay->writer);
	expectation.kind = RH_WRITE_BITMAP_CLUSTER;
	expectation.writes = writes;
	expectation.write_count = count;
	context.census = census;
	context.first = 0;
	context.count = count;
	if (rh_ntfs_overlay_run_action(overlay, &expectation,
			rh_bitmap_stage_action, &context))
		goto out;
	if (overlay->writer->operation_count != checkpoint + count)
		goto out;
	*first_operation_ordinal = checkpoint + 1U;
	*staged_change_count = count;
	result = 0;
out:
	free(writes);
	return result;
}

int rh_cluster_bitmap_stage(struct rh_ntfs_overlay *overlay,
		const struct rh_cluster_bitmap_census *census,
		size_t *first_operation_ordinal)
{
	size_t staged = 0;

	if (!census) {
		errno = EINVAL;
		return -1;
	}
	if (census->change_count > RH_BITMAP_MAX_CHANGES) {
		errno = E2BIG;
		return -1;
	}
	if (rh_cluster_bitmap_stage_prefix(overlay, census,
			RH_BITMAP_MAX_CHANGES, &staged, first_operation_ordinal))
		return -1;
	if (staged != census->change_count) {
		errno = EIO;
		return -1;
	}
	return 0;
}
