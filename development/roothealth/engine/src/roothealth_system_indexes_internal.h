#ifndef ROOTHEALTH_SYSTEM_INDEXES_INTERNAL_H
#define ROOTHEALTH_SYSTEM_INDEXES_INTERNAL_H

#include <stdint.h>

struct rh_census_reader;
struct rh_namespace_census;
struct rh_raw_mft_census;
struct rh_system_index_census;
struct _ntfs_volume;

/* Owned exclusively by the immutable common-census publisher. */
int rh_system_index_census_run_internal(
		const struct rh_census_reader *reader, struct _ntfs_volume *volume,
		const struct rh_raw_mft_census *raw,
		const struct rh_namespace_census *namespace_census,
		uint64_t generation, struct rh_system_index_census **output);
void rh_system_index_census_destroy_internal(
		struct rh_system_index_census *census);

#endif
