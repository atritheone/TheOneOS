/* ROOTHEALTH_REPAIR_ROLE(TYPED_WAL_ADAPTER) ROOTHEALTH_IO_ROLE(RAW_WAL) */
#include "config.h"

#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#ifdef __linux__
#include <sys/random.h>
#endif

#include "attrib.h"
#include "device.h"
#include "dir.h"
#include "endians.h"
#include "inode.h"
#include "layout.h"
#include "logfile.h"
#include "mft.h"
#include "mst.h"
#include "roothealth_bitmap.h"
#include "roothealth_census_device.h"
#include "roothealth_complete_census.h"
#include "roothealth_coverage.h"
#include "roothealth_dirty.h"
#include "roothealth_free_slot_authority_internal.h"
#include "roothealth_hash_stream.h"
#include "roothealth_index_bitmap.h"
#include "roothealth_mft_bitmap.h"
#include "roothealth_namespace_repair.h"
#include "roothealth_overlay.h"
#include "roothealth_raw_mft.h"
#include "roothealth_repair.h"
#include "roothealth_recover.h"
#include "roothealth_wal.h"
#include "runlist.h"
#include "volume.h"

#define RH_WAL_HEADER_SIZE 4096U
#define RH_WAL_ENTRY_START 8192ULL
#define RH_WAL_HEADER_DIGEST 0xfe0U
#define RH_WAL_DESCRIPTOR_SIZE 512U
#define RH_WAL_DESCRIPTOR_DIGEST 0x1e0U
#define RH_WAL_PLAN_BYTES RH_WAL_DESCRIPTOR_PLAN_BYTES
#define RH_WAL_JOURNAL_FILE_FLAGS UINT32_C(0x00002007)

static const unsigned char rh_wal_magic[16] = "T1ROOTHEALTHWAL";
static const unsigned char rh_entry_magic[8] = "RHENTRY1";

static int rh_wal_builtin_bitmap_dirty_verifier(
		const struct rh_wal_action_verifier_context *context);

static void rh_wal_install_builtin_action_verifiers(struct rh_wal *wal)
{
	static const enum rh_write_kind kinds[] = {
		RH_WRITE_INDEX_ROOT,
		RH_WRITE_INDEX_BITMAP,
		RH_WRITE_BITMAP_MFT,
		RH_WRITE_BITMAP_CLUSTER,
		RH_WRITE_VOLUME_DIRTY_SET,
		RH_WRITE_VOLUME_DIRTY_CLEAR
	};
	size_t i;

	for (i = 0; i < sizeof(kinds) / sizeof(kinds[0]); i++)
		wal->action_verifiers[RH_WRITE_ACTION_ID(kinds[i])].verify =
			rh_wal_builtin_bitmap_dirty_verifier;
}

#ifdef ROOTHEALTH_WAL_TEST_HOOKS
void rh_wal_test_install_builtin_action_verifiers(struct rh_wal *wal)
{
	if (wal)
		rh_wal_install_builtin_action_verifiers(wal);
}
#endif

struct rh_wal_planned_entry {
	uint64_t target_offset;
	uint64_t length;
	uint64_t payload_offset;
	uint64_t padded_length;
	uint32_t kind;
	unsigned char old_hash[32];
	unsigned char new_hash[32];
	struct rh_write_semantic_target target;
	unsigned char *before;
	unsigned char *after;
};

int rh_wal_committed_entry_at(const struct rh_wal *wal, size_t ordinal,
		struct rh_wal_committed_entry *entry)
{
	const struct rh_wal_planned_entry *source;

	if (!wal || !entry || ordinal >= wal->planned_count ||
			wal->state != RH_WAL_COMMITTED) {
		errno = EINVAL;
		return -1;
	}
	source = &wal->planned_entries[ordinal];
	memset(entry, 0, sizeof(*entry));
	entry->action_id = source->kind;
	entry->target_offset = source->target_offset;
	entry->length = source->length;
	memcpy(entry->before_hash, source->old_hash, sizeof(entry->before_hash));
	memcpy(entry->after_hash, source->new_hash, sizeof(entry->after_hash));
	entry->target = source->target;
	return 0;
}

static void rh_wal_free_runs(struct rh_wal *wal)
{
	if (!wal)
		return;
	free(wal->runs);
	wal->runs = NULL;
	wal->run_count = 0;
	wal->run_capacity = 0;
	wal->data_size = 0;
}

static int rh_wal_append_run(struct rh_wal *wal,
		const struct rh_wal_run *run)
{
	struct rh_wal_run *grown;
	size_t capacity;

	if (!wal || !run || !run->length || wal->run_count == SIZE_MAX) {
		errno = EINVAL;
		return -1;
	}
	if (wal->run_count == wal->run_capacity) {
		capacity = wal->run_capacity ? wal->run_capacity : 64U;
		if (capacity > SIZE_MAX / 2U)
			capacity = wal->run_count + 1U;
		else
			capacity *= 2U;
		if (capacity < wal->run_count + 1U ||
				capacity > SIZE_MAX / sizeof(*grown)) {
			errno = EOVERFLOW;
			return -1;
		}
		grown = realloc(wal->runs, capacity * sizeof(*grown));
		if (!grown)
			return -1;
		wal->runs = grown;
		wal->run_capacity = capacity;
	}
	wal->runs[wal->run_count++] = *run;
	return 0;
}

#ifdef ROOTHEALTH_WAL_TEST_HOOKS
int rh_wal_test_append_run(struct rh_wal *wal, uint64_t stream_offset,
		uint64_t device_offset, uint64_t length)
{
	const struct rh_wal_run run = {
		.stream_offset = stream_offset,
		.device_offset = device_offset,
		.length = length
	};

	return rh_wal_append_run(wal, &run);
}
#endif

static uint16_t rh_get_u16(const unsigned char *p)
{
	return (uint16_t)p[0] | ((uint16_t)p[1] << 8);
}

static uint32_t rh_get_u32(const unsigned char *p)
{
	return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
		((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static uint64_t rh_get_u64(const unsigned char *p)
{
	uint64_t value = 0;
	unsigned int i;

	for (i = 0; i < 8; i++)
		value |= (uint64_t)p[i] << (8U * i);
	return value;
}

static int64_t rh_get_s64(const unsigned char *p)
{
	uint64_t value = rh_get_u64(p);

	if (value <= INT64_MAX)
		return (int64_t)value;
	return -1 - (int64_t)(~value);
}

static void rh_put_u16(unsigned char *p, uint16_t value)
{
	p[0] = (unsigned char)value;
	p[1] = (unsigned char)(value >> 8);
}

static void rh_put_u32(unsigned char *p, uint32_t value)
{
	p[0] = (unsigned char)value;
	p[1] = (unsigned char)(value >> 8);
	p[2] = (unsigned char)(value >> 16);
	p[3] = (unsigned char)(value >> 24);
}

static void rh_put_u64(unsigned char *p, uint64_t value)
{
	unsigned int i;

	for (i = 0; i < 8; i++)
		p[i] = (unsigned char)(value >> (8U * i));
}

static int rh_all_zero(const unsigned char *data, size_t length)
{
	size_t i;

	for (i = 0; i < length; i++)
		if (data[i])
			return 0;
	return 1;
}

static int rh_hex_value(unsigned char ch)
{
	if (ch >= '0' && ch <= '9')
		return ch - '0';
	if (ch >= 'a' && ch <= 'f')
		return ch - 'a' + 10;
	if (ch >= 'A' && ch <= 'F')
		return ch - 'A' + 10;
	return -1;
}

int rh_uuid_parse(const char *text, unsigned char output[16])
{
	static const unsigned int hyphens[] = { 8, 13, 18, 23 };
	unsigned int source = 0, target = 0, h = 0;

	if (!text || strlen(text) != 36 || !output)
		return -1;
	while (source < 36) {
		int high, low;
		if (h < sizeof(hyphens) / sizeof(hyphens[0]) &&
			source == hyphens[h]) {
			if (text[source++] != '-')
				return -1;
			h++;
			continue;
		}
		high = rh_hex_value((unsigned char)text[source++]);
		low = rh_hex_value((unsigned char)text[source++]);
		if (high < 0 || low < 0 || target >= 16)
			return -1;
		output[target++] = (unsigned char)((high << 4) | low);
	}
	return target == 16 && !rh_all_zero(output, 16) ? 0 : -1;
}

void rh_uuid_format(const unsigned char input[16], char output[37])
{
	static const char hex[] = "0123456789abcdef";
	unsigned int source, target = 0;

	for (source = 0; source < 16; source++) {
		if (source == 4 || source == 6 || source == 8 || source == 10)
			output[target++] = '-';
		output[target++] = hex[input[source] >> 4];
		output[target++] = hex[input[source] & 15];
	}
	output[target] = 0;
}

static int rh_wal_stream_read(const struct rh_wal *wal, uint64_t offset,
		size_t length, void *buffer)
{
	unsigned char *out = buffer;
	size_t i;

	if (!wal || !buffer || offset > wal->data_size ||
		length > wal->data_size - offset) {
		errno = EINVAL;
		return -1;
	}
	for (i = 0; length && i < wal->run_count; i++) {
		const struct rh_wal_run *run = &wal->runs[i];
		uint64_t run_end = run->stream_offset + run->length;
		size_t take;
		if (offset >= run_end)
			continue;
		if (offset < run->stream_offset) {
			errno = EIO;
			return -1;
		}
		take = (size_t)(run_end - offset);
		if (take > length)
			take = length;
		if (rh_writer_read(wal->writer,
			run->device_offset + offset - run->stream_offset,
			take, out))
			return -1;
		out += take;
		offset += take;
		length -= take;
	}
	if (length) {
		errno = EIO;
		return -1;
	}
	return 0;
}

static int rh_wal_stream_write(struct rh_wal *wal, uint64_t offset,
		size_t length, const void *buffer)
{
	const unsigned char *input = buffer;
	size_t i;

	if (!wal || !buffer || wal->writer->write_fd < 0 ||
		offset > wal->data_size || length > wal->data_size - offset) {
		errno = EINVAL;
		return -1;
	}
	for (i = 0; length && i < wal->run_count; i++) {
		const struct rh_wal_run *run = &wal->runs[i];
		uint64_t run_end = run->stream_offset + run->length;
		size_t take, done = 0;
		uint64_t physical;
		if (offset >= run_end)
			continue;
		if (offset < run->stream_offset) {
			errno = EIO;
			return -1;
		}
		take = (size_t)(run_end - offset);
		if (take > length)
			take = length;
		physical = run->device_offset + offset - run->stream_offset;
		while (done < take) {
			ssize_t written = rh_writer_raw_pwrite(wal->writer,
				input + done, take - done, physical + done);
			if (written < 0) {
				if (errno == EINTR)
					continue;
				return -1;
			}
			if (!written) {
				errno = EIO;
				return -1;
			}
			done += (size_t)written;
		}
		input += take;
		offset += take;
		length -= take;
	}
	if (length) {
		errno = EIO;
		return -1;
	}
	return 0;
}

static int rh_wal_trace_reserve(struct rh_wal *wal)
{
	struct rh_wal_trace_action *grown;
	size_t capacity;

	if (wal->trace_count < wal->trace_capacity)
		return 0;
	capacity = wal->trace_capacity ? wal->trace_capacity * 2U : 64U;
	if (capacity < wal->trace_count + 1U ||
			capacity > SIZE_MAX / sizeof(*grown)) {
		errno = EOVERFLOW;
		return -1;
	}
	grown = realloc(wal->trace_actions, capacity * sizeof(*grown));
	if (!grown)
		return -1;
	wal->trace_actions = grown;
	wal->trace_capacity = capacity;
	return 0;
}

static int rh_wal_traced_write(struct rh_wal *wal,
		enum rh_wal_trace_kind kind, uint64_t offset, size_t length,
		int slot, enum rh_wal_state from_state, enum rh_wal_state to_state,
		const void *data)
{
	struct rh_wal_trace_action *trace;
	unsigned char *before = NULL, *after = NULL;
	size_t first_boundary;
	int result = -1;

	if (!wal || !data || !length || rh_wal_trace_reserve(wal))
		return -1;
	before = malloc(length);
	after = malloc(length);
	if (!before || !after)
		goto out;
	if (rh_wal_stream_read(wal, offset, length, before))
		goto out;
	first_boundary = wal->writer->write_boundaries;
	if (rh_wal_stream_write(wal, offset, length, data) ||
			rh_writer_raw_sync(wal->writer) ||
			rh_wal_stream_read(wal, offset, length, after) ||
			memcmp(after, data, length)) {
		if (!errno)
			errno = EIO;
		goto out;
	}
	trace = &wal->trace_actions[wal->trace_count];
	memset(trace, 0, sizeof(*trace));
	trace->kind = kind;
	trace->extent_offset = offset;
	trace->length = length;
	trace->slot = slot;
	trace->from_state = from_state;
	trace->to_state = to_state;
	memcpy(trace->transaction_uuid, wal->transaction_uuid, 16);
	rh_sha256(before, length, trace->before_hash);
	rh_sha256(after, length, trace->after_hash);
	trace->sync_ordinal = wal->writer->sync_count;
	trace->write_boundaries = wal->writer->write_boundaries - first_boundary;
	/*
	 * Undo payloads and descriptors are transaction data, not state
	 * transitions.  A newly bound transaction may legitimately reuse WAL slots
	 * whose stale bytes already equal the new payload/descriptor.  The physical
	 * write, sync and readback remain mandatory; byte inequality adds no
	 * durability evidence.  State, reconstruction and target-restore writes
	 * must still change bytes.
	 */
	if (!trace->write_boundaries ||
			(kind != RH_WAL_TRACE_UNDO_PAYLOAD &&
			 kind != RH_WAL_TRACE_DESCRIPTOR &&
			 !memcmp(trace->before_hash, trace->after_hash, 32))) {
		errno = EIO;
		goto out;
	}
	wal->trace_count++;
	result = 0;
out:
	free(after);
	free(before);
	return result;
}

static int rh_wal_trace_completed_target_write(struct rh_wal *wal,
		uint64_t offset, size_t length, const void *before, const void *after,
		size_t first_boundary)
{
	struct rh_wal_trace_action *trace;

	if (!wal || !before || !after || !length || rh_wal_trace_reserve(wal))
		return -1;
	trace = &wal->trace_actions[wal->trace_count];
	memset(trace, 0, sizeof(*trace));
	trace->kind = RH_WAL_TRACE_ROLLBACK_RESTORE;
	trace->extent_offset = offset;
	trace->length = length;
	trace->slot = -1;
	trace->from_state = RH_WAL_ROLLBACK;
	trace->to_state = RH_WAL_ROLLBACK;
	memcpy(trace->transaction_uuid, wal->transaction_uuid, 16U);
	rh_sha256(before, length, trace->before_hash);
	rh_sha256(after, length, trace->after_hash);
	trace->sync_ordinal = wal->writer->sync_count;
	trace->write_boundaries = wal->writer->write_boundaries - first_boundary;
	if (!trace->write_boundaries ||
			!memcmp(trace->before_hash, trace->after_hash, 32U)) {
		errno = EIO;
		return -1;
	}
	wal->trace_count++;
	return 0;
}

size_t rh_wal_trace_action_count(const struct rh_wal *wal)
{
	return wal ? wal->trace_count : 0;
}

int rh_wal_trace_action_at(const struct rh_wal *wal, size_t ordinal,
		struct rh_wal_trace_action *action)
{
	if (!wal || !action || ordinal >= wal->trace_count) {
		errno = EINVAL;
		return -1;
	}
	*action = wal->trace_actions[ordinal];
	return 0;
}

static int rh_run_overlap(uint64_t first, uint64_t first_length,
		uint64_t second, uint64_t second_length)
{
	if (!first_length || !second_length ||
		first_length > UINT64_MAX - first ||
		second_length > UINT64_MAX - second)
		return 1;
	return first < second + second_length && second < first + first_length;
}

static int rh_wal_range_compare(const void *left_pointer,
		const void *right_pointer)
{
	const struct rh_free_slot_range *left = left_pointer;
	const struct rh_free_slot_range *right = right_pointer;

	if (left->offset != right->offset)
		return left->offset < right->offset ? -1 : 1;
	if (left->length != right->length)
		return left->length < right->length ? -1 : 1;
	return 0;
}

static int rh_wal_run_device_compare(const void *left_pointer,
		const void *right_pointer)
{
	const struct rh_wal_run *left = left_pointer;
	const struct rh_wal_run *right = right_pointer;

	if (left->device_offset != right->device_offset)
		return left->device_offset < right->device_offset ? -1 : 1;
	if (left->length != right->length)
		return left->length < right->length ? -1 : 1;
	if (left->stream_offset != right->stream_offset)
		return left->stream_offset < right->stream_offset ? -1 : 1;
	return 0;
}

static int rh_wal_hash_u16(struct rh_hash_stream *hash, uint16_t value)
{
	unsigned char encoded[2] = {
		(unsigned char)value, (unsigned char)(value >> 8)
	};

	return rh_hash_stream_update(hash, encoded, sizeof(encoded));
}

static int rh_wal_hash_u32(struct rh_hash_stream *hash, uint32_t value)
{
	unsigned char encoded[4];
	unsigned int i;

	for (i = 0; i < 4U; i++)
		encoded[i] = (unsigned char)(value >> (8U * i));
	return rh_hash_stream_update(hash, encoded, sizeof(encoded));
}

static int rh_wal_hash_u64(struct rh_hash_stream *hash, uint64_t value)
{
	unsigned char encoded[8];
	unsigned int i;

	for (i = 0; i < 8U; i++)
		encoded[i] = (unsigned char)(value >> (8U * i));
	return rh_hash_stream_update(hash, encoded, sizeof(encoded));
}

static int rh_wal_create_free_slot_exclusion_seal_common(
		const struct rh_wal *wal, const struct rh_writer *writer,
		int preimage_mode,
		uint64_t correlation_generation,
		struct rh_free_slot_component_seal **output)
{
	struct rh_free_slot_range *excluded = NULL;
	struct rh_free_slot_range *allowed = NULL;
	struct rh_wal_run *runs = NULL;
	struct rh_hash_stream hash;
	unsigned char source_hash[32];
	char journal_uuid[37];
	uint64_t expected_stream = 0;
	uint64_t backup_offset;
	size_t i, j;
	int base_seen = 0, backup_seen = 0;
	int result = -1;

	if (output)
		*output = NULL;
	if (!output || !wal || !writer || !wal->observation ||
			!correlation_generation || writer->read_fd < 0 ||
			writer->write_fd >= 0 || (!preimage_mode && writer->operation_count) ||
			writer->planned_bytes || writer->backend || writer->backend_opaque ||
			writer->commit_started || writer->commit_completed ||
			wal->sector_size != 512U ||
			wal->sector_size > writer->device_size ||
			!wal->volume_serial || !wal->journal_record ||
			!wal->journal_sequence || !wal->run_count || !wal->runs ||
			wal->run_count > wal->run_capacity || wal->data_size != RH_WAL_SIZE ||
			!wal->journal_record_device_length ||
			wal->journal_record_device_length != 1024U ||
			wal->journal_record_device_offset > writer->device_size ||
			wal->journal_record_device_length > writer->device_size -
				wal->journal_record_device_offset ||
			writer->excluded_count > writer->excluded_capacity ||
			writer->raw_wal_allowed_count >
				writer->raw_wal_allowed_capacity ||
			writer->excluded_count != wal->run_count + 2U ||
			!writer->excluded ||
			writer->raw_wal_allowed_count != wal->run_count ||
			!writer->raw_wal_allowed ||
			!wal->observation->checked || wal->observation->present != 1 ||
			wal->observation->valid != 1 ||
			!wal->observation->fast_path_trusted ||
			!wal->observation->write_safe ||
			!wal->observation->ownership_census_complete ||
			wal->observation->unreadable_record_count ||
			wal->observation->definite_duplicate_count ||
			wal->observation->volume_serial != wal->volume_serial ||
			wal->observation->max_entry_count != RH_WAL_MAX_ENTRIES) {
		errno = EPERM;
		return -1;
	}
	rh_uuid_format(wal->journal_uuid, journal_uuid);
	if (strcmp(journal_uuid, wal->observation->journal_uuid)) {
		errno = EPERM;
		return -1;
	}
	if (writer->excluded_count > SIZE_MAX / sizeof(*excluded) ||
			wal->run_count > SIZE_MAX / sizeof(*allowed) ||
			wal->run_count > SIZE_MAX / sizeof(*runs)) {
		errno = EOVERFLOW;
		return -1;
	}
	excluded = malloc(writer->excluded_count * sizeof(*excluded));
	allowed = malloc(wal->run_count * sizeof(*allowed));
	runs = malloc(wal->run_count * sizeof(*runs));
	if (!excluded || !allowed || !runs)
		goto out;
	for (i = 0; i < writer->excluded_count; i++) {
		excluded[i].offset = writer->excluded[i].offset;
		excluded[i].length = writer->excluded[i].length;
		if (!excluded[i].length ||
				excluded[i].offset > writer->device_size ||
				excluded[i].length > writer->device_size -
					excluded[i].offset) {
			errno = EIO;
			goto out;
		}
	}
	for (i = 0; i < wal->run_count; i++) {
		allowed[i].offset = writer->raw_wal_allowed[i].offset;
		allowed[i].length = writer->raw_wal_allowed[i].length;
		runs[i] = wal->runs[i];
		if (!allowed[i].length || allowed[i].offset > writer->device_size ||
				allowed[i].length > writer->device_size -
					allowed[i].offset || !runs[i].length ||
				runs[i].device_offset > writer->device_size ||
				runs[i].length > writer->device_size -
					runs[i].device_offset) {
			errno = EIO;
			goto out;
		}
		if (wal->runs[i].stream_offset != expected_stream ||
				wal->runs[i].length > UINT64_MAX - expected_stream) {
			errno = EIO;
			goto out;
		}
		expected_stream += wal->runs[i].length;
	}
	if (expected_stream != wal->data_size) {
		errno = EIO;
		goto out;
	}
	qsort(excluded, writer->excluded_count, sizeof(*excluded),
		rh_wal_range_compare);
	qsort(allowed, wal->run_count, sizeof(*allowed), rh_wal_range_compare);
	qsort(runs, wal->run_count, sizeof(*runs), rh_wal_run_device_compare);
	backup_offset = writer->device_size - wal->sector_size;
	for (i = 0; i < writer->excluded_count; i++) {
		if (i && rh_run_overlap(excluded[i - 1U].offset,
				excluded[i - 1U].length, excluded[i].offset,
				excluded[i].length)) {
			errno = EIO;
			goto out;
		}
		if (excluded[i].offset == wal->journal_record_device_offset &&
				excluded[i].length == wal->journal_record_device_length)
			base_seen++;
		if (excluded[i].offset == backup_offset &&
				excluded[i].length == wal->sector_size)
			backup_seen++;
	}
	if (base_seen != 1 || backup_seen != 1) {
		errno = EIO;
		goto out;
	}
	for (i = 0; i < wal->run_count; i++) {
		int excluded_match = 0;

		if (i && (rh_run_overlap(allowed[i - 1U].offset,
				allowed[i - 1U].length, allowed[i].offset,
				allowed[i].length) || rh_run_overlap(runs[i - 1U].device_offset,
				runs[i - 1U].length, runs[i].device_offset, runs[i].length))) {
			errno = EIO;
			goto out;
		}
		if (allowed[i].offset != runs[i].device_offset ||
				allowed[i].length != runs[i].length) {
			errno = EIO;
			goto out;
		}
		for (j = 0; j < writer->excluded_count; j++)
			if (excluded[j].offset == allowed[i].offset &&
					excluded[j].length == allowed[i].length) {
				excluded_match = 1;
				break;
			}
		if (!excluded_match) {
			errno = EIO;
			goto out;
		}
	}
	rh_hash_stream_init(&hash);
	if (rh_hash_stream_update(&hash, "RHWEX1\0\0", 8U) ||
			rh_wal_hash_u32(&hash, 1U) ||
			rh_wal_hash_u64(&hash, writer->device_size) ||
			rh_wal_hash_u32(&hash, wal->sector_size) ||
			rh_wal_hash_u64(&hash, wal->volume_serial) ||
			rh_wal_hash_u64(&hash, wal->journal_record) ||
			rh_wal_hash_u16(&hash, wal->journal_sequence) ||
			rh_hash_stream_update(&hash, wal->journal_uuid, 16U) ||
			rh_wal_hash_u64(&hash, wal->journal_record_device_offset) ||
			rh_wal_hash_u64(&hash, wal->journal_record_device_length) ||
			rh_wal_hash_u64(&hash, wal->data_size) ||
			rh_wal_hash_u64(&hash, wal->run_count) ||
			rh_wal_hash_u64(&hash, writer->excluded_count) ||
			rh_wal_hash_u64(&hash, writer->raw_wal_allowed_count))
		goto out;
	for (i = 0; i < wal->run_count; i++)
		if (rh_wal_hash_u64(&hash, runs[i].stream_offset) ||
				rh_wal_hash_u64(&hash, runs[i].device_offset) ||
				rh_wal_hash_u64(&hash, runs[i].length))
			goto out;
	for (i = 0; i < writer->excluded_count; i++)
		if (rh_wal_hash_u64(&hash, excluded[i].offset) ||
				rh_wal_hash_u64(&hash, excluded[i].length))
			goto out;
	for (i = 0; i < wal->run_count; i++)
		if (rh_wal_hash_u64(&hash, allowed[i].offset) ||
				rh_wal_hash_u64(&hash, allowed[i].length))
			goto out;
	if (rh_hash_stream_final(&hash, source_hash) ||
			rh_free_slot_friend_wal_exclusions_seal(correlation_generation,
				writer->excluded_count, writer->excluded_count,
				source_hash, excluded, writer->excluded_count, allowed,
				wal->run_count, output))
		goto out;
	result = 0;
out:
	free(runs);
	free(allowed);
	free(excluded);
	return result;
}

int rh_wal_create_free_slot_exclusion_seal(const struct rh_wal *wal,
		uint64_t correlation_generation,
		struct rh_free_slot_component_seal **output)
{
	return rh_wal_create_free_slot_exclusion_seal_common(wal,
		wal ? wal->writer : NULL, 0, correlation_generation, output);
}

static int rh_wal_overlaps_attr(ntfs_attr *attribute,
		const struct rh_wal *wal)
{
	runlist_element *run;
	size_t i;
	uint64_t cluster_size;

	if (!attribute || !NAttrNonResident(attribute))
		return 0;
	if (ntfs_attr_map_whole_runlist(attribute))
		return -1;
	cluster_size = attribute->ni->vol->cluster_size;
	for (run = attribute->rl; run && run->length; run++) {
		uint64_t offset, length;
		if (run->lcn < 0 || run->length <= 0 ||
			(uint64_t)run->lcn > UINT64_MAX / cluster_size ||
			(uint64_t)run->length > UINT64_MAX / cluster_size)
			return -1;
		offset = (uint64_t)run->lcn * cluster_size;
		length = (uint64_t)run->length * cluster_size;
		for (i = 0; i < wal->run_count; i++)
			if (rh_run_overlap(offset, length, wal->runs[i].device_offset,
					wal->runs[i].length))
				return 1;
	}
	return 0;
}

static int rh_wal_validate_system_nonoverlap(ntfs_volume *volume,
		const struct rh_wal *wal)
{
	static const uint64_t records[] = { FILE_LogFile, FILE_Boot };
	ntfs_inode *inode = NULL;
	ntfs_attr *attribute = NULL;
	size_t i;
	int result;

	result = rh_wal_overlaps_attr(volume->mft_na, wal);
	if (result)
		return result;
	result = rh_wal_overlaps_attr(volume->mftmirr_na, wal);
	if (result)
		return result;
	result = rh_wal_overlaps_attr(volume->lcnbmp_na, wal);
	if (result)
		return result;
	for (i = 0; i < sizeof(records) / sizeof(records[0]); i++) {
		inode = ntfs_inode_open(volume, records[i]);
		if (!inode)
			return -1;
		attribute = ntfs_attr_open(inode, AT_DATA, AT_UNNAMED, 0);
		if (!attribute) {
			ntfs_inode_close(inode);
			return -1;
		}
		result = rh_wal_overlaps_attr(attribute, wal);
		ntfs_attr_close(attribute);
		attribute = NULL;
		if (ntfs_inode_close(inode))
			return -1;
		inode = NULL;
		if (result)
			return result;
	}
	return 0;
}

static int rh_wal_filename_under_parent(const ATTR_RECORD *attribute,
		uint64_t parent_record, uint16_t *parent_sequence,
		uint32_t *file_flags)
{
	const unsigned char *raw = (const unsigned char *)attribute;
	uint32_t length = le32_to_cpu(attribute->length);
	uint32_t value_length;
	uint16_t value_offset;
	const unsigned char *value;
	uint64_t parent;
	uint8_t name_length;
	static const char name[] = "$RootHealth";
	size_t i;

	if (attribute->non_resident)
		return 0;
	value_length = le32_to_cpu(attribute->value_length);
	value_offset = le16_to_cpu(attribute->value_offset);
	if (value_offset < 24 || value_offset > length ||
		value_length > length - value_offset || value_length < 66)
		return -1;
	value = raw + value_offset;
	parent = rh_get_u64(value);
	name_length = value[64];
	if (name_length != sizeof(name) - 1 ||
		66U + 2U * name_length != value_length)
		return 0;
	for (i = 0; i < name_length; i++)
		if (value[66 + 2 * i] != (unsigned char)name[i] ||
			value[67 + 2 * i])
			return 0;
	if ((parent & 0x0000ffffffffffffULL) != parent_record)
		return 0;
	*parent_sequence = (uint16_t)(parent >> 48);
	*file_flags = rh_get_u32(value + 56);
	return 1;
}

static int rh_wal_mft_bitmap_observe(ntfs_volume *volume,
		uint64_t record_number, int *allocated);

/*
 * Windows may extend $MFT/$DATA by zero-initializing a tail of records while
 * leaving their $MFT bitmap bits clear.  Such a slot has no FILE record and
 * therefore cannot contain a live competing $RootHealth name.  libntfs
 * correctly rejects it as an MST-protected FILE record, so recognize only
 * this canonical, bitmap-proven free representation here.  Any nonzero or
 * bitmap-allocated unreadable slot remains a fail-closed condition.
 */
static int rh_wal_zero_initialized_free_record(ntfs_volume *volume,
		uint64_t record_number, unsigned char *record)
{
	uint64_t offset;
	int allocated = -1;

	if (!volume || !volume->mft_na || !record ||
			record_number > INT64_MAX / volume->mft_record_size)
		return 0;
	offset = record_number * (uint64_t)volume->mft_record_size;
	if (ntfs_attr_pread(volume->mft_na, (s64)offset,
			volume->mft_record_size, record) !=
			(s64)volume->mft_record_size ||
			rh_wal_mft_bitmap_observe(volume, record_number, &allocated))
		return 0;
	return !allocated && rh_all_zero(record, volume->mft_record_size);
}

/*
 * Prove that the attested base record is the only live raw-MFT record with a
 * $RootHealth FILE_NAME under $Extend.  Index lookup is deliberately not an
 * authority here: this scan has to remain usable while recovering an
 * interrupted transaction whose namespace indexes may not yet be trusted.
 */
static int rh_wal_scan_unique_record(ntfs_volume *volume,
		uint16_t extend_sequence, uint64_t expected_record,
		uint16_t expected_sequence, uint64_t *unreadable_records,
		uint64_t *definite_duplicates)
{
	unsigned char *record_buffer = NULL;
	uint64_t record_count, record_number, matches = 0;
	int expected_seen = 0;
	int result = -1;

	if (!volume || !volume->mft_na ||
		!volume->mft_record_size || !unreadable_records ||
		!definite_duplicates ||
		volume->mft_na->initialized_size <= 0 ||
		(uint64_t)volume->mft_na->initialized_size %
			volume->mft_record_size)
		return -1;
	*unreadable_records = 0;
	*definite_duplicates = 0;
	record_count = (uint64_t)volume->mft_na->initialized_size /
		volume->mft_record_size;
	if (!record_count || expected_record >= record_count ||
			record_count > UINT64_MAX - 7)
		return -1;
	record_buffer = malloc(volume->mft_record_size);
	if (!record_buffer)
		goto out;
	for (record_number = 0; record_number < record_count; record_number++) {
		MFT_RECORD *record = (MFT_RECORD *)record_buffer;
		uint32_t used, offset;
		unsigned int record_matches = 0;
		uint16_t record_parent_sequence = 0;
		int readable = 1;

		if (ntfs_mft_record_read(volume, (MFT_REF)record_number, record) ||
			!ntfs_is_file_record(record->magic) ||
			le32_to_cpu(record->bytes_allocated) !=
				volume->mft_record_size) {
			readable = 0;
		} else if (!(le16_to_cpu(record->flags) &
				le16_to_cpu(MFT_RECORD_IN_USE))) {
			continue;
		} else {
			used = le32_to_cpu(record->bytes_in_use);
			offset = le16_to_cpu(record->attrs_offset);
			if (used < sizeof(*record) || used > volume->mft_record_size ||
				offset < sizeof(*record) || (offset & 7) ||
				offset > used - sizeof(ATTR_TYPES)) {
				readable = 0;
			} else {
				for (;;) {
					ATTR_RECORD *attribute;
					uint32_t length;
					uint16_t parent_sequence = 0;
					uint32_t ignored_flags = 0;
					int match;

					if (offset > used - sizeof(ATTR_TYPES)) {
						readable = 0;
						break;
					}
					attribute = (ATTR_RECORD *)((unsigned char *)record + offset);
					if (attribute->type == AT_END)
						break;
					if (offset > used - 24) {
						readable = 0;
						break;
					}
					length = le32_to_cpu(attribute->length);
					if (length < 24 || (length & 7) ||
						length > used - offset) {
						readable = 0;
						break;
					}
					if (attribute->type == AT_FILE_NAME) {
						match = rh_wal_filename_under_parent(attribute,
							FILE_Extend, &parent_sequence,
							&ignored_flags);
						if (match < 0) {
							readable = 0;
							break;
						}
						if (match) {
							record_matches++;
							record_parent_sequence = parent_sequence;
						}
					}
					offset += length;
				}
			}
		}
		if (!readable && rh_wal_zero_initialized_free_record(volume,
				record_number, record_buffer))
			continue;
		if (!readable) {
			if (record_number == expected_record)
				goto out;
			if (record_matches) {
				(*definite_duplicates)++;
				goto out;
			}
			(*unreadable_records)++;
			continue;
		}
		if (record_matches > 1) {
			(*definite_duplicates)++;
			goto out;
		}
		if (record_matches == 1) {
			matches++;
			if (record_number == expected_record &&
				le16_to_cpu(record->sequence_number) == expected_sequence &&
				record_parent_sequence == extend_sequence)
				expected_seen = 1;
			else {
				(*definite_duplicates)++;
				goto out;
			}
			if (matches > 1)
				goto out;
		}
	}
	if (!expected_seen || matches != 1)
		goto out;
	result = 0;
out:
	free(record_buffer);
	return result;
}

static int rh_wal_validate_record_metadata(const MFT_RECORD *mft,
		uint16_t extend_sequence)
{
	static const ATTR_TYPES expected_types[] = {
		AT_STANDARD_INFORMATION, AT_FILE_NAME, AT_SECURITY_DESCRIPTOR, AT_DATA
	};
	unsigned char *record = (unsigned char *)mft;
	uint32_t used = le32_to_cpu(mft->bytes_in_use);
	uint32_t offset = le16_to_cpu(mft->attrs_offset);
	unsigned int filename_count = 0, standard_count = 0, data_count = 0;
	unsigned int attribute_ordinal = 0;
	uint32_t filename_flags = 0, standard_flags = 0;

	if (!(le16_to_cpu(mft->flags) & 1) ||
		(le16_to_cpu(mft->flags) & 2) ||
		le64_to_cpu(mft->base_mft_record) ||
		le16_to_cpu(mft->link_count) != 1)
		return -1;
	while (offset + sizeof(ATTR_TYPES) <= used) {
		ATTR_RECORD *attribute = (ATTR_RECORD *)(record + offset);
		uint32_t length, value_length;
		uint16_t value_offset;
		int match;
		if (attribute->type == AT_END)
			break;
		if (offset + 24 > used)
			return -1;
		length = le32_to_cpu(attribute->length);
		if (length < 24 || (length & 7) || length > used - offset)
			return -1;
		if (attribute_ordinal >= sizeof(expected_types) /
				sizeof(expected_types[0]) ||
			attribute->type != expected_types[attribute_ordinal++] ||
			attribute->name_length)
			return -1;
		if (attribute->type == AT_FILE_NAME) {
			uint16_t parent_sequence = 0;
			match = rh_wal_filename_under_parent(attribute, FILE_Extend,
				&parent_sequence, &filename_flags);
			if (match < 0)
				return -1;
			if (match && parent_sequence != extend_sequence)
				return -1;
			filename_count += (unsigned int)match;
		}
		if (attribute->type == AT_STANDARD_INFORMATION) {
			if (attribute->non_resident)
				return -1;
			value_length = le32_to_cpu(attribute->value_length);
			value_offset = le16_to_cpu(attribute->value_offset);
			if (value_length < 36 || value_offset < 24 ||
				value_offset > length || value_length > length - value_offset)
				return -1;
			standard_flags = rh_get_u32((unsigned char *)attribute +
				value_offset + 32);
			standard_count++;
		}
		if (attribute->type == AT_SECURITY_DESCRIPTOR &&
				attribute->non_resident)
			return -1;
		if (attribute->type == AT_DATA) {
			if (!attribute->non_resident)
				return -1;
			data_count++;
		}
		offset += length;
	}
	if (offset + sizeof(ATTR_TYPES) > used ||
		((ATTR_RECORD *)(record + offset))->type != AT_END ||
		!rh_all_zero(record + offset + sizeof(ATTR_TYPES),
			used - offset - sizeof(ATTR_TYPES)) ||
		attribute_ordinal != sizeof(expected_types) /
			sizeof(expected_types[0]) ||
		filename_count != 1 || standard_count != 1 || data_count != 1 ||
		standard_flags != RH_WAL_JOURNAL_FILE_FLAGS ||
		filename_flags != RH_WAL_JOURNAL_FILE_FLAGS)
		return -1;
	return 0;
}

static int rh_wal_validate_inode_metadata(ntfs_inode *inode,
		uint16_t extend_sequence)
{
	if (!inode || NInoAttrList(inode))
		return -1;
	return rh_wal_validate_record_metadata(inode->mrec, extend_sequence);
}

struct rh_wal_i30_count {
	uint64_t expected_record;
	uint16_t expected_sequence;
	unsigned int matches;
	int conflict;
};

static int rh_wal_i30_filldir(void *opaque, const ntfschar *name,
		const int name_len, const int name_type __attribute__((unused)),
		const s64 pos __attribute__((unused)), const MFT_REF mref,
		const unsigned dt_type __attribute__((unused)))
{
	static const uint16_t expected[] = {
		'$', 'R', 'o', 'o', 't', 'H', 'e', 'a', 'l', 't', 'h'
	};
	struct rh_wal_i30_count *count = opaque;
	size_t i;

	if (!count || !name || name_len != (int)(sizeof(expected) /
			sizeof(expected[0])))
		return 0;
	for (i = 0; i < sizeof(expected) / sizeof(expected[0]); i++)
		if (le16_to_cpu(name[i]) != expected[i])
			return 0;
	count->matches++;
	if (MREF(mref) != count->expected_record ||
			MSEQNO(mref) != count->expected_sequence)
		count->conflict = 1;
	return 0;
}

static int rh_wal_validate_cached_i30(ntfs_inode *extend,
		uint64_t expected_record, uint16_t expected_sequence,
		uint16_t extend_sequence)
{
	static const uint16_t expected_name[] = {
		'$', 'R', 'o', 'o', 't', 'H', 'e', 'a', 'l', 't', 'h'
	};
	ntfschar name[sizeof(expected_name) / sizeof(expected_name[0])];
	struct rh_wal_i30_count count;
	INDEX_ENTRY *entry = NULL;
	const FILE_NAME_ATTR *key;
	uint64_t indexed, parent;
	s64 position = 0;
	size_t i;
	int result = -1;

	if (!extend)
		return -1;
	memset(&count, 0, sizeof(count));
	count.expected_record = expected_record;
	count.expected_sequence = expected_sequence;
	for (i = 0; i < sizeof(expected_name) / sizeof(expected_name[0]); i++)
		name[i] = cpu_to_le16(expected_name[i]);
	if (ntfs_readdir(extend, &position, &count, rh_wal_i30_filldir) ||
			count.matches != 1U || count.conflict)
		return -1;
	entry = __ntfs_inode_lookup_by_name(extend, name,
		(int)(sizeof(name) / sizeof(name[0])));
	if (!entry || (le16_to_cpu(entry->ie_flags) &
			le16_to_cpu(INDEX_ENTRY_END)) || entry->reserved ||
			le16_to_cpu(entry->key_length) !=
			sizeof(FILE_NAME_ATTR) + sizeof(name))
		goto out;
	indexed = le64_to_cpu(entry->indexed_file);
	key = &entry->key.file_name;
	parent = le64_to_cpu(key->parent_directory);
	if (MREF(indexed) != expected_record ||
			MSEQNO(indexed) != expected_sequence ||
			MREF(parent) != FILE_Extend || MSEQNO(parent) != extend_sequence ||
			le32_to_cpu(key->file_attributes) != RH_WAL_JOURNAL_FILE_FLAGS ||
			key->file_name_length != sizeof(name) / sizeof(name[0]))
		goto out;
	for (i = 0; i < sizeof(name) / sizeof(name[0]); i++)
		if (key->file_name[i] != name[i])
			goto out;
	result = 0;
out:
	free(entry);
	return result;
}

static int rh_wal_cluster_bitmap_observe(ntfs_volume *volume,
		const struct rh_wal *wal, uint64_t *false_free_count)
{
	size_t i;

	if (!false_free_count)
		return -1;
	*false_free_count = 0;
	for (i = 0; i < wal->run_count; i++) {
		uint64_t first_cluster = wal->runs[i].device_offset /
			volume->cluster_size;
		uint64_t clusters = wal->runs[i].length / volume->cluster_size;
		uint64_t last_cluster, first_byte, last_byte, byte_count;
		size_t bytes;
		s64 bitmap_bytes;
		unsigned char *bitmap;
		uint64_t cluster;
		if (!clusters || first_cluster >= (uint64_t)volume->nr_clusters ||
			clusters > (uint64_t)volume->nr_clusters - first_cluster)
			return -1;
		last_cluster = first_cluster + clusters;
		first_byte = first_cluster >> 3;
		last_byte = (last_cluster >> 3) + !!(last_cluster & 7);
		byte_count = last_byte - first_byte;
		if (!byte_count || byte_count > SIZE_MAX || byte_count > INT64_MAX)
			return -1;
		bytes = (size_t)byte_count;
		bitmap_bytes = (s64)byte_count;
		bitmap = malloc(bytes);
		if (!bitmap)
			return -1;
		if (ntfs_attr_pread(volume->lcnbmp_na, (s64)first_byte, bitmap_bytes,
				bitmap) != bitmap_bytes) {
			free(bitmap);
			return -1;
		}
		for (cluster = first_cluster; cluster < last_cluster; cluster++) {
			uint64_t bit = cluster - (first_byte << 3);
			if (!(bitmap[bit >> 3] & (1U << (bit & 7))))
				(*false_free_count)++;
		}
		free(bitmap);
	}
	return 0;
}

static int rh_wal_mft_bitmap_observe(ntfs_volume *volume,
		uint64_t record_number, int *allocated)
{
	unsigned char byte;
	uint64_t byte_offset = record_number >> 3;

	if (!volume || !volume->mftbmp_na || !allocated ||
			byte_offset > INT64_MAX || volume->mftbmp_na->data_size <= 0 ||
			byte_offset >= (uint64_t)volume->mftbmp_na->data_size ||
			ntfs_attr_pread(volume->mftbmp_na, (s64)byte_offset, 1, &byte) != 1)
		return -1;
	*allocated = !!(byte & (unsigned char)(1U << (record_number & 7U)));
	return 0;
}

static int rh_wal_copy_runs(struct rh_wal *wal, ntfs_attr *data,
		ntfs_volume *volume)
{
	runlist_element *run;
	uint64_t expected_vcn = 0;

	if (!NAttrNonResident(data) || data->data_flags ||
		data->allocated_size != (s64)RH_WAL_SIZE ||
		data->data_size != (s64)RH_WAL_SIZE ||
		data->initialized_size != (s64)RH_WAL_SIZE ||
		ntfs_attr_map_whole_runlist(data))
		return -1;
	for (run = data->rl; run && run->length; run++) {
		struct rh_wal_run candidate;
		size_t i;
		if (run->vcn < 0 ||
			(uint64_t)run->vcn != expected_vcn || run->lcn < 0 ||
			run->length <= 0 || (uint64_t)run->lcn >=
				(uint64_t)volume->nr_clusters || (uint64_t)run->length >
				(uint64_t)volume->nr_clusters - (uint64_t)run->lcn ||
			(uint64_t)run->vcn > UINT64_MAX / volume->cluster_size ||
			(uint64_t)run->lcn > UINT64_MAX / volume->cluster_size ||
			(uint64_t)run->length > UINT64_MAX / volume->cluster_size ||
			(uint64_t)run->length > UINT64_MAX - expected_vcn) {
			errno = EIO;
			return -1;
		}
		candidate.stream_offset = (uint64_t)run->vcn * volume->cluster_size;
		candidate.device_offset = (uint64_t)run->lcn * volume->cluster_size;
		candidate.length = (uint64_t)run->length * volume->cluster_size;
		if (candidate.device_offset > wal->writer->device_size ||
			candidate.length > wal->writer->device_size -
				candidate.device_offset) {
			errno = EIO;
			return -1;
		}
		for (i = 0; i < wal->run_count; i++)
			if (rh_run_overlap(candidate.device_offset, candidate.length,
					wal->runs[i].device_offset, wal->runs[i].length)) {
				errno = EIO;
				return -1;
			}
		if (rh_wal_append_run(wal, &candidate))
			return -1;
		expected_vcn += (uint64_t)run->length;
	}
	if (expected_vcn > UINT64_MAX / volume->cluster_size) {
		errno = EIO;
		return -1;
	}
	wal->data_size = expected_vcn * volume->cluster_size;
	if (!wal->run_count || wal->data_size != RH_WAL_SIZE) {
		errno = EIO;
		return -1;
	}
	return 0;
}

static int rh_wal_exclude_base_record(struct rh_wal *wal,
		ntfs_volume *volume)
{
	uint64_t offset = wal->journal_record * volume->mft_record_size;
	uint64_t remaining = volume->mft_record_size;
	runlist_element *run;

	while (remaining) {
		uint64_t vcn = offset / volume->cluster_size;
		uint64_t within = offset % volume->cluster_size;
		uint64_t take, physical;
		run = ntfs_attr_find_vcn(volume->mft_na, (VCN)vcn);
		if (!run || run->lcn < 0 || (VCN)vcn < run->vcn ||
			(VCN)vcn >= run->vcn + run->length)
			return -1;
		take = volume->cluster_size - within;
		if (take > remaining)
			take = remaining;
		physical = ((uint64_t)run->lcn + vcn - (uint64_t)run->vcn) *
			volume->cluster_size + within;
		/* 1 KiB records are cluster-aligned within the exact 4 KiB profile. */
		if (wal->journal_record_device_length ||
				take != volume->mft_record_size ||
				rh_writer_exclude(wal->writer, physical, take))
			return -1;
		wal->journal_record_device_offset = physical;
		wal->journal_record_device_length = take;
		offset += take;
		remaining -= take;
	}
	return 0;
}

static int rh_wal_validate_backup_boot_nonoverlap(const struct rh_wal *wal)
{
	uint64_t backup_offset;
	size_t i;

	if (!wal || wal->writer->device_size < wal->sector_size)
		return -1;
	backup_offset = wal->writer->device_size - wal->sector_size;
	for (i = 0; i < wal->run_count; i++)
		if (rh_run_overlap(backup_offset, wal->sector_size,
				wal->runs[i].device_offset, wal->runs[i].length))
			return -1;
	return 0;
}

static ATTR_RECORD *rh_wal_raw_unnamed_data(MFT_RECORD *record)
{
	unsigned char *raw = (unsigned char *)record;
	uint32_t used, offset;
	ATTR_RECORD *found = NULL;

	if (!record)
		return NULL;
	used = le32_to_cpu(record->bytes_in_use);
	offset = le16_to_cpu(record->attrs_offset);
	if (used < sizeof(*record) || used > ROOTHEALTH_SUPPORTED_MFT_RECORD_SIZE ||
			offset < sizeof(*record) || (offset & 7U) ||
			offset > used - sizeof(ATTR_TYPES))
		return NULL;
	for (;;) {
		ATTR_RECORD *attribute;
		uint32_t length;

		if (offset > used - sizeof(ATTR_TYPES))
			return NULL;
		attribute = (ATTR_RECORD *)(raw + offset);
		if (attribute->type == AT_END)
			return found;
		if (offset > used - 24U)
			return NULL;
		length = le32_to_cpu(attribute->length);
		if (length < 24U || (length & 7U) || length > used - offset)
			return NULL;
		if (attribute->type == AT_DATA && !attribute->name_length) {
			if (found)
				return NULL;
			found = attribute;
		}
		offset += length;
	}
}

static int64_t rh_wal_raw_mapping_signed(const unsigned char *bytes,
		unsigned int count)
{
	uint64_t value = 0;
	unsigned int i;

	for (i = 0; i < count; ++i)
		value |= (uint64_t)bytes[i] << (8U * i);
	if (count < 8U && (bytes[count - 1U] & 0x80U))
		value |= UINT64_MAX << (8U * count);
	if (value <= INT64_MAX)
		return (int64_t)value;
	return -1 - (int64_t)(~value);
}

/*
 * Decode a base-record, unnamed, nonresident stream without mounting NTFS.
 * The decoder is deliberately narrower than libntfs: no sparse/compressed
 * runs, no attribute-list continuation, and one complete VCN-zero runlist.
 */
static int rh_wal_raw_decode_stream(struct rh_wal *wal,
		const ATTR_RECORD *attribute, uint64_t logical_offset,
		uint64_t logical_length, uint64_t *device_offset, int install_runs)
{
	const unsigned char *raw = (const unsigned char *)attribute;
	const unsigned char *cursor, *end;
	uint32_t length;
	uint16_t mapping_offset;
	uint64_t volume_clusters, vcn = 0, allocated, data, initialized;
	int64_t lcn = 0, highest;
	int found = 0, terminated = 0;
	size_t checkpoint;

	if (!wal || !attribute || !attribute->non_resident ||
			attribute->name_length || le16_to_cpu(attribute->flags) ||
			attribute->compression_unit ||
			sle64_to_cpu(attribute->lowest_vcn) != 0)
		return -1;
	length = le32_to_cpu(attribute->length);
	mapping_offset = le16_to_cpu(attribute->mapping_pairs_offset);
	highest = sle64_to_cpu(attribute->highest_vcn);
	allocated = (uint64_t)sle64_to_cpu(attribute->allocated_size);
	data = (uint64_t)sle64_to_cpu(attribute->data_size);
	initialized = (uint64_t)sle64_to_cpu(attribute->initialized_size);
	if (length < 64U || mapping_offset < 64U || mapping_offset >= length ||
			highest < 0 || (int64_t)allocated < 0 || (int64_t)data < 0 ||
			(int64_t)initialized < 0 || !allocated || !data ||
			initialized != data || data > allocated ||
			(allocated & (ROOTHEALTH_SUPPORTED_CLUSTER_SIZE - 1U)) ||
			logical_offset > data || logical_length > data - logical_offset)
		return -1;
	volume_clusters = wal->writer->device_size /
		ROOTHEALTH_SUPPORTED_CLUSTER_SIZE;
	cursor = raw + mapping_offset;
	end = raw + length;
	checkpoint = wal->run_count;
	while (cursor < end) {
		unsigned int length_bytes, offset_bytes;
		uint64_t run_length, run_start, run_bytes;
		int64_t delta, next_lcn;

		if (!*cursor) {
			terminated = 1;
			break;
		}
		length_bytes = *cursor & 0x0fU;
		offset_bytes = *cursor >> 4;
		cursor++;
		if (!length_bytes || length_bytes > 8U || !offset_bytes ||
				offset_bytes > 8U || (size_t)(end - cursor) <
				(size_t)length_bytes + offset_bytes)
			goto fail;
		run_length = 0;
		for (unsigned int i = 0; i < length_bytes; ++i)
			run_length |= (uint64_t)cursor[i] << (8U * i);
		cursor += length_bytes;
		delta = rh_wal_raw_mapping_signed(cursor, offset_bytes);
		cursor += offset_bytes;
		if (!run_length || run_length > UINT64_MAX - vcn ||
				(delta > 0 && lcn > INT64_MAX - delta) ||
				(delta < 0 && lcn < INT64_MIN - delta))
			goto fail;
		next_lcn = lcn + delta;
		if (next_lcn < 0 || (uint64_t)next_lcn >= volume_clusters ||
				run_length > volume_clusters - (uint64_t)next_lcn ||
				run_length > UINT64_MAX / ROOTHEALTH_SUPPORTED_CLUSTER_SIZE)
			goto fail;
		run_start = vcn * ROOTHEALTH_SUPPORTED_CLUSTER_SIZE;
		run_bytes = run_length * ROOTHEALTH_SUPPORTED_CLUSTER_SIZE;
		if (logical_length && logical_offset >= run_start &&
				logical_offset - run_start <= run_bytes &&
				logical_length <= run_bytes - (logical_offset - run_start)) {
			if (found || !device_offset)
				goto fail;
			*device_offset = (uint64_t)next_lcn *
				ROOTHEALTH_SUPPORTED_CLUSTER_SIZE + logical_offset - run_start;
			found = 1;
		}
		if (install_runs) {
			struct rh_wal_run run = {
				.stream_offset = run_start,
				.device_offset = (uint64_t)next_lcn *
					ROOTHEALTH_SUPPORTED_CLUSTER_SIZE,
				.length = run_bytes
			};
			size_t i;
			for (i = checkpoint; i < wal->run_count; ++i)
				if (rh_run_overlap(run.device_offset, run.length,
						wal->runs[i].device_offset, wal->runs[i].length))
					goto fail;
			if (rh_wal_append_run(wal, &run))
				goto fail;
		}
		vcn += run_length;
		lcn = next_lcn;
	}
	if (!terminated || vcn != (uint64_t)highest + 1U ||
			vcn > UINT64_MAX / ROOTHEALTH_SUPPORTED_CLUSTER_SIZE ||
			allocated != vcn * ROOTHEALTH_SUPPORTED_CLUSTER_SIZE ||
			(logical_length && !found))
		goto fail;
	if (install_runs) {
		if (allocated != RH_WAL_SIZE || data != RH_WAL_SIZE ||
				initialized != RH_WAL_SIZE)
			goto fail;
		wal->data_size = data;
	}
	return 0;
fail:
	if (install_runs) {
		wal->run_count = checkpoint;
		wal->data_size = 0;
	}
	return -1;
}

static int rh_wal_raw_read_mft_record(struct rh_wal *wal,
		const struct rh_boot_geometry *geometry, uint64_t record_number,
		unsigned char output[ROOTHEALTH_SUPPORTED_MFT_RECORD_SIZE],
		uint64_t *device_offset)
{
	unsigned char mft_raw[ROOTHEALTH_SUPPORTED_MFT_RECORD_SIZE];
	unsigned char *mft_fixed = NULL;
	ATTR_RECORD *mft_data;
	uint64_t mft_offset, record_offset;
	int status;

	if (!wal || !geometry || !output ||
			record_number > UINT64_MAX / geometry->mft_record_size)
		return -1;
	mft_offset = geometry->mft_lcn * geometry->cluster_size;
	if (mft_offset > wal->writer->device_size || sizeof(mft_raw) >
			wal->writer->device_size - mft_offset ||
			rh_writer_read(wal->writer, mft_offset, sizeof(mft_raw), mft_raw))
		return -1;
	status = roothealth_bootstrap_mft_record_structure(mft_raw,
		sizeof(mft_raw), FILE_MFT, geometry, &mft_fixed);
	if (status <= 0)
		return -1;
	mft_data = rh_wal_raw_unnamed_data((MFT_RECORD *)mft_fixed);
	record_offset = record_number * geometry->mft_record_size;
	status = !mft_data || rh_wal_raw_decode_stream(wal, mft_data,
		record_offset, geometry->mft_record_size, &mft_offset, 0) ||
		rh_writer_read(wal->writer, mft_offset, geometry->mft_record_size,
			output);
	free(mft_fixed);
	if (status || ntfs_mst_post_read_fixup((NTFS_RECORD *)output,
			geometry->mft_record_size))
		return -1;
	if (device_offset)
		*device_offset = mft_offset;
	return 0;
}

static int rh_wal_locate_raw_recovery(struct rh_wal *wal,
		const struct rh_boot_geometry *geometry, uint64_t expected_record,
		uint16_t expected_sequence)
{
	unsigned char extend_raw[ROOTHEALTH_SUPPORTED_MFT_RECORD_SIZE];
	unsigned char journal_raw[ROOTHEALTH_SUPPORTED_MFT_RECORD_SIZE];
	MFT_RECORD *extend = (MFT_RECORD *)extend_raw;
	MFT_RECORD *journal = (MFT_RECORD *)journal_raw;
	ATTR_RECORD *data;
	uint64_t journal_record_offset;
	uint16_t extend_sequence;
	size_t i;

	if (rh_wal_raw_read_mft_record(wal, geometry, FILE_Extend, extend_raw,
			NULL) ||
			rh_wal_raw_read_mft_record(wal, geometry, expected_record,
				journal_raw, &journal_record_offset))
		return RH_RESULT_UNSAFE;
	extend_sequence = le16_to_cpu(extend->sequence_number);
	if (extend->magic != magic_FILE ||
			!(le16_to_cpu(extend->flags) & le16_to_cpu(MFT_RECORD_IN_USE)) ||
			!(le16_to_cpu(extend->flags) & le16_to_cpu(MFT_RECORD_IS_DIRECTORY)) ||
			journal->magic != magic_FILE ||
			le32_to_cpu(journal->mft_record_number) != expected_record ||
			le16_to_cpu(journal->sequence_number) != expected_sequence ||
			rh_wal_validate_record_metadata(journal, extend_sequence))
		return RH_RESULT_UNSAFE;
	data = rh_wal_raw_unnamed_data(journal);
	if (!data || rh_wal_raw_decode_stream(wal, data, 0, 0, NULL, 1))
		return RH_RESULT_UNSAFE;
	if (journal_record_offset > wal->writer->device_size ||
			geometry->mft_record_size > wal->writer->device_size -
				journal_record_offset ||
			rh_writer_exclude(wal->writer, journal_record_offset,
				geometry->mft_record_size) ||
			rh_wal_validate_backup_boot_nonoverlap(wal))
		return RH_RESULT_UNSAFE;
	for (i = 0; i < wal->run_count; ++i)
		if (rh_writer_exclude(wal->writer, wal->runs[i].device_offset,
				wal->runs[i].length) ||
				rh_writer_allow_raw_wal(wal->writer,
					wal->runs[i].device_offset, wal->runs[i].length))
			return RH_RESULT_UNSAFE;
	if (rh_writer_exclude(wal->writer,
			wal->writer->device_size - wal->sector_size, wal->sector_size))
		return RH_RESULT_UNSAFE;
	wal->journal_record = expected_record;
	wal->journal_sequence = expected_sequence;
	wal->journal_record_device_offset = journal_record_offset;
	wal->journal_record_device_length = geometry->mft_record_size;
	wal->observation->checked = 1;
	wal->observation->present = 1;
	wal->observation->write_safe = 1;
	wal->raw_recovery_locator = 1;
	return RH_RESULT_OK;
}

static int rh_wal_validate_mounted_geometry(const struct rh_wal *wal,
		ntfs_volume *volume)
{
	unsigned char boot[ROOTHEALTH_SUPPORTED_SECTOR_SIZE];
	uint64_t sectors;

	if (!wal || !volume || !volume->dev ||
		ntfs_pread(volume->dev, 0, sizeof(boot), boot) !=
			(s64)sizeof(boot) ||
		memcmp(boot + 3, "NTFS    ", 8) || boot[510] != 0x55 ||
		boot[511] != 0xaa ||
		rh_get_u16(boot + 11) != ROOTHEALTH_SUPPORTED_SECTOR_SIZE ||
		boot[13] != ROOTHEALTH_SUPPORTED_CLUSTER_SIZE /
			ROOTHEALTH_SUPPORTED_SECTOR_SIZE ||
		rh_get_u64(boot + 72) != wal->volume_serial ||
		volume->sector_size != ROOTHEALTH_SUPPORTED_SECTOR_SIZE ||
		volume->cluster_size != ROOTHEALTH_SUPPORTED_CLUSTER_SIZE ||
		volume->mft_record_size != ROOTHEALTH_SUPPORTED_MFT_RECORD_SIZE ||
		volume->indx_record_size != ROOTHEALTH_SUPPORTED_INDEX_RECORD_SIZE)
		return -1;
	sectors = rh_get_u64(boot + 40);
	if (!sectors || wal->writer->device_size > ROOTHEALTH_MAX_VOLUME_BYTES ||
		wal->writer->device_size % ROOTHEALTH_SUPPORTED_SECTOR_SIZE ||
		wal->writer->device_size / ROOTHEALTH_SUPPORTED_SECTOR_SIZE < 2 ||
		sectors != wal->writer->device_size /
			ROOTHEALTH_SUPPORTED_SECTOR_SIZE - 1)
		return -1;
	return 0;
}

static int rh_wal_locate(struct rh_wal *wal, uint64_t expected_record,
		uint16_t expected_sequence)
{
	ntfs_volume *volume = NULL;
	ntfs_inode *extend = NULL, *inode = NULL;
	ntfs_attr *data = NULL;
	struct rh_cluster_bitmap_census ownership_census;
	uint16_t extend_sequence;
	uint64_t unreadable_records = 0;
	uint64_t definite_duplicates = 0;
	int result = RH_RESULT_UNSAFE;
	int overlap, mft_bitmap_allocated = -1;
	size_t i;

	memset(&ownership_census, 0, sizeof(ownership_census));
	volume = ntfs_mount(wal->writer->path, NTFS_MNT_RDONLY |
		NTFS_MNT_FORENSIC | NTFS_MNT_FS_NO_REPAIR);
	if (!volume)
		return errno == EIO ? RH_RESULT_IO : RH_RESULT_UNSAFE;
	if (!NDevReadOnly(volume->dev)) {
		result = RH_RESULT_INTERNAL;
		goto out;
	}
	if ((uint64_t)volume->sector_size != wal->sector_size ||
		rh_wal_validate_mounted_geometry(wal, volume))
		goto out;
	extend = ntfs_inode_open(volume, FILE_Extend);
	if (!extend || !(le16_to_cpu(extend->mrec->flags) & 1) ||
		!(le16_to_cpu(extend->mrec->flags) & 2))
		goto out;
	extend_sequence = le16_to_cpu(extend->mrec->sequence_number);
	inode = ntfs_inode_open(volume, expected_record);
	if (!inode || inode->mft_no != expected_record ||
		le16_to_cpu(inode->mrec->sequence_number) != expected_sequence)
		goto out;
	if (rh_wal_validate_inode_metadata(inode, extend_sequence))
		goto out;
	if (rh_wal_validate_cached_i30(extend, expected_record,
			expected_sequence, extend_sequence))
		goto out;
	wal->observation->checked = 1;
	wal->observation->present = 1;
	if (rh_wal_scan_unique_record(volume, extend_sequence, expected_record,
			expected_sequence, &unreadable_records,
			&definite_duplicates)) {
		wal->observation->unreadable_record_count = unreadable_records;
		wal->observation->definite_duplicate_count = definite_duplicates;
		if (errno == EIO || unreadable_records)
			result = RH_RESULT_IO;
		goto out;
	}
	wal->observation->unreadable_record_count = unreadable_records;
	wal->observation->definite_duplicate_count = definite_duplicates;
	wal->journal_record = expected_record;
	wal->journal_sequence = expected_sequence;
	data = ntfs_attr_open(inode, AT_DATA, AT_UNNAMED, 0);
	if (!data || rh_wal_copy_runs(wal, data, volume))
		goto invalid;
	if (!rh_wal_mft_bitmap_observe(volume, expected_record,
			&mft_bitmap_allocated))
		wal->observation->journal_mft_bitmap_allocated =
			mft_bitmap_allocated;
	if (rh_wal_cluster_bitmap_observe(volume, wal,
			&wal->observation->journal_cluster_bitmap_false_free_count))
		goto invalid;
	if (rh_cluster_bitmap_census_run(volume, wal->writer, 1,
			&ownership_census)) {
		result = errno == EIO ? RH_RESULT_IO :
			errno == ENOMEM ? RH_RESULT_INTERNAL : RH_RESULT_UNSAFE;
		goto out;
	}
	if (ownership_census.unreadable_slots) {
		result = RH_RESULT_IO;
		goto out;
	}
	if (!ownership_census.complete ||
			!ownership_census.structurally_valid ||
			!ownership_census.ownership_exact) {
		goto invalid;
	}
	wal->observation->ownership_census_complete = 1;
	overlap = rh_wal_validate_system_nonoverlap(volume, wal);
	if (overlap)
		goto invalid;
	if (rh_wal_validate_backup_boot_nonoverlap(wal))
		goto invalid;
	for (i = 0; i < wal->run_count; i++)
		if (rh_writer_exclude(wal->writer, wal->runs[i].device_offset,
				wal->runs[i].length) ||
			rh_writer_allow_raw_wal(wal->writer,
				wal->runs[i].device_offset, wal->runs[i].length))
			goto invalid;
	if (rh_wal_exclude_base_record(wal, volume))
		goto invalid;
	if (rh_writer_exclude(wal->writer,
			wal->writer->device_size - wal->sector_size, wal->sector_size))
		goto invalid;
	wal->observation->write_safe = 1;
	result = RH_RESULT_OK;
	goto out;
invalid:
	wal->observation->valid = 0;
	result = RH_RESULT_UNSAFE;
out:
	rh_cluster_bitmap_census_destroy(&ownership_census);
	if (data)
		ntfs_attr_close(data);
	if (inode && ntfs_inode_close(inode) && result == RH_RESULT_OK)
		result = RH_RESULT_IO;
	if (extend && ntfs_inode_close(extend) && result == RH_RESULT_OK)
		result = RH_RESULT_IO;
	if (ntfs_umount(volume, FALSE) && result == RH_RESULT_OK)
		result = RH_RESULT_IO;
	return result;
}

struct rh_parsed_header {
	uint64_t generation;
	uint32_t state;
	uint32_t transaction_kind;
	uint64_t data_used;
	uint64_t entry_count;
	uint64_t target_bytes;
	unsigned char journal_uuid[16];
	unsigned char transaction_uuid[16];
	unsigned char plan_hash[32];
};

static int rh_wal_same_transaction(const struct rh_parsed_header *first,
		const struct rh_parsed_header *second)
{
	return first->transaction_kind == second->transaction_kind &&
		!memcmp(first->transaction_uuid, second->transaction_uuid, 16) &&
		!memcmp(first->plan_hash, second->plan_hash, 32);
}

static int rh_wal_same_prefix(const struct rh_parsed_header *first,
		const struct rh_parsed_header *second)
{
	return first->data_used == second->data_used &&
		first->entry_count == second->entry_count &&
		first->target_bytes == second->target_bytes;
}

static int rh_wal_valid_header_transition(
		const struct rh_parsed_header parsed[2], int older, int newer)
{
	const struct rh_parsed_header *old = &parsed[older];
	const struct rh_parsed_header *new = &parsed[newer];

	if (memcmp(old->journal_uuid, new->journal_uuid, 16) ||
		old->generation == UINT64_MAX ||
		new->generation != old->generation + 1)
		return -1;
	if (old->state == RH_WAL_EMPTY && new->state == RH_WAL_EMPTY)
		return 0; /* Canonical release seed generations 1 and 2. */
	if (old->state == RH_WAL_EMPTY && new->state == RH_WAL_PREPARING)
		return new->data_used || new->entry_count || new->target_bytes ? -1 : 0;
	if ((old->state == RH_WAL_COMMITTED || old->state == RH_WAL_ROLLBACK) &&
		new->state == RH_WAL_EMPTY)
		return 0;
	if (!rh_wal_same_transaction(old, new))
		return -1;
	if (old->state == RH_WAL_PREPARING && new->state == RH_WAL_APPLYING)
		return old->data_used || old->entry_count || old->target_bytes ||
			new->entry_count != 1 || !new->data_used || !new->target_bytes ?
			-1 : 0;
	if (old->state == RH_WAL_APPLYING && new->state == RH_WAL_APPLYING)
		return old->entry_count == UINT64_MAX ||
			new->entry_count != old->entry_count + 1 ||
			new->data_used <= old->data_used ||
			new->target_bytes <= old->target_bytes ? -1 : 0;
	if (old->state == RH_WAL_APPLYING && new->state == RH_WAL_COMMITTED)
		return rh_wal_same_prefix(old, new) ? 0 : -1;
	if ((old->state == RH_WAL_PREPARING ||
		old->state == RH_WAL_APPLYING ||
		old->state == RH_WAL_COMMITTED) && new->state == RH_WAL_ROLLBACK)
		return rh_wal_same_prefix(old, new) ? 0 : -1;
	return -1;
}

static int rh_wal_parse_header(const struct rh_wal *wal,
		const unsigned char block[RH_WAL_HEADER_SIZE],
		struct rh_parsed_header *parsed)
{
	unsigned char digest[32];
	uint32_t state, transaction_kind;
	uint64_t data_used, entry_count, target_bytes;

	rh_sha256(block, RH_WAL_HEADER_DIGEST, digest);
	if (memcmp(block, rh_wal_magic, sizeof(rh_wal_magic)) ||
		rh_get_u32(block + 0x10) != 1 ||
		rh_get_u32(block + 0x14) != RH_WAL_HEADER_SIZE ||
		rh_get_u32(block + 0x18) != wal->sector_size ||
		!rh_get_u64(block + 0x20) ||
		rh_get_u64(block + 0x28) != wal->volume_serial ||
		rh_all_zero(block + 0x30, 16) ||
		rh_get_u64(block + 0x50) != RH_WAL_SIZE ||
		rh_get_u64(block + 0x58) != RH_WAL_ENTRY_START ||
		rh_get_u64(block + 0x98) != RH_WAL_MAX_TARGET_BYTES ||
		rh_get_u32(block + 0xa4) != RH_WAL_MAX_ENTRIES ||
		!rh_all_zero(block + 0xa8, RH_WAL_HEADER_DIGEST - 0xa8) ||
		memcmp(digest, block + RH_WAL_HEADER_DIGEST, 32))
		return -1;
	state = rh_get_u32(block + 0x1c);
	transaction_kind = rh_get_u32(block + 0xa0);
	data_used = rh_get_u64(block + 0x60);
	entry_count = rh_get_u64(block + 0x68);
	target_bytes = rh_get_u64(block + 0x70);
	if (state > RH_WAL_ROLLBACK || data_used > RH_WAL_SIZE -
		RH_WAL_ENTRY_START || entry_count > RH_WAL_MAX_ENTRIES ||
		target_bytes > RH_WAL_MAX_TARGET_BYTES)
		return -1;
	if (state == RH_WAL_EMPTY) {
		if (transaction_kind != RH_WAL_TX_NONE || data_used || entry_count ||
			target_bytes || !rh_all_zero(block + 0x40, 16) ||
			!rh_all_zero(block + 0x78, 32))
			return -1;
	} else if ((transaction_kind != RH_WAL_TX_METADATA_REPAIR &&
		transaction_kind != RH_WAL_TX_DIRTY_CLEAR) ||
		rh_all_zero(block + 0x40, 16) || rh_all_zero(block + 0x78, 32)) {
		return -1;
	}
	if (data_used % wal->sector_size ||
		(state == RH_WAL_PREPARING &&
		 (data_used || entry_count || target_bytes)) ||
		(entry_count == 0 && (data_used || target_bytes)) ||
		(entry_count && (entry_count > UINT64_MAX / RH_WAL_DESCRIPTOR_SIZE ||
			data_used < entry_count * RH_WAL_DESCRIPTOR_SIZE)) ||
		((state == RH_WAL_APPLYING || state == RH_WAL_COMMITTED) &&
			!entry_count))
		return -1;
	memset(parsed, 0, sizeof(*parsed));
	parsed->generation = rh_get_u64(block + 0x20);
	parsed->state = state;
	parsed->transaction_kind = transaction_kind;
	parsed->data_used = data_used;
	parsed->entry_count = entry_count;
	parsed->target_bytes = target_bytes;
	memcpy(parsed->journal_uuid, block + 0x30, 16);
	memcpy(parsed->transaction_uuid, block + 0x40, 16);
	memcpy(parsed->plan_hash, block + 0x78, 32);
	return 0;
}

static void rh_wal_observe_selected(struct rh_wal *wal,
		const struct rh_parsed_header *parsed)
{
	struct rh_wal_observation *observation = wal->observation;

	wal->generation = parsed->generation;
	wal->state = (enum rh_wal_state)parsed->state;
	wal->transaction_kind =
		(enum rh_wal_transaction_kind)parsed->transaction_kind;
	wal->data_used = parsed->data_used;
	wal->entry_count = parsed->entry_count;
	wal->target_bytes = parsed->target_bytes;
	memcpy(wal->journal_uuid, parsed->journal_uuid, 16);
	memcpy(wal->transaction_uuid, parsed->transaction_uuid, 16);
	memcpy(wal->plan_hash, parsed->plan_hash, 32);
	observation->valid = 1;
	observation->state = (int)wal->state;
	observation->transaction_kind = (int)wal->transaction_kind;
	observation->max_entry_count = RH_WAL_MAX_ENTRIES;
	observation->generation = wal->generation;
	observation->recovery_required = wal->state == RH_WAL_EMPTY ? 0 : 1;
	observation->volume_serial = wal->volume_serial;
	rh_uuid_format(wal->journal_uuid, observation->journal_uuid);
}

int rh_wal_locate_and_validate(struct rh_wal *wal, struct rh_writer *writer,
		uint64_t expected_serial, const unsigned char expected_uuid[16],
		uint64_t expected_record, uint16_t expected_sequence,
		struct rh_wal_observation *observation)
{
	unsigned char headers[2][RH_WAL_HEADER_SIZE];
	struct rh_parsed_header parsed[2];
	int valid[2] = {0, 0};
	int result, selected;
	struct rh_boot_geometry geometry;
	size_t excluded_checkpoint, raw_checkpoint;

	if (!wal || !writer || !expected_serial || !expected_uuid ||
		!expected_record || !expected_sequence || !observation)
		return RH_RESULT_INTERNAL;
	/* Locator owns the complete restriction manifest for this fresh writer. */
	if (writer->excluded_count || writer->raw_wal_allowed_count)
		return RH_RESULT_INTERNAL;
	if (expected_record < FILE_first_user)
		return RH_RESULT_UNSAFE;
	memset(wal, 0, sizeof(*wal));
	memset(observation, 0, sizeof(*observation));
	observation->present = -1;
	observation->valid = -1;
	observation->recovery_required = -1;
	observation->state = -1;
	observation->transaction_kind = -1;
	observation->max_entry_count = -1;
	observation->journal_mft_bitmap_allocated = -1;
	wal->writer = writer;
	wal->observation = observation;
	wal->volume_serial = expected_serial;
	excluded_checkpoint = writer->excluded_count;
	raw_checkpoint = writer->raw_wal_allowed_count;
	/* The boot parser has already constrained this to a legal NTFS sector. */
	{
		unsigned char boot[512];
		if (rh_writer_read(writer, 0, sizeof(boot), boot))
			return RH_RESULT_IO;
		if (memcmp(boot + 3, "NTFS    ", 8) || boot[510] != 0x55 ||
			boot[511] != 0xaa ||
			rh_get_u16(boot + 11) != ROOTHEALTH_SUPPORTED_SECTOR_SIZE ||
			boot[13] != ROOTHEALTH_SUPPORTED_CLUSTER_SIZE /
				ROOTHEALTH_SUPPORTED_SECTOR_SIZE ||
			rh_get_u64(boot + 72) != expected_serial ||
			writer->device_size > ROOTHEALTH_MAX_VOLUME_BYTES ||
			writer->device_size % ROOTHEALTH_SUPPORTED_SECTOR_SIZE ||
			writer->device_size / ROOTHEALTH_SUPPORTED_SECTOR_SIZE < 2 ||
			rh_get_u64(boot + 40) != writer->device_size /
				ROOTHEALTH_SUPPORTED_SECTOR_SIZE - 1)
			return RH_RESULT_UNSAFE;
		wal->sector_size = rh_get_u16(boot + 11);
		if (!roothealth_boot_sector_validate(boot, sizeof(boot),
				writer->device_size, &geometry))
			return RH_RESULT_UNSAFE;
	}
	result = rh_wal_locate(wal, expected_record, expected_sequence);
	if (result != RH_RESULT_OK)
		goto fail_restrictions;
	if (rh_wal_stream_read(wal, 0, sizeof(headers), headers)) {
		result = RH_RESULT_IO;
		goto fail_restrictions;
	}
	valid[0] = !rh_wal_parse_header(wal, headers[0], &parsed[0]);
	valid[1] = !rh_wal_parse_header(wal, headers[1], &parsed[1]);
	if (!valid[0] && !valid[1]) {
		observation->valid = 0;
		result = RH_RESULT_UNSAFE;
		goto fail_restrictions;
	}
	if (valid[0] && valid[1]) {
		if (memcmp(parsed[0].journal_uuid, parsed[1].journal_uuid, 16) ||
			(parsed[0].generation == parsed[1].generation &&
			 memcmp(headers[0], headers[1], RH_WAL_HEADER_SIZE))) {
			observation->valid = 0;
			result = RH_RESULT_UNSAFE;
			goto fail_restrictions;
		}
		if (parsed[0].generation != parsed[1].generation) {
			int newer = parsed[1].generation > parsed[0].generation ? 1 : 0;
			if (rh_wal_valid_header_transition(parsed, newer ? 0 : 1,
					newer)) {
				observation->valid = 0;
				result = RH_RESULT_UNSAFE;
				goto fail_restrictions;
			}
		}
		selected = parsed[1].generation > parsed[0].generation ? 1 : 0;
	} else {
		selected = valid[0] ? 0 : 1;
		wal->degraded_slot = selected ? 1 : 2;
	}
	wal->selected_slot = selected;
	memcpy(wal->selected_header, headers[selected], RH_WAL_HEADER_SIZE);
	rh_wal_observe_selected(wal, &parsed[selected]);
	if (memcmp(wal->journal_uuid, expected_uuid, 16)) {
		result = RH_RESULT_UNSAFE;
		goto fail_restrictions;
	}
	rh_wal_install_builtin_action_verifiers(wal);
	observation->fast_path_trusted = 1;
	return RH_RESULT_OK;
fail_restrictions:
	observation->fast_path_trusted = 0;
	observation->write_safe = 0;
	rh_wal_free_runs(wal);
	if (rh_writer_restore_restrictions(writer, excluded_checkpoint,
			raw_checkpoint))
		return RH_RESULT_INTERNAL;
	return result;
}

static int rh_wal_locate_raw_bounded(struct rh_wal *wal,
		struct rh_writer *writer, uint64_t expected_serial,
		const unsigned char expected_uuid[16], uint64_t expected_record,
		uint16_t expected_sequence, struct rh_wal_observation *observation,
		int require_interrupted)
{
	unsigned char boot[ROOTHEALTH_SUPPORTED_SECTOR_SIZE];
	unsigned char headers[2][RH_WAL_HEADER_SIZE];
	struct rh_boot_geometry geometry;
	struct rh_parsed_header parsed[2];
	int valid[2] = {0, 0}, selected = -1, result = RH_RESULT_UNSAFE;
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
	const char *test_stage = "arguments";
#endif

	if (!wal || !writer || !expected_serial || !expected_uuid ||
			!expected_record || !expected_sequence || !observation ||
			writer->excluded_count || writer->raw_wal_allowed_count)
		return RH_RESULT_INTERNAL;
	memset(wal, 0, sizeof(*wal));
	memset(observation, 0, sizeof(*observation));
	observation->present = observation->valid =
		observation->recovery_required = observation->state =
		observation->transaction_kind = observation->max_entry_count = -1;
	observation->journal_mft_bitmap_allocated = -1;
	wal->writer = writer;
	wal->observation = observation;
	wal->volume_serial = expected_serial;
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
	test_stage = "boot";
#endif
	if (rh_writer_read(writer, 0, sizeof(boot), boot))
		return RH_RESULT_IO;
	if (!roothealth_boot_sector_validate(boot, sizeof(boot), writer->device_size,
			&geometry) || geometry.serial != expected_serial)
		return RH_RESULT_UNSAFE;
	wal->sector_size = geometry.sector_size;
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
	test_stage = "raw-locate";
#endif
	result = rh_wal_locate_raw_recovery(wal, &geometry, expected_record,
		expected_sequence);
	if (result != RH_RESULT_OK)
		goto fail;
	/* Every later rejection is unsafe unless a concrete read reports I/O. */
	result = RH_RESULT_UNSAFE;
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
	test_stage = "headers-read";
#endif
	if (rh_wal_stream_read(wal, 0, sizeof(headers), headers)) {
		result = RH_RESULT_IO;
		goto fail;
	}
	valid[0] = !rh_wal_parse_header(wal, headers[0], &parsed[0]);
	valid[1] = !rh_wal_parse_header(wal, headers[1], &parsed[1]);
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
	test_stage = "headers-parse";
#endif
	if (!valid[0] && !valid[1])
		goto fail;
	if (valid[0] && valid[1]) {
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
		test_stage = "header-pair";
#endif
		if (memcmp(parsed[0].journal_uuid, parsed[1].journal_uuid, 16) ||
				(parsed[0].generation == parsed[1].generation &&
				 memcmp(headers[0], headers[1], RH_WAL_HEADER_SIZE)))
			goto fail;
		selected = parsed[1].generation > parsed[0].generation ? 1 : 0;
		if (parsed[0].generation != parsed[1].generation &&
				rh_wal_valid_header_transition(parsed, selected ? 0 : 1,
					selected))
			goto fail;
	} else {
		selected = valid[0] ? 0 : 1;
		wal->degraded_slot = selected ? 1 : 2;
	}
	wal->selected_slot = selected;
	memcpy(wal->selected_header, headers[selected], RH_WAL_HEADER_SIZE);
	rh_wal_observe_selected(wal, &parsed[selected]);
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
	test_stage = "identity-state";
#endif
	if (memcmp(wal->journal_uuid, expected_uuid, 16) ||
			(require_interrupted && (wal->state == RH_WAL_EMPTY ||
			 wal->state == RH_WAL_PREPARING)))
		goto fail;
	rh_wal_install_builtin_action_verifiers(wal);
	observation->fast_path_trusted = 1;
	return RH_RESULT_OK;
fail:
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
	fprintf(stderr, "raw WAL recovery locator failed stage=%s result=%d "
		"valid=%d/%d selected=%d state=%d errno=%d\n", test_stage,
		result, valid[0], valid[1],
		selected, selected >= 0 ? (int)wal->state : -1, errno);
#endif
	observation->fast_path_trusted = 0;
	observation->write_safe = 0;
	rh_wal_free_runs(wal);
	(void)rh_writer_restore_restrictions(writer, 0, 0);
	return result;
}

int rh_wal_locate_and_validate_bounded(struct rh_wal *wal,
		struct rh_writer *writer, uint64_t expected_serial,
		const unsigned char expected_uuid[16], uint64_t expected_record,
		uint16_t expected_sequence, struct rh_wal_observation *observation)
{
	return rh_wal_locate_raw_bounded(wal, writer, expected_serial,
		expected_uuid, expected_record, expected_sequence, observation, 0);
}

int rh_wal_locate_raw_interrupted_recovery(struct rh_wal *wal,
		struct rh_writer *writer, uint64_t expected_serial,
		const unsigned char expected_uuid[16], uint64_t expected_record,
		uint16_t expected_sequence, struct rh_wal_observation *observation)
{
	return rh_wal_locate_raw_bounded(wal, writer, expected_serial,
		expected_uuid, expected_record, expected_sequence, observation, 1);
}

static int rh_random_uuid(unsigned char output[16])
{
	size_t done = 0;
#ifdef __linux__
	while (done < 16) {
		ssize_t got = getrandom(output + done, 16 - done, 0);
		if (got < 0) {
			if (errno == EINTR)
				continue;
			break;
		}
		done += (size_t)got;
	}
#endif
	if (done < 16) {
		int fd = open("/dev/urandom", O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
		if (fd < 0)
			return -1;
		while (done < 16) {
			ssize_t got = read(fd, output + done, 16 - done);
			if (got < 0) {
				if (errno == EINTR)
					continue;
				close(fd);
				return -1;
			}
			if (!got) {
				close(fd);
				errno = EIO;
				return -1;
			}
			done += (size_t)got;
		}
		if (close(fd))
			return -1;
	}
	output[6] = (unsigned char)((output[6] & 0x0f) | 0x40);
	output[8] = (unsigned char)((output[8] & 0x3f) | 0x80);
	return rh_all_zero(output, 16) ? -1 : 0;
}

static void rh_wal_build_header(const struct rh_wal *wal,
		enum rh_wal_state state,
		enum rh_wal_transaction_kind transaction_kind,
		uint64_t generation, uint64_t data_used, uint64_t entry_count,
		uint64_t target_bytes, const unsigned char transaction_uuid[16],
		const unsigned char plan_hash[32],
		unsigned char output[RH_WAL_HEADER_SIZE])
{
	unsigned char digest[32];

	memset(output, 0, RH_WAL_HEADER_SIZE);
	memcpy(output, rh_wal_magic, sizeof(rh_wal_magic));
	rh_put_u32(output + 0x10, 1);
	rh_put_u32(output + 0x14, RH_WAL_HEADER_SIZE);
	rh_put_u32(output + 0x18, wal->sector_size);
	rh_put_u32(output + 0x1c, (uint32_t)state);
	rh_put_u64(output + 0x20, generation);
	rh_put_u64(output + 0x28, wal->volume_serial);
	memcpy(output + 0x30, wal->journal_uuid, 16);
	if (state != RH_WAL_EMPTY) {
		memcpy(output + 0x40, transaction_uuid, 16);
		memcpy(output + 0x78, plan_hash, 32);
	}
	rh_put_u64(output + 0x50, RH_WAL_SIZE);
	rh_put_u64(output + 0x58, RH_WAL_ENTRY_START);
	rh_put_u64(output + 0x60, data_used);
	rh_put_u64(output + 0x68, entry_count);
	rh_put_u64(output + 0x70, target_bytes);
	rh_put_u64(output + 0x98, RH_WAL_MAX_TARGET_BYTES);
	rh_put_u32(output + 0xa0, (uint32_t)transaction_kind);
	rh_put_u32(output + 0xa4, RH_WAL_MAX_ENTRIES);
	rh_sha256(output, RH_WAL_HEADER_DIGEST, digest);
	memcpy(output + RH_WAL_HEADER_DIGEST, digest, sizeof(digest));
}

static int rh_wal_publish(struct rh_wal *wal, enum rh_wal_state state,
		enum rh_wal_transaction_kind transaction_kind,
		uint64_t data_used, uint64_t entry_count, uint64_t target_bytes,
		const unsigned char transaction_uuid[16],
		const unsigned char plan_hash[32])
{
	unsigned char output[RH_WAL_HEADER_SIZE];
	unsigned char check[RH_WAL_HEADER_SIZE];
	struct rh_parsed_header parsed;
	int slot = wal->selected_slot ? 0 : 1;
	uint64_t generation;

	if (wal->generation == UINT64_MAX) {
		errno = EOVERFLOW;
		return -1;
	}
	generation = wal->generation + 1;
	rh_wal_build_header(wal, state, transaction_kind, generation, data_used,
		entry_count, target_bytes, transaction_uuid, plan_hash, output);
	if (rh_wal_traced_write(wal,
			wal->state == state ? RH_WAL_TRACE_DESCRIPTOR : RH_WAL_TRACE_STATE,
			(uint64_t)slot * RH_WAL_HEADER_SIZE, sizeof(output), slot,
			wal->state, state, output) ||
		rh_wal_stream_read(wal, (uint64_t)slot * RH_WAL_HEADER_SIZE,
			sizeof(check), check) || memcmp(output, check, sizeof(output)) ||
		rh_wal_parse_header(wal, check, &parsed)) {
		if (!errno)
			errno = EIO;
		return -1;
	}
	wal->selected_slot = slot;
	memcpy(wal->selected_header, output, sizeof(output));
	rh_wal_observe_selected(wal, &parsed);
	return 0;
}

int rh_wal_reconstruct_degraded(struct rh_wal *wal)
{
	unsigned char check[RH_WAL_HEADER_SIZE];
	int slot;
	int opened = 0;
	int result = -1;

	if (!wal || !wal->degraded_slot || !wal->observation ||
		wal->observation->valid != 1) {
		errno = EINVAL;
		return -1;
	}
	slot = wal->selected_slot ? 0 : 1;
	if (wal->writer->write_fd < 0) {
		if (rh_writer_raw_begin(wal->writer))
			return -1;
		opened = 1;
	}
	if (rh_wal_traced_write(wal, RH_WAL_TRACE_SUPERBLOCK_RECONSTRUCT,
			(uint64_t)slot * RH_WAL_HEADER_SIZE, RH_WAL_HEADER_SIZE, slot,
			wal->state, wal->state, wal->selected_header) ||
		rh_wal_stream_read(wal, (uint64_t)slot * RH_WAL_HEADER_SIZE,
			RH_WAL_HEADER_SIZE, check) ||
		memcmp(check, wal->selected_header, RH_WAL_HEADER_SIZE))
		goto out;
	wal->degraded_slot = 0;
	wal->observation->recovered = 1;
	wal->observation->recovery_required = wal->state == RH_WAL_EMPTY ? 0 : 1;
	result = 0;
out:
	wal->observation->write_boundaries = wal->writer->write_boundaries;
	if (opened && rh_writer_raw_end(wal->writer))
		result = -1;
	return result;
}

static void rh_wal_free_planned(struct rh_wal *wal)
{
	size_t i;

	if (!wal)
		return;
	for (i = 0; i < wal->planned_count; i++) {
		free(wal->planned_entries[i].before);
		free(wal->planned_entries[i].after);
	}
	free(wal->planned_entries);
	wal->planned_entries = NULL;
	wal->planned_count = 0;
}

static void rh_wal_descriptor_prefix(const struct rh_wal_planned_entry *entry,
		uint64_t ordinal, unsigned char output[RH_WAL_PLAN_BYTES])
{
	memset(output, 0, RH_WAL_PLAN_BYTES);
	memcpy(output, rh_entry_magic, sizeof(rh_entry_magic));
	rh_put_u32(output + 0x08, 1);
	rh_put_u32(output + 0x0c, RH_WAL_DESCRIPTOR_SIZE);
	rh_put_u64(output + 0x10, ordinal);
	rh_put_u64(output + 0x18, entry->target_offset);
	rh_put_u64(output + 0x20, entry->length);
	rh_put_u64(output + 0x28, entry->payload_offset);
	rh_put_u64(output + 0x30, entry->padded_length);
	rh_put_u32(output + 0x38, entry->kind);
	memcpy(output + 0x40, entry->old_hash, sizeof(entry->old_hash));
	memcpy(output + 0x60, entry->new_hash, sizeof(entry->new_hash));
	rh_put_u32(output + 0x080, entry->target.seal_version);
	rh_put_u32(output + 0x084, (uint32_t)entry->target.object);
	rh_put_u64(output + 0x088, entry->target.owner_mft_record);
	rh_put_u16(output + 0x090, entry->target.owner_sequence);
	rh_put_u16(output + 0x092, entry->target.attribute_instance);
	rh_put_u32(output + 0x094, entry->target.attribute_type);
	rh_put_u16(output + 0x098, entry->target.attribute_name_length);
	rh_put_u16(output + 0x09a, entry->target.flags);
	rh_put_u32(output + 0x09c, entry->target.evidence_version);
	memcpy(output + 0x0a0, entry->target.attribute_name_hash, 32);
	rh_put_u64(output + 0x0c0, (uint64_t)entry->target.lowest_vcn);
	rh_put_u64(output + 0x0c8, (uint64_t)entry->target.logical_vcn);
	rh_put_u64(output + 0x0d0, entry->target.logical_offset);
	rh_put_u64(output + 0x0d8, entry->target.logical_length);
	rh_put_u64(output + 0x0e0, entry->target.semantic_target_offset);
	rh_put_u64(output + 0x0e8, entry->target.semantic_target_length);
	rh_put_u64(output + 0x0f0, (uint64_t)entry->target.lcn);
	rh_put_u64(output + 0x0f8, entry->target.evidence_generation);
	memcpy(output + 0x100, entry->target.evidence_hash, 32);
	memcpy(output + 0x120, entry->target.staged_view_hash, 32);
	memcpy(output + 0x140, entry->target.semantic_before_hash, 32);
	memcpy(output + 0x160, entry->target.semantic_after_hash, 32);
}

static void rh_wal_descriptor_target_parse(const unsigned char *descriptor,
		struct rh_write_semantic_target *target)
{
	memset(target, 0, sizeof(*target));
	target->seal_version = rh_get_u32(descriptor + 0x080);
	target->object = (enum rh_write_target_object)
		rh_get_u32(descriptor + 0x084);
	target->owner_mft_record = rh_get_u64(descriptor + 0x088);
	target->owner_sequence = rh_get_u16(descriptor + 0x090);
	target->attribute_instance = rh_get_u16(descriptor + 0x092);
	target->attribute_type = rh_get_u32(descriptor + 0x094);
	target->attribute_name_length = rh_get_u16(descriptor + 0x098);
	target->flags = rh_get_u16(descriptor + 0x09a);
	target->evidence_version = rh_get_u32(descriptor + 0x09c);
	memcpy(target->attribute_name_hash, descriptor + 0x0a0, 32);
	target->lowest_vcn = rh_get_s64(descriptor + 0x0c0);
	target->logical_vcn = rh_get_s64(descriptor + 0x0c8);
	target->logical_offset = rh_get_u64(descriptor + 0x0d0);
	target->logical_length = rh_get_u64(descriptor + 0x0d8);
	target->semantic_target_offset = rh_get_u64(descriptor + 0x0e0);
	target->semantic_target_length = rh_get_u64(descriptor + 0x0e8);
	target->lcn = rh_get_s64(descriptor + 0x0f0);
	target->evidence_generation = rh_get_u64(descriptor + 0x0f8);
	memcpy(target->evidence_hash, descriptor + 0x100, 32);
	memcpy(target->staged_view_hash, descriptor + 0x120, 32);
	memcpy(target->semantic_before_hash, descriptor + 0x140, 32);
	memcpy(target->semantic_after_hash, descriptor + 0x160, 32);
	target->finalized = 1;
}

static int rh_wal_metadata_action_order_valid_internal(
		const uint32_t *action_ids, size_t count, int complete)
{
	size_t i;
	unsigned int redo_count = 0;
	unsigned int restart_count = 0;
	unsigned int dirty_set_count = 0;
	int derived_seen = 0;
	int nonbitmap_derived_seen = 0;
	int index_root_seen = 0;
	int allocation_bitmap_seen = 0;
	int restart_seen = 0;

	if (!action_ids || !count)
		return 0;
	for (i = 0; i < count; i++) {
		uint32_t id = action_ids[i];

		/* IDs 1-4 are direct redundant-copy foundation operations only. */
		if (id >= RH_WRITE_ACTION_ID(RH_WRITE_BOOT_PRIMARY) &&
			id <= RH_WRITE_ACTION_ID(RH_WRITE_MFT_MIRROR))
			return 0;
		if (id == RH_WRITE_ACTION_ID(RH_WRITE_VOLUME_DIRTY_SET)) {
			if (i != dirty_set_count || i > 1 || derived_seen || restart_seen)
				return 0;
			dirty_set_count++;
			continue;
		}
		if (id == RH_WRITE_ACTION_ID(RH_WRITE_LOGFILE_REDO)) {
			if (derived_seen || restart_seen)
				return 0;
			redo_count++;
			continue;
		}
		if (id == RH_WRITE_ACTION_ID(RH_WRITE_LOGFILE_RESTART)) {
			restart_seen = 1;
			restart_count++;
			continue;
		}
		if (id == RH_WRITE_ACTION_ID(RH_WRITE_BITMAP_MFT) ||
				id == RH_WRITE_ACTION_ID(RH_WRITE_BITMAP_CLUSTER)) {
			if (restart_seen || nonbitmap_derived_seen)
				return 0;
			derived_seen = 1;
			allocation_bitmap_seen = 1;
			continue;
		}
		/*
		 * Action 11 only removes the proven stale resident $I30 edge.  It
		 * allocates and frees no records or clusters, and its repaired view
		 * can therefore be the evidence precursor for allocation bitmaps.
		 * Keep this exception one-way and singular: every other derived
		 * action still has to follow the allocation-obligation prefix.
		 */
		if (id == RH_WRITE_ACTION_ID(RH_WRITE_INDEX_ROOT)) {
			if (restart_seen || allocation_bitmap_seen || index_root_seen ||
					nonbitmap_derived_seen)
				return 0;
			derived_seen = 1;
			index_root_seen = 1;
			continue;
		}
		if (restart_seen)
			return 0;
		derived_seen = 1;
		nonbitmap_derived_seen = 1;
	}
	/* Supported native-log plans always publish both restart-page copies. */
	if (restart_count > 2 ||
		(restart_count && !redo_count &&
		 !(restart_count == 2U && count == 2U)) ||
			(complete && redo_count && restart_count != 2))
		return 0;
	if (dirty_set_count > 2 || (complete && dirty_set_count != 0 &&
			dirty_set_count != 2))
		return 0;
	if (complete && !derived_seen && !redo_count && restart_count != 2U)
		return 0;
	if (!complete && dirty_set_count == 1 && count != 1)
		return 0;
	return 1;
}

static int rh_wal_metadata_action_order_valid(const uint32_t *action_ids,
		size_t count)
{
	return rh_wal_metadata_action_order_valid_internal(action_ids, count, 1);
}

int rh_wal_validate_action_order(enum rh_wal_transaction_kind transaction_kind,
		const enum rh_write_kind *kinds, size_t count)
{
	uint32_t *action_ids;
	size_t i;
	unsigned int dirty_set_count = 0;
	unsigned int dirty_clear_count = 0;
	int result = 0;

	if (!kinds || !count || count > RH_WAL_MAX_ENTRIES)
		return 0;
	action_ids = malloc(count * sizeof(*action_ids));
	if (!action_ids)
		return 0;
	for (i = 0; i < count; i++) {
		if (kinds[i] < 0 || kinds[i] >= RH_WRITE_KIND_COUNT)
			goto out;
		action_ids[i] = RH_WRITE_ACTION_ID(kinds[i]);
		if (kinds[i] == RH_WRITE_VOLUME_DIRTY_SET)
			dirty_set_count++;
		else if (kinds[i] == RH_WRITE_VOLUME_DIRTY_CLEAR)
			dirty_clear_count++;
	}
	if (transaction_kind == RH_WAL_TX_DIRTY_CLEAR) {
		result = count == 2 && dirty_clear_count == 2 && !dirty_set_count;
		goto out;
	}
	if (transaction_kind != RH_WAL_TX_METADATA_REPAIR || dirty_clear_count ||
		(dirty_set_count != 0 && dirty_set_count != 2) ||
		(dirty_set_count && (kinds[0] != RH_WRITE_VOLUME_DIRTY_SET ||
			kinds[1] != RH_WRITE_VOLUME_DIRTY_SET)))
		goto out;
	result = rh_wal_metadata_action_order_valid(action_ids, count);
out:
	free(action_ids);
	return result;
}

static int rh_wal_dirty_pair_operations_valid(const struct rh_wal *wal,
		const struct rh_write_operation *first,
		const struct rh_write_operation *second, int set_dirty)
{
	unsigned char boot[512];
	uint64_t mft_lcn, mirror_lcn, primary_base, mirror_base, relative;
	uint16_t before, after;
	enum rh_write_kind kind = set_dirty ? RH_WRITE_VOLUME_DIRTY_SET :
		RH_WRITE_VOLUME_DIRTY_CLEAR;
	uint16_t dirty = le16_to_cpu(VOLUME_IS_DIRTY);

	if (!wal || !first || !second || first->kind != kind ||
			second->kind != kind || first->length != sizeof(le16) ||
			second->length != sizeof(le16) ||
			memcmp(first->before, second->before, sizeof(le16)) ||
			memcmp(first->after, second->after, sizeof(le16)) ||
			rh_writer_staged_read(wal->writer, 0, 0, sizeof(boot), boot))
		return 0;
	mft_lcn = rh_get_u64(boot + 48);
	mirror_lcn = rh_get_u64(boot + 56);
	if (mft_lcn > (wal->writer->device_size >> 12) ||
			mirror_lcn > (wal->writer->device_size >> 12) ||
			mft_lcn > (UINT64_MAX >> 12) || mirror_lcn > (UINT64_MAX >> 12))
		return 0;
	primary_base = (mft_lcn << 12) + ((uint64_t)FILE_Volume << 10);
	mirror_base = (mirror_lcn << 12) + ((uint64_t)FILE_Volume << 10);
	if (first->offset < primary_base || first->offset - primary_base >
			1024U - sizeof(le16))
		return 0;
	relative = first->offset - primary_base;
	if (second->offset != mirror_base + relative ||
			(first->offset >> 9) !=
			((first->offset + sizeof(le16) - 1U) >> 9) ||
			(second->offset >> 9) !=
			((second->offset + sizeof(le16) - 1U) >> 9))
		return 0;
	before = rh_get_u16(first->before);
	after = rh_get_u16(first->after);
	return set_dirty ? (!(before & dirty) && after == (uint16_t)(before | dirty)) :
		((before & dirty) && after == (uint16_t)(before & (uint16_t)~dirty));
}

static int rh_wal_mft_record_bases(const struct rh_wal *wal, uint64_t record,
		uint64_t *primary_base, uint64_t *mirror_base)
{
	unsigned char boot[512];
	uint64_t mft_lcn, mirror_lcn, record_offset;

	if (!wal || !primary_base || !mirror_base || record > 3U ||
			rh_writer_staged_read(wal->writer, 0, 0, sizeof(boot), boot))
		return 0;
	mft_lcn = rh_get_u64(boot + 48);
	mirror_lcn = rh_get_u64(boot + 56);
	record_offset = record << 10;
	if (mft_lcn > (UINT64_MAX >> 12) || mirror_lcn > (UINT64_MAX >> 12) ||
			(mft_lcn << 12) > UINT64_MAX - record_offset ||
			(mirror_lcn << 12) > UINT64_MAX - record_offset)
		return 0;
	*primary_base = (mft_lcn << 12) + record_offset;
	*mirror_base = (mirror_lcn << 12) + record_offset;
	return wal->writer->device_size >= 1024U &&
		*primary_base <= wal->writer->device_size - 1024U &&
		*mirror_base <= wal->writer->device_size - 1024U;
}

static int rh_wal_mft_raw_records_equal(const unsigned char *first,
		const unsigned char *second)
{
	unsigned char fixed_first[1024], fixed_second[1024];
	MFT_RECORD *first_mft = (MFT_RECORD *)fixed_first;
	MFT_RECORD *second_mft = (MFT_RECORD *)fixed_second;
	uint16_t usa_offset, usa_count;
	size_t usa_end, i;

	if (!first || !second)
		return 0;
	memcpy(fixed_first, first, sizeof(fixed_first));
	memcpy(fixed_second, second, sizeof(fixed_second));
	if (ntfs_mst_post_read_fixup((NTFS_RECORD *)fixed_first,
			sizeof(fixed_first)) ||
			ntfs_mst_post_read_fixup((NTFS_RECORD *)fixed_second,
				sizeof(fixed_second)) || first_mft->magic != magic_FILE ||
			second_mft->magic != magic_FILE)
		return 0;
	usa_offset = le16_to_cpu(first_mft->usa_ofs);
	usa_count = le16_to_cpu(first_mft->usa_count);
	usa_end = (size_t)usa_offset + (size_t)usa_count * sizeof(uint16_t);
	if (usa_count != 3U || le16_to_cpu(second_mft->usa_ofs) != usa_offset ||
			le16_to_cpu(second_mft->usa_count) != usa_count ||
			usa_end > sizeof(fixed_first))
		return 0;
	for (i = 0; i < sizeof(fixed_first); i++) {
		if (i >= usa_offset && i < usa_end)
			continue;
		if (fixed_first[i] != fixed_second[i])
			return 0;
	}
	return 1;
}

static int rh_wal_semantic_targets_are_mirror_pair(
		const struct rh_write_semantic_target *first, uint64_t first_base,
		const struct rh_write_semantic_target *second, uint64_t second_base)
{
	uint16_t location = RH_WRITE_TARGET_PRIMARY | RH_WRITE_TARGET_MIRROR;

	if (!first || !second ||
			first->object != RH_WRITE_TARGET_MFT_RECORD_PRIMARY ||
			second->object != RH_WRITE_TARGET_MFT_RECORD_MIRROR ||
			first->owner_mft_record > 3U ||
			first->owner_mft_record != second->owner_mft_record ||
			first->owner_sequence != second->owner_sequence ||
			first->seal_version != second->seal_version ||
			first->attribute_instance != second->attribute_instance ||
			first->attribute_type != second->attribute_type ||
			first->attribute_name_length != second->attribute_name_length ||
			(first->flags & (uint16_t)~location) !=
				(second->flags & (uint16_t)~location) ||
			(first->flags & location) != RH_WRITE_TARGET_PRIMARY ||
			(second->flags & location) != RH_WRITE_TARGET_MIRROR ||
			first->evidence_version != second->evidence_version ||
			memcmp(first->attribute_name_hash, second->attribute_name_hash, 32) ||
			first->lowest_vcn != second->lowest_vcn ||
			first->logical_vcn != second->logical_vcn ||
			first->logical_offset != second->logical_offset ||
			first->logical_length != second->logical_length ||
			first->semantic_target_offset < first_base ||
			second->semantic_target_offset < second_base ||
			first->semantic_target_offset - first_base !=
				second->semantic_target_offset - second_base ||
			first->semantic_target_length != second->semantic_target_length ||
			first->lcn != second->lcn ||
			first->evidence_generation != second->evidence_generation ||
			memcmp(first->evidence_hash, second->evidence_hash, 32) ||
			memcmp(first->staged_view_hash, second->staged_view_hash, 32) ||
			memcmp(first->semantic_before_hash,
				second->semantic_before_hash, 32) ||
			memcmp(first->semantic_after_hash,
				second->semantic_after_hash, 32) ||
			first->finalized != second->finalized)
		return 0;
	return 1;
}

static int rh_wal_mft_pair_operations_valid(const struct rh_wal *wal,
		const struct rh_write_operation *first,
		const struct rh_write_operation *second)
{
	uint64_t primary_base, mirror_base;

	if (!wal || !first || !second || first->kind != second->kind ||
			!rh_wal_mft_record_bases(wal, first->target.owner_mft_record,
				&primary_base, &mirror_base) ||
			!rh_wal_semantic_targets_are_mirror_pair(&first->target,
				primary_base, &second->target, mirror_base))
		return 0;
	if (first->kind == RH_WRITE_VOLUME_DIRTY_SET)
		return rh_wal_dirty_pair_operations_valid(wal, first, second, 1);
	if (first->kind == RH_WRITE_VOLUME_DIRTY_CLEAR)
		return rh_wal_dirty_pair_operations_valid(wal, first, second, 0);
	return first->offset == primary_base && second->offset == mirror_base &&
		first->length == 1024U && second->length == 1024U &&
		rh_wal_mft_raw_records_equal(first->before, second->before) &&
		rh_wal_mft_raw_records_equal(first->after, second->after);
}

int rh_wal_validate_mft_operation_pairs(const struct rh_wal *wal,
		const struct rh_write_operation *operations, size_t count)
{
	size_t i;

	for (i = 0; i < count; i++) {
		const struct rh_write_semantic_target *target = &operations[i].target;

		if (target->object == RH_WRITE_TARGET_MFT_RECORD_MIRROR)
			return 0;
		if (target->object != RH_WRITE_TARGET_MFT_RECORD_PRIMARY ||
				target->owner_mft_record > 3U)
			continue;
		if (i + 1U >= count ||
				!rh_wal_mft_pair_operations_valid(wal, &operations[i],
					&operations[i + 1U]))
			return 0;
		i++;
	}
	return 1;
}

static int rh_wal_prepare_plan(struct rh_wal *wal,
		const struct rh_write_operation *operations, size_t count,
		unsigned char output[32])
{
	unsigned char *manifest = NULL;
	uint32_t *action_ids = NULL;
	uint64_t cursor = RH_WAL_ENTRY_START;
	uint64_t target_total = 0;
	unsigned int dirty_set_count = 0;
	unsigned int dirty_clear_count = 0;
	size_t i, manifest_size;
	int result = -1;

	if (!wal || !operations || !count || count > RH_WAL_MAX_ENTRIES ||
		count > SIZE_MAX / RH_WAL_PLAN_BYTES) {
		errno = EINVAL;
		return -1;
	}
	rh_wal_free_planned(wal);
	wal->planned_entries = calloc(count, sizeof(*wal->planned_entries));
	if (!wal->planned_entries)
		return -1;
	wal->planned_count = count;
	manifest_size = count * RH_WAL_PLAN_BYTES;
	manifest = malloc(manifest_size);
	action_ids = malloc(count * sizeof(*action_ids));
	if (!manifest || !action_ids)
		goto out;
	for (i = 0; i < count; i++) {
		const struct rh_write_operation *operation = &operations[i];
		struct rh_wal_planned_entry *entry = &wal->planned_entries[i];
		uint64_t semantic_end, physical_end, relative;
		int excluded;

		if (operation->kind < 0 || operation->kind >= RH_WRITE_KIND_COUNT ||
			!operation->length || operation->offset > wal->writer->device_size ||
			operation->length > wal->writer->device_size - operation->offset ||
			!rh_write_operation_semantics_valid(operation, 1))
			goto invalid;
		semantic_end = operation->offset + operation->length;
		if (semantic_end > UINT64_MAX - (wal->sector_size - 1))
			goto overflow;
		entry->target_offset = operation->offset &
			~((uint64_t)wal->sector_size - 1);
		physical_end = (semantic_end + wal->sector_size - 1) &
			~((uint64_t)wal->sector_size - 1);
		if (physical_end > wal->writer->device_size ||
			physical_end <= entry->target_offset)
			goto invalid;
		entry->length = physical_end - entry->target_offset;
		entry->padded_length = entry->length;
		entry->kind = RH_WRITE_ACTION_ID(operation->kind);
		entry->target = operation->target;
		action_ids[i] = entry->kind;
		if (operation->kind == RH_WRITE_VOLUME_DIRTY_SET) {
			dirty_set_count++;
		} else if (operation->kind == RH_WRITE_VOLUME_DIRTY_CLEAR) {
			dirty_clear_count++;
		}
		if (entry->length > SIZE_MAX ||
			entry->length > RH_WAL_MAX_TARGET_BYTES - target_total ||
			cursor > RH_WAL_SIZE - RH_WAL_DESCRIPTOR_SIZE)
			goto capacity;
		entry->payload_offset = cursor + RH_WAL_DESCRIPTOR_SIZE;
		if (entry->length > RH_WAL_SIZE - entry->payload_offset)
			goto capacity;
		excluded = rh_writer_range_excluded(wal->writer,
			entry->target_offset, entry->length);
		if (excluded)
			goto invalid;
		entry->before = malloc((size_t)entry->length);
		entry->after = malloc((size_t)entry->length);
		if (!entry->before || !entry->after)
			goto out;
		if (rh_writer_staged_read(wal->writer, i, entry->target_offset,
				(size_t)entry->length, entry->before))
			goto out;
		memcpy(entry->after, entry->before, (size_t)entry->length);
		relative = operation->offset - entry->target_offset;
		if (relative > entry->length || operation->length >
				entry->length - relative ||
			memcmp(entry->before + relative, operation->before,
				operation->length))
			goto invalid;
		memcpy(entry->after + relative, operation->after, operation->length);
		rh_sha256(entry->before, (size_t)entry->length, entry->old_hash);
		rh_sha256(entry->after, (size_t)entry->length, entry->new_hash);
		rh_wal_descriptor_prefix(entry, i,
			manifest + i * RH_WAL_PLAN_BYTES);
		cursor = entry->payload_offset + entry->length;
		target_total += entry->length;
	}
	if (!rh_wal_validate_mft_operation_pairs(wal, operations, count) ||
		(wal->transaction_kind == RH_WAL_TX_DIRTY_CLEAR &&
		(count != 2 || dirty_clear_count != 2 || dirty_set_count ||
		 !rh_wal_dirty_pair_operations_valid(wal, &operations[0],
			&operations[1], 0))) ||
		(wal->transaction_kind == RH_WAL_TX_METADATA_REPAIR &&
			(dirty_clear_count ||
			 (dirty_set_count != 0 && dirty_set_count != 2) ||
			 (dirty_set_count == 2 &&
			  !rh_wal_dirty_pair_operations_valid(wal, &operations[0],
				&operations[1], 1)))) ||
		(wal->transaction_kind == RH_WAL_TX_METADATA_REPAIR &&
			!rh_wal_metadata_action_order_valid(action_ids, count)))
		goto invalid;
	rh_sha256(manifest, manifest_size, output);
	if (rh_all_zero(output, 32))
		goto invalid;
	result = 0;
	goto out;
capacity:
	errno = ENOSPC;
	goto out;
overflow:
	errno = EOVERFLOW;
	goto out;
invalid:
	errno = EINVAL;
out:
	free(manifest);
	free(action_ids);
	if (result)
		rh_wal_free_planned(wal);
	return result;
}

static int rh_wal_backend_begin(void *opaque,
		const struct rh_write_operation *operations, size_t count)
{
	struct rh_wal *wal = opaque;

	if (!wal || wal->state != RH_WAL_EMPTY || !count ||
		count > RH_WAL_MAX_ENTRIES ||
		wal->transaction_kind == RH_WAL_TX_NONE) {
		if (!errno)
			errno = EINVAL;
		return -1;
	}
	if (rh_wal_prepare_plan(wal, operations, count, wal->plan_hash)) {
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
		fprintf(stderr, "wal prepare plan failed kind=%d count=%zu errno=%d\n",
			(int)wal->transaction_kind, count, errno);
#endif
		return -1;
	}
	if (rh_random_uuid(wal->transaction_uuid)) {
		rh_wal_free_planned(wal);
		return -1;
	}
	wal->data_used = 0;
	wal->entry_count = 0;
	wal->target_bytes = 0;
	return rh_wal_publish(wal, RH_WAL_PREPARING, wal->transaction_kind,
		0, 0, 0, wal->transaction_uuid, wal->plan_hash);
}

static int rh_wal_backend_before_write(void *opaque, size_t ordinal,
		const struct rh_write_operation *operation)
{
	struct rh_wal *wal = opaque;
	struct rh_wal_planned_entry *entry;
	unsigned char descriptor[RH_WAL_DESCRIPTOR_SIZE];
	unsigned char descriptor_digest[32];
	unsigned char *current = NULL;
	uint64_t descriptor_offset, new_used, relative;
	int result = -1;
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
	const char *test_stage = "preflight";
#endif

	if (!wal || !operation || ordinal != wal->entry_count + 1 ||
		ordinal > wal->planned_count || !operation->length) {
		errno = EINVAL;
		return -1;
	}
	entry = &wal->planned_entries[ordinal - 1];
	if (entry->kind != (uint32_t)operation->kind + 1 ||
		operation->offset < entry->target_offset ||
		operation->offset - entry->target_offset > entry->length ||
		operation->length > entry->length -
			(operation->offset - entry->target_offset)) {
		errno = EINVAL;
		return -1;
	}
	relative = operation->offset - entry->target_offset;
	if (memcmp(entry->before + relative, operation->before,
			operation->length) ||
		memcmp(entry->after + relative, operation->after, operation->length)) {
		errno = EINVAL;
		return -1;
	}
	descriptor_offset = RH_WAL_ENTRY_START + wal->data_used;
	if (descriptor_offset > RH_WAL_SIZE - RH_WAL_DESCRIPTOR_SIZE ||
		entry->payload_offset != descriptor_offset + RH_WAL_DESCRIPTOR_SIZE ||
		entry->length > RH_WAL_SIZE - entry->payload_offset ||
		entry->length > RH_WAL_MAX_TARGET_BYTES - wal->target_bytes) {
		errno = ENOSPC;
		return -1;
	}
	new_used = wal->data_used + RH_WAL_DESCRIPTOR_SIZE + entry->length;
	current = malloc((size_t)entry->length);
	if (!current)
		return -1;
	if (rh_writer_current_read(wal->writer, entry->target_offset,
			(size_t)entry->length, current) ||
		memcmp(current, entry->before, (size_t)entry->length)) {
		errno = ESTALE;
		goto out;
	}
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
	test_stage = "undo";
#endif
	if (rh_wal_traced_write(wal, RH_WAL_TRACE_UNDO_PAYLOAD,
			entry->payload_offset, (size_t)entry->length, -1,
			wal->state, wal->state, entry->before))
		goto out;
	memset(descriptor, 0, sizeof(descriptor));
	rh_wal_descriptor_prefix(entry, ordinal - 1, descriptor);
	rh_sha256(descriptor, RH_WAL_DESCRIPTOR_DIGEST, descriptor_digest);
	memcpy(descriptor + RH_WAL_DESCRIPTOR_DIGEST, descriptor_digest,
		sizeof(descriptor_digest));
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
	test_stage = "descriptor";
#endif
	if (rh_wal_traced_write(wal, RH_WAL_TRACE_DESCRIPTOR,
			descriptor_offset, sizeof(descriptor), -1,
			wal->state, wal->state, descriptor))
		goto out;
	wal->data_used = new_used;
	wal->entry_count = ordinal;
	wal->target_bytes += entry->length;
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
	test_stage = "applying-state";
#endif
	result = rh_wal_publish(wal, RH_WAL_APPLYING, wal->transaction_kind,
		wal->data_used, wal->entry_count, wal->target_bytes,
		wal->transaction_uuid, wal->plan_hash);
out:
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
	if (result)
		fprintf(stderr, "wal before-write failed stage=%s ordinal=%zu errno=%d\n",
			test_stage, ordinal, errno);
#endif
	free(current);
	return result;
}

static int rh_wal_backend_after_write(void *opaque, size_t ordinal,
		const struct rh_write_operation *operation __attribute__((unused)))
{
	struct rh_wal *wal = opaque;
	struct rh_wal_planned_entry *entry;
	unsigned char *current;
	unsigned char digest[32];
	int result = -1;

	if (!wal || !ordinal || ordinal > wal->planned_count) {
		errno = EINVAL;
		return -1;
	}
	entry = &wal->planned_entries[ordinal - 1];
	current = malloc((size_t)entry->length);
	if (!current)
		return -1;
	if (rh_writer_current_read(wal->writer, entry->target_offset,
			(size_t)entry->length, current))
		goto out;
	rh_sha256(current, (size_t)entry->length, digest);
	if (memcmp(digest, entry->new_hash, sizeof(digest)) ||
		memcmp(current, entry->after, (size_t)entry->length)) {
		errno = EIO;
		goto out;
	}
	result = 0;
out:
	free(current);
	return result;
}

static int rh_wal_backend_barrier(void *opaque __attribute__((unused)),
		size_t completed __attribute__((unused)))
{
	return 0;
}

static int rh_wal_backend_finish(void *opaque, size_t completed)
{
	struct rh_wal *wal = opaque;

	if (!wal || completed != wal->entry_count ||
		completed != wal->planned_count ||
		wal->state != RH_WAL_APPLYING) {
		errno = EINVAL;
		return -1;
	}
	return rh_wal_publish(wal, RH_WAL_COMMITTED, wal->transaction_kind,
		wal->data_used, wal->entry_count, wal->target_bytes,
		wal->transaction_uuid, wal->plan_hash);
}

static void rh_wal_backend_abort(void *opaque, size_t completed __attribute__((unused)))
{
	struct rh_wal *wal = opaque;

	if (wal)
		(void)rh_wal_rollback(wal);
}

static const struct rh_write_backend_ops rh_wal_backend = {
	.persistent_undo = 1,
	.begin = rh_wal_backend_begin,
	.before_write = rh_wal_backend_before_write,
	.after_write = rh_wal_backend_after_write,
	.barrier = rh_wal_backend_barrier,
	.finish = rh_wal_backend_finish,
	.abort = rh_wal_backend_abort,
};

int rh_wal_install_backend(struct rh_wal *wal,
		enum rh_wal_transaction_kind transaction_kind)
{
	if (!wal || wal->state != RH_WAL_EMPTY ||
		(transaction_kind != RH_WAL_TX_METADATA_REPAIR &&
		 transaction_kind != RH_WAL_TX_DIRTY_CLEAR)) {
		errno = EINVAL;
		return -1;
	}
	free(wal->trace_actions);
	wal->trace_actions = NULL;
	wal->trace_count = 0;
	wal->trace_capacity = 0;
	rh_wal_free_planned(wal);
	wal->transaction_kind = transaction_kind;
	return rh_writer_set_backend(wal->writer, &rh_wal_backend, wal);
}

void rh_wal_uninstall_backend(struct rh_wal *wal)
{
	if (!wal || !wal->writer)
		return;
	wal->writer->backend = NULL;
	wal->writer->backend_opaque = NULL;
	rh_wal_free_planned(wal);
	/*
	 * The located run map is part of the WAL handle, not the installed write
	 * backend.  Recovery/acceptance immediately after a commit still needs it
	 * to reload the durable descriptors.  It is released when the WAL handle
	 * is empty again, never merely because a committed transaction has ended
	 * planning.
	 */
	if (wal->state == RH_WAL_EMPTY)
		rh_wal_free_runs(wal);
	if (wal->state == RH_WAL_EMPTY) {
		free(wal->trace_actions);
		wal->trace_actions = NULL;
		wal->trace_count = 0;
		wal->trace_capacity = 0;
	}
}

int rh_wal_register_action_verifier(struct rh_wal *wal, uint32_t action_id,
		rh_wal_action_verifier_fn verify)
{
	struct rh_wal_action_verifier_slot *slot;

	if (!wal || !wal->writer || !wal->observation ||
		wal->observation->valid != 1 || !verify || !action_id ||
		action_id > RH_WRITE_KIND_COUNT) {
		errno = EINVAL;
		return -1;
	}
	/*
	 * Native replay cannot be enabled by registering a digest-only callback.
	 * These IDs stay closed until the exact namespace/free-slot evidence ABI
	 * and a source-bound rederivation verifier are frozen together.
	 */
	if (action_id == RH_WRITE_ACTION_ID(RH_WRITE_LOGFILE_REDO) ||
		action_id == RH_WRITE_ACTION_ID(RH_WRITE_LOGFILE_RESTART)) {
		errno = EOPNOTSUPP;
		return -1;
	}
	slot = &wal->action_verifiers[action_id];
	if (slot->verify) {
		errno = EEXIST;
		return -1;
	}
	slot->verify = verify;
	return 0;
}

struct rh_wal_entry {
	uint64_t target_offset;
	uint64_t length;
	uint64_t payload_offset;
	uint64_t padded_length;
	uint32_t kind;
	unsigned char old_hash[32];
	unsigned char new_hash[32];
	struct rh_write_semantic_target target;
	unsigned char *old;
};

static void rh_wal_entries_free(struct rh_wal_entry *entries, size_t count)
{
	size_t i;

	if (!entries)
		return;
	for (i = 0; i < count; i++)
		free(entries[i].old);
	free(entries);
}

static int rh_wal_view_writer_init(struct rh_writer *view,
		const struct rh_writer *source, const struct rh_wal_entry *entries,
		size_t count, int pretransaction)
{
	size_t i;

	if (!view || !source || (count && !entries))
		return -1;
	*view = *source;
	view->write_fd = -1;
	view->operations = NULL;
	view->operation_count = 0;
	view->operation_capacity = 0;
	view->planned_bytes = 0;
	view->backend = NULL;
	view->backend_opaque = NULL;
	view->commit_started = 0;
	view->commit_completed = 0;
	if (!pretransaction || !count)
		return 0;
	view->operations = calloc(count, sizeof(*view->operations));
	if (!view->operations)
		return -1;
	view->operation_capacity = count;
	for (i = 0; i < count; i++) {
		const struct rh_wal_entry *entry = &entries[count - 1U - i];
		struct rh_write_operation *operation = &view->operations[i];

		operation->offset = entry->target_offset;
		operation->length = (size_t)entry->length;
		operation->after = malloc(operation->length);
		if (!operation->after)
			goto fail;
		memcpy(operation->after, entry->old, operation->length);
		view->operation_count++;
	}
	return 0;
fail:
	for (i = 0; i < view->operation_count; i++)
		free(view->operations[i].after);
	free(view->operations);
	view->operations = NULL;
	view->operation_count = 0;
	view->operation_capacity = 0;
	return -1;
}

/*
 * Bitmap planners intentionally emit one typed operation per changed bit.
 * Several changes in one bitmap byte therefore produce an ordered chain of
 * full-sector writes to the same physical range.  Only the last member of an
 * exact-range chain can match the committed postimage.  Partial or differently
 * bounded overlap remains outside the recovery ABI and fails closed.
 */
static int rh_wal_entry_has_later_exact_replacement(
		const struct rh_wal_entry *entries, size_t count, size_t index)
{
	const struct rh_wal_entry *entry;
	size_t i;
	int replaced = 0;

	if (!entries || index >= count)
		return -1;
	entry = &entries[index];
	for (i = index + 1U; i < count; i++) {
		const struct rh_wal_entry *later = &entries[i];
		int overlaps = entry->target_offset <= later->target_offset ?
			later->target_offset - entry->target_offset < entry->length :
			entry->target_offset - later->target_offset < later->length;

		if (!overlaps)
			continue;
		if (entry->target_offset != later->target_offset ||
				entry->length != later->length)
			return -1;
		replaced = 1;
	}
	return replaced;
}

static void rh_wal_view_writer_destroy(struct rh_writer *view)
{
	size_t i;

	if (!view)
		return;
	for (i = 0; i < view->operation_count; i++)
		free(view->operations[i].after);
	free(view->operations);
	view->operations = NULL;
	view->operation_count = 0;
	view->operation_capacity = 0;
}

struct rh_wal_preimage {
	struct rh_writer *writer;
	struct rh_wal *wal;
	struct rh_wal_entry *internal_entries;
	const unsigned char *const *old_payloads;
	size_t entry_count;
};

int rh_wal_preimage_create_free_slot_exclusion_seal(
		const struct rh_wal_preimage *preimage,
		uint64_t correlation_generation,
		struct rh_free_slot_component_seal **output)
{
	if (!preimage || !preimage->wal || !preimage->writer) {
		if (output)
			*output = NULL;
		errno = EINVAL;
		return -1;
	}
	return rh_wal_create_free_slot_exclusion_seal_common(preimage->wal,
		preimage->writer, 1, correlation_generation, output);
}

uint64_t rh_wal_preimage_size(const struct rh_wal_preimage *preimage)
{
	return preimage && preimage->writer ? preimage->writer->device_size : 0;
}

int rh_wal_preimage_read(const struct rh_wal_preimage *preimage,
		uint64_t offset, size_t length, void *buffer)
{
	if (!preimage || !preimage->writer || !buffer || !length ||
		offset > preimage->writer->device_size ||
		length > preimage->writer->device_size - offset) {
		errno = EINVAL;
		return -1;
	}
	return rh_writer_read(preimage->writer, offset, length, buffer);
}

int rh_wal_preimage_range_excluded(const struct rh_wal_preimage *preimage,
		uint64_t offset, uint64_t length, int *excluded)
{
	if (!preimage || !preimage->writer || !excluded || !length ||
			offset > preimage->writer->device_size ||
			length > preimage->writer->device_size - offset) {
		errno = EINVAL;
		return -1;
	}
	*excluded = rh_writer_range_excluded(preimage->writer, offset, length);
	return 0;
}

int rh_wal_entry_old_read(const struct rh_wal_action_verifier_context *context,
		uint64_t ordinal, uint64_t relative_offset, size_t length,
		void *buffer)
{
	const struct rh_wal_preimage *preimage;
	const struct rh_wal_recovery_entry_view *entry;

	if (!context || !context->preimage || !buffer || !length || !ordinal ||
		ordinal > context->entry_count) {
		errno = EINVAL;
		return -1;
	}
	preimage = context->preimage;
	if (preimage->entry_count != context->entry_count ||
		!preimage->old_payloads || !preimage->old_payloads[ordinal - 1U]) {
		errno = EINVAL;
		return -1;
	}
	entry = &context->entries[ordinal - 1U];
	if (entry->ordinal != ordinal || relative_offset > entry->length ||
		length > entry->length - relative_offset) {
		errno = EINVAL;
		return -1;
	}
	memcpy(buffer, preimage->old_payloads[ordinal - 1U] + relative_offset,
		length);
	return 0;
}

static int rh_wal_recovery_entry_view_valid(
		const struct rh_wal_recovery_entry_view *entry,
		const unsigned char *old_payload, const struct rh_writer *preimage)
{
	unsigned char digest[32];
	enum rh_write_kind kind;

	if (!entry || !old_payload || !preimage || !entry->ordinal ||
		!entry->action_id || entry->action_id > RH_WRITE_KIND_COUNT ||
		entry->reserved32 || !entry->length || entry->length > SIZE_MAX ||
		entry->target_offset > preimage->device_size ||
		entry->length > preimage->device_size - entry->target_offset ||
		entry->target.semantic_target_offset < entry->target_offset ||
		entry->target.semantic_target_offset - entry->target_offset >
			entry->length ||
		entry->target.semantic_target_length > entry->length -
			(entry->target.semantic_target_offset - entry->target_offset) ||
		entry->target.semantic_target_length > SIZE_MAX)
		return 0;
	kind = (enum rh_write_kind)(entry->action_id - 1U);
	if (!rh_write_semantic_target_valid(kind, &entry->target,
			((entry->target.object == RH_WRITE_TARGET_MFT_RECORD_PRIMARY ||
			  entry->target.object == RH_WRITE_TARGET_MFT_RECORD_MIRROR) &&
			 kind != RH_WRITE_VOLUME_DIRTY_SET &&
			 kind != RH_WRITE_VOLUME_DIRTY_CLEAR) ? entry->target_offset :
				entry->target.semantic_target_offset,
			((entry->target.object == RH_WRITE_TARGET_MFT_RECORD_PRIMARY ||
			  entry->target.object == RH_WRITE_TARGET_MFT_RECORD_MIRROR) &&
			 kind != RH_WRITE_VOLUME_DIRTY_SET &&
			 kind != RH_WRITE_VOLUME_DIRTY_CLEAR) ? (size_t)entry->length :
				(size_t)entry->target.semantic_target_length, 1))
		return 0;
	rh_sha256(old_payload, (size_t)entry->length, digest);
	if (memcmp(digest, entry->old_hash, sizeof(digest)))
		return 0;
	return !rh_write_semantic_payload_hash(kind, &entry->target,
		entry->target_offset, (size_t)entry->length, old_payload, digest) &&
		!memcmp(digest, entry->target.semantic_before_hash,
		sizeof(digest));
}

static int rh_wal_builtin_restart_pair_verify(struct rh_writer *preimage,
		const struct rh_wal_recovery_entry_view *entries,
		const struct rh_wal_entry *internal_entries, size_t count)
{
	struct rh_ntfs_overlay overlay;
	ntfs_inode *inode = NULL;
	ntfs_attr *attribute = NULL;
	RESTART_PAGE_HEADER *selected = NULL;
	RESTART_AREA area;
	LOG_CLIENT_RECORD log_client;
	unsigned char fixed[2][RH_WAL_HEADER_SIZE];
	unsigned char clean[RH_WAL_HEADER_SIZE], digest[32];
	LCN lcn[2];
	u64 logfile_size;
	uint16_t area_offset, client_offset;
	size_t i;
	int mounted = 0, result = -1;

	if (!preimage || !entries || !internal_entries || count != 2U)
		goto out;
	for (i = 0; i < count; ++i) {
		const struct rh_write_semantic_target *target = &entries[i].target;

		if (entries[i].action_id !=
				RH_WRITE_ACTION_ID(RH_WRITE_LOGFILE_RESTART) ||
				entries[i].length != RH_WAL_HEADER_SIZE ||
				target->logical_vcn != (int64_t)i ||
				target->logical_offset != i * RH_WAL_HEADER_SIZE ||
				target->logical_length != RH_WAL_HEADER_SIZE ||
				target->semantic_target_offset != entries[i].target_offset ||
				target->semantic_target_length != RH_WAL_HEADER_SIZE)
			goto out;
	}
	if (rh_ntfs_overlay_mount(&overlay, preimage, 0))
		goto out;
	mounted = 1;
	if (overlay.volume->cluster_size != RH_WAL_HEADER_SIZE)
		goto out;
	inode = ntfs_inode_open(overlay.volume, FILE_LogFile);
	if (!inode)
		goto out;
	attribute = ntfs_attr_open(inode, AT_DATA, AT_UNNAMED, 0);
	if (!attribute || !NAttrNonResident(attribute) ||
			attribute->data_size < 2 * RH_WAL_HEADER_SIZE ||
			ntfs_attr_map_whole_runlist(attribute))
		goto out;
	for (i = 0; i < count; ++i) {
		lcn[i] = ntfs_rl_vcn_to_lcn(attribute->rl, (VCN)i);
		if (lcn[i] < 0 || (u64)lcn[i] > UINT64_MAX / RH_WAL_HEADER_SIZE ||
				(u64)lcn[i] * RH_WAL_HEADER_SIZE != entries[i].target_offset ||
				entries[i].target.lcn != lcn[i])
			goto out;
	}
	logfile_size = (u64)attribute->data_size;
	for (i = 0; i < count; ++i) {
		RESTART_PAGE_HEADER *candidate;
		const RESTART_AREA *candidate_area;
		const RESTART_AREA *selected_area;

		memcpy(fixed[i], internal_entries[i].old, sizeof(fixed[i]));
		if (ntfs_mst_post_read_fixup((NTFS_RECORD *)fixed[i],
				sizeof(fixed[i])))
			continue;
		candidate = (RESTART_PAGE_HEADER *)fixed[i];
		if (!roothealth_restart_page_supported(candidate, logfile_size))
			continue;
		if (!selected) {
			selected = candidate;
			continue;
		}
		candidate_area = (const RESTART_AREA *)(fixed[i] +
			le16_to_cpu(candidate->restart_area_offset));
		selected_area = (const RESTART_AREA *)((const unsigned char *)selected +
			le16_to_cpu(selected->restart_area_offset));
		if ((s64)(sle64_to_cpu(candidate_area->current_lsn) -
				sle64_to_cpu(selected_area->current_lsn)) > 0)
			selected = candidate;
	}
	if (!selected)
		goto out;
	area_offset = le16_to_cpu(selected->restart_area_offset);
	memcpy(&area, (const unsigned char *)selected + area_offset,
		sizeof(area));
	client_offset = le16_to_cpu(area.client_array_offset);
	memcpy(&log_client, (const unsigned char *)selected + area_offset +
		client_offset, sizeof(log_client));
	area.client_in_use_list = LOGFILE_NO_CLIENT;
	area.client_free_list = const_cpu_to_le16(0);
	area.flags |= RESTART_VOLUME_IS_CLEAN;
	memset(clean, 0, sizeof(clean));
	memcpy(clean, selected, sizeof(*selected));
	memcpy(clean + area_offset, &area, sizeof(area));
	memcpy(clean + area_offset + client_offset, &log_client,
		sizeof(log_client));
	if (!roothealth_restart_page_supported(
			(RESTART_PAGE_HEADER *)clean, logfile_size) ||
			ntfs_mst_pre_write_fixup((NTFS_RECORD *)clean, sizeof(clean)))
		goto out;
	rh_sha256(clean, sizeof(clean), digest);
	for (i = 0; i < count; ++i)
		if (memcmp(digest, internal_entries[i].new_hash, sizeof(digest)) ||
				memcmp(digest, entries[i].target.semantic_after_hash,
					sizeof(digest)))
			goto out;
	result = 0;
out:
	if (attribute)
		ntfs_attr_close(attribute);
	if (inode)
		ntfs_inode_close(inode);
	if (mounted)
		rh_ntfs_overlay_unmount(&overlay);
	if (result)
		errno = EOPNOTSUPP;
	return result;
}

static int rh_wal_native_replay_view_init(struct rh_writer *view,
		const struct rh_writer *preimage)
{
	size_t i;

	if (!view || !preimage || preimage->write_fd >= 0 ||
			preimage->backend || preimage->backend_opaque)
		return -1;
	*view = *preimage;
	view->write_fd = -1;
	view->operations = NULL;
	view->operation_count = 0;
	view->operation_capacity = 0;
	view->planned_bytes = 0;
	view->backend = NULL;
	view->backend_opaque = NULL;
	view->commit_started = 0;
	view->commit_completed = 0;
	if (!preimage->operation_count)
		return 0;
	view->operations = calloc(preimage->operation_count,
		sizeof(*view->operations));
	if (!view->operations)
		return -1;
	view->operation_capacity = preimage->operation_count;
	for (i = 0; i < preimage->operation_count; ++i) {
		const struct rh_write_operation *source = &preimage->operations[i];
		struct rh_write_operation *target = &view->operations[i];

		if (!source->after || !source->length)
			goto fail;
		target->offset = source->offset;
		target->length = source->length;
		target->after = malloc(source->length);
		if (!target->after)
			goto fail;
		memcpy(target->after, source->after, source->length);
		view->operation_count++;
	}
	return 0;
fail:
	for (i = 0; i < view->operation_count; ++i)
		free(view->operations[i].after);
	free(view->operations);
	view->operations = NULL;
	view->operation_count = 0;
	view->operation_capacity = 0;
	return -1;
}

static void rh_wal_native_replay_view_destroy(struct rh_writer *view)
{
	size_t i;

	if (!view)
		return;
	for (i = 0; i < view->operation_count; ++i) {
		free(view->operations[i].before);
		free(view->operations[i].after);
	}
	free(view->operations);
	view->operations = NULL;
	view->operation_count = 0;
	view->operation_capacity = 0;
}

static int rh_wal_native_rederived_plan_hash(const struct rh_wal *wal,
		struct rh_writer *replay, size_t checkpoint, size_t count,
		unsigned char output[32])
{
	unsigned char *manifest = NULL;
	uint64_t cursor = RH_WAL_ENTRY_START;
	size_t manifest_size, i;
	int result = -1;

	if (!wal || !replay || !output || !count ||
			checkpoint > replay->operation_count ||
			count > replay->operation_count - checkpoint ||
			count > RH_WAL_MAX_ENTRIES ||
			count > SIZE_MAX / RH_WAL_PLAN_BYTES) {
		errno = EINVAL;
		return -1;
	}
	manifest_size = count * RH_WAL_PLAN_BYTES;
	manifest = malloc(manifest_size);
	if (!manifest)
		return -1;
	for (i = 0; i < count; ++i) {
		const struct rh_write_operation *operation =
			&replay->operations[checkpoint + i];
		struct rh_wal_planned_entry entry;
		uint64_t semantic_end, physical_end, relative;

		memset(&entry, 0, sizeof(entry));
		if (operation->kind < 0 || operation->kind >= RH_WRITE_KIND_COUNT ||
				!operation->length ||
				operation->offset > replay->device_size ||
				operation->length > replay->device_size - operation->offset ||
				!rh_write_operation_semantics_valid(operation, 1))
			goto out;
		semantic_end = operation->offset + operation->length;
		if (semantic_end > UINT64_MAX - (wal->sector_size - 1U))
			goto out;
		entry.target_offset = operation->offset &
			~((uint64_t)wal->sector_size - 1U);
		physical_end = (semantic_end + wal->sector_size - 1U) &
			~((uint64_t)wal->sector_size - 1U);
		if (physical_end > replay->device_size ||
				physical_end <= entry.target_offset)
			goto out;
		entry.length = physical_end - entry.target_offset;
		entry.padded_length = entry.length;
		entry.kind = RH_WRITE_ACTION_ID(operation->kind);
		entry.target = operation->target;
		if (entry.length > SIZE_MAX ||
				cursor > RH_WAL_SIZE - RH_WAL_DESCRIPTOR_SIZE) {
			errno = ENOSPC;
			goto out;
		}
		entry.payload_offset = cursor + RH_WAL_DESCRIPTOR_SIZE;
		if (entry.length > RH_WAL_SIZE - entry.payload_offset) {
			errno = ENOSPC;
			goto out;
		}
		entry.before = malloc((size_t)entry.length);
		entry.after = malloc((size_t)entry.length);
		if (!entry.before || !entry.after) {
			free(entry.before);
			free(entry.after);
			goto out;
		}
		if (rh_writer_staged_read(replay, checkpoint + i,
				entry.target_offset, (size_t)entry.length, entry.before)) {
			free(entry.before);
			free(entry.after);
			goto out;
		}
		memcpy(entry.after, entry.before, (size_t)entry.length);
		relative = operation->offset - entry.target_offset;
		if (relative > entry.length ||
				operation->length > entry.length - relative ||
				memcmp(entry.before + relative, operation->before,
					operation->length)) {
			free(entry.before);
			free(entry.after);
			goto out;
		}
		memcpy(entry.after + relative, operation->after, operation->length);
		rh_sha256(entry.before, (size_t)entry.length, entry.old_hash);
		rh_sha256(entry.after, (size_t)entry.length, entry.new_hash);
		rh_wal_descriptor_prefix(&entry, i,
			manifest + i * RH_WAL_PLAN_BYTES);
		cursor = entry.payload_offset + entry.length;
		free(entry.before);
		free(entry.after);
	}
	rh_sha256(manifest, manifest_size, output);
	result = rh_all_zero(output, 32U) ? -1 : 0;
out:
	free(manifest);
	if (result && !errno)
		errno = EINVAL;
	return result;
}

/*
 * Native recovery is one indivisible ID5/ID6 group.  Re-run the pinned native
 * parser against the WAL's virtual pre-transaction image, run the complete
 * T1OS census over the re-derived post-replay overlay, finalize every semantic
 * target from that fresh census, and require byte-for-byte equality with the
 * durable WAL descriptors.  No digest-only callback can authorize this path.
 */
static int rh_wal_builtin_native_replay_verify(struct rh_wal *wal,
		struct rh_writer *preimage,
		const struct rh_wal_recovery_entry_view *entries,
		const struct rh_wal_entry *internal_entries,
		const unsigned char *const *old_payloads, size_t count)
{
	struct rh_writer replay;
	struct rh_ntfs_overlay overlay;
	struct rh_log_result native;
	struct rh_census_reader reader;
	struct rh_complete_census_profile profile;
	struct rh_complete_census census;
	unsigned char rederived_plan_hash[32];
	uint64_t evidence_generation;
	size_t checkpoint = 0, full_count = 0, i = 0;
	int mounted = 0, census_ready = 0, result = -1;
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
	const char *test_stage = "shape";
#endif

	memset(&replay, 0, sizeof(replay));
	memset(&overlay, 0, sizeof(overlay));
	memset(&native, 0, sizeof(native));
	memset(&census, 0, sizeof(census));
	if (!wal || !preimage || !entries || !internal_entries || !old_payloads ||
			!count || wal->transaction_kind != RH_WAL_TX_METADATA_REPAIR)
		goto out;
	for (i = 0; i < count; ++i) {
		if (entries[i].ordinal != i + 1U ||
				(entries[i].action_id !=
					RH_WRITE_ACTION_ID(RH_WRITE_LOGFILE_REDO) &&
				 entries[i].action_id !=
					RH_WRITE_ACTION_ID(RH_WRITE_LOGFILE_RESTART)) ||
				!old_payloads[i] || !entries[i].target.finalized)
			goto out;
	}
	evidence_generation = entries[0].target.evidence_generation;
	if (evidence_generation < 2U)
		goto out;
	for (i = 1; i < count; ++i)
		if (entries[i].target.evidence_version !=
				entries[0].target.evidence_version ||
			entries[i].target.evidence_generation != evidence_generation)
			goto out;
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
	test_stage = "preimage-view";
#endif
	if (rh_wal_native_replay_view_init(&replay, preimage))
		goto out;
	checkpoint = replay.operation_count;
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
	test_stage = "preimage-mount";
#endif
	if (checkpoint != count || rh_ntfs_overlay_mount(&overlay, &replay, 0))
		goto out;
	mounted = 1;
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
	test_stage = "rederive";
#endif
	if (roothealth_log_replay_plan_mounted(overlay.volume, &replay,
			checkpoint, &native) ||
			native.state != RH_NATIVE_LOG_REPLAY_PLANNED ||
			native.io_errors || native.parse_errors || native.unsupported_actions ||
			native.restart_pages_planned != 2U ||
			!native.planned_io_operations ||
			native.planned_io_operations > SIZE_MAX ||
			replay.operation_count != checkpoint +
				(size_t)native.planned_io_operations)
		goto out;
	full_count = (size_t)native.planned_io_operations;
	if (full_count < 3U || count > full_count)
		goto out;
	for (i = 0; i < full_count; ++i) {
		uint32_t expected = i + 2U < full_count ?
			RH_WRITE_ACTION_ID(RH_WRITE_LOGFILE_REDO) :
			RH_WRITE_ACTION_ID(RH_WRITE_LOGFILE_RESTART);

		if (RH_WRITE_ACTION_ID(replay.operations[checkpoint + i].kind) !=
				expected)
			goto out;
	}
	rh_ntfs_overlay_unmount(&overlay);
	mounted = 0;
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
	test_stage = "census";
#endif
	memset(&profile, 0, sizeof(profile));
	profile.expected_volume_serial = wal->volume_serial;
	profile.roothealth_record = wal->journal_record;
	profile.roothealth_sequence = wal->journal_sequence;
	profile.require_t1os_identity = 1;
	if (rh_census_reader_from_writer_prefix(&replay, replay.operation_count,
			&reader) || rh_complete_census_run(&reader, &profile,
				evidence_generation - 1U, &census))
		goto out;
	census_ready = 1;
	if (!census.providers_complete || !census.coverage.complete ||
			!rh_coverage_is_clean(&census.coverage))
		goto out;
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
	test_stage = "finalize";
#endif
	for (i = 0; i < full_count; ++i)
		if (rh_writer_finalize_target(&replay, checkpoint + i + 1U,
				entries[0].target.evidence_version, evidence_generation,
				census.cluster_bitmap.census_hash,
				census.cluster_bitmap.census_hash))
			goto out;
	if (rh_wal_native_rederived_plan_hash(wal, &replay, checkpoint,
			full_count, rederived_plan_hash) ||
			memcmp(rederived_plan_hash, wal->plan_hash,
				sizeof(rederived_plan_hash)))
		goto out;
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
	test_stage = "compare";
#endif
	for (i = 0; i < count; ++i) {
		const struct rh_write_operation *operation =
			&replay.operations[checkpoint + i];
		unsigned char digest[32];

		if (operation->kind !=
				(enum rh_write_kind)(entries[i].action_id - 1U) ||
			operation->offset != entries[i].target_offset ||
			operation->length != entries[i].length || !operation->before ||
			!operation->after || memcmp(operation->before, old_payloads[i],
				operation->length) ||
			memcmp(&operation->target, &entries[i].target,
				sizeof(operation->target)))
			goto out;
		rh_sha256(operation->after, operation->length, digest);
		if (memcmp(digest, entries[i].new_hash, sizeof(digest)) ||
				memcmp(digest, internal_entries[i].new_hash, sizeof(digest)))
			goto out;
	}
	result = 0;
out:
	if (census_ready)
		rh_complete_census_release(&census);
	if (mounted)
		rh_ntfs_overlay_unmount(&overlay);
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
	if (result)
		fprintf(stderr, "native WAL replay verifier failed stage=%s "
			"entry=%zu checkpoint=%zu full=%zu operations=%zu native-state=%d "
			"native-operations=%"PRIu64" parse=%u unsupported=%u io=%u "
			"errno=%d\n", test_stage, i, checkpoint, full_count,
			replay.operation_count, native.state, native.planned_io_operations,
			native.parse_errors, native.unsupported_actions, native.io_errors,
			errno);
#endif
	rh_wal_native_replay_view_destroy(&replay);
	if (result && !errno)
		errno = EOPNOTSUPP;
	return result;
}

static int rh_wal_callback_errno(int value)
{
	switch (value) {
	case EIO:
	case ENXIO:
	case ENODEV:
	case ENOMEM:
	case EINVAL:
	case EOPNOTSUPP:
		return value;
	default:
		return EINVAL;
	}
}

/*
 * Dispatch only after proving that every distinct action ID has an exact
 * verifier.  Callbacks receive opaque, bounded read access only.  The deep
 * snapshots below still catch mutation through an accidental caller closure
 * before recovery can write a sector.
 */
static int rh_wal_dispatch_action_verifiers(struct rh_wal *wal,
		struct rh_writer *preimage,
		const struct rh_wal_recovery_entry_view *entries,
		const unsigned char *const *old_payloads,
		struct rh_wal_entry *internal_entries, size_t count)
{
	struct rh_wal_recovery_entry_view *entry_snapshot = NULL;
	struct rh_write_operation *operation_snapshot = NULL;
	struct rh_writer writer_snapshot;
	struct rh_wal_preimage preimage_handle;
	struct rh_wal_preimage preimage_snapshot;
	struct rh_wal wal_snapshot;
	unsigned char seen[RH_WRITE_KIND_COUNT + 1U];
	unsigned char processed[RH_WRITE_KIND_COUNT + 1U];
	size_t i;
	int result = -1;

	if (!wal || !preimage || !entries || !old_payloads || !count ||
		count > RH_WAL_MAX_ENTRIES || preimage->write_fd >= 0 ||
		preimage->backend || preimage->backend_opaque ||
		preimage->commit_started || preimage->commit_completed ||
		preimage->operation_count != count) {
		errno = EINVAL;
		return -1;
	}
	memset(seen, 0, sizeof(seen));
	memset(processed, 0, sizeof(processed));
	for (i = 0; i < count; i++) {
		const struct rh_wal_recovery_entry_view *entry = &entries[i];
		const struct rh_write_operation *operation =
			&preimage->operations[count - 1U - i];

		if (!rh_wal_recovery_entry_view_valid(entry, old_payloads[i],
				preimage) || entry->ordinal != i + 1U || !operation->after ||
			operation->offset != entry->target_offset ||
			operation->length != entry->length ||
			memcmp(operation->after, old_payloads[i],
				(size_t)entry->length)) {
			errno = EINVAL;
			return -1;
		}
		seen[entry->action_id] = 1U;
	}
	if (seen[RH_WRITE_ACTION_ID(RH_WRITE_LOGFILE_REDO)]) {
		for (i = 1; i <= RH_WRITE_KIND_COUNT; ++i)
			if (seen[i] && i != RH_WRITE_ACTION_ID(RH_WRITE_LOGFILE_REDO) &&
					i != RH_WRITE_ACTION_ID(RH_WRITE_LOGFILE_RESTART)) {
				errno = EOPNOTSUPP;
				return -1;
			}
		return rh_wal_builtin_native_replay_verify(wal, preimage,
			entries, internal_entries, old_payloads, count);
	}
	if (seen[RH_WRITE_ACTION_ID(RH_WRITE_LOGFILE_RESTART)]) {
		for (i = 1; i <= RH_WRITE_KIND_COUNT; ++i)
			if (seen[i] && i !=
					RH_WRITE_ACTION_ID(RH_WRITE_LOGFILE_RESTART)) {
				errno = EOPNOTSUPP;
				return -1;
			}
		return rh_wal_builtin_restart_pair_verify(preimage, entries,
			internal_entries, count);
	}
	/* Registration is all-or-nothing for every non-native action family. */
	for (i = 1; i <= RH_WRITE_KIND_COUNT; i++) {
		if (!seen[i])
			continue;
		if (i == RH_WRITE_ACTION_ID(RH_WRITE_LOGFILE_REDO) ||
			!wal->action_verifiers[i].verify) {
			errno = EOPNOTSUPP;
			return -1;
		}
	}
	entry_snapshot = malloc(count * sizeof(*entry_snapshot));
	operation_snapshot = malloc(count * sizeof(*operation_snapshot));
	if (!entry_snapshot || !operation_snapshot) {
		if (!errno)
			errno = ENOMEM;
		goto out;
	}
	memcpy(entry_snapshot, entries, count * sizeof(*entry_snapshot));
	memcpy(operation_snapshot, preimage->operations,
		count * sizeof(*operation_snapshot));
	writer_snapshot = *preimage;
	wal_snapshot = *wal;
	memset(&preimage_handle, 0, sizeof(preimage_handle));
	preimage_handle.writer = preimage;
	preimage_handle.wal = wal;
	preimage_handle.internal_entries = internal_entries;
	preimage_handle.old_payloads = old_payloads;
	preimage_handle.entry_count = count;
	preimage_snapshot = preimage_handle;
	for (i = 1; i <= RH_WRITE_KIND_COUNT; i++) {
		struct rh_wal_action_verifier_context context;
		struct rh_wal_action_verifier_context context_snapshot;
		rh_wal_action_verifier_fn verify;
		size_t j;
		int callback_errno;
		int callback_result;

		if (!seen[i] || processed[i])
			continue;
		verify = wal->action_verifiers[i].verify;
		memset(&context, 0, sizeof(context));
		context.version = RH_WAL_ACTION_VERIFIER_ABI_VERSION;
		context.action_id = (uint32_t)i;
		context.transaction_kind = wal->transaction_kind;
		context.state = wal->state;
		context.generation = wal->generation;
		context.volume_serial = wal->volume_serial;
		context.journal_record = wal->journal_record;
		context.journal_sequence = wal->journal_sequence;
		memcpy(context.journal_uuid, wal->journal_uuid,
			sizeof(context.journal_uuid));
		memcpy(context.transaction_uuid, wal->transaction_uuid,
			sizeof(context.transaction_uuid));
		memcpy(context.plan_hash, wal->plan_hash,
			sizeof(context.plan_hash));
		context.preimage = &preimage_handle;
		context.entries = entries;
		context.entry_count = count;
		context_snapshot = context;
		errno = 0;
		callback_result = verify(&context);
		callback_errno = errno;
		if (callback_result) {
			errno = rh_wal_callback_errno(callback_errno);
			goto out;
		}
		if (memcmp(&context, &context_snapshot, sizeof(context)) ||
			memcmp(&preimage_handle, &preimage_snapshot,
				sizeof(preimage_handle)) ||
			memcmp(wal, &wal_snapshot, sizeof(*wal)) ||
			memcmp(preimage, &writer_snapshot, sizeof(*preimage)) ||
			memcmp(entries, entry_snapshot,
				count * sizeof(*entry_snapshot)) ||
			memcmp(preimage->operations, operation_snapshot,
				count * sizeof(*operation_snapshot))) {
			errno = EINVAL;
			goto out;
		}
		for (j = 0; j < count; j++) {
			unsigned char digest[32];

			rh_sha256(old_payloads[j], (size_t)entries[j].length, digest);
			if (memcmp(digest, entry_snapshot[j].old_hash,
					sizeof(digest)) ||
				memcmp(preimage->operations[count - 1U - j].after,
					old_payloads[j], (size_t)entries[j].length)) {
				errno = EINVAL;
				goto out;
			}
		}
		for (j = i; j <= RH_WRITE_KIND_COUNT; j++)
			if (seen[j] && wal->action_verifiers[j].verify == verify)
				processed[j] = 1U;
	}
	errno = 0;
	result = 0;
out:
	free(operation_snapshot);
	free(entry_snapshot);
	return result;
}

#ifdef ROOTHEALTH_WAL_TEST_HOOKS
int rh_wal_test_dispatch_action_verifiers(struct rh_wal *wal,
		struct rh_writer *preimage,
		const struct rh_wal_recovery_entry_view *entries,
		const unsigned char *const *old_payloads, size_t count)
{
	return rh_wal_dispatch_action_verifiers(wal, preimage, entries,
		old_payloads, NULL, count);
}
#endif

static int rh_wal_entry_expected_after(const struct rh_wal_entry *entry,
		const void *semantic_after, size_t semantic_length)
{
	unsigned char semantic_hash[32], full_hash[32];
	unsigned char *full;
	uint64_t relative;
	int result = 0;

	if (!entry || !semantic_after || !semantic_length ||
			semantic_length != entry->target.semantic_target_length ||
			entry->target.semantic_target_offset < entry->target_offset)
		return 0;
	relative = entry->target.semantic_target_offset - entry->target_offset;
	if (relative > entry->length || semantic_length > entry->length - relative)
		return 0;
	rh_sha256(semantic_after, semantic_length, semantic_hash);
	if (memcmp(semantic_hash, entry->target.semantic_after_hash, 32))
		return 0;
	full = malloc((size_t)entry->length);
	if (!full)
		return 0;
	memcpy(full, entry->old, (size_t)entry->length);
	memcpy(full + relative, semantic_after, semantic_length);
	rh_sha256(full, (size_t)entry->length, full_hash);
	result = !memcmp(full_hash, entry->new_hash, sizeof(full_hash));
	free(full);
	return result;
}

static int rh_wal_bitmap_entry_valid(
		const struct rh_cluster_bitmap_census *census,
		const struct rh_wal_entry *entry, unsigned char *matched)
{
	const struct rh_write_semantic_target *target = &entry->target;
	unsigned char unnamed_hash[32];
	size_t i;

	rh_sha256("", 0, unnamed_hash);
	if (!census || !entry || !matched ||
			entry->kind != RH_WRITE_ACTION_ID(RH_WRITE_BITMAP_CLUSTER) ||
			target->evidence_version != 1 ||
			memcmp(target->evidence_hash, census->census_hash, 32) ||
			target->object != RH_WRITE_TARGET_NONRESIDENT_ATTRIBUTE ||
			target->owner_mft_record != FILE_Bitmap ||
			target->owner_sequence != census->bitmap_sequence ||
			target->attribute_instance != census->bitmap_attribute_instance ||
			target->attribute_type != 0x80U ||
			target->attribute_name_length ||
			memcmp(target->attribute_name_hash, unnamed_hash, 32) ||
			(target->flags != (RH_WRITE_TARGET_NONRESIDENT |
			 RH_WRITE_TARGET_SET_ONLY) &&
			 target->flags != (RH_WRITE_TARGET_NONRESIDENT |
			 RH_WRITE_TARGET_CLEAR_ONLY)))
		return 0;
	for (i = 0; i < census->change_count; i++) {
		const struct rh_cluster_bitmap_change *change = &census->changes[i];
		uint16_t flags = RH_WRITE_TARGET_NONRESIDENT |
			(change->set_mask ? RH_WRITE_TARGET_SET_ONLY :
			 RH_WRITE_TARGET_CLEAR_ONLY);

		if (matched[i] || target->flags != flags ||
				target->semantic_target_offset !=
				change->physical_offset || target->semantic_target_length != 1 ||
				target->lowest_vcn != 0 || target->logical_vcn < 0 ||
				(uint64_t)target->logical_vcn != change->logical_vcn ||
				target->logical_offset != change->logical_offset ||
				target->logical_length != 1 || target->lcn < 0 ||
				(uint64_t)target->lcn != change->lcn ||
				!rh_wal_entry_expected_after(entry, &change->after, 1))
			continue;
		matched[i] = 1;
		return 1;
	}
	return 0;
}

static int rh_wal_mft_bitmap_entry_valid(
		const struct rh_mft_bitmap_census *census,
		const struct rh_wal_entry *entry, unsigned char *matched)
{
	const struct rh_write_semantic_target *target = &entry->target;
	unsigned char unnamed_hash[32];
	size_t i;

	rh_sha256("", 0, unnamed_hash);
	if (!census || !entry || !matched ||
			entry->kind != RH_WRITE_ACTION_ID(RH_WRITE_BITMAP_MFT) ||
			target->evidence_version != 1U ||
			memcmp(target->evidence_hash, census->census_hash, 32U) ||
			target->object != RH_WRITE_TARGET_NONRESIDENT_ATTRIBUTE ||
			target->owner_mft_record != FILE_MFT ||
			target->owner_sequence != census->mft_sequence ||
			target->attribute_instance != census->bitmap_attribute_instance ||
			target->attribute_type != AT_BITMAP ||
			target->attribute_name_length ||
			memcmp(target->attribute_name_hash, unnamed_hash, 32U) ||
			(target->flags != (RH_WRITE_TARGET_NONRESIDENT |
			 RH_WRITE_TARGET_SET_ONLY) &&
			 target->flags != (RH_WRITE_TARGET_NONRESIDENT |
			 RH_WRITE_TARGET_CLEAR_ONLY)))
		return 0;
	for (i = 0; i < census->change_count; i++) {
		const struct rh_mft_bitmap_change *change = &census->changes[i];
		uint16_t flags = RH_WRITE_TARGET_NONRESIDENT |
			(change->set_mask ? RH_WRITE_TARGET_SET_ONLY :
			 RH_WRITE_TARGET_CLEAR_ONLY);

		if (matched[i] || target->flags != flags ||
				target->semantic_target_offset != change->physical_offset ||
				target->semantic_target_length != 1U ||
				target->lowest_vcn != 0 || target->logical_vcn < 0 ||
				(uint64_t)target->logical_vcn != change->logical_vcn ||
				target->logical_offset != change->logical_offset ||
				target->logical_length != 1U || target->lcn < 0 ||
				(uint64_t)target->lcn != change->lcn ||
				!rh_wal_entry_expected_after(entry, &change->after, 1U))
			continue;
		matched[i] = 1U;
		return 1;
	}
	return 0;
}

static int rh_wal_index_resident_expected_after(
		const struct rh_wal_entry *entry,
		const struct rh_index_bitmap_change *change)
{
	unsigned char semantic_hash[32], full_hash[32];
	unsigned char *record;
	MFT_RECORD *mft = NULL;
	int valid = 0;
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
	const char *stage = "shape";
#endif

	if (!entry || !change || entry->length != 1024U ||
			change->physical_length != entry->length ||
			change->resident_record_offset != entry->target_offset ||
			change->resident_value_offset >= entry->length)
		return 0;
	record = malloc((size_t)entry->length);
	if (!record)
		return 0;
	memcpy(record, entry->old, (size_t)entry->length);
	#ifdef ROOTHEALTH_WAL_TEST_HOOKS
	stage = "post-fixup";
	#endif
	if (ntfs_mst_post_read_fixup((NTFS_RECORD *)record, (u32)entry->length))
		goto out;
	#ifdef ROOTHEALTH_WAL_TEST_HOOKS
	stage = "identity";
	#endif
	mft = (MFT_RECORD *)record;
	if (mft->magic != magic_FILE ||
			le32_to_cpu(mft->mft_record_number) != change->owner_mft_record ||
			le16_to_cpu(mft->sequence_number) != change->owner_sequence ||
			record[change->resident_value_offset] != change->before)
		goto out;
	rh_sha256(&change->before, 1U, semantic_hash);
	#ifdef ROOTHEALTH_WAL_TEST_HOOKS
	stage = "before-hash";
	#endif
	if (memcmp(semantic_hash, entry->target.semantic_before_hash, 32U))
		goto out;
	record[change->resident_value_offset] = change->after;
	rh_sha256(&change->after, 1U, semantic_hash);
	#ifdef ROOTHEALTH_WAL_TEST_HOOKS
	stage = "after-hash-fixup";
	#endif
	if (memcmp(semantic_hash, entry->target.semantic_after_hash, 32U) ||
			ntfs_mst_pre_write_fixup((NTFS_RECORD *)record,
				(u32)entry->length))
		goto out;
	rh_sha256(record, (size_t)entry->length, full_hash);
	#ifdef ROOTHEALTH_WAL_TEST_HOOKS
	stage = "full-hash";
	#endif
	valid = !memcmp(full_hash, entry->new_hash, sizeof(full_hash));
out:
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
	if (!valid)
		fprintf(stderr, "index resident expected-after failed stage=%s "
			"record=%u/%u expected=%llu/%u byte=%u->%u\n", stage,
			mft ? le32_to_cpu(mft->mft_record_number) : 0U,
			mft ? le16_to_cpu(mft->sequence_number) : 0U,
			(unsigned long long)change->owner_mft_record,
			change->owner_sequence, change->before, change->after);
#endif
	free(record);
	return valid;
}

static int rh_wal_index_bitmap_entry_valid(
		const struct rh_index_bitmap_census *census,
		const struct rh_wal_entry *entry, unsigned char *matched)
{
	const struct rh_write_semantic_target *target = &entry->target;
	unsigned char i30_hash[32];
	static const unsigned char i30_name[] = {'$', 0, 'I', 0, '3', 0, '0', 0};
	size_t i;

	rh_sha256(i30_name, sizeof(i30_name), i30_hash);
	if (!census || !entry || !matched ||
			entry->kind != RH_WRITE_ACTION_ID(RH_WRITE_INDEX_BITMAP) ||
			target->evidence_version != RH_INDEX_BITMAP_EVIDENCE_VERSION ||
			memcmp(target->evidence_hash, census->census_hash, 32U) ||
			target->attribute_type != AT_BITMAP ||
			target->attribute_name_length != 4U ||
			memcmp(target->attribute_name_hash, i30_hash, 32U) ||
			!(target->flags & RH_WRITE_TARGET_SET_ONLY) ||
			(target->flags & RH_WRITE_TARGET_CLEAR_ONLY))
		return 0;
	for (i = 0; i < census->change_count; i++) {
		const struct rh_index_bitmap_change *change = &census->changes[i];
		int expected;

		if (matched[i] || !change->set_mask || change->clear_mask ||
				target->owner_mft_record != change->owner_mft_record ||
				target->owner_sequence != change->owner_sequence ||
				target->attribute_instance != change->bitmap_instance ||
				target->logical_offset != change->logical_offset ||
				target->logical_length != 1U ||
				target->semantic_target_length != 1U ||
				target->semantic_target_offset !=
					(change->storage == RH_INDEX_BITMAP_RESIDENT_MFT ?
					 change->resident_record_offset +
					 change->resident_value_offset : change->physical_offset))
			continue;
		if (change->storage == RH_INDEX_BITMAP_RESIDENT_MFT) {
			expected = target->object == RH_WRITE_TARGET_MFT_RECORD_PRIMARY &&
				target->flags == (RH_WRITE_TARGET_PRIMARY |
				 RH_WRITE_TARGET_RESIDENT | RH_WRITE_TARGET_SET_ONLY) &&
				target->lowest_vcn == -1 && target->logical_vcn == -1 &&
				target->lcn == -1 &&
				rh_wal_index_resident_expected_after(entry, change);
		} else {
			expected = target->object ==
				RH_WRITE_TARGET_NONRESIDENT_ATTRIBUTE &&
				target->flags == (RH_WRITE_TARGET_NONRESIDENT |
				 RH_WRITE_TARGET_SET_ONLY) &&
				target->lowest_vcn == change->lowest_vcn &&
				target->logical_vcn == change->logical_vcn &&
				target->lcn == change->lcn &&
				rh_wal_entry_expected_after(entry, &change->after, 1U);
		}
		if (!expected)
			continue;
		matched[i] = 1U;
		return 1;
	}
	return 0;
}

static int rh_wal_operations_registry_entry_valid(
		const struct rh_census_reader *reader,
		const struct rh_complete_census *census,
		const struct rh_wal_entry *entry)
{
	struct rh_namespace_repair_candidate candidate;
	struct rh_write_semantic_target expected;
	unsigned char before[1024], after[1024];
	unsigned char before_hash[32], after_hash[32];
	unsigned char semantic_before[32], semantic_after[32];

	if (!reader || !census || !entry ||
			entry->kind != RH_WRITE_ACTION_ID(RH_WRITE_INDEX_ROOT) ||
			entry->length != sizeof(before) ||
			rh_namespace_operations_registry_derive(reader, census, &candidate,
				before, after, &expected))
		return 0;
	rh_sha256(before, sizeof(before), before_hash);
	rh_sha256(after, sizeof(after), after_hash);
	if (memcmp(before, entry->old, sizeof(before)) ||
			memcmp(before_hash, entry->old_hash, 32U) ||
			memcmp(after_hash, entry->new_hash, 32U) ||
			entry->target_offset != candidate.physical_record_offset ||
			entry->target.evidence_version !=
				RH_NAMESPACE_REPAIR_EVIDENCE_VERSION ||
			entry->target.evidence_generation != census->generation ||
			memcmp(entry->target.evidence_hash, candidate.evidence_hash, 32U) ||
			entry->target.object != expected.object ||
			entry->target.owner_mft_record != expected.owner_mft_record ||
			entry->target.owner_sequence != expected.owner_sequence ||
			entry->target.attribute_instance != expected.attribute_instance ||
			entry->target.attribute_type != expected.attribute_type ||
			entry->target.attribute_name_length != expected.attribute_name_length ||
			entry->target.flags != expected.flags ||
			memcmp(entry->target.attribute_name_hash,
				expected.attribute_name_hash, 32U) ||
			entry->target.lowest_vcn != expected.lowest_vcn ||
			entry->target.logical_vcn != expected.logical_vcn ||
			entry->target.lcn != expected.lcn ||
			entry->target.logical_offset != expected.logical_offset ||
			entry->target.logical_length != expected.logical_length ||
			entry->target.semantic_target_offset !=
				expected.semantic_target_offset ||
			entry->target.semantic_target_length !=
				expected.semantic_target_length)
		return 0;
	if (rh_write_semantic_payload_hash(RH_WRITE_INDEX_ROOT, &expected,
			candidate.physical_record_offset, sizeof(before), before,
			semantic_before) ||
			rh_write_semantic_payload_hash(RH_WRITE_INDEX_ROOT, &expected,
				candidate.physical_record_offset, sizeof(after), after,
				semantic_after))
		return 0;
	return !memcmp(semantic_before, entry->target.semantic_before_hash, 32U) &&
		!memcmp(semantic_after, entry->target.semantic_after_hash, 32U);
}

static int rh_wal_dirty_entry_valid(const struct rh_wal_entry *entry,
		const struct rh_volume_dirty_pair *pair, int mirror)
{
	le16 after = cpu_to_le16(pair->flags_after);
	unsigned char unnamed_hash[32];
	const struct rh_write_semantic_target *target = &entry->target;
	uint64_t expected_offset = mirror ? pair->mirror_flag_offset :
		pair->primary_flag_offset;
	uint16_t expected_flags = (mirror ? RH_WRITE_TARGET_MIRROR :
		RH_WRITE_TARGET_PRIMARY) | RH_WRITE_TARGET_RESIDENT |
		(pair->requested_dirty ? RH_WRITE_TARGET_SET_ONLY :
		 RH_WRITE_TARGET_CLEAR_ONLY);

	rh_sha256("", 0, unnamed_hash);
	return target->evidence_version == 1 &&
		target->object == (mirror ? RH_WRITE_TARGET_MFT_RECORD_MIRROR :
			RH_WRITE_TARGET_MFT_RECORD_PRIMARY) &&
		target->owner_mft_record == FILE_Volume &&
		target->owner_sequence == pair->sequence &&
		target->attribute_instance == pair->attribute_instance &&
		target->attribute_type == 0x70U &&
		!target->attribute_name_length &&
		!memcmp(target->attribute_name_hash, unnamed_hash, 32) &&
		target->flags == expected_flags &&
		target->lowest_vcn == -1 && target->logical_vcn == -1 &&
		target->logical_offset == offsetof(VOLUME_INFORMATION, flags) &&
		target->logical_length == sizeof(after) && target->lcn == -1 &&
		target->semantic_target_offset == expected_offset &&
		target->semantic_target_length == sizeof(after) &&
		rh_wal_entry_expected_after(entry, &after, sizeof(after));
}

static int rh_wal_validate_legacy_recovery_targets(struct rh_wal *wal,
		struct rh_wal_entry *entries, size_t count)
{
	struct rh_writer pre_writer, post_writer;
	struct rh_ntfs_overlay pre_overlay, post_overlay;
	struct rh_cluster_bitmap_census pre_census, post_census;
	struct rh_raw_mft_census pre_raw, post_raw;
	struct rh_mft_bitmap_census pre_mft, post_mft;
	struct rh_index_bitmap_census pre_index, post_index;
	struct rh_complete_census pre_complete, post_complete;
	struct rh_complete_census_profile complete_profile;
	struct rh_census_reader pre_reader, post_reader;
	struct rh_volume_dirty_pair dirty_pair;
	unsigned char *matched = NULL;
	unsigned char *mft_matched = NULL, *index_matched = NULL;
	size_t i, bitmap_entries = 0, mft_entries = 0, index_entries = 0;
	size_t dirty_entries = 0, namespace_entries = 0;
	uint64_t evidence_generation;
	int pre_mounted = 0, post_mounted = 0, pre_initialized = 0;
	int post_initialized = 0, result = -1, set_dirty;
	int post_cluster_result;
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
	const char *test_stage = "arguments";
#endif

	memset(&pre_census, 0, sizeof(pre_census));
	memset(&post_census, 0, sizeof(post_census));
	memset(&pre_raw, 0, sizeof(pre_raw));
	memset(&post_raw, 0, sizeof(post_raw));
	memset(&pre_mft, 0, sizeof(pre_mft));
	memset(&post_mft, 0, sizeof(post_mft));
	memset(&pre_index, 0, sizeof(pre_index));
	memset(&post_index, 0, sizeof(post_index));
	memset(&pre_complete, 0, sizeof(pre_complete));
	memset(&post_complete, 0, sizeof(post_complete));
	memset(&complete_profile, 0, sizeof(complete_profile));
	if (!wal || !entries || !count)
		return -1;
	evidence_generation = 0;
	for (i = 0; i < count; i++) {
		enum rh_write_kind kind =
			(enum rh_write_kind)(entries[i].kind - 1U);

		if (kind != RH_WRITE_INDEX_ROOT && kind != RH_WRITE_INDEX_BITMAP &&
			kind != RH_WRITE_BITMAP_MFT &&
			kind != RH_WRITE_BITMAP_CLUSTER &&
			kind != RH_WRITE_VOLUME_DIRTY_SET &&
			kind != RH_WRITE_VOLUME_DIRTY_CLEAR)
			continue;
		if (!evidence_generation)
			evidence_generation = entries[i].target.evidence_generation;
		if (!evidence_generation ||
			entries[i].target.evidence_generation != evidence_generation)
			return -1;
		if (kind == RH_WRITE_INDEX_ROOT) {
			namespace_entries++;
		} else if (kind == RH_WRITE_BITMAP_CLUSTER) {
			bitmap_entries++;
		} else if (kind == RH_WRITE_BITMAP_MFT) {
			mft_entries++;
		} else if (kind == RH_WRITE_INDEX_BITMAP) {
			index_entries++;
		} else {
			dirty_entries++;
		}
	}
	if (!namespace_entries && !bitmap_entries && !mft_entries &&
			!index_entries && !dirty_entries)
		return -1;
	if (rh_wal_view_writer_init(&pre_writer, wal->writer, entries, count, 1))
		goto out;
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
	test_stage = "pre-mount";
#endif
	pre_initialized = 1;
	if (namespace_entries) {
		complete_profile.expected_volume_serial = wal->volume_serial;
		complete_profile.roothealth_record = wal->journal_record;
		complete_profile.roothealth_sequence = wal->journal_sequence;
		complete_profile.require_t1os_identity = 1U;
		if (namespace_entries != 1U ||
				rh_census_reader_from_writer_prefix(&pre_writer,
					pre_writer.operation_count, &pre_reader) ||
				rh_complete_census_run(&pre_reader, &complete_profile,
					evidence_generation, &pre_complete))
			goto out;
	}
	if (rh_ntfs_overlay_mount(&pre_overlay, &pre_writer, 0))
		goto out;
	pre_mounted = 1;
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
	test_stage = "pre-census";
#endif
	if (rh_cluster_bitmap_census_run(pre_overlay.volume, &pre_writer,
			evidence_generation, &pre_census) || !pre_census.complete ||
			!pre_census.structurally_valid || !pre_census.ownership_exact ||
			pre_census.unreadable_slots)
		goto out;
	if ((mft_entries || index_entries) &&
			(rh_raw_mft_census_run(pre_overlay.volume, &pre_writer,
				evidence_generation, &pre_raw) ||
			 rh_mft_bitmap_census_run_from_raw(pre_overlay.volume, &pre_writer,
				evidence_generation, wal->journal_record,
				wal->journal_sequence, &pre_raw, &pre_mft) ||
			 rh_index_bitmap_census_run_from_raw(pre_overlay.volume, &pre_writer,
				&pre_raw, evidence_generation, &pre_index) ||
			 !pre_raw.records_bounded ||
			 !pre_raw.attribute_lists_complete || !pre_raw.extents_complete ||
			 !pre_mft.complete || !pre_mft.structurally_valid ||
			 !pre_index.complete || !pre_index.index_tree_complete ||
			 !pre_index.child_vcns_valid || !pre_index.indx_blocks_valid ||
			 !pre_index.reachable_set_exact))
		goto out;
	if (pre_census.change_count) {
		matched = calloc(pre_census.change_count, 1);
		if (!matched)
			goto out;
	}
	if (pre_mft.change_count) {
		mft_matched = calloc(pre_mft.change_count, 1U);
		if (!mft_matched)
			goto out;
	}
	if (pre_index.change_count) {
		index_matched = calloc(pre_index.change_count, 1U);
		if (!index_matched)
			goto out;
	}
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
	test_stage = "entry-match";
#endif
	for (i = 0; i < count; i++) {
		if (entries[i].kind == RH_WRITE_ACTION_ID(RH_WRITE_INDEX_ROOT) &&
				!rh_wal_operations_registry_entry_valid(&pre_reader,
					&pre_complete, &entries[i]))
			goto out;
		if (entries[i].kind ==
				RH_WRITE_ACTION_ID(RH_WRITE_BITMAP_CLUSTER) &&
				!rh_wal_bitmap_entry_valid(&pre_census, &entries[i], matched)) {
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
			fprintf(stderr, "cluster entry mismatch i=%zu pre_changes=%zu "
				"off=%llu len=%llu sem=%llu/%llu\n", i,
				pre_census.change_count,
				(unsigned long long)entries[i].target_offset,
				(unsigned long long)entries[i].length,
				(unsigned long long)entries[i].target.semantic_target_offset,
				(unsigned long long)entries[i].target.semantic_target_length);
#endif
			goto out;
		}
		if (entries[i].kind == RH_WRITE_ACTION_ID(RH_WRITE_BITMAP_MFT) &&
				!rh_wal_mft_bitmap_entry_valid(&pre_mft, &entries[i],
					mft_matched))
			goto out;
		if (entries[i].kind == RH_WRITE_ACTION_ID(RH_WRITE_INDEX_BITMAP) &&
				!rh_wal_index_bitmap_entry_valid(&pre_index, &entries[i],
					index_matched))
			goto out;
	}
	if (wal->state == RH_WAL_COMMITTED &&
			(bitmap_entries || mft_entries || index_entries) &&
			(bitmap_entries != pre_census.change_count ||
			 mft_entries != pre_mft.change_count ||
			 index_entries != pre_index.change_count))
		goto out;
	if (dirty_entries) {
		size_t dirty_index = 0;

		set_dirty = entries[0].kind ==
			RH_WRITE_ACTION_ID(RH_WRITE_VOLUME_DIRTY_SET);
		if (!set_dirty && entries[0].kind !=
				RH_WRITE_ACTION_ID(RH_WRITE_VOLUME_DIRTY_CLEAR)) {
			for (i = 1; i < count; i++)
				if (entries[i].kind ==
						RH_WRITE_ACTION_ID(RH_WRITE_VOLUME_DIRTY_SET) ||
					entries[i].kind ==
						RH_WRITE_ACTION_ID(RH_WRITE_VOLUME_DIRTY_CLEAR)) {
					set_dirty = entries[i].kind ==
						RH_WRITE_ACTION_ID(RH_WRITE_VOLUME_DIRTY_SET);
					break;
				}
		}
		if ((dirty_entries != count && dirty_entries != 2) ||
				rh_volume_dirty_inspect(pre_overlay.volume, &pre_writer,
					set_dirty, &dirty_pair) ||
				(set_dirty ? dirty_pair.initially_dirty :
				 !dirty_pair.initially_dirty))
			goto out;
		for (i = 0; i < count; i++) {
			if (entries[i].kind !=
					RH_WRITE_ACTION_ID(RH_WRITE_VOLUME_DIRTY_SET) &&
				entries[i].kind !=
					RH_WRITE_ACTION_ID(RH_WRITE_VOLUME_DIRTY_CLEAR))
				continue;
			if (!rh_wal_dirty_entry_valid(&entries[i], &dirty_pair,
					dirty_index == 1U) ||
					memcmp(entries[i].target.evidence_hash,
						pre_census.census_hash, 32))
				goto out;
			dirty_index++;
		}
	}
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
	test_stage = "post-init";
#endif
	if (wal->transaction_kind == RH_WAL_TX_DIRTY_CLEAR &&
			(!pre_census.clean || bitmap_entries || mft_entries || index_entries))
		goto out;
	if (wal->state != RH_WAL_COMMITTED) {
		result = 0;
		goto out;
	}
	if (rh_wal_view_writer_init(&post_writer, wal->writer, entries, count, 0))
		goto out;
	post_initialized = 1;
	if (namespace_entries) {
		if (rh_census_reader_from_writer_prefix(&post_writer,
				post_writer.operation_count, &post_reader) ||
				rh_complete_census_run(&post_reader, &complete_profile,
					evidence_generation + 1U, &post_complete) ||
				!post_complete.identity_matches ||
				!post_complete.namespace_census.graph_complete ||
				!post_complete.namespace_census.i30_complete ||
				!post_complete.namespace_census.reciprocity_complete ||
				post_complete.namespace_census.i30_edge_count !=
					post_complete.namespace_census.link_count ||
				memcmp(pre_complete.raw.file_name_manifest_hash,
					post_complete.raw.file_name_manifest_hash, 32U))
			goto out;
	}
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
	test_stage = "post-current-hash";
#endif
	for (i = 0; i < count; i++) {
		int replaced = rh_wal_entry_has_later_exact_replacement(entries,
			count, i);
		unsigned char *current;
		unsigned char hash[32];

		if (replaced < 0)
			goto out;
		if (replaced)
			continue;
		current = malloc((size_t)entries[i].length);
		if (!current || rh_writer_read(&post_writer,
				entries[i].target_offset, (size_t)entries[i].length, current)) {
			free(current);
			goto out;
		}
		rh_sha256(current, (size_t)entries[i].length, hash);
		if (memcmp(hash, entries[i].new_hash, sizeof(hash))) {
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
			uint64_t relative = entries[i].target.semantic_target_offset -
				entries[i].target_offset;
			fprintf(stderr, "postimage hash mismatch i=%zu kind=%u "
				"off=%llu len=%llu relative=%llu old=%u actual=%u\n",
				i, entries[i].kind,
				(unsigned long long)entries[i].target_offset,
				(unsigned long long)entries[i].length,
				(unsigned long long)relative,
				relative < entries[i].length ? entries[i].old[relative] : 0U,
				relative < entries[i].length ? current[relative] : 0U);
			{
				size_t difference, printed = 0;
				for (difference = 0; difference < entries[i].length &&
						printed < 16U; difference++)
					if (entries[i].old[difference] != current[difference]) {
						fprintf(stderr, "  changed[%zu]=%u->%u\n",
							difference, entries[i].old[difference],
							current[difference]);
						printed++;
					}
			}
#endif
			free(current);
			goto out;
		}
		free(current);
	}
	if (rh_ntfs_overlay_mount(&post_overlay, &post_writer, 0))
		goto out;
	post_mounted = 1;
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
	test_stage = "post-census";
#endif
	post_cluster_result = rh_cluster_bitmap_census_run(post_overlay.volume,
		&post_writer, evidence_generation, &post_census);
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
	fprintf(stderr, "wal post cluster census rc=%d complete=%u clean=%u "
		"structural=%u ownership=%u unreadable=%"PRIu64" changes=%zu/%zu "
		"allocation_equal=%u\n", post_cluster_result, post_census.complete,
		post_census.clean, post_census.structurally_valid,
		post_census.ownership_exact, post_census.unreadable_slots,
		pre_census.change_count, post_census.change_count,
		(unsigned int)!memcmp(pre_census.allocation_hash,
			post_census.allocation_hash, 32U));
#endif
	/*
	 * Removing the resident stale edge is allocation-neutral, so ownership
	 * truth must never change.  The number of bitmap differences also stays
	 * fixed unless this same transaction contains the exact cluster-bitmap
	 * actions that make the post view clean.
	 */
	if (post_cluster_result ||
			!post_census.complete ||
			((bitmap_entries || mft_entries || index_entries) &&
			 !post_census.clean) ||
			!post_census.structurally_valid || !post_census.ownership_exact ||
			post_census.unreadable_slots ||
			(namespace_entries &&
			 ((!bitmap_entries &&
			   pre_census.change_count != post_census.change_count) ||
			  memcmp(pre_census.allocation_hash,
				post_census.allocation_hash, 32U))))
		goto out;
	if ((mft_entries || index_entries) &&
			(rh_raw_mft_census_run(post_overlay.volume, &post_writer,
				evidence_generation, &post_raw) ||
			 rh_mft_bitmap_census_run_from_raw(post_overlay.volume, &post_writer,
				evidence_generation, wal->journal_record,
				wal->journal_sequence, &post_raw, &post_mft) ||
			 rh_index_bitmap_census_run_from_raw(post_overlay.volume, &post_writer,
				&post_raw, evidence_generation, &post_index) ||
			 !post_mft.complete || !post_mft.structurally_valid ||
			 !post_mft.clean || post_mft.change_count ||
			 !post_index.complete || !post_index.clean ||
			 post_index.change_count))
		goto out;
	for (i = 0; i < count; i++)
		if ((entries[i].kind == RH_WRITE_ACTION_ID(RH_WRITE_INDEX_ROOT) &&
				memcmp(entries[i].target.staged_view_hash,
					post_complete.namespace_census.census_hash, 32U)) ||
			((entries[i].kind == RH_WRITE_ACTION_ID(RH_WRITE_BITMAP_CLUSTER) ||
			entries[i].kind == RH_WRITE_ACTION_ID(RH_WRITE_VOLUME_DIRTY_SET) ||
			entries[i].kind == RH_WRITE_ACTION_ID(RH_WRITE_VOLUME_DIRTY_CLEAR)) &&
			memcmp(entries[i].target.staged_view_hash,
				post_census.census_hash, 32)) ||
			(entries[i].kind == RH_WRITE_ACTION_ID(RH_WRITE_BITMAP_MFT) &&
			 memcmp(entries[i].target.staged_view_hash,
				post_mft.census_hash, 32)) ||
			(entries[i].kind == RH_WRITE_ACTION_ID(RH_WRITE_INDEX_BITMAP) &&
			 memcmp(entries[i].target.staged_view_hash,
				post_index.census_hash, 32)))
			goto out;
	if (dirty_entries) {
		set_dirty = entries[0].kind ==
			RH_WRITE_ACTION_ID(RH_WRITE_VOLUME_DIRTY_SET);
		if (rh_volume_dirty_inspect(post_overlay.volume, &post_writer,
				set_dirty, &dirty_pair) ||
				dirty_pair.initially_dirty != set_dirty)
			goto out;
	}
	result = 0;
out:
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
	if (result)
		fprintf(stderr, "wal builtin verifier failed stage=%s errno=%d\n",
			test_stage, errno);
#endif
	free(matched);
	free(mft_matched);
	free(index_matched);
	rh_index_bitmap_census_destroy(&post_index);
	rh_index_bitmap_census_destroy(&pre_index);
	rh_mft_bitmap_census_destroy(&post_mft);
	rh_mft_bitmap_census_destroy(&pre_mft);
	rh_cluster_bitmap_census_destroy(&post_census);
	rh_cluster_bitmap_census_destroy(&pre_census);
	rh_raw_mft_census_release(&post_raw);
	rh_raw_mft_census_release(&pre_raw);
	rh_complete_census_release(&post_complete);
	rh_complete_census_release(&pre_complete);
	if (post_mounted)
		rh_ntfs_overlay_unmount(&post_overlay);
	if (pre_mounted)
		rh_ntfs_overlay_unmount(&pre_overlay);
	if (post_initialized)
		rh_wal_view_writer_destroy(&post_writer);
	if (pre_initialized)
		rh_wal_view_writer_destroy(&pre_writer);
	if (result && !errno)
		errno = EIO;
	return result;
}

static int rh_wal_builtin_bitmap_dirty_verifier(
		const struct rh_wal_action_verifier_context *context)
{
	const struct rh_wal_preimage *preimage;
	size_t i;
	int found = 0;

	if (!context || !context->preimage ||
		context->version != RH_WAL_ACTION_VERIFIER_ABI_VERSION) {
		errno = EINVAL;
		return -1;
	}
	preimage = context->preimage;
	if (!preimage->wal || !preimage->internal_entries ||
		preimage->entry_count != context->entry_count) {
		errno = EINVAL;
		return -1;
	}
	for (i = 0; i < context->entry_count; i++) {
		uint32_t action_id = context->entries[i].action_id;

		if (action_id == RH_WRITE_ACTION_ID(RH_WRITE_INDEX_ROOT) ||
			action_id == RH_WRITE_ACTION_ID(RH_WRITE_INDEX_BITMAP) ||
			action_id == RH_WRITE_ACTION_ID(RH_WRITE_BITMAP_MFT) ||
			action_id == RH_WRITE_ACTION_ID(RH_WRITE_BITMAP_CLUSTER) ||
			action_id == RH_WRITE_ACTION_ID(RH_WRITE_VOLUME_DIRTY_SET) ||
			action_id == RH_WRITE_ACTION_ID(RH_WRITE_VOLUME_DIRTY_CLEAR))
			found = 1;
	}
	if (!found) {
		errno = EINVAL;
		return -1;
	}
	return rh_wal_validate_legacy_recovery_targets(preimage->wal,
		preimage->internal_entries, preimage->entry_count);
}

static int rh_wal_validate_recovery_targets(struct rh_wal *wal,
		struct rh_wal_entry *entries, size_t count)
{
	struct rh_wal_recovery_entry_view *views = NULL;
	const unsigned char **old_payloads = NULL;
	struct rh_writer preimage;
	size_t i;
	int preimage_initialized = 0;
	int result = -1;

	if (!wal || !entries || !count) {
		errno = EINVAL;
		return -1;
	}
	/*
	 * Every transaction, including the existing bitmap/dirty families, enters
	 * the same exact-ID registry.  There is no digest-only or privileged
	 * special-case bypass.
	 */
	views = calloc(count, sizeof(*views));
	old_payloads = calloc(count, sizeof(*old_payloads));
	if (!views || !old_payloads) {
		if (!errno)
			errno = ENOMEM;
		goto out;
	}
	for (i = 0; i < count; i++) {
		views[i].ordinal = i + 1U;
		views[i].action_id = entries[i].kind;
		views[i].target_offset = entries[i].target_offset;
		views[i].length = entries[i].length;
		memcpy(views[i].old_hash, entries[i].old_hash,
			sizeof(views[i].old_hash));
		memcpy(views[i].new_hash, entries[i].new_hash,
			sizeof(views[i].new_hash));
		views[i].target = entries[i].target;
		old_payloads[i] = entries[i].old;
	}
	if (rh_wal_view_writer_init(&preimage, wal->writer, entries, count, 1))
		goto out;
	preimage_initialized = 1;
	result = rh_wal_dispatch_action_verifiers(wal, &preimage, views,
		old_payloads, entries, count);
out:
	if (preimage_initialized)
		rh_wal_view_writer_destroy(&preimage);
	free(old_payloads);
	free(views);
	return result;
}

static int rh_wal_dirty_primary_entry_valid(const struct rh_wal *wal,
		const struct rh_wal_entry *entry, int set_dirty)
{
	unsigned char boot[512];
	uint64_t mft_lcn, primary_base, relative;
	uint32_t expected = RH_WRITE_ACTION_ID(set_dirty ?
		RH_WRITE_VOLUME_DIRTY_SET : RH_WRITE_VOLUME_DIRTY_CLEAR);

	if (!wal || !entry || entry->kind != expected ||
			entry->length != wal->sector_size ||
			rh_writer_staged_read(wal->writer, 0, 0, sizeof(boot), boot))
		return 0;
	mft_lcn = rh_get_u64(boot + 48);
	if (mft_lcn > (wal->writer->device_size >> 12) ||
			mft_lcn > (UINT64_MAX >> 12))
		return 0;
	primary_base = (mft_lcn << 12) + ((uint64_t)FILE_Volume << 10);
	if (entry->target_offset < primary_base ||
			entry->target_offset - primary_base >= 1024U)
		return 0;
	relative = entry->target_offset - primary_base;
	return !(relative % wal->sector_size);
}

static int rh_wal_dirty_pair_entries_valid(const struct rh_wal *wal,
		const struct rh_wal_entry *first, const struct rh_wal_entry *second,
		int set_dirty)
{
	unsigned char boot[512];
	uint64_t mft_lcn, mirror_lcn, primary_base, mirror_base, relative;
	uint32_t expected = RH_WRITE_ACTION_ID(set_dirty ?
		RH_WRITE_VOLUME_DIRTY_SET : RH_WRITE_VOLUME_DIRTY_CLEAR);

	if (!wal || !first || !second ||
			!rh_wal_dirty_primary_entry_valid(wal, first, set_dirty) ||
			first->kind != expected ||
			second->kind != expected || first->length != wal->sector_size ||
			second->length != wal->sector_size ||
			rh_writer_staged_read(wal->writer, 0, 0, sizeof(boot), boot))
		return 0;
	mft_lcn = rh_get_u64(boot + 48);
	mirror_lcn = rh_get_u64(boot + 56);
	if (mft_lcn > (wal->writer->device_size >> 12) ||
			mirror_lcn > (wal->writer->device_size >> 12) ||
			mft_lcn > (UINT64_MAX >> 12) || mirror_lcn > (UINT64_MAX >> 12))
		return 0;
	primary_base = (mft_lcn << 12) + ((uint64_t)FILE_Volume << 10);
	mirror_base = (mirror_lcn << 12) + ((uint64_t)FILE_Volume << 10);
	if (first->target_offset < primary_base ||
			first->target_offset - primary_base >= 1024U)
		return 0;
	relative = first->target_offset - primary_base;
	return !(relative % wal->sector_size) &&
		second->target_offset == mirror_base + relative;
}

static int rh_wal_mft_primary_entry_valid(const struct rh_wal *wal,
		const struct rh_wal_entry *entry)
{
	uint64_t primary_base, mirror_base;
	enum rh_write_kind kind;

	if (!wal || !entry || entry->kind == 0 ||
			entry->kind > RH_WRITE_KIND_COUNT ||
			entry->target.object != RH_WRITE_TARGET_MFT_RECORD_PRIMARY ||
			entry->target.owner_mft_record > 3U ||
			!rh_wal_mft_record_bases(wal, entry->target.owner_mft_record,
				&primary_base, &mirror_base))
		return 0;
	(void)mirror_base;
	kind = (enum rh_write_kind)(entry->kind - 1U);
	if (kind == RH_WRITE_VOLUME_DIRTY_SET)
		return rh_wal_dirty_primary_entry_valid(wal, entry, 1);
	if (kind == RH_WRITE_VOLUME_DIRTY_CLEAR)
		return rh_wal_dirty_primary_entry_valid(wal, entry, 0);
	return entry->target_offset == primary_base && entry->length == 1024U;
}

static int rh_wal_mft_pair_entries_valid(const struct rh_wal *wal,
		const struct rh_wal_entry *first, const struct rh_wal_entry *second)
{
	uint64_t primary_base, mirror_base;
	enum rh_write_kind kind;

	if (!rh_wal_mft_primary_entry_valid(wal, first) || !second ||
			first->kind != second->kind ||
			!rh_wal_mft_record_bases(wal, first->target.owner_mft_record,
				&primary_base, &mirror_base) ||
			!rh_wal_semantic_targets_are_mirror_pair(&first->target,
				primary_base, &second->target, mirror_base))
		return 0;
	kind = (enum rh_write_kind)(first->kind - 1U);
	if (kind == RH_WRITE_VOLUME_DIRTY_SET)
		return rh_wal_dirty_pair_entries_valid(wal, first, second, 1);
	if (kind == RH_WRITE_VOLUME_DIRTY_CLEAR)
		return rh_wal_dirty_pair_entries_valid(wal, first, second, 0);
	return first->target_offset == primary_base &&
		second->target_offset == mirror_base && first->length == 1024U &&
		second->length == 1024U &&
		rh_wal_mft_raw_records_equal(first->old, second->old);
}

static int rh_wal_mft_entry_pairs_valid(const struct rh_wal *wal,
		const struct rh_wal_entry *entries, size_t count,
		int allow_trailing_primary)
{
	size_t i;

	for (i = 0; i < count; i++) {
		const struct rh_write_semantic_target *target = &entries[i].target;

		if (target->object == RH_WRITE_TARGET_MFT_RECORD_MIRROR)
			return 0;
		if (target->object != RH_WRITE_TARGET_MFT_RECORD_PRIMARY ||
				target->owner_mft_record > 3U)
			continue;
		if (i + 1U >= count) {
			if (!allow_trailing_primary ||
					!rh_wal_mft_primary_entry_valid(wal, &entries[i]))
				return 0;
			continue;
		}
		if (!rh_wal_mft_pair_entries_valid(wal, &entries[i],
				&entries[i + 1U]))
			return 0;
		i++;
	}
	return 1;
}

static int rh_wal_load_entries(struct rh_wal *wal,
		struct rh_wal_entry **entries_out)
{
	struct rh_wal_entry *entries;
	unsigned char *manifest = NULL;
	uint32_t *action_ids = NULL;
	unsigned char plan_hash[32];
	uint64_t cursor = RH_WAL_ENTRY_START;
	uint64_t target_total = 0;
	uint64_t i = 0;
	unsigned int dirty_set_count = 0;
	unsigned int dirty_clear_count = 0;
	size_t manifest_size;
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
	const char *test_stage = "start";
#endif

	if (!wal->entry_count) {
		if (wal->data_used || wal->target_bytes)
			return -1;
		*entries_out = NULL;
		return 0;
	}
	if (wal->entry_count > SIZE_MAX / sizeof(*entries) ||
		wal->entry_count > SIZE_MAX / RH_WAL_PLAN_BYTES)
		return -1;
	entries = calloc((size_t)wal->entry_count, sizeof(*entries));
	if (!entries)
		return -1;
	manifest_size = (size_t)wal->entry_count * RH_WAL_PLAN_BYTES;
	manifest = malloc(manifest_size);
	action_ids = malloc((size_t)wal->entry_count * sizeof(*action_ids));
	if (!manifest || !action_ids)
		goto invalid;
	for (i = 0; i < wal->entry_count; i++) {
		unsigned char descriptor[RH_WAL_DESCRIPTOR_SIZE];
		unsigned char digest[32];
		unsigned char *payload;
		struct rh_wal_entry *entry = &entries[i];
		#ifdef ROOTHEALTH_WAL_TEST_HOOKS
		test_stage = "descriptor";
		#endif
		{
			int stream_error = rh_wal_stream_read(wal, cursor,
				sizeof(descriptor), descriptor);
			int invalid_descriptor = !stream_error &&
				(memcmp(descriptor, rh_entry_magic, sizeof(rh_entry_magic)) ||
				 rh_get_u32(descriptor + 0x08) != 1 ||
				 rh_get_u32(descriptor + 0x0c) != RH_WAL_DESCRIPTOR_SIZE ||
				 rh_get_u64(descriptor + 0x10) != i ||
				 rh_get_u32(descriptor + 0x3c) ||
				 !rh_all_zero(descriptor + 0x180,
					RH_WAL_DESCRIPTOR_DIGEST - 0x180));
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
			if (stream_error || invalid_descriptor)
				fprintf(stderr, "descriptor[%llu] stream=%d read_fd=%d write_fd=%d "
					"ops=%zu device=%llu runs=%zu run0=%llu/%llu/%llu "
					"data=%llu cursor=%llu magic=%d "
					"version=%u size=%u ordinal=%llu reserved=%u zero=%d\n",
					(unsigned long long)i, stream_error, wal->writer->read_fd,
					wal->writer->write_fd, wal->writer->operation_count,
					(unsigned long long)wal->writer->device_size, wal->run_count,
					(unsigned long long)(wal->run_count ?
						wal->runs[0].stream_offset : 0),
					(unsigned long long)(wal->run_count ?
						wal->runs[0].device_offset : 0),
					(unsigned long long)(wal->run_count ?
						wal->runs[0].length : 0),
					(unsigned long long)wal->data_size,
					(unsigned long long)cursor,
					memcmp(descriptor, rh_entry_magic,
						sizeof(rh_entry_magic)),
					rh_get_u32(descriptor + 0x08),
					rh_get_u32(descriptor + 0x0c),
					(unsigned long long)rh_get_u64(descriptor + 0x10),
					rh_get_u32(descriptor + 0x3c),
					rh_all_zero(descriptor + 0x180,
						RH_WAL_DESCRIPTOR_DIGEST - 0x180));
#endif
			if (stream_error || invalid_descriptor)
				goto invalid;
		}
		#ifdef ROOTHEALTH_WAL_TEST_HOOKS
		test_stage = "descriptor-digest";
		#endif
		rh_sha256(descriptor, RH_WAL_DESCRIPTOR_DIGEST, digest);
		if (memcmp(digest, descriptor + RH_WAL_DESCRIPTOR_DIGEST, 32))
			goto invalid;
		memcpy(manifest + (size_t)i * RH_WAL_PLAN_BYTES, descriptor,
			RH_WAL_PLAN_BYTES);
		entry->target_offset = rh_get_u64(descriptor + 0x18);
		entry->length = rh_get_u64(descriptor + 0x20);
		entry->payload_offset = rh_get_u64(descriptor + 0x28);
		entry->padded_length = rh_get_u64(descriptor + 0x30);
		entry->kind = rh_get_u32(descriptor + 0x38);
		action_ids[i] = entry->kind;
		memcpy(entry->old_hash, descriptor + 0x40, 32);
		memcpy(entry->new_hash, descriptor + 0x60, 32);
		rh_wal_descriptor_target_parse(descriptor, &entry->target);
		#ifdef ROOTHEALTH_WAL_TEST_HOOKS
		test_stage = "descriptor-fields";
		#endif
		if (!entry->length || entry->length > SIZE_MAX ||
			entry->padded_length > SIZE_MAX ||
			entry->target_offset % wal->sector_size ||
			entry->length % wal->sector_size ||
			entry->target_offset > wal->writer->device_size ||
			entry->length > wal->writer->device_size - entry->target_offset ||
			entry->payload_offset != cursor + RH_WAL_DESCRIPTOR_SIZE ||
			entry->padded_length != entry->length ||
			entry->padded_length % wal->sector_size ||
			entry->padded_length > RH_WAL_SIZE - entry->payload_offset ||
			entry->kind == 0 || entry->kind > RH_WRITE_KIND_COUNT ||
			entry->target.semantic_target_offset < entry->target_offset ||
			entry->target.semantic_target_offset - entry->target_offset >
				entry->length ||
			entry->target.semantic_target_length > entry->length -
				(entry->target.semantic_target_offset - entry->target_offset) ||
			entry->target.semantic_target_length > SIZE_MAX ||
			!rh_write_semantic_target_valid(
				(enum rh_write_kind)(entry->kind - 1U), &entry->target,
				((entry->target.object == RH_WRITE_TARGET_MFT_RECORD_PRIMARY ||
				 entry->target.object == RH_WRITE_TARGET_MFT_RECORD_MIRROR) ?
					(entry->kind != RH_WRITE_ACTION_ID(
						RH_WRITE_VOLUME_DIRTY_SET) && entry->kind !=
						RH_WRITE_ACTION_ID(RH_WRITE_VOLUME_DIRTY_CLEAR)) : 0) ?
					entry->target_offset :
					entry->target.semantic_target_offset,
				((entry->target.object == RH_WRITE_TARGET_MFT_RECORD_PRIMARY ||
				 entry->target.object == RH_WRITE_TARGET_MFT_RECORD_MIRROR) ?
					(entry->kind != RH_WRITE_ACTION_ID(
						RH_WRITE_VOLUME_DIRTY_SET) && entry->kind !=
						RH_WRITE_ACTION_ID(RH_WRITE_VOLUME_DIRTY_CLEAR)) : 0) ?
					(size_t)entry->length :
					(size_t)entry->target.semantic_target_length, 1))
			goto invalid;
		if (rh_writer_range_excluded(wal->writer, entry->target_offset,
				entry->length))
			goto invalid;
		if (entry->kind == RH_WRITE_ACTION_ID(RH_WRITE_VOLUME_DIRTY_SET)) {
			dirty_set_count++;
		} else if (entry->kind ==
			RH_WRITE_ACTION_ID(RH_WRITE_VOLUME_DIRTY_CLEAR)) {
			dirty_clear_count++;
		}
		payload = malloc((size_t)entry->padded_length);
		#ifdef ROOTHEALTH_WAL_TEST_HOOKS
		test_stage = "payload-alloc";
		#endif
		if (!payload)
			goto invalid;
		#ifdef ROOTHEALTH_WAL_TEST_HOOKS
		test_stage = "payload-read";
		#endif
		if (rh_wal_stream_read(wal, entry->payload_offset,
				(size_t)entry->padded_length, payload) ||
			!rh_all_zero(payload + entry->length,
				(size_t)(entry->padded_length - entry->length))) {
			free(payload);
			goto invalid;
		}
		#ifdef ROOTHEALTH_WAL_TEST_HOOKS
		test_stage = "payload-old-hash";
		#endif
		rh_sha256(payload, (size_t)entry->length, digest);
		if (memcmp(digest, entry->old_hash, 32)) {
			free(payload);
			goto invalid;
		}
		#ifdef ROOTHEALTH_WAL_TEST_HOOKS
		test_stage = "payload-semantic-hash";
		#endif
		if (rh_write_semantic_payload_hash(
				(enum rh_write_kind)(entry->kind - 1U), &entry->target,
				entry->target_offset, (size_t)entry->length, payload, digest) ||
				memcmp(digest, entry->target.semantic_before_hash, 32)) {
			free(payload);
			goto invalid;
		}
		entry->old = payload;
		cursor = entry->payload_offset + entry->padded_length;
		if (entry->length > UINT64_MAX - target_total)
			goto invalid;
		target_total += entry->length;
	}
	#ifdef ROOTHEALTH_WAL_TEST_HOOKS
	test_stage = "transaction-shape";
	#endif
	if (cursor != RH_WAL_ENTRY_START + wal->data_used ||
		target_total != wal->target_bytes ||
		!rh_wal_mft_entry_pairs_valid(wal, entries,
			(size_t)wal->entry_count,
			wal->state == RH_WAL_APPLYING || wal->state == RH_WAL_ROLLBACK) ||
		(wal->transaction_kind == RH_WAL_TX_DIRTY_CLEAR &&
			(dirty_set_count || dirty_clear_count != wal->entry_count ||
			 wal->entry_count > 2 ||
			 (wal->state == RH_WAL_COMMITTED && wal->entry_count != 2) ||
			 (wal->entry_count == 1 &&
			  !rh_wal_dirty_primary_entry_valid(wal, &entries[0], 0)) ||
			 (wal->entry_count == 2 &&
			  !rh_wal_dirty_pair_entries_valid(wal, &entries[0],
				&entries[1], 0)))) ||
		(wal->transaction_kind == RH_WAL_TX_METADATA_REPAIR &&
			(dirty_clear_count ||
			 dirty_set_count > 2 ||
			 (wal->state == RH_WAL_COMMITTED && dirty_set_count != 0 &&
			  dirty_set_count != 2) ||
			 (dirty_set_count == 1 &&
			  !rh_wal_dirty_primary_entry_valid(wal, &entries[0], 1)) ||
			 (dirty_set_count == 2 &&
			  !rh_wal_dirty_pair_entries_valid(wal, &entries[0],
				&entries[1], 1)))) ||
		(wal->transaction_kind == RH_WAL_TX_METADATA_REPAIR &&
			!rh_wal_metadata_action_order_valid_internal(action_ids,
				(size_t)wal->entry_count,
				wal->state == RH_WAL_COMMITTED))) {
		goto invalid;
	}
	if (wal->state == RH_WAL_COMMITTED) {
		#ifdef ROOTHEALTH_WAL_TEST_HOOKS
		test_stage = "plan-hash";
		#endif
		rh_sha256(manifest, manifest_size, plan_hash);
		if (memcmp(plan_hash, wal->plan_hash, sizeof(plan_hash)))
			goto invalid;
	}
	#ifdef ROOTHEALTH_WAL_TEST_HOOKS
	test_stage = "recovery-targets";
	#endif
	if (rh_wal_validate_recovery_targets(wal, entries,
			(size_t)wal->entry_count))
		goto invalid;
	free(manifest);
	free(action_ids);
	*entries_out = entries;
	return 0;
invalid:
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
	fprintf(stderr, "wal load failed stage=%s entry=%"PRIu64" errno=%d\n",
		test_stage, i, errno);
	if (!strcmp(test_stage, "descriptor-fields") && i < wal->entry_count) {
		const struct rh_wal_entry *failed = &entries[i];
		int mft_object = failed->target.object ==
			RH_WRITE_TARGET_MFT_RECORD_PRIMARY || failed->target.object ==
			RH_WRITE_TARGET_MFT_RECORD_MIRROR;
		fprintf(stderr, "entry kind=%u off=%llu len=%llu payload=%llu/%llu "
			"obj=%u sem=%llu/%llu logical=%llu target-valid=%d excluded=%d\n",
			failed->kind, (unsigned long long)failed->target_offset,
			(unsigned long long)failed->length,
			(unsigned long long)failed->payload_offset,
			(unsigned long long)failed->padded_length,
			(unsigned int)failed->target.object,
			(unsigned long long)failed->target.semantic_target_offset,
			(unsigned long long)failed->target.semantic_target_length,
			(unsigned long long)failed->target.logical_length,
			rh_write_semantic_target_valid(
				(enum rh_write_kind)(failed->kind - 1U), &failed->target,
				mft_object ? failed->target_offset :
					failed->target.semantic_target_offset,
				mft_object ? (size_t)failed->length :
					(size_t)failed->target.semantic_target_length, 1),
			rh_writer_range_excluded(wal->writer, failed->target_offset,
				failed->length));
	}
#endif
	free(manifest);
	free(action_ids);
	rh_wal_entries_free(entries, (size_t)wal->entry_count);
	errno = EIO;
	return -1;
}

int rh_wal_finalize_empty(struct rh_wal *wal)
{
	static const unsigned char zero_uuid[16] = {0};
	static const unsigned char zero_hash[32] = {0};
	int opened = 0;
	int result;

	if (!wal || wal->state == RH_WAL_EMPTY) {
		errno = EINVAL;
		return -1;
	}
	if (wal->writer->write_fd < 0) {
		if (rh_writer_raw_begin(wal->writer))
			return -1;
		opened = 1;
	}
	result = rh_wal_publish(wal, RH_WAL_EMPTY, RH_WAL_TX_NONE, 0, 0, 0,
		zero_uuid, zero_hash);
	if (!result) {
		wal->observation->recovery_required = 0;
		wal->observation->recovered = 1;
	}
	wal->observation->write_boundaries = wal->writer->write_boundaries;
	if (opened && rh_writer_raw_end(wal->writer))
		result = -1;
	return result;
}

int rh_wal_rollback(struct rh_wal *wal)
{
	struct rh_wal_entry *entries = NULL;
	unsigned char *old = NULL, *current = NULL;
	unsigned char hash[32];
	uint64_t i;
	int opened = 0;
	int result = -1;

	if (!wal || wal->state == RH_WAL_EMPTY ||
		(wal->state != RH_WAL_PREPARING &&
		 rh_wal_load_entries(wal, &entries)))
		return -1;
	if (wal->state == RH_WAL_PREPARING &&
			(wal->entry_count || wal->data_used || wal->target_bytes)) {
		errno = EIO;
		return -1;
	}
	if (wal->writer->write_fd < 0) {
		if (rh_writer_raw_begin(wal->writer))
			goto out;
		opened = 1;
	}
	if (wal->state != RH_WAL_ROLLBACK &&
		rh_wal_publish(wal, RH_WAL_ROLLBACK, wal->transaction_kind,
			wal->data_used, wal->entry_count, wal->target_bytes,
			wal->transaction_uuid, wal->plan_hash))
		goto out;
	for (i = wal->entry_count; i; i--) {
		const struct rh_wal_entry *entry = &entries[i - 1];
		size_t first_boundary;
		old = malloc((size_t)entry->length);
		current = malloc((size_t)entry->length);
		if (!old || !current ||
			rh_wal_stream_read(wal, entry->payload_offset,
				(size_t)entry->length, old) ||
			rh_writer_current_read(wal->writer, entry->target_offset,
				(size_t)entry->length, current))
			goto out;
		rh_sha256(current, (size_t)entry->length, hash);
		if (memcmp(hash, entry->old_hash, 32)) {
			first_boundary = wal->writer->write_boundaries;
			if (rh_writer_recovery_write(wal->writer, entry->target_offset,
					(size_t)entry->length, old) ||
					rh_wal_trace_completed_target_write(wal,
						entry->target_offset, (size_t)entry->length,
						current, old, first_boundary))
				goto out;
		}
		free(old);
		free(current);
		old = current = NULL;
	}
	if (rh_wal_finalize_empty(wal))
		goto out;
	wal->observation->recovered = 1;
	result = 0;
out:
	free(old);
	free(current);
	rh_wal_entries_free(entries, (size_t)wal->entry_count);
	wal->observation->write_boundaries = wal->writer->write_boundaries;
	if (opened && wal->writer->write_fd >= 0 && rh_writer_raw_end(wal->writer))
		result = -1;
	return result;
}

int rh_wal_recovery_entry_at(struct rh_wal *wal, size_t ordinal,
		struct rh_wal_committed_entry *entry)
{
	struct rh_wal_entry *entries = NULL;
	const struct rh_wal_entry *source;
	int result = -1;

	if (!wal || !entry || ordinal >= wal->entry_count ||
			wal->state == RH_WAL_EMPTY) {
		errno = EINVAL;
		return -1;
	}
	if (rh_wal_load_entries(wal, &entries))
		return -1;
	source = &entries[ordinal];
	memset(entry, 0, sizeof(*entry));
	entry->action_id = source->kind;
	entry->target_offset = source->target_offset;
	entry->length = source->length;
	memcpy(entry->before_hash, source->old_hash,
		sizeof(entry->before_hash));
	memcpy(entry->after_hash, source->new_hash,
		sizeof(entry->after_hash));
	entry->target = source->target;
	result = 0;
	rh_wal_entries_free(entries, (size_t)wal->entry_count);
	return result;
}

int rh_wal_recovery_entries(struct rh_wal *wal,
		struct rh_wal_committed_entry **output, size_t *count)
{
	struct rh_wal_entry *entries = NULL;
	struct rh_wal_committed_entry *views = NULL;
	size_t i;

	if (!wal || !output || !count || wal->state == RH_WAL_EMPTY ||
			wal->entry_count > SIZE_MAX) {
		errno = EINVAL;
		return -1;
	}
	*output = NULL;
	*count = 0;
	if (rh_wal_load_entries(wal, &entries))
		return -1;
	if (wal->entry_count) {
		views = calloc((size_t)wal->entry_count, sizeof(*views));
		if (!views) {
			rh_wal_entries_free(entries, (size_t)wal->entry_count);
			return -1;
		}
	}
	for (i = 0; i < (size_t)wal->entry_count; i++) {
		views[i].action_id = entries[i].kind;
		views[i].target_offset = entries[i].target_offset;
		views[i].length = entries[i].length;
		memcpy(views[i].before_hash, entries[i].old_hash, 32U);
		memcpy(views[i].after_hash, entries[i].new_hash, 32U);
		views[i].target = entries[i].target;
	}
	rh_wal_entries_free(entries, (size_t)wal->entry_count);
	*output = views;
	*count = (size_t)wal->entry_count;
	return 0;
}

int rh_wal_committed_accept(struct rh_wal *wal,
		enum rh_wal_transaction_kind verified_kind)
{
	struct rh_wal_entry *entries = NULL;

	if (!wal || wal->state != RH_WAL_COMMITTED ||
		wal->transaction_kind != verified_kind ||
		(verified_kind != RH_WAL_TX_METADATA_REPAIR &&
			verified_kind != RH_WAL_TX_DIRTY_CLEAR)) {
		errno = EINVAL;
		return -1;
	}
	if (rh_wal_load_entries(wal, &entries))
		return -1;
	rh_wal_entries_free(entries, (size_t)wal->entry_count);
	return rh_wal_finalize_empty(wal);
}
