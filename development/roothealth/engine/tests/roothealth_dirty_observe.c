#include "config.h"

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>

#include "roothealth_dirty.h"

int main(int argc, char **argv)
{
	struct rh_writer writer;
	struct rh_ntfs_overlay overlay;
	struct rh_volume_dirty_pair pair;
	char *end = NULL;
	long expected;
	int mounted = 0;
	int result = 1;

	if (argc != 3)
		return 5;
	errno = 0;
	expected = strtol(argv[1], &end, 10);
	if (errno || !end || *end || (expected != 0 && expected != 1))
		return 5;
	if (rh_writer_open(&writer, argv[2]))
		return 3;
	if (rh_ntfs_overlay_mount(&overlay, &writer, 0))
		goto out;
	mounted = 1;
	if (rh_volume_dirty_inspect(overlay.volume, &writer, (int)expected,
			&pair) || pair.initially_dirty != expected)
		goto out;
	printf("volume-dirty expected=%ld observed=%d primary=%llu mirror=%llu\n",
		expected, pair.initially_dirty,
		(unsigned long long)pair.primary_flag_offset,
		(unsigned long long)pair.mirror_flag_offset);
	result = 0;
out:
	if (mounted)
		rh_ntfs_overlay_unmount(&overlay);
	rh_writer_close(&writer);
	return result;
}
