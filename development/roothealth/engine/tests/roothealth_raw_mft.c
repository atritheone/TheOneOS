#include "config.h"

#include <errno.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#include "device.h"
#include "endians.h"
#include "layout.h"
#include "mft.h"
#include "roothealth_raw_mft.h"
#include "roothealth_write.h"
#include "volume.h"

static int parse_count(const char *text, uint64_t *value)
{
	char *end = NULL;

	errno = 0;
	*value = strtoull(text, &end, 10);
	return errno || !end || *end;
}

static void digest_hex(const unsigned char digest[32], char output[65])
{
	static const char hex[] = "0123456789abcdef";
	size_t i;

	for (i = 0; i < 32U; i++) {
		output[i * 2U] = hex[digest[i] >> 4];
		output[i * 2U + 1U] = hex[digest[i] & 15U];
	}
	output[64] = 0;
}

int main(int argc, char **argv)
{
	struct rh_writer writer;
	struct rh_raw_mft_census census;
	ntfs_volume *volume = NULL;
	uint64_t expected[9] = { 0 };
	uint64_t live;
	char hash[65];
	int result = 1;
	int i;

	if (argc != 10 && argc != 11)
		return 5;
	for (i = 0; i < argc - 2; i++)
		if (parse_count(argv[i + 2], &expected[i]))
			return 5;
	if (rh_writer_open(&writer, argv[1]))
		return 3;
	volume = ntfs_mount(argv[1], NTFS_MNT_RDONLY | NTFS_MNT_FORENSIC |
		NTFS_MNT_FS_NO_REPAIR);
	if (!volume || !NDevReadOnly(volume->dev))
		goto out;
	if (rh_raw_mft_census_run(volume, &writer, 1, &census))
		goto out;
	live = census.live_base_records + census.live_extent_records;
	if (!census.records_bounded ||
			census.records_complete != !expected[8] ||
			census.layout_complete != !expected[8] ||
			census.layout_candidate_count != expected[8] ||
			!census.attribute_lists_complete ||
			!census.extents_complete || census.slots_expected != expected[0] ||
			live != expected[1] || census.free_records != expected[2] ||
			census.attribute_count != expected[3] ||
			census.resident_attributes != expected[4] ||
			census.nonresident_attributes != expected[5] ||
			census.run_count != expected[6] ||
			census.file_name_count != expected[7] ||
			census.slots_completed != census.slots_expected ||
			census.extents_completed != census.extents_expected ||
			census.runs_completed != census.runs_expected ||
			writer.write_boundaries) {
		fprintf(stderr, "observed slots=%"PRIu64" completed=%"PRIu64
			" live=%"PRIu64" free=%"PRIu64" unreadable=%"PRIu64
			" invalid=%"PRIu64" attrs=%zu resident=%"PRIu64
			" nonresident=%"PRIu64" extents=%"PRIu64"/%"PRIu64
			" runs=%zu fn=%zu lists=%zu layout=%zu "
			"complete=%u/%u/%u bounded=%u\n",
			census.slots_expected, census.slots_completed, live,
			census.free_records, census.unreadable_records,
			census.invalid_records, census.attribute_count,
			census.resident_attributes, census.nonresident_attributes,
			census.extents_completed, census.extents_expected,
			census.run_count, census.file_name_count,
			census.list_entry_count, census.layout_candidate_count,
			census.records_complete,
			census.attribute_lists_complete, census.extents_complete,
			census.records_bounded);
		for (i = 0; i < (int)census.slot_count; i++)
			if (census.slots[i].state == RH_RAW_SLOT_INVALID ||
					census.slots[i].state == RH_RAW_SLOT_UNREADABLE) {
				unsigned char raw_record[1024];
				MFT_RECORD *record = (MFT_RECORD *)raw_record;

				fprintf(stderr, "slot[%d]=%d\n", i,
					census.slots[i].state);
				if (!ntfs_mft_record_read(volume, i, record))
					fprintf(stderr, "  magic=%08x seq=%u usa=%u/%u "
						"links=%u attrs=%u flags=%x used=%u alloc=%u "
						"base=%"PRIx64" number=%u\n",
						le32_to_cpu(record->magic),
						le16_to_cpu(record->sequence_number),
						le16_to_cpu(record->usa_ofs),
						le16_to_cpu(record->usa_count),
						le16_to_cpu(record->link_count),
						le16_to_cpu(record->attrs_offset),
						le16_to_cpu(record->flags),
						le32_to_cpu(record->bytes_in_use),
						le32_to_cpu(record->bytes_allocated),
						le64_to_cpu(record->base_mft_record),
						le32_to_cpu(record->mft_record_number));
			}
		for (i = 0; i < (int)census.slot_count; i++)
			if (census.slots[i].state == RH_RAW_SLOT_LIVE_BASE &&
					census.slots[i].has_attribute_list &&
					!census.slots[i].attribute_list_assembled) {
				fprintf(stderr, "attribute-list-unassembled[%d] attrs=%zu "
					"entries=%zu errno=%d\n", i,
					census.slots[i].attribute_count,
					census.slots[i].list_entry_count, errno);
				break;
			}
		rh_raw_mft_census_release(&census);
		goto out;
	}
	digest_hex(census.census_hash, hash);
	printf("raw-mft slots=%"PRIu64" live=%"PRIu64" free=%"PRIu64
		" attrs=%zu resident=%"PRIu64" nonresident=%"PRIu64
		" extents=%"PRIu64" runs=%zu fn=%zu lists=%zu layout=%zu "
		"complete=%u/1/1 "
		"writes=0 hash=%s\n", census.slots_expected, live,
		census.free_records, census.attribute_count,
		census.resident_attributes, census.nonresident_attributes,
		census.extents_completed, census.run_count, census.file_name_count,
		census.list_entry_count, census.layout_candidate_count,
		census.records_complete, hash);
	rh_raw_mft_census_release(&census);
	result = 0;
out:
	if (volume && ntfs_umount(volume, FALSE) && !result)
		result = 1;
	rh_writer_close(&writer);
	return result;
}
