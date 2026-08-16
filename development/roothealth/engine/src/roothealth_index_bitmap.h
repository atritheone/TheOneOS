#ifndef ROOTHEALTH_INDEX_BITMAP_H
#define ROOTHEALTH_INDEX_BITMAP_H

#include <stddef.h>
#include <stdint.h>

#include "roothealth_overlay.h"
#include "roothealth_policy.h"

struct rh_raw_mft_census;
struct rh_census_reader;

/* One v1 WAL transaction capacity; a complete census may exceed this. */
#define RH_INDEX_BITMAP_MAX_CHANGES 4094U
#define RH_INDEX_BITMAP_EVIDENCE_VERSION 2U

enum rh_index_bitmap_storage {
	RH_INDEX_BITMAP_RESIDENT_MFT = 1,
	RH_INDEX_BITMAP_NONRESIDENT = 2
};

struct rh_index_bitmap_change {
	uint64_t owner_mft_record;
	uint16_t owner_sequence;
	/* Physical attribute-record provenance can be an ATTRIBUTE_LIST extent. */
	uint64_t storage_mft_record;
	uint16_t storage_sequence;
	uint16_t index_root_instance;
	uint16_t index_allocation_instance;
	uint16_t bitmap_instance;
	enum rh_index_bitmap_storage storage;
	uint64_t block_ordinal;
	int64_t child_vcn;
	uint64_t logical_offset;
	int64_t lowest_vcn;
	int64_t logical_vcn;
	int64_t lcn;
	uint64_t resident_record_offset;
	uint64_t resident_value_offset;
	uint64_t physical_offset;
	uint64_t physical_length;
	unsigned char before;
	unsigned char after;
	unsigned char set_mask;
	unsigned char clear_mask;
	uint32_t evidence_version;
	unsigned char evidence_hash[32];
};

struct rh_index_bitmap_census {
	uint64_t generation;
	unsigned char census_hash[32];
	unsigned char tree_hash[32];
	unsigned char expected_hash[32];
	uint64_t mft_slots_expected;
	uint64_t mft_slots_completed;
	uint64_t directories_expected;
	uint64_t directories_completed;
	uint64_t indexes_expected;
	uint64_t indexes_completed;
	uint64_t index_entries_examined;
	uint64_t index_blocks_expected;
	uint64_t index_blocks_examined;
	uint64_t index_blocks_reachable;
	uint64_t child_vcns_examined;
	uint64_t bitmap_bits_examined;
	uint64_t unreadable_records;
	uint64_t ambiguous_attributes;
	uint64_t unresolved_blocks;
	uint64_t clear_bits_required;
	uint32_t failure_stage;
	struct rh_index_bitmap_change *changes;
	size_t change_count;
	size_t change_capacity;
	int complete;
	int index_tree_complete;
	int child_vcns_valid;
	int indx_blocks_valid;
	int reachable_set_exact;
	int sets_proven_reachable;
	int namespace_reciprocity_complete;
	int clears_proven_unreferenced;
	int targets_outside_wal;
	int set_only_safe;
	int clean;
};

struct rh_i30_edge_view {
	uint64_t parent_mft_record;
	uint16_t parent_sequence;
	uint64_t child_mft_record;
	uint16_t child_sequence;
	uint64_t indexed_file_reference;
	uint16_t entry_length;
	uint16_t key_length;
	uint16_t entry_flags;
	uint8_t name_namespace;
	uint8_t name_length;
	const unsigned char *name_utf16le;
	const unsigned char *file_name_value;
	uint8_t from_index_block;
	int64_t block_vcn;
};

typedef int (*rh_i30_edge_callback)(const struct rh_i30_edge_view *edge,
		void *opaque);

int rh_index_bitmap_census_run(ntfs_volume *volume, struct rh_writer *writer,
		uint64_t generation, struct rh_index_bitmap_census *census);
int rh_index_bitmap_census_run_edges(ntfs_volume *volume,
		struct rh_writer *writer, uint64_t generation,
		struct rh_index_bitmap_census *census,
		rh_i30_edge_callback callback, void *opaque);
/* Preferred readers consume the already assembled immutable raw census. */
int rh_index_bitmap_census_run_from_raw(ntfs_volume *volume,
		struct rh_writer *writer, const struct rh_raw_mft_census *raw,
		uint64_t generation, struct rh_index_bitmap_census *census);
int rh_index_bitmap_census_run_from_raw_reader(ntfs_volume *volume,
		const struct rh_census_reader *reader,
		const struct rh_raw_mft_census *raw, uint64_t generation,
		struct rh_index_bitmap_census *census);
int rh_index_bitmap_census_run_edges_from_raw(ntfs_volume *volume,
		struct rh_writer *writer, const struct rh_raw_mft_census *raw,
		uint64_t generation, struct rh_index_bitmap_census *census,
		rh_i30_edge_callback callback, void *opaque);
int rh_index_bitmap_census_run_edges_from_raw_reader(ntfs_volume *volume,
		const struct rh_census_reader *reader,
		const struct rh_raw_mft_census *raw, uint64_t generation,
		struct rh_index_bitmap_census *census,
		rh_i30_edge_callback callback, void *opaque);
void rh_index_bitmap_census_destroy(struct rh_index_bitmap_census *census);

/* Profile arithmetic has no historical 4,194,304-slot implementation cap. */
int rh_index_bitmap_slot_count_from_initialized(uint64_t initialized_size,
		uint32_t mft_record_size, uint64_t *slot_count);

#ifdef ROOTHEALTH_INDEX_BITMAP_TEST_HOOKS
int rh_index_bitmap_test_iterative_frames(uint64_t block_count,
		size_t frame_count);
#endif

/* The typed adapter consumes immutable census targets only. */
int rh_index_bitmap_stage(struct rh_ntfs_overlay *overlay,
		const struct rh_index_bitmap_census *census,
		size_t *first_operation_ordinal);
size_t rh_index_bitmap_next_batch_count(
		const struct rh_index_bitmap_census *census, size_t wal_capacity);
int rh_index_bitmap_stage_prefix(struct rh_ntfs_overlay *overlay,
		const struct rh_index_bitmap_census *census,
		size_t wal_capacity, size_t *staged_change_count,
		size_t *first_operation_ordinal);
int rh_index_bitmap_seal_policy(
		const struct rh_index_bitmap_census *initial,
		const struct rh_index_bitmap_census *final,
		const struct rh_writer *writer, size_t first_operation_ordinal,
		int identity_bound, int namespace_census_complete,
		struct rh_policy_evidence **evidence);

#endif
