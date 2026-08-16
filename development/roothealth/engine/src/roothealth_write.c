/* ROOTHEALTH_REPAIR_ROLE(TYPED_WAL_ADAPTER) ROOTHEALTH_IO_ROLE(TYPED_WRITER) */
#include "config.h"

#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

#ifdef __linux__
#include <linux/fs.h>
#include <sys/ioctl.h>
#endif

#include "endians.h"
#include "layout.h"
#include "mst.h"
#include "roothealth_write.h"

#ifndef O_CLOEXEC
#define O_CLOEXEC 0
#endif
#ifndef O_NOFOLLOW
#define O_NOFOLLOW 0
#endif

#define RH_MAX_OPERATIONS 131072U
#define RH_MAX_OPERATION_BYTES (16U * 1024U * 1024U)
#define RH_MAX_PLANNED_BYTES (512ULL * 1024ULL * 1024ULL)

struct rh_sha256_ctx {
	uint32_t state[8];
	uint64_t bits;
	unsigned char block[64];
	size_t used;
};

static uint32_t rh_rotr32(uint32_t value, unsigned int count)
{
	return (value >> count) | (value << (32U - count));
}

static void rh_sha256_transform(struct rh_sha256_ctx *ctx,
		const unsigned char block[64])
{
	static const uint32_t k[64] = {
		0x428a2f98U, 0x71374491U, 0xb5c0fbcfU, 0xe9b5dba5U,
		0x3956c25bU, 0x59f111f1U, 0x923f82a4U, 0xab1c5ed5U,
		0xd807aa98U, 0x12835b01U, 0x243185beU, 0x550c7dc3U,
		0x72be5d74U, 0x80deb1feU, 0x9bdc06a7U, 0xc19bf174U,
		0xe49b69c1U, 0xefbe4786U, 0x0fc19dc6U, 0x240ca1ccU,
		0x2de92c6fU, 0x4a7484aaU, 0x5cb0a9dcU, 0x76f988daU,
		0x983e5152U, 0xa831c66dU, 0xb00327c8U, 0xbf597fc7U,
		0xc6e00bf3U, 0xd5a79147U, 0x06ca6351U, 0x14292967U,
		0x27b70a85U, 0x2e1b2138U, 0x4d2c6dfcU, 0x53380d13U,
		0x650a7354U, 0x766a0abbU, 0x81c2c92eU, 0x92722c85U,
		0xa2bfe8a1U, 0xa81a664bU, 0xc24b8b70U, 0xc76c51a3U,
		0xd192e819U, 0xd6990624U, 0xf40e3585U, 0x106aa070U,
		0x19a4c116U, 0x1e376c08U, 0x2748774cU, 0x34b0bcb5U,
		0x391c0cb3U, 0x4ed8aa4aU, 0x5b9cca4fU, 0x682e6ff3U,
		0x748f82eeU, 0x78a5636fU, 0x84c87814U, 0x8cc70208U,
		0x90befffaU, 0xa4506cebU, 0xbef9a3f7U, 0xc67178f2U
	};
	uint32_t w[64];
	uint32_t a, b, c, d, e, f, g, h;
	unsigned int i;

	for (i = 0; i < 16; i++) {
		w[i] = ((uint32_t)block[4 * i] << 24) |
			((uint32_t)block[4 * i + 1] << 16) |
			((uint32_t)block[4 * i + 2] << 8) |
			(uint32_t)block[4 * i + 3];
	}
	for (i = 16; i < 64; i++) {
		uint32_t s0 = rh_rotr32(w[i - 15], 7) ^
			rh_rotr32(w[i - 15], 18) ^ (w[i - 15] >> 3);
		uint32_t s1 = rh_rotr32(w[i - 2], 17) ^
			rh_rotr32(w[i - 2], 19) ^ (w[i - 2] >> 10);
		w[i] = w[i - 16] + s0 + w[i - 7] + s1;
	}
	a = ctx->state[0]; b = ctx->state[1]; c = ctx->state[2];
	d = ctx->state[3]; e = ctx->state[4]; f = ctx->state[5];
	g = ctx->state[6]; h = ctx->state[7];
	for (i = 0; i < 64; i++) {
		uint32_t s1 = rh_rotr32(e, 6) ^ rh_rotr32(e, 11) ^
			rh_rotr32(e, 25);
		uint32_t choose = (e & f) ^ ((~e) & g);
		uint32_t t1 = h + s1 + choose + k[i] + w[i];
		uint32_t s0 = rh_rotr32(a, 2) ^ rh_rotr32(a, 13) ^
			rh_rotr32(a, 22);
		uint32_t majority = (a & b) ^ (a & c) ^ (b & c);
		uint32_t t2 = s0 + majority;
		h = g; g = f; f = e; e = d + t1;
		d = c; c = b; b = a; a = t1 + t2;
	}
	ctx->state[0] += a; ctx->state[1] += b;
	ctx->state[2] += c; ctx->state[3] += d;
	ctx->state[4] += e; ctx->state[5] += f;
	ctx->state[6] += g; ctx->state[7] += h;
}

static void rh_sha256_init(struct rh_sha256_ctx *ctx)
{
	static const uint32_t initial[8] = {
		0x6a09e667U, 0xbb67ae85U, 0x3c6ef372U, 0xa54ff53aU,
		0x510e527fU, 0x9b05688cU, 0x1f83d9abU, 0x5be0cd19U
	};
	memcpy(ctx->state, initial, sizeof(initial));
	ctx->bits = 0;
	ctx->used = 0;
}

static void rh_sha256_update(struct rh_sha256_ctx *ctx, const void *data,
		size_t length)
{
	const unsigned char *input = data;

	ctx->bits += (uint64_t)length * 8U;
	while (length) {
		size_t take = sizeof(ctx->block) - ctx->used;
		if (take > length)
			take = length;
		memcpy(ctx->block + ctx->used, input, take);
		ctx->used += take;
		input += take;
		length -= take;
		if (ctx->used == sizeof(ctx->block)) {
			rh_sha256_transform(ctx, ctx->block);
			ctx->used = 0;
		}
	}
}

static void rh_sha256_final(struct rh_sha256_ctx *ctx, unsigned char out[32])
{
	uint64_t bits = ctx->bits;
	unsigned int i;

	ctx->block[ctx->used++] = 0x80;
	if (ctx->used > 56) {
		memset(ctx->block + ctx->used, 0, 64 - ctx->used);
		rh_sha256_transform(ctx, ctx->block);
		ctx->used = 0;
	}
	memset(ctx->block + ctx->used, 0, 56 - ctx->used);
	for (i = 0; i < 8; i++)
		ctx->block[63 - i] = (unsigned char)(bits >> (8U * i));
	rh_sha256_transform(ctx, ctx->block);
	for (i = 0; i < 8; i++) {
		out[4 * i] = (unsigned char)(ctx->state[i] >> 24);
		out[4 * i + 1] = (unsigned char)(ctx->state[i] >> 16);
		out[4 * i + 2] = (unsigned char)(ctx->state[i] >> 8);
		out[4 * i + 3] = (unsigned char)ctx->state[i];
	}
}

void rh_sha256(const void *data, size_t length, unsigned char output[32])
{
	struct rh_sha256_ctx ctx;

	rh_sha256_init(&ctx);
	rh_sha256_update(&ctx, data, length);
	rh_sha256_final(&ctx, output);
}

void rh_sha256_hex(const void *data, size_t length, char output[65])
{
	static const char hex[] = "0123456789abcdef";
	unsigned char digest[32];
	unsigned int i;

	rh_sha256(data, length, digest);
	for (i = 0; i < sizeof(digest); i++) {
		output[2 * i] = hex[digest[i] >> 4];
		output[2 * i + 1] = hex[digest[i] & 15];
	}
	output[64] = 0;
}

const char *rh_write_kind_name(enum rh_write_kind kind)
{
	static const char *const names[RH_WRITE_KIND_COUNT] = {
		"boot-primary", "boot-backup", "mft-primary", "mft-mirror",
		"logfile-redo", "logfile-restart", "mft-record",
		"attribute-list", "runlist-mapping-pairs", "attribute-data",
		"index-root", "index-allocation", "index-bitmap",
		"cluster-data", "recovery-namespace", "reparse-index",
		"secure-sds", "secure-sdh", "secure-sii", "upcase-data",
		"attrdef-data", "bitmap-mft", "bitmap-cluster",
		"volume-dirty-set", "volume-dirty-clear"
	};
	if (kind < 0 || kind >= RH_WRITE_KIND_COUNT)
		return "invalid";
	return names[kind];
}

static int rh_full_pread(int fd, void *buffer, size_t length, uint64_t offset)
{
	unsigned char *p = buffer;
	while (length) {
		ssize_t got = pread(fd, p, length, (off_t)offset);
		if (got < 0) {
			if (errno == EINTR)
				continue;
			return -1;
		}
		if (!got) {
			errno = EIO;
			return -1;
		}
		p += got;
		offset += (uint64_t)got;
		length -= (size_t)got;
	}
	return 0;
}

static int rh_fault(const char *stage, size_t ordinal);

static int rh_full_pwrite(struct rh_writer *writer, const void *buffer,
		size_t length, uint64_t offset)
{
	const unsigned char *p = buffer;
	while (length) {
		ssize_t put;
		size_t ordinal = writer->write_boundaries + 1U;

		if (rh_fault("before-pwrite", ordinal))
			return -1;
		writer->write_boundaries++;
		put = pwrite(writer->write_fd, p, length, (off_t)offset);
		if (put < 0) {
			if (errno == EINTR)
				continue;
			return -1;
		}
		if (!put) {
			errno = EIO;
			return -1;
		}
		if (rh_fault("after-pwrite", ordinal))
			return -1;
		p += put;
		offset += (uint64_t)put;
		length -= (size_t)put;
	}
	return 0;
}

static int rh_get_size(int fd, const struct stat *st, uint64_t *size)
{
	if (S_ISREG(st->st_mode)) {
		if (st->st_size <= 0) {
			errno = EINVAL;
			return -1;
		}
		*size = (uint64_t)st->st_size;
		return 0;
	}
#ifdef BLKGETSIZE64
	if (S_ISBLK(st->st_mode)) {
		unsigned long long bytes = 0;
		if (ioctl(fd, BLKGETSIZE64, &bytes))
			return -1;
		*size = (uint64_t)bytes;
		return bytes ? 0 : -1;
	}
#endif
	errno = ENOTSUP;
	return -1;
}

int rh_writer_open(struct rh_writer *writer, const char *path)
{
	struct stat st;

	if (!writer || !path || !*path) {
		errno = EINVAL;
		return -1;
	}
	memset(writer, 0, sizeof(*writer));
	writer->read_fd = -1;
	writer->write_fd = -1;
	writer->path = strdup(path);
	if (!writer->path)
		return -1;
	writer->read_fd = open(path, O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
	if (writer->read_fd < 0)
		goto fail;
	if (fstat(writer->read_fd, &st) || rh_get_size(writer->read_fd, &st,
			&writer->device_size))
		goto fail;
	if (flock(writer->read_fd, LOCK_EX | LOCK_NB))
		goto fail;
	writer->lock_held = 1;
	writer->device_id = st.st_dev;
	writer->inode_id = st.st_ino;
	return 0;
fail:
	rh_writer_close(writer);
	return -1;
}

void rh_writer_reset_plan(struct rh_writer *writer)
{
	size_t i;
	if (!writer)
		return;
	for (i = 0; i < writer->operation_count; i++) {
		free(writer->operations[i].before);
		free(writer->operations[i].after);
	}
	free(writer->operations);
	writer->operations = NULL;
	writer->operation_count = 0;
	writer->operation_capacity = 0;
	writer->planned_bytes = 0;
	writer->last_verified_ordinal = 0;
	writer->sync_count = 0;
	writer->commit_started = 0;
	writer->commit_completed = 0;
}

void rh_writer_close(struct rh_writer *writer)
{
	if (!writer)
		return;
	if (writer->write_fd >= 0)
		close(writer->write_fd);
	if (writer->read_fd >= 0)
		close(writer->read_fd);
	writer->write_fd = -1;
	writer->read_fd = -1;
	writer->lock_held = 0;
	rh_writer_reset_plan(writer);
	free(writer->excluded);
	writer->excluded = NULL;
	writer->excluded_count = 0;
	writer->excluded_capacity = 0;
	free(writer->raw_wal_allowed);
	writer->raw_wal_allowed = NULL;
	writer->raw_wal_allowed_count = 0;
	writer->raw_wal_allowed_capacity = 0;
	free(writer->path);
	writer->path = NULL;
}

int rh_writer_pause_for_rescan(struct rh_writer *writer)
{
	if (!writer || writer->read_fd < 0 || writer->write_fd >= 0 ||
			!writer->lock_held || writer->operation_count || writer->backend) {
		errno = EBUSY;
		return -1;
	}
	if (flock(writer->read_fd, LOCK_UN))
		return -1;
	writer->lock_held = 0;
	return 0;
}

int rh_writer_resume_after_rescan(struct rh_writer *writer)
{
	if (!writer || writer->read_fd < 0 || writer->write_fd >= 0 ||
			writer->lock_held || writer->operation_count || writer->backend) {
		errno = EBUSY;
		return -1;
	}
	if (flock(writer->read_fd, LOCK_EX | LOCK_NB))
		return -1;
	writer->lock_held = 1;
	return 0;
}

int rh_writer_set_backend(struct rh_writer *writer,
		const struct rh_write_backend_ops *ops, void *opaque)
{
	if (!writer || writer->commit_started) {
		errno = EBUSY;
		return -1;
	}
	writer->backend = ops;
	writer->backend_opaque = opaque;
	return 0;
}

static int rh_writer_add_range(struct rh_write_range **ranges,
		size_t *count, size_t *capacity, uint64_t offset, uint64_t length)
{
	struct rh_write_range *grown;
	size_t next;

	if (!ranges || !count || !capacity || *count == SIZE_MAX) {
		errno = EOVERFLOW;
		return -1;
	}
	if (*count == *capacity) {
		next = *capacity ? *capacity : 64U;
		if (next > SIZE_MAX / 2U)
			next = *count + 1U;
		else
			next *= 2U;
		if (next < *count + 1U || next > SIZE_MAX / sizeof(*grown)) {
			errno = EOVERFLOW;
			return -1;
		}
		grown = realloc(*ranges, next * sizeof(*grown));
		if (!grown)
			return -1;
		*ranges = grown;
		*capacity = next;
	}
	(*ranges)[*count].offset = offset;
	(*ranges)[*count].length = length;
	(*count)++;
	return 0;
}

int rh_writer_exclude(struct rh_writer *writer, uint64_t offset,
		uint64_t length)
{
	if (!writer || !length || offset > writer->device_size ||
			length > writer->device_size - offset) {
		errno = EINVAL;
		return -1;
	}
	return rh_writer_add_range(&writer->excluded, &writer->excluded_count,
		&writer->excluded_capacity, offset, length);
}

int rh_writer_allow_raw_wal(struct rh_writer *writer, uint64_t offset,
		uint64_t length)
{
	if (!writer || !length || offset > writer->device_size ||
			length > writer->device_size - offset) {
		errno = EINVAL;
		return -1;
	}
	return rh_writer_add_range(&writer->raw_wal_allowed,
		&writer->raw_wal_allowed_count, &writer->raw_wal_allowed_capacity,
		offset, length);
}

int rh_writer_restore_restrictions(struct rh_writer *writer,
		size_t excluded_count, size_t raw_wal_allowed_count)
{
	if (!writer || excluded_count > writer->excluded_count ||
			raw_wal_allowed_count > writer->raw_wal_allowed_count ||
			writer->commit_started) {
		errno = EINVAL;
		return -1;
	}
	if (writer->excluded_count != excluded_count)
		memset(writer->excluded + excluded_count, 0,
			(writer->excluded_count - excluded_count) *
				sizeof(writer->excluded[0]));
	if (writer->raw_wal_allowed_count != raw_wal_allowed_count)
		memset(writer->raw_wal_allowed + raw_wal_allowed_count, 0,
			(writer->raw_wal_allowed_count - raw_wal_allowed_count) *
				sizeof(writer->raw_wal_allowed[0]));
	writer->excluded_count = excluded_count;
	writer->raw_wal_allowed_count = raw_wal_allowed_count;
	return 0;
}

static int rh_raw_wal_range_allowed(const struct rh_writer *writer,
		uint64_t offset, size_t length)
{
	size_t i;

	for (i = 0; i < writer->raw_wal_allowed_count; i++) {
		uint64_t start = writer->raw_wal_allowed[i].offset;
		uint64_t allowed = writer->raw_wal_allowed[i].length;
		if (offset >= start && offset - start <= allowed &&
			length <= allowed - (offset - start))
			return 1;
	}
	return 0;
}

int rh_writer_staged_read(struct rh_writer *writer, size_t operation_count,
		uint64_t offset, size_t length, void *buffer)
{
	size_t i;
	unsigned char *out = buffer;
	uint64_t end;

	if (!writer || writer->read_fd < 0 || operation_count >
		writer->operation_count || (!buffer && length) ||
		offset > writer->device_size || length > writer->device_size - offset) {
		errno = EINVAL;
		return -1;
	}
	if (!length)
		return 0;
	if (rh_full_pread(writer->read_fd, out, length, offset))
		return -1;
	end = offset + length;
	for (i = 0; i < operation_count; i++) {
		const struct rh_write_operation *op = &writer->operations[i];
		uint64_t op_end = op->offset + op->length;
		uint64_t first, last;
		if (op_end <= offset || op->offset >= end)
			continue;
		first = op->offset > offset ? op->offset : offset;
		last = op_end < end ? op_end : end;
		memcpy(out + (first - offset), op->after + (first - op->offset),
			(size_t)(last - first));
	}
	return 0;
}

#ifdef ROOTHEALTH_REPAIR_TESTING
static int rh_read_fault(uint64_t offset)
{
	const char *setting = getenv("ROOTHEALTH_REPAIR_TEST_FAIL");
	char expected[64];

	if (!setting)
		return 0;
	snprintf(expected, sizeof(expected), "read-offset:%"PRIu64, offset);
	if (strcmp(setting, expected))
		return 0;
	errno = EIO;
	return -1;
}
#else
static int rh_read_fault(uint64_t offset __attribute__((unused)))
{
	return 0;
}
#endif

int rh_writer_read(struct rh_writer *writer, uint64_t offset, size_t length,
		void *buffer)
{
	if (rh_read_fault(offset))
		return -1;
	return rh_writer_staged_read(writer, writer ? writer->operation_count : 0,
		offset, length, buffer);
}

static int rh_overlaps_exclusion(const struct rh_writer *writer,
		uint64_t offset, uint64_t length)
{
	size_t i;
	uint64_t end = offset + length;
	for (i = 0; i < writer->excluded_count; i++) {
		uint64_t xend = writer->excluded[i].offset +
			writer->excluded[i].length;
		if (offset < xend && writer->excluded[i].offset < end)
			return 1;
	}
	return 0;
}

int rh_writer_range_excluded(const struct rh_writer *writer, uint64_t offset,
		uint64_t length)
{
	if (!writer || !length || offset > writer->device_size ||
		length > writer->device_size - offset) {
		errno = EINVAL;
		return -1;
	}
	return rh_overlaps_exclusion(writer, offset, length);
}

int rh_writer_current_read(struct rh_writer *writer, uint64_t offset,
		size_t length, void *buffer)
{
	if (!writer || writer->write_fd < 0 || !buffer || !length ||
		offset > writer->device_size || length > writer->device_size - offset) {
		errno = EINVAL;
		return -1;
	}
	return rh_full_pread(writer->write_fd, buffer, length, offset);
}

static int rh_semantic_target_full_record(
		const struct rh_write_semantic_target *target);
static int rh_semantic_target_pretransaction_initialize(
		enum rh_write_kind kind,
		const struct rh_write_semantic_target *target, uint64_t offset,
		size_t length);

/*
 * Hash the logical bytes named by a semantic target.  Raw MFT records carry
 * update-sequence protection on disk, while their semantic offsets name the
 * post-fixup record.  WAL descriptor validation must therefore use the same
 * logical view as operation planning; hashing the raw undo slice would bind
 * the USA sector trailer rather than the named attribute bytes.
 */
int rh_write_semantic_payload_hash(enum rh_write_kind kind,
		const struct rh_write_semantic_target *target, uint64_t offset,
		size_t length, const unsigned char *payload, unsigned char output[32])
{
	unsigned char fixed[1024];
	const MFT_RECORD *mft;
	uint64_t relative;
	uint16_t usa_offset, usa_count;
	int mft_object;

	if (!target || !payload || !output ||
			target->semantic_target_offset < offset)
		return -1;
	relative = target->semantic_target_offset - offset;
	if (relative > length || target->semantic_target_length >
			length - (size_t)relative)
		return -1;
	mft_object = target->object == RH_WRITE_TARGET_MFT_RECORD_PRIMARY ||
		target->object == RH_WRITE_TARGET_MFT_RECORD_MIRROR;
	if (mft_object && kind != RH_WRITE_VOLUME_DIRTY_SET &&
			kind != RH_WRITE_VOLUME_DIRTY_CLEAR &&
			!rh_semantic_target_pretransaction_initialize(kind, target,
				offset, length)) {
		if (length != sizeof(fixed))
			return -1;
		memcpy(fixed, payload, sizeof(fixed));
		if (ntfs_mst_post_read_fixup((NTFS_RECORD *)fixed, sizeof(fixed)))
			return -1;
		mft = (const MFT_RECORD *)fixed;
		usa_offset = le16_to_cpu(mft->usa_ofs);
		usa_count = le16_to_cpu(mft->usa_count);
		if (mft->magic != magic_FILE || usa_count != 3U ||
				usa_offset > sizeof(fixed) ||
				(size_t)usa_count * sizeof(uint16_t) >
					sizeof(fixed) - usa_offset)
			return -1;
		rh_sha256(fixed + relative,
			(size_t)target->semantic_target_length, output);
		return 0;
	}
	rh_sha256(payload + relative,
		(size_t)target->semantic_target_length, output);
	return 0;
}

static int rh_semantic_hash_operation(enum rh_write_kind kind,
		const struct rh_write_semantic_target *target, uint64_t offset,
		size_t length, const unsigned char *before, const unsigned char *after,
		unsigned char before_hash[32], unsigned char after_hash[32])
{
	uint64_t relative;
	int mft_object;
	int bitmap_kind = kind == RH_WRITE_INDEX_BITMAP ||
		kind == RH_WRITE_BITMAP_MFT || kind == RH_WRITE_BITMAP_CLUSTER;

	if (!target || !before || !after || target->semantic_target_offset < offset)
		return -1;
	relative = target->semantic_target_offset - offset;
	if (relative > length || target->semantic_target_length >
			length - (size_t)relative)
		return -1;
	mft_object = target->object == RH_WRITE_TARGET_MFT_RECORD_PRIMARY ||
		target->object == RH_WRITE_TARGET_MFT_RECORD_MIRROR;
	if (rh_semantic_target_pretransaction_initialize(kind, target, offset,
			length)) {
		unsigned char fixed_after[1024];
		const MFT_RECORD *after_mft;
		uint16_t usa_offset, usa_count;
		uint32_t bytes_in_use, attrs_offset;

		if (length != sizeof(fixed_after) || !memcmp(before, after, length))
			return -1;
		memcpy(fixed_after, after, sizeof(fixed_after));
		if (ntfs_mst_post_read_fixup((NTFS_RECORD *)fixed_after,
				sizeof(fixed_after)))
			return -1;
		after_mft = (const MFT_RECORD *)fixed_after;
		usa_offset = le16_to_cpu(after_mft->usa_ofs);
		usa_count = le16_to_cpu(after_mft->usa_count);
		bytes_in_use = le32_to_cpu(after_mft->bytes_in_use);
		attrs_offset = le16_to_cpu(after_mft->attrs_offset);
		if (after_mft->magic != magic_FILE || usa_count != 3U ||
				usa_offset < sizeof(NTFS_RECORD) ||
				usa_offset > sizeof(fixed_after) ||
				(size_t)usa_count * sizeof(uint16_t) >
					sizeof(fixed_after) - usa_offset ||
				le32_to_cpu(after_mft->mft_record_number) !=
					target->owner_mft_record ||
				le16_to_cpu(after_mft->sequence_number) !=
					target->owner_sequence ||
				le32_to_cpu(after_mft->bytes_allocated) !=
					sizeof(fixed_after) || bytes_in_use < sizeof(*after_mft) ||
				bytes_in_use > sizeof(fixed_after) || (bytes_in_use & 7U) ||
				attrs_offset < sizeof(*after_mft) || (attrs_offset & 7U) ||
				attrs_offset > bytes_in_use - sizeof(uint32_t))
			return -1;
		/* The stale/free before record may be arbitrary and need not be a
		 * decodable FILE record.  Exact raw hashes bind WAL undo and redo. */
		rh_sha256(before, length, before_hash);
		rh_sha256(after, length, after_hash);
		return 0;
	}
	if (mft_object && kind != RH_WRITE_VOLUME_DIRTY_SET &&
			kind != RH_WRITE_VOLUME_DIRTY_CLEAR) {
		unsigned char fixed_before[1024], fixed_after[1024];
		unsigned char compare_before[1024], compare_after[1024];
		const MFT_RECORD *before_mft, *after_mft;
		uint16_t usa_offset, usa_count;
		size_t usa_bytes;

		if (length != sizeof(fixed_before))
			return -1;
		memcpy(fixed_before, before, sizeof(fixed_before));
		memcpy(fixed_after, after, sizeof(fixed_after));
		if (ntfs_mst_post_read_fixup((NTFS_RECORD *)fixed_before,
				sizeof(fixed_before)) ||
				ntfs_mst_post_read_fixup((NTFS_RECORD *)fixed_after,
					sizeof(fixed_after)))
			return -1;
		before_mft = (const MFT_RECORD *)fixed_before;
		after_mft = (const MFT_RECORD *)fixed_after;
		usa_offset = le16_to_cpu(before_mft->usa_ofs);
		usa_count = le16_to_cpu(before_mft->usa_count);
		usa_bytes = (size_t)usa_count * sizeof(uint16_t);
		if (before_mft->magic != magic_FILE || after_mft->magic != magic_FILE ||
				le16_to_cpu(after_mft->usa_ofs) != usa_offset ||
				le16_to_cpu(after_mft->usa_count) != usa_count ||
				usa_count != 3U || usa_offset > sizeof(fixed_before) ||
				usa_bytes > sizeof(fixed_before) - usa_offset)
			return -1;
		rh_sha256(fixed_before + relative,
			(size_t)target->semantic_target_length, before_hash);
		rh_sha256(fixed_after + relative,
			(size_t)target->semantic_target_length, after_hash);
		/*
		 * A raw MFT operation may differ solely because its update-sequence
		 * number was regenerated.  That is not evidence that the sealed
		 * logical attribute subrange changed.  Refuse such semantic no-ops
		 * before the USA bytes are deliberately excluded below.
		 */
		if (!memcmp(fixed_before + relative, fixed_after + relative,
				(size_t)target->semantic_target_length))
			return -1;
		memcpy(compare_before, fixed_before, sizeof(compare_before));
		memcpy(compare_after, fixed_after, sizeof(compare_after));
		memset(compare_before + relative, 0,
			(size_t)target->semantic_target_length);
		memset(compare_after + relative, 0,
			(size_t)target->semantic_target_length);
		memset(compare_before + usa_offset, 0, usa_bytes);
		memset(compare_after + usa_offset, 0, usa_bytes);
		if (memcmp(compare_before, compare_after, sizeof(compare_before)))
			return -1;
		if (bitmap_kind) {
			unsigned char old_byte = fixed_before[relative];
			unsigned char new_byte = fixed_after[relative];
			unsigned char set_mask = (unsigned char)~old_byte & new_byte;
			unsigned char clear_mask = old_byte & (unsigned char)~new_byte;

			if (target->semantic_target_length != 1U ||
					!!set_mask == !!clear_mask ||
					(set_mask && (set_mask & (unsigned char)(set_mask - 1U))) ||
					(clear_mask && (clear_mask &
					 (unsigned char)(clear_mask - 1U))) ||
					!!(target->flags & RH_WRITE_TARGET_SET_ONLY) != !!set_mask ||
					!!(target->flags & RH_WRITE_TARGET_CLEAR_ONLY) !=
						!!clear_mask)
				return -1;
		}
		return 0;
	}
	if (bitmap_kind) {
		unsigned char old_byte = before[relative];
		unsigned char new_byte = after[relative];
		unsigned char set_mask = (unsigned char)~old_byte & new_byte;
		unsigned char clear_mask = old_byte & (unsigned char)~new_byte;

		if (target->semantic_target_length != 1U ||
				!!set_mask == !!clear_mask ||
				(set_mask && (set_mask & (unsigned char)(set_mask - 1U))) ||
				(clear_mask && (clear_mask &
				 (unsigned char)(clear_mask - 1U))) ||
				!!(target->flags & RH_WRITE_TARGET_SET_ONLY) != !!set_mask ||
				!!(target->flags & RH_WRITE_TARGET_CLEAR_ONLY) != !!clear_mask)
			return -1;
	}
	rh_sha256(before + relative, (size_t)target->semantic_target_length,
		before_hash);
	rh_sha256(after + relative, (size_t)target->semantic_target_length,
		after_hash);
	return 0;
}

static int rh_bytes_all_zero(const unsigned char *bytes, size_t length)
{
	size_t i;

	for (i = 0; i < length; i++)
		if (bytes[i])
			return 0;
	return 1;
}

static int rh_semantic_target_has_attribute(
		const struct rh_write_semantic_target *target)
{
	return target->attribute_type != 0;
}

static int rh_semantic_target_full_record(
		const struct rh_write_semantic_target *target)
{
	return !target->attribute_type && !target->attribute_instance &&
		!target->attribute_name_length &&
		rh_bytes_all_zero(target->attribute_name_hash,
			sizeof(target->attribute_name_hash));
}

static int rh_semantic_target_pretransaction_initialize(
		enum rh_write_kind kind,
		const struct rh_write_semantic_target *target, uint64_t offset,
		size_t length)
{
	const uint16_t exact_flags = RH_WRITE_TARGET_PRIMARY |
		RH_WRITE_TARGET_RESIDENT | RH_WRITE_TARGET_PRETRANSACTION_FREE |
		RH_WRITE_TARGET_NATIVE_LOG_DERIVED;

	return target && kind == RH_WRITE_LOGFILE_REDO &&
		target->object == RH_WRITE_TARGET_MFT_RECORD_PRIMARY &&
		target->owner_mft_record > 3U && target->owner_sequence &&
		rh_semantic_target_full_record(target) &&
		target->flags == exact_flags && target->lowest_vcn == -1 &&
		target->logical_vcn == -1 && target->lcn == -1 &&
		!target->logical_offset && target->logical_length == 1024U &&
		target->semantic_target_offset == offset &&
		target->semantic_target_length == 1024U && length == 1024U;
}

static int rh_semantic_kind_accepts_object(enum rh_write_kind kind,
		enum rh_write_target_object object)
{
	switch (kind) {
	case RH_WRITE_BOOT_PRIMARY:
		return object == RH_WRITE_TARGET_BOOT_PRIMARY;
	case RH_WRITE_BOOT_BACKUP:
		return object == RH_WRITE_TARGET_BOOT_BACKUP;
	case RH_WRITE_MFT_PRIMARY:
		return object == RH_WRITE_TARGET_MFT_RECORD_PRIMARY;
	case RH_WRITE_MFT_MIRROR:
		return object == RH_WRITE_TARGET_MFT_RECORD_MIRROR;
	case RH_WRITE_LOGFILE_REDO:
		return object == RH_WRITE_TARGET_MFT_RECORD_PRIMARY ||
			object == RH_WRITE_TARGET_MFT_RECORD_MIRROR ||
			object == RH_WRITE_TARGET_NONRESIDENT_ATTRIBUTE;
	case RH_WRITE_LOGFILE_RESTART:
		return object == RH_WRITE_TARGET_NONRESIDENT_ATTRIBUTE;
	case RH_WRITE_MFT_RECORD:
	case RH_WRITE_RUNLIST_MAPPING_PAIRS:
	case RH_WRITE_INDEX_ROOT:
		return object == RH_WRITE_TARGET_MFT_RECORD_PRIMARY ||
			object == RH_WRITE_TARGET_MFT_RECORD_MIRROR;
	case RH_WRITE_ATTRIBUTE_LIST:
	case RH_WRITE_ATTRIBUTE_DATA:
	case RH_WRITE_INDEX_BITMAP:
	case RH_WRITE_RECOVERY_NAMESPACE:
	case RH_WRITE_REPARSE_INDEX:
		return object == RH_WRITE_TARGET_MFT_RECORD_PRIMARY ||
			object == RH_WRITE_TARGET_MFT_RECORD_MIRROR ||
			object == RH_WRITE_TARGET_NONRESIDENT_ATTRIBUTE;
	case RH_WRITE_INDEX_ALLOCATION:
	case RH_WRITE_SECURE_SDS:
	case RH_WRITE_UPCASE_DATA:
	case RH_WRITE_ATTRDEF_DATA:
	case RH_WRITE_BITMAP_MFT:
	case RH_WRITE_BITMAP_CLUSTER:
		return object == RH_WRITE_TARGET_NONRESIDENT_ATTRIBUTE;
	case RH_WRITE_SECURE_SDH:
	case RH_WRITE_SECURE_SII:
		return object == RH_WRITE_TARGET_MFT_RECORD_PRIMARY ||
			object == RH_WRITE_TARGET_MFT_RECORD_MIRROR ||
			object == RH_WRITE_TARGET_NONRESIDENT_ATTRIBUTE;
	case RH_WRITE_CLUSTER_DATA:
		return object == RH_WRITE_TARGET_NONRESIDENT_ATTRIBUTE ||
			object == RH_WRITE_TARGET_PROVEN_FREE_ALLOCATION;
	case RH_WRITE_VOLUME_DIRTY_SET:
	case RH_WRITE_VOLUME_DIRTY_CLEAR:
		return object == RH_WRITE_TARGET_MFT_RECORD_PRIMARY ||
			object == RH_WRITE_TARGET_MFT_RECORD_MIRROR;
	case RH_WRITE_KIND_COUNT:
		break;
	}
	return 0;
}

static int rh_semantic_name_is(const struct rh_write_semantic_target *target,
		const char *ascii)
{
	unsigned char encoded[64], digest[32];
	size_t length = strlen(ascii), i;

	if (length > sizeof(encoded) / 2U ||
			target->attribute_name_length != length)
		return 0;
	for (i = 0; i < length; i++) {
		encoded[2U * i] = (unsigned char)ascii[i];
		encoded[2U * i + 1U] = 0;
	}
	rh_sha256(encoded, length * 2U, digest);
	return !memcmp(digest, target->attribute_name_hash, sizeof(digest));
}

static int rh_semantic_name_is_unnamed(
		const struct rh_write_semantic_target *target)
{
	return rh_semantic_name_is(target, "");
}

static int rh_semantic_kind_fields_valid(enum rh_write_kind kind,
		const struct rh_write_semantic_target *target)
{
	int mft_object = target->object == RH_WRITE_TARGET_MFT_RECORD_PRIMARY ||
		target->object == RH_WRITE_TARGET_MFT_RECORD_MIRROR;
	int nonresident = target->object ==
		RH_WRITE_TARGET_NONRESIDENT_ATTRIBUTE;

	switch (kind) {
	case RH_WRITE_BOOT_PRIMARY:
	case RH_WRITE_BOOT_BACKUP:
		return !target->attribute_type;
	case RH_WRITE_MFT_PRIMARY:
	case RH_WRITE_MFT_MIRROR:
	case RH_WRITE_MFT_RECORD:
		return mft_object && rh_semantic_target_full_record(target) &&
			(kind != RH_WRITE_MFT_PRIMARY ||
			 target->owner_mft_record <= 3U);
	case RH_WRITE_LOGFILE_REDO:
		return !!(target->flags & RH_WRITE_TARGET_NATIVE_LOG_DERIVED) &&
			(nonresident || mft_object);
	case RH_WRITE_LOGFILE_RESTART:
		return nonresident && target->owner_mft_record == 2U &&
			target->attribute_type == 0x80U &&
			rh_semantic_name_is_unnamed(target);
	case RH_WRITE_ATTRIBUTE_LIST:
		return target->attribute_type == 0x20U &&
			rh_semantic_name_is_unnamed(target);
	case RH_WRITE_RUNLIST_MAPPING_PAIRS:
		return mft_object && target->attribute_type != 0;
	case RH_WRITE_ATTRIBUTE_DATA:
		return target->attribute_type == 0x80U;
	case RH_WRITE_INDEX_ROOT:
		return mft_object && target->attribute_type == 0x90U &&
			target->attribute_name_length;
	case RH_WRITE_INDEX_ALLOCATION:
		return nonresident && target->attribute_type == 0xa0U &&
			target->attribute_name_length;
	case RH_WRITE_INDEX_BITMAP:
		return target->attribute_type == 0xb0U &&
			target->attribute_name_length;
	case RH_WRITE_CLUSTER_DATA:
		return target->attribute_type == 0x80U;
	case RH_WRITE_RECOVERY_NAMESPACE:
		return (mft_object && target->attribute_type == 0x30U &&
				rh_semantic_name_is_unnamed(target)) ||
			(mft_object && target->attribute_type == 0x90U &&
				target->attribute_name_length) ||
			(nonresident && (target->attribute_type == 0xa0U ||
				target->attribute_type == 0xb0U) &&
			 target->attribute_name_length);
	case RH_WRITE_REPARSE_INDEX:
		return target->owner_mft_record == 26U &&
			rh_semantic_name_is(target, "$R") &&
			((mft_object && target->attribute_type == 0x90U) ||
			 (nonresident && (target->attribute_type == 0xa0U ||
				target->attribute_type == 0xb0U)));
	case RH_WRITE_SECURE_SDS:
		return nonresident && target->owner_mft_record == 9U &&
			target->attribute_type == 0x80U &&
			rh_semantic_name_is(target, "$SDS");
	case RH_WRITE_SECURE_SDH:
		return target->owner_mft_record == 9U &&
			rh_semantic_name_is(target, "$SDH") &&
			((mft_object && target->attribute_type == 0x90U) ||
			 (nonresident && (target->attribute_type == 0xa0U ||
				target->attribute_type == 0xb0U)));
	case RH_WRITE_SECURE_SII:
		return target->owner_mft_record == 9U &&
			rh_semantic_name_is(target, "$SII") &&
			((mft_object && target->attribute_type == 0x90U) ||
			 (nonresident && (target->attribute_type == 0xa0U ||
				target->attribute_type == 0xb0U)));
	case RH_WRITE_UPCASE_DATA:
		return nonresident && target->owner_mft_record == 10U &&
			target->attribute_type == 0x80U &&
			rh_semantic_name_is_unnamed(target);
	case RH_WRITE_ATTRDEF_DATA:
		return nonresident && target->owner_mft_record == 4U &&
			target->attribute_type == 0x80U &&
			rh_semantic_name_is_unnamed(target);
	case RH_WRITE_BITMAP_MFT:
		return nonresident && !target->owner_mft_record &&
			target->attribute_type == 0xb0U &&
			rh_semantic_name_is_unnamed(target);
	case RH_WRITE_BITMAP_CLUSTER:
		return nonresident && target->owner_mft_record == 6U &&
			target->attribute_type == 0x80U &&
			rh_semantic_name_is_unnamed(target);
	case RH_WRITE_VOLUME_DIRTY_SET:
	case RH_WRITE_VOLUME_DIRTY_CLEAR:
		return mft_object && target->owner_mft_record == 3U &&
			target->attribute_type == 0x70U &&
			rh_semantic_name_is_unnamed(target);
	case RH_WRITE_KIND_COUNT:
		break;
	}
	return 0;
}

int rh_write_semantic_target_valid(enum rh_write_kind kind,
		const struct rh_write_semantic_target *target,
		uint64_t offset, size_t length, int require_finalized)
{
	unsigned char empty_name_hash[32];
	uint16_t location, residency, mode, expected_base_flags = 0;
	int has_attribute;

	if (kind < 0 || kind >= RH_WRITE_KIND_COUNT || !target ||
			target->seal_version != 1 ||
			target->object <= RH_WRITE_TARGET_INVALID ||
			target->object > RH_WRITE_TARGET_PROVEN_FREE_ALLOCATION ||
			(target->flags & (uint16_t)~RH_WRITE_TARGET_FLAGS_MASK) ||
			(require_finalized && !target->finalized) ||
			(!require_finalized && target->finalized) ||
			target->attribute_name_length > 255U ||
			!target->logical_length ||
			target->logical_length != target->semantic_target_length ||
			target->logical_offset > UINT64_MAX - target->logical_length ||
			offset > UINT64_MAX - length ||
			target->semantic_target_offset > UINT64_MAX -
				target->semantic_target_length ||
			!rh_semantic_kind_accepts_object(kind, target->object))
		return 0;
	if (target->object == RH_WRITE_TARGET_MFT_RECORD_PRIMARY ||
			target->object == RH_WRITE_TARGET_MFT_RECORD_MIRROR) {
		if (kind == RH_WRITE_VOLUME_DIRTY_SET ||
				kind == RH_WRITE_VOLUME_DIRTY_CLEAR) {
			if (target->semantic_target_offset != offset ||
					target->semantic_target_length != length)
				return 0;
		} else if (length != 1024U || (offset & 1023U) ||
				target->semantic_target_offset < offset ||
				target->semantic_target_length >
					offset + length - target->semantic_target_offset)
			return 0;
	} else if (target->semantic_target_offset != offset ||
			target->semantic_target_length != length)
		return 0;
	location = target->flags &
		(RH_WRITE_TARGET_PRIMARY | RH_WRITE_TARGET_MIRROR);
	residency = target->flags &
		(RH_WRITE_TARGET_RESIDENT | RH_WRITE_TARGET_NONRESIDENT);
	mode = target->flags & (RH_WRITE_TARGET_SET_ONLY |
		RH_WRITE_TARGET_CLEAR_ONLY);
	if (location == (RH_WRITE_TARGET_PRIMARY | RH_WRITE_TARGET_MIRROR) ||
			residency == (RH_WRITE_TARGET_RESIDENT |
			 RH_WRITE_TARGET_NONRESIDENT) ||
			mode == (RH_WRITE_TARGET_SET_ONLY |
			 RH_WRITE_TARGET_CLEAR_ONLY))
		return 0;
	if ((kind == RH_WRITE_LOGFILE_REDO ||
			kind == RH_WRITE_LOGFILE_RESTART) !=
		!!(target->flags & RH_WRITE_TARGET_NATIVE_LOG_DERIVED))
		return 0;
	if (kind != RH_WRITE_INDEX_BITMAP && kind != RH_WRITE_BITMAP_MFT &&
			kind != RH_WRITE_BITMAP_CLUSTER &&
			kind != RH_WRITE_VOLUME_DIRTY_SET &&
			kind != RH_WRITE_VOLUME_DIRTY_CLEAR && mode)
		return 0;

	switch (target->object) {
	case RH_WRITE_TARGET_BOOT_PRIMARY:
		expected_base_flags = RH_WRITE_TARGET_PRIMARY;
		if (target->owner_mft_record || target->owner_sequence ||
				!rh_semantic_target_full_record(target) ||
				target->lowest_vcn != -1 || target->logical_vcn != -1 ||
				target->lcn != -1 || target->logical_offset)
			return 0;
		break;
	case RH_WRITE_TARGET_BOOT_BACKUP:
		expected_base_flags = RH_WRITE_TARGET_MIRROR;
		if (target->owner_mft_record || target->owner_sequence ||
				!rh_semantic_target_full_record(target) ||
				target->lowest_vcn != -1 || target->logical_vcn != -1 ||
				target->lcn != -1 || target->logical_offset)
			return 0;
		break;
	case RH_WRITE_TARGET_MFT_RECORD_PRIMARY:
		expected_base_flags = RH_WRITE_TARGET_PRIMARY |
			RH_WRITE_TARGET_RESIDENT;
		if (rh_semantic_target_pretransaction_initialize(kind, target,
				offset, length))
			expected_base_flags |= RH_WRITE_TARGET_PRETRANSACTION_FREE;
		if (!target->owner_sequence || target->lowest_vcn != -1 ||
				target->logical_vcn != -1 || target->lcn != -1)
			return 0;
		break;
	case RH_WRITE_TARGET_MFT_RECORD_MIRROR:
		expected_base_flags = RH_WRITE_TARGET_MIRROR |
			RH_WRITE_TARGET_RESIDENT;
		if (!target->owner_sequence || target->owner_mft_record > 3U ||
				target->lowest_vcn != -1 || target->logical_vcn != -1 ||
				target->lcn != -1)
			return 0;
		break;
	case RH_WRITE_TARGET_NONRESIDENT_ATTRIBUTE:
		expected_base_flags = RH_WRITE_TARGET_NONRESIDENT;
		if (!target->owner_sequence || !target->attribute_type ||
				target->lowest_vcn < 0 || target->logical_vcn <
				target->lowest_vcn || target->lcn < 0)
			return 0;
		break;
	case RH_WRITE_TARGET_PROVEN_FREE_ALLOCATION:
		expected_base_flags = RH_WRITE_TARGET_NONRESIDENT |
			RH_WRITE_TARGET_PRETRANSACTION_FREE;
		if (!target->owner_sequence || !target->attribute_type ||
				target->lowest_vcn < 0 || target->logical_vcn <
				target->lowest_vcn || target->lcn < 0)
			return 0;
		break;
	case RH_WRITE_TARGET_INVALID:
		return 0;
	}
	if ((target->flags & (RH_WRITE_TARGET_PRIMARY |
			RH_WRITE_TARGET_MIRROR | RH_WRITE_TARGET_RESIDENT |
			RH_WRITE_TARGET_NONRESIDENT |
			RH_WRITE_TARGET_PRETRANSACTION_FREE)) != expected_base_flags)
		return 0;

	has_attribute = rh_semantic_target_has_attribute(target);
	if (has_attribute) {
		if (rh_bytes_all_zero(target->attribute_name_hash,
				sizeof(target->attribute_name_hash)))
			return 0;
		rh_sha256("", 0, empty_name_hash);
		if (!target->attribute_name_length &&
				memcmp(target->attribute_name_hash, empty_name_hash,
					sizeof(empty_name_hash)))
			return 0;
	} else if (!rh_semantic_target_full_record(target))
		return 0;
	if ((target->object == RH_WRITE_TARGET_NONRESIDENT_ATTRIBUTE ||
			target->object == RH_WRITE_TARGET_PROVEN_FREE_ALLOCATION) &&
			!has_attribute)
		return 0;
	if ((kind == RH_WRITE_MFT_PRIMARY || kind == RH_WRITE_MFT_MIRROR) &&
			!rh_semantic_target_full_record(target))
		return 0;
	if ((kind == RH_WRITE_MFT_PRIMARY || kind == RH_WRITE_MFT_MIRROR ||
			kind == RH_WRITE_MFT_RECORD) &&
			(target->logical_offset || target->logical_length != length ||
			 target->semantic_target_offset != offset ||
			 target->semantic_target_length != length))
		return 0;
	if (!rh_semantic_kind_fields_valid(kind, target))
		return 0;
	if ((kind == RH_WRITE_VOLUME_DIRTY_SET ||
			kind == RH_WRITE_VOLUME_DIRTY_CLEAR) &&
			(target->owner_mft_record != 3U || target->attribute_type != 0x70U ||
			 target->attribute_name_length || target->logical_offset != 0x0aU ||
			 target->logical_length != 2U ||
			 mode != (kind == RH_WRITE_VOLUME_DIRTY_SET ?
				RH_WRITE_TARGET_SET_ONLY : RH_WRITE_TARGET_CLEAR_ONLY)))
		return 0;
	if (kind == RH_WRITE_BITMAP_MFT &&
			(target->owner_mft_record != 0U || target->attribute_type != 0xb0U))
		return 0;
	if (kind == RH_WRITE_BITMAP_CLUSTER &&
			(target->owner_mft_record != 6U || target->attribute_type != 0x80U))
		return 0;
	if ((kind == RH_WRITE_INDEX_BITMAP || kind == RH_WRITE_BITMAP_MFT ||
			kind == RH_WRITE_BITMAP_CLUSTER) &&
			mode != RH_WRITE_TARGET_SET_ONLY &&
			mode != RH_WRITE_TARGET_CLEAR_ONLY)
		return 0;
	if ((kind == RH_WRITE_INDEX_BITMAP || kind == RH_WRITE_BITMAP_MFT ||
			kind == RH_WRITE_BITMAP_CLUSTER) &&
			(target->logical_length != 1U ||
			 target->semantic_target_length != 1U ||
			 ((target->object == RH_WRITE_TARGET_MFT_RECORD_PRIMARY ||
			   target->object == RH_WRITE_TARGET_MFT_RECORD_MIRROR) ?
				length != 1024U : length != 1U)))
		return 0;
	if (kind == RH_WRITE_LOGFILE_RESTART &&
			(target->owner_mft_record != 2U || target->attribute_type != 0x80U))
		return 0;
	if (!require_finalized &&
			(target->evidence_version || target->evidence_generation ||
			 !rh_bytes_all_zero(target->evidence_hash,
				sizeof(target->evidence_hash)) ||
			 !rh_bytes_all_zero(target->staged_view_hash,
				sizeof(target->staged_view_hash))))
		return 0;
	if (!require_finalized &&
			(rh_bytes_all_zero(target->semantic_before_hash,
				sizeof(target->semantic_before_hash)) !=
			 rh_bytes_all_zero(target->semantic_after_hash,
				sizeof(target->semantic_after_hash))))
		return 0;
	if (require_finalized &&
			(!target->evidence_version || !target->evidence_generation ||
			 rh_bytes_all_zero(target->evidence_hash,
				sizeof(target->evidence_hash)) ||
			 rh_bytes_all_zero(target->staged_view_hash,
				sizeof(target->staged_view_hash)) ||
			 rh_bytes_all_zero(target->semantic_before_hash,
				sizeof(target->semantic_before_hash)) ||
			 rh_bytes_all_zero(target->semantic_after_hash,
				sizeof(target->semantic_after_hash))))
		return 0;
	return 1;
}

int rh_write_operation_semantics_valid(const struct rh_write_operation *op,
		int require_finalized)
{
	unsigned char before_hash[32], after_hash[32];

	if (!op || !op->before || !op->after ||
			!rh_write_semantic_target_valid(op->kind, &op->target, op->offset,
				op->length, require_finalized) ||
			rh_semantic_hash_operation(op->kind, &op->target, op->offset,
				op->length, op->before, op->after, before_hash, after_hash))
		return 0;
	return !memcmp(before_hash, op->target.semantic_before_hash,
			sizeof(before_hash)) &&
		!memcmp(after_hash, op->target.semantic_after_hash,
			sizeof(after_hash));
}

int rh_writer_plan_typed(struct rh_writer *writer, enum rh_write_kind kind,
		uint64_t offset, size_t length, const void *after,
		const struct rh_write_semantic_target *target)
{
	struct rh_write_operation *op;

	if (!writer || writer->commit_started || kind < 0 ||
		kind >= RH_WRITE_KIND_COUNT || !length || !after ||
		length > RH_MAX_OPERATION_BYTES || offset > writer->device_size ||
		length > writer->device_size - offset ||
		length > RH_MAX_PLANNED_BYTES - writer->planned_bytes ||
		rh_overlaps_exclusion(writer, offset, length)) {
		errno = EINVAL;
		return -1;
	}
	if (target && !rh_write_semantic_target_valid(kind, target, offset,
			length, 0)) {
		errno = EINVAL;
		return -1;
	}
	if (writer->operation_count >= RH_MAX_OPERATIONS) {
		errno = E2BIG;
		return -1;
	}
	if (writer->operation_count == writer->operation_capacity) {
		size_t capacity = writer->operation_capacity ?
			writer->operation_capacity * 2 : 64;
		void *grown;
		if (capacity > RH_MAX_OPERATIONS)
			capacity = RH_MAX_OPERATIONS;
		grown = realloc(writer->operations, capacity * sizeof(*op));
		if (!grown)
			return -1;
		writer->operations = grown;
		writer->operation_capacity = capacity;
	}
	op = &writer->operations[writer->operation_count];
	memset(op, 0, sizeof(*op));
	op->before = malloc(length);
	op->after = malloc(length);
	if (!op->before || !op->after) {
		free(op->before);
		free(op->after);
		memset(op, 0, sizeof(*op));
		return -1;
	}
	if (rh_writer_read(writer, offset, length, op->before)) {
		free(op->before);
		free(op->after);
		memset(op, 0, sizeof(*op));
		return -1;
	}
	if (!memcmp(op->before, after, length)) {
		free(op->before);
		free(op->after);
		memset(op, 0, sizeof(*op));
		return 0;
	}
	op->kind = kind;
	op->offset = offset;
	op->length = length;
	memcpy(op->after, after, length);
	if (target) {
		op->target = *target;
		if (rh_semantic_hash_operation(kind, target, offset, length,
				op->before, op->after,
				op->target.semantic_before_hash,
				op->target.semantic_after_hash)) {
			free(op->before);
			free(op->after);
			memset(op, 0, sizeof(*op));
			errno = EINVAL;
			return -1;
		}
	}
	rh_sha256_hex(op->before, length, op->before_sha256);
	rh_sha256_hex(op->after, length, op->after_sha256);
	writer->operation_count++;
	writer->planned_bytes += length;
	return 0;
}

int rh_writer_plan(struct rh_writer *writer, enum rh_write_kind kind,
		uint64_t offset, size_t length, const void *after)
{
	if (kind != RH_WRITE_BOOT_PRIMARY && kind != RH_WRITE_BOOT_BACKUP &&
			kind != RH_WRITE_MFT_PRIMARY && kind != RH_WRITE_MFT_MIRROR) {
		errno = EPERM;
		return -1;
	}
	return rh_writer_plan_typed(writer, kind, offset, length, after, NULL);
}

int rh_writer_finalize_target(struct rh_writer *writer,
		size_t operation_ordinal, uint32_t evidence_version,
		uint64_t evidence_generation, const unsigned char evidence_hash[32],
		const unsigned char staged_view_hash[32])
{
	struct rh_write_semantic_target *target;

	if (!writer || !operation_ordinal ||
			operation_ordinal > writer->operation_count || !evidence_version ||
			!evidence_hash || !staged_view_hash ||
			rh_bytes_all_zero(evidence_hash, 32) ||
			rh_bytes_all_zero(staged_view_hash, 32)) {
		errno = EINVAL;
		return -1;
	}
	target = &writer->operations[operation_ordinal - 1U].target;
	if (target->seal_version != 1 || target->finalized) {
		errno = EBUSY;
		return -1;
	}
	target->evidence_version = evidence_version;
	target->evidence_generation = evidence_generation;
	memcpy(target->evidence_hash, evidence_hash, 32);
	memcpy(target->staged_view_hash, staged_view_hash, 32);
	target->finalized = 1;
	if (!rh_write_semantic_target_valid(
			writer->operations[operation_ordinal - 1U].kind, target,
			writer->operations[operation_ordinal - 1U].offset,
			writer->operations[operation_ordinal - 1U].length, 1)) {
		memset(target->evidence_hash, 0, sizeof(target->evidence_hash));
		memset(target->staged_view_hash, 0,
			sizeof(target->staged_view_hash));
		target->evidence_version = 0;
		target->evidence_generation = 0;
		target->finalized = 0;
		errno = EINVAL;
		return -1;
	}
	return 0;
}

size_t rh_writer_plan_checkpoint(const struct rh_writer *writer)
{
	return writer ? writer->operation_count : SIZE_MAX;
}

int rh_writer_discard_after(struct rh_writer *writer, size_t checkpoint)
{
	size_t i;

	if (!writer || writer->commit_started || checkpoint >
			writer->operation_count) {
		errno = EINVAL;
		return -1;
	}
	for (i = checkpoint; i < writer->operation_count; i++) {
		if (writer->planned_bytes < writer->operations[i].length) {
			errno = EIO;
			return -1;
		}
		writer->planned_bytes -= writer->operations[i].length;
		free(writer->operations[i].before);
		free(writer->operations[i].after);
		memset(&writer->operations[i], 0,
			sizeof(writer->operations[i]));
	}
	writer->operation_count = checkpoint;
	return 0;
}

static void rh_plan_put_u32(unsigned char *output, uint32_t value)
{
	output[0] = (unsigned char)(value >> 24);
	output[1] = (unsigned char)(value >> 16);
	output[2] = (unsigned char)(value >> 8);
	output[3] = (unsigned char)value;
}

static void rh_plan_put_u64(unsigned char *output, uint64_t value)
{
	size_t i;

	for (i = 0; i < 8; i++)
		output[i] = (unsigned char)(value >> (56U - (unsigned int)i * 8U));
}

int rh_writer_plan_hash(const struct rh_writer *writer, size_t operation_count,
		unsigned char output[32])
{
	static const unsigned char magic[8] = {
		'R', 'H', 'P', 'L', 'A', 'N', 2, 0
	};
	const size_t entry_size = 208;
	unsigned char *serialized;
	size_t total, i;

	if (!writer || !output || !operation_count ||
			operation_count > writer->operation_count ||
			operation_count > (SIZE_MAX - 16) / entry_size) {
		errno = EINVAL;
		return -1;
	}
	total = 16 + operation_count * entry_size;
	serialized = calloc(1, total);
	if (!serialized)
		return -1;
	memcpy(serialized, magic, sizeof(magic));
	rh_plan_put_u64(serialized + 8, operation_count);
	for (i = 0; i < operation_count; i++) {
		const struct rh_write_operation *op = &writer->operations[i];
		unsigned char *entry = serialized + 16 + i * entry_size;

		if (op->kind < 0 || op->kind >= RH_WRITE_KIND_COUNT ||
				!op->length || !op->before || !op->after ||
				op->offset > UINT64_MAX - op->length) {
			free(serialized);
			errno = EINVAL;
			return -1;
		}
		rh_plan_put_u32(entry, RH_WRITE_ACTION_ID(op->kind));
		rh_plan_put_u64(entry + 4, op->offset);
		rh_plan_put_u64(entry + 12, op->length);
		rh_sha256(op->before, op->length, entry + 20);
		rh_sha256(op->after, op->length, entry + 52);
		rh_plan_put_u32(entry + 84, op->target.seal_version);
		rh_plan_put_u32(entry + 88, (uint32_t)op->target.object);
		rh_plan_put_u64(entry + 92, op->target.owner_mft_record);
		rh_plan_put_u32(entry + 100, op->target.owner_sequence);
		rh_plan_put_u32(entry + 104, op->target.attribute_instance);
		rh_plan_put_u32(entry + 108, op->target.attribute_type);
		rh_plan_put_u32(entry + 112, op->target.attribute_name_length);
		rh_plan_put_u32(entry + 116, op->target.flags);
		memcpy(entry + 120, op->target.attribute_name_hash, 32);
		rh_plan_put_u64(entry + 152, (uint64_t)op->target.lowest_vcn);
		rh_plan_put_u64(entry + 160, (uint64_t)op->target.logical_vcn);
		rh_plan_put_u64(entry + 168, op->target.logical_offset);
		rh_plan_put_u64(entry + 176, op->target.logical_length);
		rh_plan_put_u64(entry + 184,
			op->target.semantic_target_offset);
		rh_plan_put_u64(entry + 192,
			op->target.semantic_target_length);
		rh_plan_put_u64(entry + 200, (uint64_t)op->target.lcn);
	}
	rh_sha256(serialized, total, output);
	free(serialized);
	return 0;
}

#ifdef ROOTHEALTH_REPAIR_TESTING
static int rh_fault(const char *stage, size_t ordinal)
{
	const char *setting = getenv("ROOTHEALTH_REPAIR_TEST_FAIL");
	char expected[64];
	char powercut[64];
	if (!setting)
		return 0;
	snprintf(expected, sizeof(expected), "%s:%zu", stage, ordinal);
	snprintf(powercut, sizeof(powercut), "powercut-%s:%zu", stage, ordinal);
	if (!strcmp(setting, powercut))
		_exit(86);
	if (!strcmp(setting, expected)) {
		errno = EIO;
		return -1;
	}
	return 0;
}
#else
static int rh_fault(const char *stage __attribute__((unused)),
		size_t ordinal __attribute__((unused)))
{
	return 0;
}
#endif

static int rh_direct_kind_allowed(enum rh_write_kind kind)
{
	return kind == RH_WRITE_BOOT_PRIMARY || kind == RH_WRITE_BOOT_BACKUP ||
		kind == RH_WRITE_MFT_PRIMARY || kind == RH_WRITE_MFT_MIRROR ||
		kind == RH_WRITE_LOGFILE_REDO || kind == RH_WRITE_LOGFILE_RESTART ||
		kind == RH_WRITE_VOLUME_DIRTY_SET ||
		kind == RH_WRITE_VOLUME_DIRTY_CLEAR;
}

static int rh_open_write_fd(struct rh_writer *writer)
{
	struct stat st;
	uint64_t size;

	writer->write_fd = open(writer->path,
		O_RDWR | O_CLOEXEC | O_NOFOLLOW | O_EXCL);
	if (writer->write_fd < 0)
		return -1;
	if (fstat(writer->write_fd, &st) || st.st_dev != writer->device_id ||
		st.st_ino != writer->inode_id || rh_get_size(writer->write_fd, &st,
			&size) || size != writer->device_size) {
		errno = ESTALE;
		close(writer->write_fd);
		writer->write_fd = -1;
		return -1;
	}
	return 0;
}

int rh_writer_sync(struct rh_writer *writer)
{
	if (!writer || writer->write_fd < 0) {
		errno = EINVAL;
		return -1;
	}
	if (rh_fault("before-sync", writer->sync_count + 1))
		return -1;
	if (fsync(writer->write_fd))
		return -1;
	writer->sync_count++;
	if (writer->backend && writer->backend->barrier &&
		writer->backend->barrier(writer->backend_opaque,
			writer->last_verified_ordinal))
		return -1;
	return rh_fault("after-sync", writer->sync_count);
}

int rh_writer_commit(struct rh_writer *writer)
{
	unsigned char *check = NULL;
	size_t i;
	int result = -1;
	int restart_barrier_done = 0;
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
	const char *test_stage = "preflight";
#endif

	if (!writer || writer->commit_started || !writer->operation_count) {
		errno = EINVAL;
		return -1;
	}
	if (!writer->backend || !writer->backend->persistent_undo) {
		for (i = 0; i < writer->operation_count; i++) {
			if (!rh_direct_kind_allowed(writer->operations[i].kind)) {
				errno = EPERM;
				return -1;
			}
		}
	} else {
		for (i = 0; i < writer->operation_count; i++) {
			const struct rh_write_operation *op =
				&writer->operations[i];

			if (!rh_write_semantic_target_valid(op->kind, &op->target,
					op->offset, op->length, 1)) {
				errno = EPERM;
				return -1;
			}
		}
	}
	if (rh_open_write_fd(writer))
		goto out;
	writer->commit_started = 1;
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
	test_stage = "backend-begin";
#endif
	if (writer->backend && writer->backend->begin &&
		writer->backend->begin(writer->backend_opaque, writer->operations,
			writer->operation_count))
		goto abort;
	for (i = 0; i < writer->operation_count; i++) {
		struct rh_write_operation *op = &writer->operations[i];
		size_t first_boundary = writer->write_boundaries;
		unsigned char *grown = realloc(check, op->length);
		if (!grown)
			goto abort;
		check = grown;
		if (op->kind == RH_WRITE_LOGFILE_RESTART &&
			!restart_barrier_done) {
			if (rh_writer_sync(writer))
				goto abort;
			restart_barrier_done = 1;
		}
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
		test_stage = "target-preimage";
#endif
		if (rh_full_pread(writer->write_fd, check, op->length,
				op->offset) || memcmp(check, op->before, op->length)) {
			errno = ESTALE;
			goto abort;
		}
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
		test_stage = "backend-before-write";
#endif
		if (writer->backend && writer->backend->before_write &&
			writer->backend->before_write(writer->backend_opaque, i + 1, op))
			goto abort;
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
		test_stage = "target-write";
#endif
		if (rh_fault("before-write", i + 1) ||
			rh_full_pwrite(writer, op->after, op->length,
				op->offset) || rh_fault("after-write", i + 1))
			goto abort;
		/*
		 * No target copy is authoritative until it is durable.  Persistent
		 * undo transactions and direct sole-valid-peer bootstrap copies both
		 * require pwrite -> fsync -> post-sync full-byte readback for every
		 * operation; a later repair must never rely on an unsynced peer.
		 */
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
		test_stage = "target-sync";
#endif
		if (rh_writer_sync(writer))
			goto abort;
		op->write_boundaries = writer->write_boundaries - first_boundary;
		op->sync_ordinal = writer->sync_count;
		op->sync_completed = 1;
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
		test_stage = "backend-after-write";
#endif
		if (writer->backend && writer->backend->after_write &&
			writer->backend->after_write(writer->backend_opaque, i + 1, op))
			goto abort;
		if (rh_full_pread(writer->write_fd, check, op->length,
				op->offset) || memcmp(check, op->after, op->length)) {
			errno = EIO;
			goto abort;
		}
		op->verified = 1;
		op->readback_verified = 1;
		writer->last_verified_ordinal = i + 1;
		if (rh_fault("after-verify", i + 1))
			goto abort;
		/*
		 * Each $LogFile restart page is a separate authoritative copy.
		 * Make page one durable before page two is touched, then make page
		 * two durable before any later operation can begin.
		 */
		if (op->kind == RH_WRITE_LOGFILE_RESTART &&
			rh_writer_sync(writer))
			goto abort;
	}
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
	test_stage = "final-sync";
#endif
	if (rh_writer_sync(writer))
		goto abort;
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
	test_stage = "backend-finish";
#endif
	if (writer->backend && writer->backend->finish &&
		writer->backend->finish(writer->backend_opaque,
			writer->operation_count))
		goto abort;
	writer->commit_completed = 1;
	result = 0;
	goto out;
abort:
#ifdef ROOTHEALTH_WAL_TEST_HOOKS
	fprintf(stderr, "writer commit failed stage=%s ordinal=%zu errno=%d\n",
		test_stage, i, errno);
#endif
	if (writer->backend && writer->backend->abort)
		writer->backend->abort(writer->backend_opaque,
			writer->last_verified_ordinal);
out:
	free(check);
	if (writer && writer->write_fd >= 0) {
		int saved_errno = errno;
		int close_result = close(writer->write_fd);
		writer->write_fd = -1;
		if (close_result && !result)
			result = -1;
		else if (result)
			errno = saved_errno;
	}
	return result;
}

ssize_t rh_writer_raw_pread(struct rh_writer *writer, void *buffer,
		size_t length, uint64_t offset)
{
	if (!writer || writer->write_fd < 0 || offset > writer->device_size ||
		length > writer->device_size - offset ||
		!rh_raw_wal_range_allowed(writer, offset, length)) {
		errno = EINVAL;
		return -1;
	}
	return pread(writer->write_fd, buffer, length, (off_t)offset);
}

ssize_t rh_writer_raw_pwrite(struct rh_writer *writer, const void *buffer,
		size_t length, uint64_t offset)
{
	ssize_t result;
	size_t ordinal;

	if (!writer || writer->write_fd < 0 || offset > writer->device_size ||
		length > writer->device_size - offset ||
		!rh_raw_wal_range_allowed(writer, offset, length)) {
		errno = EINVAL;
		return -1;
	}
	ordinal = writer->write_boundaries + 1U;
	if (rh_fault("before-pwrite", ordinal))
		return -1;
	writer->write_boundaries++;
	result = pwrite(writer->write_fd, buffer, length, (off_t)offset);
	if (result >= 0 && rh_fault("after-pwrite", ordinal))
		return -1;
	return result;
}

int rh_writer_raw_begin(struct rh_writer *writer)
{
	if (!writer || writer->write_fd >= 0) {
		errno = EBUSY;
		return -1;
	}
	return rh_open_write_fd(writer);
}

int rh_writer_raw_sync(struct rh_writer *writer)
{
	if (!writer || writer->write_fd < 0) {
		errno = EINVAL;
		return -1;
	}
	if (rh_fault("before-sync", writer->sync_count + 1U) ||
			fsync(writer->write_fd))
		return -1;
	writer->sync_count++;
	return rh_fault("after-sync", writer->sync_count);
}

int rh_writer_raw_end(struct rh_writer *writer)
{
	int result;

	if (!writer || writer->write_fd < 0) {
		errno = EINVAL;
		return -1;
	}
	result = close(writer->write_fd);
	writer->write_fd = -1;
	return result;
}

int rh_writer_recovery_write(struct rh_writer *writer, uint64_t offset,
		size_t length, const void *data)
{
	unsigned char *check;
	int result = -1;

	if (!writer || writer->write_fd < 0 || !data || !length ||
		offset > writer->device_size || length > writer->device_size - offset ||
		rh_overlaps_exclusion(writer, offset, length)) {
		errno = EINVAL;
		return -1;
	}
	check = malloc(length);
	if (!check)
		return -1;
	if (rh_full_pwrite(writer, data, length, offset) ||
		rh_writer_raw_sync(writer) ||
		rh_full_pread(writer->write_fd, check, length, offset) ||
		memcmp(check, data, length)) {
		if (!errno)
			errno = EIO;
		goto out;
	}
	result = 0;
out:
	free(check);
	return result;
}
