/* ROOTHEALTH_REPAIR_ROLE(TEST_FIXTURE_BUILDER) */
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

static uint16_t get_u16le(const unsigned char *bytes)
{
	return (uint16_t)bytes[0] | (uint16_t)bytes[1] << 8;
}

static uint64_t get_u64le(const unsigned char *bytes)
{
	uint64_t value = 0;
	unsigned int i;

	for (i = 0; i < 8U; i++)
		value |= (uint64_t)bytes[i] << (8U * i);
	return value;
}

static void put_u16le(unsigned char *bytes, uint16_t value)
{
	bytes[0] = (unsigned char)value;
	bytes[1] = (unsigned char)(value >> 8);
}

int main(int argc, char **argv)
{
	static const unsigned char attrdef_name[] = {
		'$', 0, 'A', 0, 't', 0, 't', 0, 'r', 0, 'D', 0, 'e', 0,
		'f', 0
	};
	struct stat status;
	unsigned char *image = MAP_FAILED;
	uint64_t cluster_size, record_size, mft_offset, record_offset;
	uint64_t mft_lcn;
	unsigned long parsed;
	size_t at, match = SIZE_MAX, matches = 0;
	uint16_t old_sequence, new_sequence;
	int fd = -1, result = 1;
	char *end = NULL;

	if (argc != 3)
		return 2;
	errno = 0;
	parsed = strtoul(argv[2], &end, 0);
	if (errno || !end || *end || !parsed || parsed > UINT16_MAX)
		return 2;
	new_sequence = (uint16_t)parsed;
	fd = open(argv[1], O_RDWR | O_CLOEXEC);
	if (fd < 0 || fstat(fd, &status) || status.st_size < 512)
		goto out;
	image = mmap(NULL, (size_t)status.st_size, PROT_READ | PROT_WRITE,
		MAP_SHARED, fd, 0);
	if (image == MAP_FAILED)
		goto out;
	cluster_size = (uint64_t)get_u16le(image + 11U) * image[13U];
	mft_lcn = get_u64le(image + 48U);
	if (!cluster_size || !mft_lcn)
		goto out;
	if ((int8_t)image[64U] < 0)
		record_size = UINT64_C(1) << (unsigned int)(-(int8_t)image[64U]);
	else
		record_size = cluster_size * image[64U];
	if (record_size != 1024U || mft_lcn > UINT64_MAX / cluster_size)
		goto out;
	mft_offset = mft_lcn * cluster_size;
	if (mft_offset > UINT64_MAX - 4U * record_size)
		goto out;
	record_offset = mft_offset + 4U * record_size;
	if (record_offset > (uint64_t)status.st_size - record_size ||
		memcmp(image + record_offset, "FILE", 4U))
		goto out;
	old_sequence = get_u16le(image + record_offset + 16U);
	if (!old_sequence || old_sequence == new_sequence)
		goto out;
	for (at = 82U; at <= (size_t)status.st_size - sizeof(attrdef_name);
			at++) {
		uint64_t indexed_reference;

		if (memcmp(image + at, attrdef_name, sizeof(attrdef_name)))
			continue;
		indexed_reference = get_u64le(image + at - 82U);
		if ((indexed_reference & UINT64_C(0xffffffffffff)) != 4U ||
				(uint16_t)(indexed_reference >> 48) != old_sequence)
			continue;
		match = at - 82U;
		matches++;
	}
	if (matches != 1U)
		goto out;
	put_u16le(image + record_offset + 16U, new_sequence);
	put_u16le(image + match + 6U, new_sequence);
	if (msync(image, (size_t)status.st_size, MS_SYNC) || fsync(fd))
		goto out;
	printf("fixed-sequence record=4 old=%u new=%u i30-offset=%zu\n",
		(unsigned int)old_sequence, (unsigned int)new_sequence, match);
	result = 0;
out:
	if (image != MAP_FAILED && munmap(image, (size_t)status.st_size) && !result)
		result = 1;
	if (fd >= 0 && close(fd) && !result)
		result = 1;
	return result;
}
