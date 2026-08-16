#include "roothealth_replay_analysis.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define TABLE_HEADER 24U
#define TABLE_ENTRY 40U
#define ALLOCATED UINT32_C(0xffffffff)

static unsigned int failures;

static void expect(int condition, const char *label)
{
	if (!condition) {
		fprintf(stderr, "FAIL: %s\n", label);
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

static void common(unsigned char *record, size_t size, uint64_t lsn,
		uint64_t previous, uint64_t undo_next, uint32_t type, uint32_t tx)
{
	memset(record, 0, size);
	wr64(record, lsn);
	wr64(record + 8, previous);
	wr64(record + 16, undo_next);
	wr32(record + 24, (uint32_t)size - 48U);
	wr16(record + 28, 1);
	wr32(record + 32, type);
	wr32(record + 36, tx);
}

static void table_header(unsigned char *table, int allocated)
{
	memset(table, 0, 64);
	wr16(table, TABLE_ENTRY);
	wr16(table + 2, 1);
	wr16(table + 4, (uint16_t)allocated);
	if (allocated) {
		wr32(table + TABLE_HEADER, ALLOCATED);
	} else {
		wr32(table + 16, TABLE_HEADER);
		wr32(table + 20, TABLE_HEADER);
	}
}

static void dump(unsigned char record[144], uint64_t lsn, uint64_t previous,
		uint16_t op, const unsigned char table[64])
{
	common(record, 144, lsn, previous, previous, 1, 24);
	wr16(record + 48, op);
	wr16(record + 52, 0x28);
	wr16(record + 54, 64);
	memcpy(record + 80, table, 64);
}

static void build_valid(unsigned char open_dump[144],
		unsigned char names[88], unsigned char dirty_dump[144],
		unsigned char tx_dump[144], unsigned char checkpoint[152],
		unsigned char update[104], unsigned char forget[88])
{
	unsigned char table[64];

	table_header(table, 1);
	wr32(table + TABLE_HEADER + 8, 0x80);
	wr64(table + TABLE_HEADER + 16, (UINT64_C(1) << 48) | 3U);
	dump(open_dump, 100, 0, 29, table);
	common(names, 88, 200, 100, 100, 1, 24);
	wr16(names + 48, 30);

	table_header(table, 1);
	wr32(table + TABLE_HEADER + 4, TABLE_HEADER);
	wr32(table + TABLE_HEADER + 8, 4096);
	wr32(table + TABLE_HEADER + 12, 1);
	wr64(table + TABLE_HEADER + 16, 0);
	wr64(table + TABLE_HEADER + 24, 100);
	wr64(table + TABLE_HEADER + 32, 4);
	dump(dirty_dump, 300, 200, 31, table);
	table_header(table, 0);
	dump(tx_dump, 400, 300, 32, table);

	common(checkpoint, 152, 500, 400, 0, 2, 0);
	wr32(checkpoint + 48, 1);
	wr32(checkpoint + 52, 1);
	wr64(checkpoint + 56, 500);
	wr64(checkpoint + 64, 100);
	wr64(checkpoint + 72, 200);
	wr64(checkpoint + 80, 300);
	wr64(checkpoint + 88, 400);
	wr32(checkpoint + 96, 64);
	wr32(checkpoint + 100, 8);
	wr32(checkpoint + 104, 64);
	wr32(checkpoint + 108, 64);

	common(update, 104, 600, 0, 0, 1, 64);
	wr16(update + 40, 2);
	wr16(update + 48, 7);
	wr16(update + 50, 7);
	wr16(update + 52, 0x28);
	wr16(update + 54, 2);
	wr16(update + 56, 0x30);
	wr16(update + 58, 2);
	wr16(update + 60, TABLE_HEADER);
	wr16(update + 62, 1);
	wr16(update + 64, 360);
	wr16(update + 66, 24);
	wr16(update + 68, 6);
	wr16(update + 70, 2);
	wr64(update + 80, 4);
	update[88] = 'S';
	update[96] = 'R';

	common(forget, 88, 700, 600, 600, 1, 64);
	wr16(forget + 48, 27);
}

static int analyze(unsigned char open_dump[144], unsigned char names[88],
		unsigned char dirty_dump[144], unsigned char tx_dump[144],
		unsigned char checkpoint[152], unsigned char update[104],
		unsigned char forget[88], struct rh_replay_analysis_result *result)
{
	struct rh_replay_geometry geometry = {
		.page_size = 4096, .cluster_size = 4096, .mft_record_size = 1024,
		.index_record_size = 4096, .logfile_size = 2U * 1024U * 1024U,
		.volume_clusters = 16383, .sequence_bits = 45,
		.client_sequence = 1, .client_index = 0
	};
	struct rh_replay_analysis_record records[] = {
		{ .bytes = open_dump, .size = 144 },
		{ .bytes = names, .size = 88 },
		{ .bytes = dirty_dump, .size = 144 },
		{ .bytes = tx_dump, .size = 144 },
		{ .bytes = checkpoint, .size = 152 },
		{ .bytes = update, .size = 104 },
		{ .bytes = forget, .size = 88 }
	};
	int rc = rh_replay_analysis_plan(records, sizeof(records) / sizeof(records[0]),
		&geometry, 100, 700, result);

	if (!rc)
		expect(records[5].plan_flags == RH_REPLAY_PLAN_REDO,
			"checkpoint winner marked for redo");
	return rc;
}

static void test_dynamic_open44(void)
{
	unsigned char open_record[128], update[104], forget[88];
	struct rh_replay_geometry geometry = {
		.page_size = 4096, .cluster_size = 4096, .mft_record_size = 1024,
		.index_record_size = 4096, .logfile_size = 2U * 1024U * 1024U,
		.volume_clusters = 16383, .sequence_bits = 45,
		.client_sequence = 1, .client_index = 0
	};
	struct rh_replay_analysis_record records[] = {
		{ .bytes = open_record, .size = sizeof(open_record) },
		{ .bytes = update, .size = sizeof(update) },
		{ .bytes = forget, .size = sizeof(forget) }
	};
	struct rh_replay_analysis_result result;

	common(open_record, sizeof(open_record), 100, 0, 0, 1, 64);
	wr16(open_record + 48, 28);
	wr16(open_record + 52, 0x28);
	wr16(open_record + 54, 44);
	wr16(open_record + 60, TABLE_HEADER);
	wr32(open_record + 80, ALLOCATED);
	wr64(open_record + 88, (UINT64_C(1) << 48) | 0U);
	wr32(open_record + 108, 0x80);

	common(update, sizeof(update), 200, 100, 100, 1, 64);
	wr16(update + 40, 2);
	wr16(update + 48, 7);
	wr16(update + 50, 7);
	wr16(update + 52, 0x28);
	wr16(update + 54, 2);
	wr16(update + 56, 0x30);
	wr16(update + 58, 2);
	wr16(update + 60, TABLE_HEADER);
	wr16(update + 62, 1);
	wr16(update + 64, 360);
	wr16(update + 66, 24);
	wr16(update + 68, 6);
	wr16(update + 70, 2);
	wr64(update + 80, 4);
	update[88] = 'S';
	update[96] = 'R';
	common(forget, sizeof(forget), 300, 200, 200, 1, 64);
	wr16(forget + 48, 27);
	expect(!rh_replay_analysis_plan(records, 3, &geometry, 100, 300,
			&result), "44-byte dynamic open-attribute format");
	expect(result.dynamic_open_attributes == 1 && result.winner_redos == 1,
		"44-byte dynamic open participates in winner analysis");
}

int main(void)
{
	unsigned char open_dump[144], names[88], dirty_dump[144], tx_dump[144];
	unsigned char checkpoint[152], update[104], forget[88], saved[152];
	struct rh_replay_analysis_result result;
	uint32_t random = 0x8badf00dU;
	unsigned int i;

	build_valid(open_dump, names, dirty_dump, tx_dump, checkpoint, update, forget);
	test_dynamic_open44();
	expect(!analyze(open_dump, names, dirty_dump, tx_dump, checkpoint, update,
		forget, &result), "valid checkpoint analysis");
	expect(result.checkpoint_records == 1 && result.open_attribute_tables == 1 &&
		result.attribute_name_tables == 1 && result.dirty_page_tables == 1 &&
		result.transaction_tables == 1 && result.winner_redos == 1,
		"all analysis controls counted");

	memcpy(saved, open_dump, sizeof(open_dump));
	wr32(open_dump + 80 + TABLE_HEADER + 8, 0x81);
	expect(analyze(open_dump, names, dirty_dump, tx_dump, checkpoint, update,
		forget, NULL), "misaligned open attribute type rejected");
	memcpy(open_dump, saved, sizeof(open_dump));
	memcpy(saved, dirty_dump, sizeof(dirty_dump));
	wr64(dirty_dump + 80 + TABLE_HEADER + 32, UINT64_MAX);
	expect(analyze(open_dump, names, dirty_dump, tx_dump, checkpoint, update,
		forget, NULL), "out-of-volume dirty LCN rejected");
	memcpy(dirty_dump, saved, sizeof(dirty_dump));
	memcpy(saved, tx_dump, sizeof(tx_dump));
	wr32(tx_dump + 80 + TABLE_HEADER, TABLE_HEADER);
	expect(analyze(open_dump, names, dirty_dump, tx_dump, checkpoint, update,
		forget, NULL), "transaction free-list cycle rejected");
	memcpy(tx_dump, saved, sizeof(tx_dump));
	memcpy(saved, checkpoint, sizeof(checkpoint));
	wr32(checkpoint + 96, 63);
	expect(analyze(open_dump, names, dirty_dump, tx_dump, checkpoint, update,
		forget, NULL), "checkpoint/table length mismatch rejected");
	memcpy(checkpoint, saved, sizeof(checkpoint));

	for (i = 0; i < 20000U; ++i) {
		unsigned int at;
		unsigned char old;

		random ^= random << 13;
		random ^= random >> 17;
		random ^= random << 5;
		at = random % sizeof(tx_dump);
		old = tx_dump[at];
		tx_dump[at] ^= (unsigned char)(1U << (random & 7U));
		(void)analyze(open_dump, names, dirty_dump, tx_dump, checkpoint, update,
			forget, NULL);
		tx_dump[at] = old;
	}
	if (failures) {
		fprintf(stderr, "%u roothealth replay analysis checks failed\n", failures);
		return 1;
	}
	puts("PASS roothealth native replay analysis malformed corpus");
	return 0;
}
