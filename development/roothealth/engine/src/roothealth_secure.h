#ifndef ROOTHEALTH_SECURE_H
#define ROOTHEALTH_SECURE_H

#include <stddef.h>
#include <stdint.h>

#include "roothealth_overlay.h"

struct rh_raw_mft_census;
struct rh_census_reader;

#define RH_SECURE_AUTHORITY_VERSION UINT32_C(1)
#define RH_SECURE_LEDGER_FORMAT UINT32_C(3)
#define RH_SECURE_EVIDENCE_VERSION UINT32_C(1)
#define RH_SECURE_BATCH_CURSOR_VERSION UINT32_C(1)
#define RH_SECURE_BATCH_MAX_OPERATIONS 4096U
#define RH_SECURE_SDS_CHECK_ID "system.secure.sds"
#define RH_SECURE_SDH_CHECK_ID "system.secure.sdh"
#define RH_SECURE_SII_CHECK_ID "system.secure.sii"

enum rh_secure_view {
	RH_SECURE_PRETRANSACTION = 1,
	RH_SECURE_STAGED = 2
};

enum rh_secure_stage_result {
	RH_SECURE_STAGE_ERROR = -1,
	RH_SECURE_STAGE_CLEAN = 0,
	RH_SECURE_STAGE_PLANNED = 1,
	RH_SECURE_STAGE_REFUSED = 2
};

struct rh_secure_census {
	enum rh_secure_view view;
	uint32_t ledger_format;
	uint64_t generation;
	uint64_t volume_serial;
	int coverage_complete;
	int identity_bound;
	int no_io_uncertainty;
	int complete_mft_census;
	int complete_attribute_census;
	int complete_runlist_census;
	int complete_namespace_census;
	int complete_index_census;
	int complete_security_descriptor_census;
	int complete_security_id_census;
	int namespace_security_reciprocity_complete;
	int global_security_identity_complete;
	int sole_valid_peer_authority_complete;
	int no_conflicting_valid_authorities;
	int target_ownership_exact;
	int targets_outside_wal;
	int data_preserving;
	int final_overlay_valid;
	int raw_mft_extent_authority_complete;
	uint64_t mft_records_expected;
	uint64_t mft_records_examined;
	uint64_t attributes_expected;
	uint64_t attributes_examined;
	uint64_t runs_expected;
	uint64_t runs_examined;
	uint64_t namespace_links_expected;
	uint64_t namespace_links_examined;
	uint64_t namespace_links_reciprocal;
	uint64_t security_descriptors_expected;
	uint64_t security_descriptors_examined;
	uint64_t security_ids_expected;
	uint64_t security_ids_examined;
	uint64_t security_id_references_expected;
	uint64_t security_id_references_examined;
	uint64_t security_id_references_resolved;
	uint64_t legacy_security_descriptors_expected;
	uint64_t legacy_security_descriptors_examined;
	size_t live_security_id_count;
	const uint32_t *live_security_ids;
	unsigned char coverage_ledger_hash[32];
	unsigned char identity_graph_hash[32];
	unsigned char namespace_security_hash[32];
	unsigned char security_id_use_hash[32];
	unsigned char global_security_hash[32];
	unsigned char descriptor_manifest_hash[32];
	unsigned char raw_mft_census_hash[32];
	unsigned char legacy_security_descriptor_hash[32];
	const struct rh_raw_mft_census *raw_mft_census;
};

struct rh_secure_authority {
	uint32_t version;
	struct rh_secure_census census;
	uint32_t *owned_live_security_ids;
	unsigned char seal[32];
};

struct rh_secure_descriptor {
	uint32_t hash;
	uint32_t security_id;
	uint64_t offset;
	uint32_t length;
	unsigned char descriptor_hash[32];
};

struct rh_secure_mapping_slice {
	uint64_t logical_offset;
	uint64_t length;
	uint64_t physical_offset;
	int64_t logical_vcn;
	int64_t lcn;
	uint64_t storage_mft_record;
	uint16_t storage_sequence;
	uint16_t attribute_instance;
	int64_t lowest_vcn;
};

struct rh_secure_index_state {
	int large;
	int root_clean;
	int allocation_clean;
	int bitmap_clean;
	int bitmap_resident;
	uint16_t allocation_instance;
	uint16_t bitmap_instance;
	uint64_t root_storage_mft_record;
	uint16_t root_storage_sequence;
	uint64_t root_record_physical;
	uint64_t bitmap_storage_mft_record;
	uint16_t bitmap_storage_sequence;
	uint64_t bitmap_record_physical;
	uint64_t allocation_data_size;
	uint64_t bitmap_data_size;
	uint64_t bitmap_semantic_physical;
	uint64_t canonical_block_count;
	unsigned char *root_current;
	unsigned char *allocation_current;
	unsigned char *canonical_blocks;
	unsigned char *bitmap_current;
	unsigned char *bitmap_canonical;
	unsigned char *dirty_blocks;
	struct rh_secure_mapping_slice *allocation_slices;
	size_t allocation_slice_count;
	struct rh_secure_mapping_slice *bitmap_slices;
	size_t bitmap_slice_count;
};

struct rh_secure_inspection {
	uint64_t volume_serial;
	uint64_t owner_mft_record;
	uint16_t owner_sequence;
	uint16_t sds_instance;
	uint16_t sdh_instance;
	uint16_t sii_instance;
	uint64_t sds_data_size;
	uint64_t mft_record_physical;
	uint64_t sdh_semantic_physical;
	uint64_t sii_semantic_physical;
	uint64_t sdh_value_length;
	uint64_t sii_value_length;
	int sds_clean;
	int sdh_clean;
	int sii_clean;
	unsigned char sds_current_hash[32];
	unsigned char sds_staged_hash[32];
	unsigned char sdh_current_hash[32];
	unsigned char sdh_canonical_hash[32];
	unsigned char sii_current_hash[32];
	unsigned char sii_canonical_hash[32];
	unsigned char descriptor_manifest_hash[32];
	unsigned char mapping_hash[32];
	unsigned char *sds_current;
	unsigned char *sds_staged;
	unsigned char *sdh_canonical;
	unsigned char *sii_canonical;
	struct rh_secure_descriptor *descriptors;
	size_t descriptor_count;
	struct rh_secure_mapping_slice *sds_slices;
	size_t sds_slice_count;
	const struct rh_raw_mft_census *raw_mft_census;
	struct rh_secure_index_state sdh_index;
	struct rh_secure_index_state sii_index;
};

struct rh_secure_plan {
	uint64_t generation;
	uint64_t volume_serial;
	size_t initial_checkpoint;
	size_t final_checkpoint;
	size_t first_operation_ordinal;
	size_t operation_count;
	size_t sds_operation_count;
	size_t sdh_operation_count;
	size_t sii_operation_count;
	int clean;
	int staged_verified;
	int finalized;
	int batch;
	int more_work;
	uint64_t batch_ordinal;
	unsigned char descriptor_manifest_hash[32];
	unsigned char mapping_hash[32];
	unsigned char pre_state_hash[32];
	unsigned char staged_state_hash[32];
	unsigned char pre_evidence_hash[32];
	unsigned char staged_evidence_hash[32];
	unsigned char staged_plan_hash[32];
};

struct rh_secure_batch_cursor {
	uint32_t version;
	uint32_t complete;
	uint64_t generation;
	uint64_t volume_serial;
	uint64_t next_batch_ordinal;
	uint64_t operations_completed;
	unsigned char descriptor_manifest_hash[32];
	unsigned char mapping_hash[32];
	unsigned char expected_state_hash[32];
	unsigned char seal[32];
};

struct rh_secure_recovery_entry {
	enum rh_write_kind kind;
	uint64_t target_offset;
	size_t length;
	unsigned char old_hash[32];
	unsigned char new_hash[32];
	struct rh_write_semantic_target target;
};

int rh_secure_authority_seal(const struct rh_secure_census *census,
		struct rh_secure_authority *authority);
void rh_secure_authority_destroy(struct rh_secure_authority *authority);
int rh_secure_authority_valid(const struct rh_secure_authority *authority,
		enum rh_secure_view view, uint64_t volume_serial,
		const unsigned char descriptor_manifest_hash[32]);
int rh_secure_descriptor_bytes_valid(const void *bytes, size_t length);
int rh_secure_legacy_census(const struct rh_raw_mft_census *census,
		uint64_t *descriptor_count, unsigned char manifest_hash[32]);
int rh_secure_legacy_census_reader(const struct rh_census_reader *reader,
		const struct rh_raw_mft_census *census,
		uint64_t *descriptor_count, unsigned char manifest_hash[32]);
#ifdef ROOTHEALTH_TESTING
int rh_secure_test_ranges_overlap(uint64_t first_offset,
		uint64_t first_length, uint64_t second_offset, uint64_t second_length);
void rh_secure_test_set_batch_max_operations(size_t maximum_operations);
#endif
int rh_secure_inspect(ntfs_volume *volume, struct rh_writer *writer,
		const struct rh_secure_census *census,
		struct rh_secure_inspection *inspection);
int rh_secure_inspect_reader(ntfs_volume *volume,
		const struct rh_census_reader *reader,
		const struct rh_secure_census *census,
		struct rh_secure_inspection *inspection);
void rh_secure_inspection_destroy(struct rh_secure_inspection *inspection);
enum rh_secure_stage_result rh_secure_stage(struct rh_ntfs_overlay *overlay,
		const struct rh_secure_authority *authority,
		struct rh_secure_plan *plan);
enum rh_secure_stage_result rh_secure_stage_batch(
		struct rh_ntfs_overlay *overlay,
		const struct rh_secure_authority *authority,
		const struct rh_secure_batch_cursor *before,
		struct rh_secure_batch_cursor *after, struct rh_secure_plan *plan);
int rh_secure_verify_staged(struct rh_ntfs_overlay *overlay,
		const struct rh_secure_authority *authority,
		struct rh_secure_plan *plan);
int rh_secure_verify_batch_staged(struct rh_ntfs_overlay *overlay,
		const struct rh_secure_authority *authority,
		const struct rh_secure_batch_cursor *after,
		struct rh_secure_plan *plan);
int rh_secure_finalize(struct rh_writer *writer, struct rh_secure_plan *plan);
int rh_secure_rederive_recovery(ntfs_volume *pre_volume,
		struct rh_writer *pre_writer,
		const struct rh_secure_authority *pre_authority,
		ntfs_volume *post_volume, struct rh_writer *post_writer,
		const struct rh_secure_authority *post_authority,
		const struct rh_secure_recovery_entry *entries, size_t entry_count);
int rh_secure_rederive_batch_recovery(ntfs_volume *pre_volume,
		struct rh_writer *pre_writer,
		const struct rh_secure_authority *pre_authority,
		const struct rh_secure_batch_cursor *before,
		ntfs_volume *post_volume, struct rh_writer *post_writer,
		const struct rh_secure_authority *post_authority,
		const struct rh_secure_batch_cursor *after,
		const struct rh_secure_recovery_entry *entries, size_t entry_count);

#endif
