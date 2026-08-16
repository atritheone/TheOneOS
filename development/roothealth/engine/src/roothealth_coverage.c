/* ROOTHEALTH_REPAIR_ROLE(DIAGNOSTIC) ROOTHEALTH_IO_ROLE(PLANNER) */
#include "config.h"

#include <errno.h>
#include <limits.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include "roothealth_coverage.h"
#include "roothealth_write.h"

static const unsigned char rh_coverage_magic[8] = {
	'R', 'H', 'C', 'O', 'V', '3', 0, 0,
};

static const char *const rh_required_fixed_checks[] = {
	"extend.objid", "extend.quota", "extend.reparse", "extend.roothealth",
	"extend.usnjrnl", "system.attrdef", "system.badclus", "system.bitmap",
	"system.boot", "system.extend", "system.logfile", "system.mft",
	"system.mftmirr", "system.root", "system.secure", "system.upcase",
	"system.volume",
};

size_t rh_coverage_required_fixed_check_count(void)
{
	return sizeof(rh_required_fixed_checks) /
		sizeof(rh_required_fixed_checks[0]);
}

const char *rh_coverage_required_fixed_check_id(size_t index)
{
	if (index >= rh_coverage_required_fixed_check_count()) {
		errno = EINVAL;
		return NULL;
	}
	return rh_required_fixed_checks[index];
}

static void rh_put_u16le(unsigned char *bytes, uint16_t value)
{
	bytes[0] = (unsigned char)value;
	bytes[1] = (unsigned char)(value >> 8);
}

static void rh_put_u32le(unsigned char *bytes, uint32_t value)
{
	unsigned int i;

	for (i = 0; i < 4U; i++)
		bytes[i] = (unsigned char)(value >> (8U * i));
}

static void rh_put_u64le(unsigned char *bytes, uint64_t value)
{
	unsigned int i;

	for (i = 0; i < 8U; i++)
		bytes[i] = (unsigned char)(value >> (8U * i));
}

static size_t rh_coverage_counter_vector(const struct rh_coverage_ledger *ledger,
		const struct rh_coverage_counter *counters[RH_COVERAGE_COUNTER_COUNT])
{
	size_t count = 0;

#define RH_APPEND_COUNTER(counter_) counters[count++] = &(counter_)
	RH_APPEND_COUNTER(ledger->io_errors);
	RH_APPEND_COUNTER(ledger->skipped);
	RH_APPEND_COUNTER(ledger->mft_slots.expected);
	RH_APPEND_COUNTER(ledger->mft_slots.completed);
	RH_APPEND_COUNTER(ledger->mft_slots.live);
	RH_APPEND_COUNTER(ledger->mft_slots.free);
	RH_APPEND_COUNTER(ledger->mft_slots.unreadable);
	RH_APPEND_COUNTER(ledger->mft_slots.invalid);
	RH_APPEND_COUNTER(ledger->attributes.expected);
	RH_APPEND_COUNTER(ledger->attributes.completed);
	RH_APPEND_COUNTER(ledger->attributes.resident);
	RH_APPEND_COUNTER(ledger->attributes.nonresident);
	RH_APPEND_COUNTER(ledger->attributes.user_defined);
	RH_APPEND_COUNTER(ledger->attributes.extents_expected);
	RH_APPEND_COUNTER(ledger->attributes.extents_completed);
	RH_APPEND_COUNTER(ledger->attributes.runs_expected);
	RH_APPEND_COUNTER(ledger->attributes.runs_completed);
	RH_APPEND_COUNTER(ledger->attributes.unreadable);
	RH_APPEND_COUNTER(ledger->attributes.skipped);
	RH_APPEND_COUNTER(ledger->namespace_links.expected);
	RH_APPEND_COUNTER(ledger->namespace_links.completed);
	RH_APPEND_COUNTER(ledger->namespace_links.reciprocal);
	RH_APPEND_COUNTER(ledger->namespace_links.unresolved);
	RH_APPEND_COUNTER(ledger->namespace_links.unreadable);
	RH_APPEND_COUNTER(ledger->indexes.expected);
	RH_APPEND_COUNTER(ledger->indexes.completed);
	RH_APPEND_COUNTER(ledger->indexes.blocks_allocated);
	RH_APPEND_COUNTER(ledger->indexes.blocks_reachable);
	RH_APPEND_COUNTER(ledger->indexes.blocks_examined);
	RH_APPEND_COUNTER(ledger->indexes.blocks_unreadable);
	RH_APPEND_COUNTER(ledger->indexes.bitmap_bits_expected);
	RH_APPEND_COUNTER(ledger->indexes.bitmap_bits_examined);
	RH_APPEND_COUNTER(ledger->bitmaps.mft_bits_expected);
	RH_APPEND_COUNTER(ledger->bitmaps.mft_bits_examined);
	RH_APPEND_COUNTER(ledger->bitmaps.cluster_bits_expected);
	RH_APPEND_COUNTER(ledger->bitmaps.cluster_bits_examined);
	RH_APPEND_COUNTER(ledger->bitmaps.differences);
	RH_APPEND_COUNTER(ledger->security.ids_expected);
	RH_APPEND_COUNTER(ledger->security.ids_examined);
	RH_APPEND_COUNTER(ledger->security.descriptors_expected);
	RH_APPEND_COUNTER(ledger->security.descriptors_examined);
	RH_APPEND_COUNTER(ledger->security.sds_entries_expected);
	RH_APPEND_COUNTER(ledger->security.sds_entries_examined);
	RH_APPEND_COUNTER(ledger->security.sdh_entries_expected);
	RH_APPEND_COUNTER(ledger->security.sdh_entries_examined);
	RH_APPEND_COUNTER(ledger->security.sii_entries_expected);
	RH_APPEND_COUNTER(ledger->security.sii_entries_examined);
	RH_APPEND_COUNTER(ledger->security.unreadable);
	RH_APPEND_COUNTER(ledger->reparse.attributes_expected);
	RH_APPEND_COUNTER(ledger->reparse.attributes_examined);
	RH_APPEND_COUNTER(ledger->reparse.index_entries_expected);
	RH_APPEND_COUNTER(ledger->reparse.index_entries_examined);
	RH_APPEND_COUNTER(ledger->reparse.unresolved);
	RH_APPEND_COUNTER(ledger->reparse.unreadable);
	RH_APPEND_COUNTER(ledger->compressed.units_expected);
	RH_APPEND_COUNTER(ledger->compressed.units_examined);
	RH_APPEND_COUNTER(ledger->compressed.unreadable);
	RH_APPEND_COUNTER(ledger->fixed_system.expected);
	RH_APPEND_COUNTER(ledger->fixed_system.completed);
	RH_APPEND_COUNTER(ledger->fixed_system.failed);
#undef RH_APPEND_COUNTER
	return count;
}

static bool rh_fixed_check_id_valid(const char *id, size_t *length)
{
	size_t i;

	if (!id)
		return false;
	for (i = 0; id[i]; i++) {
		unsigned char c = (unsigned char)id[i];

		if (i == 255U || !((c >= 'a' && c <= 'z') ||
				(c >= '0' && c <= '9') || c == '_' || c == '.' ||
				c == '-'))
			return false;
	}
	if (!i)
		return false;
	*length = i;
	return true;
}

int rh_coverage_hash(const struct rh_coverage_ledger *ledger,
		unsigned char output[32])
{
	const struct rh_coverage_counter *counters[RH_COVERAGE_COUNTER_COUNT];
	unsigned char *encoded = NULL;
	size_t counter_count, encoded_size, position, i;
	int result = -1;

	if (!ledger || !output || ledger->fixed_system.check_count > UINT16_MAX ||
			(ledger->fixed_system.check_count &&
			 !ledger->fixed_system.checks)) {
		errno = EINVAL;
		return -1;
	}
	counter_count = rh_coverage_counter_vector(ledger, counters);
	if (counter_count != RH_COVERAGE_COUNTER_COUNT) {
		errno = EINVAL;
		return -1;
	}
	encoded_size = sizeof(rh_coverage_magic) + 4U + 1U +
		RH_COVERAGE_COUNTER_COUNT * 9U + 4U;
	for (i = 0; i < ledger->fixed_system.check_count; i++) {
		size_t length;

		if (!rh_fixed_check_id_valid(ledger->fixed_system.checks[i].id,
				&length) || ledger->fixed_system.checks[i].result <
				RH_FIXED_CHECK_PASS ||
				ledger->fixed_system.checks[i].result >
				RH_FIXED_CHECK_SKIPPED || encoded_size >
				SIZE_MAX - (2U + length + 1U)) {
			errno = EINVAL;
			goto out;
		}
		if (i && strcmp(ledger->fixed_system.checks[i - 1U].id,
				ledger->fixed_system.checks[i].id) >= 0) {
			errno = EINVAL;
			goto out;
		}
		encoded_size += 2U + length + 1U;
	}
	encoded = malloc(encoded_size);
	if (!encoded)
		goto out;
	position = 0;
	memcpy(encoded + position, rh_coverage_magic, sizeof(rh_coverage_magic));
	position += sizeof(rh_coverage_magic);
	rh_put_u32le(encoded + position, RH_COVERAGE_FORMAT);
	position += 4U;
	encoded[position++] = ledger->complete ? 1U : 0U;
	for (i = 0; i < counter_count; i++) {
		encoded[position++] = counters[i]->known ? 1U : 0U;
		rh_put_u64le(encoded + position,
			counters[i]->known ? counters[i]->value : 0U);
		position += 8U;
	}
	rh_put_u32le(encoded + position,
		(uint32_t)ledger->fixed_system.check_count);
	position += 4U;
	for (i = 0; i < ledger->fixed_system.check_count; i++) {
		size_t length = strlen(ledger->fixed_system.checks[i].id);

		rh_put_u16le(encoded + position, (uint16_t)length);
		position += 2U;
		memcpy(encoded + position, ledger->fixed_system.checks[i].id, length);
		position += length;
		encoded[position++] =
			(unsigned char)ledger->fixed_system.checks[i].result;
	}
	if (position != encoded_size) {
		errno = EINVAL;
		goto out;
	}
	rh_sha256(encoded, encoded_size, output);
	result = 0;
out:
	free(encoded);
	return result;
}

static bool rh_known_equal(const struct rh_coverage_counter *left,
		const struct rh_coverage_counter *right)
{
	return left->known && right->known && left->value == right->value;
}

static bool rh_known_zero(const struct rh_coverage_counter *counter)
{
	return counter->known && !counter->value;
}

static bool rh_known_nonzero(const struct rh_coverage_counter *counter)
{
	return counter->known && counter->value;
}

static bool rh_known_sum(const struct rh_coverage_counter *total,
		const struct rh_coverage_counter *left,
		const struct rh_coverage_counter *right)
{
	return total->known && left->known && right->known &&
		left->value <= total->value && total->value - left->value == right->value;
}

static bool rh_fixed_check_set_complete(const struct rh_coverage_ledger *ledger)
{
	size_t i;

	if (ledger->fixed_system.check_count !=
			rh_coverage_required_fixed_check_count())
		return false;
	for (i = 0; i < ledger->fixed_system.check_count; i++) {
		if (strcmp(rh_required_fixed_checks[i],
				ledger->fixed_system.checks[i].id))
			return false;
	}
	return true;
}

bool rh_coverage_is_clean(const struct rh_coverage_ledger *ledger)
{
	const struct rh_coverage_counter *counters[RH_COVERAGE_COUNTER_COUNT];
	unsigned char ledger_hash[32];
	size_t i;

	if (!ledger || !ledger->complete ||
			rh_coverage_counter_vector(ledger, counters) !=
			RH_COVERAGE_COUNTER_COUNT ||
			rh_coverage_hash(ledger, ledger_hash))
		return false;
	for (i = 0; i < RH_COVERAGE_COUNTER_COUNT; i++) {
		if (!counters[i]->known)
			return false;
	}
	if (!rh_known_zero(&ledger->io_errors) ||
			!rh_known_zero(&ledger->skipped) ||
			!rh_known_nonzero(&ledger->mft_slots.expected) ||
			!rh_known_equal(&ledger->mft_slots.expected,
				&ledger->mft_slots.completed) ||
			!rh_known_sum(&ledger->mft_slots.expected,
				&ledger->mft_slots.live, &ledger->mft_slots.free) ||
			!rh_known_zero(&ledger->mft_slots.unreadable) ||
			!rh_known_zero(&ledger->mft_slots.invalid) ||
			!rh_known_nonzero(&ledger->attributes.expected) ||
			!rh_known_nonzero(&ledger->attributes.nonresident) ||
			!rh_known_nonzero(&ledger->attributes.runs_expected) ||
			!rh_known_equal(&ledger->attributes.expected,
				&ledger->attributes.completed) ||
			!rh_known_sum(&ledger->attributes.completed,
				&ledger->attributes.resident,
				&ledger->attributes.nonresident) ||
			ledger->attributes.user_defined.value >
				ledger->attributes.completed.value ||
			!rh_known_equal(&ledger->attributes.extents_expected,
				&ledger->attributes.extents_completed) ||
			!rh_known_equal(&ledger->attributes.runs_expected,
				&ledger->attributes.runs_completed) ||
			!rh_known_zero(&ledger->attributes.unreadable) ||
			!rh_known_zero(&ledger->attributes.skipped) ||
			!rh_known_nonzero(&ledger->namespace_links.expected) ||
			!rh_known_equal(&ledger->namespace_links.expected,
				&ledger->namespace_links.completed) ||
			!rh_known_equal(&ledger->namespace_links.expected,
				&ledger->namespace_links.reciprocal) ||
			!rh_known_zero(&ledger->namespace_links.unresolved) ||
			!rh_known_zero(&ledger->namespace_links.unreadable) ||
			!rh_known_nonzero(&ledger->indexes.expected) ||
			!rh_known_equal(&ledger->indexes.expected,
				&ledger->indexes.completed) ||
			!rh_known_equal(&ledger->indexes.blocks_allocated,
				&ledger->indexes.blocks_reachable) ||
			!rh_known_equal(&ledger->indexes.blocks_allocated,
				&ledger->indexes.blocks_examined) ||
			!rh_known_zero(&ledger->indexes.blocks_unreadable) ||
			!rh_known_equal(&ledger->indexes.bitmap_bits_expected,
				&ledger->indexes.bitmap_bits_examined) ||
			!rh_known_nonzero(&ledger->bitmaps.mft_bits_expected) ||
			!rh_known_nonzero(&ledger->bitmaps.cluster_bits_expected) ||
			!rh_known_equal(&ledger->bitmaps.mft_bits_expected,
				&ledger->bitmaps.mft_bits_examined) ||
			!rh_known_equal(&ledger->bitmaps.cluster_bits_expected,
				&ledger->bitmaps.cluster_bits_examined) ||
			!rh_known_zero(&ledger->bitmaps.differences) ||
			!rh_known_nonzero(&ledger->security.ids_expected) ||
			!rh_known_nonzero(&ledger->security.descriptors_expected) ||
			!rh_known_nonzero(&ledger->security.sds_entries_expected) ||
			!rh_known_nonzero(&ledger->security.sdh_entries_expected) ||
			!rh_known_nonzero(&ledger->security.sii_entries_expected) ||
			!rh_known_equal(&ledger->security.ids_expected,
				&ledger->security.ids_examined) ||
			!rh_known_equal(&ledger->security.descriptors_expected,
				&ledger->security.descriptors_examined) ||
			!rh_known_equal(&ledger->security.sds_entries_expected,
				&ledger->security.sds_entries_examined) ||
			!rh_known_equal(&ledger->security.sdh_entries_expected,
				&ledger->security.sdh_entries_examined) ||
			!rh_known_equal(&ledger->security.sii_entries_expected,
				&ledger->security.sii_entries_examined) ||
			!rh_known_zero(&ledger->security.unreadable) ||
			!rh_known_equal(&ledger->reparse.attributes_expected,
				&ledger->reparse.attributes_examined) ||
			!rh_known_equal(&ledger->reparse.index_entries_expected,
				&ledger->reparse.index_entries_examined) ||
			!rh_known_zero(&ledger->reparse.unresolved) ||
			!rh_known_zero(&ledger->reparse.unreadable) ||
			!rh_known_equal(&ledger->compressed.units_expected,
				&ledger->compressed.units_examined) ||
			!rh_known_zero(&ledger->compressed.unreadable) ||
			!rh_known_equal(&ledger->fixed_system.expected,
				&ledger->fixed_system.completed) ||
			!rh_known_zero(&ledger->fixed_system.failed) ||
			ledger->fixed_system.expected.value !=
			ledger->fixed_system.check_count ||
			(ledger->fixed_system.check_count &&
			 !ledger->fixed_system.checks) ||
			!rh_fixed_check_set_complete(ledger))
		return false;
	for (i = 0; i < ledger->fixed_system.check_count; i++) {
		if (ledger->fixed_system.checks[i].result != RH_FIXED_CHECK_PASS)
			return false;
	}
	return true;
}
