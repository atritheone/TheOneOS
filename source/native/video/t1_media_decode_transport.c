#define _GNU_SOURCE

#include "t1_media_decode_transport.h"

#include <errno.h>
#include <fcntl.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/uio.h>
#include <unistd.h>

void
t1_media_packet_initialize(struct t1_media_packet *packet)
{
    memset(packet, 0, sizeof(*packet));
    for (unsigned index = 0; index < T1_MEDIA_MAX_FRAME_OBJECTS; ++index)
        packet->fds[index] = -1;
}

void
t1_media_packet_close_fds(struct t1_media_packet *packet)
{
    for (unsigned index = 0; index < packet->fd_count; ++index) {
        if (packet->fds[index] >= 0)
            close(packet->fds[index]);
        packet->fds[index] = -1;
    }
    packet->fd_count = 0;
}

static int
t1_media_descriptor_cloexec(int descriptor)
{
    int flags = fcntl(descriptor, F_GETFD);
    if (flags < 0)
        return -1;
    if (flags & FD_CLOEXEC)
        return 0;
    return fcntl(descriptor, F_SETFD, flags | FD_CLOEXEC);
}

int
t1_media_receive_packet(int socket_fd, struct t1_media_packet *packet)
{
    t1_media_packet_initialize(packet);

    struct iovec vector = {
        .iov_base = packet->bytes,
        .iov_len = sizeof(packet->bytes),
    };
    char control[
        CMSG_SPACE(sizeof(int) * T1_MEDIA_MAX_FRAME_OBJECTS)] = {0};
    struct msghdr message = {
        .msg_iov = &vector,
        .msg_iovlen = 1,
        .msg_control = control,
        .msg_controllen = sizeof(control),
    };

    ssize_t received;
    do {
        received = recvmsg(socket_fd, &message, MSG_CMSG_CLOEXEC);
    } while (received < 0 && errno == EINTR);

    if (received <= 0)
        return (int)received;

    bool ancillary_invalid = false;
    for (struct cmsghdr *header = CMSG_FIRSTHDR(&message);
         header;
         header = CMSG_NXTHDR(&message, header)) {
        if (header->cmsg_level != SOL_SOCKET ||
            header->cmsg_type != SCM_RIGHTS ||
            header->cmsg_len < CMSG_LEN(sizeof(int))) {
            ancillary_invalid = true;
            continue;
        }

        size_t payload_size = header->cmsg_len - CMSG_LEN(0);
        if (payload_size % sizeof(int) != 0) {
            ancillary_invalid = true;
            continue;
        }
        unsigned count = (unsigned)(payload_size / sizeof(int));
        int *descriptors = (int *)CMSG_DATA(header);
        for (unsigned index = 0; index < count; ++index) {
            if (packet->fd_count >= T1_MEDIA_MAX_FRAME_OBJECTS) {
                close(descriptors[index]);
                ancillary_invalid = true;
                continue;
            }
            int descriptor = descriptors[index];
            if (t1_media_descriptor_cloexec(descriptor) < 0) {
                close(descriptor);
                ancillary_invalid = true;
                continue;
            }
            packet->fds[packet->fd_count++] = descriptor;
        }
    }

    packet->size = (size_t)received;
    if ((message.msg_flags & (MSG_TRUNC | MSG_CTRUNC)) != 0 ||
        packet->size < sizeof(struct t1_media_message_header)) {
        t1_media_packet_close_fds(packet);
        errno = EPROTO;
        return -1;
    }
    const struct t1_media_message_header *wire =
        (const struct t1_media_message_header *)packet->bytes;
    if (ancillary_invalid ||
        wire->magic != T1_MEDIA_PROTOCOL_MAGIC ||
        wire->version != T1_MEDIA_PROTOCOL_VERSION ||
        wire->size != packet->size ||
        wire->size > T1_MEDIA_MAX_CONTROL_BYTES ||
        wire->type < T1_MEDIA_HELLO ||
        wire->type > T1_MEDIA_BACKPRESSURE ||
        wire->flags != 0) {
        t1_media_packet_close_fds(packet);
        errno = EPROTO;
        return -1;
    }
    return 1;
}

int
t1_media_send_packet(int socket_fd,
                     uint16_t type,
                     uint64_t session,
                     uint64_t request,
                     uint64_t generation,
                     const void *payload,
                     size_t payload_size,
                     const int *fds,
                     unsigned fd_count)
{
    if (type < T1_MEDIA_HELLO ||
        type > T1_MEDIA_BACKPRESSURE ||
        payload_size > T1_MEDIA_MAX_CONTROL_BYTES -
            sizeof(struct t1_media_message_header) ||
        fd_count > T1_MEDIA_MAX_FRAME_OBJECTS ||
        (payload_size != 0 && !payload) ||
        (fd_count != 0 && !fds)) {
        errno = EINVAL;
        return -1;
    }

    struct t1_media_message_header header = {
        .magic = T1_MEDIA_PROTOCOL_MAGIC,
        .version = T1_MEDIA_PROTOCOL_VERSION,
        .type = type,
        .size = (uint32_t)(sizeof(header) + payload_size),
        .session = session,
        .request = request,
        .generation = generation,
        .flags = 0,
    };
    struct iovec vectors[2] = {
        {
            .iov_base = &header,
            .iov_len = sizeof(header),
        },
        {
            .iov_base = (void *)payload,
            .iov_len = payload_size,
        },
    };
    char control[
        CMSG_SPACE(sizeof(int) * T1_MEDIA_MAX_FRAME_OBJECTS)] = {0};
    struct msghdr message = {
        .msg_iov = vectors,
        .msg_iovlen = payload_size ? 2 : 1,
    };

    if (fd_count) {
        message.msg_control = control;
        message.msg_controllen = CMSG_SPACE(sizeof(int) * fd_count);
        struct cmsghdr *rights = CMSG_FIRSTHDR(&message);
        rights->cmsg_level = SOL_SOCKET;
        rights->cmsg_type = SCM_RIGHTS;
        rights->cmsg_len = CMSG_LEN(sizeof(int) * fd_count);
        memcpy(CMSG_DATA(rights), fds, sizeof(int) * fd_count);
    }

    ssize_t sent;
    do {
        sent = sendmsg(socket_fd, &message, MSG_NOSIGNAL);
    } while (sent < 0 && errno == EINTR);

    if (sent < 0)
        return -1;
    if ((size_t)sent != sizeof(header) + payload_size) {
        errno = EIO;
        return -1;
    }
    return 0;
}

int
t1_media_send_error(int socket_fd,
                    uint64_t session,
                    uint64_t request,
                    uint64_t generation,
                    uint32_t status,
                    const char *detail)
{
    size_t detail_size = detail ? strlen(detail) : 0;
    if (detail_size > T1_MEDIA_MAX_ERROR_TEXT)
        detail_size = T1_MEDIA_MAX_ERROR_TEXT;

    unsigned char payload[
        sizeof(struct t1_media_error) + T1_MEDIA_MAX_ERROR_TEXT] = {0};
    struct t1_media_error *error = (struct t1_media_error *)payload;
    error->status = status;
    error->detail_size = (uint32_t)detail_size;
    if (detail_size)
        memcpy(payload + sizeof(*error), detail, detail_size);

    return t1_media_send_packet(
        socket_fd,
        T1_MEDIA_ERROR,
        session,
        request,
        generation,
        payload,
        sizeof(*error) + detail_size,
        NULL,
        0);
}

const struct t1_media_message_header *
t1_media_packet_header(const struct t1_media_packet *packet)
{
    if (!packet || packet->size < sizeof(struct t1_media_message_header))
        return NULL;
    return (const struct t1_media_message_header *)packet->bytes;
}

void *
t1_media_packet_payload(struct t1_media_packet *packet)
{
    if (!packet || packet->size < sizeof(struct t1_media_message_header))
        return NULL;
    return packet->bytes + sizeof(struct t1_media_message_header);
}

const void *
t1_media_packet_payload_const(const struct t1_media_packet *packet)
{
    if (!packet || packet->size < sizeof(struct t1_media_message_header))
        return NULL;
    return packet->bytes + sizeof(struct t1_media_message_header);
}

size_t
t1_media_packet_payload_size(const struct t1_media_packet *packet)
{
    if (!packet || packet->size < sizeof(struct t1_media_message_header))
        return 0;
    return packet->size - sizeof(struct t1_media_message_header);
}
