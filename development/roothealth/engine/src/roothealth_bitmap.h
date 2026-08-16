#ifndef ROOTHEALTH_BITMAP_H
#define ROOTHEALTH_BITMAP_H

#include <stddef.h>
#include <stdint.h>

#include "roothealth_overlay.h"
#include "roothealth_policy.h"

struct rh_raw_mft_census;
struct rh_census_reader;

/* One v1 WAL transaction capacity; a complete census may exceed this. */
#define RH_BITMAP_MAX_CHANGES 4094U

struct rh_cluster_bitmap_change {
	uint64_t logical_offset;
	uint64_t logical_vcn;
	uint64_t lcn;
	uint64_t physical_offset;
	unsigned char before;
	unsigned char after;
	unsigned char set_mask;
	unsigned char clear_mask;
};

struct rh_cluster_bitmap_census {
	uint64_t generation;
	unsigned char census_hash[32];
	unsigned char allocation_hash[32];
	uint64_t cluster_count;
	uint64_t bitmap_bits_examined;
	uint64_t mft_slots_expected;
	uint64_t mft_slots_completed;
	uint64_t mft_slots_in_use;
	uint64_t mft_slots_free;
	uint64_t attributes_examined;
	uint64_t nonresident_extents_examined;
	uint64_t runs_examined;
	uint64_t clusters_owned;
	uint64_t duplicate_clusters;
	uint64_t unreadable_slots;
	uint16_t bitmap_sequence;
	uint16_t bitmap_attribute_instance;
	unsigned char *expected_bitmap;
	unsigned char *observed_bitmap;
	size_t bitmap_bytes;
	struct rh_cluster_bitmap_change *changes;
	size_t change_count;
	size_t change_capacity;
	int complete;
	int structurally_valid;
	int ownership_exact;
	int targets_outside_wal;
	int clean;
};

int rh_cluster_bitmap_census_run(ntfs_volume *volume,
		struct rh_writer *writer, uint64_t generation,
		struct rh_cluster_bitmap_census *census);
/* Preferred integrated path: reuse the already assembled raw-MFT census. */
int rh_cluster_bitmap_census_run_from_raw(ntfs_volume *volume,
		struct rh_writer *writer, uint64_t generation,
		const struct rh_raw_mft_census *raw,
		struct rh_cluster_bitmap_census *census);
int rh_cluster_bitmap_census_run_from_raw_reader(ntfs_volume *volume,
		const struct rh_census_reader *reader, uint64_t generation,
		const struct rh_raw_mft_census *raw,
		struct rh_cluster_bitmap_census *census);
void rh_cluster_bitmap_census_destroy(
		struct rh_cluster_bitmap_census *census);

/* This function is implemented only in the typed-WAL adapter translation unit. */
int rh_cluster_bitmap_stage(struct rh_ntfs_overlay *overlay,
		const struct rh_cluster_bitmap_census *census,
		size_t *first_operation_ordinal);
size_t rh_cluster_bitmap_next_batch_count(
		const struct rh_cluster_bitmap_census *census, size_t wal_capacity);
int rh_cluster_bitmap_stage_prefix(struct rh_ntfs_overlay *overlay,
		const struct rh_cluster_bitmap_census *census, size_t wal_capacity,
		size_t *staged_change_count, size_t *first_operation_ordinal);

int rh_cluster_bitmap_seal_policy(
		const struct rh_cluster_bitmap_census *initial,
		const struct rh_cluster_bitmap_census *final,
		const struct rh_writer *writer, size_t first_operation_ordinal,
		int identity_bound, struct rh_policy_evidence **evidence);

#endif
