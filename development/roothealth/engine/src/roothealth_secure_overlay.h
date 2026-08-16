#ifndef ROOTHEALTH_SECURE_OVERLAY_H
#define ROOTHEALTH_SECURE_OVERLAY_H

#include <stddef.h>
#include <stdint.h>

#include "roothealth_overlay.h"

struct rh_secure_overlay_data_context {
	const struct rh_overlay_expected_write *writes;
	const unsigned char **bytes;
	size_t count;
};

struct rh_secure_overlay_mft_context {
	uint64_t physical;
	unsigned char record[1024];
};

struct rh_secure_overlay_operation {
	uint64_t physical;
	size_t length;
	uint32_t mst_block_size;
	unsigned char *bytes;
};

struct rh_secure_overlay_operations_context {
	struct rh_secure_overlay_operation *operations;
	size_t count;
};

int rh_secure_overlay_apply_data(ntfs_volume *volume, void *opaque);
int rh_secure_overlay_apply_mft(ntfs_volume *volume, void *opaque);
int rh_secure_overlay_apply_operations(ntfs_volume *volume, void *opaque);

#endif
