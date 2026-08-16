#include "config.h"

#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "device.h"
#include "roothealth_raw_mft.h"
#include "roothealth_write.h"
#include "volume.h"

enum fixture_kind {
	FIXTURE_ATTRLIST_CLEAN,
	FIXTURE_RESERVED_CANDIDATE,
	FIXTURE_MAPPING_INVALID,
};

static int scan(const char *path, enum fixture_kind kind,
		unsigned char hash[32])
{
	struct rh_raw_mft_census census;
	struct rh_writer writer;
	ntfs_volume *volume = NULL;
	size_t i, nonzero_extent_instances = 0;
	int result = -1;

	if (rh_writer_open(&writer, path))
		return -1;
	volume = ntfs_mount(path, NTFS_MNT_RDONLY | NTFS_MNT_FORENSIC |
		NTFS_MNT_FS_NO_REPAIR);
	if (!volume || !NDevReadOnly(volume->dev) ||
			rh_raw_mft_census_run(volume, &writer, 1, &census))
		goto out;
	if (writer.write_boundaries)
		goto release;
	if (kind == FIXTURE_ATTRLIST_CLEAN) {
		for (i = 0; i < census.list_entry_count; i++)
			if (census.list_entries[i].storage.record !=
					census.list_entries[i].owner.record &&
					census.list_entries[i].instance)
				nonzero_extent_instances++;
		if (!census.records_complete || !census.records_bounded ||
				!census.layout_complete || !census.attribute_lists_complete ||
				!census.extents_complete || census.layout_candidate_count ||
				census.attribute_lists != 1U ||
				census.list_entry_count != 124U ||
				nonzero_extent_instances != 100U)
			goto release;
	} else if (kind == FIXTURE_RESERVED_CANDIDATE) {
		const struct rh_raw_layout_candidate *candidate;

		if (!census.records_bounded || census.records_complete ||
				census.layout_complete || !census.attribute_lists_complete ||
				!census.extents_complete || census.layout_candidate_count != 1U)
			goto release;
		candidate = &census.layout_candidates[0];
		if (candidate->reason != RH_RAW_LAYOUT_RECORD_RESERVED ||
				candidate->storage.record != 24U ||
				candidate->logical_offset != 42U || candidate->length != 2U ||
				!memcmp(candidate->logical_record_before_hash,
					candidate->logical_record_after_hash, 32))
			goto release;
	} else {
		if (census.records_bounded || census.records_complete ||
				!census.invalid_records || census.attribute_lists_complete ||
				census.extents_complete || census.layout_candidate_count)
			goto release;
	}
	memcpy(hash, census.census_hash, 32);
	result = 0;
release:
	rh_raw_mft_census_release(&census);
out:
	if (volume && ntfs_umount(volume, FALSE) && !result)
		result = -1;
	rh_writer_close(&writer);
	return result;
}

int main(int argc, char **argv)
{
	unsigned char producer_hash[32], zeroed_hash[32], ignored[32];

	if (argc != 5)
		return 5;
	if (scan(argv[1], FIXTURE_ATTRLIST_CLEAN, producer_hash) ||
			scan(argv[2], FIXTURE_ATTRLIST_CLEAN, zeroed_hash) ||
			scan(argv[3], FIXTURE_RESERVED_CANDIDATE, ignored) ||
			scan(argv[4], FIXTURE_MAPPING_INVALID, ignored) ||
			!memcmp(producer_hash, zeroed_hash, sizeof(producer_hash)))
		return 1;
	printf("raw-layout opaque-mapping-slack=clean-and-bound "
		"nonresident-attrlist=clean nonzero-extent-instances=100 "
		"reserved-header=id7-candidate encoded-run-corruption=invalid "
		"writes=0\n");
	return 0;
}
