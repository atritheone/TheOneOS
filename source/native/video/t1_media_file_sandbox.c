#define _GNU_SOURCE

#include "t1_media_decode_sandbox.h"

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <unistd.h>


/*
 * FFmpeg and FFprobe load this measured library before main().  Shared-library
 * dependencies are already mapped at this point, while no untrusted container
 * bytes have been parsed.  The process is therefore confined before it opens
 * the exact input named by the parent.
 */
__attribute__((constructor))
static void
t1_media_file_sandbox(void)
{
    const char *path = getenv("T1OS_MEDIA_SANDBOX_INPUT");
    const char *required = getenv("T1OS_MEDIA_SANDBOX_REQUIRED");
    if (!path || !*path) {
        if (required && !strcmp(required, "1")) {
            fputs(
                "T1_MEDIA_FILE_SANDBOX missing-input\n",
                stderr);
            _exit(77);
        }
        return;
    }
    const struct t1_media_sandbox_path paths[] = {
        {
            .path = path,
            .mode = T1_MEDIA_SANDBOX_PATH_READ_ONLY,
            .required = true,
        },
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
    unsigned landlock_abi = 0;
    if (path[0] != '/' ||
        prctl(PR_SET_DUMPABLE, 0, 0, 0, 0) < 0 ||
        prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) < 0 ||
        t1_media_install_landlock(
            paths,
            sizeof(paths) / sizeof(paths[0]),
            &landlock_abi) < 0 ||
        t1_media_install_worker_seccomp() < 0) {
        int saved_errno = errno ? errno : EPERM;
        fprintf(
            stderr,
            "T1_MEDIA_FILE_SANDBOX failed error=%s\n",
            strerror(saved_errno));
        _exit(77);
    }
    if (getenv("T1OS_MEDIA_SANDBOX_DEBUG")) {
        fprintf(
            stderr,
            "T1_MEDIA_FILE_SANDBOX ready landlock_abi=%u "
            "filesystem=input-only network=denied process=threads-only\n",
            landlock_abi);
    }
}
