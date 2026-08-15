#define _GNU_SOURCE

#include "../t1_media_decode_privilege.h"
#include "../t1_media_decode_sandbox.h"

#include <errno.h>
#include <fcntl.h>
#include <linux/seccomp.h>
#include <pthread.h>
#include <signal.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/resource.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/shm.h>
#include <sys/syscall.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

#ifndef __X32_SYSCALL_BIT
#define __X32_SYSCALL_BIT 0x40000000U
#endif

struct tsync_proof {
    pthread_mutex_t mutex;
    pthread_cond_t condition;
    bool run;
    int socket_result;
    int socket_errno;
};

static int
write_file(const char *path, const char *contents)
{
    int descriptor = open(
        path,
        O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC,
        0644);
    if (descriptor < 0)
        return -1;
    size_t length = strlen(contents);
    ssize_t written = write(descriptor, contents, length);
    int saved_errno = errno;
    close(descriptor);
    errno = saved_errno;
    return written == (ssize_t)length ? 0 : -1;
}

static void *
thread_proof(void *argument)
{
    return argument;
}

static void *
tsync_thread_proof(void *argument)
{
    struct tsync_proof *proof = argument;
    pthread_mutex_lock(&proof->mutex);
    while (!proof->run)
        pthread_cond_wait(
            &proof->condition,
            &proof->mutex);
    pthread_mutex_unlock(&proof->mutex);
    errno = 0;
    proof->socket_result = socket(
        AF_INET,
        SOCK_STREAM | SOCK_CLOEXEC,
        0);
    proof->socket_errno = errno;
    if (proof->socket_result >= 0)
        close(proof->socket_result);
    return NULL;
}

static bool
failed_with(int result, int expected_errno)
{
    return result == -1 && errno == expected_errno;
}

static int
sandbox_child(const char *allowed,
              const char *allowed_file,
              const char *cache,
              const char *cache_file,
              const char *device,
              const char *device_file,
              const char *device_create,
              const char *denied_file,
              int proof_fd,
              pid_t parent)
{
    if (t1_media_prepare_worker_privileges(
            65534,
            1000,
            parent) < 0)
        return 10;

    struct t1_media_sandbox_path paths[] = {
        {
            .path = allowed,
            .mode = T1_MEDIA_SANDBOX_PATH_READ_ONLY,
            .required = true,
        },
        {
            .path = cache,
            .mode = T1_MEDIA_SANDBOX_PATH_CACHE,
            .required = true,
        },
        {
            .path = device,
            .mode = T1_MEDIA_SANDBOX_PATH_DEVICE,
            .required = true,
        },
    };
    unsigned abi = 0;
    if (t1_media_install_landlock(
            paths,
            sizeof(paths) / sizeof(paths[0]),
            &abi) < 0 ||
        abi < 5)
        return 11;

    struct tsync_proof tsync = {
        .mutex = PTHREAD_MUTEX_INITIALIZER,
        .condition = PTHREAD_COND_INITIALIZER,
        .socket_result = -2,
    };
    pthread_t existing_thread;
    if (pthread_create(
            &existing_thread,
            NULL,
            tsync_thread_proof,
            &tsync) != 0)
        return 29;

    if (t1_media_install_worker_seccomp() < 0 ||
        prctl(PR_GET_SECCOMP, 0, 0, 0, 0) != 2)
        return 12;
    pthread_mutex_lock(&tsync.mutex);
    tsync.run = true;
    pthread_cond_broadcast(&tsync.condition);
    pthread_mutex_unlock(&tsync.mutex);
    if (pthread_join(existing_thread, NULL) != 0 ||
        tsync.socket_result != -1 ||
        tsync.socket_errno != EPERM)
        return 30;
    pthread_cond_destroy(&tsync.condition);
    pthread_mutex_destroy(&tsync.mutex);

    int descriptor = open(
        allowed_file,
        O_RDONLY | O_CLOEXEC);
    if (descriptor < 0)
        return 13;
    char value = 0;
    if (read(descriptor, &value, 1) != 1 || value != 'a') {
        close(descriptor);
        return 14;
    }
    close(descriptor);

    descriptor = open(
        cache_file,
        O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC,
        0600);
    if (descriptor < 0)
        return 34;
    if (write(descriptor, "c", 1) != 1) {
        close(descriptor);
        return 35;
    }
    close(descriptor);

    errno = 0;
    descriptor = open(
        denied_file,
        O_RDONLY | O_CLOEXEC);
    if (descriptor >= 0 ||
        (errno != EACCES && errno != EPERM)) {
        if (descriptor >= 0)
            close(descriptor);
        return 15;
    }

    errno = 0;
    descriptor = open(
        allowed_file,
        O_WRONLY | O_CLOEXEC);
    if (descriptor >= 0 ||
        (errno != EACCES && errno != EPERM)) {
        if (descriptor >= 0)
            close(descriptor);
        return 16;
    }

    descriptor = open(
        device_file,
        O_RDWR | O_CLOEXEC);
    if (descriptor < 0)
        return 31;
    if (write(descriptor, "d", 1) != 1) {
        close(descriptor);
        return 32;
    }
    close(descriptor);

    errno = 0;
    descriptor = open(
        device_create,
        O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC,
        0600);
    if (descriptor >= 0 ||
        (errno != EACCES && errno != EPERM)) {
        if (descriptor >= 0) {
            close(descriptor);
            unlink(device_create);
        }
        return 33;
    }

    errno = 0;
    if (!failed_with(
            mkdirat(
                AT_FDCWD,
                "/tmp/t1md-sandbox-forbidden",
                0700),
            EPERM))
        return 17;

    errno = 0;
    if (!failed_with(
            socket(
                AF_INET,
                SOCK_STREAM | SOCK_CLOEXEC,
                0),
            EPERM))
        return 18;

    errno = 0;
    if (!failed_with(
            kill(parent, 0),
            EPERM))
        return 24;

    errno = 0;
    if (!failed_with(
            prctl(PR_SET_DUMPABLE, 1, 0, 0, 0),
            EPERM))
        return 25;
    errno = 0;
    if (!failed_with(
            prctl(PR_SET_PDEATHSIG, 0, 0, 0, 0),
            EPERM))
        return 26;

    errno = 0;
    if (!failed_with(
            setpriority(PRIO_PROCESS, 0, 0),
            EPERM))
        return 27;

    errno = 0;
    if (!failed_with(
            shmget(
                IPC_PRIVATE,
                4096,
                IPC_CREAT | 0600),
            EPERM))
        return 28;

    errno = 0;
    pid_t child = fork();
    if (child >= 0 || errno != EPERM) {
        if (child == 0)
            _exit(90);
        if (child > 0)
            waitpid(child, NULL, 0);
        return 19;
    }

    char *const arguments[] = {
        (char *)"/bin/true",
        NULL,
    };
    char *const environment[] = {NULL};
    errno = 0;
    execve(arguments[0], arguments, environment);
    if (errno != EPERM)
        return 20;

    pthread_t thread;
    int marker = 42;
    if (pthread_create(
            &thread,
            NULL,
            thread_proof,
            &marker) != 0)
        return 21;
    void *thread_result = NULL;
    if (pthread_join(thread, &thread_result) != 0 ||
        thread_result != &marker)
        return 22;

    uint32_t proof[] = {
        abi,
        1,
        1,
        1,
        1,
        1,
        1,
        1,
        1,
        1,
        1,
        1,
        1,
        1,
        1,
    };
    if (send(
            proof_fd,
            proof,
            sizeof(proof),
            MSG_NOSIGNAL) !=
        (ssize_t)sizeof(proof))
        return 23;
    return 0;
}

static int
test_x32_guard(void)
{
    pid_t child = fork();
    if (child < 0)
        return -1;
    if (child == 0) {
        if (prctl(
                PR_SET_NO_NEW_PRIVS,
                1,
                0,
                0,
                0) < 0 ||
            t1_media_install_worker_seccomp() < 0)
            _exit(80);
        syscall(
            __NR_socket | __X32_SYSCALL_BIT,
            AF_INET,
            SOCK_STREAM,
            0);
        _exit(81);
    }
    int status = 0;
    while (waitpid(child, &status, 0) < 0 &&
           errno == EINTR)
        ;
    return WIFSIGNALED(status) &&
            WTERMSIG(status) == SIGSYS
        ? 0
        : -1;
}

int
main(void)
{
    if (geteuid() != 0) {
        fprintf(
            stderr,
            "sandbox proof test requires root\n");
        return 77;
    }
    if (test_x32_guard() < 0) {
        fprintf(stderr, "x32 seccomp guard proof failed\n");
        return 1;
    }

    char root[] = "/tmp/t1md-sandbox-test-XXXXXX";
    if (!mkdtemp(root))
        return 1;
    char allowed[512];
    char cache[512];
    char device[512];
    char denied[512];
    char allowed_file[1024];
    char cache_file[1024];
    char device_file[1024];
    char device_create[1024];
    char denied_file[1024];
    snprintf(allowed, sizeof(allowed), "%s/allowed", root);
    snprintf(cache, sizeof(cache), "%s/cache", root);
    snprintf(device, sizeof(device), "%s/device", root);
    snprintf(denied, sizeof(denied), "%s/denied", root);
    snprintf(
        allowed_file,
        sizeof(allowed_file),
        "%s/readable",
        allowed);
    snprintf(
        cache_file,
        sizeof(cache_file),
        "%s/compiled-kernel",
        cache);
    snprintf(
        device_file,
        sizeof(device_file),
        "%s/node",
        device);
    snprintf(
        device_create,
        sizeof(device_create),
        "%s/created",
        device);
    snprintf(
        denied_file,
        sizeof(denied_file),
        "%s/user-secret",
        denied);

    int result = 1;
    if (chmod(root, 0755) < 0 ||
        mkdir(allowed, 0755) < 0 ||
        mkdir(cache, 0777) < 0 ||
        mkdir(device, 0755) < 0 ||
        mkdir(denied, 0755) < 0 ||
        write_file(allowed_file, "allowed\n") < 0 ||
        write_file(device_file, "device\n") < 0 ||
        write_file(denied_file, "denied\n") < 0)
        goto cleanup;
    if (chmod(cache, 01777) < 0 ||
        chmod(allowed_file, 0666) < 0 ||
        chmod(device_file, 0666) < 0)
        goto cleanup;

    int channel[2] = {-1, -1};
    if (socketpair(
            AF_UNIX,
            SOCK_SEQPACKET | SOCK_CLOEXEC,
            0,
            channel) < 0)
        goto cleanup;
    pid_t parent = getpid();
    pid_t child = fork();
    if (child < 0) {
        close(channel[0]);
        close(channel[1]);
        goto cleanup;
    }
    if (child == 0) {
        close(channel[0]);
        int child_result = sandbox_child(
            allowed,
            allowed_file,
            cache,
            cache_file,
            device,
            device_file,
            device_create,
            denied_file,
            channel[1],
            parent);
        close(channel[1]);
        _exit(child_result);
    }
    close(channel[1]);
    uint32_t proof[15] = {0};
    size_t remaining = sizeof(proof);
    unsigned char *cursor = (unsigned char *)proof;
    while (remaining) {
        ssize_t received = read(
            channel[0],
            cursor,
            remaining);
        if (received < 0 && errno == EINTR)
            continue;
        if (received <= 0)
            break;
        cursor += (size_t)received;
        remaining -= (size_t)received;
    }
    close(channel[0]);
    int status = 0;
    while (waitpid(child, &status, 0) < 0 &&
           errno == EINTR)
        ;
    if (remaining ||
        !WIFEXITED(status) ||
        WEXITSTATUS(status) != 0 ||
        proof[0] < 5) {
        fprintf(
            stderr,
            "T1MD sandbox proof failed status=%d "
            "remaining=%zu abi=%u\n",
            status,
            remaining,
            proof[0]);
        goto cleanup;
    }
    for (size_t index = 1;
         index < sizeof(proof) / sizeof(proof[0]);
         ++index) {
        if (proof[index] != 1)
            goto cleanup;
    }
    printf(
        "T1MD sandbox proof passed landlock_abi=%u "
        "seccomp=filter network=denied arbitrary_read=denied "
        "write=denied mutation=denied fork=denied exec=denied "
        "signal=denied prctl_mutation=denied priority=denied "
        "sysv_ipc=denied thread=allowed rlimit_core=%llu "
        "seccomp_tsync=proven x32=denied device_rdwr=allowed "
        "watchdog_channel_send=allowed "
        "readonly_write=denied cache_create=allowed device_create=denied "
        "rlimit_fsize=%llu rlimit_nofile=%llu "
        "rlimit_nproc=%llu\n",
        proof[0],
        T1_MEDIA_WORKER_RLIMIT_CORE,
        T1_MEDIA_WORKER_RLIMIT_FSIZE,
        T1_MEDIA_WORKER_RLIMIT_NOFILE,
        T1_MEDIA_WORKER_RLIMIT_NPROC);
    result = 0;

cleanup:
    unlink(allowed_file);
    unlink(cache_file);
    unlink(device_file);
    unlink(device_create);
    unlink(denied_file);
    rmdir(allowed);
    rmdir(cache);
    rmdir(device);
    rmdir(denied);
    rmdir(root);
    return result;
}
