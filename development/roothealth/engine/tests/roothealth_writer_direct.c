#include "config.h"

#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include "roothealth_write.h"

int main(void)
{
	char path[] = "/var/tmp/roothealth-writer-direct.XXXXXX";
	unsigned char image[4096], check[4096], replacement[512];
	struct rh_writer writer;
	int fd = -1, result = 1;

	memset(image, 0x5a, sizeof(image));
	memset(replacement, 0xa5, sizeof(replacement));
	fd = mkstemp(path);
	if (fd < 0 || write(fd, image, sizeof(image)) != (ssize_t)sizeof(image) ||
			fsync(fd) || close(fd))
		goto out;
	fd = -1;
	if (rh_writer_open(&writer, path))
		goto out;
	if (rh_writer_plan(&writer, RH_WRITE_BOOT_PRIMARY, 512,
			sizeof(replacement), replacement) ||
			rh_writer_plan(&writer, RH_WRITE_MFT_MIRROR, 2048,
				sizeof(replacement), replacement) ||
			rh_writer_commit(&writer) || writer.sync_count != 3 ||
			writer.last_verified_ordinal != 2 || !writer.operations[0].verified ||
			!writer.operations[1].verified)
		goto close_writer;
	rh_writer_close(&writer);
	fd = open(path, O_RDONLY | O_CLOEXEC);
	if (fd < 0 || read(fd, check, sizeof(check)) != (ssize_t)sizeof(check) ||
			memcmp(check, image, 512) ||
			memcmp(check + 512, replacement, sizeof(replacement)) ||
			memcmp(check + 1024, image + 1024, 1024) ||
			memcmp(check + 2048, replacement, sizeof(replacement)) ||
			memcmp(check + 2560, image + 2560, sizeof(image) - 2560))
		goto out;
	printf("direct operations=2 per_operation_sync=1 post_sync_readback=1 "
		"source_untouched=1 syncs=3\n");
	result = 0;
	goto out;
close_writer:
	rh_writer_close(&writer);
out:
	if (fd >= 0)
		close(fd);
	unlink(path);
	return result;
}
