/* ROOTHEALTH_REPAIR_ROLE(DIAGNOSTIC) ROOTHEALTH_IO_ROLE(READER) */
#include "config.h"

#include <errno.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include "endians.h"
#include "layout.h"
#include "roothealth_census_device.h"
#include "roothealth_hash_stream.h"
#include "roothealth_namespace.h"
#include "roothealth_raw_mft.h"
#include "roothealth_secure.h"
#include "roothealth_secure_census_provider.h"
#include "roothealth_secure_raw.h"

#define RH_SDS_BLOCK UINT64_C(0x40000)
#define RH_SDS_PAIR UINT64_C(0x80000)
#define RH_SDS_ALIGN UINT64_C(16)
#define RH_SDS_HEADER ((size_t)offsetof(SDS_ENTRY, sid))
#define RH_SECURE_RECORD UINT64_C(9)

struct rh_security_reference {
	uint64_t record;
	uint16_t sequence;
	uint32_t security_id;
};

struct rh_secure_census_provider {
	uint64_t magic;
	struct rh_secure_census_provider_view view;
	unsigned char integrity_hash[32];
};

#define RH_SECURE_PROVIDER_MAGIC UINT64_C(0x5248534350524f56)

static int rh_u32_compare(const void *left, const void *right)
{
	uint32_t first = *(const uint32_t *)left;
	uint32_t second = *(const uint32_t *)right;

	return first < second ? -1 : first > second ? 1 : 0;
}

static int rh_reference_compare(const void *left, const void *right)
{
	const struct rh_security_reference *first = left;
	const struct rh_security_reference *second = right;

	if (first->record != second->record)
		return first->record < second->record ? -1 : 1;
	if (first->sequence != second->sequence)
		return first->sequence < second->sequence ? -1 : 1;
	return first->security_id < second->security_id ? -1 :
		first->security_id > second->security_id ? 1 : 0;
}

static int rh_hash_nonzero(const unsigned char hash[32])
{
	size_t i;

	for (i = 0; i < 32U; i++)
		if (hash[i])
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
	unsigned char bytes[4] = {
		(unsigned char)value, (unsigned char)(value >> 8),
		(unsigned char)(value >> 16), (unsigned char)(value >> 24)
	};

	return rh_h_bytes(hash, bytes, sizeof(bytes));
}

static int rh_h_u64(struct rh_hash_stream *hash, uint64_t value)
{
	unsigned char bytes[8];
	unsigned int i;

	for (i = 0; i < 8U; i++)
		bytes[i] = (unsigned char)(value >> (i * 8U));
	return rh_h_bytes(hash, bytes, sizeof(bytes));
}

static uint32_t rh_descriptor_hash(const unsigned char *bytes, size_t length)
{
	uint32_t hash = 0;
	size_t i;

	for (i = 0; i < length; i += 4U) {
		uint32_t word = (uint32_t)bytes[i] |
			((uint32_t)bytes[i + 1U] << 8) |
			((uint32_t)bytes[i + 2U] << 16) |
			((uint32_t)bytes[i + 3U] << 24);

		hash = (hash << 3) | (hash >> 29);
		hash += word;
	}
	return hash;
}

static int rh_append_id(uint32_t **ids, size_t *count, uint32_t id)
{
	uint32_t *grown;

	if (*count >= SIZE_MAX / sizeof(**ids)) {
		errno = EOVERFLOW;
		return -1;
	}
	grown = realloc(*ids, (*count + 1U) * sizeof(**ids));
	if (!grown)
		return -1;
	*ids = grown;
	grown[(*count)++] = id;
	return 0;
}

static int rh_discover_sds_ids(const struct rh_census_reader *reader,
		const struct rh_raw_mft_census *raw, struct rh_raw_mft_ref owner,
		uint32_t **ids_out, size_t *count_out)
{
	struct rh_secure_mapping_slice *slices = NULL;
	unsigned char *bytes = NULL;
	uint32_t *ids = NULL;
	uint64_t data_size = 0, pair_base;
	size_t slice_count = 0, count = 0, i, unique;
	int result = -1;

	if (!reader || !raw || !ids_out || !count_out || *ids_out || *count_out ||
			rh_secure_raw_build_mapping_reader(raw, reader, owner, AT_DATA,
				(const unsigned char *)STREAM_SDS, 4U, RH_SDS_BLOCK + 1U,
				reader->device_size, &slices, &slice_count, &data_size) ||
			data_size > SIZE_MAX) {
		if (!errno)
			errno = EINVAL;
		goto out;
	}
	bytes = malloc((size_t)data_size);
	if (!bytes)
		goto out;
	for (i = 0; i < slice_count; i++) {
		const struct rh_secure_mapping_slice *slice = &slices[i];

		if (slice->logical_offset > data_size ||
				slice->length > data_size - slice->logical_offset ||
				slice->length > SIZE_MAX ||
				rh_census_reader_read_exact(reader, slice->physical_offset,
					(size_t)slice->length, bytes + slice->logical_offset))
			goto out;
	}
	for (pair_base = 0; pair_base < data_size; pair_base += RH_SDS_PAIR) {
		uint64_t copy;

		if (data_size - pair_base <= RH_SDS_BLOCK)
			break;
		for (copy = 0; copy <= RH_SDS_BLOCK; copy += RH_SDS_BLOCK) {
			uint64_t copy_base = pair_base + copy;
			uint64_t copy_length = data_size - copy_base;
			uint64_t cursor;

			if (copy_length > RH_SDS_BLOCK)
				copy_length = RH_SDS_BLOCK;
			for (cursor = 0; cursor <= copy_length &&
					copy_length - cursor >= RH_SDS_HEADER;
					cursor += RH_SDS_ALIGN) {
				const SDS_ENTRY *entry = (const SDS_ENTRY *)(bytes +
					copy_base + cursor);
				uint32_t length = le32_to_cpu(entry->length);
				uint32_t id = le32_to_cpu(entry->security_id);
				uint64_t offset = le64_to_cpu(entry->offset);
				const unsigned char *descriptor;
				size_t descriptor_length;

				if (offset != pair_base + cursor || id < 0x100U ||
						length < RH_SDS_HEADER +
							sizeof(SECURITY_DESCRIPTOR_RELATIVE) ||
						length > copy_length - cursor ||
						((length - RH_SDS_HEADER) & 3U))
					continue;
				descriptor = (const unsigned char *)entry + RH_SDS_HEADER;
				descriptor_length = length - RH_SDS_HEADER;
				if (!rh_secure_descriptor_bytes_valid(descriptor,
						descriptor_length) ||
						rh_descriptor_hash(descriptor, descriptor_length) !=
							le32_to_cpu(entry->hash))
					continue;
				if (rh_append_id(&ids, &count, id))
					goto out;
			}
		}
	}
	if (!count) {
		errno = EUCLEAN;
		goto out;
	}
	qsort(ids, count, sizeof(*ids), rh_u32_compare);
	for (i = 0, unique = 0; i < count; i++)
		if (!i || ids[i] != ids[i - 1U])
			ids[unique++] = ids[i];
	*ids_out = ids;
	*count_out = unique;
	ids = NULL;
	result = 0;
out:
	free(ids);
	free(bytes);
	free(slices);
	return result;
}

static int rh_id_exists(const uint32_t *ids, size_t count, uint32_t id)
{
	return bsearch(&id, ids, count, sizeof(*ids), rh_u32_compare) != NULL;
}

static int rh_gather_security_references(const struct rh_raw_mft_census *raw,
		const uint32_t *ids, size_t id_count,
		struct rh_security_reference **references_out, size_t *count_out,
		uint64_t *legacy_si_count)
{
	struct rh_security_reference *references = NULL;
	unsigned char *seen = NULL;
	size_t count = 0, i;
	int result = -1;

	if (!raw || !ids || !id_count || !references_out || !count_out ||
			!legacy_si_count || raw->slot_count > SIZE_MAX) {
		errno = EINVAL;
		return -1;
	}
	seen = calloc(raw->slot_count, 1U);
	if (!seen)
		return -1;
	for (i = 0; i < raw->attribute_count; i++) {
		const struct rh_raw_attribute *attribute = &raw->attributes[i];
		const unsigned char *value;
		uint32_t id;
		void *grown;

		if (attribute->type != AT_STANDARD_INFORMATION)
			continue;
		if (attribute->owner.record >= raw->slot_count ||
				raw->slots[attribute->owner.record].state !=
					RH_RAW_SLOT_LIVE_BASE ||
				raw->slots[attribute->owner.record].sequence !=
					attribute->owner.sequence ||
				seen[attribute->owner.record] || attribute->nonresident ||
				attribute->name_length || attribute->flags ||
				attribute->resident_flags ||
				attribute->value_arena_offset > raw->value_arena_size ||
				attribute->value_length > raw->value_arena_size -
					attribute->value_arena_offset) {
			errno = EUCLEAN;
			goto out;
		}
		seen[attribute->owner.record] = 1U;
		if (attribute->value_length == 48U) {
			(*legacy_si_count)++;
			continue;
		}
		if (attribute->value_length != sizeof(STANDARD_INFORMATION)) {
			errno = EUCLEAN;
			goto out;
		}
		value = raw->value_arena + attribute->value_arena_offset;
		id = le32_to_cpu(((const STANDARD_INFORMATION *)value)->security_id);
		if (!id)
			continue;
		if (id < 0x100U || !rh_id_exists(ids, id_count, id) ||
				count >= SIZE_MAX / sizeof(*references)) {
			errno = EUCLEAN;
			goto out;
		}
		grown = realloc(references, (count + 1U) * sizeof(*references));
		if (!grown)
			goto out;
		references = grown;
		references[count].record = attribute->owner.record;
		references[count].sequence = attribute->owner.sequence;
		references[count].security_id = id;
		count++;
	}
	for (i = 0; i < raw->slot_count; i++)
		if (raw->slots[i].state == RH_RAW_SLOT_LIVE_BASE && !seen[i]) {
			errno = EUCLEAN;
			goto out;
		}
	if (!count) {
		errno = EUCLEAN;
		goto out;
	}
	qsort(references, count, sizeof(*references), rh_reference_compare);
	*references_out = references;
	*count_out = count;
	references = NULL;
	result = 0;
out:
	free(references);
	free(seen);
	return result;
}

static int rh_hash_ids(const uint32_t *ids, size_t count,
		unsigned char output[32])
{
	struct rh_hash_stream hash;
	size_t i;

	rh_hash_stream_init(&hash);
	if (rh_h_bytes(&hash, "RHSECID1", 8U) || rh_h_u64(&hash, count))
		return -1;
	for (i = 0; i < count; i++)
		if (rh_h_u32(&hash, ids[i]))
			return -1;
	return rh_hash_stream_final(&hash, output);
}

static int rh_hash_references(const struct rh_security_reference *references,
		size_t count, unsigned char output[32])
{
	struct rh_hash_stream hash;
	size_t i;

	rh_hash_stream_init(&hash);
	if (rh_h_bytes(&hash, "RHSECREF", 8U) || rh_h_u64(&hash, count))
		return -1;
	for (i = 0; i < count; i++)
		if (rh_h_u64(&hash, references[i].record) ||
				rh_h_u16(&hash, references[i].sequence) ||
				rh_h_u32(&hash, references[i].security_id))
			return -1;
	return rh_hash_stream_final(&hash, output);
}

static uint64_t rh_bitmap_popcount(const unsigned char *bytes, uint64_t length)
{
	uint64_t count = 0, i;

	for (i = 0; i < length; i++) {
		unsigned char value = bytes[i];

		while (value) {
			count += value & 1U;
			value >>= 1;
		}
	}
	return count;
}

static int rh_add_u64(uint64_t left, uint64_t right, uint64_t *output)
{
	if (left > UINT64_MAX - right) {
		errno = EOVERFLOW;
		return -1;
	}
	*output = left + right;
	return 0;
}

static int rh_hash_provider(struct rh_secure_census_provider *provider,
		uint64_t volume_serial, const struct rh_raw_mft_census *raw,
		const struct rh_namespace_census *namespace_census,
		const struct rh_secure_inspection *inspection)
{
	const struct rh_secure_census_provider_view *view = &provider->view;
	struct rh_hash_stream hash;

	rh_hash_stream_init(&hash);
	if (rh_h_bytes(&hash, "RHSECPR1", 8U) ||
			rh_h_u32(&hash, view->version) ||
			rh_h_u64(&hash, volume_serial) ||
			rh_h_u64(&hash, view->security_ids_expected) ||
			rh_h_u64(&hash, view->security_ids_examined) ||
			rh_h_u64(&hash, view->security_id_references_expected) ||
			rh_h_u64(&hash, view->security_id_references_examined) ||
			rh_h_u64(&hash, view->security_id_references_resolved) ||
			rh_h_u64(&hash, view->descriptors_expected) ||
			rh_h_u64(&hash, view->descriptors_examined) ||
			rh_h_u64(&hash, view->legacy_descriptors_expected) ||
			rh_h_u64(&hash, view->legacy_descriptors_examined) ||
			rh_h_u64(&hash, view->sds_entries_expected) ||
			rh_h_u64(&hash, view->sds_entries_examined) ||
			rh_h_u64(&hash, view->sdh_entries_expected) ||
			rh_h_u64(&hash, view->sdh_entries_examined) ||
			rh_h_u64(&hash, view->sii_entries_expected) ||
			rh_h_u64(&hash, view->sii_entries_examined) ||
			rh_h_u64(&hash, view->indexes_expected) ||
			rh_h_u64(&hash, view->indexes_completed) ||
			rh_h_u64(&hash, view->index_blocks_allocated) ||
			rh_h_u64(&hash, view->index_blocks_reachable) ||
			rh_h_u64(&hash, view->index_blocks_examined) ||
			rh_h_u64(&hash, view->index_bitmap_bits_expected) ||
			rh_h_u64(&hash, view->index_bitmap_bits_examined) ||
			rh_h_u8(&hash, view->sds_clean) ||
			rh_h_u8(&hash, view->sdh_clean) ||
			rh_h_u8(&hash, view->sii_clean) ||
			rh_h_bytes(&hash, raw->census_hash, 32U) ||
			rh_h_bytes(&hash, namespace_census->census_hash, 32U) ||
			rh_h_bytes(&hash, view->security_id_manifest_hash, 32U) ||
			rh_h_bytes(&hash, view->security_id_use_hash, 32U) ||
			rh_h_bytes(&hash, view->descriptor_manifest_hash, 32U) ||
			rh_h_bytes(&hash, view->mapping_hash, 32U) ||
			rh_h_bytes(&hash, inspection->sds_current_hash, 32U) ||
			rh_h_bytes(&hash, inspection->sds_staged_hash, 32U) ||
			rh_h_bytes(&hash, inspection->sdh_current_hash, 32U) ||
			rh_h_bytes(&hash, inspection->sdh_canonical_hash, 32U) ||
			rh_h_bytes(&hash, inspection->sii_current_hash, 32U) ||
			rh_h_bytes(&hash, inspection->sii_canonical_hash, 32U))
		return -1;
	return rh_hash_stream_final(&hash, provider->view.census_hash);
}

static int rh_integrity_hash(const struct rh_secure_census_provider *provider,
		unsigned char output[32])
{
	struct rh_hash_stream hash;

	rh_hash_stream_init(&hash);
	if (rh_h_bytes(&hash, "RHSECI1\0", 8U) ||
			rh_h_u64(&hash, provider->magic) ||
			rh_h_bytes(&hash, provider->view.census_hash, 32U) ||
			rh_h_u8(&hash, provider->view.complete))
		return -1;
	return rh_hash_stream_final(&hash, output);
}

static int rh_provider_valid(const struct rh_secure_census_provider *provider)
{
	unsigned char integrity[32];

	return provider && provider->magic == RH_SECURE_PROVIDER_MAGIC &&
		provider->view.version == RH_SECURE_CENSUS_PROVIDER_VERSION &&
		provider->view.correlation_generation && provider->view.complete &&
		provider->view.security_ids_expected &&
		provider->view.security_ids_expected ==
			provider->view.security_ids_examined &&
		provider->view.security_id_references_expected ==
			provider->view.security_id_references_examined &&
		provider->view.security_id_references_expected ==
			provider->view.security_id_references_resolved &&
		provider->view.descriptors_expected ==
			provider->view.descriptors_examined &&
		provider->view.sds_entries_expected ==
			provider->view.sds_entries_examined &&
		provider->view.sdh_entries_expected ==
			provider->view.sdh_entries_examined &&
		provider->view.sii_entries_expected ==
			provider->view.sii_entries_examined &&
		provider->view.indexes_expected == provider->view.indexes_completed &&
		provider->view.sds_clean && provider->view.sdh_clean &&
		provider->view.sii_clean &&
		rh_hash_nonzero(provider->view.security_id_manifest_hash) &&
		rh_hash_nonzero(provider->view.security_id_use_hash) &&
		rh_hash_nonzero(provider->view.descriptor_manifest_hash) &&
		rh_hash_nonzero(provider->view.mapping_hash) &&
		rh_hash_nonzero(provider->view.census_hash) &&
		!rh_integrity_hash(provider, integrity) &&
		!memcmp(integrity, provider->integrity_hash, 32U);
}

int rh_secure_census_provider_run(const struct rh_census_reader *reader,
		ntfs_volume *volume, const struct rh_raw_mft_census *raw,
		const struct rh_namespace_census *namespace_census,
		uint64_t generation, struct rh_secure_census_provider **output)
{
	struct rh_secure_census_provider *provider = NULL;
	struct rh_secure_inspection inspection;
	struct rh_secure_census census;
	struct rh_security_reference *references = NULL;
	uint32_t *ids = NULL;
	uint64_t legacy_count = 0, legacy_si_count = 0;
	unsigned char legacy_hash[32];
	size_t id_count = 0, reference_count = 0;
	uint64_t sdh_blocks, sii_blocks, sdh_allocated, sii_allocated;
	int result = -1;

	if (output)
		*output = NULL;
	if (!output || !reader || !volume || !raw || !namespace_census ||
			!generation || raw->generation != generation ||
			namespace_census->generation != generation ||
			!raw->records_complete || !raw->records_bounded ||
			!raw->layout_complete || !raw->attribute_lists_complete ||
			!raw->extents_complete ||
			raw->slots_completed != raw->slots_expected ||
			raw->extents_completed != raw->extents_expected ||
			raw->runs_completed != raw->runs_expected ||
			!namespace_census->graph_bounded ||
			!namespace_census->graph_complete ||
			!namespace_census->i30_complete ||
			!namespace_census->reciprocity_complete ||
			raw->slot_count <= RH_SECURE_RECORD ||
			raw->slots[RH_SECURE_RECORD].state != RH_RAW_SLOT_LIVE_BASE ||
			!raw->slots[RH_SECURE_RECORD].sequence) {
		errno = EPERM;
		return -1;
	}
	memset(&inspection, 0, sizeof(inspection));
	memset(&census, 0, sizeof(census));
	if (rh_discover_sds_ids(reader, raw, (struct rh_raw_mft_ref){
			RH_SECURE_RECORD, raw->slots[RH_SECURE_RECORD].sequence},
			&ids, &id_count) ||
			rh_gather_security_references(raw, ids, id_count, &references,
				&reference_count, &legacy_si_count) ||
			rh_secure_legacy_census_reader(reader, raw, &legacy_count,
				legacy_hash) ||
			legacy_si_count != legacy_count)
		goto out;
	census.generation = generation;
	census.complete_security_id_census = 1;
	census.security_ids_expected = id_count;
	census.security_ids_examined = id_count;
	census.security_id_references_expected = reference_count;
	census.security_id_references_examined = reference_count;
	census.security_id_references_resolved = reference_count;
	census.live_security_ids = ids;
	census.live_security_id_count = id_count;
	census.legacy_security_descriptors_expected = legacy_count;
	census.legacy_security_descriptors_examined = legacy_count;
	memcpy(census.legacy_security_descriptor_hash, legacy_hash, 32U);
	census.raw_mft_extent_authority_complete = 1;
	census.raw_mft_census = raw;
	memcpy(census.raw_mft_census_hash, raw->census_hash, 32U);
	if (rh_secure_inspect_reader(volume, reader, &census, &inspection) ||
			!inspection.sds_clean || !inspection.sdh_clean ||
			!inspection.sii_clean || inspection.descriptor_count != id_count)
		goto out;
	provider = calloc(1, sizeof(*provider));
	if (!provider)
		goto out;
	provider->view.version = RH_SECURE_CENSUS_PROVIDER_VERSION;
	provider->view.correlation_generation = generation;
	provider->view.security_ids_expected = id_count;
	provider->view.security_ids_examined = id_count;
	provider->view.security_id_references_expected = reference_count;
	provider->view.security_id_references_examined = reference_count;
	provider->view.security_id_references_resolved = reference_count;
	if (rh_add_u64(id_count, legacy_count,
			&provider->view.descriptors_expected))
		goto out;
	provider->view.descriptors_examined =
		provider->view.descriptors_expected;
	provider->view.legacy_descriptors_expected = legacy_count;
	provider->view.legacy_descriptors_examined = legacy_count;
	provider->view.sds_entries_expected = id_count;
	provider->view.sds_entries_examined = id_count;
	provider->view.sdh_entries_expected = id_count;
	provider->view.sdh_entries_examined = id_count;
	provider->view.sii_entries_expected = id_count;
	provider->view.sii_entries_examined = id_count;
	provider->view.indexes_expected = 2U;
	provider->view.indexes_completed = 2U;
	sdh_blocks = inspection.sdh_index.large ?
		inspection.sdh_index.canonical_block_count : 0U;
	sii_blocks = inspection.sii_index.large ?
		inspection.sii_index.canonical_block_count : 0U;
	sdh_allocated = inspection.sdh_index.large ? rh_bitmap_popcount(
		inspection.sdh_index.bitmap_current,
		inspection.sdh_index.bitmap_data_size) : 0U;
	sii_allocated = inspection.sii_index.large ? rh_bitmap_popcount(
		inspection.sii_index.bitmap_current,
		inspection.sii_index.bitmap_data_size) : 0U;
	if (rh_add_u64(sdh_blocks, sii_blocks,
			&provider->view.index_blocks_reachable) ||
			rh_add_u64(sdh_blocks, sii_blocks,
				&provider->view.index_blocks_examined) ||
			rh_add_u64(sdh_allocated, sii_allocated,
				&provider->view.index_blocks_allocated) ||
			rh_add_u64(inspection.sdh_index.bitmap_data_size,
				inspection.sii_index.bitmap_data_size,
				&provider->view.index_bitmap_bits_expected))
		goto out;
	if (provider->view.index_bitmap_bits_expected > UINT64_MAX / 8U) {
		errno = EOVERFLOW;
		goto out;
	}
	provider->view.index_bitmap_bits_expected *= 8U;
	provider->view.index_bitmap_bits_examined =
		provider->view.index_bitmap_bits_expected;
	provider->view.sds_clean = 1U;
	provider->view.sdh_clean = 1U;
	provider->view.sii_clean = 1U;
	memcpy(provider->view.descriptor_manifest_hash,
		inspection.descriptor_manifest_hash, 32U);
	memcpy(provider->view.mapping_hash, inspection.mapping_hash, 32U);
	if (rh_hash_ids(ids, id_count,
			provider->view.security_id_manifest_hash) ||
			rh_hash_references(references, reference_count,
				provider->view.security_id_use_hash) ||
			rh_hash_provider(provider, inspection.volume_serial, raw,
				namespace_census, &inspection))
		goto out;
	provider->view.complete = 1U;
	provider->magic = RH_SECURE_PROVIDER_MAGIC;
	if (rh_integrity_hash(provider, provider->integrity_hash) ||
			!rh_provider_valid(provider)) {
		errno = EIO;
		goto out;
	}
	*output = provider;
	provider = NULL;
	result = 0;
out:
	rh_secure_census_provider_destroy(provider);
	rh_secure_inspection_destroy(&inspection);
	free(references);
	free(ids);
	return result;
}

int rh_secure_census_provider_get_view(
		const struct rh_secure_census_provider *provider,
		struct rh_secure_census_provider_view *view)
{
	if (!view || !rh_provider_valid(provider)) {
		errno = EINVAL;
		return -1;
	}
	*view = provider->view;
	return 0;
}

void rh_secure_census_provider_destroy(
		struct rh_secure_census_provider *provider)
{
	if (!provider)
		return;
	memset(provider, 0, sizeof(*provider));
	free(provider);
}
