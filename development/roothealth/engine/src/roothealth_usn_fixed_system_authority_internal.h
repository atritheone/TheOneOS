#ifndef ROOTHEALTH_USN_FIXED_SYSTEM_AUTHORITY_INTERNAL_H
#define ROOTHEALTH_USN_FIXED_SYSTEM_AUTHORITY_INTERNAL_H

#include <stdint.h>

struct rh_census_reader;
struct rh_mft_bitmap_census;
struct rh_namespace_census;
struct rh_raw_mft_census;
struct rh_usn_fixed_system_authority_census;

/* Owned exclusively by the immutable common-census publisher. */
int rh_usn_fixed_system_authority_census_run(
		const struct rh_census_reader *reader, uint64_t volume_serial,
		uint64_t generation, const struct rh_raw_mft_census *raw,
		const struct rh_namespace_census *namespace_census,
		const struct rh_mft_bitmap_census *mft_bitmap,
		struct rh_usn_fixed_system_authority_census **output);
void rh_usn_fixed_system_authority_census_destroy(
		struct rh_usn_fixed_system_authority_census *census);

#endif
