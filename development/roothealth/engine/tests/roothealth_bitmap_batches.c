/* ROOTHEALTH_REPAIR_ROLE(DIAGNOSTIC) */
#include "config.h"

#include <stdio.h>
#include <string.h>

#include "roothealth_bitmap.h"
#include "roothealth_mft_bitmap.h"

static int batch_counts(size_t (*next)(const void *, size_t), void *census,
		size_t *change_count)
{
	size_t first, middle, final;

	*change_count = 9001U;
	first = next(census, 4092U);
	*change_count -= first;
	middle = next(census, 4094U);
	*change_count -= middle;
	final = next(census, 4094U);
	return first == 4092U && middle == 4094U && final == 815U &&
		first + middle + final == 9001U;
}

static size_t cluster_next(const void *census, size_t capacity)
{
	return rh_cluster_bitmap_next_batch_count(census, capacity);
}

static size_t mft_next(const void *census, size_t capacity)
{
	return rh_mft_bitmap_next_batch_count(census, capacity);
}

int main(void)
{
	struct rh_cluster_bitmap_census cluster;
	struct rh_mft_bitmap_census mft;

	memset(&cluster, 0, sizeof(cluster));
	memset(&mft, 0, sizeof(mft));
	if (!batch_counts(cluster_next, &cluster, &cluster.change_count) ||
			!batch_counts(mft_next, &mft, &mft.change_count))
		return 1;
	printf("bitmap-batches cluster=9001:4092+4094+815 "
		"mft=9001:4092+4094+815 fresh-rescan-required=1\n");
	return 0;
}
