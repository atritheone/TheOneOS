#include "config.h"

#include <errno.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "endians.h"
#include "layout.h"
#include "roothealth_bitmap.h"
#include "roothealth_mft_bitmap.h"
#include "roothealth_raw_mft.h"

static int unnamed_stream(const struct rh_raw_attribute *attribute,
		uint64_t owner, uint32_t type)
{
	return attribute->owner.record == owner && attribute->type == type &&
		!attribute->name_length && attribute->nonresident;
}

static int fault_mft_record_reads(const ntfs_volume *volume,
		const struct rh_raw_mft_census *raw)
{
	char setting[96];
	size_t i;

	for (i = 0; i < raw->attribute_count; i++) {
		const struct rh_raw_attribute *attribute = &raw->attributes[i];
		const struct rh_raw_run *run;
		uint64_t physical;

		if (!unnamed_stream(attribute, FILE_MFT, le32_to_cpu(AT_DATA)) ||
				attribute->lowest_vcn || !attribute->run_count)
			continue;
		run = &raw->runs[attribute->run_first];
		if (run->sparse || run->lcn < 0 ||
				(uint64_t)run->lcn > UINT64_MAX / volume->cluster_size)
			return -1;
		physical = (uint64_t)run->lcn * volume->cluster_size;
		if (snprintf(setting, sizeof(setting), "read-offset:%" PRIu64,
				physical) < 0 || setenv("ROOTHEALTH_REPAIR_TEST_FAIL", setting, 1))
			return -1;
		return 0;
	}
	errno = EIO;
	return -1;
}

static int split_cluster_bitmap_extent(struct rh_raw_mft_census *raw)
{
	struct rh_raw_attribute *attributes;
	struct rh_raw_run *runs;
	size_t i, attribute_index = SIZE_MAX, old_attribute_count, old_run_count;
	uint64_t split;

	for (i = 0; i < raw->attribute_count; i++) {
		const struct rh_raw_attribute *attribute = &raw->attributes[i];

		if (unnamed_stream(attribute, FILE_Bitmap, le32_to_cpu(AT_DATA)) &&
				!attribute->lowest_vcn && attribute->run_count == 1U &&
				raw->runs[attribute->run_first].length >= 2U) {
			attribute_index = i;
			break;
		}
	}
	if (attribute_index == SIZE_MAX) {
		errno = EIO;
		return -1;
	}
	old_attribute_count = raw->attribute_count;
	old_run_count = raw->run_count;
	attributes = realloc(raw->attributes,
		(old_attribute_count + 1U) * sizeof(*attributes));
	if (!attributes)
		return -1;
	raw->attributes = attributes;
	raw->attribute_capacity = old_attribute_count + 1U;
	runs = realloc(raw->runs, (old_run_count + 1U) * sizeof(*runs));
	if (!runs)
		return -1;
	raw->runs = runs;
	raw->run_capacity = old_run_count + 1U;
	split = raw->runs[raw->attributes[attribute_index].run_first].length / 2U;
	raw->attributes[old_attribute_count] = raw->attributes[attribute_index];
	raw->attributes[old_attribute_count].lowest_vcn = (int64_t)split;
	raw->attributes[old_attribute_count].run_first = old_run_count;
	raw->attributes[old_attribute_count].run_count = 1U;
	raw->attributes[attribute_index].highest_vcn = (int64_t)(split - 1U);
	raw->runs[old_run_count] =
		raw->runs[raw->attributes[attribute_index].run_first];
	raw->runs[old_run_count].attribute_index = old_attribute_count;
	raw->runs[old_run_count].vcn += (int64_t)split;
	raw->runs[old_run_count].lcn += (int64_t)split;
	raw->runs[old_run_count].length -= split;
	raw->runs[raw->attributes[attribute_index].run_first].length = split;
	raw->attributes[old_attribute_count].highest_vcn =
		raw->runs[old_run_count].vcn +
		(int64_t)raw->runs[old_run_count].length - 1;
	raw->attribute_count++;
	raw->nonresident_attributes++;
	raw->extents_expected++;
	raw->extents_completed++;
	raw->run_count++;
	raw->runs_expected++;
	raw->runs_completed++;
	return 0;
}

int main(int argc, char **argv)
{
	struct rh_writer writer;
	struct rh_ntfs_overlay overlay;
	struct rh_raw_mft_census raw;
	struct rh_cluster_bitmap_census cluster, split;
	struct rh_mft_bitmap_census mft;
	int result = 1;

	memset(&raw, 0, sizeof(raw));
	memset(&cluster, 0, sizeof(cluster));
	memset(&split, 0, sizeof(split));
	memset(&mft, 0, sizeof(mft));
	if (argc != 2)
		return 5;
	if (rh_writer_open(&writer, argv[1]))
		return 3;
	if (rh_ntfs_overlay_mount(&overlay, &writer, 0))
		goto out_writer;
	if (rh_raw_mft_census_run(overlay.volume, &writer, 7, &raw) ||
			fault_mft_record_reads(overlay.volume, &raw) ||
			rh_cluster_bitmap_census_run_from_raw(overlay.volume, &writer, 7,
				&raw, &cluster) || !cluster.complete || !cluster.clean ||
			rh_mft_bitmap_census_run_from_raw(overlay.volume, &writer, 7,
				RH_MFT_BITMAP_NO_ROOTHEALTH, 0, &raw, &mft) ||
			!mft.complete || !mft.clean ||
			cluster.mft_slots_completed != raw.slots_completed ||
			mft.mft_slots_completed != raw.slots_completed ||
			writer.write_boundaries || split_cluster_bitmap_extent(&raw) ||
			rh_cluster_bitmap_census_run_from_raw(overlay.volume, &writer, 7,
				&raw, &split) || !split.complete || !split.clean ||
			memcmp(cluster.allocation_hash, split.allocation_hash,
				sizeof(cluster.allocation_hash)) || writer.write_boundaries) {
		fprintf(stderr, "raw bitmap consumer failed: %s cluster=%d mft=%d "
			"split=%d writes=%zu\n", strerror(errno), cluster.complete,
			mft.complete, split.complete, writer.write_boundaries);
		goto out;
	}
	printf("bitmap-from-raw slots=%" PRIu64 " attrs=%" PRIu64
		" runs=%" PRIu64 " shared-census=2 mft-reread-fault=not-hit "
		"multi-extent=accepted opaque-slack=raw-owned source-writes=0\n",
		raw.slots_completed, split.attributes_examined, split.runs_examined);
	result = 0;
out:
	unsetenv("ROOTHEALTH_REPAIR_TEST_FAIL");
	rh_mft_bitmap_census_destroy(&mft);
	rh_cluster_bitmap_census_destroy(&split);
	rh_cluster_bitmap_census_destroy(&cluster);
	rh_raw_mft_census_release(&raw);
	rh_ntfs_overlay_unmount(&overlay);
out_writer:
	rh_writer_close(&writer);
	return result;
}
