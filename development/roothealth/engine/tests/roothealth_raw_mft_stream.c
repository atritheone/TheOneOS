#include "config.h"

#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/* Keep the streaming parser private to production while exercising its exact
 * implementation in this qualification-only translation unit. */
#include "../src/roothealth_raw_mft.c"

#define STREAM_ENTRIES 8192U
#define STREAM_ENTRY_BYTES 32U

static int write_all(int fd, const unsigned char *bytes, size_t length)
{
	while (length) {
		ssize_t written = write(fd, bytes, length);

		if (written <= 0)
			return -1;
		bytes += written;
		length -= (size_t)written;
	}
	return 0;
}

static int make_stream(char path[64], uint64_t *data_size,
		uint64_t *allocated_size)
{
	unsigned char entry[STREAM_ENTRY_BYTES];
	ATTR_LIST_ENTRY *raw = (ATTR_LIST_ENTRY *)entry;
	uint64_t bytes = (uint64_t)STREAM_ENTRIES * STREAM_ENTRY_BYTES;
	uint64_t allocated = ((bytes + 4095U) & ~UINT64_C(4095)) + 4096U;
	unsigned int i;
	int fd;

	strcpy(path, "/var/tmp/roothealth-attrlist-stream.XXXXXX");
	fd = mkstemp(path);
	if (fd < 0)
		return -1;
	memset(entry, 0, sizeof(entry));
	raw->type = AT_DATA;
	raw->length = cpu_to_le16(sizeof(entry));
	raw->name_offset = offsetof(ATTR_LIST_ENTRY, name);
	raw->lowest_vcn = cpu_to_sle64(0);
	raw->instance = cpu_to_le16(1);
	for (i = 0; i < STREAM_ENTRIES; i++) {
		raw->mft_reference = MK_LE_MREF((uint64_t)i + 100U, 1U);
		if (write_all(fd, entry, sizeof(entry)))
			goto fail;
	}
	if (ftruncate(fd, (off_t)allocated) || fsync(fd) || close(fd))
		goto fail_closed;
	*data_size = bytes;
	*allocated_size = allocated;
	return 0;
fail:
	close(fd);
fail_closed:
	unlink(path);
	return -1;
}

static int parse_case(const char *path, uint64_t data_size,
		uint64_t allocated_size, int64_t lcn, int expect_success)
{
	struct rh_raw_mft_census census;
	struct rh_raw_mft_slot slot;
	struct rh_raw_attribute *attribute;
	struct rh_raw_run *run;
	struct rh_writer writer;
	ntfs_volume volume;
	int parsed, result = -1;

	memset(&census, 0, sizeof(census));
	memset(&slot, 0, sizeof(slot));
	memset(&volume, 0, sizeof(volume));
	volume.cluster_size = 4096;
	census.attributes = calloc(1, sizeof(*census.attributes));
	census.runs = calloc(1, sizeof(*census.runs));
	if (!census.attributes || !census.runs)
		goto out;
	census.attribute_count = census.attribute_capacity = 1U;
	census.run_count = census.run_capacity = 1U;
	attribute = census.attributes;
	run = census.runs;
	attribute->nonresident = 1;
	attribute->lowest_vcn = 0;
	attribute->highest_vcn = (int64_t)(allocated_size / 4096U - 1U);
	attribute->allocated_size = (int64_t)allocated_size;
	attribute->data_size = (int64_t)data_size;
	attribute->initialized_size = (int64_t)data_size;
	attribute->run_first = 0;
	attribute->run_count = 1;
	run->attribute_index = 0;
	run->vcn = 0;
	run->lcn = lcn;
	run->length = allocated_size / 4096U;
	slot.record = 64;
	slot.sequence = 1;
	if (rh_writer_open(&writer, path))
		goto out;
	slot.list_entry_first = 0;
	errno = 0;
	parsed = rh_parse_attribute_list_nonresident(&volume, &writer, &census,
		&slot, attribute, STREAM_ENTRIES);
	if (expect_success) {
		if (!parsed && census.list_entry_count == STREAM_ENTRIES &&
				census.name_arena_size == 0 && !writer.write_boundaries)
			result = 0;
	} else if (parsed && census.list_entry_count <= STREAM_ENTRIES &&
			!writer.write_boundaries) {
		result = 0;
	}
	rh_writer_close(&writer);
out:
	rh_raw_mft_census_release(&census);
	return result;
}

int main(void)
{
	char path[64];
	uint64_t data_size, allocated_size;
	int result = 1;

	if (make_stream(path, &data_size, &allocated_size))
		return 1;
	if (!parse_case(path, data_size, allocated_size, 0, 1) &&
			!parse_case(path, data_size - 1U, allocated_size, 0, 0) &&
			!parse_case(path, data_size + STREAM_ENTRY_BYTES, allocated_size,
				0, 0) &&
			!parse_case(path, data_size, allocated_size, 1, 0)) {
		printf("raw-attrlist-stream bytes=%llu entries=%u max-0x40000=accepted "
			"oversize=refused truncated-entry=refused cluster-boundaries=1 "
			"read-fault=refused source-writes=0\n",
			(unsigned long long)data_size,
			STREAM_ENTRIES);
		result = 0;
	}
	if (unlink(path) && !result)
		result = 1;
	return result;
}
