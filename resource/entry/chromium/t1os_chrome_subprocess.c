#define _GNU_SOURCE

#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define T1OS_CHROMIUM_BINARY \
	"/the one/software/chromium/program/chrome"
#define T1OS_CHROMIUM_PATH_PROVIDER \
	"/.ephemeral/chromium/path-provider.so"
#define T1OS_CHROMIUM_LIBRARY_PATH_BASE \
	"/the one/software/chromium/libraries:" \
	"/the one/catalogue/graphics"
#define T1OS_CHROMIUM_LIBRARY_PATH_NVIDIA \
	"/the one/catalogue/graphics/nvidia:" \
	"/the one/catalogue/graphics:" \
	"/the one/software/chromium/libraries"
#define T1OS_CHROMIUM_GPU_LIBRARY_VARIABLE \
	"SANDBOX_GPU_LD_LIBRARY_PATH"
#define T1OS_CHROMIUM_GPU_EGL_VENDOR_VARIABLE \
	"SANDBOX_GPU_EGL_VENDOR_LIBRARY_FILENAMES"
#define T1OS_CHROMIUM_GPU_EGL_EXTERNAL_VARIABLE \
	"SANDBOX_GPU_EGL_EXTERNAL_PLATFORM_CONFIG_DIRS"
#define T1OS_CHROMIUM_GPU_GBM_PATH_VARIABLE \
	"SANDBOX_GPU_GBM_BACKENDS_PATH"
#define T1OS_CHROMIUM_GPU_GBM_BACKEND_VARIABLE \
	"SANDBOX_GPU_GBM_BACKEND"
#define T1OS_CHROMIUM_NVIDIA_EGL_VENDOR \
	"/the one/catalogue/graphics/nvidia/egl_vendor.d/10_nvidia.json"
#define T1OS_CHROMIUM_NVIDIA_GBM_PATH \
	"/the one/catalogue/graphics/nvidia/gbm"
#define T1OS_CHROMIUM_NVIDIA_GBM_BACKEND "nvidia-drm"
#define T1OS_CHROMIUM_LAUNCH_VARIABLE "T1OS_CHROMIUM_LAUNCH_ID"
#define T1OS_CHROMIUM_PROCESS_ROOT "/the one/drivers/processes"
#define T1OS_CHROMIUM_ENGINE_ID 1000

extern char **environ;

static int launch_id_valid(const char *value)
{
	size_t index;

	if (!value || strlen(value) != 32)
		return 0;
	for (index = 0; index < 32; index++) {
		if (!((value[index] >= '0' && value[index] <= '9') ||
		      (value[index] >= 'a' && value[index] <= 'f')))
			return 0;
	}
	return 1;
}

static const char *child_process_type(int argc, char **argv)
{
	static const char *const forbidden_switches[] = {
		"--no-sandbox",
		"--disable-setuid-sandbox",
		"--disable-namespace-sandbox",
		"--disable-seccomp-filter-sandbox",
	};
	const char *type = NULL;
	int index;
	size_t switch_index;

	for (index = 1; index < argc; index++) {
		const char *argument = argv[index];

		if (!argument)
			return NULL;
		for (switch_index = 0;
		     switch_index < sizeof(forbidden_switches) /
					    sizeof(forbidden_switches[0]);
		     switch_index++) {
			size_t length = strlen(forbidden_switches[switch_index]);

			if (strncmp(argument, forbidden_switches[switch_index],
				    length) == 0 &&
			    (argument[length] == '\0' ||
			     argument[length] == '='))
				return NULL;
		}
		if (strncmp(argument, "--type=", 7) != 0)
			continue;
		if (type || argument[7] == '\0')
			return NULL;
		type = argument + 7;
	}
	if (!type || strcmp(type, "zygote") == 0)
		return NULL;
	return type;
}

static int loader_environment_valid(void)
{
	size_t index;

	for (index = 0; environ && environ[index]; index++) {
		const char *entry = environ[index];

		if (strncmp(entry, "LD_", 3) == 0 &&
		    strcmp(entry,
			   "LD_PRELOAD=" T1OS_CHROMIUM_PATH_PROVIDER) != 0 &&
		    strcmp(entry,
			   "LD_LIBRARY_PATH="
			   T1OS_CHROMIUM_LIBRARY_PATH_BASE) != 0)
			return 0;
		if (strncmp(entry, "SANDBOX_LD_", 11) == 0 &&
		    strcmp(entry,
			   "SANDBOX_LD_PRELOAD="
			   T1OS_CHROMIUM_PATH_PROVIDER) != 0 &&
		    strcmp(entry,
			   "SANDBOX_LD_LIBRARY_PATH="
			   T1OS_CHROMIUM_LIBRARY_PATH_BASE) != 0)
			return 0;
		if (strncmp(entry, T1OS_CHROMIUM_GPU_LIBRARY_VARIABLE "=",
			    strlen(T1OS_CHROMIUM_GPU_LIBRARY_VARIABLE "=")) == 0 &&
		    strcmp(entry,
			   T1OS_CHROMIUM_GPU_LIBRARY_VARIABLE "="
			   T1OS_CHROMIUM_LIBRARY_PATH_NVIDIA) != 0)
			return 0;
		if (strncmp(entry, T1OS_CHROMIUM_GPU_EGL_VENDOR_VARIABLE "=",
			    strlen(T1OS_CHROMIUM_GPU_EGL_VENDOR_VARIABLE "=")) == 0 &&
		    strcmp(entry,
			   T1OS_CHROMIUM_GPU_EGL_VENDOR_VARIABLE "="
			   T1OS_CHROMIUM_NVIDIA_EGL_VENDOR) != 0)
			return 0;
		if (strncmp(entry, T1OS_CHROMIUM_GPU_EGL_EXTERNAL_VARIABLE "=",
			    strlen(T1OS_CHROMIUM_GPU_EGL_EXTERNAL_VARIABLE "=")) == 0 &&
		    strcmp(entry,
			   T1OS_CHROMIUM_GPU_EGL_EXTERNAL_VARIABLE "="
			   T1OS_CHROMIUM_NVIDIA_GBM_PATH) != 0)
			return 0;
		if (strncmp(entry, T1OS_CHROMIUM_GPU_GBM_PATH_VARIABLE "=",
			    strlen(T1OS_CHROMIUM_GPU_GBM_PATH_VARIABLE "=")) == 0 &&
		    strcmp(entry,
			   T1OS_CHROMIUM_GPU_GBM_PATH_VARIABLE "="
			   T1OS_CHROMIUM_NVIDIA_GBM_PATH) != 0)
			return 0;
		if (strncmp(entry, T1OS_CHROMIUM_GPU_GBM_BACKEND_VARIABLE "=",
			    strlen(T1OS_CHROMIUM_GPU_GBM_BACKEND_VARIABLE "=")) == 0 &&
		    strcmp(entry,
			   T1OS_CHROMIUM_GPU_GBM_BACKEND_VARIABLE "="
			   T1OS_CHROMIUM_NVIDIA_GBM_BACKEND) != 0)
			return 0;
		if (strncmp(entry, "__EGL_VENDOR_LIBRARY_FILENAMES=", 31) == 0 ||
		    strncmp(entry, "__EGL_EXTERNAL_PLATFORM_CONFIG_DIRS=", 36) == 0 ||
		    strncmp(entry, "GBM_BACKENDS_PATH=", 18) == 0 ||
		    strncmp(entry, "GBM_BACKEND=", 12) == 0)
			return 0;
		if (strncmp(entry, "GCONV_PATH=", 11) == 0 ||
		    strncmp(entry, "GLIBC_TUNABLES=", 15) == 0 ||
		    strncmp(entry, "LOCPATH=", 8) == 0 ||
		    strncmp(entry, "MALLOC_TRACE=", 13) == 0)
			return 0;
	}
	return 1;
}

static int unprivileged_identity_valid(void)
{
	gid_t effective_gid;
	gid_t real_gid;
	gid_t saved_gid;
	uid_t effective_uid;
	uid_t real_uid;
	uid_t saved_uid;

	if (getresuid(&real_uid, &effective_uid, &saved_uid) != 0 ||
	    getresgid(&real_gid, &effective_gid, &saved_gid) != 0)
		return 0;
	return real_uid == T1OS_CHROMIUM_ENGINE_ID &&
	       effective_uid == real_uid && saved_uid == real_uid &&
	       real_gid == T1OS_CHROMIUM_ENGINE_ID &&
	       effective_gid == real_gid && saved_gid == real_gid &&
	       getgroups(0, NULL) == 0;
}

static int parent_is_chromium(const char **parent_kind,
			      const char **rejection_reason)
{
	char command[16384];
	char executable[PATH_MAX];
	char process_path[PATH_MAX];
	char extra;
	size_t offset;
	size_t total = 0;
	int descriptor;
	const char *type = NULL;
	ssize_t length;
	int written;

	if (parent_kind)
		*parent_kind = "invalid";
	if (rejection_reason)
		*rejection_reason = "unknown";
	written = snprintf(process_path, sizeof(process_path), "%s/%ld/exe",
			   T1OS_CHROMIUM_PROCESS_ROOT, (long)getppid());
	if (written < 0 || written >= (int)sizeof(process_path))
		return 0;
	length = readlink(process_path, executable, sizeof(executable) - 1);
	if (length <= 0 || length >= (ssize_t)sizeof(executable)) {
		if (rejection_reason)
			*rejection_reason = "executable-read";
		return 0;
	}
	executable[length] = '\0';
	if (strcmp(executable, T1OS_CHROMIUM_BINARY) != 0) {
		if (rejection_reason)
			*rejection_reason = "executable-mismatch";
		return 0;
	}

	written = snprintf(process_path, sizeof(process_path), "%s/%ld/cmdline",
			   T1OS_CHROMIUM_PROCESS_ROOT, (long)getppid());
	if (written < 0 || written >= (int)sizeof(process_path))
		return 0;
	descriptor = open(process_path, O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
	if (descriptor < 0) {
		if (rejection_reason)
			*rejection_reason = "command-open";
		return 0;
	}
	while (total < sizeof(command) - 1) {
		length = read(descriptor, command + total,
			      sizeof(command) - 1 - total);
		if (length < 0 && errno == EINTR)
			continue;
		if (length < 0) {
			close(descriptor);
			if (rejection_reason)
				*rejection_reason = "command-read";
			return 0;
		}
		if (length == 0)
			break;
		total += (size_t)length;
	}
	length = read(descriptor, &extra, 1);
	if (close(descriptor) != 0 || length != 0 || total == 0 ||
	    command[total - 1] != '\0') {
		if (rejection_reason)
			*rejection_reason = "command-shape";
		return 0;
	}
	command[total] = '\0';
	if (command[0] == '\0') {
		if (rejection_reason)
			*rejection_reason = "argv0-empty";
		return 0;
	}
	offset = strlen(command) + 1;
	while (offset < total) {
		const char *argument = command + offset;
		const char *terminator =
			memchr(argument, '\0', total - offset);

		if (!terminator) {
			if (rejection_reason)
				*rejection_reason = "argument-shape";
			return 0;
		}
		if (strncmp(argument, "--type=", 7) == 0) {
			if (type || argument[7] == '\0') {
				if (rejection_reason)
					*rejection_reason = "type-shape";
				return 0;
			}
			type = argument + 7;
		}
		offset = (size_t)(terminator - command) + 1;
	}
	if (offset != total) {
		if (rejection_reason)
			*rejection_reason = "argument-boundary";
		return 0;
	}

	/*
	 * M150 rewrites argv[0], so it is not an executable identity credential.
	 * The process driver's immutable executable link above is authoritative.
	 * Accept that exact Chrome executable only as either the untyped browser or its one
	 * typed zygote. Renderer, GPU, Network Service, and arbitrary typed Chrome
	 * processes are not valid parents for this exec boundary.
	 */
	if (!type) {
		if (parent_kind)
			*parent_kind = "browser";
		return 1;
	}
	if (strcmp(type, "zygote") == 0) {
		if (parent_kind)
			*parent_kind = "zygote";
		return 1;
	}
	if (rejection_reason)
		*rejection_reason = "typed-parent";
	return 0;
}

/*
 * Chromium's direct subprocess path uses this helper for unprivileged GPU and
 * utility children. The independent SUID-zygote path restores unsafe loader
 * variables inside chrome-sandbox after dropping root. Validate the browser's
 * matching saved values, its exact parent identity, and the child boundary
 * here, then immediately replace this process with the measured Chrome
 * executable. Only a GPU child may select the NVIDIA-specific loader path.
 *
 * Keep argv[0] unchanged. Chromium uses the configured subprocess path for
 * direct utility launches, while the kernel executable identity continues to
 * identify the real Chrome image after execve().
 */
int main(int argc, char **argv)
{
	char working_directory[PATH_MAX] = "(unavailable)";
	const char *launch_id;
	const char *gpu_egl_external;
	const char *gpu_egl_vendor;
	const char *gpu_gbm_backend;
	const char *gpu_gbm_path;
	const char *gpu_library_path;
	const char *library_path;
	const char *saved_library_path;
	const char *parent_kind = "invalid";
	const char *parent_rejection = "unknown";
	const char *path_provider;
	const char *process_type;
	int gpu_contract_fields;
	int use_nvidia_gpu;

	if (argc < 1 || !argv || !argv[0]) {
		fputs("t1os-chrome-subprocess: invalid argument vector\n", stderr);
		return 126;
	}

	if (!getcwd(working_directory, sizeof(working_directory)))
		strcpy(working_directory, "(unavailable)");
	if (argc == 2 && strcmp(argv[1], "--t1os-sandbox-probe") == 0)
		return 0;
	process_type = child_process_type(argc, argv);
	if (!process_type) {
		fputs("t1os-chrome-subprocess: invalid child process type\n",
		      stderr);
		return 126;
	}
	if (!unprivileged_identity_valid()) {
		fputs("t1os-chrome-subprocess: invalid child identity\n", stderr);
		return 126;
	}
	if (!loader_environment_valid()) {
		fputs("t1os-chrome-subprocess: unsafe loader environment\n",
		      stderr);
		return 126;
	}
	if (!parent_is_chromium(&parent_kind, &parent_rejection)) {
		fputs("t1os-chrome-subprocess: invalid Chromium parent\n",
		      stderr);
		fprintf(stderr,
			"t1os-chrome-subprocess: rejected parent pid=%ld "
			"reason=%s\n",
			(long)getppid(), parent_rejection);
		return 126;
	}

	path_provider = getenv("SANDBOX_LD_PRELOAD");
	saved_library_path = getenv("SANDBOX_LD_LIBRARY_PATH");
	gpu_library_path = getenv(T1OS_CHROMIUM_GPU_LIBRARY_VARIABLE);
	gpu_egl_vendor = getenv(T1OS_CHROMIUM_GPU_EGL_VENDOR_VARIABLE);
	gpu_egl_external = getenv(T1OS_CHROMIUM_GPU_EGL_EXTERNAL_VARIABLE);
	gpu_gbm_path = getenv(T1OS_CHROMIUM_GPU_GBM_PATH_VARIABLE);
	gpu_gbm_backend = getenv(T1OS_CHROMIUM_GPU_GBM_BACKEND_VARIABLE);
	launch_id = getenv(T1OS_CHROMIUM_LAUNCH_VARIABLE);
	if (!path_provider ||
	    strcmp(path_provider, T1OS_CHROMIUM_PATH_PROVIDER) != 0) {
		fputs("t1os-chrome-subprocess: invalid saved path provider\n",
		      stderr);
		return 126;
	}
	if (!saved_library_path ||
	    strcmp(saved_library_path, T1OS_CHROMIUM_LIBRARY_PATH_BASE) != 0) {
		fputs("t1os-chrome-subprocess: invalid saved library path\n",
		      stderr);
		return 126;
	}
	if (gpu_library_path &&
	    strcmp(gpu_library_path, T1OS_CHROMIUM_LIBRARY_PATH_NVIDIA) != 0) {
		fputs("t1os-chrome-subprocess: invalid GPU library path\n",
		      stderr);
		return 126;
	}
	gpu_contract_fields = (gpu_library_path != NULL) +
		(gpu_egl_vendor != NULL) + (gpu_egl_external != NULL) +
		(gpu_gbm_path != NULL) + (gpu_gbm_backend != NULL);
	if (gpu_contract_fields != 0 && gpu_contract_fields != 5) {
		fputs("t1os-chrome-subprocess: incomplete GPU graphics contract\n",
		      stderr);
		return 126;
	}
	if (!launch_id_valid(launch_id)) {
		fputs("t1os-chrome-subprocess: invalid launch scope\n", stderr);
		return 126;
	}
	use_nvidia_gpu = strcmp(process_type, "gpu-process") == 0 &&
		gpu_contract_fields == 5;
	library_path = saved_library_path;
	if (use_nvidia_gpu)
		library_path = T1OS_CHROMIUM_LIBRARY_PATH_NVIDIA;

	fprintf(stderr,
		"t1os-chrome-subprocess: entered uid=%ld euid=%ld cwd=%s "
		"chrome=%s libraries=%s process-alias=%s parent=%s "
		"child-type=%s launch-scope=yes\n",
		(long)getuid(), (long)geteuid(), working_directory,
		access(T1OS_CHROMIUM_BINARY, F_OK) == 0 ? "yes" : "no",
		strcmp(library_path, T1OS_CHROMIUM_LIBRARY_PATH_NVIDIA) == 0 ?
			"nvidia-gpu" : "base",
		access(T1OS_CHROMIUM_PROCESS_ROOT "/self/fd", F_OK) == 0 ?
			"yes" : "no",
		parent_kind,
		process_type);

	if (setenv("LD_PRELOAD", path_provider, 1) != 0) {
		fprintf(stderr,
			"t1os-chrome-subprocess: could not restore path provider: %s\n",
			strerror(errno));
		return 126;
	}
	if (setenv("LD_LIBRARY_PATH", library_path, 1) != 0) {
		fprintf(stderr,
			"t1os-chrome-subprocess: could not restore library path: %s\n",
			strerror(errno));
		return 126;
	}
	if (use_nvidia_gpu &&
	    (setenv("__EGL_VENDOR_LIBRARY_FILENAMES",
		    T1OS_CHROMIUM_NVIDIA_EGL_VENDOR, 1) != 0 ||
	     setenv("__EGL_EXTERNAL_PLATFORM_CONFIG_DIRS",
		    T1OS_CHROMIUM_NVIDIA_GBM_PATH, 1) != 0 ||
	     setenv("GBM_BACKENDS_PATH", T1OS_CHROMIUM_NVIDIA_GBM_PATH, 1) != 0 ||
	     setenv("GBM_BACKEND", T1OS_CHROMIUM_NVIDIA_GBM_BACKEND, 1) != 0)) {
		fprintf(stderr,
			"t1os-chrome-subprocess: could not install GPU graphics contract: %s\n",
			strerror(errno));
		return 126;
	}
	if (!use_nvidia_gpu &&
	    (unsetenv("__EGL_VENDOR_LIBRARY_FILENAMES") != 0 ||
	     unsetenv("__EGL_EXTERNAL_PLATFORM_CONFIG_DIRS") != 0 ||
	     unsetenv("GBM_BACKENDS_PATH") != 0 ||
	     unsetenv("GBM_BACKEND") != 0)) {
		fprintf(stderr,
			"t1os-chrome-subprocess: could not clear GPU graphics environment: %s\n",
			strerror(errno));
		return 126;
	}
	if (unsetenv(T1OS_CHROMIUM_GPU_LIBRARY_VARIABLE) != 0) {
		fprintf(stderr,
			"t1os-chrome-subprocess: could not clear GPU library contract: %s\n",
			strerror(errno));
		return 126;
	}
	if (unsetenv(T1OS_CHROMIUM_GPU_EGL_VENDOR_VARIABLE) != 0 ||
	    unsetenv(T1OS_CHROMIUM_GPU_EGL_EXTERNAL_VARIABLE) != 0 ||
	    unsetenv(T1OS_CHROMIUM_GPU_GBM_PATH_VARIABLE) != 0 ||
	    unsetenv(T1OS_CHROMIUM_GPU_GBM_BACKEND_VARIABLE) != 0) {
		fprintf(stderr,
			"t1os-chrome-subprocess: could not clear saved GPU graphics contract: %s\n",
			strerror(errno));
		return 126;
	}

	execve(T1OS_CHROMIUM_BINARY, argv, environ);
	fprintf(stderr, "t1os-chrome-subprocess: execve failed: %s\n",
		strerror(errno));
	return 127;
}
