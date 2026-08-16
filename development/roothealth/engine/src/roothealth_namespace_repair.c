/* ROOTHEALTH_REPAIR_ROLE(TYPED_WAL_ADAPTER) ROOTHEALTH_IO_ROLE(PLANNER) */
#include "config.h"

#include <errno.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include "endians.h"
#include "layout.h"
#include "mst.h"
#include "roothealth_census_device.h"
#include "roothealth_namespace_repair.h"
#include "roothealth_raw_mft.h"

#define RH_FILE_MFT 0U
#define RH_FILE_ROOT 5U
#define RH_MFT_RECORD_BYTES 1024U

static int rh_ascii_name(const unsigned char *bytes, size_t available,
		uint8_t length, const char *ascii)
{
	size_t i, expected = strlen(ascii);

	if (!bytes || length != expected || available < expected * 2U)
		return 0;
	for (i = 0; i < expected; i++)
		if (bytes[2U * i] != (unsigned char)ascii[i] || bytes[2U * i + 1U])
			return 0;
	return 1;
}

static int rh_ref_equal(struct rh_raw_mft_ref left,
		struct rh_raw_mft_ref right)
{
	return left.record == right.record && left.sequence == right.sequence;
}

static int rh_edge_matches_link(const struct rh_namespace_census *ns,
		const struct rh_namespace_i30_edge *edge,
		const struct rh_namespace_link *link)
{
	if (!ns || !edge || !link || !rh_ref_equal(edge->child, link->owner) ||
			!rh_ref_equal(edge->parent, link->parent) ||
			edge->name_namespace != link->name_namespace ||
			edge->name_length != link->name_length ||
			memcmp(edge->reciprocity_value_hash,
				link->reciprocity_value_hash, 32U))
		return 0;
	if (edge->name_offset > ns->i30_name_arena_size ||
			link->name_offset > ns->name_arena_size ||
			(size_t)edge->name_length * 2U >
				ns->i30_name_arena_size - edge->name_offset ||
			(size_t)link->name_length * 2U >
				ns->name_arena_size - link->name_offset)
		return 0;
	return !memcmp(ns->i30_name_arena + edge->name_offset,
		ns->name_arena + link->name_offset, (size_t)edge->name_length * 2U);
}

static int rh_resolve_operations_parent_without_edge(
		const struct rh_complete_census *census,
		const struct rh_namespace_i30_edge *ignored,
		struct rh_raw_mft_ref *operations)
{
	static const char *const components[] = {"the one", "settings", "operations"};
	struct rh_namespace_census filtered;
	struct rh_namespace_i30_edge *edges = NULL;
	struct rh_raw_mft_ref parent;
	size_t i, copied = 0;
	int result = -1;

	if (!census || !ignored || !operations ||
			census->raw.slot_count <= RH_FILE_ROOT ||
			!census->namespace_census.i30_edges ||
			census->namespace_census.i30_edge_count !=
				census->namespace_census.link_count + 1U)
		return -1;
	if (census->namespace_census.link_count) {
		edges = malloc(census->namespace_census.link_count * sizeof(*edges));
		if (!edges)
			return -1;
	}
	for (i = 0; i < census->namespace_census.i30_edge_count; i++) {
		const struct rh_namespace_i30_edge *edge =
			&census->namespace_census.i30_edges[i];

		if (edge == ignored)
			continue;
		if (copied >= census->namespace_census.link_count)
			goto out;
		edges[copied++] = *edge;
	}
	if (copied != census->namespace_census.link_count)
		goto out;
	filtered = census->namespace_census;
	filtered.i30_edges = edges;
	filtered.i30_edge_count = copied;
	filtered.reciprocity_complete = 1;
	parent.record = RH_FILE_ROOT;
	parent.sequence = census->raw.slots[RH_FILE_ROOT].sequence;
	for (i = 0; i < sizeof(components) / sizeof(components[0]); i++) {
		struct rh_namespace_resolved_child resolved;

		if (rh_namespace_resolve_exact_child(&census->raw,
				&filtered, parent, components[i], 1,
				&resolved) || resolved.state != RH_NAMESPACE_CHILD_PRESENT)
			goto out;
		parent = resolved.child;
	}
	*operations = parent;
	result = 0;
out:
	free(edges);
	return result;
}

static int rh_i30_attribute(const struct rh_complete_census *census,
		struct rh_raw_mft_ref parent, const struct rh_raw_attribute **root)
{
	static const unsigned char i30[] = {'$', 0, 'I', 0, '3', 0, '0', 0};
	size_t i;

	*root = NULL;
	for (i = 0; i < census->raw.attribute_count; i++) {
		const struct rh_raw_attribute *attribute = &census->raw.attributes[i];
		const unsigned char *name;

		if (!rh_ref_equal(attribute->owner, parent) ||
				(attribute->type != AT_INDEX_ROOT &&
				 attribute->type != AT_INDEX_ALLOCATION &&
				 attribute->type != AT_BITMAP) || attribute->name_length != 4U ||
				attribute->name_offset > census->raw.name_arena_size ||
				8U > census->raw.name_arena_size - attribute->name_offset)
			continue;
		name = census->raw.name_arena + attribute->name_offset;
		if (memcmp(name, i30, sizeof(i30)))
			continue;
		/* Only a single resident small index is in the repair surface. */
		if (attribute->type != AT_INDEX_ROOT || attribute->nonresident ||
				!rh_ref_equal(attribute->storage, parent) || *root)
			return -1;
		*root = attribute;
	}
	return *root ? 0 : -1;
}

int rh_namespace_operations_registry_qualify(
		const struct rh_complete_census *census,
		struct rh_namespace_repair_candidate *candidate)
{
	const struct rh_namespace_census *ns;
	const struct rh_namespace_i30_edge *unmatched = NULL;
	const struct rh_raw_attribute *root = NULL;
	struct rh_raw_mft_ref operations, mft;
	size_t i, j, unmatched_count = 0;

	if (candidate)
		memset(candidate, 0, sizeof(*candidate));
	if (!census || !candidate || census->version != RH_COMPLETE_CENSUS_VERSION ||
			!census->identity_matches || !census->raw.records_complete ||
			!census->raw.records_bounded || !census->raw.layout_complete ||
			!census->raw.attribute_lists_complete ||
			!census->raw.extents_complete || census->raw.unreadable_records ||
			census->raw.invalid_records || !census->namespace_census.graph_complete ||
			!census->namespace_census.i30_complete ||
			census->namespace_census.reciprocity_complete ||
			!census->index_bitmap.complete ||
			!census->index_bitmap.index_tree_complete ||
			!census->index_bitmap.child_vcns_valid ||
			!census->index_bitmap.indx_blocks_valid ||
			census->index_bitmap.unreadable_records ||
			census->index_bitmap.ambiguous_attributes ||
			!census->mft_bitmap.complete ||
			!census->cluster_bitmap.complete) {
		errno = EINVAL;
		return -1;
	}
	ns = &census->namespace_census;
	if (ns->i30_edge_count != ns->link_count + 1U || !ns->i30_edges ||
			(ns->link_count && !ns->links)) {
		errno = EPERM;
		return -1;
	}
	for (i = 0; i < ns->i30_edge_count; i++) {
		size_t matches = 0;
		for (j = 0; j < ns->link_count; j++)
			matches += rh_edge_matches_link(ns, &ns->i30_edges[i],
				&ns->links[j]);
		if (!matches) {
			unmatched = &ns->i30_edges[i];
			unmatched_count++;
		} else if (matches != 1U) {
			errno = EPERM;
			return -1;
		}
	}
	for (j = 0; j < ns->link_count; j++) {
		size_t matches = 0;
		for (i = 0; i < ns->i30_edge_count; i++)
			matches += rh_edge_matches_link(ns, &ns->i30_edges[i],
				&ns->links[j]);
		if (matches != 1U) {
			errno = EPERM;
			return -1;
		}
	}
	if (unmatched_count != 1U || !unmatched ||
			rh_resolve_operations_parent_without_edge(census, unmatched,
				&operations) ||
			!rh_ref_equal(unmatched->parent, operations) ||
			unmatched->from_index_block ||
			(unmatched->entry_flags & (le16_to_cpu(INDEX_ENTRY_NODE) |
			 le16_to_cpu(INDEX_ENTRY_END))) ||
			unmatched->name_offset > ns->i30_name_arena_size ||
			!rh_ascii_name(ns->i30_name_arena + unmatched->name_offset,
				ns->i30_name_arena_size - unmatched->name_offset,
				unmatched->name_length, "operations.txt") ||
			unmatched->child.record >= census->raw.slot_count ||
			census->raw.slots[unmatched->child.record].state != RH_RAW_SLOT_FREE ||
			!unmatched->entry_length || (unmatched->entry_length & 7U) ||
			rh_i30_attribute(census, operations, &root)) {
		errno = EPERM;
		return -1;
	}
	mft.record = RH_FILE_MFT;
	mft.sequence = census->raw.slots[RH_FILE_MFT].sequence;
	if (rh_raw_mft_map_stream_range(&census->raw, mft, AT_DATA, NULL, 0,
			operations.record * RH_MFT_RECORD_BYTES, RH_MFT_RECORD_BYTES,
			&candidate->physical_record_offset))
		return -1;
	candidate->parent_record = operations.record;
	candidate->parent_sequence = operations.sequence;
	candidate->child_record = unmatched->child.record;
	candidate->child_sequence = unmatched->child.sequence;
	candidate->attribute_record_offset = root->record_offset;
	candidate->attribute_record_length = root->record_length;
	candidate->attribute_instance = root->instance;
	candidate->indexed_file_reference = unmatched->indexed_file_reference;
	candidate->entry_length = unmatched->entry_length;
	candidate->key_length = unmatched->key_length;
	candidate->name_namespace = unmatched->name_namespace;
	memcpy(candidate->evidence_hash, ns->census_hash, 32U);
	return 0;
}

int rh_namespace_operations_registry_derive(
		const struct rh_census_reader *reader,
		const struct rh_complete_census *census,
		struct rh_namespace_repair_candidate *candidate,
		unsigned char before[1024], unsigned char after[1024],
		struct rh_write_semantic_target *target)
{
	static const unsigned char i30[] = {'$', 0, 'I', 0, '3', 0, '0', 0};
	MFT_RECORD *mft;
	ATTR_RECORD *attribute;
	INDEX_ROOT *root;
	unsigned char *cursor, *end, *matched = NULL;
	uint32_t used, attr_length, value_length, index_length, allocated;
	size_t match_count = 0;

	if (!reader || !census || !candidate || !before || !after || !target ||
			rh_namespace_operations_registry_qualify(census, candidate) ||
			rh_census_reader_read_exact(reader, candidate->physical_record_offset,
				RH_MFT_RECORD_BYTES, before))
		return -1;
	memcpy(after, before, RH_MFT_RECORD_BYTES);
	if (ntfs_mst_post_read_fixup((NTFS_RECORD *)after, RH_MFT_RECORD_BYTES))
		return -1;
	mft = (MFT_RECORD *)after;
	used = le32_to_cpu(mft->bytes_in_use);
	if (mft->magic != magic_FILE ||
			le32_to_cpu(mft->mft_record_number) != candidate->parent_record ||
			le16_to_cpu(mft->sequence_number) != candidate->parent_sequence ||
			used > RH_MFT_RECORD_BYTES || used < candidate->attribute_record_offset +
				candidate->attribute_record_length)
		return -1;
	attribute = (ATTR_RECORD *)(after + candidate->attribute_record_offset);
	attr_length = le32_to_cpu(attribute->length);
	value_length = le32_to_cpu(attribute->value_length);
	if (attribute->type != AT_INDEX_ROOT || attribute->non_resident ||
			le16_to_cpu(attribute->instance) != candidate->attribute_instance ||
			attr_length != candidate->attribute_record_length ||
			attribute->name_length != 4U ||
			le16_to_cpu(attribute->name_offset) > attr_length ||
			8U > attr_length - le16_to_cpu(attribute->name_offset) ||
			memcmp((unsigned char *)attribute +
				le16_to_cpu(attribute->name_offset), i30, sizeof(i30)) ||
			le16_to_cpu(attribute->value_offset) > attr_length ||
			value_length > attr_length - le16_to_cpu(attribute->value_offset))
		return -1;
	root = (INDEX_ROOT *)((unsigned char *)attribute +
		le16_to_cpu(attribute->value_offset));
	index_length = le32_to_cpu(root->index.index_length);
	allocated = le32_to_cpu(root->index.allocated_size);
	if (root->index.ih_flags != SMALL_INDEX || index_length != allocated ||
			value_length != offsetof(INDEX_ROOT, index) + index_length ||
			le32_to_cpu(root->index.entries_offset) != sizeof(INDEX_HEADER) ||
			candidate->entry_length > index_length - sizeof(INDEX_HEADER))
		return -1;
	cursor = (unsigned char *)&root->index +
		le32_to_cpu(root->index.entries_offset);
	end = (unsigned char *)&root->index + index_length;
	while (cursor < end) {
		INDEX_ENTRY *entry = (INDEX_ENTRY *)cursor;
		uint16_t length, key_length, flags;

		if ((size_t)(end - cursor) < sizeof(INDEX_ENTRY_HEADER))
			return -1;
		length = le16_to_cpu(entry->length);
		key_length = le16_to_cpu(entry->key_length);
		flags = le16_to_cpu(entry->ie_flags);
		if (!length || (length & 7U) || length > (size_t)(end - cursor))
			return -1;
		if (!(flags & le16_to_cpu(INDEX_ENTRY_END)) &&
				le64_to_cpu(entry->indexed_file) ==
					candidate->indexed_file_reference &&
				length == candidate->entry_length &&
				key_length == candidate->key_length &&
				key_length >= offsetof(FILE_NAME_ATTR, file_name) &&
				key_length <= length - sizeof(INDEX_ENTRY_HEADER)) {
			FILE_NAME_ATTR *name = &entry->key.file_name;
			if (name->file_name_type == candidate->name_namespace &&
					rh_ascii_name((unsigned char *)&name->file_name,
						key_length - offsetof(FILE_NAME_ATTR, file_name),
						name->file_name_length, "operations.txt")) {
				matched = cursor;
				match_count++;
			}
		}
		cursor += length;
	}
	if (cursor != end || match_count != 1U || !matched ||
			candidate->entry_length > attr_length ||
			candidate->entry_length > value_length ||
			candidate->entry_length > index_length ||
			candidate->entry_length > allocated ||
			candidate->entry_length > used - (uint32_t)(matched - after))
		return -1;
	memmove(matched, matched + candidate->entry_length,
		used - (uint32_t)(matched - after) - candidate->entry_length);
	memset(after + used - candidate->entry_length, 0,
		candidate->entry_length);
	mft->bytes_in_use = cpu_to_le32(used - candidate->entry_length);
	attribute->length = cpu_to_le32(attr_length - candidate->entry_length);
	attribute->value_length = cpu_to_le32(value_length - candidate->entry_length);
	root->index.index_length = cpu_to_le32(index_length - candidate->entry_length);
	root->index.allocated_size = cpu_to_le32(allocated - candidate->entry_length);
	memset(target, 0, sizeof(*target));
	target->seal_version = 1U;
	target->object = RH_WRITE_TARGET_MFT_RECORD_PRIMARY;
	target->owner_mft_record = candidate->parent_record;
	target->owner_sequence = candidate->parent_sequence;
	target->attribute_instance = candidate->attribute_instance;
	target->attribute_type = AT_INDEX_ROOT;
	target->attribute_name_length = 4U;
	target->flags = RH_WRITE_TARGET_PRIMARY | RH_WRITE_TARGET_RESIDENT;
	rh_sha256(i30, sizeof(i30), target->attribute_name_hash);
	target->lowest_vcn = -1;
	target->logical_vcn = -1;
	target->lcn = -1;
	target->logical_offset = offsetof(MFT_RECORD, bytes_in_use);
	target->logical_length = used - offsetof(MFT_RECORD, bytes_in_use);
	target->semantic_target_offset = candidate->physical_record_offset +
		offsetof(MFT_RECORD, bytes_in_use);
	target->semantic_target_length = target->logical_length;
	if (ntfs_mst_pre_write_fixup((NTFS_RECORD *)after, RH_MFT_RECORD_BYTES) ||
			!rh_write_semantic_target_valid(RH_WRITE_INDEX_ROOT, target,
				candidate->physical_record_offset, RH_MFT_RECORD_BYTES, 0))
		return -1;
	return 0;
}

int rh_namespace_operations_registry_stage(
		const struct rh_census_reader *reader,
		const struct rh_complete_census *census, struct rh_writer *writer,
		size_t *operation_ordinal,
		struct rh_namespace_repair_candidate *candidate)
{
	unsigned char before[1024], after[1024];
	struct rh_write_semantic_target target;
	size_t checkpoint;

	if (operation_ordinal)
		*operation_ordinal = 0;
	if (!writer || !operation_ordinal || !candidate ||
			rh_namespace_operations_registry_derive(reader, census, candidate,
				before, after, &target))
		return -1;
	checkpoint = rh_writer_plan_checkpoint(writer);
	if (rh_writer_plan_typed(writer, RH_WRITE_INDEX_ROOT,
			candidate->physical_record_offset, sizeof(after), after, &target) ||
			writer->operation_count != checkpoint + 1U)
		return -1;
	*operation_ordinal = checkpoint + 1U;
	return 0;
}
