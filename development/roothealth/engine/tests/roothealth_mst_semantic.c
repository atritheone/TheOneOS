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

static void make_fixed(unsigned char record[1024])
{
	MFT_RECORD *mft = (MFT_RECORD *)record;

	memset(record, 0, 1024);
	mft->magic = magic_FILE;
	mft->usa_ofs = cpu_to_le16(0x30);
	mft->usa_count = cpu_to_le16(3);
	mft->sequence_number = cpu_to_le16(1);
	mft->mft_record_number = cpu_to_le32(5);
	mft->bytes_allocated = cpu_to_le32(1024);
	mft->bytes_in_use = cpu_to_le32(512);
	record[510] = 0;
	record[511] = 0xa5;
	record[1022] = 0x5a;
	record[1023] = 0xc3;
}

static int protect(const unsigned char fixed[1024], unsigned char raw[1024])
{
	memcpy(raw, fixed, 1024);
	return ntfs_mst_pre_write_fixup((NTFS_RECORD *)raw, 1024);
}

static void target_init(struct rh_write_semantic_target *target,
		uint64_t semantic_offset)
{
	static const unsigned char i30[] = {
		'$', 0, 'I', 0, '3', 0, '0', 0
	};

	memset(target, 0, sizeof(*target));
	target->seal_version = 1;
	target->object = RH_WRITE_TARGET_MFT_RECORD_PRIMARY;
	target->owner_mft_record = 5;
	target->owner_sequence = 1;
	target->attribute_instance = 4;
	target->attribute_type = 0xb0;
	target->attribute_name_length = 4;
	target->flags = RH_WRITE_TARGET_PRIMARY | RH_WRITE_TARGET_RESIDENT |
		RH_WRITE_TARGET_SET_ONLY;
	rh_sha256(i30, sizeof(i30), target->attribute_name_hash);
	target->lowest_vcn = -1;
	target->logical_vcn = -1;
	target->lcn = -1;
	target->logical_offset = 0;
	target->logical_length = 1;
	target->semantic_target_offset = semantic_offset;
	target->semantic_target_length = 1;
}

int main(void)
{
	char path[] = "/var/tmp/roothealth-mst-semantic.XXXXXX";
	unsigned char fixed_before[1024], fixed_after[1024];
	unsigned char raw_before[1024], raw_after[1024];
	unsigned char zero = 0, one = 1, zero_hash[32], one_hash[32];
	unsigned char evidence_hash[32], staged_hash[32];
	struct rh_write_semantic_target target;
	struct rh_writer writer;
	int fd = -1, result = 1;

	make_fixed(fixed_before);
	memcpy(fixed_after, fixed_before, sizeof(fixed_after));
	fixed_after[510] = 1;
	if (protect(fixed_before, raw_before) || protect(fixed_after, raw_after))
		goto out;
	fd = mkstemp(path);
	if (fd < 0 || fchmod(fd, 0600) || write(fd, raw_before, 1024) != 1024 ||
			fsync(fd) || close(fd))
		goto out;
	fd = -1;
	if (rh_writer_open(&writer, path))
		goto out;
	target_init(&target, 510);
	if (rh_writer_plan_typed(&writer, RH_WRITE_INDEX_BITMAP, 0, 1024,
			raw_after, &target) || writer.operation_count != 1 ||
			writer.write_boundaries)
		goto out_writer;
	rh_sha256(&zero, 1, zero_hash);
	rh_sha256(&one, 1, one_hash);
	if (memcmp(writer.operations[0].target.semantic_before_hash, zero_hash, 32) ||
			memcmp(writer.operations[0].target.semantic_after_hash, one_hash, 32) ||
			!rh_write_operation_semantics_valid(&writer.operations[0], 0))
		goto out_writer;
	rh_sha256("evidence", 8, evidence_hash);
	rh_sha256("staged", 6, staged_hash);
	if (rh_writer_finalize_target(&writer, 1, 1, 1, evidence_hash,
			staged_hash) ||
			!rh_write_operation_semantics_valid(&writer.operations[0], 1))
		goto out_writer;
	rh_writer_reset_plan(&writer);
	/* A regenerated USA/USN with an unchanged logical bitmap byte is a no-op. */
	memcpy(raw_after, raw_before, sizeof(raw_after));
	raw_after[0x30] ^= 0x5a;
	raw_after[510] = raw_after[0x30];
	raw_after[1022] = raw_after[0x30];
	if (!rh_writer_plan_typed(&writer, RH_WRITE_INDEX_BITMAP, 0, 1024,
			raw_after, &target) || writer.operation_count)
		goto out_writer;
	memcpy(fixed_after, fixed_before, sizeof(fixed_after));
	fixed_after[510] = 1;
	fixed_after[100] = 1;
	if (protect(fixed_after, raw_after) ||
			!rh_writer_plan_typed(&writer, RH_WRITE_INDEX_BITMAP, 0, 1024,
				raw_after, &target) || writer.operation_count)
		goto out_writer;
	memcpy(fixed_after, fixed_before, sizeof(fixed_after));
	fixed_after[510] = 1;
	if (protect(fixed_after, raw_after))
		goto out_writer;
	target_init(&target, 511);
	if (!rh_writer_plan_typed(&writer, RH_WRITE_INDEX_BITMAP, 0, 1024,
			raw_after, &target) || writer.operation_count)
		goto out_writer;
	printf("mst-semantic trailer_offset=510 full_target=1024 semantic_length=1 "
		"semantic_hashes=exact finalized_rederived=1 usa_only=refused "
		"unrelated_drift=refused "
		"retarget=refused "
		"source_writes=0\n");
	result = 0;
out_writer:
	rh_writer_close(&writer);
out:
	if (fd >= 0)
		close(fd);
	unlink(path);
	return result;
}
