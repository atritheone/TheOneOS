#include "config.h"

#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include "endians.h"
#include "layout.h"
#include "mst.h"
#include "roothealth_write.h"

static void make_after(unsigned char fixed[1024], uint64_t record,
		uint16_t sequence)
{
	MFT_RECORD *mft = (MFT_RECORD *)fixed;

	memset(fixed, 0, 1024);
	mft->magic = magic_FILE;
	mft->usa_ofs = cpu_to_le16(0x30);
	mft->usa_count = cpu_to_le16(3);
	mft->sequence_number = cpu_to_le16(sequence);
	mft->attrs_offset = cpu_to_le16(0x38);
	mft->bytes_in_use = cpu_to_le32(0x40);
	mft->bytes_allocated = cpu_to_le32(1024);
	mft->mft_record_number = cpu_to_le32((uint32_t)record);
	*(le32 *)(fixed + 0x38) = AT_END;
	fixed[510] = 0x31;
	fixed[511] = 0x72;
	fixed[1022] = 0xa4;
	fixed[1023] = 0xc5;
}

static int protect(const unsigned char fixed[1024],
		unsigned char raw[1024])
{
	memcpy(raw, fixed, 1024);
	return ntfs_mst_pre_write_fixup((NTFS_RECORD *)raw, 1024);
}

static void target_init(struct rh_write_semantic_target *target)
{
	memset(target, 0, sizeof(*target));
	target->seal_version = 1;
	target->object = RH_WRITE_TARGET_MFT_RECORD_PRIMARY;
	target->owner_mft_record = 42;
	target->owner_sequence = 7;
	target->flags = RH_WRITE_TARGET_PRIMARY | RH_WRITE_TARGET_RESIDENT |
		RH_WRITE_TARGET_PRETRANSACTION_FREE |
		RH_WRITE_TARGET_NATIVE_LOG_DERIVED;
	target->lowest_vcn = -1;
	target->logical_vcn = -1;
	target->lcn = -1;
	target->logical_length = 1024;
	target->semantic_target_length = 1024;
}

static int target_negatives(const struct rh_write_semantic_target *valid)
{
	struct rh_write_semantic_target target;

	if (!rh_write_semantic_target_valid(RH_WRITE_LOGFILE_REDO, valid, 0,
			1024, 0))
		return -1;
	target = *valid;
	target.owner_mft_record = 3;
	if (rh_write_semantic_target_valid(RH_WRITE_LOGFILE_REDO, &target, 0,
			1024, 0))
		return -1;
	target = *valid;
	target.object = RH_WRITE_TARGET_MFT_RECORD_MIRROR;
	target.flags ^= RH_WRITE_TARGET_PRIMARY | RH_WRITE_TARGET_MIRROR;
	if (rh_write_semantic_target_valid(RH_WRITE_LOGFILE_REDO, &target, 0,
			1024, 0))
		return -1;
	target = *valid;
	target.semantic_target_length = target.logical_length = 1;
	if (rh_write_semantic_target_valid(RH_WRITE_LOGFILE_REDO, &target, 0,
			1024, 0))
		return -1;
	target = *valid;
	target.flags |= RH_WRITE_TARGET_CLEAR_ONLY;
	if (rh_write_semantic_target_valid(RH_WRITE_LOGFILE_REDO, &target, 0,
			1024, 0))
		return -1;
	if (rh_write_semantic_target_valid(RH_WRITE_MFT_RECORD, valid, 0, 1024,
			0))
		return -1;
	return 0;
}

int main(void)
{
	char path[] = "/var/tmp/roothealth-id5-initialize.XXXXXX";
	unsigned char stale[1024], fixed_after[1024], raw_after[1024];
	unsigned char before_hash[32], after_hash[32], evidence_hash[32], staged[32];
	struct rh_write_semantic_target target, generic;
	struct rh_writer writer;
	int fd = -1, result = 1;

	memset(stale, 0x5a, sizeof(stale));
	make_after(fixed_after, 42, 7);
	if (protect(fixed_after, raw_after))
		goto out;
	fd = mkstemp(path);
	if (fd < 0 || fchmod(fd, 0600) || write(fd, stale, sizeof(stale)) !=
			(ssize_t)sizeof(stale) || fsync(fd))
		goto out;
	if (close(fd)) {
		fd = -1;
		goto out;
	}
	fd = -1;
	if (rh_writer_open(&writer, path))
		goto out;
	target_init(&target);
	if (target_negatives(&target) ||
			rh_writer_plan_typed(&writer, RH_WRITE_LOGFILE_REDO, 0, 1024,
				raw_after, &target) || writer.operation_count != 1U ||
			writer.write_boundaries)
		goto out_writer;
	rh_sha256(stale, sizeof(stale), before_hash);
	rh_sha256(raw_after, sizeof(raw_after), after_hash);
	if (memcmp(writer.operations[0].target.semantic_before_hash, before_hash,
			32) || memcmp(writer.operations[0].target.semantic_after_hash,
			after_hash, 32) ||
			!rh_write_operation_semantics_valid(&writer.operations[0], 0))
		goto out_writer;
	rh_sha256("free-ledger", 11, evidence_hash);
	rh_sha256("overlay", 7, staged);
	if (rh_writer_finalize_target(&writer, 1, 1, 1, evidence_hash, staged) ||
			!rh_write_operation_semantics_valid(&writer.operations[0], 1))
		goto out_writer;
	rh_writer_reset_plan(&writer);
	generic = target;
	generic.flags &= (uint16_t)~RH_WRITE_TARGET_PRETRANSACTION_FREE;
	if (!rh_writer_plan_typed(&writer, RH_WRITE_LOGFILE_REDO, 0, 1024,
			raw_after, &generic) || writer.operation_count)
		goto out_writer;
	make_after(fixed_after, 43, 7);
	if (protect(fixed_after, raw_after) ||
			!rh_writer_plan_typed(&writer, RH_WRITE_LOGFILE_REDO, 0, 1024,
				raw_after, &target) || writer.operation_count)
		goto out_writer;
	make_after(fixed_after, 42, 8);
	if (protect(fixed_after, raw_after) ||
			!rh_writer_plan_typed(&writer, RH_WRITE_LOGFILE_REDO, 0, 1024,
				raw_after, &target) || writer.operation_count)
		goto out_writer;
	memset(raw_after, 0, sizeof(raw_after));
	if (!rh_writer_plan_typed(&writer, RH_WRITE_LOGFILE_REDO, 0, 1024,
			raw_after, &target) || writer.operation_count)
		goto out_writer;
	printf("id5-initialize stale-preimage=accepted raw-hashes=exact "
		"owner-gt3=1 after-mst-file-identity=1 finalize-gate=1 "
		"generic-stale=refused negatives=8 source-writes=0\n");
	result = 0;
out_writer:
	rh_writer_close(&writer);
out:
	if (fd >= 0)
		close(fd);
	unlink(path);
	return result;
}
