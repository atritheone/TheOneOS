/* ROOTHEALTH_REPAIR_ROLE(DIAGNOSTIC) ROOTHEALTH_IO_ROLE(READER) */
#include "config.h"

#include <errno.h>
#include <limits.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include "attrdef.h"
#include "endians.h"
#include "layout.h"
#include "roothealth_census_device.h"
#include "roothealth_fixed_metadata_reader.h"
#include "roothealth_hash_stream.h"
#include "roothealth_raw_mft.h"
#include "unistr.h"

#define RH_FIXED_CLUSTER_SIZE UINT64_C(4096)

/* ntfs-next d4f481d, pinned again by the normative output digests below. */
static const char rh_upcase_source[] =
	"ntfs-next:d4f481d:libntfs/unistr.c:ntfs_upcase_build_default";
static const char rh_attrdef_source[] =
	"ntfs-next:d4f481d:src/attrdef.c:attrdef_ntfs3x_array";

struct rh_fixed_spec {
	enum rh_fixed_metadata_reader_kind kind;
	uint64_t record;
	uint64_t size;
	const char *hex;
	const char *source;
};

static const struct rh_fixed_spec rh_fixed_specs[2] = {
	{ RH_FIXED_METADATA_READER_ATTRDEF, 4U,
		RH_FIXED_METADATA_ATTRDEF_SIZE,
		RH_FIXED_METADATA_ATTRDEF_SHA256, rh_attrdef_source },
	{ RH_FIXED_METADATA_READER_UPCASE, 10U,
		RH_FIXED_METADATA_UPCASE_SIZE,
		RH_FIXED_METADATA_UPCASE_SHA256, rh_upcase_source },
};

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

static int rh_nonzero_hash(const unsigned char digest[32])
{
	size_t i;

	for (i = 0; i < 32U; i++)
		if (digest[i])
			return 1;
	return 0;
}

static int rh_digest_is_hex(const unsigned char digest[32],
		const char expected[65])
{
	static const char digits[] = "0123456789abcdef";
	char actual[65];
	size_t i;

	for (i = 0; i < 32U; i++) {
		actual[2U * i] = digits[digest[i] >> 4];
		actual[2U * i + 1U] = digits[digest[i] & 15U];
	}
	actual[64] = 0;
	return !strcmp(actual, expected);
}

static int rh_hash_buffer(const void *bytes, size_t length,
		unsigned char output[32])
{
	struct rh_hash_stream hash;

	rh_hash_stream_init(&hash);
	return rh_hash_stream_update(&hash, bytes, length) ||
		rh_hash_stream_final(&hash, output);
}

static int rh_canonical_build(const struct rh_fixed_spec *spec,
		unsigned char **bytes, size_t *length, unsigned char digest[32])
{
	unsigned char *result;

	if (!spec || !bytes || !length || !digest || spec->size > SIZE_MAX) {
		errno = EINVAL;
		return -1;
	}
	*bytes = NULL;
	*length = 0;
	if (spec->kind == RH_FIXED_METADATA_READER_UPCASE) {
		ntfschar *upcase = NULL;
		u32 count = ntfs_upcase_build_default(&upcase);

		if (!upcase || count != spec->size / sizeof(*upcase)) {
			free(upcase);
			errno = EIO;
			return -1;
		}
		result = (unsigned char *)upcase;
	} else if (spec->kind == RH_FIXED_METADATA_READER_ATTRDEF) {
		result = malloc((size_t)spec->size);
		if (!result)
			return -1;
		memcpy(result, attrdef_ntfs3x_array, (size_t)spec->size);
	} else {
		errno = EINVAL;
		return -1;
	}
	if (rh_hash_buffer(result, (size_t)spec->size, digest) ||
			!rh_digest_is_hex(digest, spec->hex)) {
		int saved_errno = errno ? errno : EILSEQ;

		memset(result, 0, (size_t)spec->size);
		free(result);
		errno = saved_errno;
		return -1;
	}
	*bytes = result;
	*length = (size_t)spec->size;
	return 0;
}

static int rh_raw_ready(const struct rh_census_reader *reader,
		const struct rh_raw_mft_census *raw)
{
	return reader && reader->context && reader->read && reader->device_size &&
		(reader->source == RH_CENSUS_READER_IMMUTABLE ||
		 reader->source == RH_CENSUS_READER_WRITER_PREFIX ||
		 reader->source == RH_CENSUS_READER_WAL_PREIMAGE) &&
		raw && raw->generation &&
		raw->slots && raw->slot_count == raw->slots_expected &&
		raw->slots_completed == raw->slots_expected && raw->records_complete &&
		raw->records_bounded && raw->layout_complete &&
		raw->attribute_lists_complete && raw->extents_complete &&
		!raw->unreadable_records && !raw->invalid_records &&
		!raw->layout_candidate_count &&
		raw->extents_completed == raw->extents_expected &&
		raw->runs_completed == raw->runs_expected &&
		raw->runs_expected == raw->run_count &&
		(!raw->attribute_count || raw->attributes) &&
		(!raw->run_count || raw->runs) &&
		raw->opaque_records == raw->opaque_slot_count &&
		(!raw->opaque_slot_count || raw->opaque_slots_complete) &&
		rh_nonzero_hash(raw->census_hash);
}

static int rh_target_attribute(const struct rh_raw_attribute *attribute,
		uint64_t record)
{
	return attribute->owner.record == record &&
		attribute->type == le32_to_cpu(AT_DATA) && !attribute->name_length;
}

static int rh_hash_observed_mapping(const struct rh_raw_mft_census *raw,
		const struct rh_fixed_spec *spec,
		struct rh_fixed_metadata_reader_entry *entry)
{
	struct rh_hash_stream hash;
	uint64_t attribute_count = 0, run_count = 0;
	size_t i, j;

	for (i = 0; i < raw->attribute_count; i++) {
		const struct rh_raw_attribute *attribute = &raw->attributes[i];

		if (!rh_target_attribute(attribute, spec->record))
			continue;
		attribute_count++;
		if (attribute->run_first <= raw->run_count &&
				attribute->run_count <= raw->run_count -
				attribute->run_first)
			run_count += attribute->run_count;
	}
	entry->extents_examined = attribute_count;
	entry->runs_examined = run_count;
	rh_hash_stream_init(&hash);
	if (rh_h_bytes(&hash, "RHFXMAP2", 8U) ||
			rh_h_u32(&hash, RH_FIXED_METADATA_READER_VERSION) ||
			rh_h_bytes(&hash, raw->census_hash, 32U) ||
			rh_h_u32(&hash, (uint32_t)spec->kind) ||
			rh_h_u64(&hash, spec->record) ||
			rh_h_u64(&hash, attribute_count))
		return -1;
	for (i = 0; i < raw->attribute_count; i++) {
		const struct rh_raw_attribute *attribute = &raw->attributes[i];
		int run_slice_valid;

		if (!rh_target_attribute(attribute, spec->record))
			continue;
		run_slice_valid = attribute->run_first <= raw->run_count &&
			attribute->run_count <= raw->run_count - attribute->run_first;
		if (rh_h_u64(&hash, i) ||
				rh_h_u64(&hash, attribute->owner.record) ||
				rh_h_u16(&hash, attribute->owner.sequence) ||
				rh_h_u64(&hash, attribute->storage.record) ||
				rh_h_u16(&hash, attribute->storage.sequence) ||
				rh_h_u32(&hash, attribute->type) ||
				rh_h_u16(&hash, attribute->instance) ||
				rh_h_u16(&hash, attribute->flags) ||
				rh_h_u8(&hash, attribute->nonresident) ||
				rh_h_u8(&hash, attribute->compression_unit) ||
				rh_h_u8(&hash, attribute->list_claimed) ||
				rh_h_u64(&hash, (uint64_t)attribute->lowest_vcn) ||
				rh_h_u64(&hash, (uint64_t)attribute->highest_vcn) ||
				rh_h_u64(&hash, (uint64_t)attribute->allocated_size) ||
				rh_h_u64(&hash, (uint64_t)attribute->data_size) ||
				rh_h_u64(&hash, (uint64_t)attribute->initialized_size) ||
				rh_h_u64(&hash, (uint64_t)attribute->compressed_size) ||
				rh_h_u64(&hash, attribute->run_first) ||
				rh_h_u64(&hash, attribute->run_count) ||
				rh_h_u8(&hash, (uint8_t)run_slice_valid))
			return -1;
		if (!run_slice_valid)
			continue;
		for (j = 0; j < attribute->run_count; j++) {
			const struct rh_raw_run *run =
				&raw->runs[attribute->run_first + j];

			if (rh_h_u64(&hash, run->attribute_index) ||
					rh_h_u64(&hash, (uint64_t)run->vcn) ||
					rh_h_u64(&hash, (uint64_t)run->lcn) ||
					rh_h_u64(&hash, run->length) ||
					rh_h_u8(&hash, run->sparse))
				return -1;
		}
	}
	return rh_hash_stream_final(&hash, entry->mapping_hash);
}

static int rh_storage_exact(const struct rh_raw_mft_census *raw,
		const struct rh_raw_mft_slot *owner,
		const struct rh_raw_attribute *attribute)
{
	const struct rh_raw_mft_slot *storage;

	if (attribute->storage.record >= raw->slot_count)
		return 0;
	storage = &raw->slots[attribute->storage.record];
	if (storage->record != attribute->storage.record ||
			storage->sequence != attribute->storage.sequence)
		return 0;
	if (attribute->storage.record == owner->record)
		return attribute->storage.sequence == owner->sequence &&
			storage->state == RH_RAW_SLOT_LIVE_BASE;
	return storage->state == RH_RAW_SLOT_LIVE_EXTENT &&
		storage->base.record == owner->record &&
		storage->base.sequence == owner->sequence;
}

static int rh_exact_layout(const struct rh_census_reader *reader,
		const struct rh_raw_mft_census *raw,
		const struct rh_fixed_spec *spec,
		struct rh_fixed_metadata_reader_entry *entry)
{
	const struct rh_raw_mft_slot *owner;
	const struct rh_raw_attribute *base = NULL;
	uint64_t expected_vcn = 0, expected_clusters;
	size_t base_index = SIZE_MAX, selected_count = 0, candidate_count = 0;
	size_t i, j;

	if (spec->record >= raw->slot_count)
		return 0;
	owner = &raw->slots[spec->record];
	if (owner->record != spec->record ||
			owner->state != RH_RAW_SLOT_LIVE_BASE || !owner->sequence ||
			(owner->flags & le16_to_cpu(MFT_RECORD_IS_DIRECTORY)) ||
			!owner->attribute_list_assembled)
		return 0;
	entry->owner_sequence = owner->sequence;
	for (i = 0; i < raw->attribute_count; i++) {
		const struct rh_raw_attribute *attribute = &raw->attributes[i];

		if (!rh_target_attribute(attribute, spec->record))
			continue;
		candidate_count++;
		if (attribute->owner.sequence == owner->sequence &&
				attribute->lowest_vcn == 0) {
			if (base)
				return 0;
			base = attribute;
			base_index = i;
		}
	}
	if (!base || base->storage.record != owner->record ||
			base->storage.sequence != owner->sequence || !base->nonresident ||
			base->flags || base->compression_unit ||
			base->data_size != (int64_t)spec->size ||
			base->initialized_size != (int64_t)spec->size ||
			base->allocated_size < 0 ||
			(uint64_t)base->allocated_size !=
				((spec->size + RH_FIXED_CLUSTER_SIZE - 1U) &
				 ~(RH_FIXED_CLUSTER_SIZE - 1U)) ||
			base->compressed_size != base->allocated_size)
		return 0;
	entry->attribute_instance = base->instance;
	entry->data_size = (uint64_t)base->data_size;
	entry->initialized_size = (uint64_t)base->initialized_size;
	entry->allocated_size = (uint64_t)base->allocated_size;
	expected_clusters = entry->allocated_size / RH_FIXED_CLUSTER_SIZE;
	while (expected_vcn < expected_clusters) {
		const struct rh_raw_attribute *selected = NULL;
		size_t selected_index = SIZE_MAX, matches = 0;
		uint64_t next_vcn = expected_vcn;

		for (i = 0; i < raw->attribute_count; i++) {
			const struct rh_raw_attribute *attribute = &raw->attributes[i];

			if (!rh_target_attribute(attribute, spec->record) ||
					attribute->owner.sequence != owner->sequence ||
					attribute->lowest_vcn < 0 ||
					(uint64_t)attribute->lowest_vcn != expected_vcn)
				continue;
			selected = attribute;
			selected_index = i;
			matches++;
		}
		if (matches != 1U || !selected || !selected->nonresident ||
				selected->flags || selected->compression_unit ||
				selected->highest_vcn < selected->lowest_vcn ||
				selected->run_first > raw->run_count ||
				selected->run_count > raw->run_count - selected->run_first ||
				!selected->run_count || !rh_storage_exact(raw, owner, selected) ||
				!!selected->list_claimed != !!owner->has_attribute_list ||
				(selected_index == base_index) != (expected_vcn == 0U))
			return 0;
		for (j = 0; j < selected->run_count; j++) {
			const struct rh_raw_run *run =
				&raw->runs[selected->run_first + j];
			uint64_t physical;

			if (run->attribute_index != selected_index || run->vcn < 0 ||
					(uint64_t)run->vcn != next_vcn || !run->length ||
					run->length > UINT64_MAX - next_vcn || run->sparse ||
					run->lcn < 0 || (uint64_t)run->lcn >
					UINT64_MAX / RH_FIXED_CLUSTER_SIZE)
				return 0;
			physical = (uint64_t)run->lcn * RH_FIXED_CLUSTER_SIZE;
			if (run->length > UINT64_MAX / RH_FIXED_CLUSTER_SIZE ||
					physical > reader->device_size ||
					run->length * RH_FIXED_CLUSTER_SIZE >
					reader->device_size - physical)
				return 0;
			next_vcn += run->length;
		}
		if (selected->highest_vcn == INT64_MAX ||
				next_vcn != (uint64_t)selected->highest_vcn + 1U ||
				next_vcn > expected_clusters)
			return 0;
		for (i = 0, matches = 0; i < raw->run_count; i++)
			if (raw->runs[i].attribute_index == selected_index)
				matches++;
		if (matches != selected->run_count)
			return 0;
		selected_count++;
		expected_vcn = next_vcn;
	}
	if (selected_count != candidate_count || expected_vcn != expected_clusters)
		return 0;
	entry->mapping_complete = 1U;
	return 1;
}

static int rh_read_payload(const struct rh_census_reader *reader,
		const struct rh_raw_mft_census *raw,
		const struct rh_fixed_spec *spec, const unsigned char *canonical,
		struct rh_fixed_metadata_reader_entry *entry)
{
	struct rh_raw_mft_ref owner = {
		spec->record, entry->owner_sequence
	};
	struct rh_hash_stream hash;
	unsigned char buffer[65536];
	uint64_t offset = 0;
	int equal = 1;

	rh_hash_stream_init(&hash);
	while (offset < spec->size) {
		size_t part = sizeof(buffer);

		if ((uint64_t)part > spec->size - offset)
			part = (size_t)(spec->size - offset);
		if (rh_raw_mft_stream_pread_reader(reader, raw, owner,
				le32_to_cpu(AT_DATA), NULL, 0U, offset, part, buffer))
			return -1;
		if (memcmp(buffer, canonical + (size_t)offset, part))
			equal = 0;
		if (rh_hash_stream_update(&hash, buffer, part))
			return -1;
		offset += part;
	}
	if (rh_hash_stream_final(&hash, entry->current_hash))
		return -1;
	entry->bytes_examined = spec->size;
	entry->current_hash_valid = 1U;
	return equal && !memcmp(entry->current_hash, entry->canonical_hash, 32U);
}

static int rh_entry_evidence(const struct rh_fixed_metadata_reader_census *all,
		const struct rh_fixed_spec *spec,
		struct rh_fixed_metadata_reader_entry *entry)
{
	struct rh_hash_stream hash;
	size_t source_length = strlen(spec->source);

	rh_hash_stream_init(&hash);
	if (source_length > UINT16_MAX ||
			rh_h_bytes(&hash, "RHFXENT2", 8U) ||
			rh_h_u32(&hash, RH_FIXED_METADATA_READER_VERSION) ||
			rh_h_u16(&hash, (uint16_t)source_length) ||
			rh_h_bytes(&hash, spec->source, source_length) ||
			rh_h_u64(&hash, all->volume_serial) ||
			rh_h_bytes(&hash, all->raw_census_hash, 32U) ||
			rh_h_u32(&hash, (uint32_t)entry->kind) ||
			rh_h_u32(&hash, (uint32_t)entry->state) ||
			rh_h_u64(&hash, entry->owner_record) ||
			rh_h_u16(&hash, entry->owner_sequence) ||
			rh_h_u16(&hash, entry->attribute_instance) ||
			rh_h_u64(&hash, entry->expected_size) ||
			rh_h_u64(&hash, entry->data_size) ||
			rh_h_u64(&hash, entry->initialized_size) ||
			rh_h_u64(&hash, entry->allocated_size) ||
			rh_h_u64(&hash, entry->extents_examined) ||
			rh_h_u64(&hash, entry->runs_examined) ||
			rh_h_u64(&hash, entry->bytes_examined) ||
			rh_h_bytes(&hash, entry->canonical_hash, 32U) ||
			rh_h_bytes(&hash, entry->current_hash, 32U) ||
			rh_h_bytes(&hash, entry->mapping_hash, 32U) ||
			rh_h_u8(&hash, entry->current_hash_valid) ||
			rh_h_u8(&hash, entry->mapping_complete))
		return -1;
	return rh_hash_stream_final(&hash, entry->evidence_hash);
}

static int rh_census_evidence(struct rh_fixed_metadata_reader_census *census)
{
	struct rh_hash_stream hash;
	size_t i;

	rh_hash_stream_init(&hash);
	if (rh_h_bytes(&hash, "RHFXCNS2", 8U) ||
			rh_h_u32(&hash, census->version) ||
			rh_h_u64(&hash, census->volume_serial) ||
			rh_h_u64(&hash, census->entries_expected) ||
			rh_h_u64(&hash, census->entries_completed) ||
			rh_h_u64(&hash, census->entries_passed) ||
			rh_h_u64(&hash, census->entries_failed) ||
			rh_h_u64(&hash, census->entries_io) ||
			rh_h_bytes(&hash, census->raw_census_hash, 32U))
		return -1;
	for (i = 0; i < 2U; i++)
		if (rh_h_bytes(&hash, census->entries[i].evidence_hash, 32U))
			return -1;
	if (rh_h_u8(&hash, census->complete) ||
			rh_h_u8(&hash, census->no_io_uncertainty))
		return -1;
	return rh_hash_stream_final(&hash, census->evidence_hash);
}

static int rh_boot_serial(const struct rh_census_reader *reader,
		uint64_t *serial)
{
	unsigned char boot[512];
	unsigned int i;

	*serial = 0;
	if (rh_census_reader_read_exact(reader, 0, sizeof(boot), boot))
		return -1;
	if (memcmp(boot + 3U, "NTFS    ", 8U) || boot[510] != 0x55 ||
			boot[511] != 0xaa)
		return 0;
	for (i = 0; i < 8U; i++)
		*serial |= (uint64_t)boot[72U + i] << (8U * i);
	return *serial ? 1 : 0;
}

int rh_fixed_metadata_reader_census_run(
		const struct rh_census_reader *reader,
		const struct rh_raw_mft_census *raw,
		struct rh_fixed_metadata_reader_census *census)
{
	unsigned char *canonical[2] = { NULL, NULL };
	size_t canonical_length[2] = { 0, 0 };
	int boot_state;
	size_t i;

	if (census)
		memset(census, 0, sizeof(*census));
	if (!census || !rh_raw_ready(reader, raw)) {
		errno = EINVAL;
		return -1;
	}
	census->version = RH_FIXED_METADATA_READER_VERSION;
	census->generation = raw->generation;
	census->entries_expected = RH_FIXED_METADATA_READER_ENTRY_COUNT;
	memcpy(census->raw_census_hash, raw->census_hash, 32U);
	for (i = 0; i < 2U; i++) {
		struct rh_fixed_metadata_reader_entry *entry = &census->entries[i];

		entry->kind = rh_fixed_specs[i].kind;
		entry->owner_record = rh_fixed_specs[i].record;
		entry->expected_size = rh_fixed_specs[i].size;
		if (rh_canonical_build(&rh_fixed_specs[i], &canonical[i],
				&canonical_length[i], entry->canonical_hash) ||
				canonical_length[i] != rh_fixed_specs[i].size ||
				rh_hash_observed_mapping(raw, &rh_fixed_specs[i], entry))
			goto fail;
	}
	boot_state = rh_boot_serial(reader, &census->volume_serial);
	for (i = 0; i < 2U; i++) {
		struct rh_fixed_metadata_reader_entry *entry = &census->entries[i];
		int layout, payload;

		if (boot_state < 0) {
			entry->state = RH_FIXED_METADATA_READER_IO;
			continue;
		}
		layout = rh_exact_layout(reader, raw, &rh_fixed_specs[i], entry);
		if (!boot_state || !layout) {
			entry->state = RH_FIXED_METADATA_READER_FAIL;
			continue;
		}
		payload = rh_read_payload(reader, raw, &rh_fixed_specs[i],
			canonical[i], entry);
		if (payload < 0)
			entry->state = RH_FIXED_METADATA_READER_IO;
		else if (!payload)
			entry->state = RH_FIXED_METADATA_READER_FAIL;
		else
			entry->state = RH_FIXED_METADATA_READER_PASS;
	}
	for (i = 0; i < 2U; i++) {
		struct rh_fixed_metadata_reader_entry *entry = &census->entries[i];

		if (entry->state == RH_FIXED_METADATA_READER_PASS)
			census->entries_passed++;
		else if (entry->state == RH_FIXED_METADATA_READER_FAIL)
			census->entries_failed++;
		else if (entry->state == RH_FIXED_METADATA_READER_IO)
			census->entries_io++;
		else {
			errno = EIO;
			goto fail;
		}
		census->entries_completed++;
		if (rh_entry_evidence(census, &rh_fixed_specs[i], entry))
			goto fail;
	}
	census->complete = census->entries_completed ==
		census->entries_expected;
	census->no_io_uncertainty = !census->entries_io;
	if (!census->complete || rh_census_evidence(census))
		goto fail;
	for (i = 0; i < 2U; i++) {
		memset(canonical[i], 0, canonical_length[i]);
		free(canonical[i]);
	}
	errno = 0;
	return 0;
fail:
	{
		int saved_errno = errno ? errno : EIO;

		for (i = 0; i < 2U; i++) {
			if (canonical[i])
				memset(canonical[i], 0, canonical_length[i]);
			free(canonical[i]);
		}
		memset(census, 0, sizeof(*census));
		errno = saved_errno;
	}
	return -1;
}
