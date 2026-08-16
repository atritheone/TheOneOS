#ifndef ROOTHEALTH_NATIVE_AUTHORITY_H
#define ROOTHEALTH_NATIVE_AUTHORITY_H

#include "roothealth_replay_analysis.h"

#include <stddef.h>
#include <stdint.h>

#define RH_NATIVE_AUTHORITY_CENSUS_VERSION UINT32_C(1)

struct rh_free_slot_component_seal;
struct rh_native_authority_census;

struct rh_native_authority_census_view {
	uint32_t version;
	uint64_t correlation_generation;
	uint64_t records_expected;
	uint64_t records_completed;
	uint64_t unknown_records;
	uint64_t unsupported_records;
	uint64_t error_records;
	uint64_t open_attributes_expected;
	uint64_t open_attributes_completed;
	uint64_t targets_expected;
	uint64_t targets_completed;
	uint64_t controls_expected;
	uint64_t controls_completed;
	uint64_t redo_records;
	uint64_t undo_records;
	uint64_t checkpoint_records;
	uint64_t transaction_tables;
	uint64_t open_attribute_tables;
	uint64_t attribute_name_tables;
	uint64_t dirty_page_tables;
	uint64_t dynamic_open_attributes;
	uint64_t delete_dirty_controls;
	uint64_t hotfix_controls;
	uint64_t mutation_records;
	uint64_t winner_redos;
	uint64_t loser_redos;
	uint64_t loser_undos;
	uint8_t checked;
	uint8_t complete;
	unsigned char source_hash[32];
	unsigned char evidence_hash[32];
};

/* The owned replay extension is declared by roothealth_replay_analysis.h. */
void rh_native_authority_census_destroy(
		struct rh_native_authority_census *census);
int rh_native_authority_census_get_view(
		const struct rh_native_authority_census *census,
		struct rh_native_authority_census_view *view);

int rh_native_open_attribute_component_seal_create(
		const struct rh_native_authority_census *census,
		struct rh_free_slot_component_seal **seal);
int rh_native_target_component_seal_create(
		const struct rh_native_authority_census *census,
		struct rh_free_slot_component_seal **seal);
int rh_native_control_component_seal_create(
		const struct rh_native_authority_census *census,
		struct rh_free_slot_component_seal **seal);

#ifdef ROOTHEALTH_REPAIR_TESTING
enum rh_native_authority_test_tamper {
	RH_NATIVE_TEST_TAMPER_SOURCE_HASH = 1,
	RH_NATIVE_TEST_TAMPER_OPEN_COUNT = 2,
	RH_NATIVE_TEST_TAMPER_TARGET_REFERENCE = 3,
	RH_NATIVE_TEST_TAMPER_UNKNOWN_COUNT = 4,
	RH_NATIVE_TEST_TAMPER_MANIFEST_OMISSION = 5
};
int rh_native_authority_test_tamper(
		struct rh_native_authority_census *census,
		enum rh_native_authority_test_tamper tamper);
#endif

#endif
