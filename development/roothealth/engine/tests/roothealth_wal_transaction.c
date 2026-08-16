#include "config.h"

#include <errno.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "roothealth_wal.h"
#include "roothealth_write.h"

static int parse_u64(const char *text, int base, uint64_t *value)
{
	char *end = NULL;

	errno = 0;
	*value = strtoull(text, &end, base);
	return errno || !*value || !end || *end ? -1 : 0;
}

int main(int argc, char **argv)
{
	struct rh_writer writer;
	struct rh_wal wal;
	struct rh_wal_observation observation;
	unsigned char uuid[16], before[512], after[512];
	uint64_t serial, record, target;
	uint64_t sequence;
	int result = 1;

	if (argc != 7 || parse_u64(argv[1], 16, &serial) ||
		rh_uuid_parse(argv[2], uuid) || parse_u64(argv[3], 10, &record) ||
		parse_u64(argv[4], 10, &sequence) || sequence > UINT16_MAX ||
		parse_u64(argv[5], 0, &target))
		return 64;
	if (rh_writer_open(&writer, argv[6]))
		return 1;
	if (rh_wal_locate_and_validate(&wal, &writer, serial, uuid, record,
			(uint16_t)sequence, &observation) ||
		rh_writer_read(&writer, target & ~511ULL, sizeof(before), before) ||
		rh_wal_install_backend(&wal, RH_WAL_TX_METADATA_REPAIR))
		goto out;
	memcpy(after, before, sizeof(after));
	after[target & 511U] ^= 1;
	after[(target & 511U) + 1] ^= 2;
	if (rh_writer_plan(&writer, RH_WRITE_ATTRIBUTE_DATA, target, 1,
			after + (target & 511U)) ||
		rh_writer_plan(&writer, RH_WRITE_ATTRIBUTE_DATA, target + 1, 1,
			after + (target & 511U) + 1) ||
		rh_writer_plan(&writer, RH_WRITE_ATTRIBUTE_DATA, target + 1, 1,
			after + (target & 511U) + 1) ||
		writer.operation_count != 2 || rh_writer_commit(&writer) ||
		wal.state != RH_WAL_COMMITTED || wal.entry_count != 2 ||
		wal.target_bytes != 1024 || wal.planned_count != 2)
		goto out;
	rh_writer_reset_plan(&writer);
	if (rh_wal_rollback(&wal) || wal.state != RH_WAL_EMPTY ||
		rh_writer_read(&writer, target & ~511ULL, sizeof(after), after) ||
		memcmp(before, after, sizeof(before)))
		goto out;
	printf("entries=2 expanded_bytes=1024 chained=1 rollback=1 "
		"writes=%zu syncs=%zu\n", writer.write_boundaries,
		writer.sync_count);
	result = 0;
out:
	rh_wal_uninstall_backend(&wal);
	rh_writer_close(&writer);
	return result;
}
