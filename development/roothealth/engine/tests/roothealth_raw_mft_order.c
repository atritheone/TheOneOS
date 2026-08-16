#include "config.h"

#include <stdint.h>
#include <stdio.h>

#include "device.h"
#include "roothealth_raw_mft.h"
#include "roothealth_write.h"
#include "volume.h"

static int scan(const char *path, int expect_list_complete,
		uint64_t expected_links)
{
	struct rh_raw_mft_census census;
	struct rh_writer writer;
	ntfs_volume *volume = NULL;
	int result = -1;

	if (rh_writer_open(&writer, path))
		return -1;
	volume = ntfs_mount(path, NTFS_MNT_RDONLY | NTFS_MNT_FORENSIC |
		NTFS_MNT_FS_NO_REPAIR);
	if (!volume || !NDevReadOnly(volume->dev) ||
			rh_raw_mft_census_run(volume, &writer, 1, &census))
		goto out;
	if (!census.records_complete || !census.records_bounded ||
			!census.layout_complete ||
			census.attribute_lists_complete != expect_list_complete ||
			census.extents_complete != expect_list_complete ||
			census.file_name_links != expected_links || writer.write_boundaries)
		goto release;
	result = 0;
release:
	rh_raw_mft_census_release(&census);
out:
	if (volume && ntfs_umount(volume, FALSE) && !result)
		result = -1;
	rh_writer_close(&writer);
	return result;
}

int main(int argc, char **argv)
{
	if (argc != 5)
		return 5;
	if (scan(argv[1], 1, 18) || scan(argv[2], 0, 17) ||
			scan(argv[3], 0, 16) || scan(argv[4], 0, 16))
		return 1;
	printf("raw-order same-basename-hardlinks=accepted "
		"reversed-equal-key-ale=refused wrong-instance=refused "
		"duplicate-instance=refused writes=0\n");
	return 0;
}
