#ifndef ROOTHEALTH_RECOVERY_NAMESPACE_AUTHORITY_H
#define ROOTHEALTH_RECOVERY_NAMESPACE_AUTHORITY_H

#include <stddef.h>
#include <stdint.h>

#include "roothealth_namespace.h"

struct rh_complete_census;
struct rh_free_slot_component_seal;
struct rh_recovery_namespace_authority_census;

#define RH_RECOVERY_NAMESPACE_AUTHORITY_VERSION UINT32_C(1)

struct rh_recovery_namespace_authority_view {
	uint32_t version;
	uint64_t correlation_generation;
	uint64_t raw_file_name_links;
	uint64_t namespace_links;
	uint64_t i30_edges;
	enum rh_namespace_recovery_anchor_state recovery_anchor_state;
	uint64_t recovery_anchor_components_completed;
	uint64_t recovery_anchor_reference_occurrences;
	uint64_t reference_occurrences_expected;
	uint64_t reference_occurrences_completed;
	uint64_t unique_references;
	unsigned char recovery_anchor_hash[32];
	unsigned char source_census_hash[32];
};

/* Accessors accept only the source-owned object retained by a common census. */
int rh_complete_census_recovery_namespace_get_view(
		const struct rh_complete_census *complete,
		struct rh_recovery_namespace_authority_view *view);
int rh_complete_census_recovery_namespace_component_seal_create(
		const struct rh_complete_census *complete,
		struct rh_free_slot_component_seal **output);

#endif
