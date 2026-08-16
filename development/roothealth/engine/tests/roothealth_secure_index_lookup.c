#include "config.h"

#include <errno.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "attrib.h"
#include "dir.h"
#include "endians.h"
#include "index.h"
#include "inode.h"
#include "layout.h"
#include "roothealth_secure.h"
#include "volume.h"

#define LOOKUP_SDS_BLOCK UINT64_C(0x40000)
#define LOOKUP_SDS_PAIR UINT64_C(0x80000)
#define LOOKUP_SDS_ALIGN UINT64_C(16)
#define LOOKUP_SDS_HEADER ((size_t)offsetof(SDS_ENTRY, sid))

static uint32_t descriptor_hash(const unsigned char *bytes, size_t length)
{
	uint32_t hash = 0;
	size_t offset;

	if (length & 3U)
		return UINT32_MAX;
	for (offset = 0; offset < length; offset += 4U) {
		le32 word;

		memcpy(&word, bytes + offset, sizeof(word));
		hash = (hash << 3) | (hash >> 29);
		hash += le32_to_cpu(word);
	}
	return hash;
}

static int find_live_descriptor(const unsigned char *stream, size_t length,
		uint32_t security_id, SDS_ENTRY *result)
{
	uint64_t base;
	unsigned int matches = 0;

	for (base = 0; base < length; base += LOOKUP_SDS_PAIR) {
		size_t primary_length = length - (size_t)base;
		size_t cursor;

		if (primary_length > LOOKUP_SDS_BLOCK)
			primary_length = LOOKUP_SDS_BLOCK;
		for (cursor = 0; cursor + LOOKUP_SDS_HEADER <= primary_length;
				cursor += LOOKUP_SDS_ALIGN) {
			const SDS_ENTRY *candidate = (const SDS_ENTRY *)(stream + base +
				cursor);
			uint32_t entry_length = le32_to_cpu(candidate->length);
			uint64_t logical = base + cursor;
			const unsigned char *descriptor;
			size_t descriptor_length;

			if (le32_to_cpu(candidate->security_id) != security_id ||
					le64_to_cpu(candidate->offset) != logical ||
					entry_length < LOOKUP_SDS_HEADER ||
					entry_length > primary_length - cursor)
				continue;
			descriptor = (const unsigned char *)candidate +
				LOOKUP_SDS_HEADER;
			descriptor_length = entry_length - LOOKUP_SDS_HEADER;
			if (!rh_secure_descriptor_bytes_valid(descriptor,
					descriptor_length) || descriptor_hash(descriptor,
					descriptor_length) != le32_to_cpu(candidate->hash))
				continue;
			if (++matches != 1U)
				return -1;
			memcpy(result, candidate, sizeof(*result));
		}
	}
	return matches == 1U ? 0 : -1;
}

static int validate_entry(const INDEX_ENTRY *entry, const SDS_ENTRY *sds,
		int sdh)
{
	const SECURITY_DESCRIPTOR_HEADER *data;
	uint16_t offset, length;

	if (!entry || !sds || (entry->ie_flags & INDEX_ENTRY_END) ||
			le16_to_cpu(entry->key_length) != (sdh ? 8U : 4U))
		return -1;
	offset = le16_to_cpu(entry->data_offset);
	length = le16_to_cpu(entry->data_length);
	if (length != sizeof(*data) || offset > le16_to_cpu(entry->length) ||
			length > le16_to_cpu(entry->length) - offset)
		return -1;
	data = (const SECURITY_DESCRIPTOR_HEADER *)((const unsigned char *)entry +
		offset);
	if (data->hash != sds->hash || data->security_id != sds->security_id ||
			data->offset != sds->offset || data->length != sds->length)
		return -1;
	if (sdh && (((const SDH_INDEX_DATA *)data)->reserved_II !=
			cpu_to_le32(0x00490049U) || entry->key.sdh.hash != sds->hash ||
			entry->key.sdh.security_id != sds->security_id))
		return -1;
	if (!sdh && entry->key.sii.security_id != sds->security_id)
		return -1;
	return 0;
}

int main(int argc, char **argv)
{
	ntfs_volume *volume = NULL;
	ntfs_inode *inode = NULL;
	ntfs_attr *sds = NULL;
	ntfs_index_context *sdh = NULL, *sii = NULL;
	unsigned char *stream = NULL;
	char *end = NULL;
	unsigned long count;
	SDS_ENTRY entry;
	int result = 1;

	if (argc != 3)
		return 64;
	errno = 0;
	count = strtoul(argv[2], &end, 10);
	if (errno || !end || *end || !count)
		return 64;
	volume = ntfs_mount(argv[1], NTFS_MNT_RDONLY | NTFS_MNT_FORENSIC |
		NTFS_MNT_FS_NO_REPAIR);
	if (!volume)
		goto out;
	inode = ntfs_inode_open(volume, FILE_Secure);
	if (!inode)
		goto out;
	sds = ntfs_attr_open(inode, AT_DATA, STREAM_SDS, 4);
	if (!sds || sds->data_size <= 0 || (uint64_t)sds->data_size > SIZE_MAX)
		goto out;
	stream = malloc((size_t)sds->data_size);
	if (!stream || ntfs_attr_pread(sds, 0, sds->data_size, stream) !=
			sds->data_size)
		goto out;
	sdh = ntfs_index_ctx_get(inode, NTFS_INDEX_SDH, 4);
	sii = ntfs_index_ctx_get(inode, NTFS_INDEX_SII, 4);
	if (!sdh || !sii)
		goto out;
	for (unsigned long i = 0; i < count; i++) {
		SDH_INDEX_KEY sdh_key;
		SII_INDEX_KEY sii_key;

		if (find_live_descriptor(stream, (size_t)sds->data_size,
				0x100U + (uint32_t)i, &entry))
			goto out;
		sdh_key.hash = entry.hash;
		sdh_key.security_id = entry.security_id;
		sii_key.security_id = entry.security_id;
		ntfs_index_ctx_reinit(sdh);
		if (ntfs_index_lookup(&sdh_key, sizeof(sdh_key), sdh) ||
				validate_entry(sdh->entry, &entry, 1))
			goto out;
		ntfs_index_ctx_reinit(sii);
		if (ntfs_index_lookup(&sii_key, sizeof(sii_key), sii) ||
				validate_entry(sii->entry, &entry, 0))
			goto out;
	}
	printf("secure_index_lookups=%lu sdh=exact sii=exact\n", count);
	result = 0;
out:
	free(stream);
	if (sii)
		ntfs_index_ctx_put(sii);
	if (sdh)
		ntfs_index_ctx_put(sdh);
	if (sds)
		ntfs_attr_close(sds);
	if (inode)
		ntfs_inode_close(inode);
	if (volume)
		ntfs_umount(volume, TRUE);
	if (result)
		perror("secure index lookup");
	return result;
}
