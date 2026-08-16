#include "config.h"

#include <errno.h>
#include <stdint.h>
#include <stdlib.h>

#include "device.h"
#include "mft.h"
#include "volume.h"

static s64 fixture_pwrite(struct ntfs_device *device, const void *buffer,
		s64 count, s64 offset, void *opaque)
{
	(void)opaque;
	if (!device || !device->d_ops || !device->d_ops->pwrite) {
		errno = EIO;
		return -1;
	}
	return device->d_ops->pwrite(device, buffer, count, offset);
}

static int parse_u64(const char *text, uint64_t maximum, uint64_t *value)
{
	char *end = NULL;
	unsigned long long parsed;

	errno = 0;
	parsed = strtoull(text, &end, 0);
	if (errno || !end || *end || parsed > maximum)
		return -1;
	*value = parsed;
	return 0;
}

int main(int argc, char **argv)
{
	unsigned char record[1024];
	ntfs_volume *volume = NULL;
	uint64_t record_number, logical_offset, expected, replacement;
	int result = 1;

	if (argc != 6 || parse_u64(argv[2], UINT64_MAX, &record_number) ||
			parse_u64(argv[3], sizeof(record) - 1U, &logical_offset) ||
			parse_u64(argv[4], UINT8_MAX, &expected) ||
			parse_u64(argv[5], UINT8_MAX, &replacement))
		return 5;
	volume = ntfs_mount(argv[1], NTFS_MNT_FORENSIC | NTFS_MNT_FS_NO_REPAIR);
	if (!volume || NDevReadOnly(volume->dev) ||
			volume->mft_record_size != sizeof(record))
		goto out;
	if (ntfs_device_roothealth_install_plan_write(volume->dev,
			fixture_pwrite, NULL))
		goto out;
	if (ntfs_mft_record_read(volume, record_number, (MFT_RECORD *)record))
		goto out;
	if (record[logical_offset] != expected) {
		errno = EINVAL;
		goto out;
	}
	record[logical_offset] = (unsigned char)replacement;
	if (ntfs_mft_record_write(volume, record_number, (MFT_RECORD *)record) ||
			!volume->dev->d_ops || !volume->dev->d_ops->sync ||
			volume->dev->d_ops->sync(volume->dev))
		goto out;
	result = 0;
out:
	if (volume)
		ntfs_device_roothealth_remove_plan_write(volume->dev);
	if (volume && ntfs_umount(volume, FALSE) && !result)
		result = 1;
	return result;
}
