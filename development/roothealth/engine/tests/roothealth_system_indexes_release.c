#include "config.h"

#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "roothealth_census_device.h"
#include "roothealth_index_bitmap.h"
#include "roothealth_namespace.h"
#include "roothealth_raw_mft.h"
#include "roothealth_system_indexes.h"
#include "roothealth_write.h"

static void hex(const unsigned char bytes[32], char output[65])
{
	static const char digits[] = "0123456789abcdef";
	unsigned int i;

	for (i = 0; i < 32U; i++) {
		output[i * 2U] = digits[bytes[i] >> 4];
		output[i * 2U + 1U] = digits[bytes[i] & 15U];
	}
	output[64] = 0;
}

int main(int argc, char **argv)
{
	const uint64_t generation = UINT64_C(0x5359534944580001);
	struct rh_writer writer;
	struct rh_census_reader reader;
	struct rh_census_device device;
	struct rh_raw_mft_census raw;
	struct rh_namespace_census namespace_census;
	struct rh_index_bitmap_census i30_census;
	struct rh_system_index_census *census = NULL;
	struct rh_system_index_census_view view;
	struct rh_free_slot_component_seal *reparse_seal = NULL;
	struct rh_free_slot_component_seal *objid_seal = NULL;
	char census_hash[65], reparse_hash[65], objid_hash[65], quota_hash[65];
	const char *mode;
	uint64_t system_generation;
	size_t expected_indexed;
	int fixture;
	int opened = 0, mounted = 0, result = 1;

	if (argc != 2 && (argc != 3 ||
		(strcmp(argv[2], "fixture") && strcmp(argv[2], "refuse-reparse") &&
		 strcmp(argv[2], "refuse-objid") &&
		 strcmp(argv[2], "quota-o-mismatch") &&
		 strcmp(argv[2], "quota-q-refuse") &&
		 strcmp(argv[2], "source-refuse"))))
		return 64;
	mode = argc == 2 ? "release" : argv[2];
	fixture = argc == 3;
	system_generation = !strcmp(mode, "source-refuse") ? generation + 1U :
		generation;
	expected_indexed = fixture ? 1U : 0U;
	memset(&raw, 0, sizeof(raw));
	memset(&namespace_census, 0, sizeof(namespace_census));
	memset(&i30_census, 0, sizeof(i30_census));
	memset(&view, 0, sizeof(view));
	if (rh_writer_open(&writer, argv[1]))
		goto out;
	opened = 1;
	if (rh_census_reader_from_writer_prefix(&writer, 0, &reader) ||
		rh_census_device_mount(&device, &reader, 0))
		goto out;
	mounted = 1;
	if (rh_raw_mft_census_run_reader(device.volume, &reader, generation,
			&raw)) {
		fprintf(stderr, "system-index fixture step=raw errno=%d\n", errno);
		goto out;
	}
	if (rh_namespace_census_run(&raw, generation, &namespace_census) ||
		rh_namespace_i30_census_run_reader(device.volume, &reader, &raw,
			&namespace_census, &i30_census)) {
		fprintf(stderr, "system-index fixture step=namespace errno=%d\n",
			errno);
		goto out;
	}
	if (rh_system_index_census_run(&reader, device.volume, &raw,
			&namespace_census, system_generation, &census)) {
		fprintf(stderr, "system-index fixture step=census errno=%d\n", errno);
		goto out;
	}
	if (rh_system_index_census_get_view(census, &view)) {
		fprintf(stderr, "system-index fixture step=view errno=%d\n", errno);
		goto out;
	}
	if (!strcmp(mode, "source-refuse")) {
		errno = 0;
		if (view.complete || view.records_complete ||
			view.attributes_complete || view.no_io_uncertainty ||
			!memcmp(view.census_hash, (unsigned char[32]){ 0 }, 32U) ||
			!rh_system_index_reparse_component_seal(census,
				&reparse_seal) || errno != EINVAL || writer.operation_count) {
			fprintf(stderr, "source refusal gate failed complete=%u "
				"records=%u attributes=%u io=%u errno=%d ops=%zu\n",
				view.complete, view.records_complete,
				view.attributes_complete, view.no_io_uncertainty, errno,
				writer.operation_count);
			goto out;
		}
		printf("raw_system_indexes=green mode=source-refuse "
			"generation=mismatch authority=absent seal=refused "
			"operations=0\n");
		result = 0;
		goto out;
	}
	if (!strcmp(mode, "refuse-reparse")) {
		errno = 0;
		if (!rh_system_index_reparse_component_seal(census,
				&reparse_seal) || errno != EUCLEAN ||
			rh_system_index_objid_component_seal(census, &objid_seal) ||
			view.index[RH_SYSTEM_INDEX_REPARSE_R].structurally_valid ||
			!view.reparse_authority_complete ||
			view.reparse_reference_count != 1U || writer.operation_count) {
			fprintf(stderr, "system-index refusal mismatch errno=%d "
				"structural=%u authority=%u refs=%zu ops=%zu\n", errno,
				view.index[RH_SYSTEM_INDEX_REPARSE_R].structurally_valid,
				view.reparse_authority_complete,
				view.reparse_reference_count, writer.operation_count);
			goto out;
		}
		printf("raw_system_indexes=green mode=refuse-reparse "
			"authority=complete observed_index=invalid seal=refused "
			"objid_seal=green operations=0\n");
		result = 0;
		goto out;
	}
	if (!strcmp(mode, "refuse-objid")) {
		errno = 0;
		if (!rh_system_index_objid_component_seal(census, &objid_seal) ||
			errno != EINVAL ||
			rh_system_index_reparse_component_seal(census, &reparse_seal) ||
			view.index[RH_SYSTEM_INDEX_OBJID_O].structurally_valid ||
			view.objid_authority_complete ||
			view.objid_reference_count || writer.operation_count) {
			fprintf(stderr, "object-id refusal mismatch errno=%d "
				"structural=%u authority=%u refs=%zu ops=%zu\n", errno,
				view.index[RH_SYSTEM_INDEX_OBJID_O].structurally_valid,
				view.objid_authority_complete,
				view.objid_reference_count, writer.operation_count);
			goto out;
		}
		printf("raw_system_indexes=green mode=refuse-objid "
			"authority=absent observed_index=invalid seal=refused "
			"reparse_seal=green operations=0\n");
		result = 0;
		goto out;
	}
	if (rh_system_index_reparse_component_seal(census, &reparse_seal)) {
		fprintf(stderr, "system-index fixture step=reparse-seal errno=%d "
			"complete=%u auth=%u/%u/%u ns=%u structural=%u refs=%zu entries=%llu\n",
			errno, view.complete, view.reparse_authority_complete,
			view.objid_authority_complete, view.quota_authority_complete,
			view.namespace_reciprocity_complete,
			view.index[RH_SYSTEM_INDEX_REPARSE_R].structurally_valid,
			view.reparse_reference_count,
			(unsigned long long)view.index[RH_SYSTEM_INDEX_REPARSE_R].entries_examined);
		goto out;
	}
	if (!strcmp(mode, "quota-o-mismatch")) {
		if (!view.complete || !view.quota_authority_complete ||
			!view.index[RH_SYSTEM_INDEX_QUOTA_O].structurally_valid ||
			view.index[RH_SYSTEM_INDEX_QUOTA_O].clean ||
			!view.index[RH_SYSTEM_INDEX_QUOTA_Q].clean ||
			writer.operation_count) {
			fprintf(stderr, "quota-o mismatch gate failed complete=%u "
				"authority=%u structural=%u clean=%u/%u ops=%zu\n",
				view.complete, view.quota_authority_complete,
				view.index[RH_SYSTEM_INDEX_QUOTA_O].structurally_valid,
				view.index[RH_SYSTEM_INDEX_QUOTA_O].clean,
				view.index[RH_SYSTEM_INDEX_QUOTA_Q].clean,
				writer.operation_count);
			goto out;
		}
		printf("raw_system_indexes=green mode=quota-o-mismatch "
			"q_authority=complete o_manifest=mismatch operations=0\n");
		result = 0;
		goto out;
	}
	if (!strcmp(mode, "quota-q-refuse")) {
		if (view.complete || view.quota_authority_complete ||
			view.index[RH_SYSTEM_INDEX_QUOTA_Q].structurally_valid ||
			writer.operation_count) {
			fprintf(stderr, "quota-q refusal gate failed complete=%u "
				"authority=%u structural=%u ops=%zu\n", view.complete,
				view.quota_authority_complete,
				view.index[RH_SYSTEM_INDEX_QUOTA_Q].structurally_valid,
				writer.operation_count);
			goto out;
		}
		printf("raw_system_indexes=green mode=quota-q-refuse "
			"q_authority=absent quota_policy=closed operations=0\n");
		result = 0;
		goto out;
	}
	if (rh_system_index_objid_component_seal(census, &objid_seal)) {
		fprintf(stderr, "system-index fixture step=objid-seal errno=%d "
			"complete=%u auth=%u structural=%u refs=%zu entries=%llu\n",
			errno, view.complete, view.objid_authority_complete,
			view.index[RH_SYSTEM_INDEX_OBJID_O].structurally_valid,
			view.objid_reference_count,
			(unsigned long long)view.index[RH_SYSTEM_INDEX_OBJID_O].entries_examined);
		goto out;
	}
	if (
		rh_free_slot_component_seal_kind(reparse_seal) !=
			RH_FREE_SLOT_COMPONENT_REPARSE ||
		rh_free_slot_component_seal_kind(objid_seal) !=
			RH_FREE_SLOT_COMPONENT_OBJID) {
		fprintf(stderr, "system-index fixture step=seal-kind errno=%d\n", errno);
		goto out;
	}
	if (!view.complete || !view.records_complete ||
		!view.attributes_complete || !view.no_io_uncertainty ||
		!view.namespace_reciprocity_complete ||
		!view.reparse_authority_complete ||
		!view.objid_authority_complete || !view.quota_authority_complete ||
		view.reparse_count != expected_indexed ||
		view.objid_count != expected_indexed ||
		view.quota_count != 2U || view.sid_arena_size != 16U ||
		view.quota_defaults_owner_id != 1U ||
		view.quota_first_user_owner_id != 0x100U ||
		view.quota_first_user_sid_length != 16U ||
		view.quota_defaults_version != 2U ||
		view.quota_first_user_version != 2U ||
		view.quota_defaults_flags != 1U ||
		view.quota_first_user_flags != 1U ||
		view.index[RH_SYSTEM_INDEX_REPARSE_R].entries_examined !=
			expected_indexed ||
		view.index[RH_SYSTEM_INDEX_OBJID_O].entries_examined !=
			expected_indexed ||
		view.index[RH_SYSTEM_INDEX_QUOTA_O].entries_examined != 1U ||
		view.index[RH_SYSTEM_INDEX_QUOTA_Q].entries_examined != 2U ||
		view.index[RH_SYSTEM_INDEX_REPARSE_R].end_entries_examined != 1U ||
		view.index[RH_SYSTEM_INDEX_OBJID_O].end_entries_examined != 1U ||
		view.index[RH_SYSTEM_INDEX_QUOTA_O].end_entries_examined != 1U ||
		view.index[RH_SYSTEM_INDEX_QUOTA_Q].end_entries_examined != 1U ||
		!view.index[RH_SYSTEM_INDEX_REPARSE_R].clean ||
		!view.index[RH_SYSTEM_INDEX_OBJID_O].clean ||
		!view.index[RH_SYSTEM_INDEX_QUOTA_O].clean ||
		!view.index[RH_SYSTEM_INDEX_QUOTA_Q].clean ||
		view.index[RH_SYSTEM_INDEX_REPARSE_R].large ||
		view.index[RH_SYSTEM_INDEX_OBJID_O].large ||
		view.index[RH_SYSTEM_INDEX_QUOTA_O].large ||
		view.index[RH_SYSTEM_INDEX_QUOTA_Q].large ||
		view.reparse_reference_count != expected_indexed ||
		view.objid_reference_count != expected_indexed ||
		view.quota_source_reference_count || writer.operation_count) {
		fprintf(stderr, "release gate mismatch complete=%u auth=%u/%u/%u "
			"facts=%zu/%zu/%zu entries=%llu/%llu/%llu/%llu "
			"end=%llu/%llu/%llu/%llu clean=%u/%u/%u/%u ops=%zu "
			"raw=%u/%u/%u/%u slots=%llu/%llu bad=%llu/%llu "
			"ext=%llu/%llu runs=%llu/%llu gen=%llx/%llx errno=%d\n",
			view.complete, view.reparse_authority_complete,
			view.objid_authority_complete, view.quota_authority_complete,
			view.reparse_count, view.objid_count, view.quota_count,
			(unsigned long long)view.index[1].entries_examined,
			(unsigned long long)view.index[2].entries_examined,
			(unsigned long long)view.index[3].entries_examined,
			(unsigned long long)view.index[4].entries_examined,
			(unsigned long long)view.index[1].end_entries_examined,
			(unsigned long long)view.index[2].end_entries_examined,
			(unsigned long long)view.index[3].end_entries_examined,
			(unsigned long long)view.index[4].end_entries_examined,
			view.index[1].clean, view.index[2].clean,
			view.index[3].clean, view.index[4].clean,
			writer.operation_count, raw.records_complete, raw.records_bounded,
			raw.layout_complete, raw.attribute_lists_complete,
			(unsigned long long)raw.slots_completed,
			(unsigned long long)raw.slots_expected,
			(unsigned long long)raw.unreadable_records,
			(unsigned long long)raw.invalid_records,
			(unsigned long long)raw.extents_completed,
			(unsigned long long)raw.extents_expected,
			(unsigned long long)raw.runs_completed,
			(unsigned long long)raw.runs_expected,
			(unsigned long long)raw.generation,
			(unsigned long long)generation, errno);
		fprintf(stderr, "raw_more ext_complete=%u hash0=%d slots24_26=%u:%u/%u:%u/%u:%u count=%zu\n",
			raw.extents_complete,
			!memcmp(raw.census_hash, (unsigned char[32]){ 0 }, 32U),
			raw.slots[24].state, raw.slots[24].sequence,
			raw.slots[25].state, raw.slots[25].sequence,
			raw.slots[26].state, raw.slots[26].sequence, raw.slot_count);
		goto out;
	}
	hex(view.census_hash, census_hash);
	hex(view.reparse_manifest_hash, reparse_hash);
	hex(view.objid_manifest_hash, objid_hash);
	hex(view.quota_manifest_hash, quota_hash);
	printf("raw_system_indexes=green mode=%s reparse_live=%zu reparse_end=1 "
		"objid_live=%zu objid_end=1 quota_o_live=1 quota_o_end=1 "
		"quota_q_live=2 quota_q_end=1 quota_users=1 "
		"si=%llu file_names=%llu attrlists=%llu extents=%llu "
		"refs=%zu/%zu quota_si_refs=0 operations=0 "
		"hash=%s reparse=%s objid=%s quota=%s\n",
		mode, expected_indexed, expected_indexed,
		(unsigned long long)view.standard_information_examined,
		(unsigned long long)view.file_name_links_examined,
		(unsigned long long)raw.attribute_lists,
		(unsigned long long)raw.live_extent_records, expected_indexed,
		expected_indexed, census_hash,
		reparse_hash, objid_hash, quota_hash);
	result = 0;
out:
	rh_free_slot_component_seal_destroy(reparse_seal);
	rh_free_slot_component_seal_destroy(objid_seal);
	rh_system_index_census_destroy(census);
	rh_index_bitmap_census_destroy(&i30_census);
	rh_namespace_census_release(&namespace_census);
	rh_raw_mft_census_release(&raw);
	if (mounted)
		rh_census_device_unmount(&device);
	if (opened)
		rh_writer_close(&writer);
	if (result)
		perror("roothealth system indexes release");
	return result;
}
