/* ROOTHEALTH_REPAIR_ROLE(DIAGNOSTIC) */
#include "config.h"

#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#include "layout.h"
#include "roothealth_census_device.h"
#include "roothealth_complete_census.h"
#include "roothealth_free_slot_authority.h"
#include "roothealth_hash_stream.h"
#include "roothealth_native_authority.h"
#include "roothealth_recovery_namespace_authority.h"
#include "roothealth_system_indexes.h"
#include "roothealth_usn_fixed_system_authority.h"
#include "roothealth_write.h"

#define ROOTHEALTH_WAL_TEST_HOOKS 1
#include "roothealth_wal.h"

static struct rh_complete_census_profile profile;
static struct rh_complete_census planning;
static struct rh_complete_census recovery;
static struct rh_free_slot_component_seal *planning_recovery_ns_seal;
static struct rh_recovery_namespace_authority_view planning_recovery_ns_view;
static unsigned char planning_recovery_ns_hash[32];
static struct rh_system_index_census_view planning_system_index_view;
static struct rh_free_slot_component_seal *planning_reparse_seal;
static struct rh_free_slot_component_seal *planning_objid_seal;
static unsigned char planning_reparse_hash[32];
static unsigned char planning_objid_hash[32];
static struct rh_free_slot_component_seal *planning_usn_fixed_seal;
static struct rh_usn_fixed_system_authority_view planning_usn_fixed_view;
static unsigned char planning_usn_fixed_hash[32];
static struct rh_free_slot_authority *planning_slot_authority;
static struct rh_free_slot_authority_view planning_slot_authority_view;
static struct rh_wal *active_wal;
static uint64_t census_generation;
static int verifier_mode;
static unsigned int verifier_calls;

static int file_hash(int fd, uint64_t size, unsigned char output[32])
{
	struct rh_hash_stream hash;
	unsigned char bytes[65536];
	uint64_t offset = 0;

	rh_hash_stream_init(&hash);
	while (offset < size) {
		size_t part = sizeof(bytes);
		ssize_t got;

		if (part > size - offset)
			part = (size_t)(size - offset);
		got = pread(fd, bytes, part, (off_t)offset);
		if (got != (ssize_t)part || rh_hash_stream_update(&hash, bytes, part))
			return -1;
		offset += part;
	}
	return rh_hash_stream_final(&hash, output);
}

static void hex_digest(const unsigned char digest[32], char output[65])
{
	static const char hex[] = "0123456789abcdef";
	size_t i;

	for (i = 0; i < 32U; i++) {
		output[2U * i] = hex[digest[i] >> 4];
		output[2U * i + 1U] = hex[digest[i] & 15U];
	}
	output[64] = 0;
}

#define NATIVE_TABLE_HEADER 24U
#define NATIVE_ALLOCATED UINT32_C(0xffffffff)

static void native_wr16(unsigned char *bytes, uint16_t value)
{
	bytes[0] = (unsigned char)value;
	bytes[1] = (unsigned char)(value >> 8);
}

static void native_wr32(unsigned char *bytes, uint32_t value)
{
	native_wr16(bytes, (uint16_t)value);
	native_wr16(bytes + 2U, (uint16_t)(value >> 16));
}

static void native_wr64(unsigned char *bytes, uint64_t value)
{
	native_wr32(bytes, (uint32_t)value);
	native_wr32(bytes + 4U, (uint32_t)(value >> 32));
}

static void native_common(unsigned char *record, size_t size, uint64_t lsn,
		uint64_t previous_lsn, uint64_t undo_next_lsn, uint32_t transaction)
{
	memset(record, 0, size);
	native_wr64(record, lsn);
	native_wr64(record + 8U, previous_lsn);
	native_wr64(record + 16U, undo_next_lsn);
	native_wr32(record + 24U, (uint32_t)size - 48U);
	native_wr16(record + 28U, 1U);
	native_wr32(record + 32U, 1U);
	native_wr32(record + 36U, transaction);
}

static int native_build(uint64_t generation, uint64_t referenced_record,
		uint16_t referenced_sequence,
		struct rh_native_authority_census **census)
{
	unsigned char open_record[136], update[104], forget[88];
	struct rh_replay_geometry geometry = {
		.page_size = 4096, .cluster_size = 4096, .mft_record_size = 1024,
		.index_record_size = 4096, .logfile_size = 2U * 1024U * 1024U,
		.volume_clusters = 16383, .sequence_bits = 45,
		.client_sequence = 1, .client_index = 0
	};
	struct rh_replay_analysis_record records[] = {
		{ .bytes = open_record, .size = sizeof(open_record) },
		{ .bytes = update, .size = sizeof(update) },
		{ .bytes = forget, .size = sizeof(forget) }
	};

	native_common(open_record, sizeof(open_record), 100U, 0U, 0U, 64U);
	native_wr16(open_record + 48U, 28U);
	native_wr16(open_record + 52U, 0x28U);
	native_wr16(open_record + 54U, 44U);
	native_wr16(open_record + 56U, 0x58U);
	native_wr16(open_record + 58U, 2U);
	native_wr16(open_record + 60U, NATIVE_TABLE_HEADER);
	native_wr32(open_record + 80U, NATIVE_ALLOCATED);
	native_wr64(open_record + 88U,
		((uint64_t)referenced_sequence << 48) | referenced_record);
	native_wr64(open_record + 96U, 90U);
	open_record[105U] = 1U;
	open_record[112U] = 1U;
	native_wr32(open_record + 108U, 0x80U);
	native_wr16(open_record + 128U, 'N');

	native_common(update, sizeof(update), 200U, 100U, 100U, 64U);
	native_wr16(update + 40U, 2U);
	native_wr16(update + 48U, 7U);
	native_wr16(update + 50U, 7U);
	native_wr16(update + 52U, 0x28U);
	native_wr16(update + 54U, 2U);
	native_wr16(update + 56U, 0x30U);
	native_wr16(update + 58U, 2U);
	native_wr16(update + 60U, NATIVE_TABLE_HEADER);
	native_wr16(update + 62U, 1U);
	native_wr16(update + 64U, 360U);
	native_wr16(update + 66U, 24U);
	native_wr16(update + 68U, 6U);
	native_wr16(update + 70U, 2U);
	native_wr64(update + 80U, 4U);
	update[88U] = 'S';
	update[96U] = 'R';

	native_common(forget, sizeof(forget), 300U, 200U, 200U, 64U);
	native_wr16(forget + 48U, 27U);
	return rh_replay_analysis_plan_native(records,
		sizeof(records) / sizeof(records[0]), &geometry, 100U, 300U,
		generation, NULL, census);
}

static int recovery_namespace_build(const struct rh_complete_census *complete,
		struct rh_free_slot_component_seal **seal,
		struct rh_recovery_namespace_authority_view *view,
		unsigned char hash[32])
{
	*seal = NULL;
	return rh_complete_census_recovery_namespace_get_view(complete, view) ||
		rh_complete_census_recovery_namespace_component_seal_create(complete,
			seal) ||
		rh_free_slot_component_seal_hash(*seal, hash);
}

static int recovery_namespace_views_equal(
		const struct rh_recovery_namespace_authority_view *left,
		const struct rh_recovery_namespace_authority_view *right)
{
	return left->version == right->version &&
		left->raw_file_name_links == right->raw_file_name_links &&
		left->namespace_links == right->namespace_links &&
		left->i30_edges == right->i30_edges &&
		left->recovery_anchor_state == right->recovery_anchor_state &&
		left->recovery_anchor_components_completed ==
			right->recovery_anchor_components_completed &&
		left->recovery_anchor_reference_occurrences ==
			right->recovery_anchor_reference_occurrences &&
		left->reference_occurrences_expected ==
			right->reference_occurrences_expected &&
		left->reference_occurrences_completed ==
			right->reference_occurrences_completed &&
		left->unique_references == right->unique_references &&
		!memcmp(left->recovery_anchor_hash, right->recovery_anchor_hash, 32U) &&
		!memcmp(left->source_census_hash, right->source_census_hash, 32U);
}

static int usn_fixed_build(const struct rh_complete_census *complete,
		struct rh_free_slot_component_seal **seal,
		struct rh_usn_fixed_system_authority_view *view,
		unsigned char hash[32])
{
	*seal = NULL;
	return rh_complete_census_usn_fixed_system_get_view(complete, view) ||
		rh_complete_census_usn_fixed_system_component_seal_create(complete,
			seal) || rh_free_slot_component_seal_hash(*seal, hash);
}

static int system_index_build(const struct rh_complete_census *complete,
		struct rh_system_index_census_view *view,
		struct rh_free_slot_component_seal **reparse_seal,
		unsigned char reparse_hash[32],
		struct rh_free_slot_component_seal **objid_seal,
		unsigned char objid_hash[32])
{
	*reparse_seal = NULL;
	*objid_seal = NULL;
	return rh_complete_census_system_indexes_get_view(complete, view) ||
		rh_complete_census_reparse_component_seal_create(complete,
			reparse_seal) ||
		rh_free_slot_component_seal_hash(*reparse_seal, reparse_hash) ||
		rh_complete_census_objid_component_seal_create(complete,
			objid_seal) ||
		rh_free_slot_component_seal_hash(*objid_seal, objid_hash);
}

static int setup_wal_exclusions(struct rh_writer *writer, struct rh_wal *wal,
		struct rh_wal_observation *observation)
{
	static const unsigned char uuid[16] = {
		0x10, 0x32, 0x54, 0x76, 0x98, 0xba, 0x4c, 0xde,
		0x8f, 0x01, 0x23, 0x45, 0x67, 0x89, 0xab, 0xcd
	};
	uint64_t run_offset = 2U * RH_WAL_SIZE;
	uint64_t journal_offset;

	if (!writer || !wal || !observation ||
			writer->device_size < run_offset + RH_WAL_SIZE ||
			writer->device_size < 8192U)
		return -1;
	journal_offset = writer->device_size - 8192U;
	wal->writer = writer;
	wal->observation = observation;
	wal->sector_size = 512U;
	wal->volume_serial = profile.expected_volume_serial;
	wal->journal_record = 81U;
	wal->journal_sequence = 1U;
	wal->data_size = RH_WAL_SIZE;
	wal->journal_record_device_offset = journal_offset;
	wal->journal_record_device_length = 1024U;
	memcpy(wal->journal_uuid, uuid, sizeof(uuid));
	if (rh_wal_test_append_run(wal, 0U, run_offset, RH_WAL_SIZE) ||
			rh_writer_exclude(writer, run_offset, RH_WAL_SIZE) ||
			rh_writer_exclude(writer, journal_offset, 1024U) ||
			rh_writer_exclude(writer, writer->device_size - 512U, 512U) ||
			rh_writer_allow_raw_wal(writer, run_offset, RH_WAL_SIZE))
		return -1;
	observation->checked = 1;
	observation->present = 1;
	observation->valid = 1;
	observation->fast_path_trusted = 1;
	observation->write_safe = 1;
	observation->ownership_census_complete = 1;
	observation->max_entry_count = RH_WAL_MAX_ENTRIES;
	observation->volume_serial = wal->volume_serial;
	rh_uuid_format(wal->journal_uuid, observation->journal_uuid);
	return 0;
}

static void destroy_component_set(
		struct rh_free_slot_component_seal *seals[
			RH_FREE_SLOT_COMPONENT_COUNT])
{
	size_t i;

	for (i = 1U; i < RH_FREE_SLOT_COMPONENT_COUNT; i++) {
		rh_free_slot_component_seal_destroy(seals[i]);
		seals[i] = NULL;
	}
}

static int build_component_set(const struct rh_complete_census *complete,
		struct rh_native_authority_census *native, const struct rh_wal *wal,
		const struct rh_wal_preimage *preimage,
		uint64_t generation,
		struct rh_free_slot_component_seal *seals[
			RH_FREE_SLOT_COMPONENT_COUNT],
		const struct rh_free_slot_component_seal *ordered[
			RH_FREE_SLOT_REQUIRED_COMPONENTS])
{
	size_t i;

	memset(seals, 0, RH_FREE_SLOT_COMPONENT_COUNT * sizeof(*seals));
	if (rh_native_open_attribute_component_seal_create(native, &seals[1]) ||
			rh_native_target_component_seal_create(native, &seals[2]) ||
			rh_native_control_component_seal_create(native, &seals[3]) ||
			rh_complete_census_reparse_component_seal_create(complete,
				&seals[4]) ||
			rh_complete_census_objid_component_seal_create(complete,
				&seals[5]) ||
			rh_complete_census_recovery_namespace_component_seal_create(
				complete, &seals[6]) ||
			(preimage ? rh_wal_preimage_create_free_slot_exclusion_seal(
				preimage, generation, &seals[7]) :
				rh_wal_create_free_slot_exclusion_seal(wal, generation,
					&seals[7])) ||
			rh_complete_census_usn_fixed_system_component_seal_create(complete,
				&seals[8]))
		goto fail;
	for (i = 1U; i < RH_FREE_SLOT_COMPONENT_COUNT; i++) {
		if (rh_free_slot_component_seal_kind(seals[i]) !=
				(enum rh_free_slot_component_kind)i)
			goto fail;
		ordered[i - 1U] = seals[i];
	}
	return 0;
fail:
	destroy_component_set(seals);
	return -1;
}

static int usn_fixed_views_equal(
		const struct rh_usn_fixed_system_authority_view *left,
		const struct rh_usn_fixed_system_authority_view *right)
{
	return left->version == right->version &&
		left->fixed_roles_expected == right->fixed_roles_expected &&
		left->fixed_roles_completed == right->fixed_roles_completed &&
		left->fixed_roles_present == right->fixed_roles_present &&
		left->usn_records_expected == right->usn_records_expected &&
		left->usn_records_completed == right->usn_records_completed &&
		left->reference_fields_examined == right->reference_fields_examined &&
		left->unique_references == right->unique_references &&
		left->usn_state == right->usn_state &&
		left->usn_reference.record == right->usn_reference.record &&
		left->usn_reference.sequence == right->usn_reference.sequence &&
		left->present_role_mask == right->present_role_mask &&
		left->absent_role_mask == right->absent_role_mask &&
		!memcmp(left->evidence_hash, right->evidence_hash, 32U);
}

static int usn_fixed_identity_equal(
		const struct rh_usn_fixed_system_authority_view *left,
		const struct rh_usn_fixed_system_authority_view *right)
{
	return left->version == right->version &&
		left->correlation_generation == right->correlation_generation &&
		left->fixed_roles_expected == right->fixed_roles_expected &&
		left->fixed_roles_completed == right->fixed_roles_completed &&
		left->fixed_roles_present == right->fixed_roles_present &&
		left->usn_records_expected == right->usn_records_expected &&
		left->usn_records_completed == right->usn_records_completed &&
		left->reference_fields_examined == right->reference_fields_examined &&
		left->unique_references == right->unique_references &&
		left->usn_state == right->usn_state &&
		left->usn_reference.record == right->usn_reference.record &&
		left->usn_reference.sequence == right->usn_reference.sequence &&
		left->present_role_mask == right->present_role_mask &&
		left->absent_role_mask == right->absent_role_mask &&
		left->complete == right->complete &&
		!memcmp(left->attrdef_payload_hash, right->attrdef_payload_hash, 32U) &&
		!memcmp(left->upcase_payload_hash, right->upcase_payload_hash, 32U) &&
		!memcmp(left->role_manifest_hash, right->role_manifest_hash, 32U) &&
		!memcmp(left->reference_manifest_hash,
			right->reference_manifest_hash, 32U);
}

static int census_verifier(
		const struct rh_wal_action_verifier_context *context)
{
	struct rh_census_reader reader;
	struct rh_free_slot_component_seal *recovery_ns_seal = NULL;
	struct rh_recovery_namespace_authority_view recovery_ns_view;
	struct rh_system_index_census_view recovery_system_index_view;
	struct rh_free_slot_component_seal *recovery_reparse_seal = NULL;
	struct rh_free_slot_component_seal *recovery_objid_seal = NULL;
	struct rh_free_slot_component_seal *recovery_usn_fixed_seal = NULL;
	struct rh_native_authority_census *recovery_native = NULL;
	struct rh_free_slot_component_seal *authority_seals[
		RH_FREE_SLOT_COMPONENT_COUNT] = {0};
	const struct rh_free_slot_component_seal *authority_components[
		RH_FREE_SLOT_REQUIRED_COMPONENTS] = {0};
	struct rh_usn_fixed_system_authority_view recovery_usn_fixed_view;
	unsigned char recovery_ns_hash[32];
	unsigned char recovery_reparse_hash[32];
	unsigned char recovery_objid_hash[32];
	unsigned char recovery_usn_fixed_hash[32];
	int authority_equal = 0;
	int result = -1, stage = 0;

	if (!context || context->action_id !=
			RH_WRITE_ACTION_ID(RH_WRITE_BITMAP_MFT) ||
			context->transaction_kind != RH_WAL_TX_METADATA_REPAIR ||
			context->state != RH_WAL_APPLYING || context->entry_count != 1U ||
			rh_census_reader_from_wal_preimage(context->preimage, &reader))
		return -1;
	stage = 1;
	rh_complete_census_release(&recovery);
	if (rh_complete_census_run(&reader, &profile, census_generation,
			&recovery) || recovery_namespace_build(&recovery,
			&recovery_ns_seal, &recovery_ns_view, recovery_ns_hash) ||
			system_index_build(&recovery, &recovery_system_index_view,
				&recovery_reparse_seal, recovery_reparse_hash,
				&recovery_objid_seal, recovery_objid_hash) ||
			usn_fixed_build(&recovery, &recovery_usn_fixed_seal,
				&recovery_usn_fixed_view, recovery_usn_fixed_hash))
		goto out;
	stage = 2;
	verifier_calls++;
	if (!recovery_namespace_views_equal(&planning_recovery_ns_view,
			&recovery_ns_view) || memcmp(planning_recovery_ns_hash,
			recovery_ns_hash, sizeof(recovery_ns_hash)))
		goto out;
	stage = 3;
	if (memcmp(planning_system_index_view.census_hash,
			recovery_system_index_view.census_hash, 32U) ||
			memcmp(planning_reparse_hash, recovery_reparse_hash, 32U) ||
			memcmp(planning_objid_hash, recovery_objid_hash, 32U))
		goto out;
	stage = 4;
	if (!active_wal || recovery.raw.slot_count <= 18U ||
			native_build(census_generation, 18U,
				recovery.raw.slots[18U].sequence, &recovery_native) ||
			build_component_set(&recovery, recovery_native, active_wal,
				context->preimage,
				census_generation, authority_seals, authority_components))
		goto out;
	if (verifier_mode == 1) {
		if (rh_free_slot_authority_rederive_evidence_equal_reader(
				planning_slot_authority_view.evidence_hash, &reader,
				&recovery.raw, &recovery.mft_bitmap,
				&recovery.namespace_census, census_generation, 16U, 1U,
				authority_components, RH_FREE_SLOT_REQUIRED_COMPONENTS,
				&authority_equal) || !authority_equal)
			goto out;
	} else {
		errno = 0;
		if (!rh_free_slot_authority_rederive_evidence_equal_reader(
				planning_slot_authority_view.evidence_hash, &reader,
				&recovery.raw, &recovery.mft_bitmap,
				&recovery.namespace_census, census_generation, 16U, 1U,
				authority_components, RH_FREE_SLOT_REQUIRED_COMPONENTS,
				&authority_equal) || authority_equal)
			goto out;
	}
	stage = 5;
	if (verifier_mode == 1) {
		result = usn_fixed_views_equal(&planning_usn_fixed_view,
			&recovery_usn_fixed_view) &&
			!memcmp(planning_usn_fixed_hash, recovery_usn_fixed_hash,
				sizeof(recovery_usn_fixed_hash)) &&
			rh_complete_census_outputs_equal(&planning, &recovery) ? 0 : -1;
		goto out;
	}
	if (verifier_mode == 2 && usn_fixed_identity_equal(
			&planning_usn_fixed_view, &recovery_usn_fixed_view) &&
			!usn_fixed_views_equal(&planning_usn_fixed_view,
				&recovery_usn_fixed_view) && memcmp(planning_usn_fixed_hash,
				recovery_usn_fixed_hash, sizeof(recovery_usn_fixed_hash)) &&
			!rh_complete_census_outputs_equal(&planning, &recovery) &&
			recovery.mft_bitmap.change_count == 1U &&
			recovery.mft_bitmap.changes[0].clear_mask == 1U &&
			recovery.coverage.bitmaps.differences.known &&
			recovery.coverage.bitmaps.differences.value == 1U)
		result = 0;
	else
		errno = EINVAL;
out:
	if (result)
		fprintf(stderr, "complete-census verifier failed stage=%d mode=%d "
			"errno=%d equal=%d secure=%d/%d fixed=%02x/%02x "
			"coverage=%02x/%02x census=%02x/%02x\n", stage, verifier_mode,
			errno, authority_equal, planning.secure_provider != NULL,
			recovery.secure_provider != NULL,
			planning.fixed_metadata.evidence_hash[0],
			recovery.fixed_metadata.evidence_hash[0],
			planning.coverage_hash[0], recovery.coverage_hash[0],
			planning.census_hash[0], recovery.census_hash[0]);
	destroy_component_set(authority_seals);
	rh_native_authority_census_destroy(recovery_native);
	rh_free_slot_component_seal_destroy(recovery_usn_fixed_seal);
	rh_free_slot_component_seal_destroy(recovery_objid_seal);
	rh_free_slot_component_seal_destroy(recovery_reparse_seal);
	rh_free_slot_component_seal_destroy(recovery_ns_seal);
	return result;
}

static void fill_entry(struct rh_wal_recovery_entry_view *entry,
		struct rh_write_operation *operation, unsigned char *old_payload,
		unsigned char after, uint64_t physical, uint64_t logical,
		unsigned char mode)
{
	unsigned char empty_hash[32];

	memset(entry, 0, sizeof(*entry));
	memset(operation, 0, sizeof(*operation));
	entry->ordinal = 1U;
	entry->action_id = RH_WRITE_ACTION_ID(RH_WRITE_BITMAP_MFT);
	entry->target_offset = physical;
	entry->length = 1U;
	rh_sha256(old_payload, 1U, entry->old_hash);
	rh_sha256(&after, 1U, entry->new_hash);
	entry->target.seal_version = 1U;
	entry->target.object = RH_WRITE_TARGET_NONRESIDENT_ATTRIBUTE;
	entry->target.owner_mft_record = 0U;
	entry->target.owner_sequence = planning.mft_bitmap.mft_sequence;
	entry->target.attribute_instance =
		planning.mft_bitmap.bitmap_attribute_instance;
	entry->target.attribute_type = le32_to_cpu(AT_BITMAP);
	entry->target.flags = RH_WRITE_TARGET_NONRESIDENT | mode;
	rh_sha256("", 0, empty_hash);
	memcpy(entry->target.attribute_name_hash, empty_hash, 32U);
	entry->target.lowest_vcn = 0;
	entry->target.logical_vcn = (int64_t)(logical / 4096U);
	entry->target.logical_offset = logical;
	entry->target.logical_length = 1U;
	entry->target.semantic_target_offset = physical;
	entry->target.semantic_target_length = 1U;
	entry->target.lcn = (int64_t)(physical / 4096U);
	entry->target.evidence_version = 1U;
	entry->target.evidence_generation = census_generation;
	memset(entry->target.evidence_hash, 0x22,
		sizeof(entry->target.evidence_hash));
	memset(entry->target.staged_view_hash, 0x33,
		sizeof(entry->target.staged_view_hash));
	rh_sha256(old_payload, 1U, entry->target.semantic_before_hash);
	rh_sha256(&after, 1U, entry->target.semantic_after_hash);
	entry->target.finalized = 1;
	operation->offset = physical;
	operation->length = 1U;
	operation->after = old_payload;
}

static int dispatch_view(struct rh_writer *source, struct rh_wal *wal,
		uint64_t physical, uint64_t logical, unsigned char old,
		unsigned char after, unsigned char mode)
{
	struct rh_writer preimage = *source;
	struct rh_write_operation operation;
	struct rh_wal_recovery_entry_view entry;
	const unsigned char *payloads[1];

	fill_entry(&entry, &operation, &old, after, physical, logical, mode);
	preimage.write_fd = -1;
	preimage.operations = &operation;
	preimage.operation_count = 1U;
	preimage.operation_capacity = 1U;
	preimage.planned_bytes = 0;
	preimage.backend = NULL;
	preimage.backend_opaque = NULL;
	preimage.commit_started = 0;
	preimage.commit_completed = 0;
	payloads[0] = &old;
	wal->writer = &preimage;
	return rh_wal_test_dispatch_action_verifiers(wal, &preimage, &entry,
		payloads, 1U);
}

int main(int argc, char **argv)
{
	struct rh_writer writer;
	struct rh_census_reader reader;
	struct rh_wal wal;
	struct rh_wal_observation observation;
	struct rh_native_authority_census *planning_native = NULL;
	struct rh_free_slot_component_seal *authority_seals[
		RH_FREE_SLOT_COMPONENT_COUNT] = {0};
	const struct rh_free_slot_component_seal *authority_components[
		RH_FREE_SLOT_REQUIRED_COMPONENTS] = {0};
	struct rh_raw_mft_ref mft;
	struct stat status;
	unsigned char boot[512], before_file[32], after_file[32];
	unsigned char clean_byte, corrupt_byte;
	uint64_t opaque_records[2] = {16U, 17U};
	uint64_t physical, logical = 2U;
	char coverage_hex[65], census_hex[65], preimage_hex[65];
	char raw_hex[65], namespace_hex[65], index_hex[65], mft_hex[65];
	char cluster_hex[65], fixed_hex[65], recovery_namespace_hex[65];
	char reparse_hex[65], objid_hex[65], usn_fixed_hex[65];
	size_t i;
	int result = 1, stage = 0;
	int release_mode = argc == 3 && !strcmp(argv[2], "--release");

	memset(&writer, 0, sizeof(writer));
	memset(&planning, 0, sizeof(planning));
	memset(&recovery, 0, sizeof(recovery));
	memset(&wal, 0, sizeof(wal));
	memset(&observation, 0, sizeof(observation));
	if ((argc != 2 && !release_mode) || rh_writer_open(&writer, argv[1]) ||
			fstat(writer.read_fd, &status) || status.st_size <= 0 ||
			file_hash(writer.read_fd, writer.device_size, before_file) ||
			rh_census_reader_from_writer_prefix(&writer, 0, &reader) ||
			rh_census_reader_read_exact(&reader, 0, sizeof(boot), boot))
		goto out;
	stage = 1;
	census_generation = 17U;
	memset(&profile, 0, sizeof(profile));
	profile.expected_volume_serial = 0;
	for (i = 0; i < 8U; i++)
		profile.expected_volume_serial |= (uint64_t)boot[72U + i] << (8U * i);
	profile.roothealth_record = RH_MFT_BITMAP_NO_ROOTHEALTH;
	if (!release_mode) {
		profile.opaque_records = opaque_records;
		profile.opaque_record_count = 2U;
	}
	if (!profile.expected_volume_serial)
		goto out;
	if (rh_complete_census_run(&reader, &profile, census_generation,
			&planning)) {
		perror("complete-census initial run");
		goto out;
	}
	if (release_mode) {
		stage = 2;
		if (!planning.providers_complete || !planning.coverage.complete ||
				!planning.coverage.skipped.known ||
				planning.coverage.skipped.value ||
				!planning.compressed_provider ||
				!rh_coverage_is_clean(&planning.coverage) ||
				planning.coverage.fixed_system.check_count !=
					RH_COMPLETE_CENSUS_FIXED_CHECK_COUNT)
			goto out;
		for (i = 0; i < planning.coverage.fixed_system.check_count; i++)
			if (planning.fixed_checks[i].result != RH_FIXED_CHECK_PASS)
				goto out;
		if (file_hash(writer.read_fd, writer.device_size, after_file) ||
				memcmp(before_file, after_file, sizeof(before_file)))
			goto out;
		hex_digest(planning.coverage_hash, coverage_hex);
		hex_digest(planning.census_hash, census_hex);
		printf("complete-census release complete=1 providers=1 skipped=0 "
			"fixed=17 clean=1 coverage=%s census=%s source-writes=0\n",
			coverage_hex, census_hex);
		result = 0;
		goto out;
	}
	if (planning.coverage.complete ||
			planning.providers_complete || !planning.read_passes_complete ||
			!planning.coverage.skipped.known ||
			planning.coverage.skipped.value !=
				(planning.secure_provider ? 1U : 4U) ||
			rh_coverage_is_clean(&planning.coverage) ||
			planning.coverage.fixed_system.check_count !=
				RH_COMPLETE_CENSUS_FIXED_CHECK_COUNT) {
		fprintf(stderr, "initial coverage complete=%u providers=%u read=%u "
			"skipped=%llu secure=%u clean=%u checks=%zu\n",
			planning.coverage.complete, planning.providers_complete,
			planning.read_passes_complete,
			(unsigned long long)planning.coverage.skipped.value,
			planning.secure_provider != NULL,
			rh_coverage_is_clean(&planning.coverage),
			planning.coverage.fixed_system.check_count);
		goto out;
	}
	stage = 2;
	if (recovery_namespace_build(&planning,
			&planning_recovery_ns_seal, &planning_recovery_ns_view,
			planning_recovery_ns_hash) ||
			planning_recovery_ns_view.raw_file_name_links !=
				planning.raw.file_name_count ||
			planning_recovery_ns_view.namespace_links !=
				planning.namespace_census.link_count ||
			planning_recovery_ns_view.i30_edges !=
				planning.namespace_census.i30_edge_count ||
			planning_recovery_ns_view.reference_occurrences_expected !=
				planning.raw.file_name_count * 8U +
				planning_recovery_ns_view.
					recovery_anchor_reference_occurrences)
		goto out;
	stage = 3;
	if (system_index_build(&planning, &planning_system_index_view,
			&planning_reparse_seal, planning_reparse_hash,
			&planning_objid_seal, planning_objid_hash) ||
			!planning_system_index_view.complete ||
			!planning_system_index_view.reparse_authority_complete ||
			!planning_system_index_view.objid_authority_complete ||
			!planning_system_index_view.quota_authority_complete ||
			!planning_system_index_view.no_io_uncertainty)
		goto out;
	stage = 4;
	if (usn_fixed_build(&planning, &planning_usn_fixed_seal,
			&planning_usn_fixed_view, planning_usn_fixed_hash) ||
			planning_usn_fixed_view.fixed_roles_expected != 17U ||
			planning_usn_fixed_view.fixed_roles_completed != 17U ||
			planning_usn_fixed_view.fixed_roles_present != 15U ||
			planning_usn_fixed_view.usn_state != RH_FREE_SLOT_USN_ABSENT ||
			planning_usn_fixed_view.usn_reference.record ||
			planning_usn_fixed_view.usn_reference.sequence ||
			planning_usn_fixed_view.unique_references != 15U ||
			planning_usn_fixed_view.absent_role_mask !=
				((UINT32_C(1) << 3U) | (UINT32_C(1) << 4U)))
		goto out;
	stage = 5;
	{
		struct rh_complete_census invalid = planning;
		struct rh_recovery_namespace_authority_view refused;
		struct rh_system_index_census_view system_refused;
		struct rh_usn_fixed_system_authority_view fixed_refused;

		invalid.namespace_census.reciprocity_complete = 0;
		if (!rh_complete_census_recovery_namespace_get_view(&invalid,
				&refused)) {
			goto out;
		}
		invalid = planning;
		invalid.index_bitmap.change_count = 1U;
		if (!rh_complete_census_recovery_namespace_get_view(&invalid,
				&refused)) {
			goto out;
		}
		invalid = planning;
		invalid.raw.census_hash[0] ^= 1U;
		if (!rh_complete_census_usn_fixed_system_get_view(&invalid,
				&fixed_refused))
			goto out;
		invalid = planning;
		invalid.namespace_census.census_hash[0] ^= 1U;
		if (!rh_complete_census_system_indexes_get_view(&invalid,
				&system_refused))
			goto out;
		invalid = planning;
		invalid.mft_bitmap.census_hash[31] ^= 1U;
		if (!rh_complete_census_usn_fixed_system_get_view(&invalid,
				&fixed_refused))
			goto out;
	}
	for (i = 0; i < planning.coverage.fixed_system.check_count; i++) {
		int typed = i != 14U || planning.secure_provider;

		if (planning.fixed_checks[i].result != (typed ?
				RH_FIXED_CHECK_PASS : RH_FIXED_CHECK_SKIPPED))
			goto out;
	}
	stage = 6;
	if (planning.raw.slot_count <= 18U) {
		errno = ERANGE;
		perror("complete-census authority slot range");
		goto out;
	}
	if (setup_wal_exclusions(&writer, &wal, &observation)) {
		perror("complete-census WAL exclusions");
		goto out;
	}
	if (native_build(census_generation, 18U,
			planning.raw.slots[18U].sequence, &planning_native)) {
		perror("complete-census native authority");
		goto out;
	}
	if (build_component_set(&planning, planning_native, &wal, NULL,
			census_generation, authority_seals, authority_components)) {
		perror("complete-census component union");
		goto out;
	}
	if (rh_free_slot_authority_create(&writer, &planning.raw,
			&planning.mft_bitmap, &planning.namespace_census,
			census_generation, 16U, 1U, authority_components,
			RH_FREE_SLOT_REQUIRED_COMPONENTS, &planning_slot_authority)) {
		perror("complete-census planning slot authority");
		goto out;
	}
	if (rh_free_slot_authority_get_view(planning_slot_authority,
			&planning_slot_authority_view)) {
		perror("complete-census planning slot view");
		goto out;
	}
	active_wal = &wal;
	destroy_component_set(authority_seals);
	rh_native_authority_census_destroy(planning_native);
	planning_native = NULL;
	stage = 7;
	mft.record = 0U;
	mft.sequence = planning.raw.slots[0].sequence;
	if (!mft.sequence || rh_raw_mft_map_stream_range(&planning.raw, mft,
			le32_to_cpu(AT_BITMAP), NULL, 0, logical, 1U, &physical) ||
			rh_census_reader_read_exact(&reader, physical, 1U, &clean_byte) ||
			(clean_byte & 1U))
		goto out;
	corrupt_byte = clean_byte | 1U;
	wal.transaction_kind = RH_WAL_TX_METADATA_REPAIR;
	wal.state = RH_WAL_APPLYING;
	wal.generation = census_generation;
	wal.volume_serial = profile.expected_volume_serial;
	wal.journal_record = 81U;
	wal.journal_sequence = 1U;
	wal.writer = &writer;
	if (rh_wal_register_action_verifier(&wal,
			RH_WRITE_ACTION_ID(RH_WRITE_BITMAP_MFT), census_verifier))
		goto out;
	stage = 8;
	verifier_mode = 1;
	if (dispatch_view(&writer, &wal, physical, logical, clean_byte,
			corrupt_byte, RH_WRITE_TARGET_SET_ONLY) || verifier_calls != 1U)
		goto out;
	stage = 9;
	verifier_mode = 2;
	if (dispatch_view(&writer, &wal, physical, logical, corrupt_byte,
			clean_byte, RH_WRITE_TARGET_CLEAR_ONLY) || verifier_calls != 2U ||
			file_hash(writer.read_fd, writer.device_size, after_file) ||
			memcmp(before_file, after_file, sizeof(before_file)))
		goto out;
	hex_digest(planning.coverage_hash, coverage_hex);
	hex_digest(planning.census_hash, census_hex);
	hex_digest(recovery.census_hash, preimage_hex);
	hex_digest(planning.raw.census_hash, raw_hex);
	hex_digest(planning.namespace_census.census_hash, namespace_hex);
	hex_digest(planning.index_bitmap.census_hash, index_hex);
	hex_digest(planning.mft_bitmap.census_hash, mft_hex);
	hex_digest(planning.cluster_bitmap.census_hash, cluster_hex);
	hex_digest(planning.fixed_manifest_hash, fixed_hex);
	hex_digest(planning_recovery_ns_hash, recovery_namespace_hex);
	hex_digest(planning_reparse_hash, reparse_hex);
	hex_digest(planning_objid_hash, objid_hex);
	hex_digest(planning_usn_fixed_hash, usn_fixed_hex);
	printf("complete-census partial=1 skipped=%u fixed=17 planning-preimage="
		"byte-identical old-current-separated=1 mft-differences=%zu "
		"coverage=%s census=%s old-view=%s source-writes=0\n",
		RH_COMPLETE_CENSUS_PARTIAL_SKIPPED,
		recovery.mft_bitmap.change_count, coverage_hex, census_hex,
		preimage_hex);
	printf("complete-census families raw=%s namespace=%s index=%s mft=%s "
		"cluster=%s fixed=%s\n", raw_hex, namespace_hex, index_hex,
		mft_hex, cluster_hex, fixed_hex);
	printf("recovery-namespace raw-fn=%llu namespace=%llu i30=%llu "
		"anchor=%u/%llu occurrences=%llu unique=%llu "
		"planning-preimage=byte-identical "
		"seal=%s source-writes=0\n",
		(unsigned long long)planning_recovery_ns_view.raw_file_name_links,
		(unsigned long long)planning_recovery_ns_view.namespace_links,
		(unsigned long long)planning_recovery_ns_view.i30_edges,
		(unsigned int)planning_recovery_ns_view.recovery_anchor_state,
		(unsigned long long)
			planning_recovery_ns_view.recovery_anchor_components_completed,
		(unsigned long long)
			planning_recovery_ns_view.reference_occurrences_expected,
		(unsigned long long)planning_recovery_ns_view.unique_references,
		recovery_namespace_hex);
	printf("system-indexes entries=%llu end=%llu reparse=%zu objid=%zu "
		"quota=%zu planning-preimage=byte-identical reparse-seal=%s "
		"objid-seal=%s source-writes=0\n",
		(unsigned long long)planning_system_index_view.index_entries_examined,
		(unsigned long long)
			planning_system_index_view.index_end_entries_examined,
		planning_system_index_view.reparse_count,
		planning_system_index_view.objid_count,
		planning_system_index_view.quota_count, reparse_hex, objid_hex);
	printf("usn-fixed roles=%llu/%llu present=%llu usn=ABSENT "
		"references=%llu attrdef=pinned upcase=pinned "
		"planning-preimage=byte-identical seal=%s source-writes=0\n",
		(unsigned long long)planning_usn_fixed_view.fixed_roles_completed,
		(unsigned long long)planning_usn_fixed_view.fixed_roles_expected,
		(unsigned long long)planning_usn_fixed_view.fixed_roles_present,
		(unsigned long long)planning_usn_fixed_view.unique_references,
		usn_fixed_hex);
	result = 0;
out:
	if (result)
		fprintf(stderr, "complete-census failed stage=%d errno=%d\n",
			stage, errno);
	active_wal = NULL;
	destroy_component_set(authority_seals);
	rh_native_authority_census_destroy(planning_native);
	rh_free_slot_authority_destroy(planning_slot_authority);
	planning_slot_authority = NULL;
	free(wal.runs);
	wal.runs = NULL;
	rh_free_slot_component_seal_destroy(planning_usn_fixed_seal);
	rh_free_slot_component_seal_destroy(planning_objid_seal);
	rh_free_slot_component_seal_destroy(planning_reparse_seal);
	rh_free_slot_component_seal_destroy(planning_recovery_ns_seal);
	rh_complete_census_release(&recovery);
	rh_complete_census_release(&planning);
	rh_writer_close(&writer);
	return result;
}
