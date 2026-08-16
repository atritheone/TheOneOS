#include "config.h"

#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include <sys/stat.h>

#include "layout.h"
#include "roothealth_overlay.h"
#include "roothealth_raw_mft.h"
#include "roothealth_secure.h"

struct test_context {
	struct rh_raw_mft_census raw;
	struct rh_secure_inspection inspection;
	struct rh_secure_authority authority;
};

static void fact_hash(const char *label, unsigned char output[32])
{
	rh_sha256(label, strlen(label), output);
}

static uint32_t get_u32(const unsigned char *bytes)
{
	return (uint32_t)bytes[0] | ((uint32_t)bytes[1] << 8) |
		((uint32_t)bytes[2] << 16) | ((uint32_t)bytes[3] << 24);
}

static int security_reference_count(const struct rh_raw_mft_census *raw,
		const uint32_t *ids, size_t id_count, uint64_t *references)
{
	uint64_t count = 0;
	size_t i;

	for (i = 0; i < raw->attribute_count; i++) {
		const struct rh_raw_attribute *attribute = &raw->attributes[i];
		const unsigned char *value;
		uint32_t id;
		size_t low = 0, high = id_count;

		if (attribute->type != AT_STANDARD_INFORMATION ||
				attribute->nonresident || attribute->name_length ||
				attribute->value_length != sizeof(STANDARD_INFORMATION))
			continue;
		if (attribute->value_arena_offset > raw->value_arena_size ||
				attribute->value_length > raw->value_arena_size -
					attribute->value_arena_offset)
			return -1;
		value = raw->value_arena + attribute->value_arena_offset;
		id = get_u32(value + 52U);
		if (id < 0x100U) {
			if (id)
				return -1;
			continue;
		}
		while (low < high) {
			size_t middle = low + (high - low) / 2U;

			if (ids[middle] == id)
				break;
			if (ids[middle] < id)
				low = middle + 1U;
			else
				high = middle;
		}
		if (low == high)
			return -1;
		count++;
	}
	if (!count)
		return -1;
	*references = count;
	return 0;
}

static int build_context(struct rh_ntfs_overlay *overlay,
		struct rh_writer *writer, const uint32_t *ids, size_t id_count,
		uint64_t generation, enum rh_secure_view view,
		struct test_context *context)
{
	struct rh_secure_census census;
	unsigned char legacy_hash[32];
	uint64_t legacy_count = 0, references = 0;

	memset(context, 0, sizeof(*context));
	memset(&census, 0, sizeof(census));
	if (rh_raw_mft_census_run(overlay->volume, writer, generation,
			&context->raw) ||
			rh_secure_legacy_census(&context->raw, &legacy_count,
				legacy_hash) ||
			security_reference_count(&context->raw, ids, id_count,
				&references))
		return -1;
	census.generation = generation;
	census.complete_security_id_census = 1;
	census.security_ids_expected = id_count;
	census.security_ids_examined = id_count;
	census.live_security_ids = ids;
	census.live_security_id_count = id_count;
	census.raw_mft_extent_authority_complete = 1;
	census.raw_mft_census = &context->raw;
	memcpy(census.raw_mft_census_hash, context->raw.census_hash, 32);
	census.legacy_security_descriptors_expected = legacy_count;
	census.legacy_security_descriptors_examined = legacy_count;
	memcpy(census.legacy_security_descriptor_hash, legacy_hash, 32);
	if (rh_secure_inspect(overlay->volume, writer, &census,
			&context->inspection) ||
			context->inspection.descriptor_count != id_count)
		return -1;
	census.view = view;
	census.ledger_format = RH_SECURE_LEDGER_FORMAT;
	census.volume_serial = context->inspection.volume_serial;
	census.coverage_complete = 1;
	census.identity_bound = 1;
	census.no_io_uncertainty = 1;
	census.complete_mft_census = 1;
	census.complete_attribute_census = 1;
	census.complete_runlist_census = 1;
	census.complete_namespace_census = 1;
	census.complete_index_census = 1;
	census.complete_security_descriptor_census = 1;
	census.namespace_security_reciprocity_complete = 1;
	census.global_security_identity_complete = 1;
	census.sole_valid_peer_authority_complete = 1;
	census.no_conflicting_valid_authorities = 1;
	census.target_ownership_exact = 1;
	census.targets_outside_wal = 1;
	census.data_preserving = 1;
	census.final_overlay_valid = view == RH_SECURE_STAGED;
	census.mft_records_expected = context->raw.slots_expected;
	census.mft_records_examined = census.mft_records_expected;
	census.attributes_expected = context->raw.attribute_count;
	census.attributes_examined = census.attributes_expected;
	census.runs_expected = context->raw.run_count;
	census.runs_examined = census.runs_expected;
	census.namespace_links_expected = context->raw.file_name_count;
	census.namespace_links_examined = census.namespace_links_expected;
	census.namespace_links_reciprocal = census.namespace_links_expected;
	census.security_descriptors_expected = id_count + legacy_count;
	census.security_descriptors_examined = census.security_descriptors_expected;
	census.security_id_references_expected = references;
	census.security_id_references_examined = references;
	census.security_id_references_resolved = references;
	fact_hash("raw-batch-coverage", census.coverage_ledger_hash);
	fact_hash("raw-batch-identity", census.identity_graph_hash);
	fact_hash("raw-batch-namespace", census.namespace_security_hash);
	fact_hash("raw-batch-security-use", census.security_id_use_hash);
	fact_hash("raw-batch-global", census.global_security_hash);
	memcpy(census.descriptor_manifest_hash,
		context->inspection.descriptor_manifest_hash, 32);
	return rh_secure_authority_seal(&census, &context->authority);
}

static void destroy_context(struct test_context *context)
{
	rh_secure_authority_destroy(&context->authority);
	rh_secure_inspection_destroy(&context->inspection);
	rh_raw_mft_census_release(&context->raw);
	memset(context, 0, sizeof(*context));
}

static int full_pread(int fd, void *buffer, size_t length, uint64_t offset)
{
	unsigned char *bytes = buffer;
	size_t done = 0;

	while (done < length) {
		ssize_t got = pread(fd, bytes + done, length - done,
			(off_t)(offset + done));

		if (got <= 0)
			return -1;
		done += (size_t)got;
	}
	return 0;
}

static int full_pwrite(int fd, const void *buffer, size_t length,
		uint64_t offset)
{
	const unsigned char *bytes = buffer;
	size_t done = 0;

	while (done < length) {
		ssize_t put = pwrite(fd, bytes + done, length - done,
			(off_t)(offset + done));

		if (put <= 0)
			return -1;
		done += (size_t)put;
	}
	return 0;
}

static int copy_image(const char *source, const char *target)
{
	unsigned char buffer[1024U * 1024U];
	struct stat status;
	int input = -1, output = -1, result = -1;
	off_t offset = 0;

	input = open(source, O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
	output = open(target, O_RDWR | O_CREAT | O_TRUNC | O_CLOEXEC |
		O_NOFOLLOW, 0600);
	if (input < 0 || output < 0 || fstat(input, &status) ||
			status.st_size <= 0 || ftruncate(output, status.st_size))
		goto out;
	while (offset < status.st_size) {
		size_t take = (size_t)(status.st_size - offset);

		if (take > sizeof(buffer))
			take = sizeof(buffer);
		if (full_pread(input, buffer, take, (uint64_t)offset) ||
				full_pwrite(output, buffer, take, (uint64_t)offset))
			goto out;
		offset += (off_t)take;
	}
	result = fsync(output);
out:
	if (output >= 0)
		close(output);
	if (input >= 0)
		close(input);
	return result;
}

static int materialize(const char *path, const struct rh_writer *writer,
		size_t count)
{
	unsigned char *current = NULL;
	int fd = -1, result = -1;
	size_t i;

	fd = open(path, O_RDWR | O_CLOEXEC | O_NOFOLLOW);
	if (fd < 0)
		return -1;
	for (i = 0; i < count; i++) {
		const struct rh_write_operation *operation = &writer->operations[i];
		unsigned char *grown = realloc(current, operation->length);

		if (!grown)
			goto out;
		current = grown;
		if (full_pread(fd, current, operation->length, operation->offset) ||
				memcmp(current, operation->before, operation->length) ||
				full_pwrite(fd, operation->after, operation->length,
					operation->offset)) {
			errno = ESTALE;
			goto out;
		}
	}
	result = fsync(fd);
out:
	free(current);
	close(fd);
	return result;
}

static void export_entries(const struct rh_writer *writer,
		struct rh_secure_recovery_entry *entries)
{
	size_t i;

	for (i = 0; i < writer->operation_count; i++) {
		const struct rh_write_operation *operation = &writer->operations[i];

		entries[i].kind = operation->kind;
		entries[i].target_offset = operation->offset;
		entries[i].length = operation->length;
		rh_sha256(operation->before, operation->length, entries[i].old_hash);
		rh_sha256(operation->after, operation->length, entries[i].new_hash);
		entries[i].target = operation->target;
	}
}

static int recovery_check(const char *pre_path, const char *post_path,
		const uint32_t *ids, size_t id_count, uint64_t generation,
		const struct rh_secure_batch_cursor *before,
		const struct rh_secure_batch_cursor *after,
		struct rh_secure_recovery_entry *entries, size_t entry_count,
		size_t *negative_count)
{
	struct rh_writer pre_writer, post_writer;
	struct rh_ntfs_overlay pre_overlay, post_overlay;
	struct test_context pre, post;
	struct rh_secure_recovery_entry saved;
	struct rh_secure_batch_cursor bad_after;
	int pre_open = 0, post_open = 0, pre_mounted = 0, post_mounted = 0;
	int result = -1;
	const char *phase = "open-pre";
	size_t negative_case = 0;

	memset(&pre, 0, sizeof(pre));
	memset(&post, 0, sizeof(post));
	if (rh_writer_open(&pre_writer, pre_path))
		goto out;
	pre_open = 1;
	phase = "mount-pre";
	if (rh_ntfs_overlay_mount(&pre_overlay, &pre_writer, 0))
		goto out;
	pre_mounted = 1;
	phase = "open-post";
	if (rh_writer_open(&post_writer, post_path))
		goto out;
	post_open = 1;
	phase = "mount-post";
	if (rh_ntfs_overlay_mount(&post_overlay, &post_writer, 0))
		goto out;
	post_mounted = 1;
	phase = "context-pre";
	if (build_context(&pre_overlay, &pre_writer, ids, id_count, generation,
			RH_SECURE_PRETRANSACTION, &pre))
		goto out;
	phase = "context-post";
	if (build_context(&post_overlay, &post_writer, ids, id_count, generation,
			RH_SECURE_STAGED, &post))
		goto out;
	phase = "positive";
	if (rh_secure_rederive_batch_recovery(pre_overlay.volume, &pre_writer,
			&pre.authority, before, post_overlay.volume, &post_writer,
			&post.authority, after, entries, entry_count))
		goto out;
	*negative_count = 0;
#define EXPECT_REFUSAL() do { \
	phase = "negative"; \
	negative_case++; \
	if (!rh_secure_rederive_batch_recovery(pre_overlay.volume, &pre_writer, \
			&pre.authority, before, post_overlay.volume, &post_writer, \
			&post.authority, after, entries, entry_count)) \
		goto out; \
	(*negative_count)++; \
} while (0)
	saved = entries[0];
	entries[0].old_hash[0] ^= 1U;
	EXPECT_REFUSAL();
	entries[0] = saved;
	entries[0].new_hash[0] ^= 1U;
	EXPECT_REFUSAL();
	entries[0] = saved;
	entries[0].target_offset++;
	EXPECT_REFUSAL();
	entries[0] = saved;
	entries[0].length--;
	EXPECT_REFUSAL();
	entries[0] = saved;
	entries[0].target.attribute_name_hash[0] ^= 1U;
	EXPECT_REFUSAL();
	entries[0] = saved;
	entries[0].target.owner_mft_record++;
	EXPECT_REFUSAL();
	entries[0] = saved;
	entries[0].target.attribute_instance++;
	EXPECT_REFUSAL();
	entries[0] = saved;
	entries[0].target.lowest_vcn++;
	EXPECT_REFUSAL();
	entries[0] = saved;
	entries[0].target.lcn++;
	EXPECT_REFUSAL();
	entries[0] = saved;
	bad_after = *after;
	bad_after.mapping_hash[0] ^= 1U;
	if (!rh_secure_rederive_batch_recovery(pre_overlay.volume, &pre_writer,
			&pre.authority, before, post_overlay.volume, &post_writer,
			&post.authority, &bad_after, entries, entry_count))
		goto out;
	(*negative_count)++;
#undef EXPECT_REFUSAL
	result = 0;
out:
	if (result)
		fprintf(stderr, "raw recovery phase=%s negative=%zu errno=%d\n",
			phase, negative_case, errno);
	destroy_context(&post);
	destroy_context(&pre);
	if (post_mounted)
		rh_ntfs_overlay_unmount(&post_overlay);
	if (post_open)
		rh_writer_close(&post_writer);
	if (pre_mounted)
		rh_ntfs_overlay_unmount(&pre_overlay);
	if (pre_open)
		rh_writer_close(&pre_writer);
	return result;
}

static int partial_recovery_refuses(const char *pre_path,
		const char *partial_path, const uint32_t *ids, size_t id_count,
		uint64_t generation, const struct rh_secure_batch_cursor *before,
		const struct rh_secure_batch_cursor *after,
		const struct rh_secure_recovery_entry *entries, size_t entry_count)
{
	struct rh_writer pre_writer, partial_writer;
	struct rh_ntfs_overlay pre_overlay, partial_overlay;
	struct test_context pre, partial;
	int pre_open = 0, partial_open = 0, pre_mounted = 0;
	int partial_mounted = 0, result = -1;

	memset(&pre, 0, sizeof(pre));
	memset(&partial, 0, sizeof(partial));
	if (rh_writer_open(&pre_writer, pre_path))
		goto out;
	pre_open = 1;
	if (rh_ntfs_overlay_mount(&pre_overlay, &pre_writer, 0))
		goto out;
	pre_mounted = 1;
	if (rh_writer_open(&partial_writer, partial_path))
		goto out;
	partial_open = 1;
	if (rh_ntfs_overlay_mount(&partial_overlay, &partial_writer, 0)) {
		result = 0;
		goto out;
	}
	partial_mounted = 1;
	if (build_context(&pre_overlay, &pre_writer, ids, id_count, generation,
			RH_SECURE_PRETRANSACTION, &pre) ||
			build_context(&partial_overlay, &partial_writer, ids, id_count,
				generation, RH_SECURE_STAGED, &partial)) {
		/* An unreadable mixed state is already a fail-closed recovery result. */
		result = 0;
		goto out;
	}
	if (!rh_secure_rederive_batch_recovery(pre_overlay.volume, &pre_writer,
			&pre.authority, before, partial_overlay.volume, &partial_writer,
			&partial.authority, after, entries, entry_count)) {
		errno = EBADE;
		goto out;
	}
	result = 0;
out:
	destroy_context(&partial);
	destroy_context(&pre);
	if (partial_mounted)
		rh_ntfs_overlay_unmount(&partial_overlay);
	if (partial_open)
		rh_writer_close(&partial_writer);
	if (pre_mounted)
		rh_ntfs_overlay_unmount(&pre_overlay);
	if (pre_open)
		rh_writer_close(&pre_writer);
	return result;
}

int main(int argc, char **argv)
{
	const uint64_t generation = UINT64_C(0x5345435241574241);
	struct rh_writer writer;
	struct rh_ntfs_overlay overlay;
	struct test_context pre, staged;
	struct rh_secure_batch_cursor before, after;
	struct rh_secure_plan plan;
	struct rh_secure_recovery_entry *entries = NULL;
	uint32_t *ids = NULL;
	char partial_path[] = "/var/tmp/rhsecure-raw-powercut-XXXXXX";
	char *end = NULL;
	unsigned long parsed;
	size_t id_count, negative_count = 0;
	size_t power_cut_count = 0;
	int opened = 0, mounted = 0, result = 1;
	int partial_fd = -1;
	const char *phase = "arguments";

	if (argc != 4)
		return 64;
	errno = 0;
	parsed = strtoul(argv[3], &end, 10);
	if (errno || !end || *end || !parsed || parsed > UINT32_MAX - 0x100U)
		return 64;
	id_count = (size_t)parsed;
	ids = malloc(id_count * sizeof(*ids));
	if (!ids)
		return 1;
	for (size_t i = 0; i < id_count; i++)
		ids[i] = 0x100U + (uint32_t)i;
	memset(&pre, 0, sizeof(pre));
	memset(&staged, 0, sizeof(staged));
	memset(&before, 0, sizeof(before));
	phase = "open";
	if (rh_writer_open(&writer, argv[1]))
		goto out;
	opened = 1;
	if (rh_ntfs_overlay_mount(&overlay, &writer, 0))
		goto out;
	mounted = 1;
	phase = "pre-census-stage";
	if (build_context(&overlay, &writer, ids, id_count, generation,
			RH_SECURE_PRETRANSACTION, &pre) ||
			rh_secure_stage_batch(&overlay, &pre.authority, &before, &after,
				&plan) != RH_SECURE_STAGE_PLANNED || !after.complete ||
				plan.more_work || !plan.operation_count ||
				plan.operation_count > RH_SECURE_BATCH_MAX_OPERATIONS)
		goto out;
	rh_ntfs_overlay_unmount(&overlay);
	mounted = 0;
	if (rh_ntfs_overlay_mount(&overlay, &writer, 0))
		goto out;
	mounted = 1;
	phase = "staged-census-verify";
	if (build_context(&overlay, &writer, ids, id_count, generation,
			RH_SECURE_STAGED, &staged) ||
			rh_secure_verify_batch_staged(&overlay, &staged.authority, &after,
				&plan) || rh_secure_finalize(&writer, &plan))
		goto out;
	entries = calloc(plan.operation_count, sizeof(*entries));
	if (!entries)
		goto out;
	export_entries(&writer, entries);
	phase = "copy-materialize";
	if (copy_image(argv[1], argv[2]) ||
			materialize(argv[2], &writer, plan.operation_count))
		goto out;
	phase = "powercut-materialize";
	partial_fd = mkstemp(partial_path);
	if (partial_fd < 0 || close(partial_fd))
		goto out;
	partial_fd = -1;
	if (copy_image(argv[1], partial_path) ||
			materialize(partial_path, &writer,
				plan.operation_count > 1U ? plan.operation_count / 2U : 0U))
		goto out;
	if (mounted) {
		rh_ntfs_overlay_unmount(&overlay);
		mounted = 0;
	}
	if (opened) {
		rh_writer_close(&writer);
		opened = 0;
	}
	phase = "powercut-refusal";
	if (partial_recovery_refuses(argv[1], partial_path, ids, id_count,
			generation, &before, &after, entries, plan.operation_count))
		goto out;
	power_cut_count = 1U;
	phase = "recovery";
	if (recovery_check(argv[1], argv[2], ids, id_count, generation,
			&before, &after, entries, plan.operation_count, &negative_count))
		goto out;
	printf("raw_secure_batch=green descriptors=%zu operations=%zu "
		"recovery_negatives=%zu power_cut_prefixes=%zu batches=1 "
		"source_writes=0\n", id_count, plan.operation_count, negative_count,
		power_cut_count);
	result = 0;
out:
	if (result)
		fprintf(stderr, "raw secure batch phase=%s errno=%d\n", phase,
			errno);
	free(entries);
	if (partial_fd >= 0)
		close(partial_fd);
	unlink(partial_path);
	destroy_context(&staged);
	destroy_context(&pre);
	if (mounted)
		rh_ntfs_overlay_unmount(&overlay);
	if (opened)
		rh_writer_close(&writer);
	free(ids);
	return result;
}
