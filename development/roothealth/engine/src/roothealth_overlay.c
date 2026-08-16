/* ROOTHEALTH_REPAIR_ROLE(TYPED_WAL_ADAPTER) ROOTHEALTH_IO_ROLE(PLANNER) */
#include "config.h"

#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>

#include "device.h"
#include "roothealth_overlay.h"

static struct rh_ntfs_overlay *rh_overlay_from_device(struct ntfs_device *dev)
{
	if (!dev || !dev->d_private) {
		errno = EINVAL;
		return NULL;
	}
	return dev->d_private;
}

static int rh_overlay_open(struct ntfs_device *dev, int flags)
{
	struct rh_ntfs_overlay *overlay = rh_overlay_from_device(dev);
	struct stat st;

	if (!overlay || NDevOpen(dev) || (flags & O_ACCMODE) != O_RDONLY ||
		fstat(overlay->writer->read_fd, &st)) {
		if (!errno)
			errno = EROFS;
		return -1;
	}
	NDevSetOpen(dev);
	NDevSetReadOnly(dev);
	if (S_ISBLK(st.st_mode))
		NDevSetBlock(dev);
	return 0;
}

static int rh_overlay_close(struct ntfs_device *dev)
{
	if (!dev || !NDevOpen(dev)) {
		errno = EINVAL;
		return -1;
	}
	NDevClearOpen(dev);
	return 0;
}

static s64 rh_overlay_seek(struct ntfs_device *dev, s64 offset, int whence)
{
	struct rh_ntfs_overlay *overlay = rh_overlay_from_device(dev);
	uint64_t base;

	if (!overlay)
		return -1;
	if (whence == SEEK_SET)
		base = 0;
	else if (whence == SEEK_CUR) {
		if (overlay->position < 0) {
			errno = EINVAL;
			return -1;
		}
		base = (uint64_t)overlay->position;
	} else if (whence == SEEK_END)
		base = overlay->writer->device_size;
	else {
		errno = EINVAL;
		return -1;
	}
	if ((offset < 0 && (uint64_t)(-(offset + 1)) + 1 > base) ||
		(offset >= 0 && (uint64_t)offset > UINT64_MAX - base) ||
		(offset >= 0 && base + (uint64_t)offset > INT64_MAX)) {
		errno = EINVAL;
		return -1;
	}
	overlay->position = offset < 0 ?
		(s64)(base - ((uint64_t)(-(offset + 1)) + 1)) :
		(s64)(base + (uint64_t)offset);
	return overlay->position;
}

static s64 rh_overlay_pread(struct ntfs_device *dev, void *buf, s64 count,
		s64 offset)
{
	struct rh_ntfs_overlay *overlay = rh_overlay_from_device(dev);

	if (!overlay || !buf || count < 0 || offset < 0 ||
		(uint64_t)count > SIZE_MAX) {
		errno = EINVAL;
		return -1;
	}
	if ((uint64_t)offset >= overlay->writer->device_size)
		return 0;
	if ((uint64_t)count > overlay->writer->device_size - (uint64_t)offset)
		count = (s64)(overlay->writer->device_size - (uint64_t)offset);
	if (!count)
		return 0;
	if (rh_writer_read(overlay->writer, (uint64_t)offset,
			(size_t)count, buf)) {
		overlay->failed = 1;
		return -1;
	}
	return count;
}

static s64 rh_overlay_read(struct ntfs_device *dev, void *buf, s64 count)
{
	struct rh_ntfs_overlay *overlay = rh_overlay_from_device(dev);
	s64 result;

	if (!overlay)
		return -1;
	result = rh_overlay_pread(dev, buf, count, overlay->position);
	if (result > 0)
		overlay->position += result;
	return result;
}

static s64 rh_overlay_refuse_write(struct ntfs_device *dev __attribute__((unused)),
		const void *buf __attribute__((unused)),
		s64 count __attribute__((unused)))
{
	errno = EPERM;
	return -1;
}

static s64 rh_overlay_refuse_pwrite(struct ntfs_device *dev __attribute__((unused)),
		const void *buf __attribute__((unused)),
		s64 count __attribute__((unused)), s64 offset __attribute__((unused)))
{
	/* Direct d_ops->pwrite callers are an architectural violation. */
	errno = EPERM;
	return -1;
}

static s64 rh_overlay_plan_write(struct ntfs_device *dev, const void *buf,
		s64 count, s64 offset, void *opaque)
{
	struct rh_ntfs_overlay *overlay = opaque;
	uint64_t end;
	const struct rh_overlay_expected_write *expected;
	size_t before_count;

	if (!overlay || overlay != rh_overlay_from_device(dev) ||
		!overlay->action_active || overlay->failed || !buf || count <= 0 ||
		offset < 0 || (uint64_t)count > SIZE_MAX ||
		overlay->active_kind < 0 ||
		overlay->active_kind >= RH_WRITE_KIND_COUNT ||
		overlay->observed_write_calls >= overlay->expected_write_count ||
		(uint64_t)count > UINT64_MAX - (uint64_t)offset) {
		errno = EPERM;
		if (overlay)
			overlay->failed = 1;
		return -1;
	}
	end = (uint64_t)offset + (uint64_t)count;
	expected = &overlay->expected_writes[overlay->observed_write_calls];
	if ((uint64_t)offset != expected->offset ||
		(uint64_t)count != expected->length ||
		end != expected->offset + expected->length) {
		errno = EPERM;
		overlay->failed = 1;
		return -1;
	}
	before_count = overlay->writer->operation_count;
	if (rh_writer_plan_typed(overlay->writer, overlay->active_kind,
			(uint64_t)offset, (size_t)count, buf, &expected->target)) {
		overlay->failed = 1;
		return -1;
	}
	/* A helper which attempts an identical target write is not a repair. */
	if (overlay->writer->operation_count != before_count + 1) {
		errno = EPERM;
		overlay->failed = 1;
		return -1;
	}
	overlay->observed_write_calls++;
	overlay->planned_calls[overlay->active_kind]++;
	return count;
}

static int rh_overlay_sync(struct ntfs_device *dev __attribute__((unused)))
{
	/* Diagnosis is plan-only; persistence is owned by rh_writer_commit(). */
	return 0;
}

static int rh_overlay_stat(struct ntfs_device *dev, struct stat *buf)
{
	struct rh_ntfs_overlay *overlay = rh_overlay_from_device(dev);

	if (!overlay || !buf)
		return -1;
	return fstat(overlay->writer->read_fd, buf);
}

static int rh_overlay_ioctl(struct ntfs_device *dev __attribute__((unused)),
		unsigned long request __attribute__((unused)),
		void *argp __attribute__((unused)))
{
	errno = ENOTTY;
	return -1;
}

static struct ntfs_device_operations rh_overlay_operations = {
	.open = rh_overlay_open,
	.close = rh_overlay_close,
	.seek = rh_overlay_seek,
	.read = rh_overlay_read,
	.write = rh_overlay_refuse_write,
	.pread = rh_overlay_pread,
	.pwrite = rh_overlay_refuse_pwrite,
	.sync = rh_overlay_sync,
	.stat = rh_overlay_stat,
	.ioctl = rh_overlay_ioctl,
};

static int rh_ntfs_overlay_mount_device(struct rh_ntfs_overlay *overlay)
{
	overlay->position = 0;
	overlay->device = ntfs_device_alloc(overlay->writer->path, 0,
			&rh_overlay_operations, overlay);
	if (!overlay->device)
		return -1;
	if (ntfs_device_roothealth_install_plan_write(overlay->device,
			rh_overlay_plan_write, overlay))
		goto fail;
	overlay->volume = ntfs_device_mount(overlay->device,
			overlay->diagnostic_flags | NTFS_MNT_RDONLY |
			NTFS_MNT_FORENSIC | NTFS_MNT_FS_NO_REPAIR);
	if (!overlay->volume)
		goto fail;
	if (!NDevReadOnly(overlay->volume->dev)) {
		errno = EPERM;
		ntfs_device_roothealth_remove_plan_write(overlay->volume->dev);
		ntfs_umount(overlay->volume, TRUE);
		overlay->volume = NULL;
		overlay->device = NULL;
		return -1;
	}
	return 0;

fail:
	ntfs_device_roothealth_remove_plan_write(overlay->device);
	if (NDevOpen(overlay->device))
		overlay->device->d_ops->close(overlay->device);
	ntfs_device_free(overlay->device);
	overlay->device = NULL;
	return -1;
}

int rh_ntfs_overlay_mount(struct rh_ntfs_overlay *overlay,
		struct rh_writer *writer, ntfs_mount_flags diagnostic_flags)
{
	ntfs_mount_flags forbidden = NTFS_MNT_FS_AUTO_REPAIR |
		NTFS_MNT_FS_ASK_REPAIR | NTFS_MNT_FS_YES_REPAIR;

	if (!overlay || !writer || writer->read_fd < 0 ||
		(diagnostic_flags & forbidden)) {
		errno = EINVAL;
		return -1;
	}
	memset(overlay, 0, sizeof(*overlay));
	overlay->writer = writer;
	overlay->active_kind = RH_WRITE_KIND_COUNT;
	overlay->diagnostic_flags = diagnostic_flags;
	return rh_ntfs_overlay_mount_device(overlay);
}

static int rh_ntfs_overlay_begin_action(struct rh_ntfs_overlay *overlay,
		const struct rh_overlay_action_expectation *expectation)
{
	size_t i;

	if (!overlay || !overlay->volume || overlay->action_active ||
		overlay->failed || !expectation || !expectation->write_count ||
		!expectation->writes ||
		expectation->write_count > 4096 ||
		expectation->kind < 0 || expectation->kind >= RH_WRITE_KIND_COUNT) {
		errno = EINVAL;
		return -1;
	}
	for (i = 0; i < expectation->write_count; i++) {
		if (!expectation->writes[i].length ||
			expectation->writes[i].target.seal_version != 1 ||
			expectation->writes[i].offset > overlay->writer->device_size ||
			expectation->writes[i].length > overlay->writer->device_size -
				expectation->writes[i].offset) {
			errno = EINVAL;
			return -1;
		}
	}
	overlay->expected_writes = malloc(expectation->write_count *
		sizeof(*overlay->expected_writes));
	if (!overlay->expected_writes)
		return -1;
	memcpy(overlay->expected_writes, expectation->writes,
		expectation->write_count * sizeof(*overlay->expected_writes));
	overlay->active_kind = expectation->kind;
	overlay->expected_write_count = expectation->write_count;
	overlay->observed_write_calls = 0;
	overlay->action_checkpoint = rh_writer_plan_checkpoint(overlay->writer);
	overlay->action_active = 1;
	NVolClearReadOnly(overlay->volume);
	return 0;
}

static int rh_ntfs_overlay_finish_action(struct rh_ntfs_overlay *overlay,
		int helper_result)
{
	int success;
	int refused;
	enum rh_write_kind kind;

	if (!overlay || !overlay->volume || !overlay->action_active) {
		errno = EINVAL;
		return -1;
	}
	NVolSetReadOnly(overlay->volume);
	kind = overlay->active_kind;
	success = !helper_result && !overlay->failed &&
		overlay->observed_write_calls == overlay->expected_write_count &&
		overlay->writer->operation_count - overlay->action_checkpoint ==
			overlay->expected_write_count;
	refused = helper_result == RH_OVERLAY_ACTION_REFUSED && !overlay->failed;
	if (!success) {
		if (rh_writer_discard_after(overlay->writer,
				overlay->action_checkpoint))
			overlay->failed = 1;
		if (kind >= 0 && kind < RH_WRITE_KIND_COUNT &&
			overlay->planned_calls[kind] >= overlay->observed_write_calls)
			overlay->planned_calls[kind] -= overlay->observed_write_calls;
	}
	overlay->active_kind = RH_WRITE_KIND_COUNT;
	overlay->action_active = 0;
	free(overlay->expected_writes);
	overlay->expected_writes = NULL;
	overlay->expected_write_count = 0;
	overlay->observed_write_calls = 0;
	if (success) {
		/*
		 * Never derive policy facts from helper-mutated libntfs caches.  A
		 * successful staged action is visible only through the writer overlay
		 * after a complete forensic remount.
		 */
		ntfs_device_roothealth_remove_plan_write(overlay->volume->dev);
		if (ntfs_umount(overlay->volume, TRUE)) {
			overlay->volume = NULL;
			overlay->device = NULL;
			overlay->failed = 1;
			return RH_OVERLAY_ACTION_ERROR;
		}
		overlay->volume = NULL;
		overlay->device = NULL;
		if (rh_ntfs_overlay_mount_device(overlay)) {
			overlay->failed = 1;
			return RH_OVERLAY_ACTION_ERROR;
		}
		return RH_OVERLAY_ACTION_OK;
	}
	if (!success) {
		if (refused && !overlay->failed) {
			ntfs_device_roothealth_remove_plan_write(overlay->volume->dev);
			if (ntfs_umount(overlay->volume, TRUE)) {
				overlay->volume = NULL;
				overlay->device = NULL;
				overlay->failed = 1;
				return RH_OVERLAY_ACTION_ERROR;
			}
			overlay->volume = NULL;
			overlay->device = NULL;
			if (rh_ntfs_overlay_mount_device(overlay)) {
				overlay->failed = 1;
				return RH_OVERLAY_ACTION_ERROR;
			}
			return RH_OVERLAY_ACTION_REFUSED;
		}
		overlay->failed = 1;
		errno = EIO;
		return RH_OVERLAY_ACTION_ERROR;
	}
	return 0;
}

int rh_ntfs_overlay_run_action(struct rh_ntfs_overlay *overlay,
		const struct rh_overlay_action_expectation *expectation,
		rh_overlay_action_fn action, void *opaque)
{
	int helper_result;

	if (!action || rh_ntfs_overlay_begin_action(overlay, expectation))
		return -1;
	helper_result = action(overlay->volume, opaque);
	return rh_ntfs_overlay_finish_action(overlay, helper_result);
}

int rh_ntfs_overlay_failed(const struct rh_ntfs_overlay *overlay)
{
	return !overlay || overlay->failed;
}

void rh_ntfs_overlay_unmount(struct rh_ntfs_overlay *overlay)
{
	if (!overlay)
		return;
	if (overlay->action_active) {
		NVolSetReadOnly(overlay->volume);
		rh_writer_discard_after(overlay->writer,
			overlay->action_checkpoint);
		overlay->action_active = 0;
	}
	free(overlay->expected_writes);
	if (overlay->volume) {
		NVolSetReadOnly(overlay->volume);
		ntfs_device_roothealth_remove_plan_write(overlay->volume->dev);
		ntfs_umount(overlay->volume, TRUE);
	}
	memset(overlay, 0, sizeof(*overlay));
	overlay->active_kind = RH_WRITE_KIND_COUNT;
}
