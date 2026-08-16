/* ROOTHEALTH_REPAIR_ROLE(DIAGNOSTIC) */
#include "config.h"

#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "roothealth_free_slot_authority.h"
#include "roothealth_wal.h"

#define DEVICE_SIZE UINT64_C(536870912)
#define RUN_LENGTH UINT64_C(67108864)

static int setup(struct rh_writer *writer, struct rh_wal *wal,
		struct rh_wal_observation *observation)
{
	static const unsigned char uuid[16] = {
		0x10, 0x32, 0x54, 0x76, 0x98, 0xba, 0x4c, 0xde,
		0x8f, 0x01, 0x23, 0x45, 0x67, 0x89, 0xab, 0xcd
	};

	memset(writer, 0, sizeof(*writer));
	memset(wal, 0, sizeof(*wal));
	memset(observation, 0, sizeof(*observation));
	writer->read_fd = 12345;
	writer->write_fd = -1;
	writer->device_size = DEVICE_SIZE;
	wal->writer = writer;
	wal->observation = observation;
	wal->sector_size = 512U;
	wal->volume_serial = UINT64_C(0x1122334455667788);
	wal->journal_record = 81U;
	wal->journal_sequence = 1U;
	wal->data_size = RH_WAL_SIZE;
	wal->journal_record_device_offset = UINT64_C(400000000);
	wal->journal_record_device_length = 1024U;
	memcpy(wal->journal_uuid, uuid, sizeof(uuid));
	if (rh_wal_test_append_run(wal, 0U, UINT64_C(16777216), RUN_LENGTH) ||
			rh_wal_test_append_run(wal, RUN_LENGTH, UINT64_C(134217728),
				RUN_LENGTH) ||
			rh_writer_exclude(writer, UINT64_C(134217728), RUN_LENGTH) ||
			rh_writer_exclude(writer, wal->journal_record_device_offset, 1024U) ||
			rh_writer_exclude(writer, DEVICE_SIZE - 512U, 512U) ||
			rh_writer_exclude(writer, UINT64_C(16777216), RUN_LENGTH) ||
			rh_writer_allow_raw_wal(writer, UINT64_C(16777216), RUN_LENGTH) ||
			rh_writer_allow_raw_wal(writer, UINT64_C(134217728), RUN_LENGTH))
		return -1;
	observation->checked = 1;
	observation->present = 1;
	observation->valid = 1;
	observation->fast_path_trusted = 1;
	observation->write_safe = 1;
	observation->ownership_census_complete = 1;
	observation->max_entry_count = RH_WAL_MAX_ENTRIES;
	observation->volume_serial = wal->volume_serial;
	rh_uuid_format(wal->journal_uuid, observation->journal_uuid);
	return 0;
}

int main(void)
{
	struct rh_writer writer;
	struct rh_wal wal;
	struct rh_wal_observation observation;
	struct rh_free_slot_component_seal *first = NULL, *second = NULL;
	unsigned char first_hash[32], second_hash[32];
	int result = 1;

	if (setup(&writer, &wal, &observation) ||
			rh_wal_create_free_slot_exclusion_seal(&wal, 7U, &first) ||
			rh_free_slot_component_seal_kind(first) !=
				RH_FREE_SLOT_COMPONENT_WAL_EXCLUSIONS ||
			rh_free_slot_component_seal_hash(first, first_hash))
		goto out;
	/* Mutable WAL header state/generation is deliberately outside RHWEX1. */
	wal.generation = 999U;
	wal.state = RH_WAL_APPLYING;
	wal.entry_count = 3U;
	if (rh_wal_create_free_slot_exclusion_seal(&wal, 99U, &second) ||
			rh_free_slot_component_seal_hash(second, second_hash) ||
			memcmp(first_hash, second_hash, sizeof(first_hash)))
		goto out;
	rh_free_slot_component_seal_destroy(second);
	second = NULL;
	observation.ownership_census_complete = 0;
	if (!rh_wal_create_free_slot_exclusion_seal(&wal, 7U, &second) ||
			errno != EPERM)
		goto out;
	observation.ownership_census_complete = 1;
	writer.raw_wal_allowed[0].offset++;
	if (!rh_wal_create_free_slot_exclusion_seal(&wal, 7U, &second))
		goto out;
	writer.raw_wal_allowed[0].offset--;
	wal.runs[1].stream_offset++;
	if (!rh_wal_create_free_slot_exclusion_seal(&wal, 7U, &second))
		goto out;
	printf("wal-exclusion-seal runs=2 exclusions=4 raw=2 complete=1 "
		"generation-independent=1 incomplete-refused=1 retarget-refused=1\n");
	result = 0;
out:
	rh_free_slot_component_seal_destroy(second);
	rh_free_slot_component_seal_destroy(first);
	rh_wal_uninstall_backend(&wal);
	writer.read_fd = -1;
	rh_writer_close(&writer);
	return result;
}
