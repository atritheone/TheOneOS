#include "config.h"

#include <errno.h>
#include <stdio.h>
#include <string.h>

#include "roothealth_bitmap.h"

int main(int argc, char **argv)
{
	struct rh_writer writer;
	struct rh_ntfs_overlay overlay;
	struct rh_cluster_bitmap_census census;
	int result = 1;

	if (argc != 2)
		return 5;
	if (rh_writer_open(&writer, argv[1]))
		return 3;
	if (rh_ntfs_overlay_mount(&overlay, &writer, 0))
		goto out_writer;
	if (rh_cluster_bitmap_census_run(overlay.volume, &writer, 1, &census)) {
		fprintf(stderr, "census failed: %s; mft=%llu live=%llu free=%llu "
			"attrs=%llu extents=%llu runs=%llu owned=%llu duplicates=%llu\n",
			strerror(errno),
			(unsigned long long)census.mft_slots_completed,
			(unsigned long long)census.mft_slots_in_use,
			(unsigned long long)census.mft_slots_free,
			(unsigned long long)census.attributes_examined,
			(unsigned long long)census.nonresident_extents_examined,
			(unsigned long long)census.runs_examined,
			(unsigned long long)census.clusters_owned,
			(unsigned long long)census.duplicate_clusters);
		goto out_overlay;
	}
	if (!census.complete || !census.structurally_valid ||
			!census.ownership_exact || !census.clean || census.change_count ||
			census.mft_slots_completed != census.mft_slots_expected ||
			census.mft_slots_in_use + census.mft_slots_free !=
				census.mft_slots_expected || census.unreadable_slots) {
		fprintf(stderr, "census not clean: complete=%d structural=%d ownership=%d "
			"clean=%d changes=%zu mft=%llu/%llu live=%llu free=%llu "
			"unreadable=%llu duplicates=%llu\n", census.complete,
			census.structurally_valid, census.ownership_exact, census.clean,
			census.change_count,
			(unsigned long long)census.mft_slots_completed,
			(unsigned long long)census.mft_slots_expected,
			(unsigned long long)census.mft_slots_in_use,
			(unsigned long long)census.mft_slots_free,
			(unsigned long long)census.unreadable_slots,
			(unsigned long long)census.duplicate_clusters);
		if (census.change_count)
			fprintf(stderr, "first change logical=%llu physical=%llu "
				"before=%02x after=%02x\n",
				(unsigned long long)census.changes[0].logical_offset,
				(unsigned long long)census.changes[0].physical_offset,
				census.changes[0].before, census.changes[0].after);
		goto out_census;
	}
	printf("bitmap-clean clusters=%llu bits=%llu mft=%llu live=%llu free=%llu "
		"attrs=%llu extents=%llu runs=%llu owned=%llu changes=%zu\n",
		(unsigned long long)census.cluster_count,
		(unsigned long long)census.bitmap_bits_examined,
		(unsigned long long)census.mft_slots_completed,
		(unsigned long long)census.mft_slots_in_use,
		(unsigned long long)census.mft_slots_free,
		(unsigned long long)census.attributes_examined,
		(unsigned long long)census.nonresident_extents_examined,
		(unsigned long long)census.runs_examined,
		(unsigned long long)census.clusters_owned, census.change_count);
	result = 0;
out_census:
	rh_cluster_bitmap_census_destroy(&census);
out_overlay:
	rh_ntfs_overlay_unmount(&overlay);
out_writer:
	rh_writer_close(&writer);
	return result;
}
