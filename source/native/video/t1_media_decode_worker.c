#define _GNU_SOURCE

#include "t1_media_decode_transport.h"
#include "t1_media_decode_privilege.h"
#include "t1_media_decode_sandbox.h"
#include "t1_media_decode_watchdog.h"

#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <linux/memfd.h>
#include <poll.h>
#include <signal.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/random.h>
#include <sys/mman.h>
#include <sys/prctl.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <time.h>
#include <unistd.h>

#include <libavcodec/avcodec.h>
#include <libavutil/avutil.h>
#include <libavutil/buffer.h>
#include <libavutil/hwcontext.h>
#include <libavutil/hwcontext_vaapi.h>
#include <libavutil/pixdesc.h>
#include <va/va.h>
#include <va/va_drmcommon.h>

#define T1_MEDIA_HANDSHAKE_TIMEOUT_MS 60000
#define T1_MEDIA_RELEASE_FENCE_TIMEOUT_MS 5000
#define T1_MEDIA_ABSOLUTE_DIMENSION 16384u
#define T1_MEDIA_CONSERVATIVE_MAX_DIMENSION 8192u

struct t1_media_frame_slot {
    uint64_t frame_id;
    uint64_t generation;
    AVFrame *frame;
    int fds[T1_MEDIA_MAX_FRAME_OBJECTS];
    unsigned fd_count;
};

struct t1_media_worker {
    int socket_fd;
    int watchdog_fd;
    const char *device_path;
    struct t1_media_capabilities capabilities;
    uint64_t session;
    uint64_t last_request;
    uint64_t generation;
    uint64_t next_frame_id;
    AVBufferRef *device;
    AVCodecContext *codec;
    struct t1_media_frame_slot slots[T1_MEDIA_MAX_IN_FLIGHT_FRAMES];
    uint32_t import_fourcc[T1_MEDIA_MAX_IMPORT_FOURCC];
    unsigned import_fourcc_count;
    uint32_t configured_visible_x;
    uint32_t configured_visible_y;
    uint32_t configured_visible_width;
    uint32_t configured_visible_height;
    uint32_t configured_minimum_width;
    uint32_t configured_minimum_height;
    uint32_t configured_maximum_width;
    uint32_t configured_maximum_height;
    uint32_t configured_bit_depths;
    unsigned in_flight;
    bool created;
    bool drained;
    bool stopping;
    bool debug;
    bool watchdog_active;
    bool watchdog_waiting;
    bool reset_interrupted;
    bool linear_memory_output;
    bool first_surface_export_logged;
    uint16_t watchdog_operation;
    uint64_t watchdog_request;
    uint64_t watchdog_generation;
};

static volatile sig_atomic_t t1_media_worker_stopping = 0;
static volatile sig_atomic_t t1_media_worker_socket = -1;

static void
t1_media_worker_signal(int signal_number)
{
    (void)signal_number;
    t1_media_worker_stopping = 1;
    if (t1_media_worker_socket >= 0) {
        close((int)t1_media_worker_socket);
        t1_media_worker_socket = -1;
    }
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

static int
t1_media_parse_descriptor(const char *value)
{
    if (!value || !*value)
        return -1;
    errno = 0;
    char *end = NULL;
    long parsed = strtol(value, &end, 10);
    if (errno || !end || *end || parsed < 0 || parsed > INT32_MAX)
        return -1;
    return (int)parsed;
}

static unsigned
t1_media_parse_sessions(const char *value)
{
    if (!value || !*value)
        return 8;
    errno = 0;
    char *end = NULL;
    unsigned long parsed = strtoul(value, &end, 10);
    if (errno || !end || *end || parsed < 1 || parsed > 16)
        return 0;
    return (unsigned)parsed;
}

static int
t1_media_validate_watchdog_descriptor(int descriptor)
{
    struct stat status;
    int type = 0;
    socklen_t type_size = sizeof(type);
    int flags = fcntl(descriptor, F_GETFL);
    if (descriptor <= STDERR_FILENO ||
        fstat(descriptor, &status) < 0 ||
        !S_ISSOCK(status.st_mode) ||
        getsockopt(
            descriptor,
            SOL_SOCKET,
            SO_TYPE,
            &type,
            &type_size) < 0 ||
        type_size != sizeof(type) ||
        type != SOCK_SEQPACKET ||
        flags < 0 ||
        !(flags & O_NONBLOCK)) {
        errno = EINVAL;
        return -1;
    }
    return 0;
}

static int
t1_media_watchdog_notify(
    struct t1_media_worker *worker,
    uint16_t event,
    uint16_t operation,
    uint64_t request,
    uint64_t generation)
{
    struct t1_media_watchdog_message message = {
        .magic = T1_MEDIA_WATCHDOG_MAGIC,
        .format = T1_MEDIA_WATCHDOG_FORMAT,
        .event = event,
        .operation = operation,
        .request = request,
        .generation = generation,
    };
    ssize_t sent;
    do {
        sent = send(
            worker->watchdog_fd,
            &message,
            sizeof(message),
            MSG_DONTWAIT | MSG_NOSIGNAL);
    } while (sent < 0 && errno == EINTR);
    if (sent != (ssize_t)sizeof(message)) {
        if (sent >= 0)
            errno = EIO;
        return -1;
    }
    return 0;
}

static int
t1_media_watchdog_begin(
    struct t1_media_worker *worker,
    uint16_t operation,
    uint64_t request,
    uint64_t generation)
{
    if (worker->watchdog_active) {
        errno = EPROTO;
        return -1;
    }
    if (t1_media_watchdog_notify(
            worker,
            T1_MEDIA_WATCHDOG_BEGIN,
            operation,
            request,
            generation) < 0)
        return -1;
    worker->watchdog_active = true;
    worker->watchdog_waiting = false;
    worker->watchdog_operation = operation;
    worker->watchdog_request = request;
    worker->watchdog_generation = generation;
    return 0;
}

static int
t1_media_watchdog_complete(
    struct t1_media_worker *worker,
    uint16_t operation,
    uint64_t request,
    uint64_t generation)
{
    if (!worker->watchdog_active ||
        worker->watchdog_waiting ||
        worker->watchdog_operation != operation ||
        worker->watchdog_request != request ||
        worker->watchdog_generation != generation) {
        errno = EPROTO;
        return -1;
    }
    if (t1_media_watchdog_notify(
            worker,
            T1_MEDIA_WATCHDOG_COMPLETE,
            operation,
            request,
            generation) < 0)
        return -1;
    worker->watchdog_active = false;
    worker->watchdog_operation = T1_MEDIA_WATCHDOG_NONE;
    worker->watchdog_request = 0;
    worker->watchdog_generation = 0;
    return 0;
}

static int
t1_media_watchdog_wait(
    struct t1_media_worker *worker)
{
    if (!worker->watchdog_active ||
        worker->watchdog_waiting) {
        errno = EPROTO;
        return -1;
    }
    if (t1_media_watchdog_notify(
            worker,
            T1_MEDIA_WATCHDOG_WAIT,
            worker->watchdog_operation,
            worker->watchdog_request,
            worker->watchdog_generation) < 0)
        return -1;
    worker->watchdog_waiting = true;
    return 0;
}

static int
t1_media_watchdog_resume(
    struct t1_media_worker *worker)
{
    if (!worker->watchdog_active ||
        !worker->watchdog_waiting) {
        errno = EPROTO;
        return -1;
    }
    if (t1_media_watchdog_notify(
            worker,
            T1_MEDIA_WATCHDOG_RESUME,
            worker->watchdog_operation,
            worker->watchdog_request,
            worker->watchdog_generation) < 0)
        return -1;
    worker->watchdog_waiting = false;
    return 0;
}

static uint16_t
t1_media_watchdog_operation(uint16_t message_type)
{
    switch (message_type) {
    case T1_MEDIA_CREATE:
        return T1_MEDIA_WATCHDOG_CREATE;
    case T1_MEDIA_DECODE:
        return T1_MEDIA_WATCHDOG_DECODE;
    case T1_MEDIA_FLUSH:
        return T1_MEDIA_WATCHDOG_FLUSH;
    case T1_MEDIA_RESET:
        return T1_MEDIA_WATCHDOG_RESET;
    case T1_MEDIA_RELEASE:
        return T1_MEDIA_WATCHDOG_RELEASE;
    case T1_MEDIA_DESTROY:
        return T1_MEDIA_WATCHDOG_DESTROY;
    default:
        return T1_MEDIA_WATCHDOG_NONE;
    }
}

static int
t1_media_parse_identity(const char *value, unsigned long maximum,
                        unsigned long *output)
{
    if (!value || !*value)
        return -1;
    errno = 0;
    char *end = NULL;
    unsigned long parsed = strtoul(value, &end, 10);
    if (errno || !end || *end || parsed == 0 || parsed > maximum)
        return -1;
    *output = parsed;
    return 0;
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

static enum AVPixelFormat
t1_media_hardware_format(AVCodecContext *context,
                         const enum AVPixelFormat *formats)
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

static uint32_t
t1_media_rt_bit_depths(uint32_t format)
{
    uint32_t result = 0;
    if (format & VA_RT_FORMAT_YUV420)
        result |= T1_MEDIA_BIT_DEPTH_8;
#ifdef VA_RT_FORMAT_YUV420_10
    if (format & VA_RT_FORMAT_YUV420_10)
        result |= T1_MEDIA_BIT_DEPTH_10;
#endif
    return result;
}

static uint32_t
t1_media_browser_profile_bit_depths(uint32_t profile)
{
    switch (profile) {
    case T1_MEDIA_PROFILE_H264_BASELINE:
    case T1_MEDIA_PROFILE_H264_MAIN:
    case T1_MEDIA_PROFILE_H264_HIGH:
    case T1_MEDIA_PROFILE_VP8_ANY:
    case T1_MEDIA_PROFILE_VP9_0:
    case T1_MEDIA_PROFILE_HEVC_MAIN:
        return T1_MEDIA_BIT_DEPTH_8;
    case T1_MEDIA_PROFILE_VP9_2:
    case T1_MEDIA_PROFILE_HEVC_MAIN10:
        return T1_MEDIA_BIT_DEPTH_10;
    case T1_MEDIA_PROFILE_AV1_MAIN:
        return T1_MEDIA_BIT_DEPTH_8 | T1_MEDIA_BIT_DEPTH_10;
    default:
        return 0;
    }
}

static uint32_t
t1_media_output_formats_for_bit_depths(uint32_t bit_depths)
{
    uint32_t result = 0;
    if (bit_depths & T1_MEDIA_BIT_DEPTH_8)
        result |= T1_MEDIA_OUTPUT_NV12;
    if (bit_depths & T1_MEDIA_BIT_DEPTH_10)
        result |= T1_MEDIA_OUTPUT_P010;
    return result;
}

static bool
t1_media_separate_import_fourcc(uint32_t fourcc);

static int
t1_media_capability_contract_self_test(void)
{
    if (t1_media_browser_profile_bit_depths(
            T1_MEDIA_PROFILE_H264_HIGH) !=
            T1_MEDIA_BIT_DEPTH_8 ||
        t1_media_browser_profile_bit_depths(
            T1_MEDIA_PROFILE_VP9_1) != 0 ||
        t1_media_browser_profile_bit_depths(
            T1_MEDIA_PROFILE_VP9_2) !=
            T1_MEDIA_BIT_DEPTH_10 ||
        t1_media_browser_profile_bit_depths(
            T1_MEDIA_PROFILE_AV1_MAIN) !=
            (T1_MEDIA_BIT_DEPTH_8 | T1_MEDIA_BIT_DEPTH_10) ||
        t1_media_browser_profile_bit_depths(
            T1_MEDIA_PROFILE_MPEG2_MAIN) != 0 ||
        t1_media_output_formats_for_bit_depths(
            T1_MEDIA_BIT_DEPTH_8) != T1_MEDIA_OUTPUT_NV12 ||
        t1_media_output_formats_for_bit_depths(
            T1_MEDIA_BIT_DEPTH_10) != T1_MEDIA_OUTPUT_P010 ||
        t1_media_output_formats_for_bit_depths(
            T1_MEDIA_BIT_DEPTH_8 | T1_MEDIA_BIT_DEPTH_10) !=
            (T1_MEDIA_OUTPUT_NV12 | T1_MEDIA_OUTPUT_P010) ||
        !t1_media_separate_import_fourcc(T1_MEDIA_DRM_FORMAT_R8) ||
        !t1_media_separate_import_fourcc(T1_MEDIA_DRM_FORMAT_GR1616) ||
        t1_media_separate_import_fourcc(T1_MEDIA_DRM_FORMAT_NV12) ||
        t1_media_separate_import_fourcc(T1_MEDIA_DRM_FORMAT_P010))
        return 1;
    puts(
        "T1MD capability contract self-test passed "
        "chroma=420 formats=NV12/P010 av1_depths=8/10");
    return 0;
}

static bool
t1_media_map_va_profile(VAProfile source,
                        uint32_t *codec,
                        uint32_t *profile)
{
    switch (source) {
    case VAProfileH264ConstrainedBaseline:
        *codec = T1_MEDIA_CODEC_H264;
        *profile = T1_MEDIA_PROFILE_H264_BASELINE;
        return true;
    case VAProfileH264Main:
        *codec = T1_MEDIA_CODEC_H264;
        *profile = T1_MEDIA_PROFILE_H264_MAIN;
        return true;
    case VAProfileH264High:
        *codec = T1_MEDIA_CODEC_H264;
        *profile = T1_MEDIA_PROFILE_H264_HIGH;
        return true;
    case VAProfileVP8Version0_3:
        *codec = T1_MEDIA_CODEC_VP8;
        *profile = T1_MEDIA_PROFILE_VP8_ANY;
        return true;
    case VAProfileVP9Profile0:
        *codec = T1_MEDIA_CODEC_VP9;
        *profile = T1_MEDIA_PROFILE_VP9_0;
        return true;
    case VAProfileVP9Profile2:
        *codec = T1_MEDIA_CODEC_VP9;
        *profile = T1_MEDIA_PROFILE_VP9_2;
        return true;
    case VAProfileHEVCMain:
        *codec = T1_MEDIA_CODEC_HEVC;
        *profile = T1_MEDIA_PROFILE_HEVC_MAIN;
        return true;
    case VAProfileHEVCMain10:
        *codec = T1_MEDIA_CODEC_HEVC;
        *profile = T1_MEDIA_PROFILE_HEVC_MAIN10;
        return true;
    case VAProfileAV1Profile0:
        *codec = T1_MEDIA_CODEC_AV1;
        *profile = T1_MEDIA_PROFILE_AV1_MAIN;
        return true;
    default:
        return false;
    }
}

static int
t1_media_collect_capabilities(const char *device_path,
                              unsigned maximum_sessions,
                              struct t1_media_capabilities *capabilities)
{
    memset(capabilities, 0, sizeof(*capabilities));
    capabilities->features =
        T1_MEDIA_FEATURE_DMABUF |
        T1_MEDIA_FEATURE_DRM_MODIFIERS |
        T1_MEDIA_FEATURE_RESET |
        T1_MEDIA_FEATURE_RELEASE_FENCE |
        T1_MEDIA_FEATURE_PER_SESSION_WORKER |
        T1_MEDIA_FEATURE_SEALED_INPUT |
        T1_MEDIA_FEATURE_BACKPRESSURE |
        T1_MEDIA_FEATURE_LINEAR_MEMORY_OUTPUT;
    capabilities->maximum_sessions = maximum_sessions;
    capabilities->maximum_decode_requests = T1_MEDIA_MAX_DECODE_REQUESTS;
    capabilities->maximum_in_flight_frames =
        T1_MEDIA_MAX_IN_FLIGHT_FRAMES;
    capabilities->maximum_encoded_bytes = T1_MEDIA_MAX_ENCODED_BYTES;
    capabilities->maximum_extradata_bytes =
        T1_MEDIA_MAX_EXTRADATA_BYTES;

    AVBufferRef *device = NULL;
    int result = av_hwdevice_ctx_create(
        &device,
        AV_HWDEVICE_TYPE_VAAPI,
        device_path,
        NULL,
        0);
    if (result < 0)
        return result;

    AVHWDeviceContext *hardware = (AVHWDeviceContext *)device->data;
    AVVAAPIDeviceContext *vaapi =
        (AVVAAPIDeviceContext *)hardware->hwctx;
    VADisplay display = vaapi->display;
    const char *vendor = vaQueryVendorString(display);
    if (vendor)
        snprintf(
            capabilities->vendor,
            sizeof(capabilities->vendor),
            "%s",
            vendor);

    int maximum = vaMaxNumProfiles(display);
    if (maximum <= 0) {
        av_buffer_unref(&device);
        return AVERROR(ENODEV);
    }
    VAProfile *profiles = calloc((size_t)maximum, sizeof(*profiles));
    if (!profiles) {
        av_buffer_unref(&device);
        return AVERROR(ENOMEM);
    }
    int profile_count = 0;
    VAStatus status =
        vaQueryConfigProfiles(display, profiles, &profile_count);
    if (status != VA_STATUS_SUCCESS) {
        free(profiles);
        av_buffer_unref(&device);
        return AVERROR_EXTERNAL;
    }

    for (int index = 0;
         index < profile_count &&
         capabilities->profile_count < T1_MEDIA_MAX_PROFILES;
         ++index) {
        uint32_t codec = 0;
        uint32_t profile = 0;
        if (!t1_media_map_va_profile(
                profiles[index],
                &codec,
                &profile))
            continue;

        VAEntrypoint entrypoints[16] = {0};
        int entrypoint_count = 0;
        status = vaQueryConfigEntrypoints(
            display,
            profiles[index],
            entrypoints,
            &entrypoint_count);
        if (status != VA_STATUS_SUCCESS)
            continue;
        bool decode = false;
        for (int entry = 0; entry < entrypoint_count; ++entry) {
            if (entrypoints[entry] == VAEntrypointVLD) {
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
        status = vaGetConfigAttributes(
            display,
            profiles[index],
            VAEntrypointVLD,
            attributes,
            3);
        if (status != VA_STATUS_SUCCESS)
            continue;

        uint32_t rt_format =
            attributes[0].value == VA_ATTRIB_NOT_SUPPORTED
                ? 0
                : attributes[0].value;
        struct t1_media_capability_profile *destination =
            &capabilities->profiles[capabilities->profile_count];
        destination->codec = codec;
        destination->profile = profile;
        destination->bit_depths =
            t1_media_rt_bit_depths(rt_format) &
            t1_media_browser_profile_bit_depths(profile);
        destination->output_formats =
            t1_media_output_formats_for_bit_depths(
                destination->bit_depths);
        destination->minimum_width = 16;
        destination->minimum_height = 16;
        destination->maximum_width =
            attributes[1].value == VA_ATTRIB_NOT_SUPPORTED ||
            attributes[1].value == 0
                ? T1_MEDIA_CONSERVATIVE_MAX_DIMENSION
                : attributes[1].value >
                        T1_MEDIA_ABSOLUTE_DIMENSION
                    ? T1_MEDIA_ABSOLUTE_DIMENSION
                    : attributes[1].value;
        destination->maximum_height =
            attributes[2].value == VA_ATTRIB_NOT_SUPPORTED ||
            attributes[2].value == 0
                ? T1_MEDIA_CONSERVATIVE_MAX_DIMENSION
                : attributes[2].value >
                        T1_MEDIA_ABSOLUTE_DIMENSION
                    ? T1_MEDIA_ABSOLUTE_DIMENSION
                    : attributes[2].value;
        if (destination->bit_depths &&
            destination->output_formats)
            capabilities->profile_count++;
    }

    free(profiles);
    av_buffer_unref(&device);
    return capabilities->profile_count ? 0 : AVERROR(ENODEV);
}

static int
t1_media_write_all(int descriptor, const void *data, size_t size)
{
    const unsigned char *cursor = data;
    while (size) {
        ssize_t written = write(descriptor, cursor, size);
        if (written < 0) {
            if (errno == EINTR)
                continue;
            return -1;
        }
        if (written == 0) {
            errno = EIO;
            return -1;
        }
        cursor += (size_t)written;
        size -= (size_t)written;
    }
    return 0;
}

static int
t1_media_read_all(int descriptor, void *data, size_t size)
{
    unsigned char *cursor = data;
    off_t offset = 0;
    while (size) {
        ssize_t received = pread(
            descriptor,
            cursor,
            size,
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
        size -= (size_t)received;
        offset += received;
    }
    return 0;
}

static int
t1_media_probe_main(const char *device_path,
                    unsigned maximum_sessions,
                    int output_fd,
                    unsigned landlock_abi,
                    bool debug)
{
    struct t1_media_capabilities capabilities;
    int result = t1_media_collect_capabilities(
        device_path,
        maximum_sessions,
        &capabilities);
    if (t1_media_install_worker_seccomp() < 0) {
        fprintf(
            stderr,
            "T1_MEDIA_WORKER sandbox-failed stage=seccomp "
            "error=%s\n",
            strerror(errno));
        return 77;
    }
    if (debug) {
        fprintf(
            stderr,
            "T1_MEDIA_WORKER sandbox=ready landlock_abi=%u "
            "landlock_fs=all-through-ioctl-dev "
            "seccomp=filter seccomp_tsync=1 "
            "worker_uid=%lu worker_gid=%lu "
            "rlimit_core=%llu rlimit_fsize=%llu "
            "rlimit_nofile=%llu rlimit_nproc=%llu\n",
            landlock_abi,
            (unsigned long)geteuid(),
            (unsigned long)getegid(),
            T1_MEDIA_WORKER_RLIMIT_CORE,
            T1_MEDIA_WORKER_RLIMIT_FSIZE,
            T1_MEDIA_WORKER_RLIMIT_NOFILE,
            T1_MEDIA_WORKER_RLIMIT_NPROC);
    }
    if (result < 0) {
        char detail[AV_ERROR_MAX_STRING_SIZE] = {0};
        av_strerror(result, detail, sizeof(detail));
        fprintf(
            stderr,
            "T1_MEDIA_WORKER probe-failed device=%s error=%s\n",
            device_path,
            detail);
        return 69;
    }
    if (output_fd >= 0) {
        const struct t1_media_sandbox_report sandbox = {
            .format = T1_MEDIA_SANDBOX_REPORT_FORMAT,
            .landlock_abi = landlock_abi,
            .flags = T1_MEDIA_SANDBOX_REQUIRED_FLAGS,
            .rlimit_fsize =
                T1_MEDIA_WORKER_RLIMIT_FSIZE,
            .rlimit_nofile =
                T1_MEDIA_WORKER_RLIMIT_NOFILE,
            .rlimit_nproc =
                T1_MEDIA_WORKER_RLIMIT_NPROC,
            .rlimit_core =
                T1_MEDIA_WORKER_RLIMIT_CORE,
        };
        if (t1_media_write_all(
                output_fd,
                &capabilities,
                sizeof(capabilities)) < 0 ||
            t1_media_write_all(
                output_fd,
                &sandbox,
                sizeof(sandbox)) < 0) {
            fprintf(stderr, "T1_MEDIA_WORKER probe-write-failed: %s\n",
                    strerror(errno));
            return 74;
        }
    } else {
        printf(
            "{\"format\":1,\"protocol\":\"T1MD\","
            "\"protocol_version\":%u,\"device\":\"%s\","
            "\"vendor\":\"%s\",\"profiles\":%u}\n",
            T1_MEDIA_PROTOCOL_VERSION,
            device_path,
            capabilities.vendor,
            capabilities.profile_count);
    }
    return 0;
}

static uint64_t
t1_media_random_session(void)
{
    uint64_t value = 0;
    ssize_t received;
    do {
        received = getrandom(&value, sizeof(value), 0);
    } while (received < 0 && errno == EINTR);
    if (received != (ssize_t)sizeof(value) || value == 0) {
        struct timespec now = {0};
        clock_gettime(CLOCK_MONOTONIC, &now);
        value =
            ((uint64_t)(uint32_t)getpid() << 32) ^
            (uint64_t)now.tv_nsec ^
            ((uint64_t)now.tv_sec << 1);
        if (!value)
            value = 1;
    }
    return value;
}

static const struct t1_media_capability_profile *
t1_media_find_capability(const struct t1_media_capabilities *capabilities,
                         uint32_t codec,
                         uint32_t profile)
{
    unsigned count = capabilities->profile_count;
    if (count > T1_MEDIA_MAX_PROFILES)
        count = T1_MEDIA_MAX_PROFILES;
    for (unsigned index = 0; index < count; ++index) {
        if (capabilities->profiles[index].codec == codec &&
            capabilities->profiles[index].profile == profile)
            return &capabilities->profiles[index];
    }
    return NULL;
}

static enum AVCodecID
t1_media_codec_id(uint32_t codec)
{
    switch (codec) {
    case T1_MEDIA_CODEC_H264: return AV_CODEC_ID_H264;
    case T1_MEDIA_CODEC_VP8: return AV_CODEC_ID_VP8;
    case T1_MEDIA_CODEC_VP9: return AV_CODEC_ID_VP9;
    case T1_MEDIA_CODEC_HEVC: return AV_CODEC_ID_HEVC;
    case T1_MEDIA_CODEC_AV1: return AV_CODEC_ID_AV1;
    case T1_MEDIA_CODEC_MPEG2: return AV_CODEC_ID_MPEG2VIDEO;
    default: return AV_CODEC_ID_NONE;
    }
}

static int
t1_media_av_profile(uint32_t profile)
{
    switch (profile) {
    case T1_MEDIA_PROFILE_H264_BASELINE:
        return AV_PROFILE_H264_CONSTRAINED_BASELINE;
    case T1_MEDIA_PROFILE_H264_MAIN:
        return AV_PROFILE_H264_MAIN;
    case T1_MEDIA_PROFILE_H264_HIGH:
        return AV_PROFILE_H264_HIGH;
    case T1_MEDIA_PROFILE_VP8_ANY:
        return AV_PROFILE_UNKNOWN;
    case T1_MEDIA_PROFILE_VP9_0:
        return AV_PROFILE_VP9_0;
    case T1_MEDIA_PROFILE_VP9_1:
        return AV_PROFILE_VP9_1;
    case T1_MEDIA_PROFILE_VP9_2:
        return AV_PROFILE_VP9_2;
    case T1_MEDIA_PROFILE_VP9_3:
        return AV_PROFILE_VP9_3;
    case T1_MEDIA_PROFILE_HEVC_MAIN:
        return AV_PROFILE_HEVC_MAIN;
    case T1_MEDIA_PROFILE_HEVC_MAIN10:
        return AV_PROFILE_HEVC_MAIN_10;
    case T1_MEDIA_PROFILE_AV1_MAIN:
        return AV_PROFILE_AV1_MAIN;
    case T1_MEDIA_PROFILE_MPEG2_SIMPLE:
        return AV_PROFILE_MPEG2_SIMPLE;
    case T1_MEDIA_PROFILE_MPEG2_MAIN:
        return AV_PROFILE_MPEG2_MAIN;
    default:
        return AV_PROFILE_UNKNOWN;
    }
}

static void
t1_media_release_slot(struct t1_media_worker *worker, unsigned index)
{
    struct t1_media_frame_slot *slot = &worker->slots[index];
    if (!slot->frame_id)
        return;
    for (unsigned object = 0; object < slot->fd_count; ++object) {
        if (slot->fds[object] >= 0)
            close(slot->fds[object]);
        slot->fds[object] = -1;
    }
    slot->fd_count = 0;
    av_frame_free(&slot->frame);
    slot->frame_id = 0;
    slot->generation = 0;
    if (worker->in_flight)
        worker->in_flight--;
}

static void
t1_media_release_all(struct t1_media_worker *worker)
{
    for (unsigned index = 0;
         index < T1_MEDIA_MAX_IN_FLIGHT_FRAMES;
         ++index)
        t1_media_release_slot(worker, index);
}

static void
t1_media_close_decoder(struct t1_media_worker *worker)
{
    t1_media_release_all(worker);
    avcodec_free_context(&worker->codec);
    worker->created = false;
    worker->drained = false;
    worker->import_fourcc_count = 0;
    worker->configured_visible_x = 0;
    worker->configured_visible_y = 0;
    worker->configured_visible_width = 0;
    worker->configured_visible_height = 0;
    worker->configured_minimum_width = 0;
    worker->configured_minimum_height = 0;
    worker->configured_maximum_width = 0;
    worker->configured_maximum_height = 0;
    worker->configured_bit_depths = 0;
    worker->first_surface_export_logged = false;
}

static bool
t1_media_create_imports_fourcc(
    const struct t1_media_create *configuration,
    uint32_t fourcc)
{
    for (uint32_t index = 0;
         index < configuration->import_fourcc_count;
         ++index) {
        if (configuration->import_fourcc[index] == fourcc)
            return true;
    }
    return false;
}

static bool
t1_media_separate_import_fourcc(uint32_t fourcc)
{
    switch (fourcc) {
    case T1_MEDIA_DRM_FORMAT_R8:
    case T1_MEDIA_DRM_FORMAT_R16:
    case T1_MEDIA_DRM_FORMAT_RG88:
    case T1_MEDIA_DRM_FORMAT_GR88:
    case T1_MEDIA_DRM_FORMAT_RG1616:
    case T1_MEDIA_DRM_FORMAT_GR1616:
        return true;
    default:
        return false;
    }
}

static bool
t1_media_create_imports_separate_depth(
    const struct t1_media_create *configuration,
    uint32_t bit_depth)
{
    if (bit_depth == 8)
        return t1_media_create_imports_fourcc(
                   configuration,
                   T1_MEDIA_DRM_FORMAT_R8) &&
            (t1_media_create_imports_fourcc(
                 configuration,
                 T1_MEDIA_DRM_FORMAT_RG88) ||
             t1_media_create_imports_fourcc(
                 configuration,
                 T1_MEDIA_DRM_FORMAT_GR88));
    if (bit_depth == 10)
        return t1_media_create_imports_fourcc(
                   configuration,
                   T1_MEDIA_DRM_FORMAT_R16) &&
            (t1_media_create_imports_fourcc(
                 configuration,
                 T1_MEDIA_DRM_FORMAT_RG1616) ||
             t1_media_create_imports_fourcc(
                 configuration,
                 T1_MEDIA_DRM_FORMAT_GR1616));
    return false;
}

static uint32_t
t1_media_validate_create(
    const struct t1_media_worker *worker,
    const struct t1_media_create *configuration,
    size_t payload_size)
{
    if (payload_size != sizeof(*configuration) +
            configuration->extradata_size ||
        configuration->extradata_size >
            T1_MEDIA_MAX_EXTRADATA_BYTES ||
        configuration->import_fourcc_count == 0 ||
        configuration->import_fourcc_count >
            T1_MEDIA_MAX_IMPORT_FOURCC ||
        configuration->coded_width == 0 ||
        configuration->coded_height == 0 ||
        configuration->coded_width > T1_MEDIA_ABSOLUTE_DIMENSION ||
        configuration->coded_height > T1_MEDIA_ABSOLUTE_DIMENSION ||
        configuration->visible_width == 0 ||
        configuration->visible_height == 0 ||
        configuration->visible_x > configuration->coded_width ||
        configuration->visible_y > configuration->coded_height ||
        configuration->visible_width >
            configuration->coded_width - configuration->visible_x ||
        configuration->visible_height >
            configuration->coded_height - configuration->visible_y ||
        (configuration->bit_depth != 0 &&
         configuration->bit_depth != 8 &&
         configuration->bit_depth != 10) ||
        configuration->chroma_subsampling != T1_MEDIA_CHROMA_420 ||
        configuration->color_primaries > 255 ||
        configuration->color_transfer > 255 ||
        configuration->color_matrix > 255 ||
        configuration->color_range > T1_MEDIA_COLOR_RANGE_FULL ||
        configuration->flags &
            ~(T1_MEDIA_CREATE_LOW_DELAY |
              T1_MEDIA_CREATE_ENCRYPTED))
        return T1_MEDIA_STATUS_INVALID_MESSAGE;
    for (uint32_t index = 0;
         index < configuration->import_fourcc_count;
         ++index) {
        if (!t1_media_separate_import_fourcc(
                configuration->import_fourcc[index]))
            return T1_MEDIA_STATUS_INVALID_MESSAGE;
        for (uint32_t previous = 0; previous < index; ++previous) {
            if (configuration->import_fourcc[previous] ==
                configuration->import_fourcc[index])
                return T1_MEDIA_STATUS_INVALID_MESSAGE;
        }
    }
    if (configuration->flags & T1_MEDIA_CREATE_ENCRYPTED)
        return T1_MEDIA_STATUS_UNSUPPORTED_CONFIGURATION;
    if (configuration->bit_depth == 0 &&
        (configuration->codec != T1_MEDIA_CODEC_AV1 ||
         configuration->profile != T1_MEDIA_PROFILE_AV1_MAIN))
        return T1_MEDIA_STATUS_UNSUPPORTED_CONFIGURATION;

    const struct t1_media_capability_profile *capability =
        t1_media_find_capability(
            &worker->capabilities,
            configuration->codec,
            configuration->profile);
    if (!capability)
        return T1_MEDIA_STATUS_UNSUPPORTED_PROFILE;
    uint32_t depth_flags =
        configuration->bit_depth == 8
            ? T1_MEDIA_BIT_DEPTH_8
            : configuration->bit_depth == 10
                ? T1_MEDIA_BIT_DEPTH_10
                : capability->bit_depths &
                    (T1_MEDIA_BIT_DEPTH_8 |
                     T1_MEDIA_BIT_DEPTH_10);
    if (!depth_flags ||
        (depth_flags & ~capability->bit_depths) != 0 ||
        ((depth_flags & T1_MEDIA_BIT_DEPTH_8) &&
         (!(capability->output_formats & T1_MEDIA_OUTPUT_NV12) ||
          !t1_media_create_imports_separate_depth(
              configuration,
              8))) ||
        ((depth_flags & T1_MEDIA_BIT_DEPTH_10) &&
         (!(capability->output_formats & T1_MEDIA_OUTPUT_P010) ||
          !t1_media_create_imports_separate_depth(
              configuration,
              10))))
        return T1_MEDIA_STATUS_UNSUPPORTED_CONFIGURATION;
    if ((capability->minimum_width &&
         configuration->coded_width < capability->minimum_width) ||
        (capability->minimum_height &&
         configuration->coded_height < capability->minimum_height) ||
        (capability->maximum_width &&
         configuration->coded_width > capability->maximum_width) ||
        (capability->maximum_height &&
         configuration->coded_height > capability->maximum_height))
        return T1_MEDIA_STATUS_UNSUPPORTED_CONFIGURATION;
    return T1_MEDIA_STATUS_OK;
}

static uint32_t
t1_media_open_decoder(struct t1_media_worker *worker,
                      const struct t1_media_create *configuration,
                      size_t payload_size)
{
    uint32_t validation =
        t1_media_validate_create(worker, configuration, payload_size);
    if (validation != T1_MEDIA_STATUS_OK)
        return validation;

    enum AVCodecID codec_id =
        t1_media_codec_id(configuration->codec);
    const AVCodec *decoder = avcodec_find_decoder(codec_id);
    if (!decoder)
        return T1_MEDIA_STATUS_UNSUPPORTED_CODEC;

    AVCodecContext *context = avcodec_alloc_context3(decoder);
    if (!context)
        return T1_MEDIA_STATUS_RESOURCE_EXHAUSTED;
    context->codec_id = codec_id;
    context->width = (int)configuration->coded_width;
    context->height = (int)configuration->coded_height;
    context->profile = t1_media_av_profile(configuration->profile);
    context->colorspace =
        (enum AVColorSpace)configuration->color_matrix;
    context->color_primaries =
        (enum AVColorPrimaries)configuration->color_primaries;
    context->color_trc =
        (enum AVColorTransferCharacteristic)
            configuration->color_transfer;
    context->color_range =
        (enum AVColorRange)configuration->color_range;
    context->pkt_timebase = (AVRational){1, 1000000000};
    context->time_base = (AVRational){1, 1000000000};
    context->thread_count = 1;
    context->get_format = t1_media_hardware_format;
    if (configuration->flags & T1_MEDIA_CREATE_LOW_DELAY)
        context->flags |= AV_CODEC_FLAG_LOW_DELAY;

    if (configuration->extradata_size) {
        context->extradata = av_mallocz(
            configuration->extradata_size +
            AV_INPUT_BUFFER_PADDING_SIZE);
        if (!context->extradata) {
            avcodec_free_context(&context);
            return T1_MEDIA_STATUS_RESOURCE_EXHAUSTED;
        }
        context->extradata_size =
            (int)configuration->extradata_size;
        memcpy(
            context->extradata,
            (const unsigned char *)configuration +
                sizeof(*configuration),
            configuration->extradata_size);
    }

    if (!worker->device) {
        avcodec_free_context(&context);
        return T1_MEDIA_STATUS_HARDWARE_UNAVAILABLE;
    }
    context->hw_device_ctx = av_buffer_ref(worker->device);
    if (!context->hw_device_ctx) {
        avcodec_free_context(&context);
        return T1_MEDIA_STATUS_RESOURCE_EXHAUSTED;
    }
    int result = avcodec_open2(context, decoder, NULL);
    if (result < 0) {
        avcodec_free_context(&context);
        return T1_MEDIA_STATUS_UNSUPPORTED_CONFIGURATION;
    }

    t1_media_close_decoder(worker);
    worker->codec = context;
    worker->created = true;
    worker->drained = false;
    worker->import_fourcc_count =
        configuration->import_fourcc_count;
    memcpy(
        worker->import_fourcc,
        configuration->import_fourcc,
        sizeof(uint32_t) * worker->import_fourcc_count);
    worker->configured_visible_x = configuration->visible_x;
    worker->configured_visible_y = configuration->visible_y;
    worker->configured_visible_width = configuration->visible_width;
    worker->configured_visible_height = configuration->visible_height;
    const struct t1_media_capability_profile *capability =
        t1_media_find_capability(
            &worker->capabilities,
            configuration->codec,
            configuration->profile);
    worker->configured_minimum_width =
        capability ? capability->minimum_width : 1;
    worker->configured_minimum_height =
        capability ? capability->minimum_height : 1;
    worker->configured_maximum_width =
        capability && capability->maximum_width
            ? capability->maximum_width
            : T1_MEDIA_ABSOLUTE_DIMENSION;
    worker->configured_maximum_height =
        capability && capability->maximum_height
            ? capability->maximum_height
            : T1_MEDIA_ABSOLUTE_DIMENSION;
    worker->configured_bit_depths =
        configuration->bit_depth == 8
            ? T1_MEDIA_BIT_DEPTH_8
            : configuration->bit_depth == 10
                ? T1_MEDIA_BIT_DEPTH_10
                : capability
                    ? capability->bit_depths &
                        (T1_MEDIA_BIT_DEPTH_8 |
                         T1_MEDIA_BIT_DEPTH_10)
                    : 0;
    return T1_MEDIA_STATUS_OK;
}

static VADisplay
t1_media_display(struct t1_media_worker *worker)
{
    if (!worker->device)
        return NULL;
    AVHWDeviceContext *hardware =
        (AVHWDeviceContext *)worker->device->data;
    AVVAAPIDeviceContext *vaapi =
        (AVVAAPIDeviceContext *)hardware->hwctx;
    return vaapi->display;
}

static enum AVPixelFormat
t1_media_software_format(const AVFrame *frame)
{
    if (!frame->hw_frames_ctx)
        return AV_PIX_FMT_NONE;
    const AVHWFramesContext *frames =
        (const AVHWFramesContext *)frame->hw_frames_ctx->data;
    return frames->sw_format;
}

static uint32_t
t1_media_pixel_format(const AVFrame *frame)
{
    enum AVPixelFormat format = t1_media_software_format(frame);
    if (format == AV_PIX_FMT_NV12)
        return T1_MEDIA_PIXEL_FORMAT_NV12;
    if (format == AV_PIX_FMT_P010LE)
        return T1_MEDIA_PIXEL_FORMAT_P010;
    return T1_MEDIA_PIXEL_FORMAT_UNKNOWN;
}

static uint32_t
t1_media_frame_bit_depth(const AVFrame *frame)
{
    const AVPixFmtDescriptor *description =
        av_pix_fmt_desc_get(t1_media_software_format(frame));
    if (!description || description->nb_components < 1)
        return 0;
    return (uint32_t)description->comp[0].depth;
}

static bool
t1_media_frame_format_valid(const struct t1_media_worker *worker,
                            const AVFrame *frame)
{
    enum AVPixelFormat software_format =
        t1_media_software_format(frame);
    uint32_t pixel_format = t1_media_pixel_format(frame);
    uint32_t bit_depth = t1_media_frame_bit_depth(frame);
    uint32_t depth_flag =
        bit_depth == 8
            ? T1_MEDIA_BIT_DEPTH_8
            : bit_depth == 10
                ? T1_MEDIA_BIT_DEPTH_10
                : 0;
    const AVPixFmtDescriptor *description =
        av_pix_fmt_desc_get(software_format);
    return description &&
        description->nb_components == 3 &&
        description->log2_chroma_w == 1 &&
        description->log2_chroma_h == 1 &&
        depth_flag &&
        (worker->configured_bit_depths & depth_flag) != 0 &&
        ((bit_depth == 8 &&
          software_format == AV_PIX_FMT_NV12 &&
          pixel_format == T1_MEDIA_PIXEL_FORMAT_NV12) ||
         (bit_depth == 10 &&
          software_format == AV_PIX_FMT_P010LE &&
          pixel_format == T1_MEDIA_PIXEL_FORMAT_P010));
}

static bool
t1_media_import_format_accepted(const struct t1_media_worker *worker,
                                uint32_t fourcc)
{
    if (!worker->import_fourcc_count)
        return true;
    for (unsigned index = 0;
         index < worker->import_fourcc_count;
         ++index) {
        if (worker->import_fourcc[index] == fourcc)
            return true;
    }
    return false;
}

static bool
t1_media_drm_separate_descriptor_valid(
    const struct t1_media_worker *worker,
    const AVFrame *frame,
    const VADRMPRIMESurfaceDescriptor *drm)
{
    uint32_t pixel_format = t1_media_pixel_format(frame);
    uint32_t luma_fourcc =
        pixel_format == T1_MEDIA_PIXEL_FORMAT_NV12
            ? T1_MEDIA_DRM_FORMAT_R8
            : pixel_format == T1_MEDIA_PIXEL_FORMAT_P010
                ? T1_MEDIA_DRM_FORMAT_R16
                : 0;
    uint32_t chroma_fourcc =
        pixel_format == T1_MEDIA_PIXEL_FORMAT_NV12
            ? T1_MEDIA_DRM_FORMAT_RG88
            : pixel_format == T1_MEDIA_PIXEL_FORMAT_P010
                ? T1_MEDIA_DRM_FORMAT_RG1616
                : 0;
    uint32_t alternate_chroma_fourcc =
        pixel_format == T1_MEDIA_PIXEL_FORMAT_NV12
            ? T1_MEDIA_DRM_FORMAT_GR88
            : pixel_format == T1_MEDIA_PIXEL_FORMAT_P010
                ? T1_MEDIA_DRM_FORMAT_GR1616
                : 0;
    if (!luma_fourcc ||
        drm->num_objects != 2 ||
        drm->num_layers != 2 ||
        drm->layers[0].drm_format != luma_fourcc ||
        (drm->layers[1].drm_format != chroma_fourcc &&
         drm->layers[1].drm_format != alternate_chroma_fourcc) ||
        drm->layers[0].num_planes != 1 ||
        drm->layers[1].num_planes != 1 ||
        drm->layers[0].object_index[0] ==
            drm->layers[1].object_index[0])
        return false;
    for (uint32_t object = 0; object < drm->num_objects; ++object) {
        if (drm->objects[object].fd < 0 ||
            drm->objects[object].size == 0 ||
            drm->objects[object].drm_format_modifier == UINT64_MAX)
            return false;
    }
    for (uint32_t layer = 0; layer < drm->num_layers; ++layer) {
        uint32_t object = drm->layers[layer].object_index[0];
        uint32_t width =
            layer == 0
                ? (uint32_t)frame->width
                : (uint32_t)frame->width / 2u +
                    (uint32_t)frame->width % 2u;
        uint32_t height =
            layer == 0
                ? (uint32_t)frame->height
                : (uint32_t)frame->height / 2u +
                    (uint32_t)frame->height % 2u;
        uint64_t bytes_per_component =
            pixel_format == T1_MEDIA_PIXEL_FORMAT_NV12 ? 1u : 2u;
        uint64_t minimum_row_bytes =
            (uint64_t)width * bytes_per_component *
            (layer == 0 ? 1u : 2u);
        uint64_t pitch = drm->layers[layer].pitch[0];
        uint64_t offset = drm->layers[layer].offset[0];
        if (!t1_media_import_format_accepted(
            worker,
                drm->layers[layer].drm_format) ||
            object >= drm->num_objects ||
            offset != 0 ||
            pitch < minimum_row_bytes ||
            height == 0 ||
            pitch > UINT32_MAX)
            return false;
        uint64_t required =
            pitch * ((uint64_t)height - 1u) +
            minimum_row_bytes;
        if (required > drm->objects[object].size)
            return false;
    }
    return true;
}

static void
t1_media_close_drm(VADRMPRIMESurfaceDescriptor *drm)
{
    unsigned count = drm->num_objects;
    if (count > T1_MEDIA_MAX_FRAME_OBJECTS)
        count = T1_MEDIA_MAX_FRAME_OBJECTS;
    for (unsigned object = 0; object < count; ++object) {
        if (drm->objects[object].fd >= 0)
            close(drm->objects[object].fd);
        drm->objects[object].fd = -1;
    }
}

static unsigned
t1_media_open_slot(const struct t1_media_worker *worker)
{
    for (unsigned index = 0;
         index < T1_MEDIA_MAX_IN_FLIGHT_FRAMES;
         ++index) {
        if (!worker->slots[index].frame_id)
            return index;
    }
    return T1_MEDIA_MAX_IN_FLIGHT_FRAMES;
}

static void
t1_media_layer_size(const AVFrame *frame,
                    uint32_t layer,
                    uint32_t layer_count,
                    uint32_t width,
                    uint32_t height,
                    uint32_t *layer_width,
                    uint32_t *layer_height)
{
    *layer_width = width;
    *layer_height = height;
    if (layer_count < 2 || layer == 0)
        return;
    const AVPixFmtDescriptor *description =
        av_pix_fmt_desc_get(t1_media_software_format(frame));
    if (!description)
        return;
    unsigned width_shift =
        (unsigned)description->log2_chroma_w;
    unsigned height_shift =
        (unsigned)description->log2_chroma_h;
    *layer_width =
        (width + (1u << width_shift) - 1u) >> width_shift;
    *layer_height =
        (height + (1u << height_shift) - 1u) >> height_shift;
}

static void
t1_media_fill_frame_metadata(struct t1_media_worker *worker,
                             const AVFrame *frame,
                             struct t1_media_frame *output)
{
    output->timestamp_ns =
        frame->best_effort_timestamp != AV_NOPTS_VALUE
            ? frame->best_effort_timestamp
            : frame->pts != AV_NOPTS_VALUE
                ? frame->pts
                : 0;
    output->duration_ns = frame->duration > 0 ? frame->duration : 0;
    output->coded_width = (uint32_t)frame->width;
    output->coded_height = (uint32_t)frame->height;
    uint32_t crop_left =
        frame->crop_left <= (size_t)frame->width
            ? (uint32_t)frame->crop_left
            : 0;
    uint32_t crop_right =
        frame->crop_right <= (size_t)frame->width - crop_left
            ? (uint32_t)frame->crop_right
            : 0;
    uint32_t crop_top =
        frame->crop_top <= (size_t)frame->height
            ? (uint32_t)frame->crop_top
            : 0;
    uint32_t crop_bottom =
        frame->crop_bottom <= (size_t)frame->height - crop_top
            ? (uint32_t)frame->crop_bottom
            : 0;
    if (crop_left || crop_right || crop_top || crop_bottom) {
        output->visible_x = crop_left;
        output->visible_y = crop_top;
        output->visible_width =
            output->coded_width - crop_left - crop_right;
        output->visible_height =
            output->coded_height - crop_top - crop_bottom;
    } else if (
        worker->configured_visible_width &&
        worker->configured_visible_height &&
        worker->configured_visible_x <= output->coded_width &&
        worker->configured_visible_y <= output->coded_height &&
        worker->configured_visible_width <=
            output->coded_width - worker->configured_visible_x &&
        worker->configured_visible_height <=
            output->coded_height - worker->configured_visible_y) {
        output->visible_x = worker->configured_visible_x;
        output->visible_y = worker->configured_visible_y;
        output->visible_width = worker->configured_visible_width;
        output->visible_height = worker->configured_visible_height;
    } else {
        output->visible_width = output->coded_width;
        output->visible_height = output->coded_height;
    }
    output->pixel_format = t1_media_pixel_format(frame);
    output->bit_depth = t1_media_frame_bit_depth(frame);
    output->color_primaries = (uint32_t)frame->color_primaries;
    output->color_transfer = (uint32_t)frame->color_trc;
    output->color_matrix = (uint32_t)frame->colorspace;
    output->color_range = (uint32_t)frame->color_range;
    output->chroma_location = (uint32_t)frame->chroma_location;
    output->flags = T1_MEDIA_FRAME_SYNCHRONIZED;
    if (frame->flags & AV_FRAME_FLAG_INTERLACED)
        output->flags |= T1_MEDIA_FRAME_INTERLACED;
    if (frame->flags & AV_FRAME_FLAG_TOP_FIELD_FIRST)
        output->flags |= T1_MEDIA_FRAME_TOP_FIELD_FIRST;
}

static bool
t1_media_frame_dimensions_valid(const struct t1_media_worker *worker,
                                const AVFrame *frame)
{
    if (!frame ||
        frame->width <= 0 ||
        frame->height <= 0 ||
        (uint32_t)frame->width > T1_MEDIA_ABSOLUTE_DIMENSION ||
        (uint32_t)frame->height > T1_MEDIA_ABSOLUTE_DIMENSION)
        return false;
    uint32_t width = (uint32_t)frame->width;
    uint32_t height = (uint32_t)frame->height;
    return (!worker->configured_minimum_width ||
            width >= worker->configured_minimum_width) &&
        (!worker->configured_minimum_height ||
         height >= worker->configured_minimum_height) &&
        (!worker->configured_maximum_width ||
         width <= worker->configured_maximum_width) &&
        (!worker->configured_maximum_height ||
         height <= worker->configured_maximum_height);
}

static int
t1_media_send_linear_frame(struct t1_media_worker *worker,
                           AVFrame *frame,
                           uint64_t request,
                           unsigned slot_index)
{
    enum AVPixelFormat software_format = t1_media_software_format(frame);
    if (software_format != AV_PIX_FMT_NV12 &&
        software_format != AV_PIX_FMT_P010LE)
        return AVERROR(ENOSYS);

    AVFrame *software = av_frame_alloc();
    if (!software)
        return AVERROR(ENOMEM);
    software->format = software_format;
    software->width = frame->width;
    software->height = frame->height;
    int result = av_frame_get_buffer(software, 64);
    if (result >= 0)
        result = av_hwframe_transfer_data(software, frame, 0);
    if (result < 0) {
        av_frame_free(&software);
        return result;
    }

    uint64_t bytes_per_component =
        software_format == AV_PIX_FMT_NV12 ? 1u : 2u;
    uint64_t row_bytes =
        (uint64_t)(uint32_t)frame->width * bytes_per_component;
    if (software->width != frame->width ||
        software->height != frame->height ||
        !software->data[0] ||
        !software->data[1] ||
        software->linesize[0] <= 0 ||
        software->linesize[1] <= 0 ||
        (uint64_t)(uint32_t)software->linesize[0] < row_bytes ||
        (uint64_t)(uint32_t)software->linesize[1] < row_bytes) {
        av_frame_free(&software);
        return AVERROR(EINVAL);
    }
    uint64_t pitch_value = (row_bytes + 63u) & ~UINT64_C(63);
    uint64_t chroma_height =
        (uint64_t)((uint32_t)frame->height / 2u +
                   (uint32_t)frame->height % 2u);
    uint64_t luma_size =
        pitch_value * (uint64_t)(uint32_t)frame->height;
    uint64_t total_size = luma_size + pitch_value * chroma_height;
    if (!pitch_value || pitch_value > UINT32_MAX ||
        !total_size || total_size > INT64_MAX) {
        av_frame_free(&software);
        return AVERROR(EOVERFLOW);
    }

    int descriptor = memfd_create(
        "t1os-hardware-decoded-linear-frame",
        MFD_CLOEXEC | MFD_ALLOW_SEALING);
    if (descriptor < 0 ||
        ftruncate(descriptor, (off_t)total_size) < 0) {
        int saved = errno;
        if (descriptor >= 0)
            close(descriptor);
        av_frame_free(&software);
        return AVERROR(saved);
    }
    unsigned char *mapping = mmap(
        NULL,
        (size_t)total_size,
        PROT_READ | PROT_WRITE,
        MAP_SHARED,
        descriptor,
        0);
    if (mapping == MAP_FAILED) {
        int saved = errno;
        close(descriptor);
        av_frame_free(&software);
        return AVERROR(saved);
    }
    for (uint32_t row = 0; row < (uint32_t)frame->height; ++row) {
        memcpy(
            mapping + (size_t)pitch_value * row,
            software->data[0] + (size_t)software->linesize[0] * row,
            (size_t)row_bytes);
    }
    for (uint32_t row = 0; row < (uint32_t)chroma_height; ++row) {
        memcpy(
            mapping + (size_t)luma_size + (size_t)pitch_value * row,
            software->data[1] + (size_t)software->linesize[1] * row,
            (size_t)row_bytes);
    }
    av_frame_free(&software);
    if (munmap(mapping, (size_t)total_size) < 0 ||
        fcntl(
            descriptor,
            F_ADD_SEALS,
            F_SEAL_SEAL | F_SEAL_SHRINK |
                F_SEAL_GROW | F_SEAL_WRITE) < 0) {
        int saved = errno;
        close(descriptor);
        return AVERROR(saved);
    }

    struct t1_media_frame output = {0};
    output.frame_id = ++worker->next_frame_id;
    t1_media_fill_frame_metadata(worker, frame, &output);
    output.object_count = 1;
    output.layer_count = 1;
    output.flags |= T1_MEDIA_FRAME_LINEAR_MEMORY;
    output.objects[0].size = total_size;
    output.objects[0].modifier = 0;
    output.layers[0].drm_fourcc =
        output.pixel_format == T1_MEDIA_PIXEL_FORMAT_NV12
            ? T1_MEDIA_DRM_FORMAT_NV12
            : T1_MEDIA_DRM_FORMAT_P010;
    output.layers[0].width = output.coded_width;
    output.layers[0].height = output.coded_height;
    output.layers[0].plane_count = 2;
    output.layers[0].planes[0].object_index = 0;
    output.layers[0].planes[0].offset = 0;
    output.layers[0].planes[0].pitch = (uint32_t)pitch_value;
    output.layers[0].planes[1].object_index = 0;
    output.layers[0].planes[1].offset = (uint32_t)luma_size;
    output.layers[0].planes[1].pitch = (uint32_t)pitch_value;

    struct t1_media_frame_slot *slot = &worker->slots[slot_index];
    slot->frame_id = output.frame_id;
    slot->generation = worker->generation;
    slot->frame = frame;
    slot->fd_count = 1;
    slot->fds[0] = descriptor;
    worker->in_flight++;
    if (t1_media_send_packet(
            worker->socket_fd,
            T1_MEDIA_FRAME,
            worker->session,
            request,
            worker->generation,
            &output,
            sizeof(output),
            &descriptor,
            1) < 0) {
        slot->frame = NULL;
        t1_media_release_slot(worker, slot_index);
        return AVERROR(EPIPE);
    }
    if (worker->debug) {
        fprintf(
            stderr,
            "T1_MEDIA_WORKER frame session=%" PRIu64
            " frame=%" PRIu64 " generation=%" PRIu64
            " size=%ux%u objects=1 layers=1 in_flight=%u "
            "linear_memory=1\n",
            worker->session,
            output.frame_id,
            worker->generation,
            output.coded_width,
            output.coded_height,
            worker->in_flight);
    }
    return 0;
}

static int
t1_media_send_frame(struct t1_media_worker *worker,
                    AVFrame *frame,
                    uint64_t request)
{
    if (!t1_media_frame_dimensions_valid(worker, frame) ||
        frame->format != AV_PIX_FMT_VAAPI ||
        !t1_media_frame_format_valid(worker, frame)) {
        if (worker->debug) {
            enum AVPixelFormat software =
                t1_media_software_format(frame);
            fprintf(
                stderr,
                "T1_MEDIA_WORKER frame-format-rejected "
                "hardware=%d software=%s depth=%u "
                "allowed_depths=%u chroma=420\n",
                frame->format,
                av_get_pix_fmt_name(software)
                    ? av_get_pix_fmt_name(software)
                    : "unknown",
                t1_media_frame_bit_depth(frame),
                worker->configured_bit_depths);
        }
        return AVERROR(EINVAL);
    }
    unsigned slot_index = t1_media_open_slot(worker);
    if (slot_index >= T1_MEDIA_MAX_IN_FLIGHT_FRAMES)
        return AVERROR(ENOBUFS);

    VADisplay display = t1_media_display(worker);
    VASurfaceID surface =
        (VASurfaceID)(uintptr_t)frame->data[3];
    VAStatus status = vaSyncSurface(display, surface);
    if (status != VA_STATUS_SUCCESS)
        return AVERROR_EXTERNAL;
    if (worker->linear_memory_output)
        return t1_media_send_linear_frame(
            worker,
            frame,
            request,
            slot_index);

    VADRMPRIMESurfaceDescriptor drm = {0};
    status = vaExportSurfaceHandle(
        display,
        surface,
        VA_SURFACE_ATTRIB_MEM_TYPE_DRM_PRIME_2,
        VA_EXPORT_SURFACE_READ_ONLY |
            VA_EXPORT_SURFACE_SEPARATE_LAYERS,
        &drm);
    if (status != VA_STATUS_SUCCESS ||
        !t1_media_drm_separate_descriptor_valid(
            worker,
            frame,
            &drm)) {
        if (status == VA_STATUS_SUCCESS)
            t1_media_close_drm(&drm);
        return status == VA_STATUS_SUCCESS
            ? AVERROR(ENOSYS)
            : AVERROR_EXTERNAL;
    }

    struct t1_media_frame output = {0};
    output.frame_id = ++worker->next_frame_id;
    output.timestamp_ns =
        frame->best_effort_timestamp != AV_NOPTS_VALUE
            ? frame->best_effort_timestamp
            : frame->pts != AV_NOPTS_VALUE
                ? frame->pts
                : 0;
    output.duration_ns = frame->duration > 0 ? frame->duration : 0;
    output.coded_width = (uint32_t)frame->width;
    output.coded_height = (uint32_t)frame->height;
    uint32_t crop_left =
        frame->crop_left <= (size_t)frame->width
            ? (uint32_t)frame->crop_left
            : 0;
    uint32_t crop_right =
        frame->crop_right <= (size_t)frame->width - crop_left
            ? (uint32_t)frame->crop_right
            : 0;
    uint32_t crop_top =
        frame->crop_top <= (size_t)frame->height
            ? (uint32_t)frame->crop_top
            : 0;
    uint32_t crop_bottom =
        frame->crop_bottom <= (size_t)frame->height - crop_top
            ? (uint32_t)frame->crop_bottom
            : 0;
    if (crop_left || crop_right || crop_top || crop_bottom) {
        output.visible_x = crop_left;
        output.visible_y = crop_top;
        output.visible_width =
            output.coded_width - crop_left - crop_right;
        output.visible_height =
            output.coded_height - crop_top - crop_bottom;
    } else if (
        worker->configured_visible_width &&
        worker->configured_visible_height &&
        worker->configured_visible_x <= output.coded_width &&
        worker->configured_visible_y <= output.coded_height &&
        worker->configured_visible_width <=
            output.coded_width - worker->configured_visible_x &&
        worker->configured_visible_height <=
            output.coded_height - worker->configured_visible_y) {
        output.visible_x = worker->configured_visible_x;
        output.visible_y = worker->configured_visible_y;
        output.visible_width = worker->configured_visible_width;
        output.visible_height = worker->configured_visible_height;
    } else {
        output.visible_width = output.coded_width;
        output.visible_height = output.coded_height;
    }
    output.pixel_format = t1_media_pixel_format(frame);
    output.bit_depth = t1_media_frame_bit_depth(frame);
    output.color_primaries = (uint32_t)frame->color_primaries;
    output.color_transfer = (uint32_t)frame->color_trc;
    output.color_matrix = (uint32_t)frame->colorspace;
    output.color_range = (uint32_t)frame->color_range;
    output.chroma_location = (uint32_t)frame->chroma_location;
    output.object_count = drm.num_objects;
    output.layer_count = drm.num_layers;
    output.flags = T1_MEDIA_FRAME_SYNCHRONIZED;
    if (frame->flags & AV_FRAME_FLAG_INTERLACED)
        output.flags |= T1_MEDIA_FRAME_INTERLACED;
    if (frame->flags & AV_FRAME_FLAG_TOP_FIELD_FIRST)
        output.flags |= T1_MEDIA_FRAME_TOP_FIELD_FIRST;
    output.flags |= T1_MEDIA_FRAME_SEPARATE_LAYERS;

    int descriptors[T1_MEDIA_MAX_FRAME_OBJECTS] = {-1, -1, -1, -1};
    for (uint32_t object = 0; object < drm.num_objects; ++object) {
        descriptors[object] = drm.objects[object].fd;
        output.objects[object].size = drm.objects[object].size;
        output.objects[object].modifier =
            drm.objects[object].drm_format_modifier;
    }
    for (uint32_t layer = 0; layer < drm.num_layers; ++layer) {
        struct t1_media_frame_layer *target =
            &output.layers[layer];
        target->drm_fourcc = drm.layers[layer].drm_format;
        uint32_t layer_width = output.coded_width;
        uint32_t layer_height = output.coded_height;
        t1_media_layer_size(
            frame,
            layer,
            drm.num_layers,
            output.coded_width,
            output.coded_height,
            &layer_width,
            &layer_height);
        target->width = layer_width;
        target->height = layer_height;
        target->plane_count = drm.layers[layer].num_planes;
        for (uint32_t plane = 0;
             plane < target->plane_count;
             ++plane) {
            target->planes[plane].object_index =
                drm.layers[layer].object_index[plane];
            target->planes[plane].offset =
                drm.layers[layer].offset[plane];
            target->planes[plane].pitch =
                drm.layers[layer].pitch[plane];
        }
    }

    if (!worker->first_surface_export_logged) {
        worker->first_surface_export_logged = true;
        fprintf(
            stderr,
            "T1_MEDIA_WORKER surface-export "
            "mode=separate-layers object_layout=one-object-per-plane "
            "modifier_scope=per-object modifier_layout=natural-per-plane "
            "composed_fallback=0 pixel_format=%u bit_depth=%u "
            "objects=%u layers=%u luma_modifier=0x%016" PRIx64 " "
            "chroma_modifier=0x%016" PRIx64 "\n",
            output.pixel_format,
            output.bit_depth,
            output.object_count,
            output.layer_count,
            output.objects[
                output.layers[0].planes[0].object_index].modifier,
            output.objects[
                output.layers[1].planes[0].object_index].modifier);
    }

    struct t1_media_frame_slot *slot =
        &worker->slots[slot_index];
    slot->frame_id = output.frame_id;
    slot->generation = worker->generation;
    slot->frame = frame;
    slot->fd_count = drm.num_objects;
    memcpy(
        slot->fds,
        descriptors,
        sizeof(int) * drm.num_objects);
    worker->in_flight++;

    if (t1_media_send_packet(
            worker->socket_fd,
            T1_MEDIA_FRAME,
            worker->session,
            request,
            worker->generation,
            &output,
            sizeof(output),
            descriptors,
            drm.num_objects) < 0) {
        slot->frame = NULL;
        t1_media_release_slot(worker, slot_index);
        return AVERROR(EPIPE);
    }
    if (worker->debug) {
        fprintf(
            stderr,
            "T1_MEDIA_WORKER frame session=%" PRIu64
            " frame=%" PRIu64 " generation=%" PRIu64
            " size=%ux%u objects=%u layers=%u in_flight=%u\n",
            worker->session,
            output.frame_id,
            worker->generation,
            output.coded_width,
            output.coded_height,
            output.object_count,
            output.layer_count,
            worker->in_flight);
    }
    return 0;
}

static int
t1_media_handle_release(
    struct t1_media_worker *worker,
    struct t1_media_packet *packet);

static int
t1_media_validate_session_header(
    const struct t1_media_worker *worker,
    const struct t1_media_message_header *header);

static int
t1_media_send_result(struct t1_media_worker *worker,
                     uint16_t type,
                     uint64_t request,
                     uint32_t status);

static int
t1_media_send_backpressure(
    struct t1_media_worker *worker,
    uint32_t state)
{
    struct t1_media_backpressure backpressure = {
        .state = state,
        .in_flight_frames = worker->in_flight,
    };
    return t1_media_send_packet(
        worker->socket_fd,
        T1_MEDIA_BACKPRESSURE,
        worker->session,
        worker->watchdog_request,
        worker->watchdog_generation,
        &backpressure,
        sizeof(backpressure),
        NULL,
        0);
}

/*
 * Returns zero after one frame release, one when RESET interrupted the active
 * DECODE/FLUSH, or -1 on a fatal session/protocol failure.
 */
static int
t1_media_wait_for_backpressure_release(
    struct t1_media_worker *worker)
{
    if (t1_media_send_backpressure(
            worker,
            T1_MEDIA_BACKPRESSURE_ENTER) < 0 ||
        t1_media_watchdog_wait(worker) < 0)
        return -1;

    struct t1_media_packet packet;
    int received =
        t1_media_receive_packet(
            worker->socket_fd,
            &packet);
    if (received != 1) {
        worker->stopping = true;
        return -1;
    }
    const struct t1_media_message_header *header =
        t1_media_packet_header(&packet);
    if (!t1_media_validate_session_header(
            worker,
            header) ||
        header->request <= worker->last_request) {
        uint64_t invalid_request =
            header ? header->request : 0;
        if (t1_media_watchdog_resume(
                worker) < 0) {
            t1_media_packet_close_fds(&packet);
            worker->stopping = true;
            return -1;
        }
        t1_media_packet_close_fds(&packet);
        t1_media_send_error(
            worker->socket_fd,
            worker->session,
            invalid_request,
            worker->generation,
            T1_MEDIA_STATUS_PROTOCOL_ERROR,
            "backpressure accepts only a later RELEASE or RESET");
        worker->stopping = true;
        return -1;
    }

    if (header->type == T1_MEDIA_RELEASE) {
        uint64_t release_request =
            header->request;
        worker->last_request = release_request;
        if (t1_media_watchdog_resume(
                worker) < 0 ||
            t1_media_handle_release(
                worker,
                &packet) < 0) {
            t1_media_packet_close_fds(&packet);
            t1_media_send_error(
                worker->socket_fd,
                worker->session,
                release_request,
                worker->generation,
                T1_MEDIA_STATUS_PROTOCOL_ERROR,
                "invalid frame release during backpressure");
            worker->stopping = true;
            return -1;
        }
        if (t1_media_send_backpressure(
                worker,
                T1_MEDIA_BACKPRESSURE_EXIT) < 0) {
            worker->stopping = true;
            return -1;
        }
        return 0;
    }

    bool valid_reset =
        header->type == T1_MEDIA_RESET &&
        header->generation ==
            worker->generation + 1 &&
        packet.fd_count == 0 &&
        t1_media_packet_payload_size(&packet) == 0;
    if (!valid_reset) {
        uint64_t invalid_request =
            header->request;
        if (t1_media_watchdog_resume(
                worker) < 0) {
            t1_media_packet_close_fds(&packet);
            worker->stopping = true;
            return -1;
        }
        t1_media_packet_close_fds(&packet);
        t1_media_send_error(
            worker->socket_fd,
            worker->session,
            invalid_request,
            worker->generation,
            T1_MEDIA_STATUS_PROTOCOL_ERROR,
            "backpressure accepts only RELEASE or next-generation RESET");
        worker->stopping = true;
        return -1;
    }

    uint64_t reset_request = header->request;
    uint64_t reset_generation =
        header->generation;
    worker->last_request = reset_request;
    if (t1_media_watchdog_resume(
            worker) < 0) {
        t1_media_packet_close_fds(&packet);
        worker->stopping = true;
        return -1;
    }
    t1_media_packet_close_fds(&packet);

    uint16_t interrupted_operation =
        worker->watchdog_operation;
    uint64_t interrupted_request =
        worker->watchdog_request;
    uint64_t interrupted_generation =
        worker->watchdog_generation;
    if (t1_media_watchdog_complete(
            worker,
            interrupted_operation,
            interrupted_request,
            interrupted_generation) < 0 ||
        t1_media_watchdog_begin(
            worker,
            T1_MEDIA_WATCHDOG_RESET,
            reset_request,
            reset_generation) < 0) {
        worker->stopping = true;
        return -1;
    }
    avcodec_flush_buffers(worker->codec);
    worker->generation = reset_generation;
    worker->drained = false;
    int result = t1_media_send_result(
        worker,
        T1_MEDIA_RESET_DONE,
        reset_request,
        T1_MEDIA_STATUS_OK);
    if (result < 0 ||
        t1_media_watchdog_complete(
            worker,
            T1_MEDIA_WATCHDOG_RESET,
            reset_request,
            reset_generation) < 0) {
        worker->stopping = true;
        return -1;
    }
    worker->reset_interrupted = true;
    return 1;
}

typedef int (*t1_media_receive_frame_function)(
    struct t1_media_worker *,
    AVFrame *,
    void *);

typedef int (*t1_media_send_frame_function)(
    struct t1_media_worker *,
    AVFrame *,
    uint64_t,
    void *);

typedef int (*t1_media_wait_frame_function)(
    struct t1_media_worker *,
    void *);

static int
t1_media_receive_codec_frame(
    struct t1_media_worker *worker,
    AVFrame *frame,
    void *context)
{
    (void)context;
    return avcodec_receive_frame(
        worker->codec,
        frame);
}

static int
t1_media_send_codec_frame(
    struct t1_media_worker *worker,
    AVFrame *frame,
    uint64_t request,
    void *context)
{
    (void)context;
    return t1_media_send_frame(
        worker,
        frame,
        request);
}

static int
t1_media_wait_codec_frame(
    struct t1_media_worker *worker,
    void *context)
{
    (void)context;
    return t1_media_wait_for_backpressure_release(
        worker);
}

static int
t1_media_receive_frames_with(
    struct t1_media_worker *worker,
    uint64_t request,
    t1_media_receive_frame_function receive_frame,
    t1_media_send_frame_function send_frame,
    t1_media_wait_frame_function wait_frame,
    void *context)
{
    for (;;) {
        AVFrame *frame = av_frame_alloc();
        if (!frame)
            return AVERROR(ENOMEM);
        int result = receive_frame(
            worker,
            frame,
            context);
        if (result == AVERROR(EAGAIN) || result == AVERROR_EOF) {
            av_frame_free(&frame);
            return result;
        }
        if (result < 0) {
            av_frame_free(&frame);
            return result;
        }
        result = send_frame(
            worker,
            frame,
            request,
            context);
        while (result == AVERROR(ENOBUFS)) {
            int backpressure =
                wait_frame(
                    worker,
                    context);
            if (backpressure != 0) {
                av_frame_free(&frame);
                return backpressure > 0
                    ? AVERROR(ECANCELED)
                    : AVERROR(EPIPE);
            }
            result = send_frame(
                worker,
                frame,
                request,
                context);
        }
        if (result < 0) {
            av_frame_free(&frame);
            return result;
        }
    }
}

static int
t1_media_receive_frames(struct t1_media_worker *worker,
                        uint64_t request)
{
    return t1_media_receive_frames_with(
        worker,
        request,
        t1_media_receive_codec_frame,
        t1_media_send_codec_frame,
        t1_media_wait_codec_frame,
        NULL);
}

static uint32_t
t1_media_read_decode_packet(const struct t1_media_decode *input,
                            int descriptor,
                            AVPacket *packet)
{
    if (input->data_size == 0 ||
        input->data_size > T1_MEDIA_MAX_ENCODED_BYTES ||
        input->flags &
            ~(T1_MEDIA_DECODE_KEYFRAME |
              T1_MEDIA_DECODE_DISCONTINUITY))
        return T1_MEDIA_STATUS_INVALID_MESSAGE;

    struct stat status;
    if (fstat(descriptor, &status) < 0 ||
        !S_ISREG(status.st_mode) ||
        input->data_offset > (uint64_t)status.st_size ||
        input->data_size >
            (uint64_t)status.st_size - input->data_offset)
        return T1_MEDIA_STATUS_INVALID_MESSAGE;
    int seals = fcntl(descriptor, F_GET_SEALS);
    int required_seals =
        F_SEAL_WRITE | F_SEAL_SHRINK | F_SEAL_GROW;
    if (seals < 0 || (seals & required_seals) != required_seals)
        return T1_MEDIA_STATUS_INVALID_MESSAGE;

    int result = av_new_packet(packet, (int)input->data_size);
    if (result < 0)
        return T1_MEDIA_STATUS_RESOURCE_EXHAUSTED;
    size_t remaining = input->data_size;
    unsigned char *cursor = packet->data;
    uint64_t offset = input->data_offset;
    while (remaining) {
        ssize_t received = pread(
            descriptor,
            cursor,
            remaining,
            (off_t)offset);
        if (received < 0) {
            if (errno == EINTR)
                continue;
            av_packet_unref(packet);
            return T1_MEDIA_STATUS_INVALID_MESSAGE;
        }
        if (received == 0) {
            av_packet_unref(packet);
            return T1_MEDIA_STATUS_INVALID_MESSAGE;
        }
        cursor += (size_t)received;
        offset += (uint64_t)received;
        remaining -= (size_t)received;
    }
    packet->pts = input->timestamp_ns;
    packet->dts = input->timestamp_ns;
    packet->duration =
        input->duration_ns > 0 ? input->duration_ns : 0;
    if (input->flags & T1_MEDIA_DECODE_KEYFRAME)
        packet->flags |= AV_PKT_FLAG_KEY;
    return T1_MEDIA_STATUS_OK;
}

static uint32_t
t1_media_decode_access_unit(struct t1_media_worker *worker,
                            const struct t1_media_decode *input,
                            int descriptor,
                            uint64_t request)
{
    if (worker->drained)
        return T1_MEDIA_STATUS_PROTOCOL_ERROR;
    AVPacket *packet = av_packet_alloc();
    if (!packet)
        return T1_MEDIA_STATUS_RESOURCE_EXHAUSTED;
    uint32_t status =
        t1_media_read_decode_packet(input, descriptor, packet);
    if (status != T1_MEDIA_STATUS_OK) {
        av_packet_free(&packet);
        return status;
    }
    if (input->flags & T1_MEDIA_DECODE_DISCONTINUITY)
        avcodec_flush_buffers(worker->codec);

    int result;
    for (;;) {
        result = avcodec_send_packet(worker->codec, packet);
        if (result != AVERROR(EAGAIN))
            break;
        result = t1_media_receive_frames(worker, request);
        if (result != AVERROR(EAGAIN) && result != AVERROR_EOF)
            break;
    }
    av_packet_free(&packet);
    if (result < 0)
        return result == AVERROR(ENOBUFS)
            ? T1_MEDIA_STATUS_RESOURCE_EXHAUSTED
            : T1_MEDIA_STATUS_DECODE_ERROR;

    result = t1_media_receive_frames(worker, request);
    if (result != AVERROR(EAGAIN) && result != AVERROR_EOF)
        return result == AVERROR(ENOBUFS)
            ? T1_MEDIA_STATUS_RESOURCE_EXHAUSTED
            : T1_MEDIA_STATUS_DECODE_ERROR;
    return T1_MEDIA_STATUS_OK;
}

static uint32_t
t1_media_flush_decoder(struct t1_media_worker *worker,
                       uint64_t request)
{
    if (worker->drained)
        return T1_MEDIA_STATUS_OK;
    int result = avcodec_send_packet(worker->codec, NULL);
    while (result == AVERROR(EAGAIN)) {
        result = t1_media_receive_frames(worker, request);
        if (result == AVERROR(EAGAIN))
            result = avcodec_send_packet(worker->codec, NULL);
    }
    if (result < 0 && result != AVERROR_EOF)
        return T1_MEDIA_STATUS_DECODE_ERROR;
    for (;;) {
        result = t1_media_receive_frames(worker, request);
        if (result == AVERROR_EOF || result == AVERROR(EAGAIN))
            break;
        if (result < 0)
            return result == AVERROR(ENOBUFS)
                ? T1_MEDIA_STATUS_RESOURCE_EXHAUSTED
                : T1_MEDIA_STATUS_DECODE_ERROR;
    }
    worker->drained = true;
    return T1_MEDIA_STATUS_OK;
}

static int
t1_media_send_result(struct t1_media_worker *worker,
                     uint16_t type,
                     uint64_t request,
                     uint32_t status)
{
    struct t1_media_result result = {
        .status = status,
    };
    return t1_media_send_packet(
        worker->socket_fd,
        type,
        worker->session,
        request,
        worker->generation,
        &result,
        sizeof(result),
        NULL,
        0);
}

static int
t1_media_handle_release(struct t1_media_worker *worker,
                        struct t1_media_packet *packet)
{
    const struct t1_media_message_header *header =
        t1_media_packet_header(packet);
    const struct t1_media_release *release =
        t1_media_packet_payload_const(packet);
    if (t1_media_packet_payload_size(packet) != sizeof(*release) ||
        release->reserved != 0 ||
        release->flags & ~T1_MEDIA_RELEASE_HAS_FENCE ||
        packet->fd_count !=
            ((release->flags & T1_MEDIA_RELEASE_HAS_FENCE) ? 1u : 0u))
        return -1;

    unsigned slot_index = T1_MEDIA_MAX_IN_FLIGHT_FRAMES;
    for (unsigned index = 0;
         index < T1_MEDIA_MAX_IN_FLIGHT_FRAMES;
         ++index) {
        if (worker->slots[index].frame_id == release->frame_id) {
            slot_index = index;
            break;
        }
    }
    if (slot_index >= T1_MEDIA_MAX_IN_FLIGHT_FRAMES ||
        worker->slots[slot_index].generation != header->generation)
        return -1;

    if (packet->fd_count == 1) {
        struct pollfd fence = {
            .fd = packet->fds[0],
            .events = POLLIN | POLLERR | POLLHUP,
        };
        int ready;
        do {
            ready = poll(
                &fence,
                1,
                T1_MEDIA_RELEASE_FENCE_TIMEOUT_MS);
        } while (ready < 0 && errno == EINTR);
        if (ready <= 0)
            return -1;
    }
    t1_media_packet_close_fds(packet);
    t1_media_release_slot(worker, slot_index);
    return 0;
}

static int
t1_media_validate_session_header(const struct t1_media_worker *worker,
                                 const struct t1_media_message_header *header)
{
    return header &&
        header->session == worker->session &&
        header->request != 0 &&
        header->generation != 0;
}

static int
t1_media_finish_hello(struct t1_media_worker *worker)
{
    int result = t1_media_send_packet(
        worker->socket_fd,
        T1_MEDIA_CAPABILITIES,
        worker->session,
        worker->last_request,
        0,
        &worker->capabilities,
        sizeof(worker->capabilities),
        NULL,
        0);
    if (result < 0)
        return -1;
    return t1_media_watchdog_complete(
        worker,
        T1_MEDIA_WATCHDOG_HELLO,
        worker->last_request,
        0);
}

static int
t1_media_accept_hello(struct t1_media_worker *worker,
                      struct t1_media_packet *packet,
                      bool defer_capabilities)
{
    const struct t1_media_message_header *header =
        t1_media_packet_header(packet);
    const struct t1_media_hello *hello =
        t1_media_packet_payload_const(packet);
    uint32_t required_output_features =
        hello->required_features &
        (T1_MEDIA_FEATURE_DMABUF |
         T1_MEDIA_FEATURE_LINEAR_MEMORY_OUTPUT);
    bool valid =
        header->type == T1_MEDIA_HELLO &&
        header->session == 0 &&
        header->generation == 0 &&
        header->request > worker->last_request &&
        packet->fd_count == 0 &&
        t1_media_packet_payload_size(packet) == sizeof(*hello) &&
        hello->minimum_version <= T1_MEDIA_PROTOCOL_VERSION &&
        hello->maximum_version >= T1_MEDIA_PROTOCOL_VERSION &&
        hello->reserved == 0 &&
        hello->maximum_frame_objects >= T1_MEDIA_MAX_FRAME_OBJECTS &&
        hello->maximum_frame_layers >= T1_MEDIA_MAX_FRAME_LAYERS &&
        hello->maximum_planes_per_layer >=
            T1_MEDIA_MAX_PLANES_PER_LAYER &&
        (required_output_features == T1_MEDIA_FEATURE_DMABUF ||
         required_output_features ==
             T1_MEDIA_FEATURE_LINEAR_MEMORY_OUTPUT) &&
        !(hello->required_features & ~worker->capabilities.features);
    uint64_t request = header->request;
    t1_media_packet_close_fds(packet);
    if (!valid) {
        t1_media_send_error(
            worker->socket_fd,
            0,
            request,
            0,
            T1_MEDIA_STATUS_UNSUPPORTED_VERSION,
            "invalid or unsupported HELLO");
        errno = EPROTO;
        return -1;
    }

    if (t1_media_watchdog_begin(
            worker,
            T1_MEDIA_WATCHDOG_HELLO,
            request,
            0) < 0)
        return -1;
    worker->session = t1_media_random_session();
    worker->generation = 0;
    worker->last_request = request;
    worker->linear_memory_output =
        (hello->required_features &
         T1_MEDIA_FEATURE_LINEAR_MEMORY_OUTPUT) != 0;
    return defer_capabilities
        ? 0
        : t1_media_finish_hello(worker);
}

static int
t1_media_handshake(struct t1_media_worker *worker,
                   bool defer_capabilities)
{
    struct pollfd descriptor = {
        .fd = worker->socket_fd,
        .events = POLLIN | POLLERR | POLLHUP,
    };
    int ready;
    do {
        ready = poll(
            &descriptor,
            1,
            T1_MEDIA_HANDSHAKE_TIMEOUT_MS);
    } while (ready < 0 && errno == EINTR);
    if (ready <= 0) {
        if (ready == 0)
            errno = ETIMEDOUT;
        return -1;
    }

    struct t1_media_packet packet;
    if (t1_media_receive_packet(worker->socket_fd, &packet) != 1)
        return -1;
    return t1_media_accept_hello(
        worker,
        &packet,
        defer_capabilities);
}

static int
t1_media_worker_loop(struct t1_media_worker *worker)
{
    while (!t1_media_worker_stopping && !worker->stopping) {
        struct t1_media_packet packet;
        int received =
            t1_media_receive_packet(worker->socket_fd, &packet);
        if (received == 0)
            break;
        if (received < 0) {
            t1_media_send_error(
                worker->socket_fd,
                worker->session,
                0,
                worker->generation,
                T1_MEDIA_STATUS_INVALID_MESSAGE,
                "malformed T1MD packet");
            return 1;
        }

        const struct t1_media_message_header *header =
            t1_media_packet_header(&packet);
        if (header->type == T1_MEDIA_HELLO &&
            !worker->created &&
            worker->in_flight == 0) {
            if (t1_media_accept_hello(
                    worker,
                    &packet,
                    false) < 0)
                return 1;
            if (worker->debug) {
                fprintf(
                    stderr,
                    "T1_MEDIA_WORKER rehandshake session=%" PRIu64
                    "\n",
                    worker->session);
            }
            continue;
        }
        if (!t1_media_validate_session_header(worker, header)) {
            t1_media_packet_close_fds(&packet);
            t1_media_send_error(
                worker->socket_fd,
                worker->session,
                header ? header->request : 0,
                worker->generation,
                T1_MEDIA_STATUS_PROTOCOL_ERROR,
                "session, request, or generation is invalid");
            return 1;
        }
        if (header->request <= worker->last_request) {
            t1_media_packet_close_fds(&packet);
            t1_media_send_error(
                worker->socket_fd,
                worker->session,
                header->request,
                worker->generation,
                T1_MEDIA_STATUS_PROTOCOL_ERROR,
                "request identifiers must increase");
            return 1;
        }
        worker->last_request = header->request;
        worker->reset_interrupted = false;

        uint16_t watchdog_operation =
            t1_media_watchdog_operation(
                header->type);
        uint64_t watchdog_request =
            header->request;
        uint64_t watchdog_generation =
            header->generation;
        if (watchdog_operation !=
                T1_MEDIA_WATCHDOG_NONE &&
            t1_media_watchdog_begin(
                worker,
                watchdog_operation,
                watchdog_request,
                watchdog_generation) < 0) {
            t1_media_packet_close_fds(&packet);
            return 1;
        }

        int handler_result = 0;
        switch (header->type) {
        case T1_MEDIA_CREATE: {
            const struct t1_media_create *configuration =
                t1_media_packet_payload_const(&packet);
            struct t1_media_created created = {
                .status = T1_MEDIA_STATUS_PROTOCOL_ERROR,
                .maximum_decode_requests =
                    T1_MEDIA_MAX_DECODE_REQUESTS,
                .maximum_in_flight_frames =
                    T1_MEDIA_MAX_IN_FLIGHT_FRAMES,
            };
            if (packet.fd_count != 0 ||
                t1_media_packet_payload_size(&packet) <
                    sizeof(*configuration) ||
                worker->created ||
                header->generation <= worker->generation) {
                created.status = T1_MEDIA_STATUS_PROTOCOL_ERROR;
            } else {
                worker->generation = header->generation;
                created.status = t1_media_open_decoder(
                    worker,
                    configuration,
                    t1_media_packet_payload_size(&packet));
            }
            handler_result = t1_media_send_packet(
                worker->socket_fd,
                T1_MEDIA_CREATED,
                worker->session,
                header->request,
                worker->generation,
                &created,
                sizeof(created),
                NULL,
                0);
            if (worker->debug) {
                fprintf(
                    stderr,
                    "T1_MEDIA_WORKER create session=%" PRIu64
                    " generation=%" PRIu64 " status=%u\n",
                    worker->session,
                    worker->generation,
                    created.status);
            }
            break;
        }
        case T1_MEDIA_DECODE: {
            const struct t1_media_decode *input =
                t1_media_packet_payload_const(&packet);
            uint32_t status = T1_MEDIA_STATUS_PROTOCOL_ERROR;
            if (worker->created &&
                !worker->drained &&
                header->generation == worker->generation &&
                t1_media_packet_payload_size(&packet) ==
                    sizeof(*input) &&
                packet.fd_count == 1 &&
                worker->in_flight <
                    T1_MEDIA_MAX_IN_FLIGHT_FRAMES) {
                status = t1_media_decode_access_unit(
                    worker,
                    input,
                    packet.fds[0],
                    header->request);
            }
            t1_media_packet_close_fds(&packet);
            if (worker->reset_interrupted)
                break;
            struct t1_media_decode_done done = {
                .status = status,
            };
            handler_result = t1_media_send_packet(
                worker->socket_fd,
                T1_MEDIA_DECODE_DONE,
                worker->session,
                header->request,
                worker->generation,
                &done,
                sizeof(done),
                NULL,
                0);
            break;
        }
        case T1_MEDIA_RELEASE:
            if (t1_media_handle_release(worker, &packet) < 0) {
                t1_media_packet_close_fds(&packet);
                t1_media_send_error(
                    worker->socket_fd,
                    worker->session,
                    header->request,
                    worker->generation,
                    T1_MEDIA_STATUS_PROTOCOL_ERROR,
                    "invalid frame release");
                return 1;
            }
            break;
        case T1_MEDIA_FLUSH: {
            uint32_t status =
                worker->created &&
                header->generation == worker->generation &&
                packet.fd_count == 0 &&
                t1_media_packet_payload_size(&packet) == 0
                    ? t1_media_flush_decoder(
                        worker,
                        header->request)
                    : T1_MEDIA_STATUS_PROTOCOL_ERROR;
            if (worker->reset_interrupted)
                break;
            handler_result = t1_media_send_result(
                worker,
                T1_MEDIA_FLUSHED,
                header->request,
                status);
            break;
        }
        case T1_MEDIA_RESET: {
            uint32_t status = T1_MEDIA_STATUS_PROTOCOL_ERROR;
            if (worker->created &&
                header->generation == worker->generation + 1 &&
                packet.fd_count == 0 &&
                t1_media_packet_payload_size(&packet) == 0) {
                avcodec_flush_buffers(worker->codec);
                worker->generation = header->generation;
                worker->drained = false;
                status = T1_MEDIA_STATUS_OK;
            }
            handler_result = t1_media_send_result(
                worker,
                T1_MEDIA_RESET_DONE,
                header->request,
                status);
            break;
        }
        case T1_MEDIA_DESTROY: {
            uint32_t status =
                packet.fd_count == 0 &&
                t1_media_packet_payload_size(&packet) == 0 &&
                header->generation >= worker->generation &&
                worker->in_flight == 0
                    ? T1_MEDIA_STATUS_OK
                    : worker->in_flight != 0
                        ? T1_MEDIA_STATUS_RESOURCE_EXHAUSTED
                        : T1_MEDIA_STATUS_PROTOCOL_ERROR;
            if (status == T1_MEDIA_STATUS_OK) {
                worker->generation = header->generation;
                t1_media_close_decoder(worker);
            }
            handler_result = t1_media_send_result(
                worker,
                T1_MEDIA_DESTROY,
                header->request,
                status);
            break;
        }
        default:
            t1_media_packet_close_fds(&packet);
            t1_media_send_error(
                worker->socket_fd,
                worker->session,
                header->request,
                worker->generation,
                T1_MEDIA_STATUS_PROTOCOL_ERROR,
                "message type is not valid from a client");
            return 1;
        }
        t1_media_packet_close_fds(&packet);
        if (handler_result < 0)
            return 1;
        if (worker->stopping)
            return 1;
        if (watchdog_operation !=
                T1_MEDIA_WATCHDOG_NONE &&
            !worker->reset_interrupted) {
            if (!worker->watchdog_active ||
                t1_media_watchdog_complete(
                    worker,
                    watchdog_operation,
                    watchdog_request,
                    watchdog_generation) < 0)
                return 1;
        }
    }
    return 0;
}

static int
t1_media_backpressure_test_packet(
    int descriptor,
    uint16_t expected_type,
    uint64_t expected_request,
    uint64_t expected_generation,
    uint32_t expected_value,
    uint32_t expected_in_flight)
{
    struct t1_media_packet packet;
    if (t1_media_receive_packet(
            descriptor,
            &packet) != 1)
        return -1;
    const struct t1_media_message_header *header =
        t1_media_packet_header(&packet);
    bool valid =
        header &&
        header->type == expected_type &&
        header->request == expected_request &&
        header->generation == expected_generation &&
        packet.fd_count == 0;
    if (valid &&
        expected_type == T1_MEDIA_BACKPRESSURE) {
        const struct t1_media_backpressure *value =
            t1_media_packet_payload_const(&packet);
        valid =
            t1_media_packet_payload_size(&packet) ==
                sizeof(*value) &&
            value->state == expected_value &&
            value->in_flight_frames ==
                expected_in_flight;
    } else if (valid &&
               expected_type ==
                   T1_MEDIA_RESET_DONE) {
        const struct t1_media_result *value =
            t1_media_packet_payload_const(&packet);
        valid =
            t1_media_packet_payload_size(&packet) ==
                sizeof(*value) &&
            value->status == expected_value &&
            value->reserved == 0;
    }
    t1_media_packet_close_fds(&packet);
    return valid ? 0 : -1;
}

static int
t1_media_backpressure_test_watchdog(
    int descriptor,
    uint16_t expected_event,
    uint16_t expected_operation,
    uint64_t expected_request,
    uint64_t expected_generation)
{
    struct t1_media_watchdog_message message = {0};
    ssize_t received;
    do {
        received = recv(
            descriptor,
            &message,
            sizeof(message),
            0);
    } while (received < 0 && errno == EINTR);
    return received == (ssize_t)sizeof(message) &&
            message.magic == T1_MEDIA_WATCHDOG_MAGIC &&
            message.format == T1_MEDIA_WATCHDOG_FORMAT &&
            message.event == expected_event &&
            message.operation == expected_operation &&
            message.request == expected_request &&
            message.generation == expected_generation &&
            message.reserved16 == 0 &&
            message.reserved32 == 0
        ? 0
        : -1;
}

struct t1_media_output_pump_test {
    int received_frames;
    int delivered_frames;
    int waits;
    int terminal_result;
    uint64_t expected_request;
    AVFrame *retained_frame;
    bool retained_identity_proven;
    bool reset_interrupt;
};

static int
t1_media_output_pump_test_receive(
    struct t1_media_worker *worker,
    AVFrame *frame,
    void *context)
{
    (void)worker;
    struct t1_media_output_pump_test *test =
        context;
    if (test->received_frames >= 2)
        return test->terminal_result;
    frame->pts = test->received_frames;
    test->received_frames++;
    return 0;
}

static int
t1_media_output_pump_test_send(
    struct t1_media_worker *worker,
    AVFrame *frame,
    uint64_t request,
    void *context)
{
    (void)worker;
    struct t1_media_output_pump_test *test =
        context;
    if (request != test->expected_request)
        return AVERROR(EINVAL);
    if (frame->pts == 1 && test->waits == 0) {
        test->retained_frame = frame;
        return AVERROR(ENOBUFS);
    }
    if (frame->pts == 1) {
        if (frame != test->retained_frame)
            return AVERROR(EINVAL);
        test->retained_identity_proven = true;
    }
    test->delivered_frames++;
    av_frame_free(&frame);
    return 0;
}

static int
t1_media_output_pump_test_wait(
    struct t1_media_worker *worker,
    void *context)
{
    (void)worker;
    struct t1_media_output_pump_test *test =
        context;
    test->waits++;
    return test->reset_interrupt ? 1 : 0;
}

static int
t1_media_output_pump_self_test(void)
{
    struct t1_media_worker worker = {0};
    struct t1_media_output_pump_test decode = {
        .terminal_result = AVERROR(EAGAIN),
        .expected_request = 301,
    };
    int decode_result = t1_media_receive_frames_with(
        &worker,
        decode.expected_request,
        t1_media_output_pump_test_receive,
        t1_media_output_pump_test_send,
        t1_media_output_pump_test_wait,
        &decode);
    if (decode_result != AVERROR(EAGAIN) ||
        decode.received_frames != 2 ||
        decode.delivered_frames != 2 ||
        decode.waits != 1 ||
        !decode.retained_identity_proven)
        return -1;

    struct t1_media_output_pump_test flush = {
        .terminal_result = AVERROR_EOF,
        .expected_request = 302,
    };
    int flush_result = t1_media_receive_frames_with(
        &worker,
        flush.expected_request,
        t1_media_output_pump_test_receive,
        t1_media_output_pump_test_send,
        t1_media_output_pump_test_wait,
        &flush);
    if (flush_result != AVERROR_EOF ||
        flush.received_frames != 2 ||
        flush.delivered_frames != 2 ||
        flush.waits != 1 ||
        !flush.retained_identity_proven)
        return -1;

    struct t1_media_output_pump_test reset = {
        .terminal_result = AVERROR(EAGAIN),
        .expected_request = 303,
        .reset_interrupt = true,
    };
    int reset_result = t1_media_receive_frames_with(
        &worker,
        reset.expected_request,
        t1_media_output_pump_test_receive,
        t1_media_output_pump_test_send,
        t1_media_output_pump_test_wait,
        &reset);
    if (reset_result != AVERROR(ECANCELED) ||
        reset.received_frames != 2 ||
        reset.delivered_frames != 1 ||
        reset.waits != 1 ||
        !reset.retained_frame)
        return -1;
    return 0;
}

static int
t1_media_backpressure_self_test(void)
{
    if (T1_MEDIA_MAX_DECODE_REQUESTS != 1 ||
        t1_media_output_pump_self_test() < 0) {
        fprintf(
            stderr,
            "T1_MEDIA_WORKER backpressure-self-test-failed "
            "stage=output-pump\n");
        return 1;
    }
    int session[2] = {-1, -1};
    int watchdog[2] = {-1, -1};
    if (socketpair(
            AF_UNIX,
            SOCK_SEQPACKET | SOCK_CLOEXEC,
            0,
            session) < 0 ||
        socketpair(
            AF_UNIX,
            SOCK_SEQPACKET | SOCK_CLOEXEC | SOCK_NONBLOCK,
            0,
            watchdog) < 0) {
        fprintf(
            stderr,
            "T1_MEDIA_WORKER backpressure-self-test-failed "
            "stage=release-socket errno=%d\n",
            errno);
        if (session[0] >= 0)
            close(session[0]);
        if (session[1] >= 0)
            close(session[1]);
        return 1;
    }
    struct t1_media_worker release_worker = {
        .socket_fd = session[1],
        .watchdog_fd = watchdog[1],
        .session = 101,
        .last_request = 10,
        .generation = 1,
        .in_flight = T1_MEDIA_MAX_IN_FLIGHT_FRAMES,
        .created = true,
        .watchdog_active = true,
        .watchdog_operation = T1_MEDIA_WATCHDOG_DECODE,
        .watchdog_request = 10,
        .watchdog_generation = 1,
    };
    release_worker.slots[0].frame_id = 55;
    release_worker.slots[0].generation = 1;
    release_worker.slots[0].frame =
        av_frame_alloc();
    bool release_frame_ready =
        release_worker.slots[0].frame != NULL;
    for (unsigned object = 0;
         object < T1_MEDIA_MAX_FRAME_OBJECTS;
         ++object)
        release_worker.slots[0].fds[object] = -1;
    struct t1_media_release release = {
        .frame_id = 55,
    };
    int release_send_result =
        t1_media_send_packet(
            session[0],
            T1_MEDIA_RELEASE,
            release_worker.session,
            11,
            1,
            &release,
            sizeof(release),
            NULL,
            0);
    int release_wait_result =
        release_send_result < 0
            ? -1
            : t1_media_wait_for_backpressure_release(
                &release_worker);
    int release_enter_result =
        release_wait_result == 0
            ? t1_media_backpressure_test_packet(
                session[0],
                T1_MEDIA_BACKPRESSURE,
                10,
                1,
                T1_MEDIA_BACKPRESSURE_ENTER,
                T1_MEDIA_MAX_IN_FLIGHT_FRAMES)
            : -1;
    int release_exit_result =
        release_enter_result == 0
            ? t1_media_backpressure_test_packet(
                session[0],
                T1_MEDIA_BACKPRESSURE,
                10,
                1,
                T1_MEDIA_BACKPRESSURE_EXIT,
                T1_MEDIA_MAX_IN_FLIGHT_FRAMES - 1)
            : -1;
    int release_wait_watchdog =
        release_exit_result == 0
            ? t1_media_backpressure_test_watchdog(
                watchdog[0],
                T1_MEDIA_WATCHDOG_WAIT,
                T1_MEDIA_WATCHDOG_DECODE,
                10,
                1)
            : -1;
    int release_resume_watchdog =
        release_wait_watchdog == 0
            ? t1_media_backpressure_test_watchdog(
                watchdog[0],
                T1_MEDIA_WATCHDOG_RESUME,
                T1_MEDIA_WATCHDOG_DECODE,
                10,
                1)
            : -1;
    if (!release_frame_ready ||
        release_send_result < 0 ||
        release_wait_result != 0 ||
        release_worker.in_flight !=
            T1_MEDIA_MAX_IN_FLIGHT_FRAMES - 1 ||
        release_worker.slots[0].frame_id != 0 ||
        release_enter_result < 0 ||
        release_exit_result < 0 ||
        release_wait_watchdog < 0 ||
        release_resume_watchdog < 0) {
        fprintf(
            stderr,
            "T1_MEDIA_WORKER backpressure-self-test-failed "
            "stage=release-flow in_flight=%u frame=%" PRIu64
            " send=%d wait=%d enter=%d exit=%d "
            "watchdog_wait=%d watchdog_resume=%d errno=%d\n",
            release_worker.in_flight,
            release_worker.slots[0].frame_id,
            release_send_result,
            release_wait_result,
            release_enter_result,
            release_exit_result,
            release_wait_watchdog,
            release_resume_watchdog,
            errno);
        t1_media_release_all(&release_worker);
        close(session[0]);
        close(session[1]);
        close(watchdog[0]);
        close(watchdog[1]);
        return 1;
    }
    close(session[0]);
    close(session[1]);
    close(watchdog[0]);
    close(watchdog[1]);

    int reset_session[2] = {-1, -1};
    int reset_watchdog[2] = {-1, -1};
    const AVCodec *codec =
        avcodec_find_decoder(AV_CODEC_ID_H264);
    AVCodecContext *context =
        codec ? avcodec_alloc_context3(codec) : NULL;
    if (socketpair(
            AF_UNIX,
            SOCK_SEQPACKET | SOCK_CLOEXEC,
            0,
            reset_session) < 0 ||
        socketpair(
            AF_UNIX,
            SOCK_SEQPACKET | SOCK_CLOEXEC | SOCK_NONBLOCK,
            0,
            reset_watchdog) < 0 ||
        !context ||
        avcodec_open2(context, codec, NULL) < 0) {
        fprintf(
            stderr,
            "T1_MEDIA_WORKER backpressure-self-test-failed "
            "stage=reset-setup codec=%u context=%u errno=%d\n",
            codec ? 1u : 0u,
            context ? 1u : 0u,
            errno);
        if (reset_session[0] >= 0)
            close(reset_session[0]);
        if (reset_session[1] >= 0)
            close(reset_session[1]);
        if (reset_watchdog[0] >= 0)
            close(reset_watchdog[0]);
        if (reset_watchdog[1] >= 0)
            close(reset_watchdog[1]);
        avcodec_free_context(&context);
        return 1;
    }
    struct t1_media_worker reset_worker = {
        .socket_fd = reset_session[1],
        .watchdog_fd = reset_watchdog[1],
        .session = 202,
        .last_request = 20,
        .generation = 1,
        .in_flight = T1_MEDIA_MAX_IN_FLIGHT_FRAMES,
        .created = true,
        .codec = context,
        .watchdog_active = true,
        .watchdog_operation = T1_MEDIA_WATCHDOG_DECODE,
        .watchdog_request = 20,
        .watchdog_generation = 1,
    };
    if (t1_media_send_packet(
            reset_session[0],
            T1_MEDIA_RESET,
            reset_worker.session,
            21,
            2,
            NULL,
            0,
            NULL,
            0) < 0 ||
        t1_media_wait_for_backpressure_release(
            &reset_worker) != 1 ||
        !reset_worker.reset_interrupted ||
        reset_worker.generation != 2 ||
        reset_worker.last_request != 21 ||
        reset_worker.watchdog_active ||
        t1_media_backpressure_test_packet(
            reset_session[0],
            T1_MEDIA_BACKPRESSURE,
            20,
            1,
            T1_MEDIA_BACKPRESSURE_ENTER,
            T1_MEDIA_MAX_IN_FLIGHT_FRAMES) < 0 ||
        t1_media_backpressure_test_packet(
            reset_session[0],
            T1_MEDIA_RESET_DONE,
            21,
            2,
            T1_MEDIA_STATUS_OK,
            0) < 0 ||
        t1_media_backpressure_test_watchdog(
            reset_watchdog[0],
            T1_MEDIA_WATCHDOG_WAIT,
            T1_MEDIA_WATCHDOG_DECODE,
            20,
            1) < 0 ||
        t1_media_backpressure_test_watchdog(
            reset_watchdog[0],
            T1_MEDIA_WATCHDOG_RESUME,
            T1_MEDIA_WATCHDOG_DECODE,
            20,
            1) < 0 ||
        t1_media_backpressure_test_watchdog(
            reset_watchdog[0],
            T1_MEDIA_WATCHDOG_COMPLETE,
            T1_MEDIA_WATCHDOG_DECODE,
            20,
            1) < 0 ||
        t1_media_backpressure_test_watchdog(
            reset_watchdog[0],
            T1_MEDIA_WATCHDOG_BEGIN,
            T1_MEDIA_WATCHDOG_RESET,
            21,
            2) < 0 ||
        t1_media_backpressure_test_watchdog(
            reset_watchdog[0],
            T1_MEDIA_WATCHDOG_COMPLETE,
            T1_MEDIA_WATCHDOG_RESET,
            21,
            2) < 0) {
        fprintf(
            stderr,
            "T1_MEDIA_WORKER backpressure-self-test-failed "
            "stage=reset-flow interrupted=%u generation=%" PRIu64
            " last_request=%" PRIu64 " watchdog_active=%u errno=%d\n",
            reset_worker.reset_interrupted ? 1u : 0u,
            reset_worker.generation,
            reset_worker.last_request,
            reset_worker.watchdog_active ? 1u : 0u,
            errno);
        avcodec_free_context(&reset_worker.codec);
        close(reset_session[0]);
        close(reset_session[1]);
        close(reset_watchdog[0]);
        close(reset_watchdog[1]);
        return 1;
    }
    unsigned char unexpected = 0;
    errno = 0;
    if (recv(
            reset_session[0],
            &unexpected,
            sizeof(unexpected),
            MSG_DONTWAIT) >= 0 ||
        (errno != EAGAIN &&
         errno != EWOULDBLOCK)) {
        avcodec_free_context(&reset_worker.codec);
        close(reset_session[0]);
        close(reset_session[1]);
        close(reset_watchdog[0]);
        close(reset_watchdog[1]);
        return 1;
    }
    avcodec_free_context(&reset_worker.codec);
    close(reset_session[0]);
    close(reset_session[1]);
    close(reset_watchdog[0]);
    close(reset_watchdog[1]);
    puts(
        "T1MD backpressure self-test passed "
        "maximum_decode_requests=1 multi_frame_decode=lossless "
        "multi_frame_flush=lossless retained_identity=proven "
        "enter_release_exit=proven passive_wait_timeout=none "
        "reset_interrupt=proven reset_done_cancels_enter "
        "reset_exit=omitted old_terminal=omitted");
    return 0;
}

static int
t1_media_worker_main(int socket_fd,
                     int capabilities_fd,
                     int watchdog_fd,
                     const char *device_path,
                     bool debug,
                     unsigned landlock_abi)
{
    t1_media_worker_socket = socket_fd;
    struct t1_media_worker worker = {
        .socket_fd = socket_fd,
        .watchdog_fd = watchdog_fd,
        .device_path = device_path,
        .debug = debug,
    };
    for (unsigned index = 0;
         index < T1_MEDIA_MAX_IN_FLIGHT_FRAMES;
         ++index) {
        for (unsigned object = 0;
             object < T1_MEDIA_MAX_FRAME_OBJECTS;
             ++object)
            worker.slots[index].fds[object] = -1;
    }
    if (t1_media_read_all(
            capabilities_fd,
            &worker.capabilities,
            sizeof(worker.capabilities)) < 0 ||
        worker.capabilities.profile_count >
            T1_MEDIA_MAX_PROFILES ||
        worker.capabilities.maximum_in_flight_frames !=
            T1_MEDIA_MAX_IN_FLIGHT_FRAMES ||
        !(worker.capabilities.features & T1_MEDIA_FEATURE_DMABUF) ||
        !(worker.capabilities.features &
          T1_MEDIA_FEATURE_LINEAR_MEMORY_OUTPUT)) {
        fprintf(stderr, "T1_MEDIA_WORKER invalid capability cache\n");
        return 1;
    }
    close(capabilities_fd);

    /*
     * Browser-side GPU initialization can retry several child processes in
     * quick succession.  Authenticate the inherited connection before opening
     * VA-API/NVDEC so an abandoned broker socket is reaped immediately instead
     * of occupying a decoder slot for the duration of NVIDIA initialization.
     * Only the fixed-size HELLO is consumed at this point.  CAPABILITIES is
     * deferred until after the device is open and seccomp is installed, so the
     * browser cannot submit any compressed media to an unsandboxed worker.
     */
    if (t1_media_watchdog_notify(
            &worker,
            T1_MEDIA_WATCHDOG_READY,
            T1_MEDIA_WATCHDOG_NONE,
            0,
            0) < 0)
        return 1;
    if (t1_media_handshake(&worker, true) < 0) {
        if (debug) {
            fprintf(
                stderr,
                "T1_MEDIA_WORKER preauthentication-discard "
                "error=%s\n",
                strerror(errno));
        }
        return 1;
    }
    int hardware_result = av_hwdevice_ctx_create(
        &worker.device,
        AV_HWDEVICE_TYPE_VAAPI,
        worker.device_path,
        NULL,
        0);
    if (hardware_result < 0 && debug) {
        char detail[AV_ERROR_MAX_STRING_SIZE] = {0};
        av_strerror(
            hardware_result,
            detail,
            sizeof(detail));
        fprintf(
            stderr,
            "T1_MEDIA_WORKER device-preinitialization-failed "
            "device=%s error=%s\n",
            worker.device_path,
            detail);
    }
    if (t1_media_install_worker_seccomp() < 0) {
        fprintf(
            stderr,
            "T1_MEDIA_WORKER sandbox-failed stage=seccomp "
            "error=%s\n",
            strerror(errno));
        av_buffer_unref(&worker.device);
        return 77;
    }
    if (debug) {
        fprintf(
            stderr,
            "T1_MEDIA_WORKER sandbox=ready landlock_abi=%u "
            "landlock_fs=all-through-ioctl-dev "
            "seccomp=filter seccomp_tsync=1 "
            "worker_uid=%lu worker_gid=%lu "
            "device_preinitialized=%u "
            "rlimit_core=%llu rlimit_fsize=%llu "
            "rlimit_nofile=%llu rlimit_nproc=%llu\n",
            landlock_abi,
            (unsigned long)geteuid(),
            (unsigned long)getegid(),
            worker.device ? 1u : 0u,
            T1_MEDIA_WORKER_RLIMIT_CORE,
            T1_MEDIA_WORKER_RLIMIT_FSIZE,
            T1_MEDIA_WORKER_RLIMIT_NOFILE,
            T1_MEDIA_WORKER_RLIMIT_NPROC);
    }

    if (t1_media_finish_hello(&worker) < 0) {
        av_buffer_unref(&worker.device);
        return 1;
    }
    if (debug) {
        fprintf(
            stderr,
            "T1_MEDIA_WORKER handshake session=%" PRIu64 "\n",
            worker.session);
    }

    int result = t1_media_worker_loop(&worker);
    bool cleanup_armed = false;
    if (worker.watchdog_active &&
        worker.watchdog_waiting &&
        t1_media_watchdog_resume(&worker) < 0) {
        result = 1;
        goto close_descriptors;
    }
    if (!worker.watchdog_active) {
        if (t1_media_watchdog_begin(
                &worker,
                T1_MEDIA_WATCHDOG_CLEANUP,
                worker.last_request,
                worker.generation) < 0) {
            result = 1;
            goto close_descriptors;
        }
        cleanup_armed = true;
    }
    t1_media_close_decoder(&worker);
    t1_media_release_all(&worker);
    av_buffer_unref(&worker.device);
    if (cleanup_armed) {
        if (t1_media_watchdog_complete(
                &worker,
                T1_MEDIA_WATCHDOG_CLEANUP,
                worker.last_request,
                worker.generation) < 0 ||
            t1_media_watchdog_notify(
                &worker,
                T1_MEDIA_WATCHDOG_EXITING,
                T1_MEDIA_WATCHDOG_NONE,
                0,
                0) < 0)
            result = 1;
    }
close_descriptors:
    if (t1_media_worker_socket >= 0) {
        close(socket_fd);
        t1_media_worker_socket = -1;
    }
    close(watchdog_fd);
    if (debug) {
        fprintf(
            stderr,
            "T1_MEDIA_WORKER stopped session=%" PRIu64
            " result=%d\n",
            worker.session,
            result);
    }
    return result;
}

int
main(int argc, char **argv)
{
    /*
     * Linux resets dumpability across exec for an ordinary executable.  Close
     * that post-exec window before parsing any untrusted configuration.
     */
    if (prctl(PR_SET_DUMPABLE, 0, 0, 0, 0) < 0)
        return 77;
    setvbuf(stderr, NULL, _IOLBF, 0);
    bool debug =
        t1_media_has_argument(argc, argv, "--debug") ||
        t1_media_environment_true("T1OS_MEDIA_DECODE_DEBUG");
    if (t1_media_has_argument(
            argc,
            argv,
            "--backpressure-self-test"))
        return t1_media_backpressure_self_test();
    if (t1_media_has_argument(
            argc,
            argv,
            "--capability-contract-self-test"))
        return t1_media_capability_contract_self_test();
    const char *device_path =
        t1_media_argument(argc, argv, "--device");
    if (!device_path || device_path[0] != '/') {
        fprintf(stderr, "--device must be an absolute path\n");
        return 64;
    }
    unsigned maximum_sessions = t1_media_parse_sessions(
        t1_media_argument(argc, argv, "--maximum-sessions"));
    if (!maximum_sessions) {
        fprintf(stderr, "invalid --maximum-sessions\n");
        return 64;
    }
    unsigned long expected_uid = 0;
    unsigned long expected_gid = 0;
    unsigned long expected_parent = 0;
    if (t1_media_parse_identity(
            t1_media_argument(argc, argv, "--expected-uid"),
            UINT32_MAX,
            &expected_uid) < 0 ||
        t1_media_parse_identity(
            t1_media_argument(argc, argv, "--expected-gid"),
            UINT32_MAX,
            &expected_gid) < 0 ||
        t1_media_parse_identity(
            t1_media_argument(argc, argv, "--expected-parent"),
            INT32_MAX,
            &expected_parent) < 0 ||
        t1_media_verify_worker_privileges(
            (uid_t)expected_uid,
            (gid_t)expected_gid,
            (pid_t)expected_parent) < 0) {
        fprintf(
            stderr,
            "T1_MEDIA_WORKER refused unsafe identity "
            "uid=%lu gid=%lu parent=%lu\n",
            (unsigned long)geteuid(),
            (unsigned long)getegid(),
            (unsigned long)getppid());
        return 77;
    }

    unsigned landlock_abi = 0;
    if (t1_media_install_worker_landlock(
            &landlock_abi) < 0) {
        fprintf(
            stderr,
            "T1_MEDIA_WORKER sandbox-failed stage=landlock "
            "error=%s\n",
            strerror(errno));
        return 77;
    }

    if (t1_media_has_argument(argc, argv, "--probe")) {
        int output_fd = t1_media_parse_descriptor(
            t1_media_argument(argc, argv, "--probe-fd"));
        return t1_media_probe_main(
            device_path,
            maximum_sessions,
            output_fd,
            landlock_abi,
            debug);
    }

    int socket_fd = t1_media_parse_descriptor(
        t1_media_argument(argc, argv, "--session-fd"));
    int capabilities_fd = t1_media_parse_descriptor(
        t1_media_argument(argc, argv, "--capabilities-fd"));
    int watchdog_fd = t1_media_parse_descriptor(
        t1_media_argument(argc, argv, "--watchdog-fd"));
    if (socket_fd < 0 ||
        capabilities_fd < 0 ||
        watchdog_fd < 0 ||
        socket_fd == capabilities_fd ||
        socket_fd == watchdog_fd ||
        capabilities_fd == watchdog_fd ||
        t1_media_validate_watchdog_descriptor(
            watchdog_fd) < 0) {
        fprintf(
            stderr,
            "--session-fd, --capabilities-fd, and a nonblocking "
            "SOCK_SEQPACKET --watchdog-fd are required\n");
        return 64;
    }

    struct sigaction action = {
        .sa_handler = t1_media_worker_signal,
    };
    sigemptyset(&action.sa_mask);
    sigaction(SIGINT, &action, NULL);
    sigaction(SIGTERM, &action, NULL);
    signal(SIGPIPE, SIG_IGN);
    av_log_set_level(debug ? AV_LOG_VERBOSE : AV_LOG_WARNING);

    return t1_media_worker_main(
        socket_fd,
        capabilities_fd,
        watchdog_fd,
        device_path,
        debug,
        landlock_abi);
}
