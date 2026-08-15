#define _GNU_SOURCE 1
#define _LARGEFILE64_SOURCE 1

#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <signal.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/types.h>
#include <sys/uio.h>
#include <unistd.h>

/*
 * Test-only durability observer for RootHealth qualification.
 *
 * The interposer never injects a target fsync and never treats a killed loop
 * device's cache as crash media.  It passes target calls through, captures the
 * bytes actually returned by each write attempt in an external payload, and
 * records the real fsync/fdatasync barriers in roothealth-powercut-tsv-v2.
 * powercut-materialize.py later synthesizes conservative durable-media images
 * from an immutable pre-repair source.
 *
 * Required environment for capture:
 *   ROOTHEALTH_FAULT_MODE=capture
 *   ROOTHEALTH_FAULT_TARGET=/dev/loopN
 *   ROOTHEALTH_FAULT_LOG=/trusted/fresh/events.tsv
 *   ROOTHEALTH_FAULT_PAYLOAD=/trusted/fresh/payload.bin
 *
 * Barrier reachability test:
 *   ROOTHEALTH_FAULT_MODE=crash-before-barrier
 *   ROOTHEALTH_FAULT_AT=N
 * or ROOTHEALTH_FAULT_MODE=crash-after-barrier to kill after the real
 * successful/failed target barrier has returned and been recorded.
 *
 * Target-write reachability tests (no event/payload side channel):
 *   ROOTHEALTH_FAULT_MODE=crash-before-write|crash-after-write
 *   ROOTHEALTH_FAULT_AT=N
 *
 * Prewrite read-I/O test (no event/payload side channel):
 *   ROOTHEALTH_FAULT_MODE=read-fault
 *   ROOTHEALTH_FAULT_TARGET=/dev/loopN
 *   ROOTHEALTH_FAULT_READ_OFFSET=absolute-byte-offset
 *
 * A partial or invalid configuration exits 125.  This is deliberately
 * fail-closed: qualification must not silently run without observation.
 */

enum observer_mode {
	OBSERVER_DISABLED = 0,
	OBSERVER_CAPTURE,
	OBSERVER_CRASH_BEFORE_BARRIER,
	OBSERVER_CRASH_AFTER_BARRIER,
	OBSERVER_CRASH_BEFORE_WRITE,
	OBSERVER_CRASH_AFTER_WRITE,
	OBSERVER_READ_FAULT,
};

static enum observer_mode observer_mode;
static unsigned long long crash_barrier;
static unsigned long long crash_write;
static unsigned long long target_write_attempt;
static unsigned long long sequence_number;
static unsigned long long write_number;
static unsigned long long barrier_number;
static unsigned long long epoch_number = 1;
static unsigned long long payload_offset;
static unsigned long long read_fault_offset;
static int event_fd = -1;
static int payload_fd = -1;
static struct stat target_stat;
static bool target_ready;
static atomic_flag target_call_lock = ATOMIC_FLAG_INIT;

static ssize_t (*next_write)(int, const void *, size_t);
static ssize_t (*next_read)(int, void *, size_t);
static ssize_t (*next_pread)(int, void *, size_t, off_t);
static ssize_t (*next_pread64)(int, void *, size_t, off64_t);
static ssize_t (*next_pwrite)(int, const void *, size_t, off_t);
static ssize_t (*next_pwrite64)(int, const void *, size_t, off64_t);
static ssize_t (*next_writev)(int, const struct iovec *, int);
static ssize_t (*next_pwritev)(int, const struct iovec *, int, off_t);
static ssize_t (*next_pwritev2)(int, const struct iovec *, int, off_t, int);
static int (*next_fsync)(int);
static int (*next_fdatasync)(int);

static void raw_message(const char *message)
{
	if (message)
		(void)syscall(SYS_write, STDERR_FILENO, message, strlen(message));
}

static void fail_closed(const char *message)
{
	raw_message("roothealth durability observer: ");
	raw_message(message);
	raw_message("\n");
	_exit(125);
}

static void acquire_target_lock(void)
{
	while (atomic_flag_test_and_set_explicit(&target_call_lock,
			memory_order_acquire))
		(void)syscall(SYS_sched_yield);
}

static void release_target_lock(void)
{
	atomic_flag_clear_explicit(&target_call_lock, memory_order_release);
}

static bool same_target(int fd)
{
	struct stat current;

	if (!target_ready || fstat(fd, &current))
		return false;
	if (S_ISBLK(target_stat.st_mode))
		return S_ISBLK(current.st_mode) &&
			current.st_rdev == target_stat.st_rdev;
	return current.st_dev == target_stat.st_dev &&
		current.st_ino == target_stat.st_ino;
}

static void raw_write_all(int fd, const void *data, size_t length,
		const char *label)
{
	const unsigned char *bytes = data;

	while (length) {
		ssize_t written = syscall(SYS_write, fd, bytes, length);

		if (written < 0 && errno == EINTR)
			continue;
		if (written <= 0)
			fail_closed(label);
		bytes += (size_t)written;
		length -= (size_t)written;
	}
}

static void sync_side_channel(int fd, const char *label)
{
	int result;

	do {
		result = (int)syscall(SYS_fsync, fd);
	} while (result && errno == EINTR);
	if (result)
		fail_closed(label);
}

static void append_event(const char *line, size_t length)
{
	if (event_fd < 0)
		fail_closed("event log is unavailable");
	raw_write_all(event_fd, line, length, "cannot append event log");
	sync_side_channel(event_fd, "cannot sync event log");
}

static long current_tid(void)
{
	return (long)syscall(SYS_gettid);
}

static void capture_buffer(const void *buffer, size_t length)
{
	if (!length)
		return;
	if (!buffer)
		fail_closed("successful target write has a null capture buffer");
	raw_write_all(payload_fd, buffer, length, "cannot append captured payload");
}

static void capture_iovecs(const struct iovec *iov, int iovcnt, size_t length)
{
	int index;

	if (length && (!iov || iovcnt <= 0))
		fail_closed("successful vector write has no capture iovec");
	for (index = 0; index < iovcnt && length; index++) {
		size_t part = iov[index].iov_len;

		if (part > length)
			part = length;
		capture_buffer(iov[index].iov_base, part);
		length -= part;
	}
	if (length)
		fail_closed("successful vector result exceeds its iovec payload");
}

static size_t iovec_size(const struct iovec *iov, int iovcnt)
{
	size_t total = 0;
	int index;

	if (!iov || iovcnt < 0)
		return 0;
	for (index = 0; index < iovcnt; index++) {
		if (SIZE_MAX - total < iov[index].iov_len)
			return SIZE_MAX;
		total += iov[index].iov_len;
	}
	return total;
}

static void emit_write_event(const char *operation, long long offset,
		size_t requested, ssize_t result, int call_errno,
		unsigned int flags)
{
	char line[512];
	unsigned long long captured = result > 0 ? (unsigned long long)result : 0;
	unsigned long long event_payload_offset = payload_offset;
	int length;

	sequence_number++;
	write_number++;
	length = snprintf(line, sizeof(line),
		"W\t%llu\t%llu\t%llu\t%s\t%lld\t%zu\t%zd\t%d\t%llu\t%llu\t%u\t%ld\t%ld\n",
		sequence_number, write_number, epoch_number, operation, offset,
		requested, result, result < 0 ? call_errno : 0,
		event_payload_offset, captured, flags, (long)getpid(), current_tid());
	if (length <= 0 || (size_t)length >= sizeof(line))
		fail_closed("write event exceeds its bounded record");
	append_event(line, (size_t)length);
	if (ULLONG_MAX - payload_offset < captured)
		fail_closed("captured payload offset overflow");
	payload_offset += captured;
}

static void emit_sync_event(const char *operation, int result, int call_errno)
{
	char line[384];
	int length;

	sequence_number++;
	barrier_number++;
	length = snprintf(line, sizeof(line),
		"S\t%llu\t%llu\t%llu\t%s\t%d\t%d\t%llu\t%ld\t%ld\n",
		sequence_number, barrier_number, epoch_number, operation, result,
		result < 0 ? call_errno : 0, write_number, (long)getpid(),
		current_tid());
	if (length <= 0 || (size_t)length >= sizeof(line))
		fail_closed("sync event exceeds its bounded record");
	append_event(line, (size_t)length);
	if (!result)
		epoch_number++;
}

static void emit_crash_event(const char *operation)
{
	char line[384];
	int length;

	sequence_number++;
	barrier_number++;
	length = snprintf(line, sizeof(line),
		"C\t%llu\t%llu\t%llu\t%s\t%llu\t%ld\t%ld\n",
		sequence_number, barrier_number, epoch_number, operation,
		write_number, (long)getpid(), current_tid());
	if (length <= 0 || (size_t)length >= sizeof(line))
		fail_closed("crash event exceeds its bounded record");
	append_event(line, (size_t)length);
}

static void terminate_now(void)
{
	(void)syscall(SYS_kill, getpid(), SIGKILL);
	_exit(137);
}

static unsigned long long parse_positive(const char *value,
		const char *description)
{
	char *end = NULL;
	unsigned long long parsed;

	if (!value || !*value)
		fail_closed(description);
	errno = 0;
	parsed = strtoull(value, &end, 10);
	if (errno || !parsed || !end || *end)
		fail_closed(description);
	return parsed;
}

static unsigned long long parse_nonnegative(const char *value,
		const char *description)
{
	char *end = NULL;
	unsigned long long parsed;

	if (!value || !*value)
		fail_closed(description);
	errno = 0;
	parsed = strtoull(value, &end, 10);
	if (errno || !end || *end)
		fail_closed(description);
	return parsed;
}

static bool stat_matches_fd(const struct stat *expected, int fd)
{
	struct stat actual;

	return !fstat(fd, &actual) && actual.st_dev == expected->st_dev &&
		actual.st_ino == expected->st_ino;
}

static bool is_internal_rescan_process(void)
{
	static const char marker[] = "--internal-rescan-fd";
	char command_line[8192];
	ssize_t bytes;
	size_t at = 0;
	int fd;

	fd = (int)syscall(SYS_openat, AT_FDCWD, "/proc/self/cmdline",
		O_RDONLY | O_CLOEXEC | O_NOFOLLOW, 0);
	if (fd < 0)
		return false;
	bytes = (ssize_t)syscall(SYS_read, fd, command_line,
		sizeof(command_line));
	(void)syscall(SYS_close, fd);
	if (bytes <= 0)
		return false;
	while (at < (size_t)bytes) {
		size_t remaining = (size_t)bytes - at;
		size_t length = strnlen(command_line + at, remaining);

		if (length == sizeof(marker) - 1U &&
				!memcmp(command_line + at, marker, sizeof(marker) - 1U))
			return true;
		if (length == remaining)
			break;
		at += length + 1U;
	}
	return false;
}

__attribute__((constructor)) static void initialize_observer(void)
{
	const char *mode_text = getenv("ROOTHEALTH_FAULT_MODE");
	const char *target_path = getenv("ROOTHEALTH_FAULT_TARGET");
	const char *event_path = getenv("ROOTHEALTH_FAULT_LOG");
	const char *payload_path = getenv("ROOTHEALTH_FAULT_PAYLOAD");
	const char *at_text = getenv("ROOTHEALTH_FAULT_AT");
	const char *read_offset_text = getenv("ROOTHEALTH_FAULT_READ_OFFSET");
	bool any_configuration = mode_text || target_path || event_path ||
		payload_path || at_text || read_offset_text;
	struct stat event_stat;
	char header[384];
	int length;

	next_write = dlsym(RTLD_NEXT, "write");
	next_read = dlsym(RTLD_NEXT, "read");
	next_pread = dlsym(RTLD_NEXT, "pread");
	next_pread64 = dlsym(RTLD_NEXT, "pread64");
	next_pwrite = dlsym(RTLD_NEXT, "pwrite");
	next_pwrite64 = dlsym(RTLD_NEXT, "pwrite64");
	next_writev = dlsym(RTLD_NEXT, "writev");
	next_pwritev = dlsym(RTLD_NEXT, "pwritev");
	next_pwritev2 = dlsym(RTLD_NEXT, "pwritev2");
	next_fsync = dlsym(RTLD_NEXT, "fsync");
	next_fdatasync = dlsym(RTLD_NEXT, "fdatasync");
	if (!any_configuration)
		return;
	if (!mode_text || !target_path)
		fail_closed("partial ROOTHEALTH_FAULT_* configuration");
	if (!strcmp(mode_text, "read-fault")) {
		observer_mode = OBSERVER_READ_FAULT;
		if (event_path || payload_path || at_text || !read_offset_text)
			fail_closed("read-fault has invalid side-channel configuration");
		read_fault_offset = parse_nonnegative(read_offset_text,
			"read-fault requires ROOTHEALTH_FAULT_READ_OFFSET");
	} else if (!strcmp(mode_text, "capture")) {
		observer_mode = OBSERVER_CAPTURE;
		if (!event_path || !payload_path || at_text || read_offset_text)
			fail_closed("capture mode forbids ROOTHEALTH_FAULT_AT");
	} else if (!strcmp(mode_text, "crash-before-barrier")) {
		observer_mode = OBSERVER_CRASH_BEFORE_BARRIER;
		if (!event_path || !payload_path || read_offset_text)
			fail_closed("crash mode has invalid side-channel configuration");
		crash_barrier = parse_positive(at_text,
			"crash-before-barrier requires a positive ROOTHEALTH_FAULT_AT");
	} else if (!strcmp(mode_text, "crash-after-barrier")) {
		observer_mode = OBSERVER_CRASH_AFTER_BARRIER;
		if (!event_path || !payload_path || read_offset_text)
			fail_closed("crash mode has invalid side-channel configuration");
		crash_barrier = parse_positive(at_text,
			"crash-after-barrier requires a positive ROOTHEALTH_FAULT_AT");
	} else if (!strcmp(mode_text, "crash-before-write") ||
			!strcmp(mode_text, "crash-after-write")) {
		observer_mode = !strcmp(mode_text, "crash-before-write") ?
			OBSERVER_CRASH_BEFORE_WRITE : OBSERVER_CRASH_AFTER_WRITE;
		if (event_path || payload_path || read_offset_text)
			fail_closed("write-crash mode forbids side-channel configuration");
		crash_write = parse_positive(at_text,
			"write-crash mode requires a positive ROOTHEALTH_FAULT_AT");
	} else {
		fail_closed("ROOTHEALTH_FAULT_MODE is unknown");
	}
	/*
	 * A successful transaction launches a read-only self-exec rescan.  The
	 * parent retains the exclusive capture files; the child must not try to
	 * recreate them and performs no target writes by contract/trace check.
	 */
	if (event_path && is_internal_rescan_process()) {
		observer_mode = OBSERVER_DISABLED;
		return;
	}
	if (stat(target_path, &target_stat))
		fail_closed("cannot stat the selected target");
	target_ready = true;
	if (observer_mode == OBSERVER_READ_FAULT ||
			observer_mode == OBSERVER_CRASH_BEFORE_WRITE ||
			observer_mode == OBSERVER_CRASH_AFTER_WRITE)
		return;
	event_fd = (int)syscall(SYS_openat, AT_FDCWD, event_path,
		O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW, 0600);
	if (event_fd < 0)
		fail_closed("cannot exclusively create event log");
	payload_fd = (int)syscall(SYS_openat, AT_FDCWD, payload_path,
		O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW, 0600);
	if (payload_fd < 0)
		fail_closed("cannot exclusively create payload file");
	if (stat_matches_fd(&target_stat, event_fd) ||
		stat_matches_fd(&target_stat, payload_fd))
		fail_closed("side channel aliases the selected target");
	if (fstat(event_fd, &event_stat) || !S_ISREG(event_stat.st_mode))
		fail_closed("event log is not a regular file");
	if (fstat(payload_fd, &event_stat) || !S_ISREG(event_stat.st_mode))
		fail_closed("payload is not a regular file");
	length = snprintf(header, sizeof(header), "H\t2\t512\t%llu\t%llu\t%llu\n",
		(unsigned long long)target_stat.st_dev,
		(unsigned long long)target_stat.st_ino,
		(unsigned long long)target_stat.st_rdev);
	if (length <= 0 || (size_t)length >= sizeof(header))
		fail_closed("target identity header exceeds its bounded record");
	append_event(header, (size_t)length);
	sync_side_channel(payload_fd, "cannot initialize payload file");
}

static bool read_fault_matches(int fd, unsigned long long offset, size_t count)
{
	unsigned long long end;

	if (observer_mode != OBSERVER_READ_FAULT || !same_target(fd) || !count)
		return false;
	if (ULLONG_MAX - offset < count)
		end = ULLONG_MAX;
	else
		end = offset + count;
	return offset <= read_fault_offset && read_fault_offset < end;
}

ssize_t read(int fd, void *buffer, size_t count)
{
	off_t offset;

	if (!next_read) {
		errno = ENOSYS;
		return -1;
	}
	offset = lseek(fd, 0, SEEK_CUR);
	if (offset >= 0 && read_fault_matches(fd,
			(unsigned long long)offset, count)) {
		errno = EIO;
		return -1;
	}
	return next_read(fd, buffer, count);
}

ssize_t pread(int fd, void *buffer, size_t count, off_t offset)
{
	if (!next_pread) {
		errno = ENOSYS;
		return -1;
	}
	if (offset >= 0 && read_fault_matches(fd,
			(unsigned long long)offset, count)) {
		errno = EIO;
		return -1;
	}
	return next_pread(fd, buffer, count, offset);
}

ssize_t pread64(int fd, void *buffer, size_t count, off64_t offset)
{
	if (!next_pread64) {
		errno = ENOSYS;
		return -1;
	}
	if (offset >= 0 && read_fault_matches(fd,
			(unsigned long long)offset, count)) {
		errno = EIO;
		return -1;
	}
	return next_pread64(fd, buffer, count, offset);
}

static void begin_target_write(void)
{
	target_write_attempt++;
	if (observer_mode == OBSERVER_READ_FAULT)
		fail_closed("read-fault observation encountered a target write");
	if (observer_mode == OBSERVER_CRASH_BEFORE_WRITE &&
			target_write_attempt == crash_write)
		terminate_now();
}

static bool finish_target_write(void)
{
	if (observer_mode == OBSERVER_CRASH_AFTER_WRITE &&
			target_write_attempt == crash_write)
		terminate_now();
	return observer_mode == OBSERVER_CRASH_BEFORE_WRITE ||
		observer_mode == OBSERVER_CRASH_AFTER_WRITE;
}

ssize_t write(int fd, const void *buffer, size_t count)
{
	ssize_t result;
	int saved_errno;
	off_t offset;

	if (!next_write) {
		errno = ENOSYS;
		return -1;
	}
	if (!same_target(fd))
		return next_write(fd, buffer, count);
	acquire_target_lock();
	offset = lseek(fd, 0, SEEK_CUR);
	if (offset < 0)
		fail_closed("cannot determine sequential target write offset");
	begin_target_write();
	result = next_write(fd, buffer, count);
	saved_errno = errno;
	if (finish_target_write()) {
		release_target_lock();
		errno = saved_errno;
		return result;
	}
	if (result > 0) {
		capture_buffer(buffer, (size_t)result);
		sync_side_channel(payload_fd, "cannot sync captured payload");
	}
	emit_write_event("write", (long long)offset, count, result, saved_errno, 0);
	release_target_lock();
	errno = saved_errno;
	return result;
}

ssize_t pwrite(int fd, const void *buffer, size_t count, off_t offset)
{
	ssize_t result;
	int saved_errno;

	if (!next_pwrite) {
		errno = ENOSYS;
		return -1;
	}
	if (!same_target(fd))
		return next_pwrite(fd, buffer, count, offset);
	acquire_target_lock();
	begin_target_write();
	result = next_pwrite(fd, buffer, count, offset);
	saved_errno = errno;
	if (finish_target_write()) {
		release_target_lock();
		errno = saved_errno;
		return result;
	}
	if (result > 0) {
		capture_buffer(buffer, (size_t)result);
		sync_side_channel(payload_fd, "cannot sync captured payload");
	}
	emit_write_event("pwrite", (long long)offset, count, result, saved_errno, 0);
	release_target_lock();
	errno = saved_errno;
	return result;
}

ssize_t pwrite64(int fd, const void *buffer, size_t count, off64_t offset)
{
	ssize_t result;
	int saved_errno;

	if (!next_pwrite64) {
		errno = ENOSYS;
		return -1;
	}
	if (!same_target(fd))
		return next_pwrite64(fd, buffer, count, offset);
	acquire_target_lock();
	begin_target_write();
	result = next_pwrite64(fd, buffer, count, offset);
	saved_errno = errno;
	if (finish_target_write()) {
		release_target_lock();
		errno = saved_errno;
		return result;
	}
	if (result > 0) {
		capture_buffer(buffer, (size_t)result);
		sync_side_channel(payload_fd, "cannot sync captured payload");
	}
	emit_write_event("pwrite64", (long long)offset, count, result, saved_errno, 0);
	release_target_lock();
	errno = saved_errno;
	return result;
}

ssize_t writev(int fd, const struct iovec *iov, int iovcnt)
{
	ssize_t result;
	int saved_errno;
	off_t offset;
	size_t requested = iovec_size(iov, iovcnt);

	if (!next_writev) {
		errno = ENOSYS;
		return -1;
	}
	if (!same_target(fd))
		return next_writev(fd, iov, iovcnt);
	acquire_target_lock();
	offset = lseek(fd, 0, SEEK_CUR);
	if (offset < 0)
		fail_closed("cannot determine sequential vector target write offset");
	begin_target_write();
	result = next_writev(fd, iov, iovcnt);
	saved_errno = errno;
	if (finish_target_write()) {
		release_target_lock();
		errno = saved_errno;
		return result;
	}
	if (result > 0) {
		capture_iovecs(iov, iovcnt, (size_t)result);
		sync_side_channel(payload_fd, "cannot sync captured payload");
	}
	emit_write_event("writev", (long long)offset, requested, result,
		saved_errno, 0);
	release_target_lock();
	errno = saved_errno;
	return result;
}

ssize_t pwritev(int fd, const struct iovec *iov, int iovcnt, off_t offset)
{
	ssize_t result;
	int saved_errno;
	size_t requested = iovec_size(iov, iovcnt);

	if (!next_pwritev) {
		errno = ENOSYS;
		return -1;
	}
	if (!same_target(fd))
		return next_pwritev(fd, iov, iovcnt, offset);
	acquire_target_lock();
	begin_target_write();
	result = next_pwritev(fd, iov, iovcnt, offset);
	saved_errno = errno;
	if (finish_target_write()) {
		release_target_lock();
		errno = saved_errno;
		return result;
	}
	if (result > 0) {
		capture_iovecs(iov, iovcnt, (size_t)result);
		sync_side_channel(payload_fd, "cannot sync captured payload");
	}
	emit_write_event("pwritev", (long long)offset, requested, result,
		saved_errno, 0);
	release_target_lock();
	errno = saved_errno;
	return result;
}

ssize_t pwritev2(int fd, const struct iovec *iov, int iovcnt,
		off_t offset, int flags)
{
	ssize_t result;
	int saved_errno;
	size_t requested = iovec_size(iov, iovcnt);

	if (!next_pwritev2) {
		errno = ENOSYS;
		return -1;
	}
	if (!same_target(fd))
		return next_pwritev2(fd, iov, iovcnt, offset, flags);
	acquire_target_lock();
	begin_target_write();
	result = next_pwritev2(fd, iov, iovcnt, offset, flags);
	saved_errno = errno;
	if (finish_target_write()) {
		release_target_lock();
		errno = saved_errno;
		return result;
	}
	if (result > 0) {
		capture_iovecs(iov, iovcnt, (size_t)result);
		sync_side_channel(payload_fd, "cannot sync captured payload");
	}
	emit_write_event("pwritev2", (long long)offset, requested, result,
		saved_errno, (unsigned int)flags);
	release_target_lock();
	errno = saved_errno;
	return result;
}

static int observe_barrier(int fd, const char *operation, int (*function)(int))
{
	int result;
	int saved_errno;

	if (!function) {
		errno = ENOSYS;
		return -1;
	}
	if (!same_target(fd))
		return function(fd);
	acquire_target_lock();
	if (observer_mode == OBSERVER_CRASH_BEFORE_BARRIER &&
			barrier_number + 1 == crash_barrier) {
		emit_crash_event(operation);
		release_target_lock();
		terminate_now();
	}
	result = function(fd);
	saved_errno = errno;
	emit_sync_event(operation, result, saved_errno);
	if (observer_mode == OBSERVER_CRASH_AFTER_BARRIER &&
			barrier_number == crash_barrier) {
		release_target_lock();
		terminate_now();
	}
	release_target_lock();
	errno = saved_errno;
	return result;
}

int fsync(int fd)
{
	return observe_barrier(fd, "fsync", next_fsync);
}

int fdatasync(int fd)
{
	return observe_barrier(fd, "fdatasync", next_fdatasync);
}
