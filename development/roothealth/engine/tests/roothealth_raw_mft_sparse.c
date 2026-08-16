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

static int open_scan(const char *path, struct rh_writer *writer,
		ntfs_volume **volume, struct rh_raw_mft_census *census)
{
	if (rh_writer_open(writer, path))
		return -1;
	*volume = ntfs_mount(path, NTFS_MNT_RDONLY | NTFS_MNT_FORENSIC |
		NTFS_MNT_FS_NO_REPAIR);
	if (!*volume || !NDevReadOnly((*volume)->dev) ||
			rh_raw_mft_census_run(*volume, writer, 1, census))
		return -1;
	return 0;
}

static void close_scan(struct rh_writer *writer, ntfs_volume *volume,
		struct rh_raw_mft_census *census)
{
	rh_raw_mft_census_release(census);
	if (volume)
		ntfs_umount(volume, FALSE);
	rh_writer_close(writer);
}

int main(int argc, char **argv)
{
	struct rh_raw_mft_census census;
	struct rh_writer writer;
	ntfs_volume *volume = NULL;
	const struct rh_raw_attribute *sparse = NULL;
	const struct rh_raw_run *first, *hole;
	unsigned char clean_hash[32];
	size_t i;

	if (argc != 5)
		return 5;
	if (open_scan(argv[1], &writer, &volume, &census))
		return 1;
	for (i = 0; i < census.attribute_count; i++) {
		const struct rh_raw_attribute *candidate = &census.attributes[i];

		if (candidate->owner.record == 64U &&
				candidate->type == le32_to_cpu(AT_DATA) &&
				!candidate->name_length) {
			if (sparse) {
				close_scan(&writer, volume, &census);
				return 1;
			}
			sparse = candidate;
		}
	}
	if (!sparse || !census.records_complete ||
			!census.attribute_lists_complete || !census.extents_complete ||
			sparse->flags != le16_to_cpu(ATTR_IS_SPARSE) ||
			sparse->compression_unit != STANDARD_COMPRESSION_UNIT ||
			sparse->lowest_vcn != 0 || sparse->highest_vcn != 31 ||
			sparse->allocated_size != 131072 || sparse->data_size != 131072 ||
			sparse->initialized_size != 8192 || sparse->compressed_size != 8192 ||
			sparse->run_count != 2U || writer.write_boundaries) {
		close_scan(&writer, volume, &census);
		return 1;
	}
	first = &census.runs[sparse->run_first];
	hole = first + 1;
	if (first->vcn != 0 || first->lcn != 8704 || first->length != 2U ||
			first->sparse || hole->vcn != 2 || hole->lcn != -1 ||
			hole->length != 30U || !hole->sparse) {
		close_scan(&writer, volume, &census);
		return 1;
	}
	memcpy(clean_hash, census.census_hash, sizeof(clean_hash));
	close_scan(&writer, volume, &census);
	volume = NULL;
	if (open_scan(argv[2], &writer, &volume, &census))
		return 1;
	if (!census.records_complete || !census.attribute_lists_complete ||
			!census.extents_complete || census.layout_candidate_count ||
			!memcmp(clean_hash, census.census_hash, sizeof(clean_hash)) ||
			writer.write_boundaries) {
		close_scan(&writer, volume, &census);
		return 1;
	}
	close_scan(&writer, volume, &census);
	volume = NULL;
	if (open_scan(argv[3], &writer, &volume, &census))
		return 1;
	if (!census.records_complete || !census.attribute_lists_complete ||
			census.extents_complete || writer.write_boundaries) {
		close_scan(&writer, volume, &census);
		return 1;
	}
	close_scan(&writer, volume, &census);
	volume = NULL;
	if (open_scan(argv[4], &writer, &volume, &census))
		return 1;
	if (census.records_bounded || census.records_complete ||
			!census.invalid_records || writer.write_boundaries) {
		close_scan(&writer, volume, &census);
		return 1;
	}
	close_scan(&writer, volume, &census);
	printf("raw-sparse flags=0x8000 unit=4 physical_clusters=2 "
		"hole_clusters=30 opaque_tail=clean-and-bound "
		"wrong_unit=refused unflagged_hole=refused writes=0\n");
	return 0;
}
