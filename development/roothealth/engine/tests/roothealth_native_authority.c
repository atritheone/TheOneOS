#include "roothealth_free_slot_authority.h"
#include "roothealth_native_authority.h"

#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define TABLE_HEADER 24U
#define ALLOCATED UINT32_C(0xffffffff)

static void wr16(unsigned char *bytes, uint16_t value)
{
	bytes[0] = (unsigned char)value;
	bytes[1] = (unsigned char)(value >> 8);
}

static void wr32(unsigned char *bytes, uint32_t value)
{
	wr16(bytes, (uint16_t)value);
	wr16(bytes + 2, (uint16_t)(value >> 16));
}

static void wr64(unsigned char *bytes, uint64_t value)
{
	wr32(bytes, (uint32_t)value);
	wr32(bytes + 4, (uint32_t)(value >> 32));
}

static void common(unsigned char *record, size_t size, uint64_t lsn,
		uint64_t previous_lsn, uint64_t undo_next_lsn, uint32_t transaction)
{
	memset(record, 0, size);
	wr64(record, lsn);
	wr64(record + 8, previous_lsn);
	wr64(record + 16, undo_next_lsn);
	wr32(record + 24, (uint32_t)size - 48U);
	wr16(record + 28, 1U);
	wr32(record + 32, 1U);
	wr32(record + 36, transaction);
}

static int build_census(uint64_t generation, uint16_t name,
		struct rh_native_authority_census **census,
		struct rh_replay_analysis_result *result)
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

	common(open_record, sizeof(open_record), 100, 0, 0, 64);
	wr16(open_record + 48, 28U);
	wr16(open_record + 52, 0x28U);
	wr16(open_record + 54, 44U);
	wr16(open_record + 56, 0x58U);
	wr16(open_record + 58, 2U);
	wr16(open_record + 60, TABLE_HEADER);
	wr32(open_record + 80, ALLOCATED);
	wr64(open_record + 88, (UINT64_C(7) << 48) | 42U);
	wr64(open_record + 96, 90U);
	open_record[105] = 1U;
	open_record[112] = 1U;
	wr32(open_record + 108, 0x80U);
	wr16(open_record + 128, name);

	common(update, sizeof(update), 200, 100, 100, 64);
	wr16(update + 40, 2U);
	wr16(update + 48, 7U);
	wr16(update + 50, 7U);
	wr16(update + 52, 0x28U);
	wr16(update + 54, 2U);
	wr16(update + 56, 0x30U);
	wr16(update + 58, 2U);
	wr16(update + 60, TABLE_HEADER);
	wr16(update + 62, 1U);
	wr16(update + 64, 360U);
	wr16(update + 66, 24U);
	wr16(update + 68, 6U);
	wr16(update + 70, 2U);
	wr64(update + 80, 4U);
	update[88] = 'S';
	update[96] = 'R';

	common(forget, sizeof(forget), 300, 200, 200, 64);
	wr16(forget + 48, 27U);

	return rh_replay_analysis_plan_native(records,
		sizeof(records) / sizeof(records[0]), &geometry, 100U, 300U,
		generation, result, census);
}

static int tamper_negative(enum rh_native_authority_test_tamper tamper)
{
	struct rh_native_authority_census *census = NULL;
	struct rh_free_slot_component_seal *open = NULL, *target = NULL;
	struct rh_free_slot_component_seal *control = NULL;
	struct rh_native_authority_census_view view;
	int refused;

	if (build_census(17U, 'N', &census, NULL) ||
			rh_native_authority_test_tamper(census, tamper))
		goto fail;
	refused = rh_native_authority_census_get_view(census, &view) &&
		rh_native_open_attribute_component_seal_create(census, &open) &&
		rh_native_target_component_seal_create(census, &target) &&
		rh_native_control_component_seal_create(census, &control) &&
		!open && !target && !control;
	rh_free_slot_component_seal_destroy(control);
	rh_free_slot_component_seal_destroy(target);
	rh_free_slot_component_seal_destroy(open);
	rh_native_authority_census_destroy(census);
	return refused ? 0 : -1;
fail:
	rh_free_slot_component_seal_destroy(control);
	rh_free_slot_component_seal_destroy(target);
	rh_free_slot_component_seal_destroy(open);
	rh_native_authority_census_destroy(census);
	return -1;
}

int main(void)
{
	struct rh_native_authority_census *census = NULL;
	struct rh_native_authority_census *regenerated = NULL;
	struct rh_native_authority_census *alternate = NULL;
	struct rh_native_authority_census_view view;
	struct rh_native_authority_census_view regenerated_view;
	struct rh_native_authority_census_view alternate_view;
	struct rh_replay_analysis_result result;
	struct rh_free_slot_component_seal *open = NULL, *target = NULL;
	struct rh_free_slot_component_seal *control = NULL;
	unsigned char open_hash[32], target_hash[32], control_hash[32];
	int status = 1;

	memset(&result, 0, sizeof(result));
	if (build_census(17U, 'N', &census, &result) ||
			rh_native_authority_census_get_view(census, &view) ||
			view.version != RH_NATIVE_AUTHORITY_CENSUS_VERSION ||
			view.correlation_generation != 17U || !view.checked ||
			!view.complete || view.records_expected != 3U ||
			view.records_completed != 3U || view.unknown_records ||
			view.unsupported_records || view.error_records ||
			view.open_attributes_expected != 1U ||
			view.open_attributes_completed != 1U ||
			view.targets_expected != 1U || view.targets_completed != 1U ||
			view.controls_expected != 2U || view.controls_completed != 2U ||
			view.redo_records != 1U || view.undo_records ||
			view.dynamic_open_attributes != 1U ||
			view.mutation_records != 1U || view.winner_redos != 1U ||
			view.loser_redos || view.loser_undos ||
			result.dynamic_open_attributes != 1U ||
			result.mutation_records != 1U || result.winner_redos != 1U ||
			rh_native_open_attribute_component_seal_create(census, &open) ||
			rh_native_target_component_seal_create(census, &target) ||
			rh_native_control_component_seal_create(census, &control) ||
			rh_free_slot_component_seal_kind(open) !=
				RH_FREE_SLOT_COMPONENT_NATIVE_OPEN_ATTRIBUTE ||
			rh_free_slot_component_seal_kind(target) !=
				RH_FREE_SLOT_COMPONENT_NATIVE_TARGET ||
			rh_free_slot_component_seal_kind(control) !=
				RH_FREE_SLOT_COMPONENT_NATIVE_CONTROL ||
			rh_free_slot_component_seal_hash(open, open_hash) ||
			rh_free_slot_component_seal_hash(target, target_hash) ||
			rh_free_slot_component_seal_hash(control, control_hash) ||
			!memcmp(open_hash, target_hash, 32U) ||
			!memcmp(open_hash, control_hash, 32U) ||
			!memcmp(target_hash, control_hash, 32U) ||
			build_census(99U, 'N', &regenerated, NULL) ||
			rh_native_authority_census_get_view(regenerated,
				&regenerated_view) ||
			regenerated_view.correlation_generation != 99U ||
			memcmp(view.source_hash, regenerated_view.source_hash, 32U) ||
			memcmp(view.evidence_hash, regenerated_view.evidence_hash, 32U) ||
			build_census(99U, 'M', &alternate, NULL) ||
			rh_native_authority_census_get_view(alternate, &alternate_view) ||
			!memcmp(view.source_hash, alternate_view.source_hash, 32U) ||
			!memcmp(view.evidence_hash, alternate_view.evidence_hash, 32U))
		goto out;
	if (tamper_negative(RH_NATIVE_TEST_TAMPER_SOURCE_HASH) ||
			tamper_negative(RH_NATIVE_TEST_TAMPER_OPEN_COUNT) ||
			tamper_negative(RH_NATIVE_TEST_TAMPER_TARGET_REFERENCE) ||
			tamper_negative(RH_NATIVE_TEST_TAMPER_UNKNOWN_COUNT) ||
			tamper_negative(RH_NATIVE_TEST_TAMPER_MANIFEST_OMISSION))
		goto out;
	puts("PASS immutable native replay census and typed OPEN/TARGET/CONTROL seals");
	status = 0;
out:
	rh_free_slot_component_seal_destroy(control);
	rh_free_slot_component_seal_destroy(target);
	rh_free_slot_component_seal_destroy(open);
	rh_native_authority_census_destroy(alternate);
	rh_native_authority_census_destroy(regenerated);
	rh_native_authority_census_destroy(census);
	return status;
}
