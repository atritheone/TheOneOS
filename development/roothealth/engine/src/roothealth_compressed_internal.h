#ifndef ROOTHEALTH_COMPRESSED_INTERNAL_H
#define ROOTHEALTH_COMPRESSED_INTERNAL_H

#include "roothealth_compressed.h"

#define RH_COMPRESSED_CENSUS_MAGIC UINT64_C(0x5248434f4d505231)

struct rh_compressed_record_target {
	uint64_t record;
	uint16_t sequence;
	uint64_t physical_offset;
	unsigned char logical_before[1024];
	unsigned char logical_after[1024];
	unsigned char before_hash[32];
	unsigned char after_hash[32];
};

struct rh_compressed_census {
	uint64_t magic;
	uint32_t version;
	uint64_t generation;
	uint64_t streams_expected;
	uint64_t streams_examined;
	uint64_t resident_streams;
	uint64_t nonresident_streams;
	uint64_t units_expected;
	uint64_t units_examined;
	uint64_t sparse_units;
	uint64_t compressed_units;
	uint64_t uncompressed_units;
	uint64_t physical_clusters;
	uint64_t sparse_clusters;
	uint64_t initialized_bytes;
	uint64_t data_bytes;
	uint64_t si_compressed_records;
	uint64_t si_compressed_directories;
	uint64_t si_compressed_intent_only_files;
	uint64_t compressed_stream_owners;
	uint64_t payload_invalid;
	uint64_t payload_ambiguous;
	uint64_t topology_invalid;
	uint64_t header_fields_mismatched;
	uint8_t raw_complete;
	uint8_t census_complete;
	uint8_t payloads_valid;
	uint8_t repair_authority_complete;
	uint8_t clean;
	uint8_t no_io_uncertainty;
	uint8_t si_data_reconciled;
	struct rh_compressed_record_target *targets;
	size_t target_count;
	size_t target_capacity;
	unsigned char raw_census_hash[32];
	unsigned char unit_manifest_hash[32];
	unsigned char repair_manifest_hash[32];
	unsigned char census_hash[32];
};

int rh_compressed_census_internal_valid(
		const struct rh_compressed_census *census);

#ifdef ROOTHEALTH_REPAIR_TESTING
int rh_compressed_test_lznt1(unsigned char *destination,
		size_t destination_size, const unsigned char *source,
		size_t source_size);
#endif

#endif
