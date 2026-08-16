/* ROOTHEALTH_REPAIR_ROLE(DIAGNOSTIC) */
#include "config.h"

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "endians.h"
#include "layout.h"
#include "roothealth_namespace.h"
#include "roothealth_write.h"

struct fixture {
	struct rh_raw_mft_census raw;
	size_t name_used;
	size_t value_used;
};

static int add_name(struct fixture *fixture, uint64_t owner,
		uint64_t parent, uint8_t name_namespace, const char *ascii)
{
	struct rh_raw_file_name *file_name;
	FILE_NAME_ATTR *value;
	size_t index = fixture->raw.file_name_count;
	size_t units = strlen(ascii), i;
	size_t value_length = offsetof(FILE_NAME_ATTR, file_name) + units * 2U;

	if (index >= 12U || units > 32U ||
			fixture->value_used + value_length > 4096U ||
			fixture->name_used + units * 2U > 512U)
		return -1;
	file_name = &fixture->raw.file_names[index];
	value = (FILE_NAME_ATTR *)(fixture->raw.value_arena + fixture->value_used);
	memset(value, 0, value_length);
	value->parent_directory = MK_LE_MREF(parent,
		fixture->raw.slots[parent].sequence);
	value->file_name_length = units;
	value->file_name_type = name_namespace;
	for (i = 0; i < units; i++) {
		value->file_name[i] = cpu_to_le16((uint16_t)(unsigned char)ascii[i]);
		fixture->raw.name_arena[fixture->name_used + i * 2U] =
			(unsigned char)ascii[i];
		fixture->raw.name_arena[fixture->name_used + i * 2U + 1U] = 0;
	}
	file_name->owner.record = owner;
	file_name->owner.sequence = fixture->raw.slots[owner].sequence;
	file_name->storage = file_name->owner;
	file_name->parent.record = parent;
	file_name->parent.sequence = fixture->raw.slots[parent].sequence;
	file_name->attribute_instance = (uint16_t)index;
	file_name->record_value_offset = (uint32_t)(0x100U + index * 0x80U);
	file_name->name_namespace = name_namespace;
	file_name->name_length = units;
	file_name->value_length = value_length;
	file_name->name_offset = fixture->name_used;
	file_name->value_arena_offset = fixture->value_used;
	rh_sha256(value, value_length, file_name->value_hash);
	rh_sha256(value, offsetof(FILE_NAME_ATTR, file_name_length),
		file_name->logical_link_hash);
	fixture->name_used += units * 2U;
	fixture->value_used += value_length;
	fixture->raw.name_arena_size = fixture->name_used;
	fixture->raw.value_arena_size = fixture->value_used;
	fixture->raw.file_name_count++;
	fixture->raw.slots[owner].owned_file_name_count++;
	return 0;
}

static int setup(struct fixture *fixture)
{
	memset(fixture, 0, sizeof(*fixture));
	fixture->raw.slot_count = 10U;
	fixture->raw.slots = calloc(fixture->raw.slot_count,
		sizeof(*fixture->raw.slots));
	fixture->raw.file_names = calloc(12U, sizeof(*fixture->raw.file_names));
	fixture->raw.name_arena = calloc(1U, 512U);
	fixture->raw.value_arena = calloc(1U, 4096U);
	if (!fixture->raw.slots || !fixture->raw.file_names ||
			!fixture->raw.name_arena || !fixture->raw.value_arena)
		return -1;
	fixture->raw.records_bounded = 1;
	fixture->raw.attribute_lists_complete = 1;
	fixture->raw.extents_complete = 1;
	fixture->raw.slots[5].state = RH_RAW_SLOT_LIVE_BASE;
	fixture->raw.slots[5].record = 5U;
	fixture->raw.slots[5].sequence = 5U;
	fixture->raw.slots[5].flags = le16_to_cpu(MFT_RECORD_IN_USE) |
		le16_to_cpu(MFT_RECORD_IS_DIRECTORY);
	fixture->raw.slots[5].link_count = 1U;
	fixture->raw.slots[6].state = RH_RAW_SLOT_LIVE_BASE;
	fixture->raw.slots[6].record = 6U;
	fixture->raw.slots[6].sequence = 6U;
	fixture->raw.slots[6].flags = le16_to_cpu(MFT_RECORD_IN_USE) |
		le16_to_cpu(MFT_RECORD_IS_DIRECTORY);
	fixture->raw.slots[6].link_count = 1U;
	fixture->raw.slots[7].state = RH_RAW_SLOT_LIVE_BASE;
	fixture->raw.slots[7].record = 7U;
	fixture->raw.slots[7].sequence = 7U;
	fixture->raw.slots[7].flags = le16_to_cpu(MFT_RECORD_IN_USE);
	fixture->raw.slots[7].link_count = 2U;
	fixture->raw.slots[8].state = RH_RAW_SLOT_LIVE_BASE;
	fixture->raw.slots[8].record = 8U;
	fixture->raw.slots[8].sequence = 8U;
	fixture->raw.slots[8].flags = le16_to_cpu(MFT_RECORD_IN_USE) |
		le16_to_cpu(MFT_RECORD_IS_DIRECTORY);
	fixture->raw.slots[8].link_count = 1U;
	if (add_name(fixture, 5U, 5U, FILE_NAME_POSIX, ".") ||
			add_name(fixture, 6U, 5U, FILE_NAME_WIN32_AND_DOS, "directory") ||
			add_name(fixture, 8U, 5U, FILE_NAME_POSIX, "other-directory") ||
			add_name(fixture, 7U, 6U, FILE_NAME_DOS, "FILE~1") ||
			add_name(fixture, 7U, 6U, FILE_NAME_WIN32, "file-long") ||
			add_name(fixture, 7U, 8U, FILE_NAME_POSIX, "cross-parent"))
		return -1;
	return 0;
}

static int scan(struct fixture *fixture, int expect_complete)
{
	struct rh_namespace_census census;
	int result;

	memset(&census, 0, sizeof(census));
	result = rh_namespace_census_run(&fixture->raw, 1U, &census);
	if (!result && (!!census.graph_complete != !!expect_complete ||
			census.links_completed != fixture->raw.file_name_count))
		result = -1;
	rh_namespace_census_release(&census);
	return result;
}

static int set_ascii_name(struct fixture *fixture, size_t index,
		const char *ascii)
{
	struct rh_raw_file_name *file_name;
	FILE_NAME_ATTR *value;
	size_t units = strlen(ascii), i;

	if (index >= fixture->raw.file_name_count)
		return -1;
	file_name = &fixture->raw.file_names[index];
	if (units != file_name->name_length)
		return -1;
	value = (FILE_NAME_ATTR *)(fixture->raw.value_arena +
		file_name->value_arena_offset);
	for (i = 0; i < units; i++) {
		value->file_name[i] = cpu_to_le16((uint16_t)(unsigned char)ascii[i]);
		fixture->raw.name_arena[file_name->name_offset + i * 2U] =
			(unsigned char)ascii[i];
		fixture->raw.name_arena[file_name->name_offset + i * 2U + 1U] = 0;
	}
	rh_sha256(value, file_name->value_length, file_name->value_hash);
	return 0;
}

static int scan_collisions(struct fixture *fixture, int expect_complete,
		uint64_t expected_posix, uint64_t expected_aliases)
{
	struct rh_namespace_census census;
	int result;

	memset(&census, 0, sizeof(census));
	result = rh_namespace_census_run(&fixture->raw, 1U, &census);
	if (!result && (!!census.graph_complete != !!expect_complete ||
			census.posix_case_collisions != expected_posix ||
			census.aliases != expected_aliases))
		result = -1;
	rh_namespace_census_release(&census);
	return result;
}

int main(void)
{
	struct fixture fixture, collisions;
	struct rh_raw_file_name *dos, *win32;

	if (setup(&fixture) || scan(&fixture, 1))
		return 1;
	/* A DOS+WIN32 pair is one logical MFT link. */
	fixture.raw.slots[7].link_count = 3U;
	if (scan(&fixture, 0))
		return 1;
	/* POSIX and namespace-3 attributes never collapse. */
	dos = &fixture.raw.file_names[3];
	win32 = &fixture.raw.file_names[4];
	dos->name_namespace = FILE_NAME_POSIX;
	win32->name_namespace = FILE_NAME_WIN32_AND_DOS;
	fixture.raw.value_arena[dos->value_arena_offset +
		offsetof(FILE_NAME_ATTR, file_name_type)] = FILE_NAME_POSIX;
	fixture.raw.value_arena[win32->value_arena_offset +
		offsetof(FILE_NAME_ATTR, file_name_type)] = FILE_NAME_WIN32_AND_DOS;
	fixture.raw.slots[7].link_count = 3U;
	if (scan(&fixture, 1))
		return 1;
	/* A non-root directory may have exactly one logical parent link. */
	if (add_name(&fixture, 6U, 5U, FILE_NAME_POSIX, "directory-two"))
		return 1;
	fixture.raw.slots[6].link_count = 2U;
	if (scan(&fixture, 0))
		return 1;

	rh_raw_mft_census_release(&fixture.raw);
	if (setup(&collisions))
		return 1;
	collisions.raw.slots[9].state = RH_RAW_SLOT_LIVE_BASE;
	collisions.raw.slots[9].record = 9U;
	collisions.raw.slots[9].sequence = 9U;
	collisions.raw.slots[9].flags = le16_to_cpu(MFT_RECORD_IN_USE);
	collisions.raw.slots[9].link_count = 1U;
	if (add_name(&collisions, 9U, 6U, FILE_NAME_POSIX, "CASE") ||
			add_name(&collisions, 7U, 6U, FILE_NAME_POSIX, "case"))
		return 1;
	collisions.raw.slots[7].link_count = 3U;
	if (scan_collisions(&collisions, 1, 1U, 0U))
		return 1;
	/* Exact duplicates remain ambiguous even when both are POSIX. */
	if (set_ascii_name(&collisions, 7U, "CASE") ||
			scan_collisions(&collisions, 0, 0U, 1U))
		return 1;
	if (set_ascii_name(&collisions, 7U, "case"))
		return 1;
	/* Case-distinct Win32 entries are valid in case-sensitive NTFS directories. */
	collisions.raw.file_names[7].name_namespace = FILE_NAME_WIN32;
	collisions.raw.value_arena[collisions.raw.file_names[7].value_arena_offset +
		offsetof(FILE_NAME_ATTR, file_name_type)] = FILE_NAME_WIN32;
	if (scan_collisions(&collisions, 1, 1U, 0U))
		return 1;
	/* DOS-bearing namespaces remain collating and therefore ambiguous. */
	collisions.raw.file_names[7].name_namespace = FILE_NAME_WIN32_AND_DOS;
	collisions.raw.value_arena[collisions.raw.file_names[7].value_arena_offset +
		offsetof(FILE_NAME_ATTR, file_name_type)] = FILE_NAME_WIN32_AND_DOS;
	if (scan_collisions(&collisions, 0, 0U, 1U))
		return 1;
	collisions.raw.file_names[7].name_namespace = FILE_NAME_POSIX;
	collisions.raw.value_arena[collisions.raw.file_names[7].value_arena_offset +
		offsetof(FILE_NAME_ATTR, file_name_type)] = FILE_NAME_POSIX;
	/* A second collating POSIX name for the same child is also ambiguous. */
	if (add_name(&collisions, 7U, 6U, FILE_NAME_POSIX, "CaSe"))
		return 1;
	collisions.raw.slots[7].link_count = 4U;
	if (scan_collisions(&collisions, 0, 0U, 2U))
		return 1;
	rh_raw_mft_census_release(&collisions.raw);
	printf("namespace-links dos-win32=one posix-and-namespace3=two "
		"directory-hardlink=refused cross-parent-file-hardlinks=allowed "
		"posix-or-win32-case-collision=allowed dos-bearing-or-exact-or-same-child=refused "
		"writes=0\n");
	return 0;
}
