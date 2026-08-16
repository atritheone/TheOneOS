#include "config.h"

#include <stdio.h>
#include <string.h>

#include "roothealth_bitmap.h"

static int authorize_all(const struct rh_writer *writer,
		const struct rh_policy_evidence *evidence, size_t first,
		size_t count)
{
	const struct rh_policy_definition *problem;
	const struct rh_policy_definition *aggregate;
	struct rh_policy_authorization authorization;
	size_t i;

	problem = rh_policy_problem(PR_CLUSTER_BITMAP_MISMATCH);
	aggregate = rh_policy_aggregate("CLUSTER_BITMAP");
	if (!problem || !aggregate || rh_policy_evidence_target_count(evidence) != count)
		return -1;
	for (i = 0; i < count; i++) {
		if (rh_policy_authorize_operation(problem, evidence, i, writer,
				first + i, &authorization) != RH_POLICY_FINAL_AUTHORIZED ||
				authorization.target.action_kind != RH_WRITE_BITMAP_CLUSTER ||
				rh_policy_authorize_operation(aggregate, evidence, i, writer,
				first + i, &authorization) != RH_POLICY_FINAL_AUTHORIZED)
			return -1;
	}
	return 0;
}

int main(int argc, char **argv)
{
	struct rh_writer writer;
	struct rh_ntfs_overlay overlay;
	struct rh_cluster_bitmap_census initial;
	struct rh_cluster_bitmap_census final;
	struct rh_policy_evidence *evidence = NULL;
	size_t first = 0;
	int result = 1;

	memset(&initial, 0, sizeof(initial));
	memset(&final, 0, sizeof(final));
	if (argc != 2)
		return 5;
	if (rh_writer_open(&writer, argv[1]))
		return 3;
	if (rh_ntfs_overlay_mount(&overlay, &writer, 0))
		goto out_writer;
	if (rh_cluster_bitmap_census_run(overlay.volume, &writer, 1, &initial) ||
			initial.change_count != 1 || initial.clean ||
			rh_cluster_bitmap_stage(&overlay, &initial, &first) || first != 1 ||
			writer.operation_count != 1 ||
			rh_cluster_bitmap_census_run(overlay.volume, &writer, 2, &final) ||
			!final.clean || final.change_count ||
			rh_cluster_bitmap_seal_policy(&initial, &final, &writer, first, 1,
				&evidence) ||
			authorize_all(&writer, evidence, first, initial.change_count))
		goto out_evidence;
	printf("bitmap-plan operations=%zu kind=%u offset=%llu before=%02x "
		"after=%02x source_writes=%zu final_clean=%d authorized=2\n",
		writer.operation_count,
		RH_WRITE_ACTION_ID(writer.operations[0].kind),
		(unsigned long long)writer.operations[0].offset,
		writer.operations[0].before[0], writer.operations[0].after[0],
		writer.write_boundaries, final.clean);
	result = 0;
out_evidence:
	rh_policy_evidence_destroy(evidence);
	rh_cluster_bitmap_census_destroy(&final);
	rh_cluster_bitmap_census_destroy(&initial);
	rh_ntfs_overlay_unmount(&overlay);
out_writer:
	rh_writer_close(&writer);
	return result;
}
