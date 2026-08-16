/* ROOTHEALTH_IO_ROLE(PLANNER) */
#include "config.h"

#include <errno.h>
#include <dirent.h>
#include <inttypes.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>

#include "bootsect.h"
#include "device.h"
#include "dir.h"
#include "endians.h"
#include "inode.h"
#include "layout.h"
#include "mst.h"
#include "roothealth_namespace.h"
#include "roothealth_hash_stream.h"
#include "roothealth_raw_mft.h"
#include "roothealth_repair.h"
#include "volume.h"

static int rh_power_of_two(uint64_t value)
{
	return value && !(value & (value - 1));
}

static int rh_record_size(s8 encoded, uint32_t cluster_size,
		uint32_t *result)
{
	uint64_t size;
	if (encoded < 0) {
		if (encoded == -128 || -encoded >= 32)
			return -1;
		size = 1ULL << -encoded;
	} else {
		size = (uint64_t)(uint8_t)encoded * cluster_size;
	}
	if (!rh_power_of_two(size) || size < 512 || size > 65536)
		return -1;
	*result = (uint32_t)size;
	return 0;
}

int roothealth_boot_sector_validate(unsigned char *sector, uint32_t sector_size,
		uint64_t device_size, struct rh_boot_geometry *geometry)
{
	NTFS_BOOT_SECTOR *boot = (NTFS_BOOT_SECTOR *)sector;
	uint32_t sectors_per_cluster;
	uint64_t clusters;
	uint64_t sector_count;

	if (sector_size < sizeof(*boot) ||
		le16_to_cpu(boot->bpb.bytes_per_sector) != sector_size ||
		boot->end_of_sector_marker != const_cpu_to_le16(0xaa55) ||
		!ntfs_boot_sector_is_ntfs(boot))
		return 0;
	sectors_per_cluster = boot->bpb.sectors_per_cluster;
	if (!sectors_per_cluster || sectors_per_cluster > 128 ||
		!rh_power_of_two(sectors_per_cluster))
		return 0;
	sector_count = (uint64_t)sle64_to_cpu(boot->number_of_sectors);
	if (!sector_count || sector_count > device_size / sector_size)
		return 0;
	geometry->sector_size = sector_size;
	geometry->cluster_size = sector_size * sectors_per_cluster;
	geometry->sector_count = sector_count;
	geometry->mft_lcn = (uint64_t)sle64_to_cpu(boot->mft_lcn);
	geometry->mftmirr_lcn = (uint64_t)sle64_to_cpu(boot->mftmirr_lcn);
	geometry->serial = le64_to_cpu(boot->volume_serial_number);
	clusters = sector_count / sectors_per_cluster;
	if (!geometry->serial || !geometry->mft_lcn ||
		!geometry->mftmirr_lcn || geometry->mft_lcn >= clusters ||
		geometry->mftmirr_lcn >= clusters ||
		geometry->mft_lcn == geometry->mftmirr_lcn ||
		rh_record_size(boot->clusters_per_mft_record,
			geometry->cluster_size, &geometry->mft_record_size) ||
		rh_record_size(boot->clusters_per_index_record,
			geometry->cluster_size, &geometry->index_record_size))
		return 0;
	if (geometry->cluster_size <= 4U * geometry->mft_record_size)
		geometry->mirrored_records = 4;
	else
		geometry->mirrored_records = geometry->cluster_size /
			geometry->mft_record_size;
	if (geometry->mirrored_records > FILE_first_user)
		geometry->mirrored_records = FILE_first_user;
	return 1;
}

#define RH_BOOTSTRAP_MAX_LOGFILE_SIZE (64U * 1024U * 1024U)

struct rh_bootstrap_run {
	uint64_t lcn;
	uint64_t length;
};

struct rh_bootstrap_runs {
	struct rh_bootstrap_run *items;
	size_t count;
	size_t capacity;
};

struct rh_bootstrap_stream {
	uint64_t first_lcn;
	uint64_t clusters;
	uint64_t allocated_size;
	uint64_t data_size;
	uint64_t initialized_size;
};

static int rh_bytes_zero(const unsigned char *bytes, size_t length)
{
	size_t i;

	for (i = 0; i < length; i++)
		if (bytes[i])
			return 0;
	return 1;
}

static uint64_t rh_get_unsigned_le(const unsigned char *bytes, size_t count)
{
	uint64_t value = 0;
	size_t i;

	for (i = 0; i < count; i++)
		value |= (uint64_t)bytes[i] << (8U * i);
	return value;
}

static int64_t rh_get_signed_le(const unsigned char *bytes, size_t count)
{
	uint64_t value = rh_get_unsigned_le(bytes, count);
	int64_t result;

	if (count < sizeof(value) && (bytes[count - 1U] & 0x80U))
		value |= UINT64_MAX << (8U * count);
	memcpy(&result, &value, sizeof(result));
	return result;
}

static int rh_s64_add_checked(int64_t left, int64_t right, int64_t *result)
{
	if ((right > 0 && left > INT64_MAX - right) ||
		(right < 0 && left < INT64_MIN - right))
		return -1;
	*result = left + right;
	return 0;
}

static int rh_bootstrap_runs_reserve(struct rh_bootstrap_runs *runs)
{
	struct rh_bootstrap_run *grown;
	size_t capacity;

	if (runs->count < runs->capacity)
		return 0;
#ifdef ROOTHEALTH_REPAIR_TESTING
	{
		const char *failure = getenv("ROOTHEALTH_REPAIR_TEST_FAIL");

		/* Exercise failure of a growth which the removed 128-run ceiling
		 * used to classify as corrupt metadata.  This threshold is test-only
		 * and never constrains production input. */
		if (failure && !strcmp(failure, "bootstrap-runs-oom") &&
			runs->count >= 128U) {
			errno = ENOMEM;
			return -1;
		}
	}
#endif
	capacity = runs->capacity ? runs->capacity : 16U;
	if (capacity > SIZE_MAX / 2U)
		capacity = SIZE_MAX;
	else
		capacity *= 2U;
	if (capacity <= runs->count ||
		capacity > SIZE_MAX / sizeof(*runs->items)) {
		errno = ENOMEM;
		return -1;
	}
	grown = realloc(runs->items, capacity * sizeof(*runs->items));
	if (!grown)
		return -1;
	runs->items = grown;
	runs->capacity = capacity;
	return 0;
}

static int rh_bootstrap_run_compare(const void *left_value,
		const void *right_value)
{
	const struct rh_bootstrap_run *left = left_value;
	const struct rh_bootstrap_run *right = right_value;

	if (left->lcn < right->lcn)
		return -1;
	if (left->lcn > right->lcn)
		return 1;
	if (left->length < right->length)
		return -1;
	if (left->length > right->length)
		return 1;
	return 0;
}

static int rh_bootstrap_runs_nonoverlapping(struct rh_bootstrap_runs *runs)
{
	size_t i;

	if (runs->count < 2U)
		return 1;
	qsort(runs->items, runs->count, sizeof(*runs->items),
		rh_bootstrap_run_compare);
	for (i = 1; i < runs->count; i++) {
		uint64_t previous_end;

		if (runs->items[i - 1U].length >
			UINT64_MAX - runs->items[i - 1U].lcn)
			return 0;
		previous_end = runs->items[i - 1U].lcn +
			runs->items[i - 1U].length;
		if (runs->items[i].lcn < previous_end)
			return 0;
	}
	return 1;
}

#ifdef ROOTHEALTH_REPAIR_TESTING
int roothealth_bootstrap_test_run_intervals(size_t count, int overlap)
{
	struct rh_bootstrap_runs runs = {0};
	size_t i;
	int result;

	if (!count || count > UINT64_MAX / 2U)
		return RH_RESULT_UNSAFE;
	for (i = 0; i < count; i++) {
		if (rh_bootstrap_runs_reserve(&runs)) {
			free(runs.items);
			return RH_RESULT_INTERNAL;
		}
		/* Reverse physical order is valid and forces an actual sort. */
		runs.items[runs.count].lcn = 2U * (uint64_t)(count - i);
		runs.items[runs.count].length = 1U;
		runs.count++;
	}
	if (overlap && count > 1U)
		runs.items[count - 1U].lcn = runs.items[0].lcn;
	result = rh_bootstrap_runs_nonoverlapping(&runs) ? RH_RESULT_OK :
		RH_RESULT_UNSAFE;
	free(runs.items);
	return result;
}
#endif

static int rh_bootstrap_mapping_pairs(const ATTR_RECORD *attr,
		uint32_t length, const struct rh_boot_geometry *geometry,
		struct rh_bootstrap_runs *runs,
		struct rh_bootstrap_stream *stream)
{
	const unsigned char *cursor, *end;
	uint64_t volume_clusters;
	uint64_t vcn = 0;
	int64_t lcn = 0;
	int64_t highest;
	uint64_t allocated, data, initialized;
	int terminated = 0;

	if (!attr->non_resident || length < 64U || attr->name_length ||
		le16_to_cpu(attr->name_offset) != 64U ||
		le16_to_cpu(attr->mapping_pairs_offset) != 64U ||
		le16_to_cpu(attr->flags) || attr->compression_unit ||
		!rh_bytes_zero(attr->reserved1, sizeof(attr->reserved1)) ||
		sle64_to_cpu(attr->lowest_vcn) != 0)
		return 0;
	highest = sle64_to_cpu(attr->highest_vcn);
	if (highest < 0 || highest == INT64_MAX)
		return 0;
	allocated = (uint64_t)sle64_to_cpu(attr->allocated_size);
	data = (uint64_t)sle64_to_cpu(attr->data_size);
	initialized = (uint64_t)sle64_to_cpu(attr->initialized_size);
	if ((int64_t)allocated < 0 || (int64_t)data < 0 ||
		(int64_t)initialized < 0 || !allocated || !data ||
		initialized != data || data > allocated ||
		(allocated & (geometry->cluster_size - 1U)))
		return 0;
	volume_clusters = geometry->sector_count /
		(geometry->cluster_size / geometry->sector_size);
	cursor = (const unsigned char *)attr + 64U;
	end = (const unsigned char *)attr + length;
	while (cursor < end) {
		unsigned int length_bytes, offset_bytes;
		uint64_t run_length;
		int64_t delta, next_lcn;

		if (!*cursor) {
			cursor++;
			/* Bytes after the first bounded terminator are opaque
			 * ATTR_RECORD slack.  Pinned libntfs preserves rather than
			 * canonicalizes them, so they do not participate in decoding. */
			terminated = 1;
			break;
		}
		length_bytes = *cursor & 0x0fU;
		offset_bytes = *cursor >> 4;
		cursor++;
		if (!length_bytes || length_bytes > 8U || !offset_bytes ||
			offset_bytes > 8U || (size_t)(end - cursor) <
				(size_t)length_bytes + offset_bytes)
			return 0;
		run_length = rh_get_unsigned_le(cursor, length_bytes);
		cursor += length_bytes;
		delta = rh_get_signed_le(cursor, offset_bytes);
		cursor += offset_bytes;
		if (!run_length || run_length > UINT64_MAX - vcn ||
			rh_s64_add_checked(lcn, delta, &next_lcn) || next_lcn < 0 ||
			(uint64_t)next_lcn >= volume_clusters ||
			run_length > volume_clusters - (uint64_t)next_lcn)
			return 0;
		if (rh_bootstrap_runs_reserve(runs))
			return -1;
		if (!vcn)
			stream->first_lcn = (uint64_t)next_lcn;
		runs->items[runs->count].lcn = (uint64_t)next_lcn;
		runs->items[runs->count].length = run_length;
		runs->count++;
		lcn = next_lcn;
		vcn += run_length;
	}
	if (!terminated || vcn != (uint64_t)highest + 1U ||
		vcn > UINT64_MAX / geometry->cluster_size ||
		allocated != vcn * geometry->cluster_size)
		return 0;
	stream->clusters = vcn;
	stream->allocated_size = allocated;
	stream->data_size = data;
	stream->initialized_size = initialized;
	return 1;
}

static int rh_bootstrap_filename_valid(const ATTR_RECORD *attr,
		const char *expected)
{
	const FILE_NAME_ATTR *name;
	uint32_t value_length = le32_to_cpu(attr->value_length);
	uint32_t expected_length = (uint32_t)strlen(expected);
	uint64_t parent;
	uint32_t i;

	if (value_length != sizeof(*name) + expected_length * sizeof(ntfschar))
		return 0;
	name = (const FILE_NAME_ATTR *)((const unsigned char *)attr + 24U);
	parent = le64_to_cpu(name->parent_directory);
	if (MREF(parent) != FILE_root || MSEQNO(parent) != FILE_root ||
		name->file_name_length != expected_length ||
		name->file_name_type != FILE_NAME_WIN32_AND_DOS ||
		le32_to_cpu(name->file_attributes) !=
			(le32_to_cpu(FILE_ATTR_HIDDEN) | le32_to_cpu(FILE_ATTR_SYSTEM)) ||
		name->packed_ea_size || name->reserved)
		return 0;
	for (i = 0; i < expected_length; i++)
		if (le16_to_cpu(name->file_name[i]) != (unsigned char)expected[i])
			return 0;
	return 1;
}

int roothealth_bootstrap_mft_record_structure(const unsigned char *raw,
		uint32_t size,
		uint32_t number, const struct rh_boot_geometry *geometry,
		unsigned char **fixed_out)
{
	static const uint32_t mft_types[] = { 0x10U, 0x30U, 0x80U, 0xb0U };
	static const uint32_t mirror_types[] = { 0x10U, 0x30U, 0x80U };
	static const uint32_t volume_types[] = {
		0x10U, 0x30U, 0x50U, 0x60U, 0x70U, 0x80U
	};
	static const uint32_t volume_windows_types[] = {
		0x10U, 0x30U, 0x60U, 0x70U, 0x80U
	};
	static const uint16_t mft_instances[] = { 0U, 2U, 1U, 3U };
	static const uint16_t mirror_instances[] = { 0U, 2U, 1U };
	static const uint16_t volume_instances[] = { 0U, 1U, 2U, 4U, 5U, 3U };
	static const uint16_t volume_windows_instances[] = { 0U, 1U, 4U, 5U, 3U };
	static const char *const names[] = {
		"$MFT", "$MFTMirr", "$LogFile", "$Volume"
	};
	const uint32_t *expected_types;
	const uint16_t *expected_instances;
	uint32_t expected_count;
	MFT_RECORD *record;
	ATTR_RECORD *attr;
	ATTR_RECORD *filename = NULL;
	unsigned char *fixed;
	struct rh_bootstrap_runs runs = {0};
	struct rh_bootstrap_stream data_stream = {0};
	struct rh_bootstrap_stream bitmap_stream = {0};
	uint32_t used;
	uint16_t offset;
	uint32_t index = 0;
	uint16_t expected_sequence;
	int windows_volume_profile = 0;

	*fixed_out = NULL;
	if (!geometry || size != ROOTHEALTH_SUPPORTED_MFT_RECORD_SIZE ||
		number > FILE_Volume)
		return 0;
	if (number == FILE_MFT) {
		expected_types = mft_types;
		expected_instances = mft_instances;
		expected_count = sizeof(mft_types) / sizeof(mft_types[0]);
	} else if (number == FILE_Volume) {
		expected_types = volume_types;
		expected_instances = volume_instances;
		expected_count = sizeof(volume_types) / sizeof(volume_types[0]);
	} else {
		expected_types = mirror_types;
		expected_instances = mirror_instances;
		expected_count = sizeof(mirror_types) / sizeof(mirror_types[0]);
	}
	fixed = malloc(size);
	if (!fixed)
		return -1;
	memcpy(fixed, raw, size);
	if (ntfs_mst_post_read_fixup((NTFS_RECORD *)fixed, size))
		goto invalid;
	record = (MFT_RECORD *)fixed;
	used = le32_to_cpu(record->bytes_in_use);
	offset = le16_to_cpu(record->attrs_offset);
	expected_sequence = number ? (uint16_t)number : 1U;
	if (record->magic != magic_FILE ||
		le16_to_cpu(record->usa_ofs) != sizeof(*record) ||
		le16_to_cpu(record->usa_count) !=
			size / ROOTHEALTH_SUPPORTED_SECTOR_SIZE + 1U ||
		le32_to_cpu(record->mft_record_number) != number ||
		le16_to_cpu(record->sequence_number) != expected_sequence ||
		le16_to_cpu(record->link_count) != 1U ||
		le16_to_cpu(record->next_attr_instance) !=
			(number == FILE_Volume ? 6U : expected_count) ||
		record->reserved || le32_to_cpu(record->bytes_allocated) != size ||
		used < sizeof(*record) || used > size || (used & 7U) ||
		offset != 56U || offset >= used ||
		le16_to_cpu(record->flags) != le16_to_cpu(MFT_RECORD_IN_USE) ||
		le64_to_cpu(record->base_mft_record))
		goto invalid;
	attr = (ATTR_RECORD *)(fixed + offset);
	/*
	 * Windows upgrades $Volume's $STANDARD_INFORMATION from the 48-byte
	 * NTFS 1.2 form to the 72-byte NTFS 3.x form and removes the legacy
	 * resident $SECURITY_DESCRIPTOR once its security_id is authoritative.
	 * Both records 3 in $MFT and $MFTMirr are updated this way when Windows
	 * first attaches an expanded image.  Accept exactly those two canonical
	 * layouts; all attribute order, instances and framing remain strict.
	 */
	if (number == FILE_Volume && attr->type == AT_STANDARD_INFORMATION &&
			!attr->non_resident &&
			le32_to_cpu(attr->value_length) ==
				offsetof(STANDARD_INFORMATION, v3_end)) {
		expected_types = volume_windows_types;
		expected_instances = volume_windows_instances;
		expected_count = sizeof(volume_windows_types) /
			sizeof(volume_windows_types[0]);
		windows_volume_profile = 1;
	}
	for (;;) {
		uint32_t length, type, value_length;
		uint16_t minimum;
		unsigned char *value_end;

		if ((unsigned char *)attr + sizeof(attr->type) > fixed + used)
			goto invalid;
		if (attr->type == AT_END) {
			if (index != expected_count || !rh_bytes_zero(
					(const unsigned char *)attr + sizeof(attr->type),
					(size_t)(fixed + used -
					 ((unsigned char *)attr + sizeof(attr->type)))))
				goto invalid;
			break;
		}
		if (index >= expected_count ||
			(unsigned char *)attr + 24U > fixed + used)
			goto invalid;
		length = le32_to_cpu(attr->length);
		type = le32_to_cpu(attr->type);
		minimum = attr->non_resident ? 64U : 24U;
		if (type != expected_types[index] ||
			le16_to_cpu(attr->instance) != expected_instances[index] ||
			attr->non_resident > 1 || length < minimum || (length & 7U) ||
			(unsigned char *)attr + length > fixed + used ||
			attr->name_length || le16_to_cpu(attr->name_offset) != minimum ||
			le16_to_cpu(attr->flags))
			goto invalid;
		if (!attr->non_resident) {
			value_length = le32_to_cpu(attr->value_length);
			if (le16_to_cpu(attr->value_offset) != 24U ||
				attr->reservedR || value_length > length - 24U ||
				(type == 0x30U ? attr->resident_flags !=
					RESIDENT_ATTR_IS_INDEXED : attr->resident_flags))
				goto invalid;
			value_end = (unsigned char *)attr + 24U + value_length;
			if (!rh_bytes_zero(value_end,
					(size_t)((unsigned char *)attr + length - value_end)))
				goto invalid;
			if (type == 0x10U) {
				const STANDARD_INFORMATION *standard =
					(const STANDARD_INFORMATION *)((unsigned char *)attr + 24U);
				uint32_t expected_length = number == FILE_Volume &&
					!windows_volume_profile ?
					offsetof(STANDARD_INFORMATION, v1_end) :
					offsetof(STANDARD_INFORMATION, v3_end);
				if (value_length != expected_length ||
					le32_to_cpu(standard->file_attributes) !=
					 (le32_to_cpu(FILE_ATTR_HIDDEN) |
					  le32_to_cpu(FILE_ATTR_SYSTEM)) ||
					(!windows_volume_profile && number == FILE_Volume &&
					 memcmp(standard->reserved12,
						 "\0\0\0\0\0\0\0\0\0\0\0\0", 12U)))
					goto invalid;
			} else if (type == 0x30U) {
				filename = attr;
			} else if (type == 0x70U) {
				const VOLUME_INFORMATION *information =
					(const VOLUME_INFORMATION *)((unsigned char *)attr + 24U);
				if (value_length != sizeof(*information) ||
					information->reserved || information->major_ver != 3U ||
					information->minor_ver != 1U ||
					(le16_to_cpu(information->flags) &
					 ~le16_to_cpu(VOLUME_FLAGS_MASK)))
					goto invalid;
			} else if (type == 0x80U && number == FILE_Volume &&
				value_length)
				goto invalid;
		} else {
			struct rh_bootstrap_stream *stream = type == 0xb0U ?
				&bitmap_stream : &data_stream;
			int mapping_status;

			if (type != 0x80U && type != 0xb0U)
				goto invalid;
			mapping_status = rh_bootstrap_mapping_pairs(attr, length,
				geometry, &runs, stream);
			if (mapping_status < 0)
				goto internal;
			if (!mapping_status)
				goto invalid;
		}
		index++;
		attr = (ATTR_RECORD *)((unsigned char *)attr + length);
	}
	if (!rh_bootstrap_runs_nonoverlapping(&runs))
		goto invalid;
	if (!filename || !rh_bootstrap_filename_valid(filename, names[number]))
		goto invalid;
	if (number == FILE_MFT) {
		uint64_t records = data_stream.data_size / geometry->mft_record_size;
		uint64_t required_bitmap = (records + 7U) / 8U;
		if (!data_stream.clusters || data_stream.first_lcn != geometry->mft_lcn ||
			data_stream.data_size % geometry->mft_record_size ||
			records < geometry->mirrored_records ||
			bitmap_stream.data_size < required_bitmap)
			goto invalid;
	} else if (number == FILE_MFTMirr) {
		uint64_t expected_size = (uint64_t)geometry->mirrored_records *
			geometry->mft_record_size;
		if (data_stream.first_lcn != geometry->mftmirr_lcn ||
			data_stream.data_size != expected_size ||
			data_stream.allocated_size != geometry->cluster_size)
			goto invalid;
	} else if (number == FILE_LogFile) {
		if (data_stream.data_size < 4U * geometry->index_record_size ||
			data_stream.data_size > RH_BOOTSTRAP_MAX_LOGFILE_SIZE ||
			data_stream.data_size != data_stream.allocated_size ||
			(data_stream.data_size & (geometry->index_record_size - 1U)))
			goto invalid;
	}
	free(runs.items);
	*fixed_out = fixed;
	return 1;
internal:
	free(runs.items);
	free(fixed);
	errno = ENOMEM;
	return -1;
invalid:
	free(runs.items);
	free(fixed);
	return 0;
}

int roothealth_bootstrap_mft_records_equal(const unsigned char *left,
		const unsigned char *right, uint32_t size)
{
	const MFT_RECORD *left_record;
	const MFT_RECORD *right_record;
	uint32_t used;
	uint16_t left_usa, right_usa, left_count, right_count;
	uint32_t i;

	if (!left || !right)
		return 0;
	left_record = (const MFT_RECORD *)left;
	right_record = (const MFT_RECORD *)right;
	used = le32_to_cpu(left_record->bytes_in_use);
	left_usa = le16_to_cpu(left_record->usa_ofs);
	right_usa = le16_to_cpu(right_record->usa_ofs);
	left_count = le16_to_cpu(left_record->usa_count);
	right_count = le16_to_cpu(right_record->usa_count);
	if (used != le32_to_cpu(right_record->bytes_in_use) || used > size ||
		left_usa != right_usa || left_count != right_count ||
		left_usa > used || (uint32_t)left_count * sizeof(le16) >
			used - left_usa)
		return 0;
	for (i = 0; i < used; i++) {
		if (i >= left_usa && i < left_usa +
			(uint32_t)left_count * sizeof(le16))
			continue;
		if (left[i] != right[i])
			return 0;
	}
	return 1;
}

static int rh_mirror_record_hash(const unsigned char *record, uint32_t size,
		unsigned char output[32])
{
	struct rh_hash_stream hash;

	rh_hash_stream_init(&hash);
	return rh_hash_stream_update(&hash, record, size) ||
		rh_hash_stream_final(&hash, output);
}

static void rh_mirror_record_difference(const unsigned char *left,
		const unsigned char *right, uint32_t size, uint32_t *first,
		uint32_t *count)
{
	const MFT_RECORD *left_record = (const MFT_RECORD *)left;
	const MFT_RECORD *right_record = (const MFT_RECORD *)right;
	uint32_t left_used = le32_to_cpu(left_record->bytes_in_use);
	uint32_t right_used = le32_to_cpu(right_record->bytes_in_use);
	uint32_t used = left_used > right_used ? left_used : right_used;
	uint16_t usa = le16_to_cpu(left_record->usa_ofs);
	uint16_t usa_count = le16_to_cpu(left_record->usa_count);
	uint32_t usa_end = (uint32_t)usa +
		(uint32_t)usa_count * sizeof(le16);
	uint32_t i;

	*first = 0;
	*count = 0;
	if (used > size)
		used = size;
	for (i = 0; i < used; i++) {
		if (i >= usa && i < usa_end)
			continue;
		if (i >= left_used || i >= right_used || left[i] != right[i]) {
			if (!*count)
				*first = i;
			(*count)++;
		}
	}
}

static int rh_volume_dirty_only_difference(const unsigned char *primary,
		const unsigned char *mirror, uint32_t size, int *primary_is_dirty)
{
	const MFT_RECORD *records[2] = {
		(const MFT_RECORD *)primary, (const MFT_RECORD *)mirror
	};
	uint32_t flag_offsets[2] = {0, 0};
	uint16_t flags[2] = {0, 0};
	uint16_t usa_offsets[2], usa_counts[2];
	uint32_t used[2], i;
	unsigned int side;
	uint16_t dirty = le16_to_cpu(VOLUME_IS_DIRTY);

	if (!primary || !mirror || !primary_is_dirty)
		return 0;
	for (side = 0; side < 2U; side++) {
		const unsigned char *bytes = side ? mirror : primary;
		const MFT_RECORD *record = records[side];
		uint32_t offset;

		used[side] = le32_to_cpu(record->bytes_in_use);
		usa_offsets[side] = le16_to_cpu(record->usa_ofs);
		usa_counts[side] = le16_to_cpu(record->usa_count);
		offset = le16_to_cpu(record->attrs_offset);
		if (used[side] > size || offset > used[side] - sizeof(le32))
			return 0;
		while (offset <= used[side] - sizeof(le32)) {
			const ATTR_RECORD *attribute =
				(const ATTR_RECORD *)(bytes + offset);
			uint32_t type = le32_to_cpu(attribute->type);
			uint32_t length, value_length;
			uint16_t value_offset;
			const VOLUME_INFORMATION *information;

			if (type == 0xffffffffU)
				break;
			length = le32_to_cpu(attribute->length);
			if (length < 24U || (length & 7U) || length > used[side] - offset)
				return 0;
			if (type != le32_to_cpu(AT_VOLUME_INFORMATION)) {
				offset += length;
				continue;
			}
			if (flag_offsets[side] || attribute->non_resident ||
					attribute->name_length)
				return 0;
			value_length = le32_to_cpu(attribute->value_length);
			value_offset = le16_to_cpu(attribute->value_offset);
			if (value_length != sizeof(*information) || value_offset < 24U ||
					value_offset > length || value_length > length - value_offset)
				return 0;
			information = (const VOLUME_INFORMATION *)
				(bytes + offset + value_offset);
			flag_offsets[side] = offset + value_offset +
				offsetof(VOLUME_INFORMATION, flags);
			flags[side] = le16_to_cpu(information->flags);
			offset += length;
		}
		if (!flag_offsets[side] || flag_offsets[side] > size - sizeof(le16))
			return 0;
	}
	if (used[0] != used[1] || usa_offsets[0] != usa_offsets[1] ||
			usa_counts[0] != usa_counts[1] ||
			flag_offsets[0] != flag_offsets[1] ||
			(flags[0] ^ flags[1]) != dirty)
		return 0;
	for (i = 0; i < used[0]; i++) {
		uint32_t usa_end = (uint32_t)usa_offsets[0] +
			(uint32_t)usa_counts[0] * sizeof(le16);
		if ((i >= usa_offsets[0] && i < usa_end) ||
				(i >= flag_offsets[0] && i < flag_offsets[0] + sizeof(le16)))
			continue;
		if (primary[i] != mirror[i])
			return 0;
	}
	*primary_is_dirty = !!(flags[0] & dirty);
	return 1;
}

static int rh_read_volume_label(struct rh_writer *writer,
		const struct rh_boot_geometry *geometry, char output[64])
{
	uint64_t offset = geometry->mft_lcn * geometry->cluster_size +
		(uint64_t)FILE_Volume * geometry->mft_record_size;
	unsigned char *raw = NULL;
	unsigned char *fixed = NULL;
	MFT_RECORD *record;
	ATTR_RECORD *attr;
	uint32_t used;
	int result = -1;

	output[0] = 0;
	if (offset > writer->device_size || geometry->mft_record_size >
		writer->device_size - offset)
		return -1;
	raw = malloc(geometry->mft_record_size);
	if (!raw)
		return -1;
	if (rh_writer_read(writer, offset, geometry->mft_record_size, raw) ||
		roothealth_bootstrap_mft_record_structure(raw,
			geometry->mft_record_size,
			FILE_Volume, geometry, &fixed) <= 0)
		goto out;
	record = (MFT_RECORD *)fixed;
	used = le32_to_cpu(record->bytes_in_use);
	attr = (ATTR_RECORD *)(fixed + le16_to_cpu(record->attrs_offset));
	while (attr->type != AT_END) {
		uint32_t length = le32_to_cpu(attr->length);
		if (attr->type == AT_VOLUME_NAME) {
			uint32_t bytes;
			uint16_t value_offset;
			const le16 *name;
			uint32_t i, chars;
			if (attr->non_resident)
				goto out;
			bytes = le32_to_cpu(attr->value_length);
			value_offset = le16_to_cpu(attr->value_offset);
			if ((bytes & 1) || bytes >= 2 * 64 ||
				value_offset < 24 || value_offset > length ||
				bytes > length - value_offset ||
				(unsigned char *)attr + value_offset + bytes > fixed + used)
				goto out;
			name = (const le16 *)((unsigned char *)attr + value_offset);
			chars = bytes / 2;
			for (i = 0; i < chars; i++) {
				uint16_t ch = le16_to_cpu(name[i]);
				if (ch < 0x20 || ch > 0x7e)
					goto out;
				output[i] = (char)ch;
			}
			output[chars] = 0;
			result = 0;
			goto out;
		}
		attr = (ATTR_RECORD *)((unsigned char *)attr + length);
	}
out:
	free(fixed);
	free(raw);
	return result;
}

static int rh_label_has_prefix(const char *label, const char *prefix)
{
	size_t length;

	if (!label || !prefix || !*prefix)
		return 0;
	length = strlen(prefix);
	return !strncmp(label, prefix, length) &&
		(!label[length] || label[length] == ' ');
}

int roothealth_refuse_mounted(const char *device_path)
{
	struct stat st;
	FILE *mounts;
	char line[4096];
	unsigned int wanted_major, wanted_minor;
	char holders_path[128];
	DIR *holders;
	struct dirent *entry;

	if (stat(device_path, &st))
		return -1;
	if (!S_ISBLK(st.st_mode))
		return 0;
	wanted_major = major(st.st_rdev);
	wanted_minor = minor(st.st_rdev);
	snprintf(holders_path, sizeof(holders_path),
		"/sys/dev/block/%u:%u/holders", wanted_major, wanted_minor);
	holders = opendir(holders_path);
	if (!holders && errno != ENOENT)
		return -1;
	if (holders) {
		while ((entry = readdir(holders)) != NULL) {
			if (strcmp(entry->d_name, ".") && strcmp(entry->d_name, "..")) {
				closedir(holders);
				errno = EBUSY;
				return 1;
			}
		}
		closedir(holders);
	}
	mounts = fopen("/proc/self/mountinfo", "re");
	if (!mounts)
		return -1;
	while (fgets(line, sizeof(line), mounts)) {
		unsigned int found_major, found_minor;
		if (sscanf(line, "%*u %*u %u:%u", &found_major,
				&found_minor) == 2 && found_major == wanted_major &&
			found_minor == wanted_minor) {
			fclose(mounts);
			errno = EBUSY;
			return 1;
		}
	}
	if (ferror(mounts)) {
		fclose(mounts);
		return -1;
	}
	fclose(mounts);
	return 0;
}

int roothealth_bootstrap_boot_plan(struct rh_writer *writer,
		uint64_t expected_serial, const char *expected_label_prefix,
		struct rh_identity_result *identity,
		struct rh_boot_result *boot_result)
{
	unsigned char primary[ROOTHEALTH_SUPPORTED_SECTOR_SIZE];
	unsigned char backup[ROOTHEALTH_SUPPORTED_SECTOR_SIZE];
	struct rh_boot_geometry primary_geometry = {0};
	struct rh_boot_geometry backup_geometry = {0};
	struct rh_boot_geometry *chosen;
	int primary_valid = 0, backup_valid = 0;
	int primary_structural, backup_structural;
	uint64_t backup_offset;

	if (!writer || !identity || !boot_result || !expected_serial)
		return RH_RESULT_INTERNAL;
	memset(identity, 0, sizeof(*identity));
	memset(boot_result, 0, sizeof(*boot_result));
	identity->expected_serial = expected_serial;
	if (expected_label_prefix && *expected_label_prefix &&
		strlen(expected_label_prefix) < sizeof(identity->expected_label))
		strcpy(identity->expected_label, expected_label_prefix);
	/*
	 * The repair profile has one exact physical-sector geometry.  A failed
	 * pre-write read is media/I/O failure, never evidence that the peer may be
	 * overwritten.  Reading a fixed 512-byte peer also avoids probing a corrupt
	 * boot sector into an attacker-selected backup offset.
	 */
	if (writer->device_size < 2U * ROOTHEALTH_SUPPORTED_SECTOR_SIZE ||
		writer->device_size > ROOTHEALTH_MAX_VOLUME_BYTES ||
		writer->device_size % ROOTHEALTH_SUPPORTED_SECTOR_SIZE)
		return RH_RESULT_UNSAFE;
	backup_offset = writer->device_size - ROOTHEALTH_SUPPORTED_SECTOR_SIZE;
	if (rh_writer_read(writer, 0, sizeof(primary), primary) ||
		rh_writer_read(writer, backup_offset, sizeof(backup), backup))
		return RH_RESULT_IO;
	primary_valid = roothealth_boot_sector_validate(primary, sizeof(primary),
		writer->device_size, &primary_geometry);
	backup_valid = roothealth_boot_sector_validate(backup, sizeof(backup),
		writer->device_size, &backup_geometry);
	primary_structural = primary_valid;
	backup_structural = backup_valid;
	if (primary_valid)
		identity->observed_primary_serial = primary_geometry.serial;
	if (backup_valid)
		identity->observed_backup_serial = backup_geometry.serial;
	identity->primary_boot_valid = primary_structural &&
		primary_geometry.serial == expected_serial;
	identity->backup_boot_valid = backup_structural &&
		backup_geometry.serial == expected_serial;
	boot_result->checked = 1;
	boot_result->primary_valid = identity->primary_boot_valid;
	boot_result->backup_valid = identity->backup_boot_valid;
	/*
	 * A structurally valid peer is an authority even when it is not the
	 * expected T1OS volume.  Never erase a conflicting valid boot sector.
	 */
	if (primary_structural && backup_structural) {
		if (memcmp(&primary_geometry, &backup_geometry,
				sizeof(primary_geometry)) ||
			memcmp(primary, backup, primary_geometry.sector_size))
			return RH_RESULT_UNSAFE;
		if (primary_geometry.serial != expected_serial)
			return RH_RESULT_WRONG_ROOT;
		primary_valid = backup_valid = 1;
	} else if (primary_structural) {
		if (primary_geometry.serial != expected_serial)
			return RH_RESULT_WRONG_ROOT;
		primary_valid = 1;
		backup_valid = 0;
	} else if (backup_structural) {
		if (backup_geometry.serial != expected_serial)
			return RH_RESULT_WRONG_ROOT;
		primary_valid = 0;
		backup_valid = 1;
	} else {
		return RH_RESULT_UNSAFE;
	}
	chosen = primary_valid ? &primary_geometry : &backup_geometry;
	if (chosen->sector_size != ROOTHEALTH_SUPPORTED_SECTOR_SIZE ||
		chosen->cluster_size != ROOTHEALTH_SUPPORTED_CLUSTER_SIZE ||
		chosen->mft_record_size != ROOTHEALTH_SUPPORTED_MFT_RECORD_SIZE ||
		chosen->index_record_size != ROOTHEALTH_SUPPORTED_INDEX_RECORD_SIZE ||
		writer->device_size > ROOTHEALTH_MAX_VOLUME_BYTES ||
		writer->device_size % ROOTHEALTH_SUPPORTED_SECTOR_SIZE ||
		writer->device_size / ROOTHEALTH_SUPPORTED_SECTOR_SIZE < 2 ||
		chosen->sector_count != writer->device_size /
			ROOTHEALTH_SUPPORTED_SECTOR_SIZE - 1) {
		boot_result->geometry = *chosen;
		return RH_RESULT_UNSAFE;
	}
	boot_result->geometry_supported = 1;
	/* Label and namespace identity are intentionally deferred until replay. */
	boot_result->geometry = *chosen;
	boot_result->backup_offset = backup_offset;
	if (primary_valid && !backup_valid) {
		if (rh_writer_plan(writer, RH_WRITE_BOOT_BACKUP,
				backup_offset,
				chosen->sector_size, primary))
			return errno == EIO ? RH_RESULT_IO : RH_RESULT_UNSAFE;
		boot_result->repaired_backup = 1;
	} else if (!primary_valid && backup_valid) {
		if (rh_writer_plan(writer, RH_WRITE_BOOT_PRIMARY, 0,
				chosen->sector_size, backup))
			return errno == EIO ? RH_RESULT_IO : RH_RESULT_UNSAFE;
		boot_result->repaired_primary = 1;
	}
	return RH_RESULT_OK;
}

struct rh_required_path {
	const char *path;
	int directory;
};

static int rh_identity_errno_result(int error)
{
	if (error == ENOMEM)
		return RH_RESULT_INTERNAL;
	if (error == EIO || error == ENXIO || error == ENODEV ||
		error == ESTALE)
		return RH_RESULT_IO;
	return RH_RESULT_UNSAFE;
}

static int rh_check_required_path(ntfs_volume *volume,
		const struct rh_required_path *required)
{
	ntfs_inode *inode;
	int is_directory;
	int error;

	errno = 0;
	inode = ntfs_pathname_to_inode(volume, NULL, required->path);
	if (!inode) {
		error = errno;
		if (error == ENOENT)
			return RH_RESULT_WRONG_ROOT;
		return rh_identity_errno_result(error);
	}
	is_directory = !!(inode->mrec->flags & MFT_RECORD_IS_DIRECTORY);
	if (ntfs_inode_close(inode))
		return RH_RESULT_IO;
	return is_directory == required->directory ? RH_RESULT_OK :
		RH_RESULT_WRONG_ROOT;
}

static int rh_check_forbidden_path(ntfs_volume *volume, const char *path)
{
	ntfs_inode *inode;
	int error;

	errno = 0;
	inode = ntfs_pathname_to_inode(volume, NULL, path);
	if (inode) {
		if (ntfs_inode_close(inode))
			return RH_RESULT_IO;
		return RH_RESULT_WRONG_ROOT;
	}
	error = errno;
	if (error == ENOENT)
		return RH_RESULT_OK;
	return rh_identity_errno_result(error);
}

static int rh_verify_namespace_identity_raw(ntfs_volume *volume,
		struct rh_writer *writer, struct rh_identity_result *identity)
{
	struct rh_raw_mft_census raw;
	struct rh_namespace_census namespace;
	int result = RH_RESULT_IO;

	memset(&raw, 0, sizeof(raw));
	memset(&namespace, 0, sizeof(namespace));
	if (rh_raw_mft_census_run(volume, writer, 1, &raw) ||
			rh_namespace_census_run(&raw, 1, &namespace) ||
			rh_namespace_check_t1os_identity(&raw, &namespace))
		goto out;
	identity->required_paths_checked =
		(uint32_t)namespace.identity_required_completed;
	identity->forbidden_paths_checked =
		(uint32_t)namespace.forbidden_root_names_expected;
	if (namespace.identity == RH_T1OS_IDENTITY_MATCH &&
			namespace.identity_required_completed ==
				namespace.identity_required_expected &&
			!namespace.forbidden_root_children_matched) {
		strcpy(identity->anchor,
			"serial+label-prefix+raw-namespace-census");
		result = RH_RESULT_OK;
	} else {
		result = namespace.identity == RH_T1OS_IDENTITY_MISSING ?
			RH_RESULT_WRONG_ROOT : RH_RESULT_UNSAFE;
	}
out:
	rh_namespace_census_release(&namespace);
	rh_raw_mft_census_release(&raw);
	return result;
}

static int roothealth_verify_namespace_identity_common(struct rh_writer *writer,
		const char *device_path, const struct rh_boot_geometry *geometry,
		uint64_t expected_serial, const char *expected_label_prefix,
		struct rh_identity_result *identity, int allow_full_fallback)
{
	static const struct rh_required_path required[] = {
		{ "the one", 1 },
		{ "the one/software/python/bin/python", 0 },
		{ "the one/build/GODDESS/GODDESS.py", 0 },
		{ "the one/build/drivers/driverserver.py", 0 },
		{ "the one/drivers/tools/modprobe", 0 },
		{ "the one/drivers/settings/policy.json", 0 },
		{ "the one/drivers/modules/module-manifest.sha256", 0 },
	};
	static const char *forbidden[] = {
		"bin", "dev", "etc", "home", "lib", "lib64", "mnt", "opt",
		"proc", "root", "run", "sbin", "srv", "sys", "tmp", "usr", "var",
	};
	struct rh_boot_geometry mirror_geometry;
	char primary_label[64] = {0};
	char mirror_label[64] = {0};
	ntfs_volume *volume = NULL;
	size_t i;
	int result = RH_RESULT_UNSAFE;
	int error, legacy_namespace_io = 0;

	if (!writer || !device_path || !*device_path || !geometry || !identity ||
		!expected_serial || geometry->serial != expected_serial ||
		!expected_label_prefix || !*expected_label_prefix)
		return RH_RESULT_INTERNAL;
	identity->prewrite_checked = 1;
	identity->prewrite_valid = 0;
	identity->required_paths_checked = 0;
	identity->forbidden_paths_checked = 0;
	if (rh_read_volume_label(writer, geometry, primary_label))
		return RH_RESULT_UNSAFE;
	mirror_geometry = *geometry;
	mirror_geometry.mft_lcn = geometry->mftmirr_lcn;
	if (rh_read_volume_label(writer, &mirror_geometry, mirror_label))
		return RH_RESULT_UNSAFE;
	if (strcmp(primary_label, mirror_label))
		return RH_RESULT_UNSAFE;
	strcpy(identity->observed_label, primary_label);
	if (!rh_label_has_prefix(primary_label, expected_label_prefix))
		return RH_RESULT_WRONG_ROOT;
	volume = ntfs_mount(device_path, NTFS_MNT_RDONLY | NTFS_MNT_FORENSIC |
		NTFS_MNT_FS_NO_REPAIR);
	if (!volume) {
		error = errno;
		return rh_identity_errno_result(error);
	}
	if (!NDevReadOnly(volume->dev)) {
		result = RH_RESULT_INTERNAL;
		goto out;
	}
	if (ntfs_volume_check_hiberfile(volume, 1) < 0) {
		error = errno;
		result = error == EPERM ? RH_RESULT_UNSAFE :
			rh_identity_errno_result(error);
		goto out;
	}
	for (i = 0; i < sizeof(required) / sizeof(required[0]); i++) {
		result = rh_check_required_path(volume, &required[i]);
		if (result != RH_RESULT_OK) {
			if (result == RH_RESULT_IO) {
				legacy_namespace_io = 1;
				break;
			}
			goto out;
		}
		identity->required_paths_checked++;
	}
	for (i = 0; !legacy_namespace_io &&
			i < sizeof(forbidden) / sizeof(forbidden[0]); i++) {
		result = rh_check_forbidden_path(volume, forbidden[i]);
		if (result != RH_RESULT_OK) {
			if (result == RH_RESULT_IO) {
				legacy_namespace_io = 1;
				break;
			}
			goto out;
		}
		identity->forbidden_paths_checked++;
	}
	if (legacy_namespace_io) {
		if (!allow_full_fallback) {
			result = RH_RESULT_UNSAFE;
			goto out;
		}
		result = rh_verify_namespace_identity_raw(volume, writer, identity);
		if (result != RH_RESULT_OK)
			goto out;
	}
	identity->prewrite_valid = 1;
	if (!legacy_namespace_io)
		strcpy(identity->anchor, "serial+label-prefix+namespace");
	result = RH_RESULT_OK;
out:
	if (ntfs_umount(volume, FALSE) && result == RH_RESULT_OK)
		result = RH_RESULT_IO;
	if (result != RH_RESULT_OK)
		identity->prewrite_valid = 0;
	return result;
}

int roothealth_verify_namespace_identity(struct rh_writer *writer,
		const char *device_path, const struct rh_boot_geometry *geometry,
		uint64_t expected_serial, const char *expected_label_prefix,
		struct rh_identity_result *identity)
{
	return roothealth_verify_namespace_identity_common(writer, device_path,
		geometry, expected_serial, expected_label_prefix, identity, 1);
}

int roothealth_verify_namespace_identity_bounded(struct rh_writer *writer,
		const char *device_path, const struct rh_boot_geometry *geometry,
		uint64_t expected_serial, const char *expected_label_prefix,
		struct rh_identity_result *identity)
{
	return roothealth_verify_namespace_identity_common(writer, device_path,
		geometry, expected_serial, expected_label_prefix, identity, 0);
}

int roothealth_mftmirr_plan(struct rh_writer *writer,
		const struct rh_boot_geometry *geometry,
		struct rh_mirror_result *result)
{
	unsigned char *primary = NULL, *mirror = NULL;
	unsigned char *primary_fixed = NULL, *mirror_fixed = NULL;
	uint32_t i;
	int status = RH_RESULT_OK;

	if (!writer || !geometry || !result || !geometry->mft_record_size ||
		!geometry->mirrored_records || geometry->mirrored_records >
			ROOTHEALTH_MAX_MIRRORED_RECORDS)
		return RH_RESULT_INTERNAL;
	memset(result, 0, sizeof(*result));
	result->checked = 1;
	primary = malloc(geometry->mft_record_size);
	mirror = malloc(geometry->mft_record_size);
	if (!primary || !mirror) {
		status = RH_RESULT_INTERNAL;
		goto out;
	}
	for (i = 0; i < geometry->mirrored_records; i++) {
		typeof(result->records[0]) *observation = &result->records[i];
		uint64_t primary_offset = geometry->mft_lcn *
			geometry->cluster_size +
			(uint64_t)i * geometry->mft_record_size;
		uint64_t mirror_offset = geometry->mftmirr_lcn *
			geometry->cluster_size +
			(uint64_t)i * geometry->mft_record_size;
		int primary_valid, mirror_valid;

		if (primary_offset > writer->device_size || mirror_offset >
			writer->device_size || geometry->mft_record_size >
			writer->device_size - primary_offset ||
			geometry->mft_record_size > writer->device_size - mirror_offset ||
			rh_writer_read(writer, primary_offset,
				geometry->mft_record_size, primary) ||
			rh_writer_read(writer, mirror_offset,
				geometry->mft_record_size, mirror)) {
			status = RH_RESULT_IO;
			goto out;
		}
		observation->checked = 1;
		if (!rh_mirror_record_hash(primary, geometry->mft_record_size,
				observation->primary_sha256) &&
				!rh_mirror_record_hash(mirror, geometry->mft_record_size,
					observation->mirror_sha256))
			observation->hashes_known = 1;
		primary_valid = roothealth_bootstrap_mft_record_structure(primary,
			geometry->mft_record_size, i, geometry, &primary_fixed);
		mirror_valid = roothealth_bootstrap_mft_record_structure(mirror,
			geometry->mft_record_size, i, geometry, &mirror_fixed);
		if (primary_valid < 0 || mirror_valid < 0) {
			status = RH_RESULT_INTERNAL;
			goto out;
		}
		result->records_checked++;
		observation->primary_valid = primary_valid;
		observation->mirror_valid = mirror_valid;
		if (primary_valid && mirror_valid) {
			int primary_is_dirty = 0;

			observation->equal_known = 1;
			observation->equal = roothealth_bootstrap_mft_records_equal(
				primary_fixed, mirror_fixed, geometry->mft_record_size);
			if (!observation->equal) {
				/* A power cut while clearing the mirrored dirty flag can leave
				 * two otherwise identical, structurally valid record-3 peers.
				 * Dirty is the conservative authority: roll the clean peer back
				 * to dirty, then the bounded boot pass can retry the pair. */
				if (i == FILE_Volume && rh_volume_dirty_only_difference(
						primary_fixed, mirror_fixed,
						geometry->mft_record_size, &primary_is_dirty)) {
					if (primary_is_dirty) {
						if (rh_writer_plan(writer, RH_WRITE_MFT_MIRROR,
								mirror_offset, geometry->mft_record_size,
								primary)) {
							status = RH_RESULT_IO;
							goto out;
						}
						result->mirror_repaired++;
					} else {
						if (rh_writer_plan(writer, RH_WRITE_MFT_PRIMARY,
								primary_offset, geometry->mft_record_size,
								mirror)) {
							status = RH_RESULT_IO;
							goto out;
						}
						result->primary_repaired++;
					}
					goto peer_done;
				}
				rh_mirror_record_difference(primary_fixed, mirror_fixed,
					geometry->mft_record_size,
					&observation->first_difference_offset,
					&observation->differing_bytes);
				observation->first_difference_known =
					observation->differing_bytes != 0;
				result->ambiguous_records++;
				result->failure_kind =
					RH_MIRROR_FAILURE_VALID_DIVERGENCE;
				result->failure_record_known = 1;
				result->failure_record = i;
				status = RH_RESULT_UNSAFE;
				goto out;
			}
		} else if (primary_valid) {
			if (rh_writer_plan(writer, RH_WRITE_MFT_MIRROR,
					mirror_offset, geometry->mft_record_size,
					primary)) {
				status = RH_RESULT_IO;
				goto out;
			}
			result->mirror_repaired++;
		} else if (mirror_valid) {
			if (rh_writer_plan(writer, RH_WRITE_MFT_PRIMARY,
					primary_offset, geometry->mft_record_size,
					mirror)) {
				status = RH_RESULT_IO;
				goto out;
			}
			result->primary_repaired++;
		} else {
			result->unsupported_records++;
			result->failure_kind = RH_MIRROR_FAILURE_BOTH_UNSUPPORTED;
			result->failure_record_known = 1;
			result->failure_record = i;
			status = RH_RESULT_UNSAFE;
			goto out;
		}
	peer_done:
		free(primary_fixed);
		free(mirror_fixed);
		primary_fixed = NULL;
		mirror_fixed = NULL;
	}
out:
	free(primary_fixed);
	free(mirror_fixed);
	free(primary);
	free(mirror);
	return status;
}
