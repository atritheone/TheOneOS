#ifndef ROOTHEALTH_COMPRESSED_H
#define ROOTHEALTH_COMPRESSED_H

#include <stddef.h>
#include <stdint.h>

#include "roothealth_census_device.h"
#include "roothealth_raw_mft.h"

struct _ntfs_volume;
struct rh_compressed_census;

#define RH_COMPRESSED_CENSUS_VERSION UINT32_C(1)
#define RH_COMPRESSED_UNIT_CLUSTERS UINT32_C(16)
#define RH_COMPRESSED_UNIT_BYTES UINT32_C(65536)

struct rh_compressed_census_view {
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
	uint64_t repair_record_count;
	uint8_t raw_complete;
	uint8_t census_complete;
	uint8_t payloads_valid;
	uint8_t repair_authority_complete;
	uint8_t clean;
	uint8_t no_io_uncertainty;
	uint8_t si_data_reconciled;
	unsigned char raw_census_hash[32];
	unsigned char unit_manifest_hash[32];
	unsigned char repair_manifest_hash[32];
	unsigned char census_hash[32];
};

/*
 * The reader and mounted volume must describe the same immutable view used to
 * build the tolerant raw census.  The common reader ABI has no identity token;
 * the integration ledger remains responsible for binding that relationship.
 */
int rh_compressed_census_run(const struct rh_census_reader *reader,
		struct _ntfs_volume *volume, const struct rh_raw_mft_census *raw,
		uint64_t generation, struct rh_compressed_census **output);
void rh_compressed_census_destroy(struct rh_compressed_census *census);
int rh_compressed_census_get_view(const struct rh_compressed_census *census,
		struct rh_compressed_census_view *view);

#endif
