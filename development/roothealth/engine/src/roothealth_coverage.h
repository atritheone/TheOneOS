#ifndef ROOTHEALTH_COVERAGE_H
#define ROOTHEALTH_COVERAGE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define RH_COVERAGE_FORMAT 3U
#define RH_COVERAGE_COUNTER_COUNT 60U

struct rh_coverage_counter {
	bool known;
	uint64_t value;
};

enum rh_fixed_check_result {
	RH_FIXED_CHECK_PASS = 1,
	RH_FIXED_CHECK_FAIL = 2,
	RH_FIXED_CHECK_UNREADABLE = 3,
	RH_FIXED_CHECK_SKIPPED = 4,
};

struct rh_fixed_check {
	const char *id;
	enum rh_fixed_check_result result;
};

struct rh_coverage_mft_slots {
	struct rh_coverage_counter expected;
	struct rh_coverage_counter completed;
	struct rh_coverage_counter live;
	struct rh_coverage_counter free;
	struct rh_coverage_counter unreadable;
	struct rh_coverage_counter invalid;
};

struct rh_coverage_attributes {
	struct rh_coverage_counter expected;
	struct rh_coverage_counter completed;
	struct rh_coverage_counter resident;
	struct rh_coverage_counter nonresident;
	struct rh_coverage_counter user_defined;
	struct rh_coverage_counter extents_expected;
	struct rh_coverage_counter extents_completed;
	struct rh_coverage_counter runs_expected;
	struct rh_coverage_counter runs_completed;
	struct rh_coverage_counter unreadable;
	struct rh_coverage_counter skipped;
};

struct rh_coverage_namespace_links {
	struct rh_coverage_counter expected;
	struct rh_coverage_counter completed;
	struct rh_coverage_counter reciprocal;
	struct rh_coverage_counter unresolved;
	struct rh_coverage_counter unreadable;
};

struct rh_coverage_indexes {
	struct rh_coverage_counter expected;
	struct rh_coverage_counter completed;
	struct rh_coverage_counter blocks_allocated;
	struct rh_coverage_counter blocks_reachable;
	struct rh_coverage_counter blocks_examined;
	struct rh_coverage_counter blocks_unreadable;
	struct rh_coverage_counter bitmap_bits_expected;
	struct rh_coverage_counter bitmap_bits_examined;
};

struct rh_coverage_bitmaps {
	struct rh_coverage_counter mft_bits_expected;
	struct rh_coverage_counter mft_bits_examined;
	struct rh_coverage_counter cluster_bits_expected;
	struct rh_coverage_counter cluster_bits_examined;
	struct rh_coverage_counter differences;
};

struct rh_coverage_security {
	struct rh_coverage_counter ids_expected;
	struct rh_coverage_counter ids_examined;
	struct rh_coverage_counter descriptors_expected;
	struct rh_coverage_counter descriptors_examined;
	struct rh_coverage_counter sds_entries_expected;
	struct rh_coverage_counter sds_entries_examined;
	struct rh_coverage_counter sdh_entries_expected;
	struct rh_coverage_counter sdh_entries_examined;
	struct rh_coverage_counter sii_entries_expected;
	struct rh_coverage_counter sii_entries_examined;
	struct rh_coverage_counter unreadable;
};

struct rh_coverage_reparse {
	struct rh_coverage_counter attributes_expected;
	struct rh_coverage_counter attributes_examined;
	struct rh_coverage_counter index_entries_expected;
	struct rh_coverage_counter index_entries_examined;
	struct rh_coverage_counter unresolved;
	struct rh_coverage_counter unreadable;
};

struct rh_coverage_compressed {
	struct rh_coverage_counter units_expected;
	struct rh_coverage_counter units_examined;
	struct rh_coverage_counter unreadable;
};

struct rh_coverage_fixed_system {
	struct rh_coverage_counter expected;
	struct rh_coverage_counter completed;
	struct rh_coverage_counter failed;
	const struct rh_fixed_check *checks;
	size_t check_count;
};

struct rh_coverage_ledger {
	bool complete;
	struct rh_coverage_counter io_errors;
	struct rh_coverage_counter skipped;
	struct rh_coverage_mft_slots mft_slots;
	struct rh_coverage_attributes attributes;
	struct rh_coverage_namespace_links namespace_links;
	struct rh_coverage_indexes indexes;
	struct rh_coverage_bitmaps bitmaps;
	struct rh_coverage_security security;
	struct rh_coverage_reparse reparse;
	struct rh_coverage_compressed compressed;
	struct rh_coverage_fixed_system fixed_system;
};

int rh_coverage_hash(const struct rh_coverage_ledger *ledger,
		unsigned char output[32]);
bool rh_coverage_is_clean(const struct rh_coverage_ledger *ledger);
size_t rh_coverage_required_fixed_check_count(void);
const char *rh_coverage_required_fixed_check_id(size_t index);

#endif
