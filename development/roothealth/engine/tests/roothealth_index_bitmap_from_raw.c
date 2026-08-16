/* ROOTHEALTH_REPAIR_ROLE(DIAGNOSTIC) */
#include "config.h"

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "device.h"
#include "endians.h"
#include "layout.h"
#include "roothealth_index_bitmap.h"
#include "roothealth_raw_mft.h"
#include "roothealth_write.h"
#include "volume.h"

struct edge_copy {
	uint64_t parent;
	uint16_t parent_sequence;
	uint64_t child;
	uint16_t child_sequence;
	uint16_t key_length;
	uint8_t from_block;
	int64_t block_vcn;
	unsigned char key_hash[32];
};

struct edge_list {
	struct edge_copy *items;
	size_t count;
};

static int raw_i30_name(const struct rh_raw_mft_census *raw,
		const struct rh_raw_attribute *attribute)
{
	static const unsigned char name[] = {
		'$', 0, 'I', 0, '3', 0, '0', 0
	};

	return attribute->name_length == 4U &&
		attribute->name_offset <= raw->name_arena_size &&
		sizeof(name) <= raw->name_arena_size - attribute->name_offset &&
		!memcmp(raw->name_arena + attribute->name_offset, name, sizeof(name));
}

static int split_one_i30_allocation(struct rh_raw_mft_census *raw)
{
	struct rh_raw_run *first = NULL, *second = NULL, *grown_runs;
	struct rh_raw_attribute original, extension, *grown_attributes;
	size_t attribute_index, first_count = 0, second_count = 0, run_index;
	size_t run_checkpoint, extension_index;
	uint16_t instance = 0;

	for (attribute_index = 0; attribute_index < raw->attribute_count;
			attribute_index++) {
		const struct rh_raw_attribute *candidate =
			&raw->attributes[attribute_index];
		size_t stream_extents = 0, i;

		if (!candidate->nonresident || candidate->lowest_vcn ||
				candidate->highest_vcn < 1 || candidate->data_size < 8192 ||
				candidate->type != le32_to_cpu(AT_INDEX_ALLOCATION) ||
				!raw_i30_name(raw, candidate))
			continue;
		for (i = 0; i < raw->attribute_count; i++)
			if (raw->attributes[i].owner.record == candidate->owner.record &&
					raw->attributes[i].owner.sequence ==
						candidate->owner.sequence &&
					raw->attributes[i].type == candidate->type &&
					raw_i30_name(raw, &raw->attributes[i]))
				stream_extents++;
		if (stream_extents == 1U)
			break;
	}
	if (attribute_index == raw->attribute_count) {
		errno = ENOENT;
		return -1;
	}
	original = raw->attributes[attribute_index];
	first = calloc(original.run_count + 1U, sizeof(*first));
	second = calloc(original.run_count + 1U, sizeof(*second));
	if (!first || !second)
		goto fail;
	for (run_index = 0; run_index < original.run_count; run_index++) {
		struct rh_raw_run run =
			raw->runs[original.run_first + run_index];
		uint64_t start = (uint64_t)run.vcn;
		uint64_t end = start + run.length;

		if (end <= 1U) {
			first[first_count++] = run;
		} else if (start >= 1U) {
			second[second_count++] = run;
		} else {
			struct rh_raw_run tail = run;

			run.length = 1U - start;
			first[first_count++] = run;
			tail.vcn = 1;
			tail.length = end - 1U;
			if (!tail.sparse)
				tail.lcn += (int64_t)(1U - start);
			second[second_count++] = tail;
		}
	}
	if (!first_count || !second_count) {
		errno = EIO;
		goto fail;
	}
	if (raw->run_count > SIZE_MAX - first_count - second_count) {
		errno = EOVERFLOW;
		goto fail;
	}
	run_checkpoint = raw->run_count;
	grown_runs = realloc(raw->runs, (raw->run_count + first_count +
		second_count) * sizeof(*grown_runs));
	if (!grown_runs)
		goto fail;
	raw->runs = grown_runs;
	memcpy(raw->runs + run_checkpoint, first, first_count * sizeof(*first));
	memcpy(raw->runs + run_checkpoint + first_count, second,
		second_count * sizeof(*second));
	extension_index = raw->attribute_count;
	for (run_index = 0; run_index < first_count; run_index++)
		raw->runs[run_checkpoint + run_index].attribute_index =
			attribute_index;
	for (run_index = 0; run_index < second_count; run_index++)
		raw->runs[run_checkpoint + first_count + run_index].attribute_index =
			extension_index;
	grown_attributes = realloc(raw->attributes,
		(raw->attribute_count + 1U) * sizeof(*grown_attributes));
	if (!grown_attributes)
		goto fail_after_runs;
	raw->attributes = grown_attributes;
	for (run_index = 0; run_index < raw->attribute_count; run_index++)
		if (raw->attributes[run_index].owner.record == original.owner.record &&
				raw->attributes[run_index].owner.sequence ==
					original.owner.sequence &&
				raw->attributes[run_index].instance >= instance)
			instance = raw->attributes[run_index].instance == UINT16_MAX ?
				UINT16_MAX : raw->attributes[run_index].instance + 1U;
	if (instance == UINT16_MAX) {
		errno = EOVERFLOW;
		goto fail_after_attributes;
	}
	extension = original;
	extension.lowest_vcn = 1;
	extension.instance = instance;
	extension.run_first = run_checkpoint + first_count;
	extension.run_count = second_count;
	raw->attributes[attribute_index].highest_vcn = 0;
	raw->attributes[attribute_index].run_first = run_checkpoint;
	raw->attributes[attribute_index].run_count = first_count;
	raw->attributes[extension_index] = extension;
	raw->attribute_count++;
	raw->attribute_capacity = raw->attribute_count;
	raw->run_count += first_count + second_count;
	raw->run_capacity = raw->run_count;
	raw->extents_expected++;
	raw->extents_completed++;
	free(second);
	free(first);
	return 0;

fail_after_attributes:
	/* The realloc can move the allocation but has not changed its contents. */
	raw->attribute_capacity = raw->attribute_count + 1U;
fail_after_runs:
	raw->run_capacity = raw->run_count + first_count + second_count;
	/* Appended runs are unreachable until the successful commit above. */
fail:
	free(second);
	free(first);
	return -1;
}

static int collect_edge(const struct rh_i30_edge_view *edge, void *opaque)
{
	struct edge_list *list = opaque;
	struct edge_copy *grown;
	struct edge_copy *copy;

	grown = realloc(list->items, (list->count + 1U) * sizeof(*grown));
	if (!grown)
		return -1;
	list->items = grown;
	copy = &list->items[list->count++];
	memset(copy, 0, sizeof(*copy));
	copy->parent = edge->parent_mft_record;
	copy->parent_sequence = edge->parent_sequence;
	copy->child = edge->child_mft_record;
	copy->child_sequence = edge->child_sequence;
	copy->key_length = edge->key_length;
	copy->from_block = edge->from_index_block;
	copy->block_vcn = edge->block_vcn;
	rh_sha256(edge->file_name_value, edge->key_length, copy->key_hash);
	return 0;
}

static int scan(const char *path)
{
	struct rh_writer writer;
	struct rh_raw_mft_census raw;
	struct rh_index_bitmap_census legacy, shared;
	struct edge_list legacy_edges = {0}, shared_edges = {0};
	ntfs_volume *volume = NULL;
	int raw_only = getenv("RH_I30_RAW_ONLY") != NULL;
	uint64_t roots_in_extents = 0, allocation_extents = 0;
	uint64_t multi_extent_allocations = 0;
	int result = -1;

	memset(&raw, 0, sizeof(raw));
	memset(&legacy, 0, sizeof(legacy));
	memset(&shared, 0, sizeof(shared));
	if (rh_writer_open(&writer, path))
		return -1;
	volume = ntfs_mount(path, NTFS_MNT_RDONLY | NTFS_MNT_FORENSIC |
		NTFS_MNT_FS_NO_REPAIR);
	if (!volume || !NDevReadOnly(volume->dev) ||
			rh_raw_mft_census_run(volume, &writer, 1U, &raw) ||
			(getenv("RH_I30_SPLIT_ALLOCATION") &&
			 split_one_i30_allocation(&raw)) ||
			(!raw_only && rh_index_bitmap_census_run_edges(volume, &writer,
				2U, &legacy, collect_edge, &legacy_edges)) ||
			rh_index_bitmap_census_run_edges_from_raw(volume, &writer, &raw,
				2U, &shared, collect_edge, &shared_edges) ||
			!shared.complete ||
			raw.file_name_count != shared_edges.count ||
			(!raw_only && (!legacy.complete ||
			 legacy_edges.count != shared_edges.count ||
			 memcmp(legacy_edges.items, shared_edges.items,
				legacy_edges.count * sizeof(*legacy_edges.items)) ||
			 legacy.mft_slots_expected != shared.mft_slots_expected ||
			 legacy.directories_expected != shared.directories_expected ||
			 legacy.indexes_expected != shared.indexes_expected ||
			 legacy.index_entries_examined != shared.index_entries_examined ||
			 legacy.index_blocks_reachable != shared.index_blocks_reachable ||
			 legacy.change_count != shared.change_count ||
			 legacy.clear_bits_required != shared.clear_bits_required ||
			 memcmp(legacy.tree_hash, shared.tree_hash, 32U) ||
			 memcmp(legacy.expected_hash, shared.expected_hash, 32U) ||
			 memcmp(legacy.census_hash, shared.census_hash, 32U))) ||
			writer.write_boundaries)
		goto out;
	{
		size_t attribute_index, slot_index;

		for (attribute_index = 0; attribute_index < raw.attribute_count;
				attribute_index++) {
			const struct rh_raw_attribute *attribute =
				&raw.attributes[attribute_index];

			if (!raw_i30_name(&raw, attribute))
				continue;
			if (attribute->type == le32_to_cpu(AT_INDEX_ROOT) &&
					attribute->storage.record != attribute->owner.record)
				roots_in_extents++;
			if (attribute->type == le32_to_cpu(AT_INDEX_ALLOCATION))
				allocation_extents++;
		}
		for (slot_index = 0; slot_index < raw.slot_count; slot_index++) {
			const struct rh_raw_mft_slot *slot = &raw.slots[slot_index];
			size_t extents = 0;

			if (slot->state != RH_RAW_SLOT_LIVE_BASE)
				continue;
			for (attribute_index = 0; attribute_index < raw.attribute_count;
					attribute_index++) {
				const struct rh_raw_attribute *attribute =
					&raw.attributes[attribute_index];
				if (attribute->owner.record == slot->record &&
						attribute->owner.sequence == slot->sequence &&
						attribute->type == le32_to_cpu(AT_INDEX_ALLOCATION) &&
						raw_i30_name(&raw, attribute))
					extents++;
			}
			if (extents > 1U)
				multi_extent_allocations++;
		}
	}
	printf("i30-from-raw slots=%llu directories=%llu indexes=%llu "
		"file-names=%zu edges=%zu blocks=%llu/%llu/%llu "
		"child-vcns=%llu bitmap-bits=%llu "
		"root-extents=%llu allocation-extents=%llu "
		"multi-extent-allocations=%llu changes=%zu clears=%llu writes=0\n",
		(unsigned long long)shared.mft_slots_expected,
		(unsigned long long)shared.directories_expected,
		(unsigned long long)shared.indexes_expected, raw.file_name_count,
		shared_edges.count,
		(unsigned long long)shared.index_blocks_reachable,
		(unsigned long long)shared.index_blocks_examined,
		(unsigned long long)shared.index_blocks_expected,
		(unsigned long long)shared.child_vcns_examined,
		(unsigned long long)shared.bitmap_bits_examined,
		(unsigned long long)roots_in_extents,
		(unsigned long long)allocation_extents,
		(unsigned long long)multi_extent_allocations,
		shared.change_count,
		(unsigned long long)shared.clear_bits_required);
	result = 0;
out:
	if (result)
		fprintf(stderr, "i30 raw comparison failed for %s: errno=%d "
			"stage=%u legacy=%zu shared=%zu\n", path, errno,
			shared.failure_stage, legacy_edges.count, shared_edges.count);
	free(shared_edges.items);
	free(legacy_edges.items);
	rh_index_bitmap_census_destroy(&shared);
	rh_index_bitmap_census_destroy(&legacy);
	rh_raw_mft_census_release(&raw);
	if (volume && ntfs_umount(volume, FALSE) && !result)
		result = -1;
	rh_writer_close(&writer);
	return result;
}

int main(int argc, char **argv)
{
	int i;

	if (argc < 2)
		return 5;
	for (i = 1; i < argc; i++)
		if (scan(argv[i]))
			return 1;
	return 0;
}
