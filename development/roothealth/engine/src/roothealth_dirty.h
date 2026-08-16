#ifndef ROOTHEALTH_DIRTY_H
#define ROOTHEALTH_DIRTY_H

#include <stddef.h>
#include <stdint.h>

#include "roothealth_overlay.h"

enum rh_volume_peer {
	RH_VOLUME_PEER_MFT_PRIMARY = 1,
	RH_VOLUME_PEER_MFT_MIRROR = 2
};

struct rh_volume_dirty_pair {
	uint16_t sequence;
	uint16_t attribute_instance;
	uint16_t flags_before;
	uint16_t flags_after;
	uint64_t primary_record_offset;
	uint64_t mirror_record_offset;
	uint64_t primary_flag_offset;
	uint64_t mirror_flag_offset;
	size_t first_operation_ordinal;
	int initially_dirty;
	int requested_dirty;
	int planned;
};

int rh_volume_dirty_inspect(ntfs_volume *volume, struct rh_writer *writer,
		int requested_dirty, struct rh_volume_dirty_pair *pair);
int rh_volume_dirty_stage_pair(struct rh_writer *writer,
		struct rh_volume_dirty_pair *pair);

#endif
