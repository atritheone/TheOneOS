/* ROOTHEALTH_REPAIR_ROLE(DIAGNOSTIC) ROOTHEALTH_IO_ROLE(PLANNER) */
#include "config.h"

#include <errno.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include "roothealth_free_slot_authority.h"
#include "roothealth_free_slot_authority_internal.h"
#include "roothealth_hash_stream.h"
#include "roothealth_native_authority.h"
#include "roothealth_replay_analysis_internal.h"

#define RH_NATIVE_CENSUS_MAGIC UINT64_C(0x52484e415443454e)
#define RH_NATIVE_MFT_RECORD_MAX UINT64_C(0x0000ffffffffffff)

struct rh_native_open_manifest {
	uint32_t key;
	uint32_t type;
	uint64_t file_reference;
	uint32_t bytes_per_index;
	uint64_t open_lsn;
	uint64_t source_lsn;
	uint16_t name_bytes;
	uint8_t source_kind;
	unsigned char name_utf16le[RH_REPLAY_NATIVE_NAME_MAX];
	unsigned char name_hash[32];
};

struct rh_native_target_manifest {
	uint64_t source_ordinal;
	uint64_t this_lsn;
	uint64_t previous_lsn;
	uint64_t undo_next_lsn;
	uint64_t file_reference;
	uint64_t target_vcn;
	uint64_t first_lcn;
	uint64_t effective_lcn;
	uint64_t target_slice_offset;
	uint64_t target_object_size;
	uint64_t open_lsn;
	uint32_t transaction_id;
	uint32_t open_key;
	uint32_t attribute_type;
	uint32_t bytes_per_index;
	uint32_t record_type;
	uint32_t action_class;
	uint16_t redo_operation;
	uint16_t undo_operation;
	uint16_t redo_length;
	uint16_t undo_length;
	uint8_t plan_flags;
	uint8_t has_effective_lcn;
	unsigned char attribute_name_hash[32];
	unsigned char redo_hash[32];
	unsigned char undo_hash[32];
};

struct rh_native_control_manifest {
	uint64_t source_ordinal;
	uint64_t this_lsn;
	uint64_t previous_lsn;
	uint64_t undo_next_lsn;
	uint64_t target_vcn;
	uint64_t first_lcn;
	uint64_t file_reference;
	uint64_t checkpoint_analysis_start_lsn;
	uint64_t checkpoint_table_lsn[4];
	uint32_t checkpoint_table_length[4];
	uint32_t transaction_id;
	uint32_t open_key;
	uint32_t attribute_type;
	uint32_t record_type;
	uint32_t action_class;
	uint16_t redo_operation;
	uint16_t undo_operation;
	uint16_t redo_length;
	uint16_t undo_length;
	uint8_t has_open_attribute;
	unsigned char attribute_name_hash[32];
	unsigned char record_hash[32];
};

struct rh_native_authority_census {
	uint64_t magic;
	struct rh_native_authority_census_view view;
	struct rh_native_open_manifest *opens;
	size_t open_count;
	struct rh_native_target_manifest *targets;
	size_t target_count;
	struct rh_native_control_manifest *controls;
	size_t control_count;
};

struct rh_native_build_context {
	uint64_t correlation_generation;
	struct rh_native_authority_census **output;
};

static uint16_t rh_rd16(const unsigned char *bytes)
{
	return (uint16_t)bytes[0] | ((uint16_t)bytes[1] << 8);
}

static uint32_t rh_rd32(const unsigned char *bytes)
{
	return (uint32_t)bytes[0] | ((uint32_t)bytes[1] << 8) |
		((uint32_t)bytes[2] << 16) | ((uint32_t)bytes[3] << 24);
}

static uint64_t rh_rd64(const unsigned char *bytes)
{
	return (uint64_t)rh_rd32(bytes) | ((uint64_t)rh_rd32(bytes + 4) << 32);
}

static int rh_hash_zero(const unsigned char hash[32])
{
	size_t i;

	for (i = 0; i < 32U; i++)
		if (hash[i])
			return 0;
	return 1;
}

static int rh_h_bytes(struct rh_hash_stream *hash, const void *bytes,
		size_t length)
{
	return rh_hash_stream_update(hash, bytes, length);
}

static int rh_h_u8(struct rh_hash_stream *hash, uint8_t value)
{
	return rh_h_bytes(hash, &value, 1U);
}

static int rh_h_u16(struct rh_hash_stream *hash, uint16_t value)
{
	unsigned char encoded[2] = {
		(unsigned char)value, (unsigned char)(value >> 8)
	};

	return rh_h_bytes(hash, encoded, sizeof(encoded));
}

static int rh_h_u32(struct rh_hash_stream *hash, uint32_t value)
{
	unsigned char encoded[4];
	unsigned int i;

	for (i = 0; i < 4U; i++)
		encoded[i] = (unsigned char)(value >> (8U * i));
	return rh_h_bytes(hash, encoded, sizeof(encoded));
}

static int rh_h_u64(struct rh_hash_stream *hash, uint64_t value)
{
	unsigned char encoded[8];
	unsigned int i;

	for (i = 0; i < 8U; i++)
		encoded[i] = (unsigned char)(value >> (8U * i));
	return rh_h_bytes(hash, encoded, sizeof(encoded));
}

static int rh_digest(const void *bytes, size_t length,
		unsigned char output[32])
{
	struct rh_hash_stream hash;

	rh_hash_stream_init(&hash);
	return rh_hash_stream_update(&hash, bytes, length) ||
		rh_hash_stream_final(&hash, output) ? -1 : 0;
}

static int rh_file_reference_valid(uint64_t reference)
{
	return (reference & RH_NATIVE_MFT_RECORD_MAX) <=
		RH_NATIVE_MFT_RECORD_MAX && (uint16_t)(reference >> 48) != 0;
}

static int rh_is_mutation(enum rh_replay_action_class action_class)
{
	return action_class == RH_REPLAY_ACTION_MFT_WRITE ||
		action_class == RH_REPLAY_ACTION_INDX_WRITE ||
		action_class == RH_REPLAY_ACTION_RAW_WRITE ||
		action_class == RH_REPLAY_ACTION_BITMAP_WRITE;
}

static int rh_open_compare(const void *left_pointer,
		const void *right_pointer)
{
	const struct rh_native_open_manifest *left = left_pointer;
	const struct rh_native_open_manifest *right = right_pointer;
	int compared;

	if (left->key != right->key)
		return left->key < right->key ? -1 : 1;
	if (left->type != right->type)
		return left->type < right->type ? -1 : 1;
	if (left->file_reference != right->file_reference)
		return left->file_reference < right->file_reference ? -1 : 1;
	if (left->name_bytes != right->name_bytes)
		return left->name_bytes < right->name_bytes ? -1 : 1;
	compared = memcmp(left->name_utf16le, right->name_utf16le,
		left->name_bytes);
	return compared < 0 ? -1 : compared > 0;
}

static int rh_target_compare(const void *left_pointer,
		const void *right_pointer)
{
	const struct rh_native_target_manifest *left = left_pointer;
	const struct rh_native_target_manifest *right = right_pointer;

	if (left->this_lsn != right->this_lsn)
		return left->this_lsn < right->this_lsn ? -1 : 1;
	if (left->source_ordinal != right->source_ordinal)
		return left->source_ordinal < right->source_ordinal ? -1 : 1;
	return 0;
}

static int rh_control_compare(const void *left_pointer,
		const void *right_pointer)
{
	const struct rh_native_control_manifest *left = left_pointer;
	const struct rh_native_control_manifest *right = right_pointer;

	if (left->this_lsn != right->this_lsn)
		return left->this_lsn < right->this_lsn ? -1 : 1;
	if (left->source_ordinal != right->source_ordinal)
		return left->source_ordinal < right->source_ordinal ? -1 : 1;
	return 0;
}

static const struct rh_native_open_manifest *rh_find_open(
		const struct rh_native_authority_census *census, uint32_t key)
{
	size_t i;

	for (i = 0; i < census->open_count; i++)
		if (census->opens[i].key == key)
			return &census->opens[i];
	return NULL;
}

static int rh_hash_source(const struct rh_replay_analysis_export *completed,
		unsigned char output[32])
{
	struct rh_hash_stream hash;
	const struct rh_replay_geometry *geometry = completed->geometry;
	size_t i;

	rh_hash_stream_init(&hash);
	if (rh_h_bytes(&hash, "RHNATS1\0", 8U) ||
			rh_h_u64(&hash, completed->record_count) ||
			rh_h_u32(&hash, geometry->page_size) ||
			rh_h_u32(&hash, geometry->cluster_size) ||
			rh_h_u32(&hash, geometry->mft_record_size) ||
			rh_h_u32(&hash, geometry->index_record_size) ||
			rh_h_u64(&hash, geometry->logfile_size) ||
			rh_h_u64(&hash, geometry->volume_clusters) ||
			rh_h_u32(&hash, geometry->sequence_bits) ||
			rh_h_u16(&hash, geometry->client_sequence) ||
			rh_h_u16(&hash, geometry->client_index) ||
			rh_h_u64(&hash, completed->synced_lsn) ||
			rh_h_u64(&hash, completed->committed_lsn) ||
			rh_h_u64(&hash, completed->analysis_start_lsn))
		return -1;
	for (i = 0; i < completed->record_count; i++) {
		const struct rh_replay_analysis_record *record =
			&completed->records[i];

		if (rh_h_u64(&hash, i) || rh_h_u64(&hash, record->size) ||
				rh_h_bytes(&hash, record->bytes, record->size) ||
				rh_h_u32(&hash, record->plan_flags) ||
				rh_h_u8(&hash, (uint8_t)record->has_effective_lcn) ||
				rh_h_u64(&hash, record->effective_lcn))
			return -1;
	}
	return rh_hash_stream_final(&hash, output);
}

static int rh_hash_evidence(const struct rh_native_authority_census *census,
		unsigned char output[32])
{
	const struct rh_native_authority_census_view *view = &census->view;
	struct rh_hash_stream hash;
	size_t i, j;

	rh_hash_stream_init(&hash);
	if (rh_h_bytes(&hash, "RHNATE1\0", 8U) ||
			rh_h_u32(&hash, view->version) ||
			rh_h_u64(&hash, view->records_expected) ||
			rh_h_u64(&hash, view->records_completed) ||
			rh_h_u64(&hash, view->unknown_records) ||
			rh_h_u64(&hash, view->unsupported_records) ||
			rh_h_u64(&hash, view->error_records) ||
			rh_h_u64(&hash, view->open_attributes_expected) ||
			rh_h_u64(&hash, view->open_attributes_completed) ||
			rh_h_u64(&hash, view->targets_expected) ||
			rh_h_u64(&hash, view->targets_completed) ||
			rh_h_u64(&hash, view->controls_expected) ||
			rh_h_u64(&hash, view->controls_completed) ||
			rh_h_u64(&hash, view->redo_records) ||
			rh_h_u64(&hash, view->undo_records) ||
			rh_h_u64(&hash, view->checkpoint_records) ||
			rh_h_u64(&hash, view->transaction_tables) ||
			rh_h_u64(&hash, view->open_attribute_tables) ||
			rh_h_u64(&hash, view->attribute_name_tables) ||
			rh_h_u64(&hash, view->dirty_page_tables) ||
			rh_h_u64(&hash, view->dynamic_open_attributes) ||
			rh_h_u64(&hash, view->delete_dirty_controls) ||
			rh_h_u64(&hash, view->hotfix_controls) ||
			rh_h_u64(&hash, view->mutation_records) ||
			rh_h_u64(&hash, view->winner_redos) ||
			rh_h_u64(&hash, view->loser_redos) ||
			rh_h_u64(&hash, view->loser_undos) ||
			rh_h_u8(&hash, view->checked) || rh_h_u8(&hash, view->complete) ||
			rh_h_bytes(&hash, view->source_hash, 32U))
		return -1;
	for (i = 0; i < census->open_count; i++) {
		const struct rh_native_open_manifest *open = &census->opens[i];

		if (rh_h_bytes(&hash, "OPEN", 4U) || rh_h_u32(&hash, open->key) ||
				rh_h_u32(&hash, open->type) ||
				rh_h_u64(&hash, open->file_reference) ||
				rh_h_u32(&hash, open->bytes_per_index) ||
				rh_h_u64(&hash, open->open_lsn) ||
				rh_h_u64(&hash, open->source_lsn) ||
				rh_h_u16(&hash, open->name_bytes) ||
				rh_h_u8(&hash, open->source_kind) ||
				rh_h_bytes(&hash, open->name_utf16le, open->name_bytes) ||
				rh_h_bytes(&hash, open->name_hash, 32U))
			return -1;
	}
	for (i = 0; i < census->target_count; i++) {
		const struct rh_native_target_manifest *target = &census->targets[i];

		if (rh_h_bytes(&hash, "TARG", 4U) ||
				rh_h_u64(&hash, target->source_ordinal) ||
				rh_h_u64(&hash, target->this_lsn) ||
				rh_h_u64(&hash, target->previous_lsn) ||
				rh_h_u64(&hash, target->undo_next_lsn) ||
				rh_h_u64(&hash, target->file_reference) ||
				rh_h_u64(&hash, target->target_vcn) ||
				rh_h_u64(&hash, target->first_lcn) ||
				rh_h_u64(&hash, target->effective_lcn) ||
				rh_h_u64(&hash, target->target_slice_offset) ||
				rh_h_u64(&hash, target->target_object_size) ||
				rh_h_u64(&hash, target->open_lsn) ||
				rh_h_u32(&hash, target->transaction_id) ||
				rh_h_u32(&hash, target->open_key) ||
				rh_h_u32(&hash, target->attribute_type) ||
				rh_h_u32(&hash, target->bytes_per_index) ||
				rh_h_u32(&hash, target->record_type) ||
				rh_h_u32(&hash, target->action_class) ||
				rh_h_u16(&hash, target->redo_operation) ||
				rh_h_u16(&hash, target->undo_operation) ||
				rh_h_u16(&hash, target->redo_length) ||
				rh_h_u16(&hash, target->undo_length) ||
				rh_h_u8(&hash, target->plan_flags) ||
				rh_h_u8(&hash, target->has_effective_lcn) ||
				rh_h_bytes(&hash, target->attribute_name_hash, 32U) ||
				rh_h_bytes(&hash, target->redo_hash, 32U) ||
				rh_h_bytes(&hash, target->undo_hash, 32U))
			return -1;
	}
	for (i = 0; i < census->control_count; i++) {
		const struct rh_native_control_manifest *control = &census->controls[i];

		if (rh_h_bytes(&hash, "CTRL", 4U) ||
				rh_h_u64(&hash, control->source_ordinal) ||
				rh_h_u64(&hash, control->this_lsn) ||
				rh_h_u64(&hash, control->previous_lsn) ||
				rh_h_u64(&hash, control->undo_next_lsn) ||
				rh_h_u64(&hash, control->target_vcn) ||
				rh_h_u64(&hash, control->first_lcn) ||
				rh_h_u64(&hash, control->file_reference) ||
				rh_h_u64(&hash, control->checkpoint_analysis_start_lsn))
			return -1;
		for (j = 0; j < 4U; j++)
			if (rh_h_u64(&hash, control->checkpoint_table_lsn[j]) ||
					rh_h_u32(&hash,
						control->checkpoint_table_length[j]))
				return -1;
		if (rh_h_u32(&hash, control->transaction_id) ||
				rh_h_u32(&hash, control->open_key) ||
				rh_h_u32(&hash, control->attribute_type) ||
				rh_h_u32(&hash, control->record_type) ||
				rh_h_u32(&hash, control->action_class) ||
				rh_h_u16(&hash, control->redo_operation) ||
				rh_h_u16(&hash, control->undo_operation) ||
				rh_h_u16(&hash, control->redo_length) ||
				rh_h_u16(&hash, control->undo_length) ||
				rh_h_u8(&hash, control->has_open_attribute) ||
				rh_h_bytes(&hash, control->attribute_name_hash, 32U) ||
				rh_h_bytes(&hash, control->record_hash, 32U))
			return -1;
	}
	return rh_hash_stream_final(&hash, output);
}

static int rh_census_valid(const struct rh_native_authority_census *census)
{
	unsigned char evidence_hash[32];
	uint64_t redo = 0, undo = 0;
	size_t i;

	if (!census || census->magic != RH_NATIVE_CENSUS_MAGIC ||
			census->view.version != RH_NATIVE_AUTHORITY_CENSUS_VERSION ||
			!census->view.correlation_generation || !census->view.checked ||
			!census->view.complete || census->view.unknown_records ||
			census->view.unsupported_records || census->view.error_records ||
			census->view.records_completed != census->view.records_expected ||
			census->view.open_attributes_completed !=
				census->view.open_attributes_expected ||
			census->view.targets_completed != census->view.targets_expected ||
			census->view.controls_completed != census->view.controls_expected ||
			census->view.mutation_records != census->view.targets_completed ||
			census->view.redo_records != census->view.winner_redos +
				census->view.loser_redos ||
			census->view.undo_records != census->view.loser_undos ||
			census->open_count != census->view.open_attributes_completed ||
			census->target_count != census->view.targets_completed ||
			census->control_count != census->view.controls_completed ||
			(census->open_count && !census->opens) ||
			(census->target_count && !census->targets) ||
			(census->control_count && !census->controls) ||
			rh_hash_zero(census->view.source_hash) ||
			rh_hash_zero(census->view.evidence_hash))
		return 0;
	for (i = 0; i < census->open_count; i++) {
		const struct rh_native_open_manifest *open = &census->opens[i];
		unsigned char name_hash[32];

		if (!open->key || !open->type || (open->type & 0xfU) ||
				open->type > 0x100U || !rh_file_reference_valid(
					open->file_reference) || open->name_bytes >
					RH_REPLAY_NATIVE_NAME_MAX || (open->name_bytes & 1U) ||
				(open->source_kind != 1U && open->source_kind != 2U) ||
				(i && census->opens[i - 1U].key >= open->key))
			return 0;
		if (rh_digest(open->name_utf16le, open->name_bytes, name_hash))
			return 0;
		if (memcmp(name_hash, open->name_hash, 32U))
			return 0;
	}
	for (i = 0; i < census->target_count; i++) {
		const struct rh_native_target_manifest *target = &census->targets[i];
		const struct rh_native_open_manifest *open =
			rh_find_open(census, target->open_key);

		if (target->source_ordinal >= census->view.records_expected ||
				!target->this_lsn || !target->open_key || !open ||
				!rh_file_reference_valid(target->file_reference) ||
				target->file_reference != open->file_reference ||
				target->attribute_type != open->type ||
				target->bytes_per_index != open->bytes_per_index ||
				target->open_lsn != open->open_lsn ||
				memcmp(target->attribute_name_hash, open->name_hash, 32U) ||
				!rh_is_mutation((enum rh_replay_action_class)
					target->action_class) ||
				(target->plan_flags & ~(RH_REPLAY_PLAN_REDO |
					RH_REPLAY_PLAN_UNDO)) ||
				(target->plan_flags && !target->has_effective_lcn) ||
				(i && rh_target_compare(&census->targets[i - 1U], target) >= 0))
			return 0;
		if (target->plan_flags & RH_REPLAY_PLAN_REDO)
			redo++;
		if (target->plan_flags & RH_REPLAY_PLAN_UNDO)
			undo++;
	}
	for (i = 0; i < census->control_count; i++) {
		const struct rh_native_control_manifest *control = &census->controls[i];
		const struct rh_native_open_manifest *open = control->has_open_attribute ?
			rh_find_open(census, control->open_key) : NULL;

		if (control->source_ordinal >= census->view.records_expected ||
				!control->this_lsn ||
				(control->action_class != RH_REPLAY_ACTION_CHECKPOINT &&
				 control->action_class != RH_REPLAY_ACTION_CONTROL &&
				 control->action_class != RH_REPLAY_ACTION_TRANSACTION_END) ||
				(control->has_open_attribute &&
				 (!control->open_key || !open || !rh_file_reference_valid(
					control->file_reference) ||
				  control->file_reference != open->file_reference ||
				  control->attribute_type != open->type ||
				  memcmp(control->attribute_name_hash, open->name_hash, 32U))) ||
				(i && rh_control_compare(&census->controls[i - 1U],
					control) >= 0))
			return 0;
	}
	if (redo != census->view.redo_records ||
			undo != census->view.undo_records ||
			rh_hash_evidence(census, evidence_hash) ||
			memcmp(evidence_hash, census->view.evidence_hash, 32U))
		return 0;
	return 1;
}

static int rh_build_completed(
		const struct rh_replay_analysis_export *completed, void *opaque)
{
	struct rh_native_build_context *context = opaque;
	struct rh_native_authority_census *census = NULL;
	size_t i, open_count = 0, target_count = 0, control_count = 0;
	size_t open_at = 0, target_at = 0, control_at = 0;
	uint64_t redo_count = 0, undo_count = 0;

	if (!context || !context->output || !context->correlation_generation ||
			!completed || !completed->records || !completed->views ||
			!completed->record_count || !completed->geometry ||
			!completed->result || !completed->open_attributes) {
		errno = EINVAL;
		return -1;
	}
	for (i = 0; i < completed->open_attribute_capacity; i++)
		if (completed->open_attributes[i].present)
			open_count++;
	for (i = 0; i < completed->record_count; i++) {
		const struct rh_replay_action_view *view = &completed->views[i];

		if (rh_is_mutation(view->action_class)) {
			if (view->this_lsn >= completed->analysis_start_lsn)
				target_count++;
		} else if (view->action_class == RH_REPLAY_ACTION_CHECKPOINT ||
				view->action_class == RH_REPLAY_ACTION_CONTROL ||
				view->action_class == RH_REPLAY_ACTION_TRANSACTION_END) {
			control_count++;
		} else {
			errno = ENOTSUP;
			return -1;
		}
	}
	if (target_count != completed->result->mutation_records ||
			open_count > SIZE_MAX / sizeof(*census->opens) ||
			target_count > SIZE_MAX / sizeof(*census->targets) ||
			control_count > SIZE_MAX / sizeof(*census->controls)) {
		errno = EIO;
		return -1;
	}
	census = calloc(1, sizeof(*census));
	if (!census)
		return -1;
	if (open_count)
		census->opens = calloc(open_count, sizeof(*census->opens));
	if (target_count)
		census->targets = calloc(target_count, sizeof(*census->targets));
	if (control_count)
		census->controls = calloc(control_count, sizeof(*census->controls));
	if ((open_count && !census->opens) ||
			(target_count && !census->targets) ||
			(control_count && !census->controls))
		goto fail;
	census->magic = RH_NATIVE_CENSUS_MAGIC;
	census->open_count = open_count;
	census->target_count = target_count;
	census->control_count = control_count;
	for (i = 0; i < completed->open_attribute_capacity; i++) {
		const struct rh_open_attribute *source =
			&completed->open_attributes[i];
		struct rh_native_open_manifest *open;

		if (!source->present)
			continue;
		if (!source->key || !source->type ||
				!rh_file_reference_valid(source->file_reference) ||
				source->name_bytes > RH_REPLAY_NATIVE_NAME_MAX ||
				(source->name_bytes & 1U) ||
				!!source->expects_name != !!source->name_bytes ||
				!!source->name_present != !!source->name_bytes ||
				(source->source_kind != 1U && source->source_kind != 2U)) {
			errno = EIO;
			goto fail;
		}
		open = &census->opens[open_at++];
		open->key = source->key;
		open->type = source->type;
		open->file_reference = source->file_reference;
		open->bytes_per_index = source->bytes_per_index;
		open->open_lsn = source->open_lsn;
		open->source_lsn = source->source_lsn;
		open->name_bytes = source->name_bytes;
		open->source_kind = source->source_kind;
		memcpy(open->name_utf16le, source->name_utf16le,
			source->name_bytes);
		if (rh_digest(open->name_utf16le, open->name_bytes,
				open->name_hash))
			goto fail;
	}
	qsort(census->opens, census->open_count, sizeof(*census->opens),
		rh_open_compare);
	for (i = 1; i < census->open_count; i++)
		if (census->opens[i - 1U].key == census->opens[i].key) {
			errno = EIO;
			goto fail;
		}
	for (i = 0; i < completed->record_count; i++) {
		const struct rh_replay_analysis_record *record =
			&completed->records[i];
		const struct rh_replay_action_view *view = &completed->views[i];

		if (rh_is_mutation(view->action_class) &&
				view->this_lsn >= completed->analysis_start_lsn) {
			struct rh_native_target_manifest *target =
				&census->targets[target_at++];
			const struct rh_native_open_manifest *open;
			uint32_t key;

			if (record->size < 62U) {
				errno = EIO;
				goto fail;
			}
			key = rh_rd16(record->bytes + 60U);
			open = rh_find_open(census, key);
			if (!open || (record->plan_flags && !record->has_effective_lcn)) {
				errno = EIO;
				goto fail;
			}
			target->source_ordinal = i;
			target->this_lsn = view->this_lsn;
			target->previous_lsn = view->previous_lsn;
			target->undo_next_lsn = view->undo_next_lsn;
			target->file_reference = open->file_reference;
			target->target_vcn = view->target_vcn;
			target->first_lcn = view->first_lcn;
			target->effective_lcn = record->effective_lcn;
			target->target_slice_offset = view->target_slice_offset;
			target->target_object_size = view->target_object_size;
			target->open_lsn = open->open_lsn;
			target->transaction_id = view->transaction_id;
			target->open_key = key;
			target->attribute_type = open->type;
			target->bytes_per_index = open->bytes_per_index;
			target->record_type = view->record_type;
			target->action_class = (uint32_t)view->action_class;
			target->redo_operation = view->redo_operation;
			target->undo_operation = view->undo_operation;
			target->redo_length = view->redo_length;
			target->undo_length = view->undo_length;
			target->plan_flags = (uint8_t)record->plan_flags;
			target->has_effective_lcn =
				(uint8_t)record->has_effective_lcn;
			memcpy(target->attribute_name_hash, open->name_hash, 32U);
			if (rh_digest(record->bytes + view->redo_data_offset,
					view->redo_length, target->redo_hash) ||
					rh_digest(record->bytes + view->undo_data_offset,
					view->undo_length, target->undo_hash))
				goto fail;
			if (record->plan_flags & RH_REPLAY_PLAN_REDO)
				redo_count++;
			if (record->plan_flags & RH_REPLAY_PLAN_UNDO)
				undo_count++;
			continue;
		}
		if (!rh_is_mutation(view->action_class)) {
			struct rh_native_control_manifest *control =
				&census->controls[control_at++];
			const struct rh_native_open_manifest *open = NULL;

			control->source_ordinal = i;
			control->this_lsn = view->this_lsn;
			control->previous_lsn = view->previous_lsn;
			control->undo_next_lsn = view->undo_next_lsn;
			control->target_vcn = view->target_vcn;
			control->first_lcn = view->first_lcn;
			control->transaction_id = view->transaction_id;
			control->record_type = view->record_type;
			control->action_class = (uint32_t)view->action_class;
			control->redo_operation = view->redo_operation;
			control->undo_operation = view->undo_operation;
			control->redo_length = view->redo_length;
			control->undo_length = view->undo_length;
			if ((view->redo_operation == 23U ||
					view->redo_operation == 28U) && record->size >= 62U) {
				control->open_key = rh_rd16(record->bytes + 60U);
				open = rh_find_open(census, control->open_key);
				if (!open) {
					errno = EIO;
					goto fail;
				}
				control->has_open_attribute = 1U;
				control->file_reference = open->file_reference;
				control->attribute_type = open->type;
				memcpy(control->attribute_name_hash, open->name_hash, 32U);
			}
			if (view->action_class == RH_REPLAY_ACTION_CHECKPOINT) {
				size_t j;

				if (record->size < 112U) {
					errno = EIO;
					goto fail;
				}
				control->checkpoint_analysis_start_lsn =
					rh_rd64(record->bytes + 56U);
				for (j = 0; j < 4U; j++) {
					control->checkpoint_table_lsn[j] =
						rh_rd64(record->bytes + 64U + 8U * j);
					control->checkpoint_table_length[j] =
						rh_rd32(record->bytes + 96U + 4U * j);
				}
			}
			if (rh_digest(record->bytes, record->size,
					control->record_hash))
				goto fail;
		}
	}
	if (open_at != open_count || target_at != target_count ||
			control_at != control_count ||
			redo_count != (uint64_t)completed->result->winner_redos +
				completed->result->loser_redos ||
			undo_count != completed->result->loser_undos) {
		errno = EIO;
		goto fail;
	}
	qsort(census->targets, census->target_count, sizeof(*census->targets),
		rh_target_compare);
	qsort(census->controls, census->control_count, sizeof(*census->controls),
		rh_control_compare);
	census->view.version = RH_NATIVE_AUTHORITY_CENSUS_VERSION;
	census->view.correlation_generation = context->correlation_generation;
	census->view.records_expected = completed->record_count;
	census->view.records_completed = completed->record_count;
	census->view.open_attributes_expected = open_count;
	census->view.open_attributes_completed = open_count;
	census->view.targets_expected = target_count;
	census->view.targets_completed = target_count;
	census->view.controls_expected = control_count;
	census->view.controls_completed = control_count;
	census->view.redo_records = redo_count;
	census->view.undo_records = undo_count;
	census->view.checkpoint_records = completed->result->checkpoint_records;
	census->view.transaction_tables = completed->result->transaction_tables;
	census->view.open_attribute_tables =
		completed->result->open_attribute_tables;
	census->view.attribute_name_tables =
		completed->result->attribute_name_tables;
	census->view.dirty_page_tables = completed->result->dirty_page_tables;
	census->view.dynamic_open_attributes =
		completed->result->dynamic_open_attributes;
	census->view.delete_dirty_controls =
		completed->result->delete_dirty_controls;
	census->view.hotfix_controls = completed->result->hotfix_controls;
	census->view.mutation_records = completed->result->mutation_records;
	census->view.winner_redos = completed->result->winner_redos;
	census->view.loser_redos = completed->result->loser_redos;
	census->view.loser_undos = completed->result->loser_undos;
	census->view.checked = 1U;
	census->view.complete = 1U;
	if (rh_hash_source(completed, census->view.source_hash) ||
			rh_hash_evidence(census, census->view.evidence_hash) ||
			!rh_census_valid(census))
		goto fail;
	*context->output = census;
	return 0;
fail:
	rh_native_authority_census_destroy(census);
	return -1;
}

int rh_replay_analysis_plan_native(
		struct rh_replay_analysis_record *records, size_t record_count,
		const struct rh_replay_geometry *geometry, uint64_t synced_lsn,
		uint64_t committed_lsn, uint64_t correlation_generation,
		struct rh_replay_analysis_result *result,
		struct rh_native_authority_census **census)
{
	struct rh_native_build_context context;

	if (census)
		*census = NULL;
	if (!census || !correlation_generation) {
		errno = EINVAL;
		return -1;
	}
	context.correlation_generation = correlation_generation;
	context.output = census;
	if (rh_replay_analysis_plan_export(records, record_count, geometry,
			synced_lsn, committed_lsn, rh_build_completed, &context, result)) {
		rh_native_authority_census_destroy(*census);
		*census = NULL;
		return -1;
	}
	return 0;
}

void rh_native_authority_census_destroy(
		struct rh_native_authority_census *census)
{
	if (!census)
		return;
	free(census->controls);
	free(census->targets);
	free(census->opens);
	memset(census, 0, sizeof(*census));
	free(census);
}

int rh_native_authority_census_get_view(
		const struct rh_native_authority_census *census,
		struct rh_native_authority_census_view *view)
{
	if (!view || !rh_census_valid(census)) {
		errno = EINVAL;
		return -1;
	}
	*view = census->view;
	return 0;
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

static int rh_reference_append(struct rh_free_slot_reference *references,
		size_t capacity, size_t *count, uint64_t file_reference)
{
	if (!rh_file_reference_valid(file_reference) || *count >= capacity) {
		errno = EIO;
		return -1;
	}
	references[*count].record = file_reference & RH_NATIVE_MFT_RECORD_MAX;
	references[*count].sequence = (uint16_t)(file_reference >> 48);
	(*count)++;
	return 0;
}

static size_t rh_reference_deduplicate(
		struct rh_free_slot_reference *references, size_t count)
{
	size_t input, output = 0;

	qsort(references, count, sizeof(*references), rh_reference_compare);
	for (input = 0; input < count; input++)
		if (!output || rh_reference_compare(&references[output - 1U],
				&references[input]))
			references[output++] = references[input];
	return output;
}

static int rh_native_component_create(
		const struct rh_native_authority_census *census,
		enum rh_free_slot_component_kind kind,
		struct rh_free_slot_component_seal **seal)
{
	struct rh_free_slot_reference *references = NULL;
	size_t capacity, count = 0, i;
	int result;

	if (seal)
		*seal = NULL;
	if (!seal || !rh_census_valid(census) ||
			(kind != RH_FREE_SLOT_COMPONENT_NATIVE_OPEN_ATTRIBUTE &&
			 kind != RH_FREE_SLOT_COMPONENT_NATIVE_TARGET &&
			 kind != RH_FREE_SLOT_COMPONENT_NATIVE_CONTROL)) {
		errno = EINVAL;
		return -1;
	}
	capacity = kind == RH_FREE_SLOT_COMPONENT_NATIVE_OPEN_ATTRIBUTE ?
		census->open_count : kind == RH_FREE_SLOT_COMPONENT_NATIVE_TARGET ?
		census->target_count : census->control_count;
	if (capacity > SIZE_MAX / sizeof(*references)) {
		errno = EOVERFLOW;
		return -1;
	}
	if (capacity) {
		references = malloc(capacity * sizeof(*references));
		if (!references)
			return -1;
	}
	if (kind == RH_FREE_SLOT_COMPONENT_NATIVE_OPEN_ATTRIBUTE) {
		for (i = 0; i < census->open_count; i++)
			if (rh_reference_append(references, capacity, &count,
					census->opens[i].file_reference))
				goto fail;
	} else if (kind == RH_FREE_SLOT_COMPONENT_NATIVE_TARGET) {
		for (i = 0; i < census->target_count; i++)
			if (rh_reference_append(references, capacity, &count,
					census->targets[i].file_reference))
				goto fail;
	} else {
		for (i = 0; i < census->control_count; i++)
			if (census->controls[i].has_open_attribute &&
					rh_reference_append(references, capacity, &count,
						census->controls[i].file_reference))
				goto fail;
	}
	count = rh_reference_deduplicate(references, count);
	if (kind == RH_FREE_SLOT_COMPONENT_NATIVE_OPEN_ATTRIBUTE)
		result = rh_free_slot_friend_native_open_attribute_seal(
			census->view.correlation_generation, census->open_count,
			census->open_count, census->view.evidence_hash, references,
			count, seal);
	else if (kind == RH_FREE_SLOT_COMPONENT_NATIVE_TARGET)
		result = rh_free_slot_friend_native_target_seal(
			census->view.correlation_generation, census->target_count,
			census->target_count, census->view.evidence_hash, references,
			count, seal);
	else
		result = rh_free_slot_friend_native_control_seal(
			census->view.correlation_generation, census->control_count,
			census->control_count, census->view.evidence_hash, references,
			count, seal);
	free(references);
	return result;
fail:
	free(references);
	return -1;
}

int rh_native_open_attribute_component_seal_create(
		const struct rh_native_authority_census *census,
		struct rh_free_slot_component_seal **seal)
{
	return rh_native_component_create(census,
		RH_FREE_SLOT_COMPONENT_NATIVE_OPEN_ATTRIBUTE, seal);
}

int rh_native_target_component_seal_create(
		const struct rh_native_authority_census *census,
		struct rh_free_slot_component_seal **seal)
{
	return rh_native_component_create(census,
		RH_FREE_SLOT_COMPONENT_NATIVE_TARGET, seal);
}

int rh_native_control_component_seal_create(
		const struct rh_native_authority_census *census,
		struct rh_free_slot_component_seal **seal)
{
	return rh_native_component_create(census,
		RH_FREE_SLOT_COMPONENT_NATIVE_CONTROL, seal);
}

#ifdef ROOTHEALTH_REPAIR_TESTING
int rh_native_authority_test_tamper(
		struct rh_native_authority_census *census,
		enum rh_native_authority_test_tamper tamper)
{
	if (!census || census->magic != RH_NATIVE_CENSUS_MAGIC) {
		errno = EINVAL;
		return -1;
	}
	switch (tamper) {
	case RH_NATIVE_TEST_TAMPER_SOURCE_HASH:
		census->view.source_hash[0] ^= 0x80U;
		break;
	case RH_NATIVE_TEST_TAMPER_OPEN_COUNT:
		census->view.open_attributes_completed++;
		break;
	case RH_NATIVE_TEST_TAMPER_TARGET_REFERENCE:
		if (!census->target_count) {
			errno = EINVAL;
			return -1;
		}
		census->targets[0].file_reference ^= 1U;
		break;
	case RH_NATIVE_TEST_TAMPER_UNKNOWN_COUNT:
		census->view.unknown_records++;
		break;
	case RH_NATIVE_TEST_TAMPER_MANIFEST_OMISSION:
		if (!census->target_count) {
			errno = EINVAL;
			return -1;
		}
		census->target_count--;
		break;
	default:
		errno = EINVAL;
		return -1;
	}
	return 0;
}
#endif
