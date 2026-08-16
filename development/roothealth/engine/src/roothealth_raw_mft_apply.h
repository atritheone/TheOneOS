#ifndef ROOTHEALTH_RAW_MFT_APPLY_H
#define ROOTHEALTH_RAW_MFT_APPLY_H

#include <stddef.h>

#include "roothealth_overlay.h"
#include "roothealth_raw_mft.h"

int rh_raw_layout_stage(struct rh_ntfs_overlay *overlay,
		const struct rh_raw_mft_census *census,
		size_t *first_operation_ordinal);

#endif
