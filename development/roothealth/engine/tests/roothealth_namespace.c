/* ROOTHEALTH_REPAIR_ROLE(DIAGNOSTIC) */
#include "config.h"

#include <errno.h>
#include <stdio.h>
#include <string.h>

#include "device.h"
#include "layout.h"
#include "roothealth_namespace.h"
#include "roothealth_write.h"
#include "volume.h"

static int test_forbidden_collation(struct rh_raw_mft_census *raw)
{
	static const char replacement[] = "LiB64";
	struct rh_namespace_census census;
	struct rh_raw_mft_ref root;
	size_t i, j;
	int found = 0, result = -1;

	memset(&census, 0, sizeof(census));
	if (raw->slot_count <= 5U)
		return -1;
	root.record = 5U;
	root.sequence = raw->slots[5].sequence;
	for (i = 0; i < raw->file_name_count; i++) {
		struct rh_raw_file_name *file_name = &raw->file_names[i];
		unsigned char *value;

		if (file_name->parent.record != root.record ||
				file_name->parent.sequence != root.sequence ||
				file_name->name_length != sizeof(replacement) - 1U)
			continue;
		for (j = 0; j < sizeof(replacement) - 1U; j++)
			if (raw->name_arena[file_name->name_offset + j * 2U] !=
					(unsigned char)"$Boot"[j] ||
					raw->name_arena[file_name->name_offset + j * 2U + 1U])
				break;
		if (j != sizeof(replacement) - 1U)
			continue;
		value = raw->value_arena + file_name->value_arena_offset;
		for (j = 0; j < sizeof(replacement) - 1U; j++) {
			raw->name_arena[file_name->name_offset + j * 2U] =
				(unsigned char)replacement[j];
			value[offsetof(FILE_NAME_ATTR, file_name) + j * 2U] =
				(unsigned char)replacement[j];
			value[offsetof(FILE_NAME_ATTR, file_name) + j * 2U + 1U] = 0;
		}
		rh_sha256(value, file_name->value_length, file_name->value_hash);
		rh_sha256(value, offsetof(FILE_NAME_ATTR, file_name_length),
			file_name->logical_link_hash);
		found = 1;
		break;
	}
	if (!found || rh_namespace_census_run(raw, 7U, &census) ||
			rh_namespace_check_t1os_identity(raw, &census) ||
			census.identity != RH_T1OS_IDENTITY_MISSING ||
			census.forbidden_root_names_expected != 18U ||
			census.forbidden_root_children_matched != 1U)
		goto out;
	result = 0;
out:
	rh_namespace_census_release(&census);
	return result;
}

static int scan(const char *path, uint64_t slots, uint64_t nodes,
		uint64_t links, enum rh_t1os_identity_result identity,
		uint64_t referenced_record, int expect_referenced,
		int expect_reciprocity, int test_forbidden)
{
	struct rh_writer writer;
	struct rh_raw_mft_census raw;
	struct rh_namespace_census first, repeat;
	ntfs_volume *volume = NULL;
	int referenced = -1;
	int result = -1;

	memset(&raw, 0, sizeof(raw));
	memset(&first, 0, sizeof(first));
	memset(&repeat, 0, sizeof(repeat));
	if (rh_writer_open(&writer, path))
		return -1;
	volume = ntfs_mount(path, NTFS_MNT_RDONLY | NTFS_MNT_FORENSIC |
		NTFS_MNT_FS_NO_REPAIR);
	if (!volume || !NDevReadOnly(volume->dev) ||
			rh_raw_mft_census_run(volume, &writer, 1, &raw) ||
			rh_namespace_census_run(&raw, 1, &first) ||
			!first.graph_bounded || !first.graph_complete ||
			first.live_nodes_expected != nodes ||
			first.live_nodes_completed != nodes ||
			first.links_expected != links || first.links_completed != links ||
			first.orphan_nodes || first.unresolved_parents || first.cycles ||
			first.aliases || raw.slots_expected != slots ||
			rh_namespace_i30_census_run(volume, &writer, &raw, &first) ||
			!first.i30_complete ||
			first.reciprocity_complete != expect_reciprocity ||
			first.i30_edge_count != links ||
			rh_namespace_check_t1os_identity(&raw, &first) ||
			first.identity != identity ||
			first.identity_required_expected != 6U ||
			first.identity_required_completed !=
				(identity == RH_T1OS_IDENTITY_MATCH ? 6U : 0U) ||
			first.forbidden_root_names_expected != 18U ||
			first.forbidden_root_children_matched ||
			(expect_reciprocity ?
			 rh_namespace_complete_record_referenced(&first, referenced_record,
				&referenced) :
			 rh_namespace_raw_link_record_referenced(&first, referenced_record,
				&referenced)) || referenced != expect_referenced ||
			rh_namespace_census_run(&raw, 99, &repeat) ||
			rh_namespace_i30_census_run(volume, &writer, &raw, &repeat) ||
			rh_namespace_check_t1os_identity(&raw, &repeat) ||
			memcmp(first.graph_hash, repeat.graph_hash, 32) ||
			memcmp(first.manifest_hash, repeat.manifest_hash, 32) ||
			memcmp(first.identity_hash, repeat.identity_hash, 32) ||
			memcmp(first.census_hash, repeat.census_hash, 32) ||
			(test_forbidden && test_forbidden_collation(&raw)) ||
			writer.write_boundaries)
		goto out;
	printf("raw-namespace slots=%llu nodes=%llu links=%llu i30=%zu "
		"reciprocal=%d cached-differences=%llu posix-collisions=%llu "
		"directories=%llu/%llu indexes=%llu/%llu "
		"blocks=%llu/%llu/%llu bitmap-bits=%llu "
		"reachable=%llu identity=%u "
		"referenced[%llu]=%d "
		"canonical-generation=1 writes=0\n",
		(unsigned long long)slots, (unsigned long long)nodes,
		(unsigned long long)links, first.i30_edge_count, expect_reciprocity,
		(unsigned long long)first.cached_file_name_differences,
		(unsigned long long)first.posix_case_collisions,
		(unsigned long long)first.i30_directories_completed,
		(unsigned long long)first.i30_directories_expected,
		(unsigned long long)first.i30_indexes_completed,
		(unsigned long long)first.i30_indexes_expected,
		(unsigned long long)first.i30_blocks_reachable,
		(unsigned long long)first.i30_blocks_examined,
		(unsigned long long)first.i30_blocks_expected,
		(unsigned long long)first.i30_bitmap_bits_examined,
		(unsigned long long)first.reachable_nodes, first.identity,
		(unsigned long long)referenced_record, referenced);
	printf("namespace-hashes graph=");
	for (size_t digest_index = 0; digest_index < 32U; digest_index++)
		printf("%02x", first.graph_hash[digest_index]);
	printf(" reciprocity=");
	for (size_t digest_index = 0; digest_index < 32U; digest_index++)
		printf("%02x", first.reciprocity_hash[digest_index]);
	printf(" census=");
	for (size_t digest_index = 0; digest_index < 32U; digest_index++)
		printf("%02x", first.census_hash[digest_index]);
	printf("\n");
	result = 0;
out:
	if (result)
		fprintf(stderr, "namespace scan failed for %s: errno=%d "
			"nodes=%llu/%llu links=%llu/%llu reachable=%llu orphan=%llu "
			"unresolved=%llu cycles=%llu aliases=%llu posix=%llu complete=%u "
			"i30=%u/%u edges=%zu identity=%u required=%llu/%llu "
			"forbidden=%llu/%llu referenced=%d writes=%llu "
			"repeat-hashes=%d/%d/%d/%d\n",
			path, errno, (unsigned long long)first.live_nodes_completed,
			(unsigned long long)first.live_nodes_expected,
			(unsigned long long)first.links_completed,
			(unsigned long long)first.links_expected,
			(unsigned long long)first.reachable_nodes,
			(unsigned long long)first.orphan_nodes,
			(unsigned long long)first.unresolved_parents,
			(unsigned long long)first.cycles,
			(unsigned long long)first.aliases,
			(unsigned long long)first.posix_case_collisions,
			first.graph_complete, first.i30_complete,
			first.reciprocity_complete, first.i30_edge_count, first.identity,
			(unsigned long long)first.identity_required_completed,
			(unsigned long long)first.identity_required_expected,
			(unsigned long long)first.forbidden_root_children_matched,
			(unsigned long long)first.forbidden_root_children_examined,
			referenced, (unsigned long long)writer.write_boundaries,
			memcmp(first.graph_hash, repeat.graph_hash, 32),
			memcmp(first.manifest_hash, repeat.manifest_hash, 32),
			memcmp(first.identity_hash, repeat.identity_hash, 32),
			memcmp(first.census_hash, repeat.census_hash, 32));
	if (result) {
		size_t slot_index;
		if (first.i30_complete && !first.reciprocity_complete) {
			size_t edge_index, limit = first.link_count < first.i30_edge_count ?
				first.link_count : first.i30_edge_count;
			for (edge_index = 0; edge_index < limit; edge_index++)
				if (first.links[edge_index].file_name_value_length !=
						first.i30_edges[edge_index].key_length ||
						memcmp(first.links[edge_index].reciprocity_value_hash,
							first.i30_edges[edge_index].reciprocity_value_hash,
							32U)) {
					size_t byte_index, byte_limit =
						first.links[edge_index].file_name_value_length <
						first.i30_edges[edge_index].key_length ?
						first.links[edge_index].file_name_value_length :
						first.i30_edges[edge_index].key_length;
					for (byte_index = 0; byte_index < byte_limit; byte_index++)
						if (first.file_name_value_arena[
								first.links[edge_index].file_name_value_offset +
								byte_index] != first.i30_value_arena[
								first.i30_edges[edge_index].file_name_value_offset +
								byte_index])
							break;
					fprintf(stderr, "  reciprocity[%zu] child=%llu:%u/%llu:%u "
						"parent=%llu:%u/%llu:%u key=%u/%u "
						"hash=%02x%02x%02x%02x/%02x%02x%02x%02x "
						"first-diff=%zu:%02x/%02x\n",
						edge_index,
						(unsigned long long)first.links[edge_index].owner.record,
						first.links[edge_index].owner.sequence,
						(unsigned long long)first.i30_edges[edge_index].child.record,
						first.i30_edges[edge_index].child.sequence,
						(unsigned long long)first.links[edge_index].parent.record,
						first.links[edge_index].parent.sequence,
						(unsigned long long)first.i30_edges[edge_index].parent.record,
						first.i30_edges[edge_index].parent.sequence,
						first.links[edge_index].file_name_value_length,
						first.i30_edges[edge_index].key_length,
						first.links[edge_index].file_name_value_hash[0],
						first.links[edge_index].file_name_value_hash[1],
						first.links[edge_index].file_name_value_hash[2],
						first.links[edge_index].file_name_value_hash[3],
						first.i30_edges[edge_index].file_name_value_hash[0],
						first.i30_edges[edge_index].file_name_value_hash[1],
						first.i30_edges[edge_index].file_name_value_hash[2],
						first.i30_edges[edge_index].file_name_value_hash[3],
						byte_index,
						byte_index < first.links[edge_index].file_name_value_length ?
						first.file_name_value_arena[
							first.links[edge_index].file_name_value_offset +
							byte_index] : 0U,
						byte_index < first.i30_edges[edge_index].key_length ?
						first.i30_value_arena[
							first.i30_edges[edge_index].file_name_value_offset +
							byte_index] : 0U);
					break;
				}
		}
		for (slot_index = 0; slot_index < raw.slot_count; slot_index++)
			if (raw.slots[slot_index].state == RH_RAW_SLOT_LIVE_BASE &&
					raw.slots[slot_index].link_count !=
					raw.slots[slot_index].owned_file_name_count)
				fprintf(stderr, "  slot[%zu] links=%u fn=%zu flags=%x\n",
					slot_index, raw.slots[slot_index].link_count,
					raw.slots[slot_index].owned_file_name_count,
					raw.slots[slot_index].flags);
	}
	rh_namespace_census_release(&repeat);
	rh_namespace_census_release(&first);
	rh_raw_mft_census_release(&raw);
	if (volume && ntfs_umount(volume, FALSE) && !result)
		result = -1;
	rh_writer_close(&writer);
	return result;
}

int main(int argc, char **argv)
{
	static const char *const forbidden[] = {
		"bin", "dev", "etc", "home", "lib", "lib64", "media", "mnt",
		"opt", "proc", "root", "run", "sbin", "srv", "sys", "tmp",
		"usr", "var",
	};
	size_t i;

	if (argc == 3 && !strcmp(argv[1], "--release"))
		return scan(argv[2], 23112U, 22739U, 22980U,
			RH_T1OS_IDENTITY_MATCH, 0U, 1, 1, 0) ? 1 : 0;
	if (argc != 3 && argc != 4)
		return 5;
	if (rh_namespace_forbidden_root_name_count() !=
			sizeof(forbidden) / sizeof(forbidden[0]))
		return 1;
	for (i = 0; i < sizeof(forbidden) / sizeof(forbidden[0]); i++)
		if (!rh_namespace_forbidden_root_name(i) ||
				strcmp(rh_namespace_forbidden_root_name(i), forbidden[i]))
			return 1;
	if (rh_namespace_forbidden_root_name(i))
		return 1;
	if (scan(argv[1], 27U, 19U, 15U, RH_T1OS_IDENTITY_MISSING,
			27U, 0, 1, 1) ||
			scan(argv[2], 82U, 37U, 33U, RH_T1OS_IDENTITY_MATCH,
			81U, 1, 1, 0) ||
			(argc == 4 && scan(argv[3], 80U, 20U, 18U,
				RH_T1OS_IDENTITY_MISSING, 64U, 1, 1, 0)))
		return 1;
	return 0;
}
