#ifndef ROOTHEALTH_FIXED_METADATA_READER_H
#define ROOTHEALTH_FIXED_METADATA_READER_H

#include <stdint.h>

struct rh_census_reader;
struct rh_raw_mft_census;

#define RH_FIXED_METADATA_READER_VERSION UINT32_C(1)
#define RH_FIXED_METADATA_READER_ENTRY_COUNT UINT64_C(2)
#define RH_FIXED_METADATA_ATTRDEF_SIZE UINT64_C(2560)
#define RH_FIXED_METADATA_UPCASE_SIZE UINT64_C(131072)

#define RH_FIXED_METADATA_ATTRDEF_SHA256 \
	"d7de5b1b2f79f45f235ceb1adbc46908ed64eae174eb90ed66aefe5f25165da3"
#define RH_FIXED_METADATA_UPCASE_SHA256 \
	"41c26bc7a12bdaeb26025c93118697c7e3ef81ee048b00fe5cce2a472e0e0742"

enum rh_fixed_metadata_reader_kind {
	RH_FIXED_METADATA_READER_ATTRDEF = 1,
	RH_FIXED_METADATA_READER_UPCASE = 2,
};

/* A mismatch is evidence, not a constructor error.  IO is kept distinct. */
enum rh_fixed_metadata_reader_state {
	RH_FIXED_METADATA_READER_UNAVAILABLE = 0,
	RH_FIXED_METADATA_READER_PASS = 1,
	RH_FIXED_METADATA_READER_FAIL = 2,
	RH_FIXED_METADATA_READER_IO = 3,
};

struct rh_fixed_metadata_reader_entry {
	enum rh_fixed_metadata_reader_kind kind;
	enum rh_fixed_metadata_reader_state state;
	uint64_t owner_record;
	uint16_t owner_sequence;
	uint16_t attribute_instance;
	uint64_t expected_size;
	uint64_t data_size;
	uint64_t initialized_size;
	uint64_t allocated_size;
	uint64_t extents_examined;
	uint64_t runs_examined;
	uint64_t bytes_examined;
	unsigned char canonical_hash[32];
	unsigned char current_hash[32];
	unsigned char mapping_hash[32];
	unsigned char evidence_hash[32];
	uint8_t current_hash_valid;
	uint8_t mapping_complete;
};

/*
 * Source-owned, read-only census output.  Entry zero is $AttrDef (record 4)
 * and entry one is $UpCase (record 10).  complete means both roles reached a
 * terminal PASS/FAIL/IO state; it does not mean that either role passed.
 */
struct rh_fixed_metadata_reader_census {
	uint32_t version;
	uint64_t generation;
	uint64_t volume_serial;
	uint64_t entries_expected;
	uint64_t entries_completed;
	uint64_t entries_passed;
	uint64_t entries_failed;
	uint64_t entries_io;
	unsigned char raw_census_hash[32];
	struct rh_fixed_metadata_reader_entry entries[2];
	unsigned char evidence_hash[32];
	uint8_t complete;
	uint8_t no_io_uncertainty;
};

/*
 * Examine the exact unnamed nonresident DATA streams owned by records 4 and
 * 10 from an already assembled raw census.  The function never stages or
 * writes.  Invalid arguments/source census return -1; content mismatch and
 * source IO return zero with per-entry terminal states.
 */
int rh_fixed_metadata_reader_census_run(
		const struct rh_census_reader *reader,
		const struct rh_raw_mft_census *raw,
		struct rh_fixed_metadata_reader_census *census);

#endif
