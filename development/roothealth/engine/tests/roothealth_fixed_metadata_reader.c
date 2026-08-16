/* ROOTHEALTH_REPAIR_ROLE(DIAGNOSTIC) */
#include "config.h"

#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#include "endians.h"
#include "layout.h"
#include "roothealth_census_device.h"
#include "roothealth_fixed_metadata_reader.h"
#include "roothealth_hash_stream.h"
#include "roothealth_raw_mft.h"
#include "roothealth_write.h"

struct fault_reader {
	struct rh_census_reader base;
	uint64_t target;
	int fail;
};

static int fault_read(const struct rh_census_reader *reader, uint64_t offset,
		size_t length, void *buffer)
{
	const struct fault_reader *fault = reader->context;

	if (fault->target >= offset && fault->target - offset < length) {
		if (fault->fail) {
			errno = EIO;
			return -1;
		}
		if (fault->base.read(&fault->base, offset, length, buffer))
			return -1;
		((unsigned char *)buffer)[fault->target - offset] ^= 1U;
		return 0;
	}
	return fault->base.read(&fault->base, offset, length, buffer);
}

static int file_hash(int fd, uint64_t size, unsigned char output[32])
{
	struct rh_hash_stream hash;
	unsigned char buffer[65536];
	uint64_t offset = 0;

	rh_hash_stream_init(&hash);
	while (offset < size) {
		size_t part = sizeof(buffer);
		ssize_t got;

		if ((uint64_t)part > size - offset)
			part = (size_t)(size - offset);
		got = pread(fd, buffer, part, (off_t)offset);
		if (got != (ssize_t)part ||
				rh_hash_stream_update(&hash, buffer, part))
			return -1;
		offset += part;
	}
	return rh_hash_stream_final(&hash, output);
}

static void hex(const unsigned char digest[32], char output[65])
{
	static const char digits[] = "0123456789abcdef";
	size_t i;

	for (i = 0; i < 32U; i++) {
		output[2U * i] = digits[digest[i] >> 4];
		output[2U * i + 1U] = digits[digest[i] & 15U];
	}
	output[64] = 0;
}

static int clean_exact(const struct rh_fixed_metadata_reader_census *census)
{
	const struct rh_fixed_metadata_reader_entry *attrdef = &census->entries[0];
	const struct rh_fixed_metadata_reader_entry *upcase = &census->entries[1];

	return census->version == RH_FIXED_METADATA_READER_VERSION &&
		census->complete && census->no_io_uncertainty &&
		census->entries_expected == 2U && census->entries_completed == 2U &&
		census->entries_passed == 2U && !census->entries_failed &&
		!census->entries_io && census->volume_serial &&
		attrdef->kind == RH_FIXED_METADATA_READER_ATTRDEF &&
		attrdef->state == RH_FIXED_METADATA_READER_PASS &&
		attrdef->owner_record == 4U && attrdef->owner_sequence &&
		attrdef->expected_size == RH_FIXED_METADATA_ATTRDEF_SIZE &&
		attrdef->data_size == attrdef->expected_size &&
		attrdef->initialized_size == attrdef->expected_size &&
		attrdef->allocated_size == 4096U && attrdef->mapping_complete &&
		attrdef->current_hash_valid &&
		!memcmp(attrdef->current_hash, attrdef->canonical_hash, 32U) &&
		upcase->kind == RH_FIXED_METADATA_READER_UPCASE &&
		upcase->state == RH_FIXED_METADATA_READER_PASS &&
		upcase->owner_record == 10U && upcase->owner_sequence &&
		upcase->expected_size == RH_FIXED_METADATA_UPCASE_SIZE &&
		upcase->data_size == upcase->expected_size &&
		upcase->initialized_size == upcase->expected_size &&
		upcase->allocated_size == RH_FIXED_METADATA_UPCASE_SIZE &&
		upcase->mapping_complete && upcase->current_hash_valid &&
		!memcmp(upcase->current_hash, upcase->canonical_hash, 32U);
}

static void make_fault_reader(const struct rh_census_reader *base,
		struct fault_reader *fault, uint64_t target, int fail,
		struct rh_census_reader *reader)
{
	memset(fault, 0, sizeof(*fault));
	fault->base = *base;
	fault->target = target;
	fault->fail = fail;
	memset(reader, 0, sizeof(*reader));
	reader->context = fault;
	reader->device_size = base->device_size;
	reader->source = RH_CENSUS_READER_WRITER_PREFIX;
	reader->writer_operation_count = 0;
	reader->read = fault_read;
}

int main(int argc, char **argv)
{
	const uint64_t generation = UINT64_C(0x4649584544520001);
	struct rh_writer writer;
	struct rh_census_reader reader, changed_reader, failed_reader;
	struct rh_census_device device;
	struct rh_raw_mft_census raw, altered;
	struct rh_raw_attribute *altered_attributes = NULL;
	struct rh_fixed_metadata_reader_census clean, changed, failed, shaped;
	struct fault_reader change_fault, io_fault;
	struct rh_raw_mft_ref upcase;
	struct stat status;
	unsigned char before[32], after[32];
	char attrdef_hex[65], upcase_hex[65], evidence_hex[65];
	uint64_t physical;
	size_t i;
	int opened = 0, mounted = 0, stage = 0, result = 1;

	memset(&writer, 0, sizeof(writer));
	memset(&device, 0, sizeof(device));
	memset(&raw, 0, sizeof(raw));
	if (argc != 2 || rh_writer_open(&writer, argv[1]))
		goto out;
	opened = 1;
	if (fstat(writer.read_fd, &status) || status.st_size <= 0 ||
			file_hash(writer.read_fd, writer.device_size, before) ||
			rh_census_reader_from_writer_prefix(&writer, 0, &reader) ||
			rh_census_device_mount(&device, &reader, 0))
		goto out;
	mounted = 1;
	stage = 1;
	if (rh_raw_mft_census_run_reader(device.volume, &reader, generation, &raw))
		goto out;
	stage = 2;
	if (rh_fixed_metadata_reader_census_run(&reader, &raw, &clean) ||
			!clean_exact(&clean))
		goto out;
	stage = 3;
	upcase.record = 10U;
	upcase.sequence = raw.slots[10U].sequence;
	if (!upcase.sequence || rh_raw_mft_map_stream_range(&raw, upcase,
			le32_to_cpu(AT_DATA), NULL, 0U, 257U, 1U, &physical))
		goto out;
	make_fault_reader(&reader, &change_fault, physical, 0, &changed_reader);
	if (rh_fixed_metadata_reader_census_run(&changed_reader, &raw, &changed) ||
			changed.entries_passed != 1U || changed.entries_failed != 1U ||
			changed.entries_io || !changed.no_io_uncertainty ||
			changed.entries[0].state != RH_FIXED_METADATA_READER_PASS ||
			changed.entries[1].state != RH_FIXED_METADATA_READER_FAIL ||
			!changed.entries[1].mapping_complete ||
			!changed.entries[1].current_hash_valid ||
			!memcmp(changed.entries[1].current_hash,
				changed.entries[1].canonical_hash, 32U) ||
			memcmp(changed.entries[1].mapping_hash,
				clean.entries[1].mapping_hash, 32U))
		goto out;
	stage = 4;
	make_fault_reader(&reader, &io_fault, physical, 1, &failed_reader);
	if (rh_fixed_metadata_reader_census_run(&failed_reader, &raw, &failed) ||
			failed.entries_passed != 1U || failed.entries_failed ||
			failed.entries_io != 1U || failed.no_io_uncertainty ||
			failed.entries[0].state != RH_FIXED_METADATA_READER_PASS ||
			failed.entries[1].state != RH_FIXED_METADATA_READER_IO ||
			failed.entries[1].current_hash_valid)
		goto out;
	stage = 5;
	altered = raw;
	altered_attributes = malloc(raw.attribute_count *
		sizeof(*altered_attributes));
	if (!altered_attributes)
		goto out;
	memcpy(altered_attributes, raw.attributes,
		raw.attribute_count * sizeof(*altered_attributes));
	altered.attributes = altered_attributes;
	for (i = 0; i < altered.attribute_count; i++) {
		struct rh_raw_attribute *attribute = &altered.attributes[i];

		if (attribute->owner.record == 10U &&
				attribute->owner.sequence == upcase.sequence &&
				attribute->type == le32_to_cpu(AT_DATA) &&
				!attribute->name_length && !attribute->lowest_vcn) {
			attribute->data_size--;
			break;
		}
	}
	if (i == altered.attribute_count ||
			rh_fixed_metadata_reader_census_run(&reader, &altered, &shaped) ||
			shaped.entries_passed != 1U || shaped.entries_failed != 1U ||
			shaped.entries_io ||
			shaped.entries[1].state != RH_FIXED_METADATA_READER_FAIL ||
			shaped.entries[1].mapping_complete ||
			shaped.entries[1].current_hash_valid ||
			!memcmp(shaped.entries[1].mapping_hash,
				clean.entries[1].mapping_hash, 32U))
		goto out;
	stage = 6;
	if (writer.operation_count ||
			file_hash(writer.read_fd, writer.device_size, after) ||
			memcmp(before, after, sizeof(before)))
		goto out;
	hex(clean.entries[0].current_hash, attrdef_hex);
	hex(clean.entries[1].current_hash, upcase_hex);
	hex(clean.evidence_hash, evidence_hex);
	printf("fixed-metadata-reader pass=2 fail-tamper=1 io-fault=1 "
		"shape-refusal=1 attrdef=%s upcase=%s evidence=%s writes=0\n",
		attrdef_hex, upcase_hex, evidence_hex);
	result = 0;
out:
	if (result)
		fprintf(stderr, "fixed-metadata-reader stage=%d errno=%d\n",
			stage, errno);
	free(altered_attributes);
	rh_raw_mft_census_release(&raw);
	if (mounted && rh_census_device_unmount(&device))
		result = 1;
	if (opened)
		rh_writer_close(&writer);
	return result;
}
