#include "config.h"

#include <errno.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#include "roothealth_repair.h"

int main(int argc, char **argv)
{
	struct rh_writer writer;
	struct rh_identity_result identity;
	struct rh_boot_result boot;
	char *end = NULL;
	uint64_t expected_serial;
	long expected_result;
	int result;

	if (argc != 4)
		return 5;
	errno = 0;
	expected_serial = strtoull(argv[1], &end, 16);
	if (errno || !expected_serial || !end || *end)
		return 5;
	errno = 0;
	expected_result = strtol(argv[2], &end, 10);
	if (errno || !end || *end || expected_result < 0 || expected_result > 5)
		return 5;
	if (rh_writer_open(&writer, argv[3]))
		return 3;
	result = roothealth_bootstrap_boot_plan(&writer, expected_serial,
		"T1OS", &identity, &boot);
	if (result != expected_result || writer.operation_count) {
		fprintf(stderr, "expected=%ld result=%d operations=%zu primary=%d "
			"backup=%d serials=%016"PRIx64"/%016"PRIx64"\n",
			expected_result, result, writer.operation_count,
			identity.primary_boot_valid, identity.backup_boot_valid,
			identity.observed_primary_serial,
			identity.observed_backup_serial);
		rh_writer_close(&writer);
		return 1;
	}
	printf("bootstrap result=%d operations=0 primary=%d backup=%d "
		"geometry_supported=%d\n", result, identity.primary_boot_valid,
		identity.backup_boot_valid, boot.geometry_supported);
	rh_writer_close(&writer);
	return 0;
}
