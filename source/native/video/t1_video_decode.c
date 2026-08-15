#define _GNU_SOURCE

#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <poll.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/prctl.h>
#include <sys/types.h>
#include <unistd.h>

#include "t1_media_decode_sandbox.h"

#include <libavcodec/avcodec.h>
#include <libavformat/avformat.h>
#include <libavutil/avutil.h>
#include <libavutil/buffer.h>
#include <libavutil/hwcontext.h>
#include <libavutil/hwcontext_vaapi.h>
#include <libavutil/pixdesc.h>
#include <libavutil/rational.h>
#include <va/va.h>
#include <va/va_drmcommon.h>
#include <va/va_vpp.h>

#define T1_VIDEO_CONTROL_MAGIC 0x54315643u
#define T1_VIDEO_CONTROL_RELEASE 1u
#define T1_VIDEO_CONTROL_STOP 2u
#define T1_VIDEO_CONTROL_RESIZE 3u
#define T1_VIDEO_MAX_IN_FLIGHT 16
#define T1_VIDEO_MAX_OBJECTS 4
#define T1_VIDEO_MAX_IMPORT_FORMATS 256
#define T1_VIDEO_PACKET_LIMIT 16384

static int
t1_video_install_file_landlock(const char *path, unsigned *landlock_abi)
{
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
    if (!path || path[0] != '/') {
        errno = EINVAL;
        return -1;
    }
    if (prctl(PR_SET_DUMPABLE, 0, 0, 0, 0) < 0 ||
        prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) < 0)
        return -1;
    if (t1_media_install_landlock(
            paths,
            sizeof(paths) / sizeof(paths[0]),
            landlock_abi) < 0)
        return -1;
    return 0;
}

static int
t1_video_install_file_seccomp(unsigned landlock_abi)
{
    if (t1_media_install_worker_seccomp() < 0)
        return -1;
    fprintf(
        stderr,
        "T1_VIDEO_STAGE sandbox-ready landlock_abi=%u "
        "filesystem=input-only network=denied process=threads-only "
        "device_preinitialized=1\n",
        landlock_abi);
    return 0;
}

struct t1_video_control {
    uint32_t magic;
    uint32_t type;
    uint64_t frame_id;
};

struct t1_video_slot {
    uint64_t frame_id;
    AVFrame *decoded;
    int fds[T1_VIDEO_MAX_OBJECTS];
    unsigned fd_count;
    VASurfaceID output_surface;
    unsigned output_width;
    unsigned output_height;
};

struct t1_video_decoder {
    int socket_fd;
    int video_stream;
    int64_t next_frame_id;
    int64_t stream_origin;
    AVRational time_base;
    AVFormatContext *format;
    AVCodecContext *codec;
    AVBufferRef *device;
    VAConfigID vpp_config;
    VAContextID vpp_context;
    unsigned target_width;
    unsigned target_height;
    unsigned source_rotation;
    unsigned va_rotation;
    unsigned vpp_width;
    unsigned vpp_height;
    uint32_t import_formats[T1_VIDEO_MAX_IMPORT_FORMATS];
    unsigned import_format_count;
    struct t1_video_slot slots[T1_VIDEO_MAX_IN_FLIGHT];
    unsigned in_flight;
    bool first_packet_logged;
    bool first_frame_logged;
    bool first_surface_sync_logged;
    bool first_surface_export_logged;
    bool first_vpp_logged;
    bool vpp_disabled;
    bool stopped;
};

static enum AVPixelFormat
t1_video_hardware_format(AVCodecContext *context, const enum AVPixelFormat *formats)
{
    (void)context;

    for (const enum AVPixelFormat *format = formats;
         *format != AV_PIX_FMT_NONE;
         ++format) {
        if (*format == AV_PIX_FMT_VAAPI)
            return *format;
    }

    return AV_PIX_FMT_NONE;
}

static const char *
t1_video_profile_name(VAProfile profile)
{
    switch (profile) {
    case VAProfileMPEG2Simple: return "MPEG2Simple";
    case VAProfileMPEG2Main: return "MPEG2Main";
    case VAProfileH264ConstrainedBaseline: return "H264ConstrainedBaseline";
    case VAProfileH264Main: return "H264Main";
    case VAProfileH264High: return "H264High";
    case VAProfileVC1Simple: return "VC1Simple";
    case VAProfileVC1Main: return "VC1Main";
    case VAProfileVC1Advanced: return "VC1Advanced";
    case VAProfileHEVCMain: return "HEVCMain";
    case VAProfileHEVCMain10: return "HEVCMain10";
    case VAProfileHEVCMain12: return "HEVCMain12";
    case VAProfileVP9Profile0: return "VP9Profile0";
    case VAProfileVP9Profile1: return "VP9Profile1";
    case VAProfileVP9Profile2: return "VP9Profile2";
    case VAProfileVP9Profile3: return "VP9Profile3";
    case VAProfileAV1Profile0: return "AV1Profile0";
    case VAProfileAV1Profile1: return "AV1Profile1";
    case VAProfileAV1Profile2: return "AV1Profile2";
    default: return "Unknown";
    }
}

static const char *
t1_video_codec_name(VAProfile profile)
{
    switch (profile) {
    case VAProfileH264ConstrainedBaseline:
    case VAProfileH264Main:
    case VAProfileH264High:
        return "H264";
    case VAProfileMPEG2Simple:
    case VAProfileMPEG2Main:
        return "MPEG2VIDEO";
    case VAProfileVC1Simple:
    case VAProfileVC1Main:
    case VAProfileVC1Advanced:
        return "VC1";
    case VAProfileHEVCMain:
    case VAProfileHEVCMain10:
    case VAProfileHEVCMain12:
        return "HEVC";
    case VAProfileVP9Profile0:
    case VAProfileVP9Profile1:
    case VAProfileVP9Profile2:
    case VAProfileVP9Profile3:
        return "VP9";
    case VAProfileAV1Profile0:
    case VAProfileAV1Profile1:
    case VAProfileAV1Profile2:
        return "AV1";
    default:
        return "UNKNOWN";
    }
}

static bool
t1_video_rt_supports_8_bit(uint32_t format)
{
    uint32_t mask = VA_RT_FORMAT_YUV420 |
                    VA_RT_FORMAT_YUV422 |
                    VA_RT_FORMAT_YUV444;
    return (format & mask) != 0;
}

static bool
t1_video_rt_supports_10_bit(uint32_t format)
{
    uint32_t mask = 0;
#ifdef VA_RT_FORMAT_YUV420_10
    mask |= VA_RT_FORMAT_YUV420_10;
#endif
#ifdef VA_RT_FORMAT_YUV422_10
    mask |= VA_RT_FORMAT_YUV422_10;
#endif
#ifdef VA_RT_FORMAT_YUV444_10
    mask |= VA_RT_FORMAT_YUV444_10;
#endif
    return mask && (format & mask) != 0;
}

static bool
t1_video_rt_supports_12_bit(uint32_t format)
{
    uint32_t mask = 0;
#ifdef VA_RT_FORMAT_YUV420_12
    mask |= VA_RT_FORMAT_YUV420_12;
#endif
#ifdef VA_RT_FORMAT_YUV422_12
    mask |= VA_RT_FORMAT_YUV422_12;
#endif
#ifdef VA_RT_FORMAT_YUV444_12
    mask |= VA_RT_FORMAT_YUV444_12;
#endif
    return mask && (format & mask) != 0;
}

static void
t1_video_print_format(bool *first,
                      const char *chroma,
                      unsigned bit_depth)
{
    if (!*first)
        putchar(',');
    *first = false;
    printf("{\"chroma\":\"%s\",\"bit_depth\":%u}", chroma, bit_depth);
}

static int
t1_video_probe(const char *device)
{
    AVBufferRef *reference = NULL;
    av_log_set_level(AV_LOG_VERBOSE);
    int result = av_hwdevice_ctx_create(
        &reference,
        AV_HWDEVICE_TYPE_VAAPI,
        device,
        NULL,
        0);
    if (result < 0) {
        char detail[AV_ERROR_MAX_STRING_SIZE] = {0};
        av_strerror(result, detail, sizeof(detail));
        fprintf(stderr, "VAAPI device creation failed: %s\n", detail);
        return 2;
    }

    AVHWDeviceContext *hardware = (AVHWDeviceContext *)reference->data;
    AVVAAPIDeviceContext *vaapi = (AVVAAPIDeviceContext *)hardware->hwctx;
    VADisplay display = vaapi->display;
    int maximum = vaMaxNumProfiles(display);
    VAProfile *profiles = calloc((size_t)maximum, sizeof(*profiles));
    int count = 0;

    if (!profiles ||
        vaQueryConfigProfiles(display, profiles, &count) != VA_STATUS_SUCCESS) {
        free(profiles);
        av_buffer_unref(&reference);
        fprintf(stderr, "VAAPI profile query failed\n");
        return 3;
    }

    printf("{\"format\":1,\"device\":\"%s\",\"vendor\":\"",
           device ? device : "");
    const char *vendor = vaQueryVendorString(display);
    for (const char *cursor = vendor ? vendor : ""; *cursor; ++cursor) {
        if (*cursor == '"' || *cursor == '\\')
            putchar('\\');
        if ((unsigned char)*cursor >= 0x20)
            putchar(*cursor);
    }
    printf("\",\"profiles\":[");

    bool first = true;
    for (int index = 0; index < count; ++index) {
        VAEntrypoint entries[16] = {0};
        int entry_count = 0;
        if (vaQueryConfigEntrypoints(
                display,
                profiles[index],
                entries,
                &entry_count) != VA_STATUS_SUCCESS)
            continue;

        bool decode = false;
        for (int entry = 0; entry < entry_count; ++entry) {
            if (entries[entry] == VAEntrypointVLD) {
                decode = true;
                break;
            }
        }
        if (!decode)
            continue;

        VAConfigAttrib attributes[3] = {
            {.type = VAConfigAttribRTFormat},
            {.type = VAConfigAttribMaxPictureWidth},
            {.type = VAConfigAttribMaxPictureHeight},
        };
        vaGetConfigAttributes(
            display,
            profiles[index],
            VAEntrypointVLD,
            attributes,
            3);

        if (!first)
            putchar(',');
        first = false;
        uint32_t rt_format =
            attributes[0].value == VA_ATTRIB_NOT_SUPPORTED
                ? 0u
                : attributes[0].value;
        printf(
            "{\"id\":%d,\"name\":\"%s\",\"codec\":\"%s\","
            "\"rt_format\":%u,\"max_width\":%u,\"max_height\":%u,"
            "\"bit_depths\":[",
            (int)profiles[index],
            t1_video_profile_name(profiles[index]),
            t1_video_codec_name(profiles[index]),
            rt_format,
            attributes[1].value == VA_ATTRIB_NOT_SUPPORTED ? 0u : attributes[1].value,
            attributes[2].value == VA_ATTRIB_NOT_SUPPORTED ? 0u : attributes[2].value);
        bool first_depth = true;
        if (t1_video_rt_supports_8_bit(rt_format)) {
            fputs("8", stdout);
            first_depth = false;
        }
        if (t1_video_rt_supports_10_bit(rt_format)) {
            fputs(first_depth ? "10" : ",10", stdout);
            first_depth = false;
        }
        if (t1_video_rt_supports_12_bit(rt_format))
            fputs(first_depth ? "12" : ",12", stdout);
        fputs("],\"formats\":[", stdout);
        bool first_format = true;
        if (rt_format & VA_RT_FORMAT_YUV420)
            t1_video_print_format(&first_format, "4:2:0", 8);
        if (rt_format & VA_RT_FORMAT_YUV422)
            t1_video_print_format(&first_format, "4:2:2", 8);
        if (rt_format & VA_RT_FORMAT_YUV444)
            t1_video_print_format(&first_format, "4:4:4", 8);
#ifdef VA_RT_FORMAT_YUV420_10
        if (rt_format & VA_RT_FORMAT_YUV420_10)
            t1_video_print_format(&first_format, "4:2:0", 10);
#endif
#ifdef VA_RT_FORMAT_YUV422_10
        if (rt_format & VA_RT_FORMAT_YUV422_10)
            t1_video_print_format(&first_format, "4:2:2", 10);
#endif
#ifdef VA_RT_FORMAT_YUV444_10
        if (rt_format & VA_RT_FORMAT_YUV444_10)
            t1_video_print_format(&first_format, "4:4:4", 10);
#endif
#ifdef VA_RT_FORMAT_YUV420_12
        if (rt_format & VA_RT_FORMAT_YUV420_12)
            t1_video_print_format(&first_format, "4:2:0", 12);
#endif
#ifdef VA_RT_FORMAT_YUV422_12
        if (rt_format & VA_RT_FORMAT_YUV422_12)
            t1_video_print_format(&first_format, "4:2:2", 12);
#endif
#ifdef VA_RT_FORMAT_YUV444_12
        if (rt_format & VA_RT_FORMAT_YUV444_12)
            t1_video_print_format(&first_format, "4:4:4", 12);
#endif
        fputs("]}", stdout);
    }

    printf("]}\n");
    free(profiles);
    av_buffer_unref(&reference);
    return 0;
}

static void
t1_video_release_slot(struct t1_video_decoder *decoder, unsigned index)
{
    struct t1_video_slot *slot = &decoder->slots[index];
    if (!slot->frame_id)
        return;

    for (unsigned object = 0; object < slot->fd_count; ++object) {
        if (slot->fds[object] >= 0)
            close(slot->fds[object]);
        slot->fds[object] = -1;
    }
    slot->fd_count = 0;
    av_frame_free(&slot->decoded);
    slot->frame_id = 0;
    if (decoder->in_flight)
        decoder->in_flight--;
}

static void
t1_video_release_all(struct t1_video_decoder *decoder)
{
    for (unsigned index = 0; index < T1_VIDEO_MAX_IN_FLIGHT; ++index)
        t1_video_release_slot(decoder, index);
}

static VADisplay
t1_video_display(struct t1_video_decoder *decoder)
{
    if (!decoder->device)
        return NULL;
    AVHWDeviceContext *hardware =
        (AVHWDeviceContext *)decoder->device->data;
    AVVAAPIDeviceContext *vaapi =
        (AVVAAPIDeviceContext *)hardware->hwctx;
    return vaapi->display;
}

static void
t1_video_destroy_vpp(struct t1_video_decoder *decoder)
{
    VADisplay display = t1_video_display(decoder);
    if (!display)
        return;
    if (decoder->vpp_context != VA_INVALID_ID) {
        vaDestroyContext(display, decoder->vpp_context);
        decoder->vpp_context = VA_INVALID_ID;
    }
    if (decoder->vpp_config != VA_INVALID_ID) {
        vaDestroyConfig(display, decoder->vpp_config);
        decoder->vpp_config = VA_INVALID_ID;
    }
    decoder->vpp_width = 0;
    decoder->vpp_height = 0;
}

static void
t1_video_destroy_vpp_surfaces(struct t1_video_decoder *decoder)
{
    VADisplay display = t1_video_display(decoder);
    if (!display)
        return;
    for (unsigned index = 0; index < T1_VIDEO_MAX_IN_FLIGHT; ++index) {
        struct t1_video_slot *slot = &decoder->slots[index];
        if (slot->output_surface != VA_INVALID_SURFACE) {
            vaDestroySurfaces(display, &slot->output_surface, 1);
            slot->output_surface = VA_INVALID_SURFACE;
            slot->output_width = 0;
            slot->output_height = 0;
        }
    }
}

static int
t1_video_control(struct t1_video_decoder *decoder, bool wait)
{
    struct pollfd descriptor = {
        .fd = decoder->socket_fd,
        .events = POLLIN | POLLHUP | POLLERR,
    };

    int ready = poll(&descriptor, 1, wait ? -1 : 0);
    if (ready < 0) {
        if (errno == EINTR)
            return 0;
        return -1;
    }
    if (!ready)
        return 0;
    if (descriptor.revents & (POLLHUP | POLLERR | POLLNVAL)) {
        decoder->stopped = true;
        return -1;
    }

    struct t1_video_control message = {0};
    ssize_t length = recv(
        decoder->socket_fd,
        &message,
        sizeof(message),
        MSG_DONTWAIT);
    if (length == 0) {
        decoder->stopped = true;
        return -1;
    }
    if (length < 0) {
        if (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR)
            return 0;
        return -1;
    }
    if ((size_t)length != sizeof(message) ||
        message.magic != T1_VIDEO_CONTROL_MAGIC)
        return 0;

    if (message.type == T1_VIDEO_CONTROL_STOP) {
        decoder->stopped = true;
        return 1;
    }
    if (message.type == T1_VIDEO_CONTROL_RESIZE) {
        unsigned width = (unsigned)(message.frame_id >> 32);
        unsigned height = (unsigned)(message.frame_id & UINT32_MAX);
        if (width >= 2 && height >= 2) {
            decoder->target_width = width & ~1u;
            decoder->target_height = height & ~1u;
            decoder->vpp_disabled = false;
            fprintf(stderr,
                    "T1_VIDEO_STAGE presentation-resize width=%u height=%u\n",
                    decoder->target_width,
                    decoder->target_height);
        }
        return 1;
    }
    if (message.type != T1_VIDEO_CONTROL_RELEASE)
        return 0;

    for (unsigned index = 0; index < T1_VIDEO_MAX_IN_FLIGHT; ++index) {
        if (decoder->slots[index].frame_id == message.frame_id) {
            t1_video_release_slot(decoder, index);
            break;
        }
    }
    return 1;
}

static int
t1_video_json_append(char *buffer, size_t capacity, size_t *used,
                     const char *format, ...)
{
    if (*used >= capacity)
        return -1;

    va_list arguments;
    va_start(arguments, format);
    int count = vsnprintf(
        buffer + *used,
        capacity - *used,
        format,
        arguments);
    va_end(arguments);
    if (count < 0 || (size_t)count >= capacity - *used)
        return -1;
    *used += (size_t)count;
    return 0;
}

static int
t1_video_send_json(struct t1_video_decoder *decoder,
                   const char *json,
                   const int *fds,
                   unsigned fd_count)
{
    struct iovec vector = {
        .iov_base = (void *)json,
        .iov_len = strlen(json),
    };
    char control[CMSG_SPACE(sizeof(int) * T1_VIDEO_MAX_OBJECTS)] = {0};
    struct msghdr message = {
        .msg_iov = &vector,
        .msg_iovlen = 1,
    };

    if (fd_count) {
        message.msg_control = control;
        message.msg_controllen = CMSG_SPACE(sizeof(int) * fd_count);
        struct cmsghdr *header = CMSG_FIRSTHDR(&message);
        header->cmsg_level = SOL_SOCKET;
        header->cmsg_type = SCM_RIGHTS;
        header->cmsg_len = CMSG_LEN(sizeof(int) * fd_count);
        memcpy(CMSG_DATA(header), fds, sizeof(int) * fd_count);
    }

    for (;;) {
        ssize_t sent = sendmsg(decoder->socket_fd, &message, MSG_NOSIGNAL);
        if (sent >= 0)
            return sent == (ssize_t)vector.iov_len ? 0 : -1;
        if (errno != EINTR)
            return -1;
    }
}

static unsigned
t1_video_open_slot(struct t1_video_decoder *decoder)
{
    while (!decoder->stopped) {
        for (unsigned index = 0; index < T1_VIDEO_MAX_IN_FLIGHT; ++index) {
            if (!decoder->slots[index].frame_id)
                return index;
        }
        t1_video_control(decoder, true);
    }
    return T1_VIDEO_MAX_IN_FLIGHT;
}

static int
t1_video_vpp_context(struct t1_video_decoder *decoder,
                     unsigned width,
                     unsigned height)
{
    if (decoder->vpp_disabled)
        return AVERROR(ENOSYS);
    if (decoder->vpp_context != VA_INVALID_ID &&
        decoder->vpp_width == width &&
        decoder->vpp_height == height)
        return 0;

    VADisplay display = t1_video_display(decoder);
    if (!display)
        return AVERROR(EINVAL);
    t1_video_destroy_vpp(decoder);

    VAStatus status = vaCreateConfig(
        display,
        VAProfileNone,
        VAEntrypointVideoProc,
        NULL,
        0,
        &decoder->vpp_config);
    if (status != VA_STATUS_SUCCESS)
        goto unavailable;
    status = vaCreateContext(
        display,
        decoder->vpp_config,
        (int)width,
        (int)height,
        VA_PROGRESSIVE,
        NULL,
        0,
        &decoder->vpp_context);
    if (status != VA_STATUS_SUCCESS)
        goto unavailable;

    decoder->vpp_width = width;
    decoder->vpp_height = height;
    return 0;

unavailable:
    fprintf(stderr,
            "VAAPI video processing unavailable: %s (%d)\n",
            vaErrorStr(status),
            status);
    t1_video_destroy_vpp(decoder);
    decoder->vpp_disabled = true;
    return AVERROR(ENOSYS);
}

static uint32_t
t1_video_output_format(AVFrame *frame, uint32_t *fourcc)
{
    enum AVPixelFormat software = AV_PIX_FMT_NONE;
    if (frame->hw_frames_ctx) {
        AVHWFramesContext *frames =
            (AVHWFramesContext *)frame->hw_frames_ctx->data;
        software = frames->sw_format;
    }

#ifdef VA_RT_FORMAT_YUV420_10
    if (software == AV_PIX_FMT_P010LE || software == AV_PIX_FMT_P010BE) {
        *fourcc = VA_FOURCC_P010;
        return VA_RT_FORMAT_YUV420_10;
    }
#endif
#ifdef VA_RT_FORMAT_YUV420_12
    if (software == AV_PIX_FMT_P012LE || software == AV_PIX_FMT_P012BE) {
        *fourcc = VA_FOURCC_P012;
        return VA_RT_FORMAT_YUV420_12;
    }
#endif
    *fourcc = VA_FOURCC_NV12;
    return VA_RT_FORMAT_YUV420;
}

static enum AVPixelFormat
t1_video_software_format(AVFrame *frame)
{
    if (!frame->hw_frames_ctx)
        return AV_PIX_FMT_NONE;
    AVHWFramesContext *frames =
        (AVHWFramesContext *)frame->hw_frames_ctx->data;
    return frames->sw_format;
}

static int
t1_video_bit_depth(AVFrame *frame)
{
    const AVPixFmtDescriptor *description =
        av_pix_fmt_desc_get(t1_video_software_format(frame));
    if (!description || description->nb_components < 1)
        return 0;
    return description->comp[0].depth;
}

static void
t1_video_layer_size(AVFrame *frame,
                    uint32_t layer,
                    uint32_t layer_count,
                    unsigned width,
                    unsigned height,
                    unsigned *layer_width,
                    unsigned *layer_height)
{
    *layer_width = width;
    *layer_height = height;
    if (layer_count < 2 || layer == 0)
        return;
    const AVPixFmtDescriptor *description =
        av_pix_fmt_desc_get(t1_video_software_format(frame));
    if (!description)
        return;
    unsigned width_shift = (unsigned)description->log2_chroma_w;
    unsigned height_shift = (unsigned)description->log2_chroma_h;
    *layer_width = (width + (1u << width_shift) - 1u) >> width_shift;
    *layer_height = (height + (1u << height_shift) - 1u) >> height_shift;
}

static int
t1_video_vpp_surface(struct t1_video_decoder *decoder,
                     struct t1_video_slot *slot,
                     AVFrame *frame,
                     VASurfaceID input,
                     VASurfaceID *output,
                     unsigned *width,
                     unsigned *height)
{
    unsigned target_width = decoder->target_width;
    unsigned target_height = decoder->target_height;
    unsigned crop_left = frame->crop_left < (size_t)frame->width
        ? (unsigned)frame->crop_left
        : 0u;
    unsigned crop_right = frame->crop_right < (size_t)frame->width - crop_left
        ? (unsigned)frame->crop_right
        : 0u;
    unsigned crop_top = frame->crop_top < (size_t)frame->height
        ? (unsigned)frame->crop_top
        : 0u;
    unsigned crop_bottom = frame->crop_bottom < (size_t)frame->height - crop_top
        ? (unsigned)frame->crop_bottom
        : 0u;
    unsigned source_width = (unsigned)frame->width - crop_left - crop_right;
    unsigned source_height = (unsigned)frame->height - crop_top - crop_bottom;
    bool rotated = decoder->va_rotation != VA_ROTATION_NONE;
    unsigned display_width =
        decoder->source_rotation == 90u || decoder->source_rotation == 270u
            ? source_height
            : source_width;
    unsigned display_height =
        decoder->source_rotation == 90u || decoder->source_rotation == 270u
            ? source_width
            : source_height;
    bool cropped = crop_left || crop_right || crop_top || crop_bottom;
    if (target_width < 2 || target_height < 2 ||
        (!rotated && !cropped &&
         target_width >= display_width &&
         target_height >= display_height)) {
        *output = input;
        *width = (unsigned)frame->width;
        *height = (unsigned)frame->height;
        return 0;
    }
    const AVPixFmtDescriptor *description =
        av_pix_fmt_desc_get(t1_video_software_format(frame));
    if (!description ||
        description->log2_chroma_w != 1 ||
        description->log2_chroma_h != 1) {
        /*
         * The bounded presentation formats below are NV12/P010/P012. Keep
         * uncommon 4:2:2 and 4:4:4 decode surfaces intact instead of reducing
         * their chroma fidelity merely to save composition bandwidth.
         */
        if (rotated || cropped)
            return AVERROR(ENOSYS);
        *output = input;
        *width = (unsigned)frame->width;
        *height = (unsigned)frame->height;
        return 0;
    }
    target_width = target_width > display_width
        ? display_width
        : target_width;
    target_height = target_height > display_height
        ? display_height
        : target_height;
    target_width &= ~1u;
    target_height &= ~1u;
    if (target_width < 2 || target_height < 2)
        return AVERROR(EINVAL);

    int result = t1_video_vpp_context(
        decoder,
        target_width,
        target_height);
    if (result < 0)
        return result;

    VADisplay display = t1_video_display(decoder);
    if (slot->output_surface != VA_INVALID_SURFACE &&
        (slot->output_width != target_width ||
         slot->output_height != target_height)) {
        vaDestroySurfaces(display, &slot->output_surface, 1);
        slot->output_surface = VA_INVALID_SURFACE;
        slot->output_width = 0;
        slot->output_height = 0;
    }
    if (slot->output_surface == VA_INVALID_SURFACE) {
        uint32_t fourcc = VA_FOURCC_NV12;
        uint32_t rt_format = t1_video_output_format(frame, &fourcc);
        VASurfaceAttrib attribute = {
            .type = VASurfaceAttribPixelFormat,
            .flags = VA_SURFACE_ATTRIB_SETTABLE,
            .value = {
                .type = VAGenericValueTypeInteger,
                .value.i = (int)fourcc,
            },
        };
        VAStatus status = vaCreateSurfaces(
            display,
            rt_format,
            target_width,
            target_height,
            &slot->output_surface,
            1,
            &attribute,
            1);
        if (status != VA_STATUS_SUCCESS) {
            fprintf(stderr,
                    "VAAPI VPP output surface creation failed: %s (%d)\n",
                    vaErrorStr(status),
                    status);
            slot->output_surface = VA_INVALID_SURFACE;
            return AVERROR_EXTERNAL;
        }
        slot->output_width = target_width;
        slot->output_height = target_height;
    }

    VARectangle source_region = {
        .x = (int16_t)crop_left,
        .y = (int16_t)crop_top,
        .width = (uint16_t)source_width,
        .height = (uint16_t)source_height,
    };
    VARectangle output_region = {
        .x = 0,
        .y = 0,
        .width = (uint16_t)target_width,
        .height = (uint16_t)target_height,
    };
    VAProcPipelineParameterBuffer parameters = {
        .surface = input,
        .surface_region = &source_region,
        .output_region = &output_region,
        .rotation_state = decoder->va_rotation,
    };
#ifdef VA_FILTER_SCALING_HQ
    parameters.filter_flags = VA_FILTER_SCALING_HQ;
#endif
    VABufferID buffer = VA_INVALID_ID;
    bool begun = false;
    VAStatus status = vaCreateBuffer(
        display,
        decoder->vpp_context,
        VAProcPipelineParameterBufferType,
        sizeof(parameters),
        1,
        &parameters,
        &buffer);
    if (status == VA_STATUS_SUCCESS) {
        status = vaBeginPicture(
            display,
            decoder->vpp_context,
            slot->output_surface);
        begun = status == VA_STATUS_SUCCESS;
    }
    if (status == VA_STATUS_SUCCESS)
        status = vaRenderPicture(
            display,
            decoder->vpp_context,
            &buffer,
            1);
    if (status == VA_STATUS_SUCCESS) {
        status = vaEndPicture(display, decoder->vpp_context);
        begun = false;
    }
    if (begun)
        vaEndPicture(display, decoder->vpp_context);
    if (buffer != VA_INVALID_ID)
        vaDestroyBuffer(display, buffer);
    if (status != VA_STATUS_SUCCESS) {
        fprintf(stderr,
                "VAAPI video processing failed: %s (%d)\n",
                vaErrorStr(status),
                status);
        return AVERROR_EXTERNAL;
    }

    if (!decoder->first_vpp_logged) {
        decoder->first_vpp_logged = true;
        fprintf(stderr,
                "T1_VIDEO_STAGE first-vpp-surface source=%dx%d output=%ux%u\n",
                frame->width,
                frame->height,
                target_width,
                target_height);
    }
    *output = slot->output_surface;
    *width = target_width;
    *height = target_height;
    return 0;
}

static int
t1_video_send_frame(struct t1_video_decoder *decoder, AVFrame *frame)
{
    if (frame->format != AV_PIX_FMT_VAAPI) {
        fprintf(stderr,
                "decoder returned %s instead of a VAAPI surface\n",
                av_get_pix_fmt_name((enum AVPixelFormat)frame->format));
        return AVERROR(EINVAL);
    }

    VADisplay display = t1_video_display(decoder);
    VASurfaceID decoded_surface = (VASurfaceID)(uintptr_t)frame->data[3];
    VAStatus status = vaSyncSurface(display, decoded_surface);
    if (status != VA_STATUS_SUCCESS) {
        fprintf(stderr,
                "VAAPI surface sync failed for surface %u: %s (%d)\n",
                (unsigned)decoded_surface,
                vaErrorStr(status),
                status);
        return AVERROR_EXTERNAL;
    }
    if (!decoder->first_surface_sync_logged) {
        decoder->first_surface_sync_logged = true;
        fprintf(stderr,
                "T1_VIDEO_STAGE first-surface-synced surface=%u\n",
                (unsigned)decoded_surface);
    }

    unsigned slot_index = t1_video_open_slot(decoder);
    if (slot_index >= T1_VIDEO_MAX_IN_FLIGHT)
        return AVERROR_EXIT;
    struct t1_video_slot *slot = &decoder->slots[slot_index];
    VASurfaceID surface = decoded_surface;
    unsigned output_width = (unsigned)frame->width;
    unsigned output_height = (unsigned)frame->height;
    int vpp_result = t1_video_vpp_surface(
        decoder,
        slot,
        frame,
        decoded_surface,
        &surface,
        &output_width,
        &output_height);
    if (vpp_result < 0) {
        decoder->vpp_disabled = true;
        surface = decoded_surface;
        output_width = (unsigned)frame->width;
        output_height = (unsigned)frame->height;
    }
    if (surface != decoded_surface) {
        status = vaSyncSurface(display, surface);
        if (status != VA_STATUS_SUCCESS) {
            fprintf(stderr,
                    "VAAPI VPP surface sync failed for surface %u: %s (%d)\n",
                    (unsigned)surface,
                    vaErrorStr(status),
                    status);
            decoder->vpp_disabled = true;
            surface = decoded_surface;
            output_width = (unsigned)frame->width;
            output_height = (unsigned)frame->height;
        }
    }

    VADRMPRIMESurfaceDescriptor drm = {0};
    status = vaExportSurfaceHandle(
        display,
        surface,
        VA_SURFACE_ATTRIB_MEM_TYPE_DRM_PRIME_2,
        VA_EXPORT_SURFACE_READ_ONLY |
            VA_EXPORT_SURFACE_COMPOSED_LAYERS,
        &drm);
    const char *export_mode = "composed";
    bool acceptable =
        status == VA_STATUS_SUCCESS &&
        drm.num_layers >= 1 &&
        drm.num_layers <= 2;
    if (acceptable && decoder->import_format_count) {
        for (uint32_t layer = 0; layer < drm.num_layers; ++layer) {
            bool matched = false;
            for (unsigned format = 0;
                 format < decoder->import_format_count;
                 ++format) {
                if (drm.layers[layer].drm_format ==
                    decoder->import_formats[format]) {
                    matched = true;
                    break;
                }
            }
            if (!matched) {
                acceptable = false;
                break;
            }
        }
    }
    if (!acceptable) {
        if (status == VA_STATUS_SUCCESS) {
            for (uint32_t object = 0; object < drm.num_objects; ++object)
                close(drm.objects[object].fd);
        }
        memset(&drm, 0, sizeof(drm));
        status = vaExportSurfaceHandle(
            display,
            surface,
            VA_SURFACE_ATTRIB_MEM_TYPE_DRM_PRIME_2,
            VA_EXPORT_SURFACE_READ_ONLY |
                VA_EXPORT_SURFACE_SEPARATE_LAYERS,
            &drm);
        export_mode = "separate";
        acceptable =
            status == VA_STATUS_SUCCESS &&
            drm.num_layers >= 1 &&
            drm.num_layers <= 2;
        if (acceptable && decoder->import_format_count) {
            for (uint32_t layer = 0; layer < drm.num_layers; ++layer) {
                bool matched = false;
                for (unsigned format = 0;
                     format < decoder->import_format_count;
                     ++format) {
                    if (drm.layers[layer].drm_format ==
                        decoder->import_formats[format]) {
                        matched = true;
                        break;
                    }
                }
                if (!matched) {
                    acceptable = false;
                    break;
                }
            }
        }
    }
    if (status != VA_STATUS_SUCCESS || !acceptable) {
        if (status == VA_STATUS_SUCCESS) {
            for (uint32_t object = 0; object < drm.num_objects; ++object)
                close(drm.objects[object].fd);
            fprintf(stderr,
                    "VAAPI surface export formats are not accepted by EGL\n");
            return AVERROR(ENOSYS);
        }
        fprintf(stderr,
                "VAAPI surface export failed for surface %u: %s (%d)\n",
                (unsigned)surface,
                vaErrorStr(status),
                status);
        return AVERROR_EXTERNAL;
    }
    if (!decoder->first_surface_export_logged) {
        decoder->first_surface_export_logged = true;
        fprintf(stderr,
                "T1_VIDEO_STAGE first-surface-exported surface=%u "
                "objects=%u layers=%u mode=%s size=%ux%u\n",
                (unsigned)surface,
                drm.num_objects,
                drm.num_layers,
                export_mode,
                output_width,
                output_height);
    }

    if (drm.num_objects < 1 ||
        drm.num_objects > T1_VIDEO_MAX_OBJECTS ||
        drm.num_layers < 1 ||
        drm.num_layers > 2) {
        for (uint32_t object = 0; object < drm.num_objects; ++object)
            close(drm.objects[object].fd);
        return AVERROR(EINVAL);
    }
    for (uint32_t layer = 0; layer < drm.num_layers; ++layer) {
        if (drm.layers[layer].num_planes < 1 ||
            drm.layers[layer].num_planes > 4) {
            for (uint32_t object = 0; object < drm.num_objects; ++object)
                close(drm.objects[object].fd);
            return AVERROR(EINVAL);
        }
    }

    uint64_t frame_id = (uint64_t)++decoder->next_frame_id;
    int64_t timestamp = frame->best_effort_timestamp;
    if (timestamp == AV_NOPTS_VALUE)
        timestamp = frame->pts;
    if (timestamp == AV_NOPTS_VALUE)
        timestamp = decoder->stream_origin;

    int64_t relative = timestamp - decoder->stream_origin;
    if (relative < 0)
        relative = 0;
    int64_t pts_ns = av_rescale_q(
        relative,
        decoder->time_base,
        (AVRational){1, 1000000000});
    int64_t duration_ns = 0;
    if (frame->duration > 0) {
        duration_ns = av_rescale_q(
            frame->duration,
            decoder->time_base,
            (AVRational){1, 1000000000});
    }

    char json[T1_VIDEO_PACKET_LIMIT] = {0};
    size_t used = 0;
    if (t1_video_json_append(
            json,
            sizeof(json),
            &used,
            "{\"op\":\"frame\",\"frame\":%" PRIu64
            ",\"pts_ns\":%" PRId64
            ",\"duration_ns\":%" PRId64
            ",\"width\":%u,\"height\":%u,\"coded_width\":%d,"
            "\"coded_height\":%d,\"format\":\"drm_prime\"," 
            "\"export_mode\":\"%s\",\"gpu_scaled\":%s,\"bit_depth\":%d,"
            "\"source_rotation\":%u,\"rotation\":0,"
            "\"interlaced\":%s,\"top_field_first\":%s,"
            "\"color\":{\"primaries\":%d,\"transfer\":%d,\"space\":%d,"
            "\"range\":%d,\"chroma\":%d},\"objects\":[",
            frame_id,
            pts_ns,
            duration_ns,
            output_width,
            output_height,
            frame->width,
            frame->height,
            export_mode,
            surface != decoded_surface ? "true" : "false",
            t1_video_bit_depth(frame),
            decoder->source_rotation,
            (frame->flags & AV_FRAME_FLAG_INTERLACED) ? "true" : "false",
            (frame->flags & AV_FRAME_FLAG_TOP_FIELD_FIRST) ? "true" : "false",
            frame->color_primaries,
            frame->color_trc,
            frame->colorspace,
            frame->color_range,
            frame->chroma_location) < 0) {
        for (uint32_t object = 0; object < drm.num_objects; ++object)
            close(drm.objects[object].fd);
        return AVERROR(ENOSPC);
    }

    int fds[T1_VIDEO_MAX_OBJECTS] = {-1, -1, -1, -1};
    for (uint32_t object = 0; object < drm.num_objects; ++object) {
        if (object &&
            t1_video_json_append(json, sizeof(json), &used, ",") < 0)
            goto json_overflow;
        fds[object] = drm.objects[object].fd;
        if (t1_video_json_append(
                json,
                sizeof(json),
                &used,
                "{\"size\":%u,\"modifier\":%" PRIu64 "}",
                drm.objects[object].size,
                drm.objects[object].drm_format_modifier) < 0)
            goto json_overflow;
    }
    if (t1_video_json_append(
            json,
            sizeof(json),
            &used,
            "],\"layers\":[") < 0)
        goto json_overflow;

    for (uint32_t layer = 0; layer < drm.num_layers; ++layer) {
        if (layer &&
            t1_video_json_append(json, sizeof(json), &used, ",") < 0)
            goto json_overflow;
        unsigned layer_width = output_width;
        unsigned layer_height = output_height;
        t1_video_layer_size(
            frame,
            layer,
            drm.num_layers,
            output_width,
            output_height,
            &layer_width,
            &layer_height);
        if (t1_video_json_append(
                json,
                sizeof(json),
                &used,
                "{\"fourcc\":%u,\"width\":%u,\"height\":%u,\"planes\":[",
                drm.layers[layer].drm_format,
                layer_width,
                layer_height) < 0)
            goto json_overflow;

        for (uint32_t plane = 0;
             plane < drm.layers[layer].num_planes;
             ++plane) {
            if (plane &&
                t1_video_json_append(json, sizeof(json), &used, ",") < 0)
                goto json_overflow;
            if (t1_video_json_append(
                    json,
                    sizeof(json),
                    &used,
                    "{\"object\":%u,\"offset\":%u,\"pitch\":%u}",
                    drm.layers[layer].object_index[plane],
                    drm.layers[layer].offset[plane],
                    drm.layers[layer].pitch[plane]) < 0)
                goto json_overflow;
        }
        if (t1_video_json_append(
                json,
                sizeof(json),
                &used,
                "]}") < 0)
            goto json_overflow;
    }
    if (t1_video_json_append(
            json,
            sizeof(json),
            &used,
            "]}") < 0)
        goto json_overflow;

    slot->frame_id = frame_id;
    slot->decoded = frame;
    slot->fd_count = (unsigned)drm.num_objects;
    for (unsigned object = 0; object < T1_VIDEO_MAX_OBJECTS; ++object)
        slot->fds[object] = -1;
    memcpy(
        slot->fds,
        fds,
        sizeof(int) * drm.num_objects);
    decoder->in_flight++;

    if (t1_video_send_json(
            decoder,
            json,
            fds,
            (unsigned)drm.num_objects) < 0) {
        /*
         * The caller still owns frame when this operation fails.  Detach it
         * before releasing the mapped surface so the caller can free it once.
         */
        slot->decoded = NULL;
        t1_video_release_slot(decoder, slot_index);
        return AVERROR(EPIPE);
    }
    return 0;

json_overflow:
    for (uint32_t object = 0; object < drm.num_objects; ++object)
        close(drm.objects[object].fd);
    return AVERROR(ENOSPC);
}

static int
t1_video_receive_frames(struct t1_video_decoder *decoder)
{
    while (!decoder->stopped) {
        t1_video_control(decoder, false);
        AVFrame *frame = av_frame_alloc();
        if (!frame)
            return AVERROR(ENOMEM);

        int result = avcodec_receive_frame(decoder->codec, frame);
        if (result == AVERROR(EAGAIN) || result == AVERROR_EOF) {
            av_frame_free(&frame);
            return result;
        }
        if (result < 0) {
            av_frame_free(&frame);
            return result;
        }

        if (!decoder->first_frame_logged) {
            fprintf(stderr, "T1_VIDEO_STAGE first-frame-decoded\n");
            decoder->first_frame_logged = true;
        }

        result = t1_video_send_frame(decoder, frame);
        if (result < 0) {
            av_frame_free(&frame);
            return result;
        }
    }
    return AVERROR_EXIT;
}

static int
t1_video_decode(const char *path,
                 const char *device,
                 int socket_fd,
                 double start_seconds,
                 int requested_stream,
                 unsigned target_width,
                 unsigned target_height,
                 unsigned source_rotation,
                 const uint32_t *import_formats,
                 unsigned import_format_count)
{
    struct t1_video_decoder decoder = {
        .socket_fd = socket_fd,
        .video_stream = -1,
        .next_frame_id = 0,
        .vpp_config = VA_INVALID_ID,
        .vpp_context = VA_INVALID_ID,
        .target_width = target_width & ~1u,
        .target_height = target_height & ~1u,
        .source_rotation = source_rotation,
        .va_rotation = source_rotation == 90u
            ? VA_ROTATION_90
            : source_rotation == 180u
                ? VA_ROTATION_180
                : source_rotation == 270u
                    ? VA_ROTATION_270
                    : VA_ROTATION_NONE,
    };
    decoder.import_format_count =
        import_format_count > T1_VIDEO_MAX_IMPORT_FORMATS
            ? T1_VIDEO_MAX_IMPORT_FORMATS
            : import_format_count;
    if (decoder.import_format_count)
        memcpy(
            decoder.import_formats,
            import_formats,
            decoder.import_format_count * sizeof(decoder.import_formats[0]));
    for (unsigned index = 0; index < T1_VIDEO_MAX_IN_FLIGHT; ++index) {
        decoder.slots[index].output_surface = VA_INVALID_SURFACE;
        for (unsigned object = 0; object < T1_VIDEO_MAX_OBJECTS; ++object)
            decoder.slots[index].fds[object] = -1;
    }
    int result = 0;
    unsigned landlock_abi = 0;
    if (t1_video_install_file_landlock(path, &landlock_abi) < 0) {
        fprintf(
            stderr,
            "T1_VIDEO_STAGE sandbox-failed stage=landlock error=%s\n",
            strerror(errno));
        result = AVERROR(errno ? errno : EPERM);
        goto finish;
    }

    /*
     * NVIDIA's VA-API adapter initializes CUDA/NVDEC state with operations
     * which are deliberately unavailable after the decoder seccomp filter is
     * active.  Landlock is already active here, and no untrusted container
     * bytes are opened until after the device is ready and seccomp is applied.
     * This is the same security ordering used by the browser media worker.
     */
    result = av_hwdevice_ctx_create(
        &decoder.device,
        AV_HWDEVICE_TYPE_VAAPI,
        device,
        NULL,
        0);
    if (result < 0)
        goto finish;
    fprintf(stderr, "T1_VIDEO_STAGE va-device-created\n");

    if (t1_video_install_file_seccomp(landlock_abi) < 0) {
        fprintf(
            stderr,
            "T1_VIDEO_STAGE sandbox-failed stage=seccomp error=%s\n",
            strerror(errno));
        result = AVERROR(errno ? errno : EPERM);
        goto finish;
    }

    result = avformat_open_input(&decoder.format, path, NULL, NULL);
    if (result < 0)
        goto finish;
    fprintf(stderr, "T1_VIDEO_STAGE input-opened\n");

    result = avformat_find_stream_info(decoder.format, NULL);
    if (result < 0)
        goto finish;
    fprintf(stderr, "T1_VIDEO_STAGE stream-info-ready\n");

    const AVCodec *codec = NULL;
    if (requested_stream >= 0) {
        if ((unsigned)requested_stream >= decoder.format->nb_streams ||
            decoder.format->streams[requested_stream]->codecpar->codec_type !=
                AVMEDIA_TYPE_VIDEO) {
            result = AVERROR_STREAM_NOT_FOUND;
            goto finish;
        }
        decoder.video_stream = requested_stream;
        codec = avcodec_find_decoder(
            decoder.format->streams[requested_stream]->codecpar->codec_id);
        if (!codec) {
            result = AVERROR_DECODER_NOT_FOUND;
            goto finish;
        }
    } else {
        result = av_find_best_stream(
            decoder.format,
            AVMEDIA_TYPE_VIDEO,
            -1,
            -1,
            &codec,
            0);
        if (result < 0)
            goto finish;
        decoder.video_stream = result;
    }
    AVStream *stream = decoder.format->streams[decoder.video_stream];
    decoder.time_base = stream->time_base;
    decoder.stream_origin =
        stream->start_time == AV_NOPTS_VALUE ? 0 : stream->start_time;

    decoder.codec = avcodec_alloc_context3(codec);
    if (!decoder.codec) {
        result = AVERROR(ENOMEM);
        goto finish;
    }
    result = avcodec_parameters_to_context(
        decoder.codec,
        stream->codecpar);
    if (result < 0)
        goto finish;

    decoder.codec->hw_device_ctx = av_buffer_ref(decoder.device);
    if (!decoder.codec->hw_device_ctx) {
        result = AVERROR(ENOMEM);
        goto finish;
    }

    decoder.codec->get_format = t1_video_hardware_format;
    decoder.codec->thread_count = 1;

    fprintf(stderr, "T1_VIDEO_STAGE codec-open-begin\n");
    result = avcodec_open2(decoder.codec, codec, NULL);
    if (result < 0)
        goto finish;
    fprintf(stderr, "T1_VIDEO_STAGE codec-open-complete\n");

    if (start_seconds > 0.0) {
        int64_t target = av_rescale_q(
            (int64_t)(start_seconds * AV_TIME_BASE),
            AV_TIME_BASE_Q,
            stream->time_base);
        target += decoder.stream_origin;
        result = av_seek_frame(
            decoder.format,
            decoder.video_stream,
            target,
            AVSEEK_FLAG_BACKWARD);
        if (result < 0)
            goto finish;
        avcodec_flush_buffers(decoder.codec);
    }

    AVPacket *packet = av_packet_alloc();
    if (!packet) {
        result = AVERROR(ENOMEM);
        goto finish;
    }

    while (!decoder.stopped &&
           (result = av_read_frame(decoder.format, packet)) >= 0) {
        t1_video_control(&decoder, false);
        if (packet->stream_index != decoder.video_stream) {
            av_packet_unref(packet);
            continue;
        }

        /*
         * AVERROR(EAGAIN) means the decoder still owns output which must be
         * received before this same packet can be submitted.  Retrying the
         * packet is essential: unreferencing it here would silently discard
         * compressed video and create the intermittent missing-frame pattern
         * this transport is intended to eliminate.
         */
        for (;;) {
            if (!decoder.first_packet_logged) {
                fprintf(stderr, "T1_VIDEO_STAGE first-packet-submit\n");
                decoder.first_packet_logged = true;
            }
            result = avcodec_send_packet(decoder.codec, packet);
            if (result != AVERROR(EAGAIN))
                break;

            result = t1_video_receive_frames(&decoder);
            if (result != AVERROR(EAGAIN) && result != AVERROR_EOF)
                break;
        }
        av_packet_unref(packet);
        if (result < 0)
            break;

        result = t1_video_receive_frames(&decoder);
        if (result != AVERROR(EAGAIN) && result != AVERROR_EOF)
            break;
    }

    if (!decoder.stopped && result == AVERROR_EOF) {
        avcodec_send_packet(decoder.codec, NULL);
        while ((result = t1_video_receive_frames(&decoder)) == 0)
            ;
        if (result == AVERROR_EOF || result == AVERROR(EAGAIN))
            result = 0;
    }

    av_packet_free(&packet);
    if (!decoder.stopped && result >= 0) {
        t1_video_send_json(&decoder, "{\"op\":\"eof\"}", NULL, 0);

        /*
         * Exported DMA-BUFs remain owned by these AVFrames.  Keep the decoder
         * and its VA surfaces alive until the compositor has retired every
         * submitted frame, or until the parent explicitly stops playback.
         */
        while (!decoder.stopped && decoder.in_flight)
            t1_video_control(&decoder, true);
    }

finish:
    if (result < 0 && result != AVERROR_EXIT) {
        char detail[AV_ERROR_MAX_STRING_SIZE] = {0};
        av_strerror(result, detail, sizeof(detail));
        fprintf(stderr, "video decode failed: %s\n", detail);
    }
    t1_video_release_all(&decoder);
    t1_video_destroy_vpp_surfaces(&decoder);
    t1_video_destroy_vpp(&decoder);
    av_buffer_unref(&decoder.device);
    avcodec_free_context(&decoder.codec);
    avformat_close_input(&decoder.format);
    return result < 0 && result != AVERROR_EXIT ? 1 : 0;
}

static const char *
t1_video_argument(int argc, char **argv, const char *name)
{
    for (int index = 1; index + 1 < argc; ++index) {
        if (!strcmp(argv[index], name))
            return argv[index + 1];
    }
    return NULL;
}

static unsigned
t1_video_import_formats(const char *value, uint32_t *formats, unsigned capacity)
{
    if (!value || !*value || !formats || !capacity)
        return 0;
    char *copy = strdup(value);
    if (!copy)
        return 0;
    unsigned count = 0;
    char *save = NULL;
    for (char *part = strtok_r(copy, ",", &save);
         part && count < capacity;
         part = strtok_r(NULL, ",", &save)) {
        char *end = NULL;
        errno = 0;
        unsigned long parsed = strtoul(part, &end, 10);
        if (errno || !end || *end || parsed > UINT32_MAX) {
            count = 0;
            break;
        }
        formats[count++] = (uint32_t)parsed;
    }
    free(copy);
    return count;
}

int
main(int argc, char **argv)
{
    setvbuf(stderr, NULL, _IOLBF, 0);
    const char *sandbox_test =
        t1_video_argument(argc, argv, "--file-sandbox-self-test");
    if (sandbox_test) {
        unsigned landlock_abi = 0;
        if (t1_video_install_file_landlock(
                sandbox_test,
                &landlock_abi) < 0 ||
            t1_video_install_file_seccomp(landlock_abi) < 0)
            return 77;
        int allowed = open(
            sandbox_test,
            O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
        errno = 0;
        int forbidden = open(
            "/etc/passwd",
            O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
        int denied = errno;
        if (allowed < 0 || forbidden >= 0 ||
            (denied != EACCES && denied != EPERM)) {
            if (allowed >= 0)
                close(allowed);
            if (forbidden >= 0)
                close(forbidden);
            return 77;
        }
        close(allowed);
        puts(
            "T1 video file sandbox self-test passed "
            "input=read-only unrelated-files=denied");
        return 0;
    }
    const char *device = t1_video_argument(argc, argv, "--device");
    if (!device) {
        fprintf(stderr, "--device is required\n");
        return 64;
    }
    for (int index = 1; index < argc; ++index) {
        if (!strcmp(argv[index], "--probe"))
            return t1_video_probe(device);
    }

    const char *path = t1_video_argument(argc, argv, "--input");
    const char *socket_value =
        t1_video_argument(argc, argv, "--socket-fd");
    const char *start_value =
        t1_video_argument(argc, argv, "--start");
    const char *stream_value =
        t1_video_argument(argc, argv, "--stream-index");
    const char *width_value =
        t1_video_argument(argc, argv, "--output-width");
    const char *height_value =
        t1_video_argument(argc, argv, "--output-height");
    const char *rotation_value =
        t1_video_argument(argc, argv, "--rotation");
    const char *import_value =
        t1_video_argument(argc, argv, "--import-fourcc");
    if (!path || !socket_value) {
        fprintf(stderr, "--input and --socket-fd are required\n");
        return 64;
    }

    char *end = NULL;
    long socket_fd = strtol(socket_value, &end, 10);
    if (!end || *end || socket_fd < 0 || socket_fd > INT32_MAX) {
        fprintf(stderr, "invalid --socket-fd\n");
        return 64;
    }
    double start_seconds =
        start_value ? strtod(start_value, NULL) : 0.0;
    if (start_seconds < 0.0)
        start_seconds = 0.0;
    int stream_index = -1;
    if (stream_value) {
        end = NULL;
        long parsed = strtol(stream_value, &end, 10);
        if (!end || *end || parsed < 0 || parsed > INT32_MAX) {
            fprintf(stderr, "invalid --stream-index\n");
            return 64;
        }
        stream_index = (int)parsed;
    }
    unsigned output_width = 0;
    unsigned output_height = 0;
    if (width_value && height_value) {
        end = NULL;
        unsigned long parsed_width = strtoul(width_value, &end, 10);
        if (!end || *end || parsed_width < 2 || parsed_width > UINT16_MAX) {
            fprintf(stderr, "invalid --output-width\n");
            return 64;
        }
        end = NULL;
        unsigned long parsed_height = strtoul(height_value, &end, 10);
        if (!end || *end || parsed_height < 2 || parsed_height > UINT16_MAX) {
            fprintf(stderr, "invalid --output-height\n");
            return 64;
        }
        output_width = (unsigned)parsed_width;
        output_height = (unsigned)parsed_height;
    }
    unsigned source_rotation = 0;
    if (rotation_value) {
        end = NULL;
        unsigned long parsed_rotation = strtoul(rotation_value, &end, 10);
        if (!end || *end ||
            (parsed_rotation != 0 && parsed_rotation != 90 &&
             parsed_rotation != 180 && parsed_rotation != 270)) {
            fprintf(stderr, "invalid --rotation\n");
            return 64;
        }
        source_rotation = (unsigned)parsed_rotation;
    }
    uint32_t import_formats[T1_VIDEO_MAX_IMPORT_FORMATS] = {0};
    unsigned import_format_count = t1_video_import_formats(
        import_value,
        import_formats,
        T1_VIDEO_MAX_IMPORT_FORMATS);
    if (import_value && *import_value && !import_format_count) {
        fprintf(stderr, "invalid --import-fourcc\n");
        return 64;
    }

    return t1_video_decode(
        path,
        device,
        (int)socket_fd,
        start_seconds,
        stream_index,
        output_width,
        output_height,
        source_rotation,
        import_formats,
        import_format_count);
}
