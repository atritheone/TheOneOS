#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "roothealth_write.h"

static void set_name(struct rh_write_semantic_target *target,
		const char *name)
{
	unsigned char encoded[64];
	size_t length = strlen(name), i;

	for (i = 0; i < length; i++) {
		encoded[2U * i] = (unsigned char)name[i];
		encoded[2U * i + 1U] = 0;
	}
	target->attribute_name_length = (uint16_t)length;
	rh_sha256(encoded, length * 2U, target->attribute_name_hash);
}

static void set_attribute(struct rh_write_semantic_target *target,
		enum rh_write_target_object object, uint64_t owner, uint32_t type,
		const char *name)
{
	target->object = object;
	target->owner_mft_record = owner;
	target->owner_sequence = 1;
	target->attribute_instance = 2;
	target->attribute_type = type;
	set_name(target, name);
	if (object == RH_WRITE_TARGET_MFT_RECORD_PRIMARY ||
			object == RH_WRITE_TARGET_MFT_RECORD_MIRROR) {
		target->flags = object == RH_WRITE_TARGET_MFT_RECORD_PRIMARY ?
			RH_WRITE_TARGET_PRIMARY : RH_WRITE_TARGET_MIRROR;
		target->flags |= RH_WRITE_TARGET_RESIDENT;
		target->lowest_vcn = -1;
		target->logical_vcn = -1;
		target->lcn = -1;
	} else {
		target->flags = RH_WRITE_TARGET_NONRESIDENT;
		target->lowest_vcn = 0;
		target->logical_vcn = 0;
		target->lcn = 8;
		if (object == RH_WRITE_TARGET_PROVEN_FREE_ALLOCATION)
			target->flags |= RH_WRITE_TARGET_PRETRANSACTION_FREE;
	}
}

static void set_full_record(struct rh_write_semantic_target *target,
		enum rh_write_target_object object, uint64_t owner)
{
	target->object = object;
	target->owner_mft_record = owner;
	target->owner_sequence = 1;
	target->flags = object == RH_WRITE_TARGET_MFT_RECORD_PRIMARY ?
		RH_WRITE_TARGET_PRIMARY : RH_WRITE_TARGET_MIRROR;
	target->flags |= RH_WRITE_TARGET_RESIDENT;
	target->lowest_vcn = -1;
	target->logical_vcn = -1;
	target->lcn = -1;
}

static int valid_target(enum rh_write_kind kind,
		struct rh_write_semantic_target *target, size_t *length)
{
	memset(target, 0, sizeof(*target));
	target->seal_version = 1;
	target->semantic_target_offset = 4096;
	target->semantic_target_length = 1;
	target->logical_length = 1;
	*length = 1;
	switch (kind) {
	case RH_WRITE_BOOT_PRIMARY:
		target->object = RH_WRITE_TARGET_BOOT_PRIMARY;
		target->flags = RH_WRITE_TARGET_PRIMARY;
		target->lowest_vcn = target->logical_vcn = target->lcn = -1;
		break;
	case RH_WRITE_BOOT_BACKUP:
		target->object = RH_WRITE_TARGET_BOOT_BACKUP;
		target->flags = RH_WRITE_TARGET_MIRROR;
		target->lowest_vcn = target->logical_vcn = target->lcn = -1;
		break;
	case RH_WRITE_MFT_PRIMARY:
		set_full_record(target, RH_WRITE_TARGET_MFT_RECORD_PRIMARY, 0);
		break;
	case RH_WRITE_MFT_MIRROR:
		set_full_record(target, RH_WRITE_TARGET_MFT_RECORD_MIRROR, 0);
		break;
	case RH_WRITE_LOGFILE_REDO:
		set_attribute(target, RH_WRITE_TARGET_NONRESIDENT_ATTRIBUTE, 2,
			0x80, "");
		target->flags |= RH_WRITE_TARGET_NATIVE_LOG_DERIVED;
		break;
	case RH_WRITE_LOGFILE_RESTART:
		set_attribute(target, RH_WRITE_TARGET_NONRESIDENT_ATTRIBUTE, 2,
			0x80, "");
		target->flags |= RH_WRITE_TARGET_NATIVE_LOG_DERIVED;
		break;
	case RH_WRITE_MFT_RECORD:
		set_full_record(target, RH_WRITE_TARGET_MFT_RECORD_PRIMARY, 42);
		break;
	case RH_WRITE_ATTRIBUTE_LIST:
		set_attribute(target, RH_WRITE_TARGET_NONRESIDENT_ATTRIBUTE, 42,
			0x20, "");
		break;
	case RH_WRITE_RUNLIST_MAPPING_PAIRS:
		set_attribute(target, RH_WRITE_TARGET_MFT_RECORD_PRIMARY, 42,
			0x80, "");
		break;
	case RH_WRITE_ATTRIBUTE_DATA:
		set_attribute(target, RH_WRITE_TARGET_NONRESIDENT_ATTRIBUTE, 42,
			0x80, "userDefinedStream");
		break;
	case RH_WRITE_INDEX_ROOT:
		set_attribute(target, RH_WRITE_TARGET_MFT_RECORD_PRIMARY, 42,
			0x90, "$I30");
		break;
	case RH_WRITE_INDEX_ALLOCATION:
		set_attribute(target, RH_WRITE_TARGET_NONRESIDENT_ATTRIBUTE, 42,
			0xa0, "$I30");
		break;
	case RH_WRITE_INDEX_BITMAP:
		set_attribute(target, RH_WRITE_TARGET_NONRESIDENT_ATTRIBUTE, 42,
			0xb0, "$I30");
		target->flags |= RH_WRITE_TARGET_SET_ONLY;
		break;
	case RH_WRITE_CLUSTER_DATA:
		set_attribute(target, RH_WRITE_TARGET_PROVEN_FREE_ALLOCATION, 42,
			0x80, "data");
		break;
	case RH_WRITE_RECOVERY_NAMESPACE:
		set_attribute(target, RH_WRITE_TARGET_MFT_RECORD_PRIMARY, 42,
			0x30, "");
		break;
	case RH_WRITE_REPARSE_INDEX:
		set_attribute(target, RH_WRITE_TARGET_MFT_RECORD_PRIMARY, 26,
			0x90, "$R");
		break;
	case RH_WRITE_SECURE_SDS:
		set_attribute(target, RH_WRITE_TARGET_NONRESIDENT_ATTRIBUTE, 9,
			0x80, "$SDS");
		break;
	case RH_WRITE_SECURE_SDH:
		set_attribute(target, RH_WRITE_TARGET_MFT_RECORD_PRIMARY, 9,
			0x90, "$SDH");
		break;
	case RH_WRITE_SECURE_SII:
		set_attribute(target, RH_WRITE_TARGET_NONRESIDENT_ATTRIBUTE, 9,
			0xa0, "$SII");
		break;
	case RH_WRITE_UPCASE_DATA:
		set_attribute(target, RH_WRITE_TARGET_NONRESIDENT_ATTRIBUTE, 10,
			0x80, "");
		break;
	case RH_WRITE_ATTRDEF_DATA:
		set_attribute(target, RH_WRITE_TARGET_NONRESIDENT_ATTRIBUTE, 4,
			0x80, "");
		break;
	case RH_WRITE_BITMAP_MFT:
		set_attribute(target, RH_WRITE_TARGET_NONRESIDENT_ATTRIBUTE, 0,
			0xb0, "");
		target->flags |= RH_WRITE_TARGET_SET_ONLY;
		break;
	case RH_WRITE_BITMAP_CLUSTER:
		set_attribute(target, RH_WRITE_TARGET_NONRESIDENT_ATTRIBUTE, 6,
			0x80, "");
		target->flags |= RH_WRITE_TARGET_SET_ONLY;
		break;
	case RH_WRITE_VOLUME_DIRTY_SET:
	case RH_WRITE_VOLUME_DIRTY_CLEAR:
		set_attribute(target, RH_WRITE_TARGET_MFT_RECORD_PRIMARY, 3,
			0x70, "");
		target->flags |= kind == RH_WRITE_VOLUME_DIRTY_SET ?
			RH_WRITE_TARGET_SET_ONLY : RH_WRITE_TARGET_CLEAR_ONLY;
		target->logical_offset = 10;
		target->logical_length = 2;
		target->semantic_target_length = 2;
		*length = 2;
		break;
	case RH_WRITE_KIND_COUNT:
		return -1;
	}
	if ((target->object == RH_WRITE_TARGET_MFT_RECORD_PRIMARY ||
			target->object == RH_WRITE_TARGET_MFT_RECORD_MIRROR) &&
			kind != RH_WRITE_VOLUME_DIRTY_SET &&
			kind != RH_WRITE_VOLUME_DIRTY_CLEAR) {
		*length = 1024;
		if (!target->attribute_type) {
			target->logical_length = 1024;
			target->semantic_target_length = 1024;
		}
	}
	return 0;
}

int main(void)
{
	struct rh_write_semantic_target target, mutated;
	size_t length, cases = 0;
	int kind, object;

	for (kind = 0; kind < RH_WRITE_KIND_COUNT; kind++) {
		if (valid_target((enum rh_write_kind)kind, &target, &length) ||
				!rh_write_semantic_target_valid((enum rh_write_kind)kind,
					&target, 4096, length, 0)) {
			fprintf(stderr, "valid target rejected kind=%d\n", kind);
			return 1;
		}
		cases++;
		mutated = target;
		mutated.flags ^= RH_WRITE_TARGET_NATIVE_LOG_DERIVED;
		if (rh_write_semantic_target_valid((enum rh_write_kind)kind,
				&mutated, 4096, length, 0)) {
			fprintf(stderr, "native provenance alias kind=%d\n", kind);
			return 1;
		}
		cases++;
		if (target.attribute_type) {
			mutated = target;
			mutated.attribute_type = 0;
			if (rh_write_semantic_target_valid((enum rh_write_kind)kind,
					&mutated, 4096, length, 0)) {
				fprintf(stderr, "zero type accepted kind=%d\n", kind);
				return 1;
			}
			cases++;
		}
		if (kind == RH_WRITE_MFT_PRIMARY) {
			mutated = target;
			mutated.owner_mft_record = 4;
			if (rh_write_semantic_target_valid((enum rh_write_kind)kind,
					&mutated, 4096, length, 0)) {
				fprintf(stderr, "foundation owner alias kind=%d\n", kind);
				return 1;
			}
			cases++;
		}
		if (kind == RH_WRITE_ATTRIBUTE_LIST ||
				kind == RH_WRITE_RECOVERY_NAMESPACE) {
			mutated = target;
			set_name(&mutated, "BAD");
			if (rh_write_semantic_target_valid((enum rh_write_kind)kind,
					&mutated, 4096, length, 0)) {
				fprintf(stderr, "unnamed alias kind=%d\n", kind);
				return 1;
			}
			cases++;
		}
		if (kind == RH_WRITE_LOGFILE_RESTART ||
				kind == RH_WRITE_REPARSE_INDEX ||
				(kind >= RH_WRITE_SECURE_SDS &&
				 kind <= RH_WRITE_VOLUME_DIRTY_CLEAR)) {
			mutated = target;
			mutated.owner_mft_record += 100;
			if (rh_write_semantic_target_valid((enum rh_write_kind)kind,
					&mutated, 4096, length, 0)) {
				fprintf(stderr, "owner alias kind=%d\n", kind);
				return 1;
			}
			cases++;
			mutated = target;
			set_name(&mutated, "BAD");
			if (rh_write_semantic_target_valid((enum rh_write_kind)kind,
					&mutated, 4096, length, 0)) {
				fprintf(stderr, "name alias kind=%d\n", kind);
				return 1;
			}
			cases++;
		}
		for (object = RH_WRITE_TARGET_INVALID;
				object <= RH_WRITE_TARGET_PROVEN_FREE_ALLOCATION; object++) {
			if (object == (int)target.object)
				continue;
			mutated = target;
			mutated.object = (enum rh_write_target_object)object;
			if (rh_write_semantic_target_valid((enum rh_write_kind)kind,
					&mutated, 4096, length, 0)) {
				fprintf(stderr, "object alias kind=%d object=%d\n", kind,
					object);
				return 1;
			}
			cases++;
		}
		mutated = target;
		mutated.flags ^= RH_WRITE_TARGET_PRIMARY;
		if (rh_write_semantic_target_valid((enum rh_write_kind)kind,
				&mutated, 4096, length, 0)) {
			fprintf(stderr, "flag alias kind=%d\n", kind);
			return 1;
		}
		cases++;
		mutated = target;
		mutated.flags |= RH_WRITE_TARGET_SET_ONLY |
			RH_WRITE_TARGET_CLEAR_ONLY;
		if (rh_write_semantic_target_valid((enum rh_write_kind)kind,
				&mutated, 4096, length, 0)) {
			fprintf(stderr, "set-clear alias kind=%d\n", kind);
			return 1;
		}
		cases++;
		mutated = target;
		mutated.finalized = 1;
		if (rh_write_semantic_target_valid((enum rh_write_kind)kind,
				&mutated, 4096, length, 1)) {
			fprintf(stderr, "unsealed-final accepted kind=%d\n", kind);
			return 1;
		}
		cases++;
		mutated = target;
		mutated.finalized = 1;
		mutated.evidence_version = 1;
		memset(mutated.evidence_hash, 1, sizeof(mutated.evidence_hash));
		memset(mutated.staged_view_hash, 2,
			sizeof(mutated.staged_view_hash));
		memset(mutated.semantic_before_hash, 3,
			sizeof(mutated.semantic_before_hash));
		memset(mutated.semantic_after_hash, 4,
			sizeof(mutated.semantic_after_hash));
		if (rh_write_semantic_target_valid((enum rh_write_kind)kind,
				&mutated, 4096, length, 1)) {
			fprintf(stderr, "zero evidence generation accepted kind=%d\n", kind);
			return 1;
		}
		cases++;
	}
	printf("semantic-target kinds=%d negative_cases=%zu passed=1\n",
		RH_WRITE_KIND_COUNT, cases - RH_WRITE_KIND_COUNT);
	return 0;
}
