#ifndef ROOTHEALTH_NAMESPACE_REPAIR_H
#define ROOTHEALTH_NAMESPACE_REPAIR_H

#include <stddef.h>
#include <stdint.h>

#include "roothealth_complete_census.h"
#include "roothealth_write.h"

#define RH_NAMESPACE_REPAIR_EVIDENCE_VERSION 1U

struct rh_census_reader;

struct rh_namespace_repair_candidate {
	uint64_t parent_record;
	uint16_t parent_sequence;
	uint64_t child_record;
	uint16_t child_sequence;
	uint64_t physical_record_offset;
	uint32_t attribute_record_offset;
	uint32_t attribute_record_length;
	uint16_t attribute_instance;
	uint64_t indexed_file_reference;
	uint16_t entry_length;
	uint16_t key_length;
	uint8_t name_namespace;
	unsigned char evidence_hash[32];
};

int rh_namespace_operations_registry_qualify(
		const struct rh_complete_census *census,
		struct rh_namespace_repair_candidate *candidate);
int rh_namespace_operations_registry_derive(
		const struct rh_census_reader *reader,
		const struct rh_complete_census *census,
		struct rh_namespace_repair_candidate *candidate,
		unsigned char before[1024], unsigned char after[1024],
		struct rh_write_semantic_target *target);
int rh_namespace_operations_registry_stage(
		const struct rh_census_reader *reader,
		const struct rh_complete_census *census, struct rh_writer *writer,
		size_t *operation_ordinal,
		struct rh_namespace_repair_candidate *candidate);

#endif
