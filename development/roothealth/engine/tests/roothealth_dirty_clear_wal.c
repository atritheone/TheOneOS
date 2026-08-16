#include "config.h"

#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "roothealth_bitmap.h"
#include "roothealth_dirty.h"
#include "roothealth_wal.h"

static int parse_u64(const char *text, int base, uint64_t *value)
{
	char *end = NULL;

	errno = 0;
	*value = strtoull(text, &end, base);
	return errno || !*value || !end || *end ? -1 : 0;
}

int main(int argc, char **argv)
{
	struct rh_writer writer;
	struct rh_wal wal;
	struct rh_wal_observation observation;
	struct rh_ntfs_overlay overlay;
	struct rh_cluster_bitmap_census before = {0}, staged = {0}, final = {0};
	struct rh_volume_dirty_pair clear, observed;
	unsigned char uuid[16];
	uint64_t serial, record, sequence;
	int mounted = 0;
	int result = 1;
	const char *stage = "arguments";

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
	stage = "initial-plan";
	if (rh_cluster_bitmap_census_run(overlay.volume, &writer, 1, &before) ||
			!before.clean || rh_volume_dirty_inspect(overlay.volume, &writer, 0,
				&clear) || !clear.initially_dirty ||
			rh_volume_dirty_stage_pair(&writer, &clear) ||
			writer.operation_count != 2)
		goto out;
	rh_ntfs_overlay_unmount(&overlay);
	mounted = 0;
	if (rh_ntfs_overlay_mount(&overlay, &writer, 0))
		goto out;
	mounted = 1;
	stage = "staged-finalize";
	if (rh_cluster_bitmap_census_run(overlay.volume, &writer, 2, &staged) ||
			!staged.clean || rh_volume_dirty_inspect(overlay.volume, &writer, 0,
				&observed) || observed.initially_dirty ||
			rh_writer_finalize_target(&writer, 1, 1, before.generation,
				before.census_hash, staged.census_hash) ||
			rh_writer_finalize_target(&writer, 2, 1, before.generation,
				before.census_hash, staged.census_hash))
		goto out;
	rh_ntfs_overlay_unmount(&overlay);
	mounted = 0;
	stage = "commit";
	if (rh_wal_install_backend(&wal, RH_WAL_TX_DIRTY_CLEAR) ||
			rh_writer_commit(&writer) || wal.state != RH_WAL_COMMITTED ||
			wal.entry_count != 2 || wal.target_bytes != 1024)
		goto out;
	rh_wal_uninstall_backend(&wal);
	rh_writer_reset_plan(&writer);
	if (rh_ntfs_overlay_mount(&overlay, &writer, 0))
		goto out;
	mounted = 1;
	stage = "post-commit";
	if (rh_cluster_bitmap_census_run(overlay.volume, &writer, 3, &final) ||
			!final.clean || rh_volume_dirty_inspect(overlay.volume, &writer, 0,
				&observed) || observed.initially_dirty)
		goto out;
	rh_ntfs_overlay_unmount(&overlay);
	mounted = 0;
	stage = "accept";
	if (rh_wal_committed_accept(&wal, RH_WAL_TX_DIRTY_CLEAR) ||
			wal.state != RH_WAL_EMPTY)
		goto out;
	printf("dirty-clear-wal entries=2 target_bytes=1024 final_clean=1 "
		"write_boundaries=%zu\n", writer.write_boundaries);
	result = 0;
out:
	if (result)
		fprintf(stderr, "dirty-clear failed stage=%s errno=%d (%s) "
			"wal_state=%d entries=%llu operations=%zu\n", stage, errno,
			strerror(errno), wal.state, (unsigned long long)wal.entry_count,
			writer.operation_count);
	if (mounted)
		rh_ntfs_overlay_unmount(&overlay);
	rh_wal_uninstall_backend(&wal);
	rh_cluster_bitmap_census_destroy(&final);
	rh_cluster_bitmap_census_destroy(&staged);
	rh_cluster_bitmap_census_destroy(&before);
	rh_writer_close(&writer);
	return result;
}
