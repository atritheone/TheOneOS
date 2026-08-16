#include "config.h"

#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "device.h"
#include "endians.h"
#include "layout.h"
#include "roothealth_raw_mft.h"
#include "roothealth_write.h"
#include "volume.h"

static int name_is(const struct rh_raw_mft_census *census,
		const struct rh_raw_attribute *attribute, const char *ascii)
{
	size_t length = strlen(ascii), i;
	const unsigned char *name;

	if (attribute->name_length != length)
		return 0;
	name = census->name_arena + attribute->name_offset;
	for (i = 0; i < length; i++)
		if (name[i * 2U] != (unsigned char)ascii[i] || name[i * 2U + 1U])
			return 0;
	return 1;
}

static int open_scan(const char *path, struct rh_writer *writer,
		ntfs_volume **volume, struct rh_raw_mft_census *census)
{
	if (rh_writer_open(writer, path))
		return -1;
	*volume = ntfs_mount(path, NTFS_MNT_RDONLY | NTFS_MNT_FORENSIC |
		NTFS_MNT_FS_NO_REPAIR);
	if (!*volume || !NDevReadOnly((*volume)->dev) ||
			rh_raw_mft_census_run(*volume, writer, 1, census))
		return -1;
	return 0;
}

static void close_scan(struct rh_writer *writer, ntfs_volume *volume,
		struct rh_raw_mft_census *census)
{
	rh_raw_mft_census_release(census);
	if (volume)
		ntfs_umount(volume, FALSE);
	rh_writer_close(writer);
}

static int clean_fixture(const char *path)
{
	struct rh_raw_mft_census census;
	struct rh_writer writer;
	ntfs_volume *volume = NULL;
	int found_data = 0, found_i30 = 0;
	size_t i;

	if (open_scan(path, &writer, &volume, &census))
		return -1;
	for (i = 0; i < census.attribute_count; i++) {
		const struct rh_raw_attribute *attribute = &census.attributes[i];

		if (attribute->storage.record == 64U && !attribute->nonresident &&
				attribute->type == le32_to_cpu(AT_DATA) &&
				!attribute->name_length &&
				attribute->flags == le16_to_cpu(ATTR_IS_COMPRESSED) &&
				!attribute->value_length)
			found_data++;
		if (attribute->storage.record == 65U && !attribute->nonresident &&
				attribute->type == le32_to_cpu(AT_INDEX_ROOT) &&
				name_is(&census, attribute, "$I30") &&
				attribute->flags == le16_to_cpu(ATTR_IS_COMPRESSED) &&
				attribute->value_length == 48U)
			found_i30++;
	}
	i = census.records_complete && census.records_bounded &&
		census.layout_complete && census.attribute_lists_complete &&
		census.extents_complete && !census.layout_candidate_count &&
		!writer.write_boundaries && found_data == 1 && found_i30 == 1 ? 0U : 1U;
	close_scan(&writer, volume, &census);
	return (int)i;
}

static int invalid_fixture(const char *path)
{
	struct rh_raw_mft_census census;
	struct rh_writer writer;
	ntfs_volume *volume = NULL;
	int result;

	if (open_scan(path, &writer, &volume, &census))
		return -1;
	result = census.records_bounded || census.records_complete ||
		census.invalid_records != 1U ||
		census.slots_completed + census.invalid_records !=
			census.slots_expected || census.layout_candidate_count ||
		writer.write_boundaries;
	close_scan(&writer, volume, &census);
	return result;
}

int main(int argc, char **argv)
{
	if (argc != 5)
		return 5;
	if (clean_fixture(argv[1]) || invalid_fixture(argv[2]) ||
			invalid_fixture(argv[3]) || invalid_fixture(argv[4]))
		return 1;
	printf("raw-resident-flags compressed-data=clean compressed-i30=clean "
		"sparse=invalid encrypted=invalid wrong-type=invalid writes=0\n");
	return 0;
}
