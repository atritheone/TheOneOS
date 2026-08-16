#include <stdio.h>

#include "logging.h"
#include "roothealth_overlay.h"

int main(int argc, char **argv)
{
	struct rh_writer writer;
	struct rh_ntfs_overlay overlay;

	if (argc != 2)
		return 5;
	ntfs_log_set_handler(ntfs_log_handler_stderr);
	ntfs_log_set_levels(NTFS_LOG_LEVEL_DEBUG | NTFS_LOG_LEVEL_INFO |
		NTFS_LOG_LEVEL_VERBOSE | NTFS_LOG_LEVEL_WARNING |
		NTFS_LOG_LEVEL_ERROR | NTFS_LOG_LEVEL_PERROR);
	if (rh_writer_open(&writer, argv[1])) {
		perror("writer open");
		return 3;
	}
	if (rh_ntfs_overlay_mount(&overlay, &writer, 0)) {
		perror("overlay mount");
		rh_writer_close(&writer);
		return 2;
	}
	printf("records=%lld operations=%zu failed=%d\n",
		(long long)(overlay.volume->mft_na->initialized_size >>
			overlay.volume->mft_record_size_bits),
		writer.operation_count, rh_ntfs_overlay_failed(&overlay));
	rh_ntfs_overlay_unmount(&overlay);
	rh_writer_close(&writer);
	return 0;
}
