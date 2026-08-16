/* ROOTHEALTH_REPAIR_ROLE(DIAGNOSTIC) ROOTHEALTH_IO_ROLE(PLANNER) */
#include "config.h"

#include <errno.h>
#include <limits.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include "endians.h"
#include "layout.h"
#include "roothealth_hash_stream.h"
#include "roothealth_mft_bitmap.h"
#include "roothealth_census_device.h"
#include "roothealth_complete_census.h"
#include "roothealth_policy_internal.h"
#include "roothealth_raw_mft.h"
#include "roothealth_write.h"

#define RH_MFT_BITMAP_HASH_HEADER_SIZE 80U
#define RH_MFT_BITMAP_HASH_SLOT_SIZE 24U
#define RH_MFT_BITMAP_FULL_LEDGER_MAGIC UINT64_C(0x52484d46544c4447)
#define RH_MFT_BITMAP_FULL_LEDGER_VERSION UINT32_C(1)

struct rh_mft_bitmap_slot_evidence {
	uint64_t base_record;
	uint16_t sequence;
	uint16_t base_sequence;
	uint16_t flags;
	uint16_t link_count;
	uint16_t roothealth_parent_sequence;
	uint8_t in_use;
	uint8_t structural;
	uint8_t roothealth_name_matches;
	uint8_t reserved;
};

/* Opaque outside this pass: callers can obtain it only from two full views. */
struct rh_mft_bitmap_full_ledger_seal {
	uint64_t magic;
	uint32_t version;
	uint64_t initial_generation;
	unsigned char initial_census_hash[32];
	uint64_t final_generation;
	unsigned char final_census_hash[32];
	uint8_t identity_bound;
	uint8_t namespace_census_complete;
};

int rh_mft_bitmap_full_ledger_seal_create(
		const struct rh_complete_census *initial,
		const struct rh_complete_census *final,
		struct rh_mft_bitmap_full_ledger_seal **output)
{
	struct rh_mft_bitmap_full_ledger_seal *seal;

	if (output)
		*output = NULL;
	if (!initial || !final || !output || !initial->identity_matches ||
			!final->identity_matches || !initial->raw.records_complete ||
			!final->raw.records_complete || !initial->raw.layout_complete ||
			!final->raw.layout_complete ||
			!initial->raw.attribute_lists_complete ||
			!final->raw.attribute_lists_complete ||
			!initial->raw.extents_complete || !final->raw.extents_complete ||
			!initial->namespace_census.graph_complete ||
			!final->namespace_census.graph_complete ||
			!initial->namespace_census.i30_complete ||
			!final->namespace_census.i30_complete ||
			!initial->namespace_census.reciprocity_complete ||
			!final->namespace_census.reciprocity_complete ||
			!initial->index_bitmap.index_tree_complete ||
			!final->index_bitmap.index_tree_complete ||
			initial->raw.unreadable_records || final->raw.unreadable_records ||
			initial->raw.invalid_records || final->raw.invalid_records ||
			initial->namespace_census.unresolved_parents ||
			final->namespace_census.unresolved_parents ||
			initial->namespace_census.i30_edge_count !=
				initial->namespace_census.link_count ||
			final->namespace_census.i30_edge_count !=
				final->namespace_census.link_count ||
			!initial->mft_bitmap.complete || !final->mft_bitmap.complete ||
			memcmp(initial->mft_bitmap.expected_hash,
				final->mft_bitmap.expected_hash, 32U)) {
		errno = EINVAL;
		return -1;
	}
	seal = calloc(1, sizeof(*seal));
	if (!seal)
		return -1;
	seal->magic = RH_MFT_BITMAP_FULL_LEDGER_MAGIC;
	seal->version = RH_MFT_BITMAP_FULL_LEDGER_VERSION;
	seal->initial_generation = initial->mft_bitmap.generation;
	memcpy(seal->initial_census_hash, initial->mft_bitmap.census_hash, 32U);
	seal->final_generation = final->mft_bitmap.generation;
	memcpy(seal->final_census_hash, final->mft_bitmap.census_hash, 32U);
	seal->identity_bound = 1U;
	seal->namespace_census_complete = 1U;
	*output = seal;
	return 0;
}

void rh_mft_bitmap_full_ledger_seal_destroy(
		struct rh_mft_bitmap_full_ledger_seal *seal)
{
	if (!seal)
		return;
	memset(seal, 0, sizeof(*seal));
	free(seal);
}

static void rh_put_u16_le(unsigned char *bytes, uint16_t value)
{
	bytes[0] = (unsigned char)value;
	bytes[1] = (unsigned char)(value >> 8);
}

static void rh_put_u64_le(unsigned char *bytes, uint64_t value)
{
	unsigned int i;

	for (i = 0; i < 8U; i++)
		bytes[i] = (unsigned char)(value >> (8U * i));
}

static int rh_bitmap_test(const unsigned char *bitmap, uint64_t bit)
{
	return !!(bitmap[bit >> 3] & (unsigned char)(1U << (bit & 7U)));
}

static void rh_bitmap_set(unsigned char *bitmap, uint64_t bit)
{
	bitmap[bit >> 3] |= (unsigned char)(1U << (bit & 7U));
}

static int rh_add_change(struct rh_mft_bitmap_census *census,
		const struct rh_mft_bitmap_change *change)
{
	struct rh_mft_bitmap_change *grown;
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

static int rh_raw_census_ready(ntfs_volume *volume, uint64_t generation,
		const struct rh_raw_mft_census *raw)
{
	size_t i, j;

	if (!raw || raw->generation != generation || !raw->records_bounded ||
			!raw->attribute_lists_complete || !raw->extents_complete ||
			!raw->slot_count || !raw->slots ||
			(raw->attribute_count && !raw->attributes) ||
			(raw->run_count && !raw->runs) ||
			(raw->file_name_count && (!raw->file_names || !raw->name_arena)) ||
			raw->slots_expected != raw->slot_count ||
			raw->slots_completed != raw->slots_expected ||
			raw->live_base_records + raw->live_extent_records >
				raw->slots_expected ||
			raw->free_records + raw->opaque_records != raw->slots_expected -
				(raw->live_base_records + raw->live_extent_records) ||
			raw->opaque_records != raw->opaque_slot_count ||
			raw->opaque_slot_count > raw->opaque_slot_capacity ||
			raw->unreadable_records || raw->invalid_records ||
			raw->runs_expected != raw->run_count ||
			raw->runs_completed != raw->run_count ||
			raw->extents_expected != raw->nonresident_attributes ||
			raw->extents_completed != raw->nonresident_attributes ||
			!volume->mft_na || volume->mft_record_size != 1024 ||
			volume->mft_record_size_bits != 10 ||
			volume->cluster_size_bits != 12 ||
			volume->mft_na->initialized_size <= 0 ||
			(volume->mft_na->initialized_size % 1024) ||
			(uint64_t)volume->mft_na->initialized_size / 1024U !=
				raw->slots_expected)
		return 0;
	if (!raw->opaque_slot_count)
		return !raw->opaque_slots_complete && !raw->opaque_slots &&
			!raw->opaque_slot_capacity;
	if (!raw->opaque_slots_complete || !raw->opaque_slots)
		return 0;
	for (i = 0; i < raw->opaque_slot_count; i++) {
		const struct rh_raw_opaque_slot_evidence *opaque =
			&raw->opaque_slots[i];
		int nonzero = 0;

		if (opaque->record < FILE_first_user ||
				opaque->record >= raw->slot_count ||
				raw->slots[opaque->record].state !=
					RH_RAW_SLOT_OPAQUE_FREE_CANDIDATE ||
				(i && raw->opaque_slots[i - 1U].record >= opaque->record))
			return 0;
		for (j = 0; j < 32U; j++)
			if (opaque->raw_before_hash[j]) {
				nonzero = 1;
				break;
			}
		if (!nonzero)
			return 0;
	}
	return 1;
}

static int rh_same_unnamed_stream(const struct rh_raw_attribute *left,
		const struct rh_raw_attribute *right)
{
	return left->owner.record == right->owner.record &&
		left->owner.sequence == right->owner.sequence &&
		left->type == right->type && !left->name_length &&
		!right->name_length;
}

static int rh_find_bitmap_stream(const struct rh_raw_mft_census *raw,
		const struct rh_raw_attribute **initial, size_t *bitmap_bytes)
{
	size_t i, members = 0;

	*initial = NULL;
	if (FILE_MFT >= raw->slot_count ||
			raw->slots[FILE_MFT].state != RH_RAW_SLOT_LIVE_BASE ||
			!raw->slots[FILE_MFT].sequence) {
		errno = EIO;
		return -1;
	}
	for (i = 0; i < raw->attribute_count; i++) {
		const struct rh_raw_attribute *attribute = &raw->attributes[i];

		if (attribute->owner.record != FILE_MFT ||
				attribute->type != le32_to_cpu(AT_BITMAP) ||
				attribute->name_length)
			continue;
		members++;
		if (!attribute->nonresident || attribute->flags ||
				attribute->compression_unit) {
			errno = EIO;
			return -1;
		}
		if (!attribute->lowest_vcn) {
			if (*initial) {
				errno = EIO;
				return -1;
			}
			*initial = attribute;
		}
	}
	if (!members || !*initial ||
			(*initial)->owner.sequence != raw->slots[FILE_MFT].sequence ||
			(*initial)->data_size <= 0 || ((*initial)->data_size & 7) ||
			(uint64_t)(*initial)->data_size > SIZE_MAX ||
			(*initial)->initialized_size != (*initial)->data_size ||
			(*initial)->allocated_size < (*initial)->data_size) {
		errno = EIO;
		return -1;
	}
	for (i = 0; i < raw->attribute_count; i++) {
		const struct rh_raw_attribute *attribute = &raw->attributes[i];
		size_t j;

		if (!rh_same_unnamed_stream(*initial, attribute))
			continue;
		if (attribute->run_first > raw->run_count ||
				attribute->run_count > raw->run_count - attribute->run_first) {
			errno = EIO;
			return -1;
		}
		for (j = 0; j < attribute->run_count; j++) {
			const struct rh_raw_run *run =
				&raw->runs[attribute->run_first + j];

			if (run->attribute_index != i || run->sparse || run->vcn < 0 ||
					run->lcn < 0 || !run->length) {
				errno = EIO;
				return -1;
			}
		}
	}
	*bitmap_bytes = (size_t)(*initial)->data_size;
	return 0;
}

static int rh_stream_read(ntfs_volume *volume,
		const struct rh_census_reader *reader,
		const struct rh_raw_mft_census *raw,
		const struct rh_raw_attribute *initial, unsigned char *buffer,
		size_t length)
{
	uint64_t covered = 0;
	size_t i;

	for (i = 0; i < raw->attribute_count; i++) {
		const struct rh_raw_attribute *attribute = &raw->attributes[i];
		size_t j;

		if (!rh_same_unnamed_stream(initial, attribute))
			continue;
		if (attribute->run_first > raw->run_count ||
				attribute->run_count > raw->run_count - attribute->run_first) {
			errno = EIO;
			return -1;
		}
		for (j = 0; j < attribute->run_count; j++) {
			const struct rh_raw_run *run =
				&raw->runs[attribute->run_first + j];
			uint64_t logical, run_bytes, part, physical;

			if (run->vcn < 0 || run->lcn < 0 || run->sparse ||
					(uint64_t)run->vcn > UINT64_MAX / volume->cluster_size ||
					run->length > UINT64_MAX / volume->cluster_size ||
					(uint64_t)run->lcn > UINT64_MAX / volume->cluster_size) {
				errno = EIO;
				return -1;
			}
			logical = (uint64_t)run->vcn * volume->cluster_size;
			run_bytes = run->length * volume->cluster_size;
			if (logical >= length)
				continue;
			part = run_bytes < (uint64_t)length - logical ? run_bytes :
				(uint64_t)length - logical;
			physical = (uint64_t)run->lcn * volume->cluster_size;
			if (part > SIZE_MAX || physical > reader->device_size ||
					part > reader->device_size - physical ||
					rh_census_reader_read_exact(reader, physical, (size_t)part,
						buffer + (size_t)logical))
				return -1;
			if (covered > UINT64_MAX - part) {
				errno = EOVERFLOW;
				return -1;
			}
			covered += part;
		}
	}
	if (covered != length) {
		errno = EIO;
		return -1;
	}
	return 0;
}

static int rh_stream_map_byte(ntfs_volume *volume,
		const struct rh_raw_mft_census *raw,
		const struct rh_raw_attribute *initial, uint64_t logical,
		uint64_t *logical_vcn, uint64_t *lcn, uint64_t *physical)
{
	uint64_t vcn = logical >> volume->cluster_size_bits;
	uint64_t within = logical & (volume->cluster_size - 1U);
	const struct rh_raw_run *match = NULL;
	size_t i;

	for (i = 0; i < raw->attribute_count; i++) {
		const struct rh_raw_attribute *attribute = &raw->attributes[i];
		size_t j;

		if (!rh_same_unnamed_stream(initial, attribute))
			continue;
		if (attribute->run_first > raw->run_count ||
				attribute->run_count > raw->run_count - attribute->run_first) {
			errno = EIO;
			return -1;
		}
		for (j = 0; j < attribute->run_count; j++) {
			const struct rh_raw_run *run =
				&raw->runs[attribute->run_first + j];

			if (run->vcn < 0 || (uint64_t)run->vcn > vcn ||
					vcn - (uint64_t)run->vcn >= run->length)
				continue;
			if (match || run->sparse || run->lcn < 0 ||
					(uint64_t)run->lcn > UINT64_MAX -
						(vcn - (uint64_t)run->vcn)) {
				errno = EIO;
				return -1;
			}
			match = run;
		}
	}
	if (!match) {
		errno = EIO;
		return -1;
	}
	*logical_vcn = vcn;
	*lcn = (uint64_t)match->lcn + vcn - (uint64_t)match->vcn;
	if (*lcn > UINT64_MAX >> volume->cluster_size_bits) {
		errno = EOVERFLOW;
		return -1;
	}
	*physical = *lcn << volume->cluster_size_bits;
	if (*physical > UINT64_MAX - within) {
		errno = EOVERFLOW;
		return -1;
	}
	*physical += within;
	return 0;
}

static int rh_name_ascii(const struct rh_raw_mft_census *raw,
		const struct rh_raw_file_name *file_name, const char *name)
{
	const unsigned char *bytes;
	size_t expected = strlen(name), i, name_bytes;

	if (file_name->name_length != expected ||
			expected > SIZE_MAX / 2U)
		return 0;
	name_bytes = expected * 2U;
	if (file_name->name_offset > raw->name_arena_size ||
			name_bytes > raw->name_arena_size - file_name->name_offset)
		return 0;
	bytes = raw->name_arena + file_name->name_offset;
	for (i = 0; i < expected; i++)
		if (bytes[2U * i] != (unsigned char)name[i] || bytes[2U * i + 1U])
			return 0;
	return 1;
}

static int rh_import_raw_slots(const struct rh_raw_mft_census *raw,
		struct rh_mft_bitmap_census *census)
{
	size_t i;

	for (i = 0; i < raw->slot_count; i++) {
		const struct rh_raw_mft_slot *source = &raw->slots[i];
		struct rh_mft_bitmap_slot_evidence *slot = &census->slots[i];

		slot->sequence = source->sequence;
		slot->flags = source->flags;
		slot->link_count = source->link_count;
		slot->base_record = source->base.record;
		slot->base_sequence = source->base.sequence;
		slot->structural = source->state == RH_RAW_SLOT_FREE ||
			source->state == RH_RAW_SLOT_LIVE_BASE ||
			source->state == RH_RAW_SLOT_LIVE_EXTENT ||
			source->state == RH_RAW_SLOT_OPAQUE_FREE_CANDIDATE;
		slot->in_use = source->state == RH_RAW_SLOT_LIVE_BASE ||
			source->state == RH_RAW_SLOT_LIVE_EXTENT;
		if (!slot->structural || (!!(slot->flags &
				le16_to_cpu(MFT_RECORD_IN_USE)) != !!slot->in_use)) {
			errno = EIO;
			return -1;
		}
		if (slot->in_use) {
			census->mft_slots_in_use++;
			rh_bitmap_set(census->expected_bitmap, i);
		} else {
			census->mft_slots_free++;
		}
		census->mft_slots_completed++;
	}
	if (census->roothealth_record != RH_MFT_BITMAP_NO_ROOTHEALTH) {
		struct rh_mft_bitmap_slot_evidence *slot;

		if (census->roothealth_record >= raw->slot_count) {
			errno = EINVAL;
			return -1;
		}
		slot = &census->slots[census->roothealth_record];
		for (i = 0; i < raw->file_name_count; i++) {
			const struct rh_raw_file_name *file_name = &raw->file_names[i];

			if (file_name->owner.record != census->roothealth_record ||
					file_name->parent.record != FILE_Extend ||
					!rh_name_ascii(raw, file_name, "$RootHealth"))
				continue;
			if (slot->roothealth_name_matches == UINT8_MAX) {
				errno = EOVERFLOW;
				return -1;
			}
			slot->roothealth_name_matches++;
			slot->roothealth_parent_sequence = file_name->parent.sequence;
		}
	}
	return 0;
}

static int rh_validate_slot_links(struct rh_mft_bitmap_census *census)
{
	uint64_t i;

	for (i = 0; i < census->mft_slots_expected; i++) {
		const struct rh_mft_bitmap_slot_evidence *slot = &census->slots[i];

		if (!slot->structural) {
			census->ambiguous_slots++;
			return -1;
		}
		if (!slot->in_use || !slot->base_record)
			continue;
		if (slot->base_record >= census->mft_slots_expected ||
				slot->base_record == i ||
				!census->slots[slot->base_record].in_use ||
				census->slots[slot->base_record].base_record ||
				(slot->base_sequence && slot->base_sequence !=
					census->slots[slot->base_record].sequence)) {
			census->ambiguous_slots++;
			errno = EIO;
			return -1;
		}
	}
	return 0;
}

static int rh_validate_roothealth(struct rh_mft_bitmap_census *census)
{
	const struct rh_mft_bitmap_slot_evidence *slot, *extend;

	if (census->roothealth_record == RH_MFT_BITMAP_NO_ROOTHEALTH)
		return 0;
	if (!census->roothealth_sequence ||
			census->roothealth_record >= census->mft_slots_expected ||
			FILE_Extend >= census->mft_slots_expected) {
		errno = EINVAL;
		return -1;
	}
	slot = &census->slots[census->roothealth_record];
	extend = &census->slots[FILE_Extend];
	if (!slot->structural || !slot->in_use || slot->base_record ||
			slot->sequence != census->roothealth_sequence ||
			(slot->flags & le16_to_cpu(MFT_RECORD_IS_DIRECTORY)) ||
			slot->link_count != 1U || slot->roothealth_name_matches != 1U ||
			!extend->structural || !extend->in_use || extend->base_record ||
			!(extend->flags & le16_to_cpu(MFT_RECORD_IS_DIRECTORY)) ||
			slot->roothealth_parent_sequence != extend->sequence) {
		errno = EIO;
		return -1;
	}
	census->roothealth_record_bound = 1;
	return 0;
}

static int rh_build_changes(ntfs_volume *volume,
		const struct rh_census_reader *reader,
		const struct rh_raw_mft_census *raw,
		const struct rh_raw_attribute *bitmap,
		struct rh_mft_bitmap_census *census)
{
	uint64_t i;

	if (rh_stream_read(volume, reader, raw, bitmap,
			census->observed_bitmap, census->bitmap_bytes))
		return -1;
	for (i = 0; i < census->bitmap_bytes; i++) {
		struct rh_mft_bitmap_change mapping;
		unsigned char set_mask, clear_mask;
		unsigned char staged, masks[2];
		unsigned int bit, phase;

		if (census->observed_bitmap[i] == census->expected_bitmap[i])
			continue;
		set_mask = (unsigned char)((unsigned char)~census->observed_bitmap[i] &
			census->expected_bitmap[i]);
		clear_mask = (unsigned char)(census->observed_bitmap[i] &
			(unsigned char)~census->expected_bitmap[i]);
		for (bit = 0; bit < 8U; bit++) {
			uint64_t slot_number = i * 8U + bit;
			unsigned char mask = (unsigned char)(1U << bit);

			if ((set_mask & mask) &&
					(slot_number >= census->mft_slots_expected ||
					!census->slots[slot_number].structural ||
					!census->slots[slot_number].in_use)) {
				errno = EIO;
				return -1;
			}
			if ((clear_mask & mask) && slot_number < census->mft_slots_expected &&
					(!census->slots[slot_number].structural ||
					census->slots[slot_number].in_use)) {
				errno = EIO;
				return -1;
			}
		}
		memset(&mapping, 0, sizeof(mapping));
		if (rh_stream_map_byte(volume, raw, bitmap, i,
				&mapping.logical_vcn, &mapping.lcn,
				&mapping.physical_offset))
			return -1;
		mapping.logical_offset = i;
		if (mapping.physical_offset >= reader->device_size) {
			errno = EIO;
			return -1;
		}
		if (reader->excluded) {
			int excluded;

			if (rh_census_reader_range_excluded(reader,
					mapping.physical_offset, 1, &excluded))
				return -1;
			if (excluded) {
			errno = EPERM;
			return -1;
			}
		}
		staged = census->observed_bitmap[i];
		masks[0] = set_mask;
		masks[1] = clear_mask;
		for (phase = 0; phase < 2U; phase++) {
			unsigned char remaining = masks[phase];

			while (remaining) {
				unsigned int bit_index = (unsigned int)__builtin_ctz(
					(unsigned int)remaining);
				unsigned char mask = (unsigned char)(1U << bit_index);
				struct rh_mft_bitmap_change change = mapping;

				change.before = staged;
				if (!phase) {
					change.after = staged | mask;
					change.set_mask = mask;
				} else {
					change.after = staged & (unsigned char)~mask;
					change.clear_mask = mask;
				}
				if (rh_add_change(census, &change))
					return -1;
				staged = change.after;
				remaining &= (unsigned char)~mask;
			}
		}
	}
	census->sets_proven_live = 1;
	census->clears_structurally_free = 1;
	/* Only the integrated namespace/coverage ledger may ever raise this. */
	census->clears_proven_unreferenced = 0;
	census->targets_outside_wal = reader->excluded != NULL;
	return 0;
}

static int rh_hash_census(struct rh_mft_bitmap_census *census)
{
	unsigned char header[RH_MFT_BITMAP_HASH_HEADER_SIZE];
	struct rh_hash_stream hash;
	uint64_t i;

	memset(header, 0, sizeof(header));
	rh_put_u64_le(header, census->mft_slots_completed);
	rh_put_u64_le(header + 8U, census->mft_slots_in_use);
	rh_put_u64_le(header + 16U, census->mft_slots_free);
	rh_put_u64_le(header + 24U, census->bitmap_bytes);
	rh_put_u64_le(header + 32U, census->padding_bits_examined);
	rh_put_u64_le(header + 40U, census->attributes_examined);
	rh_put_u64_le(header + 48U,
		census->nonresident_extents_examined);
	rh_put_u64_le(header + 56U, census->mapping_runs_examined);
	rh_put_u64_le(header + 64U, census->roothealth_record);
	rh_put_u16_le(header + 72U, census->roothealth_sequence);
	rh_put_u16_le(header + 74U, census->mft_sequence);
	rh_put_u16_le(header + 76U, census->bitmap_attribute_instance);
	header[78] = (unsigned char)census->roothealth_record_bound;
	header[79] =
		(unsigned char)census->roothealth_false_free_obligation;
	rh_hash_stream_init(&hash);
	if (rh_hash_stream_update(&hash, header, sizeof(header)))
		return -1;
	for (i = 0; i < census->mft_slots_expected; i++) {
		const struct rh_mft_bitmap_slot_evidence *slot = &census->slots[i];
		unsigned char output[RH_MFT_BITMAP_HASH_SLOT_SIZE];

		memset(output, 0, sizeof(output));
		rh_put_u64_le(output, slot->base_record);
		rh_put_u16_le(output + 8U, slot->sequence);
		rh_put_u16_le(output + 10U, slot->base_sequence);
		rh_put_u16_le(output + 12U, slot->flags);
		rh_put_u16_le(output + 14U, slot->link_count);
		rh_put_u16_le(output + 16U, slot->roothealth_parent_sequence);
		output[18] = slot->in_use;
		output[19] = slot->structural;
		output[20] = slot->roothealth_name_matches;
		if (rh_hash_stream_update(&hash, output, sizeof(output)))
			return -1;
	}
	rh_sha256(census->expected_bitmap, census->bitmap_bytes,
		census->expected_hash);
	if (rh_hash_stream_update(&hash, census->expected_bitmap,
			census->bitmap_bytes) ||
			rh_hash_stream_update(&hash, census->observed_bitmap,
				census->bitmap_bytes))
		return -1;
	return rh_hash_stream_final(&hash, census->census_hash);
}

int rh_mft_bitmap_census_run_from_raw_reader(ntfs_volume *volume,
		const struct rh_census_reader *reader,
		uint64_t generation, uint64_t roothealth_record,
		uint16_t roothealth_sequence, const struct rh_raw_mft_census *raw,
		struct rh_mft_bitmap_census *census)
{
	const struct rh_raw_attribute *bitmap = NULL;
	uint64_t bitmap_bits;
	size_t bitmap_bytes = 0;
	int result = -1;

	if (!volume || !reader || !generation || !census ||
			volume->sector_size != 512 || volume->cluster_size != 4096 ||
			volume->nr_clusters <= 0 ||
			!rh_raw_census_ready(volume, generation, raw) ||
			(roothealth_record != RH_MFT_BITMAP_NO_ROOTHEALTH &&
				!roothealth_sequence)) {
		errno = EINVAL;
		return -1;
	}
	memset(census, 0, sizeof(*census));
	census->generation = generation;
	census->roothealth_record = roothealth_record;
	census->roothealth_sequence = roothealth_sequence;
	census->mft_slots_expected = raw->slots_expected;
	census->attributes_examined = raw->attribute_count;
	census->nonresident_extents_examined = raw->nonresident_attributes;
	census->mapping_runs_examined = raw->run_count;
	census->unreadable_slots = raw->unreadable_records;
	if (rh_find_bitmap_stream(raw, &bitmap, &bitmap_bytes))
		return -1;
	census->bitmap_bytes = bitmap_bytes;
	if (census->bitmap_bytes > UINT64_MAX / 8U) {
		errno = EOVERFLOW;
		return -1;
	}
	bitmap_bits = (uint64_t)census->bitmap_bytes * 8U;
	if (bitmap_bits < census->mft_slots_expected ||
			census->mft_slots_expected > SIZE_MAX /
				sizeof(*census->slots)) {
		errno = EIO;
		return -1;
	}
	census->padding_bits_examined = bitmap_bits - census->mft_slots_expected;
	census->expected_bitmap = calloc(1, census->bitmap_bytes);
	census->observed_bitmap = calloc(1, census->bitmap_bytes);
	census->slots = calloc((size_t)census->mft_slots_expected,
		sizeof(*census->slots));
	if (!census->expected_bitmap || !census->observed_bitmap ||
			!census->slots)
		goto out;
	if (rh_import_raw_slots(raw, census))
		goto out;
	census->mft_sequence = census->slots[FILE_MFT].sequence;
	census->bitmap_attribute_instance = bitmap->instance;
	if (!census->mft_sequence ||
			!census->slots[FILE_MFT].in_use ||
			census->slots[FILE_MFT].base_record ||
			rh_validate_slot_links(census) || rh_validate_roothealth(census) ||
			rh_build_changes(volume, reader, raw, bitmap, census))
		goto out;
	if (roothealth_record != RH_MFT_BITMAP_NO_ROOTHEALTH) {
		census->roothealth_bitmap_bit_set =
			rh_bitmap_test(census->observed_bitmap, roothealth_record);
		census->roothealth_false_free_obligation =
			!census->roothealth_bitmap_bit_set;
	}
	if (rh_hash_census(census))
		goto out;
	census->bitmap_bits_examined = bitmap_bits;
	census->complete = 1;
	census->structurally_valid = 1;
	census->clean = !census->change_count;
	result = 0;
out:
	if (result)
		census->structurally_valid = 0;
	return result;
}

int rh_mft_bitmap_census_run_from_raw(ntfs_volume *volume,
		struct rh_writer *writer, uint64_t generation,
		uint64_t roothealth_record, uint16_t roothealth_sequence,
		const struct rh_raw_mft_census *raw,
		struct rh_mft_bitmap_census *census)
{
	struct rh_census_reader reader;

	if (!writer || rh_census_reader_from_writer_prefix(writer,
			writer->operation_count, &reader))
		return -1;
	return rh_mft_bitmap_census_run_from_raw_reader(volume, &reader,
		generation, roothealth_record, roothealth_sequence, raw, census);
}

int rh_mft_bitmap_census_run(ntfs_volume *volume, struct rh_writer *writer,
		uint64_t generation, uint64_t roothealth_record,
		uint16_t roothealth_sequence, struct rh_mft_bitmap_census *census)
{
	struct rh_raw_mft_census raw;
	int result;

	memset(&raw, 0, sizeof(raw));
	if (rh_raw_mft_census_run(volume, writer, generation, &raw))
		return -1;
	result = rh_mft_bitmap_census_run_from_raw(volume, writer, generation,
		roothealth_record, roothealth_sequence, &raw, census);
	rh_raw_mft_census_release(&raw);
	return result;
}

void rh_mft_bitmap_census_destroy(struct rh_mft_bitmap_census *census)
{
	if (!census)
		return;
	free(census->expected_bitmap);
	free(census->observed_bitmap);
	free(census->slots);
	free(census->changes);
	memset(census, 0, sizeof(*census));
}

static int rh_full_ledger_seal_valid(
		const struct rh_mft_bitmap_full_ledger_seal *seal,
		const struct rh_mft_bitmap_census *initial,
		const struct rh_mft_bitmap_census *final, int identity_bound,
		int namespace_census_complete)
{
	return seal && seal->magic == RH_MFT_BITMAP_FULL_LEDGER_MAGIC &&
		seal->version == RH_MFT_BITMAP_FULL_LEDGER_VERSION &&
		seal->identity_bound == 1U &&
		seal->namespace_census_complete == 1U && identity_bound == 1 &&
		namespace_census_complete == 1 &&
		seal->initial_generation == initial->generation &&
		seal->final_generation == final->generation &&
		!memcmp(seal->initial_census_hash, initial->census_hash, 32) &&
		!memcmp(seal->final_census_hash, final->census_hash, 32);
}

int rh_mft_bitmap_seal_policy(const struct rh_mft_bitmap_census *initial,
		const struct rh_mft_bitmap_census *final,
		const struct rh_writer *writer, size_t first_operation_ordinal,
		int identity_bound, int namespace_census_complete,
		const struct rh_mft_bitmap_full_ledger_seal *full_ledger_seal,
		struct rh_policy_evidence **evidence)
{
	struct rh_bitmap_census_result result;
	struct rh_policy_target_identity *targets = NULL;
	unsigned char plan_hash[32];
	size_t i;
	int status = -1;

	if (evidence)
		*evidence = NULL;
	if (!initial || !final || !writer || !evidence || !identity_bound ||
			!namespace_census_complete || !initial->complete || !final->complete ||
			!initial->structurally_valid || !final->structurally_valid ||
			!initial->change_count || !final->clean || final->change_count ||
			!initial->sets_proven_live || !initial->clears_structurally_free ||
			!initial->targets_outside_wal || !final->targets_outside_wal ||
			initial->mft_slots_expected != final->mft_slots_expected ||
			initial->roothealth_record != final->roothealth_record ||
			initial->roothealth_sequence != final->roothealth_sequence ||
			memcmp(initial->expected_hash, final->expected_hash, 32) ||
			initial->change_count > writer->operation_count ||
			!first_operation_ordinal ||
			first_operation_ordinal - 1U > writer->operation_count ||
			initial->change_count > writer->operation_count -
				(first_operation_ordinal - 1U) ||
			rh_writer_plan_hash(writer, writer->operation_count, plan_hash)) {
		errno = EINVAL;
		return -1;
	}
	if (!rh_full_ledger_seal_valid(full_ledger_seal, initial, final,
			identity_bound, namespace_census_complete)) {
		errno = EPERM;
		return -1;
	}
	targets = calloc(initial->change_count, sizeof(*targets));
	if (!targets)
		return -1;
	for (i = 0; i < initial->change_count; i++) {
		const struct rh_mft_bitmap_change *change = &initial->changes[i];
		const struct rh_write_operation *operation =
			&writer->operations[first_operation_ordinal - 1U + i];
		struct rh_policy_target_identity *target = &targets[i];

		if (operation->kind != RH_WRITE_BITMAP_MFT ||
				operation->offset != change->physical_offset ||
				operation->length != 1U ||
				operation->before[0] != change->before ||
				operation->after[0] != change->after) {
			errno = EIO;
			goto out;
		}
		target->object = RH_POLICY_TARGET_MFT_BITMAP;
		target->action_kind = RH_WRITE_BITMAP_MFT;
		target->write_object = RH_WRITE_TARGET_NONRESIDENT_ATTRIBUTE;
		target->semantic_flags = RH_WRITE_TARGET_NONRESIDENT |
			(change->set_mask ? RH_WRITE_TARGET_SET_ONLY :
			 RH_WRITE_TARGET_CLEAR_ONLY);
		target->mft_record = FILE_MFT;
		target->mft_sequence = initial->mft_sequence;
		target->attribute_instance = initial->bitmap_attribute_instance;
		target->attribute_type = 0xb0U;
		rh_sha256("", 0, target->attribute_name_hash);
		target->lowest_vcn = 0;
		target->logical_vcn = change->logical_vcn;
		target->lcn = change->lcn;
		target->logical_offset = change->logical_offset;
		target->logical_length = 1;
		target->physical_offset = change->physical_offset;
		target->physical_length = 1;
		target->semantic_offset = change->physical_offset;
		target->semantic_length = 1;
		target->operation_ordinal = first_operation_ordinal + i;
		target->writer_checkpoint = writer->operation_count;
		memcpy(target->staged_plan_hash, plan_hash, sizeof(plan_hash));
		rh_sha256(operation->before, operation->length, target->before_hash);
		rh_sha256(operation->after, operation->length, target->after_hash);
		target->changes_set_bits = !!change->set_mask;
		target->changes_clear_bits = !!change->clear_mask;
	}
	memset(&result, 0, sizeof(result));
	result.object = RH_POLICY_TARGET_MFT_BITMAP;
	result.generation = initial->generation;
	memcpy(result.census_hash, initial->census_hash,
		sizeof(result.census_hash));
	result.final_overlay_generation = final->generation;
	memcpy(result.final_overlay_hash, final->census_hash,
		sizeof(result.final_overlay_hash));
	result.completed = 1;
	result.identity_bound = 1;
	result.complete_mft_census = initial->complete && final->complete;
	result.complete_namespace_census = 1;
	result.no_io_uncertainty = !initial->unreadable_slots &&
		!final->unreadable_slots && !initial->ambiguous_slots &&
		!final->ambiguous_slots;
	result.targets_outside_wal = initial->targets_outside_wal &&
		final->targets_outside_wal;
	result.sets_proven_live = initial->sets_proven_live;
	result.clears_proven_unreferenced = 1;
	result.data_preserving = 1;
	result.final_overlay_valid = final->clean &&
		!memcmp(initial->expected_hash, final->expected_hash, 32);
	status = rh_policy_seal_bitmap_census(&result, targets,
		initial->change_count, evidence);
out:
	free(targets);
	return status;
}
