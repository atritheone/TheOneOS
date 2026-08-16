#include "config.h"

#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

#include "endians.h"
#include "layout.h"
#include "roothealth_dirty.h"
#include "roothealth_overlay.h"

static int rotate_mirror_usn(const char *path)
{
	NTFS_BOOT_SECTOR boot;
	unsigned char record[1024];
	MFT_RECORD *mft = (MFT_RECORD *)record;
	uint64_t offset;
	uint16_t usa_offset, usa_count, usn;
	int fd;

	fd = open(path, O_RDWR | O_CLOEXEC);
	if (fd < 0)
		return -1;
	if (pread(fd, &boot, sizeof(boot), 0) != sizeof(boot) ||
			le16_to_cpu(boot.bpb.bytes_per_sector) != 512U ||
			boot.bpb.sectors_per_cluster != 8U ||
			sle64_to_cpu(boot.mftmirr_lcn) < 0) {
		close(fd);
		return -1;
	}
	offset = ((uint64_t)sle64_to_cpu(boot.mftmirr_lcn) << 12) +
		((uint64_t)FILE_Volume << 10);
	if (pread(fd, record, sizeof(record), (off_t)offset) != sizeof(record) ||
			mft->magic != magic_FILE) {
		close(fd);
		return -1;
	}
	usa_offset = le16_to_cpu(mft->usa_ofs);
	usa_count = le16_to_cpu(mft->usa_count);
	if (usa_count != 3U || usa_offset > sizeof(record) - 6U) {
		close(fd);
		return -1;
	}
	memcpy(&usn, record + usa_offset, sizeof(usn));
	usn = (uint16_t)(le16_to_cpu(usn) + 1U);
	if (!usn)
		usn = 1U;
	usn = cpu_to_le16(usn);
	memcpy(record + usa_offset, &usn, sizeof(usn));
	memcpy(record + 510, &usn, sizeof(usn));
	memcpy(record + 1022, &usn, sizeof(usn));
	if (pwrite(fd, record, sizeof(record), (off_t)offset) != sizeof(record) ||
			fsync(fd) || close(fd))
		return -1;
	return 0;
}

int main(int argc, char **argv)
{
	struct rh_writer writer;
	struct rh_ntfs_overlay overlay;
	struct rh_volume_dirty_pair pair;
	int expected, result = 1;

	if (argc != 2)
		return 5;
	if (rotate_mirror_usn(argv[1]))
		return 3;
	if (rh_writer_open(&writer, argv[1]))
		return 3;
	if (rh_ntfs_overlay_mount(&overlay, &writer, 0))
		goto out_writer;
	expected = !!(le16_to_cpu(overlay.volume->flags) &
		le16_to_cpu(VOLUME_IS_DIRTY));
	if (rh_volume_dirty_inspect(overlay.volume, &writer, expected, &pair) ||
			pair.initially_dirty != expected || writer.operation_count ||
			writer.write_boundaries)
		goto out_overlay;
	printf("dirty-pair usa_only_difference=accepted canonical_non_usa_equal=1 "
		"source_writes=fixture-only planned_writes=0\n");
	result = 0;
out_overlay:
	rh_ntfs_overlay_unmount(&overlay);
out_writer:
	rh_writer_close(&writer);
	return result;
}
