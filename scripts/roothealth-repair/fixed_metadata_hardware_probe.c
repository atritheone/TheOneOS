#include "config.h"

#include <inttypes.h>
#include <stdio.h>
#include <string.h>

#include "roothealth_fixed_metadata.h"

static int inspect_one(struct rh_ntfs_overlay *overlay,
		enum rh_fixed_metadata_kind kind, uint64_t record, uint64_t length,
		struct rh_fixed_metadata_inspection *inspection)
{
	memset(inspection, 0, sizeof(*inspection));
	if (rh_fixed_metadata_inspect(overlay->volume, overlay->writer, kind,
			inspection) || !inspection->canonical ||
			inspection->owner_mft_record != record ||
			!inspection->owner_sequence || inspection->data_size != length ||
			inspection->slice_count != 1U ||
			inspection->slices[0].logical_offset ||
			inspection->slices[0].length != length ||
			inspection->slices[0].logical_vcn ||
			inspection->slices[0].lcn < 0)
		return -1;
	return 0;
}

int main(int argc, char **argv)
{
	struct rh_fixed_metadata_inspection upcase, attrdef;
	struct rh_ntfs_overlay bootstrap, ordinary;
	struct rh_writer writer;
	int bootstrap_mounted = 0;
	int result = 1;

	memset(&upcase, 0, sizeof(upcase));
	memset(&attrdef, 0, sizeof(attrdef));
	memset(&bootstrap, 0, sizeof(bootstrap));
	memset(&ordinary, 0, sizeof(ordinary));
	if (argc != 2)
		return 64;
	if (rh_writer_open(&writer, argv[1]))
		return 65;
	if (rh_ntfs_overlay_mount_fixed_metadata_bootstrap(&bootstrap,
			&writer, 0))
		goto out;
	bootstrap_mounted = 1;
	if (inspect_one(&bootstrap, RH_FIXED_METADATA_UPCASE, 10U,
			RH_UPCASE_CANONICAL_SIZE, &upcase) ||
			inspect_one(&bootstrap, RH_FIXED_METADATA_ATTRDEF, 4U,
				RH_ATTRDEF_CANONICAL_SIZE, &attrdef) ||
			writer.operation_count || writer.planned_bytes ||
			writer.write_boundaries)
		goto out;
	rh_ntfs_overlay_unmount(&bootstrap);
	bootstrap_mounted = 0;
	if (rh_ntfs_overlay_mount(&ordinary, &writer, 0))
		goto out;
	rh_ntfs_overlay_unmount(&ordinary);
	if (writer.operation_count || writer.planned_bytes ||
			writer.write_boundaries)
		goto out;
	printf("{\"attrdef_length\":%" PRIu64
		",\"attrdef_lcn\":%" PRId64
		",\"attrdef_offset\":%" PRIu64
		",\"ordinary_mount\":true,\"result\":\"PASS\""
		",\"source_writes\":0,\"upcase_length\":%" PRIu64
		",\"upcase_lcn\":%" PRId64
		",\"upcase_offset\":%" PRIu64 "}\n",
		attrdef.slices[0].length, attrdef.slices[0].lcn,
		attrdef.slices[0].physical_offset, upcase.slices[0].length,
		upcase.slices[0].lcn, upcase.slices[0].physical_offset);
	result = 0;
out:
	rh_fixed_metadata_inspection_destroy(&attrdef);
	rh_fixed_metadata_inspection_destroy(&upcase);
	if (bootstrap_mounted)
		rh_ntfs_overlay_unmount(&bootstrap);
	rh_writer_close(&writer);
	return result;
}
