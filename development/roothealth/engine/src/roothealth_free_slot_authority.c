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
#include "roothealth_census_device.h"
#include "roothealth_free_slot_authority.h"
#include "roothealth_free_slot_authority_internal.h"
#include "roothealth_hash_stream.h"
#include "roothealth_mft_bitmap.h"
#include "roothealth_namespace.h"
#include "roothealth_raw_mft.h"
#include "roothealth_write.h"

#define RH_FREE_COMPONENT_MAGIC UINT64_C(0x52484653434f4d50)
#define RH_FREE_AUTHORITY_MAGIC UINT64_C(0x5248465341555448)
#define RH_FREE_COMPONENT_VERSION UINT32_C(2)
#define RH_FREE_MFT_REFERENCE_MAX UINT64_C(0x0000ffffffffffff)

struct rh_free_slot_component_seal {
	uint64_t magic;
	uint32_t version;
	enum rh_free_slot_component_kind kind;
	uint64_t correlation_generation;
	uint64_t items_expected;
	uint64_t items_completed;
	unsigned char source_census_hash[32];
	struct rh_free_slot_reference *references;
	size_t reference_count;
	struct rh_free_slot_range *ranges;
	size_t range_count;
	struct rh_free_slot_range *raw_ranges;
	size_t raw_range_count;
	unsigned char seal_hash[32];
};

struct rh_free_slot_authority {
	uint64_t magic;
	struct rh_free_slot_authority_view view;
};

static int rh_hash_all_zero(const unsigned char hash[32])
{
	size_t i;

	for (i = 0; i < 32U; i++)
		if (hash[i])
			return 0;
	return 1;
}

static int rh_h_bytes(struct rh_hash_stream *stream, const void *data,
		size_t length)
{
	return rh_hash_stream_update(stream, data, length);
}

static int rh_h_u16(struct rh_hash_stream *stream, uint16_t value)
{
	unsigned char encoded[2] = {
		(unsigned char)value, (unsigned char)(value >> 8)
	};

	return rh_h_bytes(stream, encoded, sizeof(encoded));
}

static int rh_h_u32(struct rh_hash_stream *stream, uint32_t value)
{
	unsigned char encoded[4];
	unsigned int i;

	for (i = 0; i < 4U; i++)
		encoded[i] = (unsigned char)(value >> (8U * i));
	return rh_h_bytes(stream, encoded, sizeof(encoded));
}

static int rh_h_u64(struct rh_hash_stream *stream, uint64_t value)
{
	unsigned char encoded[8];
	unsigned int i;

	for (i = 0; i < 8U; i++)
		encoded[i] = (unsigned char)(value >> (8U * i));
	return rh_h_bytes(stream, encoded, sizeof(encoded));
}

static int rh_reference_compare(const void *left_pointer,
		const void *right_pointer)
{
	const struct rh_free_slot_reference *left = left_pointer;
	const struct rh_free_slot_reference *right = right_pointer;

	if (left->record != right->record)
		return left->record < right->record ? -1 : 1;
	if (left->sequence != right->sequence)
		return left->sequence < right->sequence ? -1 : 1;
	return 0;
}

static int rh_range_compare(const void *left_pointer,
		const void *right_pointer)
{
	const struct rh_free_slot_range *left = left_pointer;
	const struct rh_free_slot_range *right = right_pointer;

	if (left->offset != right->offset)
		return left->offset < right->offset ? -1 : 1;
	if (left->length != right->length)
		return left->length < right->length ? -1 : 1;
	return 0;
}

static int rh_component_shape_valid(
		const struct rh_free_slot_component_seal *seal)
{
	size_t i;

	if (!seal || seal->magic != RH_FREE_COMPONENT_MAGIC ||
			seal->version != RH_FREE_COMPONENT_VERSION ||
			seal->kind <= RH_FREE_SLOT_COMPONENT_INVALID ||
			seal->kind >= RH_FREE_SLOT_COMPONENT_COUNT ||
			!seal->correlation_generation ||
			seal->items_completed != seal->items_expected ||
			seal->reference_count > seal->items_completed ||
			rh_hash_all_zero(seal->source_census_hash) ||
			(seal->reference_count && !seal->references) ||
			(seal->range_count && !seal->ranges) ||
			(seal->raw_range_count && !seal->raw_ranges))
		return 0;
	if (seal->kind == RH_FREE_SLOT_COMPONENT_WAL_EXCLUSIONS) {
		if (seal->reference_count || !seal->range_count ||
				!seal->raw_range_count ||
				seal->items_expected != seal->range_count)
			return 0;
	} else if (seal->range_count || seal->raw_range_count) {
		return 0;
	}
	for (i = 0; i < seal->reference_count; i++) {
		if (!seal->references[i].sequence ||
				seal->references[i].record > RH_FREE_MFT_REFERENCE_MAX ||
				(i && rh_reference_compare(&seal->references[i - 1U],
					&seal->references[i]) > 0))
			return 0;
	}
	for (i = 0; i < seal->range_count; i++) {
		uint64_t end;

		if (!seal->ranges[i].length || seal->ranges[i].offset >
				UINT64_MAX - seal->ranges[i].length)
			return 0;
		end = seal->ranges[i].offset + seal->ranges[i].length;
		if (i && seal->ranges[i - 1U].offset +
				seal->ranges[i - 1U].length > seal->ranges[i].offset)
			return 0;
		if (end <= seal->ranges[i].offset)
			return 0;
	}
	for (i = 0; i < seal->raw_range_count; i++) {
		uint64_t end;
		size_t j;
		int found = 0;

		if (!seal->raw_ranges[i].length || seal->raw_ranges[i].offset >
				UINT64_MAX - seal->raw_ranges[i].length)
			return 0;
		end = seal->raw_ranges[i].offset + seal->raw_ranges[i].length;
		if ((i && seal->raw_ranges[i - 1U].offset +
				seal->raw_ranges[i - 1U].length >
				seal->raw_ranges[i].offset) || end <= seal->raw_ranges[i].offset)
			return 0;
		for (j = 0; j < seal->range_count; j++)
			if (!rh_range_compare(&seal->raw_ranges[i], &seal->ranges[j])) {
				found = 1;
				break;
			}
		if (!found)
			return 0;
	}
	return 1;
}

static int rh_component_compute_hash(
		const struct rh_free_slot_component_seal *seal,
		unsigned char output[32])
{
	struct rh_hash_stream hash;
	size_t i;

	if (!rh_component_shape_valid(seal) || !output) {
		errno = EINVAL;
		return -1;
	}
	rh_hash_stream_init(&hash);
	if (rh_h_bytes(&hash, "RHFSC2\0\0", 8U) ||
			rh_h_u32(&hash, (uint32_t)seal->kind) ||
			rh_h_u64(&hash, seal->items_expected) ||
			rh_h_u64(&hash, seal->items_completed) ||
			rh_h_bytes(&hash, seal->source_census_hash, 32U) ||
			rh_h_u64(&hash, seal->reference_count) ||
			rh_h_u64(&hash, seal->range_count) ||
			rh_h_u64(&hash, seal->raw_range_count))
		return -1;
	for (i = 0; i < seal->reference_count; i++)
		if (rh_h_u64(&hash, seal->references[i].record) ||
				rh_h_u16(&hash, seal->references[i].sequence))
			return -1;
	for (i = 0; i < seal->range_count; i++)
		if (rh_h_u64(&hash, seal->ranges[i].offset) ||
				rh_h_u64(&hash, seal->ranges[i].length))
			return -1;
	for (i = 0; i < seal->raw_range_count; i++)
		if (rh_h_u64(&hash, seal->raw_ranges[i].offset) ||
				rh_h_u64(&hash, seal->raw_ranges[i].length))
			return -1;
	return rh_hash_stream_final(&hash, output);
}

static int rh_component_valid(const struct rh_free_slot_component_seal *seal)
{
	unsigned char hash[32];

	return rh_component_shape_valid(seal) &&
		!rh_component_compute_hash(seal, hash) &&
		!memcmp(hash, seal->seal_hash, sizeof(hash));
}

static int rh_component_seal_create(
		enum rh_free_slot_component_kind kind, uint64_t correlation_generation,
		uint64_t items_expected, uint64_t items_completed,
		const unsigned char source_census_hash[32],
		const struct rh_free_slot_reference *references,
		size_t reference_count, const struct rh_free_slot_range *ranges,
		size_t range_count, const struct rh_free_slot_range *raw_ranges,
		size_t raw_range_count, struct rh_free_slot_component_seal **output)
{
	struct rh_free_slot_component_seal *seal = NULL;

	if (output)
		*output = NULL;
	if (!output || kind <= RH_FREE_SLOT_COMPONENT_INVALID ||
			kind >= RH_FREE_SLOT_COMPONENT_COUNT || !correlation_generation ||
			items_completed != items_expected || !source_census_hash ||
			rh_hash_all_zero(source_census_hash) ||
			(reference_count && !references) || (range_count && !ranges) ||
			(raw_range_count && !raw_ranges) ||
			(kind == RH_FREE_SLOT_COMPONENT_WAL_EXCLUSIONS ?
			 (!range_count || !raw_range_count || reference_count ||
			  items_expected != range_count) :
			 (range_count || raw_range_count))) {
		errno = EINVAL;
		return -1;
	}
	seal = calloc(1, sizeof(*seal));
	if (!seal)
		return -1;
	if (reference_count) {
		size_t input, unique = 0;

		if (reference_count > SIZE_MAX / sizeof(*seal->references)) {
			errno = EOVERFLOW;
			goto fail;
		}
		seal->references = malloc(reference_count *
			sizeof(*seal->references));
		if (!seal->references)
			goto fail;
		memcpy(seal->references, references,
			reference_count * sizeof(*seal->references));
		qsort(seal->references, reference_count,
			sizeof(*seal->references), rh_reference_compare);
		for (input = 0; input < reference_count; input++)
			if (!unique || rh_reference_compare(
					&seal->references[unique - 1U],
					&seal->references[input]))
				seal->references[unique++] = seal->references[input];
		reference_count = unique;
	}
	if (range_count) {
		if (range_count > SIZE_MAX / sizeof(*seal->ranges)) {
			errno = EOVERFLOW;
			goto fail;
		}
		seal->ranges = malloc(range_count * sizeof(*seal->ranges));
		if (!seal->ranges)
			goto fail;
		memcpy(seal->ranges, ranges, range_count * sizeof(*seal->ranges));
		qsort(seal->ranges, range_count, sizeof(*seal->ranges),
			rh_range_compare);
	}
	if (raw_range_count) {
		if (raw_range_count > SIZE_MAX / sizeof(*seal->raw_ranges)) {
			errno = EOVERFLOW;
			goto fail;
		}
		seal->raw_ranges = malloc(raw_range_count *
			sizeof(*seal->raw_ranges));
		if (!seal->raw_ranges)
			goto fail;
		memcpy(seal->raw_ranges, raw_ranges, raw_range_count *
			sizeof(*seal->raw_ranges));
		qsort(seal->raw_ranges, raw_range_count,
			sizeof(*seal->raw_ranges), rh_range_compare);
	}
	seal->magic = RH_FREE_COMPONENT_MAGIC;
	seal->version = RH_FREE_COMPONENT_VERSION;
	seal->kind = kind;
	seal->correlation_generation = correlation_generation;
	seal->items_expected = items_expected;
	seal->items_completed = items_completed;
	memcpy(seal->source_census_hash, source_census_hash, 32U);
	seal->reference_count = reference_count;
	seal->range_count = range_count;
	seal->raw_range_count = raw_range_count;
	if (!rh_component_shape_valid(seal) ||
			rh_component_compute_hash(seal, seal->seal_hash))
		goto fail;
	*output = seal;
	return 0;
fail:
	rh_free_slot_component_seal_destroy(seal);
	return -1;
}

#ifdef ROOTHEALTH_REPAIR_TESTING
int rh_free_slot_test_component_seal_create(
		enum rh_free_slot_component_kind kind, uint64_t correlation_generation,
		uint64_t items_expected, uint64_t items_completed,
		const unsigned char source_census_hash[32],
		const struct rh_free_slot_reference *references,
		size_t reference_count, const struct rh_free_slot_range *ranges,
		size_t range_count, struct rh_free_slot_component_seal **output)
{
	return rh_component_seal_create(kind, correlation_generation,
		items_expected, items_completed, source_census_hash, references,
		reference_count, ranges, range_count,
		kind == RH_FREE_SLOT_COMPONENT_WAL_EXCLUSIONS ? ranges : NULL,
		kind == RH_FREE_SLOT_COMPONENT_WAL_EXCLUSIONS ? range_count : 0U,
		output);
}
#endif

int rh_free_slot_friend_native_open_attribute_seal(
		uint64_t correlation_generation, uint64_t items_expected,
		uint64_t items_completed, const unsigned char source_census_hash[32],
		const struct rh_free_slot_reference *references,
		size_t reference_count, struct rh_free_slot_component_seal **output)
{
	return rh_component_seal_create(
		RH_FREE_SLOT_COMPONENT_NATIVE_OPEN_ATTRIBUTE,
		correlation_generation, items_expected, items_completed,
		source_census_hash, references, reference_count, NULL, 0U,
		NULL, 0U, output);
}

int rh_free_slot_friend_native_target_seal(
		uint64_t correlation_generation, uint64_t items_expected,
		uint64_t items_completed, const unsigned char source_census_hash[32],
		const struct rh_free_slot_reference *references,
		size_t reference_count, struct rh_free_slot_component_seal **output)
{
	return rh_component_seal_create(RH_FREE_SLOT_COMPONENT_NATIVE_TARGET,
		correlation_generation, items_expected, items_completed,
		source_census_hash, references, reference_count, NULL, 0U,
		NULL, 0U, output);
}

int rh_free_slot_friend_native_control_seal(
		uint64_t correlation_generation, uint64_t items_expected,
		uint64_t items_completed, const unsigned char source_census_hash[32],
		const struct rh_free_slot_reference *references,
		size_t reference_count, struct rh_free_slot_component_seal **output)
{
	return rh_component_seal_create(RH_FREE_SLOT_COMPONENT_NATIVE_CONTROL,
		correlation_generation, items_expected, items_completed,
		source_census_hash, references, reference_count, NULL, 0U,
		NULL, 0U, output);
}

int rh_free_slot_friend_reparse_seal(
		uint64_t correlation_generation, uint64_t items_expected,
		uint64_t items_completed, const unsigned char source_census_hash[32],
		const struct rh_free_slot_reference *references,
		size_t reference_count, struct rh_free_slot_component_seal **output)
{
	return rh_component_seal_create(RH_FREE_SLOT_COMPONENT_REPARSE,
		correlation_generation, items_expected, items_completed,
		source_census_hash, references, reference_count, NULL, 0U,
		NULL, 0U, output);
}

int rh_free_slot_friend_objid_seal(
		uint64_t correlation_generation, uint64_t items_expected,
		uint64_t items_completed, const unsigned char source_census_hash[32],
		const struct rh_free_slot_reference *references,
		size_t reference_count, struct rh_free_slot_component_seal **output)
{
	return rh_component_seal_create(RH_FREE_SLOT_COMPONENT_OBJID,
		correlation_generation, items_expected, items_completed,
		source_census_hash, references, reference_count, NULL, 0U,
		NULL, 0U, output);
}

int rh_free_slot_friend_recovery_namespace_seal(
		uint64_t correlation_generation, uint64_t items_expected,
		uint64_t items_completed, const unsigned char source_census_hash[32],
		const struct rh_free_slot_reference *references,
		size_t reference_count, struct rh_free_slot_component_seal **output)
{
	return rh_component_seal_create(
		RH_FREE_SLOT_COMPONENT_RECOVERY_NAMESPACE, correlation_generation,
		items_expected, items_completed, source_census_hash, references,
		reference_count, NULL, 0U, NULL, 0U, output);
}

int rh_free_slot_friend_wal_exclusions_seal(
		uint64_t correlation_generation, uint64_t ranges_expected,
		uint64_t ranges_completed, const unsigned char source_census_hash[32],
		const struct rh_free_slot_range *ranges, size_t range_count,
		const struct rh_free_slot_range *raw_ranges, size_t raw_range_count,
		struct rh_free_slot_component_seal **output)
{
	return rh_component_seal_create(RH_FREE_SLOT_COMPONENT_WAL_EXCLUSIONS,
		correlation_generation, ranges_expected, ranges_completed,
		source_census_hash, NULL, 0U, ranges, range_count, raw_ranges,
		raw_range_count, output);
}

int rh_free_slot_friend_usn_fixed_system_seal(
		uint64_t correlation_generation, enum rh_free_slot_usn_state usn_state,
		const struct rh_free_slot_reference *usn_reference,
		uint64_t items_expected,
		uint64_t items_completed, const unsigned char source_census_hash[32],
		const struct rh_free_slot_reference *references,
		size_t reference_count, struct rh_free_slot_component_seal **output)
{
	size_t i;
	int found = 0;

	if (usn_state == RH_FREE_SLOT_USN_UNKNOWN ||
			(usn_state == RH_FREE_SLOT_USN_ABSENT && usn_reference) ||
			(usn_state == RH_FREE_SLOT_USN_PRESENT && (!usn_reference ||
			 !usn_reference->sequence))) {
		errno = EINVAL;
		return -1;
	}
	if (usn_state == RH_FREE_SLOT_USN_PRESENT) {
		for (i = 0; i < reference_count; i++)
			if (references[i].record == usn_reference->record &&
					references[i].sequence == usn_reference->sequence) {
				found = 1;
				break;
			}
		if (!found) {
			errno = EINVAL;
			return -1;
		}
	}
	return rh_component_seal_create(
		RH_FREE_SLOT_COMPONENT_USN_FIXED_SYSTEM, correlation_generation,
		items_expected, items_completed, source_census_hash, references,
		reference_count, NULL, 0U, NULL, 0U, output);
}

void rh_free_slot_component_seal_destroy(
		struct rh_free_slot_component_seal *seal)
{
	if (!seal)
		return;
	free(seal->raw_ranges);
	free(seal->ranges);
	free(seal->references);
	memset(seal, 0, sizeof(*seal));
	free(seal);
}

enum rh_free_slot_component_kind rh_free_slot_component_seal_kind(
		const struct rh_free_slot_component_seal *seal)
{
	return rh_component_valid(seal) ? seal->kind :
		RH_FREE_SLOT_COMPONENT_INVALID;
}

int rh_free_slot_component_seal_hash(
		const struct rh_free_slot_component_seal *seal,
		unsigned char output[32])
{
	if (!output || !rh_component_valid(seal)) {
		errno = EINVAL;
		return -1;
	}
	memcpy(output, seal->seal_hash, 32U);
	return 0;
}

static int rh_raw_ref_valid(const struct rh_raw_mft_census *raw,
		struct rh_raw_mft_ref reference, int allow_zero)
{
	if (!reference.record && !reference.sequence)
		return allow_zero;
	return reference.sequence && reference.record < raw->slot_count &&
		(raw->slots[reference.record].state == RH_RAW_SLOT_LIVE_BASE ||
		 raw->slots[reference.record].state == RH_RAW_SLOT_LIVE_EXTENT) &&
		raw->slots[reference.record].sequence == reference.sequence;
}

static int rh_raw_ready(const struct rh_raw_mft_census *raw,
		uint64_t generation)
{
	uint64_t live_base = 0, live_extent = 0, free_slots = 0, opaque_slots = 0;
	uint64_t resident = 0, nonresident = 0, attribute_lists = 0;
	uint64_t user_defined = 0, indexed_resident = 0;
	uint64_t slot_attributes = 0, slot_file_names = 0;
	uint64_t slot_owned_file_names = 0, slot_list_entries = 0;
	size_t i, j, opaque_at = 0;

	if (!raw || raw->generation != generation || !raw->records_complete ||
			!raw->records_bounded || !raw->layout_complete ||
			!raw->attribute_lists_complete || !raw->extents_complete ||
			!raw->slots || !raw->slot_count ||
			raw->layout_candidate_count ||
			raw->slot_count != raw->slots_expected ||
			raw->slots_completed != raw->slots_expected ||
			raw->unreadable_records || raw->invalid_records ||
			raw->attribute_count > raw->attribute_capacity ||
			raw->run_count > raw->run_capacity ||
			raw->file_name_count > raw->file_name_capacity ||
			raw->list_entry_count > raw->list_entry_capacity ||
			raw->layout_candidate_count > raw->layout_candidate_capacity ||
			raw->name_arena_size > raw->name_arena_capacity ||
			raw->value_arena_size > raw->value_arena_capacity ||
			!raw->opaque_slots_complete || !raw->opaque_slot_count ||
			raw->opaque_records != raw->opaque_slot_count ||
			raw->opaque_slot_count > raw->opaque_slot_capacity ||
			!raw->opaque_slots ||
			(raw->attribute_count && !raw->attributes) ||
			(raw->run_count && !raw->runs) ||
			(raw->file_name_count && !raw->file_names) ||
			(raw->list_entry_count && !raw->list_entries) ||
			(raw->name_arena_size && !raw->name_arena) ||
			(raw->value_arena_size && !raw->value_arena) ||
			raw->runs_expected != raw->run_count ||
			raw->runs_completed != raw->run_count ||
			raw->file_name_links != raw->file_name_count ||
			raw->attribute_list_entries != raw->list_entry_count ||
			rh_hash_all_zero(raw->slot_hash) ||
			rh_hash_all_zero(raw->attribute_hash) ||
			rh_hash_all_zero(raw->attrlist_hash) ||
			rh_hash_all_zero(raw->run_hash) ||
			rh_hash_all_zero(raw->file_name_manifest_hash) ||
			rh_hash_all_zero(raw->layout_hash) ||
			rh_hash_all_zero(raw->census_hash))
		return 0;
	for (i = 0; i < raw->slot_count; i++) {
		const struct rh_raw_mft_slot *slot = &raw->slots[i];

		if (slot->record != i || slot->attribute_first > raw->attribute_count ||
				slot->attribute_count > raw->attribute_count -
					slot->attribute_first ||
				slot->file_name_first > raw->file_name_count ||
				slot->file_name_count > raw->file_name_count -
					slot->file_name_first ||
				slot->list_entry_first > raw->list_entry_count ||
				slot->list_entry_count > raw->list_entry_count -
					slot->list_entry_first)
			return 0;
		if ((uint64_t)slot->attribute_count > UINT64_MAX - slot_attributes ||
				(uint64_t)slot->file_name_count >
					UINT64_MAX - slot_file_names ||
				(uint64_t)slot->owned_file_name_count >
					UINT64_MAX - slot_owned_file_names ||
				(uint64_t)slot->list_entry_count >
					UINT64_MAX - slot_list_entries)
			return 0;
		slot_attributes += slot->attribute_count;
		slot_file_names += slot->file_name_count;
		slot_owned_file_names += slot->owned_file_name_count;
		slot_list_entries += slot->list_entry_count;
		switch (slot->state) {
		case RH_RAW_SLOT_FREE:
			free_slots++;
			if ((slot->flags & le16_to_cpu(MFT_RECORD_IN_USE)) ||
					slot->base.record || slot->base.sequence ||
					slot->attribute_count || slot->file_name_count ||
					slot->owned_file_name_count || slot->list_entry_count ||
					slot->has_attribute_list ||
					slot->attribute_list_assembled)
				return 0;
			break;
		case RH_RAW_SLOT_OPAQUE_FREE_CANDIDATE:
			opaque_slots++;
			if (opaque_at >= raw->opaque_slot_count ||
					raw->opaque_slots[opaque_at].record != i ||
					rh_hash_all_zero(raw->opaque_slots[opaque_at].raw_before_hash) ||
					(opaque_at && raw->opaque_slots[opaque_at - 1U].record >= i) ||
					slot->sequence || slot->flags ||
					slot->link_count || slot->base.record || slot->base.sequence ||
					slot->attribute_count || slot->file_name_count ||
					slot->owned_file_name_count || slot->list_entry_count ||
					slot->has_attribute_list || slot->attribute_list_assembled)
				return 0;
			opaque_at++;
			break;
		case RH_RAW_SLOT_LIVE_BASE:
			live_base++;
			if (!slot->sequence || !(slot->flags &
					le16_to_cpu(MFT_RECORD_IN_USE)) || slot->base.record ||
					slot->base.sequence || !slot->attribute_list_assembled)
				return 0;
			break;
		case RH_RAW_SLOT_LIVE_EXTENT:
			live_extent++;
			if (!slot->sequence || !(slot->flags &
					le16_to_cpu(MFT_RECORD_IN_USE)) ||
					!rh_raw_ref_valid(raw, slot->base, 0) ||
					raw->slots[slot->base.record].state !=
						RH_RAW_SLOT_LIVE_BASE || slot->has_attribute_list ||
					slot->attribute_list_assembled || slot->list_entry_count)
				return 0;
			break;
		case RH_RAW_SLOT_UNREADABLE:
		case RH_RAW_SLOT_INVALID:
		default:
			return 0;
		}
	}
	if (live_base != raw->live_base_records ||
			live_extent != raw->live_extent_records ||
			free_slots != raw->free_records ||
			opaque_slots != raw->opaque_records ||
			opaque_at != raw->opaque_slot_count ||
			live_base + live_extent + free_slots + opaque_slots != raw->slot_count ||
			slot_attributes != raw->attribute_count ||
			slot_file_names != raw->file_name_count ||
			slot_owned_file_names != raw->file_name_count ||
			slot_list_entries != raw->list_entry_count)
		return 0;
	for (i = 0; i < raw->attribute_count; i++) {
		const struct rh_raw_attribute *attribute = &raw->attributes[i];

		if (!rh_raw_ref_valid(raw, attribute->owner, 0) ||
				raw->slots[attribute->owner.record].state !=
					RH_RAW_SLOT_LIVE_BASE ||
				!rh_raw_ref_valid(raw, attribute->storage, 0) ||
				attribute->name_offset > raw->name_arena_size ||
				(size_t)attribute->name_length * 2U >
					raw->name_arena_size - attribute->name_offset ||
				attribute->run_first > raw->run_count ||
				attribute->run_count > raw->run_count -
					attribute->run_first)
			return 0;
		if (attribute->nonresident) {
			nonresident++;
		} else {
			resident++;
			if (attribute->value_arena_offset > raw->value_arena_size ||
					attribute->value_length > raw->value_arena_size -
						attribute->value_arena_offset || attribute->run_count)
				return 0;
		}
		if (attribute->type == le32_to_cpu(AT_ATTRIBUTE_LIST))
			attribute_lists++;
		if (attribute->type >= 0x1000U)
			user_defined++;
		if (!attribute->nonresident && attribute->resident_flags &&
				attribute->type != le32_to_cpu(AT_FILE_NAME))
			indexed_resident++;
		for (j = 0; j < attribute->run_count; j++) {
			const struct rh_raw_run *run =
				&raw->runs[attribute->run_first + j];

			if (run->attribute_index != i || run->vcn < 0 || !run->length ||
					(!run->sparse && run->lcn < 0))
				return 0;
		}
	}
	if (resident != raw->resident_attributes ||
			nonresident != raw->nonresident_attributes ||
			nonresident != raw->extents_expected ||
			nonresident != raw->extents_completed ||
			attribute_lists != raw->attribute_lists ||
			user_defined != raw->user_defined_attributes ||
			indexed_resident != raw->indexed_resident_attributes ||
			resident + nonresident != raw->attribute_count)
		return 0;
	for (i = 0; i < raw->run_count; i++)
		if (raw->runs[i].attribute_index >= raw->attribute_count)
			return 0;
	for (i = 0; i < raw->file_name_count; i++) {
		const struct rh_raw_file_name *name = &raw->file_names[i];

		if (!rh_raw_ref_valid(raw, name->owner, 0) ||
				raw->slots[name->owner.record].state !=
					RH_RAW_SLOT_LIVE_BASE ||
				!rh_raw_ref_valid(raw, name->storage, 0) ||
				!rh_raw_ref_valid(raw, name->parent, 0) ||
				raw->slots[name->parent.record].state !=
					RH_RAW_SLOT_LIVE_BASE ||
				name->name_offset > raw->name_arena_size ||
				(size_t)name->name_length * 2U >
					raw->name_arena_size - name->name_offset ||
				name->value_arena_offset > raw->value_arena_size ||
				name->value_length > raw->value_arena_size -
					name->value_arena_offset)
			return 0;
	}
	for (i = 0; i < raw->list_entry_count; i++) {
		const struct rh_raw_attr_list_entry *entry = &raw->list_entries[i];

		if (!entry->matched || entry->matched_attribute >=
				raw->attribute_count || !rh_raw_ref_valid(raw, entry->owner, 0) ||
				raw->slots[entry->owner.record].state !=
					RH_RAW_SLOT_LIVE_BASE ||
				!rh_raw_ref_valid(raw, entry->storage, 0) ||
				entry->name_offset > raw->name_arena_size ||
				(size_t)entry->name_length * 2U >
					raw->name_arena_size - entry->name_offset)
			return 0;
	}
	return 1;
}

static int rh_mft_bitmap_ready(const struct rh_mft_bitmap_census *bitmap,
		const struct rh_raw_mft_census *raw, uint64_t generation)
{
	unsigned char expected_hash[32];
	unsigned char *replayed = NULL;
	uint64_t bitmap_bits, expected_in_use = 0, differences = 0;
	size_t i;
	int result = 0;

	if (!bitmap || bitmap->generation != generation || !bitmap->complete ||
			!bitmap->structurally_valid || !bitmap->expected_bitmap ||
			!bitmap->observed_bitmap || !bitmap->bitmap_bytes ||
			!bitmap->slots || bitmap->mft_slots_expected != raw->slot_count ||
			bitmap->mft_slots_completed != bitmap->mft_slots_expected ||
			bitmap->mft_slots_in_use + bitmap->mft_slots_free !=
				bitmap->mft_slots_expected || bitmap->unreadable_slots ||
			bitmap->ambiguous_slots || rh_hash_all_zero(bitmap->census_hash) ||
			rh_hash_all_zero(bitmap->expected_hash) ||
			bitmap->bitmap_bytes > UINT64_MAX / 8U ||
			(bitmap->change_count && !bitmap->changes) ||
			bitmap->clean != !bitmap->change_count ||
			!bitmap->targets_outside_wal || !bitmap->sets_proven_live ||
			!bitmap->clears_structurally_free ||
			bitmap->clears_proven_unreferenced ||
			bitmap->mft_slots_in_use != raw->live_base_records +
				raw->live_extent_records ||
			bitmap->mft_slots_free != raw->free_records + raw->opaque_records ||
			FILE_MFT >= raw->slot_count ||
			bitmap->mft_sequence != raw->slots[FILE_MFT].sequence)
		return 0;
	bitmap_bits = (uint64_t)bitmap->bitmap_bytes * 8U;
	if (bitmap_bits < bitmap->mft_slots_expected ||
			bitmap->bitmap_bits_examined != bitmap_bits ||
			bitmap->padding_bits_examined != bitmap_bits -
				bitmap->mft_slots_expected ||
			bitmap->attributes_examined != raw->attribute_count ||
			bitmap->nonresident_extents_examined !=
				raw->nonresident_attributes ||
			bitmap->mapping_runs_examined != raw->run_count)
		return 0;
	if (bitmap->roothealth_record == RH_MFT_BITMAP_NO_ROOTHEALTH) {
		if (bitmap->roothealth_sequence || bitmap->roothealth_record_bound ||
				bitmap->roothealth_bitmap_bit_set ||
				bitmap->roothealth_false_free_obligation)
			return 0;
	} else {
		unsigned char roothealth_mask;
		size_t roothealth_offset;

		if (!bitmap->roothealth_sequence || !bitmap->roothealth_record_bound ||
				bitmap->roothealth_record >= raw->slot_count ||
				raw->slots[bitmap->roothealth_record].state !=
					RH_RAW_SLOT_LIVE_BASE ||
				raw->slots[bitmap->roothealth_record].sequence !=
					bitmap->roothealth_sequence)
			return 0;
		roothealth_offset = (size_t)(bitmap->roothealth_record >> 3);
		roothealth_mask = (unsigned char)(1U <<
			(bitmap->roothealth_record & 7U));
		if (bitmap->roothealth_bitmap_bit_set !=
				!!(bitmap->observed_bitmap[roothealth_offset] &
				roothealth_mask) || bitmap->roothealth_false_free_obligation !=
				!bitmap->roothealth_bitmap_bit_set)
			return 0;
	}
	for (i = 0; i < raw->slot_count; i++) {
		unsigned char mask = (unsigned char)(1U << (i & 7U));
		int expected = !!(bitmap->expected_bitmap[i >> 3] & mask);
		int raw_in_use = raw->slots[i].state == RH_RAW_SLOT_LIVE_BASE ||
			raw->slots[i].state == RH_RAW_SLOT_LIVE_EXTENT;

		if (expected != raw_in_use)
			return 0;
		if (expected)
			expected_in_use++;
	}
	for (i = 0; i < bitmap->bitmap_bytes; i++) {
		unsigned char difference = bitmap->observed_bitmap[i] ^
			bitmap->expected_bitmap[i];

		while (difference) {
			differences++;
			difference &= (unsigned char)(difference - 1U);
		}
	}
	if (expected_in_use != bitmap->mft_slots_in_use ||
			differences != bitmap->change_count)
		return 0;
	if (bitmap->change_count) {
		replayed = malloc(bitmap->bitmap_bytes);
		if (!replayed)
			return 0;
		memcpy(replayed, bitmap->observed_bitmap, bitmap->bitmap_bytes);
		for (i = 0; i < bitmap->change_count; i++) {
			const struct rh_mft_bitmap_change *change = &bitmap->changes[i];
			unsigned char mask = change->set_mask | change->clear_mask;

			if (change->logical_offset >= bitmap->bitmap_bytes || !mask ||
					(change->set_mask && change->clear_mask) ||
					(mask & (unsigned char)(mask - 1U)) ||
					(change->before ^ change->after) != mask ||
					replayed[change->logical_offset] != change->before ||
					(change->set_mask && ((change->before & mask) ||
					 !(change->after & mask))) ||
					(change->clear_mask && (!(change->before & mask) ||
					 (change->after & mask))))
				goto out;
			replayed[change->logical_offset] = change->after;
		}
		if (memcmp(replayed, bitmap->expected_bitmap,
				bitmap->bitmap_bytes))
			goto out;
	}
	rh_sha256(bitmap->expected_bitmap, bitmap->bitmap_bytes, expected_hash);
	result = !memcmp(expected_hash, bitmap->expected_hash,
		sizeof(expected_hash));
out:
	free(replayed);
	return result;
}

static int rh_namespace_ready(const struct rh_namespace_census *census,
		const struct rh_raw_mft_census *raw, uint64_t generation)
{
	size_t i;

	if (!census || census->generation != generation ||
			!census->graph_bounded || !census->graph_complete ||
			!census->i30_complete || !census->reciprocity_complete ||
			census->live_nodes_completed != census->live_nodes_expected ||
			census->links_completed != census->links_expected ||
			census->links_expected != raw->file_name_count ||
			census->link_count != census->links_expected ||
			census->i30_edge_count != census->link_count ||
			(census->link_count && (!census->links || !census->name_arena ||
			 !census->file_name_value_arena)) ||
			(census->i30_edge_count && (!census->i30_edges ||
			 !census->i30_name_arena || !census->i30_value_arena)) ||
			census->orphan_nodes || census->unresolved_parents ||
			census->cycles || census->aliases ||
			census->i30_directories_completed !=
				census->i30_directories_expected ||
			census->i30_indexes_completed != census->i30_indexes_expected ||
			census->i30_blocks_examined != census->i30_blocks_expected ||
			census->i30_blocks_reachable != census->i30_blocks_expected ||
			census->i30_bitmap_changes || census->i30_clear_bits_required ||
			rh_hash_all_zero(census->upcase_hash) ||
			rh_hash_all_zero(census->graph_hash) ||
			rh_hash_all_zero(census->manifest_hash) ||
			rh_hash_all_zero(census->i30_edge_hash) ||
			rh_hash_all_zero(census->i30_manifest_hash) ||
			rh_hash_all_zero(census->i30_tree_hash) ||
			rh_hash_all_zero(census->i30_expected_bitmap_hash) ||
			rh_hash_all_zero(census->i30_index_census_hash) ||
			rh_hash_all_zero(census->reciprocity_hash) ||
			rh_hash_all_zero(census->census_hash))
		return 0;
	for (i = 0; i < census->link_count; i++) {
		const struct rh_namespace_link *link = &census->links[i];

		if (!rh_raw_ref_valid(raw, link->owner, 0) ||
				raw->slots[link->owner.record].state !=
					RH_RAW_SLOT_LIVE_BASE ||
				!rh_raw_ref_valid(raw, link->storage, 0) ||
				!rh_raw_ref_valid(raw, link->parent, 0) ||
				raw->slots[link->parent.record].state !=
					RH_RAW_SLOT_LIVE_BASE ||
				link->name_offset > census->name_arena_size ||
				(size_t)link->name_length * 2U >
					census->name_arena_size - link->name_offset ||
				link->file_name_value_offset >
					census->file_name_value_arena_size ||
				link->file_name_value_length >
					census->file_name_value_arena_size -
						link->file_name_value_offset)
			return 0;
	}
	for (i = 0; i < census->i30_edge_count; i++) {
		const struct rh_namespace_i30_edge *edge = &census->i30_edges[i];

		if (!rh_raw_ref_valid(raw, edge->child, 0) ||
				raw->slots[edge->child.record].state !=
					RH_RAW_SLOT_LIVE_BASE ||
				!rh_raw_ref_valid(raw, edge->parent, 0) ||
				raw->slots[edge->parent.record].state !=
					RH_RAW_SLOT_LIVE_BASE ||
				edge->name_offset > census->i30_name_arena_size ||
				(size_t)edge->name_length * 2U >
					census->i30_name_arena_size - edge->name_offset ||
				edge->file_name_value_offset >
					census->i30_value_arena_size ||
				edge->key_length > census->i30_value_arena_size -
					edge->file_name_value_offset)
			return 0;
	}
	return 1;
}

static int rh_ref_is_zero(struct rh_raw_mft_ref reference)
{
	return !reference.record && !reference.sequence;
}

static void rh_count_reference(struct rh_free_slot_authority_view *view,
		struct rh_raw_mft_ref reference, uint64_t target)
{
	if (rh_ref_is_zero(reference))
		return;
	view->total_references_examined++;
	if (reference.record == target)
		view->references_matched++;
}

static int rh_collect_raw_references(const struct rh_raw_mft_census *raw,
		struct rh_free_slot_authority_view *view)
{
	size_t i, j;

	view->slots_examined = raw->slot_count;
	view->attributes_examined = raw->attribute_count;
	view->runs_examined = raw->run_count;
	view->attribute_list_entries_examined = raw->list_entry_count;
	view->file_name_links_examined = raw->file_name_count;
	for (i = 0; i < raw->slot_count; i++) {
		const struct rh_raw_mft_slot *slot = &raw->slots[i];

		if (slot->state == RH_RAW_SLOT_LIVE_EXTENT) {
			uint64_t before = view->references_matched;

			rh_count_reference(view, slot->base, view->target_record);
			if (view->references_matched != before)
				view->extent_references_matched++;
		}
	}
	for (i = 0; i < raw->attribute_count; i++) {
		const struct rh_raw_attribute *attribute = &raw->attributes[i];
		uint64_t before = view->references_matched;

		rh_count_reference(view, attribute->owner, view->target_record);
		if (view->references_matched != before)
			view->allocation_owners_matched++;
		rh_count_reference(view, attribute->storage, view->target_record);
		for (j = 0; j < attribute->run_count; j++)
			if (attribute->owner.record == view->target_record)
				view->owned_runs_matched++;
	}
	for (i = 0; i < raw->list_entry_count; i++) {
		rh_count_reference(view, raw->list_entries[i].owner,
			view->target_record);
		rh_count_reference(view, raw->list_entries[i].storage,
			view->target_record);
	}
	for (i = 0; i < raw->file_name_count; i++) {
		rh_count_reference(view, raw->file_names[i].owner,
			view->target_record);
		rh_count_reference(view, raw->file_names[i].storage,
			view->target_record);
		rh_count_reference(view, raw->file_names[i].parent,
			view->target_record);
	}
	return 0;
}

static void rh_collect_namespace_references(
		const struct rh_namespace_census *census,
		struct rh_free_slot_authority_view *view)
{
	size_t i;

	view->i30_edges_examined = census->i30_edge_count;
	for (i = 0; i < census->link_count; i++) {
		rh_count_reference(view, census->links[i].owner,
			view->target_record);
		rh_count_reference(view, census->links[i].storage,
			view->target_record);
		rh_count_reference(view, census->links[i].parent,
			view->target_record);
	}
	for (i = 0; i < census->i30_edge_count; i++) {
		rh_count_reference(view, census->i30_edges[i].child,
			view->target_record);
		rh_count_reference(view, census->i30_edges[i].parent,
			view->target_record);
	}
}

static int rh_collect_components(
		const struct rh_free_slot_component_seal *const *components,
		size_t component_count, uint64_t generation, uint64_t slot_count,
		struct rh_free_slot_authority_view *view,
		const struct rh_free_slot_component_seal **wal)
{
	const struct rh_free_slot_component_seal *by_kind[
		RH_FREE_SLOT_COMPONENT_COUNT] = {0};
	size_t i, j;

	*wal = NULL;
	if (!components || component_count != RH_FREE_SLOT_REQUIRED_COMPONENTS) {
		errno = EPERM;
		return -1;
	}
	for (i = 0; i < component_count; i++) {
		const struct rh_free_slot_component_seal *seal = components[i];

		if (!rh_component_valid(seal) ||
				seal->correlation_generation != generation ||
				by_kind[seal->kind]) {
			errno = EPERM;
			return -1;
		}
		by_kind[seal->kind] = seal;
	}
	for (i = 1; i < RH_FREE_SLOT_COMPONENT_COUNT; i++) {
		const struct rh_free_slot_component_seal *seal = by_kind[i];

		if (!seal) {
			errno = EPERM;
			return -1;
		}
		memcpy(view->component_source_hashes[i],
			seal->source_census_hash, 32U);
		memcpy(view->component_hashes[i], seal->seal_hash, 32U);
		if (i == RH_FREE_SLOT_COMPONENT_WAL_EXCLUSIONS) {
			*wal = seal;
			continue;
		}
		for (j = 0; j < seal->reference_count; j++) {
			struct rh_raw_mft_ref reference;

			if (seal->references[j].record >= slot_count) {
				errno = EPERM;
				return -1;
			}
			reference.record = seal->references[j].record;
			reference.sequence = seal->references[j].sequence;
			view->explicit_references_examined++;
			rh_count_reference(view, reference, view->target_record);
		}
	}
	return *wal ? 0 : -1;
}

static int rh_writer_exclusions(const struct rh_writer *writer,
		const struct rh_free_slot_component_seal *wal,
		struct rh_free_slot_authority_view *view)
{
	struct rh_free_slot_range *ranges = NULL;
	struct rh_free_slot_range *raw_ranges = NULL;
	struct rh_hash_stream hash;
	size_t i, j;
	int result = -1;

	if (!writer || !wal || wal->kind !=
			RH_FREE_SLOT_COMPONENT_WAL_EXCLUSIONS || writer->read_fd < 0 ||
			writer->write_fd >= 0 ||
			!writer->device_size || writer->write_boundaries ||
			writer->commit_started || writer->commit_completed ||
			writer->excluded_count != wal->range_count ||
			!writer->excluded_count || !writer->raw_wal_allowed_count ||
			writer->raw_wal_allowed_count != wal->raw_range_count ||
			!writer->excluded || !writer->raw_wal_allowed ||
			writer->excluded_count > writer->excluded_capacity ||
			writer->raw_wal_allowed_count >
				writer->raw_wal_allowed_capacity ||
			writer->raw_wal_allowed_count > writer->excluded_count) {
		errno = EPERM;
		return -1;
	}
	ranges = calloc(writer->excluded_count, sizeof(*ranges));
	raw_ranges = calloc(writer->raw_wal_allowed_count, sizeof(*raw_ranges));
	if (!ranges || !raw_ranges)
		goto out;
	for (i = 0; i < writer->excluded_count; i++) {
		if (!writer->excluded[i].length || writer->excluded[i].offset >
				writer->device_size || writer->excluded[i].length >
				writer->device_size - writer->excluded[i].offset) {
			errno = EIO;
			goto out;
		}
		ranges[i].offset = writer->excluded[i].offset;
		ranges[i].length = writer->excluded[i].length;
	}
	qsort(ranges, writer->excluded_count, sizeof(*ranges), rh_range_compare);
	for (i = 0; i < writer->excluded_count; i++) {
		if (memcmp(&ranges[i], &wal->ranges[i], sizeof(ranges[i])) ||
				(i && ranges[i - 1U].offset + ranges[i - 1U].length >
				 ranges[i].offset)) {
			errno = EIO;
			goto out;
		}
	}
	for (i = 0; i < writer->raw_wal_allowed_count; i++) {
		if (!writer->raw_wal_allowed[i].length ||
				writer->raw_wal_allowed[i].offset > writer->device_size ||
				writer->raw_wal_allowed[i].length > writer->device_size -
					writer->raw_wal_allowed[i].offset) {
			errno = EIO;
			goto out;
		}
		raw_ranges[i].offset = writer->raw_wal_allowed[i].offset;
		raw_ranges[i].length = writer->raw_wal_allowed[i].length;
	}
	qsort(raw_ranges, writer->raw_wal_allowed_count, sizeof(*raw_ranges),
		rh_range_compare);
	for (i = 0; i < writer->raw_wal_allowed_count; i++) {
		int found = 0;

		if (memcmp(&raw_ranges[i], &wal->raw_ranges[i],
				sizeof(raw_ranges[i])) || (i && raw_ranges[i - 1U].offset +
				raw_ranges[i - 1U].length > raw_ranges[i].offset)) {
			errno = EIO;
			goto out;
		}
		for (j = 0; j < writer->excluded_count; j++)
			if (!memcmp(&raw_ranges[i], &ranges[j],
					sizeof(raw_ranges[i]))) {
				found = 1;
				break;
			}
		if (!found) {
			errno = EIO;
			goto out;
		}
	}
	view->wal_ranges_examined = writer->excluded_count;
	view->wal_raw_ranges_examined = writer->raw_wal_allowed_count;
	view->device_size = writer->device_size;
	rh_hash_stream_init(&hash);
	if (rh_h_bytes(&hash, "RHFWAL1\0", 8U) ||
			rh_h_u64(&hash, writer->device_size) ||
			rh_h_u64(&hash, writer->excluded_count) ||
			rh_h_u64(&hash, writer->raw_wal_allowed_count))
		goto out;
	for (i = 0; i < writer->excluded_count; i++)
		if (rh_h_u64(&hash, ranges[i].offset) ||
				rh_h_u64(&hash, ranges[i].length))
			goto out;
	for (i = 0; i < writer->raw_wal_allowed_count; i++)
		if (rh_h_u64(&hash, raw_ranges[i].offset) ||
				rh_h_u64(&hash, raw_ranges[i].length))
			goto out;
	if (rh_hash_stream_final(&hash, view->writer_exclusion_hash))
		goto out;
	result = 0;
out:
	free(raw_ranges);
	free(ranges);
	return result;
}

static int rh_reader_exclusions(const struct rh_census_reader *reader,
		const struct rh_free_slot_component_seal *wal,
		struct rh_free_slot_authority_view *view)
{
	struct rh_hash_stream hash;
	size_t i;

	if (!reader || !reader->context || !reader->read || !reader->excluded ||
			!reader->device_size || !wal || wal->kind !=
				RH_FREE_SLOT_COMPONENT_WAL_EXCLUSIONS ||
			!wal->range_count || !wal->raw_range_count) {
		errno = EPERM;
		return -1;
	}
	for (i = 0; i < wal->range_count; i++) {
		int excluded = 0;

		if (wal->ranges[i].offset > reader->device_size ||
				wal->ranges[i].length > reader->device_size -
					wal->ranges[i].offset ||
				rh_census_reader_range_excluded(reader, wal->ranges[i].offset,
					wal->ranges[i].length, &excluded) || !excluded) {
			errno = EIO;
			return -1;
		}
	}
	for (i = 0; i < wal->raw_range_count; i++) {
		int excluded = 0;

		if (wal->raw_ranges[i].offset > reader->device_size ||
				wal->raw_ranges[i].length > reader->device_size -
					wal->raw_ranges[i].offset ||
				rh_census_reader_range_excluded(reader,
					wal->raw_ranges[i].offset, wal->raw_ranges[i].length,
					&excluded) || !excluded) {
			errno = EIO;
			return -1;
		}
	}
	view->wal_ranges_examined = wal->range_count;
	view->wal_raw_ranges_examined = wal->raw_range_count;
	view->device_size = reader->device_size;
	rh_hash_stream_init(&hash);
	if (rh_h_bytes(&hash, "RHFWAL1\0", 8U) ||
			rh_h_u64(&hash, reader->device_size) ||
			rh_h_u64(&hash, wal->range_count) ||
			rh_h_u64(&hash, wal->raw_range_count))
		return -1;
	for (i = 0; i < wal->range_count; i++)
		if (rh_h_u64(&hash, wal->ranges[i].offset) ||
				rh_h_u64(&hash, wal->ranges[i].length))
			return -1;
	for (i = 0; i < wal->raw_range_count; i++)
		if (rh_h_u64(&hash, wal->raw_ranges[i].offset) ||
				rh_h_u64(&hash, wal->raw_ranges[i].length))
			return -1;
	return rh_hash_stream_final(&hash, view->writer_exclusion_hash);
}

static int rh_authority_compute_hash(
		const struct rh_free_slot_authority_view *view,
		unsigned char output[32])
{
	struct rh_hash_stream hash;
	size_t i;

	if (!view || !output || view->version !=
			RH_FREE_SLOT_AUTHORITY_VERSION) {
		errno = EINVAL;
		return -1;
	}
	rh_hash_stream_init(&hash);
	if (rh_h_bytes(&hash, "RHFSA1\0\0", 8U) ||
			rh_h_u32(&hash, view->version) ||
			rh_h_u64(&hash, view->target_record) ||
			rh_h_u16(&hash, view->intended_sequence) ||
			rh_h_u16(&hash, view->observed_slot_sequence) ||
			rh_h_u64(&hash, view->physical_offset) ||
			rh_h_u64(&hash, view->physical_length) ||
			rh_h_u64(&hash, view->mft_bitmap_physical_offset) ||
			rh_h_u64(&hash, view->device_size) ||
			rh_h_u64(&hash, view->slots_examined) ||
			rh_h_u64(&hash, view->attributes_examined) ||
			rh_h_u64(&hash, view->runs_examined) ||
			rh_h_u64(&hash, view->attribute_list_entries_examined) ||
			rh_h_u64(&hash, view->file_name_links_examined) ||
			rh_h_u64(&hash, view->i30_edges_examined) ||
			rh_h_u64(&hash, view->explicit_references_examined) ||
			rh_h_u64(&hash, view->total_references_examined) ||
			rh_h_u64(&hash, view->references_matched) ||
			rh_h_u64(&hash, view->extent_references_matched) ||
			rh_h_u64(&hash, view->allocation_owners_matched) ||
			rh_h_u64(&hash, view->owned_runs_matched) ||
			rh_h_u64(&hash, view->wal_ranges_examined) ||
			rh_h_u64(&hash, view->wal_raw_ranges_examined) ||
			rh_h_u64(&hash, view->wal_overlaps_matched) ||
			rh_h_bytes(&hash, &view->bitmap_mask, 1U) ||
			rh_h_bytes(&hash, &view->observed_bitmap_byte, 1U) ||
			rh_h_bytes(&hash, &view->expected_bitmap_byte, 1U) ||
			rh_h_bytes(&hash, view->raw_before_hash, 32U) ||
			rh_h_bytes(&hash, view->raw_census_hash, 32U) ||
			rh_h_bytes(&hash, view->mft_bitmap_census_hash, 32U) ||
			rh_h_bytes(&hash, view->namespace_census_hash, 32U) ||
			rh_h_bytes(&hash, view->writer_exclusion_hash, 32U))
		return -1;
	for (i = 1; i < RH_FREE_SLOT_COMPONENT_COUNT; i++)
		if (rh_h_u32(&hash, (uint32_t)i) ||
				rh_h_bytes(&hash, view->component_source_hashes[i], 32U) ||
				rh_h_bytes(&hash, view->component_hashes[i], 32U))
			return -1;
	return rh_hash_stream_final(&hash, output);
}

static int rh_authority_valid(const struct rh_free_slot_authority *authority)
{
	unsigned char hash[32];
	size_t i;

	if (!authority || authority->magic != RH_FREE_AUTHORITY_MAGIC ||
			authority->view.version != RH_FREE_SLOT_AUTHORITY_VERSION ||
			!authority->view.correlation_generation ||
			!authority->view.intended_sequence ||
			authority->view.target_record < FILE_first_user ||
			authority->view.target_record > UINT32_MAX ||
			authority->view.physical_length != RH_FREE_SLOT_RAW_RECORD_SIZE ||
			!authority->view.bitmap_mask ||
			authority->view.bitmap_mask != (unsigned char)(1U <<
				(authority->view.target_record & 7U)) ||
			!authority->view.wal_ranges_examined ||
			!authority->view.wal_raw_ranges_examined ||
			authority->view.physical_offset > authority->view.device_size ||
			authority->view.physical_length > authority->view.device_size -
				authority->view.physical_offset ||
			authority->view.mft_bitmap_physical_offset >=
				authority->view.device_size ||
			authority->view.references_matched ||
			authority->view.extent_references_matched ||
			authority->view.allocation_owners_matched ||
			authority->view.owned_runs_matched ||
			authority->view.wal_overlaps_matched ||
			(authority->view.observed_bitmap_byte &
			 authority->view.bitmap_mask) ||
			(authority->view.expected_bitmap_byte &
			 authority->view.bitmap_mask) ||
			rh_hash_all_zero(authority->view.raw_before_hash) ||
			rh_hash_all_zero(authority->view.raw_census_hash) ||
			rh_hash_all_zero(authority->view.mft_bitmap_census_hash) ||
			rh_hash_all_zero(authority->view.namespace_census_hash) ||
			rh_hash_all_zero(authority->view.writer_exclusion_hash))
		return 0;
	for (i = 1; i < RH_FREE_SLOT_COMPONENT_COUNT; i++)
		if (rh_hash_all_zero(authority->view.component_source_hashes[i]) ||
				rh_hash_all_zero(authority->view.component_hashes[i]))
			return 0;
	return !rh_authority_compute_hash(&authority->view, hash) &&
		!memcmp(hash, authority->view.evidence_hash, sizeof(hash));
}

static const struct rh_raw_opaque_slot_evidence *rh_find_opaque_slot(
		const struct rh_raw_mft_census *raw, uint64_t record)
{
	size_t low = 0, high = raw->opaque_slot_count;

	while (low < high) {
		size_t middle = low + (high - low) / 2U;

		if (raw->opaque_slots[middle].record == record)
			return &raw->opaque_slots[middle];
		if (raw->opaque_slots[middle].record < record)
			low = middle + 1U;
		else
			high = middle;
	}
	return NULL;
}

static int rh_free_slot_authority_create_reader_internal(
		const struct rh_census_reader *reader, const struct rh_writer *writer,
		const struct rh_raw_mft_census *raw,
		const struct rh_mft_bitmap_census *mft_bitmap,
		const struct rh_namespace_census *namespace_census,
		uint64_t correlation_generation, uint64_t target_record,
		uint16_t intended_sequence,
		const struct rh_free_slot_component_seal *const *components,
		size_t component_count, struct rh_free_slot_authority **output)
{
	const struct rh_free_slot_component_seal *wal = NULL;
	const struct rh_raw_opaque_slot_evidence *opaque = NULL;
	struct rh_free_slot_authority *authority = NULL;
	struct rh_raw_mft_ref mft_owner;
	unsigned char raw_before[RH_FREE_SLOT_RAW_RECORD_SIZE];
	unsigned char current_bitmap_byte;
	uint64_t logical_offset, physical_offset, bitmap_physical_offset;
	size_t bitmap_offset;
	int overlap;

	if (output)
		*output = NULL;
	if (!output || !reader || !reader->context || !reader->read ||
			!reader->excluded || !reader->device_size ||
			!rh_census_reader_is_pretransaction(reader) ||
			!correlation_generation ||
			!intended_sequence || target_record < FILE_first_user ||
			target_record > UINT32_MAX ||
			!rh_raw_ready(raw, correlation_generation) ||
			!rh_mft_bitmap_ready(mft_bitmap, raw,
				correlation_generation) ||
			!rh_namespace_ready(namespace_census, raw,
				correlation_generation) || target_record >= raw->slot_count) {
		errno = EINVAL;
		return -1;
	}
	opaque = rh_find_opaque_slot(raw, target_record);
	if (!opaque || raw->slots[target_record].state !=
			RH_RAW_SLOT_OPAQUE_FREE_CANDIDATE ||
			raw->slots[target_record].attribute_count ||
			raw->slots[target_record].file_name_count ||
			raw->slots[target_record].owned_file_name_count ||
			raw->slots[target_record].list_entry_count ||
			raw->slots[target_record].has_attribute_list) {
		errno = EBUSY;
		return -1;
	}
	bitmap_offset = (size_t)(target_record >> 3);
	if (bitmap_offset >= mft_bitmap->bitmap_bytes) {
		errno = EIO;
		return -1;
	}
	authority = calloc(1, sizeof(*authority));
	if (!authority)
		return -1;
	authority->magic = RH_FREE_AUTHORITY_MAGIC;
	authority->view.version = RH_FREE_SLOT_AUTHORITY_VERSION;
	authority->view.correlation_generation = correlation_generation;
	authority->view.target_record = target_record;
	authority->view.intended_sequence = intended_sequence;
	authority->view.observed_slot_sequence =
		raw->slots[target_record].sequence;
	authority->view.physical_length = RH_FREE_SLOT_RAW_RECORD_SIZE;
	authority->view.bitmap_mask =
		(unsigned char)(1U << (target_record & 7U));
	authority->view.observed_bitmap_byte =
		mft_bitmap->observed_bitmap[bitmap_offset];
	authority->view.expected_bitmap_byte =
		mft_bitmap->expected_bitmap[bitmap_offset];
	if ((authority->view.observed_bitmap_byte & authority->view.bitmap_mask) ||
			(authority->view.expected_bitmap_byte &
			 authority->view.bitmap_mask)) {
		errno = EBUSY;
		goto fail;
	}
	memcpy(authority->view.raw_census_hash, raw->census_hash, 32U);
	memcpy(authority->view.mft_bitmap_census_hash,
		mft_bitmap->census_hash, 32U);
	memcpy(authority->view.namespace_census_hash,
		namespace_census->census_hash, 32U);
	if (rh_collect_components(components, component_count,
			correlation_generation, raw->slot_count, &authority->view, &wal) ||
			(writer ? rh_writer_exclusions(writer, wal, &authority->view) :
			 rh_reader_exclusions(reader, wal, &authority->view)) ||
			rh_collect_raw_references(raw, &authority->view))
		goto fail;
	rh_collect_namespace_references(namespace_census, &authority->view);
	if (authority->view.references_matched ||
			authority->view.extent_references_matched ||
			authority->view.allocation_owners_matched ||
			authority->view.owned_runs_matched) {
		errno = EBUSY;
		goto fail;
	}
	if (!raw->slot_count || raw->slots[FILE_MFT].state !=
			RH_RAW_SLOT_LIVE_BASE || !raw->slots[FILE_MFT].sequence ||
			target_record > UINT64_MAX / RH_FREE_SLOT_RAW_RECORD_SIZE) {
		errno = EIO;
		goto fail;
	}
	mft_owner.record = FILE_MFT;
	mft_owner.sequence = raw->slots[FILE_MFT].sequence;
	if (rh_raw_mft_map_stream_range(raw, mft_owner,
			le32_to_cpu(AT_BITMAP), NULL, 0U, bitmap_offset, 1U,
			&bitmap_physical_offset) ||
			bitmap_physical_offset >= reader->device_size ||
			rh_census_reader_read_exact(reader, bitmap_physical_offset, 1U,
				&current_bitmap_byte) || current_bitmap_byte !=
				authority->view.observed_bitmap_byte) {
		errno = EIO;
		goto fail;
	}
	authority->view.mft_bitmap_physical_offset = bitmap_physical_offset;
	if (rh_census_reader_range_excluded(reader, bitmap_physical_offset, 1U,
			&overlap))
		goto fail;
	if (overlap) {
		if (overlap > 0) {
			authority->view.wal_overlaps_matched++;
			errno = EPERM;
		}
		goto fail;
	}
	logical_offset = target_record * RH_FREE_SLOT_RAW_RECORD_SIZE;
	if (rh_raw_mft_map_stream_range(raw, mft_owner,
			le32_to_cpu(AT_DATA), NULL, 0U, logical_offset,
			RH_FREE_SLOT_RAW_RECORD_SIZE, &physical_offset) ||
			physical_offset > reader->device_size ||
			RH_FREE_SLOT_RAW_RECORD_SIZE >
				reader->device_size - physical_offset ||
			rh_census_reader_read_exact(reader, physical_offset,
				RH_FREE_SLOT_RAW_RECORD_SIZE, raw_before))
		goto fail;
	authority->view.physical_offset = physical_offset;
	if (rh_census_reader_range_excluded(reader, physical_offset,
			RH_FREE_SLOT_RAW_RECORD_SIZE, &overlap))
		goto fail;
	if (overlap) {
		if (overlap > 0) {
			authority->view.wal_overlaps_matched++;
			errno = EPERM;
		}
		goto fail;
	}
	rh_sha256(raw_before, sizeof(raw_before),
		authority->view.raw_before_hash);
	if (memcmp(authority->view.raw_before_hash, opaque->raw_before_hash,
			sizeof(authority->view.raw_before_hash))) {
		errno = EIO;
		goto fail;
	}
	if (rh_authority_compute_hash(&authority->view,
			authority->view.evidence_hash) || !rh_authority_valid(authority))
		goto fail;
	*output = authority;
	return 0;
fail:
	rh_free_slot_authority_destroy(authority);
	return -1;
}

int rh_free_slot_authority_create(struct rh_writer *writer,
		const struct rh_raw_mft_census *raw,
		const struct rh_mft_bitmap_census *mft_bitmap,
		const struct rh_namespace_census *namespace_census,
		uint64_t correlation_generation, uint64_t target_record,
		uint16_t intended_sequence,
		const struct rh_free_slot_component_seal *const *components,
		size_t component_count, struct rh_free_slot_authority **output)
{
	struct rh_census_reader reader;

	if (output)
		*output = NULL;
	if (!output || !writer || writer->operation_count ||
			writer->planned_bytes || writer->last_verified_ordinal ||
			writer->sync_count || writer->write_boundaries ||
			writer->commit_started || writer->commit_completed ||
			writer->write_fd >= 0 || rh_writer_plan_checkpoint(writer) != 0U ||
			rh_census_reader_from_writer_prefix(writer, 0U, &reader)) {
		errno = EINVAL;
		return -1;
	}
	return rh_free_slot_authority_create_reader_internal(&reader, writer,
		raw, mft_bitmap, namespace_census, correlation_generation,
		target_record, intended_sequence, components, component_count, output);
}

void rh_free_slot_authority_destroy(struct rh_free_slot_authority *authority)
{
	if (!authority)
		return;
	memset(authority, 0, sizeof(*authority));
	free(authority);
}

int rh_free_slot_authority_get_view(
		const struct rh_free_slot_authority *authority,
		struct rh_free_slot_authority_view *view)
{
	if (!view || !rh_authority_valid(authority)) {
		errno = EINVAL;
		return -1;
	}
	*view = authority->view;
	return 0;
}

int rh_free_slot_authority_equal(const struct rh_free_slot_authority *left,
		const struct rh_free_slot_authority *right)
{
	return rh_authority_valid(left) && rh_authority_valid(right) &&
		!memcmp(left->view.evidence_hash, right->view.evidence_hash, 32U);
}

int rh_free_slot_authority_rederive_equal(
		const struct rh_free_slot_authority *expected,
		struct rh_writer *writer, const struct rh_raw_mft_census *raw,
		const struct rh_mft_bitmap_census *mft_bitmap,
		const struct rh_namespace_census *namespace_census,
		uint64_t correlation_generation, uint64_t target_record,
		uint16_t intended_sequence,
		const struct rh_free_slot_component_seal *const *components,
		size_t component_count, int *equal)
{
	struct rh_free_slot_authority *rederived = NULL;
	int result = -1;

	if (equal)
		*equal = 0;
	if (!equal || !rh_authority_valid(expected)) {
		errno = EINVAL;
		return -1;
	}
	if (rh_free_slot_authority_create(writer, raw, mft_bitmap,
			namespace_census, correlation_generation, target_record,
			intended_sequence, components, component_count, &rederived))
		return -1;
	*equal = rh_free_slot_authority_equal(expected, rederived);
	result = 0;
	rh_free_slot_authority_destroy(rederived);
	return result;
}

int rh_free_slot_authority_rederive_evidence_equal(
		const unsigned char expected_evidence_hash[32],
		struct rh_writer *writer, const struct rh_raw_mft_census *raw,
		const struct rh_mft_bitmap_census *mft_bitmap,
		const struct rh_namespace_census *namespace_census,
		uint64_t correlation_generation, uint64_t target_record,
		uint16_t intended_sequence,
		const struct rh_free_slot_component_seal *const *components,
		size_t component_count, int *equal)
{
	struct rh_free_slot_authority *rederived = NULL;
	int result = -1;

	if (equal)
		*equal = 0;
	if (!equal || !expected_evidence_hash ||
			rh_hash_all_zero(expected_evidence_hash)) {
		errno = EINVAL;
		return -1;
	}
	if (rh_free_slot_authority_create(writer, raw, mft_bitmap,
			namespace_census, correlation_generation, target_record,
			intended_sequence, components, component_count, &rederived))
		return -1;
	*equal = !memcmp(expected_evidence_hash,
		rederived->view.evidence_hash, 32U);
	result = 0;
	rh_free_slot_authority_destroy(rederived);
	return result;
}

int rh_free_slot_authority_rederive_evidence_equal_reader(
		const unsigned char expected_evidence_hash[32],
		const struct rh_census_reader *reader,
		const struct rh_raw_mft_census *raw,
		const struct rh_mft_bitmap_census *mft_bitmap,
		const struct rh_namespace_census *namespace_census,
		uint64_t correlation_generation, uint64_t target_record,
		uint16_t intended_sequence,
		const struct rh_free_slot_component_seal *const *components,
		size_t component_count, int *equal)
{
	struct rh_free_slot_authority *rederived = NULL;
	int result = -1;

	if (equal)
		*equal = 0;
	if (!equal || !expected_evidence_hash ||
			rh_hash_all_zero(expected_evidence_hash)) {
		errno = EINVAL;
		return -1;
	}
	if (rh_free_slot_authority_create_reader_internal(reader, NULL, raw,
			mft_bitmap, namespace_census, correlation_generation,
			target_record, intended_sequence, components, component_count,
			&rederived))
		return -1;
	*equal = !memcmp(expected_evidence_hash,
		rederived->view.evidence_hash, 32U);
	result = 0;
	rh_free_slot_authority_destroy(rederived);
	return result;
}
