#include "config.h"

#include <errno.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

#include "device.h"
#include "dir.h"
#include "endians.h"
#include "inode.h"
#include "object_id.h"
#include "reparse.h"
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

static ntfs_inode *create_file(ntfs_inode *root, const char *ascii)
{
	ntfschar *name = NULL;
	ntfs_inode *inode;
	int length = ntfs_mbstoucs(ascii, &name);

	if (length <= 0 || length > 255)
		return NULL;
	inode = ntfs_create(root, const_cpu_to_le32(0), name, (uint8_t)length,
		S_IFREG);
	free(name);
	return inode;
}

int main(int argc, char **argv)
{
	ntfs_volume *volume = NULL;
	ntfs_inode *root = NULL, *objid = NULL, *reparse = NULL;
	unsigned char object_id[64];
	unsigned char reparse_data[22];
	int result = 1;
	unsigned int i;

	if (argc != 2)
		return 64;
	volume = ntfs_mount(argv[1], NTFS_MNT_FORENSIC | NTFS_MNT_FS_NO_REPAIR);
	if (!volume || NDevReadOnly(volume->dev) ||
		ntfs_device_roothealth_install_plan_write(volume->dev,
			fixture_pwrite, NULL))
		goto out;
	root = ntfs_inode_open(volume, FILE_root);
	if (!root)
		goto out;
	objid = create_file(root, "objid");
	reparse = create_file(root, "reparse");
	if (!objid || !reparse)
		goto out;
	for (i = 0; i < sizeof(object_id); i++)
		object_id[i] = (unsigned char)(0x31U + i);
	memset(object_id + 48U, 0, 16U);
	if (ntfs_set_ntfs_object_id(objid, (const char *)object_id,
			sizeof(object_id), 0))
		goto out;
	memset(reparse_data, 0, sizeof(reparse_data));
	reparse_data[0] = 0x0c;
	reparse_data[3] = 0xa0;
	reparse_data[4] = 14U;
	reparse_data[10] = 2U;
	reparse_data[14] = 2U;
	reparse_data[20] = 'x';
	if (ntfs_set_ntfs_reparse_data(reparse,
			(const char *)reparse_data, sizeof(reparse_data), 0))
		goto out;
	if (ntfs_inode_sync_in_dir(objid, root) ||
		ntfs_inode_sync_in_dir(reparse, root))
		goto out;
	if (ntfs_inode_close(objid))
		goto out;
	objid = NULL;
	if (ntfs_inode_close(reparse))
		goto out;
	reparse = NULL;
	if (ntfs_inode_close(root))
		goto out;
	root = NULL;
	if (!volume->dev->d_ops || !volume->dev->d_ops->sync ||
		volume->dev->d_ops->sync(volume->dev))
		goto out;
	result = 0;
out:
	if (objid)
		ntfs_inode_close(objid);
	if (reparse)
		ntfs_inode_close(reparse);
	if (root)
		ntfs_inode_close(root);
	if (volume)
		ntfs_device_roothealth_remove_plan_write(volume->dev);
	if (volume && ntfs_umount(volume, FALSE) && !result)
		result = 1;
	return result;
}
