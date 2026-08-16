#ifndef ROOTHEALTH_USN_FIXED_SYSTEM_AUTHORITY_H
#define ROOTHEALTH_USN_FIXED_SYSTEM_AUTHORITY_H

#include <stddef.h>
#include <stdint.h>

#include "roothealth_free_slot_authority.h"

struct rh_complete_census;
struct rh_usn_fixed_system_authority_census;

#define RH_USN_FIXED_SYSTEM_AUTHORITY_VERSION UINT32_C(1)
#define RH_USN_FIXED_SYSTEM_ROLE_COUNT UINT64_C(17)

struct rh_usn_fixed_system_authority_view {
	uint32_t version;
	uint64_t correlation_generation;
	uint64_t fixed_roles_expected;
	uint64_t fixed_roles_completed;
	uint64_t fixed_roles_present;
	uint64_t usn_records_expected;
	uint64_t usn_records_completed;
	uint64_t reference_fields_examined;
	uint64_t unique_references;
	enum rh_free_slot_usn_state usn_state;
	struct rh_free_slot_reference usn_reference;
	uint32_t present_role_mask;
	uint32_t absent_role_mask;
	unsigned char attrdef_payload_hash[32];
	unsigned char upcase_payload_hash[32];
	unsigned char role_manifest_hash[32];
	unsigned char reference_manifest_hash[32];
	unsigned char evidence_hash[32];
	uint8_t complete;
};

/* Accessors accept only the source-owned object retained by a common census. */
int rh_complete_census_usn_fixed_system_get_view(
		const struct rh_complete_census *complete,
		struct rh_usn_fixed_system_authority_view *view);
int rh_complete_census_usn_fixed_system_component_seal_create(
		const struct rh_complete_census *complete,
		struct rh_free_slot_component_seal **output);

#endif
