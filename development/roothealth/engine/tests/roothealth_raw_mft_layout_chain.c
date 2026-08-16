#include "config.h"

#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "device.h"
#include "endians.h"
#include "layout.h"
#include "roothealth_raw_mft.h"
#include "roothealth_write.h"
#include "volume.h"

int main(int argc, char **argv)
{
	struct rh_raw_mft_census census;
	struct rh_writer writer;
	ntfs_volume *volume = NULL;
	int result = 1;

	if (argc != 2)
		return 5;
	if (rh_writer_open(&writer, argv[1]))
		return 3;
	volume = ntfs_mount(argv[1], NTFS_MNT_RDONLY | NTFS_MNT_FORENSIC |
		NTFS_MNT_FS_NO_REPAIR);
	if (!volume || !NDevReadOnly(volume->dev) ||
			rh_raw_mft_census_run(volume, &writer, 1, &census))
		goto out;
	if (!census.records_bounded || census.records_complete ||
			census.layout_complete || !census.attribute_lists_complete ||
			!census.extents_complete || census.layout_candidate_count != 2U ||
			census.layout_candidates[0].reason !=
				RH_RAW_LAYOUT_RECORD_RESERVED ||
			census.layout_candidates[1].reason !=
				RH_RAW_LAYOUT_RESIDENT_HEADER_RESERVED ||
			census.layout_candidates[0].storage.record != FILE_MFT ||
			census.layout_candidates[1].storage.record != FILE_MFT ||
			census.layout_candidates[0].attribute_type != 0U ||
			census.layout_candidates[1].attribute_type !=
				le32_to_cpu(AT_STANDARD_INFORMATION) ||
			census.layout_candidates[0].logical_offset != 42U ||
			census.layout_candidates[1].logical_offset != 79U ||
			census.layout_candidates[0].length != 2U ||
			census.layout_candidates[1].length != 1U ||
			memcmp(census.layout_candidates[0].logical_record_after_hash,
				census.layout_candidates[1].logical_record_before_hash, 32) ||
			writer.write_boundaries)
		goto release;
	printf("raw-layout-chain record=0 candidates=2 offsets=42,79 "
		"chained=1 clean=0 writes=0\n");
	result = 0;
release:
	rh_raw_mft_census_release(&census);
out:
	if (volume && ntfs_umount(volume, FALSE) && !result)
		result = 1;
	rh_writer_close(&writer);
	return result;
}
