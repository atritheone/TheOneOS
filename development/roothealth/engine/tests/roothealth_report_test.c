
#include "config.h"

#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

#include "roothealth_report.h"

static int read_exact_file(const char *path, const char *expected)
{
	char buffer[64];
	int fd;
	ssize_t got;

	fd = open(path, O_RDONLY | O_CLOEXEC);
	if (fd < 0)
		return -1;
	got = read(fd, buffer, sizeof(buffer) - 1);
	if (got < 0 || close(fd))
		return -1;
	buffer[got] = 0;
	return strcmp(buffer, expected) ? -1 : 0;
}

static int is_invalid_zero_reservation(const char *path)
{
	unsigned char buffer[32];
	struct stat st;
	ssize_t got;
	int fd;

	if (stat(path, &st) || !S_ISREG(st.st_mode) ||
			st.st_size != (off_t)RH_REPORT_LIMIT)
		return 0;
	fd = open(path, O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
	if (fd < 0)
		return 0;
	got = read(fd, buffer, sizeof(buffer));
	if (got != (ssize_t)sizeof(buffer) || close(fd))
		return 0;
	for (size_t i = 0; i < sizeof(buffer); i++)
		if (buffer[i] != 0)
			return 0;
	return 1;
}

int main(void)
{
	char directory[] = "/tmp/roothealth-report-test.XXXXXX";
	char report_path[256], existing_path[256], link_path[256];
	char victim_path[256], overflow_path[256], write_fail_path[256];
	char empty_path[256], strict_path[256], race_path[256], moved_path[256];
	char hard_path[256], hard_alias[256], cleanup_fail_path[256];
	char first_fstat_path[256];
	struct rh_report report;
	struct stat st;
	int fd;

	umask(077);
	if (!mkdtemp(directory))
		return 1;
	snprintf(report_path, sizeof(report_path), "%s/report.json", directory);
	if (rh_report_prepare(&report, report_path) ||
			rh_report_append(&report, "{}\n", 3) ||
			rh_report_publish(&report) || stat(report_path, &st) ||
			st.st_size != 3 || (st.st_mode & 0777) != 0600 ||
			read_exact_file(report_path, "{}\n"))
		return 2;

	snprintf(existing_path, sizeof(existing_path), "%s/existing", directory);
	fd = open(existing_path, O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
	if (fd < 0 || write(fd, "sentinel", 8) != 8 || close(fd) ||
			!rh_report_prepare(&report, existing_path) ||
			read_exact_file(existing_path, "sentinel"))
		return 3;

	snprintf(victim_path, sizeof(victim_path), "%s/victim", directory);
	fd = open(victim_path, O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
	if (fd < 0 || write(fd, "victim", 6) != 6 || close(fd))
		return 4;
	snprintf(link_path, sizeof(link_path), "%s/link", directory);
	if (symlink(victim_path, link_path) ||
			!rh_report_prepare(&report, link_path) ||
			read_exact_file(victim_path, "victim"))
		return 5;

	snprintf(overflow_path, sizeof(overflow_path), "%s/overflow", directory);
	if (rh_report_prepare(&report, overflow_path))
		return 6;
	errno = 0;
	if (!rh_report_append(&report, report.buffer, report.capacity + 1) ||
			errno != EOVERFLOW)
		return 7;
	if (rh_report_abort(&report))
		return 8;
	errno = 0;
	if (!lstat(overflow_path, &st) || errno != ENOENT)
		return 9;

	snprintf(write_fail_path, sizeof(write_fail_path), "%s/write-fail", directory);
	if (rh_report_prepare(&report, write_fail_path) ||
			rh_report_append(&report, "{}\n", 3))
		return 10;
	if (close(report.fd))
		return 11;
	errno = 0;
	if (!rh_report_publish(&report))
		return 12;
	errno = 0;
	if (!lstat(write_fail_path, &st) || errno != ENOENT)
		return 13;
	if (!rh_report_prepare(&report, "/dev/full"))
		return 14;

	snprintf(empty_path, sizeof(empty_path), "%s/empty", directory);
	if (rh_report_prepare(&report, empty_path) || !rh_report_publish(&report))
		return 15;
	errno = 0;
	if (!lstat(empty_path, &st) || errno != ENOENT)
		return 16;

	snprintf(strict_path, sizeof(strict_path), "%s/strict", directory);
	umask(0777);
	if (rh_report_prepare(&report, strict_path) ||
			rh_report_append(&report, "{}\n", 3) ||
			rh_report_publish(&report) || stat(strict_path, &st) ||
			(st.st_mode & 0777) != 0600)
		return 17;
	umask(077);

	snprintf(race_path, sizeof(race_path), "%s/race", directory);
	snprintf(moved_path, sizeof(moved_path), "%s/race-moved", directory);
	if (rh_report_prepare(&report, race_path) ||
			rh_report_append(&report, "{}\n", 3) ||
			rename(race_path, moved_path))
		return 18;
	fd = open(race_path, O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
	if (fd < 0 || write(fd, "replacement", 11) != 11 || close(fd) ||
			!rh_report_publish(&report) ||
			read_exact_file(race_path, "replacement") ||
			lstat(moved_path, &st))
		return 19;

	snprintf(hard_path, sizeof(hard_path), "%s/hard", directory);
	snprintf(hard_alias, sizeof(hard_alias), "%s/hard-alias", directory);
	if (rh_report_prepare(&report, hard_path) ||
			rh_report_append(&report, "{}\n", 3) ||
			link(hard_path, hard_alias) || !rh_report_publish(&report) ||
			lstat(hard_path, &st) || lstat(hard_alias, &st))
		return 20;

	snprintf(first_fstat_path, sizeof(first_fstat_path), "%s/first-fstat",
		directory);
	rh_report_test_fail_first_created_fstat();
	errno = 0;
	if (!rh_report_prepare(&report, first_fstat_path) || errno != EIO)
		return 21;
	errno = 0;
	if (!lstat(first_fstat_path, &st) || errno != ENOENT)
		return 22;

	snprintf(cleanup_fail_path, sizeof(cleanup_fail_path), "%s/cleanup-fail",
		directory);
	if (rh_report_prepare(&report, cleanup_fail_path) ||
			close(report.directory_fd))
		return 23;
	report.directory_fd = -1;
	errno = 0;
	if (!rh_report_abort(&report) || !errno || lstat(cleanup_fail_path, &st))
		return 24;
	if (!is_invalid_zero_reservation(cleanup_fail_path))
		return 25;

	printf("roothealth-report cases=12 passed=1\n");
	return 0;
}
