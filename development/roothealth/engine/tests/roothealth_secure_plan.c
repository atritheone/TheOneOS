#include "config.h"

#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include <sys/stat.h>

#include "roothealth_secure.h"

static size_t fixture_descriptor_count = 2U;
static uint32_t *fixture_live_ids;

#ifdef ROOTHEALTH_REALLOC_FAULT_TEST
void *__real_realloc(void *pointer, size_t size);
static size_t realloc_fault_size;
static int realloc_fault_armed;

void *__wrap_realloc(void *pointer, size_t size)
{
	if (realloc_fault_armed && size == realloc_fault_size) {
		realloc_fault_armed = 0;
		errno = ENOMEM;
		return NULL;
	}
	return __real_realloc(pointer, size);
}
#endif

static void fact_hash(const char *label, unsigned char output[32])
{
	rh_sha256(label, strlen(label), output);
}

static void seed_fixture_identity(struct rh_secure_census *census)
{
	memset(census, 0, sizeof(*census));
	census->complete_security_id_census = 1;
	census->security_ids_expected = fixture_descriptor_count;
	census->security_ids_examined = fixture_descriptor_count;
	census->live_security_id_count = fixture_descriptor_count;
	census->live_security_ids = fixture_live_ids;
}

static int make_authority(const struct rh_secure_inspection *inspection,
		enum rh_secure_view view, uint64_t generation,
		struct rh_secure_authority *authority)
{
	struct rh_secure_census census;

	seed_fixture_identity(&census);
	census.view = view;
	census.ledger_format = RH_SECURE_LEDGER_FORMAT;
	census.generation = generation;
	census.volume_serial = inspection->volume_serial;
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
	census.mft_records_expected = 16;
	census.mft_records_examined = 16;
	census.attributes_expected = 32;
	census.attributes_examined = 32;
	census.runs_expected = inspection->sds_slice_count;
	census.runs_examined = inspection->sds_slice_count;
	census.namespace_links_expected = 1;
	census.namespace_links_examined = 1;
	census.namespace_links_reciprocal = 1;
	census.security_descriptors_expected = inspection->descriptor_count;
	census.security_descriptors_examined = inspection->descriptor_count;
	if (inspection->descriptor_count != census.live_security_id_count) {
		errno = EUCLEAN;
		return -1;
	}
	census.security_id_references_expected = 16;
	census.security_id_references_examined = 16;
	census.security_id_references_resolved = 16;
	fact_hash("test-only-rhcov3-coverage", census.coverage_ledger_hash);
	fact_hash("test-only-rhcov3-identity", census.identity_graph_hash);
	fact_hash("test-only-rhcov3-namespace-security",
		census.namespace_security_hash);
	fact_hash("test-only-rhcov3-security-id-use",
		census.security_id_use_hash);
	fact_hash("test-only-rhcov3-global-security",
		census.global_security_hash);
	memcpy(census.descriptor_manifest_hash,
		inspection->descriptor_manifest_hash, 32);
	return rh_secure_authority_seal(&census, authority);
}

static int expected_state(const char *mode,
		const struct rh_secure_inspection *inspection)
{
	if (!strcmp(mode, "clean"))
		return inspection->sds_clean && inspection->sdh_clean &&
			inspection->sii_clean;
	if (!strcmp(mode, "sds"))
		return !inspection->sds_clean && inspection->sdh_clean &&
			inspection->sii_clean;
	if (!strcmp(mode, "sdh"))
		return inspection->sds_clean && !inspection->sdh_clean &&
			inspection->sii_clean;
	if (!strcmp(mode, "sii"))
		return inspection->sds_clean && inspection->sdh_clean &&
			!inspection->sii_clean;
	if (!strcmp(mode, "indexes"))
		return inspection->sds_clean && !inspection->sdh_clean &&
			!inspection->sii_clean;
	if (!strcmp(mode, "batch-indexes"))
		return inspection->sds_clean && !inspection->sdh_clean &&
			!inspection->sii_clean;
	if (!strcmp(mode, "all"))
		return !inspection->sds_clean && !inspection->sdh_clean &&
			!inspection->sii_clean;
	return 0;
}

static int expected_plan_shape(const char *mode,
		const struct rh_secure_plan *plan)
{
	int sds = !strcmp(mode, "sds") || !strcmp(mode, "all");
	int sdh = !strcmp(mode, "sdh") || !strcmp(mode, "indexes") ||
		!strcmp(mode, "all");
	int sii = !strcmp(mode, "sii") || !strcmp(mode, "indexes") ||
		!strcmp(mode, "all");

	return (!!plan->sds_operation_count == sds) &&
		(!!plan->sdh_operation_count == sdh) &&
		(!!plan->sii_operation_count == sii) &&
		plan->operation_count == plan->sds_operation_count +
			plan->sdh_operation_count + plan->sii_operation_count;
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

static int materialize_post(const char *path,
		const struct rh_writer *writer, size_t first, size_t count)
{
	unsigned char *current = NULL;
	int fd = -1, result = -1;
	size_t i;

	fd = open(path, O_RDWR | O_CLOEXEC | O_NOFOLLOW);
	if (fd < 0)
		return -1;
	for (i = 0; i < count; i++) {
		const struct rh_write_operation *operation =
			&writer->operations[first + i];
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
	if (fsync(fd))
		goto out;
	result = 0;
out:
	free(current);
	close(fd);
	return result;
}

static void export_entries(const struct rh_writer *writer, size_t first,
		size_t count, struct rh_secure_recovery_entry *entries)
{
	size_t i;

	for (i = 0; i < count; i++) {
		const struct rh_write_operation *operation =
			&writer->operations[first + i];

		memset(&entries[i], 0, sizeof(entries[i]));
		entries[i].kind = operation->kind;
		entries[i].target_offset = operation->offset;
		entries[i].length = operation->length;
		rh_sha256(operation->before, operation->length,
			entries[i].old_hash);
		rh_sha256(operation->after, operation->length,
			entries[i].new_hash);
		entries[i].target = operation->target;
	}
}

static int recovery_call(struct rh_ntfs_overlay *pre_overlay,
		struct rh_writer *pre_writer,
		const struct rh_secure_authority *pre_authority,
		struct rh_ntfs_overlay *post_overlay, struct rh_writer *post_writer,
		const struct rh_secure_authority *post_authority,
		const struct rh_secure_recovery_entry *entries, size_t count)
{
	return rh_secure_rederive_recovery(pre_overlay->volume, pre_writer,
		pre_authority, post_overlay->volume, post_writer, post_authority,
		entries, count);
}

static int batch_recovery_call(struct rh_ntfs_overlay *pre_overlay,
		struct rh_writer *pre_writer,
		const struct rh_secure_authority *pre_authority,
		const struct rh_secure_batch_cursor *before,
		struct rh_ntfs_overlay *post_overlay, struct rh_writer *post_writer,
		const struct rh_secure_authority *post_authority,
		const struct rh_secure_batch_cursor *after,
		const struct rh_secure_recovery_entry *entries, size_t count)
{
	return rh_secure_rederive_batch_recovery(pre_overlay->volume, pre_writer,
		pre_authority, before, post_overlay->volume, post_writer,
		post_authority, after, entries, count);
}

static int recovery_matrix(const char *pre_path, const char *post_path,
		struct rh_secure_recovery_entry *entries, size_t count,
		uint64_t generation)
{
	struct rh_writer pre_writer, post_writer;
	struct rh_ntfs_overlay pre_overlay, post_overlay;
	struct rh_secure_inspection pre_inspection, post_inspection;
	struct rh_secure_authority pre_authority, post_authority, bad_authority;
	struct rh_secure_census seed;
	struct rh_secure_recovery_entry saved;
	int pre_open = 0, post_open = 0, pre_mounted = 0, post_mounted = 0;
	int result = -1;

	memset(&pre_inspection, 0, sizeof(pre_inspection));
	memset(&post_inspection, 0, sizeof(post_inspection));
	memset(&pre_authority, 0, sizeof(pre_authority));
	memset(&post_authority, 0, sizeof(post_authority));
	seed_fixture_identity(&seed);
	if (rh_writer_open(&pre_writer, pre_path))
		goto out;
	pre_open = 1;
	if (rh_ntfs_overlay_mount(&pre_overlay, &pre_writer, 0))
		goto out;
	pre_mounted = 1;
	if (rh_writer_open(&post_writer, post_path))
		goto out;
	post_open = 1;
	if (rh_ntfs_overlay_mount(&post_overlay, &post_writer, 0))
		goto out;
	post_mounted = 1;
	if (
			rh_secure_inspect(pre_overlay.volume, &pre_writer, &seed,
				&pre_inspection) ||
			rh_secure_inspect(post_overlay.volume, &post_writer, &seed,
				&post_inspection) ||
			make_authority(&pre_inspection, RH_SECURE_PRETRANSACTION,
				generation, &pre_authority) ||
			make_authority(&post_inspection, RH_SECURE_STAGED, generation,
				&post_authority) ||
			recovery_call(&pre_overlay, &pre_writer, &pre_authority,
				&post_overlay, &post_writer, &post_authority, entries, count))
		goto out;
	saved = entries[0];
	entries[0].old_hash[0] ^= 1U;
	if (!recovery_call(&pre_overlay, &pre_writer, &pre_authority,
			&post_overlay, &post_writer, &post_authority, entries, count))
		goto out;
	entries[0] = saved;
	entries[0].new_hash[0] ^= 1U;
	if (!recovery_call(&pre_overlay, &pre_writer, &pre_authority,
			&post_overlay, &post_writer, &post_authority, entries, count))
		goto out;
	entries[0] = saved;
	entries[0].target_offset++;
	if (!recovery_call(&pre_overlay, &pre_writer, &pre_authority,
			&post_overlay, &post_writer, &post_authority, entries, count))
		goto out;
	entries[0] = saved;
	entries[0].length--;
	if (!recovery_call(&pre_overlay, &pre_writer, &pre_authority,
			&post_overlay, &post_writer, &post_authority, entries, count))
		goto out;
	entries[0] = saved;
	entries[0].target.owner_mft_record++;
	if (!recovery_call(&pre_overlay, &pre_writer, &pre_authority,
			&post_overlay, &post_writer, &post_authority, entries, count))
		goto out;
	entries[0] = saved;
	entries[0].target.attribute_name_hash[0] ^= 1U;
	if (!recovery_call(&pre_overlay, &pre_writer, &pre_authority,
			&post_overlay, &post_writer, &post_authority, entries, count))
		goto out;
	entries[0] = saved;
	entries[0].target.semantic_target_length--;
	if (!recovery_call(&pre_overlay, &pre_writer, &pre_authority,
			&post_overlay, &post_writer, &post_authority, entries, count))
		goto out;
	entries[0] = saved;
	entries[0].kind = entries[0].kind == RH_WRITE_SECURE_SDS ?
		RH_WRITE_SECURE_SDH : RH_WRITE_SECURE_SDS;
	if (!recovery_call(&pre_overlay, &pre_writer, &pre_authority,
			&post_overlay, &post_writer, &post_authority, entries, count))
		goto out;
	entries[0] = saved;
	bad_authority = post_authority;
	bad_authority.seal[0] ^= 1U;
	if (!recovery_call(&pre_overlay, &pre_writer, &pre_authority,
			&post_overlay, &post_writer, &bad_authority, entries, count))
		goto out;
	for (enum rh_write_kind kind = RH_WRITE_SECURE_SDS;
			kind <= RH_WRITE_SECURE_SII;
			kind = (enum rh_write_kind)(kind + 1)) {
		size_t i;

		for (i = 0; i < count; i++)
			if (entries[i].kind == kind)
				break;
		if (i == count)
			continue;
		saved = entries[i];
		entries[i].target.attribute_instance++;
		if (!recovery_call(&pre_overlay, &pre_writer, &pre_authority,
				&post_overlay, &post_writer, &post_authority, entries, count))
			goto out;
		entries[i] = saved;
	}
	result = 0;
out:
	if (post_mounted)
		rh_ntfs_overlay_unmount(&post_overlay);
	if (post_open)
		rh_writer_close(&post_writer);
	if (pre_mounted)
		rh_ntfs_overlay_unmount(&pre_overlay);
	if (pre_open)
		rh_writer_close(&pre_writer);
	rh_secure_inspection_destroy(&post_inspection);
	rh_secure_inspection_destroy(&pre_inspection);
	rh_secure_authority_destroy(&post_authority);
	rh_secure_authority_destroy(&pre_authority);
	return result;
}

static int batch_recovery_matrix(const char *pre_path, const char *post_path,
		const struct rh_secure_batch_cursor *before,
		const struct rh_secure_batch_cursor *after,
		struct rh_secure_recovery_entry *entries, size_t count,
		uint64_t generation, size_t *negative_count)
{
	struct rh_writer pre_writer, post_writer;
	struct rh_ntfs_overlay pre_overlay, post_overlay;
	struct rh_secure_inspection pre_inspection, post_inspection;
	struct rh_secure_authority pre_authority, post_authority, bad_authority;
	struct rh_secure_batch_cursor bad_before, bad_after;
	struct rh_secure_census seed;
	struct rh_secure_recovery_entry saved;
	int pre_open = 0, post_open = 0, pre_mounted = 0, post_mounted = 0;
	int result = -1;
	const char *phase = "open-pre";
	size_t negative_case = 0;

	memset(&pre_inspection, 0, sizeof(pre_inspection));
	memset(&post_inspection, 0, sizeof(post_inspection));
	memset(&pre_authority, 0, sizeof(pre_authority));
	memset(&post_authority, 0, sizeof(post_authority));
	seed_fixture_identity(&seed);
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
	phase = "inspect-pre";
	if (rh_secure_inspect(pre_overlay.volume, &pre_writer, &seed,
			&pre_inspection))
		goto out;
	phase = "inspect-post";
	if (rh_secure_inspect(post_overlay.volume, &post_writer, &seed,
			&post_inspection))
		goto out;
	phase = "authority-pre";
	if (make_authority(&pre_inspection, RH_SECURE_PRETRANSACTION,
			generation, &pre_authority))
		goto out;
	phase = "authority-post";
	if (make_authority(&post_inspection, RH_SECURE_STAGED, generation,
			&post_authority))
		goto out;
	phase = "positive";
	if (batch_recovery_call(&pre_overlay, &pre_writer, &pre_authority,
			before, &post_overlay, &post_writer, &post_authority, after,
			entries, count))
		goto out;
	*negative_count = 0;
#define EXPECT_BATCH_RECOVERY_REFUSAL() do { \
	phase = "entry-negative"; \
	negative_case++; \
	if (!batch_recovery_call(&pre_overlay, &pre_writer, &pre_authority, \
			before, &post_overlay, &post_writer, &post_authority, after, \
			entries, count)) \
		goto out; \
	(*negative_count)++; \
} while (0)
	saved = entries[0];
	entries[0].old_hash[0] ^= 1U;
	EXPECT_BATCH_RECOVERY_REFUSAL();
	entries[0] = saved;
	entries[0].new_hash[0] ^= 1U;
	EXPECT_BATCH_RECOVERY_REFUSAL();
	entries[0] = saved;
	entries[0].target_offset++;
	EXPECT_BATCH_RECOVERY_REFUSAL();
	entries[0] = saved;
	entries[0].length--;
	EXPECT_BATCH_RECOVERY_REFUSAL();
	entries[0] = saved;
	entries[0].target.owner_mft_record++;
	EXPECT_BATCH_RECOVERY_REFUSAL();
	entries[0] = saved;
	entries[0].target.attribute_name_hash[0] ^= 1U;
	EXPECT_BATCH_RECOVERY_REFUSAL();
	entries[0] = saved;
	entries[0].target.semantic_target_length--;
	EXPECT_BATCH_RECOVERY_REFUSAL();
	entries[0] = saved;
	entries[0].target.attribute_instance++;
	EXPECT_BATCH_RECOVERY_REFUSAL();
	entries[0] = saved;
	entries[0].kind = entries[0].kind == RH_WRITE_SECURE_SDS ?
		RH_WRITE_SECURE_SDH : RH_WRITE_SECURE_SDS;
	EXPECT_BATCH_RECOVERY_REFUSAL();
	entries[0] = saved;
	bad_authority = post_authority;
	phase = "authority-negative";
	bad_authority.seal[0] ^= 1U;
	if (!batch_recovery_call(&pre_overlay, &pre_writer, &pre_authority,
			before, &post_overlay, &post_writer, &bad_authority, after,
			entries, count))
		goto out;
	(*negative_count)++;
	bad_after = *after;
	phase = "cursor-negative";
	bad_after.seal[0] ^= 1U;
	if (!batch_recovery_call(&pre_overlay, &pre_writer, &pre_authority,
			before, &post_overlay, &post_writer, &post_authority, &bad_after,
			entries, count))
		goto out;
	(*negative_count)++;
	bad_after = *after;
	bad_after.expected_state_hash[0] ^= 1U;
	if (!batch_recovery_call(&pre_overlay, &pre_writer, &pre_authority,
			before, &post_overlay, &post_writer, &post_authority, &bad_after,
			entries, count))
		goto out;
	(*negative_count)++;
	bad_after = *after;
	bad_after.mapping_hash[0] ^= 1U;
	if (!batch_recovery_call(&pre_overlay, &pre_writer, &pre_authority,
			before, &post_overlay, &post_writer, &post_authority, &bad_after,
			entries, count))
		goto out;
	(*negative_count)++;
	bad_after = *after;
	bad_after.descriptor_manifest_hash[0] ^= 1U;
	if (!batch_recovery_call(&pre_overlay, &pre_writer, &pre_authority,
			before, &post_overlay, &post_writer, &post_authority, &bad_after,
			entries, count))
		goto out;
	(*negative_count)++;
	bad_after = *after;
	bad_after.next_batch_ordinal++;
	if (!batch_recovery_call(&pre_overlay, &pre_writer, &pre_authority,
			before, &post_overlay, &post_writer, &post_authority, &bad_after,
			entries, count))
		goto out;
	(*negative_count)++;
	bad_after = *after;
	bad_after.operations_completed++;
	if (!batch_recovery_call(&pre_overlay, &pre_writer, &pre_authority,
			before, &post_overlay, &post_writer, &post_authority, &bad_after,
			entries, count))
		goto out;
	(*negative_count)++;
	bad_after = *after;
	bad_after.complete ^= 1U;
	if (!batch_recovery_call(&pre_overlay, &pre_writer, &pre_authority,
			before, &post_overlay, &post_writer, &post_authority, &bad_after,
			entries, count))
		goto out;
	(*negative_count)++;
	bad_before = *before;
	bad_before.seal[0] ^= 1U;
	if (!batch_recovery_call(&pre_overlay, &pre_writer, &pre_authority,
			&bad_before, &post_overlay, &post_writer, &post_authority, after,
			entries, count))
		goto out;
	(*negative_count)++;
#undef EXPECT_BATCH_RECOVERY_REFUSAL
	result = 0;
out:
	if (result)
		fprintf(stderr, "batch recovery phase=%s negative=%zu errno=%d\n",
			phase, negative_case, errno);
	if (post_mounted)
		rh_ntfs_overlay_unmount(&post_overlay);
	if (post_open)
		rh_writer_close(&post_writer);
	if (pre_mounted)
		rh_ntfs_overlay_unmount(&pre_overlay);
	if (pre_open)
		rh_writer_close(&pre_writer);
	rh_secure_inspection_destroy(&post_inspection);
	rh_secure_inspection_destroy(&pre_inspection);
	rh_secure_authority_destroy(&post_authority);
	rh_secure_authority_destroy(&pre_authority);
	return result;
}

static int copy_image_to_fd(const char *source, int output)
{
	unsigned char buffer[65536];
	struct stat st;
	int input = -1, result = -1;
	off_t offset = 0;

	input = open(source, O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
	if (input < 0 || fstat(input, &st) || st.st_size <= 0 ||
			ftruncate(output, st.st_size))
		goto out;
	while (offset < st.st_size) {
		size_t take = (size_t)(st.st_size - offset);
		ssize_t got, put;

		if (take > sizeof(buffer))
			take = sizeof(buffer);
		got = pread(input, buffer, take, offset);
		if (got != (ssize_t)take)
			goto out;
		put = pwrite(output, buffer, take, offset);
		if (put != (ssize_t)take)
			goto out;
		offset += (off_t)take;
	}
	result = fsync(output);
out:
	if (input >= 0)
		close(input);
	return result;
}

static int copy_image_path(const char *source, const char *target)
{
	int output, result;

	output = open(target, O_RDWR | O_CREAT | O_TRUNC | O_CLOEXEC |
		O_NOFOLLOW, 0600);
	if (output < 0)
		return -1;
	result = copy_image_to_fd(source, output);
	if (close(output) && !result)
		result = -1;
	return result;
}

static int partial_recovery_refuses(const struct rh_writer *source_writer,
		size_t pre_operation_count, const char *partial_path,
		const struct rh_secure_recovery_entry *entries, size_t count,
		uint64_t generation)
{
	struct rh_writer pre_writer, partial_writer;
	struct rh_ntfs_overlay pre_overlay, partial_overlay;
	struct rh_secure_inspection pre, partial;
	struct rh_secure_authority pre_authority, partial_authority;
	struct rh_secure_census seed;
	int partial_open = 0, pre_mounted = 0;
	int partial_mounted = 0, result = -1;

	memset(&pre, 0, sizeof(pre));
	memset(&partial, 0, sizeof(partial));
	memset(&pre_authority, 0, sizeof(pre_authority));
	memset(&partial_authority, 0, sizeof(partial_authority));
	seed_fixture_identity(&seed);
	pre_writer = *source_writer;
	pre_writer.operation_count = pre_operation_count;
	if (rh_ntfs_overlay_mount(&pre_overlay, &pre_writer, 0))
		goto out;
	pre_mounted = 1;
	if (rh_writer_open(&partial_writer, partial_path))
		goto out;
	partial_open = 1;
	if (rh_ntfs_overlay_mount(&partial_overlay, &partial_writer, 0)) {
		/* A torn MST record/block is an acceptable fail-closed outcome. */
		result = 0;
		goto out;
	}
	partial_mounted = 1;
	if (rh_secure_inspect(pre_overlay.volume, &pre_writer, &seed, &pre))
		goto out;
	if (rh_secure_inspect(partial_overlay.volume, &partial_writer, &seed,
			&partial)) {
		result = 0;
		goto out;
	}
	if (make_authority(&pre, RH_SECURE_PRETRANSACTION, generation,
			&pre_authority) ||
			make_authority(&partial, RH_SECURE_STAGED, generation,
				&partial_authority))
		goto out;
	if (!recovery_call(&pre_overlay, &pre_writer, &pre_authority,
			&partial_overlay, &partial_writer, &partial_authority,
			entries, count)) {
		errno = EBADE;
		goto out;
	}
	result = 0;
out:
	if (partial_mounted)
		rh_ntfs_overlay_unmount(&partial_overlay);
	if (partial_open)
		rh_writer_close(&partial_writer);
	if (pre_mounted)
		rh_ntfs_overlay_unmount(&pre_overlay);
	rh_secure_authority_destroy(&partial_authority);
	rh_secure_authority_destroy(&pre_authority);
	rh_secure_inspection_destroy(&partial);
	rh_secure_inspection_destroy(&pre);
	return result;
}

static int power_cut_matrix(const char *pre_path,
		const struct rh_writer *writer, size_t first, size_t count,
		const struct rh_secure_recovery_entry *entries, uint64_t generation)
{
	size_t cut;

	for (cut = 0; cut < count; cut++) {
		char path[] = "/var/tmp/rhsecure-powercut-XXXXXX";
		int fd = mkstemp(path);
		int failed = 0;

		if (fd < 0)
			return -1;
		if (copy_image_to_fd(pre_path, fd))
			failed = 1;
		if (close(fd) && !failed)
			failed = 1;
		if (!failed && materialize_post(path, writer, first, cut))
			failed = 1;
		if (!failed && partial_recovery_refuses(writer, first, path, entries,
				count, generation))
			failed = 1;
		if (unlink(path) && !failed)
			failed = 1;
		if (failed)
			return -1;
	}
	return 0;
}

static int batch_cursor_refusals(struct rh_ntfs_overlay *overlay,
		const struct rh_secure_authority *authority,
		const struct rh_secure_batch_cursor *cursor, size_t *negative_count)
{
	struct rh_secure_batch_cursor bad, after, empty_cursor;
	struct rh_secure_plan plan, empty_plan;
	unsigned int variant;

	memset(&empty_cursor, 0, sizeof(empty_cursor));
	memset(&empty_plan, 0, sizeof(empty_plan));
	for (variant = 0; variant < 7U; variant++) {
		bad = *cursor;
		switch (variant) {
		case 0:
			bad.seal[0] ^= 1U;
			break;
		case 1:
			bad.expected_state_hash[0] ^= 1U;
			break;
		case 2:
			bad.mapping_hash[0] ^= 1U;
			break;
		case 3:
			bad.descriptor_manifest_hash[0] ^= 1U;
			break;
		case 4:
			bad.next_batch_ordinal++;
			break;
		case 5:
			bad.operations_completed++;
			break;
		default:
			bad.complete = 1U;
			break;
		}
		memset(&after, 0xa5, sizeof(after));
		memset(&plan, 0xa5, sizeof(plan));
		if (rh_secure_stage_batch(overlay, authority, &bad, &after, &plan) !=
				RH_SECURE_STAGE_REFUSED || overlay->writer->operation_count ||
				memcmp(&after, &empty_cursor, sizeof(after)) ||
				memcmp(&plan, &empty_plan, sizeof(plan)))
			return -1;
		(*negative_count)++;
	}
	return 0;
}

static int batch_partial_recovery_refuses(
		const struct rh_writer *source_writer, size_t pre_operation_count,
		const char *partial_path,
		const struct rh_secure_batch_cursor *before,
		const struct rh_secure_batch_cursor *after,
		const struct rh_secure_recovery_entry *entries, size_t count,
		uint64_t generation)
{
	struct rh_writer pre_writer, post_writer;
	struct rh_ntfs_overlay pre_overlay, post_overlay;
	struct rh_secure_inspection pre, post;
	struct rh_secure_authority pre_authority, post_authority;
	struct rh_secure_census seed;
	int post_open = 0, pre_mounted = 0, post_mounted = 0;
	int result = -1;
	const char *phase = "pre-mount";

	memset(&pre, 0, sizeof(pre));
	memset(&post, 0, sizeof(post));
	memset(&pre_authority, 0, sizeof(pre_authority));
	memset(&post_authority, 0, sizeof(post_authority));
	seed_fixture_identity(&seed);
	pre_writer = *source_writer;
	pre_writer.operation_count = pre_operation_count;
	if (rh_ntfs_overlay_mount(&pre_overlay, &pre_writer, 0))
		goto out;
	pre_mounted = 1;
	phase = "post-open";
	if (rh_writer_open(&post_writer, partial_path))
		goto out;
	post_open = 1;
	phase = "post-mount";
	if (rh_ntfs_overlay_mount(&post_overlay, &post_writer, 0)) {
		result = 0;
		goto out;
	}
	post_mounted = 1;
	phase = "inspect";
	if (rh_secure_inspect(pre_overlay.volume, &pre_writer, &seed, &pre) ||
			rh_secure_inspect(post_overlay.volume, &post_writer, &seed, &post)) {
		result = 0;
		goto out;
	}
	phase = "authority";
	if (make_authority(&pre, RH_SECURE_PRETRANSACTION, generation,
			&pre_authority) ||
			make_authority(&post, RH_SECURE_STAGED, generation,
				&post_authority))
		goto out;
	phase = "expected-refusal";
	if (!batch_recovery_call(&pre_overlay, &pre_writer, &pre_authority,
			before, &post_overlay, &post_writer, &post_authority, after,
			entries, count)) {
		errno = EBADE;
		goto out;
	}
	result = 0;
out:
	if (result)
		fprintf(stderr, "batch partial phase=%s errno=%d\n", phase, errno);
	if (post_mounted)
		rh_ntfs_overlay_unmount(&post_overlay);
	if (post_open)
		rh_writer_close(&post_writer);
	if (pre_mounted)
		rh_ntfs_overlay_unmount(&pre_overlay);
	rh_secure_authority_destroy(&post_authority);
	rh_secure_authority_destroy(&pre_authority);
	rh_secure_inspection_destroy(&post);
	rh_secure_inspection_destroy(&pre);
	return result;
}

static int batch_power_cut_matrix(const char *pre_path,
		const struct rh_writer *writer, size_t first, size_t count,
		const struct rh_secure_batch_cursor *before,
		const struct rh_secure_batch_cursor *after,
		const struct rh_secure_recovery_entry *entries, uint64_t generation,
		size_t *cut_count)
{
	size_t cut;

	for (cut = 0; cut < count; cut++) {
		char path[] = "/var/tmp/rhsecure-batch-powercut-XXXXXX";
		int fd = mkstemp(path);
		int failed = 0;
		const char *phase = "create";

		if (fd < 0)
			return -1;
		if (copy_image_to_fd(pre_path, fd)) {
			phase = "copy";
			failed = 1;
		}
		if (close(fd) && !failed) {
			phase = "close";
			failed = 1;
		}
		if (!failed && materialize_post(path, writer, first, cut)) {
			phase = "materialize";
			failed = 1;
		}
		if (!failed && batch_partial_recovery_refuses(writer, first, path,
				before, after, entries, count, generation)) {
			phase = "recovery-refusal";
			failed = 1;
		}
		if (unlink(path) && !failed) {
			phase = "unlink";
			failed = 1;
		}
		if (failed) {
			fprintf(stderr, "batch powercut phase=%s cut=%zu errno=%d\n",
				phase, cut, errno);
			return -1;
		}
		(*cut_count)++;
	}
	return 0;
}

static int batch_matrix(const char *source_path, const char *final_path,
		uint64_t generation)
{
	char paths[2][48] = {
		"/var/tmp/rhsecure-batch-a-XXXXXX",
		"/var/tmp/rhsecure-batch-b-XXXXXX"
	};
	struct rh_secure_batch_cursor cursor, after;
	struct rh_secure_census seed;
	size_t batches = 0, operations = 0, negative_count = 0, cut_count = 0;
	int descriptors[2] = {-1, -1};
	int current = 0, result = -1;
	const char *phase = "temporary-images";

	memset(&cursor, 0, sizeof(cursor));
	seed_fixture_identity(&seed);
	for (size_t i = 0; i < 2U; i++) {
		descriptors[i] = mkstemp(paths[i]);
		if (descriptors[i] < 0)
			goto out;
		if (close(descriptors[i]))
			goto out;
		descriptors[i] = -1;
	}
	if (copy_image_path(source_path, paths[current]))
		goto out;
	rh_secure_test_set_batch_max_operations(1U);
	while (batches < 32U) {
		struct rh_writer writer;
		struct rh_ntfs_overlay overlay;
		struct rh_secure_inspection inspection, staged;
		struct rh_secure_authority authority, staged_authority;
		struct rh_secure_batch_cursor cursor_before = cursor;
		struct rh_secure_plan plan;
		struct rh_secure_recovery_entry *entries = NULL;
		size_t local_negatives = 0;
		int mounted = 0, opened = 0, next = 1 - current;

		memset(&inspection, 0, sizeof(inspection));
		memset(&staged, 0, sizeof(staged));
		memset(&authority, 0, sizeof(authority));
		memset(&staged_authority, 0, sizeof(staged_authority));
		phase = "batch-open";
		if (rh_writer_open(&writer, paths[current]))
			goto batch_out;
		opened = 1;
		if (rh_ntfs_overlay_mount(&overlay, &writer, 0))
			goto batch_out;
		mounted = 1;
		phase = "batch-pre-authority";
		if (rh_secure_inspect(overlay.volume, &writer, &seed, &inspection) ||
				(inspection.sds_clean && inspection.sdh_clean &&
				 inspection.sii_clean) ||
				make_authority(&inspection, RH_SECURE_PRETRANSACTION,
					generation, &authority))
			goto batch_out;
		if (batches && batch_cursor_refusals(&overlay, &authority, &cursor,
				&negative_count))
			goto batch_out;
		phase = "batch-stage";
		if (rh_secure_stage_batch(&overlay, &authority, &cursor, &after,
				&plan) != RH_SECURE_STAGE_PLANNED ||
				plan.operation_count != 1U || writer.operation_count != 1U)
			goto batch_out;
		/* The staged authority is always reconstructed after a fresh remount. */
		rh_ntfs_overlay_unmount(&overlay);
		mounted = 0;
		if (rh_ntfs_overlay_mount(&overlay, &writer, 0))
			goto batch_out;
		mounted = 1;
		phase = "batch-staged-inspect";
		if (rh_secure_inspect(overlay.volume, &writer, &authority.census,
				&staged))
			goto batch_out;
		phase = "batch-staged-authority";
		if (make_authority(&staged, RH_SECURE_STAGED, generation,
				&staged_authority))
			goto batch_out;
		phase = "batch-staged-verify";
		if (rh_secure_verify_batch_staged(&overlay, &staged_authority,
				&after, &plan))
			goto batch_out;
		phase = "batch-finalize";
		if (rh_secure_finalize(&writer, &plan))
			goto batch_out;
		entries = calloc(plan.operation_count, sizeof(*entries));
		if (!entries)
			goto batch_out;
		export_entries(&writer, plan.initial_checkpoint,
			plan.operation_count, entries);
		phase = "batch-copy";
		if (copy_image_path(paths[current], paths[next]))
			goto batch_out;
		phase = "batch-materialize";
		if (materialize_post(paths[next], &writer,
				plan.initial_checkpoint, plan.operation_count))
			goto batch_out;
		phase = "batch-powercut";
		if (batch_power_cut_matrix(paths[current], &writer,
				plan.initial_checkpoint, plan.operation_count,
				&cursor_before, &after, entries, generation, &cut_count))
			goto batch_out;
		if (mounted) {
			rh_ntfs_overlay_unmount(&overlay);
			mounted = 0;
		}
		if (opened) {
			rh_writer_close(&writer);
			opened = 0;
		}
		phase = "batch-recovery";
		if (batch_recovery_matrix(paths[current], paths[next],
				&cursor_before, &after, entries, plan.operation_count,
				generation, &local_negatives))
			goto batch_out;
		negative_count += local_negatives;
		operations += plan.operation_count;
		batches++;
		cursor = after;
		current = next;
		free(entries);
		rh_secure_authority_destroy(&staged_authority);
		rh_secure_authority_destroy(&authority);
		rh_secure_inspection_destroy(&staged);
		rh_secure_inspection_destroy(&inspection);
		if (cursor.complete)
			break;
		continue;
batch_out:
		free(entries);
		if (mounted)
			rh_ntfs_overlay_unmount(&overlay);
		if (opened)
			rh_writer_close(&writer);
		rh_secure_authority_destroy(&staged_authority);
		rh_secure_authority_destroy(&authority);
		rh_secure_inspection_destroy(&staged);
		rh_secure_inspection_destroy(&inspection);
		goto out;
	}
	phase = "final-copy";
	if (!cursor.complete || batches < 2U || operations != batches ||
			copy_image_path(paths[current], final_path))
		goto out;
	{
		struct rh_writer writer;
		struct rh_ntfs_overlay overlay;
		struct rh_secure_inspection inspection;
		struct rh_secure_authority authority;
		struct rh_secure_batch_cursor empty, clean_after;
		struct rh_secure_plan clean_plan;
		int opened = 0, mounted = 0;

		memset(&inspection, 0, sizeof(inspection));
		memset(&authority, 0, sizeof(authority));
		memset(&empty, 0, sizeof(empty));
		phase = "final-noop";
		if (rh_writer_open(&writer, final_path))
			goto final_out;
		opened = 1;
		if (rh_ntfs_overlay_mount(&overlay, &writer, 0))
			goto final_out;
		mounted = 1;
		if (rh_secure_inspect(overlay.volume, &writer, &seed, &inspection) ||
				!inspection.sds_clean || !inspection.sdh_clean ||
				!inspection.sii_clean ||
				make_authority(&inspection, RH_SECURE_PRETRANSACTION,
					generation, &authority) ||
				rh_secure_stage_batch(&overlay, &authority, &empty,
					&clean_after, &clean_plan) != RH_SECURE_STAGE_CLEAN ||
				!clean_after.complete || writer.operation_count)
			goto final_out;
		result = 0;
final_out:
		if (mounted)
			rh_ntfs_overlay_unmount(&overlay);
		if (opened)
			rh_writer_close(&writer);
		rh_secure_authority_destroy(&authority);
		rh_secure_inspection_destroy(&inspection);
	}
	if (!result)
		printf("mode=batch-indexes batches=%zu operations=%zu "
			"cursor_negatives=%zu power_cut_prefixes=%zu final=noop\n",
			batches, operations, negative_count, cut_count);
out:
	if (result)
		fprintf(stderr, "batch_matrix phase=%s batch=%zu errno=%d\n",
			phase, batches, errno);
	rh_secure_test_set_batch_max_operations(0);
	for (size_t i = 0; i < 2U; i++) {
		if (descriptors[i] >= 0)
			close(descriptors[i]);
		if (paths[i][0])
			unlink(paths[i]);
	}
	return result;
}

static int refusal_case(const char *path)
{
	struct rh_writer writer;
	struct rh_ntfs_overlay overlay;
	struct rh_secure_inspection inspection;
	struct rh_secure_plan plan;
	struct rh_secure_census seed;
	int mounted = 0, result = -1;

	memset(&inspection, 0, sizeof(inspection));
	seed_fixture_identity(&seed);
	if (rh_writer_open(&writer, path))
		return -1;
	if (rh_ntfs_overlay_mount(&overlay, &writer, 0))
		goto out;
	mounted = 1;
	if (!rh_secure_inspect(overlay.volume, &writer, &seed, &inspection) ||
			writer.operation_count ||
			rh_secure_stage(&overlay, NULL, &plan) != RH_SECURE_STAGE_REFUSED ||
			writer.operation_count)
		goto out;
	result = 0;
out:
	rh_secure_inspection_destroy(&inspection);
	if (mounted)
		rh_ntfs_overlay_unmount(&overlay);
	rh_writer_close(&writer);
	return result;
}

int main(int argc, char **argv)
{
	const uint64_t generation = UINT64_C(0x5345435552450001);
	struct rh_writer writer;
	struct rh_ntfs_overlay overlay;
	struct rh_secure_inspection inspection, staged;
	struct rh_secure_authority authority, staged_authority, tampered;
	struct rh_secure_plan plan, probe;
	struct rh_secure_census incomplete;
	struct rh_secure_census seed;
	struct rh_secure_recovery_entry *entries = NULL;
	int mounted = 0, opened = 0, result = 1;

	if (argc != 4 && argc != 5)
		return 64;
	if (argc == 5) {
		char *end = NULL;
		unsigned long count;

		errno = 0;
		count = strtoul(argv[4], &end, 10);
		if (errno || !end || *end || !count || count > UINT32_MAX - 0x100U)
			return 64;
		fixture_descriptor_count = count;
	}
	if (fixture_descriptor_count > SIZE_MAX / sizeof(*fixture_live_ids))
		return 64;
	fixture_live_ids = malloc(fixture_descriptor_count *
		sizeof(*fixture_live_ids));
	if (!fixture_live_ids)
		return 1;
	for (size_t i = 0; i < fixture_descriptor_count; i++)
		fixture_live_ids[i] = 0x100U + (uint32_t)i;
	if (!strcmp(argv[3], "refuse")) {
		if (refusal_case(argv[1])) {
			perror("refusal case");
			free(fixture_live_ids);
			return 1;
		}
		printf("mode=refuse inspect=closed operations=0\n");
		free(fixture_live_ids);
		return 0;
	}
	memset(&inspection, 0, sizeof(inspection));
	memset(&staged, 0, sizeof(staged));
	memset(&authority, 0, sizeof(authority));
	memset(&staged_authority, 0, sizeof(staged_authority));
	seed_fixture_identity(&seed);
	if (rh_writer_open(&writer, argv[1])) {
		fprintf(stderr, "writer open failed\n");
		goto out;
	}
	opened = 1;
	if (rh_ntfs_overlay_mount(&overlay, &writer, 0)) {
		fprintf(stderr, "overlay mount failed\n");
		goto out;
	}
	mounted = 1;
	if (rh_secure_inspect(overlay.volume, &writer, &seed, &inspection)) {
		fprintf(stderr, "initial inspect failed mode=%s\n", argv[3]);
		goto out;
	}
	if (!expected_state(argv[3], &inspection)) {
		fprintf(stderr, "unexpected state mode=%s sds=%d sdh=%d sii=%d\n",
			argv[3], inspection.sds_clean, inspection.sdh_clean,
			inspection.sii_clean);
		goto out;
	}
	if (make_authority(&inspection, RH_SECURE_PRETRANSACTION,
			generation, &authority)) {
		fprintf(stderr, "initial authority failed descriptors=%zu runs=%zu\n",
			inspection.descriptor_count, inspection.sds_slice_count);
		goto out;
	}
	memset(&probe, 0xa5, sizeof(probe));
	if (rh_secure_stage(&overlay, NULL, &probe) != RH_SECURE_STAGE_REFUSED ||
			writer.operation_count) {
		fprintf(stderr, "null authority probe failed ops=%zu\n",
			writer.operation_count);
		goto out;
	}
	tampered = authority;
	tampered.seal[0] ^= 1U;
	if (rh_secure_stage(&overlay, &tampered, &probe) !=
			RH_SECURE_STAGE_REFUSED || writer.operation_count) {
		fprintf(stderr, "tampered authority probe failed ops=%zu\n",
			writer.operation_count);
		goto out;
	}
	incomplete = authority.census;
	incomplete.complete_security_id_census = 0;
	if (!rh_secure_authority_seal(&incomplete, &tampered)) {
		fprintf(stderr, "incomplete authority unexpectedly sealed\n");
		goto out;
	}
	tampered = authority;
	tampered.census.complete_security_id_census = 0;
	if (rh_secure_stage(&overlay, &tampered, &probe) !=
				RH_SECURE_STAGE_REFUSED || writer.operation_count) {
		fprintf(stderr, "incomplete authority probe failed ops=%zu\n",
			writer.operation_count);
		goto out;
	}
	if (!strcmp(argv[3], "batch-indexes")) {
		rh_ntfs_overlay_unmount(&overlay);
		mounted = 0;
		rh_writer_close(&writer);
		opened = 0;
		if (batch_matrix(argv[1], argv[2], generation)) {
			fprintf(stderr, "batch matrix failed\n");
			goto out;
		}
		result = 0;
		goto out;
	}
	if (!strcmp(argv[3], "clean")) {
		if (rh_secure_stage(&overlay, &authority, &plan) !=
				RH_SECURE_STAGE_CLEAN || !plan.clean || writer.operation_count) {
			perror("clean stage");
			goto out;
		}
		printf("mode=clean result=noop operations=0 descriptors=%zu\n",
			inspection.descriptor_count);
		result = 0;
		goto out;
	}
#ifdef ROOTHEALTH_REALLOC_FAULT_TEST
	if (getenv("ROOTHEALTH_SECURE_FAIL_ACTION_REALLOC")) {
		struct rh_secure_plan empty;

		memset(&empty, 0, sizeof(empty));
		realloc_fault_size = sizeof(struct rh_overlay_expected_write);
		realloc_fault_armed = 1;
		errno = 0;
		memset(&plan, 0xa5, sizeof(plan));
		if (rh_secure_stage(&overlay, &authority, &plan) !=
				RH_SECURE_STAGE_ERROR || errno != ENOMEM ||
				realloc_fault_armed || writer.operation_count ||
				memcmp(&plan, &empty, sizeof(plan))) {
			fprintf(stderr, "allocation fault did not close atomically "
				"errno=%d ops=%zu armed=%d\n", errno,
				writer.operation_count, realloc_fault_armed);
			goto out;
		}
		printf("mode=%s allocation_failure=closed operations=0\n", argv[3]);
		result = 0;
		goto out;
	}
#endif
	if (rh_secure_stage(&overlay, &authority, &plan) !=
			RH_SECURE_STAGE_PLANNED) {
		fprintf(stderr, "stage failed mode=%s ops=%zu\n", argv[3],
			writer.operation_count);
		goto out;
	}
	if (!expected_plan_shape(argv[3], &plan)) {
		fprintf(stderr, "plan shape failed mode=%s total=%zu sds=%zu "
			"sdh=%zu sii=%zu\n", argv[3], plan.operation_count,
			plan.sds_operation_count, plan.sdh_operation_count,
			plan.sii_operation_count);
		goto out;
	}
	if (rh_secure_inspect(overlay.volume, &writer,
			&authority.census, &staged)) {
		fprintf(stderr, "staged inspect failed\n");
		goto out;
	}
	if (make_authority(&staged, RH_SECURE_STAGED, generation,
			&staged_authority)) {
		fprintf(stderr, "staged authority failed\n");
		goto out;
	}
	if (rh_secure_verify_staged(&overlay, &staged_authority, &plan)) {
		fprintf(stderr, "staged verify failed\n");
		goto out;
	}
	if (rh_secure_finalize(&writer, &plan) || !plan.finalized) {
		fprintf(stderr, "finalize failed\n");
		goto out;
	}
	entries = calloc(plan.operation_count, sizeof(*entries));
	if (!entries)
		goto out;
	export_entries(&writer, plan.initial_checkpoint, plan.operation_count,
		entries);
	if (power_cut_matrix(argv[1], &writer, plan.initial_checkpoint,
			plan.operation_count, entries, generation)) {
		fprintf(stderr, "power-cut matrix failed\n");
		goto out;
	}
	if (mounted) {
		rh_ntfs_overlay_unmount(&overlay);
		mounted = 0;
	}
	if (materialize_post(argv[2], &writer, plan.initial_checkpoint,
			plan.operation_count))
		goto out;
	rh_writer_close(&writer);
	opened = 0;
	if (recovery_matrix(argv[1], argv[2], entries, plan.operation_count,
			generation))
		goto out;
	printf("mode=%s operations=%zu sds=%zu sdh=%zu sii=%zu "
		"recovery_negatives=9 power_cut_prefixes=%zu\n", argv[3],
		plan.operation_count,
		plan.sds_operation_count, plan.sdh_operation_count,
		plan.sii_operation_count, plan.operation_count);
	result = 0;
out:
	if (result)
		perror("secure plan test");
	free(entries);
	rh_secure_inspection_destroy(&staged);
	rh_secure_inspection_destroy(&inspection);
	if (mounted)
		rh_ntfs_overlay_unmount(&overlay);
	if (opened)
		rh_writer_close(&writer);
	rh_secure_authority_destroy(&staged_authority);
	rh_secure_authority_destroy(&authority);
	free(fixture_live_ids);
	return result;
}
