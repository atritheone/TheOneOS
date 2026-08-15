#include "config.h"

#include <errno.h>
#include <inttypes.h>
#include <stdio.h>
#include <string.h>

#include "roothealth_bitmap.h"
#include "roothealth_fixed_metadata.h"
#include "roothealth_namespace.h"
#include "roothealth_raw_mft.h"

int main(int argc, char **argv)
{
	struct rh_cluster_bitmap_census cluster;
	struct rh_namespace_census namespace_census;
	struct rh_raw_mft_census raw;
	struct rh_writer writer;
	unsigned char type_use_hash[32];
	ntfs_volume *volume = NULL;
	int result = 1;

	memset(&cluster, 0, sizeof(cluster));
	memset(&namespace_census, 0, sizeof(namespace_census));
	memset(&raw, 0, sizeof(raw));
	if (argc != 2)
		return 64;
	if (rh_writer_open(&writer, argv[1]))
		return 65;
	volume = ntfs_mount(argv[1], NTFS_MNT_RDONLY | NTFS_MNT_FORENSIC |
		NTFS_MNT_FS_NO_REPAIR);
	if (!volume || !NDevReadOnly(volume->dev) ||
			rh_raw_mft_census_run(volume, &writer, 17U, &raw) ||
			!raw.records_complete || !raw.records_bounded ||
			!raw.layout_complete || !raw.attribute_lists_complete ||
			!raw.extents_complete || raw.unreadable_records ||
			raw.invalid_records ||
			rh_namespace_census_run(&raw, 17U, &namespace_census) ||
			rh_namespace_i30_census_run(volume, &writer, &raw,
				&namespace_census) ||
			rh_namespace_check_t1os_identity(&raw, &namespace_census) ||
			!namespace_census.graph_complete ||
			!namespace_census.i30_complete ||
			!namespace_census.reciprocity_complete ||
			namespace_census.identity != RH_T1OS_IDENTITY_MATCH ||
			namespace_census.i30_bitmap_changes ||
			rh_cluster_bitmap_census_run_from_raw(volume, &writer, 17U,
				&raw, &cluster) || !cluster.complete ||
			!cluster.structurally_valid || !cluster.ownership_exact ||
			!cluster.clean || cluster.duplicate_clusters ||
			cluster.unreadable_slots || writer.operation_count ||
			writer.planned_bytes || writer.write_boundaries ||
			!rh_fixed_metadata_attrdef_type_census(&raw, type_use_hash))
		goto out;
	printf("{\"attributes\":%zu,\"bitmap_bits\":%" PRIu64
		",\"cluster_bitmap_clean\":true,\"identity\":\"MATCH\""
		",\"indexes\":%" PRIu64 ",\"links\":%" PRIu64
		",\"raw_complete\":true,\"result\":\"PASS\",\"runs\":%zu"
		",\"slots\":%zu,\"source_writes\":0}\n",
		raw.attribute_count, cluster.bitmap_bits_examined,
		namespace_census.i30_indexes_completed,
		namespace_census.links_completed, raw.run_count, raw.slot_count);
	result = 0;
out:
	if (result)
		fprintf(stderr, "release census failed errno=%d raw=%u/%u/%u/%u "
			"namespace=%u/%u/%u identity=%u i30_changes=%" PRIu64
			" cached=%" PRIu64 " bitmap=%d/%d/%d clean=%d "
			"duplicates=%" PRIu64 " unreadable=%" PRIu64 "\n", errno,
			raw.records_complete, raw.records_bounded, raw.layout_complete,
			raw.extents_complete, namespace_census.graph_complete,
			namespace_census.i30_complete,
			namespace_census.reciprocity_complete,
			(unsigned int)namespace_census.identity,
			namespace_census.i30_bitmap_changes,
			namespace_census.cached_file_name_differences, cluster.complete,
			cluster.structurally_valid, cluster.ownership_exact, cluster.clean,
			cluster.duplicate_clusters, cluster.unreadable_slots);
	if (result)
		fprintf(stderr, "cluster partial clusters=%" PRIu64
			" attrs=%" PRIu64 " extents=%" PRIu64 " runs=%" PRIu64
			" owned=%" PRIu64 " changes=%zu bytes=%zu\n",
			cluster.cluster_count, cluster.attributes_examined,
			cluster.nonresident_extents_examined, cluster.runs_examined,
			cluster.clusters_owned, cluster.change_count, cluster.bitmap_bytes);
	if (result && volume)
		fprintf(stderr, "raw-ready generation=%" PRIu64 " slots=%" PRIu64
			"/%" PRIu64 "/%zu live=%" PRIu64 "+%" PRIu64
			" free=%" PRIu64 " runs=%" PRIu64 "/%" PRIu64 "/%zu"
			" extents=%" PRIu64 "/%" PRIu64 "/%" PRIu64
			" mft-init=%" PRId64 " nr-clusters=%" PRId64
			" sector=%u cluster=%u mft=%u bits=%u/%u\n",
			raw.generation, raw.slots_completed, raw.slots_expected,
			raw.slot_count, raw.live_base_records, raw.live_extent_records,
			raw.free_records, raw.runs_completed, raw.runs_expected,
			raw.run_count, raw.extents_completed, raw.extents_expected,
			raw.nonresident_attributes,
			volume->mft_na ? volume->mft_na->initialized_size : -1,
			(int64_t)volume->nr_clusters, volume->sector_size,
			volume->cluster_size, volume->mft_record_size,
			volume->mft_record_size_bits, volume->cluster_size_bits);
	rh_cluster_bitmap_census_destroy(&cluster);
	rh_namespace_census_release(&namespace_census);
	rh_raw_mft_census_release(&raw);
	if (volume)
		ntfs_umount(volume, 0);
	rh_writer_close(&writer);
	return result;
}
