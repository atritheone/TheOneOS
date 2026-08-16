#include "config.h"

#include <errno.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "roothealth_repair.h"

int main(int argc, char **argv)
{
	struct rh_writer writer;
	struct rh_identity_result identity;
	struct rh_boot_result boot;
	struct rh_mirror_result mirror;
	char *end = NULL;
	uint64_t expected_serial;
	long expected_result, expected_operations;
	int result;

	memset(&mirror, 0, sizeof(mirror));

	if (argc != 5)
		return 5;
	errno = 0;
	expected_serial = strtoull(argv[1], &end, 16);
	if (errno || !expected_serial || !end || *end)
		return 5;
	expected_result = strtol(argv[2], &end, 10);
	if (errno || !end || *end || expected_result < 0 || expected_result > 5)
		return 5;
	expected_operations = strtol(argv[3], &end, 10);
	if (errno || !end || *end || expected_operations < 0)
		return 5;
	if (rh_writer_open(&writer, argv[4]))
		return 3;
	result = roothealth_bootstrap_boot_plan(&writer, expected_serial, NULL,
		&identity, &boot);
	if (result == RH_RESULT_OK && !writer.operation_count)
		result = roothealth_mftmirr_plan(&writer, &boot.geometry, &mirror);
	if (result != expected_result ||
		writer.operation_count != (size_t)expected_operations) {
		fprintf(stderr, "expected=%ld/%ld result=%d operations=%zu "
			"checked=%u primary=%u mirror=%u ambiguous=%u\n",
			expected_result, expected_operations, result,
			writer.operation_count, mirror.records_checked,
			mirror.primary_repaired, mirror.mirror_repaired,
			mirror.ambiguous_records);
		rh_writer_close(&writer);
		return 1;
	}
	printf("mftmirr result=%d operations=%zu checked=%u primary=%u "
		"mirror=%u ambiguous=%u\n", result, writer.operation_count,
		mirror.records_checked, mirror.primary_repaired,
		mirror.mirror_repaired, mirror.ambiguous_records);
	rh_writer_close(&writer);
	return 0;
}
