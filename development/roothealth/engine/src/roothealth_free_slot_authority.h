#ifndef ROOTHEALTH_FREE_SLOT_AUTHORITY_H
#define ROOTHEALTH_FREE_SLOT_AUTHORITY_H

#include <stddef.h>
#include <stdint.h>

struct rh_writer;
struct rh_census_reader;
struct rh_raw_mft_census;
struct rh_mft_bitmap_census;
struct rh_namespace_census;

#define RH_FREE_SLOT_AUTHORITY_VERSION UINT32_C(1)
#define RH_FREE_SLOT_RAW_RECORD_SIZE UINT32_C(1024)

enum rh_free_slot_component_kind {
	RH_FREE_SLOT_COMPONENT_INVALID = 0,
	RH_FREE_SLOT_COMPONENT_NATIVE_OPEN_ATTRIBUTE = 1,
	RH_FREE_SLOT_COMPONENT_NATIVE_TARGET = 2,
	RH_FREE_SLOT_COMPONENT_NATIVE_CONTROL = 3,
	RH_FREE_SLOT_COMPONENT_REPARSE = 4,
	RH_FREE_SLOT_COMPONENT_OBJID = 5,
	RH_FREE_SLOT_COMPONENT_RECOVERY_NAMESPACE = 6,
	RH_FREE_SLOT_COMPONENT_WAL_EXCLUSIONS = 7,
	RH_FREE_SLOT_COMPONENT_USN_FIXED_SYSTEM = 8,
	RH_FREE_SLOT_COMPONENT_COUNT = 9
};

enum rh_free_slot_usn_state {
	RH_FREE_SLOT_USN_UNKNOWN = 0,
	RH_FREE_SLOT_USN_ABSENT = 1,
	RH_FREE_SLOT_USN_PRESENT = 2,
};

#define RH_FREE_SLOT_REQUIRED_COMPONENTS \
	((size_t)RH_FREE_SLOT_COMPONENT_COUNT - 1U)

struct rh_free_slot_reference {
	uint64_t record;
	uint16_t sequence;
};

struct rh_free_slot_range {
	uint64_t offset;
	uint64_t length;
};

struct rh_free_slot_component_seal;
struct rh_free_slot_authority;

/*
 * Component seals are opaque completed-pass products.  Production seals must
 * be returned by typed constructors owned by the corresponding completed
 * census; a caller cannot assert completion by supplying booleans or counts.
 * The generic constructor exists only for isolated synthetic tests while the
 * typed census adapters are being added.  WAL_EXCLUSIONS is the only range
 * component; every other component contains references only.
 */
#ifdef ROOTHEALTH_REPAIR_TESTING
int rh_free_slot_test_component_seal_create(
		enum rh_free_slot_component_kind kind, uint64_t correlation_generation,
		uint64_t items_expected, uint64_t items_completed,
		const unsigned char source_census_hash[32],
		const struct rh_free_slot_reference *references,
		size_t reference_count, const struct rh_free_slot_range *ranges,
		size_t range_count, struct rh_free_slot_component_seal **output);
#endif
void rh_free_slot_component_seal_destroy(
		struct rh_free_slot_component_seal *seal);
enum rh_free_slot_component_kind rh_free_slot_component_seal_kind(
		const struct rh_free_slot_component_seal *seal);
int rh_free_slot_component_seal_hash(
		const struct rh_free_slot_component_seal *seal,
		unsigned char output[32]);

struct rh_free_slot_authority_view {
	uint32_t version;
	uint64_t correlation_generation;
	uint64_t target_record;
	uint16_t intended_sequence;
	uint16_t observed_slot_sequence;
	uint64_t physical_offset;
	uint64_t physical_length;
	uint64_t mft_bitmap_physical_offset;
	uint64_t device_size;
	uint64_t slots_examined;
	uint64_t attributes_examined;
	uint64_t runs_examined;
	uint64_t attribute_list_entries_examined;
	uint64_t file_name_links_examined;
	uint64_t i30_edges_examined;
	uint64_t explicit_references_examined;
	uint64_t total_references_examined;
	uint64_t references_matched;
	uint64_t extent_references_matched;
	uint64_t allocation_owners_matched;
	uint64_t owned_runs_matched;
	uint64_t wal_ranges_examined;
	uint64_t wal_raw_ranges_examined;
	uint64_t wal_overlaps_matched;
	uint8_t bitmap_mask;
	uint8_t observed_bitmap_byte;
	uint8_t expected_bitmap_byte;
	unsigned char raw_before_hash[32];
	unsigned char raw_census_hash[32];
	unsigned char mft_bitmap_census_hash[32];
	unsigned char namespace_census_hash[32];
	unsigned char writer_exclusion_hash[32];
	unsigned char component_source_hashes[RH_FREE_SLOT_COMPONENT_COUNT][32];
	unsigned char component_hashes[RH_FREE_SLOT_COMPONENT_COUNT][32];
	unsigned char evidence_hash[32];
};

int rh_free_slot_authority_create(struct rh_writer *writer,
		const struct rh_raw_mft_census *raw,
		const struct rh_mft_bitmap_census *mft_bitmap,
		const struct rh_namespace_census *namespace_census,
		uint64_t correlation_generation, uint64_t target_record,
		uint16_t intended_sequence,
		const struct rh_free_slot_component_seal *const *components,
		size_t component_count, struct rh_free_slot_authority **output);
void rh_free_slot_authority_destroy(struct rh_free_slot_authority *authority);
int rh_free_slot_authority_get_view(
		const struct rh_free_slot_authority *authority,
		struct rh_free_slot_authority_view *view);

/* Equality intentionally ignores correlation generation. */
int rh_free_slot_authority_equal(const struct rh_free_slot_authority *left,
		const struct rh_free_slot_authority *right);
int rh_free_slot_authority_rederive_equal(
		const struct rh_free_slot_authority *expected,
		struct rh_writer *writer, const struct rh_raw_mft_census *raw,
		const struct rh_mft_bitmap_census *mft_bitmap,
		const struct rh_namespace_census *namespace_census,
		uint64_t correlation_generation, uint64_t target_record,
		uint16_t intended_sequence,
		const struct rh_free_slot_component_seal *const *components,
		size_t component_count, int *equal);
/* Recovery can compare directly with the evidence hash persisted in WAL. */
int rh_free_slot_authority_rederive_evidence_equal(
		const unsigned char expected_evidence_hash[32],
		struct rh_writer *writer, const struct rh_raw_mft_census *raw,
		const struct rh_mft_bitmap_census *mft_bitmap,
		const struct rh_namespace_census *namespace_census,
		uint64_t correlation_generation, uint64_t target_record,
		uint16_t intended_sequence,
		const struct rh_free_slot_component_seal *const *components,
		size_t component_count, int *equal);
/* Recovery uses the immutable WAL-preimage reader and no mutable writer. */
int rh_free_slot_authority_rederive_evidence_equal_reader(
		const unsigned char expected_evidence_hash[32],
		const struct rh_census_reader *reader,
		const struct rh_raw_mft_census *raw,
		const struct rh_mft_bitmap_census *mft_bitmap,
		const struct rh_namespace_census *namespace_census,
		uint64_t correlation_generation, uint64_t target_record,
		uint16_t intended_sequence,
		const struct rh_free_slot_component_seal *const *components,
		size_t component_count, int *equal);

#endif
