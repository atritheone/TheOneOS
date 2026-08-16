#ifndef ROOTHEALTH_OVERLAY_H
#define ROOTHEALTH_OVERLAY_H

#include <stddef.h>
#include <stdint.h>

#include "device.h"
#include "roothealth_write.h"
#include "volume.h"

struct rh_overlay_expected_write {
	uint64_t offset;
	uint64_t length;
	struct rh_write_semantic_target target;
};

struct rh_overlay_action_expectation {
	enum rh_write_kind kind;
	const struct rh_overlay_expected_write *writes;
	size_t write_count;
};

typedef int (*rh_overlay_action_fn)(ntfs_volume *volume, void *opaque);

enum rh_overlay_action_result {
	RH_OVERLAY_ACTION_OK = 0,
	RH_OVERLAY_ACTION_REFUSED = 1,
	RH_OVERLAY_ACTION_ERROR = -1
};

struct rh_ntfs_overlay {
	struct rh_writer *writer;
	struct ntfs_device *device;
	ntfs_volume *volume;
	s64 position;
	enum rh_write_kind active_kind;
	uint64_t planned_calls[RH_WRITE_KIND_COUNT];
	struct rh_overlay_expected_write *expected_writes;
	size_t expected_write_count;
	size_t observed_write_calls;
	size_t action_checkpoint;
	ntfs_mount_flags diagnostic_flags;
	int action_active;
	int failed;
};

int rh_ntfs_overlay_mount(struct rh_ntfs_overlay *overlay,
		struct rh_writer *writer, ntfs_mount_flags diagnostic_flags);
int rh_ntfs_overlay_run_action(struct rh_ntfs_overlay *overlay,
		const struct rh_overlay_action_expectation *expectation,
		rh_overlay_action_fn action, void *opaque);
int rh_ntfs_overlay_failed(const struct rh_ntfs_overlay *overlay);
void rh_ntfs_overlay_unmount(struct rh_ntfs_overlay *overlay);

#endif
