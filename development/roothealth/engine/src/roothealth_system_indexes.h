#ifndef ROOTHEALTH_SYSTEM_INDEXES_H
#define ROOTHEALTH_SYSTEM_INDEXES_H

#include <stddef.h>
#include <stdint.h>

#include "roothealth_census_device.h"
#include "roothealth_free_slot_authority.h"
#include "roothealth_raw_mft.h"

struct rh_complete_census;
struct rh_namespace_census;

#define RH_SYSTEM_INDEX_CENSUS_VERSION UINT32_C(1)

enum rh_system_index_kind {
	RH_SYSTEM_INDEX_INVALID = 0,
	RH_SYSTEM_INDEX_REPARSE_R = 1,
	RH_SYSTEM_INDEX_OBJID_O = 2,
	RH_SYSTEM_INDEX_QUOTA_O = 3,
	RH_SYSTEM_INDEX_QUOTA_Q = 4,
	RH_SYSTEM_INDEX_COUNT = 5
};

struct rh_system_index_state {
	uint64_t owner_record;
	uint16_t owner_sequence;
	uint16_t root_instance;
	uint16_t allocation_instance;
	uint16_t bitmap_instance;
	uint64_t entries_examined;
	uint64_t end_entries_examined;
	uint64_t blocks_examined;
	uint64_t blocks_reachable;
	uint64_t allocation_data_size;
	uint64_t bitmap_data_size;
	uint8_t root_found;
	uint8_t large;
	uint8_t structurally_valid;
	uint8_t manifest_exact;
	uint8_t clean;
	unsigned char observed_manifest_hash[32];
	unsigned char canonical_manifest_hash[32];
};

struct rh_system_index_census;

struct rh_system_index_census_view {
	uint32_t version;
	uint64_t generation;
	uint64_t mft_records_expected;
	uint64_t mft_records_examined;
	uint64_t attributes_expected;
	uint64_t attributes_examined;
	uint64_t file_name_links_expected;
	uint64_t file_name_links_examined;
	uint64_t standard_information_examined;
	uint64_t quota_owner_references_examined;
	uint64_t quota_owner_references_resolved;
	uint64_t index_entries_examined;
	uint64_t index_end_entries_examined;
	uint64_t index_blocks_examined;
	uint64_t index_blocks_reachable;
	uint8_t records_complete;
	uint8_t attributes_complete;
	uint8_t namespace_reciprocity_complete;
	uint8_t reparse_authority_complete;
	uint8_t objid_authority_complete;
	uint8_t quota_authority_complete;
	uint8_t no_io_uncertainty;
	uint8_t complete;
	size_t reparse_count;
	size_t objid_count;
	size_t quota_count;
	size_t sid_arena_size;
	size_t reparse_reference_count;
	size_t objid_reference_count;
	size_t quota_source_reference_count;
	uint32_t quota_defaults_owner_id;
	uint32_t quota_defaults_version;
	uint32_t quota_defaults_flags;
	uint32_t quota_first_user_owner_id;
	uint32_t quota_first_user_version;
	uint32_t quota_first_user_flags;
	uint16_t quota_first_user_sid_length;
	struct rh_system_index_state index[RH_SYSTEM_INDEX_COUNT];
	unsigned char raw_census_hash[32];
	unsigned char namespace_census_hash[32];
	unsigned char reparse_manifest_hash[32];
	unsigned char objid_manifest_hash[32];
	unsigned char quota_manifest_hash[32];
	unsigned char namespace_reciprocity_hash[32];
	unsigned char census_hash[32];
};

#ifdef ROOTHEALTH_REPAIR_TESTING
/* Direct fixture API; absent from production headers and objects. */
int rh_system_index_census_run(const struct rh_census_reader *reader,
		struct _ntfs_volume *volume, const struct rh_raw_mft_census *raw,
		const struct rh_namespace_census *namespace_census,
		uint64_t generation, struct rh_system_index_census **output);
void rh_system_index_census_destroy(struct rh_system_index_census *census);
int rh_system_index_census_get_view(
		const struct rh_system_index_census *census,
		struct rh_system_index_census_view *view);

/* Source-owned free-slot reference manifests; no caller completion booleans. */
int rh_system_index_reparse_component_seal(
		const struct rh_system_index_census *census,
		struct rh_free_slot_component_seal **output);
int rh_system_index_objid_component_seal(
		const struct rh_system_index_census *census,
		struct rh_free_slot_component_seal **output);
#endif

/* Production accessors accept only the common publisher's source-owned object. */
int rh_complete_census_system_indexes_get_view(
		const struct rh_complete_census *complete,
		struct rh_system_index_census_view *view);
int rh_complete_census_reparse_component_seal_create(
		const struct rh_complete_census *complete,
		struct rh_free_slot_component_seal **output);
int rh_complete_census_objid_component_seal_create(
		const struct rh_complete_census *complete,
		struct rh_free_slot_component_seal **output);

#endif
