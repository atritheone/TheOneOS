#ifndef ROOTHEALTH_REPAIR_H
#define ROOTHEALTH_REPAIR_H

#include <stdint.h>

#include "roothealth_recover.h"
#include "roothealth_write.h"

#define ROOTHEALTH_REPAIR_VERSION "0.5.2"
#define ROOTHEALTH_EXPECTED_LABEL_PREFIX "T1OS"
#define ROOTHEALTH_SUPPORTED_SECTOR_SIZE 512U
#define ROOTHEALTH_SUPPORTED_CLUSTER_SIZE 4096U
#define ROOTHEALTH_SUPPORTED_MFT_RECORD_SIZE 1024U
#define ROOTHEALTH_SUPPORTED_INDEX_RECORD_SIZE 4096U
#define ROOTHEALTH_MAX_VOLUME_BYTES (256ULL * 1024ULL * 1024ULL * 1024ULL)
#define ROOTHEALTH_MAX_MIRRORED_RECORDS 4U

enum rh_result_code {
	RH_RESULT_OK = 0,
	RH_RESULT_UNSAFE = 2,
	RH_RESULT_IO = 3,
	RH_RESULT_WRONG_ROOT = 4,
	RH_RESULT_INTERNAL = 5
};

struct rh_boot_geometry {
	uint32_t sector_size;
	uint32_t cluster_size;
	uint32_t mft_record_size;
	uint32_t index_record_size;
	uint32_t mirrored_records;
	uint64_t sector_count;
	uint64_t mft_lcn;
	uint64_t mftmirr_lcn;
	uint64_t serial;
};

struct rh_identity_result {
	int prewrite_checked;
	int prewrite_valid;
	uint64_t expected_serial;
	uint64_t observed_primary_serial;
	uint64_t observed_backup_serial;
	int primary_boot_valid;
	int backup_boot_valid;
	uint32_t required_paths_checked;
	uint32_t forbidden_paths_checked;
	char expected_label[32];
	char observed_label[64];
	char anchor[32];
};

struct rh_boot_result {
	int checked;
	int geometry_supported;
	int primary_valid;
	int backup_valid;
	int repaired_primary;
	int repaired_backup;
	uint64_t backup_offset;
	struct rh_boot_geometry geometry;
};

struct rh_mirror_result {
	int checked;
	uint32_t records_checked;
	uint32_t primary_repaired;
	uint32_t mirror_repaired;
	uint32_t ambiguous_records;
	uint32_t unsupported_records;
	enum {
		RH_MIRROR_FAILURE_NONE = 0,
		RH_MIRROR_FAILURE_VALID_DIVERGENCE = 1,
		RH_MIRROR_FAILURE_BOTH_UNSUPPORTED = 2
	} failure_kind;
	int failure_record_known;
	uint32_t failure_record;
	struct {
		int checked;
		int primary_valid;
		int mirror_valid;
		int equal_known;
		int equal;
		int first_difference_known;
		uint32_t first_difference_offset;
		uint32_t differing_bytes;
		int hashes_known;
		unsigned char primary_sha256[32];
		unsigned char mirror_sha256[32];
	} records[ROOTHEALTH_MAX_MIRRORED_RECORDS];
};

int roothealth_boot_sector_validate(unsigned char *sector,
		uint32_t sector_size, uint64_t device_size,
		struct rh_boot_geometry *geometry);
int roothealth_bootstrap_mft_record_structure(const unsigned char *raw,
		uint32_t size, uint32_t number,
		const struct rh_boot_geometry *geometry, unsigned char **fixed_out);
int roothealth_bootstrap_mft_records_equal(const unsigned char *left,
		const unsigned char *right, uint32_t size);

int roothealth_refuse_mounted(const char *device_path);
int roothealth_bootstrap_boot_plan(struct rh_writer *writer,
		uint64_t expected_serial, const char *expected_label_prefix,
		struct rh_identity_result *identity,
		struct rh_boot_result *boot);
int roothealth_mftmirr_plan(struct rh_writer *writer,
		const struct rh_boot_geometry *geometry,
		struct rh_mirror_result *result);
int roothealth_verify_namespace_identity(struct rh_writer *writer,
		const char *device_path, const struct rh_boot_geometry *geometry,
		uint64_t expected_serial, const char *expected_label_prefix,
		struct rh_identity_result *identity);
int roothealth_verify_namespace_identity_bounded(struct rh_writer *writer,
		const char *device_path, const struct rh_boot_geometry *geometry,
		uint64_t expected_serial, const char *expected_label_prefix,
		struct rh_identity_result *identity);

#ifdef ROOTHEALTH_REPAIR_TESTING
int roothealth_bootstrap_test_run_intervals(size_t count, int overlap);
#endif

#endif
