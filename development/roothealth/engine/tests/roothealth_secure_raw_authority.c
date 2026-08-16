#include "config.h"

#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "endians.h"
#include "device.h"
#include "inode.h"
#include "layout.h"
#include "dir.h"
#include "roothealth_overlay.h"
#include "roothealth_raw_mft.h"
#include "roothealth_secure.h"
#include "roothealth_secure_raw.h"

static int u32_compare(const void *left, const void *right)
{
	uint32_t first = *(const uint32_t *)left;
	uint32_t second = *(const uint32_t *)right;

	return first < second ? -1 : first > second ? 1 : 0;
}

static int gather_live_ids(const struct rh_raw_mft_census *raw,
		uint32_t **ids_out, size_t *count_out, uint64_t *references_out,
		size_t *distinct_si_ids_out)
{
	uint32_t *ids = NULL;
	size_t count = 0, i, unique;
	int zero_seen = 0;

	for (i = 0; i < raw->attribute_count; i++) {
		const struct rh_raw_attribute *attribute = &raw->attributes[i];
		const unsigned char *value;
		uint32_t id;
		void *grown;

		if (attribute->type != AT_STANDARD_INFORMATION ||
				attribute->value_length != sizeof(STANDARD_INFORMATION))
			continue;
		if (attribute->nonresident || attribute->name_length ||
				attribute->value_arena_offset > raw->value_arena_size ||
				attribute->value_length > raw->value_arena_size -
					attribute->value_arena_offset ||
				count >= SIZE_MAX / sizeof(*ids))
			goto error;
		value = raw->value_arena + attribute->value_arena_offset;
		id = (uint32_t)value[52] | ((uint32_t)value[53] << 8) |
			((uint32_t)value[54] << 16) | ((uint32_t)value[55] << 24);
		if (id < 0x100U) {
			if (id)
				goto error;
			zero_seen = 1;
			continue;
		}
		grown = realloc(ids, (count + 1U) * sizeof(*ids));
		if (!grown)
			goto error;
		ids = grown;
		ids[count++] = id;
	}
	if (!count)
		goto error;
	qsort(ids, count, sizeof(*ids), u32_compare);
	for (i = 0, unique = 0; i < count; i++)
		if (!i || ids[i] != ids[i - 1U])
			ids[unique++] = ids[i];
	*references_out = count;
	*ids_out = ids;
	*count_out = unique;
	*distinct_si_ids_out = unique + (size_t)zero_seen;
	return 0;
error:
	free(ids);
	return -1;
}

static uint32_t descriptor_hash(const unsigned char *bytes, size_t length)
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

static int gather_sds_ids(const struct rh_raw_mft_census *raw,
		struct rh_writer *writer, struct rh_raw_mft_ref owner,
		const uint32_t *referenced_ids, size_t referenced_count,
		uint32_t **ids_out, size_t *count_out)
{
	struct rh_secure_mapping_slice *slices = NULL;
	unsigned char *bytes = NULL;
	uint32_t *ids = NULL;
	uint64_t size = 0;
	size_t slice_count = 0, count = 0, i;
	uint64_t pair_base;
	int result = -1;
	const char *phase = "mapping";

	if (rh_secure_raw_build_mapping(raw, writer, owner, AT_DATA,
			(const unsigned char *)STREAM_SDS, 4, 0x40001U,
			writer->device_size, &slices, &slice_count, &size)) {
		for (i = 0; i < raw->attribute_count; i++) {
			const struct rh_raw_attribute *attribute = &raw->attributes[i];
			const unsigned char *name;

			if (attribute->owner.record != owner.record ||
					attribute->type != AT_DATA || attribute->name_length != 4 ||
					attribute->name_offset > raw->name_arena_size ||
					8U > raw->name_arena_size - attribute->name_offset)
				continue;
			name = raw->name_arena + attribute->name_offset;
			if (memcmp(name, STREAM_SDS, 8U))
				continue;
			fprintf(stderr, " raw SDS storage=%llu:%u instance=%u "
				"vcn=%lld..%lld runs=%zu listed=%u data=%lld alloc=%lld\n",
				(unsigned long long)attribute->storage.record,
				attribute->storage.sequence, attribute->instance,
				(long long)attribute->lowest_vcn,
				(long long)attribute->highest_vcn, attribute->run_count,
				attribute->list_claimed, (long long)attribute->data_size,
				(long long)attribute->allocated_size);
		}
		goto out;
	}
	if (size > SIZE_MAX)
		goto out;
	bytes = malloc((size_t)size);
	if (!bytes)
		goto out;
	phase = "stream-read";
	for (i = 0; i < slice_count; i++)
		if (rh_writer_read(writer, slices[i].physical_offset,
				(size_t)slices[i].length, bytes + slices[i].logical_offset))
			goto out;
	phase = "descriptor-scan";
	for (pair_base = 0; pair_base < size; pair_base += UINT64_C(0x80000)) {
		uint64_t cursor;

		if (size - pair_base <= UINT64_C(0x40000))
			break;
		for (cursor = 0;
				cursor + offsetof(SDS_ENTRY, sid) <= UINT64_C(0x40000);
				cursor += 16U) {
			uint64_t primary = pair_base + cursor;
			uint64_t backup = pair_base + UINT64_C(0x40000) + cursor;
			const SDS_ENTRY *entry = (const SDS_ENTRY *)(bytes + primary);
			uint32_t length = le32_to_cpu(entry->length);
			uint32_t id = le32_to_cpu(entry->security_id);
			uint64_t offset = le64_to_cpu(entry->offset);
			void *grown;

			if (offset != primary || id < 0x100U ||
					length < offsetof(SDS_ENTRY, sid) +
						sizeof(SECURITY_DESCRIPTOR_RELATIVE) ||
					(length - offsetof(SDS_ENTRY, sid)) & 3U ||
					length > UINT64_C(0x40000) - cursor ||
					backup > size || length > size - backup ||
					!rh_secure_descriptor_bytes_valid(
						bytes + primary + offsetof(SDS_ENTRY, sid),
						length - offsetof(SDS_ENTRY, sid)) ||
					descriptor_hash(bytes + primary +
						offsetof(SDS_ENTRY, sid),
						length - offsetof(SDS_ENTRY, sid)) !=
						le32_to_cpu(entry->hash))
				continue;
			if (memcmp(bytes + primary, bytes + backup, length))
				goto out;
			grown = realloc(ids, (count + 1U) * sizeof(*ids));
			if (!grown)
				goto out;
			ids = grown;
			ids[count++] = id;
		}
	}
	if (!count)
		goto out;
	phase = "identity-sort";
	qsort(ids, count, sizeof(*ids), u32_compare);
	for (i = 1; i < count; i++)
		if (ids[i] == ids[i - 1U])
			goto out;
	for (i = 0; i < referenced_count; i++)
		if (!bsearch(&referenced_ids[i], ids, count, sizeof(*ids),
			u32_compare))
			goto out;
	*ids_out = ids;
	*count_out = count;
	ids = NULL;
	result = 0;
out:
	if (result)
		fprintf(stderr, "gather_sds phase=%s slices=%zu size=%llu ids=%zu "
			"errno=%d\n", phase, slice_count, (unsigned long long)size,
			count, errno);
	free(ids);
	free(bytes);
	free(slices);
	return result;
}

static void fact_hash(const char *label, unsigned char output[32])
{
	rh_sha256(label, strlen(label), output);
}

static void seed_secure_census(struct rh_secure_census *census,
		const struct rh_raw_mft_census *raw, uint64_t generation,
		const uint32_t *ids, size_t id_count, uint64_t references,
		uint64_t legacy_count, const unsigned char legacy_hash[32])
{
	memset(census, 0, sizeof(*census));
	census->generation = generation;
	census->complete_security_id_census = 1;
	census->security_ids_expected = id_count;
	census->security_ids_examined = id_count;
	census->live_security_ids = ids;
	census->live_security_id_count = id_count;
	census->legacy_security_descriptors_expected = legacy_count;
	census->legacy_security_descriptors_examined = legacy_count;
	memcpy(census->legacy_security_descriptor_hash, legacy_hash, 32);
	census->raw_mft_extent_authority_complete = 1;
	census->raw_mft_census = raw;
	memcpy(census->raw_mft_census_hash, raw->census_hash, 32);
	census->security_id_references_expected = references;
	census->security_id_references_examined = references;
	census->security_id_references_resolved = references;
}

static int seal_full_authority(struct rh_secure_census *census,
		const struct rh_secure_inspection *inspection,
		enum rh_secure_view view, struct rh_secure_authority *authority)
{
	census->view = view;
	census->ledger_format = RH_SECURE_LEDGER_FORMAT;
	census->volume_serial = inspection->volume_serial;
	census->coverage_complete = 1;
	census->identity_bound = 1;
	census->no_io_uncertainty = 1;
	census->complete_mft_census = 1;
	census->complete_attribute_census = 1;
	census->complete_runlist_census = 1;
	census->complete_namespace_census = 1;
	census->complete_index_census = 1;
	census->complete_security_descriptor_census = 1;
	census->namespace_security_reciprocity_complete = 1;
	census->global_security_identity_complete = 1;
	census->sole_valid_peer_authority_complete = 1;
	census->no_conflicting_valid_authorities = 1;
	census->target_ownership_exact = 1;
	census->targets_outside_wal = 1;
	census->data_preserving = 1;
	census->final_overlay_valid = view == RH_SECURE_STAGED;
	census->mft_records_expected = census->raw_mft_census->slots_expected;
	census->mft_records_examined = census->mft_records_expected;
	census->attributes_expected = census->raw_mft_census->attribute_count;
	census->attributes_examined = census->attributes_expected;
	census->runs_expected = census->raw_mft_census->run_count;
	census->runs_examined = census->runs_expected;
	census->namespace_links_expected =
		census->raw_mft_census->file_name_count;
	census->namespace_links_examined = census->namespace_links_expected;
	census->namespace_links_reciprocal = census->namespace_links_expected;
	census->security_descriptors_expected = inspection->descriptor_count +
		census->legacy_security_descriptors_expected;
	census->security_descriptors_examined =
		census->security_descriptors_expected;
	fact_hash("release-rhcov3-coverage", census->coverage_ledger_hash);
	fact_hash("release-rhcov3-identity", census->identity_graph_hash);
	fact_hash("release-rhcov3-namespace", census->namespace_security_hash);
	fact_hash("release-rhcov3-security-use", census->security_id_use_hash);
	fact_hash("release-rhcov3-global", census->global_security_hash);
	memcpy(census->descriptor_manifest_hash,
		inspection->descriptor_manifest_hash, 32);
	return rh_secure_authority_seal(census, authority);
}

static int check_mapping(const struct rh_raw_mft_census *raw,
		struct rh_writer *writer, struct rh_raw_mft_ref owner, uint32_t type,
		const ntfschar *name, uint16_t name_length, uint64_t expected_size,
		size_t *extent_count)
{
	struct rh_secure_mapping_slice *slices = NULL;
	uint64_t size = 0;
	size_t count = 0, i;
	int result = -1;

	if (rh_secure_raw_build_mapping(raw, writer, owner, type,
			(const unsigned char *)name, name_length, 1U,
			writer->device_size, &slices, &count, &size) ||
			(expected_size && size != expected_size))
		goto out;
	for (i = 0; i < count; i++)
		if (!slices[i].storage_sequence ||
				slices[i].lowest_vcn < 0)
			goto out;
	*extent_count = count;
	result = 0;
out:
	free(slices);
	return result;
}

static int count_stream_extents(const struct rh_raw_mft_census *raw,
		struct rh_raw_mft_ref owner, uint32_t type, const ntfschar *name,
		uint16_t name_length, size_t *extent_count, size_t *offbase_count)
{
	size_t count = 0, offbase = 0, i;

	for (i = 0; i < raw->attribute_count; i++) {
		const struct rh_raw_attribute *attribute = &raw->attributes[i];

		if (attribute->owner.record != owner.record ||
				attribute->owner.sequence != owner.sequence ||
				attribute->type != type ||
				attribute->name_length != name_length ||
				attribute->name_offset > raw->name_arena_size ||
				(size_t)name_length * 2U >
					raw->name_arena_size - attribute->name_offset ||
				memcmp(raw->name_arena + attribute->name_offset, name,
					(size_t)name_length * 2U))
			continue;
		count++;
		if (attribute->storage.record != owner.record)
			offbase++;
	}
	if (!count)
		return -1;
	*extent_count = count;
	*offbase_count = offbase;
	return 0;
}

int main(int argc, char **argv)
{
	const uint64_t generation = UINT64_C(0x5345435552415701);
	struct rh_writer writer;
	struct rh_ntfs_overlay overlay;
	struct rh_raw_mft_census raw;
	struct rh_secure_raw_resident root, bitmap, sii_root, sii_bitmap;
	struct rh_secure_inspection inspection;
	struct rh_secure_census secure_census;
	struct rh_secure_authority authority;
	struct rh_secure_batch_cursor before, after;
	struct rh_secure_plan plan;
	struct rh_raw_mft_ref owner;
	uint32_t *live_ids = NULL;
	uint32_t *referenced_ids = NULL;
	unsigned char legacy_hash[32];
	uint64_t legacy_count = 0, references = 0;
	size_t live_id_count = 0, referenced_id_count = 0;
	size_t distinct_si_id_count = 0;
	size_t sds_slices = 0, sdh_slices = 0, sii_slices = 0;
	size_t sds_extents = 0, sds_offbase = 0, sdh_extents = 0;
	size_t sdh_offbase = 0, sii_extents = 0, sii_offbase = 0;
	size_t expected_descriptor_count = 29U;
	int release_mode = 1;
	int require_attrlist_extents = 0;
	int mounted = 0, opened = 0, result = 1;

	if (argc != 2 && argc != 4)
		return 64;
	if (argc == 4) {
		char *end = NULL;
		unsigned long parsed;

		if (strcmp(argv[2], "fixture") &&
				strcmp(argv[2], "fixture-attrlist"))
			return 64;
		require_attrlist_extents = !strcmp(argv[2], "fixture-attrlist");
		errno = 0;
		parsed = strtoul(argv[3], &end, 10);
		if (errno || !end || *end || !parsed || parsed > UINT32_MAX - 0x100U)
			return 64;
		expected_descriptor_count = (size_t)parsed;
		release_mode = 0;
	}
	memset(&raw, 0, sizeof(raw));
	memset(&inspection, 0, sizeof(inspection));
	memset(&authority, 0, sizeof(authority));
	memset(&before, 0, sizeof(before));
	if (rh_writer_open(&writer, argv[1]))
		goto out;
	opened = 1;
	if (rh_ntfs_overlay_mount(&overlay, &writer, 0))
		goto out;
	mounted = 1;
	if (rh_raw_mft_census_run(overlay.volume, &writer, generation, &raw) ||
			raw.slot_count <= FILE_Secure) {
		fprintf(stderr, "raw census failed bounded=%u invalid=%llu "
			"unreadable=%llu errno=%d\n", raw.records_bounded,
			(unsigned long long)raw.invalid_records,
			(unsigned long long)raw.unreadable_records, errno);
		goto out;
	}
	owner.record = FILE_Secure;
	owner.sequence = raw.slots[FILE_Secure].sequence;
	if (!rh_secure_raw_census_valid(&raw, generation, owner.sequence)) {
		fprintf(stderr, "raw authority shape invalid bounded=%u attrlist=%u "
			"extents=%u slots=%llu/%llu runs=%llu/%llu ext=%llu/%llu "
			"slot9=%u seq=%u generation=%llu/%llu\n",
			raw.records_bounded, raw.attribute_lists_complete,
			raw.extents_complete,
			(unsigned long long)raw.slots_completed,
			(unsigned long long)raw.slots_expected,
			(unsigned long long)raw.runs_completed,
			(unsigned long long)raw.runs_expected,
			(unsigned long long)raw.extents_completed,
			(unsigned long long)raw.extents_expected,
			raw.slots[FILE_Secure].state, owner.sequence,
			(unsigned long long)raw.generation,
			(unsigned long long)generation);
		for (size_t slot = 0; slot < raw.slot_count; slot++)
			if (raw.slots[slot].state == RH_RAW_SLOT_INVALID ||
					raw.slots[slot].state == RH_RAW_SLOT_UNREADABLE)
				fprintf(stderr, " bad_slot=%zu state=%u\n", slot,
					raw.slots[slot].state);
		goto out;
	}
	if (rh_secure_legacy_census(&raw, &legacy_count, legacy_hash)) {
		fprintf(stderr, "legacy descriptor census failed errno=%d\n", errno);
		for (size_t attribute_index = 0;
				attribute_index < raw.attribute_count; attribute_index++) {
			const struct rh_raw_attribute *attribute =
				&raw.attributes[attribute_index];

			if (attribute->type == AT_SECURITY_DESCRIPTOR)
				fprintf(stderr, " legacy owner=%llu storage=%llu "
					"nonresident=%u value=%u data=%lld si-slot-state=%u\n",
					(unsigned long long)attribute->owner.record,
					(unsigned long long)attribute->storage.record,
					attribute->nonresident, attribute->value_length,
					(long long)attribute->data_size,
					raw.slots[attribute->owner.record].state);
		}
		goto out;
	}
	if (gather_live_ids(&raw, &referenced_ids, &referenced_id_count,
			&references, &distinct_si_id_count)) {
		fprintf(stderr, "MFT security-id census failed errno=%d\n", errno);
		goto out;
	}
	if (gather_sds_ids(&raw, &writer, owner, referenced_ids,
			referenced_id_count, &live_ids, &live_id_count)) {
		fprintf(stderr, "SDS security-id census failed errno=%d\n", errno);
		goto out;
	}
	if (check_mapping(&raw, &writer, owner, AT_DATA, STREAM_SDS, 4,
			release_mode ? 268496U : 0U, &sds_slices)) {
		fprintf(stderr, "SDS mapping failed errno=%d\n", errno);
		goto out;
	}
	if (check_mapping(&raw, &writer, owner, AT_INDEX_ALLOCATION,
			NTFS_INDEX_SDH, 4, release_mode ? 4096U : 0U, &sdh_slices)) {
		fprintf(stderr, "SDH allocation mapping failed errno=%d\n", errno);
		goto out;
	}
	if (check_mapping(&raw, &writer, owner, AT_INDEX_ALLOCATION,
			NTFS_INDEX_SII, 4, release_mode ? 4096U : 0U, &sii_slices)) {
		fprintf(stderr, "SII allocation mapping failed errno=%d\n", errno);
		goto out;
	}
	if (count_stream_extents(&raw, owner, AT_DATA, STREAM_SDS, 4,
			&sds_extents, &sds_offbase) ||
			count_stream_extents(&raw, owner, AT_INDEX_ALLOCATION,
				NTFS_INDEX_SDH, 4, &sdh_extents, &sdh_offbase) ||
			count_stream_extents(&raw, owner, AT_INDEX_ALLOCATION,
				NTFS_INDEX_SII, 4, &sii_extents, &sii_offbase)) {
		fprintf(stderr, "raw extent count failed\n");
		goto out;
	}
	if (rh_secure_raw_find_resident(&raw, owner, AT_INDEX_ROOT,
			(const unsigned char *)NTFS_INDEX_SDH, 4, &root) ||
			rh_secure_raw_find_resident(&raw, owner, AT_BITMAP,
				(const unsigned char *)NTFS_INDEX_SDH, 4, &bitmap) ||
			rh_secure_raw_find_resident(&raw, owner, AT_INDEX_ROOT,
				(const unsigned char *)NTFS_INDEX_SII, 4, &sii_root) ||
			rh_secure_raw_find_resident(&raw, owner, AT_BITMAP,
				(const unsigned char *)NTFS_INDEX_SII, 4, &sii_bitmap) ||
			(release_mode && bitmap.value_length != 8U) ||
			!bitmap.value_length || writer.operation_count) {
		fprintf(stderr, "resident SDH root/bitmap failed errno=%d len=%u\n",
			errno, bitmap.value_length);
		goto out;
	}
	if (require_attrlist_extents &&
			(!raw.slots[FILE_Secure].has_attribute_list ||
			 !raw.slots[FILE_Secure].attribute_list_assembled ||
			 sds_extents < 2U || !sds_offbase || !sdh_offbase || !sii_offbase ||
			 root.storage_mft_record == FILE_Secure ||
			 bitmap.storage_mft_record == FILE_Secure ||
			 sii_root.storage_mft_record == FILE_Secure ||
			 sii_bitmap.storage_mft_record == FILE_Secure)) {
		fprintf(stderr, "record9 attrlist/extent placement incomplete\n");
		goto out;
	}
	seed_secure_census(&secure_census, &raw, generation, live_ids,
		live_id_count, references, legacy_count, legacy_hash);
	if ((release_mode && (legacy_count != 7U || live_id_count != 29U ||
			referenced_id_count != 20U || distinct_si_id_count != 21U)) ||
			live_id_count != expected_descriptor_count ||
			rh_secure_inspect(overlay.volume, &writer, &secure_census,
			&inspection) || inspection.descriptor_count != live_id_count ||
			(release_mode && inspection.sds_data_size != 268496U) ||
			!inspection.sds_clean ||
			!inspection.sdh_clean || !inspection.sii_clean ||
			!inspection.sdh_index.large || !inspection.sii_index.large ||
			(release_mode &&
			 (inspection.sdh_index.allocation_data_size != 4096U ||
			  inspection.sii_index.allocation_data_size != 4096U ||
			  inspection.sdh_index.bitmap_data_size != 8U ||
			  inspection.sii_index.bitmap_data_size != 8U)) ||
			seal_full_authority(&secure_census, &inspection,
				RH_SECURE_PRETRANSACTION, &authority) ||
			rh_secure_stage_batch(&overlay, &authority, &before, &after,
				&plan) != RH_SECURE_STAGE_CLEAN || !plan.clean ||
			!plan.batch || !after.complete || writer.operation_count) {
		fprintf(stderr, "full release Secure no-write gate failed ids=%zu "
			"descriptors=%zu sds=%llu clean=%d/%d/%d large=%d/%d "
			"alloc=%llu/%llu bitmap=%llu/%llu authority=%u ops=%zu "
			"errno=%d\n", live_id_count, inspection.descriptor_count,
			(unsigned long long)inspection.sds_data_size,
			inspection.sds_clean, inspection.sdh_clean, inspection.sii_clean,
			inspection.sdh_index.large, inspection.sii_index.large,
			(unsigned long long)inspection.sdh_index.allocation_data_size,
			(unsigned long long)inspection.sii_index.allocation_data_size,
			(unsigned long long)inspection.sdh_index.bitmap_data_size,
			(unsigned long long)inspection.sii_index.bitmap_data_size,
			authority.version, writer.operation_count, errno);
		goto out;
	}
	printf("raw_secure_authority=green mode=%s legacy=%llu sds_slices=%zu "
		"sdh_slices=%zu sii_slices=%zu sdh_bitmap=%u attrlists=%llu "
		"extents=%llu secure_live_entries=%zu secure_end_entries=1 "
		"secure_entries_with_end=%zu referenced_central_ids=%zu "
		"distinct_mft_si_ids=%zu central_references=%llu "
		"stream_extents=%zu/%zu/%zu offbase=%zu/%zu/%zu "
		"root_storage=%llu/%llu bitmap_storage=%llu/%llu operations=0\n",
		release_mode ? "release" : "fixture",
		(unsigned long long)legacy_count,
		sds_slices, sdh_slices, sii_slices, bitmap.value_length,
		(unsigned long long)raw.attribute_lists,
		(unsigned long long)raw.live_extent_records, live_id_count,
		live_id_count + 1U, referenced_id_count, distinct_si_id_count,
		(unsigned long long)references, sds_extents, sdh_extents, sii_extents,
		sds_offbase, sdh_offbase, sii_offbase,
		(unsigned long long)root.storage_mft_record,
		(unsigned long long)sii_root.storage_mft_record,
		(unsigned long long)bitmap.storage_mft_record,
		(unsigned long long)sii_bitmap.storage_mft_record);
	result = 0;
out:
	rh_raw_mft_census_release(&raw);
	rh_secure_authority_destroy(&authority);
	rh_secure_inspection_destroy(&inspection);
	free(live_ids);
	free(referenced_ids);
	if (mounted)
		rh_ntfs_overlay_unmount(&overlay);
	if (opened)
		rh_writer_close(&writer);
	if (result)
		perror("raw secure authority");
	return result;
}
