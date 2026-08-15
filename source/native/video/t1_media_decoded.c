#define _GNU_SOURCE

#include "t1_media_decode_transport.h"
#include "t1_media_decode_privilege.h"
#include "t1_media_decode_sandbox.h"
#include "t1_media_decode_watchdog.h"

#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <limits.h>
#include <poll.h>
#include <signal.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/mman.h>
#include <sys/prctl.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/types.h>
#include <sys/un.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#define T1_MEDIA_DEFAULT_SOCKET "/.ephemeral/media/decode.sock"
#define T1_MEDIA_DEFAULT_STATE "/.ephemeral/media/decode-state.json"
#define T1_MEDIA_DEFAULT_DEVICE "/the one/drivers/nodes/dri/renderD128"
#define T1_MEDIA_DEFAULT_WORKER \
    "/the one/software/audio/t1-video-decode"
#define T1_MEDIA_NULL_DEVICE "/the one/drivers/nodes/null"
#define T1_MEDIA_DEFAULT_SESSIONS 8u
#define T1_MEDIA_ABSOLUTE_SESSION_LIMIT 16u
#define T1_MEDIA_PROBE_DIAGNOSTIC_LIMIT (64u * 1024u)
#define T1_MEDIA_SESSION_DIAGNOSTIC_LIMIT \
    (1024u * 1024u)
#define T1_MEDIA_SURFACE_EXPORT_MODE "separate-layers"
#define T1_MEDIA_SURFACE_OBJECT_LAYOUT "one-object-per-plane"
#define T1_MEDIA_SURFACE_MODIFIER_SCOPE "per-object"
#define T1_MEDIA_SURFACE_MODIFIER_LAYOUT "natural-per-plane"

#ifdef T1_MEDIA_DEVELOPMENT
#define T1_MEDIA_SESSION_STDERR_STATE \
    "bounded-nonblocking-relay"
#define T1_MEDIA_SESSION_DIAGNOSTIC_STATE_LIMIT \
    T1_MEDIA_SESSION_DIAGNOSTIC_LIMIT
#else
#define T1_MEDIA_SESSION_STDERR_STATE "null"
#define T1_MEDIA_SESSION_DIAGNOSTIC_STATE_LIMIT 0u
#endif

#ifndef CLOSE_RANGE_CLOEXEC
#define CLOSE_RANGE_CLOEXEC (1U << 2)
#endif

struct t1_media_daemon_options {
    const char *socket_path;
    const char *state_path;
    const char *device_path;
    const char *worker_path;
    uid_t socket_uid;
    gid_t socket_gid;
    uid_t allowed_uid;
    uid_t worker_uid;
    gid_t worker_gid;
    unsigned maximum_sessions;
    unsigned maximum_connections;
    bool debug;
};

enum t1_media_watchdog_state {
    T1_MEDIA_WATCHDOG_EMPTY = 0,
    T1_MEDIA_WATCHDOG_STARTING,
    T1_MEDIA_WATCHDOG_IDLE,
    T1_MEDIA_WATCHDOG_ACTIVE,
    T1_MEDIA_WATCHDOG_WAITING,
    T1_MEDIA_WATCHDOG_EXITING_STATE,
    T1_MEDIA_WATCHDOG_FAILED,
};

struct t1_media_watchdog_slot {
    int descriptor;
    enum t1_media_watchdog_state state;
    uint16_t operation;
    uint64_t request;
    uint64_t generation;
    uint64_t deadline_ms;
};

static volatile sig_atomic_t t1_media_stopping = 0;
static volatile sig_atomic_t t1_media_children_changed = 0;
static const char *t1_media_null_device = T1_MEDIA_NULL_DEVICE;

static void
t1_media_signal_stop(int signal_number)
{
    (void)signal_number;
    t1_media_stopping = 1;
}

static void
t1_media_signal_child(int signal_number)
{
    (void)signal_number;
    t1_media_children_changed = 1;
}

static const char *
t1_media_argument(int argc, char **argv, const char *name)
{
    for (int index = 1; index + 1 < argc; ++index) {
        if (!strcmp(argv[index], name))
            return argv[index + 1];
    }
    return NULL;
}

static bool
t1_media_has_argument(int argc, char **argv, const char *name)
{
    for (int index = 1; index < argc; ++index) {
        if (!strcmp(argv[index], name))
            return true;
    }
    return false;
}

static bool
t1_media_environment_true(const char *name)
{
    const char *value = getenv(name);
    return value &&
        (!strcmp(value, "1") ||
         !strcasecmp(value, "true") ||
         !strcasecmp(value, "yes") ||
         !strcasecmp(value, "on"));
}

static int
t1_media_parse_unsigned(const char *value,
                        unsigned long maximum,
                        unsigned long *output)
{
    if (!value || !*value)
        return -1;
    errno = 0;
    char *end = NULL;
    unsigned long parsed = strtoul(value, &end, 10);
    if (errno || !end || *end || parsed > maximum)
        return -1;
    *output = parsed;
    return 0;
}

static int
t1_media_validate_path(const char *path, size_t maximum)
{
    if (!path || path[0] != '/' || strlen(path) >= maximum) {
        errno = EINVAL;
        return -1;
    }
    return 0;
}

static int
t1_media_open_null(void)
{
    int descriptor = open(
        t1_media_null_device,
        O_RDWR | O_CLOEXEC | O_NOFOLLOW);
    if (descriptor >= 0 &&
        descriptor <= STDERR_FILENO) {
        int replacement = fcntl(
            descriptor,
            F_DUPFD_CLOEXEC,
            STDERR_FILENO + 1);
        int saved_errno = errno;
        close(descriptor);
        descriptor = replacement;
        errno = saved_errno;
    }
    return descriptor;
}

static int
t1_media_clear_close_on_exec(int descriptor)
{
    int flags = fcntl(descriptor, F_GETFD);
    if (flags < 0)
        return -1;
    return fcntl(
        descriptor,
        F_SETFD,
        flags & ~FD_CLOEXEC);
}

static int
t1_media_sanitize_worker_descriptors(
    int first_required,
    int second_required,
    int third_required,
    int diagnostic)
{
    if (first_required <= STDERR_FILENO ||
        (second_required >= 0 &&
         (second_required <= STDERR_FILENO ||
          second_required == first_required)) ||
        (third_required >= 0 &&
         (third_required <= STDERR_FILENO ||
          third_required == first_required ||
          third_required == second_required)) ||
        (diagnostic >= 0 &&
         (diagnostic == first_required ||
          diagnostic == second_required ||
          diagnostic == third_required))) {
        errno = EINVAL;
        return -1;
    }
    int null_descriptor = t1_media_open_null();
    if (null_descriptor < 0)
        return -1;
    if (dup2(null_descriptor, STDIN_FILENO) < 0 ||
        dup2(null_descriptor, STDOUT_FILENO) < 0 ||
        dup2(
            diagnostic >= 0
                ? diagnostic
                : null_descriptor,
            STDERR_FILENO) < 0 ||
        syscall(
            SYS_close_range,
            3u,
            UINT_MAX,
            CLOSE_RANGE_CLOEXEC) < 0 ||
        t1_media_clear_close_on_exec(
            first_required) < 0 ||
        (second_required >= 0 &&
         t1_media_clear_close_on_exec(
             second_required) < 0) ||
        (third_required >= 0 &&
         t1_media_clear_close_on_exec(
             third_required) < 0)) {
        int saved_errno = errno;
        close(null_descriptor);
        errno = saved_errno;
        return -1;
    }
    close(null_descriptor);
    return 0;
}

static int
t1_media_monotonic_milliseconds(uint64_t *milliseconds)
{
    struct timespec now;
    if (!milliseconds ||
        clock_gettime(CLOCK_MONOTONIC, &now) < 0)
        return -1;
    *milliseconds =
        (uint64_t)now.tv_sec * 1000u +
        (uint64_t)now.tv_nsec / 1000000u;
    return 0;
}

static uint32_t
t1_media_watchdog_operation_timeout(uint16_t operation)
{
    switch (operation) {
    case T1_MEDIA_WATCHDOG_HELLO:
        return T1_MEDIA_WATCHDOG_HELLO_TIMEOUT_MS;
    case T1_MEDIA_WATCHDOG_CREATE:
        return T1_MEDIA_WATCHDOG_CREATE_TIMEOUT_MS;
    case T1_MEDIA_WATCHDOG_DECODE:
        return T1_MEDIA_WATCHDOG_DECODE_TIMEOUT_MS;
    case T1_MEDIA_WATCHDOG_FLUSH:
        return T1_MEDIA_WATCHDOG_FLUSH_TIMEOUT_MS;
    case T1_MEDIA_WATCHDOG_RESET:
        return T1_MEDIA_WATCHDOG_RESET_TIMEOUT_MS;
    case T1_MEDIA_WATCHDOG_RELEASE:
        return T1_MEDIA_WATCHDOG_RELEASE_TIMEOUT_MS;
    case T1_MEDIA_WATCHDOG_DESTROY:
        return T1_MEDIA_WATCHDOG_DESTROY_TIMEOUT_MS;
    case T1_MEDIA_WATCHDOG_CLEANUP:
        return T1_MEDIA_WATCHDOG_CLEANUP_TIMEOUT_MS;
    default:
        return 0;
    }
}

#ifdef T1_MEDIA_DEVELOPMENT
static const char *
t1_media_watchdog_operation_name(uint16_t operation)
{
    switch (operation) {
    case T1_MEDIA_WATCHDOG_HELLO:
        return "HELLO";
    case T1_MEDIA_WATCHDOG_CREATE:
        return "CREATE";
    case T1_MEDIA_WATCHDOG_DECODE:
        return "DECODE";
    case T1_MEDIA_WATCHDOG_FLUSH:
        return "FLUSH";
    case T1_MEDIA_WATCHDOG_RESET:
        return "RESET";
    case T1_MEDIA_WATCHDOG_RELEASE:
        return "RELEASE";
    case T1_MEDIA_WATCHDOG_DESTROY:
        return "DESTROY";
    case T1_MEDIA_WATCHDOG_CLEANUP:
        return "CLEANUP";
    default:
        return "STARTING";
    }
}
#endif

static void
t1_media_watchdog_initialize(
    struct t1_media_watchdog_slot *watchdog)
{
    memset(watchdog, 0, sizeof(*watchdog));
    watchdog->descriptor = -1;
}

static void
t1_media_watchdog_close(
    struct t1_media_watchdog_slot *watchdog)
{
    if (watchdog->descriptor >= 0)
        close(watchdog->descriptor);
    t1_media_watchdog_initialize(watchdog);
}

static bool
t1_media_watchdog_has_deadline(
    const struct t1_media_watchdog_slot *watchdog)
{
    return watchdog &&
        (watchdog->state ==
             T1_MEDIA_WATCHDOG_STARTING ||
         watchdog->state ==
             T1_MEDIA_WATCHDOG_ACTIVE ||
         watchdog->state ==
             T1_MEDIA_WATCHDOG_EXITING_STATE);
}

static int
t1_media_watchdog_arm_starting(
    struct t1_media_watchdog_slot *watchdog,
    int descriptor)
{
    uint64_t now = 0;
    if (!watchdog || descriptor < 0 ||
        t1_media_monotonic_milliseconds(&now) < 0)
        return -1;
    t1_media_watchdog_initialize(watchdog);
    watchdog->descriptor = descriptor;
    watchdog->state = T1_MEDIA_WATCHDOG_STARTING;
    watchdog->deadline_ms =
        now + T1_MEDIA_WATCHDOG_STARTING_TIMEOUT_MS;
    return 0;
}

static void
t1_media_watchdog_fail(
    struct t1_media_watchdog_slot *watchdog,
    pid_t child,
    const char *reason)
{
    if (!watchdog ||
        watchdog->state == T1_MEDIA_WATCHDOG_FAILED)
        return;
#ifdef T1_MEDIA_DEVELOPMENT
    fprintf(
        stderr,
        "T1_MEDIA_SERVICE watchdog-kill pid=%ld reason=%s "
        "operation=%s request=%" PRIu64 " generation=%" PRIu64 "\n",
        (long)child,
        reason ? reason : "failure",
        t1_media_watchdog_operation_name(watchdog->operation),
        watchdog->request,
        watchdog->generation);
#else
    (void)reason;
#endif
    if (child > 0)
        kill(child, SIGKILL);
    if (watchdog->descriptor >= 0)
        close(watchdog->descriptor);
    watchdog->descriptor = -1;
    watchdog->state = T1_MEDIA_WATCHDOG_FAILED;
    watchdog->deadline_ms = 0;
}

static int
t1_media_watchdog_apply_message(
    struct t1_media_watchdog_slot *watchdog,
    const struct t1_media_watchdog_message *message)
{
    if (!watchdog || !message ||
        message->magic != T1_MEDIA_WATCHDOG_MAGIC ||
        message->format != T1_MEDIA_WATCHDOG_FORMAT ||
        message->reserved16 != 0 ||
        message->reserved32 != 0) {
        errno = EPROTO;
        return -1;
    }

    uint64_t now = 0;
    if (t1_media_monotonic_milliseconds(&now) < 0)
        return -1;
    if ((watchdog->state == T1_MEDIA_WATCHDOG_STARTING ||
         watchdog->state == T1_MEDIA_WATCHDOG_ACTIVE) &&
        now >= watchdog->deadline_ms) {
        errno = ETIMEDOUT;
        return -1;
    }

    if (message->event == T1_MEDIA_WATCHDOG_READY) {
        if (watchdog->state != T1_MEDIA_WATCHDOG_STARTING ||
            message->operation != T1_MEDIA_WATCHDOG_NONE ||
            message->request != 0 ||
            message->generation != 0) {
            errno = EPROTO;
            return -1;
        }
        watchdog->state = T1_MEDIA_WATCHDOG_IDLE;
        watchdog->operation = T1_MEDIA_WATCHDOG_NONE;
        watchdog->request = 0;
        watchdog->generation = 0;
        watchdog->deadline_ms = 0;
        return 0;
    }

    if (message->event == T1_MEDIA_WATCHDOG_BEGIN) {
        uint32_t timeout =
            t1_media_watchdog_operation_timeout(
                message->operation);
        bool request_valid =
            message->request != 0 ||
            message->operation ==
                T1_MEDIA_WATCHDOG_CLEANUP;
        if (watchdog->state != T1_MEDIA_WATCHDOG_IDLE ||
            timeout == 0 ||
            !request_valid) {
            errno = EPROTO;
            return -1;
        }
        watchdog->state = T1_MEDIA_WATCHDOG_ACTIVE;
        watchdog->operation = message->operation;
        watchdog->request = message->request;
        watchdog->generation = message->generation;
        watchdog->deadline_ms = now + timeout;
        return 0;
    }

    if (message->event == T1_MEDIA_WATCHDOG_COMPLETE) {
        if (watchdog->state != T1_MEDIA_WATCHDOG_ACTIVE ||
            message->operation != watchdog->operation ||
            message->request != watchdog->request ||
            message->generation != watchdog->generation) {
            errno = EPROTO;
            return -1;
        }
        watchdog->state = T1_MEDIA_WATCHDOG_IDLE;
        watchdog->operation = T1_MEDIA_WATCHDOG_NONE;
        watchdog->request = 0;
        watchdog->generation = 0;
        watchdog->deadline_ms = 0;
        return 0;
    }

    if (message->event == T1_MEDIA_WATCHDOG_WAIT) {
        if (watchdog->state != T1_MEDIA_WATCHDOG_ACTIVE ||
            (watchdog->operation !=
                 T1_MEDIA_WATCHDOG_DECODE &&
             watchdog->operation !=
                 T1_MEDIA_WATCHDOG_FLUSH) ||
            message->operation != watchdog->operation ||
            message->request != watchdog->request ||
            message->generation != watchdog->generation) {
            errno = EPROTO;
            return -1;
        }
        watchdog->state = T1_MEDIA_WATCHDOG_WAITING;
        watchdog->deadline_ms = 0;
        return 0;
    }

    if (message->event == T1_MEDIA_WATCHDOG_RESUME) {
        uint32_t timeout =
            t1_media_watchdog_operation_timeout(
                watchdog->operation);
        if (watchdog->state != T1_MEDIA_WATCHDOG_WAITING ||
            timeout == 0 ||
            message->operation != watchdog->operation ||
            message->request != watchdog->request ||
            message->generation != watchdog->generation) {
            errno = EPROTO;
            return -1;
        }
        watchdog->state = T1_MEDIA_WATCHDOG_ACTIVE;
        watchdog->deadline_ms = now + timeout;
        return 0;
    }

    if (message->event == T1_MEDIA_WATCHDOG_EXITING) {
        if (watchdog->state != T1_MEDIA_WATCHDOG_IDLE ||
            message->operation != T1_MEDIA_WATCHDOG_NONE ||
            message->request != 0 ||
            message->generation != 0) {
            errno = EPROTO;
            return -1;
        }
        watchdog->state =
            T1_MEDIA_WATCHDOG_EXITING_STATE;
        watchdog->deadline_ms =
            now + T1_MEDIA_WATCHDOG_EXITING_TIMEOUT_MS;
        return 0;
    }

    errno = EPROTO;
    return -1;
}

static void
t1_media_watchdog_drain(
    struct t1_media_watchdog_slot *watchdog,
    pid_t child)
{
    if (!watchdog || watchdog->descriptor < 0 ||
        watchdog->state == T1_MEDIA_WATCHDOG_FAILED)
        return;
    for (;;) {
        struct t1_media_watchdog_message message = {0};
        ssize_t received = recv(
            watchdog->descriptor,
            &message,
            sizeof(message),
            MSG_DONTWAIT | MSG_TRUNC);
        if (received == (ssize_t)sizeof(message)) {
            if (t1_media_watchdog_apply_message(
                    watchdog,
                    &message) < 0) {
                t1_media_watchdog_fail(
                    watchdog,
                    child,
                    errno == ETIMEDOUT
                        ? "deadline"
                        : "invalid-event");
                return;
            }
            continue;
        }
        if (received < 0 && errno == EINTR)
            continue;
        if (received < 0 &&
            (errno == EAGAIN ||
             errno == EWOULDBLOCK))
            return;
        if (received == 0 &&
            watchdog->state ==
                T1_MEDIA_WATCHDOG_EXITING_STATE) {
            close(watchdog->descriptor);
            watchdog->descriptor = -1;
            return;
        }
        t1_media_watchdog_fail(
            watchdog,
            child,
            received == 0
                ? "channel-closed"
                : "invalid-packet");
        return;
    }
}

static void
t1_media_watchdog_expire(
    struct t1_media_watchdog_slot *watchdogs,
    const pid_t *children,
    unsigned capacity)
{
    uint64_t now = 0;
    if (t1_media_monotonic_milliseconds(&now) < 0) {
        for (unsigned index = 0; index < capacity; ++index) {
            if (children[index] > 0)
                t1_media_watchdog_fail(
                    &watchdogs[index],
                    children[index],
                    "clock-failed");
        }
        return;
    }
    for (unsigned index = 0; index < capacity; ++index) {
        if (children[index] <= 0 ||
            !t1_media_watchdog_has_deadline(
                &watchdogs[index]) ||
            now < watchdogs[index].deadline_ms)
            continue;
        t1_media_watchdog_fail(
            &watchdogs[index],
            children[index],
            "deadline");
    }
}

static int
t1_media_watchdog_poll_timeout(
    const struct t1_media_watchdog_slot *watchdogs,
    const pid_t *children,
    unsigned capacity)
{
    uint64_t now = 0;
    if (t1_media_monotonic_milliseconds(&now) < 0)
        return 0;
    uint64_t timeout = 250;
    for (unsigned index = 0; index < capacity; ++index) {
        if (children[index] <= 0 ||
            !t1_media_watchdog_has_deadline(
                &watchdogs[index]))
            continue;
        if (watchdogs[index].deadline_ms <= now)
            return 0;
        uint64_t remaining =
            watchdogs[index].deadline_ms - now;
        if (remaining < timeout)
            timeout = remaining;
    }
    return (int)timeout;
}

static void
t1_media_forward_probe_diagnostics(
    int descriptor,
    pid_t worker)
{
    size_t forwarded = 0;
    bool truncated = false;
    char buffer[4096];
    for (;;) {
        ssize_t received = read(
            descriptor,
            buffer,
            sizeof(buffer));
        if (received < 0 && errno == EINTR)
            continue;
        if (received < 0 &&
            (errno == EAGAIN ||
             errno == EWOULDBLOCK))
            break;
        if (received <= 0)
            break;
        size_t available =
            forwarded < T1_MEDIA_PROBE_DIAGNOSTIC_LIMIT
                ? T1_MEDIA_PROBE_DIAGNOSTIC_LIMIT -
                    forwarded
                : 0;
        size_t output =
            (size_t)received < available
                ? (size_t)received
                : available;
        if (output) {
            fwrite(buffer, 1, output, stderr);
            forwarded += output;
        }
        if (output < (size_t)received)
            truncated = true;
    }
    close(descriptor);
    if (truncated) {
        fprintf(
            stderr,
            "T1_MEDIA_SERVICE probe-diagnostics-truncated "
            "pid=%ld limit=%u\n",
            (long)worker,
            T1_MEDIA_PROBE_DIAGNOSTIC_LIMIT);
    }
}

#ifdef T1_MEDIA_DEVELOPMENT
static int
t1_media_create_diagnostic_pipe(int descriptors[2])
{
    if (pipe2(
            descriptors,
            O_CLOEXEC | O_NONBLOCK) < 0)
        return -1;
#ifdef F_SETPIPE_SZ
    (void)fcntl(
        descriptors[0],
        F_SETPIPE_SZ,
        (int)T1_MEDIA_SESSION_DIAGNOSTIC_LIMIT);
#endif
    return 0;
}
#endif

static void
t1_media_emit_session_diagnostic(
    pid_t worker,
    const unsigned char *data,
    size_t size)
{
    fprintf(
        stderr,
        "T1_MEDIA_WORKER_DIAGNOSTIC pid=%ld data=\"",
        (long)worker);
    for (size_t index = 0; index < size; ++index) {
        unsigned char value = data[index];
        if (value == '"' || value == '\\') {
            fputc('\\', stderr);
            fputc(value, stderr);
        } else if (value == '\n') {
            fputs("\\n", stderr);
        } else if (value == '\r') {
            fputs("\\r", stderr);
        } else if (value == '\t') {
            fputs("\\t", stderr);
        } else if (value >= 0x20 && value < 0x7f) {
            fputc(value, stderr);
        } else {
            fprintf(stderr, "\\x%02x", value);
        }
    }
    fputs("\"\n", stderr);
}

static void
t1_media_drain_session_diagnostics(
    int *descriptor,
    pid_t worker,
    size_t *forwarded,
    bool *truncated)
{
    if (!descriptor || *descriptor < 0)
        return;
    char buffer[4096];
    for (;;) {
        ssize_t received = read(
            *descriptor,
            buffer,
            sizeof(buffer));
        if (received < 0 && errno == EINTR)
            continue;
        if (received < 0 &&
            (errno == EAGAIN ||
             errno == EWOULDBLOCK))
            return;
        if (received <= 0) {
            close(*descriptor);
            *descriptor = -1;
            return;
        }
        size_t available =
            *forwarded <
                    T1_MEDIA_SESSION_DIAGNOSTIC_LIMIT
                ? T1_MEDIA_SESSION_DIAGNOSTIC_LIMIT -
                    *forwarded
                : 0;
        size_t output =
            (size_t)received < available
                ? (size_t)received
                : available;
        if (output) {
            t1_media_emit_session_diagnostic(
                worker,
                (const unsigned char *)buffer,
                output);
            *forwarded += output;
        }
        if (output < (size_t)received &&
            !*truncated) {
            *truncated = true;
            fprintf(
                stderr,
                "T1_MEDIA_SERVICE "
                "worker-diagnostics-truncated "
                "pid=%ld limit=%u\n",
                (long)worker,
                T1_MEDIA_SESSION_DIAGNOSTIC_LIMIT);
        }
    }
}

static int
t1_media_remove_stale_socket(const char *path)
{
    struct stat status;
    if (lstat(path, &status) < 0)
        return errno == ENOENT ? 0 : -1;
    if (!S_ISSOCK(status.st_mode)) {
        errno = EEXIST;
        return -1;
    }

    int probe = socket(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC, 0);
    if (probe < 0)
        return -1;
    struct sockaddr_un address = {
        .sun_family = AF_UNIX,
    };
    memcpy(address.sun_path, path, strlen(path) + 1);
    int result = connect(probe, (struct sockaddr *)&address, sizeof(address));
    int connect_error = errno;
    close(probe);
    if (result == 0) {
        errno = EADDRINUSE;
        return -1;
    }
    if (connect_error != ECONNREFUSED && connect_error != ENOENT) {
        errno = connect_error;
        return -1;
    }
    return unlink(path);
}

static int
t1_media_listen(const struct t1_media_daemon_options *options)
{
    if (t1_media_validate_path(
            options->socket_path,
            sizeof(((struct sockaddr_un *)0)->sun_path)) < 0)
        return -1;
    if (t1_media_remove_stale_socket(options->socket_path) < 0)
        return -1;

    int descriptor = socket(
        AF_UNIX,
        SOCK_SEQPACKET | SOCK_CLOEXEC | SOCK_NONBLOCK,
        0);
    if (descriptor < 0)
        return -1;

    int buffer_size = (int)(T1_MEDIA_MAX_CONTROL_BYTES * 2u);
    setsockopt(
        descriptor,
        SOL_SOCKET,
        SO_RCVBUF,
        &buffer_size,
        sizeof(buffer_size));
    setsockopt(
        descriptor,
        SOL_SOCKET,
        SO_SNDBUF,
        &buffer_size,
        sizeof(buffer_size));

    struct sockaddr_un address = {
        .sun_family = AF_UNIX,
    };
    memcpy(
        address.sun_path,
        options->socket_path,
        strlen(options->socket_path) + 1);
    mode_t previous_mask = umask(0077);
    int result = bind(
        descriptor,
        (struct sockaddr *)&address,
        sizeof(address));
    umask(previous_mask);
    if (result < 0)
        goto failed;
    if (chown(
            options->socket_path,
            options->socket_uid,
            options->socket_gid) < 0)
        goto failed_bound;
    if (chmod(options->socket_path, 0660) < 0)
        goto failed_bound;
    if (listen(descriptor, (int)options->maximum_connections) < 0)
        goto failed_bound;
    return descriptor;

failed_bound:
    unlink(options->socket_path);
failed:
    {
        int saved = errno;
        close(descriptor);
        errno = saved;
    }
    return -1;
}

static int
t1_media_capability_profile_valid(
    const struct t1_media_capability_profile *profile)
{
    uint32_t permitted_depths = 0;
    switch (profile->profile) {
    case T1_MEDIA_PROFILE_H264_BASELINE:
    case T1_MEDIA_PROFILE_H264_MAIN:
    case T1_MEDIA_PROFILE_H264_HIGH:
        if (profile->codec != T1_MEDIA_CODEC_H264)
            return 0;
        permitted_depths = T1_MEDIA_BIT_DEPTH_8;
        break;
    case T1_MEDIA_PROFILE_VP8_ANY:
        if (profile->codec != T1_MEDIA_CODEC_VP8)
            return 0;
        permitted_depths = T1_MEDIA_BIT_DEPTH_8;
        break;
    case T1_MEDIA_PROFILE_VP9_0:
        if (profile->codec != T1_MEDIA_CODEC_VP9)
            return 0;
        permitted_depths = T1_MEDIA_BIT_DEPTH_8;
        break;
    case T1_MEDIA_PROFILE_VP9_2:
        if (profile->codec != T1_MEDIA_CODEC_VP9)
            return 0;
        permitted_depths = T1_MEDIA_BIT_DEPTH_10;
        break;
    case T1_MEDIA_PROFILE_HEVC_MAIN:
        if (profile->codec != T1_MEDIA_CODEC_HEVC)
            return 0;
        permitted_depths = T1_MEDIA_BIT_DEPTH_8;
        break;
    case T1_MEDIA_PROFILE_HEVC_MAIN10:
        if (profile->codec != T1_MEDIA_CODEC_HEVC)
            return 0;
        permitted_depths = T1_MEDIA_BIT_DEPTH_10;
        break;
    case T1_MEDIA_PROFILE_AV1_MAIN:
        if (profile->codec != T1_MEDIA_CODEC_AV1)
            return 0;
        permitted_depths =
            T1_MEDIA_BIT_DEPTH_8 |
            T1_MEDIA_BIT_DEPTH_10;
        break;
    default:
        return 0;
    }

    uint32_t expected_outputs = 0;
    if (profile->bit_depths & T1_MEDIA_BIT_DEPTH_8)
        expected_outputs |= T1_MEDIA_OUTPUT_NV12;
    if (profile->bit_depths & T1_MEDIA_BIT_DEPTH_10)
        expected_outputs |= T1_MEDIA_OUTPUT_P010;
    return profile->bit_depths != 0 &&
        (profile->bit_depths & ~permitted_depths) == 0 &&
        profile->output_formats == expected_outputs &&
        profile->minimum_width > 0 &&
        profile->minimum_height > 0 &&
        profile->maximum_width >= profile->minimum_width &&
        profile->maximum_height >= profile->minimum_height;
}

static int
t1_media_read_capabilities(int descriptor,
                           const struct t1_media_daemon_options *options,
                           struct t1_media_capabilities *capabilities)
{
    unsigned char *cursor = (unsigned char *)capabilities;
    size_t remaining = sizeof(*capabilities);
    off_t offset = 0;
    while (remaining) {
        ssize_t received = pread(
            descriptor,
            cursor,
            remaining,
            offset);
        if (received < 0) {
            if (errno == EINTR)
                continue;
            return -1;
        }
        if (received == 0) {
            errno = EIO;
            return -1;
        }
        cursor += (size_t)received;
        remaining -= (size_t)received;
        offset += received;
    }
    if (capabilities->profile_count == 0 ||
        capabilities->profile_count > T1_MEDIA_MAX_PROFILES ||
        capabilities->reserved != 0 ||
        !memchr(
            capabilities->vendor,
            '\0',
            sizeof(capabilities->vendor)) ||
        capabilities->vendor[0] == '\0' ||
        capabilities->maximum_sessions != options->maximum_sessions ||
        capabilities->maximum_decode_requests !=
            T1_MEDIA_MAX_DECODE_REQUESTS ||
        capabilities->maximum_in_flight_frames !=
            T1_MEDIA_MAX_IN_FLIGHT_FRAMES ||
        capabilities->maximum_encoded_bytes !=
            T1_MEDIA_MAX_ENCODED_BYTES ||
        capabilities->maximum_extradata_bytes !=
            T1_MEDIA_MAX_EXTRADATA_BYTES ||
        !(capabilities->features &
              T1_MEDIA_FEATURE_DMABUF) ||
        !(capabilities->features &
              T1_MEDIA_FEATURE_DRM_MODIFIERS) ||
        !(capabilities->features &
              T1_MEDIA_FEATURE_BACKPRESSURE) ||
        !(capabilities->features &
              T1_MEDIA_FEATURE_LINEAR_MEMORY_OUTPUT)) {
        errno = EPROTO;
        return -1;
    }
    for (uint32_t index = 0;
         index < capabilities->profile_count;
         ++index) {
        if (!t1_media_capability_profile_valid(
                &capabilities->profiles[index])) {
            errno = EPROTO;
            return -1;
        }
        for (uint32_t previous = 0;
             previous < index;
             ++previous) {
            if (capabilities->profiles[index].codec ==
                    capabilities->profiles[previous].codec &&
                capabilities->profiles[index].profile ==
                    capabilities->profiles[previous].profile) {
                errno = EPROTO;
                return -1;
            }
        }
    }
    return 0;
}

static int
t1_media_read_sandbox_report(
    int descriptor,
    struct t1_media_sandbox_report *report)
{
    unsigned char *cursor = (unsigned char *)report;
    size_t remaining = sizeof(*report);
    off_t offset =
        (off_t)sizeof(struct t1_media_capabilities);
    while (remaining) {
        ssize_t received = pread(
            descriptor,
            cursor,
            remaining,
            offset);
        if (received < 0) {
            if (errno == EINTR)
                continue;
            return -1;
        }
        if (received == 0) {
            errno = EIO;
            return -1;
        }
        cursor += (size_t)received;
        remaining -= (size_t)received;
        offset += received;
    }
    if (report->format !=
            T1_MEDIA_SANDBOX_REPORT_FORMAT ||
        report->landlock_abi <
            T1_MEDIA_SANDBOX_MINIMUM_LANDLOCK_ABI ||
        report->flags !=
            T1_MEDIA_SANDBOX_REQUIRED_FLAGS ||
        report->reserved != 0 ||
        report->rlimit_core !=
            T1_MEDIA_WORKER_RLIMIT_CORE ||
        report->rlimit_fsize !=
            T1_MEDIA_WORKER_RLIMIT_FSIZE ||
        report->rlimit_nofile !=
            T1_MEDIA_WORKER_RLIMIT_NOFILE ||
        report->rlimit_nproc !=
            T1_MEDIA_WORKER_RLIMIT_NPROC) {
        errno = EPROTO;
        return -1;
    }
    return 0;
}

static int
t1_media_wait_child_bounded(
    pid_t child,
    int *status,
    uint32_t timeout_ms)
{
    uint64_t started = 0;
    if (child <= 0 || !status ||
        t1_media_monotonic_milliseconds(
            &started) < 0)
        return -1;
    for (;;) {
        pid_t result = waitpid(
            child,
            status,
            WNOHANG);
        if (result == child)
            return 0;
        if (result < 0) {
            if (errno == EINTR)
                continue;
            return -1;
        }
        uint64_t now = 0;
        if (t1_media_monotonic_milliseconds(
                &now) < 0 ||
            now - started >= timeout_ms) {
            kill(child, SIGKILL);
            while (waitpid(child, status, 0) < 0 &&
                   errno == EINTR)
                ;
            errno = ETIMEDOUT;
            return -1;
        }
        struct timespec pause = {
            .tv_sec = 0,
            .tv_nsec = 10000000,
        };
        while (nanosleep(&pause, &pause) < 0 &&
               errno == EINTR)
            ;
    }
}

static int
t1_media_probe_worker(const struct t1_media_daemon_options *options,
                      struct t1_media_capabilities *capabilities,
                      struct t1_media_sandbox_report *sandbox)
{
    int cache = memfd_create(
        "t1md-capabilities",
        MFD_CLOEXEC | MFD_ALLOW_SEALING);
    if (cache < 0)
        return -1;
    int diagnostics[2] = {-1, -1};
    if (pipe2(
            diagnostics,
            O_CLOEXEC | O_NONBLOCK) < 0) {
        close(cache);
        return -1;
    }
    pid_t supervisor = getpid();
    pid_t child = fork();
    if (child < 0) {
        close(diagnostics[0]);
        close(diagnostics[1]);
        close(cache);
        return -1;
    }
    if (child == 0) {
        close(diagnostics[0]);
        if (t1_media_sanitize_worker_descriptors(
                cache,
                -1,
                -1,
                diagnostics[1]) < 0) {
            dprintf(
                diagnostics[1],
                "T1_MEDIA_SERVICE probe-worker-setup-failed "
                "stage=descriptor-sanitization error=%s\n",
                strerror(errno));
            _exit(126);
        }
        char cache_text[32];
        char sessions[32];
        char worker_uid[32];
        char worker_gid[32];
        char expected_parent[32];
        snprintf(cache_text, sizeof(cache_text), "%d", cache);
        snprintf(
            sessions,
            sizeof(sessions),
            "%u",
            options->maximum_sessions);
        snprintf(
            worker_uid,
            sizeof(worker_uid),
            "%lu",
            (unsigned long)options->worker_uid);
        snprintf(
            worker_gid,
            sizeof(worker_gid),
            "%lu",
            (unsigned long)options->worker_gid);
        snprintf(
            expected_parent,
            sizeof(expected_parent),
            "%ld",
            (long)supervisor);
        char *arguments[19] = {
            (char *)options->worker_path,
            "--t1md-worker",
            "--probe",
            "--probe-fd",
            cache_text,
            "--device",
            (char *)options->device_path,
            "--maximum-sessions",
            sessions,
            "--expected-uid",
            worker_uid,
            "--expected-gid",
            worker_gid,
            "--expected-parent",
            expected_parent,
            NULL,
            NULL,
            NULL,
        };
        if (options->debug) {
            arguments[15] = "--debug";
            arguments[16] = NULL;
        }
        if (t1_media_prepare_worker_privileges(
                options->worker_uid,
                options->worker_gid,
                supervisor) < 0) {
            dprintf(
                STDERR_FILENO,
                "T1_MEDIA_SERVICE probe-worker-setup-failed "
                "stage=privilege-drop uid=%lu gid=%lu error=%s\n",
                (unsigned long)options->worker_uid,
                (unsigned long)options->worker_gid,
                strerror(errno));
            _exit(126);
        }
        execv(options->worker_path, arguments);
        _exit(127);
    }

    close(diagnostics[1]);
    int status = 0;
    int wait_result = t1_media_wait_child_bounded(
        child,
        &status,
        T1_MEDIA_WATCHDOG_STARTING_TIMEOUT_MS);
    int wait_errno = errno;
    t1_media_forward_probe_diagnostics(
        diagnostics[0],
        child);
    if (wait_result < 0) {
        errno = wait_errno;
        goto failed;
    }
    if (!WIFEXITED(status) || WEXITSTATUS(status) != 0) {
        errno = ENODEV;
        goto failed;
    }
    struct stat cache_status;
    if (fstat(cache, &cache_status) < 0 ||
        cache_status.st_size !=
            (off_t)(
                sizeof(*capabilities) +
                sizeof(*sandbox)) ||
        t1_media_read_capabilities(
            cache,
            options,
            capabilities) < 0 ||
        t1_media_read_sandbox_report(
            cache,
            sandbox) < 0)
        goto failed;
    if (fcntl(
            cache,
            F_ADD_SEALS,
            F_SEAL_WRITE |
                F_SEAL_SHRINK |
                F_SEAL_GROW |
                F_SEAL_SEAL) < 0)
        goto failed;
    return cache;

failed:
    {
        int saved = errno;
        close(cache);
        errno = saved;
    }
    return -1;
}

static int
t1_media_json_string(FILE *stream, const char *value)
{
    if (fputc('"', stream) == EOF)
        return -1;
    for (const unsigned char *cursor =
             (const unsigned char *)(value ? value : "");
         *cursor;
         ++cursor) {
        if (*cursor == '"' || *cursor == '\\') {
            if (fputc('\\', stream) == EOF)
                return -1;
            if (fputc(*cursor, stream) == EOF)
                return -1;
        } else if (*cursor >= 0x20 && *cursor < 0x7f) {
            if (fputc(*cursor, stream) == EOF)
                return -1;
        } else if (fprintf(stream, "\\u%04x", *cursor) < 0) {
            return -1;
        }
    }
    return fputc('"', stream) == EOF ? -1 : 0;
}

static int
t1_media_write_state(const struct t1_media_daemon_options *options,
                     const char *service_path,
                     const struct t1_media_capabilities *capabilities,
                     const struct t1_media_sandbox_report *sandbox)
{
    if (!options->state_path || !*options->state_path)
        return 0;
    if (t1_media_validate_path(options->state_path, 4096) < 0)
        return -1;

    char temporary[4096];
    int count = snprintf(
        temporary,
        sizeof(temporary),
        "%s.tmp.%ld",
        options->state_path,
        (long)getpid());
    if (count < 0 || (size_t)count >= sizeof(temporary)) {
        errno = ENAMETOOLONG;
        return -1;
    }
    int descriptor = open(
        temporary,
        O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC,
        0644);
    if (descriptor < 0)
        return -1;
    FILE *stream = fdopen(descriptor, "w");
    if (!stream) {
        int saved = errno;
        close(descriptor);
        unlink(temporary);
        errno = saved;
        return -1;
    }

    uint32_t bit_depths = 0;
    uint32_t output_formats = 0;
    for (uint32_t index = 0;
         index < capabilities->profile_count;
         ++index) {
        bit_depths |= capabilities->profiles[index].bit_depths;
        output_formats |= capabilities->profiles[index].output_formats;
    }
    const char *bit_depth_json =
        bit_depths == (T1_MEDIA_BIT_DEPTH_8 | T1_MEDIA_BIT_DEPTH_10)
            ? "[8, 10]"
            : bit_depths == T1_MEDIA_BIT_DEPTH_10
                ? "[10]"
                : "[8]";
    const char *output_format_json =
        output_formats == (T1_MEDIA_OUTPUT_NV12 | T1_MEDIA_OUTPUT_P010)
            ? "[\"NV12\", \"P010\"]"
            : output_formats == T1_MEDIA_OUTPUT_P010
                ? "[\"P010\"]"
                : "[\"NV12\"]";

    bool failed =
        fprintf(
            stream,
            "{\n"
            "  \"format\": 1,\n"
            "  \"protocol\": \"T1MD\",\n"
            "  \"protocol_version\": %u,\n"
            "  \"state\": \"ready\",\n"
            "  \"socket\": ",
            T1_MEDIA_PROTOCOL_VERSION) < 0 ||
        t1_media_json_string(stream, options->socket_path) < 0 ||
        fprintf(
            stream,
            ",\n  \"pid\": %ld,\n  \"device\": ",
            (long)getpid()) < 0 ||
        t1_media_json_string(stream, options->device_path) < 0 ||
        fprintf(stream, ",\n  \"service\": ") < 0 ||
        t1_media_json_string(stream, service_path) < 0 ||
        fprintf(stream, ",\n  \"worker\": ") < 0 ||
        t1_media_json_string(stream, options->worker_path) < 0 ||
        fprintf(
            stream,
            ",\n  \"maximum_sessions\": %u,"
            "\n  \"maximum_connections\": %u,"
            "\n  \"maximum_decode_requests\": %u,"
            "\n  \"maximum_in_flight_frames\": %u,"
            "\n  \"surface_export\": {"
            "\n    \"mode\": \"%s\","
            "\n    \"object_layout\": \"%s\","
            "\n    \"modifier_scope\": \"%s\","
            "\n    \"modifier_layout\": \"%s\","
            "\n    \"composed_fallback\": false"
            "\n  },"
            "\n  \"capabilities\": {"
            "\n    \"vendor\": ",
            options->maximum_sessions,
            options->maximum_connections,
            T1_MEDIA_MAX_DECODE_REQUESTS,
            T1_MEDIA_MAX_IN_FLIGHT_FRAMES,
            T1_MEDIA_SURFACE_EXPORT_MODE,
            T1_MEDIA_SURFACE_OBJECT_LAYOUT,
            T1_MEDIA_SURFACE_MODIFIER_SCOPE,
            T1_MEDIA_SURFACE_MODIFIER_LAYOUT) < 0 ||
        t1_media_json_string(stream, capabilities->vendor) < 0 ||
        fprintf(
            stream,
            ","
            "\n    \"profile_count\": %u,"
            "\n    \"chroma_subsampling\": \"4:2:0\","
            "\n    \"bit_depths\": %s,"
            "\n    \"output_formats\": %s"
            "\n  },"
            "\n  \"worker_uid\": %lu,"
            "\n  \"worker_gid\": %lu,"
            "\n  \"sandbox\": {"
            "\n    \"format\": %u,"
            "\n    \"landlock_abi\": %u,"
            "\n    \"landlock_minimum_abi\": %u,"
            "\n    \"landlock_filesystem\": "
            "\"deny-by-default-all-through-ioctl-dev\","
            "\n    \"landlock_network\": "
            "\"deny-tcp-bind-connect\","
            "\n    \"seccomp\": \"filter\","
            "\n    \"seccomp_tsync\": true,"
            "\n    \"runtime_filesystem\": \"read-only\"," 
            "\n    \"device_filesystem\": \"read-write-ioctl\"," 
            "\n    \"ephemeral_cache\": "
            "\"/.ephemeral/cache/nvidia:read-write\"," 
            "\n    \"network_creation\": \"denied\"," 
            "\n    \"process_creation\": \"threads-only\","
            "\n    \"session_stdin\": \"null\","
            "\n    \"session_stdout\": \"null\","
            "\n    \"session_stderr\": \"%s\","
            "\n    \"session_diagnostic_limit\": %u,"
            "\n    \"session_exec_visible_fds\": %u,"
            "\n    \"session_required_ipc_fds\": %u,"
            "\n    \"session_unexpected_inherited_fds\": %u,"
            "\n    \"probe_diagnostic_limit\": %u,"
            "\n    \"policy_flags\": %u,"
            "\n    \"rlimit_core\": %llu,"
            "\n    \"rlimit_fsize\": %llu,"
            "\n    \"rlimit_nofile\": %u,"
            "\n    \"rlimit_nproc\": %u"
            "\n  },"
            "\n  \"watchdog\": {"
            "\n    \"format\": %u,"
            "\n    \"policy_id\": \"%s\","
            "\n    \"authority\": \"supervisor\","
            "\n    \"clock\": \"CLOCK_MONOTONIC\","
            "\n    \"timeout_action\": \"SIGKILL\","
            "\n    \"idle_timeout_ms\": 0,"
            "\n    \"starting_timeout_ms\": %u,"
            "\n    \"hello_timeout_ms\": %u,"
            "\n    \"create_timeout_ms\": %u,"
            "\n    \"decode_timeout_ms\": %u,"
            "\n    \"flush_timeout_ms\": %u,"
            "\n    \"reset_timeout_ms\": %u,"
            "\n    \"release_timeout_ms\": %u,"
            "\n    \"destroy_timeout_ms\": %u,"
            "\n    \"cleanup_timeout_ms\": %u,"
            "\n    \"exiting_timeout_ms\": %u"
            "\n  },"
            "\n  \"backpressure\": {"
            "\n    \"feature_bit\": %u,"
            "\n    \"message_type\": %u,"
            "\n    \"passive_wait_timeout_ms\": 0,"
            "\n    \"frame_order\": \"before-terminal\","
            "\n    \"reset_terminal\": \"RESET_DONE-without-EXIT\""
            "\n  },"
            "\n  \"debug\": %s\n}\n",
            capabilities->profile_count,
            bit_depth_json,
            output_format_json,
            (unsigned long)options->worker_uid,
            (unsigned long)options->worker_gid,
            sandbox->format,
            sandbox->landlock_abi,
            T1_MEDIA_SANDBOX_MINIMUM_LANDLOCK_ABI,
            T1_MEDIA_SESSION_STDERR_STATE,
            T1_MEDIA_SESSION_DIAGNOSTIC_STATE_LIMIT,
            T1_MEDIA_WORKER_EXEC_VISIBLE_FDS,
            T1_MEDIA_WORKER_REQUIRED_IPC_FDS,
            T1_MEDIA_WORKER_UNEXPECTED_INHERITED_FDS,
            T1_MEDIA_PROBE_DIAGNOSTIC_LIMIT,
            sandbox->flags,
            (unsigned long long)sandbox->rlimit_core,
            (unsigned long long)sandbox->rlimit_fsize,
            sandbox->rlimit_nofile,
            sandbox->rlimit_nproc,
            T1_MEDIA_WATCHDOG_FORMAT,
            T1_MEDIA_WATCHDOG_POLICY_ID,
            T1_MEDIA_WATCHDOG_STARTING_TIMEOUT_MS,
            T1_MEDIA_WATCHDOG_HELLO_TIMEOUT_MS,
            T1_MEDIA_WATCHDOG_CREATE_TIMEOUT_MS,
            T1_MEDIA_WATCHDOG_DECODE_TIMEOUT_MS,
            T1_MEDIA_WATCHDOG_FLUSH_TIMEOUT_MS,
            T1_MEDIA_WATCHDOG_RESET_TIMEOUT_MS,
            T1_MEDIA_WATCHDOG_RELEASE_TIMEOUT_MS,
            T1_MEDIA_WATCHDOG_DESTROY_TIMEOUT_MS,
            T1_MEDIA_WATCHDOG_CLEANUP_TIMEOUT_MS,
            T1_MEDIA_WATCHDOG_EXITING_TIMEOUT_MS,
            T1_MEDIA_FEATURE_BACKPRESSURE,
            T1_MEDIA_BACKPRESSURE,
            options->debug ? "true" : "false") < 0;

    if (fflush(stream) < 0 || fsync(descriptor) < 0)
        failed = true;
    if (fclose(stream) < 0)
        failed = true;
    if (failed) {
        int saved = errno ? errno : EIO;
        unlink(temporary);
        errno = saved;
        return -1;
    }
    if (chmod(temporary, 0644) < 0 ||
        rename(temporary, options->state_path) < 0) {
        int saved = errno;
        unlink(temporary);
        errno = saved;
        return -1;
    }
    return 0;
}

static void
t1_media_reap_children(pid_t *children,
                       int *diagnostics,
                       struct t1_media_watchdog_slot *watchdogs,
                       size_t *diagnostic_bytes,
                       bool *diagnostic_truncated,
                       unsigned capacity,
                       unsigned *active)
{
    for (;;) {
        int status = 0;
        pid_t child = waitpid(-1, &status, WNOHANG);
        if (child <= 0)
            break;
        for (unsigned index = 0; index < capacity; ++index) {
            if (children[index] == child) {
                t1_media_drain_session_diagnostics(
                    &diagnostics[index],
                    children[index],
                    &diagnostic_bytes[index],
                    &diagnostic_truncated[index]);
                if (diagnostics[index] >= 0) {
                    close(diagnostics[index]);
                    diagnostics[index] = -1;
                }
                t1_media_watchdog_close(
                    &watchdogs[index]);
                children[index] = 0;
                diagnostic_bytes[index] = 0;
                diagnostic_truncated[index] = false;
                if (*active)
                    (*active)--;
                break;
            }
        }
#ifdef T1_MEDIA_DEVELOPMENT
        fprintf(
            stderr,
            "T1_MEDIA_SERVICE worker-exit pid=%ld status=%d active=%u\n",
            (long)child,
            status,
            *active);
#endif
    }
    t1_media_children_changed = 0;
}

static int
t1_media_spawn_worker(const struct t1_media_daemon_options *options,
                      int client,
                      int capabilities_fd,
                      pid_t *child_out,
                      int *diagnostic_out,
                      int *watchdog_out)
{
    int watchdog[2] = {-1, -1};
    if (socketpair(
            AF_UNIX,
            SOCK_SEQPACKET | SOCK_CLOEXEC | SOCK_NONBLOCK,
            0,
            watchdog) < 0)
        return -1;
#ifdef T1_MEDIA_DEVELOPMENT
    int diagnostics[2] = {-1, -1};
    if (t1_media_create_diagnostic_pipe(
            diagnostics) < 0) {
        close(watchdog[0]);
        close(watchdog[1]);
        return -1;
    }
#endif
    pid_t supervisor = getpid();
    pid_t child = fork();
    if (child < 0) {
#ifdef T1_MEDIA_DEVELOPMENT
        close(diagnostics[0]);
        close(diagnostics[1]);
#endif
        close(watchdog[0]);
        close(watchdog[1]);
        return -1;
    }
    if (child == 0) {
        close(watchdog[0]);
#ifdef T1_MEDIA_DEVELOPMENT
        close(diagnostics[0]);
        int diagnostic = diagnostics[1];
#else
        int diagnostic = -1;
#endif
        char descriptor[32];
        char capabilities[32];
        char watchdog_descriptor[32];
        char sessions[32];
        char worker_uid[32];
        char worker_gid[32];
        char expected_parent[32];
        snprintf(descriptor, sizeof(descriptor), "%d", client);
        snprintf(
            capabilities,
            sizeof(capabilities),
            "%d",
            capabilities_fd);
        snprintf(
            watchdog_descriptor,
            sizeof(watchdog_descriptor),
            "%d",
            watchdog[1]);
        snprintf(
            sessions,
            sizeof(sessions),
            "%u",
            options->maximum_sessions);
        snprintf(
            worker_uid,
            sizeof(worker_uid),
            "%lu",
            (unsigned long)options->worker_uid);
        snprintf(
            worker_gid,
            sizeof(worker_gid),
            "%lu",
            (unsigned long)options->worker_gid);
        snprintf(
            expected_parent,
            sizeof(expected_parent),
            "%ld",
            (long)supervisor);
        if (t1_media_sanitize_worker_descriptors(
                client,
                capabilities_fd,
                watchdog[1],
                diagnostic) < 0)
            _exit(126);
        char *arguments[21] = {
            (char *)options->worker_path,
            "--t1md-worker",
            "--session-fd",
            descriptor,
            "--capabilities-fd",
            capabilities,
            "--watchdog-fd",
            watchdog_descriptor,
            "--device",
            (char *)options->device_path,
            "--maximum-sessions",
            sessions,
            "--expected-uid",
            worker_uid,
            "--expected-gid",
            worker_gid,
            "--expected-parent",
            expected_parent,
            NULL,
            NULL,
            NULL,
        };
        if (options->debug) {
            arguments[18] = "--debug";
            arguments[19] = NULL;
        }
        if (t1_media_prepare_worker_privileges(
                options->worker_uid,
                options->worker_gid,
                supervisor) < 0)
            _exit(126);
        execv(options->worker_path, arguments);
        _exit(127);
    }
    close(watchdog[1]);
#ifdef T1_MEDIA_DEVELOPMENT
    close(diagnostics[1]);
    *diagnostic_out = diagnostics[0];
#else
    *diagnostic_out = -1;
#endif
    *watchdog_out = watchdog[0];
    *child_out = child;
    return 0;
}

static void
t1_media_stop_children(pid_t *children, unsigned capacity)
{
    for (unsigned index = 0; index < capacity; ++index) {
        if (children[index] > 0)
            kill(children[index], SIGTERM);
    }

    struct timespec pause = {
        .tv_sec = 0,
        .tv_nsec = 50000000,
    };
    for (unsigned attempt = 0; attempt < 40; ++attempt) {
        unsigned remaining = 0;
        for (unsigned index = 0; index < capacity; ++index) {
            if (children[index] <= 0)
                continue;
            pid_t result = waitpid(children[index], NULL, WNOHANG);
            if (result == children[index]) {
                children[index] = 0;
            } else if (result == 0) {
                remaining++;
            } else if (errno == ECHILD) {
                children[index] = 0;
            }
        }
        if (!remaining)
            return;
        nanosleep(&pause, NULL);
    }

    for (unsigned index = 0; index < capacity; ++index) {
        if (children[index] > 0)
            kill(children[index], SIGKILL);
    }
    for (unsigned index = 0; index < capacity; ++index) {
        if (children[index] <= 0)
            continue;
        while (waitpid(children[index], NULL, 0) < 0 && errno == EINTR)
            ;
        children[index] = 0;
    }
}

static int
t1_media_run(const struct t1_media_daemon_options *options,
             const char *service_path)
{
    struct t1_media_capabilities capabilities = {0};
    struct t1_media_sandbox_report sandbox = {0};
    int capabilities_fd =
        t1_media_probe_worker(
            options,
            &capabilities,
            &sandbox);
    if (capabilities_fd < 0) {
        fprintf(
            stderr,
            "T1_MEDIA_SERVICE hardware-probe-failed device=%s: %s\n",
            options->device_path,
            strerror(errno));
        return 69;
    }

    int listener = t1_media_listen(options);
    if (listener < 0) {
        fprintf(
            stderr,
            "T1_MEDIA_SERVICE listen-failed socket=%s: %s\n",
            options->socket_path,
            strerror(errno));
        close(capabilities_fd);
        return 73;
    }
    if (t1_media_write_state(
            options,
            service_path,
            &capabilities,
            &sandbox) < 0) {
        fprintf(
            stderr,
            "T1_MEDIA_SERVICE state-failed path=%s: %s\n",
            options->state_path ? options->state_path : "",
            strerror(errno));
        close(listener);
        close(capabilities_fd);
        unlink(options->socket_path);
        return 73;
    }

    fprintf(
        stderr,
        "T1_MEDIA_SERVICE ready protocol=%u socket=%s device=%s "
        "maximum_sessions=%u maximum_connections=%u profiles=%u "
        "surface_export=%s object_layout=%s modifier_scope=%s "
        "modifier_layout=%s composed_fallback=0 chroma=420 "
        "maximum_decode_requests=%u maximum_in_flight_frames=%u "
        "worker_uid=%lu worker_gid=%lu landlock_abi=%u "
        "landlock_fs=all-through-ioctl-dev "
        "seccomp=filter seccomp_tsync=1 "
        "session_stdin=null session_stdout=null "
        "session_stderr=%s session_diagnostic_limit=%u "
        "exec_visible_fds=%u required_ipc_fds=%u "
        "unexpected_inherited_fds=%u "
        "watchdog_policy=%s watchdog_clock=CLOCK_MONOTONIC "
        "watchdog_idle_ms=0 watchdog_starting_ms=%u "
        "watchdog_hello_ms=%u watchdog_create_ms=%u "
        "watchdog_decode_ms=%u watchdog_flush_ms=%u "
        "watchdog_reset_ms=%u watchdog_release_ms=%u "
        "watchdog_destroy_ms=%u watchdog_cleanup_ms=%u "
        "watchdog_exiting_ms=%u "
        "backpressure_feature=%u backpressure_message=%u "
        "backpressure_wait_ms=0 "
        "rlimit_core=%llu rlimit_fsize=%llu "
        "rlimit_nofile=%u rlimit_nproc=%u\n",
        T1_MEDIA_PROTOCOL_VERSION,
        options->socket_path,
        options->device_path,
        options->maximum_sessions,
        options->maximum_connections,
        capabilities.profile_count,
        T1_MEDIA_SURFACE_EXPORT_MODE,
        T1_MEDIA_SURFACE_OBJECT_LAYOUT,
        T1_MEDIA_SURFACE_MODIFIER_SCOPE,
        T1_MEDIA_SURFACE_MODIFIER_LAYOUT,
        T1_MEDIA_MAX_DECODE_REQUESTS,
        T1_MEDIA_MAX_IN_FLIGHT_FRAMES,
        (unsigned long)options->worker_uid,
        (unsigned long)options->worker_gid,
        sandbox.landlock_abi,
        T1_MEDIA_SESSION_STDERR_STATE,
        T1_MEDIA_SESSION_DIAGNOSTIC_STATE_LIMIT,
        T1_MEDIA_WORKER_EXEC_VISIBLE_FDS,
        T1_MEDIA_WORKER_REQUIRED_IPC_FDS,
        T1_MEDIA_WORKER_UNEXPECTED_INHERITED_FDS,
        T1_MEDIA_WATCHDOG_POLICY_ID,
        T1_MEDIA_WATCHDOG_STARTING_TIMEOUT_MS,
        T1_MEDIA_WATCHDOG_HELLO_TIMEOUT_MS,
        T1_MEDIA_WATCHDOG_CREATE_TIMEOUT_MS,
        T1_MEDIA_WATCHDOG_DECODE_TIMEOUT_MS,
        T1_MEDIA_WATCHDOG_FLUSH_TIMEOUT_MS,
        T1_MEDIA_WATCHDOG_RESET_TIMEOUT_MS,
        T1_MEDIA_WATCHDOG_RELEASE_TIMEOUT_MS,
        T1_MEDIA_WATCHDOG_DESTROY_TIMEOUT_MS,
        T1_MEDIA_WATCHDOG_CLEANUP_TIMEOUT_MS,
        T1_MEDIA_WATCHDOG_EXITING_TIMEOUT_MS,
        T1_MEDIA_FEATURE_BACKPRESSURE,
        T1_MEDIA_BACKPRESSURE,
        (unsigned long long)sandbox.rlimit_core,
        (unsigned long long)sandbox.rlimit_fsize,
        sandbox.rlimit_nofile,
        sandbox.rlimit_nproc);

    pid_t children[T1_MEDIA_ABSOLUTE_SESSION_LIMIT] = {0};
    int diagnostics[T1_MEDIA_ABSOLUTE_SESSION_LIMIT];
    struct t1_media_watchdog_slot watchdogs[
        T1_MEDIA_ABSOLUTE_SESSION_LIMIT];
    size_t diagnostic_bytes[
        T1_MEDIA_ABSOLUTE_SESSION_LIMIT] = {0};
    bool diagnostic_truncated[
        T1_MEDIA_ABSOLUTE_SESSION_LIMIT] = {0};
    for (unsigned index = 0;
         index < T1_MEDIA_ABSOLUTE_SESSION_LIMIT;
         ++index) {
        diagnostics[index] = -1;
        t1_media_watchdog_initialize(
            &watchdogs[index]);
    }
    unsigned active = 0;
    int result = 0;

    while (!t1_media_stopping) {
        for (unsigned index = 0;
             index < T1_MEDIA_ABSOLUTE_SESSION_LIMIT;
             ++index) {
            t1_media_drain_session_diagnostics(
                &diagnostics[index],
                children[index],
                &diagnostic_bytes[index],
                &diagnostic_truncated[index]);
            t1_media_watchdog_drain(
                &watchdogs[index],
                children[index]);
        }
        t1_media_watchdog_expire(
            watchdogs,
            children,
            T1_MEDIA_ABSOLUTE_SESSION_LIMIT);
        if (t1_media_children_changed)
            t1_media_reap_children(
                children,
                diagnostics,
                watchdogs,
                diagnostic_bytes,
                diagnostic_truncated,
                T1_MEDIA_ABSOLUTE_SESSION_LIMIT,
                &active);

        struct pollfd descriptors[
            T1_MEDIA_ABSOLUTE_SESSION_LIMIT + 1] = {
            {
                .fd = listener,
                .events = POLLIN | POLLERR | POLLHUP,
            },
        };
        unsigned descriptor_slots[
            T1_MEDIA_ABSOLUTE_SESSION_LIMIT + 1] = {0};
        nfds_t descriptor_count = 1;
        for (unsigned index = 0;
             index < T1_MEDIA_ABSOLUTE_SESSION_LIMIT;
             ++index) {
            if (watchdogs[index].descriptor < 0)
                continue;
            descriptors[descriptor_count].fd =
                watchdogs[index].descriptor;
            descriptors[descriptor_count].events =
                POLLIN | POLLERR | POLLHUP;
            descriptor_slots[descriptor_count] = index;
            descriptor_count++;
        }
        int ready = poll(
            descriptors,
            descriptor_count,
            t1_media_watchdog_poll_timeout(
                watchdogs,
                children,
                T1_MEDIA_ABSOLUTE_SESSION_LIMIT));
        if (ready < 0) {
            if (errno == EINTR)
                continue;
            result = 1;
            break;
        }
        for (nfds_t descriptor_index = 1;
             descriptor_index < descriptor_count;
             ++descriptor_index) {
            if (!descriptors[descriptor_index].revents)
                continue;
            unsigned slot =
                descriptor_slots[descriptor_index];
            t1_media_watchdog_drain(
                &watchdogs[slot],
                children[slot]);
            if (watchdogs[slot].descriptor >= 0 &&
                descriptors[descriptor_index].revents &
                    (POLLERR | POLLHUP | POLLNVAL)) {
                t1_media_watchdog_fail(
                    &watchdogs[slot],
                    children[slot],
                    "channel-failed");
            }
        }
        t1_media_watchdog_expire(
            watchdogs,
            children,
            T1_MEDIA_ABSOLUTE_SESSION_LIMIT);
        if (!ready)
            continue;
        if (descriptors[0].revents &
            (POLLERR | POLLHUP | POLLNVAL)) {
            result = 1;
            break;
        }
        if (!(descriptors[0].revents & POLLIN))
            continue;

        int client = accept4(
            listener,
            NULL,
            NULL,
            SOCK_CLOEXEC);
        if (client < 0) {
            if (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR)
                continue;
            result = 1;
            break;
        }

        struct ucred credentials = {0};
        socklen_t credential_size = sizeof(credentials);
        if (getsockopt(
                client,
                SOL_SOCKET,
                SO_PEERCRED,
                &credentials,
                &credential_size) < 0 ||
            credential_size != sizeof(credentials) ||
            credentials.uid != options->allowed_uid) {
            t1_media_send_error(
                client,
                0,
                0,
                0,
                T1_MEDIA_STATUS_UNAUTHENTICATED,
                "peer uid is not permitted");
            close(client);
            continue;
        }

        t1_media_reap_children(
            children,
            diagnostics,
            watchdogs,
            diagnostic_bytes,
            diagnostic_truncated,
            T1_MEDIA_ABSOLUTE_SESSION_LIMIT,
            &active);
        if (active >= options->maximum_connections) {
#ifdef T1_MEDIA_DEVELOPMENT
            fprintf(
                stderr,
                "T1_MEDIA_SERVICE worker-reject reason=capacity "
                "peer_pid=%ld active=%u limit=%u\n",
                (long)credentials.pid,
                active,
                options->maximum_connections);
#endif
            t1_media_send_error(
                client,
                0,
                0,
                0,
                T1_MEDIA_STATUS_BUSY,
                "all decoder connections are occupied");
            close(client);
            continue;
        }

        unsigned slot = 0;
        while (slot < T1_MEDIA_ABSOLUTE_SESSION_LIMIT && children[slot] != 0)
            slot++;
        pid_t worker = 0;
        int watchdog_descriptor = -1;
        if (slot >= T1_MEDIA_ABSOLUTE_SESSION_LIMIT ||
            t1_media_spawn_worker(
                options,
                client,
                capabilities_fd,
                &worker,
                &diagnostics[slot],
                &watchdog_descriptor) < 0) {
            t1_media_send_error(
                client,
                0,
                0,
                0,
                T1_MEDIA_STATUS_INTERNAL_ERROR,
                "could not start decoder worker");
            close(client);
            continue;
        }
        if (t1_media_watchdog_arm_starting(
                &watchdogs[slot],
                watchdog_descriptor) < 0) {
            int saved = errno;
            close(watchdog_descriptor);
            if (diagnostics[slot] >= 0) {
                close(diagnostics[slot]);
                diagnostics[slot] = -1;
            }
            kill(worker, SIGKILL);
            while (waitpid(worker, NULL, 0) < 0 &&
                   errno == EINTR)
                ;
            t1_media_send_error(
                client,
                0,
                0,
                0,
                T1_MEDIA_STATUS_INTERNAL_ERROR,
                "could not arm decoder watchdog");
            close(client);
            errno = saved;
            continue;
        }
        children[slot] = worker;
        diagnostic_bytes[slot] = 0;
        diagnostic_truncated[slot] = false;
        active++;
#ifdef T1_MEDIA_DEVELOPMENT
        fprintf(
            stderr,
            "T1_MEDIA_SERVICE worker-start pid=%ld peer_pid=%ld active=%u\n",
            (long)worker,
            (long)credentials.pid,
            active);
#endif
        close(client);
    }

    close(listener);
    close(capabilities_fd);
    t1_media_stop_children(
        children,
        T1_MEDIA_ABSOLUTE_SESSION_LIMIT);
    for (unsigned index = 0;
         index < T1_MEDIA_ABSOLUTE_SESSION_LIMIT;
         ++index) {
        t1_media_drain_session_diagnostics(
            &diagnostics[index],
            children[index],
            &diagnostic_bytes[index],
            &diagnostic_truncated[index]);
        if (diagnostics[index] >= 0)
            close(diagnostics[index]);
        t1_media_watchdog_close(
            &watchdogs[index]);
    }
    if (options->state_path)
        unlink(options->state_path);
    unlink(options->socket_path);
    fprintf(stderr, "T1_MEDIA_SERVICE stopped\n");
    return result;
}

static int
t1_media_self_test(void)
{
    if (sizeof(struct t1_media_message_header) != 40 ||
        T1_MEDIA_MAX_FRAME_OBJECTS != 4 ||
        T1_MEDIA_MAX_IN_FLIGHT_FRAMES != 16 ||
        T1_MEDIA_MAX_DECODE_REQUESTS != 1 ||
        T1_MEDIA_BACKPRESSURE != 15 ||
        sizeof(struct t1_media_backpressure) != 8)
        return 1;

    int sockets[2] = {-1, -1};
    if (socketpair(
            AF_UNIX,
            SOCK_SEQPACKET | SOCK_CLOEXEC,
            0,
            sockets) < 0)
        return 1;
    struct t1_media_hello hello = {
        .minimum_version = T1_MEDIA_PROTOCOL_VERSION,
        .maximum_version = T1_MEDIA_PROTOCOL_VERSION,
        .required_features = T1_MEDIA_FEATURE_DMABUF,
        .maximum_frame_objects = T1_MEDIA_MAX_FRAME_OBJECTS,
        .maximum_frame_layers = T1_MEDIA_MAX_FRAME_LAYERS,
        .maximum_planes_per_layer = T1_MEDIA_MAX_PLANES_PER_LAYER,
    };
    int result = t1_media_send_packet(
        sockets[0],
        T1_MEDIA_HELLO,
        0,
        1,
        0,
        &hello,
        sizeof(hello),
        NULL,
        0);
    struct t1_media_packet packet;
    if (result == 0)
        result = t1_media_receive_packet(sockets[1], &packet) == 1 ? 0 : -1;
    if (result == 0) {
        const struct t1_media_message_header *header =
            t1_media_packet_header(&packet);
        result =
            header &&
            header->type == T1_MEDIA_HELLO &&
            header->request == 1 &&
            t1_media_packet_payload_size(&packet) == sizeof(hello)
                ? 0
                : -1;
        t1_media_packet_close_fds(&packet);
    }
    close(sockets[0]);
    close(sockets[1]);
    if (result < 0)
        return 1;
    puts("T1MD transport self-test passed");
    return 0;
}

struct t1_media_privilege_proof {
    uint32_t format;
    uint32_t verification;
    uint64_t real_uid;
    uint64_t effective_uid;
    uint64_t saved_uid;
    uint64_t real_gid;
    uint64_t effective_gid;
    uint64_t saved_gid;
    int32_t supplementary_groups;
    int32_t root_regain_result;
    int32_t root_regain_errno;
};

static int
t1_media_privilege_self_test(uid_t worker_uid, gid_t worker_gid)
{
    if (geteuid() != 0) {
        fprintf(stderr, "privilege self-test requires root\n");
        return 77;
    }
    int channel[2] = {-1, -1};
    if (pipe2(channel, O_CLOEXEC) < 0)
        return 1;
    pid_t supervisor = getpid();
    pid_t child = fork();
    if (child < 0) {
        close(channel[0]);
        close(channel[1]);
        return 1;
    }
    if (child == 0) {
        close(channel[0]);
        struct t1_media_privilege_proof proof = {
            .format = 1,
        };
        if (t1_media_prepare_worker_privileges(
                worker_uid,
                worker_gid,
                supervisor) == 0) {
            uid_t real_uid = (uid_t)-1;
            uid_t effective_uid = (uid_t)-1;
            uid_t saved_uid = (uid_t)-1;
            gid_t real_gid = (gid_t)-1;
            gid_t effective_gid = (gid_t)-1;
            gid_t saved_gid = (gid_t)-1;
            proof.verification =
                t1_media_verify_worker_privileges(
                    worker_uid,
                    worker_gid,
                    supervisor) == 0;
            getresuid(&real_uid, &effective_uid, &saved_uid);
            getresgid(&real_gid, &effective_gid, &saved_gid);
            proof.real_uid = real_uid;
            proof.effective_uid = effective_uid;
            proof.saved_uid = saved_uid;
            proof.real_gid = real_gid;
            proof.effective_gid = effective_gid;
            proof.saved_gid = saved_gid;
            proof.supplementary_groups = getgroups(0, NULL);
            errno = 0;
            proof.root_regain_result = setresuid(0, 0, 0);
            proof.root_regain_errno = errno;
        }
        ssize_t written = write(
            channel[1],
            &proof,
            sizeof(proof));
        close(channel[1]);
        _exit(written == (ssize_t)sizeof(proof) ? 0 : 1);
    }
    close(channel[1]);
    struct t1_media_privilege_proof proof = {0};
    size_t remaining = sizeof(proof);
    unsigned char *cursor = (unsigned char *)&proof;
    while (remaining) {
        ssize_t received = read(channel[0], cursor, remaining);
        if (received < 0 && errno == EINTR)
            continue;
        if (received <= 0)
            break;
        cursor += (size_t)received;
        remaining -= (size_t)received;
    }
    close(channel[0]);
    int status = 0;
    while (waitpid(child, &status, 0) < 0 && errno == EINTR)
        ;
    if (remaining ||
        !WIFEXITED(status) ||
        WEXITSTATUS(status) != 0 ||
        proof.format != 1 ||
        proof.verification != 1 ||
        proof.real_uid != worker_uid ||
        proof.effective_uid != worker_uid ||
        proof.saved_uid != worker_uid ||
        proof.real_gid != worker_gid ||
        proof.effective_gid != worker_gid ||
        proof.saved_gid != worker_gid ||
        proof.supplementary_groups != 0 ||
        proof.root_regain_result != -1 ||
        proof.root_regain_errno != EPERM) {
        fprintf(stderr, "T1_MEDIA_SERVICE privilege self-test failed\n");
        return 1;
    }
    printf(
        "T1MD worker privilege self-test passed uid=%lu gid=%lu "
        "groups=0 no_new_privs=1 rlimit_core=%llu "
        "rlimit_fsize=%llu rlimit_nofile=%llu "
        "rlimit_nproc=%llu\n",
        (unsigned long)worker_uid,
        (unsigned long)worker_gid,
        T1_MEDIA_WORKER_RLIMIT_CORE,
        T1_MEDIA_WORKER_RLIMIT_FSIZE,
        T1_MEDIA_WORKER_RLIMIT_NOFILE,
        T1_MEDIA_WORKER_RLIMIT_NPROC);
    return 0;
}

static int
t1_media_parent_death_self_test(uid_t worker_uid, gid_t worker_gid)
{
    if (geteuid() != 0) {
        fprintf(stderr, "parent-death self-test requires root\n");
        return 77;
    }
    if (prctl(PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) < 0)
        return 1;
    int channel[2] = {-1, -1};
    if (pipe2(channel, O_CLOEXEC) < 0) {
        prctl(PR_SET_CHILD_SUBREAPER, 0, 0, 0, 0);
        return 1;
    }
    pid_t supervisor = fork();
    if (supervisor < 0) {
        close(channel[0]);
        close(channel[1]);
        prctl(PR_SET_CHILD_SUBREAPER, 0, 0, 0, 0);
        return 1;
    }
    if (supervisor == 0) {
        close(channel[0]);
        pid_t expected_parent = getpid();
        pid_t worker = fork();
        if (worker < 0)
            _exit(1);
        if (worker == 0) {
            if (t1_media_prepare_worker_privileges(
                    worker_uid,
                    worker_gid,
                    expected_parent) < 0)
                _exit(126);
            pid_t identity = getpid();
            ssize_t written = write(
                channel[1],
                &identity,
                sizeof(identity));
            close(channel[1]);
            if (written != (ssize_t)sizeof(identity))
                _exit(1);
            for (;;)
                pause();
        }
        close(channel[1]);
        for (;;)
            pause();
    }

    close(channel[1]);
    pid_t worker = 0;
    size_t remaining = sizeof(worker);
    unsigned char *cursor = (unsigned char *)&worker;
    while (remaining) {
        ssize_t received = read(channel[0], cursor, remaining);
        if (received < 0 && errno == EINTR)
            continue;
        if (received <= 0)
            break;
        cursor += (size_t)received;
        remaining -= (size_t)received;
    }
    close(channel[0]);
    int result = 1;
    if (!remaining && worker > 1 &&
        kill(supervisor, SIGKILL) == 0) {
        while (waitpid(supervisor, NULL, 0) < 0 && errno == EINTR)
            ;
        struct timespec delay = {
            .tv_sec = 0,
            .tv_nsec = 20000000,
        };
        for (unsigned attempt = 0; attempt < 100; ++attempt) {
            int status = 0;
            pid_t reaped = waitpid(worker, &status, WNOHANG);
            if (reaped == worker) {
                if (WIFSIGNALED(status) &&
                    WTERMSIG(status) == SIGKILL)
                    result = 0;
                break;
            }
            if (reaped < 0 && errno == ECHILD)
                break;
            nanosleep(&delay, NULL);
        }
    }
    if (result != 0 && worker > 1) {
        kill(worker, SIGKILL);
        while (waitpid(worker, NULL, 0) < 0 && errno == EINTR)
            ;
    }
    if (result != 0) {
        kill(supervisor, SIGKILL);
        while (waitpid(supervisor, NULL, 0) < 0 && errno == EINTR)
            ;
    }
    prctl(PR_SET_CHILD_SUBREAPER, 0, 0, 0, 0);
    if (result != 0) {
        fprintf(
            stderr,
            "T1_MEDIA_SERVICE parent-death self-test failed\n");
        return 1;
    }
    printf(
        "T1MD parent-death self-test passed signal=SIGKILL "
        "orphan_workers=0\n");
    return 0;
}

static pid_t
t1_media_watchdog_test_child(void)
{
    pid_t child = fork();
    if (child != 0)
        return child;
    for (;;)
        pause();
}

static int
t1_media_watchdog_wait_for_signal(
    pid_t child,
    int expected_signal)
{
    int status = 0;
    while (waitpid(child, &status, 0) < 0) {
        if (errno != EINTR)
            return -1;
    }
    return WIFSIGNALED(status) &&
            WTERMSIG(status) == expected_signal
        ? 0
        : -1;
}

static int
t1_media_watchdog_self_test(void)
{
    int sockets[2] = {-1, -1};
    if (socketpair(
            AF_UNIX,
            SOCK_SEQPACKET | SOCK_CLOEXEC | SOCK_NONBLOCK,
            0,
            sockets) < 0)
        return 1;

    struct t1_media_watchdog_slot watchdog;
    if (t1_media_watchdog_arm_starting(
            &watchdog,
            sockets[0]) < 0) {
        close(sockets[0]);
        close(sockets[1]);
        return 1;
    }
    struct t1_media_watchdog_message message = {
        .magic = T1_MEDIA_WATCHDOG_MAGIC,
        .format = T1_MEDIA_WATCHDOG_FORMAT,
        .event = T1_MEDIA_WATCHDOG_READY,
    };
    if (t1_media_watchdog_apply_message(
            &watchdog,
            &message) < 0 ||
        watchdog.state != T1_MEDIA_WATCHDOG_IDLE ||
        watchdog.deadline_ms != 0) {
        close(sockets[1]);
        t1_media_watchdog_close(&watchdog);
        return 1;
    }

    static const uint16_t operations[] = {
        T1_MEDIA_WATCHDOG_HELLO,
        T1_MEDIA_WATCHDOG_CREATE,
        T1_MEDIA_WATCHDOG_DECODE,
        T1_MEDIA_WATCHDOG_FLUSH,
        T1_MEDIA_WATCHDOG_RESET,
        T1_MEDIA_WATCHDOG_RELEASE,
        T1_MEDIA_WATCHDOG_DESTROY,
        T1_MEDIA_WATCHDOG_CLEANUP,
    };
    for (unsigned index = 0;
         index < sizeof(operations) / sizeof(operations[0]);
         ++index) {
        uint64_t before = 0;
        if (t1_media_monotonic_milliseconds(
                &before) < 0) {
            close(sockets[1]);
            t1_media_watchdog_close(&watchdog);
            return 1;
        }
        message.event = T1_MEDIA_WATCHDOG_BEGIN;
        message.operation = operations[index];
        message.request = index + 1;
        message.generation =
            operations[index] ==
                    T1_MEDIA_WATCHDOG_HELLO
                ? 0
                : 1;
        if (t1_media_watchdog_apply_message(
                &watchdog,
                &message) < 0 ||
            watchdog.state !=
                T1_MEDIA_WATCHDOG_ACTIVE ||
            watchdog.deadline_ms <
                before +
                    t1_media_watchdog_operation_timeout(
                        operations[index])) {
            close(sockets[1]);
            t1_media_watchdog_close(&watchdog);
            return 1;
        }
        struct t1_media_watchdog_message duplicate =
            message;
        if (t1_media_watchdog_apply_message(
                &watchdog,
                &duplicate) == 0 ||
            errno != EPROTO) {
            close(sockets[1]);
            t1_media_watchdog_close(&watchdog);
            return 1;
        }
        message.event = T1_MEDIA_WATCHDOG_WAIT;
        bool wait_allowed =
            operations[index] ==
                T1_MEDIA_WATCHDOG_DECODE ||
            operations[index] ==
                T1_MEDIA_WATCHDOG_FLUSH;
        int wait_result =
            t1_media_watchdog_apply_message(
                &watchdog,
                &message);
        if ((wait_allowed &&
             (wait_result < 0 ||
              watchdog.state !=
                  T1_MEDIA_WATCHDOG_WAITING ||
              watchdog.deadline_ms != 0)) ||
            (!wait_allowed &&
             (wait_result == 0 ||
              errno != EPROTO ||
              watchdog.state !=
                  T1_MEDIA_WATCHDOG_ACTIVE))) {
            close(sockets[1]);
            t1_media_watchdog_close(&watchdog);
            return 1;
        }
        if (wait_allowed) {
            message.event =
                T1_MEDIA_WATCHDOG_RESUME;
            if (t1_media_watchdog_apply_message(
                    &watchdog,
                    &message) < 0 ||
                watchdog.state !=
                    T1_MEDIA_WATCHDOG_ACTIVE) {
                close(sockets[1]);
                t1_media_watchdog_close(&watchdog);
                return 1;
            }
        }
        message.event =
            T1_MEDIA_WATCHDOG_COMPLETE;
        if (t1_media_watchdog_apply_message(
                &watchdog,
                &message) < 0 ||
            watchdog.state != T1_MEDIA_WATCHDOG_IDLE ||
            watchdog.deadline_ms != 0) {
            close(sockets[1]);
            t1_media_watchdog_close(&watchdog);
            return 1;
        }
    }
    message.event = T1_MEDIA_WATCHDOG_EXITING;
    message.operation = T1_MEDIA_WATCHDOG_NONE;
    message.request = 0;
    message.generation = 0;
    if (t1_media_watchdog_apply_message(
            &watchdog,
            &message) < 0 ||
        watchdog.state !=
            T1_MEDIA_WATCHDOG_EXITING_STATE) {
        close(sockets[1]);
        t1_media_watchdog_close(&watchdog);
        return 1;
    }
    close(sockets[1]);
    t1_media_watchdog_close(&watchdog);

    pid_t idle_child =
        t1_media_watchdog_test_child();
    if (idle_child < 0)
        return 1;
    struct t1_media_watchdog_slot idle;
    t1_media_watchdog_initialize(&idle);
    idle.state = T1_MEDIA_WATCHDOG_IDLE;
    idle.deadline_ms = 0;
    pid_t idle_children[1] = {idle_child};
    t1_media_watchdog_expire(
        &idle,
        idle_children,
        1);
    if (kill(idle_child, 0) < 0) {
        kill(idle_child, SIGKILL);
        t1_media_watchdog_wait_for_signal(
            idle_child,
            SIGKILL);
        return 1;
    }
    kill(idle_child, SIGKILL);
    if (t1_media_watchdog_wait_for_signal(
            idle_child,
            SIGKILL) < 0)
        return 1;

    pid_t waiting_child =
        t1_media_watchdog_test_child();
    if (waiting_child < 0)
        return 1;
    struct t1_media_watchdog_slot waiting;
    t1_media_watchdog_initialize(&waiting);
    waiting.state = T1_MEDIA_WATCHDOG_WAITING;
    waiting.operation = T1_MEDIA_WATCHDOG_DECODE;
    waiting.request = 61;
    waiting.generation = 4;
    waiting.deadline_ms = 0;
    pid_t waiting_children[1] = {waiting_child};
    t1_media_watchdog_expire(
        &waiting,
        waiting_children,
        1);
    if (waiting.state != T1_MEDIA_WATCHDOG_WAITING ||
        kill(waiting_child, 0) < 0) {
        kill(waiting_child, SIGKILL);
        t1_media_watchdog_wait_for_signal(
            waiting_child,
            SIGKILL);
        return 1;
    }
    kill(waiting_child, SIGKILL);
    if (t1_media_watchdog_wait_for_signal(
            waiting_child,
            SIGKILL) < 0)
        return 1;

    pid_t blocked_child =
        t1_media_watchdog_test_child();
    if (blocked_child < 0)
        return 1;
    struct t1_media_watchdog_slot blocked;
    t1_media_watchdog_initialize(&blocked);
    blocked.state = T1_MEDIA_WATCHDOG_ACTIVE;
    blocked.operation = T1_MEDIA_WATCHDOG_DECODE;
    blocked.request = 77;
    blocked.generation = 9;
    blocked.deadline_ms = 0;
    pid_t blocked_children[1] = {blocked_child};
    t1_media_watchdog_expire(
        &blocked,
        blocked_children,
        1);
    if (blocked.state !=
            T1_MEDIA_WATCHDOG_FAILED ||
        t1_media_watchdog_wait_for_signal(
            blocked_child,
            SIGKILL) < 0)
        return 1;

    printf(
        "T1MD watchdog self-test passed policy=%s "
        "authority=supervisor clock=CLOCK_MONOTONIC "
        "idle_timeout_ms=0 starting=%u hello=%u create=%u "
        "decode=%u flush=%u reset=%u release=%u destroy=%u "
        "cleanup=%u exiting=%u timeout_signal=SIGKILL "
        "backpressure_wait_ms=0 ordering=fail-closed reap=proven\n",
        T1_MEDIA_WATCHDOG_POLICY_ID,
        T1_MEDIA_WATCHDOG_STARTING_TIMEOUT_MS,
        T1_MEDIA_WATCHDOG_HELLO_TIMEOUT_MS,
        T1_MEDIA_WATCHDOG_CREATE_TIMEOUT_MS,
        T1_MEDIA_WATCHDOG_DECODE_TIMEOUT_MS,
        T1_MEDIA_WATCHDOG_FLUSH_TIMEOUT_MS,
        T1_MEDIA_WATCHDOG_RESET_TIMEOUT_MS,
        T1_MEDIA_WATCHDOG_RELEASE_TIMEOUT_MS,
        T1_MEDIA_WATCHDOG_DESTROY_TIMEOUT_MS,
        T1_MEDIA_WATCHDOG_CLEANUP_TIMEOUT_MS,
        T1_MEDIA_WATCHDOG_EXITING_TIMEOUT_MS);
    return 0;
}

static int
t1_media_watchdog_state_self_test(const char *state_path)
{
    char generated_path[256];
    if (state_path) {
        if (t1_media_validate_path(state_path, 4096) < 0)
            return 64;
    } else {
        int path_size = snprintf(
            generated_path,
            sizeof(generated_path),
            "/.ephemeral/media/t1md-watchdog-state-%ld.json",
            (long)getpid());
        if (path_size < 0 ||
            (size_t)path_size >= sizeof(generated_path))
            return 1;
        state_path = generated_path;
    }
    struct t1_media_daemon_options options = {
        .socket_path = T1_MEDIA_DEFAULT_SOCKET,
        .state_path = state_path,
        .device_path = T1_MEDIA_DEFAULT_DEVICE,
        .worker_path = T1_MEDIA_DEFAULT_WORKER,
        .worker_uid = 65534,
        .worker_gid = 1000,
        .maximum_sessions = 8,
        .maximum_connections = 8,
        .debug = true,
    };
    struct t1_media_sandbox_report sandbox = {
        .format = T1_MEDIA_SANDBOX_REPORT_FORMAT,
        .landlock_abi =
            T1_MEDIA_SANDBOX_MINIMUM_LANDLOCK_ABI,
        .flags = T1_MEDIA_SANDBOX_REQUIRED_FLAGS,
        .rlimit_core = T1_MEDIA_WORKER_RLIMIT_CORE,
        .rlimit_fsize =
            T1_MEDIA_WORKER_RLIMIT_FSIZE,
        .rlimit_nofile =
            T1_MEDIA_WORKER_RLIMIT_NOFILE,
        .rlimit_nproc =
            T1_MEDIA_WORKER_RLIMIT_NPROC,
    };
    struct t1_media_capabilities capabilities = {
        .profile_count = 1,
        .vendor = "T1OS state self-test",
        .profiles = {{
            .codec = T1_MEDIA_CODEC_AV1,
            .profile = T1_MEDIA_PROFILE_AV1_MAIN,
            .bit_depths =
                T1_MEDIA_BIT_DEPTH_8 |
                T1_MEDIA_BIT_DEPTH_10,
            .output_formats =
                T1_MEDIA_OUTPUT_NV12 |
                T1_MEDIA_OUTPUT_P010,
            .minimum_width = 16,
            .minimum_height = 16,
            .maximum_width = 8192,
            .maximum_height = 8192,
        }},
    };
    if (t1_media_write_state(
            &options,
            "/the one/software/audio/t1-media-decoderd",
            &capabilities,
            &sandbox) < 0)
        return 1;
    int descriptor = open(
        state_path,
        O_RDONLY | O_CLOEXEC);
    char contents[16384] = {0};
    ssize_t received =
        descriptor >= 0
            ? read(
                descriptor,
                contents,
                sizeof(contents) - 1)
            : -1;
    int saved = errno;
    if (descriptor >= 0)
        close(descriptor);
    unlink(state_path);
    errno = saved;
    if (received <= 0 ||
        !strstr(
            contents,
            "\"session_exec_visible_fds\": 6") ||
        !strstr(
            contents,
            "\"session_required_ipc_fds\": 3") ||
        !strstr(
            contents,
            "\"session_unexpected_inherited_fds\": 0") ||
        !strstr(
            contents,
            "\"policy_id\": \"t1md-watchdog-v1\"") ||
        !strstr(
            contents,
            "\"authority\": \"supervisor\"") ||
        !strstr(
            contents,
            "\"clock\": \"CLOCK_MONOTONIC\"") ||
        !strstr(
            contents,
            "\"idle_timeout_ms\": 0") ||
        !strstr(
            contents,
            "\"starting_timeout_ms\": 15000") ||
        !strstr(
            contents,
            "\"hello_timeout_ms\": 30000") ||
        !strstr(
            contents,
            "\"create_timeout_ms\": 15000") ||
        !strstr(
            contents,
            "\"decode_timeout_ms\": 15000") ||
        !strstr(
            contents,
            "\"flush_timeout_ms\": 15000") ||
        !strstr(
            contents,
            "\"reset_timeout_ms\": 10000") ||
        !strstr(
            contents,
            "\"release_timeout_ms\": 6000") ||
        !strstr(
            contents,
            "\"destroy_timeout_ms\": 10000") ||
        !strstr(
            contents,
            "\"cleanup_timeout_ms\": 10000") ||
        !strstr(
            contents,
            "\"exiting_timeout_ms\": 1000"))
        return 1;
    if (!strstr(
            contents,
            "\"mode\": \"separate-layers\"") ||
        !strstr(
            contents,
            "\"object_layout\": \"one-object-per-plane\"") ||
        !strstr(
            contents,
            "\"modifier_scope\": \"per-object\"") ||
        !strstr(
            contents,
            "\"modifier_layout\": \"natural-per-plane\"") ||
        !strstr(
            contents,
            "\"composed_fallback\": false") ||
        !strstr(
            contents,
            "\"vendor\": \"T1OS state self-test\"") ||
        !strstr(
            contents,
            "\"profile_count\": 1") ||
        !strstr(
            contents,
            "\"chroma_subsampling\": \"4:2:0\"") ||
        !strstr(
            contents,
            "\"bit_depths\": [8, 10]") ||
        !strstr(
            contents,
            "\"output_formats\": [\"NV12\", \"P010\"]"))
        return 1;
    if (!strstr(
            contents,
            "\"maximum_decode_requests\": 1") ||
        !strstr(
            contents,
            "\"maximum_in_flight_frames\": 16") ||
        !strstr(
            contents,
            "\"feature_bit\": 64") ||
        !strstr(
            contents,
            "\"message_type\": 15") ||
        !strstr(
            contents,
            "\"passive_wait_timeout_ms\": 0") ||
        !strstr(
            contents,
            "\"reset_terminal\": \"RESET_DONE-without-EXIT\""))
        return 1;
    puts(
        "T1MD watchdog state self-test passed "
        "schema=ready descriptor_contract=6/3/0 "
        "surface_export=separate-layers modifiers=per-object "
        "formats=NV12/P010 chroma=420");
    return 0;
}

struct t1_media_descriptor_proof {
    uint32_t format;
    uint32_t open_descriptors;
    uint32_t safe_standard_descriptors;
    uint32_t null_standard_descriptors;
    uint32_t stderr_pipe;
    uint32_t required_descriptors;
};

static int
t1_media_descriptor_proof_worker(
    int session,
    int capabilities,
    int watchdog)
{
    if (session <= STDERR_FILENO ||
        capabilities <= STDERR_FILENO ||
        watchdog <= STDERR_FILENO ||
        session == capabilities ||
        session == watchdog ||
        capabilities == watchdog)
        return 64;
    struct t1_media_descriptor_proof proof = {
        .format = 1,
    };
    for (int descriptor = STDIN_FILENO;
         descriptor <= STDOUT_FILENO;
         ++descriptor) {
        struct stat status;
        if (fstat(descriptor, &status) < 0 ||
            !S_ISCHR(status.st_mode))
            return 1;
        proof.safe_standard_descriptors++;
        proof.null_standard_descriptors++;
    }
    struct stat error_status;
    if (fstat(STDERR_FILENO, &error_status) < 0)
        return 1;
#ifdef T1_MEDIA_DEVELOPMENT
    if (!S_ISFIFO(error_status.st_mode))
        return 1;
    proof.stderr_pipe = 1;
    static const char relay_proof[] =
        "T1MD session diagnostic relay proof\n";
    if (write(
            STDERR_FILENO,
            relay_proof,
            sizeof(relay_proof) - 1) !=
        (ssize_t)(sizeof(relay_proof) - 1))
        return 1;
#else
    if (!S_ISCHR(error_status.st_mode))
        return 1;
    proof.null_standard_descriptors++;
#endif
    proof.safe_standard_descriptors++;
    struct stat session_status;
    struct stat capability_status;
    struct stat watchdog_status;
    int watchdog_type = 0;
    socklen_t watchdog_type_size =
        sizeof(watchdog_type);
    if (fstat(session, &session_status) < 0 ||
        !S_ISSOCK(session_status.st_mode) ||
        fstat(capabilities, &capability_status) < 0 ||
        !S_ISREG(capability_status.st_mode) ||
        fstat(watchdog, &watchdog_status) < 0 ||
        !S_ISSOCK(watchdog_status.st_mode) ||
        getsockopt(
            watchdog,
            SOL_SOCKET,
            SO_TYPE,
            &watchdog_type,
            &watchdog_type_size) < 0 ||
        watchdog_type_size != sizeof(watchdog_type) ||
        watchdog_type != SOCK_SEQPACKET)
        return 1;

    struct rlimit descriptor_limit;
    if (getrlimit(
            RLIMIT_NOFILE,
            &descriptor_limit) < 0 ||
        descriptor_limit.rlim_cur > 1048576)
        return 1;
    for (int descriptor = 0;
         (rlim_t)descriptor <
             descriptor_limit.rlim_cur;
         ++descriptor) {
        if (fcntl(descriptor, F_GETFD) >= 0) {
            proof.open_descriptors++;
            if (descriptor == session ||
                descriptor == capabilities ||
                descriptor == watchdog)
                proof.required_descriptors++;
        } else if (errno != EBADF) {
            return 1;
        }
    }
    if (proof.open_descriptors !=
            T1_MEDIA_WORKER_EXEC_VISIBLE_FDS ||
        proof.safe_standard_descriptors != 3 ||
#ifdef T1_MEDIA_DEVELOPMENT
        proof.null_standard_descriptors != 2 ||
        proof.stderr_pipe != 1 ||
#else
        proof.null_standard_descriptors != 3 ||
        proof.stderr_pipe != 0 ||
#endif
        proof.required_descriptors !=
            T1_MEDIA_WORKER_REQUIRED_IPC_FDS)
        return 1;
    return write(
               session,
               &proof,
               sizeof(proof)) ==
            (ssize_t)sizeof(proof)
        ? 0
        : 1;
}

static int
t1_media_descriptor_self_test(
    const char *service_path,
    const char *loader_path,
    const char *loader_library_path)
{
    if ((loader_path == NULL) !=
        (loader_library_path == NULL))
        return 64;
    int sockets[2] = {-1, -1};
    if (socketpair(
            AF_UNIX,
            SOCK_SEQPACKET | SOCK_CLOEXEC,
            0,
            sockets) < 0)
        return 1;
    int watchdog[2] = {-1, -1};
    if (socketpair(
            AF_UNIX,
            SOCK_SEQPACKET | SOCK_CLOEXEC | SOCK_NONBLOCK,
            0,
            watchdog) < 0) {
        close(sockets[0]);
        close(sockets[1]);
        return 1;
    }
    int capabilities = memfd_create(
        "t1md-fd-proof",
        MFD_CLOEXEC);
    int inherited_one = t1_media_open_null();
    int inherited_two = t1_media_open_null();
#ifdef T1_MEDIA_DEVELOPMENT
    int diagnostics[2] = {-1, -1};
    bool diagnostics_ready =
        t1_media_create_diagnostic_pipe(
            diagnostics) == 0;
#endif
    if (capabilities < 0 ||
        inherited_one < 0 ||
        inherited_two < 0
#ifdef T1_MEDIA_DEVELOPMENT
        || !diagnostics_ready
#endif
        ) {
        close(sockets[0]);
        close(sockets[1]);
        close(watchdog[0]);
        close(watchdog[1]);
        if (capabilities >= 0)
            close(capabilities);
        if (inherited_one >= 0)
            close(inherited_one);
        if (inherited_two >= 0)
            close(inherited_two);
#ifdef T1_MEDIA_DEVELOPMENT
        if (diagnostics[0] >= 0)
            close(diagnostics[0]);
        if (diagnostics[1] >= 0)
            close(diagnostics[1]);
#endif
        return 1;
    }
    pid_t child = fork();
    if (child < 0) {
        close(sockets[0]);
        close(sockets[1]);
        close(watchdog[0]);
        close(watchdog[1]);
        close(capabilities);
        close(inherited_one);
        close(inherited_two);
#ifdef T1_MEDIA_DEVELOPMENT
        close(diagnostics[0]);
        close(diagnostics[1]);
#endif
        return 1;
    }
    if (child == 0) {
#ifdef T1_MEDIA_DEVELOPMENT
        close(diagnostics[0]);
        int diagnostic = diagnostics[1];
#else
        int diagnostic = -1;
#endif
        char session_text[32];
        char capabilities_text[32];
        char watchdog_text[32];
        snprintf(
            session_text,
            sizeof(session_text),
            "%d",
            sockets[1]);
        snprintf(
            capabilities_text,
            sizeof(capabilities_text),
            "%d",
            capabilities);
        snprintf(
            watchdog_text,
            sizeof(watchdog_text),
            "%d",
            watchdog[1]);
        if (t1_media_sanitize_worker_descriptors(
                sockets[1],
                capabilities,
                watchdog[1],
                diagnostic) < 0)
            _exit(126);
        if (loader_path) {
            execl(
                loader_path,
                loader_path,
                "--library-path",
                loader_library_path,
                service_path,
                "--fd-sanitization-worker",
                "--session-fd",
                session_text,
                "--capabilities-fd",
                capabilities_text,
                "--watchdog-fd",
                watchdog_text,
                (char *)NULL);
        } else {
            execl(
                service_path,
                service_path,
                "--fd-sanitization-worker",
                "--session-fd",
                session_text,
                "--capabilities-fd",
                capabilities_text,
                "--watchdog-fd",
                watchdog_text,
                (char *)NULL);
        }
        _exit(127);
    }
    close(sockets[1]);
    close(watchdog[1]);
    close(capabilities);
    close(inherited_one);
    close(inherited_two);
#ifdef T1_MEDIA_DEVELOPMENT
    close(diagnostics[1]);
#endif
    struct t1_media_descriptor_proof proof = {0};
    ssize_t received;
    do {
        received = recv(
            sockets[0],
            &proof,
            sizeof(proof),
            0);
    } while (received < 0 && errno == EINTR);
    close(sockets[0]);
    close(watchdog[0]);
    int status = 0;
    while (waitpid(child, &status, 0) < 0 &&
           errno == EINTR)
        ;
#ifdef T1_MEDIA_DEVELOPMENT
    char relay[128] = {0};
    ssize_t relay_size;
    do {
        relay_size = read(
            diagnostics[0],
            relay,
            sizeof(relay) - 1);
    } while (relay_size < 0 && errno == EINTR);
    close(diagnostics[0]);
#endif
    if (received != (ssize_t)sizeof(proof) ||
        !WIFEXITED(status) ||
        WEXITSTATUS(status) != 0 ||
        proof.format != 1 ||
        proof.open_descriptors !=
            T1_MEDIA_WORKER_EXEC_VISIBLE_FDS ||
        proof.safe_standard_descriptors != 3 ||
#ifdef T1_MEDIA_DEVELOPMENT
        proof.null_standard_descriptors != 2 ||
        proof.stderr_pipe != 1 ||
        relay_size <= 0 ||
        !strstr(
            relay,
            "T1MD session diagnostic relay proof") ||
#else
        proof.null_standard_descriptors != 3 ||
        proof.stderr_pipe != 0 ||
#endif
        proof.required_descriptors !=
            T1_MEDIA_WORKER_REQUIRED_IPC_FDS) {
        fprintf(
            stderr,
            "T1_MEDIA_SERVICE inherited-fd self-test failed "
            "status=%d received=%zd open=%u safe_stdio=%u "
            "null_stdio=%u stderr_pipe=%u required=%u\n",
            status,
            received,
            proof.open_descriptors,
            proof.safe_standard_descriptors,
            proof.null_standard_descriptors,
            proof.stderr_pipe,
            proof.required_descriptors);
        return 1;
    }
#ifdef T1_MEDIA_DEVELOPMENT
    puts(
        "T1MD inherited-fd self-test passed "
        "stdin_stdout=null stderr=bounded-nonblocking-relay "
        "open_descriptors=6 required_ipc=3 unexpected=0 "
        "relay=proven limit=1048576");
#else
    puts(
        "T1MD inherited-fd self-test passed "
        "stdio=null open_descriptors=6 required_ipc=3 "
        "unexpected=0");
#endif
    return 0;
}

int
main(int argc, char **argv)
{
    setvbuf(stderr, NULL, _IOLBF, 0);
    if (t1_media_has_argument(
            argc,
            argv,
            "--fd-sanitization-worker")) {
        unsigned long session = 0;
        unsigned long capabilities = 0;
        unsigned long watchdog = 0;
        if (t1_media_parse_unsigned(
                t1_media_argument(
                    argc,
                    argv,
                    "--session-fd"),
                INT32_MAX,
                &session) < 0 ||
            t1_media_parse_unsigned(
                t1_media_argument(
                    argc,
                    argv,
                    "--capabilities-fd"),
                INT32_MAX,
                &capabilities) < 0 ||
            t1_media_parse_unsigned(
                t1_media_argument(
                    argc,
                    argv,
                    "--watchdog-fd"),
                INT32_MAX,
                &watchdog) < 0)
            return 64;
        return t1_media_descriptor_proof_worker(
            (int)session,
            (int)capabilities,
            (int)watchdog);
    }
    if (t1_media_has_argument(
            argc,
            argv,
            "--fd-sanitization-self-test")) {
        const char *null_device = t1_media_argument(
            argc,
            argv,
            "--self-test-null-device");
        if (null_device) {
            if (t1_media_validate_path(null_device, 4096) < 0)
                return 64;
            t1_media_null_device = null_device;
        }
        return t1_media_descriptor_self_test(
            argv[0],
            t1_media_argument(
                argc,
                argv,
                "--self-test-loader"),
            t1_media_argument(
                argc,
                argv,
                "--self-test-library-path"));
    }
    if (t1_media_has_argument(
            argc,
            argv,
            "--watchdog-self-test"))
        return t1_media_watchdog_self_test();
    if (t1_media_has_argument(
            argc,
            argv,
            "--watchdog-state-self-test"))
        return t1_media_watchdog_state_self_test(
            t1_media_argument(
                argc,
                argv,
                "--self-test-state"));
    if (t1_media_has_argument(argc, argv, "--self-test"))
        return t1_media_self_test();

    const char *device_environment = getenv("T1OS_DRM_RENDER_DEVICE");
    struct t1_media_daemon_options options = {
        .socket_path = T1_MEDIA_DEFAULT_SOCKET,
        .state_path = T1_MEDIA_DEFAULT_STATE,
        .device_path =
            device_environment && *device_environment
                ? device_environment
                : T1_MEDIA_DEFAULT_DEVICE,
        .worker_path = T1_MEDIA_DEFAULT_WORKER,
        .socket_uid = 1000,
        .socket_gid = 1000,
        .allowed_uid = 1000,
        .worker_uid = 65534,
        .worker_gid = 1000,
        .maximum_sessions = T1_MEDIA_DEFAULT_SESSIONS,
        .maximum_connections = T1_MEDIA_DEFAULT_SESSIONS,
        .debug =
            t1_media_has_argument(argc, argv, "--debug") ||
            t1_media_environment_true("T1OS_MEDIA_DECODE_DEBUG"),
    };

    const char *value = t1_media_argument(argc, argv, "--socket");
    if (value)
        options.socket_path = value;
    value = t1_media_argument(argc, argv, "--state");
    if (value)
        options.state_path = !strcmp(value, "none") ? NULL : value;
    value = t1_media_argument(argc, argv, "--device");
    if (value)
        options.device_path = value;
    value = t1_media_argument(argc, argv, "--worker");
    if (value)
        options.worker_path = value;

    unsigned long parsed = 0;
    value = t1_media_argument(argc, argv, "--socket-uid");
    if (value) {
        if (t1_media_parse_unsigned(value, UINT32_MAX, &parsed) < 0) {
            fprintf(stderr, "invalid --socket-uid\n");
            return 64;
        }
        options.socket_uid = (uid_t)parsed;
        options.allowed_uid = (uid_t)parsed;
    }
    value = t1_media_argument(argc, argv, "--socket-gid");
    if (value) {
        if (t1_media_parse_unsigned(value, UINT32_MAX, &parsed) < 0) {
            fprintf(stderr, "invalid --socket-gid\n");
            return 64;
        }
        options.socket_gid = (gid_t)parsed;
    }
    value = t1_media_argument(argc, argv, "--allow-uid");
    if (value) {
        if (t1_media_parse_unsigned(value, UINT32_MAX, &parsed) < 0) {
            fprintf(stderr, "invalid --allow-uid\n");
            return 64;
        }
        options.allowed_uid = (uid_t)parsed;
    }
    value = t1_media_argument(argc, argv, "--worker-uid");
    if (value) {
        if (t1_media_parse_unsigned(value, UINT32_MAX, &parsed) < 0 ||
            parsed == 0) {
            fprintf(stderr, "invalid --worker-uid\n");
            return 64;
        }
        options.worker_uid = (uid_t)parsed;
    }
    value = t1_media_argument(argc, argv, "--worker-gid");
    if (value) {
        if (t1_media_parse_unsigned(value, UINT32_MAX, &parsed) < 0 ||
            parsed == 0) {
            fprintf(stderr, "invalid --worker-gid\n");
            return 64;
        }
        options.worker_gid = (gid_t)parsed;
    }
    value = t1_media_argument(argc, argv, "--max-sessions");
    if (value) {
        if (t1_media_parse_unsigned(
                value,
                T1_MEDIA_ABSOLUTE_SESSION_LIMIT,
                &parsed) < 0 ||
            parsed == 0) {
            fprintf(stderr, "invalid --max-sessions\n");
            return 64;
        }
        options.maximum_sessions = (unsigned)parsed;
    }
    value = t1_media_argument(argc, argv, "--max-connections");
    if (value) {
        if (t1_media_parse_unsigned(
                value,
                T1_MEDIA_ABSOLUTE_SESSION_LIMIT,
                &parsed) < 0 ||
            parsed == 0) {
            fprintf(stderr, "invalid --max-connections\n");
            return 64;
        }
        options.maximum_connections = (unsigned)parsed;
    }
    /*
     * Each accepted connection can own at most one decoder.  Keeping the
     * connection bound at or below the decoder bound enforces the active
     * session ceiling without placing any GPU resources in the supervisor.
     */
    if (options.maximum_connections > options.maximum_sessions) {
        fprintf(
            stderr,
            "--max-connections cannot exceed --max-sessions\n");
        return 64;
    }
    if (t1_media_has_argument(
            argc,
            argv,
            "--privilege-self-test"))
        return t1_media_privilege_self_test(
            options.worker_uid,
            options.worker_gid);
    if (t1_media_has_argument(
            argc,
            argv,
            "--parent-death-self-test"))
        return t1_media_parent_death_self_test(
            options.worker_uid,
            options.worker_gid);
    if (geteuid() != 0) {
        fprintf(
            stderr,
            "t1-media-decoderd must run as root so it can create the "
            "socket and then drop every worker to its measured identity\n");
        return 77;
    }

    if (t1_media_validate_path(options.worker_path, 4096) < 0 ||
        t1_media_validate_path(options.device_path, 4096) < 0) {
        fprintf(stderr, "worker and device paths must be absolute\n");
        return 64;
    }
    const bool hardware_probe_self_test = t1_media_has_argument(
        argc,
        argv,
        "--hardware-probe-self-test");
    const char *self_test_null_device = t1_media_argument(
        argc,
        argv,
        "--self-test-null-device");
    if (hardware_probe_self_test || self_test_null_device) {
        /*
         * The build host does not expose the T1OS node namespace.  Permit a
         * host null device only in the deliberately failing /nonexistent
         * hardware-probe test; a real service/device can never select it.
         */
        if (!hardware_probe_self_test ||
            !self_test_null_device ||
            strcmp(options.device_path, "/nonexistent") != 0 ||
            options.state_path != NULL ||
            t1_media_validate_path(self_test_null_device, 4096) < 0) {
            fprintf(stderr, "invalid hardware probe self-test contract\n");
            return 64;
        }
        t1_media_null_device = self_test_null_device;
    }

    struct sigaction stop_action = {
        .sa_handler = t1_media_signal_stop,
    };
    sigemptyset(&stop_action.sa_mask);
    sigaction(SIGINT, &stop_action, NULL);
    sigaction(SIGTERM, &stop_action, NULL);
    struct sigaction child_action = {
        .sa_handler = t1_media_signal_child,
        .sa_flags = SA_RESTART | SA_NOCLDSTOP,
    };
    sigemptyset(&child_action.sa_mask);
    sigaction(SIGCHLD, &child_action, NULL);
    signal(SIGPIPE, SIG_IGN);

    return t1_media_run(&options, argv[0]);
}
