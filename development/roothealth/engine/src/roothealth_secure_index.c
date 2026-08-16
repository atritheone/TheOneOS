/* ROOTHEALTH_REPAIR_ROLE(DIAGNOSTIC) ROOTHEALTH_IO_ROLE(PLANNER) */
#include "config.h"

#include <errno.h>
#include <limits.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include "attrib.h"
#include "device.h"
#include "dir.h"
#include "endians.h"
#include "inode.h"
#include "layout.h"
#include "mst.h"
#include "roothealth_secure_index.h"
#include "roothealth_secure_raw.h"
#include "roothealth_secure_reader.h"
#include "runlist.h"

#define RH_SECURE_INDEX_BLOCK 4096U
#define RH_SECURE_INDEX_USA_OFFSET 40U
#define RH_SECURE_INDEX_USA_COUNT 9U
#define RH_SECURE_INDEX_ENTRY_OFFSET 64U

struct rh_secure_index_builder {
	const struct rh_secure_descriptor **ordered;
	size_t descriptor_count;
	int sdh;
	size_t leaf_entry_size;
	size_t node_entry_size;
	size_t leaf_capacity;
	size_t node_capacity;
	unsigned char *blocks;
	size_t block_capacity;
	size_t next_block;
};

static void rh_secure_index_name_hash(const char *name,
		unsigned char hash[32])
{
	unsigned char encoded[32];
	size_t length = strlen(name), i;

	memset(encoded, 0, sizeof(encoded));
	for (i = 0; i < length; i++)
		encoded[i * 2U] = (unsigned char)name[i];
	rh_sha256(encoded, length * 2U, hash);
}

static int rh_secure_index_sdh_compare(const void *left, const void *right)
{
	const struct rh_secure_descriptor *const *a = left;
	const struct rh_secure_descriptor *const *b = right;

	if ((*a)->hash != (*b)->hash)
		return (*a)->hash < (*b)->hash ? -1 : 1;
	if ((*a)->security_id != (*b)->security_id)
		return (*a)->security_id < (*b)->security_id ? -1 : 1;
	return 0;
}

static struct rh_secure_index_state *rh_secure_index_state(
		struct rh_secure_inspection *inspection, int sdh)
{
	return sdh ? &inspection->sdh_index : &inspection->sii_index;
}

static const struct rh_secure_index_state *rh_secure_index_state_const(
		const struct rh_secure_inspection *inspection, int sdh)
{
	return sdh ? &inspection->sdh_index : &inspection->sii_index;
}

static unsigned char **rh_secure_index_root_canonical(
		struct rh_secure_inspection *inspection, int sdh)
{
	return sdh ? &inspection->sdh_canonical : &inspection->sii_canonical;
}

static uint64_t *rh_secure_index_root_length(
		struct rh_secure_inspection *inspection, int sdh)
{
	return sdh ? &inspection->sdh_value_length :
		&inspection->sii_value_length;
}

static uint64_t *rh_secure_index_root_physical(
		struct rh_secure_inspection *inspection, int sdh)
{
	return sdh ? &inspection->sdh_semantic_physical :
		&inspection->sii_semantic_physical;
}

static uint16_t *rh_secure_index_root_instance(
		struct rh_secure_inspection *inspection, int sdh)
{
	return sdh ? &inspection->sdh_instance : &inspection->sii_instance;
}

static int *rh_secure_index_clean(struct rh_secure_inspection *inspection,
		int sdh)
{
	return sdh ? &inspection->sdh_clean : &inspection->sii_clean;
}

static unsigned char *rh_secure_index_current_hash(
		struct rh_secure_inspection *inspection, int sdh)
{
	return sdh ? inspection->sdh_current_hash : inspection->sii_current_hash;
}

static unsigned char *rh_secure_index_canonical_hash(
		struct rh_secure_inspection *inspection, int sdh)
{
	return sdh ? inspection->sdh_canonical_hash :
		inspection->sii_canonical_hash;
}

static int rh_secure_index_build_mapping(ntfs_volume *volume,
		struct rh_writer *writer, ntfs_attr *attribute, uint64_t maximum,
		uint16_t owner_sequence, uint16_t instance,
		struct rh_secure_mapping_slice **slices, size_t *slice_count,
		uint64_t *data_size)
{
	runlist_element *run;
	uint64_t expected_vcn = 0, covered = 0, allocated_clusters;

	if (!volume || !writer || !attribute || !owner_sequence ||
			!slices || !slice_count ||
			!data_size || !NAttrNonResident(attribute) ||
			attribute->data_flags || attribute->data_size <= 0 ||
			(uint64_t)attribute->data_size > SIZE_MAX ||
			(uint64_t)attribute->data_size > maximum ||
			attribute->initialized_size != attribute->data_size ||
			attribute->allocated_size < attribute->data_size ||
			(attribute->allocated_size % volume->cluster_size) ||
			ntfs_attr_map_whole_runlist(attribute)) {
		if (attribute && attribute->data_size > 0 &&
				(uint64_t)attribute->data_size > maximum)
			errno = E2BIG;
		return -1;
	}
	allocated_clusters = (uint64_t)attribute->allocated_size /
		volume->cluster_size;
	for (run = attribute->rl; run && run->length; run++) {
		uint64_t run_bytes, take, physical;
		struct rh_secure_mapping_slice *grown;

		if (run->vcn < 0 || run->lcn < 0 || run->length <= 0 ||
				(uint64_t)run->vcn != expected_vcn ||
				expected_vcn > allocated_clusters ||
				(uint64_t)run->length > allocated_clusters - expected_vcn ||
				(uint64_t)run->length > UINT64_MAX / volume->cluster_size ||
				(uint64_t)run->lcn > UINT64_MAX / volume->cluster_size)
			return -1;
		run_bytes = (uint64_t)run->length * volume->cluster_size;
		physical = (uint64_t)run->lcn * volume->cluster_size;
		if (physical > writer->device_size ||
				run_bytes > writer->device_size - physical)
			return -1;
		take = run_bytes;
		if (covered > (uint64_t)attribute->data_size)
			return -1;
		if (take > (uint64_t)attribute->data_size - covered)
			take = (uint64_t)attribute->data_size - covered;
		if (take) {
			if (*slice_count >= SIZE_MAX / sizeof(**slices)) {
				errno = EOVERFLOW;
				return -1;
			}
			if (rh_writer_range_excluded(writer, physical, take))
				return -1;
			grown = realloc(*slices,
				(*slice_count + 1U) * sizeof(**slices));
			if (!grown)
				return -1;
			*slices = grown;
			grown = &(*slices)[(*slice_count)++];
			grown->logical_offset = covered;
			grown->length = take;
			grown->physical_offset = physical;
			grown->logical_vcn = run->vcn;
			grown->lcn = run->lcn;
			grown->storage_mft_record = FILE_Secure;
			grown->storage_sequence = owner_sequence;
			grown->attribute_instance = instance;
			grown->lowest_vcn = 0;
			covered += take;
		}
		expected_vcn += (uint64_t)run->length;
	}
	if (!run || run->length || run->vcn < 0 || run->lcn != LCN_ENOENT ||
			(uint64_t)run->vcn != expected_vcn ||
			expected_vcn != allocated_clusters ||
			covered != (uint64_t)attribute->data_size || !*slice_count)
		return -1;
	*data_size = (uint64_t)attribute->data_size;
	return 0;
}

static int rh_secure_index_read_slices(
		const struct rh_secure_read_source *source,
		const struct rh_secure_mapping_slice *slices, size_t slice_count,
		unsigned char *bytes, uint64_t length)
{
	size_t i;

	for (i = 0; i < slice_count; i++) {
		const struct rh_secure_mapping_slice *slice = &slices[i];

		if (slice->logical_offset > length ||
				slice->length > length - slice->logical_offset ||
				slice->length > SIZE_MAX ||
				rh_secure_source_read(source, slice->physical_offset,
					(size_t)slice->length, bytes + slice->logical_offset))
			return -1;
	}
	return 0;
}

static int rh_secure_index_find_slice(
		const struct rh_secure_mapping_slice *slices, size_t slice_count,
		uint64_t logical, uint64_t length,
		const struct rh_secure_mapping_slice **slice_out, uint64_t *relative)
{
	size_t i;

	if (!length || logical > UINT64_MAX - length)
		return -1;
	for (i = 0; i < slice_count; i++) {
		const struct rh_secure_mapping_slice *slice = &slices[i];

		if (logical < slice->logical_offset ||
				logical - slice->logical_offset > slice->length ||
				length > slice->length - (logical - slice->logical_offset))
			continue;
		*slice_out = slice;
		*relative = logical - slice->logical_offset;
		return 0;
	}
	return -1;
}

static int rh_secure_index_mft_record_physical(ntfs_volume *volume,
		const struct rh_secure_read_source *source, uint64_t record,
		uint64_t *physical)
{
	runlist_element *run;
	uint64_t logical, vcn, within;

	if (!volume || !volume->mft_na || !rh_secure_source_valid(source) ||
			!physical ||
			volume->mft_record_size != 1024U ||
			record > UINT64_MAX / volume->mft_record_size ||
			ntfs_attr_map_whole_runlist(volume->mft_na))
		return -1;
	logical = record * volume->mft_record_size;
	vcn = logical / volume->cluster_size;
	within = logical % volume->cluster_size;
	for (run = volume->mft_na->rl; run && run->length; run++)
		if (run->vcn >= 0 && run->lcn >= 0 && run->length > 0 &&
				vcn >= (uint64_t)run->vcn &&
				vcn - (uint64_t)run->vcn < (uint64_t)run->length) {
			uint64_t lcn = (uint64_t)run->lcn + vcn -
				(uint64_t)run->vcn;
			uint64_t offset;
			int excluded;

			if (lcn > UINT64_MAX / volume->cluster_size)
				return -1;
			offset = lcn * volume->cluster_size + within;

			if ((offset & 1023U) || offset > rh_secure_source_size(source) ||
					1024U > rh_secure_source_size(source) - offset)
				return -1;
			excluded = rh_secure_source_excluded(source, offset, 1024U);
			if (excluded)
				return -1;
			*physical = offset;
			return 0;
		}
	return -1;
}

static void rh_secure_index_fill_entry(unsigned char *bytes, int sdh,
		const struct rh_secure_descriptor *descriptor, int node, uint64_t child)
{
	INDEX_ENTRY *entry = (INDEX_ENTRY *)bytes;
	size_t base_length = sdh ? 0x30U : 0x28U;
	SECURITY_DESCRIPTOR_HEADER *data;

	memset(bytes, 0, base_length + (node ? sizeof(leVCN) : 0U));
	entry->data_offset = cpu_to_le16(sdh ? 0x18U : 0x14U);
	entry->data_length = cpu_to_le16(0x14U);
	entry->length = cpu_to_le16((uint16_t)(base_length +
		(node ? sizeof(leVCN) : 0U)));
	entry->key_length = cpu_to_le16(sdh ? 8U : 4U);
	entry->ie_flags = node ? INDEX_ENTRY_NODE : 0;
	if (sdh) {
		SDH_INDEX_DATA *sdh_data;

		entry->key.sdh.hash = cpu_to_le32(descriptor->hash);
		entry->key.sdh.security_id = cpu_to_le32(descriptor->security_id);
		sdh_data = (SDH_INDEX_DATA *)(bytes + 0x18U);
		sdh_data->hash = cpu_to_le32(descriptor->hash);
		sdh_data->security_id = cpu_to_le32(descriptor->security_id);
		sdh_data->offset = cpu_to_le64(descriptor->offset);
		sdh_data->length = cpu_to_le32(descriptor->length);
		sdh_data->reserved_II = cpu_to_le32(0x00490049U);
	} else {
		entry->key.sii.security_id = cpu_to_le32(descriptor->security_id);
		data = (SECURITY_DESCRIPTOR_HEADER *)(bytes + 0x14U);
		data->hash = cpu_to_le32(descriptor->hash);
		data->security_id = cpu_to_le32(descriptor->security_id);
		data->offset = cpu_to_le64(descriptor->offset);
		data->length = cpu_to_le32(descriptor->length);
	}
	if (node)
		*(leVCN *)(bytes + base_length) = cpu_to_sle64((int64_t)child);
}

static void rh_secure_index_fill_end(unsigned char *bytes, int node,
		uint64_t child)
{
	INDEX_ENTRY_HEADER *entry = (INDEX_ENTRY_HEADER *)bytes;
	size_t length = sizeof(*entry) + (node ? sizeof(leVCN) : 0U);

	memset(bytes, 0, length);
	entry->length = cpu_to_le16((uint16_t)length);
	entry->flags = INDEX_ENTRY_END | (node ? INDEX_ENTRY_NODE : 0);
	if (node)
		*(leVCN *)(bytes + sizeof(*entry)) = cpu_to_sle64((int64_t)child);
}

static size_t rh_secure_index_subtree_max(
		const struct rh_secure_index_builder *builder, unsigned int height)
{
	size_t maximum = builder->leaf_capacity;
	unsigned int i;

	for (i = 0; i < height; i++) {
		if (maximum > (SIZE_MAX - builder->node_capacity) /
				(builder->node_capacity + 1U))
			return SIZE_MAX;
		maximum = builder->node_capacity +
			(builder->node_capacity + 1U) * maximum;
	}
	return maximum;
}

static int rh_secure_index_build_subtree(
		struct rh_secure_index_builder *builder, size_t first, size_t count,
		unsigned int height, uint64_t *vcn_out)
{
	INDEX_BLOCK *block;
	unsigned char *cursor;
	size_t vcn, remaining, position, child_count, child_max, i;

	if (!builder || !vcn_out || first > builder->descriptor_count ||
			count > builder->descriptor_count - first ||
			builder->next_block >= builder->block_capacity)
		return -1;
	vcn = builder->next_block++;
	block = (INDEX_BLOCK *)(builder->blocks + vcn * RH_SECURE_INDEX_BLOCK);
	memset(block, 0, RH_SECURE_INDEX_BLOCK);
	block->magic = magic_INDX;
	block->usa_ofs = cpu_to_le16(RH_SECURE_INDEX_USA_OFFSET);
	block->usa_count = cpu_to_le16(RH_SECURE_INDEX_USA_COUNT);
	block->lsn = cpu_to_sle64(0);
	block->index_block_vcn = cpu_to_sle64((int64_t)vcn);
	block->index.entries_offset = cpu_to_le32(40U);
	block->index.allocated_size = cpu_to_le32(4072U);
	memset(block->index.reserved, 0, sizeof(block->index.reserved));
	cursor = (unsigned char *)block + RH_SECURE_INDEX_ENTRY_OFFSET;
	if (!height) {
		if (count > builder->leaf_capacity)
			return -1;
		block->index.ih_flags = LEAF_NODE;
		for (i = 0; i < count; i++) {
			rh_secure_index_fill_entry(cursor, builder->sdh,
				builder->ordered[first + i], 0, 0);
			cursor += builder->leaf_entry_size;
		}
		rh_secure_index_fill_end(cursor, 0, 0);
		cursor += sizeof(INDEX_ENTRY_HEADER);
	} else {
		block->index.ih_flags = INDEX_NODE;
		child_max = rh_secure_index_subtree_max(builder, height - 1U);
		child_count = child_max == SIZE_MAX ? 1U :
			count / (child_max + 1U) + 1U;
		if (child_count > builder->node_capacity + 1U)
			return -1;
		remaining = count;
		position = first;
		for (i = 0; i < child_count; i++) {
			size_t separators_left = child_count - i - 1U;
			size_t child_entries = remaining - separators_left;
			uint64_t child_vcn;

			if (child_entries > child_max)
				child_entries = child_max;
			if (rh_secure_index_build_subtree(builder, position,
					child_entries, height - 1U, &child_vcn))
				return -1;
			position += child_entries;
			remaining -= child_entries;
			if (i + 1U < child_count) {
				if (!remaining)
					return -1;
				rh_secure_index_fill_entry(cursor, builder->sdh,
					builder->ordered[position], 1, child_vcn);
				cursor += builder->node_entry_size;
				position++;
				remaining--;
			} else {
				rh_secure_index_fill_end(cursor, 1, child_vcn);
				cursor += sizeof(INDEX_ENTRY_HEADER) + sizeof(leVCN);
			}
		}
		if (remaining)
			return -1;
	}
	if ((size_t)(cursor - (unsigned char *)&block->index) > 4072U)
		return -1;
	block->index.index_length = cpu_to_le32(
		(uint32_t)(cursor - (unsigned char *)&block->index));
	*vcn_out = vcn;
	return 0;
}

static int rh_secure_index_build_large(
		const struct rh_secure_inspection *inspection, int sdh,
		uint64_t root_length, uint64_t allocation_length,
		unsigned char **root_out, unsigned char **blocks_out,
		size_t *block_count_out)
{
	struct rh_secure_index_builder builder;
	const struct rh_secure_descriptor **ordered = NULL;
	INDEX_ROOT *root;
	unsigned char *root_bytes = NULL, *cursor;
	size_t root_capacity, root_entry_size, child_count, child_max;
	size_t remaining, position, i;
	unsigned int height = 1U;

	if (!inspection || !inspection->descriptor_count || !root_out ||
			!blocks_out || !block_count_out || root_length < 56U ||
			(root_length & 7U) || allocation_length < RH_SECURE_INDEX_BLOCK ||
			(allocation_length % RH_SECURE_INDEX_BLOCK) ||
			allocation_length > SIZE_MAX || inspection->descriptor_count >
				SIZE_MAX / sizeof(*ordered))
		return -1;
	memset(&builder, 0, sizeof(builder));
	builder.sdh = sdh;
	builder.descriptor_count = inspection->descriptor_count;
	builder.leaf_entry_size = sdh ? 0x30U : 0x28U;
	builder.node_entry_size = builder.leaf_entry_size + sizeof(leVCN);
	builder.leaf_capacity = (4032U - sizeof(INDEX_ENTRY_HEADER)) /
		builder.leaf_entry_size;
	builder.node_capacity = (4032U - sizeof(INDEX_ENTRY_HEADER) -
		sizeof(leVCN)) / builder.node_entry_size;
	builder.block_capacity = (size_t)(allocation_length /
		RH_SECURE_INDEX_BLOCK);
	ordered = calloc(inspection->descriptor_count, sizeof(*ordered));
	root_bytes = calloc(1, (size_t)root_length);
	builder.blocks = calloc(builder.block_capacity, RH_SECURE_INDEX_BLOCK);
	if (!ordered || !root_bytes || !builder.blocks)
		goto error;
	for (i = 0; i < inspection->descriptor_count; i++)
		ordered[i] = &inspection->descriptors[i];
	if (sdh)
		qsort(ordered, inspection->descriptor_count, sizeof(*ordered),
			rh_secure_index_sdh_compare);
	builder.ordered = ordered;
	root_entry_size = builder.node_entry_size;
	root_capacity = ((size_t)root_length - sizeof(INDEX_ROOT) -
		(sizeof(INDEX_ENTRY_HEADER) + sizeof(leVCN))) / root_entry_size;
	while (1) {
		size_t subtree = rh_secure_index_subtree_max(&builder, height - 1U);
		size_t maximum;

		if (subtree > (SIZE_MAX - root_capacity) / (root_capacity + 1U))
			maximum = SIZE_MAX;
		else
			maximum = root_capacity + (root_capacity + 1U) * subtree;
		if (inspection->descriptor_count <= maximum)
			break;
		if (height == UINT_MAX)
			goto error;
		height++;
	}
	root = (INDEX_ROOT *)root_bytes;
	root->type = AT_UNUSED;
	root->collation_rule = sdh ? COLLATION_NTOFS_SECURITY_HASH :
		COLLATION_NTOFS_ULONG;
	root->index_block_size = cpu_to_le32(RH_SECURE_INDEX_BLOCK);
	root->clusters_per_index_block = 1;
	memset(root->reserved, 0, sizeof(root->reserved));
	root->index.entries_offset = cpu_to_le32(sizeof(INDEX_HEADER));
	root->index.index_length = cpu_to_le32((uint32_t)root_length -
		offsetof(INDEX_ROOT, index));
	root->index.allocated_size = root->index.index_length;
	root->index.ih_flags = LARGE_INDEX;
	memset(root->index.reserved, 0, sizeof(root->index.reserved));
	cursor = root_bytes + sizeof(INDEX_ROOT);
	child_max = rh_secure_index_subtree_max(&builder, height - 1U);
	child_count = child_max == SIZE_MAX ? 1U :
		inspection->descriptor_count / (child_max + 1U) + 1U;
	if (child_count > root_capacity + 1U)
		goto error;
	remaining = inspection->descriptor_count;
	position = 0;
	for (i = 0; i < child_count; i++) {
		size_t separators_left = child_count - i - 1U;
		size_t child_entries = remaining - separators_left;
		uint64_t child_vcn;

		if (child_entries > child_max)
			child_entries = child_max;
		if (rh_secure_index_build_subtree(&builder, position,
				child_entries, height - 1U, &child_vcn))
			goto error;
		position += child_entries;
		remaining -= child_entries;
		if (i + 1U < child_count) {
			if (!remaining)
				goto error;
			rh_secure_index_fill_entry(cursor, sdh, ordered[position], 1,
				child_vcn);
			cursor += root_entry_size;
			position++;
			remaining--;
		} else {
			rh_secure_index_fill_end(cursor, 1, child_vcn);
			cursor += sizeof(INDEX_ENTRY_HEADER) + sizeof(leVCN);
		}
	}
	if (remaining || (size_t)(cursor - root_bytes) > root_length ||
		!builder.next_block)
		goto error;
	free(ordered);
	*root_out = root_bytes;
	*blocks_out = builder.blocks;
	*block_count_out = builder.next_block;
	return 0;
error:
	free(ordered);
	free(root_bytes);
	free(builder.blocks);
	return -1;
}

static int rh_secure_index_normalize_block(const unsigned char *raw,
		unsigned char normalized[RH_SECURE_INDEX_BLOCK])
{
	memcpy(normalized, raw, RH_SECURE_INDEX_BLOCK);
	if (ntfs_mst_post_read_fixup((NTFS_RECORD *)normalized,
			RH_SECURE_INDEX_BLOCK))
		return -1;
	memset(normalized + 8U, 0, 8U);
	memset(normalized + RH_SECURE_INDEX_USA_OFFSET, 0,
		RH_SECURE_INDEX_USA_COUNT * sizeof(le16));
	return 0;
}

static void rh_secure_index_normalize_canonical(unsigned char *block)
{
	memset(block + 8U, 0, 8U);
	memset(block + RH_SECURE_INDEX_USA_OFFSET, 0,
		RH_SECURE_INDEX_USA_COUNT * sizeof(le16));
}

static int rh_secure_index_composite_hash(
		struct rh_secure_inspection *inspection, int sdh)
{
	struct rh_secure_index_state *state = rh_secure_index_state(inspection, sdh);
	const unsigned char *root = sdh ? inspection->sdh_canonical :
		inspection->sii_canonical;
	uint64_t root_length = sdh ? inspection->sdh_value_length :
		inspection->sii_value_length;
	unsigned char *current = NULL, *canonical = NULL;
	size_t total, cursor, i;

	if (root_length > SIZE_MAX || state->bitmap_data_size > SIZE_MAX ||
			(size_t)root_length >
				SIZE_MAX - (size_t)state->bitmap_data_size ||
			state->canonical_block_count > (SIZE_MAX - (size_t)root_length -
				(size_t)state->bitmap_data_size) / RH_SECURE_INDEX_BLOCK)
		return -1;
	total = (size_t)root_length + state->canonical_block_count *
		RH_SECURE_INDEX_BLOCK + (size_t)state->bitmap_data_size;
	current = malloc(total);
	canonical = malloc(total);
	if (!current || !canonical)
		goto error;
	memcpy(current, state->root_current, (size_t)root_length);
	memcpy(canonical, root, (size_t)root_length);
	cursor = (size_t)root_length;
	for (i = 0; i < state->canonical_block_count; i++) {
		unsigned char normalized[RH_SECURE_INDEX_BLOCK];
		unsigned char expected[RH_SECURE_INDEX_BLOCK];

		memcpy(expected, state->canonical_blocks +
			i * RH_SECURE_INDEX_BLOCK, sizeof(expected));
		rh_secure_index_normalize_canonical(expected);
		if (rh_secure_index_normalize_block(state->allocation_current +
				i * RH_SECURE_INDEX_BLOCK, normalized))
			memcpy(normalized, state->allocation_current +
				i * RH_SECURE_INDEX_BLOCK, sizeof(normalized));
		memcpy(current + cursor, normalized, sizeof(normalized));
		memcpy(canonical + cursor, expected, sizeof(expected));
		cursor += sizeof(expected);
	}
	memcpy(current + cursor, state->bitmap_current,
		(size_t)state->bitmap_data_size);
	memcpy(canonical + cursor, state->bitmap_canonical,
		(size_t)state->bitmap_data_size);
	rh_sha256(current, total, rh_secure_index_current_hash(inspection, sdh));
	rh_sha256(canonical, total,
		rh_secure_index_canonical_hash(inspection, sdh));
	free(current);
	free(canonical);
	return 0;
error:
	free(current);
	free(canonical);
	return -1;
}

static int rh_secure_index_attr_record(ntfs_inode *inode, ATTR_TYPES type,
		const ntfschar *name, ATTR_RECORD **attribute_out,
		ntfs_attr_search_ctx **search_out)
{
	ntfs_attr_search_ctx *search;

	search = ntfs_attr_get_search_ctx(inode, NULL);
	if (!search || ntfs_attr_lookup(type, name, 4, CASE_SENSITIVE, 0, NULL, 0,
			search) || !search->ntfs_ino || !search->attr) {
		if (search)
			ntfs_attr_put_search_ctx(search);
		return -1;
	}
	*attribute_out = search->attr;
	*search_out = search;
	return 0;
}

static int rh_secure_index_inspect_common(ntfs_volume *volume,
		const struct rh_secure_read_source *source, ntfs_inode *inode,
		struct rh_secure_inspection *inspection, int sdh)
{
	struct rh_writer *writer = source ? source->writer : NULL;
	ntfschar *name = sdh ? NTFS_INDEX_SDH : NTFS_INDEX_SII;
	struct rh_secure_index_state *state;
	ntfs_attr_search_ctx *root_search = NULL, *bitmap_search = NULL;
	ATTR_RECORD *root_attribute = NULL, *bitmap_attribute = NULL;
	ntfs_attr *allocation = NULL, *bitmap = NULL;
	unsigned char **root_canonical;
	uint64_t *root_length, *root_physical;
	uint64_t expected_root_length;
	uint16_t *root_instance;
	uint32_t attr_offset, attr_length, value_offset, value_length;
	uint64_t root_record_physical;
	int has_allocation, has_bitmap, result = -1;
	size_t i;

	if (!volume || !rh_secure_source_valid(source) || !inode || !inspection)
		return -1;
	state = rh_secure_index_state(inspection, sdh);
	root_canonical = rh_secure_index_root_canonical(inspection, sdh);
	root_length = rh_secure_index_root_length(inspection, sdh);
	expected_root_length = *root_length;
	root_physical = rh_secure_index_root_physical(inspection, sdh);
	root_instance = rh_secure_index_root_instance(inspection, sdh);
	if (rh_secure_index_attr_record(inode, AT_INDEX_ROOT, name,
			&root_attribute, &root_search))
		goto out;
	if (!root_search->ntfs_ino || !root_search->ntfs_ino->mrec ||
			!le16_to_cpu(root_search->ntfs_ino->mrec->sequence_number) ||
			(root_search->ntfs_ino != inode && !inspection->raw_mft_census) ||
			rh_secure_index_mft_record_physical(volume, source,
				root_search->ntfs_ino->mft_no, &root_record_physical))
		goto out;
	attr_offset = (uint32_t)((unsigned char *)root_attribute -
		(unsigned char *)root_search->ntfs_ino->mrec);
	attr_length = le32_to_cpu(root_attribute->length);
	value_offset = le16_to_cpu(root_attribute->value_offset);
	value_length = le32_to_cpu(root_attribute->value_length);
	if (root_attribute->non_resident || root_attribute->flags ||
			root_attribute->name_length != 4U ||
			root_attribute->resident_flags ||
			attr_length < sizeof(ATTR_RECORD) || (attr_length & 7U) ||
			value_offset > attr_length || value_length > attr_length - value_offset ||
			attr_offset > 1024U || attr_length > 1024U - attr_offset ||
			root_record_physical > UINT64_MAX - attr_offset -
				value_offset)
		goto out;
	if (inspection->raw_mft_census) {
		struct rh_secure_raw_resident raw_resident;
		struct rh_raw_mft_ref owner = {
			FILE_Secure, inspection->owner_sequence
		};

		if (rh_secure_raw_find_resident(inspection->raw_mft_census, owner,
				AT_INDEX_ROOT, (const unsigned char *)name, 4,
				&raw_resident) || raw_resident.storage_mft_record !=
					root_search->ntfs_ino->mft_no ||
				raw_resident.storage_sequence != le16_to_cpu(
					root_search->ntfs_ino->mrec->sequence_number) ||
				raw_resident.attribute_instance !=
					le16_to_cpu(root_attribute->instance) ||
				raw_resident.record_offset != attr_offset ||
				raw_resident.record_length != attr_length ||
				raw_resident.value_offset != value_offset ||
				raw_resident.value_length != value_length)
			goto out;
	}
	*root_instance = le16_to_cpu(root_attribute->instance);
	*root_physical = root_record_physical + attr_offset +
		value_offset;
	state->root_storage_mft_record = root_search->ntfs_ino->mft_no;
	state->root_storage_sequence = le16_to_cpu(
		root_search->ntfs_ino->mrec->sequence_number);
	state->root_record_physical = root_record_physical;
	*root_length = value_length;
	state->root_current = malloc(value_length);
	if (!state->root_current)
		goto out;
	memcpy(state->root_current, (unsigned char *)root_attribute + value_offset,
		value_length);
	has_allocation = ntfs_attr_exist(inode, AT_INDEX_ALLOCATION, name, 4);
	has_bitmap = ntfs_attr_exist(inode, AT_BITMAP, name, 4);
	if (!!has_allocation != !!has_bitmap)
		goto out;
	if (!has_allocation) {
		if (!*root_canonical || value_length != expected_root_length ||
				value_length < sizeof(INDEX_ROOT) + sizeof(INDEX_ENTRY_HEADER))
			goto out;
		state->large = 0;
		state->root_clean = !memcmp(state->root_current, *root_canonical,
			value_length);
		state->allocation_clean = 1;
		state->bitmap_clean = 1;
		state->bitmap_data_size = 0;
		rh_sha256(state->root_current, value_length,
			rh_secure_index_current_hash(inspection, sdh));
		rh_sha256(*root_canonical, value_length,
			rh_secure_index_canonical_hash(inspection, sdh));
		*rh_secure_index_clean(inspection, sdh) = state->root_clean;
		result = 0;
		goto out;
	}
	state->large = 1;
	if (value_length < 56U || (value_length & 7U))
		goto out;
	if (rh_secure_index_attr_record(inode, AT_INDEX_ALLOCATION, name,
			&bitmap_attribute, &bitmap_search))
		goto out;
	if (!bitmap_attribute->non_resident || bitmap_attribute->flags ||
			bitmap_attribute->name_length != 4U)
		goto out;
	state->allocation_instance = le16_to_cpu(bitmap_attribute->instance);
	ntfs_attr_put_search_ctx(bitmap_search);
	bitmap_search = NULL;
	bitmap_attribute = NULL;
	allocation = ntfs_attr_open(inode, AT_INDEX_ALLOCATION, name, 4);
	if (!allocation || allocation->type != AT_INDEX_ALLOCATION ||
			allocation->name_len != 4U)
		goto out;
	if (inspection->raw_mft_census) {
		struct rh_raw_mft_ref owner = {
			FILE_Secure, inspection->owner_sequence
		};

		if ((writer ? rh_secure_raw_build_mapping(
				inspection->raw_mft_census, writer, owner,
				AT_INDEX_ALLOCATION, (const unsigned char *)name, 4,
				RH_SECURE_INDEX_BLOCK, rh_secure_source_size(source),
				&state->allocation_slices, &state->allocation_slice_count,
				&state->allocation_data_size) :
				rh_secure_raw_build_mapping_reader(
				inspection->raw_mft_census, source->reader, owner,
				AT_INDEX_ALLOCATION, (const unsigned char *)name, 4,
				RH_SECURE_INDEX_BLOCK, rh_secure_source_size(source),
				&state->allocation_slices, &state->allocation_slice_count,
				&state->allocation_data_size)))
			goto out;
		state->allocation_instance =
			state->allocation_slices[0].attribute_instance;
	} else if (!writer || rh_secure_index_build_mapping(volume, writer,
			allocation,
			writer->device_size, inspection->owner_sequence,
			state->allocation_instance, &state->allocation_slices,
			&state->allocation_slice_count, &state->allocation_data_size))
		goto out;
	if (state->allocation_data_size % RH_SECURE_INDEX_BLOCK)
		goto out;
	state->allocation_current = malloc((size_t)state->allocation_data_size);
	if (!state->allocation_current || rh_secure_index_read_slices(source,
			state->allocation_slices, state->allocation_slice_count,
			state->allocation_current, state->allocation_data_size))
		goto out;
	if (rh_secure_index_attr_record(inode, AT_BITMAP, name, &bitmap_attribute,
			&bitmap_search))
		goto out;
	state->bitmap_instance = le16_to_cpu(bitmap_attribute->instance);
	if (bitmap_attribute->flags ||
			bitmap_attribute->name_length != 4U)
		goto out;
	if (!bitmap_attribute->non_resident) {
		uint64_t bitmap_record_physical;
		uint32_t bitmap_attr_length = le32_to_cpu(bitmap_attribute->length);
		uint32_t bitmap_value_offset =
			le16_to_cpu(bitmap_attribute->value_offset);
		uint32_t bitmap_value_length =
			le32_to_cpu(bitmap_attribute->value_length);
		uint32_t bitmap_attr_offset = (uint32_t)(
			(unsigned char *)bitmap_attribute -
			(unsigned char *)bitmap_search->ntfs_ino->mrec);

		if (!bitmap_search->ntfs_ino || !bitmap_search->ntfs_ino->mrec ||
				!le16_to_cpu(bitmap_search->ntfs_ino->mrec->sequence_number) ||
				(bitmap_search->ntfs_ino != inode &&
				 !inspection->raw_mft_census) ||
				rh_secure_index_mft_record_physical(volume, source,
					bitmap_search->ntfs_ino->mft_no,
					&bitmap_record_physical) ||
				bitmap_attribute->resident_flags ||
				bitmap_value_offset > bitmap_attr_length ||
				bitmap_value_length > bitmap_attr_length - bitmap_value_offset ||
				!bitmap_value_length || bitmap_attr_offset > 1024U ||
				bitmap_attr_length > 1024U - bitmap_attr_offset ||
				bitmap_record_physical > UINT64_MAX -
					bitmap_attr_offset - bitmap_value_offset)
			goto out;
		if (inspection->raw_mft_census) {
			struct rh_secure_raw_resident raw_resident;
			struct rh_raw_mft_ref owner = {
				FILE_Secure, inspection->owner_sequence
			};

			if (rh_secure_raw_find_resident(inspection->raw_mft_census,
					owner, AT_BITMAP, (const unsigned char *)name, 4,
					&raw_resident) || raw_resident.storage_mft_record !=
						bitmap_search->ntfs_ino->mft_no ||
					raw_resident.storage_sequence != le16_to_cpu(
						bitmap_search->ntfs_ino->mrec->sequence_number) ||
					raw_resident.attribute_instance !=
						le16_to_cpu(bitmap_attribute->instance) ||
					raw_resident.record_offset != bitmap_attr_offset ||
					raw_resident.record_length != bitmap_attr_length ||
					raw_resident.value_offset != bitmap_value_offset ||
					raw_resident.value_length != bitmap_value_length)
				goto out;
		}
		state->bitmap_resident = 1;
		state->bitmap_data_size = bitmap_value_length;
		state->bitmap_semantic_physical = bitmap_record_physical +
			bitmap_attr_offset + bitmap_value_offset;
		state->bitmap_storage_mft_record = bitmap_search->ntfs_ino->mft_no;
		state->bitmap_storage_sequence = le16_to_cpu(
			bitmap_search->ntfs_ino->mrec->sequence_number);
		state->bitmap_record_physical = bitmap_record_physical;
		state->bitmap_current = malloc(bitmap_value_length);
		if (!state->bitmap_current)
			goto out;
		memcpy(state->bitmap_current,
			(unsigned char *)bitmap_attribute + bitmap_value_offset,
			bitmap_value_length);
	} else {
		state->bitmap_resident = 0;
		ntfs_attr_put_search_ctx(bitmap_search);
		bitmap_search = NULL;
		bitmap = ntfs_attr_open(inode, AT_BITMAP, name, 4);
		if (!bitmap || bitmap->type != AT_BITMAP || bitmap->name_len != 4U)
			goto out;
		if (inspection->raw_mft_census) {
			struct rh_raw_mft_ref owner = {
				FILE_Secure, inspection->owner_sequence
			};

			if ((writer ? rh_secure_raw_build_mapping(
					inspection->raw_mft_census, writer, owner, AT_BITMAP,
					(const unsigned char *)name, 4, 1U,
					rh_secure_source_size(source), &state->bitmap_slices,
					&state->bitmap_slice_count, &state->bitmap_data_size) :
					rh_secure_raw_build_mapping_reader(
					inspection->raw_mft_census, source->reader, owner,
					AT_BITMAP, (const unsigned char *)name, 4, 1U,
					rh_secure_source_size(source), &state->bitmap_slices,
					&state->bitmap_slice_count, &state->bitmap_data_size)))
				goto out;
			state->bitmap_instance =
				state->bitmap_slices[0].attribute_instance;
		} else if (!writer || rh_secure_index_build_mapping(volume, writer,
				bitmap,
				writer->device_size, inspection->owner_sequence,
				state->bitmap_instance, &state->bitmap_slices,
				&state->bitmap_slice_count, &state->bitmap_data_size))
			goto out;
		state->bitmap_current = malloc((size_t)state->bitmap_data_size);
		if (!state->bitmap_current || rh_secure_index_read_slices(source,
				state->bitmap_slices, state->bitmap_slice_count,
				state->bitmap_current, state->bitmap_data_size))
			goto out;
	}
	free(*root_canonical);
	*root_canonical = NULL;
	if (rh_secure_index_build_large(inspection, sdh, value_length,
			state->allocation_data_size, root_canonical,
			&state->canonical_blocks, &i))
		goto out;
	state->canonical_block_count = i;
	if (state->canonical_block_count > SIZE_MAX - 7U ||
			state->canonical_block_count > state->allocation_data_size /
			RH_SECURE_INDEX_BLOCK || state->bitmap_data_size > SIZE_MAX ||
			(state->canonical_block_count + 7U) / 8U >
				state->bitmap_data_size)
		goto out;
	state->bitmap_canonical = calloc(1, (size_t)state->bitmap_data_size);
	state->dirty_blocks = calloc(state->canonical_block_count, 1U);
	if (!state->bitmap_canonical || !state->dirty_blocks)
		goto out;
	for (i = 0; i < state->canonical_block_count; i++)
		state->bitmap_canonical[i / 8U] |= (unsigned char)(1U << (i & 7U));
	state->root_clean = !memcmp(state->root_current, *root_canonical,
		value_length);
	state->allocation_clean = 1;
	for (i = 0; i < state->canonical_block_count; i++) {
		unsigned char normalized[RH_SECURE_INDEX_BLOCK];
		unsigned char expected[RH_SECURE_INDEX_BLOCK];

		memcpy(expected, state->canonical_blocks +
			i * RH_SECURE_INDEX_BLOCK, sizeof(expected));
		rh_secure_index_normalize_canonical(expected);
		if (rh_secure_index_normalize_block(state->allocation_current +
				i * RH_SECURE_INDEX_BLOCK, normalized) ||
				memcmp(normalized, expected, sizeof(expected))) {
			state->dirty_blocks[i] = 1;
			state->allocation_clean = 0;
		}
	}
	state->bitmap_clean = !memcmp(state->bitmap_current,
		state->bitmap_canonical, (size_t)state->bitmap_data_size);
	if (rh_secure_index_composite_hash(inspection, sdh))
		goto out;
	*rh_secure_index_clean(inspection, sdh) = state->root_clean &&
		state->allocation_clean && state->bitmap_clean;
	result = 0;
out:
	if (bitmap)
		ntfs_attr_close(bitmap);
	if (allocation)
		ntfs_attr_close(allocation);
	if (bitmap_search)
		ntfs_attr_put_search_ctx(bitmap_search);
	if (root_search)
		ntfs_attr_put_search_ctx(root_search);
	if (result) {
		rh_secure_index_state_destroy(state);
		if (!errno)
			errno = ENOTSUP;
	}
	return result;
}

int rh_secure_index_inspect(ntfs_volume *volume, struct rh_writer *writer,
		ntfs_inode *inode, struct rh_secure_inspection *inspection, int sdh)
{
	const struct rh_secure_read_source source = { writer, NULL };

	return rh_secure_index_inspect_common(volume, &source, inode, inspection,
		sdh);
}

int rh_secure_index_inspect_reader(ntfs_volume *volume,
		const struct rh_census_reader *reader, ntfs_inode *inode,
		struct rh_secure_inspection *inspection, int sdh)
{
	const struct rh_secure_read_source source = { NULL, reader };

	return rh_secure_index_inspect_common(volume, &source, inode, inspection,
		sdh);
}

void rh_secure_index_state_destroy(struct rh_secure_index_state *state)
{
	if (!state)
		return;
	free(state->root_current);
	free(state->allocation_current);
	free(state->canonical_blocks);
	free(state->bitmap_current);
	free(state->bitmap_canonical);
	free(state->dirty_blocks);
	free(state->allocation_slices);
	free(state->bitmap_slices);
	memset(state, 0, sizeof(*state));
}

static int rh_secure_index_action_append(
		struct rh_secure_index_action *action,
		const struct rh_overlay_expected_write *write,
		uint32_t mst_block_size, const unsigned char *bytes)
{
	struct rh_overlay_expected_write *grown_writes;
	struct rh_secure_overlay_operation *grown_operations;
	unsigned char **grown_after;
	unsigned char *operation_bytes = NULL, *expected_after = NULL;
	size_t i;

	if (!action || !write || !write->length || write->length > SIZE_MAX ||
			(mst_block_size && write->length % mst_block_size))
		return -1;
	if (action->count >= SIZE_MAX / sizeof(*grown_writes) ||
			action->count >= SIZE_MAX / sizeof(*grown_operations) ||
			action->count >= SIZE_MAX / sizeof(*grown_after)) {
		errno = EOVERFLOW;
		return -1;
	}
	operation_bytes = malloc((size_t)write->length);
	expected_after = malloc((size_t)write->length);
	if (!operation_bytes || !expected_after)
		goto error;
	memcpy(operation_bytes, bytes, (size_t)write->length);
	memcpy(expected_after, bytes, (size_t)write->length);
	if (mst_block_size)
		for (i = 0; i < write->length / mst_block_size; i++)
			if (ntfs_mst_pre_write_fixup((NTFS_RECORD *)(expected_after +
					i * mst_block_size), mst_block_size))
				goto error;
	grown_writes = realloc(action->writes,
		(action->count + 1U) * sizeof(*grown_writes));
	if (!grown_writes)
		goto error;
	action->writes = grown_writes;
	grown_operations = realloc(action->operations,
		(action->count + 1U) * sizeof(*grown_operations));
	if (!grown_operations)
		goto error;
	action->operations = grown_operations;
	grown_after = realloc(action->expected_after,
		(action->count + 1U) * sizeof(*grown_after));
	if (!grown_after)
		goto error;
	action->expected_after = grown_after;
	action->writes[action->count] = *write;
	action->operations[action->count].physical = write->offset;
	action->operations[action->count].length = (size_t)write->length;
	action->operations[action->count].mst_block_size = mst_block_size;
	action->operations[action->count].bytes = operation_bytes;
	action->expected_after[action->count] = expected_after;
	action->count++;
	return 0;
error:
	free(operation_bytes);
	free(expected_after);
	return -1;
}

static void rh_secure_index_nonresident_target(
		const struct rh_secure_inspection *inspection, int sdh,
		uint16_t instance, uint32_t type,
		const struct rh_secure_mapping_slice *slice, uint64_t relative,
		uint64_t length, struct rh_write_semantic_target *target)
{
	uint64_t cluster_delta = relative / RH_SECURE_INDEX_BLOCK;

	memset(target, 0, sizeof(*target));
	target->seal_version = 1;
	target->object = RH_WRITE_TARGET_NONRESIDENT_ATTRIBUTE;
	target->owner_mft_record = FILE_Secure;
	target->owner_sequence = inspection->owner_sequence;
	target->attribute_instance = slice->attribute_instance ?
		slice->attribute_instance : instance;
	target->attribute_type = type;
	target->attribute_name_length = 4;
	target->flags = RH_WRITE_TARGET_NONRESIDENT;
	rh_secure_index_name_hash(sdh ? "$SDH" : "$SII",
		target->attribute_name_hash);
	target->lowest_vcn = slice->lowest_vcn;
	target->logical_vcn = slice->logical_vcn + (int64_t)cluster_delta;
	target->logical_offset = slice->logical_offset + relative;
	target->logical_length = length;
	target->semantic_target_offset = slice->physical_offset + relative;
	target->semantic_target_length = length;
	target->lcn = slice->lcn + (int64_t)cluster_delta;
}

static void rh_secure_index_resident_target(
		const struct rh_secure_inspection *inspection, int sdh,
		uint16_t instance, uint32_t type, uint64_t semantic_physical,
		uint64_t semantic_length, struct rh_write_semantic_target *target)
{
	memset(target, 0, sizeof(*target));
	target->seal_version = 1;
	target->object = RH_WRITE_TARGET_MFT_RECORD_PRIMARY;
	target->owner_mft_record = FILE_Secure;
	target->owner_sequence = inspection->owner_sequence;
	target->attribute_instance = instance;
	target->attribute_type = type;
	target->attribute_name_length = 4;
	target->flags = RH_WRITE_TARGET_PRIMARY | RH_WRITE_TARGET_RESIDENT;
	rh_secure_index_name_hash(sdh ? "$SDH" : "$SII",
		target->attribute_name_hash);
	target->lowest_vcn = -1;
	target->logical_vcn = -1;
	target->logical_offset = 0;
	target->logical_length = semantic_length;
	target->semantic_target_offset = semantic_physical;
	target->semantic_target_length = semantic_length;
	target->lcn = -1;
}

static int rh_secure_index_find_resident(ntfs_inode *inode,
		ATTR_TYPES type, const ntfschar *name, uint16_t instance,
		uint64_t storage_record, uint16_t storage_sequence,
		uint64_t expected_physical, uint64_t mft_physical,
		uint32_t *value_offset_out, uint32_t *value_length_out,
		unsigned char logical_record[1024])
{
	ntfs_attr_search_ctx *search = NULL;
	ATTR_RECORD *attribute = NULL;
	uint32_t attr_offset, attr_length, value_offset, value_length;
	int result = -1;

	if (rh_secure_index_attr_record(inode, type, name, &attribute, &search))
		return -1;
	attr_offset = (uint32_t)((unsigned char *)attribute -
		(unsigned char *)search->ntfs_ino->mrec);
	attr_length = le32_to_cpu(attribute->length);
	value_offset = le16_to_cpu(attribute->value_offset);
	value_length = le32_to_cpu(attribute->value_length);
	if (search->ntfs_ino && search->ntfs_ino->mrec &&
			search->ntfs_ino->mft_no == storage_record &&
			le16_to_cpu(search->ntfs_ino->mrec->sequence_number) ==
				storage_sequence &&
			!attribute->non_resident && !attribute->flags &&
			le16_to_cpu(attribute->instance) == instance &&
			value_offset <= attr_length && value_length <= attr_length - value_offset &&
			attr_offset <= 1024U && attr_length <= 1024U - attr_offset &&
			mft_physical + attr_offset + value_offset == expected_physical) {
		*value_offset_out = attr_offset + value_offset;
		*value_length_out = value_length;
		memcpy(logical_record, search->ntfs_ino->mrec, 1024U);
		result = 0;
	}
	ntfs_attr_put_search_ctx(search);
	return result;
}

static void rh_secure_index_seed_mst(unsigned char *logical,
		const unsigned char *raw, size_t block_size)
{
	unsigned char current[RH_SECURE_INDEX_BLOCK];

	if (block_size != RH_SECURE_INDEX_BLOCK)
		return;
	memcpy(current, raw, block_size);
	if (!ntfs_mst_post_read_fixup((NTFS_RECORD *)current, block_size)) {
		memcpy(logical + 8U, current + 8U, 8U);
		memcpy(logical + RH_SECURE_INDEX_USA_OFFSET,
			current + RH_SECURE_INDEX_USA_OFFSET, sizeof(le16));
	}
}

static int rh_secure_index_prepare_allocation(
		const struct rh_secure_inspection *inspection, int sdh,
		struct rh_secure_index_action *action)
{
	const struct rh_secure_index_state *state =
		rh_secure_index_state_const(inspection, sdh);
	size_t block = 0;

	while (block < state->canonical_block_count) {
		const struct rh_secure_mapping_slice *slice;
		struct rh_overlay_expected_write write;
		uint64_t logical, relative;
		size_t end, i;
		unsigned char *logical_bytes;

		while (block < state->canonical_block_count &&
				!state->dirty_blocks[block])
			block++;
		if (block == state->canonical_block_count)
			break;
		logical = (uint64_t)block * RH_SECURE_INDEX_BLOCK;
		if (rh_secure_index_find_slice(state->allocation_slices,
				state->allocation_slice_count, logical,
				RH_SECURE_INDEX_BLOCK, &slice, &relative))
			return -1;
		end = block + 1U;
		while (end < state->canonical_block_count &&
				state->dirty_blocks[end] &&
				end - block < RH_SECURE_BATCH_MAX_OPERATIONS &&
				(uint64_t)(end + 1U) * RH_SECURE_INDEX_BLOCK <=
					slice->logical_offset + slice->length)
			end++;
		logical_bytes = malloc((end - block) * RH_SECURE_INDEX_BLOCK);
		if (!logical_bytes)
			return -1;
		for (i = block; i < end; i++) {
			unsigned char *target = logical_bytes +
				(i - block) * RH_SECURE_INDEX_BLOCK;

			memcpy(target, state->canonical_blocks +
				i * RH_SECURE_INDEX_BLOCK, RH_SECURE_INDEX_BLOCK);
			rh_secure_index_seed_mst(target, state->allocation_current +
				i * RH_SECURE_INDEX_BLOCK, RH_SECURE_INDEX_BLOCK);
		}
		memset(&write, 0, sizeof(write));
		rh_secure_index_nonresident_target(inspection, sdh,
			state->allocation_instance, AT_INDEX_ALLOCATION, slice, relative,
			(uint64_t)(end - block) * RH_SECURE_INDEX_BLOCK, &write.target);
		write.offset = write.target.semantic_target_offset;
		write.length = write.target.semantic_target_length;
		if (!rh_write_semantic_target_valid(sdh ? RH_WRITE_SECURE_SDH :
				RH_WRITE_SECURE_SII, &write.target, write.offset,
				(size_t)write.length, 0) ||
				rh_secure_index_action_append(action, &write,
					RH_SECURE_INDEX_BLOCK, logical_bytes)) {
			free(logical_bytes);
			return -1;
		}
		free(logical_bytes);
		block = end;
	}
	return 0;
}

static int rh_secure_index_prepare_nonresident_bitmap(
		const struct rh_secure_inspection *inspection, int sdh,
		struct rh_secure_index_action *action)
{
	const struct rh_secure_index_state *state =
		rh_secure_index_state_const(inspection, sdh);
	uint64_t cursor = 0;

	while (cursor < state->bitmap_data_size) {
		const struct rh_secure_mapping_slice *slice;
		struct rh_overlay_expected_write write;
		uint64_t start, end, relative;

		while (cursor < state->bitmap_data_size &&
				state->bitmap_current[cursor] == state->bitmap_canonical[cursor])
			cursor++;
		if (cursor == state->bitmap_data_size)
			break;
		start = cursor;
		if (rh_secure_index_find_slice(state->bitmap_slices,
				state->bitmap_slice_count, start, 1U, &slice, &relative))
			return -1;
		while (cursor < state->bitmap_data_size &&
				cursor < slice->logical_offset + slice->length &&
				state->bitmap_current[cursor] != state->bitmap_canonical[cursor])
			cursor++;
		end = cursor;
		memset(&write, 0, sizeof(write));
		rh_secure_index_nonresident_target(inspection, sdh,
			state->bitmap_instance, AT_BITMAP, slice, relative, end - start,
			&write.target);
		write.offset = write.target.semantic_target_offset;
		write.length = write.target.semantic_target_length;
		if (!rh_write_semantic_target_valid(sdh ? RH_WRITE_SECURE_SDH :
				RH_WRITE_SECURE_SII, &write.target, write.offset,
				(size_t)write.length, 0) ||
				rh_secure_index_action_append(action, &write, 0,
					state->bitmap_canonical + start))
			return -1;
	}
	return 0;
}

int rh_secure_index_prepare_action(ntfs_volume *volume,
		const struct rh_secure_inspection *inspection, int sdh,
		struct rh_secure_index_action *action)
{
	const struct rh_secure_index_state *state;
	ntfschar *name = sdh ? NTFS_INDEX_SDH : NTFS_INDEX_SII;
	const unsigned char *root_canonical = sdh ? inspection->sdh_canonical :
		inspection->sii_canonical;
	uint64_t root_length = sdh ? inspection->sdh_value_length :
		inspection->sii_value_length;
	uint64_t root_physical = sdh ? inspection->sdh_semantic_physical :
		inspection->sii_semantic_physical;
	uint16_t root_instance = sdh ? inspection->sdh_instance :
		inspection->sii_instance;
	ntfs_inode *inode = NULL;
	unsigned char logical_record[1024];
	uint32_t value_offset, value_length;
	struct rh_overlay_expected_write write;
	int result = -1;

	if (!volume || !inspection || !action || !root_canonical ||
			root_length > SIZE_MAX)
		return -1;
	memset(action, 0, sizeof(*action));
	state = rh_secure_index_state_const(inspection, sdh);
	if (state->large && !state->allocation_clean &&
			rh_secure_index_prepare_allocation(inspection, sdh, action))
		goto out;
	if (state->large && !state->bitmap_resident && !state->bitmap_clean &&
			rh_secure_index_prepare_nonresident_bitmap(inspection, sdh, action))
		goto out;
	if (state->root_clean && (!state->large || !state->bitmap_resident ||
			state->bitmap_clean)) {
		result = 0;
		goto out;
	}
	inode = ntfs_inode_open(volume, FILE_Secure);
	if (!inode || !inode->mrec || inode->mft_no != FILE_Secure ||
			le16_to_cpu(inode->mrec->sequence_number) !=
				inspection->owner_sequence)
		goto out;
	if (!state->root_clean) {
		if (rh_secure_index_find_resident(inode, AT_INDEX_ROOT, name,
				root_instance, state->root_storage_mft_record,
				state->root_storage_sequence, root_physical,
				state->root_record_physical, &value_offset, &value_length,
				logical_record) || value_length != root_length)
			goto out;
		memcpy(logical_record + value_offset, root_canonical,
			(size_t)root_length);
		memset(&write, 0, sizeof(write));
		rh_secure_index_resident_target(inspection, sdh, root_instance,
			AT_INDEX_ROOT, root_physical, root_length, &write.target);
		write.offset = state->root_record_physical;
		write.length = sizeof(logical_record);
		if (!rh_write_semantic_target_valid(sdh ? RH_WRITE_SECURE_SDH :
				RH_WRITE_SECURE_SII, &write.target, write.offset,
				write.length, 0) ||
				rh_secure_index_action_append(action, &write,
					sizeof(logical_record), logical_record))
			goto out;
	}
	if (state->large && state->bitmap_resident && !state->bitmap_clean) {
		unsigned char bitmap_record[1024];

		if (rh_secure_index_find_resident(inode, AT_BITMAP, name,
				state->bitmap_instance, state->bitmap_storage_mft_record,
				state->bitmap_storage_sequence,
				state->bitmap_semantic_physical,
				state->bitmap_record_physical, &value_offset, &value_length,
				bitmap_record) ||
				value_length != state->bitmap_data_size)
			goto out;
		if (state->root_clean || state->root_storage_mft_record !=
				state->bitmap_storage_mft_record)
			memcpy(logical_record, bitmap_record, sizeof(logical_record));
		memcpy(logical_record + value_offset, state->bitmap_canonical,
			(size_t)state->bitmap_data_size);
		memset(&write, 0, sizeof(write));
		rh_secure_index_resident_target(inspection, sdh,
			state->bitmap_instance, AT_BITMAP,
			state->bitmap_semantic_physical, state->bitmap_data_size,
			&write.target);
		write.offset = state->bitmap_record_physical;
		write.length = sizeof(logical_record);
		if (!rh_write_semantic_target_valid(sdh ? RH_WRITE_SECURE_SDH :
				RH_WRITE_SECURE_SII, &write.target, write.offset,
				write.length, 0) ||
				rh_secure_index_action_append(action, &write,
					sizeof(logical_record), logical_record))
			goto out;
	}
	result = 0;
out:
	if (inode)
		ntfs_inode_close(inode);
	if (result)
		rh_secure_index_action_destroy(action);
	return result;
}

void rh_secure_index_action_destroy(struct rh_secure_index_action *action)
{
	size_t i;

	if (!action)
		return;
	for (i = 0; i < action->count; i++) {
		free(action->operations[i].bytes);
		free(action->expected_after[i]);
	}
	free(action->writes);
	free(action->operations);
	free(action->expected_after);
	memset(action, 0, sizeof(*action));
}
