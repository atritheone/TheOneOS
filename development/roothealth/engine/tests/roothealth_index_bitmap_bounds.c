/* ROOTHEALTH_REPAIR_ROLE(DIAGNOSTIC) */
#include "config.h"

#include <errno.h>
#include <stdint.h>
#include <stdio.h>

#include "roothealth_index_bitmap.h"

int main(void)
{
	const uint64_t old_cap_plus_one = UINT64_C(4194305);
	uint64_t slots = 0;

	if (rh_index_bitmap_slot_count_from_initialized(
			old_cap_plus_one * UINT64_C(1024), 1024U, &slots) ||
			slots != old_cap_plus_one)
		return 1;
	if (rh_index_bitmap_test_iterative_frames(64U, 65U))
		return 1;
	errno = 0;
	if (!rh_index_bitmap_test_iterative_frames(64U, 66U) ||
			errno != ELOOP)
		return 1;
	printf("index-bounds slots=%llu old-4m-cap-removed=1 "
		"iterative-depth=65 allocation-block-bound=64 over-bound-refused=1\n",
		(unsigned long long)slots);
	return 0;
}
