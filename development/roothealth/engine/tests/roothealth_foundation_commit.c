#include "config.h"

#include <errno.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#include "roothealth_repair.h"

static int run_plan(struct rh_writer *writer, uint64_t serial,
		struct rh_boot_result *boot, size_t *planned)
{
	struct rh_identity_result identity;
	struct rh_mirror_result mirror;
	int result;

	result = roothealth_bootstrap_boot_plan(writer, serial, NULL, &identity,
		boot);
	if (result != RH_RESULT_OK)
		return result;
	if (writer->operation_count) {
		*planned += writer->operation_count;
		if (rh_writer_commit(writer))
			return RH_RESULT_IO;
		return RH_RESULT_OK;
	}
	result = roothealth_mftmirr_plan(writer, &boot->geometry, &mirror);
	if (result != RH_RESULT_OK)
		return result;
	if (writer->operation_count) {
		*planned += writer->operation_count;
		if (rh_writer_commit(writer))
			return RH_RESULT_IO;
	}
	return RH_RESULT_OK;
}

int main(int argc, char **argv)
{
	struct rh_writer writer;
	struct rh_boot_result boot;
	char *end = NULL;
	uint64_t serial;
	size_t planned = 0, verification_planned = 0;
	int require_plan = 1;
	int result;

	if (argc != 3 && argc != 4)
		return 5;
	errno = 0;
	serial = strtoull(argv[1], &end, 16);
	if (errno || !serial || !end || *end)
		return 5;
	if (argc == 4) {
		require_plan = (int)strtol(argv[3], &end, 10);
		if (!end || *end || (require_plan != 0 && require_plan != 1))
			return 5;
	}
	if (rh_writer_open(&writer, argv[2]))
		return 3;
	result = run_plan(&writer, serial, &boot, &planned);
	rh_writer_close(&writer);
	if (result != RH_RESULT_OK)
		return result;
	if (rh_writer_open(&writer, argv[2]))
		return 3;
	result = run_plan(&writer, serial, &boot, &verification_planned);
	rh_writer_close(&writer);
	if (result != RH_RESULT_OK || (require_plan && !planned) ||
		verification_planned) {
		fprintf(stderr, "result=%d planned=%zu verification=%zu\n", result,
			planned, verification_planned);
		return 1;
	}
	printf("foundation-commit result=0 planned=%zu fresh_plan=0\n", planned);
	return 0;
}
