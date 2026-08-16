#include "config.h"

#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "device.h"
#include "roothealth_raw_mft.h"
#include "roothealth_write.h"
#include "volume.h"

static int scan_candidate(const char *path, enum rh_raw_layout_reason reason,
		uint32_t offset, const unsigned char *replacement, size_t length)
{
	struct rh_raw_mft_census census;
	struct rh_writer writer;
	ntfs_volume *volume = NULL;
	const struct rh_raw_layout_candidate *candidate;
	int result = -1;

	if (rh_writer_open(&writer, path))
		return -1;
	volume = ntfs_mount(path, NTFS_MNT_RDONLY | NTFS_MNT_FORENSIC |
		NTFS_MNT_FS_NO_REPAIR);
	if (!volume || !NDevReadOnly(volume->dev) ||
			rh_raw_mft_census_run(volume, &writer, 1, &census))
		goto out;
	if (!census.records_bounded || census.records_complete ||
			census.layout_complete || !census.attribute_lists_complete ||
			!census.extents_complete || census.layout_candidate_count != 1U ||
			writer.write_boundaries)
		goto release;
	candidate = &census.layout_candidates[0];
	if (candidate->reason != reason || candidate->storage.record != 24U ||
			candidate->logical_offset != offset || candidate->length != length ||
			candidate->replacement_length != length ||
			memcmp(candidate->replacement, replacement, length) ||
			!memcmp(candidate->logical_record_before_hash,
				candidate->logical_record_after_hash, 32))
		goto release;
	result = 0;
release:
	rh_raw_mft_census_release(&census);
out:
	if (volume && ntfs_umount(volume, FALSE) && !result)
		result = -1;
	rh_writer_close(&writer);
	return result;
}

static int scan_historical_next(const char *path)
{
	struct rh_raw_mft_census census;
	struct rh_writer writer;
	ntfs_volume *volume = NULL;
	int result = -1;

	if (rh_writer_open(&writer, path))
		return -1;
	volume = ntfs_mount(path, NTFS_MNT_RDONLY | NTFS_MNT_FORENSIC |
		NTFS_MNT_FS_NO_REPAIR);
	if (!volume || !NDevReadOnly(volume->dev) ||
			rh_raw_mft_census_run(volume, &writer, 1, &census))
		goto out;
	if (census.records_complete && census.records_bounded &&
			census.layout_complete && census.attribute_lists_complete &&
			census.extents_complete && !census.layout_candidate_count &&
			!writer.write_boundaries)
		result = 0;
	rh_raw_mft_census_release(&census);
out:
	if (volume && ntfs_umount(volume, FALSE) && !result)
		result = -1;
	rh_writer_close(&writer);
	return result;
}

static int scan_chain(const char *path)
{
	static const enum rh_raw_layout_reason expected[] = {
		RH_RAW_LAYOUT_BYTES_ALLOCATED,
		RH_RAW_LAYOUT_RECORD_RESERVED,
		RH_RAW_LAYOUT_BYTES_IN_USE,
		RH_RAW_LAYOUT_NEXT_ATTRIBUTE_INSTANCE,
	};
	struct rh_raw_mft_census census;
	struct rh_writer writer;
	ntfs_volume *volume = NULL;
	size_t i;
	int result = -1;

	if (rh_writer_open(&writer, path))
		return -1;
	volume = ntfs_mount(path, NTFS_MNT_RDONLY | NTFS_MNT_FORENSIC |
		NTFS_MNT_FS_NO_REPAIR);
	if (!volume || !NDevReadOnly(volume->dev) ||
			rh_raw_mft_census_run(volume, &writer, 1, &census))
		goto out;
	if (!census.records_bounded || census.records_complete ||
			census.layout_complete || census.layout_candidate_count != 4U ||
			writer.write_boundaries)
		goto release;
	for (i = 0; i < sizeof(expected) / sizeof(expected[0]); i++) {
		if (census.layout_candidates[i].reason != expected[i] ||
				census.layout_candidates[i].storage.record != 24U ||
				(i && memcmp(census.layout_candidates[i - 1U].
					logical_record_after_hash,
					census.layout_candidates[i].logical_record_before_hash,
					32)))
			goto release;
	}
	result = 0;
release:
	rh_raw_mft_census_release(&census);
out:
	if (volume && ntfs_umount(volume, FALSE) && !result)
		result = -1;
	rh_writer_close(&writer);
	return result;
}

static int scan_ambiguous(const char *path)
{
	struct rh_raw_mft_census census;
	struct rh_writer writer;
	ntfs_volume *volume = NULL;
	int result = -1;

	if (rh_writer_open(&writer, path))
		return -1;
	volume = ntfs_mount(path, NTFS_MNT_RDONLY | NTFS_MNT_FORENSIC |
		NTFS_MNT_FS_NO_REPAIR);
	if (!volume || !NDevReadOnly(volume->dev) ||
			rh_raw_mft_census_run(volume, &writer, 1, &census))
		goto out;
	if (!census.records_bounded && !census.records_complete &&
			census.invalid_records == 1U &&
			census.slots[24].state == RH_RAW_SLOT_INVALID &&
			!census.layout_candidate_count && !writer.write_boundaries)
		result = 0;
	rh_raw_mft_census_release(&census);
out:
	if (volume && ntfs_umount(volume, FALSE) && !result)
		result = -1;
	rh_writer_close(&writer);
	return result;
}

static int scan_free_cosmetic(const char *path)
{
	struct rh_raw_mft_census census;
	struct rh_writer writer;
	ntfs_volume *volume = NULL;
	int result = -1;

	if (rh_writer_open(&writer, path))
		return -1;
	volume = ntfs_mount(path, NTFS_MNT_RDONLY | NTFS_MNT_FORENSIC |
		NTFS_MNT_FS_NO_REPAIR);
	if (!volume || !NDevReadOnly(volume->dev) ||
			rh_raw_mft_census_run(volume, &writer, 1, &census))
		goto out;
	if (census.records_bounded && census.records_complete &&
			census.layout_complete && census.attribute_lists_complete &&
			census.extents_complete && !census.layout_candidate_count &&
			census.slots[16].state == RH_RAW_SLOT_FREE &&
			!census.slots[16].sequence && !writer.write_boundaries)
		result = 0;
	rh_raw_mft_census_release(&census);
out:
	if (volume && ntfs_umount(volume, FALSE) && !result)
		result = -1;
	rh_writer_close(&writer);
	return result;
}

int main(int argc, char **argv)
{
	static const unsigned char biu[] = { 0x70, 0x02, 0x00, 0x00 };
	static const unsigned char allocated[] = { 0x00, 0x04, 0x00, 0x00 };
	static const unsigned char next[] = { 0x04, 0x00 };
	static const unsigned char wrapped[] = { 0x00, 0x00 };

	if (argc != 10)
		return 5;
	if (scan_candidate(argv[1], RH_RAW_LAYOUT_BYTES_IN_USE, 24U, biu,
			sizeof(biu)) ||
			scan_candidate(argv[2], RH_RAW_LAYOUT_BYTES_IN_USE, 24U, biu,
				sizeof(biu)) ||
			scan_candidate(argv[3], RH_RAW_LAYOUT_BYTES_ALLOCATED, 28U,
				allocated, sizeof(allocated)) ||
			scan_candidate(argv[4], RH_RAW_LAYOUT_NEXT_ATTRIBUTE_INSTANCE,
				40U, next, sizeof(next)) ||
			scan_historical_next(argv[5]) ||
			scan_candidate(argv[6], RH_RAW_LAYOUT_NEXT_ATTRIBUTE_INSTANCE,
				40U, wrapped, sizeof(wrapped)) || scan_chain(argv[7]) ||
			scan_ambiguous(argv[8]) || scan_free_cosmetic(argv[9]))
		return 1;
	printf("raw-header biu-shrink-grow=id7 bytes-allocated=id7 "
		"next-low=id7 next-historical=preserved next-wrap=id7 "
		"multi-header-chain=exact alternate-attr-chain=refused "
		"free-seq0-cosmetic=ignored writes=0\n");
	return 0;
}
