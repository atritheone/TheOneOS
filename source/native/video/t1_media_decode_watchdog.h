#ifndef T1_MEDIA_DECODE_WATCHDOG_H
#define T1_MEDIA_DECODE_WATCHDOG_H

#include <stdint.h>

/*
 * Private supervisor/worker protocol.  The worker reports only ordered
 * operation boundaries; the root supervisor owns CLOCK_MONOTONIC, chooses the
 * deadline, and sends SIGKILL when it expires.  An idle worker has no deadline.
 */
#define T1_MEDIA_WATCHDOG_MAGIC 0x54315744u /* "T1WD" */
#define T1_MEDIA_WATCHDOG_FORMAT 1u
#define T1_MEDIA_WATCHDOG_POLICY_ID "t1md-watchdog-v1"

#define T1_MEDIA_WATCHDOG_STARTING_TIMEOUT_MS 15000u
#define T1_MEDIA_WATCHDOG_HELLO_TIMEOUT_MS 30000u
#define T1_MEDIA_WATCHDOG_CREATE_TIMEOUT_MS 15000u
#define T1_MEDIA_WATCHDOG_DECODE_TIMEOUT_MS 15000u
#define T1_MEDIA_WATCHDOG_FLUSH_TIMEOUT_MS 15000u
#define T1_MEDIA_WATCHDOG_RESET_TIMEOUT_MS 10000u
#define T1_MEDIA_WATCHDOG_RELEASE_TIMEOUT_MS 6000u
#define T1_MEDIA_WATCHDOG_DESTROY_TIMEOUT_MS 10000u
#define T1_MEDIA_WATCHDOG_CLEANUP_TIMEOUT_MS 10000u
#define T1_MEDIA_WATCHDOG_EXITING_TIMEOUT_MS 1000u

#define T1_MEDIA_WORKER_EXEC_VISIBLE_FDS 6u
#define T1_MEDIA_WORKER_REQUIRED_IPC_FDS 3u
#define T1_MEDIA_WORKER_UNEXPECTED_INHERITED_FDS 0u

enum t1_media_watchdog_event {
    T1_MEDIA_WATCHDOG_READY = 1,
    T1_MEDIA_WATCHDOG_BEGIN = 2,
    T1_MEDIA_WATCHDOG_COMPLETE = 3,
    T1_MEDIA_WATCHDOG_EXITING = 4,
    T1_MEDIA_WATCHDOG_WAIT = 5,
    T1_MEDIA_WATCHDOG_RESUME = 6,
};

enum t1_media_watchdog_operation {
    T1_MEDIA_WATCHDOG_NONE = 0,
    T1_MEDIA_WATCHDOG_HELLO = 1,
    T1_MEDIA_WATCHDOG_CREATE = 2,
    T1_MEDIA_WATCHDOG_DECODE = 3,
    T1_MEDIA_WATCHDOG_FLUSH = 4,
    T1_MEDIA_WATCHDOG_RESET = 5,
    T1_MEDIA_WATCHDOG_RELEASE = 6,
    T1_MEDIA_WATCHDOG_DESTROY = 7,
    T1_MEDIA_WATCHDOG_CLEANUP = 8,
};

struct t1_media_watchdog_message {
    uint32_t magic;
    uint16_t format;
    uint16_t event;
    uint16_t operation;
    uint16_t reserved16;
    uint32_t reserved32;
    uint64_t request;
    uint64_t generation;
};

_Static_assert(
    sizeof(struct t1_media_watchdog_message) == 32,
    "T1 watchdog message layout changed");

#endif /* T1_MEDIA_DECODE_WATCHDOG_H */
