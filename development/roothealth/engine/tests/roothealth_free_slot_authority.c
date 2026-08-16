/* ROOTHEALTH_REPAIR_ROLE(DIAGNOSTIC) */
#include "config.h"

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "device.h"
#include "endians.h"
#include "layout.h"
#include "roothealth_free_slot_authority.h"
#include "roothealth_mft_bitmap.h"
#include "roothealth_namespace.h"
#include "roothealth_raw_mft.h"
#include "roothealth_write.h"
#include "volume.h"

static void source_hash(enum rh_free_slot_component_kind kind,
		unsigned int variant, unsigned char hash[32])
{
	unsigned char input[16] = {0};

	memcpy(input, "component", 9U);
	input[12] = (unsigned char)kind;
	input[13] = (unsigned char)variant;
	rh_sha256(input, sizeof(input), hash);
}

static void destroy_components(
		struct rh_free_slot_component_seal *seals[
			RH_FREE_SLOT_COMPONENT_COUNT])
{
	size_t i;

	for (i = 1; i < RH_FREE_SLOT_COMPONENT_COUNT; i++) {
		rh_free_slot_component_seal_destroy(seals[i]);
		seals[i] = NULL;
	}
}

static int build_components(uint64_t generation,
		const struct rh_free_slot_range *wal_ranges, size_t wal_range_count,
		struct rh_free_slot_component_seal *seals[
			RH_FREE_SLOT_COMPONENT_COUNT],
		const struct rh_free_slot_component_seal *ordered[
			RH_FREE_SLOT_REQUIRED_COMPONENTS])
{
	unsigned char hash[32];
	size_t kind, output = 0;

	memset(seals, 0, RH_FREE_SLOT_COMPONENT_COUNT * sizeof(*seals));
	for (kind = 1; kind < RH_FREE_SLOT_COMPONENT_COUNT; kind++) {
		source_hash((enum rh_free_slot_component_kind)kind, 0U, hash);
		if (rh_free_slot_test_component_seal_create(
				(enum rh_free_slot_component_kind)kind, generation,
				kind == RH_FREE_SLOT_COMPONENT_WAL_EXCLUSIONS ?
					wal_range_count : 0U,
				kind == RH_FREE_SLOT_COMPONENT_WAL_EXCLUSIONS ?
					wal_range_count : 0U,
				hash, NULL, 0U,
				kind == RH_FREE_SLOT_COMPONENT_WAL_EXCLUSIONS ?
					wal_ranges : NULL,
				kind == RH_FREE_SLOT_COMPONENT_WAL_EXCLUSIONS ?
					wal_range_count : 0U, &seals[kind]))
			goto fail;
	}
	/* Deliberately reverse input order; the authority keys seals by type. */
	for (kind = RH_FREE_SLOT_COMPONENT_COUNT - 1U; kind > 0; kind--)
		ordered[output++] = seals[kind];
	return 0;
fail:
	destroy_components(seals);
	return -1;
}

static int omitted_component_negatives(struct rh_writer *writer,
		const struct rh_raw_mft_census *raw,
		const struct rh_mft_bitmap_census *bitmap,
		const struct rh_namespace_census *namespace_census, uint64_t record,
		uint16_t sequence,
		const struct rh_free_slot_component_seal *const complete[
			RH_FREE_SLOT_REQUIRED_COMPONENTS])
{
	const struct rh_free_slot_component_seal *partial[
		RH_FREE_SLOT_REQUIRED_COMPONENTS];
	size_t omitted, i, count, refusals = 0;

	for (omitted = 1; omitted < RH_FREE_SLOT_COMPONENT_COUNT; omitted++) {
		struct rh_free_slot_authority *unexpected = NULL;

		count = 0;
		for (i = 0; i < RH_FREE_SLOT_REQUIRED_COMPONENTS; i++)
			if (rh_free_slot_component_seal_kind(complete[i]) != omitted)
				partial[count++] = complete[i];
		if (!rh_free_slot_authority_create(writer, raw, bitmap,
				namespace_census, raw->generation, record, sequence, partial,
				count, &unexpected) || unexpected) {
			rh_free_slot_authority_destroy(unexpected);
			return -1;
		}
		refusals++;
	}
	return refusals == RH_FREE_SLOT_REQUIRED_COMPONENTS ? 0 : -1;
}

static int referenced_component_negatives(struct rh_writer *writer,
		const struct rh_raw_mft_census *raw,
		const struct rh_mft_bitmap_census *bitmap,
		const struct rh_namespace_census *namespace_census, uint64_t record,
		uint16_t sequence,
		const struct rh_free_slot_component_seal *const complete[
			RH_FREE_SLOT_REQUIRED_COMPONENTS])
{
	struct rh_free_slot_reference reference;
	unsigned char hash[32];
	size_t kind, i, refusals = 0;

	reference.record = record;
	reference.sequence = sequence;
	for (kind = RH_FREE_SLOT_COMPONENT_NATIVE_OPEN_ATTRIBUTE;
			kind <= RH_FREE_SLOT_COMPONENT_USN_FIXED_SYSTEM; kind++) {
		if (kind == RH_FREE_SLOT_COMPONENT_WAL_EXCLUSIONS)
			continue;
		struct rh_free_slot_component_seal *referencing = NULL;
		struct rh_free_slot_authority *unexpected = NULL;
		const struct rh_free_slot_component_seal *candidate[
			RH_FREE_SLOT_REQUIRED_COMPONENTS];

		source_hash((enum rh_free_slot_component_kind)kind, 1U, hash);
		if (rh_free_slot_test_component_seal_create(
				(enum rh_free_slot_component_kind)kind, raw->generation,
				1U, 1U, hash, &reference, 1U, NULL, 0U, &referencing))
			return -1;
		for (i = 0; i < RH_FREE_SLOT_REQUIRED_COMPONENTS; i++)
			candidate[i] = rh_free_slot_component_seal_kind(complete[i]) ==
				kind ? referencing : complete[i];
		if (!rh_free_slot_authority_create(writer, raw, bitmap,
				namespace_census, raw->generation, record, sequence, candidate,
				RH_FREE_SLOT_REQUIRED_COMPONENTS, &unexpected) || unexpected) {
			rh_free_slot_authority_destroy(unexpected);
			rh_free_slot_component_seal_destroy(referencing);
			return -1;
		}
		rh_free_slot_component_seal_destroy(referencing);
		refusals++;
	}
	return refusals == 7U ? 0 : -1;
}

static int wal_overlap_negative(struct rh_writer *writer,
		const struct rh_raw_mft_census *raw,
		const struct rh_mft_bitmap_census *bitmap,
		const struct rh_namespace_census *namespace_census, uint64_t record,
		uint16_t sequence, uint64_t target_physical,
		const struct rh_free_slot_range *original_range,
		const struct rh_free_slot_component_seal *const complete[
			RH_FREE_SLOT_REQUIRED_COMPONENTS])
{
	struct rh_free_slot_range ranges[2];
	struct rh_free_slot_component_seal *overlap_seal = NULL;
	struct rh_free_slot_authority *unexpected = NULL;
	const struct rh_free_slot_component_seal *candidate[
		RH_FREE_SLOT_REQUIRED_COMPONENTS];
	unsigned char hash[32];
	size_t i, checkpoint = writer->excluded_count;
	int result = -1;

	ranges[0] = *original_range;
	ranges[1].offset = target_physical;
	ranges[1].length = RH_FREE_SLOT_RAW_RECORD_SIZE;
	if (rh_writer_exclude(writer, ranges[1].offset, ranges[1].length))
		return -1;
	source_hash(RH_FREE_SLOT_COMPONENT_WAL_EXCLUSIONS, 1U, hash);
	if (rh_free_slot_test_component_seal_create(
			RH_FREE_SLOT_COMPONENT_WAL_EXCLUSIONS, raw->generation, 2U, 2U,
			hash, NULL, 0U, ranges, 2U, &overlap_seal))
		goto out;
	for (i = 0; i < RH_FREE_SLOT_REQUIRED_COMPONENTS; i++)
		candidate[i] = rh_free_slot_component_seal_kind(complete[i]) ==
			RH_FREE_SLOT_COMPONENT_WAL_EXCLUSIONS ? overlap_seal : complete[i];
	if (rh_free_slot_authority_create(writer, raw, bitmap, namespace_census,
			raw->generation, record, sequence, candidate,
			RH_FREE_SLOT_REQUIRED_COMPONENTS, &unexpected) && !unexpected)
		result = 0;
out:
	rh_free_slot_authority_destroy(unexpected);
	rh_free_slot_component_seal_destroy(overlap_seal);
	if (rh_writer_restore_restrictions(writer, checkpoint,
			writer->raw_wal_allowed_count))
		result = -1;
	return result;
}

static int wal_raw_escape_negative(struct rh_writer *writer,
		const struct rh_raw_mft_census *raw,
		const struct rh_mft_bitmap_census *bitmap,
		const struct rh_namespace_census *namespace_census, uint64_t record,
		uint16_t sequence, uint64_t target_physical,
		const struct rh_free_slot_component_seal *const complete[
			RH_FREE_SLOT_REQUIRED_COMPONENTS])
{
	struct rh_free_slot_authority *unexpected = NULL;
	size_t excluded_checkpoint = writer->excluded_count;
	size_t raw_checkpoint = writer->raw_wal_allowed_count;
	int result = -1;

	if (rh_writer_allow_raw_wal(writer, target_physical, 1U))
		return -1;
	if (rh_free_slot_authority_create(writer, raw, bitmap, namespace_census,
			raw->generation, record, sequence, complete,
			RH_FREE_SLOT_REQUIRED_COMPONENTS, &unexpected) && !unexpected)
		result = 0;
	rh_free_slot_authority_destroy(unexpected);
	if (rh_writer_restore_restrictions(writer, excluded_checkpoint,
			raw_checkpoint))
		result = -1;
	return result;
}

int main(int argc, char **argv)
{
	struct rh_writer writer;
	struct rh_raw_mft_census raw, raw_recovery;
	struct rh_mft_bitmap_census bitmap, bitmap_recovery, bitmap_bad;
	struct rh_namespace_census namespace_census, namespace_recovery;
	struct rh_free_slot_component_seal *seals[
		RH_FREE_SLOT_COMPONENT_COUNT] = {0};
	struct rh_free_slot_component_seal *recovery_seals[
		RH_FREE_SLOT_COMPONENT_COUNT] = {0};
	struct rh_free_slot_component_seal *altered_recovery = NULL;
	const struct rh_free_slot_component_seal *components[
		RH_FREE_SLOT_REQUIRED_COMPONENTS] = {0};
	const struct rh_free_slot_component_seal *recovery_components[
		RH_FREE_SLOT_REQUIRED_COMPONENTS] = {0};
	struct rh_free_slot_authority *authority = NULL, *second_authority = NULL;
	struct rh_free_slot_authority *recovered = NULL;
	struct rh_free_slot_authority_view view, second_view, recovered_view;
	struct rh_free_slot_range wal_range;
	struct rh_raw_mft_ref mft_owner;
	unsigned char before[RH_FREE_SLOT_RAW_RECORD_SIZE], before_hash[32];
	unsigned char zero_hash[32] = {0}, valid_hash[32];
	unsigned char *bad_observed = NULL;
	uint64_t opaque_records[2] = { FILE_first_user + 1U, FILE_first_user };
	uint64_t record, second_record, physical;
	uint16_t sequence;
	ntfs_volume *volume = NULL;
	int equal = 0, mounted = 0, result = 1;

	if (argc != 2)
		return 5;
	memset(&raw, 0, sizeof(raw));
	memset(&raw_recovery, 0, sizeof(raw_recovery));
	memset(&bitmap, 0, sizeof(bitmap));
	memset(&bitmap_recovery, 0, sizeof(bitmap_recovery));
	memset(&namespace_census, 0, sizeof(namespace_census));
	memset(&namespace_recovery, 0, sizeof(namespace_recovery));
	if (rh_writer_open(&writer, argv[1]))
		return 2;
	volume = ntfs_mount(argv[1], NTFS_MNT_RDONLY | NTFS_MNT_FORENSIC |
		NTFS_MNT_FS_NO_REPAIR);
	if (!volume || !NDevReadOnly(volume->dev))
		goto out;
	mounted = 1;
	{
		struct rh_raw_mft_census rejected;
		struct rh_writer dirty_writer = writer;
		uint64_t duplicate[2] = { FILE_first_user, FILE_first_user };
		uint64_t outside = UINT64_MAX;

		memset(&rejected, 0, sizeof(rejected));
		dirty_writer.operation_count = 1U;
		dirty_writer.planned_bytes = 1U;
		if (!rh_raw_mft_census_run_with_opaque_slots(volume, &dirty_writer,
				1U, opaque_records, 2U, &rejected)) {
			rh_raw_mft_census_release(&rejected);
			goto out;
		}
		if (!rh_raw_mft_census_run_with_opaque_slots(volume, &writer, 1U,
				duplicate, 2U, &rejected)) {
			rh_raw_mft_census_release(&rejected);
			goto out;
		}
		if (!rh_raw_mft_census_run_with_opaque_slots(volume, &writer, 1U,
				&outside, 1U, &rejected)) {
			rh_raw_mft_census_release(&rejected);
			goto out;
		}
	}
	if (rh_raw_mft_census_run_with_opaque_slots(volume, &writer, 1U,
			opaque_records, 2U, &raw) ||
			rh_mft_bitmap_census_run_from_raw(volume, &writer, 1U,
				RH_MFT_BITMAP_NO_ROOTHEALTH, 0U, &raw, &bitmap) ||
			rh_namespace_census_run(&raw, 1U, &namespace_census) ||
			rh_namespace_i30_census_run(volume, &writer, &raw,
				&namespace_census))
		goto out;
	if (raw.opaque_slot_count != 2U || !raw.opaque_slots_complete ||
			raw.opaque_slots[0].record != FILE_first_user ||
			raw.opaque_slots[1].record != FILE_first_user + 1U)
		goto out;
	record = raw.opaque_slots[0].record;
	second_record = raw.opaque_slots[1].record;
	sequence = 1U;
	if (writer.device_size < 512U)
		goto out;
	wal_range.offset = writer.device_size - 512U;
	wal_range.length = 512U;
	if (rh_writer_exclude(&writer,
			wal_range.offset, wal_range.length) ||
			rh_writer_allow_raw_wal(&writer,
				wal_range.offset, wal_range.length) ||
			build_components(1U, &wal_range, 1U, seals, components) ||
			rh_free_slot_authority_create(&writer, &raw, &bitmap,
				&namespace_census, 1U, record, sequence, components,
				RH_FREE_SLOT_REQUIRED_COMPONENTS, &authority) ||
			rh_free_slot_authority_get_view(authority, &view) ||
			rh_free_slot_authority_create(&writer, &raw, &bitmap,
				&namespace_census, 1U, second_record, 2U, components,
				RH_FREE_SLOT_REQUIRED_COMPONENTS, &second_authority) ||
			rh_free_slot_authority_get_view(second_authority, &second_view))
		goto out;
	mft_owner.record = FILE_MFT;
	mft_owner.sequence = raw.slots[FILE_MFT].sequence;
	if (rh_raw_mft_map_stream_range(&raw, mft_owner,
			le32_to_cpu(AT_DATA), NULL, 0U,
			record * RH_FREE_SLOT_RAW_RECORD_SIZE,
			RH_FREE_SLOT_RAW_RECORD_SIZE, &physical) ||
			physical != view.physical_offset ||
			rh_writer_staged_read(&writer, 0U, physical, sizeof(before), before))
		goto out;
	rh_sha256(before, sizeof(before), before_hash);
	if (view.version != RH_FREE_SLOT_AUTHORITY_VERSION ||
			view.correlation_generation != 1U || view.target_record != record ||
			view.intended_sequence != sequence ||
			view.physical_length != RH_FREE_SLOT_RAW_RECORD_SIZE ||
			memcmp(view.raw_before_hash, before_hash, 32U) ||
			view.references_matched || view.extent_references_matched ||
			view.allocation_owners_matched || view.owned_runs_matched ||
			view.wal_overlaps_matched || view.wal_ranges_examined != 1U ||
			view.wal_raw_ranges_examined != 1U ||
			second_view.target_record != second_record ||
			second_view.intended_sequence != 2U ||
			(view.observed_bitmap_byte & view.bitmap_mask) ||
			(view.expected_bitmap_byte & view.bitmap_mask) ||
			writer.write_boundaries ||
			omitted_component_negatives(&writer, &raw, &bitmap,
				&namespace_census, record, sequence, components) ||
			referenced_component_negatives(&writer, &raw, &bitmap,
				&namespace_census, record, sequence, components) ||
			wal_overlap_negative(&writer, &raw, &bitmap, &namespace_census,
				record, sequence, physical, &wal_range, components) ||
			wal_raw_escape_negative(&writer, &raw, &bitmap,
				&namespace_census, record, sequence, physical, components))
		goto out;
	{
		struct rh_free_slot_authority *unexpected = NULL;

		if (!rh_free_slot_authority_create(&writer, &raw, &bitmap,
				&namespace_census, 1U, FILE_MFT, sequence, components,
				RH_FREE_SLOT_REQUIRED_COMPONENTS, &unexpected) || unexpected) {
			rh_free_slot_authority_destroy(unexpected);
			goto out;
		}
	}
	/* Source constructors reject unknown/incomplete evidence directly. */
	source_hash(RH_FREE_SLOT_COMPONENT_REPARSE, 0U, valid_hash);
	{
		struct rh_free_slot_component_seal *unexpected = NULL;
		if (!rh_free_slot_test_component_seal_create(
				RH_FREE_SLOT_COMPONENT_REPARSE, 1U, 1U, 0U, valid_hash,
				NULL, 0U, NULL, 0U, &unexpected) || unexpected) {
			rh_free_slot_component_seal_destroy(unexpected);
			goto out;
		}
		if (!rh_free_slot_test_component_seal_create(
				RH_FREE_SLOT_COMPONENT_REPARSE, 1U, 0U, 0U, zero_hash,
				NULL, 0U, NULL, 0U, &unexpected) || unexpected) {
			rh_free_slot_component_seal_destroy(unexpected);
			goto out;
		}
	}
	bitmap_bad = bitmap;
	bad_observed = malloc(bitmap.bitmap_bytes);
	if (!bad_observed)
		goto out;
	memcpy(bad_observed, bitmap.observed_bitmap, bitmap.bitmap_bytes);
	bad_observed[record >> 3] |= (unsigned char)(1U << (record & 7U));
	bitmap_bad.observed_bitmap = bad_observed;
	{
		struct rh_free_slot_authority *unexpected = NULL;
		if (!rh_free_slot_authority_create(&writer, &raw, &bitmap_bad,
				&namespace_census, 1U, record, sequence, components,
				RH_FREE_SLOT_REQUIRED_COMPONENTS, &unexpected) || unexpected) {
			rh_free_slot_authority_destroy(unexpected);
			goto out;
		}
	}
	/* Recovery reruns every source census at checkpoint zero.  Only the
	 * correlation generation changes; canonical evidence remains identical. */
	if (rh_raw_mft_census_run_with_opaque_slots(volume, &writer, 99U,
			opaque_records, 2U, &raw_recovery) ||
			rh_mft_bitmap_census_run_from_raw(volume, &writer, 99U,
				RH_MFT_BITMAP_NO_ROOTHEALTH, 0U, &raw_recovery,
				&bitmap_recovery) ||
			rh_namespace_census_run(&raw_recovery, 99U,
				&namespace_recovery) ||
			rh_namespace_i30_census_run(volume, &writer, &raw_recovery,
				&namespace_recovery) ||
			build_components(99U, &wal_range, 1U, recovery_seals,
			recovery_components) ||
			rh_free_slot_authority_create(&writer, &raw_recovery,
				&bitmap_recovery, &namespace_recovery, 99U, record, sequence,
				recovery_components, RH_FREE_SLOT_REQUIRED_COMPONENTS,
				&recovered) || !rh_free_slot_authority_equal(authority, recovered) ||
			rh_free_slot_authority_get_view(recovered, &recovered_view) ||
			recovered_view.correlation_generation != 99U ||
			memcmp(view.evidence_hash, recovered_view.evidence_hash, 32U) ||
			rh_free_slot_authority_rederive_equal(authority, &writer,
				&raw_recovery, &bitmap_recovery, &namespace_recovery, 99U,
				record, sequence, recovery_components,
				RH_FREE_SLOT_REQUIRED_COMPONENTS, &equal) || !equal ||
			rh_free_slot_authority_rederive_evidence_equal(view.evidence_hash,
				&writer, &raw_recovery, &bitmap_recovery,
				&namespace_recovery, 99U, record, sequence,
				recovery_components, RH_FREE_SLOT_REQUIRED_COMPONENTS,
				&equal) || !equal)
		goto out;
	{
		const struct rh_free_slot_component_seal *altered_components[
			RH_FREE_SLOT_REQUIRED_COMPONENTS];
		size_t i;

		source_hash(RH_FREE_SLOT_COMPONENT_RECOVERY_NAMESPACE, 2U,
			valid_hash);
		if (rh_free_slot_test_component_seal_create(
				RH_FREE_SLOT_COMPONENT_RECOVERY_NAMESPACE, 99U, 0U, 0U,
				valid_hash, NULL, 0U, NULL, 0U, &altered_recovery))
			goto out;
		for (i = 0; i < RH_FREE_SLOT_REQUIRED_COMPONENTS; i++)
			altered_components[i] = rh_free_slot_component_seal_kind(
				recovery_components[i]) ==
				RH_FREE_SLOT_COMPONENT_RECOVERY_NAMESPACE ?
				altered_recovery : recovery_components[i];
		if (rh_free_slot_authority_rederive_evidence_equal(view.evidence_hash,
				&writer, &raw_recovery, &bitmap_recovery,
				&namespace_recovery, 99U, record, sequence,
				altered_components, RH_FREE_SLOT_REQUIRED_COMPONENTS,
				&equal) || equal)
			goto out;
	}
	printf("free-slot-authority record=%llu sequence=%u raw-before=exact-1024 "
		"opaque-targets=2 second-record=%llu physical=%llu second-physical=%llu "
		"bitmap-clear=1 references=%llu matched=0 extents=0 owned-runs=0 "
		"components=%zu omission-refusals=8 reference-refusals=7 "
		"wal-raw-ranges=1 wal-overlap-refused=1 "
		"wal-raw-escape-refused=1 system-slot-refused=1 "
		"recovery-generation=99 rederive-equal=1 "
		"writes=0\n", (unsigned long long)record, sequence,
		(unsigned long long)second_record,
		(unsigned long long)view.physical_offset,
		(unsigned long long)second_view.physical_offset,
		(unsigned long long)view.total_references_examined,
		RH_FREE_SLOT_REQUIRED_COMPONENTS);
	result = 0;
out:
	free(bad_observed);
	rh_free_slot_component_seal_destroy(altered_recovery);
	rh_free_slot_authority_destroy(recovered);
	rh_free_slot_authority_destroy(second_authority);
	rh_free_slot_authority_destroy(authority);
	destroy_components(recovery_seals);
	destroy_components(seals);
	rh_namespace_census_release(&namespace_census);
	rh_namespace_census_release(&namespace_recovery);
	rh_mft_bitmap_census_destroy(&bitmap);
	rh_mft_bitmap_census_destroy(&bitmap_recovery);
	rh_raw_mft_census_release(&raw);
	rh_raw_mft_census_release(&raw_recovery);
	if (mounted && ntfs_umount(volume, FALSE) && !result)
		result = 1;
	rh_writer_close(&writer);
	return result;
}
