#include "config.h"

#include <errno.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "roothealth_wal.h"
#include "roothealth_write.h"

int main(int argc, char **argv)
{
	struct rh_writer writer;
	struct rh_wal wal;
	struct rh_wal_observation observation;
	unsigned char uuid[16];
	char *end = NULL;
	uint64_t serial, record;
	unsigned long sequence;
	int result;

	if ((argc != 6 && argc != 7) || rh_uuid_parse(argv[2], uuid))
		return 64;
	errno = 0;
	serial = strtoull(argv[1], &end, 16);
	if (errno || !serial || !end || *end)
		return 64;
	errno = 0;
	record = strtoull(argv[3], &end, 10);
	if (errno || !record || !end || *end)
		return 64;
	errno = 0;
	sequence = strtoul(argv[4], &end, 10);
	if (errno || !sequence || sequence > UINT16_MAX || !end || *end)
		return 64;
	if (rh_writer_open(&writer, argv[5])) {
		perror("rh_writer_open");
		return 1;
	}
	result = rh_wal_locate_and_validate(&wal, &writer, serial, uuid,
		record, (uint16_t)sequence, &observation);
	printf("result=%d checked=%d present=%d valid=%d fast=%d "
		"unreadable=%"PRIu64" duplicates=%"PRIu64" ownership=%d "
		"write_safe=%d mft_bitmap=%d cluster_false_free=%"PRIu64" state=%d "
		"tx=%d cap=%d runs=%zu allowed=%zu excluded=%zu writes=%zu\n",
		result, observation.checked, observation.present, observation.valid,
		observation.fast_path_trusted,
		observation.unreadable_record_count,
		observation.definite_duplicate_count,
		observation.ownership_census_complete, observation.write_safe,
		observation.journal_mft_bitmap_allocated,
		observation.journal_cluster_bitmap_false_free_count,
		observation.state,
		observation.transaction_kind, observation.max_entry_count,
		wal.run_count, writer.raw_wal_allowed_count, writer.excluded_count,
		writer.write_boundaries);
	if (!result && argc == 7 && !strcmp(argv[6], "reconstruct")) {
		if (rh_wal_reconstruct_degraded(&wal)) {
			perror("rh_wal_reconstruct_degraded");
			result = 1;
		} else {
			printf("reconstructed=1 writes=%zu\n", writer.write_boundaries);
		}
	}
	rh_wal_uninstall_backend(&wal);
	rh_writer_close(&writer);
	return result;
}
