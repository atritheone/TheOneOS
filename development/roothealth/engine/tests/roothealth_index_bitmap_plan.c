#include "config.h"

#include <errno.h>
#include <stdio.h>
#include <string.h>

#include "roothealth_index_bitmap.h"

static int target_exact(const struct rh_write_operation *operation,
		const struct rh_index_bitmap_change *change)
{
	static const unsigned char i30_utf16le[] = {
		'$', 0, 'I', 0, '3', 0, '0', 0
	};
	const struct rh_write_semantic_target *target = &operation->target;
	unsigned char name_hash[32], before_hash[32], after_hash[32];
	uint16_t flags;

	rh_sha256(i30_utf16le, sizeof(i30_utf16le), name_hash);
	rh_sha256(&change->before, 1, before_hash);
	rh_sha256(&change->after, 1, after_hash);
	flags = RH_WRITE_TARGET_SET_ONLY;
	if (change->storage == RH_INDEX_BITMAP_RESIDENT_MFT)
		flags |= RH_WRITE_TARGET_PRIMARY | RH_WRITE_TARGET_RESIDENT;
	else
		flags |= RH_WRITE_TARGET_NONRESIDENT;
	return operation->kind == RH_WRITE_INDEX_BITMAP &&
		operation->offset == change->physical_offset &&
		operation->length == change->physical_length &&
		target->seal_version == 1 &&
		target->object == (change->storage == RH_INDEX_BITMAP_RESIDENT_MFT ?
			RH_WRITE_TARGET_MFT_RECORD_PRIMARY :
			RH_WRITE_TARGET_NONRESIDENT_ATTRIBUTE) &&
		target->owner_mft_record == change->owner_mft_record &&
		target->owner_sequence == change->owner_sequence &&
		target->attribute_instance == change->bitmap_instance &&
		target->attribute_type == AT_BITMAP &&
		target->attribute_name_length == 4 && target->flags == flags &&
		!memcmp(target->attribute_name_hash, name_hash, 32) &&
		target->logical_offset == change->logical_offset &&
		target->logical_length == 1 &&
		target->semantic_target_offset ==
			(change->storage == RH_INDEX_BITMAP_RESIDENT_MFT ?
			 change->resident_record_offset + change->resident_value_offset :
			 change->physical_offset) &&
		target->semantic_target_length == 1 &&
		!memcmp(target->semantic_before_hash, before_hash, 32) &&
		!memcmp(target->semantic_after_hash, after_hash, 32) &&
		!target->evidence_version && !target->evidence_generation &&
		!target->finalized;
}

int main(int argc, char **argv)
{
	struct rh_writer writer;
	struct rh_ntfs_overlay overlay;
	struct rh_index_bitmap_census initial, repeat, final;
	size_t first = 0;
	const char *mode;
	int mounted = 0;
	int result = 1;

	memset(&initial, 0, sizeof(initial));
	memset(&repeat, 0, sizeof(repeat));
	memset(&final, 0, sizeof(final));
	if (argc != 3 || (strcmp(argv[2], "set") &&
			strcmp(argv[2], "clean") && strcmp(argv[2], "clear")))
		return 5;
	mode = argv[2];
	if (rh_writer_open(&writer, argv[1]))
		return 3;
	if (rh_ntfs_overlay_mount(&overlay, &writer, 0))
		goto out_writer;
	mounted = 1;
	if (rh_index_bitmap_census_run(overlay.volume, &writer, 1, &initial)) {
		fprintf(stderr, "initial index census failed: %s mft=%llu/%llu "
			"dirs=%llu/%llu indexes=%llu/%llu blocks=%llu/%llu "
			"reachable=%llu unreadable=%llu ambiguous=%llu unresolved=%llu "
			"failure_stage=%u\n",
			strerror(errno),
			(unsigned long long)initial.mft_slots_completed,
			(unsigned long long)initial.mft_slots_expected,
			(unsigned long long)initial.directories_completed,
			(unsigned long long)initial.directories_expected,
			(unsigned long long)initial.indexes_completed,
			(unsigned long long)initial.indexes_expected,
			(unsigned long long)initial.index_blocks_examined,
			(unsigned long long)initial.index_blocks_expected,
			(unsigned long long)initial.index_blocks_reachable,
			(unsigned long long)initial.unreadable_records,
			(unsigned long long)initial.ambiguous_attributes,
			(unsigned long long)initial.unresolved_blocks,
			initial.failure_stage);
		goto out_overlay;
	}
	if (!strcmp(mode, "clean")) {
		if (!initial.complete || !initial.clean || initial.change_count ||
				initial.clear_bits_required || writer.operation_count ||
				writer.write_boundaries) {
			fprintf(stderr, "clean index census was not a no-op\n");
			goto out_initial;
		}
		printf("index-bitmap-clean slots=%llu dirs=%llu indexes=%llu "
			"entries=%llu blocks=%llu operations=0 source_writes=0\n",
			(unsigned long long)initial.mft_slots_expected,
			(unsigned long long)initial.directories_expected,
			(unsigned long long)initial.indexes_expected,
			(unsigned long long)initial.index_entries_examined,
			(unsigned long long)initial.index_blocks_expected);
		result = 0;
		goto out_initial;
	}
	if (!strcmp(mode, "clear")) {
		errno = 0;
		if (!initial.complete || initial.clean || initial.change_count != 1 ||
				initial.clear_bits_required != 1 || initial.set_only_safe ||
				initial.changes[0].evidence_version !=
					RH_INDEX_BITMAP_EVIDENCE_VERSION ||
				initial.changes[0].set_mask ||
				initial.changes[0].clear_mask != 2 ||
				initial.changes[0].before != 3 ||
				initial.changes[0].after != 1 ||
				!rh_index_bitmap_stage(&overlay, &initial, &first) ||
				writer.operation_count || writer.write_boundaries) {
			fprintf(stderr, "unsafe index clear was not refused: %s "
				"changes=%zu clears=%llu operations=%zu\n", strerror(errno),
				initial.change_count,
				(unsigned long long)initial.clear_bits_required,
				writer.operation_count);
			goto out_initial;
		}
		printf("index-bitmap-clear-refused owner=5 logical=0 before=03 "
			"after=01 set=00 clear=02 operations=0 source_writes=0 "
			"reason=namespace-ledger-required\n");
		result = 0;
		goto out_initial;
	}
	if (!initial.complete || initial.clean || initial.change_count != 1 ||
			initial.clear_bits_required || !initial.set_only_safe ||
			!initial.sets_proven_reachable || initial.changes[0].owner_mft_record != 5 ||
			initial.changes[0].evidence_version !=
				RH_INDEX_BITMAP_EVIDENCE_VERSION ||
			initial.changes[0].owner_sequence != 5 ||
			initial.changes[0].bitmap_instance != 4 ||
			initial.changes[0].storage != RH_INDEX_BITMAP_RESIDENT_MFT ||
			initial.changes[0].block_ordinal != 0 ||
			initial.changes[0].logical_offset != 0 ||
			initial.changes[0].resident_record_offset != 21504 ||
			initial.changes[0].resident_value_offset != 496 ||
			initial.changes[0].physical_offset != 21504 ||
			initial.changes[0].physical_length != 1024 ||
			initial.changes[0].before != 0 || initial.changes[0].after != 1 ||
			initial.changes[0].set_mask != 1 || initial.changes[0].clear_mask) {
		fprintf(stderr, "unexpected index census: complete=%d clean=%d "
			"changes=%zu clears=%llu owner=%llu seq=%u instance=%u "
			"storage=%u block=%llu logical=%llu physical=%llu "
			"before=%02x after=%02x set=%02x clear=%02x\n",
			initial.complete, initial.clean, initial.change_count,
			(unsigned long long)initial.clear_bits_required,
			(unsigned long long)(initial.change_count ?
			 initial.changes[0].owner_mft_record : 0),
			initial.change_count ? initial.changes[0].owner_sequence : 0,
			initial.change_count ? initial.changes[0].bitmap_instance : 0,
			initial.change_count ? initial.changes[0].storage : 0,
			(unsigned long long)(initial.change_count ?
			 initial.changes[0].block_ordinal : 0),
			(unsigned long long)(initial.change_count ?
			 initial.changes[0].logical_offset : 0),
			(unsigned long long)(initial.change_count ?
			 initial.changes[0].physical_offset : 0),
			initial.change_count ? initial.changes[0].before : 0,
			initial.change_count ? initial.changes[0].after : 0,
			initial.change_count ? initial.changes[0].set_mask : 0,
			initial.change_count ? initial.changes[0].clear_mask : 0);
		goto out_initial;
	}
	if (rh_index_bitmap_census_run(overlay.volume, &writer, 99, &repeat) ||
			memcmp(initial.census_hash, repeat.census_hash, 32) ||
			memcmp(initial.tree_hash, repeat.tree_hash, 32) ||
			memcmp(initial.expected_hash, repeat.expected_hash, 32)) {
		fprintf(stderr, "canonical index census changed with generation\n");
		goto out_repeat;
	}
	rh_index_bitmap_census_destroy(&repeat);
	if (rh_index_bitmap_stage(&overlay, &initial, &first) || first != 1 ||
			writer.operation_count != 1 || writer.write_boundaries ||
			!target_exact(&writer.operations[0], &initial.changes[0])) {
		fprintf(stderr, "index stage failed: %s first=%zu ops=%zu writes=%zu\n",
			strerror(errno), first, writer.operation_count,
			writer.write_boundaries);
		goto out_initial;
	}
	rh_ntfs_overlay_unmount(&overlay);
	mounted = 0;
	if (rh_ntfs_overlay_mount(&overlay, &writer, 0))
		goto out_initial;
	mounted = 1;
	if (rh_index_bitmap_census_run(overlay.volume, &writer, 2, &final) ||
			!final.complete || !final.clean || final.change_count ||
			final.clear_bits_required ||
			memcmp(initial.tree_hash, final.tree_hash, 32) ||
			memcmp(initial.expected_hash, final.expected_hash, 32)) {
		fprintf(stderr, "final index census failed: %s complete=%d clean=%d "
			"changes=%zu clears=%llu\n", strerror(errno), final.complete,
			final.clean, final.change_count,
			(unsigned long long)final.clear_bits_required);
		goto out_final;
	}
	printf("index-bitmap-plan slots=%llu dirs=%llu indexes=%llu "
		"entries=%llu blocks=%llu bitmap_bits=%llu operations=%zu action=%u "
		"owner=%llu sequence=%u instance=%u logical=0 target_offset=21504 "
		"target_length=1024 resident_value_offset=496 "
		"before=00 after=01 set=01 clear=00 source_writes=%zu "
		"final_clean=1 canonical_hash=1 evidence=RHI30EV2 "
		"policy_gate=namespace-pending\n",
		(unsigned long long)initial.mft_slots_expected,
		(unsigned long long)initial.directories_expected,
		(unsigned long long)initial.indexes_expected,
		(unsigned long long)initial.index_entries_examined,
		(unsigned long long)initial.index_blocks_expected,
		(unsigned long long)initial.bitmap_bits_examined,
		writer.operation_count,
		RH_WRITE_ACTION_ID(writer.operations[0].kind),
		(unsigned long long)initial.changes[0].owner_mft_record,
		initial.changes[0].owner_sequence,
		initial.changes[0].bitmap_instance, writer.write_boundaries);
	result = 0;
out_final:
	rh_index_bitmap_census_destroy(&final);
out_initial:
	rh_index_bitmap_census_destroy(&initial);
	goto out_overlay;
out_repeat:
	rh_index_bitmap_census_destroy(&repeat);
	goto out_initial;
out_overlay:
	if (mounted)
		rh_ntfs_overlay_unmount(&overlay);
out_writer:
	rh_writer_close(&writer);
	return result;
}
