#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

#define ROOTHEALTH_WAL_TEST_HOOKS 1
#include "roothealth_wal.h"

static void fill_target(struct rh_wal_recovery_entry_view *entry,
		uint64_t ordinal, enum rh_write_kind kind, uint64_t offset,
		uint64_t owner, unsigned char *old)
{
	unsigned char digest[32];

	memset(entry, 0, sizeof(*entry));
	entry->ordinal = ordinal;
	entry->action_id = RH_WRITE_ACTION_ID(kind);
	entry->target_offset = offset;
	entry->length = 512U;
	rh_sha256(old, 512U, entry->old_hash);
	memset(entry->new_hash, 0x5a, sizeof(entry->new_hash));
	entry->target.seal_version = 1U;
	entry->target.object = RH_WRITE_TARGET_NONRESIDENT_ATTRIBUTE;
	entry->target.owner_mft_record = owner;
	entry->target.owner_sequence = 1U;
	entry->target.attribute_instance = 1U;
	entry->target.attribute_type = 0x80U;
	entry->target.flags = RH_WRITE_TARGET_NONRESIDENT;
	rh_sha256("", 0, entry->target.attribute_name_hash);
	entry->target.lowest_vcn = 0;
	entry->target.logical_vcn = (int64_t)(offset / 4096U);
	entry->target.logical_offset = offset;
	entry->target.logical_length = 512U;
	entry->target.semantic_target_offset = offset;
	entry->target.semantic_target_length = 512U;
	entry->target.lcn = (int64_t)(offset / 4096U);
	entry->target.evidence_version = 1U;
	entry->target.evidence_generation = 11U;
	memset(entry->target.evidence_hash, 0x31,
		sizeof(entry->target.evidence_hash));
	memset(entry->target.staged_view_hash, 0x32,
		sizeof(entry->target.staged_view_hash));
	rh_sha256(old, 512U, digest);
	memcpy(entry->target.semantic_before_hash, digest, 32U);
	memset(entry->target.semantic_after_hash, 0x33,
		sizeof(entry->target.semantic_after_hash));
	entry->target.finalized = 1;
}

int main(void)
{
	static const enum rh_wal_state states[] = {
		RH_WAL_PREPARING, RH_WAL_APPLYING, RH_WAL_COMMITTED,
	};
	struct rh_wal_recovery_entry_view entries[2];
	struct rh_write_operation operations[2];
	struct rh_wal_observation observation;
	struct rh_writer preimage;
	struct rh_wal wal;
	const unsigned char *payloads[2];
	unsigned char upcase_old[512], attrdef_old[512];
	size_t i;

	memset(&wal, 0, sizeof(wal));
	memset(&observation, 0, sizeof(observation));
	memset(&preimage, 0, sizeof(preimage));
	memset(operations, 0, sizeof(operations));
	memset(upcase_old, 0, sizeof(upcase_old));
	memset(attrdef_old, 0, sizeof(attrdef_old));
	preimage.read_fd = open("/dev/zero", O_RDONLY | O_CLOEXEC);
	preimage.write_fd = -1;
	preimage.device_size = 4096U;
	preimage.operations = operations;
	preimage.operation_count = 2U;
	preimage.operation_capacity = 2U;
	fill_target(&entries[0], 1U, RH_WRITE_UPCASE_DATA, 0, 10U,
		upcase_old);
	fill_target(&entries[1], 2U, RH_WRITE_ATTRDEF_DATA, 512U, 4U,
		attrdef_old);
	operations[1].offset = 0;
	operations[1].length = sizeof(upcase_old);
	operations[1].after = upcase_old;
	operations[0].offset = 512U;
	operations[0].length = sizeof(attrdef_old);
	operations[0].after = attrdef_old;
	payloads[0] = upcase_old;
	payloads[1] = attrdef_old;
	wal.writer = &preimage;
	wal.observation = &observation;
	observation.valid = 1;
	wal.transaction_kind = RH_WAL_TX_METADATA_REPAIR;
	wal.generation = 11U;
	for (i = 0; i < sizeof(states) / sizeof(states[0]); i++) {
		wal.state = states[i];
		errno = 0;
		if (rh_wal_test_dispatch_action_verifiers(&wal, &preimage,
				entries, payloads, 2U) != -1 || errno != EOPNOTSUPP ||
				wal.action_verifiers[20].verify ||
				wal.action_verifiers[21].verify ||
				preimage.planned_bytes || preimage.write_boundaries)
			return 1;
	}
	if (close(preimage.read_fd))
		return 2;
	puts("fixed-metadata WAL closed self-test: PASS (3/3 crash states)");
	return 0;
}
