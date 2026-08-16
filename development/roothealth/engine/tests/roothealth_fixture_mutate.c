#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static int full_write(int fd, const void *buffer, size_t length)
{
	const unsigned char *bytes = buffer;

	while (length) {
		ssize_t written = write(fd, bytes, length);
		if (written < 0) {
			if (errno == EINTR)
				continue;
			return -1;
		}
		if (!written) {
			errno = EIO;
			return -1;
		}
		bytes += written;
		length -= (size_t)written;
	}
	return 0;
}

int main(int argc, char **argv)
{
	unsigned char buffer[65536];
	struct stat source_stat;
	int source = -1, output = -1;
	int i, result = 1;

	if (argc < 3)
		return 5;
	source = open(argv[1], O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
	if (source < 0 || fstat(source, &source_stat) ||
		!S_ISREG(source_stat.st_mode))
		goto out;
	output = open(argv[2], O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC |
		O_NOFOLLOW, 0600);
	if (output < 0)
		goto out;
	for (;;) {
		ssize_t count = read(source, buffer, sizeof(buffer));
		if (count < 0) {
			if (errno == EINTR)
				continue;
			goto out;
		}
		if (!count)
			break;
		if (full_write(output, buffer, (size_t)count))
			goto out;
	}
	for (i = 3; i < argc; i++) {
		char *separator = strchr(argv[i], ':');
		char *end = NULL;
		uint64_t offset;
		unsigned long value;
		unsigned char byte;
		if (!separator)
			goto out;
		*separator = 0;
		errno = 0;
		offset = strtoull(argv[i], &end, 0);
		if (errno || !end || *end || offset >= (uint64_t)source_stat.st_size)
			goto out;
		errno = 0;
		value = strtoul(separator + 1, &end, 0);
		if (errno || !end || *end || value > 255U)
			goto out;
		byte = (unsigned char)value;
		if (pwrite(output, &byte, 1, (off_t)offset) != 1)
			goto out;
	}
	if (fsync(output))
		goto out;
	result = 0;
out:
	if (output >= 0 && close(output) && !result)
		result = 1;
	if (source >= 0)
		close(source);
	if (result && output >= 0)
		unlink(argv[2]);
	return result;
}
