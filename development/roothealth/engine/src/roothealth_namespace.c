/* ROOTHEALTH_REPAIR_ROLE(DIAGNOSTIC) */
#include "config.h"

#include <errno.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include "endians.h"
#include "layout.h"
#include "roothealth_hash_stream.h"
#include "roothealth_index_bitmap.h"
#include "roothealth_census_device.h"
#include "roothealth_namespace.h"
#include "roothealth_write.h"
#include "volume.h"
#include "unistr.h"

struct rh_namespace_sort_context {
	const struct rh_namespace_census *census;
};

static const struct rh_namespace_census *rh_sort_census;
static const struct rh_namespace_census *rh_i30_sort_census;

struct rh_i30_collect_context {
	const struct rh_raw_mft_census *raw;
	struct rh_namespace_census *census;
	size_t edge_capacity;
	size_t name_capacity;
	size_t value_capacity;
};

static int rh_ref_equal(struct rh_raw_mft_ref first,
		struct rh_raw_mft_ref second)
{
	return first.record == second.record && first.sequence == second.sequence;
}

static int rh_link_name_compare(const struct rh_namespace_census *census,
		const struct rh_namespace_link *first,
		const struct rh_namespace_link *second)
{
	size_t first_bytes = (size_t)first->name_length * 2U;
	size_t second_bytes = (size_t)second->name_length * 2U;
	size_t common = first_bytes < second_bytes ? first_bytes : second_bytes;
	int result = memcmp(census->name_arena + first->name_offset,
		census->name_arena + second->name_offset, common);

	if (result)
		return result;
	return first_bytes < second_bytes ? -1 : first_bytes > second_bytes;
}

static int rh_link_sort_compare(const void *first_pointer,
		const void *second_pointer)
{
	const struct rh_namespace_link *first = first_pointer;
	const struct rh_namespace_link *second = second_pointer;
	int result;

	if (first->owner.record != second->owner.record)
		return first->owner.record < second->owner.record ? -1 : 1;
	if (first->owner.sequence != second->owner.sequence)
		return first->owner.sequence < second->owner.sequence ? -1 : 1;
	if (first->parent.record != second->parent.record)
		return first->parent.record < second->parent.record ? -1 : 1;
	if (first->parent.sequence != second->parent.sequence)
		return first->parent.sequence < second->parent.sequence ? -1 : 1;
	result = rh_link_name_compare(rh_sort_census, first, second);
	if (result)
		return result;
	if (first->name_namespace != second->name_namespace)
		return first->name_namespace < second->name_namespace ? -1 : 1;
	result = memcmp(first->reciprocity_value_hash,
		second->reciprocity_value_hash, 32U);
	if (result)
		return result;
	if (first->storage.record != second->storage.record)
		return first->storage.record < second->storage.record ? -1 : 1;
	if (first->storage.sequence != second->storage.sequence)
		return first->storage.sequence < second->storage.sequence ? -1 : 1;
	if (first->attribute_instance != second->attribute_instance)
		return first->attribute_instance < second->attribute_instance ? -1 : 1;
	if (first->record_value_offset != second->record_value_offset)
		return first->record_value_offset < second->record_value_offset ? -1 : 1;
	result = memcmp(first->file_name_value_hash,
		second->file_name_value_hash, 32U);
	if (result)
		return result;
	result = memcmp(first->logical_link_hash, second->logical_link_hash, 32U);
	if (result)
		return result;
	return 0;
}

static int rh_i30_name_compare(const struct rh_namespace_census *census,
		const struct rh_namespace_i30_edge *first,
		const struct rh_namespace_i30_edge *second)
{
	size_t first_bytes = (size_t)first->name_length * 2U;
	size_t second_bytes = (size_t)second->name_length * 2U;
	size_t common = first_bytes < second_bytes ? first_bytes : second_bytes;
	int result = memcmp(census->i30_name_arena + first->name_offset,
		census->i30_name_arena + second->name_offset, common);

	if (result)
		return result;
	return first_bytes < second_bytes ? -1 : first_bytes > second_bytes;
}

static int rh_i30_sort_compare(const void *first_pointer,
		const void *second_pointer)
{
	const struct rh_namespace_i30_edge *first = first_pointer;
	const struct rh_namespace_i30_edge *second = second_pointer;
	int result;

	if (first->child.record != second->child.record)
		return first->child.record < second->child.record ? -1 : 1;
	if (first->child.sequence != second->child.sequence)
		return first->child.sequence < second->child.sequence ? -1 : 1;
	if (first->parent.record != second->parent.record)
		return first->parent.record < second->parent.record ? -1 : 1;
	if (first->parent.sequence != second->parent.sequence)
		return first->parent.sequence < second->parent.sequence ? -1 : 1;
	result = rh_i30_name_compare(rh_i30_sort_census, first, second);
	if (result)
		return result;
	if (first->name_namespace != second->name_namespace)
		return first->name_namespace < second->name_namespace ? -1 : 1;
	result = memcmp(first->reciprocity_value_hash,
		second->reciprocity_value_hash, 32U);
	if (result)
		return result;
	if (first->from_index_block != second->from_index_block)
		return first->from_index_block < second->from_index_block ? -1 : 1;
	if (first->block_vcn != second->block_vcn)
		return first->block_vcn < second->block_vcn ? -1 : 1;
	return 0;
}

static int rh_grow(void **buffer, size_t *capacity, size_t needed,
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

int rh_namespace_file_name_reciprocity_hash(const unsigned char *value,
		size_t length, unsigned char digest[32])
{
	static const unsigned char ignored_cached_fields[
		offsetof(FILE_NAME_ATTR, file_name_length) -
		offsetof(FILE_NAME_ATTR, creation_time)] = {0};
	struct rh_hash_stream hash;
	size_t stable_suffix = offsetof(FILE_NAME_ATTR, file_name_length);

	if (!value || length < offsetof(FILE_NAME_ATTR, file_name) ||
			length != offsetof(FILE_NAME_ATTR, file_name) +
			(size_t)value[offsetof(FILE_NAME_ATTR, file_name_length)] * 2U) {
		errno = EIO;
		return -1;
	}
	rh_hash_stream_init(&hash);
	if (rh_hash_stream_update(&hash, value,
			offsetof(FILE_NAME_ATTR, creation_time)) ||
			rh_hash_stream_update(&hash, ignored_cached_fields,
				sizeof(ignored_cached_fields)) ||
			rh_hash_stream_update(&hash, value + stable_suffix,
				length - stable_suffix))
		return -1;
	return rh_hash_stream_final(&hash, digest);
}

static int rh_collect_i30_edge(const struct rh_i30_edge_view *view,
		void *opaque)
{
	struct rh_i30_collect_context *context = opaque;
	struct rh_namespace_census *census = context->census;
	struct rh_namespace_i30_edge edge;
	const struct rh_raw_mft_slot *parent, *child;
	size_t name_bytes;

	if (!view || !view->name_utf16le || !view->file_name_value ||
			!view->name_length ||
			view->name_namespace > 3U || !view->parent_sequence ||
			!view->child_sequence || view->parent_mft_record >=
				context->raw->slot_count ||
			view->child_mft_record >= context->raw->slot_count) {
		errno = EIO;
		return -1;
	}
	parent = &context->raw->slots[view->parent_mft_record];
	child = &context->raw->slots[view->child_mft_record];
	if (parent->state != RH_RAW_SLOT_LIVE_BASE ||
			parent->sequence != view->parent_sequence ||
			!(parent->flags & le16_to_cpu(MFT_RECORD_IS_DIRECTORY)) ||
			(child->state != RH_RAW_SLOT_LIVE_BASE &&
			 child->state != RH_RAW_SLOT_FREE) ||
			(child->state == RH_RAW_SLOT_LIVE_BASE &&
			 child->sequence != view->child_sequence)) {
		errno = EIO;
		return -1;
	}
	name_bytes = (size_t)view->name_length * 2U;
	if (name_bytes > SIZE_MAX - census->i30_name_arena_size ||
			view->key_length > SIZE_MAX - census->i30_value_arena_size ||
			rh_grow((void **)&census->i30_edges, &context->edge_capacity,
				census->i30_edge_count + 1U, sizeof(*census->i30_edges)) ||
			rh_grow((void **)&census->i30_name_arena,
				&context->name_capacity,
				census->i30_name_arena_size + name_bytes, 1U) ||
			rh_grow((void **)&census->i30_value_arena,
				&context->value_capacity,
				census->i30_value_arena_size + view->key_length, 1U))
		return -1;
	memset(&edge, 0, sizeof(edge));
	edge.parent.record = view->parent_mft_record;
	edge.parent.sequence = view->parent_sequence;
	edge.child.record = view->child_mft_record;
	edge.child.sequence = view->child_sequence;
	edge.name_namespace = view->name_namespace;
	edge.name_length = view->name_length;
	edge.entry_length = view->entry_length;
	edge.key_length = view->key_length;
	edge.entry_flags = view->entry_flags;
	edge.from_index_block = view->from_index_block;
	edge.block_vcn = view->block_vcn;
	edge.indexed_file_reference = view->indexed_file_reference;
	edge.name_offset = census->i30_name_arena_size;
	edge.file_name_value_offset = census->i30_value_arena_size;
	rh_sha256(view->file_name_value, view->key_length,
		edge.file_name_value_hash);
	if (rh_namespace_file_name_reciprocity_hash(view->file_name_value,
			view->key_length, edge.reciprocity_value_hash))
		return -1;
	memcpy(census->i30_name_arena + census->i30_name_arena_size,
		view->name_utf16le, name_bytes);
	census->i30_name_arena_size += name_bytes;
	memcpy(census->i30_value_arena + census->i30_value_arena_size,
		view->file_name_value, view->key_length);
	census->i30_value_arena_size += view->key_length;
	census->i30_edges[census->i30_edge_count++] = edge;
	return 0;
}

static uint16_t rh_name_unit(const struct rh_namespace_census *census,
		const struct rh_namespace_link *link, size_t index);

static int rh_name_equal_ascii(const struct rh_namespace_census *census,
		const struct rh_namespace_link *link, const char *ascii)
{
	size_t length = strlen(ascii), i;
	const unsigned char *name;

	if (length != link->name_length)
		return 0;
	name = census->name_arena + link->name_offset;
	for (i = 0; i < length; i++)
		if (name[i * 2U] != (unsigned char)ascii[i] || name[i * 2U + 1U])
			return 0;
	return 1;
}

static int rh_name_collates_ascii(const struct rh_namespace_census *census,
		const struct rh_namespace_link *link, const char *ascii,
		const uint16_t *upcase)
{
	size_t length = strlen(ascii), i;

	if (length != link->name_length)
		return 0;
	for (i = 0; i < length; i++)
		if (upcase[rh_name_unit(census, link, i)] !=
				upcase[(unsigned char)ascii[i]])
			return 0;
	return 1;
}

static uint16_t rh_name_unit(const struct rh_namespace_census *census,
		const struct rh_namespace_link *link, size_t index)
{
	const unsigned char *name = census->name_arena + link->name_offset;

	return (uint16_t)name[index * 2U] |
		(uint16_t)((uint16_t)name[index * 2U + 1U] << 8);
}

static int rh_collated_name_equal(const struct rh_namespace_census *census,
		const uint16_t *upcase, const struct rh_namespace_link *first,
		const struct rh_namespace_link *second)
{
	size_t i;

	if (first->name_length != second->name_length)
		return 0;
	for (i = 0; i < first->name_length; i++)
		if (upcase[rh_name_unit(census, first, i)] !=
				upcase[rh_name_unit(census, second, i)])
			return 0;
	return 1;
}

static const struct rh_namespace_census *rh_alias_sort_census;
static const uint16_t *rh_alias_sort_upcase;

static int rh_alias_sort_compare(const void *first_pointer,
		const void *second_pointer)
{
	const struct rh_namespace_link *first = first_pointer;
	const struct rh_namespace_link *second = second_pointer;
	size_t i, common;

	if (first->parent.record != second->parent.record)
		return first->parent.record < second->parent.record ? -1 : 1;
	if (first->parent.sequence != second->parent.sequence)
		return first->parent.sequence < second->parent.sequence ? -1 : 1;
	common = first->name_length < second->name_length ? first->name_length :
		second->name_length;
	for (i = 0; i < common; i++) {
		uint16_t first_unit = rh_alias_sort_upcase[rh_name_unit(
			rh_alias_sort_census, first, i)];
		uint16_t second_unit = rh_alias_sort_upcase[rh_name_unit(
			rh_alias_sort_census, second, i)];
		if (first_unit != second_unit)
			return first_unit < second_unit ? -1 : 1;
	}
	if (first->name_length != second->name_length)
		return first->name_length < second->name_length ? -1 : 1;
	{
		int result = rh_link_name_compare(rh_alias_sort_census, first, second);
		if (result)
			return result;
	}
	if (first->owner.record != second->owner.record)
		return first->owner.record < second->owner.record ? -1 : 1;
	if (first->owner.sequence != second->owner.sequence)
		return first->owner.sequence < second->owner.sequence ? -1 : 1;
	if (first->name_namespace != second->name_namespace)
		return first->name_namespace < second->name_namespace ? -1 : 1;
	return 0;
}

static int rh_alias_owner_compare(const void *first_pointer,
		const void *second_pointer)
{
	const struct rh_namespace_link *first = first_pointer;
	const struct rh_namespace_link *second = second_pointer;

	if (first->owner.record != second->owner.record)
		return first->owner.record < second->owner.record ? -1 : 1;
	if (first->owner.sequence != second->owner.sequence)
		return first->owner.sequence < second->owner.sequence ? -1 : 1;
	return rh_link_name_compare(rh_alias_sort_census, first, second);
}

static int rh_logical_link_sort_compare(const void *first_pointer,
		const void *second_pointer)
{
	const struct rh_namespace_link *first = first_pointer;
	const struct rh_namespace_link *second = second_pointer;

	if (first->owner.record != second->owner.record)
		return first->owner.record < second->owner.record ? -1 : 1;
	if (first->owner.sequence != second->owner.sequence)
		return first->owner.sequence < second->owner.sequence ? -1 : 1;
	if (first->parent.record != second->parent.record)
		return first->parent.record < second->parent.record ? -1 : 1;
	if (first->parent.sequence != second->parent.sequence)
		return first->parent.sequence < second->parent.sequence ? -1 : 1;
	if (first->name_namespace != second->name_namespace)
		return first->name_namespace < second->name_namespace ? -1 : 1;
	return rh_link_name_compare(rh_alias_sort_census, first, second);
}

static int rh_copy_links(const struct rh_raw_mft_census *raw,
		struct rh_namespace_census *census)
{
	size_t i, arena_size = 0, value_arena_size = 0;

	if (raw->file_name_count > SIZE_MAX / sizeof(*census->links)) {
		errno = EOVERFLOW;
		return -1;
	}
	for (i = 0; i < raw->file_name_count; i++) {
		if ((size_t)raw->file_names[i].name_length * 2U >
				SIZE_MAX - arena_size) {
			errno = EOVERFLOW;
			return -1;
		}
		arena_size += (size_t)raw->file_names[i].name_length * 2U;
		if (raw->file_names[i].value_length > SIZE_MAX - value_arena_size) {
			errno = EOVERFLOW;
			return -1;
		}
		value_arena_size += raw->file_names[i].value_length;
	}
	census->links = calloc(raw->file_name_count ? raw->file_name_count : 1U,
		sizeof(*census->links));
	census->name_arena = malloc(arena_size ? arena_size : 1U);
	census->file_name_value_arena = malloc(value_arena_size ?
		value_arena_size : 1U);
	if (!census->links || !census->name_arena ||
			!census->file_name_value_arena)
		return -1;
	for (i = 0; i < raw->file_name_count; i++) {
		const struct rh_raw_file_name *source = &raw->file_names[i];
		struct rh_namespace_link *target = &census->links[i];
		size_t bytes = (size_t)source->name_length * 2U;

		target->owner = source->owner;
		target->storage = source->storage;
		target->parent = source->parent;
		target->attribute_instance = source->attribute_instance;
		target->record_value_offset = source->record_value_offset;
		target->name_namespace = source->name_namespace;
		target->name_length = source->name_length;
		target->file_name_value_length = source->value_length;
		target->file_name_value_offset = census->file_name_value_arena_size;
		memcpy(target->file_name_value_hash, source->value_hash,
			sizeof(target->file_name_value_hash));
		memcpy(target->logical_link_hash, source->logical_link_hash,
			sizeof(target->logical_link_hash));
		if (rh_namespace_file_name_reciprocity_hash(raw->value_arena +
				source->value_arena_offset, source->value_length,
				target->reciprocity_value_hash))
			return -1;
		target->name_offset = census->name_arena_size;
		memcpy(census->name_arena + census->name_arena_size,
			raw->name_arena + source->name_offset, bytes);
		census->name_arena_size += bytes;
		memcpy(census->file_name_value_arena +
			census->file_name_value_arena_size,
			raw->value_arena + source->value_arena_offset,
			source->value_length);
		census->file_name_value_arena_size += source->value_length;
	}
	census->link_count = raw->file_name_count;
	return 0;
}

static int rh_parent_valid(const struct rh_raw_mft_census *raw,
		struct rh_raw_mft_ref parent)
{
	const struct rh_raw_mft_slot *slot;

	if (parent.record >= raw->slot_count)
		return 0;
	slot = &raw->slots[parent.record];
	return slot->state == RH_RAW_SLOT_LIVE_BASE &&
		slot->sequence == parent.sequence &&
		(slot->flags & le16_to_cpu(MFT_RECORD_IS_DIRECTORY));
}

static int rh_validate_graph(const struct rh_raw_mft_census *raw,
		struct rh_namespace_census *census, const uint16_t *upcase)
{
	struct rh_namespace_link *alias_links = NULL;
	struct rh_namespace_link *logical_links = NULL;
	uint64_t *logical_link_count = NULL;
	uint64_t *directory_parent = NULL;
	uint8_t *directory_parent_known = NULL;
	uint8_t *reach_state = NULL;
	uint8_t *file_parent_seen = NULL;
	uint8_t *file_parents_reachable = NULL;
	uint64_t *path = NULL;
	size_t i;
	int result = -1;

	if (raw->slot_count > SIZE_MAX / sizeof(*directory_parent) ||
			raw->slot_count > SIZE_MAX / sizeof(*path) ||
			census->link_count > SIZE_MAX / sizeof(*alias_links)) {
		errno = EOVERFLOW;
		return -1;
	}
	directory_parent = malloc(raw->slot_count * sizeof(*directory_parent));
	directory_parent_known = calloc(raw->slot_count,
		sizeof(*directory_parent_known));
	reach_state = calloc(raw->slot_count, sizeof(*reach_state));
	file_parent_seen = calloc(raw->slot_count, sizeof(*file_parent_seen));
	file_parents_reachable = malloc(raw->slot_count *
		sizeof(*file_parents_reachable));
	path = malloc(raw->slot_count * sizeof(*path));
	alias_links = malloc((census->link_count ? census->link_count : 1U) *
		sizeof(*alias_links));
	logical_links = malloc((census->link_count ? census->link_count : 1U) *
		sizeof(*logical_links));
	logical_link_count = calloc(raw->slot_count,
		sizeof(*logical_link_count));
	if (!directory_parent || !directory_parent_known || !reach_state ||
			!file_parent_seen || !file_parents_reachable || !path || !alias_links ||
			!logical_links || !logical_link_count)
		goto out;
	memset(file_parents_reachable, 1,
		raw->slot_count * sizeof(*file_parents_reachable));
	memset(directory_parent, 0xff,
		raw->slot_count * sizeof(*directory_parent));
	memcpy(alias_links, census->links,
		census->link_count * sizeof(*alias_links));
	memcpy(logical_links, census->links,
		census->link_count * sizeof(*logical_links));
	rh_alias_sort_census = census;
	qsort(logical_links, census->link_count, sizeof(*logical_links),
		rh_logical_link_sort_compare);
	rh_alias_sort_census = NULL;
	for (i = 0; i < census->link_count;) {
		size_t end = i + 1U, dos = 0, win32 = 0, j;
		uint64_t owner = logical_links[i].owner.record;

		while (end < census->link_count &&
				rh_ref_equal(logical_links[i].owner,
					logical_links[end].owner) &&
				rh_ref_equal(logical_links[i].parent,
					logical_links[end].parent))
			end++;
		for (j = i; j < end; j++) {
			dos += logical_links[j].name_namespace == FILE_NAME_DOS;
			win32 += logical_links[j].name_namespace == FILE_NAME_WIN32;
		}
		if (owner < raw->slot_count) {
			logical_link_count[owner] += end - i -
				(dos == 1U && win32 == 1U ? 1U : 0U);
			if (dos > 1U || win32 > 1U)
				census->unresolved_parents++;
		}
		i = end;
	}

	for (i = 0; i < raw->slot_count; i++) {
		const struct rh_raw_mft_slot *slot = &raw->slots[i];
		if (slot->state != RH_RAW_SLOT_LIVE_BASE)
			continue;
		census->live_nodes_expected++;
		/* Windows counts a DOS/Win32 FILE_NAME pair as two links while
		 * ntfs-3g may count the same logical directory entry as one.  Both
		 * encodings are structurally valid when they match an exact census. */
		if ((slot->link_count != logical_link_count[i] &&
			 slot->link_count != slot->owned_file_name_count) ||
				((slot->flags & le16_to_cpu(MFT_RECORD_IS_DIRECTORY)) &&
				 logical_link_count[i] != (i >= 12U && i <= 15U ? 0U : 1U))) {
			census->unresolved_parents++;
			continue;
		}
		census->live_nodes_completed++;
		if (!slot->owned_file_name_count && (i < 12U || i > 15U))
			census->orphan_nodes++;
	}
	for (i = 0; i < census->link_count; i++) {
		const struct rh_namespace_link *link = &census->links[i];
		const struct rh_raw_mft_slot *owner;

		if (link->owner.record >= raw->slot_count ||
				link->storage.record >= raw->slot_count ||
				!link->name_length || link->name_namespace > 3U) {
			census->unresolved_parents++;
			continue;
		}
		owner = &raw->slots[link->owner.record];
		if (owner->state != RH_RAW_SLOT_LIVE_BASE ||
				owner->sequence != link->owner.sequence ||
				!rh_parent_valid(raw, link->parent)) {
			census->unresolved_parents++;
			continue;
		}
		if (rh_ref_equal(link->owner, link->parent) &&
				!(link->owner.record == 5U &&
				 rh_name_equal_ascii(census, link, "."))) {
			census->cycles++;
			continue;
		}
		if ((owner->flags & le16_to_cpu(MFT_RECORD_IS_DIRECTORY)) &&
				link->owner.record != 5U) {
			if (!directory_parent_known[link->owner.record]) {
				directory_parent[link->owner.record] = link->parent.record;
				directory_parent_known[link->owner.record] = 1;
			} else if (directory_parent[link->owner.record] !=
					link->parent.record) {
				census->unresolved_parents++;
			}
		}
		census->links_completed++;
	}
	rh_alias_sort_census = census;
	rh_alias_sort_upcase = upcase;
	qsort(alias_links, census->link_count, sizeof(*alias_links),
		rh_alias_sort_compare);
	rh_alias_sort_census = NULL;
	rh_alias_sort_upcase = NULL;
	for (i = 0; i < census->link_count;) {
		size_t end = i + 1U, j;
		int valid_dos_win_pair, valid_case_collision;

		while (end < census->link_count &&
				rh_ref_equal(alias_links[i].parent,
					alias_links[end].parent) &&
				rh_collated_name_equal(census, upcase, &alias_links[i],
					&alias_links[end]))
			end++;
		valid_dos_win_pair = end - i == 2U &&
			rh_ref_equal(alias_links[i].owner, alias_links[i + 1U].owner) &&
			((alias_links[i].name_namespace == FILE_NAME_DOS &&
			  alias_links[i + 1U].name_namespace == FILE_NAME_WIN32) ||
			 (alias_links[i].name_namespace == FILE_NAME_WIN32 &&
			  alias_links[i + 1U].name_namespace == FILE_NAME_DOS));
		valid_case_collision = end - i > 1U;
		for (j = i; valid_case_collision && j < end; j++)
			if (alias_links[j].name_namespace == FILE_NAME_DOS ||
					alias_links[j].name_namespace == FILE_NAME_WIN32_AND_DOS ||
					(j > i && !rh_link_name_compare(census,
						&alias_links[j - 1U], &alias_links[j])))
				valid_case_collision = 0;
		if (valid_case_collision) {
			rh_alias_sort_census = census;
			qsort(alias_links + i, end - i, sizeof(*alias_links),
				rh_alias_owner_compare);
			rh_alias_sort_census = NULL;
			for (j = i + 1U; j < end; j++)
				if (rh_ref_equal(alias_links[j - 1U].owner,
						alias_links[j].owner)) {
					valid_case_collision = 0;
					break;
				}
		}
		if (valid_case_collision)
			census->posix_case_collisions += end - i - 1U;
		if (end - i > 1U && !valid_dos_win_pair &&
				!valid_case_collision)
			census->aliases += end - i - 1U;
		i = end;
	}
	if (raw->slot_count > 5U)
		reach_state[5] = 2;
	for (i = 0; i < raw->slot_count; i++) {
		const struct rh_raw_mft_slot *slot = &raw->slots[i];
		uint64_t current = i;
		size_t path_count = 0;
		uint8_t outcome = 0;

		if (slot->state != RH_RAW_SLOT_LIVE_BASE || i == 5U ||
				!(slot->flags & le16_to_cpu(MFT_RECORD_IS_DIRECTORY)) ||
				reach_state[i])
			continue;
		while (!outcome) {
			if (current >= raw->slot_count ||
					raw->slots[current].state != RH_RAW_SLOT_LIVE_BASE ||
					!(raw->slots[current].flags &
					 le16_to_cpu(MFT_RECORD_IS_DIRECTORY))) {
				outcome = 3;
				break;
			}
			if (reach_state[current] == 2 || reach_state[current] == 3) {
				outcome = reach_state[current];
				break;
			}
			if (reach_state[current] == 1) {
				census->cycles++;
				outcome = 3;
				break;
			}
			reach_state[current] = 1;
			path[path_count++] = current;
			if (!directory_parent_known[current]) {
				outcome = 3;
				break;
			}
			current = directory_parent[current];
		}
		while (path_count)
			reach_state[path[--path_count]] = outcome;
	}
	for (i = 0; i < census->link_count; i++) {
		const struct rh_namespace_link *link = &census->links[i];
		const struct rh_raw_mft_slot *owner;

		if (link->owner.record >= raw->slot_count)
			continue;
		owner = &raw->slots[link->owner.record];
		if (owner->state != RH_RAW_SLOT_LIVE_BASE ||
				(owner->flags & le16_to_cpu(MFT_RECORD_IS_DIRECTORY)))
			continue;
		file_parent_seen[link->owner.record] = 1;
		if (link->parent.record >= raw->slot_count ||
				reach_state[link->parent.record] != 2)
			file_parents_reachable[link->owner.record] = 0;
	}
	for (i = 0; i < raw->slot_count; i++) {
		const struct rh_raw_mft_slot *slot = &raw->slots[i];

		if (slot->state != RH_RAW_SLOT_LIVE_BASE || i == 5U ||
				(i >= 12U && i <= 15U) || !slot->owned_file_name_count)
			continue;
		if (slot->flags & le16_to_cpu(MFT_RECORD_IS_DIRECTORY)) {
			if (reach_state[i] == 2)
				census->reachable_nodes++;
			else
				census->unresolved_parents++;
			continue;
		}
		if (file_parent_seen[i] && file_parents_reachable[i])
			census->reachable_nodes++;
		else
			census->unresolved_parents++;
	}
	result = 0;
out:
	free(alias_links);
	free(logical_links);
	free(logical_link_count);
	free(directory_parent);
	free(directory_parent_known);
	free(reach_state);
	free(file_parent_seen);
	free(file_parents_reachable);
	free(path);
	return result;
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

static int rh_hash_graph(const struct rh_raw_mft_census *raw,
		struct rh_namespace_census *census)
{
	struct rh_hash_stream graph, manifest, complete;
	unsigned char record[136];
	size_t i;

	rh_hash_stream_init(&graph);
	if (rh_hash_stream_update(&graph, "RHNSG1\0\0", 8U) ||
			rh_hash_stream_update(&graph, census->upcase_hash, 32U))
		return -1;
	for (i = 0; i < raw->slot_count; i++) {
		const struct rh_raw_mft_slot *slot = &raw->slots[i];
		if (slot->state != RH_RAW_SLOT_LIVE_BASE)
			continue;
		memset(record, 0, 32U);
		rh_put_u64le(record, slot->record);
		rh_put_u16le(record + 8, slot->sequence);
		rh_put_u16le(record + 10, slot->flags);
		rh_put_u16le(record + 12, slot->link_count);
		if (rh_hash_stream_update(&graph, record, 32U))
			return -1;
	}
	rh_sort_census = census;
	qsort(census->links, census->link_count, sizeof(*census->links),
		rh_link_sort_compare);
	rh_sort_census = NULL;
	for (i = 0; i < census->link_count; i++) {
		const struct rh_namespace_link *link = &census->links[i];
		size_t name_bytes = (size_t)link->name_length * 2U;
		memset(record, 0, 48U);
		rh_put_u64le(record, link->owner.record);
		rh_put_u16le(record + 8, link->owner.sequence);
		rh_put_u64le(record + 16, link->parent.record);
		rh_put_u16le(record + 24, link->parent.sequence);
		record[26] = link->name_namespace;
		record[27] = link->name_length;
		if (rh_hash_stream_update(&graph, record, 48U) ||
				rh_hash_stream_update(&graph,
					census->name_arena + link->name_offset, name_bytes))
			return -1;
	}
	if (rh_hash_stream_final(&graph, census->graph_hash))
		return -1;
	rh_hash_stream_init(&manifest);
	if (rh_hash_stream_update(&manifest, "RHNSM1\0\0", 8U))
		return -1;
	for (i = 0; i < census->link_count; i++) {
		const struct rh_namespace_link *link = &census->links[i];
		memset(record, 0, 128U);
		rh_put_u64le(record, link->storage.record);
		rh_put_u16le(record + 8, link->storage.sequence);
		rh_put_u16le(record + 10, link->attribute_instance);
		rh_put_u32le(record + 12, link->record_value_offset);
		rh_put_u64le(record + 16, link->owner.record);
		rh_put_u16le(record + 24, link->owner.sequence);
		rh_put_u32le(record + 28, link->file_name_value_length);
		memcpy(record + 32, link->file_name_value_hash, 32U);
		memcpy(record + 64, link->logical_link_hash, 32U);
		memcpy(record + 96, link->reciprocity_value_hash, 32U);
		if (rh_hash_stream_update(&manifest, record, 128U))
			return -1;
	}
	if (rh_hash_stream_final(&manifest, census->manifest_hash))
		return -1;
	memset(record, 0, sizeof(record));
	memcpy(record, "RHNSC2\0\0", 8U);
	rh_put_u64le(record + 8, census->live_nodes_expected);
	rh_put_u64le(record + 16, census->live_nodes_completed);
	rh_put_u64le(record + 24, census->links_expected);
	rh_put_u64le(record + 32, census->links_completed);
	rh_put_u64le(record + 40, census->reachable_nodes);
	rh_put_u64le(record + 48, census->orphan_nodes);
	rh_put_u64le(record + 56, census->unresolved_parents);
	rh_put_u64le(record + 64, census->cycles);
	rh_put_u64le(record + 72, census->aliases);
	rh_put_u64le(record + 80, census->posix_case_collisions);
	memcpy(record + 88, census->graph_hash, 32);
	memcpy(record + 120, census->manifest_hash, 16);
	rh_hash_stream_init(&complete);
	if (rh_hash_stream_update(&complete, record, sizeof(record)) ||
			rh_hash_stream_update(&complete, census->manifest_hash + 16, 16U))
		return -1;
	return rh_hash_stream_final(&complete, census->census_hash);
}

static int rh_link_edge_compare(const struct rh_namespace_census *census,
		const struct rh_namespace_link *link,
		const struct rh_namespace_i30_edge *edge)
{
	size_t link_bytes, edge_bytes, common;
	int result;

	if (link->owner.record != edge->child.record)
		return link->owner.record < edge->child.record ? -1 : 1;
	if (link->owner.sequence != edge->child.sequence)
		return link->owner.sequence < edge->child.sequence ? -1 : 1;
	if (link->parent.record != edge->parent.record)
		return link->parent.record < edge->parent.record ? -1 : 1;
	if (link->parent.sequence != edge->parent.sequence)
		return link->parent.sequence < edge->parent.sequence ? -1 : 1;
	link_bytes = (size_t)link->name_length * 2U;
	edge_bytes = (size_t)edge->name_length * 2U;
	common = link_bytes < edge_bytes ? link_bytes : edge_bytes;
	result = memcmp(census->name_arena + link->name_offset,
		census->i30_name_arena + edge->name_offset, common);
	if (result)
		return result;
	if (link_bytes != edge_bytes)
		return link_bytes < edge_bytes ? -1 : 1;
	if (link->name_namespace != edge->name_namespace)
		return link->name_namespace < edge->name_namespace ? -1 : 1;
	if (link->file_name_value_length != edge->key_length)
		return link->file_name_value_length < edge->key_length ? -1 : 1;
	result = memcmp(link->reciprocity_value_hash,
		edge->reciprocity_value_hash, 32U);
	if (result)
		return result;
	return 0;
}

static int rh_hash_i30_reciprocity(struct rh_namespace_census *census)
{
	struct rh_hash_stream edges, manifest, reciprocity, combined;
	unsigned char record[160], prior_census_hash[32];
	size_t i;

	rh_hash_stream_init(&edges);
	rh_hash_stream_init(&manifest);
	if (rh_hash_stream_update(&edges, "RHI30E1\0", 8U))
		return -1;
	if (rh_hash_stream_update(&manifest, "RHI30M1\0", 8U))
		return -1;
	for (i = 0; i < census->i30_edge_count; i++) {
		const struct rh_namespace_i30_edge *edge = &census->i30_edges[i];
		size_t name_bytes = (size_t)edge->name_length * 2U;

		memset(record, 0, 48U);
		rh_put_u64le(record, edge->child.record);
		rh_put_u16le(record + 8, edge->child.sequence);
		rh_put_u64le(record + 16, edge->parent.record);
		rh_put_u16le(record + 24, edge->parent.sequence);
		record[26] = edge->name_namespace;
		record[27] = edge->name_length;
		if (rh_hash_stream_update(&edges, record, 48U) ||
				rh_hash_stream_update(&edges,
					census->i30_name_arena + edge->name_offset, name_bytes))
			return -1;
		memset(record, 0, 128U);
		rh_put_u64le(record, edge->child.record);
		rh_put_u16le(record + 8, edge->child.sequence);
		rh_put_u64le(record + 16, edge->parent.record);
		rh_put_u16le(record + 24, edge->parent.sequence);
		rh_put_u64le(record + 32, edge->indexed_file_reference);
		rh_put_u16le(record + 40, edge->entry_length);
		rh_put_u16le(record + 42, edge->key_length);
		rh_put_u16le(record + 44, edge->entry_flags);
		record[46] = edge->from_index_block;
		rh_put_u64le(record + 48, (uint64_t)edge->block_vcn);
		memcpy(record + 64, edge->file_name_value_hash, 32U);
		memcpy(record + 96, edge->reciprocity_value_hash, 32U);
		if (rh_hash_stream_update(&manifest, record, 128U))
			return -1;
	}
	if (rh_hash_stream_final(&edges, census->i30_edge_hash) ||
			rh_hash_stream_final(&manifest, census->i30_manifest_hash))
		return -1;
	memset(record, 0, 136U);
	memcpy(record, "RHNSR1\0\0", 8U);
	rh_put_u64le(record + 8, census->link_count);
	rh_put_u64le(record + 16, census->i30_edge_count);
	record[24] = census->reciprocity_complete;
	memcpy(record + 32, census->graph_hash, 32);
	memcpy(record + 64, census->i30_edge_hash, 32);
	memcpy(record + 96, census->i30_manifest_hash, 32);
	rh_put_u64le(record + 128, census->cached_file_name_differences);
	rh_hash_stream_init(&reciprocity);
	if (rh_hash_stream_update(&reciprocity, record, 136U))
		return -1;
	memset(record, 0, 104U);
	memcpy(record, "RHI30C1\0", 8U);
	rh_put_u64le(record + 8, census->i30_directories_expected);
	rh_put_u64le(record + 16, census->i30_directories_completed);
	rh_put_u64le(record + 24, census->i30_indexes_expected);
	rh_put_u64le(record + 32, census->i30_indexes_completed);
	rh_put_u64le(record + 40, census->i30_entries_examined);
	rh_put_u64le(record + 48, census->i30_blocks_expected);
	rh_put_u64le(record + 56, census->i30_blocks_examined);
	rh_put_u64le(record + 64, census->i30_blocks_reachable);
	rh_put_u64le(record + 72, census->i30_child_vcns_examined);
	rh_put_u64le(record + 80, census->i30_bitmap_bits_examined);
	rh_put_u64le(record + 88, census->i30_bitmap_changes);
	rh_put_u64le(record + 96, census->i30_clear_bits_required);
	if (rh_hash_stream_update(&reciprocity, record, 104U) ||
			rh_hash_stream_final(&reciprocity, census->reciprocity_hash))
		return -1;
	memcpy(prior_census_hash, census->census_hash,
		sizeof(prior_census_hash));
	memset(record, 0, 136U);
	memcpy(record, "RHNSC3\0\0", 8U);
	memcpy(record + 8, prior_census_hash, 32);
	memcpy(record + 40, census->i30_edge_hash, 32);
	memcpy(record + 72, census->reciprocity_hash, 32);
	memcpy(record + 104, census->i30_manifest_hash, 32);
	rh_hash_stream_init(&combined);
	if (rh_hash_stream_update(&combined, record, 136U))
		return -1;
	memset(record, 0, 104U);
	memcpy(record, "RHI30H1\0", 8U);
	memcpy(record + 8, census->i30_tree_hash, 32U);
	memcpy(record + 40, census->i30_expected_bitmap_hash, 32U);
	memcpy(record + 72, census->i30_index_census_hash, 32U);
	if (rh_hash_stream_update(&combined, record, 104U))
		return -1;
	return rh_hash_stream_final(&combined, census->census_hash);
}

int rh_namespace_i30_census_run_reader(ntfs_volume *volume,
		const struct rh_census_reader *reader,
		const struct rh_raw_mft_census *raw,
		struct rh_namespace_census *census,
		struct rh_index_bitmap_census *index_output)
{
	struct rh_i30_collect_context context;
	size_t i;
	int result = -1;

	if (!volume || !reader || !raw || !census || !index_output ||
			!census->graph_bounded || census->i30_edges ||
			census->i30_name_arena) {
		errno = EINVAL;
		return -1;
	}
	memset(index_output, 0, sizeof(*index_output));
	memset(&context, 0, sizeof(context));
	context.raw = raw;
	context.census = census;
	if (rh_index_bitmap_census_run_edges_from_raw_reader(volume, reader, raw,
			census->generation, index_output, rh_collect_i30_edge, &context) ||
			!index_output->complete ||
			!index_output->index_tree_complete ||
			!index_output->child_vcns_valid ||
			!index_output->indx_blocks_valid ||
			!index_output->reachable_set_exact)
		goto out;
	census->i30_directories_expected = index_output->directories_expected;
	census->i30_directories_completed = index_output->directories_completed;
	census->i30_indexes_expected = index_output->indexes_expected;
	census->i30_indexes_completed = index_output->indexes_completed;
	census->i30_entries_examined = index_output->index_entries_examined;
	census->i30_blocks_expected = index_output->index_blocks_expected;
	census->i30_blocks_examined = index_output->index_blocks_examined;
	census->i30_blocks_reachable = index_output->index_blocks_reachable;
	census->i30_child_vcns_examined = index_output->child_vcns_examined;
	census->i30_bitmap_bits_examined = index_output->bitmap_bits_examined;
	census->i30_bitmap_changes = index_output->change_count;
	census->i30_clear_bits_required = index_output->clear_bits_required;
	memcpy(census->i30_tree_hash, index_output->tree_hash, 32U);
	memcpy(census->i30_expected_bitmap_hash, index_output->expected_hash, 32U);
	memcpy(census->i30_index_census_hash, index_output->census_hash, 32U);
	rh_i30_sort_census = census;
	qsort(census->i30_edges, census->i30_edge_count,
		sizeof(*census->i30_edges), rh_i30_sort_compare);
	rh_i30_sort_census = NULL;
	census->i30_complete = 1;
	census->reciprocity_complete = census->link_count == census->i30_edge_count;
	if (census->reciprocity_complete) {
		for (i = 0; i < census->link_count; i++) {
			if (rh_link_edge_compare(census, &census->links[i],
					&census->i30_edges[i])) {
				census->reciprocity_complete = 0;
				break;
			} else if (memcmp(census->links[i].file_name_value_hash,
					census->i30_edges[i].file_name_value_hash, 32U))
				census->cached_file_name_differences++;
		}
	}
	if (rh_hash_i30_reciprocity(census))
		goto out;
	result = 0;
out:
	if (result) {
		rh_index_bitmap_census_destroy(index_output);
		free(census->i30_edges);
		free(census->i30_name_arena);
		free(census->i30_value_arena);
		census->i30_edges = NULL;
		census->i30_edge_count = 0;
		census->i30_name_arena = NULL;
		census->i30_name_arena_size = 0;
		census->i30_value_arena = NULL;
		census->i30_value_arena_size = 0;
		census->i30_complete = 0;
		census->reciprocity_complete = 0;
	}
	return result;
}

int rh_namespace_i30_census_run(ntfs_volume *volume,
		struct rh_writer *writer, const struct rh_raw_mft_census *raw,
		struct rh_namespace_census *census)
{
	struct rh_census_reader reader;
	struct rh_index_bitmap_census index;
	int result;

	memset(&index, 0, sizeof(index));
	if (!writer || rh_census_reader_from_writer_prefix(writer,
			writer->operation_count, &reader))
		return -1;
	result = rh_namespace_i30_census_run_reader(volume, &reader, raw, census,
		&index);
	rh_index_bitmap_census_destroy(&index);
	return result;
}

int rh_namespace_census_run(const struct rh_raw_mft_census *raw,
		uint64_t generation, struct rh_namespace_census *census)
{
	static const char expected_upcase[] =
		"41c26bc7a12bdaeb26025c93118697c7e3ef81ee048b00fe5cce2a472e0e0742";
	uint16_t *upcase = NULL;
	char actual_upcase[65];
	u32 upcase_length;

	if (!raw || !census || !generation || !raw->records_bounded ||
			!raw->attribute_lists_complete || !raw->extents_complete ||
			!raw->slots || !raw->slot_count) {
		errno = EINVAL;
		return -1;
	}
	memset(census, 0, sizeof(*census));
	census->generation = generation;
	upcase_length = ntfs_upcase_build_default((ntfschar **)&upcase);
	if (!upcase || upcase_length != 65536U) {
		errno = EIO;
		goto fail;
	}
	rh_sha256(upcase, (size_t)upcase_length * sizeof(*upcase),
		census->upcase_hash);
	rh_sha256_hex(upcase, (size_t)upcase_length * sizeof(*upcase),
		actual_upcase);
	if (strcmp(actual_upcase, expected_upcase) ||
			rh_copy_links(raw, census)) {
		if (!errno)
			errno = EIO;
		goto fail;
	}
	census->links_expected = raw->file_name_count;
	if (rh_validate_graph(raw, census, upcase) ||
			rh_hash_graph(raw, census)) {
		if (!errno)
			errno = EIO;
		goto fail;
	}
	census->graph_bounded = 1;
	census->graph_complete = census->graph_bounded &&
		census->live_nodes_completed == census->live_nodes_expected &&
		census->links_completed == census->links_expected &&
		!census->orphan_nodes && !census->unresolved_parents &&
		!census->cycles && !census->aliases;
	free(upcase);
	return 0;
fail:
	free(upcase);
	rh_namespace_census_release(census);
	return -1;
}

static int rh_find_child(const struct rh_raw_mft_census *raw,
		const struct rh_namespace_census *census, struct rh_raw_mft_ref parent,
		const char *name, int require_directory, const uint16_t *upcase,
		struct rh_raw_mft_ref *child)
{
	size_t i;
	int found = 0, exact_spelling = 0;

	for (i = 0; i < census->link_count; i++) {
		const struct rh_namespace_link *link = &census->links[i];
		const struct rh_raw_mft_slot *slot;

		if (!rh_ref_equal(link->parent, parent) ||
				!rh_name_collates_ascii(census, link, name, upcase) ||
				link->owner.record >= raw->slot_count)
			continue;
		slot = &raw->slots[link->owner.record];
		if (slot->state != RH_RAW_SLOT_LIVE_BASE ||
				slot->sequence != link->owner.sequence ||
				!!(slot->flags & le16_to_cpu(MFT_RECORD_IS_DIRECTORY)) !=
					require_directory)
			continue;
		if (found)
			return -1;
		*child = link->owner;
		found = 1;
		if (rh_name_equal_ascii(census, link, name))
			exact_spelling = 1;
	}
	return found && exact_spelling;
}

static int rh_find_path(const struct rh_raw_mft_census *raw,
		const struct rh_namespace_census *census, const char *path,
		const uint16_t *upcase)
{
	char component[256];
	struct rh_raw_mft_ref current = {5U, 0};
	const char *cursor = path;

	if (raw->slot_count <= 5U ||
			raw->slots[5].state != RH_RAW_SLOT_LIVE_BASE)
		return 0;
	current.sequence = raw->slots[5].sequence;
	while (*cursor) {
		const char *slash = strchr(cursor, '/');
		size_t length = slash ? (size_t)(slash - cursor) : strlen(cursor);
		struct rh_raw_mft_ref next = {0, 0};
		int directory = !!slash;
		int status;

		if (!length || length >= sizeof(component))
			return -1;
		memcpy(component, cursor, length);
		component[length] = 0;
		status = rh_find_child(raw, census, current, component, directory,
			upcase, &next);
		if (status <= 0)
			return status;
		current = next;
		cursor = slash ? slash + 1U : cursor + length;
	}
	return 1;
}

static int rh_hash_recovery_anchor(
		const struct rh_namespace_census *census,
		struct rh_namespace_recovery_anchor *anchor)
{
	static const char *const names[RH_NAMESPACE_RECOVERY_ANCHOR_COMPONENTS] = {
		"the one", "recovered files", "roothealth",
	};
	struct rh_hash_stream hash;
	unsigned char header[48], record[24], length[2];
	size_t i;

	memset(header, 0, sizeof(header));
	memcpy(header, "RHRCVR1", 8U);
	header[8] = (unsigned char)anchor->state;
	header[9] = anchor->components_completed;
	memcpy(header + 16U, census->census_hash, 32U);
	rh_hash_stream_init(&hash);
	if (rh_hash_stream_update(&hash, header, sizeof(header)))
		return -1;
	for (i = 0; i < RH_NAMESPACE_RECOVERY_ANCHOR_COMPONENTS; i++) {
		size_t bytes = strlen(names[i]);

		rh_put_u16le(length, (uint16_t)bytes);
		memset(record, 0, sizeof(record));
		if (i < anchor->components_completed) {
			const struct rh_namespace_recovery_anchor_component *component =
				&anchor->components[i];

			rh_put_u64le(record, component->parent.record);
			rh_put_u16le(record + 8U, component->parent.sequence);
			rh_put_u64le(record + 12U, component->child.record);
			rh_put_u16le(record + 20U, component->child.sequence);
			record[22] = component->name_namespace;
		}
		if (rh_hash_stream_update(&hash, length, sizeof(length)) ||
				rh_hash_stream_update(&hash, names[i], bytes) ||
				rh_hash_stream_update(&hash, record, sizeof(record)))
			return -1;
	}
	return rh_hash_stream_final(&hash, anchor->manifest_hash);
}

static int rh_hash_resolved_child(const struct rh_namespace_census *census,
		const char *name, int require_directory,
		struct rh_namespace_resolved_child *resolved)
{
	struct rh_hash_stream hash;
	unsigned char header[72], length[2];
	size_t bytes = strlen(name);

	memset(header, 0, sizeof(header));
	memcpy(header, "RHCHLD1", 8U);
	header[8] = (unsigned char)resolved->state;
	header[9] = (unsigned char)(require_directory + 1);
	header[10] = resolved->name_namespace;
	rh_put_u64le(header + 16U, resolved->parent.record);
	rh_put_u16le(header + 24U, resolved->parent.sequence);
	rh_put_u64le(header + 28U, resolved->child.record);
	rh_put_u16le(header + 36U, resolved->child.sequence);
	memcpy(header + 40U, census->census_hash, 32U);
	rh_put_u16le(length, (uint16_t)bytes);
	rh_hash_stream_init(&hash);
	if (rh_hash_stream_update(&hash, header, sizeof(header)) ||
			rh_hash_stream_update(&hash, length, sizeof(length)) ||
			rh_hash_stream_update(&hash, name, bytes))
		return -1;
	return rh_hash_stream_final(&hash, resolved->manifest_hash);
}

int rh_namespace_resolve_exact_child(
		const struct rh_raw_mft_census *raw,
		const struct rh_namespace_census *census,
		struct rh_raw_mft_ref parent, const char *exact_ascii_name,
		int require_directory,
		struct rh_namespace_resolved_child *resolved)
{
	uint16_t *upcase = NULL;
	unsigned char upcase_hash[32];
	const struct rh_namespace_link *match = NULL;
	u32 upcase_length;
	size_t bytes, collating = 0, matching_edges = 0, i;
	int result = -1;

	if (!raw || !census || !exact_ascii_name || !resolved ||
			(require_directory < -1 || require_directory > 1) ||
			!(bytes = strlen(exact_ascii_name)) || bytes > UINT8_MAX ||
			!census->graph_bounded || !census->graph_complete ||
			!census->i30_complete || !census->reciprocity_complete ||
			census->link_count != census->i30_edge_count ||
			(census->link_count && (!census->links || !census->i30_edges)) ||
			parent.record >= raw->slot_count ||
			raw->slots[parent.record].state != RH_RAW_SLOT_LIVE_BASE ||
			raw->slots[parent.record].sequence != parent.sequence ||
			!(raw->slots[parent.record].flags &
				le16_to_cpu(MFT_RECORD_IS_DIRECTORY))) {
		errno = EINVAL;
		return -1;
	}
	memset(resolved, 0, sizeof(*resolved));
	resolved->parent = parent;
	upcase_length = ntfs_upcase_build_default((ntfschar **)&upcase);
	if (!upcase || upcase_length != 65536U) {
		errno = EIO;
		goto out;
	}
	rh_sha256(upcase, (size_t)upcase_length * sizeof(*upcase), upcase_hash);
	if (memcmp(upcase_hash, census->upcase_hash, sizeof(upcase_hash))) {
		errno = EIO;
		goto out;
	}
	for (i = 0; i < census->link_count; i++) {
		const struct rh_namespace_link *link = &census->links[i];

		if (!rh_ref_equal(link->parent, parent) ||
				!rh_name_collates_ascii(census, link, exact_ascii_name, upcase))
			continue;
		collating++;
		match = link;
	}
	if (!collating) {
		resolved->state = RH_NAMESPACE_CHILD_ABSENT;
	} else if (collating != 1U || !rh_name_equal_ascii(census, match,
			exact_ascii_name) || match->owner.record >= raw->slot_count ||
			raw->slots[match->owner.record].state != RH_RAW_SLOT_LIVE_BASE ||
			raw->slots[match->owner.record].sequence != match->owner.sequence ||
			(require_directory >= 0 &&
			 !!(raw->slots[match->owner.record].flags &
				le16_to_cpu(MFT_RECORD_IS_DIRECTORY)) != require_directory)) {
		resolved->state = RH_NAMESPACE_CHILD_AMBIGUOUS;
	} else {
		for (i = 0; i < census->i30_edge_count; i++)
			if (!rh_link_edge_compare(census, match,
					&census->i30_edges[i]))
				matching_edges++;
		if (matching_edges != 1U) {
			resolved->state = RH_NAMESPACE_CHILD_AMBIGUOUS;
		} else {
			resolved->state = RH_NAMESPACE_CHILD_PRESENT;
			resolved->child = match->owner;
			resolved->name_namespace = match->name_namespace;
		}
	}
	if (rh_hash_resolved_child(census, exact_ascii_name, require_directory,
			resolved))
		goto out;
	result = 0;
out:
	free(upcase);
	return result;
}

int rh_namespace_resolve_recovery_anchor(
		const struct rh_raw_mft_census *raw,
		const struct rh_namespace_census *census,
		struct rh_namespace_recovery_anchor *anchor)
{
	static const char *const names[RH_NAMESPACE_RECOVERY_ANCHOR_COMPONENTS] = {
		"the one", "recovered files", "roothealth",
	};
	uint16_t *upcase = NULL;
	unsigned char upcase_hash[32];
	struct rh_raw_mft_ref current;
	u32 upcase_length;
	size_t component, i;
	int result = -1;

	if (!raw || !census || !anchor || !raw->slots || raw->slot_count <= 5U ||
			!census->graph_bounded || !census->graph_complete ||
			!census->i30_complete || !census->reciprocity_complete ||
			census->link_count != census->i30_edge_count ||
			(census->link_count && (!census->links || !census->i30_edges)) ||
			raw->slots[5].state != RH_RAW_SLOT_LIVE_BASE ||
			!raw->slots[5].sequence ||
			!(raw->slots[5].flags & le16_to_cpu(MFT_RECORD_IS_DIRECTORY))) {
		errno = EINVAL;
		return -1;
	}
	memset(anchor, 0, sizeof(*anchor));
	upcase_length = ntfs_upcase_build_default((ntfschar **)&upcase);
	if (!upcase || upcase_length != 65536U) {
		errno = EIO;
		goto out;
	}
	rh_sha256(upcase, (size_t)upcase_length * sizeof(*upcase), upcase_hash);
	if (memcmp(upcase_hash, census->upcase_hash, sizeof(upcase_hash))) {
		errno = EIO;
		goto out;
	}
	current.record = 5U;
	current.sequence = raw->slots[5].sequence;
	for (component = 0; component < RH_NAMESPACE_RECOVERY_ANCHOR_COMPONENTS;
			component++) {
		const struct rh_namespace_link *match = NULL;
		size_t collating = 0, matching_edges = 0;

		for (i = 0; i < census->link_count; i++) {
			const struct rh_namespace_link *link = &census->links[i];

			if (!rh_ref_equal(link->parent, current) ||
					!rh_name_collates_ascii(census, link, names[component],
						upcase))
				continue;
			collating++;
			match = link;
		}
		if (!collating) {
			anchor->state = RH_NAMESPACE_RECOVERY_ANCHOR_ABSENT;
			break;
		}
		if (collating != 1U || !rh_name_equal_ascii(census, match,
				names[component]) || match->owner.record >= raw->slot_count ||
				raw->slots[match->owner.record].state != RH_RAW_SLOT_LIVE_BASE ||
				raw->slots[match->owner.record].sequence !=
					match->owner.sequence ||
				!(raw->slots[match->owner.record].flags &
					le16_to_cpu(MFT_RECORD_IS_DIRECTORY))) {
			anchor->state = RH_NAMESPACE_RECOVERY_ANCHOR_AMBIGUOUS;
			break;
		}
		for (i = 0; i < census->i30_edge_count; i++)
			if (!rh_link_edge_compare(census, match,
					&census->i30_edges[i]))
				matching_edges++;
		if (matching_edges != 1U) {
			anchor->state = RH_NAMESPACE_RECOVERY_ANCHOR_AMBIGUOUS;
			break;
		}
		anchor->components[component].parent = current;
		anchor->components[component].child = match->owner;
		anchor->components[component].name_namespace = match->name_namespace;
		anchor->components_completed++;
		current = match->owner;
	}
	if (anchor->components_completed == RH_NAMESPACE_RECOVERY_ANCHOR_COMPONENTS)
		anchor->state = RH_NAMESPACE_RECOVERY_ANCHOR_PRESENT;
	else if (anchor->state == RH_NAMESPACE_RECOVERY_ANCHOR_UNKNOWN)
		anchor->state = RH_NAMESPACE_RECOVERY_ANCHOR_ABSENT;
	if (rh_hash_recovery_anchor(census, anchor))
		goto out;
	result = 0;
out:
	free(upcase);
	return result;
}

static const char *const rh_t1os_required_paths[] = {
	"the one/software/python/bin/python",
	"the one/build/GODDESS/GODDESS.py",
	"the one/build/drivers/driverserver.py",
	"the one/drivers/tools/modprobe",
	"the one/drivers/settings/policy.json",
	"the one/drivers/modules/module-manifest.sha256",
};

static const char *const rh_t1os_forbidden_root_names[] = {
	"bin", "dev", "etc", "home", "lib", "lib64", "media", "mnt",
	"opt", "proc", "root", "run", "sbin", "srv", "sys", "tmp",
	"usr", "var",
};

size_t rh_namespace_forbidden_root_name_count(void)
{
	return sizeof(rh_t1os_forbidden_root_names) /
		sizeof(rh_t1os_forbidden_root_names[0]);
}

const char *rh_namespace_forbidden_root_name(size_t index)
{
	if (index >= rh_namespace_forbidden_root_name_count())
		return NULL;
	return rh_t1os_forbidden_root_names[index];
}

static int rh_hash_identity(struct rh_namespace_census *census)
{
	struct rh_hash_stream set, identity, combined;
	unsigned char record[160], length[4], prior_hash[32];
	size_t i;

	rh_hash_stream_init(&set);
	memset(record, 0, 16U);
	memcpy(record, "RHFBN1\0\0", 8U);
	rh_put_u64le(record + 8, census->forbidden_root_names_expected);
	if (rh_hash_stream_update(&set, record, 16U))
		return -1;
	for (i = 0; i < rh_namespace_forbidden_root_name_count(); i++) {
		size_t bytes = strlen(rh_t1os_forbidden_root_names[i]);

		rh_put_u32le(length, (uint32_t)bytes);
		if (rh_hash_stream_update(&set, length, sizeof(length)) ||
				rh_hash_stream_update(&set,
					rh_t1os_forbidden_root_names[i], bytes))
			return -1;
	}
	if (rh_hash_stream_final(&set, census->forbidden_root_set_hash))
		return -1;

	rh_hash_stream_init(&identity);
	memset(record, 0, sizeof(record));
	memcpy(record, "RHNSI1\0\0", 8U);
	rh_put_u64le(record + 8, census->identity_required_expected);
	rh_put_u64le(record + 16, census->identity_required_completed);
	rh_put_u64le(record + 24, census->forbidden_root_names_expected);
	rh_put_u64le(record + 32, census->forbidden_root_children_examined);
	rh_put_u64le(record + 40, census->forbidden_root_children_matched);
	record[48] = census->identity_checked;
	record[49] = (unsigned char)census->identity;
	memcpy(record + 56, census->upcase_hash, 32U);
	memcpy(record + 88, census->graph_hash, 32U);
	memcpy(record + 120, census->forbidden_root_set_hash, 32U);
	if (rh_hash_stream_update(&identity, record, sizeof(record)))
		return -1;
	for (i = 0; i < sizeof(rh_t1os_required_paths) /
			sizeof(rh_t1os_required_paths[0]); i++) {
		size_t bytes = strlen(rh_t1os_required_paths[i]);

		rh_put_u32le(length, (uint32_t)bytes);
		if (rh_hash_stream_update(&identity, length, sizeof(length)) ||
				rh_hash_stream_update(&identity,
					rh_t1os_required_paths[i], bytes))
			return -1;
	}
	if (rh_hash_stream_final(&identity, census->identity_hash))
		return -1;

	memcpy(prior_hash, census->census_hash, sizeof(prior_hash));
	memset(record, 0, 80U);
	memcpy(record, "RHNSC3\0\0", 8U);
	memcpy(record + 8, prior_hash, 32U);
	memcpy(record + 40, census->identity_hash, 32U);
	rh_hash_stream_init(&combined);
	if (rh_hash_stream_update(&combined, record, 80U))
		return -1;
	return rh_hash_stream_final(&combined, census->census_hash);
}

int rh_namespace_check_t1os_identity(const struct rh_raw_mft_census *raw,
		struct rh_namespace_census *census)
{
	uint16_t *upcase = NULL;
	unsigned char upcase_hash[32];
	struct rh_raw_mft_ref root;
	u32 upcase_length;
	size_t i, j;
	int ambiguous, missing = 0;

	if (!raw || !census || !census->graph_bounded ||
			census->identity_checked) {
		errno = EINVAL;
		return -1;
	}
	upcase_length = ntfs_upcase_build_default((ntfschar **)&upcase);
	if (!upcase || upcase_length != 65536U) {
		free(upcase);
		errno = EIO;
		return -1;
	}
	rh_sha256(upcase, (size_t)upcase_length * sizeof(*upcase), upcase_hash);
	if (memcmp(upcase_hash, census->upcase_hash, sizeof(upcase_hash))) {
		free(upcase);
		errno = EIO;
		return -1;
	}
	census->identity_checked = 1;
	census->identity_required_expected = sizeof(rh_t1os_required_paths) /
		sizeof(rh_t1os_required_paths[0]);
	census->forbidden_root_names_expected =
		rh_namespace_forbidden_root_name_count();
	ambiguous = !census->graph_complete;
	for (i = 0; i < census->identity_required_expected; i++) {
		int status = rh_find_path(raw, census, rh_t1os_required_paths[i],
			upcase);

		if (status < 0)
			ambiguous = 1;
		else if (!status)
			missing = 1;
		else
			census->identity_required_completed++;
	}
	root.record = 5U;
	root.sequence = raw->slot_count > 5U ? raw->slots[5].sequence : 0U;
	for (i = 0; i < census->link_count; i++) {
		const struct rh_namespace_link *link = &census->links[i];
		int forbidden = 0;

		if (!rh_ref_equal(link->parent, root))
			continue;
		census->forbidden_root_children_examined++;
		for (j = 0; j < rh_namespace_forbidden_root_name_count(); j++)
			if (rh_name_collates_ascii(census, link,
					rh_t1os_forbidden_root_names[j], upcase)) {
				forbidden = 1;
				break;
			}
		if (forbidden) {
			census->forbidden_root_children_matched++;
			missing = 1;
		}
	}
	census->identity = ambiguous ? RH_T1OS_IDENTITY_AMBIGUOUS :
		missing ? RH_T1OS_IDENTITY_MISSING : RH_T1OS_IDENTITY_MATCH;
	free(upcase);
	return rh_hash_identity(census);
}

int rh_namespace_raw_link_record_referenced(
		const struct rh_namespace_census *census,
		uint64_t record, int *referenced)
{
	size_t i;

	if (!census || !referenced || !census->graph_bounded) {
		errno = EINVAL;
		return -1;
	}
	*referenced = 0;
	for (i = 0; i < census->link_count; i++)
		if (census->links[i].owner.record == record ||
				census->links[i].parent.record == record ||
				census->links[i].storage.record == record) {
			*referenced = 1;
			break;
		}
	return 0;
}

int rh_namespace_complete_record_referenced(
		const struct rh_namespace_census *census,
		uint64_t record, int *referenced)
{
	size_t i;

	if (!census || !referenced || !census->graph_bounded ||
			!census->i30_complete || !census->reciprocity_complete) {
		errno = EINVAL;
		return -1;
	}
	if (rh_namespace_raw_link_record_referenced(census, record, referenced) ||
			*referenced)
		return 0;
	for (i = 0; i < census->i30_edge_count; i++)
		if (census->i30_edges[i].child.record == record ||
				census->i30_edges[i].parent.record == record) {
			*referenced = 1;
			break;
		}
	return 0;
}

void rh_namespace_census_release(struct rh_namespace_census *census)
{
	if (!census)
		return;
	free(census->links);
	free(census->i30_edges);
	free(census->name_arena);
	free(census->file_name_value_arena);
	free(census->i30_name_arena);
	free(census->i30_value_arena);
	memset(census, 0, sizeof(*census));
}
