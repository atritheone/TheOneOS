#ifndef ROOTHEALTH_MFT_BITMAP_H
#define ROOTHEALTH_MFT_BITMAP_H

#include <stddef.h>
#include <stdint.h>

#include "roothealth_overlay.h"
#include "roothealth_policy.h"

struct rh_raw_mft_census;
struct rh_census_reader;
struct rh_complete_census;

/* One v1 WAL transaction capacity; a complete census may exceed this. */
#define RH_MFT_BITMAP_MAX_CHANGES 4094U
#define RH_MFT_BITMAP_NO_ROOTHEALTH UINT64_MAX

struct rh_mft_bitmap_change {
	uint64_t logical_offset;
	uint64_t logical_vcn;
	uint64_t lcn;
	uint64_t physical_offset;
	unsigned char before;
	unsigned char after;
	unsigned char set_mask;
	unsigned char clear_mask;
};

struct rh_mft_bitmap_slot_evidence;
struct rh_mft_bitmap_full_ledger_seal;

struct rh_mft_bitmap_census {
	uint64_t generation;
	unsigned char census_hash[32];
	unsigned char expected_hash[32];
	uint64_t mft_slots_expected;
	uint64_t mft_slots_completed;
	uint64_t mft_slots_in_use;
	uint64_t mft_slots_free;
	uint64_t bitmap_bits_examined;
	uint64_t padding_bits_examined;
	uint64_t attributes_examined;
	uint64_t nonresident_extents_examined;
	uint64_t mapping_runs_examined;
	uint64_t unreadable_slots;
	uint64_t ambiguous_slots;
	uint16_t mft_sequence;
	uint16_t bitmap_attribute_instance;
	uint64_t roothealth_record;
	uint16_t roothealth_sequence;
	int roothealth_record_bound;
	int roothealth_bitmap_bit_set;
	int roothealth_false_free_obligation;
	unsigned char *expected_bitmap;
	unsigned char *observed_bitmap;
	size_t bitmap_bytes;
	struct rh_mft_bitmap_slot_evidence *slots;
	struct rh_mft_bitmap_change *changes;
	size_t change_count;
	size_t change_capacity;
	int complete;
	int structurally_valid;
	int targets_outside_wal;
	int sets_proven_live;
	/*
	 * Structural freedom is not namespace freedom.  This remains false until
	 * the integrated ledger proves there is no parent-index or attribute-list
	 * reference.  A mandatory future fixture is a free FILE header whose bit is
	 * set while a live parent $I30 entry still references it.
	 */
	int clears_structurally_free;
	int clears_proven_unreferenced;
	int clean;
};

int rh_mft_bitmap_census_run(ntfs_volume *volume, struct rh_writer *writer,
		uint64_t generation, uint64_t roothealth_record,
		uint16_t roothealth_sequence, struct rh_mft_bitmap_census *census);
/* Preferred integrated path: reuse the already assembled raw-MFT census. */
int rh_mft_bitmap_census_run_from_raw(ntfs_volume *volume,
		struct rh_writer *writer, uint64_t generation,
		uint64_t roothealth_record, uint16_t roothealth_sequence,
		const struct rh_raw_mft_census *raw,
		struct rh_mft_bitmap_census *census);
int rh_mft_bitmap_census_run_from_raw_reader(ntfs_volume *volume,
		const struct rh_census_reader *reader, uint64_t generation,
		uint64_t roothealth_record, uint16_t roothealth_sequence,
		const struct rh_raw_mft_census *raw,
		struct rh_mft_bitmap_census *census);
void rh_mft_bitmap_census_destroy(struct rh_mft_bitmap_census *census);

/* Implemented only by the typed-WAL adapter translation unit. */
int rh_mft_bitmap_stage(struct rh_ntfs_overlay *overlay,
		const struct rh_mft_bitmap_census *census,
		size_t *first_operation_ordinal);
size_t rh_mft_bitmap_next_batch_count(
		const struct rh_mft_bitmap_census *census, size_t wal_capacity);
int rh_mft_bitmap_stage_prefix(struct rh_ntfs_overlay *overlay,
		const struct rh_mft_bitmap_census *census, size_t wal_capacity,
		size_t *staged_change_count, size_t *first_operation_ordinal);

int rh_mft_bitmap_seal_policy(const struct rh_mft_bitmap_census *initial,
		const struct rh_mft_bitmap_census *final,
		const struct rh_writer *writer, size_t first_operation_ordinal,
		int identity_bound, int namespace_census_complete,
		const struct rh_mft_bitmap_full_ledger_seal *full_ledger_seal,
		struct rh_policy_evidence **evidence);
int rh_mft_bitmap_full_ledger_seal_create(
		const struct rh_complete_census *initial,
		const struct rh_complete_census *final,
		struct rh_mft_bitmap_full_ledger_seal **seal);
void rh_mft_bitmap_full_ledger_seal_destroy(
		struct rh_mft_bitmap_full_ledger_seal *seal);

#endif
