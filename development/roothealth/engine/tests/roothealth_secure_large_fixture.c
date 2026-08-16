#include "config.h"

#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "attrib.h"
#include "dir.h"
#include "device.h"
#include "endians.h"
#include "index.h"
#include "inode.h"
#include "layout.h"
#include "logging.h"
#include "volume.h"

#define FIXTURE_BLOCK UINT64_C(0x40000)
#define FIXTURE_PAIR UINT64_C(0x80000)
#define FIXTURE_HEADER ((size_t)offsetof(SDS_ENTRY, sid))
#define CURRENT_PROFILE_SDS_DATA INT64_C(268496)
#define CURRENT_PROFILE_SDS_ALLOCATED INT64_C(270336)

static int64_t fixture_write(struct ntfs_device *device, const void *buffer,
		int64_t count, int64_t offset, void *opaque)
{
	(void)opaque;
	return device && device->d_ops && device->d_ops->pwrite ?
		device->d_ops->pwrite(device, buffer, count, offset) : -1;
}

static int reset_index(ntfs_inode *inode, ntfschar *name)
{
	ntfs_attr *attribute;
	INDEX_ROOT *root;
	INDEX_ENTRY *end;
	int result = -1;

	attribute = ntfs_attr_open(inode, AT_INDEX_ALLOCATION, name, 4);
	if (attribute) {
		if (ntfs_attr_rm(attribute)) {
			ntfs_attr_close(attribute);
			return -1;
		}
		ntfs_attr_close(attribute);
	}
	attribute = ntfs_attr_open(inode, AT_BITMAP, name, 4);
	if (attribute) {
		if (ntfs_attr_rm(attribute)) {
			ntfs_attr_close(attribute);
			return -1;
		}
		ntfs_attr_close(attribute);
	}
	attribute = ntfs_attr_open(inode, AT_INDEX_ROOT, name, 4);
	if (!attribute)
		return -1;
	if (ntfs_attr_truncate(attribute,
			sizeof(INDEX_ROOT) + sizeof(INDEX_ENTRY_HEADER)))
		goto out;
	root = ntfs_ir_lookup2(inode, name, 4);
	if (!root)
		goto out;
	root->index.entries_offset = cpu_to_le32(sizeof(INDEX_HEADER));
	root->index.index_length = cpu_to_le32(sizeof(INDEX_HEADER) +
		sizeof(INDEX_ENTRY_HEADER));
	root->index.allocated_size = root->index.index_length;
	root->index.ih_flags = SMALL_INDEX;
	memset(root->index.reserved, 0, sizeof(root->index.reserved));
	end = (INDEX_ENTRY *)((unsigned char *)&root->index +
		sizeof(INDEX_HEADER));
	memset(end, 0, sizeof(INDEX_ENTRY_HEADER));
	end->length = cpu_to_le16(sizeof(INDEX_ENTRY_HEADER));
	end->ie_flags = INDEX_ENTRY_END;
	ntfs_inode_mark_dirty(inode);
	result = 0;
out:
	ntfs_attr_close(attribute);
	return result;
}

static int add_index_entry(ntfs_inode *inode, ntfschar *name, int sdh,
		const SDS_ENTRY *sds)
{
	unsigned char bytes[sizeof(INDEX_ENTRY)];
	INDEX_ENTRY *entry = (INDEX_ENTRY *)bytes;
	SECURITY_DESCRIPTOR_HEADER *data;
	ntfs_index_context *context;
	int result;

	memset(bytes, 0, sizeof(bytes));
	entry->data_offset = cpu_to_le16(sdh ? 0x18U : 0x14U);
	entry->data_length = cpu_to_le16(sizeof(*data));
	entry->length = cpu_to_le16(sdh ? 0x30U : 0x28U);
	entry->key_length = cpu_to_le16(sdh ? sizeof(SDH_INDEX_KEY) :
		sizeof(SII_INDEX_KEY));
	if (sdh) {
		entry->key.sdh.hash = sds->hash;
		entry->key.sdh.security_id = sds->security_id;
	} else
		entry->key.sii.security_id = sds->security_id;
	data = (SECURITY_DESCRIPTOR_HEADER *)(bytes +
		le16_to_cpu(entry->data_offset));
	data->hash = sds->hash;
	data->security_id = sds->security_id;
	data->offset = sds->offset;
	data->length = sds->length;
	if (sdh)
		((SDH_INDEX_DATA *)data)->reserved_II = cpu_to_le32(0x00490049U);
	context = ntfs_index_ctx_get(inode, name, 4);
	if (!context)
		return -1;
	result = ntfs_ie_add(context, entry);
	ntfs_index_ctx_put(context);
	return result;
}

static int force_nonresident_bitmap(ntfs_inode *inode, ntfschar *name)
{
	ntfs_attr *attribute;
	unsigned char bytes[4096];
	int64_t original;
	int result = -1;

	memset(bytes, 0, sizeof(bytes));
	attribute = ntfs_attr_open(inode, AT_BITMAP, name, 4);
	if (!attribute)
		return -1;
	original = attribute->data_size;
	if (original <= 0 || original > (int64_t)sizeof(bytes) ||
			ntfs_attr_pread(attribute, 0, original, bytes) != original ||
			ntfs_attr_truncate(attribute, sizeof(bytes)) ||
			ntfs_attr_pwrite(attribute, 0, sizeof(bytes), bytes) !=
				(int64_t)sizeof(bytes) || !NAttrNonResident(attribute))
		goto out;
	result = 0;
out:
	ntfs_attr_close(attribute);
	return result;
}

static int verify_current_profile_index(ntfs_inode *inode, ntfschar *name)
{
	ntfs_attr *allocation = NULL, *bitmap = NULL;
	int result = -1;

	allocation = ntfs_attr_open(inode, AT_INDEX_ALLOCATION, name, 4);
	bitmap = ntfs_attr_open(inode, AT_BITMAP, name, 4);
	if (!allocation || !bitmap || !NAttrNonResident(allocation) ||
			allocation->data_size != 4096 || NAttrNonResident(bitmap) ||
			bitmap->data_size != 8)
		goto out;
	result = 0;
out:
	if (bitmap)
		ntfs_attr_close(bitmap);
	if (allocation)
		ntfs_attr_close(allocation);
	return result;
}

int main(int argc, char **argv)
{
	ntfs_volume *volume = NULL;
	ntfs_inode *inode = NULL;
	ntfs_attr *sds = NULL;
	unsigned char *stream = NULL, *source = NULL;
	char *end = NULL;
	unsigned long count;
	uint32_t source_length;
	uint64_t entry_span, descriptors_per_block, pair_count, stream_length;
	int current_profile = 0;
	int result = 1;
	const char *phase = "arguments";

	if (argc != 3 && argc != 4)
		return 64;
	if (argc == 4 && strcmp(argv[3], "nonresident-bitmap") &&
			strcmp(argv[3], "current-profile"))
		return 64;
	current_profile = argc == 4 && !strcmp(argv[3], "current-profile");
	ntfs_log_set_handler(ntfs_log_handler_stderr);
	ntfs_log_set_levels(NTFS_LOG_LEVEL_ERROR | NTFS_LOG_LEVEL_PERROR |
		NTFS_LOG_LEVEL_WARNING | NTFS_LOG_LEVEL_DEBUG);
	errno = 0;
	count = strtoul(argv[2], &end, 10);
	if (errno || !end || *end || count < 3U || count > 20000U ||
			(current_profile && count != 30U))
		return 64;
	phase = "mount";
	volume = ntfs_mount(argv[1], 0);
	if (!volume)
		goto out;
	if (ntfs_device_roothealth_install_plan_write(volume->dev,
			fixture_write, NULL))
		goto out;
	phase = "inode";
	inode = ntfs_inode_open(volume, FILE_Secure);
	if (!inode)
		goto out;
	phase = "sds-open";
	sds = ntfs_attr_open(inode, AT_DATA, STREAM_SDS, 4);
	if (!sds)
		goto out;
	phase = "sds-read";
	source = malloc(4096);
	if (!source || ntfs_attr_pread(sds, 0, 4096, source) != 4096)
		goto out;
	source_length = le32_to_cpu(((SDS_ENTRY *)source)->length);
	if (source_length < FIXTURE_HEADER +
			sizeof(SECURITY_DESCRIPTOR_RELATIVE) || source_length > 4096U ||
			(source_length & 3U))
		goto out;
	entry_span = (source_length + 15U) & ~UINT64_C(15);
	descriptors_per_block = FIXTURE_BLOCK / entry_span;
	if (!descriptors_per_block || count > UINT64_MAX -
			(descriptors_per_block - 1U))
		goto out;
	pair_count = (count + descriptors_per_block - 1U) /
		descriptors_per_block;
	if (!pair_count || pair_count > UINT64_MAX / FIXTURE_PAIR)
		goto out;
	stream_length = pair_count * FIXTURE_PAIR;
	if (current_profile) {
		if (pair_count != 1U || count >
				(CURRENT_PROFILE_SDS_DATA - FIXTURE_BLOCK) / entry_span)
			goto out;
		stream_length = CURRENT_PROFILE_SDS_DATA;
	}
	stream = calloc(1, (size_t)stream_length);
	if (!stream)
		goto out;
	for (unsigned long i = 0; i < count; i++) {
		SDS_ENTRY *primary, *backup;
		uint64_t pair = i / descriptors_per_block;
		uint64_t slot = i % descriptors_per_block;
		uint64_t cursor = pair * FIXTURE_PAIR + slot * entry_span;

		primary = (SDS_ENTRY *)(stream + cursor);
		backup = (SDS_ENTRY *)(stream + FIXTURE_BLOCK + cursor);
		memcpy(primary, source, source_length);
		primary->security_id = cpu_to_le32((uint32_t)(0x100U + i));
		primary->offset = cpu_to_le64(cursor);
		memcpy(backup, primary, source_length);
	}
	phase = "sds-write-and-reset";
	if (ntfs_attr_truncate(sds, stream_length))
		goto out;
	phase = "sds-write";
	{
		uint64_t written = 0;
		while (written < stream_length) {
			int64_t request = stream_length - written > 4096U ? 4096 :
				(int64_t)(stream_length - written);
			int64_t chunk = ntfs_attr_pwrite(sds, written, request,
				stream + written);
			if (chunk != request) {
				fprintf(stderr, "sds short write=%lld at=%llu size=%lld\n",
					(long long)chunk, (unsigned long long)written,
					(long long)sds->data_size);
				goto out;
			}
			written += (uint64_t)request;
		}
	}
	phase = "sii-reset";
	if (reset_index(inode, NTFS_INDEX_SII))
		goto out;
	phase = "sdh-reset";
	if (reset_index(inode, NTFS_INDEX_SDH))
		goto out;
	for (unsigned long i = 0; i < count; i++) {
		uint64_t pair = i / descriptors_per_block;
		uint64_t slot = i % descriptors_per_block;
		SDS_ENTRY *entry = (SDS_ENTRY *)(stream + pair * FIXTURE_PAIR +
			slot * entry_span);

		phase = "index-insert";
		if (add_index_entry(inode, NTFS_INDEX_SII, 0, entry) ||
				add_index_entry(inode, NTFS_INDEX_SDH, 1, entry))
			goto out;
	}
	phase = "inode-sync";
	if (ntfs_inode_sync(inode))
		goto out;
	if (argc == 4 && !strcmp(argv[3], "nonresident-bitmap")) {
		phase = "nonresident-bitmap";
		if (force_nonresident_bitmap(inode, NTFS_INDEX_SDH) ||
				force_nonresident_bitmap(inode, NTFS_INDEX_SII) ||
				ntfs_inode_sync(inode))
			goto out;
	}
	if (current_profile) {
		phase = "current-profile-shape";
		if (sds->data_size != CURRENT_PROFILE_SDS_DATA ||
				sds->allocated_size != CURRENT_PROFILE_SDS_ALLOCATED ||
				verify_current_profile_index(inode, NTFS_INDEX_SDH) ||
				verify_current_profile_index(inode, NTFS_INDEX_SII))
			goto out;
		fprintf(stderr, "current-profile descriptors=30 sds=%lld/%lld "
			"sdh-ia=4096 sii-ia=4096 bitmaps=resident/8\n",
			(long long)sds->data_size, (long long)sds->allocated_size);
	}
	result = 0;
out:
	free(stream);
	free(source);
	if (sds)
		ntfs_attr_close(sds);
	if (inode)
		ntfs_inode_close(inode);
	if (volume && ntfs_umount(volume, 0) && !result)
		result = 1;
	if (result)
		fprintf(stderr, "large fixture phase=%s errno=%d (%s)\n", phase,
			errno, strerror(errno));
	return result;
}
