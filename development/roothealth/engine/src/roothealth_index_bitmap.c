/* ROOTHEALTH_REPAIR_ROLE(DIAGNOSTIC) ROOTHEALTH_IO_ROLE(PLANNER) */
#include "config.h"

#include <errno.h>
#include <limits.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include "attrib.h"
#include "collate.h"
#include "dir.h"
#include "endians.h"
#include "index.h"
#include "inode.h"
#include "layout.h"
#include "mst.h"
#include "roothealth_hash_stream.h"
#include "roothealth_census_device.h"
#include "roothealth_index_bitmap.h"
#include "roothealth_policy_internal.h"
#include "roothealth_raw_mft.h"
#include "unistr.h"

struct rh_bytes {
	struct rh_hash_stream hash;
	int initialized;
};

struct rh_index_walk {
	ntfs_volume *volume;
	ntfs_attr *allocation;
	struct rh_writer *writer;
	const struct rh_census_reader *reader;
	const struct rh_raw_mft_census *raw;
	struct rh_raw_mft_ref allocation_owner;
	uint64_t owner;
	uint16_t owner_sequence;
	uint64_t block_count;
	unsigned char *visited;
	const ntfschar *canonical_upcase;
	u32 canonical_upcase_length;
	rh_i30_edge_callback edge_callback;
	void *edge_opaque;
	struct rh_bytes *tree_bytes;
	struct rh_index_bitmap_census *census;
};

/*
 * An explicit stack makes tree depth a property of the validated allocation,
 * not an implementation validity limit.  Allocation failure is a resource
 * error; a repeated/out-of-range VCN remains structural corruption.
 */
struct rh_index_walk_frame {
	INDEX_BLOCK *owned_block;
	const unsigned char *cursor;
	const unsigned char *header_end;
	union {
		uint64_t alignment;
		unsigned char bytes[offsetof(FILE_NAME_ATTR, file_name) + 510U];
	} previous_key;
	uint16_t previous_key_length;
	uint8_t child_visited;
	uint8_t from_index_block;
	int64_t block_vcn;
};

static int rh_bytes_append(struct rh_bytes *bytes, const void *data,
		size_t length)
{
	if (!bytes || (!data && length)) {
		errno = EINVAL;
		return -1;
	}
	if (!bytes->initialized) {
		rh_hash_stream_init(&bytes->hash);
		bytes->initialized = 1;
	}
	return rh_hash_stream_update(&bytes->hash, data, length);
}

static int rh_bytes_u16(struct rh_bytes *bytes, uint16_t value)
{
	unsigned char encoded[2] = {
		(unsigned char)value, (unsigned char)(value >> 8)
	};
	return rh_bytes_append(bytes, encoded, sizeof(encoded));
}

static int rh_bytes_u64(struct rh_bytes *bytes, uint64_t value)
{
	unsigned char encoded[8];
	unsigned int i;

	for (i = 0; i < 8U; i++)
		encoded[i] = (unsigned char)(value >> (8U * i));
	return rh_bytes_append(bytes, encoded, sizeof(encoded));
}

static int rh_bytes_final(struct rh_bytes *bytes, unsigned char digest[32])
{
	if (!bytes || !digest) {
		errno = EINVAL;
		return -1;
	}
	if (!bytes->initialized) {
		rh_hash_stream_init(&bytes->hash);
		bytes->initialized = 1;
	}
	return rh_hash_stream_final(&bytes->hash, digest);
}

static int rh_all_zero(const unsigned char *bytes, size_t length)
{
	size_t i;

	for (i = 0; i < length; i++)
		if (bytes[i])
			return 0;
	return 1;
}

static int rh_bitmap_get(const unsigned char *bitmap, uint64_t bit)
{
	return !!(bitmap[bit >> 3] & (unsigned char)(1U << (bit & 7U)));
}

static void rh_bitmap_set(unsigned char *bitmap, uint64_t bit)
{
	bitmap[bit >> 3] |= (unsigned char)(1U << (bit & 7U));
}

static int rh_bitmap_bytes_for_bits(uint64_t bit_count, size_t *byte_count)
{
	uint64_t bytes;

	if (!bit_count || !byte_count) {
		errno = EINVAL;
		return -1;
	}
	bytes = bit_count / 8U + !!(bit_count % 8U);
	if (bytes > SIZE_MAX) {
		errno = EOVERFLOW;
		return -1;
	}
	*byte_count = (size_t)bytes;
	return 0;
}

int rh_index_bitmap_slot_count_from_initialized(uint64_t initialized_size,
		uint32_t mft_record_size, uint64_t *slot_count)
{
	uint64_t count;

	if (!initialized_size || !mft_record_size || !slot_count ||
			initialized_size % mft_record_size) {
		errno = EINVAL;
		return -1;
	}
	count = initialized_size / mft_record_size;
	if (!count) {
		errno = EINVAL;
		return -1;
	}
	*slot_count = count;
	return 0;
}

static int rh_name_i30(const ATTR_RECORD *attribute, uint32_t length,
		uint32_t minimum)
{
	static const uint16_t i30[] = { '$', 'I', '3', '0' };
	uint16_t offset = le16_to_cpu(attribute->name_offset);
	const le16 *name;
	size_t i;

	if (attribute->name_length != 4U || offset < minimum || offset > length ||
		8U > length - offset)
		return 0;
	name = (const le16 *)((const unsigned char *)attribute + offset);
	for (i = 0; i < sizeof(i30) / sizeof(i30[0]); i++)
		if (le16_to_cpu(name[i]) != i30[i])
			return 0;
	return 1;
}

static const unsigned char rh_i30_utf16le[] = {
	'$', 0, 'I', 0, '3', 0, '0', 0
};

static int rh_raw_name_i30(const struct rh_raw_mft_census *raw,
		const struct rh_raw_attribute *attribute)
{
	return raw && attribute && attribute->name_length == 4U &&
		attribute->name_offset <= raw->name_arena_size &&
		sizeof(rh_i30_utf16le) <= raw->name_arena_size -
			attribute->name_offset &&
		!memcmp(raw->name_arena + attribute->name_offset,
			rh_i30_utf16le, sizeof(rh_i30_utf16le));
}

static int rh_raw_owned_i30(const struct rh_raw_mft_census *raw,
		const struct rh_raw_attribute *attribute,
		struct rh_raw_mft_ref owner, uint32_t type)
{
	return attribute->owner.record == owner.record &&
		attribute->owner.sequence == owner.sequence &&
		attribute->type == type && rh_raw_name_i30(raw, attribute);
}

static int rh_mft_physical(ntfs_volume *volume, uint64_t record,
		uint64_t *physical)
{
	uint64_t logical, vcn, within, delta;
	runlist_element *run;

	if (!volume || !volume->mft_na || !physical ||
		record > UINT64_MAX / volume->mft_record_size)
		return -1;
	logical = record * volume->mft_record_size;
	vcn = logical >> volume->cluster_size_bits;
	within = logical & (volume->cluster_size - 1U);
	if (vcn > INT64_MAX)
		return -1;
	run = ntfs_attr_find_vcn(volume->mft_na, (int64_t)vcn);
	if (!run || run->lcn < 0 || run->vcn < 0 || run->length <= 0 ||
		vcn < (uint64_t)run->vcn ||
		vcn >= (uint64_t)run->vcn + (uint64_t)run->length ||
		within + volume->mft_record_size > volume->cluster_size)
		return -1;
	delta = vcn - (uint64_t)run->vcn;
	if ((uint64_t)run->lcn > UINT64_MAX - delta ||
		(uint64_t)run->lcn + delta >
			UINT64_MAX / volume->cluster_size)
		return -1;
	*physical = ((uint64_t)run->lcn + delta) * volume->cluster_size + within;
	return 0;
}

static int rh_nonresident_physical(ntfs_volume *volume, ntfs_attr *attribute,
		uint64_t logical, uint64_t *physical, int64_t *logical_vcn,
		int64_t *lcn)
{
	uint64_t vcn = logical >> volume->cluster_size_bits;
	uint64_t within = logical & (volume->cluster_size - 1U);
	uint64_t delta;
	runlist_element *run;

	if (vcn > INT64_MAX)
		return -1;
	run = ntfs_attr_find_vcn(attribute, (int64_t)vcn);
	if (!run || run->lcn < 0 || run->vcn < 0 || run->length <= 0 ||
		vcn < (uint64_t)run->vcn ||
		vcn >= (uint64_t)run->vcn + (uint64_t)run->length)
		return -1;
	delta = vcn - (uint64_t)run->vcn;
	if ((uint64_t)run->lcn > UINT64_MAX - delta ||
		(uint64_t)run->lcn + delta > UINT64_MAX / volume->cluster_size)
		return -1;
	*logical_vcn = (int64_t)vcn;
	*lcn = run->lcn + (int64_t)delta;
	*physical = (uint64_t)*lcn * volume->cluster_size + within;
	return 0;
}

static int rh_entry_key_valid(struct rh_index_walk *walk,
		const INDEX_ENTRY *entry, uint16_t key_length)
{
	const FILE_NAME_ATTR *name;
	uint64_t indexed, parent, indexed_record, slot_count;
	uint32_t expected_length;

	if (key_length < sizeof(FILE_NAME_ATTR)) {
		walk->census->failure_stage = 231U;
		return 0;
	}
	name = &entry->key.file_name;
	expected_length = sizeof(*name) + 2U * name->file_name_length;
	indexed = le64_to_cpu(entry->indexed_file);
	parent = le64_to_cpu(name->parent_directory);
	indexed_record = MREF(indexed);
	slot_count = walk->raw ? walk->raw->slot_count :
		(uint64_t)walk->volume->mft_na->initialized_size /
		walk->volume->mft_record_size;
	if (key_length != expected_length) {
		walk->census->failure_stage = 232U;
		return 0;
	}
	if (!MSEQNO(indexed) || indexed_record >= slot_count) {
		walk->census->failure_stage = 233U;
		return 0;
	}
	if (MREF(parent) != walk->owner ||
			MSEQNO(parent) != walk->owner_sequence) {
		walk->census->failure_stage = 234U;
		return 0;
	}
	if (name->file_name_type > FILE_NAME_WIN32_AND_DOS) {
		walk->census->failure_stage = 235U;
		return 0;
	}
	return 1;
}

static int rh_walk_entries(struct rh_index_walk *walk,
		const INDEX_HEADER *header, const unsigned char *header_end);

static int rh_canonical_file_name_compare(const struct rh_index_walk *walk,
		const FILE_NAME_ATTR *first, const FILE_NAME_ATTR *second)
{
	ntfschar first_name[255], second_name[255];

	memcpy(first_name, (const unsigned char *)first +
		offsetof(FILE_NAME_ATTR, file_name),
		(size_t)first->file_name_length * sizeof(*first_name));
	memcpy(second_name, (const unsigned char *)second +
		offsetof(FILE_NAME_ATTR, file_name),
		(size_t)second->file_name_length * sizeof(*second_name));
	return ntfs_names_full_collate(first_name, first->file_name_length,
		second_name, second->file_name_length, CASE_SENSITIVE,
		walk->canonical_upcase, walk->canonical_upcase_length);
}

static int rh_read_index_block(struct rh_index_walk *walk, int64_t vcn,
		INDEX_BLOCK *block)
{
	if (!walk->raw)
		return ntfs_attr_mst_pread(walk->allocation,
			vcn * (int64_t)walk->volume->cluster_size, 1,
			walk->volume->indx_record_size, block) == 1 ? 0 : -1;
	if (!walk->reader || vcn < 0 ||
		(uint64_t)vcn > UINT64_MAX / walk->volume->cluster_size ||
		rh_raw_mft_stream_pread_reader(walk->reader, walk->raw,
			walk->allocation_owner, le32_to_cpu(AT_INDEX_ALLOCATION),
			rh_i30_utf16le, 4U,
			(uint64_t)vcn * walk->volume->cluster_size,
			walk->volume->indx_record_size, (unsigned char *)block) ||
		ntfs_mst_post_read_fixup((NTFS_RECORD *)block,
			walk->volume->indx_record_size))
		return -1;
	return 0;
}

static int rh_walk_frame_push(struct rh_index_walk *walk,
		struct rh_index_walk_frame **frames, size_t *frame_count,
		size_t *frame_capacity, const INDEX_HEADER *header,
		const unsigned char *header_end, INDEX_BLOCK *owned_block,
		uint8_t from_index_block, int64_t block_vcn)
{
	struct rh_index_walk_frame *grown, *frame;
	uint32_t entries_offset;
	size_t capacity, maximum;

	if (!walk || !frames || !frame_count || !frame_capacity || !header ||
		!header_end || (const unsigned char *)header >= header_end) {
		errno = EINVAL;
		return -1;
	}
	entries_offset = le32_to_cpu(header->entries_offset);
	if (entries_offset < sizeof(*header) || (entries_offset & 7U) ||
		(const unsigned char *)header + entries_offset >= header_end) {
		walk->census->failure_stage = 221U;
		errno = EIO;
		return -1;
	}
	maximum = walk->block_count < (uint64_t)SIZE_MAX ?
		(size_t)walk->block_count + 1U : SIZE_MAX;
	if (*frame_count >= maximum) {
		walk->census->failure_stage = 218U;
		errno = ELOOP;
		return -1;
	}
	if (*frame_count == *frame_capacity) {
		capacity = *frame_capacity ? *frame_capacity : 8U;
		if (capacity > SIZE_MAX / 2U)
			capacity = *frame_count + 1U;
		else
			capacity *= 2U;
		if (capacity > maximum)
			capacity = maximum;
		if (capacity <= *frame_count ||
				capacity > SIZE_MAX / sizeof(**frames)) {
			errno = EOVERFLOW;
			return -1;
		}
		grown = realloc(*frames, capacity * sizeof(**frames));
		if (!grown)
			return -1;
		*frames = grown;
		*frame_capacity = capacity;
	}
	frame = &(*frames)[(*frame_count)++];
	memset(frame, 0, sizeof(*frame));
	frame->owned_block = owned_block;
	frame->cursor = (const unsigned char *)header + entries_offset;
	frame->header_end = header_end;
	frame->from_index_block = from_index_block;
	frame->block_vcn = block_vcn;
	return 0;
}

#ifdef ROOTHEALTH_INDEX_BITMAP_TEST_HOOKS
int rh_index_bitmap_test_iterative_frames(uint64_t block_count,
		size_t requested_frames)
{
	struct rh_index_walk walk;
	struct rh_index_bitmap_census census;
	struct rh_index_walk_frame *frames = NULL;
	struct {
		INDEX_HEADER header;
		INDEX_ENTRY_HEADER entry;
	} node;
	size_t frame_count = 0, frame_capacity = 0, i;
	int result = -1;

	if (!requested_frames) {
		errno = EINVAL;
		return -1;
	}
	memset(&walk, 0, sizeof(walk));
	memset(&census, 0, sizeof(census));
	memset(&node, 0, sizeof(node));
	node.header.entries_offset = cpu_to_le32(sizeof(node.header));
	walk.block_count = block_count;
	walk.census = &census;
	for (i = 0; i < requested_frames; i++)
		if (rh_walk_frame_push(&walk, &frames, &frame_count,
				&frame_capacity, &node.header,
				(const unsigned char *)&node + sizeof(node), NULL,
				i != 0, i ? (int64_t)(i - 1U) : -1))
			goto out;
	result = 0;
out:
	free(frames);
	return result;
}
#endif

static int rh_walk_load_child(struct rh_index_walk *walk, int64_t vcn,
		INDEX_BLOCK **block_out, const unsigned char **header_end_out)
{
	INDEX_BLOCK *block;
	uint64_t ordinal;
	uint32_t entries_offset, index_length, allocated;
	unsigned char tag[16];

	if (!walk || !block_out || !header_end_out || vcn < 0 ||
			(uint64_t)vcn >= walk->block_count) {
		if (walk)
			walk->census->failure_stage = 211U;
		errno = EIO;
		return -1;
	}
	ordinal = (uint64_t)vcn;
	if (rh_bitmap_get(walk->visited, ordinal)) {
		walk->census->failure_stage = 212U;
		errno = ELOOP;
		return -1;
	}
	rh_bitmap_set(walk->visited, ordinal);
	walk->census->child_vcns_examined++;
	walk->census->index_blocks_reachable++;
	block = malloc(walk->volume->indx_record_size);
	if (!block) {
		walk->census->failure_stage = 213U;
		return -1;
	}
	if (rh_read_index_block(walk, vcn, block)) {
		walk->census->failure_stage = 214U;
		goto error;
	}
	if (block->magic != magic_INDX ||
		le16_to_cpu(block->usa_ofs) != sizeof(INDEX_BLOCK) ||
		le16_to_cpu(block->usa_count) !=
			walk->volume->indx_record_size /
			walk->volume->sector_size + 1U ||
		sle64_to_cpu(block->index_block_vcn) != vcn ||
		block->index.ih_flags & (uint8_t)~NODE_MASK ||
		!rh_all_zero(block->index.reserved,
			sizeof(block->index.reserved))) {
		walk->census->failure_stage = 215U;
		goto error;
	}
	entries_offset = le32_to_cpu(block->index.entries_offset);
	index_length = le32_to_cpu(block->index.index_length);
	allocated = le32_to_cpu(block->index.allocated_size);
	if (entries_offset < sizeof(INDEX_HEADER) || (entries_offset & 7U) ||
		index_length < entries_offset + sizeof(INDEX_ENTRY_HEADER) ||
		(index_length & 7U) ||
		allocated != walk->volume->indx_record_size -
			offsetof(INDEX_BLOCK, index) ||
		index_length > allocated ||
		offsetof(INDEX_BLOCK, index) + index_length >
			walk->volume->indx_record_size) {
		walk->census->failure_stage = 216U;
		goto error;
	}
	memset(tag, 0, sizeof(tag));
	memcpy(tag, "I30BLOCK", 8);
	if (rh_bytes_append(walk->tree_bytes, tag, sizeof(tag)) ||
		rh_bytes_u64(walk->tree_bytes, walk->owner) ||
		rh_bytes_u64(walk->tree_bytes, (uint64_t)vcn) ||
		rh_bytes_append(walk->tree_bytes, block,
			walk->volume->indx_record_size)) {
		walk->census->failure_stage = 217U;
		goto error;
	}
	walk->census->index_blocks_examined++;
	*block_out = block;
	*header_end_out = (const unsigned char *)&block->index + index_length;
	return 0;
error:
	free(block);
	return -1;
}

static int rh_walk_entries(struct rh_index_walk *walk,
		const INDEX_HEADER *header, const unsigned char *header_end)
{
	struct rh_index_walk_frame *frames = NULL;
	size_t frame_count = 0, frame_capacity = 0;
	int result = -1;

	if (rh_walk_frame_push(walk, &frames, &frame_count, &frame_capacity,
			header, header_end, NULL, 0, -1))
		goto out;
	while (frame_count) {
		struct rh_index_walk_frame *frame = &frames[frame_count - 1U];
		const unsigned char *cursor = frame->cursor;
		const INDEX_ENTRY *entry;
		uint16_t length, key_length, flags;
		const unsigned char *key_end, *payload_end;

		if (cursor >= frame->header_end ||
				(size_t)(frame->header_end - cursor) <
				sizeof(INDEX_ENTRY_HEADER)) {
			walk->census->failure_stage = 222U;
			errno = EIO;
			goto out;
		}
		entry = (const INDEX_ENTRY *)cursor;
		length = le16_to_cpu(entry->length);
		key_length = le16_to_cpu(entry->key_length);
		flags = le16_to_cpu(entry->ie_flags);
		if (length < sizeof(INDEX_ENTRY_HEADER) || (length & 7U) ||
			length > (size_t)(frame->header_end - cursor) ||
			(flags & ~(le16_to_cpu(INDEX_ENTRY_NODE) |
			 le16_to_cpu(INDEX_ENTRY_END))) || entry->reserved) {
			walk->census->failure_stage = 223U;
			errno = EIO;
			goto out;
		}
		key_end = cursor + sizeof(INDEX_ENTRY_HEADER) + key_length;
		payload_end = cursor + length -
			((flags & le16_to_cpu(INDEX_ENTRY_NODE)) ? sizeof(leVCN) : 0U);
		/* Entry alignment padding is not required to be initialized on NTFS. */
		if (key_end > payload_end || payload_end - key_end >= 8) {
			walk->census->failure_stage = 224U;
			errno = EIO;
			goto out;
		}
		if ((flags & le16_to_cpu(INDEX_ENTRY_NODE)) &&
				!frame->child_visited) {
			sle64 encoded_child;
			int64_t child;
			INDEX_BLOCK *child_block = NULL;
			const unsigned char *child_end = NULL;

			memcpy(&encoded_child, payload_end, sizeof(encoded_child));
			child = sle64_to_cpu(encoded_child);
			frame->child_visited = 1;
			if (rh_walk_load_child(walk, child, &child_block, &child_end))
				goto out;
			if (rh_walk_frame_push(walk, &frames, &frame_count,
					&frame_capacity, &child_block->index, child_end,
					child_block, 1, child)) {
				free(child_block);
				goto out;
			}
			continue;
		}
		if (flags & le16_to_cpu(INDEX_ENTRY_END)) {
			if (key_length || le64_to_cpu(entry->indexed_file) ||
				cursor + length != frame->header_end) {
				walk->census->failure_stage = 225U;
				errno = EIO;
				goto out;
			}
		} else {
			const FILE_NAME_ATTR *current_name = &entry->key.file_name;

			if (!key_length || !rh_entry_key_valid(walk, entry, key_length)) {
				if (walk->census->failure_stage < 230U)
					walk->census->failure_stage = 226U;
				errno = EIO;
				goto out;
			}
			if (frame->previous_key_length) {
				const FILE_NAME_ATTR *previous_name =
					(const FILE_NAME_ATTR *)frame->previous_key.bytes;
				int comparison = rh_canonical_file_name_compare(walk,
					previous_name, current_name);
				if (comparison >= 0) {
					walk->census->failure_stage = 227U;
					errno = EIO;
					goto out;
				}
			}
			if (walk->edge_callback) {
				struct rh_i30_edge_view edge;
				uint64_t indexed = le64_to_cpu(entry->indexed_file);

				memset(&edge, 0, sizeof(edge));
				edge.parent_mft_record = walk->owner;
				edge.parent_sequence = walk->owner_sequence;
				edge.child_mft_record = MREF(indexed);
				edge.child_sequence = MSEQNO(indexed);
				edge.indexed_file_reference = indexed;
				edge.entry_length = length;
				edge.key_length = key_length;
				edge.entry_flags = flags;
				edge.name_namespace = current_name->file_name_type;
				edge.name_length = current_name->file_name_length;
				edge.name_utf16le =
					(const unsigned char *)&current_name->file_name;
				edge.file_name_value =
					(const unsigned char *)current_name;
				edge.from_index_block = frame->from_index_block;
				edge.block_vcn = frame->from_index_block ?
					frame->block_vcn : -1;
				if (walk->edge_callback(&edge, walk->edge_opaque)) {
					walk->census->failure_stage = 229U;
					goto out;
				}
			}
			memcpy(frame->previous_key.bytes, &entry->key, key_length);
			frame->previous_key_length = key_length;
			walk->census->index_entries_examined++;
		}
		frame->cursor = cursor + length;
		frame->child_visited = 0;
		if (flags & le16_to_cpu(INDEX_ENTRY_END)) {
			free(frame->owned_block);
			frame->owned_block = NULL;
			frame_count--;
		}
	}
	result = 0;
out:
	while (frame_count) {
		free(frames[frame_count - 1U].owned_block);
		frame_count--;
	}
	free(frames);
	return result;
}

static int rh_add_change(struct rh_index_bitmap_census *census,
		const struct rh_index_bitmap_change *change)
{
	struct rh_index_bitmap_change *grown;
	size_t capacity;

	if (!census || !change || census->change_count == SIZE_MAX) {
		errno = EOVERFLOW;
		return -1;
	}
	if (census->change_count == census->change_capacity) {
		capacity = census->change_capacity ? census->change_capacity : 64U;
		if (capacity > SIZE_MAX / 2U)
			capacity = census->change_count + 1U;
		else
			capacity *= 2U;
		if (capacity < census->change_count + 1U ||
				capacity > SIZE_MAX / sizeof(*grown)) {
			errno = EOVERFLOW;
			return -1;
		}
		grown = realloc(census->changes, capacity * sizeof(*grown));
		if (!grown)
			return -1;
		census->changes = grown;
		census->change_capacity = capacity;
	}
	census->changes[census->change_count++] = *change;
	return 0;
}

static int rh_scan_large_index(ntfs_volume *volume, struct rh_writer *writer,
		uint64_t owner, uint16_t sequence, const unsigned char *record,
		const ATTR_RECORD *root_attr, const ATTR_RECORD *allocation_attr,
		const ATTR_RECORD *bitmap_attr, struct rh_bytes *tree_bytes,
		struct rh_bytes *expected_bytes,
		struct rh_index_bitmap_census *census,
		const ntfschar *canonical_upcase, u32 canonical_upcase_length,
		rh_i30_edge_callback edge_callback, void *edge_opaque)
{
	const INDEX_ROOT *root;
	ntfs_inode *inode = NULL;
	ntfs_attr *allocation = NULL, *bitmap = NULL;
	unsigned char *observed = NULL, *expected = NULL, *visited = NULL;
	uint32_t root_value_length, root_value_offset, root_payload;
	uint32_t root_index_length;
	uint64_t block_count, bitmap_bytes, mft_physical = 0;
	uint64_t reachable_before;
	struct rh_index_walk walk;
	size_t i, visited_bytes;
	int result = -1;

	memset(&walk, 0, sizeof(walk));
	census->failure_stage = 101U;
	root_value_length = le32_to_cpu(root_attr->value_length);
	root_value_offset = le16_to_cpu(root_attr->value_offset);
	if (root_value_offset > le32_to_cpu(root_attr->length) ||
		root_value_length > le32_to_cpu(root_attr->length) - root_value_offset ||
		root_value_length < sizeof(INDEX_ROOT) + sizeof(INDEX_ENTRY_HEADER))
		return -1;
	root = (const INDEX_ROOT *)((const unsigned char *)root_attr +
		root_value_offset);
	root_payload = root_value_length - offsetof(INDEX_ROOT, index);
	root_index_length = le32_to_cpu(root->index.index_length);
	if (root->type != AT_FILE_NAME ||
		root->collation_rule != COLLATION_FILE_NAME ||
		le32_to_cpu(root->index_block_size) != volume->indx_record_size ||
		root->clusters_per_index_block != 1 ||
		!rh_all_zero(root->reserved, sizeof(root->reserved)) ||
		root->index.ih_flags != LARGE_INDEX ||
		!rh_all_zero(root->index.reserved, sizeof(root->index.reserved)) ||
		le32_to_cpu(root->index.entries_offset) != sizeof(INDEX_HEADER) ||
		root_index_length != le32_to_cpu(root->index.allocated_size) ||
		root_index_length != root_payload ||
		root_index_length < sizeof(INDEX_HEADER) + sizeof(INDEX_ENTRY_HEADER))
		return -1;
	census->failure_stage = 102U;
	inode = ntfs_inode_open(volume, owner);
	if (!inode)
		goto out;
	census->failure_stage = 103U;
	allocation = ntfs_attr_open(inode, AT_INDEX_ALLOCATION,
		NTFS_INDEX_I30, 4U);
	if (!allocation || !NAttrNonResident(allocation) ||
		allocation->data_size <= 0 ||
		allocation->data_size != allocation->initialized_size ||
		allocation->data_size % volume->indx_record_size)
		goto out;
	block_count = (uint64_t)allocation->data_size / volume->indx_record_size;
	if (!block_count || rh_bitmap_bytes_for_bits(block_count, &visited_bytes))
		goto out;
	census->failure_stage = 104U;
	if (bitmap_attr->non_resident) {
		bitmap = ntfs_attr_open(inode, AT_BITMAP, NTFS_INDEX_I30, 4U);
		if (!bitmap || !NAttrNonResident(bitmap) || bitmap->data_size <= 0 ||
			bitmap->data_size != bitmap->initialized_size)
			goto out;
		bitmap_bytes = (uint64_t)bitmap->data_size;
	} else {
		uint32_t value_offset = le16_to_cpu(bitmap_attr->value_offset);
		uint32_t value_length = le32_to_cpu(bitmap_attr->value_length);
		uint32_t length = le32_to_cpu(bitmap_attr->length);
		if (value_offset < 24U || value_offset > length ||
			value_length > length - value_offset || !value_length)
			goto out;
		bitmap_bytes = value_length;
	}
	if (bitmap_bytes > SIZE_MAX || bitmap_bytes > UINT64_MAX / 8U ||
		bitmap_bytes * 8U < block_count)
		goto out;
	census->failure_stage = 105U;
	observed = malloc((size_t)bitmap_bytes);
	expected = calloc(1, (size_t)bitmap_bytes);
	visited = calloc(1, visited_bytes);
	if (!observed || !expected || !visited)
		goto out;
	census->failure_stage = 106U;
	if (bitmap_attr->non_resident) {
		if (ntfs_attr_pread(bitmap, 0, bitmap->data_size, observed) !=
				bitmap->data_size)
			goto out;
	} else {
		memcpy(observed, (const unsigned char *)bitmap_attr +
			le16_to_cpu(bitmap_attr->value_offset), (size_t)bitmap_bytes);
		if (rh_mft_physical(volume, owner, &mft_physical))
			goto out;
	}
	walk.volume = volume;
	walk.allocation = allocation;
	walk.owner = owner;
	walk.owner_sequence = sequence;
	walk.block_count = block_count;
	walk.visited = visited;
	walk.canonical_upcase = canonical_upcase;
	walk.canonical_upcase_length = canonical_upcase_length;
	walk.tree_bytes = tree_bytes;
	walk.census = census;
	walk.edge_callback = edge_callback;
	walk.edge_opaque = edge_opaque;
	reachable_before = census->index_blocks_reachable;
	census->failure_stage = 107U;
	if (!walk.canonical_upcase ||
		rh_bytes_append(tree_bytes, "I30ROOT\0", 8U) ||
		rh_bytes_u64(tree_bytes, owner) ||
		rh_bytes_u16(tree_bytes, sequence) ||
		rh_bytes_append(tree_bytes, root, root_value_length) ||
		rh_walk_entries(&walk, &root->index,
			(const unsigned char *)&root->index + root_index_length))
		goto out;
	for (i = 0; i < (size_t)block_count; i++)
		if (rh_bitmap_get(visited, i))
			rh_bitmap_set(expected, i);
	census->index_blocks_expected +=
		census->index_blocks_reachable - reachable_before;
	census->bitmap_bits_examined += bitmap_bytes * 8U;
	census->failure_stage = 108U;
	if (rh_bytes_u64(expected_bytes, owner) ||
		rh_bytes_u64(expected_bytes, bitmap_bytes) ||
		rh_bytes_append(expected_bytes, expected, (size_t)bitmap_bytes))
		goto out;
	census->failure_stage = 109U;
	for (i = 0; i < (size_t)bitmap_bytes; i++) {
		unsigned char staged = observed[i];
		unsigned char masks[2];
		unsigned int phase;

		masks[0] = (unsigned char)~staged & expected[i];
		masks[1] = staged & (unsigned char)~expected[i];
		census->clear_bits_required +=
			(uint64_t)__builtin_popcount((unsigned int)masks[1]);
		/* Canonical per-byte order is every set bit, then every clear bit. */
		for (phase = 0; phase < 2U; phase++) {
			unsigned char remaining = masks[phase];

			while (remaining) {
				unsigned int bit_index = (unsigned int)__builtin_ctz(
					(unsigned int)remaining);
				unsigned char bit = (unsigned char)(1U << bit_index);
				struct rh_index_bitmap_change change;

				memset(&change, 0, sizeof(change));
				change.owner_mft_record = owner;
				change.owner_sequence = sequence;
				change.storage_mft_record = owner;
				change.storage_sequence = sequence;
				change.index_root_instance =
					le16_to_cpu(root_attr->instance);
				change.index_allocation_instance =
					le16_to_cpu(allocation_attr->instance);
				change.bitmap_instance =
					le16_to_cpu(bitmap_attr->instance);
				change.block_ordinal = (uint64_t)i * 8U + bit_index;
				change.child_vcn = change.block_ordinal < block_count ?
					(int64_t)change.block_ordinal : -1;
				change.logical_offset = i;
				change.before = staged;
				if (!phase) {
					change.after = staged | bit;
					change.set_mask = bit;
				} else {
					change.after = staged & (unsigned char)~bit;
					change.clear_mask = bit;
				}
				if (!bitmap_attr->non_resident) {
					uint64_t within_record =
						(uint64_t)((const unsigned char *)bitmap_attr -
						 record) + le16_to_cpu(bitmap_attr->value_offset) + i;
					change.storage = RH_INDEX_BITMAP_RESIDENT_MFT;
					change.lowest_vcn = -1;
					change.logical_vcn = -1;
					change.lcn = -1;
					if (within_record >= volume->mft_record_size ||
						mft_physical > UINT64_MAX - within_record)
						goto out;
					change.resident_record_offset = mft_physical;
					change.resident_value_offset = within_record;
					change.physical_offset = mft_physical;
					change.physical_length = volume->mft_record_size;
				} else {
					change.storage = RH_INDEX_BITMAP_NONRESIDENT;
					change.lowest_vcn = 0;
					if (rh_nonresident_physical(volume, bitmap, i,
							&change.physical_offset,
							&change.logical_vcn, &change.lcn))
						goto out;
					change.physical_length = 1;
				}
				if (rh_writer_range_excluded(writer,
						change.physical_offset,
						(size_t)change.physical_length) != 0 ||
						rh_add_change(census, &change))
					goto out;
				staged = change.after;
				remaining &= (unsigned char)~bit;
			}
		}
	}
	census->indexes_completed++;
	census->failure_stage = 110U;
	result = 0;
out:
	free(visited);
	free(expected);
	free(observed);
	if (bitmap)
		ntfs_attr_close(bitmap);
	if (allocation)
		ntfs_attr_close(allocation);
	if (inode && ntfs_inode_close(inode) && !result)
		result = -1;
	if (!result)
		census->failure_stage = 0;
	return result;
}

struct rh_raw_i30_shape {
	const struct rh_raw_attribute *root;
	const struct rh_raw_attribute *allocation;
	const struct rh_raw_attribute *bitmap;
	size_t root_count;
	size_t allocation_count;
	size_t allocation_base_count;
	size_t bitmap_count;
	size_t bitmap_base_count;
};

static int rh_raw_i30_dormant_auxiliary(ntfs_volume *volume,
		const struct rh_raw_mft_census *raw,
		const struct rh_raw_i30_shape *shape)
{
	const struct rh_raw_attribute *allocation = shape->allocation;
	const struct rh_raw_attribute *bitmap = shape->bitmap;
	uint64_t clusters, covered = 0, required_bitmap_bytes;
	size_t allocation_index, i;

	if (!shape->allocation_count && !shape->bitmap_count)
		return 0;
	if (!volume || !raw || !allocation || !bitmap ||
			shape->allocation_count != 1U ||
			shape->allocation_base_count != 1U ||
			shape->bitmap_count != 1U || shape->bitmap_base_count != 1U ||
			!allocation->nonresident || allocation->flags ||
			allocation->lowest_vcn || allocation->highest_vcn < 0 ||
			allocation->allocated_size <= 0 || allocation->data_size < 0 ||
			allocation->initialized_size < 0 ||
			allocation->initialized_size > allocation->data_size ||
			allocation->data_size > allocation->allocated_size ||
			allocation->data_size % volume->indx_record_size ||
			allocation->initialized_size % volume->indx_record_size ||
			!allocation->run_count ||
			allocation->allocated_size % volume->cluster_size ||
			bitmap->nonresident || bitmap->flags || !bitmap->value_length ||
			bitmap->value_arena_offset > raw->value_arena_size ||
			bitmap->value_length > raw->value_arena_size -
				bitmap->value_arena_offset)
		return -1;
	clusters = (uint64_t)allocation->allocated_size / volume->cluster_size;
	if (!clusters || (uint64_t)allocation->highest_vcn + 1U != clusters ||
			allocation->run_first > raw->run_count ||
			allocation->run_count > raw->run_count - allocation->run_first)
		return -1;
	allocation_index = (size_t)(allocation - raw->attributes);
	for (i = 0; i < allocation->run_count; i++) {
		const struct rh_raw_run *run =
			&raw->runs[allocation->run_first + i];

		if (run->attribute_index != allocation_index || run->sparse ||
				run->vcn < 0 || run->lcn < 0 || !run->length ||
				(uint64_t)run->vcn != covered ||
				run->length > clusters - covered)
			return -1;
		covered += run->length;
	}
	required_bitmap_bytes = (clusters + 7U) >> 3;
	/* A small index owns no active allocation blocks.  Windows can retain a
	 * fully sized/initialized auxiliary stream after shrinking the tree; an
	 * all-clear, completely bounded bitmap makes those blocks dormant regardless
	 * of their stale contents. */
	if (covered != clusters || bitmap->value_length < required_bitmap_bytes ||
			!rh_all_zero(raw->value_arena + bitmap->value_arena_offset,
				bitmap->value_length))
		return -1;
	return 1;
}

static int rh_raw_i30_shape_find(const struct rh_raw_mft_census *raw,
		struct rh_raw_mft_ref owner, struct rh_raw_i30_shape *shape)
{
	size_t i;

	memset(shape, 0, sizeof(*shape));
	for (i = 0; i < raw->attribute_count; i++) {
		const struct rh_raw_attribute *attribute = &raw->attributes[i];

		if (rh_raw_owned_i30(raw, attribute, owner,
				le32_to_cpu(AT_INDEX_ROOT))) {
			shape->root_count++;
			shape->root = attribute;
		} else if (rh_raw_owned_i30(raw, attribute, owner,
				le32_to_cpu(AT_INDEX_ALLOCATION))) {
			shape->allocation_count++;
			if (!attribute->lowest_vcn) {
				shape->allocation_base_count++;
				shape->allocation = attribute;
			}
		} else if (rh_raw_owned_i30(raw, attribute, owner,
				le32_to_cpu(AT_BITMAP))) {
			shape->bitmap_count++;
			if (!attribute->nonresident || !attribute->lowest_vcn) {
				shape->bitmap_base_count++;
				shape->bitmap = attribute;
			}
		}
	}
	if (shape->root_count != 1U || !shape->root ||
			shape->root->nonresident ||
			shape->root->value_length < sizeof(INDEX_ROOT) +
				sizeof(INDEX_ENTRY_HEADER) ||
			shape->root->value_arena_offset > raw->value_arena_size ||
			shape->root->value_length > raw->value_arena_size -
				shape->root->value_arena_offset) {
		errno = EIO;
		return -1;
	}
	return 0;
}

static int rh_raw_resident_record_physical(ntfs_volume *volume,
		const struct rh_raw_mft_census *raw,
		const struct rh_raw_attribute *attribute, uint64_t *physical)
{
	struct rh_raw_mft_ref mft_owner;
	uint64_t logical;

	if (!volume || !raw || !attribute || !physical || !raw->slot_count ||
			raw->slots[0].state != RH_RAW_SLOT_LIVE_BASE ||
			!raw->slots[0].sequence ||
			attribute->storage.record > UINT64_MAX /
				volume->mft_record_size) {
		errno = EIO;
		return -1;
	}
	mft_owner.record = 0;
	mft_owner.sequence = raw->slots[0].sequence;
	logical = attribute->storage.record * volume->mft_record_size;
	return rh_raw_mft_map_stream_range(raw, mft_owner,
		le32_to_cpu(AT_DATA), NULL, 0U, logical,
		volume->mft_record_size, physical);
}

static int rh_raw_nonresident_byte_location(ntfs_volume *volume,
		const struct rh_raw_mft_census *raw,
		struct rh_raw_mft_ref owner, uint32_t type, uint64_t logical,
		uint64_t *physical, int64_t *lowest_vcn, int64_t *logical_vcn,
		int64_t *lcn, uint16_t *instance)
{
	uint64_t vcn;
	size_t i, matches = 0;

	if (!volume || !raw || !physical || !lowest_vcn || !logical_vcn ||
			!lcn || !instance || !volume->cluster_size ||
			rh_raw_mft_map_stream_range(raw, owner, type,
				rh_i30_utf16le, 4U, logical, 1U, physical))
		return -1;
	vcn = logical / volume->cluster_size;
	for (i = 0; i < raw->attribute_count; i++) {
		const struct rh_raw_attribute *attribute = &raw->attributes[i];
		size_t j;

		if (!attribute->nonresident ||
				!rh_raw_owned_i30(raw, attribute, owner, type))
			continue;
		for (j = 0; j < attribute->run_count; j++) {
			const struct rh_raw_run *run =
				&raw->runs[attribute->run_first + j];
			uint64_t start, end;

			if (run->vcn < 0 || run->length > UINT64_MAX -
					(uint64_t)run->vcn)
				continue;
			start = (uint64_t)run->vcn;
			end = start + run->length;
			if (vcn < start || vcn >= end)
				continue;
			if (run->sparse || run->lcn < 0 ||
					(uint64_t)run->lcn > INT64_MAX - (vcn - start)) {
				errno = EIO;
				return -1;
			}
			*lowest_vcn = attribute->lowest_vcn;
			*logical_vcn = (int64_t)vcn;
			*lcn = run->lcn + (int64_t)(vcn - start);
			*instance = attribute->instance;
			matches++;
		}
	}
	if (matches != 1U || *physical / volume->cluster_size != (uint64_t)*lcn) {
		errno = EIO;
		return -1;
	}
	return 0;
}

static int rh_scan_large_index_raw(ntfs_volume *volume,
		const struct rh_census_reader *reader,
		const struct rh_raw_mft_census *raw,
		struct rh_raw_mft_ref owner, const struct rh_raw_i30_shape *shape,
		const unsigned char *root_value,
		struct rh_bytes *tree_bytes, struct rh_bytes *expected_bytes,
		struct rh_index_bitmap_census *census,
		const ntfschar *canonical_upcase, u32 canonical_upcase_length,
		rh_i30_edge_callback edge_callback, void *edge_opaque)
{
	const struct rh_raw_attribute *root_attr = shape->root;
	const struct rh_raw_attribute *allocation_attr = shape->allocation;
	const struct rh_raw_attribute *bitmap_attr = shape->bitmap;
	const INDEX_ROOT *root;
	unsigned char *observed = NULL, *expected = NULL, *visited = NULL;
	uint32_t root_value_length, root_payload, root_index_length;
	uint64_t block_count, bitmap_bytes, resident_physical = 0;
	uint64_t reachable_before;
	struct rh_index_walk walk;
	size_t i, visited_bytes;
	int result = -1;

	memset(&walk, 0, sizeof(walk));
	census->failure_stage = 151U;
	if (!allocation_attr || !bitmap_attr ||
			shape->allocation_base_count != 1U ||
			shape->bitmap_base_count != 1U ||
			!shape->allocation_count || !shape->bitmap_count ||
			!allocation_attr->nonresident || allocation_attr->flags ||
			allocation_attr->data_size <= 0 ||
			allocation_attr->initialized_size != allocation_attr->data_size ||
			allocation_attr->data_size % volume->indx_record_size)
		return -1;
	for (i = 0; i < raw->attribute_count; i++) {
		const struct rh_raw_attribute *attribute = &raw->attributes[i];

		if (rh_raw_owned_i30(raw, attribute, owner,
				le32_to_cpu(AT_INDEX_ALLOCATION)) &&
				(!attribute->nonresident || attribute->flags))
			return -1;
		if (rh_raw_owned_i30(raw, attribute, owner,
				le32_to_cpu(AT_BITMAP)) &&
				(attribute->nonresident != bitmap_attr->nonresident ||
				 attribute->flags))
			return -1;
	}
	root_value_length = root_attr->value_length;
	if (root_value_length < sizeof(INDEX_ROOT) + sizeof(INDEX_ENTRY_HEADER))
		return -1;
	root = (const INDEX_ROOT *)root_value;
	root_payload = root_value_length - offsetof(INDEX_ROOT, index);
	root_index_length = le32_to_cpu(root->index.index_length);
	if (root->type != AT_FILE_NAME ||
			root->collation_rule != COLLATION_FILE_NAME ||
			le32_to_cpu(root->index_block_size) != volume->indx_record_size ||
			root->clusters_per_index_block != 1 ||
			!rh_all_zero(root->reserved, sizeof(root->reserved)) ||
			root->index.ih_flags != LARGE_INDEX ||
			!rh_all_zero(root->index.reserved,
				sizeof(root->index.reserved)) ||
			le32_to_cpu(root->index.entries_offset) != sizeof(INDEX_HEADER) ||
			root_index_length != le32_to_cpu(root->index.allocated_size) ||
			root_index_length != root_payload ||
			root_index_length < sizeof(INDEX_HEADER) +
				sizeof(INDEX_ENTRY_HEADER))
		return -1;
	block_count = (uint64_t)allocation_attr->data_size /
		volume->indx_record_size;
	if (!block_count || rh_bitmap_bytes_for_bits(block_count, &visited_bytes))
		return -1;
	if (bitmap_attr->nonresident) {
		if (bitmap_attr->data_size <= 0 ||
				bitmap_attr->initialized_size != bitmap_attr->data_size)
			return -1;
		bitmap_bytes = (uint64_t)bitmap_attr->data_size;
	} else {
		if (shape->bitmap_count != 1U || !bitmap_attr->value_length)
			return -1;
		bitmap_bytes = bitmap_attr->value_length;
	}
	if (bitmap_bytes > SIZE_MAX || bitmap_bytes > UINT64_MAX / 8U ||
			bitmap_bytes * 8U < block_count)
		return -1;
	observed = malloc((size_t)bitmap_bytes);
	expected = calloc(1, (size_t)bitmap_bytes);
	visited = calloc(1, visited_bytes);
	if (!observed || !expected || !visited)
		goto out;
	census->failure_stage = 152U;
	if (bitmap_attr->nonresident) {
		if (rh_raw_mft_stream_pread_reader(reader, raw, owner,
				le32_to_cpu(AT_BITMAP), rh_i30_utf16le, 4U, 0,
				(size_t)bitmap_bytes, observed))
			goto out;
	} else {
		if (bitmap_attr->value_arena_offset > raw->value_arena_size ||
				bitmap_bytes > raw->value_arena_size -
					bitmap_attr->value_arena_offset ||
				rh_raw_resident_record_physical(volume, raw, bitmap_attr,
					&resident_physical))
			goto out;
		memcpy(observed, raw->value_arena +
			bitmap_attr->value_arena_offset, (size_t)bitmap_bytes);
	}
	walk.volume = volume;
	walk.reader = reader;
	walk.raw = raw;
	walk.allocation_owner = owner;
	walk.owner = owner.record;
	walk.owner_sequence = owner.sequence;
	walk.block_count = block_count;
	walk.visited = visited;
	walk.canonical_upcase = canonical_upcase;
	walk.canonical_upcase_length = canonical_upcase_length;
	walk.tree_bytes = tree_bytes;
	walk.census = census;
	walk.edge_callback = edge_callback;
	walk.edge_opaque = edge_opaque;
	reachable_before = census->index_blocks_reachable;
	census->failure_stage = 153U;
	if (!walk.canonical_upcase ||
			rh_bytes_append(tree_bytes, "I30ROOT\0", 8U) ||
			rh_bytes_u64(tree_bytes, owner.record) ||
			rh_bytes_u16(tree_bytes, owner.sequence) ||
			rh_bytes_append(tree_bytes, root, root_value_length) ||
			rh_walk_entries(&walk, &root->index,
				(const unsigned char *)&root->index + root_index_length))
		goto out;
	for (i = 0; i < (size_t)block_count; i++)
		if (rh_bitmap_get(visited, i))
			rh_bitmap_set(expected, i);
	census->index_blocks_expected +=
		census->index_blocks_reachable - reachable_before;
	census->bitmap_bits_examined += bitmap_bytes * 8U;
	census->failure_stage = 154U;
	if (rh_bytes_u64(expected_bytes, owner.record) ||
			rh_bytes_u64(expected_bytes, bitmap_bytes) ||
			rh_bytes_append(expected_bytes, expected, (size_t)bitmap_bytes))
		goto out;
	census->failure_stage = 155U;
	for (i = 0; i < (size_t)bitmap_bytes; i++) {
		unsigned char staged = observed[i];
		unsigned char masks[2];
		unsigned int phase;

		masks[0] = (unsigned char)~staged & expected[i];
		masks[1] = staged & (unsigned char)~expected[i];
		census->clear_bits_required +=
			(uint64_t)__builtin_popcount((unsigned int)masks[1]);
		for (phase = 0; phase < 2U; phase++) {
			unsigned char remaining = masks[phase];

			while (remaining) {
				unsigned int bit_index = (unsigned int)__builtin_ctz(
					(unsigned int)remaining);
				unsigned char bit = (unsigned char)(1U << bit_index);
				struct rh_index_bitmap_change change;

				memset(&change, 0, sizeof(change));
				change.owner_mft_record = owner.record;
				change.owner_sequence = owner.sequence;
				change.storage_mft_record = bitmap_attr->storage.record;
				change.storage_sequence = bitmap_attr->storage.sequence;
				change.index_root_instance = root_attr->instance;
				change.index_allocation_instance = allocation_attr->instance;
				change.bitmap_instance = bitmap_attr->instance;
				change.block_ordinal = (uint64_t)i * 8U + bit_index;
				change.child_vcn = change.block_ordinal < block_count ?
					(int64_t)change.block_ordinal : -1;
				change.logical_offset = i;
				change.before = staged;
				if (!phase) {
					change.after = staged | bit;
					change.set_mask = bit;
				} else {
					change.after = staged & (unsigned char)~bit;
					change.clear_mask = bit;
				}
				if (!bitmap_attr->nonresident) {
					uint64_t within = (uint64_t)bitmap_attr->record_offset +
						bitmap_attr->value_offset + i;

					change.storage = RH_INDEX_BITMAP_RESIDENT_MFT;
					change.lowest_vcn = -1;
					change.logical_vcn = -1;
					change.lcn = -1;
					if (within >= volume->mft_record_size ||
							resident_physical > UINT64_MAX - within)
						goto out;
					change.resident_record_offset = resident_physical;
					change.resident_value_offset = within;
					change.physical_offset = resident_physical;
					change.physical_length = volume->mft_record_size;
				} else {
					change.storage = RH_INDEX_BITMAP_NONRESIDENT;
					if (rh_raw_nonresident_byte_location(volume, raw, owner,
							le32_to_cpu(AT_BITMAP), i,
							&change.physical_offset, &change.lowest_vcn,
							&change.logical_vcn, &change.lcn,
							&change.bitmap_instance))
						goto out;
					change.physical_length = 1;
					/* The instance and storage record identify the extent
					 * containing this byte, rather than merely stream VCN 0. */
					{
						size_t attribute_index;
						for (attribute_index = 0;
								attribute_index < raw->attribute_count;
								attribute_index++) {
							const struct rh_raw_attribute *attribute =
								&raw->attributes[attribute_index];
							if (rh_raw_owned_i30(raw, attribute, owner,
									le32_to_cpu(AT_BITMAP)) &&
									attribute->instance == change.bitmap_instance &&
									attribute->lowest_vcn == change.lowest_vcn) {
								change.storage_mft_record =
									attribute->storage.record;
								change.storage_sequence =
									attribute->storage.sequence;
								break;
							}
						}
						if (attribute_index == raw->attribute_count)
							goto out;
					}
				}
				if (change.physical_offset > reader->device_size ||
						change.physical_length > reader->device_size -
						change.physical_offset) {
					errno = EIO;
					goto out;
				}
				if (reader->excluded) {
					int excluded;

					if (rh_census_reader_range_excluded(reader,
							change.physical_offset, change.physical_length,
							&excluded))
						goto out;
					if (excluded) {
						errno = EPERM;
						goto out;
					}
				}
				if (rh_add_change(census, &change))
					goto out;
				staged = change.after;
				remaining &= (unsigned char)~bit;
			}
		}
	}
	census->indexes_completed++;
	census->failure_stage = 0;
	result = 0;
out:
	free(visited);
	free(expected);
	free(observed);
	return result;
}

static int rh_scan_directory(ntfs_volume *volume, struct rh_writer *writer,
		uint64_t record_number, unsigned char *record,
		struct rh_bytes *tree_bytes, struct rh_bytes *expected_bytes,
		struct rh_index_bitmap_census *census,
		const ntfschar *canonical_upcase, u32 canonical_upcase_length,
		rh_i30_edge_callback edge_callback, void *edge_opaque)
{
	MFT_RECORD *mft = (MFT_RECORD *)record;
	ATTR_RECORD *attribute;
	ATTR_RECORD *root = NULL, *allocation = NULL, *bitmap = NULL;
	uint32_t used, offset;
	int found_end = 0;

	used = le32_to_cpu(mft->bytes_in_use);
	offset = le16_to_cpu(mft->attrs_offset);
	while (offset <= used - sizeof(uint32_t)) {
		uint32_t type, length, minimum;

		attribute = (ATTR_RECORD *)(record + offset);
		type = le32_to_cpu(attribute->type);
		if (type == 0xffffffffU) {
			found_end = 1;
			break;
		}
		if (used - offset < 24U)
			return -1;
		length = le32_to_cpu(attribute->length);
		minimum = attribute->non_resident ? 64U : 24U;
		if (attribute->non_resident > 1 || length < minimum || (length & 7U) ||
			length > used - offset)
			return -1;
		if (type == 0x20U)
			return -1;
		if ((type == 0x90U || type == 0xa0U || type == 0xb0U) &&
				rh_name_i30(attribute, length, minimum)) {
			ATTR_RECORD **slot = type == 0x90U ? &root :
				(type == 0xa0U ? &allocation : &bitmap);
			if (*slot) {
				census->ambiguous_attributes++;
				return -1;
			}
			*slot = attribute;
		}
		offset += length;
	}
	if (!found_end || !root || root->non_resident)
		return -1;
	census->indexes_expected++;
	{
		const INDEX_ROOT *index_root = (const INDEX_ROOT *)
			((unsigned char *)root + le16_to_cpu(root->value_offset));
		if (le16_to_cpu(root->value_offset) > le32_to_cpu(root->length) ||
			le32_to_cpu(root->value_length) > le32_to_cpu(root->length) -
			 le16_to_cpu(root->value_offset) ||
			le32_to_cpu(root->value_length) < sizeof(INDEX_ROOT) +
			 sizeof(INDEX_ENTRY_HEADER))
			return -1;
		if (index_root->index.ih_flags == SMALL_INDEX) {
			struct rh_index_walk walk;
			uint32_t index_length =
				le32_to_cpu(index_root->index.index_length);
			uint32_t payload = le32_to_cpu(root->value_length) -
				offsetof(INDEX_ROOT, index);
			if (allocation || bitmap || index_root->type != AT_FILE_NAME ||
				index_root->collation_rule != COLLATION_FILE_NAME ||
				le32_to_cpu(index_root->index_block_size) !=
				 volume->indx_record_size ||
				index_root->clusters_per_index_block != 1 ||
				!rh_all_zero(index_root->reserved,
				 sizeof(index_root->reserved)) ||
				!rh_all_zero(index_root->index.reserved,
				 sizeof(index_root->index.reserved)) ||
				index_length != payload ||
				le32_to_cpu(index_root->index.allocated_size) != payload)
				return -1;
			memset(&walk, 0, sizeof(walk));
			walk.volume = volume;
			walk.owner = record_number;
			walk.owner_sequence = le16_to_cpu(mft->sequence_number);
			walk.canonical_upcase = canonical_upcase;
			walk.canonical_upcase_length = canonical_upcase_length;
			walk.tree_bytes = tree_bytes;
			walk.census = census;
			walk.edge_callback = edge_callback;
			walk.edge_opaque = edge_opaque;
			if (!walk.canonical_upcase ||
				rh_bytes_append(tree_bytes, "I30ROOT\0", 8U) ||
				rh_bytes_u64(tree_bytes, record_number) ||
				rh_bytes_u16(tree_bytes,
					le16_to_cpu(mft->sequence_number)) ||
				rh_bytes_append(tree_bytes, index_root,
					le32_to_cpu(root->value_length)) ||
				rh_walk_entries(&walk, &index_root->index,
					(const unsigned char *)&index_root->index +
					index_length)) {
				return -1;
			}
			census->indexes_completed++;
		} else if (index_root->index.ih_flags == LARGE_INDEX) {
			if (!allocation || !bitmap || !allocation->non_resident)
				return -1;
			if (rh_scan_large_index(volume, writer, record_number,
					le16_to_cpu(mft->sequence_number), record, root,
					allocation, bitmap, tree_bytes, expected_bytes, census,
					canonical_upcase, canonical_upcase_length,
					edge_callback, edge_opaque))
				return -1;
		} else
			return -1;
	}
	return 0;
}

static int rh_scan_directory_raw(ntfs_volume *volume,
		const struct rh_census_reader *reader,
		const struct rh_raw_mft_census *raw,
		const struct rh_raw_mft_slot *slot, struct rh_bytes *tree_bytes,
		struct rh_bytes *expected_bytes,
		struct rh_index_bitmap_census *census,
		const ntfschar *canonical_upcase, u32 canonical_upcase_length,
		rh_i30_edge_callback edge_callback, void *edge_opaque)
{
	struct rh_raw_i30_shape shape;
	struct rh_raw_mft_ref owner;
	const INDEX_ROOT *index_root;
	unsigned char *root_value = NULL;
	uint32_t index_length, payload;
	int result = -1;

	owner.record = slot->record;
	owner.sequence = slot->sequence;
	if (rh_raw_i30_shape_find(raw, owner, &shape))
		return -1;
	census->indexes_expected++;
	root_value = malloc(shape.root->value_length);
	if (!root_value)
		return -1;
	memcpy(root_value, raw->value_arena + shape.root->value_arena_offset,
		shape.root->value_length);
	index_root = (const INDEX_ROOT *)root_value;
	index_length = le32_to_cpu(index_root->index.index_length);
	payload = shape.root->value_length - offsetof(INDEX_ROOT, index);
	if (index_root->index.ih_flags == SMALL_INDEX) {
		struct rh_index_walk walk;
		int dormant_auxiliary = rh_raw_i30_dormant_auxiliary(volume, raw,
			&shape);

		if (dormant_auxiliary < 0 ||
				((shape.allocation_count || shape.bitmap_count) &&
				 !dormant_auxiliary) ||
				index_root->type != AT_FILE_NAME ||
				index_root->collation_rule != COLLATION_FILE_NAME ||
				le32_to_cpu(index_root->index_block_size) !=
					volume->indx_record_size ||
				index_root->clusters_per_index_block != 1 ||
				!rh_all_zero(index_root->reserved,
					sizeof(index_root->reserved)) ||
				!rh_all_zero(index_root->index.reserved,
					sizeof(index_root->index.reserved)) ||
				le32_to_cpu(index_root->index.entries_offset) !=
					sizeof(INDEX_HEADER) ||
				index_length != payload ||
				le32_to_cpu(index_root->index.allocated_size) != payload ||
				index_length < sizeof(INDEX_HEADER) +
					sizeof(INDEX_ENTRY_HEADER))
			goto out;
		memset(&walk, 0, sizeof(walk));
		walk.volume = volume;
		walk.reader = reader;
		walk.raw = raw;
		walk.owner = owner.record;
		walk.owner_sequence = owner.sequence;
		walk.canonical_upcase = canonical_upcase;
		walk.canonical_upcase_length = canonical_upcase_length;
		walk.tree_bytes = tree_bytes;
		walk.census = census;
		walk.edge_callback = edge_callback;
		walk.edge_opaque = edge_opaque;
		if (!walk.canonical_upcase ||
				rh_bytes_append(tree_bytes, "I30ROOT\0", 8U) ||
				rh_bytes_u64(tree_bytes, owner.record) ||
				rh_bytes_u16(tree_bytes, owner.sequence) ||
				rh_bytes_append(tree_bytes, index_root,
					shape.root->value_length) ||
				rh_walk_entries(&walk, &index_root->index,
					(const unsigned char *)&index_root->index + index_length))
			goto out;
		census->indexes_completed++;
	} else if (index_root->index.ih_flags == LARGE_INDEX) {
		if (rh_scan_large_index_raw(volume, reader, raw, owner, &shape,
				root_value, tree_bytes, expected_bytes, census, canonical_upcase,
				canonical_upcase_length, edge_callback, edge_opaque))
			goto out;
	} else {
		errno = EIO;
		goto out;
	}
	result = 0;
out:
	free(root_value);
	return result;
}

static int rh_finalize_hashes(struct rh_index_bitmap_census *census,
		struct rh_bytes *tree_bytes, struct rh_bytes *expected_bytes)
{
	struct rh_bytes canonical = {0};
	size_t i;

	if (rh_bytes_final(tree_bytes, census->tree_hash) ||
			rh_bytes_final(expected_bytes, census->expected_hash) ||
		rh_bytes_append(&canonical, "RHI30BM2", 8U) ||
		rh_bytes_u64(&canonical, census->mft_slots_expected) ||
		rh_bytes_u64(&canonical, census->mft_slots_completed) ||
		rh_bytes_u64(&canonical, census->directories_expected) ||
		rh_bytes_u64(&canonical, census->directories_completed) ||
		rh_bytes_u64(&canonical, census->indexes_expected) ||
		rh_bytes_u64(&canonical, census->indexes_completed) ||
		rh_bytes_u64(&canonical, census->index_entries_examined) ||
		rh_bytes_u64(&canonical, census->index_blocks_expected) ||
		rh_bytes_u64(&canonical, census->index_blocks_examined) ||
		rh_bytes_u64(&canonical, census->index_blocks_reachable) ||
		rh_bytes_u64(&canonical, census->child_vcns_examined) ||
		rh_bytes_u64(&canonical, census->bitmap_bits_examined) ||
		rh_bytes_append(&canonical, census->tree_hash, 32U) ||
		rh_bytes_append(&canonical, census->expected_hash, 32U) ||
		rh_bytes_u64(&canonical, census->change_count))
		return -1;
	for (i = 0; i < census->change_count; i++) {
		struct rh_index_bitmap_change *change = &census->changes[i];
		struct rh_bytes evidence = {0};
		struct rh_hash_stream prefix_snapshot;
		unsigned char prefix_hash[32];

		change->evidence_version = RH_INDEX_BITMAP_EVIDENCE_VERSION;
		if (rh_bytes_u64(&canonical, change->owner_mft_record) ||
			rh_bytes_u16(&canonical, change->owner_sequence) ||
			rh_bytes_u64(&canonical, change->storage_mft_record) ||
			rh_bytes_u16(&canonical, change->storage_sequence) ||
			rh_bytes_u16(&canonical, change->index_root_instance) ||
			rh_bytes_u16(&canonical, change->index_allocation_instance) ||
			rh_bytes_u16(&canonical, change->bitmap_instance) ||
			rh_bytes_u64(&canonical, change->storage) ||
			rh_bytes_u64(&canonical, change->block_ordinal) ||
			rh_bytes_u64(&canonical, change->logical_offset) ||
			rh_bytes_u64(&canonical, change->resident_record_offset) ||
			rh_bytes_u64(&canonical, change->resident_value_offset) ||
			rh_bytes_u64(&canonical, change->physical_offset) ||
			rh_bytes_u64(&canonical, change->physical_length) ||
			rh_bytes_append(&canonical, &change->before, 1U) ||
			rh_bytes_append(&canonical, &change->after, 1U) ||
			rh_bytes_append(&canonical, &change->set_mask, 1U) ||
			rh_bytes_append(&canonical, &change->clear_mask, 1U))
			return -1;
		/* Bind each immutable candidate to the exact cumulative canonical
		 * prefix without retaining that potentially unbounded prefix. */
		prefix_snapshot = canonical.hash;
		if (rh_hash_stream_final(&prefix_snapshot, prefix_hash) ||
			rh_bytes_append(&evidence, "RHI30EV2", 8U) ||
			rh_bytes_append(&evidence, census->tree_hash, 32U) ||
			rh_bytes_append(&evidence, census->expected_hash, 32U) ||
			rh_bytes_append(&evidence, prefix_hash, sizeof(prefix_hash)) ||
			rh_bytes_final(&evidence, change->evidence_hash))
			return -1;
	}
	return rh_bytes_final(&canonical, census->census_hash);
}

int rh_index_bitmap_census_run_edges(ntfs_volume *volume,
		struct rh_writer *writer, uint64_t generation,
		struct rh_index_bitmap_census *census,
		rh_i30_edge_callback edge_callback, void *edge_opaque)
{
	static const char expected_upcase[] =
		"41c26bc7a12bdaeb26025c93118697c7e3ef81ee048b00fe5cce2a472e0e0742";
	unsigned char *record = NULL;
	struct rh_bytes tree_bytes = {0}, expected_bytes = {0};
	ntfschar *canonical_upcase = NULL;
	char upcase_hash[65];
	uint64_t slots, i;
	u32 canonical_upcase_length;
	int result = -1;

	if (!volume || !writer || !generation || !census ||
		volume->sector_size != 512U || volume->cluster_size != 4096U ||
		volume->mft_record_size != 1024U ||
		volume->indx_record_size != 4096U || !volume->mft_na ||
		volume->mft_na->initialized_size <= 0) {
		errno = EINVAL;
		return -1;
	}
	memset(census, 0, sizeof(*census));
	census->generation = generation;
	if (rh_index_bitmap_slot_count_from_initialized(
			(uint64_t)volume->mft_na->initialized_size,
			volume->mft_record_size, &slots))
		return -1;
	census->mft_slots_expected = slots;
	census->targets_outside_wal = 1;
	canonical_upcase_length = ntfs_upcase_build_default(&canonical_upcase);
	if (!canonical_upcase || canonical_upcase_length != 65536U)
		goto out;
	rh_sha256_hex(canonical_upcase,
		(size_t)canonical_upcase_length * sizeof(*canonical_upcase),
		upcase_hash);
	if (strcmp(upcase_hash, expected_upcase)) {
		errno = EIO;
		goto out;
	}
	record = malloc(volume->mft_record_size);
	if (!record)
		goto out;
	for (i = 0; i < slots; i++) {
		MFT_RECORD *mft;
		uint32_t used, allocated, attrs;
		uint16_t flags;

		if (i > INT64_MAX / volume->mft_record_size ||
			ntfs_attr_mst_pread(volume->mft_na,
				(int64_t)(i * volume->mft_record_size), 1,
				volume->mft_record_size, record) != 1) {
			census->unreadable_records++;
			goto out;
		}
		mft = (MFT_RECORD *)record;
		used = le32_to_cpu(mft->bytes_in_use);
		allocated = le32_to_cpu(mft->bytes_allocated);
		attrs = le16_to_cpu(mft->attrs_offset);
		flags = le16_to_cpu(mft->flags);
		if (mft->magic != magic_FILE || allocated != volume->mft_record_size ||
			used < sizeof(*mft) || used > allocated || (used & 7U) ||
			attrs < sizeof(*mft) || (attrs & 7U) ||
			attrs > used - sizeof(uint32_t) ||
			(flags & (uint16_t)~(le16_to_cpu(MFT_RECORD_IN_USE) |
			 le16_to_cpu(MFT_RECORD_IS_DIRECTORY) |
			 le16_to_cpu(MFT_RECORD_IS_4) |
			 le16_to_cpu(MFT_RECORD_IS_VIEW_INDEX))))
			goto out;
		census->mft_slots_completed++;
		if (!(flags & le16_to_cpu(MFT_RECORD_IN_USE)))
			continue;
		if (le32_to_cpu(mft->mft_record_number) != i ||
			!le16_to_cpu(mft->sequence_number))
			goto out;
		if (!(flags & le16_to_cpu(MFT_RECORD_IS_DIRECTORY)))
			continue;
		census->directories_expected++;
		if (rh_scan_directory(volume, writer, i, record, &tree_bytes,
				&expected_bytes, census, canonical_upcase,
				canonical_upcase_length, edge_callback, edge_opaque))
			goto out;
		census->directories_completed++;
	}
	if (census->mft_slots_completed != census->mft_slots_expected ||
		census->directories_completed != census->directories_expected ||
		census->indexes_completed != census->indexes_expected ||
		census->index_blocks_examined != census->index_blocks_expected ||
		census->index_blocks_reachable != census->index_blocks_expected ||
		census->unreadable_records || census->ambiguous_attributes ||
		census->unresolved_blocks || rh_finalize_hashes(census, &tree_bytes,
			&expected_bytes))
		goto out;
	census->complete = 1;
	census->index_tree_complete = 1;
	census->child_vcns_valid = 1;
	census->indx_blocks_valid = 1;
	census->reachable_set_exact = 1;
	census->sets_proven_reachable = 1;
	/* Full raw FILE_NAME reciprocity is sealed by the later namespace pass. */
	census->namespace_reciprocity_complete = 0;
	census->clears_proven_unreferenced = 0;
	census->set_only_safe = !census->clear_bits_required;
	for (i = 0; i < census->change_count; i++)
		if (census->changes[i].storage == RH_INDEX_BITMAP_RESIDENT_MFT &&
				(census->changes[i].storage_mft_record !=
				 census->changes[i].owner_mft_record ||
				 census->changes[i].storage_sequence !=
				 census->changes[i].owner_sequence))
			census->set_only_safe = 0;
	census->clean = !census->change_count && !census->clear_bits_required;
	result = 0;
out:
	free(canonical_upcase);
	free(record);
	return result;
}

int rh_index_bitmap_census_run(ntfs_volume *volume, struct rh_writer *writer,
		uint64_t generation, struct rh_index_bitmap_census *census)
{
	return rh_index_bitmap_census_run_edges(volume, writer, generation,
		census, NULL, NULL);
}

int rh_index_bitmap_census_run_edges_from_raw_reader(ntfs_volume *volume,
		const struct rh_census_reader *reader,
		const struct rh_raw_mft_census *raw,
		uint64_t generation, struct rh_index_bitmap_census *census,
		rh_i30_edge_callback edge_callback, void *edge_opaque)
{
	static const char expected_upcase[] =
		"41c26bc7a12bdaeb26025c93118697c7e3ef81ee048b00fe5cce2a472e0e0742";
	struct rh_bytes tree_bytes = {0}, expected_bytes = {0};
	ntfschar *canonical_upcase = NULL;
	char upcase_hash[65];
	u32 canonical_upcase_length;
	uint64_t i;
	int result = -1;

	if (!volume || !reader || !raw || !generation || !census ||
			volume->sector_size != 512U || volume->cluster_size != 4096U ||
			volume->mft_record_size != 1024U ||
			volume->indx_record_size != 4096U ||
			!raw->generation || !raw->records_complete ||
			!raw->records_bounded || !raw->attribute_lists_complete ||
			!raw->extents_complete || raw->unreadable_records ||
			raw->invalid_records || !raw->slot_count ||
			raw->slot_count != raw->slots_expected ||
			raw->slots_completed != raw->slots_expected) {
		errno = EINVAL;
		return -1;
	}
	memset(census, 0, sizeof(*census));
	census->generation = generation;
	census->mft_slots_expected = raw->slot_count;
	census->targets_outside_wal = reader->excluded != NULL;
	canonical_upcase_length = ntfs_upcase_build_default(&canonical_upcase);
	if (!canonical_upcase || canonical_upcase_length != 65536U)
		goto out;
	rh_sha256_hex(canonical_upcase,
		(size_t)canonical_upcase_length * sizeof(*canonical_upcase),
		upcase_hash);
	if (strcmp(upcase_hash, expected_upcase)) {
		errno = EIO;
		goto out;
	}
	for (i = 0; i < raw->slot_count; i++) {
		const struct rh_raw_mft_slot *slot = &raw->slots[i];

		if (slot->record != i ||
				(slot->state != RH_RAW_SLOT_FREE &&
				 slot->state != RH_RAW_SLOT_LIVE_BASE &&
				 slot->state != RH_RAW_SLOT_LIVE_EXTENT &&
				 slot->state != RH_RAW_SLOT_OPAQUE_FREE_CANDIDATE)) {
			census->unreadable_records++;
			errno = EIO;
			goto out;
		}
		census->mft_slots_completed++;
		if (slot->state != RH_RAW_SLOT_LIVE_BASE)
			continue;
		if (!slot->sequence || slot->record != i) {
			errno = EIO;
			goto out;
		}
		if (!(slot->flags & le16_to_cpu(MFT_RECORD_IS_DIRECTORY)))
			continue;
		census->directories_expected++;
		if (rh_scan_directory_raw(volume, reader, raw, slot, &tree_bytes,
				&expected_bytes, census, canonical_upcase,
				canonical_upcase_length, edge_callback, edge_opaque))
			goto out;
		census->directories_completed++;
	}
	if (census->mft_slots_completed != census->mft_slots_expected ||
			census->directories_completed != census->directories_expected ||
			census->indexes_completed != census->indexes_expected ||
			census->index_blocks_examined != census->index_blocks_expected ||
			census->index_blocks_reachable != census->index_blocks_expected ||
			census->unreadable_records || census->ambiguous_attributes ||
			census->unresolved_blocks || rh_finalize_hashes(census,
				&tree_bytes, &expected_bytes))
		goto out;
	census->complete = 1;
	census->index_tree_complete = 1;
	census->child_vcns_valid = 1;
	census->indx_blocks_valid = 1;
	census->reachable_set_exact = 1;
	census->sets_proven_reachable = 1;
	census->namespace_reciprocity_complete = 0;
	census->clears_proven_unreferenced = 0;
	census->set_only_safe = !census->clear_bits_required;
	for (i = 0; i < census->change_count; i++)
		if (census->changes[i].storage == RH_INDEX_BITMAP_RESIDENT_MFT &&
				(census->changes[i].storage_mft_record !=
				 census->changes[i].owner_mft_record ||
				 census->changes[i].storage_sequence !=
				 census->changes[i].owner_sequence))
			census->set_only_safe = 0;
	census->clean = !census->change_count && !census->clear_bits_required;
	result = 0;
out:
	free(canonical_upcase);
	return result;
}

int rh_index_bitmap_census_run_edges_from_raw(ntfs_volume *volume,
		struct rh_writer *writer, const struct rh_raw_mft_census *raw,
		uint64_t generation, struct rh_index_bitmap_census *census,
		rh_i30_edge_callback edge_callback, void *edge_opaque)
{
	struct rh_census_reader reader;

	if (!writer || rh_census_reader_from_writer_prefix(writer,
			writer->operation_count, &reader))
		return -1;
	return rh_index_bitmap_census_run_edges_from_raw_reader(volume, &reader,
		raw, generation, census, edge_callback, edge_opaque);
}

int rh_index_bitmap_census_run_from_raw(ntfs_volume *volume,
		struct rh_writer *writer, const struct rh_raw_mft_census *raw,
		uint64_t generation, struct rh_index_bitmap_census *census)
{
	return rh_index_bitmap_census_run_edges_from_raw(volume, writer, raw,
		generation, census, NULL, NULL);
}

int rh_index_bitmap_census_run_from_raw_reader(ntfs_volume *volume,
		const struct rh_census_reader *reader,
		const struct rh_raw_mft_census *raw, uint64_t generation,
		struct rh_index_bitmap_census *census)
{
	return rh_index_bitmap_census_run_edges_from_raw_reader(volume, reader,
		raw, generation, census, NULL, NULL);
}

int rh_index_bitmap_seal_policy(
		const struct rh_index_bitmap_census *initial,
		const struct rh_index_bitmap_census *final,
		const struct rh_writer *writer, size_t first_operation_ordinal,
		int identity_bound, int namespace_census_complete,
		struct rh_policy_evidence **evidence)
{
	static const uint16_t i30_prefix[] = {'$', 'I', '3', '0'};
	struct rh_bitmap_census_result result;
	struct rh_policy_target_identity *targets = NULL;
	unsigned char plan_hash[32];
	size_t i;
	int status = -1;

	if (evidence)
		*evidence = NULL;
	if (!initial || !final || !writer || !evidence || !identity_bound ||
			!namespace_census_complete || !initial->complete || !final->complete ||
			!initial->index_tree_complete || !final->index_tree_complete ||
			!initial->child_vcns_valid || !final->child_vcns_valid ||
			!initial->indx_blocks_valid || !final->indx_blocks_valid ||
			!initial->reachable_set_exact || !final->reachable_set_exact ||
			!initial->sets_proven_reachable || !initial->set_only_safe ||
			initial->clear_bits_required || !initial->change_count ||
			!final->clean || final->change_count || final->clear_bits_required ||
			!initial->targets_outside_wal || !final->targets_outside_wal ||
			memcmp(initial->tree_hash, final->tree_hash, 32U) ||
			memcmp(initial->expected_hash, final->expected_hash, 32U) ||
			initial->change_count > writer->operation_count ||
			!first_operation_ordinal ||
			first_operation_ordinal - 1U > writer->operation_count ||
			initial->change_count > writer->operation_count -
				(first_operation_ordinal - 1U) ||
			rh_writer_plan_hash(writer, writer->operation_count, plan_hash)) {
		errno = EINVAL;
		return -1;
	}
	targets = calloc(initial->change_count, sizeof(*targets));
	if (!targets)
		return -1;
	for (i = 0; i < initial->change_count; i++) {
		const struct rh_index_bitmap_change *change = &initial->changes[i];
		const struct rh_write_operation *operation =
			&writer->operations[first_operation_ordinal - 1U + i];
		struct rh_policy_target_identity *target = &targets[i];
		uint16_t location_flags;

		if (operation->kind != RH_WRITE_INDEX_BITMAP || !change->set_mask ||
				change->clear_mask || operation->offset != change->physical_offset ||
				operation->length != change->physical_length) {
			errno = EIO;
			goto out;
		}
		if (change->storage == RH_INDEX_BITMAP_RESIDENT_MFT) {
			target->write_object = RH_WRITE_TARGET_MFT_RECORD_PRIMARY;
			location_flags = RH_WRITE_TARGET_PRIMARY |
				RH_WRITE_TARGET_RESIDENT;
			target->lowest_vcn = UINT64_MAX;
			target->logical_vcn = UINT64_MAX;
			target->lcn = UINT64_MAX;
		} else if (change->storage == RH_INDEX_BITMAP_NONRESIDENT) {
			target->write_object = RH_WRITE_TARGET_NONRESIDENT_ATTRIBUTE;
			location_flags = RH_WRITE_TARGET_NONRESIDENT;
			target->lowest_vcn = (uint64_t)change->lowest_vcn;
			target->logical_vcn = (uint64_t)change->logical_vcn;
			target->lcn = (uint64_t)change->lcn;
		} else {
			errno = EIO;
			goto out;
		}
		target->object = RH_POLICY_TARGET_INDEX_BITMAP;
		target->action_kind = RH_WRITE_INDEX_BITMAP;
		target->semantic_flags = location_flags | RH_WRITE_TARGET_SET_ONLY;
		target->mft_record = change->owner_mft_record;
		target->mft_sequence = change->owner_sequence;
		target->attribute_instance = change->bitmap_instance;
		target->attribute_type = AT_BITMAP;
		target->attribute_name_length = 4U;
		target->attribute_name_prefix_length = 4U;
		memcpy(target->attribute_name_prefix, i30_prefix,
			sizeof(i30_prefix));
		{
			static const unsigned char i30[] = {'$', 0, 'I', 0, '3', 0, '0', 0};
			rh_sha256(i30, sizeof(i30), target->attribute_name_hash);
		}
		target->logical_offset = change->logical_offset;
		target->logical_length = 1U;
		target->physical_offset = change->physical_offset;
		target->physical_length = change->physical_length;
		target->semantic_offset = change->storage ==
			RH_INDEX_BITMAP_RESIDENT_MFT ? change->resident_record_offset +
			change->resident_value_offset : change->physical_offset;
		target->semantic_length = 1U;
		target->operation_ordinal = first_operation_ordinal + i;
		target->writer_checkpoint = writer->operation_count;
		memcpy(target->staged_plan_hash, plan_hash, sizeof(plan_hash));
		rh_sha256(operation->before, operation->length, target->before_hash);
		rh_sha256(operation->after, operation->length, target->after_hash);
		target->changes_set_bits = 1U;
	}
	memset(&result, 0, sizeof(result));
	result.object = RH_POLICY_TARGET_INDEX_BITMAP;
	result.generation = initial->generation;
	memcpy(result.census_hash, initial->census_hash, 32U);
	result.final_overlay_generation = final->generation;
	memcpy(result.final_overlay_hash, final->census_hash, 32U);
	result.completed = 1;
	result.identity_bound = 1;
	result.complete_mft_census = 1;
	result.complete_namespace_census = 1;
	result.complete_index_census = 1;
	result.no_io_uncertainty = !initial->unreadable_records &&
		!final->unreadable_records && !initial->ambiguous_attributes &&
		!final->ambiguous_attributes;
	result.targets_outside_wal = initial->targets_outside_wal &&
		final->targets_outside_wal;
	result.index_tree_complete = 1;
	result.child_vcns_valid = 1;
	result.indx_blocks_valid = 1;
	result.reachable_set_exact = 1;
	result.no_unresolved_blocks = !initial->unresolved_blocks &&
		!final->unresolved_blocks;
	result.data_preserving = 1;
	result.final_overlay_valid = 1;
	status = rh_policy_seal_bitmap_census(&result, targets,
		initial->change_count, evidence);
out:
	free(targets);
	return status;
}

void rh_index_bitmap_census_destroy(struct rh_index_bitmap_census *census)
{
	if (!census)
		return;
	free(census->changes);
	memset(census, 0, sizeof(*census));
}
