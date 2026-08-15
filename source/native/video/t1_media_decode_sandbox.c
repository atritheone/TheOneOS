#define _GNU_SOURCE

#include "t1_media_decode_sandbox.h"

#include <errno.h>
#include <fcntl.h>
#include <linux/audit.h>
#include <linux/filter.h>
#include <linux/landlock.h>
#include <linux/sched.h>
#include <linux/seccomp.h>
#include <stddef.h>
#include <stdint.h>
#include <sys/prctl.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <unistd.h>

#ifndef LANDLOCK_ACCESS_FS_IOCTL_DEV
#define LANDLOCK_ACCESS_FS_IOCTL_DEV (1ULL << 15)
#endif

#ifndef LANDLOCK_ACCESS_NET_BIND_TCP
#define LANDLOCK_ACCESS_NET_BIND_TCP (1ULL << 0)
#endif

#ifndef LANDLOCK_ACCESS_NET_CONNECT_TCP
#define LANDLOCK_ACCESS_NET_CONNECT_TCP (1ULL << 1)
#endif

#ifndef SECCOMP_RET_KILL_PROCESS
#define SECCOMP_RET_KILL_PROCESS SECCOMP_RET_KILL
#endif

#ifndef SECCOMP_FILTER_FLAG_TSYNC
#define SECCOMP_FILTER_FLAG_TSYNC (1UL << 0)
#endif

#ifndef __X32_SYSCALL_BIT
#define __X32_SYSCALL_BIT 0x40000000U
#endif

#if !defined(__x86_64__)
#error "The T1OS media sandbox syscall policy is defined for x86_64 only."
#endif

#define T1_MEDIA_LANDLOCK_MINIMUM_ABI 5

#define T1_MEDIA_LANDLOCK_ALL_FS_RIGHTS ( \
    LANDLOCK_ACCESS_FS_EXECUTE | \
    LANDLOCK_ACCESS_FS_WRITE_FILE | \
    LANDLOCK_ACCESS_FS_READ_FILE | \
    LANDLOCK_ACCESS_FS_READ_DIR | \
    LANDLOCK_ACCESS_FS_REMOVE_DIR | \
    LANDLOCK_ACCESS_FS_REMOVE_FILE | \
    LANDLOCK_ACCESS_FS_MAKE_CHAR | \
    LANDLOCK_ACCESS_FS_MAKE_DIR | \
    LANDLOCK_ACCESS_FS_MAKE_REG | \
    LANDLOCK_ACCESS_FS_MAKE_SOCK | \
    LANDLOCK_ACCESS_FS_MAKE_FIFO | \
    LANDLOCK_ACCESS_FS_MAKE_BLOCK | \
    LANDLOCK_ACCESS_FS_MAKE_SYM | \
    LANDLOCK_ACCESS_FS_REFER | \
    LANDLOCK_ACCESS_FS_TRUNCATE | \
    LANDLOCK_ACCESS_FS_IOCTL_DEV)

#define T1_MEDIA_LANDLOCK_READ_RIGHTS ( \
    LANDLOCK_ACCESS_FS_READ_FILE | \
    LANDLOCK_ACCESS_FS_READ_DIR)

#define T1_MEDIA_LANDLOCK_DEVICE_RIGHTS ( \
    T1_MEDIA_LANDLOCK_READ_RIGHTS | \
    LANDLOCK_ACCESS_FS_WRITE_FILE | \
    LANDLOCK_ACCESS_FS_IOCTL_DEV)

#define T1_MEDIA_LANDLOCK_CACHE_RIGHTS ( \
    T1_MEDIA_LANDLOCK_READ_RIGHTS | \
    LANDLOCK_ACCESS_FS_WRITE_FILE | \
    LANDLOCK_ACCESS_FS_REMOVE_DIR | \
    LANDLOCK_ACCESS_FS_REMOVE_FILE | \
    LANDLOCK_ACCESS_FS_MAKE_DIR | \
    LANDLOCK_ACCESS_FS_MAKE_REG | \
    LANDLOCK_ACCESS_FS_REFER | \
    LANDLOCK_ACCESS_FS_TRUNCATE)

struct t1_media_landlock_ruleset_attr {
    uint64_t handled_access_fs;
    uint64_t handled_access_net;
};

static int
t1_media_landlock_create_ruleset(
    const void *attributes,
    size_t size,
    uint32_t flags)
{
    return (int)syscall(
        SYS_landlock_create_ruleset,
        attributes,
        size,
        flags);
}

static int
t1_media_landlock_add_path(
    int ruleset,
    const struct t1_media_sandbox_path *path)
{
    int descriptor = open(
        path->path,
        O_PATH | O_CLOEXEC | O_NOFOLLOW);
    if (descriptor < 0) {
        if (!path->required && errno == ENOENT)
            return 0;
        return -1;
    }

    struct stat status = {0};
    if (fstat(descriptor, &status) < 0) {
        int saved_errno = errno;
        close(descriptor);
        errno = saved_errno;
        return -1;
    }

    uint64_t allowed_access;
    if (S_ISDIR(status.st_mode)) {
        allowed_access =
            path->mode == T1_MEDIA_SANDBOX_PATH_DEVICE
                ? T1_MEDIA_LANDLOCK_DEVICE_RIGHTS
                : path->mode == T1_MEDIA_SANDBOX_PATH_CACHE
                    ? T1_MEDIA_LANDLOCK_CACHE_RIGHTS
                    : T1_MEDIA_LANDLOCK_READ_RIGHTS;
    } else {
        allowed_access = LANDLOCK_ACCESS_FS_READ_FILE;
        if (path->mode == T1_MEDIA_SANDBOX_PATH_DEVICE)
            allowed_access |=
                LANDLOCK_ACCESS_FS_WRITE_FILE |
                LANDLOCK_ACCESS_FS_IOCTL_DEV;
        else if (path->mode == T1_MEDIA_SANDBOX_PATH_CACHE)
            allowed_access |=
                LANDLOCK_ACCESS_FS_WRITE_FILE |
                LANDLOCK_ACCESS_FS_TRUNCATE;
    }

    struct landlock_path_beneath_attr rule = {
        .allowed_access = allowed_access,
        .parent_fd = descriptor,
    };
    int result = (int)syscall(
        SYS_landlock_add_rule,
        ruleset,
        LANDLOCK_RULE_PATH_BENEATH,
        &rule,
        0);
    int saved_errno = errno;
    close(descriptor);
    errno = saved_errno;
    return result;
}

int
t1_media_install_landlock(
    const struct t1_media_sandbox_path *paths,
    size_t path_count,
    unsigned *abi_version)
{
    if ((!paths && path_count) ||
        prctl(PR_GET_NO_NEW_PRIVS, 0, 0, 0, 0) != 1) {
        errno = EPERM;
        return -1;
    }

    int abi = t1_media_landlock_create_ruleset(
        NULL,
        0,
        LANDLOCK_CREATE_RULESET_VERSION);
    if (abi < T1_MEDIA_LANDLOCK_MINIMUM_ABI) {
        if (abi >= 0)
            errno = EOPNOTSUPP;
        return -1;
    }

    struct t1_media_landlock_ruleset_attr attributes = {
        .handled_access_fs = T1_MEDIA_LANDLOCK_ALL_FS_RIGHTS,
        .handled_access_net =
            LANDLOCK_ACCESS_NET_BIND_TCP |
            LANDLOCK_ACCESS_NET_CONNECT_TCP,
    };
    int ruleset = t1_media_landlock_create_ruleset(
        &attributes,
        sizeof(attributes),
        0);
    if (ruleset < 0)
        return -1;

    for (size_t index = 0; index < path_count; ++index) {
        if (!paths[index].path ||
            (paths[index].mode !=
                 T1_MEDIA_SANDBOX_PATH_READ_ONLY &&
             paths[index].mode !=
                 T1_MEDIA_SANDBOX_PATH_DEVICE &&
             paths[index].mode !=
                 T1_MEDIA_SANDBOX_PATH_CACHE) ||
            t1_media_landlock_add_path(
                ruleset,
                &paths[index]) < 0) {
            int saved_errno =
                errno ? errno : EINVAL;
            close(ruleset);
            errno = saved_errno;
            return -1;
        }
    }

    if (syscall(
            SYS_landlock_restrict_self,
            ruleset,
            0) < 0) {
        int saved_errno = errno;
        close(ruleset);
        errno = saved_errno;
        return -1;
    }
    close(ruleset);
    if (abi_version)
        *abi_version = (unsigned)abi;
    return 0;
}

int
t1_media_install_worker_landlock(unsigned *abi_version)
{
    static const struct t1_media_sandbox_path paths[] = {
        {
            .path = "/the one/software/audio",
            .mode = T1_MEDIA_SANDBOX_PATH_READ_ONLY,
        },
        {
            .path = "/the one/catalogue/audio",
            .mode = T1_MEDIA_SANDBOX_PATH_READ_ONLY,
        },
        {
            .path = "/the one/catalogue/graphics",
            .mode = T1_MEDIA_SANDBOX_PATH_READ_ONLY,
        },
        {
            .path = "/the one/catalogue/python",
            .mode = T1_MEDIA_SANDBOX_PATH_READ_ONLY,
        },
        {
            .path = "/.ephemeral/graphics",
            .mode = T1_MEDIA_SANDBOX_PATH_READ_ONLY,
        },
        {
            .path = "/.ephemeral/cache/nvidia",
            .mode = T1_MEDIA_SANDBOX_PATH_CACHE,
        },
        {
            .path = "/the one/drivers/processes",
            .mode = T1_MEDIA_SANDBOX_PATH_READ_ONLY,
        },
        {
            .path = "/the one/drivers/state",
            .mode = T1_MEDIA_SANDBOX_PATH_READ_ONLY,
        },
        {
            .path = "/the one/drivers/nodes",
            .mode = T1_MEDIA_SANDBOX_PATH_DEVICE,
        },
    };
    return t1_media_install_landlock(
        paths,
        sizeof(paths) / sizeof(paths[0]),
        abi_version);
}

#define T1_MEDIA_SECCOMP_ERROR(error) \
    (SECCOMP_RET_ERRNO | \
     ((uint32_t)(error) & SECCOMP_RET_DATA))

#define T1_MEDIA_SECCOMP_DENY(number) \
    BPF_JUMP( \
        BPF_JMP | BPF_JEQ | BPF_K, \
        (number), \
        0, \
        1), \
    BPF_STMT( \
        BPF_RET | BPF_K, \
        T1_MEDIA_SECCOMP_ERROR(EPERM))

#define T1_MEDIA_SECCOMP_UNAVAILABLE(number) \
    BPF_JUMP( \
        BPF_JMP | BPF_JEQ | BPF_K, \
        (number), \
        0, \
        1), \
    BPF_STMT( \
        BPF_RET | BPF_K, \
        T1_MEDIA_SECCOMP_ERROR(ENOSYS))

#define T1_MEDIA_SECCOMP_CHECK_CLONE(number) \
    BPF_JUMP( \
        BPF_JMP | BPF_JEQ | BPF_K, \
        (number), \
        0, \
        5), \
    BPF_STMT( \
        BPF_LD | BPF_W | BPF_ABS, \
        offsetof(struct seccomp_data, args[0])), \
    BPF_STMT( \
        BPF_ALU | BPF_AND | BPF_K, \
        CLONE_THREAD), \
    BPF_JUMP( \
        BPF_JMP | BPF_JEQ | BPF_K, \
        0, \
        0, \
        1), \
    BPF_STMT( \
        BPF_RET | BPF_K, \
        T1_MEDIA_SECCOMP_ERROR(EPERM)), \
    BPF_STMT( \
        BPF_LD | BPF_W | BPF_ABS, \
        offsetof(struct seccomp_data, nr))

#define T1_MEDIA_SECCOMP_CHECK_PRCTL(number) \
    BPF_JUMP( \
        BPF_JMP | BPF_JEQ | BPF_K, \
        (number), \
        0, \
        7), \
    BPF_STMT( \
        BPF_LD | BPF_W | BPF_ABS, \
        offsetof(struct seccomp_data, args[0])), \
    BPF_JUMP( \
        BPF_JMP | BPF_JEQ | BPF_K, \
        PR_GET_SECCOMP, \
        4, \
        0), \
    BPF_JUMP( \
        BPF_JMP | BPF_JEQ | BPF_K, \
        PR_GET_NO_NEW_PRIVS, \
        3, \
        0), \
    BPF_JUMP( \
        BPF_JMP | BPF_JEQ | BPF_K, \
        PR_GET_DUMPABLE, \
        2, \
        0), \
    BPF_JUMP( \
        BPF_JMP | BPF_JEQ | BPF_K, \
        PR_SET_NAME, \
        1, \
        0), \
    BPF_STMT( \
        BPF_RET | BPF_K, \
        T1_MEDIA_SECCOMP_ERROR(EPERM)), \
    BPF_STMT( \
        BPF_LD | BPF_W | BPF_ABS, \
        offsetof(struct seccomp_data, nr))

int
t1_media_install_worker_seccomp(void)
{
    if (prctl(PR_GET_NO_NEW_PRIVS, 0, 0, 0, 0) != 1) {
        errno = EPERM;
        return -1;
    }

    static const struct sock_filter filter[] = {
        BPF_STMT(
            BPF_LD | BPF_W | BPF_ABS,
            offsetof(struct seccomp_data, arch)),
        BPF_JUMP(
            BPF_JMP | BPF_JEQ | BPF_K,
            AUDIT_ARCH_X86_64,
            1,
            0),
        BPF_STMT(
            BPF_RET | BPF_K,
            SECCOMP_RET_KILL_PROCESS),
        BPF_STMT(
            BPF_LD | BPF_W | BPF_ABS,
            offsetof(struct seccomp_data, nr)),
        BPF_JUMP(
            BPF_JMP | BPF_JSET | BPF_K,
            __X32_SYSCALL_BIT,
            0,
            1),
        BPF_STMT(
            BPF_RET | BPF_K,
            SECCOMP_RET_KILL_PROCESS),

        T1_MEDIA_SECCOMP_CHECK_PRCTL(__NR_prctl),

        T1_MEDIA_SECCOMP_DENY(__NR_socket),
        T1_MEDIA_SECCOMP_DENY(__NR_socketpair),
        T1_MEDIA_SECCOMP_DENY(__NR_connect),
        T1_MEDIA_SECCOMP_DENY(__NR_bind),
        T1_MEDIA_SECCOMP_DENY(__NR_listen),
        T1_MEDIA_SECCOMP_DENY(__NR_accept),
        T1_MEDIA_SECCOMP_DENY(__NR_accept4),

        T1_MEDIA_SECCOMP_DENY(__NR_execve),
#ifdef __NR_execveat
        T1_MEDIA_SECCOMP_DENY(__NR_execveat),
#endif
        T1_MEDIA_SECCOMP_DENY(__NR_fork),
        T1_MEDIA_SECCOMP_DENY(__NR_vfork),
#ifdef __NR_clone3
        T1_MEDIA_SECCOMP_UNAVAILABLE(__NR_clone3),
#endif
        T1_MEDIA_SECCOMP_CHECK_CLONE(__NR_clone),
        T1_MEDIA_SECCOMP_DENY(__NR_kill),
        T1_MEDIA_SECCOMP_DENY(__NR_tkill),
        T1_MEDIA_SECCOMP_DENY(__NR_tgkill),
        T1_MEDIA_SECCOMP_DENY(__NR_rt_sigqueueinfo),
#ifdef __NR_rt_tgsigqueueinfo
        T1_MEDIA_SECCOMP_DENY(__NR_rt_tgsigqueueinfo),
#endif
        T1_MEDIA_SECCOMP_DENY(__NR_setpgid),
        T1_MEDIA_SECCOMP_DENY(__NR_setsid),
        T1_MEDIA_SECCOMP_DENY(__NR_setpriority),
        T1_MEDIA_SECCOMP_DENY(__NR_sched_setparam),
        T1_MEDIA_SECCOMP_DENY(__NR_sched_setscheduler),
        T1_MEDIA_SECCOMP_DENY(__NR_sched_setaffinity),
#ifdef __NR_sched_setattr
        T1_MEDIA_SECCOMP_DENY(__NR_sched_setattr),
#endif
        T1_MEDIA_SECCOMP_DENY(__NR_ioprio_set),
        T1_MEDIA_SECCOMP_DENY(__NR_setrlimit),
        T1_MEDIA_SECCOMP_DENY(__NR_prlimit64),
#ifdef __NR_process_madvise
        T1_MEDIA_SECCOMP_DENY(__NR_process_madvise),
#endif
#ifdef __NR_process_mrelease
        T1_MEDIA_SECCOMP_DENY(__NR_process_mrelease),
#endif

        T1_MEDIA_SECCOMP_DENY(__NR_shmget),
        T1_MEDIA_SECCOMP_DENY(__NR_shmat),
        T1_MEDIA_SECCOMP_DENY(__NR_shmdt),
        T1_MEDIA_SECCOMP_DENY(__NR_shmctl),
        T1_MEDIA_SECCOMP_DENY(__NR_msgget),
        T1_MEDIA_SECCOMP_DENY(__NR_msgsnd),
        T1_MEDIA_SECCOMP_DENY(__NR_msgrcv),
        T1_MEDIA_SECCOMP_DENY(__NR_msgctl),
        T1_MEDIA_SECCOMP_DENY(__NR_semget),
        T1_MEDIA_SECCOMP_DENY(__NR_semop),
        T1_MEDIA_SECCOMP_DENY(__NR_semctl),
#ifdef __NR_semtimedop
        T1_MEDIA_SECCOMP_DENY(__NR_semtimedop),
#endif

        T1_MEDIA_SECCOMP_DENY(__NR_unlink),
        T1_MEDIA_SECCOMP_DENY(__NR_unlinkat),
        T1_MEDIA_SECCOMP_DENY(__NR_rename),
        T1_MEDIA_SECCOMP_DENY(__NR_renameat),
#ifdef __NR_renameat2
        T1_MEDIA_SECCOMP_DENY(__NR_renameat2),
#endif
        T1_MEDIA_SECCOMP_DENY(__NR_link),
        T1_MEDIA_SECCOMP_DENY(__NR_linkat),
        T1_MEDIA_SECCOMP_DENY(__NR_symlink),
        T1_MEDIA_SECCOMP_DENY(__NR_symlinkat),
        T1_MEDIA_SECCOMP_DENY(__NR_mkdir),
        T1_MEDIA_SECCOMP_DENY(__NR_mkdirat),
        T1_MEDIA_SECCOMP_DENY(__NR_rmdir),
        T1_MEDIA_SECCOMP_DENY(__NR_mknod),
        T1_MEDIA_SECCOMP_DENY(__NR_mknodat),
        T1_MEDIA_SECCOMP_DENY(__NR_truncate),
        T1_MEDIA_SECCOMP_DENY(__NR_fallocate),
        T1_MEDIA_SECCOMP_DENY(__NR_chmod),
        T1_MEDIA_SECCOMP_DENY(__NR_fchmod),
        T1_MEDIA_SECCOMP_DENY(__NR_fchmodat),
#ifdef __NR_fchmodat2
        T1_MEDIA_SECCOMP_DENY(__NR_fchmodat2),
#endif
        T1_MEDIA_SECCOMP_DENY(__NR_chown),
        T1_MEDIA_SECCOMP_DENY(__NR_fchown),
        T1_MEDIA_SECCOMP_DENY(__NR_lchown),
        T1_MEDIA_SECCOMP_DENY(__NR_fchownat),
        T1_MEDIA_SECCOMP_DENY(__NR_setxattr),
        T1_MEDIA_SECCOMP_DENY(__NR_lsetxattr),
        T1_MEDIA_SECCOMP_DENY(__NR_fsetxattr),
        T1_MEDIA_SECCOMP_DENY(__NR_removexattr),
        T1_MEDIA_SECCOMP_DENY(__NR_lremovexattr),
        T1_MEDIA_SECCOMP_DENY(__NR_fremovexattr),
        T1_MEDIA_SECCOMP_DENY(__NR_utime),
        T1_MEDIA_SECCOMP_DENY(__NR_utimes),
        T1_MEDIA_SECCOMP_DENY(__NR_futimesat),
        T1_MEDIA_SECCOMP_DENY(__NR_utimensat),
#ifdef __NR_utimensat_time64
        T1_MEDIA_SECCOMP_DENY(__NR_utimensat_time64),
#endif

        T1_MEDIA_SECCOMP_DENY(__NR_mount),
        T1_MEDIA_SECCOMP_DENY(__NR_umount2),
        T1_MEDIA_SECCOMP_DENY(__NR_pivot_root),
        T1_MEDIA_SECCOMP_DENY(__NR_chroot),
        T1_MEDIA_SECCOMP_DENY(__NR_unshare),
        T1_MEDIA_SECCOMP_DENY(__NR_setns),
#ifdef __NR_fsopen
        T1_MEDIA_SECCOMP_DENY(__NR_fsopen),
#endif
#ifdef __NR_fsconfig
        T1_MEDIA_SECCOMP_DENY(__NR_fsconfig),
#endif
#ifdef __NR_fsmount
        T1_MEDIA_SECCOMP_DENY(__NR_fsmount),
#endif
#ifdef __NR_open_tree
        T1_MEDIA_SECCOMP_DENY(__NR_open_tree),
#endif
#ifdef __NR_move_mount
        T1_MEDIA_SECCOMP_DENY(__NR_move_mount),
#endif
#ifdef __NR_mount_setattr
        T1_MEDIA_SECCOMP_DENY(__NR_mount_setattr),
#endif

        T1_MEDIA_SECCOMP_DENY(__NR_ptrace),
        T1_MEDIA_SECCOMP_DENY(__NR_process_vm_readv),
        T1_MEDIA_SECCOMP_DENY(__NR_process_vm_writev),
#ifdef __NR_pidfd_open
        T1_MEDIA_SECCOMP_DENY(__NR_pidfd_open),
#endif
#ifdef __NR_pidfd_getfd
        T1_MEDIA_SECCOMP_DENY(__NR_pidfd_getfd),
#endif
#ifdef __NR_pidfd_send_signal
        T1_MEDIA_SECCOMP_DENY(__NR_pidfd_send_signal),
#endif

        T1_MEDIA_SECCOMP_DENY(__NR_setuid),
        T1_MEDIA_SECCOMP_DENY(__NR_setgid),
        T1_MEDIA_SECCOMP_DENY(__NR_setreuid),
        T1_MEDIA_SECCOMP_DENY(__NR_setregid),
        T1_MEDIA_SECCOMP_DENY(__NR_setresuid),
        T1_MEDIA_SECCOMP_DENY(__NR_setresgid),
        T1_MEDIA_SECCOMP_DENY(__NR_setfsuid),
        T1_MEDIA_SECCOMP_DENY(__NR_setfsgid),
        T1_MEDIA_SECCOMP_DENY(__NR_setgroups),
        T1_MEDIA_SECCOMP_DENY(__NR_capset),

#ifdef __NR_bpf
        T1_MEDIA_SECCOMP_DENY(__NR_bpf),
#endif
        T1_MEDIA_SECCOMP_DENY(__NR_perf_event_open),
        T1_MEDIA_SECCOMP_DENY(__NR_add_key),
        T1_MEDIA_SECCOMP_DENY(__NR_request_key),
        T1_MEDIA_SECCOMP_DENY(__NR_keyctl),
        T1_MEDIA_SECCOMP_DENY(__NR_init_module),
        T1_MEDIA_SECCOMP_DENY(__NR_finit_module),
        T1_MEDIA_SECCOMP_DENY(__NR_delete_module),
        T1_MEDIA_SECCOMP_DENY(__NR_kexec_load),
#ifdef __NR_kexec_file_load
        T1_MEDIA_SECCOMP_DENY(__NR_kexec_file_load),
#endif
        T1_MEDIA_SECCOMP_DENY(__NR_reboot),
        T1_MEDIA_SECCOMP_DENY(__NR_swapon),
        T1_MEDIA_SECCOMP_DENY(__NR_swapoff),
        T1_MEDIA_SECCOMP_DENY(__NR_acct),
        T1_MEDIA_SECCOMP_DENY(__NR_iopl),
        T1_MEDIA_SECCOMP_DENY(__NR_ioperm),
        T1_MEDIA_SECCOMP_DENY(__NR_sethostname),
        T1_MEDIA_SECCOMP_DENY(__NR_setdomainname),
        T1_MEDIA_SECCOMP_DENY(__NR_clock_settime),
        T1_MEDIA_SECCOMP_DENY(__NR_settimeofday),
        T1_MEDIA_SECCOMP_DENY(__NR_adjtimex),
        T1_MEDIA_SECCOMP_DENY(__NR_syslog),
        T1_MEDIA_SECCOMP_DENY(__NR_personality),
        T1_MEDIA_SECCOMP_DENY(__NR_quotactl),
        T1_MEDIA_SECCOMP_DENY(__NR_lookup_dcookie),
        T1_MEDIA_SECCOMP_DENY(__NR_kcmp),
        T1_MEDIA_SECCOMP_DENY(__NR_userfaultfd),
        T1_MEDIA_SECCOMP_DENY(__NR_fanotify_init),
#ifdef __NR_io_uring_setup
        T1_MEDIA_SECCOMP_DENY(__NR_io_uring_setup),
        T1_MEDIA_SECCOMP_DENY(__NR_io_uring_enter),
        T1_MEDIA_SECCOMP_DENY(__NR_io_uring_register),
#endif
#ifdef __NR_landlock_create_ruleset
        T1_MEDIA_SECCOMP_DENY(__NR_landlock_create_ruleset),
        T1_MEDIA_SECCOMP_DENY(__NR_landlock_add_rule),
        T1_MEDIA_SECCOMP_DENY(__NR_landlock_restrict_self),
#endif
        T1_MEDIA_SECCOMP_DENY(__NR_seccomp),

        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
    };
    struct sock_fprog program = {
        .len =
            (unsigned short)(sizeof(filter) / sizeof(filter[0])),
        .filter = (struct sock_filter *)filter,
    };
    long synchronization = syscall(
        SYS_seccomp,
        SECCOMP_SET_MODE_FILTER,
        SECCOMP_FILTER_FLAG_TSYNC,
        &program);
    if (synchronization != 0) {
        if (synchronization > 0)
            errno = EBUSY;
        return -1;
    }
    if (prctl(PR_GET_SECCOMP, 0, 0, 0, 0) != 2) {
        errno = EPERM;
        return -1;
    }
    return 0;
}
