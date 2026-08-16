#include <stdio.h>

#include "roothealth_wal.h"

struct order_case {
	const char *name;
	enum rh_wal_transaction_kind transaction_kind;
	enum rh_write_kind kinds[8];
	size_t count;
	int expected;
};

int main(void)
{
	static const struct order_case cases[] = {
		{ "native", RH_WAL_TX_METADATA_REPAIR,
			{ RH_WRITE_LOGFILE_REDO, RH_WRITE_LOGFILE_REDO,
			  RH_WRITE_LOGFILE_RESTART, RH_WRITE_LOGFILE_RESTART }, 4, 1 },
		{ "dirty-native-derived", RH_WAL_TX_METADATA_REPAIR,
			{ RH_WRITE_VOLUME_DIRTY_SET, RH_WRITE_VOLUME_DIRTY_SET,
			  RH_WRITE_LOGFILE_REDO,
			  RH_WRITE_BITMAP_MFT, RH_WRITE_LOGFILE_RESTART,
			  RH_WRITE_LOGFILE_RESTART }, 6, 1 },
		{ "derived-only", RH_WAL_TX_METADATA_REPAIR,
			{ RH_WRITE_INDEX_BITMAP }, 1, 1 },
		{ "bitmap-obligation-prefix", RH_WAL_TX_METADATA_REPAIR,
			{ RH_WRITE_BITMAP_MFT, RH_WRITE_BITMAP_CLUSTER,
			  RH_WRITE_INDEX_BITMAP }, 3, 1 },
		{ "operations-edge-before-bitmap-obligations",
			RH_WAL_TX_METADATA_REPAIR,
			{ RH_WRITE_VOLUME_DIRTY_SET, RH_WRITE_VOLUME_DIRTY_SET,
			  RH_WRITE_INDEX_ROOT, RH_WRITE_BITMAP_MFT,
			  RH_WRITE_BITMAP_CLUSTER }, 5, 1 },
		{ "operations-edge-after-bitmap-obligations",
			RH_WAL_TX_METADATA_REPAIR,
			{ RH_WRITE_BITMAP_MFT, RH_WRITE_INDEX_ROOT }, 2, 0 },
		{ "bitmap-obligation-late", RH_WAL_TX_METADATA_REPAIR,
			{ RH_WRITE_INDEX_BITMAP, RH_WRITE_BITMAP_MFT }, 2, 0 },
		{ "other-derived-before-bitmap-obligation",
			RH_WAL_TX_METADATA_REPAIR,
			{ RH_WRITE_INDEX_ALLOCATION, RH_WRITE_BITMAP_MFT }, 2, 0 },
		{ "foundation-in-wal", RH_WAL_TX_METADATA_REPAIR,
			{ RH_WRITE_MFT_PRIMARY }, 1, 0 },
		{ "redo-after-derived", RH_WAL_TX_METADATA_REPAIR,
			{ RH_WRITE_BITMAP_MFT, RH_WRITE_LOGFILE_REDO,
			  RH_WRITE_LOGFILE_RESTART, RH_WRITE_LOGFILE_RESTART }, 4, 0 },
		{ "lone-restart", RH_WAL_TX_METADATA_REPAIR,
			{ RH_WRITE_LOGFILE_RESTART }, 1, 0 },
		{ "derived-two-restarts", RH_WAL_TX_METADATA_REPAIR,
			{ RH_WRITE_INDEX_BITMAP, RH_WRITE_LOGFILE_RESTART,
			  RH_WRITE_LOGFILE_RESTART }, 3, 0 },
		{ "extra-restart", RH_WAL_TX_METADATA_REPAIR,
			{ RH_WRITE_LOGFILE_RESTART, RH_WRITE_LOGFILE_RESTART,
			  RH_WRITE_LOGFILE_RESTART }, 3, 0 },
		{ "after-restart", RH_WAL_TX_METADATA_REPAIR,
			{ RH_WRITE_LOGFILE_RESTART, RH_WRITE_LOGFILE_RESTART,
			  RH_WRITE_INDEX_ROOT }, 3, 0 },
		{ "dirty-set-not-first", RH_WAL_TX_METADATA_REPAIR,
			{ RH_WRITE_INDEX_ROOT, RH_WRITE_VOLUME_DIRTY_SET }, 2, 0 },
		{ "dirty-set-lone", RH_WAL_TX_METADATA_REPAIR,
			{ RH_WRITE_VOLUME_DIRTY_SET, RH_WRITE_INDEX_ROOT }, 2, 0 },
		{ "dirty-clear", RH_WAL_TX_DIRTY_CLEAR,
			{ RH_WRITE_VOLUME_DIRTY_CLEAR,
			  RH_WRITE_VOLUME_DIRTY_CLEAR }, 2, 1 },
		{ "dirty-clear-lone", RH_WAL_TX_DIRTY_CLEAR,
			{ RH_WRITE_VOLUME_DIRTY_CLEAR }, 1, 0 },
		{ "dirty-clear-mixed", RH_WAL_TX_DIRTY_CLEAR,
			{ RH_WRITE_VOLUME_DIRTY_CLEAR, RH_WRITE_INDEX_BITMAP }, 2, 0 },
	};
	size_t i;

	for (i = 0; i < sizeof(cases) / sizeof(cases[0]); i++) {
		int actual = rh_wal_validate_action_order(cases[i].transaction_kind,
				cases[i].kinds, cases[i].count);
		if (actual != cases[i].expected) {
			fprintf(stderr, "%s: expected %d got %d\n", cases[i].name,
				cases[i].expected, actual);
			return 1;
		}
	}
	printf("wal-order cases=%zu passed=1\n",
		sizeof(cases) / sizeof(cases[0]));
	return 0;
}
