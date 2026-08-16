#ifndef ROOTHEALTH_CENSUS_DEVICE_H
#define ROOTHEALTH_CENSUS_DEVICE_H

#include <stddef.h>
#include <stdint.h>
#include <sys/stat.h>

#include "volume.h"

struct ntfs_device;
struct rh_writer;
struct rh_wal_preimage;
struct rh_census_reader;

typedef int (*rh_census_reader_read_fn)(const struct rh_census_reader *reader,
		uint64_t offset, size_t length, void *buffer);
typedef int (*rh_census_reader_stat_fn)(const struct rh_census_reader *reader,
		struct stat *status);
typedef int (*rh_census_reader_excluded_fn)(
		const struct rh_census_reader *reader, uint64_t offset,
		uint64_t length, int *excluded);

enum rh_census_reader_source {
	RH_CENSUS_READER_INVALID = 0,
	RH_CENSUS_READER_IMMUTABLE = 1,
	RH_CENSUS_READER_WRITER_PREFIX = 2,
	RH_CENSUS_READER_WAL_PREIMAGE = 3,
};

/* Immutable exact-length reader used by both planning and WAL recovery. */
struct rh_census_reader {
	const void *context;
	uint64_t device_size;
	enum rh_census_reader_source source;
	/* Exact staged prefix.  Meaningful only for a writer-backed reader. */
	size_t writer_operation_count;
	rh_census_reader_read_fn read;
	rh_census_reader_stat_fn stat;
	rh_census_reader_excluded_fn excluded;
};

struct rh_census_device {
	struct rh_census_reader reader;
	struct ntfs_device *device;
	ntfs_volume *volume;
	s64 position;
	int failed;
	int failure_errno;
};

int rh_census_reader_from_writer_prefix(const struct rh_writer *writer,
		size_t operation_count, struct rh_census_reader *reader);
int rh_census_reader_from_wal_preimage(
		const struct rh_wal_preimage *preimage,
		struct rh_census_reader *reader);
int rh_census_reader_read_exact(const struct rh_census_reader *reader,
		uint64_t offset, size_t length, void *buffer);
int rh_census_reader_is_pretransaction(const struct rh_census_reader *reader);
int rh_census_reader_range_excluded(const struct rh_census_reader *reader,
		uint64_t offset, uint64_t length, int *excluded);
int rh_census_device_mount(struct rh_census_device *device,
		const struct rh_census_reader *reader,
		ntfs_mount_flags diagnostic_flags);
int rh_census_device_unmount(struct rh_census_device *device);
int rh_census_device_failed(const struct rh_census_device *device);

#endif
