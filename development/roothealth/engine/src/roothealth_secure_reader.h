#ifndef ROOTHEALTH_SECURE_READER_H
#define ROOTHEALTH_SECURE_READER_H

#include <errno.h>
#include <stddef.h>
#include <stdint.h>

#include "roothealth_census_device.h"
#include "roothealth_write.h"

struct rh_secure_read_source {
	struct rh_writer *writer;
	const struct rh_census_reader *reader;
};

static inline int rh_secure_source_valid(
		const struct rh_secure_read_source *source)
{
	return source && !!source->writer != !!source->reader &&
		(source->writer ? source->writer->read_fd >= 0 &&
			source->writer->device_size : source->reader->context &&
			source->reader->read && source->reader->device_size);
}

static inline uint64_t rh_secure_source_size(
		const struct rh_secure_read_source *source)
{
	return source->writer ? source->writer->device_size :
		source->reader->device_size;
}

static inline int rh_secure_source_read(
		const struct rh_secure_read_source *source, uint64_t offset,
		size_t length, void *buffer)
{
	if (!rh_secure_source_valid(source)) {
		errno = EINVAL;
		return -1;
	}
	return source->writer ? rh_writer_read(source->writer, offset, length,
		buffer) : rh_census_reader_read_exact(source->reader, offset, length,
		buffer);
}

static inline int rh_secure_source_excluded(
		const struct rh_secure_read_source *source, uint64_t offset,
		uint64_t length)
{
	int excluded;

	if (!rh_secure_source_valid(source) || !length) {
		errno = EINVAL;
		return -1;
	}
	if (source->writer)
		return rh_writer_range_excluded(source->writer, offset, length) ? 1 : 0;
	if (rh_census_reader_range_excluded(source->reader, offset, length,
			&excluded))
		return -1;
	return excluded ? 1 : 0;
}

#endif
