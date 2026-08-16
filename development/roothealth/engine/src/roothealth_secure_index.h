#ifndef ROOTHEALTH_SECURE_INDEX_H
#define ROOTHEALTH_SECURE_INDEX_H

#include <stddef.h>

#include "roothealth_secure.h"
#include "roothealth_secure_overlay.h"

struct rh_census_reader;

struct rh_secure_index_action {
	struct rh_overlay_expected_write *writes;
	struct rh_secure_overlay_operation *operations;
	unsigned char **expected_after;
	size_t count;
};

int rh_secure_index_inspect(ntfs_volume *volume, struct rh_writer *writer,
		ntfs_inode *inode, struct rh_secure_inspection *inspection, int sdh);
int rh_secure_index_inspect_reader(ntfs_volume *volume,
		const struct rh_census_reader *reader, ntfs_inode *inode,
		struct rh_secure_inspection *inspection, int sdh);
void rh_secure_index_state_destroy(struct rh_secure_index_state *state);
int rh_secure_index_prepare_action(ntfs_volume *volume,
		const struct rh_secure_inspection *inspection, int sdh,
		struct rh_secure_index_action *action);
void rh_secure_index_action_destroy(struct rh_secure_index_action *action);

#endif
