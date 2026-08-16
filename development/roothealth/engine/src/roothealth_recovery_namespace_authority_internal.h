#ifndef ROOTHEALTH_RECOVERY_NAMESPACE_AUTHORITY_INTERNAL_H
#define ROOTHEALTH_RECOVERY_NAMESPACE_AUTHORITY_INTERNAL_H

struct rh_complete_census;
struct rh_recovery_namespace_authority_census;

/* Owned exclusively by the immutable common-census publisher. */
int rh_recovery_namespace_authority_census_create(
		const struct rh_complete_census *complete,
		struct rh_recovery_namespace_authority_census **output);
void rh_recovery_namespace_authority_census_destroy(
		struct rh_recovery_namespace_authority_census *census);

#endif
