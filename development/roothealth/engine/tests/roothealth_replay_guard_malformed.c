#include "roothealth_replay_guard.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define ARRAY_SIZE(a) (sizeof(a) / sizeof((a)[0]))
#define BIT(n) (UINT64_C(1) << (n))

static unsigned int failures;

static void expect(int condition, const char *name)
{
	if (!condition) {
		fprintf(stderr, "FAIL: %s\n", name);
		++failures;
	}
}

static void wr16(unsigned char *p, uint16_t value)
{
	p[0] = (unsigned char)value;
	p[1] = (unsigned char)(value >> 8);
}

static void wr32(unsigned char *p, uint32_t value)
{
	wr16(p, (uint16_t)value);
	wr16(p + 2, (uint16_t)(value >> 16));
}

static void wr64(unsigned char *p, uint64_t value)
{
	wr32(p, (uint32_t)value);
	wr32(p + 4, (uint32_t)(value >> 32));
}

static uint64_t make_lsn(uint64_t source)
{
	return (UINT64_C(1) << 19) | (source / 8U);
}

static void make_resident(unsigned char record[104])
{
	memset(record, 0, 104);
	wr64(record, make_lsn(0x5040));
	wr32(record + 24, 56);
	wr16(record + 28, 1);
	wr32(record + 32, 1);
	wr32(record + 36, 0x11223344);
	wr16(record + 48, 7);
	wr16(record + 50, 7);
	wr16(record + 52, 0x28);
	wr16(record + 54, 2);
	wr16(record + 56, 0x30);
	wr16(record + 58, 2);
	wr16(record + 60, 4);
	wr16(record + 62, 1);
	wr16(record + 64, 360);
	wr16(record + 66, 24);
	wr16(record + 68, 6);
	wr16(record + 70, 2);
	wr64(record + 72, 0);
	wr64(record + 80, 4);
	record[88] = 'S';
	record[96] = 'R';
}

static void make_forget(unsigned char record[88])
{
	uint64_t prior = make_lsn(0x5040);

	memset(record, 0, 88);
	wr64(record, make_lsn(0x50a8));
	wr64(record + 8, prior);
	wr64(record + 16, prior);
	wr32(record + 24, 40);
	wr16(record + 28, 1);
	wr32(record + 32, 1);
	wr32(record + 36, 0x11223344);
	wr16(record + 48, 27);
}

static void make_page(unsigned char page[RH_REPLAY_PAGE_SIZE])
{
	unsigned int sector;

	memset(page, 0, RH_REPLAY_PAGE_SIZE);
	memcpy(page, "RCRD", 4);
	wr16(page + 4, 40);
	wr16(page + 6, 9);
	wr64(page + 8, make_lsn(0x5040));
	wr32(page + 16, 1);
	wr16(page + 20, 1);
	wr16(page + 22, 1);
	wr16(page + 24, 64);
	wr64(page + 32, make_lsn(0x5040));
	wr16(page + 40, 0x51a7);
	for (sector = 1; sector < 9; ++sector) {
		size_t tail = sector * 512U - 2U;

		page[40 + 2U * sector] = page[tail];
		page[41 + 2U * sector] = page[tail + 1];
		wr16(page + tail, 0x51a7);
	}
}

static void test_policy(void)
{
	static const uint64_t masks[38] = {
		/*  0 */ BIT(0),
		/*  1 */ BIT(0),
		/*  2 */ BIT(0),
		/*  3 */ BIT(2),
		/*  4 */ BIT(4),
		/*  5 */ BIT(6),
		/*  6 */ BIT(5),
		/*  7 */ BIT(7),
		/*  8 */ BIT(8),
		/*  9 */ BIT(9),
		/* 10 */ BIT(0),
		/* 11 */ BIT(11),
		/* 12 */ BIT(13),
		/* 13 */ BIT(12),
		/* 14 */ BIT(15),
		/* 15 */ BIT(14),
		/* 16 */ BIT(16),
		/* 17 */ BIT(17),
		/* 18 */ BIT(18),
		/* 19 */ BIT(19),
		/* 20 */ BIT(20),
		/* 21 */ BIT(22),
		/* 22 */ BIT(21),
		/* 23 */ BIT(0),
		/* 24 */ BIT(0),
		/* 25 */ BIT(0),
		/* 26 */ BIT(0),
		/* 27 */ BIT(0),
		/* 28 */ BIT(0),
		/* 29 */ BIT(0),
		/* 30 */ BIT(0),
		/* 31 */ BIT(0),
		/* 32 */ BIT(0),
		/* 33 */ BIT(33),
		/* 34 */ BIT(34),
		/* 35 */ BIT(35),
		/* 36 */ BIT(36),
		/* 37 */ BIT(0)
	};
	unsigned int op;
	unsigned int supported = 0;

	for (op = 0; op < ARRAY_SIZE(masks); ++op) {
		const struct rh_replay_action_policy *policy =
			rh_replay_action_policy(op);

		expect(policy != NULL, "all 38 policy rows exist");
		if (!policy)
			continue;
		expect(policy->name != NULL, "policy name exists");
		expect(policy->undo_mask == masks[op], "exact pair mask");
		if (policy->action_class != RH_REPLAY_ACTION_DENY)
			++supported;
		else
			expect(policy->deny_reason != NULL, "deny reason exists");
	}
	expect(rh_replay_action_policy(38) == NULL, "opcode 38 denied");
	expect(supported == 38, "exact guarded action/control count");
}

static void test_pages(void)
{
	unsigned char valid[RH_REPLAY_PAGE_SIZE];
	unsigned char page[RH_REPLAY_PAGE_SIZE];
	struct rh_replay_page_view view;
	unsigned int sector;

	make_page(valid);
	memcpy(page, valid, sizeof(page));
	expect(!rh_replay_guard_unprotect_rcrd(page, sizeof(page), &view),
		"valid RCRD page");
	expect(view.next_record_offset == 64, "RCRD next offset");
	expect(rh_replay_guard_unprotect_rcrd(page, sizeof(page) - 1, NULL),
		"short RCRD page rejected");

	for (sector = 1; sector < 9; ++sector) {
		memcpy(page, valid, sizeof(page));
		page[sector * 512U - 2U] ^= 1U;
		expect(rh_replay_guard_unprotect_rcrd(page, sizeof(page), NULL),
			"every MST sector tail checked");
	}
#define BAD_PAGE(offset, value, label) do { \
	memcpy(page, valid, sizeof(page)); \
	wr16(page + (offset), (value)); \
	expect(rh_replay_guard_unprotect_rcrd(page, sizeof(page), NULL), label); \
} while (0)
	memcpy(page, valid, sizeof(page));
	page[0] = 'X';
	expect(rh_replay_guard_unprotect_rcrd(page, sizeof(page), NULL),
		"bad RCRD magic rejected");
	BAD_PAGE(4, 42, "noncanonical USA offset rejected");
	BAD_PAGE(6, 8, "wrong USA count rejected");
	memcpy(page, valid, sizeof(page));
	wr32(page + 16, 0);
	expect(rh_replay_guard_unprotect_rcrd(page, sizeof(page), NULL),
		"non-single-page RCRD flags rejected");
	memcpy(page, valid, sizeof(page));
	wr16(page + 20, 2);
	expect(!rh_replay_guard_unprotect_rcrd(page, sizeof(page), NULL),
		"bounded first page of multi-page RCRD accepted");
	BAD_PAGE(22, 2, "bad page position rejected");
	BAD_PAGE(24, 63, "short next offset rejected");
	BAD_PAGE(24, 65, "unaligned next offset rejected");
	BAD_PAGE(24, 4104, "unbounded next offset rejected");
	memcpy(page, valid, sizeof(page));
	page[26] = 1;
	expect(rh_replay_guard_unprotect_rcrd(page, sizeof(page), NULL),
		"nonzero RCRD reserved byte rejected");
#undef BAD_PAGE
}

static void test_actions(void)
{
	struct rh_replay_geometry geometry = {
		.page_size = 4096,
		.cluster_size = 4096,
		.mft_record_size = 1024,
		.index_record_size = 4096,
		.logfile_size = 2U * 1024U * 1024U,
		.volume_clusters = 16383,
		.sequence_bits = 45,
		.client_sequence = 1,
		.client_index = 0
	};
	struct rh_replay_action_view view;
	unsigned char valid[104];
	unsigned char changed[4096];
	unsigned char forget[88];
	unsigned char control[96];
	unsigned int op, undo;
	uint32_t random = 0x13579bdfU;
	size_t i;

	make_resident(valid);
	make_forget(forget);
	expect(!rh_replay_guard_profile(&geometry), "valid T1OS profile");
	expect(!rh_replay_guard_action(valid, sizeof(valid), &geometry,
		0x5040, &view), "valid resident action");
	expect(view.redo_data_offset == 88 && view.undo_data_offset == 96,
		"resident payload windows");
	expect(view.target_slice_offset == 3072, "resident target slice");
	expect(!rh_replay_guard_action(forget, sizeof(forget), &geometry,
		0x50a8, &view), "valid transaction end");

	memset(control, 0, sizeof(control));
	wr64(control, make_lsn(0x5200));
	wr32(control + 24, 48);
	wr16(control + 28, 1);
	wr32(control + 32, 1);
	wr32(control + 36, 64);
	wr16(control + 48, 10);
	wr16(control + 52, 0x28);
	wr16(control + 54, 16);
	wr64(control + 80, 4);
	wr64(control + 88, 2);
	expect(!rh_replay_guard_action(control, sizeof(control), &geometry,
		RH_REPLAY_SOURCE_UNKNOWN, &view) &&
		view.action_class == RH_REPLAY_ACTION_CONTROL,
		"valid DeleteDirtyClusters analysis control");
	wr64(control + 88, 0);
	expect(rh_replay_guard_action(control, sizeof(control), &geometry,
		RH_REPLAY_SOURCE_UNKNOWN, NULL),
		"zero-length DeleteDirtyClusters range rejected");

	memset(control, 0, 88);
	wr64(control, make_lsn(0x5300));
	wr32(control + 24, 40);
	wr16(control + 28, 1);
	wr32(control + 32, 1);
	wr32(control + 36, 64);
	wr16(control + 48, 23);
	wr16(control + 60, 24);
	wr16(control + 62, 1);
	wr64(control + 72, 2);
	wr64(control + 80, 5);
	expect(!rh_replay_guard_action(control, 88, &geometry,
		RH_REPLAY_SOURCE_UNKNOWN, &view) &&
		view.action_class == RH_REPLAY_ACTION_CONTROL,
		"valid HotFix analysis control");
	wr64(control + 80, geometry.volume_clusters);
	expect(rh_replay_guard_action(control, 88, &geometry,
		RH_REPLAY_SOURCE_UNKNOWN, NULL),
		"out-of-volume HotFix target rejected");

	for (op = 0; op < 38; ++op) {
		memcpy(changed, valid, sizeof(valid));
		wr16(changed + 48, (uint16_t)op);
		if (op != 7)
			expect(rh_replay_guard_action(changed, sizeof(valid), &geometry,
				0x5040, NULL), "every unqualified opcode rejected");
	}
	for (op = 0; op < 38; ++op) {
		const struct rh_replay_action_policy *policy =
			rh_replay_action_policy(op);

		for (undo = 0; undo < 38; ++undo) {
			if (policy->undo_mask & BIT(undo))
				continue;
			memcpy(changed, valid, sizeof(valid));
			wr16(changed + 48, (uint16_t)op);
			wr16(changed + 50, (uint16_t)undo);
			expect(rh_replay_guard_action(changed, sizeof(valid),
				&geometry, 0x5040, NULL),
				"every non-allowlisted redo/undo pair rejected");
		}
	}

#define BAD_ACTION(offset, width, value, label) do { \
	memcpy(changed, valid, sizeof(valid)); \
	if ((width) == 2) wr16(changed + (offset), (uint16_t)(value)); \
	else if ((width) == 4) wr32(changed + (offset), (uint32_t)(value)); \
	else wr64(changed + (offset), (uint64_t)(value)); \
	expect(rh_replay_guard_action(changed, sizeof(valid), &geometry, \
		0x5040, NULL), label); \
} while (0)
	BAD_ACTION(24, 4, 0xffffffffU, "oversized client length rejected");
	BAD_ACTION(30, 2, 1, "wrong client index rejected");
	BAD_ACTION(36, 4, 0, "zero transaction rejected");
	BAD_ACTION(40, 2, 1, "record flags rejected");
	BAD_ACTION(42, 2, 1, "reserved bytes rejected");
	BAD_ACTION(50, 2, 1, "unqualified compensation pair rejected");
	BAD_ACTION(52, 2, 0x20, "redo overlaps LCN table rejected");
	BAD_ACTION(54, 2, 32, "redo end bound rejected");
	BAD_ACTION(56, 2, 0x38, "payload gap rejected");
	BAD_ACTION(58, 2, 16, "undo end bound rejected");
	BAD_ACTION(62, 2, 0xffff, "LCN list bound rejected");
	BAD_ACTION(68, 2, 1, "misaligned MFT record slice rejected");
	BAD_ACTION(68, 2, 7, "protected target slice rejected");
	BAD_ACTION(70, 2, 8, "wrong target family rejected");
	BAD_ACTION(80, 8, 16383, "out-of-volume LCN rejected");
	BAD_ACTION(8, 8, make_lsn(0x5040), "nonpast previous LSN rejected");
	BAD_ACTION(28, 2, 2, "wrong log client sequence rejected");
	expect(rh_replay_guard_action(valid, sizeof(valid), &geometry,
		0x6040, NULL), "LSN source mismatch rejected");
	expect(rh_replay_guard_action(valid, sizeof(valid) - 8, &geometry,
		0x5040, NULL), "truncated action rejected");
	memcpy(changed, forget, sizeof(forget));
	changed[87] = 1;
	expect(rh_replay_guard_action(changed, sizeof(forget), &geometry,
		0x50a8, NULL), "transaction-end trailing data rejected");
#undef BAD_ACTION

	geometry.page_size = 8192;
	expect(rh_replay_guard_profile(&geometry), "8KiB log page rejected");
	geometry.page_size = 4096;
	geometry.logfile_size = RH_REPLAY_MAX_LOGFILE_SIZE + 4096U;
	expect(rh_replay_guard_profile(&geometry), "oversized logfile rejected");
	geometry.logfile_size = 2U * 1024U * 1024U;
	geometry.cluster_size = 8192;
	expect(rh_replay_guard_profile(&geometry), "non-T1OS cluster rejected");
	geometry.cluster_size = 4096;
	geometry.mft_record_size = 4096;
	expect(rh_replay_guard_profile(&geometry), "non-T1OS MFT size rejected");
	geometry.mft_record_size = 1024;

	for (i = 0; i < 20000; ++i) {
		size_t length;
		size_t j;

		random ^= random << 13;
		random ^= random >> 17;
		random ^= random << 5;
		length = random % sizeof(changed);
		for (j = 0; j < length; ++j) {
			random = random * 1664525U + 1013904223U;
			changed[j] = (unsigned char)(random >> 24);
		}
		(void)rh_replay_guard_action(changed, length, &geometry,
			RH_REPLAY_SOURCE_UNKNOWN, NULL);
	}
	for (i = 0; i < sizeof(valid); ++i) {
		memcpy(changed, valid, sizeof(valid));
		changed[i] ^= (unsigned char)(1U << (i & 7U));
		(void)rh_replay_guard_action(changed, sizeof(valid), &geometry,
			0x5040, NULL);
	}
}

int main(void)
{
	test_policy();
	test_pages();
	test_actions();
	if (failures) {
		fprintf(stderr, "%u roothealth replay guard checks failed\n", failures);
		return 1;
	}
	puts("PASS roothealth native replay guard malformed corpus");
	return 0;
}
