#ifndef ROOTHEALTH_SECURE_CENSUS_PROVIDER_H
#define ROOTHEALTH_SECURE_CENSUS_PROVIDER_H

#include <stdint.h>

struct rh_census_reader;
struct rh_namespace_census;
struct rh_raw_mft_census;
struct rh_secure_census_provider;
struct _ntfs_volume;

#define RH_SECURE_CENSUS_PROVIDER_VERSION UINT32_C(1)

struct rh_secure_census_provider_view {
	uint32_t version;
	uint64_t correlation_generation;
	uint64_t security_ids_expected;
	uint64_t security_ids_examined;
	uint64_t security_id_references_expected;
	uint64_t security_id_references_examined;
	uint64_t security_id_references_resolved;
	uint64_t descriptors_expected;
	uint64_t descriptors_examined;
	uint64_t legacy_descriptors_expected;
	uint64_t legacy_descriptors_examined;
	uint64_t sds_entries_expected;
	uint64_t sds_entries_examined;
	uint64_t sdh_entries_expected;
	uint64_t sdh_entries_examined;
	uint64_t sii_entries_expected;
	uint64_t sii_entries_examined;
	uint64_t indexes_expected;
	uint64_t indexes_completed;
	uint64_t index_blocks_allocated;
	uint64_t index_blocks_reachable;
	uint64_t index_blocks_examined;
	uint64_t index_bitmap_bits_expected;
	uint64_t index_bitmap_bits_examined;
	uint8_t sds_clean;
	uint8_t sdh_clean;
	uint8_t sii_clean;
	uint8_t complete;
	unsigned char security_id_manifest_hash[32];
	unsigned char security_id_use_hash[32];
	unsigned char descriptor_manifest_hash[32];
	unsigned char mapping_hash[32];
	unsigned char census_hash[32];
};

int rh_secure_census_provider_run(const struct rh_census_reader *reader,
		struct _ntfs_volume *volume, const struct rh_raw_mft_census *raw,
		const struct rh_namespace_census *namespace_census,
		uint64_t generation, struct rh_secure_census_provider **output);
int rh_secure_census_provider_get_view(
		const struct rh_secure_census_provider *provider,
		struct rh_secure_census_provider_view *view);
void rh_secure_census_provider_destroy(
		struct rh_secure_census_provider *provider);

#endif
