#ifndef T1_MEDIA_DECODE_PRIVILEGE_H
#define T1_MEDIA_DECODE_PRIVILEGE_H

#include <sys/types.h>

#define T1_MEDIA_WORKER_RLIMIT_CORE 0ULL
#define T1_MEDIA_WORKER_RLIMIT_FSIZE (64ULL * 1024ULL * 1024ULL)
#define T1_MEDIA_WORKER_RLIMIT_NOFILE 256ULL
#define T1_MEDIA_WORKER_RLIMIT_NPROC 256ULL

/*
 * Irrevocably enter the measured decoder-worker identity.  This must be called
 * in the post-fork child immediately before exec.  In security-significant
 * order it bounds core/file/fd/process resources, removes supplementary groups
 * and all real/effective/saved root IDs, arms SIGKILL parent-death protection
 * after the credential change (setuid can clear an earlier PDEATHSIG), verifies
 * the expected parent still exists, and finally sets no_new_privs.
 */
int t1_media_prepare_worker_privileges(uid_t worker_uid,
                                       gid_t worker_gid,
                                       pid_t expected_parent);

/*
 * Verifies the complete post-drop identity, including saved IDs, empty
 * supplementary groups, disabled keep-caps, resource limits, and no_new_privs.
 */
int t1_media_verify_worker_privileges(uid_t worker_uid,
                                      gid_t worker_gid,
                                      pid_t expected_parent);

#endif /* T1_MEDIA_DECODE_PRIVILEGE_H */
