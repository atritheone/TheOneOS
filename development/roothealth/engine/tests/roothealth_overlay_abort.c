#include <stdio.h>
#include <string.h>

#include "attrib.h"
#include "inode.h"
#include "layout.h"
#include "roothealth_overlay.h"

struct abort_context {
	unsigned char value;
	int refuse_after_write;
	le16 cached_flags;
};

static void initialize_target(struct rh_overlay_expected_write *write,
		const ntfs_inode *inode, const runlist_element *run,
		unsigned char before, unsigned char after)
{
	unsigned char delta = before ^ after;

	memset(&write->target, 0, sizeof(write->target));
	write->target.seal_version = 1;
	write->target.object = RH_WRITE_TARGET_NONRESIDENT_ATTRIBUTE;
	write->target.owner_mft_record = FILE_Bitmap;
	write->target.owner_sequence = le16_to_cpu(inode->mrec->sequence_number);
	write->target.attribute_type = AT_DATA;
	write->target.flags = RH_WRITE_TARGET_NONRESIDENT |
		((after & delta) ? RH_WRITE_TARGET_SET_ONLY :
		 RH_WRITE_TARGET_CLEAR_ONLY);
	rh_sha256("", 0, write->target.attribute_name_hash);
	write->target.lowest_vcn = 0;
	write->target.logical_vcn = 0;
	write->target.lcn = run->lcn;
	write->target.logical_length = 1;
	write->target.semantic_target_offset = write->offset;
	write->target.semantic_target_length = 1;
}

static int write_then_decide(ntfs_volume *volume __attribute__((unused)),
		void *opaque)
{
	struct abort_context *context = opaque;
	ntfs_inode *inode;
	ntfs_attr *attribute;
	int result = RH_OVERLAY_ACTION_ERROR;

	/* Deliberately poison a libntfs-only cache field before the decision. */
	volume->flags = cpu_to_le16(le16_to_cpu(context->cached_flags) ^ 0x4000U);
	inode = ntfs_inode_open(volume, FILE_Bitmap);
	if (!inode)
		return result;
	attribute = ntfs_attr_open(inode, AT_DATA, AT_UNNAMED, 0);
	if (attribute && ntfs_attr_pwrite(attribute, 0, 1,
			&context->value) == 1)
		result = context->refuse_after_write ? RH_OVERLAY_ACTION_REFUSED :
			RH_OVERLAY_ACTION_OK;
	if (attribute)
		ntfs_attr_close(attribute);
	ntfs_inode_close(inode);
	return result;
}

int main(int argc, char **argv)
{
	struct rh_writer writer;
	struct rh_ntfs_overlay overlay;
	ntfs_inode *inode = NULL;
	ntfs_attr *attribute = NULL;
	runlist_element *run;
	struct rh_overlay_expected_write write;
	struct rh_overlay_action_expectation expectation;
	struct abort_context context;
	unsigned char original, observed;
	le16 original_volume_flags;
	int result = 1;

	if (argc != 2)
		return 5;
	if (rh_writer_open(&writer, argv[1]))
		return 3;
	if (rh_ntfs_overlay_mount(&overlay, &writer, 0))
		goto out_writer;
	inode = ntfs_inode_open(overlay.volume, FILE_Bitmap);
	if (!inode)
		goto out_overlay;
	attribute = ntfs_attr_open(inode, AT_DATA, AT_UNNAMED, 0);
	if (!attribute || ntfs_attr_pread(attribute, 0, 1, &original) != 1)
		goto out_inode;
	original_volume_flags = overlay.volume->flags;
	run = ntfs_attr_find_vcn(attribute, 0);
	if (!run || run->lcn < 0)
		goto out_inode;
	write.offset = (uint64_t)run->lcn << overlay.volume->cluster_size_bits;
	write.length = 1;
	context.value = original ^ 0x40;
	initialize_target(&write, inode, run, original, context.value);
	expectation.kind = RH_WRITE_BITMAP_CLUSTER;
	expectation.writes = &write;
	expectation.write_count = 1;
	context.refuse_after_write = 1;
	context.cached_flags = original_volume_flags;
	ntfs_attr_close(attribute);
	ntfs_inode_close(inode);
	attribute = NULL;
	inode = NULL;
	if (rh_ntfs_overlay_run_action(&overlay, &expectation,
			write_then_decide, &context) != RH_OVERLAY_ACTION_REFUSED ||
		writer.operation_count || writer.planned_bytes ||
		!NVolReadOnly(overlay.volume) || rh_ntfs_overlay_failed(&overlay) ||
		overlay.volume->flags != original_volume_flags)
		goto out_inode;
	inode = ntfs_inode_open(overlay.volume, FILE_Bitmap);
	if (!inode)
		goto out_overlay;
	attribute = ntfs_attr_open(inode, AT_DATA, AT_UNNAMED, 0);
	if (!attribute || ntfs_attr_pread(attribute, 0, 1, &observed) != 1 ||
		observed != original)
		goto out_inode;
	ntfs_attr_close(attribute);
	ntfs_inode_close(inode);
	attribute = NULL;
	inode = NULL;
	context.refuse_after_write = 0;
	if (rh_ntfs_overlay_run_action(&overlay, &expectation,
			write_then_decide, &context) != RH_OVERLAY_ACTION_OK ||
		writer.operation_count != 1 || writer.planned_bytes != 1 ||
		!NVolReadOnly(overlay.volume) ||
		overlay.volume->flags != original_volume_flags)
		goto out_inode;
	printf("partial_discarded=1 later_action=1 readonly_restored=1 "
		"cache_remounted=2 operations=1\n");
	result = 0;

out_inode:
	if (attribute)
		ntfs_attr_close(attribute);
	if (inode)
		ntfs_inode_close(inode);
out_overlay:
	rh_ntfs_overlay_unmount(&overlay);
out_writer:
	rh_writer_close(&writer);
	return result;
}
