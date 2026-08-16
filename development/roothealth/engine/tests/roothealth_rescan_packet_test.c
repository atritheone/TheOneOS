
#include "config.h"

#include <stdio.h>

#include "roothealth_orchestrator.h"

struct packet_case {
	int result;
	int completed;
	int identity_valid;
	int logfile_clean_known;
	int logfile_clean;
	int native_state;
};

int main(void)
{
	static const struct packet_case positive[] = {
		{ RH_RESULT_OK, 1, 1, 1, 1, RH_NATIVE_LOG_CLEAN_RESTART },
		{ RH_RESULT_OK, 1, 1, 1, 1, RH_NATIVE_LOG_EMPTY_T1OS },
		{ RH_RESULT_UNSAFE, 1, 1, 1, 0, -1 },
		{ RH_RESULT_WRONG_ROOT, 1, 0, 0, 0, 0 },
		{ RH_RESULT_UNSAFE, 1, 1, 1, 1, RH_NATIVE_LOG_CLEAN_RESTART },
		{ RH_RESULT_IO, 0, 1, 0, 0, 0 },
	};
	static const struct packet_case negative[] = {
		{ RH_RESULT_OK, 0, 1, 1, 1, RH_NATIVE_LOG_CLEAN_RESTART },
		{ RH_RESULT_OK, 1, 0, 1, 1, RH_NATIVE_LOG_CLEAN_RESTART },
		{ RH_RESULT_OK, 1, 1, 0, 1, RH_NATIVE_LOG_CLEAN_RESTART },
		{ RH_RESULT_OK, 1, 1, 1, 0, RH_NATIVE_LOG_CLEAN_RESTART },
		{ RH_RESULT_OK, 1, 1, 1, 0, RH_NATIVE_LOG_REPLAY_PLANNED },
		{ RH_RESULT_OK, 1, 1, 0, 0, 0 },
		{ RH_RESULT_UNSAFE, 2, 0, 0, 0, 0 },
		{ 99, 1, 0, 0, 0, 0 },
		{ RH_RESULT_UNSAFE, 1, 0, 0, 0, 99 },
		{ RH_RESULT_UNSAFE, 1, 0, 1, 0, 0 },
		{ RH_RESULT_UNSAFE, 1, 0, 0, 0, RH_NATIVE_LOG_CLEAN_RESTART },
		{ RH_RESULT_UNSAFE, 1, 0, 1, 1, RH_NATIVE_LOG_REPLAY_PLANNED },
	};
	size_t i;

	for (i = 0; i < sizeof(positive) / sizeof(positive[0]); i++)
		if (!rh_orchestrator_test_rescan_semantics(positive[i].result,
				positive[i].completed, positive[i].identity_valid,
				positive[i].logfile_clean_known, positive[i].logfile_clean,
				positive[i].native_state))
			return 1;
	for (i = 0; i < sizeof(negative) / sizeof(negative[0]); i++)
		if (rh_orchestrator_test_rescan_semantics(negative[i].result,
				negative[i].completed, negative[i].identity_valid,
				negative[i].logfile_clean_known, negative[i].logfile_clean,
				negative[i].native_state))
			return 2;
	printf("roothealth-rescan-packet positives=%zu negatives=%zu passed=1\n",
		sizeof(positive) / sizeof(positive[0]),
		sizeof(negative) / sizeof(negative[0]));
	return 0;
}
