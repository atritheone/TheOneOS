
/* ROOTHEALTH_REPAIR_ROLE(REPORT) ROOTHEALTH_IO_ROLE(REPORT) */
#include "config.h"

#include <errno.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

#include "roothealth_report.h"

#ifdef ROOTHEALTH_REPORT_TEST_HOOKS
static int rh_report_test_first_created_fstat_failure;

void rh_report_test_fail_first_created_fstat(void)
{
	rh_report_test_first_created_fstat_failure = 1;
}
#endif

#ifndef O_CLOEXEC
#error "roothealth requires O_CLOEXEC"
#endif
#ifndef O_NOFOLLOW
#error "roothealth requires O_NOFOLLOW"
#endif

static void rh_report_release(struct rh_report *report)
{
	if (!report)
		return;
	if (report->fd >= 0)
		close(report->fd);
	report->fd = -1;
	if (report->directory_fd >= 0)
		close(report->directory_fd);
	report->directory_fd = -1;
	free(report->buffer);
	report->buffer = NULL;
	free(report->path);
	report->path = NULL;
	free(report->name);
	report->name = NULL;
	report->capacity = 0;
	report->used = 0;
	report->created = 0;
	report->identity_bound = 0;
}

static int rh_report_name_matches(const struct rh_report *report)
{
	struct stat st;

	if (!report || report->directory_fd < 0 || !report->name ||
			fstatat(report->directory_fd, report->name, &st,
				AT_SYMLINK_NOFOLLOW))
		return -1;
	if (!S_ISREG(st.st_mode) || st.st_dev != report->created_dev ||
			st.st_ino != report->created_ino || st.st_nlink != 1) {
		errno = ESTALE;
		return -1;
	}
	return 0;
}

static int rh_fstat_retry(int fd, struct stat *st)
{
	int result;
	do {
		result = fstat(fd, st);
	} while (result && errno == EINTR);
	return result;
}

static int rh_report_unlink_created(struct rh_report *report)
{
	struct stat st;

	if (!report || !report->created)
		return 0;
	/*
	 * O_EXCL proves that this descriptor created a new inode, but it does not
	 * make the pathname safe to unlink after a rename/replacement race.  If
	 * the first post-open fstat failed, bind the descriptor identity here
	 * while it is still open, then use the same name/identity proof as every
	 * other cleanup path.
	 */
	if (!report->identity_bound) {
		if (report->fd < 0 || rh_fstat_retry(report->fd, &st))
			return -1;
		if (!S_ISREG(st.st_mode) || st.st_nlink != 1) {
			errno = ESTALE;
			return -1;
		}
		report->created_dev = st.st_dev;
		report->created_ino = st.st_ino;
		report->identity_bound = 1;
	}
	if (rh_report_name_matches(report))
		return -1;
	if (unlinkat(report->directory_fd, report->name, 0))
		return -1;
	report->created = 0;
	return 0;
}

int rh_report_prepare(struct rh_report *report, const char *path)
{
	struct stat directory_st, st;
	char *directory = NULL;
	const char *slash;
	int error;

	if (!report || !path || path[0] != '/') {
		errno = EINVAL;
		return -1;
	}
	memset(report, 0, sizeof(*report));
	report->fd = -1;
	report->directory_fd = -1;
	slash = strrchr(path, '/');
	if (!slash || !slash[1] || !strcmp(slash + 1, ".") ||
			!strcmp(slash + 1, "..")) {
		errno = EINVAL;
		return -1;
	}
	directory = slash == path ? strdup("/") :
		strndup(path, (size_t)(slash - path));
	/* All memory needed for publication is committed before the target opens. */
	report->buffer = malloc(RH_REPORT_LIMIT);
	report->path = strdup(path);
	report->name = strdup(slash + 1);
	if (!directory || !report->buffer || !report->path || !report->name)
		goto fail;
	report->directory_fd = open(directory,
		O_RDONLY | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW);
	free(directory);
	directory = NULL;
	if (report->directory_fd < 0)
		goto fail;
	if (rh_fstat_retry(report->directory_fd, &directory_st))
		goto fail;
	if (!S_ISDIR(directory_st.st_mode) || directory_st.st_uid != 0 ||
			(directory_st.st_mode & 022) != 0) {
		errno = EPERM;
		goto fail;
	}
	report->capacity = RH_REPORT_LIMIT;
	report->fd = openat(report->directory_fd, report->name,
		O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW, 0600);
	if (report->fd < 0)
		goto fail;
	report->created = 1;
#ifdef ROOTHEALTH_REPORT_TEST_HOOKS
	if (rh_report_test_first_created_fstat_failure) {
		rh_report_test_first_created_fstat_failure = 0;
		errno = EIO;
		goto fail;
	}
#endif
	if (rh_fstat_retry(report->fd, &st))
		goto fail;
	if (!S_ISREG(st.st_mode) || st.st_nlink != 1) {
		errno = EINVAL;
		goto fail;
	}
	report->created_dev = st.st_dev;
	report->created_ino = st.st_ino;
	report->identity_bound = 1;
	if (fchmod(report->fd, 0600) || rh_fstat_retry(report->fd, &st))
		goto fail;
	if (st.st_dev != report->created_dev ||
			st.st_ino != report->created_ino || st.st_nlink != 1 ||
			(st.st_mode & 0777) != 0600) {
		errno = EINVAL;
		goto fail;
	}
	/* A late ENOSPC after a committed repair is not an acceptable design. */
	error = posix_fallocate(report->fd, 0, (off_t)RH_REPORT_LIMIT);
	if (error) {
		errno = error;
		goto fail;
	}
	return 0;
fail:
	error = errno ? errno : EIO;
	free(directory);
	/* Keep the descriptor open until an unbound created inode is identified. */
	if (report->created)
		(void)rh_report_unlink_created(report);
	rh_report_release(report);
	errno = error;
	return -1;
}

int rh_report_append(struct rh_report *report, const void *data, size_t length)
{
	if (!report || !report->buffer || (!data && length) ||
		length > report->capacity - report->used) {
		errno = EOVERFLOW;
		return -1;
	}
	memcpy(report->buffer + report->used, data, length);
	report->used += length;
	return 0;
}

int rh_report_appendf(struct rh_report *report, const char *format, ...)
{
	va_list ap;
	int length;
	size_t available;

	if (!report || !report->buffer || !format) {
		errno = EINVAL;
		return -1;
	}
	available = report->capacity - report->used;
	va_start(ap, format);
	length = vsnprintf(report->buffer + report->used, available, format, ap);
	va_end(ap);
	if (length < 0)
		return -1;
	if ((size_t)length >= available) {
		errno = EOVERFLOW;
		return -1;
	}
	report->used += (size_t)length;
	return 0;
}

int rh_report_json_string(struct rh_report *report, const char *text)
{
	const unsigned char *p = (const unsigned char *)(text ? text : "");

	if (rh_report_append(report, "\"", 1))
		return -1;
	while (*p) {
		char escape[7];
		if (*p == '\\' || *p == '"') {
			escape[0] = '\\';
			escape[1] = (char)*p++;
			if (rh_report_append(report, escape, 2))
				return -1;
		} else if (*p < 0x20) {
			int length = snprintf(escape, sizeof(escape), "\\u%04x", *p++);
			if (length != 6 || rh_report_append(report, escape, 6))
				return -1;
		} else {
			unsigned char ch = *p++;
			if (rh_report_append(report, &ch, 1))
				return -1;
		}
	}
	return rh_report_append(report, "\"", 1);
}

static int rh_report_pwrite_all(int fd, const void *data, size_t length,
		off_t offset)
{
	const unsigned char *p = data;

	while (length) {
		ssize_t result = pwrite(fd, p, length, offset);
		if (result < 0) {
			if (errno == EINTR)
				continue;
			return -1;
		}
		if (!result) {
			errno = EIO;
			return -1;
		}
		p += result;
		length -= (size_t)result;
		offset += result;
	}
	return 0;
}

int rh_report_publish(struct rh_report *report)
{
	int error;

	if (!report) {
		errno = EINVAL;
		return -1;
	}
	if (report->fd < 0 || !report->created || !report->used ||
			report->used > RH_REPORT_LIMIT) {
		errno = EINVAL;
		if (report->created)
			goto fail;
		return -1;
	}
	if (rh_report_name_matches(report) ||
		rh_report_pwrite_all(report->fd, report->buffer, report->used, 0) ||
		ftruncate(report->fd, (off_t)report->used) || fdatasync(report->fd) ||
		rh_report_name_matches(report))
		goto fail;
	if (close(report->fd)) {
		report->fd = -1;
		goto fail;
	}
	report->fd = -1;
	rh_report_release(report);
	return 0;
fail:
	error = errno ? errno : EIO;
	/* Identity-check and unlink while the created descriptor is still open. */
	(void)rh_report_unlink_created(report);
	rh_report_release(report);
	errno = error;
	return -1;
}

int rh_report_abort(struct rh_report *report)
{
	int cleanup_error = 0;
	int primary_error = errno;

	if (!report) {
		errno = EINVAL;
		return -1;
	}
	if (rh_report_unlink_created(report))
		cleanup_error = errno ? errno : EIO;
	rh_report_release(report);
	errno = primary_error ? primary_error : cleanup_error;
	return cleanup_error ? -1 : 0;
}
