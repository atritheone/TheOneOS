#define _GNU_SOURCE
#define _LARGEFILE64_SOURCE

#include <dirent.h>
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

/*
 * NVIDIA's closed userspace components retain Linux's conventional /dev
 * device names even when paired with the open kernel modules. T1OS deliberately
 * has no /dev runtime tree: devtmpfs is mounted at /the one/drivers/nodes.
 *
 * This provider is preloaded into measured NVIDIA graphics and video clients
 * and translates the NVIDIA KMS/control nodes, the exact UVM node required by
 * CUDA/NVDEC, bounded DRM card/render names, and the procfs/sysfs discovery
 * trees used by NVIDIA's CUDA userspace. The one cosmetic CUDA thread-name
 * write is absorbed by an anonymous in-memory descriptor because T1OS mounts
 * procfs read-only. The provider creates no aliases and grants no additional
 * kernel permission; the T1OS read-only mounts and LSM still authorize every
 * translated destination per process.
 */

#define T1OS_DEVICE_ROOT "/the one/drivers/nodes"
#define T1OS_PROCESS_ROOT "/the one/drivers/processes"
#define T1OS_STATE_ROOT "/the one/drivers/state"
#define T1OS_CUDA_THREAD_NAME "t1os-cuda-thread-name"

static bool decimal_suffix(const char *value)
{
	if (!value || *value < '0' || *value > '9')
		return false;
	while (*value >= '0' && *value <= '9')
		value++;
	return *value == '\0';
}

static bool nvidia_node_name(const char *name)
{
	if (!name)
		return false;
	if (!strcmp(name, "nvidiactl") ||
	    !strcmp(name, "nvidia-modeset") ||
	    !strcmp(name, "nvidia-uvm"))
		return true;
	return !strncmp(name, "nvidia", 6) && decimal_suffix(name + 6);
}

static bool drm_node_name(const char *name)
{
	if (!name)
		return false;
	if (!strncmp(name, "card", 4))
		return decimal_suffix(name + 4);
	if (!strncmp(name, "renderD", 7))
		return decimal_suffix(name + 7);
	if (!strncmp(name, "controlD", 8))
		return decimal_suffix(name + 8);
	return false;
}

/*
 * Keep a translated procfs/sysfs child inside its selected T1OS mount.
 * NVIDIA uses ordinary absolute children, so "." and ".." components are
 * unnecessary and could otherwise escape the bounded mount after VFS path
 * normalization.
 */
static bool bounded_tree_suffix(const char *suffix)
{
	const char *component;
	const char *end;
	size_t length;

	if (!suffix || *suffix != '/')
		return false;

	component = suffix + 1;
	while (*component) {
		while (*component == '/')
			component++;
		if (!*component)
			break;

		end = component;
		while (*end && *end != '/')
			end++;
		length = (size_t)(end - component);
		if ((length == 1 && component[0] == '.') ||
		    (length == 2 && component[0] == '.' &&
		     component[1] == '.'))
			return false;
		component = end;
	}

	return true;
}

/*
 * CUDA names each worker by opening its own procfs comm attribute with
 * O_WRONLY|O_CREAT|O_TRUNC. T1OS intentionally mounts the process tree
 * read-only, and NVIDIA 610 treats the resulting EROFS as a fatal cuInit
 * operating-system error even though the name is cosmetic. Accept only one
 * of the process's exact numeric thread attributes and absorb that write in
 * an anonymous memfd. This does not ask the LSM for unrelated device-node
 * authority and no other procfs write is redirected.
 */
static bool cuda_thread_name_path(const char *path)
{
	static const char prefix[] = "/proc/self/task/";
	const char *thread;

	if (!path || strncmp(path, prefix, sizeof(prefix) - 1))
		return false;

	thread = path + sizeof(prefix) - 1;
	if (*thread < '0' || *thread > '9')
		return false;
	while (*thread >= '0' && *thread <= '9')
		thread++;
	return !strcmp(thread, "/comm");
}

static bool cuda_thread_name_open(const char *path, int flags)
{
	return (flags & O_ACCMODE) == O_WRONLY &&
	       (flags & (O_CREAT | O_TRUNC)) == (O_CREAT | O_TRUNC) &&
	       cuda_thread_name_path(path);
}

static int cuda_thread_name_descriptor(int flags)
{
	unsigned int options = 0;

	if (flags & O_CLOEXEC)
		options |= MFD_CLOEXEC;
	return memfd_create(T1OS_CUDA_THREAD_NAME, options);
}

static FILE *cuda_thread_name_stream(const char *mode)
{
	FILE *stream;
	int descriptor;
	int saved_errno;

	descriptor = memfd_create(T1OS_CUDA_THREAD_NAME, MFD_CLOEXEC);
	if (descriptor < 0)
		return NULL;
	stream = fdopen(descriptor, mode);
	if (stream)
		return stream;

	saved_errno = errno;
	close(descriptor);
	errno = saved_errno;
	return NULL;
}

static const char *t1os_nvidia_path(const char *path, char output[PATH_MAX])
{
	int written;

	if (!path) {
		errno = EFAULT;
		return NULL;
	}

	if (!strcmp(path, "/dev/dri")) {
		written = snprintf(output, PATH_MAX, "%s/dri", T1OS_DEVICE_ROOT);
	} else if (!strncmp(path, "/dev/dri/", 9) &&
		   drm_node_name(path + 9)) {
		written = snprintf(output, PATH_MAX, "%s/dri/%s",
				   T1OS_DEVICE_ROOT, path + 9);
	} else if (!strncmp(path, "/dev/", 5) &&
		   nvidia_node_name(path + 5)) {
		written = snprintf(output, PATH_MAX, "%s/%s",
				   T1OS_DEVICE_ROOT, path + 5);
	} else if (!strcmp(path, "/proc")) {
		written = snprintf(output, PATH_MAX, "%s", T1OS_PROCESS_ROOT);
	} else if (!strncmp(path, "/proc/", 6)) {
		if (!bounded_tree_suffix(path + 5)) {
			errno = EINVAL;
			return NULL;
		}
		written = snprintf(output, PATH_MAX, "%s%s",
				   T1OS_PROCESS_ROOT, path + 5);
	} else if (!strcmp(path, "/sys")) {
		written = snprintf(output, PATH_MAX, "%s", T1OS_STATE_ROOT);
	} else if (!strncmp(path, "/sys/", 5)) {
		if (!bounded_tree_suffix(path + 4)) {
			errno = EINVAL;
			return NULL;
		}
		written = snprintf(output, PATH_MAX, "%s%s",
				   T1OS_STATE_ROOT, path + 4);
	} else {
		return path;
	}

	if (written < 0 || written >= PATH_MAX) {
		errno = ENAMETOOLONG;
		return NULL;
	}
	return output;
}

#define RESOLVE(symbol) \
	static __typeof__(symbol) *real_##symbol; \
	if (!real_##symbol) \
		real_##symbol = dlsym(RTLD_NEXT, #symbol)

int open(const char *path, int flags, ...)
{
	mode_t mode = 0;
	char mapped[PATH_MAX];
	const char *target;

	RESOLVE(open);
	if (flags & (O_CREAT | O_TMPFILE)) {
		va_list arguments;
		va_start(arguments, flags);
		mode = (mode_t)va_arg(arguments, int);
		va_end(arguments);
	}
	if (cuda_thread_name_open(path, flags))
		return cuda_thread_name_descriptor(flags);
	target = t1os_nvidia_path(path, mapped);
	if (!target)
		return -1;
	return flags & (O_CREAT | O_TMPFILE) ?
		real_open(target, flags, mode) : real_open(target, flags);
}

int open64(const char *path, int flags, ...)
{
	mode_t mode = 0;
	char mapped[PATH_MAX];
	const char *target;

	RESOLVE(open64);
	if (flags & (O_CREAT | O_TMPFILE)) {
		va_list arguments;
		va_start(arguments, flags);
		mode = (mode_t)va_arg(arguments, int);
		va_end(arguments);
	}
	if (cuda_thread_name_open(path, flags))
		return cuda_thread_name_descriptor(flags);
	target = t1os_nvidia_path(path, mapped);
	if (!target)
		return -1;
	return flags & (O_CREAT | O_TMPFILE) ?
		real_open64(target, flags, mode) : real_open64(target, flags);
}

int openat(int directory, const char *path, int flags, ...)
{
	mode_t mode = 0;
	char mapped[PATH_MAX];
	const char *target;

	RESOLVE(openat);
	if (flags & (O_CREAT | O_TMPFILE)) {
		va_list arguments;
		va_start(arguments, flags);
		mode = (mode_t)va_arg(arguments, int);
		va_end(arguments);
	}
	if (cuda_thread_name_open(path, flags))
		return cuda_thread_name_descriptor(flags);
	target = t1os_nvidia_path(path, mapped);
	if (!target)
		return -1;
	return flags & (O_CREAT | O_TMPFILE) ?
		real_openat(directory, target, flags, mode) :
		real_openat(directory, target, flags);
}

int openat64(int directory, const char *path, int flags, ...)
{
	mode_t mode = 0;
	char mapped[PATH_MAX];
	const char *target;

	RESOLVE(openat64);
	if (flags & (O_CREAT | O_TMPFILE)) {
		va_list arguments;
		va_start(arguments, flags);
		mode = (mode_t)va_arg(arguments, int);
		va_end(arguments);
	}
	if (cuda_thread_name_open(path, flags))
		return cuda_thread_name_descriptor(flags);
	target = t1os_nvidia_path(path, mapped);
	if (!target)
		return -1;
	return flags & (O_CREAT | O_TMPFILE) ?
		real_openat64(directory, target, flags, mode) :
		real_openat64(directory, target, flags);
}

FILE *fopen(const char *path, const char *mode)
{
	char mapped[PATH_MAX];
	const char *target;
	RESOLVE(fopen);
	if (mode && mode[0] == 'w' && cuda_thread_name_path(path))
		return cuda_thread_name_stream(mode);
	target = t1os_nvidia_path(path, mapped);
	return target ? real_fopen(target, mode) : NULL;
}

FILE *fopen64(const char *path, const char *mode)
{
	char mapped[PATH_MAX];
	const char *target;
	RESOLVE(fopen64);
	if (mode && mode[0] == 'w' && cuda_thread_name_path(path))
		return cuda_thread_name_stream(mode);
	target = t1os_nvidia_path(path, mapped);
	return target ? real_fopen64(target, mode) : NULL;
}

int access(const char *path, int mode)
{
	char mapped[PATH_MAX];
	const char *target;
	RESOLVE(access);
	target = t1os_nvidia_path(path, mapped);
	return target ? real_access(target, mode) : -1;
}

int faccessat(int directory, const char *path, int mode, int flags)
{
	char mapped[PATH_MAX];
	const char *target;
	RESOLVE(faccessat);
	target = t1os_nvidia_path(path, mapped);
	return target ? real_faccessat(directory, target, mode, flags) : -1;
}

int stat(const char *path, struct stat *status)
{
	char mapped[PATH_MAX];
	const char *target;
	RESOLVE(stat);
	target = t1os_nvidia_path(path, mapped);
	return target ? real_stat(target, status) : -1;
}

int stat64(const char *path, struct stat64 *status)
{
	char mapped[PATH_MAX];
	const char *target;
	RESOLVE(stat64);
	target = t1os_nvidia_path(path, mapped);
	return target ? real_stat64(target, status) : -1;
}

int __xstat(int version, const char *path, struct stat *status)
{
	char mapped[PATH_MAX];
	const char *target;
	RESOLVE(__xstat);
	target = t1os_nvidia_path(path, mapped);
	return target ? real___xstat(version, target, status) : -1;
}

int __xstat64(int version, const char *path, struct stat64 *status)
{
	char mapped[PATH_MAX];
	const char *target;
	RESOLVE(__xstat64);
	target = t1os_nvidia_path(path, mapped);
	return target ? real___xstat64(version, target, status) : -1;
}

int fstatat(int directory, const char *path, struct stat *status, int flags)
{
	char mapped[PATH_MAX];
	const char *target;
	RESOLVE(fstatat);
	target = t1os_nvidia_path(path, mapped);
	return target ? real_fstatat(directory, target, status, flags) : -1;
}

int fstatat64(int directory, const char *path, struct stat64 *status,
	      int flags)
{
	char mapped[PATH_MAX];
	const char *target;
	RESOLVE(fstatat64);
	target = t1os_nvidia_path(path, mapped);
	return target ?
		real_fstatat64(directory, target, status, flags) : -1;
}

DIR *opendir(const char *path)
{
	char mapped[PATH_MAX];
	const char *target;
	RESOLVE(opendir);
	target = t1os_nvidia_path(path, mapped);
	return target ? real_opendir(target) : NULL;
}

ssize_t readlink(const char *path, char *buffer, size_t size)
{
	char mapped[PATH_MAX];
	const char *target;
	RESOLVE(readlink);
	target = t1os_nvidia_path(path, mapped);
	return target ? real_readlink(target, buffer, size) : -1;
}

ssize_t readlinkat(int directory, const char *path, char *buffer, size_t size)
{
	char mapped[PATH_MAX];
	const char *target;
	RESOLVE(readlinkat);
	target = t1os_nvidia_path(path, mapped);
	return target ?
		real_readlinkat(directory, target, buffer, size) : -1;
}

char *realpath(const char *path, char *resolved)
{
	char mapped[PATH_MAX];
	const char *target;
	RESOLVE(realpath);
	target = t1os_nvidia_path(path, mapped);
	return target ? real_realpath(target, resolved) : NULL;
}
