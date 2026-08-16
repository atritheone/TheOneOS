#ifndef ROOTHEALTH_NAMESPACE_H
#define ROOTHEALTH_NAMESPACE_H

#include <stddef.h>
#include <stdint.h>

#include "roothealth_raw_mft.h"

struct rh_census_reader;
struct rh_index_bitmap_census;

enum rh_t1os_identity_result {
	RH_T1OS_IDENTITY_UNKNOWN = 0,
	RH_T1OS_IDENTITY_MATCH = 1,
	RH_T1OS_IDENTITY_MISSING = 2,
	RH_T1OS_IDENTITY_AMBIGUOUS = 3
};

enum rh_namespace_recovery_anchor_state {
	RH_NAMESPACE_RECOVERY_ANCHOR_UNKNOWN = 0,
	RH_NAMESPACE_RECOVERY_ANCHOR_ABSENT = 1,
	RH_NAMESPACE_RECOVERY_ANCHOR_PRESENT = 2,
	RH_NAMESPACE_RECOVERY_ANCHOR_AMBIGUOUS = 3,
};

#define RH_NAMESPACE_RECOVERY_ANCHOR_COMPONENTS 3U

struct rh_namespace_recovery_anchor_component {
	struct rh_raw_mft_ref parent;
	struct rh_raw_mft_ref child;
	uint8_t name_namespace;
};

struct rh_namespace_recovery_anchor {
	enum rh_namespace_recovery_anchor_state state;
	uint8_t components_completed;
	struct rh_namespace_recovery_anchor_component
		components[RH_NAMESPACE_RECOVERY_ANCHOR_COMPONENTS];
	unsigned char manifest_hash[32];
};

enum rh_namespace_child_state {
	RH_NAMESPACE_CHILD_UNKNOWN = 0,
	RH_NAMESPACE_CHILD_ABSENT = 1,
	RH_NAMESPACE_CHILD_PRESENT = 2,
	RH_NAMESPACE_CHILD_AMBIGUOUS = 3,
};

struct rh_namespace_resolved_child {
	enum rh_namespace_child_state state;
	struct rh_raw_mft_ref parent;
	struct rh_raw_mft_ref child;
	uint8_t name_namespace;
	unsigned char manifest_hash[32];
};

struct rh_namespace_link {
	struct rh_raw_mft_ref owner;
	struct rh_raw_mft_ref storage;
	struct rh_raw_mft_ref parent;
	uint16_t attribute_instance;
	uint32_t record_value_offset;
	uint8_t name_namespace;
	uint8_t name_length;
	uint32_t file_name_value_length;
	size_t name_offset;
	size_t file_name_value_offset;
	unsigned char file_name_value_hash[32];
	unsigned char reciprocity_value_hash[32];
	unsigned char logical_link_hash[32];
};

struct rh_namespace_i30_edge {
	struct rh_raw_mft_ref child;
	struct rh_raw_mft_ref parent;
	uint8_t name_namespace;
	uint8_t name_length;
	uint16_t entry_length;
	uint16_t key_length;
	uint16_t entry_flags;
	uint8_t from_index_block;
	int64_t block_vcn;
	uint64_t indexed_file_reference;
	size_t name_offset;
	size_t file_name_value_offset;
	unsigned char file_name_value_hash[32];
	unsigned char reciprocity_value_hash[32];
};

struct rh_namespace_census {
	uint64_t generation;
	uint64_t live_nodes_expected;
	uint64_t live_nodes_completed;
	uint64_t links_expected;
	uint64_t links_completed;
	uint64_t reachable_nodes;
	uint64_t orphan_nodes;
	uint64_t unresolved_parents;
	uint64_t cycles;
	uint64_t aliases;
	uint64_t posix_case_collisions;
	uint64_t identity_required_expected;
	uint64_t identity_required_completed;
	uint64_t forbidden_root_names_expected;
	uint64_t forbidden_root_children_examined;
	uint64_t forbidden_root_children_matched;
	uint64_t cached_file_name_differences;
	uint64_t i30_directories_expected;
	uint64_t i30_directories_completed;
	uint64_t i30_indexes_expected;
	uint64_t i30_indexes_completed;
	uint64_t i30_entries_examined;
	uint64_t i30_blocks_expected;
	uint64_t i30_blocks_examined;
	uint64_t i30_blocks_reachable;
	uint64_t i30_child_vcns_examined;
	uint64_t i30_bitmap_bits_examined;
	uint64_t i30_bitmap_changes;
	uint64_t i30_clear_bits_required;
	struct rh_namespace_link *links;
	size_t link_count;
	struct rh_namespace_i30_edge *i30_edges;
	size_t i30_edge_count;
	unsigned char *name_arena;
	size_t name_arena_size;
	unsigned char *file_name_value_arena;
	size_t file_name_value_arena_size;
	unsigned char *i30_name_arena;
	size_t i30_name_arena_size;
	unsigned char *i30_value_arena;
	size_t i30_value_arena_size;
	unsigned char upcase_hash[32];
	unsigned char graph_hash[32];
	unsigned char manifest_hash[32];
	unsigned char i30_edge_hash[32];
	unsigned char i30_manifest_hash[32];
	unsigned char i30_tree_hash[32];
	unsigned char i30_expected_bitmap_hash[32];
	unsigned char i30_index_census_hash[32];
	unsigned char reciprocity_hash[32];
	unsigned char forbidden_root_set_hash[32];
	unsigned char identity_hash[32];
	unsigned char census_hash[32];
	uint8_t graph_bounded;
	uint8_t graph_complete;
	uint8_t i30_complete;
	uint8_t reciprocity_complete;
	uint8_t identity_checked;
	enum rh_t1os_identity_result identity;
};

int rh_namespace_census_run(const struct rh_raw_mft_census *raw,
		uint64_t generation, struct rh_namespace_census *census);
int rh_namespace_file_name_reciprocity_hash(const unsigned char *value,
		size_t length, unsigned char digest[32]);
int rh_namespace_check_t1os_identity(const struct rh_raw_mft_census *raw,
		struct rh_namespace_census *census);
int rh_namespace_resolve_recovery_anchor(
		const struct rh_raw_mft_census *raw,
		const struct rh_namespace_census *census,
		struct rh_namespace_recovery_anchor *anchor);
int rh_namespace_resolve_exact_child(
		const struct rh_raw_mft_census *raw,
		const struct rh_namespace_census *census,
		struct rh_raw_mft_ref parent, const char *exact_ascii_name,
		int require_directory,
		struct rh_namespace_resolved_child *resolved);
size_t rh_namespace_forbidden_root_name_count(void);
const char *rh_namespace_forbidden_root_name(size_t index);
int rh_namespace_i30_census_run(struct _ntfs_volume *volume,
		struct rh_writer *writer, const struct rh_raw_mft_census *raw,
		struct rh_namespace_census *census);
int rh_namespace_i30_census_run_reader(struct _ntfs_volume *volume,
		const struct rh_census_reader *reader,
		const struct rh_raw_mft_census *raw,
		struct rh_namespace_census *census,
		struct rh_index_bitmap_census *index_output);
/* Raw FILE_NAME references only; this is not the complete slot-authority seal. */
int rh_namespace_raw_link_record_referenced(
		const struct rh_namespace_census *census,
		uint64_t record, int *referenced);
int rh_namespace_complete_record_referenced(
		const struct rh_namespace_census *census,
		uint64_t record, int *referenced);
void rh_namespace_census_release(struct rh_namespace_census *census);

#endif
