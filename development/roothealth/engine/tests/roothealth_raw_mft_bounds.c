/* ROOTHEALTH_REPAIR_ROLE(DIAGNOSTIC) */
#include "config.h"

#include <errno.h>
#include <stdint.h>
#include <stdio.h>

#include "roothealth_raw_mft.h"

int main(void)
{
	const uint64_t old_cap_plus = UINT64_C(4194304) + 123U;
	const uint64_t profile_max = (UINT64_C(256) << 30) / 1024U;
	size_t count = 0;

	if (rh_raw_mft_slot_count_from_size(old_cap_plus * 1024U, 1024U,
			&count) || count != old_cap_plus ||
			rh_raw_mft_slot_count_from_size(profile_max * 1024U, 1024U,
				&count) || count != profile_max)
		return 1;
	errno = 0;
	if (!rh_raw_mft_slot_count_from_size(1025U, 1024U, &count) ||
			errno != EINVAL)
		return 1;
	printf("raw-mft-bounds old-cap-plus=%llu profile-max-slots=%llu "
		"validity-cap=removed allocation-failure=resource writes=0\n",
		(unsigned long long)old_cap_plus,
		(unsigned long long)profile_max);
	return 0;
}
