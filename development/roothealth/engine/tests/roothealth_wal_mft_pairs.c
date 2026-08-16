#include "config.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "endians.h"
#include "layout.h"
#include "roothealth_wal.h"

static uint64_t get_u64(const unsigned char *bytes)
{
	uint64_t value = 0;
	unsigned int i;

	for (i = 0; i < 8U; i++)
		value |= (uint64_t)bytes[i] << (8U * i);
	return value;
}

static void initialize_target(struct rh_write_semantic_target *target,
		enum rh_write_target_object object, uint64_t base,
		uint16_t sequence)
{
	memset(target, 0, sizeof(*target));
	target->seal_version = 1;
	target->object = object;
	target->owner_sequence = sequence;
	target->flags = RH_WRITE_TARGET_RESIDENT |
		(object == RH_WRITE_TARGET_MFT_RECORD_PRIMARY ?
		 RH_WRITE_TARGET_PRIMARY : RH_WRITE_TARGET_MIRROR);
	target->lowest_vcn = -1;
	target->logical_vcn = -1;
	target->lcn = -1;
	target->logical_length = 1024;
	target->semantic_target_offset = base;
	target->semantic_target_length = 1024;
}

int main(int argc, char **argv)
{
	struct rh_writer writer;
	struct rh_wal wal;
	struct rh_write_operation ops[3];
	unsigned char boot[512];
	unsigned char primary[1024], mirror[1024];
	unsigned char primary_after[1024], mirror_after[1024];
	uint64_t primary_base, mirror_base;
	uint16_t sequence;
	int result = 1;

	if (argc != 2)
		return 5;
	if (rh_writer_open(&writer, argv[1]))
		return 3;
	memset(&wal, 0, sizeof(wal));
	wal.writer = &writer;
	if (rh_writer_read(&writer, 0, sizeof(boot), boot))
		goto out;
	primary_base = get_u64(boot + 48) << 12;
	mirror_base = get_u64(boot + 56) << 12;
	if (rh_writer_read(&writer, primary_base, sizeof(primary), primary) ||
			rh_writer_read(&writer, mirror_base, sizeof(mirror), mirror))
		goto out;
	sequence = le16_to_cpu(((const MFT_RECORD *)primary)->sequence_number);
	memcpy(primary_after, primary, sizeof(primary_after));
	memcpy(mirror_after, mirror, sizeof(mirror_after));
	memset(ops, 0, sizeof(ops));
	ops[0].kind = RH_WRITE_MFT_RECORD;
	ops[0].offset = primary_base;
	ops[0].length = sizeof(primary);
	ops[0].before = primary;
	ops[0].after = primary_after;
	initialize_target(&ops[0].target, RH_WRITE_TARGET_MFT_RECORD_PRIMARY,
		primary_base, sequence);
	ops[1].kind = RH_WRITE_MFT_RECORD;
	ops[1].offset = mirror_base;
	ops[1].length = sizeof(mirror);
	ops[1].before = mirror;
	ops[1].after = mirror_after;
	initialize_target(&ops[1].target, RH_WRITE_TARGET_MFT_RECORD_MIRROR,
		mirror_base, sequence);
	if (!rh_wal_validate_mft_operation_pairs(&wal, ops, 2) ||
			rh_wal_validate_mft_operation_pairs(&wal, ops, 1) ||
			rh_wal_validate_mft_operation_pairs(&wal, ops + 1, 1))
		goto out;
	ops[2] = ops[1];
	ops[1] = ops[0];
	ops[1].target.owner_mft_record = 5;
	if (rh_wal_validate_mft_operation_pairs(&wal, ops, 3) ||
			!rh_wal_validate_mft_operation_pairs(&wal, ops + 1, 1))
		goto out;
	ops[1] = ops[2];
	ops[1].kind = RH_WRITE_INDEX_ROOT;
	if (rh_wal_validate_mft_operation_pairs(&wal, ops, 2))
		goto out;
	ops[1] = ops[2];
	ops[1].target.owner_sequence++;
	if (rh_wal_validate_mft_operation_pairs(&wal, ops, 2))
		goto out;
	ops[1] = ops[2];
	mirror_after[100] ^= 1U;
	if (rh_wal_validate_mft_operation_pairs(&wal, ops, 2))
		goto out;
	printf("wal-mft-pairs valid=1 primary_only=refused mirror_only=refused "
		"nonadjacent=refused kind_mismatch=refused identity_mismatch=refused "
		"delta_mismatch=refused owner_gt3_single=accepted writes=0\n");
	result = 0;
out:
	rh_writer_close(&writer);
	return result;
}
