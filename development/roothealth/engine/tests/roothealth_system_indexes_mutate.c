#include "config.h"

#include <errno.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include "attrib.h"
#include "device.h"
#include "dir.h"
#include "inode.h"
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

static int parse(const char *text, uint64_t maximum, uint64_t *value)
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
	ntfschar name[2];
	ntfs_volume *volume = NULL;
	ntfs_inode *inode = NULL;
	ntfs_attr *attribute = NULL;
	unsigned char *bytes = NULL;
	uint64_t record, offset, expected, replacement;
	int result = 1;

	if (argc != 8 || parse(argv[2], 26U, &record) ||
		strlen(argv[3]) != 1U ||
		parse(argv[4], UINT64_MAX, &offset) ||
		parse(argv[5], UINT8_MAX, &expected) ||
		parse(argv[6], UINT8_MAX, &replacement) || strcmp(argv[7], "apply"))
		return 64;
	name[0] = cpu_to_le16((uint16_t)'$');
	name[1] = cpu_to_le16((uint16_t)argv[3][0]);
	volume = ntfs_mount(argv[1], NTFS_MNT_FORENSIC | NTFS_MNT_FS_NO_REPAIR);
	if (!volume || NDevReadOnly(volume->dev) ||
		ntfs_device_roothealth_install_plan_write(volume->dev,
			fixture_pwrite, NULL))
		goto out;
	inode = ntfs_inode_open(volume, record);
	if (!inode)
		goto out;
	attribute = ntfs_attr_open(inode, AT_INDEX_ROOT, name, 2U);
	if (!attribute || attribute->data_size <= 0 ||
		(uint64_t)attribute->data_size > SIZE_MAX ||
		offset >= (uint64_t)attribute->data_size)
		goto out;
	bytes = malloc((size_t)attribute->data_size);
	if (!bytes || ntfs_attr_pread(attribute, 0, attribute->data_size, bytes) !=
			attribute->data_size || bytes[offset] != expected)
		goto out;
	bytes[offset] = (unsigned char)replacement;
	if (ntfs_attr_pwrite(attribute, 0, attribute->data_size, bytes) !=
			attribute->data_size || ntfs_inode_sync(inode) ||
		!volume->dev->d_ops || !volume->dev->d_ops->sync ||
		volume->dev->d_ops->sync(volume->dev))
		goto out;
	result = 0;
out:
	free(bytes);
	if (attribute)
		ntfs_attr_close(attribute);
	if (inode)
		ntfs_inode_close(inode);
	if (volume)
		ntfs_device_roothealth_remove_plan_write(volume->dev);
	if (volume && ntfs_umount(volume, FALSE) && !result)
		result = 1;
	return result;
}
