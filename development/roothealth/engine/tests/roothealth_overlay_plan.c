#include <errno.h>
#include <stdio.h>
#include <string.h>

#include "attrib.h"
#include "inode.h"
#include "layout.h"
#include "roothealth_overlay.h"

struct plan_context {
	unsigned char after;
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

static int plan_bitmap_byte(ntfs_volume *volume, void *opaque)
{
	struct plan_context *context = opaque;
	ntfs_inode *inode;
	ntfs_attr *attribute;
	int result = -1;

	inode = ntfs_inode_open(volume, FILE_Bitmap);
	if (!inode)
		return result;
	attribute = ntfs_attr_open(inode, AT_DATA, AT_UNNAMED, 0);
	if (attribute && ntfs_attr_pwrite(attribute, 0, 1,
			&context->after) == 1)
		result = 0;
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
	struct plan_context context;
	struct rh_overlay_expected_write write;
	struct rh_overlay_action_expectation expectation;
	unsigned char before, after, observed;
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
	if (!attribute || ntfs_attr_pread(attribute, 0, 1, &before) != 1)
		goto out_inode;
	after = before ^ 0x80;
	run = ntfs_attr_find_vcn(attribute, 0);
	if (!run || run->lcn < 0)
		goto out_inode;
	write.offset = (uint64_t)run->lcn << overlay.volume->cluster_size_bits;
	write.length = 1;
	initialize_target(&write, inode, run, before, after);
	context.after = after;
	expectation.kind = RH_WRITE_BITMAP_CLUSTER;
	expectation.writes = &write;
	expectation.write_count = 1;
	ntfs_attr_close(attribute);
	ntfs_inode_close(inode);
	attribute = NULL;
	inode = NULL;
	if (rh_ntfs_overlay_run_action(&overlay, &expectation,
			plan_bitmap_byte, &context))
		goto out_inode;
	inode = ntfs_inode_open(overlay.volume, FILE_Bitmap);
	if (!inode)
		goto out_overlay;
	attribute = ntfs_attr_open(inode, AT_DATA, AT_UNNAMED, 0);
	if (ntfs_attr_pread(attribute, 0, 1, &observed) != 1 ||
		observed != after || writer.operation_count != 1 ||
		writer.operations[0].kind != RH_WRITE_BITMAP_CLUSTER ||
		writer.operations[0].length != 1 ||
		writer.operations[0].before[0] != before ||
		writer.operations[0].after[0] != after)
		goto out_inode;
	errno = 0;
	if (overlay.device->d_ops->pwrite(overlay.device, &after, 1, 0) != -1 ||
		errno != EPERM)
		goto out_inode;
	printf("family=%s operations=%zu overlay_visible=1 direct_refused=1\n",
		rh_write_kind_name(writer.operations[0].kind),
		writer.operation_count);
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
