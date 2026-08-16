
/* ROOTHEALTH_REPAIR_ROLE(ORCHESTRATOR) ROOTHEALTH_IO_ROLE(REPORT) */
#include "config.h"

#include <errno.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

#include "roothealth_format3.h"
#include "roothealth_orchestrator.h"
#include "roothealth_report.h"

static void rh_diagnostic_hex(const unsigned char *bytes, size_t length,
		char *output)
{
	static const char digits[] = "0123456789abcdef";
	size_t i;

	for (i = 0; i < length; i++) {
		output[i * 2U] = digits[bytes[i] >> 4];
		output[i * 2U + 1U] = digits[bytes[i] & 15U];
	}
	output[length * 2U] = 0;
}

int main(int argc, char **argv)
{
	struct rh_cli cli;
	struct rh_report report;
	struct rh_device_evidence device;
	struct rh_scan_evidence initial, current, final;
	struct rh_scan_evidence *active = &initial;
	struct rh_foundation_evidence foundation;
	struct rh_repair_evidence repair;
	struct rh_writer writer;
	char binary_hash[65], initial_exec_id[37];
	int result, have_final = 0, have_current = 0;

	if (rh_cli_parse(argc, argv, &cli)) {
		rh_cli_usage(stderr);
		return RH_RESULT_INTERNAL;
	}
	if (cli.internal_fd >= 0)
		return rh_orchestrator_internal_rescan(&cli);
	if (cli.mode == RH_CLI_PREFLIGHT) {
		memset(&writer, 0, sizeof(writer));
		writer.read_fd = -1;
		writer.write_fd = -1;
		if (rh_device_resolve(cli.device_path, &device))
			return errno == ENOMEM ? RH_RESULT_INTERNAL : RH_RESULT_IO;
		result = rh_orchestrator_scan(&cli, &device, &initial, &writer, 0);
		if (!device.selection_proven)
			result = rh_result_precedence(result, RH_RESULT_IO);
		if (!cli.quiet)
			fprintf(stderr, "roothealth preflight: %s\n",
				rh_public_result(result));
		return result;
	}
	if (cli.mode == RH_CLI_BOOT_REPAIR) {
		unsigned int attempt, repairs = 0;
		const char *stage = "boot-scan";
		const char *repair_stage = "none";
		int saved_errno = 0, repair_errno = 0;

		if (rh_device_resolve(cli.device_path, &device))
			return errno == ENOMEM ? RH_RESULT_INTERNAL : RH_RESULT_IO;
		result = RH_RESULT_UNSAFE;
		for (attempt = 0; attempt < 5U; attempt++) {
			repair_stage = "none";
			repair_errno = 0;
			memset(&writer, 0, sizeof(writer));
			writer.read_fd = -1;
			writer.write_fd = -1;
			result = rh_orchestrator_scan(&cli, &device, &initial,
				&writer, 1);
			if (!device.selection_proven)
				result = rh_result_precedence(result, RH_RESULT_IO);
			if (result == RH_RESULT_OK) {
				if (initial.wal_handle_valid)
					rh_wal_uninstall_backend(&initial.wal_handle);
				rh_writer_close(&writer);
				if (!cli.quiet)
					fprintf(stderr,
						"roothealth boot: admitted after %u repair step%s\n",
						repairs, repairs == 1U ? "" : "s");
				return RH_RESULT_OK;
			}
			stage = initial.refusal_stage[0] ? initial.refusal_stage :
				"boot-scan";
			saved_errno = initial.refusal_errno;
			if (result != RH_RESULT_UNSAFE || attempt == 4U) {
				if (initial.wal_handle_valid)
					rh_wal_uninstall_backend(&initial.wal_handle);
				rh_writer_close(&writer);
				break;
			}
			errno = 0;
			result = rh_orchestrator_boot_repair(&initial, &writer);
			if (result != RH_RESULT_OK) {
				repair_stage = "boot-repair";
				repair_errno = errno;
			}
			if (initial.wal_handle_valid)
				rh_wal_uninstall_backend(&initial.wal_handle);
			rh_writer_close(&writer);
			if (result != RH_RESULT_OK)
				break;
			repairs++;
		}
		fprintf(stderr,
			"roothealth boot refusal: result=%s exit=%d stage=%s errno=%d (%s) repairs=%u repair_stage=%s repair_errno=%d wal_state=%d wal_degraded=%d identity_valid=%d native_checked=%d native_state=%d native_parse_errors=%u native_unsupported=%u dirty_known=%d dirty=%d\n",
			rh_public_result(result), result, stage, saved_errno,
			saved_errno ? strerror(saved_errno) : "none", repairs,
			repair_stage, repair_errno, initial.wal.state,
			initial.wal_degraded, initial.identity_valid,
			initial.native_log.checked, (int)initial.native_log.state,
			initial.native_log.parse_errors,
			initial.native_log.unsupported_actions,
			initial.dirty_known, initial.dirty);
		return result;
	}
	/*
	 * Reserve the complete 4 MiB report arena before resolving or opening the
	 * target.  O_EXCL/O_NOFOLLOW also makes target/report aliasing fail closed.
	 */
	if (rh_report_prepare(&report, cli.report_path))
		return RH_RESULT_INTERNAL;
	if (rh_device_resolve(cli.device_path, &device) ||
			rh_binary_hash(binary_hash) || rh_uuid_text(initial_exec_id)) {
		if (rh_report_abort(&report))
			return RH_RESULT_INTERNAL;
		return errno == ENOMEM ? RH_RESULT_INTERNAL : RH_RESULT_IO;
	}
	memset(&foundation, 0, sizeof(foundation));
	memset(&repair, 0, sizeof(repair));
	memset(&writer, 0, sizeof(writer));
	writer.read_fd = -1;
	writer.write_fd = -1;

	result = rh_orchestrator_scan(&cli, &device, &initial, &writer, 1);
	/* rh_orchestrator_scan initializes the entire snapshot. */
	strcpy(initial.execution.role, "INITIAL");
	strcpy(initial.execution.transport, "DIRECT");
	strcpy(initial.execution.exec_id, initial_exec_id);
	strcpy(initial.execution.binary_sha256, binary_hash);
	initial.execution.pid = (uint64_t)getpid();
	initial.execution.parent_pid = (uint64_t)getppid();
	if (writer.path && writer.device_id == device.resolved_stat.st_dev &&
			writer.inode_id == device.resolved_stat.st_ino)
		device.selection_proven = 1;
	if (cli.mode == RH_CLI_CHECK) {
		if (initial.wal_handle_valid)
			rh_wal_uninstall_backend(&initial.wal_handle);
		if (writer.path)
			rh_writer_close(&writer);
		final = initial; /* public check aliases its one read-only scan */
		have_final = 1;
	} else if (writer.path) {
		if (initial.wal_handle_valid && initial.wal.valid == 1 &&
				(initial.wal_degraded || initial.wal.state != RH_WAL_EMPTY)) {
			struct rh_wal_observation observed_wal = initial.wal;

			if (initial.wal_degraded)
				result = rh_orchestrator_reconstruct_degraded(&initial,
					&writer, &repair);
			else
				result = RH_RESULT_OK;
			if (result == RH_RESULT_OK && initial.wal.state != RH_WAL_EMPTY)
				result = rh_orchestrator_recover(&cli, &device, binary_hash,
					report.fd, &initial, &writer, &repair);
			initial.wal = observed_wal;
			if (initial.wal_handle_valid)
				rh_wal_uninstall_backend(&initial.wal_handle);
			rh_writer_close(&writer);
			if (result == RH_RESULT_OK) {
				memset(&writer, 0, sizeof(writer));
				writer.read_fd = -1;
				writer.write_fd = -1;
				result = rh_orchestrator_scan(&cli, &device, &current,
					&writer, 1);
				have_current = 1;
				active = &current;
			}
		}
		if (writer.path)
			result = rh_orchestrator_repair(&cli, &device, binary_hash,
				report.fd, active, &writer, &repair);
		if (active->wal_handle_valid)
			rh_wal_uninstall_backend(&active->wal_handle);
		rh_writer_close(&writer);
		if (result == RH_RESULT_OK && !repair.transaction_count) {
			result = rh_orchestrator_self_rescan(&cli, &device, &final,
				binary_hash, report.fd);
			have_final = final.completed || final.scan_id[0];
		}
	}
	if (!device.selection_proven)
		result = rh_result_precedence(result, RH_RESULT_IO);
	if (rh_format3_publish(&report, &cli, &device, &initial,
			have_final ? &final : NULL, &foundation, &repair, result)) {
		if (initial.census_available)
			rh_complete_census_release(&initial.census);
		if (have_current && current.census_available)
			rh_complete_census_release(&current.census);
		if (cli.mode == RH_CLI_REPAIR && have_final && final.census_available)
			rh_complete_census_release(&final.census);
		rh_orchestrator_repair_release(&repair);
		return RH_RESULT_INTERNAL;
	}
	if (result != RH_RESULT_OK) {
		const char *stage = repair.refusal_stage[0] ? repair.refusal_stage :
			(active && active->refusal_stage[0] ? active->refusal_stage :
			 "unclassified");
		int refusal_errno = repair.refusal_stage[0] ? repair.refusal_errno :
			(active ? active->refusal_errno : 0);

		if (active && active->mirror.failure_record_known) {
			const uint32_t record = active->mirror.failure_record;
			const typeof(active->mirror.records[0]) *observation =
				&active->mirror.records[record];
			const char *kind = active->mirror.failure_kind ==
				RH_MIRROR_FAILURE_VALID_DIVERGENCE ?
				"valid-divergence" : "both-unsupported";
			char primary_hash[65] = "unavailable";
			char mirror_hash[65] = "unavailable";

			if (observation->hashes_known) {
				rh_diagnostic_hex(observation->primary_sha256, 32U,
					primary_hash);
				rh_diagnostic_hex(observation->mirror_sha256, 32U,
					mirror_hash);
			}
			fprintf(stderr,
				"roothealth refusal: result=%s exit=%d stage=%s errno=%d (%s) detail=%s record=%"PRIu32" primary_valid=%d mirror_valid=%d equal=%d first_difference=%"PRIu32" differing_bytes=%"PRIu32" primary_sha256=%s mirror_sha256=%s\n",
				rh_public_result(result), result, stage, refusal_errno,
				refusal_errno ? strerror(refusal_errno) : "none", kind,
				record, observation->primary_valid,
				observation->mirror_valid,
				observation->equal_known ? observation->equal : -1,
				observation->first_difference_known ?
					observation->first_difference_offset : UINT32_MAX,
				observation->differing_bytes, primary_hash, mirror_hash);
		} else {
			fprintf(stderr,
				"roothealth refusal: result=%s exit=%d stage=%s errno=%d (%s)\n",
				rh_public_result(result), result, stage, refusal_errno,
				refusal_errno ? strerror(refusal_errno) : "none");
		}
	}
	if (initial.census_available)
		rh_complete_census_release(&initial.census);
	if (have_current && current.census_available)
		rh_complete_census_release(&current.census);
	if (cli.mode == RH_CLI_REPAIR && have_final && final.census_available)
		rh_complete_census_release(&final.census);
	rh_orchestrator_repair_release(&repair);
	return result;
}
