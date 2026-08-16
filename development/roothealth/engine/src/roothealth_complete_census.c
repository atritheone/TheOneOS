/* ROOTHEALTH_REPAIR_ROLE(DIAGNOSTIC) ROOTHEALTH_IO_ROLE(READER) */
#include "config.h"

#include <errno.h>
#include <limits.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
#include <stdio.h>
#endif

#include "roothealth_census_device.h"
#include "roothealth_compressed.h"
#include "roothealth_complete_census.h"
#include "roothealth_hash_stream.h"
#include "roothealth_recovery_namespace_authority.h"
#include "roothealth_recovery_namespace_authority_internal.h"
#include "roothealth_repair.h"
#include "roothealth_secure_census_provider.h"
#include "roothealth_system_indexes.h"
#include "roothealth_system_indexes_internal.h"
#include "roothealth_usn_fixed_system_authority.h"
#include "roothealth_usn_fixed_system_authority_internal.h"

static void rh_known(struct rh_coverage_counter *counter, uint64_t value)
{
	counter->known = true;
	counter->value = value;
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

static uint64_t rh_get_u64le(const unsigned char *bytes)
{
	uint64_t value = 0;
	unsigned int i;

	for (i = 0; i < 8U; i++)
		value |= (uint64_t)bytes[i] << (8U * i);
	return value;
}

static void rh_put_u16le(unsigned char bytes[2], uint16_t value)
{
	bytes[0] = (unsigned char)value;
	bytes[1] = (unsigned char)(value >> 8);
}

static void rh_put_u64le(unsigned char bytes[8], uint64_t value)
{
	unsigned int i;

	for (i = 0; i < 8U; i++)
		bytes[i] = (unsigned char)(value >> (8U * i));
}

static enum rh_fixed_check_result rh_fixed_reader_result(
		enum rh_fixed_metadata_reader_state state)
{
	if (state == RH_FIXED_METADATA_READER_PASS)
		return RH_FIXED_CHECK_PASS;
	if (state == RH_FIXED_METADATA_READER_FAIL)
		return RH_FIXED_CHECK_FAIL;
	if (state == RH_FIXED_METADATA_READER_IO)
		return RH_FIXED_CHECK_UNREADABLE;
	return RH_FIXED_CHECK_SKIPPED;
}

static unsigned int rh_count_bits(uint32_t value)
{
	unsigned int count = 0;

	while (value) {
		count += value & 1U;
		value >>= 1;
	}
	return count;
}

static void rh_core_fixed_set(struct rh_complete_census *census,
		size_t index, int valid, int io_error)
{
	uint32_t bit = UINT32_C(1) << index;

	census->core_fixed_checked_mask |= bit;
	if (valid)
		census->core_fixed_valid_mask |= bit;
	if (io_error)
		census->core_fixed_io_mask |= bit;
}

static int rh_core_fixed_census(const struct rh_census_reader *reader,
		struct rh_complete_census *census)
{
	static const size_t record_checks[4] = {11U, 12U, 10U, 16U};
	struct rh_usn_fixed_system_authority_view roles;
	struct rh_boot_geometry primary_geometry = {0}, backup_geometry = {0};
	struct rh_raw_mft_ref mft = {0, 1}, mirror = {1, 1};
	unsigned char primary_boot[ROOTHEALTH_SUPPORTED_SECTOR_SIZE];
	unsigned char backup_boot[ROOTHEALTH_SUPPORTED_SECTOR_SIZE];
	uint32_t required_mask = 0;
	uint64_t backup_offset;
	size_t i;

	if (!reader || !census || reader->device_size <
			2U * ROOTHEALTH_SUPPORTED_SECTOR_SIZE) {
		errno = EINVAL;
		return -1;
	}
	if (!census->usn_fixed_system_authority ||
			rh_complete_census_usn_fixed_system_get_view(census, &roles) ||
			!roles.complete)
		return 0;
	for (i = 6U; i <= 13U; i++)
		required_mask |= UINT32_C(1) << i;
	required_mask |= UINT32_C(1) << 16U;
	if ((roles.present_role_mask & required_mask) != required_mask)
		return 0;
	rh_core_fixed_set(census, 6U, census->raw.records_complete &&
		census->raw.extents_complete, 0);
	rh_core_fixed_set(census, 7U, census->cluster_bitmap.complete &&
		census->cluster_bitmap.structurally_valid &&
		census->cluster_bitmap.clean, 0);
	rh_core_fixed_set(census, 9U, census->namespace_census.graph_bounded &&
		census->namespace_census.reciprocity_complete &&
		census->index_bitmap.complete, 0);
	rh_core_fixed_set(census, 13U, census->namespace_census.graph_bounded &&
		census->namespace_census.reciprocity_complete &&
		census->index_bitmap.complete, 0);

	backup_offset = reader->device_size - ROOTHEALTH_SUPPORTED_SECTOR_SIZE;
	if (rh_census_reader_read_exact(reader, 0, sizeof(primary_boot),
			primary_boot) || rh_census_reader_read_exact(reader, backup_offset,
			sizeof(backup_boot), backup_boot)) {
		rh_core_fixed_set(census, 8U, 0, 1);
		return 0;
	}
	rh_core_fixed_set(census, 8U,
		roothealth_boot_sector_validate(primary_boot, sizeof(primary_boot),
			reader->device_size, &primary_geometry) &&
		roothealth_boot_sector_validate(backup_boot, sizeof(backup_boot),
			reader->device_size, &backup_geometry) &&
		!memcmp(&primary_geometry, &backup_geometry,
			sizeof(primary_geometry)) &&
		!memcmp(primary_boot, backup_boot, sizeof(primary_boot)) &&
		primary_geometry.serial == census->volume_serial, 0);
	if (!(census->core_fixed_valid_mask & (UINT32_C(1) << 8U)))
		return 0;

	for (i = 0; i < 4U; i++) {
		unsigned char primary[ROOTHEALTH_SUPPORTED_MFT_RECORD_SIZE];
		unsigned char peer[ROOTHEALTH_SUPPORTED_MFT_RECORD_SIZE];
		unsigned char *primary_fixed = NULL, *peer_fixed = NULL;
		int primary_valid, peer_valid;

		if (rh_raw_mft_stream_pread_reader(reader, &census->raw, mft,
				AT_DATA, NULL, 0, i * sizeof(primary), sizeof(primary),
				primary) ||
				rh_raw_mft_stream_pread_reader(reader, &census->raw, mirror,
					AT_DATA, NULL, 0, i * sizeof(peer), sizeof(peer), peer)) {
			rh_core_fixed_set(census, record_checks[i], 0, 1);
			continue;
		}
		primary_valid = roothealth_bootstrap_mft_record_structure(primary,
			sizeof(primary), (uint32_t)i, &primary_geometry, &primary_fixed);
		peer_valid = roothealth_bootstrap_mft_record_structure(peer,
			sizeof(peer), (uint32_t)i, &primary_geometry, &peer_fixed);
		if (primary_valid < 0 || peer_valid < 0) {
			free(primary_fixed);
			free(peer_fixed);
			return -1;
		}
		rh_core_fixed_set(census, record_checks[i], primary_valid &&
			peer_valid && roothealth_bootstrap_mft_records_equal(primary_fixed,
				peer_fixed, sizeof(primary)), 0);
		free(primary_fixed);
		free(peer_fixed);
	}
	return 0;
}

static int rh_all_providers_complete(struct rh_complete_census *census)
{
	const uint32_t core_mask =
		(UINT32_C(1) << 6U) | (UINT32_C(1) << 7U) |
		(UINT32_C(1) << 8U) | (UINT32_C(1) << 9U) |
		(UINT32_C(1) << 10U) | (UINT32_C(1) << 11U) |
		(UINT32_C(1) << 12U) | (UINT32_C(1) << 13U) |
		(UINT32_C(1) << 16U);
	struct rh_recovery_namespace_authority_view recovery;
	struct rh_system_index_census_view system;
	struct rh_usn_fixed_system_authority_view fixed;
	struct rh_secure_census_provider_view secure;
	struct rh_compressed_census_view compressed;

	return census->system_index_authority &&
		census->recovery_namespace_authority &&
		census->usn_fixed_system_authority && census->secure_provider &&
		census->compressed_provider && census->fixed_metadata.complete &&
		(census->core_fixed_checked_mask & core_mask) == core_mask &&
		!rh_complete_census_recovery_namespace_get_view(census, &recovery) &&
		!rh_complete_census_system_indexes_get_view(census, &system) &&
		system.complete && system.no_io_uncertainty &&
		!rh_complete_census_usn_fixed_system_get_view(census, &fixed) &&
		fixed.complete &&
		!rh_secure_census_provider_get_view(census->secure_provider, &secure) &&
		secure.complete &&
		!rh_compressed_census_get_view(census->compressed_provider,
			&compressed) && compressed.census_complete &&
		compressed.no_io_uncertainty;
}

static int rh_fixed_typed(struct rh_complete_census *census,
		uint64_t *skipped_out)
{
	struct rh_hash_stream hash;
	unsigned char header[16], length[2], result;
	struct rh_secure_census_provider_view secure;
	struct rh_system_index_census_view system;
	struct rh_usn_fixed_system_authority_view fixed;
	uint64_t completed = 0, failed = 0, skipped = 0;
	size_t expected, i;

	expected = rh_coverage_required_fixed_check_count();
	if (expected != RH_COMPLETE_CENSUS_FIXED_CHECK_COUNT) {
		errno = EINVAL;
		return -1;
	}
	rh_hash_stream_init(&hash);
	memset(header, 0, sizeof(header));
	memcpy(header, "RHFIXP2\0", 8U);
	rh_put_u64le(header + 8U, expected);
	if (rh_hash_stream_update(&hash, header, sizeof(header)))
		return -1;
	for (i = 0; i < expected; i++) {
		const char *id = rh_coverage_required_fixed_check_id(i);
		size_t bytes;

		if (!id || !(bytes = strlen(id)) || bytes > UINT16_MAX) {
			errno = EINVAL;
			return -1;
		}
		census->fixed_checks[i].id = id;
		census->fixed_checks[i].result = RH_FIXED_CHECK_SKIPPED;
		if (census->core_fixed_checked_mask & (UINT32_C(1) << i))
			census->fixed_checks[i].result =
				(census->core_fixed_io_mask & (UINT32_C(1) << i)) ?
				RH_FIXED_CHECK_UNREADABLE :
				(census->core_fixed_valid_mask & (UINT32_C(1) << i)) ?
				RH_FIXED_CHECK_PASS : RH_FIXED_CHECK_FAIL;
	}
	if (census->fixed_metadata.complete) {
		census->fixed_checks[5].result = rh_fixed_reader_result(
			census->fixed_metadata.entries[0].state);
		census->fixed_checks[15].result = rh_fixed_reader_result(
			census->fixed_metadata.entries[1].state);
	}
	if (census->secure_provider &&
			!rh_secure_census_provider_get_view(census->secure_provider,
				&secure))
		census->fixed_checks[14].result = secure.complete &&
			secure.sds_clean && secure.sdh_clean && secure.sii_clean ?
			RH_FIXED_CHECK_PASS : RH_FIXED_CHECK_FAIL;
	if (census->system_index_authority &&
			!rh_complete_census_system_indexes_get_view(census, &system)) {
		census->fixed_checks[0].result = system.objid_authority_complete &&
			system.index[RH_SYSTEM_INDEX_OBJID_O].clean ?
			RH_FIXED_CHECK_PASS : RH_FIXED_CHECK_FAIL;
		census->fixed_checks[1].result = system.quota_authority_complete &&
			system.index[RH_SYSTEM_INDEX_QUOTA_O].clean &&
			system.index[RH_SYSTEM_INDEX_QUOTA_Q].clean ?
			RH_FIXED_CHECK_PASS : RH_FIXED_CHECK_FAIL;
		census->fixed_checks[2].result = system.reparse_authority_complete &&
			system.index[RH_SYSTEM_INDEX_REPARSE_R].clean ?
			RH_FIXED_CHECK_PASS : RH_FIXED_CHECK_FAIL;
	}
	if (census->usn_fixed_system_authority &&
			!rh_complete_census_usn_fixed_system_get_view(census, &fixed) &&
			fixed.complete) {
		census->fixed_checks[3].result = RH_FIXED_CHECK_PASS;
		census->fixed_checks[4].result = RH_FIXED_CHECK_PASS;
	}
	for (i = 0; i < expected; i++) {
		const char *id = census->fixed_checks[i].id;
		size_t bytes = strlen(id);

		result = (unsigned char)census->fixed_checks[i].result;
		if (result == RH_FIXED_CHECK_SKIPPED)
			skipped++;
		else {
			completed++;
			if (result != RH_FIXED_CHECK_PASS)
				failed++;
		}
		rh_put_u16le(length, (uint16_t)bytes);
		if (rh_hash_stream_update(&hash, length, sizeof(length)) ||
				rh_hash_stream_update(&hash, id, bytes) ||
				rh_hash_stream_update(&hash, &result, sizeof(result)))
			return -1;
	}
	census->coverage.fixed_system.checks = census->fixed_checks;
	census->coverage.fixed_system.check_count = expected;
	rh_known(&census->coverage.fixed_system.expected, expected);
	rh_known(&census->coverage.fixed_system.completed, completed);
	rh_known(&census->coverage.fixed_system.failed, failed);
	*skipped_out = skipped;
	return rh_hash_stream_final(&hash, census->fixed_manifest_hash);
}

static int rh_publish_partial_coverage(struct rh_complete_census *census)
{
	const struct rh_raw_mft_census *raw = &census->raw;
	const struct rh_namespace_census *ns = &census->namespace_census;
	const struct rh_mft_bitmap_census *mft = &census->mft_bitmap;
	const struct rh_cluster_bitmap_census *cluster = &census->cluster_bitmap;
	struct rh_secure_census_provider_view secure;
	struct rh_compressed_census_view compressed;
	struct rh_system_index_census_view system;
	uint64_t live, unresolved, differences, skipped, indexes_expected = 0;
	uint64_t indexes_completed = 0, blocks_allocated = 0;
	uint64_t blocks_reachable = 0, blocks_examined = 0;
	uint64_t index_bitmap_bits = 0;
	size_t i;

	memset(&census->coverage, 0, sizeof(census->coverage));
	census->coverage.complete = census->providers_complete;
	if (rh_fixed_typed(census, &skipped) ||
			rh_add_u64(raw->live_base_records, raw->live_extent_records, &live) ||
			rh_add_u64(ns->unresolved_parents, ns->orphan_nodes, &unresolved) ||
			rh_add_u64(unresolved, ns->cycles, &unresolved) ||
			rh_add_u64(unresolved, ns->aliases, &unresolved) ||
			rh_add_u64(mft->change_count, cluster->change_count, &differences))
		return -1;
	{
		uint64_t io_errors;

		if (rh_add_u64(raw->unreadable_records,
				census->fixed_metadata.entries_io, &io_errors))
			return -1;
		if (rh_add_u64(io_errors, rh_count_bits(census->core_fixed_io_mask),
				&io_errors))
			return -1;
		rh_known(&census->coverage.io_errors, io_errors);
	}
	if (census->compressed_provider &&
			rh_compressed_census_get_view(census->compressed_provider,
				&compressed))
		return -1;
	if (!census->compressed_provider && rh_add_u64(skipped, 1U, &skipped))
		return -1;
	/* Without Secure, both its counter family and the combined index
	 * denominator remain unknown. */
	if (!census->secure_provider &&
			(rh_add_u64(skipped, 2U, &skipped)))
		return -1;
	rh_known(&census->coverage.skipped, skipped);
	rh_known(&census->coverage.mft_slots.expected, raw->slots_expected);
	rh_known(&census->coverage.mft_slots.completed, raw->slots_completed);
	rh_known(&census->coverage.mft_slots.live, live);
	rh_known(&census->coverage.mft_slots.free, raw->free_records);
	rh_known(&census->coverage.mft_slots.unreadable,
		raw->unreadable_records);
	rh_known(&census->coverage.mft_slots.invalid, raw->invalid_records);
	if (raw->records_bounded) {
		rh_known(&census->coverage.attributes.expected,
			raw->attribute_count);
		rh_known(&census->coverage.attributes.completed,
			raw->attribute_count);
		rh_known(&census->coverage.attributes.resident,
			raw->resident_attributes);
		rh_known(&census->coverage.attributes.nonresident,
			raw->nonresident_attributes);
		rh_known(&census->coverage.attributes.user_defined,
			raw->user_defined_attributes);
		rh_known(&census->coverage.attributes.extents_expected,
			raw->extents_expected);
		rh_known(&census->coverage.attributes.extents_completed,
			raw->extents_completed);
		rh_known(&census->coverage.attributes.runs_expected,
			raw->runs_expected);
		rh_known(&census->coverage.attributes.runs_completed,
			raw->runs_completed);
		rh_known(&census->coverage.attributes.unreadable, 0);
		rh_known(&census->coverage.attributes.skipped, 0);
	}
	if (ns->graph_bounded) {
		rh_known(&census->coverage.namespace_links.expected,
			ns->links_expected);
		rh_known(&census->coverage.namespace_links.completed,
			ns->links_completed);
		if (ns->reciprocity_complete)
			rh_known(&census->coverage.namespace_links.reciprocal,
				ns->links_expected);
		rh_known(&census->coverage.namespace_links.unresolved, unresolved);
		rh_known(&census->coverage.namespace_links.unreadable,
			raw->unreadable_records);
	}
	for (i = 0; i < raw->attribute_count; i++)
		if (raw->attributes[i].type == AT_INDEX_ROOT)
			indexes_expected++;
	if (census->system_index_authority && census->secure_provider &&
			!rh_complete_census_system_indexes_get_view(census, &system) &&
			!rh_secure_census_provider_get_view(census->secure_provider,
				&secure) && system.complete && secure.complete) {
		indexes_completed = ns->i30_indexes_completed +
			(RH_SYSTEM_INDEX_COUNT - 1U) + secure.indexes_completed;
		blocks_allocated = ns->i30_blocks_expected;
		blocks_reachable = ns->i30_blocks_reachable;
		blocks_examined = ns->i30_blocks_examined;
		index_bitmap_bits = ns->i30_bitmap_bits_examined;
		for (i = 1U; i < RH_SYSTEM_INDEX_COUNT; i++) {
			if (rh_add_u64(blocks_allocated,
					system.index[i].blocks_reachable, &blocks_allocated) ||
					rh_add_u64(blocks_reachable,
						system.index[i].blocks_reachable, &blocks_reachable) ||
					rh_add_u64(blocks_examined,
						system.index[i].blocks_examined, &blocks_examined) ||
					system.index[i].bitmap_data_size > UINT64_MAX / 8U ||
					rh_add_u64(index_bitmap_bits,
						system.index[i].bitmap_data_size * 8U,
						&index_bitmap_bits))
				return -1;
		}
		if (rh_add_u64(blocks_allocated, secure.index_blocks_allocated,
				&blocks_allocated) ||
				rh_add_u64(blocks_reachable, secure.index_blocks_reachable,
					&blocks_reachable) ||
				rh_add_u64(blocks_examined, secure.index_blocks_examined,
					&blocks_examined) ||
				rh_add_u64(index_bitmap_bits,
					secure.index_bitmap_bits_examined, &index_bitmap_bits))
			return -1;
		if (indexes_completed != indexes_expected) {
			errno = EUCLEAN;
			return -1;
		}
		rh_known(&census->coverage.indexes.expected, indexes_expected);
		rh_known(&census->coverage.indexes.completed, indexes_completed);
		rh_known(&census->coverage.indexes.blocks_allocated,
			blocks_allocated);
		rh_known(&census->coverage.indexes.blocks_reachable,
			blocks_reachable);
		rh_known(&census->coverage.indexes.blocks_examined,
			blocks_examined);
		rh_known(&census->coverage.indexes.blocks_unreadable, 0);
		rh_known(&census->coverage.indexes.bitmap_bits_expected,
			index_bitmap_bits);
		rh_known(&census->coverage.indexes.bitmap_bits_examined,
			index_bitmap_bits);
		rh_known(&census->coverage.security.ids_expected,
			secure.security_ids_expected);
		rh_known(&census->coverage.security.ids_examined,
			secure.security_ids_examined);
		rh_known(&census->coverage.security.descriptors_expected,
			secure.descriptors_expected);
		rh_known(&census->coverage.security.descriptors_examined,
			secure.descriptors_examined);
		rh_known(&census->coverage.security.sds_entries_expected,
			secure.sds_entries_expected);
		rh_known(&census->coverage.security.sds_entries_examined,
			secure.sds_entries_examined);
		rh_known(&census->coverage.security.sdh_entries_expected,
			secure.sdh_entries_expected);
		rh_known(&census->coverage.security.sdh_entries_examined,
			secure.sdh_entries_examined);
		rh_known(&census->coverage.security.sii_entries_expected,
			secure.sii_entries_expected);
		rh_known(&census->coverage.security.sii_entries_examined,
			secure.sii_entries_examined);
		rh_known(&census->coverage.security.unreadable, 0);
		rh_known(&census->coverage.reparse.attributes_expected,
			system.reparse_count);
		rh_known(&census->coverage.reparse.attributes_examined,
			system.reparse_count);
		rh_known(&census->coverage.reparse.index_entries_expected,
			system.index[RH_SYSTEM_INDEX_REPARSE_R].entries_examined);
		rh_known(&census->coverage.reparse.index_entries_examined,
			system.index[RH_SYSTEM_INDEX_REPARSE_R].entries_examined);
		rh_known(&census->coverage.reparse.unresolved, 0);
		rh_known(&census->coverage.reparse.unreadable, 0);
	}
	/* Directory and metadata index census above is now one denominator. */
	if (mft->complete) {
		rh_known(&census->coverage.bitmaps.mft_bits_expected,
			mft->bitmap_bits_examined);
		rh_known(&census->coverage.bitmaps.mft_bits_examined,
			mft->bitmap_bits_examined);
	}
	if (cluster->complete) {
		rh_known(&census->coverage.bitmaps.cluster_bits_expected,
			cluster->cluster_count);
		rh_known(&census->coverage.bitmaps.cluster_bits_examined,
			cluster->bitmap_bits_examined);
	}
	rh_known(&census->coverage.bitmaps.differences, differences);
	if (census->compressed_provider) {
		uint64_t compressed_unreadable;

		if (rh_add_u64(compressed.payload_invalid,
				compressed.payload_ambiguous, &compressed_unreadable) ||
				rh_add_u64(compressed_unreadable,
					compressed.topology_invalid, &compressed_unreadable) ||
				(!compressed.no_io_uncertainty &&
				 rh_add_u64(compressed_unreadable, 1U,
					&compressed_unreadable)))
			return -1;
		rh_known(&census->coverage.compressed.units_expected,
			compressed.units_expected);
		rh_known(&census->coverage.compressed.units_examined,
			compressed.units_examined);
		rh_known(&census->coverage.compressed.unreadable,
			compressed_unreadable);
	}
	return rh_coverage_hash(&census->coverage, census->coverage_hash);
}

static int rh_combined_hash(struct rh_complete_census *census)
{
	struct rh_hash_stream hash;
	unsigned char header[25];
	unsigned char system_index_hash[32] = {0};
	unsigned char recovery_namespace_hash[32] = {0};
	unsigned char fixed_reference_hash[32] = {0};
	unsigned char secure_hash[32] = {0};
	unsigned char compressed_hash[32] = {0};
	struct rh_recovery_namespace_authority_view recovery_namespace_view;
	struct rh_system_index_census_view system_index_view;
	struct rh_usn_fixed_system_authority_view fixed_reference_view;
	struct rh_secure_census_provider_view secure_view;
	struct rh_compressed_census_view compressed_view;

	if (census->system_index_authority) {
		if (rh_complete_census_system_indexes_get_view(census,
				&system_index_view))
			return -1;
		memcpy(system_index_hash, system_index_view.census_hash, 32U);
	}

	if (census->recovery_namespace_authority) {
		if (rh_complete_census_recovery_namespace_get_view(census,
				&recovery_namespace_view))
			return -1;
		memcpy(recovery_namespace_hash,
			recovery_namespace_view.source_census_hash, 32U);
	}

	if (census->usn_fixed_system_authority) {
		if (rh_complete_census_usn_fixed_system_get_view(census,
				&fixed_reference_view))
			return -1;
		memcpy(fixed_reference_hash, fixed_reference_view.evidence_hash, 32U);
	}
	if (census->secure_provider) {
		if (rh_secure_census_provider_get_view(census->secure_provider,
				&secure_view))
			return -1;
		memcpy(secure_hash, secure_view.census_hash, 32U);
	}
	if (census->compressed_provider) {
		if (rh_compressed_census_get_view(census->compressed_provider,
				&compressed_view))
			return -1;
		memcpy(compressed_hash, compressed_view.census_hash, 32U);
	}

	memset(header, 0, sizeof(header));
	memcpy(header, "RHCENP2\0", 8U);
	rh_put_u64le(header + 8U, census->volume_serial);
	header[16] = census->read_passes_complete;
	header[17] = census->providers_complete;
	header[18] = census->identity_matches;
	header[19] = census->usn_fixed_system_authority != NULL;
	header[20] = census->recovery_namespace_authority != NULL;
	header[21] = census->system_index_authority != NULL;
	header[22] = census->fixed_metadata.complete;
	header[23] = census->secure_provider != NULL;
	header[24] = census->compressed_provider != NULL;
	rh_hash_stream_init(&hash);
	if (rh_hash_stream_update(&hash, header, sizeof(header)) ||
			rh_hash_stream_update(&hash, census->raw.census_hash, 32U) ||
			rh_hash_stream_update(&hash,
				census->namespace_census.census_hash, 32U) ||
			rh_hash_stream_update(&hash, census->index_bitmap.census_hash, 32U) ||
			rh_hash_stream_update(&hash, census->mft_bitmap.census_hash, 32U) ||
			rh_hash_stream_update(&hash, census->cluster_bitmap.census_hash, 32U) ||
			rh_hash_stream_update(&hash, census->fixed_manifest_hash, 32U) ||
			rh_hash_stream_update(&hash, system_index_hash, 32U) ||
			rh_hash_stream_update(&hash, recovery_namespace_hash, 32U) ||
			rh_hash_stream_update(&hash, fixed_reference_hash, 32U) ||
			rh_hash_stream_update(&hash,
				census->fixed_metadata.evidence_hash, 32U) ||
			rh_hash_stream_update(&hash, secure_hash, 32U) ||
			rh_hash_stream_update(&hash, compressed_hash, 32U) ||
			rh_hash_stream_update(&hash, census->coverage_hash, 32U))
		return -1;
	return rh_hash_stream_final(&hash, census->census_hash);
}

int rh_complete_census_run(const struct rh_census_reader *reader,
		const struct rh_complete_census_profile *profile,
		uint64_t generation, struct rh_complete_census *census)
{
	struct rh_census_device device;
	unsigned char boot[512];
	size_t opaque_at;
	int mounted = 0;
	int result = -1;
	int raw_result;
	int failure_errno = 0;
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
	const char *test_stage = "arguments";
#endif

	if (!reader || !profile || !generation || !census ||
			!profile->expected_volume_serial ||
			(profile->roothealth_record != RH_MFT_BITMAP_NO_ROOTHEALTH &&
			 !profile->roothealth_sequence) ||
			profile->require_t1os_identity > 1U ||
			(profile->opaque_record_count && (!profile->opaque_records ||
			 !rh_census_reader_is_pretransaction(reader)))) {
		errno = EINVAL;
		return -1;
	}
	for (opaque_at = 1U; opaque_at < profile->opaque_record_count;
			opaque_at++)
		if (profile->opaque_records[opaque_at - 1U] >=
				profile->opaque_records[opaque_at]) {
			errno = EINVAL;
			return -1;
		}
	memset(census, 0, sizeof(*census));
	memset(&device, 0, sizeof(device));
	census->version = RH_COMPLETE_CENSUS_VERSION;
	census->generation = generation;
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
	test_stage = "boot";
#endif
	if (rh_census_reader_read_exact(reader, 0, sizeof(boot), boot))
		goto out;
	census->volume_serial = rh_get_u64le(boot + 72U);
	if (!census->volume_serial ||
			census->volume_serial != profile->expected_volume_serial) {
		errno = EINVAL;
		goto out;
	}
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
	test_stage = "mount";
#endif
	if (rh_census_device_mount(&device, reader, 0))
		goto out;
	mounted = 1;
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
	test_stage = "raw-mft";
#endif
	if (profile->opaque_record_count)
		raw_result = rh_raw_mft_census_run_with_opaque_slots_reader(
			device.volume, reader, generation, profile->opaque_records,
			profile->opaque_record_count, &census->raw);
	else
		raw_result = rh_raw_mft_census_run_reader_compressed_headers(
			device.volume, reader, generation, &census->raw);
	if (raw_result)
		goto out;
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
	test_stage = "namespace";
#endif
	if (rh_namespace_census_run(&census->raw, generation,
			&census->namespace_census))
		goto out;
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
	test_stage = "namespace-i30";
#endif
	if (rh_namespace_i30_census_run_reader(device.volume, reader,
			&census->raw, &census->namespace_census,
			&census->index_bitmap))
		goto out;
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
	test_stage = "identity";
#endif
	if (rh_namespace_check_t1os_identity(&census->raw,
			&census->namespace_census))
		goto out;
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
	test_stage = "mft-bitmap";
#endif
	if (rh_mft_bitmap_census_run_from_raw_reader(device.volume, reader,
			generation, profile->roothealth_record,
			profile->roothealth_sequence, &census->raw,
			&census->mft_bitmap))
		goto out;
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
	test_stage = "cluster-bitmap";
#endif
	if (rh_cluster_bitmap_census_run_from_raw_reader(device.volume, reader,
			generation, &census->raw, &census->cluster_bitmap))
		goto out;
	census->read_passes_complete = 1;
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
	test_stage = "system-index";
#endif
	if (rh_system_index_census_run_internal(reader, device.volume,
			&census->raw, &census->namespace_census, generation,
			&census->system_index_authority))
		goto out;
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
	test_stage = "fixed-metadata";
#endif
	if (rh_fixed_metadata_reader_census_run(reader, &census->raw,
			&census->fixed_metadata))
		goto out;
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
	test_stage = "recovery-namespace-provider";
#endif
	errno = 0;
	if (rh_recovery_namespace_authority_census_create(census,
			&census->recovery_namespace_authority)) {
		int provider_errno = errno ? errno : EIO;

		if (provider_errno != EPERM && provider_errno != EOPNOTSUPP &&
				provider_errno != EINVAL) {
			errno = provider_errno;
			goto out;
		}
		errno = 0;
	}
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
	test_stage = "fixed-system-provider";
#endif
	errno = 0;
	if (rh_usn_fixed_system_authority_census_run(reader,
			census->volume_serial, generation, &census->raw,
			&census->namespace_census, &census->mft_bitmap,
			&census->usn_fixed_system_authority)) {
		int provider_errno = errno ? errno : EIO;

		if (provider_errno != EPERM && provider_errno != EOPNOTSUPP &&
				provider_errno != EINVAL) {
			errno = provider_errno;
			goto out;
		}
		errno = 0;
	}
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
	test_stage = "core-fixed";
#endif
	if (rh_core_fixed_census(reader, census))
		goto out;
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
	test_stage = "secure-provider";
#endif
	errno = 0;
	if (rh_secure_census_provider_run(reader, device.volume, &census->raw,
			&census->namespace_census, generation,
			&census->secure_provider)) {
		int provider_errno = errno ? errno : EIO;

		if (provider_errno != EPERM && provider_errno != EOPNOTSUPP &&
				provider_errno != EINVAL && provider_errno != EUCLEAN) {
			errno = provider_errno;
			goto out;
		}
		errno = 0;
	}
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
	test_stage = "compressed-provider";
#endif
	if (!profile->opaque_record_count &&
			rh_compressed_census_run(reader, device.volume, &census->raw,
				generation, &census->compressed_provider))
		goto out;
	census->providers_complete = rh_all_providers_complete(census);
	census->identity_matches =
		census->namespace_census.identity == RH_T1OS_IDENTITY_MATCH;
	/* A fully framed wrong identity is a verdict, not a parser error. */
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
	test_stage = "publish";
#endif
	if (rh_publish_partial_coverage(census) || rh_combined_hash(census))
		goto out;
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
	test_stage = "unmount";
#endif
	if (rh_census_device_unmount(&device)) {
		mounted = 0;
		goto out;
	}
	mounted = 0;
	result = 0;
out:
	if (result)
		failure_errno = errno ? errno : EIO;
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
	if (result)
		fprintf(stderr, "roothealth test census failure: stage=%s errno=%d\n",
			test_stage, failure_errno);
#endif
	if (mounted && rh_census_device_unmount(&device) && !failure_errno)
		failure_errno = errno ? errno : EIO;
	if (result) {
		rh_complete_census_release(census);
		errno = failure_errno ? failure_errno : EIO;
	}
	return result;
}

int rh_complete_census_outputs_equal(const struct rh_complete_census *left,
		const struct rh_complete_census *right)
{
	struct rh_usn_fixed_system_authority_view left_fixed, right_fixed;
	struct rh_recovery_namespace_authority_view left_recovery_ns,
		right_recovery_ns;
	struct rh_system_index_census_view left_system_index,
		right_system_index;
	struct rh_secure_census_provider_view left_secure, right_secure;
	struct rh_compressed_census_view left_compressed, right_compressed;

	if (!left || !right || left->version != RH_COMPLETE_CENSUS_VERSION ||
			right->version != RH_COMPLETE_CENSUS_VERSION)
		return 0;
	if (!!left->usn_fixed_system_authority !=
			!!right->usn_fixed_system_authority)
		return 0;
	if (!!left->recovery_namespace_authority !=
			!!right->recovery_namespace_authority)
		return 0;
	if (!!left->system_index_authority != !!right->system_index_authority)
		return 0;
	if (!!left->secure_provider != !!right->secure_provider)
		return 0;
	if (!!left->compressed_provider != !!right->compressed_provider)
		return 0;
	if (left->system_index_authority &&
			(rh_complete_census_system_indexes_get_view(left,
				&left_system_index) ||
			 rh_complete_census_system_indexes_get_view(right,
				&right_system_index) ||
			 memcmp(left_system_index.census_hash,
				right_system_index.census_hash, 32U)))
		return 0;
	if (left->recovery_namespace_authority &&
			(rh_complete_census_recovery_namespace_get_view(left,
				&left_recovery_ns) ||
			 rh_complete_census_recovery_namespace_get_view(right,
				&right_recovery_ns) ||
			 memcmp(left_recovery_ns.source_census_hash,
				right_recovery_ns.source_census_hash, 32U)))
		return 0;
	if (left->usn_fixed_system_authority &&
			(rh_complete_census_usn_fixed_system_get_view(left,
				&left_fixed) ||
			 rh_complete_census_usn_fixed_system_get_view(right,
				&right_fixed) ||
			 memcmp(left_fixed.evidence_hash, right_fixed.evidence_hash, 32U)))
		return 0;
	if (left->secure_provider &&
			(rh_secure_census_provider_get_view(left->secure_provider,
				&left_secure) ||
			 rh_secure_census_provider_get_view(right->secure_provider,
				&right_secure) ||
			 memcmp(left_secure.census_hash, right_secure.census_hash, 32U)))
		return 0;
	if (left->compressed_provider &&
			(rh_compressed_census_get_view(left->compressed_provider,
				&left_compressed) ||
			 rh_compressed_census_get_view(right->compressed_provider,
				&right_compressed) ||
			 memcmp(left_compressed.census_hash,
				right_compressed.census_hash, 32U)))
		return 0;
	return left->volume_serial == right->volume_serial &&
		left->read_passes_complete == right->read_passes_complete &&
		left->providers_complete == right->providers_complete &&
		left->identity_matches == right->identity_matches &&
		!memcmp(left->raw.census_hash, right->raw.census_hash, 32U) &&
		!memcmp(left->namespace_census.census_hash,
			right->namespace_census.census_hash, 32U) &&
		!memcmp(left->index_bitmap.census_hash,
			right->index_bitmap.census_hash, 32U) &&
		!memcmp(left->mft_bitmap.census_hash,
			right->mft_bitmap.census_hash, 32U) &&
		!memcmp(left->cluster_bitmap.census_hash,
			right->cluster_bitmap.census_hash, 32U) &&
		!memcmp(left->fixed_manifest_hash, right->fixed_manifest_hash, 32U) &&
		!memcmp(left->fixed_metadata.evidence_hash,
			right->fixed_metadata.evidence_hash, 32U) &&
		!memcmp(left->coverage_hash, right->coverage_hash, 32U) &&
		!memcmp(left->census_hash, right->census_hash, 32U);
}

void rh_complete_census_release(struct rh_complete_census *census)
{
	if (!census)
		return;
	rh_system_index_census_destroy_internal(census->system_index_authority);
	rh_recovery_namespace_authority_census_destroy(
		census->recovery_namespace_authority);
	rh_usn_fixed_system_authority_census_destroy(
		census->usn_fixed_system_authority);
	rh_secure_census_provider_destroy(census->secure_provider);
	rh_compressed_census_destroy(census->compressed_provider);
	rh_cluster_bitmap_census_destroy(&census->cluster_bitmap);
	rh_mft_bitmap_census_destroy(&census->mft_bitmap);
	rh_index_bitmap_census_destroy(&census->index_bitmap);
	rh_namespace_census_release(&census->namespace_census);
	rh_raw_mft_census_release(&census->raw);
	memset(census, 0, sizeof(*census));
}
