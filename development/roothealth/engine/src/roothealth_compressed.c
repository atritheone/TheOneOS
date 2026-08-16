/* ROOTHEALTH_REPAIR_ROLE(DIAGNOSTIC) ROOTHEALTH_IO_ROLE(READER) */
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
#include "mst.h"
#include "roothealth_compressed_internal.h"
#include "roothealth_hash_stream.h"
#include "roothealth_write.h"

#define RH_CLUSTER_BYTES UINT32_C(4096)
#define RH_LZNT1_SUBBLOCK UINT32_C(4096)
#define RH_LZNT1_SIZE_MASK UINT16_C(0x0fff)
#define RH_LZNT1_COMPRESSED UINT16_C(0x8000)

enum rh_compressed_field_kind {
	RH_COMPRESSED_FIELD_UNIT = 1,
	RH_COMPRESSED_FIELD_SIZE = 2,
};

struct rh_compressed_stream {
	struct rh_raw_mft_ref owner;
	size_t base_attribute;
	unsigned char *name;
	uint16_t name_length;
	uint8_t resident;
	uint64_t allocated_size;
	uint64_t data_size;
	uint64_t initialized_size;
	uint64_t physical_clusters;
	uint64_t unit_count;
	unsigned char name_hash[32];
};

struct rh_compressed_run_ref {
	size_t stream;
	const struct rh_raw_run *run;
};

struct rh_compressed_field {
	enum rh_compressed_field_kind kind;
	struct rh_raw_mft_ref owner;
	struct rh_raw_mft_ref storage;
	uint16_t attribute_instance;
	uint32_t logical_offset;
	uint8_t length;
	unsigned char before[8];
	unsigned char after[8];
};

#ifdef ROOTHEALTH_REPAIR_TESTING
static int rh_compressed_test_fail(const char *point)
{
	const char *selected = getenv("ROOTHEALTH_COMPRESSED_TEST_FAIL");

	return selected && !strcmp(selected, point);
}
#endif

static uint16_t rh_u16(const unsigned char *bytes)
{
	return (uint16_t)bytes[0] | (uint16_t)((uint16_t)bytes[1] << 8);
}

static uint32_t rh_u32(const unsigned char *bytes)
{
	return (uint32_t)bytes[0] | ((uint32_t)bytes[1] << 8) |
		((uint32_t)bytes[2] << 16) | ((uint32_t)bytes[3] << 24);
}

static void rh_put_u16(unsigned char *bytes, uint16_t value)
{
	bytes[0] = (unsigned char)value;
	bytes[1] = (unsigned char)(value >> 8);
}

static void rh_put_u32(unsigned char *bytes, uint32_t value)
{
	unsigned int i;

	for (i = 0; i < 4U; i++)
		bytes[i] = (unsigned char)(value >> (8U * i));
}

static void rh_put_u64(unsigned char *bytes, uint64_t value)
{
	unsigned int i;

	for (i = 0; i < 8U; i++)
		bytes[i] = (unsigned char)(value >> (8U * i));
}

static int rh_hash_zero(const unsigned char hash[32])
{
	unsigned int i;

	for (i = 0; i < 32U; i++)
		if (hash[i])
			return 0;
	return 1;
}

static int rh_add_u64(uint64_t *value, uint64_t add)
{
	if (*value > UINT64_MAX - add) {
		errno = EOVERFLOW;
		return -1;
	}
	*value += add;
	return 0;
}

static int rh_grow(void **items, size_t *capacity, size_t needed,
		size_t item_size)
{
	void *grown;
	size_t next;

	if (needed <= *capacity)
		return 0;
#ifdef ROOTHEALTH_REPAIR_TESTING
	if (rh_compressed_test_fail("grow")) {
		errno = ENOMEM;
		return -1;
	}
#endif
	if (!item_size || needed > SIZE_MAX / item_size) {
		errno = EOVERFLOW;
		return -1;
	}
	next = *capacity ? *capacity : 32U;
	while (next < needed) {
		if (next > SIZE_MAX / 2U) {
			next = needed;
			break;
		}
		next *= 2U;
	}
	if (next < needed || next > SIZE_MAX / item_size) {
		errno = EOVERFLOW;
		return -1;
	}
	grown = realloc(*items, next * item_size);
	if (!grown)
		return -1;
	*items = grown;
	*capacity = next;
	return 0;
}

static int rh_stream_compare(const void *left, const void *right)
{
	const struct rh_compressed_stream *a = left;
	const struct rh_compressed_stream *b = right;
	size_t bytes, common;
	int compared;

	if (a->owner.record != b->owner.record)
		return a->owner.record < b->owner.record ? -1 : 1;
	if (a->owner.sequence != b->owner.sequence)
		return a->owner.sequence < b->owner.sequence ? -1 : 1;
	bytes = (size_t)a->name_length * 2U;
	common = bytes < (size_t)b->name_length * 2U ? bytes :
		(size_t)b->name_length * 2U;
	compared = common ? memcmp(a->name, b->name, common) : 0;
	if (compared)
		return compared;
	return a->name_length < b->name_length ? -1 :
		a->name_length > b->name_length;
}

static int rh_run_ref_compare(const void *left, const void *right)
{
	const struct rh_compressed_run_ref *a = left;
	const struct rh_compressed_run_ref *b = right;

	if (a->stream != b->stream)
		return a->stream < b->stream ? -1 : 1;
	if (a->run->vcn != b->run->vcn)
		return a->run->vcn < b->run->vcn ? -1 : 1;
	return 0;
}

static int rh_field_compare(const void *left, const void *right)
{
	const struct rh_compressed_field *a = left;
	const struct rh_compressed_field *b = right;

	if (a->storage.record != b->storage.record)
		return a->storage.record < b->storage.record ? -1 : 1;
	if (a->storage.sequence != b->storage.sequence)
		return a->storage.sequence < b->storage.sequence ? -1 : 1;
	if (a->logical_offset != b->logical_offset)
		return a->logical_offset < b->logical_offset ? -1 : 1;
	return a->kind < b->kind ? -1 : a->kind > b->kind;
}

static int rh_raw_name(const struct rh_raw_mft_census *raw,
		const struct rh_raw_attribute *attribute,
		const unsigned char **name, size_t *bytes)
{
	size_t length = (size_t)attribute->name_length * 2U;

	if (attribute->name_offset > raw->name_arena_size ||
			length > raw->name_arena_size - attribute->name_offset) {
		errno = EUCLEAN;
		return -1;
	}
	*name = raw->name_arena + attribute->name_offset;
	*bytes = length;
	return 0;
}

static int rh_stream_find(const struct rh_compressed_stream *streams,
		size_t count, const struct rh_raw_mft_census *raw,
		const struct rh_raw_attribute *attribute, size_t *position)
{
	struct rh_compressed_stream target;
	const unsigned char *name;
	size_t bytes, low = 0, high = count;

	if (rh_raw_name(raw, attribute, &name, &bytes))
		return -1;
	(void)bytes;
	memset(&target, 0, sizeof(target));
	target.owner = attribute->owner;
	target.name = (unsigned char *)name;
	target.name_length = attribute->name_length;
	while (low < high) {
		size_t middle = low + (high - low) / 2U;
		int comparison = rh_stream_compare(&streams[middle], &target);

		if (comparison < 0)
			low = middle + 1U;
		else
			high = middle;
	}
	if (low >= count || rh_stream_compare(&streams[low], &target)) {
		errno = EUCLEAN;
		return -1;
	}
	*position = low;
	return 0;
}

/* Hardened local copy of the pinned ntfs-next LZNT1 receive-side decoder. */
static int rh_lznt1_decompress(unsigned char *destination,
		size_t destination_size, const unsigned char *source,
		size_t source_size)
{
	const unsigned char *cursor = source, *source_end;
	unsigned char *output = destination, *output_end;

	if (!destination || !source || destination_size != RH_COMPRESSED_UNIT_BYTES ||
			source_size > RH_COMPRESSED_UNIT_BYTES) {
		errno = EINVAL;
		return -1;
	}
	source_end = source + source_size;
	output_end = destination + destination_size;
	while (output < output_end) {
		const unsigned char *sub_end;
		unsigned char *sub_start = output;
		uint16_t header;

		if (cursor == source_end) {
			memset(output, 0, (size_t)(output_end - output));
			return 0;
		}
		if ((size_t)(source_end - cursor) < 2U) {
			errno = EOVERFLOW;
			return -1;
		}
		header = rh_u16(cursor);
		if (!header) {
			memset(output, 0, (size_t)(output_end - output));
			return 0;
		}
		/* Match the linked ntfs_decompress receive-side lower bound. */
		if ((size_t)(source_end - cursor) < 6U) {
			errno = EOVERFLOW;
			return -1;
		}
		if ((size_t)(output_end - output) < RH_LZNT1_SUBBLOCK) {
			errno = EOVERFLOW;
			return -1;
		}
		if ((size_t)(source_end - cursor) <
				(size_t)(header & RH_LZNT1_SIZE_MASK) + 3U) {
			errno = EOVERFLOW;
			return -1;
		}
		sub_end = cursor + (header & RH_LZNT1_SIZE_MASK) + 3U;
		cursor += 2U;
		if (!(header & RH_LZNT1_COMPRESSED)) {
			if ((size_t)(sub_end - cursor) != RH_LZNT1_SUBBLOCK) {
				errno = EOVERFLOW;
				return -1;
			}
			memcpy(output, cursor, RH_LZNT1_SUBBLOCK);
			output += RH_LZNT1_SUBBLOCK;
			cursor = sub_end;
			continue;
		}
		while (cursor < sub_end && output < sub_start + RH_LZNT1_SUBBLOCK) {
			unsigned char tag = *cursor++;
			unsigned int token;

			for (token = 0; token < 8U && cursor < sub_end &&
					output < sub_start + RH_LZNT1_SUBBLOCK;
					token++, tag >>= 1) {
				if (!(tag & 1U)) {
					if (output >= sub_start + RH_LZNT1_SUBBLOCK) {
						errno = EOVERFLOW;
						return -1;
					}
					*output++ = *cursor++;
				} else {
					uint16_t phrase, logarithm = 0, length, distance;
					size_t produced;

					if ((size_t)(sub_end - cursor) < 2U || output == sub_start) {
						errno = EOVERFLOW;
						return -1;
					}
					produced = (size_t)(output - sub_start);
					for (distance = (uint16_t)(produced - 1U);
							distance >= 0x10U; distance >>= 1)
						logarithm++;
					phrase = rh_u16(cursor);
					cursor += 2U;
					distance = (uint16_t)((phrase >> (12U - logarithm)) + 1U);
					length = (uint16_t)((phrase &
						(UINT16_C(0x0fff) >> logarithm)) + 3U);
					if (distance > produced || length >
							(size_t)(sub_start + RH_LZNT1_SUBBLOCK - output)) {
						errno = EOVERFLOW;
						return -1;
					}
					while (length--) {
						*output = *(output - distance);
						output++;
					}
				}
			}
		}
		/*
		 * The pinned receive-side decoder treats a full destination subblock
		 * as complete and ignores any remaining encoded bytes in that source
		 * subblock.  Producer-canonical trailing bytes are not required on read.
		 */
		if (output == sub_start + RH_LZNT1_SUBBLOCK)
			cursor = sub_end;
		if (cursor != sub_end || output > sub_start + RH_LZNT1_SUBBLOCK) {
			errno = EOVERFLOW;
			return -1;
		}
		if (output < sub_start + RH_LZNT1_SUBBLOCK) {
			memset(output, 0,
				(size_t)(sub_start + RH_LZNT1_SUBBLOCK - output));
			output = sub_start + RH_LZNT1_SUBBLOCK;
		}
	}
	return 0;
}

#ifdef ROOTHEALTH_REPAIR_TESTING
int rh_compressed_test_lznt1(unsigned char *destination,
		size_t destination_size, const unsigned char *source,
		size_t source_size)
{
	return rh_lznt1_decompress(destination, destination_size, source,
		source_size);
}
#endif

static int rh_field_add(struct rh_compressed_field **fields, size_t *count,
		size_t *capacity, enum rh_compressed_field_kind kind,
		const struct rh_raw_attribute *attribute, uint32_t field_offset,
		const unsigned char *before, const unsigned char *after, uint8_t length)
{
	struct rh_compressed_field *field;

	if (!length || length > 8U || *count == SIZE_MAX ||
			attribute->record_offset > UINT32_MAX - field_offset ||
			rh_grow((void **)fields, capacity, *count + 1U,
			sizeof(**fields)))
		return -1;
	field = &(*fields)[(*count)++];
	memset(field, 0, sizeof(*field));
	field->kind = kind;
	field->owner = attribute->owner;
	field->storage = attribute->storage;
	field->attribute_instance = attribute->instance;
	field->logical_offset = attribute->record_offset + field_offset;
	field->length = length;
	memcpy(field->before, before, length);
	memcpy(field->after, after, length);
	return 0;
}

static int rh_target_add(struct rh_compressed_census *census,
		const struct rh_compressed_record_target *target)
{
	if (census->target_count == SIZE_MAX ||
			rh_grow((void **)&census->targets, &census->target_capacity,
			census->target_count + 1U, sizeof(*census->targets)))
		return -1;
	census->targets[census->target_count++] = *target;
	return 0;
}

static int rh_si_flags(const struct rh_raw_mft_census *raw,
		uint32_t **flags_out)
{
	uint8_t *seen = NULL;
	uint32_t *flags = NULL;
	size_t i;

	if (raw->slot_count > SIZE_MAX / sizeof(*flags)) {
		errno = EOVERFLOW;
		return -1;
	}
	seen = calloc(raw->slot_count ? raw->slot_count : 1U, 1U);
	flags = calloc(raw->slot_count ? raw->slot_count : 1U, sizeof(*flags));
	if (!seen || !flags)
		goto fail;
	for (i = 0; i < raw->attribute_count; i++) {
		const struct rh_raw_attribute *attribute = &raw->attributes[i];
		const unsigned char *value;
		uint64_t record = attribute->owner.record;

		if (attribute->type != le32_to_cpu(AT_STANDARD_INFORMATION))
			continue;
		if (record >= raw->slot_count ||
				raw->slots[record].state != RH_RAW_SLOT_LIVE_BASE ||
				attribute->owner.sequence != raw->slots[record].sequence ||
				attribute->nonresident || attribute->name_length ||
				(attribute->value_length != 48U &&
				 attribute->value_length != 72U) ||
				attribute->value_arena_offset > raw->value_arena_size ||
				attribute->value_length > raw->value_arena_size -
					attribute->value_arena_offset || seen[record]) {
			errno = EUCLEAN;
			goto fail;
		}
		value = raw->value_arena + attribute->value_arena_offset;
		seen[record] = 1;
		flags[record] = rh_u32(value + 32U);
	}
	for (i = 0; i < raw->slot_count; i++)
		if (raw->slots[i].state == RH_RAW_SLOT_LIVE_BASE && !seen[i]) {
			errno = EUCLEAN;
			goto fail;
		}
	free(seen);
	*flags_out = flags;
	return 0;
fail:
	free(seen);
	free(flags);
	return -1;
}

static int rh_reconcile_si_data(const struct rh_raw_mft_census *raw,
		const uint32_t *si_flags, struct rh_compressed_census *census)
{
	uint8_t *compressed_owner = NULL, *nonempty_unnamed = NULL;
	size_t i;
	int result = -1;

	compressed_owner = calloc(raw->slot_count ? raw->slot_count : 1U, 1U);
	nonempty_unnamed = calloc(raw->slot_count ? raw->slot_count : 1U, 1U);
	if (!compressed_owner || !nonempty_unnamed)
		goto out;
	for (i = 0; i < raw->attribute_count; i++) {
		const struct rh_raw_attribute *attribute = &raw->attributes[i];
		uint16_t compression;
		uint64_t record;

		if (attribute->type != le32_to_cpu(AT_DATA))
			continue;
		record = attribute->owner.record;
		if (record >= raw->slot_count ||
			raw->slots[record].state != RH_RAW_SLOT_LIVE_BASE ||
			attribute->owner.sequence != raw->slots[record].sequence) {
			errno = EUCLEAN;
			goto out;
		}
		compression = attribute->flags & le16_to_cpu(ATTR_COMPRESSION_MASK);
		if (compression == le16_to_cpu(ATTR_IS_COMPRESSED)) {
			/* Pinned ntfs-next treats a resident compression mask as corrupt. */
			if (!attribute->nonresident) {
				errno = EUCLEAN;
				goto out;
			}
			compressed_owner[record] = 1;
			if (!attribute->name_length && !attribute->lowest_vcn &&
					attribute->initialized_size > 0)
				nonempty_unnamed[record] = 1;
		} else if (compression) {
			errno = EUCLEAN;
			goto out;
		}
	}
	for (i = 0; i < raw->slot_count; i++) {
		int si_compressed;

		if (raw->slots[i].state != RH_RAW_SLOT_LIVE_BASE)
			continue;
		si_compressed = !!(si_flags[i] &
			le32_to_cpu(FILE_ATTR_COMPRESSED));
		/* Only a non-empty compressed unnamed stream requires the SI cache bit. */
		if (nonempty_unnamed[i] && !si_compressed) {
			errno = EUCLEAN;
			goto out;
		}
		if (compressed_owner[i] &&
				rh_add_u64(&census->compressed_stream_owners, 1U))
			goto out;
		if (!si_compressed)
			continue;
		if (rh_add_u64(&census->si_compressed_records, 1U))
			goto out;
		if (raw->slots[i].flags & le16_to_cpu(MFT_RECORD_IS_DIRECTORY)) {
			if (rh_add_u64(&census->si_compressed_directories, 1U))
				goto out;
		} else if (!nonempty_unnamed[i] &&
				rh_add_u64(&census->si_compressed_intent_only_files, 1U)) {
				goto out;
		}
	}
	census->si_data_reconciled = 1;
	result = 0;
out:
	free(nonempty_unnamed);
	free(compressed_owner);
	return result;
}

static int rh_unit_hash_update(struct rh_hash_stream *table,
		const struct rh_compressed_stream *stream, uint64_t unit_vcn,
		uint64_t physical_clusters, uint64_t sparse_clusters,
		uint64_t initialized_bytes, uint64_t data_bytes, uint8_t topology,
		uint8_t payload_state, const unsigned char physical_hash[32],
		const unsigned char logical_hash[32])
{
	unsigned char frame[160];

	memset(frame, 0, sizeof(frame));
	rh_put_u64(frame, stream->owner.record);
	rh_put_u16(frame + 8U, stream->owner.sequence);
	rh_put_u64(frame + 16U, unit_vcn);
	rh_put_u64(frame + 24U, physical_clusters);
	rh_put_u64(frame + 32U, sparse_clusters);
	rh_put_u64(frame + 40U, initialized_bytes);
	rh_put_u64(frame + 48U, data_bytes);
	frame[56] = topology;
	frame[57] = payload_state;
	memcpy(frame + 64U, stream->name_hash, 32U);
	memcpy(frame + 96U, physical_hash, 32U);
	memcpy(frame + 128U, logical_hash, 32U);
	return rh_hash_stream_update(table, frame, sizeof(frame));
}

static int rh_census_hash(struct rh_compressed_census *census)
{
	struct rh_hash_stream hash;
	unsigned char header[288];
	size_t i;

	memset(header, 0, sizeof(header));
	memcpy(header, "RHCOMP1", 7U);
	rh_put_u32(header + 8U, census->version);
	rh_put_u64(header + 16U, census->generation);
	rh_put_u64(header + 24U, census->streams_expected);
	rh_put_u64(header + 32U, census->streams_examined);
	rh_put_u64(header + 40U, census->resident_streams);
	rh_put_u64(header + 48U, census->nonresident_streams);
	rh_put_u64(header + 56U, census->units_expected);
	rh_put_u64(header + 64U, census->units_examined);
	rh_put_u64(header + 72U, census->sparse_units);
	rh_put_u64(header + 80U, census->compressed_units);
	rh_put_u64(header + 88U, census->uncompressed_units);
	rh_put_u64(header + 96U, census->physical_clusters);
	rh_put_u64(header + 104U, census->sparse_clusters);
	rh_put_u64(header + 112U, census->initialized_bytes);
	rh_put_u64(header + 120U, census->data_bytes);
	rh_put_u64(header + 128U, census->payload_invalid);
	rh_put_u64(header + 136U, census->payload_ambiguous);
	rh_put_u64(header + 144U, census->topology_invalid);
	rh_put_u64(header + 152U, census->header_fields_mismatched);
	rh_put_u64(header + 160U, census->target_count);
	header[168] = census->raw_complete;
	header[169] = census->census_complete;
	header[170] = census->payloads_valid;
	header[171] = census->repair_authority_complete;
	header[172] = census->clean;
	header[173] = census->no_io_uncertainty;
	memcpy(header + 176U, census->raw_census_hash, 32U);
	memcpy(header + 208U, census->unit_manifest_hash, 32U);
	rh_put_u64(header + 240U, census->si_compressed_records);
	rh_put_u64(header + 248U, census->si_compressed_directories);
	rh_put_u64(header + 256U, census->si_compressed_intent_only_files);
	rh_put_u64(header + 264U, census->compressed_stream_owners);
	header[272] = census->si_data_reconciled;
	rh_hash_stream_init(&hash);
	if (rh_hash_stream_update(&hash, header, sizeof(header)) ||
			rh_hash_stream_update(&hash, census->repair_manifest_hash, 32U))
		return -1;
	for (i = 0; i < census->target_count; i++) {
		const struct rh_compressed_record_target *target = &census->targets[i];
		unsigned char frame[96];
		unsigned char digest[32];

		rh_sha256(target->logical_before, sizeof(target->logical_before), digest);
		if (memcmp(digest, target->before_hash, 32U)) {
			errno = EUCLEAN;
			return -1;
		}
		rh_sha256(target->logical_after, sizeof(target->logical_after), digest);
		if (memcmp(digest, target->after_hash, 32U)) {
			errno = EUCLEAN;
			return -1;
		}
		memset(frame, 0, sizeof(frame));
		rh_put_u64(frame, target->record);
		rh_put_u16(frame + 8U, target->sequence);
		rh_put_u64(frame + 16U, target->physical_offset);
		memcpy(frame + 24U, target->before_hash, 32U);
		memcpy(frame + 56U, target->after_hash, 32U);
		if (rh_hash_stream_update(&hash, frame, sizeof(frame)))
			return -1;
	}
	return rh_hash_stream_final(&hash, census->census_hash);
}

static int rh_build_record_targets(struct _ntfs_volume *volume,
		const struct rh_raw_mft_census *raw,
		struct rh_compressed_field *fields, size_t field_count,
		struct rh_compressed_census *census)
{
	struct rh_hash_stream table;
	struct rh_raw_mft_ref mft_owner;
	size_t at = 0;

	rh_hash_stream_init(&table);
	if (field_count > 1U)
		qsort(fields, field_count, sizeof(*fields), rh_field_compare);
	if (!raw->slot_count || raw->slots[0].state != RH_RAW_SLOT_LIVE_BASE ||
			!raw->slots[0].sequence) {
		errno = EUCLEAN;
		return -1;
	}
	mft_owner.record = 0;
	mft_owner.sequence = raw->slots[0].sequence;
	while (at < field_count) {
		struct rh_compressed_record_target target;
		uint64_t record = fields[at].storage.record;
		uint16_t sequence = fields[at].storage.sequence;
		size_t end = at, i;

		if (record <= 3U || record >= raw->slot_count || !sequence ||
			raw->slots[record].sequence != sequence ||
			(raw->slots[record].state != RH_RAW_SLOT_LIVE_BASE &&
			 raw->slots[record].state != RH_RAW_SLOT_LIVE_EXTENT) ||
			record > INT64_MAX / 1024U) {
			errno = EUCLEAN;
			return -1;
		}
		while (end < field_count && fields[end].storage.record == record) {
			if (fields[end].storage.sequence != sequence) {
				errno = EUCLEAN;
				return -1;
			}
			end++;
		}
		memset(&target, 0, sizeof(target));
		target.record = record;
		target.sequence = sequence;
		if (ntfs_attr_mst_pread(volume->mft_na, (s64)(record * 1024U), 1,
				1024U, target.logical_before) != 1) {
			return -1;
		}
		memcpy(target.logical_after, target.logical_before, 1024U);
		for (i = at; i < end; i++) {
			const struct rh_compressed_field *field = &fields[i];
			uint32_t field_end;

			if (field->logical_offset > UINT32_MAX - field->length ||
				(field_end = field->logical_offset + field->length) > 1024U ||
				(i > at && fields[i - 1U].logical_offset +
				 fields[i - 1U].length > field->logical_offset) ||
				memcmp(target.logical_after + field->logical_offset,
					field->before, field->length)) {
				errno = EUCLEAN;
				return -1;
			}
			memcpy(target.logical_after + field->logical_offset,
				field->after, field->length);
		}
		if (rh_raw_mft_map_stream_range(raw, mft_owner,
				le32_to_cpu(AT_DATA), NULL, 0, record * 1024U, 1024U,
				&target.physical_offset))
			return -1;
		rh_sha256(target.logical_before, 1024U, target.before_hash);
		rh_sha256(target.logical_after, 1024U, target.after_hash);
		if (!memcmp(target.before_hash, target.after_hash, 32U) ||
				rh_target_add(census, &target)) {
			if (!errno)
				errno = EUCLEAN;
			return -1;
		}
		at = end;
	}
	for (at = 0; at < census->target_count; at++) {
		unsigned char frame[80];
		const struct rh_compressed_record_target *target = &census->targets[at];

		memset(frame, 0, sizeof(frame));
		rh_put_u64(frame, target->record);
		rh_put_u16(frame + 8U, target->sequence);
		rh_put_u64(frame + 16U, target->physical_offset);
		memcpy(frame + 24U, target->before_hash, 32U);
		memcpy(frame + 56U, target->after_hash, 24U);
		if (rh_hash_stream_update(&table, frame, sizeof(frame)) ||
			rh_hash_stream_update(&table, target->after_hash + 24U, 8U))
			return -1;
	}
	return rh_hash_stream_final(&table, census->repair_manifest_hash);
}

static int rh_process_stream(const struct rh_census_reader *reader,
		const struct rh_compressed_stream *stream,
		const struct rh_compressed_run_ref *refs, size_t ref_count,
		struct rh_hash_stream *unit_table,
		struct rh_compressed_census *census)
{
	unsigned char physical[RH_COMPRESSED_UNIT_BYTES];
	unsigned char logical[RH_COMPRESSED_UNIT_BYTES];
	uint64_t cluster_count, unit;
	size_t run_at = 0;

	if (stream->resident)
		return 0;
	if (stream->allocated_size % RH_COMPRESSED_UNIT_BYTES) {
		errno = EUCLEAN;
		return -1;
	}
	cluster_count = stream->allocated_size / RH_CLUSTER_BYTES;
	if (stream->unit_count != cluster_count / RH_COMPRESSED_UNIT_CLUSTERS ||
			cluster_count % RH_COMPRESSED_UNIT_CLUSTERS) {
		errno = EUCLEAN;
		return -1;
	}
	for (unit = 0; unit < stream->unit_count; unit++) {
		uint64_t unit_start = unit * RH_COMPRESSED_UNIT_CLUSTERS;
		uint64_t cursor = unit_start, unit_end = unit_start +
			RH_COMPRESSED_UNIT_CLUSTERS;
		uint64_t physical_clusters = 0, sparse_clusters = 0;
		uint64_t data_bytes = 0, initialized_bytes = 0;
		size_t physical_bytes = 0;
		unsigned char physical_hash[32], logical_hash[32];
		uint8_t topology = 0, payload_state = 1;
		int sparse_seen = 0, topology_bad = 0;

		memset(physical, 0, sizeof(physical));
		memset(logical, 0, sizeof(logical));
		while (cursor < unit_end) {
			const struct rh_raw_run *run;
			uint64_t run_start, run_end, take, within;

			while (run_at < ref_count && refs[run_at].run->vcn >= 0 &&
				(uint64_t)refs[run_at].run->vcn + refs[run_at].run->length <=
				cursor)
				run_at++;
			if (run_at >= ref_count || refs[run_at].run->vcn < 0) {
				topology_bad = 1;
				break;
			}
			run = refs[run_at].run;
			run_start = (uint64_t)run->vcn;
			if (run->length > UINT64_MAX - run_start || run_start > cursor) {
				topology_bad = 1;
				break;
			}
			run_end = run_start + run->length;
			within = cursor - run_start;
			take = run_end - cursor;
			if (take > unit_end - cursor)
				take = unit_end - cursor;
			if (run->sparse) {
				sparse_seen = 1;
				sparse_clusters += take;
			} else {
				uint64_t lcn, byte_offset, byte_length;

				if (sparse_seen || run->lcn < 0 ||
					(uint64_t)run->lcn > UINT64_MAX - within) {
					topology_bad = 1;
					break;
				}
				lcn = (uint64_t)run->lcn + within;
				if (lcn > UINT64_MAX / RH_CLUSTER_BYTES ||
					take > UINT64_MAX / RH_CLUSTER_BYTES) {
					errno = EOVERFLOW;
					return -1;
				}
				byte_offset = lcn * RH_CLUSTER_BYTES;
				byte_length = take * RH_CLUSTER_BYTES;
				if (byte_length > sizeof(physical) - physical_bytes ||
					byte_offset > reader->device_size ||
					byte_length > reader->device_size - byte_offset ||
					rh_census_reader_read_exact(reader, byte_offset,
						(size_t)byte_length, physical + physical_bytes))
					return -1;
				physical_bytes += (size_t)byte_length;
				physical_clusters += take;
			}
			cursor += take;
		}
		if (cursor != unit_end || physical_clusters + sparse_clusters !=
				RH_COMPRESSED_UNIT_CLUSTERS)
			topology_bad = 1;
		if (unit * RH_COMPRESSED_UNIT_BYTES < stream->data_size) {
			data_bytes = stream->data_size - unit * RH_COMPRESSED_UNIT_BYTES;
			if (data_bytes > RH_COMPRESSED_UNIT_BYTES)
				data_bytes = RH_COMPRESSED_UNIT_BYTES;
		}
		if (unit * RH_COMPRESSED_UNIT_BYTES < stream->initialized_size) {
			initialized_bytes = stream->initialized_size -
				unit * RH_COMPRESSED_UNIT_BYTES;
			if (initialized_bytes > RH_COMPRESSED_UNIT_BYTES)
				initialized_bytes = RH_COMPRESSED_UNIT_BYTES;
		}
		rh_sha256(physical, physical_bytes, physical_hash);
		if (topology_bad) {
			if (rh_add_u64(&census->topology_invalid, 1U))
				return -1;
			payload_state = 0;
		} else if (!physical_clusters) {
			topology = 1;
			if (rh_add_u64(&census->sparse_units, 1U))
				return -1;
		} else if (physical_clusters == RH_COMPRESSED_UNIT_CLUSTERS &&
				!sparse_clusters) {
			topology = 3;
			if (rh_add_u64(&census->uncompressed_units, 1U))
				return -1;
			memcpy(logical, physical, sizeof(logical));
		} else if (physical_clusters < RH_COMPRESSED_UNIT_CLUSTERS &&
				sparse_clusters == RH_COMPRESSED_UNIT_CLUSTERS -
				physical_clusters) {
			topology = 2;
			if (rh_add_u64(&census->compressed_units, 1U))
				return -1;
			if (!initialized_bytes) {
				if (rh_add_u64(&census->payload_ambiguous, 1U))
					return -1;
				payload_state = 2;
			} else if (rh_lznt1_decompress(logical, sizeof(logical), physical,
					physical_bytes)) {
				if (rh_add_u64(&census->payload_invalid, 1U))
					return -1;
				payload_state = 0;
			}
		} else {
			if (rh_add_u64(&census->topology_invalid, 1U))
				return -1;
			payload_state = 0;
		}
		rh_sha256(logical, sizeof(logical), logical_hash);
		if (rh_add_u64(&census->physical_clusters, physical_clusters) ||
			rh_add_u64(&census->sparse_clusters, sparse_clusters) ||
			rh_add_u64(&census->initialized_bytes, initialized_bytes) ||
			rh_add_u64(&census->data_bytes, data_bytes) ||
			rh_add_u64(&census->units_examined, 1U) ||
			rh_unit_hash_update(unit_table, stream, unit_start,
				physical_clusters, sparse_clusters, initialized_bytes,
				data_bytes, topology, payload_state, physical_hash,
				logical_hash))
			return -1;
	}
	return 0;
}

static void rh_streams_destroy(struct rh_compressed_stream *streams,
		size_t count)
{
	size_t i;

	for (i = 0; i < count; i++)
		free(streams[i].name);
	free(streams);
}

static int rh_compressed_build(const struct rh_census_reader *reader,
		struct _ntfs_volume *volume, const struct rh_raw_mft_census *raw,
		uint64_t generation, struct rh_compressed_census *census)
{
	struct rh_compressed_stream *streams = NULL;
	struct rh_compressed_run_ref *refs = NULL;
	struct rh_compressed_field *fields = NULL;
	uint32_t *si_flags = NULL;
	size_t stream_count = 0, stream_capacity = 0;
	size_t ref_count = 0, ref_capacity = 0;
	size_t field_count = 0, field_capacity = 0;
	struct rh_hash_stream unit_table;
	uint64_t mismatch_seen = 0;
	size_t i, ref_at = 0;
	int result = -1;

	if (!reader || !reader->context || !reader->read || !volume || !raw ||
			!generation || raw->generation != generation ||
			!raw->compressed_header_tolerant || !raw->records_bounded ||
			!raw->attribute_lists_complete || !raw->extents_complete ||
			raw->slots_completed != raw->slots_expected ||
			raw->unreadable_records || raw->invalid_records ||
			raw->opaque_slot_count || raw->layout_candidate_count ||
			rh_hash_zero(raw->census_hash)) {
		errno = EINVAL;
		return -1;
	}
	memset(census, 0, sizeof(*census));
	census->magic = RH_COMPRESSED_CENSUS_MAGIC;
	census->version = RH_COMPRESSED_CENSUS_VERSION;
	census->generation = generation;
	census->raw_complete = raw->records_bounded &&
		raw->attribute_lists_complete && raw->extents_complete;
	memcpy(census->raw_census_hash, raw->census_hash, 32U);
	if (rh_si_flags(raw, &si_flags))
		goto out;
	if (rh_reconcile_si_data(raw, si_flags, census))
		goto out;
	for (i = 0; i < raw->attribute_count; i++) {
		const struct rh_raw_attribute *attribute = &raw->attributes[i];
		struct rh_compressed_stream *stream;
		const unsigned char *name;
		size_t name_bytes;

		if (attribute->type != le32_to_cpu(AT_DATA) ||
			(attribute->flags & le16_to_cpu(ATTR_COMPRESSION_MASK)) !=
				le16_to_cpu(ATTR_IS_COMPRESSED) ||
			(attribute->nonresident && attribute->lowest_vcn))
			continue;
		if (attribute->owner.record >= raw->slot_count ||
			raw->slots[attribute->owner.record].state !=
				RH_RAW_SLOT_LIVE_BASE ||
			attribute->owner.sequence !=
				raw->slots[attribute->owner.record].sequence ||
			rh_raw_name(raw, attribute, &name, &name_bytes) ||
				stream_count == SIZE_MAX ||
				rh_grow((void **)&streams, &stream_capacity, stream_count + 1U,
				sizeof(*streams))) {
			if (!errno)
				errno = EUCLEAN;
			goto out;
		}
		stream = &streams[stream_count++];
		memset(stream, 0, sizeof(*stream));
		stream->owner = attribute->owner;
		stream->base_attribute = i;
		stream->name_length = attribute->name_length;
		stream->name = malloc(name_bytes ? name_bytes : 1U);
		if (!stream->name)
			goto out;
		if (name_bytes)
			memcpy(stream->name, name, name_bytes);
		rh_sha256(name, name_bytes, stream->name_hash);
		stream->resident = !attribute->nonresident;
		if (attribute->nonresident) {
			if (attribute->allocated_size < 0 || attribute->data_size < 0 ||
				attribute->initialized_size < 0 ||
				attribute->initialized_size > attribute->data_size) {
				errno = EUCLEAN;
				goto out;
			}
			stream->allocated_size = (uint64_t)attribute->allocated_size;
			stream->data_size = (uint64_t)attribute->data_size;
			stream->initialized_size =
				(uint64_t)attribute->initialized_size;
			if (stream->allocated_size % RH_COMPRESSED_UNIT_BYTES) {
				errno = EUCLEAN;
				goto out;
			}
			stream->unit_count = stream->allocated_size /
				RH_COMPRESSED_UNIT_BYTES;
		}
	}
	if (stream_count > 1U)
		qsort(streams, stream_count, sizeof(*streams), rh_stream_compare);
	for (i = 1; i < stream_count; i++)
		if (!rh_stream_compare(&streams[i - 1U], &streams[i])) {
			errno = EUCLEAN;
			goto out;
		}
	census->streams_expected = stream_count;
	for (i = 0; i < raw->attribute_count; i++) {
		const struct rh_raw_attribute *attribute = &raw->attributes[i];
		size_t stream_index, j;

		if (attribute->compression_unit_mismatch ||
			attribute->compressed_size_mismatch) {
			if (attribute->type != le32_to_cpu(AT_DATA) ||
				!(attribute->flags & le16_to_cpu(ATTR_IS_COMPRESSED))) {
				errno = EUCLEAN;
				goto out;
			}
		}
		if (attribute->type != le32_to_cpu(AT_DATA) ||
			(attribute->flags & le16_to_cpu(ATTR_COMPRESSION_MASK)) !=
				le16_to_cpu(ATTR_IS_COMPRESSED))
			continue;
		if (rh_stream_find(streams, stream_count, raw, attribute,
				&stream_index))
			goto out;
		if (!!attribute->nonresident == !!streams[stream_index].resident) {
			errno = EUCLEAN;
			goto out;
		}
		if (attribute->run_first > raw->run_count ||
				attribute->run_count > raw->run_count - attribute->run_first) {
			errno = EUCLEAN;
			goto out;
		}
		if (attribute->compression_unit_mismatch) {
			unsigned char before = attribute->compression_unit;
			unsigned char after = STANDARD_COMPRESSION_UNIT;

			if (rh_field_add(&fields, &field_count, &field_capacity,
					RH_COMPRESSED_FIELD_UNIT, attribute,
					offsetof(ATTR_RECORD, compression_unit), &before, &after, 1U))
				goto out;
			if (rh_add_u64(&mismatch_seen, 1U))
				goto out;
		}
		for (j = 0; j < attribute->run_count; j++) {
			const struct rh_raw_run *run =
				&raw->runs[attribute->run_first + j];

			if (run->attribute_index != i) {
				errno = EUCLEAN;
				goto out;
			}
			if (ref_count == SIZE_MAX ||
					rh_grow((void **)&refs, &ref_capacity, ref_count + 1U,
					sizeof(*refs)))
				goto out;
			refs[ref_count].stream = stream_index;
			refs[ref_count].run = run;
			if (!refs[ref_count].run->sparse &&
				rh_add_u64(&streams[stream_index].physical_clusters,
					refs[ref_count].run->length))
				goto out;
			ref_count++;
		}
	}
	/* Compressed-size candidates require the complete run total. */
	for (i = 0; i < raw->attribute_count; i++) {
		const struct rh_raw_attribute *attribute = &raw->attributes[i];
		size_t stream_index;
		unsigned char before[8], after[8];
		uint64_t expected;

		if (!attribute->compressed_size_mismatch)
			continue;
		if (rh_stream_find(streams, stream_count, raw, attribute,
				&stream_index) || attribute->lowest_vcn ||
			streams[stream_index].physical_clusters >
				UINT64_MAX / RH_CLUSTER_BYTES) {
			errno = EUCLEAN;
			goto out;
		}
		expected = streams[stream_index].physical_clusters * RH_CLUSTER_BYTES;
		rh_put_u64(before, (uint64_t)attribute->compressed_size);
		rh_put_u64(after, expected);
		if (rh_field_add(&fields, &field_count, &field_capacity,
				RH_COMPRESSED_FIELD_SIZE, attribute,
				offsetof(ATTR_RECORD, compressed_size), before, after, 8U))
			goto out;
		if (rh_add_u64(&mismatch_seen, 1U))
			goto out;
	}
	if (mismatch_seen != raw->compressed_header_mismatches ||
		mismatch_seen != field_count) {
		errno = EUCLEAN;
		goto out;
	}
	if (ref_count > 1U)
		qsort(refs, ref_count, sizeof(*refs), rh_run_ref_compare);
	rh_hash_stream_init(&unit_table);
	for (i = 0; i < stream_count; i++) {
		size_t start = ref_at;

		while (ref_at < ref_count && refs[ref_at].stream == i)
			ref_at++;
		if (streams[i].resident) {
			if (rh_add_u64(&census->resident_streams, 1U))
				goto out;
			if (ref_at != start) {
				errno = EUCLEAN;
				goto out;
			}
		} else {
			if (rh_add_u64(&census->nonresident_streams, 1U))
				goto out;
			if (rh_add_u64(&census->units_expected,
					streams[i].unit_count) ||
				rh_process_stream(reader, &streams[i], ref_count ? refs + start :
					NULL,
					ref_at - start, &unit_table, census))
				goto out;
		}
		if (rh_add_u64(&census->streams_examined, 1U))
			goto out;
	}
	if (ref_at != ref_count || rh_hash_stream_final(&unit_table,
			census->unit_manifest_hash)) {
		errno = EUCLEAN;
		goto out;
	}
	census->header_fields_mismatched = mismatch_seen;
	census->census_complete = census->streams_examined ==
		census->streams_expected && census->units_examined ==
		census->units_expected;
	census->payloads_valid = !census->payload_invalid &&
		!census->payload_ambiguous && !census->topology_invalid;
	if (census->payloads_valid) {
		if (rh_build_record_targets(volume, raw, fields, field_count, census))
			goto out;
	} else {
		struct rh_hash_stream empty;

		rh_hash_stream_init(&empty);
		if (rh_hash_stream_final(&empty, census->repair_manifest_hash))
			goto out;
	}
	census->no_io_uncertainty = 1;
	census->repair_authority_complete = census->raw_complete &&
		census->census_complete && census->payloads_valid &&
		census->si_data_reconciled &&
		census->header_fields_mismatched ==
			raw->compressed_header_mismatches &&
		(!census->header_fields_mismatched || census->target_count);
	census->clean = census->repair_authority_complete &&
		!census->header_fields_mismatched;
	if (rh_census_hash(census))
		goto out;
	result = 0;
out:
	free(si_flags);
	rh_streams_destroy(streams, stream_count);
	free(refs);
	free(fields);
	return result;
}

int rh_compressed_census_internal_valid(
		const struct rh_compressed_census *census)
{
	struct rh_compressed_census copy;

	if (!census || census->magic != RH_COMPRESSED_CENSUS_MAGIC ||
		census->version != RH_COMPRESSED_CENSUS_VERSION ||
		rh_hash_zero(census->census_hash))
		return 0;
	copy = *census;
	if (rh_census_hash(&copy))
		return 0;
	return !memcmp(copy.census_hash, census->census_hash, 32U);
}

int rh_compressed_census_run(const struct rh_census_reader *reader,
		struct _ntfs_volume *volume, const struct rh_raw_mft_census *raw,
		uint64_t generation, struct rh_compressed_census **output)
{
	struct rh_compressed_census *census;

	if (output)
		*output = NULL;
	if (!output) {
		errno = EINVAL;
		return -1;
	}
#ifdef ROOTHEALTH_REPAIR_TESTING
	if (rh_compressed_test_fail("census")) {
		errno = ENOMEM;
		return -1;
	}
#endif
	census = calloc(1, sizeof(*census));
	if (!census)
		return -1;
	if (rh_compressed_build(reader, volume, raw, generation, census)) {
		rh_compressed_census_destroy(census);
		return -1;
	}
	*output = census;
	return 0;
}

void rh_compressed_census_destroy(struct rh_compressed_census *census)
{
	if (!census)
		return;
	free(census->targets);
	memset(census, 0, sizeof(*census));
	free(census);
}

int rh_compressed_census_get_view(const struct rh_compressed_census *census,
		struct rh_compressed_census_view *view)
{
	if (!view || !rh_compressed_census_internal_valid(census)) {
		errno = EINVAL;
		return -1;
	}
	memset(view, 0, sizeof(*view));
	view->version = census->version;
	view->generation = census->generation;
	view->streams_expected = census->streams_expected;
	view->streams_examined = census->streams_examined;
	view->resident_streams = census->resident_streams;
	view->nonresident_streams = census->nonresident_streams;
	view->units_expected = census->units_expected;
	view->units_examined = census->units_examined;
	view->sparse_units = census->sparse_units;
	view->compressed_units = census->compressed_units;
	view->uncompressed_units = census->uncompressed_units;
	view->physical_clusters = census->physical_clusters;
	view->sparse_clusters = census->sparse_clusters;
	view->initialized_bytes = census->initialized_bytes;
	view->data_bytes = census->data_bytes;
	view->si_compressed_records = census->si_compressed_records;
	view->si_compressed_directories = census->si_compressed_directories;
	view->si_compressed_intent_only_files =
		census->si_compressed_intent_only_files;
	view->compressed_stream_owners = census->compressed_stream_owners;
	view->payload_invalid = census->payload_invalid;
	view->payload_ambiguous = census->payload_ambiguous;
	view->topology_invalid = census->topology_invalid;
	view->header_fields_mismatched = census->header_fields_mismatched;
	view->repair_record_count = census->target_count;
	view->raw_complete = census->raw_complete;
	view->census_complete = census->census_complete;
	view->payloads_valid = census->payloads_valid;
	view->repair_authority_complete = census->repair_authority_complete;
	view->clean = census->clean;
	view->no_io_uncertainty = census->no_io_uncertainty;
	view->si_data_reconciled = census->si_data_reconciled;
	memcpy(view->raw_census_hash, census->raw_census_hash, 32U);
	memcpy(view->unit_manifest_hash, census->unit_manifest_hash, 32U);
	memcpy(view->repair_manifest_hash, census->repair_manifest_hash, 32U);
	memcpy(view->census_hash, census->census_hash, 32U);
	return 0;
}
