#ifndef ROOTHEALTH_FREE_SLOT_AUTHORITY_INTERNAL_H
#define ROOTHEALTH_FREE_SLOT_AUTHORITY_INTERNAL_H

#include "roothealth_free_slot_authority.h"

/*
 * Private, source-owned friend ABI.  Every entry point fixes the component
 * kind in its name; there is deliberately no production function accepting a
 * caller-selected kind or a caller assertion of completeness.
 */
int rh_free_slot_friend_native_open_attribute_seal(
		uint64_t correlation_generation, uint64_t items_expected,
		uint64_t items_completed, const unsigned char source_census_hash[32],
		const struct rh_free_slot_reference *references,
		size_t reference_count, struct rh_free_slot_component_seal **output);
int rh_free_slot_friend_native_target_seal(
		uint64_t correlation_generation, uint64_t items_expected,
		uint64_t items_completed, const unsigned char source_census_hash[32],
		const struct rh_free_slot_reference *references,
		size_t reference_count, struct rh_free_slot_component_seal **output);
int rh_free_slot_friend_native_control_seal(
		uint64_t correlation_generation, uint64_t items_expected,
		uint64_t items_completed, const unsigned char source_census_hash[32],
		const struct rh_free_slot_reference *references,
		size_t reference_count, struct rh_free_slot_component_seal **output);
int rh_free_slot_friend_reparse_seal(
		uint64_t correlation_generation, uint64_t items_expected,
		uint64_t items_completed, const unsigned char source_census_hash[32],
		const struct rh_free_slot_reference *references,
		size_t reference_count, struct rh_free_slot_component_seal **output);
int rh_free_slot_friend_objid_seal(
		uint64_t correlation_generation, uint64_t items_expected,
		uint64_t items_completed, const unsigned char source_census_hash[32],
		const struct rh_free_slot_reference *references,
		size_t reference_count, struct rh_free_slot_component_seal **output);
int rh_free_slot_friend_recovery_namespace_seal(
		uint64_t correlation_generation, uint64_t items_expected,
		uint64_t items_completed, const unsigned char source_census_hash[32],
		const struct rh_free_slot_reference *references,
		size_t reference_count, struct rh_free_slot_component_seal **output);
int rh_free_slot_friend_wal_exclusions_seal(
		uint64_t correlation_generation, uint64_t ranges_expected,
		uint64_t ranges_completed, const unsigned char source_census_hash[32],
		const struct rh_free_slot_range *ranges, size_t range_count,
		const struct rh_free_slot_range *raw_ranges, size_t raw_range_count,
		struct rh_free_slot_component_seal **output);
int rh_free_slot_friend_usn_fixed_system_seal(
		uint64_t correlation_generation, enum rh_free_slot_usn_state usn_state,
		const struct rh_free_slot_reference *usn_reference,
		uint64_t items_expected,
		uint64_t items_completed, const unsigned char source_census_hash[32],
		const struct rh_free_slot_reference *references,
		size_t reference_count, struct rh_free_slot_component_seal **output);

#endif
