#define _GNU_SOURCE

#include "../t1_media_decode_transport.h"
#include "../t1_media_decode_privilege.h"

#include <errno.h>
#include <dirent.h>
#include <fcntl.h>
#include <stddef.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

static int
fail(const char *detail)
{
    fprintf(stderr, "T1MD TEST FAILED: %s\n", detail);
    return 1;
}

static int
open_descriptor_count(void)
{
    DIR *directory = opendir("/proc/self/fd");
    if (!directory)
        return -1;
    int count = 0;
    for (;;) {
        struct dirent *entry = readdir(directory);
        if (!entry)
            break;
        if (strcmp(entry->d_name, ".") &&
            strcmp(entry->d_name, ".."))
            count++;
    }
    closedir(directory);
    return count;
}

static int
clear_cloexec(int descriptor)
{
    int flags = fcntl(descriptor, F_GETFD);
    if (flags < 0)
        return -1;
    return fcntl(descriptor, F_SETFD, flags & ~FD_CLOEXEC);
}

static int
test_layout(void)
{
    if (sizeof(struct t1_media_message_header) != 40)
        return fail("wire header size");
    if (offsetof(struct t1_media_message_header, magic) != 0 ||
        offsetof(struct t1_media_message_header, version) != 4 ||
        offsetof(struct t1_media_message_header, type) != 6 ||
        offsetof(struct t1_media_message_header, size) != 8 ||
        offsetof(struct t1_media_message_header, session) != 12 ||
        offsetof(struct t1_media_message_header, request) != 20 ||
        offsetof(struct t1_media_message_header, generation) != 28 ||
        offsetof(struct t1_media_message_header, flags) != 36)
        return fail("wire header offsets");
    if (T1_MEDIA_PROTOCOL_MAGIC != UINT32_C(0x444d3154))
        return fail("wire magic");
    if (T1_MEDIA_MAX_DECODE_REQUESTS != 1 ||
        sizeof(struct t1_media_backpressure) != 8 ||
        T1_MEDIA_BACKPRESSURE != 15 ||
        T1_MEDIA_FEATURE_BACKPRESSURE !=
            (UINT32_C(1) << 6) ||
        T1_MEDIA_FEATURE_LINEAR_MEMORY_OUTPUT !=
            (UINT32_C(1) << 7))
        return fail("backpressure layout/constants");
    return 0;
}

static int
test_transport(void)
{
    int sockets[2] = {-1, -1};
    if (socketpair(
            AF_UNIX,
            SOCK_SEQPACKET | SOCK_CLOEXEC,
            0,
            sockets) < 0)
        return fail("socketpair");

    struct t1_media_hello hello = {
        .minimum_version = 1,
        .maximum_version = 1,
        .required_features = T1_MEDIA_FEATURE_DMABUF,
        .maximum_frame_objects = T1_MEDIA_MAX_FRAME_OBJECTS,
        .maximum_frame_layers = T1_MEDIA_MAX_FRAME_LAYERS,
        .maximum_planes_per_layer =
            T1_MEDIA_MAX_PLANES_PER_LAYER,
    };
    if (t1_media_send_packet(
            sockets[0],
            T1_MEDIA_HELLO,
            0,
            9,
            0,
            &hello,
            sizeof(hello),
            NULL,
            0) < 0) {
        close(sockets[0]);
        close(sockets[1]);
        return fail("send packet");
    }

    struct t1_media_packet packet;
    if (t1_media_receive_packet(sockets[1], &packet) != 1) {
        close(sockets[0]);
        close(sockets[1]);
        return fail("receive packet");
    }
    const struct t1_media_message_header *header =
        t1_media_packet_header(&packet);
    if (!header ||
        header->type != T1_MEDIA_HELLO ||
        header->request != 9 ||
        t1_media_packet_payload_size(&packet) != sizeof(hello)) {
        t1_media_packet_close_fds(&packet);
        close(sockets[0]);
        close(sockets[1]);
        return fail("packet contents");
    }
    t1_media_packet_close_fds(&packet);

    struct t1_media_backpressure backpressure = {
        .state = T1_MEDIA_BACKPRESSURE_ENTER,
        .in_flight_frames =
            T1_MEDIA_MAX_IN_FLIGHT_FRAMES,
    };
    if (t1_media_send_packet(
            sockets[0],
            T1_MEDIA_BACKPRESSURE,
            7,
            11,
            1,
            &backpressure,
            sizeof(backpressure),
            NULL,
            0) < 0 ||
        t1_media_receive_packet(
            sockets[1],
            &packet) != 1) {
        close(sockets[0]);
        close(sockets[1]);
        return fail("backpressure transport");
    }
    header = t1_media_packet_header(&packet);
    const struct t1_media_backpressure *received_backpressure =
        t1_media_packet_payload_const(&packet);
    if (!header ||
        header->type != T1_MEDIA_BACKPRESSURE ||
        header->request != 11 ||
        header->generation != 1 ||
        packet.fd_count != 0 ||
        t1_media_packet_payload_size(&packet) !=
            sizeof(*received_backpressure) ||
        received_backpressure->state !=
            T1_MEDIA_BACKPRESSURE_ENTER ||
        received_backpressure->in_flight_frames !=
            T1_MEDIA_MAX_IN_FLIGHT_FRAMES) {
        t1_media_packet_close_fds(&packet);
        close(sockets[0]);
        close(sockets[1]);
        return fail("backpressure packet contents");
    }
    t1_media_packet_close_fds(&packet);

    int data = memfd_create("t1md-test-data", MFD_CLOEXEC);
    if (data < 0 ||
        t1_media_send_packet(
            sockets[0],
            T1_MEDIA_DECODE,
            7,
            10,
            1,
            &hello,
            sizeof(hello),
            &data,
            1) < 0 ||
        t1_media_receive_packet(sockets[1], &packet) != 1 ||
        packet.fd_count != 1 ||
        !(fcntl(packet.fds[0], F_GETFD) & FD_CLOEXEC)) {
        if (data >= 0)
            close(data);
        t1_media_packet_close_fds(&packet);
        close(sockets[0]);
        close(sockets[1]);
        return fail("SCM_RIGHTS/CLOEXEC");
    }
    close(data);
    t1_media_packet_close_fds(&packet);

    struct t1_media_message_header malformed = {
        .magic = T1_MEDIA_PROTOCOL_MAGIC,
        .version = T1_MEDIA_PROTOCOL_VERSION,
        .type = T1_MEDIA_HELLO,
        .size = sizeof(malformed) + 1,
    };
    if (send(sockets[0], &malformed, sizeof(malformed), 0) !=
            (ssize_t)sizeof(malformed) ||
        t1_media_receive_packet(sockets[1], &packet) != -1 ||
        errno != EPROTO) {
        close(sockets[0]);
        close(sockets[1]);
        return fail("malformed packet rejection");
    }

    int leak_probe = memfd_create("t1md-short-packet", MFD_CLOEXEC);
    int before = open_descriptor_count();
    unsigned char short_payload = 0;
    struct iovec short_vector = {
        .iov_base = &short_payload,
        .iov_len = sizeof(short_payload),
    };
    char short_control[CMSG_SPACE(sizeof(int))] = {0};
    struct msghdr short_message = {
        .msg_iov = &short_vector,
        .msg_iovlen = 1,
        .msg_control = short_control,
        .msg_controllen = sizeof(short_control),
    };
    struct cmsghdr *rights = CMSG_FIRSTHDR(&short_message);
    if (leak_probe < 0 || before < 0 || !rights) {
        if (leak_probe >= 0)
            close(leak_probe);
        close(sockets[0]);
        close(sockets[1]);
        return fail("short packet setup");
    }
    rights->cmsg_level = SOL_SOCKET;
    rights->cmsg_type = SCM_RIGHTS;
    rights->cmsg_len = CMSG_LEN(sizeof(int));
    memcpy(CMSG_DATA(rights), &leak_probe, sizeof(leak_probe));
    if (sendmsg(sockets[0], &short_message, 0) != 1 ||
        t1_media_receive_packet(sockets[1], &packet) != -1 ||
        errno != EPROTO ||
        open_descriptor_count() != before) {
        close(leak_probe);
        close(sockets[0]);
        close(sockets[1]);
        return fail("malformed packet descriptor cleanup");
    }
    close(leak_probe);

    close(sockets[0]);
    close(sockets[1]);
    return 0;
}

static int
receive_type(int descriptor,
             uint16_t type,
             struct t1_media_packet *packet)
{
    if (t1_media_receive_packet(descriptor, packet) != 1)
        return -1;
    const struct t1_media_message_header *header =
        t1_media_packet_header(packet);
    if (!header || header->type != type) {
        t1_media_packet_close_fds(packet);
        errno = EPROTO;
        return -1;
    }
    return 0;
}

static int
verify_worker_process_identity(pid_t worker, uid_t uid, gid_t gid)
{
    char path[64];
    snprintf(path, sizeof(path), "/proc/%ld/status", (long)worker);
    FILE *stream = fopen(path, "r");
    if (!stream)
        return -1;
    bool uid_valid = false;
    bool gid_valid = false;
    bool groups_empty = false;
    bool no_new_privs = false;
    bool capabilities_inheritable_empty = false;
    bool capabilities_permitted_empty = false;
    bool capabilities_effective_empty = false;
    bool capabilities_ambient_empty = false;
    bool seccomp_filter = false;
    char line[512];
    while (fgets(line, sizeof(line), stream)) {
        unsigned long real = 0;
        unsigned long effective = 0;
        unsigned long saved = 0;
        unsigned long filesystem = 0;
        if (sscanf(
                line,
                "Uid:\t%lu\t%lu\t%lu\t%lu",
                &real,
                &effective,
                &saved,
                &filesystem) == 4) {
            uid_valid =
                real == uid &&
                effective == uid &&
                saved == uid &&
                filesystem == uid;
        } else if (sscanf(
                       line,
                       "Gid:\t%lu\t%lu\t%lu\t%lu",
                       &real,
                       &effective,
                       &saved,
                       &filesystem) == 4) {
            gid_valid =
                real == gid &&
                effective == gid &&
                saved == gid &&
                filesystem == gid;
        } else if (!strncmp(line, "Groups:", 7)) {
            char *cursor = line + 7;
            while (*cursor == ' ' || *cursor == '\t')
                cursor++;
            groups_empty = *cursor == '\n' || *cursor == '\0';
        } else {
            unsigned value = 0;
            if (sscanf(line, "NoNewPrivs:\t%u", &value) == 1)
                no_new_privs = value == 1;
            if (sscanf(line, "Seccomp:\t%u", &value) == 1)
                seccomp_filter = value == 2;
            unsigned long long capabilities = ~0ULL;
            if (sscanf(line, "CapInh:\t%llx", &capabilities) == 1)
                capabilities_inheritable_empty = capabilities == 0;
            else if (sscanf(line, "CapPrm:\t%llx", &capabilities) == 1)
                capabilities_permitted_empty = capabilities == 0;
            else if (sscanf(line, "CapEff:\t%llx", &capabilities) == 1)
                capabilities_effective_empty = capabilities == 0;
            else if (sscanf(line, "CapAmb:\t%llx", &capabilities) == 1)
                capabilities_ambient_empty = capabilities == 0;
        }
    }
    fclose(stream);
    return uid_valid &&
            gid_valid &&
            groups_empty &&
            no_new_privs &&
            capabilities_inheritable_empty &&
            capabilities_permitted_empty &&
            capabilities_effective_empty &&
            capabilities_ambient_empty &&
            seccomp_filter
        ? 0
        : -1;
}

static int
send_create(int descriptor,
            uint64_t session,
            uint64_t request,
            uint64_t generation,
            uint32_t flags,
            uint32_t visible_width)
{
    struct t1_media_create create = {
        .codec = T1_MEDIA_CODEC_H264,
        .profile = T1_MEDIA_PROFILE_H264_HIGH,
        .coded_width = 1920,
        .coded_height = 1080,
        .visible_width = visible_width,
        .visible_height = 1080,
        .bit_depth = 8,
        .chroma_subsampling = T1_MEDIA_CHROMA_420,
        .flags = flags,
        .import_fourcc_count = 6,
        .import_fourcc = {
            T1_MEDIA_DRM_FORMAT_R8,
            T1_MEDIA_DRM_FORMAT_RG88,
            T1_MEDIA_DRM_FORMAT_GR88,
            T1_MEDIA_DRM_FORMAT_R16,
            T1_MEDIA_DRM_FORMAT_RG1616,
            T1_MEDIA_DRM_FORMAT_GR1616,
        },
    };
    return t1_media_send_packet(
        descriptor,
        T1_MEDIA_CREATE,
        session,
        request,
        generation,
        &create,
        sizeof(create),
        NULL,
        0);
}

static int
send_destroy(int descriptor,
             uint64_t session,
             uint64_t request,
             uint64_t generation)
{
    return t1_media_send_packet(
        descriptor,
        T1_MEDIA_DESTROY,
        session,
        request,
        generation,
        NULL,
        0,
        NULL,
        0);
}

static int
test_worker_reuse(const char *worker_path)
{
    if (geteuid() != 0)
        return fail("worker privilege test requires root");
    int sockets[2] = {-1, -1};
    if (socketpair(
            AF_UNIX,
            SOCK_SEQPACKET | SOCK_CLOEXEC,
            0,
            sockets) < 0)
        return fail("worker socketpair");
    int watchdogs[2] = {-1, -1};
    if (socketpair(
            AF_UNIX,
            SOCK_SEQPACKET | SOCK_CLOEXEC | SOCK_NONBLOCK,
            0,
            watchdogs) < 0) {
        close(sockets[0]);
        close(sockets[1]);
        return fail("worker watchdog socketpair");
    }

    int capabilities_fd = memfd_create(
        "t1md-test-capabilities",
        MFD_CLOEXEC | MFD_ALLOW_SEALING);
    if (capabilities_fd < 0) {
        close(sockets[0]);
        close(sockets[1]);
        close(watchdogs[0]);
        close(watchdogs[1]);
        return fail("capability memfd");
    }
    struct t1_media_capabilities capabilities = {
        .features =
            T1_MEDIA_FEATURE_DMABUF |
            T1_MEDIA_FEATURE_DRM_MODIFIERS |
            T1_MEDIA_FEATURE_RESET |
            T1_MEDIA_FEATURE_RELEASE_FENCE |
            T1_MEDIA_FEATURE_PER_SESSION_WORKER |
            T1_MEDIA_FEATURE_SEALED_INPUT |
            T1_MEDIA_FEATURE_BACKPRESSURE |
            T1_MEDIA_FEATURE_LINEAR_MEMORY_OUTPUT,
        .maximum_sessions = 8,
        .maximum_decode_requests = T1_MEDIA_MAX_DECODE_REQUESTS,
        .maximum_in_flight_frames =
            T1_MEDIA_MAX_IN_FLIGHT_FRAMES,
        .maximum_encoded_bytes = T1_MEDIA_MAX_ENCODED_BYTES,
        .maximum_extradata_bytes =
            T1_MEDIA_MAX_EXTRADATA_BYTES,
        .profile_count = 1,
        .vendor = "T1MD protocol test",
        .profiles = {
            {
                .codec = T1_MEDIA_CODEC_H264,
                .profile = T1_MEDIA_PROFILE_H264_HIGH,
                .bit_depths = T1_MEDIA_BIT_DEPTH_8,
                .output_formats = T1_MEDIA_OUTPUT_NV12,
                .minimum_width = 16,
                .minimum_height = 16,
                .maximum_width = 4096,
                .maximum_height = 4096,
            },
        },
    };
    if (write(
            capabilities_fd,
            &capabilities,
            sizeof(capabilities)) !=
            (ssize_t)sizeof(capabilities) ||
        fcntl(
            capabilities_fd,
            F_ADD_SEALS,
            F_SEAL_WRITE |
                F_SEAL_SHRINK |
                F_SEAL_GROW |
                F_SEAL_SEAL) < 0) {
        close(capabilities_fd);
        close(sockets[0]);
        close(sockets[1]);
        close(watchdogs[0]);
        close(watchdogs[1]);
        return fail("capability cache");
    }

    pid_t test_supervisor = getpid();
    pid_t child = fork();
    if (child < 0) {
        close(capabilities_fd);
        close(sockets[0]);
        close(sockets[1]);
        close(watchdogs[0]);
        close(watchdogs[1]);
        return fail("worker fork");
    }
    if (child == 0) {
        close(sockets[0]);
        if (clear_cloexec(sockets[1]) < 0 ||
            clear_cloexec(capabilities_fd) < 0 ||
            clear_cloexec(watchdogs[1]) < 0)
            _exit(126);
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
            capabilities_fd);
        snprintf(
            watchdog_text,
            sizeof(watchdog_text),
            "%d",
            watchdogs[1]);
        char parent_text[32];
        snprintf(
            parent_text,
            sizeof(parent_text),
            "%ld",
            (long)test_supervisor);
        if (t1_media_prepare_worker_privileges(
                65534,
                1000,
                test_supervisor) < 0)
            _exit(126);
        execl(
            worker_path,
            worker_path,
            "--t1md-worker",
            "--session-fd",
            session_text,
            "--capabilities-fd",
            capabilities_text,
            "--watchdog-fd",
            watchdog_text,
            "--device",
            "/nonexistent",
            "--maximum-sessions",
            "8",
            "--expected-uid",
            "65534",
            "--expected-gid",
            "1000",
            "--expected-parent",
            parent_text,
            (char *)NULL);
        _exit(127);
    }
    close(sockets[1]);
    close(watchdogs[1]);
    close(capabilities_fd);

    struct t1_media_hello hello = {
        .minimum_version = 1,
        .maximum_version = 1,
        .required_features =
            T1_MEDIA_FEATURE_DMABUF |
            T1_MEDIA_FEATURE_SEALED_INPUT |
            T1_MEDIA_FEATURE_BACKPRESSURE,
        .maximum_frame_objects = T1_MEDIA_MAX_FRAME_OBJECTS,
        .maximum_frame_layers = T1_MEDIA_MAX_FRAME_LAYERS,
        .maximum_planes_per_layer =
            T1_MEDIA_MAX_PLANES_PER_LAYER,
    };
    struct t1_media_packet packet;
    int result = 0;
    if (t1_media_send_packet(
            sockets[0],
            T1_MEDIA_HELLO,
            0,
            1,
            0,
            &hello,
            sizeof(hello),
            NULL,
            0) < 0 ||
        receive_type(
            sockets[0],
            T1_MEDIA_CAPABILITIES,
            &packet) < 0) {
        result = fail("worker HELLO/CAPABILITIES");
        goto finish;
    }
    const struct t1_media_message_header *header =
        t1_media_packet_header(&packet);
    uint64_t session = header ? header->session : 0;
    if (!session ||
        t1_media_packet_payload_size(&packet) !=
            sizeof(struct t1_media_capabilities)) {
        t1_media_packet_close_fds(&packet);
        result = fail("worker capabilities payload");
        goto finish;
    }
    t1_media_packet_close_fds(&packet);
    if (verify_worker_process_identity(child, 65534, 1000) < 0) {
        result = fail("worker uid/gid/groups/no_new_privs");
        goto finish;
    }

    if (send_create(
            sockets[0],
            session,
            2,
            1,
            T1_MEDIA_CREATE_ENCRYPTED,
            1920) < 0 ||
        receive_type(sockets[0], T1_MEDIA_CREATED, &packet) < 0) {
        result = fail("first CREATE response");
        goto finish;
    }
    const struct t1_media_created *created =
        t1_media_packet_payload_const(&packet);
    if (t1_media_packet_payload_size(&packet) != sizeof(*created) ||
        created->status !=
            T1_MEDIA_STATUS_UNSUPPORTED_CONFIGURATION) {
        t1_media_packet_close_fds(&packet);
        result = fail("first CREATE status");
        goto finish;
    }
    t1_media_packet_close_fds(&packet);

    if (send_destroy(sockets[0], session, 3, 1) < 0 ||
        receive_type(sockets[0], T1_MEDIA_DESTROY, &packet) < 0) {
        result = fail("first DESTROY response");
        goto finish;
    }
    const struct t1_media_result *destroyed =
        t1_media_packet_payload_const(&packet);
    if (t1_media_packet_payload_size(&packet) != sizeof(*destroyed) ||
        destroyed->status != T1_MEDIA_STATUS_OK) {
        t1_media_packet_close_fds(&packet);
        result = fail("first DESTROY status");
        goto finish;
    }
    t1_media_packet_close_fds(&packet);

    if (t1_media_send_packet(
            sockets[0],
            T1_MEDIA_HELLO,
            0,
            4,
            0,
            &hello,
            sizeof(hello),
            NULL,
            0) < 0 ||
        receive_type(
            sockets[0],
            T1_MEDIA_CAPABILITIES,
            &packet) < 0) {
        result = fail("reused HELLO/CAPABILITIES");
        goto finish;
    }
    header = t1_media_packet_header(&packet);
    uint64_t reused_session = header ? header->session : 0;
    if (!reused_session || reused_session == session) {
        t1_media_packet_close_fds(&packet);
        result = fail("reused session identity");
        goto finish;
    }
    session = reused_session;
    t1_media_packet_close_fds(&packet);

    if (send_create(
            sockets[0],
            session,
            5,
            1,
            0,
            0) < 0 ||
        receive_type(sockets[0], T1_MEDIA_CREATED, &packet) < 0) {
        result = fail("reused CREATE response");
        goto finish;
    }
    created = t1_media_packet_payload_const(&packet);
    if (t1_media_packet_payload_size(&packet) != sizeof(*created) ||
        created->status != T1_MEDIA_STATUS_INVALID_MESSAGE) {
        t1_media_packet_close_fds(&packet);
        result = fail("reused CREATE status");
        goto finish;
    }
    t1_media_packet_close_fds(&packet);

    if (send_destroy(sockets[0], session, 6, 1) < 0 ||
        receive_type(sockets[0], T1_MEDIA_DESTROY, &packet) < 0) {
        result = fail("reused DESTROY response");
        goto finish;
    }
    destroyed = t1_media_packet_payload_const(&packet);
    if (t1_media_packet_payload_size(&packet) != sizeof(*destroyed) ||
        destroyed->status != T1_MEDIA_STATUS_OK) {
        t1_media_packet_close_fds(&packet);
        result = fail("reused DESTROY status");
        goto finish;
    }
    t1_media_packet_close_fds(&packet);

finish:
    close(sockets[0]);
    int status = 0;
    while (waitpid(child, &status, 0) < 0 && errno == EINTR)
        ;
    close(watchdogs[0]);
    if (!result &&
        (!WIFEXITED(status) || WEXITSTATUS(status) != 0))
        result = fail("worker exit status");
    return result;
}

int
main(int argc, char **argv)
{
    if (argc != 2) {
        fprintf(stderr, "usage: %s WORKER\n", argv[0]);
        return 64;
    }
    if (test_layout() ||
        test_transport() ||
        test_worker_reuse(argv[1]))
        return 1;
    puts("T1MD protocol and worker reuse tests passed");
    return 0;
}
