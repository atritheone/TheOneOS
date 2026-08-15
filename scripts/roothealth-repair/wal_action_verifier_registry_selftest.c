#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define ROOTHEALTH_WAL_TEST_HOOKS 1
#include "roothealth_wal.h"

struct callback_state {
	unsigned int calls;
	int mutate;
	int failure_errno;
	struct rh_writer *closure_writer;
};

static struct callback_state state;
static unsigned int mixed_builtin_calls;

static int exact_verifier(
		const struct rh_wal_action_verifier_context *context)
{
	unsigned char preimage_byte;
	unsigned char payload_byte;
	const struct rh_wal_recovery_entry_view *entry = NULL;
	size_t i;

	if (!context ||
		context->version != RH_WAL_ACTION_VERIFIER_ABI_VERSION ||
		context->action_id != RH_WRITE_ACTION_ID(RH_WRITE_BITMAP_MFT) ||
		context->transaction_kind != RH_WAL_TX_METADATA_REPAIR ||
		context->state != RH_WAL_APPLYING)
		return -1;
	for (i = 0; i < context->entry_count; i++)
		if (context->entries[i].action_id == context->action_id) {
			if (entry)
				return -1;
			entry = &context->entries[i];
		}
	if (!entry || entry->target.owner_mft_record != 0U ||
		entry->target.attribute_type != 0xb0U ||
		rh_wal_preimage_size(context->preimage) < entry->target_offset + 1U ||
		rh_wal_preimage_read(context->preimage, entry->target_offset, 1,
			&preimage_byte) ||
		rh_wal_entry_old_read(context, entry->ordinal, 0, 1, &payload_byte) ||
		preimage_byte != 0xa5U || payload_byte != 0xa5U)
		return -1;
	state.calls++;
	if (state.failure_errno) {
		errno = state.failure_errno;
		return -1;
	}
	if (state.mutate && state.closure_writer)
		state.closure_writer->planned_bytes++;
	return 0;
}

static int mixed_builtin_verifier(
		const struct rh_wal_action_verifier_context *context)
{
	unsigned char preimage_byte;
	unsigned char payload_byte;
	const struct rh_wal_recovery_entry_view *entry = NULL;
	size_t i;

	if (!context || context->action_id !=
			RH_WRITE_ACTION_ID(RH_WRITE_BITMAP_CLUSTER))
		return -1;
	for (i = 0; i < context->entry_count; i++)
		if (context->entries[i].action_id == context->action_id)
			entry = &context->entries[i];
	if (!entry || entry->target.owner_mft_record != 6U ||
		entry->target.attribute_type != 0x80U ||
		rh_wal_preimage_read(context->preimage, entry->target_offset, 1,
			&preimage_byte) ||
		rh_wal_entry_old_read(context, entry->ordinal, 0, 1, &payload_byte) ||
		preimage_byte != 0xb6U || payload_byte != 0xb6U)
		return -1;
	mixed_builtin_calls++;
	return 0;
}

static void fill_fixture(struct rh_wal *wal,
		struct rh_wal_observation *observation, struct rh_writer *preimage,
		struct rh_write_operation *operation,
		struct rh_wal_recovery_entry_view *entry, unsigned char old[512])
{
	unsigned char empty_hash[32];
	unsigned char before_hash[32];

	memset(wal, 0, sizeof(*wal));
	memset(observation, 0, sizeof(*observation));
	memset(preimage, 0, sizeof(*preimage));
	memset(operation, 0, sizeof(*operation));
	memset(entry, 0, sizeof(*entry));
	memset(old, 0xa5, 512);
	preimage->read_fd = open("/dev/zero", O_RDONLY | O_CLOEXEC);
	preimage->write_fd = -1;
	preimage->device_size = 512U;
	preimage->operations = operation;
	preimage->operation_count = 1U;
	preimage->operation_capacity = 1U;
	operation->offset = 0;
	operation->length = 512U;
	operation->after = old;
	wal->writer = preimage;
	wal->observation = observation;
	observation->valid = 1;
	wal->transaction_kind = RH_WAL_TX_METADATA_REPAIR;
	wal->state = RH_WAL_APPLYING;
	wal->generation = 9U;
	wal->volume_serial = 0x1122334455667788ULL;
	wal->journal_record = 81U;
	wal->journal_sequence = 1U;
	entry->ordinal = 1U;
	entry->action_id = RH_WRITE_ACTION_ID(RH_WRITE_BITMAP_MFT);
	entry->target_offset = 0;
	entry->length = 512U;
	rh_sha256(old, 512U, entry->old_hash);
	memset(entry->new_hash, 0x11, sizeof(entry->new_hash));
	entry->target.seal_version = 1U;
	entry->target.object = RH_WRITE_TARGET_NONRESIDENT_ATTRIBUTE;
	entry->target.owner_mft_record = 0U;
	entry->target.owner_sequence = 1U;
	entry->target.attribute_type = 0xb0U;
	entry->target.flags = RH_WRITE_TARGET_NONRESIDENT |
		RH_WRITE_TARGET_SET_ONLY;
	rh_sha256("", 0, empty_hash);
	memcpy(entry->target.attribute_name_hash, empty_hash, 32);
	entry->target.lowest_vcn = 0;
	entry->target.logical_vcn = 0;
	entry->target.logical_offset = 0;
	entry->target.logical_length = 1U;
	entry->target.semantic_target_offset = 0;
	entry->target.semantic_target_length = 1U;
	entry->target.lcn = 0;
	entry->target.evidence_version = 1U;
	entry->target.evidence_generation = 9U;
	memset(entry->target.evidence_hash, 0x22,
		sizeof(entry->target.evidence_hash));
	memset(entry->target.staged_view_hash, 0x33,
		sizeof(entry->target.staged_view_hash));
	rh_sha256(old, 1U, before_hash);
	memcpy(entry->target.semantic_before_hash, before_hash, 32);
	memset(entry->target.semantic_after_hash, 0x44,
		sizeof(entry->target.semantic_after_hash));
	entry->target.finalized = 1;
}

int main(void)
{
	struct rh_wal wal;
	struct rh_wal_observation observation;
	struct rh_writer preimage;
	struct rh_write_operation operation;
	struct rh_wal_recovery_entry_view entry;
	const unsigned char *old_payloads[1];
	unsigned char old[512];

	fill_fixture(&wal, &observation, &preimage, &operation, &entry, old);
	if (preimage.read_fd < 0)
		return 64;
	old_payloads[0] = old;
	errno = 0;
	if (rh_wal_test_dispatch_action_verifiers(&wal, &preimage, &entry,
			old_payloads, 1U) !=
			-1 || errno != EOPNOTSUPP)
		return 1;
	errno = 0;
	if (rh_wal_register_action_verifier(&wal,
			RH_WRITE_ACTION_ID(RH_WRITE_LOGFILE_REDO), exact_verifier) != -1 ||
		errno != EOPNOTSUPP)
		return 2;
	memset(&state, 0, sizeof(state));
	state.closure_writer = &preimage;
	if (rh_wal_register_action_verifier(&wal,
			RH_WRITE_ACTION_ID(RH_WRITE_BITMAP_MFT), exact_verifier) ||
		rh_wal_test_dispatch_action_verifiers(&wal, &preimage, &entry,
			old_payloads, 1U) ||
		state.calls != 1U)
		return 3;
	errno = 0;
	if (rh_wal_register_action_verifier(&wal,
			RH_WRITE_ACTION_ID(RH_WRITE_BITMAP_MFT), exact_verifier) != -1 ||
		errno != EEXIST)
		return 4;
	state.failure_errno = EIO;
	errno = 0;
	if (rh_wal_test_dispatch_action_verifiers(&wal, &preimage, &entry,
			old_payloads, 1U) != -1 || errno != EIO)
		return 5;
	state.failure_errno = ENOMEM;
	errno = 0;
	if (rh_wal_test_dispatch_action_verifiers(&wal, &preimage, &entry,
			old_payloads, 1U) != -1 || errno != ENOMEM)
		return 6;
	state.failure_errno = 0;
	state.mutate = 1;
	errno = 0;
	if (rh_wal_test_dispatch_action_verifiers(&wal, &preimage, &entry,
			old_payloads, 1U) !=
			-1 || errno != EINVAL || preimage.planned_bytes != 1U)
		return 7;
	preimage.planned_bytes = 0;
	rh_wal_test_install_builtin_action_verifiers(&wal);
	if (!wal.action_verifiers[
			RH_WRITE_ACTION_ID(RH_WRITE_BITMAP_CLUSTER)].verify ||
		wal.action_verifiers[
			RH_WRITE_ACTION_ID(RH_WRITE_BITMAP_CLUSTER)].verify !=
		wal.action_verifiers[
			RH_WRITE_ACTION_ID(RH_WRITE_VOLUME_DIRTY_SET)].verify ||
		wal.action_verifiers[
			RH_WRITE_ACTION_ID(RH_WRITE_BITMAP_CLUSTER)].verify !=
		wal.action_verifiers[
			RH_WRITE_ACTION_ID(RH_WRITE_VOLUME_DIRTY_CLEAR)].verify) {
		return 8;
	}
	errno = 0;
	if (rh_wal_register_action_verifier(&wal,
			RH_WRITE_ACTION_ID(RH_WRITE_BITMAP_CLUSTER), exact_verifier) != -1 ||
		errno != EEXIST)
		return 8;
	{
		struct rh_wal_recovery_entry_view mixed_entries[2];
		struct rh_write_operation mixed_operations[2];
		const unsigned char *mixed_payloads[2];
		unsigned char cluster_old[512];
		unsigned char digest[32];

		memset(mixed_operations, 0, sizeof(mixed_operations));
		memset(cluster_old, 0xb6, sizeof(cluster_old));
		mixed_entries[0] = entry;
		mixed_entries[0].ordinal = 1U;
		mixed_entries[1] = entry;
		mixed_entries[1].ordinal = 2U;
		mixed_entries[1].action_id =
			RH_WRITE_ACTION_ID(RH_WRITE_BITMAP_CLUSTER);
		mixed_entries[1].target_offset = 512U;
		mixed_entries[1].target.owner_mft_record = 6U;
		mixed_entries[1].target.attribute_type = 0x80U;
		mixed_entries[1].target.logical_vcn = 1;
		mixed_entries[1].target.logical_offset = 4096U;
		mixed_entries[1].target.semantic_target_offset = 512U;
		mixed_entries[1].target.lcn = 1;
		rh_sha256(cluster_old, sizeof(cluster_old),
			mixed_entries[1].old_hash);
		rh_sha256(cluster_old, 1U, digest);
		memcpy(mixed_entries[1].target.semantic_before_hash, digest, 32);
		mixed_operations[0].offset = 512U;
		mixed_operations[0].length = sizeof(cluster_old);
		mixed_operations[0].after = cluster_old;
		mixed_operations[1].offset = 0;
		mixed_operations[1].length = sizeof(old);
		mixed_operations[1].after = old;
		mixed_payloads[0] = old;
		mixed_payloads[1] = cluster_old;
		preimage.device_size = 1024U;
		preimage.operations = mixed_operations;
		preimage.operation_count = 2U;
		preimage.operation_capacity = 2U;
		memset(&state, 0, sizeof(state));
		state.closure_writer = &preimage;
		mixed_builtin_calls = 0;
		wal.action_verifiers[
			RH_WRITE_ACTION_ID(RH_WRITE_BITMAP_CLUSTER)].verify =
			mixed_builtin_verifier;
		if (rh_wal_test_dispatch_action_verifiers(&wal, &preimage,
				mixed_entries, mixed_payloads, 2U) || state.calls != 1U ||
			mixed_builtin_calls != 1U)
			return 9;
	}
	if (close(preimage.read_fd))
		return 10;
	puts("wal-action-verifier-registry self-test: PASS (9/9)");
	return 0;
}
