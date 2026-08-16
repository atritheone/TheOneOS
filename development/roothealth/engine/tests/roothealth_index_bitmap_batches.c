/* ROOTHEALTH_REPAIR_ROLE(DIAGNOSTIC) */
#include "config.h"

#include <stdio.h>
#include <string.h>

#include "roothealth_index_bitmap.h"

int main(void)
{
	struct rh_index_bitmap_census census;
	size_t first, second, final;

	memset(&census, 0, sizeof(census));
	census.change_count = 9001U;
	if (rh_index_bitmap_next_batch_count(&census, 5000U) != 4094U)
		return 1;
	first = rh_index_bitmap_next_batch_count(&census, 4092U);
	census.change_count -= first;
	second = rh_index_bitmap_next_batch_count(&census, 4094U);
	census.change_count -= second;
	final = rh_index_bitmap_next_batch_count(&census, 4094U);
	if (first != 4092U || second != 4094U || final != 815U ||
			first + second + final != 9001U ||
			rh_index_bitmap_next_batch_count(&census, 0U) != 0U)
		return 1;
	printf("index-batches differences=9001 first-with-dirty-pair=%zu "
		"middle=%zu final=%zu cumulative=9001 "
		"overflow-is-not-filesystem-corruption=1\n", first, second, final);
	return 0;
}
