/* ROOTHEALTH_REPAIR_ROLE(DIAGNOSTIC) */
#include "config.h"

#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#include "device.h"
#include "roothealth_census_device.h"
#include "roothealth_write.h"

#ifdef RH_CENSUS_DEVICE_TEST_STUB_PREIMAGE
uint64_t rh_wal_preimage_size(
		const struct rh_wal_preimage *preimage __attribute__((unused)))
{
	return 0;
}

int rh_wal_preimage_read(
		const struct rh_wal_preimage *preimage __attribute__((unused)),
		uint64_t offset __attribute__((unused)),
		size_t length __attribute__((unused)),
		void *buffer __attribute__((unused)))
{
	errno = EINVAL;
	return -1;
}

int rh_wal_preimage_range_excluded(
		const struct rh_wal_preimage *preimage __attribute__((unused)),
		uint64_t offset __attribute__((unused)),
		uint64_t length __attribute__((unused)),
		int *excluded __attribute__((unused)))
{
	errno = EINVAL;
	return -1;
}
#endif

struct file_reader {
	int fd;
};

static int file_read(const struct rh_census_reader *view, uint64_t offset,
		size_t length, void *buffer)
{
	const struct file_reader *reader = view->context;
	unsigned char *out = buffer;

	while (length) {
		ssize_t got = pread(reader->fd, out, length, (off_t)offset);

		if (got < 0) {
			if (errno == EINTR)
				continue;
			return -1;
		}
		if (!got) {
			errno = EIO;
			return -1;
		}
		out += got;
		offset += (uint64_t)got;
		length -= (size_t)got;
	}
	return 0;
}

static int file_stat(const struct rh_census_reader *view, struct stat *status)
{
	const struct file_reader *reader = view->context;

	return fstat(reader->fd, status);
}

int main(int argc, char **argv)
{
	struct rh_writer writer;
	struct rh_census_reader initial_reader, staged_reader, immutable_reader;
	struct rh_census_reader invalid_reader;
	struct rh_census_device first, second, faulted;
	struct file_reader file;
	struct stat status;
	unsigned char first_boot[512], second_boot[512];
	uint64_t serial = 0;
	s64 clusters;
	unsigned char byte = 0;
	unsigned char original, replacement, observed_initial, observed_staged;
	uint64_t staged_offset;
	unsigned int i;
	int result = 1;

	memset(&writer, 0, sizeof(writer));
	memset(&first, 0, sizeof(first));
	memset(&second, 0, sizeof(second));
	memset(&faulted, 0, sizeof(faulted));
	file.fd = -1;
	if (argc != 2)
		return 5;
	if (rh_writer_open(&writer, argv[1]) ||
			rh_census_reader_from_writer_prefix(&writer, 0, &initial_reader) ||
			rh_census_device_mount(&first, &initial_reader, 0))
		goto out;
	if (first.volume->dev->d_ops->pread(first.volume->dev, first_boot,
			sizeof(first_boot), 0) != (s64)sizeof(first_boot))
		goto out;
	for (i = 0; i < 8U; i++)
		serial |= (uint64_t)first_boot[72U + i] << (8U * i);
	clusters = first.volume->nr_clusters;
	errno = 0;
	if (first.volume->dev->d_ops->pwrite(first.volume->dev, &byte, 1, 0) >= 0 ||
			errno != EPERM || first.volume->dev->d_roothealth_plan_write ||
			writer.write_boundaries)
		goto out;
	if (rh_census_device_unmount(&first))
		goto out;
	staged_offset = writer.device_size - 512U;
	if (rh_census_reader_read_exact(&initial_reader, staged_offset, 1,
			&original))
		goto out;
	replacement = original ^ 0x80U;
	if (rh_writer_plan(&writer, RH_WRITE_BOOT_BACKUP, staged_offset, 1,
			&replacement) || writer.operation_count != 1U ||
			rh_census_reader_from_writer_prefix(&writer, 1, &staged_reader) ||
			rh_census_reader_read_exact(&initial_reader, staged_offset, 1,
				&observed_initial) ||
			rh_census_reader_read_exact(&staged_reader, staged_offset, 1,
				&observed_staged) || observed_initial != original ||
			observed_staged != replacement)
		goto out;
	errno = 0;
	if (!rh_census_reader_from_writer_prefix(&writer, 2, &invalid_reader) ||
			errno != EINVAL)
		goto out;
	file.fd = open(argv[1], O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
	if (file.fd < 0 || fstat(file.fd, &status) || status.st_size <= 0)
		goto out;
	memset(&immutable_reader, 0, sizeof(immutable_reader));
	immutable_reader.context = &file;
	immutable_reader.device_size = (uint64_t)status.st_size;
	immutable_reader.source = RH_CENSUS_READER_IMMUTABLE;
	immutable_reader.read = file_read;
	immutable_reader.stat = file_stat;
	if (rh_census_device_mount(&second, &immutable_reader, 0) ||
			second.volume->nr_clusters != clusters ||
			second.volume->dev->d_roothealth_plan_write ||
			rh_census_device_failed(&second))
		goto out;
	if (second.volume->dev->d_ops->pread(second.volume->dev, second_boot,
			sizeof(second_boot), 0) != (s64)sizeof(second_boot) ||
			memcmp(first_boot, second_boot, sizeof(first_boot)))
		goto out;
	if (rh_census_device_unmount(&second) ||
			rh_census_device_mount(&faulted, &immutable_reader, 0) ||
			setenv("ROOTHEALTH_REPAIR_TEST_FAIL", "census-unmount", 1))
		goto out;
	errno = 0;
	if (!rh_census_device_unmount(&faulted) || errno != EIO ||
			unsetenv("ROOTHEALTH_REPAIR_TEST_FAIL"))
		goto out;
	printf("census-device serial=%016llx clusters=%lld planning=readonly "
		"recovery=immutable prefix0=%02x prefix1=%02x "
		"wrong-prefix=refused unmount-fault=closed writes=refused "
		"source-writes=0\n",
		(unsigned long long)serial, (long long)clusters, original,
		observed_staged);
	result = 0;
out:
	unsetenv("ROOTHEALTH_REPAIR_TEST_FAIL");
	(void)rh_census_device_unmount(&faulted);
	(void)rh_census_device_unmount(&second);
	(void)rh_census_device_unmount(&first);
	if (file.fd >= 0)
		close(file.fd);
	rh_writer_close(&writer);
	return result;
}
