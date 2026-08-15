#ifndef T1_MEDIA_DECODE_PROTOCOL_H
#define T1_MEDIA_DECODE_PROTOCOL_H

/*
 * T1OS native media decode protocol, version 1.
 *
 * The transport is AF_UNIX/SOCK_SEQPACKET.  Every packet contains exactly one
 * t1_media_message_header followed by the payload for its type.  Header.size
 * is the total packet size, including the header.  All integer fields are
 * little-endian.  Version 1 is intentionally restricted to little-endian
 * hosts; peers must reject a byte-swapped magic instead of guessing.
 *
 * Compressed access units are supplied in one immutable, sealed memfd attached
 * to T1_MEDIA_DECODE.  Hardware-decoded 4:2:0 DMA-BUF frames use the
 * T1_MEDIA_FRAME_SEPARATE_LAYERS topology: one luma layer/object and one chroma
 * layer/object, with each object's natural DRM modifier carried independently.
 * The v1 service does not synthesize a common modifier and does not fall back
 * to a composed allocation.  Object descriptors are attached to T1_MEDIA_FRAME
 * in object-array order.  A client requiring
 * T1_MEDIA_FEATURE_LINEAR_MEMORY_OUTPUT instead receives one sealed, read-only
 * linear memfd so a non-GPU compositor can present hardware-decoded frames
 * without attempting to mmap a driver surface.  File descriptors use
 * SCM_RIGHTS and are never encoded as integer values in the payload.
 *
 * A connection carries one decoder at a time and is reusable.  The client
 * sends HELLO promptly after receiving its preconnected descriptor, receives
 * CAPABILITIES and may then keep the connection idle indefinitely.  CREATE
 * selects a new monotonically increasing non-zero generation.  After every
 * FRAME has been RELEASEd, DESTROY tears down that decoder and is acknowledged
 * with T1_MEDIA_DESTROY carrying t1_media_result.  The connection may then
 * either CREATE a later generation directly or send HELLO again.  Re-HELLO
 * assigns a new non-zero session, resets generation to zero, and is the
 * recommended way to return a descriptor to Chromium's idle connection pool.
 *
 * FLUSH drains the codec to end-of-stream and is acknowledged by FLUSHED with
 * t1_media_result.  No further DECODE is accepted until RESET.  RESET uses the
 * next generation and is acknowledged by RESET_DONE with t1_media_result.
 * Frames from older generations remain valid until their matching RELEASE.
 * Every client request, including one-way RELEASE, uses a connection-unique,
 * monotonically increasing non-zero header.request value.  Replies echo that
 * value.  FRAME uses the DECODE/FLUSH request which produced the frame.
 *
 * Exactly one DECODE or FLUSH may be outstanding.  If all exported frame slots
 * are occupied while that operation has another decoded frame, the service
 * sends BACKPRESSURE ENTER for the operation, retains the undelivered frame,
 * and accepts only RELEASE or a next-generation RESET.  After RELEASE frees a
 * slot, BACKPRESSURE EXIT reports the post-release count and precedes resumed
 * codec/GPU work.  Clients pause operation timeouts between ENTER and EXIT
 * while continuing to RELEASE frames.  An interrupting RESET emits no EXIT:
 * RESET_DONE cancels ENTER and the client's paused timeout state, while RESET
 * advances generation and omits the old operation's terminal
 * DECODE_DONE/FLUSHED reply.
 */

#include <stdint.h>

#define T1_MEDIA_PROTOCOL_MAGIC UINT32_C(0x444d3154) /* "T1MD" on the wire. */
#define T1_MEDIA_PROTOCOL_VERSION UINT16_C(1)

#define T1_MEDIA_MAX_CONTROL_BYTES UINT32_C(65536)
#define T1_MEDIA_MAX_ENCODED_BYTES UINT32_C(16777216)
#define T1_MEDIA_MAX_EXTRADATA_BYTES UINT32_C(32768)
#define T1_MEDIA_MAX_PROFILES UINT32_C(48)
#define T1_MEDIA_MAX_IMPORT_FOURCC UINT32_C(8)
#define T1_MEDIA_MAX_FRAME_OBJECTS UINT32_C(4)
#define T1_MEDIA_MAX_FRAME_LAYERS UINT32_C(2)
#define T1_MEDIA_MAX_PLANES_PER_LAYER UINT32_C(4)
#define T1_MEDIA_MAX_IN_FLIGHT_FRAMES UINT32_C(16)
#define T1_MEDIA_MAX_DECODE_REQUESTS UINT32_C(1)
#define T1_MEDIA_MAX_ERROR_TEXT UINT32_C(512)
#define T1_MEDIA_VENDOR_BYTES UINT32_C(128)

#define T1_MEDIA_DRM_FOURCC(a, b, c, d) \
    ((uint32_t)(a) | ((uint32_t)(b) << 8) | \
     ((uint32_t)(c) << 16) | ((uint32_t)(d) << 24))
#define T1_MEDIA_DRM_FORMAT_R8 \
    T1_MEDIA_DRM_FOURCC('R', '8', ' ', ' ')
#define T1_MEDIA_DRM_FORMAT_R16 \
    T1_MEDIA_DRM_FOURCC('R', '1', '6', ' ')
#define T1_MEDIA_DRM_FORMAT_GR88 \
    T1_MEDIA_DRM_FOURCC('G', 'R', '8', '8')
#define T1_MEDIA_DRM_FORMAT_GR1616 \
    T1_MEDIA_DRM_FOURCC('G', 'R', '3', '2')
#define T1_MEDIA_DRM_FORMAT_RG88 \
    T1_MEDIA_DRM_FOURCC('R', 'G', '8', '8')
#define T1_MEDIA_DRM_FORMAT_RG1616 \
    T1_MEDIA_DRM_FOURCC('R', 'G', '3', '2')
#define T1_MEDIA_DRM_FORMAT_NV12 \
    T1_MEDIA_DRM_FOURCC('N', 'V', '1', '2')
#define T1_MEDIA_DRM_FORMAT_P010 \
    T1_MEDIA_DRM_FOURCC('P', '0', '1', '0')

enum t1_media_message_type {
    T1_MEDIA_HELLO = 1,
    T1_MEDIA_CAPABILITIES = 2,
    T1_MEDIA_CREATE = 3,
    T1_MEDIA_CREATED = 4,
    T1_MEDIA_DECODE = 5,
    T1_MEDIA_DECODE_DONE = 6,
    T1_MEDIA_FRAME = 7,
    T1_MEDIA_RELEASE = 8,
    T1_MEDIA_FLUSH = 9,
    T1_MEDIA_FLUSHED = 10,
    T1_MEDIA_RESET = 11,
    T1_MEDIA_RESET_DONE = 12,
    T1_MEDIA_DESTROY = 13,
    T1_MEDIA_ERROR = 14,
    T1_MEDIA_BACKPRESSURE = 15,
};

enum t1_media_status {
    T1_MEDIA_STATUS_OK = 0,
    T1_MEDIA_STATUS_INVALID_MESSAGE = 1,
    T1_MEDIA_STATUS_UNSUPPORTED_VERSION = 2,
    T1_MEDIA_STATUS_UNAUTHENTICATED = 3,
    T1_MEDIA_STATUS_BUSY = 4,
    T1_MEDIA_STATUS_UNSUPPORTED_CODEC = 5,
    T1_MEDIA_STATUS_UNSUPPORTED_PROFILE = 6,
    T1_MEDIA_STATUS_UNSUPPORTED_CONFIGURATION = 7,
    T1_MEDIA_STATUS_HARDWARE_UNAVAILABLE = 8,
    T1_MEDIA_STATUS_DECODE_ERROR = 9,
    T1_MEDIA_STATUS_RESOURCE_EXHAUSTED = 10,
    T1_MEDIA_STATUS_PROTOCOL_ERROR = 11,
    T1_MEDIA_STATUS_SERVICE_STOPPING = 12,
    T1_MEDIA_STATUS_INTERNAL_ERROR = 13,
};

enum t1_media_codec {
    T1_MEDIA_CODEC_UNKNOWN = 0,
    T1_MEDIA_CODEC_H264 = 1,
    T1_MEDIA_CODEC_VP8 = 2,
    T1_MEDIA_CODEC_VP9 = 3,
    T1_MEDIA_CODEC_HEVC = 4,
    T1_MEDIA_CODEC_AV1 = 5,
    T1_MEDIA_CODEC_MPEG2 = 6,
};

enum t1_media_profile {
    T1_MEDIA_PROFILE_UNKNOWN = 0,
    T1_MEDIA_PROFILE_H264_BASELINE = 1,
    T1_MEDIA_PROFILE_H264_MAIN = 2,
    T1_MEDIA_PROFILE_H264_HIGH = 3,
    T1_MEDIA_PROFILE_VP8_ANY = 10,
    T1_MEDIA_PROFILE_VP9_0 = 20,
    T1_MEDIA_PROFILE_VP9_1 = 21,
    T1_MEDIA_PROFILE_VP9_2 = 22,
    T1_MEDIA_PROFILE_VP9_3 = 23,
    T1_MEDIA_PROFILE_HEVC_MAIN = 30,
    T1_MEDIA_PROFILE_HEVC_MAIN10 = 31,
    T1_MEDIA_PROFILE_AV1_MAIN = 40,
    T1_MEDIA_PROFILE_MPEG2_SIMPLE = 50,
    T1_MEDIA_PROFILE_MPEG2_MAIN = 51,
};

enum t1_media_pixel_format {
    T1_MEDIA_PIXEL_FORMAT_UNKNOWN = 0,
    T1_MEDIA_PIXEL_FORMAT_NV12 = 1,
    T1_MEDIA_PIXEL_FORMAT_P010 = 2,
    T1_MEDIA_PIXEL_FORMAT_P012 = 3,
};

enum t1_media_chroma_subsampling {
    T1_MEDIA_CHROMA_UNKNOWN = 0,
    T1_MEDIA_CHROMA_420 = 1,
    T1_MEDIA_CHROMA_422 = 2,
    T1_MEDIA_CHROMA_444 = 3,
};

/*
 * color_primaries, color_transfer and color_matrix carry the corresponding
 * unsigned ISO/IEC 23091-2 (H.273) code point.  Zero means unspecified.
 * Values are not Chromium or FFmpeg enum ordinals even where those enums
 * currently use the same numeric assignments.
 */
enum t1_media_color_range {
    T1_MEDIA_COLOR_RANGE_UNSPECIFIED = 0,
    T1_MEDIA_COLOR_RANGE_LIMITED = 1,
    T1_MEDIA_COLOR_RANGE_FULL = 2,
};

enum t1_media_chroma_location {
    T1_MEDIA_CHROMA_LOCATION_UNSPECIFIED = 0,
    T1_MEDIA_CHROMA_LOCATION_LEFT = 1,
    T1_MEDIA_CHROMA_LOCATION_CENTER = 2,
    T1_MEDIA_CHROMA_LOCATION_TOP_LEFT = 3,
    T1_MEDIA_CHROMA_LOCATION_TOP = 4,
    T1_MEDIA_CHROMA_LOCATION_BOTTOM_LEFT = 5,
    T1_MEDIA_CHROMA_LOCATION_BOTTOM = 6,
};

enum t1_media_feature {
    T1_MEDIA_FEATURE_DMABUF = UINT32_C(1) << 0,
    T1_MEDIA_FEATURE_DRM_MODIFIERS = UINT32_C(1) << 1,
    T1_MEDIA_FEATURE_RESET = UINT32_C(1) << 2,
    T1_MEDIA_FEATURE_RELEASE_FENCE = UINT32_C(1) << 3,
    T1_MEDIA_FEATURE_PER_SESSION_WORKER = UINT32_C(1) << 4,
    T1_MEDIA_FEATURE_SEALED_INPUT = UINT32_C(1) << 5,
    T1_MEDIA_FEATURE_BACKPRESSURE = UINT32_C(1) << 6,
    T1_MEDIA_FEATURE_LINEAR_MEMORY_OUTPUT = UINT32_C(1) << 7,
};

enum t1_media_backpressure_state {
    T1_MEDIA_BACKPRESSURE_ENTER = 1,
    T1_MEDIA_BACKPRESSURE_EXIT = 2,
};

enum t1_media_bit_depth {
    T1_MEDIA_BIT_DEPTH_8 = UINT32_C(1) << 0,
    T1_MEDIA_BIT_DEPTH_10 = UINT32_C(1) << 1,
    /* Reserved for a later protocol capability; v1 workers do not advertise. */
    T1_MEDIA_BIT_DEPTH_12 = UINT32_C(1) << 2,
};

enum t1_media_output_format {
    T1_MEDIA_OUTPUT_NV12 = UINT32_C(1) << 0,
    T1_MEDIA_OUTPUT_P010 = UINT32_C(1) << 1,
    /* Reserved for a later protocol capability; v1 workers do not advertise. */
    T1_MEDIA_OUTPUT_P012 = UINT32_C(1) << 2,
};

enum t1_media_create_flag {
    T1_MEDIA_CREATE_LOW_DELAY = UINT32_C(1) << 0,
    T1_MEDIA_CREATE_ENCRYPTED = UINT32_C(1) << 1,
};

enum t1_media_decode_flag {
    T1_MEDIA_DECODE_KEYFRAME = UINT32_C(1) << 0,
    T1_MEDIA_DECODE_DISCONTINUITY = UINT32_C(1) << 1,
};

enum t1_media_frame_flag {
    T1_MEDIA_FRAME_SYNCHRONIZED = UINT32_C(1) << 0,
    T1_MEDIA_FRAME_INTERLACED = UINT32_C(1) << 1,
    T1_MEDIA_FRAME_TOP_FIELD_FIRST = UINT32_C(1) << 2,
    T1_MEDIA_FRAME_SEPARATE_LAYERS = UINT32_C(1) << 3,
    T1_MEDIA_FRAME_LINEAR_MEMORY = UINT32_C(1) << 4,
};

enum t1_media_release_flag {
    /*
     * One sync-file FD accompanies RELEASE.  The worker waits for it before
     * returning the native surface to the decoder.  A release sent after the
     * Chromium SharedImage sync token has completed should omit this flag.
     */
    T1_MEDIA_RELEASE_HAS_FENCE = UINT32_C(1) << 0,
};

#if defined(_MSC_VER)
#pragma pack(push, 1)
#define T1_MEDIA_PACKED
#else
#define T1_MEDIA_PACKED __attribute__((packed))
#endif

struct T1_MEDIA_PACKED t1_media_message_header {
    uint32_t magic;
    uint16_t version;
    uint16_t type;
    uint32_t size;
    uint64_t session;
    uint64_t request;
    uint64_t generation;
    uint32_t flags;
};

struct T1_MEDIA_PACKED t1_media_hello {
    uint16_t minimum_version;
    uint16_t maximum_version;
    uint32_t required_features;
    uint32_t maximum_frame_objects;
    uint32_t maximum_frame_layers;
    uint32_t maximum_planes_per_layer;
    uint32_t reserved;
};

struct T1_MEDIA_PACKED t1_media_capability_profile {
    uint32_t codec;
    uint32_t profile;
    uint32_t bit_depths;
    uint32_t output_formats;
    uint32_t minimum_width;
    uint32_t minimum_height;
    uint32_t maximum_width;
    uint32_t maximum_height;
};

struct T1_MEDIA_PACKED t1_media_capabilities {
    uint32_t features;
    uint32_t maximum_sessions;
    uint32_t maximum_decode_requests;
    uint32_t maximum_in_flight_frames;
    uint32_t maximum_encoded_bytes;
    uint32_t maximum_extradata_bytes;
    uint32_t profile_count;
    uint32_t reserved;
    char vendor[T1_MEDIA_VENDOR_BYTES];
    struct t1_media_capability_profile profiles[T1_MEDIA_MAX_PROFILES];
};

struct T1_MEDIA_PACKED t1_media_create {
    uint32_t codec;
    uint32_t profile;
    uint32_t coded_width;
    uint32_t coded_height;
    uint32_t visible_x;
    uint32_t visible_y;
    uint32_t visible_width;
    uint32_t visible_height;
    /*
     * 8 or 10 for profiles with a fixed browser-visible depth. Zero is allowed
     * only for AV1 Main and means that the worker must accept an actual 8- or
     * 10-bit decoded frame within the advertised capability mask, deriving the
     * exact depth from that frame and rejecting every other output format.
     */
    uint32_t bit_depth;
    uint32_t chroma_subsampling;
    uint32_t color_primaries;
    uint32_t color_transfer;
    uint32_t color_matrix;
    uint32_t color_range;
    uint32_t flags;
    uint32_t extradata_size;
    uint32_t import_fourcc_count;
    /*
     * Exact separate-layer DRM formats the Chromium importer supports, not
     * merely the logical decoded pixel format.  An NV12 importer advertises R8
     * and both RG88/GR88 component-order spellings; a P010 importer advertises
     * R16 and both RG1616/GR1616 spellings.  The worker rejects a composed
     * export and rejects any layer whose fourcc is absent from this list.
     * FRAME always reports the exact format and object modifier of each layer.
     */
    uint32_t import_fourcc[T1_MEDIA_MAX_IMPORT_FOURCC];
    /*
     * Exactly extradata_size bytes follow this structure.  Bitstream framing
     * is passed through from Chromium without conversion:
     *
     * - H.264 uses length-prefixed access units when extradata is an
     *   AVCDecoderConfigurationRecord, otherwise Annex-B.
     * - HEVC uses length-prefixed access units when extradata is an
     *   HEVCDecoderConfigurationRecord, otherwise Annex-B.
     * - VP8/VP9 carries one Chromium DecoderBuffer frame (VP9 superframes are
     *   retained intact).
     * - AV1 carries the DecoderBuffer temporal unit/OBUs with av1C extradata
     *   when supplied.
     *
     * Consequently Chromium's T1OS decoder reports
     * NeedsBitstreamConversion() == false.
     */
};

struct T1_MEDIA_PACKED t1_media_created {
    uint32_t status;
    uint32_t maximum_decode_requests;
    uint32_t maximum_in_flight_frames;
    uint32_t reserved;
};

struct T1_MEDIA_PACKED t1_media_decode {
    int64_t timestamp_ns;
    int64_t duration_ns;
    uint64_t data_offset;
    uint32_t data_size;
    uint32_t flags;
    /* Exactly one immutable sealed memfd accompanies this message. */
};

struct T1_MEDIA_PACKED t1_media_decode_done {
    uint32_t status;
    uint32_t reserved;
};

struct T1_MEDIA_PACKED t1_media_frame_object {
    uint64_t size;
    uint64_t modifier;
};

struct T1_MEDIA_PACKED t1_media_frame_plane {
    uint32_t object_index;
    uint32_t offset;
    uint32_t pitch;
    uint32_t reserved;
};

struct T1_MEDIA_PACKED t1_media_frame_layer {
    uint32_t drm_fourcc;
    uint32_t width;
    uint32_t height;
    uint32_t plane_count;
    struct t1_media_frame_plane planes[T1_MEDIA_MAX_PLANES_PER_LAYER];
};

struct T1_MEDIA_PACKED t1_media_frame {
    uint64_t frame_id;
    int64_t timestamp_ns;
    int64_t duration_ns;
    uint32_t coded_width;
    uint32_t coded_height;
    uint32_t visible_x;
    uint32_t visible_y;
    uint32_t visible_width;
    uint32_t visible_height;
    uint32_t pixel_format;
    uint32_t bit_depth;
    uint32_t color_primaries;
    uint32_t color_transfer;
    uint32_t color_matrix;
    uint32_t color_range;
    uint32_t chroma_location;
    uint32_t object_count;
    uint32_t layer_count;
    uint32_t flags;
    struct t1_media_frame_object objects[T1_MEDIA_MAX_FRAME_OBJECTS];
    struct t1_media_frame_layer layers[T1_MEDIA_MAX_FRAME_LAYERS];
};

struct T1_MEDIA_PACKED t1_media_release {
    uint64_t frame_id;
    uint32_t flags;
    uint32_t reserved;
};

struct T1_MEDIA_PACKED t1_media_backpressure {
    uint32_t state;
    uint32_t in_flight_frames;
};

struct T1_MEDIA_PACKED t1_media_result {
    uint32_t status;
    uint32_t reserved;
};

struct T1_MEDIA_PACKED t1_media_error {
    uint32_t status;
    uint32_t detail_size;
    /* Exactly detail_size bytes follow, without a trailing NUL. */
};

#if defined(_MSC_VER)
#pragma pack(pop)
#endif

#undef T1_MEDIA_PACKED

#if defined(__cplusplus)
#define T1_MEDIA_LAYOUT_ASSERT(type, size) \
    static_assert(sizeof(type) == (size), "T1MD v1 " #type " layout changed")
#else
#define T1_MEDIA_LAYOUT_ASSERT(type, size) \
    _Static_assert(sizeof(struct type) == (size), \
                   "T1MD v1 " #type " layout changed")
#endif

T1_MEDIA_LAYOUT_ASSERT(t1_media_message_header, 40);
T1_MEDIA_LAYOUT_ASSERT(t1_media_hello, 24);
T1_MEDIA_LAYOUT_ASSERT(t1_media_capability_profile, 32);
T1_MEDIA_LAYOUT_ASSERT(t1_media_capabilities, 1696);
T1_MEDIA_LAYOUT_ASSERT(t1_media_create, 100);
T1_MEDIA_LAYOUT_ASSERT(t1_media_created, 16);
T1_MEDIA_LAYOUT_ASSERT(t1_media_decode, 32);
T1_MEDIA_LAYOUT_ASSERT(t1_media_decode_done, 8);
T1_MEDIA_LAYOUT_ASSERT(t1_media_frame_object, 16);
T1_MEDIA_LAYOUT_ASSERT(t1_media_frame_plane, 16);
T1_MEDIA_LAYOUT_ASSERT(t1_media_frame_layer, 80);
T1_MEDIA_LAYOUT_ASSERT(t1_media_frame, 312);
T1_MEDIA_LAYOUT_ASSERT(t1_media_release, 16);
T1_MEDIA_LAYOUT_ASSERT(t1_media_backpressure, 8);
T1_MEDIA_LAYOUT_ASSERT(t1_media_result, 8);
T1_MEDIA_LAYOUT_ASSERT(t1_media_error, 8);

#undef T1_MEDIA_LAYOUT_ASSERT

#endif /* T1_MEDIA_DECODE_PROTOCOL_H */
