#define _GNU_SOURCE

#include <dlfcn.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <spawn.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/statfs.h>
#include <sys/auxv.h>
#include <sys/inotify.h>
#include <sys/syscall.h>
#include <sys/types.h>
#include <sys/un.h>
#include <unistd.h>

#define T1OS_CHROMIUM_PERSISTENT_SANDBOX \
	"/the one/software/chromium/program/chrome-sandbox"
#define T1OS_CHROMIUM_EXECUTABLE \
	"/the one/software/chromium/program/chrome"
#define T1OS_CHROMIUM_PROCESS_EXECUTABLE \
	"/the one/drivers/processes/self/exe"
#define T1OS_CHROMIUM_URANDOM \
	"/the one/drivers/nodes/urandom"
#define T1OS_CHROMIUM_NVIDIA_CONTROL \
	"/the one/drivers/nodes/nvidiactl"
#define T1OS_CHROMIUM_NVIDIA_ROOT \
	"/the one/drivers/nodes/nvidia"
#define T1OS_CHROMIUM_NVIDIA_MAXIMUM_GPUS 16

static const char *t1os_path(const char *path, char output[PATH_MAX]);

static int chromium_urandom_descriptor = -1;

__attribute__((constructor))
static void t1os_path_provider_initialize(void)
{
	const char *executable = (const char *)getauxval(AT_EXECFN);

	/*
	 * The SUID sandbox eventually chroots the zygote into an empty directory.
	 * Preserve a read-only random source before that happens; later /dev/urandom
	 * opens receive a duplicated descriptor instead of requiring a path outside
	 * the chroot.  This creates no filesystem object or symbolic link.
	 */
	if (executable && strcmp(executable, T1OS_CHROMIUM_EXECUTABLE) == 0) {
		chromium_urandom_descriptor =
			(int)syscall(SYS_openat, AT_FDCWD, T1OS_CHROMIUM_URANDOM,
				     O_RDONLY | O_CLOEXEC, 0);
	}

#ifdef T1OS_PATH_PROVIDER_TRACE
	dprintf(STDERR_FILENO,
		"T1OS path provider trace: load pid=%ld executable=%s urandom=%d "
		"error=%d\n",
		(long)getpid(), executable ? executable : "missing",
		chromium_urandom_descriptor,
		chromium_urandom_descriptor < 0 ? errno : 0);
#endif
}

static bool chromium_urandom_open(const char *path, int flags, int *result)
{
	int command;

	if (!path || strcmp(path, "/dev/urandom") != 0 ||
	    chromium_urandom_descriptor < 0 ||
	    (flags & O_ACCMODE) != O_RDONLY ||
	    (flags & (O_CREAT | O_TMPFILE)))
		return false;

	command = flags & O_CLOEXEC ? F_DUPFD_CLOEXEC : F_DUPFD;
	*result = fcntl(chromium_urandom_descriptor, command, 0);
	return true;
}

static bool chromium_singleton_name(const char *path)
{
	const char *name;

	if (!path)
		return false;
	name = strrchr(path, '/');
	name = name ? name + 1 : path;
	return strcmp(name, "SingletonLock") == 0 ||
	       strcmp(name, "SingletonSocket") == 0 ||
	       strcmp(name, "SingletonCookie") == 0;
}

/*
 * Chrome normally stores its process-singleton tokens in symbolic links.
 * T1OS forbids symbolic links globally, so store those opaque tokens in
 * exclusive regular files and emulate readlink only for the three fixed
 * singleton names.  All other symlink creation remains denied.
 */
static int chromium_singleton_create(const char *target_path,
				     const char *link_path)
{
	char mapped[PATH_MAX];
	const char *target;
	size_t length;
	size_t offset = 0;
	int descriptor;

	if (!target_path || !chromium_singleton_name(link_path)) {
		errno = EPERM;
		return -1;
	}
	target = t1os_path(link_path, mapped);
	if (!target)
		return -1;
	length = strlen(target_path);
	if (length == 0 || length >= PATH_MAX) {
		errno = EINVAL;
		return -1;
	}

	descriptor = (int)syscall(SYS_openat, AT_FDCWD, target,
				  O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC |
					  O_NOFOLLOW,
				  0600);
	if (descriptor < 0)
		return -1;
	while (offset < length) {
		ssize_t written =
			syscall(SYS_write, descriptor, target_path + offset,
				length - offset);
		if (written < 0 && errno == EINTR)
			continue;
		if (written <= 0) {
			int saved_errno = written < 0 ? errno : EIO;
			syscall(SYS_close, descriptor);
			syscall(SYS_unlinkat, AT_FDCWD, target, 0);
			errno = saved_errno;
			return -1;
		}
		offset += (size_t)written;
	}
	if (syscall(SYS_close, descriptor) != 0) {
		int saved_errno = errno;
		syscall(SYS_unlinkat, AT_FDCWD, target, 0);
		errno = saved_errno;
		return -1;
	}
	return 0;
}

static bool chromium_singleton_readlink(int directory, const char *path,
					char *buffer, size_t size,
					ssize_t *result)
{
	char mapped[PATH_MAX];
	const char *target;
	struct stat status;
	int descriptor;
	ssize_t length;

	if (!chromium_singleton_name(path))
		return false;
	if (!buffer || size == 0) {
		errno = EINVAL;
		*result = -1;
		return true;
	}
	target = t1os_path(path, mapped);
	if (!target) {
		*result = -1;
		return true;
	}
	descriptor = (int)syscall(SYS_openat, directory, target,
				  O_RDONLY | O_CLOEXEC | O_NOFOLLOW, 0);
	if (descriptor < 0) {
		*result = -1;
		return true;
	}
	if (syscall(SYS_fstat, descriptor, &status) != 0 ||
	    !S_ISREG(status.st_mode) || status.st_size <= 0 ||
	    status.st_size >= PATH_MAX) {
		int saved_errno = errno ? errno : EINVAL;
		syscall(SYS_close, descriptor);
		errno = saved_errno;
		*result = -1;
		return true;
	}
	length = syscall(SYS_read, descriptor, buffer, size);
	if (length < 0) {
		int saved_errno = errno;
		syscall(SYS_close, descriptor);
		errno = saved_errno;
		*result = -1;
		return true;
	}
	if (syscall(SYS_close, descriptor) != 0 && length >= 0) {
		*result = -1;
		return true;
	}
	*result = length;
	return true;
}

struct path_map {
	const char *legacy;
	const char *t1os;
	bool prefix;
};

static bool decimal_suffix(const char *value)
{
	if (!value || *value < '0' || *value > '9')
		return false;
	while (*value >= '0' && *value <= '9')
		value++;
	return *value == '\0';
}

static bool chromium_nvidia_graphics_node(const char *path)
{
	long index;
	char *end;

	if (!path)
		return false;
	if (strcmp(path, "/dev/nvidiactl") == 0)
		return true;
	if (strncmp(path, "/dev/nvidia", 11) != 0 ||
	    !decimal_suffix(path + 11))
		return false;
	errno = 0;
	index = strtol(path + 11, &end, 10);
	return !errno && end && *end == '\0' && index >= 0 &&
	       index < T1OS_CHROMIUM_NVIDIA_MAXIMUM_GPUS;
}

static const struct path_map path_maps[] = {
	{ "/dev/dri", "/the one/drivers/nodes/dri", true },
	{ "/dev/shm", "/.ephemeral/chromium/shared", true },
	{ "/dev/null", "/the one/drivers/nodes/null", false },
	{ "/dev/zero", "/the one/drivers/nodes/zero", false },
	{ "/dev/full", "/the one/drivers/nodes/full", false },
	{ "/dev/random", "/the one/drivers/nodes/random", false },
	{ "/dev/urandom", "/the one/drivers/nodes/urandom", false },
	{ "/dev/tty", "/the one/drivers/nodes/tty", false },
	{ "/proc", "/the one/drivers/processes", true },
	{ "/sys", "/the one/drivers/state", true },
	{ "/tmp/.X11-unix", "/.ephemeral/chromium/display", true },
	{ "/tmp", "/.ephemeral/chromium/temporary", true },
	{ "/run", "/.ephemeral/chromium/runtime", true },
	{ "/var/lib/xkb", "/.ephemeral/chromium/xkb", true },
	{ "/var", "/.ephemeral/chromium/variable", true },
	{ "/etc/ssl/certs/ca-certificates.crt", "/the one/settings/network/cacerts.pem", false },
	{ "/etc/fonts", "/the one/software/chromium/resources/fontconfig-configuration", true },
	{ "/etc/localtime", "/the one/software/chromium/resources/zoneinfo/Australia/Sydney", false },
	{ "/etc/opt/chrome/policies/managed", "/the one/settings/chromium/policies", true },
	{ "/etc", "/.ephemeral/chromium/system", true },
	{ "/usr/share/X11/xkb", "/the one/software/chromium/resources/xkb", true },
	{ "/usr/share/fonts", "/the one/software/chromium/resources/fonts", true },
	{ "/usr/share/icons", "/the one/software/chromium/resources/icons", true },
	{ "/usr/share/mime", "/the one/software/chromium/resources/mime", true },
	{ "/usr/share/themes", "/the one/software/chromium/resources/themes", true },
	{ "/usr/share/zoneinfo", "/the one/software/chromium/resources/zoneinfo", true },
	{ "/usr/lib/x86_64-linux-gnu/dri", "/the one/catalogue/graphics/drivers", true },
	{ "/usr/lib64/dri", "/the one/catalogue/graphics/drivers", true },
	{ "/usr/lib/dri", "/the one/catalogue/graphics/drivers", true },
	{ "/usr/bin/xkbcomp", "/the one/software/chromium/tools/xkbcomp", false },
	{ "/usr", "/the one/software/chromium/legacy", true },
	{ "/bin/sh", "/the one/software/chromium/tools/dash", false },
	{ "/bin", "/the one/software/chromium/tools", true },
	{ "/lib64", "/the one/software/chromium/libraries", true },
	{ "/lib", "/the one/software/chromium/libraries", true },
	{ "/home/chromium", "/the one/settings/chromium", true },
	{ "/home", "/the one/settings/chromium/homes", true },
	{ "/root", "/the one/settings/chromium/root", true },
	{ "/media", "/.ephemeral/volumes", true },
	{ "/mnt", "/.ephemeral/volumes", true },
	{ "/the one/software/chromium/program/extensions", "/.ephemeral/chromium/extensions", true },
	{ "/opt/google/chrome/extensions", "/.ephemeral/chromium/extensions", true },
	{ "/opt/google/chrome", "/the one/software/chromium/program", true },
	{ "/opt", "/the one/software", true },
};

static bool path_matches(const char *path, const struct path_map *mapping)
{
	size_t length = strlen(mapping->legacy);

	if (strncmp(path, mapping->legacy, length) != 0)
		return false;
	if (!mapping->prefix)
		return path[length] == '\0';
	return path[length] == '\0' || path[length] == '/';
}

static const char *t1os_path(const char *path, char output[PATH_MAX])
{
	size_t index;
	int written;

	if (!path || path[0] != '/')
		return path;

	/*
	 * NVIDIA EGL/GL needs the control node and selected numeric GPU node for
	 * ordinary rendering. Compute and video-decode device paths deliberately
	 * have no mapping here and remain owned by the external media service.
	 */
	if (chromium_nvidia_graphics_node(path)) {
		if (strcmp(path, "/dev/nvidiactl") == 0)
			written = snprintf(output, PATH_MAX, "%s",
					   T1OS_CHROMIUM_NVIDIA_CONTROL);
		else
			written = snprintf(output, PATH_MAX, "%s%s",
					   T1OS_CHROMIUM_NVIDIA_ROOT,
					   path + 11);
		if (written < 0 || written >= PATH_MAX) {
			errno = ENAMETOOLONG;
			return NULL;
		}
		return output;
	}

	for (index = 0; index < sizeof(path_maps) / sizeof(path_maps[0]); index++) {
		const struct path_map *mapping = &path_maps[index];
		size_t legacy_length;

		if (!path_matches(path, mapping))
			continue;
		legacy_length = strlen(mapping->legacy);
		written = snprintf(output, PATH_MAX, "%s%s", mapping->t1os,
				   path + legacy_length);
		if (written < 0 || written >= PATH_MAX) {
			errno = ENAMETOOLONG;
			return NULL;
		}
		return output;
	}

	return path;
}

static bool chromium_sandbox_discovery(void)
{
	const char *enabled = getenv("T1OS_CHROMIUM_SANDBOX_DISCOVERY");

	return enabled && strcmp(enabled, "1") == 0;
}

static bool chromium_sandbox_candidate_probe(const char *path, int mode)
{
	return chromium_sandbox_discovery() && mode == F_OK && path &&
	       strcmp(path, T1OS_CHROMIUM_PERSISTENT_SANDBOX) == 0;
}

static bool chromium_executable_owner_probe(const char *path)
{
	return chromium_sandbox_discovery() && path &&
	       strcmp(path, "/proc/self/exe") == 0;
}

static bool chromium_executable_readlink(const char *path, char *buffer,
					 size_t size, ssize_t *result)
{
	const char *executable;
	size_t length;

	/*
	 * Every Chromium child needs a stable executable identity.  The discovery
	 * flag is deliberately not consulted here: Chromium does not preserve that
	 * private flag in every zygote environment, while LD_PRELOAD itself is
	 * restored by the SUID sandbox.  AT_EXECFN keeps crashpad and other packaged
	 * executables distinct without creating a filesystem symbolic link.
	 */
	if (!path || strcmp(path, "/proc/self/exe") != 0)
		return false;
	if (!buffer || size == 0) {
		errno = EINVAL;
		*result = -1;
		return true;
	}

	executable = (const char *)getauxval(AT_EXECFN);
	if (!executable || executable[0] != '/' ||
	    strcmp(executable, "/proc/self/exe") == 0 ||
	    strcmp(executable, T1OS_CHROMIUM_PROCESS_EXECUTABLE) == 0)
		executable = T1OS_CHROMIUM_EXECUTABLE;
#ifdef T1OS_PATH_PROVIDER_TRACE
	dprintf(STDERR_FILENO,
		"T1OS path provider trace: readlink pid=%ld path=%s executable=%s\n",
		(long)getpid(), path, executable);
#endif
	length = strlen(executable);
	if (length > size)
		length = size;
	memcpy(buffer, executable, length);
	*result = (ssize_t)length;
	return true;
}

#define RESOLVE(symbol) \
	static typeof(symbol) *real_##symbol; \
	if (!real_##symbol) real_##symbol = dlsym(RTLD_NEXT, #symbol)

int open(const char *path, int flags, ...)
{
	mode_t mode = 0;
	char mapped[PATH_MAX];
	const char *target;
	int result;
	RESOLVE(open);
	if (chromium_urandom_open(path, flags, &result))
		return result;
	if (flags & (O_CREAT | O_TMPFILE)) {
		va_list arguments;
		va_start(arguments, flags);
		mode = (mode_t)va_arg(arguments, int);
		va_end(arguments);
	}
	target = t1os_path(path, mapped);
	if (!target) return -1;
	return flags & (O_CREAT | O_TMPFILE) ? real_open(target, flags, mode) : real_open(target, flags);
}

int open64(const char *path, int flags, ...)
{
	mode_t mode = 0;
	char mapped[PATH_MAX];
	const char *target;
	int result;
	RESOLVE(open64);
	if (chromium_urandom_open(path, flags, &result))
		return result;
	if (flags & (O_CREAT | O_TMPFILE)) {
		va_list arguments;
		va_start(arguments, flags);
		mode = (mode_t)va_arg(arguments, int);
		va_end(arguments);
	}
	target = t1os_path(path, mapped);
	if (!target) return -1;
	return flags & (O_CREAT | O_TMPFILE) ? real_open64(target, flags, mode) : real_open64(target, flags);
}

int openat(int directory, const char *path, int flags, ...)
{
	mode_t mode = 0;
	char mapped[PATH_MAX];
	const char *target;
	int result;
	RESOLVE(openat);
	if (chromium_urandom_open(path, flags, &result))
		return result;
	if (flags & (O_CREAT | O_TMPFILE)) {
		va_list arguments;
		va_start(arguments, flags);
		mode = (mode_t)va_arg(arguments, int);
		va_end(arguments);
	}
	target = t1os_path(path, mapped);
	if (!target) return -1;
	return flags & (O_CREAT | O_TMPFILE) ? real_openat(directory, target, flags, mode) : real_openat(directory, target, flags);
}

int openat64(int directory, const char *path, int flags, ...)
{
	mode_t mode = 0;
	char mapped[PATH_MAX];
	const char *target;
	int result;
	RESOLVE(openat64);
	if (chromium_urandom_open(path, flags, &result))
		return result;
	if (flags & (O_CREAT | O_TMPFILE)) {
		va_list arguments;
		va_start(arguments, flags);
		mode = (mode_t)va_arg(arguments, int);
		va_end(arguments);
	}
	target = t1os_path(path, mapped);
	if (!target) return -1;
	return flags & (O_CREAT | O_TMPFILE) ? real_openat64(directory, target, flags, mode) : real_openat64(directory, target, flags);
}

int creat(const char *path, mode_t mode)
{
	char mapped[PATH_MAX];
	const char *target;
	RESOLVE(creat);
	target = t1os_path(path, mapped);
	return target ? real_creat(target, mode) : -1;
}

int creat64(const char *path, mode_t mode)
{
	char mapped[PATH_MAX];
	const char *target;
	RESOLVE(creat64);
	target = t1os_path(path, mapped);
	return target ? real_creat64(target, mode) : -1;
}

FILE *fopen(const char *path, const char *mode)
{
	char mapped[PATH_MAX];
	const char *target;
	RESOLVE(fopen);
	target = t1os_path(path, mapped);
	return target ? real_fopen(target, mode) : NULL;
}

FILE *fopen64(const char *path, const char *mode)
{
	char mapped[PATH_MAX];
	const char *target;
	RESOLVE(fopen64);
	target = t1os_path(path, mapped);
	return target ? real_fopen64(target, mode) : NULL;
}

#define PATH_WRAPPER(function, declaration, invocation) \
	int function declaration { \
		char mapped[PATH_MAX]; \
		const char *target; \
		RESOLVE(function); \
		target = t1os_path(path, mapped); \
		return target ? real_##function invocation : -1; \
	}

PATH_WRAPPER(chmod, (const char *path, mode_t mode), (target, mode))
PATH_WRAPPER(chown, (const char *path, uid_t owner, gid_t group), (target, owner, group))
PATH_WRAPPER(lchown, (const char *path, uid_t owner, gid_t group), (target, owner, group))
PATH_WRAPPER(mkdir, (const char *path, mode_t mode), (target, mode))
PATH_WRAPPER(unlink, (const char *path), (target))
PATH_WRAPPER(rmdir, (const char *path), (target))
PATH_WRAPPER(lstat, (const char *path, struct stat *status), (target, status))
PATH_WRAPPER(statfs, (const char *path, struct statfs *status), (target, status))
PATH_WRAPPER(lstat64, (const char *path, struct stat64 *status), (target, status))
PATH_WRAPPER(statfs64, (const char *path, struct statfs64 *status), (target, status))
PATH_WRAPPER(chdir, (const char *path), (target))

int access(const char *path, int mode)
{
	char mapped[PATH_MAX];
	const char *target;
	RESOLVE(access);
	if (chromium_sandbox_candidate_probe(path, mode)) {
		errno = ENOENT;
		return -1;
	}
	target = t1os_path(path, mapped);
	return target ? real_access(target, mode) : -1;
}

int stat(const char *path, struct stat *status)
{
	char mapped[PATH_MAX];
	const char *target;
	int result;
	RESOLVE(stat);
	target = t1os_path(path, mapped);
	if (!target)
		return -1;
	result = real_stat(target, status);
	if (result == 0 && chromium_executable_owner_probe(path))
		status->st_uid = getuid();
	return result;
}

int stat64(const char *path, struct stat64 *status)
{
	char mapped[PATH_MAX];
	const char *target;
	int result;
	RESOLVE(stat64);
	target = t1os_path(path, mapped);
	if (!target)
		return -1;
	result = real_stat64(target, status);
	if (result == 0 && chromium_executable_owner_probe(path))
		status->st_uid = getuid();
	return result;
}

/*
 * Chrome 150 is built against glibc's versioned large-file stat ABI and
 * imports __xstat64/__lxstat64 directly. Cover those entry points so ordinary
 * packaged runtime discovery observes the same T1OS paths as open and access.
 */
int __xstat(int version, const char *path, struct stat *status)
{
	char mapped[PATH_MAX];
	const char *target;
	int result;
	RESOLVE(__xstat);
	target = t1os_path(path, mapped);
	if (!target)
		return -1;
	result = real___xstat(version, target, status);
	if (result == 0 && chromium_executable_owner_probe(path))
		status->st_uid = getuid();
	return result;
}

int __xstat64(int version, const char *path, struct stat64 *status)
{
	char mapped[PATH_MAX];
	const char *target;
	int result;
	RESOLVE(__xstat64);
	target = t1os_path(path, mapped);
	if (!target)
		return -1;
	result = real___xstat64(version, target, status);
	if (result == 0 && chromium_executable_owner_probe(path))
		status->st_uid = getuid();
	return result;
}

int __lxstat64(int version, const char *path, struct stat64 *status)
{
	char mapped[PATH_MAX];
	const char *target;
	RESOLVE(__lxstat64);
	target = t1os_path(path, mapped);
	return target ? real___lxstat64(version, target, status) : -1;
}

int __fxstatat64(int version, int directory, const char *path,
		 struct stat64 *status, int flags)
{
	char mapped[PATH_MAX];
	const char *target;
	RESOLVE(__fxstatat64);
	target = t1os_path(path, mapped);
	return target ?
		real___fxstatat64(version, directory, target, status, flags) : -1;
}

int faccessat(int directory, const char *path, int mode, int flags)
{
	char mapped[PATH_MAX];
	const char *target;
	RESOLVE(faccessat);
	target = t1os_path(path, mapped);
	return target ? real_faccessat(directory, target, mode, flags) : -1;
}

int fchmodat(int directory, const char *path, mode_t mode, int flags)
{
	char mapped[PATH_MAX];
	const char *target;
	RESOLVE(fchmodat);
	target = t1os_path(path, mapped);
	return target ? real_fchmodat(directory, target, mode, flags) : -1;
}

int fchownat(int directory, const char *path, uid_t owner, gid_t group, int flags)
{
	char mapped[PATH_MAX];
	const char *target;
	RESOLVE(fchownat);
	target = t1os_path(path, mapped);
	return target ? real_fchownat(directory, target, owner, group, flags) : -1;
}

int fstatat(int directory, const char *path, struct stat *status, int flags)
{
	char mapped[PATH_MAX];
	const char *target;
	RESOLVE(fstatat);
	target = t1os_path(path, mapped);
	return target ? real_fstatat(directory, target, status, flags) : -1;
}

int fstatat64(int directory, const char *path, struct stat64 *status, int flags)
{
	char mapped[PATH_MAX];
	const char *target;
	RESOLVE(fstatat64);
	target = t1os_path(path, mapped);
	return target ? real_fstatat64(directory, target, status, flags) : -1;
}

int inotify_add_watch(int descriptor, const char *path, uint32_t mask)
{
	char mapped[PATH_MAX];
	const char *target;
	RESOLVE(inotify_add_watch);
	target = t1os_path(path, mapped);
	return target ? real_inotify_add_watch(descriptor, target, mask) : -1;
}

int mkdirat(int directory, const char *path, mode_t mode)
{
	char mapped[PATH_MAX];
	const char *target;
	RESOLVE(mkdirat);
	target = t1os_path(path, mapped);
	return target ? real_mkdirat(directory, target, mode) : -1;
}

int unlinkat(int directory, const char *path, int flags)
{
	char mapped[PATH_MAX];
	const char *target;
	RESOLVE(unlinkat);
	target = t1os_path(path, mapped);
	return target ? real_unlinkat(directory, target, flags) : -1;
}

DIR *opendir(const char *path)
{
	char mapped[PATH_MAX];
	const char *target;
	RESOLVE(opendir);
	target = t1os_path(path, mapped);
	return target ? real_opendir(target) : NULL;
}

ssize_t readlink(const char *path, char *buffer, size_t size)
{
	char mapped[PATH_MAX];
	const char *target;
	ssize_t result;
	RESOLVE(readlink);
	if (chromium_executable_readlink(path, buffer, size, &result))
		return result;
	if (chromium_singleton_readlink(AT_FDCWD, path, buffer, size, &result))
		return result;
	target = t1os_path(path, mapped);
	return target ? real_readlink(target, buffer, size) : -1;
}

ssize_t readlinkat(int directory, const char *path, char *buffer, size_t size)
{
	char mapped[PATH_MAX];
	const char *target;
	ssize_t result;
	RESOLVE(readlinkat);
	if (chromium_executable_readlink(path, buffer, size, &result))
		return result;
	if (chromium_singleton_readlink(directory, path, buffer, size, &result))
		return result;
	target = t1os_path(path, mapped);
	return target ? real_readlinkat(directory, target, buffer, size) : -1;
}

char *realpath(const char *path, char *resolved)
{
	char mapped[PATH_MAX];
	const char *target;
	RESOLVE(realpath);
	target = t1os_path(path, mapped);
	return target ? real_realpath(target, resolved) : NULL;
}

int rename(const char *old_path, const char *new_path)
{
	char old_mapped[PATH_MAX], new_mapped[PATH_MAX];
	const char *old_target, *new_target;
	RESOLVE(rename);
	old_target = t1os_path(old_path, old_mapped);
	new_target = t1os_path(new_path, new_mapped);
	return old_target && new_target ? real_rename(old_target, new_target) : -1;
}

int renameat(int old_directory, const char *old_path,
	     int new_directory, const char *new_path)
{
	char old_mapped[PATH_MAX], new_mapped[PATH_MAX];
	const char *old_target, *new_target;
	RESOLVE(renameat);
	old_target = t1os_path(old_path, old_mapped);
	new_target = t1os_path(new_path, new_mapped);
	return old_target && new_target ?
		real_renameat(old_directory, old_target, new_directory, new_target) : -1;
}

int renameat2(int old_directory, const char *old_path,
	      int new_directory, const char *new_path, unsigned int flags)
{
	char old_mapped[PATH_MAX], new_mapped[PATH_MAX];
	const char *old_target, *new_target;
	RESOLVE(renameat2);
	old_target = t1os_path(old_path, old_mapped);
	new_target = t1os_path(new_path, new_mapped);
	return old_target && new_target ?
		real_renameat2(old_directory, old_target, new_directory, new_target, flags) : -1;
}

int link(const char *old_path, const char *new_path)
{
	char old_mapped[PATH_MAX], new_mapped[PATH_MAX];
	const char *old_target, *new_target;
	RESOLVE(link);
	old_target = t1os_path(old_path, old_mapped);
	new_target = t1os_path(new_path, new_mapped);
	return old_target && new_target ? real_link(old_target, new_target) : -1;
}

int linkat(int old_directory, const char *old_path,
	   int new_directory, const char *new_path, int flags)
{
	char old_mapped[PATH_MAX], new_mapped[PATH_MAX];
	const char *old_target, *new_target;
	RESOLVE(linkat);
	old_target = t1os_path(old_path, old_mapped);
	new_target = t1os_path(new_path, new_mapped);
	return old_target && new_target ?
		real_linkat(old_directory, old_target, new_directory, new_target, flags) : -1;
}

int symlink(const char *target_path, const char *link_path)
{
	return chromium_singleton_create(target_path, link_path);
}

int symlinkat(const char *target_path, int directory, const char *link_path)
{
	if (directory != AT_FDCWD && link_path[0] != '/') {
		errno = EPERM;
		return -1;
	}
	return chromium_singleton_create(target_path, link_path);
}

int execve(const char *path, char *const arguments[], char *const environment[])
{
	char mapped[PATH_MAX];
	const char *target;
	RESOLVE(execve);
	target = t1os_path(path, mapped);
	return target ? real_execve(target, arguments, environment) : -1;
}

int execv(const char *path, char *const arguments[])
{
	char mapped[PATH_MAX];
	const char *target;
	RESOLVE(execv);
	target = t1os_path(path, mapped);
	return target ? real_execv(target, arguments) : -1;
}

int execvp(const char *file, char *const arguments[])
{
	char mapped[PATH_MAX];
	const char *target;
	RESOLVE(execvp);
	target = t1os_path(file, mapped);
	return target ? real_execvp(target, arguments) : -1;
}

int execvpe(const char *file, char *const arguments[], char *const environment[])
{
	char mapped[PATH_MAX];
	const char *target;
	RESOLVE(execvpe);
	target = t1os_path(file, mapped);
	return target ? real_execvpe(target, arguments, environment) : -1;
}

int execveat(int directory, const char *path, char *const arguments[],
	     char *const environment[], int flags)
{
	char mapped[PATH_MAX];
	const char *target;
	RESOLVE(execveat);
	target = t1os_path(path, mapped);
	return target ? real_execveat(directory, target, arguments, environment, flags) : -1;
}

#define T1OS_EXEC_ARGUMENT_LIMIT 256

int execl(const char *path, const char *argument, ...)
{
	char *arguments[T1OS_EXEC_ARGUMENT_LIMIT];
	char mapped[PATH_MAX];
	const char *target;
	va_list values;
	size_t count = 0;

	arguments[count++] = (char *)argument;
	va_start(values, argument);
	while (arguments[count - 1] != NULL) {
		if (count == T1OS_EXEC_ARGUMENT_LIMIT) {
			va_end(values);
			errno = E2BIG;
			return -1;
		}
		arguments[count++] = va_arg(values, char *);
	}
	va_end(values);
	RESOLVE(execv);
	target = t1os_path(path, mapped);
	return target ? real_execv(target, arguments) : -1;
}

int execlp(const char *file, const char *argument, ...)
{
	char *arguments[T1OS_EXEC_ARGUMENT_LIMIT];
	char mapped[PATH_MAX];
	const char *target;
	va_list values;
	size_t count = 0;

	arguments[count++] = (char *)argument;
	va_start(values, argument);
	while (arguments[count - 1] != NULL) {
		if (count == T1OS_EXEC_ARGUMENT_LIMIT) {
			va_end(values);
			errno = E2BIG;
			return -1;
		}
		arguments[count++] = va_arg(values, char *);
	}
	va_end(values);
	RESOLVE(execvp);
	target = t1os_path(file, mapped);
	return target ? real_execvp(target, arguments) : -1;
}

int execle(const char *path, const char *argument, ...)
{
	char *arguments[T1OS_EXEC_ARGUMENT_LIMIT];
	char *const *environment;
	char mapped[PATH_MAX];
	const char *target;
	va_list values;
	size_t count = 0;

	arguments[count++] = (char *)argument;
	va_start(values, argument);
	while (arguments[count - 1] != NULL) {
		if (count == T1OS_EXEC_ARGUMENT_LIMIT) {
			va_end(values);
			errno = E2BIG;
			return -1;
		}
		arguments[count++] = va_arg(values, char *);
	}
	environment = va_arg(values, char *const *);
	va_end(values);
	RESOLVE(execve);
	target = t1os_path(path, mapped);
	return target ? real_execve(target, arguments, environment) : -1;
}

int posix_spawn(pid_t *process, const char *path,
		const posix_spawn_file_actions_t *actions,
		const posix_spawnattr_t *attributes,
		char *const arguments[], char *const environment[])
{
	char mapped[PATH_MAX];
	const char *target;
	RESOLVE(posix_spawn);
	target = t1os_path(path, mapped);
	return target ? real_posix_spawn(process, target, actions, attributes,
					 arguments, environment) : EINVAL;
}

int posix_spawnp(pid_t *process, const char *file,
		 const posix_spawn_file_actions_t *actions,
		 const posix_spawnattr_t *attributes,
		 char *const arguments[], char *const environment[])
{
	char mapped[PATH_MAX];
	const char *target;
	RESOLVE(posix_spawnp);
	target = t1os_path(file, mapped);
	return target ? real_posix_spawnp(process, target, actions, attributes,
					  arguments, environment) : EINVAL;
}

void *dlopen(const char *path, int flags)
{
	char mapped[PATH_MAX];
	const char *target;
	RESOLVE(dlopen);
	if (!path)
		return real_dlopen(NULL, flags);
	target = t1os_path(path, mapped);
	return target ? real_dlopen(target, flags) : NULL;
}

static int translated_unix_socket(int fd, const struct sockaddr *address,
				  socklen_t length, bool connecting)
{
	struct sockaddr_un translated;
	char mapped[PATH_MAX];
	const char *target;

	if (!address || address->sa_family != AF_UNIX ||
	    length <= offsetof(struct sockaddr_un, sun_path))
		return -2;

	memset(&translated, 0, sizeof(translated));
	memcpy(&translated, address, length > sizeof(translated) ? sizeof(translated) : length);
	if (translated.sun_path[0] == '\0')
		return -2;
	target = t1os_path(translated.sun_path, mapped);
	if (!target)
		return -1;
	if (target == translated.sun_path)
		return -2;
	if (strlen(target) >= sizeof(translated.sun_path)) {
		errno = ENAMETOOLONG;
		return -1;
	}
	strcpy(translated.sun_path, target);
	length = offsetof(struct sockaddr_un, sun_path) + strlen(target) + 1;
	if (connecting) {
		RESOLVE(connect);
		return real_connect(fd, (const struct sockaddr *)&translated, length);
	}
	{
		RESOLVE(bind);
		return real_bind(fd, (const struct sockaddr *)&translated, length);
	}
}

int connect(int fd, const struct sockaddr *address, socklen_t length)
{
	int translated = translated_unix_socket(fd, address, length, true);
	if (translated != -2)
		return translated;
	RESOLVE(connect);
	return real_connect(fd, address, length);
}

int bind(int fd, const struct sockaddr *address, socklen_t length)
{
	int translated = translated_unix_socket(fd, address, length, false);
	if (translated != -2)
		return translated;
	RESOLVE(bind);
	return real_bind(fd, address, length);
}
