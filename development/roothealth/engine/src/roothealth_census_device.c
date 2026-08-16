/* ROOTHEALTH_REPAIR_ROLE(DIAGNOSTIC) ROOTHEALTH_IO_ROLE(READER) */
#include "config.h"

#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

#include "device.h"
#include "roothealth_census_device.h"
#include "roothealth_wal.h"
#include "roothealth_write.h"

static struct rh_census_device *rh_census_from_ntfs(struct ntfs_device *device)
{
	if (!device || !device->d_private) {
		errno = EINVAL;
		return NULL;
	}
	return device->d_private;
}

static int rh_census_open(struct ntfs_device *device, int flags)
{
	struct rh_census_device *census = rh_census_from_ntfs(device);

	if (!census || NDevOpen(device) || (flags & O_ACCMODE) != O_RDONLY) {
		if (!errno)
			errno = EROFS;
		return -1;
	}
	NDevSetOpen(device);
	NDevSetReadOnly(device);
	return 0;
}

static int rh_census_close(struct ntfs_device *device)
{
	if (!device || !NDevOpen(device)) {
		errno = EINVAL;
		return -1;
	}
	NDevClearOpen(device);
	return 0;
}

static s64 rh_census_seek(struct ntfs_device *device, s64 offset, int whence)
{
	struct rh_census_device *census = rh_census_from_ntfs(device);
	uint64_t base;

	if (!census)
		return -1;
	if (whence == SEEK_SET)
		base = 0;
	else if (whence == SEEK_CUR) {
		if (census->position < 0) {
			errno = EINVAL;
			return -1;
		}
		base = (uint64_t)census->position;
	} else if (whence == SEEK_END) {
		base = census->reader.device_size;
	} else {
		errno = EINVAL;
		return -1;
	}
	if ((offset < 0 && (uint64_t)(-(offset + 1)) + 1U > base) ||
			(offset >= 0 && (uint64_t)offset > UINT64_MAX - base) ||
			(offset >= 0 && base + (uint64_t)offset > INT64_MAX)) {
		errno = EINVAL;
		return -1;
	}
	census->position = offset < 0 ?
		(s64)(base - ((uint64_t)(-(offset + 1)) + 1U)) :
		(s64)(base + (uint64_t)offset);
	return census->position;
}

static s64 rh_census_pread(struct ntfs_device *device, void *buffer, s64 count,
		s64 offset)
{
	struct rh_census_device *census = rh_census_from_ntfs(device);

	if (!census || !buffer || count < 0 || offset < 0 ||
			(uint64_t)count > SIZE_MAX) {
		errno = EINVAL;
		return -1;
	}
	if ((uint64_t)offset >= census->reader.device_size)
		return 0;
	if ((uint64_t)count > census->reader.device_size - (uint64_t)offset)
		count = (s64)(census->reader.device_size - (uint64_t)offset);
	if (!count)
		return 0;
	if (rh_census_reader_read_exact(&census->reader, (uint64_t)offset,
			(size_t)count, buffer)) {
		census->failed = 1;
		census->failure_errno = errno ? errno : EIO;
		return -1;
	}
	return count;
}

static s64 rh_census_read(struct ntfs_device *device, void *buffer, s64 count)
{
	struct rh_census_device *census = rh_census_from_ntfs(device);
	s64 result;

	if (!census)
		return -1;
	result = rh_census_pread(device, buffer, count, census->position);
	if (result > 0)
		census->position += result;
	return result;
}

static s64 rh_census_refuse_write(struct ntfs_device *device
		__attribute__((unused)), const void *buffer __attribute__((unused)),
		s64 count __attribute__((unused)))
{
	errno = EPERM;
	return -1;
}

static s64 rh_census_refuse_pwrite(struct ntfs_device *device
		__attribute__((unused)), const void *buffer __attribute__((unused)),
		s64 count __attribute__((unused)), s64 offset __attribute__((unused)))
{
	errno = EPERM;
	return -1;
}

static int rh_census_sync(struct ntfs_device *device __attribute__((unused)))
{
#ifdef ROOTHEALTH_REPAIR_TESTING
	const char *fault = getenv("ROOTHEALTH_REPAIR_TEST_FAIL");

	if (fault && !strcmp(fault, "census-unmount")) {
		errno = EIO;
		return -1;
	}
#endif
	return 0;
}

static int rh_census_stat(struct ntfs_device *device, struct stat *status)
{
	struct rh_census_device *census = rh_census_from_ntfs(device);

	if (!census || !status)
		return -1;
	if (census->reader.stat && census->reader.stat(&census->reader, status)) {
		census->failed = 1;
		census->failure_errno = errno ? errno : EIO;
		return -1;
	}
	if (census->reader.stat)
		return 0;
	if (census->reader.device_size > INT64_MAX) {
		errno = EOVERFLOW;
		return -1;
	}
	memset(status, 0, sizeof(*status));
	status->st_mode = S_IFREG | S_IRUSR;
	status->st_size = (off_t)census->reader.device_size;
	status->st_blksize = 4096;
	return 0;
}

static int rh_census_ioctl(struct ntfs_device *device
		__attribute__((unused)), unsigned long request __attribute__((unused)),
		void *argument __attribute__((unused)))
{
	errno = ENOTTY;
	return -1;
}

static struct ntfs_device_operations rh_census_operations = {
	.open = rh_census_open,
	.close = rh_census_close,
	.seek = rh_census_seek,
	.read = rh_census_read,
	.write = rh_census_refuse_write,
	.pread = rh_census_pread,
	.pwrite = rh_census_refuse_pwrite,
	.sync = rh_census_sync,
	.stat = rh_census_stat,
	.ioctl = rh_census_ioctl,
};

static int rh_writer_reader_read(const struct rh_census_reader *reader,
		uint64_t offset, size_t length, void *buffer)
{
	return rh_writer_staged_read((struct rh_writer *)reader->context,
		reader->writer_operation_count, offset, length, buffer);
}

static int rh_writer_reader_stat(const struct rh_census_reader *reader,
		struct stat *status)
{
	const struct rh_writer *writer = reader->context;

	if (!writer || writer->read_fd < 0 || !status)
		return -1;
	return fstat(writer->read_fd, status);
}

static int rh_writer_reader_excluded(const struct rh_census_reader *reader,
		uint64_t offset, uint64_t length, int *excluded)
{
	const struct rh_writer *writer = reader->context;

	if (!writer || !excluded || !length || offset > writer->device_size ||
			length > writer->device_size - offset) {
		errno = EINVAL;
		return -1;
	}
	*excluded = rh_writer_range_excluded(writer, offset, length);
	return 0;
}

int rh_census_reader_from_writer_prefix(const struct rh_writer *writer,
		size_t operation_count, struct rh_census_reader *reader)
{
	if (!writer || !reader || writer->read_fd < 0 || !writer->device_size ||
			operation_count > writer->operation_count) {
		errno = EINVAL;
		return -1;
	}
	memset(reader, 0, sizeof(*reader));
	reader->context = writer;
	reader->device_size = writer->device_size;
	reader->source = RH_CENSUS_READER_WRITER_PREFIX;
	reader->writer_operation_count = operation_count;
	reader->read = rh_writer_reader_read;
	reader->stat = rh_writer_reader_stat;
	reader->excluded = rh_writer_reader_excluded;
	return 0;
}

static int rh_preimage_reader_read(const struct rh_census_reader *reader,
		uint64_t offset, size_t length, void *buffer)
{
	return rh_wal_preimage_read(reader->context, offset, length, buffer);
}

static int rh_preimage_reader_excluded(const struct rh_census_reader *reader,
		uint64_t offset, uint64_t length, int *excluded)
{
	return rh_wal_preimage_range_excluded(reader->context, offset, length,
		excluded);
}

int rh_census_reader_read_exact(const struct rh_census_reader *reader,
		uint64_t offset, size_t length, void *buffer)
{
	if (!reader || !reader->context || !reader->read ||
			(!buffer && length) || offset > reader->device_size ||
			length > reader->device_size - offset) {
		errno = EINVAL;
		return -1;
	}
	return reader->read(reader, offset, length, buffer);
}

int rh_census_reader_is_pretransaction(const struct rh_census_reader *reader)
{
	return reader && ((reader->source == RH_CENSUS_READER_WRITER_PREFIX &&
		!reader->writer_operation_count) ||
		reader->source == RH_CENSUS_READER_WAL_PREIMAGE);
}

int rh_census_reader_range_excluded(const struct rh_census_reader *reader,
		uint64_t offset, uint64_t length, int *excluded)
{
	if (!reader || !excluded || !length || offset > reader->device_size ||
			length > reader->device_size - offset) {
		errno = EINVAL;
		return -1;
	}
	if (!reader->excluded) {
		errno = EOPNOTSUPP;
		return -1;
	}
	return reader->excluded(reader, offset, length, excluded);
}

int rh_census_reader_from_wal_preimage(
		const struct rh_wal_preimage *preimage,
		struct rh_census_reader *reader)
{
	uint64_t size;

	if (!preimage || !reader || !(size = rh_wal_preimage_size(preimage))) {
		errno = EINVAL;
		return -1;
	}
	memset(reader, 0, sizeof(*reader));
	reader->context = preimage;
	reader->device_size = size;
	reader->source = RH_CENSUS_READER_WAL_PREIMAGE;
	reader->read = rh_preimage_reader_read;
	reader->excluded = rh_preimage_reader_excluded;
	return 0;
}

int rh_census_device_mount(struct rh_census_device *census,
		const struct rh_census_reader *reader,
		ntfs_mount_flags diagnostic_flags)
{
	ntfs_mount_flags forbidden = NTFS_MNT_FS_AUTO_REPAIR |
		NTFS_MNT_FS_ASK_REPAIR | NTFS_MNT_FS_YES_REPAIR;

	if (!census || !reader || !reader->context || !reader->device_size ||
			!reader->read || reader->source <= RH_CENSUS_READER_INVALID ||
			reader->source > RH_CENSUS_READER_WAL_PREIMAGE ||
			(diagnostic_flags & forbidden)) {
		errno = EINVAL;
		return -1;
	}
	memset(census, 0, sizeof(*census));
	census->reader = *reader;
	census->device = ntfs_device_alloc("roothealth-census", 0,
		&rh_census_operations, census);
	if (!census->device)
		return -1;
	census->volume = ntfs_device_mount(census->device,
		diagnostic_flags | NTFS_MNT_RDONLY | NTFS_MNT_FORENSIC |
		NTFS_MNT_FS_NO_REPAIR);
	if (!census->volume)
		goto fail;
	if (!NDevReadOnly(census->volume->dev) ||
			census->volume->dev->d_roothealth_plan_write) {
		errno = EPERM;
		goto fail;
	}
	return 0;
fail:
	{
		int saved_errno = errno ? errno : EIO;
	if (census->volume) {
		ntfs_umount(census->volume, TRUE);
		census->volume = NULL;
		census->device = NULL;
	} else if (census->device) {
		if (NDevOpen(census->device))
			census->device->d_ops->close(census->device);
		ntfs_device_free(census->device);
		census->device = NULL;
	}
		errno = saved_errno;
	}
	return -1;
}

int rh_census_device_unmount(struct rh_census_device *census)
{
	int result = 0;
	int saved_errno;

	if (!census) {
		errno = EINVAL;
		return -1;
	}
	saved_errno = census->failure_errno;
	if (census->volume) {
		if (ntfs_umount(census->volume, TRUE)) {
			result = -1;
			if (!saved_errno)
				saved_errno = errno ? errno : EIO;
		}
		census->volume = NULL;
		census->device = NULL;
	} else if (census->device) {
		if (NDevOpen(census->device) &&
				census->device->d_ops->close(census->device)) {
			result = -1;
			if (!saved_errno)
				saved_errno = errno ? errno : EIO;
		}
		ntfs_device_free(census->device);
		census->device = NULL;
	}
	if (census->failed) {
		result = -1;
		if (!saved_errno)
			saved_errno = EIO;
	}
	if (result) {
		errno = saved_errno ? saved_errno : EIO;
		return -1;
	}
	return 0;
}

int rh_census_device_failed(const struct rh_census_device *census)
{
	return !census || census->failed;
}
