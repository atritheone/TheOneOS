
/* ROOTHEALTH_REPAIR_ROLE(REPORT) ROOTHEALTH_IO_ROLE(REPORT) */
#include "config.h"

#include <errno.h>
#include <inttypes.h>
#include <stdint.h>
#ifdef ROOTHEALTH_FORMAT3_TEST_HOOKS
#include <stdlib.h>
#endif
#include <string.h>
#include <sys/sysmacros.h>

#include "roothealth_format3.h"

#include "roothealth_hash_stream.h"

/* Compile-time lengths for literal and adjacent-literal JSON fragments. */
#define RH_APPEND_LITERAL(report, literal) \
	rh_report_append((report), (literal), sizeof(literal) - 1U)

static const char rh_unavailable_coverage_hash[] =
	"fd2ded85e5d9dacae9cd6a9f03f987ac97f4a655f9d397b0fd1bd82aa2aa61ac";
static const char rh_empty_batch_hash[] =
	"02aa38ce7a8e62b93190e6088f62d2d17ec3d93aee44532d50efdef42941cb90";
static const char rh_empty_wal_hash[] =
	"e2050efb40ae6807a9483334f8aee9d5beb17241917ab8537709dc20e32f4b68";
static const char rh_size_hash[] =
	"03e7d405abfb81027dddd44ec44c970b7f35221deddaabb55e78ededcf70f8a4";

static int rh_decode_hex_report(const char text[65], unsigned char output[32]);

struct rh_issue_detail {
	const char *code;
	const char *pass;
	const char *message;
	const char *severity;
	unsigned int severity_code;
	const char *predicates[8];
	unsigned int predicate_count;
};

static int rh_issue_add_predicate(struct rh_issue_detail *issue,
		const char *predicate)
{
	unsigned int i, position;

	if (!issue || !predicate || !*predicate)
		return -1;
	for (i = 0; i < issue->predicate_count; i++)
		if (!strcmp(issue->predicates[i], predicate))
			return 0;
	if (issue->predicate_count >=
			sizeof(issue->predicates) / sizeof(issue->predicates[0]))
		return -1;
	position = issue->predicate_count++;
	while (position && strcmp(issue->predicates[position - 1U], predicate) > 0) {
		issue->predicates[position] = issue->predicates[position - 1U];
		position--;
	}
	issue->predicates[position] = predicate;
	return 0;
}

static void rh_put_le16(unsigned char output[2], uint16_t value)
{
	output[0] = (unsigned char)value;
	output[1] = (unsigned char)(value >> 8);
}

static void rh_put_le32_report(unsigned char output[4], uint32_t value)
{
	output[0] = (unsigned char)value;
	output[1] = (unsigned char)(value >> 8);
	output[2] = (unsigned char)(value >> 16);
	output[3] = (unsigned char)(value >> 24);
}

static void rh_put_le64_report(unsigned char output[8], uint64_t value)
{
	size_t i;
	for (i = 0; i < 8; i++)
		output[i] = (unsigned char)(value >> (8U * i));
}

static int rh_hash_text(struct rh_hash_stream *hash, const char *text)
{
	unsigned char length[2];
	size_t size = strlen(text);

	if (size >= UINT16_MAX)
		return -1;
	rh_put_le16(length, (uint16_t)size);
	return rh_hash_stream_update(hash, length, sizeof(length)) ||
		rh_hash_stream_update(hash, text, size);
}

static void rh_hex_report(const unsigned char *bytes, size_t length,
		char *output)
{
	static const char digits[] = "0123456789abcdef";
	size_t i;
	for (i = 0; i < length; i++) {
		output[i * 2] = digits[bytes[i] >> 4];
		output[i * 2 + 1] = digits[bytes[i] & 15U];
	}
	output[length * 2] = 0;
}

static int rh_issue_ledger_hash(const struct rh_issue_detail *issue,
		char output[65])
{
	struct rh_hash_stream hash;
	unsigned char integer[8], header[12], digest[32];
	unsigned char fields[12] = { 0 };
	unsigned int i;

	rh_hash_stream_init(&hash);
	rh_put_le32_report(header, 3);
	rh_put_le64_report(header + 4, 1);
	if (rh_hash_stream_update(&hash, "RHISS3\0\0", 8) ||
			rh_hash_stream_update(&hash, header, sizeof(header)))
		return -1;
	rh_put_le64_report(fields, 0);
	fields[8] = (unsigned char)issue->severity_code;
	fields[9] = 0; /* unresolved */
	fields[10] = 3; /* DENY */
	fields[11] = 0;
	if (rh_hash_stream_update(&hash, fields, sizeof(fields)))
		return -1;
	memset(integer, 0xff, sizeof(integer));
	if (rh_hash_stream_update(&hash, integer, sizeof(integer)) ||
			rh_hash_stream_update(&hash, integer, sizeof(integer)) ||
			rh_hash_text(&hash, issue->code) ||
			rh_hash_text(&hash, issue->pass))
		return -1;
	rh_put_le16(fields, UINT16_MAX); /* null path */
	if (rh_hash_stream_update(&hash, fields, 2) ||
			rh_hash_text(&hash, issue->message))
		return -1;
	rh_put_le16(fields, (uint16_t)issue->predicate_count);
	if (rh_hash_stream_update(&hash, fields, 2))
		return -1;
	for (i = 0; i < issue->predicate_count; i++)
		if (rh_hash_text(&hash, issue->predicates[i]))
			return -1;
	if (rh_hash_stream_update(&hash, fields, 2))
		return -1;
	for (i = 0; i < issue->predicate_count; i++)
		if (rh_hash_text(&hash, issue->predicates[i]))
			return -1;
	memset(fields, 0, 4); /* no action ordinals */
	if (rh_hash_stream_update(&hash, fields, 4) ||
			rh_hash_stream_final(&hash, digest))
		return -1;
	rh_hex_report(digest, sizeof(digest), output);
	return 0;
}

static int rh_bool_or_null(struct rh_report *report, int known, int value)
{
	return rh_report_appendf(report, "%s",
		known ? (value ? "true" : "false") : "null");
}

static int rh_execution(struct rh_report *report,
		const struct rh_execution_evidence *execution)
{
	if (RH_APPEND_LITERAL(report, "{\"binary_sha256\":") ||
			rh_report_json_string(report, execution->binary_sha256) ||
			rh_report_appendf(report,
				",\"device_fd_inherited\":%s,\"exec_id\":",
				execution->device_fd_inherited ? "true" : "false") ||
			rh_report_json_string(report, execution->exec_id) ||
			rh_report_appendf(report,
				",\"parent_pid\":%"PRIu64",\"pid\":%"PRIu64
				",\"pipe_payload_bytes\":%"PRIu64
				",\"report_fd_inherited\":%s,\"role\":",
				execution->parent_pid, execution->pid,
				execution->pipe_payload_bytes,
				execution->report_fd_inherited ? "true" : "false") ||
			rh_report_json_string(report, execution->role) ||
			RH_APPEND_LITERAL(report, ",\"timed_out\":") ||
			rh_bool_or_null(report, execution->timed_out_known,
				execution->timed_out) ||
			RH_APPEND_LITERAL(report, ",\"timeout_ms\":"))
		return -1;
	if (execution->timeout_known) {
		if (rh_report_appendf(report, "%u", execution->timeout_ms))
			return -1;
	} else if (RH_APPEND_LITERAL(report, "null"))
		return -1;
	if (RH_APPEND_LITERAL(report, ",\"transport\":") ||
			rh_report_json_string(report, execution->transport) ||
			RH_APPEND_LITERAL(report, ",\"transport_exit_status\":"))
		return -1;
	if (execution->transport_status_known) {
		if (rh_report_appendf(report, "%d", execution->transport_status))
			return -1;
	} else if (RH_APPEND_LITERAL(report, "null"))
		return -1;
	return RH_APPEND_LITERAL(report, "}");
}

static int rh_coverage_unavailable(struct rh_report *report)
{
	return rh_report_appendf(report,
		"{\"attributes\":{\"completed\":null,\"expected\":null,"
		"\"extents_completed\":null,\"extents_expected\":null,"
		"\"nonresident\":null,\"resident\":null,\"runs_completed\":null,"
		"\"runs_expected\":null,\"skipped\":null,\"unreadable\":null,"
		"\"user_defined\":null},\"bitmaps\":{\"cluster_bits_examined\":null,"
		"\"cluster_bits_expected\":null,\"differences\":null,"
		"\"mft_bits_examined\":null,\"mft_bits_expected\":null},"
		"\"complete\":false,\"compressed\":{\"units_examined\":null,"
		"\"units_expected\":null,\"unreadable\":null},\"fixed_system\":{"
		"\"checks\":[],\"completed\":null,\"expected\":null,\"failed\":null},"
		"\"indexes\":{\"bitmap_bits_examined\":null,"
		"\"bitmap_bits_expected\":null,\"blocks_allocated\":null,"
		"\"blocks_examined\":null,\"blocks_reachable\":null,"
		"\"blocks_unreadable\":null,\"completed\":null,\"expected\":null},"
		"\"io_errors\":null,\"ledger_hash\":\"%s\",\"mft_slots\":{"
		"\"completed\":null,\"expected\":null,\"free\":null,\"invalid\":null,"
		"\"live\":null,\"unreadable\":null},\"namespace_links\":{"
		"\"completed\":null,\"expected\":null,\"reciprocal\":null,"
		"\"unreadable\":null,\"unresolved\":null},\"reparse\":{"
		"\"attributes_examined\":null,\"attributes_expected\":null,"
		"\"index_entries_examined\":null,\"index_entries_expected\":null,"
		"\"unreadable\":null,\"unresolved\":null},\"security\":{"
		"\"descriptors_examined\":null,\"descriptors_expected\":null,"
		"\"ids_examined\":null,\"ids_expected\":null,"
		"\"sdh_entries_examined\":null,\"sdh_entries_expected\":null,"
		"\"sds_entries_examined\":null,\"sds_entries_expected\":null,"
		"\"sii_entries_examined\":null,\"sii_entries_expected\":null,"
		"\"unreadable\":null},\"skipped\":null}",
		rh_unavailable_coverage_hash);
}

static int rh_coverage_counter(struct rh_report *report,
		const struct rh_coverage_counter *counter)
{
	if (!counter || !counter->known)
		return RH_APPEND_LITERAL(report, "null");
	return rh_report_appendf(report, "%"PRIu64, counter->value);
}

static const char *rh_fixed_result_name(enum rh_fixed_check_result result)
{
	switch (result) {
	case RH_FIXED_CHECK_PASS: return "PASS";
	case RH_FIXED_CHECK_FAIL: return "FAIL";
	case RH_FIXED_CHECK_UNREADABLE: return "UNREADABLE";
	case RH_FIXED_CHECK_SKIPPED: return "SKIPPED";
	default: return NULL;
	}
}

#define RH_COV_FIELD(report, name, value) \
	(RH_APPEND_LITERAL((report), name) || rh_coverage_counter((report), (value)))

static int rh_coverage(struct rh_report *report,
		const struct rh_scan_evidence *scan)
{
	const struct rh_coverage_ledger *c;
	char hash[65];
	size_t i;

	if (!scan || !scan->census_available)
		return rh_coverage_unavailable(report);
	c = &scan->census.coverage;
	rh_hex_report(scan->census.coverage_hash, 32, hash);
	if (RH_APPEND_LITERAL(report, "{\"attributes\":{") ||
			RH_COV_FIELD(report, "\"completed\":", &c->attributes.completed) ||
			RH_COV_FIELD(report, ",\"expected\":", &c->attributes.expected) ||
			RH_COV_FIELD(report, ",\"extents_completed\":",
				&c->attributes.extents_completed) ||
			RH_COV_FIELD(report, ",\"extents_expected\":",
				&c->attributes.extents_expected) ||
			RH_COV_FIELD(report, ",\"nonresident\":",
				&c->attributes.nonresident) ||
			RH_COV_FIELD(report, ",\"resident\":", &c->attributes.resident) ||
			RH_COV_FIELD(report, ",\"runs_completed\":",
				&c->attributes.runs_completed) ||
			RH_COV_FIELD(report, ",\"runs_expected\":",
				&c->attributes.runs_expected) ||
			RH_COV_FIELD(report, ",\"skipped\":", &c->attributes.skipped) ||
			RH_COV_FIELD(report, ",\"unreadable\":",
				&c->attributes.unreadable) ||
			RH_COV_FIELD(report, ",\"user_defined\":",
				&c->attributes.user_defined) ||
			RH_APPEND_LITERAL(report, "},\"bitmaps\":{") ||
			RH_COV_FIELD(report, "\"cluster_bits_examined\":",
				&c->bitmaps.cluster_bits_examined) ||
			RH_COV_FIELD(report, ",\"cluster_bits_expected\":",
				&c->bitmaps.cluster_bits_expected) ||
			RH_COV_FIELD(report, ",\"differences\":", &c->bitmaps.differences) ||
			RH_COV_FIELD(report, ",\"mft_bits_examined\":",
				&c->bitmaps.mft_bits_examined) ||
			RH_COV_FIELD(report, ",\"mft_bits_expected\":",
				&c->bitmaps.mft_bits_expected) ||
			rh_report_appendf(report, "},\"complete\":%s,\"compressed\":{",
				c->complete ? "true" : "false") ||
			RH_COV_FIELD(report, "\"units_examined\":",
				&c->compressed.units_examined) ||
			RH_COV_FIELD(report, ",\"units_expected\":",
				&c->compressed.units_expected) ||
			RH_COV_FIELD(report, ",\"unreadable\":",
				&c->compressed.unreadable) ||
			RH_APPEND_LITERAL(report, "},\"fixed_system\":{\"checks\":["))
		return -1;
	for (i = 0; i < c->fixed_system.check_count; i++) {
		const char *result = rh_fixed_result_name(c->fixed_system.checks[i].result);
		if (!result || (i && RH_APPEND_LITERAL(report, ",")) ||
				RH_APPEND_LITERAL(report, "{\"id\":") ||
				rh_report_json_string(report, c->fixed_system.checks[i].id) ||
				RH_APPEND_LITERAL(report, ",\"result\":") ||
				rh_report_json_string(report, result) ||
				RH_APPEND_LITERAL(report, "}"))
			return -1;
	}
	if (RH_COV_FIELD(report, "],\"completed\":",
			&c->fixed_system.completed) ||
			RH_COV_FIELD(report, ",\"expected\":", &c->fixed_system.expected) ||
			RH_COV_FIELD(report, ",\"failed\":", &c->fixed_system.failed) ||
			RH_APPEND_LITERAL(report, "},\"indexes\":{") ||
			RH_COV_FIELD(report, "\"bitmap_bits_examined\":",
				&c->indexes.bitmap_bits_examined) ||
			RH_COV_FIELD(report, ",\"bitmap_bits_expected\":",
				&c->indexes.bitmap_bits_expected) ||
			RH_COV_FIELD(report, ",\"blocks_allocated\":",
				&c->indexes.blocks_allocated) ||
			RH_COV_FIELD(report, ",\"blocks_examined\":",
				&c->indexes.blocks_examined) ||
			RH_COV_FIELD(report, ",\"blocks_reachable\":",
				&c->indexes.blocks_reachable) ||
			RH_COV_FIELD(report, ",\"blocks_unreadable\":",
				&c->indexes.blocks_unreadable) ||
			RH_COV_FIELD(report, ",\"completed\":", &c->indexes.completed) ||
			RH_COV_FIELD(report, ",\"expected\":", &c->indexes.expected) ||
			RH_APPEND_LITERAL(report, "},\"io_errors\":") ||
			rh_coverage_counter(report, &c->io_errors) ||
			RH_APPEND_LITERAL(report, ",\"ledger_hash\":") ||
			rh_report_json_string(report, hash) ||
			RH_APPEND_LITERAL(report, ",\"mft_slots\":{") ||
			RH_COV_FIELD(report, "\"completed\":", &c->mft_slots.completed) ||
			RH_COV_FIELD(report, ",\"expected\":", &c->mft_slots.expected) ||
			RH_COV_FIELD(report, ",\"free\":", &c->mft_slots.free) ||
			RH_COV_FIELD(report, ",\"invalid\":", &c->mft_slots.invalid) ||
			RH_COV_FIELD(report, ",\"live\":", &c->mft_slots.live) ||
			RH_COV_FIELD(report, ",\"unreadable\":", &c->mft_slots.unreadable) ||
			RH_APPEND_LITERAL(report, "},\"namespace_links\":{") ||
			RH_COV_FIELD(report, "\"completed\":", &c->namespace_links.completed) ||
			RH_COV_FIELD(report, ",\"expected\":", &c->namespace_links.expected) ||
			RH_COV_FIELD(report, ",\"reciprocal\":",
				&c->namespace_links.reciprocal) ||
			RH_COV_FIELD(report, ",\"unreadable\":",
				&c->namespace_links.unreadable) ||
			RH_COV_FIELD(report, ",\"unresolved\":",
				&c->namespace_links.unresolved) ||
			RH_APPEND_LITERAL(report, "},\"reparse\":{") ||
			RH_COV_FIELD(report, "\"attributes_examined\":",
				&c->reparse.attributes_examined) ||
			RH_COV_FIELD(report, ",\"attributes_expected\":",
				&c->reparse.attributes_expected) ||
			RH_COV_FIELD(report, ",\"index_entries_examined\":",
				&c->reparse.index_entries_examined) ||
			RH_COV_FIELD(report, ",\"index_entries_expected\":",
				&c->reparse.index_entries_expected) ||
			RH_COV_FIELD(report, ",\"unreadable\":", &c->reparse.unreadable) ||
			RH_COV_FIELD(report, ",\"unresolved\":", &c->reparse.unresolved) ||
			RH_APPEND_LITERAL(report, "},\"security\":{") ||
			RH_COV_FIELD(report, "\"descriptors_examined\":",
				&c->security.descriptors_examined) ||
			RH_COV_FIELD(report, ",\"descriptors_expected\":",
				&c->security.descriptors_expected) ||
			RH_COV_FIELD(report, ",\"ids_examined\":", &c->security.ids_examined) ||
			RH_COV_FIELD(report, ",\"ids_expected\":", &c->security.ids_expected) ||
			RH_COV_FIELD(report, ",\"sdh_entries_examined\":",
				&c->security.sdh_entries_examined) ||
			RH_COV_FIELD(report, ",\"sdh_entries_expected\":",
				&c->security.sdh_entries_expected) ||
			RH_COV_FIELD(report, ",\"sds_entries_examined\":",
				&c->security.sds_entries_examined) ||
			RH_COV_FIELD(report, ",\"sds_entries_expected\":",
				&c->security.sds_entries_expected) ||
			RH_COV_FIELD(report, ",\"sii_entries_examined\":",
				&c->security.sii_entries_examined) ||
			RH_COV_FIELD(report, ",\"sii_entries_expected\":",
				&c->security.sii_entries_expected) ||
			RH_COV_FIELD(report, ",\"unreadable\":", &c->security.unreadable) ||
			RH_APPEND_LITERAL(report, "},\"skipped\":") ||
			rh_coverage_counter(report, &c->skipped) || RH_APPEND_LITERAL(report, "}"))
		return -1;
	return 0;
}

#undef RH_COV_FIELD

static int rh_snapshot(struct rh_report *report,
		const struct rh_scan_evidence *scan, int rescan,
		uint64_t ordinal, const char *binding, const char *transaction_uuid,
		const char *plan_hash, const char *stage)
{
	const char *native = rh_native_state(scan);

	if (RH_APPEND_LITERAL(report, "{"))
		return -1;
	if (rescan && (RH_APPEND_LITERAL(report, "\"binding\":") ||
			rh_report_json_string(report, binding) ||
			RH_APPEND_LITERAL(report, ",")))
		return -1;
	if (rh_report_appendf(report, "\"completed\":%s,\"coverage\":",
			scan->completed ? "true" : "false") ||
			rh_coverage(report, scan) ||
			RH_APPEND_LITERAL(report, ",\"dirty\":") ||
			rh_bool_or_null(report, scan->dirty_known, scan->dirty) ||
			RH_APPEND_LITERAL(report, ",\"execution\":") ||
			rh_execution(report, &scan->execution) ||
			rh_report_appendf(report,
				",\"exit_code\":%d,\"fresh_process\":true,"
				"\"identity_valid\":", scan->result) ||
			rh_bool_or_null(report, scan->identity.prewrite_checked,
				scan->identity_valid) ||
			RH_APPEND_LITERAL(report, ",\"logfile_clean\":") ||
			rh_bool_or_null(report, scan->logfile_clean_known,
				scan->logfile_clean) ||
			RH_APPEND_LITERAL(report, ",\"native_log_state\":"))
		return -1;
	if (native) {
		if (rh_report_json_string(report, native))
			return -1;
	} else if (RH_APPEND_LITERAL(report, "null"))
		return -1;
	if (rescan && rh_report_appendf(report,
			",\"ordinal\":%"PRIu64",\"plan_hash\":", ordinal))
		return -1;
	if (rescan) {
		if (plan_hash) {
			if (rh_report_json_string(report, plan_hash))
				return -1;
		} else if (RH_APPEND_LITERAL(report, "null"))
			return -1;
	}
	if (RH_APPEND_LITERAL(report, ",\"read_only\":true,\"result\":") ||
			rh_report_json_string(report, rh_public_result(scan->result)) ||
			RH_APPEND_LITERAL(report, ",\"scan_id\":") ||
			rh_report_json_string(report, scan->scan_id))
		return -1;
	if (rescan) {
		if (RH_APPEND_LITERAL(report, ",\"stage\":") ||
				rh_report_json_string(report, stage) ||
				RH_APPEND_LITERAL(report, ",\"transaction_uuid\":"))
			return -1;
		if (transaction_uuid) {
			if (rh_report_json_string(report, transaction_uuid))
				return -1;
		} else if (RH_APPEND_LITERAL(report, "null"))
			return -1;
	}
	return RH_APPEND_LITERAL(report, "}");
}

static int rh_slice_hash(const char magic[8], const char *bytes, size_t length,
		char output[65])
{
	struct rh_hash_stream hash;
	unsigned char header[12], digest[32];

	rh_put_le32_report(header, 3U);
	rh_put_le64_report(header + 4U, length);
	rh_hash_stream_init(&hash);
	if (rh_hash_stream_update(&hash, magic, 8U) ||
			rh_hash_stream_update(&hash, header, sizeof(header)) ||
			rh_hash_stream_update(&hash, bytes, length) ||
			rh_hash_stream_final(&hash, digest))
		return -1;
	rh_hex_report(digest, sizeof(digest), output);
	return 0;
}

static int rh_snapshot_hash(struct rh_report *report,
		const struct rh_scan_evidence *scan, uint64_t ordinal,
		const char *binding, const char *transaction_uuid,
		const char *plan_hash, const char *stage, char output[65])
{
	size_t saved = report->used;
	int result;

	if (rh_snapshot(report, scan, 1, ordinal, binding, transaction_uuid,
			plan_hash, stage))
		return -1;
	result = rh_slice_hash("RHSCAN3\0", report->buffer + saved,
		report->used - saved, output);
	report->used = saved;
	return result;
}

static int rh_diagnosis_hash(struct rh_report *report,
		const struct rh_scan_evidence *scan, char output[65])
{
	const char *native = rh_native_state(scan);
	size_t saved = report->used;
	int result;

	if (rh_report_appendf(report, "{\"completed\":%s,\"dirty\":",
			scan->completed ? "true" : "false") ||
			rh_bool_or_null(report, scan->dirty_known, scan->dirty) ||
			rh_report_appendf(report, ",\"exit_code\":%d,\"identity_valid\":",
				scan->result) ||
			rh_bool_or_null(report, scan->identity.prewrite_checked,
				scan->identity_valid) ||
			RH_APPEND_LITERAL(report, ",\"logfile_clean\":") ||
			rh_bool_or_null(report, scan->logfile_clean_known,
				scan->logfile_clean) ||
			RH_APPEND_LITERAL(report, ",\"native_log_state\":"))
		return -1;
	if (native) {
		if (rh_report_json_string(report, native))
			return -1;
	} else if (RH_APPEND_LITERAL(report, "null"))
		return -1;
	if (RH_APPEND_LITERAL(report, ",\"result\":") ||
			rh_report_json_string(report, rh_public_result(scan->result)) ||
			RH_APPEND_LITERAL(report, "}"))
		return -1;
	result = rh_slice_hash("RHDIAG3\0", report->buffer + saved,
		report->used - saved, output);
	report->used = saved;
	return result;
}

static int rh_device(struct rh_report *report,
		const struct rh_device_evidence *device)
{
	if (RH_APPEND_LITERAL(report, "{\"mapper_name\":null,\"requested_dev\":") ||
			rh_report_appendf(report,
				"\"%"PRIu64"\",\"requested_ino\":\"%"PRIu64
				"\",\"requested_path\":",
				(uint64_t)device->requested_stat.st_dev,
				(uint64_t)device->requested_stat.st_ino) ||
			rh_report_json_string(report, device->requested) ||
			rh_report_appendf(report,
				",\"requested_was_symlink\":%s,"
				"\"resolved_dev\":\"%"PRIu64"\","
				"\"resolved_ino\":\"%"PRIu64"\","
				"\"resolved_major\":%u,\"resolved_minor\":%u,"
				"\"resolved_path\":",
				device->requested_was_symlink ? "true" : "false",
				(uint64_t)device->resolved_stat.st_dev,
				(uint64_t)device->resolved_stat.st_ino,
				(unsigned int)major(device->resolved_stat.st_rdev),
				(unsigned int)minor(device->resolved_stat.st_rdev)) ||
			rh_report_json_string(report, device->resolved) ||
			rh_report_appendf(report,
				",\"resolved_type\":\"%s\",\"selection_proven\":%s}",
				S_ISBLK(device->resolved_stat.st_mode) ?
					"block" : "regular",
				device->selection_proven ? "true" : "false"))
		return -1;
	return 0;
}

static int rh_identity(struct rh_report *report, const struct rh_cli *cli,
		const struct rh_scan_evidence *scan)
{
	if (RH_APPEND_LITERAL(report, "{\"anchor\":") ||
			(scan->identity.prewrite_checked && scan->identity.anchor[0] ?
				rh_report_json_string(report, scan->identity.anchor) :
				RH_APPEND_LITERAL(report, "null")) ||
			RH_APPEND_LITERAL(report, ",\"expected_label\":\"T1OS\","
				"\"expected_serial\":") ||
			rh_report_appendf(report, "\"0x%016"PRIx64"\","
				"\"observed_backup_serial\":", cli->expected_serial))
		return -1;
	if (scan->identity.prewrite_checked &&
			scan->identity.observed_backup_serial) {
		if (rh_report_appendf(report, "\"0x%016"PRIx64"\"",
				scan->identity.observed_backup_serial))
			return -1;
	} else if (RH_APPEND_LITERAL(report, "null"))
		return -1;
	if (RH_APPEND_LITERAL(report, ",\"observed_label\":") ||
			(scan->identity.prewrite_checked &&
			 scan->identity.observed_label[0] ?
				rh_report_json_string(report, scan->identity.observed_label) :
				RH_APPEND_LITERAL(report, "null")) ||
			RH_APPEND_LITERAL(report, ",\"observed_primary_serial\":"))
		return -1;
	if (scan->identity.prewrite_checked &&
			scan->identity.observed_primary_serial) {
		if (rh_report_appendf(report, "\"0x%016"PRIx64"\"",
				scan->identity.observed_primary_serial))
			return -1;
	} else if (RH_APPEND_LITERAL(report, "null"))
		return -1;
	if (rh_report_appendf(report,
			",\"prewrite_checked\":%s,\"prewrite_valid\":",
			scan->identity.prewrite_checked ? "true" : "false") ||
			rh_bool_or_null(report, scan->identity.prewrite_checked,
				scan->identity_valid))
		return -1;
	return RH_APPEND_LITERAL(report, "}");
}

static int rh_native(struct rh_report *report,
		const struct rh_scan_evidence *scan)
{
	const struct rh_log_result *log = &scan->native_log;
	const char *state = rh_native_state(scan);
	int checked = log->checked && state;
	int restart_evidence = checked &&
		(log->state == RH_NATIVE_LOG_CLEAN_RESTART ||
		 log->state == RH_NATIVE_LOG_REPLAY_PLANNED);

	/*
	 * Native-log evidence is retained, but this slice zeroes its physical plan
	 * after classifying imported replay as unsupported.
	 */
	if (rh_report_appendf(report,
			"{\"checked\":%s,\"state\":", checked ? "true" : "false"))
		return -1;
	if (checked) {
		if (rh_report_json_string(report, state))
			return -1;
	} else if (RH_APPEND_LITERAL(report, "null"))
		return -1;
	if (RH_APPEND_LITERAL(report, ",\"logfile_bytes\":"))
		return -1;
	if (checked) {
		if (rh_report_appendf(report, "%"PRIu64,
				(uint64_t)log->logfile_bytes))
			return -1;
	} else if (RH_APPEND_LITERAL(report, "null"))
		return -1;
	if (RH_APPEND_LITERAL(report, ",\"pages_expected\":"))
		return -1;
	if (checked) {
		if (rh_report_appendf(report, "%u", log->pages_expected))
			return -1;
	} else if (RH_APPEND_LITERAL(report, "null"))
		return -1;
	if (rh_report_appendf(report,
			",\"pages_examined\":%u,\"wiped_pages_scanned\":%u,"
			"\"version_major\":",
			checked ? log->pages_examined : 0,
			checked ? log->wiped_pages_scanned : 0))
		return -1;
	if (restart_evidence) {
		if (rh_report_appendf(report, "%d", log->major_version))
			return -1;
	} else if (RH_APPEND_LITERAL(report, "null"))
		return -1;
	if (RH_APPEND_LITERAL(report, ",\"version_minor\":"))
		return -1;
	if (restart_evidence) {
		if (rh_report_appendf(report, "%d", log->minor_version))
			return -1;
	} else if (RH_APPEND_LITERAL(report, "null"))
		return -1;
#define RH_NATIVE_LSN(name, value) \
	do { \
		if (RH_APPEND_LITERAL(report, ",\"" name "\":")) \
			return -1; \
		if (restart_evidence) { \
			if (rh_report_appendf(report, "%"PRIu64, (uint64_t)(value))) \
				return -1; \
		} else if (RH_APPEND_LITERAL(report, "null")) \
			return -1; \
	} while (0)
	RH_NATIVE_LSN("restart_lsn", log->restart_lsn);
	RH_NATIVE_LSN("synced_lsn", log->synced_lsn);
	RH_NATIVE_LSN("committed_lsn", log->committed_lsn);
	RH_NATIVE_LSN("latest_lsn", log->latest_lsn);
#undef RH_NATIVE_LSN
	return rh_report_appendf(report,
		",\"checkpoint_records_examined\":%u,"
		"\"control_records_examined\":%u,\"mutation_records_examined\":%u,"
		"\"open_attribute_tables\":%u,\"attribute_name_tables\":%u,"
		"\"dirty_page_tables\":%u,\"transaction_tables\":%u,"
		"\"actions_seen\":%u,\"redo_actions\":%u,\"undo_actions\":%u,"
		"\"restart_pages_planned\":%u,\"unsupported_actions\":%u,"
		"\"io_errors\":%u,\"parse_errors\":%u,"
		"\"planned_io_operations\":%zu,\"planned_io_bytes\":%"PRIu64"}",
		checked ? log->checkpoint_records_examined : 0,
		checked ? log->control_records_examined : 0,
		checked ? log->mutation_records_examined : 0,
		checked ? log->open_attribute_tables : 0,
		checked ? log->attribute_name_tables : 0,
		checked ? log->dirty_page_tables : 0,
		checked ? log->transaction_tables : 0,
		checked ? log->actions_seen : 0,
		checked ? log->redo_actions : 0,
		checked ? log->undo_actions : 0,
		checked ? log->restart_pages_planned : 0,
		checked ? log->unsupported_actions : 0,
		checked ? log->io_errors : 0,
		checked ? log->parse_errors : 0,
		checked && !scan->native_refused ?
			log->planned_io_operations : 0,
		checked && !scan->native_refused ?
			(uint64_t)log->planned_io_bytes : 0);
}

static const char *rh_wal_state(int state)
{
	switch (state) {
	case RH_WAL_EMPTY: return "EMPTY";
	case RH_WAL_PREPARING: return "PREPARING";
	case RH_WAL_APPLYING: return "APPLYING";
	case RH_WAL_COMMITTED: return "COMMITTED";
	case RH_WAL_ROLLBACK: return "ROLLBACK";
	default: return NULL;
	}
}

static const char *rh_wal_tx(int state)
{
	switch (state) {
	case RH_WAL_TX_NONE: return "NONE";
	case RH_WAL_TX_METADATA_REPAIR: return "METADATA_REPAIR";
	case RH_WAL_TX_DIRTY_CLEAR: return "DIRTY_CLEAR";
	default: return NULL;
	}
}

static const char *rh_wal_trace_name(enum rh_wal_trace_kind kind)
{
	switch (kind) {
	case RH_WAL_TRACE_UNDO_PAYLOAD: return "undo-payload-append";
	case RH_WAL_TRACE_DESCRIPTOR: return "descriptor-append";
	case RH_WAL_TRACE_STATE: return "state-transition";
	case RH_WAL_TRACE_SUPERBLOCK_RECONSTRUCT:
		return "superblock-reconstruct";
	case RH_WAL_TRACE_ROLLBACK_RESTORE: return "rollback-restore";
	default: return NULL;
	}
}

static int rh_wal_trace_hash(const struct rh_repair_evidence *repair,
		char output[65])
{
	struct rh_hash_stream hash;
	unsigned char header[16], values[32], uuid[16], digest[32];
	size_t i;

	rh_hash_stream_init(&hash);
	rh_put_le32_report(header, 3U);
	rh_put_le64_report(header + 4U, repair->wal_action_count);
	if (rh_hash_stream_update(&hash, "RHWAL3\0\0", 8U) ||
			rh_hash_stream_update(&hash, header, 12U))
		return -1;
	for (i = 0; i < repair->wal_action_count; i++) {
		const struct rh_wal_action_evidence *action = &repair->wal_actions[i];
		int superblock = action->kind == RH_WAL_TRACE_SUPERBLOCK_RECONSTRUCT;
		unsigned int from = action->kind == RH_WAL_TRACE_STATE ?
			(unsigned int)action->from_state + 1U : 0U;
		unsigned int to = action->kind == RH_WAL_TRACE_STATE ?
			(unsigned int)action->to_state + 1U : 0U;
		unsigned int slot = action->kind == RH_WAL_TRACE_STATE || superblock ?
			(unsigned int)action->slot + 1U : 0U;

		if (!rh_wal_trace_name(action->kind) ||
				(!superblock && rh_uuid_parse(action->transaction_uuid, uuid)))
			return -1;
		rh_put_le64_report(header, i);
		header[8] = (unsigned char)action->kind;
		header[9] = (unsigned char)from;
		header[10] = (unsigned char)to;
		header[11] = (unsigned char)slot;
		rh_put_le32_report(header + 12U, 3U);
		if (rh_hash_stream_update(&hash, header, sizeof(header)))
			return -1;
		rh_put_le64_report(values, superblock ? UINT64_MAX :
			action->transaction_ordinal);
		if (rh_hash_stream_update(&hash, values, 8U) ||
				rh_hash_stream_update(&hash, superblock ?
					(unsigned char[16]){0} : uuid, 16U))
			return -1;
		rh_put_le64_report(values, action->extent_offset);
		rh_put_le64_report(values + 8U, action->length);
		rh_put_le64_report(values + 16U, action->sync_ordinal);
		rh_put_le64_report(values + 24U, action->write_boundaries);
		if (rh_hash_stream_update(&hash, values, sizeof(values)) ||
				rh_decode_hex_report(action->before_hash, digest) ||
				rh_hash_stream_update(&hash, digest, 32U) ||
				rh_decode_hex_report(action->after_hash, digest) ||
				rh_hash_stream_update(&hash, digest, 32U))
			return -1;
	}
	if (rh_hash_stream_final(&hash, digest))
		return -1;
	rh_hex_report(digest, sizeof(digest), output);
	return 0;
}

static int rh_wal_kind_map(struct rh_report *report,
		const uint64_t values[5])
{
	size_t i;
	int first = 1;

	if (RH_APPEND_LITERAL(report, "{"))
		return -1;
	for (i = 0; i < 5U; i++) {
		const char *name;
		if (!values[i])
			continue;
		name = rh_wal_trace_name((enum rh_wal_trace_kind)(i + 1U));
		if (!name || rh_report_appendf(report, "%s", first ? "" : ",") ||
				rh_report_json_string(report, name) ||
				rh_report_appendf(report, ":%"PRIu64, values[i]))
			return -1;
		first = 0;
	}
	return RH_APPEND_LITERAL(report, "}");
}

static int rh_wal_trace_tail(struct rh_report *report,
		const struct rh_repair_evidence *repair)
{
	uint64_t count[5] = {0}, bytes[5] = {0}, syncs[5] = {0}, bounds[5] = {0};
	char ledger_hash[65];
	size_t i;
	int emitted = 0;

	if (rh_wal_trace_hash(repair, ledger_hash))
		return -1;
	for (i = 0; i < repair->wal_action_count; i++) {
		size_t kind = (size_t)repair->wal_actions[i].kind - 1U;
		if (kind >= 5U)
			return -1;
		count[kind]++;
		bytes[kind] += repair->wal_actions[i].length;
		syncs[kind]++;
		bounds[kind] += repair->wal_actions[i].write_boundaries;
	}
	if (rh_report_appendf(report,
			",\"write_boundaries\":%"PRIu64",\"action_ledger\":{"
			"\"format\":\"RHWAL3\",\"entry_count\":%zu,"
			"\"ledger_hash\":\"%s\",\"total_bytes\":%"PRIu64
			",\"syncs\":%"PRIu64",\"write_boundaries\":%"PRIu64
			",\"by_kind\":" , repair->wal_write_boundaries,
			repair->wal_action_count, ledger_hash, repair->wal_bytes,
			repair->wal_syncs, repair->wal_write_boundaries) ||
			rh_wal_kind_map(report, count) ||
			RH_APPEND_LITERAL(report, ",\"bytes_by_kind\":") ||
			rh_wal_kind_map(report, bytes) ||
			RH_APPEND_LITERAL(report, ",\"syncs_by_kind\":") ||
			rh_wal_kind_map(report, syncs) ||
			RH_APPEND_LITERAL(report, ",\"boundaries_by_kind\":") ||
			rh_wal_kind_map(report, bounds) ||
			RH_APPEND_LITERAL(report, ",\"first_kind\":") ||
			rh_report_json_string(report,
				rh_wal_trace_name(repair->wal_actions[0].kind)) ||
			RH_APPEND_LITERAL(report, ",\"last_kind\":") ||
			rh_report_json_string(report, rh_wal_trace_name(
				repair->wal_actions[repair->wal_action_count - 1U].kind)) ||
			RH_APPEND_LITERAL(report, ",\"error_count\":0},\"actions\":["))
		return -1;
	for (i = 0; i < repair->wal_action_count; i++) {
		const struct rh_wal_action_evidence *action = &repair->wal_actions[i];
		const char *name = rh_wal_trace_name(action->kind);
		const char *from = action->kind == RH_WAL_TRACE_STATE ?
			rh_wal_state(action->from_state) : NULL;
		const char *to = action->kind == RH_WAL_TRACE_STATE ?
			rh_wal_state(action->to_state) : NULL;
		int first = i < 32U;
		int last = i + 32U >= repair->wal_action_count;
		int superblock = action->kind == RH_WAL_TRACE_SUPERBLOCK_RECONSTRUCT;

		if (!first && !last)
			continue;
		if (rh_report_appendf(report,
					"%s{\"ordinal\":%zu,\"kind\":\"%s\","
					"\"extent_offset\":%"PRIu64",\"length\":%"PRIu64
					",\"slot\":",
					emitted++ ? "," : "", i, name, action->extent_offset,
					action->length))
			return -1;
		if (action->kind == RH_WAL_TRACE_STATE || superblock) {
			if (rh_report_appendf(report, "%d", action->slot))
				return -1;
		} else if (RH_APPEND_LITERAL(report, "null"))
			return -1;
		if (RH_APPEND_LITERAL(report, ",\"transaction_ordinal\":"))
			return -1;
		if (!superblock) {
			if (rh_report_appendf(report, "%"PRIu64,
					action->transaction_ordinal))
				return -1;
		} else if (RH_APPEND_LITERAL(report, "null"))
			return -1;
		if (RH_APPEND_LITERAL(report, ",\"transaction_uuid\":"))
			return -1;
		if (!superblock) {
			if (rh_report_json_string(report, action->transaction_uuid))
				return -1;
		} else if (RH_APPEND_LITERAL(report, "null"))
			return -1;
		if (RH_APPEND_LITERAL(report, ",\"from_state\":"))
			return -1;
		if (from) {
			if (rh_report_json_string(report, from))
				return -1;
		} else if (RH_APPEND_LITERAL(report, "null"))
			return -1;
		if (RH_APPEND_LITERAL(report, ",\"to_state\":"))
			return -1;
		if (to) {
			if (rh_report_json_string(report, to))
				return -1;
		} else if (RH_APPEND_LITERAL(report, "null"))
			return -1;
		if (rh_report_appendf(report,
					",\"before_hash\":\"%s\",\"after_hash\":\"%s\","
					"\"sync_ordinal\":%"PRIu64",\"sync_completed\":true,"
					"\"readback_verified\":true,\"write_boundaries\":%"PRIu64
					",\"sample_reasons\":[%s%s%s]}",
					action->before_hash, action->after_hash,
					action->sync_ordinal, action->write_boundaries,
					first ? "\"FIRST\"" : "", first && last ? "," : "",
					last ? "\"LAST\"" : ""))
			return -1;
	}
	return RH_APPEND_LITERAL(report, "]}");
}

static int rh_wal(struct rh_report *report,
		const struct rh_scan_evidence *scan,
		const struct rh_repair_evidence *repair)
{
	const struct rh_wal_observation *wal = &scan->wal;
	const char *state = rh_wal_state(wal->state);
	const char *transaction = rh_wal_tx(wal->transaction_kind);
	size_t i;
	int recovered = 0;

	for (i = 0; i < repair->transaction_count; i++)
		if (repair->transactions[i].origin != RH_REPAIR_ORIGIN_NEW)
			recovered = 1;

	if (rh_report_appendf(report,
			"{\"checked\":%s,\"present\":",
			wal->checked ? "true" : "false") ||
			rh_bool_or_null(report, wal->present >= 0, wal->present) ||
			RH_APPEND_LITERAL(report, ",\"valid\":") ||
			rh_bool_or_null(report, wal->valid >= 0, wal->valid) ||
			RH_APPEND_LITERAL(report, ",\"state\":"))
		return -1;
	if (state) {
		if (rh_report_json_string(report, state))
			return -1;
	} else if (RH_APPEND_LITERAL(report, "null"))
		return -1;
	if (RH_APPEND_LITERAL(report, ",\"generation\":"))
		return -1;
	if (wal->valid == 1) {
		if (rh_report_appendf(report, "%"PRIu64, wal->generation))
			return -1;
	} else if (RH_APPEND_LITERAL(report, "null"))
		return -1;
	if (RH_APPEND_LITERAL(report, ",\"recovery_required\":") ||
			rh_bool_or_null(report, wal->recovery_required >= 0,
				wal->recovery_required) ||
			rh_report_appendf(report, ",\"recovered\":%s,\"journal_uuid\":",
				recovered ? "true" : "false"))
		return -1;
	if (wal->valid == 1 && wal->journal_uuid[0]) {
		if (rh_report_json_string(report, wal->journal_uuid))
			return -1;
	} else if (RH_APPEND_LITERAL(report, "null"))
		return -1;
	if (RH_APPEND_LITERAL(report, ",\"volume_serial\":"))
		return -1;
	if (wal->valid == 1) {
		if (rh_report_appendf(report, "\"0x%016"PRIx64"\"",
				wal->volume_serial))
			return -1;
	} else if (RH_APPEND_LITERAL(report, "null"))
		return -1;
	if (RH_APPEND_LITERAL(report, ",\"transaction_kind\":"))
		return -1;
	if (transaction) {
		if (rh_report_json_string(report, transaction))
			return -1;
	} else if (RH_APPEND_LITERAL(report, "null"))
		return -1;
	if (RH_APPEND_LITERAL(report, ",\"max_entry_count\":"))
		return -1;
	if (wal->max_entry_count >= 0) {
		if (rh_report_appendf(report, "%d", wal->max_entry_count))
			return -1;
	} else if (RH_APPEND_LITERAL(report, "null"))
		return -1;
	if (RH_APPEND_LITERAL(report, ",\"fast_path_trusted\":") ||
			rh_bool_or_null(report, wal->checked, wal->fast_path_trusted) ||
			RH_APPEND_LITERAL(report, ",\"fallback_attempted\":") ||
			rh_bool_or_null(report, wal->checked, 0) ||
			RH_APPEND_LITERAL(report, ",\"fallback_ambiguous\":") ||
			rh_bool_or_null(report, wal->checked, 0) ||
			RH_APPEND_LITERAL(report, ",\"unreadable_record_count\":"))
		return -1;
	if (wal->checked) {
		if (rh_report_appendf(report, "%"PRIu64,
				wal->unreadable_record_count))
			return -1;
	} else if (RH_APPEND_LITERAL(report, "null"))
		return -1;
	if (RH_APPEND_LITERAL(report, ",\"definite_duplicate_count\":"))
		return -1;
	if (wal->checked) {
		if (rh_report_appendf(report, "%"PRIu64,
				wal->definite_duplicate_count))
			return -1;
	} else if (RH_APPEND_LITERAL(report, "null"))
		return -1;
	if (repair->wal_action_count)
		return rh_wal_trace_tail(report, repair);
	return rh_report_appendf(report,
		",\"write_boundaries\":0,\"action_ledger\":{"
		"\"format\":\"RHWAL3\",\"entry_count\":0,\"ledger_hash\":\"%s\","
		"\"total_bytes\":0,\"syncs\":0,\"write_boundaries\":0,"
		"\"by_kind\":{},\"bytes_by_kind\":{},\"syncs_by_kind\":{},"
		"\"boundaries_by_kind\":{},\"first_kind\":null,\"last_kind\":null,"
		"\"error_count\":0},\"actions\":[]}", rh_empty_wal_hash);
}

static void rh_maps(const struct rh_foundation_evidence *foundation,
		uint64_t count[RH_WRITE_KIND_COUNT],
		uint64_t bytes[RH_WRITE_KIND_COUNT])
{
	size_t i;
	memset(count, 0, sizeof(uint64_t) * RH_WRITE_KIND_COUNT);
	memset(bytes, 0, sizeof(uint64_t) * RH_WRITE_KIND_COUNT);
	for (i = 0; i < foundation->count; i++) {
		enum rh_write_kind kind = foundation->actions[i].kind;
		count[kind]++;
		bytes[kind] += foundation->actions[i].length;
	}
}

static void rh_all_maps(const struct rh_foundation_evidence *foundation,
		const struct rh_repair_evidence *repair,
		uint64_t count[RH_WRITE_KIND_COUNT],
		uint64_t bytes[RH_WRITE_KIND_COUNT])
{
	size_t i, j;

	rh_maps(foundation, count, bytes);
	for (i = 0; i < repair->transaction_count; i++)
		if (repair->transactions[i].origin == RH_REPAIR_ORIGIN_NEW)
		for (j = 0; j < repair->transactions[i].action_count; j++) {
			const struct rh_repair_action_evidence *action =
				&repair->transactions[i].actions[j];

			count[action->kind]++;
			bytes[action->kind] += action->length;
		}
}

static void rh_transaction_maps(
		const struct rh_repair_transaction_evidence *transaction,
		uint64_t count[RH_WRITE_KIND_COUNT],
		uint64_t bytes[RH_WRITE_KIND_COUNT])
{
	size_t i;

	memset(count, 0, sizeof(uint64_t) * RH_WRITE_KIND_COUNT);
	memset(bytes, 0, sizeof(uint64_t) * RH_WRITE_KIND_COUNT);
	for (i = 0; i < transaction->action_count; i++) {
		const struct rh_repair_action_evidence *action =
			&transaction->actions[i];

		count[action->kind]++;
		bytes[action->kind] += action->length;
	}
}

static int rh_id_map(struct rh_report *report,
		const uint64_t values[RH_WRITE_KIND_COUNT])
{
	size_t i;
	int first = 1;
	if (RH_APPEND_LITERAL(report, "{"))
		return -1;
	for (i = 0; i < RH_WRITE_KIND_COUNT; i++) {
		if (!values[i])
			continue;
		if (rh_report_appendf(report, "%s\"%zu\":%"PRIu64,
				first ? "" : ",", i + 1, values[i]))
			return -1;
		first = 0;
	}
	return RH_APPEND_LITERAL(report, "}");
}

static int rh_kind_map(struct rh_report *report,
		const uint64_t values[RH_WRITE_KIND_COUNT])
{
	size_t i;
	int first = 1;
	if (RH_APPEND_LITERAL(report, "{"))
		return -1;
	for (i = 0; i < RH_WRITE_KIND_COUNT; i++) {
		if (!values[i])
			continue;
		if (rh_report_appendf(report, "%s", first ? "" : ",") ||
				rh_report_json_string(report,
					rh_write_kind_name((enum rh_write_kind)i)) ||
				rh_report_appendf(report, ":%"PRIu64, values[i]))
			return -1;
		first = 0;
	}
	return RH_APPEND_LITERAL(report, "}");
}

static int rh_foundation(struct rh_report *report,
		const struct rh_foundation_evidence *foundation)
{
	size_t i;
	if (RH_APPEND_LITERAL(report, "["))
		return -1;
	for (i = 0; i < foundation->count; i++) {
		const struct rh_foundation_action *action = &foundation->actions[i];
		if (rh_report_appendf(report,
				"%s{\"ordinal\":%"PRIu64",\"action_id\":%u,\"kind\":",
				i ? "," : "", action->ordinal, action->action_id) ||
				rh_report_json_string(report,
					rh_write_kind_name(action->kind)) ||
				RH_APPEND_LITERAL(report, ",\"target\":") ||
				rh_report_json_string(report, action->target) ||
				rh_report_appendf(report,
					",\"offset\":%"PRIu64",\"length\":%"PRIu64
					",\"before_hash\":\"%s\",\"after_hash\":\"%s\","
					"\"verified\":true,\"write_boundaries\":%"PRIu64
					",\"sync_ordinal\":%"PRIu64",\"sync_completed\":true,"
					"\"readback_verified\":true,\"authority\":{"
					"\"source_peer\":",
					action->offset, action->length, action->before_hash,
					action->after_hash, action->write_boundaries,
					action->sync_ordinal) ||
				rh_report_json_string(report, action->source_peer) ||
				RH_APPEND_LITERAL(report, ",\"target_peer\":") ||
				rh_report_json_string(report, action->target_peer) ||
				RH_APPEND_LITERAL(report, ",\"source_strict_valid\":true,"
					"\"source_expected_bound\":true,"
					"\"target_status\":\"READABLE_STRUCTURALLY_INVALID\","
					"\"sole_valid_peer\":true,"
					"\"conflicting_valid_peer\":false}}"))
			return -1;
	}
	return RH_APPEND_LITERAL(report, "]");
}

static int rh_plan(struct rh_report *report,
		const struct rh_foundation_evidence *foundation,
		const struct rh_repair_evidence *repair)
{
	uint64_t count[RH_WRITE_KIND_COUNT], bytes[RH_WRITE_KIND_COUNT];
	rh_all_maps(foundation, repair, count, bytes);
	if (rh_report_appendf(report,
			"{\"operations\":%zu,\"bytes\":%"PRIu64
			",\"priority_operations\":0,\"foundation_operations\":%zu,"
			"\"foundation_bytes\":%"PRIu64
			",\"wal_operations\":%zu,\"wal_bytes\":%"PRIu64
			",\"by_action_id\":",
			foundation->count + repair->action_count,
			foundation->bytes + repair->target_bytes,
			foundation->count, foundation->bytes,
			repair->action_count, repair->target_bytes) ||
			rh_id_map(report, count) ||
			RH_APPEND_LITERAL(report, ",\"by_kind\":") ||
			rh_kind_map(report, count) ||
			RH_APPEND_LITERAL(report, ",\"bytes_by_action_id\":") ||
			rh_id_map(report, bytes) ||
			RH_APPEND_LITERAL(report, ",\"bytes_by_kind\":") ||
			rh_kind_map(report, bytes) ||
			RH_APPEND_LITERAL(report, "}"))
		return -1;
	return 0;
}

static int rh_batch_ledger(struct rh_report *report,
		const struct rh_foundation_evidence *foundation)
{
	uint64_t count[RH_WRITE_KIND_COUNT], bytes[RH_WRITE_KIND_COUNT];
	int present = foundation->count != 0;
	rh_maps(foundation, count, bytes);
	/*
	 * Foundation samples are complete and bounded (maximum four).  The full
	 * RHTXN3 streaming hash is emitted by the later batch engine; this slice
	 * uses the frozen empty vector when no physical phase exists and binds a
	 * foundation phase to its canonical repair-ledger hash otherwise.
	 */
	if (rh_report_appendf(report,
			"{\"format\":\"RHTXN3\",\"record_count\":%d,\"ledger_hash\":\"%s\","
			"\"foundation_count\":%d,\"new_count\":0,"
			"\"recovered_committed_count\":0,"
			"\"recovered_rolled_back_count\":0,\"metadata_count\":0,"
			"\"dirty_clear_count\":0,\"accepted_count\":%d,"
			"\"refused_count\":0,\"rolled_back_count\":0,\"priority_count\":0,"
			"\"rescan_count\":%d,\"commit_started_count\":%d,"
			"\"commit_completed_count\":%d,\"verified_entries\":%zu,"
			"\"rollback_restored_entries\":0,\"rollback_restored_bytes\":0,"
			"\"rollback_syncs\":0,\"rollback_write_boundaries\":0,"
			"\"entry_count\":%zu,\"target_bytes\":%"PRIu64
			",\"syncs\":%"PRIu64",\"write_boundaries\":%"PRIu64
			",\"by_action_id\":",
			present, present ? foundation->repair_ledger_hash :
				rh_empty_batch_hash,
			present, present, present, present, present,
			foundation->count, foundation->count, foundation->bytes,
			foundation->syncs, foundation->write_boundaries) ||
			rh_id_map(report, count) ||
			RH_APPEND_LITERAL(report, ",\"by_kind\":") ||
			rh_kind_map(report, count) ||
			RH_APPEND_LITERAL(report, ",\"bytes_by_action_id\":") ||
			rh_id_map(report, bytes) ||
			RH_APPEND_LITERAL(report, ",\"bytes_by_kind\":") ||
			rh_kind_map(report, bytes) ||
			rh_report_appendf(report,
				",\"dirty_set_action_count\":0,"
				"\"dirty_set_phase_ordinal\":null,"
				"\"dirty_clear_action_count\":0,"
				"\"dirty_clear_phase_ordinal\":null,"
				"\"native_redo_count\":0,\"native_restart_count\":0,"
				"\"native_phase_ordinal\":null,"
				"\"first_metadata_ordinal\":null,\"first_phase\":%s,"
				"\"last_phase\":%s,\"final_rescan_digest\":null,"
				"\"final_coverage_ledger_hash\":null,"
				"\"final_diagnosis_hash\":null}",
				present ? "\"FOUNDATION\"" : "null",
				present ? "\"FOUNDATION\"" : "null"))
		return -1;
	return 0;
}

static int rh_decode_hex_report(const char text[65], unsigned char output[32])
{
	size_t i;

	for (i = 0; i < 32U; i++) {
		unsigned int high, low;
		char a = text[2U * i], b = text[2U * i + 1U];

		high = a >= '0' && a <= '9' ? (unsigned int)(a - '0') :
			a >= 'a' && a <= 'f' ? (unsigned int)(a - 'a' + 10) : 16U;
		low = b >= '0' && b <= '9' ? (unsigned int)(b - '0') :
			b >= 'a' && b <= 'f' ? (unsigned int)(b - 'a' + 10) : 16U;
		if (high > 15U || low > 15U)
			return -1;
		output[i] = (unsigned char)((high << 4) | low);
	}
	return text[64] ? -1 : 0;
}

static int rh_batch_hash(struct rh_report *report,
		const struct rh_repair_evidence *repair,
		char rescan_hash[RH_REPAIR_TRANSACTION_MAX][65],
		char diagnosis_hash[RH_REPAIR_TRANSACTION_MAX][65],
		char output[65])
{
	struct rh_hash_stream hash;
	unsigned char header[16], values[72], bytes32[32], uuid[16], digest[32];
	uint64_t count[RH_WRITE_KIND_COUNT], action_bytes[RH_WRITE_KIND_COUNT];
	size_t i, j;

	rh_hash_stream_init(&hash);
	rh_put_le32_report(header, 3U);
	rh_put_le64_report(header + 4U, repair->transaction_count);
	if (rh_hash_stream_update(&hash, "RHTXN3\0\0", 8U) ||
			rh_hash_stream_update(&hash, header, 12U))
		return -1;
	for (i = 0; i < repair->transaction_count; i++) {
		const struct rh_repair_transaction_evidence *transaction =
			&repair->transactions[i];
		const char *stage = transaction->kind == RH_WAL_TX_DIRTY_CLEAR ?
			"FINAL" : "POST_METADATA";
		unsigned int phase = transaction->kind == RH_WAL_TX_DIRTY_CLEAR ? 3U : 2U;
		unsigned int origin = transaction->origin == RH_REPAIR_ORIGIN_NEW ? 2U :
			transaction->origin == RH_REPAIR_ORIGIN_RECOVERED_COMMITTED ? 3U : 4U;
		unsigned int result = transaction->rolled_back ? 3U : 1U;
		unsigned int flags = (transaction->commit_started ? 1U : 0U) |
			(transaction->commit_completed ? 2U : 0U) | 4U |
			(transaction->rolled_back ? 24U : 0U);

		if (!transaction->post_scan_available)
			return -1;
		if (rh_snapshot_hash(report, &transaction->post_scan, i,
				"TRANSACTION", transaction->transaction_uuid,
				transaction->plan_hash, stage, rescan_hash[i]) ||
				rh_diagnosis_hash(report, &transaction->post_scan,
					diagnosis_hash[i]) ||
				rh_uuid_parse(transaction->transaction_uuid, uuid) ||
				rh_decode_hex_report(transaction->plan_hash, bytes32))
			return -1;
		rh_put_le64_report(header, i);
		header[8] = (unsigned char)phase;
		header[9] = (unsigned char)origin;
		header[10] = (unsigned char)result;
		header[11] = (unsigned char)flags;
		memset(header + 12U, 0, 4U);
		if (rh_hash_stream_update(&hash, header, sizeof(header)) ||
				rh_hash_stream_update(&hash, uuid, sizeof(uuid)) ||
				rh_hash_stream_update(&hash, bytes32, sizeof(bytes32)) ||
				rh_decode_hex_report(transaction->repair_ledger_hash, bytes32) ||
				rh_hash_stream_update(&hash, bytes32, sizeof(bytes32)))
			return -1;
		rh_put_le64_report(values, transaction->action_count);
		rh_put_le64_report(values + 8U, transaction->target_bytes);
		rh_put_le64_report(values + 16U, transaction->last_verified_ordinal);
		rh_put_le64_report(values + 24U, transaction->syncs);
		rh_put_le64_report(values + 32U, transaction->write_boundaries);
		rh_put_le64_report(values + 40U,
			transaction->rollback_restored_entries);
		rh_put_le64_report(values + 48U,
			transaction->rollback_restored_bytes);
		rh_put_le64_report(values + 56U, transaction->rollback_syncs);
		rh_put_le64_report(values + 64U,
			transaction->rollback_write_boundaries);
		if (rh_hash_stream_update(&hash, values, sizeof(values)))
			return -1;
		rh_transaction_maps(transaction, count, action_bytes);
		for (j = 0; j < RH_WRITE_KIND_COUNT; j++) {
			rh_put_le64_report(values, count[j]);
			if (rh_hash_stream_update(&hash, values, 8U))
				return -1;
		}
		for (j = 0; j < RH_WRITE_KIND_COUNT; j++) {
			rh_put_le64_report(values, action_bytes[j]);
			if (rh_hash_stream_update(&hash, values, 8U))
				return -1;
		}
		if (rh_decode_hex_report(rescan_hash[i], bytes32) ||
				rh_hash_stream_update(&hash, bytes32, 32U) ||
				rh_hash_stream_update(&hash,
					transaction->post_scan.census.coverage_hash, 32U) ||
				rh_decode_hex_report(diagnosis_hash[i], bytes32) ||
				rh_hash_stream_update(&hash, bytes32, 32U))
			return -1;
	}
	if (rh_hash_stream_final(&hash, digest))
		return -1;
	rh_hex_report(digest, sizeof(digest), output);
	return 0;
}

static int rh_repair_action_samples(struct rh_report *report,
		const struct rh_repair_evidence *repair)
{
	size_t i, j, ordinal = 0;

	if (RH_APPEND_LITERAL(report, "["))
		return -1;
	for (i = 0; i < repair->transaction_count; i++)
		if (repair->transactions[i].origin == RH_REPAIR_ORIGIN_NEW)
		for (j = 0; j < repair->transactions[i].action_count; j++, ordinal++) {
			const struct rh_repair_action_evidence *action =
				&repair->transactions[i].actions[j];
			int first = ordinal < 32U;
			int last = ordinal + 32U >= repair->action_count;

			if (!first && !last)
				continue;
			if (rh_report_appendf(report,
					"%s{\"action_id\":%u,\"after_hash\":\"%s\","
					"\"before_hash\":\"%s\",\"kind\":",
					report->buffer[report->used - 1U] == '[' ? "" : ",",
					action->action_id, action->after_hash,
					action->before_hash) ||
					rh_report_json_string(report, rh_write_kind_name(action->kind)) ||
					rh_report_appendf(report,
						",\"length\":%"PRIu64",\"offset\":%"PRIu64
						",\"ordinal\":%zu,\"sample_reasons\":[%s%s%s],"
						"\"target\":",
						action->length, action->offset, ordinal,
						first ? "\"FIRST\"" : "",
						first && last ? "," : "",
						last ? "\"LAST\"" : "") ||
					rh_report_json_string(report, rh_write_kind_name(action->kind)) ||
					rh_report_appendf(report,
						",\"verified\":true,\"write_boundaries\":%"PRIu64"}",
						action->write_boundaries))
				return -1;
		}
	return RH_APPEND_LITERAL(report, "]");
}

static int rh_repair_batches(struct rh_report *report,
		const struct rh_repair_evidence *repair)
{
	char rescan_hash[RH_REPAIR_TRANSACTION_MAX][65] = {{0}};
	char diagnosis_hash[RH_REPAIR_TRANSACTION_MAX][65] = {{0}};
	char ledger_hash[65], coverage_hash[65];
	uint64_t count[RH_WRITE_KIND_COUNT], bytes[RH_WRITE_KIND_COUNT];
	uint64_t metadata_count = 0, dirty_clear_count = 0;
	uint64_t dirty_set_actions = 0, dirty_clear_actions = 0;
	uint64_t new_count = 0, recovered_committed = 0, recovered_rolled_back = 0;
	uint64_t accepted_count = 0, rolled_back_count = 0;
	uint64_t commit_started_count = 0, commit_completed_count = 0;
	uint64_t verified_entries = 0, entry_count = 0, target_bytes = 0;
	uint64_t syncs = 0, write_boundaries = 0;
	uint64_t rollback_entries = 0, rollback_bytes = 0;
	uint64_t rollback_syncs = 0, rollback_boundaries = 0;
	size_t first_metadata = SIZE_MAX, dirty_set_phase = SIZE_MAX;
	size_t native_phase = SIZE_MAX, i;

	if (!repair->transaction_count)
		return -1;
	memset(count, 0, sizeof(count));
	memset(bytes, 0, sizeof(bytes));
	for (i = 0; i < repair->transaction_count; i++) {
		uint64_t local_count[RH_WRITE_KIND_COUNT];
		uint64_t local_bytes[RH_WRITE_KIND_COUNT];
		size_t j;

		rh_transaction_maps(&repair->transactions[i], local_count, local_bytes);
		for (j = 0; j < RH_WRITE_KIND_COUNT; j++) {
			count[j] += local_count[j];
			bytes[j] += local_bytes[j];
		}
		if (repair->transactions[i].origin == RH_REPAIR_ORIGIN_NEW)
			new_count++;
		else if (repair->transactions[i].origin ==
				RH_REPAIR_ORIGIN_RECOVERED_COMMITTED)
			recovered_committed++;
		else if (repair->transactions[i].origin ==
				RH_REPAIR_ORIGIN_RECOVERED_ROLLED_BACK)
			recovered_rolled_back++;
		else
			return -1;
		if (repair->transactions[i].rolled_back)
			rolled_back_count++;
		else if (repair->transactions[i].accepted)
			accepted_count++;
		else
			return -1;
		commit_started_count += repair->transactions[i].commit_started != 0;
		commit_completed_count += repair->transactions[i].commit_completed != 0;
		verified_entries += repair->transactions[i].last_verified_ordinal;
		entry_count += repair->transactions[i].action_count;
		target_bytes += repair->transactions[i].target_bytes;
		syncs += repair->transactions[i].syncs;
		write_boundaries += repair->transactions[i].write_boundaries;
		rollback_entries += repair->transactions[i].rollback_restored_entries;
		rollback_bytes += repair->transactions[i].rollback_restored_bytes;
		rollback_syncs += repair->transactions[i].rollback_syncs;
		rollback_boundaries +=
			repair->transactions[i].rollback_write_boundaries;
		if (repair->transactions[i].kind == RH_WAL_TX_METADATA_REPAIR) {
			if (first_metadata == SIZE_MAX)
				first_metadata = i;
			if (native_phase == SIZE_MAX &&
					(local_count[RH_WRITE_LOGFILE_REDO] ||
					 local_count[RH_WRITE_LOGFILE_RESTART]))
				native_phase = i;
			if (local_count[RH_WRITE_VOLUME_DIRTY_SET])
				dirty_set_phase = i;
			metadata_count++;
		} else if (repair->transactions[i].kind == RH_WAL_TX_DIRTY_CLEAR) {
			dirty_clear_count++;
		} else
			return -1;
	}
	dirty_set_actions = count[RH_WRITE_VOLUME_DIRTY_SET];
	dirty_clear_actions = count[RH_WRITE_VOLUME_DIRTY_CLEAR];
	if (rh_batch_hash(report, repair, rescan_hash, diagnosis_hash, ledger_hash))
		return -1;
	rh_hex_report(repair->transactions[repair->transaction_count - 1U]
		.post_scan.census.coverage_hash, 32U, coverage_hash);
	if (rh_report_appendf(report,
			"{\"format\":\"RHTXN3\",\"record_count\":%zu,"
			"\"ledger_hash\":\"%s\",\"foundation_count\":0,"
			"\"new_count\":%"PRIu64",\"recovered_committed_count\":%"PRIu64","
			"\"recovered_rolled_back_count\":%"PRIu64",\"metadata_count\":%"PRIu64
			",\"dirty_clear_count\":%"PRIu64",\"accepted_count\":%"PRIu64","
			"\"refused_count\":0,\"rolled_back_count\":%"PRIu64","
			"\"priority_count\":%"PRIu64",\"rescan_count\":%zu,"
			"\"commit_started_count\":%"PRIu64",\"commit_completed_count\":%"PRIu64","
			"\"verified_entries\":%"PRIu64",\"rollback_restored_entries\":%"PRIu64","
			"\"rollback_restored_bytes\":%"PRIu64",\"rollback_syncs\":%"PRIu64","
			"\"rollback_write_boundaries\":%"PRIu64",\"entry_count\":%"PRIu64","
			"\"target_bytes\":%"PRIu64",\"syncs\":%"PRIu64
			",\"write_boundaries\":%"PRIu64",\"by_action_id\":" ,
			repair->transaction_count, ledger_hash, new_count,
			recovered_committed, recovered_rolled_back, metadata_count,
			dirty_clear_count, accepted_count, rolled_back_count,
			rolled_back_count, repair->transaction_count, commit_started_count,
			commit_completed_count, verified_entries, rollback_entries,
			rollback_bytes, rollback_syncs, rollback_boundaries, entry_count,
			target_bytes, syncs, write_boundaries) ||
			rh_id_map(report, count) ||
			RH_APPEND_LITERAL(report, ",\"by_kind\":") ||
			rh_kind_map(report, count) ||
			RH_APPEND_LITERAL(report, ",\"bytes_by_action_id\":") ||
			rh_id_map(report, bytes) ||
			RH_APPEND_LITERAL(report, ",\"bytes_by_kind\":") ||
			rh_kind_map(report, bytes) ||
			rh_report_appendf(report,
				",\"dirty_set_action_count\":%"PRIu64
				",\"dirty_set_phase_ordinal\":",
				dirty_set_actions))
		return -1;
	if (dirty_set_actions) {
		if (dirty_set_phase == SIZE_MAX ||
				rh_report_appendf(report, "%zu", dirty_set_phase))
			return -1;
	} else if (RH_APPEND_LITERAL(report, "null"))
		return -1;
	if (rh_report_appendf(report,
			",\"dirty_clear_action_count\":%"PRIu64
			",\"dirty_clear_phase_ordinal\":",
			dirty_clear_actions))
		return -1;
	if (dirty_clear_count) {
		if (rh_report_appendf(report, "%zu", repair->transaction_count - 1U))
			return -1;
	} else if (RH_APPEND_LITERAL(report, "null"))
		return -1;
	if (rh_report_appendf(report,
			",\"native_redo_count\":%"PRIu64
			",\"native_restart_count\":%"PRIu64
			",\"native_phase_ordinal\":",
			count[RH_WRITE_LOGFILE_REDO],
			count[RH_WRITE_LOGFILE_RESTART]))
		return -1;
	if (native_phase != SIZE_MAX) {
		if (rh_report_appendf(report, "%zu", native_phase))
			return -1;
	} else if (RH_APPEND_LITERAL(report, "null"))
		return -1;
	if (RH_APPEND_LITERAL(report, ",\"first_metadata_ordinal\":"))
		return -1;
	if (first_metadata != SIZE_MAX) {
		if (rh_report_appendf(report, "%zu", first_metadata))
			return -1;
	} else if (RH_APPEND_LITERAL(report, "null"))
		return -1;
	if (RH_APPEND_LITERAL(report, ",\"first_phase\":") ||
			rh_report_json_string(report, metadata_count ?
				"METADATA_REPAIR" : "DIRTY_CLEAR") ||
			RH_APPEND_LITERAL(report, ",\"last_phase\":") ||
			rh_report_json_string(report, dirty_clear_count ?
				"DIRTY_CLEAR" : "METADATA_REPAIR") ||
			rh_report_appendf(report,
				",\"final_rescan_digest\":\"%s\","
				"\"final_coverage_ledger_hash\":\"%s\","
				"\"final_diagnosis_hash\":\"%s\"},\"batch_samples\":[",
				rescan_hash[repair->transaction_count - 1U], coverage_hash,
				diagnosis_hash[repair->transaction_count - 1U]))
		return -1;
	for (i = 0; i < repair->transaction_count; i++) {
		const struct rh_repair_transaction_evidence *transaction =
			&repair->transactions[i];
		uint64_t local_count[RH_WRITE_KIND_COUNT];
		uint64_t local_bytes[RH_WRITE_KIND_COUNT];
		const char *phase = transaction->kind == RH_WAL_TX_DIRTY_CLEAR ?
			"DIRTY_CLEAR" : "METADATA_REPAIR";
		const char *stage = transaction->kind == RH_WAL_TX_DIRTY_CLEAR ?
			"FINAL" : "POST_METADATA";
		const char *origin = transaction->origin == RH_REPAIR_ORIGIN_NEW ? "NEW" :
			transaction->origin == RH_REPAIR_ORIGIN_RECOVERED_COMMITTED ?
				"RECOVERED_COMMITTED" : "RECOVERED_ROLLED_BACK";
		const char *batch_result = transaction->rolled_back ?
			"rolled-back" : "accepted";

		rh_transaction_maps(transaction, local_count, local_bytes);
		rh_hex_report(transaction->post_scan.census.coverage_hash, 32U,
			coverage_hash);
		if (rh_report_appendf(report,
				"%s{\"ordinal\":%zu,\"phase\":\"%s\",\"origin\":\"%s\","
				"\"transaction_uuid\":\"%s\",\"plan_hash\":\"%s\","
				"\"repair_ledger_hash\":\"%s\",\"entry_count\":%zu,"
				"\"target_bytes\":%"PRIu64",\"by_action_id\":" ,
				i ? "," : "", i, phase, origin, transaction->transaction_uuid,
				transaction->plan_hash, transaction->repair_ledger_hash,
				transaction->action_count, transaction->target_bytes) ||
				rh_id_map(report, local_count) ||
				RH_APPEND_LITERAL(report, ",\"by_kind\":") ||
				rh_kind_map(report, local_count) ||
				RH_APPEND_LITERAL(report, ",\"bytes_by_action_id\":") ||
				rh_id_map(report, local_bytes) ||
				RH_APPEND_LITERAL(report, ",\"bytes_by_kind\":") ||
				rh_kind_map(report, local_bytes) ||
				rh_report_appendf(report,
					",\"commit_started\":%s,\"commit_completed\":%s,"
					"\"rollback_completed\":%s,"
					"\"rollback_readback_verified\":%s,"
					"\"rollback_restored_entries\":%"PRIu64","
					"\"rollback_restored_bytes\":%"PRIu64
					",\"rollback_syncs\":%"PRIu64","
					"\"rollback_write_boundaries\":%"PRIu64","
					"\"last_verified_ordinal\":%"PRIu64
					",\"syncs\":%"PRIu64",\"write_boundaries\":%"PRIu64
					",\"result\":\"%s\",\"rescan_digest\":\"%s\","
					"\"post_coverage_ledger_hash\":\"%s\","
					"\"post_diagnosis_hash\":\"%s\","
					"\"sample_reasons\":[%s\"FIRST\",\"LAST\"],\"rescan\":" ,
					transaction->commit_started ? "true" : "false",
					transaction->commit_completed ? "true" : "false",
					transaction->rolled_back ? "true" : "false",
					transaction->rolled_back ? "true" : "false",
					transaction->rollback_restored_entries,
					transaction->rollback_restored_bytes,
					transaction->rollback_syncs,
					transaction->rollback_write_boundaries,
					transaction->last_verified_ordinal, transaction->syncs,
					transaction->write_boundaries, batch_result, rescan_hash[i], coverage_hash,
					diagnosis_hash[i],
					transaction->rolled_back ? "\"ERROR\"," : "") ||
				rh_snapshot(report, &transaction->post_scan, 1, i,
					"TRANSACTION", transaction->transaction_uuid,
					transaction->plan_hash, stage) ||
				RH_APPEND_LITERAL(report, "}"))
			return -1;
	}
	return RH_APPEND_LITERAL(report, "]");
}

static int rh_counter_positive(const struct rh_coverage_counter *counter)
{
	return counter && counter->known && counter->value != 0;
}

static struct rh_issue_detail rh_issue_select(
		const struct rh_scan_evidence *scan,
		const struct rh_repair_evidence *repair, int result)
{
	const char *repair_stage = repair && repair->refusal_stage[0] ?
		repair->refusal_stage : NULL;
	const char *scan_stage = scan && scan->refusal_stage[0] ?
		scan->refusal_stage : NULL;
	struct rh_issue_detail issue = {
		.code = "METADATA_UNRESOLVED",
		.pass = repair_stage ? repair_stage : scan_stage ? scan_stage : "orchestration",
		.message = "metadata is unresolved outside the qualified repair surface",
		.severity = "UNSAFE", .severity_code = 5
	};

	if (result == RH_RESULT_INTERNAL) {
		issue.code = "ORCHESTRATION_INTERNAL_ERROR";
		issue.message = "orchestration failed before a complete verdict";
	} else if (result == RH_RESULT_IO) {
		issue.code = "TARGET_IO_ERROR";
		issue.pass = scan_stage ? scan_stage : "device";
		issue.message = "target diagnosis encountered I/O uncertainty";
		issue.severity = "IO";
		issue.severity_code = 4;
	} else if (result == RH_RESULT_WRONG_ROOT) {
		issue.code = "IDENTITY_MISMATCH";
		issue.pass = scan_stage ? scan_stage : "identity";
		issue.message = "the target does not satisfy the T1OS identity contract";
	} else if (repair_stage &&
			(strstr(repair_stage, "rescan") || strstr(repair_stage, "accept"))) {
		issue.code = "REPAIR_POST_RESCAN_FAILED";
		issue.message = "a qualified repair did not pass its independent final verification";
	} else if (scan && (scan->native_refused || scan->native_log.parse_errors ||
			scan->native_log.unsupported_actions)) {
		issue.code = "NATIVE_LOG_UNSUPPORTED_ACTION";
		issue.pass = "native-log";
		issue.message = "the NTFS journal contains work outside the qualified replay surface";
	} else if (scan && scan->native_log.state == RH_NATIVE_LOG_REPLAY_PLANNED) {
		issue.code = "NATIVE_LOG_REPLAY_REQUIRED";
		issue.pass = "native-log";
		issue.message = "the validated NTFS journal still requires replay";
	} else if (scan && scan->wal.checked &&
			(scan->wal.valid != 1 || scan->wal.recovery_required != 0 ||
			 scan->wal_degraded || !scan->wal.write_safe)) {
		issue.code = scan->wal.recovery_required != 0 ?
			"WAL_RECOVERY_REQUIRED" : "WAL_UNSAFE";
		issue.pass = scan_stage ? scan_stage : "wal";
		issue.message = "the bound RootHealth WAL is not empty and write-safe";
	} else if (scan && (scan->boot.repaired_primary || scan->boot.repaired_backup ||
			scan->mirror.primary_repaired || scan->mirror.mirror_repaired)) {
		issue.code = "FOUNDATION_REPAIR_DEFERRED";
		issue.pass = scan_stage ? scan_stage : "foundation";
		issue.message = "a redundant-metadata repair lacks complete commit authority";
	} else if (scan && scan->mirror.failure_kind ==
			RH_MIRROR_FAILURE_VALID_DIVERGENCE) {
		issue.code = "MFT_MIRROR_DIVERGENCE";
		issue.pass = "mft-mirror";
		issue.message = "the primary and mirror MFT records are individually valid but differ";
	} else if (scan && scan->mirror.failure_kind ==
			RH_MIRROR_FAILURE_BOTH_UNSUPPORTED) {
		issue.code = "MFT_MIRROR_UNSUPPORTED_LAYOUT";
		issue.pass = "mft-mirror";
		issue.message = "neither copy of a mirrored MFT record matches the qualified structural layouts";
	} else if (!scan || !scan->census_available ||
			!scan->census.coverage.complete || !scan->census.providers_complete) {
		issue.code = "CENSUS_INCOMPLETE";
		issue.message = "the complete NTFS census or one of its providers did not finish";
	} else if (rh_counter_positive(&scan->census.coverage.fixed_system.failed)) {
		issue.code = "FIXED_SYSTEM_CHECK_FAILED";
		issue.pass = "fixed-system";
		issue.message = "one or more fixed NTFS system metadata checks failed";
	} else if (rh_counter_positive(&scan->census.coverage.namespace_links.unresolved) ||
			rh_counter_positive(&scan->census.coverage.namespace_links.unreadable)) {
		issue.code = "NAMESPACE_RECIPROCITY_MISMATCH";
		issue.pass = "namespace";
		issue.message = "the directory and FILE_NAME namespace evidence does not reconcile";
	} else if (scan->census.mft_bitmap.change_count) {
		issue.code = "MFT_BITMAP_MISMATCH";
		issue.pass = "mft-bitmap";
		issue.message = "the MFT allocation bitmap differs from the complete record census";
	} else if (scan->census.index_bitmap.change_count) {
		issue.code = "INDEX_BITMAP_MISMATCH";
		issue.pass = "index-bitmap";
		issue.message = "a directory index bitmap differs from the complete index census";
	} else if (scan->census.cluster_bitmap.change_count) {
		issue.code = "CLUSTER_BITMAP_MISMATCH";
		issue.pass = "cluster-bitmap";
		issue.message = "the volume allocation bitmap differs from the ownership census";
	} else if (scan->dirty_known && scan->dirty) {
		issue.code = "VOLUME_DIRTY";
		issue.pass = "volume-dirty";
		issue.message = "the NTFS volume dirty flag remains set";
	} else if (!rh_coverage_is_clean(&scan->census.coverage)) {
		issue.code = "UNSUPPORTED_VALID_METADATA";
		issue.pass = repair_stage ? repair_stage : "coverage";
		issue.message = "metadata outside the qualified validation surface prevents a clean verdict";
	}

	(void)rh_issue_add_predicate(&issue, "COMPLETE_CHECK_SURFACE");
	if (result == RH_RESULT_INTERNAL)
		(void)rh_issue_add_predicate(&issue, "ORCHESTRATION_COMPLETE");
	if (result == RH_RESULT_IO)
		(void)rh_issue_add_predicate(&issue, "NO_IO_UNCERTAINTY");
	if (result == RH_RESULT_WRONG_ROOT || (scan && !scan->identity_valid))
		(void)rh_issue_add_predicate(&issue, "T1OS_IDENTITY_BOUND");
	if (scan && (!scan->logfile_clean_known || !scan->logfile_clean))
		(void)rh_issue_add_predicate(&issue, "LOGFILE_CLEAN");
	if (scan && scan->dirty_known && scan->dirty)
		(void)rh_issue_add_predicate(&issue, "VOLUME_NOT_DIRTY");
	if (scan && scan->wal.checked && (scan->wal.valid != 1 ||
			scan->wal.recovery_required != 0 || scan->wal_degraded ||
			!scan->wal.write_safe))
		(void)rh_issue_add_predicate(&issue, "WAL_EMPTY_WRITE_SAFE");
	if (scan && scan->mirror.failure_kind != RH_MIRROR_FAILURE_NONE)
		(void)rh_issue_add_predicate(&issue, "MFT_MIRROR_QUALIFIED");
	if (!scan || !scan->census_available || !scan->census.coverage.complete)
		(void)rh_issue_add_predicate(&issue, "CENSUS_COMPLETE");
	if (!scan || !scan->census_available || !scan->census.providers_complete)
		(void)rh_issue_add_predicate(&issue, "PROVIDERS_COMPLETE");
	if (scan && scan->census_available &&
			!rh_coverage_is_clean(&scan->census.coverage))
		(void)rh_issue_add_predicate(&issue, "COVERAGE_CLEAN");
	if (repair_stage && (strstr(repair_stage, "rescan") ||
			strstr(repair_stage, "accept")))
		(void)rh_issue_add_predicate(&issue, "FINAL_RESCAN_CLEAN");
	return issue;
}

static int rh_issue(struct rh_report *report,
		const struct rh_issue_detail *issue)
{
	char hash[65];
	unsigned int i;

	if (rh_issue_ledger_hash(issue, hash) ||
			rh_report_appendf(report,
				"\"issue_ledger\":{\"format\":\"RHISS3\",\"entry_count\":1,"
				"\"ledger_hash\":\"%s\",\"resolved_count\":0,"
				"\"unresolved_count\":1,\"error_count\":1,"
				"\"by_severity\":{\"%s\":1},"
				"\"unresolved_by_severity\":{\"%s\":1},"
				"\"first_severity\":\"%s\",\"last_severity\":\"%s\"},"
				"\"issues\":[{\"ordinal\":0,\"code\":",
				hash, issue->severity, issue->severity,
				issue->severity, issue->severity) ||
			rh_report_json_string(report, issue->code) ||
			RH_APPEND_LITERAL(report, ",\"pass\":") ||
			rh_report_json_string(report, issue->pass) ||
			RH_APPEND_LITERAL(report, ",\"message\":") ||
			rh_report_json_string(report, issue->message) ||
			rh_report_appendf(report,
				",\"severity\":\"%s\",\"resolved\":false,"
				"\"record\":null,\"offset\":null,\"path\":null,"
				"\"policy\":\"DENY\",\"required_predicates\":[",
				issue->severity))
		return -1;
	for (i = 0; i < issue->predicate_count; i++) {
		if ((i && RH_APPEND_LITERAL(report, ",")) ||
				rh_report_json_string(report, issue->predicates[i]))
			return -1;
	}
	if (RH_APPEND_LITERAL(report, "],\"failed_predicates\":["))
		return -1;
	for (i = 0; i < issue->predicate_count; i++) {
		if ((i && RH_APPEND_LITERAL(report, ",")) ||
				rh_report_json_string(report, issue->predicates[i]))
			return -1;
	}
	if (RH_APPEND_LITERAL(report,
			"],\"action_ordinals\":[],"
			"\"sample_reasons\":[\"ERROR\",\"FIRST\",\"LAST\"]}]"))
		return -1;
	return 0;
}

static int rh_issue_empty(struct rh_report *report)
{
	return RH_APPEND_LITERAL(report,
		"\"issue_ledger\":{\"format\":\"RHISS3\",\"entry_count\":0,"
		"\"ledger_hash\":\"e148ae863889130ef3aeb5ea3a8f711abf07841005089a92ccddff952904d955\","
		"\"resolved_count\":0,\"unresolved_count\":0,\"error_count\":0,"
		"\"by_severity\":{},\"unresolved_by_severity\":{},"
		"\"first_severity\":null,\"last_severity\":null},\"issues\":[]");
}

static int rh_budget(struct rh_report *report, uint64_t written,
		uint64_t repair_count, int batch_samples, int batch_priority,
		uint64_t wal_count,
		int issue_samples)
{
	uint64_t repair_samples = repair_count > 64U ? 64U : repair_count;
	uint64_t wal_samples = wal_count > 64U ? 64U : wal_count;

	return rh_report_appendf(report,
		"{\"limit_bytes\":4194304,\"reservation_method\":\"POSIX_FALLOCATE\","
		"\"reserved_bytes\":4194304,\"reserved_before_mutation\":true,"
		"\"fixed_buffers_allocated_before_mutation\":true,"
		"\"envelope_frozen_before_mutation\":true,"
		"\"every_committed_batch_preflighted_before_its_commit\":true,"
		"\"future_batches_envelope_constrained\":true,"
		"\"worst_case_bytes\":3466470,\"written_bytes\":%"PRIu64","
		"\"size_proof_format\":\"RHSIZE3\",\"size_proof_hash\":\"%s\","
		"\"repair_samples_limit\":128,\"repair_samples_emitted\":%"PRIu64","
		"\"repair_samples_omitted\":%"PRIu64",\"repair_priority_emitted\":0,"
		"\"repair_priority_omitted\":0,\"batch_samples_limit\":64,"
		"\"batch_samples_emitted\":%d,\"batch_samples_omitted\":0,"
		"\"batch_priority_emitted\":%d,\"batch_priority_omitted\":0,"
		"\"wal_action_samples_limit\":128,\"wal_action_samples_emitted\":%"PRIu64","
		"\"wal_action_samples_omitted\":%"PRIu64",\"wal_action_priority_emitted\":0,"
		"\"wal_action_priority_omitted\":0,\"issue_samples_limit\":128,"
		"\"issue_samples_emitted\":%d,\"issue_samples_omitted\":0,"
		"\"issue_priority_emitted\":%d,\"issue_priority_omitted\":0}",
		written, rh_size_hash, repair_samples, repair_count - repair_samples,
		batch_samples, batch_priority, wal_samples, wal_count - wal_samples, issue_samples,
		issue_samples);
}

static int rh_build(struct rh_report *report, const struct rh_cli *cli,
		const struct rh_device_evidence *device,
		const struct rh_scan_evidence *initial,
		const struct rh_scan_evidence *final,
		const struct rh_foundation_evidence *foundation,
		const struct rh_repair_evidence *repair, int result,
		uint64_t written)
{
	struct rh_scan_evidence incomplete;
	struct rh_issue_detail issue;
	const struct rh_scan_evidence *last;
	int batch_priority = 0;
	uint64_t batch_verified = 0;
	size_t batch_index;

	for (batch_index = 0; batch_index < repair->transaction_count; batch_index++) {
		batch_priority += repair->transactions[batch_index].rolled_back != 0;
		batch_verified += repair->transactions[batch_index].last_verified_ordinal;
	}

	if (repair->transaction_count) {
		last = &repair->transactions[repair->transaction_count - 1U].post_scan;
	} else if (final) {
		last = final;
	} else if (cli->mode == RH_CLI_REPAIR) {
		/* An early repair refusal did not execute a fresh FINAL scan. */
		incomplete = *initial;
		incomplete.completed = 0;
		last = &incomplete;
	} else {
		last = initial;
	}
	issue = rh_issue_select(initial, repair, result);

	report->used = 0;
	if (RH_APPEND_LITERAL(report, "{\"format\":3,\"checker\":\"roothealth\","
			"\"checker_version\":") ||
			rh_report_json_string(report, ROOTHEALTH_REPAIR_VERSION) ||
			rh_report_appendf(report, ",\"mode\":\"%s\",\"result\":",
				cli->mode == RH_CLI_CHECK ? "check" : "repair") ||
			rh_report_json_string(report, rh_public_result(result)) ||
			rh_report_appendf(report, ",\"exit_code\":%d,\"device\":", result) ||
			rh_device(report, device) ||
			RH_APPEND_LITERAL(report, ",\"identity\":") ||
			rh_identity(report, cli, initial) ||
			RH_APPEND_LITERAL(report, ",\"initial\":") ||
			rh_snapshot(report, initial, 0, 0, NULL, NULL, NULL, NULL) ||
			RH_APPEND_LITERAL(report, ",\"native_log\":") ||
			rh_native(report, initial) ||
			RH_APPEND_LITERAL(report, ",\"foundation_repairs\":") ||
			rh_foundation(report, foundation) ||
			RH_APPEND_LITERAL(report, ",\"plan\":") ||
			rh_plan(report, foundation, repair) ||
			rh_report_appendf(report,
				",\"commit\":{\"started\":%s,\"completed\":%s,"
				"\"last_verified_ordinal\":%zu,\"syncs\":%"PRIu64
				",\"write_boundaries\":%"PRIu64"},\"batch_ledger\":",
				foundation->count || repair->transaction_count ? "true" : "false",
				foundation->count || repair->transaction_count ? "true" : "false",
				foundation->count + batch_verified,
				foundation->syncs + repair->syncs + repair->wal_syncs,
				foundation->write_boundaries + repair->write_boundaries +
					repair->wal_write_boundaries) ||
			(repair->transaction_count ?
				rh_repair_batches(report, repair) :
				(rh_batch_ledger(report, foundation) ||
				 RH_APPEND_LITERAL(report, ",\"batch_samples\":[]"))) ||
			RH_APPEND_LITERAL(report, ",\"repairs\":") ||
			rh_repair_action_samples(report, repair) ||
			RH_APPEND_LITERAL(report, ",\"wal\":") ||
			rh_wal(report, initial, repair) ||
			RH_APPEND_LITERAL(report, ",") ||
			(result == RH_RESULT_OK ? rh_issue_empty(report) :
			 rh_issue(report, &issue)) ||
			RH_APPEND_LITERAL(report, ",\"report_budget\":") ||
			rh_budget(report, written, repair->action_count,
				(int)repair->transaction_count, batch_priority,
				repair->wal_action_count,
				result == RH_RESULT_OK ? 0 : 1) ||
			RH_APPEND_LITERAL(report, ",\"final\":") ||
			(repair->transaction_count ?
				rh_snapshot(report, last, 1, repair->transaction_count - 1U,
					"TRANSACTION", repair->transactions[
						repair->transaction_count - 1U].transaction_uuid,
					repair->transactions[
						repair->transaction_count - 1U].plan_hash, "FINAL") :
				rh_snapshot(report, last, 1, 0,
					foundation->count ? "FOUNDATION" : "INITIAL", NULL,
					foundation->count ? foundation->plan_hash : NULL, "FINAL")) ||
			rh_report_appendf(report, ",\"dirty_cleared\":%s}\n",
				repair->dirty_cleared ? "true" : "false"))
		return -1;
	return 0;
}

int rh_format3_publish(struct rh_report *report, const struct rh_cli *cli,
		const struct rh_device_evidence *device,
		const struct rh_scan_evidence *initial,
		const struct rh_scan_evidence *final,
		const struct rh_foundation_evidence *foundation,
		const struct rh_repair_evidence *repair, int result)
{
	uint64_t guess = 0, prior = UINT64_MAX;
	unsigned int iteration;

#ifdef ROOTHEALTH_FORMAT3_TEST_HOOKS
	if (getenv("ROOTHEALTH_FORMAT3_TEST_FORCE_BUILD_FAILURE")) {
		errno = EOVERFLOW;
		rh_report_abort(report);
		return -1;
	}
#endif

	for (iteration = 0; iteration < 8; iteration++) {
		if (rh_build(report, cli, device, initial, final, foundation,
				repair, result, guess)) {
			rh_report_abort(report);
			return -1;
		}
		if (report->used == prior)
			break;
		prior = report->used;
		guess = report->used;
	}
	if (iteration == 8 || report->used != guess ||
			report->used > 3466470U) {
		errno = EOVERFLOW;
		rh_report_abort(report);
		return -1;
	}
	return rh_report_publish(report);
}
