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
#include "roothealth_bitmap.h"
#include "roothealth_census_device.h"
#include "roothealth_hash_stream.h"
#include "roothealth_policy_internal.h"
#include "roothealth_raw_mft.h"
#include "roothealth_write.h"

#define RH_BITMAP_HASH_HEADER_SIZE 56U

static void rh_put_u64_le(unsigned char *bytes, uint64_t value)
{
	unsigned int i;

	for (i = 0; i < 8; i++)
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

static int rh_add_change(struct rh_cluster_bitmap_census *census,
		const struct rh_cluster_bitmap_change *change)
{
	struct rh_cluster_bitmap_change *grown;
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

static int rh_mark_cluster(struct rh_cluster_bitmap_census *census,
		uint64_t cluster)
{
	if (cluster >= census->cluster_count) {
		errno = EIO;
		return -1;
	}
	if (rh_bitmap_test(census->expected_bitmap, cluster)) {
		census->duplicate_clusters++;
		errno = EIO;
		return -1;
	}
	rh_bitmap_set(census->expected_bitmap, cluster);
	census->clusters_owned++;
	return 0;
}

static int rh_raw_census_ready(ntfs_volume *volume, uint64_t generation,
		const struct rh_raw_mft_census *raw)
{
	return raw && raw->generation == generation && raw->records_bounded &&
		raw->attribute_lists_complete && raw->extents_complete &&
		raw->slot_count && raw->slots &&
		(!raw->attribute_count || raw->attributes) &&
		(!raw->run_count || raw->runs) &&
		raw->slots_expected == raw->slot_count &&
		raw->slots_completed == raw->slots_expected &&
		raw->live_base_records + raw->live_extent_records <=
			raw->slots_expected &&
		raw->opaque_records == raw->opaque_slot_count &&
		(!raw->opaque_slot_count || (raw->opaque_slots_complete &&
		 raw->opaque_slots)) &&
		raw->free_records + raw->opaque_records == raw->slots_expected -
			(raw->live_base_records + raw->live_extent_records) &&
		!raw->unreadable_records && !raw->invalid_records &&
		raw->runs_expected == raw->run_count &&
		raw->runs_completed == raw->run_count &&
		raw->extents_expected == raw->nonresident_attributes &&
		raw->extents_completed == raw->nonresident_attributes &&
		volume->mft_na && volume->mft_record_size == 1024 &&
		volume->mft_record_size_bits == 10 &&
		volume->cluster_size_bits == 12 &&
		volume->mft_na->initialized_size > 0 &&
		!(volume->mft_na->initialized_size % 1024) &&
		(uint64_t)volume->mft_na->initialized_size / 1024U ==
			raw->slots_expected;
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
		uint64_t owner_record, uint32_t type, size_t expected_bytes,
		const struct rh_raw_attribute **initial)
{
	size_t i, members = 0, windows_aligned_bytes;

	if (expected_bytes > SIZE_MAX - 7U) {
		errno = EOVERFLOW;
		return -1;
	}
	windows_aligned_bytes = (expected_bytes + 7U) & ~(size_t)7U;

	*initial = NULL;
	if (owner_record >= raw->slot_count ||
			raw->slots[owner_record].state != RH_RAW_SLOT_LIVE_BASE ||
			!raw->slots[owner_record].sequence) {
		errno = EIO;
		return -1;
	}
	for (i = 0; i < raw->attribute_count; i++) {
		const struct rh_raw_attribute *attribute = &raw->attributes[i];

		if (attribute->owner.record != owner_record ||
				attribute->type != type || attribute->name_length)
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
			(*initial)->owner.sequence != raw->slots[owner_record].sequence ||
			(*initial)->data_size < 0 ||
			((uint64_t)(*initial)->data_size != expected_bytes &&
			 (uint64_t)(*initial)->data_size != windows_aligned_bytes) ||
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

static int rh_mark_raw_ownership(const struct rh_raw_mft_census *raw,
		struct rh_cluster_bitmap_census *census)
{
	size_t i;

	for (i = 0; i < raw->run_count; i++) {
		const struct rh_raw_run *run = &raw->runs[i];
		uint64_t cluster;

		if (run->attribute_index >= raw->attribute_count || run->vcn < 0 ||
				!run->length || (!run->sparse && run->lcn < 0)) {
			errno = EIO;
			return -1;
		}
		if (!run->sparse) {
			if ((uint64_t)run->lcn >= census->cluster_count ||
					run->length > census->cluster_count - (uint64_t)run->lcn) {
				errno = EIO;
				return -1;
			}
			for (cluster = 0; cluster < run->length; cluster++)
				if (rh_mark_cluster(census, (uint64_t)run->lcn + cluster))
					return -1;
		}
		census->runs_examined++;
	}
	return 0;
}

static int rh_build_changes(ntfs_volume *volume,
		const struct rh_census_reader *reader,
		const struct rh_raw_mft_census *raw,
		const struct rh_raw_attribute *bitmap,
		struct rh_cluster_bitmap_census *census)
{
	unsigned char *stored_bitmap = NULL;
	size_t stored_bytes;
	uint64_t i;

	if (bitmap->data_size < 0 || (uint64_t)bitmap->data_size > SIZE_MAX ||
			(uint64_t)bitmap->data_size < census->bitmap_bytes) {
		errno = EIO;
		return -1;
	}
	stored_bytes = (size_t)bitmap->data_size;
	if (stored_bytes == census->bitmap_bytes) {
		if (rh_stream_read(volume, reader, raw, bitmap,
				census->observed_bitmap, census->bitmap_bytes))
			return -1;
	} else {
		stored_bitmap = malloc(stored_bytes);
		if (!stored_bitmap)
			return -1;
		if (rh_stream_read(volume, reader, raw, bitmap, stored_bitmap,
				stored_bytes))
			goto padded_fail;
		memcpy(census->observed_bitmap, stored_bitmap, census->bitmap_bytes);
		for (i = census->bitmap_bytes; i < stored_bytes; i++)
			if (stored_bitmap[i] != 0xffU) {
				errno = EIO;
				goto padded_fail;
			}
		free(stored_bitmap);
		stored_bitmap = NULL;
	}
	for (i = census->cluster_count; i < census->bitmap_bytes * 8U; i++)
		rh_bitmap_set(census->expected_bitmap, i);
	for (i = 0; i < census->bitmap_bytes; i++) {
		uint64_t vcn, physical;
		uint64_t lcn;
		unsigned char staged, masks[2];
		unsigned int phase;

		if (census->observed_bitmap[i] == census->expected_bitmap[i])
			continue;
		if (rh_stream_map_byte(volume, raw, bitmap, i, &vcn, &lcn,
				&physical))
			return -1;
		if (physical >= reader->device_size) {
			errno = EIO;
			return -1;
		}
		if (reader->excluded) {
			int excluded;

			if (rh_census_reader_range_excluded(reader, physical, 1,
					&excluded))
				return -1;
			if (excluded) {
			errno = EPERM;
			return -1;
			}
		}
		staged = census->observed_bitmap[i];
		masks[0] = (unsigned char)~staged & census->expected_bitmap[i];
		masks[1] = staged & (unsigned char)~census->expected_bitmap[i];
		for (phase = 0; phase < 2U; phase++) {
			unsigned char remaining = masks[phase];

			while (remaining) {
				unsigned int bit_index = (unsigned int)__builtin_ctz(
					(unsigned int)remaining);
				unsigned char bit = (unsigned char)(1U << bit_index);
				struct rh_cluster_bitmap_change change;

				memset(&change, 0, sizeof(change));
				change.logical_offset = i;
				change.logical_vcn = vcn;
				change.lcn = lcn;
				change.physical_offset = physical;
				change.before = staged;
				if (!phase) {
					change.after = staged | bit;
					change.set_mask = bit;
				} else {
					change.after = staged & (unsigned char)~bit;
					change.clear_mask = bit;
				}
				if (rh_add_change(census, &change))
					return -1;
				staged = change.after;
				remaining &= (unsigned char)~bit;
			}
		}
	}
	return 0;
padded_fail:
	free(stored_bitmap);
	return -1;
}

static int rh_hash_census(struct rh_cluster_bitmap_census *census)
{
	unsigned char header[RH_BITMAP_HASH_HEADER_SIZE];
	struct rh_hash_stream hash;

	memset(&header, 0, sizeof(header));
	rh_put_u64_le(header, census->cluster_count);
	rh_put_u64_le(header + 8, census->mft_slots_completed);
	rh_put_u64_le(header + 16, census->mft_slots_in_use);
	rh_put_u64_le(header + 24, census->attributes_examined);
	rh_put_u64_le(header + 32, census->nonresident_extents_examined);
	rh_put_u64_le(header + 40, census->runs_examined);
	rh_put_u64_le(header + 48, census->clusters_owned);
	rh_sha256(census->expected_bitmap, census->bitmap_bytes,
		census->allocation_hash);
	rh_hash_stream_init(&hash);
	if (rh_hash_stream_update(&hash, header, sizeof(header)) ||
			rh_hash_stream_update(&hash, census->expected_bitmap,
				census->bitmap_bytes) ||
			rh_hash_stream_update(&hash, census->observed_bitmap,
				census->bitmap_bytes))
		return -1;
	return rh_hash_stream_final(&hash, census->census_hash);
}

int rh_cluster_bitmap_census_run_from_raw_reader(ntfs_volume *volume,
		const struct rh_census_reader *reader, uint64_t generation,
		const struct rh_raw_mft_census *raw,
		struct rh_cluster_bitmap_census *census)
{
	const struct rh_raw_attribute *bitmap = NULL;
	int result = -1;

	if (!volume || !reader || !generation || !census ||
			volume->sector_size != 512 || volume->cluster_size != 4096 ||
			volume->nr_clusters <= 0 ||
			(uint64_t)volume->nr_clusters >
				(UINT64_C(256) << 30) / 4096U ||
			!rh_raw_census_ready(volume, generation, raw)) {
		errno = EINVAL;
		return -1;
	}
	memset(census, 0, sizeof(*census));
	census->generation = generation;
	census->cluster_count = (uint64_t)volume->nr_clusters;
	census->bitmap_bytes = (size_t)((census->cluster_count + 7U) >> 3);
	census->mft_slots_expected = raw->slots_expected;
	census->mft_slots_completed = raw->slots_completed;
	census->mft_slots_in_use = raw->live_base_records +
		raw->live_extent_records;
	census->mft_slots_free = raw->free_records + raw->opaque_records;
	census->attributes_examined = raw->attribute_count;
	census->nonresident_extents_examined = raw->nonresident_attributes;
	census->unreadable_slots = raw->unreadable_records;
	census->expected_bitmap = calloc(1, census->bitmap_bytes);
	census->observed_bitmap = calloc(1, census->bitmap_bytes);
	if (!census->expected_bitmap || !census->observed_bitmap)
		goto out;
	if (rh_mark_raw_ownership(raw, census))
		goto out;
	if (rh_find_bitmap_stream(raw, FILE_Bitmap, le32_to_cpu(AT_DATA),
			census->bitmap_bytes, &bitmap))
		goto out;
	census->bitmap_sequence = bitmap->owner.sequence;
	census->bitmap_attribute_instance = bitmap->instance;
	if (!census->bitmap_sequence)
		goto out;
	if (rh_build_changes(volume, reader, raw, bitmap, census))
		goto out;
	if (rh_hash_census(census))
		goto out;
	census->bitmap_bits_examined = census->cluster_count;
	census->complete = 1;
	census->structurally_valid = 1;
	census->ownership_exact = !census->duplicate_clusters;
	census->targets_outside_wal = reader->excluded != NULL;
	census->clean = !census->change_count;
	result = 0;
out:
	if (result)
		census->structurally_valid = 0;
	return result;
}

int rh_cluster_bitmap_census_run_from_raw(ntfs_volume *volume,
		struct rh_writer *writer, uint64_t generation,
		const struct rh_raw_mft_census *raw,
		struct rh_cluster_bitmap_census *census)
{
	struct rh_census_reader reader;

	if (!writer || rh_census_reader_from_writer_prefix(writer,
			writer->operation_count, &reader))
		return -1;
	return rh_cluster_bitmap_census_run_from_raw_reader(volume, &reader,
		generation, raw, census);
}

int rh_cluster_bitmap_census_run(ntfs_volume *volume,
		struct rh_writer *writer, uint64_t generation,
		struct rh_cluster_bitmap_census *census)
{
	struct rh_raw_mft_census raw;
	int result;

	memset(&raw, 0, sizeof(raw));
	if (rh_raw_mft_census_run(volume, writer, generation, &raw))
		return -1;
	result = rh_cluster_bitmap_census_run_from_raw(volume, writer, generation,
		&raw, census);
	rh_raw_mft_census_release(&raw);
	return result;
}

void rh_cluster_bitmap_census_destroy(
		struct rh_cluster_bitmap_census *census)
{
	if (!census)
		return;
	free(census->expected_bitmap);
	free(census->observed_bitmap);
	free(census->changes);
	memset(census, 0, sizeof(*census));
}

int rh_cluster_bitmap_seal_policy(
		const struct rh_cluster_bitmap_census *initial,
		const struct rh_cluster_bitmap_census *final,
		const struct rh_writer *writer, size_t first_operation_ordinal,
		int identity_bound, struct rh_policy_evidence **evidence)
{
	struct rh_bitmap_census_result result;
	struct rh_policy_target_identity *targets = NULL;
	unsigned char plan_hash[32];
	size_t i;
	int status = -1;

	if (evidence)
		*evidence = NULL;
	if (!initial || !final || !writer || !evidence || !initial->complete ||
			!final->complete || !initial->change_count || !final->clean ||
			initial->change_count > writer->operation_count ||
			!first_operation_ordinal ||
			first_operation_ordinal - 1U > writer->operation_count ||
			initial->change_count > writer->operation_count -
				(first_operation_ordinal - 1U) ||
			memcmp(initial->allocation_hash, final->allocation_hash, 32) ||
			rh_writer_plan_hash(writer, writer->operation_count, plan_hash)) {
		errno = EINVAL;
		return -1;
	}
	targets = calloc(initial->change_count, sizeof(*targets));
	if (!targets)
		return -1;
	for (i = 0; i < initial->change_count; i++) {
		const struct rh_cluster_bitmap_change *change = &initial->changes[i];
		const struct rh_write_operation *operation =
			&writer->operations[first_operation_ordinal - 1U + i];
		struct rh_policy_target_identity *target = &targets[i];
		unsigned char set_mask = (unsigned char)~change->before &
			change->after;
		unsigned char clear_mask = change->before &
			(unsigned char)~change->after;

		if (operation->kind != RH_WRITE_BITMAP_CLUSTER ||
				operation->offset != change->physical_offset ||
				operation->length != 1 ||
				operation->before[0] != change->before ||
				operation->after[0] != change->after ||
				change->set_mask != set_mask ||
				change->clear_mask != clear_mask ||
				!!set_mask == !!clear_mask ||
				(set_mask && (set_mask & (unsigned char)(set_mask - 1U))) ||
				(clear_mask && (clear_mask &
				 (unsigned char)(clear_mask - 1U)))) {
			errno = EIO;
			goto out;
		}
		target->object = RH_POLICY_TARGET_VOLUME_BITMAP;
		target->action_kind = RH_WRITE_BITMAP_CLUSTER;
		target->write_object = RH_WRITE_TARGET_NONRESIDENT_ATTRIBUTE;
		target->semantic_flags = RH_WRITE_TARGET_NONRESIDENT |
			(clear_mask ?
			 RH_WRITE_TARGET_CLEAR_ONLY : RH_WRITE_TARGET_SET_ONLY);
		target->mft_record = FILE_Bitmap;
		target->mft_sequence = initial->bitmap_sequence;
		target->attribute_instance = initial->bitmap_attribute_instance;
		target->attribute_type = 0x80;
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
		target->changes_set_bits = !!set_mask;
		target->changes_clear_bits = !!clear_mask;
	}
	memset(&result, 0, sizeof(result));
	result.object = RH_POLICY_TARGET_VOLUME_BITMAP;
	result.generation = initial->generation;
	memcpy(result.census_hash, initial->census_hash,
		sizeof(result.census_hash));
	result.final_overlay_generation = final->generation;
	memcpy(result.final_overlay_hash, final->census_hash,
		sizeof(result.final_overlay_hash));
	result.completed = 1;
	result.identity_bound = !!identity_bound;
	result.complete_mft_census = initial->complete && final->complete;
	result.complete_attribute_census = result.complete_mft_census;
	result.complete_runlist_census = result.complete_mft_census;
	result.complete_cluster_census = result.complete_mft_census;
	result.no_io_uncertainty = !initial->unreadable_slots &&
		!final->unreadable_slots;
	result.no_duplicate_clusters = initial->ownership_exact &&
		final->ownership_exact;
	result.targets_outside_wal = initial->targets_outside_wal;
	result.ownership_exact = result.no_duplicate_clusters;
	result.sets_proven_live = result.ownership_exact;
	/*
	 * The cluster census is derived from every initialized MFT slot and every
	 * decoded nonresident run.  When that census is complete and ownership is
	 * exact, a bit absent from the derived allocation map has no filesystem
	 * owner.  Bind that exhaustive negative proof into the policy seal so both
	 * false-free sets and false-allocated clears can be authorized.
	 */
	result.clears_proven_unreferenced = initial->complete && final->complete &&
		initial->ownership_exact && final->ownership_exact &&
		!initial->duplicate_clusters && !final->duplicate_clusters;
	result.data_preserving = 1;
	result.final_overlay_valid = final->clean &&
		!memcmp(initial->allocation_hash, final->allocation_hash, 32);
	status = rh_policy_seal_bitmap_census(&result, targets,
		initial->change_count, evidence);
out:
	free(targets);
	return status;
}
