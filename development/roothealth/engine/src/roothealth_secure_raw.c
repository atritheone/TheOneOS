/* ROOTHEALTH_REPAIR_ROLE(DIAGNOSTIC) ROOTHEALTH_IO_ROLE(PLANNER) */
#include "config.h"

#include <errno.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include "roothealth_secure_raw.h"
#include "roothealth_secure_reader.h"
#include "roothealth_write.h"

#define RH_SECURE_CLUSTER_SIZE UINT64_C(4096)
#define RH_SECURE_RECORD UINT64_C(9)

struct rh_secure_raw_extent_ref {
	const struct rh_raw_attribute *attribute;
	size_t attribute_index;
};

static int rh_secure_bytes_nonzero(const unsigned char *bytes, size_t length)
{
	size_t i;

	for (i = 0; i < length; i++)
		if (bytes[i])
			return 1;
	return 0;
}

static int rh_secure_raw_name_equal(const struct rh_raw_mft_census *census,
		const struct rh_raw_attribute *attribute,
		const unsigned char *name_utf16le, uint16_t name_length)
{
	if (attribute->name_length != name_length ||
			(name_length && !name_utf16le) ||
			attribute->name_offset > census->name_arena_size ||
			(size_t)name_length * 2U >
				census->name_arena_size - attribute->name_offset)
		return 0;
	return !name_length || !memcmp(census->name_arena + attribute->name_offset,
		name_utf16le, (size_t)name_length * 2U);
}

static int rh_secure_raw_stream_equal(const struct rh_raw_mft_census *census,
		const struct rh_raw_attribute *attribute, struct rh_raw_mft_ref owner,
		uint32_t type, const unsigned char *name_utf16le,
		uint16_t name_length)
{
	return attribute->owner.record == owner.record &&
		attribute->owner.sequence == owner.sequence &&
		attribute->type == type &&
		rh_secure_raw_name_equal(census, attribute, name_utf16le, name_length);
}

int rh_secure_raw_census_valid(const struct rh_raw_mft_census *census,
		uint64_t generation, uint16_t secure_sequence)
{
	const struct rh_raw_mft_slot *slot;

	if (!census || !generation || census->generation != generation ||
			!secure_sequence || !census->records_bounded ||
			!census->attribute_lists_complete || !census->extents_complete ||
			census->slots_completed != census->slots_expected ||
			census->extents_completed != census->extents_expected ||
			census->runs_completed != census->runs_expected ||
			census->slot_count <= RH_SECURE_RECORD || !census->slots ||
			!census->attributes || !census->runs ||
			!rh_secure_bytes_nonzero(census->census_hash, 32))
		return 0;
	slot = &census->slots[RH_SECURE_RECORD];
	return slot->state == RH_RAW_SLOT_LIVE_BASE &&
		slot->record == RH_SECURE_RECORD && slot->sequence == secure_sequence &&
		(!slot->has_attribute_list || slot->attribute_list_assembled);
}

static int rh_secure_raw_extent_compare(const void *left, const void *right)
{
	const struct rh_secure_raw_extent_ref *first = left;
	const struct rh_secure_raw_extent_ref *second = right;

	if (first->attribute->lowest_vcn != second->attribute->lowest_vcn)
		return first->attribute->lowest_vcn < second->attribute->lowest_vcn ?
			-1 : 1;
	if (first->attribute->storage.record != second->attribute->storage.record)
		return first->attribute->storage.record <
			second->attribute->storage.record ? -1 : 1;
	return first->attribute->instance < second->attribute->instance ? -1 :
		first->attribute->instance > second->attribute->instance ? 1 : 0;
}

static int rh_secure_raw_append_slice(
		const struct rh_secure_read_source *source,
		const struct rh_raw_attribute *attribute, const struct rh_raw_run *run,
		uint64_t stream_size, struct rh_secure_mapping_slice **slices,
		size_t *slice_count)
{
	struct rh_secure_mapping_slice *grown;
	uint64_t logical, run_bytes, take, physical;

	if (run->vcn < 0 || run->lcn < 0 || !run->length || run->sparse ||
			(uint64_t)run->vcn > UINT64_MAX / RH_SECURE_CLUSTER_SIZE ||
			run->length > UINT64_MAX / RH_SECURE_CLUSTER_SIZE ||
			(uint64_t)run->lcn > UINT64_MAX / RH_SECURE_CLUSTER_SIZE) {
		errno = EIO;
		return -1;
	}
	logical = (uint64_t)run->vcn * RH_SECURE_CLUSTER_SIZE;
	run_bytes = run->length * RH_SECURE_CLUSTER_SIZE;
	physical = (uint64_t)run->lcn * RH_SECURE_CLUSTER_SIZE;
	if (logical >= stream_size)
		return 0;
	take = run_bytes;
	if (take > stream_size - logical)
		take = stream_size - logical;
	if (!take || physical > rh_secure_source_size(source) ||
			take > rh_secure_source_size(source) - physical ||
			take > SIZE_MAX || *slice_count >= SIZE_MAX / sizeof(**slices)) {
		errno = EIO;
		return -1;
	}
	{
		int excluded = rh_secure_source_excluded(source, physical, take);

		if (excluded) {
			if (excluded > 0)
				errno = EIO;
			return -1;
		}
	}
	grown = realloc(*slices, (*slice_count + 1U) * sizeof(**slices));
	if (!grown)
		return -1;
	*slices = grown;
	grown = &grown[(*slice_count)++];
	memset(grown, 0, sizeof(*grown));
	grown->logical_offset = logical;
	grown->length = take;
	grown->physical_offset = physical;
	grown->logical_vcn = run->vcn;
	grown->lcn = run->lcn;
	grown->storage_mft_record = attribute->storage.record;
	grown->storage_sequence = attribute->storage.sequence;
	grown->attribute_instance = attribute->instance;
	grown->lowest_vcn = attribute->lowest_vcn;
	return 0;
}

static int rh_secure_raw_build_mapping_common(
		const struct rh_raw_mft_census *census,
		const struct rh_secure_read_source *source,
		struct rh_raw_mft_ref owner, uint32_t type,
		const unsigned char *name_utf16le, uint16_t name_length,
		uint64_t minimum_data_size, uint64_t maximum_data_size,
		struct rh_secure_mapping_slice **slices, size_t *slice_count,
		uint64_t *data_size)
{
	struct rh_secure_raw_extent_ref *extents = NULL;
	const struct rh_raw_attribute *base = NULL;
	uint64_t expected_vcn = 0, covered = 0, allocated_clusters;
	size_t extent_count = 0, i, j;
	int result = -1;

	if (!census || !rh_secure_source_valid(source) || !owner.sequence ||
			!slices || !slice_count ||
			!data_size || *slices || *slice_count || !maximum_data_size ||
			(!name_utf16le && name_length)) {
		errno = EINVAL;
		return -1;
	}
	for (i = 0; i < census->attribute_count; i++) {
		const struct rh_raw_attribute *attribute = &census->attributes[i];
		void *grown;

		if (!rh_secure_raw_stream_equal(census, attribute, owner, type,
				name_utf16le, name_length))
			continue;
		if (!attribute->nonresident || attribute->flags ||
				attribute->compression_unit ||
				attribute->lowest_vcn < 0 || attribute->highest_vcn <
					attribute->lowest_vcn || !attribute->storage.sequence ||
				extent_count >= SIZE_MAX / sizeof(*extents)) {
			errno = EIO;
			goto out;
		}
		grown = realloc(extents, (extent_count + 1U) * sizeof(*extents));
		if (!grown)
			goto out;
		extents = grown;
		extents[extent_count].attribute = attribute;
		extents[extent_count].attribute_index = i;
		extent_count++;
		if (!attribute->lowest_vcn) {
			if (base) {
				errno = EIO;
				goto out;
			}
			base = attribute;
		}
	}
	if (!extent_count || !base || base->data_size < 0 ||
			base->initialized_size != base->data_size ||
			base->allocated_size < base->data_size ||
			base->allocated_size < 0 ||
			(base->allocated_size % (int64_t)RH_SECURE_CLUSTER_SIZE) ||
			(uint64_t)base->data_size < minimum_data_size ||
			(uint64_t)base->data_size > maximum_data_size) {
		errno = EIO;
		goto out;
	}
	*data_size = (uint64_t)base->data_size;
	allocated_clusters = (uint64_t)base->allocated_size /
		RH_SECURE_CLUSTER_SIZE;
	qsort(extents, extent_count, sizeof(*extents),
		rh_secure_raw_extent_compare);
	for (i = 0; i < extent_count; i++) {
		const struct rh_raw_attribute *attribute = extents[i].attribute;
		uint64_t extent_end;

		if ((uint64_t)attribute->lowest_vcn != expected_vcn ||
				(uint64_t)attribute->highest_vcn == UINT64_MAX ||
				(uint64_t)attribute->highest_vcn < expected_vcn) {
			errno = EIO;
			goto out;
		}
		extent_end = (uint64_t)attribute->highest_vcn + 1U;
		if (extent_end > allocated_clusters || !attribute->run_count ||
				attribute->run_first > census->run_count ||
				attribute->run_count > census->run_count - attribute->run_first) {
			errno = EIO;
			goto out;
		}
		for (j = 0; j < attribute->run_count; j++) {
			const struct rh_raw_run *run =
				&census->runs[attribute->run_first + j];

			if (run->attribute_index != extents[i].attribute_index ||
					run->vcn < 0 || (uint64_t)run->vcn != expected_vcn ||
					run->length > extent_end - expected_vcn ||
					rh_secure_raw_append_slice(source, attribute, run,
						*data_size, slices, slice_count)) {
				errno = errno ? errno : EIO;
				goto out;
			}
			expected_vcn += run->length;
			if (run->vcn >= 0 && (uint64_t)run->vcn *
					RH_SECURE_CLUSTER_SIZE < *data_size) {
				uint64_t end = (uint64_t)run->vcn * RH_SECURE_CLUSTER_SIZE +
					run->length * RH_SECURE_CLUSTER_SIZE;

				if (end > *data_size)
					end = *data_size;
				covered = end;
			}
		}
		if (expected_vcn != extent_end) {
			errno = EIO;
			goto out;
		}
	}
	if (expected_vcn != allocated_clusters || covered != *data_size ||
			!*slice_count) {
		errno = EIO;
		goto out;
	}
	result = 0;
out:
	free(extents);
	if (result) {
		free(*slices);
		*slices = NULL;
		*slice_count = 0;
		*data_size = 0;
	}
	return result;
}

int rh_secure_raw_build_mapping(const struct rh_raw_mft_census *census,
		struct rh_writer *writer, struct rh_raw_mft_ref owner, uint32_t type,
		const unsigned char *name_utf16le, uint16_t name_length,
		uint64_t minimum_data_size, uint64_t maximum_data_size,
		struct rh_secure_mapping_slice **slices, size_t *slice_count,
		uint64_t *data_size)
{
	const struct rh_secure_read_source source = { writer, NULL };

	return rh_secure_raw_build_mapping_common(census, &source, owner, type,
		name_utf16le, name_length, minimum_data_size, maximum_data_size,
		slices, slice_count, data_size);
}

int rh_secure_raw_build_mapping_reader(const struct rh_raw_mft_census *census,
		const struct rh_census_reader *reader, struct rh_raw_mft_ref owner,
		uint32_t type, const unsigned char *name_utf16le,
		uint16_t name_length, uint64_t minimum_data_size,
		uint64_t maximum_data_size, struct rh_secure_mapping_slice **slices,
		size_t *slice_count, uint64_t *data_size)
{
	const struct rh_secure_read_source source = { NULL, reader };

	return rh_secure_raw_build_mapping_common(census, &source, owner, type,
		name_utf16le, name_length, minimum_data_size, maximum_data_size,
		slices, slice_count, data_size);
}

int rh_secure_raw_find_resident(const struct rh_raw_mft_census *census,
		struct rh_raw_mft_ref owner, uint32_t type,
		const unsigned char *name_utf16le, uint16_t name_length,
		struct rh_secure_raw_resident *resident)
{
	const struct rh_raw_attribute *found = NULL;
	size_t i;

	if (!census || !resident || !owner.sequence ||
			(!name_utf16le && name_length)) {
		errno = EINVAL;
		return -1;
	}
	for (i = 0; i < census->attribute_count; i++) {
		const struct rh_raw_attribute *attribute = &census->attributes[i];

		if (!rh_secure_raw_stream_equal(census, attribute, owner, type,
				name_utf16le, name_length))
			continue;
		if (found || attribute->nonresident || attribute->flags ||
				attribute->resident_flags ||
				!attribute->storage.sequence ||
				attribute->record_offset > 1024U ||
				attribute->record_length > 1024U - attribute->record_offset ||
				attribute->value_offset > attribute->record_length ||
				attribute->value_length >
					attribute->record_length - attribute->value_offset) {
			errno = EIO;
			return -1;
		}
		found = attribute;
	}
	if (!found) {
		errno = ENOENT;
		return -1;
	}
	memset(resident, 0, sizeof(*resident));
	resident->storage_mft_record = found->storage.record;
	resident->storage_sequence = found->storage.sequence;
	resident->attribute_instance = found->instance;
	resident->record_offset = found->record_offset;
	resident->record_length = found->record_length;
	resident->value_offset = found->value_offset;
	resident->value_length = found->value_length;
	return 0;
}
