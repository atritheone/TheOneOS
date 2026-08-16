/* ROOTHEALTH_REPAIR_ROLE(DIAGNOSTIC) */
#include "config.h"

#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "roothealth_wal.h"

#define TEST_RUN_COUNT 8193U

int main(void)
{
	struct rh_writer writer;
	struct rh_wal wal;
	size_t i;

	memset(&writer, 0, sizeof(writer));
	memset(&wal, 0, sizeof(wal));
	wal.writer = &writer;
	for (i = 0; i < TEST_RUN_COUNT; i++) {
		uint64_t stream = (uint64_t)i * 4096U;
		uint64_t device = ((uint64_t)i + TEST_RUN_COUNT) * 4096U;

		if (rh_wal_test_append_run(&wal, stream, device, 4096U))
			return 1;
	}
	if (wal.run_count != TEST_RUN_COUNT ||
			wal.run_capacity < wal.run_count || !wal.runs ||
			wal.runs[TEST_RUN_COUNT - 1U].stream_offset !=
				(uint64_t)(TEST_RUN_COUNT - 1U) * 4096U)
		return 1;
	rh_wal_uninstall_backend(&wal);
	if (wal.runs || wal.run_count || wal.run_capacity)
		return 1;
	printf("wal-run-capacity runs=%u dynamic=1 fixed-cap=removed cleanup=1\n",
		TEST_RUN_COUNT);
	return 0;
}
