/* ROOTHEALTH_REPAIR_ROLE(DIAGNOSTIC) */
#include "config.h"

#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "device.h"
#include "roothealth_raw_mft.h"
#include "roothealth_write.h"
#include "volume.h"

static int hex_value(char value)
{
	if (value >= '0' && value <= '9')
		return value - '0';
	if (value >= 'a' && value <= 'f')
		return value - 'a' + 10;
	return -1;
}

static int expected_digest(const char text[65], unsigned char digest[32])
{
	size_t i;

	if (text[64])
		return -1;
	for (i = 0; i < 32U; i++) {
		int high = hex_value(text[i * 2U]);
		int low = hex_value(text[i * 2U + 1U]);

		if (high < 0 || low < 0)
			return -1;
		digest[i] = (unsigned char)((high << 4) | low);
	}
	return 0;
}

static int scan_hash(const char *path, const char expected[65])
{
	struct rh_raw_mft_census census;
	struct rh_writer writer;
	ntfs_volume *volume = NULL;
	unsigned char digest[32];
	int result = -1;

	if (expected_digest(expected, digest) || rh_writer_open(&writer, path))
		return -1;
	volume = ntfs_mount(path, NTFS_MNT_RDONLY | NTFS_MNT_FORENSIC |
		NTFS_MNT_FS_NO_REPAIR);
	if (!volume || !NDevReadOnly(volume->dev) ||
			rh_raw_mft_census_run(volume, &writer, 1, &census))
		goto out;
	if (census.records_complete && census.records_bounded &&
			census.attribute_lists_complete && census.extents_complete &&
			census.layout_complete && !census.layout_candidate_count &&
			!memcmp(census.census_hash, digest, sizeof(digest)) &&
			!writer.write_boundaries)
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
	static const char clean_hash[] =
		"dcd1ca1f80fac540383a84327e38aced4115fb055010929be5a7ba3ddbf8dae6";
	static const char attrlist_hash[] =
		"c952700649431eba6d60f686a8c749eac24186c7f44b531ffd199da95e082bfa";

	if (argc != 3)
		return 5;
	if (scan_hash(argv[1], clean_hash) || scan_hash(argv[2], attrlist_hash))
		return 1;
	printf("raw-hash-vector serializer=RHMFT1 incremental=1 "
		"clean=%s attrlist=%s writes=0\n", clean_hash, attrlist_hash);
	return 0;
}
