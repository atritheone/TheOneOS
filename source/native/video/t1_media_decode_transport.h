#ifndef T1_MEDIA_DECODE_TRANSPORT_H
#define T1_MEDIA_DECODE_TRANSPORT_H

#include <stddef.h>
#include <stdint.h>

#include "t1_media_decode_protocol.h"

struct t1_media_packet {
    unsigned char bytes[T1_MEDIA_MAX_CONTROL_BYTES];
    size_t size;
    int fds[T1_MEDIA_MAX_FRAME_OBJECTS];
    unsigned fd_count;
};

void t1_media_packet_initialize(struct t1_media_packet *packet);
void t1_media_packet_close_fds(struct t1_media_packet *packet);

/*
 * Returns 1 for one complete packet, 0 for orderly peer shutdown, or -1 with
 * errno set.  Malformed packets are rejected with errno=EPROTO and every
 * received descriptor is closed.
 */
int t1_media_receive_packet(int socket_fd, struct t1_media_packet *packet);

int t1_media_send_packet(int socket_fd,
                         uint16_t type,
                         uint64_t session,
                         uint64_t request,
                         uint64_t generation,
                         const void *payload,
                         size_t payload_size,
                         const int *fds,
                         unsigned fd_count);

int t1_media_send_error(int socket_fd,
                        uint64_t session,
                        uint64_t request,
                        uint64_t generation,
                        uint32_t status,
                        const char *detail);

const struct t1_media_message_header *
t1_media_packet_header(const struct t1_media_packet *packet);

void *t1_media_packet_payload(struct t1_media_packet *packet);
const void *t1_media_packet_payload_const(const struct t1_media_packet *packet);
size_t t1_media_packet_payload_size(const struct t1_media_packet *packet);

#endif /* T1_MEDIA_DECODE_TRANSPORT_H */
