
#ifndef ROOTHEALTH_REPORT_H
#define ROOTHEALTH_REPORT_H

#include <stddef.h>
#include <sys/types.h>

#define RH_REPORT_LIMIT (4U * 1024U * 1024U)

/*
 * The report is reserved before the target is opened.  Until publish succeeds
 * it is deliberately a zero-filled, invalid JSON file.  This means an abrupt
 * power loss can leave an incomplete file, but never a false success report.
 */
struct rh_report {
	int fd;
	int directory_fd;
	char *path;
	char *name;
	char *buffer;
	size_t capacity;
	size_t used;
	int created;
	int identity_bound;
	dev_t created_dev;
	ino_t created_ino;
};

int rh_report_prepare(struct rh_report *report, const char *path);
int rh_report_append(struct rh_report *report, const void *data, size_t length);
int rh_report_appendf(struct rh_report *report, const char *format, ...)
	__attribute__((format(printf, 2, 3)));
int rh_report_json_string(struct rh_report *report, const char *text);
int rh_report_publish(struct rh_report *report);
int rh_report_abort(struct rh_report *report);

#ifdef ROOTHEALTH_REPORT_TEST_HOOKS
void rh_report_test_fail_first_created_fstat(void);
#endif

#endif
