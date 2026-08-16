#ifndef ROOTHEALTH_COMPLETE_CENSUS_H
#define ROOTHEALTH_COMPLETE_CENSUS_H

#include <stddef.h>
#include <stdint.h>

#include "roothealth_bitmap.h"
#include "roothealth_compressed.h"
#include "roothealth_coverage.h"
#include "roothealth_fixed_metadata_reader.h"
#include "roothealth_index_bitmap.h"
#include "roothealth_mft_bitmap.h"
#include "roothealth_namespace.h"
#include "roothealth_raw_mft.h"

#define RH_COMPLETE_CENSUS_VERSION 1U
#define RH_COMPLETE_CENSUS_FIXED_CHECK_COUNT 17U
/* 17 fixed checks plus metadata-index, Secure, Reparse and compressed passes. */
#define RH_COMPLETE_CENSUS_PARTIAL_SKIPPED 21U

struct rh_census_reader;
struct rh_recovery_namespace_authority_census;
struct rh_system_index_census;
struct rh_usn_fixed_system_authority_census;
struct rh_secure_census_provider;

struct rh_complete_census_profile {
	uint64_t expected_volume_serial;
	uint64_t roothealth_record;
	uint16_t roothealth_sequence;
	uint8_t require_t1os_identity;
	/* Sorted unique native-op2 targets; requires a pretransaction reader. */
	const uint64_t *opaque_records;
	size_t opaque_record_count;
};

/*
 * One immutable read-only view.  The current publisher deliberately remains
 * partial until typed metadata-index, Secure, Reparse, compressed-stream and
 * fixed-system providers are merged.  Those sections are null/SKIPPED and can
 * never authorize a policy predicate or a clean verdict.
 */
struct rh_complete_census {
	uint32_t version;
	uint64_t generation;
	uint64_t volume_serial;
	struct rh_raw_mft_census raw;
	struct rh_namespace_census namespace_census;
	struct rh_index_bitmap_census index_bitmap;
	struct rh_mft_bitmap_census mft_bitmap;
	struct rh_cluster_bitmap_census cluster_bitmap;
	struct rh_coverage_ledger coverage;
	struct rh_fixed_check fixed_checks[RH_COMPLETE_CENSUS_FIXED_CHECK_COUNT];
	struct rh_system_index_census *system_index_authority;
	struct rh_recovery_namespace_authority_census *
		recovery_namespace_authority;
	struct rh_usn_fixed_system_authority_census *usn_fixed_system_authority;
	struct rh_fixed_metadata_reader_census fixed_metadata;
	struct rh_secure_census_provider *secure_provider;
	struct rh_compressed_census *compressed_provider;
	unsigned char fixed_manifest_hash[32];
	unsigned char coverage_hash[32];
	unsigned char census_hash[32];
	uint32_t core_fixed_checked_mask;
	uint32_t core_fixed_valid_mask;
	uint32_t core_fixed_io_mask;
	uint8_t read_passes_complete;
	uint8_t providers_complete;
	uint8_t identity_matches;
};

int rh_complete_census_run(const struct rh_census_reader *reader,
		const struct rh_complete_census_profile *profile,
		uint64_t generation, struct rh_complete_census *census);
int rh_complete_census_outputs_equal(const struct rh_complete_census *left,
		const struct rh_complete_census *right);
void rh_complete_census_release(struct rh_complete_census *census);

#endif
