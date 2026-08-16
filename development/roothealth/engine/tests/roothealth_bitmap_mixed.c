#include "config.h"

#include <errno.h>
#include <stdio.h>
#include <string.h>

#include "roothealth_bitmap.h"
#include "roothealth_mft_bitmap.h"

static int exact_pair(const struct rh_writer *writer, enum rh_write_kind kind,
		uint64_t offset, unsigned char first_before,
		unsigned char first_after, unsigned char second_after)
{
	return writer->operation_count == 2 && !writer->write_boundaries &&
		writer->operations[0].kind == kind &&
		writer->operations[1].kind == kind &&
		writer->operations[0].offset == offset &&
		writer->operations[1].offset == offset &&
		writer->operations[0].length == 1 &&
		writer->operations[1].length == 1 &&
		writer->operations[0].before[0] == first_before &&
		writer->operations[0].after[0] == first_after &&
		writer->operations[1].before[0] == first_after &&
		writer->operations[1].after[0] == second_after &&
		writer->operations[0].target.flags ==
			(RH_WRITE_TARGET_NONRESIDENT | RH_WRITE_TARGET_SET_ONLY) &&
		writer->operations[1].target.flags ==
			(RH_WRITE_TARGET_NONRESIDENT | RH_WRITE_TARGET_CLEAR_ONLY);
}

static int run_mft(struct rh_writer *writer, struct rh_ntfs_overlay *overlay)
{
	struct rh_mft_bitmap_census initial, final;
	size_t first = 0;
	int result = -1;

	memset(&initial, 0, sizeof(initial));
	memset(&final, 0, sizeof(final));
	if (rh_mft_bitmap_census_run(overlay->volume, writer, 1, 81, 1,
			&initial) || !initial.complete || initial.change_count != 2 ||
			initial.changes[0].physical_offset != 8202 ||
			initial.changes[1].physical_offset != 8202 ||
			initial.changes[0].before != 5 || initial.changes[0].after != 7 ||
			initial.changes[0].set_mask != 2 ||
			initial.changes[0].clear_mask ||
			initial.changes[1].before != 7 || initial.changes[1].after != 3 ||
			initial.changes[1].set_mask ||
			initial.changes[1].clear_mask != 4 ||
			rh_mft_bitmap_stage(overlay, &initial, &first) || first != 1 ||
			!exact_pair(writer, RH_WRITE_BITMAP_MFT, 8202, 5, 7, 3))
		goto out;
	rh_ntfs_overlay_unmount(overlay);
	if (rh_ntfs_overlay_mount(overlay, writer, 0) ||
			rh_mft_bitmap_census_run(overlay->volume, writer, 2, 81, 1,
				&final) || !final.clean || final.change_count)
		goto out;
	printf("mft-bitmap-mixed operations=2 action=22 offset=8202 "
		"set=02 clear=04 chain=05:07:03 flags=40,72 source_writes=0 "
		"final_clean=1 policy_clear_gate=closed\n");
	result = 0;
out:
	if (result)
		fprintf(stderr, "mft mixed failed: %s changes=%zu operations=%zu\n",
			strerror(errno), initial.change_count, writer->operation_count);
	rh_mft_bitmap_census_destroy(&final);
	rh_mft_bitmap_census_destroy(&initial);
	return result;
}

static int run_cluster(struct rh_writer *writer,
		struct rh_ntfs_overlay *overlay)
{
	struct rh_cluster_bitmap_census initial, final;
	size_t first = 0;
	int result = -1;

	memset(&initial, 0, sizeof(initial));
	memset(&final, 0, sizeof(final));
	if (rh_cluster_bitmap_census_run(overlay->volume, writer, 1, &initial) ||
			!initial.complete || initial.change_count != 2 ||
			initial.changes[0].physical_offset != 67137536 ||
			initial.changes[1].physical_offset != 67137536 ||
			initial.changes[0].before != 0xfe ||
			initial.changes[0].after != 0xff ||
			initial.changes[0].set_mask != 1 ||
			initial.changes[0].clear_mask ||
			initial.changes[1].before != 0xff ||
			initial.changes[1].after != 0xf7 ||
			initial.changes[1].set_mask ||
			initial.changes[1].clear_mask != 8 ||
			rh_cluster_bitmap_stage(overlay, &initial, &first) || first != 1 ||
			!exact_pair(writer, RH_WRITE_BITMAP_CLUSTER, 67137536,
				0xfe, 0xff, 0xf7))
		goto out;
	rh_ntfs_overlay_unmount(overlay);
	if (rh_ntfs_overlay_mount(overlay, writer, 0) ||
			rh_cluster_bitmap_census_run(overlay->volume, writer, 2, &final) ||
			!final.clean || final.change_count)
		goto out;
	printf("cluster-bitmap-mixed operations=2 action=23 offset=67137536 "
		"set=01 clear=08 chain=fe:ff:f7 flags=40,72 source_writes=0 "
		"final_clean=1 policy_clear_gate=closed\n");
	result = 0;
out:
	if (result)
		fprintf(stderr, "cluster mixed failed: %s changes=%zu operations=%zu\n",
			strerror(errno), initial.change_count, writer->operation_count);
	rh_cluster_bitmap_census_destroy(&final);
	rh_cluster_bitmap_census_destroy(&initial);
	return result;
}

int main(int argc, char **argv)
{
	struct rh_writer writer;
	struct rh_ntfs_overlay overlay;
	int result;

	if (argc != 3 || (strcmp(argv[2], "mft") &&
			strcmp(argv[2], "cluster")))
		return 5;
	if (rh_writer_open(&writer, argv[1]))
		return 3;
	if (rh_ntfs_overlay_mount(&overlay, &writer, 0)) {
		rh_writer_close(&writer);
		return 3;
	}
	result = !strcmp(argv[2], "mft") ? run_mft(&writer, &overlay) :
		run_cluster(&writer, &overlay);
	rh_ntfs_overlay_unmount(&overlay);
	rh_writer_close(&writer);
	return result ? 1 : 0;
}
