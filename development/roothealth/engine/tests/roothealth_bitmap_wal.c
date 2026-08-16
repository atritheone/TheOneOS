#include "config.h"

#include <errno.h>
#include <inttypes.h>
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

static int authorize_bitmap(const struct rh_writer *writer,
		const struct rh_policy_evidence *evidence, size_t first, size_t count)
{
	const struct rh_policy_definition *definitions[2];
	struct rh_policy_authorization authorization;
	size_t d, i;

	definitions[0] = rh_policy_problem(PR_CLUSTER_BITMAP_MISMATCH);
	definitions[1] = rh_policy_aggregate("CLUSTER_BITMAP");
	if (!definitions[0] || !definitions[1] ||
			rh_policy_evidence_target_count(evidence) != count)
		return -1;
	for (d = 0; d < 2; d++)
		for (i = 0; i < count; i++)
			if (rh_policy_authorize_operation(definitions[d], evidence, i,
					writer, first + i, &authorization) !=
					RH_POLICY_FINAL_AUTHORIZED)
				return -1;
	return 0;
}

static int finalize_range(struct rh_writer *writer, size_t first, size_t count,
		uint64_t generation, const unsigned char evidence_hash[32],
		const unsigned char staged_view_hash[32])
{
	size_t i;

	for (i = 0; i < count; i++)
		if (rh_writer_finalize_target(writer, first + i, 1, generation,
				evidence_hash, staged_view_hash))
			return -1;
	return 0;
}

static int mount_and_verify(struct rh_ntfs_overlay *overlay,
		struct rh_writer *writer, uint64_t generation, int expect_dirty,
		struct rh_cluster_bitmap_census *census)
{
	struct rh_volume_dirty_pair dirty;

	if (rh_ntfs_overlay_mount(overlay, writer, 0))
		return -1;
	if (rh_cluster_bitmap_census_run(overlay->volume, writer, generation,
				census) || !census->clean || census->change_count ||
			rh_volume_dirty_inspect(overlay->volume, writer, expect_dirty,
				&dirty) || dirty.initially_dirty != expect_dirty) {
		rh_ntfs_overlay_unmount(overlay);
		return -1;
	}
	return 0;
}

int main(int argc, char **argv)
{
	struct rh_writer writer;
	struct rh_wal wal;
	struct rh_wal_observation observation;
	struct rh_ntfs_overlay overlay;
	struct rh_cluster_bitmap_census initial, staged, post_metadata;
	struct rh_cluster_bitmap_census dirty_clear_staged, final;
	struct rh_volume_dirty_pair dirty_set, dirty_clear, dirty_observed;
	struct rh_policy_evidence *evidence = NULL;
	unsigned char uuid[16];
	uint64_t serial, record, sequence;
	size_t bitmap_first = 0;
	size_t metadata_boundaries, final_boundaries;
	const char *stage = "arguments";
	int overlay_mounted = 0;
	int result = 1;

	memset(&initial, 0, sizeof(initial));
	memset(&staged, 0, sizeof(staged));
	memset(&post_metadata, 0, sizeof(post_metadata));
	memset(&dirty_clear_staged, 0, sizeof(dirty_clear_staged));
	memset(&final, 0, sizeof(final));
	if (argc != 6 || parse_u64(argv[1], 16, &serial) ||
			rh_uuid_parse(argv[2], uuid) || parse_u64(argv[3], 10, &record) ||
			parse_u64(argv[4], 10, &sequence) || sequence > UINT16_MAX)
		return 64;
	if (rh_writer_open(&writer, argv[5]))
		return 3;
	stage = "wal-locate-and-overlay-mount";
	if (rh_wal_locate_and_validate(&wal, &writer, serial, uuid, record,
			(uint16_t)sequence, &observation) || wal.state != RH_WAL_EMPTY ||
			rh_ntfs_overlay_mount(&overlay, &writer, 0))
		goto out_writer;
	overlay_mounted = 1;
	stage = "initial-census-and-plan";
	if (rh_cluster_bitmap_census_run(overlay.volume, &writer, 1, &initial) ||
			initial.change_count != 1 || initial.clean || !initial.complete ||
			!initial.ownership_exact || initial.unreadable_slots ||
			rh_volume_dirty_inspect(overlay.volume, &writer, 1, &dirty_set) ||
			dirty_set.initially_dirty ||
			rh_volume_dirty_stage_pair(&writer, &dirty_set) ||
			!dirty_set.planned || dirty_set.first_operation_ordinal != 1 ||
			rh_cluster_bitmap_stage(&overlay, &initial, &bitmap_first) ||
			bitmap_first != 3 || writer.operation_count != 3)
		goto out_overlay;
	rh_ntfs_overlay_unmount(&overlay);
	overlay_mounted = 0;
	stage = "staged-rescan";
	if (mount_and_verify(&overlay, &writer, 2, 1, &staged))
		goto out_writer;
	overlay_mounted = 1;
	stage = "policy-seal-and-authorize";
	if (rh_cluster_bitmap_seal_policy(&initial, &staged, &writer,
			bitmap_first, 1, &evidence) ||
			authorize_bitmap(&writer, evidence, bitmap_first,
				initial.change_count) ||
			finalize_range(&writer, 1, writer.operation_count,
				initial.generation, initial.census_hash,
				staged.census_hash))
		goto out_overlay;
	rh_ntfs_overlay_unmount(&overlay);
	overlay_mounted = 0;
	stage = "metadata-wal-commit";
	if (rh_wal_install_backend(&wal, RH_WAL_TX_METADATA_REPAIR) ||
			rh_writer_commit(&writer) || wal.state != RH_WAL_COMMITTED ||
			wal.entry_count != 3 || wal.target_bytes != 1536)
		goto out_writer;
	metadata_boundaries = writer.write_boundaries;
	rh_wal_uninstall_backend(&wal);
	rh_writer_reset_plan(&writer);
	stage = "post-metadata-rescan";
	if (mount_and_verify(&overlay, &writer, 3, 1, &post_metadata))
		goto out_writer;
	overlay_mounted = 1;
	rh_ntfs_overlay_unmount(&overlay);
	overlay_mounted = 0;
	stage = "metadata-wal-accept";
	if (rh_wal_committed_accept(&wal, RH_WAL_TX_METADATA_REPAIR))
		goto out_writer;
	if (rh_ntfs_overlay_mount(&overlay, &writer, 0))
		goto out_writer;
	overlay_mounted = 1;
	stage = "dirty-clear-plan";
	if (rh_volume_dirty_inspect(overlay.volume, &writer, 0, &dirty_clear) ||
			!dirty_clear.initially_dirty ||
			rh_volume_dirty_stage_pair(&writer, &dirty_clear) ||
			!dirty_clear.planned || dirty_clear.first_operation_ordinal != 1 ||
			writer.operation_count != 2)
		goto out_overlay;
	rh_ntfs_overlay_unmount(&overlay);
	overlay_mounted = 0;
	stage = "dirty-clear-staged-rescan";
	if (mount_and_verify(&overlay, &writer, 4, 0, &dirty_clear_staged))
		goto out_writer;
	overlay_mounted = 1;
	if (finalize_range(&writer, 1, writer.operation_count,
			post_metadata.generation, post_metadata.census_hash,
			dirty_clear_staged.census_hash))
		goto out_overlay;
	rh_ntfs_overlay_unmount(&overlay);
	overlay_mounted = 0;
	stage = "dirty-clear-wal-commit";
	if (rh_wal_install_backend(&wal, RH_WAL_TX_DIRTY_CLEAR) ||
			rh_writer_commit(&writer) || wal.state != RH_WAL_COMMITTED ||
			wal.entry_count != 2 || wal.target_bytes != 1024)
		goto out_writer;
	rh_wal_uninstall_backend(&wal);
	rh_writer_reset_plan(&writer);
	stage = "final-rescan";
	if (mount_and_verify(&overlay, &writer, 5, 0, &final))
		goto out_writer;
	overlay_mounted = 1;
	rh_ntfs_overlay_unmount(&overlay);
	overlay_mounted = 0;
	stage = "dirty-clear-wal-accept";
	if (rh_wal_committed_accept(&wal, RH_WAL_TX_DIRTY_CLEAR) ||
			wal.state != RH_WAL_EMPTY)
		goto out_writer;
	final_boundaries = writer.write_boundaries;
	if (rh_ntfs_overlay_mount(&overlay, &writer, 0))
		goto out_writer;
	overlay_mounted = 1;
	stage = "final-independent-check";
	if (rh_volume_dirty_inspect(overlay.volume, &writer, 0,
			&dirty_observed) || dirty_observed.initially_dirty)
		goto out_overlay;
	printf("bitmap-wal policy_authorizations=2 metadata_entries=3 "
		"metadata_target_bytes=1536 dirty_clear_entries=2 "
		"dirty_clear_target_bytes=1024 post_metadata_clean=1 final_clean=1 "
		"metadata_write_boundaries=%zu total_write_boundaries=%zu\n",
		metadata_boundaries, final_boundaries);
	result = 0;
out_overlay:
	if (overlay_mounted)
		rh_ntfs_overlay_unmount(&overlay);
out_writer:
	if (result)
		fprintf(stderr, "failed stage=%s errno=%d (%s) operations=%zu "
			"wal_state=%d wal_entries=%"PRIu64" writes=%zu\n", stage,
			errno, strerror(errno), writer.operation_count, (int)wal.state,
			wal.entry_count, writer.write_boundaries);
	rh_wal_uninstall_backend(&wal);
	rh_policy_evidence_destroy(evidence);
	rh_cluster_bitmap_census_destroy(&final);
	rh_cluster_bitmap_census_destroy(&dirty_clear_staged);
	rh_cluster_bitmap_census_destroy(&post_metadata);
	rh_cluster_bitmap_census_destroy(&staged);
	rh_cluster_bitmap_census_destroy(&initial);
	rh_writer_close(&writer);
	return result;
}
