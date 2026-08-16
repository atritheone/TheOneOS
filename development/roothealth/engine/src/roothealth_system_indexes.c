/* ROOTHEALTH_REPAIR_ROLE(DIAGNOSTIC) ROOTHEALTH_IO_ROLE(READER) */
#include "config.h"

#include <errno.h>
#include <limits.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include "endians.h"
#include "layout.h"
#include "mst.h"
#include "roothealth_free_slot_authority_internal.h"
#include "roothealth_hash_stream.h"
#include "roothealth_complete_census.h"
#include "roothealth_namespace.h"
#include "roothealth_system_indexes.h"
#include "roothealth_system_indexes_internal.h"
#include "roothealth_write.h"

#define RH_SYSTEM_INDEX_BLOCK UINT32_C(4096)
#define RH_SYSTEM_INDEX_SECTOR UINT32_C(512)
#define RH_REPARSE_MAXIMUM_SIZE UINT32_C(16384)
#define RH_SYSTEM_INDEX_CENSUS_MAGIC UINT64_C(0x5248535953494458)

static const unsigned char rh_name_r[] = { '$', 0, 'R', 0 };
static const unsigned char rh_name_o[] = { '$', 0, 'O', 0 };
static const unsigned char rh_name_q[] = { '$', 0, 'Q', 0 };

struct rh_reparse_fact {
	uint32_t tag;
	struct rh_raw_mft_ref file;
	struct rh_raw_mft_ref storage;
	uint16_t attribute_instance;
	uint64_t value_length;
	unsigned char value_hash[32];
};

struct rh_objid_fact {
	unsigned char object_id[16];
	struct rh_raw_mft_ref file;
	struct rh_raw_mft_ref storage;
	uint16_t attribute_instance;
	uint8_t attribute_has_extended_info;
	uint8_t extended_info_authoritative;
	unsigned char extended_info[48];
	unsigned char value_hash[32];
};

struct rh_quota_fact {
	uint32_t owner_id;
	uint32_t version;
	uint32_t flags;
	uint64_t bytes_used;
	int64_t change_time;
	int64_t threshold;
	int64_t limit;
	int64_t exceeded_time;
	size_t sid_offset;
	uint16_t sid_length;
	unsigned char value_hash[32];
};

struct rh_system_index_census {
	uint64_t magic;
	uint32_t version;
	uint64_t generation;
	uint64_t mft_records_expected;
	uint64_t mft_records_examined;
	uint64_t attributes_expected;
	uint64_t attributes_examined;
	uint64_t file_name_links_expected;
	uint64_t file_name_links_examined;
	uint64_t standard_information_examined;
	uint64_t quota_owner_references_examined;
	uint64_t quota_owner_references_resolved;
	uint64_t index_entries_examined;
	uint64_t index_end_entries_examined;
	uint64_t index_blocks_examined;
	uint64_t index_blocks_reachable;
	uint8_t records_complete;
	uint8_t attributes_complete;
	uint8_t namespace_reciprocity_complete;
	uint8_t reparse_authority_complete;
	uint8_t objid_authority_complete;
	uint8_t quota_authority_complete;
	uint8_t no_io_uncertainty;
	uint8_t complete;
	struct rh_reparse_fact *reparse;
	size_t reparse_count;
	size_t reparse_capacity;
	struct rh_objid_fact *objid;
	size_t objid_count;
	size_t objid_capacity;
	struct rh_quota_fact *quota;
	size_t quota_count;
	size_t quota_capacity;
	unsigned char *sid_arena;
	size_t sid_arena_size;
	size_t sid_arena_capacity;
	struct rh_free_slot_reference *reparse_references;
	size_t reparse_reference_count;
	struct rh_free_slot_reference *objid_references;
	size_t objid_reference_count;
	struct rh_free_slot_reference *quota_source_references;
	size_t quota_source_reference_count;
	struct rh_system_index_state index[RH_SYSTEM_INDEX_COUNT];
	unsigned char raw_census_hash[32];
	unsigned char namespace_census_hash[32];
	unsigned char reparse_manifest_hash[32];
	unsigned char objid_manifest_hash[32];
	unsigned char quota_manifest_hash[32];
	unsigned char namespace_reciprocity_hash[32];
	unsigned char census_hash[32];
};

struct rh_index_item {
	enum rh_system_index_kind kind;
	unsigned char *key;
	unsigned char *data;
	size_t key_length;
	size_t data_length;
};

struct rh_index_manifest {
	struct rh_index_item *items;
	size_t count;
	size_t capacity;
};

struct rh_index_walk_frame {
	unsigned char *owned_block;
	const unsigned char *cursor;
	const unsigned char *end;
	uint8_t child_visited;
};

struct rh_index_walk {
	const struct rh_census_reader *reader;
	struct _ntfs_volume *volume;
	const struct rh_raw_mft_census *raw;
	struct rh_raw_mft_ref owner;
	enum rh_system_index_kind kind;
	const unsigned char *name;
	uint16_t name_length;
	uint64_t block_count;
	unsigned char *visited;
	size_t visited_size;
	unsigned char *previous_key;
	size_t previous_key_length;
	struct rh_index_manifest *manifest;
	struct rh_system_index_state *state;
};

static uint16_t rh_u16(const unsigned char *bytes)
{
	return (uint16_t)bytes[0] | (uint16_t)((uint16_t)bytes[1] << 8);
}

static uint32_t rh_u32(const unsigned char *bytes)
{
	return (uint32_t)bytes[0] | ((uint32_t)bytes[1] << 8) |
		((uint32_t)bytes[2] << 16) | ((uint32_t)bytes[3] << 24);
}

static uint64_t rh_u64(const unsigned char *bytes)
{
	uint64_t value = 0;
	unsigned int i;

	for (i = 0; i < 8U; i++)
		value |= (uint64_t)bytes[i] << (8U * i);
	return value;
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

static int rh_all_zero(const unsigned char *bytes, size_t length)
{
	size_t i;

	for (i = 0; i < length; i++)
		if (bytes[i])
			return 0;
	return 1;
}

static int rh_hash_zero(const unsigned char hash[32])
{
	return rh_all_zero(hash, 32U);
}

static int rh_raw_name_is(const struct rh_raw_mft_census *raw,
		const struct rh_raw_attribute *attribute, const unsigned char *name,
		uint16_t name_length)
{
	size_t bytes = (size_t)name_length * 2U;

	return raw && attribute && attribute->name_length == name_length &&
		attribute->name_offset <= raw->name_arena_size &&
		bytes <= raw->name_arena_size - attribute->name_offset &&
		(!bytes || !memcmp(raw->name_arena + attribute->name_offset,
			name, bytes));
}

static int rh_raw_stream_attribute_is(const struct rh_raw_mft_census *raw,
		const struct rh_raw_attribute *attribute, struct rh_raw_mft_ref owner,
		uint32_t type, const unsigned char *name, uint16_t name_length)
{
	return attribute->owner.record == owner.record &&
		attribute->owner.sequence == owner.sequence &&
		attribute->type == type && rh_raw_name_is(raw, attribute, name,
			name_length);
}

static const struct rh_raw_attribute *rh_stream_base(
		const struct rh_raw_mft_census *raw, struct rh_raw_mft_ref owner,
		uint32_t type, const unsigned char *name, uint16_t name_length,
		size_t *attribute_index)
{
	const struct rh_raw_attribute *found = NULL;
	size_t i;

	for (i = 0; i < raw->attribute_count; i++) {
		const struct rh_raw_attribute *attribute = &raw->attributes[i];

		if (!rh_raw_stream_attribute_is(raw, attribute, owner, type, name,
				name_length) || (attribute->nonresident && attribute->lowest_vcn))
			continue;
		if (found)
			return NULL;
		found = attribute;
		if (attribute_index)
			*attribute_index = i;
	}
	return found;
}

static int rh_stream_read(const struct rh_census_reader *reader,
		struct _ntfs_volume *volume, const struct rh_raw_mft_census *raw,
		struct rh_raw_mft_ref owner, uint32_t type,
		const unsigned char *name, uint16_t name_length, uint64_t offset,
		size_t length, unsigned char *buffer)
{
	if (!reader || !volume || !raw || (!buffer && length)) {
		errno = EINVAL;
		return -1;
	}
	return rh_raw_mft_stream_pread_reader(reader, raw, owner, type, name,
		name_length, offset, length, buffer);
}

static int rh_attribute_value(const struct rh_census_reader *reader,
		struct _ntfs_volume *volume, const struct rh_raw_mft_census *raw,
		const struct rh_raw_attribute *attribute, uint64_t maximum,
		unsigned char **owned, const unsigned char **value, size_t *length)
{
	uint64_t size;

	*owned = NULL;
	*value = NULL;
	*length = 0;
	if (!attribute->nonresident) {
		if (attribute->value_arena_offset > raw->value_arena_size ||
			attribute->value_length > raw->value_arena_size -
				attribute->value_arena_offset) {
			errno = EUCLEAN;
			return -1;
		}
		size = attribute->value_length;
		if (size > maximum) {
			errno = EUCLEAN;
			return -1;
		}
		*value = raw->value_arena + attribute->value_arena_offset;
		*length = (size_t)size;
		return 0;
	}
	if (attribute->lowest_vcn || attribute->data_size < 0 ||
		(uint64_t)attribute->data_size > maximum ||
		(uint64_t)attribute->data_size > SIZE_MAX) {
		errno = EUCLEAN;
		return -1;
	}
	size = (uint64_t)attribute->data_size;
	*owned = malloc(size ? (size_t)size : 1U);
	if (!*owned)
		return -1;
	if (size && rh_stream_read(reader, volume, raw, attribute->owner,
			attribute->type,
			raw->name_arena + attribute->name_offset,
			attribute->name_length, 0, (size_t)size, *owned)) {
		free(*owned);
		*owned = NULL;
		return -1;
	}
	*value = *owned;
	*length = (size_t)size;
	return 0;
}

static void rh_index_manifest_destroy(struct rh_index_manifest *manifest)
{
	size_t i;

	if (!manifest)
		return;
	for (i = 0; i < manifest->count; i++) {
		free(manifest->items[i].key);
		free(manifest->items[i].data);
	}
	free(manifest->items);
	memset(manifest, 0, sizeof(*manifest));
}

static int rh_index_item_compare(const void *left, const void *right)
{
	const struct rh_index_item *a = left;
	const struct rh_index_item *b = right;
	size_t i, common;

	if (a->kind != b->kind)
		return a->kind < b->kind ? -1 : 1;
	if (a->kind == RH_SYSTEM_INDEX_QUOTA_O) {
		common = a->key_length < b->key_length ? a->key_length :
			b->key_length;
		i = memcmp(a->key, b->key, common);
		if (i)
			return (int)i;
		return a->key_length < b->key_length ? -1 :
			a->key_length > b->key_length ? 1 : 0;
	}
	if (a->key_length != b->key_length)
		return a->key_length < b->key_length ? -1 : 1;
	if (a->key_length & 3U)
		return memcmp(a->key, b->key, a->key_length);
	for (i = 0; i < a->key_length; i += 4U) {
		uint32_t first = rh_u32(a->key + i);
		uint32_t second = rh_u32(b->key + i);

		if (first != second)
			return first < second ? -1 : 1;
	}
	return 0;
}

static int rh_index_manifest_add(struct rh_index_manifest *manifest,
		enum rh_system_index_kind kind, const unsigned char *key,
		size_t key_length, const unsigned char *data, size_t data_length)
{
	struct rh_index_item *grown, *item;
	size_t capacity;

	if (!manifest || !key || !key_length || (!data && data_length)) {
		errno = EINVAL;
		return -1;
	}
	if (manifest->count == manifest->capacity) {
		capacity = manifest->capacity ? manifest->capacity : 32U;
		if (capacity > SIZE_MAX / 2U)
			capacity = manifest->count + 1U;
		else
			capacity *= 2U;
		if (capacity <= manifest->count ||
			capacity > SIZE_MAX / sizeof(*grown)) {
			errno = EOVERFLOW;
			return -1;
		}
		grown = realloc(manifest->items, capacity * sizeof(*grown));
		if (!grown)
			return -1;
		manifest->items = grown;
		manifest->capacity = capacity;
	}
	item = &manifest->items[manifest->count];
	memset(item, 0, sizeof(*item));
	item->key = malloc(key_length);
	item->data = data_length ? malloc(data_length) : NULL;
	if (!item->key || (data_length && !item->data)) {
		free(item->key);
		free(item->data);
		memset(item, 0, sizeof(*item));
		return -1;
	}
	memcpy(item->key, key, key_length);
	if (data_length)
		memcpy(item->data, data, data_length);
	item->kind = kind;
	item->key_length = key_length;
	item->data_length = data_length;
	manifest->count++;
	return 0;
}

static int rh_index_manifest_sort(struct rh_index_manifest *manifest)
{
	size_t i;

	if (manifest->count < 2U)
		return 0;
	qsort(manifest->items, manifest->count, sizeof(*manifest->items),
		rh_index_item_compare);
	for (i = 1; i < manifest->count; i++)
		if (!rh_index_item_compare(&manifest->items[i - 1U],
				&manifest->items[i])) {
			errno = EUCLEAN;
			return -1;
		}
	return 0;
}

static int rh_index_manifest_hash(const struct rh_index_manifest *manifest,
		unsigned char output[32])
{
	struct rh_hash_stream hash;
	size_t i;

	rh_hash_stream_init(&hash);
	for (i = 0; i < manifest->count; i++) {
		const struct rh_index_item *item = &manifest->items[i];
		unsigned char header[12];

		rh_put_u32(header, (uint32_t)item->kind);
		rh_put_u32(header + 4U, (uint32_t)item->key_length);
		rh_put_u32(header + 8U, (uint32_t)item->data_length);
		if (item->key_length > UINT32_MAX || item->data_length > UINT32_MAX ||
			rh_hash_stream_update(&hash, header, sizeof(header)) ||
			rh_hash_stream_update(&hash, item->key, item->key_length))
			return -1;
		if (item->data_length && rh_hash_stream_update(&hash, item->data,
				item->data_length))
			return -1;
	}
	return rh_hash_stream_final(&hash, output);
}

static int rh_index_manifest_equal(const struct rh_index_manifest *left,
		const struct rh_index_manifest *right)
{
	size_t i;

	if (left->count != right->count)
		return 0;
	for (i = 0; i < left->count; i++) {
		const struct rh_index_item *a = &left->items[i];
		const struct rh_index_item *b = &right->items[i];

		if (a->kind != b->kind || a->key_length != b->key_length ||
			a->data_length != b->data_length ||
			memcmp(a->key, b->key, a->key_length) ||
			(a->data_length && memcmp(a->data, b->data, a->data_length)))
			return 0;
	}
	return 1;
}

static int rh_sid_valid(const unsigned char *sid, size_t length,
		size_t *used_length)
{
	size_t needed;

	if (!sid || length < 8U || sid[0] != 1U || sid[1] > 15U)
		return 0;
	needed = 8U + (size_t)sid[1] * 4U;
	if (needed > length)
		return 0;
	if (used_length)
		*used_length = needed;
	return 1;
}

static int rh_live_ref_valid(const struct rh_raw_mft_census *raw,
		uint64_t encoded)
{
	uint64_t record = encoded & UINT64_C(0x0000ffffffffffff);
	uint16_t sequence = (uint16_t)(encoded >> 48);

	return sequence && record < raw->slot_count &&
		raw->slots[record].state == RH_RAW_SLOT_LIVE_BASE &&
		raw->slots[record].sequence == sequence;
}

static int rh_quota_flags_valid(uint32_t owner_id, uint32_t flags)
{
	const uint32_t user = UINT32_C(0x00000007);
	const uint32_t defaults = UINT32_C(0x00000ff0);

	return !(flags & ~(user | (owner_id == 1U ? defaults : 0U)));
}

static int rh_index_normalize_item(struct rh_index_walk *walk,
		const unsigned char *key, size_t key_length,
		const unsigned char *data, size_t data_length)
{
	unsigned char normalized[80];
	size_t sid_length, normalized_length;
	uint64_t reference;
	uint32_t owner_id, flags;
	int64_t threshold, limit;

	switch (walk->kind) {
	case RH_SYSTEM_INDEX_REPARSE_R:
		if (key_length != 12U || data_length || !rh_u32(key))
			goto corrupt;
		reference = rh_u64(key + 4U);
		if (!rh_live_ref_valid(walk->raw, reference))
			goto corrupt;
		return rh_index_manifest_add(walk->manifest, walk->kind, key,
			key_length, NULL, 0);
	case RH_SYSTEM_INDEX_OBJID_O:
		if (key_length != 16U || data_length != 56U)
			goto corrupt;
		reference = rh_u64(data);
		if (!rh_live_ref_valid(walk->raw, reference) ||
			!rh_all_zero(data + 40U, 16U))
			goto corrupt;
		return rh_index_manifest_add(walk->manifest, walk->kind, key,
			key_length, data, data_length);
	case RH_SYSTEM_INDEX_QUOTA_O:
		if (!rh_sid_valid(key, key_length, &sid_length) ||
			sid_length != key_length || data_length != 4U ||
			rh_u32(data) < 0x100U)
			goto corrupt;
		return rh_index_manifest_add(walk->manifest, walk->kind, key,
			key_length, data, data_length);
	case RH_SYSTEM_INDEX_QUOTA_Q:
		if (key_length != 4U || data_length < 48U ||
			(data_length & 7U))
			goto corrupt;
		owner_id = rh_u32(key);
		if (owner_id != 1U && owner_id < 0x100U)
			goto corrupt;
		if (rh_u32(data) != 2U ||
			!rh_quota_flags_valid(owner_id, (flags = rh_u32(data + 4U))))
			goto corrupt;
		threshold = (int64_t)rh_u64(data + 24U);
		limit = (int64_t)rh_u64(data + 32U);
		if (threshold < -1 || limit < -1 ||
			(threshold >= 0 && limit >= 0 && threshold > limit))
			goto corrupt;
		if (owner_id == 1U) {
			if (data_length != 48U)
				goto corrupt;
			normalized_length = 48U;
		} else {
			if (data_length <= 48U ||
				!rh_sid_valid(data + 48U, data_length - 48U,
					&sid_length) ||
				sid_length > data_length - 48U ||
				data_length - 48U - sid_length >= 8U)
				goto corrupt;
			normalized_length = 48U + ((sid_length + 7U) & ~(size_t)7U);
		}
		if (normalized_length > sizeof(normalized))
			goto corrupt;
		memset(normalized, 0, normalized_length);
		memcpy(normalized, data, owner_id == 1U ? 48U : 48U + sid_length);
		(void)flags;
		return rh_index_manifest_add(walk->manifest, walk->kind, key,
			key_length, normalized, normalized_length);
	case RH_SYSTEM_INDEX_INVALID:
	case RH_SYSTEM_INDEX_COUNT:
		break;
	}
corrupt:
	errno = EUCLEAN;
	return -1;
}

static int rh_index_key_compare(enum rh_system_index_kind kind,
		const unsigned char *left, size_t left_length,
		const unsigned char *right, size_t right_length)
{
	struct rh_index_item a, b;

	memset(&a, 0, sizeof(a));
	memset(&b, 0, sizeof(b));
	a.kind = b.kind = kind;
	a.key = (unsigned char *)left;
	b.key = (unsigned char *)right;
	a.key_length = left_length;
	b.key_length = right_length;
	return rh_index_item_compare(&a, &b);
}

static int rh_index_frame_push(struct rh_index_walk_frame **frames,
		size_t *count, size_t *capacity, const unsigned char *header,
		const unsigned char *header_end, unsigned char *owned)
{
	struct rh_index_walk_frame *grown, *frame;
	uint32_t entries_offset;
	size_t next;

	if (!frames || !count || !capacity || !header ||
		header_end <= header || (size_t)(header_end - header) < 16U) {
		errno = EINVAL;
		return -1;
	}
	entries_offset = rh_u32(header);
	if (entries_offset < 16U || (entries_offset & 7U) ||
		entries_offset >= (size_t)(header_end - header)) {
		errno = EUCLEAN;
		return -1;
	}
	if (*count == *capacity) {
		if (*capacity && *capacity > SIZE_MAX / 2U) {
			errno = EOVERFLOW;
			return -1;
		}
		next = *capacity ? *capacity * 2U : 8U;
		if (next <= *count || next > SIZE_MAX / sizeof(**frames)) {
			errno = EOVERFLOW;
			return -1;
		}
		grown = realloc(*frames, next * sizeof(**frames));
		if (!grown)
			return -1;
		*frames = grown;
		*capacity = next;
	}
	frame = &(*frames)[(*count)++];
	memset(frame, 0, sizeof(*frame));
	frame->owned_block = owned;
	frame->cursor = header + entries_offset;
	frame->end = header_end;
	return 0;
}

static int rh_bitmap_test(const unsigned char *bitmap, uint64_t bit)
{
	return !!(bitmap[bit >> 3] & (unsigned char)(1U << (bit & 7U)));
}

static void rh_bitmap_mark(unsigned char *bitmap, uint64_t bit)
{
	bitmap[bit >> 3] |= (unsigned char)(1U << (bit & 7U));
}

static int rh_index_load_child(struct rh_index_walk *walk, int64_t vcn,
		unsigned char **block_out, const unsigned char **header_out,
		const unsigned char **end_out)
{
	unsigned char *block;
	INDEX_BLOCK *index_block;
	uint64_t ordinal, logical;
	uint32_t entries_offset, index_length, allocated;

	if (!walk || !block_out || !header_out || !end_out || vcn < 0 ||
		walk->volume->cluster_size != RH_SYSTEM_INDEX_BLOCK ||
		(uint64_t)vcn >= walk->block_count) {
		errno = EUCLEAN;
		return -1;
	}
	ordinal = (uint64_t)vcn;
	if (rh_bitmap_test(walk->visited, ordinal)) {
		errno = EUCLEAN;
		return -1;
	}
	logical = ordinal * RH_SYSTEM_INDEX_BLOCK;
	block = malloc(RH_SYSTEM_INDEX_BLOCK);
	if (!block)
		return -1;
	if (rh_stream_read(walk->reader, walk->volume, walk->raw, walk->owner,
			le32_to_cpu(AT_INDEX_ALLOCATION), walk->name,
			walk->name_length, logical, RH_SYSTEM_INDEX_BLOCK, block))
		goto fail;
	if (ntfs_mst_post_read_fixup((NTFS_RECORD *)block,
			RH_SYSTEM_INDEX_BLOCK)) {
		errno = EUCLEAN;
		goto fail;
	}
	index_block = (INDEX_BLOCK *)block;
	if (index_block->magic != magic_INDX ||
		le16_to_cpu(index_block->usa_ofs) != sizeof(INDEX_BLOCK) ||
		le16_to_cpu(index_block->usa_count) !=
			RH_SYSTEM_INDEX_BLOCK / RH_SYSTEM_INDEX_SECTOR + 1U ||
		sle64_to_cpu(index_block->index_block_vcn) != vcn ||
		(index_block->index.ih_flags & (uint8_t)~NODE_MASK) ||
		!rh_all_zero(index_block->index.reserved,
			sizeof(index_block->index.reserved))) {
		errno = EUCLEAN;
		goto fail;
	}
	entries_offset = le32_to_cpu(index_block->index.entries_offset);
	index_length = le32_to_cpu(index_block->index.index_length);
	allocated = le32_to_cpu(index_block->index.allocated_size);
	if (entries_offset < sizeof(INDEX_HEADER) || (entries_offset & 7U) ||
		index_length < entries_offset + sizeof(INDEX_ENTRY_HEADER) ||
		(index_length & 7U) ||
		allocated != RH_SYSTEM_INDEX_BLOCK - offsetof(INDEX_BLOCK, index) ||
		index_length > allocated ||
		offsetof(INDEX_BLOCK, index) + index_length > RH_SYSTEM_INDEX_BLOCK) {
		errno = EUCLEAN;
		goto fail;
	}
	rh_bitmap_mark(walk->visited, ordinal);
	walk->state->blocks_examined++;
	walk->state->blocks_reachable++;
	*block_out = block;
	*header_out = (const unsigned char *)&index_block->index;
	*end_out = *header_out + index_length;
	return 0;
fail:
	free(block);
	return -1;
}

static int rh_index_walk_entries(struct rh_index_walk *walk,
		const unsigned char *root_header, const unsigned char *root_end)
{
	struct rh_index_walk_frame *frames = NULL;
	size_t count = 0, capacity = 0;
	int result = -1;

	if (rh_index_frame_push(&frames, &count, &capacity, root_header,
			root_end, NULL))
		goto out;
	while (count) {
		struct rh_index_walk_frame *frame = &frames[count - 1U];
		const unsigned char *entry = frame->cursor;
		uint16_t data_offset, data_length, length, key_length, flags;
		const unsigned char *key, *payload_end, *data;

		if (entry >= frame->end ||
			(size_t)(frame->end - entry) < sizeof(INDEX_ENTRY_HEADER)) {
			errno = EUCLEAN;
			goto out;
		}
		data_offset = rh_u16(entry);
		data_length = rh_u16(entry + 2U);
		length = rh_u16(entry + 8U);
		key_length = rh_u16(entry + 10U);
		flags = rh_u16(entry + 12U);
		if (length < sizeof(INDEX_ENTRY_HEADER) || (length & 7U) ||
			length > (size_t)(frame->end - entry) ||
			(flags & ~(le16_to_cpu(INDEX_ENTRY_NODE) |
				le16_to_cpu(INDEX_ENTRY_END))) || rh_u16(entry + 14U) ||
			rh_u32(entry + 4U)) {
			errno = EUCLEAN;
			goto out;
		}
		payload_end = entry + length -
			((flags & le16_to_cpu(INDEX_ENTRY_NODE)) ? sizeof(leVCN) : 0U);
		if ((flags & le16_to_cpu(INDEX_ENTRY_NODE)) && !frame->child_visited) {
			unsigned char *child_block = NULL;
			const unsigned char *child_header = NULL, *child_end = NULL;
			int64_t child = (int64_t)rh_u64(payload_end);

			frame->child_visited = 1;
			if (rh_index_load_child(walk, child, &child_block,
					&child_header, &child_end) ||
				rh_index_frame_push(&frames, &count, &capacity,
					child_header, child_end, child_block)) {
				free(child_block);
				goto out;
			}
			continue;
		}
		if (flags & le16_to_cpu(INDEX_ENTRY_END)) {
			if (key_length || data_offset || data_length ||
				entry + length != frame->end) {
				errno = EUCLEAN;
				goto out;
			}
			walk->state->end_entries_examined++;
		} else {
			key = entry + sizeof(INDEX_ENTRY_HEADER);
			if (!key_length || key > payload_end ||
				key_length > (size_t)(payload_end - key) ||
				data_offset < sizeof(INDEX_ENTRY_HEADER) + key_length ||
				data_offset > (size_t)(payload_end - entry) ||
				data_length > (size_t)(payload_end - entry) - data_offset ||
				(size_t)(payload_end - (entry + data_offset + data_length)) >=
					8U) {
				errno = EUCLEAN;
				goto out;
			}
			if ((walk->kind == RH_SYSTEM_INDEX_REPARSE_R &&
					(data_offset != 28U || key_length != 12U || data_length)) ||
				(walk->kind == RH_SYSTEM_INDEX_OBJID_O &&
					(data_offset != 32U || key_length != 16U ||
					 data_length != 56U)) ||
				(walk->kind == RH_SYSTEM_INDEX_QUOTA_O &&
					(data_offset != ((16U + key_length + 7U) & ~7U) ||
					 data_length != 4U ||
					(size_t)(payload_end - (entry + data_offset + 4U)) < 4U ||
					 rh_u32(entry + data_offset + 4U) != 32U)) ||
				(walk->kind == RH_SYSTEM_INDEX_QUOTA_Q &&
					(data_offset != 20U || key_length != 4U))) {
				errno = EUCLEAN;
				goto out;
			}
			if (walk->previous_key &&
				rh_index_key_compare(walk->kind, walk->previous_key,
					walk->previous_key_length, key, key_length) >= 0) {
				errno = EUCLEAN;
				goto out;
			}
			data = entry + data_offset;
			if (rh_index_normalize_item(walk, key, key_length, data,
					data_length))
				goto out;
			free(walk->previous_key);
			walk->previous_key = malloc(key_length);
			if (!walk->previous_key)
				goto out;
			memcpy(walk->previous_key, key, key_length);
			walk->previous_key_length = key_length;
			walk->state->entries_examined++;
		}
		frame->cursor = entry + length;
		frame->child_visited = 0;
		if (flags & le16_to_cpu(INDEX_ENTRY_END)) {
			free(frame->owned_block);
			frame->owned_block = NULL;
			count--;
		}
	}
	result = 0;
out:
	while (count) {
		free(frames[count - 1U].owned_block);
		count--;
	}
	free(frames);
	return result;
}

static const struct rh_raw_attribute *rh_find_index_attribute(
		const struct rh_raw_mft_census *raw, struct rh_raw_mft_ref owner,
		uint32_t type, const unsigned char *name, uint16_t name_length,
		int require_resident)
{
	const struct rh_raw_attribute *found = NULL;
	size_t i;

	for (i = 0; i < raw->attribute_count; i++) {
		const struct rh_raw_attribute *attribute = &raw->attributes[i];

		if (!rh_raw_stream_attribute_is(raw, attribute, owner, type, name,
				name_length) || (attribute->nonresident && attribute->lowest_vcn))
			continue;
		if ((require_resident > 0 && attribute->nonresident) ||
			(require_resident == 0 && !attribute->nonresident) || found)
			return NULL;
		found = attribute;
	}
	return found;
}

static int rh_index_bitmap_exact(const struct rh_index_walk *walk,
		const unsigned char *bitmap, size_t bitmap_length)
{
	uint64_t bit, bits;

	if (!walk->block_count || walk->block_count > UINT64_MAX - 7U ||
		bitmap_length < (size_t)((walk->block_count + 7U) / 8U) ||
		bitmap_length > UINT64_MAX / 8U)
		return 0;
	bits = (uint64_t)bitmap_length * 8U;
	for (bit = 0; bit < bits; bit++) {
		int expected = bit < walk->block_count &&
			rh_bitmap_test(walk->visited, bit);

		if (rh_bitmap_test(bitmap, bit) != expected)
			return 0;
	}
	return 1;
}

static int rh_index_inspect(const struct rh_census_reader *reader,
		struct _ntfs_volume *volume, const struct rh_raw_mft_census *raw,
		struct rh_raw_mft_ref owner, enum rh_system_index_kind kind,
		const unsigned char *name, uint16_t name_length,
		struct rh_index_manifest *manifest,
		struct rh_system_index_state *state)
{
	const struct rh_raw_attribute *root_attribute, *allocation = NULL;
	const struct rh_raw_attribute *bitmap_attribute = NULL;
	const unsigned char *root_value, *bitmap = NULL;
	unsigned char *owned_bitmap = NULL;
	struct rh_index_walk walk;
	uint32_t expected_collation, entries_offset, index_length, allocated;
	uint64_t bitmap_maximum;
	size_t root_length, bitmap_length = 0, visited_size;
	int large, result = -1;

	memset(&walk, 0, sizeof(walk));
	memset(state, 0, sizeof(*state));
	state->owner_record = owner.record;
	state->owner_sequence = owner.sequence;
	root_attribute = rh_find_index_attribute(raw, owner,
		le32_to_cpu(AT_INDEX_ROOT), name, name_length, 1);
	if (!root_attribute || root_attribute->value_arena_offset >
			raw->value_arena_size ||
		root_attribute->value_length > raw->value_arena_size -
			root_attribute->value_arena_offset ||
		root_attribute->value_length < sizeof(INDEX_ROOT) +
			sizeof(INDEX_ENTRY_HEADER)) {
		errno = EUCLEAN;
		goto out;
	}
	state->root_found = 1;
	state->root_instance = root_attribute->instance;
	root_value = raw->value_arena + root_attribute->value_arena_offset;
	root_length = root_attribute->value_length;
	expected_collation = kind == RH_SYSTEM_INDEX_QUOTA_O ?
		le32_to_cpu(COLLATION_NTOFS_SID) :
		kind == RH_SYSTEM_INDEX_QUOTA_Q ?
		le32_to_cpu(COLLATION_NTOFS_ULONG) :
		le32_to_cpu(COLLATION_NTOFS_ULONGS);
	if (rh_u32(root_value) != le32_to_cpu(AT_UNUSED) ||
		rh_u32(root_value + 4U) != expected_collation ||
		rh_u32(root_value + 8U) != RH_SYSTEM_INDEX_BLOCK ||
		root_value[12] != 1U || !rh_all_zero(root_value + 13U, 3U)) {
		errno = EUCLEAN;
		goto out;
	}
	entries_offset = rh_u32(root_value + 16U);
	index_length = rh_u32(root_value + 20U);
	allocated = rh_u32(root_value + 24U);
	large = root_value[28] == LARGE_INDEX;
	if ((!large && root_value[28] != SMALL_INDEX) ||
		!rh_all_zero(root_value + 29U, 3U) ||
		entries_offset < sizeof(INDEX_HEADER) || (entries_offset & 7U) ||
		index_length < entries_offset + sizeof(INDEX_ENTRY_HEADER) ||
		(index_length & 7U) || allocated < index_length ||
		allocated > root_length - 16U) {
		errno = EUCLEAN;
		goto out;
	}
	walk.reader = reader;
	walk.volume = volume;
	walk.raw = raw;
	walk.owner = owner;
	walk.kind = kind;
	walk.name = name;
	walk.name_length = name_length;
	walk.manifest = manifest;
	walk.state = state;
	if (large) {
		allocation = rh_find_index_attribute(raw, owner,
			le32_to_cpu(AT_INDEX_ALLOCATION), name, name_length, 0);
		bitmap_attribute = rh_find_index_attribute(raw, owner,
			le32_to_cpu(AT_BITMAP), name, name_length, -1);
		if (!allocation || !bitmap_attribute || allocation->data_size <= 0 ||
			allocation->initialized_size != allocation->data_size ||
			(uint64_t)allocation->data_size % RH_SYSTEM_INDEX_BLOCK) {
			errno = EUCLEAN;
			goto out;
		}
		walk.block_count = (uint64_t)allocation->data_size /
			RH_SYSTEM_INDEX_BLOCK;
		if (!walk.block_count || walk.block_count > UINT64_MAX - 7U ||
			(walk.block_count + 7U) / 8U > SIZE_MAX) {
			errno = EOVERFLOW;
			goto out;
		}
		visited_size = (size_t)((walk.block_count + 7U) / 8U);
		walk.visited = calloc(1, visited_size);
		if (!walk.visited)
			goto out;
		walk.visited_size = visited_size;
		bitmap_maximum = reader->device_size;
		if (rh_attribute_value(reader, volume, raw, bitmap_attribute,
				bitmap_maximum, &owned_bitmap, &bitmap, &bitmap_length))
			goto out;
		state->large = 1;
		state->allocation_instance = allocation->instance;
		state->bitmap_instance = bitmap_attribute->instance;
		state->allocation_data_size = (uint64_t)allocation->data_size;
		state->bitmap_data_size = bitmap_length;
	} else if (rh_stream_base(raw, owner, le32_to_cpu(AT_INDEX_ALLOCATION),
			name, name_length, NULL) ||
		rh_stream_base(raw, owner, le32_to_cpu(AT_BITMAP), name,
			name_length, NULL)) {
		errno = EUCLEAN;
		goto out;
	}
	if (rh_index_walk_entries(&walk, root_value + 16U,
			root_value + 16U + index_length))
		goto out;
	if (large && !rh_index_bitmap_exact(&walk, bitmap, bitmap_length)) {
		errno = EUCLEAN;
		goto out;
	}
	if (rh_index_manifest_sort(manifest) ||
		rh_index_manifest_hash(manifest, state->observed_manifest_hash))
		goto out;
	state->structurally_valid = 1;
	result = 0;
out:
	free(walk.previous_key);
	free(walk.visited);
	free(owned_bitmap);
	if (result && errno == EUCLEAN) {
		rh_index_manifest_destroy(manifest);
		result = 1;
	}
	return result;
}

static int rh_reparse_bytes_valid(const unsigned char *bytes, size_t length,
		int directory, uint32_t file_attributes)
{
	uint32_t tag;
	uint16_t data_length;
	size_t header, payload, offset, extent;

	if (!bytes || length < 8U || !(tag = rh_u32(bytes)))
		return 0;
	data_length = rh_u16(bytes + 4U);
	header = tag & UINT32_C(0x80000000) ? 8U : 24U;
	if (length != header + data_length)
		return 0;
	payload = header;
	switch (tag) {
	case UINT32_C(0xa0000003):
		if (!directory || data_length < 8U)
			return 0;
		offset = rh_u16(bytes + payload);
		extent = rh_u16(bytes + payload + 2U);
		if ((offset | extent) & 1U || offset > data_length - 8U ||
			extent > data_length - 8U - offset)
			return 0;
		offset = rh_u16(bytes + payload + 4U);
		extent = rh_u16(bytes + payload + 6U);
		return !((offset | extent) & 1U) && offset <= data_length - 8U &&
			extent <= data_length - 8U - offset;
	case UINT32_C(0xa000000c):
		if (data_length < 12U)
			return 0;
		offset = rh_u16(bytes + payload);
		extent = rh_u16(bytes + payload + 2U);
		if ((offset | extent) & 1U || offset > data_length - 12U ||
			extent > data_length - 12U - offset)
			return 0;
		offset = rh_u16(bytes + payload + 4U);
		extent = rh_u16(bytes + payload + 6U);
		return !((offset | extent) & 1U) && offset <= data_length - 12U &&
			extent <= data_length - 12U - offset;
	case UINT32_C(0xa000001d):
		return data_length > 4U && rh_u32(bytes + payload) == 2U;
	case UINT32_C(0x80000023):
	case UINT32_C(0x80000024):
	case UINT32_C(0x80000025):
	case UINT32_C(0x80000026):
		return !data_length &&
			(file_attributes & UINT32_C(0x00040000));
	default:
		return 1;
	}
}

static int rh_reparse_fact_add(struct rh_system_index_census *census,
		const struct rh_reparse_fact *fact)
{
	struct rh_reparse_fact *grown;
	size_t capacity;

	if (census->reparse_count == census->reparse_capacity) {
		if (census->reparse_capacity > SIZE_MAX / 2U) {
			errno = EOVERFLOW;
			return -1;
		}
		capacity = census->reparse_capacity ? census->reparse_capacity * 2U :
			32U;
		if (capacity <= census->reparse_count ||
			capacity > SIZE_MAX / sizeof(*grown)) {
			errno = EOVERFLOW;
			return -1;
		}
		grown = realloc(census->reparse, capacity * sizeof(*grown));
		if (!grown)
			return -1;
		census->reparse = grown;
		census->reparse_capacity = capacity;
	}
	census->reparse[census->reparse_count++] = *fact;
	return 0;
}

static int rh_objid_fact_add(struct rh_system_index_census *census,
		const struct rh_objid_fact *fact)
{
	struct rh_objid_fact *grown;
	size_t capacity;

	if (census->objid_count == census->objid_capacity) {
		if (census->objid_capacity > SIZE_MAX / 2U) {
			errno = EOVERFLOW;
			return -1;
		}
		capacity = census->objid_capacity ? census->objid_capacity * 2U : 32U;
		if (capacity <= census->objid_count ||
			capacity > SIZE_MAX / sizeof(*grown)) {
			errno = EOVERFLOW;
			return -1;
		}
		grown = realloc(census->objid, capacity * sizeof(*grown));
		if (!grown)
			return -1;
		census->objid = grown;
		census->objid_capacity = capacity;
	}
	census->objid[census->objid_count++] = *fact;
	return 0;
}

static int rh_sid_arena_add(struct rh_system_index_census *census,
		const unsigned char *sid, size_t length, size_t *offset)
{
	unsigned char *grown;
	size_t capacity, required;

	if (length > SIZE_MAX - census->sid_arena_size) {
		errno = EOVERFLOW;
		return -1;
	}
	required = census->sid_arena_size + length;
	if (required > census->sid_arena_capacity) {
		capacity = census->sid_arena_capacity ? census->sid_arena_capacity :
			256U;
		while (capacity < required) {
			if (capacity > SIZE_MAX / 2U) {
				capacity = required;
				break;
			}
			capacity *= 2U;
		}
		grown = realloc(census->sid_arena, capacity);
		if (!grown)
			return -1;
		census->sid_arena = grown;
		census->sid_arena_capacity = capacity;
	}
	*offset = census->sid_arena_size;
	if (length)
		memcpy(census->sid_arena + census->sid_arena_size, sid, length);
	census->sid_arena_size = required;
	return 0;
}

static int rh_quota_fact_add(struct rh_system_index_census *census,
		const struct rh_quota_fact *fact)
{
	struct rh_quota_fact *grown;
	size_t capacity;

	if (census->quota_count == census->quota_capacity) {
		if (census->quota_capacity > SIZE_MAX / 2U) {
			errno = EOVERFLOW;
			return -1;
		}
		capacity = census->quota_capacity ? census->quota_capacity * 2U : 32U;
		if (capacity <= census->quota_count ||
			capacity > SIZE_MAX / sizeof(*grown)) {
			errno = EOVERFLOW;
			return -1;
		}
		grown = realloc(census->quota, capacity * sizeof(*grown));
		if (!grown)
			return -1;
		census->quota = grown;
		census->quota_capacity = capacity;
	}
	census->quota[census->quota_count++] = *fact;
	return 0;
}

static int rh_reference_compare(const void *left, const void *right)
{
	const struct rh_free_slot_reference *a = left;
	const struct rh_free_slot_reference *b = right;

	if (a->record != b->record)
		return a->record < b->record ? -1 : 1;
	return a->sequence < b->sequence ? -1 : a->sequence > b->sequence;
}

static int rh_reference_add(struct rh_free_slot_reference **references,
		size_t *count, uint64_t record, uint16_t sequence)
{
	struct rh_free_slot_reference *grown;

	if (!sequence || *count >= SIZE_MAX / sizeof(**references)) {
		errno = EOVERFLOW;
		return -1;
	}
	grown = realloc(*references, (*count + 1U) * sizeof(**references));
	if (!grown)
		return -1;
	*references = grown;
	grown[*count].record = record;
	grown[*count].sequence = sequence;
	(*count)++;
	return 0;
}

static void rh_references_sort_unique(struct rh_free_slot_reference *references,
		size_t *count)
{
	size_t i, unique;

	if (*count < 2U)
		return;
	qsort(references, *count, sizeof(*references), rh_reference_compare);
	for (i = 0, unique = 0; i < *count; i++)
		if (!i || rh_reference_compare(&references[i], &references[i - 1U]))
			references[unique++] = references[i];
	*count = unique;
}

static int rh_manifest_find(const struct rh_index_manifest *manifest,
		enum rh_system_index_kind kind, const unsigned char *key,
		size_t key_length, size_t *position)
{
	struct rh_index_item target;
	size_t low = 0, high = manifest->count;

	memset(&target, 0, sizeof(target));
	target.kind = kind;
	target.key = (unsigned char *)key;
	target.key_length = key_length;
	while (low < high) {
		size_t middle = low + (high - low) / 2U;
		int comparison = rh_index_item_compare(&manifest->items[middle],
			&target);

		if (comparison < 0)
			low = middle + 1U;
		else
			high = middle;
	}
	if (low >= manifest->count ||
		rh_index_item_compare(&manifest->items[low], &target))
		return 0;
	*position = low;
	return 1;
}

static int rh_scan_standard_information(const struct rh_raw_mft_census *raw,
		struct rh_system_index_census *census, uint8_t **seen_out,
		uint32_t **flags_out, uint32_t **owner_ids_out)
{
	uint8_t *seen;
	uint32_t *flags, *owner_ids;
	size_t i;

	if (raw->slot_count > SIZE_MAX / sizeof(*flags)) {
		errno = EOVERFLOW;
		return -1;
	}
	seen = calloc(raw->slot_count ? raw->slot_count : 1U, 1U);
	flags = calloc(raw->slot_count ? raw->slot_count : 1U, sizeof(*flags));
	owner_ids = calloc(raw->slot_count ? raw->slot_count : 1U,
		sizeof(*owner_ids));
	if (!seen || !flags || !owner_ids)
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
			(attribute->value_length != 48U && attribute->value_length != 72U) ||
			attribute->value_arena_offset > raw->value_arena_size ||
			attribute->value_length > raw->value_arena_size -
				attribute->value_arena_offset || seen[record]) {
			errno = EUCLEAN;
			goto fail;
		}
		value = raw->value_arena + attribute->value_arena_offset;
		seen[record] = 1;
		flags[record] = rh_u32(value + 32U);
		owner_ids[record] = attribute->value_length == 72U ?
			rh_u32(value + 48U) : 0U;
		census->standard_information_examined++;
	}
	for (i = 0; i < raw->slot_count; i++)
		if (raw->slots[i].state == RH_RAW_SLOT_LIVE_BASE && !seen[i]) {
			errno = EUCLEAN;
			goto fail;
		}
	*seen_out = seen;
	*flags_out = flags;
	*owner_ids_out = owner_ids;
	return 0;
fail:
	free(seen);
	free(flags);
	free(owner_ids);
	return errno == EUCLEAN ? 1 : -1;
}

static int rh_scan_reparse(const struct rh_census_reader *reader,
		struct _ntfs_volume *volume, const struct rh_raw_mft_census *raw,
		const uint32_t *si_flags, struct rh_system_index_census *census,
		uint8_t **seen_out, uint32_t **tags_out)
{
	uint8_t *seen;
	uint32_t *tags;
	size_t i;

	seen = calloc(raw->slot_count ? raw->slot_count : 1U, 1U);
	tags = calloc(raw->slot_count ? raw->slot_count : 1U, sizeof(*tags));
	if (!seen || !tags)
		goto fail;
	for (i = 0; i < raw->attribute_count; i++) {
		const struct rh_raw_attribute *attribute = &raw->attributes[i];
		struct rh_reparse_fact fact;
		const unsigned char *value;
		unsigned char *owned;
		size_t length;
		uint64_t record;

		if (attribute->type != le32_to_cpu(AT_REPARSE_POINT))
			continue;
		if (attribute->nonresident && attribute->lowest_vcn)
			continue;
		record = attribute->owner.record;
		if (record >= raw->slot_count ||
			raw->slots[record].state != RH_RAW_SLOT_LIVE_BASE ||
			attribute->owner.sequence != raw->slots[record].sequence ||
			attribute->name_length || attribute->flags || seen[record]) {
			errno = EUCLEAN;
			goto fail;
		}
		if (rh_attribute_value(reader, volume, raw, attribute,
				RH_REPARSE_MAXIMUM_SIZE, &owned, &value, &length))
			goto fail;
		if (!rh_reparse_bytes_valid(value, length,
				!!(raw->slots[record].flags & MFT_RECORD_IS_DIRECTORY),
				si_flags[record]) || !(si_flags[record] & UINT32_C(0x400))) {
			free(owned);
			errno = EUCLEAN;
			goto fail;
		}
		memset(&fact, 0, sizeof(fact));
		fact.tag = rh_u32(value);
		fact.file = attribute->owner;
		fact.storage = attribute->storage;
		fact.attribute_instance = attribute->instance;
		fact.value_length = length;
		rh_sha256(value, length, fact.value_hash);
		free(owned);
		if (rh_reparse_fact_add(census, &fact))
			goto fail;
		seen[record] = 1;
		tags[record] = fact.tag;
	}
	for (i = 0; i < raw->slot_count; i++)
		if (raw->slots[i].state == RH_RAW_SLOT_LIVE_BASE &&
			!!(si_flags[i] & UINT32_C(0x400)) != !!seen[i]) {
			errno = EUCLEAN;
			goto fail;
		}
	*seen_out = seen;
	*tags_out = tags;
	return 0;
fail:
	free(seen);
	free(tags);
	return errno == EUCLEAN ? 1 : -1;
}

static int rh_scan_objid(const struct rh_raw_mft_census *raw,
		struct rh_system_index_census *census)
{
	uint8_t *seen;
	size_t i;

	seen = calloc(raw->slot_count ? raw->slot_count : 1U, 1U);
	if (!seen)
		return -1;
	for (i = 0; i < raw->attribute_count; i++) {
		const struct rh_raw_attribute *attribute = &raw->attributes[i];
		struct rh_objid_fact fact;
		const unsigned char *value;
		uint64_t record;

		if (attribute->type != le32_to_cpu(AT_OBJECT_ID))
			continue;
		record = attribute->owner.record;
		if (record >= raw->slot_count ||
			raw->slots[record].state != RH_RAW_SLOT_LIVE_BASE ||
			attribute->owner.sequence != raw->slots[record].sequence ||
			attribute->nonresident || attribute->name_length || attribute->flags ||
			(attribute->value_length != 16U && attribute->value_length != 64U) ||
			attribute->value_arena_offset > raw->value_arena_size ||
			attribute->value_length > raw->value_arena_size -
				attribute->value_arena_offset || seen[record]) {
			errno = EUCLEAN;
			free(seen);
			return 1;
		}
		value = raw->value_arena + attribute->value_arena_offset;
		if (rh_all_zero(value, 16U) ||
			(attribute->value_length == 64U &&
			 !rh_all_zero(value + 48U, 16U))) {
			errno = EUCLEAN;
			free(seen);
			return 1;
		}
		memset(&fact, 0, sizeof(fact));
		memcpy(fact.object_id, value, 16U);
		fact.file = attribute->owner;
		fact.storage = attribute->storage;
		fact.attribute_instance = attribute->instance;
		fact.attribute_has_extended_info = attribute->value_length == 64U;
		fact.extended_info_authoritative = fact.attribute_has_extended_info;
		if (fact.attribute_has_extended_info)
			memcpy(fact.extended_info, value + 16U, 48U);
		rh_sha256(value, attribute->value_length, fact.value_hash);
		if (rh_objid_fact_add(census, &fact)) {
			free(seen);
			return -1;
		}
		seen[record] = 1;
	}
	free(seen);
	return 0;
}

static uint64_t rh_encode_ref(struct rh_raw_mft_ref reference)
{
	return (reference.record & UINT64_C(0x0000ffffffffffff)) |
		((uint64_t)reference.sequence << 48);
}

static int rh_build_reparse_manifest(struct rh_system_index_census *census,
		struct rh_index_manifest *canonical)
{
	size_t i;

	for (i = 0; i < census->reparse_count; i++) {
		const struct rh_reparse_fact *fact = &census->reparse[i];
		unsigned char key[12];

		if (fact->file.record >> 48) {
			errno = EUCLEAN;
			return 1;
		}
		rh_put_u32(key, fact->tag);
		rh_put_u64(key + 4U, rh_encode_ref(fact->file));
		if (rh_index_manifest_add(canonical, RH_SYSTEM_INDEX_REPARSE_R,
				key, sizeof(key), NULL, 0) ||
			rh_reference_add(&census->reparse_references,
				&census->reparse_reference_count, fact->file.record,
				fact->file.sequence))
			return -1;
	}
	if (rh_index_manifest_sort(canonical))
		return errno == EUCLEAN ? 1 : -1;
	return rh_index_manifest_hash(canonical,
		census->reparse_manifest_hash);
}

static int rh_build_objid_manifest(struct rh_system_index_census *census,
		const struct rh_index_manifest *observed, int observed_valid,
		struct rh_index_manifest *canonical)
{
	size_t i;
	int complete = 1;

	for (i = 0; i < census->objid_count; i++) {
		struct rh_objid_fact *fact = &census->objid[i];
		unsigned char data[56];
		size_t position;

		if (fact->file.record >> 48) {
			errno = EUCLEAN;
			return 1;
		}
		if (!fact->attribute_has_extended_info) {
			if (!observed_valid || !rh_manifest_find(observed,
					RH_SYSTEM_INDEX_OBJID_O, fact->object_id, 16U,
					&position) || observed->items[position].data_length != 56U ||
				rh_u64(observed->items[position].data) !=
					rh_encode_ref(fact->file)) {
				complete = 0;
				continue;
			}
			memcpy(fact->extended_info,
				observed->items[position].data + 8U, 48U);
			fact->extended_info_authoritative = 1;
		}
		memset(data, 0, sizeof(data));
		rh_put_u64(data, rh_encode_ref(fact->file));
		memcpy(data + 8U, fact->extended_info, 48U);
		if (rh_index_manifest_add(canonical, RH_SYSTEM_INDEX_OBJID_O,
				fact->object_id, 16U, data, sizeof(data)) ||
			rh_reference_add(&census->objid_references,
				&census->objid_reference_count, fact->file.record,
				fact->file.sequence))
			return -1;
	}
	if (!complete)
		return 1;
	if (rh_index_manifest_sort(canonical))
		return errno == EUCLEAN ? 1 : -1;
	return rh_index_manifest_hash(canonical, census->objid_manifest_hash);
}

static int rh_quota_from_q(struct rh_system_index_census *census,
		const struct rh_index_manifest *q,
		struct rh_index_manifest *canonical_o,
		struct rh_index_manifest *canonical_q)
{
	size_t i, default_count = 0;

	for (i = 0; i < q->count; i++) {
		const struct rh_index_item *item = &q->items[i];
		struct rh_quota_fact fact;
		unsigned char owner[4];
		size_t sid_length = 0;

		if (item->kind != RH_SYSTEM_INDEX_QUOTA_Q ||
			item->key_length != 4U || item->data_length < 48U) {
			errno = EUCLEAN;
			return 1;
		}
		memset(&fact, 0, sizeof(fact));
		fact.owner_id = rh_u32(item->key);
		fact.version = rh_u32(item->data);
		fact.flags = rh_u32(item->data + 4U);
		fact.bytes_used = rh_u64(item->data + 8U);
		fact.change_time = (int64_t)rh_u64(item->data + 16U);
		fact.threshold = (int64_t)rh_u64(item->data + 24U);
		fact.limit = (int64_t)rh_u64(item->data + 32U);
		fact.exceeded_time = (int64_t)rh_u64(item->data + 40U);
		if (fact.owner_id == 1U) {
			default_count++;
		} else {
			if (!rh_sid_valid(item->data + 48U,
					item->data_length - 48U, &sid_length) ||
				sid_length > UINT16_MAX ||
				rh_sid_arena_add(census, item->data + 48U, sid_length,
					&fact.sid_offset))
				return errno == EUCLEAN ? 1 : -1;
			fact.sid_length = (uint16_t)sid_length;
			rh_put_u32(owner, fact.owner_id);
			if (rh_index_manifest_add(canonical_o,
					RH_SYSTEM_INDEX_QUOTA_O,
					census->sid_arena + fact.sid_offset, sid_length,
					owner, sizeof(owner)))
				return -1;
		}
		rh_sha256(item->data, item->data_length, fact.value_hash);
		if (rh_quota_fact_add(census, &fact) ||
			rh_index_manifest_add(canonical_q, RH_SYSTEM_INDEX_QUOTA_Q,
				item->key, item->key_length, item->data, item->data_length))
			return -1;
	}
	if (default_count != 1U || rh_index_manifest_sort(canonical_o) ||
		rh_index_manifest_sort(canonical_q))
		return errno == EUCLEAN ? 1 : -1;
	return 0;
}

static int rh_quota_owner_find(const struct rh_system_index_census *census,
		uint32_t owner_id)
{
	size_t low = 0, high = census->quota_count;

	while (low < high) {
		size_t middle = low + (high - low) / 2U;
		uint32_t current = census->quota[middle].owner_id;

		if (current < owner_id)
			low = middle + 1U;
		else
			high = middle;
	}
	return low < census->quota_count &&
		census->quota[low].owner_id == owner_id;
}

static int rh_quota_fact_compare(const void *left, const void *right)
{
	const struct rh_quota_fact *a = left;
	const struct rh_quota_fact *b = right;

	return a->owner_id < b->owner_id ? -1 : a->owner_id > b->owner_id;
}

static int rh_namespace_reciprocity(
		const struct rh_namespace_census *namespace_census,
		const uint8_t *reparse_seen, const uint32_t *reparse_tags,
		struct rh_system_index_census *census)
{
	struct rh_hash_stream hash;
	size_t i;

	rh_hash_stream_init(&hash);
	for (i = 0; i < namespace_census->i30_edge_count; i++) {
		const struct rh_namespace_i30_edge *edge =
			&namespace_census->i30_edges[i];
		const unsigned char *value;
		uint64_t owner = edge->child.record;
		uint32_t flags, tag;
		unsigned char evidence[20];

		if (owner >= census->mft_records_expected ||
			edge->file_name_value_offset >
				namespace_census->i30_value_arena_size ||
			edge->key_length < offsetof(FILE_NAME_ATTR, file_name) ||
			edge->key_length > namespace_census->i30_value_arena_size -
				edge->file_name_value_offset) {
			errno = EUCLEAN;
			return 1;
		}
		value = namespace_census->i30_value_arena +
			edge->file_name_value_offset;
		flags = rh_u32(value + 56U);
		tag = rh_u32(value + 60U);
		if (reparse_seen[owner]) {
			if (!(flags & UINT32_C(0x400)) || tag != reparse_tags[owner]) {
				errno = EUCLEAN;
				return 1;
			}
		} else if (flags & UINT32_C(0x400)) {
			errno = EUCLEAN;
			return 1;
		}
		rh_put_u64(evidence, owner);
		rh_put_u16(evidence + 8U, edge->child.sequence);
		rh_put_u16(evidence + 10U, edge->entry_flags);
		rh_put_u32(evidence + 12U, flags);
		rh_put_u32(evidence + 16U, tag);
		if (rh_hash_stream_update(&hash, evidence, sizeof(evidence)))
			return -1;
		census->file_name_links_examined++;
	}
	return rh_hash_stream_final(&hash,
		census->namespace_reciprocity_hash);
}

static int rh_add_observed_references(struct rh_system_index_census *census,
		const struct rh_index_manifest *manifest,
		enum rh_system_index_kind kind)
{
	size_t i;

	for (i = 0; i < manifest->count; i++) {
		uint64_t encoded;
		struct rh_free_slot_reference **references;
		size_t *count;

		if (kind == RH_SYSTEM_INDEX_REPARSE_R) {
			encoded = rh_u64(manifest->items[i].key + 4U);
			references = &census->reparse_references;
			count = &census->reparse_reference_count;
		} else if (kind == RH_SYSTEM_INDEX_OBJID_O) {
			encoded = rh_u64(manifest->items[i].data);
			references = &census->objid_references;
			count = &census->objid_reference_count;
		} else {
			errno = EINVAL;
			return -1;
		}
		if (rh_reference_add(references, count,
			encoded & UINT64_C(0x0000ffffffffffff),
			(uint16_t)(encoded >> 48)))
			return -1;
	}
	return 0;
}

static int rh_census_hash(struct rh_system_index_census *census)
{
	struct rh_hash_stream hash;
	unsigned char header[96];
	size_t i;

	memset(header, 0, sizeof(header));
	rh_put_u32(header, census->version);
	rh_put_u64(header + 8U, census->generation);
	rh_put_u64(header + 16U, census->mft_records_expected);
	rh_put_u64(header + 24U, census->mft_records_examined);
	rh_put_u64(header + 32U, census->attributes_expected);
	rh_put_u64(header + 40U, census->attributes_examined);
	rh_put_u64(header + 48U, census->file_name_links_expected);
	rh_put_u64(header + 56U, census->file_name_links_examined);
	rh_put_u64(header + 64U, census->index_entries_examined);
	rh_put_u64(header + 72U, census->index_end_entries_examined);
	header[80] = census->records_complete;
	header[81] = census->attributes_complete;
	header[82] = census->namespace_reciprocity_complete;
	header[83] = census->reparse_authority_complete;
	header[84] = census->objid_authority_complete;
	header[85] = census->quota_authority_complete;
	header[86] = census->no_io_uncertainty;
	header[87] = census->complete;
	rh_hash_stream_init(&hash);
	if (rh_hash_stream_update(&hash, "RHSYSIDX1", 9U) ||
		rh_hash_stream_update(&hash, header, sizeof(header)) ||
		rh_hash_stream_update(&hash, census->raw_census_hash, 32U) ||
		rh_hash_stream_update(&hash, census->namespace_census_hash, 32U) ||
		rh_hash_stream_update(&hash, census->reparse_manifest_hash, 32U) ||
		rh_hash_stream_update(&hash, census->objid_manifest_hash, 32U) ||
		rh_hash_stream_update(&hash, census->quota_manifest_hash, 32U) ||
		rh_hash_stream_update(&hash, census->namespace_reciprocity_hash, 32U))
		return -1;
	for (i = 1; i < RH_SYSTEM_INDEX_COUNT; i++) {
		const struct rh_system_index_state *state = &census->index[i];
		unsigned char shape[24];

		memset(shape, 0, sizeof(shape));
		rh_put_u64(shape, state->owner_record);
		rh_put_u16(shape + 8U, state->owner_sequence);
		rh_put_u64(shape + 12U, state->entries_examined);
		shape[20] = state->root_found;
		shape[21] = state->large;
		shape[22] = state->structurally_valid;
		shape[23] = state->manifest_exact;
		if (rh_hash_stream_update(&hash, shape, sizeof(shape)) ||
			rh_hash_stream_update(&hash, state->observed_manifest_hash, 32U) ||
			rh_hash_stream_update(&hash, state->canonical_manifest_hash, 32U))
			return -1;
	}
	for (i = 0; i < census->reparse_reference_count; i++) {
		unsigned char reference[10];

		rh_put_u64(reference, census->reparse_references[i].record);
		rh_put_u16(reference + 8U, census->reparse_references[i].sequence);
		if (rh_hash_stream_update(&hash, "R", 1U) ||
			rh_hash_stream_update(&hash, reference, sizeof(reference)))
			return -1;
	}
	for (i = 0; i < census->objid_reference_count; i++) {
		unsigned char reference[10];

		rh_put_u64(reference, census->objid_references[i].record);
		rh_put_u16(reference + 8U, census->objid_references[i].sequence);
		if (rh_hash_stream_update(&hash, "O", 1U) ||
			rh_hash_stream_update(&hash, reference, sizeof(reference)))
			return -1;
	}
	for (i = 0; i < census->quota_source_reference_count; i++) {
		unsigned char reference[10];

		rh_put_u64(reference, census->quota_source_references[i].record);
		rh_put_u16(reference + 8U,
			census->quota_source_references[i].sequence);
		if (rh_hash_stream_update(&hash, "Q", 1U) ||
			rh_hash_stream_update(&hash, reference, sizeof(reference)))
			return -1;
	}
	return rh_hash_stream_final(&hash, census->census_hash);
}

static void rh_system_index_census_clear(struct rh_system_index_census *census);

static int rh_system_index_census_build(const struct rh_census_reader *reader,
		struct _ntfs_volume *volume, const struct rh_raw_mft_census *raw,
		const struct rh_namespace_census *namespace_census,
		uint64_t generation, struct rh_system_index_census *census)
{
	struct rh_index_manifest observed[RH_SYSTEM_INDEX_COUNT];
	struct rh_index_manifest canonical[RH_SYSTEM_INDEX_COUNT];
	struct rh_raw_mft_ref owner;
	uint8_t *si_seen = NULL, *reparse_seen = NULL;
	uint32_t *si_flags = NULL, *owner_ids = NULL, *reparse_tags = NULL;
	unsigned char quota_hashes[64];
	int inspect_result[RH_SYSTEM_INDEX_COUNT] = { 0 };
	int si_result, reparse_result = 1, objid_result, build_result;
	int quota_result = 1, namespace_result = 1;
	size_t i;
	int result = -1;

	if (!census || !reader || !reader->context || !reader->read || !volume ||
		!raw || !namespace_census || !generation) {
		errno = EINVAL;
		return -1;
	}
	memset(census, 0, sizeof(*census));
	memset(observed, 0, sizeof(observed));
	memset(canonical, 0, sizeof(canonical));
	census->magic = RH_SYSTEM_INDEX_CENSUS_MAGIC;
	census->version = RH_SYSTEM_INDEX_CENSUS_VERSION;
	census->generation = generation;
	census->mft_records_expected = raw->slots_expected;
	census->mft_records_examined = raw->slots_completed;
	census->attributes_expected = raw->attribute_count;
	census->attributes_examined = raw->attribute_count;
	census->file_name_links_expected = raw->file_name_count;
	memcpy(census->raw_census_hash, raw->census_hash, 32U);
	memcpy(census->namespace_census_hash, namespace_census->census_hash, 32U);
	if (raw->generation != generation || raw->slot_count <= 26U ||
		!raw->records_complete || !raw->records_bounded ||
		!raw->layout_complete || !raw->attribute_lists_complete ||
		!raw->extents_complete || raw->slots_completed != raw->slots_expected ||
		raw->unreadable_records || raw->invalid_records ||
		raw->extents_completed != raw->extents_expected ||
		raw->runs_completed != raw->runs_expected ||
		rh_hash_zero(raw->census_hash) ||
		raw->slots[24].state != RH_RAW_SLOT_LIVE_BASE ||
		raw->slots[25].state != RH_RAW_SLOT_LIVE_BASE ||
		raw->slots[26].state != RH_RAW_SLOT_LIVE_BASE ||
		!raw->slots[24].sequence || !raw->slots[25].sequence ||
		!raw->slots[26].sequence ||
		namespace_census->generation != generation ||
		!namespace_census->graph_bounded ||
		!namespace_census->graph_complete || !namespace_census->i30_complete ||
		!namespace_census->reciprocity_complete ||
		namespace_census->links_expected != raw->file_name_count ||
		namespace_census->links_completed != raw->file_name_count ||
		namespace_census->link_count != raw->file_name_count ||
		namespace_census->i30_edge_count != raw->file_name_count ||
		rh_hash_zero(namespace_census->census_hash)) {
		errno = EUCLEAN;
		return rh_census_hash(census);
	}
	census->records_complete = 1;
	census->attributes_complete = 1;
	owner.record = 26U;
	owner.sequence = raw->slots[26].sequence;
	inspect_result[RH_SYSTEM_INDEX_REPARSE_R] = rh_index_inspect(reader,
		volume, raw, owner, RH_SYSTEM_INDEX_REPARSE_R, rh_name_r, 2U,
		&observed[RH_SYSTEM_INDEX_REPARSE_R],
		&census->index[RH_SYSTEM_INDEX_REPARSE_R]);
	owner.record = 25U;
	owner.sequence = raw->slots[25].sequence;
	inspect_result[RH_SYSTEM_INDEX_OBJID_O] = rh_index_inspect(reader,
		volume, raw, owner, RH_SYSTEM_INDEX_OBJID_O, rh_name_o, 2U,
		&observed[RH_SYSTEM_INDEX_OBJID_O],
		&census->index[RH_SYSTEM_INDEX_OBJID_O]);
	owner.record = 24U;
	owner.sequence = raw->slots[24].sequence;
	inspect_result[RH_SYSTEM_INDEX_QUOTA_O] = rh_index_inspect(reader,
		volume, raw, owner, RH_SYSTEM_INDEX_QUOTA_O, rh_name_o, 2U,
		&observed[RH_SYSTEM_INDEX_QUOTA_O],
		&census->index[RH_SYSTEM_INDEX_QUOTA_O]);
	inspect_result[RH_SYSTEM_INDEX_QUOTA_Q] = rh_index_inspect(reader,
		volume, raw, owner, RH_SYSTEM_INDEX_QUOTA_Q, rh_name_q, 2U,
		&observed[RH_SYSTEM_INDEX_QUOTA_Q],
		&census->index[RH_SYSTEM_INDEX_QUOTA_Q]);
	for (i = 1; i < RH_SYSTEM_INDEX_COUNT; i++)
		if (inspect_result[i] < 0)
			goto out;
	si_result = rh_scan_standard_information(raw, census, &si_seen,
		&si_flags, &owner_ids);
	if (si_result < 0)
		goto out;
	if (!si_result) {
		reparse_result = rh_scan_reparse(reader, volume, raw, si_flags,
			census, &reparse_seen, &reparse_tags);
		if (reparse_result < 0)
			goto out;
	}
	objid_result = rh_scan_objid(raw, census);
	if (objid_result < 0)
		goto out;
	if (!reparse_result) {
		build_result = rh_build_reparse_manifest(census,
			&canonical[RH_SYSTEM_INDEX_REPARSE_R]);
		if (build_result < 0)
			goto out;
		if (!build_result)
			census->reparse_authority_complete = 1;
	}
	if (!objid_result) {
		build_result = rh_build_objid_manifest(census,
			&observed[RH_SYSTEM_INDEX_OBJID_O],
			!inspect_result[RH_SYSTEM_INDEX_OBJID_O],
			&canonical[RH_SYSTEM_INDEX_OBJID_O]);
		if (build_result < 0)
			goto out;
		if (!build_result)
			census->objid_authority_complete = 1;
	}
	if (!inspect_result[RH_SYSTEM_INDEX_QUOTA_Q]) {
		quota_result = rh_quota_from_q(census,
			&observed[RH_SYSTEM_INDEX_QUOTA_Q],
			&canonical[RH_SYSTEM_INDEX_QUOTA_O],
			&canonical[RH_SYSTEM_INDEX_QUOTA_Q]);
		if (quota_result < 0)
			goto out;
	}
	if (!quota_result) {
		if (census->quota_count > 1U)
			qsort(census->quota, census->quota_count,
				sizeof(*census->quota), rh_quota_fact_compare);
		for (i = 1; i < census->quota_count; i++)
			if (census->quota[i - 1U].owner_id == census->quota[i].owner_id) {
				quota_result = 1;
				break;
			}
	}
	if (!si_result && !quota_result) {
		for (i = 0; i < raw->slot_count; i++) {
			if (raw->slots[i].state != RH_RAW_SLOT_LIVE_BASE || !owner_ids[i])
				continue;
			census->quota_owner_references_examined++;
			if (owner_ids[i] < 0x100U ||
				!rh_quota_owner_find(census, owner_ids[i])) {
				quota_result = 1;
				break;
			}
			census->quota_owner_references_resolved++;
			if (rh_reference_add(&census->quota_source_references,
					&census->quota_source_reference_count, i,
					raw->slots[i].sequence))
				goto out;
		}
		if (!quota_result)
			census->quota_authority_complete = 1;
	}
	if (!si_result && !reparse_result) {
		namespace_result = rh_namespace_reciprocity(namespace_census,
			reparse_seen,
			reparse_tags, census);
		if (namespace_result < 0)
			goto out;
		if (!namespace_result)
			census->namespace_reciprocity_complete = 1;
	}
	for (i = 1; i < RH_SYSTEM_INDEX_COUNT; i++) {
		struct rh_system_index_state *state = &census->index[i];

		if (canonical[i].items || !canonical[i].count) {
			if (rh_index_manifest_hash(&canonical[i],
					state->canonical_manifest_hash))
				goto out;
		}
		if (!inspect_result[i] &&
			((i == RH_SYSTEM_INDEX_REPARSE_R &&
			  census->reparse_authority_complete) ||
			 (i == RH_SYSTEM_INDEX_OBJID_O &&
			  census->objid_authority_complete) ||
			 ((i == RH_SYSTEM_INDEX_QUOTA_O || i == RH_SYSTEM_INDEX_QUOTA_Q) &&
			  census->quota_authority_complete))) {
			state->manifest_exact = rh_index_manifest_equal(&observed[i],
				&canonical[i]);
			state->clean = state->manifest_exact;
		}
		census->index_entries_examined += state->entries_examined;
		census->index_end_entries_examined += state->end_entries_examined;
		census->index_blocks_examined += state->blocks_examined;
		census->index_blocks_reachable += state->blocks_reachable;
	}
	if (!inspect_result[RH_SYSTEM_INDEX_REPARSE_R] &&
		rh_add_observed_references(census,
			&observed[RH_SYSTEM_INDEX_REPARSE_R],
			RH_SYSTEM_INDEX_REPARSE_R))
		goto out;
	if (!inspect_result[RH_SYSTEM_INDEX_OBJID_O] &&
		rh_add_observed_references(census,
			&observed[RH_SYSTEM_INDEX_OBJID_O], RH_SYSTEM_INDEX_OBJID_O))
		goto out;
	rh_references_sort_unique(census->reparse_references,
		&census->reparse_reference_count);
	rh_references_sort_unique(census->objid_references,
		&census->objid_reference_count);
	rh_references_sort_unique(census->quota_source_references,
		&census->quota_source_reference_count);
	if (census->quota_authority_complete) {
		memcpy(quota_hashes,
			census->index[RH_SYSTEM_INDEX_QUOTA_O].canonical_manifest_hash,
			32U);
		memcpy(quota_hashes + 32U,
			census->index[RH_SYSTEM_INDEX_QUOTA_Q].canonical_manifest_hash,
			32U);
		rh_sha256(quota_hashes, sizeof(quota_hashes),
			census->quota_manifest_hash);
	}
	census->no_io_uncertainty = 1;
	census->complete = !si_result && !reparse_result && !objid_result &&
		!quota_result && !namespace_result;
	if (rh_census_hash(census))
		goto out;
	result = 0;
out:
	for (i = 0; i < RH_SYSTEM_INDEX_COUNT; i++) {
		rh_index_manifest_destroy(&observed[i]);
		rh_index_manifest_destroy(&canonical[i]);
	}
	free(si_seen);
	free(si_flags);
	free(owner_ids);
	free(reparse_seen);
	free(reparse_tags);
	if (result)
		rh_system_index_census_clear(census);
	return result;
}

static void rh_system_index_census_clear(struct rh_system_index_census *census)
{
	if (!census)
		return;
	free(census->reparse);
	free(census->objid);
	free(census->quota);
	free(census->sid_arena);
	free(census->reparse_references);
	free(census->objid_references);
	free(census->quota_source_references);
	memset(census, 0, sizeof(*census));
}

static int rh_system_index_census_valid(
		const struct rh_system_index_census *census)
{
	struct rh_system_index_census copy;

	if (!census || census->magic != RH_SYSTEM_INDEX_CENSUS_MAGIC ||
		census->version != RH_SYSTEM_INDEX_CENSUS_VERSION ||
		rh_hash_zero(census->census_hash))
		return 0;
	copy = *census;
	if (rh_census_hash(&copy))
		return 0;
	return !memcmp(copy.census_hash, census->census_hash, 32U);
}

int rh_system_index_census_run_internal(const struct rh_census_reader *reader,
		struct _ntfs_volume *volume, const struct rh_raw_mft_census *raw,
		const struct rh_namespace_census *namespace_census,
		uint64_t generation, struct rh_system_index_census **output)
{
	struct rh_system_index_census *census;

	if (output)
		*output = NULL;
	if (!output) {
		errno = EINVAL;
		return -1;
	}
	census = calloc(1, sizeof(*census));
	if (!census)
		return -1;
	if (rh_system_index_census_build(reader, volume, raw, namespace_census,
			generation, census)) {
		free(census);
		return -1;
	}
	*output = census;
	return 0;
}

void rh_system_index_census_destroy_internal(
		struct rh_system_index_census *census)
{
	if (!census)
		return;
	rh_system_index_census_clear(census);
	free(census);
}

static int rh_system_index_census_get_view_internal(
		const struct rh_system_index_census *census,
		struct rh_system_index_census_view *view)
{
	if (!view || !rh_system_index_census_valid(census)) {
		errno = EINVAL;
		return -1;
	}
	memset(view, 0, sizeof(*view));
	view->version = census->version;
	view->generation = census->generation;
	view->mft_records_expected = census->mft_records_expected;
	view->mft_records_examined = census->mft_records_examined;
	view->attributes_expected = census->attributes_expected;
	view->attributes_examined = census->attributes_examined;
	view->file_name_links_expected = census->file_name_links_expected;
	view->file_name_links_examined = census->file_name_links_examined;
	view->standard_information_examined =
		census->standard_information_examined;
	view->quota_owner_references_examined =
		census->quota_owner_references_examined;
	view->quota_owner_references_resolved =
		census->quota_owner_references_resolved;
	view->index_entries_examined = census->index_entries_examined;
	view->index_end_entries_examined = census->index_end_entries_examined;
	view->index_blocks_examined = census->index_blocks_examined;
	view->index_blocks_reachable = census->index_blocks_reachable;
	view->records_complete = census->records_complete;
	view->attributes_complete = census->attributes_complete;
	view->namespace_reciprocity_complete =
		census->namespace_reciprocity_complete;
	view->reparse_authority_complete = census->reparse_authority_complete;
	view->objid_authority_complete = census->objid_authority_complete;
	view->quota_authority_complete = census->quota_authority_complete;
	view->no_io_uncertainty = census->no_io_uncertainty;
	view->complete = census->complete;
	view->reparse_count = census->reparse_count;
	view->objid_count = census->objid_count;
	view->quota_count = census->quota_count;
	view->sid_arena_size = census->sid_arena_size;
	view->reparse_reference_count = census->reparse_reference_count;
	view->objid_reference_count = census->objid_reference_count;
	view->quota_source_reference_count =
		census->quota_source_reference_count;
	if (census->quota_count) {
		view->quota_defaults_owner_id = census->quota[0].owner_id;
		view->quota_defaults_version = census->quota[0].version;
		view->quota_defaults_flags = census->quota[0].flags;
	}
	if (census->quota_count > 1U) {
		view->quota_first_user_owner_id = census->quota[1].owner_id;
		view->quota_first_user_version = census->quota[1].version;
		view->quota_first_user_flags = census->quota[1].flags;
		view->quota_first_user_sid_length = census->quota[1].sid_length;
	}
	memcpy(view->index, census->index, sizeof(view->index));
	memcpy(view->raw_census_hash, census->raw_census_hash, 32U);
	memcpy(view->namespace_census_hash, census->namespace_census_hash, 32U);
	memcpy(view->reparse_manifest_hash, census->reparse_manifest_hash, 32U);
	memcpy(view->objid_manifest_hash, census->objid_manifest_hash, 32U);
	memcpy(view->quota_manifest_hash, census->quota_manifest_hash, 32U);
	memcpy(view->namespace_reciprocity_hash,
		census->namespace_reciprocity_hash, 32U);
	memcpy(view->census_hash, census->census_hash, 32U);
	return 0;
}

static int rh_system_index_reparse_component_seal_internal(
		const struct rh_system_index_census *census,
		struct rh_free_slot_component_seal **output)
{
	const struct rh_system_index_state *state;

	if (!output || !rh_system_index_census_valid(census) ||
		!census->generation || !census->records_complete ||
		!census->attributes_complete || !census->no_io_uncertainty ||
		!census->reparse_authority_complete ||
		!census->namespace_reciprocity_complete) {
		errno = EINVAL;
		return -1;
	}
	state = &census->index[RH_SYSTEM_INDEX_REPARSE_R];
	if (!state->structurally_valid) {
		errno = EUCLEAN;
		return -1;
	}
	return rh_free_slot_friend_reparse_seal(census->generation,
		state->entries_examined, state->entries_examined,
		census->census_hash, census->reparse_references,
		census->reparse_reference_count, output);
}

static int rh_system_index_objid_component_seal_internal(
		const struct rh_system_index_census *census,
		struct rh_free_slot_component_seal **output)
{
	const struct rh_system_index_state *state;

	if (!output || !rh_system_index_census_valid(census) ||
		!census->generation || !census->no_io_uncertainty ||
		!census->objid_authority_complete ||
		!census->records_complete || !census->attributes_complete) {
		errno = EINVAL;
		return -1;
	}
	state = &census->index[RH_SYSTEM_INDEX_OBJID_O];
	if (!state->structurally_valid) {
		errno = EUCLEAN;
		return -1;
	}
	return rh_free_slot_friend_objid_seal(census->generation,
		state->entries_examined, state->entries_examined,
		census->census_hash, census->objid_references,
		census->objid_reference_count, output);
}

static int rh_complete_matches(const struct rh_complete_census *complete,
		const struct rh_system_index_census *census)
{
	return complete && complete->version == RH_COMPLETE_CENSUS_VERSION &&
		complete->system_index_authority == census &&
		rh_system_index_census_valid(census) &&
		complete->generation == census->generation &&
		!memcmp(complete->raw.census_hash, census->raw_census_hash, 32U) &&
		!memcmp(complete->namespace_census.census_hash,
			census->namespace_census_hash, 32U);
}

int rh_complete_census_system_indexes_get_view(
		const struct rh_complete_census *complete,
		struct rh_system_index_census_view *view)
{
	if (!view || !complete || !rh_complete_matches(complete,
			complete->system_index_authority)) {
		errno = EPERM;
		return -1;
	}
	return rh_system_index_census_get_view_internal(
		complete->system_index_authority, view);
}

int rh_complete_census_reparse_component_seal_create(
		const struct rh_complete_census *complete,
		struct rh_free_slot_component_seal **output)
{
	if (output)
		*output = NULL;
	if (!output || !complete || !rh_complete_matches(complete,
			complete->system_index_authority)) {
		errno = EPERM;
		return -1;
	}
	return rh_system_index_reparse_component_seal_internal(
		complete->system_index_authority, output);
}

int rh_complete_census_objid_component_seal_create(
		const struct rh_complete_census *complete,
		struct rh_free_slot_component_seal **output)
{
	if (output)
		*output = NULL;
	if (!output || !complete || !rh_complete_matches(complete,
			complete->system_index_authority)) {
		errno = EPERM;
		return -1;
	}
	return rh_system_index_objid_component_seal_internal(
		complete->system_index_authority, output);
}

#ifdef ROOTHEALTH_REPAIR_TESTING
int rh_system_index_census_run(const struct rh_census_reader *reader,
		struct _ntfs_volume *volume, const struct rh_raw_mft_census *raw,
		const struct rh_namespace_census *namespace_census,
		uint64_t generation, struct rh_system_index_census **output)
{
	return rh_system_index_census_run_internal(reader, volume, raw,
		namespace_census, generation, output);
}

void rh_system_index_census_destroy(struct rh_system_index_census *census)
{
	rh_system_index_census_destroy_internal(census);
}

int rh_system_index_census_get_view(
		const struct rh_system_index_census *census,
		struct rh_system_index_census_view *view)
{
	return rh_system_index_census_get_view_internal(census, view);
}

int rh_system_index_reparse_component_seal(
		const struct rh_system_index_census *census,
		struct rh_free_slot_component_seal **output)
{
	return rh_system_index_reparse_component_seal_internal(census, output);
}

int rh_system_index_objid_component_seal(
		const struct rh_system_index_census *census,
		struct rh_free_slot_component_seal **output)
{
	return rh_system_index_objid_component_seal_internal(census, output);
}
#endif
