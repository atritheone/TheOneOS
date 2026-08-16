#include "config.h"

#include <errno.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "roothealth_wal.h"

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
	unsigned char uuid[16];
	uint64_t serial, record, sequence;
	int initial_state;
	int result = 1;

	if (argc != 6 || parse_u64(argv[1], 16, &serial) ||
			rh_uuid_parse(argv[2], uuid) || parse_u64(argv[3], 10, &record) ||
			parse_u64(argv[4], 10, &sequence) || sequence > UINT16_MAX)
		return 64;
	if (rh_writer_open(&writer, argv[5]))
		return 3;
	if (rh_wal_locate_and_validate(&wal, &writer, serial, uuid, record,
			(uint16_t)sequence, &observation))
		goto out;
	initial_state = wal.state;
	if (wal.state != RH_WAL_EMPTY) {
		struct rh_wal_committed_entry *entries = NULL;
		size_t entry_count = 0;
		if (rh_wal_recovery_entries(&wal, &entries, &entry_count)) {
			fprintf(stderr, "recovery-entry snapshot failed: %s\n",
				strerror(errno));
			goto out;
		}
		fprintf(stderr, "recovery-entry snapshot count=%zu state=%d kind=%d\n",
			entry_count, (int)wal.state, (int)wal.transaction_kind);
		free(entries);
	}
	if (wal.state != RH_WAL_EMPTY && rh_wal_rollback(&wal))
		goto out;
	printf("wal-recover initial_state=%d final_state=%d entries=%"PRIu64
		" write_boundaries=%zu write_safe=%d\n", initial_state,
		(int)wal.state, wal.entry_count, writer.write_boundaries,
		observation.write_safe);
	result = 0;
out:
	rh_wal_uninstall_backend(&wal);
	rh_writer_close(&writer);
	return result;
}
