#define _GNU_SOURCE

#include "t1_media_decode_privilege.h"

#include <errno.h>
#include <grp.h>
#include <signal.h>
#include <sys/prctl.h>
#include <sys/resource.h>
#include <sys/types.h>
#include <unistd.h>

static int
t1_media_verify_limit(int resource, rlim_t expected)
{
    struct rlimit limit = {0};
    if (getrlimit(resource, &limit) < 0)
        return -1;
    if (limit.rlim_cur != expected ||
        limit.rlim_max != expected) {
        errno = EPERM;
        return -1;
    }
    return 0;
}

int
t1_media_verify_worker_privileges(uid_t worker_uid,
                                  gid_t worker_gid,
                                  pid_t expected_parent)
{
    uid_t real_uid = (uid_t)-1;
    uid_t effective_uid = (uid_t)-1;
    uid_t saved_uid = (uid_t)-1;
    gid_t real_gid = (gid_t)-1;
    gid_t effective_gid = (gid_t)-1;
    gid_t saved_gid = (gid_t)-1;
    if (getresuid(&real_uid, &effective_uid, &saved_uid) < 0 ||
        getresgid(&real_gid, &effective_gid, &saved_gid) < 0)
        return -1;
    int parent_death_signal = 0;
    if (prctl(PR_GET_PDEATHSIG, &parent_death_signal, 0, 0, 0) < 0)
        return -1;
    if (expected_parent <= 1 ||
        getppid() != expected_parent ||
        real_uid != worker_uid ||
        effective_uid != worker_uid ||
        saved_uid != worker_uid ||
        real_gid != worker_gid ||
        effective_gid != worker_gid ||
        saved_gid != worker_gid ||
        getgroups(0, NULL) != 0 ||
        prctl(PR_GET_KEEPCAPS, 0, 0, 0, 0) != 0 ||
        prctl(PR_GET_DUMPABLE, 0, 0, 0, 0) != 0 ||
        prctl(PR_GET_NO_NEW_PRIVS, 0, 0, 0, 0) != 1 ||
        parent_death_signal != SIGKILL ||
        t1_media_verify_limit(
            RLIMIT_CORE,
            (rlim_t)T1_MEDIA_WORKER_RLIMIT_CORE) < 0 ||
        t1_media_verify_limit(
            RLIMIT_FSIZE,
            (rlim_t)T1_MEDIA_WORKER_RLIMIT_FSIZE) < 0 ||
        t1_media_verify_limit(
            RLIMIT_NOFILE,
            (rlim_t)T1_MEDIA_WORKER_RLIMIT_NOFILE) < 0 ||
        t1_media_verify_limit(
            RLIMIT_NPROC,
            (rlim_t)T1_MEDIA_WORKER_RLIMIT_NPROC) < 0) {
        errno = EPERM;
        return -1;
    }
    return 0;
}

int
t1_media_prepare_worker_privileges(uid_t worker_uid,
                                   gid_t worker_gid,
                                   pid_t expected_parent)
{
    if (worker_uid == 0 || worker_gid == 0 || expected_parent <= 1) {
        errno = EINVAL;
        return -1;
    }
    const struct rlimit core_limit = {
        .rlim_cur = (rlim_t)T1_MEDIA_WORKER_RLIMIT_CORE,
        .rlim_max = (rlim_t)T1_MEDIA_WORKER_RLIMIT_CORE,
    };
    const struct rlimit file_limit = {
        .rlim_cur = (rlim_t)T1_MEDIA_WORKER_RLIMIT_FSIZE,
        .rlim_max = (rlim_t)T1_MEDIA_WORKER_RLIMIT_FSIZE,
    };
    const struct rlimit descriptor_limit = {
        .rlim_cur = (rlim_t)T1_MEDIA_WORKER_RLIMIT_NOFILE,
        .rlim_max = (rlim_t)T1_MEDIA_WORKER_RLIMIT_NOFILE,
    };
    const struct rlimit process_limit = {
        .rlim_cur = (rlim_t)T1_MEDIA_WORKER_RLIMIT_NPROC,
        .rlim_max = (rlim_t)T1_MEDIA_WORKER_RLIMIT_NPROC,
    };
    if (setrlimit(RLIMIT_CORE, &core_limit) < 0 ||
        setrlimit(RLIMIT_FSIZE, &file_limit) < 0 ||
        setrlimit(RLIMIT_NOFILE, &descriptor_limit) < 0 ||
        setrlimit(RLIMIT_NPROC, &process_limit) < 0 ||
        prctl(PR_SET_KEEPCAPS, 0, 0, 0, 0) < 0 ||
        setgroups(0, NULL) < 0 ||
        setresgid(worker_gid, worker_gid, worker_gid) < 0 ||
        setresuid(worker_uid, worker_uid, worker_uid) < 0 ||
        prctl(PR_SET_DUMPABLE, 0, 0, 0, 0) < 0 ||
        prctl(PR_SET_PDEATHSIG, SIGKILL, 0, 0, 0) < 0 ||
        getppid() != expected_parent ||
        prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) < 0)
        return -1;
    return t1_media_verify_worker_privileges(
        worker_uid,
        worker_gid,
        expected_parent);
}
