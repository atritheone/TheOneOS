/* ROOTHEALTH_REPAIR_ROLE(DIAGNOSTIC) ROOTHEALTH_IO_ROLE(READER) */
#include "config.h"

#include <errno.h>
#include <limits.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include "roothealth_complete_census.h"
#include "roothealth_free_slot_authority.h"
#include "roothealth_free_slot_authority_internal.h"
#include "roothealth_hash_stream.h"
#include "roothealth_recovery_namespace_authority.h"
#include "roothealth_recovery_namespace_authority_internal.h"

#define RH_RECOVERY_NAMESPACE_MAGIC UINT64_C(0x5248524e53415554)

enum rh_recovery_reference_domain {
	RH_RECOVERY_REFERENCE_RAW_FILE_NAME = 1,
	RH_RECOVERY_REFERENCE_NAMESPACE_LINK = 2,
	RH_RECOVERY_REFERENCE_I30_EDGE = 3,
	RH_RECOVERY_REFERENCE_ANCHOR = 4,
};

enum rh_recovery_reference_role {
	RH_RECOVERY_REFERENCE_OWNER = 1,
	RH_RECOVERY_REFERENCE_STORAGE = 2,
	RH_RECOVERY_REFERENCE_PARENT = 3,
	RH_RECOVERY_REFERENCE_CHILD = 4,
};

struct rh_recovery_namespace_authority_census {
	uint64_t magic;
	uint64_t volume_serial;
	struct rh_recovery_namespace_authority_view view;
	unsigned char raw_census_hash[32];
	unsigned char namespace_census_hash[32];
	unsigned char index_census_hash[32];
	struct rh_free_slot_reference *references;
	size_t reference_count;
	unsigned char integrity_hash[32];
};

static int rh_hash_nonzero(const unsigned char digest[32])
{
	size_t i;

	for (i = 0; i < 32U; i++)
		if (digest[i])
			return 1;
	return 0;
}

static int rh_h_bytes(struct rh_hash_stream *hash, const void *bytes,
		size_t length)
{
	return rh_hash_stream_update(hash, bytes, length);
}

static int rh_h_u8(struct rh_hash_stream *hash, uint8_t value)
{
	return rh_h_bytes(hash, &value, sizeof(value));
}

static int rh_h_u16(struct rh_hash_stream *hash, uint16_t value)
{
	unsigned char bytes[2] = {
		(unsigned char)value, (unsigned char)(value >> 8)
	};

	return rh_h_bytes(hash, bytes, sizeof(bytes));
}

static int rh_h_u32(struct rh_hash_stream *hash, uint32_t value)
{
	unsigned char bytes[4];
	unsigned int i;

	for (i = 0; i < 4U; i++)
		bytes[i] = (unsigned char)(value >> (8U * i));
	return rh_h_bytes(hash, bytes, sizeof(bytes));
}

static int rh_h_u64(struct rh_hash_stream *hash, uint64_t value)
{
	unsigned char bytes[8];
	unsigned int i;

	for (i = 0; i < 8U; i++)
		bytes[i] = (unsigned char)(value >> (8U * i));
	return rh_h_bytes(hash, bytes, sizeof(bytes));
}

static int rh_u64_add(uint64_t left, uint64_t right, uint64_t *output)
{
	if (left > UINT64_MAX - right) {
		errno = EOVERFLOW;
		return -1;
	}
	*output = left + right;
	return 0;
}

static int rh_u64_mul(uint64_t left, uint64_t right, uint64_t *output)
{
	if (left && right > UINT64_MAX / left) {
		errno = EOVERFLOW;
		return -1;
	}
	*output = left * right;
	return 0;
}

static int rh_ref_live(const struct rh_raw_mft_census *raw,
		struct rh_raw_mft_ref reference, int base_only)
{
	const struct rh_raw_mft_slot *slot;

	if (!reference.sequence || reference.record >= raw->slot_count)
		return 0;
	slot = &raw->slots[reference.record];
	if (slot->sequence != reference.sequence)
		return 0;
	return slot->state == RH_RAW_SLOT_LIVE_BASE ||
		(!base_only && slot->state == RH_RAW_SLOT_LIVE_EXTENT);
}

static int rh_inputs_ready(const struct rh_complete_census *complete)
{
	const struct rh_raw_mft_census *raw;
	const struct rh_namespace_census *ns;
	const struct rh_index_bitmap_census *index;

	if (!complete || complete->version != RH_COMPLETE_CENSUS_VERSION ||
			!complete->generation || !complete->volume_serial ||
			!complete->read_passes_complete)
		return 0;
	raw = &complete->raw;
	ns = &complete->namespace_census;
	index = &complete->index_bitmap;
	if (raw->generation != complete->generation ||
			ns->generation != complete->generation ||
			index->generation != complete->generation ||
			!raw->records_complete || !raw->records_bounded ||
			!raw->layout_complete || !raw->attribute_lists_complete ||
			!raw->extents_complete ||
			!raw->slots || !raw->slot_count ||
			raw->slot_count != raw->slots_expected ||
			raw->slots_completed != raw->slots_expected ||
			raw->unreadable_records || raw->invalid_records ||
			raw->layout_candidate_count ||
			raw->opaque_records != raw->opaque_slot_count ||
			(raw->opaque_slot_count && !raw->opaque_slots_complete) ||
			raw->file_name_links != raw->file_name_count ||
			(raw->file_name_count && (!raw->file_names || !raw->name_arena ||
			 !raw->value_arena)) ||
			!rh_hash_nonzero(raw->file_name_manifest_hash) ||
			!rh_hash_nonzero(raw->census_hash) || !ns->graph_bounded ||
			!ns->graph_complete || !ns->i30_complete ||
			!ns->reciprocity_complete || !ns->identity_checked ||
			ns->identity == RH_T1OS_IDENTITY_UNKNOWN ||
			ns->live_nodes_completed != ns->live_nodes_expected ||
			ns->links_completed != ns->links_expected ||
			ns->links_expected != raw->file_name_count ||
			ns->link_count != raw->file_name_count ||
			ns->i30_edge_count != ns->link_count ||
			(ns->link_count && (!ns->links || !ns->name_arena ||
			 !ns->file_name_value_arena)) ||
			(ns->i30_edge_count && (!ns->i30_edges || !ns->i30_name_arena ||
			 !ns->i30_value_arena)) || ns->orphan_nodes ||
			ns->unresolved_parents || ns->cycles || ns->aliases ||
			ns->i30_directories_completed != ns->i30_directories_expected ||
			ns->i30_indexes_completed != ns->i30_indexes_expected ||
			ns->i30_blocks_examined != ns->i30_blocks_expected ||
			ns->i30_blocks_reachable != ns->i30_blocks_expected ||
			ns->i30_bitmap_changes || ns->i30_clear_bits_required ||
			!rh_hash_nonzero(ns->graph_hash) ||
			!rh_hash_nonzero(ns->manifest_hash) ||
			!rh_hash_nonzero(ns->i30_edge_hash) ||
			!rh_hash_nonzero(ns->i30_manifest_hash) ||
			!rh_hash_nonzero(ns->i30_tree_hash) ||
			!rh_hash_nonzero(ns->i30_index_census_hash) ||
			!rh_hash_nonzero(ns->reciprocity_hash) ||
			!rh_hash_nonzero(ns->census_hash) || !index->complete ||
			!index->index_tree_complete || !index->child_vcns_valid ||
			!index->indx_blocks_valid || !index->reachable_set_exact ||
			!index->sets_proven_reachable ||
			!index->targets_outside_wal || !index->clean ||
			index->unreadable_records || index->ambiguous_attributes ||
			index->unresolved_blocks || index->clear_bits_required ||
			index->change_count || index->directories_expected !=
				ns->i30_directories_expected || index->directories_completed !=
				ns->i30_directories_completed || index->indexes_expected !=
				ns->i30_indexes_expected || index->indexes_completed !=
				ns->i30_indexes_completed || index->index_entries_examined !=
				ns->i30_entries_examined || !rh_hash_nonzero(index->tree_hash) ||
			!rh_hash_nonzero(index->expected_hash) ||
			!rh_hash_nonzero(index->census_hash))
		return 0;
	return 1;
}

static int rh_hash_reference(struct rh_hash_stream *hash,
		unsigned char *seen, const struct rh_raw_mft_census *raw,
		enum rh_recovery_reference_domain domain,
		enum rh_recovery_reference_role role, uint64_t ordinal,
		struct rh_raw_mft_ref reference, int base_only)
{
	if (!rh_ref_live(raw, reference, base_only)) {
		errno = EPERM;
		return -1;
	}
	seen[reference.record] = 1U;
	return rh_h_u8(hash, (uint8_t)domain) ||
		rh_h_u8(hash, (uint8_t)role) || rh_h_u16(hash, 0U) ||
		rh_h_u64(hash, ordinal) || rh_h_u64(hash, reference.record) ||
		rh_h_u16(hash, reference.sequence);
}

static int rh_hash_input_header(struct rh_hash_stream *hash,
		const struct rh_complete_census *complete,
		const struct rh_namespace_recovery_anchor *anchor,
		uint64_t anchor_occurrences, uint64_t occurrences)
{
	const struct rh_raw_mft_census *raw = &complete->raw;
	const struct rh_namespace_census *ns = &complete->namespace_census;

	return rh_h_bytes(hash, "RHRNSA1", 8U) ||
		rh_h_u32(hash, RH_RECOVERY_NAMESPACE_AUTHORITY_VERSION) ||
		rh_h_u64(hash, complete->volume_serial) ||
		rh_h_u64(hash, raw->slots_expected) ||
		rh_h_u64(hash, raw->file_name_count) ||
		rh_h_u64(hash, ns->link_count) ||
		rh_h_u64(hash, ns->i30_edge_count) ||
		rh_h_u32(hash, (uint32_t)anchor->state) ||
		rh_h_u64(hash, anchor->components_completed) ||
		rh_h_u64(hash, anchor_occurrences) ||
		rh_h_u64(hash, occurrences) ||
		rh_h_bytes(hash, raw->file_name_manifest_hash, 32U) ||
		rh_h_bytes(hash, raw->census_hash, 32U) ||
		rh_h_bytes(hash, ns->graph_hash, 32U) ||
		rh_h_bytes(hash, ns->manifest_hash, 32U) ||
		rh_h_bytes(hash, ns->i30_edge_hash, 32U) ||
		rh_h_bytes(hash, ns->i30_manifest_hash, 32U) ||
		rh_h_bytes(hash, ns->reciprocity_hash, 32U) ||
		rh_h_bytes(hash, ns->census_hash, 32U) ||
		rh_h_bytes(hash, complete->index_bitmap.census_hash, 32U) ||
		rh_h_bytes(hash, anchor->manifest_hash, 32U);
}

static int rh_integrity_hash(
		const struct rh_recovery_namespace_authority_census *census,
		unsigned char output[32])
{
	struct rh_hash_stream hash;
	size_t i;

	if (!census || !output)
		return -1;
	rh_hash_stream_init(&hash);
	if (rh_h_bytes(&hash, "RHRNSO1", 8U) ||
			rh_h_u64(&hash, census->volume_serial) ||
			rh_h_u32(&hash, census->view.version) ||
			rh_h_u64(&hash, census->view.correlation_generation) ||
			rh_h_u64(&hash, census->view.raw_file_name_links) ||
			rh_h_u64(&hash, census->view.namespace_links) ||
			rh_h_u64(&hash, census->view.i30_edges) ||
			rh_h_u32(&hash, (uint32_t)census->view.recovery_anchor_state) ||
			rh_h_u64(&hash,
				census->view.recovery_anchor_components_completed) ||
			rh_h_u64(&hash,
				census->view.recovery_anchor_reference_occurrences) ||
			rh_h_u64(&hash,
				census->view.reference_occurrences_expected) ||
			rh_h_u64(&hash,
				census->view.reference_occurrences_completed) ||
			rh_h_u64(&hash, census->view.unique_references) ||
			rh_h_bytes(&hash, census->view.recovery_anchor_hash, 32U) ||
			rh_h_bytes(&hash, census->view.source_census_hash, 32U) ||
			rh_h_bytes(&hash, census->raw_census_hash, 32U) ||
			rh_h_bytes(&hash, census->namespace_census_hash, 32U) ||
			rh_h_bytes(&hash, census->index_census_hash, 32U) ||
			rh_h_u64(&hash, census->reference_count))
		return -1;
	for (i = 0; i < census->reference_count; i++)
		if (rh_h_u64(&hash, census->references[i].record) ||
				rh_h_u16(&hash, census->references[i].sequence))
			return -1;
	return rh_hash_stream_final(&hash, output);
}

static int rh_census_valid(
		const struct rh_recovery_namespace_authority_census *census)
{
	unsigned char digest[32];
	size_t i;

	if (!census || census->magic != RH_RECOVERY_NAMESPACE_MAGIC ||
			!census->volume_serial ||
			census->view.version !=
				RH_RECOVERY_NAMESPACE_AUTHORITY_VERSION ||
			!census->view.correlation_generation ||
			census->view.reference_occurrences_completed !=
				census->view.reference_occurrences_expected ||
			census->view.unique_references != census->reference_count ||
			census->reference_count >
				census->view.reference_occurrences_completed ||
			(census->reference_count && !census->references) ||
			(census->view.recovery_anchor_state !=
				RH_NAMESPACE_RECOVERY_ANCHOR_ABSENT &&
			 census->view.recovery_anchor_state !=
				RH_NAMESPACE_RECOVERY_ANCHOR_PRESENT) ||
			census->view.recovery_anchor_components_completed >
				RH_NAMESPACE_RECOVERY_ANCHOR_COMPONENTS ||
			census->view.recovery_anchor_reference_occurrences !=
				census->view.recovery_anchor_components_completed * 2U ||
			!rh_hash_nonzero(census->view.recovery_anchor_hash) ||
			!rh_hash_nonzero(census->view.source_census_hash) ||
			!rh_hash_nonzero(census->raw_census_hash) ||
			!rh_hash_nonzero(census->namespace_census_hash) ||
			!rh_hash_nonzero(census->index_census_hash))
		return 0;
	for (i = 0; i < census->reference_count; i++)
		if (!census->references[i].sequence || (i &&
				census->references[i - 1U].record >=
					census->references[i].record))
			return 0;
	return !rh_integrity_hash(census, digest) &&
		!memcmp(digest, census->integrity_hash, sizeof(digest));
}

int rh_recovery_namespace_authority_census_create(
		const struct rh_complete_census *complete,
		struct rh_recovery_namespace_authority_census **output)
{
	const struct rh_raw_mft_census *raw;
	const struct rh_namespace_census *ns;
	struct rh_recovery_namespace_authority_census *result = NULL;
	struct rh_namespace_recovery_anchor anchor;
	struct rh_hash_stream hash;
	unsigned char *seen = NULL;
	uint64_t raw_occurrences, namespace_occurrences, edge_occurrences;
	uint64_t anchor_occurrences;
	uint64_t occurrences, unique = 0;
	size_t i, at = 0;

	if (output)
		*output = NULL;
	if (!output || !rh_inputs_ready(complete)) {
		errno = EPERM;
		return -1;
	}
	raw = &complete->raw;
	ns = &complete->namespace_census;
	if (rh_namespace_resolve_recovery_anchor(raw, ns, &anchor) ||
			anchor.state == RH_NAMESPACE_RECOVERY_ANCHOR_AMBIGUOUS ||
			anchor.state == RH_NAMESPACE_RECOVERY_ANCHOR_UNKNOWN) {
		errno = EPERM;
		return -1;
	}
	if (rh_u64_mul(raw->file_name_count, 3U, &raw_occurrences) ||
			rh_u64_mul(ns->link_count, 3U, &namespace_occurrences) ||
			rh_u64_mul(ns->i30_edge_count, 2U, &edge_occurrences) ||
			rh_u64_mul(anchor.components_completed, 2U,
				&anchor_occurrences) ||
			rh_u64_add(raw_occurrences, namespace_occurrences, &occurrences) ||
			rh_u64_add(occurrences, edge_occurrences, &occurrences) ||
			rh_u64_add(occurrences, anchor_occurrences, &occurrences))
		return -1;
	result = calloc(1, sizeof(*result));
	seen = calloc(raw->slot_count, sizeof(*seen));
	if (!result || !seen)
		goto fail;
	rh_hash_stream_init(&hash);
	if (rh_hash_input_header(&hash, complete, &anchor, anchor_occurrences,
			occurrences))
		goto fail;
	for (i = 0; i < raw->file_name_count; i++) {
		const struct rh_raw_file_name *name = &raw->file_names[i];

		if (name->name_offset > raw->name_arena_size ||
				(size_t)name->name_length * 2U >
					raw->name_arena_size - name->name_offset ||
				name->value_arena_offset > raw->value_arena_size ||
				name->value_length > raw->value_arena_size -
					name->value_arena_offset ||
				!rh_hash_nonzero(name->value_hash) ||
				!rh_hash_nonzero(name->logical_link_hash) ||
				rh_hash_reference(&hash, seen, raw,
					RH_RECOVERY_REFERENCE_RAW_FILE_NAME,
					RH_RECOVERY_REFERENCE_OWNER, i, name->owner, 1) ||
				rh_hash_reference(&hash, seen, raw,
					RH_RECOVERY_REFERENCE_RAW_FILE_NAME,
					RH_RECOVERY_REFERENCE_STORAGE, i, name->storage, 0) ||
				rh_hash_reference(&hash, seen, raw,
					RH_RECOVERY_REFERENCE_RAW_FILE_NAME,
					RH_RECOVERY_REFERENCE_PARENT, i, name->parent, 1))
			goto fail;
	}
	for (i = 0; i < ns->link_count; i++) {
		const struct rh_namespace_link *link = &ns->links[i];

		if (link->name_offset > ns->name_arena_size ||
				(size_t)link->name_length * 2U > ns->name_arena_size -
					link->name_offset || link->file_name_value_offset >
					ns->file_name_value_arena_size ||
				link->file_name_value_length >
					ns->file_name_value_arena_size -
					link->file_name_value_offset ||
				!rh_hash_nonzero(link->file_name_value_hash) ||
				!rh_hash_nonzero(link->reciprocity_value_hash) ||
				!rh_hash_nonzero(link->logical_link_hash) ||
				rh_hash_reference(&hash, seen, raw,
					RH_RECOVERY_REFERENCE_NAMESPACE_LINK,
					RH_RECOVERY_REFERENCE_OWNER, i, link->owner, 1) ||
				rh_hash_reference(&hash, seen, raw,
					RH_RECOVERY_REFERENCE_NAMESPACE_LINK,
					RH_RECOVERY_REFERENCE_STORAGE, i, link->storage, 0) ||
				rh_hash_reference(&hash, seen, raw,
					RH_RECOVERY_REFERENCE_NAMESPACE_LINK,
					RH_RECOVERY_REFERENCE_PARENT, i, link->parent, 1))
			goto fail;
	}
	for (i = 0; i < ns->i30_edge_count; i++) {
		const struct rh_namespace_i30_edge *edge = &ns->i30_edges[i];

		if (edge->name_offset > ns->i30_name_arena_size ||
				(size_t)edge->name_length * 2U >
					ns->i30_name_arena_size - edge->name_offset ||
				edge->file_name_value_offset > ns->i30_value_arena_size ||
				edge->key_length > ns->i30_value_arena_size -
					edge->file_name_value_offset ||
				!rh_hash_nonzero(edge->file_name_value_hash) ||
				!rh_hash_nonzero(edge->reciprocity_value_hash) ||
				rh_hash_reference(&hash, seen, raw,
					RH_RECOVERY_REFERENCE_I30_EDGE,
					RH_RECOVERY_REFERENCE_CHILD, i, edge->child, 1) ||
				rh_hash_reference(&hash, seen, raw,
					RH_RECOVERY_REFERENCE_I30_EDGE,
					RH_RECOVERY_REFERENCE_PARENT, i, edge->parent, 1))
			goto fail;
	}
	for (i = 0; i < anchor.components_completed; i++) {
		const struct rh_namespace_recovery_anchor_component *component =
			&anchor.components[i];

		if (rh_hash_reference(&hash, seen, raw,
				RH_RECOVERY_REFERENCE_ANCHOR,
				RH_RECOVERY_REFERENCE_PARENT, i, component->parent, 1) ||
				rh_hash_reference(&hash, seen, raw,
					RH_RECOVERY_REFERENCE_ANCHOR,
					RH_RECOVERY_REFERENCE_CHILD, i, component->child, 1))
			goto fail;
	}
	for (i = 0; i < raw->slot_count; i++)
		if (seen[i])
			unique++;
	if (unique > SIZE_MAX / sizeof(*result->references)) {
		errno = EOVERFLOW;
		goto fail;
	}
	if (unique) {
		result->references = malloc((size_t)unique *
			sizeof(*result->references));
		if (!result->references)
			goto fail;
	}
	if (rh_h_u64(&hash, unique))
		goto fail;
	for (i = 0; i < raw->slot_count; i++) {
		if (!seen[i])
			continue;
		result->references[at].record = i;
		result->references[at].sequence = raw->slots[i].sequence;
		if (rh_h_u64(&hash, i) ||
				rh_h_u16(&hash, raw->slots[i].sequence))
			goto fail;
		at++;
	}
	if (at != unique || rh_hash_stream_final(&hash,
			result->view.source_census_hash))
		goto fail;
	result->magic = RH_RECOVERY_NAMESPACE_MAGIC;
	result->volume_serial = complete->volume_serial;
	result->view.version = RH_RECOVERY_NAMESPACE_AUTHORITY_VERSION;
	result->view.correlation_generation = complete->generation;
	result->view.raw_file_name_links = raw->file_name_count;
	result->view.namespace_links = ns->link_count;
	result->view.i30_edges = ns->i30_edge_count;
	result->view.recovery_anchor_state = anchor.state;
	result->view.recovery_anchor_components_completed =
		anchor.components_completed;
	result->view.recovery_anchor_reference_occurrences =
		anchor_occurrences;
	result->view.reference_occurrences_expected = occurrences;
	result->view.reference_occurrences_completed = occurrences;
	result->view.unique_references = unique;
	memcpy(result->view.recovery_anchor_hash, anchor.manifest_hash, 32U);
	memcpy(result->raw_census_hash, raw->census_hash, 32U);
	memcpy(result->namespace_census_hash, ns->census_hash, 32U);
	memcpy(result->index_census_hash,
		complete->index_bitmap.census_hash, 32U);
	result->reference_count = (size_t)unique;
	if (rh_integrity_hash(result, result->integrity_hash) ||
			!rh_census_valid(result))
		goto fail;
	free(seen);
	*output = result;
	return 0;
fail:
	free(seen);
	rh_recovery_namespace_authority_census_destroy(result);
	return -1;
}

void rh_recovery_namespace_authority_census_destroy(
		struct rh_recovery_namespace_authority_census *census)
{
	if (!census)
		return;
	free(census->references);
	memset(census, 0, sizeof(*census));
	free(census);
}

static int rh_recovery_namespace_authority_census_get_view(
		const struct rh_recovery_namespace_authority_census *census,
		struct rh_recovery_namespace_authority_view *view)
{
	if (!view || !rh_census_valid(census)) {
		errno = EINVAL;
		return -1;
	}
	*view = census->view;
	return 0;
}

static int rh_recovery_namespace_component_seal_create(
		const struct rh_recovery_namespace_authority_census *census,
		struct rh_free_slot_component_seal **output)
{
	if (output)
		*output = NULL;
	if (!output || !rh_census_valid(census)) {
		errno = EINVAL;
		return -1;
	}
	return rh_free_slot_friend_recovery_namespace_seal(
		census->view.correlation_generation,
		census->view.reference_occurrences_expected,
		census->view.reference_occurrences_completed,
		census->view.source_census_hash, census->references,
		census->reference_count, output);
}

static int rh_complete_matches(
		const struct rh_complete_census *complete,
		const struct rh_recovery_namespace_authority_census *census)
{
	return complete && complete->version == RH_COMPLETE_CENSUS_VERSION &&
		complete->recovery_namespace_authority == census &&
		rh_inputs_ready(complete) && rh_census_valid(census) &&
		complete->generation ==
			census->view.correlation_generation &&
		complete->volume_serial == census->volume_serial &&
		!memcmp(complete->raw.census_hash, census->raw_census_hash, 32U) &&
		!memcmp(complete->namespace_census.census_hash,
			census->namespace_census_hash, 32U) &&
		!memcmp(complete->index_bitmap.census_hash,
			census->index_census_hash, 32U);
}

int rh_complete_census_recovery_namespace_get_view(
		const struct rh_complete_census *complete,
		struct rh_recovery_namespace_authority_view *view)
{
	if (!view || !complete || !rh_complete_matches(complete,
			complete->recovery_namespace_authority)) {
		errno = EPERM;
		return -1;
	}
	return rh_recovery_namespace_authority_census_get_view(
		complete->recovery_namespace_authority, view);
}

int rh_complete_census_recovery_namespace_component_seal_create(
		const struct rh_complete_census *complete,
		struct rh_free_slot_component_seal **output)
{
	if (output)
		*output = NULL;
	if (!output || !complete || !rh_complete_matches(complete,
			complete->recovery_namespace_authority)) {
		errno = EPERM;
		return -1;
	}
	return rh_recovery_namespace_component_seal_create(
		complete->recovery_namespace_authority, output);
}
