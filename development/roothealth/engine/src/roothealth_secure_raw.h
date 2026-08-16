#ifndef ROOTHEALTH_SECURE_RAW_H
#define ROOTHEALTH_SECURE_RAW_H

#include <stddef.h>
#include <stdint.h>

#include "roothealth_raw_mft.h"
#include "roothealth_secure.h"

struct rh_census_reader;

struct rh_secure_raw_resident {
	uint64_t storage_mft_record;
	uint16_t storage_sequence;
	uint16_t attribute_instance;
	uint32_t record_offset;
	uint32_t record_length;
	uint32_t value_offset;
	uint32_t value_length;
};

int rh_secure_raw_census_valid(const struct rh_raw_mft_census *census,
		uint64_t generation, uint16_t secure_sequence);
int rh_secure_raw_build_mapping(const struct rh_raw_mft_census *census,
		struct rh_writer *writer, struct rh_raw_mft_ref owner, uint32_t type,
		const unsigned char *name_utf16le, uint16_t name_length,
		uint64_t minimum_data_size, uint64_t maximum_data_size,
		struct rh_secure_mapping_slice **slices, size_t *slice_count,
		uint64_t *data_size);
int rh_secure_raw_build_mapping_reader(const struct rh_raw_mft_census *census,
		const struct rh_census_reader *reader, struct rh_raw_mft_ref owner,
		uint32_t type, const unsigned char *name_utf16le,
		uint16_t name_length, uint64_t minimum_data_size,
		uint64_t maximum_data_size, struct rh_secure_mapping_slice **slices,
		size_t *slice_count, uint64_t *data_size);
int rh_secure_raw_find_resident(const struct rh_raw_mft_census *census,
		struct rh_raw_mft_ref owner, uint32_t type,
		const unsigned char *name_utf16le, uint16_t name_length,
		struct rh_secure_raw_resident *resident);

#endif
