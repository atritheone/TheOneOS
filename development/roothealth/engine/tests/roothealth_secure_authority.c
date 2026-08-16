#include "config.h"

#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "roothealth_secure.h"

void *__real_malloc(size_t size);

static int fail_identity_allocation;
static size_t identity_allocation_size;

void *__wrap_malloc(size_t size)
{
	if (fail_identity_allocation && size == identity_allocation_size) {
		errno = ENOMEM;
		return NULL;
	}
	return __real_malloc(size);
}

static void fact(const char *name, unsigned char hash[32])
{
	rh_sha256(name, strlen(name), hash);
}

static void complete_census(struct rh_secure_census *census,
		const uint32_t *ids, size_t count)
{
	memset(census, 0, sizeof(*census));
	census->view = RH_SECURE_PRETRANSACTION;
	census->ledger_format = RH_SECURE_LEDGER_FORMAT;
	census->generation = 7;
	census->volume_serial = 9;
	census->coverage_complete = 1;
	census->identity_bound = 1;
	census->no_io_uncertainty = 1;
	census->complete_mft_census = 1;
	census->complete_attribute_census = 1;
	census->complete_runlist_census = 1;
	census->complete_namespace_census = 1;
	census->complete_index_census = 1;
	census->complete_security_descriptor_census = 1;
	census->complete_security_id_census = 1;
	census->namespace_security_reciprocity_complete = 1;
	census->global_security_identity_complete = 1;
	census->sole_valid_peer_authority_complete = 1;
	census->no_conflicting_valid_authorities = 1;
	census->target_ownership_exact = 1;
	census->targets_outside_wal = 1;
	census->data_preserving = 1;
	census->mft_records_expected = census->mft_records_examined = 16;
	census->attributes_expected = census->attributes_examined = 32;
	census->runs_expected = census->runs_examined = 4;
	census->namespace_links_expected = census->namespace_links_examined = 1;
	census->namespace_links_reciprocal = 1;
	census->security_descriptors_expected =
		census->security_descriptors_examined = count;
	census->security_ids_expected = census->security_ids_examined = count;
	census->security_id_references_expected =
		census->security_id_references_examined =
		census->security_id_references_resolved = count;
	census->live_security_id_count = count;
	census->live_security_ids = ids;
	fact("coverage", census->coverage_ledger_hash);
	fact("identity", census->identity_graph_hash);
	fact("namespace", census->namespace_security_hash);
	fact("use", census->security_id_use_hash);
	fact("global", census->global_security_hash);
	fact("manifest", census->descriptor_manifest_hash);
}

int main(void)
{
	struct rh_secure_census census;
	struct rh_secure_authority authority;
	uint32_t *ids;
	const size_t count = 5000U;
	uint32_t dummy = 0x100U;

	ids = malloc(count * sizeof(*ids));
	if (!ids)
		return 1;
	for (size_t i = 0; i < count; i++)
		ids[i] = 0x100U + (uint32_t)i;
	memset(&authority, 0, sizeof(authority));
	complete_census(&census, ids, count);
	if (rh_secure_authority_seal(&census, &authority) ||
			!rh_secure_authority_valid(&authority,
				RH_SECURE_PRETRANSACTION, 9,
				census.descriptor_manifest_hash))
		return 1;
	rh_secure_authority_destroy(&authority);
	complete_census(&census, &dummy, SIZE_MAX / sizeof(uint32_t) + 1U);
	if (!rh_secure_authority_seal(&census, &authority) || errno != EPERM)
		return 1;
	complete_census(&census, ids, count);
	identity_allocation_size = count * sizeof(*ids);
	fail_identity_allocation = 1;
	errno = 0;
	if (!rh_secure_authority_seal(&census, &authority) || errno != ENOMEM ||
			authority.owned_live_security_ids || authority.version)
		return 1;
	fail_identity_allocation = 0;
	free(ids);
	printf("dynamic_security_ids=%zu overflow=refused oom=closed\n", count);
	return 0;
}
