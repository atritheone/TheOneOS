#include "config.h"

#include <errno.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include "attrib.h"
#include "device.h"
#include "endians.h"
#include "inode.h"
#include "layout.h"
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
	ntfs_inode *inode = NULL;
	ntfs_attr *attribute = NULL;
	unsigned char *value = NULL, temporary[256];
	ATTR_LIST_ENTRY *previous = NULL;
	s64 position = 0;
	char *end = NULL;
	uint64_t record;
	int found = 0, result = 1;

	if (argc != 3 && argc != 4)
		return 5;
	errno = 0;
	record = strtoull(argv[2], &end, 0);
	if (errno || !end || *end || record > UINT64_C(0x0000ffffffffffff))
		return 5;
	volume = ntfs_mount(argv[1], NTFS_MNT_FORENSIC | NTFS_MNT_FS_NO_REPAIR);
	if (!volume || NDevReadOnly(volume->dev) ||
			ntfs_device_roothealth_install_plan_write(volume->dev,
				fixture_pwrite, NULL))
		goto out;
	inode = ntfs_inode_open(volume, record);
	if (!inode)
		goto out;
	attribute = ntfs_attr_open(inode, AT_ATTRIBUTE_LIST, AT_UNNAMED, 0);
	if (!attribute || attribute->data_size <= 0 ||
			attribute->data_size > 256 * 1024)
		goto out;
	value = malloc((size_t)attribute->data_size);
	if (!value || ntfs_attr_pread(attribute, 0, attribute->data_size, value) !=
			attribute->data_size)
		goto out;
	while (position + (s64)sizeof(ATTR_LIST_ENTRY) <= attribute->data_size) {
		ATTR_LIST_ENTRY *left = (ATTR_LIST_ENTRY *)(value + position);
		uint16_t left_length = le16_to_cpu(left->length);
		ATTR_LIST_ENTRY *right;
		uint16_t right_length;

		if (left_length < sizeof(*left) || (left_length & 7U) ||
				left_length > attribute->data_size - position)
			goto out;
		if (position + left_length + (s64)sizeof(*right) >
				attribute->data_size)
			break;
		right = (ATTR_LIST_ENTRY *)(value + position + left_length);
		right_length = le16_to_cpu(right->length);
		if (right_length < sizeof(*right) || (right_length & 7U) ||
				right_length > attribute->data_size - position - left_length)
			goto out;
		if (argc == 4 && !strcmp(argv[3], "wrong-instance") &&
				MREF_LE(left->mft_reference) != record &&
				le16_to_cpu(left->instance) &&
				le16_to_cpu(left->instance) != UINT16_MAX) {
			left->instance = cpu_to_le16(le16_to_cpu(left->instance) + 1U);
			found = 1;
			break;
		}
		if (argc == 4 && !strcmp(argv[3], "duplicate-instance") && previous &&
				MREF_LE(previous->mft_reference) ==
					MREF_LE(left->mft_reference) &&
				previous->instance != left->instance) {
			left->instance = previous->instance;
			found = 1;
			break;
		}
		if (argc == 3 && left->type == AT_FILE_NAME &&
				right->type == AT_FILE_NAME &&
				left->name_length == right->name_length &&
				left->lowest_vcn == right->lowest_vcn &&
				left->instance == right->instance &&
				left_length == right_length && left_length <= sizeof(temporary)) {
			memcpy(temporary, left, left_length);
			memcpy(left, right, right_length);
			memcpy((unsigned char *)left + right_length, temporary,
				left_length);
			found = 1;
			break;
		}
		previous = left;
		position += left_length;
	}
	if (!found || ntfs_attr_pwrite(attribute, 0, attribute->data_size, value) !=
			attribute->data_size || !volume->dev->d_ops ||
			!volume->dev->d_ops->sync || volume->dev->d_ops->sync(volume->dev))
		goto out;
	result = 0;
out:
	free(value);
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
