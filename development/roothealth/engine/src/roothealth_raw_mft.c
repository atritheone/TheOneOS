/* ROOTHEALTH_REPAIR_ROLE(DIAGNOSTIC) ROOTHEALTH_IO_ROLE(PLANNER) */
#include "config.h"

#include <errno.h>
#include <limits.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include "attrib.h"
#include "endians.h"
#include "layout.h"
#include "mft.h"
#include "roothealth_hash_stream.h"
#include "roothealth_raw_mft.h"
#include "roothealth_census_device.h"
#include "roothealth_write.h"
#include "unistr.h"
#include "volume.h"

/* Pinned d4 and the NTFS inode/volume contract enforce this format limit. */
#define RH_RAW_ATTR_LIST_MAX UINT64_C(0x40000)
#define RH_RAW_HASH_HEADER_BYTES 320U
#define RH_RAW_HASH_SLOT_BYTES 64U
#define RH_RAW_HASH_ATTRIBUTE_BYTES 224U
#define RH_RAW_HASH_RUN_BYTES 40U
#define RH_RAW_HASH_FILE_NAME_BYTES 96U
#define RH_RAW_HASH_LIST_BYTES 88U
#define RH_RAW_HASH_LAYOUT_BYTES 192U

static int rh_all_zero(const unsigned char *bytes, size_t length)
{
	size_t i;

	for (i = 0; i < length; i++)
		if (bytes[i])
			return 0;
	return 1;
}

static uint16_t rh_raw_get_u16le(const unsigned char *bytes)
{
	return (uint16_t)bytes[0] | (uint16_t)bytes[1] << 8;
}

static uint32_t rh_raw_get_u32le(const unsigned char *bytes)
{
	return (uint32_t)bytes[0] | (uint32_t)bytes[1] << 8 |
		(uint32_t)bytes[2] << 16 | (uint32_t)bytes[3] << 24;
}

/*
 * libntfs may cache or normalize an MFT record while resolving namespace
 * paths.  The complete census must still prove the update-sequence framing
 * from the raw $MFT stream itself, otherwise an earlier diagnostic read can
 * hide an on-disk torn sector from the later structural pass.
 */
static int rh_raw_record_framing_valid(const ntfs_volume *volume,
		const unsigned char *record)
{
	uint16_t usa_offset, usa_count, usn, sector;

	if (!volume || !record || volume->sector_size < 2U ||
			volume->mft_record_size < volume->sector_size ||
			volume->mft_record_size % volume->sector_size)
		return 0;
	if (rh_all_zero(record, volume->mft_record_size))
		return 1;
	if (rh_raw_get_u32le(record) != le32_to_cpu(magic_FILE))
		return 0;
	usa_offset = rh_raw_get_u16le(record + 4U);
	usa_count = rh_raw_get_u16le(record + 6U);
	if (usa_offset < sizeof(NTFS_RECORD) ||
			usa_count != volume->mft_record_size / volume->sector_size + 1U ||
			usa_offset > volume->mft_record_size ||
			(uint32_t)usa_count * 2U > volume->mft_record_size - usa_offset)
		return 0;
	usn = rh_raw_get_u16le(record + usa_offset);
	if (!usn)
		return 0;
	for (sector = 1U; sector < usa_count; sector++) {
		size_t trailer = (size_t)sector * volume->sector_size - 2U;

		if (rh_raw_get_u16le(record + trailer) != usn)
			return 0;
	}
	return 1;
}

/*
 * A Windows-grown $MFT can contain an initialized tail whose storage is
 * canonically zero while the corresponding $MFT bitmap bits remain clear.
 * These are valid free slots, not unreadable FILE records.  Keep the
 * exception deliberately narrow: both the complete raw record and its
 * allocation bit must be readable, the bit must be clear, and every byte of
 * the record must be zero.
 */
static int rh_zero_initialized_free_slot(ntfs_volume *volume,
		uint64_t record_number, unsigned char *record)
{
	unsigned char bitmap;
	uint64_t record_offset, bitmap_offset;

	if (!volume || !volume->mft_na || !volume->mftbmp_na || !record ||
			record_number > INT64_MAX / volume->mft_record_size)
		return 0;
	record_offset = record_number * (uint64_t)volume->mft_record_size;
	bitmap_offset = record_number >> 3;
	if (bitmap_offset > INT64_MAX ||
			ntfs_attr_pread(volume->mft_na, (s64)record_offset,
				volume->mft_record_size, record) !=
				(s64)volume->mft_record_size ||
			ntfs_attr_pread(volume->mftbmp_na, (s64)bitmap_offset,
				1, &bitmap) != 1 ||
			(bitmap & (unsigned char)(1U << (record_number & 7U))))
		return 0;
	return rh_all_zero(record, volume->mft_record_size);
}

static int rh_opaque_record_compare(const void *left_pointer,
		const void *right_pointer)
{
	const struct rh_raw_opaque_slot_evidence *left = left_pointer;
	const struct rh_raw_opaque_slot_evidence *right = right_pointer;

	if (left->record == right->record)
		return 0;
	return left->record < right->record ? -1 : 1;
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

	if (count < 8U && (bytes[count - 1U] & 0x80U))
		value |= UINT64_MAX << (count * 8U);
	return (int64_t)value;
}

static struct rh_raw_mft_ref rh_ref_from_le(leMFT_REF input)
{
	uint64_t value = le64_to_cpu(input);
	struct rh_raw_mft_ref result;

	result.record = value & UINT64_C(0x0000ffffffffffff);
	result.sequence = (uint16_t)(value >> 48);
	return result;
}

static int rh_u64_add(uint64_t first, uint64_t second, uint64_t *result)
{
	if (first > UINT64_MAX - second)
		return -1;
	*result = first + second;
	return 0;
}

static int rh_s64_add(int64_t first, int64_t second, int64_t *result)
{
	if ((second > 0 && first > INT64_MAX - second) ||
			(second < 0 && first < INT64_MIN - second))
		return -1;
	*result = first + second;
	return 0;
}

static int rh_grow_array(void **buffer, size_t *capacity, size_t needed,
		size_t element_size)
{
	size_t next;
	void *grown;

	if (needed <= *capacity)
		return 0;
	next = *capacity ? *capacity : 32U;
	while (next < needed) {
		if (next > SIZE_MAX / 2U) {
			errno = EOVERFLOW;
			return -1;
		}
		next *= 2U;
	}
	if (next > SIZE_MAX / element_size) {
		errno = EOVERFLOW;
		return -1;
	}
	grown = realloc(*buffer, next * element_size);
	if (!grown)
		return -1;
	*buffer = grown;
	*capacity = next;
	return 0;
}

static int rh_arena_append(unsigned char **arena, size_t *size,
		size_t *capacity, const void *bytes, size_t length, size_t *offset)
{
	if (length > SIZE_MAX - *size ||
			rh_grow_array((void **)arena, capacity, *size + length, 1U))
		return -1;
	*offset = *size;
	if (length)
		memcpy(*arena + *size, bytes, length);
	*size += length;
	return 0;
}

static int rh_append_attribute(struct rh_raw_mft_census *census,
		const struct rh_raw_attribute *attribute, size_t *index)
{
	if (rh_grow_array((void **)&census->attributes,
			&census->attribute_capacity, census->attribute_count + 1U,
			sizeof(*census->attributes)))
		return -1;
	*index = census->attribute_count;
	census->attributes[census->attribute_count++] = *attribute;
	return 0;
}

static int rh_append_run(struct rh_raw_mft_census *census,
		const struct rh_raw_run *run)
{
	if (rh_grow_array((void **)&census->runs, &census->run_capacity,
			census->run_count + 1U, sizeof(*census->runs)))
		return -1;
	census->runs[census->run_count++] = *run;
	return 0;
}

static int rh_append_file_name(struct rh_raw_mft_census *census,
		const struct rh_raw_file_name *file_name)
{
	if (rh_grow_array((void **)&census->file_names,
			&census->file_name_capacity, census->file_name_count + 1U,
			sizeof(*census->file_names)))
		return -1;
	census->file_names[census->file_name_count++] = *file_name;
	return 0;
}

static int rh_append_list_entry(struct rh_raw_mft_census *census,
		const struct rh_raw_attr_list_entry *entry)
{
	if (rh_grow_array((void **)&census->list_entries,
			&census->list_entry_capacity, census->list_entry_count + 1U,
			sizeof(*census->list_entries)))
		return -1;
	census->list_entries[census->list_entry_count++] = *entry;
	return 0;
}

static int rh_append_layout_candidate(struct rh_raw_mft_census *census,
		enum rh_raw_layout_reason reason,
		struct rh_raw_mft_ref owner, struct rh_raw_mft_ref storage,
		uint32_t attribute_type, uint16_t attribute_instance,
		uint32_t logical_offset, const unsigned char *before,
		const unsigned char *replacement, uint32_t length)
{
	static const unsigned char zeros[1024];
	struct rh_raw_layout_candidate candidate;
	unsigned char canonical_record[1024];
	const unsigned char *logical_record;
	size_t i;

	if (!length || length > sizeof(zeros) || !before ||
			(replacement && length > sizeof(candidate.replacement)) ||
			logical_offset > 1024U || length > 1024U - logical_offset) {
		errno = EINVAL;
		return -1;
	}
	if (rh_grow_array((void **)&census->layout_candidates,
			&census->layout_candidate_capacity,
			census->layout_candidate_count + 1U,
			sizeof(*census->layout_candidates)))
		return -1;
	logical_record = before - logical_offset;
	memcpy(canonical_record, logical_record, sizeof(canonical_record));
	for (i = 0; i < census->layout_candidate_count; i++) {
		const struct rh_raw_layout_candidate *prior =
			&census->layout_candidates[i];
		uint32_t prior_end, current_end;

		if (prior->storage.record != storage.record ||
				prior->storage.sequence != storage.sequence)
			continue;
		prior_end = prior->logical_offset + prior->length;
		current_end = logical_offset + length;
		if (prior->logical_offset < current_end && logical_offset < prior_end) {
			errno = EIO;
			return -1;
		}
		if (prior->replacement_length) {
			if (prior->replacement_length != prior->length) {
				errno = EIO;
				return -1;
			}
			memcpy(canonical_record + prior->logical_offset,
				prior->replacement, prior->replacement_length);
		} else {
			memset(canonical_record + prior->logical_offset, 0,
				prior->length);
		}
	}
	memset(&candidate, 0, sizeof(candidate));
	candidate.reason = reason;
	candidate.owner = owner;
	candidate.storage = storage;
	candidate.attribute_type = attribute_type;
	candidate.attribute_instance = attribute_instance;
	candidate.logical_offset = logical_offset;
	candidate.length = length;
	rh_sha256(canonical_record + logical_offset, length, candidate.before_hash);
	rh_sha256(replacement ? replacement : zeros, length, candidate.after_hash);
	rh_sha256(canonical_record, sizeof(canonical_record),
		candidate.logical_record_before_hash);
	if (replacement) {
		candidate.replacement_length = (uint8_t)length;
		memcpy(candidate.replacement, replacement, length);
		memcpy(canonical_record + logical_offset, replacement, length);
	} else {
		memset(canonical_record + logical_offset, 0, length);
	}
	rh_sha256(canonical_record, sizeof(canonical_record),
		candidate.logical_record_after_hash);
	census->layout_candidates[census->layout_candidate_count++] = candidate;
	return 0;
}

static int rh_append_zero_layout_candidate(struct rh_raw_mft_census *census,
		enum rh_raw_layout_reason reason,
		struct rh_raw_mft_ref owner, struct rh_raw_mft_ref storage,
		uint32_t attribute_type, uint16_t attribute_instance,
		uint32_t logical_offset, const unsigned char *before, uint32_t length)
{
	return rh_append_layout_candidate(census, reason, owner, storage,
		attribute_type, attribute_instance, logical_offset, before, NULL,
		length);
}

static int rh_attribute_type_valid(const ATTR_RECORD *attribute)
{
	uint32_t type = le32_to_cpu(attribute->type);

	return ntfs_is_valid_attr_type(attribute) ||
		(type >= 0x1000U && type < 0xffffffffU);
}

static int rh_attribute_name(const ATTR_RECORD *attribute, uint32_t length,
		uint32_t minimum, struct rh_raw_mft_census *census,
		size_t *name_offset)
{
	uint32_t offset = le16_to_cpu(attribute->name_offset);
	uint32_t bytes = (uint32_t)attribute->name_length * 2U;

	if (!attribute->name_length) {
		if (offset && (offset < minimum || offset > length))
			return -1;
		return rh_arena_append(&census->name_arena,
			&census->name_arena_size, &census->name_arena_capacity,
			NULL, 0, name_offset);
	}
	if (offset < minimum || offset > length || bytes > length - offset)
		return -1;
	return rh_arena_append(&census->name_arena,
		&census->name_arena_size, &census->name_arena_capacity,
		(const unsigned char *)attribute + offset, bytes, name_offset);
}

static int rh_name_equal(const struct rh_raw_mft_census *census,
		size_t left_offset, uint16_t left_length,
		size_t right_offset, uint16_t right_length)
{
	return left_length == right_length &&
		(!left_length || !memcmp(census->name_arena + left_offset,
			census->name_arena + right_offset, (size_t)left_length * 2U));
}

static int rh_attribute_name_ascii(const struct rh_raw_mft_census *census,
		const struct rh_raw_attribute *attribute, const char *name)
{
	size_t length = strlen(name), i;
	const unsigned char *bytes;

	if (attribute->name_length != length)
		return 0;
	bytes = census->name_arena + attribute->name_offset;
	for (i = 0; i < length; i++)
		if (bytes[i * 2U] != (unsigned char)name[i] || bytes[i * 2U + 1U])
			return 0;
	return 1;
}

static int rh_resident_only_type(uint32_t type)
{
	return type == le32_to_cpu(AT_STANDARD_INFORMATION) ||
		type == le32_to_cpu(AT_FILE_NAME) ||
		type == le32_to_cpu(AT_OBJECT_ID) ||
		type == le32_to_cpu(AT_VOLUME_NAME) ||
		type == le32_to_cpu(AT_VOLUME_INFORMATION) ||
		type == le32_to_cpu(AT_INDEX_ROOT) ||
		type == le32_to_cpu(AT_REPARSE_POINT) ||
		type == le32_to_cpu(AT_EA_INFORMATION);
}

static int rh_attribute_order_compare(const struct rh_raw_mft_census *census,
		const struct rh_raw_attribute *left,
		const struct rh_raw_attribute *right, const ntfschar *upcase,
		uint32_t upcase_length)
{
	const unsigned char *left_value, *right_value;
	size_t compared;
	int comparison;

	if (left->type < right->type)
		return -1;
	if (left->type > right->type)
		return 1;
	if (!left->name_length && right->name_length)
		return -1;
	if (left->name_length && !right->name_length)
		return 1;
	if (left->name_length) {
		comparison = ntfs_names_full_collate(
			(const ntfschar *)(census->name_arena + left->name_offset),
			left->name_length,
			(const ntfschar *)(census->name_arena + right->name_offset),
			right->name_length, CASE_SENSITIVE, upcase, upcase_length);
		if (comparison)
			return comparison;
	}
	if (left->nonresident != right->nonresident)
		return left->nonresident ? 1 : -1;
	if (left->nonresident) {
		if (left->lowest_vcn < right->lowest_vcn)
			return -1;
		if (left->lowest_vcn > right->lowest_vcn)
			return 1;
		return 0;
	}
	compared = left->value_length < right->value_length ?
		left->value_length : right->value_length;
	comparison = 0;
	if (compared) {
		left_value = census->value_arena + left->value_arena_offset;
		right_value = census->value_arena + right->value_arena_offset;
		comparison = memcmp(left_value, right_value, compared);
	}
	if (comparison)
		return comparison;
	if (left->value_length < right->value_length)
		return -1;
	if (left->value_length > right->value_length)
		return 1;
	return 0;
}

static int rh_decode_mapping_pairs(ntfs_volume *volume,
		const ATTR_RECORD *attribute, uint32_t attribute_length,
		struct rh_raw_mft_census *census, size_t attribute_index,
		struct rh_raw_attribute *output, int allow_virtual_sparse)
{
	const unsigned char *base = (const unsigned char *)attribute;
	const unsigned char *cursor, *end;
	uint32_t mapping_offset = le16_to_cpu(attribute->mapping_pairs_offset);
	int64_t lowest = sle64_to_cpu(attribute->lowest_vcn);
	int64_t highest = sle64_to_cpu(attribute->highest_vcn);
	int64_t vcn, lcn = 0;
	uint16_t flags = le16_to_cpu(attribute->flags);
	uint16_t sparse_or_compressed = le16_to_cpu(ATTR_IS_SPARSE) |
		le16_to_cpu(ATTR_IS_COMPRESSED);
	int terminated = 0;

	if (!attribute->non_resident || mapping_offset < 64U ||
			mapping_offset >= attribute_length || lowest < 0 ||
			highest < lowest - 1) {
		errno = EIO;
		return -1;
	}
	cursor = base + mapping_offset;
	end = base + attribute_length;
	vcn = lowest;
	output->run_first = census->run_count;
	while (cursor < end) {
		struct rh_raw_run run;
		unsigned int length_bytes, offset_bytes;
		uint64_t run_length, run_end;
		int64_t delta, next_lcn;

		if (!*cursor) {
			terminated = 1;
			cursor++;
			break;
		}
		length_bytes = *cursor & 15U;
		offset_bytes = *cursor >> 4;
		cursor++;
		if (!length_bytes || length_bytes > 8U || offset_bytes > 8U ||
				(size_t)(end - cursor) <
				(size_t)length_bytes + offset_bytes) {
			errno = EIO;
			return -1;
		}
		run_length = rh_get_unsigned_le(cursor, length_bytes);
		cursor += length_bytes;
		if (!run_length || run_length > INT64_MAX || vcn < 0 ||
				rh_u64_add((uint64_t)vcn, run_length, &run_end) ||
				run_end > (uint64_t)INT64_MAX) {
			errno = EIO;
			return -1;
		}
		memset(&run, 0, sizeof(run));
		run.attribute_index = attribute_index;
		run.vcn = vcn;
		run.length = run_length;
		if (!offset_bytes) {
			if (!(flags & sparse_or_compressed) && !allow_virtual_sparse) {
				errno = EIO;
				return -1;
			}
			run.sparse = 1;
			run.lcn = -1;
		} else {
			delta = rh_get_signed_le(cursor, offset_bytes);
			cursor += offset_bytes;
			if (rh_s64_add(lcn, delta, &next_lcn) || next_lcn < 0 ||
					(uint64_t)next_lcn >= (uint64_t)volume->nr_clusters ||
					run_length > (uint64_t)volume->nr_clusters -
						(uint64_t)next_lcn) {
				errno = EIO;
				return -1;
			}
			lcn = next_lcn;
			run.lcn = lcn;
		}
		if (rh_append_run(census, &run))
			return -1;
		vcn = (int64_t)run_end;
	}
	if (!terminated ||
			(highest >= lowest && (highest == INT64_MAX ||
			 vcn != (int64_t)((uint64_t)highest + 1U))) ||
			(highest == lowest - 1 && vcn != lowest)) {
		errno = EIO;
		return -1;
	}
	/* Bytes after the first terminator are opaque producer slack. */
	output->run_count = census->run_count - output->run_first;
	return 0;
}

static int rh_parse_file_name(const struct rh_raw_attribute *parsed,
		struct rh_raw_mft_census *census,
		struct rh_raw_mft_ref initial_owner)
{
	const unsigned char *value;
	const FILE_NAME_ATTR *name;
	struct rh_raw_file_name result;
	uint32_t exact_length;

	if (parsed->nonresident || parsed->name_length ||
			parsed->value_length < offsetof(FILE_NAME_ATTR, file_name)) {
		errno = EIO;
		return -1;
	}
	value = census->value_arena + parsed->value_arena_offset;
	name = (const FILE_NAME_ATTR *)value;
	exact_length = (uint32_t)offsetof(FILE_NAME_ATTR, file_name) +
		(uint32_t)name->file_name_length * 2U;
	if (!name->file_name_length ||
			name->file_name_type > FILE_NAME_WIN32_AND_DOS ||
			parsed->value_length != exact_length) {
		errno = EIO;
		return -1;
	}
	memset(&result, 0, sizeof(result));
	result.owner = initial_owner;
	result.storage = parsed->storage;
	result.parent = rh_ref_from_le(name->parent_directory);
	result.attribute_instance = parsed->instance;
	result.record_value_offset = parsed->record_offset + parsed->value_offset;
	result.name_namespace = name->file_name_type;
	result.name_length = name->file_name_length;
	result.value_length = parsed->value_length;
	result.value_arena_offset = parsed->value_arena_offset;
	memcpy(result.value_hash, parsed->value_hash,
		sizeof(result.value_hash));
	/* Parent/cached metadata identify one logical link.  The final name
	 * length, namespace, and UTF-16 spelling distinguish the optional DOS
	 * and WIN32 attribute pair for that same logical link. */
	rh_sha256(value, offsetof(FILE_NAME_ATTR, file_name_length),
		result.logical_link_hash);
	if (!result.parent.sequence ||
			rh_arena_append(&census->name_arena, &census->name_arena_size,
			&census->name_arena_capacity, name->file_name,
			(size_t)name->file_name_length * 2U, &result.name_offset) ||
			rh_append_file_name(census, &result)) {
		if (!errno)
			errno = EIO;
		return -1;
	}
	return 0;
}

static int rh_parse_attribute(ntfs_volume *volume, const unsigned char *record,
		uint32_t record_offset, uint32_t record_remaining,
		struct rh_raw_mft_census *census, struct rh_raw_mft_ref storage,
		struct rh_raw_mft_ref owner, size_t *attribute_index)
{
	const ATTR_RECORD *attribute =
		(const ATTR_RECORD *)(record + record_offset);
	struct rh_raw_attribute parsed;
	uint32_t length, minimum, data_offset, data_length, name_end;
	size_t run_checkpoint = census->run_count;
	size_t value_checkpoint = census->value_arena_size;
	size_t name_checkpoint = census->name_arena_size;
	size_t layout_checkpoint = census->layout_candidate_count;
	uint16_t flags;

	if (record_remaining < 16U) {
		errno = EIO;
		return -1;
	}
	memset(&parsed, 0, sizeof(parsed));
	length = le32_to_cpu(attribute->length);
	flags = le16_to_cpu(attribute->flags);
	minimum = attribute->non_resident ?
		(flags & (le16_to_cpu(ATTR_IS_COMPRESSED) |
		 le16_to_cpu(ATTR_IS_SPARSE)) ? 72U : 64U) : 24U;
	if (attribute->non_resident > 1U || length < minimum || (length & 7U) ||
			length > record_remaining || !rh_attribute_type_valid(attribute) ||
			(flags & (uint16_t)~(le16_to_cpu(ATTR_IS_COMPRESSED) |
			 le16_to_cpu(ATTR_IS_SPARSE) |
			 le16_to_cpu(ATTR_IS_ENCRYPTED))) ||
			(!attribute->non_resident &&
			 (flags & (uint16_t)~le16_to_cpu(ATTR_IS_COMPRESSED))) ||
			(attribute->non_resident && rh_resident_only_type(
				le32_to_cpu(attribute->type))) ||
			(attribute->non_resident &&
			 (flags & (le16_to_cpu(ATTR_IS_COMPRESSED) |
			  le16_to_cpu(ATTR_IS_SPARSE) |
			  le16_to_cpu(ATTR_IS_ENCRYPTED))) &&
			 le32_to_cpu(attribute->type) != le32_to_cpu(AT_DATA)) ||
			((flags & le16_to_cpu(ATTR_IS_ENCRYPTED)) &&
			 (flags & (le16_to_cpu(ATTR_IS_COMPRESSED) |
			  le16_to_cpu(ATTR_IS_SPARSE)))) ||
			((flags & le16_to_cpu(ATTR_IS_COMPRESSED)) &&
			 (flags & le16_to_cpu(ATTR_IS_SPARSE)))) {
		errno = EIO;
		return -1;
	}
	parsed.owner = owner;
	parsed.storage = storage;
	parsed.type = le32_to_cpu(attribute->type);
	parsed.instance = le16_to_cpu(attribute->instance);
	parsed.flags = flags;
	parsed.record_offset = record_offset;
	parsed.record_length = length;
	parsed.name_record_offset = le16_to_cpu(attribute->name_offset);
	parsed.nonresident = attribute->non_resident;
	parsed.name_length = attribute->name_length;
	if (rh_attribute_name(attribute, length, minimum, census,
			&parsed.name_offset)) {
		errno = EIO;
		goto rollback;
	}
	name_end = attribute->name_length ?
		le16_to_cpu(attribute->name_offset) +
		(uint32_t)attribute->name_length * 2U :
		(parsed.name_record_offset ? parsed.name_record_offset : minimum);
	if (parsed.name_record_offset > minimum &&
			!rh_all_zero((const unsigned char *)attribute + minimum,
				parsed.name_record_offset - minimum) &&
			rh_append_zero_layout_candidate(census,
				RH_RAW_LAYOUT_ATTRIBUTE_NAME_PADDING,
				parsed.owner, parsed.storage, parsed.type, parsed.instance,
				record_offset + minimum,
				(const unsigned char *)attribute + minimum,
				parsed.name_record_offset - minimum))
		goto rollback;
	if (!attribute->non_resident && flags &&
			!(parsed.type == le32_to_cpu(AT_DATA) ||
			 (parsed.type == le32_to_cpu(AT_INDEX_ROOT) &&
			  rh_attribute_name_ascii(census, &parsed, "$I30")))) {
		errno = EIO;
		goto rollback;
	}
	if (attribute->non_resident) {
		int virtual_badclus;

		data_offset = le16_to_cpu(attribute->mapping_pairs_offset);
		parsed.mapping_pairs_offset = (uint16_t)data_offset;
		if (data_offset < minimum || (data_offset & 7U) ||
				data_offset < name_end || data_offset >= length) {
			errno = EIO;
			goto rollback;
		}
		if (!rh_all_zero(attribute->reserved1,
				sizeof(attribute->reserved1)) &&
				rh_append_zero_layout_candidate(census,
					RH_RAW_LAYOUT_NONRESIDENT_HEADER_RESERVED,
					parsed.owner, parsed.storage, parsed.type,
					parsed.instance,
					record_offset + offsetof(ATTR_RECORD, reserved1),
					attribute->reserved1, sizeof(attribute->reserved1)))
			goto rollback;
		if (data_offset > name_end &&
				!rh_all_zero((const unsigned char *)attribute + name_end,
					data_offset - name_end) &&
				rh_append_zero_layout_candidate(census,
					RH_RAW_LAYOUT_MAPPING_PAIRS_PADDING,
					parsed.owner, parsed.storage, parsed.type,
					parsed.instance, record_offset + name_end,
					(const unsigned char *)attribute + name_end,
					data_offset - name_end))
			goto rollback;
		parsed.lowest_vcn = sle64_to_cpu(attribute->lowest_vcn);
		parsed.highest_vcn = sle64_to_cpu(attribute->highest_vcn);
		parsed.compression_unit = attribute->compression_unit;
		parsed.allocated_size = sle64_to_cpu(attribute->allocated_size);
		parsed.data_size = sle64_to_cpu(attribute->data_size);
		parsed.initialized_size = sle64_to_cpu(attribute->initialized_size);
		parsed.compressed_size = flags &
			(le16_to_cpu(ATTR_IS_COMPRESSED) |
			 le16_to_cpu(ATTR_IS_SPARSE)) ?
			sle64_to_cpu(attribute->compressed_size) :
			parsed.allocated_size;
		if (parsed.lowest_vcn == 0 && (parsed.allocated_size < 0 ||
				parsed.data_size < 0 || parsed.initialized_size < 0 ||
				parsed.initialized_size > parsed.data_size ||
				(parsed.allocated_size & (volume->cluster_size - 1U)) ||
				((parsed.compressed_size < 0 ||
				  (parsed.compressed_size & (volume->cluster_size - 1U))) &&
				 (!census->compressed_header_tolerant ||
				  !(flags & (le16_to_cpu(ATTR_IS_COMPRESSED) |
				   le16_to_cpu(ATTR_IS_SPARSE))))))) {
			errno = EIO;
			goto rollback;
		}
		virtual_badclus = storage.record == FILE_BadClus &&
			parsed.type == le32_to_cpu(AT_DATA) &&
			rh_attribute_name_ascii(census, &parsed, "$Bad");
		if (rh_decode_mapping_pairs(volume, attribute, length, census,
				census->attribute_count, &parsed, virtual_badclus))
			goto rollback;
		rh_sha256((const unsigned char *)attribute + data_offset,
			length - data_offset, parsed.mapping_hash);
	} else {
		data_offset = le16_to_cpu(attribute->value_offset);
		data_length = le32_to_cpu(attribute->value_length);
		if (data_offset < minimum || (data_offset & 7U) ||
				data_offset < name_end ||
				data_offset > length || data_length > length - data_offset ||
				(attribute->resident_flags &
				 (uint8_t)~RESIDENT_ATTR_IS_INDEXED) ||
				(le32_to_cpu(attribute->type) == le32_to_cpu(AT_FILE_NAME) ?
				 attribute->resident_flags != RESIDENT_ATTR_IS_INDEXED :
				 attribute->resident_flags &&
				 le32_to_cpu(attribute->type) < 0x1000U)) {
			errno = EIO;
			goto rollback;
		}
		/* Pinned ntfs-3g images contain nonzero resident reservedR bytes.
		 * Readers do not interpret this byte.  Preserve and evidence-bind it;
		 * never normalize producer slack into a repair candidate. */
		parsed.resident_reserved = attribute->reservedR;
		if (data_offset > name_end &&
				!rh_all_zero((const unsigned char *)attribute + name_end,
					data_offset - name_end) &&
				rh_append_zero_layout_candidate(census,
					RH_RAW_LAYOUT_ATTRIBUTE_VALUE_PADDING,
					parsed.owner, parsed.storage, parsed.type,
					parsed.instance, record_offset + name_end,
					(const unsigned char *)attribute + name_end,
					data_offset - name_end))
			goto rollback;
		parsed.value_offset = data_offset;
		parsed.value_length = data_length;
		parsed.resident_flags = attribute->resident_flags;
		if (rh_arena_append(&census->value_arena,
				&census->value_arena_size, &census->value_arena_capacity,
				(const unsigned char *)attribute + data_offset, data_length,
				&parsed.value_arena_offset))
			goto rollback;
		rh_sha256((const unsigned char *)attribute + data_offset,
			data_length, parsed.value_hash);
	}
	if (rh_append_attribute(census, &parsed, attribute_index))
		goto rollback;
	if (parsed.type == le32_to_cpu(AT_FILE_NAME) &&
			rh_parse_file_name(&parsed, census, owner)) {
		census->attribute_count--;
		goto rollback;
	}
	return 0;
rollback:
	census->run_count = run_checkpoint;
	census->value_arena_size = value_checkpoint;
	census->name_arena_size = name_checkpoint;
	census->layout_candidate_count = layout_checkpoint;
	return -1;
}

static int rh_record_header_valid(ntfs_volume *volume,
		const MFT_RECORD *record, uint32_t *bytes_in_use,
		uint32_t *bytes_allocated, uint32_t *attribute_offset)
{
	uint16_t usa_offset, usa_count, flags;

	if (record->magic != magic_FILE)
		return 0;
	usa_offset = le16_to_cpu(record->usa_ofs);
	usa_count = le16_to_cpu(record->usa_count);
	*bytes_in_use = le32_to_cpu(record->bytes_in_use);
	*bytes_allocated = le32_to_cpu(record->bytes_allocated);
	*attribute_offset = le16_to_cpu(record->attrs_offset);
	flags = le16_to_cpu(record->flags);
	/* bytes_in_use and bytes_allocated are checked after the complete,
	 * uniquely bounded attribute chain has established their exact values. */
	return *attribute_offset >= sizeof(*record) &&
		!(*attribute_offset & 7U) &&
		*attribute_offset <= volume->mft_record_size - 8U &&
		usa_offset >= sizeof(NTFS_RECORD) &&
		usa_offset <= volume->mft_record_size &&
		usa_count == volume->mft_record_size / volume->sector_size + 1U &&
		(uint32_t)usa_count * 2U <= volume->mft_record_size - usa_offset &&
		*attribute_offset >= (((uint32_t)usa_offset +
			(uint32_t)usa_count * 2U + 7U) & ~7U) &&
		!(flags & (uint16_t)~0x000fU);
}

static int rh_biu_growth_unambiguous(
		const struct rh_raw_mft_census *census,
		const struct rh_raw_mft_slot *slot, uint32_t observed_biu,
		uint32_t canonical_biu)
{
	uint32_t old_end;
	size_t i;

	if (observed_biu >= canonical_biu)
		return 1;
	if (observed_biu < 8U)
		return 0;
	old_end = observed_biu - 8U;
	for (i = slot->attribute_first;
			i < slot->attribute_first + slot->attribute_count; i++) {
		const struct rh_raw_attribute *attribute = &census->attributes[i];
		uint32_t minimum = attribute->nonresident ?
			(attribute->flags & (le16_to_cpu(ATTR_IS_COMPRESSED) |
			 le16_to_cpu(ATTR_IS_SPARSE)) ? 72U : 64U) : 24U;

		/* A too-small BIU is uniquely a header defect only when its old
		 * terminator position falls well inside an already bounded attribute.
		 * If it coincides with (or lies in the header of) a newly plausible
		 * attribute, stale slack and a corrupted AT_END are indistinguishable. */
		if (old_end >= attribute->record_offset + minimum &&
				old_end < attribute->record_offset + attribute->record_length)
			return 1;
	}
	return 0;
}

static int rh_parse_record(ntfs_volume *volume, uint64_t record_number,
		const unsigned char *record_bytes, struct rh_raw_mft_census *census,
		const ntfschar *upcase, uint32_t upcase_length)
{
	const MFT_RECORD *record = (const MFT_RECORD *)record_bytes;
	struct rh_raw_mft_slot *slot = &census->slots[record_number];
	struct rh_raw_mft_ref storage, owner;
	uint32_t bytes_in_use = 0, bytes_allocated = 0, offset = 0;
	size_t attr_checkpoint = census->attribute_count;
	size_t run_checkpoint = census->run_count;
	size_t fn_checkpoint = census->file_name_count;
	size_t name_checkpoint = census->name_arena_size;
	size_t value_checkpoint = census->value_arena_size;
	size_t layout_checkpoint = census->layout_candidate_count;
	uint16_t instance_seen[UINT16_MAX / 8U + 1U];
	uint16_t max_instance = 0;
	size_t previous_attribute = SIZE_MAX;
	int found_end = 0, saw_attribute = 0;

	memset(instance_seen, 0, sizeof(instance_seen));
	if (!rh_record_header_valid(volume, record, &bytes_in_use,
			&bytes_allocated,
			&offset)) {
		errno = EIO;
		return -1;
	}
	storage.record = record_number;
	storage.sequence = le16_to_cpu(record->sequence_number);
	slot->record = record_number;
	slot->sequence = storage.sequence;
	slot->flags = le16_to_cpu(record->flags);
	slot->link_count = le16_to_cpu(record->link_count);
	slot->next_attribute_instance =
		le16_to_cpu(record->next_attr_instance);
	if (!(slot->flags & le16_to_cpu(MFT_RECORD_IN_USE))) {
		/* Deleted-record attribute bytes are stale and are deliberately not
		 * parsed or canonicalized.  Without a live chain there is no typed
		 * identity or authority for cosmetic header rewrites. */
		if (bytes_in_use < sizeof(*record) ||
				bytes_in_use > volume->mft_record_size ||
				(bytes_in_use & 7U) || offset > bytes_in_use - 4U) {
			errno = EIO;
			goto rollback;
		}
		slot->state = RH_RAW_SLOT_FREE;
		return 0;
	}
	if (!storage.sequence) {
		errno = EIO;
		return -1;
	}
	slot->base = rh_ref_from_le(record->base_mft_record);
	if (slot->base.record || slot->base.sequence) {
		if (!slot->base.record || !slot->base.sequence ||
				slot->base.record == record_number) {
			errno = EIO;
			return -1;
		}
		slot->state = RH_RAW_SLOT_LIVE_EXTENT;
		owner = slot->base;
	} else {
		slot->state = RH_RAW_SLOT_LIVE_BASE;
		owner = storage;
	}
	/* mft_record_number and reserved are non-authoritative producer cache/slack
	 * fields.  Windows and Linux NTFS producers legitimately leave values in
	 * them (notably on WSL-EA records).  The slot position, MST framing,
	 * sequence, base reference and fully bounded attribute chain establish the
	 * record identity; these two fields must not turn a healthy record into a
	 * repair prerequisite or a boot refusal. */
	if (bytes_allocated != volume->mft_record_size) {
		le32 replacement = cpu_to_le32(volume->mft_record_size);

		if (rh_append_layout_candidate(census,
				RH_RAW_LAYOUT_BYTES_ALLOCATED, owner, storage, 0, 0,
				offsetof(MFT_RECORD, bytes_allocated),
				(const unsigned char *)&record->bytes_allocated,
				(const unsigned char *)&replacement, sizeof(replacement)))
			goto rollback;
	}
	slot->attribute_first = census->attribute_count;
	slot->file_name_first = census->file_name_count;
	while (offset <= volume->mft_record_size - sizeof(uint32_t)) {
		const ATTR_RECORD *attribute =
			(const ATTR_RECORD *)(record_bytes + offset);
		uint32_t type = le32_to_cpu(attribute->type);
		uint32_t length;
		uint16_t instance;
		size_t attribute_index;

		if (type == 0xffffffffU) {
			/* The four bytes following AT_END are not part of an attribute.
			 * Windows uses this producer-owned slack in newly created records;
			 * readers ignore it, so preserve it rather than inventing a repair. */
			found_end = 1;
			break;
		}
		if (volume->mft_record_size - offset < 16U) {
			errno = EIO;
			goto rollback;
		}
		instance = le16_to_cpu(attribute->instance);
		if (instance_seen[instance >> 3] & (uint16_t)(1U << (instance & 7U))) {
			errno = EIO;
			goto rollback;
		}
		instance_seen[instance >> 3] |=
			(uint16_t)(1U << (instance & 7U));
		if (!saw_attribute || instance > max_instance)
			max_instance = instance;
		saw_attribute = 1;
		if (rh_parse_attribute(volume, record_bytes, offset,
				volume->mft_record_size - offset, census, storage, owner,
				&attribute_index))
			goto rollback;
		if (previous_attribute != SIZE_MAX &&
				rh_attribute_order_compare(census,
					&census->attributes[previous_attribute],
					&census->attributes[attribute_index], upcase,
					upcase_length) >= 0) {
			errno = EIO;
			goto rollback;
		}
		previous_attribute = attribute_index;
		length = census->attributes[attribute_index].record_length;
		if (type == le32_to_cpu(AT_ATTRIBUTE_LIST)) {
			if (slot->has_attribute_list ||
					census->attributes[attribute_index].name_length) {
				errno = EIO;
				goto rollback;
			}
			slot->has_attribute_list = 1;
		}
		offset += length;
	}
	if (!found_end) {
		errno = EIO;
		goto rollback;
	}
	slot->attribute_count = census->attribute_count - slot->attribute_first;
	slot->file_name_count = census->file_name_count - slot->file_name_first;
	if (bytes_in_use != offset + 8U) {
		le32 replacement = cpu_to_le32(offset + 8U);

		if (!rh_biu_growth_unambiguous(census, slot, bytes_in_use,
				offset + 8U)) {
			errno = EIO;
			goto rollback;
		}
		if (rh_append_layout_candidate(census,
				RH_RAW_LAYOUT_BYTES_IN_USE, owner, storage, 0, 0,
				offsetof(MFT_RECORD, bytes_in_use),
				(const unsigned char *)&record->bytes_in_use,
				(const unsigned char *)&replacement, sizeof(replacement)))
			goto rollback;
	}
	if (saw_attribute && slot->next_attribute_instance <= max_instance) {
		uint16_t expected = (uint16_t)(max_instance + 1U);

		if (slot->next_attribute_instance != expected) {
			le16 replacement = cpu_to_le16(expected);

			if (rh_append_layout_candidate(census,
					RH_RAW_LAYOUT_NEXT_ATTRIBUTE_INSTANCE,
					owner, storage, 0, 0,
					offsetof(MFT_RECORD, next_attr_instance),
					(const unsigned char *)&record->next_attr_instance,
					(const unsigned char *)&replacement,
					sizeof(replacement)))
				goto rollback;
		}
	}
	if (slot->state == RH_RAW_SLOT_LIVE_BASE) {
		size_t i;
		unsigned int i30_roots = 0;

		for (i = slot->attribute_first;
				i < slot->attribute_first + slot->attribute_count; i++)
			if (census->attributes[i].type == le32_to_cpu(AT_INDEX_ROOT) &&
					rh_attribute_name_ascii(census, &census->attributes[i],
						"$I30"))
				i30_roots++;
		if (i30_roots > 1U || (!slot->has_attribute_list &&
				(!!i30_roots != !!(slot->flags &
				 le16_to_cpu(MFT_RECORD_IS_DIRECTORY))))) {
			errno = EIO;
			goto rollback;
		}
	}
	return 0;
rollback:
	census->attribute_count = attr_checkpoint;
	census->run_count = run_checkpoint;
	census->file_name_count = fn_checkpoint;
	census->name_arena_size = name_checkpoint;
	census->value_arena_size = value_checkpoint;
	census->layout_candidate_count = layout_checkpoint;
	memset(slot, 0, sizeof(*slot));
	slot->record = record_number;
	slot->state = RH_RAW_SLOT_INVALID;
	return -1;
}

static int rh_nonresident_list_shape(ntfs_volume *volume,
		const struct rh_raw_mft_census *census,
		const struct rh_raw_attribute *attribute)
{
	uint64_t expected_vcn = 0, allocated_bytes;
	size_t i;

	if (!attribute->nonresident || attribute->lowest_vcn ||
			attribute->data_size <= 0 || attribute->allocated_size <= 0 ||
			(uint64_t)attribute->data_size > RH_RAW_ATTR_LIST_MAX ||
			attribute->initialized_size != attribute->data_size ||
			attribute->data_size > attribute->allocated_size ||
			attribute->flags || attribute->run_count == 0 ||
			attribute->highest_vcn < 0) {
		errno = EIO;
		return -1;
	}
	for (i = 0; i < attribute->run_count; i++) {
		const struct rh_raw_run *run =
			&census->runs[attribute->run_first + i];

		if (run->attribute_index != (uint64_t)(attribute - census->attributes) ||
				run->sparse || run->vcn < 0 ||
				(uint64_t)run->vcn != expected_vcn || run->lcn < 0 ||
				run->length > UINT64_MAX - expected_vcn) {
			errno = EIO;
			return -1;
		}
		expected_vcn += run->length;
	}
	if (expected_vcn != (uint64_t)attribute->highest_vcn + 1U ||
			expected_vcn > UINT64_MAX / volume->cluster_size) {
		errno = EIO;
		return -1;
	}
	allocated_bytes = expected_vcn * volume->cluster_size;
	if ((uint64_t)attribute->allocated_size != allocated_bytes) {
		errno = EIO;
		return -1;
	}
	return 0;
}

static int rh_nonresident_list_pread(ntfs_volume *volume,
		const struct rh_census_reader *reader,
		const struct rh_raw_mft_census *census,
		const struct rh_raw_attribute *attribute, uint64_t offset,
		size_t length, unsigned char *buffer)
{
	uint64_t request_end, copied = 0;
	size_t i;

	if (!buffer || offset > (uint64_t)attribute->data_size ||
			length > (uint64_t)attribute->data_size - offset ||
			rh_u64_add(offset, length, &request_end)) {
		errno = EINVAL;
		return -1;
	}
	for (i = 0; i < attribute->run_count && copied < length; i++) {
		const struct rh_raw_run *run =
			&census->runs[attribute->run_first + i];
		uint64_t run_start, run_bytes, run_end, part_start, part_end;
		uint64_t physical, within, part_length;

		if (run->vcn < 0 || run->lcn < 0 || run->sparse ||
				(uint64_t)run->vcn > UINT64_MAX / volume->cluster_size ||
				run->length > UINT64_MAX / volume->cluster_size ||
				(uint64_t)run->lcn > UINT64_MAX / volume->cluster_size) {
			errno = EIO;
			return -1;
		}
		run_start = (uint64_t)run->vcn * volume->cluster_size;
		run_bytes = run->length * volume->cluster_size;
		if (rh_u64_add(run_start, run_bytes, &run_end)) {
			errno = EOVERFLOW;
			return -1;
		}
		if (request_end <= run_start || offset >= run_end)
			continue;
		part_start = offset > run_start ? offset : run_start;
		part_end = request_end < run_end ? request_end : run_end;
		within = part_start - run_start;
		part_length = part_end - part_start;
		physical = (uint64_t)run->lcn * volume->cluster_size;
		if (physical > UINT64_MAX - within || part_length > SIZE_MAX ||
				part_start - offset != copied ||
				rh_census_reader_read_exact(reader, physical + within,
					(size_t)part_length,
					buffer + copied))
			return -1;
		copied += part_length;
	}
	if (copied != length) {
		errno = EIO;
		return -1;
	}
	return 0;
}

static int rh_parse_attribute_list_entry(struct rh_raw_mft_census *census,
		struct rh_raw_mft_slot *slot, const unsigned char *value,
		size_t value_length, size_t maximum_entries)
{
	const ATTR_LIST_ENTRY *raw;
	struct rh_raw_attr_list_entry entry;
	uint16_t length;
	uint32_t name_end;

	if (!value || value_length < sizeof(*raw) ||
			census->list_entry_count - slot->list_entry_first >=
			maximum_entries) {
		errno = EIO;
		return -1;
	}
	raw = (const ATTR_LIST_ENTRY *)value;
	length = le16_to_cpu(raw->length);
	if (length != value_length || length < sizeof(*raw) || (length & 7U) ||
			le32_to_cpu(raw->type) == le32_to_cpu(AT_ATTRIBUTE_LIST) ||
			(!ntfs_is_valid_attr_type((const ATTR_RECORD *)raw) &&
			 !(le32_to_cpu(raw->type) >= 0x1000U &&
			  le32_to_cpu(raw->type) < 0xffffffffU)) ||
			raw->name_offset < offsetof(ATTR_LIST_ENTRY, name) ||
			raw->name_offset > length) {
		errno = EIO;
		return -1;
	}
	name_end = (uint32_t)raw->name_offset +
		(uint32_t)raw->name_length * 2U;
	if (name_end > length ||
			!rh_all_zero((const unsigned char *)raw +
				offsetof(ATTR_LIST_ENTRY, name),
				raw->name_offset - offsetof(ATTR_LIST_ENTRY, name))) {
		errno = EIO;
		return -1;
	}
	/* Bytes after the bounded UTF-16 name are producer-owned alignment slack.
	 * Windows and ntfs3 can preserve nonzero values there; no NTFS reader
	 * interprets them.  Bind the typed fields and name above, but do not turn
	 * ignored padding into a boot-blocking health claim. */
	memset(&entry, 0, sizeof(entry));
	entry.owner.record = slot->record;
	entry.owner.sequence = slot->sequence;
	entry.storage = rh_ref_from_le(raw->mft_reference);
	entry.type = le32_to_cpu(raw->type);
	entry.lowest_vcn = sle64_to_cpu(raw->lowest_vcn);
	entry.instance = le16_to_cpu(raw->instance);
	entry.name_length = raw->name_length;
	entry.matched_attribute = SIZE_MAX;
	if (!entry.storage.sequence || entry.lowest_vcn < 0 ||
			rh_arena_append(&census->name_arena, &census->name_arena_size,
				&census->name_arena_capacity,
				(const unsigned char *)raw + raw->name_offset,
				(size_t)raw->name_length * 2U, &entry.name_offset) ||
			rh_append_list_entry(census, &entry)) {
		if (!errno)
			errno = EIO;
		return -1;
	}
	return 0;
}

static int rh_parse_attribute_list_memory(struct rh_raw_mft_census *census,
		struct rh_raw_mft_slot *slot, const unsigned char *value,
		size_t value_length, size_t maximum_entries)
{
	size_t position = 0;

	while (position < value_length) {
		const ATTR_LIST_ENTRY *raw;
		uint16_t length;

		if (value_length - position < sizeof(*raw)) {
			errno = EIO;
			return -1;
		}
		raw = (const ATTR_LIST_ENTRY *)(value + position);
		length = le16_to_cpu(raw->length);
		if (length > value_length - position ||
				rh_parse_attribute_list_entry(census, slot, value + position,
					length, maximum_entries))
			return -1;
		position += length;
	}
	if (!position || position != value_length) {
		errno = EIO;
		return -1;
	}
	return 0;
}

static int rh_parse_attribute_list_nonresident(ntfs_volume *volume,
		const struct rh_census_reader *reader,
		struct rh_raw_mft_census *census,
		struct rh_raw_mft_slot *slot,
		const struct rh_raw_attribute *attribute, size_t maximum_entries)
{
	unsigned char header[sizeof(ATTR_LIST_ENTRY)];
	uint64_t position = 0, value_length = (uint64_t)attribute->data_size;

	if (rh_nonresident_list_shape(volume, census, attribute)) {
		if (errno == EIO)
			errno = EUCLEAN;
		return -1;
	}
	while (position < value_length) {
		unsigned char *entry;
		uint16_t length;

		if (value_length - position < sizeof(header)) {
			errno = EUCLEAN;
			return -1;
		}
		if (rh_nonresident_list_pread(volume, reader, census, attribute,
				position, sizeof(header), header))
			return -1;
		length = le16_to_cpu(((const ATTR_LIST_ENTRY *)header)->length);
		if (length < sizeof(header) || (length & 7U) ||
				length > value_length - position) {
			errno = EUCLEAN;
			return -1;
		}
		entry = malloc(length);
		if (!entry)
			return -1;
		memcpy(entry, header, sizeof(header));
		if (length > sizeof(header) &&
				rh_nonresident_list_pread(volume, reader, census, attribute,
					position + sizeof(header), length - sizeof(header),
					entry + sizeof(header))) {
			free(entry);
			return -1;
		}
		if (rh_parse_attribute_list_entry(census, slot, entry, length,
				maximum_entries)) {
			if (errno == EIO)
				errno = EUCLEAN;
			free(entry);
			return -1;
		}
		free(entry);
		position += length;
	}
	if (!position || position != value_length) {
		errno = EUCLEAN;
		return -1;
	}
	return 0;
}

static int rh_entry_matches_attribute(const struct rh_raw_mft_census *census,
		const struct rh_raw_attr_list_entry *entry,
		const struct rh_raw_attribute *attribute)
{
	int64_t lowest = attribute->nonresident ? attribute->lowest_vcn : 0;

	return entry->type == attribute->type &&
		entry->storage.record == attribute->storage.record &&
		entry->storage.sequence == attribute->storage.sequence &&
		entry->lowest_vcn == lowest &&
		entry->instance == attribute->instance &&
		rh_name_equal(census, entry->name_offset, entry->name_length,
			attribute->name_offset, attribute->name_length);
}

static int rh_list_entry_order_compare(
		const struct rh_raw_mft_census *census,
		const struct rh_raw_attr_list_entry *left,
		const struct rh_raw_attr_list_entry *right,
		const ntfschar *upcase, uint32_t upcase_length)
{
	int comparison;

	if (left->type != right->type)
		return left->type < right->type ? -1 : 1;
	if (!left->name_length && right->name_length)
		return -1;
	if (left->name_length && !right->name_length)
		return 1;
	if (left->name_length) {
		comparison = ntfs_names_full_collate(
			(const ntfschar *)(census->name_arena + left->name_offset),
			left->name_length,
			(const ntfschar *)(census->name_arena + right->name_offset),
			right->name_length, CASE_SENSITIVE, upcase, upcase_length);
		if (comparison)
			return comparison;
	}
	if (left->lowest_vcn != right->lowest_vcn)
		return left->lowest_vcn < right->lowest_vcn ? -1 : 1;
	/* Resident duplicates have no value in the list entry.  Pinned ntfs-3g
	 * can place equal type/name/VCN entries in storage/instance order that is
	 * unrelated to the full resident-value order.  Exact one-to-one matching
	 * below proves their identities; no extra order exists to validate here. */
	return 0;
}

static int rh_assemble_attribute_lists(ntfs_volume *volume,
		const struct rh_census_reader *reader,
		struct rh_raw_mft_census *census,
		const ntfschar *upcase, uint32_t upcase_length)
{
	size_t slot_index, i, j;

	for (slot_index = 0; slot_index < census->slot_count; slot_index++) {
		struct rh_raw_mft_slot *slot = &census->slots[slot_index];

		if (slot->state != RH_RAW_SLOT_LIVE_EXTENT)
			continue;
		/*
		 * The supported v1 profile follows layout.h's ATTRIBUTE_LIST
		 * bootstrap rule: the list excludes itself and, when nonresident,
		 * its complete mapping array remains in the base FILE record.  The
		 * exact d4 writer enforces this in attrib.c before splitting mapping
		 * pairs.  A list attribute in an extent is therefore unsupported,
		 * not silently treated as a partial list.
		 */
		if (slot->base.record >= census->slot_count ||
				census->slots[slot->base.record].state !=
				RH_RAW_SLOT_LIVE_BASE ||
				census->slots[slot->base.record].sequence !=
				slot->base.sequence || slot->link_count ||
				slot->has_attribute_list) {
			errno = EIO;
			return -1;
		}
		if (!census->slots[slot->base.record].has_attribute_list) {
			errno = EIO;
			return -1;
		}
		for (i = slot->attribute_first;
				i < slot->attribute_first + slot->attribute_count; i++)
			census->attributes[i].owner = slot->base;
		for (i = slot->file_name_first;
				i < slot->file_name_first + slot->file_name_count; i++)
			census->file_names[i].owner = slot->base;
	}
	for (slot_index = 0; slot_index < census->slot_count; slot_index++) {
		struct rh_raw_mft_slot *slot = &census->slots[slot_index];
		const struct rh_raw_attribute *list = NULL;
		size_t entry_checkpoint, name_checkpoint, maximum_entries = 0;

		if (slot->state != RH_RAW_SLOT_LIVE_BASE)
			continue;
		if (!slot->has_attribute_list) {
			slot->attribute_list_assembled = 1;
			continue;
		}
		for (i = slot->attribute_first;
				i < slot->attribute_first + slot->attribute_count; i++) {
			if (census->attributes[i].type ==
					le32_to_cpu(AT_ATTRIBUTE_LIST)) {
			if (list) {
					errno = EIO;
					return -1;
				}
				list = &census->attributes[i];
			}
		}
		if (!list || list->owner.record != slot->record ||
				list->owner.sequence != slot->sequence || list->name_length) {
			errno = EIO;
			return -1;
		}
		for (i = 0; i < census->attribute_count; i++)
			if (census->attributes[i].owner.record == slot->record &&
					census->attributes[i].owner.sequence == slot->sequence &&
					census->attributes[i].type !=
						le32_to_cpu(AT_ATTRIBUTE_LIST))
				maximum_entries++;
		if (!maximum_entries) {
			errno = EIO;
			return -1;
		}
		entry_checkpoint = census->list_entry_count;
		name_checkpoint = census->name_arena_size;
		slot->list_entry_first = census->list_entry_count;
		if (list->nonresident) {
			if (rh_parse_attribute_list_nonresident(volume, reader, census,
					slot, list, maximum_entries))
				goto parse_fail;
		} else {
			if (rh_parse_attribute_list_memory(census, slot,
					census->value_arena + list->value_arena_offset,
					list->value_length, maximum_entries))
				goto parse_fail;
		}
		slot->list_entry_count = census->list_entry_count -
			slot->list_entry_first;
		if (slot->list_entry_count != maximum_entries) {
			errno = EIO;
			goto parse_fail;
		}
		for (i = slot->list_entry_first;
				i < slot->list_entry_first + slot->list_entry_count; i++) {
			struct rh_raw_attr_list_entry *entry = &census->list_entries[i];
			size_t match = SIZE_MAX;

			if (entry->storage.record >= census->slot_count ||
					(census->slots[entry->storage.record].state !=
					 RH_RAW_SLOT_LIVE_BASE &&
					 census->slots[entry->storage.record].state !=
					 RH_RAW_SLOT_LIVE_EXTENT) ||
					census->slots[entry->storage.record].sequence !=
					entry->storage.sequence) {
				errno = EIO;
				return -1;
			}
			for (j = 0; j < census->attribute_count; j++) {
				struct rh_raw_attribute *attribute = &census->attributes[j];

				if (attribute->owner.record != slot->record ||
						attribute->owner.sequence != slot->sequence ||
						!rh_entry_matches_attribute(census, entry, attribute))
					continue;
				if (match != SIZE_MAX || attribute->list_claimed) {
					errno = EIO;
					return -1;
				}
				match = j;
			}
			if (match == SIZE_MAX) {
				errno = EIO;
				return -1;
			}
			entry->matched = 1;
			entry->matched_attribute = match;
			census->attributes[match].list_claimed = 1;
		}
		for (i = 0; i < census->attribute_count; i++) {
			const struct rh_raw_attribute *attribute = &census->attributes[i];

			if (attribute->owner.record == slot->record &&
					attribute->owner.sequence == slot->sequence &&
					attribute->type != le32_to_cpu(AT_ATTRIBUTE_LIST) &&
					!attribute->list_claimed) {
				errno = EIO;
				return -1;
			}
		}
		for (i = slot->list_entry_first + 1U;
				i < slot->list_entry_first + slot->list_entry_count; i++) {
			const struct rh_raw_attr_list_entry *left =
				&census->list_entries[i - 1U];
			const struct rh_raw_attr_list_entry *right =
				&census->list_entries[i];
			if (left->matched_attribute >= census->attribute_count ||
					right->matched_attribute >= census->attribute_count ||
					rh_list_entry_order_compare(census, left, right, upcase,
					upcase_length) > 0) {
				errno = EIO;
				return -1;
			}
		}
		slot->attribute_list_assembled = 1;
		continue;
parse_fail:
		census->list_entry_count = entry_checkpoint;
		census->name_arena_size = name_checkpoint;
		slot->list_entry_first = 0;
		slot->list_entry_count = 0;
		return -1;
	}
	return 0;
}

static int rh_same_stream(const struct rh_raw_mft_census *census,
		const struct rh_raw_attribute *left,
		const struct rh_raw_attribute *right)
{
	return left->owner.record == right->owner.record &&
		left->owner.sequence == right->owner.sequence &&
		left->type == right->type &&
		rh_name_equal(census, left->name_offset, left->name_length,
			right->name_offset, right->name_length);
}

static int rh_validate_stream_extents(ntfs_volume *volume,
		struct rh_raw_mft_census *census)
{
	unsigned char *visited;
	size_t i, j;

	visited = calloc(census->attribute_count ? census->attribute_count : 1U, 1U);
	if (!visited)
		return -1;
	for (i = 0; i < census->attribute_count; i++) {
		for (j = i + 1U; j < census->attribute_count; j++) {
			const struct rh_raw_attribute *left = &census->attributes[i];
			const struct rh_raw_attribute *right = &census->attributes[j];

			if (!rh_same_stream(census, left, right))
				continue;
			if (left->nonresident != right->nonresident ||
					(!left->nonresident &&
					 left->type != le32_to_cpu(AT_FILE_NAME))) {
				errno = EIO;
				goto fail;
			}
		}
	}
	for (i = 0; i < census->attribute_count; i++) {
		struct rh_raw_attribute *initial = &census->attributes[i];
		uint64_t expected_vcn = 0, physical_clusters = 0;
		uint64_t virtual_bytes, physical_bytes;
		int virtual_badclus;
		int have_extent = 1;

		if (!initial->nonresident || visited[i] || initial->lowest_vcn)
			continue;
		while (have_extent) {
			struct rh_raw_attribute *extent = NULL;
			size_t extent_index = SIZE_MAX;
			uint64_t next_vcn;

			have_extent = 0;
			for (j = 0; j < census->attribute_count; j++) {
				struct rh_raw_attribute *candidate = &census->attributes[j];

				if (!candidate->nonresident || visited[j] ||
						!rh_same_stream(census, initial, candidate))
					continue;
				if (candidate->lowest_vcn < 0) {
					errno = EIO;
					goto fail;
				}
				if ((uint64_t)candidate->lowest_vcn != expected_vcn)
					continue;
				if (extent) {
					errno = EIO;
					goto fail;
				}
				extent = candidate;
				extent_index = j;
			}
			if (!extent)
				break;
			if (extent->flags != initial->flags ||
					extent->highest_vcn < extent->lowest_vcn - 1) {
				errno = EIO;
				goto fail;
			}
			if (extent->compression_unit !=
					((initial->flags & (le16_to_cpu(ATTR_IS_COMPRESSED) |
					  le16_to_cpu(ATTR_IS_SPARSE))) ?
					 STANDARD_COMPRESSION_UNIT : 0U)) {
				if (!census->compressed_header_tolerant) {
					errno = EIO;
					goto fail;
				}
				extent->compression_unit_mismatch = 1;
				if (rh_u64_add(census->compressed_header_mismatches, 1U,
						&census->compressed_header_mismatches)) {
					errno = EOVERFLOW;
					goto fail;
				}
			}
			next_vcn = expected_vcn;
			for (j = 0; j < extent->run_count; j++) {
				const struct rh_raw_run *run =
					&census->runs[extent->run_first + j];

				if (run->attribute_index != extent_index || run->vcn < 0 ||
						(uint64_t)run->vcn != next_vcn ||
						run->length > UINT64_MAX - next_vcn ||
						(!run->sparse && run->length >
						 UINT64_MAX - physical_clusters)) {
					errno = EIO;
					goto fail;
				}
				next_vcn += run->length;
				if (!run->sparse)
					physical_clusters += run->length;
			}
			if (extent->highest_vcn >= extent->lowest_vcn) {
				if (extent->highest_vcn == INT64_MAX ||
						next_vcn != (uint64_t)extent->highest_vcn + 1U) {
					errno = EIO;
					goto fail;
				}
			} else if (next_vcn != expected_vcn) {
				errno = EIO;
				goto fail;
			}
			visited[extent_index] = 1;
			census->extents_completed++;
			expected_vcn = next_vcn;
			have_extent = 1;
		}
		for (j = 0; j < census->attribute_count; j++) {
			if (!visited[j] && census->attributes[j].nonresident &&
					rh_same_stream(census, initial, &census->attributes[j])) {
				errno = EIO;
				goto fail;
			}
		}
		if (initial->allocated_size < 0 || initial->data_size < 0 ||
				initial->initialized_size < 0 ||
				initial->initialized_size > initial->data_size ||
				expected_vcn > UINT64_MAX / volume->cluster_size ||
				physical_clusters > UINT64_MAX / volume->cluster_size) {
			errno = EIO;
			goto fail;
		}
		virtual_bytes = expected_vcn * volume->cluster_size;
		physical_bytes = physical_clusters * volume->cluster_size;
		virtual_badclus = initial->owner.record == FILE_BadClus &&
			initial->type == le32_to_cpu(AT_DATA) &&
			rh_attribute_name_ascii(census, initial, "$Bad");
		if ((uint64_t)initial->allocated_size != virtual_bytes ||
				(uint64_t)initial->data_size > virtual_bytes ||
				(virtual_badclus ? physical_bytes != 0U :
				 !(initial->flags & (le16_to_cpu(ATTR_IS_COMPRESSED) |
				 le16_to_cpu(ATTR_IS_SPARSE))) &&
				 physical_bytes != virtual_bytes)) {
			errno = EIO;
			goto fail;
		}
		if (!virtual_badclus &&
				(initial->flags & (le16_to_cpu(ATTR_IS_COMPRESSED) |
				 le16_to_cpu(ATTR_IS_SPARSE))) &&
				(initial->compressed_size < 0 ||
				 (uint64_t)initial->compressed_size != physical_bytes)) {
			if (!census->compressed_header_tolerant) {
				errno = EIO;
				goto fail;
			}
			initial->compressed_size_mismatch = 1;
			if (rh_u64_add(census->compressed_header_mismatches, 1U,
					&census->compressed_header_mismatches)) {
				errno = EOVERFLOW;
				goto fail;
			}
		}
	}
	for (i = 0; i < census->attribute_count; i++) {
		if (census->attributes[i].nonresident && !visited[i]) {
			errno = EIO;
			goto fail;
		}
	}
	free(visited);
	return 0;
fail:
	free(visited);
	return -1;
}

static int rh_validate_directory_shapes(
		const struct rh_raw_mft_census *census)
{
	size_t slot_index, attribute_index;

	for (slot_index = 0; slot_index < census->slot_count; slot_index++) {
		const struct rh_raw_mft_slot *slot = &census->slots[slot_index];
		unsigned int i30_roots = 0;

		if (slot->state != RH_RAW_SLOT_LIVE_BASE)
			continue;
		for (attribute_index = 0;
				attribute_index < census->attribute_count; attribute_index++) {
			const struct rh_raw_attribute *attribute =
				&census->attributes[attribute_index];

			if (attribute->owner.record != slot->record ||
					attribute->owner.sequence != slot->sequence ||
					attribute->type != le32_to_cpu(AT_INDEX_ROOT) ||
					!rh_attribute_name_ascii(census, attribute, "$I30"))
				continue;
			i30_roots++;
		}
		if (i30_roots > 1U || (!!i30_roots !=
				!!(slot->flags & le16_to_cpu(MFT_RECORD_IS_DIRECTORY)))) {
			errno = EIO;
			return -1;
		}
	}
	return 0;
}

static int rh_count_owned_file_names(struct rh_raw_mft_census *census)
{
	size_t i;

	for (i = 0; i < census->slot_count; i++)
		census->slots[i].owned_file_name_count = 0;
	for (i = 0; i < census->file_name_count; i++) {
		const struct rh_raw_file_name *file_name = &census->file_names[i];
		struct rh_raw_mft_slot *slot;

		if (file_name->owner.record >= census->slot_count) {
			errno = EIO;
			return -1;
		}
		slot = &census->slots[file_name->owner.record];
		if (slot->state != RH_RAW_SLOT_LIVE_BASE ||
				slot->sequence != file_name->owner.sequence ||
				slot->owned_file_name_count == SIZE_MAX) {
			errno = EIO;
			return -1;
		}
		slot->owned_file_name_count++;
	}
	return 0;
}

static void rh_put_u16le(unsigned char *bytes, uint16_t value)
{
	bytes[0] = (unsigned char)value;
	bytes[1] = (unsigned char)(value >> 8);
}

static void rh_put_u32le(unsigned char *bytes, uint32_t value)
{
	unsigned int i;

	for (i = 0; i < 4U; i++)
		bytes[i] = (unsigned char)(value >> (8U * i));
}

static void rh_put_u64le(unsigned char *bytes, uint64_t value)
{
	unsigned int i;

	for (i = 0; i < 8U; i++)
		bytes[i] = (unsigned char)(value >> (8U * i));
}

static void rh_hash_name(const struct rh_raw_mft_census *census,
		size_t offset, uint16_t length, unsigned char digest[32])
{
	if (!length) {
		rh_sha256("", 0, digest);
		return;
	}
	rh_sha256(census->name_arena + offset, (size_t)length * 2U, digest);
}

static void rh_encode_hash_slot(const struct rh_raw_mft_slot *slot,
		unsigned char bytes[RH_RAW_HASH_SLOT_BYTES])
{
	memset(bytes, 0, RH_RAW_HASH_SLOT_BYTES);
	bytes[0] = (unsigned char)slot->state;
	rh_put_u64le(bytes + 8, slot->record);
	rh_put_u16le(bytes + 16, slot->sequence);
	rh_put_u16le(bytes + 18, slot->flags);
	rh_put_u16le(bytes + 20, slot->link_count);
	rh_put_u16le(bytes + 22, slot->next_attribute_instance);
	rh_put_u64le(bytes + 24, slot->base.record);
	rh_put_u16le(bytes + 32, slot->base.sequence);
	rh_put_u64le(bytes + 40, slot->attribute_count);
	rh_put_u64le(bytes + 48, slot->file_name_count);
	bytes[56] = slot->has_attribute_list;
	bytes[57] = slot->attribute_list_assembled;
}

static void rh_encode_hash_attribute(const struct rh_raw_mft_census *census,
		const struct rh_raw_attribute *attribute,
		unsigned char bytes[RH_RAW_HASH_ATTRIBUTE_BYTES])
{
	unsigned char name_hash[32];

	memset(bytes, 0, RH_RAW_HASH_ATTRIBUTE_BYTES);
	rh_hash_name(census, attribute->name_offset, attribute->name_length,
		name_hash);
	rh_put_u64le(bytes, attribute->owner.record);
	rh_put_u16le(bytes + 8, attribute->owner.sequence);
	rh_put_u64le(bytes + 16, attribute->storage.record);
	rh_put_u16le(bytes + 24, attribute->storage.sequence);
	rh_put_u32le(bytes + 28, attribute->type);
	rh_put_u16le(bytes + 32, attribute->instance);
	rh_put_u16le(bytes + 34, attribute->flags);
	rh_put_u32le(bytes + 36, attribute->record_offset);
	rh_put_u32le(bytes + 40, attribute->record_length);
	rh_put_u16le(bytes + 44, attribute->name_length);
	memcpy(bytes + 48, name_hash, sizeof(name_hash));
	bytes[80] = attribute->nonresident;
	bytes[81] = attribute->compression_unit;
	bytes[82] = attribute->resident_flags;
	bytes[83] = attribute->list_claimed;
	bytes[84] = attribute->resident_reserved;
	bytes[85] = attribute->compression_unit_mismatch;
	bytes[86] = attribute->compressed_size_mismatch;
	rh_put_u64le(bytes + 88, (uint64_t)attribute->lowest_vcn);
	rh_put_u64le(bytes + 96, (uint64_t)attribute->highest_vcn);
	rh_put_u64le(bytes + 104, (uint64_t)attribute->allocated_size);
	rh_put_u64le(bytes + 112, (uint64_t)attribute->data_size);
	rh_put_u64le(bytes + 120, (uint64_t)attribute->initialized_size);
	rh_put_u64le(bytes + 128, (uint64_t)attribute->compressed_size);
	rh_put_u64le(bytes + 136, attribute->run_count);
	rh_put_u32le(bytes + 144, attribute->value_length);
	memcpy(bytes + 152, attribute->value_hash,
		sizeof(attribute->value_hash));
	memcpy(bytes + 184, attribute->mapping_hash,
		sizeof(attribute->mapping_hash));
	rh_put_u16le(bytes + 216, attribute->name_record_offset);
	rh_put_u16le(bytes + 218, (uint16_t)attribute->value_offset);
	rh_put_u16le(bytes + 220, attribute->mapping_pairs_offset);
}

static void rh_encode_hash_run(const struct rh_raw_run *run,
		unsigned char bytes[RH_RAW_HASH_RUN_BYTES])
{
	memset(bytes, 0, RH_RAW_HASH_RUN_BYTES);
	rh_put_u64le(bytes, run->attribute_index);
	rh_put_u64le(bytes + 8, (uint64_t)run->vcn);
	rh_put_u64le(bytes + 16, (uint64_t)run->lcn);
	rh_put_u64le(bytes + 24, run->length);
	bytes[32] = run->sparse;
}

static void rh_encode_hash_list(const struct rh_raw_mft_census *census,
		const struct rh_raw_attr_list_entry *entry,
		unsigned char bytes[RH_RAW_HASH_LIST_BYTES])
{
	unsigned char name_hash[32];

	memset(bytes, 0, RH_RAW_HASH_LIST_BYTES);
	rh_hash_name(census, entry->name_offset, entry->name_length, name_hash);
	rh_put_u64le(bytes, entry->owner.record);
	rh_put_u16le(bytes + 8, entry->owner.sequence);
	rh_put_u64le(bytes + 16, entry->storage.record);
	rh_put_u16le(bytes + 24, entry->storage.sequence);
	rh_put_u32le(bytes + 28, entry->type);
	rh_put_u64le(bytes + 32, (uint64_t)entry->lowest_vcn);
	rh_put_u16le(bytes + 40, entry->instance);
	bytes[42] = entry->name_length;
	bytes[43] = entry->matched;
	memcpy(bytes + 48, name_hash, sizeof(name_hash));
	rh_put_u64le(bytes + 80, entry->matched_attribute);
}

static void rh_encode_hash_file_name(const struct rh_raw_mft_census *census,
		const struct rh_raw_file_name *file_name,
		unsigned char bytes[RH_RAW_HASH_FILE_NAME_BYTES])
{
	unsigned char name_hash[32];

	memset(bytes, 0, RH_RAW_HASH_FILE_NAME_BYTES);
	rh_hash_name(census, file_name->name_offset, file_name->name_length,
		name_hash);
	rh_put_u64le(bytes, file_name->owner.record);
	rh_put_u16le(bytes + 8, file_name->owner.sequence);
	rh_put_u64le(bytes + 16, file_name->storage.record);
	rh_put_u16le(bytes + 24, file_name->storage.sequence);
	rh_put_u64le(bytes + 32, file_name->parent.record);
	rh_put_u16le(bytes + 40, file_name->parent.sequence);
	rh_put_u16le(bytes + 42, file_name->attribute_instance);
	rh_put_u32le(bytes + 44, file_name->record_value_offset);
	bytes[48] = file_name->name_namespace;
	bytes[49] = file_name->name_length;
	memcpy(bytes + 50, name_hash, sizeof(name_hash));
}

static void rh_encode_hash_layout(
		const struct rh_raw_layout_candidate *candidate,
		unsigned char bytes[RH_RAW_HASH_LAYOUT_BYTES])
{
	memset(bytes, 0, RH_RAW_HASH_LAYOUT_BYTES);
	rh_put_u32le(bytes, (uint32_t)candidate->reason);
	rh_put_u64le(bytes + 8, candidate->owner.record);
	rh_put_u16le(bytes + 16, candidate->owner.sequence);
	rh_put_u64le(bytes + 24, candidate->storage.record);
	rh_put_u16le(bytes + 32, candidate->storage.sequence);
	rh_put_u32le(bytes + 36, candidate->attribute_type);
	rh_put_u16le(bytes + 40, candidate->attribute_instance);
	rh_put_u32le(bytes + 44, candidate->logical_offset);
	rh_put_u32le(bytes + 48, candidate->length);
	memcpy(bytes + 56, candidate->before_hash, 32);
	memcpy(bytes + 88, candidate->after_hash, 32);
	memcpy(bytes + 120, candidate->logical_record_before_hash, 32);
	memcpy(bytes + 152, candidate->logical_record_after_hash, 32);
	bytes[184] = candidate->replacement_length;
	memcpy(bytes + 185, candidate->replacement,
		sizeof(candidate->replacement));
}

static void rh_encode_hash_header(const struct rh_raw_mft_census *census,
		unsigned char bytes[RH_RAW_HASH_HEADER_BYTES])
{
	static const unsigned char magic[8] = {
		'R', 'H', 'M', 'F', 'T', '1', 0, 0,
	};

	memset(bytes, 0, RH_RAW_HASH_HEADER_BYTES);
	memcpy(bytes, magic, sizeof(magic));
	rh_put_u64le(bytes + 8, census->slots_expected);
	rh_put_u64le(bytes + 16, census->slots_completed);
	rh_put_u64le(bytes + 24, census->live_base_records);
	rh_put_u64le(bytes + 32, census->live_extent_records);
	rh_put_u64le(bytes + 40, census->free_records);
	rh_put_u64le(bytes + 48, census->unreadable_records);
	rh_put_u64le(bytes + 56, census->invalid_records);
	rh_put_u64le(bytes + 64, census->attribute_count);
	rh_put_u64le(bytes + 72, census->resident_attributes);
	rh_put_u64le(bytes + 80, census->nonresident_attributes);
	rh_put_u64le(bytes + 88, census->run_count);
	rh_put_u64le(bytes + 96, census->list_entry_count);
	rh_put_u64le(bytes + 104, census->file_name_count);
	bytes[112] = census->records_complete;
	bytes[113] = census->attribute_lists_complete;
	bytes[114] = census->extents_complete;
	bytes[115] = census->records_bounded;
	bytes[116] = census->layout_complete;
	bytes[117] = census->compressed_header_tolerant;
	memcpy(bytes + 120, census->slot_hash, 32);
	memcpy(bytes + 152, census->attribute_hash, 32);
	memcpy(bytes + 184, census->run_hash, 32);
	memcpy(bytes + 216, census->attrlist_hash, 32);
	memcpy(bytes + 248, census->file_name_manifest_hash, 32);
	memcpy(bytes + 280, census->layout_hash, 32);
	rh_put_u64le(bytes + 312, census->layout_candidate_count);
}

static int rh_hash_census(struct rh_raw_mft_census *census)
{
	static const unsigned char opaque_tag[16] = {
		'R', 'H', 'M', 'F', 'T', '-', 'O', 'P', 'A', 'Q', 'U', 'E', 0, 0, 0, 1,
	};
	struct rh_hash_stream table;
	struct rh_hash_stream complete;
	unsigned char record[RH_RAW_HASH_ATTRIBUTE_BYTES];
	unsigned char header[RH_RAW_HASH_HEADER_BYTES];
	unsigned char opaque_header[24];
	unsigned char opaque_frame[40];
	size_t i;

	rh_hash_stream_init(&table);
	for (i = 0; i < census->slot_count; i++) {
		rh_encode_hash_slot(&census->slots[i], record);
		if (rh_hash_stream_update(&table, record, RH_RAW_HASH_SLOT_BYTES))
			return -1;
	}
	if (rh_hash_stream_final(&table, census->slot_hash))
		return -1;
	rh_hash_stream_init(&table);
	for (i = 0; i < census->attribute_count; i++) {
		rh_encode_hash_attribute(census, &census->attributes[i], record);
		if (rh_hash_stream_update(&table, record,
				RH_RAW_HASH_ATTRIBUTE_BYTES))
			return -1;
	}
	if (rh_hash_stream_final(&table, census->attribute_hash))
		return -1;
	rh_hash_stream_init(&table);
	for (i = 0; i < census->run_count; i++) {
		rh_encode_hash_run(&census->runs[i], record);
		if (rh_hash_stream_update(&table, record, RH_RAW_HASH_RUN_BYTES))
			return -1;
	}
	if (rh_hash_stream_final(&table, census->run_hash))
		return -1;
	rh_hash_stream_init(&table);
	for (i = 0; i < census->list_entry_count; i++) {
		rh_encode_hash_list(census, &census->list_entries[i], record);
		if (rh_hash_stream_update(&table, record, RH_RAW_HASH_LIST_BYTES))
			return -1;
	}
	if (rh_hash_stream_final(&table, census->attrlist_hash))
		return -1;
	rh_hash_stream_init(&table);
	for (i = 0; i < census->file_name_count; i++) {
		rh_encode_hash_file_name(census, &census->file_names[i], record);
		if (rh_hash_stream_update(&table, record,
				RH_RAW_HASH_FILE_NAME_BYTES))
			return -1;
	}
	if (rh_hash_stream_final(&table, census->file_name_manifest_hash))
		return -1;
	rh_hash_stream_init(&table);
	for (i = 0; i < census->layout_candidate_count; i++) {
		rh_encode_hash_layout(&census->layout_candidates[i], record);
		if (rh_hash_stream_update(&table, record, RH_RAW_HASH_LAYOUT_BYTES))
			return -1;
	}
	if (rh_hash_stream_final(&table, census->layout_hash))
		return -1;

	rh_encode_hash_header(census, header);
	rh_hash_stream_init(&complete);
	if (rh_hash_stream_update(&complete, header, sizeof(header)))
		return -1;
	for (i = 0; i < census->slot_count; i++) {
		rh_encode_hash_slot(&census->slots[i], record);
		if (rh_hash_stream_update(&complete, record,
				RH_RAW_HASH_SLOT_BYTES))
			return -1;
	}
	for (i = 0; i < census->attribute_count; i++) {
		rh_encode_hash_attribute(census, &census->attributes[i], record);
		if (rh_hash_stream_update(&complete, record,
				RH_RAW_HASH_ATTRIBUTE_BYTES))
			return -1;
	}
	for (i = 0; i < census->run_count; i++) {
		rh_encode_hash_run(&census->runs[i], record);
		if (rh_hash_stream_update(&complete, record,
				RH_RAW_HASH_RUN_BYTES))
			return -1;
	}
	for (i = 0; i < census->list_entry_count; i++) {
		rh_encode_hash_list(census, &census->list_entries[i], record);
		if (rh_hash_stream_update(&complete, record,
				RH_RAW_HASH_LIST_BYTES))
			return -1;
	}
	for (i = 0; i < census->file_name_count; i++) {
		rh_encode_hash_file_name(census, &census->file_names[i], record);
		if (rh_hash_stream_update(&complete, record,
				RH_RAW_HASH_FILE_NAME_BYTES))
			return -1;
	}
	for (i = 0; i < census->layout_candidate_count; i++) {
		rh_encode_hash_layout(&census->layout_candidates[i], record);
		if (rh_hash_stream_update(&complete, record,
				RH_RAW_HASH_LAYOUT_BYTES))
			return -1;
	}
	if (census->opaque_slots_complete) {
		memset(opaque_header, 0, sizeof(opaque_header));
		memcpy(opaque_header, opaque_tag, sizeof(opaque_tag));
		rh_put_u64le(opaque_header + 16, census->opaque_slot_count);
		if (rh_hash_stream_update(&complete, opaque_header,
				sizeof(opaque_header)))
			return -1;
		for (i = 0; i < census->opaque_slot_count; i++) {
			const struct rh_raw_opaque_slot_evidence *opaque =
				&census->opaque_slots[i];

			memset(opaque_frame, 0, sizeof(opaque_frame));
			rh_put_u64le(opaque_frame, opaque->record);
			memcpy(opaque_frame + 8, opaque->raw_before_hash, 32U);
			if (rh_hash_stream_update(&complete, opaque_frame,
					sizeof(opaque_frame)))
				return -1;
		}
	}
	return rh_hash_stream_final(&complete, census->census_hash);
}

static int rh_raw_attribute_matches_stream(
		const struct rh_raw_mft_census *census,
		const struct rh_raw_attribute *attribute,
		struct rh_raw_mft_ref owner, uint32_t type,
		const unsigned char *name_utf16le, uint16_t name_length)
{
	if (attribute->owner.record != owner.record ||
			attribute->owner.sequence != owner.sequence ||
			attribute->type != type || attribute->name_length != name_length)
		return 0;
	if (!name_length)
		return 1;
	return !memcmp(census->name_arena + attribute->name_offset,
		name_utf16le, (size_t)name_length * 2U);
}

int rh_raw_mft_map_stream_range(const struct rh_raw_mft_census *census,
		struct rh_raw_mft_ref owner, uint32_t type,
		const unsigned char *name_utf16le, uint16_t name_length,
		uint64_t logical_offset, uint64_t length, uint64_t *physical_offset)
{
	const uint64_t cluster_size = 4096U;
	uint64_t stream_size = 0, remaining = length, current = logical_offset;
	uint64_t first_physical = 0, completed = 0;
	size_t base_count = 0, stream_extents = 0;
	size_t i;

	if (!census || !physical_offset || !length || (!name_utf16le &&
			name_length) || !owner.sequence || !census->records_bounded ||
			!census->attribute_lists_complete || !census->extents_complete ||
			logical_offset > UINT64_MAX - length) {
		errno = EINVAL;
		return -1;
	}
	for (i = 0; i < census->attribute_count; i++) {
		const struct rh_raw_attribute *attribute = &census->attributes[i];

		if (!rh_raw_attribute_matches_stream(census, attribute, owner, type,
				name_utf16le, name_length))
			continue;
		if (!attribute->nonresident) {
			errno = EIO;
			return -1;
		}
		stream_extents++;
		if (!attribute->lowest_vcn) {
			if (attribute->data_size < 0) {
				errno = EIO;
				return -1;
			}
			base_count++;
			stream_size = (uint64_t)attribute->data_size;
		}
	}
	if (!stream_extents || base_count != 1U ||
			logical_offset + length > stream_size) {
		errno = EIO;
		return -1;
	}
	while (remaining) {
		const struct rh_raw_run *selected = NULL;
		uint64_t vcn = current / cluster_size;
		uint64_t within = current % cluster_size;
		uint64_t selected_end = 0, chunk, physical, physical_cluster;
		size_t matches = 0;

		for (i = 0; i < census->attribute_count; i++) {
			const struct rh_raw_attribute *attribute = &census->attributes[i];
			size_t run_index;

			if (!rh_raw_attribute_matches_stream(census, attribute, owner,
					type, name_utf16le, name_length))
				continue;
			for (run_index = 0; run_index < attribute->run_count;
					run_index++) {
				const struct rh_raw_run *run =
					&census->runs[attribute->run_first + run_index];
				uint64_t start, end;

				if (run->vcn < 0 || run->length > UINT64_MAX -
						(uint64_t)run->vcn)
					continue;
				start = (uint64_t)run->vcn;
				end = start + run->length;
				if (vcn < start || vcn >= end)
					continue;
				selected = run;
				selected_end = end;
				matches++;
			}
		}
		if (matches != 1U || !selected || selected->sparse ||
				selected->lcn < 0 || selected_end > UINT64_MAX /
				cluster_size || (uint64_t)selected->lcn >
				UINT64_MAX / cluster_size) {
			errno = EIO;
			return -1;
		}
		chunk = selected_end * cluster_size - current;
		if (chunk > remaining)
			chunk = remaining;
		if ((uint64_t)selected->lcn > UINT64_MAX -
				(vcn - (uint64_t)selected->vcn) ||
			(physical_cluster = (uint64_t)selected->lcn +
			 (vcn - (uint64_t)selected->vcn)) >
				(UINT64_MAX - within) / cluster_size) {
			errno = EOVERFLOW;
			return -1;
		}
		physical = physical_cluster * cluster_size + within;
		if (physical > UINT64_MAX - chunk ||
				(completed && (first_physical > UINT64_MAX - completed ||
				 physical != first_physical + completed))) {
			errno = EIO;
			return -1;
		}
		if (!completed)
			first_physical = physical;
		current += chunk;
		completed += chunk;
		remaining -= chunk;
	}
	*physical_offset = first_physical;
	return 0;
}

int rh_raw_mft_stream_pread_reader(const struct rh_census_reader *reader,
		const struct rh_raw_mft_census *census,
		struct rh_raw_mft_ref owner, uint32_t type,
		const unsigned char *name_utf16le, uint16_t name_length,
		uint64_t logical_offset, size_t length, unsigned char *buffer)
{
	const uint64_t cluster_size = 4096U;
	uint64_t stream_size = 0, current = logical_offset;
	size_t remaining = length, base_count = 0, stream_extents = 0, i;

	if (!reader || !census || !buffer || !length ||
			(!name_utf16le && name_length) || !owner.sequence ||
			!census->records_bounded || !census->attribute_lists_complete ||
			!census->extents_complete || logical_offset > UINT64_MAX - length) {
		errno = EINVAL;
		return -1;
	}
	for (i = 0; i < census->attribute_count; i++) {
		const struct rh_raw_attribute *attribute = &census->attributes[i];

		if (!rh_raw_attribute_matches_stream(census, attribute, owner, type,
				name_utf16le, name_length))
			continue;
		if (!attribute->nonresident) {
			errno = EIO;
			return -1;
		}
		stream_extents++;
		if (!attribute->lowest_vcn) {
			if (attribute->data_size < 0) {
				errno = EIO;
				return -1;
			}
			base_count++;
			stream_size = (uint64_t)attribute->data_size;
		}
	}
	if (!stream_extents || base_count != 1U ||
			logical_offset + length > stream_size) {
		errno = EIO;
		return -1;
	}
	while (remaining) {
		const struct rh_raw_run *selected = NULL;
		uint64_t vcn = current / cluster_size;
		uint64_t within = current % cluster_size;
		uint64_t selected_end = 0, chunk64;
		size_t chunk, matches = 0;

		for (i = 0; i < census->attribute_count; i++) {
			const struct rh_raw_attribute *attribute = &census->attributes[i];
			size_t run_index;

			if (!rh_raw_attribute_matches_stream(census, attribute, owner,
					type, name_utf16le, name_length))
				continue;
			for (run_index = 0; run_index < attribute->run_count; run_index++) {
				const struct rh_raw_run *run =
					&census->runs[attribute->run_first + run_index];
				uint64_t start, end;

				if (run->vcn < 0 || run->length > UINT64_MAX -
						(uint64_t)run->vcn)
					continue;
				start = (uint64_t)run->vcn;
				end = start + run->length;
				if (vcn < start || vcn >= end)
					continue;
				selected = run;
				selected_end = end;
				matches++;
			}
		}
		if (matches != 1U || !selected || selected_end >
				UINT64_MAX / cluster_size) {
			errno = EIO;
			return -1;
		}
		chunk64 = selected_end * cluster_size - current;
		chunk = chunk64 < remaining ? (size_t)chunk64 : remaining;
		if (selected->sparse) {
			memset(buffer + (length - remaining), 0, chunk);
		} else {
			uint64_t physical_cluster, physical;

			if (selected->lcn < 0 || (uint64_t)selected->lcn >
					UINT64_MAX - (vcn - (uint64_t)selected->vcn) ||
					(physical_cluster = (uint64_t)selected->lcn +
					 (vcn - (uint64_t)selected->vcn)) >
					(UINT64_MAX - within) / cluster_size) {
				errno = EOVERFLOW;
				return -1;
			}
			physical = physical_cluster * cluster_size + within;
			if (physical > reader->device_size ||
					chunk > reader->device_size - physical ||
					rh_census_reader_read_exact(reader, physical, chunk,
						buffer + (length - remaining)))
				return -1;
		}
		current += chunk;
		remaining -= chunk;
	}
	return 0;
}

int rh_raw_mft_stream_pread(struct rh_writer *writer,
		const struct rh_raw_mft_census *census,
		struct rh_raw_mft_ref owner, uint32_t type,
		const unsigned char *name_utf16le, uint16_t name_length,
		uint64_t logical_offset, size_t length, unsigned char *buffer)
{
	struct rh_census_reader reader;

	if (!writer || rh_census_reader_from_writer_prefix(writer,
			writer->operation_count, &reader))
		return -1;
	return rh_raw_mft_stream_pread_reader(&reader, census, owner, type,
		name_utf16le, name_length, logical_offset, length, buffer);
}

void rh_raw_mft_census_release(struct rh_raw_mft_census *census)
{
	if (!census)
		return;
	free(census->slots);
	free(census->attributes);
	free(census->runs);
	free(census->file_names);
	free(census->list_entries);
	free(census->layout_candidates);
	free(census->opaque_slots);
	free(census->name_arena);
	free(census->value_arena);
	memset(census, 0, sizeof(*census));
}

int rh_raw_mft_slot_count_from_size(uint64_t initialized_size,
		uint32_t record_size, size_t *slot_count)
{
	uint64_t count;

	if (!slot_count || !initialized_size || !record_size ||
			initialized_size % record_size) {
		errno = EINVAL;
		return -1;
	}
	count = initialized_size / record_size;
	if (!count || count > SIZE_MAX / sizeof(struct rh_raw_mft_slot)) {
		errno = EOVERFLOW;
		return -1;
	}
	*slot_count = (size_t)count;
	return 0;
}

static int rh_raw_mft_census_run_internal(struct _ntfs_volume *volume,
		const struct rh_census_reader *reader, uint64_t generation,
		const uint64_t *opaque_records, size_t opaque_record_count,
		int compressed_header_tolerant,
		struct rh_raw_mft_census *census)
{
	static const char canonical_upcase_hash[] =
		"41c26bc7a12bdaeb26025c93118697c7e3ef81ee048b00fe5cce2a472e0e0742";
	ntfschar *canonical_upcase = NULL;
	unsigned char *record = NULL, *raw_record = NULL;
	char upcase_hash[65];
	uint64_t record_number;
	size_t opaque_at = 0;
	u32 upcase_length;
	int assembly_ok = 0, extents_ok = 0;
	int has_opaque = opaque_record_count != 0;

	if (!volume || !reader || !generation || !census ||
			(has_opaque && !opaque_records) ||
			(has_opaque && !rh_census_reader_is_pretransaction(reader)) ||
			volume->sector_size != 512 || volume->cluster_size != 4096 ||
			volume->mft_record_size != 1024 || volume->indx_record_size != 4096 ||
			volume->nr_clusters <= 0 ||
			(uint64_t)volume->nr_clusters >
				(UINT64_C(256) << 30) / 4096U || !volume->mft_na ||
			volume->mft_na->initialized_size <= 0 ||
			volume->mft_na->initialized_size % volume->mft_record_size) {
		errno = EINVAL;
		return -1;
	}
	memset(census, 0, sizeof(*census));
	census->generation = generation;
	census->compressed_header_tolerant = !!compressed_header_tolerant;
	if (rh_raw_mft_slot_count_from_size(
			(uint64_t)volume->mft_na->initialized_size,
			volume->mft_record_size, &census->slot_count))
		return -1;
	census->slots_expected = census->slot_count;
	if (has_opaque) {
		size_t i;

		if (opaque_record_count > census->slot_count ||
				opaque_record_count > SIZE_MAX / sizeof(*census->opaque_slots)) {
			errno = EOVERFLOW;
			goto fatal;
		}
		census->opaque_slots = calloc(opaque_record_count,
			sizeof(*census->opaque_slots));
		if (!census->opaque_slots)
			goto fatal;
		census->opaque_slot_count = opaque_record_count;
		census->opaque_slot_capacity = opaque_record_count;
		for (i = 0; i < opaque_record_count; i++)
			census->opaque_slots[i].record = opaque_records[i];
		qsort(census->opaque_slots, opaque_record_count,
			sizeof(*census->opaque_slots), rh_opaque_record_compare);
		for (i = 0; i < opaque_record_count; i++)
			if (census->opaque_slots[i].record < FILE_first_user ||
					census->opaque_slots[i].record >= census->slots_expected ||
					(i && census->opaque_slots[i - 1U].record ==
					 census->opaque_slots[i].record)) {
				errno = EINVAL;
				goto fatal;
			}
	}
	census->slots = calloc(census->slot_count, sizeof(*census->slots));
	record = malloc(volume->mft_record_size);
	raw_record = malloc(volume->mft_record_size);
	upcase_length = ntfs_upcase_build_default(&canonical_upcase);
	if (!census->slots || !record || !raw_record || !canonical_upcase ||
			upcase_length != 65536U) {
		if (!errno)
			errno = EIO;
		goto fatal;
	}
	rh_sha256_hex(canonical_upcase, (size_t)upcase_length * sizeof(ntfschar),
		upcase_hash);
	if (strcmp(upcase_hash, canonical_upcase_hash)) {
		errno = EIO;
		goto fatal;
	}
	for (record_number = 0; record_number < census->slots_expected;
			record_number++) {
		struct rh_raw_mft_slot *slot = &census->slots[record_number];
		int error;

		slot->record = record_number;
		if (opaque_at < census->opaque_slot_count && record_number ==
				census->opaque_slots[opaque_at].record) {
			s64 got = ntfs_attr_pread(volume->mft_na,
				(s64)(record_number * (uint64_t)volume->mft_record_size),
				volume->mft_record_size, record);

			if (got != (s64)volume->mft_record_size) {
				if (got < 0 && (errno == ENOMEM || errno == EOVERFLOW))
					goto fatal;
				slot->state = RH_RAW_SLOT_UNREADABLE;
				census->unreadable_records++;
				continue;
			}
			slot->state = RH_RAW_SLOT_OPAQUE_FREE_CANDIDATE;
			census->opaque_records++;
			rh_sha256(record, volume->mft_record_size,
				census->opaque_slots[opaque_at].raw_before_hash);
			opaque_at++;
			census->slots_completed++;
			continue;
		}
		errno = 0;
		if (ntfs_attr_pread(volume->mft_na,
				(s64)(record_number * (uint64_t)volume->mft_record_size),
				volume->mft_record_size, raw_record) !=
					(s64)volume->mft_record_size ||
				!rh_raw_record_framing_valid(volume, raw_record)) {
			error = errno;
			if (error == ENOMEM || error == EOVERFLOW)
				goto fatal;
			slot->state = RH_RAW_SLOT_UNREADABLE;
			census->unreadable_records++;
			continue;
		}
		errno = 0;
		if (ntfs_mft_record_read(volume, record_number, (MFT_RECORD *)record)) {
			error = errno;
			if (error == ENOMEM || error == EOVERFLOW)
				goto fatal;
			if (rh_zero_initialized_free_slot(volume, record_number,
					record)) {
				slot->state = RH_RAW_SLOT_FREE;
				census->free_records++;
				census->slots_completed++;
				continue;
			}
			slot->state = RH_RAW_SLOT_UNREADABLE;
			census->unreadable_records++;
			continue;
		}
		if (!ntfs_is_file_record(((MFT_RECORD *)record)->magic) &&
				rh_zero_initialized_free_slot(volume, record_number, record)) {
			slot->state = RH_RAW_SLOT_FREE;
			census->free_records++;
			census->slots_completed++;
			continue;
		}
		errno = 0;
		if (rh_parse_record(volume, record_number, record, census,
				canonical_upcase, upcase_length)) {
			error = errno;
			if (error == ENOMEM || error == EOVERFLOW || error == E2BIG)
				goto fatal;
			slot->state = RH_RAW_SLOT_INVALID;
			census->invalid_records++;
			continue;
		}
		switch (slot->state) {
		case RH_RAW_SLOT_FREE:
			census->free_records++;
			break;
		case RH_RAW_SLOT_LIVE_BASE:
			census->live_base_records++;
			break;
		case RH_RAW_SLOT_LIVE_EXTENT:
			census->live_extent_records++;
			break;
		default:
			census->invalid_records++;
			slot->state = RH_RAW_SLOT_INVALID;
			continue;
		}
		census->slots_completed++;
	}
	census->records_bounded = census->slots_completed == census->slots_expected &&
		!census->unreadable_records && !census->invalid_records;
	census->opaque_slots_complete = has_opaque &&
		opaque_at == census->opaque_slot_count &&
		census->opaque_records == census->opaque_slot_count;
	census->layout_complete = !census->layout_candidate_count;
	census->records_complete = census->records_bounded &&
		census->layout_complete;
	for (record_number = 0; record_number < census->attribute_count;
			record_number++) {
		const struct rh_raw_attribute *attribute =
			&census->attributes[record_number];

		if (attribute->nonresident)
			census->nonresident_attributes++;
		else
			census->resident_attributes++;
		if (attribute->type >= 0x1000U)
			census->user_defined_attributes++;
		if (attribute->type == le32_to_cpu(AT_ATTRIBUTE_LIST))
			census->attribute_lists++;
		if (!attribute->nonresident && attribute->resident_flags &&
				attribute->type != le32_to_cpu(AT_FILE_NAME))
			census->indexed_resident_attributes++;
	}
	census->extents_expected = census->nonresident_attributes;
	census->runs_expected = census->run_count;
	census->runs_completed = census->run_count;
	census->file_name_links = census->file_name_count;
	if (census->records_bounded) {
		int assembly_result, names_result = -1, directories_result = -1;

		errno = 0;
		assembly_result = rh_assemble_attribute_lists(volume, reader, census,
			canonical_upcase, upcase_length);
		if (!assembly_result)
			names_result = rh_count_owned_file_names(census);
		if (!assembly_result && !names_result)
			directories_result = rh_validate_directory_shapes(census);
		if (!assembly_result && !names_result && !directories_result) {
			assembly_ok = 1;
			census->attribute_lists_complete = 1;
			census->attribute_list_entries = census->list_entry_count;
		} else if (errno == EIO || errno == ENOMEM || errno == EOVERFLOW ||
				errno == E2BIG) {
			goto fatal;
		}
		if (assembly_ok) {
			errno = 0;
			if (!rh_validate_stream_extents(volume, census)) {
				extents_ok = 1;
				census->extents_complete = 1;
			} else if (errno == ENOMEM || errno == EOVERFLOW || errno == E2BIG) {
				goto fatal;
			}
		}
	}
	if (!extents_ok)
		census->extents_completed = 0;
	census->layout_complete = !census->layout_candidate_count &&
		!census->compressed_header_mismatches;
	census->records_complete = census->records_bounded &&
		census->layout_complete;
	if (rh_hash_census(census))
		goto fatal;
	free(canonical_upcase);
	free(raw_record);
	free(record);
	return 0;
fatal:
	free(canonical_upcase);
	free(raw_record);
	free(record);
	rh_raw_mft_census_release(census);
	return -1;
}

int rh_raw_mft_census_run(struct _ntfs_volume *volume,
		struct rh_writer *writer, uint64_t generation,
		struct rh_raw_mft_census *census)
{
	struct rh_census_reader reader;

	if (!writer || rh_census_reader_from_writer_prefix(writer,
			writer->operation_count, &reader))
		return -1;
	return rh_raw_mft_census_run_internal(volume, &reader, generation, 0, 0,
		0, census);
}

int rh_raw_mft_census_run_reader(struct _ntfs_volume *volume,
		const struct rh_census_reader *reader, uint64_t generation,
		struct rh_raw_mft_census *census)
{
	return rh_raw_mft_census_run_internal(volume, reader, generation, 0, 0,
		0, census);
}

int rh_raw_mft_census_run_reader_compressed_headers(
		struct _ntfs_volume *volume, const struct rh_census_reader *reader,
		uint64_t generation, struct rh_raw_mft_census *census)
{
	return rh_raw_mft_census_run_internal(volume, reader, generation, 0, 0,
		1, census);
}

int rh_raw_mft_census_run_with_opaque_slots(struct _ntfs_volume *volume,
		struct rh_writer *writer, uint64_t generation,
		const uint64_t *opaque_records, size_t opaque_record_count,
		struct rh_raw_mft_census *census)
{
	struct rh_census_reader reader;

	if (!writer || writer->operation_count || writer->planned_bytes ||
			writer->last_verified_ordinal || writer->sync_count ||
			writer->write_boundaries || writer->commit_started ||
			writer->commit_completed || writer->write_fd >= 0 ||
			rh_writer_plan_checkpoint(writer) != 0U ||
			rh_census_reader_from_writer_prefix(writer, 0, &reader)) {
		if (!errno)
			errno = EINVAL;
		return -1;
	}
	return rh_raw_mft_census_run_internal(volume, &reader, generation,
		opaque_records, opaque_record_count, 0, census);
}

int rh_raw_mft_census_run_with_opaque_slots_reader(
		struct _ntfs_volume *volume, const struct rh_census_reader *reader,
		uint64_t generation, const uint64_t *opaque_records,
		size_t opaque_record_count, struct rh_raw_mft_census *census)
{
	return rh_raw_mft_census_run_internal(volume, reader, generation,
		opaque_records, opaque_record_count, 0, census);
}

int rh_raw_mft_census_run_with_opaque_slot(struct _ntfs_volume *volume,
		struct rh_writer *writer, uint64_t generation, uint64_t opaque_record,
		struct rh_raw_mft_census *census)
{
	return rh_raw_mft_census_run_with_opaque_slots(volume, writer, generation,
		&opaque_record, 1U, census);
}
