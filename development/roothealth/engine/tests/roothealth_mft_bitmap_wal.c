#include "config.h"

#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "roothealth_bitmap.h"
#include "roothealth_dirty.h"
#include "roothealth_mft_bitmap.h"
#include "roothealth_raw_mft.h"
#include "roothealth_wal.h"

static int parse_u64(const char *text, int base, uint64_t *value)
{
	char *end = NULL;

	errno = 0;
	*value = strtoull(text, &end, base);
	return errno || !end || *end ? -1 : 0;
}

static int finalize(struct rh_writer *writer, size_t first, size_t count,
		uint64_t generation, const unsigned char before[32],
		const unsigned char after[32])
{
	size_t i;

	for (i = 0; i < count; i++)
		if (rh_writer_finalize_target(writer, first + i, 1, generation,
				before, after))
			return -1;
	return 0;
}

int main(int argc, char **argv)
{
	struct rh_writer writer;
	struct rh_wal wal;
	struct rh_wal_observation observation;
	struct rh_ntfs_overlay overlay;
	struct rh_cluster_bitmap_census cluster_before = {0}, cluster_after = {0};
	struct rh_raw_mft_census raw_before = {0}, raw_after = {0};
	struct rh_mft_bitmap_census mft_before = {0}, mft_after = {0};
	struct rh_volume_dirty_pair dirty;
	unsigned char uuid[16];
	uint64_t serial, record, sequence;
	size_t first = 0;
	const char *stage = "arguments";
	int mounted = 0;
	int result = 1;

	if (argc != 6 || parse_u64(argv[1], 16, &serial) ||
			rh_uuid_parse(argv[2], uuid) || parse_u64(argv[3], 10, &record) ||
			parse_u64(argv[4], 10, &sequence) || sequence > UINT16_MAX)
		return 64;
	if (rh_writer_open(&writer, argv[5]))
		return 3;
	stage = "locate";
	if (rh_wal_locate_and_validate(&wal, &writer, serial, uuid, record,
			(uint16_t)sequence, &observation) || wal.state != RH_WAL_EMPTY ||
			rh_ntfs_overlay_mount(&overlay, &writer, 0))
		goto out;
	mounted = 1;
	stage = "initial";
	if (rh_cluster_bitmap_census_run(overlay.volume, &writer, 1,
			&cluster_before) || !cluster_before.clean ||
			rh_volume_dirty_inspect(overlay.volume, &writer, 1, &dirty) ||
			dirty.initially_dirty || rh_volume_dirty_stage_pair(&writer, &dirty) ||
			rh_raw_mft_census_run(overlay.volume, &writer, 1, &raw_before) ||
			rh_mft_bitmap_census_run_from_raw(overlay.volume, &writer, 1,
				record, (uint16_t)sequence, &raw_before, &mft_before) ||
			mft_before.clean || mft_before.change_count != 1 ||
			rh_mft_bitmap_stage(&overlay, &mft_before, &first) || first != 3 ||
			writer.operation_count != 3)
		goto out;
	rh_ntfs_overlay_unmount(&overlay);
	mounted = 0;
	stage = "staged";
	if (rh_ntfs_overlay_mount(&overlay, &writer, 0))
		goto out;
	mounted = 1;
	if (rh_cluster_bitmap_census_run(overlay.volume, &writer, 2,
			&cluster_after) || !cluster_after.clean ||
			rh_raw_mft_census_run(overlay.volume, &writer, 2, &raw_after) ||
			rh_mft_bitmap_census_run_from_raw(overlay.volume, &writer, 2,
				record, (uint16_t)sequence, &raw_after, &mft_after) ||
			!mft_after.clean || mft_after.change_count ||
			finalize(&writer, 1, 2, cluster_before.generation,
				cluster_before.census_hash, cluster_after.census_hash) ||
			finalize(&writer, 3, 1, mft_before.generation,
				mft_before.census_hash, mft_after.census_hash))
		goto out;
	rh_ntfs_overlay_unmount(&overlay);
	mounted = 0;
	stage = "commit";
	if (rh_wal_install_backend(&wal, RH_WAL_TX_METADATA_REPAIR) ||
			rh_writer_commit(&writer) || wal.state != RH_WAL_COMMITTED ||
			wal.entry_count != 3)
		goto out;
	rh_wal_uninstall_backend(&wal);
	rh_writer_reset_plan(&writer);
	stage = "accept";
	if (rh_wal_committed_accept(&wal, RH_WAL_TX_METADATA_REPAIR) ||
			wal.state != RH_WAL_EMPTY)
		goto out;
	printf("mft-bitmap-wal actions=24,24,22 entries=3 recovered=1 "
		"source_writes=%zu\n", writer.write_boundaries);
	result = 0;
out:
	if (result)
		fprintf(stderr, "mft-bitmap-wal failed stage=%s errno=%d (%s)\n",
			stage, errno, strerror(errno));
	if (mounted)
		rh_ntfs_overlay_unmount(&overlay);
	rh_wal_uninstall_backend(&wal);
	rh_mft_bitmap_census_destroy(&mft_after);
	rh_mft_bitmap_census_destroy(&mft_before);
	rh_raw_mft_census_release(&raw_after);
	rh_raw_mft_census_release(&raw_before);
	rh_cluster_bitmap_census_destroy(&cluster_after);
	rh_cluster_bitmap_census_destroy(&cluster_before);
	rh_writer_close(&writer);
	return result;
}
