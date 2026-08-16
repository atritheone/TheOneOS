#include "config.h"

#include <errno.h>
#include <stdint.h>
#include <stdlib.h>

#include "device.h"
#include "dir.h"
#include "inode.h"
#include "unistr.h"
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

int main(int argc, char **argv)
{
	ntfs_volume *volume = NULL;
	ntfs_inode *inode = NULL, *directory = NULL;
	ntfschar *name = NULL;
	char *end = NULL;
	uint64_t record, parent = FILE_root;
	int name_length, result = 1;

	if (argc != 4 && argc != 5)
		return 5;
	errno = 0;
	record = strtoull(argv[2], &end, 0);
	if (errno || !end || *end || record > UINT64_C(0x0000ffffffffffff))
		return 5;
	if (argc == 5) {
		errno = 0;
		parent = strtoull(argv[4], &end, 0);
		if (errno || !end || *end ||
				parent > UINT64_C(0x0000ffffffffffff))
			return 5;
	}
	name_length = ntfs_mbstoucs(argv[3], &name);
	if (name_length <= 0 || name_length > 255)
		goto out;
	volume = ntfs_mount(argv[1], NTFS_MNT_FORENSIC | NTFS_MNT_FS_NO_REPAIR);
	if (!volume || NDevReadOnly(volume->dev) ||
			ntfs_device_roothealth_install_plan_write(volume->dev,
				fixture_pwrite, NULL))
		goto out;
	inode = ntfs_inode_open(volume, record);
	directory = ntfs_inode_open(volume, parent);
	if (!inode || !directory || ntfs_link(inode, directory, name,
			(uint8_t)name_length))
		goto out;
	if (ntfs_inode_close(inode))
		goto out;
	inode = NULL;
	if (ntfs_inode_close(directory))
		goto out;
	directory = NULL;
	if (!volume->dev->d_ops || !volume->dev->d_ops->sync ||
			volume->dev->d_ops->sync(volume->dev))
		goto out;
	result = 0;
out:
	if (inode)
		ntfs_inode_close(inode);
	if (directory)
		ntfs_inode_close(directory);
	if (volume)
		ntfs_device_roothealth_remove_plan_write(volume->dev);
	if (volume && ntfs_umount(volume, FALSE) && !result)
		result = 1;
	free(name);
	return result;
}
