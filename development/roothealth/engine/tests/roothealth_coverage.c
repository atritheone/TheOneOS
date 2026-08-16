#include "config.h"

#include <stdio.h>
#include <string.h>

#include "roothealth_coverage.h"

static const char *const required_check_ids[] = {
	"extend.objid", "extend.quota", "extend.reparse", "extend.roothealth",
	"extend.usnjrnl", "system.attrdef", "system.badclus", "system.bitmap",
	"system.boot", "system.extend", "system.logfile", "system.mft",
	"system.mftmirr", "system.root", "system.secure", "system.upcase",
	"system.volume",
};

static void set_known(struct rh_coverage_counter *counter, uint64_t value)
{
	counter->known = true;
	counter->value = value;
}

static void digest_hex(const unsigned char digest[32], char output[65]);

static size_t counter_vector(struct rh_coverage_ledger *ledger,
		struct rh_coverage_counter *counters[RH_COVERAGE_COUNTER_COUNT])
{
	struct rh_coverage_counter *ordered[RH_COVERAGE_COUNTER_COUNT] = {
		&ledger->io_errors, &ledger->skipped,
		&ledger->mft_slots.expected, &ledger->mft_slots.completed,
		&ledger->mft_slots.live, &ledger->mft_slots.free,
		&ledger->mft_slots.unreadable, &ledger->mft_slots.invalid,
		&ledger->attributes.expected, &ledger->attributes.completed,
		&ledger->attributes.resident, &ledger->attributes.nonresident,
		&ledger->attributes.user_defined,
		&ledger->attributes.extents_expected,
		&ledger->attributes.extents_completed,
		&ledger->attributes.runs_expected,
		&ledger->attributes.runs_completed,
		&ledger->attributes.unreadable, &ledger->attributes.skipped,
		&ledger->namespace_links.expected,
		&ledger->namespace_links.completed,
		&ledger->namespace_links.reciprocal,
		&ledger->namespace_links.unresolved,
		&ledger->namespace_links.unreadable,
		&ledger->indexes.expected, &ledger->indexes.completed,
		&ledger->indexes.blocks_allocated,
		&ledger->indexes.blocks_reachable,
		&ledger->indexes.blocks_examined,
		&ledger->indexes.blocks_unreadable,
		&ledger->indexes.bitmap_bits_expected,
		&ledger->indexes.bitmap_bits_examined,
		&ledger->bitmaps.mft_bits_expected,
		&ledger->bitmaps.mft_bits_examined,
		&ledger->bitmaps.cluster_bits_expected,
		&ledger->bitmaps.cluster_bits_examined,
		&ledger->bitmaps.differences,
		&ledger->security.ids_expected,
		&ledger->security.ids_examined,
		&ledger->security.descriptors_expected,
		&ledger->security.descriptors_examined,
		&ledger->security.sds_entries_expected,
		&ledger->security.sds_entries_examined,
		&ledger->security.sdh_entries_expected,
		&ledger->security.sdh_entries_examined,
		&ledger->security.sii_entries_expected,
		&ledger->security.sii_entries_examined,
		&ledger->security.unreadable,
		&ledger->reparse.attributes_expected,
		&ledger->reparse.attributes_examined,
		&ledger->reparse.index_entries_expected,
		&ledger->reparse.index_entries_examined,
		&ledger->reparse.unresolved, &ledger->reparse.unreadable,
		&ledger->compressed.units_expected,
		&ledger->compressed.units_examined,
		&ledger->compressed.unreadable,
		&ledger->fixed_system.expected,
		&ledger->fixed_system.completed,
		&ledger->fixed_system.failed,
	};

	memcpy(counters, ordered, sizeof(ordered));
	return sizeof(ordered) / sizeof(ordered[0]);
}

static int known_vector_test(void)
{
	static const char expected[] =
		"48477bed28045444d8c8b4fbe21f0cafb31172758c2520a19043e908d1b0b885";
	struct rh_coverage_ledger ledger;
	struct rh_coverage_counter *counters[RH_COVERAGE_COUNTER_COUNT];
	struct rh_fixed_check checks[] = {
		{ "attrdef.basic", RH_FIXED_CHECK_PASS },
		{ "mft.0", RH_FIXED_CHECK_FAIL },
		{ "secure-sii", RH_FIXED_CHECK_UNREADABLE },
		{ "upcase-nonascii", RH_FIXED_CHECK_SKIPPED },
	};
	unsigned char digest[32];
	char hex[65];
	size_t i;

	memset(&ledger, 0, sizeof(ledger));
	if (counter_vector(&ledger, counters) != RH_COVERAGE_COUNTER_COUNT)
		return -1;
	for (i = 0; i < RH_COVERAGE_COUNTER_COUNT; i++) {
		if (i == 1U || i == 17U || i == 43U || i == 59U)
			continue;
		set_known(counters[i], (uint64_t)i * UINT64_C(0x01020304050607) + 7U);
	}
	ledger.fixed_system.checks = checks;
	ledger.fixed_system.check_count = sizeof(checks) / sizeof(checks[0]);
	if (rh_coverage_hash(&ledger, digest))
		return -1;
	digest_hex(digest, hex);
	return strcmp(hex, expected) ? -1 : 0;
}

static void initialize_clean(struct rh_coverage_ledger *ledger,
		struct rh_fixed_check *checks)
{
	size_t i;

	memset(ledger, 0, sizeof(*ledger));
	ledger->complete = true;
	for (i = 0; i < sizeof(required_check_ids) / sizeof(required_check_ids[0]);
			i++) {
		checks[i].id = required_check_ids[i];
		checks[i].result = RH_FIXED_CHECK_PASS;
	}
#define RH_KNOWN_ZERO(field_) set_known(&(field_), 0)
	RH_KNOWN_ZERO(ledger->io_errors);
	RH_KNOWN_ZERO(ledger->skipped);
	RH_KNOWN_ZERO(ledger->mft_slots.expected);
	RH_KNOWN_ZERO(ledger->mft_slots.completed);
	RH_KNOWN_ZERO(ledger->mft_slots.live);
	RH_KNOWN_ZERO(ledger->mft_slots.free);
	RH_KNOWN_ZERO(ledger->mft_slots.unreadable);
	RH_KNOWN_ZERO(ledger->mft_slots.invalid);
	RH_KNOWN_ZERO(ledger->attributes.expected);
	RH_KNOWN_ZERO(ledger->attributes.completed);
	RH_KNOWN_ZERO(ledger->attributes.resident);
	RH_KNOWN_ZERO(ledger->attributes.nonresident);
	RH_KNOWN_ZERO(ledger->attributes.user_defined);
	RH_KNOWN_ZERO(ledger->attributes.extents_expected);
	RH_KNOWN_ZERO(ledger->attributes.extents_completed);
	RH_KNOWN_ZERO(ledger->attributes.runs_expected);
	RH_KNOWN_ZERO(ledger->attributes.runs_completed);
	RH_KNOWN_ZERO(ledger->attributes.unreadable);
	RH_KNOWN_ZERO(ledger->attributes.skipped);
	RH_KNOWN_ZERO(ledger->namespace_links.expected);
	RH_KNOWN_ZERO(ledger->namespace_links.completed);
	RH_KNOWN_ZERO(ledger->namespace_links.reciprocal);
	RH_KNOWN_ZERO(ledger->namespace_links.unresolved);
	RH_KNOWN_ZERO(ledger->namespace_links.unreadable);
	RH_KNOWN_ZERO(ledger->indexes.expected);
	RH_KNOWN_ZERO(ledger->indexes.completed);
	RH_KNOWN_ZERO(ledger->indexes.blocks_allocated);
	RH_KNOWN_ZERO(ledger->indexes.blocks_reachable);
	RH_KNOWN_ZERO(ledger->indexes.blocks_examined);
	RH_KNOWN_ZERO(ledger->indexes.blocks_unreadable);
	RH_KNOWN_ZERO(ledger->indexes.bitmap_bits_expected);
	RH_KNOWN_ZERO(ledger->indexes.bitmap_bits_examined);
	RH_KNOWN_ZERO(ledger->bitmaps.mft_bits_expected);
	RH_KNOWN_ZERO(ledger->bitmaps.mft_bits_examined);
	RH_KNOWN_ZERO(ledger->bitmaps.cluster_bits_expected);
	RH_KNOWN_ZERO(ledger->bitmaps.cluster_bits_examined);
	RH_KNOWN_ZERO(ledger->bitmaps.differences);
	RH_KNOWN_ZERO(ledger->security.ids_expected);
	RH_KNOWN_ZERO(ledger->security.ids_examined);
	RH_KNOWN_ZERO(ledger->security.descriptors_expected);
	RH_KNOWN_ZERO(ledger->security.descriptors_examined);
	RH_KNOWN_ZERO(ledger->security.sds_entries_expected);
	RH_KNOWN_ZERO(ledger->security.sds_entries_examined);
	RH_KNOWN_ZERO(ledger->security.sdh_entries_expected);
	RH_KNOWN_ZERO(ledger->security.sdh_entries_examined);
	RH_KNOWN_ZERO(ledger->security.sii_entries_expected);
	RH_KNOWN_ZERO(ledger->security.sii_entries_examined);
	RH_KNOWN_ZERO(ledger->security.unreadable);
	RH_KNOWN_ZERO(ledger->reparse.attributes_expected);
	RH_KNOWN_ZERO(ledger->reparse.attributes_examined);
	RH_KNOWN_ZERO(ledger->reparse.index_entries_expected);
	RH_KNOWN_ZERO(ledger->reparse.index_entries_examined);
	RH_KNOWN_ZERO(ledger->reparse.unresolved);
	RH_KNOWN_ZERO(ledger->reparse.unreadable);
	RH_KNOWN_ZERO(ledger->compressed.units_expected);
	RH_KNOWN_ZERO(ledger->compressed.units_examined);
	RH_KNOWN_ZERO(ledger->compressed.unreadable);
	set_known(&ledger->fixed_system.expected,
		sizeof(required_check_ids) / sizeof(required_check_ids[0]));
	set_known(&ledger->fixed_system.completed,
		sizeof(required_check_ids) / sizeof(required_check_ids[0]));
	RH_KNOWN_ZERO(ledger->fixed_system.failed);
#undef RH_KNOWN_ZERO
	set_known(&ledger->mft_slots.expected, 32);
	set_known(&ledger->mft_slots.completed, 32);
	set_known(&ledger->mft_slots.live, 20);
	set_known(&ledger->mft_slots.free, 12);
	set_known(&ledger->attributes.expected, 64);
	set_known(&ledger->attributes.completed, 64);
	set_known(&ledger->attributes.resident, 63);
	set_known(&ledger->attributes.nonresident, 1);
	set_known(&ledger->attributes.extents_expected, 1);
	set_known(&ledger->attributes.extents_completed, 1);
	set_known(&ledger->attributes.runs_expected, 1);
	set_known(&ledger->attributes.runs_completed, 1);
	set_known(&ledger->namespace_links.expected, 10);
	set_known(&ledger->namespace_links.completed, 10);
	set_known(&ledger->namespace_links.reciprocal, 10);
	set_known(&ledger->indexes.expected, 8);
	set_known(&ledger->indexes.completed, 8);
	set_known(&ledger->bitmaps.mft_bits_expected, 32);
	set_known(&ledger->bitmaps.mft_bits_examined, 32);
	set_known(&ledger->bitmaps.cluster_bits_expected, 1024);
	set_known(&ledger->bitmaps.cluster_bits_examined, 1024);
	set_known(&ledger->security.ids_expected, 1);
	set_known(&ledger->security.ids_examined, 1);
	set_known(&ledger->security.descriptors_expected, 1);
	set_known(&ledger->security.descriptors_examined, 1);
	set_known(&ledger->security.sds_entries_expected, 1);
	set_known(&ledger->security.sds_entries_examined, 1);
	set_known(&ledger->security.sdh_entries_expected, 1);
	set_known(&ledger->security.sdh_entries_examined, 1);
	set_known(&ledger->security.sii_entries_expected, 1);
	set_known(&ledger->security.sii_entries_examined, 1);
	ledger->fixed_system.checks = checks;
	ledger->fixed_system.check_count =
		sizeof(required_check_ids) / sizeof(required_check_ids[0]);
}

static void digest_hex(const unsigned char digest[32], char output[65])
{
	static const char hex[] = "0123456789abcdef";
	size_t i;

	for (i = 0; i < 32U; i++) {
		output[2U * i] = hex[digest[i] >> 4];
		output[2U * i + 1U] = hex[digest[i] & 15U];
	}
	output[64] = 0;
}

int main(void)
{
	struct rh_coverage_ledger ledger;
	struct rh_fixed_check checks[
		sizeof(required_check_ids) / sizeof(required_check_ids[0])];
	unsigned char digest[32];
	char hex[65];

	if (known_vector_test() || rh_coverage_required_fixed_check_count() !=
			sizeof(required_check_ids) / sizeof(required_check_ids[0]))
		return 1;
	for (size_t i = 0; i < rh_coverage_required_fixed_check_count(); i++)
		if (strcmp(rh_coverage_required_fixed_check_id(i),
				required_check_ids[i]))
			return 1;
	initialize_clean(&ledger, checks);
	if (!rh_coverage_is_clean(&ledger) || rh_coverage_hash(&ledger, digest))
		return 1;
	digest_hex(digest, hex);
	ledger.attributes.runs_completed.known = false;
	if (rh_coverage_is_clean(&ledger))
		return 1;
	ledger.attributes.runs_completed.known = true;
	checks[0].result = RH_FIXED_CHECK_UNREADABLE;
	if (rh_coverage_is_clean(&ledger))
		return 1;
	checks[0].result = RH_FIXED_CHECK_PASS;
	checks[0].id = checks[1].id;
	if (!rh_coverage_hash(&ledger, digest) || rh_coverage_is_clean(&ledger))
		return 1;
	checks[0].id = "INVALID";
	if (!rh_coverage_hash(&ledger, digest) || rh_coverage_is_clean(&ledger))
		return 1;
	checks[0].id = "extend.aaaa";
	if (rh_coverage_hash(&ledger, digest) || rh_coverage_is_clean(&ledger))
		return 1;
	checks[0].id = required_check_ids[1];
	checks[1].id = required_check_ids[0];
	if (!rh_coverage_hash(&ledger, digest))
		return 1;
	printf("coverage format=3 counters=60 known_vector=48477bed clean=1 "
		"fixed_checks=17 "
		"null_refused=1 unreadable_refused=1 duplicate_refused=1 "
		"invalid_id_refused=1 unknown_check_refused=1 unsorted_refused=1 "
		"ledger_hash=%s\n", hex);
	return 0;
}
