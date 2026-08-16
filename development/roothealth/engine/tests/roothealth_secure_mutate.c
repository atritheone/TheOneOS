#include "config.h"

#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include "endians.h"
#include "layout.h"
#include "mst.h"
#include "roothealth_raw_mft.h"
#include "roothealth_secure.h"

#define TEST_SDS_BLOCK UINT64_C(0x40000)
#define TEST_SDS_HEADER ((size_t)offsetof(SDS_ENTRY, sid))

static uint32_t descriptor_hash(const unsigned char *bytes, size_t length)
{
	uint32_t hash = 0;
	size_t i;

	for (i = 0; i < length; i += 4U) {
		uint32_t word = (uint32_t)bytes[i] |
			((uint32_t)bytes[i + 1U] << 8) |
			((uint32_t)bytes[i + 2U] << 16) |
			((uint32_t)bytes[i + 3U] << 24);
		hash = (hash << 3) | (hash >> 29);
		hash += word;
	}
	return hash;
}

static int logical_to_physical(const struct rh_secure_inspection *inspection,
		uint64_t logical, uint64_t length, uint64_t *physical)
{
	size_t i;

	for (i = 0; i < inspection->sds_slice_count; i++) {
		const struct rh_secure_mapping_slice *slice =
			&inspection->sds_slices[i];

		if (logical >= slice->logical_offset &&
				logical - slice->logical_offset <= slice->length &&
				length <= slice->length - (logical - slice->logical_offset)) {
			*physical = slice->physical_offset +
				(logical - slice->logical_offset);
			return 0;
		}
	}
	errno = ERANGE;
	return -1;
}

static int full_pread(int fd, void *buffer, size_t length, uint64_t offset)
{
	unsigned char *bytes = buffer;
	size_t done = 0;

	while (done < length) {
		ssize_t got = pread(fd, bytes + done, length - done,
			(off_t)(offset + done));

		if (got <= 0)
			return -1;
		done += (size_t)got;
	}
	return 0;
}

static int full_pwrite(int fd, const void *buffer, size_t length,
		uint64_t offset)
{
	const unsigned char *bytes = buffer;
	size_t done = 0;

	while (done < length) {
		ssize_t put = pwrite(fd, bytes + done, length - done,
			(off_t)(offset + done));

		if (put <= 0)
			return -1;
		done += (size_t)put;
	}
	return 0;
}

static int flip_sds_descriptor(int fd,
		const struct rh_secure_inspection *inspection, int backup,
		int make_independently_valid)
{
	const struct rh_secure_descriptor *descriptor = &inspection->descriptors[0];
	unsigned char *entry;
	uint64_t logical = descriptor->offset +
		(backup ? TEST_SDS_BLOCK : 0U), physical;
	uint32_t hash;

	if (descriptor->length <= TEST_SDS_HEADER + 4U ||
			logical_to_physical(inspection, logical, descriptor->length,
				&physical))
		return -1;
	entry = malloc(descriptor->length);
	if (!entry)
		return -1;
	if (full_pread(fd, entry, descriptor->length, physical))
		goto error;
	entry[descriptor->length - 1U] ^= 0x01U;
	if (make_independently_valid) {
		hash = descriptor_hash(entry + TEST_SDS_HEADER,
			descriptor->length - TEST_SDS_HEADER);
		entry[0] = (unsigned char)hash;
		entry[1] = (unsigned char)(hash >> 8);
		entry[2] = (unsigned char)(hash >> 16);
		entry[3] = (unsigned char)(hash >> 24);
	}
	if (full_pwrite(fd, entry, descriptor->length, physical))
		goto error;
	free(entry);
	return 0;
error:
	free(entry);
	return -1;
}

static int flip_index_padding(int fd, uint64_t semantic_physical,
		uint64_t value_length)
{
	unsigned char byte;
	uint64_t physical;

	if (value_length < 3U || semantic_physical > UINT64_MAX - value_length)
		return -1;
	/* Stay clear of the raw MFT sector trailer at offsets 510/511. */
	physical = semantic_physical + value_length - 3U;
	if (full_pread(fd, &byte, 1, physical))
		return -1;
	byte ^= 0x5aU;
	return full_pwrite(fd, &byte, 1, physical);
}

static int write_logical(int fd,
		const struct rh_secure_inspection *inspection, uint64_t logical,
		const void *bytes, size_t length)
{
	uint64_t physical;

	return logical_to_physical(inspection, logical, length, &physical) ||
		full_pwrite(fd, bytes, length, physical);
}

static uint64_t first_unused_slot(
		const struct rh_secure_inspection *inspection)
{
	uint64_t end = 0;
	size_t i;

	for (i = 0; i < inspection->descriptor_count; i++) {
		uint64_t descriptor_end = inspection->descriptors[i].offset +
			inspection->descriptors[i].length;

		if (descriptor_end > end)
			end = descriptor_end;
	}
	return (end + 15U) & ~UINT64_C(15);
}

static int add_gap_bytes(int fd,
		const struct rh_secure_inspection *inspection)
{
	const unsigned char gap[16] = {
		0xa5, 0x5a, 0x31, 0x72, 0x88, 0x19, 0xee, 0x40,
		0x02, 0x91, 0x73, 0x14, 0xbc, 0x6d, 0xf0, 0x27
	};
	uint64_t logical = first_unused_slot(inspection) + 0x100U;

	return logical > TEST_SDS_BLOCK - sizeof(gap) ? -1 :
		write_logical(fd, inspection, logical, gap, sizeof(gap));
}

static int add_retired_entry(int fd,
		const struct rh_secure_inspection *inspection)
{
	const struct rh_secure_descriptor *source = &inspection->descriptors[0];
	unsigned char *entry = NULL;
	uint64_t source_physical, retired = first_unused_slot(inspection) + 0x200U;
	int result = -1;

	retired = (retired + 15U) & ~UINT64_C(15);
	if (retired > TEST_SDS_BLOCK - source->length ||
			logical_to_physical(inspection, source->offset, source->length,
				&source_physical))
		return -1;
	entry = malloc(source->length);
	if (!entry || full_pread(fd, entry, source->length, source_physical))
		goto out;
	entry[4] = 0x00U;
	entry[5] = 0x05U;
	entry[6] = entry[7] = 0;
	for (unsigned int i = 0; i < 8U; i++)
		entry[8U + i] = (unsigned char)(retired >> (8U * i));
	/* The mkntfs fixture's short final backup ends at its live descriptors. */
	if (write_logical(fd, inspection, retired, entry, source->length))
		goto out;
	result = 0;
out:
	free(entry);
	return result;
}

static int make_duplicate_hash_ids(int fd,
		const struct rh_secure_inspection *inspection)
{
	const struct rh_secure_descriptor *source = &inspection->descriptors[0];
	const struct rh_secure_descriptor *target = &inspection->descriptors[1];
	unsigned char *entry = NULL;
	uint64_t source_physical;
	int result = -1;

	if (source->length != target->length ||
			logical_to_physical(inspection, source->offset, source->length,
				&source_physical)) {
		errno = ENOTSUP;
		return -1;
	}
	entry = malloc(source->length);
	if (!entry || full_pread(fd, entry, source->length, source_physical))
		goto out;
	entry[4] = (unsigned char)target->security_id;
	entry[5] = (unsigned char)(target->security_id >> 8);
	entry[6] = (unsigned char)(target->security_id >> 16);
	entry[7] = (unsigned char)(target->security_id >> 24);
	for (unsigned int i = 0; i < 8U; i++)
		entry[8U + i] = (unsigned char)(target->offset >> (8U * i));
	if (write_logical(fd, inspection, target->offset, entry,
			target->length) ||
			write_logical(fd, inspection, target->offset + TEST_SDS_BLOCK,
				entry, target->length))
		goto out;
	result = 0;
out:
	free(entry);
	return result;
}

static int secure_mapping_attribute(const ATTR_RECORD *attribute, uint32_t type,
		int include_indexes)
{
	const unsigned char *name;
	uint16_t name_offset;
	uint32_t length = le32_to_cpu(attribute->length);

	if (!attribute->non_resident || attribute->name_length != 4U ||
			(type != le32_to_cpu(AT_DATA) &&
			 (!include_indexes || (type != le32_to_cpu(AT_INDEX_ALLOCATION) &&
			  type != le32_to_cpu(AT_BITMAP)))))
		return 0;
	name_offset = le16_to_cpu(attribute->name_offset);
	if (name_offset > length || 8U > length - name_offset)
		return 0;
	name = (const unsigned char *)attribute + name_offset;
	if (name[0] != '$' || name[1] || name[2] != 'S' || name[3] ||
			name[5] || name[7])
		return 0;
	if (type == le32_to_cpu(AT_DATA))
		return name[4] == 'D' && name[6] == 'S';
	return (name[4] == 'D' && name[6] == 'H') ||
		(name[4] == 'I' && name[6] == 'I');
}

static int mst_protected_position(size_t offset, uint32_t usa_offset,
		uint32_t usa_length)
{
	return (offset & 511U) >= 510U ||
		(offset >= usa_offset && offset - usa_offset < usa_length);
}

static int mutate_mapping_tail(ATTR_RECORD *attribute, uint32_t length,
		uint32_t record_offset, uint32_t usa_offset, uint32_t usa_length,
		unsigned int ordinal)
{
	unsigned char *bytes = (unsigned char *)attribute;
	uint32_t scan = le16_to_cpu(attribute->mapping_pairs_offset);
	uint32_t candidate;

	if (scan >= length)
	{
		errno = EINVAL;
		return -1;
	}
	while (scan < length && bytes[scan]) {
		uint32_t field = bytes[scan++];
		uint32_t length_bytes = field & 15U;
		uint32_t offset_bytes = field >> 4;

		if (!length_bytes || length_bytes > 8U || offset_bytes > 8U ||
				length_bytes + offset_bytes > length - scan) {
			errno = EUCLEAN;
			return -1;
		}
		scan += length_bytes + offset_bytes;
	}
	if (scan >= length || scan + 1U >= length) {
		errno = ENOSPC;
		return -1;
	}
	for (candidate = scan + 1U; candidate < length; candidate++)
		if (!mst_protected_position(record_offset + candidate, usa_offset,
				usa_length)) {
			bytes[candidate] = (unsigned char)(0xa0U | (ordinal & 15U));
			return 0;
		}
	errno = ENOSPC;
	return -1;
}

static int add_mapping_pairs_tail(int fd,
		const struct rh_secure_inspection *inspection, int include_indexes)
{
	unsigned char raw[1024], record[1024];
	MFT_RECORD *mft = (MFT_RECORD *)record;
	uint32_t cursor, usa_offset, usa_length;
	unsigned int mutated = 0, applied = 0;
	size_t i;

	if (full_pread(fd, raw, sizeof(raw), inspection->mft_record_physical))
		return -1;
	memcpy(record, raw, sizeof(record));
	if (
			ntfs_mst_post_read_fixup((NTFS_RECORD *)record, sizeof(record)))
		return -1;
	usa_offset = le16_to_cpu(mft->usa_ofs);
	usa_length = (uint32_t)le16_to_cpu(mft->usa_count) * sizeof(le16);
	if (usa_offset > sizeof(record) || usa_length > sizeof(record) - usa_offset)
		return -1;
	cursor = le16_to_cpu(mft->attrs_offset);
	while (cursor <= sizeof(record) - sizeof(uint32_t)) {
		ATTR_RECORD *attribute = (ATTR_RECORD *)(record + cursor);
		uint32_t type = le32_to_cpu(attribute->type);
		uint32_t length;

		if (type == le32_to_cpu(AT_END))
			break;
		length = le32_to_cpu(attribute->length);
		if (length < offsetof(ATTR_RECORD, resident_end) || (length & 7U) ||
				length > sizeof(record) - cursor)
			return -1;
		if (attribute->non_resident &&
				length < offsetof(ATTR_RECORD, non_resident_end))
			return -1;
		if (secure_mapping_attribute(attribute, type, include_indexes)) {
			mutated++;
			if (mutate_mapping_tail(attribute, length, cursor, usa_offset,
					usa_length, mutated))
				return -1;
		}
		cursor += length;
	}
	if (!mutated) {
		errno = ENOENT;
		return -1;
	}
	for (i = 0; i < sizeof(record); i++) {
		if (record[i] == raw[i])
			continue;
		if (mst_protected_position(i, usa_offset, usa_length))
			continue;
		raw[i] = record[i];
		applied++;
	}
	if (applied < mutated) {
		errno = EUCLEAN;
		return -1;
	}
	return full_pwrite(fd, raw, sizeof(raw),
		inspection->mft_record_physical);
}

static int add_nested_sds_ambiguity(int fd,
		const struct rh_secure_inspection *inspection)
{
	const struct rh_secure_descriptor *descriptor = &inspection->descriptors[0];
	unsigned char *source = NULL;
	unsigned char outer[192];
	uint64_t physical;
	int result = -1;

	if (descriptor->offset || descriptor->length > sizeof(outer) - 32U ||
			logical_to_physical(inspection, descriptor->offset,
				descriptor->length, &physical))
		return -1;
	source = malloc(descriptor->length);
	if (!source || full_pread(fd, source, descriptor->length, physical))
		goto out;
	memset(outer, 0, sizeof(outer));
	/* Plausible self-pointing outer entry whose descriptor body is invalid. */
	memcpy(outer, source, TEST_SDS_HEADER);
	outer[16] = (unsigned char)sizeof(outer);
	outer[17] = outer[18] = outer[19] = 0;
	/* A second, hash-valid live-ID entry begins at an aligned nested slot. */
	memcpy(outer + 32U, source, descriptor->length);
	outer[40] = 32U;
	memset(outer + 41U, 0, 7U);
	if (write_logical(fd, inspection, 0, outer, sizeof(outer)))
		goto out;
	result = 0;
out:
	free(source);
	return result;
}

int main(int argc, char **argv)
{
	struct rh_writer writer;
	struct rh_ntfs_overlay overlay;
	struct rh_secure_inspection inspection;
	struct rh_secure_census census;
	struct rh_raw_mft_census raw;
	uint32_t *live_ids = NULL;
	unsigned char legacy_hash[32];
	uint64_t legacy_count = 0;
	size_t live_id_count = 2U, i;
	int use_raw = 0;
	int fd = -1, result = 1;

	if (argc != 3 && argc != 4 && argc != 5)
		return 64;
	if (argc >= 4) {
		char *end = NULL;
		unsigned long count;

		errno = 0;
		count = strtoul(argv[3], &end, 10);
		if (errno || !end || *end || !count || count > UINT32_MAX - 0x100U)
			return 64;
		live_id_count = count;
	}
	if (argc == 5) {
		if (strcmp(argv[4], "raw"))
			return 64;
		use_raw = 1;
	}
	if (live_id_count > SIZE_MAX / sizeof(*live_ids))
		return 64;
	live_ids = malloc(live_id_count * sizeof(*live_ids));
	if (!live_ids)
		return 1;
	for (i = 0; i < live_id_count; i++)
		live_ids[i] = 0x100U + (uint32_t)i;
	memset(&inspection, 0, sizeof(inspection));
	memset(&census, 0, sizeof(census));
	memset(&raw, 0, sizeof(raw));
	census.generation = UINT64_C(0x5345434d55544154);
	census.complete_security_id_census = 1;
	census.security_ids_expected = live_id_count;
	census.security_ids_examined = live_id_count;
	census.live_security_id_count = live_id_count;
	census.live_security_ids = live_ids;
	if (rh_writer_open(&writer, argv[1])) {
		perror("writer open");
		free(live_ids);
		return 1;
	}
	if (rh_ntfs_overlay_mount(&overlay, &writer, 0)) {
		perror("overlay mount");
		rh_writer_close(&writer);
		goto out;
	}
	if (use_raw && (rh_raw_mft_census_run(overlay.volume, &writer,
				census.generation, &raw) ||
			 rh_secure_legacy_census(&raw, &legacy_count, legacy_hash))) {
		perror("raw authority");
		rh_ntfs_overlay_unmount(&overlay);
		rh_writer_close(&writer);
		goto out;
	}
	if (use_raw) {
		census.raw_mft_extent_authority_complete = 1;
		census.raw_mft_census = &raw;
		memcpy(census.raw_mft_census_hash, raw.census_hash, 32);
		census.legacy_security_descriptors_expected = legacy_count;
		census.legacy_security_descriptors_examined = legacy_count;
		memcpy(census.legacy_security_descriptor_hash, legacy_hash, 32);
	}
	if (
			rh_secure_inspect(overlay.volume, &writer, &census, &inspection)) {
		perror("clean inspect");
		rh_ntfs_overlay_unmount(&overlay);
		rh_writer_close(&writer);
		goto out;
	}
	rh_ntfs_overlay_unmount(&overlay);
	rh_writer_close(&writer);
	fd = open(argv[1], O_RDWR | O_CLOEXEC | O_NOFOLLOW);
	if (fd < 0) {
		perror("open writable fixture");
		goto out;
	}
	fprintf(stderr, "fixture sdh=%llu/%llu sii=%llu/%llu mft=%llu\n",
		(unsigned long long)inspection.sdh_semantic_physical,
		(unsigned long long)inspection.sdh_value_length,
		(unsigned long long)inspection.sii_semantic_physical,
		(unsigned long long)inspection.sii_value_length,
		(unsigned long long)inspection.mft_record_physical);
	if (!strcmp(argv[2], "sds-backup"))
		result = flip_sds_descriptor(fd, &inspection, 1, 0);
	else if (!strcmp(argv[2], "sds-primary"))
		result = flip_sds_descriptor(fd, &inspection, 0, 0);
	else if (!strcmp(argv[2], "sds-conflict"))
		result = flip_sds_descriptor(fd, &inspection, 1, 1);
	else if (!strcmp(argv[2], "sds-both-invalid"))
		result = flip_sds_descriptor(fd, &inspection, 0, 0) ||
			flip_sds_descriptor(fd, &inspection, 1, 0);
	else if (!strcmp(argv[2], "sdh"))
		result = flip_index_padding(fd, inspection.sdh_semantic_physical,
			inspection.sdh_value_length);
	else if (!strcmp(argv[2], "sii"))
		result = flip_index_padding(fd, inspection.sii_semantic_physical,
			inspection.sii_value_length);
	else if (!strcmp(argv[2], "indexes"))
		result = flip_index_padding(fd, inspection.sdh_semantic_physical,
			inspection.sdh_value_length) ||
			flip_index_padding(fd, inspection.sii_semantic_physical,
				inspection.sii_value_length);
	else if (!strcmp(argv[2], "all"))
		result = flip_sds_descriptor(fd, &inspection, 1, 0) ||
			flip_index_padding(fd, inspection.sdh_semantic_physical,
				inspection.sdh_value_length) ||
			flip_index_padding(fd, inspection.sii_semantic_physical,
				inspection.sii_value_length);
	else if (!strcmp(argv[2], "gap"))
		result = add_gap_bytes(fd, &inspection);
	else if (!strcmp(argv[2], "retired"))
		result = add_retired_entry(fd, &inspection);
	else if (!strcmp(argv[2], "duplicate-hash"))
		result = make_duplicate_hash_ids(fd, &inspection);
	else if (!strcmp(argv[2], "mapping-tail"))
		result = add_mapping_pairs_tail(fd, &inspection, 0);
	else if (!strcmp(argv[2], "mapping-tail-all"))
		result = add_mapping_pairs_tail(fd, &inspection, 1);
	else if (!strcmp(argv[2], "nested-ambiguity"))
		result = add_nested_sds_ambiguity(fd, &inspection);
	else {
		errno = EINVAL;
		result = -1;
	}
	if (result) {
		perror("mutate");
	} else if (fsync(fd)) {
		perror("fsync");
		result = -1;
	}
out:
	if (fd >= 0)
		close(fd);
	rh_secure_inspection_destroy(&inspection);
	rh_raw_mft_census_release(&raw);
	free(live_ids);
	return result ? 1 : 0;
}
