#ifndef T1_MEDIA_DECODE_SANDBOX_H
#define T1_MEDIA_DECODE_SANDBOX_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define T1_MEDIA_SANDBOX_REPORT_FORMAT 1u
#define T1_MEDIA_SANDBOX_MINIMUM_LANDLOCK_ABI 5u

#define T1_MEDIA_SANDBOX_FS_ALL_RIGHTS (1u << 0)
#define T1_MEDIA_SANDBOX_FS_RUNTIME_READ_ONLY (1u << 1)
#define T1_MEDIA_SANDBOX_FS_DEVICE_ONLY_WRITE (1u << 2)
#define T1_MEDIA_SANDBOX_SECCOMP_FILTER (1u << 3)
#define T1_MEDIA_SANDBOX_SECCOMP_TSYNC (1u << 4)
#define T1_MEDIA_SANDBOX_NETWORK_DENIED (1u << 5)
#define T1_MEDIA_SANDBOX_PROCESS_THREADS_ONLY (1u << 6)
#define T1_MEDIA_SANDBOX_FS_EPHEMERAL_CACHE (1u << 7)

#define T1_MEDIA_SANDBOX_REQUIRED_FLAGS ( \
    T1_MEDIA_SANDBOX_FS_ALL_RIGHTS | \
    T1_MEDIA_SANDBOX_FS_RUNTIME_READ_ONLY | \
    T1_MEDIA_SANDBOX_FS_DEVICE_ONLY_WRITE | \
    T1_MEDIA_SANDBOX_SECCOMP_FILTER | \
    T1_MEDIA_SANDBOX_SECCOMP_TSYNC | \
    T1_MEDIA_SANDBOX_NETWORK_DENIED | \
    T1_MEDIA_SANDBOX_PROCESS_THREADS_ONLY | \
    T1_MEDIA_SANDBOX_FS_EPHEMERAL_CACHE)

struct t1_media_sandbox_report {
    uint32_t format;
    uint32_t landlock_abi;
    uint32_t flags;
    uint32_t reserved;
    uint64_t rlimit_fsize;
    uint32_t rlimit_nofile;
    uint32_t rlimit_nproc;
    uint64_t rlimit_core;
};

enum t1_media_sandbox_path_mode {
    T1_MEDIA_SANDBOX_PATH_READ_ONLY = 1,
    T1_MEDIA_SANDBOX_PATH_DEVICE = 2,
    T1_MEDIA_SANDBOX_PATH_CACHE = 3,
};

struct t1_media_sandbox_path {
    const char *path;
    enum t1_media_sandbox_path_mode mode;
    bool required;
};

/*
 * Installs a deny-by-default Landlock filesystem domain.  This lower-level
 * entry point exists so the native proof test can use an isolated temporary
 * hierarchy; production workers call t1_media_install_worker_landlock().
 */
int t1_media_install_landlock(
    const struct t1_media_sandbox_path *paths,
    size_t path_count,
    unsigned *abi_version);

/*
 * Installs the fixed T1OS media-worker filesystem policy.  Missing optional
 * roots receive no rule and therefore remain inaccessible.
 */
int t1_media_install_worker_landlock(unsigned *abi_version);

/*
 * Installs the second-stage seccomp-BPF policy after the trusted VA driver has
 * initialized, but before the worker receives any untrusted media messages.
 */
int t1_media_install_worker_seccomp(void);

#endif
