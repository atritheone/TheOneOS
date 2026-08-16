#include "config.h"

#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#include "bootsect.h"
#include "endians.h"
#include "layout.h"
#include "mst.h"
#include "roothealth_hash_stream.h"
#include "roothealth_repair.h"

#define TEST_RUN_COUNT 129U

static int read_exact(int fd, uint64_t offset, void *buffer, size_t length)
{
	unsigned char *bytes = buffer;
	size_t done = 0;

	while (done < length) {
		ssize_t got = pread(fd, bytes + done, length - done,
			(off_t)(offset + done));

		if (got <= 0)
			return -1;
		done += (size_t)got;
	}
	return 0;
}

static int write_exact(int fd, uint64_t offset, const void *buffer,
		size_t length)
{
	const unsigned char *bytes = buffer;
	size_t done = 0;

	while (done < length) {
		ssize_t put = pwrite(fd, bytes + done, length - done,
			(off_t)(offset + done));

		if (put <= 0)
			return -1;
		done += (size_t)put;
	}
	return 0;
}

static int hash_file(const char *path, unsigned char output[32])
{
	struct rh_hash_stream stream;
	unsigned char *buffer;
	int fd, result = -1;

	fd = open(path, O_RDONLY | O_CLOEXEC);
	if (fd < 0)
		return -1;
	buffer = malloc(1024U * 1024U);
	if (!buffer)
		goto out;
	rh_hash_stream_init(&stream);
	for (;;) {
		ssize_t got = read(fd, buffer, 1024U * 1024U);

		if (got < 0) {
			if (errno == EINTR)
				continue;
			goto out_buffer;
		}
		if (!got)
			break;
		if (rh_hash_stream_update(&stream, buffer, (size_t)got))
			goto out_buffer;
	}
	if (!rh_hash_stream_final(&stream, output))
		result = 0;
out_buffer:
	free(buffer);
out:
	close(fd);
	return result;
}

static size_t signed_width(int64_t value)
{
	size_t width;

	for (width = 1; width < sizeof(value); width++) {
		unsigned int bits = (unsigned int)(width * 8U - 1U);
		int64_t minimum = -(INT64_C(1) << bits);
		int64_t maximum = (INT64_C(1) << bits) - 1;

		if (value >= minimum && value <= maximum)
			return width;
	}
	return sizeof(value);
}

static int build_pairs(unsigned char *pairs, size_t capacity,
		uint64_t mft_lcn, uint64_t volume_clusters, size_t *length_out)
{
	uint64_t far_lcn = volume_clusters / 2U;
	int64_t previous = 0;
	size_t used = 0;
	unsigned int i;

	if (!mft_lcn || mft_lcn > INT64_MAX || far_lcn > INT64_MAX ||
		far_lcn <= mft_lcn || TEST_RUN_COUNT - 2U >
		(volume_clusters - far_lcn - 1U) / 2U)
		return -1;
	for (i = 0; i < TEST_RUN_COUNT; i++) {
		uint64_t current = !i ? mft_lcn : far_lcn + 2U * (i - 1U);
		int64_t delta = (int64_t)current - previous;
		size_t width = signed_width(delta), j;

		if (used > capacity || 2U + width > capacity - used)
			return -1;
		pairs[used++] = (unsigned char)((width << 4) | 1U);
		pairs[used++] = 1U;
		for (j = 0; j < width; j++)
			pairs[used++] = (unsigned char)((uint64_t)delta >> (8U * j));
		previous = (int64_t)current;
	}
	if (used == capacity)
		return -1;
	pairs[used++] = 0;
	*length_out = used;
	return 0;
}

static ATTR_RECORD *find_attribute(unsigned char *record, uint32_t used,
		uint32_t wanted)
{
	MFT_RECORD *mft = (MFT_RECORD *)record;
	ATTR_RECORD *attribute = (ATTR_RECORD *)(record +
		le16_to_cpu(mft->attrs_offset));

	while ((unsigned char *)attribute + sizeof(attribute->type) <=
			record + used && attribute->type != AT_END) {
		uint32_t length = le32_to_cpu(attribute->length);

		if (length < 24U || (length & 7U) ||
			(unsigned char *)attribute + length > record + used)
			return NULL;
		if (le32_to_cpu(attribute->type) == wanted)
			return attribute;
		attribute = (ATTR_RECORD *)((unsigned char *)attribute + length);
	}
	return NULL;
}

static int expand_mft_mapping(int fd, uint64_t offset,
		uint32_t record_size, uint32_t cluster_size, uint64_t mft_lcn,
		uint64_t volume_clusters)
{
	unsigned char record[ROOTHEALTH_SUPPORTED_MFT_RECORD_SIZE];
	unsigned char pairs[512];
	MFT_RECORD *mft = (MFT_RECORD *)record;
	ATTR_RECORD *data, *bitmap;
	uint32_t used, old_length, new_length, growth;
	size_t pair_length;
	uint64_t allocated, records, bitmap_bytes;

	if (record_size != sizeof(record) || read_exact(fd, offset, record,
			sizeof(record)) ||
		ntfs_mst_post_read_fixup((NTFS_RECORD *)record, sizeof(record)) ||
		mft->magic != magic_FILE ||
		le32_to_cpu(mft->mft_record_number) != FILE_MFT)
		return -1;
	used = le32_to_cpu(mft->bytes_in_use);
	data = find_attribute(record, used, 0x80U);
	bitmap = find_attribute(record, used, 0xb0U);
	if (!data || !bitmap || !data->non_resident || !bitmap->non_resident ||
		build_pairs(pairs, sizeof(pairs), mft_lcn, volume_clusters,
			&pair_length))
		return -1;
	old_length = le32_to_cpu(data->length);
	new_length = (uint32_t)((64U + pair_length + 7U) & ~7U);
	if (new_length <= old_length)
		return -1;
	growth = new_length - old_length;
	if (used > sizeof(record) || growth > sizeof(record) - used)
		return -1;
	memmove((unsigned char *)data + new_length,
		(const unsigned char *)data + old_length,
		(size_t)(record + used - ((unsigned char *)data + old_length)));
	memset((unsigned char *)data + 64U, 0, new_length - 64U);
	memcpy((unsigned char *)data + 64U, pairs, pair_length);
	data->length = cpu_to_le32(new_length);
	data->highest_vcn = cpu_to_sle64(TEST_RUN_COUNT - 1U);
	allocated = (uint64_t)TEST_RUN_COUNT * cluster_size;
	data->allocated_size = cpu_to_sle64(allocated);
	data->data_size = cpu_to_sle64(allocated);
	data->initialized_size = cpu_to_sle64(allocated);
	used += growth;
	mft->bytes_in_use = cpu_to_le32(used);
	bitmap = find_attribute(record, used, 0xb0U);
	if (!bitmap)
		return -1;
	records = allocated / record_size;
	bitmap_bytes = (records + 7U) / 8U;
	bitmap->data_size = cpu_to_sle64(bitmap_bytes);
	bitmap->initialized_size = cpu_to_sle64(bitmap_bytes);
	if (ntfs_mst_pre_write_fixup((NTFS_RECORD *)record, sizeof(record)) ||
		write_exact(fd, offset, record, sizeof(record)))
		return -1;
	return 0;
}

static int prepare_fixture(const char *path, uint64_t *serial_out)
{
	NTFS_BOOT_SECTOR boot;
	uint64_t sectors, volume_clusters, primary_offset, mirror_offset;
	uint32_t sector_size, cluster_size, record_size;
	int fd, result = -1;

	fd = open(path, O_RDWR | O_CLOEXEC);
	if (fd < 0)
		return -1;
	if (read_exact(fd, 0, &boot, sizeof(boot)))
		goto out;
	sector_size = le16_to_cpu(boot.bpb.bytes_per_sector);
	cluster_size = sector_size * boot.bpb.sectors_per_cluster;
	record_size = ROOTHEALTH_SUPPORTED_MFT_RECORD_SIZE;
	sectors = (uint64_t)sle64_to_cpu(boot.number_of_sectors);
	if (sector_size != ROOTHEALTH_SUPPORTED_SECTOR_SIZE ||
		cluster_size != ROOTHEALTH_SUPPORTED_CLUSTER_SIZE || !sectors)
		goto out;
	volume_clusters = sectors / boot.bpb.sectors_per_cluster;
	primary_offset = (uint64_t)sle64_to_cpu(boot.mft_lcn) * cluster_size;
	mirror_offset = (uint64_t)sle64_to_cpu(boot.mftmirr_lcn) * cluster_size;
	if (expand_mft_mapping(fd, primary_offset, record_size, cluster_size,
			(uint64_t)sle64_to_cpu(boot.mft_lcn), volume_clusters) ||
		expand_mft_mapping(fd, mirror_offset, record_size, cluster_size,
			(uint64_t)sle64_to_cpu(boot.mft_lcn), volume_clusters) ||
		fsync(fd))
		goto out;
	*serial_out = le64_to_cpu(boot.volume_serial_number);
	result = 0;
out:
	close(fd);
	return result;
}

static int run_foundation(const char *path, uint64_t serial, int inject_oom,
		size_t *operations_out)
{
	struct rh_writer writer;
	struct rh_identity_result identity;
	struct rh_boot_result boot;
	struct rh_mirror_result mirror;
	int result;

	if (inject_oom && setenv("ROOTHEALTH_REPAIR_TEST_FAIL",
			"bootstrap-runs-oom", 1))
		return RH_RESULT_INTERNAL;
	if (!inject_oom)
		unsetenv("ROOTHEALTH_REPAIR_TEST_FAIL");
	if (rh_writer_open(&writer, path))
		return RH_RESULT_IO;
	result = roothealth_bootstrap_boot_plan(&writer, serial, NULL, &identity,
		&boot);
	if (result == RH_RESULT_OK && !writer.operation_count)
		result = roothealth_mftmirr_plan(&writer, &boot.geometry, &mirror);
	*operations_out = writer.operation_count;
	rh_writer_close(&writer);
	unsetenv("ROOTHEALTH_REPAIR_TEST_FAIL");
	return result;
}

int main(int argc, char **argv)
{
	struct timespec start, finish;
	unsigned char before_hash[32], after_hash[32];
	uint64_t serial;
	double elapsed;
	size_t operations = 0, oom_operations = 0;
	size_t i;
	int result, oom_result, scale_result, overlap_result;

	if (argc != 2 || prepare_fixture(argv[1], &serial) ||
		hash_file(argv[1], before_hash))
		return 5;
	unsetenv("ROOTHEALTH_REPAIR_TEST_FAIL");
	if (clock_gettime(CLOCK_MONOTONIC, &start))
		return 5;
	scale_result = roothealth_bootstrap_test_run_intervals(262144U, 0);
	if (clock_gettime(CLOCK_MONOTONIC, &finish))
		return 5;
	elapsed = (double)(finish.tv_sec - start.tv_sec) +
		(double)(finish.tv_nsec - start.tv_nsec) / 1000000000.0;
	overlap_result = roothealth_bootstrap_test_run_intervals(262144U, 1);
	result = run_foundation(argv[1], serial, 0, &operations);
	oom_result = run_foundation(argv[1], serial, 1, &oom_operations);
	if (hash_file(argv[1], after_hash))
		return 5;
	if (result != RH_RESULT_OK || operations ||
		oom_result != RH_RESULT_INTERNAL || oom_operations ||
		scale_result != RH_RESULT_OK || overlap_result != RH_RESULT_UNSAFE ||
		elapsed > 10.0 || memcmp(before_hash, after_hash,
			sizeof(before_hash))) {
		fprintf(stderr, "runs=%u result=%d operations=%zu oom=%d "
			"oom_operations=%zu scale=%d overlap=%d seconds=%.6f\n",
			TEST_RUN_COUNT, result, operations, oom_result, oom_operations,
			scale_result, overlap_result, elapsed);
		return 1;
	}
	printf("bootstrap-runs runs=%u result=%d oom=%d operations=0 "
		"scale-runs=262144 overlap=refused seconds=%.6f source-sha256=",
		TEST_RUN_COUNT, result, oom_result, elapsed);
	for (i = 0; i < sizeof(after_hash); i++)
		printf("%02x", after_hash[i]);
	printf(" source-writes=0\n");
	return 0;
}
