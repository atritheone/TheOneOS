#ifndef ROOTHEALTH_RAW_MFT_H
#define ROOTHEALTH_RAW_MFT_H

#include <stddef.h>
#include <stdint.h>

struct _ntfs_volume;
struct rh_census_reader;
struct rh_writer;

enum rh_raw_slot_state {
	RH_RAW_SLOT_UNREADABLE = 0,
	RH_RAW_SLOT_FREE = 1,
	RH_RAW_SLOT_LIVE_BASE = 2,
	RH_RAW_SLOT_LIVE_EXTENT = 3,
	RH_RAW_SLOT_INVALID = 4,
	RH_RAW_SLOT_OPAQUE_FREE_CANDIDATE = 5,
};

enum rh_raw_layout_reason {
	RH_RAW_LAYOUT_RECORD_RESERVED = 1,
	RH_RAW_LAYOUT_RESIDENT_HEADER_RESERVED = 2,
	RH_RAW_LAYOUT_NONRESIDENT_HEADER_RESERVED = 3,
	RH_RAW_LAYOUT_ATTRIBUTE_NAME_PADDING = 4,
	RH_RAW_LAYOUT_ATTRIBUTE_VALUE_PADDING = 5,
	RH_RAW_LAYOUT_MAPPING_PAIRS_PADDING = 6,
	RH_RAW_LAYOUT_RECORD_END_PADDING = 7,
	RH_RAW_LAYOUT_BYTES_IN_USE = 8,
	RH_RAW_LAYOUT_BYTES_ALLOCATED = 9,
	RH_RAW_LAYOUT_NEXT_ATTRIBUTE_INSTANCE = 10,
	RH_RAW_LAYOUT_MFT_RECORD_NUMBER = 11,
};

struct rh_raw_mft_ref {
	uint64_t record;
	uint16_t sequence;
};

struct rh_raw_mft_slot {
	enum rh_raw_slot_state state;
	uint64_t record;
	uint16_t sequence;
	uint16_t flags;
	uint16_t link_count;
	uint16_t next_attribute_instance;
	struct rh_raw_mft_ref base;
	size_t attribute_first;
	size_t attribute_count;
	size_t file_name_first;
	size_t file_name_count;
	size_t owned_file_name_count;
	size_t list_entry_first;
	size_t list_entry_count;
	uint8_t has_attribute_list;
	uint8_t attribute_list_assembled;
};

struct rh_raw_run {
	uint64_t attribute_index;
	int64_t vcn;
	int64_t lcn;
	uint64_t length;
	uint8_t sparse;
};

struct rh_raw_attribute {
	struct rh_raw_mft_ref owner;
	struct rh_raw_mft_ref storage;
	uint32_t type;
	uint16_t instance;
	uint16_t flags;
	uint32_t record_offset;
	uint32_t record_length;
	uint16_t name_record_offset;
	uint16_t mapping_pairs_offset;
	size_t name_offset;
	uint16_t name_length;
	uint8_t nonresident;
	uint8_t compression_unit;
	uint8_t resident_flags;
	uint8_t resident_reserved;
	uint8_t list_claimed;
	uint8_t compression_unit_mismatch;
	uint8_t compressed_size_mismatch;
	int64_t lowest_vcn;
	int64_t highest_vcn;
	int64_t allocated_size;
	int64_t data_size;
	int64_t initialized_size;
	int64_t compressed_size;
	uint32_t value_offset;
	uint32_t value_length;
	size_t run_first;
	size_t run_count;
	size_t value_arena_offset;
	unsigned char value_hash[32];
	unsigned char mapping_hash[32];
};

struct rh_raw_layout_candidate {
	enum rh_raw_layout_reason reason;
	struct rh_raw_mft_ref owner;
	struct rh_raw_mft_ref storage;
	uint32_t attribute_type;
	uint16_t attribute_instance;
	uint32_t logical_offset;
	uint32_t length;
	unsigned char before_hash[32];
	unsigned char after_hash[32];
	unsigned char logical_record_before_hash[32];
	unsigned char logical_record_after_hash[32];
	uint8_t replacement_length;
	unsigned char replacement[4];
};

struct rh_raw_file_name {
	struct rh_raw_mft_ref owner;
	struct rh_raw_mft_ref storage;
	struct rh_raw_mft_ref parent;
	uint16_t attribute_instance;
	uint32_t record_value_offset;
	uint8_t name_namespace;
	uint8_t name_length;
	uint32_t value_length;
	size_t name_offset;
	size_t value_arena_offset;
	unsigned char value_hash[32];
	unsigned char logical_link_hash[32];
};

struct rh_raw_attr_list_entry {
	struct rh_raw_mft_ref owner;
	struct rh_raw_mft_ref storage;
	uint32_t type;
	int64_t lowest_vcn;
	uint16_t instance;
	uint8_t name_length;
	uint8_t matched;
	size_t matched_attribute;
	size_t name_offset;
};

struct rh_raw_opaque_slot_evidence {
	uint64_t record;
	unsigned char raw_before_hash[32];
};

struct rh_raw_mft_census {
	uint64_t generation;
	uint64_t slots_expected;
	uint64_t slots_completed;
	uint64_t live_base_records;
	uint64_t live_extent_records;
	uint64_t free_records;
	uint64_t unreadable_records;
	uint64_t invalid_records;
	uint64_t opaque_records;
	uint64_t resident_attributes;
	uint64_t nonresident_attributes;
	uint64_t user_defined_attributes;
	uint64_t extents_expected;
	uint64_t extents_completed;
	uint64_t runs_expected;
	uint64_t runs_completed;
	uint64_t attribute_lists;
	uint64_t attribute_list_entries;
	uint64_t file_name_links;
	uint64_t indexed_resident_attributes;
	uint64_t compressed_header_mismatches;
	uint8_t records_complete;
	uint8_t records_bounded;
	uint8_t layout_complete;
	uint8_t attribute_lists_complete;
	uint8_t extents_complete;
	uint8_t opaque_slots_complete;
	uint8_t compressed_header_tolerant;
	struct rh_raw_opaque_slot_evidence *opaque_slots;
	size_t opaque_slot_count;
	size_t opaque_slot_capacity;
	struct rh_raw_mft_slot *slots;
	size_t slot_count;
	struct rh_raw_attribute *attributes;
	size_t attribute_count;
	size_t attribute_capacity;
	struct rh_raw_run *runs;
	size_t run_count;
	size_t run_capacity;
	struct rh_raw_file_name *file_names;
	size_t file_name_count;
	size_t file_name_capacity;
	struct rh_raw_attr_list_entry *list_entries;
	size_t list_entry_count;
	size_t list_entry_capacity;
	struct rh_raw_layout_candidate *layout_candidates;
	size_t layout_candidate_count;
	size_t layout_candidate_capacity;
	unsigned char *name_arena;
	size_t name_arena_size;
	size_t name_arena_capacity;
	unsigned char *value_arena;
	size_t value_arena_size;
	size_t value_arena_capacity;
	unsigned char slot_hash[32];
	unsigned char attribute_hash[32];
	unsigned char attrlist_hash[32];
	unsigned char run_hash[32];
	unsigned char file_name_manifest_hash[32];
	unsigned char layout_hash[32];
	unsigned char census_hash[32];
};

int rh_raw_mft_census_run(struct _ntfs_volume *volume,
		struct rh_writer *writer, uint64_t generation,
		struct rh_raw_mft_census *census);
int rh_raw_mft_census_run_reader(struct _ntfs_volume *volume,
		const struct rh_census_reader *reader, uint64_t generation,
		struct rh_raw_mft_census *census);
/*
 * Compressed-header diagnosis needs a bounded run/extent census even when the
 * compression-unit or base compressed-size cache is wrong.  This entrypoint
 * tolerates only those two derivable fields, marks every mismatch, and keeps
 * records_complete/layout_complete false until a clean staged rescan.
 */
int rh_raw_mft_census_run_reader_compressed_headers(
		struct _ntfs_volume *volume, const struct rh_census_reader *reader,
		uint64_t generation, struct rh_raw_mft_census *census);
/*
 * Native op2 targets are selected atomically by the log before the census.
 * Their sorted unique records and exact 1024-byte preimages are opaque; every
 * other record is fully parsed.  Bitmap and reference censuses must prove each
 * target free, and the writer must still be at pretransaction checkpoint zero.
 */
int rh_raw_mft_census_run_with_opaque_slots(struct _ntfs_volume *volume,
		struct rh_writer *writer, uint64_t generation,
		const uint64_t *opaque_records, size_t opaque_record_count,
		struct rh_raw_mft_census *census);
int rh_raw_mft_census_run_with_opaque_slots_reader(
		struct _ntfs_volume *volume, const struct rh_census_reader *reader,
		uint64_t generation, const uint64_t *opaque_records,
		size_t opaque_record_count, struct rh_raw_mft_census *census);
int rh_raw_mft_census_run_with_opaque_slot(struct _ntfs_volume *volume,
		struct rh_writer *writer, uint64_t generation, uint64_t opaque_record,
		struct rh_raw_mft_census *census);
int rh_raw_mft_slot_count_from_size(uint64_t initialized_size,
		uint32_t record_size, size_t *slot_count);
int rh_raw_mft_map_stream_range(const struct rh_raw_mft_census *census,
		struct rh_raw_mft_ref owner, uint32_t type,
		const unsigned char *name_utf16le, uint16_t name_length,
		uint64_t logical_offset, uint64_t length, uint64_t *physical_offset);
int rh_raw_mft_stream_pread(struct rh_writer *writer,
		const struct rh_raw_mft_census *census,
		struct rh_raw_mft_ref owner, uint32_t type,
		const unsigned char *name_utf16le, uint16_t name_length,
		uint64_t logical_offset, size_t length, unsigned char *buffer);
int rh_raw_mft_stream_pread_reader(const struct rh_census_reader *reader,
		const struct rh_raw_mft_census *census,
		struct rh_raw_mft_ref owner, uint32_t type,
		const unsigned char *name_utf16le, uint16_t name_length,
		uint64_t logical_offset, size_t length, unsigned char *buffer);
void rh_raw_mft_census_release(struct rh_raw_mft_census *census);

#endif
